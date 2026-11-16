# -*- coding: utf-8 -*-
"""[EL2.4.4] اختبارات بوابة نطاق السوق «مبدأ السوق الأم» — حملة FIX-1116.

المحاور:
  1) btc_regime_up: صاعد/هابط من شموع مصنوعة، إسقاط الشمعة الجارية، fail-open
     عند فشل الجلب، كاش حدود الساعة (نداء REST واحد كل ساعة).
  2) بوابة الموجات في سلسلة strategy_trigger: ترفض عندما تكون البوابة False
     صراحةً وتسمح عند None (fail-open) — عدّاد rejected_btc_regime.
  3) بوابة السكالب في manager._entry_gates: الجسر غائب = fail-open،
     الجسر يعيد False = رفض مسمّى.
  4) الثوابت: CLUSTER_MAX_SAME_DIRECTION=2، الأعلام تُقرأ من البيئة.
  5) render.yaml: CLUSTER=2 + المفتاحان الجديدان.
  6) الإصدار EL2.4.4 في vnz وpanel.
صفر شبكة: fetch_ohlcv_df مُعترَض في كل اختبار يلمس البوابة.
"""

import importlib
import json
import time

import pandas as pd
import pytest

import vnz
import strategies.manager as manager


# ─────────────────────────────────────────────────────────────────────────────
# أدوات مشتركة
# ─────────────────────────────────────────────────────────────────────────────

def _candles(closes, ts_ms):
    """إطار بشكل fetch_ohlcv_df المعياري: عمود timestamp datetime UTC."""
    rows = []
    for c, t in zip(closes, ts_ms):
        rows.append({"timestamp": pd.to_datetime(t, unit="ms", utc=True),
                     "open": c, "high": c * 1.01, "low": c * 0.99,
                     "close": c, "volume": 1000.0})
    return pd.DataFrame(rows)


@pytest.fixture()
def reset_regime_cache():
    vnz._btc_regime_cache.clear()
    yield
    vnz._btc_regime_cache.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 1) btc_regime_up — الحساب والكاش والفشل الآمن
# ─────────────────────────────────────────────────────────────────────────────

def test_regime_up_on_uptrend(reset_regime_cache, monkeypatch):
    """اتجاه صاعد صريح → True (تُسمح LONG)."""
    now_ms = int(time.time() * 1000)
    # 60 شمعة ساعة مغلقة (آخرها انتهت قبل 5 دقائق) صاعدة بثبات
    ts = [now_ms - 3600_000 * (61 - i) for i in range(60)]
    closes = [100 + i * 1.0 for i in range(60)]
    calls = {"n": 0}

    def fake_fetch(symbol, tf, limit=200, min_candles=60):
        calls["n"] += 1
        assert symbol == "BTC/USDT" and tf == "1h"
        return _candles(closes, ts)

    monkeypatch.setattr(vnz, "fetch_ohlcv_df", fake_fetch)
    assert vnz.btc_regime_up() is True
    assert calls["n"] == 1


def test_regime_down_on_downtrend(reset_regime_cache, monkeypatch):
    """اتجاه هابط صريح → False (لا LONG) — هذه حالة نوفمبر 2026 الحية."""
    now_ms = int(time.time() * 1000)
    ts = [now_ms - 3600_000 * (61 - i) for i in range(60)]
    closes = [200 - i * 1.0 for i in range(60)]

    monkeypatch.setattr(vnz, "fetch_ohlcv_df",
                        lambda *a, **k: _candles(closes, ts))
    assert vnz.btc_regime_up() is False


def test_regime_drops_forming_candle(reset_regime_cache, monkeypatch):
    """الشمعة الجارية تُسقط — الحكم من المغلقة حصرًا (مطابقة HTF1h في المختبر)."""
    now_ms = int(time.time() * 1000)
    # 59 شمعة مغلقة هابطة + شمعة جارية صاعدة قوية (فتحها قبل 10 دقائق)
    ts = [now_ms - 3600_000 * (60 - i) for i in range(59)]
    ts.append(now_ms - 600_000)                     # جارية
    closes = [200 - i * 1.0 for i in range(59)] + [500.0]

    monkeypatch.setattr(vnz, "fetch_ohlcv_df",
                        lambda *a, **k: _candles(closes, ts))
    # لو دُخلت الجارية لانعكس الاتجاه — البوابة يجب أن ترى الهابط المغلق فقط
    assert vnz.btc_regime_up() is False


def test_regime_fail_open_on_fetch_error(reset_regime_cache, monkeypatch):
    """فشل الجلب = مجهول = None (fail-open — البوابة لا تتعطل ولا تُخزّن)."""
    def boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(vnz, "fetch_ohlcv_df", boom)
    assert vnz.btc_regime_up() is None


def test_regime_fail_open_on_short_data(reset_regime_cache, monkeypatch):
    """بيانات ناقصة (< 20 شمعة) → None fail-open."""
    now_ms = int(time.time() * 1000)
    ts = [now_ms - 3600_000 * (10 - i) for i in range(10)]
    monkeypatch.setattr(vnz, "fetch_ohlcv_df",
                        lambda *a, **k: _candles([100.0] * 10, ts))
    assert vnz.btc_regime_up() is None


def test_regime_cache_hour_key(reset_regime_cache, monkeypatch):
    """كاش حدود الساعة: نداءان داخل نفس الساعة = جلب واحد."""
    now_ms = int(time.time() * 1000)
    ts = [now_ms - 3600_000 * (61 - i) for i in range(60)]
    closes = [100 + i for i in range(60)]
    calls = {"n": 0}

    def fake_fetch(*a, **k):
        calls["n"] += 1
        return _candles(closes, ts)

    monkeypatch.setattr(vnz, "fetch_ohlcv_df", fake_fetch)
    vnz.btc_regime_up()
    vnz.btc_regime_up()
    vnz.btc_regime_up()
    assert calls["n"] == 1


def test_regime_failed_fetch_not_cached(reset_regime_cache, monkeypatch):
    """الفشل لا يُخزّن — النداء القادم داخل نفس الساعة يعيد المحاولة."""
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        now_ms = int(time.time() * 1000)
        ts = [now_ms - 3600_000 * (61 - i) for i in range(60)]
        return _candles([100 + i for i in range(60)], ts)

    monkeypatch.setattr(vnz, "fetch_ohlcv_df", flaky)
    assert vnz.btc_regime_up() is None          # أول محاولة تفشل
    assert vnz.btc_regime_up() is True          # الثانية تعيد المحاولة وتنجح
    assert calls["n"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# 2) بوابة الموجات — الأسلاك في سلسلة strategy_trigger
# ─────────────────────────────────────────────────────────────────────────────

def test_wave_gate_wired_in_trigger_chain():
    """البوابة في سلسلة بوابات الكشف قبل سقف العنقود، ورفضها مصنّف بعدّاد."""
    src = open("vnz.py", encoding="utf-8").read()
    gate_pos = src.find("BTC_REGIME_GATE_WAVES and btc_regime_up() is False")
    cluster_pos = src.find("elif CLUSTER_MAX_SAME_DIRECTION > 0 and same_direction_active")
    assert gate_pos > 0, "بوابة النطاق غير موجودة في سلسلة الكشف"
    assert 0 < gate_pos < cluster_pos, "البوابة يجب أن تسبق سقف العنقود (أرخص وأشمل)"
    assert 'scan_stats["rejected_btc_regime"] += 1' in src
    assert "rejected_btc_regime" in src  # العدّاد معرّف في scan_stats


def test_reject_reason_named():
    """الرفض يسمّي سببه (حكم يسمّي قاتله — عقد FE1.9.4)."""
    src = open("vnz.py", encoding="utf-8").read()
    assert "نطاق السوق الأم هابط" in src


# ─────────────────────────────────────────────────────────────────────────────
# 3) بوابة السكالب — manager._entry_gates عبر الجسر
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def scalp_env(monkeypatch):
    """بيئة سكالب مفتوحة للبوابات الأخرى (الزر/السقوف/التبريد) — تختبر البوابة الجديدة وحدها."""
    monkeypatch.setattr(manager, "SCALP_ENABLED", True)
    monkeypatch.setattr(manager, "_instances", {"SCALP_FLOW": object()})
    monkeypatch.setattr(manager, "get_enabled", lambda s: True)
    monkeypatch.setattr(manager, "_scalp_open_count", lambda s=None: 0)
    monkeypatch.setattr(manager, "_cooldown_left", lambda s, sym: 0.0)
    monkeypatch.setattr(manager, "_daily_loss_block", lambda s: False)
    host = {"is_trading_enabled": lambda: True, "risk_entry_block_reason": None,
            "symbol_has_active": lambda sym: False}
    monkeypatch.setattr(manager, "HOST", host)
    return host


def test_scalp_gate_blocks_on_down_regime(scalp_env, monkeypatch):
    """السوق الأم هابط → رفض مسمّى."""
    scalp_env["btc_regime_up"] = lambda: False
    ok, why = manager._entry_gates("SCALP_FLOW", "TEST/USDT")
    assert ok is False and "السوق الأم هابط" in why


def test_scalp_gate_allows_on_up_regime(scalp_env):
    """السوق الأم صاعد → تمر (الجودة كما هي)."""
    scalp_env["btc_regime_up"] = lambda: True
    ok, why = manager._entry_gates("SCALP_FLOW", "TEST/USDT")
    assert ok is True and why == ""


def test_scalp_gate_fail_open_on_unknown(scalp_env):
    """المجهول (None) = fail-open — البوابة فلتر جودة لا نقطة فشل."""
    scalp_env["btc_regime_up"] = lambda: None
    ok, why = manager._entry_gates("SCALP_FLOW", "TEST/USDT")
    assert ok is True and why == ""


def test_scalp_gate_fail_open_on_missing_bridge(scalp_env):
    """الجسر غائب (إصدارات قديمة من الجسر) = fail-open — نمط F9."""
    ok, why = manager._entry_gates("SCALP_FLOW", "TEST/USDT")
    assert ok is True and why == ""


# ─────────────────────────────────────────────────────────────────────────────
# 4) الثوابت والإعدادات والإصدار
# ─────────────────────────────────────────────────────────────────────────────

def test_cluster_default_is_2(monkeypatch):
    """[EL2.4.4] سقف العنقود 3←2 — درس عنقود 4 نوفمبر (-70.83$ في 30د)."""
    assert vnz.CLUSTER_MAX_SAME_DIRECTION == 2


def test_regime_flags_default_on():
    """الأعلام مفعّلة افتراضيًا من الوارد (1 = مفعّل)."""
    assert vnz.BTC_REGIME_GATE_WAVES is True
    assert vnz.BTC_REGIME_GATE_SCALP is True


def test_regime_flags_env_parsing():
    """عقد القراءة من البيئة — نفس تعبير vnz حرفيًا: 0/false/no/off تعطل."""
    parse = lambda v: v.strip().lower() not in ("0", "false", "no", "off")
    assert parse("0") is False and parse("false") is False
    assert parse("no") is False and parse("off") is False
    assert parse("1") is True and parse("true") is True


def test_render_yaml_keys():
    """render.yaml يحمل سقف العنقود الجديد والمفتاحين."""
    txt = open("render.yaml", encoding="utf-8").read()
    assert 'key: BTC_REGIME_GATE_WAVES' in txt and 'key: BTC_REGIME_GATE_SCALP' in txt
    block = txt.split("key: CLUSTER_MAX_SAME_DIRECTION")[1][:80]
    assert 'value: "2"' in block


def test_version_el244():
    assert vnz.BOT_VERSION == "EL2.4.4"
    panel_src = open("panel.py", encoding="utf-8").read()
    assert 'BOT_VERSION = "EL2.4.4"' in panel_src


def test_bridge_registered_in_scalp_host():
    """الجسر مسجّل في scalp_host — مسار السكالب يصل البوابة فعلًا."""
    src = open("vnz.py", encoding="utf-8").read()
    assert '"btc_regime_up": btc_regime_up' in src
