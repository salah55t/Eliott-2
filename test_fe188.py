#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fe188.py — اختبارات إصلاح موت إشارات أول دورة إقلاع (FE1.9.0)

الجذر الحي (دليل من الخدمة الجديدة fibo-elio-4s5z): 7 إعدادات صاعدة صالحة (PEPE/APT/
SUI/ARB/NEAR/LTC/AVAX) قُتلت جميعها بحكم «توليد الإشارات معطل» في أول دورة كشف
(17:37:23-45Z) لأن db_get_state أعاد الافتراضي "0" صامتًا — قاعدة حالة فارغة
(خدمة جديدة/PG جديد) أو فشل قراءة عابر، كلاهما كان يعطي علمًا ميتًا عند الإقلاع.
ثانية: تفعيل التوليد من اللوحة لم يوقظ أي فحص — انتظار حتى إغلاق الشمعة القادمة (15د).

الجولات:
  1) restore_trading_flag: مفتاح غائب (قاعدة جديدة) ← يبدأ مفعّلًا ويكتب "1"
  2) restore_trading_flag: فشل قراءة متكرر ← 3 محاولات ثم يبدأ مفعّلًا (ورقي آمن)
  3) restore_trading_flag: قيمة صريحة "0" ← تُحترم (معطّل)
  4) restore_trading_flag: قيمة "1" ← مفعّل
  5) التبديل ON يوقظ _scan_kick و_detect_kick فورًا
  6) التبديل OFF لا يوقظ شيئًا
  7) نوم scan_loop قابل للتوقظ (نمط Event.wait لا time.sleep)
  8) الحدود المحمية لم تُمس (بوابات الجودة بقيمها)

تشغيل: pytest test_fe188.py -v   (من داخل مجلد المشروع)
"""

import re
import threading

import pytest

import vnz


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 1-4 — استعادة العلم
# ─────────────────────────────────────────────────────────────────────────────

class TestRestoreTradingFlag:

    def test_missing_key_defaults_enabled_and_persists(self, monkeypatch):
        """قاعدة حالة فارغة (خدمة جديدة) ← البدء مفعّلًا + كتابة "1" (كان القتل الصامت)."""
        monkeypatch.setattr(vnz, "_state_get_raw", lambda k: None)
        writes = {}
        monkeypatch.setattr(vnz, "db_set_state", lambda k, v: writes.__setitem__(k, v))
        vnz.restore_trading_flag()
        assert vnz.is_trading_enabled is True
        assert writes.get("trading_enabled") == "1"

    def test_read_failure_retries_then_defaults_enabled(self, monkeypatch):
        """فشل قراءة عابر (PG لم يجهز) ← 3 محاولات ثم البدء مفعّلًا."""
        calls = {"n": 0}

        def boom(key):
            calls["n"] += 1
            raise RuntimeError("pg not ready")

        monkeypatch.setattr(vnz, "_state_get_raw", boom)
        monkeypatch.setattr(vnz.time, "sleep", lambda s: None)  # تسريع المحاولات
        monkeypatch.setattr(vnz, "db_set_state", lambda k, v: None)
        vnz.restore_trading_flag()
        assert calls["n"] == 3, "ثلاث محاولات قبل الاستسلام"
        assert vnz.is_trading_enabled is True

    def test_explicit_zero_stays_disabled(self, monkeypatch):
        """اختيار المستخدم المحفوظ «0» يُحترم — لا فرض تفعيل."""
        monkeypatch.setattr(vnz, "_state_get_raw", lambda k: "0")
        writes = {}
        monkeypatch.setattr(vnz, "db_set_state", lambda k, v: writes.__setitem__(k, v))
        vnz.restore_trading_flag()
        assert vnz.is_trading_enabled is False
        assert "trading_enabled" not in writes, "لا كتابة فوق اختيار المستخدم"

    def test_explicit_one_enabled(self, monkeypatch):
        monkeypatch.setattr(vnz, "_state_get_raw", lambda k: "1")
        vnz.restore_trading_flag()
        assert vnz.is_trading_enabled is True


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 5-6 — التبديل يوقظ الفحوص
# ─────────────────────────────────────────────────────────────────────────────

class TestToggleKicks:

    def _client(self):
        return vnz.app.test_client()

    def test_toggle_on_kicks_both_scans(self, monkeypatch):
        monkeypatch.setattr(vnz, "db_set_state", lambda k, v: None)
        vnz._scan_kick.clear()
        vnz._detect_kick.clear()
        if vnz.is_trading_enabled:  # اجعل الحالة معطلة قبل الاختبار
            self._client().post("/api/trading/toggle")
            vnz._scan_kick.clear()
            vnz._detect_kick.clear()
        r = self._client().post("/api/trading/toggle")
        body = r.get_json()
        assert body["trading_enabled"] is True
        assert vnz._detect_kick.is_set(), "تفعيل التوليد يوقظ دورة الكشف فورًا"
        assert vnz._scan_kick.is_set(), "تفعيل التوليد يوقظ فحص الكون فورًا"
        vnz._detect_kick.clear()
        vnz._scan_kick.clear()

    def test_toggle_off_kicks_nothing(self, monkeypatch):
        monkeypatch.setattr(vnz, "db_set_state", lambda k, v: None)
        if not vnz.is_trading_enabled:
            self._client().post("/api/trading/toggle")
        vnz._scan_kick.clear()
        vnz._detect_kick.clear()
        r = self._client().post("/api/trading/toggle")
        body = r.get_json()
        assert body["trading_enabled"] is False
        assert not vnz._detect_kick.is_set(), "الإيقاف لا يوقظ شيئًا"
        # إعادة الحالة مفعّلة (البوت يعمل مفعّلًا افتراضيًا في بيئة الاختبار)
        self._client().post("/api/trading/toggle")
        vnz._detect_kick.clear()
        vnz._scan_kick.clear()


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 7 — نوم الكشف قابل للتوقظ
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectNapInterruptible:

    def test_scan_loop_uses_event_wait_not_sleep(self):
        src = open("vnz.py", encoding="utf-8").read()
        # داخل scan_loop: لا time.sleep(nap) مباشرة — بل _detect_kick.wait
        m = re.search(
            r"nap = seconds_until_next_candle\(SIGNAL_TIMEFRAME\)\n"
            r"(?:[^\n]*\n)*?"
            r"        if _detect_kick\.wait\(timeout=nap\):\n"
            r"            _detect_kick\.clear\(\)",
            src,
        )
        assert m, "نوم حلقة الكشف يجب أن يكون عبر _detect_kick.wait (قابل للتوقظ)"
        # لا نوم مباشر متبقٍ في scan_loop بينهما
        seg = src[m.start():m.start() + 600]
        assert "time.sleep(nap)" not in seg.split("def ")[0][:300]

    def test_detect_kick_event_exists(self):
        assert isinstance(vnz._detect_kick, threading.Event)


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 8 — الحدود المحمية لم تُمس
# ─────────────────────────────────────────────────────────────────────────────

class TestProtectedBoundaries:

    def test_gate_constants_untouched(self):
        assert vnz.MAX_ENTRY_DISTANCE_PCT == 1.5
        assert vnz.RR_NET_MIN == 0.3
        assert vnz.SYMBOL_COOLDOWN_SEC == 5400
        assert vnz.MAX_STRUCTURE_AGE_BARS == 36
        assert vnz.KEEP_ALIVE_INTERVAL_SEC == 60.0

    def test_version_bumped(self):
        assert vnz.BOT_VERSION == "EL2.2.0"
