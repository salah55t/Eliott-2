#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات FE1.9.13 «موجات إليوت (LuxAlgo) على الشارت»
======================================================
الطلب: «هل يمكنك تطبيق هذا المؤشر على الشارت» مع لصق كود مؤشر
Elliott Wave [LuxAlgo] (Pine Script v5) كاملًا.

الجواب المنفَّذ: نقل حرفي لمنطق المؤشر إلى static/elliott-wave.js يُقدَّم
من /ew.js (بنمط /lwc.js) ويرسم فوق الشارت الحي من FE1.9.10 كطبقة حسابية
في متصفح المستخدم: زيجزاج 4/8/16 + دافع 12345 + تصحيح ABC + فيبو 0.5–0.854.

ما يُغطيه الملف (خوارزمية JS نفسها مُتحقق منها بـ 35/35 اختبار node منفصل):
  1) /ew.js: 200 + content-type + تخزين يومي + ترويسة الترخيص + الإسناد داخل الملف
  2) حماية اللوحة: /ew.js محمي مثل بقية نقاط اللوحة (401 عند التفعيل)
  3) اللوحة: زر التشغيل + مثيل العلامات المستقل + دوال البناء والتوقيع
     + تحويل الأنماط + سطر الإسناد الإلزامي (CC BY-NC-SA)
  4) الملف نفسه: تصدير ElliottWaveLux.compute + رأس الإسناد + بلا اعتماد خارجي
  5) تزامن الإصدار vnz/panel و/health
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


# ─────────────────────────────────────────────────────────────────────────────
# 1) /ew.js — تقديم ملف المؤشر
# ─────────────────────────────────────────────────────────────────────────────

def test_ew_js_served_with_cache_and_license(clean_db):
    r = client().get("/ew.js")
    assert r.status_code == 200
    assert "javascript" in (r.mimetype or "")
    assert r.headers.get("Cache-Control") == "public, max-age=86400"
    assert "CC BY-NC-SA 4.0" in (r.headers.get("X-Content-License") or ""), \
        "ترويسة الترخيص تحمل الإسناد الإلزامي"
    body = r.get_data(as_text=True)
    assert "ElliottWaveLux" in body, "الملف يصدّر واجهة ElliottWaveLux"
    assert "compute" in body
    assert "LuxAlgo" in body and "CC BY-NC-SA 4.0" in body, \
        "رأس الملف يحمل الإسناد © LuxAlgo والترخيص"


def test_ew_js_no_external_dependency(clean_db):
    body = client().get("/ew.js").get_data(as_text=True)
    assert "http://" not in body.split("*/")[0], "رأس الملف بلا روابط تحميل خارجية"
    assert "require(" not in body and "import " not in body, \
        "ملف المتصفح مستقل — IIFE بلا استيرادات"


def test_ew_js_file_exists_in_static():
    p = os.path.join(os.path.dirname(os.path.abspath(vnz.__file__)),
                     "static", "elliott-wave.js")
    assert os.path.isfile(p), "الملف مبنيّ في static/ بجانب مكتبة الشارت"


# ─────────────────────────────────────────────────────────────────────────────
# 2) حماية اللوحة
# ─────────────────────────────────────────────────────────────────────────────

def test_ew_js_protected_when_dashboard_protected(monkeypatch, clean_db):
    monkeypatch.setattr(vnz, "DASHBOARD_PROTECTED", True)
    r = client().get("/ew.js")
    assert r.status_code in (302, 401, 403), \
        "مؤشر الموجات خلف حماية اللوحة نفسها لا مفتوحًا للعموم"


def test_lwc_js_still_served(clean_db):
    r = client().get("/lwc.js")
    assert r.status_code == 200, "شارت FE1.9.10 لم يُمس"


# ─────────────────────────────────────────────────────────────────────────────
# 3) اللوحة — قسم المؤشر
# ─────────────────────────────────────────────────────────────────────────────

def test_panel_has_ew_script_and_toggle():
    html = panel.PANEL_HTML
    assert 'src="/ew.js"' in html, "تحميل ملف المؤشر بعد مكتبة الشارت"
    assert html.index("/lwc.js") < html.index("/ew.js"), "المكتبة قبل المؤشر"
    assert 'id="ew-toggle"' in html and "ewToggle()" in html, "زر تشغيل/إيقاف"
    assert "checked" in html.split('id="ew-toggle"')[1][:200], "مفعّل افتراضيًا"
    assert 'id="ew-note"' in html, "سطر تلخيص حالة الأنماط تحت الشارت"


def test_panel_has_ew_render_functions():
    html = panel.PANEL_HTML
    for fn in ("ewRebuild", "ewMaybe", "ewClear", "ewStyleOf"):
        assert "function " + fn in html, "دالة " + fn + " معرّفة"
    assert "EW_MARKS = LW.createSeriesMarkers" in html, \
        "مثيل علامات مستقل للمؤشر — علامات الملء/الغلق في CMARKS لا تُمسّ"
    assert "ElliottWaveLux.compute" in html, "استدعاء الخوارزمية بثلاثة أطوال"
    assert "marks.sort" in html, "الشارات تُرتب تصاعديًا — شرط المكتبة"
    assert "'#ff5b6a'" in html and "'#4da3ff'" in html, "ألوان LuxAlgo (أحمر/أزرق)"
    assert "pointMarkersVisible: false" in html, "بلا نقاط على أطراف الأضلاع"


def test_panel_ew_rebuild_signature_not_per_pulse():
    html = panel.PANEL_HTML
    assert "EW_SIG" in html and "chartBars.length" in html, \
        "إعادة البناء بتوقيع (رمز/فريم/عدد/آخر شمعة) لا عند كل نبضة"
    assert "ewMaybe();" in html, "الاستدعاء داخل دورة الشارت"


def test_panel_ew_attribution_mandatory():
    html = panel.PANEL_HTML
    assert "LuxAlgo" in html and "CC BY-NC-SA 4.0" in html, \
        "إسناد إلزامي في قسم الشارت"
    assert "creativecommons.org/licenses/by-nc-sa/4.0/" in html, \
        "رابط الترخيص ظاهر للمستخدم"


def test_indicator_file_is_pure_visualization():
    """حد أمان: ملف المؤشر عرضٌ خالص — لا شبكة ولا تخزين ولا مسارات تداول."""
    p = os.path.join(os.path.dirname(os.path.abspath(vnz.__file__)),
                     "static", "elliott-wave.js")
    body = open(p, encoding="utf-8").read()
    for banned in ("fetch(", "XMLHttpRequest", "localStorage", "document.", "window.location"):
        assert banned not in body, "المؤشر بلا " + banned + " — حساب نقي يُرجع نتائج فقط"


# ─────────────────────────────────────────────────────────────────────────────
# 5) تزامن الإصدار
# ─────────────────────────────────────────────────────────────────────────────

def test_version_sync(clean_db):
    assert vnz.BOT_VERSION == "EL2.0.0"
    assert panel.BOT_VERSION == "EL2.0.0"
    body = client().get("/health").get_json()
    assert body["version"] == "EL2.0.0"


def test_dashboard_serves_updated_html(clean_db):
    c = client()
    r = c.get("/")
    if r.status_code == 200:
        assert "/ew.js" in r.get_data(as_text=True)
    else:
        # إن كانت اللوحة محمية في هذه البيئة نكتفى بفحص PANEL_HTML مباشرة
        assert "/ew.js" in panel.PANEL_HTML
