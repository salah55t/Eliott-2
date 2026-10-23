#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات EL2.3.0 — منطق استراتيجية السكالب المتبقية على بيانات صناعية
================================================================
  1) S1 Flow-Ignition: دخول زخم صحيح + أهداف مركبة على جدار + رفض الترند الهابط
     + رفض الحجم الضعيف + رفض الامتداد الزائد + هندسة وقف مثبتة داخل الحدود
  2) الواجهة المشتركة: حارس سبوت (لا بيع مكشوف) + R:R صافي بنفس صيغة المحرك
ملاحظة: اختبارات SCALP_PROFILE أُزيلت معها في EL2.2.0 (قرار الحاكم)، واختبارات
SCALP_TREND/SCALP_SQUEEZE أُزيلت مع استراتيجيتيهما في EL2.3.0 (قرار الحاكم:
«احذف جميع الاستراتيجيات ماعدا موجات اليوت والتدفق»). اختبارات فلتر التدفق في
test_el23_flow_filter.py.
"""

import math

import pytest

from strategies.base import ScalpConfig, ScalpContext
from strategies.flow_ignition import FlowIgnition
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
# 3) تنظيف EL2.3.0 — الاستراتيجيات المزالة غائبة عن الحزمة كليًا
# ─────────────────────────────────────────────────────────────────────────────

def test_removed_strategies_are_gone():
    """قرار الحاكم EL2.3.0: SCALP_TREND وSCALP_SQUEEZE غير موجودتين — لا موديول
    ولا مثيل ولا اسم في حاملة الاستراتيجيات، وأسماؤهما في قائمة المزالة."""
    import strategies.manager as sm
    assert sm.STRATEGY_NAMES == ("SCALP_FLOW",)
    assert set(sm.LEGACY_STRATEGIES) == {"SCALP_PROFILE", "SCALP_TREND", "SCALP_SQUEEZE"}
    try:
        import strategies.trend_pullback  # noqa: F401
        raise AssertionError("strategies.trend_pullback يجب أن تكون محذوفة")
    except ModuleNotFoundError:
        pass
    try:
        import strategies.squeeze_breakout  # noqa: F401
        raise AssertionError("strategies.squeeze_breakout يجب أن تكون محذوفة")
    except ModuleNotFoundError:
        pass


