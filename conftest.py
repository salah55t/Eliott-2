# -*- coding: utf-8 -*-
"""مصائد مشتركة لكل الاختبارات — [FE1.9.9]
عزل weekly_high عن الشبكة: كل اختبار يجدها تعيد None (fail-open بالمسار التراثي)
ما لم يتجاوزها الاختبار صراحةً بـmonkeypatch الخاص به (يطغى على هذه المصيدة لأنه
يُنفَّذ بعدها بنفس كائن monkeypatch). كاش القمة يُصفَّر قبل وبعد كل اختبار."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_weekly_high(monkeypatch):
    import vnz
    vnz._tp_week_cache.clear()
    monkeypatch.setattr(vnz, "weekly_high", lambda symbol: None)
    yield
    vnz._tp_week_cache.clear()
