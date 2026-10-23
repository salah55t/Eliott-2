#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fe170.py — اختبارات FE1.7.0: بوابات جودة القبول + حماية الأوامر الحقيقية + حراسات التصفير

الخلفية الحية (أول ساعات التداول الفعلي بعد FE1.6.2):
  • 8/9 إشارات مُنشأة كانت بسعر سوق أعلى من منطقة الدخول (+1.1% إلى +4.3%) —
    5 انتهت دون لمس (ملء 11% فقط) وتُعاد حرفيًا كل دورة (زومبي يقطس خانة).
  • UNI: TP=7.592 أقل من الإغلاق الحي 7.6 وP5=7.713 — شراء نمطٍ حقق هدفه.
  • التعرض الورقي النشط 134.9% من الرصيد (لا سقف) و4/4 لونجات مترابطة.
  • api_trades_cancel يقلب الـDB فقط للأوامر الحقيقية — أمر راكد يتيم على باينانس
    (نص اللوحة يعد بـ«إلغاء الأمر الفعلي» ولا يحدث).
  • فشل جلب الشموع لموضع مفتوح يُتخطى صامتًا — الوقف بلا فحص طوال الانقطاع.
  • POST /api/stats/reset يمحو كل شيء بلا تأكيد ولا أرشفة ولا حارس صفقات حقيقية.

الجولات:
  1) structure_fresh / on_symbol_cooldown / same_direction_active (وحدوي)
  2) بوابتا المطاردة وصلاحية الهدف في create_pending_signal (وحدوي + عدادات)
  3) سقوف التعرض الورقي في compute_quantity (تقليص/رفض/تعطيل)
  4) scan_cycle تكامليًا: الترتيب الجديد (حيوية ← تقادم ← تبريد ← احتلال ← عنقود ← سعة ← HTF)
  5) api_trades_cancel الحقيقي: إلغاء فعلي / فشل يُبقي المعلق / ملء جزئي يفتح + الورقي لم يُمس
  6) api_stats_reset: تأكيد 400 + منع 409 مع صفقات حقيقية + أرشفة وتقليم لآخر 3
  7) حارس انقطاع التغذية _open_outage_step (تنبيه بعد 3 + تكرار + تصفير بالنجاح)

تشغيل: pytest test_fe170.py -v   (من داخل مجلد المشروع)
"""

import json
import math

import pandas as pd
import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة (نفس عقد test_fe100)


# ─────────────────────────────────────────────────────────────────────────────
# تجهيزات
# ─────────────────────────────────────────────────────────────────────────────

class _StubFib:
    """فيبو وهمي يكفي حساب entry_zone (الإنتاج: P3 − 0.382×W3 للصاعد)."""
    def __init__(self):
        self.wave2_retrace_pct = 0.5
        self.wave4_retrace_pct = 0.3
        self.wave2_in_zone = True
        self.wave4_in_zone = True


class _StubValidation:
    def __init__(self):
        self.fib = _StubFib()


def make_setup(prices=None, p5_idx: int = 95, direction: str = "BULLISH"):
    """نافذة صاعدة قابلة للضبط مع fib وهمي.
    الافتراضي P=[90,100,100,115,104,108]: دخول = 115−0.382×15 = 109.27،
    SL = 89.9، ولا درج من السلّم يحقق TP_MIN_RR=0.5 فيبقى امتداد 1.618 = 116.18.
    إغلاق 110 يمر ببوابتي FE1.7.0: مطاردة +0.67% ≤ 1.5% والهدف 116.18 > max(110, P5=108)."""
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


def insert_sig(symbol="TEST/USDT", status="pending", is_real=0, direction="BULLISH",
               closed_at=None, notional=100.0, order_id=None):
    vnz.db.execute(
        "INSERT INTO signals (symbol, direction, strategy_name, status, entry_price, stop_loss,"
        " take_profit, quantity, notional_usdt, created_at, closed_at, is_real, order_id)"
        " VALUES (%s,%s,'Elliott_Fibonacci',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (symbol, direction, status, 106.0, 99.9, 115.0, 10.0, notional,
         vnz.utc_now_iso(), closed_at, is_real, order_id),
    )


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


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 1 — سقف عمر البنية / تبريد الرمز / عد العنقود
# ─────────────────────────────────────────────────────────────────────────────

class TestStructureFresh:

    def test_fresh_structure_passes(self):
        # P5 عند 95 من 100 شمعة → العمر 4 ≤ 12
        assert vnz.structure_fresh(make_setup(p5_idx=95), synth_df(110.0)) is True

    def test_old_structure_rejected(self):
        # P5 عند 60 من 100 → العمر 39 > 36 [FE1.8.6: السقف رُفع من 30] — بنية أثرية
        assert vnz.structure_fresh(make_setup(p5_idx=60), synth_df(110.0)) is False

    def test_disabled_via_zero(self, monkeypatch):
        monkeypatch.setattr(vnz, "MAX_STRUCTURE_AGE_BARS", 0)
        assert vnz.structure_fresh(make_setup(p5_idx=0), synth_df(110.0)) is True

    def test_failopen_on_broken_setup(self):
        class Broken:
            pivot_indices = None
        assert vnz.structure_fresh(Broken(), synth_df(110.0)) is True


class TestSymbolCooldown:

    def test_no_history_no_cooldown(self, clean_db):
        assert vnz.on_symbol_cooldown("TEST/USDT") is False

    def test_recent_expired_blocks(self, clean_db):
        insert_sig(status="expired", closed_at=vnz.utc_now_iso())
        assert vnz.on_symbol_cooldown("TEST/USDT") is True

    def test_recent_cancelled_blocks(self, clean_db):
        insert_sig(status="cancelled", closed_at=vnz.utc_now_iso())
        assert vnz.on_symbol_cooldown("TEST/USDT") is True

    def test_old_expired_passes(self, clean_db):
        insert_sig(status="expired", closed_at="2026-01-01T00:00:00Z")
        assert vnz.on_symbol_cooldown("TEST/USDT") is False

    def test_pending_does_not_count(self, clean_db):
        insert_sig(status="pending")
        assert vnz.on_symbol_cooldown("TEST/USDT") is False

    def test_open_does_not_count(self, clean_db):
        insert_sig(status="open")
        assert vnz.on_symbol_cooldown("TEST/USDT") is False

    def test_other_symbol_ignores(self, clean_db):
        insert_sig(symbol="AAA/USDT", status="expired", closed_at=vnz.utc_now_iso())
        assert vnz.on_symbol_cooldown("TEST/USDT") is False

    def test_disabled_via_zero(self, clean_db, monkeypatch):
        insert_sig(status="expired", closed_at=vnz.utc_now_iso())
        monkeypatch.setattr(vnz, "SYMBOL_COOLDOWN_SEC", 0)
        assert vnz.on_symbol_cooldown("TEST/USDT") is False


class TestClusterCount:

    def test_counts_same_direction_only(self, clean_db):
        for _ in range(3):
            insert_sig(direction="BULLISH", status="pending")
        insert_sig(direction="BEARISH", status="pending")
        assert vnz.same_direction_active("BULLISH") == 3
        assert vnz.same_direction_active("BEARISH") == 1

    def test_closed_not_counted(self, clean_db):
        insert_sig(direction="BULLISH", status="closed", closed_at=vnz.utc_now_iso())
        assert vnz.same_direction_active("BULLISH") == 0

    def test_counters_registered(self):
        for k in ("rejected_far_entry", "rejected_target_invalid", "rejected_old_structure",
                  "rejected_cooldown", "rejected_cluster", "rejected_exposure_cap"):
            assert k in vnz.scan_stats, f"عداد {k} مفقود من scan_stats"


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 2 — بوابتا المطاردة وصلاحية الهدف في create_pending_signal
# ─────────────────────────────────────────────────────────────────────────────

class TestCreatePendingGates:

    def test_chase_rejected(self, clean_db):
        # close 115 فوق الدخول 109.27 بـ5.24% > سقف 1.5% — الحالة الحية (8/9 مطاردة)
        with vnz.scan_stats_lock:
            vnz.scan_stats["rejected_far_entry"] = 0
        assert vnz.create_pending_signal("TEST/USDT", make_setup(), last_close=115.0) is False
        rows = clean_db.query("SELECT COUNT(*) AS n FROM signals")
        assert int(rows[0]["n"]) == 0, "مطاردة يجب ألا تُنشئ صفًا"
        assert vnz.scan_stats["rejected_far_entry"] == 1

    def test_chase_allows_near(self, clean_db):
        # close 110 = +0.67% فوق الدخول — داخل السقف
        assert vnz.create_pending_signal("TEST/USDT", make_setup(), last_close=110.0) is True
        row = clean_db.query("SELECT * FROM signals", one=True)
        assert row["status"] == "pending"

    def test_target_below_p5_rejected(self, clean_db):
        # P5=117 فوق الهدف 116.18 — النمط حقق امتداد 1.618 بالفعل (حالة UNI الحية)
        with vnz.scan_stats_lock:
            vnz.scan_stats["rejected_target_invalid"] = 0
        s = make_setup(prices=[90.0, 100.0, 100.0, 115.0, 104.0, 117.0])
        assert vnz.create_pending_signal("TEST/USDT", s, last_close=110.0) is False
        assert vnz.scan_stats["rejected_target_invalid"] == 1

    def test_target_below_live_close_rejected(self, clean_db, monkeypatch):
        # إغلاق حي 117 فوق الهدف 116.18 — نعطل المطاردة لعزل بوابة الهدف
        monkeypatch.setattr(vnz, "MAX_ENTRY_DISTANCE_PCT", 0)
        with vnz.scan_stats_lock:
            vnz.scan_stats["rejected_target_invalid"] = 0
        assert vnz.create_pending_signal("TEST/USDT", make_setup(), last_close=117.0) is False
        assert vnz.scan_stats["rejected_target_invalid"] == 1

    def test_last_close_zero_skips_gates(self, clean_db):
        # توافق النداءات القديمة: بلا سعر حي = بوابات إنشاء معطلة
        assert vnz.create_pending_signal("TEST/USDT", make_setup()) is True

    def test_chase_disabled_via_zero(self, clean_db, monkeypatch):
        # close 111 = +1.58% فوق الدخول (كانت سترفض مطاردة) — بتعطيل البوابة تمر،
        # والهدف 116.18 > max(111, P5=108) فتبقى بوابة الهدف راضية
        monkeypatch.setattr(vnz, "MAX_ENTRY_DISTANCE_PCT", 0)
        with vnz.scan_stats_lock:
            vnz.scan_stats["rejected_far_entry"] = 0
        assert vnz.create_pending_signal("TEST/USDT", make_setup(), last_close=111.0) is True
        assert vnz.scan_stats["rejected_far_entry"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 3 — سقوف التعرض الورقي في compute_quantity
# ─────────────────────────────────────────────────────────────────────────────

class TestPaperExposureCaps:

    def test_position_cap_shrinks_notional(self, clean_db):
        # مخاطرة 100$ على وقف 0.1 = 1000 وحدة = 100k$ → تُقلّص إلى 30% من 10k
        qty = vnz.compute_quantity("TEST/USDT", 100.0, 99.9)
        assert qty is not None
        assert 2999.0 <= qty * 100.0 <= 3000.0 + 1e-6

    def test_position_cap_disabled(self, clean_db, monkeypatch):
        monkeypatch.setattr(vnz, "PAPER_MAX_POSITION_PCT", 0)
        monkeypatch.setattr(vnz, "PAPER_MAX_TOTAL_PCT", 0)
        qty = vnz.compute_quantity("TEST/USDT", 100.0, 99.9)
        assert math.isclose(qty * (100.0 - 99.9), 100.0, rel_tol=0.01)

    def test_total_cap_rejects_when_no_room(self, clean_db):
        insert_sig(status="open", notional=9995.0)  # المتبقي 5$ < أدنى قيمة 10$
        with vnz.scan_stats_lock:
            vnz.scan_stats["rejected_exposure_cap"] = 0
        assert vnz.compute_quantity("TEST/USDT", 100.0, 99.0) is None
        assert vnz.scan_stats["rejected_exposure_cap"] == 1

    def test_total_cap_shrinks_to_remaining(self, clean_db):
        insert_sig(status="open", notional=8000.0)  # المتبقي 2000$
        qty = vnz.compute_quantity("TEST/USDT", 100.0, 99.9)
        assert qty is not None
        assert 1999.0 <= qty * 100.0 <= 2000.0 + 1e-6

    def test_real_rows_not_counted(self, clean_db):
        insert_sig(status="open", is_real=1, notional=9995.0)
        # الصفقة الحقيقية لا تستهلك التعرض الورقي
        assert vnz.compute_quantity("TEST/USDT", 100.0, 99.0) is not None


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 4 — scan_cycle تكامليًا بالترتيب الجديد
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def scan_env170(clean_db, monkeypatch):
    """عزل دورة المسح مع قاعدة حقيقية (التبريد/العنقود/السعة تستعلم DB فعلًا)."""
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


class TestScanCycle170:

    def test_old_structure_rejected(self, scan_env170, monkeypatch):
        _patch_scan(monkeypatch, make_setup(p5_idx=60))  # [FE1.8.6] العمر 39 > السقف الجديد 36
        vnz.scan_cycle()
        assert vnz.scan_stats["rejected_old_structure"] == 1
        assert int(scan_env170.query("SELECT COUNT(*) AS n FROM signals")[0]["n"]) == 0

    def test_cooldown_rejected(self, scan_env170, monkeypatch):
        insert_sig(status="expired", closed_at=vnz.utc_now_iso())
        _patch_scan(monkeypatch, make_setup())
        vnz.scan_cycle()
        assert vnz.scan_stats["rejected_cooldown"] == 1
        assert vnz.scan_stats["setups_bull_traded"] == 0

    def test_happy_path_creates_signal(self, scan_env170, monkeypatch):
        _patch_scan(monkeypatch, make_setup())  # دخول 109.27، هدف 116.18، P5=108
        vnz.scan_cycle()
        assert vnz.scan_stats["setups_bull_traded"] == 1
        row = scan_env170.query("SELECT * FROM signals", one=True)
        assert row["status"] == "pending"
        assert math.isclose(float(row["entry_price"]), 109.27, rel_tol=1e-6)

    def test_dead_premise_counts_before_busy(self, scan_env170, monkeypatch):
        # رمز عليه صفقة نشطة وفرضيته ماتة → العداد stale_premise لا symbol_busy
        insert_sig(status="open")
        _patch_scan(monkeypatch, make_setup(prices=[150.0, 165.0, 154.5, 177.0, 159.0, 168.0]),
                    last_close=110.0)
        vnz.scan_cycle()
        assert vnz.scan_stats["rejected_stale_premise"] == 1
        assert vnz.scan_stats["rejected_symbol_busy"] == 0

    def test_cluster_cap_blocks_fourth(self, scan_env170, monkeypatch):
        for i in range(3):
            insert_sig(symbol=f"SYM{i}/USDT", status="pending", direction="BULLISH")
        _patch_scan(monkeypatch, make_setup())
        vnz.scan_cycle()
        assert vnz.scan_stats["rejected_cluster"] == 1
        assert vnz.scan_stats["rejected_active_limit"] == 0, "السعة لم تمتلمئ — العنقود هو الرافض"

    def test_bearish_display_path_untouched(self, scan_env170, monkeypatch):
        _patch_scan(monkeypatch, make_setup(direction="BEARISH"))
        vnz.scan_cycle()
        assert vnz.scan_stats["setups_bull_traded"] == 0
        assert sum(v for k, v in vnz.scan_stats.items() if k.startswith("rejected_")) == 0


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 5 — إلغاء الأمر الحقيقي يمس المنصة فعلًا
# ─────────────────────────────────────────────────────────────────────────────

class TestCancelRealOrder:

    def _insert_real_pending(self, order_id="111"):
        insert_sig(status="pending", is_real=1, order_id=order_id)
        return vnz.db.query("SELECT * FROM signals", one=True)

    def test_real_pending_cancels_on_exchange(self, clean_db, monkeypatch):
        row = self._insert_real_pending()
        calls = {}
        monkeypatch.setattr(vnz, "binance_trade_exchange", lambda: object())

        def fake_cancel(ex, symbol, order_id):
            calls["args"] = (symbol, order_id)
            return True

        monkeypatch.setattr(vnz, "cancel_real_order", fake_cancel)
        monkeypatch.setattr(vnz, "fetch_real_order",
                            lambda ex, s, o: {"status": "canceled", "filled": 0, "average": 0})
        client = vnz.app.test_client()
        r = client.post("/api/trades/cancel", json={"id": int(row["id"])})
        assert r.status_code == 200 and r.get_json()["ok"] is True
        assert calls["args"] == ("TEST/USDT", "111"), "يجب أن يُستدعى إلغاء المنصة"
        assert clean_db.query("SELECT * FROM signals", one=True)["status"] == "cancelled"

    def test_real_cancel_failure_keeps_pending(self, clean_db, monkeypatch):
        # فشل إلغاء المنصة → لا تصفير زائف للـDB — الأمر حي ويعاد آليًا
        row = self._insert_real_pending()
        monkeypatch.setattr(vnz, "binance_trade_exchange", lambda: object())
        monkeypatch.setattr(vnz, "cancel_real_order", lambda ex, s, o: False)
        client = vnz.app.test_client()
        r = client.post("/api/trades/cancel", json={"id": int(row["id"])})
        assert r.status_code == 502
        assert clean_db.query("SELECT * FROM signals", one=True)["status"] == "pending"

    def test_real_cancel_partial_fill_opens(self, clean_db, monkeypatch):
        # ملء جزئي قبل الإلغاء → موضع مفتوح بكمية الملء (الحكم من المنصة)
        row = self._insert_real_pending()
        monkeypatch.setattr(vnz, "binance_trade_exchange", lambda: object())
        monkeypatch.setattr(vnz, "cancel_real_order", lambda ex, s, o: True)
        monkeypatch.setattr(vnz, "fetch_real_order",
                            lambda ex, s, o: {"status": "canceled", "filled": 5.0, "average": 109.5})
        client = vnz.app.test_client()
        r = client.post("/api/trades/cancel", json={"id": int(row["id"])})
        assert r.status_code == 200
        after = clean_db.query("SELECT * FROM signals", one=True)
        assert after["status"] == "open"
        assert float(after["quantity"]) == 5.0

    def test_paper_cancel_untouched_by_exchange(self, clean_db, monkeypatch):
        insert_sig(status="pending", is_real=0)
        row = clean_db.query("SELECT * FROM signals", one=True)
        touched = {"n": 0}

        def _spy():
            touched["n"] += 1
            return object()

        monkeypatch.setattr(vnz, "binance_trade_exchange", _spy)
        client = vnz.app.test_client()
        r = client.post("/api/trades/cancel", json={"id": int(row["id"])})
        assert r.status_code == 200
        assert touched["n"] == 0, "الورقي لا يمس المنصة"
        assert clean_db.query("SELECT * FROM signals", one=True)["status"] == "cancelled"


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 6 — حراسات التصفير الثلاثية
# ─────────────────────────────────────────────────────────────────────────────

class TestStatsResetGuards:

    def test_requires_explicit_confirm(self, clean_db):
        insert_sig(status="pending")
        client = vnz.app.test_client()
        assert client.post("/api/stats/reset").status_code == 400
        assert client.post("/api/stats/reset", json={}).status_code == 400
        assert client.post("/api/stats/reset", json={"confirm": "nope"}).status_code == 400
        assert int(clean_db.query("SELECT COUNT(*) AS n FROM signals")[0]["n"]) == 1

    def test_confirm_via_query_param(self, clean_db):
        client = vnz.app.test_client()
        assert client.post("/api/stats/reset?confirm=RESET").status_code == 200

    def test_refuses_active_real_trades(self, clean_db):
        insert_sig(status="pending", is_real=1, order_id="9")
        client = vnz.app.test_client()
        r = client.post("/api/stats/reset", json={"confirm": "RESET"})
        assert r.status_code == 409
        assert int(clean_db.query("SELECT COUNT(*) AS n FROM signals")[0]["n"]) == 1

    def test_archives_before_delete(self, clean_db):
        insert_sig(status="expired", closed_at=vnz.utc_now_iso())
        client = vnz.app.test_client()
        r = client.post("/api/stats/reset", json={"confirm": "RESET"})
        assert r.status_code == 200
        assert int(clean_db.query("SELECT COUNT(*) AS n FROM signals")[0]["n"]) == 0
        keys = [x["key"] for x in
                clean_db.query("SELECT key FROM bot_state WHERE key LIKE 'stats_archive_%'")]
        assert len(keys) == 1
        archived = json.loads(
            clean_db.query("SELECT value FROM bot_state WHERE key = %s", (keys[0],), one=True)["value"])
        assert archived[0]["symbol"] == "TEST/USDT"

    def test_archive_pruned_to_last_three(self, clean_db):
        for i in range(5):
            vnz.db_set_state(f"stats_archive_000{i}", "[]")
        client = vnz.app.test_client()
        r = client.post("/api/stats/reset", json={"confirm": "RESET"})
        assert r.status_code == 200
        keys = [x["key"] for x in clean_db.query(
            "SELECT key FROM bot_state WHERE key LIKE 'stats_archive_%' ORDER BY key DESC")]
        assert len(keys) == 3
        # الأحدث يبقى أولًا (مفتاحه بتاريخ اليوم > مفاتيح 000i)


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 7 — حارس انقطاع التغذية للمواضع المفتوحة
# ─────────────────────────────────────────────────────────────────────────────

class TestOpenOutageGuard:

    @pytest.fixture()
    def notified(self, monkeypatch):
        seen = []
        monkeypatch.setattr(vnz, "log_and_notify",
                            lambda level, msg, ntype="INFO": seen.append((level, ntype, msg)))
        monkeypatch.setattr(vnz, "OUTAGE_ALERT_AFTER_CYCLES", 3)
        monkeypatch.setattr(vnz, "OUTAGE_RENOTIFY_SEC", 0.0)
        vnz._open_outage.clear()
        return seen

    def test_alert_after_three_failures(self, notified):
        vnz._open_outage_step("AVAX/USDT", True)
        vnz._open_outage_step("AVAX/USDT", True)
        assert notified == []
        vnz._open_outage_step("AVAX/USDT", True)
        assert len(notified) == 1
        assert "AVAX/USDT" in notified[0][2]
        assert notified[0][0] == "error"

    def test_renotify_each_cycle_after_threshold(self, notified):
        for _ in range(6):
            vnz._open_outage_step("AVAX/USDT", True)
        assert len(notified) == 4  # الدورات 3-6 (RENOTIFY=0)

    def test_success_resets_counter(self, notified):
        vnz._open_outage_step("AVAX/USDT", True)
        vnz._open_outage_step("AVAX/USDT", True)
        vnz._open_outage_step("AVAX/USDT", False)  # نجاح — صفّر
        vnz._open_outage_step("AVAX/USDT", True)
        vnz._open_outage_step("AVAX/USDT", True)
        assert notified == []
        vnz._open_outage_step("AVAX/USDT", True)
        assert len(notified) == 1

    def test_symbols_independent(self, notified):
        for _ in range(3):
            vnz._open_outage_step("AVAX/USDT", True)
        vnz._open_outage_step("BAT/USDT", True)
        vnz._open_outage_step("BAT/USDT", True)
        assert len(notified) == 1


# ─────────────────────────────────────────────────────────────────────────────
# الإصدار
# ─────────────────────────────────────────────────────────────────────────────

def test_version_fe170():
    import panel
    assert vnz.BOT_VERSION == "EL2.2.0"
    assert panel.BOT_VERSION == "EL2.2.0"
