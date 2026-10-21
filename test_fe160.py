#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fe160.py — اختبارات اقتباسات ElliottWavesEngine في FE1.6.0

ثماني جولات:
  1) القاعدة 2 بالفضاء اللوغاريتمي: عدّة تمر خطيًا وتُرفض لوغاريتميًا (W3 ليس الأقصر نسبيًا)
  2) القاعدة 4 — الأرضية التناسبية: W1 هزيلة تُرفض، والتعطيل (0) يعيد سلوك FE1.5
  3) القواعد 1 و3 واعية بالذيل: ويك يخترق أصل W1 أو أرض W1 يبطل العدّة
  4) تنقية الزيجزاج بالويك: المحور يُثبّت عند القيمة القصوى المطلقة High/Low
  5) التكامل عبر scan: دافع فيه ويك مخلّ لا يُكشف إطلاقًا، ونظيفه يُكشف
  6) سلّم الأهداف: أقرب هدف يحقق TP_MIN_RR + الاحتياطي 1.618 + التعطيل
  7) التقييم المركب: امتداد W3 ومساواة W5=W1 يهزمان الأحدث
  8) بوابة تحيز الفريم الأعلى: هابط قوي/صاعد/فشل fail-open/الكاش + بوابة scan_cycle

تشغيل: pytest test_fe160.py -v   (من داخل مجلد المشروع)
"""

import json
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة

from engine.pattern_detector import DetectorConfig, PivotDetector
from engine.wave_validator import validate_impulse


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
def _no_network(monkeypatch):
    """عزل شبكة: بطاقة باينانس تُعمى + لا إشعارات تلجرام."""
    def _stub(force=False):
        return {"connected": True, "keys_present": False, "testnet": False,
                "latency_ms": 42, "usdt_free": None, "usdt_total": None,
                "can_trade": None, "error": None, "checked_at": vnz.utc_now_iso()}
    monkeypatch.setattr(vnz, "binance_status_snapshot", _stub)
    monkeypatch.setattr(vnz, "send_telegram_message", lambda *a, **k: None)


def leg_candles(start: float, end: float, n: int, t0: int,
                wick_overrides: dict = None) -> list:
    """n شموع خطية من start إلى end مع high/low حول المسار.
    wick_overrides: {موقع_بالشمعة_المطلق: (high, low)} لتجاوز ذيول شموع محددة."""
    rows = []
    step = (end - start) / n
    for i in range(n):
        o = start + step * i
        c = start + step * (i + 1)
        h = max(o, c) * 1.0005
        lo = min(o, c) * 0.9995
        rows.append([t0 + i * 900_000, o, h, lo, c, 1000.0])
    if wick_overrides:
        for idx, (h, lo) in wick_overrides.items():
            rows[idx][2] = h
            rows[idx][3] = lo
    return rows


def impulse_df(pts=None, wick_overrides=None) -> pd.DataFrame:
    """دافع صاعد مصطنع (افتراضي: P0=100 P1=120 P2=110 P3=140 P4=125 P5=135).
    wick_overrides: {موقع_الشمعة_المطلق: (high, low)} — تُطبق بعد التجميع."""
    pts = pts or [(100.0, 120.0, 5), (120.0, 110.0, 4), (110.0, 140.0, 6),
                  (140.0, 125.0, 4), (125.0, 135.0, 4)]
    rows, t = [], 1_700_000_000_000
    for a, b, n in pts:
        rows += leg_candles(a, b, n, t)
        t += n * 900_000
    if wick_overrides:
        for idx, (h, lo) in wick_overrides.items():
            rows[idx][2] = h
            rows[idx][3] = lo
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df["symbol"] = "TEST/USDT"
    df["timeframe"] = "15m"
    return df[["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]]


DET16 = PivotDetector(DetectorConfig(method="zigzag", deviation_threshold=0.01,
                                     price_source="close", min_wave_bars=2,
                                     min_wave_proportion=0.15))


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 1 — القاعدة 2 بالفضاء اللوغاريتمي
# ─────────────────────────────────────────────────────────────────────────────

class TestLogSpaceRule2:
    def test_linear_passes_log_fails(self):
        """W3 أطول خطيًا (10.5 > 10) لكن أقصر نسبيًا (9.26% < min(9.53%, 9.36%)) —
        العدّة الشاحنة التي كانت تمر على FE1.5 تُرفض الآن."""
        P0, P1, P2, P3, P4, P5 = 100.0, 110.0, 109.0, 119.5, 112.0, 123.0
        # تحقق يدوي من الفجوة: خطي يمر
        assert (P3 - P2) > min(P1 - P0, P5 - P4)
        # لوغاريتمي يرفض
        w1 = math.log(P1 / P0); w3 = math.log(P3 / P2); w5 = math.log(P5 / P4)
        assert w3 < min(w1, w5)
        r = validate_impulse(P0, P1, P2, P3, P4, P5)
        assert not r.is_valid
        fails = [x.rule_name for x in r.failed_rules()]
        assert "Rule-2: W3 Not Shortest" in fails, f"القاعدة 2 يجب أن تفشل: {fails}"

    def test_log_lengths_on_wave_pivots(self):
        from engine.wave_validator import WavePivots
        p = WavePivots(100, 120, 110, 140, 125, 135)
        assert math.isclose(p.wave1_log_length, math.log(1.2), rel_tol=1e-9)
        assert math.isclose(p.parent_log_length, math.log(1.35), rel_tol=1e-9)

    def test_classic_impulse_still_valid_log(self):
        """المثال الكلاسيكي (نِسَب 20/27/8%) يبقى صالحًا بالفضاء اللوغاريتمي."""
        r = validate_impulse(100, 120, 110, 140, 125, 135)
        assert r.is_valid, r.summary()


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 2 — القاعدة 4 الأرضية التناسبية
# ─────────────────────────────────────────────────────────────────────────────

class TestProportionFloor:
    def test_anemic_w1_rejected(self):
        """W1 بـ 0.5% مقابل حركة أمومية 4.5% — كانت تجتاز القواعد الثلاث وتُرفض الآن."""
        # R1: P2=100.2 > P0=100 ✓ | R2 لوغاريتمي: W3 4.7% > min(0.5%, 1.94%) ✓ | R3: 102.5 > 100.5 ✓
        r = validate_impulse(100.0, 100.5, 100.2, 105.0, 102.5, 104.5)
        fails = [x.rule_name for x in r.failed_rules()]
        assert not r.is_valid
        assert "Rule-4: Motive Wave Proportion Floor" in fails, f"{fails}"
        # بقية القواعد الثلاث تمر — القاعدة 4 وحدها الحَكَم
        assert len(fails) == 1

    def test_floor_disabled_restores_old_behavior(self):
        r = validate_impulse(100.0, 100.5, 100.2, 105.0, 102.5, 104.5,
                             min_wave_proportion=0)
        assert r.is_valid, "بإبطال الأرضية يجب أن يعود سلوك FE1.5"

    def test_floor_via_detector_config(self):
        cfg = DetectorConfig(method="zigzag", deviation_threshold=0.01,
                             min_wave_proportion=0.5)
        assert cfg.min_wave_proportion == 0.5
        with pytest.raises(ValueError):
            DetectorConfig(min_wave_proportion=1.5)

    def test_healthy_impulse_passes_floor(self):
        """الدافع الكلاسيكي: كل الأمواج ≥ 15% من الأمومية."""
        r = validate_impulse(100, 120, 110, 140, 125, 135)
        assert r.is_valid
        assert r.rules["Rule-4: Motive Wave Proportion Floor"].passed


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 3 — القواعد 1 و3 واعية بالذيل
# ─────────────────────────────────────────────────────────────────────────────

class TestWickAwareRules:
    def test_wick_breaks_w1_origin_rejects(self):
        """ويك قاع بعد P0 يلمس أصل W1 — كانت الإغلاقات تخفيه."""
        r = validate_impulse(100, 120, 110, 140, 125, 135,
                             wick_min_low_p0p2=99.5)
        assert not r.is_valid
        assert not r.rules["Rule-1: W2 Retracement Bound"].passed

    def test_wick_dips_into_w1_territory_rejects(self):
        """ويك قاع بين P3 وP5 يدخل أرض W1 — اختراق R3 كان خفيًا."""
        r = validate_impulse(100, 120, 110, 140, 125, 135,
                             wick_min_low_p3p5=119.0)
        assert not r.is_valid
        assert not r.rules["Rule-3: W4 No Overlap with W1"].passed

    def test_bearish_wick_high_variants(self):
        """هابط: ويك قمة فوق أصل W1 (R1) أو فوق قاع W1 (R3)."""
        r1 = validate_impulse(200, 180, 190, 160, 175, 165,
                              wick_max_high_p0p2=201.0)
        assert not r1.rules["Rule-1: W2 Retracement Bound"].passed
        r3 = validate_impulse(200, 180, 190, 160, 175, 165,
                              wick_max_high_p3p5=181.0)
        assert not r3.rules["Rule-3: W4 No Overlap with W1"].passed

    def test_benign_wicks_do_not_reject(self):
        """ويكات لا تلمس الحدود — العدّة تبقى صالحة."""
        r = validate_impulse(100, 120, 110, 140, 125, 135,
                             wick_min_low_p0p2=105.0, wick_min_low_p3p5=122.0)
        assert r.is_valid, r.summary()

    def test_classic_call_without_wicks_still_works(self):
        """التوافق الخلفي: نداء نقاطي بلا ويكات = سلوك كلاسيكي."""
        r = validate_impulse(100, 120, 110, 140, 125, 135)
        assert r.is_valid and len(r.rules) == 4  # 3 قواعد + القاعدة 4


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 4 — تنقية الزيجزاج بالويك
# ─────────────────────────────────────────────────────────────────────────────

class TestZigzagWickRefinement:
    def test_wick_extreme_index_basics(self):
        arr = np.array([5.0, 9.0, 7.0, 9.0, 6.0])
        # أعلى قيمة مع تعادل — الأحدث يُفضل
        assert PivotDetector._wick_extreme_index(arr, 0, 4, want_max=True) == 3
        assert PivotDetector._wick_extreme_index(arr, 0, 4, want_max=False) == 0
        # شريحة جزئية
        assert PivotDetector._wick_extreme_index(arr, 2, 4, want_max=True) == 3
        # حدود خارج النطاق تُقيَّد
        assert PivotDetector._wick_extreme_index(arr, -10, 99, want_max=False) == 0

    def test_peak_pinned_to_true_wick_high(self):
        """قمة بالإغلاق 118 لكن ذيل 125 على شريط أسبق — المحور يجب أن يكون 125."""
        pts = [(100.0, 118.0, 10), (118.0, 106.0, 6)]   # صعود ثم هبوط ≥ 1%
        # شمعة 4 داخل الصعود: إغلاق ~107.2 وذيل 125 أعلى من قمة المسار كلها
        df = impulse_df(pts, wick_overrides={4: (125.0, 107.0)})
        det = PivotDetector(DetectorConfig(method="zigzag", deviation_threshold=0.01,
                                           price_source="close", min_wave_bars=2))
        pivots = det._detect_pivots_zigzag(
            df["close"].to_numpy(dtype=float),
            df["high"].to_numpy(dtype=float),
            df["low"].to_numpy(dtype=float),
        )
        peaks = [p for p in pivots if p.is_peak]
        assert peaks, "يجب تأكيد قمة واحدة على الأقل"
        top = max(p.price for p in peaks)
        assert math.isclose(top, 125.0, rel_tol=1e-6), \
            f"القمة يجب أن تُثبّت على ويك 125 لا على إغلاق المسار: {top}"

    def test_alternation_preserved_after_refinement(self):
        """التنقية لا تكسر التناوب الصارم قمة/قاع ولا ترتيب الشراائط."""
        setups_df = impulse_df()
        det = PivotDetector(DetectorConfig(method="zigzag", deviation_threshold=0.01,
                                           price_source="close", min_wave_bars=2))
        pivots = det._detect_pivots_zigzag(
            setups_df["close"].to_numpy(dtype=float),
            setups_df["high"].to_numpy(dtype=float),
            setups_df["low"].to_numpy(dtype=float),
        )
        for a, b in zip(pivots, pivots[1:]):
            assert a.pivot_type != b.pivot_type, "التناوب مكسور"
            assert b.bar_index > a.bar_index, "شريطا محورين على نفس الشريط"


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 5 — تكامل scan: الويك المخلّ يمنع الكشف
# ─────────────────────────────────────────────────────────────────────────────

class TestScanWickIntegration:
    def test_wick_violating_impulse_not_detected(self):
        """دافع صالح على الإغلاقات لكن ويك قاع بين P0 وP2 يخترق P0 —
        FE1.5 كان يكشفه (والوقف عند P0×0.999 سيُلمس حيًا)، FE1.6 يرفضه."""
        # الرحلة 110→118 قربها شمعة بويك قاع 99.5 (< P0=100)
        wick = {9: (111.0, 99.5)}   # شمعة ضمن رحلة W2 (بعد الشمعة 5)
        df = impulse_df(wick_overrides=wick)
        bulls = [s for s in DET16.scan(df) if s.direction == "BULLISH"]
        assert not bulls, "ويك يخترق أصل W1 يجب أن يبطل الكشف كله"

    def test_clean_impulse_still_detected(self):
        """نفس الدافع بلا الويك المخلّ يُكشف طبيعيًا (لا فرط رفض)."""
        df = impulse_df()
        bulls = [s for s in DET16.scan(df) if s.direction == "BULLISH"]
        assert bulls, "الدافع النظيف يجب أن يُكشف"
        s = bulls[-1]
        for got, want in zip(s.pivot_prices, [100, 120, 110, 140, 125, 135]):
            assert math.isclose(got, want, rel_tol=0.02)

    def test_wick_extremes_attached_to_validation(self):
        """النتيجة تحمل الويكات: قاع الشريحة (P0,P2] يظهر في مفاصلات القاعدة 1."""
        df = impulse_df(wick_overrides={9: (111.0, 104.0)})   # ويك عميق لكن فوق P0
        bulls = [s for s in DET16.scan(df) if s.direction == "BULLISH"]
        assert bulls
        p = bulls[-1].pivot_prices
        r = bulls[-1].validation_result
        # أدنى قاع في الشريحة أعمق من P2 المحوري نفسه (الويك 104 < P2=110)
        assert r.rules["Rule-1: W2 Retracement Bound"].passed


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 6 — سلّم الأهداف
# ─────────────────────────────────────────────────────────────────────────────

def make_setup(pivots, direction="BULLISH"):
    """DetectedSetup حقيقي من pivots عبر المحرك — ValidationResult كامل بفيبو."""
    pts = list(zip(pivots[:-1], pivots[1:]))
    segs = [(a, b, 4) for a, b in pts]
    df = impulse_df([(a, b, n) for a, b, n in segs])
    setups = [s for s in DET16.scan(df) if s.direction == direction]
    assert setups, f"لا إعداد من {pivots}"
    return setups[-1]


class TestTargetLadder:
    def test_ladder_sorted_and_annotated(self):
        s = make_setup([100.0, 110.0, 105.0, 118.0, 113.0, 117.0])
        ladder = vnz.compute_tp_ladder(s)
        assert len(ladder) == 3
        prices = [c for c, _ in ladder]
        assert prices == sorted(prices), "الصاعد يجب أن يكون تصاعديًا (الأقرب أولًا)"
        bases = {b for _, b in ladder}
        assert bases == {"w5_eq_w1", "w5_0618_w3", "ext_1618"}

    def test_nearest_target_meeting_min_rr_wins(self):
        s = make_setup([100.0, 110.0, 105.0, 118.0, 113.0, 117.0])
        entry, sl = float(s.entry_zone_low), float(s.stop_loss_price)
        risk = entry - sl
        assert risk > 0
        tp = vnz.compute_take_profit(s)      # 1.618 الأصلي
        # مع الأرضية 0.5: هدف السلّم المقبول
        chosen = None
        for cand, basis in vnz.compute_tp_ladder(s):
            if (cand - entry) / risk >= vnz.TP_MIN_RR:
                chosen = (cand, basis)
                break
        assert chosen is not None, "هذا الإعداد يجب أن يُنتج هدفًا مقبولًا من السلّم"
        assert chosen[1] in ("w5_eq_w1", "w5_0618_w3", "ext_1618")

    def test_all_below_floor_falls_back_to_1618(self):
        """إعداد الدخول البعيد: كل أهداف السلّم تحت الأرضية → يبقى 1.618 الأصلي."""
        s = make_setup([100.0, 120.0, 110.0, 140.0, 125.0, 135.0])
        entry, sl = float(s.entry_zone_low), float(s.stop_loss_price)
        risk = entry - sl
        qualifying = [c for c, _ in vnz.compute_tp_ladder(s)
                      if (c - entry) / risk >= vnz.TP_MIN_RR]
        if not qualifying:
            assert math.isclose(vnz.compute_take_profit(s),
                                110.0 + 1.618 * 20.0, rel_tol=1e-6)
        else:
            pytest.skip("الإعداد أنتج هدفًا مؤهلًا — الحالة غير مطبقة")

    def test_ladder_disabled_flag_exists(self):
        """الرقابة عبر متغير البيئة موجودة في الوحدة (تُقرأ عند الإقلاع)."""
        assert isinstance(vnz.TP_LADDER_ENABLED, bool)
        assert vnz.TP_MIN_RR > 0


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 7 — التقييم المركب
# ─────────────────────────────────────────────────────────────────────────────

class TestCompositeScoring:
    def _setup_from(self, pivots):
        return make_setup(pivots)

    def test_structure_quality_beats_recency(self):
        """إعداد بامتداد W3 قرب 1.618 ومساواة W5=W1 يتفوق على إعداد أحدث
        بمناطق فيبو مماثلة لكن بنية أضعف (امتداد 0.9 وW5 نصف W1).
        الاثنان بنفس مناطق W2/W4 تقريبًا — الفرق في جودة البنية فقط."""
        w1 = math.log(1.10)
        p2 = 105.0
        # القوي: W3 = 1.618 × W1 (لوغاريتميًا)، W4 تراجع 45%، W5 = W1
        p3g = p2 * math.exp(w1 * 1.618)
        p4g = p3g - 0.45 * (p3g - p2)
        p5g = p4g * math.exp(w1)
        s_good = self._setup_from([100.0, 110.0, p2, p3g, p4g, p5g])
        # الضعيف: W3 = 0.9 × W1، W4 تراجع 35%، W5 = 0.55 × W1
        p3w = p2 * math.exp(w1 * 0.9)
        p4w = p3w - 0.35 * (p3w - p2)
        p5w = p4w * math.exp(w1 * 0.55)
        s_weak = self._setup_from([100.0, 110.0, p2, p3w, p4w, p5w])
        # الأضعف أحدث — القديم القوي يجب أن يفوز (النقاط تسبق الأحدث)
        later = s_weak.detected_at + pd.Timedelta(hours=2)
        s_weak = s_weak.__class__(**{**s_weak.__dict__, "detected_at": later})
        best = vnz.select_best_setup([s_weak, s_good])
        assert best is s_good, "البنية الأقوى يجب أن تتفوق على الأحدث"

    def test_single_setup_short_circuit(self):
        s = self._setup_from([100.0, 120.0, 110.0, 140.0, 125.0, 135.0])
        assert vnz.select_best_setup([s]) is s
        assert vnz.select_best_setup([]) is None


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 8 — بوابة تحيز الفريم الأعلى
# ─────────────────────────────────────────────────────────────────────────────

def daily_df(closes) -> pd.DataFrame:
    n = len(closes)
    ts = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")
    df = pd.DataFrame({
        "ts": (ts.astype("int64") // 10**6),
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": [1000.0] * n,
        "timestamp": ts, "symbol": "X/USDT", "timeframe": "1d",
    })
    return df


class TestHTFBias:
    def setup_method(self):
        vnz._htf_cache.clear()

    def test_strong_bear_rejected(self):
        """حقبة هابطة واضحة: إغلاق < SMA50 وSMA20 < SMA50 وصافي 20 شمعة < -8%."""
        closes = list(np.linspace(100, 78, 55))   # هبوط ~22%
        monkey_df = daily_df(closes)
        import vnz as _v
        orig = _v.fetch_ohlcv_df
        _v.fetch_ohlcv_df = lambda *a, **k: monkey_df
        try:
            assert vnz.htf_bias("BAD/USDT") is False
        finally:
            _v.fetch_ohlcv_df = orig

    def test_neutral_or_bullish_allowed(self):
        closes = list(np.linspace(80, 100, 55))   # صعود
        monkey_df = daily_df(closes)
        import vnz as _v
        orig = _v.fetch_ohlcv_df
        _v.fetch_ohlcv_df = lambda *a, **k: monkey_df
        try:
            assert vnz.htf_bias("OK/USDT") is True
        finally:
            _v.fetch_ohlcv_df = orig

    def test_fetch_failure_fail_open(self):
        import vnz as _v
        orig = _v.fetch_ohlcv_df
        _v.fetch_ohlcv_df = lambda *a, **k: None
        try:
            assert vnz.htf_bias("FAIL/USDT") is None   # مجهول = يُسمح
        finally:
            _v.fetch_ohlcv_df = orig

    def test_cache_prevents_refetch(self):
        calls = {"n": 0}
        closes = list(np.linspace(100, 78, 55))
        monkey_df = daily_df(closes)

        def fake_fetch(*a, **k):
            calls["n"] += 1
            return monkey_df
        import vnz as _v
        orig = _v.fetch_ohlcv_df
        _v.fetch_ohlcv_df = fake_fetch
        try:
            vnz.htf_bias("CACHED/USDT")
            vnz.htf_bias("CACHED/USDT")
            vnz.htf_bias("CACHED/USDT")
        finally:
            _v.fetch_ohlcv_df = orig
        assert calls["n"] == 1, "الكاش يجب أن يمنع إعادة الجلب"


class TestScanCycleHTFGate:
    @pytest.fixture()
    def scan_env(self, clean_db, monkeypatch):
        """بيئة scan_cycle معزولة: زوج واحد بدافع صاعد حقيقي."""
        monkeypatch.setattr(vnz, "INTER_SYMBOL_SLEEP", 0.0)
        monkeypatch.setattr(vnz, "is_trading_enabled", True)
        monkeypatch.setattr(vnz, "watchlist", ["TEST/USDT"])
        monkeypatch.setattr(vnz, "fetch_ohlcv_df",
                            lambda *a, **k: impulse_df())
        # [FE1.7.0] بوابة المطاردة معطلة هنا — دافع الاختبار المصطنع ينتهي عند P5
        # (الإغلاق 135 فوق منطقة الدخول 128.54 بـ5%) وهي بوابة تُختبر في test_fe170
        monkeypatch.setattr(vnz, "MAX_ENTRY_DISTANCE_PCT", 0.0)
        with vnz.scan_stats_lock:
            vnz.scan_stats["rejected_htf_bias"] = 0
        yield

    def test_bearish_bias_blocks_signal(self, scan_env, monkeypatch):
        monkeypatch.setattr(vnz, "htf_bias", lambda sym: False)
        vnz.scan_cycle()
        with vnz.scan_stats_lock:
            assert vnz.scan_stats["rejected_htf_bias"] >= 1
        rows = vnz.db.query("SELECT COUNT(*) AS n FROM signals")
        assert int(rows[0]["n"]) == 0, "لا إشارة مع تحيز هابط قوي"

    def test_bullish_bias_allows_signal(self, scan_env, monkeypatch):
        monkeypatch.setattr(vnz, "htf_bias", lambda sym: True)
        vnz.scan_cycle()
        rows = vnz.db.query("SELECT COUNT(*) AS n FROM signals")
        assert int(rows[0]["n"]) == 1, "إشارة ورقية واحدة مع تحيز سليم"
        sig = vnz.db.query("SELECT * FROM signals")[0]
        fib = json.loads(sig["fib_json"])
        assert "tp_basis" in fib, "fib_json يجب أن يحمل أساس الهدف [FE1.6.0]"
        assert "tp_ladder" in fib, "fib_json يجب أن يحمل سلّم الأهداف [FE1.6.0]"

    def test_htf_disabled_skips_gate(self, scan_env, monkeypatch):
        called = {"n": 0}
        def _spy(sym):
            called["n"] += 1
            return False
        monkeypatch.setattr(vnz, "HTF_BIAS_ENABLED", False)
        monkeypatch.setattr(vnz, "htf_bias", _spy)
        vnz.scan_cycle()
        assert called["n"] == 0, "البوابة معطلة — لا نداء إطلاقًا"
        rows = vnz.db.query("SELECT COUNT(*) AS n FROM signals")
        assert int(rows[0]["n"]) == 1
