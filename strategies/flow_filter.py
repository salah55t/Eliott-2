# -*- coding: utf-8 -*-
"""فلتر التدفق — دعم إشارات موجات إليوت بقرار التدفق الحي (EL2.3.0)
====================================================================
طلب الحاكم: «اجعل استراتيجية اليوت تدعم بفلتر التدفق اي ان البوت يحتوي على
استراتيجية موجات اليوت مدعمة بفلتر يخص التدفق».

الفلسفة — «الموجة تعطي البنية والتدفق يعطي الإذن»:
  محرك الموجات يجد بنية إليوتية صاعدة سليمة (هيكل + فيبو + حيوية العمر)، لكن
  البنية وحدها لا تكفي: إشارة موجات في سوق تدفقه هابط أو بلا طاقة اتجاهية
  أو دلتا المشترين منهارة = بنية جميلة في تيار معاكس تموت قبل هدفها الأول
  (نفس درس SCALP_PROFILE: بنية بلا تدفق = أهداف لا تُلمس). هذا الفلتر يقيّم
  صحة التدفق على فريم التنفيذ 5m لحظة ولادة الإشارة ويمنح/يرفض الإذن.

بوابات الفلتر الأربعة (كلها إلزامية — كلها من ترسانة المشاريع مفتوحة المصدر):
  F1 اتجاه التدفق — SuperTrend(10, 2.5) على 5m صاعد (flowsurface: RMA ويلدر
     + قفل النطاقات — نفس صيغة SCALP_FLOW حرفيًا فلا ازدواج تعريف).
  F2 طاقة الاتجاه — ADX(14) ≥ 20 على 5m (flowsurface: أرضية قوة — سوق بلا
     طاقة اتجاهية يأكل التصحيحات حتى P0).
  F3 دلتا المشترين — CVD(5m) فوق EMA12 له (flowmap: تدفق المشترين ليس منهارًا
     لحظة القرار — لا شراء بنية صاعدة ودلتا تنزف).
  F4 سيطرة الجلسة — الإغلاق فوق VWAP آخر 72 شمعة 5m (لوحات OrderFlow: المشتر
     يون يسيطرون على متوسط السعر المرجح بالحجم).

عقيدة الفشل (نفس عقد المحرك — premise-alive fail-open):
  • بيانات غير كافية أو فشل جلب = fail-open مع وسم صادق (unavailable) وعدّاد
    مستقل — الفلتر لا يصمت أبدًا ولا يخفي فشله، لكنه لا يعطّل المحرك بسبب
    حادثة مزود.
  • كل رفض مسمّى باسم بوابته (F1..F4) — تصنيف صادق يظهر في اللوحة والسجل.

هذا موديول نقي: بلا I/O وبلا حالة — الشموع تصل جاهزة من المضيف والنتيجة
قاموس محايد قابل للاختبار والتخزين في fib_json.
"""

from typing import Any, Dict, List, Optional

from . import indicators as ind

# بوابات الفلتر — نفس ثوابت SCALP_FLOW حيث تلتقي الفلسفة (لا ازدواج معايير)
ST5 = (10, 2.5)          # F1: SuperTrend فريم التنفيذ (كما في FlowIgnition)
ADX_MIN = 20.0           # F2: أرضية طاقة الاتجاه (flowsurface)
VWAP_WINDOW = 72         # F4: نافذة سيطرة الجلسة (6 ساعات على 5m — كما في G5)
MIN_ROWS = 60            # أرضية بيانات — أقل من ذلك الفحص غير صادق
CVD_MIN_ROWS = 38        # هامش حساب CVD وEMA12 معًا (التنعيم 12 داخل cvd_series)


def _unavailable(why: str) -> Dict[str, Any]:
    """حكم فشل صادق — قاموس جديد كل مرة (لا كائن مشترك قابل للتلوث)."""
    return {"ok": True, "unavailable": True, "gate": None,
            "reason": why,
            "meta": {"flow_filter": "unavailable"}}


def evaluate_flow(rows: List[Dict[str, float]],
                  direction: str = "BULLISH",
                  adx_min: float = ADX_MIN) -> Dict[str, Any]:
    """حكم فلتر التدفق على شموع 5m مغلقة — يعيد قاموس الحكم الكامل:
      {"ok": bool, "unavailable": bool, "gate": "F1..F4"|None,
       "reason": str, "meta": {...بصمات القرار للشفافية}}
    direction: BULLISH فقط على سبوت (الهبوط لا يولد إشارات أصلًا — الحارس الأصلي).
    """
    unavailable = _unavailable("بيانات التدفق غير كافية — fail-open بالعقدة الأصلية")
    # سبوت: الهبوط لا يصل هنا أصلًا (حارس المحرك) — الحكم يخص الصاعد وحده
    if direction != "BULLISH":
        return {"ok": True, "unavailable": False, "gate": None,
                "reason": "", "meta": {"flow_filter": "skipped_non_bullish"}}
    if not rows or len(rows) < MIN_ROWS:
        return unavailable

    try:
        highs = [float(r["high"]) for r in rows]
        lows = [float(r["low"]) for r in rows]
        closes = [float(r["close"]) for r in rows]
        meta: Dict[str, Any] = {"flow_filter": "applied"}

        # F1 اتجاه التدفق — SuperTrend 5m صاعد (نفس صيغة SCALP_FLOW)
        st5 = ind.supertrend(highs, lows, closes, ST5[0], ST5[1])
        meta["st5_dir"] = (st5 or {}).get("dir")
        if not st5 or st5["dir"] != 1.0:
            return {"ok": False, "unavailable": False, "gate": "F1",
                    "reason": "اتجاه التدفق هابط (SuperTrend 5m) — الموجة ضد التيار",
                    "meta": meta}

        # F2 طاقة الاتجاه — ADX فوق الأرضية (غير قابل للقياس = fail-open موثّق لا رفض)
        adx5 = ind.adx(highs, lows, closes, 14)
        meta["adx5"] = round(adx5, 1) if adx5 is not None else None
        if adx5 is None:
            return _unavailable("ADX غير مكتمل الحساب — fail-open بالعقدة الأصلية")
        if adx5 < adx_min:
            return {"ok": False, "unavailable": False, "gate": "F2",
                    "reason": f"لا طاقة اتجاهية (ADX {adx5:.1f} < {adx_min:.0f}) — سوق عرضي يأكل التصحيح",
                    "meta": meta}

        # F3 دلتا المشترين — CVD فوق تنعيمه (التدفق ليس منهارًا)
        cv = ind.cvd_series(rows)
        if not cv or len(cv["cvd"]) < CVD_MIN_ROWS:
            return _unavailable("بيانات CVD غير كافية — fail-open بالعقدة الأصلية")
        meta["cvd_ok"] = bool(cv["cvd"][-1] >= cv["ema"][-1])
        meta["delta_last"] = round(float(cv["delta_last"]), 8)
        if not meta["cvd_ok"]:
            return {"ok": False, "unavailable": False, "gate": "F3",
                    "reason": "دلتا المشترين منهارة (CVD تحت EMA12) — لا شراء وتدفق ينزف",
                    "meta": meta}

        # F4 سيطرة الجلسة — الإغلاق فوق VWAP
        vw = ind.vwap_rolling(rows[-VWAP_WINDOW:])
        if vw is not None:
            meta["vwap"] = round(float(vw), 8)
            if closes[-1] <= vw:
                return {"ok": False, "unavailable": False, "gate": "F4",
                        "reason": "الإغلاق تحت VWAP — البائعون يسيطرون على متوسط الجلسة",
                        "meta": meta}

        meta["flow_filter"] = "passed"
        return {"ok": True, "unavailable": False, "gate": None,
                "reason": "", "meta": meta}
    except Exception:            # عقد الفشل: حادثة حساب لا تعطّل المحرك أبدًا
        return _unavailable("حادثة حساب في فلتر التدفق — fail-open بالعقدة الأصلية")
