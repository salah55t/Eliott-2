#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات EL2.1.0 — منطق استراتيجيتي السكالب على بيانات صناعية
================================================================
  1) S1 Flow-Ignition: دخول زخم صحيح + أهداف مركبة على جدار + رفض الترند الهابط
     + رفض الحجم الضعيف + رفض الامتداد الزائد + هندسة وقف مثبتة داخل الحدود
  2) S2 Profile-Reversion v2 «Sweep & Reclaim»: مسح سيولة + استعادة + استسلام
     + امتصاص CVD → دخول نحو أقرب مغناطيس (POC/VWAP) + رفض بلا استسلام
     + رفض بلا مسح + رفض الترند القوي + تثبيت الوقف الأدنى 0.9×ATR
  3) الواجهة المشتركة: حارس سبوت (لا بيع مكشوف) + R:R صافي بنفس صيغة المحرك
"""

import math

import pytest

from strategies.base import ScalpConfig, ScalpContext
from strategies.flow_ignition import FlowIgnition
from strategies.profile_reversion import ProfileReversion
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


# ─────────────────────────────────────────────────────────────────────────────
# 2) S2 — Profile Reversion v2 «Sweep & Reclaim»
# ─────────────────────────────────────────────────────────────────────────────

def build_s2_setup():
    """سوق عرضي يبني منطقة قيمة ثم شمعة أخيرة تمسح قاع السيولة (أدنى قاع 24 شمعة
    قبل نافذة المسح) بعمق حقيقي وحجم استسلام 1.6× المتوسط، وتُغلق فوق المستوى
    المسحوب بامتصاص CVD (دلتا موجبة قوية). البروفايل يُحسب على الصفوف النهائية."""
    rows = sine_rows(80, base=100.0, amp=2.5, period=14.0)
    a = ind.atr([r["high"] for r in rows], [r["low"] for r in rows],
                [r["close"] for r in rows], 14)
    val0 = ind.volume_profile(rows)["val"]
    # القاع المرجعي: أدنى قاع في 24 شمعة قبل نافذة المسح (آخر 3 شموع)
    prev_min = min(r["low"] for r in rows[-27:-3])
    sweep_low = prev_min - 0.35 * a
    sweep_close = val0 + 0.15 * a
    last = dict(rows[-1])
    last.update({"open": sweep_close + 0.2 * a, "high": sweep_close + 0.4 * a,
                 "low": sweep_low, "close": sweep_close,
                 "volume": 160.0, "taker_base": 147.2})   # استسلام 1.6× + دلتا موجبة
    rows = rows[:-1] + [last]
    vp = ind.volume_profile(rows)                        # البروفايل كما يراه evaluate
    return rows, a, vp


def expected_tp1(rows, a, vp):
    """المغناطيس الأقرب المؤهل — نفس منطق v2 (POC أو VWAP أيهما أقرب)."""
    close = rows[-1]["close"]
    vwap = ind.vwap_rolling(rows[-72:])
    mags = []
    if close < vp["poc"] and (vp["poc"] - close) >= 0.45 * a:
        mags.append(vp["poc"])
    if vwap and close < vwap and (vwap - close) >= 0.45 * a:
        mags.append(vwap)
    return min(mags) if mags else None


def test_s2_enters_sweep_reclaim_with_absorption():
    rows, a, vp = build_s2_setup()
    sig = ProfileReversion().evaluate(make_ctx(rows))
    assert sig is not None
    assert sig.strategy == "SCALP_PROFILE" and sig.side == "LONG"
    close = rows[-1]["close"]
    assert sig.sl < close < sig.tp1 < sig.tp2
    exp = expected_tp1(rows, a, vp)
    assert exp is not None and sig.tp1 == pytest.approx(exp)   # أقرب مغناطيس (POC/VWAP)
    assert sig.rr1 >= 0.3
    assert sig.meta["tp1_basis"] in ("poc", "vwap")
    assert sig.meta["fail_level"] == pytest.approx(rows[-1]["low"])  # فشل الاستعادة = إغلاق تحت القاع المسحوب
    assert sig.meta["sweep_vol_ratio"] >= 1.25
    assert sig.meta["reversion"] == 1
    assert sig.meta["max_hold_override"] == 45
    # مسافة الوقف داخل القيد الهيكلي [0.9, 2.6]×ATR
    assert 0.9 * a <= (close - sig.sl) <= 2.6 * a + 1e-9


def test_s2_rejects_close_above_poc():
    rows, a, vp = build_s2_setup()
    # أغلق الاستعادة فوق كل المغانط (POC وVWAP) — لا هدف قابل للبلوغ (المهمة انتهت أصلًا)
    vwap = ind.vwap_rolling(rows[-72:])
    rows[-1]["close"] = max(vp["poc"], vwap) + 0.6 * a
    rows[-1]["high"] = max(rows[-1]["high"], rows[-1]["close"])
    assert ProfileReversion().evaluate(make_ctx(rows)) is None


def test_s2_rejects_no_absorption_delta_selling():
    rows, a, vp = build_s2_setup()
    # تدفق محايد في نافذة الامتصاص (دلتا صفر) ثم بيع عنيف في شمعة المسح —
    # CVD ينخفض تحت مستوى القاع المرجعي → لا امتصاص → رفض
    for r in rows[-14:-1]:
        r["taker_base"] = r["volume"] * 0.5
    rows[-1]["taker_base"] = 0.0
    assert ProfileReversion().evaluate(make_ctx(rows)) is None


def test_s2_rejects_no_capitulation():
    rows, a, vp = build_s2_setup()
    rows[-1]["volume"] = 100.0              # حجم عادي — رمشة بلا ذبح سيولة
    rows[-1]["taker_base"] = 92.0
    assert ProfileReversion().evaluate(make_ctx(rows)) is None


def test_s2_rejects_shallow_sweep():
    """ممسح ضحل تحت قاع سوق مرتفع عن القيمة (SWING فوق VAL) بعمق أقل من
    0.15×ATR — ليس ذبح سيولة حقيقيًا → رفض."""
    rows = []
    for i in range(12):   # ذيل قديم منخفض يوسع البروفايل نزولًا
        rows.append({"ts": i * 300000.0, "open": 98.5, "high": 98.7, "low": 97.5,
                     "close": 98.0, "volume": 100.0, "taker_base": 55.0})
    for i in range(48):   # جسم متوسط واسع
        rows.append({"ts": (12 + i) * 300000.0, "open": 100.2, "high": 101.5, "low": 99.5,
                     "close": 100.8, "volume": 100.0, "taker_base": 55.0})
    for i in range(18):   # هضبة حديثة مرتفعة — قيعان الـ24 الأخيرة أعلى من VAL
        rows.append({"ts": (60 + i) * 300000.0, "open": 101.9, "high": 102.1, "low": 101.8,
                     "close": 102.0, "volume": 100.0, "taker_base": 55.0})
    a = ind.atr([r["high"] for r in rows], [r["low"] for r in rows],
                [r["close"] for r in rows], 14)
    vp0 = ind.volume_profile(rows)
    prior_low = min(float(r["low"]) for r in rows[-27:-3])   # قاع الهضبة
    liq0 = max(prior_low, vp0["val"])
    # شمعة مسح ضحلة: تخترق القاع المرجعي بـ 0.08×ATR فقط وتغلق فوقه
    last = {"ts": 78 * 300000.0, "open": liq0 + 0.02 * a, "high": liq0 + 0.12 * a,
            "low": liq0 - 0.08 * a, "close": liq0 + 0.06 * a,
            "volume": 160.0, "taker_base": 147.2}
    rows.append(last)
    assert ProfileReversion().evaluate(make_ctx(rows)) is None


def test_s2_rejects_strong_downtrend():
    # ترند هابط قوي على 5m — درع الاتجاه يمنع صيد السكاكين
    rows = list(reversed(trend_rows(90, drift=0.06, taker_ratio=0.35)))
    assert ProfileReversion().evaluate(make_ctx(rows)) is None


def test_s2_stop_clamped_to_min_atr(monkeypatch):
    """تثبيت الوقف الأدنى: وقف خام أضيق من الحد يُرفع إلى الحد لا يُرفض —
    نعزل الهندسة برقعة SL_MIN_ATR أعلى من الخام (2.5×ATR) على الإعداد السليم
    مع تعطيل أرضية R:R مؤقتًا (الاختبار للهندسة لا للبوابات الأخرى)."""
    from strategies import profile_reversion as prmod
    from strategies.base import ScalpConfig
    monkeypatch.setattr(prmod, "SL_MIN_ATR", 2.5)
    rows, _a, vp = build_s2_setup()
    a = ind.atr([r["high"] for r in rows], [r["low"] for r in rows],
                [r["close"] for r in rows], 14)   # نفس ATR الذي تراه الاستراتيجية
    cfg = ScalpConfig()
    cfg.rr_net_min = 0.0                     # عزل: هذا اختبار هندسة الوقف فقط
    sig = ProfileReversion(cfg).evaluate(make_ctx(rows))
    assert sig is not None
    close = rows[-1]["close"]
    raw_dist = close - (rows[-1]["low"] - 0.55 * a)
    assert raw_dist < 2.5 * a                # الوقف الخام أضيق من الحد — لولا التثبيت
    assert sig.sl == pytest.approx(close - 2.5 * a)   # ثبت عند الحد الأدنى
    assert sig.sl < close < sig.tp1          # البنية ما زالت سليمة


def test_s2_fib_confluence_raises_score():
    rows, a, vp = build_s2_setup()
    base = ProfileReversion().evaluate(make_ctx(rows))
    assert base is not None
    scored = ProfileReversion().evaluate(
        make_ctx(rows, fib={"0.618": vp["val"] + 0.05 * a, "0.786": vp["val"] - 1.0}))
    assert scored is not None
    assert scored.meta.get("fib_hit") == "0.618"
    assert scored.meta["score"] > base.meta["score"]


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
