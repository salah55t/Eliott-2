#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fe190.py — اختبارات FE1.9.0 «كشف لحظي»: إصلاح جذري لتأخر الكشف

الطلب الحي (المستخدم):
  «اصلح تأخر الكشف جذريا»

الجذر المؤكد بالأرقام الحية (204 بنية صالحة / 55 «فرضية ميتة» / 13 تقادم):
  تأكيد محور الزيجزاج (حركة ≥ العتبة) يقع بين دورتي كشف — ودورة الكشف القادمة
  (حتى 15 دقيقة على 15m) تجد التصحيح قد أكل نافذة الدخول أو كسر P0، فتُقيَّم
  البنية متأخرة أو ميتة، وتعاد ولادة الجثث كل دورة ما دام التصحيح جاريًا.

الحل الثلاثي (كل محور له اختبارات):
  1) نبض الحركة: أسعار ويب سوكت الحية توقظ الكشف فور تحرك أي رمز بعتبة الزيجزاج
     منذ آخر تقييم — التقييم خلال ثوانٍ من اكتمال التوقيع (صفر REST/وزن)
  2) إعادة ترتيب تصنيفي: التقادم قبل الحيوية — «فرضية ميتة» يصير عداد تأخر
     حقيقي خالص (حية العمر) والأثرية تُحسب تقادمًا — تشخيص صادق نهائي
  3) بوابة التصحيح العميق (78.6%): رفض مبكر مصنّف بدل ولادة أمر زومبي يموت بأول شمعة

تشغيل: pytest test_fe190.py -v   (من داخل مجلد المشروع)
"""

import sqlite3

import pandas as pd
import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False


# ─────────────────────────────────────────────────────────────────────────────
# تجهيزات (نفس عقد test_fe185/189)
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
    from engine.pattern_detector import DetectedSetup
    # افتراضي: بنية صاعدة P0=90 → P5=110 (مدى 20) — مثالية لبوابة عمق التصحيح
    P = prices or [90.0, 95.0, 92.0, 105.0, 100.0, 110.0]
    return DetectedSetup(
        symbol="TEST/USDT", timeframe="15m", direction=direction,
        pivot_indices=[0, 10, 20, 30, 40, p5_idx],
        pivot_timestamps=[pd.Timestamp("2026-01-01", tz="UTC")] * 6,
        pivot_prices=P,
        validation_result=_StubValidation(),
        detected_at=pd.Timestamp("2026-01-01", tz="UTC"),
    )


def synth_df(last_close: float, n: int = 100) -> pd.DataFrame:
    vals = [last_close] * n
    return pd.DataFrame({"close": vals, "open": vals, "high": vals,
                         "low": vals, "volume": [1.0] * n})


@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    """قاعدة SQLite مؤقتة لكل اختبار — عزل كامل."""
    monkeypatch.setattr(vnz, "USE_POSTGRES", False)
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    old = vnz.db.conn
    vnz.db.conn = conn
    vnz.init_db()
    vnz.set_paper_balance(vnz.PAPER_BALANCE_START)
    yield vnz.db
    vnz.db.conn = old


# ─────────────────────────────────────────────────────────────────────────────
# 1) بوابة عمق التصحيح
# ─────────────────────────────────────────────────────────────────────────────

def test_deep_retrace_boundaries():
    s = make_setup()  # P0=90, P5=110 — مدى 20
    assert vnz.deep_retrace_ok(s, 110.0) is True     # عند القمة — صفر تصحيح
    assert vnz.deep_retrace_ok(s, 100.0) is True     # 50% — تصحيح صحي
    assert vnz.deep_retrace_ok(s, 94.3) is True      # 78.5% — دون الحد
    assert vnz.deep_retrace_ok(s, 94.0) is False     # 80% — رفض مبكر
    assert vnz.deep_retrace_ok(s, 90.0) is False     # 100% — عند الإبطال
    assert vnz.deep_retrace_ok(s, 89.0) is False     # تحت P0 (premise ستلحقها)


def test_deep_retrace_disabled_and_fail_open(monkeypatch):
    s = make_setup()
    monkeypatch.setattr(vnz, "DEEP_RETRACE_BLOCK_PCT", 0.0)
    assert vnz.deep_retrace_ok(s, 90.0) is True      # 0 يعطل البوابة

    class _Broken:
        pivot_prices = None
    assert vnz.deep_retrace_ok(_Broken(), 100.0) is True  # فشل القراءة = تساهل


def test_deep_retrace_flat_range_passes():
    # P5 == P0 → مدى صفر: لا حساب ولا رفض (تساهل)
    s = make_setup(prices=[100.0, 100.0, 100.0, 100.0, 100.0, 100.0])
    assert vnz.deep_retrace_ok(s, 100.0) is True


# ─────────────────────────────────────────────────────────────────────────────
# 2) نبض الحركة — الشرط النقي
# ─────────────────────────────────────────────────────────────────────────────

def test_momentum_under_threshold_never_kicks():
    # 0.5% < عتبة الزيجزاج 0.6% — لا إيقاظ حتى بفجوة كافية
    assert vnz.momentum_should_kick(100.0, 100.5, 0.0, now=1e9) is False


def test_momentum_over_threshold_kicks_after_gap():
    assert vnz.momentum_should_kick(100.0, 100.7, 0.0, now=1e9) is True   # صعود 0.7%
    assert vnz.momentum_should_kick(100.0, 99.3, 0.0, now=1e9) is True    # هبوط 0.7% — abs


def test_momentum_gap_blocks_rapid_rekick():
    now = 10_000.0
    assert vnz.momentum_should_kick(100.0, 101.0, now - 30.0, now=now) is False  # فجوة 30ث < 90ث
    assert vnz.momentum_should_kick(100.0, 101.0, now - 91.0, now=now) is True


def test_momentum_rejects_bad_inputs():
    assert vnz.momentum_should_kick(0.0, 100.0, 0.0, now=1e9) is False
    assert vnz.momentum_should_kick(100.0, -1.0, 0.0, now=1e9) is False


# ─────────────────────────────────────────────────────────────────────────────
# 3) مرجع النبض — تسجيل أسعار التقييم
# ─────────────────────────────────────────────────────────────────────────────

def test_record_scan_price(clean_db):
    with vnz._last_scan_prices_lock:
        vnz._last_scan_prices.clear()
    vnz._record_scan_price("TEST/USDT", 85.0)
    with vnz._last_scan_prices_lock:
        assert vnz._last_scan_prices.get("TEST/USDT") == 85.0
    vnz._record_scan_price("TEST/USDT", 0)        # يُبتلع بصمت
    vnz._record_scan_price("TEST/USDT", "لا شيء")  # يُبتلع بصمت
    with vnz._last_scan_prices_lock:
        assert vnz._last_scan_prices.get("TEST/USDT") == 85.0


def test_momentum_loop_guard_single_start():
    # الحارس: استدعاء ثانٍ (أو خيط إقلاع مكرر) يعيد فورًا بلا حجب ولا إقلاع مزدوج
    vnz._momentum_state["started"] = True
    vnz.momentum_loop()  # يعيد فورًا — الحلقة اللانهائية لا تُلامس في الاختبارات
    assert vnz._momentum_state["started"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 4) التصنيف في scan_cycle — إعادة الترتيب (الأثرية = تقادم، الحية الميتة = فرضية)
# ─────────────────────────────────────────────────────────────────────────────

class _FakeDet:
    """كاشف وهمي يعيد بنية واحدة ثابتة."""
    def __init__(self, setup):
        self.s = setup

    def scan(self, df):
        return [self.s]


def _run_one_scan_cycle(clean_db, monkeypatch, setup):
    """تشغيل دورة كشف واحدة على رمز واحد بكاشف وهمي — بلا شبكة إطلاقًا."""
    df = synth_df(85.0, n=100)  # إغلاق 85 — تحت P0=90 (فرضية ميتة)
    monkeypatch.setattr(vnz, "watchlist", ["TEST/USDT"])
    monkeypatch.setattr(vnz, "fetch_ohlcv_df", lambda *a, **k: df)
    monkeypatch.setattr(vnz, "detector", _FakeDet(setup))
    monkeypatch.setattr(vnz, "HTF_BIAS_ENABLED", False)
    monkeypatch.setattr(vnz, "INTER_SYMBOL_SLEEP", 0)
    monkeypatch.setattr(vnz, "is_trading_enabled", True)
    vnz.scan_cycle()
    return df


def test_scan_classifies_ancient_dead_as_old_structure(clean_db, monkeypatch):
    # بنية أثرية (عمر P5 = 89 شمعة > 36) وميتة — يجب أن تُحسب تقادمًا لا فرضية ميتة
    with vnz.scan_stats_lock:
        vnz.scan_stats["rejected_old_structure"] = 0
        vnz.scan_stats["rejected_stale_premise"] = 0
        vnz.scan_stats["scanned"] = 0
    _run_one_scan_cycle(clean_db, monkeypatch, make_setup(p5_idx=10))
    with vnz.scan_stats_lock:
        assert vnz.scan_stats["rejected_old_structure"] == 1   # التصنيف الصادق
        assert vnz.scan_stats["rejected_stale_premise"] == 0
        assert vnz.scan_stats["scanned"] == 1
    # مرجع النبض سُجل من الدورة (85.0)
    with vnz._last_scan_prices_lock:
        assert vnz._last_scan_prices.get("TEST/USDT") == 85.0


def test_scan_classifies_fresh_dead_as_premise(clean_db, monkeypatch):
    # بنية حية العمر (عمر P5 = 4 شمعة ≤ 36) وميتة — «تأخر كشف حقيقي» خالص
    with vnz.scan_stats_lock:
        vnz.scan_stats["rejected_old_structure"] = 0
        vnz.scan_stats["rejected_stale_premise"] = 0
    _run_one_scan_cycle(clean_db, monkeypatch, make_setup(p5_idx=95))
    with vnz.scan_stats_lock:
        assert vnz.scan_stats["rejected_stale_premise"] == 1
        assert vnz.scan_stats["rejected_old_structure"] == 0


def test_scan_alive_premise_deep_retrace_blocks(clean_db, monkeypatch):
    # بنية حية العمر وفوق P0 لكن التصحيح أكل 80% — بوابة التصحيح العميق ترفضها
    df = synth_df(94.0, n=100)  # (110-94)/20 = 80% ≥ 78.6%
    monkeypatch.setattr(vnz, "watchlist", ["TEST/USDT"])
    monkeypatch.setattr(vnz, "fetch_ohlcv_df", lambda *a, **k: df)
    monkeypatch.setattr(vnz, "detector", _FakeDet(make_setup(p5_idx=95)))
    monkeypatch.setattr(vnz, "HTF_BIAS_ENABLED", False)
    monkeypatch.setattr(vnz, "INTER_SYMBOL_SLEEP", 0)
    monkeypatch.setattr(vnz, "is_trading_enabled", True)
    with vnz.scan_stats_lock:
        vnz.scan_stats["rejected_deep_retrace"] = 0
        vnz.scan_stats["rejected_stale_premise"] = 0
        vnz.scan_stats["rejected_old_structure"] = 0
    vnz.scan_cycle()
    with vnz.scan_stats_lock:
        assert vnz.scan_stats["rejected_deep_retrace"] == 1
        assert vnz.scan_stats["rejected_stale_premise"] == 0
    assert vnz._get_reject_reason("TEST/USDT").startswith("تصحيح عميق")


# ─────────────────────────────────────────────────────────────────────────────
# 5) حراسات عامة
# ─────────────────────────────────────────────────────────────────────────────

def test_version_and_env_knobs():
    assert vnz.BOT_VERSION == "EL2.4.1"
    assert vnz.MOMENTUM_LOOP_SEC > 0
    assert vnz.KICK_MIN_GAP_SEC >= 5.0
    assert 0.5 <= vnz.DEEP_RETRACE_BLOCK_PCT <= 0.95  # حد معقول افتراضيًا 0.786
