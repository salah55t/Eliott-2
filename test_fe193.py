#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fe193.py — اختبارات FE1.9.3 «تصنيف صادق»

الخلفية (أول حزام إعادة تشغيل في تاريخ المشروع — replay_orders.py):
  مسار الإنتاج الحرفي (كاشف ← بوابات ← create_pending_signal) على بيانات حقيقية
  وُلّد فيه 30 حدث أمر معلق عبر 5 رموز (XLM/ZK/ONDO/AVAX/LTC) في ~4 أيام —
  المنطق سليم نهاية-إلى-نهاية. لكن الرفض الوحيد المصنّف خطأً ظهر:
  PUMP مرّ بكل البوابات الهيكلية (تقادم/فرضية/عمق/HTF) ومات عند الإنشاء بسبب
  «أسعار الإعداد غير منطقية» بينما الحقيقة: سلّم الأهداف بلا درجة تحقق أرضية
  TP_MIN_RR (أعلى درجة 0.485R < 0.5) وأساس 1.618 تحت الدخول = هندسة بلا هدف
  مربح كفاية — رفض سليم استراتيجيًا لكن تسميته توحي بعطل حساب وتضلل قارئ اللوحة.

الجولات:
  1) الرفض الصادق الجديد: سلّم بلا درجة مؤهلة + أساس تحت الدخول → «لا هدف يحقق
     أرضية R:R» + عداد rejected_no_target (وليس «غير منطقية»)
  2) درجة سلّم مؤهلة تنقذ إعدادًا أساسه تحت الدخول → أمر معلق بالدرجة المختارة
  3) درجة مؤهلة لكن أرضية R:R الصافي → تصنيف «R:R صافٍ» الصحيح (يعبر الصحة لا العطل)
  4) السلّم المعطل (TP_LADDER_ENABLED=0) يحتفظ بالسلوك القديم حرفيًا
  5) تزامن الإصدار FE1.9.3 (vnz + panel)

تشغيل: pytest test_fe193.py -v   (من داخل مجلد المشروع)
"""

import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة (نفس عقد test_fe100)
import panel as panel_mod


# ─────────────────────────────────────────────────────────────────────────────
# تجهيزات — نفس عقد test_fe170
# ─────────────────────────────────────────────────────────────────────────────

class _StubFib:
    def __init__(self):
        self.wave2_retrace_pct = 0.5
        self.wave4_retrace_pct = 0.3
        self.wave2_in_zone = True
        self.wave4_in_zone = True


class _StubValidation:
    def __init__(self):
        self.fib = _StubFib()


def make_setup(prices=None, p5_idx: int = 95, direction: str = "BULLISH"):
    """P=[90,100,100,115,104,108]: دخول = 115−0.382×15 = 109.27،
    وقف = 90×0.999 = 89.91 → مخاطرة 19.36، أساس 1.618 الافتراضي 116.18."""
    from engine.pattern_detector import DetectedSetup
    import pandas as pd
    P = prices or [90.0, 100.0, 100.0, 115.0, 104.0, 108.0]
    return DetectedSetup(
        symbol="TEST/USDT", timeframe="15m", direction=direction,
        pivot_indices=[0, 10, 20, 30, 40, p5_idx],
        pivot_timestamps=[pd.Timestamp("2026-01-01", tz="UTC")] * 6,
        pivot_prices=P,
        validation_result=_StubValidation(),
        detected_at=pd.Timestamp("2026-01-01", tz="UTC"),
    )


@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
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


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 1 — الرفض الصادق «لا هدف يحقق أرضية R:R»
# ─────────────────────────────────────────────────────────────────────────────

class TestNoTargetHonestReject:

    def test_ladder_below_floor_base_below_entry(self, clean_db, monkeypatch):
        # حالة PUMP الحية: كل درجات السلّم تحت الأرضية والأساس 1.618 تحت الدخول
        monkeypatch.setattr(vnz, "compute_take_profit", lambda s: 105.0)
        monkeypatch.setattr(vnz, "compute_tp_ladder",
                            lambda s: [(109.5, "w5_eq_w1"), (111.0, "w5_0618_w3")])
        with vnz.scan_stats_lock:
            vnz.scan_stats["rejected_no_target"] = 0
        assert vnz.create_pending_signal("TEST/USDT", make_setup()) is False
        reason = vnz._reject_reason.get("TEST/USDT", "")
        assert "لا هدف" in reason, f"التصنيف الصادق مفقود: {reason}"
        assert "غير منطقية" not in reason, "التصنيف القديم المضلل ظهر مجددًا"
        assert vnz.scan_stats["rejected_no_target"] == 1
        rows = clean_db.query("SELECT COUNT(*) AS n FROM signals")
        assert int(rows[0]["n"]) == 0, "الرفض يجب ألا يُنشئ صفًا"

    def test_reason_carries_numbers(self, clean_db, monkeypatch):
        # الرسالة تحمل الأرقام التي تفسر القرار (أفضل R وأرضية R:R)
        monkeypatch.setattr(vnz, "compute_take_profit", lambda s: 100.0)
        monkeypatch.setattr(vnz, "compute_tp_ladder", lambda s: [(109.4, "w5_eq_w1")])
        vnz.create_pending_signal("TEST/USDT", make_setup())
        reason = vnz._reject_reason.get("TEST/USDT", "")
        assert "0.01R" in reason  # (109.4−109.27)/19.36 = 0.0067 → 0.01R
        assert "0.5" in reason    # أرضية TP_MIN_RR الافتراضية

    def test_old_message_kept_for_true_garbage(self, clean_db, monkeypatch):
        # السلّم المعطل + أساس تحت الدخول = الحالة القديمة حرفيًا (بلا تصنيف جديد)
        monkeypatch.setattr(vnz, "TP_LADDER_ENABLED", False)
        monkeypatch.setattr(vnz, "compute_take_profit", lambda s: 105.0)
        with vnz.scan_stats_lock:
            vnz.scan_stats["rejected_no_target"] = 0
        assert vnz.create_pending_signal("TEST/USDT", make_setup()) is False
        assert "غير منطقية" in vnz._reject_reason.get("TEST/USDT", "")
        assert vnz.scan_stats["rejected_no_target"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 2 — درجة مؤهلة تنقذ إعدادًا أساسه تحت الدخول
# ─────────────────────────────────────────────────────────────────────────────

class TestLadderRescue:

    def test_qualified_rung_overrides_degenerate_base(self, clean_db, monkeypatch):
        # أساس 1.618 تحت الدخول لكن درجة سلّم 119 تحقق 0.50R ≥ 0.5 → أمر معلق بها
        monkeypatch.setattr(vnz, "compute_take_profit", lambda s: 105.0)
        monkeypatch.setattr(vnz, "compute_tp_ladder", lambda s: [(119.0, "w5_eq_w1")])
        assert vnz.create_pending_signal("TEST/USDT", make_setup()) is True
        row = clean_db.query("SELECT * FROM signals", one=True)
        assert row is not None and row["status"] == "pending"
        assert abs(float(row["take_profit"]) - 119.0) < 1e-9

    def test_qualified_rung_still_respects_rr_net_floor(self, clean_db, monkeypatch):
        # الدرجة تجتاز صحة الإنشاء لكن أرضية R:R الصافي ترفضها — تصنيف «R:R صافٍ»
        # وليس «غير منطقية» (يثبت العبور الصحيح بين البوابات)
        monkeypatch.setattr(vnz, "compute_take_profit", lambda s: 105.0)
        monkeypatch.setattr(vnz, "compute_tp_ladder", lambda s: [(119.0, "w5_eq_w1")])
        monkeypatch.setattr(vnz, "RR_NET_MIN", 0.9)
        with vnz.scan_stats_lock:
            vnz.scan_stats["rejected_rr_net"] = 0
        assert vnz.create_pending_signal("TEST/USDT", make_setup()) is False
        reason = vnz._reject_reason.get("TEST/USDT", "")
        assert "R:R" in reason
        assert "غير منطقية" not in reason
        assert vnz.scan_stats["rejected_rr_net"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 3 — تزامن الإصدار
# ─────────────────────────────────────────────────────────────────────────────

class TestVersion:

    def test_vnz_version(self):
        assert vnz.BOT_VERSION == "EL2.3.0"

    def test_panel_version(self):
        assert panel_mod.BOT_VERSION == "EL2.3.0"

    def test_new_counter_in_stats(self):
        assert "rejected_no_target" in vnz.scan_stats
