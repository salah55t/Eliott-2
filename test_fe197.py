#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات FE1.9.7 «تيك خام»
================================
الطلب: «جلب الأسعار ويب سوكت لحظية لأقصى درجة ممكنة».
الترقية: طبقة تيار باينانس الخام فوق ccxt.pro (لا تغيير فيها — احتياط حي):
  • @trade لكل قائمة الكشف — سعر على كل صفقة فعلية (أجزاء الثانية)
  • @kline_<فريم التنفيذ> لرموز الصفقات — الشمعة الجارية تتحدث داخل الشريط
  • استيقاظ فوري لحلقة المراقبة عند لمس تيك لمستوى تنفيذ (معلق ← دخول،
    مفتوح ← وقف/هدف) — نفس monitor_step حرفيًا، فقط الاستدعاء لحظي
  • نبض الحركة 5ث ← 2ث (قراءة ذاكرة بلا REST)

ما يُغطيه الملف:
  1) أسماء التيارات والرابط المدمج وخريطة المعرفات (نقية)
  2) رسالة trade حية ← تحديث السعر بمصدر binance-tick + عدادات
  3) رسالة kline حية ← دمج الشمعة الجارية مع بذرة مغلقة (لا محو تاريخ)
  4) شرط الاستيقاظ النقي (معلق/مفتوح/بلا مستويات)
  5) تكامل: تيك لمس الدخول يوقظ حد المراقبة، وتيك فوق الدخول لا يوقظها
  6) /api/ws/status يكشف كتلة raw
  7) تزامن الإصدار FE1.9.7 (vnz + panel)

التصميم تساهلي: websockets غائبة أو RAW_TICK_WS=0 ← السلوك الحالي كما هو،
وفشل التيك الخام لا يمس طبقة ccxt.pro إطلاقًا.
"""

import json

import pandas as pd
import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة
import panel


# ─────────────────────────────────────────────────────────────────────────────
# أدوات مساعدة
# ─────────────────────────────────────────────────────────────────────────────

def leg_candles(start: float, end: float, n: int, t0: int) -> list:
    rows = []
    step = (end - start) / n
    for i in range(n):
        o = start + step * i
        c = start + step * (i + 1)
        h = max(o, c) * 1.0005
        lo = min(o, c) * 0.9995
        rows.append((t0 + i * 3600_000, o, h, lo, c, 1000.0))
    return rows


def impulse_df() -> pd.DataFrame:
    """دافع صاعد مصطنع: P0=100 P1=120 P2=110 P3=140 P4=125 P5=135."""
    pts = [(100.0, 120.0, 5), (120.0, 110.0, 4), (110.0, 140.0, 6),
           (140.0, 125.0, 4), (125.0, 135.0, 4)]
    rows, t = [], 1_700_000_000_000
    for a, b, n in pts:
        rows += leg_candles(a, b, n, t)
        t += n * 3600_000
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df["symbol"] = "TEST/USDT"
    df["timeframe"] = "1h"
    return df[["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]]


from engine.pattern_detector import DetectorConfig, PivotDetector

DET = PivotDetector(DetectorConfig(method="zigzag", deviation_threshold=0.01,
                                   price_source="close", min_wave_bars=2))


@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    """قاعدة SQLite مؤقتة لكل اختبار — عزل كامل."""
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
def raw_env(tmp_path, monkeypatch):
    """عزل حالة التيك الخام: مخزن السعر/الشموع/المعرفات/المستويات نظيفة."""
    monkeypatch.setattr(vnz, "_raw_mid_to_symbol", {})
    monkeypatch.setattr(vnz, "_raw_trigger_levels", {})
    monkeypatch.setattr(vnz, "_ws_price", {})
    monkeypatch.setattr(vnz, "_ws_candles", {})
    vnz._monitor_kick_event.clear()
    yield


# ─────────────────────────────────────────────────────────────────────────────
# 1) بناء التيارات (نقية)
# ─────────────────────────────────────────────────────────────────────────────

def test_stream_names_url_and_mid_map():
    wanted = {"BTC/USDT", "PUMP/USDT", "ETH/USDT"}
    full = {"PUMP/USDT"}
    names = vnz.binance_raw_stream_names(wanted, full, "5m")
    # @trade لكل المطلوب (مرتبة) و@kline للنشط وحده
    assert names == ["btcusdt@trade", "ethusdt@trade",
                     "pumpusdt@trade", "pumpusdt@kline_5m"]
    url = vnz.binance_raw_url(names)
    assert url.startswith("wss://stream.binance.com:9443/stream?streams=")
    assert "ethusdt@trade/pumpusdt@trade/pumpusdt@kline_5m" in url
    mids = vnz.binance_raw_mid_map(wanted | full)
    assert mids["pumpusdt"] == "PUMP/USDT"
    assert mids["btcusdt"] == "BTC/USDT"


# ─────────────────────────────────────────────────────────────────────────────
# 2-3) معالج الرسائل الحية
# ─────────────────────────────────────────────────────────────────────────────

def test_raw_trade_message_updates_price(raw_env):
    vnz._raw_mid_to_symbol.update({"pumpusdt": "PUMP/USDT"})
    msg = json.dumps({
        "stream": "pumpusdt@trade",
        "data": {"e": "trade", "s": "PUMPUSDT", "p": "0.004571", "q": "3967",
                 "T": 1700000000000},
    })
    kind = vnz.raw_handle_message(msg)
    assert kind == "trade"
    with vnz._ws_lock:
        entry = vnz._ws_price.get("PUMP/USDT")
    assert entry and entry["price"] == pytest.approx(0.004571)
    assert entry["source"] == "binance-tick"
    snap = vnz.raw_status_snapshot()
    assert snap["ticks"] == 1


def test_raw_trade_bad_price_ignored(raw_env):
    vnz._raw_mid_to_symbol.update({"pumpusdt": "PUMP/USDT"})
    assert vnz.raw_handle_message(json.dumps(
        {"stream": "pumpusdt@trade", "data": {"p": "0"}}) ) == ""       # صفر مرفوض
    assert vnz.raw_handle_message(json.dumps(
        {"stream": "pumpusdt@trade", "data": {"p": "abc"}})) == ""      # غير رقمي
    assert vnz.raw_handle_message("not-json") == ""                      # تالفة
    assert vnz.raw_handle_message(json.dumps(
        {"stream": "pumpusdt@depth", "data": {}})) == ""                 # تيار آخر


def test_raw_kline_merges_current_candle_keeps_seed(raw_env):
    """الدمج بنفس دمج ws_apply_ohlcv: التيك يرسل الشمعة الجارية وحدها فلا يمحو
    بذرة الشموع المغلقة — التاريخ يبقى والجارية تتحدث داخل الشريط."""
    sym = "TEST/USDT"
    vnz._raw_mid_to_symbol.update({"testusdt": sym})
    # بذرة: شمعة مغلقة سابقة + جارية أولى
    seed = [[1_700_000_000_000, 100.0, 105.0, 99.0, 104.0, 1000.0],
            [1_700_000_300_000, 104.0, 106.0, 103.0, 105.0, 1200.0]]
    assert vnz.ws_apply_ohlcv(sym, seed, "binance")
    # تيك kline للشمعة الجارية نفسها بقيم محدثة داخل الشريط
    msg = json.dumps({
        "stream": "testusdt@kline_1h",
        "data": {"k": {"t": 1_700_000_300_000, "o": "104.0", "h": "106.6",
                       "l": "102.8", "c": "105.4", "v": "1500.0", "x": False}},
    })
    assert vnz.raw_handle_message(msg) == "kline"
    with vnz._ws_lock:
        cached = vnz._ws_candles[sym]["candles"]
    assert len(cached) == 2                      # التاريخ لم يُمحُ
    assert cached[-1][2] == pytest.approx(106.6)  # high محدث داخل الشريط
    assert cached[-1][3] == pytest.approx(102.8)  # low محدث — أرضية حية للملء
    assert cached[0][0] == 1_700_000_000_000      # الشمعة المغلقة سليمة
    assert vnz.raw_status_snapshot()["klines"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 4-5) شرط الاستيقاظ الفوري + التكامل
# ─────────────────────────────────────────────────────────────────────────────

def test_raw_should_kick_monitor_pure():
    pend = {"status": "pending", "entry": 100.0, "sl": 95.0, "tp": 110.0}
    opn = {"status": "open", "entry": 100.0, "sl": 95.0, "tp": 110.0}
    assert vnz.raw_should_kick_monitor(100.0, pend) is True    # لمس الدخول
    assert vnz.raw_should_kick_monitor(99.5, pend) is True     # تحت الدخول
    assert vnz.raw_should_kick_monitor(100.01, pend) is False  # فوق الدخول
    assert vnz.raw_should_kick_monitor(95.0, opn) is True      # لمس الوقف
    assert vnz.raw_should_kick_monitor(110.0, opn) is True     # لمس الهدف
    assert vnz.raw_should_kick_monitor(101.0, opn) is False    # بينهما
    assert vnz.raw_should_kick_monitor(100.0, None) is False
    assert vnz.raw_should_kick_monitor(100.0, {"status": "closed"}) is False
    assert vnz.raw_should_kick_monitor("bad", pend) is False


def _make_pending(symbol: str = "TEST/USDT") -> None:
    df = impulse_df()
    df["symbol"] = symbol
    s = [x for x in DET.scan(df) if x.direction == "BULLISH"][-1]
    assert vnz.create_pending_signal(symbol, s)


def test_trade_touching_entry_kicks_monitor(clean_db, raw_env):
    """تكامل دورة الحياة: معلق ولد ← تيك لمس الدخول ← حد المراقبة يستيقظ."""
    _make_pending("TEST/USDT")
    vnz.refresh_raw_trigger_levels()
    with vnz._raw_state_lock:
        levels = dict(vnz._raw_trigger_levels)
    assert "TEST/USDT" in levels, "مستويات الاستيقاظ لم تتحدث عند الولادة"
    vnz._raw_mid_to_symbol.update({"testusdt": "TEST/USDT"})
    # تيك فوق الدخول — لا استيقاظ
    entry = float(levels["TEST/USDT"][0]["entry"])
    above = json.dumps({"stream": "testusdt@trade",
                        "data": {"p": repr(entry * 1.05)}})
    assert vnz.raw_handle_message(above) == "trade"
    assert not vnz._monitor_kick_event.is_set()
    # تيك يلمس الدخول — استيقاظ فوري
    touch = json.dumps({"stream": "testusdt@trade",
                        "data": {"p": repr(entry)}})
    assert vnz.raw_handle_message(touch) == "trade"
    assert vnz._monitor_kick_event.is_set()
    snap = vnz.raw_status_snapshot()
    assert snap["monitor_kicks"] >= 1


def test_open_trade_sl_tp_tick_kicks_monitor(clean_db, raw_env):
    """المفتوح: تيك ≤ الوقف أو ≥ الهدف يوقظ المراقبة لحماية/جني لحظيًا."""
    _make_pending("TEST/USDT")
    vnz.db.execute(
        "UPDATE signals SET status='open', fill_price=(SELECT entry_price FROM signals WHERE id=(SELECT MAX(id) FROM signals))"
        " WHERE status='pending'")
    vnz.refresh_raw_trigger_levels()
    vnz._raw_mid_to_symbol.update({"testusdt": "TEST/USDT"})
    with vnz._raw_state_lock:
        lv = vnz._raw_trigger_levels["TEST/USDT"][0]
    assert lv["status"] == "open"
    tp = float(lv["tp"])
    hit_tp = json.dumps({"stream": "testusdt@trade",
                         "data": {"p": repr(tp * 1.001)}})
    assert vnz.raw_handle_message(hit_tp) == "trade"
    assert vnz._monitor_kick_event.is_set()


# ─────────────────────────────────────────────────────────────────────────────
# 6-7) التشخيص + الإصدار
# ─────────────────────────────────────────────────────────────────────────────

def test_ws_status_exposes_raw_block():
    client = vnz.app.test_client()
    r = client.get("/api/ws/status")
    assert r.status_code == 200
    body = r.get_json()
    raw = body.get("raw")
    assert isinstance(raw, dict)
    for key in ("enabled", "connected", "ticks", "klines", "reconnects",
                "monitor_kicks", "age_sec", "n_streams"):
        assert key in raw, f"حقل {key} غائب من كتلة raw"


def test_version_pair():
    assert vnz.BOT_VERSION == "EL2.2.0"
    assert panel.BOT_VERSION == "EL2.2.0"


def test_panel_has_tick_badge():
    """شارة التيك الخام في اللوحة + رقاقة العداد."""
    html = panel.PANEL_HTML
    assert "تيك خام" in html and "raw" in html
