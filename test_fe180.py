#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fe180.py — اختبارات FE1.8.0: حماية الموضع (وقف راكن + BE@1R + جزئي + قاطع مخاطر + rr_net)

الخلفية: الوقف كان في الذاكرة فقط (لا أمر STOP راكن على المنصة) — نشر/انقطاع = موضع
مكشوف. لا آلية لقفل الربح بعد تحقق جزء من الفرضية. الورقي كان يعرض R:R إجماليًا
تأكل الرسوم منه نسبة معتبرة. ولا سقف خسارة يومي ولا قاطع متتاليات.

الجولات:
  1) rr_net_value (حساب صافي بعد رسوم الاتجاهين) + بوابة RR_NET_MIN في create_pending_signal
  2) قاطع المخاطر: حد الخسارة اليومي + متتاليات الخسارة + التعافي + تصفير المتتالية بالربح
  3) الحماية الورقية: ملء يثبت initial_quantity، BE@1R، جزئي 50%، محاسبة بلا ازدواج،
     وقف-أولًا داخل الشمعة (لا حماية إن لمس الشمعة الوقف)
  4) الوقف الراكن الحقيقي: يُرفع بعد الملء (STOP_LOSS_LIMIT على المنصة)، الإغلاق يلغيه
     أولًا، نُفذ على المنصة → محاسبة من سعر التنفيذ بلا بيع مزدوج، الغبار لا يرفع أمرًا
  5) المصالقة: نُفذ → إغلاق محاسبي، غائب → وضع، ملغى → إعادة وضع
  6) الجزئي الحقيقي: بيع سوق نصف الكمية + استبدال الراكن بالمتبقي وعند الدخول + بلا إعادة

تشغيل: pytest test_fe180.py -v   (من داخل مجلد المشروع)
"""

import json

import pandas as pd
import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة (نفس عقد test_fe100)


# ─────────────────────────────────────────────────────────────────────────────
# تجهيزات
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


def make_setup(prices=None, direction: str = "BULLISH"):
    """نافذة صاعدة قياسية (نفس عقد test_fe170): دخول 109.27، SL=89.9، TP=116.18،
    rr_net ≈ 0.345 ≥ 0.3 الافتراضي — تمر ببوابة FE1.8.0."""
    from engine.pattern_detector import DetectedSetup
    P = prices or [90.0, 100.0, 100.0, 115.0, 104.0, 108.0]
    return DetectedSetup(
        symbol="TEST/USDT", timeframe="15m", direction=direction,
        pivot_indices=[0, 10, 20, 30, 40, 95],
        pivot_timestamps=[pd.Timestamp("2026-01-01", tz="UTC")] * 6,
        pivot_prices=P,
        validation_result=_StubValidation(),
        detected_at=pd.Timestamp("2026-01-01", tz="UTC"),
    )


def make_df(high: float, low: float, close: float, n: int = 100) -> pd.DataFrame:
    """شمعة اصطناعية واحدة مفيدة (high/low/close مستقلة) — لبقية الشموع نفس close."""
    highs = [close] * n
    lows = [close] * n
    highs[-1], lows[-1] = high, low
    return pd.DataFrame({"close": [close] * n, "open": [close] * n,
                         "high": highs, "low": lows, "volume": [1.0] * n})


def insert_sig(status="open", is_real=0, fill=100.0, sl=95.0, tp=120.0, qty=10.0,
               entry=106.0, order_id=None, meta_json=None, symbol="TEST/USDT"):
    vnz.db.execute(
        "INSERT INTO signals (symbol, direction, strategy_name, status, entry_price, stop_loss,"
        " take_profit, quantity, notional_usdt, fill_price, created_at, is_real, order_id, meta_json, pivots_json)"
        " VALUES (%s,%s,'Elliott_Fibonacci',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (symbol, "BULLISH", status, entry, sl, tp, qty, qty * fill, fill,
         vnz.utc_now_iso(), is_real, order_id, meta_json, '{"P0": 90.0}'),
    )
    return vnz.db.query("SELECT * FROM signals ORDER BY id DESC LIMIT 1", one=True)


class FakeEx:
    """منصة وهمية تلتقط أوامر الوقف الراكن — بلا شبكة."""
    def __init__(self):
        self.orders = []
        self._n = 700

    def privatePostOrder(self, params):
        self._n += 1
        self.orders.append(dict(params))
        return {"orderId": str(self._n), "status": "NEW",
                "executedQty": "0", "cummulativeQuoteQty": "0"}


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
def real_stubs(monkeypatch):
    """طبقة باينانس وهمية موحدة: منصة تلتقط الأوامر + قواعد سوق رخوة + دقة محايدة."""
    ex = FakeEx()
    monkeypatch.setattr(vnz, "binance_trade_exchange", lambda: ex)
    monkeypatch.setattr(vnz, "real_adjust_price", lambda exx, s, p: float(p))
    monkeypatch.setattr(vnz, "real_adjust_amount", lambda exx, s, q: float(q))
    monkeypatch.setattr(vnz, "real_market",
                        lambda exx, s: {"limits": {"cost": {"min": 5.0}, "amount": {"min": 0.0001}}})
    return ex


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 1 — rr_net: الحساب والبوابة
# ─────────────────────────────────────────────────────────────────────────────

class TestRRNet:

    def test_rr_net_math_subtracts_roundtrip_fees(self):
        # (10 - 0.001*210)/5 = 1.958 — الرسوم على الدخول والخروج معًا
        assert abs(vnz.rr_net_value(100.0, 95.0, 110.0) - 1.958) < 1e-9

    def test_rr_net_zero_risk(self):
        assert vnz.rr_net_value(100.0, 100.0, 110.0) == 0.0

    def test_default_setup_passes_default_floor(self, clean_db):
        # rr_net ≈ 0.345 ≥ 0.3 — الإشارة تُقبل والأرضية مضبوطة افتراضيًا
        assert vnz.create_pending_signal("TEST/USDT", make_setup(), last_close=110.0) is True

    def test_low_rr_net_rejected_with_counter(self, clean_db, monkeypatch):
        monkeypatch.setattr(vnz, "RR_NET_MIN", 0.5)
        before = vnz.scan_stats["rejected_rr_net"]
        assert vnz.create_pending_signal("TEST/USDT", make_setup(), last_close=110.0) is False
        assert vnz.scan_stats["rejected_rr_net"] == before + 1

    def test_disabled_via_zero(self, clean_db, monkeypatch):
        monkeypatch.setattr(vnz, "RR_NET_MIN", 0.0)
        assert vnz.create_pending_signal("TEST/USDT", make_setup(), last_close=110.0) is True

    def test_rr_net_recorded_in_fib_json(self, clean_db):
        assert vnz.create_pending_signal("TEST/USDT", make_setup(), last_close=110.0) is True
        row = vnz.db.query("SELECT * FROM signals ORDER BY id DESC LIMIT 1", one=True)
        fib = json.loads(row["fib_json"])
        assert abs(fib["rr_net"] - vnz.rr_net_value(109.27, 89.9, 116.18)) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 2 — قاطع المخاطر: حد يومي + متتاليات
# ─────────────────────────────────────────────────────────────────────────────

class TestRiskBreaker:

    def _seed(self, realized="-600.0", base="10000.0", streak="0", pause=""):
        vnz.db_set_state("risk_day", vnz._utc_day())
        vnz.db_set_state("risk_realized", realized)
        vnz.db_set_state("risk_day_base", base)
        vnz.db_set_state("risk_streak", streak)
        vnz.db_set_state("risk_pause_until", pause)

    def test_daily_loss_limit_blocks_entries(self, clean_db):
        self._seed(realized="-600.0")  # 6% من أساس 10k بسقف 5%
        before = vnz.scan_stats["rejected_daily_loss"]
        assert vnz.create_pending_signal("TEST/USDT", make_setup(), last_close=110.0) is False
        assert vnz.scan_stats["rejected_daily_loss"] == before + 1

    def test_daily_limit_not_hit_allows(self, clean_db):
        self._seed(realized="-400.0")  # 4% < 5%
        assert vnz.create_pending_signal("TEST/USDT", make_setup(), last_close=110.0) is True

    def test_daily_limit_disabled_via_zero(self, clean_db, monkeypatch):
        monkeypatch.setattr(vnz, "DAILY_LOSS_LIMIT_PCT", 0.0)
        self._seed(realized="-600.0")
        assert vnz.create_pending_signal("TEST/USDT", make_setup(), last_close=110.0) is True

    def test_loss_streak_pauses_entries(self, clean_db):
        from datetime import datetime, timedelta, timezone
        until = (datetime.now(timezone.utc) + timedelta(seconds=3600)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._seed(realized="0.0", streak="3", pause=until)  # تبريد سارٍ ومسؤولية يومية صفرية
        before = vnz.scan_stats["rejected_risk_pause"]
        assert vnz.create_pending_signal("TEST/USDT", make_setup(), last_close=110.0) is False
        assert vnz.scan_stats["rejected_risk_pause"] == before + 1

    def test_expired_pause_allows(self, clean_db):
        self._seed(realized="0.0", streak="3", pause="2020-01-01T00:00:00Z")  # تبريد منتهٍ
        assert vnz.create_pending_signal("TEST/USDT", make_setup(), last_close=110.0) is True

    def test_consecutive_losses_trigger_pause(self, clean_db, monkeypatch):
        # 3 خسائر متتالية (سقف افتراضي 3) → تفعيل التبريد آليًا من close_signal_row
        for _ in range(3):
            sig = insert_sig(fill=100.0, sl=95.0, tp=120.0, qty=10.0)
            vnz.close_signal_row(sig, 95.0, "وقف اختباري")
        snap = vnz.risk_snapshot()
        assert snap["loss_streak"] == 3
        assert snap["pause_until"], "يجب أن يُفعّل التبريد بعد 3 خسائر متتالية"

    def test_win_resets_streak(self, clean_db):
        sig1 = insert_sig(fill=100.0, sl=95.0, tp=120.0, qty=10.0)
        vnz.close_signal_row(sig1, 95.0, "وقف")
        sig2 = insert_sig(fill=100.0, sl=95.0, tp=120.0, qty=10.0)
        vnz.close_signal_row(sig2, 120.0, "هدف")
        snap = vnz.risk_snapshot()
        assert snap["loss_streak"] == 0
        assert not snap["pause_until"]

    def test_risk_on_close_accumulates_daily(self, clean_db):
        self._seed(realized="0.0", base="10000.0")
        sig = insert_sig(fill=100.0, sl=95.0, tp=120.0, qty=10.0)
        vnz.close_signal_row(sig, 95.0, "وقف")
        snap = vnz.risk_snapshot()
        assert snap["daily_realized"] < 0
        assert snap["daily_base"] == 10000.0


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 3 — الحماية الورقية: BE@1R + جزئي + وقف-أولًا
# ─────────────────────────────────────────────────────────────────────────────

class TestPaperProtection:

    def test_paper_fill_sets_initial_quantity(self, clean_db, monkeypatch):
        sig = insert_sig(status="pending", fill=100.0, entry=106.0, qty=10.0, sl=95.0, tp=120.0)
        monkeypatch.setattr(vnz, "get_recent_candles",
                            lambda s, tf, limit=2, min_candles=2: make_df(106.0, 105.0, 105.5))
        vnz.monitor_step()
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        assert row["status"] == "open"
        assert float(row["initial_quantity"]) == 10.0

    def test_be_and_partial_fire_at_1R(self, clean_db):
        # +1R = 105 (دخول 100 وقف 95) — الشمعة لمست 105.5 بلا لمس الوقف
        sig = insert_sig(fill=100.0, sl=95.0, tp=120.0, qty=10.0)
        bal0 = vnz.get_paper_balance()
        vnz._protection_step(sig, 105.5)
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        meta = json.loads(row["meta_json"] or "{}")
        assert float(row["stop_loss"]) == 100.0, "الوقف انتقل للدخول (BE)"
        assert meta.get("be_done") is True
        assert meta.get("partial_done") is True
        assert float(row["quantity"]) == 5.0, "أُغلق النصف جزئيًا"
        assert float(row["initial_quantity"]) == 10.0
        # ربح الرجل: 5×(105−100) − رسوم (500+525)×0.001 = 23.975
        assert abs(float(row["realized_pnl_usdt"]) - 23.975) < 1e-6
        assert abs(vnz.get_paper_balance() - bal0 - 23.975) < 1e-6

    def test_protection_fires_once_only(self, clean_db):
        sig = insert_sig(fill=100.0, sl=95.0, tp=120.0, qty=10.0)
        vnz._protection_step(sig, 105.5)
        bal1 = vnz.get_paper_balance()
        vnz._protection_step(sig, 106.0)  # شمعة تالية أعلى — الأعلام تمنع التكرار
        assert vnz.get_paper_balance() == bal1
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        assert float(row["quantity"]) == 5.0

    def test_sl_first_guard_blocks_protection(self, clean_db):
        # الشمعة لمست الوقف (94 ≤ 95) وتجاوزت التريغر (106) — الوقف يفوز داخليًا دائمًا
        sig = insert_sig(fill=100.0, sl=95.0, tp=120.0, qty=10.0)
        monkey_df = make_df(106.0, 94.0, 100.0)
        import vnz as _v
        orig = _v.get_recent_candles
        _v.get_recent_candles = lambda s, tf, limit=2, min_candles=2: monkey_df
        try:
            _v.monitor_step()
        finally:
            _v.get_recent_candles = orig
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        assert row["status"] == "closed"
        assert "وقف" in (row["close_reason"] or "")
        assert float(row["stop_loss"]) == 95.0, "لا BE بعد لمس الوقف"
        assert float(row["quantity"]) == 10.0, "لا جزئي بعد لمس الوقف"
        assert abs(float(row["realized_pnl_usdt"] or 0)) < 1e-9

    def test_final_close_sums_realized_without_double_count(self, clean_db):
        sig = insert_sig(fill=100.0, sl=95.0, tp=120.0, qty=10.0)
        bal0 = vnz.get_paper_balance()
        vnz._protection_step(sig, 105.5)          # جزئي 50% عند 105
        vnz.close_signal_row(sig, 120.0, "هدف")   # إغلاق النصف المتبقي عند الهدف
        total = vnz.get_paper_balance() - bal0
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        # الإجمالي = ربح الرجل 23.975 + النهائي (100 − 1.1 + 23.975) — realized دخُل مرة واحدة
        assert abs(float(row["pnl_usdt"]) - 122.875) < 1e-6
        assert abs(total - (23.975 + 122.875)) < 1e-6
        assert abs(float(row["pnl_pct"]) - 122.875 / 1000.0 * 100.0) < 1e-6, "النسبة على الحجم الأصلي"

    def test_protection_disabled(self, clean_db, monkeypatch):
        monkeypatch.setattr(vnz, "BE_AT_R_ENABLED", False)
        monkeypatch.setattr(vnz, "PARTIAL_AT_R_ENABLED", False)
        sig = insert_sig(fill=100.0, sl=95.0, tp=120.0, qty=10.0)
        vnz._protection_step(sig, 105.5)
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        assert float(row["stop_loss"]) == 95.0
        assert float(row["quantity"]) == 10.0

    def test_below_trigger_noop(self, clean_db):
        sig = insert_sig(fill=100.0, sl=95.0, tp=120.0, qty=10.0)
        vnz._protection_step(sig, 104.9)  # تحت +1R = 105
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        assert float(row["stop_loss"]) == 95.0
        assert float(row["quantity"]) == 10.0
        assert not row["meta_json"]


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 4 — الوقف الراكن الحقيقي على المنصة
# ─────────────────────────────────────────────────────────────────────────────

class TestStandingStopReal:

    def test_stop_placed_after_real_fill(self, clean_db, real_stubs, monkeypatch):
        sig = insert_sig(status="pending", is_real=1, order_id="555",
                         fill=100.0, sl=95.0, tp=120.0, qty=10.0)
        monkeypatch.setattr(vnz, "fetch_real_order",
                            lambda ex, s, o: {"status": "closed", "filled": 10.0,
                                              "average": 100.2, "id": "555"})
        vnz.handle_real_pending(sig, 100.2, 90.0)
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        assert row["status"] == "open"
        assert float(row["initial_quantity"]) == 10.0
        meta = json.loads(row["meta_json"] or "{}")
        assert meta.get("stop_order_id"), "يجب تخزين معرف الوقف الراكن"
        assert len(real_stubs.orders) == 1
        o = real_stubs.orders[0]
        assert o["type"] == "STOP_LOSS_LIMIT" and o["side"] == "SELL"
        assert float(o["stopPrice"]) == 95.0
        assert float(o["quantity"]) == 10.0

    def test_close_real_trade_cancels_stop_first(self, clean_db, real_stubs, monkeypatch):
        sig = insert_sig(is_real=1, fill=100.0, sl=95.0, tp=120.0, qty=10.0,
                         meta_json=json.dumps({"stop_order_id": "777"}))
        cancels = []
        monkeypatch.setattr(vnz, "cancel_real_order",
                            lambda ex, s, o: cancels.append((s, o)) or True)
        monkeypatch.setattr(vnz, "fetch_free_base", lambda ex, b: 10.0)
        monkeypatch.setattr(vnz, "place_real_market_sell",
                            lambda s, q: {"id": "888", "average": 98.0, "status": "closed"})
        vnz.close_real_trade(sig, 95.0, "وقف اختباري")
        assert cancels == [("TEST/USDT", "777")], "الإلغاء أولًا قبل أي بيع"
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        assert row["status"] == "closed"
        assert abs(float(row["close_price"]) - 98.0) < 1e-9

    def test_close_when_stop_executed_on_exchange(self, clean_db, real_stubs, monkeypatch):
        # الوقف نُفذ أثناء غياب البوت: الإلغاء يفشل والحالة FILLED → محاسبة بلا بيع مزدوج
        sig = insert_sig(is_real=1, fill=100.0, sl=95.0, tp=120.0, qty=10.0,
                         meta_json=json.dumps({"stop_order_id": "777"}))
        monkeypatch.setattr(vnz, "cancel_real_order", lambda ex, s, o: False)
        monkeypatch.setattr(vnz, "fetch_real_order",
                            lambda ex, s, o: {"status": "closed", "filled": 10.0,
                                              "average": 94.8, "id": "777"})
        sold = {"n": 0}
        monkeypatch.setattr(vnz, "place_real_market_sell", lambda s, q: sold.__setitem__("n", sold["n"] + 1))
        vnz.close_real_trade(sig, 95.0, "وقف اختباري")
        assert sold["n"] == 0, "لا بيع سوق فوق تنفيذ الوقف"
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        assert row["status"] == "closed"
        assert abs(float(row["close_price"]) - 94.8) < 1e-9

    def test_close_deferred_when_stop_uncancellable(self, clean_db, real_stubs, monkeypatch):
        # الوقف حي ولا يُلغى → لا بيع (ازدواج) — إعادة المحاولة في الدورة القادمة
        sig = insert_sig(is_real=1, fill=100.0, sl=95.0, tp=120.0, qty=10.0,
                         meta_json=json.dumps({"stop_order_id": "777"}))
        monkeypatch.setattr(vnz, "cancel_real_order", lambda ex, s, o: False)
        monkeypatch.setattr(vnz, "fetch_real_order",
                            lambda ex, s, o: {"status": "open", "filled": 0.0, "average": 0, "id": "777"})
        vnz.close_real_trade(sig, 95.0, "وقف اختباري")
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        assert row["status"] == "open", "تبقى مفتوحة حتى يُلغى الراكن"

    def test_dust_quantity_skips_standing_stop(self, clean_db, real_stubs, monkeypatch):
        monkeypatch.setattr(vnz, "real_market",
                            lambda ex, s: {"limits": {"cost": {"min": 5.0}, "amount": {"min": 100.0}}})
        order = vnz.place_real_stop_loss("TEST/USDT", 1.0, 95.0, real_stubs)
        assert order is None
        assert real_stubs.orders == [], "الغبار لا يرفع أمرًا راكنًا — المراقبة المحلية خط الدفاع"


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 5 — المصالقة الدورية (المنصة مصدر الحقيقة)
# ─────────────────────────────────────────────────────────────────────────────

class TestReconcile:

    @pytest.fixture(autouse=True)
    def _real_mode(self, monkeypatch):
        monkeypatch.setattr(vnz, "is_real_mode", True)

    def test_stop_filled_on_exchange_closes_accounting(self, clean_db, real_stubs, monkeypatch):
        sig = insert_sig(is_real=1, fill=100.0, sl=95.0, tp=120.0, qty=10.0,
                         meta_json=json.dumps({"stop_order_id": "777", "stop_price": 95.0}))
        monkeypatch.setattr(vnz, "fetch_real_order",
                            lambda ex, s, o: {"status": "closed", "filled": 10.0,
                                              "average": 94.7, "id": "777"})
        vnz.reconcile_real_protection()
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        assert row["status"] == "closed"
        assert abs(float(row["close_price"]) - 94.7) < 1e-9

    def test_missing_stop_gets_placed(self, clean_db, real_stubs, monkeypatch):
        sig = insert_sig(is_real=1, fill=100.0, sl=95.0, tp=120.0, qty=10.0, meta_json=None)
        vnz.reconcile_real_protection()
        assert len(real_stubs.orders) == 1
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        meta = json.loads(row["meta_json"] or "{}")
        assert meta.get("stop_order_id")

    def test_canceled_stop_gets_replaced(self, clean_db, real_stubs, monkeypatch):
        sig = insert_sig(is_real=1, fill=100.0, sl=95.0, tp=120.0, qty=10.0,
                         meta_json=json.dumps({"stop_order_id": "777", "stop_price": 95.0}))
        monkeypatch.setattr(vnz, "fetch_real_order",
                            lambda ex, s, o: {"status": "canceled", "filled": 0.0,
                                              "average": 0, "id": "777"})
        vnz.reconcile_real_protection()
        assert len(real_stubs.orders) == 1, "أمر بديل وُضع فورًا"
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        meta = json.loads(row["meta_json"] or "{}")
        assert meta.get("stop_order_id") and meta["stop_order_id"] != "777"
        assert row["status"] == "open"

    def test_paper_mode_reconcile_noop(self, clean_db, real_stubs, monkeypatch):
        monkeypatch.setattr(vnz, "is_real_mode", False)
        insert_sig(is_real=1, fill=100.0, sl=95.0, tp=120.0, qty=10.0, meta_json=None)
        vnz.reconcile_real_protection()
        assert real_stubs.orders == []


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 6 — الجزئي الحقيقي: بيع سوق + استبدال الراكن
# ─────────────────────────────────────────────────────────────────────────────

class TestRealPartial:

    def test_partial_sells_market_and_replaces_stop(self, clean_db, real_stubs, monkeypatch):
        sig = insert_sig(is_real=1, fill=100.0, sl=95.0, tp=120.0, qty=10.0, meta_json="{}")
        sells = []
        monkeypatch.setattr(vnz, "place_real_market_sell",
                            lambda s, q: sells.append(q) or {"id": "9", "average": 105.2,
                                                             "status": "closed"})
        vnz._protection_step(sig, 105.5)
        assert sells == [5.0], "بيع سوق لنصف الكمية عند +1R"
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        assert float(row["quantity"]) == 5.0
        assert float(row["initial_quantity"]) == 10.0
        # 5×(105.2−100) − (500+526)×0.001 = 24.974
        assert abs(float(row["realized_pnl_usdt"]) - 24.974) < 1e-6
        # الراكن استُبدل: كمية 5 عند الدخول 100
        assert len(real_stubs.orders) == 1
        o = real_stubs.orders[0]
        assert o["type"] == "STOP_LOSS_LIMIT"
        assert float(o["quantity"]) == 5.0
        assert float(o["stopPrice"]) == 100.0
        assert float(row["stop_loss"]) == 100.0
        meta = json.loads(row["meta_json"] or "{}")
        assert meta.get("partial_done") is True and meta.get("be_done") is True

    def test_failed_sell_retries_next_cycle(self, clean_db, real_stubs, monkeypatch):
        sig = insert_sig(is_real=1, fill=100.0, sl=95.0, tp=120.0, qty=10.0, meta_json="{}")
        monkeypatch.setattr(vnz, "place_real_market_sell", lambda s, q: None)  # فشل
        vnz._protection_step(sig, 105.5)
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        meta = json.loads(row["meta_json"] or "{}")
        assert not meta.get("partial_done"), "فشل البيع → بلا علم — إعادة محاولة"
        assert float(row["quantity"]) == 10.0

    def test_paper_partial_no_exchange_calls(self, clean_db, real_stubs):
        sig = insert_sig(is_real=0, fill=100.0, sl=95.0, tp=120.0, qty=10.0)
        vnz._protection_step(sig, 105.5)
        assert real_stubs.orders == [], "الورقي لا يمس المنصة"
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        assert float(row["quantity"]) == 5.0


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 7 — الإصدار والعرض
# ─────────────────────────────────────────────────────────────────────────────

def test_version_bump():
    import panel
    assert vnz.BOT_VERSION == "EL2.3.0"
    assert panel.BOT_VERSION == "EL2.3.0"


def test_risk_snapshot_shape(clean_db):
    snap = vnz.risk_snapshot()
    for k in ("daily_realized", "daily_base", "daily_limit_pct", "daily_hit",
              "loss_streak", "max_consec_losses", "pause_until"):
        assert k in snap
