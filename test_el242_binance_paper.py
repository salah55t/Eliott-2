# -*- coding: utf-8 -*-
"""[EL2.4.2] اختبارات محاكاة قواعد باينانس للورقي — الكمية والبواقي بعد البيع.

المحاور:
  1) _paper_rules: سقوط آمن (fail-open) على الثوابت عند غياب/فشل القواعد.
  2) _paper_sell_split: أرضية LOT_SIZE + حدود minQty/minNotional — (sellable, residual).
  3) close_signal_row: بيع ورقي بقواعد باينانس + البقايا تُقيَّم بسعر الخروج بلا رسوم
     بيع — وتعادل الصيغة القديمة حرفيًا عند بلا قواعد (regression guard) — والحقيقي لم يُمس.
  4) _account_partial_close: رجل ورقية تلتزم القواعد — غبار يُتجاهل والأرضية تُطبق —
     والحقيقية بلا أرضية (البيع تم على المنصة).
  5) compute_quantity: minNotional/minQty لكل رمز بدل الثابت العام.
  6) _paper_floor_qty + جسر السكالب paper_floor_qty.
  7) _reset_paper_100: لمرة واحدة — إلغاء المعلق الورقي وتسوية المفتوح بلا ربح/خسارة،
     الحقيقي لا يُمس، والعلم يجعلها idempotent.
  8) PAPER_BALANCE=100 في render.yaml + الإصدار EL2.4.2.
صفر شبكة: real_market_rules مُعترَضة في كل اختبار.
"""

import json

import pytest

import vnz


# ─────────────────────────────────────────────────────────────────────────────
# أدوات مشتركة
# ─────────────────────────────────────────────────────────────────────────────

def insert_sig(status="open", is_real=0, fill=100.0, sl=95.0, tp=120.0, qty=10.0,
               entry=106.0, symbol="TEST/USDT", strategy="Elliott_Fibonacci"):
    vnz.db.execute(
        "INSERT INTO signals (symbol, direction, strategy_name, status, entry_price, stop_loss,"
        " take_profit, quantity, notional_usdt, fill_price, created_at, is_real, meta_json, pivots_json)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (symbol, "BULLISH", strategy, status, entry, sl, tp, qty, qty * fill, fill,
         vnz.utc_now_iso(), is_real, "{}", '{"P0": 90.0}'),
    )
    return vnz.db.query("SELECT * FROM signals ORDER BY id DESC LIMIT 1", one=True)


@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    """قاعدة SQLite مؤقتة لكل اختبار — نفس عقد test_fe180."""
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


@pytest.fixture()
def rules(monkeypatch):
    """معترض قواعد باينانس — قاموس قابل للتعديل لكل اختبار (صفر شبكة)."""
    holder = {"rules": {"tick": 0.01, "step": 0.01, "min_qty": 0.001, "min_cost": 10.0, "status": "TRADING"}}
    vnz._REAL_RULES_CACHE.clear()
    monkeypatch.setattr(vnz, "real_market_rules", lambda symbol, ex=None, force=False: dict(holder["rules"]))
    return holder


# ─────────────────────────────────────────────────────────────────────────────
# 1) _paper_rules — السقوط الآمن
# ─────────────────────────────────────────────────────────────────────────────

class TestPaperRules:
    def test_empty_rules_fall_back_to_constants(self, monkeypatch):
        vnz._REAL_RULES_CACHE.clear()
        monkeypatch.setattr(vnz, "real_market_rules", lambda symbol, ex=None, force=False: {})
        r = vnz._paper_rules("X/USDT")
        assert r["step"] == 0.0 and r["min_qty"] == 0.0
        assert r["min_cost"] == vnz.MIN_NOTIONAL_USDT

    def test_exception_falls_back_to_constants(self, monkeypatch):
        vnz._REAL_RULES_CACHE.clear()
        def _boom(symbol, ex=None, force=False):
            raise RuntimeError("شبكة")
        monkeypatch.setattr(vnz, "real_market_rules", _boom)
        r = vnz._paper_rules("X/USDT")
        assert r["min_cost"] == vnz.MIN_NOTIONAL_USDT and r["step"] == 0.0

    def test_real_rules_pass_through(self, rules):
        r = vnz._paper_rules("X/USDT")
        assert r["step"] == 0.01 and r["min_qty"] == 0.001 and r["min_cost"] == 10.0

    def test_zero_min_cost_becomes_constant(self, rules):
        rules["rules"]["min_cost"] = 0.0
        assert vnz._paper_rules("X/USDT")["min_cost"] == vnz.MIN_NOTIONAL_USDT


# ─────────────────────────────────────────────────────────────────────────────
# 2) _paper_sell_split — الكمية القابلة للبيع والبقايا
# ─────────────────────────────────────────────────────────────────────────────

class TestSellSplit:
    def test_step_floor_with_residual(self, rules):
        sellable, residual = vnz._paper_sell_split("X/USDT", 7.123456, 100.0)
        assert abs(sellable - 7.12) < 1e-12
        assert abs(residual - 0.003456) < 1e-12

    def test_full_dust_below_min_notional(self, rules):
        sellable, residual = vnz._paper_sell_split("X/USDT", 0.05, 100.0)  # 5$ < 10$
        assert sellable == 0.0 and residual == 0.05

    def test_below_min_qty_is_dust(self, rules):
        rules["rules"]["min_qty"] = 1.0
        sellable, residual = vnz._paper_sell_split("X/USDT", 0.5, 100.0)
        assert sellable == 0.0 and residual == 0.5

    def test_exact_min_notional_is_sellable(self, rules):
        sellable, residual = vnz._paper_sell_split("X/USDT", 0.1, 100.0)  # 10$ = الحد
        assert abs(sellable - 0.1) < 1e-12 and residual == 0.0

    def test_no_rules_no_floor(self, monkeypatch):
        vnz._REAL_RULES_CACHE.clear()
        monkeypatch.setattr(vnz, "real_market_rules", lambda symbol, ex=None, force=False: {})
        sellable, residual = vnz._paper_sell_split("X/USDT", 7.123456, 100.0)
        assert sellable == 7.123456 and residual == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 3) close_signal_row — البيع الورقي بقواعد باينانس
# ─────────────────────────────────────────────────────────────────────────────

class TestCloseWithBinanceRules:
    def test_residual_valued_at_exit_without_sell_fee(self, clean_db, rules):
        sig = insert_sig(fill=100.0, qty=7.123456)
        before = vnz.get_paper_balance()
        n0 = vnz.scan_stats["paper_dust_n"]
        vnz.close_signal_row(sig, 110.0, "هدف")
        expected = (7.12 * 110.0 * 0.999) + (0.003456 * 110.0) - (7.123456 * 100.0 * 1.001)
        row = vnz.db.query("SELECT * FROM signals ORDER BY id DESC LIMIT 1", one=True)
        assert abs(row["pnl_usdt"] - expected) < 1e-6
        assert abs(vnz.get_paper_balance() - (before + expected)) < 1e-6
        assert vnz.scan_stats["paper_dust_n"] == n0 + 1
        assert row["close_reason"] == "هدف"

    def test_full_dust_no_sell_fee(self, clean_db, rules):
        sig = insert_sig(fill=100.0, qty=0.05)   # 5$ < 10$ — لا بيع ممكن
        before = vnz.get_paper_balance()
        vnz.close_signal_row(sig, 110.0, "غبار")
        expected = 0.05 * 110.0 - 0.05 * 100.0 * 1.001
        row = vnz.db.query("SELECT * FROM signals ORDER BY id DESC LIMIT 1", one=True)
        assert abs(row["pnl_usdt"] - expected) < 1e-6
        assert abs(vnz.get_paper_balance() - (before + expected)) < 1e-6
        assert vnz.scan_stats["paper_dust_usdt"] > 0

    def test_no_rules_matches_legacy_formula(self, clean_db, monkeypatch):
        # regression guard: بلا قواعد = الصيغة القديمة حرفيًا (رسوم الاتجاهين كاملًا)
        vnz._REAL_RULES_CACHE.clear()
        monkeypatch.setattr(vnz, "real_market_rules", lambda symbol, ex=None, force=False: {})
        sig = insert_sig(fill=100.0, qty=10.0)
        before = vnz.get_paper_balance()
        vnz.close_signal_row(sig, 95.0, "وقف")
        legacy = 10.0 * (95.0 - 100.0) - (10.0 * 100.0 + 10.0 * 95.0) * vnz.FEE_RATE
        row = vnz.db.query("SELECT * FROM signals ORDER BY id DESC LIMIT 1", one=True)
        assert abs(row["pnl_usdt"] - legacy) < 1e-9
        assert abs(vnz.get_paper_balance() - (before + legacy)) < 1e-9

    def test_already_stepped_qty_has_no_residual(self, clean_db, rules):
        # كمية على الخطوة أصلًا = صفر بقايا = الصيغة القديمة حرفيًا حتى مع قواعد
        sig = insert_sig(fill=100.0, qty=7.12)
        before = vnz.get_paper_balance()
        vnz.close_signal_row(sig, 110.0, "هدف")
        legacy = 7.12 * (110.0 - 100.0) - (7.12 * 100.0 + 7.12 * 110.0) * vnz.FEE_RATE
        row = vnz.db.query("SELECT * FROM signals ORDER BY id DESC LIMIT 1", one=True)
        assert abs(row["pnl_usdt"] - legacy) < 1e-9
        assert abs(vnz.get_paper_balance() - (before + legacy)) < 1e-9

    def test_real_row_untouched_by_dust_logic(self, clean_db, rules):
        sig = insert_sig(fill=100.0, qty=7.123456, is_real=1)
        vnz.close_signal_row(sig, 110.0, "هدف")
        legacy = 7.123456 * (110.0 - 100.0) - (7.123456 * 100.0 + 7.123456 * 110.0) * vnz.FEE_RATE
        row = vnz.db.query("SELECT * FROM signals ORDER BY id DESC LIMIT 1", one=True)
        assert abs(row["pnl_usdt"] - legacy) < 1e-5   # الحقيقي محاسبة خالصة — بلا أرضية (تخزين مقرّب 6 منازل)


# ─────────────────────────────────────────────────────────────────────────────
# 4) _account_partial_close — الرجل الورقية تلتزم القواعد
# ─────────────────────────────────────────────────────────────────────────────

class TestPartialLegRules:
    def test_dust_leg_skipped(self, clean_db, rules):
        sig = insert_sig(fill=100.0, qty=10.0)
        before = vnz.get_paper_balance()
        got = vnz._account_partial_close(sig, 0.05, 120.0, "غبار")  # 6$ < 10$
        assert got == 0.0
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        assert abs(row["quantity"] - 10.0) < 1e-12
        assert abs(vnz.get_paper_balance() - before) < 1e-12

    def test_leg_floored_to_step(self, clean_db, rules):
        sig = insert_sig(fill=100.0, qty=10.0)
        before = vnz.get_paper_balance()
        got = vnz._account_partial_close(sig, 7.123456, 120.0, "هدف")
        expected_leg = 7.12 * (120.0 - 100.0) - (7.12 * 100.0 + 7.12 * 120.0) * vnz.FEE_RATE
        assert abs(got - expected_leg) < 1e-9
        row = vnz.db.query("SELECT * FROM signals WHERE id=%s", (sig["id"],), one=True)
        assert abs(row["quantity"] - 2.88) < 1e-9          # المتبقي يشمل البقايا
        assert abs(vnz.get_paper_balance() - (before + expected_leg)) < 1e-9

    def test_real_leg_no_floor(self, clean_db, rules):
        sig = insert_sig(fill=100.0, qty=10.0, is_real=1)
        got = vnz._account_partial_close(sig, 7.123456, 120.0, "هدف")
        expected_leg = 7.123456 * (120.0 - 100.0) - (7.123456 * 100.0 + 7.123456 * 120.0) * vnz.FEE_RATE
        assert abs(got - expected_leg) < 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# 5) compute_quantity — حدود باينانس لكل رمز
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeQuantityRules:
    def test_min_qty_rejection(self, clean_db, rules, monkeypatch):
        monkeypatch.setattr(vnz, "PAPER_MAX_POSITION_PCT", 0.0)
        monkeypatch.setattr(vnz, "PAPER_MAX_TOTAL_PCT", 0.0)
        rules["rules"]["min_qty"] = 1000.0
        before = vnz.scan_stats["rejected_binance_rules"]
        assert vnz.compute_quantity("X/USDT", 100.0, 99.0) is None
        assert vnz.scan_stats["rejected_binance_rules"] == before + 1

    def test_per_symbol_min_cost_five(self, clean_db, rules, monkeypatch):
        # رمز حدّه 5$ (لا 10$): رفع لأدنى قيمة يعمل حيث كان الثابت القديم يرفض
        monkeypatch.setattr(vnz, "PAPER_MAX_POSITION_PCT", 0.0)
        monkeypatch.setattr(vnz, "PAPER_MAX_TOTAL_PCT", 0.0)
        rules["rules"]["min_cost"] = 5.0
        vnz.set_paper_balance(100.0)
        qty = vnz.compute_quantity("X/USDT", 100.0, 50.0)   # مخاطرة 1$ — مسافة 50
        assert qty is not None
        assert abs(qty * 100.0 - 5.0) < 1e-9                # رُفعت لأدنى قيمة الرمز

    def test_constant_min_cost_rejects_wide_stop(self, clean_db, rules):
        rules["rules"]["min_cost"] = 10.0
        vnz.set_paper_balance(100.0)
        # مسافة وقف 60$: أدنى حجم 0.1 يحتاج 6$ مخاطرة > 3× المخاطرة المخططة (3$)
        assert vnz.compute_quantity("X/USDT", 100.0, 40.0) is None


# ─────────────────────────────────────────────────────────────────────────────
# 6) _paper_floor_qty + جسر السكالب
# ─────────────────────────────────────────────────────────────────────────────

class TestPaperFloorQty:
    def test_floor(self, rules):
        assert abs(vnz._paper_floor_qty("X/USDT", 1.23456) - 1.23) < 1e-12

    def test_below_min_qty_zero(self, rules):
        assert vnz._paper_floor_qty("X/USDT", 0.0005) == 0.0

    def test_no_rules_passthrough(self, monkeypatch):
        vnz._REAL_RULES_CACHE.clear()
        monkeypatch.setattr(vnz, "real_market_rules", lambda symbol, ex=None, force=False: {})
        assert vnz._paper_floor_qty("X/USDT", 1.23456) == 1.23456

    def test_scalp_host_exposes_paper_floor_qty(self, rules):
        host = vnz.scalp_host()
        assert callable(host.get("paper_floor_qty"))
        assert abs(host["paper_floor_qty"]("X/USDT", 1.23456) - 1.23) < 1e-12


# ─────────────────────────────────────────────────────────────────────────────
# 7) _reset_paper_100 — إعادة الضبط لمرة واحدة
# ─────────────────────────────────────────────────────────────────────────────

class TestResetPaper100:
    def test_reset_once(self, clean_db, rules):
        insert_sig(status="pending", fill=100.0, qty=5.0)
        insert_sig(status="open", fill=100.0, qty=5.0)
        insert_sig(status="open", fill=100.0, qty=5.0, is_real=1)
        vnz.set_paper_balance(9917.91)
        vnz._reset_paper_100()
        assert abs(vnz.get_paper_balance() - vnz.PAPER_BALANCE_START) < 1e-9
        pend = vnz.db.query("SELECT * FROM signals WHERE status='pending' AND is_real=0")
        assert len(pend) == 0
        open_paper = vnz.db.query("SELECT * FROM signals WHERE status='open' AND is_real=0")
        assert len(open_paper) == 0
        open_real = vnz.db.query("SELECT * FROM signals WHERE status='open' AND is_real=1")
        assert len(open_real) == 1                     # الحقيقي لم يُمس
        flat = vnz.db.query("SELECT * FROM signals WHERE close_reason LIKE 'إعادة ضبط%'")
        assert len(flat) == 2
        for r in flat:
            assert float(r["pnl_usdt"] or 0) == 0.0    # تسوية بلا ربح/خسارة — لا تغذية للقاطع
        assert vnz.db_get_state(vnz.PAPER_RESET_100_KEY) == repr(vnz.PAPER_BALANCE_START)

    def test_target_change_retriggers_reset(self, clean_db, rules, monkeypatch):
        # إقلاع بهدف مختلف (تغيّر PAPER_BALANCE على المنصة بعد إقلاع سابق) → يعيد الضبط
        vnz._reset_paper_100()
        insert_sig(status="pending", fill=100.0, qty=5.0)
        monkeypatch.setattr(vnz, "PAPER_BALANCE_START", 100.0)   # الهدف الجديد (كان الافتراضي 10000 في بيئة الاختبار)
        vnz._reset_paper_100()
        assert len(vnz.db.query("SELECT * FROM signals WHERE status='pending'")) == 0
        assert abs(vnz.get_paper_balance() - 100.0) < 1e-9
        assert vnz.db_get_state(vnz.PAPER_RESET_100_KEY) == "100.0"

    def test_reset_idempotent(self, clean_db, rules):
        vnz._reset_paper_100()
        insert_sig(status="pending", fill=100.0, qty=5.0)
        vnz._reset_paper_100()
        pend = vnz.db.query("SELECT * FROM signals WHERE status='pending'")
        assert len(pend) == 1                          # العلم يمنع إعادة الضبط

    def test_real_pending_untouched(self, clean_db, rules):
        insert_sig(status="pending", fill=100.0, qty=5.0, is_real=1)
        vnz._reset_paper_100()
        pend = vnz.db.query("SELECT * FROM signals WHERE status='pending' AND is_real=1")
        assert len(pend) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 8) الإعدادات والإصدار
# ─────────────────────────────────────────────────────────────────────────────

def test_render_yaml_paper_balance_100():
    raw = open("render.yaml", encoding="utf-8").read()
    assert "- key: PAPER_BALANCE" in raw
    seg = raw.split("- key: PAPER_BALANCE", 1)[1]
    val = seg.strip().splitlines()[0]
    assert 'value: "100"' in val, f"PAPER_BALANCE يجب أن يكون 100 — وجدنا: {val}"


def test_version_el242():
    import panel
    assert vnz.BOT_VERSION == "EL2.4.2"
    assert panel.BOT_VERSION == "EL2.4.2"
