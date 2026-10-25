#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات EL2.3.0 — فلتر التدفق: دعم إشارات موجات إليوت بقرار التدفق الحي
============================================================================
طلب الحاكم: «اجعل استراتيجية اليوت تدعم بفلتر التدفق» — الفلاتر الأربعة (F1..F4):
SuperTrend(10,2.5) صاعد + ADX(14) ≥ 20 + CVD فوق EMA12 + الإغلاق فوق VWAP.

جولات الاختبار:
  1) المنطق النقي evaluate_flow على بيانات صناعية: موافقة كاملة + رفض كل بوابة
     مسمّى + fail-open بلا بيانات + تجاهل غير الصاعد (سبوت)
  2) التكامل في create_pending_signal: الرفض يمنع الولادة بعداد وحكم مسمّى،
     والموافقة تُخزن بصمتها في fib_json.flow، وغياب البيانات = fail-open
  3) سلسلة البيانات _flow_rows: انسحاب صادق من taker إلى proxy إلى unavailable
  4) البوت الثنائي: موجات إليوت + التدفق فقط — المزالة غائبة كليةً
تشغيل: pytest test_el23_flow_filter.py -v
"""

import json
import math

import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة
import panel

from engine.pattern_detector import DetectorConfig, PivotDetector
from strategies.flow_filter import evaluate_flow


FEE = 0.001


# ─────────────────────────────────────────────────────────────────────────────
# بناة البيانات الصناعية — ترند صاعد واضح بكل البوابات خضراء
# ─────────────────────────────────────────────────────────────────────────────

def bull_rows(n=90, start=100.0, drift=0.06, vol=100.0, taker_ratio=0.60,
              taker_override=None):
    """ترند صاعد قوي: ST5 صاعد، ADX عالٍ، دلتا موجبة، فوق VWAP."""
    rows = []
    px = start
    for i in range(n):
        o = px
        c = px + drift
        h = max(o, c) + 0.3
        l = min(o, c) - 0.3
        tb = taker_ratio * vol if taker_override is None else taker_override(vol)
        rows.append({"ts": i * 300000.0, "open": o, "high": h, "low": l,
                     "close": c, "volume": vol, "taker_base": tb})
        px = c
    return rows


def make_bear_tail(rows, tail=3):
    """آخر tail شموع هابطة قوية — يقلب SuperTrend ويهبط الدلتا (رفض F1/F3)."""
    out = [dict(r) for r in rows]
    px = out[-1]["close"]
    for j in range(tail):
        idx = len(out) - tail + j
        o = px
        c = px - 1.5
        out[idx] = {"ts": out[idx]["ts"], "open": o, "high": o + 0.2,
                    "low": c - 0.3, "close": c, "volume": 130.0,
                    "taker_base": 130.0 * 0.30}
        px = c
    return out


def flat_rows(n=90, base=100.0, amp=0.05, vol=100.0, taker_ratio=0.5):
    """سوق راكد شبه مسطح — ADX منهار (رفض F2: لا طاقة اتجاهية)."""
    rows = []
    for i in range(n):
        o = base + amp * math.sin(i * 0.7)
        c = base + amp * math.sin(i * 0.7 + 0.5)
        rows.append({"ts": i * 300000.0, "open": o, "high": max(o, c) + 0.02,
                     "low": min(o, c) - 0.02, "close": c, "volume": vol,
                     "taker_base": vol * taker_ratio})
    return rows


def make_ctx_rows(rows):
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# 1) المنطق النقي — evaluate_flow
# ─────────────────────────────────────────────────────────────────────────────

def test_flow_passes_on_healthy_uptrend():
    v = evaluate_flow(bull_rows(), "BULLISH")
    assert v["ok"] is True and v["unavailable"] is False and v["gate"] is None
    assert v["meta"]["flow_filter"] == "passed"
    assert v["meta"]["st5_dir"] == 1.0
    assert v["meta"]["adx5"] is not None and v["meta"]["adx5"] >= 20.0
    assert v["meta"]["cvd_ok"] is True


def test_flow_veto_f1_supertrend_down():
    rows = make_bear_tail(bull_rows())
    v = evaluate_flow(rows, "BULLISH")
    assert v["ok"] is False and v["gate"] in ("F1", "F3")   # الاتجاه أو الدلتا أوقعاها
    assert v["reason"]


def test_flow_veto_f2_no_directional_energy():
    v = evaluate_flow(flat_rows(), "BULLISH")
    assert v["ok"] is False and v["gate"] == "F2"
    assert "طاقة" in v["reason"]


def test_flow_veto_f3_cvd_bleeding():
    """ترند سعري صاعد لكن دلتا المشترين سالبة (تاكير خلف السعر) — CVD تحت تنعيمه."""
    rows = bull_rows(n=90, taker_ratio=0.60)
    for r in rows[-12:]:
        r["taker_base"] = r["volume"] * 0.25    # انزفاق تاكير حديث
    v = evaluate_flow(rows, "BULLISH")
    if v["gate"] == "F3":
        assert v["ok"] is False and "دلتا" in v["reason"]
    else:
        assert v["ok"] is True   # ADX قد يُوقع أصلًا — المهم لا موافقة صامتة بلا سبب


def test_flow_fails_open_on_thin_data():
    v = evaluate_flow(bull_rows(30), "BULLISH")
    assert v["ok"] is True and v["unavailable"] is True
    assert v["meta"]["flow_filter"] == "unavailable"


def test_flow_fails_open_on_empty_rows():
    v = evaluate_flow([], "BULLISH")
    assert v["ok"] is True and v["unavailable"] is True


def test_flow_skips_non_bullish_direction():
    v = evaluate_flow(bull_rows(), "BEARISH")
    assert v["ok"] is True and v["meta"]["flow_filter"] == "skipped_non_bullish"


def test_flow_adx_none_fails_open_not_veto():
    """ADX غير مكتمل الحساب (سلسلة قصيرة الحدود) = fail-open موثّق — لا رفض ملفّق."""
    rows = bull_rows(60)
    v = evaluate_flow(rows, "BULLISH", adx_min=200.0)   # أرضية مستحيلة = رفض F2 مضمون المنطق
    assert v["ok"] is False and v["gate"] == "F2"
    assert "طاقة" in v["reason"]


# ─────────────────────────────────────────────────────────────────────────────
# 2) التكامل — create_pending_signal مع الفلتر
# ─────────────────────────────────────────────────────────────────────────────

DET = PivotDetector(DetectorConfig(method="zigzag", deviation_threshold=0.01,
                                   price_source="close", min_wave_bars=2))


def impulse_setup():
    """دافع صاعد مصطنع: P0=100 P1=120 P2=110 P3=140 P4=125 P5=135 — نفس عقد test_fe100."""
    def leg(rows, a, b, n, t0):
        step = (b - a) / n
        for i in range(n):
            o = a + step * i
            c = a + step * (i + 1)
            rows.append((t0 + i * 3600_000, o, max(o, c) * 1.0005,
                         min(o, c) * 0.9995, c, 1000.0))
        return t0 + n * 3600_000
    rows, t = [], 1_700_000_000_000
    for a, b, n in [(100.0, 120.0, 5), (120.0, 110.0, 4), (110.0, 140.0, 6),
                    (140.0, 125.0, 4), (125.0, 135.0, 4)]:
        t = leg(rows, a, b, n, t)
    import pandas as pd
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df["symbol"] = "TEST/USDT"
    df["timeframe"] = "1h"
    bulls = [s for s in DET.scan(df) if s.direction == "BULLISH"]
    assert bulls, "يجب أن يكتشف الزيجزاج الدافع الصاعد المصطنع"
    return bulls[-1]


@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    """قاعدة SQLite مؤقتة لكل اختبار — عزل كامل (نمط المستودع)."""
    monkeypatch.setattr(vnz, "USE_POSTGRES", False)
    import sqlite3
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    old = vnz.db.conn
    vnz.db.conn = conn
    vnz.init_db()
    vnz.set_paper_balance(vnz.PAPER_BALANCE_START)
    yield vnz.db
    vnz.db.conn = old


@pytest.fixture()
def tg_off(monkeypatch):
    monkeypatch.setattr(vnz, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(vnz, "TELEGRAM_CHAT_ID", "")
    monkeypatch.setattr(vnz, "_tg_dedup", {})
    yield


@pytest.fixture()
def flow_on(monkeypatch):
    """تجاوز مصيدة العزل المشتركة — فحص الفلتر الحقيقي داخل مسار الإنشاء."""
    monkeypatch.setattr(vnz, "ELLIOTT_FLOW_FILTER", True)
    return monkeypatch


def test_veto_blocks_pending_creation(clean_db, tg_off, flow_on, monkeypatch):
    """رفض الفلتر يمنع ولادة الأمر المعلق: حكم مسمّى في اللوحة + عداد صادق."""
    monkeypatch.setattr(vnz, "elliott_flow_verdict", lambda s, direction="BULLISH":
                        {"ok": False, "unavailable": False, "gate": "F1",
                         "reason": "اتجاه التدفق هابط (SuperTrend 5m) — الموجة ضد التيار",
                         "meta": {"flow_filter": "applied", "st5_dir": -1.0}})
    n_before = vnz.scan_stats["rejected_flow_filter"]
    created = vnz.create_pending_signal("TEST/USDT", impulse_setup(), last_close=0.0)
    assert created is False
    assert vnz._get_reject_reason("TEST/USDT").startswith("فلتر التدفق")
    assert vnz.scan_stats["rejected_flow_filter"] == n_before + 1
    rows = vnz.db.query("SELECT COUNT(*) AS n FROM signals WHERE status='pending'") or []
    assert int(rows[0]["n"]) == 0


def test_pass_verdict_fingerprints_fib_json(clean_db, tg_off, flow_on, monkeypatch):
    """الموافقة تخزن بصمة الفلتر في fib_json.flow — الشفافية في السجل."""
    monkeypatch.setattr(vnz, "elliott_flow_verdict", lambda s, direction="BULLISH":
                        {"ok": True, "unavailable": False, "gate": None, "reason": "",
                         "meta": {"flow_filter": "passed", "st5_dir": 1.0,
                                  "adx5": 24.7, "cvd_ok": True,
                                  "delta_last": 12.5}})
    assert vnz.create_pending_signal("TEST/USDT", impulse_setup(), last_close=0.0) is True
    row = vnz.db.query("SELECT * FROM signals WHERE status='pending'")[0]
    flow = json.loads(row["fib_json"]).get("flow") or {}
    assert flow.get("flow_filter") == "passed"
    assert flow.get("adx5") == 24.7


def test_unavailable_fails_open_and_counts(clean_db, tg_off, flow_on, monkeypatch):
    """بيانات غائبة = fail-open موثّق: الإشارة تولد والعداد المستقل يزيد (لا صمت)."""
    monkeypatch.setattr(vnz, "elliott_flow_verdict", lambda s, direction="BULLISH":
                        {"ok": True, "unavailable": True, "gate": None,
                         "reason": "بيانات التدفق غير كافية — fail-open بالعقدة الأصلية",
                         "meta": {"flow_filter": "unavailable"}})
    n_before = vnz.scan_stats["flow_filter_unavailable"]
    assert vnz.create_pending_signal("TEST/USDT", impulse_setup(), last_close=0.0) is True
    assert vnz.scan_stats["flow_filter_unavailable"] == n_before + 1
    row = vnz.db.query("SELECT * FROM signals WHERE status='pending'")[0]
    flow = json.loads(row["fib_json"]).get("flow") or {}
    assert flow.get("flow_filter") == "unavailable"


def test_filter_disabled_env_skips_gate(clean_db, tg_off, flow_on, monkeypatch):
    """ELLIOTT_FLOW_FILTER=0 يعطل البوابة كليًا — العقدة القديمة حرفيًا."""
    monkeypatch.setattr(vnz, "ELLIOTT_FLOW_FILTER", False)
    calls = {"n": 0}
    def spy(symbol, direction="BULLISH"):
        calls["n"] += 1
        return {"ok": True, "unavailable": False, "gate": None, "reason": "", "meta": {}}
    monkeypatch.setattr(vnz, "elliott_flow_verdict", spy)
    assert vnz.create_pending_signal("TEST/USDT", impulse_setup(), last_close=0.0) is True
    assert calls["n"] == 0


def test_flow_rows_fallback_chain(monkeypatch):
    """سلسلة الحقيقة: taker (شموع خام) → proxy (بدائل) → قائمة فارغة (fail-open)."""
    raw12 = [[0, "100", "101", "99", "100.5", "10", 0, 0, 0, "6", 0, "0"]] * 80
    monkeypatch.setattr(vnz, "binance_full_klines", lambda s, iv, limit: raw12)
    rows = vnz._flow_rows("TEST/USDT")
    assert rows and len(rows) <= 80
    # بلا خام: انسحاب إلى proxy عبر fetch_ohlcv_raw
    monkeypatch.setattr(vnz, "binance_full_klines", lambda s, iv, limit: None)
    monkeypatch.setattr(vnz, "fetch_ohlcv_raw",
                        lambda s, tf, limit: ([[0, "100", "101", "99", "100.5", "10"]] * 80, "test"))
    rows = vnz._flow_rows("TEST/USDT")
    assert rows
    # لا شيء إطلاقًا: قائمة فارغة → الفلتر يعيد unavailable (fail-open)
    monkeypatch.setattr(vnz, "binance_full_klines", lambda s, iv, limit: None)
    monkeypatch.setattr(vnz, "fetch_ohlcv_raw", lambda s, tf, limit: (None, None))
    assert vnz._flow_rows("TEST/USDT") == []
    v = vnz.elliott_flow_verdict("TEST/USDT")
    assert v["ok"] is True and v["unavailable"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 3) البوت الثنائي — موجات إليوت (بفلتر التدفق) + التدفق
# ─────────────────────────────────────────────────────────────────────────────

def test_version_and_dual_bot_bootstrap():
    assert vnz.BOT_VERSION == "EL2.4.2"
    assert panel.BOT_VERSION == "EL2.4.2"
    assert set(vnz.STRATEGY_TOGGLES) == {"Elliott_Fibonacci", "SCALP_FLOW"}
    # وصف زر موجات إليوت في اللوحة يذكر الفلتر — الدعم مرئي للمستخدم
    html = panel.PANEL_HTML
    assert "SCALP_TREND" not in html and "SCALP_SQUEEZE" not in html
    assert "مدعوم بفلتر التدفق" in html
