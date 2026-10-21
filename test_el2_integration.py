#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات EL2.0.0 — تكامل المدير المتوازي مع المحرك واللوحة
=============================================================
  1) دورة حياة صفقة سكالب كاملة (ورقي): فتح بسعر حي → جزئي 50% عند TP1 + BE
     → إغلاق عند TP2 بمحاسبة صحيحة + تبريد رمز
  2) وقف-أولًا: الشمعة التي تلمس الوقف والهدف معًا تغلق خاسرة (عقيدة محمية)
  3) بوابات الدخول: زر التداول/سقف الصفقات/الرمز المشغول/التبريد
  4) الحجم: مخاطرة معقولة مقيدة بسقف القيمة (درس FE1.7.0 ضد الرافعة الضمنية)
  5) الخروج المبكر: انهيار بنية القيمة يغلق صفقة S2
  6) العزل الحرفي: monitor_step وreconcile_live_targets لا يلمسان صفوف السكالب
     والسكالب لا يلمس صفوف المحرك (سلطان مزدوج = كوارث محاسبية)
  7) النقاط: /api/scalp + كتلة scalp في /health و/api/all + بوابة تلغرام
  8) اللوحة: قسم الاستراتيجيات المتوازية + شارات الصفوف + تزامن الإصدار
"""

import inspect
import json

import pandas as pd
import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة
import panel

from strategies import manager as sm
from strategies.base import ScalpConfig, ScalpContext, ScalpSignal


# ─────────────────────────────────────────────────────────────────────────────
# تجهيزات
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def clean_db(monkeypatch):
    """قاعدة SQLite مؤقتة لكل اختبار — عزل كامل (نمط المستودع نفسه)."""
    monkeypatch.setattr(vnz, "USE_POSTGRES", False)
    import sqlite3
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    old = vnz.db.conn
    vnz.db.conn = conn
    vnz.init_db()
    yield
    vnz.db.conn = old


@pytest.fixture()
def tg_off(monkeypatch):
    monkeypatch.setattr(vnz, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(vnz, "TELEGRAM_CHAT_ID", "")
    monkeypatch.setattr(vnz, "_tg_dedup", {})
    yield


class PriceHolder:
    """حامل سعر/شمعة قابل للتعديل بين دورات المراقبة."""
    def __init__(self, price=100.0, high=None, low=None):
        self.price = price
        self.high = high if high is not None else price
        self.low = low if low is not None else price

    def df(self):
        return pd.DataFrame({"high": [self.high], "low": [self.low],
                             "close": [self.price], "open": [self.price],
                             "volume": [1.0]})


@pytest.fixture()
def host(clean_db, tg_off, monkeypatch):
    """مضيف حقن كامل مبني على vnz الحقيقي مع أسعار قابلة للتحكم."""
    ph = PriceHolder()
    fake = {
        "db_query": vnz.db.query, "db_execute": vnz.db.execute,
        "log_and_notify": vnz.log_and_notify, "logger": vnz.logger,
        "get_live_price": lambda s: ph.price,
        "get_recent_candles": lambda s, tf, limit, min_candles=2: ph.df(),
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
        "real_min_amount": vnz.real_min_amount, "real_min_cost": vnz.real_min_cost,
        "real_market_rules": vnz.real_market_rules,
        "binance_trade_exchange": vnz.binance_trade_exchange,
        "watchlist": lambda: ["TEST/USDT", "BTC/USDT"],
    }
    sm.attach_host(fake)
    # تصفير حالة المدير بين الاختبارات
    for c in sm._counters.values():
        c.update({"signals": 0, "partials": 0, "early_exits": 0, "closes": {},
                  "rejects": {}, "last_signal_at": None, "last_signal_symbol": None})
    for d in sm._cooldowns.values():
        d.clear()
    sm._state.update({"last_scan_at": None, "last_scan_ts": 0.0, "cycles": 0,
                      "last_error": "", "cvd_source_last": ""})
    yield {"fake": fake, "prices": ph}


def make_signal(symbol="TEST/USDT", entry=100.0, sl=98.5, tp1=103.0, tp2=106.0):
    return ScalpSignal(strategy="SCALP_FLOW", label="⚡ انجلال التدفق", symbol=symbol,
                       entry_ref=entry, sl=sl, tp1=tp1, tp2=tp2, rr1=1.8,
                       reason="اختبار", meta={"atr5": 1.0, "cvd_source": "taker",
                                              "entry_ref": entry})


# ─────────────────────────────────────────────────────────────────────────────
# 1) دورة الحياة الكاملة (ورقي)
# ─────────────────────────────────────────────────────────────────────────────

def test_scalp_full_lifecycle_open_partial_be_then_tp2(host):
    sig = make_signal()
    assert sm._open_position(sig) is True
    rows = vnz.db.query("SELECT * FROM signals WHERE strategy_name='SCALP_FLOW'")
    assert len(rows) == 1
    r = rows[0]
    assert r["status"] == "open" and r["direction"] == "BULLISH"
    assert float(r["fill_price"]) == 100.0
    assert float(r["take_profit"]) == 106.0 and float(r["tp1"]) == 103.0
    meta = json.loads(r["meta_json"])
    assert meta["partial_done"] is False and meta["be_done"] is False

    # شمعة تلمس TP1 دون الوقف → جزئي 50% + BE
    host["prices"].high, host["prices"].low = 103.5, 99.5
    st = sm._monitor_cycle()
    assert st["partial"] == 1
    r = vnz.db.query("SELECT * FROM signals WHERE strategy_name='SCALP_FLOW'")[0]
    assert float(r["quantity"]) == pytest.approx(6.0)          # 50% من 12
    assert float(r["stop_loss"]) == pytest.approx(100.0)       # BE عند نقطة الدخول
    assert float(r["realized_pnl_usdt"]) > 0
    meta = json.loads(r["meta_json"])
    assert meta["partial_done"] is True and meta["be_done"] is True

    # شمعة تلمس TP2 → إغلاق المتبقي + تبريد الرمز (السعر الحي يصعد معها —
    # لو بقي عند الدخول لتمس وقف BE وهو سلوك المدير الصحيح)
    host["prices"].price, host["prices"].high, host["prices"].low = 106.2, 106.5, 101.0
    st = sm._monitor_cycle()
    assert st["tp2"] == 1
    r = vnz.db.query("SELECT * FROM signals WHERE strategy_name='SCALP_FLOW'")[0]
    assert r["status"] == "closed"
    assert float(r["pnl_usdt"]) > 0                            # صفقة رابحة صافية
    assert sm._cooldown_left("SCALP_FLOW", "TEST/USDT") > 0
    assert sm._counters["SCALP_FLOW"]["closes"].get("tp") == 1
    assert sm._counters["SCALP_FLOW"]["partials"] == 1


def test_scalp_stop_loss_first_when_candle_touches_both(host):
    sm._open_position(make_signal())
    # شمعة عنيفة: تلمس الوقف والهدف الأول معًا — الوقف أولًا دائمًا
    host["prices"].high, host["prices"].low = 103.5, 98.0
    st = sm._monitor_cycle()
    assert st["sl"] == 1 and st["partial"] == 0
    r = vnz.db.query("SELECT * FROM signals WHERE strategy_name='SCALP_FLOW'")[0]
    assert r["status"] == "closed"
    assert float(r["pnl_usdt"]) < 0                            # خسارة محسوبة
    assert float(r["close_price"]) == pytest.approx(98.5)
    assert sm._counters["SCALP_FLOW"]["closes"].get("sl") == 1


# ─────────────────────────────────────────────────────────────────────────────
# 2) الحجم — سقف القيمة يمنع الرافعة الضمنية
# ─────────────────────────────────────────────────────────────────────────────

def test_size_position_capped_notional(host):
    # رصيد 10000 × مخاطرة 0.75% = 75$ / (وقف 1.5) = 50 وحدة → قيمة 5000 → تُقص 1200
    qty, notional, why = sm._size_position(100.0, 98.5)
    assert why == ""
    assert notional == pytest.approx(1200.0)
    assert qty == pytest.approx(12.0)


def test_size_position_rejects_inverted_stop(host):
    qty, notional, why = sm._size_position(100.0, 101.0)
    assert qty is None and "غير منطقية" in why


def test_size_position_rejects_dust(host, monkeypatch):
    # رصيد شبه فارغ → سقف القيمة دون الحد الأدنى → رفض صادق
    monkeypatch.setitem(sm.HOST, "get_paper_balance", lambda: 20.0)
    qty, notional, why = sm._size_position(100.0, 99.999)
    assert qty is None and "الحد الأدنى" in why


# ─────────────────────────────────────────────────────────────────────────────
# 3) بوابات الدخول
# ─────────────────────────────────────────────────────────────────────────────

def test_gates_trading_disabled(host, monkeypatch):
    monkeypatch.setitem(sm.HOST, "is_trading_enabled", lambda: False)
    ok, why = sm._entry_gates("SCALP_FLOW", "TEST/USDT")
    assert not ok and "زر التداول" in why


def test_gates_max_open(host):
    sm._open_position(make_signal())
    sm._open_position(make_signal(symbol="BTC/USDT"))
    ok, why = sm._entry_gates("SCALP_FLOW", "SOL/USDT")
    assert not ok and "سقف" in why


def test_gates_symbol_busy(host, monkeypatch):
    monkeypatch.setitem(sm.HOST, "symbol_has_active", lambda s: True)
    ok, why = sm._entry_gates("SCALP_FLOW", "TEST/USDT")
    assert not ok and "نشطة" in why


def test_gates_cooldown(host):
    sm._cooldown_set("SCALP_FLOW", "TEST/USDT")
    ok, why = sm._entry_gates("SCALP_FLOW", "TEST/USDT")
    assert not ok and "تبريد" in why
    assert sm._cooldown_left("SCALP_FLOW", "TEST/USDT") > 0


def test_gates_engine_risk_blocker(host, monkeypatch):
    monkeypatch.setitem(sm.HOST, "risk_entry_block_reason", lambda: "حد الخسارة اليومي")
    ok, why = sm._entry_gates("SCALP_FLOW", "TEST/USDT")
    assert not ok and "قاطع مخاطر" in why


# ─────────────────────────────────────────────────────────────────────────────
# 4) الخروج المبكر — انهيار بنية القيمة
# ─────────────────────────────────────────────────────────────────────────────

def test_early_exit_profile_structure_collapse(host, monkeypatch):
    sig = make_signal()
    sig.strategy = "SCALP_PROFILE"
    sig.meta["fail_level"] = 97.0
    assert sm._open_position(sig) is True
    # سياق مصنوع: آخر إغلاق 96 تحت مستوى الفشل 97
    k5 = [{"ts": i * 300000.0, "open": 100.0, "high": 100.5, "low": 99.5,
           "close": 100.0, "volume": 10.0, "taker_base": 5.0} for i in range(70)]
    k5[-1]["close"] = 96.0
    ctx = ScalpContext(symbol="TEST/USDT", now_ts=1e9, k5=k5, k15=[],
                       live_price=96.0, cvd_source="proxy", atr5=1.0,
                       extra={"fee_rate": 0.001})
    monkeypatch.setattr(sm, "_build_ctx", lambda s: ctx)
    sm._early_exits_all()
    r = vnz.db.query("SELECT * FROM signals WHERE strategy_name='SCALP_PROFILE'")[0]
    assert r["status"] == "closed"
    assert "انهيار بنية القيمة" in (r["close_reason"] or "")
    assert sm._counters["SCALP_PROFILE"]["early_exits"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 5) العزل الحرفي بين دورتي الحياة
# ─────────────────────────────────────────────────────────────────────────────

def test_monitor_step_isolated_from_scalp_rows(clean_db, tg_off, monkeypatch):
    """صف سكالب مفتوح لا يلمسه monitor_step إطلاقًا — حتى مع شمعة قاتلة."""
    now_iso = vnz.utc_now_iso()
    vnz.db.execute(
        "INSERT INTO signals (symbol, direction, strategy_name, status, entry_price, fill_price,"
        " stop_loss, take_profit, tp1, tp2, quantity, notional_usdt, rr_ratio, meta_json,"
        " created_at, filled_at, initial_quantity, is_real, peak_price)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        ("TEST/USDT", "BULLISH", "SCALP_FLOW", "open", 100.0, 100.0, 98.5, 106.0,
         103.0, 106.0, 12.0, 1200.0, 1.8, json.dumps({"partial_done": False}),
         now_iso, now_iso, 12.0, 0, 100.0))
    # شمعة تتجاوز الوقف والهدفين — لو قُرئ الصف لأُغلق
    df = pd.DataFrame({"high": [200.0], "low": [1.0], "close": [150.0],
                       "open": [100.0], "volume": [1.0]})
    monkeypatch.setattr(vnz, "get_recent_candles", lambda *a, **k: df)
    vnz.monitor_step()
    r = vnz.db.query("SELECT * FROM signals WHERE strategy_name='SCALP_FLOW'")[0]
    assert r["status"] == "open"                                # لم يُمس
    assert float(r["quantity"]) == 12.0
    assert "strategy_name='Elliott_Fibonacci'" in inspect.getsource(vnz.monitor_step)


def test_reconcile_targets_isolated_from_scalp_rows(clean_db, tg_off, monkeypatch):
    """سقف الأسبوع عقيدة المحرك — صفوف السكالب أهدافها ATRية يملكها مديرها."""
    monkeypatch.setattr(vnz, "weekly_high", lambda s: 50.0)     # يطغى على مصيدة conftest
    vnz._tp_week_cache.clear()
    now_iso = vnz.utc_now_iso()
    for strat in ("SCALP_FLOW", "Elliott_Fibonacci"):
        vnz.db.execute(
            "INSERT INTO signals (symbol, direction, strategy_name, status, entry_price, fill_price,"
            " stop_loss, take_profit, quantity, notional_usdt, rr_ratio, created_at, filled_at,"
            " initial_quantity, is_real)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            ("TEST/USDT", "BULLISH", strat, "open", 100.0, 100.0, 98.5, 104.0,
             12.0, 1200.0, 1.8, now_iso, now_iso, 12.0, 0))
    vnz.reconcile_live_targets()
    rows = {r["strategy_name"]: r for r in vnz.db.query(
        "SELECT strategy_name, take_profit FROM signals WHERE status='open'")}
    assert float(rows["SCALP_FLOW"]["take_profit"]) == pytest.approx(104.0)   # لم يُقص
    assert float(rows["Elliott_Fibonacci"]["take_profit"]) == pytest.approx(50.0)  # قُصّ كعادته


# ─────────────────────────────────────────────────────────────────────────────
# 6) النقاط والبوابات واللوحة
# ─────────────────────────────────────────────────────────────────────────────

def test_telegram_gate_passes_scalp_types():
    assert vnz.telegram_gate("SCALP_OPEN") is True
    assert vnz.telegram_gate("SCALP_PARTIAL") is True
    assert vnz.telegram_gate("SCALP_CLOSE") is True


def test_api_scalp_endpoint(host):
    c = vnz.app.test_client()
    resp = c.get("/api/scalp")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "scalp" in data
    assert data["scalp"]["enabled"] is True
    assert "SCALP_FLOW" in data["scalp"]["strategies"]
    assert "config" in data["scalp"]


def test_health_includes_scalp_block(host):
    c = vnz.app.test_client()
    h = c.get("/health").get_json()
    assert "scalp" in h
    assert h["scalp"]["enabled"] is True


def test_api_all_includes_scalp(host):
    c = vnz.app.test_client()
    d = c.get("/api/all").get_json()
    assert "scalp" in d
    assert d["scalp"]["exec_tf"] == "5m"


def test_snapshot_shape(host):
    snap = sm.snapshot()
    for key in ("enabled", "running", "exec_tf", "symbols", "config", "state", "strategies"):
        assert key in snap
    assert set(snap["strategies"].keys()) == {"SCALP_FLOW", "SCALP_PROFILE"}


def test_panel_has_scalp_section_and_chips():
    html = panel.PANEL_HTML
    assert "الاستراتيجيات المتوازية" in html
    assert "scalp-box" in html
    assert "renderScalp" in html
    assert "stratChip" in html
    assert "SCALP_FLOW" in html and "SCALP_PROFILE" in html


def test_version_sync():
    assert vnz.BOT_VERSION == "EL2.0.0"
    assert panel.BOT_VERSION == "EL2.0.0"
