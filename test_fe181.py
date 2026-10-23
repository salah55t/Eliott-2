#!/usr/bin/env python3
# test_fe181.py — اختبارات FE1.8.1:
#   1) تصفير شامل: عدادات قاطع المخاطر (risk_*) وحكم الرفض تُمسح مع البقية
#   2) لوحة أداء (اقتباس V9.34.0/OctoBot): performance_snapshot + /api/performance + /api/all
#   3) حكم الالتقاط (لماذا لا توصية؟): _reject_reason في بوابات scan_cycle وcreate_pending_signal
#      + verdict في register_detection
# العقد: 312+2 سابقة لا تنكسر (تأكيدات الإصدار حُدثت FE1.8.1) — وحدود FE1.8.0 المحمية ثابتة.
import json

import pandas as pd
import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة (نفس عقد test_fe100/170)


# ─────────────────────────────────────────────────────────────────────────────
# تجهيزات (نفس عقد test_fe170)
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


def insert_closed(symbol="TEST/USDT", pnl=10.0, created_at=None, closed_at=None):
    """صفقة مغلقة بمحاسبة معروفة — للوحة الأداء."""
    vnz.db.execute(
        "INSERT INTO signals (symbol, direction, strategy_name, status, entry_price, stop_loss,"
        " take_profit, quantity, notional_usdt, pnl_usdt, created_at, closed_at, is_real)"
        " VALUES (%s,%s,'Elliott_Fibonacci','closed',106.0,99.9,115.0,10.0,%s,%s,%s,%s,0)",
        (symbol, "BULLISH", abs(pnl) * 10.0, pnl,
         created_at or vnz.utc_now_iso(), closed_at or vnz.utc_now_iso()),
    )


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
    with vnz._reject_reason_lock:
        vnz._reject_reason.clear()
    with vnz.scan_stats_lock:
        for k in vnz.scan_stats:
            vnz.scan_stats[k] = 0
    yield vnz.db
    vnz.db.conn = old


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 1 — لوحة الأداء (اقتباس V9.34.0/OctoBot)
# ─────────────────────────────────────────────────────────────────────────────

class TestPerformanceSnapshot:

    def test_empty_db_shape(self, clean_db):
        p = vnz.performance_snapshot()
        assert p["net_profit_usdt"] == 0
        assert p["total_closed_trades"] == 0
        assert p["win_rate"] is None and p["profit_factor"] is None
        assert p["trades"] == [] and p["best_trade"] is None and p["worst_trade"] is None

    def test_core_math_quoted_from_v9(self, clean_db):
        # +100 ثم -150: صافي -50، معدل ربح 50%، عامل 100/150≈0.667
        insert_closed(symbol="A/USDT", pnl=100.0,
                      created_at="2026-01-01T10:00:00Z", closed_at="2026-01-01T11:30:00Z")
        insert_closed(symbol="B/USDT", pnl=-150.0,
                      created_at="2026-01-01T12:00:00Z", closed_at="2026-01-01T12:10:00Z")
        p = vnz.performance_snapshot()
        assert p["total_closed_trades"] == 2
        assert p["net_profit_usdt"] == -50.0
        assert p["wins_n"] == 1 and p["losses_n"] == 1
        assert p["win_rate"] == 50.0
        assert p["profit_factor"] == pytest.approx(100.0 / 150.0, abs=1e-3)
        assert p["avg_win"] == 100.0 and p["avg_loss"] == -150.0
        assert p["expectancy"] == -25.0
        assert p["best_trade"] == {"symbol": "A/USDT", "pnl": 100.0}
        assert p["worst_trade"] == {"symbol": "B/USDT", "pnl": -150.0}

    def test_max_drawdown_from_peak(self, clean_db):
        # القمة +100 ثم تراجع إلى -50 → أقصى تراجع 150
        insert_closed(symbol="A/USDT", pnl=100.0)
        insert_closed(symbol="B/USDT", pnl=-150.0)
        p = vnz.performance_snapshot()
        assert p["max_drawdown_usdt"] == 150.0

    def test_equity_curve_order_and_cum(self, clean_db):
        insert_closed(symbol="A/USDT", pnl=10.0, closed_at="2026-01-02T00:00:00Z")
        insert_closed(symbol="B/USDT", pnl=-4.0, closed_at="2026-01-03T00:00:00Z")
        insert_closed(symbol="C/USDT", pnl=6.0, closed_at="2026-01-04T00:00:00Z")
        p = vnz.performance_snapshot()
        t = p["trades"]
        assert [x["i"] for x in t] == [1, 2, 3]
        assert [x["cum_usdt"] for x in t] == [10.0, 6.0, 12.0]
        assert t[-1]["symbol"] == "C/USDT"
        assert p["net_profit_usdt"] == 12.0

    def test_today_pnl_and_duration(self, clean_db):
        today = vnz.utc_now_iso()[:10]
        insert_closed(symbol="A/USDT", pnl=7.0,
                      created_at=f"{today}T09:00:00Z", closed_at=f"{today}T10:30:00Z")
        insert_closed(symbol="OLD/USDT", pnl=-100.0,
                      created_at="2026-01-01T09:00:00Z", closed_at="2026-01-01T09:20:00Z")
        p = vnz.performance_snapshot()
        assert p["today_pnl"] == 7.0  # القديمة خارج اليوم
        assert p["avg_duration_min"] == pytest.approx((90.0 + 20.0) / 2, abs=0.1)

    def test_all_wins_profit_factor_capped(self, clean_db):
        insert_closed(symbol="A/USDT", pnl=5.0)
        p = vnz.performance_snapshot()
        assert p["profit_factor"] == 99.0  # صفر خسائر + أرباح → سقف ∞ (عقد V9 نفسه في اللوحة)

    def test_endpoint_and_api_all(self, clean_db):
        insert_closed(symbol="A/USDT", pnl=3.0)
        client = vnz.app.test_client()
        r = client.get("/api/performance")
        assert r.status_code == 200
        body = r.get_json()
        assert body["total_closed_trades"] == 1
        assert "trades" in body and "max_drawdown_usdt" in body
        r2 = client.get("/api/all")
        assert r2.status_code == 200
        assert "performance" in r2.get_json()
        assert r2.get_json()["performance"]["net_profit_usdt"] == 3.0


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 2 — التصفير الشامل (إصلاح «لم يصفر النتائج كلها»)
# ─────────────────────────────────────────────────────────────────────────────

class TestResetClearsEverything:

    def test_reset_clears_risk_breaker_state(self, clean_db):
        # بذرة عدادات قاطع المخاطر كما تركتها FE1.8.0 بعد إغلاقات خاسرة
        vnz.db_set_state("risk_day", vnz._utc_day())
        vnz.db_set_state("risk_realized", "-70.78")
        vnz.db_set_state("risk_day_base", "9841.8")
        vnz.db_set_state("risk_streak", "2")
        vnz.db_set_state("risk_pause_until", "2099-01-01T00:00:00Z")
        insert_closed(symbol="A/USDT", pnl=-7.0)
        client = vnz.app.test_client()
        r = client.post("/api/stats/reset", json={"confirm": "RESET"})
        assert r.status_code == 200
        keys = [x["key"] for x in clean_db.query("SELECT key FROM bot_state")]
        for k in ("risk_day", "risk_realized", "risk_day_base", "risk_streak", "risk_pause_until"):
            assert k not in keys
        snap = vnz.risk_snapshot()
        assert snap["daily_realized"] == 0.0 and snap["loss_streak"] == 0
        assert snap["pause_until"] == "" and snap["daily_hit"] is False

    def test_reset_clears_reject_reasons_and_counters(self, clean_db):
        vnz._set_reject_reason("TEST/USDT", "بنية متقادمة")
        vnz.scan_stats["rejected_old_structure"] = 21
        client = vnz.app.test_client()
        r = client.post("/api/stats/reset", json={"confirm": "RESET"})
        assert r.status_code == 200
        assert vnz._get_reject_reason("TEST/USDT") == ""
        assert vnz.scan_stats["rejected_old_structure"] == 0

    def test_reset_archive_survives(self, clean_db):
        # الحدود المحمية: الأرشفة قبل الحذف باقية — التصفير الشامل لا يمسها
        insert_closed(symbol="A/USDT", pnl=1.0)
        client = vnz.app.test_client()
        r = client.post("/api/stats/reset", json={"confirm": "RESET"})
        assert r.status_code == 200
        keys = [x["key"] for x in
                clean_db.query("SELECT key FROM bot_state WHERE key LIKE 'stats_archive_%'")]
        assert len(keys) == 1

    def test_guards_intact_after_fix(self, clean_db):
        # حراسات FE1.7.0 الثلاثة باقية فوق الإصلاح
        client = vnz.app.test_client()
        assert client.post("/api/stats/reset", json={}).status_code == 400
        insert_closed(symbol="A/USDT", pnl=1.0)
        vnz.db.execute(
            "INSERT INTO signals (symbol, direction, strategy_name, status, entry_price,"
            " stop_loss, take_profit, quantity, notional_usdt, created_at, is_real, order_id)"
            " VALUES (%s,'BULLISH','Elliott_Fibonacci','pending',1,0.9,1.2,1,10,%s,1,'9')",
            ("R/USDT", vnz.utc_now_iso()),
        )
        r = client.post("/api/stats/reset", json={"confirm": "RESET"})
        assert r.status_code == 409
        assert int(clean_db.query("SELECT COUNT(*) AS n FROM signals")[0]["n"]) == 2


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 3 — حكم الرفض (لماذا لا توصية معلقة؟)
# ─────────────────────────────────────────────────────────────────────────────

class TestRejectReasonInfra:

    def test_helpers_set_get_clear(self):
        vnz._set_reject_reason("X/USDT", "سبب")
        assert vnz._get_reject_reason("X/USDT") == "سبب"
        vnz._clear_reject_reason("X/USDT")
        assert vnz._get_reject_reason("X/USDT") == ""
        assert vnz._get_reject_reason("Y/USDT") == ""

    def test_rr_net_gate_sets_reason(self, clean_db, monkeypatch):
        monkeypatch.setattr(vnz, "RR_NET_MIN", 5.0)  # أي إعداد افتراضي يُرفض تحت هذه الأرضية
        ok = vnz.create_pending_signal("TEST/USDT", make_setup(), last_close=110.0)
        assert ok is False
        assert "R:R" in vnz._get_reject_reason("TEST/USDT")
        assert clean_db.query("SELECT COUNT(*) AS n FROM signals")[0]["n"] == 0

    def test_chase_gate_sets_reason(self, clean_db):
        # إغلاق 115 فوق الدخول 109.27 = +5.2% > سقف 1.5%
        ok = vnz.create_pending_signal("TEST/USDT", make_setup(), last_close=115.0)
        assert ok is False
        assert "مطاردة" in vnz._get_reject_reason("TEST/USDT")

    def test_target_gate_sets_reason(self, clean_db, monkeypatch):
        # تعطيل سقف المطاردة كي تصل الإشارة إلى بوابة الهدف (الترتيب: مطاردة ← هدف)
        monkeypatch.setattr(vnz, "MAX_ENTRY_DISTANCE_PCT", 100.0)
        # الهدف 116.18 ≤ الإغلاق 120 → هدف مُحقق
        ok = vnz.create_pending_signal("TEST/USDT", make_setup(), last_close=120.0)
        assert ok is False
        assert "الهدف" in vnz._get_reject_reason("TEST/USDT")

    def test_risk_pause_sets_reason(self, clean_db):
        vnz.db_set_state("risk_pause_until", "2099-01-01T00:00:00Z")
        ok = vnz.create_pending_signal("TEST/USDT", make_setup(), last_close=110.0)
        assert ok is False
        assert "تبريد" in vnz._get_reject_reason("TEST/USDT")

    def test_success_clears_reason(self, clean_db):
        vnz._set_reject_reason("TEST/USDT", "بوابة قديمة")
        ok = vnz.create_pending_signal("TEST/USDT", make_setup(), last_close=110.0)
        assert ok is True
        assert vnz._get_reject_reason("TEST/USDT") == ""
        row = clean_db.query("SELECT * FROM signals")[0]
        assert row["status"] == "pending"

    def test_register_detection_verdict_traded(self, clean_db):
        vnz.register_detection("TEST/USDT", make_setup(), traded=True)
        assert vnz.recent_detections[0]["verdict"] == "أُنشئ أمر معلق بانتظار منطقة الدخول"

    def test_register_detection_verdict_bearish(self, clean_db):
        vnz.register_detection("TEST/USDT", make_setup(direction="BEARISH"), traded=False)
        assert "متابعة فقط" in vnz.recent_detections[0]["verdict"]

    def test_register_detection_verdict_from_map(self, clean_db):
        vnz._set_reject_reason("TEST/USDT", "الخانات ممتلئة (5/5)")
        vnz.register_detection("TEST/USDT", make_setup(), traded=False)
        assert vnz.recent_detections[0]["verdict"] == "الخانات ممتلئة (5/5)"

    def test_register_detection_verdict_default(self, clean_db):
        vnz.register_detection("TEST/USDT", make_setup(), traded=False)
        assert vnz.recent_detections[0]["verdict"] == "مرفوض"

    def test_verdict_reaches_api_all(self, clean_db):
        vnz._set_reject_reason("TEST/USDT", "مطاردة — السعر أعلى من الدخول")
        vnz.register_detection("TEST/USDT", make_setup(), traded=False)
        client = vnz.app.test_client()
        d = client.get("/api/all").get_json()
        assert d["detections"][0]["verdict"] == "مطاردة — السعر أعلى من الدخول"


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 4 — حدود محمية لا تُمس
# ─────────────────────────────────────────────────────────────────────────────

class TestProtectedBoundaries:

    def test_version_bumped_everywhere(self):
        assert vnz.BOT_VERSION == "EL2.2.0"
        import panel
        assert panel.BOT_VERSION == "EL2.2.0"

    def test_paper_balance_still_resets(self, clean_db):
        vnz.set_paper_balance(5000.0)
        client = vnz.app.test_client()
        client.post("/api/stats/reset", json={"confirm": "RESET"})
        assert vnz.get_paper_balance() == vnz.PAPER_BALANCE_START

    def test_risk_on_close_still_counts_after_reset(self, clean_db):
        # بعد التصفير: أول إغلاق خاسر يعيد بناء العدادات من الصفر (عقد FE1.8.0)
        client = vnz.app.test_client()
        client.post("/api/stats/reset", json={"confirm": "RESET"})
        vnz._risk_on_close(-10.0)
        snap = vnz.risk_snapshot()
        assert snap["loss_streak"] == 1
        assert snap["daily_realized"] == -10.0

    def test_panel_html_has_new_sections(self):
        import panel
        html = panel.PANEL_HTML
        assert 'id="perf-cards"' in html and 'id="pnl-chart"' in html
        assert 'id="gates-strip"' in html
        assert "لوحة الأداء" in html and "الحكم" in html
        assert "verdictCell" in html and "renderPnlChart" in html and "renderGates" in html
        assert "renderPerformance" in html
