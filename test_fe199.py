#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات FE1.9.13 «أهداف سكالبينج واقعية متدرجة»
=================================================
الطلب الحي: «لا يزال هناك إشكال في احتساب الأهداف — البوت يضع أهدافًا بعيدة لم
تصلها العملة منذ أكثر من شهر. عالج آلية تحديد الأهداف بحيث لا يتجاوز الهدف قممًا
تاريخية لأقل من أسبوع — البوت مصمم للسبوت سكالبينج — ولا بأس في أهداف مراحل
(الهدف الأول والثاني والثالث)».

ما يُغطيه الملف:
  1) weekly_high: قمة آخر 7 أيام (كاش ناجح 30د + كاش سلبي للفشل)
  2) build_staged_targets: القص على السقف + أرضية R:R الصافي + إزالة التقارب + الانهيار لمرحلة مفردة
  3) create_pending_signal: تخزين tp1/tp2/tp3/weekly_high + المسار التراثي بلا قمة
  4) رفض «لا هدف واقعي تحت سقف الأسبوع» بعداد rejected_weekly_cap وسبب مسمّى
  5) _tp_stage_step (ورقي): رجل 40% عند tp1 ثم tp2، مرة واحدة لكل مرحلة، والمرحلة المفردة تُتخطى
  6) _tp_stage_step (حقيقي): غبار باينانس يُعتبر منجزًا بلا أمر بيع
  7) reconcile_live_targets: قصّ الصفقات الحية فوق القمة + بلاغ TARGET_FIX مرة واحدة + إعادة قص صامتة + انهيار المراحل
  8) تكامل monitor_step: حماية +1R ثم مرحلتا tp1/tp2 ثم الإغلاق النهائي عند take_profit
  9) ترحيل أعمدة tp1/tp2/tp3/weekly_high + tp_stages في /api/all + صدى الحماية
 10) بوابة تلغرام تمرر TARGET_FIX + تزامن الإصدار + سطر المراحل في اللوحة

التصميم: weekly_high معزولة عن الشبكة في كل الاختبارات (conftest autouse) —
القص fail-open عند فشل جلب القمة (السلوك القديم حرفيًا بلا ادّعاء).
"""

import json
import time
from types import SimpleNamespace

import pandas as pd
import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة
import panel

# الأصلية قبل مصيدة conftest — لاختبارات weekly_high ذاتها
_REAL_WEEKLY_HIGH = vnz.weekly_high


# ─────────────────────────────────────────────────────────────────────────────
# أدوات
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def clean_db(monkeypatch):
    """قاعدة SQLite مؤقتة لكل اختبار — عزل كامل."""
    monkeypatch.setattr(vnz, "USE_POSTGRES", False)
    import sqlite3
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    old = vnz.db.conn
    vnz.db.conn = conn
    vnz.init_db()
    yield
    vnz.db.conn = old


@pytest.fixture()
def tg_off(monkeypatch):
    monkeypatch.setattr(vnz, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(vnz, "TELEGRAM_CHAT_ID", "")
    monkeypatch.setattr(vnz, "_tg_dedup", {})
    yield


def ladder_of(pairs):
    """سلّم ثابت للاختبار — يستبدل compute_tp_ladder داخل build_staged_targets."""
    return [(p, b) for p, b in pairs]


def _df_from_highs(highs):
    return pd.DataFrame({"high": highs})


def insert_open(**kw):
    """صفقة مفتوحة ورقية جاهزة للمراقبة/التسوية."""
    base = dict(symbol="TEST/USDT", direction="BULLISH", strategy_name="Elliott_Fibonacci",
                status="open", entry_price=100.0, fill_price=100.0, stop_loss=98.0,
                take_profit=130.0, quantity=100.0, notional_usdt=10000.0, rr_ratio=15.0,
                created_at=vnz.utc_now_iso(), filled_at=vnz.utc_now_iso(), is_real=0,
                initial_quantity=100.0, realized_pnl_usdt=0, peak_price=100.0)
    base.update(kw)
    cols = ", ".join(base.keys())
    ph = ", ".join(["%s"] * len(base))
    vnz.db.execute(f"INSERT INTO signals ({cols}) VALUES ({ph})", tuple(base.values()))
    return int(vnz.db.query("SELECT id FROM signals ORDER BY id DESC LIMIT 1")[0]["id"])


# ─────────────────────────────────────────────────────────────────────────────
# 1) weekly_high — القمة مع الكاش
# ─────────────────────────────────────────────────────────────────────────────

def test_weekly_high_returns_max_and_caches(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "weekly_high", _REAL_WEEKLY_HIGH)
    calls = {"n": 0}

    def fake_fetch(symbol, timeframe, limit, min_candles=60):
        # عقد fetch_ohlcv_df: DataFrame أو None — لا tuple
        calls["n"] += 1
        assert timeframe == "1d" and limit == vnz.TP_WEEK_CAP_DAYS + 1
        assert min_candles == 3
        return _df_from_highs([10.0, 12.5, 11.0])

    monkeypatch.setattr(vnz, "fetch_ohlcv_df", fake_fetch)
    assert vnz.weekly_high("T/USDT") == 12.5
    assert vnz.weekly_high("T/USDT") == 12.5  # من الكاش
    assert calls["n"] == 1, "الكاش لم يمنع الطلب الثاني"


def test_weekly_high_failure_negative_cache(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "weekly_high", _REAL_WEEKLY_HIGH)
    calls = {"n": 0}

    def fake_fetch(*a, **k):
        calls["n"] += 1
        return None

    monkeypatch.setattr(vnz, "fetch_ohlcv_df", fake_fetch)
    assert vnz.weekly_high("T/USDT") is None   # fail-open
    assert vnz.weekly_high("T/USDT") is None   # كاش سلبي — بلا طلب ثانٍ
    assert calls["n"] == 1


def test_weekly_high_rejects_nonpositive(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "weekly_high", _REAL_WEEKLY_HIGH)
    monkeypatch.setattr(vnz, "fetch_ohlcv_df", lambda *a, **k: _df_from_highs([0.0, 0.0]))
    assert vnz.weekly_high("T/USDT") is None


# ─────────────────────────────────────────────────────────────────────────────
# 2) build_staged_targets — القص والأرضيات والتقارب
# ─────────────────────────────────────────────────────────────────────────────

def _stage_setup():
    return SimpleNamespace(direction="BULLISH", pivot_prices=[100.0] * 6, timeframe="1h")


def test_stages_cap_and_three_stages(monkeypatch):
    monkeypatch.setattr(vnz, "compute_tp_ladder",
                        lambda s: ladder_of([(104.0, "w5_eq_w1"), (106.0, "w5_0618_w3"), (108.0, "ext_1618")]))
    stages, capped, best = vnz.build_staged_targets(_stage_setup(), 100.0, 98.0, 107.0)
    assert [p for p, _ in stages] == [104.0, 106.0, 107.0]
    assert capped is True, "امتداد 1.618 فوق القمة ولم يُقص"
    assert best == pytest.approx(4.0)  # (108-100)/2


def test_stages_collapse_to_single_when_cap_squeezes(monkeypatch):
    monkeypatch.setattr(vnz, "compute_tp_ladder",
                        lambda s: ladder_of([(104.0, "w5_eq_w1"), (106.0, "w5_0618_w3"), (108.0, "ext_1618")]))
    stages, capped, _ = vnz.build_staged_targets(_stage_setup(), 100.0, 98.0, 101.5)
    assert [p for p, _ in stages] == [101.5], "القص عنيف = مرحلة مفردة عند القمة"
    assert capped is True


def test_stages_drop_rung_below_net_floor(monkeypatch):
    # قمة 100.5: الربح الصافي (بعد رسوم الاتجاهين) أقل من RR_NET_MIN → تُهدر كل الدرجات
    monkeypatch.setattr(vnz, "compute_tp_ladder",
                        lambda s: ladder_of([(104.0, "w5_eq_w1"), (106.0, "w5_0618_w3")]))
    stages, capped, best = vnz.build_staged_targets(_stage_setup(), 100.0, 98.0, 100.5)
    assert stages == []
    assert capped is True
    assert best == pytest.approx(3.0)  # أفضل درجة خام (106-100)/2


def test_stages_skip_rung_below_raw_floor(monkeypatch):
    monkeypatch.setattr(vnz, "compute_tp_ladder", lambda s: ladder_of([(100.8, "w5_eq_w1")]))
    stages, capped, best = vnz.build_staged_targets(_stage_setup(), 100.0, 98.0, 120.0)
    assert stages == []          # rr خام 0.4 < TP_MIN_RR — لا تأهيل
    assert capped is False       # لم تُقص درجة — السقف بعيد
    assert best == pytest.approx(0.4)


def test_stages_no_cap_needed_when_ladder_below_weekly(monkeypatch):
    monkeypatch.setattr(vnz, "compute_tp_ladder",
                        lambda s: ladder_of([(104.0, "w5_eq_w1"), (106.0, "w5_0618_w3"), (108.0, "ext_1618")]))
    stages, capped, _ = vnz.build_staged_targets(_stage_setup(), 100.0, 98.0, 120.0)
    assert [p for p, _ in stages] == [104.0, 106.0, 108.0]
    assert capped is False, "السلّم تحت القمة — لا قص ولا ادعاء"


def test_stages_dedupe_close_rungs(monkeypatch):
    # درجتان متلاصقتان (فجوة 0.3 < 0.2×2=0.4) تندمجان — لا مراحل ضجيجية
    monkeypatch.setattr(vnz, "compute_tp_ladder",
                        lambda s: ladder_of([(104.0, "w5_eq_w1"), (104.3, "w5_0618_w3"), (108.0, "ext_1618")]))
    stages, _, _ = vnz.build_staged_targets(_stage_setup(), 100.0, 98.0, 120.0)
    assert [p for p, _ in stages] == [104.0, 108.0]


# ─────────────────────────────────────────────────────────────────────────────
# 3-4) create_pending_signal — التخزين والمسار التراثي والرفض المسمّى
# ─────────────────────────────────────────────────────────────────────────────

def _creation_setup():
    """إعداد صالح: دخول 100/وقف 98 وسلّم حقيقي فوق الدخول (116 / 118.18 / 119.564)."""
    return SimpleNamespace(
        direction="BULLISH", timeframe="1h",
        entry_zone_low=100.0, entry_zone_high=101.0, stop_loss_price=98.0,
        pivot_prices=[100.0, 110.0, 102.0, 124.0, 106.0, 118.0],
        validation_result=SimpleNamespace(fib=None),
    )


def test_create_stores_staged_targets(clean_db, tg_off, monkeypatch):
    monkeypatch.setattr(vnz, "weekly_high", lambda s: 117.5)
    assert vnz.create_pending_signal("TEST/USDT", _creation_setup(), last_close=0) is True
    row = vnz.db.query("SELECT * FROM signals ORDER BY id DESC LIMIT 1")[0]
    assert row["tp1"] == pytest.approx(116.0)          # أقرب درجة مؤهلة
    assert row["tp2"] is None                          # الدرجة الوسطى قُصّت إلى السقف واندمجت
    assert row["tp3"] == pytest.approx(117.5)          # الهدف النهائي = سقف الأسبوع
    assert row["take_profit"] == pytest.approx(117.5)
    assert row["weekly_high"] == pytest.approx(117.5)
    fj = json.loads(row["fib_json"])
    assert fj["weekly_capped"] is True
    assert 117.5 in fj["tp_stages"]


def test_create_legacy_path_when_weekly_high_unavailable(clean_db, tg_off, monkeypatch):
    monkeypatch.setattr(vnz, "weekly_high", lambda s: None)
    assert vnz.create_pending_signal("TEST/USDT", _creation_setup(), last_close=0) is True
    row = vnz.db.query("SELECT * FROM signals ORDER BY id DESC LIMIT 1")[0]
    # المسار التراثي حرفيًا: أقرب درجة تحقق TP_MIN_RR، بلا مراحل
    assert row["take_profit"] == pytest.approx(116.0)
    assert row["tp1"] is None and row["tp2"] is None and row["tp3"] is None
    assert row["weekly_high"] is None


def test_create_rejects_when_no_target_below_weekly_cap(clean_db, tg_off, monkeypatch):
    monkeypatch.setattr(vnz, "weekly_high", lambda s: 100.5)  # القمة تلتهم الأرضية الصافية
    n0 = vnz.scan_stats["rejected_weekly_cap"]
    ok = vnz.create_pending_signal("TEST/USDT", _creation_setup(), last_close=0)
    assert ok is False
    assert vnz.scan_stats["rejected_weekly_cap"] == n0 + 1
    reason = vnz._get_reject_reason("TEST/USDT")
    assert reason and "سقف الأسبوع" in reason
    rows = vnz.db.query("SELECT id FROM signals")
    assert not rows, "رُفض السقف لكن أُنشئت إشارة!"


def test_create_cap_trims_ladder_below_weekly(clean_db, tg_off, monkeypatch):
    # القمة 105: كل الدرجات تُقص إليها — مرحلة مفردة مخزنة في tp1/tp3 معًا
    monkeypatch.setattr(vnz, "weekly_high", lambda s: 105.0)
    assert vnz.create_pending_signal("TEST/USDT", _creation_setup(), last_close=0) is True
    row = vnz.db.query("SELECT * FROM signals ORDER BY id DESC LIMIT 1")[0]
    assert row["take_profit"] == pytest.approx(105.0)
    assert row["tp1"] == pytest.approx(105.0) and row["tp3"] == pytest.approx(105.0)
    assert row["tp2"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 5-6) _tp_stage_step — جني المراحل (ورقي + غبار حقيقي)
# ─────────────────────────────────────────────────────────────────────────────

def _stage_sig(**kw):
    base = {"id": None, "symbol": "TEST/USDT", "status": "open", "is_real": 0,
            "entry_price": 100.0, "fill_price": 100.0, "stop_loss": 98.0,
            "take_profit": 110.0, "tp1": 104.0, "tp2": 107.0, "tp3": 110.0,
            "quantity": 100.0, "initial_quantity": 100.0, "realized_pnl_usdt": 0.0,
            "meta_json": None}
    base.update(kw)
    sig_id = insert_open(**{k: v for k, v in base.items() if k != "id"})
    row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig_id,))[0]
    return dict(row)


def test_stage_step_paper_two_legs(clean_db, tg_off):
    sig = _stage_sig()
    bal0 = vnz.get_paper_balance()
    vnz._tp_stage_step(sig, high_now=105.0)   # لمس tp1 فقط
    assert sig["quantity"] == pytest.approx(60.0), "40% من 100 عند tp1"
    meta = vnz._sig_meta(sig)
    assert meta.get("tp1_done") is True and "tp2_done" not in meta
    assert vnz.get_paper_balance() > bal0, "ربح الرجل لم يتحقق في الرصيد"
    vnz._tp_stage_step(sig, high_now=105.0)   # نفس القمة — بلا رجل ثانية
    assert sig["quantity"] == pytest.approx(60.0)
    vnz._tp_stage_step(sig, high_now=108.5)   # لمس tp2
    assert sig["quantity"] == pytest.approx(36.0), "40% من المتبقي 60"
    meta = vnz._sig_meta(sig)
    assert meta.get("tp2_done") is True


def test_stage_step_single_stage_skipped(clean_db, tg_off):
    sig = _stage_sig(tp1=110.0, tp2=None, tp3=110.0)  # مرحلة مفردة = الهدف النهائي نفسه
    vnz._tp_stage_step(sig, high_now=115.0)
    assert sig["quantity"] == pytest.approx(100.0), "المرحلة المفردة تُغلق كاملة في المسار القديم لا كرجل"
    assert not vnz._sig_meta(sig).get("tp1_done")


def test_stage_step_real_dust_marked_done_without_sell(clean_db, tg_off, monkeypatch):
    sig = _stage_sig(is_real=1)
    monkeypatch.setattr(vnz, "binance_trade_exchange", lambda: SimpleNamespace())

    def boom(*a, **k):
        raise AssertionError("أمر بيع حقيقي أُرسل لرجل غبار!")

    monkeypatch.setattr(vnz, "place_real_market_sell", boom)
    monkeypatch.setattr(vnz, "real_adjust_amount", lambda ex, sym, q: 0.0)  # غبار
    monkeypatch.setattr(vnz, "real_market", lambda ex, sym: {})
    monkeypatch.setattr(vnz, "real_min_amount", lambda mkt: 5.0)
    monkeypatch.setattr(vnz, "real_min_cost", lambda mkt: 5.0)
    vnz._tp_stage_step(sig, high_now=105.0)
    meta = vnz._sig_meta(sig)
    assert meta.get("tp1_done") is True, "الغبار يُعتبر منجزًا ويركب للمرحلة التالية"
    assert sig["quantity"] == pytest.approx(100.0), "لم تُبَع كمية"


# ─────────────────────────────────────────────────────────────────────────────
# 7) reconcile_live_targets — قصّ الأهداف الحية فوق سقف الأسبوع
# ─────────────────────────────────────────────────────────────────────────────

def _run_reconcile():
    vnz._TP_RECONCILE_LAST["at"] = 0.0
    vnz.reconcile_live_targets()


def test_reconcile_caps_open_target_and_notifies(clean_db, tg_off, monkeypatch):
    sig_id = insert_open(take_profit=130.0)
    monkeypatch.setattr(vnz, "weekly_high", lambda s: 110.0)
    _run_reconcile()
    row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig_id,))[0]
    assert row["take_profit"] == pytest.approx(110.0), "الهدف الشهري البعيد قُصّ إلى قمة الأسبوع"
    assert row["weekly_high"] == pytest.approx(110.0), "السقف يُخزن ليعرض في اللوحة"
    assert row["rr_ratio"] == pytest.approx(5.0)  # (110-100)/2
    meta = json.loads(row["meta_json"])
    assert meta.get("tp_week_capped") is True
    notifs = vnz.db.query("SELECT ntype, message FROM notifications ORDER BY id DESC LIMIT 5")
    fixes = [n for n in notifs if n["ntype"] == "TARGET_FIX"]
    assert fixes and "130" in fixes[0]["message"] or fixes, "لا بلاغ تصحيح هدف"


def test_reconcile_notify_once_then_silent_recap(clean_db, tg_off, monkeypatch):
    sig_id = insert_open(take_profit=130.0)
    monkeypatch.setattr(vnz, "weekly_high", lambda s: 110.0)
    _run_reconcile()
    n1 = len([n for n in vnz.db.query("SELECT ntype FROM notifications") if n["ntype"] == "TARGET_FIX"])
    assert n1 == 1
    # نافذة الأسبوع تتدحرج (قمة قديمة خرجت) — إعادة قص صامتة بلا بلاغ جديد
    monkeypatch.setattr(vnz, "weekly_high", lambda s: 105.0)
    _run_reconcile()
    row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig_id,))[0]
    assert row["take_profit"] == pytest.approx(105.0)
    n2 = len([n for n in vnz.db.query("SELECT ntype FROM notifications") if n["ntype"] == "TARGET_FIX"])
    assert n2 == 1, "إعادة القص بسبب تدحرج النافذة يجب أن تبقى صامتة"


def test_reconcile_collapses_stages_above_new_cap(clean_db, tg_off, monkeypatch):
    sig_id = insert_open(take_profit=130.0, tp1=120.0, tp2=None, tp3=130.0)
    monkeypatch.setattr(vnz, "weekly_high", lambda s: 110.0)
    _run_reconcile()
    row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig_id,))[0]
    assert row["take_profit"] == pytest.approx(110.0)
    assert row["tp1"] is None, "مرحلة فوق السقف الجديد تنهار"
    assert row["tp2"] is None


def test_reconcile_covers_pending_and_skips_within_cap(clean_db, tg_off, monkeypatch):
    pid = insert_open(status="pending", fill_price=None, take_profit=125.0)
    ok_id = insert_open(take_profit=105.0)
    monkeypatch.setattr(vnz, "weekly_high", lambda s: 110.0)
    _run_reconcile()
    pend = vnz.db.query("SELECT take_profit FROM signals WHERE id=%s", (pid,))[0]
    assert pend["take_profit"] == pytest.approx(110.0), "المعلق أيضًا يُقص"
    okr = vnz.db.query("SELECT take_profit FROM signals WHERE id=%s", (ok_id,))[0]
    assert okr["take_profit"] == pytest.approx(105.0), "داخل السقف — بلا مساس"


# ─────────────────────────────────────────────────────────────────────────────
# 8) تكامل monitor_step — حماية ثم مراحل ثم إغلاق نهائي
# ─────────────────────────────────────────────────────────────────────────────

def _candle(high, low):
    return pd.DataFrame([{
        "timestamp": pd.Timestamp.now(tz="UTC"), "open": (high + low) / 2,
        "high": high, "low": low, "close": (high + low) / 2, "volume": 1000.0,
    }])


def test_monitor_stage_then_final_close(clean_db, tg_off, monkeypatch):
    sig_id = insert_open(take_profit=110.0, tp1=104.0, tp2=107.0, tp3=110.0, stop_loss=98.0)
    # شمعة 1: عالية 105 → +1R جزئي (50%) وBE ثم رجل tp1 (40% من المتبقي)
    monkeypatch.setattr(vnz, "get_recent_candles", lambda *a, **k: _candle(105.0, 101.0))
    vnz.monitor_step()
    row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig_id,))[0]
    assert row["status"] == "open"
    assert row["quantity"] == pytest.approx(30.0), "100 → جزئي 1R (50) → رجل tp1 (20)"
    assert row["stop_loss"] == pytest.approx(100.0), "BE@1R نقل الوقف للدخول"
    meta = json.loads(row["meta_json"])
    assert meta.get("partial_done") and meta.get("be_done") and meta.get("tp1_done")
    # شمعة 2: عالية 111 → رجل tp2 ثم الإغلاق النهائي عند 110
    monkeypatch.setattr(vnz, "get_recent_candles", lambda *a, **k: _candle(111.0, 101.0))
    vnz.monitor_step()
    row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig_id,))[0]
    assert row["status"] == "closed"
    assert row["close_price"] == pytest.approx(110.0)
    assert row["realized_pnl_usdt"] > 0, "مجموع الرجلين + النهائي يجب أن يكون ربحًا"
    meta = json.loads(row["meta_json"])
    assert meta.get("tp2_done") is True


def test_monitor_legacy_single_target_unchanged(clean_db, tg_off, monkeypatch):
    """انحدار: هدف مفرد تراثي (بلا مراحل) يغلق كاملًا كما كان حرفيًا."""
    sig_id = insert_open(take_profit=106.0, tp1=None, tp2=None, tp3=None)
    monkeypatch.setattr(vnz, "get_recent_candles", lambda *a, **k: _candle(107.0, 101.0))
    vnz.monitor_step()
    row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig_id,))[0]
    assert row["status"] == "closed" and row["close_price"] == pytest.approx(106.0)


# ─────────────────────────────────────────────────────────────────────────────
# 9) الترحيل والعرض — أعمدة جديدة + tp_stages في اللوحة + صدى الحماية
# ─────────────────────────────────────────────────────────────────────────────

def test_migration_columns_exist(clean_db):
    import sqlite3
    cols = {r["name"] for r in vnz.db.conn.execute("PRAGMA table_info(signals)").fetchall()}
    for c in ("tp1", "tp2", "tp3", "weekly_high"):
        assert c in cols, f"عمود {c} غائب بعد الترحيل"


def test_api_all_exposes_stages_and_protection(clean_db, monkeypatch):
    insert_open(take_profit=110.0, tp1=104.0, tp2=107.0, tp3=110.0, weekly_high=110.5)
    monkeypatch.setattr(vnz, "get_live_price", lambda s: 102.0)
    client = vnz.app.test_client()
    body = client.get("/api/all").get_json()
    sig = body["open_signals"][0]
    assert sig["tp_stages"] == [104.0, 107.0, 110.0]
    assert sig["weekly_high"] == pytest.approx(110.5)
    prot = body["protection"]
    assert prot["tp_week_cap"] is True and prot["tp_week_days"] == 7
    assert prot["tp_stages"] is True and prot["tp_stage_pct"] == 40.0


def test_api_all_legacy_signal_has_no_stages(clean_db, monkeypatch):
    insert_open(take_profit=106.0)  # بلا مراحل
    monkeypatch.setattr(vnz, "get_live_price", lambda s: 102.0)
    client = vnz.app.test_client()
    body = client.get("/api/all").get_json()
    assert body["open_signals"][0]["tp_stages"] == []


# ─────────────────────────────────────────────────────────────────────────────
# 10) البوابة واللوحة والإصدار
# ─────────────────────────────────────────────────────────────────────────────

def test_telegram_gate_passes_target_fix(tg_off):
    assert vnz.telegram_gate("TARGET_FIX"), "بلاغ تصحيح الأهداف يجب أن يصل تلغرام"


def test_panel_has_stages_line_and_header():
    assert "function stagesLine" in panel.PANEL_HTML
    assert "الأهداف (متدرجة)" in panel.PANEL_HTML
    assert "سقف أسبوع" in panel.PANEL_HTML


def test_version_sync():
    assert vnz.BOT_VERSION == "EL2.4.3"
    assert panel.BOT_VERSION == "EL2.4.3"
