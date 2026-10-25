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
