#!/usr/bin/env python3
# test_fe183.py — اختبارات FE1.8.6:
#   1) مضاد النوم كل دقيقة: KEEP_ALIVE_INTERVAL_SEC 60ث بدل 600ث (طلب المستخدم)
#      — والقيمة تنتقل لحالة البقاء الحي التي تراها اللوحة
#   2) فتح الترشيح المدروس: عمر البنية 20 شمعة بدل 12 (كان يرفض كل الالتقاطات
#      «بنية متقادمة») + صلاحية المعلق 6 شموع بدل 3 — والحدود المحمية
#      (premise-alive/المطاردة/rr_net) لم تُمس
# العقد: 350+2 سابقة لا تنكسر (تأكيدات الإصدار حُدثت FE1.8.6).
import threading
import time

import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة (نفس عقد test_fe100/182)


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 1 — مضاد النوم كل دقيقة
# ─────────────────────────────────────────────────────────────────────────────

class TestKeepAliveMinute:

    def test_default_interval_is_60s(self):
        # [FE1.8.6] طلب المستخدم: نبضة كل دقيقة بدل 10 دقائق
        assert vnz.KEEP_ALIVE_INTERVAL_SEC == 60.0

    def test_interval_propagates_to_live_state(self, monkeypatch):
        # الحالة التي تعرضها اللوحة (keep_alive) يجب أن تحمل النبضة الجديدة
        monkeypatch.setattr(vnz, "KEEP_ALIVE_ENABLED", True)
        monkeypatch.setattr(vnz, "KEEP_ALIVE_URL", "https://fibo-elio.onrender.com")
        vnz.keep_alive_stop.clear()
        with vnz.keep_alive_lock:
            vnz.keep_alive_state["interval_sec"] = None
        t = threading.Thread(target=vnz.keep_alive_loop, daemon=True)
        t.start()
        deadline = time.time() + 5
        while time.time() < deadline and vnz.keep_alive_state.get("interval_sec") is None:
            time.sleep(0.05)
        snap = vnz.keep_alive_snapshot()
        vnz.keep_alive_stop.set()
        t.join(timeout=5)
        assert snap["interval_sec"] == 60
        assert snap["enabled"] is True

    def test_health_reports_new_interval(self):
        # نقطة الاطمئنان العامة تعكس الإعداد (نفس عقد /health في test_fe130)
        body = {"keep_alive": vnz.keep_alive_snapshot()}
        assert body["keep_alive"].get("interval_sec") in (None, 60)


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 2 — فتح الترشيح المدروس
# ─────────────────────────────────────────────────────────────────────────────

class _StubSetup:
    """أقل كائن تقرأه structure_fresh: pivot_indices[5] فقط."""
    def __init__(self, p5_idx):
        self.pivot_indices = [0, 10, 20, 30, 40, p5_idx]


class TestRelaxedGates:

    def test_new_defaults(self):
        assert vnz.MAX_STRUCTURE_AGE_BARS == 36      # [FE1.8.6] بدل 30 — إثبات حي: 43 رفض تقادم مرت كلها بوابة الفرضية
        assert vnz.PENDING_MAX_CANDLES == 6          # بدل 3 — صلاحية أطول للانتظار

    def test_structure_fresh_boundary_at_30(self, monkeypatch):
        # عمر 30 شمعة (7.5س على 15m) = صالح | عمر 31 = رفض — الحد FE1.8.6 بالضبط
        monkeypatch.setattr(vnz, "MAX_STRUCTURE_AGE_BARS", 30)
        df = [{"close": 1.0}] * 121
        assert vnz.structure_fresh(_StubSetup(90), df) is True    # (120)-90 = 30
        assert vnz.structure_fresh(_StubSetup(89), df) is False   # (120)-89 = 31

    def test_structure_fresh_disabled_still_works(self, monkeypatch):
        # 0 يعطل البوابة — عقد FE1.7.0 باقٍ
        monkeypatch.setattr(vnz, "MAX_STRUCTURE_AGE_BARS", 0)
        assert vnz.structure_fresh(_StubSetup(5), [{"close": 1.0}] * 10) is True

    def test_pending_validity_doubled(self):
        # صلاحية الأمر المعلق = PENDING_MAX_CANDLES × شمعة الكشف — على 15m صارت 90 دقيقة
        assert vnz.SIGNAL_TIMEFRAME in vnz.TF_SECONDS
        expected_sec = vnz.PENDING_MAX_CANDLES * vnz.TF_SECONDS[vnz.SIGNAL_TIMEFRAME]
        assert expected_sec == 6 * vnz.TF_SECONDS[vnz.SIGNAL_TIMEFRAME]
        if vnz.SIGNAL_TIMEFRAME == "15m":
            assert expected_sec == 5400  # 1.5 ساعة بدل 45 دقيقة


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 3 — حدود محمية لم تُمس
# ─────────────────────────────────────────────────────────────────────────────

class TestProtectedBoundaries:

    def test_version_bumped_everywhere(self):
        import panel
        assert vnz.BOT_VERSION == "EL2.1.0"
        assert panel.BOT_VERSION == "EL2.1.0"

    def test_render_yaml_carries_new_values(self):
        # مصدر الحقيقة على Render — يجب أن يحمل القيم الجديدة لا الافتراضيات القديمة
        import pathlib
        y = pathlib.Path("render.yaml").read_text(encoding="utf-8")
        assert 'value: "60"' in y          # KEEP_ALIVE_INTERVAL_SEC
        assert 'value: "30"' in y          # MAX_STRUCTURE_AGE_BARS [FE1.8.6]
        assert 'value: "2700"' in y        # IDLE_RESCAN_MIN_GAP_SEC [FE1.8.6]
        assert 'value: "6"' in y           # PENDING_MAX_CANDLES
        # القديم (نبضة 600ث) أزيل كليًا — value: "600" الحالية ملك BAN_LONG_THRESHOLD_SEC [FE1.8.7]
        assert "- key: KEEP_ALIVE_INTERVAL_SEC\n        value: \"600\"" not in y

    def test_quality_gates_untouched(self):
        # الحراسات الجوهرية بقيت بقيمها — التخفيف في الأعمار لا في الجودة
        assert vnz.MAX_ENTRY_DISTANCE_PCT == 1.5      # لا مطاردة
        assert vnz.SYMBOL_COOLDOWN_SEC == 5400        # لا إعادة إنشاء حرفية
        assert getattr(vnz, "RR_NET_MIN", 0.3) == 0.3 # بوابة rr_net
        assert vnz.CLUSTER_MAX_SAME_DIRECTION == 3
