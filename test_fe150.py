#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fe150.py — اختبارات ماسح الكون الكامل + إصلاحات مراجعة اللوحة FE1.5.0

تسع جولات:
  1) زيجزاج الفحص: تأكيد القمم/القيعان بعتبة الانعكاس + الاتجاه الأحادي
  2) درجة الملاءمة: موجة اصطناعية + بيانات ناقصة/فاسدة
  3) تطبيع السيولة وترشيح الكون: مستقر/مرفوع/رقيق/سبريد واسع/مدى ميت
  4) run_universe_scan كاملة: تدفق مزيف — ترشيح/تحليل/ترتيب/تطبيق/حفظ بالحالة
  5) الحفاظ الإجباري على الرموز النشطة + الاستعادة عند الإقلاع
  6) إجهاض 418/429: النتائج السابقة محفوظة والحالة صافية
  7) WS: لا «connecting» عالقة مع تدفق حديث + تنظيف اللقطة من البقايا + أسواق مصنوعة
  8) نقاط API: /api/scan/run محمية + /health ملخص بلا نتائج + /api/all بالنتائج
  9) الحماية واللوحة: HEAD / عام 200 وGET / محمي 401 + signals/pnl_history محميتان
     + PANEL_HTML يحوي قسم الفحص وesc و.tbl-wrap

تشغيل: pytest test_fe150.py -v   (من داخل مجلد المشروع)
"""

import base64
import json
import threading
import time

import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة (الافتراضي في الإنتاج admin/test123)


# ─────────────────────────────────────────────────────────────────────────────
# تجهيزات
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    """قاعدة SQLite مؤقتة لكل اختبار — عزل كامل (نمط test_fe100)."""
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


@pytest.fixture(autouse=True)
def _no_network_status(monkeypatch):
    """[عزل شبكة] بطاقة باينانس تُعمى لقاموس ثابت — /api/all كانت تلمس الشبكة
    الحقيقية عبر binance_status_snapshot (fetch_time) فتعلق الاختبارات."""
    def _stub(force=False):
        return {"connected": True, "keys_present": False, "testnet": False,
                "latency_ms": 42, "usdt_free": None, "usdt_total": None,
                "can_trade": None, "error": None, "checked_at": vnz.utc_now_iso()}
    monkeypatch.setattr(vnz, "binance_status_snapshot", _stub)


@pytest.fixture()
def client(clean_db):
    return vnz.app.test_client()


@pytest.fixture()
def scan_reset(monkeypatch):
    """حالة ماسح نظيفة + قائمة مراقبة محفوظة لكل اختبار — بلا خيوط خلفية."""
    monkeypatch.setattr(vnz, "SCAN_UNIVERSE_ENABLED", True)
    monkeypatch.setattr(vnz, "SCAN_CANDIDATES", 4)
    monkeypatch.setattr(vnz, "SCAN_TOP_N", 3)
    with vnz._scanner_lock:
        vnz._scanner_state.update({
            "enabled": True, "running": False, "last_scan_at": None,
            "next_scan_at": None, "duration_ms": None, "universe": None,
            "passed": None, "candidates": None, "applied": False, "error": None,
        })
        vnz._scanner_results[:] = []
        vnz._scanner_boot_restored = False
    old_watch = list(vnz.watchlist)
    yield
    vnz.watchlist[:] = old_watch
    with vnz._scanner_lock:
        vnz._scanner_results[:] = []
        vnz._scanner_state["running"] = False


def _wave_klines(n=200, base=100.0, amp=0.02, leg=20, drift=0.0004):
    """شموع اصطناعية بموجات متعاقبة ±amp كل leg شمعة + انجراف صاعد طفيف."""
    rows = []
    price = base
    ts = 1700000000000
    for i in range(n):
        phase = (i // leg) % 2
        step = (amp if phase == 0 else -amp) / leg
        price = price * (1.0 + step + drift)
        rows.append([ts + i * 900000, round(price * 0.999, 8), round(price * 1.005, 8),
                     round(price * 0.995, 8), round(price, 8), 1000.0])
    return rows


def _ticker(sym, last=1.0, qv=50_000_000.0, spread=0.02, rng=6.0):
    mid = last
    half_spread = mid * spread / 100.0 / 2.0
    half_range = mid * rng / 100.0 / 2.0
    return {"symbol": sym, "lastPrice": str(last), "quoteVolume": str(qv),
            "bidPrice": str(mid - half_spread), "askPrice": str(mid + half_spread),
            "highPrice": str(mid + half_range), "lowPrice": str(mid - half_range),
            "count": 50000}


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 1 — زيجزاج الفحص
# ─────────────────────────────────────────────────────────────────────────────

class TestZigzagPivots:
    def test_oscillating_series_pivots(self):
        closes = [100, 103, 100, 103.5, 100.2, 103.8]
        piv = vnz.zigzag_pivots(closes, 0.02)
        assert len(piv) >= 4                      # قمة، قاع، قمة، قاع + الأخيرة
        assert piv[0][1] == 103 and piv[1][1] == 100  # قمة أولًا ثم قاع
        idxs = [p[0] for p in piv]
        assert idxs == sorted(idxs)               # زمنيًا تصاعدي

    def test_monotonic_rising_single_pivot(self):
        piv = vnz.zigzag_pivots([float(x) for x in range(1, 200)], 0.02)
        assert len(piv) == 1                      # لا انعكاس — آخر قصوى فقط

    def test_small_noise_ignored(self):
        # تذبذب 0.1% لكل شمعة (0.5% لكل نافذة 5 شموع) أقل من العتبة 1% — لا انعكاسات مؤكدة
        closes = []
        p = 100.0
        for i in range(120):
            p *= 1.001 if (i // 5) % 2 == 0 else 0.999
            closes.append(p)
        piv = vnz.zigzag_pivots(closes, 0.01)
        assert len(piv) <= 2                      # بدون مؤكدات (أو الأخيرة فقط)

    def test_short_input(self):
        assert vnz.zigzag_pivots([1.0, 2.0], 0.01) == []


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 2 — درجة الملاءمة
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreCandidate:
    def test_wave_klines_scored(self):
        sc = vnz._scanner_score_candidate("TEST/USDT", _wave_klines())
        assert sc is not None
        assert 0.0 <= sc["score"] <= 100.0
        assert 4 <= sc["pivots"] <= 40
        assert 0.0 < sc["atr_pct"] < 10.0
        assert "avg_wave_pct" in sc and "trend_eff" in sc

    def test_flat_series_low_score(self):
        rows = [[i * 900000, 100, 100.01, 99.99, 100.0, 1.0] for i in range(150)]
        sc = vnz._scanner_score_candidate("FLAT/USDT", rows)
        assert sc is not None
        assert sc["score"] < 30.0                 # سوق ميت لا يصلح للموجات

    def test_insufficient_data(self):
        assert vnz._scanner_score_candidate("X/USDT", []) is None
        assert vnz._scanner_score_candidate("X/USDT", _wave_klines()[:30]) is None

    def test_corrupt_rows(self):
        rows = [[None, "a", "b", None, "c", "d"] for _ in range(100)]
        assert vnz._scanner_score_candidate("X/USDT", rows) is None


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 3 — تطبيع السيولة وترشيح الكون
# ─────────────────────────────────────────────────────────────────────────────

class TestLiqAndFilter:
    def test_liq_norm_bounds(self):
        assert vnz._liq_norm(0) == 0.0
        assert vnz._liq_norm(5_000_000) == pytest.approx(0.0)
        assert vnz._liq_norm(1_000_000_000) == pytest.approx(1.0)
        assert vnz._liq_norm(50_000_000) == pytest.approx(0.434, abs=0.05)

    def test_filter_rejects_stable_and_leveraged(self):
        tickers = [
            _ticker("USDCUSDT"), _ticker("FDUSDUSDT"),          # مستقر
            _ticker("BTCUPUSDT"), _ticker("ETHDOWNUSDT"),       # مرفوع
            _ticker("BTCUSDT"), _ticker("SOLUSDT"),             # سليمان
            _ticker("ETHBTC"),                                  # ليس USDT
        ]
        passed, universe = vnz._scanner_filter_tickers(tickers)
        syms = {p["symbol"] for p in passed}
        assert syms == {"BTCUSDT", "SOLUSDT"}
        assert universe == 6                                     # أزواج USDT فقط تُعد في الكون

    def test_filter_rejects_thin_wide_dead(self):
        tickers = [
            _ticker("RICHUSDT", qv=4_999_999),                   # سيولة أدنى من الحد
            _ticker("WIDEUSDT", spread=0.5),                     # سبريد واسع
            _ticker("DEADUSDT", rng=0.5),                        # مدى ميت
            _ticker("ZEROUSDT", last=0.0),                       # بلا سعر
            _ticker("GOODUSDT"),
        ]
        passed, _ = vnz._scanner_filter_tickers(tickers)
        assert [p["symbol"] for p in passed] == ["GOODUSDT"]

    def test_filter_sorts_by_volume(self):
        tickers = [_ticker("AAAUSDT", qv=10_000_000),
                   _ticker("CCCUSDT", qv=900_000_000),
                   _ticker("BBBUSDT", qv=100_000_000)]
        passed, _ = vnz._scanner_filter_tickers(tickers)
        assert [p["base"] for p in passed] == ["CCC", "BBB", "AAA"]


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 4 — run_universe_scan كاملة (تدفق مزيف)
# ─────────────────────────────────────────────────────────────────────────────

class FakeScanExchange:
    def __init__(self, tickers, klines_map):
        self._tickers = tickers
        self._klines = klines_map
        self.klines_calls = []

    def publicGetTicker24hr(self):
        return list(self._tickers)

    def publicGetKlines(self, params):
        self.klines_calls.append(dict(params))
        v = self._klines.get(params.get("symbol"))
        if v is None:
            return []
        if isinstance(v, Exception):
            raise v
        return v


class TestRunUniverseScan:
    def test_full_flow_applies_watchlist_and_state(self, clean_db, scan_reset, monkeypatch):
        tickers = [
            _ticker("AAAUSDT", qv=800_000_000), _ticker("BBBUSDT", qv=300_000_000),
            _ticker("CCCUSDT", qv=90_000_000), _ticker("DDDUSDT", qv=20_000_000),
            _ticker("POORUSDT", qv=100_000),           # يُرشَّح خارجًا
        ]
        kmap = {s: _wave_klines() for s in ("AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT")}
        kmap["DDDUSDT"] = _wave_klines(leg=10)          # موجات أكثف لدرجة أعلى
        fake = FakeScanExchange(tickers, kmap)
        monkeypatch.setattr(vnz, "_binance_public_probe", lambda: fake)
        res = vnz.run_universe_scan(trigger="auto")
        assert res["ok"] is True and res["applied"] is True
        assert res["universe"] == 5 and res["count"] == 3
        # أعلى النتائج مطبقة: AAA (سيولة 800M) ثم BBB ثم DDD (موجات أكثف تتجاوز CCC الأرخص سيولة)
        bases = {w.split("/")[0] for w in vnz.watchlist}
        assert bases == {"AAA", "BBB", "DDD"}
        # النتائج مرتبة تنازليًا وفي الحالة + محفوظة في قاعدة البيانات
        snap = vnz.scanner_state_snapshot()
        finals = [r["final"] for r in snap["results"]]
        assert finals == sorted(finals, reverse=True)
        assert snap["running"] is False and snap["last_scan_at"]
        assert snap["universe"] == 5 and snap["applied"] is True
        saved = json.loads(vnz.db_get_state("scan_results", "{}"))
        assert len(saved.get("results", [])) == 3 and saved.get("at")
        # شموع كل مرشح جُلبت بنقاط خام بعتبة الفريم الصحيح
        assert len(fake.klines_calls) == 4
        assert all(c["interval"] == vnz.SIGNAL_TIMEFRAME for c in fake.klines_calls)

    def test_running_guard_blocks_concurrent(self, clean_db, scan_reset, monkeypatch):
        fake = FakeScanExchange([_ticker("AAAUSDT")], {"AAAUSDT": _wave_klines()})
        monkeypatch.setattr(vnz, "_binance_public_probe", lambda: fake)
        with vnz._scanner_lock:
            vnz._scanner_state["running"] = True
        res = vnz.run_universe_scan(trigger="auto")     # بلا force → رفض مهذب
        assert res["ok"] is False and "جارٍ" in res["error"]
        with vnz._scanner_lock:
            vnz._scanner_state["running"] = False

    def test_force_overrides_running_flag(self, clean_db, scan_reset, monkeypatch):
        fake = FakeScanExchange([_ticker("AAAUSDT")], {"AAAUSDT": _wave_klines()})
        monkeypatch.setattr(vnz, "_binance_public_probe", lambda: fake)
        with vnz._scanner_lock:
            vnz._scanner_state["running"] = True
        res = vnz.run_universe_scan(force=True, trigger="manual")
        assert res["ok"] is True

    def test_no_results_when_all_filters_reject(self, clean_db, scan_reset, monkeypatch):
        fake = FakeScanExchange([_ticker("POORUSDT", qv=10_000)], {})
        monkeypatch.setattr(vnz, "_binance_public_probe", lambda: fake)
        res = vnz.run_universe_scan(trigger="auto")
        assert res["ok"] is True and res["count"] == 0 and res["applied"] is False
        assert vnz.watchlist != []                       # القائمة الأصلية لم تُمس


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 5 — الحفاظ على الرموز النشطة + الاستعادة عند الإقلاع
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyAndRestore:
    def test_active_symbol_preserved(self, clean_db, scan_reset, monkeypatch):
        clean_db.execute(
            "INSERT INTO signals (symbol, direction, strategy_name, status, entry_price,"
            " stop_loss, take_profit, quantity, notional_usdt, rr_ratio, created_at)"
            " VALUES ('OLDACTIVE/USDT','BULLISH','Elliott_Fibonacci','pending',1,0.9,1.2,10,10,2,%s)",
            (vnz.utc_now_iso(),),
        )
        results = [{"symbol": "AAAUSDT", "base": "AAA", "final": 80.0},
                   {"symbol": "BBBUSDT", "base": "BBB", "final": 70.0}]
        assert vnz._apply_scan_watchlist(results) is True
        assert vnz.watchlist == ["AAA/USDT", "BBB/USDT", "OLDACTIVE/USDT"]

    def test_active_symbol_inside_top_kept_once(self, clean_db, scan_reset):
        clean_db.execute(
            "INSERT INTO signals (symbol, direction, strategy_name, status, entry_price,"
            " stop_loss, take_profit, quantity, notional_usdt, rr_ratio, created_at)"
            " VALUES ('AAA/USDT','BULLISH','Elliott_Fibonacci','open',1,0.9,1.2,10,10,2,%s)",
            (vnz.utc_now_iso(),),
        )
        results = [{"symbol": "AAAUSDT", "base": "AAA", "final": 80.0}]
        vnz._apply_scan_watchlist(results)
        assert vnz.watchlist.count("AAA/USDT") == 1

    def test_restore_scan_results_from_db(self, clean_db, scan_reset):
        payload = {"at": "2026-10-13T00:00:00Z",
                   "results": [{"symbol": "RESTUSDT", "base": "REST", "final": 66.0}]}
        vnz.db_set_state("scan_results", json.dumps(payload))
        vnz.restore_scan_results()
        assert vnz.watchlist == ["REST/USDT"]
        snap = vnz.scanner_state_snapshot()
        assert snap["last_scan_at"] == "2026-10-13T00:00:00Z" and snap["applied"] is True
        assert snap["results"][0]["symbol"] == "RESTUSDT"

    def test_restore_noop_when_disabled(self, clean_db, scan_reset, monkeypatch):
        monkeypatch.setattr(vnz, "SCAN_UNIVERSE_ENABLED", False)
        vnz.db_set_state("scan_results", json.dumps(
            {"at": "x", "results": [{"symbol": "XUSDT", "base": "X", "final": 50.0}]}))
        vnz.restore_scan_results()
        assert "X/USDT" not in vnz.watchlist


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 6 — إجهاض 418/429
# ─────────────────────────────────────────────────────────────────────────────

class TestRateLimitAbort:
    def test_abort_keeps_previous_results(self, clean_db, scan_reset, monkeypatch):
        # نتائج سابقة محفوظة (كأنها من فحص قبله)
        with vnz._scanner_lock:
            vnz._scanner_results[:] = [{"symbol": "OLDUSDT", "base": "OLD", "final": 60.0}]
        old_watch = ["OLD/USDT"]
        vnz.watchlist[:] = old_watch
        tickers = [_ticker("AAAUSDT"), _ticker("BBBUSDT")]
        ban = Exception('binance {"code":-1003,"msg":"Way too much request weight used; IP banned until 1"}')
        kmap = {"AAAUSDT": _wave_klines(), "BBBUSDT": ban}
        fake = FakeScanExchange(tickers, kmap)
        monkeypatch.setattr(vnz, "_binance_public_probe", lambda: fake)
        res = vnz.run_universe_scan(trigger="auto")
        assert res["ok"] is False and "أُجهض" in res["error"]
        snap = vnz.scanner_state_snapshot()
        assert snap["running"] is False
        assert [r["symbol"] for r in snap["results"]] == ["OLDUSDT"]   # القديمة محفوظة
        assert vnz.watchlist == old_watch                              # القائمة لم تُمس

    def test_429_also_aborts(self, clean_db, scan_reset, monkeypatch):
        fake = FakeScanExchange([_ticker("AAAUSDT")],
                                {"AAAUSDT": Exception("binance 429 Too Many Requests")})
        monkeypatch.setattr(vnz, "_binance_public_probe", lambda: fake)
        res = vnz.run_universe_scan(force=True, trigger="manual")
        assert res["ok"] is False and "أُجهض" in res["error"]

    def test_ban_abort_sets_retry_hint(self, clean_db, scan_reset, monkeypatch):
        # [FE1.6.0] بعد إجهاض حظر باينانس: إعادة محاولة قريبة (30 د) بدل الإيقاع الكامل
        fake = FakeScanExchange([_ticker("AAAUSDT")],
                                {"AAAUSDT": Exception('binance 418 {"code":-1003,"msg":"IP banned"}')})
        monkeypatch.setattr(vnz, "_binance_public_probe", lambda: fake)
        vnz.run_universe_scan(force=True, trigger="auto")
        snap = vnz.scanner_state_snapshot()
        assert snap["retry_after_sec"] == vnz.SCANNER_BAN_RETRY_SEC == 1800.0

    def test_ban_abort_on_ticker_sets_retry_hint(self, clean_db, scan_reset, monkeypatch):
        # [FE1.6.0] الحظر عند نداء التكتة نفسه (المسار الخارجي) — نفس التلميح
        class BannedTickerExchange:
            def publicGetTicker24hr(self):
                raise Exception('binance 418 {"code":-1003,"msg":"Way too much request weight used; IP banned until 1"}')
        monkeypatch.setattr(vnz, "_binance_public_probe", lambda: BannedTickerExchange())
        res = vnz.run_universe_scan(trigger="auto")
        assert res["ok"] is False
        snap = vnz.scanner_state_snapshot()
        assert snap["retry_after_sec"] == 1800.0 and snap["running"] is False

    def test_success_clears_retry_hint(self, clean_db, scan_reset, monkeypatch):
        with vnz._scanner_lock:
            vnz._scanner_state["retry_after_sec"] = 1800.0
        fake = FakeScanExchange([_ticker("AAAUSDT")], {"AAAUSDT": _wave_klines()})
        monkeypatch.setattr(vnz, "_binance_public_probe", lambda: fake)
        res = vnz.run_universe_scan(trigger="auto")
        assert res["ok"] is True
        assert vnz.scanner_state_snapshot()["retry_after_sec"] is None

    def test_ban_hint_detector(self):
        assert vnz._scanner_ban_hint("binance 418 banned until x") is True
        assert vnz._scanner_ban_hint("429 Too Many Requests") is True
        assert vnz._scanner_ban_hint("code -1003 weight") is True
        assert vnz._scanner_ban_hint("Connection timeout") is False

    def test_generic_kline_error_skipped_not_abort(self, clean_db, scan_reset, monkeypatch):
        fake = FakeScanExchange([_ticker("AAAUSDT"), _ticker("BBBUSDT", qv=60_000_000)],
                                {"AAAUSDT": Exception("timeout"),
                                 "BBBUSDT": _wave_klines()})
        monkeypatch.setattr(vnz, "_binance_public_probe", lambda: fake)
        res = vnz.run_universe_scan(trigger="auto")
        assert res["ok"] is True and res["count"] == 1   # الفاشل يُتخطى فقط


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 7 — WS: الحالة واللقطة والأسواق المصنوعة
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def ws_clean():
    with vnz._ws_lock:
        vnz._ws_price.clear()
        vnz._ws_candles.clear()
        vnz._ws_subs.clear()
        vnz._ws_tasks.clear()
    old_ex = dict(vnz._ws_exchanges)
    vnz._ws_exchanges.clear()
    yield
    with vnz._ws_lock:
        vnz._ws_price.clear()
        vnz._ws_candles.clear()
        vnz._ws_subs.clear()
        vnz._ws_tasks.clear()
    vnz._ws_exchanges.clear()
    vnz._ws_exchanges.update(old_ex)


class TestWsFixes:
    def test_fresh_flow_protects_live_state(self, ws_clean):
        vnz._ws_mark("BTC/USDT", "binance", "connecting")      # دورة الإنتاج: الاشتراك أولًا
        vnz.ws_apply_price("BTC/USDT", 50000.0, "binance")     # تدفق حي الآن
        vnz._ws_mark("BTC/USDT", "binance", "connecting")      # إعادة اتصال تيار الشموع
        snap = vnz.ws_feed_snapshot()
        assert snap["subscriptions"]["BTC/USDT"]["state"] == "live"
        assert snap["live_streams"] == 1

    def test_stale_flow_allows_downgrade(self, ws_clean):
        vnz._ws_mark("BTC/USDT", "binance", "connecting")
        vnz.ws_apply_price("BTC/USDT", 50000.0, "binance")
        with vnz._ws_lock:
            vnz._ws_subs["BTC/USDT"]["last_msg_ts"] = time.time() - vnz.WS_STALE_SEC - 5
        vnz._ws_mark("BTC/USDT", "binance", "connecting")
        snap = vnz.ws_feed_snapshot()
        assert snap["subscriptions"]["BTC/USDT"]["state"] == "connecting"
        assert snap["live_streams"] == 0

    def test_error_records_last_error_but_keeps_live(self, ws_clean):
        vnz._ws_mark("ETH/USDT", "bybit", "connecting")
        vnz.ws_apply_price("ETH/USDT", 3000.0, "bybit")
        vnz._ws_mark("ETH/USDT", "bybit", "error", "boom")
        snap = vnz.ws_feed_snapshot()
        sub = snap["subscriptions"]["ETH/USDT"]
        assert sub["state"] == "live" and sub["last_error"] == "boom"

    def test_snapshot_filters_stale_candles(self, ws_clean):
        now = time.time()
        with vnz._ws_lock:
            vnz._ws_candles["FRESH/USDT"] = {"candles": [[1, 1, 1, 1, 1, 1]], "ts": now, "source": "binance"}
            vnz._ws_candles["OLD/USDT"] = {"candles": [[1, 1, 1, 1, 1, 1]], "ts": now - 6377.0, "source": "binance"}
            vnz._ws_price["OLDP/USDT"] = {"price": 1.0, "ts": now - 5000.0, "source": "binance"}
        snap = vnz.ws_feed_snapshot()
        assert "FRESH/USDT" in snap["candles"] and "OLD/USDT" not in snap["candles"]
        assert "OLDP/USDT" not in snap["prices"]

    def test_refresh_fabricated_markets_injects_new_symbols(self, ws_clean, scan_reset):
        class FakeWsEx:
            def __init__(self):
                self.markets = {}
                self.markets_by_id = {}
        vnz.watchlist[:] = ["NEWCOIN/USDT", "BTC/USDT"]
        ex = FakeWsEx()
        vnz._ws_exchanges["binance"] = ex
        vnz.ws_refresh_fabricated_markets()
        assert "NEWCOIN/USDT" in ex.markets
        assert "NEWCOINUSDT" in ex.markets_by_id          # معرف باينانس ملتصق موجود أيضًا
        assert "BTC/USDT" in ex.markets
        # نسخة بلا أسواق تُتجاهل بأمان
        class NoMarkets:
            markets = None
        vnz._ws_exchanges["okx"] = NoMarkets()
        vnz.ws_refresh_fabricated_markets()               # لا استثناء


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 8 — نقاط API
# ─────────────────────────────────────────────────────────────────────────────

class TestScanApi:
    def test_scan_run_spawns_thread(self, client, scan_reset, monkeypatch):
        done = threading.Event()
        calls = {}
        def fake_scan(force=False, trigger="auto"):
            calls["force"] = force
            calls["trigger"] = trigger
            done.set()
            return {"ok": True}
        monkeypatch.setattr(vnz, "run_universe_scan", fake_scan)
        r = client.post("/api/scan/run")
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True and body["running"] is True
        assert done.wait(5.0)
        assert calls["force"] is True and calls["trigger"] == "manual"

    def test_scan_run_busy_409_style(self, client, scan_reset):
        with vnz._scanner_lock:
            vnz._scanner_state["running"] = True
        r = client.post("/api/scan/run")
        body = r.get_json()
        assert body["ok"] is False and body["running"] is True
        with vnz._scanner_lock:
            vnz._scanner_state["running"] = False

    def test_scan_run_protected(self, client, clean_db, monkeypatch):
        monkeypatch.setattr(vnz, "DASHBOARD_PROTECTED", True)
        monkeypatch.setattr(vnz, "run_universe_scan", lambda force=False, trigger="auto": {"ok": True})
        r = client.post("/api/scan/run")
        assert r.status_code == 401
        cred = base64.b64encode(b"admin:test123").decode()
        r2 = client.post("/api/scan/run", headers={"Authorization": "Basic " + cred})
        assert r2.status_code == 200

    def test_health_has_public_scanner_summary(self, client):
        r = client.get("/health")
        body = r.get_json()
        assert r.status_code == 200
        assert body["scanner"]["enabled"] is True
        assert "results" not in body["scanner"]           # التفاصيل لا تتسرب من نقطة عامة

    def test_api_all_has_full_scanner(self, client, scan_reset):
        with vnz._scanner_lock:
            vnz._scanner_results[:] = [{"symbol": "AAAUSDT", "base": "AAA", "final": 77.5}]
        r = client.get("/api/all")
        body = r.get_json()
        assert "scanner" in body
        assert body["scanner"]["results"][0]["symbol"] == "AAAUSDT"
        assert body["scanner"]["results"][0]["final"] == 77.5


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 9 — الحماية واللوحة
# ─────────────────────────────────────────────────────────────────────────────

class TestProtectionAndPanel:
    def test_head_root_public_200(self, client, clean_db, monkeypatch):
        monkeypatch.setattr(vnz, "DASHBOARD_PROTECTED", True)
        r = client.head("/")
        assert r.status_code == 200                       # فاحصات الصحة — كان 401

    def test_get_root_still_protected(self, client, clean_db, monkeypatch):
        monkeypatch.setattr(vnz, "DASHBOARD_PROTECTED", True)
        assert client.get("/").status_code == 401
        cred = base64.b64encode(b"admin:test123").decode()
        r = client.get("/", headers={"Authorization": "Basic " + cred})
        assert r.status_code == 200

    def test_signals_endpoint_protected_now(self, client, clean_db, monkeypatch):
        monkeypatch.setattr(vnz, "DASHBOARD_PROTECTED", True)
        assert client.get("/api/signals").status_code == 401
        assert client.get("/api/pnl_history").status_code == 401
        cred = base64.b64encode(b"admin:test123").decode()
        h = {"Authorization": "Basic " + cred}
        assert client.get("/api/signals", headers=h).status_code == 200
        assert client.get("/api/pnl_history", headers=h).status_code == 200

    def test_panel_contains_scanner_section(self):
        html = vnz.get_dashboard_html()
        assert "فحص أزواج باينانس" in html
        assert "scanNow()" in html and "scan-box" in html and "scan-status" in html
        assert "/api/scan/run" in html

    def test_panel_hardening_marks(self):
        from panel import PANEL_HTML, BOT_VERSION
        assert BOT_VERSION == "EL2.0.0"
        assert "const esc = " in PANEL_HTML               # تهريب HTML
        assert "esc(n.message)" in PANEL_HTML             # الإشعارات مُهرّبة (كانت XSS)
        assert "esc(s.symbol)" in PANEL_HTML or "esc(x.symbol)" in PANEL_HTML
        assert "REAL_BUSY" in PANEL_HTML                  # لا اختطاف المفتاح أثناء الطلب
        assert "REFRESHING" in PANEL_HTML and "visibilitychange" in PANEL_HTML
        # جداول المغلقة/التقاطات/الفحص داخل .tbl-wrap (كانت تفيض على الموبايل)
        assert PANEL_HTML.count('<div class="tbl-wrap">') >= 4
        assert "err-banner" in PANEL_HTML                 # لافتة خطأ مستقلة
        assert "${'دخول/ملء'}" not in PANEL_HTML          # قالب زائد حُذف
