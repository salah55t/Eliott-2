# -*- coding: utf-8 -*-
"""مؤشرات الاستراتيجيات المتوازية — حسابات خالصة بلا حالة وبلا I/O
================================================================
كل الدوال تستقبل قوائم أرقام وتعيد قيمًا — قابلة للاختبار صناعيًا 100%.

الإسناد:
  • supertrend: إعادة كتابة بايثون لصيغة flowsurface (Apache-2.0):
    ATR بـ RMA ويلدر + قفل النطاقات (band locking) + انقلاب بالتقاطع.
  • cvd: دلتا الشمعة من حقل «حجم المشتري بالتاكير» في شموع باينانس الخام
    (المفهوم نفسه الذي تعرضه طبقات التدفق في flowsurface/flowmap).
    الوضع الاحتياطي «proxy» يقدّر الدلتا موضعيًا داخل الشمعة (تقريب معروف).
  • volume_profile: توزيع حجم التسعير على صناديق سعرية — POC/VAH/VAL
    بمنطقة قيمة 70% (المفهوم القياسي الذي تستخدمه لوحات OrderFlow).
"""

from typing import Dict, List, Optional, Sequence, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# متوسطات أساسية
# ─────────────────────────────────────────────────────────────────────────────

def sma(values: Sequence[float], period: int) -> List[float]:
    """متوسط متحرك بسيط — القيم قبل اكتمال الفترة = NaN (لا تلفيق)."""
    out: List[float] = [float("nan")] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += float(v)
        if i >= period:
            s -= float(values[i - period])
        if i >= period - 1:
            out[i] = s / period
    return out


def ema(values: Sequence[float], period: int) -> List[float]:
    """متوسط أسي — البذرة SMA للفترة الأولى (اصطلاح TradingView)."""
    out: List[float] = [float("nan")] * len(values)
    if len(values) < period or period <= 0:
        return out
    k = 2.0 / (period + 1.0)
    seed = sum(float(v) for v in values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = float(values[i]) * k + prev * (1.0 - k)
        out[i] = prev
    return out


def rma(values: Sequence[float], period: int) -> List[float]:
    """RMA ويلدر (المستخدم في ATR/ADX) — بذرة SMA ثم تنعيم 1/period."""
    out: List[float] = [float("nan")] * len(values)
    if len(values) < period or period <= 0:
        return out
    seed = sum(float(v) for v in values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = (prev * (period - 1) + float(values[i])) / period
        out[i] = prev
    return out


# ─────────────────────────────────────────────────────────────────────────────
# ATR / ADX — ويلدر
# ─────────────────────────────────────────────────────────────────────────────

def true_ranges(highs: Sequence[float], lows: Sequence[float],
                closes: Sequence[float]) -> List[float]:
    trs: List[float] = []
    for i in range(len(highs)):
        if i == 0:
            trs.append(float(highs[i]) - float(lows[i]))
            continue
        tr = max(float(highs[i]) - float(lows[i]),
                 abs(float(highs[i]) - float(closes[i - 1])),
                 abs(float(lows[i]) - float(closes[i - 1])))
        trs.append(tr)
    return trs


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
        period: int = 14) -> Optional[float]:
    """ATR ويلدر — آخر قيمة RMA للمدى الحقيقي."""
    trs = true_ranges(highs, lows, closes)
    r = rma(trs, period)
    v = r[-1] if r else float("nan")
    if v != v:  # NaN
        return None
    return float(v)


def adx(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
        period: int = 14) -> Optional[float]:
    """ADX ويلدر — قوة الاتجاه 0..100 (بلا اتجاه). None إن لم يكتمل النضج."""
    full = di(highs, lows, closes, period)
    return None if full is None else full["adx"]


def di(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
       period: int = 14) -> Optional[Dict[str, float]]:
    """[EL2.2.0] ADX مع مؤشري الاتجاه +DI/−DI (تفكيك حسابات ويلدر ذاتها) —
    يعيد {"adx","pdi","mdi"} آخر قيمة، أو None إن لم يكتمل النضج.
    +DI/−DI يحتاجهما انفجار الاختناق ليفرّق الاندفاع الصاعد عن الهابط."""
    n = len(closes)
    if n < 2 * period + 1:
        return None
    plus_dm: List[float] = [0.0]
    minus_dm: List[float] = [0.0]
    for i in range(1, n):
        up = float(highs[i]) - float(highs[i - 1])
        dn = float(lows[i - 1]) - float(lows[i])
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
    trs = true_ranges(highs, lows, closes)
    tr_r = rma(trs, period)
    p_r = rma(plus_dm, period)
    m_r = rma(minus_dm, period)
    dxs: List[float] = []
    pdi_last = mdi_last = float("nan")
    for i in range(n):
        if tr_r[i] != tr_r[i] or p_r[i] != p_r[i] or m_r[i] != m_r[i]:
            continue
        if tr_r[i] <= 0:
            dxs.append(0.0)
            continue
        pdi = 100.0 * p_r[i] / tr_r[i]
        mdi = 100.0 * m_r[i] / tr_r[i]
        pdi_last, mdi_last = pdi, mdi
        denom = (pdi + mdi)
        dxs.append(100.0 * abs(pdi - mdi) / denom if denom > 0 else 0.0)
    if len(dxs) < period:
        return None
    # RMA على سلسلة DX (انطلاقًا من متوسط أول period قيمة)
    seed = sum(dxs[:period]) / period
    prev = seed
    for v in dxs[period:]:
        prev = (prev * (period - 1) + v) / period
    if pdi_last != pdi_last:
        return None
    return {"adx": float(prev), "pdi": float(pdi_last), "mdi": float(mdi_last)}


# ─────────────────────────────────────────────────────────────────────────────
# SuperTrend — إعادة كتابة صيغة flowsurface (Apache-2.0)
# ─────────────────────────────────────────────────────────────────────────────

def supertrend(highs: Sequence[float], lows: Sequence[float],
               closes: Sequence[float], period: int = 10,
               mult: float = 2.5) -> Optional[Dict[str, float]]:
    """يعيد آخر حالة: {"dir": +1/-1, "line": مستوى الخط, "flip_bar": مؤشر آخر انقلاب}
    الخوارزمية: نطاقان حول hl2 بمقدار mult×ATR(RMA) مع القفل (النطاق لا يتسع
    إلا بالاتجاه) والانقلاب عند إغلاق خلف النطاق المقفل — كما في flowsurface.
    """
    n = len(closes)
    if n < period + 2:
        return None
    trs = true_ranges(highs, lows, closes)
    atr_r = rma(trs, period)
    direction = 0
    line = float("nan")
    flip_bar = -1
    prev_upper = prev_lower = float("nan")
    for i in range(n):
        a = atr_r[i]
        if a != a:
            continue
        mid = (float(highs[i]) + float(lows[i])) / 2.0
        upper = mid + mult * a
        lower = mid - mult * a
        # قفل النطاقات — لا تخفف النطاق إلا بالاتجاه الصاعد/الهابط
        if prev_upper == prev_upper:
            upper = upper if (upper < prev_upper or float(closes[i - 1]) > prev_upper) else prev_upper
            lower = lower if (lower > prev_lower or float(closes[i - 1]) < prev_lower) else prev_lower
        if direction == 0:
            direction = 1 if float(closes[i]) >= mid else -1
            flip_bar = i
        elif float(closes[i]) > prev_upper and direction == -1:
            direction, flip_bar = 1, i
        elif float(closes[i]) < prev_lower and direction == 1:
            direction, flip_bar = -1, i
        line = lower if direction == 1 else upper
        prev_upper, prev_lower = upper, lower
    if direction == 0:
        return None
    return {"dir": float(direction), "line": float(line), "flip_bar": int(flip_bar)}


# ─────────────────────────────────────────────────────────────────────────────
# CVD — الدلتا التراكمية من شموع باينانس الخام
# ─────────────────────────────────────────────────────────────────────────────

def cvd_series(rows: Sequence[Dict[str, float]]) -> Optional[Dict[str, object]]:
    """rows: قاموسات {open, high, low, close, volume, taker_base?}
    الوضع «taker»: delta = 2×taker_base − volume (حقل باينانس 9 الخام — الحقيقة).
    الوضع «proxy»: delta = volume × (close−open)/max(high−low,eps) (تقريب موضعي).
    يعيد: {"cvd": [...], "ema": [...], "delta_last": float, "source": str}
    """
    if not rows or len(rows) < 5:
        return None
    has_taker = all(("taker_base" in r) and r.get("taker_base") is not None for r in rows)
    deltas: List[float] = []
    src = "taker"
    for r in rows:
        vol = float(r["volume"])
        if vol <= 0:
            deltas.append(0.0)
            continue
        if has_taker:
            deltas.append(2.0 * float(r["taker_base"]) - vol)
        else:
            rng = float(r["high"]) - float(r["low"])
            pos = (float(r["close"]) - float(r["open"])) / rng if rng > 0 else 0.0
            deltas.append(vol * max(-1.0, min(1.0, pos)))
            src = "proxy"
    cvd: List[float] = []
    acc = 0.0
    for d in deltas:
        acc += d
        cvd.append(acc)
    e = ema(cvd, 12)
    return {"cvd": cvd, "ema": e, "delta_last": deltas[-1], "source": src}


# ─────────────────────────────────────────────────────────────────────────────
# VWAP الجلسة (تراكمي على النافذة المعطاة)
# ─────────────────────────────────────────────────────────────────────────────

def vwap_rolling(rows: Sequence[Dict[str, float]]) -> Optional[float]:
    """VWAP على النافذة: Σ(tp×v)/Σ(v) حيث tp=(h+l+c)/3."""
    if not rows:
        return None
    pv = 0.0
    vv = 0.0
    for r in rows:
        v = float(r["volume"])
        tp = (float(r["high"]) + float(r["low"]) + float(r["close"])) / 3.0
        pv += tp * v
        vv += v
    if vv <= 0:
        return None
    return pv / vv


# ─────────────────────────────────────────────────────────────────────────────
# Volume Profile — POC/VAH/VAL بمنطقة قيمة 70%
# ─────────────────────────────────────────────────────────────────────────────

def volume_profile(rows: Sequence[Dict[str, float]], bins: int = 48,
                   lookback: int = 72) -> Optional[Dict[str, float]]:
    """توزيع حجم التسعير (v × tp) لكل شمعة بالتساوي على الصناديق التي يغطيها
    مداها [low, high] — ثم POC = أعلى صندوق، ومنطقة القيمة تتسع من POC جارًة
    الجار الأثقل حتى 70% من الحجم. يعيد {"poc","vah","val","total"} أو None
    إن كان المدى منحلًا (high==low لكل الشموع)."""
    sub = list(rows[-lookback:]) if lookback and len(rows) > lookback else list(rows)
    if len(sub) < 10:
        return None
    lo = min(float(r["low"]) for r in sub)
    hi = max(float(r["high"]) for r in sub)
    if hi <= lo:
        return None
    step = (hi - lo) / bins
    vols = [0.0] * bins
    for r in sub:
        rl = max(lo, float(r["low"]))
        rh = min(hi, float(r["high"]))
        v = float(r["volume"])
        if rh <= rl or v <= 0:
            continue
        tp = (float(r["high"]) + float(r["low"]) + float(r["close"])) / 3.0
        quote = v * tp
        i0 = int((rl - lo) / step)
        i1 = min(bins - 1, int((rh - lo) / step))
        span = i1 - i0 + 1
        per = quote / span
        for i in range(i0, i1 + 1):
            vols[i] += per
    total = sum(vols)
    if total <= 0:
        return None
    poc_i = max(range(bins), key=lambda i: vols[i])
    # منطقة القيمة 70% — توسّع جار للجار الأثقل
    lo_i = hi_i = poc_i
    acc = vols[poc_i]
    target = 0.70 * total
    while acc < target and (lo_i > 0 or hi_i < bins - 1):
        below = vols[lo_i - 1] if lo_i > 0 else -1.0
        above = vols[hi_i + 1] if hi_i < bins - 1 else -1.0
        if above >= below:
            hi_i += 1
            acc += vols[hi_i]
        else:
            lo_i -= 1
            acc += vols[lo_i]
    def edge(i: int) -> float:
        # مركز الصندوق أفدق تمثيلًا للمنطقة من مركزية التوزيع
        return lo + (i + 0.5) * step
    return {"poc": edge(poc_i), "vah": edge(hi_i), "val": edge(lo_i),
            "total": total, "step": step}


# ─────────────────────────────────────────────────────────────────────────────
# جدران السيولة — تجميعات العمق السعرية (فكرة Liquidity Radar في OrderFlowMap)
# ─────────────────────────────────────────────────────────────────────────────

def detect_walls(levels: Sequence[Tuple[float, float]], bucket: float,
                 k: float = 6.0) -> List[Tuple[float, float]]:
    """levels: [(سعر, كمية)] من دفتر الأوامر (اتجاه واحد: bids أو asks).
    التجميع في صناديق بعرض bucket (نستخدم 0.25×ATR)، والجدار = صندوق كميته
    ≥ k× الوسيط. يعيد [(سعر مركز الصندوق, كمية)] مرتبة تنازليًا بالكمية."""
    if not levels or bucket <= 0:
        return []
    acc: Dict[int, float] = {}
    for p, q in levels:
        try:
            p, q = float(p), float(q)
        except (TypeError, ValueError):
            continue
        if p <= 0 or q <= 0:
            continue
        idx = int(p / bucket)
        acc[idx] = acc.get(idx, 0.0) + q
    if len(acc) < 4:
        return []
    qs = sorted(acc.values())
    median = qs[len(qs) // 2]
    if median <= 0:
        return []
    walls = []
    for idx, q in acc.items():
        if q >= k * median:
            walls.append((idx * bucket, q))
    walls.sort(key=lambda w: w[1], reverse=True)
    return walls[:4]


def nearest_wall(walls: Sequence[Tuple[float, float]], above: bool,
                 ref_price: float) -> Optional[Tuple[float, float]]:
    """أقرب جدار فوق (asks) أو تحت (bids) سعر مرجعي."""
    cands = [(p, q) for p, q in walls
             if ((p > ref_price) if above else (p < ref_price))]
    if not cands:
        return None
    cands.sort(key=lambda w: abs(w[0] - ref_price))
    return cands[0]


# ─────────────────────────────────────────────────────────────────────────────
# [EL2.4.1][F2] حدود السعر منذ لحظة الحدث — المساعدات النقية (بلا I/O)
# ─────────────────────────────────────────────────────────────────────────────

def candle_open_epoch(last):
    """[EL2.4.1][F2] وقت فتح الشمعة (epoch ثوانٍ) من عمود timestamp — None إن غاب (سلوك قديم)."""
    try:
        return float(last["timestamp"].timestamp())
    except (KeyError, AttributeError, TypeError, ValueError):
        return None


def merge_extremes(state, since_ts, live, candle_open_ts=None,
                   candle_high=None, candle_low=None, slack=15.0):
    """[EL2.4.1][F2] أعلى/أدنى سعر منذ since_ts. state = القاموس السابق أو None.
    السعر الحي يُدمج دائمًا؛ حدّا الشمعة يُدمجان فقط إن فُتحت الشمعة بعد since_ts - slack
    (أو candle_open_ts is None = سلوك قديم/اختبارات). حالة أقدم من since_ts تُهمل (إعادة بذر)."""
    keep = state if (state and float(state.get("since", 0.0)) >= float(since_ts)) else None
    hi = keep["hi"] if keep else None
    lo = keep["lo"] if keep else None
    pts = []
    if live:
        pts.append(float(live))
    if candle_high is not None and candle_low is not None and (
            candle_open_ts is None or float(candle_open_ts) >= float(since_ts) - slack):
        pts += [float(candle_high), float(candle_low)]
    for p in pts:
        hi = p if hi is None else max(hi, p)
        lo = p if lo is None else min(lo, p)
    return {"since": float(since_ts), "hi": hi, "lo": lo}


# ─────────────────────────────────────────────────────────────────────────────
# أدوات بنية مساعدة
# ─────────────────────────────────────────────────────────────────────────────

def last_confirmed_swing(highs: Sequence[float], lows: Sequence[float],
                         right: int = 2) -> Tuple[Optional[float], Optional[float]]:
    """آخر قمة/قاع مؤكد (يمين = right شموع أقل منه) — للوقف الدقيق."""
    n = len(highs)
    swing_hi = swing_lo = None
    for i in range(n - right - 1, 0, -1):
        if swing_hi is None and all(float(highs[i]) >= float(highs[i + j]) for j in range(1, right + 1)):
            swing_hi = float(highs[i])
        if swing_lo is None and all(float(lows[i]) <= float(lows[i + j]) for j in range(1, right + 1)):
            swing_lo = float(lows[i])
        if swing_hi is not None and swing_lo is not None:
            break
    return swing_hi, swing_lo


def fib_retrace_levels(sw_lo: float, sw_hi: float) -> Dict[str, float]:
    """مستويات فيبو التصحيحية لساق اندفاع [sw_lo → sw_hi] — مفاتيح المحرك
    الكانونية (0.618/0.786 للتصحيح العميق) المستخدمة كتقارب لاستراتيجية القيمة."""
    rng = sw_hi - sw_lo
    return {"0.382": sw_hi - 0.382 * rng, "0.5": sw_hi - 0.5 * rng,
            "0.618": sw_hi - 0.618 * rng, "0.786": sw_hi - 0.786 * rng}


def rows_from_basic(basic: Sequence[Sequence[float]]) -> List[Dict[str, float]]:
    """تحويل صفوف 6-حقول [ts,o,h,l,c,v] إلى قاموسات موحدة (وضع proxy للـCVD)."""
    out: List[Dict[str, float]] = []
    for r in basic or []:
        try:
            out.append({"ts": float(r[0]), "open": float(r[1]), "high": float(r[2]),
                        "low": float(r[3]), "close": float(r[4]), "volume": float(r[5]),
                        "taker_base": None})
        except (IndexError, TypeError, ValueError):
            continue
    return out


def rows_from_full(raw: Sequence[Sequence[float]]) -> List[Dict[str, float]]:
    """صفوف باينانس الخام الكاملة (12 حقلًا) → قاموسات مع taker_base (حقل 9)."""
    out: List[Dict[str, float]] = []
    for r in raw or []:
        try:
            out.append({"ts": float(r[0]), "open": float(r[1]), "high": float(r[2]),
                        "low": float(r[3]), "close": float(r[4]), "volume": float(r[5]),
                        "taker_base": float(r[9]) if r[9] is not None else None})
        except (IndexError, TypeError, ValueError):
            continue
    return out


def closed_rows(rows: Sequence[Dict[str, float]], tf_sec: int,
                now_ts: Optional[float] = None) -> List[Dict[str, float]]:
    """الشموع المغلقة حصرًا — الأخيرة قيد التكوين تُستبعد (لا قرار على شمعة لم تغلق)."""
    if not rows:
        return []
    now_ms = (now_ts * 1000.0) if now_ts else None
    out = []
    for r in rows:
        ts = float(r["ts"])
        if now_ms is not None and ts + tf_sec * 1000.0 > now_ms:
            continue
        out.append(r)
    if now_ms is None:
        return out if len(out) < len(rows) else rows[:-1]
    return out
