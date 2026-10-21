#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fe189.py — اختبارات FE1.8.9: تبديل فريم الكشف/التنفيذ حيًا من اللوحة (5m/15m/1h/4h)

الطلب الحي (المستخدم):
  «كيف اجعل فريم الفحص 5 دقائق بدلا من 15 دون تعديل الكود او ادرج الية لتعديل
   فريم التداول الى 5 و15 وساعة واربع ساعات يمكن التبديل من لوحة التحكم»

الجواب المزدوج:
  1) دون تعديل كود: SIGNAL_TIMEFRAME / ENTRY_TIMEFRAME env جاهزان أصلًا (لوحة Render)
  2) الميزة الجديدة: POST /api/config/timeframe + أزرار اللوحة — تبديل حي محفوظ

التصميم المحصَّن (كل بند له اختبار):
  • التبديل إعادة تهيئة نظيفة لا تغيير رقم حي: إلغاء الورقي المعلق بسبب
    «تبديل الفريم» + إعادة بناء الكاشف (يحمل عتبة الانعكاس عند الإنشاء)
    + مسح أسباب الرفض القديمة + حفظ في قاعدة الحالة + إيقاظ الكشف فورًا
  • إلغاءات التبديل مستثناة من تبريد الرموز — وإلا لعُقت الرموز كلها 90 دقيقة
    بعد كل تبديل بلا ذنب (فخ منطقي قُتل في المهاد)
  • رفض التبديل مع أمر حقيقي معلق — لا إلغاء صامت لأوامر مالية
  • القيم المسموحة فقط 5m/15m/1h/4h — غير ذلك 400
  • الاسترجاع عند الإقلاع: المحفوظ يُطبق، غير المسموح يُهمَل بأمان

تشغيل: pytest test_fe189.py -v   (من داخل مجلد المشروع)
"""

import sqlite3

import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة (نفس عقد test_fe100/185)


# ─────────────────────────────────────────────────────────────────────────────
# تجهيزات (نفس عقد test_fe140/185)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    """قاعدة SQLite مؤقتة لكل اختبار — عزل كامل."""
    monkeypatch.setattr(vnz, "USE_POSTGRES", False)
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    old = vnz.db.conn
    vnz.db.conn = conn
    vnz.init_db()
    vnz.set_paper_balance(vnz.PAPER_BALANCE_START)
    yield vnz.db
    vnz.db.conn = old


@pytest.fixture()
def tf_reset():
    """إعادة الفريمين والكاشف إلى حالة env الأصلية حول كل اختبار — بلا تسرب حالة."""
    sig0, ent0, det0 = vnz.SIGNAL_TIMEFRAME, vnz.ENTRY_TIMEFRAME, vnz.detector
    yield
    vnz.SIGNAL_TIMEFRAME, vnz.ENTRY_TIMEFRAME = sig0, ent0
    vnz.detector = det0


def insert_signal(symbol="TEST/USDT", status="pending", is_real=0, close_reason=None):
    vnz.db.execute(
        "INSERT INTO signals (symbol, direction, strategy_name, status, entry_price,"
        " created_at, closed_at, close_reason, is_real)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (symbol, "BULLISH", vnz.STRATEGY_NAME, status, 100.0,
         vnz.utc_now_iso(), (vnz.utc_now_iso() if status in ("cancelled", "expired", "closed") else None),
         close_reason, is_real),
    )
    return vnz.db.query("SELECT last_insert_rowid() AS id")[0]["id"]


# ─────────────────────────────────────────────────────────────────────────────
# 1) التطبيع والقيم المسموحة
# ─────────────────────────────────────────────────────────────────────────────

def test_norm_tf_accepts_allowed_and_rejects_rest():
    assert vnz._norm_tf("5m") == "5m"
    assert vnz._norm_tf(" 4H ") == "4h"          # تطبيع حالة + مسافات
    assert vnz._norm_tf("1h") == "1h"
    assert vnz._norm_tf("15M") == "15m"
    assert vnz._norm_tf("2h") is None            # موجود في TF_SECONDS لكنه غير مسموح للوحة
    assert vnz._norm_tf("1d") is None
    assert vnz._norm_tf("banana") is None
    assert vnz._norm_tf("") is None
    assert vnz._norm_tf(None) is None


def test_allowed_tfs_and_tf_seconds_consistent():
    assert set(vnz.ALLOWED_TFS) == {"5m", "15m", "1h", "4h"}
    for tf in vnz.ALLOWED_TFS:
        assert vnz.TF_SECONDS.get(tf), f"{tf} غائب عن TF_SECONDS — صلاحية المعلق والنوم سينكسران"


# ─────────────────────────────────────────────────────────────────────────────
# 2) apply_timeframes — البوابة والنتائج
# ─────────────────────────────────────────────────────────────────────────────

def test_apply_rejects_disallowed(clean_db, tf_reset):
    sig0, ent0 = vnz.SIGNAL_TIMEFRAME, vnz.ENTRY_TIMEFRAME
    ok, msg = vnz.apply_timeframes("7m", "5m", source="اختبار")
    assert not ok
    assert "غير مسموح" in msg
    ok, msg = vnz.apply_timeframes("5m", "1d", source="اختبار")
    assert not ok
    # الحالة لم تُمس إطلاقًا
    assert vnz.SIGNAL_TIMEFRAME == sig0 and vnz.ENTRY_TIMEFRAME == ent0


def test_apply_same_values_is_noop(clean_db, tf_reset):
    vnz._scan_kick.clear()
    cur_sig, cur_ent = vnz.SIGNAL_TIMEFRAME, vnz.ENTRY_TIMEFRAME
    ok, msg = vnz.apply_timeframes(cur_sig, cur_ent, source="اختبار")
    assert not ok
    assert "مُطبق أصلًا" in msg
    assert not vnz._scan_kick.is_set()      # بلا إيقاظ — لا إبطال داعي
    assert vnz.SIGNAL_TIMEFRAME == cur_sig


def test_apply_switches_and_persists_and_kicks(clean_db, tf_reset):
    vnz._scan_kick.clear()
    vnz._detect_kick.clear()
    old_det = vnz.detector
    ok, msg = vnz.apply_timeframes("4h", "4h", source="اختبار")
    assert ok
    assert vnz.SIGNAL_TIMEFRAME == "4h"
    assert vnz.ENTRY_TIMEFRAME == "4h"
    assert vnz.detector is not old_det      # الكاشف أعيد بناؤه (عتبة مثبتة عند الإنشاء)
    assert vnz.db_get_state("signal_timeframe", "") == "4h"   # يصمد عبر إعادة النشر
    assert vnz.db_get_state("entry_timeframe", "") == "4h"
    assert vnz._scan_kick.is_set() and vnz._detect_kick.is_set()  # أول دورة خلال ثوانٍ
    assert "15m" in msg                     # الرسالة تعرض القديم ← الجديد


def test_apply_cancels_paper_pending_with_tf_reason(clean_db, tf_reset):
    sid = insert_signal(status="pending", is_real=0)
    ok, msg = vnz.apply_timeframes("1h", "1h", source="اختبار")
    assert ok
    row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sid,))[0]
    assert row["status"] == "cancelled"
    assert row["close_reason"].startswith("تبديل الفريم")   # البصمة التي تستثنيه من التبريد
    assert "أُلغي 1" in msg


def test_apply_refuses_with_real_pending(clean_db, tf_reset):
    sid = insert_signal(status="pending", is_real=1)
    old_sig = vnz.SIGNAL_TIMEFRAME
    ok, msg = vnz.apply_timeframes("5m", "5m", source="اختبار")
    assert not ok
    assert "حقيقي" in msg
    row = vnz.db.query("SELECT status FROM signals WHERE id=%s", (sid,))[0]
    assert row["status"] == "pending"       # لا إلغاء صامت لأوامر مالية
    assert vnz.SIGNAL_TIMEFRAME == old_sig  # لا تغيير حي


def test_apply_clears_old_reject_reasons(clean_db, tf_reset):
    vnz._set_reject_reason("ABC/USDT", "بنية متقادمة — عمر P5 40 شمعة")
    vnz.apply_timeframes("4h", "4h", source="اختبار")
    assert vnz._get_reject_reason("ABC/USDT") == ""   # محسوبة على فريم لم يعد معتمدًا


# ─────────────────────────────────────────────────────────────────────────────
# 3) تبريد الرموز — استثناء إلغاءات تبديل الفريم (الفخ المنطقي)
# ─────────────────────────────────────────────────────────────────────────────

def test_cooldown_ignores_tf_switch_cancellations(clean_db):
    insert_signal(status="cancelled", close_reason="تبديل الفريم إلى 1h/1h (اختبار)")
    assert vnz.on_symbol_cooldown("TEST/USDT") is False  # التبديل لا يعقّ الرموز 90 دقيقة


def test_cooldown_still_punishes_manual_cancel(clean_db):
    insert_signal(status="cancelled", close_reason="إلغاء يدوي من اللوحة")
    assert vnz.on_symbol_cooldown("TEST/USDT") is True   # الحماية الأصلية سليمة


def test_cooldown_still_punishes_expired(clean_db):
    insert_signal(status="expired", close_reason=None)
    assert vnz.on_symbol_cooldown("TEST/USDT") is True


# ─────────────────────────────────────────────────────────────────────────────
# 4) الاسترجاع عند الإقلاع
# ─────────────────────────────────────────────────────────────────────────────

def test_restore_applies_saved_timeframes(clean_db, tf_reset):
    vnz.db_set_state("signal_timeframe", "4h")
    vnz.db_set_state("entry_timeframe", "4h")
    vnz.SIGNAL_TIMEFRAME = "15m"
    vnz.restore_timeframe_flags()
    assert vnz.SIGNAL_TIMEFRAME == "4h" and vnz.ENTRY_TIMEFRAME == "4h"


def test_restore_ignores_disallowed_saved_values(clean_db, tf_reset):
    vnz.db_set_state("signal_timeframe", "2h")   # موجودة في TF_SECONDS لكنها غير مسموحة للوحة
    vnz.db_set_state("entry_timeframe", "banana")
    vnz.SIGNAL_TIMEFRAME = "15m"
    vnz.restore_timeframe_flags()
    assert vnz.SIGNAL_TIMEFRAME == "15m"          # أُهملت بأمان وتبقت قيم env


def test_restore_with_empty_state_keeps_env(clean_db, tf_reset):
    vnz.SIGNAL_TIMEFRAME = "15m"
    vnz.restore_timeframe_flags()                 # قاعدة بلا مفاتيح فريم — لا شيء يتغير
    assert vnz.SIGNAL_TIMEFRAME == "15m"


# ─────────────────────────────────────────────────────────────────────────────
# 5) نقطة النهاية
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def client(clean_db, tf_reset):
    vnz.app.config["TESTING"] = True
    with vnz.app.test_client() as c:
        yield c


def test_endpoint_rejects_disallowed_preset(client):
    r = client.post("/api/config/timeframe", json={"preset": "7m"})
    assert r.status_code == 400
    assert "غير مسموح" in r.get_json()["error"]


def test_endpoint_preset_switch_end_to_end(client):
    sid = insert_signal(status="pending", is_real=0)
    r = client.post("/api/config/timeframe", json={"preset": "5m"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["signal_timeframe"] == "5m" and body["entry_timeframe"] == "5m"
    assert body["allowed_tfs"] == ["5m", "15m", "1h", "4h"]
    row = vnz.db.query("SELECT status, close_reason FROM signals WHERE id=%s", (sid,))[0]
    assert row["status"] == "cancelled"
    assert vnz.db_get_state("signal_timeframe", "") == "5m"


def test_endpoint_same_preset_returns_ok_noop(client):
    r = client.post("/api/config/timeframe", json={"preset": vnz.SIGNAL_TIMEFRAME})
    assert r.status_code == 200
    assert "مُطبق أصلًا" in r.get_json()["message"]


def test_endpoint_real_pending_conflict_409(client):
    insert_signal(status="pending", is_real=1)
    r = client.post("/api/config/timeframe", json={"preset": "4h"})
    assert r.status_code == 409
    assert "حقيقي" in r.get_json()["error"]


def test_endpoint_separate_signal_entry(client):
    r = client.post("/api/config/timeframe", json={"signal_tf": "1h", "entry_tf": "5m"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["signal_timeframe"] == "1h" and body["entry_timeframe"] == "5m"


# ─────────────────────────────────────────────────────────────────────────────
# 6) /api/all يعرض الفريم الحي للوحة
# ─────────────────────────────────────────────────────────────────────────────

def test_api_all_exposes_timeframes(client):
    client.post("/api/config/timeframe", json={"preset": "1h"})
    d = client.get("/api/all").get_json()
    assert d["signal_timeframe"] == "1h"
    assert d["allowed_tfs"] == ["5m", "15m", "1h", "4h"]
