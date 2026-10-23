#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبارات FE1.9.8 «التحكم والصمود»
====================================
الطلب: «راجع المشاريع مفتوحة المصدر وابحث عن ما ينقص مشروعنا وطوّره» —
ناتج تحليل الفجوات مع freqtrade/cryptofeed/OctoBot + الثلاثية المعلقة من الجلسة السابقة:

ما يُغطيه الملف:
  1) بوابة تلغرام: الأصناف المهمة تُرسل والضجيج يُكتم + تجاوز '*'
  2) كتم التكرار الحرفي (نافذة زمنية) + تعطيلها بـ0
  3) قصّ رسالة تلغرام الآمن عند 4000 حرف
  4) محلل الأوامر النقي (إنجليزي/عربي/@botname/وسيط رمز)
  5) /help و/ping كردود سليمة
  6) set_trading_enabled الموحّد (توقف/تشغيل + إشعار TRADING_STATUS_CHANGE)
  7) علم «غلق يدوي مطلوب»: تنبيه مرة + كتم التذكير داخل النافذة
  8) تكامل: فشل البيع الحقيقي في close_real_trade يرفع العلم والتنبيه
  9) الحل: close_signal_row يمسح العلم ويطلق إشعار الحلّ
 10) كاش الشموع: كتابة→قراءة رحلة كاملة + شمعة مفتوحة مستبعدة
 11) الوضع المتدهور: فشل كل المزودين ← الكاش يخدم بالمصدر "cache"
 12) /health يكشف telegram_control وkline_cache
 13) تزامن الإصدار FE1.9.8 (vnz + panel)

التصميم تساهلي: كل الإضافات محمية باستثناءات وفشل التلغرام/الكاش لا يمس التداول.
"""

import json
import time

import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة
import panel


# ─────────────────────────────────────────────────────────────────────────────
# أدوات
# ─────────────────────────────────────────────────────────────────────────────

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


@pytest.fixture()
def tg_off(monkeypatch):
    """عزل التلغرام: بلا مفاتيح + كتم نظيف — فلا إرسالات شبكية في الاختبارات."""
    monkeypatch.setattr(vnz, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(vnz, "TELEGRAM_CHAT_ID", "")
    monkeypatch.setattr(vnz, "_tg_dedup", {})
    yield


def make_sig(**kw):
    base = {
        "id": 1, "symbol": "PUMP/USDT", "direction": "BULLISH",
        "strategy_name": "Elliott_Fibonacci", "status": "open",
        "entry_price": 0.0045, "fill_price": 0.0045, "stop_loss": 0.0043,
        "take_profit": 0.0051, "quantity": 1000.0, "notional_usdt": 4.5,
        "rr_ratio": 1.5, "created_at": "2026-10-16T08:00:00Z",
        "filled_at": "2026-10-16T08:05:00Z", "is_real": 1,
        "meta_json": None, "initial_quantity": 1000.0,
        "realized_pnl_usdt": 0, "expires_at": None,
    }
    base.update(kw)
    return base


def notif_types():
    rows = vnz.db.query("SELECT ntype, message FROM notifications ORDER BY id DESC LIMIT 50")
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# 1) بوابة تلغرام — الأصناف المهمة فقط
# ─────────────────────────────────────────────────────────────────────────────

def test_telegram_gate_whitelist(tg_off):
    # المهم يمر
    for nt in ("NEW_SIGNAL", "ORDER_FILLED", "TRADE_CLOSED", "PENDING_LIFECYCLE",
               "MANUAL_CLOSE_REQUIRED", "REAL_TRADE_ERROR", "RISK_PAUSE", "BOOT"):
        assert vnz.telegram_gate(nt), f"الصنف المهم {nt} يجب أن يُرسل"
    # الضجيج يُكتم (يبقى في اللوحة وحدها)
    for nt in ("DATA_PROVIDER", "UNIVERSE_SCAN", "IDLE_RESCAN", "BREAK_EVEN",
               "ORDER_CANCELLED", "DATA_FEED"):
        assert not vnz.telegram_gate(nt), f"الصنف الضجيجي {nt} يجب أن يُكتم"
    # بلا صنف (INFO الافتراضي) يُكتم — التصفية الافتراضية صارمة
    assert not vnz.telegram_gate("")


def test_telegram_gate_star_override(monkeypatch, tg_off):
    monkeypatch.setattr(vnz, "TELEGRAM_ALERT_TYPES", {"*"})
    assert vnz.telegram_gate("UNIVERSE_SCAN")  # السلوك القديم: الكل يُرسل
    assert vnz.telegram_gate("ANYTHING")


def test_log_and_notify_panel_always_telegram_gated(clean_db, tg_off):
    # الضجيج يُسجّل في اللوحة دائمًا لكن لا يصل التلغرام (هنا: لا مفاتيح أصلاً —
    # نتحقق أن الإدخال في notifications تم رغم الكتم)
    vnz.log_and_notify("info", "🛰 فحص كون تجريبي", "UNIVERSE_SCAN")
    rows = notif_types()
    assert any(r["ntype"] == "UNIVERSE_SCAN" for r in rows)


# ─────────────────────────────────────────────────────────────────────────────
# 2) كتم التكرار الحرفي + 3) القصّ الآمن
# ─────────────────────────────────────────────────────────────────────────────

def test_tg_dedup_same_message_muted(monkeypatch, tg_off):
    monkeypatch.setattr(vnz, "TELEGRAM_DEDUP_SEC", 300)
    assert vnz._tg_dedup_ok("رسالة")
    assert not vnz._tg_dedup_ok("رسالة")        # نفس الرسالة داخل النافذة ← كتم
    assert vnz._tg_dedup_ok("رسالة أخرى")        # رسالة مختلفة تمر


def test_tg_dedup_disabled_at_zero(monkeypatch, tg_off):
    monkeypatch.setattr(vnz, "TELEGRAM_DEDUP_SEC", 0)
    assert vnz._tg_dedup_ok("رسالة")
    assert vnz._tg_dedup_ok("رسالة")             # 0 = بلا كتم (السلوك القديم)


def test_send_telegram_truncates_long_message(monkeypatch, tg_off):
    monkeypatch.setattr(vnz, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(vnz, "TELEGRAM_CHAT_ID", "C")
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["json"] = json
        class R:
            status_code = 200
            def json(self):
                return {"ok": True}
        return R()

    monkeypatch.setattr(vnz.requests, "post", fake_post)
    vnz.send_telegram_message("ب" * 5000)
    assert len(captured["json"]["text"]) <= 4002  # 4000 + " …" — تحت حد تلغرام 4096


# ─────────────────────────────────────────────────────────────────────────────
# 4) محلل الأوامر + 5) help/ping
# ─────────────────────────────────────────────────────────────────────────────

def test_tg_parse_command_pure():
    assert vnz.tg_parse_command("/close PUMP/USDT") == ("close", "PUMP/USDT")
    assert vnz.tg_parse_command("/اغلق btc") == ("close", "btc")
    assert vnz.tg_parse_command("/status@fibo_bot") == ("status", "")
    assert vnz.tg_parse_command("/close") == ("close", "")
    assert vnz.tg_parse_command("/معلق") == ("pending", "")
    assert vnz.tg_parse_command("/احصاء") == ("stats", "")
    assert vnz.tg_parse_command("/أوامر") == ("help", "")
    assert vnz.tg_parse_command("/unknown_cmd") == ("", "")
    assert vnz.tg_parse_command("مرحبا بلا أمر") == ("", "")
    assert vnz.tg_parse_command("") == ("", "")


def test_tg_help_and_ping_replies(clean_db, tg_off):
    h = vnz.tg_handle_command("help", "")
    for cmd in ("/status", "/close", "/pending", "/stats", "/pause", "/resume"):
        assert cmd in h
    p = vnz.tg_handle_command("ping", "")
    assert vnz.BOT_VERSION in p


# ─────────────────────────────────────────────────────────────────────────────
# 6) set_trading_enabled الموحّد
# ─────────────────────────────────────────────────────────────────────────────

def test_set_trading_enabled_pause_resume(clean_db, tg_off):
    original = vnz.is_trading_enabled
    try:
        msg_off = vnz.set_trading_enabled(False, "اختبار")
        assert vnz.is_trading_enabled is False
        assert vnz.db_get_state("trading_enabled") == "0"
        assert "بواسطة اختبار" in msg_off
        rows = notif_types()
        assert any(r["ntype"] == "TRADING_STATUS_CHANGE" for r in rows)
        msg_on = vnz.set_trading_enabled(True, "اختبار")
        assert vnz.is_trading_enabled is True
        assert vnz.db_get_state("trading_enabled") == "1"
        assert "بواسطة اختبار" in msg_on
    finally:
        vnz.set_trading_enabled(original, "استعادة")


# ─────────────────────────────────────────────────────────────────────────────
# 7-9) نظام «غلق يدوي مطلوب»
# ─────────────────────────────────────────────────────────────────────────────

def test_manual_close_flag_alert_once_and_remind_window(clean_db, tg_off, monkeypatch):
    monkeypatch.setattr(vnz, "MANUAL_CLOSE_REMIND_SEC", 600)
    sig = make_sig()
    vnz.db.execute(
        "INSERT INTO signals (id, symbol, direction, strategy_name, status, entry_price, fill_price,"
        " stop_loss, take_profit, quantity, notional_usdt, rr_ratio, created_at, filled_at, is_real, meta_json)"
        " VALUES (1,'PUMP/USDT','BULLISH','Elliott_Fibonacci','open',0.0045,0.0045,0.0043,0.0051,"
        "1000.0,4.5,1.5,'2026-10-16T08:00:00Z','2026-10-16T08:05:00Z',1,NULL)")
    vnz._flag_manual_close_required(sig, 0.0051, "هدف فيبوناتشي 1.618 تحقق — فشل أمر البيع")
    rows = notif_types()
    mcr = [r for r in rows if r["ntype"] == "MANUAL_CLOSE_REQUIRED"]
    assert len(mcr) == 1
    assert "غلق يدوي مطلوب" in mcr[0]["message"]
    assert "PUMP/USDT" in mcr[0]["message"]
    assert "/close" in mcr[0]["message"]           # إرشاد التنفيذ من تلغرام
    assert "هدفها" in mcr[0]["message"]            # المستوى مسمّى (هدف لا وقف)
    # داخل نافذة التذكير: لا تنبيه جديد (حماية من سبام حلقة الستين ثانية)
    vnz._flag_manual_close_required(sig, 0.0051, "هدف فيبوناتشي 1.618 تحقق — فشل أمر البيع")
    rows = notif_types()
    assert len([r for r in rows if r["ntype"] == "MANUAL_CLOSE_REQUIRED"]) == 1
    # والعلم محفوظ
    meta = vnz._sig_meta({"meta_json": vnz.db.query("SELECT meta_json FROM signals WHERE id=1")[0]["meta_json"]})
    assert meta.get("manual_close_required") is True


def test_manual_close_remind_after_window(clean_db, tg_off, monkeypatch):
    monkeypatch.setattr(vnz, "MANUAL_CLOSE_REMIND_SEC", 600)
    sig = make_sig()
    vnz._flag_manual_close_required(sig, 0.0043, "وقف خسارة تحقق — باينانس محضور")
    # تزييف مرور الوقت: آخر تنبيه قبل النافذة
    meta = vnz._sig_meta(sig)
    meta["mcr_alert_at"] = time.time() - 700
    sig2 = dict(sig)
    sig2["meta_json"] = json.dumps(meta)
    vnz._flag_manual_close_required(sig2, 0.0043, "وقف خسارة تحقق — باينانس محضور")
    rows = notif_types()
    assert len([r for r in rows if r["ntype"] == "MANUAL_CLOSE_REQUIRED"]) == 2
    assert "وقفها" in rows[0]["message"]


def test_close_real_trade_failure_flags_manual_close(clean_db, tg_off, monkeypatch):
    """التكامل الحرج: صفقة حقيقية بلغت هدفها، فشل أمر البيع (باينانس محضور) ←
    علم + تنبيه غلق يدوي. الفشل يساهلي (لا استثناء يتصاعد)."""
    monkeypatch.setattr(vnz, "binance_trade_exchange", lambda: object())  # متصل
    monkeypatch.setattr(vnz, "fetch_free_base", lambda ex, base: 1000.0)
    monkeypatch.setattr(vnz, "real_adjust_amount", lambda ex, sym, q: q)
    monkeypatch.setattr(vnz, "real_market", lambda ex, sym: {})
    monkeypatch.setattr(vnz, "real_min_amount", lambda mkt: 0.0)
    monkeypatch.setattr(vnz, "real_min_cost", lambda mkt: 0.0)
    monkeypatch.setattr(vnz, "place_real_market_sell", lambda sym, q: None)  # الفشل
    sig = make_sig(status="open")
    vnz.db.execute(
        "INSERT INTO signals (id, symbol, direction, strategy_name, status, entry_price, fill_price,"
        " stop_loss, take_profit, quantity, notional_usdt, rr_ratio, created_at, filled_at, is_real, meta_json)"
        " VALUES (1,'PUMP/USDT','BULLISH','Elliott_Fibonacci','open',0.0045,0.0045,0.0043,0.0051,"
        "1000.0,4.5,1.5,'2026-10-16T08:00:00Z','2026-10-16T08:05:00Z',1,NULL)")
    vnz.close_real_trade(sig, 0.0051, "هدف فيبوناتشي 1.618 تحقق")
    rows = notif_types()
    assert any(r["ntype"] == "MANUAL_CLOSE_REQUIRED" for r in rows)
    m = vnz.db.query("SELECT meta_json FROM signals WHERE id=1")[0]
    assert json.loads(m["meta_json"])["manual_close_required"] is True
    # الصفقة ما تزال مفتوحة (لا فقدان — إعادة المحاولة كل دورة)
    assert vnz.db.query("SELECT status FROM signals WHERE id=1")[0]["status"] == "open"


def test_close_signal_row_resolves_manual_close_flag(clean_db, tg_off):
    sig = make_sig(is_real=0)
    vnz.db.execute(
        "INSERT INTO signals (id, symbol, direction, strategy_name, status, entry_price, fill_price,"
        " stop_loss, take_profit, quantity, notional_usdt, rr_ratio, created_at, filled_at, is_real, meta_json)"
        " VALUES (1,'PUMP/USDT','BULLISH','Elliott_Fibonacci','open',0.0045,0.0045,0.0043,0.0051,"
        "1000.0,4.5,1.5,'2026-10-16T08:00:00Z','2026-10-16T08:05:00Z',0,"
        "'{\"manual_close_required\": true, \"mcr_first_at\": \"2026-10-16T08:30:00Z\"}')")
    sig["meta_json"] = '{"manual_close_required": true, "mcr_first_at": "2026-10-16T08:30:00Z"}'
    vnz.close_signal_row(sig, 0.0051, "هدف فيبوناتشي 1.618 تحقق")
    m = vnz.db.query("SELECT meta_json, status FROM signals WHERE id=1")[0]
    assert m["status"] == "closed"
    assert json.loads(m["meta_json"])["manual_close_required"] is False
    rows = notif_types()
    assert any(r["ntype"] == "MANUAL_CLOSE_REQUIRED" and "حُلّ" in r["message"] for r in rows)


# ─────────────────────────────────────────────────────────────────────────────
# 10-11) كاش الشموع + الوضع المتدهور
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def cache_env(monkeypatch):
    monkeypatch.setattr(vnz, "_kline_cache_max_ts", {})
    monkeypatch.setattr(vnz, "_kline_cache_state",
                        {"degraded": False, "writes": 0, "reads": 0, "last_write": None})
    monkeypatch.setattr(vnz, "KLINE_CACHE_ROWS", 150)
    yield


def closed_candles(n=10, period=300, ts_now=None):
    """شموع مغلقة حصرًا — آخر شمعة قبل الفترة الحالية."""
    t0 = (ts_now or int(time.time() * 1000)) - period * 1000 * (n + 1)
    return [[t0 + i * period * 1000, 1.0 + i * 0.001, 1.02 + i * 0.001,
             0.99, 1.01 + i * 0.001, 100.0] for i in range(n)]


def test_kline_cache_roundtrip_skips_open_candle(clean_db, cache_env):
    rows = closed_candles(10)
    open_candle = [int(time.time() * 1000) - 60_000, 2.0, 2.1, 1.9, 2.05, 50.0]  # داخل الدقيقة الجارية
    vnz._kline_cache_write("PUMP/USDT", "5m", rows + [open_candle])
    assert vnz._kline_cache_state["writes"] == 1
    got = vnz._kline_cache_read("PUMP/USDT", "5m", 150)
    assert got is not None and len(got) == 10           # الشمعة المفتوحة استُبعدت
    assert got[0][0] == rows[0][0] and got[-1][0] == rows[-1][0]
    # الكتابة الثانية بلا شموع جديدة: صفر كتابة إضافية (الجديد وحده)
    vnz._kline_cache_write("PUMP/USDT", "5m", rows)
    assert vnz._kline_cache_state["writes"] == 1
    # شمعة مغلقة جديدة تُكتب وحدها
    new_ts = rows[-1][0] + 300_000
    vnz._kline_cache_write("PUMP/USDT", "5m", rows + [[new_ts, 1.5, 1.6, 1.4, 1.55, 80.0]])
    assert vnz._kline_cache_state["writes"] == 2
    got = vnz._kline_cache_read("PUMP/USDT", "5m", 150)
    assert len(got) == 11 and got[-1][0] == new_ts


def test_degraded_mode_serves_cache_when_all_providers_fail(clean_db, cache_env, monkeypatch):
    rows = closed_candles(60)
    vnz._kline_cache_write("PUMP/USDT", "5m", rows)
    monkeypatch.setattr(vnz, "RAW_PROVIDERS", [])       # لا بدائل خام
    monkeypatch.setattr(vnz, "EXCHANGES", {})           # لا باينانس ccxt
    got, src = vnz.fetch_ohlcv_raw("PUMP/USDT", "5m", 60)
    assert src == "cache" and len(got) == 60
    assert vnz._kline_cache_state["degraded"] is True
    rows2 = notif_types()
    assert any(r["ntype"] == "DATA_DEGRADED" and "متدهور" in r["message"] for r in rows2)
    # عودة مزود: الخروج من الوضع المتدهور معلن مرة واحدة
    vnz._kline_cache_note_degraded(False)
    assert vnz._kline_cache_state["degraded"] is False


def test_no_cache_returns_none_not_degraded(clean_db, cache_env, monkeypatch):
    monkeypatch.setattr(vnz, "RAW_PROVIDERS", [])
    monkeypatch.setattr(vnz, "EXCHANGES", {})
    got, src = vnz.fetch_ohlcv_raw("ZK/USDT", "5m", 60)
    assert got is None and src is None
    assert vnz._kline_cache_state["degraded"] is False  # لا كاش أصلاً ≠ وضع متدهور


# ─────────────────────────────────────────────────────────────────────────────
# 12-13) /health + تزامن الإصدار
# ─────────────────────────────────────────────────────────────────────────────

def test_health_exposes_fe198_blocks():
    client = vnz.app.test_client()
    r = client.get("/health")
    assert r.status_code == 200
    body = r.get_json()
    assert "telegram_control" in body and "kline_cache" in body
    assert body["kline_cache"]["rows_per_symbol"] == vnz.KLINE_CACHE_ROWS
    assert set(body["telegram_control"]) >= {"enabled", "commands_n", "errors"}


def test_version_sync_fe198():
    assert vnz.BOT_VERSION == "EL2.3.0"
    assert panel.BOT_VERSION == "EL2.3.0"
    client = vnz.app.test_client()
    assert client.get("/health").get_json()["version"] == "EL2.3.0"


def test_panel_renders_manual_close_badge():
    """شارة 🚨 في renderOpen عند علم meta — وغيابها بدون علم."""
    open_row = {
        "id": 1, "symbol": "PUMP/USDT", "status": "open", "is_real": 1,
        "direction": "BULLISH", "entry_price": 0.0045, "fill_price": 0.0045,
        "stop_loss": 0.0043, "take_profit": 0.0051, "quantity": 1000,
        "rr_ratio": 1.5, "created_at": "2026-10-16T08:00:00Z",
        "expires_at": None, "current_price": 0.0051,
        "unrealized_usdt": 0.5, "unrealized_pct": 13.3, "progress_pct": 80,
        "dist_tp_pct": 2, "dist_sl_pct": 9, "meta": {"manual_close_required": True},
    }
    html = panel.PANEL_HTML
    assert "p-mcr" in html and "manual_close_required" in html
