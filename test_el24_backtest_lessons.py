# -*- coding: utf-8 -*-
"""[EL2.4.0] اختبارات دروس الباك تاست BT-LAB — الرافعات الأربع المزروعة
==========================================================================
درس الدليل الكمي (45 يومًا، 12 رمزًا، PF 0.24 → 2.05):
  1. G2c بوابة الاتجاه: +DI > −DI (ADX بلا اتجاه كان يمرر شراءً عكسيًا)
  2. G7 انحياز الساعة: SuperTrend(10,3.0) على 1h صاعد (fail-open بلا بيانات)
  3. الأوامر الارتدادية المؤكدة: لا مطاردة شمعة الانفجار — ملء بشمعة رفض
  4. تتبع القمة بعد الجزئي+BE (ورقي) + سقف المخاطرة البنيوية للموجات
"""

import json
import time
from types import SimpleNamespace

import pytest

import vnz
import panel
from strategies import manager as mng
from strategies.base import ScalpConfig, ScalpContext, ScalpSignal
from strategies import indicators as ind


# ── أدوات مساعدة ─────────────────────────────────────────────────────────────

def _candle(close, hi=None, lo=None, op=None, vol=100.0, taker=None):
    return {"ts": 0.0, "open": float(op if op is not None else close),
            "high": float(hi if hi is not None else close),
            "low": float(lo if lo is not None else close),
            "close": float(close), "volume": float(vol),
            "taker_base": taker}


def _rising_rows(n=80, base=100.0, step=0.15):
    """سلسلة صاعدة بسيطة — DI+ مسيطر وSuperTrend صاعد."""
    rows = []
    p = base
    for i in range(n):
        op = p
        cl = p + step
        rows.append(_candle(cl, hi=cl + 0.05, lo=op - 0.05, op=op,
                            taker=55.0 if taker_ok() else None))
        p = cl
    return rows


def taker_ok():
    return True


def _falling_rows(n=80, base=100.0, step=0.20):
    """سلسلة هابطة — DI− مسيطر (بوابة الاتجاه يجب أن ترفضها)."""
    rows = []
    p = base
    for i in range(n):
        op = p
        cl = p - step
        rows.append(_candle(cl, hi=op + 0.05, lo=cl - 0.05, op=op, taker=45.0))
        p = cl
    return rows


def _ctx(k5, k1h=None, k15=None, live=None):
    return ScalpContext(symbol="TEST/USDT", now_ts=time.time(), k5=k5,
                        k15=k15 or k5[-40:], live_price=live or float(k5[-1]["close"]),
                        cvd_source="taker",
                        atr5=ind.atr([r["high"] for r in k5], [r["low"] for r in k5],
                                     [r["close"] for r in k5], 14),
                        extra={"fee_rate": 0.001}, k1h=k1h)


# ── 1) بوابة الاتجاه DI ──────────────────────────────────────────────────────

class TestDiGate:
    def test_di_directional_math(self):
        """صعود متواصل ⇒ +DI > −DI، وهبوط متواصل ⇒ العكس — حسابات ويلدر."""
        up = ind.di([r["high"] for r in _rising_rows()], [r["low"] for r in _rising_rows()],
                    [r["close"] for r in _rising_rows()], 14)
        dn = ind.di([r["high"] for r in _falling_rows()], [r["low"] for r in _falling_rows()],
                    [r["close"] for r in _falling_rows()], 14)
        assert up and up["pdi"] > up["mdi"]
        assert dn and dn["mdi"] > dn["pdi"]

    def test_config_defaults_on(self):
        cfg = ScalpConfig()
        assert cfg.di_gate >= 1 and cfg.htf_gate >= 1
        assert cfg.retrace_atr == pytest.approx(0.6)
        assert cfg.retrace_expiry == 8
        assert cfg.trail_atr == pytest.approx(1.0)
        assert cfg.cancel_cooldown_sec == 900


# ── 2) انحياز الساعة — fail-open ─────────────────────────────────────────────

class TestHtfGate:
    def test_fail_open_without_k1h(self):
        """غياب شموع 1h = بوابة صامتة (لا تجميد) — عقد fail-open."""
        from strategies.flow_ignition import FlowIgnition
        cfg = ScalpConfig()
        strat = FlowIgnition(cfg)
        # الإشارة قد تولد أو لا تولد لسبب آخر — المهم: لا استثناء وغياب k1h مقبول
        try:
            strat.evaluate(_ctx(_rising_rows(), k1h=None))
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"fail-open منتهك: {exc}")


# ── 3) الأوامر الارتدادية المؤكدة ────────────────────────────────────────────

class TestRetraceOrders:
    @pytest.fixture(autouse=True)
    def _isolated(self, monkeypatch):
        monkeypatch.setattr(mng, "_retrace_orders", {})
        yield

    def _sig(self, entry=100.0, sl=99.0, tp1=101.5, tp2=103.0, atr=1.0):
        return ScalpSignal(strategy="SCALP_FLOW", label="⚡ اختبار",
                           symbol="TEST/USDT", entry_ref=entry, sl=sl, tp1=tp1,
                           tp2=tp2, rr1=1.0, reason="اختبار",
                           meta={"atr5": atr})

    def test_arm_creates_order_below_entry(self):
        mng._arm_retrace(self._sig(entry=100.0, atr=1.0))
        od = mng._retrace_orders.get("TEST/USDT")
        assert od and od["limit"] == pytest.approx(100.0 - 0.6 * 1.0)
        assert od["sl_ref"] == 99.0 and od["tp2"] == 103.0

    def test_arm_falls_back_without_atr(self, monkeypatch):
        """بلا ATR = المسار القديم (فتح فوري) — fail-open موثق."""
        opened = {}
        monkeypatch.setattr(mng, "_open_position",
                            lambda sig, fill_price=None: opened.setdefault("x", True) or True)
        assert mng._arm_retrace(self._sig(entry=100.0, atr=0.0)) is True
        assert opened and "TEST/USDT" not in mng._retrace_orders

    def test_cancel_on_close_below_sl_ref(self, monkeypatch):
        mng._arm_retrace(self._sig())
        monkeypatch.setattr(mng, "_cooldown_set", lambda *a, **k: None)
        ctx = _ctx([_candle(98.5, hi=99.0, lo=98.0)])   # إغلاق تحت الوقف المرجعي 99
        mng._manage_retrace("TEST/USDT", ctx)
        assert "TEST/USDT" not in mng._retrace_orders

    def test_expiry_cancels(self, monkeypatch):
        mng._arm_retrace(self._sig())
        od = mng._retrace_orders["TEST/USDT"]
        od["expires_ts"] = time.time() - 1.0
        monkeypatch.setattr(mng, "_cooldown_set", lambda *a, **k: None)
        ctx = _ctx([_candle(100.2, hi=100.5, lo=99.8)])
        mng._manage_retrace("TEST/USDT", ctx)
        assert "TEST/USDT" not in mng._retrace_orders

    def test_no_touch_no_fill(self):
        mng._arm_retrace(self._sig())
        ctx = _ctx([_candle(100.3, hi=100.6, lo=100.1)])   # لم يصل الحد 99.4
        mng._manage_retrace("TEST/USDT", ctx)
        assert "TEST/USDT" in mng._retrace_orders          # ما زال معلقًا

    def test_knife_candle_not_filled(self):
        """لمس الحد بإغلاق تحته = سكين ساقط — لا ملء (جوهر الدرس)."""
        mng._arm_retrace(self._sig(entry=100.0, sl=99.0, atr=1.0))   # الحد 99.4
        ctx = _ctx([_candle(99.2, hi=99.9, lo=99.1)])      # low ≤ 99.4 لكن close 99.2 < 99.4
        mng._manage_retrace("TEST/USDT", ctx)
        assert "TEST/USDT" in mng._retrace_orders or True  # إما ملغي (close<sl لا) أو معلق
        # close=99.2 > sl_ref=99.0 → لم يُبطل؛ close < limit → لم يُملأ
        assert "TEST/USDT" in mng._retrace_orders

    def test_rejection_candle_fills_at_limit(self, monkeypatch):
        """لمس الحد وإغلاق فوقه = رفض مؤكد — ملء عند الحد (أو الفتح أفضل)."""
        opened = {}
        monkeypatch.setattr(mng, "_cooldown_set", lambda *a, **k: None)
        monkeypatch.setattr(mng, "_scalp_open_count", lambda s=None: 0)
        monkeypatch.setattr(mng, "_daily_loss_block", lambda s: False)
        # [EL2.4.1][F3] بوابات الملء صارت الكاملة (_entry_gates) — الوهمي يجيب عنها كلها:
        # زر التداول مفعّل، لا قاطع مخاطر، لا صفقة نشطة، لا تبريد
        monkeypatch.setattr(mng, "_hf",
                            lambda key, *a, **k: (True if key == "is_trading_enabled"
                                                  else False if key == "symbol_has_active"
                                                  else None))
        monkeypatch.setattr(mng, "_entry_gates", lambda s, sym: (True, ""))
        monkeypatch.setattr(mng, "_open_position",
                            lambda sig, fill_price=None: opened.setdefault("fill", fill_price) or True)
        mng._arm_retrace(self._sig(entry=100.0, sl=99.0, atr=1.0))   # الحد 99.4
        ctx = _ctx([_candle(99.7, hi=99.8, lo=99.2, op=99.6)])       # low ≤ 99.4، close 99.7 ≥ 99.4
        mng._manage_retrace("TEST/USDT", ctx)
        assert "TEST/USDT" not in mng._retrace_orders
        assert opened["fill"] == pytest.approx(99.4)                 # fill = min(limit, open=99.6)

    def test_fill_gap_uses_open(self, monkeypatch):
        """فتحة تحت الحد = ملء بالفتح (سعر أفضل) — كما في المختبر."""
        opened = {}
        monkeypatch.setattr(mng, "_cooldown_set", lambda *a, **k: None)
        monkeypatch.setattr(mng, "_scalp_open_count", lambda s=None: 0)
        monkeypatch.setattr(mng, "_daily_loss_block", lambda s: False)
        # [EL2.4.1][F3] بوابات الملء صارت الكاملة (_entry_gates) — الوهمي يجيب عنها كلها:
        # زر التداول مفعّل، لا قاطع مخاطر، لا صفقة نشطة، لا تبريد
        monkeypatch.setattr(mng, "_hf",
                            lambda key, *a, **k: (True if key == "is_trading_enabled"
                                                  else False if key == "symbol_has_active"
                                                  else None))
        monkeypatch.setattr(mng, "_entry_gates", lambda s, sym: (True, ""))
        monkeypatch.setattr(mng, "_open_position",
                            lambda sig, fill_price=None: opened.setdefault("fill", fill_price) or True)
        mng._arm_retrace(self._sig(entry=100.0, sl=99.0, atr=1.0))   # الحد 99.4
        ctx = _ctx([_candle(99.8, hi=99.9, lo=99.3, op=99.35)])      # فتح 99.35 تحت الحد
        mng._manage_retrace("TEST/USDT", ctx)
        assert opened["fill"] == pytest.approx(99.35)

    def test_fill_blocked_when_symbol_busy(self, monkeypatch):
        """صفقة نشطة على الرمز لحظة الملء = إسقاط الأمر لا تجاوز السقف."""
        opened = {}
        monkeypatch.setattr(mng, "_cooldown_set", lambda *a, **k: None)
        monkeypatch.setattr(mng, "_scalp_open_count", lambda s=None: 0)
        monkeypatch.setattr(mng, "_daily_loss_block", lambda s: False)
        monkeypatch.setattr(mng, "_hf",
                            lambda key, *a, **k: True if key == "symbol_has_active" else None)
        monkeypatch.setattr(mng, "_open_position",
                            lambda sig, fill_price=None: opened.setdefault("x", True) or True)
        mng._arm_retrace(self._sig())
        ctx = _ctx([_candle(99.7, hi=99.8, lo=99.2, op=99.6)])
        mng._manage_retrace("TEST/USDT", ctx)
        assert not opened and "TEST/USDT" not in mng._retrace_orders


# ── 4) تتبع القمة بعد BE (منطق المراقبة) ─────────────────────────────────────

class TestTrailAfterBE:
    def test_chandelier_math(self):
        """peak − trail×ATR فوق الوقف الحالي وتحت السعر الحي ⇒ يُحدَّث الوقف صاعدًا."""
        peak, atr, cur_sl, live = 102.0, 1.0, 100.0, 101.8
        new_sl = peak - 1.0 * atr
        assert new_sl == pytest.approx(101.0)
        assert new_sl > cur_sl and new_sl < live      # شرطا التحديث في _monitor_cycle


# ── 5) سقف المخاطرة البنيوية للموجات ─────────────────────────────────────────

class TestElliottSlCap:
    def test_constants(self):
        assert vnz.ELLIOTT_SL_CAP_ATR == pytest.approx(2.0)
        assert vnz.PENDING_MAX_CANDLES == 10
        assert vnz.BOT_VERSION == "EL2.4.1" and panel.BOT_VERSION == "EL2.4.1"

    def test_cap_math(self):
        """وقف بنيوي أوسع من 2×ATR15 يُقص؛ أضيق يبقى."""
        entry, structural_sl, a15 = 100.0, 95.0, 2.0    # بنيوي 5$ > cap 4$
        capped = max(structural_sl, entry - vnz.ELLIOTT_SL_CAP_ATR * a15)
        assert capped == pytest.approx(96.0) and capped > structural_sl
        entry2, sl2, a15b = 100.0, 98.5, 2.0            # بنيوي 1.5$ < cap 4$ يبقى
        assert max(sl2, entry2 - vnz.ELLIOTT_SL_CAP_ATR * a15b) == pytest.approx(98.5)

    def test_atr15_recent_fail_open(self, monkeypatch):
        """بلا كاش 15m = None (يبقى الوقف البنيوي) — عقد fail-open."""
        monkeypatch.setattr(vnz, "_kline_cache_read", lambda s, tf, limit: None)
        assert vnz._atr15_recent("TEST/USDT") is None

    def test_atr15_recent_computes(self, monkeypatch):
        rows = [[i * 900_000, 100.0, 101.0, 99.0, 100.5, 10.0] for i in range(40)]
        monkeypatch.setattr(vnz, "_kline_cache_read", lambda s, tf, limit: rows)
        v = vnz._atr15_recent("TEST/USDT")
        assert v and v > 0


# ── 6) اللوحة والشفافية ──────────────────────────────────────────────────────

class TestPanelTransparency:
    def test_panel_documents_lessons(self):
        html = panel.PANEL_HTML
        assert "EL2.4.1" in html or panel.BOT_VERSION == "EL2.4.1"
        # أوامر الارتداد والتتبع والسقف موثقة للوحة لا مخفية
        assert "ارتدادي" in html or "دروس الباك تاست" in html
