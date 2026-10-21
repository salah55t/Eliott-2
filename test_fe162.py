#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fe162.py — اختبارات بوابة حيوية الفرضية FE1.6.2

المشكلة الحية (20:30-20:46 من سجلات production):
  الماسح (كل 15 دقيقة) يولّد إشارات صاعدة من نوافذ P0-P5 تاريخية انهار السعر
  الحالي تحتها (STRK: إغلاق 0.0849 مقابل P0=0.1126) — ثم يبطلها monitor_step
  خلال 60 ثانية («إبطال بنيوي: إغلاق خلف P0») — 5 من 7 إشارات ماتت فور ولادتها
  وحلقة إنشاء/إلغاء DOA تتكرر كل دورة مسح، فلا يُملأ أمر معلق أبدًا.

الإصلاح: premise_alive() — نفس شرط الإبطال البنيوي يُطبق لحظة الإنشاء قبل
create_pending_signal، مع عداد rejected_stale_premise وسجل واضح.

الجولات:
  1) premise_alive: حية فوق P0 / ماتت دونها / تساهل عند بيانات فاسدة
  2) scan_cycle تكامليًا: فرضية ماتة → لا إشارة + عداد — فرضية حية → إشارة تُخلق
  3) الترتيب: البوابة قبل htf_bias فلا يُستهلك نداء REST لميت

تشغيل: pytest test_fe162.py -v   (من داخل مجلد المشروع)
"""

import pandas as pd
import pytest

import vnz


# ─────────────────────────────────────────────────────────────────────────────
# تجهيزات
# ─────────────────────────────────────────────────────────────────────────────

def make_setup(p0: float, direction: str = "BULLISH"):
    from engine.pattern_detector import DetectedSetup
    return DetectedSetup(
        symbol="TEST/USDT", timeframe="15m", direction=direction,
        pivot_indices=[0, 10, 20, 30, 40, 50],
        pivot_timestamps=[pd.Timestamp("2026-01-01", tz="UTC")] * 6,
        pivot_prices=[p0, p0 * 1.05, p0 * 1.01, p0 * 1.12, p0 * 1.03, p0 * 1.09],
        validation_result=None,
        detected_at=pd.Timestamp("2026-01-01", tz="UTC"),
    )


class TestPremiseAlive:

    def test_alive_above_p0(self):
        assert vnz.premise_alive(make_setup(0.10), 0.13) is True

    def test_dead_below_p0(self):
        # الحالة الحية من production: STRK إغلاق 0.0849 مقابل P0=0.1126
        assert vnz.premise_alive(make_setup(0.1126), 0.0849) is False

    def test_equal_p0_is_alive(self):
        # monitor_step يبطل عند close < p0 فقط — المساواة حية (اتساق القاعدتين)
        assert vnz.premise_alive(make_setup(0.10), 0.10) is True

    def test_failopen_on_bad_data(self):
        s_bad_p0 = make_setup(0.10)
        s_bad_p0.pivot_prices = [None, 0.1, 0.1, 0.1, 0.1, 0.1]           # P0 فاسد
        assert vnz.premise_alive(s_bad_p0, 0.10) is True
        assert vnz.premise_alive(make_setup(0.10), None) is True           # سعر فاسد
        class Broken:
            pivot_prices = None
        assert vnz.premise_alive(Broken(), 0.10) is True


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 2 — scan_cycle تكامليًا
# ─────────────────────────────────────────────────────────────────────────────

def synth_df(last_close: float) -> pd.DataFrame:
    closes = [last_close * 1.2, last_close * 1.1, last_close]
    return pd.DataFrame({"close": closes,
                         "open": closes, "high": closes,
                         "low": closes, "volume": [1.0] * 3})


@pytest.fixture()
def scan_env(monkeypatch):
    """عزل كامل لدورة المسح: قائمة رمز واحد + بلا شبكة ولا قاعدة حقيقية."""
    calls = {"created": [], "registered": []}

    class FakeDB:
        def ensure(self):
            pass
    monkeypatch.setattr(vnz, "db", FakeDB())
    monkeypatch.setattr(vnz, "watchlist", ["TEST/USDT"])
    monkeypatch.setattr(vnz, "INTER_SYMBOL_SLEEP", 0.0)
    monkeypatch.setattr(vnz, "is_trading_enabled", True)
    monkeypatch.setattr(vnz, "HTF_BIAS_ENABLED", False)
    monkeypatch.setattr(vnz, "symbol_has_active", lambda s: False)
    monkeypatch.setattr(vnz, "active_trade_count", lambda: 0)
    monkeypatch.setattr(vnz, "htf_bias", lambda s: True)
    monkeypatch.setattr(vnz, "create_pending_signal",
                        lambda sym, setup, last_close=0.0: calls["created"].append(sym) or True)  # [FE1.7.0] وسيط last_close
    monkeypatch.setattr(
        vnz, "register_detection",
        lambda sym, setup, traded=False: calls["registered"].append((sym, traded)))
    # عدادات نظيفة
    for k in ("cycles", "scanned", "setups_valid", "setups_bull_traded",
              "setups_bear_seen", "rejected_active_limit",
              "rejected_symbol_busy", "rejected_htf_bias",
              "rejected_stale_premise"):
        vnz.scan_stats[k] = 0
    return calls


class TestScanCycleGate:

    def test_dead_premise_not_created(self, scan_env, monkeypatch):
        setup = make_setup(0.1126)
        monkeypatch.setattr(vnz, "fetch_ohlcv_df",
                            lambda s, tf, limit=500, min_candles=0: synth_df(0.0849))
        monkeypatch.setattr(vnz.detector, "scan", lambda df: [setup])
        vnz.scan_cycle()
        assert scan_env["created"] == [], "إشارة من فرضية ماتة يجب ألا تُخلق"
        assert vnz.scan_stats["rejected_stale_premise"] == 1
        # الكشف يُسجل للوحة حتى مع الرفض (شكاف الشفافية)
        assert scan_env["registered"] == [("TEST/USDT", False)]

    def test_alive_premise_created(self, scan_env, monkeypatch):
        setup = make_setup(0.10)
        monkeypatch.setattr(vnz, "fetch_ohlcv_df",
                            lambda s, tf, limit=500, min_candles=0: synth_df(0.13))
        monkeypatch.setattr(vnz.detector, "scan", lambda df: [setup])
        vnz.scan_cycle()
        assert scan_env["created"] == ["TEST/USDT"]
        assert scan_env["registered"] == [("TEST/USDT", True)]
        assert vnz.scan_stats["rejected_stale_premise"] == 0

    def test_gate_before_htf_call(self, scan_env, monkeypatch):
        """فرضية ماتة + بوابة HTF مفعلة → htf_bias لا يُستدعى أصلًا (توفير REST)."""
        setup = make_setup(0.1126)
        monkeypatch.setattr(vnz, "HTF_BIAS_ENABLED", True)
        htf_calls = []
        monkeypatch.setattr(vnz, "htf_bias", lambda s: htf_calls.append(s) or False)
        monkeypatch.setattr(vnz, "fetch_ohlcv_df",
                            lambda s, tf, limit=500, min_candles=0: synth_df(0.0849))
        monkeypatch.setattr(vnz.detector, "scan", lambda df: [setup])
        vnz.scan_cycle()
        assert htf_calls == [], "لا نداء HTF لميتة فرضيتها"
        assert vnz.scan_stats["rejected_stale_premise"] == 1

    def test_bearish_detections_untouched(self, scan_env, monkeypatch):
        """الكشف الهابط يُعرض فقط — البوابة لا تمس مساره."""
        bear = make_setup(0.1126, direction="BEARISH")
        monkeypatch.setattr(vnz, "fetch_ohlcv_df",
                            lambda s, tf, limit=500, min_candles=0: synth_df(0.0849))
        monkeypatch.setattr(vnz.detector, "scan", lambda df: [bear])
        vnz.scan_cycle()
        assert scan_env["created"] == []
        assert vnz.scan_stats["rejected_stale_premise"] == 0
        assert scan_env["registered"] == [("TEST/USDT", False)]


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 3 — عداد الإحصاء متاح في /api/all
# ─────────────────────────────────────────────────────────────────────────────

class TestStatsExposure:

    def test_counter_in_scan_stats_dict(self):
        assert "rejected_stale_premise" in vnz.scan_stats
