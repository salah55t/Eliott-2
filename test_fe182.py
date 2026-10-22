#!/usr/bin/env python3
# test_fe182.py — اختبارات FE1.8.2: إصلاح علة التصفير الحيّرة على Postgres.
#
# الجذر: db.query("...LIKE 'stats_archive_%'...") كانت تمرر params=() فارغة إلى
# psycopg2 الذي يُجري interpolation جانب العميل فتُفسَّر % الحرفية كنائب تنسيق
# → IndexError → التصفير يفشل دائمًا على PG (3/3 محاولات حية) بينما تنجح
# اختبارات SQLite (بلا interpolation). الإصلاح: بلا params لا يُمرَّر شيء للسائق
# + أرشفة بلا ابتلاع استثناءات + احتياط مدمج + نص الخطأ في الرد.
#
# العقد: 338+2 سابقة لا تنكسر (تأكيدات الإصدار حُدثت FE1.8.2) — حدود FE1.7.0/1.8.0
# المحمية ثابتة (حراسات التصفير الثلاثة، الأرشفة قبل الحذف، تصفير عدادات risk_*).
import json
import sqlite3
import threading

import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة (نفس عقد test_fe100/170/181)


# ─────────────────────────────────────────────────────────────────────────────
# تجهيزات
# ─────────────────────────────────────────────────────────────────────────────

class _FakeCursor:
    """مؤشر زائف يوثق نداءات execute كما يستقبلها السائق بالضبط."""
    def __init__(self, conn):
        self.conn = conn
    def execute(self, *args):
        self.conn.calls.append(args)
    def fetchall(self):
        return []
    description = None
    def close(self):
        pass


class _FakeConn:
    def __init__(self):
        self.calls = []
    def cursor(self):
        return _FakeCursor(self)
    def commit(self):
        pass
    def rollback(self):
        pass


def make_driverless_db(monkeypatch):
    """Database بلا اتصال حقيقي — لعقد السائق فقط (USE_POSTGRES يحدد مسار _ph/الصفوف)."""
    monkeypatch.setattr(vnz, "USE_POSTGRES", False)
    d = vnz.Database.__new__(vnz.Database)
    d.lock = threading.Lock()
    d.conn = _FakeConn()
    return d


@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    monkeypatch.setattr(vnz, "USE_POSTGRES", False)
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    old = vnz.db.conn
    vnz.db.conn = conn
    vnz.init_db()
    vnz.set_paper_balance(vnz.PAPER_BALANCE_START)
    with vnz._reject_reason_lock:
        vnz._reject_reason.clear()
    with vnz.scan_stats_lock:
        for k in vnz.scan_stats:
            vnz.scan_stats[k] = 0
    yield vnz.db
    vnz.db.conn = old


def insert_closed(symbol="A/USDT", pnl=1.0):
    vnz.db.execute(
        "INSERT INTO signals (symbol, direction, strategy_name, status, entry_price, stop_loss,"
        " take_profit, quantity, notional_usdt, pnl_usdt, created_at, closed_at, is_real)"
        " VALUES (%s,%s,'Elliott_Fibonacci','closed',106.0,99.9,115.0,10.0,%s,%s,%s,%s,0)",
        (symbol, "BULLISH", abs(pnl) * 10.0, pnl,
         vnz.utc_now_iso(), vnz.utc_now_iso()),
    )


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 1 — عقد السائق: params فارغة لا تمر إلى execute السائق أبدًا
# ─────────────────────────────────────────────────────────────────────────────

class TestDriverContract:

    def test_query_empty_params_sends_sql_only(self, monkeypatch):
        d = make_driverless_db(monkeypatch)
        d.query("SELECT 1 AS ok", one=True)
        assert len(d.conn.calls) == 1
        assert len(d.conn.calls[0]) == 1  # SQL وحده — لا كائن params فارغ يفجّر interpolation
        assert d.conn.calls[0][0] == "SELECT 1 AS ok"

    def test_execute_empty_params_sends_sql_only(self, monkeypatch):
        d = make_driverless_db(monkeypatch)
        d.execute("DELETE FROM signals")
        assert len(d.conn.calls) == 1
        assert len(d.conn.calls[0]) == 1
        assert d.conn.calls[0][0] == "DELETE FROM signals"

    def test_nonempty_params_still_passed(self, monkeypatch):
        d = make_driverless_db(monkeypatch)
        d.execute("DELETE FROM bot_state WHERE key = %s", ("risk_streak",))
        assert len(d.conn.calls[0]) == 2
        assert d.conn.calls[0][1] == ("risk_streak",)

    def test_production_like_query_never_interpolated(self, monkeypatch):
        # استعلام الإنتاج الحيّر نفسه — مع الإصلاح يمر SQL وحده بلا interpolation
        d = make_driverless_db(monkeypatch)
        d.query("SELECT key FROM bot_state WHERE key LIKE 'stats_archive_%' ORDER BY key DESC")
        sql = d.conn.calls[0][0]
        assert "stats_archive_%" in sql  # النمط يصل للسائق كما هو
        assert len(d.conn.calls[0]) == 1


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 2 — تحصين الأرشفة: نص الخطأ في الرد + احتياط مدمج + بيانات لا تُمسح عند الفشل
# ─────────────────────────────────────────────────────────────────────────────

class TestResetArchiveHardening:

    def _archive_boom(self, monkeypatch, fail_calls):
        """يُفشل نداءات db.execute المحددة (1=الأرشفة الكاملة، 2=المدمجة) ثم يمرر البقية."""
        orig = vnz.db.execute
        state = {"n": 0}

        def wrapper(sql, params=()):
            state["n"] += 1
            if state["n"] in fail_calls:
                raise RuntimeError(f"FAKE_DB_FAIL_{state['n']}")
            return orig(sql, params)

        monkeypatch.setattr(vnz.db, "execute", wrapper)
        return state

    def test_archive_failure_reports_exception_text(self, clean_db, monkeypatch):
        insert_closed(symbol="A/USDT", pnl=1.0)
        self._archive_boom(monkeypatch, fail_calls={1, 2})  # الكاملة والمدمجة معًا
        client = vnz.app.test_client()
        r = client.post("/api/stats/reset", json={"confirm": "RESET"})
        assert r.status_code == 500
        body = r.get_json()
        assert body["ok"] is False
        # [FE1.8.2] نص الاستثناء الحقيقي ظاهر في الرد — لا مزيد من فشل صامت أعمى
        assert "FAKE_DB_FAIL" in body["error"]
        # حراس FE1.7.0: بيانات المستخدم لا تُمسح عند فشل الأرشفة
        n = clean_db.query("SELECT COUNT(*) AS n FROM signals")[0]["n"]
        assert n == 1

    def test_compact_fallback_saves_and_resets(self, clean_db, monkeypatch):
        insert_closed(symbol="B/USDT", pnl=-3.5)
        insert_closed(symbol="C/USDT", pnl=2.0)
        self._archive_boom(monkeypatch, fail_calls={1})  # الكاملة فقط
        client = vnz.app.test_client()
        r = client.post("/api/stats/reset", json={"confirm": "RESET"})
        assert r.status_code == 200
        keys = [x["key"] for x in clean_db.query(
            "SELECT key FROM bot_state WHERE key LIKE 'stats_archive_%'")]
        assert len(keys) == 1 and keys[0].endswith("_compact")
        # الأرشفة المدمجة تحمل الأعمدة الجوهرية للصفحتين
        arch = json.loads(clean_db.query(
            "SELECT value FROM bot_state WHERE key = %s", (keys[0],))[0]["value"])
        assert len(arch) == 2
        assert arch[0]["symbol"] == "B/USDT" and "pnl_usdt" in arch[0] and "close_reason" in arch[0]
        # التصفير اكتمل رغم فشل الأرشفة الكاملة
        assert int(clean_db.query("SELECT COUNT(*) AS n FROM signals")[0]["n"]) == 0
        assert clean_db.query("SELECT value FROM bot_state WHERE key='paper_balance'",
                              one=True)["value"] == repr(vnz.PAPER_BALANCE_START)

    def test_full_archive_still_default_when_healthy(self, clean_db):
        # المسار السليم بلا أعطال: أرشفة كاملة (بلا _compact) ثم تصفير
        insert_closed(symbol="D/USDT", pnl=5.0)
        client = vnz.app.test_client()
        r = client.post("/api/stats/reset", json={"confirm": "RESET"})
        assert r.status_code == 200
        keys = [x["key"] for x in clean_db.query(
            "SELECT key FROM bot_state WHERE key LIKE 'stats_archive_%'")]
        assert len(keys) == 1 and not keys[0].endswith("_compact")

    def test_guards_and_comprehensive_scope_unchanged(self, clean_db):
        # حدود FE1.7.0/1.8.1 المحمية: الحراسات الثلاثة + تصفير عدادات risk_* والأحكام
        client = vnz.app.test_client()
        assert client.post("/api/stats/reset", json={}).status_code == 400
        insert_closed(symbol="E/USDT", pnl=1.0)
        vnz.db_set_state("risk_streak", "2")
        vnz.db_set_state("risk_pause_until", "2099-01-01T00:00:00Z")
        vnz._set_reject_reason("E/USDT", "بنية متقادمة")
        vnz.scan_stats["rejected_old_structure"] = 21
        r = client.post("/api/stats/reset", json={"confirm": "RESET"})
        assert r.status_code == 200
        keys = [x["key"] for x in clean_db.query("SELECT key FROM bot_state")]
        assert "risk_streak" not in keys and "risk_pause_until" not in keys
        assert vnz._get_reject_reason("E/USDT") == ""
        assert vnz.scan_stats["rejected_old_structure"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 3 — حدود محمية
# ─────────────────────────────────────────────────────────────────────────────

class TestProtectedBoundaries:

    def test_version_bumped_everywhere(self):
        import panel
        assert vnz.BOT_VERSION == "EL2.1.0"
        assert panel.BOT_VERSION == "EL2.1.0"
        assert vnz.STRATEGY_NAME == "Elliott_Fibonacci"

    def test_panel_html_has_reset_button(self):
        from panel import PANEL_HTML
        assert "resetStats" in PANEL_HTML and "تصفير الإحصائيات" in PANEL_HTML

    def test_paper_balance_still_resets(self, clean_db):
        vnz.set_paper_balance(9000.0)
        insert_closed(symbol="F/USDT", pnl=-2.0)
        client = vnz.app.test_client()
        client.post("/api/stats/reset", json={"confirm": "RESET"})
        assert vnz.get_paper_balance() == vnz.PAPER_BALANCE_START

    def test_notifications_cleared_on_reset(self, clean_db):
        vnz.log_and_notify("info", "رسالة قبل التصفير", "TEST")
        assert vnz.db.query("SELECT COUNT(*) AS n FROM notifications")[0]["n"] >= 1
        client = vnz.app.test_client()
        client.post("/api/stats/reset", json={"confirm": "RESET"})
        # بقي تنبيه التصفير نفسه فقط (أُنشئ بعد المسح)
        n = vnz.db.query("SELECT COUNT(*) AS n FROM notifications")[0]["n"]
        assert n <= 1
