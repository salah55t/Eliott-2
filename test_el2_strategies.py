#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات EL2.2.0 — منطق استراتيجيات السكالب الثلاث على بيانات صناعية
================================================================
  1) S1 Flow-Ignition: دخول زخم صحيح + أهداف مركبة على جدار + رفض الترند الهابط
     + رفض الحجم الضعيف + رفض الامتداد الزائد + هندسة وقف مثبتة داخل الحدود
  2) S2 Trend-Pullback «ركوب التيار»: تصحيح لمس القيمة في ترند قائم + استئناف
     دلتا → دخول بوقف تحت قاع التصحيح + رفض بلا نظام (15m) + رفض الامتداد
     + رفض التصحيح العميق الفاسد + قص TP2 على جدار السيولة
  3) S3 Squeeze-Breakout «انفجار الاختناق»: اختناق بولنجر/كيلتنر + انفجار
     بجسم اندفاعي وحجم ودلتا وDI → دخول بوقف تحت قاعدة الاختناق + رفض بلا
     اختناق + رفض الاختراق المستمر (ليس أول إغلاق كسر) + رفض الاتجاه غير الصاعد
  4) الواجهة المشتركة: حارس سبوت (لا بيع مكشوف) + R:R صافي بنفس صيغة المحرك
ملاحظة: اختبارات SCALP_PROFILE أُزيلت مع الاستراتيجية في EL2.2.0 (قرار الحاكم).
"""

import math

import pytest

from strategies.base import ScalpConfig, ScalpContext
from strategies.flow_ignition import FlowIgnition
from strategies.trend_pullback import TrendPullback
from strategies.squeeze_breakout import SqueezeBreakout
from strategies import indicators as ind


FEE = 0.001


# ─────────────────────────────────────────────────────────────────────────────
# بناة البيانات الصناعية
# ─────────────────────────────────────────────────────────────────────────────

def trend_rows(n=90, start=100.0, drift=0.02, wick=0.5, vol=100.0,
               taker_ratio=0.62, last_vol_mult=2.2, last_override=None):
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
    if last_override:
        rows[-1].update(last_override)
    return rows


def sine_rows(n=80, base=100.0, amp=2.5, period=14.0, vol=100.0, taker_ratio=0.55):
    """سوق عرضي — أساس Volume Profile واضح."""
    rows = []
    for i in range(n):
        p = base + amp * math.sin(i / period * 2 * math.pi)
        o = base + amp * math.sin((i - 0.5) / period * 2 * math.pi)
        h = max(o, p) + 0.3
        l = min(o, p) - 0.3
        rows.append({"ts": i * 300000.0, "open": o, "high": h, "low": l,
                     "close": p, "volume": vol, "taker_base": vol * taker_ratio})
    return rows


def make_ctx(k5, live=None, depth=None, k15=None, fib=None):
    rows = k5
    a5 = ind.atr([r["high"] for r in rows], [r["low"] for r in rows],
                 [r["close"] for r in rows], 14)
    if live is None:
        live = rows[-1]["close"]
    return ScalpContext(symbol="TEST/USDT", now_ts=1_000_000.0, k5=rows,
                        k15=k15 or [], live_price=live, depth=depth,
                        cvd_source="taker", atr5=a5, atr15=None,
                        fib_confluence=fib,
                        extra={"fee_rate": FEE})


# ─────────────────────────────────────────────────────────────────────────────
# 1) S1 — Flow Ignition
# ─────────────────────────────────────────────────────────────────────────────

def test_s1_enters_clean_breakout():
    rows = trend_rows(90)
    sig = FlowIgnition().evaluate(make_ctx(rows))
    assert sig is not None
    assert sig.strategy == "SCALP_FLOW" and sig.side == "LONG"
    close = rows[-1]["close"]
    a = sig.meta["atr5"]
    assert sig.sl < close < sig.tp1 < sig.tp2
    assert sig.rr1 >= 0.3
    assert sig.meta["cvd_source"] == "taker"
    assert sig.meta["entry_ref"] == pytest.approx(close)
    # الوقف داخل حدود السكالب المثبتة
    assert 0.55 * a <= (close - sig.sl) <= 1.4 * a
    assert sig.reason


def test_s1_rejects_downtrend():
    rows = list(reversed(trend_rows(90)))   # مرآة هابطة
    assert FlowIgnition().evaluate(make_ctx(rows)) is None


def test_s1_rejects_weak_volume():
    rows = trend_rows(90, last_vol_mult=1.0)   # آخر شمعة بحجم عادي
    assert FlowIgnition().evaluate(make_ctx(rows)) is None


def test_s1_rejects_chasing_gap():
    rows = trend_rows(90)
    live = rows[-1]["close"] * 1.03     # السعر انطلق بعيدًا عن إغلاق القرار
    assert FlowIgnition().evaluate(make_ctx(rows, live=live)) is None


def test_s1_rejects_extended_price():
    # امتداد حاد: نصف الأخيرة قفزة كبيرة تبعد الإغلاق عن EMA20
    rows = trend_rows(90, drift=0.02)
    for r in rows[-6:]:
        r["close"] += 12.0
        r["high"] = r["close"] + 0.5
        r["open"] = r["close"] - 0.02
        r["low"] = r["open"] - 0.5
    assert FlowIgnition().evaluate(make_ctx(rows)) is None


def test_s1_tp2_capped_at_liquidity_wall():
    rows = trend_rows(90)
    close = rows[-1]["close"]
    a = ind.atr([r["high"] for r in rows], [r["low"] for r in rows],
                [r["close"] for r in rows], 14)
    wall_px = close + 1.6 * a
    depth = {"asks": [[wall_px, 900.0], [close + 0.4 * a, 1.0], [close + 0.8 * a, 1.0],
                      [close + 1.2 * a, 1.0], [close + 1.4 * a, 1.0], [close + 1.8 * a, 1.0]],
             "bids": [[close - 0.5 * a, 10.0]]}
    sig = FlowIgnition().evaluate(make_ctx(rows, depth=depth))
    assert sig is not None
    # مركز صندوق الجدار مُكمَّم على عرض الصندوق (0.25×ATR) — لا مطابقة حرفية
    assert abs(sig.meta.get("wall") - wall_px) < 0.3 * a
    assert sig.tp2 <= wall_px                      # لا نستلم عند الجدار حرفيًا
    assert sig.tp2 > close + 1.2 * a


def test_s1_short_side_blocked_by_spot_guard():
    s = FlowIgnition()
    assert s._spot_guard("LONG") is True
    assert s._spot_guard("SHORT") is False         # سبوت: لا بيع مكشوف


# 3) الواجهة المشتركة
# ─────────────────────────────────────────────────────────────────────────────

def test_rr_net_matches_engine_formula():
    s = FlowIgnition()
    # نفس صيغة vnz.rr_net_value: reward − fee×(entry+tp) ثم ÷ risk
    assert s._rr_net(100.0, 98.0, 103.0, FEE) == pytest.approx(
        ((103.0 - 100.0) - FEE * (100.0 + 103.0)) / 2.0)
    assert s._rr_net(100.0, 101.0, 103.0, FEE) == 0.0   # وقف مقلوب = صفر


def test_base_meta_carries_cvd_source():
    ctx = make_ctx(trend_rows(90))
    m = FlowIgnition()._base_meta(ctx)
    assert m["cvd_source"] == "taker"
    assert m["exec_tf"] == "5m"


# ─────────────────────────────────────────────────────────────────────────────
# 2) S2 — Trend Pullback «ركوب التيار»
# ─────────────────────────────────────────────────────────────────────────────

def build_s2_setup():
    """ترند صاعد مؤكد (k15 مشتق من نفس الصعود + EMA50 صاعدة) ثم 3 شموع تصحيح
    تلمس القيمة (تحت EMA20 المحسوبة قبل التصحيح) وشمعة أخيرة استئناف صاعدة
    بدلتا موجبة. يعيد (rows, k15)."""
    rows = trend_rows(90, drift=0.03, wick=0.35, vol=100.0, taker_ratio=0.60,
                      last_vol_mult=1.0)
    # k15: كل شمعة ثالثة من أول 75 شمعة 5m — فريم النظام صاعد بالكامل
    k15 = [dict(r) for r in rows[:75:3]]
    a = ind.atr([r["high"] for r in rows], [r["low"] for r in rows],
                [r["close"] for r in rows], 14)
    e20 = ind.ema([r["close"] for r in rows], 20)[-1]
    # 3 شموع تصحيح تلمس القيمة (قيعان تحت EMA20 القديمة بهامش واضح)
    px = rows[-1]["close"]
    pull = []
    for j in range(3):
        o = px
        c = px - 0.45 * a
        pull.append({"ts": rows[-1]["ts"] + (j + 1) * 300000.0, "open": o,
                     "high": o + 0.12 * a, "low": c - 0.55 * a, "close": c,
                     "volume": 80.0, "taker_base": 48.0})
        px = c
    rows = rows[:-1] + pull
    # شمعة الاستئناف: صاعدة قوية تغلق فوق EMA20 بدلتا موجبة وحجم طبيعي
    o = px
    c = e20 + 0.35 * a
    resume = {"ts": rows[-1]["ts"] + 300000.0, "open": o,
              "high": c + 0.10 * a, "low": o - 0.08 * a, "close": c,
              "volume": 105.0, "taker_base": 65.1}
    rows.append(resume)
    return rows, k15


def test_s2_trend_enters_pullback_resume():
    rows, k15 = build_s2_setup()
    sig = TrendPullback().evaluate(make_ctx(rows, k15=k15))
    assert sig is not None
    assert sig.strategy == "SCALP_TREND" and sig.side == "LONG"
    close = rows[-1]["close"]
    a = sig.meta["atr5"]
    assert sig.sl < close < sig.tp1 < sig.tp2
    assert sig.rr1 >= 0.3
    # الوقف تحت قاع التصحيح بهامش — ومثبت داخل [0.6, 2.2]×ATR
    assert (close - sig.sl) >= 0.6 * a - 1e-9
    assert (close - sig.sl) <= 2.2 * a + 1e-9
    assert sig.meta["pull_low"] == pytest.approx(min(r["low"] for r in rows[-4:-1]))
    assert sig.meta["fail_level"] is not None          # EMA50 لمستوى الفشل
    assert sig.reason


def test_s2_trend_rejects_without_regime_frame():
    rows, _k15 = build_s2_setup()
    # بلا فريم النظام (k15 فارغة) لا صفقة — «النظام قبل الإشارة»
    assert TrendPullback().evaluate(make_ctx(rows, k15=[])) is None


def test_s2_trend_rejects_no_value_touch():
    rows, k15 = build_s2_setup()
    c = [r["close"] for r in rows]
    e20 = ind.ema(c, 20)[-1]
    vw = ind.vwap_rolling(rows[-72:])
    ref = max(e20, vw)
    a = ind.atr([r["high"] for r in rows], [r["low"] for r in rows],
                [r["close"] for r in rows], 14)
    # ارفع قيعان كل شموع النافذة فوق منطقة القيمة بهامش — لا تصحيح إطلاقًا
    for r in rows[-4:]:
        r["low"] = ref + 0.5 * a
        r["high"] = max(r["high"], r["low"] + 0.05 * a)
    assert TrendPullback().evaluate(make_ctx(rows, k15=k15)) is None


def test_s2_trend_rejects_extended_price():
    rows, k15 = build_s2_setup()
    a = ind.atr([r["high"] for r in rows], [r["low"] for r in rows],
                [r["close"] for r in rows], 14)
    # شمعة الاستئناف انطلقت بعيدًا عن EMA20 (مطاردة قمة — متأخرون)
    rows[-1]["close"] += 3.0 * a
    rows[-1]["high"] = rows[-1]["close"] + 0.1 * a
    assert TrendPullback().evaluate(make_ctx(rows, k15=k15)) is None


def test_s2_trend_rejects_too_deep_pullback():
    rows, k15 = build_s2_setup()
    a = ind.atr([r["high"] for r in rows], [r["low"] for r in rows],
                [r["close"] for r in rows], 14)
    # عمّق التصحيح إلى 3×ATR تحت الدخول — هندسة الوقف تفقد حد السكالب (1.6)
    for r in rows[-4:-1]:
        r["low"] -= 3.0 * a
    assert TrendPullback().evaluate(make_ctx(rows, k15=k15)) is None


def test_s2_trend_tp2_capped_at_wall():
    rows, k15 = build_s2_setup()
    close = rows[-1]["close"]
    a = ind.atr([r["high"] for r in rows], [r["low"] for r in rows],
                [r["close"] for r in rows], 14)
    wall_px = close + 2.4 * a
    depth = {"asks": [[wall_px, 900.0], [close + 0.4 * a, 1.0], [close + 0.8 * a, 1.0],
                      [close + 1.2 * a, 1.0], [close + 1.6 * a, 1.0], [close + 3.0 * a, 1.0]],
             "bids": [[close - 0.5 * a, 10.0]]}
    sig = TrendPullback().evaluate(make_ctx(rows, k15=k15, depth=depth))
    assert sig is not None
    assert abs(sig.meta.get("wall") - wall_px) < 0.3 * a
    assert sig.tp2 <= wall_px


def test_s2_trend_fib_confluence_raises_score():
    rows, k15 = build_s2_setup()
    base = TrendPullback().evaluate(make_ctx(rows, k15=k15))
    assert base is not None
    pull_low = base.meta["pull_low"]
    scored = TrendPullback().evaluate(
        make_ctx(rows, k15=k15, fib={"0.618": pull_low + 0.05, "0.786": pull_low - 1.0}))
    assert scored is not None
    assert scored.meta.get("fib_hit") == "0.618"
    assert scored.meta["score"] > base.meta["score"]


# ─────────────────────────────────────────────────────────────────────────────
# 3) S3 — Squeeze Breakout «انفجار الاختناق»
# ─────────────────────────────────────────────────────────────────────────────

def build_s3_setup(wick=0.2):
    """60 شمعة مختنقة (إغلاقات مسطحة — بولنجر الصفرية داخل كيلتنر بلا شك)
    ثم شمعة انفجار: كسر فوق بولنجر العلوي بجسم اندفاعي وحجم 1.8× ودلتا موجبة."""
    rows = []
    for i in range(59):
        rows.append({"ts": i * 300000.0, "open": 100.0, "high": 100.0 + wick,
                     "low": 100.0 - wick, "close": 100.0,
                     "volume": 100.0, "taker_base": 58.0})
    # شمعة الانفجار — +1.1×ATR تقريبًا (واقعية: كسر بجسمه لا قفزة مبالغًا فيها)
    rows.append({"ts": 59 * 300000.0, "open": 100.0, "high": 100.60,
                 "low": 99.95, "close": 100.45,
                 "volume": 180.0, "taker_base": 111.6})
    return rows


def test_s3_squeeze_enters_breakout():
    rows = build_s3_setup()
    sig = SqueezeBreakout().evaluate(make_ctx(rows))
    assert sig is not None
    assert sig.strategy == "SCALP_SQUEEZE" and sig.side == "LONG"
    close = rows[-1]["close"]
    a = sig.meta["atr5"]
    assert sig.sl < close < sig.tp1 < sig.tp2
    assert sig.rr1 >= 0.3
    # الاختناق موثّق والانفجار فوق بولنجر العلوي
    assert sig.meta["squeeze_bars"] >= 4
    assert close > sig.meta["bb_upper"]
    # الوقف تحت قاعدة الاختناق ومثبت داخل [0.6, 2.0]×ATR
    assert 0.6 * a - 1e-9 <= (close - sig.sl) <= 2.0 * a + 1e-9
    assert sig.meta["fail_level"] == pytest.approx(sig.meta["bb_mid"])
    assert sig.reason


def test_s3_squeeze_rejects_without_squeeze():
    """سوق واسع التقلب (مسير عشوائي بخطوات كبيرة وذيول صغيرة) — بولنجر أوسع
    من كيلتنر (σ خطوة السير تتضخم مقابل ATR الصغير) فلا اختناق 4/6 → رفض
    بوابة الاختناق مهما كان الاندلاع الأخير قويًا."""
    import random
    rng = random.Random(7)                     # بذرة مثبتة — نفس البيانات كل تشغيل
    rows = []
    px = 100.0
    for i in range(59):
        o = px
        c = px + rng.uniform(-1.5, 1.5)
        rows.append({"ts": i * 300000.0, "open": o, "high": max(o, c) + 0.12,
                     "low": min(o, c) - 0.12, "close": c,
                     "volume": 100.0, "taker_base": 58.0})
        px = c
    # شمعة اندفاعية مثالية في النهاية — الرفض يأتي من غياب الاختناق حصرًا
    rows.append({"ts": 59 * 300000.0, "open": px, "high": px + 4.2,
                 "low": px - 0.2, "close": px + 4.0,
                 "volume": 220.0, "taker_base": 136.4})
    h = [r["high"] for r in rows]; l = [r["low"] for r in rows]
    c = [r["close"] for r in rows]
    sq = 0
    for i in range(len(rows) - 6, len(rows)):
        bb = ind.bollinger(c[:i + 1], 20, 2.0)
        kc = ind.keltner(h[:i + 1], l[:i + 1], c[:i + 1], 20, 1.5)
        if bb and kc and bb["width"] < kc["width"]:
            sq += 1
    assert sq < 4, f"البيانات الصناعية يجب أن تكون غير مختنقة — وجد {sq}/6"
    assert SqueezeBreakout().evaluate(make_ctx(rows)) is None


def test_s3_squeeze_rejects_repeated_breakout():
    """كسر مستمر (الشمعة السابقة كانت خارج بولنجر العلوي أيضًا) — نطارد
    حركة بدأت من شموع → رفض «أول إغلاق كسر»."""
    rows = build_s3_setup()
    # حوّل الشمعة 58 (قبل الأخيرة) إلى كسر خارج بولنجر
    rows[-2] = {"ts": 58 * 300000.0, "open": 100.0, "high": 100.9,
                "low": 99.98, "close": 100.7, "volume": 170.0, "taker_base": 105.4}
    assert SqueezeBreakout().evaluate(make_ctx(rows)) is None


def test_s3_squeeze_rejects_weak_fuel():
    """اختناق صحيح وكسر بجسمه لكن بلا وقود: حجم الشمعة الأخيرة عادي."""
    rows = build_s3_setup()
    rows[-1]["volume"] = 100.0            # 1.0× المتوسط فقط — بلا انفجار حجم
    rows[-1]["taker_base"] = 62.0
    assert SqueezeBreakout().evaluate(make_ctx(rows)) is None


def test_s3_squeeze_rejects_bearish_direction():
    """كسر صاعد في سياق +DI ≤ −DI — شموع هابطة قبل الاختناق تقلب المؤشر."""
    rows = []
    # 40 شمعة هابطة (تضع −DI فوق +DI) ثم 19 مختنقة ثم شمعة انفجار
    px = 120.0
    for i in range(40):
        o = px
        c = px - 0.25
        rows.append({"ts": i * 300000.0, "open": o, "high": o + 0.1,
                     "low": c - 0.1, "close": c, "volume": 100.0, "taker_base": 42.0})
        px = c
    for i in range(19):
        rows.append({"ts": (40 + i) * 300000.0, "open": 110.0, "high": 110.15,
                     "low": 109.85, "close": 110.0, "volume": 100.0, "taker_base": 58.0})
    rows.append({"ts": 59 * 300000.0, "open": 110.0, "high": 111.0,
                 "low": 109.9, "close": 110.8, "volume": 180.0, "taker_base": 111.6})
    # قد يُرفض عند DI أو عند ST5 أو VWAP — المهم: لا إشارة
    assert SqueezeBreakout().evaluate(make_ctx(rows)) is None


def test_s3_squeeze_rejects_fake_wick_breakout():
    """اختراق بذيل لا بجسم — الرمشة فوق بولنجر بجسم ضئيل = فخ الاختراق."""
    rows = build_s3_setup()
    rows[-1] = {"ts": 59 * 300000.0, "open": 100.0, "high": 101.6,
                "low": 99.95, "close": 100.05, "volume": 180.0, "taker_base": 111.6}
    assert SqueezeBreakout().evaluate(make_ctx(rows)) is None
