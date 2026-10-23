#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات EL2.0.0 — مؤشرات الاستراتيجيات المتوازية
====================================================
تغطية حسابية خالصة (بلا شبكة وبلا قاعدة بيانات):
  1) SuperTrend (صيغة flowsurface): اتجاه صاعد/هابط + انقلاب + قفل النطاقات
  2) ATR/ADX ويلدر: حدود وقيم منطقية
  3) CVD: وضع التاكير (حقيقة باينانس) + وضع proxy الصادق
  4) VWAP ضمن المدى
  5) Volume Profile: ترتيب VAL < POC < VAH + منطقة قيمة ~70% + كتلة مركزة
  6) جدران السيولة: تجميع صناديق + كشف جدار شاذ + الأقرب فوق/تحت
  7) مستويات فيبو + القمم/القيعان المؤكدة + تحويل الصفوف
  8) closed_rows: استبعاد الشمعة الجارية (لا قرار على شمعة لم تغلق)
"""

import math

import pytest

from strategies import indicators as ind


# ─────────────────────────────────────────────────────────────────────────────
# بناة بيانات صناعية
# ─────────────────────────────────────────────────────────────────────────────

def trend_rows(n=90, start=100.0, drift=0.02, wick=0.5, vol=100.0,
               taker_ratio=0.62, last_vol_mult=2.0):
    """سلسلة صاعدة بسيطة — taker_ratio > 0.5 يعني دلتا موجبة (مشترون مسيطرون)."""
    rows = []
    px = start
    for i in range(n):
        o = px
        c = px + drift
        h = max(o, c) + wick
        l = min(o, c) - wick
        v = vol * (last_vol_mult if i == n - 1 else 1.0)
        rows.append({"ts": i * 300000.0, "open": o, "high": h, "low": l,
                     "close": c, "volume": v, "taker_base": v * taker_ratio})
        px = c
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# 1) SuperTrend
# ─────────────────────────────────────────────────────────────────────────────

def test_supertrend_uptrend_dir_plus_one():
    rows = trend_rows(80, drift=0.05)
    h = [r["high"] for r in rows]; l = [r["low"] for r in rows]; c = [r["close"] for r in rows]
    st = ind.supertrend(h, l, c, 10, 2.5)
    assert st is not None
    assert st["dir"] == 1.0
    assert st["line"] < c[-1]          # خط الصاعد تحت السعر


def test_supertrend_downtrend_flips():
    # صعود قصير ثم هبوط حاد طويل — الانقلاب هابط مؤكد
    h, l, c = [], [], []
    px = 100.0
    for i in range(20):
        px += 0.5
        h.append(px + 0.4); l.append(px - 0.4); c.append(px)
    for i in range(45):
        px -= 0.6
        h.append(px + 0.4); l.append(px - 0.4); c.append(px)
    st = ind.supertrend(h, l, c, 10, 2.5)
    assert st is not None
    assert st["dir"] == -1.0
    assert st["line"] > c[-1]          # خط الهابط فوق السعر


def test_supertrend_flip_records_bar():
    # هبوط ثم صعود حاد — يجب تسجيل مؤشر انقلاب حديث
    h, l, c = [], [], []
    px = 100.0
    for i in range(30):
        px -= 0.5
        h.append(px + 0.4); l.append(px - 0.4); c.append(px)
    for i in range(30):
        px += 0.8
        h.append(px + 0.4); l.append(px - 0.4); c.append(px)
    st = ind.supertrend(h, l, c, 10, 2.5)
    assert st["dir"] == 1.0
    assert st["flip_bar"] >= 30        # الانقلاب في الطور الصاعد


def test_supertrend_insufficient_data_none():
    assert ind.supertrend([1, 2], [0, 1], [1, 2], 10, 2.5) is None


# ─────────────────────────────────────────────────────────────────────────────
# 2) ATR / ADX
# ─────────────────────────────────────────────────────────────────────────────

def test_atr_positive_and_reasonable():
    rows = trend_rows(60)
    a = ind.atr([r["high"] for r in rows], [r["low"] for r in rows],
                [r["close"] for r in rows], 14)
    assert a is not None and a > 0
    assert a < 10 * (rows[0]["high"] - rows[0]["low"])   # منطقي لا منفلت


def test_adx_strong_trend_above_threshold():
    rows = trend_rows(80, drift=0.05)
    adx = ind.adx([r["high"] for r in rows], [r["low"] for r in rows],
                  [r["close"] for r in rows], 14)
    assert adx is not None
    assert adx > 25                     # ترند أحادي الاتجاه = ADX مرتفع
    assert adx <= 100.0


def test_adx_choppy_market_low():
    # تذبذب جيبي بلا اتجاه — ADX منخفض
    h, l, c = [], [], []
    for i in range(80):
        p = 100 + 3 * math.sin(i / 3.0)
        h.append(p + 0.3); l.append(p - 0.3); c.append(p)
    adx = ind.adx(h, l, c, 14)
    assert adx is not None
    assert adx < 40


# ─────────────────────────────────────────────────────────────────────────────
# 3) CVD
# ─────────────────────────────────────────────────────────────────────────────

def test_cvd_taker_mode_cumulative_exact():
    rows = trend_rows(30, vol=100.0, taker_ratio=0.62, last_vol_mult=1.0)
    cv = ind.cvd_series(rows)
    assert cv["source"] == "taker"
    # دلتا كل شمعة = 2×62 − 100 = 24 → التراكمي بعد 30 = 720
    assert abs(cv["cvd"][-1] - (30 * 24.0)) < 1e-6
    assert cv["delta_last"] == pytest.approx(24.0)


def test_cvd_proxy_mode_when_no_taker_field():
    rows = [{"ts": i * 1.0, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5,
             "volume": 50.0, "taker_base": None} for i in range(20)]
    cv = ind.cvd_series(rows)
    assert cv["source"] == "proxy"
    # (close−open)/(high−low) = 0.5/2 = 0.25 → دلتا = 12.5 لكل شمعة
    assert cv["delta_last"] == pytest.approx(12.5)
    assert cv["cvd"][-1] == pytest.approx(20 * 12.5)


def test_cvd_empty_and_short():
    assert ind.cvd_series([]) is None
    assert ind.cvd_series(trend_rows(3)) is None


# ─────────────────────────────────────────────────────────────────────────────
# 4) VWAP
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_within_range():
    rows = trend_rows(40)
    vw = ind.vwap_rolling(rows)
    assert vw is not None
    assert min(r["low"] for r in rows) <= vw <= max(r["high"] for r in rows)


# ─────────────────────────────────────────────────────────────────────────────
# 5) Volume Profile
# ─────────────────────────────────────────────────────────────────────────────

def test_volume_profile_ordering_and_value_area():
    rows = trend_rows(90)
    vp = ind.volume_profile(rows, bins=48, lookback=72)
    assert vp is not None
    assert vp["val"] < vp["poc"] < vp["vah"]
    assert 0 < vp["total"]


def test_volume_profile_poc_at_mass_center():
    # كل الحجم مكدس حول 100 — POC يجب أن يجاورها
    rows = []
    for i in range(40):
        rows.append({"ts": i * 1.0, "open": 99.8, "high": 100.2, "low": 99.7,
                     "close": 100.0, "volume": 100.0, "taker_base": 55.0})
    vp = ind.volume_profile(rows, bins=24)
    assert abs(vp["poc"] - 100.0) < 0.5


def test_volume_profile_flat_rows_none():
    rows = [{"ts": i * 1.0, "open": 5.0, "high": 5.0, "low": 5.0, "close": 5.0,
             "volume": 10.0, "taker_base": 5.0} for i in range(20)]
    assert ind.volume_profile(rows) is None


# ─────────────────────────────────────────────────────────────────────────────
# 6) جدران السيولة
# ─────────────────────────────────────────────────────────────────────────────

def test_detect_walls_finds_outlier_bucket():
    levels = [(99.0 + 0.5 * i, 1.0) for i in range(10)]      # ضجيج موزع على صناديق
    levels.append((102.0, 500.0))                            # جدار شاذ
    walls = ind.detect_walls(levels, bucket=1.0, k=6.0)
    assert walls
    prices = [w[0] for w in walls]
    assert any(abs(p - 102.0) < 1.0 for p in prices)


def test_detect_walls_no_outlier_no_walls():
    levels = [(100 + 0.1 * i, 2.0) for i in range(30)]
    assert ind.detect_walls(levels, bucket=1.0, k=6.0) == []


def test_nearest_wall_above_and_below():
    walls = [(99.0, 300.0), (101.0, 400.0), (104.0, 900.0)]
    assert ind.nearest_wall(walls, above=True, ref_price=100.0)[0] == 101.0
    assert ind.nearest_wall(walls, above=False, ref_price=100.0)[0] == 99.0


# ─────────────────────────────────────────────────────────────────────────────
# 7) فيبو + قمم/قيعان + تحويل صفوف
# ─────────────────────────────────────────────────────────────────────────────

def test_fib_retrace_levels_exact():
    lv = ind.fib_retrace_levels(100.0, 200.0)
    assert lv["0.618"] == pytest.approx(200.0 - 61.8)
    assert lv["0.786"] == pytest.approx(200.0 - 78.6)
    assert lv["0.5"] == pytest.approx(150.0)


def test_last_confirmed_swing():
    highs = [10, 10, 12, 9, 9, 10, 11, 10]
    lows = [11, 11, 9, 11, 11, 8, 9, 10]
    sh, sl = ind.last_confirmed_swing(highs, lows, right=2)
    assert sh == 12.0
    assert sl == 8.0


def test_rows_from_full_and_basic():
    full = [[1729000000000, "1", "2", "0.5", "1.5", "10", "0", "0", "0", "7", "0", "0"]]
    rows = ind.rows_from_full(full)
    assert rows[0]["taker_base"] == 7.0 and rows[0]["close"] == 1.5
    basic = [[1729000000000, "1", "2", "0.5", "1.5", "10"]]
    rows_b = ind.rows_from_basic(basic)
    assert rows_b[0]["taker_base"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 8) closed_rows — صدق الشموع المغلقة
# ─────────────────────────────────────────────────────────────────────────────

def test_closed_rows_excludes_forming_candle():
    now = 1_000_000.0
    tf = 300
    rows = [
        {"ts": (now - 2 * tf) * 1000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        {"ts": (now - 1 * tf) * 1000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        {"ts": now * 1000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},  # جارية
    ]
    out = ind.closed_rows(rows, tf, now_ts=now)
    assert len(out) == 2


def test_closed_rows_fallback_without_now():
    rows = trend_rows(5)
    out = ind.closed_rows(rows, 300)
    assert len(out) == 4    # الأخيرة تُستبعد افتراضيًا


# ─────────────────────────────────────────────────────────────────────────────
# [EL2.2.0] بولنجر وكيلتنر وDI — أدوات انفجار الاختناق
# ─────────────────────────────────────────────────────────────────────────────

def test_bollinger_flat_market_zero_width():
    closes = [100.0] * 30
    bb = ind.bollinger(closes, 20, 2.0)
    assert bb is not None
    assert bb["upper"] == pytest.approx(100.0)
    assert bb["mid"] == pytest.approx(100.0)
    assert bb["lower"] == pytest.approx(100.0)
    assert bb["width"] == pytest.approx(0.0)


def test_bollinger_known_sigma():
    # نصف القيم 102 ونصفها 98 → متوسط 100 وσ العينة = 2 → العرض = 8
    closes = [102.0] * 10 + [98.0] * 10
    bb = ind.bollinger(closes, 20, 2.0)
    assert bb["mid"] == pytest.approx(100.0)
    assert bb["upper"] == pytest.approx(104.0)
    assert bb["lower"] == pytest.approx(96.0)
    assert bb["width"] == pytest.approx(8.0)


def test_bollinger_short_series_none():
    assert ind.bollinger([100.0] * 10, 20, 2.0) is None


def test_keltner_atr_bands_symmetric():
    highs = [101.0] * 30
    lows = [99.0] * 30
    closes = [100.0] * 30
    kc = ind.keltner(highs, lows, closes, 20, 1.5)
    assert kc is not None
    assert kc["mid"] == pytest.approx(100.0)
    # ATR = 2.0 → النطاق ± 3.0
    assert kc["upper"] == pytest.approx(103.0)
    assert kc["lower"] == pytest.approx(97.0)
    assert kc["width"] == pytest.approx(6.0)


def test_keltner_short_series_none():
    assert ind.keltner([100.0] * 5, [100.0] * 5, [100.0] * 5, 20, 1.5) is None


def test_squeeze_condition_flat_market():
    """السوق المختنق الحقيقي: بولنجر (σ صغير) داخل كيلتنر (ATR ذيول) —
    الحالة المرجعية لاستراتيجية انفجار الاختناق."""
    closes = [100.0] * 30
    bb = ind.bollinger(closes, 20, 2.0)
    kc = ind.keltner([100.2] * 30, [99.8] * 30, closes, 20, 1.5)
    assert bb["width"] < kc["width"]


def test_di_directional_separation():
    """اتجاه صاعد صريح: +DI فوق −DI — واتجاه هابط: العكس. نفس حسابات ADX."""
    ups = ind.di([101.0 + i * 0.5 for i in range(40)],
                 [99.0 + i * 0.5 for i in range(40)],
                 [100.0 + i * 0.5 for i in range(40)], 14)
    assert ups is not None and ups["pdi"] > ups["mdi"]
    downs = ind.di([101.0 - i * 0.5 for i in range(40)],
                   [99.0 - i * 0.5 for i in range(40)],
                   [100.0 - i * 0.5 for i in range(40)], 14)
    assert downs is not None and downs["mdi"] > downs["pdi"]
    # اتساق ADX مع adx() القديمة — نفس الحسابات
    assert ups["adx"] == pytest.approx(ind.adx(
        [101.0 + i * 0.5 for i in range(40)], [99.0 + i * 0.5 for i in range(40)],
        [100.0 + i * 0.5 for i in range(40)], 14))


def test_di_immature_series_none():
    assert ind.di([100.0] * 20, [100.0] * 20, [100.0] * 20, 14) is None
