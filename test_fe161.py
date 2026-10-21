#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fe161.py — اختبارات إصلاح انفجار الويب سوكت KeyError: 0 في FE1.6.1

الجذور: حقن FE1.4.2 كان يضع في markets_by_id قيمًا من نوع dict مفرد، بينما
safe_market في ccxt 4.4+ ينتظر قيمة قائمة [أسواق] (يقرأ len() ثم [0]) —
فكانت كل رسالة miniTicker/kline تنفجر بـ KeyError: 0 داخل after_interrupt
(«Exception in callback» في سجلات Render) ويموت تيار باينانس الأساسي
حتى ينهار التعاقب إلى gate.

الجولات:
  1) _index_markets_by_id: الشكل (معرف → [قائمة]) + إزالة ازدواجية الرمز/المعرف
  2) مسار ticker الحقيقي عبر ccxt.pro.binance.handle_message — لا انفجار وتُفسَّر
     التذكرة (رمز موحد + آخر سعر) — إعادة إنتاج استثناء السجلات حرفيًا
  3) مسار kline الحقيقي — شمعة تُخزَّن تحت الرمز الموحد بلا انفجار
  4) رمز غائب عن الأسواق المصنوعة (إدراج جديد) — سقوط آمن بلا انفجار
  5) ws_refresh_fabricated_markets: الفهرس يبقى بقوائم بعد تحديث المراقبة
  6) _prune_markets: يحافظ على قيم القوائم ويقرر بالرمز داخل القائمة

تشغيل: pytest test_fe161.py -v   (من داخل مجلد المشروع)
"""

import pytest

import vnz


# ─────────────────────────────────────────────────────────────────────────────
# تجهيزات
# ─────────────────────────────────────────────────────────────────────────────

class FakeWsClient:
    """عميل ويب سوكت وهمي يكفي مسارات handle_message لباينانس سبوت."""
    url = "wss://stream.binance.com:9443/stream?streams=btcusdt@miniTicker"
    subscriptions = {}
    resolved = []

    def resolve(self, result, message_hash=None, *args, **kwargs):
        FakeWsClient.resolved.append((message_hash, result))


def make_ex(symbols=("BTC/USDT", "APT/USDT")):
    """نسخة ccxt.pro.binance بأسواق مصنوعة مصغّرة — نفس فلسفة _ws_exchange بعد الإصلاح."""
    import ccxt.pro
    ex = ccxt.pro.binance({"enableRateLimit": False,
                           "options": {"defaultType": "spot",
                                       "fetchMarkets": ["spot"]}})
    fab = vnz._fabricate_ws_markets("binance", list(symbols))
    ex.markets = fab
    ex.markets_by_id = vnz._index_markets_by_id(fab)
    return ex


MINI_TICKER = {"e": "24hrMiniTicker", "E": 1699999999000, "s": "BTCUSDT",
               "c": "60000.00", "o": "59000.00", "h": "61000.00",
               "l": "58000.00", "v": "100.0", "q": "6000000.00"}

KLINE = {"e": "kline", "E": 1699999999000, "s": "APTUSDT",
         "k": {"t": 1699999800000, "T": 1699999899999, "s": "APTUSDT",
               "i": "15m", "o": "0.8300", "c": "0.8364", "h": "0.8400",
               "l": "0.8280", "v": "1200.0", "n": 55, "x": False,
               "q": "1000.0", "V": "600.0", "Q": "500.0"}}


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 1 — الفهرس
# ─────────────────────────────────────────────────────────────────────────────

class TestIndexMarketsById:

    def test_values_are_lists_keyed_by_raw_id(self):
        fab = vnz._fabricate_ws_markets("binance", ["BTC/USDT", "APT/USDT"])
        idx = vnz._index_markets_by_id(fab)
        assert set(idx.keys()) == {"BTCUSDT", "APTUSDT"}   # معرفات خام فقط — لا رموز موحدة
        assert idx["BTCUSDT"] == [fab["BTC/USDT"]]          # قائمة أسواق (اصطلاح ccxt 4.4+)
        assert isinstance(idx["BTCUSDT"], list)

    def test_dedupes_unified_and_id_double_keys(self):
        # fab يحوي مفتاحين لنفس السوق (الرمز الموحد + المعرف) — الفهرس يسجل السوق مرة واحدة
        fab = vnz._fabricate_ws_markets("binance", ["BTC/USDT"])
        assert "BTC/USDT" in fab and "BTCUSDT" in fab
        idx = vnz._index_markets_by_id(fab)
        assert idx["BTCUSDT"] == [fab["BTCUSDT"]]           # نفس الكائن مرة واحدة

    def test_okx_and_gate_id_formats(self):
        fab_okx = vnz._fabricate_ws_markets("okx", ["BTC/USDT"])
        idx_okx = vnz._index_markets_by_id(fab_okx)
        assert set(idx_okx.keys()) == {"BTC-USDT"}
        fab_gate = vnz._fabricate_ws_markets("gate", ["BTC/USDT"])
        idx_gate = vnz._index_markets_by_id(fab_gate)
        assert set(idx_gate.keys()) == {"BTC_USDT"}


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 2 — مسار ticker الحقيقي (إعادة إنتاج استثناء السجلات)
# ─────────────────────────────────────────────────────────────────────────────

class TestTickerPath:

    def test_mini_ticker_no_keyerror_and_parsed(self):
        ex = make_ex()
        FakeWsClient.resolved = []
        # الرسالة الملفوفة كما تصل من باينانس المدمج (combined stream)
        wrapped = {"stream": "btcusdt@miniTicker", "data": dict(MINI_TICKER)}
        ex.handle_message(FakeWsClient(), wrapped)          # قبل الإصلاح: KeyError: 0
        tickets = [(h, m) for h, m in FakeWsClient.resolved
                   if isinstance(m, dict) and m.get("symbol")]
        assert tickets, "التذكرة يجب أن تُحلَّل وتُحل (resolve)"
        t = tickets[0][1]
        assert t["symbol"] == "BTC/USDT"
        assert t["last"] == 60000.0

    def test_ticker_registered_in_ex_tickers(self):
        ex = make_ex()
        FakeWsClient.resolved = []
        ex.handle_message(FakeWsClient(), {"stream": "btcusdt@miniTicker",
                                           "data": dict(MINI_TICKER)})
        assert ex.tickers.get("BTC/USDT", {}).get("last") == 60000.0


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 3 — مسار الشموع (kline) الحقيقي
# ─────────────────────────────────────────────────────────────────────────────

class TestKlinePath:

    def test_kline_no_keyerror_and_stored(self):
        ex = make_ex()
        FakeWsClient.resolved = []
        wrapped = {"stream": "aptusdt@kline_15m", "data": dict(KLINE)}
        ex.handle_message(FakeWsClient(), wrapped)          # قبل الإصلاح: KeyError: 0
        assert "APT/USDT" in ex.ohlcvs, "الشمعة تُخزَّن تحت الرمز الموحد"
        candles = ex.ohlcvs["APT/USDT"].get("15m")
        assert candles is not None and len(candles) == 1
        ts, o, h, l, c, v = candles[0]
        assert (o, h, l, c) == (0.83, 0.84, 0.828, 0.8364)


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 4 — رمز غائب عن الأسواق المصنوعة (سقوط آمن)
# ─────────────────────────────────────────────────────────────────────────────

class TestUnknownSymbol:

    def test_new_listing_ticker_does_not_crash(self):
        ex = make_ex(("BTC/USDT",))
        FakeWsClient.resolved = []
        # عملة مُدرجة حديثًا ليست في أسواقنا المصنوعة
        fresh = dict(MINI_TICKER, s="NEWCOINUSDT", c="1.5")
        ex.handle_message(FakeWsClient(), {"stream": "newcoinusdt@miniTicker",
                                           "data": fresh})  # لا استثناء
        assert any(isinstance(m, dict) and m.get("symbol") == "NEWCOINUSDT"
                   for _, m in FakeWsClient.resolved)


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 5 — تحديث الأسواق بعد تغيير المراقبة
# ─────────────────────────────────────────────────────────────────────────────

class TestRefreshKeepsListConvention:

    def test_refresh_fabricated_markets_list_values(self, monkeypatch):
        ex = make_ex(("BTC/USDT",))
        vnz._ws_exchanges["binance"] = ex
        try:
            vnz.watchlist[:] = ["NEWCOIN/USDT", "BTC/USDT"]
            vnz.ws_refresh_fabricated_markets()
            assert "NEWCOINUSDT" in ex.markets_by_id
            # الاصطلاح الجديد يبقى قوائم — لا dict مفردة
            assert isinstance(ex.markets_by_id["NEWCOINUSDT"], list)
            assert isinstance(ex.markets_by_id["BTCUSDT"], list)
            assert ex.markets_by_id["NEWCOINUSDT"][0]["symbol"] == "NEWCOIN/USDT"
        finally:
            vnz._ws_exchanges.pop("binance", None)


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 6 — التقليم يفهم القوائم
# ─────────────────────────────────────────────────────────────────────────────

class FakePruneEx:
    def __init__(self, markets, by_id):
        self.markets = markets
        self.markets_by_id = by_id


class TestPruneListValues:

    def test_prune_keeps_list_valued_entries(self, monkeypatch):
        fab = vnz._fabricate_ws_markets("binance", ["BTC/USDT", "APT/USDT"])
        by_id = vnz._index_markets_by_id(fab)
        # أسواق أكبر من العتبة حتى يعمل التقليم فعليًا
        markets = dict(fab)
        for i in range(500):
            markets[f"FILL{i}USDT"] = {"id": f"FILL{i}USDT", "symbol": f"FILL{i}/USDT",
                                       "type": "spot", "spot": True}
        ex = FakePruneEx(markets, dict(by_id))
        monkeypatch.setattr(vnz, "MEM_PRUNE_MARKETS", 100)
        kept_n = vnz.prune_markets(ex, ["BTC/USDT"])
        assert kept_n > 0
        # معرفات الأسواق المحفوظة بقيت بقيم قوائم
        assert isinstance(ex.markets_by_id.get("BTCUSDT"), list)
        assert ex.markets_by_id["BTCUSDT"][0]["symbol"] == "BTC/USDT"
        # الرمز المهمل حُذف من الفهرس
        assert "APTUSDT" not in ex.markets_by_id
