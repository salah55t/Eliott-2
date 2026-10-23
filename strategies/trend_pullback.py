# -*- coding: utf-8 -*-
"""الاستراتيجية S2 — «ركوب التيار» (Trend Pullback) — EL2.2.0
=============================================================
سكالب التقاط تصحيح داخل ترند قائم — الحافة الثالثة المكمّلة:
  • SCALP_FLOW تشتري الاندلاع (CVD عند قمة النافذة + حجم 1.3×) — تدخل متأخرة
    من زاوية التوسع، وتفوت تيار الترند الهادئ الذي لا يصنع انفجارات.
  • SCALP_TREND تشتري الغلس: ترند مؤكد على الفريم الأعلى + تصحيح صحي إلى
    منطقة القيمة + أول شمعة استئناف مؤكدة — تدخل حيث ينتهي التصحيح لا حيث
    ينتهي الاندفاع.

الإسناد المفاهيمي (كود أصلي — إعادة كتابة):
  • flowsurface (Apache-2.0) — فلسفة «النظام قبل الإشارة»: SuperTrend الفريم
    الأعلى هو النظام، والفريم الأدنى هو التوقيت. هنا: SuperTrend(15m,10,3.0)
    صاعد + EMA50(5m) صاعدة = تيار قائم (لا انقلاب طازج يقلب).
  • freqtrade (GPL-3.0) — انضباط «الدخول بعد تأكيد الشمعة لا خلال التراجع»:
    نمنع دخول أثناء السقوط (شمعة الاستئناف إلزامية صاعدة تغلق فوق EMA20) —
    الدرس نفسه الذي كلف SCALP_PROFILE صفقاته الأولى (دخول أثناء السقوط).
  • OrderFlowMap — POC كأرضية موقع: لا شراء تحت مغناطيس القيمة (السعر تحت
    POC يعني أن أقرب جذب لأسفل)، وفيبو المحرك 0.618/0.786 يرفع الدرجة.

بوابات الدخول (كلها إلزامية بالترتيب):
  G1 بيانات: ≥60 شمعة 5m مغلقة + سعر حي ضمن 0.4×ATR من الإغلاق (لا ملاحقة).
  G2 نظام قائم: SuperTrend(15m) صاعد + السعر فوق EMA50(5m) + EMA50 صاعدة
     منذ 7 شموع (slope موجب) — ترند مؤكد لا هبّة.
  G3 تصحيح صحي: خلال 4 الشموع السابقة لشمعة الاستئناف لامست EMA20(5m) أو
     VWAP (لمسة القيمة) — التصحيح جاء إلى المنطقة لا توقّع.
  G4 استئناف مؤكد: آخر شمعة مغلقة صاعدة (close>open، جسم ≥40% من مداها)
     وتغلق فوق EMA20، ودلتا شمعتها موجبة (عودة الشراء) وCVD فوق EMA12 له.
  G5 موقع سليم: الإغلاق فوق VWAP وفوق POC (فوق مغناطيس القيمة) وغير ممدد
     (ضمن 1.2×ATR من EMA20) — نصور من أول التصحيح لا من قمته.
  G6 هندسة المخاطرة: وقف تحت قاع التصحيح بهامش 0.25×ATR مثبت [0.6,2.2]×ATR،
     TP1 = آخر قمة مؤكدة (مغناطيس السيولة) أو 1.0×ATR أيهما أدنى شرطًا
     (≥ close+0.45×ATR)، TP2 = 2.2×ATR أو أقرب جدار بيع فوقنا، R:R صافي ≥
     أرضية المحرك، وترتيب sl < entry < tp1 < tp2 صارم.

إدارة الموضع (المدير المشترك): جزئي 50% عند TP1 + BE نقية + وقف-أولًا
  intrabar + مهلة 90د — عقائد الحماية المحمية نفسها دون أي تعديل.
خروج مبكر (شموع مغلقة): إغلاق تحت EMA50(5m) مع دلتا سالبة = النظام مات —
  أو انقلاب SuperTrend(15m) هابطًا — «ركوب التيار» لا معنى له بلا تيار.
سبوت فقط: LONG حصرًا (حارس صريح في المدير).
"""

from typing import Optional

from .base import ScalpContext, ScalpSignal, ScalpStrategyBase
from . import indicators as ind

ST15 = (10, 3.0)           # SuperTrend فريم النظام (التأكيد الأعلى)
PULLBACK_WINDOW = 4        # نافذة البحث عن لمسة القيمة
VALUE_TOUCH_ATR = 0.10     # سماحية اللمسة فوق EMA20/VWAP
BODY_MIN = 0.40            # جسم شمعة الاستئناف ≥ 40% من مداها (قوة لا رمشة)
EXT_MAX_ATR = 1.2          # أقصى ابتعاد عن EMA20 (لا شراء من القمة)
SL_BUF_ATR = 0.25          # هامش الوقف تحت قاع التصحيح
SL_MIN_ATR = 0.6           # أضيق وقف مقبول
SL_MAX_ATR = 2.2           # أوسع وقف مقبول — تصحيح 3 شموع طبيعي قد يبتعد 2×ATR (فوقه رفض)
TP1_MIN_MEAT = 0.45        # أقل مسافة مقبولة للهدف الأول
TP1_FALLBACK_ATR = 1.0     # بديل الهدف الأول غياب قمة مؤكدة قريبة
TP2_ATR = 2.2              # الهدف الثاني الافتراضي (يُقص على جدار)
WALL_SCAN_ATR = 3.2        # مدى البحث عن جدار بيع
WALL_BUF_ATR = 0.2         # هامش أمان قبل الجدار
EMA_SLOPE_N = 7            # نافذة ميل EMA50 (ترند قائم لا طازج)
FIB_TOL_ATR = 0.25         # سماحية تقارب قاع التصحيح مع فيبو المحرك


class TrendPullback(ScalpStrategyBase):
    name = "SCALP_TREND"
    label = "🐂 ركوب التيار"

    def evaluate(self, ctx: ScalpContext) -> Optional[ScalpSignal]:
        rows = ctx.k5 or []
        if len(rows) < 60:                                   # G1 بيانات
            return None
        a = ctx.atr5
        if not a or a <= 0:
            return None
        if ctx.live_price is None:
            return None
        close = float(rows[-1]["close"])
        if abs(ctx.live_price - close) > self.cfg.entry_chase_atr * a:
            return None

        highs = [float(r["high"]) for r in rows]
        lows = [float(r["low"]) for r in rows]
        closes = [float(r["close"]) for r in rows]
        opens = [float(r["open"]) for r in rows]
        n = len(rows)

        # G2 نظام قائم — SuperTrend 15m صاعد + EMA50(5m) صاعدة والسعر فوقها
        if len(ctx.k15 or []) >= 25:
            h15 = [float(r["high"]) for r in ctx.k15]
            l15 = [float(r["low"]) for r in ctx.k15]
            c15 = [float(r["close"]) for r in ctx.k15]
            st15 = ind.supertrend(h15, l15, c15, ST15[0], ST15[1])
            if not st15 or st15["dir"] != 1.0:
                return None                                  # لا تيار أعلى
        else:
            return None                                      # بلا فريم النظام لا صفقة
        e50 = ind.ema(closes, 50)
        e50_now = e50[-1] if e50 and e50[-1] == e50[-1] else None
        e50_prev = e50[-1 - EMA_SLOPE_N] if len(e50) > EMA_SLOPE_N and e50[-1 - EMA_SLOPE_N] == e50[-1 - EMA_SLOPE_N] else None
        if not e50_now or e50_prev is None:
            return None
        if not (closes[-1] > e50_now and e50_now > e50_prev):
            return None                                      # النظام غير قائم

        # G3 تصحيح صحي — لمسة قيمة في شموع التصحيح التي سبقت الاستئناف
        # (النافذة = 4 شموع قبل الأخيرة؛ شمعة الاستئناف نفسها تُستبعد لأنها
        # تفتح قرب القيمة بطبيعتها — إدراجها يجعل البوابة بلا معنى)
        e20 = ind.ema(closes, 20)
        e20_now = e20[-1] if e20 and e20[-1] == e20[-1] else None
        if not e20_now:
            return None
        vw = ind.vwap_rolling(rows[-72:])
        value_ref = max(e20_now, vw) if vw else e20_now      # أقوى حاجز قيمة
        w0 = max(0, n - 1 - PULLBACK_WINDOW)
        touched = any(lows[i] <= value_ref + VALUE_TOUCH_ATR * a for i in range(w0, n - 1))
        if not touched:
            return None                                      # لا تصحيح إلى القيمة
        pull_low = min(lows[w0:n - 1])                       # قاع التصحيح المرجعي

        # G4 استئناف مؤكد — شمعة صاعدة تغلق فوق EMA20 بدلتا موجبة
        last = rows[-1]
        rng = max(float(last["high"]) - float(last["low"]), 1e-12)
        body = float(last["close"]) - float(last["open"])
        if not (body > 0 and body >= BODY_MIN * rng and close > e20_now):
            return None                                      # لا استئناف بعد
        cv = ind.cvd_series(rows)
        if not cv:
            return None
        if not (cv["delta_last"] > 0 and cv["cvd"][-1] > cv["ema"][-1]):
            return None                                      # الدلتا لم تعد بعد

        # G5 موقع سليم — فوق VWAP وفوق POC وبلا امتداد
        if vw and close <= vw:
            return None
        vp = ind.volume_profile(rows)
        if vp and close < vp["poc"]:
            return None                                      # لا شراء تحت مغناطيس القيمة
        if abs(close - e20_now) > EXT_MAX_ATR * a:
            return None                                      # منتهي التصحيح — متأخرون

        # G6 هندسة المخاطرة — وقف تحت قاع التصحيح مثبت [0.6,1.6]×ATR
        sl = pull_low - SL_BUF_ATR * a
        dist = close - sl
        if dist < SL_MIN_ATR * a:
            sl = close - SL_MIN_ATR * a
        elif dist > SL_MAX_ATR * a:
            return None                                      # تصحيح عميق جدًا — هندسة فاسدة
        # TP1: آخر قمة مؤكدة كهدف سيولة (أقرب من البديل ويُبلَغ) وإلا 1.0×ATR
        swing_hi, _swing_lo = ind.last_confirmed_swing(highs, lows, right=2)
        tp1 = close + TP1_FALLBACK_ATR * a
        if swing_hi and close + TP1_MIN_MEAT * a <= swing_hi <= close + 2.5 * a:
            tp1 = swing_hi
        tp2 = close + TP2_ATR * a
        wall_used = None
        if ctx.depth:
            bucket = max(0.25 * a, close * 1e-5)
            walls = ind.detect_walls(ctx.depth.get("asks") or [], bucket)
            wall = ind.nearest_wall(walls, above=True, ref_price=close)
            if wall and (wall[0] - close) <= WALL_SCAN_ATR * a:
                capped = wall[0] - WALL_BUF_ATR * a
                if capped > close + 1.2 * a:
                    tp2 = capped
                    wall_used = wall[0]
        if tp2 - close < 1.2 * a:
            return None
        if tp1 >= tp2 - 0.35 * a:
            tp1 = close + max(TP1_MIN_MEAT * a, (tp2 - close) * 0.5)
        if not (sl < close < tp1 < tp2):
            return None

        rr1 = self._rr_net(close, sl, tp1, self._fee_rate(ctx))
        if rr1 < self.cfg.rr_net_min:
            return None

        # درجات الجودة: تقارب قاع التصحيح مع فيبو المحرك + جدار شراء تحتنا
        score = 1.0
        fib_hit = None
        if ctx.fib_confluence:
            for key in ("0.618", "0.786"):
                lv = ctx.fib_confluence.get(key)
                if lv and abs(lv - pull_low) <= FIB_TOL_ATR * a:
                    score += 0.5
                    fib_hit = key
                    break
        bid_wall = None
        if ctx.depth:
            bucket = max(0.25 * a, close * 1e-5)
            walls = ind.detect_walls(ctx.depth.get("bids") or [], bucket)
            wall = ind.nearest_wall(walls, above=False, ref_price=sl)
            if wall and (sl - wall[0]) <= 0.6 * a:
                score += 0.5
                bid_wall = wall[0]

        meta = self._base_meta(ctx)
        meta.update({
            "entry_ref": close, "atr5": a, "tp1": tp1, "tp2": tp2,
            "pull_low": pull_low, "value_ref": value_ref,
            "ema20": e20_now, "ema50": e50_now, "vwap": vw,
            "poc": vp["poc"] if vp else None, "wall": wall_used, "bid_wall": bid_wall,
            "score": round(score, 2), "fib_hit": fib_hit,
            "cvd_delta_last": round(float(cv["delta_last"]), 8),
            "rr1": round(rr1, 2), "tp1_basis": "swing" if swing_hi and tp1 == swing_hi else "atr",
            "fail_level": e50_now,                   # إغلاق تحت EMA50 = مات النظام
        })
        q = f" + تقارب فيبو {fib_hit}" if fib_hit else ""
        reason = (f"تصحيح لمس القيمة {value_ref:.6g} في ترند مؤكد (SuperTrend 15m صاعد "
                  f"وEMA50 صاعدة) مع شمعة استئناف دلتاها موجبة{q} — وقف تحت قاع التصحيح "
                  f"{pull_low:.6g}")
        return ScalpSignal(strategy=self.name, label=self.label, symbol=ctx.symbol,
                           entry_ref=close, sl=sl, tp1=tp1, tp2=tp2, rr1=rr1,
                           reason=reason, meta=meta)

    def _fee_rate(self, ctx: ScalpContext) -> float:
        return float((ctx.extra or {}).get("fee_rate", 0.001))
