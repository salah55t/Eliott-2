#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات FE1.9.13 «الشارت الحي»
==================================
الطلب: «فيما قد يفيدنا هذا المشروع في مشروعنا —
https://github.com/tradingview/lightweight-charts»

الجواب المنفَّذ: دمج مكتبة TradingView Lightweight Charts v5.2.1 (Apache-2.0)
في لوحة التحكم — كانت اللوحة أرقامًا ومنحنى SVG يدويًا واحدًا بلا أي شارت شموع،
فلم يكن يُرى بصريًا هل الهدف بعيد أم قريب (جذر بلاغ «الأهداف البعيدة»).

ما يُغطيه الملف:
  1) /api/klines من كاش Postgres: الشكل والترتيب التصاعدي والمصدر والعدد
  2) دمج الشمعة الجارية الحية من مخزن ويب سوكت (أحدث زمنيًا يفوز — بلا محو)
  3) رمز غير صالح/مجهول → 200 بقائمة فارغة (لا 500)، tf خارج المسموح → fallback
  4) حدود limit (تثبيت 30..OHLCV_LIMIT) وحماية اللوحة (401 عند التفعيل)
  5) /lwc.js: 200 + content-type + ترويسة ترخيص Apache داخل الملف + تخزين يومي
  6) اللوحة: قسم الشارت + قائمة الرموز + chartFocus/chartTick + خطوط المراجع +
     علامات الملء/الغلق + سطر الإسناد (Apache-2.0) + النقر على رمز الصفقات
  7) حزمة المكتبة في static/ تحمل v5.2.1 وتصدّر createSeriesMarkers
  8) تزامن الإصدار vnz/panel
"""

import os
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
    """قاعدة SQLite مؤقتة لكل اختبار — عزل كامل (نفس نمط test_fe199)."""
    monkeypatch.setattr(vnz, "USE_POSTGRES", False)
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    old = vnz.db.conn
    vnz.db.conn = conn
    vnz.init_db()
    yield
    vnz.db.conn = old


def seed_cache(symbol="TEST/USDT", tf="5m", n=50, step_ms=300_000, base_ts=1_700_000_000_000):
    """بذر شموع مغلقة في الكاش عبر الكاتب الحقيقي (نفس مسار الإنتاج).
    حاجز التكرار _kline_cache_max_ts عالمي ويصمد عبر الاختبارات بينما قاعدة كل
    اختبار جديدة — يُصفَّر للرمز/الفريم قبل البذرة لضمان كتابة حقيقية."""
    vnz._kline_cache_max_ts.pop((symbol, tf), None)
    rows = [[base_ts + i * step_ms, 100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 10.0]
            for i in range(n)]
    vnz._kline_cache_write(symbol, tf, rows)
    return rows


def client():
    return vnz.app.test_client()


# ─────────────────────────────────────────────────────────────────────────────
# 1) /api/klines من الكاش
# ─────────────────────────────────────────────────────────────────────────────

def test_klines_from_cache_shape_and_order(clean_db, monkeypatch):
    seed_cache(n=50)
    monkeypatch.setattr(vnz, "WS_ENABLED", False)  # بلا دمج حي — كاش نقي
    body = client().get("/api/klines?symbol=TEST/USDT&tf=5m&limit=50").get_json()
    assert body["count"] == 50
    assert body["source"] == "cache"
    assert body["tf"] == "5m" and body["symbol"] == "TEST/USDT"
    ts = [c[0] for c in body["candles"]]
    assert ts == sorted(ts), "الشموع تصاعدية زمنيًا — شرط مكتبة الشارت"
    c0 = body["candles"][0]
    assert len(c0) == 6 and all(isinstance(v, (int, float)) for v in c0)
    assert all(c[2] >= c[3] for c in body["candles"]), "القمة ≥ القاع"


def test_klines_respects_limit(clean_db, monkeypatch):
    seed_cache(n=80)
    monkeypatch.setattr(vnz, "WS_ENABLED", False)
    body = client().get("/api/klines?symbol=TEST/USDT&tf=5m&limit=30").get_json()
    assert body["count"] == 30
    # آخر الشموع هي الأحدث (قصّ من الأمام لا من الخلف)
    assert body["candles"][-1][0] > body["candles"][0][0]


def test_klines_limit_clamped(clean_db, monkeypatch):
    seed_cache(n=50)
    monkeypatch.setattr(vnz, "WS_ENABLED", False)
    tiny = client().get("/api/klines?symbol=TEST/USDT&tf=5m&limit=5").get_json()
    assert tiny["count"] == 30, "حد أدنى 30"
    big = client().get("/api/klines?symbol=TEST/USDT&tf=5m&limit=99999").get_json()
    assert big["count"] == 50, "السقف OHLCV_LIMIT لا يوسّع ما لا يوجد"


# ─────────────────────────────────────────────────────────────────────────────
# 2) دمج الشمعة الجارية الحية
# ─────────────────────────────────────────────────────────────────────────────

def test_klines_merges_live_candle_newer(clean_db, monkeypatch):
    rows = seed_cache(n=40)
    monkeypatch.setattr(vnz, "WS_ENABLED", True)
    monkeypatch.setattr(vnz, "ENTRY_TIMEFRAME", "5m")
    live = [rows[-1][0] + 300_000, 110.0, 112.0, 109.0, 111.0, 3.0]
    monkeypatch.setattr(vnz, "_ws_candles", {"TEST/USDT": {"candles": [live], "ts": 1.0}})
    body = client().get("/api/klines?symbol=TEST/USDT&tf=5m&limit=50").get_json()
    assert body["source"] == "cache+live"
    assert body["count"] == 41 and body["candles"][-1][4] == 111.0


def test_klines_live_candle_replaces_same_ts(clean_db, monkeypatch):
    rows = seed_cache(n=40)
    monkeypatch.setattr(vnz, "WS_ENABLED", True)
    monkeypatch.setattr(vnz, "ENTRY_TIMEFRAME", "5m")
    # نفس الطابع الزمني لآخر شمعة مغلقة؟ لا — الكاش مغلقة حصرًا؛ الحالة الفعلية:
    # الشمعة الحية لطابع لم يُغلق بعد. نحاكي تعادلًا زمنيًا صريحًا (دفاع عميق).
    live = [rows[-1][0], 100.5 + 39, 105.0, 100.0, 104.0, 7.0]
    monkeypatch.setattr(vnz, "_ws_candles", {"TEST/USDT": {"candles": [live], "ts": 1.0}})
    body = client().get("/api/klines?symbol=TEST/USDT&tf=5m&limit=50").get_json()
    assert body["source"] == "cache+live"
    assert body["count"] == 40 and body["candles"][-1][4] == 104.0
    assert body["candles"][-1][2] == 105.0, "الشمعة الحية فازت عند التعادل الزمني"


def test_klines_live_older_ignored_and_wrong_tf_no_merge(clean_db, monkeypatch):
    rows = seed_cache(n=40)
    monkeypatch.setattr(vnz, "WS_ENABLED", True)
    monkeypatch.setattr(vnz, "ENTRY_TIMEFRAME", "5m")
    live = [rows[-1][0] - 3_600_000, 90.0, 91.0, 89.0, 90.5, 1.0]  # قديمة
    monkeypatch.setattr(vnz, "_ws_candles", {"TEST/USDT": {"candles": [live], "ts": 1.0}})
    body = client().get("/api/klines?symbol=TEST/USDT&tf=5m&limit=50").get_json()
    assert body["source"] == "cache" and body["count"] == 40
    # فريم غير التنفيذ: لا دمج حي أصلًا
    body15 = client().get("/api/klines?symbol=TEST/USDT&tf=15m&limit=50").get_json()
    assert body15["count"] == 0, "كاش 5m لا يخدم 15m"


def test_klines_live_only_when_no_cache(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "WS_ENABLED", True)
    monkeypatch.setattr(vnz, "ENTRY_TIMEFRAME", "5m")
    live = [1_700_000_000_000, 100.0, 101.0, 99.0, 100.5, 1.0]
    monkeypatch.setattr(vnz, "_ws_candles", {"TEST/USDT": {"candles": [live], "ts": 1.0}})
    body = client().get("/api/klines?symbol=TEST/USDT&tf=5m&limit=50").get_json()
    assert body["source"] == "live" and body["count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 3) رموز/فريمات سيئة — بلا أعطال
# ─────────────────────────────────────────────────────────────────────────────

def test_klines_bad_symbol_returns_empty_200(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "WS_ENABLED", False)
    for sym in ("", "BTC", "  ", "%20"):
        body = client().get(f"/api/klines?symbol={sym}&tf=5m").get_json()
        assert body["candles"] == [] and body["source"] == "none"
    body = client().get("/api/klines?symbol=NOPE/USDT&tf=5m").get_json()
    assert body["candles"] == [] and body["source"] == "none"


def test_klines_bad_tf_falls_back_to_entry(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "WS_ENABLED", False)
    body = client().get("/api/klines?symbol=TEST/USDT&tf=2h").get_json()
    assert body["tf"] == vnz.ENTRY_TIMEFRAME


def test_klines_bad_limit_value_safe(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "WS_ENABLED", False)
    body = client().get("/api/klines?symbol=TEST/USDT&tf=5m&limit=abc").get_json()
    assert body["count"] == 0 and body["candles"] == []


# ─────────────────────────────────────────────────────────────────────────────
# 4) حماية اللوحة نفسها
# ─────────────────────────────────────────────────────────────────────────────

def test_klines_and_lwc_auth_when_protected(clean_db, monkeypatch):
    monkeypatch.setattr(vnz, "DASHBOARD_PROTECTED", True)
    c = client()
    assert c.get("/api/klines?symbol=TEST/USDT").status_code == 401
    assert c.get("/lwc.js").status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# 5) /lwc.js — تقديم المكتبة محليًا
# ─────────────────────────────────────────────────────────────────────────────

def test_lwc_js_served_with_license_and_cache():
    r = client().get("/lwc.js")
    assert r.status_code == 200
    assert "javascript" in (r.mimetype or "")
    assert r.headers.get("Cache-Control") == "public, max-age=86400"
    body = r.get_data(as_text=True)
    assert "TradingView Lightweight Charts" in body
    assert "Apache License 2.0" in body, "ترويسة الترخيص لا تُزال — إسناد إلزامي"


def test_lwc_bundle_in_repo_is_v5_with_plugins():
    path = os.path.join(os.path.dirname(vnz.__file__), "static",
                        "lightweight-charts.standalone.production.js")
    assert os.path.exists(path), "ملف المكتبة ضمن المستودع — بلا CDN خارجي"
    src = open(path, encoding="utf-8").read()
    assert "v5.2.1" in src
    for api in ("createChart", "CandlestickSeries", "createPriceLine",
                "createSeriesMarkers", "LineStyle", "ColorType"):
        assert api in src, f"واجهة {api} موجودة في الحزمة"


# ─────────────────────────────────────────────────────────────────────────────
# 6) اللوحة — قسم الشارت ووظائفه
# ─────────────────────────────────────────────────────────────────────────────

def test_panel_has_chart_section_and_script():
    h = panel.PANEL_HTML
    assert '<script src="/lwc.js"' in h, "المكتبة تُحمَّل محليًا"
    assert 'id="lwc-chart"' in h and 'id="chart-sym"' in h and 'id="chart-note"' in h
    assert "الشارت الحي" in h and "سقف أسبوع" in h
    assert "TradingView Lightweight Charts v5.2.1 (Apache-2.0)" in h, "سطر الإسناد"


def test_panel_chart_functions_complete():
    h = panel.PANEL_HTML
    for fn in ("function chartInit", "function chartPopulate", "function chartSelectSym",
               "function chartFocus", "function chartApplyOverlays", "function chartTick",
               "function chartSelectedRow"):
        assert fn in h, fn
    # خطوط المراجع على الشموع
    assert "createPriceLine" in h
    assert "هدف" in h and "وقف" in h and "دخول" in h
    # ألوان النيون نفسها
    assert "#00e5ff" in h and "#ff2d78" in h and "#22e58c" in h and "#ffb020" in h
    # علامات الملء/الغلق + نبض مستقل أسرع من دورة اللوحة
    assert "setMarkers" in h and "arrowUp" in h and "arrowDown" in h
    assert "setInterval(()=>{ try{ chartTick(); }catch(e){} }, 8000)" in h
    # عرض /api/klines بالترميز الصحيح
    assert "/api/klines?symbol=" in h


def test_panel_rows_clickable_to_focus_chart():
    h = panel.PANEL_HTML
    assert h.count("chartFocus('${esc(s.symbol)}')") >= 2, "المفتوحة والمغلقة كلاهما نقرتا"


def test_panel_lwc_failure_fallback():
    h = panel.PANEL_HTML
    assert "window.__LWC_FAILED" in h, "فشل تحميل المكتبة لا يكسر اللوحة"


# ─────────────────────────────────────────────────────────────────────────────
# 7) تزامن الإصدار
# ─────────────────────────────────────────────────────────────────────────────

def test_version_sync():
    assert vnz.BOT_VERSION == "EL2.1.0"
    assert panel.BOT_VERSION == "EL2.1.0"
    body = client().get("/health").get_json()
    assert body["version"] == "EL2.1.0"
