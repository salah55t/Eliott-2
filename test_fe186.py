#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fe186.py — اختبارات FE1.8.6: تبديل مزود البيانات يصل السجل/اللوحة

الحدث الحي (12:55:55Z، بعد نشر FE1.8.5):
  باينانس رفض الإقلاع بـ 429 -1003 («6000 weight per minute») عند الفحص الأول
  → سلسلة المزودين انتقلت صامتًا إلى bybit — بطاقة «مزود البيانات» في اللوحة
  تغيرت إلى BYBIT واللوج بقي فارغًا (نفس نمط شكوى المستخدم: الفشل ظاهر في
  اللوحة وبلا أثر في السجل). الانتقال كان logger.info فقط.

الإصلاح: الانتقال بين المزودين يُنشئ إشعارًا في السجل:
  • فشل الأساسي ← انتقال لبديل: warning بنص «فشل مزود البيانات X — الانتقال
    إلى Y — السبب: <آخر خطأ X>»
  • عودة الأساسي بعد انقطاع: info «عاد مزود البيانات الأساسي X»
  • أول مزود منذ الإقلاع: info «مزود البيانات الفعّال منذ الإقلاع: X»
  • بلا تبديل ← بلا إشعار (لا ضجيج)
  • إشعار المزود لا يُسقط مسار البيانات أبدًا (حصار try/except)

تشغيل: pytest test_fe186.py -v   (من داخل مجلد المشروع)
"""

import time

import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة (نفس عقد test_fe100)


# ─────────────────────────────────────────────────────────────────────────────
# تجهيزات
# ─────────────────────────────────────────────────────────────────────────────

_KLINE = [1728900000000, "1.0", "1.0", "1.0", "1.0", "1.0"]


class _GoodEx:
    """مزود وهمي صحيح — يعمل عبر مساري باينانس (publicGetKlines) والعام (fetch_ohlcv)."""
    def publicGetKlines(self, params):
        return [list(_KLINE)] * 50

    def fetch_ohlcv(self, symbol, timeframe=None, limit=None):
        return [[_KLINE[0], 1.0, 1.0, 1.0, 1.0, 1.0]] * 50


class _BadEx:
    """مزود وهمي فاشل — يرفع دائمًا (حظر -1003 مثالًا)."""
    def publicGetKlines(self, params):
        raise RuntimeError("binance 429 Too Many Requests {\"code\":-1003}")

    def fetch_ohlcv(self, symbol, timeframe=None, limit=None):
        raise RuntimeError("bybit exploded")


def _state(last_error: str = "", cooling: float = 0.0) -> dict:
    return {"ok": 0, "fail": 0, "last_error": last_error, "last_ok_at": None,
            "cooldown_until": time.time() + cooling, "markets_pruned": True}


@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    """قاعدة SQLite مؤقتة لكل اختبار — نفس عقد test_fe100."""
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
def providers(clean_db, monkeypatch):
    """عالم مزودين وهمي: binance فاشل + bybit صحيح — مع عزل active_source/prune."""
    monkeypatch.setattr(vnz, "EXCHANGES", {"binance": _BadEx(), "bybit": _GoodEx()})
    monkeypatch.setattr(vnz, "provider_state",
                        {"binance": _state(), "bybit": _state()})
    monkeypatch.setattr(vnz, "active_source", {"name": None, "since": None})
    monkeypatch.setattr(vnz, "prune_markets", lambda ex: 0)
    # [FE1.8.7] هذه الاختبارات تعاقد مسار ccxt القديم (قاتل الطوارئ DATA_FEED_RAW=0)
    # — الطبقة الخام المقتبسة من V9 لها عالمها وعقودها في test_fe187.py
    monkeypatch.setattr(vnz, "DATA_FEED_RAW", False)
    yield vnz


def _notif_n(like: str) -> int:
    rows = vnz.db.query(
        "SELECT COUNT(*) AS n FROM notifications WHERE message LIKE %s", (f"%{like}%",))
    return int(rows[0]["n"]) if rows else 0


# ─────────────────────────────────────────────────────────────────────────────
# الإشعارات
# ─────────────────────────────────────────────────────────────────────────────

class TestProviderFailoverNotify:

    def test_first_boot_provider_notifies(self, providers):
        # أول مزود ناجح منذ الإقلاع (active_source فارغ) → إشعار info
        # عالم fixtures: binance فاشل → أول نجاح = bybit
        raw, used = vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 50)
        assert used == "bybit"
        assert raw is not None
        assert _notif_n("مزود البيانات الفعّال منذ الإقلاع: BYBIT") == 1

    def test_failover_notifies_with_reason(self, providers):
        # الأساسي فاشل (آخر خطأ -1003) والبديل نجح → warning بالسبب
        providers.provider_state["binance"]["last_error"] = \
            "binance 429 Too Many Requests {\"code\":-1003}"
        providers.active_source["name"] = "binance"
        raw, used = vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 50)
        assert used == "bybit"
        assert raw is not None
        assert _notif_n("فشل مزود البيانات BINANCE — الانتقال إلى BYBIT") == 1
        assert _notif_n("-1003") == 1

    def test_recovery_to_primary_notifies(self, providers):
        # الأساسي تعافى (تبريد منتهٍ) والبديل محجوب → إشعار عودة
        providers.provider_state["binance"].update(_state())  # بلا تبريد — جاهز
        providers.provider_state["binance"]["cooldown_until"] = 0.0
        providers.EXCHANGES["binance"] = _GoodEx()          # باينانس عاد
        providers.active_source["name"] = "bybit"
        providers.provider_state["bybit"]["cooldown_until"] = time.time() + 9999
        raw, used = vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 50)
        assert used == "binance"
        assert _notif_n("عاد مزود البيانات الأساسي BINANCE") == 1
        assert _notif_n("خدمنا خلال الانقطاع") == 1

    def test_no_noise_without_transition(self, providers, monkeypatch):
        # نفس المزود يواصل النجاح → صفر إشعارات مزود
        providers.active_source["name"] = "bybit"
        raw, used = vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 50)
        assert used == "bybit"
        assert _notif_n("مزود البيانات") == 0

    def test_all_providers_fail_returns_none(self, providers, monkeypatch):
        # كل المزودين فاشلون → None بلا انهيار (والإشعارات بلا تبديل ناجح)
        monkeypatch.setattr(vnz, "EXCHANGES", {"binance": _BadEx(), "bybit": _BadEx()})
        providers.active_source["name"] = "binance"
        raw, used = vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 50)
        assert raw is None and used is None

    def test_notify_failure_never_breaks_fetch(self, providers, monkeypatch):
        # حتى لو انفجر log_and_notify — الجلب ينجح والمسار سليم
        def _explode(*a, **k):
            raise RuntimeError("sink dead")
        monkeypatch.setattr(vnz, "log_and_notify", _explode)
        raw, used = vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 50)
        assert used == "bybit" and raw is not None


# ─────────────────────────────────────────────────────────────────────────────
# الإصدار
# ─────────────────────────────────────────────────────────────────────────────

class TestVersion:

    def test_version_bumped_everywhere(self):
        import panel
        assert vnz.BOT_VERSION == "EL2.0.0"
        assert panel.BOT_VERSION == "EL2.0.0"
