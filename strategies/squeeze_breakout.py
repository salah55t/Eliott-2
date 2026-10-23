# -*- coding: utf-8 -*-
"""الاستراتيجية S3 — «انفجار الاختناق» (Squeeze Breakout) — EL2.2.0
==================================================================
سكالب انفجار التقلب: السوق يتنفس بدورات تمدد وانضغاط — حين تضيق بولنجر داخل
كيلتنر (اختناق TTM الكلاسيكي) تجمع الطاقة، واندلاعها بحجم ودلتا مؤكدة يبدأ
الساق القصيرة. هذه الحافة الرابعة وهي مختلفة جذريًا عن الأخوات:
  • SCALP_FLOW تشتري زخمًا جاريًا (CVD عند قمة 36 شمعة) — تعقب حركة بدأت.
  • SCALP_TREND تشتري تصحيحًا في تيار قائم.
  • SCALP_SQUEEZE تشتري التوقيت الصفري: آخر شمعة انتقلت من انضغاط إلى تمدد —
    تدخل في بداية التوسع قبل أن يراه الجميع، بوقف صغير (قاعدة الاختناق قريبة).

الإسناد المفاهيمي (كود أصلي — إعادة كتابة):
  • flowsurface (Apache-2.0) — قناتا التقلب والنطاقات المقفلة: صيغ بولنجر
    (SMA ± 2σ) وكيلتنر (EMA ± 1.5×ATR ويلدر) وحالة الاختناق بينهما.
  • freqtrade (GPL-3.0) — شرط «جسم الاندفاع»: الاختراق برمشة زائفة هو
    الفخ الأشهر؛ نطلب جسمًا ≥ 55% من مدى الشمعة (اندفاع حقيقي لا ذيل).
  • OrderFlowMap — جدران السيولة أهدافًا: TP2 عند أقرب جدار بيع فوقنا
    (فكرة Liquidity Radar ذاتها التي أثبتت فاعليتها في SCALP_FLOW).

بوابات الدخول (كلها إلزامية بالترتيب):
  G1 بيانات: ≥60 شمعة 5m مغلقة + سعر حي ضمن 0.4×ATR من الإغلاق (لا ملاحقة).
  G2 اختناق: بولنجر(20,2.0) داخل كيلتنر(20,1.5) في ≥4 من آخر 6 شموع مغلقة —
     طاقة مضغوطة (الانضغاط قبل التمدد، دورة التقلب الكلاسيكية).
  G3 انفجار: آخر شمعة مغلقة خارج بولنجر العلوي (أول إغلاق كسر) بجسم ≥55%
     من مداها — اختراق بالجسم لا بالرمشة (فخ الاختراق الزائف مرفوض).
  G4 وقود: حجم ≥ 1.4× متوسط 20 شمعة + دلتا الشمعة موجبة وCVD فوق EMA12
     + (+DI > −DI) — الاتجاه الصاعد مدعوم بالسيولة لا بغبار التصفية.
  G5 محاذاة: الإغلاق فوق VWAP + SuperTrend(5m) صاعد أو انقلب صاعدًا خلال
     آخر 3 شموع (flip_bar حديث) — الانفجار مع النظام لا ضده.
  G6 هندسة المخاطرة: وقف تحت قاعدة الاختناق (أدنى قاع آخر 3 شموع أو منتصف
     بولنجر — الأعمق) مثبت [0.6,2.0]×ATR (الـATR مضغوط فالوقف يبدو بعيدًا نسبيًا)، TP1 = 1.0×ATR (توسع أول)، TP2 =
     أقرب جدار بيع أو 2.4×ATR، R:R صافي ≥ أرضية المحرك وترتيب صارم.

إدارة الموضع (المدير المشترك): جزئي 50% عند TP1 + BE نقية + وقف-أولًا
  intrabar + مهلة 90د — عقائد الحماية المحمية دون أي تعديل.
خروج مبكر (شموع مغلقة): إغلاق يعود تحت منتصف بولنجر مع دلتا سالبة —
  الانفجار فشل والطاقة تسربت إلى الوراء (خروج أفضل من الوقف غالبًا).
سبوت فقط: LONG حصرًا (حارس صريح في المدير).
"""

from typing import Optional

from .base import ScalpContext, ScalpSignal, ScalpStrategyBase
from . import indicators as ind

BB = (20, 2.0)             # بولنجر — فريم التنفيذ
KC = (20, 1.5)             # كيلتنر — فريم التنفيذ
SQUEEZE_WINDOW = 6         # نافذة فحص الاختناق
SQUEEZE_MIN_BARS = 4       # أقل عدد شموع مختنقة في النافذة
BODY_MIN = 0.55            # جسم شمعة الانفجار ≥ 55% من مداها (لا رمشة)
VOL_MULT = 1.4             # وقود الحجم فوق المتوسط
SL_MIN_ATR = 0.6           # أضيق وقف مقبول
SL_MAX_ATR = 2.0           # أوسع وقف مقبول — الـATR مضغوط في الاختناق فالوقف البنيوي يبدو بعيدًا نسبيًا
TP1_ATR = 1.0              # هدف التوسع الأول
TP2_ATR = 2.4              # الهدف الثاني الافتراضي
WALL_SCAN_ATR = 3.2        # مدى البحث عن جدار بيع
WALL_BUF_ATR = 0.2         # هامش أمان قبل الجدار
ST_FLIP_FRESH = 3          # SuperTrend انقلب خلال آخر 3 شموع = مقبول
MIN_TP2_MEAT = 1.2         # أقل مسافة معقولة للهدف الثاني


class SqueezeBreakout(ScalpStrategyBase):
    name = "SCALP_SQUEEZE"
    label = "💥 انفجار الاختناق"

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
        vols = [float(r["volume"]) for r in rows]
        n = len(rows)

        # G2 اختناق — بولنجر داخل كيلتنر في ≥4 من آخر 6 شموع (نحسب تاريخيًا)
        squeezed_bars = 0
        for i in range(n - SQUEEZE_WINDOW, n):
            if i < 24:
                continue
            bb = ind.bollinger(closes[:i + 1], BB[0], BB[1])
            kc = ind.keltner(highs[:i + 1], lows[:i + 1], closes[:i + 1], KC[0], KC[1])
            if bb and kc and bb["width"] < kc["width"]:
                squeezed_bars += 1
        if squeezed_bars < SQUEEZE_MIN_BARS:
            return None                                      # لا انضغاط كافٍ

        # G3 انفجار — إغلاق خارج بولنجر العلوي بجسم اندفاعي
        bb_now = ind.bollinger(closes, BB[0], BB[1])
        if not bb_now:
            return None
        last = rows[-1]
        rng = max(float(last["high"]) - float(last["low"]), 1e-12)
        body = float(last["close"]) - float(last["open"])
        if not (close > bb_now["upper"] and body > 0 and body >= BODY_MIN * rng):
            return None                                      # لا كسر حقيقي
        # أول إغلاق كسر: الشمعة السابقة كانت داخل النطاق (لا نطارد كسرًا عمره شموع)
        prev_bb = ind.bollinger(closes[:-1], BB[0], BB[1])
        if prev_bb and closes[-2] > prev_bb["upper"]:
            return None

        # G4 وقود — حجم + دلتا + اتجاه DI
        vol_sma = ind.sma(vols[:-1], 20)
        avg_v = vol_sma[-1] if vol_sma and vol_sma[-1] == vol_sma[-1] else None
        if not avg_v or avg_v <= 0 or vols[-1] < VOL_MULT * avg_v:
            return None
        cv = ind.cvd_series(rows)
        if not cv:
            return None
        if not (cv["delta_last"] > 0 and cv["cvd"][-1] > cv["ema"][-1]):
            return None
        di = ind.di(highs, lows, closes, 14)
        if not di or di["pdi"] <= di["mdi"]:
            return None                                      # الاتجاه غير صاعد

        # G5 محاذاة — فوق VWAP + SuperTrend صاعد (الانفجار مع النظام لا ضده)
        # ملاحظة: لا نطلب قرب سند SuperTrend — في الأسواق المختنقة يبتعد السند
        # بطبيعته (ATR صغير) والاختناق الصحيح يبدأ بعيدًا عنه.
        vw = ind.vwap_rolling(rows[-72:])
        if vw and close <= vw:
            return None
        st5 = ind.supertrend(highs, lows, closes, 10, 2.5)
        if not st5 or st5["dir"] != 1.0:
            return None
        fresh_flip = (n - 1 - st5["flip_bar"]) <= ST_FLIP_FRESH

        # G6 هندسة المخاطرة — وقف تحت قاعدة الاختناق مثبت [0.6,1.5]×ATR
        base = min(min(lows[n - 3:]), bb_now["mid"])
        sl = base - 0.15 * a
        dist = close - sl
        if dist < SL_MIN_ATR * a:
            sl = close - SL_MIN_ATR * a
        elif dist > SL_MAX_ATR * a:
            return None                                      # قاعدة بعيدة جدًا — لا سكالب
        tp1 = close + TP1_ATR * a
        tp2 = close + TP2_ATR * a
        wall_used = None
        if ctx.depth:
            bucket = max(0.25 * a, close * 1e-5)
            walls = ind.detect_walls(ctx.depth.get("asks") or [], bucket)
            wall = ind.nearest_wall(walls, above=True, ref_price=close)
            if wall and (wall[0] - close) <= WALL_SCAN_ATR * a:
                capped = wall[0] - WALL_BUF_ATR * a
                if capped > close + MIN_TP2_MEAT * a:
                    tp2 = capped
                    wall_used = wall[0]
        if tp2 - close < MIN_TP2_MEAT * a:
            return None
        if tp1 >= tp2 - 0.35 * a:
            tp1 = close + max(0.7 * a, (tp2 - close) * 0.5)
        if not (sl < close < tp1 < tp2):
            return None

        rr1 = self._rr_net(close, sl, tp1, self._fee_rate(ctx))
        if rr1 < self.cfg.rr_net_min:
            return None

        # درجات الجودة: شدة الاختناق (كل النافذة مختنقة = طاقة أكبر) + حجم عنيف
        score = 1.0
        if squeezed_bars == SQUEEZE_WINDOW:
            score += 0.5
        if avg_v and vols[-1] >= 1.8 * avg_v:
            score += 0.25
        if fresh_flip:
            score += 0.25

        meta = self._base_meta(ctx)
        meta.update({
            "entry_ref": close, "atr5": a, "tp1": tp1, "tp2": tp2,
            "squeeze_bars": squeezed_bars, "bb_upper": bb_now["upper"],
            "bb_mid": bb_now["mid"], "squeeze_base": base, "vwap": vw,
            "wall": wall_used, "fresh_flip": fresh_flip,
            "pdi": round(di["pdi"], 1), "mdi": round(di["mdi"], 1),
            "cvd_delta_last": round(float(cv["delta_last"]), 8),
            "rr1": round(rr1, 2), "score": round(score, 2),
            "fail_level": bb_now["mid"],             # إغلاق تحت منتصف بولنجر = انفجار فشل
        })
        reason = (f"انفجار اختناق (بولنجر داخل كيلتنر {squeezed_bars}/{SQUEEZE_WINDOW} شموع) "
                  f"بإغلاق اندفاعي فوق بولنجر العلوي وحجم {vols[-1]/avg_v:.1f}× المتوسط "
                  f"ودلتا موجبة و+DI {di['pdi']:.0f} > −DI {di['mdi']:.0f}"
                  + (f" — هدف 2 عند جدار السيولة {wall_used:.6g}" if wall_used else ""))
        return ScalpSignal(strategy=self.name, label=self.label, symbol=ctx.symbol,
                           entry_ref=close, sl=sl, tp1=tp1, tp2=tp2, rr1=rr1,
                           reason=reason, meta=meta)

    def _fee_rate(self, ctx: ScalpContext) -> float:
        return float((ctx.extra or {}).get("fee_rate", 0.001))
