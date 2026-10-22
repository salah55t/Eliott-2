# -*- coding: utf-8 -*-
"""الاستراتيجية S2 v2 — «ارتداد القيمة — Sweep & Reclaim» (Profile Reversion)
==========================================================================
إعادة بناء كاملة بعد تشخيص حي: 3 صفقات أولى كلها وقفت بوقف «دلتا/بنية» دون
بلوغ أي هدف (0/3) — الأسباب الجذرية الثلاثة:
  1) وقف 0.3×ATR تحت الرمشة = ضجيج 5m يلملس الوقف قبل أن يتحرك السعر نحو POC.
  2) شرط «آخر شمعة رمشة+إغلاق داخلي» يدخل أثناء السقوط لا بعد انتهائه.
  3) لا شرط استسلام (capitulation) — الرمشات الصغيرة ليست تصفية سيولة حقيقية.

التصميم الجديد يستغل المشاريع المرجعية بعمق:
  • OrderFlowMap — Liquidity Radar: لا ارتداد بلا سيولة مُبتلَعة. نطلب مسحًا
    صريحًا لقاع سيولة مرجعي (أدنى قاع 24 شمعة أو VAL أيهما أعلى) بعمق ≥ 0.15×ATR
    ثم استعادة (إغلاق فوق المستوى المسحوب) — «sweep-and-reclaim».
  • Flowsurface — CVD divergence: قاع سعري جديد بينما CVD لم يصنع قاعًا جديدًا
    (امتصاص) + دلتا شمعة الاستسلام عنيفة (حجم ≥ 1.25× متوسطها) = البائع
    الحقيقي استُنزف في ذيل الحركة لا في بدايتها.
  • flowmap/OrderFlowMap — أهداف مغناطيسية قابلة للبلوغ: TP1 = أقرب مغناطيس
    (POC أو VWAP أيهما أقرب) بدل تقييد الهدف على POC وحده، وTP2 = VAH أو
    امتداد POC — وأهداف أقصى 4×ATR (سكالب واقعي لا رحلة).
  • وقف هيكلي تكيفي: تحت القاع المسحوب بهامش 0.55×ATR مع تقييد مسافة الوقف
    [0.9×ATR, 2.6×ATR] — أوسع من الضجيج، أضيق من العبث (إن فسدت الهندسة
    تُرفض الصفقة لا تُلفَّق).

بوابات الدخول (كلها إلزامية بالترتيب):
  G1 بنية: منطقة قيمة معقولة (عرض VAH−VAL ≥ 1.2×ATR) من آخر 72 شمعة 5m.
  G2 درع الاتجاه v2: يُرفض إذا SuperTrend(5m) هابط وADX ≥ 24، أو
     SuperTrend(15m) هابط وADX(15m) ≥ 25، أو سكين ساقط (EMA50 هابطة
     والسعر تحتها وADX5 ≥ 20) — الترند القوي يأكل كل ارتداده.
  G3 مسح سيولة واستعادة: خلال آخر 3 شموع مغلقة نفذ قاعٌ للمسح تحت مستوى
     السيولة المرجعي بعمق ≥ 0.15×ATR، والإغلاق الحالي عاد فوق المستوى
     المسحوب (استعادة حقيقية) — القاع المسحوب q هو أدنى قاع في النافذة.
  G4 استسلام + امتصاص: حجم شمعة المسح ≥ 1.25× متوسط حجم 20 شمعة قبلها
     (ذُبح السيولة)، وCVD الحالي أعلى من CVD عند القاع المرجعي السابق
     (p) رغم القاع الجديد — بائعون يستنزفون بلا مقابل.
  G5 قوة الاستعادة: الإغلاق الحالي فوق منتصف مدى شمعة المسح — ليست رمشة
     صامتة بل إعادة تملّك فعلية.
  G6 هندسة المخاطرة: SL تحت القاع المسحوب 0.55×ATR مع تقييد المسافة
     [0.9, 2.6]×ATR، TP1 = أقرب مغناطيس ≥ close+0.45×ATR (POC أو VWAP)،
     TP2 = VAH أو امتداد POC بسقف 4×ATR، R:R صافي ≥ أرضية المحرك.

إدارة الموضع (المدير): جزئي 50% عند TP1 + ترقية الوقف إلى ما بعد التعادل
  (lock-in) + خروج بنيوي على إغلاق مغلق تحت القاع المسحوب (فشل الاستعادة)
  + مهلة ارتداد 45د (الارتداد إما يعمل سريعًا أو فرضيته ماتت).
سبوت فقط: LONG حصرًا — حارس صريح في المدير يمنع غيره.
"""

from typing import Optional

from .base import ScalpContext, ScalpSignal, ScalpStrategyBase
from . import indicators as ind

VP_LOOKBACK = 72           # نافذة البروفايل (6 ساعات من 5m)
VP_BINS = 48               # صناديق السعر
VA_MIN_ATR = 1.2           # أضيق منطقة قيمة معتبرة
SWEEP_WINDOW = 3           # نافذة البحث عن شمعة المسح (آخر 3 شموع مغلقة)
SWEEP_MIN_ATR = 0.15       # أعمق عمق مسح تحت مستوى السيولة يُعتبر مسحًا
LIQ_WINDOW = 24            # نافذة قاع السيولة المرجعي (4 ساعات)
CLIMAX_VOL = 1.25          # حجم شمعة المسح ≥ 1.25× متوسط 20 شمعة قبلها (استسلام)
SL_BUF_ATR = 0.55          # هامش الوقف تحت القاع المسحوب (كان 0.3 — ضجيج)
SL_MIN_ATR = 0.9           # أضيق وقف مسموح (تحت الضجيج)
SL_MAX_ATR = 2.6           # أوسع وقف مسموح (فوقه هندسة فاسدة → رفض)
MIN_MEAT_ATR = 0.45        # أقل مسافة للهدف الأول
TP2_MIN_GAP_ATR = 0.35     # TP2 يجب أن يبتعد عن TP1 بهذا القدر
TP2_MAX_ATR = 4.0          # سقف الهدف الثاني عن الدخول (سكالب واقعي)
FAIL_LVL = "sweep"         # انهيار البنية = إغلاق مغلق تحت القاع المسحوب
REVERSION_HOLD_MIN = 45    # مهلة الارتداد — إما يعمل سريعًا أو ماتت الفرضية
FIB_TOL_ATR = 0.25         # سماحية تقارب مستوى السيولة مع فيبو (درجة جودة)
ADX_STRONG = 24.0          # عتبة «ترند قوي» على 5m (كانت 28 — مشددة)
ADX_STRONG15 = 25.0        # عتبة «ترند قوي» على 15m (كانت 30 — مشددة)
KNIFE_ADX = 20.0           # سكين ساقط: EMA50 هابطة + السعر تحتها + ADX هذا
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
        n = len(rows)

        # G2 درع الاتجاه v2 — لا صيد سكاكين في ترند قوي
        st5 = ind.supertrend(highs, lows, closes, ST5[0], ST5[1])
        adx5 = ind.adx(highs, lows, closes, 14)
        if st5 and st5["dir"] == -1.0 and adx5 is not None and adx5 >= ADX_STRONG:
            return None
        if len(ctx.k15 or []) >= 25:
            h15 = [float(r["high"]) for r in ctx.k15]
            l15 = [float(r["low"]) for r in ctx.k15]
            c15 = [float(r["close"]) for r in ctx.k15]
            st15 = ind.supertrend(h15, l15, c15, ST15[0], ST15[1])
            adx15 = ind.adx(h15, l15, c15, 14)
            if st15 and st15["dir"] == -1.0 and adx15 is not None and adx15 >= ADX_STRONG15:
                return None
        # سكين ساقط: EMA50 هابطة والسعر تحتها بقوة اتجاه مؤكدة
        e50 = ind.ema(closes, 50)
        if e50[-1] == e50[-1] and e50[-7] == e50[-7] and adx5 is not None:
            if closes[-1] < e50[-1] and e50[-1] < e50[-7] and adx5 >= KNIFE_ADX:
                return None

        # G3 مسح سيولة واستعادة — Liquidity Radar (من OrderFlowMap)
        w0 = max(0, n - SWEEP_WINDOW)                 # بداية نافذة المسح
        s = w0 + min(range(len(rows) - w0), key=lambda i: lows[w0 + i])  # شمعة المسح
        sweep_low = lows[s]
        # مستوى السيولة المرجعي: أعلى (قاع 24 شمعة قبل نافذة المسح، VAL)
        pre = lows[max(0, w0 - LIQ_WINDOW):w0]
        prior_low = min(pre) if pre else sweep_low
        liq_ref = max(prior_low, vp["val"])
        pierce = liq_ref - sweep_low
        if pierce < SWEEP_MIN_ATR * a:
            return None                               # لا مسح حقيقي للسيولة
        if close <= liq_ref:
            return None                               # لا استعادة — ما زلنا تحت السيولة

        # G4 استسلام + امتصاص — CVD divergence (من Flowsurface)
        cv = ind.cvd_series(rows)
        if not cv:
            return None
        cvd = cv["cvd"]
        vols = [float(r["volume"]) for r in rows]
        pre_vols = vols[max(0, s - 20):s]
        vol_mean = (sum(pre_vols) / len(pre_vols)) if pre_vols else 0.0
        if vol_mean <= 0 or vols[s] < CLIMAX_VOL * vol_mean:
            return None                               # رمشة بلا ذبح سيولة — لا استسلام
        # القاع المرجعي السابق p: أدنى قاع في آخر LIQ_WINDOW شمعة قبل نافذة المسح
        if not pre:
            return None
        p = max(0, w0 - LIQ_WINDOW) + min(range(len(pre)), key=lambda i: pre[i])
        if not (sweep_low <= lows[p] and cvd[-1] > cvd[p]):
            return None                               # لا امتصاص — الدلتا تبيع مع السعر

        # G5 قوة الاستعادة — الإغلاق فوق منتصف شمعة المسح
        sweep_mid = (highs[s] + lows[s]) / 2.0
        if close <= sweep_mid:
            return None

        # G6 هندسة المخاطرة v2 — وقف هيكلي تقييد والأهداف مغناطيسية قريبة
        sl = sweep_low - SL_BUF_ATR * a
        sl_dist = close - sl
        if sl_dist < SL_MIN_ATR * a:
            sl = close - SL_MIN_ATR * a               # أوسع من الضجيج (لا رفض — تثبيت)
            sl_dist = close - sl
        if sl_dist > SL_MAX_ATR * a:
            return None                               # هندسة فاسدة — لا صفقة
        # الأهداف: أقرب مغناطيس فوق الدخول — POC أو VWAP (المغناطيس الأقرب أوفى بلوغًا)
        vwap = ind.vwap_rolling(rows[-VP_LOOKBACK:])
        mags = []
        if close < vp["poc"] and (vp["poc"] - close) >= MIN_MEAT_ATR * a:
            mags.append((vp["poc"], "poc"))
        if vwap and close < vwap and (vwap - close) >= MIN_MEAT_ATR * a:
            mags.append((vwap, "vwap"))
        if not mags:
            return None                               # لا هدف قابل للبلوغ
        tp1, basis = min(mags, key=lambda m: m[0])
        tp2 = vp["vah"] if (vp["vah"] - tp1) >= TP2_MIN_GAP_ATR * a else tp1 + 0.7 * a
        if (tp2 - close) > TP2_MAX_ATR * a:
            tp2 = close + TP2_MAX_ATR * a
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
                if lv and abs(lv - liq_ref) <= FIB_TOL_ATR * a:
                    score += 0.5
                    fib_hit = key
                    break
        wall_used = None
        if ctx.depth:
            bucket = max(0.25 * a, close * 1e-5)
            walls = ind.detect_walls(ctx.depth.get("bids") or [], bucket)
            wall = ind.nearest_wall(walls, above=False, ref_price=liq_ref)
            if wall and (liq_ref - wall[0]) <= 0.6 * a:
                score += 0.5
                wall_used = wall[0]
        if vols[s] >= 1.6 * vol_mean:
            score += 0.25                             # استسلام عنيف = سيولة أعمق ابتُلعت

        meta = self._base_meta(ctx)
        meta.update({
            "entry_ref": close, "atr5": a, "tp1": tp1, "tp2": tp2,
            "poc": vp["poc"], "vah": vp["vah"], "val": vp["val"], "vwap": vwap,
            "liq_ref": liq_ref, "sweep_low": sweep_low,
            "sweep_vol_ratio": round(vols[s] / vol_mean, 2) if vol_mean > 0 else None,
            "pierce_atr": round(pierce / a, 2),
            "score": round(score, 2), "fib_hit": fib_hit, "wall": wall_used,
            "cvd_source": cv["source"], "rr1": round(rr1, 2),
            "tp1_basis": basis, "reversion": 1,
            "max_hold_override": REVERSION_HOLD_MIN,
            "fail_level": sweep_low,                  # إغلاق تحت القاع المسحوب = فشل الاستعادة
        })
        q = f" + تقارب فيبو {fib_hit}" if fib_hit else ""
        w = f" + جدار شراء {wall_used:.6g}" if wall_used else ""
        reason = (f"مسح سيولة تحت {liq_ref:.6g} (عمق {pierce / a:.2f}×ATR، حجم "
                  f"{vols[s] / vol_mean:.1f}× المتوسط) مع استعادة فوق المستوى وامتصاص CVD"
                  f"{q}{w} — الهدف {basis} {tp1:.6g}")
        return ScalpSignal(strategy=self.name, label=self.label, symbol=ctx.symbol,
                           entry_ref=close, sl=sl, tp1=tp1, tp2=tp2, rr1=rr1,
                           reason=reason, meta=meta)

    def _fee_rate(self, ctx: ScalpContext) -> float:
        return float((ctx.extra or {}).get("fee_rate", 0.001))
