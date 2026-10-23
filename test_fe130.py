#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fe130.py — اختبارات البقاء الحي (مضاد نوم Render المجاني) FE1.3.0

خمس جولات:
  1) اشتقاق هدف النبضة: KEEP_ALIVE_URL ← RENDER_EXTERNAL_URL ← PANEL_URL + لاحقة /health
  2) النبضة الواحدة: نجاح 200 / رفض HTTP / استثناء شبكي — عدادات التشخيص
  3) الحلقة: معطلة بالعلم / بلا هدف / توقف فوري بالحدث — بلا أي نبضات
  4) /health عام بلا مصادقة (كرون جوب) مع قسم keep_alive — حتى واللوحة محمية
  5) /api/all يحمل بطاقة النبضة للوحة

تشغيل: pytest test_fe130.py -v   (من داخل مجلد المشروع)
"""

import threading
import types

import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة (الافتراضي في الإنتاج admin/test123)


# ─────────────────────────────────────────────────────────────────────────────
# تجهيزات
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    """قاعدة SQLite مؤقتة لكل اختبار — عزل كامل (نمط test_fe100)."""
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
def ka_reset():
    """حالة وحدث نبضة نظيفان لكل اختبار — بلا خيوط خلفية في الاختبارات."""
    vnz.keep_alive_stop = threading.Event()
    with vnz.keep_alive_lock:
        vnz.keep_alive_state.update({
            "enabled": False, "target": "", "interval_sec": 0.0,
            "last_ping_at": "", "last_ok": None, "ok_count": 0, "fail_count": 0,
        })
    yield
    vnz.keep_alive_stop.set()


@pytest.fixture()
def client(clean_db):
    return vnz.app.test_client()


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 1 — اشتقاق هدف النبضة
# ─────────────────────────────────────────────────────────────────────────────

class TestResolveKeepAliveUrl:
    def test_explicit_url_wins_over_render(self, monkeypatch, ka_reset):
        monkeypatch.setattr(vnz, "KEEP_ALIVE_URL", "https://manual.example.com/")
        monkeypatch.setattr(vnz, "RENDER_EXTERNAL_URL", "https://fibo-elio.onrender.com")
        monkeypatch.setattr(vnz, "PANEL_URL", "https://fallback.example.com")
        assert vnz.resolve_keep_alive_url() == "https://manual.example.com/health"

    def test_render_external_url_second(self, monkeypatch, ka_reset):
        monkeypatch.setattr(vnz, "KEEP_ALIVE_URL", "")
        monkeypatch.setattr(vnz, "RENDER_EXTERNAL_URL", "https://fibo-elio.onrender.com")
        monkeypatch.setattr(vnz, "PANEL_URL", "https://fallback.example.com")
        assert vnz.resolve_keep_alive_url() == "https://fibo-elio.onrender.com/health"

    def test_panel_url_last_fallback(self, monkeypatch, ka_reset):
        monkeypatch.setattr(vnz, "KEEP_ALIVE_URL", "")
        monkeypatch.setattr(vnz, "RENDER_EXTERNAL_URL", "")
        monkeypatch.setattr(vnz, "PANEL_URL", "https://fallback.example.com")
        assert vnz.resolve_keep_alive_url() == "https://fallback.example.com/health"

    def test_empty_when_no_base(self, monkeypatch, ka_reset):
        monkeypatch.setattr(vnz, "KEEP_ALIVE_URL", "")
        monkeypatch.setattr(vnz, "RENDER_EXTERNAL_URL", "")
        monkeypatch.setattr(vnz, "PANEL_URL", "")
        assert vnz.resolve_keep_alive_url() == ""


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 2 — النبضة الواحدة وعدادات التشخيص
# ─────────────────────────────────────────────────────────────────────────────

class TestKeepAlivePing:
    def test_ping_success_updates_counters(self, monkeypatch, ka_reset):
        calls = []
        def fake_get(url, timeout=15):
            calls.append(url)
            return types.SimpleNamespace(status_code=200)
        monkeypatch.setattr(vnz.requests, "get", fake_get)
        assert vnz.keep_alive_ping("https://x.onrender.com/health") is True
        snap = vnz.keep_alive_snapshot()
        assert snap["ok_count"] == 1 and snap["fail_count"] == 0
        assert snap["last_ok"] is True and snap["last_ping_at"]
        assert calls == ["https://x.onrender.com/health"]

    def test_ping_http_500_counts_as_failure(self, monkeypatch, ka_reset):
        monkeypatch.setattr(vnz.requests, "get", lambda u, timeout=15: types.SimpleNamespace(status_code=500))
        assert vnz.keep_alive_ping("https://x.onrender.com/health") is False
        snap = vnz.keep_alive_snapshot()
        assert snap["ok_count"] == 0 and snap["fail_count"] == 1
        assert snap["last_ok"] is False

    def test_ping_network_exception_counts_as_failure(self, monkeypatch, ka_reset):
        def boom(url, timeout=15):
            raise ConnectionError("شبكة مقطوعة")
        monkeypatch.setattr(vnz.requests, "get", boom)
        assert vnz.keep_alive_ping("https://x.onrender.com/health") is False
        snap = vnz.keep_alive_snapshot()
        assert snap["fail_count"] == 1 and snap["last_ok"] is False


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 3 — الحلقة: أعلام التوقف والتعطيل
# ─────────────────────────────────────────────────────────────────────────────

class TestKeepAliveLoop:
    def test_disabled_by_flag_returns_without_ping(self, monkeypatch, ka_reset):
        pings = []
        monkeypatch.setattr(vnz, "KEEP_ALIVE_ENABLED", False)
        monkeypatch.setattr(vnz, "KEEP_ALIVE_URL", "https://x.onrender.com")
        monkeypatch.setattr(vnz, "keep_alive_ping", lambda u: pings.append(u) or True)
        vnz.keep_alive_loop()  # يجب أن يعود فورًا
        assert pings == []
        assert vnz.keep_alive_snapshot()["enabled"] is False

    def test_no_target_returns_without_ping(self, monkeypatch, ka_reset):
        pings = []
        monkeypatch.setattr(vnz, "KEEP_ALIVE_ENABLED", True)
        monkeypatch.setattr(vnz, "KEEP_ALIVE_URL", "")
        monkeypatch.setattr(vnz, "RENDER_EXTERNAL_URL", "")
        monkeypatch.setattr(vnz, "PANEL_URL", "")
        monkeypatch.setattr(vnz, "keep_alive_ping", lambda u: pings.append(u) or True)
        vnz.keep_alive_loop()
        assert pings == []
        assert vnz.keep_alive_snapshot()["enabled"] is False

    def test_stop_event_before_first_wait_no_ping(self, monkeypatch, ka_reset):
        """الحدث مضبوط مسبقًا → الحلقة تعود قبل أول نبضة لكن بعد تمكين الحالة."""
        pings = []
        monkeypatch.setattr(vnz, "KEEP_ALIVE_ENABLED", True)
        monkeypatch.setattr(vnz, "KEEP_ALIVE_URL", "https://x.onrender.com")
        monkeypatch.setattr(vnz, "keep_alive_ping", lambda u: pings.append(u) or True)
        vnz.keep_alive_stop.set()
        vnz.keep_alive_loop()
        assert pings == []
        snap = vnz.keep_alive_snapshot()
        assert snap["enabled"] is True
        assert snap["target"] == "https://x.onrender.com/health"


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 4 — /health عام بلا مصادقة (هدف كرون جوب)
# ─────────────────────────────────────────────────────────────────────────────

class TestHealthPublicForCron:
    def test_health_open_without_credentials(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        body = r.get_json()
        assert body["version"] == "EL2.3.0"
        assert isinstance(body["keep_alive"], dict)

    def test_health_stays_open_while_dashboard_protected(self, client, monkeypatch):
        """جوهر الطلب: لا حاجة لإزالة المصادقة — /health تبقى عامة لكرون جوب."""
        monkeypatch.setattr(vnz, "DASHBOARD_PROTECTED", True)
        assert client.get("/").status_code == 401              # اللوحة محمية
        assert client.get("/health").status_code == 200        # النبضة عامة

    def test_health_reports_enabled_state(self, client, monkeypatch, ka_reset):
        monkeypatch.setattr(vnz, "KEEP_ALIVE_ENABLED", True)
        monkeypatch.setattr(vnz, "KEEP_ALIVE_URL", "https://fibo-elio.onrender.com")
        vnz.keep_alive_stop.set()
        vnz.keep_alive_loop()
        body = client.get("/health").get_json()
        assert body["keep_alive"]["enabled"] is True
        assert body["keep_alive"]["target"] == "https://fibo-elio.onrender.com/health"
        assert body["keep_alive"]["interval_sec"] == vnz.KEEP_ALIVE_INTERVAL_SEC


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 5 — بطاقة النبضة في /api/all
# ─────────────────────────────────────────────────────────────────────────────

class TestApiAllKeepAlive:
    def test_api_all_carries_keep_alive_snapshot(self, client):
        body = client.get("/api/all").get_json()
        assert "keep_alive" in body
        ka = body["keep_alive"]
        for key in ("enabled", "target", "interval_sec", "ok_count", "fail_count"):
            assert key in ka
