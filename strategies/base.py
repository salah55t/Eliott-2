# -*- coding: utf-8 -*-
"""الواجهة المشتركة لاستراتيجيتي السكالبينغ — عقود صارمة
=======================================================
• الاستراتيجية دالة نقصة evaluate(ctx) → ScalpSignal | None — بلا I/O وبلا حالة.
• كل المعطيات تصل عبر ScalpContext (يبنيه المدير مرة واحدة لكل رمز في الدورة).
• كل القرارات مُسبَّبة نصيًا بالعربية (تصنيف صادق — فلسفة FE1.9.4).
• سبوت فقط: اتجاه LONG حصرًا (لا بيع مكشوف على باينانس سبوت) — أي مسار SHORT
  في الكود معطّل بحارس صريح ويوثّق السبب.
"""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ── ضبط بيئي مشترك (يقرأ مرة واحدة عند الاستيراد — يُتجاوز بالحقن في الاختبارات)

def _env_f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass
class ScalpConfig:
    """ضبط السكالبينغ المشترك — env قابل للضبط الحي."""
    exec_tf: str = os.getenv("SCALP_EXEC_TF", "5m")
    tf_sec: int = 300
    risk_pct: float = _env_f("SCALP_RISK_PCT", 0.75)          # مخاطرة الصفقة كنسبة من الرصيد
    max_notional_usdt: float = _env_f("SCALP_MAX_NOTIONAL_USDT", 1200.0)
    max_notional_pct: float = _env_f("SCALP_MAX_NOTIONAL_PCT", 30.0)   # سقف نسبة من الرصيد
    max_total_open: int = _env_i("SCALP_MAX_TOTAL_OPEN", 2)    # سقف صفقات السكالب مفتوحة معًا (الاتنان)
    max_open_per_strategy: int = _env_i("SCALP_MAX_OPEN_PER_STRATEGY", 2)
    cooldown_sec: int = _env_i("SCALP_COOLDOWN_SEC", 2700)     # تبريد الرمز بعد إغلاق سكالب (45د)
    daily_loss_pct: float = _env_f("SCALP_DAILY_LOSS_PCT", 0.6)  # قاطع خسارة يومي لكل استراتيجية
    max_hold_min: int = _env_i("SCALP_MAX_HOLD_MIN", 90)       # مهلة الصفقة (زمن إيقاف)
    partial_pct: float = _env_f("SCALP_PARTIAL_PCT", 50.0)     # جني جزئي عند TP1 (نفس عقيدة الحماية المحمية)
    rr_net_min: float = _env_f("SCALP_RR_NET_MIN", 0.3)        # أرضية R:R الصافي (نفس أرضية المحرك)
    entry_chase_atr: float = _env_f("SCALP_ENTRY_CHASE_ATR", 0.4)  # أقصى ابتعاد سعر حي عن إغلاق القرار
    min_notional: float = _env_f("SCALP_MIN_NOTIONAL", 10.0)
    symbols_n: int = _env_i("SCALP_SYMBOLS_N", 8)              # عدد الرموز الافتراضي من القائمة
    # [EL2.4.0] دروس الباك تاست BT-LAB (45 يومًا، PF 0.24 → 2.05):
    di_gate: float = _env_f("SCALP_DI_GATE", 1.0)              # +DI > −DI إلزامي (ADX بلا اتجاه)
    htf_gate: float = _env_f("SCALP_HTF_GATE", 1.0)            # SuperTrend(10,3.0) على 1h صاعد
    retrace_atr: float = _env_f("SCALP_RETRACE_ATR", 0.6)      # أمر محدد بعمق ×ATR تحت إغلاق القرار (0 = ملء فوري قديم)
    retrace_expiry: int = _env_i("SCALP_RETRACE_EXPIRY", 8)    # صلاحية الأمر الارتدادي بشموع 5m
    trail_atr: float = _env_f("SCALP_TRAIL_ATR", 1.0)          # تتبع القمة بعد الجزئي+BE (ورقي؛ 0 = معطل)
    cancel_cooldown_sec: int = _env_i("SCALP_CANCEL_COOLDOWN_SEC", 900)  # تبريد بعد إبطال/انتهاء أمر ارتدادي


SCALP_CONFIG = ScalpConfig()


@dataclass
class ScalpContext:
    """معطيات قرار واحدة — يبنيها المدير مرة واحدة لكل رمز/دورة وتستهلكها الاستراتيجيتان."""
    symbol: str
    now_ts: float
    k5: List[Dict[str, float]]            # شموع 5m مغلقة (تاملة الحقول أو proxy)
    k15: List[Dict[str, float]]           # شموع 15m (تأكيد الاتجاه)
    live_price: Optional[float]
    depth: Optional[Dict[str, List]] = None   # {"bids": [(p,q)...], "asks": [...]} عند التوفر
    cvd_source: str = ""                  # "taker" | "proxy" — صدق المصدر يخزن في meta
    atr5: Optional[float] = None
    atr15: Optional[float] = None
    fib_confluence: Optional[Dict[str, float]] = None  # مستويات فيبو آخر ساق (من زيجزاج المحرك)
    extra: Dict[str, Any] = field(default_factory=dict)
    k1h: Optional[List[Dict[str, float]]] = None   # [EL2.4.0] شموع 1h (انحياز الفريم الأعلى — fail-open عند غيابها)


@dataclass
class ScalpSignal:
    """إشارة سكالب ناضجة — المدير وحده ينفذها (بوابات المخاطر قبله)."""
    strategy: str                         # SCALP_FLOW | SCALP_PROFILE
    label: str                            # التسمية العربية للعرض
    symbol: str
    entry_ref: float                      # إغلاق شمعة القرار (المرجع)
    sl: float
    tp1: float
    tp2: float
    rr1: float                            # R:R الصافي حتى TP1 (بوابة الأرضية)
    reason: str                           # السبب العربي الكامل
    meta: Dict[str, Any] = field(default_factory=dict)
    side: str = "LONG"                    # سبوت فقط — الحارس يرفض غيرها


class ScalpStrategyBase:
    """أصل مشترك — الاستراتيجيتان ترثان وتنفذان evaluate فقط."""
    name: str = "SCALP_BASE"
    label: str = "قاعدة"

    def __init__(self, cfg: ScalpConfig = None):
        self.cfg = cfg or SCALP_CONFIG

    def evaluate(self, ctx: ScalpContext) -> Optional[ScalpSignal]:
        raise NotImplementedError

    # ── حماية سبوت: لا بيع مكشوف — أي إشارة غير LONG تُرفض قبل الولادة ──
    def _spot_guard(self, side: str) -> bool:
        """باينانس سبوت: لا تصفية مكشوفة بلا هامش — الاتجاه المعاكس يتطلب
        شراء ثم بيع لاحقًا وهو خارج عقد البوت (سبوت سكالبينغ طويل فقط)."""
        return side == "LONG"

    def _rr_net(self, entry: float, sl: float, tp: float, fee_rate: float) -> float:
        """R:R صافي بعد رسوم الاتجاهين — نفس صيغة المحرك rr_net_value حرفيًا."""
        risk = float(entry) - float(sl)
        if risk <= 0 or entry <= 0:
            return 0.0
        reward = (float(tp) - entry) - fee_rate * (entry + float(tp))
        return reward / risk

    def _base_meta(self, ctx: ScalpContext) -> Dict[str, Any]:
        return {"cvd_source": ctx.cvd_source, "exec_tf": self.cfg.exec_tf}
