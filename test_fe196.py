#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات FE1.9.6 «لا اختفاء صامت»
====================================
البلاغ الحي الذي ولّد هذا الإصدار (15 أكتوبر 2026، 18:44 UTC):
«السعر في باينانس للعملة قيد الانتظار وصل سعر الدخول وسعرها في اللوحة لم يتغير»
— التحقيق أثبت عكس البلاغ:
  • اللوحة حية: لقطتان متتاليتان (12ث) 0.004567 → 0.004565 طابقتا باينانس
    حرفيًا (0.00456500) — enrich_live_signal يجلب السعر الحي عند كل طلب.
  • المنطقة لم تُلمس على أي من المنصتين: أدنى قاع دقيقة على باينانس 0.0045230
    (18:21 UTC) فوق قمة منطقة الدخول 0.00452019 بـ0.06% — غير مرئي بالعين على
    الشارت، ومن هنا جاء الالتباس.
لكن التحقيق كشف فجوة عرض حقيقية: إشارة PUMP المعلقة انتهت صلاحيتها 18:55:24
فانتقلت status='expired' في قاعدة البيانات واخفت من اللوحة كليًا (المغلق كان
يعرض 'closed' وحده = صفقات تداولت وغلقت بنتيجة) — اختفاء صامت يربك المراقب.

ما يُغطيه الملف:
  1) الإشارة المنتهية (expired) تظهر في closed_signals بحالتها محفوظة
  2) الإشارة الملغاة بنيويًا (cancelled) تظهر كذلك
  3) المغلق الحقيقي (closed) يعمل كالسابق (انحدار صفر)
  4) انتهاء الصلاحية يطلق إشعارًا (⏰) — دورة الحياة مرئية
  5) الإبطال البنيوي يطلق إشعارًا (🛑)
  6) لوحة العرض تحمل شارات المنتهية/الملغاة (p-exp/p-cxl)
  7) تزامن الإصدار FE1.9.6 (vnz + panel)

صفر تغيير سلوك تداولي: شروط الملء/الإبطال/الصلاحية كما هي حرفيًا.
"""

import json

import pandas as pd
import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة
import panel


# ─────────────────────────────────────────────────────────────────────────────
# أدوات مساعدة
# ─────────────────────────────────────────────────────────────────────────────

def leg_candles(start: float, end: float, n: int, t0: int) -> list:
    rows = []
    step = (end - start) / n
    for i in range(n):
        o = start + step * i
        c = start + step * (i + 1)
        h = max(o, c) * 1.0005
        lo = min(o, c) * 0.9995
        rows.append((t0 + i * 3600_000, o, h, lo, c, 1000.0))
    return rows


def impulse_df() -> pd.DataFrame:
    """دافع صاعد مصطنع: P0=100 P1=120 P2=110 P3=140 P4=125 P5=135."""
    pts = [(100.0, 120.0, 5), (120.0, 110.0, 4), (110.0, 140.0, 6),
           (140.0, 125.0, 4), (125.0, 135.0, 4)]
    rows, t = [], 1_700_000_000_000
    for a, b, n in pts:
        rows += leg_candles(a, b, n, t)
        t += n * 3600_000
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df["symbol"] = "TEST/USDT"
    df["timeframe"] = "1h"
    return df[["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]]


from engine.pattern_detector import DetectorConfig, PivotDetector

DET = PivotDetector(DetectorConfig(method="zigzag", deviation_threshold=0.01,
                                   price_source="close", min_wave_bars=2))


@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    """قاعدة SQLite مؤقتة لكل اختبار — عزل كامل."""
    monkeypatch.setattr(vnz, "USE_POSTGRES", False)
    import sqlite3
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    old = vnz.db.conn
    vnz.db.conn = conn
    vnz.init_db()
    yield
    vnz.db.conn = old


def _make_pending() -> int:
    """إنشاء أمر معلق حقيقي عبر مسار الإنتاج وإرجاع id."""
    s = [x for x in DET.scan(impulse_df()) if x.direction == "BULLISH"][-1]
    assert vnz.create_pending_signal("TEST/USDT", s)
    rows = vnz.db.query("SELECT id FROM signals WHERE status='pending'")
    assert rows, "الأمر المعلق لم يُخزن"
    return int(rows[0]["id"])


# ─────────────────────────────────────────────────────────────────────────────
# 1-3) الظهور في قسم المغلق بلا اختفاء صامت
# ─────────────────────────────────────────────────────────────────────────────

def test_expired_signal_visible_in_closed_section(clean_db, monkeypatch):
    """الإشارة المنتهية تظهر في closed_signals — بلاغ حي: كانت تخفت كليًا."""
    monkeypatch.setattr(vnz, "get_live_price", lambda sym: 130.0)
    sig_id = _make_pending()
    vnz.db.execute(
        "UPDATE signals SET status='expired', close_reason=%s, closed_at=%s WHERE id=%s",
        ("انتهت صلاحية الأمر المعلق (3 شموع) دون لمس منطقة الدخول",
         vnz.utc_now_iso(), sig_id))
    client = vnz.app.test_client()
    body = client.get("/api/all").get_json()
    assert len(body["open_signals"]) == 0
    closed = body["closed_signals"]
    assert len(closed) == 1, "الإشارة المنتهية اختفت — عودة الاختفاء الصامت!"
    row = closed[0]
    assert row["status"] == "expired"
    assert row["symbol"] == "TEST/USDT"
    assert row["close_reason"] and "انتهت صلاحية" in row["close_reason"]
    assert row["fill_price"] is None  # لم تُملأ — العرض يستخدم الدخول المرجعي


def test_cancelled_signal_visible_in_closed_section(clean_db, monkeypatch):
    """الإشارة الملغاة بنيويًا تظهر في closed_signals بحالتها."""
    monkeypatch.setattr(vnz, "get_live_price", lambda sym: 130.0)
    sig_id = _make_pending()
    vnz.db.execute(
        "UPDATE signals SET status='cancelled', close_reason=%s, closed_at=%s WHERE id=%s",
        ("إبطال بنيوي: إغلاق 95.00 خلف أصل الموجة 1 (P0=99.95)",
         vnz.utc_now_iso(), sig_id))
    client = vnz.app.test_client()
    body = client.get("/api/all").get_json()
    closed = body["closed_signals"]
    assert len(closed) == 1
    assert closed[0]["status"] == "cancelled"
    assert "إبطال بنيوي" in closed[0]["close_reason"]


def test_truly_closed_signal_still_visible(clean_db, monkeypatch):
    """انحدار: المغلق الحقيقي (صفقة تداولت وغلقت) يظهر كالسابق بنتيجته."""
    monkeypatch.setattr(vnz, "get_live_price", lambda sym: 130.0)
    sig_id = _make_pending()
    vnz.db.execute(
        "UPDATE signals SET status='closed', fill_price=100.0, close_price=110.0,"
        " pnl_usdt=9.8, pnl_pct=9.8, close_reason=%s, closed_at=%s WHERE id=%s",
        ("هدف", vnz.utc_now_iso(), sig_id))
    client = vnz.app.test_client()
    body = client.get("/api/all").get_json()
    closed = body["closed_signals"]
    assert len(closed) == 1 and closed[0]["status"] == "closed"
    assert closed[0]["pnl_usdt"] is not None
    assert closed[0]["close_price"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# 4-5) إشعارات دورة الحياة (انتهاء صلاحية / إبطال بنيوي)
# ─────────────────────────────────────────────────────────────────────────────

def _last_close_df(close: float, low: float) -> pd.DataFrame:
    """شمعة واحدة بقيم مراقبة محددة — لمحاكاةmonitor_step بلا شبكة."""
    df = pd.DataFrame([{
        "timestamp": pd.Timestamp.now(tz="UTC"),
        "open": close, "high": max(close, low) * 1.001,
        "low": low, "close": close, "volume": 1000.0,
    }])
    return df


def test_expiry_fires_notification(clean_db, monkeypatch):
    """انتهاء الصلاحية يطلق إشعار ⏰ في اللوحة — مثل الملء (دورة الحياة مرئية)."""
    sig_id = _make_pending()
    # صلاحية منتهية فعلًا
    vnz.db.execute("UPDATE signals SET expires_at='2020-01-01T00:00:00Z' WHERE id=%s", (sig_id,))
    monkeypatch.setattr(vnz, "get_recent_candles",
                        lambda *a, **k: _last_close_df(close=130.0, low=129.0))
    vnz.monitor_step()
    rows = vnz.db.query("SELECT status FROM signals WHERE id=%s", (sig_id,))
    assert rows[0]["status"] == "expired"
    notifs = vnz.db.query("SELECT message FROM notifications ORDER BY id DESC LIMIT 1")
    assert notifs, "لا إشعار انتهاء صلاحية"
    assert "انتهت صلاحية" in notifs[0]["message"]


def test_structural_invalidation_fires_notification(clean_db, monkeypatch):
    """الإبطال البنيوي يطلق إشعار 🛑 — إغلاق خلف P0 يبطل العدّ ويُرى."""
    sig_id = _make_pending()
    pivots = json.loads(vnz.db.query(
        "SELECT pivots_json FROM signals WHERE id=%s", (sig_id,))[0]["pivots_json"])
    below_p0 = pivots["P0"] * 0.95
    monkeypatch.setattr(vnz, "get_recent_candles",
                        lambda *a, **k: _last_close_df(close=below_p0, low=below_p0 * 0.99))
    vnz.monitor_step()
    rows = vnz.db.query("SELECT status FROM signals WHERE id=%s", (sig_id,))
    assert rows[0]["status"] == "cancelled"
    notifs = vnz.db.query("SELECT message FROM notifications ORDER BY id DESC LIMIT 1")
    assert notifs and "أُبطل الأمر المعلق بنيويًا" in notifs[0]["message"]


# ─────────────────────────────────────────────────────────────────────────────
# 6-7) شارات اللوحة + الإصدار
# ─────────────────────────────────────────────────────────────────────────────

def test_panel_has_status_pills():
    """اللوحة تحمل شارات المنتهية/الملغاة وعمود الحالة."""
    html = panel.PANEL_HTML
    assert "p-exp" in html and "p-cxl" in html
    assert "منتهية" in html and "ملغاة" in html
    assert "stPill" in html  # دالة الشارة الحالةية في renderClosed
    # الدخول المرجعي عند غياب fill_price (منتهية/ملغاة بلا ملء)
    assert "s.entry_price" in html


def test_version_pair():
    assert vnz.BOT_VERSION == "EL2.4.0"
    assert panel.BOT_VERSION == "EL2.4.0"
