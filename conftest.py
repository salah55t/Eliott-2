# -*- coding: utf-8 -*-
"""مصائد مشتركة لكل الاختبارات — [FE1.9.9]
عزل weekly_high عن الشبكة: كل اختبار يجدها تعيد None (fail-open بالمسار التراثي)
ما لم يتجاوزها الاختبار صراحةً بـmonkeypatch الخاص به (يطغى على هذه المصيدة لأنه
يُنفَّذ بعدها بنفس كائن monkeypatch). كاش القمة يُصفَّر قبل وبعد كل اختبار.

[EL2.1.0] تهيئة قاعدة SQLite الافتراضية في بيئة الاختبار — الاختبارات التي لا تستخدم
مصباح clean_db تعتمد على ملف data/fibo_elio.db، وفي بيئة نظيفة (CI/حاوية جديدة)
كان غياب الجداول يفجّر اختبارات المصادقة اليدوية بـ«no such table» بدل 404/409.
init_db هنا مرة واحدة لكل جلسة اختبار فقط (لا يلمس Postgres إطلاقًا)."""

import os

# [EL2.4.1][F5] الاختبارات تعمل بكلمة المرور الافتراضية — ارفع حظر الضعف قبل أي استيراد لـvnz
os.environ.setdefault("ALLOW_WEAK_DASHBOARD_PASSWORD", "1")

import pytest


@pytest.fixture(autouse=True)
def _csrf_header_for_tests(monkeypatch):
    """[EL2.4.1][F5] كل POST في الاختبارات يحمل رأس CSRF تلقائيًا — اللوحة تضيفه
    دائمًا في الإنتاج (panel.api)، والاختبار الذي يريد قصْدًا بدون الرأس يستخدم
    عميلًا خامًا ملتقطًا قبل الترقيع."""
    import vnz
    orig_tc = vnz.app.test_client

    def _tc(*a, **kw):
        c = orig_tc(*a, **kw)
        orig_post = c.post

        def post(path, *a2, **kw2):
            if kw2.get("headers") is None:
                kw2["headers"] = {"X-Requested-With": "EliottPanel"}
            return orig_post(path, *a2, **kw2)

        c.post = post
        return c

    monkeypatch.setattr(vnz.app, "test_client", _tc)
    yield


@pytest.fixture(autouse=True)
def _isolate_weekly_high(monkeypatch):
    import vnz
    vnz._tp_week_cache.clear()
    monkeypatch.setattr(vnz, "weekly_high", lambda symbol: None)
    yield
    vnz._tp_week_cache.clear()


@pytest.fixture(autouse=True)
def _isolate_elliott_flow_filter(monkeypatch):
    """[EL2.3.0] عزل فلتر التدفق عن الشبكة في كل الاختبارات: حكم fail-open موثّق
    (unavailable) — نفس عقد _isolate_weekly_high. الاختبار المتخصص
    (test_el23_flow_filter.py) يتجاوز هذه المصيدة بmonkeypatch الخاص به لفحص
    المنطق الحقيقي والبوابات على بيانات صناعية (صفر شبكة)."""
    import vnz
    monkeypatch.setattr(
        vnz, "elliott_flow_verdict",
        lambda symbol, direction="BULLISH": {
            "ok": True, "unavailable": True, "gate": None,
            "reason": "عزل الاختبارات — فلتر التدفق fail-open",
            "meta": {"flow_filter": "unavailable"}})
    yield


@pytest.fixture(autouse=True)
def _isolate_rate_guard():
    """[EL2.4.3][حملة 1025] عزل حالة حارس وزن باينانس حول كل اختبار — الاختبار الذي
    يجري نداءً حقيقيًا (فحص اتصال/لوحة) قد يسجّل حظر 429 حقيقيًا طويل الأمد حين تكون
    الشبكة مضغوطة، فيتسرب لاختبارات الوقف الراكن الحقيقية بعدها فيفسدها عابرًا
    (فشل بيئي لا علاقة له بالكود). نفس عقد _isolate_weekly_high: حفظ واستعادة."""
    import vnz
    g = vnz.rate_guard
    saved_banned = g.banned_until
    saved_count = g.ban_count
    saved_err = g.last_error
    saved_window = list(g._window)
    yield
    g.banned_until = saved_banned
    g.ban_count = saved_count
    g.last_error = saved_err
    with g._lock:
        g._window.clear()
        g._window.extend(saved_window)


@pytest.fixture(scope="session", autouse=True)
def _ensure_default_sqlite_schema():
    """يضمن وجود جداول القاعدة الافتراضية قبل أي اختبار يلمسها بلا مصباح."""
    import sqlite3
    import vnz
    if getattr(vnz, "USE_POSTGRES", False):
        return
    path = "data/fibo_elio.db"
    try:
        os.makedirs("data", exist_ok=True)
        fresh = not os.path.exists(path)
        conn = sqlite3.connect(path, check_same_thread=False)
        if fresh or not _has_signals_table(conn):
            vnz.db.conn = conn
            vnz.init_db()
        else:
            conn.close()
    except Exception:
        pass   # fail-open: الاختبارات التي تحتاج قاعدة معزولة تستخدم clean_db


def _has_signals_table(conn) -> bool:
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='signals'")
        return cur.fetchone() is not None
    except Exception:
        return False
