# -*- coding: utf-8 -*-
"""الاستراتيجية S2 — «ارتداد القيمة» (Profile Reversion)
=======================================================
سكالب ارتدادي على 5m: السعر يخترق حافة منطقة القيمة (VAL) برمشة سيولة ثم
يعود ويغلق داخلها مع دليل امتصاص من الدلتا — ندخل مع العودة نحو POC.

فكرة القرار (Volume Profile من مفاهيم flowmap/OrderFlowMap — كود أصلي):
  امتدادات خارج منطقة القيمة تجذب رمشات سيولة تُبتلع فورًا حين لا يوجد
  بائع حقيقي خلفها — الدليل: قاع جديد سعريًا بينما CVD لم يصنع قاعًا جديدًا
  (امتصاص)، وقرب منطقة الدخول من مفاتيح فيبو المحرك (0.618/0.786) يرفع
  الجودة دون أن يكون شرطًا (تقارب يرفع الدرجة فقط).

بوابات الدخول (كلها إلزامية بالترتيب):
  G1 بنية: منطقة قيمة معقولة (عرض VAH−VAL ≥ 1.2×ATR) من آخر 72 شمعة 5m.
  G2 درع الاتجاه: لا انتحال ضد ترند قوي — يُرفض إذا SuperTrend(5m) هابط
     وADX ≥ 28، أو SuperTrend(15m) هابط وADX(15m) ≥ 30.
  G3 رمشة واقعة على آخر شمعة مغلقة: low < VAL وإغلاق داخل القيمة
     (close > VAL) ورمشة ≥ 0.30×ATR، والإغلاق ما زال تحت POC
     (له مسار نحو الهدف — إن كان فوق POC فالمهمة انتهت أصلًا).
  G4 امتصاص الدلتا: قاع الشمعة هو الأدنى في آخر 12 شمعة بينما CVD الحالي
     أعلى من CVD عند ذلك القاع السابق (بائعون يستنزفون بلا انخفاض).
  G5 هندسة المخاطرة: SL تحت الرمشة (0.3×ATR)، TP1 = POC، TP2 = VAH،
     ولحم كافٍ: tp1 ≥ close + 0.45×ATR وR:R صافي ≥ أرضية المحرك.

إدارة الموضع (المدير): جزئي 50% عند TP1 + BE، الباقي عند TP2 أو انهيار
البنية (إغلاق تحت VAL − 0.6×ATR) أو المهلة.
"""

from typing import Optional

from .base import ScalpContext, ScalpSignal, ScalpStrategyBase
from . import indicators as ind

VP_LOOKBACK = 72           # نافذة البروفايل (6 ساعات من 5m)
VP_BINS = 48               # صناديق السعر
VA_MIN_ATR = 1.2           # أضيق منطقة قيمة معتبرة
WICK_MIN_ATR = 0.30        # أدنى رمشة تحت VAL تُعتبر رمشة سيولة
SWEEP_WINDOW = 12          # نافذة قاع الامتصاص
SL_BUF_ATR = 0.3           # هامش الوقف تحت الرمشة
MIN_MEAT_ATR = 0.45        # أقل مسافة للهدف الأول
ST_FAIL_ATR = 0.6          # انهيار البنية: إغلاق تحت VAL بهذه المسافة (يديره المدير)
FIB_TOL_ATR = 0.25         # سماحية تقارب VAL مع فيبو (درجة جودة لا شرط)
ADX_STRONG = 28.0          # عتبة «ترند قوي» على 5m
ADX_STRONG15 = 30.0        # عتبة «ترند قوي» على 15m
ST5 = (10, 2.5)
ST15 = (10, 3.0)


class ProfileReversion(ScalpStrategyBase):
    name = "SCALP_PROFILE"
    label = "◈ ارتداد القيمة"

    def evaluate(self, ctx: ScalpContext) -> Optional[ScalpSignal]:
        rows = ctx.k5 or []
        if len(rows) < 60:
            return None
        a = ctx.atr5
        if not a or a <= 0:
            return None
        if ctx.live_price is None:
            return None
        close = float(rows[-1]["close"])
        if abs(ctx.live_price - close) > self.cfg.entry_chase_atr * a:
            return None

        # G1 بنية منطقة القيمة
        vp = ind.volume_profile(rows, bins=VP_BINS, lookback=VP_LOOKBACK)
        if not vp:
            return None
        if (vp["vah"] - vp["val"]) < VA_MIN_ATR * a:
            return None

        highs = [float(r["high"]) for r in rows]
        lows = [float(r["low"]) for r in rows]
        closes = [float(r["close"]) for r in rows]

        # G2 درع الاتجاه — لا صيد سكاكين في ترند قوي
        st5 = ind.supertrend(highs, lows, closes, ST5[0], ST5[1])
        adx5 = ind.adx(highs, lows, closes, 14)
        if st5 and st5["dir"] == -1.0 and adx5 is not None and adx5 >= ADX_STRONG:
            return None
        st15 = adx15 = None
        if len(ctx.k15 or []) >= 25:
            h15 = [float(r["high"]) for r in ctx.k15]
            l15 = [float(r["low"]) for r in ctx.k15]
            c15 = [float(r["close"]) for r in ctx.k15]
            st15 = ind.supertrend(h15, l15, c15, ST15[0], ST15[1])
            adx15 = ind.adx(h15, l15, c15, 14)
        if st15 and st15["dir"] == -1.0 and adx15 is not None and adx15 >= ADX_STRONG15:
            return None

        # G3 رمشة السيولة على آخر شمعة مغلقة
        last = rows[-1]
        val = vp["val"]
        if not (float(last["low"]) < val and close > val):
            return None
        wick_below = val - float(last["low"])
        if wick_below < WICK_MIN_ATR * a:
            return None
        if close >= vp["poc"]:
            return None                          # الهدف نفسه تحقق — لا صفقة

        # G4 امتصاص الدلتا — قاع سعري جديد الآن بلا قاع دلتا جديد مقابلًا:
        # نقارن CVD الحالي بـ CVD عند أدنى قاع سابق (باستثناء شمعة الرمشة نفسها)
        cv = ind.cvd_series(rows)
        if not cv:
            return None
        cvd = cv["cvd"]
        if len(cvd) < SWEEP_WINDOW + 2:
            return None
        window = range(max(0, len(rows) - 1 - SWEEP_WINDOW), len(rows) - 1)
        j = min(window, key=lambda i: lows[i])
        if not (lows[-1] <= lows[j] and cvd[-1] > cvd[j]):
            return None                          # لا امتصاص — الدلتا تبيع مع السعر

        # الوقف والأهداف
        sl = float(last["low"]) - SL_BUF_ATR * a
        tp1 = vp["poc"]
        tp2 = vp["vah"]
        if tp1 - close < MIN_MEAT_ATR * a:
            return None
        if not (sl < close < tp1 < tp2):
            return None

        rr1 = self._rr_net(close, sl, tp1, self._fee_rate(ctx))
        if rr1 < self.cfg.rr_net_min:
            return None

        # درجات الجودة (تقارب فيبو + جدار شراء تحتنا) — ترفع score ولا تمنع
        score = 1.0
        fib_hit = None
        if ctx.fib_confluence:
            for key in ("0.618", "0.786"):
                lv = ctx.fib_confluence.get(key)
                if lv and abs(lv - val) <= FIB_TOL_ATR * a:
                    score += 0.5
                    fib_hit = key
                    break
        wall_used = None
        if ctx.depth:
            bucket = max(0.25 * a, close * 1e-5)
            walls = ind.detect_walls(ctx.depth.get("bids") or [], bucket)
            wall = ind.nearest_wall(walls, above=False, ref_price=val)
            if wall and (val - wall[0]) <= 0.6 * a:
                score += 0.5
                wall_used = wall[0]

        meta = self._base_meta(ctx)
        meta.update({
            "entry_ref": close, "atr5": a, "tp1": tp1, "tp2": tp2,
            "poc": vp["poc"], "vah": vp["vah"], "val": val,
            "wick_below": round(wick_below, 8), "score": round(score, 2),
            "fib_hit": fib_hit, "wall": wall_used,
            "cvd_source": cv["source"], "rr1": round(rr1, 2),
            "fail_level": val - ST_FAIL_ATR * a,
        })
        q = f" + تقارب فيبو {fib_hit}" if fib_hit else ""
        w = f" + جدار شراء {wall_used:.6g}" if wall_used else ""
        reason = (f"رمشة سيولة تحت VAL ({vp['val']:.6g}) بإغلاق داخل القيمة مع امتصاص CVD"
                  f"{q}{w} — الهدف POC {vp['poc']:.6g} ثم VAH")
        return ScalpSignal(strategy=self.name, label=self.label, symbol=ctx.symbol,
                           entry_ref=close, sl=sl, tp1=tp1, tp2=tp2, rr1=rr1,
                           reason=reason, meta=meta)

    def _fee_rate(self, ctx: ScalpContext) -> float:
        return float((ctx.extra or {}).get("fee_rate", 0.001))
