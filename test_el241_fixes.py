#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات انحدار EL2.4.1 — إصلاحات F1..F10 حرفيًا وفق البرمبت المعتمد
=======================================================================
كل اختبار يُكتب قبل إصلاحه (يفشل على EL2.4.0) ثم يُجعل ينجح — وبأقل أثر على
السلوك القائم: القيم الافتراضية محفوظة وكل مساعد جديد fail-open مع الاختبارات
القديمة (شموع بلا عمود timestamp = السلوك التراثي حرفيًا).
"""

import json
import math
import time

import pandas as pd
import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة (نمط test_el2_integration)


@pytest.fixture()
def clean_db(monkeypatch):
    """قاعدة SQLite مؤقتة لكل اختبار — عزل كامل (نمط المستودع نفسه).
    [EL2.4.1][F2] مع حالة الحدود وكاش السعر الحي (ذاكرة العملية تُصفَّر بين الاختبارات)."""
    monkeypatch.setattr(vnz, "USE_POSTGRES", False)
    import sqlite3
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    old = vnz.db.conn
    vnz.db.conn = conn
    vnz.init_db()
    vnz._EXT_STATE.clear()
    vnz._price_cache.clear()
    yield
    vnz._EXT_STATE.clear()
    vnz._price_cache.clear()
    vnz.db.conn = old


@pytest.fixture()
def tg_off(monkeypatch):
    monkeypatch.setattr(vnz, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(vnz, "TELEGRAM_CHAT_ID", "")
    monkeypatch.setattr(vnz, "_tg_dedup", {})
    yield


def _insert_pending(sym="TEST/USDT", entry=118.0, stop=114.0, tp=135.0,
                    qty=10.0, p0=90.0, created="2026-10-24T10:00:00Z"):
    """صفقة محرك معلقة حرفية بالقيم المذكورة في البرمبت (F1)."""
    vnz.db.execute(
        "INSERT INTO signals (symbol, direction, strategy_name, status, entry_price,"
        " stop_loss, take_profit, quantity, pivots_json, created_at, expires_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (sym, "BULLISH", "Elliott_Fibonacci", "pending", entry, stop, tp, qty,
         json.dumps({"P0": p0, "P1": 100.0, "P2": 110.0, "P3": 120.0,
                     "P4": 112.0, "P5": 130.0}),
         created, "2099-01-01T00:00:00Z"))
    return vnz.db.query("SELECT * FROM signals WHERE symbol=%s", (sym,), one=True)


def _dtc_now():
    import datetime as _d
    return _d.datetime.now(_d.timezone.utc)


def dt_timedelta(minutes):
    import datetime as _d
    return _d.timedelta(minutes=minutes)


def _candle(open_, high, low, close):
    return pd.DataFrame([{"ts": 0, "open": open_, "high": high, "low": low,
                          "close": close, "volume": 1.0}])


# ─────────────────────────────────────────────────────────────────────────────
# F1 — الملء الورقي المتفائل والربح الوهمي (P0)
# ─────────────────────────────────────────────────────────────────────────────

class TestF1HonestFill:
    def test_fill_close_below_stop_no_phantom_profit(self, clean_db, tg_off, monkeypatch):
        """شمعة تلمس الدخول وتغلق تحت الوقف: الملء بسعر الأمر (لا بسعر الإغلاق)
        والصفقة تُغلق بالوقف في نفس الدورة — pnl سالب لا ربح وهمي."""
        _insert_pending()
        monkeypatch.setattr(vnz, "fetch_ohlcv_df",
                            lambda *a, **k: _candle(120, 121, 105, 110))
        vnz.monitor_step()
        row = vnz.db.query("SELECT * FROM signals", one=True)
        assert row["status"] == "closed"
        assert math.isclose(float(row["fill_price"]), 118.0, rel_tol=1e-9)
        assert math.isclose(float(row["close_price"]), 114.0, rel_tol=1e-9)
        assert float(row["pnl_usdt"]) < 0

    def test_gap_open_below_stop_closes_at_fill(self, clean_db, tg_off, monkeypatch):
        """فتح شمعة تحت الوقف: الملء بالفتح (أدنى من الدخول) وإغلاق فوري بسعر
        الملء — خسارة رسوم حصرًا لا صفقة وقف بربح."""
        _insert_pending()
        monkeypatch.setattr(vnz, "fetch_ohlcv_df",
                            lambda *a, **k: _candle(110, 121, 105, 112))
        vnz.monitor_step()
        row = vnz.db.query("SELECT * FROM signals", one=True)
        assert row["status"] == "closed"
        assert math.isclose(float(row["fill_price"]), 110.0, rel_tol=1e-9)
        assert math.isclose(float(row["close_price"]), 110.0, rel_tol=1e-9)
        assert float(row["pnl_usdt"]) < 0  # رسوم فقط

    def test_normal_touch_fills_at_limit(self, clean_db, tg_off, monkeypatch):
        """الملء الطبيعي لم يتغير: لمس الدخول مع إغلاق فوقه = ملء بسعر الأمر."""
        _insert_pending()
        monkeypatch.setattr(vnz, "fetch_ohlcv_df",
                            lambda *a, **k: _candle(120, 121, 115, 118))
        vnz.monitor_step()
        row = vnz.db.query("SELECT * FROM signals", one=True)
        assert row["status"] == "open"
        assert math.isclose(float(row["fill_price"]), 118.0, rel_tol=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# F2 — حدّا الشمعة الجارية يسبقان الحدث (P0)
# ─────────────────────────────────────────────────────────────────────────────

def _ts_candle(open_, high, low, close, open_ts):
    """شمعة بعمود timestamp (datetime) — للتحكم في ترتيب الأحداث داخل الشمعة."""
    import datetime as _dt
    return pd.DataFrame([{"ts": open_ts.timestamp() * 1000, "open": open_, "high": high,
                          "low": low, "close": close, "volume": 1.0,
                          "timestamp": open_ts}])


class _DynCandles:
    """حامل شموع قابل للتعديل بين دورات المراقبة (بعمود timestamp)."""

    def __init__(self, frame):
        self.frame = frame


class TestF2ExtremesSinceEvent:
    def _scalp_host(self, clean_db, tg_off, monkeypatch, dyn):
        """مضيف سكالب مبني على vnz الحقيقي — سعر وشموع قابلة للتحكم."""
        price = {"v": 103.1}

        def live(_sym):
            return price["v"]

        fake = {
            "db_query": vnz.db.query, "db_execute": vnz.db.execute,
            "log_and_notify": vnz.log_and_notify, "logger": vnz.logger,
            "get_live_price": live,
            "get_recent_candles": lambda s, tf, limit, min_candles=2: dyn.frame,
            "fetch_ohlcv_raw": lambda s, tf, limit: (None, None),
            "binance_full_klines": lambda s, iv, limit: None,
            "binance_depth": lambda s, limit: None,
            "utc_now_iso": vnz.utc_now_iso, "fmt_price": vnz.fmt_price,
            "seconds_until_next_candle": lambda tf: 300.0,
            "is_trading_enabled": lambda: True,
            "is_real_mode": lambda: False,
            "risk_entry_block_reason": lambda: None,
            "symbol_has_active": lambda s: False,
            "get_paper_balance": vnz.get_paper_balance,
            "fee_rate": 0.001, "deviation_threshold": 0.006,
            "zigzag_pivots": vnz.zigzag_pivots,
            "close_signal_row": vnz.close_signal_row,
            "close_real_trade": vnz.close_real_trade,
            "account_partial_close": vnz._account_partial_close,
            "place_real_market_sell": vnz.place_real_market_sell,
            "place_real_stop_loss": vnz.place_real_stop_loss,
            "replace_real_stop": vnz._replace_real_stop,
            "cancel_real_order": vnz.cancel_real_order,
            "real_market_buy": vnz.scalp_real_market_buy,
            "real_free_usdt": lambda: 0.0,
            "real_max_notional": lambda: 50.0,
            "real_adjust_amount": vnz.real_adjust_amount,
            "real_min_amount": vnz.real_min_amount,
            "real_min_cost": vnz.real_min_cost,
            "real_market_rules": vnz.real_market_rules,
            "binance_trade_exchange": vnz.binance_trade_exchange,
            "watchlist": lambda: ["TEST/USDT"],
        }
        from strategies import manager as sm
        sm.attach_host(fake)
        for c in sm._counters.values():
            c.update({"signals": 0, "partials": 0, "early_exits": 0, "closes": {},
                      "rejects": {}, "last_signal_at": None, "last_signal_symbol": None})
        for d in sm._cooldowns.values():
            d.clear()
        return sm, price

    def _open_scalp_row(self, fill=99.4, stop=97.0, tp1=103.0, tp2=105.0, qty=10.0):
        # [EL2.4.1][F2] أزمنة ديناميكية (35 دقيقة مضت) — أقل من مهلة السكالب (90د)
        t0 = (_dtc_now() - dt_timedelta(minutes=35)).strftime("%Y-%m-%dT%H:%M:%S")
        vnz.db.execute(
            "INSERT INTO signals (symbol, direction, strategy_name, status, entry_price,"
            " fill_price, stop_loss, take_profit, tp1, tp2, quantity, notional_usdt,"
            " created_at, filled_at, initial_quantity, peak_price, is_real)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0)",
            ("TEST/USDT", "BULLISH", "SCALP_FLOW", "open", fill, fill, stop, tp2,
             tp1, tp2, qty, fill * qty, t0, t0, qty, fill))
        return vnz.db.query("SELECT * FROM signals WHERE symbol='TEST/USDT'", one=True)

    def test_stale_candle_extremes_do_not_kill_position(self, clean_db, tg_off, monkeypatch):
        """سكالب: بعد الجزئي والتسليح، حدّا الشمعة القديمة (اللذان سبقا التسليح) لا
        يغلقان الصفقة في الدورة التالية — القاع الحي فوق الوقف = بلا إغلاق."""
        import datetime as dt
        from datetime import datetime as _dtc, timezone as _tzc
        from strategies import manager as sm
        now = _dtc.now(_tzc.utc)
        self._open_scalp_row()
        dyn = _DynCandles(_ts_candle(103.1, 103.2, 99.2, 103.1,
                                     now - dt.timedelta(minutes=30)))
        sm, price = self._scalp_host(clean_db, tg_off, monkeypatch, dyn)
        vnz._EXT_STATE.clear()
        sm._EXT_STATE.clear()
        sm._monitor_cycle()                      # الدورة 1: جزئي + BE + تسليح
        row = vnz.db.query("SELECT * FROM signals", one=True)
        assert row["status"] == "open"
        assert math.isclose(float(row["stop_loss"]), 99.4, rel_tol=1e-9)
        sm._monitor_cycle()                      # الدورة 2: نفس الشمعة — بلا إغلاق
        row = vnz.db.query("SELECT * FROM signals", one=True)
        assert row["status"] == "open", "القاع 99.2 سبق التسليح — لا يجوز أن يُغلق الوقف"
        # ثم يهبط السعر الحي تحت الوقف المسلّح → إغلاق
        price["v"] = 99.0
        sm._monitor_cycle()
        row = vnz.db.query("SELECT * FROM signals", one=True)
        assert row["status"] == "closed"
        assert math.isclose(float(row["close_price"]), 99.4, rel_tol=1e-9)

    def test_engine_pending_not_filled_by_stale_candle(self, clean_db, tg_off, monkeypatch):
        """محرك: شمعة جارية فُتحت قبل إنشاء الأمر وقاعها ≤ الدخول والحي فوق الدخول
        ⇒ لا ملء — الشمعة القديمة لا تملأ أمرًا لم يولد بعد."""
        import datetime as dt
        now = dt.datetime(2026, 10, 24, 10, 0, 0, tzinfo=dt.timezone.utc)
        _insert_pending(created="2026-10-24T10:00:00Z")
        old_candle = _ts_candle(119.0, 121.0, 105.0, 119.0,
                                now - dt.timedelta(minutes=15))
        monkeypatch.setattr(vnz, "fetch_ohlcv_df", lambda *a, **k: old_candle)
        vnz._EXT_STATE.clear()
        vnz.monitor_step()
        row = vnz.db.query("SELECT * FROM signals", one=True)
        assert row["status"] == "pending", "قاع شمعة فتحت قبل ولادة الأمر لا يملؤه"

    def test_no_timestamp_column_keeps_legacy_behavior(self, clean_db, tg_off, monkeypatch):
        """محاكٍ بلا عمود timestamp (نمط PriceHolder) ⇒ السلوك القديم حرفيًا: قاع
        الشمعة يملأ المعلق دون أي حكم زمني (شمعة لا تلمس الوقف — عقيدة الوقف-أولًا)."""
        _insert_pending(created="2026-10-24T10:00:00Z")
        monkeypatch.setattr(vnz, "fetch_ohlcv_df",
                            lambda *a, **k: _candle(120, 121, 116, 118))
        vnz._EXT_STATE.clear()
        vnz.monitor_step()
        row = vnz.db.query("SELECT * FROM signals", one=True)
        assert row["status"] == "open"
        assert math.isclose(float(row["fill_price"]), 118.0, rel_tol=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# F3 — بوابات الملء الارتدادي وتوحيد الوضع الحقيقي (P0)
# ─────────────────────────────────────────────────────────────────────────────

class TestF3RetraceGates:
    def _host(self, clean_db, tg_off, monkeypatch, *, trading=True, real=False,
              risk_block=None, price_v=97.5):
        """مضيف سكالب مبسّط — أزرار الحكم قابلة للضبط لكل اختبار."""
        import time as _t
        price = {"v": price_v}
        bought = []
        fake = {
            "db_query": vnz.db.query, "db_execute": vnz.db.execute,
            "log_and_notify": vnz.log_and_notify, "logger": vnz.logger,
            "get_live_price": lambda s: price["v"],
            "get_recent_candles": lambda s, tf, limit, min_candles=2: None,
            "fetch_ohlcv_raw": lambda s, tf, limit: (None, None),
            "binance_full_klines": lambda s, iv, limit: None,
            "binance_depth": lambda s, limit: None,
            "utc_now_iso": vnz.utc_now_iso, "fmt_price": vnz.fmt_price,
            "seconds_until_next_candle": lambda tf: 300.0,
            "is_trading_enabled": lambda: trading,
            "is_real_mode": lambda: real,
            "risk_entry_block_reason": lambda: risk_block,
            "symbol_has_active": lambda s: False,
            "get_paper_balance": vnz.get_paper_balance,
            "fee_rate": 0.001, "deviation_threshold": 0.006,
            "zigzag_pivots": vnz.zigzag_pivots,
            "close_signal_row": vnz.close_signal_row,
            "close_real_trade": vnz.close_real_trade,
            "account_partial_close": vnz._account_partial_close,
            "place_real_market_sell": vnz.place_real_market_sell,
            "place_real_stop_loss": lambda s, q, p: {"id": "S1"},
            "replace_real_stop": vnz._replace_real_stop,
            "cancel_real_order": vnz.cancel_real_order,
            "real_market_buy": lambda s, quote: bought.append((s, quote)) or
                {"id": "R1", "average": price["v"], "amount": quote / price["v"]},
            "real_free_usdt": lambda: 1000.0,
            "real_max_notional": lambda: 50.0,
            "real_adjust_amount": lambda ex, s, q: q,
            "real_min_amount": lambda mkt: 0.0,
            "real_min_cost": lambda mkt: 0.0,
            "real_market_rules": lambda s, ex: {},
            "binance_trade_exchange": lambda: object(),
            "watchlist": lambda: ["TEST/USDT"],
        }
        from strategies import manager as sm
        sm.attach_host(fake)
        for c in sm._counters.values():
            c.update({"signals": 0, "partials": 0, "early_exits": 0, "closes": {},
                      "rejects": {}, "last_signal_at": None, "last_signal_symbol": None})
        for d in sm._cooldowns.values():
            d.clear()
        return sm, price, bought

    def _arm(self, sm, sym="TEST/USDT", limit=97.4, sl_ref=95.0, atr5=1.0):
        import time as _t
        sm._retrace_orders[sym] = {
            "strategy": "SCALP_FLOW", "label": "انجلال التدفق", "symbol": sym,
            "limit": limit, "sl_ref": sl_ref, "tp1": 100.0, "tp2": 101.5,
            "rr1": 1.0, "entry_ref": 99.0, "atr5": atr5,
            "reason": "اختبار", "armed_ts": _t.time(),
            "expires_ts": _t.time() + 8 * 300, "meta": {"atr5": atr5}}

    def _ctx(self, sym="TEST/USDT", o=98.0, h=98.2, l=97.0, c=97.9):
        import time as _t
        from strategies.base import ScalpContext
        k5 = [{"ts": 0.0, "open": o, "high": h, "low": l, "close": c,
               "volume": 10.0, "taker_base": None}]
        return ScalpContext(symbol=sym, now_ts=_t.time(), k5=k5, k15=[],
                            live_price=c, cvd_source="taker", atr5=1.0)

    def test_retrace_fill_blocked_when_trading_disabled(self, clean_db, tg_off, monkeypatch):
        """تداول معطل ⇒ أمر ارتدادي بشمعة تأكيد صالحة لا يفتح صفقة ويزيد عداد الرفض."""
        sm, price, bought = self._host(clean_db, tg_off, monkeypatch, trading=False)
        self._arm(sm)
        sm._manage_retrace("TEST/USDT", self._ctx())
        assert bought == []
        rows = vnz.db.query("SELECT * FROM signals")
        assert rows == []
        assert "TEST/USDT" not in sm._retrace_orders
        rej = sm._counters["SCALP_FLOW"]["rejects"]
        assert any("ملء ارتدادي أُسقط" in k for k in rej), rej

    def test_retrace_fill_blocked_by_risk_entry_block(self, clean_db, tg_off, monkeypatch):
        """قاطع مخاطر المحرك نشط ⇒ بوابات الملء تمنع الافتتاح."""
        sm, price, bought = self._host(clean_db, tg_off, monkeypatch,
                                       risk_block="قاطع الخسارة اليومي")
        self._arm(sm)
        sm._manage_retrace("TEST/USDT", self._ctx())
        assert bought == []
        assert vnz.db.query("SELECT * FROM signals") == []

    def test_retrace_paper_fill_opens_when_gates_pass(self, clean_db, tg_off, monkeypatch):
        """البوابات مفتوحة (ورقي) ⇒ الملء الارتدادي يفتح صفقة بحمولة retrace_fill."""
        sm, price, bought = self._host(clean_db, tg_off, monkeypatch, trading=True)
        self._arm(sm)
        sm._manage_retrace("TEST/USDT", self._ctx())
        row = vnz.db.query("SELECT * FROM signals", one=True)
        assert row is not None and row["status"] == "open"
        assert math.isclose(float(row["fill_price"]), 97.4, rel_tol=1e-9)
        assert "retrace_fill" in (row["meta_json"] or "")

    def test_real_retrace_guarded_fill(self, clean_db, tg_off, monkeypatch):
        """حقيقي: شراء مرة واحدة عند حيّة ≤ الحد + 0.4×ATR؛ ولا شراء عند الابتعاد أو كسر الوقف."""
        sm, price, bought = self._host(clean_db, tg_off, monkeypatch, real=True,
                                       price_v=97.5)
        self._arm(sm)
        sm._manage_retrace("TEST/USDT", self._ctx())
        assert len(bought) == 1, "الملء الحقيقي المؤكد يجب أن يشتري مرة واحدة"
        row = vnz.db.query("SELECT * FROM signals", one=True)
        assert row["is_real"] == 1
        assert math.isclose(float(row["fill_price"]), 97.5, rel_tol=1e-9)
        # الابتعاد عن الحد: لا شراء
        sm, price, bought = self._host(clean_db, tg_off, monkeypatch, real=True,
                                       price_v=99.9)
        self._arm(sm)
        sm._manage_retrace("TEST/USDT", self._ctx())
        assert bought == []
        # كسر الوقف المرجعي: لا شراء
        sm, price, bought = self._host(clean_db, tg_off, monkeypatch, real=True,
                                       price_v=94.5)
        self._arm(sm)
        sm._manage_retrace("TEST/USDT", self._ctx())
        assert bought == []

    def test_scan_cycle_real_arm_switch(self, clean_db, tg_off, monkeypatch):
        """SCALP_REAL_RETRACE=1 (الافتراضي) ⇒ الوضع الحقيقي يسلّح أمرًا ارتداديًا؛
        SCALP_REAL_RETRACE=0 ⇒ السلوك القديم: شراء فوري عند إغلاق شمعة القرار."""
        import time as _t
        from strategies import manager as sm
        from strategies.base import ScalpSignal
        sm, price, bought = self._host(clean_db, tg_off, monkeypatch, real=True,
                                       price_v=99.0)

        class _FakeStrat:
            label = "انجلال التدفق"

            def evaluate(self, ctx):
                return ScalpSignal(strategy="SCALP_FLOW", label="انجلال التدفق",
                                   symbol="TEST/USDT", entry_ref=99.0, sl=96.5,
                                   tp1=100.0, tp2=101.5, rr1=1.2, reason="اختبار",
                                   meta={"atr5": 1.0})

        sm._instances["SCALP_FLOW"] = _FakeStrat()
        monkeypatch.setattr(sm, "_build_ctx", lambda s: self._ctx(o=99.0, h=99.2,
                                                                  l=98.5, c=99.0))
        sm._scan_cycle()
        assert "TEST/USDT" in sm._retrace_orders, "الافتراضي: الحقيقي يسلّح أمرًا ارتداديًا"
        assert bought == []
        # العلم مطفأ ⇒ السلوك القديم (شراء فوري)
        sm._retrace_orders.clear()
        monkeypatch.setattr(sm, "SCALP_REAL_RETRACE", False)
        sm._cooldowns["SCALP_FLOW"].clear()
        sm._scan_cycle()
        assert bought and len(bought[0]) == 2


class TestF4RetraceStopRefBreak:
    """شمعة الملء الارتدادي تكسر الوقف المرجعي بعد اللمس — الوقف أولًا (أسوأ ترتيب داخل الشمعة)."""

    def _host(self, clean_db, tg_off, monkeypatch, *, real=False, price_v=97.5):
        price = {"v": price_v}
        bought = []
        fake = {
            "db_query": vnz.db.query, "db_execute": vnz.db.execute,
            "log_and_notify": vnz.log_and_notify, "logger": vnz.logger,
            "get_live_price": lambda s: price["v"],
            "get_recent_candles": lambda s, tf, limit, min_candles=2: None,
            "fetch_ohlcv_raw": lambda s, tf, limit: (None, None),
            "binance_full_klines": lambda s, iv, limit: None,
            "binance_depth": lambda s, limit: None,
            "utc_now_iso": vnz.utc_now_iso, "fmt_price": vnz.fmt_price,
            "seconds_until_next_candle": lambda tf: 300.0,
            "is_trading_enabled": lambda: True,
            "is_real_mode": lambda: real,
            "risk_entry_block_reason": lambda: None,
            "symbol_has_active": lambda s: False,
            "get_paper_balance": vnz.get_paper_balance,
            "fee_rate": 0.001, "deviation_threshold": 0.006,
            "zigzag_pivots": vnz.zigzag_pivots,
            "close_signal_row": vnz.close_signal_row,
            "close_real_trade": vnz.close_real_trade,
            "account_partial_close": vnz._account_partial_close,
            "place_real_market_sell": vnz.place_real_market_sell,
            "place_real_stop_loss": lambda s, q, p: {"id": "S1"},
            "replace_real_stop": vnz._replace_real_stop,
            "cancel_real_order": vnz.cancel_real_order,
            "real_market_buy": lambda s, quote: bought.append((s, quote)) or
                {"id": "R1", "average": price["v"], "amount": quote / price["v"]},
            "real_free_usdt": lambda: 1000.0,
            "real_max_notional": lambda: 50.0,
            "real_adjust_amount": lambda ex, s, q: q,
            "real_min_amount": lambda mkt: 0.0,
            "real_min_cost": lambda mkt: 0.0,
            "real_market_rules": lambda s, ex: {},
            "binance_trade_exchange": lambda: object(),
            "watchlist": lambda: ["TEST/USDT"],
        }
        from strategies import manager as sm
        sm.attach_host(fake)
        for c in sm._counters.values():
            c.update({"signals": 0, "partials": 0, "early_exits": 0, "closes": {},
                      "rejects": {}, "last_signal_at": None, "last_signal_symbol": None})
        for d in sm._cooldowns.values():
            d.clear()
        return sm, price, bought

    def test_paper_break_closes_at_sl_ref(self, clean_db, tg_off, monkeypatch):
        """ورقي: لمست شمعة التأكيد الحد (99.4) ثم كسرت الوقف المرجعي (95.0) وأغلقت فوقه
        ⇒ الصفقة تُفتح ثم تُغلق فورًا بسعر الوقف المرجعي — خسارة معلنة."""
        sm, price, bought = self._host(clean_db, tg_off, monkeypatch)
        sm._retrace_orders["TEST/USDT"] = {
            "strategy": "SCALP_FLOW", "label": "انجلال التدفق", "symbol": "TEST/USDT",
            "limit": 97.4, "sl_ref": 95.0, "tp1": 100.0, "tp2": 101.5, "rr1": 1.0,
            "entry_ref": 99.0, "atr5": 1.0, "reason": "اختبار", "armed_ts": 0.0,
            "expires_ts": time.time() + 8 * 300, "meta": {"atr5": 1.0}}
        from strategies.base import ScalpContext
        k5 = [{"ts": 0.0, "open": 97.9, "high": 98.0, "low": 94.5, "close": 97.8,
               "volume": 10.0, "taker_base": None}]
        sm._manage_retrace("TEST/USDT", ScalpContext(
            symbol="TEST/USDT", now_ts=time.time(), k5=k5, k15=[],
            live_price=97.8, cvd_source="taker", atr5=1.0))
        row = vnz.db.query("SELECT * FROM signals", one=True)
        assert row is not None and row["status"] == "closed"
        assert math.isclose(float(row["close_price"]), 95.0, rel_tol=1e-9)
        assert float(row["pnl_usdt"]) < 0
        assert sm._counters["SCALP_FLOW"]["closes"].get("sl", 0) == 1

    def test_paper_gap_below_sl_ref_no_open(self, clean_db, tg_off, monkeypatch):
        """ورقي: ملء تحت الوقف المرجعي نفسه ⇒ لا فتح أصلًا + رفض معلن."""
        sm, price, bought = self._host(clean_db, tg_off, monkeypatch)
        sm._retrace_orders["TEST/USDT"] = {
            "strategy": "SCALP_FLOW", "label": "انجلال التدفق", "symbol": "TEST/USDT",
            "limit": 97.4, "sl_ref": 95.0, "tp1": 100.0, "tp2": 101.5, "rr1": 1.0,
            "entry_ref": 99.0, "atr5": 1.0, "reason": "اختبار", "armed_ts": 0.0,
            "expires_ts": time.time() + 8 * 300, "meta": {"atr5": 1.0}}
        from strategies.base import ScalpContext
        k5 = [{"ts": 0.0, "open": 94.0, "high": 97.9, "low": 93.5, "close": 97.8,
               "volume": 10.0, "taker_base": None}]
        sm._manage_retrace("TEST/USDT", ScalpContext(
            symbol="TEST/USDT", now_ts=time.time(), k5=k5, k15=[],
            live_price=97.8, cvd_source="taker", atr5=1.0))
        assert vnz.db.query("SELECT * FROM signals") == []
        assert "TEST/USDT" not in sm._retrace_orders

    def test_real_break_no_buy(self, clean_db, tg_off, monkeypatch):
        """حقيقي: شمعة التأكيد كسرت الوقف المرجعي ⇒ لا شراء أصلًا + تبريد إلغاء."""
        sm, price, bought = self._host(clean_db, tg_off, monkeypatch, real=True)
        sm._retrace_orders["TEST/USDT"] = {
            "strategy": "SCALP_FLOW", "label": "انجلال التدفق", "symbol": "TEST/USDT",
            "limit": 97.4, "sl_ref": 95.0, "tp1": 100.0, "tp2": 101.5, "rr1": 1.0,
            "entry_ref": 99.0, "atr5": 1.0, "reason": "اختبار", "armed_ts": 0.0,
            "expires_ts": time.time() + 8 * 300, "meta": {"atr5": 1.0}}
        from strategies.base import ScalpContext
        k5 = [{"ts": 0.0, "open": 97.9, "high": 98.0, "low": 94.5, "close": 97.8,
               "volume": 10.0, "taker_base": None}]
        sm._manage_retrace("TEST/USDT", ScalpContext(
            symbol="TEST/USDT", now_ts=time.time(), k5=k5, k15=[],
            live_price=97.8, cvd_source="taker", atr5=1.0))
        assert bought == []
        assert vnz.db.query("SELECT * FROM signals") == []
        assert "TEST/USDT" not in sm._retrace_orders


# ─────────────────────────────────────────────────────────────────────────────
# F5 — أمان اللوحة: مصادقة toggle + hmac + كلمة مرور ضعيفة + CSRF (P0)
# ─────────────────────────────────────────────────────────────────────────────

_RAW_TEST_CLIENT = vnz.app.test_client   # عميل خام ملتقط قبل ترقيع conftest (بلا رأس CSRF)


class TestF5DashboardSecurity:
    def _authed(self):
        monkey = {"u": "admin", "p": "secret9xY"}
        return monkey

    def test_every_route_requires_auth(self, monkeypatch):
        """كل مسار في url_map عدا /health يعيد 401 بلا مصادقة (GET وPOST بالرأس)."""
        monkeypatch.setattr(vnz, "DASHBOARD_PROTECTED", True)
        monkeypatch.setattr(vnz, "DASHBOARD_USERNAME", "admin")
        monkeypatch.setattr(vnz, "DASHBOARD_PASSWORD", "secret9xY")
        c = vnz.app.test_client()
        skip = {"/health"}
        checked = 0
        for rule in vnz.app.url_map.iter_rules():
            path = rule.rule
            if path in skip or path.startswith("/static"):
                continue
            methods = rule.methods - {"HEAD", "OPTIONS"}
            for m in methods:
                kw = {"headers": {"X-Requested-With": "EliottPanel"}} if m == "POST" else {}
                r = c.open(path, method=m, **kw)
                assert r.status_code == 401, f"{m} {path} → {r.status_code} بلا مصادقة"
                checked += 1
        assert checked >= 15

    def test_toggle_auth_and_csrf(self, clean_db, monkeypatch):
        """toggle: بلا مصادقة 401؛ بمصادقة وبلا رأس CSRF 403؛ بكلتيهما ينجح."""
        monkeypatch.setattr(vnz, "DASHBOARD_PROTECTED", True)
        monkeypatch.setattr(vnz, "DASHBOARD_USERNAME", "admin")
        monkeypatch.setattr(vnz, "DASHBOARD_PASSWORD", "secret9xY")
        monkeypatch.setattr(vnz, "TELEGRAM_BOT_TOKEN", "")
        raw = _RAW_TEST_CLIENT()
        assert raw.post("/api/trading/toggle",
                        auth=("admin", "secret9xY")).status_code == 403  # بلا رأس
        c = vnz.app.test_client()
        assert c.post("/api/trading/toggle").status_code == 401            # بلا مصادقة
        before = vnz.is_trading_enabled
        r = c.post("/api/trading/toggle", auth=("admin", "secret9xY"))
        assert r.status_code == 200
        assert vnz.is_trading_enabled == (not before)
        vnz.set_trading_enabled(before, "استعادة اختبار")

    def test_real_enable_blocked_on_weak_password(self, clean_db, monkeypatch):
        """AUTH_WEAK ⇒ تفعيل التداول الحقيقي يُرفض 403 حتى بمصادقة صحيحة ورأس CSRF."""
        monkeypatch.setattr(vnz, "DASHBOARD_PROTECTED", True)
        monkeypatch.setattr(vnz, "DASHBOARD_USERNAME", "admin")
        monkeypatch.setattr(vnz, "DASHBOARD_PASSWORD", "test123")   # ضعيفة عمدًا
        monkeypatch.setattr(vnz, "AUTH_WEAK", True)
        monkeypatch.setattr(vnz, "API_KEY", "k")
        monkeypatch.setattr(vnz, "API_SECRET", "s")
        c = vnz.app.test_client()
        r = c.post("/api/trading/real", auth=("admin", "test123"), json={"enable": True})
        assert r.status_code == 403
        assert "كلمة مرور" in r.get_json()["error"]

    def test_compare_digest_in_source(self):
        """المقارنة ثابتة الزمن في المصدر (hmac.compare_digest)."""
        import inspect
        s = inspect.getsource(vnz.require_dashboard_auth) + inspect.getsource(vnz._auth_ok)
        assert "compare_digest" in s


# ─────────────────────────────────────────────────────────────────────────────
# F6 — الإغلاق المزدوج المتسابق (P1)
# ─────────────────────────────────────────────────────────────────────────────

class TestF6DoubleCloseRace:
    def _open_row(self, fill=100.0, qty=10.0):
        vnz.db.execute(
            "INSERT INTO signals (symbol, direction, strategy_name, status, entry_price,"
            " fill_price, stop_loss, take_profit, quantity, notional_usdt, created_at,"
            " filled_at, initial_quantity, is_real) VALUES (%s,%s,%s,'open',%s,%s,%s,%s,%s,%s,%s,%s,%s,0)",
            ("TEST/USDT", "BULLISH", "Elliott_Fibonacci", fill, fill, 95.0, 130.0,
             qty, fill * qty, "2026-10-24T10:00:00Z", "2026-10-24T10:05:00Z", qty))
        return vnz.db.query("SELECT * FROM signals WHERE symbol='TEST/USDT'", one=True)

    def test_close_signal_row_idempotent(self, clean_db, tg_off):
        """إغلاق الصف نفسه مرتين بالقاموس نفسه: الرصيد الورقي يتغير مرة واحدة."""
        sig = self._open_row()
        bal0 = vnz.get_paper_balance()
        vnz.close_signal_row(sig, 105.0, "اختبار")
        bal1 = vnz.get_paper_balance()
        assert bal1 != bal0
        vnz.close_signal_row(sig, 105.0, "اختبار")   # الثاني مرفوض — لا محاسبة
        bal2 = vnz.get_paper_balance()
        assert bal2 == bal1, "الإغلاق المكرر يجب ألا يمس الرصيد"
        row = vnz.db.query("SELECT * FROM signals", one=True)
        assert row["status"] == "closed"
        assert vnz.db.query("SELECT COUNT(*) AS n FROM signals WHERE status='closed'")[0]["n"] == 1

    def test_partial_close_rejects_closed_row(self, clean_db, tg_off):
        """محاسبة رجل جزئية على صف مغلق: تعيد 0.0 ولا تمس الرصيد."""
        sig = self._open_row()
        vnz.close_signal_row(sig, 105.0, "اختبار")
        bal1 = vnz.get_paper_balance()
        out = vnz._account_partial_close(sig, 2.0, 106.0, "اختبار على صف مغلق")
        assert out == 0.0
        assert vnz.get_paper_balance() == bal1

    def test_execute_want_rowcount(self, clean_db, tg_off):
        """want_rowcount=True يعيد عدد الصفوف؛ الافتراضي None (لا تغيير نداءات قائمة)."""
        self._open_row()
        n = vnz.db.execute("UPDATE signals SET status='cancelled' WHERE status='open'",
                           want_rowcount=True)
        assert n == 1
        n2 = vnz.db.execute("UPDATE signals SET status='cancelled' WHERE status='open'",
                            want_rowcount=True)
        assert n2 == 0
        assert vnz.db.execute("UPDATE signals SET status='cancelled' WHERE status='open'") is None


# ─────────────────────────────────────────────────────────────────────────────
# F7 — الكشف الإليوتي على شموع مغلقة فقط (P1)
# ─────────────────────────────────────────────────────────────────────────────

class TestF7ClosedCandlesDetection:
    def _df(self, n=30, forming=True, period_sec=900):
        """شموع 15m: الأخيرة جارية (لم تُغلق) عند forming=True، ومغلقة عند False."""
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc)
        # مغلقة: آخر شمعة أُغلقت قبل اللحظة (open0 = now - n×period)
        # جارية: آخر شمعة فُتحت عند now ولم تُغلق (open0 = now - (n-1)×period)
        shift = (n - 1) if forming else n
        open0 = now - dt.timedelta(seconds=period_sec * shift)
        rows = []
        price = 100.0
        for i in range(n):
            ts = open0 + dt.timedelta(seconds=period_sec * i)
            price = price * (1.001 if i % 2 == 0 else 0.999)
            rows.append({"ts": ts.timestamp() * 1000, "open": price, "high": price * 1.002,
                         "low": price * 0.998, "close": price * 1.001, "volume": 10.0,
                         "timestamp": ts, "symbol": "TEST/USDT", "timeframe": "15m"})
        return pd.DataFrame(rows)

    def test_forming_candle_dropped_for_detector(self, monkeypatch):
        """شمعة جارية في الأخير ⇒ الكاشف يستقبل n-1 صفًا؛ مغلقة ⇒ n صفًا."""
        import unittest.mock as mock
        df = self._df(n=30, forming=True)
        assert len(df) == 30
        dropped = vnz._drop_forming_candle(df, "15m")
        assert len(dropped) == 29
        closed = self._df(n=30, forming=False)
        assert len(vnz._drop_forming_candle(closed, "15m")) == 30

    def test_no_timestamp_column_legacy(self):
        """بلا عمود timestamp ⇒ القائمة كما هي (سلوك قديم)."""
        df = self._df(n=10, forming=True).drop(columns=["timestamp"])
        assert len(vnz._drop_forming_candle(df, "15m")) == 10

    def test_detect_closed_only_off(self, monkeypatch):
        """DETECT_CLOSED_ONLY=0 ⇒ لا حذف أبدًا (السلوك القديم)."""
        monkeypatch.setattr(vnz, "DETECT_CLOSED_ONLY", False)
        df = self._df(n=10, forming=True)
        # scan_cycle يبني df_det = df حين العلم مطفأ — نفحص الشرط مباشرة
        df_det = vnz._drop_forming_candle(df, "15m") if vnz.DETECT_CLOSED_ONLY else df
        assert len(df_det) == 10

    def test_momentum_loop_not_started_when_closed_only(self, monkeypatch, clean_db):
        """DETECT_CLOSED_ONLY=1 ⇒ خيط نبض الحركة لا يُطلق عند الإقلاع."""
        started = []

        class _FakeThread:
            def __init__(self, target=None, daemon=False, name=None, **kw):
                started.append(name or "")
                self.daemon = daemon

            def start(self):
                pass

        monkeypatch.setattr(vnz.threading, "Thread", _FakeThread)
        monkeypatch.setattr(vnz, "SCAN_UNIVERSE_ENABLED", False)
        monkeypatch.setattr(vnz, "DETECT_CLOSED_ONLY", True)
        vnz.initialize_bot_services()
        assert "momentum-kicker" not in started
        assert "scan-loop" in started and "monitor-loop" in started
        started.clear()
        monkeypatch.setattr(vnz, "DETECT_CLOSED_ONLY", False)
        vnz.initialize_bot_services()
        assert "momentum-kicker" in started


# ─────────────────────────────────────────────────────────────────────────────
# F8 — حجم الصفقة عند رفع الحد الأدنى (P2)
# ─────────────────────────────────────────────────────────────────────────────

class TestF8MinNotionalRaise:
    def test_qty_raised_to_min_notional_survives(self, clean_db, tg_off):
        """رصيد 100 / دخول 5 / وقف 4 ⇒ الكمية تُرفع لأدنى قيمة (2.0) ولا تُرفض."""
        vnz.set_paper_balance(100.0)
        try:
            qty = vnz.compute_quantity("TEST/USDT", 5.0, 4.0)
            assert qty is not None, "فرع رفع الحد الأدنى يجب أن يعمل لا أن يُرفض دائمًا"
            assert math.isclose(qty, 2.0, rel_tol=1e-9)
        finally:
            vnz.set_paper_balance(10000.0)
