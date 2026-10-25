#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات انحدار EL2.4.1 — إصلاحات F1..F10 حرفيًا وفق البرمبت المعتمد
=======================================================================
كل اختبار يُكتب قبل إصلاحه (يفشل على EL2.4.0) ثم يُجعل ينجح — وبأقل أثر على
السلوك القائم: القيم الافتراضية محفوظة وكل مساعد جديد fail-open مع الاختبارات
القديمة (شموع بلا عمود timestamp = السلوك التراثي حرفيًا).
"""

import json
import math

import pandas as pd
import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة (نمط test_el2_integration)


@pytest.fixture()
def clean_db(monkeypatch):
    """قاعدة SQLite مؤقتة لكل اختبار — عزل كامل (نمط المستودع نفسه)."""
    monkeypatch.setattr(vnz, "USE_POSTGRES", False)
    import sqlite3
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    old = vnz.db.conn
    vnz.db.conn = conn
    vnz.init_db()
    yield
    vnz.db.conn = old


@pytest.fixture()
def tg_off(monkeypatch):
    monkeypatch.setattr(vnz, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(vnz, "TELEGRAM_CHAT_ID", "")
    monkeypatch.setattr(vnz, "_tg_dedup", {})
    yield


def _insert_pending(sym="TEST/USDT", entry=118.0, stop=114.0, tp=135.0,
                    qty=10.0, p0=90.0, created="2026-10-24T10:00:00Z"):
    """صفقة محرك معلقة حرفية بالقيم المذكورة في البرمبت (F1)."""
    vnz.db.execute(
        "INSERT INTO signals (symbol, direction, strategy_name, status, entry_price,"
        " stop_loss, take_profit, quantity, pivots_json, created_at, expires_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (sym, "BULLISH", "Elliott_Fibonacci", "pending", entry, stop, tp, qty,
         json.dumps({"P0": p0, "P1": 100.0, "P2": 110.0, "P3": 120.0,
                     "P4": 112.0, "P5": 130.0}),
         created, "2099-01-01T00:00:00Z"))
    return vnz.db.query("SELECT * FROM signals WHERE symbol=%s", (sym,), one=True)


def _candle(open_, high, low, close):
    return pd.DataFrame([{"ts": 0, "open": open_, "high": high, "low": low,
                          "close": close, "volume": 1.0}])


# ─────────────────────────────────────────────────────────────────────────────
# F1 — الملء الورقي المتفائل والربح الوهمي (P0)
# ─────────────────────────────────────────────────────────────────────────────

class TestF1HonestFill:
    def test_fill_close_below_stop_no_phantom_profit(self, clean_db, tg_off, monkeypatch):
        """شمعة تلمس الدخول وتغلق تحت الوقف: الملء بسعر الأمر (لا بسعر الإغلاق)
        والصفقة تُغلق بالوقف في نفس الدورة — pnl سالب لا ربح وهمي."""
        _insert_pending()
        monkeypatch.setattr(vnz, "fetch_ohlcv_df",
                            lambda *a, **k: _candle(120, 121, 105, 110))
        vnz.monitor_step()
        row = vnz.db.query("SELECT * FROM signals", one=True)
        assert row["status"] == "closed"
        assert math.isclose(float(row["fill_price"]), 118.0, rel_tol=1e-9)
        assert math.isclose(float(row["close_price"]), 114.0, rel_tol=1e-9)
        assert float(row["pnl_usdt"]) < 0

    def test_gap_open_below_stop_closes_at_fill(self, clean_db, tg_off, monkeypatch):
        """فتح شمعة تحت الوقف: الملء بالفتح (أدنى من الدخول) وإغلاق فوري بسعر
        الملء — خسارة رسوم حصرًا لا صفقة وقف بربح."""
        _insert_pending()
        monkeypatch.setattr(vnz, "fetch_ohlcv_df",
                            lambda *a, **k: _candle(110, 121, 105, 112))
        vnz.monitor_step()
        row = vnz.db.query("SELECT * FROM signals", one=True)
        assert row["status"] == "closed"
        assert math.isclose(float(row["fill_price"]), 110.0, rel_tol=1e-9)
        assert math.isclose(float(row["close_price"]), 110.0, rel_tol=1e-9)
        assert float(row["pnl_usdt"]) < 0  # رسوم فقط

    def test_normal_touch_fills_at_limit(self, clean_db, tg_off, monkeypatch):
        """الملء الطبيعي لم يتغير: لمس الدخول مع إغلاق فوقه = ملء بسعر الأمر."""
        _insert_pending()
        monkeypatch.setattr(vnz, "fetch_ohlcv_df",
                            lambda *a, **k: _candle(120, 121, 115, 118))
        vnz.monitor_step()
        row = vnz.db.query("SELECT * FROM signals", one=True)
        assert row["status"] == "open"
        assert math.isclose(float(row["fill_price"]), 118.0, rel_tol=1e-9)
