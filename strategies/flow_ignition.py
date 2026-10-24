# -*- coding: utf-8 -*-
"""الاستراتيجية S1 — «انجلال التدفق» (Flow Ignition)
====================================================
سكالب زخم انضباطي على 5m يدخل مع اندلاع دلتا المشترين (CVD) المؤكدة بالاتجاه،
ويعتبر جدران السيولة العلوية أهدافًا طبيعية للموجة القصيرة (رادار السيولة).

فكرة القرار (من مفاهيم flowsurface/flowmap/OrderFlowMap — كود أصلي):
  الدلتا تقود السعر: حين يتقدم CVD لأعلى مستوى في النافذة بينما السعر لم
  يندلع بعد (قريب من EMA20 وفوق VWAP) فالشراء عدواني حقيقي لا تلفيق — ندخل
  معه بوقف ATR ضيق وهدفين: الأول قريب (1.1×ATR) والثاني عند أقرب جدار
  بيع فوقنا إن وُجد (فكرة Liquidity Radar) وإلا 2.2×ATR.

بوابات الدخول (كلها إلزامية بالترتيب):
  G1 بيانات: ≥60 شمعة 5m مغلقة + سعر حي موجود ضمن 0.4×ATR من الإغلاق (لا ملاحقة).
  G2 اتجاه: SuperTrend(10, 2.5) على 5m صاعد، والتأكيد: SuperTrend(10, 3.0) على 15m صاعد **أو** ADX(14) ≥ 22 (زخم محلي قوي يكفي حين يتخلف الفريم الأعلى).
  G2c اتجاه DI [EL2.4.0]: +DI > −DI — درس الباك تاست: ADX بلا اتجاه يرتفع في
     الهبوط الحاد أيضًا ف«يؤكد» شراءً عكسيًا (AVAX: 14 صفقة إصابة 7%).
  G7 انحياز الساعة [EL2.4.0]: SuperTrend(10, 3.0) على 1h صاعد — فلسفة flowsurface
     متعددة الفريمات: لا شراء ضد ترند الساعة (fail-open عند غياب شموع 1h).
  G3 اندلاع الدلتا: CVD(5m) فوق أعلى قيمة له في آخر 36 شمعة سابقة وفوق EMA12 له.
  G4 حجم: حجم شمعة القرار ≥ 1.3× متوسط 20 شمعة.
  G5 موقع: الإغلاق فوق VWAP الجلسة وفوق POC (المشترون يسيطرون) وليس ممددًا
     (ضمن 1.4×ATR من EMA20).
  G6 هندسة المخاطرة: R:R صافي حتى TP1 ≥ أرضية المحرك (0.3) — والموقف بنيويًا
     في ترتيب sl < entry < tp1 < tp2 صارم.

التنفيذ [EL2.4.0] — «لا مطاردة شمعة الانفجار»: بدل شراء سوق عند إغلاق شمعة
الاندلاع (قمة الدفعة غالبًا)، يضع المدير أمرًا محددًا بعمق SCALP_RETRACE_ATR×ATR
تحت إغلاق القرار، صالحًا SCALP_RETRACE_EXPIRY شموع 5m، لا يُملأ إلا بشمعة رفض
مؤكدة (لمست الحد وأغلقت فوقه — مضاد السكاكين الساقطة)، ويُلغى عند كسر الوقف
المرجعي أو انقلاب SuperTrend. درس BT-LAB: هذا التغيير وحده قلب PF من 0.57 إلى 1.53.

إدارة الموضع (المدير): جزئي 50% عند TP1 + نقل الوقف لنقطة الدخول (BE) — نفس
عقيدة الحماية المحمية للمحرك — والباقي عند TP2 أو انقلاب الدلتا ضدنا أو المهلة.
"""

from typing import Optional

from .base import ScalpContext, ScalpSignal, ScalpStrategyBase
from . import indicators as ind

CVD_LOOKBACK = 36          # نافذة اندلاع CVD
VOL_MULT = 1.3             # مضاعف الحجم فوق المتوسط
ADX_MIN = 22.0             # أرضية قوة الاتجاه المحلي
ST5 = (10, 2.5)            # SuperTrend فريم التنفيذ
ST15 = (10, 3.0)           # SuperTrend فريم التأكيد
EXT_MAX_ATR = 1.4          # أقصى امتداد فوق EMA20 (لا ملاحقة متأخرة)
SL_ATR = 0.9               # مسافة الوقف
TP1_ATR = 1.1              # الهدف الأول
TP2_ATR = 2.2              # الهدف الافتراضي (يُقص على أقرب جدار)
WALL_SCAN_ATR = 3.2        # مدى البحث عن جدار بيع فوق السعر
WALL_BUF_ATR = 0.2         # هامش أمان قبل الجدار (لا نستلم عند الجدار حرفيًا)
MIN_SL_ATR = 0.55          # أضيق وقف مقبول
MAX_SL_ATR = 1.4           # أوسع وقف مقبول (أوسع = ليست صفقة سكالب)


class FlowIgnition(ScalpStrategyBase):
    name = "SCALP_FLOW"
    label = "⚡ انجلال التدفق"

    def evaluate(self, ctx: ScalpContext) -> Optional[ScalpSignal]:
        rows = ctx.k5 or []
        if len(rows) < 60:                       # G1 بيانات
            return None
        a = ctx.atr5
        if not a or a <= 0:
            return None
        close = float(rows[-1]["close"])
        # سعر حي موجود وقريب من إغلاق القرار — لا دخول على فجوة تجاوزنا
        if ctx.live_price is None:
            return None
        if abs(ctx.live_price - close) > self.cfg.entry_chase_atr * a:
            return None

        highs = [float(r["high"]) for r in rows]
        lows = [float(r["low"]) for r in rows]
        closes = [float(r["close"]) for r in rows]
        vols = [float(r["volume"]) for r in rows]

        # G2 اتجاه — تنفيذ + تأكيد
        st5 = ind.supertrend(highs, lows, closes, ST5[0], ST5[1])
        if not st5 or st5["dir"] != 1.0:
            return None
        d5 = ind.di(highs, lows, closes, 14)
        adx5 = d5["adx"] if d5 else None
        st15 = None
        if len(ctx.k15 or []) >= 25:
            h15 = [float(r["high"]) for r in ctx.k15]
            l15 = [float(r["low"]) for r in ctx.k15]
            c15 = [float(r["close"]) for r in ctx.k15]
            st15 = ind.supertrend(h15, l15, c15, ST15[0], ST15[1])
        confirmed = (st15 and st15["dir"] == 1.0) or (adx5 is not None and adx5 >= ADX_MIN)
        if not confirmed:
            return None
        # G2c بوابة الاتجاه [EL2.4.0] — ADX بلا اتجاه: درس BT-LAB (45 يومًا):
        # تأكيد ADX≥22 وحده كان يمرر شراءً في هبوط حاد (DI− مسيطر) — AVAX وحدها
        # خسرت 123$ بـ WR 7%. اشتراط +DI > −DI يجعل التأكيد اتجاهيًا صريحًا.
        if self.cfg.di_gate >= 1 and d5 and not (d5["pdi"] > d5["mdi"]):
            return None

        # G3 اندلاع الدلتا (CVD يقود)
        cv = ind.cvd_series(rows)
        if not cv:
            return None
        cvd = cv["cvd"]
        if len(cvd) < CVD_LOOKBACK + 2:
            return None
        prev_max = max(cvd[-(CVD_LOOKBACK + 1):-1])
        if not (cvd[-1] > prev_max and cvd[-1] > cv["ema"][-1]):
            return None

        # G4 حجم فوق المتوسط
        vol_sma = ind.sma(vols[:-1], 20)
        avg_v = vol_sma[-1] if vol_sma and vol_sma[-1] == vol_sma[-1] else None
        if not avg_v or avg_v <= 0 or vols[-1] < VOL_MULT * avg_v:
            return None

        # G5 موقع سليم — فوق VWAP وفوق POC وبلا امتداد زائد
        vw = ind.vwap_rolling(rows[-72:])
        if vw and close <= vw:
            return None
        ema20 = ind.ema(closes, 20)
        e20 = ema20[-1] if ema20 and ema20[-1] == ema20[-1] else None
        if not e20 or abs(close - e20) > EXT_MAX_ATR * a:
            return None
        vp = ind.volume_profile(rows)
        if vp and close <= vp["poc"]:
            return None

        # G7 انحياز الساعة [EL2.4.0] — SuperTrend(10,3.0) على 1h صاعد (فلسفة flowsurface
        # متعددة الفريمات). درس BT-LAB: قتل الصفقات عكس ترند الساعة نصف تقريبًا خسائر
        # السكالب. غياب شموع 1h = fail-open (انسحاب صادق لا تجميد للبوت).
        if self.cfg.htf_gate >= 1 and ctx.k1h:
            st1 = ind.supertrend([float(r["high"]) for r in ctx.k1h],
                                 [float(r["low"]) for r in ctx.k1h],
                                 [float(r["close"]) for r in ctx.k1h], 10, 3.0)
            if st1 and st1["dir"] != 1.0:
                return None

        # الوقف: ATR مضبوط بآخر قاع مؤكد — مُثبَّت داخل حدود السكالب (0.55–1.4×ATR)
        # التثبيت لا الرفض: قاع قريب جدًا يُوسَّع للحد الأدنى (مساحة تنفس)، وقاع بعيد يُقص
        swing_hi, swing_lo = ind.last_confirmed_swing(highs, lows, right=2)
        sl = close - SL_ATR * a
        if swing_lo and swing_lo < close:
            sl = min(sl, swing_lo - 0.15 * a)
        dist = close - sl
        if dist < MIN_SL_ATR * a:
            sl = close - MIN_SL_ATR * a
        elif dist > MAX_SL_ATR * a:
            sl = close - MAX_SL_ATR * a

        # الأهداف: TP1 قريب، TP2 عند أقرب جدار بيع (رادار السيولة) أو 2.2×ATR
        tp1 = close + TP1_ATR * a
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
        if tp1 >= tp2 - 0.35 * a:                # تدرج سليم بين الهدفين
            tp1 = close + max(0.7 * a, (tp2 - close) * 0.5)

        rr1 = self._rr_net(close, sl, tp1, self._fee_rate(ctx))
        if rr1 < self.cfg.rr_net_min:
            return None
        if not (sl < close < tp1 < tp2):
            return None

        meta = self._base_meta(ctx)
        meta.update({
            "entry_ref": close, "atr5": a, "tp1": tp1, "tp2": tp2,
            "wall": wall_used, "adx5": round(adx5, 1) if adx5 is not None else None,
            "st15_dir": (st15 or {}).get("dir"), "rr1": round(rr1, 2),
            "cvd_delta_last": round(float(cv["delta_last"]), 8),
        })
        reason = (f"اندلاع CVD لأعلى مستوى في {CVD_LOOKBACK} شمعة مع SuperTrend 5m صاعد "
                  f"وتأكيد {'15m' if (st15 and st15['dir'] == 1.0) else f'ADX {adx5:.0f}'} "
                  f"وحجم {vols[-1]/avg_v:.1f}× المتوسط — هدف 2 عند "
                  + (f"جدار السيولة {wall_used:.6g}" if wall_used else f"{TP2_ATR}×ATR"))
        return ScalpSignal(strategy=self.name, label=self.label, symbol=ctx.symbol,
                           entry_ref=close, sl=sl, tp1=tp1, tp2=tp2, rr1=rr1,
                           reason=reason, meta=meta)

    def _fee_rate(self, ctx: ScalpContext) -> float:
        """رسوم التيكر — يحقنها المضيف عبر ctx.extra['fee_rate'] (0.001 افتراضي)."""
        return float((ctx.extra or {}).get("fee_rate", 0.001))
