#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fe131.py — اختبارات حمية الذاكرة ضد أعطال OOM (سقف 512MB) FE1.3.1

خمس جولات:
  1) rss_mb: قراءة /proc وقيم معقولة
  2) mem_check: بلا تنظيف تحت العتبة / تنظيف فوقها / سجل حرج فوق الحد
  3) prune_markets: تقليم فعلي بالرمز/المعرف + تجاوز الصغير + مقاومة الأشكال الفاسدة
  4) التحميل الكسول: load_markets_async لا يحمل شيئًا في الوضع الجديد
  5) /health و/api/all يحملان قسم memory

تشغيل: pytest test_fe131.py -v   (من داخل مجلد المشروع)
"""

import gc
import types
from collections import OrderedDict

import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة


# ─────────────────────────────────────────────────────────────────────────────
# تجهيزات
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
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
def client(clean_db):
    return vnz.app.test_client()


class FakeExchange:
    """مزود وهمي بأسواق شبيهة ببنية ccxt: unified key + markets_by_id."""
    def __init__(self, n=1000, symbols=None):
        syms = symbols or ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
        self.markets = {}
        self.markets_by_id = {}
        for i in range(n):
            s = syms[i % len(syms)] if i < len(syms) else f"COIN{i}/USDT"
            m = {"id": s.replace("/", ""), "symbol": s, "active": True,
                 "precision": {"amount": 5, "price": 2}, "limits": {}}
            self.markets[s if i < len(syms) else f"COIN{i}/USDT"] = m
            self.markets_by_id[m["id"]] = m


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 1 — قياس RSS
# ─────────────────────────────────────────────────────────────────────────────

class TestRssMb:
    def test_returns_positive_on_linux(self):
        v = vnz.rss_mb()
        assert v > 0.0, "على لينكس يجب أن تُقرأ VmRSS من /proc"

    def test_zero_on_missing_proc(self, monkeypatch):
        monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(OSError()))
        assert vnz.rss_mb() == 0.0

    def test_below_typical_limit_in_tests(self):
        assert vnz.rss_mb() < 512.0, "الاختبارات نفسها لا يجب أن تتجاوز سقف الخطة المجانية"


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 2 — mem_check: تنظيف ذكي عند العتبات
# ─────────────────────────────────────────────────────────────────────────────

class TestMemCheck:
    def test_below_threshold_no_gc(self, monkeypatch):
        calls = []
        monkeypatch.setattr(vnz, "rss_mb", lambda: 100.0)
        monkeypatch.setattr(gc, "collect", lambda: calls.append(1))
        assert vnz.mem_check("اختبار") == 100.0
        assert calls == [], "تحت العتبة لا يجوز أي تجميع قسري"

    def test_above_threshold_triggers_gc(self, monkeypatch):
        calls = []
        seq = [400.0, 200.0]  # قبل التنظيف ← بعده
        monkeypatch.setattr(vnz, "rss_mb", lambda: seq.pop(0))
        monkeypatch.setattr(gc, "collect", lambda: calls.append(1))
        got = vnz.mem_check("دورة اختبار")
        assert calls == [1]
        assert got == 200.0

    def test_critical_logs_above_limit(self, monkeypatch, caplog):
        seq = [460.0, 455.0]
        monkeypatch.setattr(vnz, "rss_mb", lambda: seq.pop(0))
        monkeypatch.setattr(gc, "collect", lambda: None)
        with caplog.at_level("CRITICAL", logger="fibo-elio"):
            got = vnz.mem_check("حرج")
        assert got == 455.0
        assert any("حرجة" in r.message for r in caplog.records)


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 3 — تقليم الأسواق
# ─────────────────────────────────────────────────────────────────────────────

class TestPruneMarkets:
    def test_prunes_to_watchlist(self):
        ex = FakeExchange(n=1000)
        kept = vnz.prune_markets(ex, ["BTC/USDT", "ETH/USDT"])
        assert 0 < kept <= 4
        assert "BTC/USDT" in ex.markets and "ETH/USDT" in ex.markets
        assert len(ex.markets_by_id) <= 4
        assert "COIN500/USDT" not in ex.markets

    def test_small_markets_untouched(self):
        ex = FakeExchange(n=100)
        before = dict(ex.markets)
        kept = vnz.prune_markets(ex, ["BTC/USDT"])  # 100 ≤ MEM_PRUNE_MARKETS=400
        assert kept == 100 and ex.markets == before

    def test_keeps_market_by_id_alias(self):
        """المفتاح غير الموحد يبقى إن كان symbol أو id ضمن القائمة."""
        ex = types.SimpleNamespace(
            markets={"BTCUSDT": {"id": "BTCUSDT", "symbol": "BTC/USDT"}},
            markets_by_id={"BTCUSDT": {"id": "BTCUSDT", "symbol": "BTC/USDT"}},
        )
        # 1 سوق فقط ≤ العتبة — لا تقليم، لكن يجب ألا ينكسر
        assert vnz.prune_markets(ex, ["BTC/USDT"]) == 1

    def test_resilient_to_garbage(self):
        assert vnz.prune_markets(None) == -1
        assert vnz.prune_markets(types.SimpleNamespace(markets=None)) == -1
        ex = types.SimpleNamespace(markets={f"K{i}": "ليس قاموسًا" for i in range(500)})
        assert vnz.prune_markets(ex, ["BTC/USDT"]) >= 0  # لا استثناء مهما كان الفوضى

    def test_full_watchlist_survives(self):
        """كل أزواج القائمة الموجودة فعلًا في أسواق المزود يجب أن تبقى بعد التقليم."""
        ex = FakeExchange(n=2000)
        present = [s for s in vnz.watchlist if s in ex.markets]  # الوهم يحوي 3 أزواج فقط
        assert present, "التجهيز يجب أن يحوي أزواجًا من قائمة المراقبة الحقيقية"
        kept = vnz.prune_markets(ex, vnz.watchlist)
        for s in present:
            assert s in ex.markets, f"زوج القائمة {s} فُقد بالتقليم!"
        assert kept >= len(present)
        assert kept < 2000, "التقليم يجب أن يقلّص آلاف الأسواق الوهمية"


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 4 — التحميل الكسول
# ─────────────────────────────────────────────────────────────────────────────

class TestLazyMarkets:
    def test_lazy_mode_returns_without_loading(self, monkeypatch):
        loaded = []
        fake_ex = types.SimpleNamespace(load_markets=lambda: loaded.append(1))
        monkeypatch.setattr(vnz, "MEM_LAZY_MARKETS", True)
        monkeypatch.setattr(vnz, "EXCHANGES", {"binance": fake_ex})
        vnz.load_markets_async()  # يجب أن تعود فورًا بلا تحميل
        assert loaded == []

    def test_explicit_mode_still_loads(self, monkeypatch):
        loaded = []
        fake_ex = types.SimpleNamespace(load_markets=lambda: loaded.append(1))
        monkeypatch.setattr(vnz, "MEM_LAZY_MARKETS", False)
        monkeypatch.setattr(vnz, "EXCHANGES", {"binance": fake_ex})
        vnz.load_markets_async()
        deadline = 20
        while not loaded and deadline:
            import time as _t
            _t.sleep(0.1)
            deadline -= 1
        assert loaded == [1]

    def test_default_is_lazy(self):
        assert vnz.MEM_LAZY_MARKETS is True, "الحمية يجب أن تكون الافتراضي — هي سبب إصلاح OOM"


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 6 — FE1.3.2: أسواق spot فقط + تقليم عند الفشل
# ─────────────────────────────────────────────────────────────────────────────

class TestSpotOnlyMarketsFE132:
    def test_build_exchange_spot_only_option(self):
        """bybit/okx بلا هذا الخيار تحمّل عقودًا وخيارات = ذروة 100-200MB = OOM."""
        for name in ("binance", "bybit", "okx", "gate"):
            ex = vnz._build_exchange(name)
            assert ex.options.get("fetchMarkets") == ["spot"], f"المزود {name} بلا قصر الأسواق على spot"
            assert ex.options.get("defaultType") == "spot"

    def test_prune_after_failed_fetch(self, monkeypatch):
        """المزود المحجوب جغرافيًا حمّل أسواقه ضمن المحاولة — يجب تقليمها رغم الفشل."""
        big = {f"COIN{i}/USDT": {"id": f"COIN{i}USDT", "symbol": f"COIN{i}/USDT"} for i in range(900)}
        big["BTC/USDT"] = {"id": "BTCUSDT", "symbol": "BTC/USDT"}
        fake = types.SimpleNamespace(fetch_ohlcv=lambda *a, **k: (_ for _ in ()).throw(Exception("451 حظر")), markets=big)
        # عزل كامل: مزود واحد وهمي فاشل فقط — لا نداءات شبكة حقيقية في الاختبار
        monkeypatch.setattr(vnz, "EXCHANGES", OrderedDict([("binance", fake)]))
        # [FE1.8.7] عقد المسار القديم ccxt — الطبقة الخام في test_fe187
        monkeypatch.setattr(vnz, "DATA_FEED_RAW", False)
        with vnz.provider_lock:
            vnz.provider_state = {"binance": {"ok": 0, "fail": 0, "last_error": "",
                                              "last_ok_at": None, "cooldown_until": 0.0}}
            vnz.active_source["name"] = None
        raw, src = vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 2)
        assert raw is None and src is None
        st = vnz.provider_state["binance"]
        assert st["fail"] == 1
        assert st.get("markets_pruned") is True, "الفشل يجب أن يقلّم الأسواق المحمّلة"
        assert len(fake.markets) <= 400 + 1 and "BTC/USDT" in fake.markets


class TestMemoryDiagnostics:
    def test_health_reports_memory(self, client):
        body = client.get("/health").get_json()
        mem = body["memory"]
        assert mem["rss_mb"] > 0
        assert mem["gc_threshold_mb"] == vnz.MEM_GC_THRESHOLD_MB
        assert mem["critical_mb"] == vnz.MEM_CRITICAL_MB

    def test_api_all_reports_memory(self, client):
        body = client.get("/api/all").get_json()
        assert body["memory"]["rss_mb"] > 0

    def test_thresholds_below_free_limit(self):
        """العتبات يجب أن تبقى هامشًا آمنًا تحت سقف Render المجاني 512MB."""
        assert vnz.MEM_GC_THRESHOLD_MB < 450
        assert vnz.MEM_CRITICAL_MB < 512
        assert vnz.MEM_GC_THRESHOLD_MB < vnz.MEM_CRITICAL_MB
