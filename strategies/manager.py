# -*- coding: utf-8 -*-
"""مدير الاستراتيجيات المتوازية — Eliott+2
==========================================
شغّلان مستقلان (خيوط) بجانب محرك موجات إليوت دون أي مساس:
  • scalp-scan     — بعد إغلاق كل شمعة 5m: بناء سياق الرموز + تقييم استراتيجية
                     التدفق + البوابات المشتركة + فتح الصفقات + الخروج المبكر (شمعة مغلقة).
  • scalp-monitor  — كل 20ث: وقف-أولًا intrabar + جزئي 50% عند TP1 + BE + TP2
                     + تتبع القمة + مهلة الصفقة. (نفس عقائد الحماية المحمية للمحرك).

[EL2.3.0] قرار الحاكم: «احذف جميع الاستراتيجيات ماعدا موجات اليوت والتدفق» —
حاملة الاستراتيجيات صارت ثنائية: SCALP_FLOW (انجلال التدفق — زخم CVD) وحدها
في هذا المدير، ومحرك الموجات Elliott_Fibonacci في vnz.py مدعوم بفلتر التدفق
(strategies/flow_filter.py — إشارات الموجات لا تُولد إلا بموافقة التدفق).
SCALP_TREND وSCALP_SQUEEZE أُزيلتا نهائيًا وتُسوّى صفوفهما القديمة عند الإقلاع.

[EL2.2.0 تاريخي] SCALP_TREND «ركوب التيار» + SCALP_SQUEEZE «انفجار الاختناق»
وُلدتا واستُبدلتا بقرار لاحق. استراتيجية SCALP_PROFILE أُزيلت نهائيًا بقرار
الحاكم بعد فشلها في بلوغ الأهداف عبر جيلين — تسوية صفوف القديم كله عند الإقلاع.

عقد المضيف (حقن كامل — هذه الحزمة لا تستورد vnz.py إطلاقًا):
  attach_host({
    "db_query"(sql, params) / "db_execute"(sql, params),
    "log_and_notify"(level, msg, ntype), "logger",
    "get_live_price"(symbol), "get_recent_candles"(symbol, tf, limit, min_candles),
    "fetch_ohlcv_raw"(symbol, tf, limit) -> (rows6, source),
    "binance_full_klines"(symbol, interval, limit) -> raw12 | None,
    "binance_depth"(symbol, limit) -> {"bids":..,"asks":..} | None,
    "utc_now_iso", "fmt_price", "seconds_until_next_candle"(tf),
    "is_trading_enabled"() -> bool, "risk_entry_block_reason"() -> str|None,
    "symbol_has_active"(symbol) -> bool,
    "get_paper_balance"(), "fee_rate", "deviation_threshold",
    "zigzag_pivots"(closes, deviation) -> [(idx, price)],
    "close_signal_row"(sig, price, reason), "close_real_trade"(sig, price, reason),
    "account_partial_close"(sig, leg_qty, price, reason),
    "place_real_market_sell"(symbol, qty), "place_real_stop_loss"(symbol, qty, stop),
    "replace_real_stop"(sig, new_stop), "cancel_real_order"(ex, symbol, oid),
    "real_market_buy"(symbol, quote_usdt) -> order|None, "real_free_usdt"(),
    "real_max_notional"() -> float, "real_adjust_amount"(ex, symbol, qty),
    "real_min_amount"(mkt), "real_min_cost"(mkt), "real_market_rules"(symbol, ex),
    "binance_trade_exchange"(), "watchlist"() -> [symbols],
  })
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .base import SCALP_CONFIG, ScalpConfig, ScalpContext, ScalpSignal
from . import indicators as ind
from .flow_ignition import FlowIgnition


def _flag(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "off")


SCALP_ENABLED = _flag("SCALP_ENABLED")
# [EL2.3.0] علم البيئة لاستراتيجية التدفق — SCALP_S1_ENABLED اسم موروث لتوافق render.yaml
S1_ENABLED = _flag("SCALP_S1_ENABLED")
# [EL2.4.1][F3] توحيد سلوك الارتدادي: الوضع الحقيقي يسلّح الأوامر الارتدادية كالورقي
# (لا شراء قمة الاندفاع — النسخة التي خسرت في BT-LAB). SCALP_REAL_RETRACE=0 يعيد القديم.
SCALP_REAL_RETRACE = _flag("SCALP_REAL_RETRACE", "1")

STRATEGY_NAMES = ("SCALP_FLOW",)
# [EL2.3.0] قرار الحاكم: حذف كل الاستراتيجيات عدا موجات إليوت والتدفق —
# SCALP_PROFILE وSCALP_TREND وSCALP_SQUEEZE أسماء مزالة نهائيًا، والصفوف
# المفتوحة القديمة إن وُجدت تُسوّى عند الإقلاع (drain_legacy_strategies)
# ولا يقترب اسمها من أي بوابة.
LEGACY_STRATEGIES = ("SCALP_PROFILE", "SCALP_TREND", "SCALP_SQUEEZE")
# أسباب الوقف الصادقة لكل استراتيجية — تحليل الأداء يتطلب تصنيفًا موثوقًا بالمصدر
SL_REASONS = {
    "SCALP_FLOW": "وقف انجلال التدفق",
}

HOST: Dict[str, Any] = {}
_lock = threading.RLock()
_started = False
# [EL2.1.0] أعلام التفعيل لكل استراتيجية — من البيئة عند الإقلاع ومن اللوحة حيًا
# (زر الإعدادات). التعطيل يمنع توليد إشارات جديدة فقط — الصفقات المفتوحة تُدار حتى الإغلاق.
_enabled: Dict[str, bool] = {"SCALP_FLOW": True}
_state: Dict[str, Any] = {"boot_at": None, "last_scan_at": None, "last_scan_ts": 0.0,
                          "cycles": 0, "last_error": "", "cvd_source_last": ""}
_counters: Dict[str, Dict[str, Any]] = {
    n: {"signals": 0, "partials": 0, "early_exits": 0, "closes": {}, "rejects": {},
        "last_signal_at": None, "last_signal_symbol": None}
    for n in STRATEGY_NAMES
}
_cooldowns: Dict[str, Dict[str, float]] = {n: {} for n in STRATEGY_NAMES}

# [EL2.4.1][F2] حالة حدود السعر منذ لحظة الحدث — ذاكرة العملية حصرًا: ("o", id) للمفتوح
_EXT_STATE: Dict[Tuple[str, int], Dict[str, float]] = {}


def _iso_epoch(s: Any) -> float:
    """[EL2.4.1][F2] 'YYYY-MM-DDTHH:MM:SS...' (أول 19 حرفًا، UTC) → epoch ثوانٍ؛
    0.0 عند الفشل ⇒ سلوك قديم (fail-open)."""
    try:
        return datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _ext_forget(row_id: Any) -> None:
    """[EL2.4.1][F2] مسح حالة الحدود عند نهاية دورة حياة الصف (إغلاق نهائي)."""
    _EXT_STATE.pop(("p", row_id), None)
    _EXT_STATE.pop(("o", row_id), None)


_instances: Dict[str, Any] = {}


def set_enabled(strategy: str, flag: bool) -> None:
    """[EL2.1.0] تفعيل/تعطيل استراتيجية حيًا (زر الإعدادات باللوحة/تلغرام) —
    الأعلام تنعكس فورًا على بوابات الدخول، والمثيلات تبقى جاهزة للإعادة."""
    if strategy not in STRATEGY_NAMES:
        raise ValueError(f"استراتيجية غير معروفة: {strategy}")
    with _lock:
        _enabled[strategy] = bool(flag)


def get_enabled(strategy: str) -> bool:
    with _lock:
        return bool(_enabled.get(strategy, strategy in _instances))


def attach_host(host: Dict[str, Any]) -> None:
    """حقن اعتماديات المضيف (vnz يبنيها عند الإقلاع — الاختبارات تبني بدائل).
    [EL2.3.0] مثيل التدفق يُبنى دائمًا (جاهز للتفعيل الحي من اللوحة)،
    علم البيئة SCALP_S1_ENABLED يحدد الحالة الابتدائية فقط."""
    global HOST
    HOST = dict(host or {})
    cfg = SCALP_CONFIG
    _instances.clear()
    _instances["SCALP_FLOW"] = FlowIgnition(cfg)
    with _lock:
        _enabled["SCALP_FLOW"] = S1_ENABLED
    _state["boot_at"] = time.time()


def _hf(key: str, *a, **kw):
    fn = HOST.get(key)
    if fn is None:
        return None
    try:
        return fn(*a, **kw)
    except Exception:
        lg = HOST.get("logger")
        if lg:
            lg.warning("[سكالب] فشل استدعاء المضيف %s", key, exc_info=True)
        return None


def _bump(strategy: str, key: str, sub: Optional[str] = None) -> None:
    with _lock:
        c = _counters.setdefault(strategy, {"signals": 0, "partials": 0, "early_exits": 0,
                                            "closes": {}, "rejects": {},
                                            "last_signal_at": None, "last_signal_symbol": None})
        if sub is None:
            c[key] = c.get(key, 0) + 1
        else:
            c[key] = c.setdefault(key, {})
            c[key][sub] = c[key].get(sub, 0) + 1


def _reject(strategy: str, reason: str) -> None:
    _bump(strategy, "rejects", reason)


def _log(level: str, msg: str, ntype: str) -> None:
    _hf("log_and_notify", level, msg, ntype)


# ─────────────────────────────────────────────────────────────────────────────
# الرموز والتبريد والمخاطر اليومية
# ─────────────────────────────────────────────────────────────────────────────

def resolve_symbols() -> List[str]:
    env = (os.getenv("SCALP_SYMBOLS", "") or "").strip()
    if env:
        out = []
        for s in env.split(","):
            s = s.strip().upper()
            if not s:
                continue
            if "/" not in s:
                s += "/USDT"
            out.append(s)
        return out[:16]
    wl = _hf("watchlist") or []
    usdt = [s for s in wl if str(s).upper().endswith("/USDT")]
    return usdt[: max(1, SCALP_CONFIG.symbols_n)]


def _cooldown_set(strategy: str, symbol: str, sec: Optional[float] = None) -> None:
    # [EL2.4.0] مدة اختيارية: تبريد إبطال الأوامر الارتدادية أقصر من تبريد الصفقات
    with _lock:
        dur = float(sec if sec is not None else SCALP_CONFIG.cooldown_sec)
        _cooldowns.setdefault(strategy, {})[symbol] = (time.time(), dur)


def _cooldown_left(strategy: str, symbol: str) -> float:
    with _lock:
        val = _cooldowns.get(strategy, {}).get(symbol, 0.0)
    ts, dur = (val if isinstance(val, tuple) else (float(val), SCALP_CONFIG.cooldown_sec))
    rem = dur - (time.time() - ts)
    return max(0.0, rem)


def _scalp_open_count(strategy: Optional[str] = None) -> int:
    if strategy:
        rows = _hf("db_query", "SELECT COUNT(*) AS n FROM signals WHERE status='open'"
                                " AND strategy_name=%s", (strategy,)) or []
    else:
        rows = _hf("db_query", "SELECT COUNT(*) AS n FROM signals WHERE status='open'"
                                " AND strategy_name IN ('SCALP_FLOW')") or []
    return int(rows[0]["n"]) if rows else 0


def _utc_day_prefix() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _daily_pnl(strategy: str) -> float:
    rows = _hf("db_query", "SELECT COALESCE(SUM(pnl_usdt),0) AS s FROM signals"
                            " WHERE strategy_name=%s AND status='closed' AND closed_at LIKE %s",
               (strategy, _utc_day_prefix() + "%")) or []
    try:
        return float(rows[0]["s"] or 0.0)
    except (IndexError, TypeError, ValueError):
        return 0.0


def _daily_loss_block(strategy: str) -> bool:
    """قاطع خسارة يومي لكل استراتيجية — نسبة من الرصيد الورقي (أو الحقيقي)."""
    cap_pct = SCALP_CONFIG.daily_loss_pct
    if cap_pct <= 0:
        return False
    base = _hf("real_free_usdt") if HOST.get("is_real_mode") and HOST["is_real_mode"]() \
        else _hf("get_paper_balance")
    if not base or base <= 0:
        return False
    return _daily_pnl(strategy) < -base * cap_pct / 100.0


# ─────────────────────────────────────────────────────────────────────────────
# بناء السياق — مرة واحدة لكل رمز/دورة وتشترك فيه الاستراتيجيتان
# ─────────────────────────────────────────────────────────────────────────────

def _build_ctx(symbol: str) -> Optional[ScalpContext]:
    cfg = SCALP_CONFIG
    now = time.time()
    rows: List[Dict[str, float]] = []
    src = "proxy"
    full = _hf("binance_full_klines", symbol, cfg.exec_tf, 160)
    if full:
        rows = ind.rows_from_full(full)
        src = "taker"
    if not rows:
        raw, _source = _hf("fetch_ohlcv_raw", symbol, cfg.exec_tf, 160) or (None, None)
        rows = ind.rows_from_basic(raw or [])
        src = "proxy"
    rows = ind.closed_rows(rows, cfg.tf_sec, now)
    if len(rows) < 60:
        return None
    _state["cvd_source_last"] = src

    k15: List[Dict[str, float]] = []
    raw15, _s15 = _hf("fetch_ohlcv_raw", symbol, "15m", 60) or (None, None)
    if raw15:
        k15 = ind.closed_rows(ind.rows_from_basic(raw15), 900, now)

    k1h: List[Dict[str, float]] = _k1h_rows(symbol, now)

    live = _hf("get_live_price", symbol)
    depth = _hf("binance_depth", symbol, 100) if HOST.get("binance_depth") else None

    highs = [float(r["high"]) for r in rows]
    lows = [float(r["low"]) for r in rows]
    closes = [float(r["close"]) for r in rows]
    a5 = ind.atr(highs, lows, closes, 14)
    a15 = ind.atr([float(r["high"]) for r in k15], [float(r["low"]) for r in k15],
                  [float(r["close"]) for r in k15], 14) if len(k15) >= 20 else None

    # تقارب فيبو المحرك — زيجزاج المحرك نفسه على إغلاقات 5m (اتساق مع استراتيجية الموجات)
    fib = None
    dev = HOST.get("deviation_threshold")
    zz = _hf("zigzag_pivots", closes, dev) if dev else None
    if zz and len(zz) >= 2:
        (i1, p1), (i2, p2) = zz[-2], zz[-1]
        if p2 > p1 and (i2 - i1) >= 3:
            fib = ind.fib_retrace_levels(p1, p2)   # ساق صاعد — تصحيحات 0.618/0.786

    return ScalpContext(symbol=symbol, now_ts=now, k5=rows, k15=k15, k1h=k1h,
                        live_price=live,
                        depth=depth, cvd_source=src, atr5=a5, atr15=a15,
                        fib_confluence=fib,
                        extra={"fee_rate": float(HOST.get("fee_rate") or 0.001)})


# [EL2.4.0] شموع 1h مع كاش TTL — انحياز الفريم الأعلى (G7) بلا ثقل REST:
# نداء واحد لكل رمز كل 10 دقائق بدل كل دورة مسح. الفشل = قائمة فارغة (fail-open
# في الاستراتيجية — لا تجميد للبوت عند عطل المزود).
_K1H_TTL_SEC = 600.0
_k1h_cache: Dict[str, Tuple[float, List[Dict[str, float]]]] = {}


def _k1h_rows(symbol: str, now: float) -> List[Dict[str, float]]:
    hit = _k1h_cache.get(symbol)
    if hit and (now - hit[0]) < _K1H_TTL_SEC:
        return hit[1]
    rows: List[Dict[str, float]] = []
    try:
        raw, _src = _hf("fetch_ohlcv_raw", symbol, "1h", 120) or (None, None)
        if raw:
            rows = ind.closed_rows(ind.rows_from_basic(raw), 3600, now)
    except Exception:
        rows = []
    _k1h_cache[symbol] = (now, rows)
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# بوابات الدخول المشتركة — قبل evaluate وبعده
# ─────────────────────────────────────────────────────────────────────────────

def _entry_gates(strategy: str, symbol: str) -> Tuple[bool, str]:
    if not SCALP_ENABLED:
        return False, "معطل"
    if strategy not in _instances:
        return False, "استراتيجية غير مثبتة"
    if not get_enabled(strategy):
        return False, "معطلة من الإعدادات"   # [EL2.1.0] زر الإعدادات — بلا إشارات جديدة
    if not (_hf("is_trading_enabled") or False):
        return False, "زر التداول معطل"
    blk = _hf("risk_entry_block_reason")
    if blk:
        return False, f"قاطع مخاطر المحرك: {blk}"
    if _scalp_open_count() >= SCALP_CONFIG.max_total_open:
        return False, "سقف صفقات السكالب المفتوحة"
    if _scalp_open_count(strategy) >= SCALP_CONFIG.max_open_per_strategy:
        return False, "سقف صفقات الاستراتيجية"
    if _hf("symbol_has_active", symbol):
        return False, "صفقة نشطة على الرمز (محرك أو سكالب)"
    if _cooldown_left(strategy, symbol) > 0:
        return False, "تبريد الرمز بعد صفقة سابقة"
    if _daily_loss_block(strategy):
        return False, "قاطع خسارة اليوم لهذه الاستراتيجية"
    return True, ""


def _size_position(entry: float, sl: float) -> Tuple[Optional[float], Optional[float], str]:
    """الحجم: مخاطرة SCALP_RISK_PCT من الرصيد بوقف ATR — مقيدة بسقف قيمة صارم
    (درس FE1.7.0: الوقف الضيق × المخاطرة = رافعة ضمنية ممنوعة)."""
    cfg = SCALP_CONFIG
    risk_per_unit = entry - sl
    if risk_per_unit <= 0 or entry <= 0:
        return None, None, "هندسة وقف غير منطقية"
    if HOST.get("is_real_mode") and HOST["is_real_mode"]():
        base = float(_hf("real_free_usdt") or 0)
        if base <= 0:
            return None, None, "رصيد حقيقي غير مقروء"
        cap = min(cfg.max_notional_usdt, base * cfg.max_notional_pct / 100.0,
                  float(_hf("real_max_notional") or cfg.max_notional_usdt))
        quote = min(cap, base * cfg.risk_pct / 100.0 / risk_per_unit * entry)
        quote = min(quote, cap)
        if quote < max(cfg.min_notional, 5.0):
            return None, None, "قيمة حقيقية دون حدود باينانس"
        return quote, quote, ""          # في الحقيقي نمرر quoteOrderQty لا كمية
    base = float(_hf("get_paper_balance") or 0)
    if base <= 0:
        return None, None, "رصيد ورقي غير متاح"
    risk_usdt = base * cfg.risk_pct / 100.0
    qty = risk_usdt / risk_per_unit
    notional = qty * entry
    cap = min(base * cfg.max_notional_pct / 100.0, cfg.max_notional_usdt)
    if notional > cap:
        qty = cap / entry
        notional = qty * entry
    if notional < cfg.min_notional:
        return None, None, "قيمة صفقة أقل من الحد الأدنى"
    return qty, notional, ""


def _open_position(sig: ScalpSignal, fill_price: Optional[float] = None) -> bool:
    """فتح صفقة سكالب — ورقي: ملء فوري بسعر حي. حقيقي: شراء سوق quoteOrderQty
    + وقف راكن على المنصة (الحماية تعيش على باينانس لا في الذاكرة).
    [EL2.4.0] fill_price: ملء أمر ارتدادي محدد — ورقي حصرًا، السعر الفعلي عند
    اللمس المؤكد، ويحمل حارس الملاحقة لأن البعد عن إغلاق القرار هو المقصود."""
    cfg = SCALP_CONFIG
    real = bool(HOST.get("is_real_mode") and HOST["is_real_mode"]())
    if fill_price is not None:
        if real:
            # [EL2.4.1][F3] ملء ارتدادي حقيقي: حارس بدل ملاحقة القديم — لا شراء إن ابتعد
            # السعر عن الحد أو كسر الوقف المرجعي (تفادي الشراء في الومضة أو فوق مقبرة الوقف)
            live = _hf("get_live_price", sig.symbol)
            atr_ref = float(sig.meta.get("atr5") or 0)
            tol = cfg.entry_chase_atr * (atr_ref if atr_ref > 0 else float(fill_price))
            if live is None or float(live) <= float(sig.sl) or (float(live) - float(fill_price)) > tol:
                _reject(sig.strategy, "ملء ارتدادي حقيقي: السعر ابتعد أو كسر الوقف")
                return False
            fill = float(live)
        else:
            fill = float(fill_price)
    else:
        fill = _hf("get_live_price", sig.symbol) or sig.entry_ref
        # حارس الملاحقة: الابتعاد عن إغلاق القرار بحدّ ATR يعني أن الفرصة راحت — لا دخول
        atr_ref = float(sig.meta.get("atr5") or 0)
        chase_tol = cfg.entry_chase_atr * (atr_ref if atr_ref > 0 else sig.entry_ref)
        if abs(fill - sig.entry_ref) > chase_tol:
            _reject(sig.strategy, "السعر ابتعد عن إغلاق القرار")
            return False
    order_id = None
    if real:
        ex = _hf("binance_trade_exchange")
        if ex is None:
            _reject(sig.strategy, "مفاتيح باينانس غائبة")
            return False
        quote, _n, why = _size_position(fill, sig.sl)
        if not quote:
            _reject(sig.strategy, why)
            return False
        mkt = _hf("real_market_rules", sig.symbol, ex)
        if _hf("real_min_cost", mkt) and quote < _hf("real_min_cost", mkt):
            _reject(sig.strategy, "دون أدنى قيمة باينانس")
            return False
        order = _hf("real_market_buy", sig.symbol, quote)
        if not order:
            _reject(sig.strategy, "فشل أمر الشراء الحقيقي")
            return False
        order_id = str(order.get("id") or "") or None
        fill = float(order.get("average") or order.get("price") or fill)
        notional = quote
        qty = float(order.get("amount") or (notional / fill))
        qty = _hf("real_adjust_amount", ex, sig.symbol, qty) or qty
        stop = _hf("place_real_stop_loss", sig.symbol, qty, sig.sl)
        sig.meta["stop_order_id"] = str((stop or {}).get("id") or "") or None
    else:
        qty, notional, why = _size_position(fill, sig.sl)
        if not qty:
            _reject(sig.strategy, why)
            return False

    meta = dict(sig.meta)
    meta.update({"fill": fill, "partial_done": False, "be_done": False,
                 "opened_by": "scalp_manager", "max_hold_min": cfg.max_hold_min})
    if fill_price is not None:
        meta["retrace_fill"] = True   # [EL2.4.0] أصل الملء: أمر ارتدادي مؤكد
    now_iso = _hf("utc_now_iso") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    _hf("db_execute",
        "INSERT INTO signals (symbol, direction, strategy_name, status, entry_price, fill_price,"
        " stop_loss, take_profit, tp1, tp2, quantity, notional_usdt, rr_ratio, meta_json,"
        " created_at, filled_at, initial_quantity, is_real, peak_price)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (sig.symbol, "BULLISH", sig.strategy, "open", sig.entry_ref, fill, sig.sl, sig.tp2,
         sig.tp1, sig.tp2, qty, notional, sig.rr1, json.dumps(meta, ensure_ascii=False),
         now_iso, now_iso, qty, 1 if real else 0, fill))
    _bump(sig.strategy, "signals")
    with _lock:
        _counters[sig.strategy]["last_signal_at"] = now_iso
        _counters[sig.strategy]["last_signal_symbol"] = sig.symbol
    mode = "حقيقية 🔴" if real else "ورقية"
    fp = HOST.get("fmt_price") or (lambda p: f"{p:.6g}")
    _log("info",
         f"⚡ سكالب مفتوح ({sig.label}) {mode}: {sig.symbol} عند {fp(fill)}\n"
         f"وقف: {fp(sig.sl)} | هدف 1: {fp(sig.tp1)} (جزئي {cfg.partial_pct:.0f}% + BE) | هدف 2: {fp(sig.tp2)}\n"
         f"R:R صافي حتى الهدف 1: {sig.rr1:.2f} — {sig.reason}",
         "SCALP_OPEN")
    return True


# ─────────────────────────────────────────────────────────────────────────────────
# [EL2.4.0] الأوامر الارتدادية المؤكدة — «لا مطاردة شمعة الانفجار»
# درس الباك تاست BT-LAB (45 يومًا): الشراء عند إغلاق شمعة الاندلاع كان يشتري
# قمة الدفعة — 73% وقفات. الأمر المحدد بعمق 0.6×ATR مع ملء بشمعة رفض مؤكدة
# (لمست الحد وأغلقت فوقه) قلب السكالب من PF 0.24 إلى 2.05. نفس المنطق حرفيًا:
#   إبطال: إغلاق شمعة 5m تحت الوقف المرجعي | انتهاء الصلاحية (8 شموع)
#   ملء: low ≤ الحد AND close ≥ الحد → fill = min(الحد، الفتح)
#   بوابات الملء تُعاد لحظة التنفيذ (السقوف والقاطع والمشغول قد تغيّروا)
# ─────────────────────────────────────────────────────────────────────────────────

_retrace_orders: Dict[str, Dict[str, Any]] = {}   # symbol → أمر ارتدادي معلق (ورقي)


def retrace_pending() -> Dict[str, Dict[str, Any]]:
    """لقطة قراءة للأوامر الارتدادية المعلقة (للعرض في اللوحة/API)."""
    with _lock:
        return json.loads(json.dumps(_retrace_orders))


def _arm_retrace(sig: ScalpSignal) -> bool:
    """تسلّح أمر ارتدادي بدل الشراء الفوري (ورقي). فشل التسلّح = المسار القديم."""
    cfg = SCALP_CONFIG
    atr5 = float(sig.meta.get("atr5") or 0)
    if atr5 <= 0:
        return _open_position(sig)            # بلا ATR — المسار القديم (fail-open)
    limit = float(sig.entry_ref) - cfg.retrace_atr * atr5
    if limit <= 0 or limit <= float(sig.sl):
        return _open_position(sig)            # عمق غير منطقي — المسار القديم
    with _lock:
        _retrace_orders[sig.symbol] = {
            "strategy": sig.strategy, "label": sig.label, "symbol": sig.symbol,
            "limit": limit, "sl_ref": float(sig.sl), "tp1": float(sig.tp1),
            "tp2": float(sig.tp2), "rr1": float(sig.rr1 or 0.0),
            "entry_ref": float(sig.entry_ref), "atr5": atr5,
            "reason": sig.reason, "armed_ts": time.time(),
            "expires_ts": time.time() + cfg.retrace_expiry * cfg.tf_sec,
            "meta": dict(sig.meta),
        }
    _bump(sig.strategy, "retrace_born")
    fp = HOST.get("fmt_price") or (lambda p: f"{p:.6g}")
    _log("info",
         f"⏳ أمر ارتدادي ({sig.label}): {sig.symbol} حد {fp(limit)} "
         f"(عمق {cfg.retrace_atr}×ATR تحت {fp(sig.entry_ref)}) — صلاحية "
         f"{cfg.retrace_expiry} شمعة 5m، الملء بشمعة رفض مؤكدة فقط",
         "SCALP_RETRACE")
    return True


def _manage_retrace(sym: str, ctx: ScalpContext) -> None:
    """إدارة الأمر الارتدادي على شمعة 5m مغلقة — نفس منطق المختبر حرفيًا."""
    cfg = SCALP_CONFIG
    od = _retrace_orders.get(sym)
    if od is None or not ctx.k5:
        return
    c = ctx.k5[-1]
    lo, op, close = float(c["low"]), float(c["open"]), float(c["close"])
    now = time.time()
    # 1) الإبطال — الفرضية ماتت (إغلاق تحت الوقف المرجعي)
    if close < od["sl_ref"]:
        _retrace_orders.pop(sym, None)
        _cooldown_set(od["strategy"], sym, cfg.cancel_cooldown_sec)
        _bump(od["strategy"], "retrace_cancelled")
        return
    # 2) انتهاء الصلاحية
    if now > od["expires_ts"]:
        _retrace_orders.pop(sym, None)
        _cooldown_set(od["strategy"], sym, cfg.cancel_cooldown_sec)
        _bump(od["strategy"], "retrace_expired")
        return
    # 3) الملء بشمعة رفض مؤكدة: لمست الحد وأغلقت فوقه (مضاد السكاكين الساقطة)
    if lo > od["limit"] or close < od["limit"]:
        return
    fill = min(od["limit"], op)               # فجوة تحت الحد = ملء بالفتح (أفضل)
    # بوابات إعادة الفحص لحظة الملء — [EL2.4.1][F3] نفس بوابات الدخول كاملةً:
    # زر التداول وقاطع المخاطر ومفتاح الاستراتيجية والسقوف والمشغول والتبريد والقاطع اليومي.
    # لا تعارض مع التبريد لأنه لا يُضبط عند التسلح.
    ok, why = _entry_gates(od["strategy"], sym)
    if not ok:
        _retrace_orders.pop(sym, None)
        _cooldown_set(od["strategy"], sym, cfg.cancel_cooldown_sec)
        _reject(od["strategy"], f"ملء ارتدادي أُسقط: {why}")
        return
    _retrace_orders.pop(sym, None)
    _bump(od["strategy"], "retrace_filled")
    sig = ScalpSignal(strategy=od["strategy"], label=od["label"], symbol=sym,
                      entry_ref=od["entry_ref"], sl=od["sl_ref"], tp1=od["tp1"],
                      tp2=od["tp2"], rr1=od["rr1"], reason=od["reason"],
                      meta=dict(od["meta"]))
    _open_position(sig, fill_price=fill)


# ─────────────────────────────────────────────────────────────────────────────
# دورة المسح — بعد إغلاق كل شمعة 5m
# ─────────────────────────────────────────────────────────────────────────────

def _scan_cycle() -> Dict[str, int]:
    cfg = SCALP_CONFIG
    stats = {"symbols": 0, "ctx_fail": 0, "signals": 0}
    if not SCALP_ENABLED or not _instances:
        return stats
    _early_exits_all()
    for sym in resolve_symbols():
        stats["symbols"] += 1
        try:
            ctx = _build_ctx(sym)
        except Exception:
            stats["ctx_fail"] += 1
            continue
        if ctx is None:
            stats["ctx_fail"] += 1
            continue
        # [EL2.4.0] الأوامر الارتدادية أولًا (ملء/إبطال/انتهاء) — والمعلق يحتكر الرمز
        if sym in _retrace_orders:
            _manage_retrace(sym, ctx)
            if sym in _retrace_orders:          # ما زال معلقًا — لا تقييم جديد عليه
                continue
        for name, strat in list(_instances.items()):
            ok, why = _entry_gates(name, sym)
            if not ok:
                _reject(name, why)
                continue
            try:
                sig = strat.evaluate(ctx)
            except Exception:
                lg = HOST.get("logger")
                if lg:
                    lg.exception("[سكالب] تقييم %s على %s فشل", name, sym)
                continue
            if not sig:
                continue
            if not sig.side == "LONG":            # حارس سبوت صريح
                _reject(name, "سبوت: لا بيع مكشوف")
                continue
            # [EL2.4.0] لا مطاردة شمعة الانفجار — أمر ارتدادي بدل الشراء الفوري
            # [EL2.4.1][F3] الوضع الحقيقي يسلّح أيضًا (SCALP_REAL_RETRACE=1) — توحيد السلوك
            real_mode = bool(HOST.get("is_real_mode") and HOST["is_real_mode"]())
            if cfg.retrace_atr > 0 and (not real_mode or SCALP_REAL_RETRACE):
                if _arm_retrace(sig):
                    stats["signals"] += 1
                    break                         # رمز واحد = أمر واحد بالدورة
            if _open_position(sig):
                stats["signals"] += 1
                break                             # رمز واحد = صفقة سكالب واحدة بالدورة
    with _lock:
        _state["last_scan_at"] = _hf("utc_now_iso")
        _state["last_scan_ts"] = time.time()
        _state["cycles"] += 1
    return stats


def _early_exits_all() -> None:
    """خروج مبكر على شموع مغلقة (تفشل البنية/الدلتا) — بيانات الدورة نفسها.
    [EL2.3.0] قاعدة واحدة للباقي الوحيد: انقلاب الدلتا (CVD) ضد الاتجاه
    مع كسر SuperTrend = الموجة القصيرة ماتت — خروج فوري."""
    rows = _hf("db_query", "SELECT * FROM signals WHERE status='open'"
                            " AND strategy_name IN ('SCALP_FLOW') ORDER BY id ASC") or []
    if not rows:
        return
    by_sym: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_sym.setdefault(r["symbol"], []).append(r)
    for sym, srows in by_sym.items():
        ctx = None
        try:
            ctx = _build_ctx(sym)
        except Exception:
            ctx = None
        if ctx is None or not ctx.k5:
            continue
        closes = [float(r["close"]) for r in ctx.k5]
        cv = ind.cvd_series(ctx.k5)
        for sig in srows:
            try:
                name = sig["strategy_name"]
                meta = _sig_meta(sig)
                if name == "SCALP_FLOW":
                    st = ind.supertrend([float(r["high"]) for r in ctx.k5],
                                        [float(r["low"]) for r in ctx.k5], closes, 10, 2.5)
                    if cv and st and cv["cvd"][-1] < cv["ema"][-1] and closes[-1] < st["line"]:
                        _close_position(sig, closes[-1], "انقلاب الدلتا (CVD) ضد الاتجاه مع كسر SuperTrend", "early")
                        _bump(name, "early_exits")
                        continue
                # مهلة الصفقة — شبكة أمان مزدوجة مع المراقبة
                hold_min = int(meta.get("max_hold_override") or 0) or SCALP_CONFIG.max_hold_min
                created = str(sig.get("created_at") or "")
                if created:
                    try:
                        t0 = datetime.strptime(created[:19], "%Y-%m-%dT%H:%M:%S")
                        age_min = (datetime.now(timezone.utc).replace(tzinfo=None) - t0).total_seconds() / 60.0
                        if age_min > hold_min:
                            _close_position(sig, closes[-1], f"مهلة السكالب انتهت ({hold_min} دقيقة)", "time")
                    except ValueError:
                        pass
            except Exception:
                lg = HOST.get("logger")
                if lg:
                    lg.exception("[سكالب] خروج مبكر %s فشل", sig.get("symbol"))


def _sig_meta(sig: Dict[str, Any]) -> Dict[str, Any]:
    raw = sig.get("meta_json")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


def drain_legacy_strategies() -> int:
    """[EL2.3.0] تسوية الصفوف المفتوحة للاستراتيجيات المزالة (إن وُجدت) — لا يُترك
    مركز يتيمًا بلا مراقبة: يُغلق كل صف مفتوح بسعر حي أو سعر الملء مع سبب صادق.
    تُستدعى مرة واحدة عند الإقلاع قبل بدء الخيوط. يعيد عدد الصفوف المسوّاة
    (صفر في الحالة الطبيعية)."""
    legacy_csv = ",".join(f"'{n}'" for n in LEGACY_STRATEGIES)
    rows = _hf("db_query", f"SELECT * FROM signals WHERE status='open'"
                           f" AND strategy_name IN ({legacy_csv}) ORDER BY id ASC") or []
    n = 0
    for sig in rows:
        try:
            live = _hf("get_live_price", sig["symbol"])
            price = float(live or sig.get("fill_price") or sig.get("entry_price") or 0)
            if price <= 0:
                continue
            _close_position(sig, price,
                            "إزالة الاستراتيجية من النظام (قرار الحاكم) — تسوية مركز قديم",
                            "other")
            n += 1
        except Exception:
            lg = HOST.get("logger")
            if lg:
                lg.exception("[سكالب] تسوية صف قديم %s فشلت", sig.get("symbol"))
    if n:
        _log("info", f"◈ تمت تسوية {n} صفقة قديمة من استراتيجيات مزالة — "
                     f"النظام الآن: موجات إليوت (بفلتر التدفق) + التدفق", "SCALP_CLOSE")
    return n


# الاسم التاريخي — ورد في إصدارات سابقة ومستندات التشغيل (EL2.2.0)
drain_legacy_profile = drain_legacy_strategies


# ─────────────────────────────────────────────────────────────────────────────
# دورة المراقبة — كل 20 ثانية: وقف-أولًا + جزئي + BE + الهدف الثاني
# ─────────────────────────────────────────────────────────────────────────────

def _close_position(sig: Dict[str, Any], price: float, reason: str, klass: str = "other") -> None:
    real = bool(HOST.get("is_real_mode") and HOST["is_real_mode"]() and sig.get("is_real"))
    if real:
        _hf("close_real_trade", sig, price, reason)
    else:
        _hf("close_signal_row", sig, price, reason)
    _ext_forget(sig["id"])   # [EL2.4.1][F2] نهاية دورة الحياة — مسح حالة الحدود
    _cooldown_set(sig["strategy_name"], sig["symbol"])
    _bump(sig["strategy_name"], "closes", klass)


def _partial_close(sig: Dict[str, Any], price: float) -> bool:
    """جني جزئي SCALP_PARTIAL_PCT من المتبقي عند TP1 — ورقي: محاسبة مباشرة،
    حقيقي: بيع سوق فعلًا ثم المحاسبة، والغبار يُعتبر منجزًا (عقيدة المحرك)."""
    cfg = SCALP_CONFIG
    qty_now = float(sig.get("quantity") or 0)
    leg = qty_now * cfg.partial_pct / 100.0
    real = bool(HOST.get("is_real_mode") and HOST["is_real_mode"]() and sig.get("is_real"))
    if real:
        ex = _hf("binance_trade_exchange")
        leg = _hf("real_adjust_amount", ex, sig["symbol"], leg) or 0.0
        if leg <= 0:
            return False
        order = _hf("place_real_market_sell", sig["symbol"], leg)
        if not order:
            return False
        fill_leg = float(order.get("average") or price)
        _hf("account_partial_close", sig, leg, fill_leg, "هدف سكالب الأول (جزئي حقيقي)")
    else:
        if leg <= 0:
            return False
        _hf("account_partial_close", sig, leg, price, "هدف سكالب الأول (جزئي ورقي)")
    _bump(sig["strategy_name"], "partials")
    return True


def _monitor_cycle() -> Dict[str, int]:
    cfg = SCALP_CONFIG
    stats = {"open": 0, "sl": 0, "partial": 0, "tp2": 0}
    rows = _hf("db_query", "SELECT * FROM signals WHERE status='open'"
                            " AND strategy_name IN ('SCALP_FLOW') ORDER BY id ASC") or []
    for sig in rows:
        sym = sig["symbol"]
        try:
            live = _hf("get_live_price", sym)
            if live is None:
                live = float(sig.get("fill_price") or 0)
            if live <= 0:
                continue
            df = _hf("get_recent_candles", sym, SCALP_CONFIG.exec_tf, 2, 1)
            # [EL2.4.1][F2] الحدود منذ لحظة الملء/آخر تسليح — حدّا الشمعة الجارية لا
            # يُحسبان إن فُتحت قبل الحدث (لا وقف مبكر ولا هدف بسعر سبق الدخول)
            meta = _sig_meta(sig)
            since_ts = max(_iso_epoch(sig.get("filled_at")), float(meta.get("armed_at") or 0.0))
            key = ("o", sig["id"])
            last = df.iloc[-1] if (df is not None and not df.empty) else None
            st = ind.merge_extremes(_EXT_STATE.get(key), since_ts, live,
                                    ind.candle_open_epoch(last) if last is not None else None,
                                    float(last["high"]) if last is not None else None,
                                    float(last["low"]) if last is not None else None)
            _EXT_STATE[key] = st
            high_now = st["hi"] if st["hi"] is not None else live
            low_now = st["lo"] if st["lo"] is not None else live
            stats["open"] += 1
            # تتبع القمة (يُعرض في اللوحة)
            peak = max(float(sig.get("peak_price") or live), high_now)
            if abs(peak - float(sig.get("peak_price") or 0)) > 1e-12:
                _hf("db_execute", "UPDATE signals SET peak_price=%s WHERE id=%s", (peak, sig["id"]))
            # 1) الوقف أولًا — دائمًا قبل أي ربح (عقيدة محمية لا تكسر)
            sl_now = float(sig.get("stop_loss") or 0)
            if sl_now > 0 and low_now <= sl_now:
                # [EL2.2.0] سبب الوقف الصادق لكل استراتيجية — تحليل الأداء يتطلب صدق التصنيف
                sl_reason = SL_REASONS.get(sig.get("strategy_name"),
                                           f"وقف سكالب ({sig.get('strategy_name')})")
                _close_position(sig, sl_now, sl_reason, "sl")
                stats["sl"] += 1
                continue
            # 2) الجزئي عند TP1 + نقل الوقف لنقطة الدخول (BE) — مرة واحدة
            tp1 = float(sig.get("tp1") or 0)
            fill = float(sig.get("fill_price") or 0)
            if tp1 > 0 and not meta.get("partial_done") and high_now >= tp1:
                if _partial_close(sig, tp1):
                    meta["partial_done"] = True
                    meta["be_done"] = True
                    # BE نقي: الوقف لنقطة الدخول — المتبقي يطير نحو TP2 بلا مخاطرة
                    # (عقيدة محمية: أي قفل أبكر من BE يقطع العداء نحو الهدف الثاني)
                    # [EL2.4.1][F2] تسليح الحدود: armed_at مع نقل الوقف في UPDATE واحد
                    meta["armed_at"] = time.time()
                    _hf("db_execute", "UPDATE signals SET stop_loss=%s, meta_json=%s WHERE id=%s",
                        (fill, json.dumps(meta, ensure_ascii=False), sig["id"]))
                    sig["stop_loss"] = fill
                    if sig.get("is_real"):
                        _hf("replace_real_stop", sig, fill)
                    stats["partial"] += 1
                else:
                    meta["partial_done"] = True   # غبار/فشل بيع — لا نعيد المحاولة للأبد
                    _hf("db_execute", "UPDATE signals SET meta_json=%s WHERE id=%s",
                        (json.dumps(meta, ensure_ascii=False), sig["id"]))
            # 3) الهدف الثاني — إغلاق المتبقي
            tp2 = float(sig.get("take_profit") or 0)
            if tp2 > 0 and high_now >= tp2:
                _close_position(sig, tp2, "هدف سكالب الثاني (نهاية الموجة القصيرة)", "tp")
                stats["tp2"] += 1
                continue
            # 2b) [EL2.4.0] تتبع القمة بعد الجزئي+BE — درس BT-LAB (S12: PF 1.53→1.69):
            # المتبقي بعد BE يتبع chandelier قمة الصفقة ناقص trail_atr×ATR5 — يصعد
            # الوقف مع الصعود ويقطع الانعكاسات أبكر من انتظار TP2 أو المهلة.
            # ورقي حصرًا — الحقيقي وقفه راكن على المنصة وتعديله المتكرر مخاطرة تنفيذ.
            trail_atr = float(cfg.trail_atr or 0)
            if trail_atr > 0 and meta.get("be_done") and not sig.get("is_real"):
                atr5_m = float(meta.get("atr5") or 0)
                if atr5_m > 0:
                    new_sl = peak - trail_atr * atr5_m
                    if new_sl > 0 and new_sl > float(sig.get("stop_loss") or 0) and new_sl < live:
                        # [EL2.4.1][F2] تسليح الحدود مع كل رفع تتبع — UPDATE واحد للوقف والحالة
                        meta["armed_at"] = time.time()
                        _hf("db_execute", "UPDATE signals SET stop_loss=%s, meta_json=%s WHERE id=%s",
                            (new_sl, json.dumps(meta, ensure_ascii=False), sig["id"]))
                        sig["stop_loss"] = new_sl
            # 4) مهلة الصفقة — [EL2.2.0] مهلة خاصة عبر meta (max_hold_override) عند وجودها
            hold_min = int(meta.get("max_hold_override") or 0) or SCALP_CONFIG.max_hold_min
            created = str(sig.get("created_at") or "")
            if created:
                try:
                    t0 = datetime.strptime(created[:19], "%Y-%m-%dT%H:%M:%S")
                    age_min = (datetime.now(timezone.utc).replace(tzinfo=None) - t0).total_seconds() / 60.0
                    if age_min > hold_min:
                        _close_position(sig, live, f"مهلة السكالب انتهت ({hold_min} دقيقة)", "time")
                except ValueError:
                    pass
        except Exception:
            lg = HOST.get("logger")
            if lg:
                lg.exception("[سكالب] مراقبة %s فشلت", sym)
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# الحلقات والانطلاق
# ─────────────────────────────────────────────────────────────────────────────

def _scan_loop() -> None:
    lg = HOST.get("logger")
    time.sleep(30)   # إحماء — لا مسح قبل اكتمال إقلاع المضيف
    while True:
        try:
            s = _scan_cycle()
            if lg and s.get("signals"):
                lg.info("[سكالب] دورة مسح: %s", s)
        except Exception as exc:
            with _lock:
                _state["last_error"] = str(exc)[:200]
            if lg:
                lg.exception("استثناء في حلقة مسح السكالب: %s", exc)
        nap = 300.0
        try:
            nap = float(_hf("seconds_until_next_candle", SCALP_CONFIG.exec_tf) or 300.0) + 4.0
        except Exception:
            pass
        time.sleep(max(20.0, min(nap, 3700.0)))


def _monitor_loop() -> None:
    lg = HOST.get("logger")
    time.sleep(25)
    while True:
        try:
            _monitor_cycle()
        except Exception as exc:
            if lg:
                lg.exception("استثناء في حلقة مراقبة السكالب: %s", exc)
        time.sleep(20)


def start() -> None:
    """إقلاع خيوط السكالب — يُستدعى من initialize_bot_services بعد إقلاع بقية الخدمات."""
    global _started
    with _lock:
        if _started:
            return
        if not SCALP_ENABLED:
            HOST.get("logger") and HOST["logger"].info("[سكالب] معطل (SCALP_ENABLED=0)")
            return
        if not _instances:
            HOST.get("logger") and HOST["logger"].info("[سكالب] لا استراتيجية مثبتة — لا إقلاع")
            return
        if not any(_enabled.values()):
            HOST.get("logger") and HOST["logger"].info("[سكالب] كل الاستراتيجيات معطلة من الإعدادات — الخيوط تنطلق للمراقبة فقط")
        _started = True
        _state["boot_at"] = time.time()
    threading.Thread(target=_scan_loop, daemon=True, name="scalp-scan").start()
    threading.Thread(target=_monitor_loop, daemon=True, name="scalp-monitor").start()
    lg = HOST.get("logger")
    if lg:
        lg.info("[سكالب] مدير الاستراتيجيات المتوازية انطلق — %s",
                " + ".join(_instances.keys()))


def running() -> bool:
    return _started


# ─────────────────────────────────────────────────────────────────────────────
# لقطة الحالة — /api/scalp و/health
# ─────────────────────────────────────────────────────────────────────────────

def snapshot() -> Dict[str, Any]:
    with _lock:
        st = dict(_state)
        counters = {n: dict(c) for n, c in _counters.items()}
    st["last_scan_age"] = (round(time.time() - st.get("last_scan_ts", 0.0), 1)
                            if st.get("last_scan_ts") else None)
    cfg = SCALP_CONFIG
    strategies = {}
    for name, inst in _instances.items():
        strategies[name] = {
            "label": getattr(inst, "label", name),
            "enabled": bool(_enabled.get(name, True)),   # [EL2.1.0] الحالة الحقيقية من أعلام الإعدادات
            "open_n": _scalp_open_count(name),
            "signals": counters.get(name, {}).get("signals", 0),
            "partials": counters.get(name, {}).get("partials", 0),
            "early_exits": counters.get(name, {}).get("early_exits", 0),
            "closes": counters.get(name, {}).get("closes", {}),
            "rejects": counters.get(name, {}).get("rejects", {}),
            "daily_pnl": round(_daily_pnl(name), 4),
            "daily_loss_block": _daily_loss_block(name),
            "cooldowns": {s: round(_cooldown_left(name, s), 1)
                          for s, ts in _cooldowns.get(name, {}).items()
                          if _cooldown_left(name, s) > 0},
            "last_signal_at": counters.get(name, {}).get("last_signal_at"),
            "last_signal_symbol": counters.get(name, {}).get("last_signal_symbol"),
        }
    return {
        "enabled": SCALP_ENABLED and any(_enabled.values()),
        "running": _started,
        "exec_tf": cfg.exec_tf,
        "symbols": resolve_symbols(),
        "config": {
            "risk_pct": cfg.risk_pct, "max_total_open": cfg.max_total_open,
            "max_notional_usdt": cfg.max_notional_usdt,
            "max_notional_pct": cfg.max_notional_pct,
            "cooldown_sec": cfg.cooldown_sec, "daily_loss_pct": cfg.daily_loss_pct,
            "max_hold_min": cfg.max_hold_min, "partial_pct": cfg.partial_pct,
            "rr_net_min": cfg.rr_net_min,
        },
        "state": {"cycles": st.get("cycles", 0), "last_scan_at": st.get("last_scan_at"),
                  "last_scan_age": st.get("last_scan_age"),
                  "last_error": st.get("last_error", ""), "cvd_source_last": st.get("cvd_source_last", "")},
        "strategies": strategies,
    }


scalp_manager = {
    "attach_host": attach_host,
    "start": start,
    "snapshot": snapshot,
    "set_enabled": set_enabled,      # [EL2.1.0] تفعيل/تعطيل حي — زر الإعدادات
    "get_enabled": get_enabled,
    "running": running,
    "scan_cycle": _scan_cycle,
    "monitor_cycle": _monitor_cycle,
    "build_ctx": _build_ctx,
    "entry_gates": _entry_gates,
    "size_position": _size_position,
    "open_position": _open_position,
    "close_position": _close_position,
    "partial_close": _partial_close,
    "cooldown_set": _cooldown_set,
    "cooldown_left": _cooldown_left,
    "daily_pnl": _daily_pnl,
    "daily_loss_block": _daily_loss_block,
    "resolve_symbols": resolve_symbols,
    "sig_meta": _sig_meta,
    "drain_legacy_profile": drain_legacy_strategies,   # [EL2.3.0] اسم تاريخي — تسوية صفوف المزالة
    "drain_legacy_strategies": drain_legacy_strategies,   # [EL2.3.0] الاسم الحقيقي
    "config": SCALP_CONFIG,
    "instances": _instances,
    "counters": _counters,
    "state": _state,
}
