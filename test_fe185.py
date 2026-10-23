#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fe185.py — اختبارات FE1.8.6: شفافية فشل اتصال باينانس + معايرة عمر البنية

الشكوى الحية (المستخدم):
  «فشل الاتصال بباينانس تظهر في اللوحة ولا يظهر أي شيء في اللوج ولا وجود لتوصيات»

الجذر:
  • binance_status_snapshot يبتلع استثناء الفشل في data["error"] بصمت —
    بطاقة اللوحة تعرض «فشل الاتصال» لكن لا إشعارًا في السجل إطلاقًا (السجل =
    جدول notifications)، ولا تُعرض تفاصيل الخطأ في اللوحة أصلًا.
  • إثبات حي: حظر باينانس -1003 (429) أصاب فحص الكون 12:00:59Z وعاد في 12:31 —
    بطاقة اللوحة احمرّت في النافذة بلا أي سطر في اللوج.
  • عدادات FE1.8.4 الحية: rejected_old_structure=43 (كلها مرت بوابة الفرضية
    الحية أولًا — الترتيب premise ثم fresh) مقابل صفر رفض جودة — السقف 30
    ما زال يمنع بنيات حية الفرضية عمرها 31-36 شمعة.

الإصلاح:
  1) _binance_conn_notify: إشعار انتقال الحالة (فشل ← warning، عودة ← info)
     + تذكير كل BIN_CONN_RENOTIFY_SEC أثناء استمرار الفشل — بلا إغراق.
  2) بطاقة/شارة اللوحة تعرض نص الخطأ الحقيقي (مقطوعًا 90 حرفًا).
  3) حكم التقادم يعرض عمر P5 الفعلي (معايرة حية) + سقف 36 شمعة (9س) بدل 30.

الجولات:
  1) إشعارات انتقال الاتصال (وحدوي + تكامل السنابشوت)
  2) عمر P5 في حكم التقادم + الحد الجديد 36
  3) النشر والحراسات الجوهرية

تشغيل: pytest test_fe185.py -v   (من داخل مجلد المشروع)
"""

import pandas as pd
import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة (نفس عقد test_fe100)


# ─────────────────────────────────────────────────────────────────────────────
# تجهيزات (نفس عقد test_fe170/184)
# ─────────────────────────────────────────────────────────────────────────────

class _StubFib:
    def __init__(self):
        self.wave2_retrace_pct = 0.5
        self.wave4_retrace_pct = 0.3
        self.wave2_in_zone = True
        self.wave4_in_zone = True


class _StubValidation:
    def __init__(self):
        self.fib = _StubFib()


def make_setup(prices=None, p5_idx: int = 95, direction: str = "BULLISH"):
    from engine.pattern_detector import DetectedSetup
    P = prices or [90.0, 100.0, 100.0, 115.0, 104.0, 108.0]
    return DetectedSetup(
        symbol="TEST/USDT", timeframe="15m", direction=direction,
        pivot_indices=[0, 10, 20, 30, 40, p5_idx],
        pivot_timestamps=[pd.Timestamp("2026-01-01", tz="UTC")] * 6,
        pivot_prices=P,
        validation_result=_StubValidation(),
        detected_at=pd.Timestamp("2026-01-01", tz="UTC"),
    )


def synth_df(last_close: float, n: int = 100) -> pd.DataFrame:
    vals = [last_close] * n
    return pd.DataFrame({"close": vals, "open": vals, "high": vals,
                         "low": vals, "volume": [1.0] * n})


@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    """قاعدة SQLite مؤقتة لكل اختبار — نفس عقد test_fe100."""
    monkeypatch.setattr(vnz, "USE_POSTGRES", False)
    import sqlite3
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    old = vnz.db.conn
    vnz.db.conn = conn
    vnz.init_db()
    vnz.set_paper_balance(vnz.PAPER_BALANCE_START)
    yield vnz.db
    vnz.db.conn = old


@pytest.fixture()
def bin_conn(clean_db):
    """كاش حالة الاتصال نظيف حول كل اختبار + قاعدة إشعارات حقيقية."""
    vnz._bin_status_cache.update(
        {"ts": 0.0, "data": None, "last_connected": None, "last_notify": 0.0})
    yield vnz._bin_status_cache
    vnz._bin_status_cache.update(
        {"ts": 0.0, "data": None, "last_connected": None, "last_notify": 0.0})


def _notif_n(like: str) -> int:
    rows = vnz.db.query(
        "SELECT COUNT(*) AS n FROM notifications WHERE message LIKE %s", (f"%{like}%",))
    return int(rows[0]["n"]) if rows else 0


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 1 — إشعارات انتقال اتصال باينانات (لا صمت بعد اليوم)
# ─────────────────────────────────────────────────────────────────────────────

class TestBinanceConnNotify:

    def test_first_failure_notifies(self, bin_conn):
        # أول فشل → إشعار warning في السجل بنص الخطأ الحقيقي
        vnz._binance_conn_notify(False, "binance {\"code\":-1003,\"msg\":\"Too much request\"}")
        assert _notif_n("فشل اتصال باينانس") == 1
        assert _notif_n("-1003") == 1
        assert bin_conn["last_connected"] is False

    def test_repeated_failure_no_spam(self, bin_conn):
        # فشل متكرر داخل نافذة التذكير → لا إشعار إضافي (بلا إغراق مع تحديث اللوحة)
        vnz._binance_conn_notify(False, "boom")
        vnz._binance_conn_notify(False, "boom")
        vnz._binance_conn_notify(False, "boom")
        assert _notif_n("فشل اتصال باينانس") == 1

    def test_persistent_failure_renotifies(self, bin_conn, monkeypatch):
        # فشل مستمر تجاوز BIN_CONN_RENOTIFY_SEC → تذكير جديد
        monkeypatch.setattr(vnz, "BIN_CONN_RENOTIFY_SEC", 600.0)
        vnz._binance_conn_notify(False, "down")
        bin_conn["last_notify"] = vnz._bin_status_cache["last_notify"] - 700.0
        vnz._binance_conn_notify(False, "down")
        assert _notif_n("فشل اتصال باينانس") == 2

    def test_recovery_notifies(self, bin_conn):
        # فشل ثم عودة → إشعار عودة info
        vnz._binance_conn_notify(False, "boom")
        vnz._binance_conn_notify(True)
        assert _notif_n("عاد إلى العمل") == 1
        assert bin_conn["last_connected"] is True

    def test_stable_connected_no_noise(self, bin_conn):
        # اتصال مستقر متكرر → لا إشعارات إطلاقًا
        vnz._binance_conn_notify(True)
        vnz._binance_conn_notify(True)
        vnz._binance_conn_notify(True)
        assert _notif_n("عاد إلى العمل") == 0
        assert _notif_n("فشل اتصال") == 0

    def test_snapshot_failure_reaches_log(self, bin_conn, monkeypatch):
        # تكامل: فشل probe السنابشوت → data.error + إشعار في السجل (عقد الشكوى نفسه)
        def _boom():
            raise RuntimeError("اتصال باينانس فشل — شبكة ميتة")
        monkeypatch.setattr(vnz, "_binance_public_probe", _boom)
        snap = vnz.binance_status_snapshot(force=True)
        assert snap["connected"] is False
        assert "شبكة ميتة" in (snap["error"] or "")
        assert _notif_n("فشل اتصال باينانس") == 1
        assert _notif_n("شبكة ميتة") == 1

    def test_notify_never_raises(self, bin_conn, monkeypatch):
        # إشعار الاتصال لا يُسقط اللوحة أبدًا — حتى لو انفجر log_and_notify
        def _explode(*a, **k):
            raise RuntimeError("notification sink dead")
        monkeypatch.setattr(vnz, "log_and_notify", _explode)
        vnz._binance_conn_notify(False, "x")   # يجب ألا يرفع استثناء
        vnz._binance_conn_notify(True)


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 2 — عمر P5 في حكم التقادم + السقف 36
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def scan_env(clean_db, monkeypatch):
    """عزل دورة المسح مع قاعدة حقيقية — نفس عقد scan_env170/184."""
    monkeypatch.setattr(vnz, "watchlist", ["TEST/USDT"])
    monkeypatch.setattr(vnz, "INTER_SYMBOL_SLEEP", 0.0)
    monkeypatch.setattr(vnz, "is_trading_enabled", True)
    monkeypatch.setattr(vnz, "HTF_BIAS_ENABLED", False)
    with vnz.scan_stats_lock:
        for k in vnz.scan_stats:
            vnz.scan_stats[k] = 0
    return clean_db


def _patch_scan(monkeypatch, setup, last_close=110.0):
    monkeypatch.setattr(vnz, "fetch_ohlcv_df",
                        lambda s, tf, limit=500, min_candles=0: synth_df(last_close))
    monkeypatch.setattr(vnz.detector, "scan", lambda df: [setup])


class TestAgeVerdictAndCeiling:

    def test_new_ceiling_36(self):
        assert vnz.MAX_STRUCTURE_AGE_BARS == 36   # [FE1.8.6] بدل 30 (9س على 15m)

    def test_renotify_constant(self):
        assert vnz.BIN_CONN_RENOTIFY_SEC == 600.0

    def test_boundary_36_37(self, monkeypatch):
        monkeypatch.setattr(vnz, "MAX_STRUCTURE_AGE_BARS", 36)
        df = [{"close": 1.0}] * 101
        assert vnz.structure_fresh(make_setup(p5_idx=64), df) is True   # 100-64=36
        assert vnz.structure_fresh(make_setup(p5_idx=63), df) is False  # 100-63=37

    def test_verdict_shows_actual_age(self, scan_env, monkeypatch):
        # حكم التقادم يعرض العمر الفعلي — معايرة حية بدل «تجاوز السقف» العمياء
        # df=100 شمعة، P5 عند 60 → العمر 39 > 36
        _patch_scan(monkeypatch, make_setup(p5_idx=60))
        vnz.scan_cycle()
        assert vnz.scan_stats["rejected_old_structure"] == 1
        verdict = vnz._get_reject_reason("TEST/USDT")
        assert "عمر P5 39" in verdict
        assert "السقف 36" in verdict

    def test_age_35_now_passes_to_next_gate(self, scan_env, monkeypatch):
        # عمر 35 ≤ 36 كان مرفوضًا على FE1.8.4 — اليوم يمر لبوابات الإنشاء
        # (هنا يفشل على المطاردة/rr_net حسب الأسعار — المهم ليس حكم تقادم)
        _patch_scan(monkeypatch, make_setup(p5_idx=64))   # 99-64=35
        vnz.scan_cycle()
        assert vnz.scan_stats["rejected_old_structure"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 3 — النشر والحراسات الجوهرية
# ─────────────────────────────────────────────────────────────────────────────

class TestDeploymentAndBoundaries:

    def test_version_bumped_everywhere(self):
        import panel
        assert vnz.BOT_VERSION == "EL2.3.0"
        assert panel.BOT_VERSION == "EL2.3.0"

    def test_panel_shows_real_error(self):
        # بطاقة اللوحة تعرض نص الخطأ الحقيقي بجوار «فشل الاتصال»
        src = open("panel.py", encoding="utf-8").read()
        assert "bnErr" in src and "bn.error" in src

    def test_render_yaml_carries_values(self):
        import pathlib
        y = pathlib.Path("render.yaml").read_text(encoding="utf-8")
        assert 'value: "36"' in y          # MAX_STRUCTURE_AGE_BARS [FE1.8.6]
        assert 'value: "30"' in y          # SCAN_TOP_N (من FE1.8.4)
        assert 'value: "2700"' in y        # IDLE_RESCAN_MIN_GAP_SEC

    def test_premise_gate_untouched(self):
        dead = make_setup(prices=[150.0, 165.0, 154.5, 177.0, 159.0, 168.0])
        alive = make_setup()
        assert vnz.premise_alive(dead, 110.0) is False
        assert vnz.premise_alive(alive, 110.0) is True
        assert vnz.premise_alive(dead, None) is True   # fail-open

    def test_quality_gates_values_untouched(self):
        assert vnz.MAX_ENTRY_DISTANCE_PCT == 1.5      # لا مطاردة
        assert vnz.RR_NET_MIN == 0.3                  # أرضية R:R الصافي
        assert vnz.SYMBOL_COOLDOWN_SEC == 5400.0      # تبريد الرمز
        assert vnz.PENDING_MAX_CANDLES == 6           # صلاحية المعلق
        assert vnz.CLUSTER_MAX_SAME_DIRECTION == 3    # سقف العنقود
        assert vnz.KEEP_ALIVE_INTERVAL_SEC == 60.0    # نبضة الدقيقة
        assert vnz.SCAN_TOP_N == 30                   # قائمة FE1.8.4
        assert vnz.IDLE_RESCAN_MIN_GAP_SEC == 2700.0  # إعجال FE1.8.4
