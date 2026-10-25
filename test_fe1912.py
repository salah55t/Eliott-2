#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات FE1.9.13 «موجات المحرك — المؤشر يحسب بمنطق الاستراتيجية حرفيًا»
============================================================================
الطلب: «اضبط عدادات المؤشر ومستويات فيبوناتشي كما هي في الاستراتيجية»
       «اريد ان يحسب مؤشر موجات اليوت وفيبوناتشي كما في استراتيجية التداول»

الجواب المنفَّذ: نقطة /api/ew_strategy تشغّل الكاشف والمحقق والفيبو ذواتهم
(نسخة إعداد مطابقة معزولة عن حالة الكاشف الحي) على شموع الكاش ذاتها وتعيد
زيجزاج الاستراتيجية + البنية P0–P5 بحكم قواعدها + منطقة الدخول/الوقف + سلّم
الأهداف المقصوص على قمة الأسبوع + مفاتيح فيبو W2/W4/W3 — واللوحة ترسمها.

ما يُغطيه الملف:
  1) بنية الاستجابة: params تُصدّق إعدادات المؤلف الحرفية
  2) دافع صاعد مصنوع يدويًا: محاور P0–P5 دقيقة + قواعد صالحة + تراجعات W2/W4
  3) صيغ الاستراتيجية حرفيًا: دخول P3−0.382×W3، وقف P0×0.999، إبطال P0
  4) سلّم الأهداف: خام (3 درجات) + قصّ سقف الأسبوع + فجوة المراحل 0.2R
  5) طبقات فيبو الكانونية: مفاتيح W2/W4 وامتدادات W3
  6) الحواف: رمز سيء 200 لا 500 · شموع ناقصة · سوق مسطح بلا بنى · tf غير مسموح
  7) حماية اللوحة 401 · نقاء الكاشف الحي (إعداده لا يُمسّ)
  8) اللوحة: زر موجات المحرك + دواله + سطر الحكم + بقاء LuxAlgo وإسناده
  9) تزامن الإصدار vnz/panel
"""

import sqlite3

import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة
import panel


# ─────────────────────────────────────────────────────────────────────────────
# أدوات
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def clean_db(monkeypatch):
    """قاعدة SQLite مؤقتة لكل اختبار — عزل كامل (نفس نمط test_fe19100)."""
    monkeypatch.setattr(vnz, "USE_POSTGRES", False)
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    old = vnz.db.conn
    vnz.db.conn = conn
    vnz.init_db()
    yield
    vnz.db.conn = old


def client():
    return vnz.app.test_client()


def _impulse_closes(n_pre=35):
    """إغلاقات دافع صاعد مصنوع — المحاور تُلتقط بالويكات (قمة/قاع الشمعة) كما في
    المحرك (محاور منقّاة بالويك FE1.6.0): القيعان low=close−0.05 والقمم high=close+0.05
    → P0=99.95 P1=112.05 P2=103.95 P3=124.05 P4=114.95 P5=126.05.
    تمهيد مسطح ±0.3% (< عتبة الانعكاس 0.6% — بلا محاور) ثم أرجل ≥2.4% بحد أدنى
    شمعتين بين المحاور. التراجعات: W2=66.9% (منطقة 0.382–0.886) وW4=45.3%
    (منطقة 0.236–0.5)، وW4 فوق P1 (لا تداخل)، وكل موجة دافعة ≥15% لوغاريتميًا."""
    pre = [100.0, 100.2, 100.1, 100.3, 100.0]
    closes = []
    while len(closes) < n_pre:
        closes.extend(pre)
    closes = closes[:n_pre]
    closes += [103, 106, 109, 112,      # W1 صاعدة → P1
               110, 108, 106, 104,      # W2 تصحيحية → P2 (فوق P0)
               109, 114, 119, 124,      # W3 صاعدة → P3 (تكسر P1)
               121, 118, 115,           # W4 تصحيحية → P4 (فوق P1)
               118, 121, 124, 126,      # W5 صاعدة → P5
               125, 124, 123, 122, 121, 120]  # تلاشٍ ختامي (عمر P5 قصير)
    return closes


# المحاور الويكية المتوقعة — تُشتق منها كل صيغ الاستراتيجية في التأكيدات
XP = [99.95, 112.05, 103.95, 124.05, 114.95, 126.05]
XW1 = XP[1] - XP[0]     # 12.10
XW3 = XP[3] - XP[2]     # 20.10
XW5 = XP[5] - XP[4]     # 11.10
XENTRY = XP[3] - 0.382 * XW3
XSTOP = XP[0] * 0.999
XRISK = XENTRY - XSTOP


def seed_impulse(symbol="TEST/USDT", tf="5m", base_ts=1_699_999_800_000):
    """بذر شموع الدافع المصنوع عبر الكاتب الحقيقي (نفس مسار الإنتاج).
    base_ts محاذٍ لشبكة 5m (باقي القسمة على 300000 = صفر) لدقة اختبار الشبكة."""
    vnz._kline_cache_max_ts.pop((symbol, tf), None)
    closes = _impulse_closes()
    rows = []
    prev = closes[0]
    for i, c in enumerate(closes):
        ts = base_ts + i * 300_000
        rows.append([ts, prev, c + 0.05, c - 0.05, c, 10.0])
        prev = c
    vnz._kline_cache_write(symbol, tf, rows)
    return rows


def seed_flat(symbol="TEST/USDT", tf="5m", n=80, base_ts=1_700_000_000_000):
    """تذبذب ±0.1% حول 100 — دون عتبة الانعكاس 0.6% فلا محاور زيجزاج إطلاقًا."""
    vnz._kline_cache_max_ts.pop((symbol, tf), None)
    cycle = [100.0, 100.1, 99.9]
    rows = []
    for i in range(n):
        c = cycle[i % 3]
        ts = base_ts + i * 300_000
        rows.append([ts, c, c + 0.05, c - 0.05, c, 10.0])
    vnz._kline_cache_write(symbol, tf, rows)
    return rows


APPROX = 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# 1) بنية الاستجابة والإعدادات
# ─────────────────────────────────────────────────────────────────────────────

def test_ew_strategy_params_echo_author_settings(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "WS_ENABLED", False)
    seed_impulse()
    body = client().get("/api/ew_strategy?symbol=TEST/USDT&tf=5m").get_json()
    assert body["symbol"] == "TEST/USDT" and body["tf"] == "5m"
    p = body["params"]
    assert abs(p["deviation_pct"] - vnz.DEVIATION_THRESHOLD * 100.0) < APPROX
    assert p["price_source"] == "close"
    assert p["min_wave_bars"] == vnz.MIN_WAVE_BARS
    assert p["min_wave_proportion"] == vnz.WAVE_MIN_PROPORTION
    assert p["signal_timeframe"] == vnz.SIGNAL_TIMEFRAME
    assert "0.382" in p["entry_zone_basis"] and "P0" in p["stop_basis"]
    assert body["source"] == "cache"


# ─────────────────────────────────────────────────────────────────────────────
# 2) الدافع المصنوع: المحاور والقواعد والتراجعات
# ─────────────────────────────────────────────────────────────────────────────

def test_ew_strategy_detects_crafted_bullish_impulse(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "WS_ENABLED", False)
    seed_impulse()
    body = client().get("/api/ew_strategy?symbol=TEST/USDT&tf=5m").get_json()
    s = body["setup"]
    assert s is not None, "الدافع المصنوع يجب أن يُكتشف"
    assert s["direction"] == "BULLISH" and s["valid"] is True
    assert s["fresh"] is True and 0 <= s["age_bars"] <= vnz.MAX_STRUCTURE_AGE_BARS
    pv = [p["price"] for p in s["pivots"]]
    labels = [p["label"] for p in s["pivots"]]
    assert labels == ["P0", "P1", "P2", "P3", "P4", "P5"]
    expect = XP
    for got, want in zip(pv, expect):
        assert abs(got - want) < 1e-6, f"محور {got} != {want}"
    # زيجزاج الاستراتيجية (عتبة الانعكاس) موجود ويصل المحاور
    zz = body["zigzag"]
    assert len(zz) >= 6
    assert body["bulls"] >= 1 and body["setups"] >= 1
    # القواعد الثلاث + أرضية التناسب كلها عابرة
    assert len(s["rules"]) >= 3
    assert all(r["passed"] for r in s["rules"])


def test_ew_strategy_fib_retrace_values(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "WS_ENABLED", False)
    seed_impulse()
    s = client().get("/api/ew_strategy?symbol=TEST/USDT&tf=5m").get_json()["setup"]
    assert abs(s["retrace"]["w2"] - (XP[1] - XP[2]) / XW1) < 1e-3   # ~66.9% — داخل 0.382–0.886
    assert abs(s["retrace"]["w4"] - (XP[3] - XP[4]) / XW3) < 1e-3   # ~45.3% — داخل 0.236–0.5
    assert s["retrace"]["w2_in_zone"] is True
    assert s["retrace"]["w4_in_zone"] is True
    L = s["lengths"]
    assert abs(L["w1"] - XW1) < APPROX and abs(L["w3"] - XW3) < APPROX
    assert abs(L["w5"] - XW5) < APPROX


# ─────────────────────────────────────────────────────────────────────────────
# 3) صيغ الاستراتيجية حرفيًا: الدخول/الوقف/الإبطال
# ─────────────────────────────────────────────────────────────────────────────

def test_ew_strategy_entry_stop_invalidation_formulas(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "WS_ENABLED", False)
    seed_impulse()
    s = client().get("/api/ew_strategy?symbol=TEST/USDT&tf=5m").get_json()["setup"]
    # الدخول = P3 − 0.382×W3 (حد 0.382 لتراجع الموجة 3 — منطق الأصل)
    assert abs(s["entry_zone"]["low"] - XENTRY) < APPROX
    # الحد الأعلى = P3 − 0.236×W3
    assert abs(s["entry_zone"]["high"] - (XP[3] - 0.236 * XW3)) < APPROX
    # الوقف البنيوي = P0 × 0.999
    assert abs(s["stop"] - XSTOP) < APPROX
    # خط الإبطال = أصل الموجة 1
    assert abs(s["p0_invalidation"] - XP[0]) < APPROX


# ─────────────────────────────────────────────────────────────────────────────
# 4) سلّم الأهداف: خام + قصّ سقف الأسبوع + فجوة المراحل
# ─────────────────────────────────────────────────────────────────────────────

def test_ew_strategy_ladder_raw_and_weekly_cap(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "WS_ENABLED", False)
    seed_impulse()
    # سقف موجود لكنه عالٍ (200) — لا يقصّ شيئًا: السلّم الخام 3 درجات، والمراحل
    # بعد تأهيل TP_MIN_RR وفجوة 0.2R — ext_1618 (P2+1.618×W1) تحت أرضية 0.5R خامًا،
    # و0.618×W3 يلتصق بـW5=W1 (فجوة < 0.2R) → مرحلة واحدة عند W5=W1.
    monkeypatch.setattr(vnz, "weekly_high", lambda symbol: 200.0)
    s = client().get("/api/ew_strategy?symbol=TEST/USDT&tf=5m").get_json()["setup"]
    tp = s["tp"]
    assert len(tp["raw_ladder"]) == 3
    raw = sorted(x[0] for x in tp["raw_ladder"])
    assert abs(raw[0] - (XP[2] + 1.618 * XW1)) < APPROX   # امتداد 1.618 من P2
    assert abs(raw[1] - (XP[4] + XW1)) < APPROX            # W5 = W1
    assert abs(raw[2] - (XP[4] + 0.618 * XW3)) < APPROX    # W5 = 0.618×W3
    assert abs(tp["weekly_high"] - 200.0) < APPROX
    assert tp["weekly_capped"] is False
    assert len(tp["stages"]) == 1
    assert abs(tp["stages"][0][0] - (XP[4] + XW1)) < APPROX
    assert tp["stages"][0][1] == "w5_eq_w1"
    assert abs(tp["fallback_take_profit"] - raw[0]) < APPROX  # هدف الأصل 1.618


def test_ew_strategy_weekly_cap_cuts_targets(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "WS_ENABLED", False)
    seed_impulse()
    # سقف أسبوع 124 يقصّ الدرجتين فوقه → مرحلة واحدة عند القمة نفسها
    monkeypatch.setattr(vnz, "weekly_high", lambda symbol: 124.0)
    s = client().get("/api/ew_strategy?symbol=TEST/USDT&tf=5m").get_json()["setup"]
    tp = s["tp"]
    assert tp["weekly_capped"] is True
    assert abs(tp["weekly_high"] - 124.0) < APPROX
    assert len(tp["stages"]) == 1
    assert abs(tp["stages"][0][0] - 124.0) < APPROX
    assert abs(tp["ladder_best_rr"] - (XP[4] + 0.618 * XW3 - XENTRY) / XRISK) < 1e-3


# ─────────────────────────────────────────────────────────────────────────────
# 5) طبقات فيبو الكانونية (مفاتيح الاستراتيجية)
# ─────────────────────────────────────────────────────────────────────────────

def test_ew_strategy_fib_overlays_canonical(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "WS_ENABLED", False)
    seed_impulse()
    ov = client().get("/api/ew_strategy?symbol=TEST/USDT&tf=5m").get_json()["setup"]["fib_overlays"]
    # W2 zone على الموجة 1: 0.382/0.5/0.618 من P0→P1
    w2 = {lv["ratio"]: lv["price"] for lv in ov["w2_zone"]}
    assert set(w2) == {0.382, 0.5, 0.618}
    assert abs(w2[0.382] - (XP[1] - 0.382 * XW1)) < APPROX
    assert abs(w2[0.618] - (XP[1] - 0.618 * XW1)) < APPROX
    # W4 zone على الموجة 3: 0.236/0.382/0.5 من P2→P3
    w4 = {lv["ratio"]: lv["price"] for lv in ov["w4_zone"]}
    assert set(w4) == {0.236, 0.382, 0.5}
    assert abs(w4[0.236] - (XP[3] - 0.236 * XW3)) < APPROX
    assert abs(w4[0.5] - (XP[3] - 0.5 * XW3)) < APPROX
    # امتدادات W3 من P2: 1.618/2.618 × W1
    w3 = {lv["ratio"]: lv["price"] for lv in ov["w3_ext"]}
    assert set(w3) == {1.618, 2.618}
    assert abs(w3[1.618] - (XP[2] + 1.618 * XW1)) < APPROX
    assert abs(w3[2.618] - (XP[2] + 2.618 * XW1)) < APPROX
    # المفاتيح معلّمة (is_key) كما في ثوابت المحرك
    assert all(lv["key"] for lv in ov["w2_zone"])
    assert all(lv["key"] for lv in ov["w3_ext"])


# ─────────────────────────────────────────────────────────────────────────────
# 6) الحواف — لا 500 أبدًا
# ─────────────────────────────────────────────────────────────────────────────

def test_ew_strategy_bad_symbol_returns_200_empty(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "WS_ENABLED", False)
    body = client().get("/api/ew_strategy?symbol=NOWHERE").get_json()
    assert body["setup"] is None and body["zigzag"] == []
    assert "رمز" in body["note"]


def test_ew_strategy_insufficient_candles(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "WS_ENABLED", False)
    vnz._kline_cache_max_ts.pop(("TEST/USDT", "5m"), None)
    rows = [[1_700_000_000_000 + i * 300_000, 100, 101, 99, 100.5, 10] for i in range(10)]
    vnz._kline_cache_write("TEST/USDT", "5m", rows)
    body = client().get("/api/ew_strategy?symbol=TEST/USDT&tf=5m").get_json()
    assert body["setup"] is None and body["zigzag"] == []
    assert "شموع غير كافية" in body["note"]


def test_ew_strategy_flat_market_no_setup(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "WS_ENABLED", False)
    seed_flat()
    body = client().get("/api/ew_strategy?symbol=TEST/USDT&tf=5m").get_json()
    assert body["setup"] is None and body["setups"] == 0
    assert isinstance(body["note"], str) and body["note"]


def test_ew_strategy_tf_fallback(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "WS_ENABLED", False)
    seed_impulse()
    body = client().get("/api/ew_strategy?symbol=TEST/USDT&tf=9m").get_json()
    assert body["tf"] == vnz.SIGNAL_TIMEFRAME


# ─────────────────────────────────────────────────────────────────────────────
# 7) الحماية ونقاء الكاشف الحي
# ─────────────────────────────────────────────────────────────────────────────

def test_ew_strategy_protected_401(monkeypatch):
    monkeypatch.setattr(vnz, "DASHBOARD_PROTECTED", True)
    assert client().get("/api/ew_strategy?symbol=TEST/USDT").status_code == 401


def test_ew_strategy_zigzag_times_resolved(clean_db, monkeypatch):
    """محاور الزيجزاج تُولَد NaT في الكاشف — يجب حل أزمنتها من الشموع للعرض."""
    monkeypatch.setattr(vnz, "WS_ENABLED", False)
    seed_impulse()
    body = client().get("/api/ew_strategy?symbol=TEST/USDT&tf=5m").get_json()
    zz = body["zigzag"]
    assert len(zz) >= 6
    ts = [p["t"] for p in zz]
    assert all(t > 0 for t in ts), "لا NaT — أزمنة المحاور محلولة من عمود الشموع"
    assert ts == sorted(ts), "المحاور تصاعدية زمنيًا"
    # أزمنة المحاور تطابق شبكة شموع الكاش (300000 مللي ثانية)
    assert all(t % 300_000 == 0 for t in ts)


def test_ew_strategy_does_not_touch_shared_detector(clean_db, monkeypatch):
    """نسخة العرض معزولة — إعدادات الكاشف الحي لا تُمسّ بعد الطلب."""
    monkeypatch.setattr(vnz, "WS_ENABLED", False)
    seed_impulse()
    cfg_before = (vnz.detector.cfg.deviation_threshold, vnz.detector.cfg.method,
                  vnz.detector.cfg.price_source, vnz.detector.cfg.min_wave_proportion)
    client().get("/api/ew_strategy?symbol=TEST/USDT&tf=5m")
    cfg_after = (vnz.detector.cfg.deviation_threshold, vnz.detector.cfg.method,
                 vnz.detector.cfg.price_source, vnz.detector.cfg.min_wave_proportion)
    assert cfg_before == cfg_after
    assert vnz.detector is not None


# ─────────────────────────────────────────────────────────────────────────────
# 8) اللوحة — الزر والدوال والإسناد
# ─────────────────────────────────────────────────────────────────────────────

def test_panel_has_engine_layer_ui():
    html = panel.PANEL_HTML
    assert 'id="ewx-toggle"' in html and "ewxToggle()" in html, "زر موجات المحرك"
    assert "checked" in html.split('id="ewx-toggle"')[1][:250], "مفعّل افتراضيًا"
    assert "ewxMaybe()" in html and "ewxApply(" in html and "ewxClear()" in html
    assert "/api/ew_strategy" in html, "جلب بيانات المحرك"
    assert 'id="ewx-note"' in html, "سطر الحكم العربي"
    assert "EWX_MARKS" in html, "مثيل علامات مستقل لمحاور P0–P5"
    assert "موجات المحرك" in html
    # بقاء طبقة LuxAlgo كاملة بإسنادها
    assert 'id="ew-toggle"' in html and "ewToggle()" in html
    assert "LuxAlgo" in html and "CC BY-NC-SA 4.0" in html
    assert "ElliottWaveLux" in html


def test_panel_engine_layer_legend_and_note():
    html = panel.PANEL_HTML
    assert "زيجزاج المحرك" in html, "مفتاح الألوان للطبقة الجديدة"
    assert "0.382×W3" in html, "أساس الدخول ظاهر للمستخدم"
    assert "سقف أسبوع" in html


# ─────────────────────────────────────────────────────────────────────────────
# 9) تزامن الإصدار
# ─────────────────────────────────────────────────────────────────────────────

def test_version_sync_vnz_panel():
    assert vnz.BOT_VERSION == "EL2.4.3"
    assert panel.BOT_VERSION == "EL2.4.3"
    assert panel.BOT_VERSION == vnz.BOT_VERSION
