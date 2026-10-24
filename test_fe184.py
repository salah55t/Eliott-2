#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fe184.py — اختبارات FE1.8.6: فتح الترشيح بإثبات حي + إعادة فحص معجّلة عند موت القائمة

الخلفية الحية (FE1.8.3 بعد التصفير، 6 دورات كشف على 20 زوجًا):
  • scanned=120، setups_valid=203، setups_bear_seen=108 — وصفر توصية معلقة.
  • توزيع الرفض الحي: 54 «الفرضية ماتت» + 23 «بنية متقادمة (سقف 20)» مقابل
    صفر رفض في far_entry/htf/rr_net/cooldown/busy/cluster/limit — أي أن كل
    ما يمنع الترشيح هو بوابتا الطزاجة فقط وقائمة مراقبة ضيقة (20 زوجًا).
  • الفحص الكامل كل 6 ساعات: قائمة ميتة تبقى معتمة حتى 6 ساعات إن لم تُوقَّظ.

القرار الجراحي (الحراسات الجوهرية لم تُمس — premise-alive/Mطاردة 1.5%/rr_net≥0.3/HTF):
  1) SCAN_TOP_N 20→30 زوجًا — قائمة أوسع ترفع فرص بنيات صاعدة حية.
  2) MAX_STRUCTURE_AGE_BARS 20→30 شمعة (7.5س) — إعادة إدخال مرفوضات التقادم
     بشرط بقاء الفرضية حية والدخول قريب (بوابة المطاردة).
  3) _idle_rescan_maybe: دورة كشف بلا أي بنية صاعدة حية وبلا معلق/مفتوح
     توقظ الماسح (_scan_kick) لفحص كون معجّل بعد فجوة IDLE_RESCAN_MIN_GAP_SEC
     (45 دقيقة) — لا إعجال أثناء فحص جارٍ أو عقوبة حظر أو تعطيل.

الجولات:
  1) الافتراضيات الجديدة + الإصدار في vnz/panel
  2) _idle_rescan_maybe وحدويًا: كل شروط الرفض والقبول
  3) scan_cycle تكامليًا: قائمة ميتة توقظ الفحص / بنية حية أو صفقة نشطة لا توقّظ
  4) render.yaml يحمل القيم + الحراسات الجوهرية ثابتة

تشغيل: pytest test_fe184.py -v   (من داخل مجلد المشروع)
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة (نفس عقد test_fe100)


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
    """نافذة صاعدة قابلة للضبط — الافتراضي حي: P0=90، إغلاق 110 فوقه."""
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


def iso_ago(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


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
def scanner_clean():
    """حالة الماسح وحدث الإعجال نظيفان حول كل اختبار — بلا تسرب بين الاختبارات."""
    vnz._scan_kick.clear()
    saved = dict(vnz._scanner_state)
    vnz._scanner_state.update({"running": False, "last_scan_at": None,
                               "retry_after_sec": None, "error": None})
    yield vnz._scanner_state
    vnz._scan_kick.clear()
    vnz._scanner_state.clear()
    vnz._scanner_state.update(saved)


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 1 — الافتراضيات والإصدار
# ─────────────────────────────────────────────────────────────────────────────

class TestNewDefaults:

    def test_wider_watchlist(self):
        assert vnz.SCAN_TOP_N == 30       # [FE1.8.6] بدل 20 — قائمة أوسع

    def test_structure_age_ceiling(self):
        assert vnz.MAX_STRUCTURE_AGE_BARS == 36   # [FE1.8.6] بدل 30 (9س على 15m)

    def test_idle_rescan_gap(self):
        assert vnz.IDLE_RESCAN_MIN_GAP_SEC == 2700.0  # 45 دقيقة بين الإعجالات

    def test_version_bumped_everywhere(self):
        import panel
        assert vnz.BOT_VERSION == "EL2.4.0"
        assert panel.BOT_VERSION == "EL2.4.0"


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 2 — _idle_rescan_maybe وحدويًا (عقد القرار)
# ─────────────────────────────────────────────────────────────────────────────

class TestIdleRescanDecision:

    def test_kick_when_dead_list(self, monkeypatch, scanner_clean):
        # دورة بلا بنية حية + بلا صفقات + آخر فحص قبل ساعتين → إعجال
        monkeypatch.setattr(vnz, "active_trade_count", lambda: 0)
        scanner_clean["last_scan_at"] = iso_ago(7200)
        assert vnz._idle_rescan_maybe(cycle_bull_live=0) is True
        assert vnz._scan_kick.is_set()

    def test_no_kick_when_live_structure(self, monkeypatch, scanner_clean):
        # بنية صاعدة حية واحدة تكفي — القائمة ليست ميتة
        monkeypatch.setattr(vnz, "active_trade_count", lambda: 0)
        scanner_clean["last_scan_at"] = iso_ago(7200)
        assert vnz._idle_rescan_maybe(cycle_bull_live=1) is False
        assert not vnz._scan_kick.is_set()

    def test_no_kick_when_trades_active(self, monkeypatch, scanner_clean):
        # معلق/مفتوح نشط — الانتظار ليس فارغًا ولا حاجة لإعجال
        monkeypatch.setattr(vnz, "active_trade_count", lambda: 2)
        scanner_clean["last_scan_at"] = iso_ago(7200)
        assert vnz._idle_rescan_maybe(cycle_bull_live=0) is False
        assert not vnz._scan_kick.is_set()

    def test_no_kick_within_gap(self, monkeypatch, scanner_clean):
        # آخر فحص قبل 10 دقائق فقط (< 45 دقيقة الفجوة الدنيا) — لا عواصف
        monkeypatch.setattr(vnz, "active_trade_count", lambda: 0)
        scanner_clean["last_scan_at"] = iso_ago(600)
        assert vnz._idle_rescan_maybe(cycle_bull_live=0) is False
        assert not vnz._scan_kick.is_set()

    def test_no_kick_while_running(self, monkeypatch, scanner_clean):
        # فحص جارٍ حاليًا — الإعجال زائد
        monkeypatch.setattr(vnz, "active_trade_count", lambda: 0)
        scanner_clean["last_scan_at"] = iso_ago(7200)
        scanner_clean["running"] = True
        assert vnz._idle_rescan_maybe(cycle_bull_live=0) is False

    def test_no_kick_under_ban(self, monkeypatch, scanner_clean):
        # عقوبة حظر 418/429 قائمة (retry_after_sec) — لا إعجال يهدر المحاولات
        monkeypatch.setattr(vnz, "active_trade_count", lambda: 0)
        scanner_clean["last_scan_at"] = iso_ago(7200)
        scanner_clean["retry_after_sec"] = 1800.0
        assert vnz._idle_rescan_maybe(cycle_bull_live=0) is False

    def test_no_kick_scanner_disabled(self, monkeypatch, scanner_clean):
        monkeypatch.setattr(vnz, "SCAN_UNIVERSE_ENABLED", False)
        monkeypatch.setattr(vnz, "active_trade_count", lambda: 0)
        scanner_clean["last_scan_at"] = iso_ago(7200)
        assert vnz._idle_rescan_maybe(cycle_bull_live=0) is False

    def test_no_kick_without_last_scan(self, monkeypatch, scanner_clean):
        # بلا فحص سابق (إقلاع جديد) — لا مرجع زمني للحكم
        monkeypatch.setattr(vnz, "active_trade_count", lambda: 0)
        assert vnz._idle_rescan_maybe(cycle_bull_live=0) is False

    def test_no_kick_on_corrupted_timestamp(self, monkeypatch, scanner_clean):
        # طابع زمني تالف — تساهل (لا إعجال) لا انهيار
        monkeypatch.setattr(vnz, "active_trade_count", lambda: 0)
        scanner_clean["last_scan_at"] = "not-a-timestamp"
        assert vnz._idle_rescan_maybe(cycle_bull_live=0) is False


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 3 — scan_cycle تكامليًا (القائمة الميتة توقظ الفحص)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def scan_env(clean_db, monkeypatch):
    """عزل دورة المسح مع قاعدة حقيقية — نفس عقد scan_env170."""
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


class TestScanCycleIdleRescan:

    def test_dead_list_kicks_rescan(self, scan_env, monkeypatch, scanner_clean):
        # فرضية ميتة (إغلاق 110 تحت P0=150) + بلا صفقات + فحص قديم → توقظ
        scanner_clean["last_scan_at"] = iso_ago(7200)
        _patch_scan(monkeypatch,
                    make_setup(prices=[150.0, 165.0, 154.5, 177.0, 159.0, 168.0]))
        vnz.scan_cycle()
        assert vnz.scan_stats["rejected_stale_premise"] == 1
        assert vnz._scan_kick.is_set()   # [FE1.8.6] القائمة ميتة — الفحص يُوقظ

    def test_old_structure_also_kicks(self, scan_env, monkeypatch, scanner_clean):
        # بنية أثرية (عمر 35 > 30) + بلا صفقات + فحص قديم → توقظ أيضًا
        scanner_clean["last_scan_at"] = iso_ago(7200)
        _patch_scan(monkeypatch, make_setup(p5_idx=60))  # [FE1.8.6] العمر 39 > السقف 36
        vnz.scan_cycle()
        assert vnz.scan_stats["rejected_old_structure"] == 1
        assert vnz._scan_kick.is_set()

    def test_live_structure_no_kick(self, scan_env, monkeypatch, scanner_clean):
        # المسار السعيد: إشارة معلقة أُنشئت — لا إعجال
        scanner_clean["last_scan_at"] = iso_ago(7200)
        _patch_scan(monkeypatch, make_setup())
        vnz.scan_cycle()
        assert vnz.scan_stats["setups_bull_traded"] == 1
        assert not vnz._scan_kick.is_set()

    def test_active_trade_no_kick(self, scan_env, monkeypatch, scanner_clean):
        # صفقة مفتوحة رغم موت البنية — الانتظار ليس فارغًا، لا إعجال
        insert_sig(status="open")
        scanner_clean["last_scan_at"] = iso_ago(7200)
        _patch_scan(monkeypatch,
                    make_setup(prices=[150.0, 165.0, 154.5, 177.0, 159.0, 168.0]))
        vnz.scan_cycle()
        assert vnz.scan_stats["rejected_stale_premise"] == 1
        assert not vnz._scan_kick.is_set()

    def test_recent_scan_no_kick(self, scan_env, monkeypatch, scanner_clean):
        # قائمة ميتة لكن آخر فحص قبل 10 دقائق — الفجوة الدنيا تحمي من العواصف
        scanner_clean["last_scan_at"] = iso_ago(600)
        _patch_scan(monkeypatch,
                    make_setup(prices=[150.0, 165.0, 154.5, 177.0, 159.0, 168.0]))
        vnz.scan_cycle()
        assert vnz.scan_stats["rejected_stale_premise"] == 1
        assert not vnz._scan_kick.is_set()

    def test_backcompat_without_scan_state(self, scan_env, monkeypatch, scanner_clean):
        # بلا last_scan_at إطلاقًا (إقلاع جديد) — سلوك FE1.8.3 السابق: لا إعجال ولا أثر
        _patch_scan(monkeypatch,
                    make_setup(prices=[150.0, 165.0, 154.5, 177.0, 159.0, 168.0]))
        vnz.scan_cycle()
        assert vnz.scan_stats["rejected_stale_premise"] == 1
        assert not vnz._scan_kick.is_set()


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 4 — النشر والحراسات الجوهرية
# ─────────────────────────────────────────────────────────────────────────────

class TestDeploymentAndBoundaries:

    def test_render_yaml_carries_values(self):
        # مصدر الحقيقة على Render — يجب أن يحمل قيم FE1.8.6
        import pathlib
        y = pathlib.Path("render.yaml").read_text(encoding="utf-8")
        assert 'value: "30"' in y          # SCAN_TOP_N + MAX_STRUCTURE_AGE_BARS
        assert 'value: "2700"' in y        # IDLE_RESCAN_MIN_GAP_SEC
        assert vnz.SCAN_TOP_N == 30 and vnz.MAX_STRUCTURE_AGE_BARS == 36

    def test_premise_gate_untouched(self):
        # البوابة الجوهرية FE1.6.2: إغلاق تحت P0 = فرضية ميتة — بلا تساهل
        dead = make_setup(prices=[150.0, 165.0, 154.5, 177.0, 159.0, 168.0])
        alive = make_setup()
        assert vnz.premise_alive(dead, 110.0) is False
        assert vnz.premise_alive(alive, 110.0) is True
        assert vnz.premise_alive(dead, None) is True   # فشل القراءة = تساهل (fail-open)

    def test_quality_gates_values_untouched(self):
        # التخفيف في الأعمار والاتساع فقط — بوابات الجودة بقيت بقيمها
        assert vnz.MAX_ENTRY_DISTANCE_PCT == 1.5      # لا مطاردة
        assert vnz.RR_NET_MIN == 0.3                  # أرضية R:R الصافي
        assert vnz.SYMBOL_COOLDOWN_SEC == 5400.0      # تبريد الرمز 90 دقيقة
        assert vnz.PENDING_MAX_CANDLES == 10          # [EL2.4.0] درس باك تاست E7/E8 (كان 6 من FE1.8.3)
        assert vnz.CLUSTER_MAX_SAME_DIRECTION == 3    # سقف العنقود
        assert vnz.KEEP_ALIVE_INTERVAL_SEC == 60.0    # نبضة الدقيقة من FE1.8.3
