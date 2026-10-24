#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""باك تاست EL2 — إعادة تشغيل الاستراتيجيتين الحيتين على بيانات تاريخية حقيقية
===============================================================================
[BT1.0.0] طلب الحاكم: «الان اريد اختبار البوت باك تاست ارني الطريقة»

المنهجية — «كود الإنتاج نفسه، لا إعادة اختراع»:
  • استراتيجية SCALP_FLOW (انجلال التدفق) تُقيَّم بكود الإنتاج الحقيقي
    (strategies/flow_ignition.py + strategies/indicators.py) شمعة-بشمعة.
  • استراتيجية Elliott_Fibonacci تُكتشف بكود الإنتاج الحقيقي
    (engine/pattern_detector.py — نفس DetectorConfig) وتُدار بفلتر التدفق الحقيقي
    (strategies/flow_filter.py — بوابات F1..F4).
  • كل بوابة وحماية من vnz.py + render.yaml (الإنتاج) منقولة هنا حرفيًا بأرقام
    أسطرها: المطاردة 1.5%، تقادم البنية 36 شمعة، premise-alive، التصحيح العميق
    78.6%، سلّم الأهداف مع سقف الأسبوع والمراحل، rr_net ≥ 0.3، وقف-أولًا intrabar،
    جزئي 50% + BE@1R (سكالب) وجزئي 50% + BE@1R (محرك)، مراحل 40%، التبريد 90د
    (محرك) و45د (سكالب)، سقوف الفتح 5 (محرك) و2 (سكالب)، العنقود 3، قاطع الخسارة
    اليومي 5% (محرك) و0.6% (سكالب)، الحجم بمخاطرة 1% و0.75% بسقوف 30% و1200$.

بلا نظرة مستقبلية (no lookahead) — ثلاثة عقد صارمة:
  1) القرار عند إغلاق الشمعة فقط: كل النوافذ تنتهي بآخر شمعة مغلقة.
  2) ملء السكالب عند سعر إغلاق شمعة القرار (كما يملأ البوت لحظتها) — والمطاردة
     داخل evaluate محفوظة. أمر الموجات المعلق يُملأ عند لمس منطقة الدخول.
  3) الوقف أولًا داخل الشمعة: إن لمست الشمعة الوقف والهدف معًا فالوقف يفوز
     (عقيدة المحرك المحمية — نفترض أسوأ ترتيب داخلي).

فروق صادقة عن الحي (مُعلنة لا مخفية):
  • دفتر الأوامر (جدران السيولة لهدف SCALP_FLOW الثاني) غير متاح تاريخيًا —
    يُمرر depth=None فيقع الكود في المسار الافتراضي 2.2×ATR (مسار الحي نفسه
    عند غياب الدفتر).
  • السعر الحي = إغلاق شمعة القرار (فارق ثوانٍ في الحي) — بلا انزلاق نموذجي.
  • رسوم التيكر 0.1% لكل اتجاه (FEE_RATE الإنتاج) — لا انزلاق.

الاستخدام:
  python3 backtest_el2.py --days 45 --symbols 12            # تشغيل قياسي
  python3 backtest_el2.py --days 45 --no-flow-filter        # تجربة A/B بلا فلتر
  python3 backtest_el2.py --scalp-only / --elliott-only     # استراتيجية واحدة
  python3 backtest_el2.py --refresh                          # تجديد الكاش
النتائج: تقرير كونسول عربي + JSON + CSV صفقات + منحنى رصيد في download/el2_backtest/
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

# إنتاج render.yaml — تُثبّت قبل استيراد strategies.base (يقرأ env عند الاستيراد)
for _k, _v in (("SCALP_EXEC_TF", "5m"), ("SCALP_RISK_PCT", "0.75"),
               ("SCALP_MAX_NOTIONAL_USDT", "1200"), ("SCALP_MAX_NOTIONAL_PCT", "30"),
               ("SCALP_MAX_TOTAL_OPEN", "2"), ("SCALP_COOLDOWN_SEC", "2700"),
               ("SCALP_DAILY_LOSS_PCT", "0.6"), ("SCALP_MAX_HOLD_MIN", "90"),
               ("SCALP_PARTIAL_PCT", "50"), ("SCALP_RR_NET_MIN", "0.3"),
               ("SCALP_SYMBOLS_N", "8"), ("SCALP_S1_ENABLED", "1"),
               ("SCALP_ENABLED", "1")):
    os.environ.setdefault(_k, _v)

from engine.pattern_detector import DetectorConfig, PivotDetector  # noqa: E402
from strategies import indicators as ind                           # noqa: E402
from strategies.base import ScalpConfig, ScalpContext, ScalpSignal # noqa: E402
from strategies.flow_filter import evaluate_flow                    # noqa: E402
from strategies.flow_ignition import FlowIgnition                   # noqa: E402

# سكوت سجلات المدقق في الباك تاست (التفاصيل الحية في اللوحة/الحي — هنا نتائج فقط)
import logging  # noqa: E402
for _lg in ("engine.wave_validator", "engine.pattern_detector", "engine"):
    logging.getLogger(_lg).setLevel(logging.ERROR)

# ══════════════════════════════════════════════════════════════════════════════
# الثوابت — منقولة حرفيًا من vnz.py وrender.yaml (إنتاج 2026-10)
# ══════════════════════════════════════════════════════════════════════════════

TF_SEC = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}

# المحرك (موجات إليوت) — vnz.py:238-384 + render.yaml
SIGNAL_TF = "15m"
ENTRY_TF = "15m"
DEVIATION_THRESHOLD = 0.006          # render.yaml (منتصف نطاق 15m بجدول المؤلف)
MIN_WAVE_BARS = 2                    # vnz.py:242
FIB_TOLERANCE_PCT = 0.5              # vnz.py:243
WAVE_MIN_PROPORTION = 0.15           # render.yaml
MAX_OPEN_TRADES = 5                  # render.yaml [طلب المستخدم 2026-10-12] (معلقة+مفتوحة)
RISK_PCT_PER_TRADE = 1.0             # render.yaml
MIN_NOTIONAL_USDT = 10.0             # vnz.py:250
PAPER_MAX_POSITION_PCT = 30.0        # render.yaml
PAPER_MAX_TOTAL_PCT = 100.0          # render.yaml
PENDING_MAX_CANDLES = 6              # render.yaml (1.5س على 15m)
MAX_ENTRY_DISTANCE_PCT = 1.5         # render.yaml
MAX_STRUCTURE_AGE_BARS = 36          # render.yaml
SYMBOL_COOLDOWN_SEC = 5400.0         # render.yaml (90د بعد انتهاء/إلغاء)
CLUSTER_MAX_SAME_DIRECTION = 3       # render.yaml
DEEP_RETRACE_BLOCK_PCT = 0.786       # vnz.py:352
TP_LADDER_ENABLED = True
TP_MIN_RR = 0.5                      # render.yaml
TP_WEEK_CAP_DAYS = 7                 # vnz.py:320
TP_STAGE_SLICE_PCT = 40.0            # vnz.py:324 (% من المتبقي عند كل مرحلة)
TP_STAGE_MIN_GAP_R = 0.2             # vnz.py:325
RR_NET_MIN = 0.3                     # vnz.py:377
BE_AT_R_ENABLED = True               # vnz.py:370
BE_TRIGGER_R = 1.0                   # vnz.py:371
PARTIAL_AT_R_ENABLED = True          # vnz.py:372
PARTIAL_CLOSE_PCT = 50.0             # vnz.py:373
DAILY_LOSS_LIMIT_PCT = 5.0           # vnz.py:374 (قاطع يومي للمحرك)
FEE_RATE = 0.001                     # vnz.py:248
DETECT_WINDOW_BARS = 500             # OHLCV_LIMIT (vnz.py:240)

# السكالب — strategies/base.py + render.yaml
SCALP_EXEC_TF = "5m"
SCALP_SYMBOLS_N = 8                  # render.yaml
SCALP_MAX_TOTAL_OPEN = 2             # render.yaml
SCALP_COOLDOWN_SEC = 2700.0          # render.yaml (45د)
SCALP_DAILY_LOSS_PCT = 0.6           # render.yaml
SCALP_MAX_HOLD_MIN = 90              # render.yaml
ELLIOTT_FLOW_ADX_MIN = 20.0          # render.yaml (بوابة F2)

CVD_LOOKBACK = 36                    # flow_ignition.py:33 (للخروج المبكر)
SCAN_K15_LIMIT = 60                  # manager.py:246 (نافذة 15m للسياق)


# ══════════════════════════════════════════════════════════════════════════════
# دوال نقية منقولة حرفيًا من vnz.py (بأرقام أسطرها) — محرك الموجات
# ══════════════════════════════════════════════════════════════════════════════

def rr_net_value(entry: float, sl: float, tp: float) -> float:
    """vnz.py:3579 — R:R صافي بعد رسوم الاتجاهين."""
    risk = float(entry) - float(sl)
    if risk <= 0 or entry <= 0:
        return 0.0
    reward = (float(tp) - entry) - FEE_RATE * (entry + float(tp))
    return reward / risk


def compute_tp_ladder(setup) -> List[Tuple[float, str]]:
    """vnz.py:2289 — سلّم أهداف الموجة 5 (W5=W1 ← 0.618×W3 ← 1.618×W1)."""
    P = setup.pivot_prices
    p0, p1, p2, p3, p4 = P[0], P[1], P[2], P[3], P[4]
    w1 = abs(p1 - p0)
    w3 = abs(p3 - p2)
    if setup.direction == "BULLISH":
        cands = [(p4 + w1, "w5_eq_w1"), (p4 + 0.618 * w3, "w5_0618_w3"),
                 (p2 + 1.618 * w1, "ext_1618")]
        return sorted(cands, key=lambda t: t[0])
    cands = [(p4 - w1, "w5_eq_w1"), (p4 - 0.618 * w3, "w5_0618_w3"),
             (p2 - 1.618 * w1, "ext_1618")]
    return sorted(cands, key=lambda t: t[0], reverse=True)


def build_staged_targets(setup, entry: float, sl: float, weekly_hi: float):
    """vnz.py:2364 — درجات السلّم مقصوصة على سقف الأسبوع ومرتبة مراحل صاعدة."""
    risk = entry - sl
    if risk <= 0:
        return [], False, 0.0
    best_rr = 0.0
    weekly_capped = False
    kept: List[Tuple[float, str]] = []
    for cand, basis in compute_tp_ladder(setup):
        c = float(cand)
        rr_raw = (c - entry) / risk
        if rr_raw > best_rr:
            best_rr = rr_raw
        if rr_raw < TP_MIN_RR:
            continue
        cc = min(c, weekly_hi)
        if cc < c:
            weekly_capped = True
        if cc <= entry:
            continue
        if RR_NET_MIN > 0 and rr_net_value(entry, sl, cc) < RR_NET_MIN:
            continue
        kept.append((cc, basis))
    kept.sort(key=lambda t: t[0])
    stages: List[Tuple[float, str]] = []
    min_gap = risk * max(TP_STAGE_MIN_GAP_R, 0.0)
    for c, b in kept:
        if stages and (c - stages[-1][0]) < min_gap:
            continue
        stages.append((c, b))
    return stages, weekly_capped, best_rr


def structure_fresh(setup, df) -> bool:
    """vnz.py:5002 — سقف عمر البنية: (طول النافذة − 1) − فهرس P5 ≤ 36."""
    if MAX_STRUCTURE_AGE_BARS <= 0:
        return True
    try:
        p5_idx = int(setup.pivot_indices[5])
        return ((len(df) - 1) - p5_idx) <= MAX_STRUCTURE_AGE_BARS
    except (TypeError, ValueError, IndexError, AttributeError):
        return True


def premise_alive(setup, last_close: float) -> bool:
    """vnz.py:4970 — الإغلاق فوق أصل الموجة 1 (P0)."""
    try:
        return float(last_close) >= float(setup.pivot_prices[0])
    except (TypeError, ValueError, IndexError, AttributeError):
        return True


def deep_retrace_ok(setup, last_close: float) -> bool:
    """vnz.py:4929 — التراجع من P5 أقل من 78.6% من مدى الموجة."""
    if DEEP_RETRACE_BLOCK_PCT <= 0:
        return True
    try:
        p0 = float(setup.pivot_prices[0])
        p5 = float(setup.pivot_prices[5])
        rng = p5 - p0
        if rng <= 0:
            return True
        return ((p5 - float(last_close)) / rng) < DEEP_RETRACE_BLOCK_PCT
    except (TypeError, ValueError, IndexError, AttributeError):
        return True


def select_best_setup(setups):
    """vnz.py:4439 — التقييم المركب (ElliottWavesEngine §5-8): مناطق W2/W4 +
    تناوب العمق + امتداد W3 قرب 1.618 + مساواة W5≈W1 — الأحدث يحسم التعادل."""
    if not setups:
        return None
    if len(setups) == 1:
        return setups[0]

    def score(s):
        fib = s.validation_result.fib
        pts = 0.0
        if fib:
            if fib.wave2_in_zone:
                pts += 1.0
            if fib.wave4_in_zone:
                pts += 1.0
            w2r, w4r = fib.wave2_retrace_pct, fib.wave4_retrace_pct
            if 0.382 <= w2r <= 0.886 and 0.0 < w4r <= 0.5 and w2r > w4r + 0.1:
                pts += 0.5
        P = s.pivot_prices
        try:
            w1 = abs(math.log(P[1]) - math.log(P[0]))
            w3 = abs(math.log(P[3]) - math.log(P[2]))
            w5 = abs(math.log(P[5]) - math.log(P[4]))
            if w1 > 0:
                ext = w3 / w1
                pts += max(0.0, 1.0 - abs(ext - 1.618) / 1.618)
            if min(w1, w5) > 0:
                pts += 0.5 * (1.0 - abs(w5 - w1) / max(w1, w5))
        except (ValueError, ZeroDivisionError, IndexError):
            pass
        recency = 0.0
        try:
            _da = s.detected_at
            recency = _da.timestamp() if _da is not None else 0.0
        except (AttributeError, TypeError, ValueError):
            recency = 0.0
        return (round(pts, 4), recency)

    return max(setups, key=score)


# ══════════════════════════════════════════════════════════════════════════════
# طبقة البيانات — شموع حقيقية من باينانس (تاكير) مع كاش محلي وانسحاب لبيتبت
# ══════════════════════════════════════════════════════════════════════════════

CACHE_DIR = os.path.join(REPO, "backtest_cache")


class DataStore:
    """جلب شموع 5m/15m حقيقية (12 حقل باينانس — دلتا تاكير حقيقية) + كاش pickle."""

    def __init__(self, refresh: bool = False):
        self.refresh = refresh
        self._ex = None
        self.provider_used = ""
        os.makedirs(CACHE_DIR, exist_ok=True)

    def _exchange(self):
        if self._ex is None:
            import ccxt
            for name in ("binance", "bybit"):   # باينانس أولًا (تاكير خام) ثم بديل
                try:
                    ex = getattr(ccxt, name)({"enableRateLimit": True})
                    ex.load_markets()
                    self._ex = ex
                    self.provider_used = name
                    break
                except Exception as exc:
                    print(f"  [بيانات] مزود {name} فشل: {exc}")
            if self._ex is None:
                raise RuntimeError("لا مزود بيانات متاح (باينانس/بيتبت)")
        return self._ex

    def fetch(self, symbol: str, tf: str, days: int, end_ms: int) -> pd.DataFrame:
        """شموع مغلقة حصرًا حتى end_ms — كاش بملف (رمز|فريم) يغطي أوسع مدى مطلوب."""
        tf_ms = TF_SEC[tf] * 1000
        want_start = end_ms - days * 86400_000
        # محاذاة البداية لحافة فريم مغلقة
        want_start = (want_start // tf_ms) * tf_ms
        path = os.path.join(CACHE_DIR, f"{symbol.replace('/', '')}_{tf}.pkl")
        df = None
        if not self.refresh and os.path.exists(path):
            try:
                with open(path, "rb") as fh:
                    df = pickle.load(fh)
            except Exception:
                df = None
        need = (df is None or len(df) == 0
                or int(df["timestamp"].iloc[0]) > want_start
                or int(df["timestamp"].iloc[-1]) < end_ms - tf_ms)
        if need:
            df = self._fetch_remote(symbol, tf, want_start, end_ms)
            try:
                with open(path, "wb") as fh:
                    pickle.dump(df, fh)
            except Exception:
                pass
        else:  # قصّ الكاش على المدى المطلوب
            df = df[(df["timestamp"] >= want_start) & (df["timestamp"] < end_ms)]
        df = df.reset_index(drop=True)
        # صحة: شموع مغلقة فقط داخل النطاق
        return df

    def _fetch_remote(self, symbol: str, tf: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        ex = self._exchange()
        tf_ms = TF_SEC[tf] * 1000
        since = start_ms
        rows: List[list] = []
        print(f"  [بيانات] جلب {symbol} {tf} من {datetime.fromtimestamp(start_ms/1000, timezone.utc):%Y-%m-%d} "
              f"({self.provider_used}) ...")
        while since < end_ms:
            try:
                batch = ex.fetch_ohlcv(symbol, timeframe=tf, since=since, limit=1000)
            except Exception as exc:
                print(f"  [بيانات] إعادة محاولة {symbol} {tf}: {str(exc)[:90]}")
                time.sleep(2.0)
                batch = ex.fetch_ohlcv(symbol, timeframe=tf, since=since, limit=1000)
            if not batch:
                break
            rows.extend(batch)
            nxt = batch[-1][0] + tf_ms
            if nxt <= since:
                break
            since = nxt
            if len(batch) < 500:
                break
            time.sleep(0.12)
        cols = ["timestamp", "open", "high", "low", "close", "volume"]
        df = pd.DataFrame(rows, columns=cols[:6])
        if self.provider_used == "binance" and rows and len(rows[0]) > 9:
            df["taker_base"] = [r[9] for r in rows]
        # مغلق حصرًا + داخل النطاق + إزالة التكرار
        df = df[(df["timestamp"] >= start_ms) & (df["timestamp"] + tf_ms <= end_ms)]
        df = df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = df[c].astype(float)
        return df


def daily_highs_from_15m(df15: pd.DataFrame, days_back: int) -> Dict[int, float]:
    """قمة كل يوم من شموع 15m — يغذي سقف الأسبوع (vnz weekly_high بلا طلبات)."""
    if df15 is None or df15.empty:
        return {}
    ts = df15["timestamp"].values
    hi = df15["high"].values
    out: Dict[int, float] = {}
    day_ids = (ts // 86400_000).astype(np.int64)
    for d in np.unique(day_ids):
        m = day_ids == d
        out[int(d)] = float(hi[m].max())
    return out


def weekly_high_at(day_hi: Dict[int, float], t_ms: int) -> Optional[float]:
    """قمة آخر TP_WEEK_CAP_DAYS أيام مكتملة قبل اللحظة t — القص كما في vnz.py:2337."""
    today = t_ms // 86400_000
    vals = [day_hi[d] for d in range(today - TP_WEEK_CAP_DAYS + 1, today) if d in day_hi]
    return max(vals) if vals else None


# ══════════════════════════════════════════════════════════════════════════════
# المحاسبة الورقية — رسوم 0.1% لكل اتجاه (FEE_RATE الإنتاج)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Position:
    kind: str                # "SCALP" | "ELLIOTT"
    symbol: str
    qty: float
    entry: float
    sl: float
    tp1: Optional[float]     # سكالب: هدف الجزئي / محرك: مرحلة 1
    tp2: Optional[float]     # سكالب: الهدف الثاني / محرك: مرحلة 2
    tp_final: float
    opened_ms: int
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Trade:
    kind: str
    symbol: str
    opened_ms: int
    closed_ms: int
    entry: float
    exit_avg: float
    qty: float
    pnl: float               # صافي بعد الرسوم
    reason: str
    rr_planned: float = 0.0
    legs: List[str] = field(default_factory=list)


class Book:
    """رصيد ورقي واحد يشاركه المساران (كما في الحي) — كل رجل تُحسب لحظتها."""

    def __init__(self, balance: float):
        self.balance = float(balance)
        self.start_balance = float(balance)
        self.day_start_balance = float(balance)
        self.day_id = -1
        self.trades: List[Trade] = []
        self.equity_curve: List[Tuple[int, float]] = []

    def roll_day(self, t_ms: int) -> None:
        d = t_ms // 86400_000
        if d != self.day_id:
            self.day_id = d
            self.day_start_balance = self.balance

    def realized_today(self, kind: str) -> float:
        d = self.day_id
        return sum(t.pnl for t in self.trades if t.kind == kind
                   and (t.closed_ms // 86400_000) == d)

    def leg_fee(self, notional: float) -> float:
        return notional * FEE_RATE

    def close_leg(self, pos: Position, qty_leg: float, price: float,
                  t_ms: int, reason: str) -> None:
        """إغلاق رجل: رسوم الخروج فقط — رسوم الدخول حُسبت كاملة عند الفتح
        (في meta["pnl_acc"]) فلا ازدواج. المحصلة: رسوم = دخول + مجموع مخارج الرجل."""
        qty_leg = min(qty_leg, pos.qty)
        if qty_leg <= 0:
            return
        fee = self.leg_fee(qty_leg * price)          # رسوم الخروج حصرًا
        pnl = qty_leg * (price - pos.entry) - fee
        pos.qty -= qty_leg
        self.balance += pnl
        pos.meta.setdefault("pnl_acc", 0.0)
        pos.meta["pnl_acc"] += pnl
        pos.meta.setdefault("legs", []).append(f"{reason}@{price:.6g}:{pnl:+.2f}$")
        if pos.qty <= 1e-12:
            self.trades.append(Trade(
                kind=pos.kind, symbol=pos.symbol, opened_ms=pos.opened_ms,
                closed_ms=t_ms, entry=pos.entry,
                exit_avg=price, qty=pos.meta.get("qty0", qty_leg),
                pnl=pos.meta["pnl_acc"], reason=reason,
                rr_planned=pos.meta.get("rr_planned", 0.0),
                legs=pos.meta.get("legs", [])))


# ══════════════════════════════════════════════════════════════════════════════
# محرك السكالب — SCALP_FLOW بكود الإنتاج الحقيقي (FlowIgnition.evaluate)
# البوابات والإدارة من strategies/manager.py حرفيًا
# ══════════════════════════════════════════════════════════════════════════════

class ScalpSim:
    def __init__(self, book: Book, stats: Dict[str, Any]):
        self.cfg = ScalpConfig()          # نفس قراءة env الافتراضية للإنتاج
        self.strategy = FlowIgnition(self.cfg)
        self.book = book
        self.stats = stats
        self.cooldowns: Dict[str, int] = {}   # symbol → ms نهاية التبريد
        self.positions: Dict[str, Position] = {}   # symbol → موضع (سقف 2 إجماليًا)

    # ── بوابات الدخول (manager._entry_gates) ──
    def _entry_ok(self, sym: str, t_ms: int, elliott_busy: set) -> Tuple[bool, str]:
        if len(self.positions) >= SCALP_MAX_TOTAL_OPEN:
            return False, "سقف صفقات السكالب المفتوحة"
        if sym in self.positions:
            return False, "صفقة نشطة على الرمز"
        if sym in elliott_busy:
            return False, "صفقة نشطة على الرمز (محرك)"
        if self.cooldowns.get(sym, 0) > t_ms:
            return False, "تبريد الرمز بعد صفقة سابقة"
        # قاطع الخسارة اليومي لكل استراتيجية (manager._daily_loss_block)
        cap = self.book.day_start_balance * SCALP_DAILY_LOSS_PCT / 100.0
        if cap > 0 and self.book.realized_today("SCALP") < -cap:
            return False, "قاطع خسارة اليوم"
        return True, ""

    def _size(self, entry: float, sl: float) -> Tuple[Optional[float], str]:
        """manager._size_position (ورقي) حرفيًا: مخاطرة 0.75% بسقف 30%/1200$."""
        risk_per_unit = entry - sl
        if risk_per_unit <= 0 or entry <= 0:
            return None, "هندسة وقف غير منطقية"
        base = self.book.balance
        risk_usdt = base * self.cfg.risk_pct / 100.0
        qty = risk_usdt / risk_per_unit
        notional = qty * entry
        cap = min(base * self.cfg.max_notional_pct / 100.0, self.cfg.max_notional_usdt)
        if notional > cap:
            qty = cap / entry
            notional = qty * entry
        if notional < self.cfg.min_notional:
            return None, "قيمة صفقة أقل من الحد الأدنى"
        return qty, ""

    def on_candle(self, sym: str, t_ms: int, rows5: List[dict], rows15: List[dict],
                  elliott_busy: set) -> None:
        """دورة 5m مغلقة: إدارة المفتوح ثم تقييم الدخول (ترتيب الحي: مراقبة ثم مسح)."""
        tf = TF_SEC[SCALP_EXEC_TF] * 1000
        c = rows5[-1]
        # 1) إدارة الموضع المفتوح — وقف-أولًا intrabar (manager._monitor_cycle)
        pos = self.positions.get(sym)
        if pos is not None:
            hi, lo, close = c["high"], c["low"], c["close"]
            if lo <= pos.sl:
                self.book.close_leg(pos, pos.qty, pos.sl, t_ms, "وقف")
                self._finish(pos, t_ms)
                self.stats["scalp_closes"]["وقف"] = self.stats["scalp_closes"].get("وقف", 0) + 1
            else:
                did = False
                # جزئي 50% عند TP1 + BE (مرة واحدة)
                if pos.tp1 and not pos.meta.get("partial_done") and hi >= pos.tp1:
                    self.book.close_leg(pos, pos.qty * self.cfg.partial_pct / 100.0,
                                        pos.tp1, t_ms, "هدف1-جزئي")
                    pos.sl = pos.entry                       # BE نقي (manager.py:626-630)
                    pos.meta["partial_done"] = True
                    self.stats["partials_scalp"] += 1
                    did = True
                # الهدف الثاني يغلق المتبقي
                if pos.qty > 1e-12 and pos.tp_final and hi >= pos.tp_final:
                    self.book.close_leg(pos, pos.qty, pos.tp_final, t_ms, "هدف2")
                    self._finish(pos, t_ms)
                    self.stats["scalp_closes"]["هدف2"] = self.stats["scalp_closes"].get("هدف2", 0) + 1
                    did = True
                if pos.qty > 1e-12 and not did:
                    # خروج مبكر: انقلاب CVD مع كسر SuperTrend (manager._early_exits_all)
                    cv = ind.cvd_series(rows5)
                    st = ind.supertrend([r["high"] for r in rows5], [r["low"] for r in rows5],
                                        [r["close"] for r in rows5], 10, 2.5)
                    if cv and st and cv["cvd"][-1] < cv["ema"][-1] and close < st["line"]:
                        self.book.close_leg(pos, pos.qty, close, t_ms, "انقلاب الدلتا")
                        self._finish(pos, t_ms)
                        self.stats["scalp_closes"]["انقلاب الدلتا"] = \
                            self.stats["scalp_closes"].get("انقلاب الدلتا", 0) + 1
                    elif t_ms - pos.opened_ms > self.cfg.max_hold_min * 60_000:
                        self.book.close_leg(pos, pos.qty, close, t_ms,
                                            f"مهلة {self.cfg.max_hold_min}د")
                        self._finish(pos, t_ms)
                        self.stats["scalp_closes"]["مهلة"] = \
                            self.stats["scalp_closes"].get("مهلة", 0) + 1

        # 2) تقييم الدخول بكود الإنتاج الحقيقي
        self.stats["scalp_cycles"] += 1
        ok, why = self._entry_ok(sym, t_ms, elliott_busy)
        if not ok:
            self.stats["scalp_rejects"][why] = self.stats["scalp_rejects"].get(why, 0) + 1
            return
        atr5 = ind.atr([r["high"] for r in rows5], [r["low"] for r in rows5],
                       [r["close"] for r in rows5], 14)
        ctx = ScalpContext(symbol=sym, now_ts=t_ms / 1000.0, k5=rows5, k15=rows15,
                           live_price=float(c["close"]),   # الحي: سعر لحظي ≈ الإغلاق
                           depth=None,                     # الدفتر غير متاح تاريخيًا (مسار 2.2×ATR)
                           cvd_source="taker", atr5=atr5, atr15=None,
                           fib_confluence=None, extra={"fee_rate": FEE_RATE})
        try:
            sig = self.strategy.evaluate(ctx)
        except Exception:
            self.stats["scalp_eval_errors"] += 1
            return
        if not sig:
            return
        if sig.side != "LONG":
            self.stats["scalp_rejects"]["سبوت: لا بيع"] = \
                self.stats["scalp_rejects"].get("سبوت: لا بيع", 0) + 1
            return
        entry = float(c["close"])
        qty, why = self._size(entry, sig.sl)
        if not qty:
            self.stats["scalp_rejects"][why] = self.stats["scalp_rejects"].get(why, 0) + 1
            return
        pos = Position(kind="SCALP", symbol=sym, qty=qty, entry=entry, sl=sig.sl,
                       tp1=sig.tp1, tp2=sig.tp2, tp_final=sig.tp2, opened_ms=t_ms,
                       meta={"qty0": qty, "rr_planned": float(sig.rr1 or 0.0),
                             "reason": sig.reason[:120]})
        self.book.balance -= self.book.leg_fee(qty * entry)   # رسوم الدخول
        pos.meta["pnl_acc"] = -self.book.leg_fee(qty * entry)
        self.positions[sym] = pos
        self.stats["scalp_signals"] += 1

    def _finish(self, pos: Position, t_ms: int) -> None:
        self.positions.pop(pos.symbol, None)
        self.cooldowns[pos.symbol] = t_ms + int(SCALP_COOLDOWN_SEC * 1000)


# ══════════════════════════════════════════════════════════════════════════════
# محرك الموجات — Elliott_Fibonacci بكود الكشف الحقيقي + فلتر التدفق الحقيقي
# دورة الحياة من vnz.py: create_pending_signal + monitor_step حرفيًا
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PendingElliott:
    symbol: str
    entry: float
    sl: float
    tp1: Optional[float]
    tp2: Optional[float]
    tp_final: float
    p0: float
    qty: float
    created_ms: int
    expires_ms: int
    rr_planned: float
    basis: str


class ElliottSim:
    def __init__(self, book: Book, stats: Dict[str, Any], flow_filter_on: bool,
                 symbols: List[str]):
        self.book = book
        self.stats = stats
        self.flow_on = flow_filter_on
        self.detector = PivotDetector(DetectorConfig(   # vnz.py:1738 حرفيًا
            method="zigzag",
            deviation_threshold=DEVIATION_THRESHOLD,
            price_source="close",
            min_wave_bars=MIN_WAVE_BARS,
            require_fib_confluence=False,
            fib_tolerance_pct=FIB_TOLERANCE_PCT,
            min_wave_proportion=WAVE_MIN_PROPORTION,
        ))
        self.flow_cfg_adx = ELLIOTT_FLOW_ADX_MIN
        self.pendings: Dict[str, PendingElliott] = {}
        self.positions: Dict[str, Position] = {}
        self.cooldowns: Dict[str, int] = {}
        self.symbols = symbols

    # ── احتلال وعنقود وسقوف (vnz.py:5247-5310) ──
    def _active_count(self) -> int:
        return len(self.pendings) + len(self.positions)

    def _bullish_active(self) -> int:
        return self._active_count()      # كل الإشارات صاعدة (سبوت LONG حصرًا)

    def _daily_block(self) -> bool:
        cap = self.book.day_start_balance * DAILY_LOSS_LIMIT_PCT / 100.0
        return cap > 0 and self.book.realized_today("ELLIOTT") < -cap

    def _size_elliott(self, entry: float, sl: float) -> Optional[float]:
        """vnz.compute_quantity (ورقي) حرفيًا: مخاطرة 1% + سقف مركز 30% + سقف إجمالي 100%."""
        risk_amount = self.book.balance * (RISK_PCT_PER_TRADE / 100.0)
        risk_per_coin = abs(entry - sl)
        if risk_per_coin <= 0 or risk_amount <= 0:
            return None
        qty = risk_amount / risk_per_coin
        qty = math.floor(qty * 1e6) / 1e6
        if qty <= 0:
            return None
        notional = qty * entry
        if notional < MIN_NOTIONAL_USDT:
            qty_min = MIN_NOTIONAL_USDT / entry
            if qty_min * risk_per_coin <= risk_amount * 3.0:
                qty = math.floor(qty_min * 1e6) / 1e6
                notional = qty * entry
            else:
                return None
        if PAPER_MAX_POSITION_PCT > 0:
            max_pos = self.book.balance * (PAPER_MAX_POSITION_PCT / 100.0)
            if notional > max_pos:
                qty = math.floor((max_pos / entry) * 1e6) / 1e6
                notional = qty * entry
        if PAPER_MAX_TOTAL_PCT > 0:
            active = sum(p.qty * p.entry for p in self.positions.values())
            active += sum(p.qty * p.entry for p in self.pendings.values())
            remaining = self.book.balance * (PAPER_MAX_TOTAL_PCT / 100.0) - active
            if remaining < MIN_NOTIONAL_USDT:
                return None
            if notional > remaining:
                qty = math.floor((remaining / entry) * 1e6) / 1e6
        if qty <= 0:
            return None
        return qty

    # ── إدارة المفتوح (vnz.monitor_step:4394-4432) ──
    def manage_open(self, sym: str, t_ms: int, candle: dict) -> None:
        pos = self.positions.get(sym)
        if pos is None:
            return
        hi, lo = candle["high"], candle["low"]
        if lo <= pos.sl:                                    # الوقف أولًا — دائمًا
            self.book.close_leg(pos, pos.qty, pos.sl, t_ms, "وقف بنيوي")
            self._finish(pos)
            self.stats["ell_closes"]["وقف"] = self.stats["ell_closes"].get("وقف", 0) + 1
            return
        # حماية +1R: جزئي 50% عند الدخول+1R ثم BE (vnz._protection_step)
        trigger = pos.entry + (pos.meta["r1"]) * BE_TRIGGER_R
        if BE_AT_R_ENABLED and not pos.meta.get("be_done") and hi >= trigger:
            if PARTIAL_AT_R_ENABLED and not pos.meta.get("partial_done"):
                self.book.close_leg(pos, pos.qty * PARTIAL_CLOSE_PCT / 100.0,
                                    trigger, t_ms, "جزئي +1R")
                pos.meta["partial_done"] = True
                self.stats["partials_elliott"] += 1
            if pos.sl < pos.entry:
                pos.sl = pos.entry                          # BE@1R
                pos.meta["be_done"] = True
        # مراحل TP1/TP2 — 40% من المتبقي (vnz._tp_stage_step)
        for stage, flag in (("tp1", "tp1_done"), ("tp2", "tp2_done")):
            lvl = pos.meta.get(stage)
            if not lvl or pos.meta.get(flag) or pos.qty <= 1e-12:
                continue
            if not (pos.tp_final > lvl * 1.0005):
                continue
            if hi >= lvl:
                self.book.close_leg(pos, pos.qty * TP_STAGE_SLICE_PCT / 100.0,
                                    lvl, t_ms, f"مرحلة {stage.upper()}")
                pos.meta[flag] = True
        # الهدف النهائي يغلق المتبقي
        if pos.qty > 1e-12 and hi >= pos.tp_final:
            self.book.close_leg(pos, pos.qty, pos.tp_final, t_ms, "هدف 1.618/سقف")
            self._finish(pos)
            self.stats["ell_closes"]["هدف"] = self.stats["ell_closes"].get("هدف", 0) + 1

    # ── دورة المعلق (vnz.monitor_step:4342-4392 — إبطال ثم صلاحية ثم ملء) ──
    def manage_pending(self, sym: str, t_ms: int, candle: dict) -> None:
        pend = self.pendings.get(sym)
        if pend is None:
            return
        close, lo = candle["close"], candle["low"]
        if close < pend.p0:                                 # الإبطال البنيوي أولًا
            del self.pendings[sym]
            self.cooldowns[sym] = t_ms + int(SYMBOL_COOLDOWN_SEC * 1000)
            self.stats["ell_pending"]["إبطال بنيوي"] = \
                self.stats["ell_pending"].get("إبطال بنيوي", 0) + 1
            return
        if t_ms > pend.expires_ms:                          # انتهاء الصلاحية
            del self.pendings[sym]
            self.cooldowns[sym] = t_ms + int(SYMBOL_COOLDOWN_SEC * 1000)
            self.stats["ell_pending"]["انتهاء"] = \
                self.stats["ell_pending"].get("انتهاء", 0) + 1
            return
        if lo <= pend.entry:                                # الملء بسعر الأمر
            fill = pend.entry if close >= pend.entry else close
            del self.pendings[sym]
            pos = Position(kind="ELLIOTT", symbol=sym, qty=pend.qty, entry=fill,
                           sl=pend.sl, tp1=pend.tp1, tp2=pend.tp2, tp_final=pend.tp_final,
                           opened_ms=t_ms,
                           meta={"qty0": pend.qty, "rr_planned": pend.rr_planned,
                                 "p0": pend.p0, "r1": fill - pend.sl,
                                 "tp1": pend.tp1, "tp2": pend.tp2, "basis": pend.basis})
            self.book.balance -= self.book.leg_fee(pend.qty * fill)
            pos.meta["pnl_acc"] = -self.book.leg_fee(pend.qty * fill)
            self.positions[sym] = pos
            self.stats["ell_pending"]["ملء"] = self.stats["ell_pending"].get("ملء", 0) + 1
            self.manage_open(sym, t_ms, candle)             # نفس الشمعة تُدار (كما في الحي)

    def _finish(self, pos: Position) -> None:
        self.positions.pop(pos.symbol, None)

    # ── الكشف والقبول (vnz.scan loop:5200-5310 + create_pending_signal:3315) ──
    def detect(self, sym: str, t_ms: int, df15: pd.DataFrame, rows5: List[dict],
               week_hi: Optional[float], busy_extra: Optional[set] = None) -> None:
        self.stats["ell_scans"] += 1
        if sym in self.pendings or sym in self.positions:
            self.stats["ell_rejects"]["رمز مشغول"] = \
                self.stats["ell_rejects"].get("رمز مشغول", 0) + 1
            return
        if busy_extra and sym in busy_extra:   # symbol_has_active يعبر الاستراتيجيات
            self.stats["ell_rejects"]["رمز مشغول (سكالب)"] = \
                self.stats["ell_rejects"].get("رمز مشغول (سكالب)", 0) + 1
            return
        if self.cooldowns.get(sym, 0) > t_ms:
            self.stats["ell_rejects"]["تبريد الرمز"] = \
                self.stats["ell_rejects"].get("تبريد الرمز", 0) + 1
            return
        if self._active_count() >= MAX_OPEN_TRADES:
            self.stats["ell_rejects"]["الخانات ممتلئة"] = \
                self.stats["ell_rejects"].get("الخانات ممتلئة", 0) + 1
            return
        if CLUSTER_MAX_SAME_DIRECTION > 0 and self._bullish_active() >= CLUSTER_MAX_SAME_DIRECTION:
            self.stats["ell_rejects"]["عنقود اتجاهي"] = \
                self.stats["ell_rejects"].get("عنقود اتجاهي", 0) + 1
            return
        if self._daily_block():
            self.stats["ell_rejects"]["قاطع الخسارة اليومي"] = \
                self.stats["ell_rejects"].get("قاطع الخسارة اليومي", 0) + 1
            return
        try:
            setups = self.detector.scan(df15)
        except Exception:
            self.stats["ell_scan_errors"] += 1
            return
        bulls = [s for s in setups if s.direction == "BULLISH"]
        if not bulls:
            return
        self.stats["ell_bull_setups"] += len(bulls)
        best = select_best_setup(
            [s for s in bulls if structure_fresh(s, df15)] or bulls)
        if best is None:
            return
        last_close = float(df15["close"].iloc[-1])
        if not structure_fresh(best, df15):
            self.stats["ell_rejects"]["بنية متقادمة"] = \
                self.stats["ell_rejects"].get("بنية متقادمة", 0) + 1
            return
        if not premise_alive(best, last_close):
            self.stats["ell_rejects"]["الفرضية ماتت"] = \
                self.stats["ell_rejects"].get("الفرضية ماتت", 0) + 1
            return
        if not deep_retrace_ok(best, last_close):
            self.stats["ell_rejects"]["تصحيح عميق"] = \
                self.stats["ell_rejects"].get("تصحيح عميق", 0) + 1
            return
        # [EL2.3.0] فلتر التدفق — الحقيقي evaluate_flow على شموع 5m مغلقة
        if self.flow_on:
            verdict = evaluate_flow(rows5, direction="BULLISH",
                                    adx_min=self.flow_cfg_adx)
            if not verdict.get("ok"):
                gate = verdict.get("gate") or "؟"
                self.stats["ell_flow_rejects"][gate] = \
                    self.stats["ell_flow_rejects"].get(gate, 0) + 1
                return
            if verdict.get("unavailable"):
                self.stats["ell_flow_unavailable"] += 1
        entry = float(best.entry_zone_low)
        sl = float(best.stop_loss_price)
        risk_pre = entry - sl
        if risk_pre <= 0:
            self.stats["ell_rejects"]["هندسة غير منطقية"] = \
                self.stats["ell_rejects"].get("هندسة غير منطقية", 0) + 1
            return
        # السلّم + سقف الأسبوع + المراحل (create_pending_signal:3361-3424)
        tp_final, tp1, tp2, basis = None, None, None, "ext_1618"
        if week_hi and week_hi > 0:
            stages, _capped, best_rr = build_staged_targets(best, entry, sl, week_hi)
            if stages:
                tp1, basis = stages[0]
                tp3 = stages[-1][0]
                tp2 = stages[1][0] if len(stages) >= 3 else None
                tp_final = tp3
            elif best_rr < TP_MIN_RR:
                self.stats["ell_rejects"]["لا هدف تحت سقف الأسبوع"] = \
                    self.stats["ell_rejects"].get("لا هدف تحت سقف الأسبوع", 0) + 1
                return
            else:
                tp_final = None
        if tp_final is None:   # المسار القديم: أقرب درجة تحقق TP_MIN_RR وإلا 1.618
            ladder_best = 0.0
            tp_final = entry + risk_pre * 1.618
            basis = "ext_1618"
            if TP_LADDER_ENABLED:
                for cand, b in compute_tp_ladder(best):
                    rr_c = (float(cand) - entry) / risk_pre
                    if rr_c > ladder_best:
                        ladder_best = rr_c
                    if rr_c >= TP_MIN_RR:
                        tp_final, basis = float(cand), b
                        break
        if not (entry > 0 and sl > 0 and tp_final > entry > sl):
            self.stats["ell_rejects"]["لا هدف يحقق R:R"] = \
                self.stats["ell_rejects"].get("لا هدف يحقق R:R", 0) + 1
            return
        # مطاردة 1.5% (create_pending_signal:3449)
        if MAX_ENTRY_DISTANCE_PCT > 0:
            dist = (last_close / entry - 1.0) * 100.0
            if dist > MAX_ENTRY_DISTANCE_PCT:
                self.stats["ell_rejects"]["مطاردة"] = \
                    self.stats["ell_rejects"].get("مطاردة", 0) + 1
                return
        # صلاحية الهدف: TP ≤ max(الإغلاق, P5) مرفوض (create_pending_signal:3461)
        try:
            p5 = float(best.pivot_prices[5])
        except (TypeError, ValueError, IndexError):
            p5 = 0.0
        ceiling = max(last_close, p5) if p5 > 0 else last_close
        if tp_final <= ceiling:
            self.stats["ell_rejects"]["هدف مُحقق مسبقًا"] = \
                self.stats["ell_rejects"].get("هدف مُحقق مسبقًا", 0) + 1
            return
        # أرضية R:R الصافي 0.3 (create_pending_signal:3477)
        if RR_NET_MIN > 0 and rr_net_value(entry, sl, tp_final) < RR_NET_MIN:
            self.stats["ell_rejects"]["R:R صافٍ منخفض"] = \
                self.stats["ell_rejects"].get("R:R صافٍ منخفض", 0) + 1
            return
        qty = self._size_elliott(entry, sl)
        if not qty:
            self.stats["ell_rejects"]["رفض الحجم/السقوف"] = \
                self.stats["ell_rejects"].get("رفض الحجم/السقوف", 0) + 1
            return
        rr_planned = round((tp_final - entry) / risk_pre, 2)
        self._register_pending(sym, t_ms, entry, sl, tp_final, tp1, tp2, basis,
                               best, qty, rr_planned)

    def _register_pending(self, sym: str, t_ms: int, entry: float, sl: float,
                          tp_final: float, tp1: Optional[float], tp2: Optional[float],
                          basis: str, best, qty: float, rr_planned: float) -> None:
        """خطاف ولادة الأمر المعلق — يظل سلوك الإنتاج الافتراضي حرفيًا
        (المختبر bt_lab يتجاوزه لرافعات مثل سقف المخاطرة البنيوية)."""
        self.pendings[sym] = PendingElliott(
            symbol=sym, entry=entry, sl=sl, tp1=tp1, tp2=tp2, tp_final=tp_final,
            p0=float(best.pivot_prices[0]), qty=qty, created_ms=t_ms,
            expires_ms=t_ms + PENDING_MAX_CANDLES * TF_SEC[ENTRY_TF] * 1000,
            rr_planned=rr_planned, basis=basis)
        self.stats["ell_pending"]["وُلد"] = self.stats["ell_pending"].get("وُلد", 0) + 1


# ══════════════════════════════════════════════════════════════════════════════
# الحلقة الرئيسية — ساعة رئيسية على إغلاقات 5m (و15m على حدودها)
# ══════════════════════════════════════════════════════════════════════════════

def load_symbols(spec: str) -> List[str]:
    path = os.path.join(REPO, "crypto_list.txt")
    base = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            base = [ln.strip().upper() for ln in fh
                    if ln.strip() and not ln.strip().startswith("#")]
    spec = (spec or "").strip()
    if spec.lower() == "all":
        return [f"{s}/USDT" for s in base]
    if spec.isdigit():
        return [f"{s}/USDT" for s in base[:int(spec)]]
    if "/" in spec or "," in spec:
        out = []
        for s in spec.split(","):
            s = s.strip().upper()
            if s:
                out.append(s if "/" in s else f"{s}/USDT")
        return out
    return [f"{s}/USDT" for s in base[:12]]


def run(args) -> Dict[str, Any]:
    t0_wall = time.time()
    symbols = load_symbols(args.symbols)
    end_ms = int(time.time() * 1000) // (TF_SEC["5m"] * 1000) * (TF_SEC["5m"] * 1000)
    fetch_days = args.days + 8                    # إحماء 500 شمعة 15m + 160 شمعة 5m
    sim_start_ms = end_ms - args.days * 86400_000

    print(f"═" * 78)
    print(f"باك تاست EL2 [BT1.0.0] — كود الإنتاج الحقيقي على بيانات حقيقية")
    print(f"النطاق: آخر {args.days} يومًا | الرموز: {len(symbols)} | الرصيد: {args.balance:,.0f} USDT | "
          f"رسوم: {FEE_RATE*100:.1f}%/اتجاه")
    print(f"فلتر التدفق للموجات: {'مفعل (إنتاج)' if not args.no_flow_filter else 'معطل — تجربة A/B'}"
          f" | المحاكاة: {'الاثنتان' if not (args.scalp_only or args.elliott_only) else 'سكالب فقط' if args.scalp_only else 'موجات فقط'}")
    print(f"═" * 78)

    ds = DataStore(refresh=args.refresh)
    data: Dict[str, Dict[str, Any]] = {}
    for i, sym in enumerate(symbols, 1):
        df5 = ds.fetch(sym, "5m", fetch_days, end_ms)
        df15 = ds.fetch(sym, "15m", fetch_days, end_ms)
        if len(df5) < 200 or len(df15) < 60:
            print(f"  [تخطٍ] {sym}: بيانات غير كافية ({len(df5)}×5m, {len(df15)}×15m)")
            continue
        data[sym] = {"df5": df5, "df15": df15,
                     "day_hi": daily_highs_from_15m(df15, fetch_days)}
        print(f"  [{i}/{len(symbols)}] {sym}: {len(df5)} شمعة 5m، {len(df15)} شمعة 15m")
    symbols = [s for s in symbols if s in data]
    if not symbols:
        raise SystemExit("لا رموز ببيانات كافية")

    # ساعة البدء: أول ل boundary يسبقه إحماء كامل (500×15m و160×5m)
    warm15 = 500 * TF_SEC["15m"] * 1000
    warm5 = 200 * TF_SEC["5m"] * 1000
    start_ms = max(sim_start_ms,
                   int(data[symbols[0]]["df5"]["timestamp"].iloc[0]) + warm5,
                   int(data[symbols[0]]["df15"]["timestamp"].iloc[0]) + warm15)
    start_ms = (start_ms // (TF_SEC["5m"] * 1000)) * (TF_SEC["5m"] * 1000)

    # مؤشرات سريعة للوصول O(1) لشمعة الإغلاق عند كل حدود
    for sym in symbols:
        d5, d15 = data[sym]["df5"], data[sym]["df15"]
        data[sym]["idx5"] = {int(ts): j for j, ts in enumerate(d5["timestamp"].values)}
        data[sym]["idx15"] = {int(ts): j for j, ts in enumerate(d15["timestamp"].values)}

    stats: Dict[str, Any] = {
        "scalp_cycles": 0, "scalp_signals": 0, "partials_scalp": 0,
        "partials_elliott": 0,
        "scalp_closes": {}, "scalp_rejects": {}, "scalp_eval_errors": 0,
        "ell_scans": 0, "ell_bull_setups": 0, "ell_scan_errors": 0,
        "ell_rejects": {}, "ell_flow_rejects": {}, "ell_flow_unavailable": 0,
        "ell_pending": {}, "ell_closes": {},
    }
    book = Book(args.balance)
    scalp_syms = symbols[:args.scalp_symbols]  # resolve_symbols: أول N من القائمة
    scalp = ScalpSim(book, stats) if not args.elliott_only else None
    elliott = ElliottSim(book, stats, flow_filter_on=not args.no_flow_filter,
                         symbols=symbols) if not args.scalp_only else None

    dq5: Dict[str, deque] = {s: deque(maxlen=220) for s in symbols}
    dq15: Dict[str, deque] = {s: deque(maxlen=DETECT_WINDOW_BARS + 20) for s in symbols}

    steps = list(range(start_ms, end_ms, TF_SEC["5m"] * 1000))
    print(f"\nالحلقة: {len(steps):,} دورة 5m × {len(symbols)} رمزًا — تبدأ "
          f"{datetime.fromtimestamp(start_ms/1000, timezone.utc):%Y-%m-%d %H:%M} UTC\n")

    t_last_report = time.time()
    for n, T in enumerate(steps):
        book.roll_day(T)
        boundary15 = (T % (TF_SEC["15m"] * 1000) == 0)
        for sym in symbols:
            d = data[sym]
            j = d["idx5"].get(T - TF_SEC["5m"] * 1000)
            if j is None:
                continue
            r5 = d["df5"].iloc[j]
            row5 = {"ts": float(r5["timestamp"]), "open": float(r5["open"]),
                    "high": float(r5["high"]), "low": float(r5["low"]),
                    "close": float(r5["close"]), "volume": float(r5["volume"]),
                    "taker_base": (float(r5["taker_base"])
                                   if "taker_base" in d["df5"].columns else None)}
            dq5[sym].append(row5)
            candle15 = None
            if boundary15:
                k = d["idx15"].get(T - TF_SEC["15m"] * 1000)
                if k is not None:
                    r15 = d["df15"].iloc[k]
                    candle15 = {"ts": float(r15["timestamp"]), "open": float(r15["open"]),
                                "high": float(r15["high"]), "low": float(r15["low"]),
                                "close": float(r15["close"]),
                                "volume": float(r15["volume"]),
                                "taker_base": (float(r15["taker_base"])
                                               if "taker_base" in d["df15"].columns else None)}
                    dq15[sym].append(candle15)

            rows5 = list(dq5[sym])[-160:]
            rows15 = list(dq15[sym])[-SCAN_K15_LIMIT:]

            if boundary15 and elliott and candle15 is not None:
                # ترتيب الحي: مراقبة المفتوح والمعلق ثم كشف جديد
                elliott.manage_open(sym, T, candle15)
                elliott.manage_pending(sym, T, candle15)
                dfw = d["df15"]
                lo_idx = d["idx15"].get(T - TF_SEC["15m"] * 1000, 0)
                a = max(0, lo_idx - DETECT_WINDOW_BARS + 1)
                win = dfw.iloc[a:lo_idx + 1]
                if len(win) >= 60:
                    # نافذة بزمن pd.Timestamp (كما يمرر الحي من الكاش) — detected_at حقيقي
                    win = win.copy()
                    win["timestamp"] = pd.to_datetime(win["timestamp"], unit="ms", utc=True)
                    elliott.detect(sym, T, win, rows5,
                                   weekly_high_at(d["day_hi"], T),
                                   busy_extra=set(scalp.positions.keys()) if scalp else None)

            if scalp and sym in scalp_syms and len(rows5) >= 60:
                scalp.on_candle(sym, T, rows5, rows15,
                                set(elliott.pendings) | set(elliott.positions)
                                if elliott else set())

        if time.time() - t_last_report > 20.0:
            pct = 100.0 * (n + 1) / len(steps)
            print(f"  ... {pct:5.1f}% | رصيد {book.balance:,.2f} | "
                  f"صفقات مغلقة {len(book.trades)}", flush=True)
            t_last_report = time.time()

    # تسوية النهاية: إغلاق ما بقي مفتوحًا بآخر إغلاق (بلا افتراضات)
    open_syms = set()
    if scalp:
        open_syms |= set(scalp.positions.keys())
    if elliott:
        open_syms |= set(elliott.positions.keys())
    for sym in sorted(open_syms):
        last5 = data[sym]["df5"].iloc[-1]
        px = float(last5["close"])
        pos = (scalp.positions.get(sym) if scalp else None) or \
              (elliott.positions.get(sym) if elliott else None)
        if pos:
            book.close_leg(pos, pos.qty, px, end_ms, "نهاية الفترة")
            if pos.kind == "SCALP" and scalp:
                scalp._finish(pos, end_ms)
            elif elliott:
                elliott._finish(pos)

    # منحنى الرصيد اليومي
    day_bal: Dict[int, float] = {}
    for tr in book.trades:
        day_bal[tr.closed_ms // 86400_000] = None
    eq = []
    bal = book.start_balance
    day_pnl: Dict[int, float] = {}
    for tr in book.trades:
        day_pnl[tr.closed_ms // 86400_000] = day_pnl.get(tr.closed_ms // 86400_000, 0) + tr.pnl
    for d in sorted(day_pnl):
        bal += day_pnl[d]
        eq.append((d * 86400_000, bal))

    result = summarize(args, symbols, scalp_syms, book, stats, eq, ds.provider_used,
                       start_ms, end_ms, time.time() - t0_wall)
    report(result, book)
    save_outputs(args, result, book, eq)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# الإحصاء والتقارير
# ══════════════════════════════════════════════════════════════════════════════

def perf(trades: List[Trade]) -> Dict[str, Any]:
    if not trades:
        return {"n": 0}
    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    durs = [(t.closed_ms - t.opened_ms) / 60000.0 for t in trades]
    if losses and sum(losses) < 0:
        pf: Any = round(sum(wins) / abs(sum(losses)), 2)
    elif wins:
        pf = None   # أرباح بلا خسائر → PF غير معرف حسابيًا (يُعرض ∞)
    else:
        pf = 0.0    # لا أرباح إطلاقًا
    return {
        "n": len(trades),
        "wr": round(100.0 * len(wins) / len(trades), 1),
        "pf": pf,
        "net": round(sum(pnls), 2),
        "avg": round(sum(pnls) / len(trades), 2),
        "best": round(max(pnls), 2), "worst": round(min(pnls), 2),
        "avg_min": round(sum(durs) / len(durs), 1),
        "med_min": round(sorted(durs)[len(durs) // 2], 1),
    }


def max_drawdown(eq: List[Tuple[int, float]], start: float) -> float:
    peak, mdd = start, 0.0
    for _ts, bal in eq:
        peak = max(peak, bal)
        if peak > 0:
            mdd = max(mdd, (peak - bal) / peak * 100.0)
    return round(mdd, 2)


def summarize(args, symbols, scalp_syms, book, stats, eq, provider,
              start_ms, end_ms, wall_sec) -> Dict[str, Any]:
    out = {
        "tag": args.tag, "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": {"days": args.days,
                   "start": datetime.fromtimestamp(start_ms / 1000, timezone.utc).isoformat(),
                   "end": datetime.fromtimestamp(end_ms / 1000, timezone.utc).isoformat()},
        "config": {"symbols": symbols, "provider": provider,
                   "flow_filter": not args.no_flow_filter,
                   "scalp_enabled": not args.elliott_only,
                   "elliott_enabled": not args.scalp_only,
                   "balance_start": args.balance, "fee_rate": FEE_RATE,
                   "scalp_universe": scalp_syms,
                   "constants": {"MAX_OPEN_TRADES": MAX_OPEN_TRADES,
                                 "SCALP_MAX_TOTAL_OPEN": SCALP_MAX_TOTAL_OPEN,
                                 "RISK_PCT_PER_TRADE": RISK_PCT_PER_TRADE,
                                 "SCALP_RISK_PCT": 0.75,
                                 "PENDING_MAX_CANDLES": PENDING_MAX_CANDLES,
                                 "MAX_STRUCTURE_AGE_BARS": MAX_STRUCTURE_AGE_BARS,
                                 "MAX_ENTRY_DISTANCE_PCT": MAX_ENTRY_DISTANCE_PCT,
                                 "SYMBOL_COOLDOWN_SEC": SYMBOL_COOLDOWN_SEC,
                                 "SCALP_COOLDOWN_SEC": SCALP_COOLDOWN_SEC}},
        "balance": {"start": book.start_balance, "end": round(book.balance, 2),
                    "net": round(book.balance - book.start_balance, 2),
                    "return_pct": round((book.balance / book.start_balance - 1) * 100, 2),
                    "max_drawdown_pct": max_drawdown(eq, book.start_balance)},
        "scalp": {"perf": perf([t for t in book.trades if t.kind == "SCALP"]),
                  "signals": stats["scalp_signals"],
                  "partials": stats["partials_scalp"],
                  "closes": stats["scalp_closes"], "rejects": stats["scalp_rejects"],
                  "cycles": stats["scalp_cycles"],
                  "eval_errors": stats["scalp_eval_errors"]},
        "elliott": {"perf": perf([t for t in book.trades if t.kind == "ELLIOTT"]),
                    "scans": stats["ell_scans"], "bull_setups": stats["ell_bull_setups"],
                    "pending": stats["ell_pending"], "closes": stats["ell_closes"],
                    "rejects": stats["ell_rejects"],
                    "partials": stats["partials_elliott"],
                    "flow_rejects": stats["ell_flow_rejects"],
                    "flow_unavailable": stats["ell_flow_unavailable"],
                    "scan_errors": stats["ell_scan_errors"]},
        "wall_sec": round(wall_sec, 1),
    }
    return out


def report(r: Dict[str, Any], book: Book) -> None:
    ps, pe = r["scalp"]["perf"], r["elliott"]["perf"]
    b = r["balance"]

    def line(k: str, p: Dict[str, Any]) -> str:
        if not p.get("n"):
            return f"  {k}: لا صفقات"
        pf = p["pf"]
        pf_s = "∞ (لا خسائر)" if pf is None else f"{pf:.2f}"
        return (f"  {k}: {p['n']} صفقة | إصابة {p['wr']}% | PF {pf_s} | "
                f"صافي {p['net']:+,.2f}$ | متوسط {p['avg']:+.2f}$ | "
                f"أفضل {p['best']:+.2f} | أسوأ {p['worst']:+.2f} | "
                f"مدة وسيطية {p['med_min']:.0f}د")

    print("\n" + "═" * 78)
    print("النتيجة الإجمالية")
    print("═" * 78)
    print(f"  الرصيد: {b['start']:,.2f} → {b['end']:,.2f} USDT  "
          f"(صافي {b['net']:+,.2f}$ | {b['return_pct']:+.2f}% | أقصى تراجع {b['max_drawdown_pct']}%)")
    print(line("⚡ SCALP_FLOW (انجلال التدفق)", ps))
    print(line("🌊 Elliott_Fibonacci (الموجات + فلتر التدفق)", pe))

    e = r["elliott"]
    if e.get("scans"):
        print("\nقمع الموجات:")
        born = e["pending"].get("وُلد", 0)
        print(f"  دورات كشف {e['scans']:,} → بنيات صاعدة {e['bull_setups']:,} → "
              f"أوامر معلقة {born} → مُلئت {e['pending'].get('ملء', 0)} "
              f"({(100.0*e['pending'].get('ملء',0)/born if born else 0):.0f}%) | "
              f"انتهت {e['pending'].get('انتهاء', 0)} | أُبطلت {e['pending'].get('إبطال بنيوي', 0)}")
        if e["flow_rejects"]:
            fr = e["flow_rejects"]
            print(f"  رفض فلتر التدفق: " + " | ".join(
                f"F{k[1] if k.startswith('F') else k}={v}" for k, v in sorted(fr.items())) +
                (f" | بلا بيانات (fail-open) {e['flow_unavailable']}" if e["flow_unavailable"] else ""))
        top_rej = sorted(e["rejects"].items(), key=lambda kv: -kv[1])[:6]
        if top_rej:
            print("  أعلى رفضات البوابات: " + " | ".join(f"{k}={v}" for k, v in top_rej))
    s = r["scalp"]
    if s.get("cycles"):
        print(f"\nالسكالب: {s['cycles']:,} دورة تقييم → {s['signals']} إشارة | "
              f"جزئيات {s['partials']} | إغلاقات: " +
              " | ".join(f"{k}={v}" for k, v in sorted(s["closes"].items())))


def save_outputs(args, r: Dict[str, Any], book: Book, eq) -> None:
    out_root = args.out or "/home/z/my-project/download/el2_backtest"
    out_dir = os.path.join(out_root, r["tag"])
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(r, fh, ensure_ascii=False, indent=2)
    if book.trades:
        rows = [{
            "strategy": t.kind, "symbol": t.symbol,
            "opened": datetime.fromtimestamp(t.opened_ms / 1000, timezone.utc)
                      .strftime("%Y-%m-%d %H:%M"),
            "closed": datetime.fromtimestamp(t.closed_ms / 1000, timezone.utc)
                       .strftime("%Y-%m-%d %H:%M"),
            "duration_min": round((t.closed_ms - t.opened_ms) / 60000.0, 1),
            "entry": t.entry, "exit_avg": round(t.exit_avg, 8), "qty": round(t.qty, 8),
            "pnl_net": round(t.pnl, 4), "reason": t.reason,
            "rr_planned": t.rr_planned, "legs": " ; ".join(t.legs),
        } for t in book.trades]
        pd.DataFrame(rows).to_csv(os.path.join(out_dir, "trades.csv"),
                                  index=False, encoding="utf-8-sig")
    if eq:
        pd.DataFrame([{"date": datetime.fromtimestamp(ts / 1000, timezone.utc).date(),
                       "balance": round(bal, 2)} for ts, bal in eq]
                     ).to_csv(os.path.join(out_dir, "equity.csv"),
                              index=False, encoding="utf-8-sig")
    print(f"\n📁 النتائج: {out_dir}  (summary.json + trades.csv + equity.csv)")


def main():
    ap = argparse.ArgumentParser(description="باك تاست EL2 — كود الإنتاج الحقيقي")
    ap.add_argument("--symbols", default="12",
                    help="'all' أو عدد من رأس crypto_list أو قائمة 'BTC/USDT,ETH/USDT'")
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--balance", type=float, default=10000.0, help="رصيد الإنتاج 10000")
    ap.add_argument("--no-flow-filter", action="store_true",
                    help="تعطيل فلتر التدفق للموجات — تجربة A/B")
    ap.add_argument("--scalp-only", action="store_true")
    ap.add_argument("--elliott-only", action="store_true")
    ap.add_argument("--scalp-symbols", type=int, default=SCALP_SYMBOLS_N)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--refresh", action="store_true", help="تجديد كاش الشموع")
    a = ap.parse_args()
    a.tag = a.tag or datetime.now().strftime("run_%m%d_%H%M")
    run(a)


if __name__ == "__main__":
    main()
