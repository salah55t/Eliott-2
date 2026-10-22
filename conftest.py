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

import pytest


@pytest.fixture(autouse=True)
def _isolate_weekly_high(monkeypatch):
    import vnz
    vnz._tp_week_cache.clear()
    monkeypatch.setattr(vnz, "weekly_high", lambda symbol: None)
    yield
    vnz._tp_week_cache.clear()


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
