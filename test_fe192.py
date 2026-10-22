#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fe192.py — اختبارات FE1.9.2 «كشف بلا عمى»

التشريح الحي الذي أمر به المستخدم («لاحض الفحص كلها بنية متقادمة ولا توصية
تقبل») وكشف ثلاث حقائق قاطعة (30 رمزًا × نافذة 500 شمعة × عتبات 0.6/0.4/0.3%):
  1) صفر بنيات صاعدة حديثة في السوق كله (الأحدث 38 شمعة والبقية 117–469)
     — البوابات صادقة والسوق هو من لا يولّد لونجات حديثة
  2) 3 رموز (STRK/BAT/RNDR) تكسر الزيجزاج: انعكاس مؤكد على الشريط الأخير
     ثم محور ختامي مطلوب بعده = شريحة فارغة = argmin على تسلسل فارغ =
     الرمز يتخطى بصمت كل دورة (كشف أعمى بلا أي أثر في الإحصاءات)
  3) المختار الوحيد الذي تقيّمه البوابات هو select_best_setup — القديمة
     الأجود إليوتيًا كانت قادرة على دفن الحديثة المتواضعة (H2)

الإصلاحات الثلاثة (كل محور له اختبارات):
  أ) الزيجزاج: الشريحة الفارغة → المحور الختامي على الشريط الأخير ذاته
     (دلالة الإغلاق قبل تحسين الويك FE1.6.0) — بلا انكسار
  ب) التقادم قبل الاختيار: الحديثة تُقيَّم ولو وُجدت قديمة أعلى نقاطًا
  ج) عداد scan_errors: الاستثناءات الصامتة تصير مرئية في /api/all

تشغيل: pytest test_fe192.py -v   (من داخل مجلد المشروع)
"""

import sqlite3

import numpy as np
import pandas as pd
import pytest

import vnz
from engine.pattern_detector import DetectorConfig, PivotDetector
vnz.DASHBOARD_PROTECTED = False


# ─────────────────────────────────────────────────────────────────────────────
# تجهيزات (نفس عقد test_fe190)
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


def make_setup(prices=None, p5_idx: int = 95, direction: str = "BULLISH",
               symbol: str = "TEST/USDT"):
    from engine.pattern_detector import DetectedSetup
    P = prices or [90.0, 95.0, 92.0, 105.0, 100.0, 110.0]
    return DetectedSetup(
        symbol=symbol, timeframe="15m", direction=direction,
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


@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    """قاعدة SQLite مؤقتة لكل اختبار — عزل كامل."""
    monkeypatch.setattr(vnz, "USE_POSTGRES", False)
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    old = vnz.db.conn
    vnz.db.conn = conn
    vnz.init_db()
    vnz.set_paper_balance(vnz.PAPER_BALANCE_START)
    yield vnz.db
    vnz.db.conn = old


def make_detector(thresh: float = 0.006) -> PivotDetector:
    return PivotDetector(DetectorConfig(
        method="zigzag", deviation_threshold=thresh, price_source="close",
        min_wave_bars=vnz.MIN_WAVE_BARS, require_fib_confluence=False,
        fib_tolerance_pct=vnz.FIB_TOLERANCE_PCT,
        min_wave_proportion=vnz.WAVE_MIN_PROPORTION))


def ohlcv_df(closes, highs, lows):
    n = len(closes)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="15min"),
        "open": closes, "high": highs, "low": lows,
        "close": closes, "volume": [1.0] * n,
    })


# ─────────────────────────────────────────────────────────────────────────────
# أ) إصلاح انكسار الزيجزاج — الحالة المولِّدة للشريحة الفارغة
# ─────────────────────────────────────────────────────────────────────────────

def _crash_shape_df():
    """الشكل المولِّد للانكسار الحي (STRK/BAT/RNDR):
    إغلاقات تصعد ثم الشريط الأخير ينعكس ≥ العتبة بينما ذيل High لهذا الشريط
    هو الأعلى في الشريحة → قمة مؤكدة على الشريط الأخير → المحور الختامي
    (القاع المبدئي) مطلوب في شريحة بعده فارغة."""
    closes = [1.000, 1.005, 1.010, 1.015, 1.020, 1.008]
    highs = [1.002, 1.006, 1.011, 1.016, 1.021, 1.030]   # ذيل الأخير الأعلى
    lows = [0.999, 1.004, 1.009, 1.014, 1.019, 1.007]
    return ohlcv_df(closes, highs, lows)


def test_zigzag_survives_last_bar_reversal_peak_closeout():
    """الانعكاس على الشريط الأخير + قمة على ذيله: المحور الختامي يقع على
    الشريط الأخير ذاته — بلا ValueError وبلا إسقاط الكاشف كله."""
    det = make_detector(0.006)
    pivots = det._detect_pivots_zigzag(
        np.asarray(_crash_shape_df()["close"], dtype=float),
        np.asarray(_crash_shape_df()["high"], dtype=float),
        np.asarray(_crash_shape_df()["low"], dtype=float))
    assert len(pivots) >= 2
    # آخر محورين: قمة ثم قاع مبدئي على الشريط الأخير (نفس الشريط مسموح عند الإغلاق)
    assert pivots[-2].pivot_type == "peak"
    assert pivots[-1].pivot_type == "trough"
    assert pivots[-1].bar_index == len(_crash_shape_df()) - 1
    assert pivots[-1].price == pytest.approx(1.007)


def test_zigzag_survives_last_bar_reversal_trough_closeout():
    """المرآة: انعكاس صاعد على الشريط الأخير + قاع على ذيله — نفس الحماية."""
    closes = [1.020, 1.015, 1.010, 1.005, 1.000, 1.012]
    highs = [1.021, 1.016, 1.011, 1.006, 1.001, 1.013]
    lows = [1.019, 1.014, 1.009, 1.004, 0.970, 0.999]    # ذيل الأخير الأدنى
    det = make_detector(0.006)
    pivots = det._detect_pivots_zigzag(
        np.asarray(closes, dtype=float),
        np.asarray(highs, dtype=float),
        np.asarray(lows, dtype=float))
    assert len(pivots) >= 2
    assert pivots[-2].pivot_type == "trough"
    assert pivots[-1].pivot_type == "peak"
    assert pivots[-1].bar_index == len(closes) - 1
    assert pivots[-1].price == pytest.approx(1.013)


def test_detector_scan_end_to_end_on_crash_shape():
    """scan() الكامل (لا المساعد الداخلي وحده) يعيد قائمة بلا انكسار."""
    det = make_detector(0.006)
    setups = det.scan(_crash_shape_df())
    assert isinstance(setups, list)   # المهم: لا ValueError — أي نتيجة مقبولة


def test_wick_extreme_empty_segment_returns_last_bar():
    """العقد المباشر: شريحة فارغة → الشريط الأخير (لا استثناء)."""
    arr = np.asarray([1.0, 2.0, 3.0], dtype=float)
    # lo=3 > hi=2 بعد التقييد — الحالة الحية بالضبط
    assert PivotDetector._wick_extreme_index(arr, 3, 2, want_max=False) == 2
    assert PivotDetector._wick_extreme_index(arr, 3, 2, want_max=True) == 2
    # الحالات العادية لم تتأثر
    assert PivotDetector._wick_extreme_index(arr, 0, 2, want_max=True) == 2
    assert PivotDetector._wick_extreme_index(arr, 0, 2, want_max=False) == 0
    assert PivotDetector._wick_extreme_index(arr, 1, 1, want_max=True) == 1


# ─────────────────────────────────────────────────────────────────────────────
# ب) التقادم قبل الاختيار — الحديثة لا تُدفن
# ─────────────────────────────────────────────────────────────────────────────

def test_fresh_setup_not_shadowed_by_aged_better_one(clean_db, monkeypatch):
    """بنيتان: قديمة أجود + حديثة متواضعة — يجب أن تُقيَّم الحديثة (لا تقادم)."""
    aged = make_setup(p5_idx=10)    # عمر 89 شمعة > السقف 36
    fresh = make_setup(p5_idx=98, prices=[90.0, 95.0, 92.0, 105.0, 100.0, 108.0])
    assert vnz.structure_fresh(fresh, synth_df(85.0, n=100)) is True

    class _TwoDet:
        def scan(self, df):
            return [aged, fresh]

    df = synth_df(85.0, n=100)
    monkeypatch.setattr(vnz, "watchlist", ["TEST/USDT"])
    monkeypatch.setattr(vnz, "fetch_ohlcv_df", lambda *a, **k: df)
    monkeypatch.setattr(vnz, "detector", _TwoDet())
    monkeypatch.setattr(vnz, "HTF_BIAS_ENABLED", False)
    monkeypatch.setattr(vnz, "INTER_SYMBOL_SLEEP", 0)
    monkeypatch.setattr(vnz, "is_trading_enabled", False)  # نصنّف فقط — بلا أوامر
    vnz.scan_cycle()
    # الحكم ليس تقادمًا — الحديثة عاشت لتصل بوابات لاحقة (هنا: توليد معطل)
    assert vnz._get_reject_reason("TEST/USDT") != \
        "" and "متقادمة" not in vnz._get_reject_reason("TEST/USDT")


def test_all_aged_still_reports_old_structure(clean_db, monkeypatch):
    """كل بنيات الرمز أثرية: الحكم تقادم كما كان — لا انزلاق في التصنيف."""
    aged = make_setup(p5_idx=10)
    aged2 = make_setup(p5_idx=5, prices=[90.0, 94.0, 91.0, 104.0, 99.0, 109.0])

    class _TwoDet:
        def scan(self, df):
            return [aged, aged2]

    df = synth_df(85.0, n=100)
    monkeypatch.setattr(vnz, "watchlist", ["TEST/USDT"])
    monkeypatch.setattr(vnz, "fetch_ohlcv_df", lambda *a, **k: df)
    monkeypatch.setattr(vnz, "detector", _TwoDet())
    monkeypatch.setattr(vnz, "HTF_BIAS_ENABLED", False)
    monkeypatch.setattr(vnz, "INTER_SYMBOL_SLEEP", 0)
    monkeypatch.setattr(vnz, "is_trading_enabled", True)  # بوابة التوليد تسبق التقادم — نريدها تمر
    vnz.scan_cycle()
    assert "متقادمة" in vnz._get_reject_reason("TEST/USDT")


# ─────────────────────────────────────────────────────────────────────────────
# ج) عداد scan_errors — الكشف الأعمى الصامت يصير مرئيًا
# ─────────────────────────────────────────────────────────────────────────────

def test_scan_error_counter_visible(clean_db, monkeypatch):
    """كاشف يرمي استثناء: الرمز يتخطى لكن العداد يكشف العمى في /api/all."""
    class _BoomDet:
        def scan(self, df):
            raise ValueError("attempt to get argmin of an empty sequence")

    df = synth_df(85.0, n=100)
    monkeypatch.setattr(vnz, "watchlist", ["TEST/USDT"])
    monkeypatch.setattr(vnz, "fetch_ohlcv_df", lambda *a, **k: df)
    monkeypatch.setattr(vnz, "detector", _BoomDet())
    monkeypatch.setattr(vnz, "HTF_BIAS_ENABLED", False)
    monkeypatch.setattr(vnz, "INTER_SYMBOL_SLEEP", 0)

    with vnz.scan_stats_lock:
        before = vnz.scan_stats["scan_errors"]
    vnz.scan_cycle()
    with vnz.scan_stats_lock:
        assert vnz.scan_stats["scan_errors"] == before + 1


# ─────────────────────────────────────────────────────────────────────────────
# الإصدار
# ─────────────────────────────────────────────────────────────────────────────

def test_version_pair():
    import panel
    assert vnz.BOT_VERSION == "EL2.1.0"
    assert panel.BOT_VERSION == "EL2.1.0"
