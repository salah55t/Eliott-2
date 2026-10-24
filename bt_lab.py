#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""مختبر تجارب الباك تاست — طبقة تجارب فوق backtest_el2 (BT-LAB 1.0)
==================================================================
الفكرة: نفس محرك المحاسبة والحلقة الحرفي، مع رافعات تجريبية (variants)
مستمدة من المشاريع مفتوحة المصدر، تُفعّل لكل تجربة بلا مساس بالكود المرجعي:

  • di_gate      (freqtrade/ADXMomentum): ADX بلا اتجاه — نشترط +DI > −DI
                 على 5m حتى لا «يؤكد» ADX المرتفع في الهبوط الحاد صفقات شراء.
  • htf_gate     (flowsurface متعدد الفريمات): SuperTrend(10,3.0) على 1h
                 يجب أن يكون صاعدًا — انحياز الفريم الأعلى.
  • retrace      (ممارسة أوامر التدفق): لا مطاردة شمعة الانفجار — أمر محدد
                 بعمق retrace_atr×ATR تحت إغلاق القرار، صالح expiry شموع 5m،
                 يُلغى عند إبطال الفرضية (كسر الوقف المرجعي/انقلاب ST5).
  • trail        (freqtrade/CustomStoploss): بعد الجزئي+BE يُتبع الوقف
                 close − k×ATR (سكالب 5m / موجات 15m) بدل هدف ثابت وحيد.
  • min_rr1      رفع أرضية R:R الصافي حتى TP1 (جودة قبل الكم).
  • blackout     حظر رمز بعد سلسلة خسائر متتالية (مضاد نمط AVAX).
  • elliott:     htf_gate + rr_min/tp_min_rr أعلى + pending أطول + trail 15m.

الاستخدام:
  python3 bt_lab.py --variant S1 --days 45 --symbols 12
  python3 bt_lab.py --variant F1 --scalp-only
النتائج: download/el2_backtest/<tag>/ + طباعة مقارنة.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

import backtest_el2 as bt                                    # noqa: E402
from strategies import indicators as ind                     # noqa: E402
from strategies.base import ScalpContext                     # noqa: E402
from engine.pattern_detector import PivotDetector, DetectorConfig  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# تعريف التجارب
# ─────────────────────────────────────────────────────────────────────────────

VARIANTS: Dict[str, Dict[str, Any]] = {
    # خط أساس الصحة — يطابق الإنتاج حرفيًا
    "BASE": {},
    # سكالب: بوابة اتجاهية + انحياز 1h
    "S1": {"scalp": {"di_gate": True, "htf_gate": True}},
    # سكالب: + دخول ارتدادي (لا مطاردة شمعة الانفجار)
    "S2": {"scalp": {"di_gate": True, "htf_gate": True,
                     "retrace": {"atr": 0.35, "expiry": 4}}},
    # سكالب: ارتداد أعمق وصبر أطول
    "S3": {"scalp": {"di_gate": True, "htf_gate": True,
                     "retrace": {"atr": 0.50, "expiry": 6}}},
    # سكالب: الحزمة الكاملة — تتبع بعد الجزئي + جودة R:R + حظر السلاسل
    "S4": {"scalp": {"di_gate": True, "htf_gate": True,
                     "retrace": {"atr": 0.35, "expiry": 4},
                     "trail": {"atr": 1.0}, "min_rr1": 0.45,
                     "blackout": {"losses": 3, "hours": 12}}},
    # سكالب: كالـS4 بلا تتبع (عزل أثره)
    "S5": {"scalp": {"di_gate": True, "htf_gate": True,
                     "retrace": {"atr": 0.35, "expiry": 4},
                     "min_rr1": 0.45, "blackout": {"losses": 3, "hours": 12}}},
    # سكالب: ارتداد مع رفض مؤكد (شمعة اللمس تغلق فوق الحد — مضاد السكاكين الساقطة)
    "S6": {"scalp": {"di_gate": True, "htf_gate": True,
                     "retrace": {"atr": 0.50, "expiry": 6, "confirm": True}}},
    # سكالب: S6 + أرضية وقف من الملء 0.5×ATR (تنفّس أوسع ضد الضجيج)
    "S7": {"scalp": {"di_gate": True, "htf_gate": True,
                     "retrace": {"atr": 0.50, "expiry": 6, "confirm": True,
                                 "sl_floor_atr": 0.5}}},
    # سكالب: ارتداد أعمق + رفض مؤكد
    "S8": {"scalp": {"di_gate": True, "htf_gate": True,
                     "retrace": {"atr": 0.60, "expiry": 8, "confirm": True}}},
    # موجات: E1 + تتبع 15m بعد +1R + معلق أطول
    "E2": {"elliott": {"htf_gate": True, "rr_min": 0.9, "tp_min_rr": 0.9,
                       "trail": {"atr": 2.5}, "pending_candles": 10}},
    # موجات: انحياز 1h + أرضيات R:R أعلى (جودة قبل الكم)
    "E1": {"elliott": {"htf_gate": True, "rr_min": 0.9, "tp_min_rr": 0.9}},
    # موجات: أرضية معتدلة 0.7
    "E3": {"elliott": {"htf_gate": True, "rr_min": 0.7, "tp_min_rr": 0.7}},
    # موجات: E3 + سقف المخاطرة البنيوية 2.5×ATR15 (تضييق R لمضاعفة المضاعفات)
    "E4": {"elliott": {"htf_gate": True, "rr_min": 0.7, "tp_min_rr": 0.7,
                       "sl_cap_atr": 2.5}},
    # موجات: E4 بسقف أضيق 2.0 + تتبع 15م بعد +1R + معلق أطول
    "E5": {"elliott": {"htf_gate": True, "rr_min": 0.7, "tp_min_rr": 0.7,
                       "sl_cap_atr": 2.0, "trail": {"atr": 2.5},
                       "pending_candles": 10}},
    # مصفوفة S8 الدقيقة:
    "S9": {"scalp": {"di_gate": True, "htf_gate": True,
                     "retrace": {"atr": 0.60, "expiry": 8, "confirm": True,
                                 "sl_floor_atr": 0.5}}},
    "S10": {"scalp": {"di_gate": True, "htf_gate": True,
                      "retrace": {"atr": 0.60, "expiry": 8, "confirm": True},
                      "blackout": {"losses": 3, "hours": 12}}},
    "S11": {"scalp": {"di_gate": True, "htf_gate": True,
                      "retrace": {"atr": 0.70, "expiry": 10, "confirm": True}}},
    "S12": {"scalp": {"di_gate": True, "htf_gate": True,
                      "retrace": {"atr": 0.60, "expiry": 8, "confirm": True},
                      "trail": {"atr": 1.0}}},
    # حساسية الجوار حول F1:
    "G1": {"scalp": {"di_gate": True, "htf_gate": True,
                     "retrace": {"atr": 0.55, "expiry": 8, "confirm": True},
                     "trail": {"atr": 1.0}},
           "elliott": {"sl_cap_atr": 1.8, "pending_candles": 10}},
    "G2": {"scalp": {"di_gate": True, "htf_gate": True,
                     "retrace": {"atr": 0.65, "expiry": 8, "confirm": True},
                     "trail": {"atr": 1.0}},
           "elliott": {"sl_cap_atr": 2.2, "pending_candles": 10}},
    # جولة 2 — بلا انحياز 1h (ضرّ بمدخلات القيعان):
    "E6": {"elliott": {"sl_cap_atr": 2.5}},
    "E7": {"elliott": {"sl_cap_atr": 2.0, "pending_candles": 10}},
    "E8": {"elliott": {"pending_candles": 10}},
    "E9": {"elliott": {"sl_cap_atr": 2.5, "pending_candles": 10,
                       "trail": {"atr": 2.5}}},
    # الحزمة الفائزة النهائية — سكالب S12 + موجات E7
    "F1": {"scalp": {"di_gate": True, "htf_gate": True,
                     "retrace": {"atr": 0.60, "expiry": 8, "confirm": True},
                     "trail": {"atr": 1.0}},
           "elliott": {"sl_cap_atr": 2.0, "pending_candles": 10}},
}


# ─────────────────────────────────────────────────────────────────────────────
# شموع 1h من 5m (بلا أي بيانات إضافية) — مؤشرات الفريم الأعلى بلا نظرة مستقبلية
# ─────────────────────────────────────────────────────────────────────────────

class HTF1h:
    """تجميع 1h من 5m + SuperTrend(10,3.0) يُحدَّث عند إغلاق كل شمعة ساعة فقط.
    شمعة الساعة [H, H+3600) مغلقة منطقيًا عند T ≥ H+3600 — لا قرار مبكر."""

    PERIOD, MULT, MAXBARS = 10, 3.0, 400

    def __init__(self, df5: pd.DataFrame):
        ts = df5["timestamp"].values.astype(np.int64)
        o = df5["open"].values
        h = df5["high"].values
        l = df5["low"].values
        c = df5["close"].values
        bk = ts // 3600000
        self.ends: List[int] = []
        self.O: List[float] = []
        self.H: List[float] = []
        self.L: List[float] = []
        self.C: List[float] = []
        start = 0
        n = len(ts)
        for i in range(1, n + 1):
            if i == n or bk[i] != bk[start]:
                self.ends.append(int((bk[start] + 1) * 3600000))
                self.O.append(float(o[start]))
                self.H.append(float(h[start:i].max()))
                self.L.append(float(l[start:i].min()))
                self.C.append(float(c[i - 1]))
                start = i
        self.ptr = 0
        self.st: Optional[Dict[str, float]] = None

    def advance(self, t_ms: int) -> None:
        moved = False
        while self.ptr < len(self.ends) and self.ends[self.ptr] <= t_ms:
            self.ptr += 1
            moved = True
        if moved:
            a = max(0, self.ptr - self.MAXBARS)
            self.st = ind.supertrend(list(self.H[a:self.ptr]),
                                     list(self.L[a:self.ptr]),
                                     list(self.C[a:self.ptr]),
                                     self.PERIOD, self.MULT)


# ─────────────────────────────────────────────────────────────────────────────
# سكالب المتغير — قوالب booleans + أوامر ارتدادية + تتبع + حظر سلاسل
# ─────────────────────────────────────────────────────────────────────────────

class LabScalpSim(bt.ScalpSim):
    def __init__(self, book: bt.Book, stats: Dict[str, Any], var: Dict[str, Any],
                 htf_map: Dict[str, HTF1h]):
        super().__init__(book, stats)
        self.var = var or {}
        self.htf_map = htf_map
        self.orders: Dict[str, Dict[str, Any]] = {}      # أوامر ارتدادية معلقة
        self.loss_streak: Dict[str, int] = {}
        if self.var.get("min_rr1"):
            self.cfg.rr_net_min = float(self.var["min_rr1"])   # نفس كائن cfg لدى FlowIgnition

    # ── إغلاق نهائي يحدّث سلسلة الخسائر والحظر ──
    def _close_final(self, pos: bt.Position, price: float, t_ms: int, reason: str,
                     stat_key: str) -> None:
        self.book.close_leg(pos, pos.qty, price, t_ms, reason)
        self._finish(pos, t_ms)
        self.stats["scalp_closes"][stat_key] = self.stats["scalp_closes"].get(stat_key, 0) + 1
        blk = self.var.get("blackout") or {}
        tr = self.book.trades[-1] if self.book.trades else None
        pnl = tr.pnl if (tr and tr.kind == "SCALP" and tr.symbol == pos.symbol) else 0.0
        if pnl > 0:
            self.loss_streak[pos.symbol] = 0
        elif pnl < 0:
            n_streak = self.loss_streak.get(pos.symbol, 0) + 1
            self.loss_streak[pos.symbol] = n_streak
            if blk and n_streak >= int(blk.get("losses", 3)):
                until = t_ms + int(float(blk.get("hours", 12)) * 3600_000)
                self.cooldowns[pos.symbol] = max(self.cooldowns.get(pos.symbol, 0), until)
                self.stats["scalp_blackouts"] = self.stats.get("scalp_blackouts", 0) + 1
                self.loss_streak[pos.symbol] = 0

    # ── إدارة الأمر الارتدادي المعلق (ملء/إبطال/انتهاء) ──
    def _manage_order(self, sym: str, t_ms: int, candle: Dict[str, float]) -> None:
        od = self.orders.get(sym)
        if od is None:
            return
        lo, hi, op, close = candle["low"], candle["high"], candle["open"], candle["close"]
        if close < od["sl"]:                                   # الفرضية أُبطلت قبل الملء
            del self.orders[sym]
            self.cooldowns[sym] = t_ms + 15 * 60_000
            self.stats["scalp_orders"]["إبطال"] = self.stats["scalp_orders"].get("إبطال", 0) + 1
            return
        if t_ms > od["expires_ms"]:
            del self.orders[sym]
            self.cooldowns[sym] = t_ms + 15 * 60_000
            self.stats["scalp_orders"]["انتهاء"] = self.stats["scalp_orders"].get("انتهاء", 0) + 1
            return
        if lo > od["limit"]:
            return                                             # لم تصل منطقة الارتداد بعد
        if od.get("confirm") and close < od["limit"]:
            return              # لمس بلا رفض = سكين ساقط — ننتظر شمعة تغلق فوق الحد
        fill = min(od["limit"], op)                            # فجوة تحت الحد → ملء بالفتح (أفضل)
        del self.orders[sym]
        self.stats["scalp_orders"]["ملء"] = self.stats["scalp_orders"].get("ملء", 0) + 1
        sl_eff = od["sl"]
        sf = od.get("sl_floor_atr")
        if sf and od.get("atr"):
            sl_eff = min(sl_eff, fill - float(sf) * od["atr"])  # تنفّس أوسع ضد ضجيج الوقف
        qty, why = self._size(fill, sl_eff)
        if not qty:
            self.stats["scalp_rejects"][why] = self.stats["scalp_rejects"].get(why, 0) + 1
            return
        pos = bt.Position(kind="SCALP", symbol=sym, qty=qty, entry=fill, sl=sl_eff,
                          tp1=od["tp1"], tp2=od["tp2"], tp_final=od["tp2"],
                          opened_ms=t_ms,
                          meta={"qty0": qty, "rr_planned": od["rr1"],
                                "reason": od["reason"][:120], "retrace": True})
        self.book.balance -= self.book.leg_fee(qty * fill)
        pos.meta["pnl_acc"] = -self.book.leg_fee(qty * fill)
        self.positions[sym] = pos
        self.stats["scalp_signals"] += 1
        # نفس شمعة الملء تُدار — الوقف أولًا (عقيدة المحرك)
        if lo <= pos.sl:
            self._close_final(pos, pos.sl, t_ms, "وقف", "وقف")
            return
        self._manage_open_legs(pos, hi, t_ms)

    # ── الجزئي والهدف الثاني (مشترك) — يعيد حدث فعل (كعلم did الإنتاجي) ──
    def _manage_open_legs(self, pos: bt.Position, hi: float, t_ms: int) -> bool:
        did = False
        if pos.tp1 and not pos.meta.get("partial_done") and hi >= pos.tp1:
            self.book.close_leg(pos, pos.qty * self.cfg.partial_pct / 100.0,
                                pos.tp1, t_ms, "هدف1-جزئي")
            pos.sl = pos.entry
            pos.meta["partial_done"] = True
            self.stats["partials_scalp"] += 1
            did = True
        if pos.qty > 1e-12 and pos.tp_final and hi >= pos.tp_final:
            self._close_final(pos, pos.tp_final, t_ms, "هدف2", "هدف2")
            did = True
        return did

    def on_candle(self, sym: str, t_ms: int, rows5: List[dict], rows15: List[dict],
                  elliott_busy: set) -> None:
        c = rows5[-1]
        # 1) الأمر المعلق أولًا (قد يولّد موضعًا يُدار فورًا)
        self._manage_order(sym, t_ms, c)
        # 2) إدارة الموضع المفتوح — وقف-أولًا intrabar
        pos = self.positions.get(sym)
        if pos is not None:
            hi, lo, close = c["high"], c["low"], c["close"]
            tr_var = self.var.get("trail") or {}
            if pos.meta.get("trail") is not None:              # تتبع آخر إغلاق يفعّل من هذه الشمعة
                pos.sl = max(pos.sl, pos.meta["trail"])
            if lo <= pos.sl:
                self._close_final(pos, pos.sl, t_ms, "وقف", "وقف")
            else:
                did = self._manage_open_legs(pos, hi, t_ms)
                pos = self.positions.get(sym)
                if pos is not None and pos.qty > 1e-12:
                    a = (ind.atr([r["high"] for r in rows5], [r["low"] for r in rows5],
                                 [r["close"] for r in rows5], 14)
                         if (tr_var and pos.meta.get("partial_done")) else None)
                    if tr_var and a:
                        tr_new = close - float(tr_var["atr"]) * a
                        pos.meta["trail"] = max(pos.meta.get("trail") or tr_new, tr_new)
                    if not did:                                # علم did الإنتاجي — بلا خروج مبكر في شمعة فعل
                        cv = ind.cvd_series(rows5)
                        st = ind.supertrend([r["high"] for r in rows5], [r["low"] for r in rows5],
                                            [r["close"] for r in rows5], 10, 2.5)
                        if cv and st and cv["cvd"][-1] < cv["ema"][-1] and close < st["line"]:
                            self._close_final(pos, close, t_ms, "انقلاب الدلتا", "انقلاب الدلتا")
                        elif t_ms - pos.opened_ms > self.cfg.max_hold_min * 60_000:
                            self._close_final(pos, close, t_ms,
                                              f"مهلة {self.cfg.max_hold_min}د", "مهلة")
        # 3) تقييم دخول جديد — لا تقييم إن وضع معلق أو موضع مفتوح (بوابات الإنتاج أولًا)
        self.stats["scalp_cycles"] += 1
        if sym in self.orders:
            return
        ok, why = self._entry_ok(sym, t_ms, elliott_busy)
        if not ok:
            self.stats["scalp_rejects"][why] = self.stats["scalp_rejects"].get(why, 0) + 1
            return
        atr5 = ind.atr([r["high"] for r in rows5], [r["low"] for r in rows5],
                       [r["close"] for r in rows5], 14)
        ctx = ScalpContext(symbol=sym, now_ts=t_ms / 1000.0, k5=rows5, k15=rows15,
                           live_price=float(c["close"]), depth=None,
                           cvd_source="taker", atr5=atr5, atr15=None,
                           fib_confluence=None, extra={"fee_rate": bt.FEE_RATE})
        try:
            sig = self.strategy.evaluate(ctx)
        except Exception:
            self.stats["scalp_eval_errors"] += 1
            return
        if not sig or sig.side != "LONG":
            return
        # ── الرافعات ما بعد الإشارة ──
        gates = self.stats.setdefault("scalp_gates", {})
        if self.var.get("di_gate"):
            d = ind.di([r["high"] for r in rows5], [r["low"] for r in rows5],
                       [r["close"] for r in rows5], 14)
            if not d or d["pdi"] <= d["mdi"]:
                gates["di"] = gates.get("di", 0) + 1
                return
        if self.var.get("htf_gate"):
            st1 = (self.htf_map.get(sym).st if self.htf_map.get(sym) else None)
            if not st1 or st1.get("dir") != 1.0:
                gates["htf"] = gates.get("htf", 0) + 1
                return
        entry_ref = float(c["close"])
        ret = self.var.get("retrace")
        if ret:
            a = atr5 or 0.0
            if a <= 0:
                return
            self.orders[sym] = {
                "limit": entry_ref - float(ret["atr"]) * a,
                "sl": float(sig.sl), "tp1": float(sig.tp1), "tp2": float(sig.tp2),
                "rr1": float(sig.rr1 or 0.0), "reason": sig.reason,
                "armed_ms": t_ms, "atr": a,
                "confirm": bool(ret.get("confirm")),
                "sl_floor_atr": ret.get("sl_floor_atr"),
                "expires_ms": t_ms + int(ret["expiry"]) * 300_000,
            }
            self.stats["scalp_orders"]["وُلد"] = self.stats["scalp_orders"].get("وُلد", 0) + 1
            return
        # ملء فوري (مسار الإنتاج) مع الرافعات غير الارتدادية
        qty, why = self._size(entry_ref, sig.sl)
        if not qty:
            self.stats["scalp_rejects"][why] = self.stats["scalp_rejects"].get(why, 0) + 1
            return
        pos = bt.Position(kind="SCALP", symbol=sym, qty=qty, entry=entry_ref, sl=sig.sl,
                          tp1=sig.tp1, tp2=sig.tp2, tp_final=sig.tp2, opened_ms=t_ms,
                          meta={"qty0": qty, "rr_planned": float(sig.rr1 or 0.0),
                                "reason": sig.reason[:120]})
        self.book.balance -= self.book.leg_fee(qty * entry_ref)
        pos.meta["pnl_acc"] = -self.book.leg_fee(qty * entry_ref)
        self.positions[sym] = pos
        self.stats["scalp_signals"] += 1


# ─────────────────────────────────────────────────────────────────────────────
# موجات المتغير — انحياز 1h + تتبع 15m بعد +1R
# ─────────────────────────────────────────────────────────────────────────────

class LabElliottSim(bt.ElliottSim):
    def __init__(self, book: bt.Book, stats: Dict[str, Any], flow_filter_on: bool,
                 symbols: List[str], var: Dict[str, Any], htf_map: Dict[str, HTF1h]):
        super().__init__(book, stats, flow_filter_on, symbols)
        self.var = var or {}
        self.htf_map = htf_map
        self.atr15_map: Dict[str, Optional[float]] = {}
        self._pending_candles = int(self.var.get("pending_candles") or bt.PENDING_MAX_CANDLES)
        self._tp_min_rr = float(self.var.get("tp_min_rr") or bt.TP_MIN_RR)
        self._rr_min = float(self.var.get("rr_min") or bt.RR_NET_MIN)

    def manage_open(self, sym: str, t_ms: int, candle: dict,
                    rows15: Optional[List[dict]] = None) -> None:
        pos = self.positions.get(sym)
        if pos is None:
            return
        hi, lo = candle["high"], candle["low"]
        if lo <= pos.sl:                                       # الوقف أولًا — دائمًا
            self.book.close_leg(pos, pos.qty, pos.sl, t_ms, "وقف بنيوي")
            self._finish(pos)
            self.stats["ell_closes"]["وقف"] = self.stats["ell_closes"].get("وقف", 0) + 1
            return
        trigger = pos.entry + pos.meta["r1"] * bt.BE_TRIGGER_R
        if bt.BE_AT_R_ENABLED and not pos.meta.get("be_done") and hi >= trigger:
            if bt.PARTIAL_AT_R_ENABLED and not pos.meta.get("partial_done"):
                self.book.close_leg(pos, pos.qty * bt.PARTIAL_CLOSE_PCT / 100.0,
                                    trigger, t_ms, "جزئي +1R")
                pos.meta["partial_done"] = True
                self.stats["partials_elliott"] += 1
            if pos.sl < pos.entry:
                pos.sl = pos.entry
                pos.meta["be_done"] = True
        for stage, flag in (("tp1", "tp1_done"), ("tp2", "tp2_done")):
            lvl = pos.meta.get(stage)
            if not lvl or pos.meta.get(flag) or pos.qty <= 1e-12:
                continue
            if not (pos.tp_final > lvl * 1.0005):
                continue
            if hi >= lvl:
                self.book.close_leg(pos, pos.qty * bt.TP_STAGE_SLICE_PCT / 100.0,
                                    lvl, t_ms, f"مرحلة {stage.upper()}")
                pos.meta[flag] = True
        if pos.qty > 1e-12 and hi >= pos.tp_final:
            self.book.close_leg(pos, pos.qty, pos.tp_final, t_ms, "هدف 1.618/سقف")
            self._finish(pos)
            self.stats["ell_closes"]["هدف"] = self.stats["ell_closes"].get("هدف", 0) + 1
            return
        # تتبع 15m بعد الحماية — يُثبَّت من إغلاق هذه الشمعة ويعمل من التالية (بلا نظرة مستقبلية)
        tr_var = self.var.get("trail") or {}
        if tr_var and pos.meta.get("be_done") and pos.qty > 1e-12 and rows15:
            h15 = [r["high"] for r in rows15]
            l15 = [r["low"] for r in rows15]
            c15 = [r["close"] for r in rows15]
            a15 = ind.atr(h15, l15, c15, 14)
            if a15 and a15 > 0:
                trail = float(c15[-1]) - float(tr_var["atr"]) * a15
                if trail > pos.entry:                          # أرضية BE — التتبع لا ينزل تحت الدخول
                    pos.sl = max(pos.sl, trail)

    def manage_pending(self, sym: str, t_ms: int, candle: dict) -> None:
        pend = self.pendings.get(sym)
        if pend is None:
            return
        close, lo = candle["close"], candle["low"]
        if close < pend.p0:
            del self.pendings[sym]
            self.cooldowns[sym] = t_ms + int(bt.SYMBOL_COOLDOWN_SEC * 1000)
            self.stats["ell_pending"]["إبطال بنيوي"] = \
                self.stats["ell_pending"].get("إبطال بنيوي", 0) + 1
            return
        if t_ms > pend.expires_ms:
            del self.pendings[sym]
            self.cooldowns[sym] = t_ms + int(bt.SYMBOL_COOLDOWN_SEC * 1000)
            self.stats["ell_pending"]["انتهاء"] = self.stats["ell_pending"].get("انتهاء", 0) + 1
            return
        if lo <= pend.entry:
            fill = pend.entry if close >= pend.entry else close
            del self.pendings[sym]
            pos = bt.Position(kind="ELLIOTT", symbol=sym, qty=pend.qty, entry=fill,
                              sl=pend.sl, tp1=pend.tp1, tp2=pend.tp2,
                              tp_final=pend.tp_final, opened_ms=t_ms,
                              meta={"qty0": pend.qty, "rr_planned": pend.rr_planned,
                                    "p0": pend.p0, "r1": fill - pend.sl,
                                    "tp1": pend.tp1, "tp2": pend.tp2, "basis": pend.basis})
            self.book.balance -= self.book.leg_fee(pend.qty * fill)
            pos.meta["pnl_acc"] = -self.book.leg_fee(pend.qty * fill)
            self.positions[sym] = pos
            self.stats["ell_pending"]["ملء"] = self.stats["ell_pending"].get("ملء", 0) + 1
            self.manage_open(sym, t_ms, candle)

    def detect(self, sym: str, t_ms: int, df15: pd.DataFrame, rows5: List[dict],
               week_hi: Optional[float], busy_extra: Optional[set] = None) -> None:
        # انحياز الفريم الأعلى — قبل سلسلة القبول (بنية → تدفق → انحياز 1h)
        if self.var.get("htf_gate"):
            st1 = (self.htf_map.get(sym).st if self.htf_map.get(sym) else None)
            if not st1 or st1.get("dir") != 1.0:
                g = self.stats.setdefault("ell_gates", {})
                g["htf"] = g.get("htf", 0) + 1
                return
        super().detect(sym, t_ms, df15, rows5, week_hi, busy_extra)

    def _register_pending(self, sym, t_ms, entry, sl, tp_final, tp1, tp2, basis,
                          best, qty, rr_planned) -> None:
        # رافعة سقف المخاطرة البنيوية: وقف أضيق من البنيوي إن كان أوسع من cap×ATR15
        # — يضيّق R فيتضاعف المضاعف المخطط، والحجم يعاد حسابه على المخاطرة الجديدة
        cap = self.var.get("sl_cap_atr")
        if cap:
            a15 = self.atr15_map.get(sym)
            if a15 and a15 > 0:
                sl_capped = max(sl, entry - float(cap) * a15)
                if sl_capped > sl:
                    sl = sl_capped
                    q2 = self._size_elliott(entry, sl)
                    if q2:
                        qty = q2
                    risk = entry - sl
                    if risk > 0:
                        rr_planned = round((tp_final - entry) / risk, 2)
        self.pendings[sym] = bt.PendingElliott(
            symbol=sym, entry=entry, sl=sl, tp1=tp1, tp2=tp2, tp_final=tp_final,
            p0=float(best.pivot_prices[0]), qty=qty, created_ms=t_ms,
            expires_ms=t_ms + self._pending_candles * bt.TF_SEC[bt.ENTRY_TF] * 1000,
            rr_planned=rr_planned, basis=basis)
        self.stats["ell_pending"]["وُلد"] = self.stats["ell_pending"].get("وُلد", 0) + 1


# ─────────────────────────────────────────────────────────────────────────────
# الحلقة الرئيسية — نفس حلقة backtest_el2.run مع ربط الرافعات
# ─────────────────────────────────────────────────────────────────────────────

def run_lab(args) -> Dict[str, Any]:
    var = VARIANTS.get(args.variant, {})
    sc_var = var.get("scalp", {})
    el_var = var.get("elliott", {})
    # رافعات مستوى الثوابت (موجات) — تُثبَّت قبل الحلقة
    if el_var.get("tp_min_rr"):
        bt.TP_MIN_RR = float(el_var["tp_min_rr"])
    if el_var.get("rr_min"):
        bt.RR_NET_MIN = float(el_var["rr_min"])
    if el_var.get("pending_candles"):
        bt.PENDING_MAX_CANDLES = int(el_var["pending_candles"])

    t0_wall = time.time()
    symbols = bt.load_symbols(args.symbols)
    end_ms = int(time.time() * 1000) // (bt.TF_SEC["5m"] * 1000) * (bt.TF_SEC["5m"] * 1000)
    fetch_days = args.days + 8
    sim_start_ms = end_ms - args.days * 86400_000

    print(f"═" * 78)
    print(f"مختبر الباك تاست [BT-LAB] — التجربة: {args.variant}")
    print(f"  سكالب: {sc_var or 'إنتاج'}")
    print(f"  موجات: {el_var or 'إنتاج'}")
    print(f"═" * 78)

    ds = bt.DataStore(refresh=args.refresh)
    data: Dict[str, Dict[str, Any]] = {}
    for i, sym in enumerate(symbols, 1):
        df5 = ds.fetch(sym, "5m", fetch_days, end_ms)
        df15 = ds.fetch(sym, "15m", fetch_days, end_ms)
        if len(df5) < 200 or len(df15) < 60:
            print(f"  [تخطٍ] {sym}: بيانات غير كافية")
            continue
        data[sym] = {"df5": df5, "df15": df15,
                     "day_hi": bt.daily_highs_from_15m(df15, fetch_days),
                     "htf": HTF1h(df5) if (sc_var.get("htf_gate") or el_var.get("htf_gate")) else None}
        print(f"  [{i}/{len(symbols)}] {sym}: {len(df5)}×5m {len(df15)}×15m")
    symbols = [s for s in symbols if s in data]
    if not symbols:
        raise SystemExit("لا رموز ببيانات كافية")

    warm15 = 500 * bt.TF_SEC["15m"] * 1000
    warm5 = 200 * bt.TF_SEC["5m"] * 1000
    start_ms = max(sim_start_ms,
                   int(data[symbols[0]]["df5"]["timestamp"].iloc[0]) + warm5,
                   int(data[symbols[0]]["df15"]["timestamp"].iloc[0]) + warm15)
    start_ms = (start_ms // (bt.TF_SEC["5m"] * 1000)) * (bt.TF_SEC["5m"] * 1000)

    for sym in symbols:
        d5, d15 = data[sym]["df5"], data[sym]["df15"]
        data[sym]["idx5"] = {int(ts): j for j, ts in enumerate(d5["timestamp"].values)}
        data[sym]["idx15"] = {int(ts): j for j, ts in enumerate(d15["timestamp"].values)}

    stats: Dict[str, Any] = {
        "scalp_cycles": 0, "scalp_signals": 0, "partials_scalp": 0,
        "partials_elliott": 0, "scalp_blackouts": 0,
        "scalp_closes": {}, "scalp_rejects": {}, "scalp_eval_errors": 0,
        "scalp_orders": {}, "scalp_gates": {},
        "ell_scans": 0, "ell_bull_setups": 0, "ell_scan_errors": 0,
        "ell_rejects": {}, "ell_flow_rejects": {}, "ell_flow_unavailable": 0,
        "ell_gates": {}, "ell_pending": {}, "ell_closes": {},
    }
    book = bt.Book(args.balance)
    scalp_syms = symbols[:args.scalp_symbols]
    scalp = LabScalpSim(book, stats, sc_var,
                        {s: data[s]["htf"] for s in symbols}) if not args.elliott_only else None
    elliott = LabElliottSim(book, stats, flow_filter_on=not args.no_flow_filter,
                            symbols=symbols, var=el_var,
                            htf_map={s: data[s]["htf"] for s in symbols}
                            ) if not args.scalp_only else None

    dq5: Dict[str, deque] = {s: deque(maxlen=220) for s in symbols}
    dq15: Dict[str, deque] = {s: deque(maxlen=bt.DETECT_WINDOW_BARS + 20) for s in symbols}

    steps = list(range(start_ms, end_ms, bt.TF_SEC["5m"] * 1000))
    print(f"\nالحلقة: {len(steps):,} دورة 5m × {len(symbols)} رمزًا\n")
    t_last_report = time.time()

    for n, T in enumerate(steps):
        book.roll_day(T)
        boundary15 = (T % (bt.TF_SEC["15m"] * 1000) == 0)
        hour_boundary = (T % 3600000 == 0)
        for sym in symbols:
            d = data[sym]
            if d["htf"] is not None and hour_boundary:
                d["htf"].advance(T)
            j = d["idx5"].get(T - bt.TF_SEC["5m"] * 1000)
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
                k = d["idx15"].get(T - bt.TF_SEC["15m"] * 1000)
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
            rows15 = list(dq15[sym])[-bt.SCAN_K15_LIMIT:]

            if boundary15 and elliott and candle15 is not None:
                if rows15:
                    elliott.atr15_map[sym] = ind.atr(
                        [r["high"] for r in rows15], [r["low"] for r in rows15],
                        [r["close"] for r in rows15], 14)
                elliott.manage_open(sym, T, candle15, rows15=rows15)
                elliott.manage_pending(sym, T, candle15)
                dfw = d["df15"]
                lo_idx = d["idx15"].get(T - bt.TF_SEC["15m"] * 1000, 0)
                a = max(0, lo_idx - bt.DETECT_WINDOW_BARS + 1)
                win = dfw.iloc[a:lo_idx + 1]
                if len(win) >= 60:
                    win = win.copy()
                    win["timestamp"] = pd.to_datetime(win["timestamp"], unit="ms", utc=True)
                    busy = set(elliott.pendings) | set(elliott.positions)
                    elliott.detect(sym, T, win, rows5,
                                   bt.weekly_high_at(d["day_hi"], T),
                                   busy_extra=(busy | set(scalp.positions) | set(scalp.orders))
                                   if scalp else busy)

            if scalp and sym in scalp_syms and len(rows5) >= 60:
                busy_e = (set(elliott.pendings) | set(elliott.positions)) if elliott else set()
                scalp.on_candle(sym, T, rows5, rows15, busy_e)

        if time.time() - t_last_report > 30.0:
            pct = 100.0 * (n + 1) / len(steps)
            print(f"  ... {pct:5.1f}% | رصيد {book.balance:,.2f} | صفقات {len(book.trades)}",
                  flush=True)
            t_last_report = time.time()

    # تسوية النهاية
    open_syms = set()
    if scalp:
        open_syms |= set(scalp.positions.keys()) | set(scalp.orders.keys())
    if elliott:
        open_syms |= set(elliott.positions.keys())
    for sym in sorted(open_syms):
        last5 = data[sym]["df5"].iloc[-1]
        px = float(last5["close"])
        if scalp:
            od = scalp.orders.pop(sym, None)
            if od:
                continue                                     # أمر لم يُملأ — لا أثر محاسبي
        pos = (scalp.positions.get(sym) if scalp else None) or \
              (elliott.positions.get(sym) if elliott else None)
        if pos:
            book.close_leg(pos, pos.qty, px, end_ms, "نهاية الفترة")
            if pos.kind == "SCALP" and scalp:
                scalp._finish(pos, end_ms)
            elif elliott:
                elliott._finish(pos)

    # منحنى الرصيد
    day_pnl: Dict[int, float] = {}
    for tr in book.trades:
        day_pnl[tr.closed_ms // 86400_000] = day_pnl.get(tr.closed_ms // 86400_000, 0) + tr.pnl
    eq = []
    bal = book.start_balance
    for d in sorted(day_pnl):
        bal += day_pnl[d]
        eq.append((d * 86400_000, bal))

    result = bt.summarize(args, symbols, scalp_syms, book, stats, eq, ds.provider_used,
                          start_ms, end_ms, time.time() - t0_wall)
    result["variant"] = {"name": args.variant, "scalp": sc_var, "elliott": el_var}
    result["scalp"]["orders"] = stats.get("scalp_orders", {})
    result["scalp"]["gates"] = stats.get("scalp_gates", {})
    result["scalp"]["blackouts"] = stats.get("scalp_blackouts", 0)
    result["elliott"]["gates"] = stats.get("ell_gates", {})
    bt.report(result, book)
    bt.save_outputs(args, result, book, eq)
    return result


def main():
    ap = argparse.ArgumentParser(description="مختبر تجارب الباك تاست BT-LAB")
    ap.add_argument("--variant", default="BASE", choices=sorted(VARIANTS.keys()))
    ap.add_argument("--symbols", default="12")
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--balance", type=float, default=10000.0)
    ap.add_argument("--no-flow-filter", action="store_true")
    ap.add_argument("--scalp-only", action="store_true")
    ap.add_argument("--elliott-only", action="store_true")
    ap.add_argument("--scalp-symbols", type=int, default=bt.SCALP_SYMBOLS_N)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    a.tag = a.tag or f"lab_{a.variant}"
    run_lab(a)


if __name__ == "__main__":
    main()
