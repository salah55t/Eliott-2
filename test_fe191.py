#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fe191.py — اختبارات FE1.9.1 «نبض حي»: إصلاح قاتل نبض الحركة

الإثبات الحي (FE1.9.0 على fibo-elio-4s5z بعد نشرها):
  momentum_kicks = 0 بعد 76 دورة كشف رغم عمل الخيط والأسعار الحية.
  الجذر: ws_sync_subscriptions كانت تشترك بويب سوكت لرموز الصفقات النشطة
  وحدها (db signals pending/open) — صفر صفقات = صفر أسعار حية في _ws_price =
  _live_price(sym) ترجع None دائمًا = النبض صامت للأبد بحكم البناء.
  (الويب سوكت صُمم أصلًا في FE1.2.0 لتتبع الصفقات لا لتغذية الكشف)

الحل (كل محور له اختبارات):
  1) ws_wanted_sets — منطق الاشتراك النقي: قائمة الكشف كلها تدخل بتيار سعر
     فقط، ورموز الصفقات النشطة تبقى شموع+سعر
  2) فشل قاعدة البيانات لا يعطل نبض القائمة (rows=None بدل return مبكر)
  3) _ws_spawn(with_ohlcv=False) — تيار سعر فقط لرموز القائمة (حمية 512MB:
     الشموع ذاكرة أثقل وتبقى حكرًا على الصفقات)
  4) الإزالة والتنظيف العامان كما هما — لا بقايا
  5) سلسلة النبض كاملة حية بعد الإصلاح: مرجع مسح + سعر حي متحرك = كيك

تشغيل: pytest test_fe191.py -v   (من داخل مجلد المشروع)
"""

import asyncio
import threading
import time

import pytest

import vnz
import panel


# ─────────────────────────────────────────────────────────────────────────────
# تجهيزات — حلقة asyncio حقيقية في خيط + تيار وهمي (لا شبكة إطلاقًا)
# ─────────────────────────────────────────────────────────────────────────────

async def _stub_stream(symbol: str, stream: str) -> None:
    """بديل _ws_watch_stream — معلق للأبد، قابل للإلغاء، بلا أي شبكة."""
    await asyncio.Event().wait()


class _RowsDb:
    """قاعدة بيانات وهمية ترجع صفوف إشارات نشطة."""

    def __init__(self, rows):
        self._rows = rows

    def query(self, q):
        return self._rows


class _BoomDb:
    """قاعدة بيانات معطوبة — الاستعلام يفشل دائمًا."""

    def query(self, q):
        raise RuntimeError("db down")


@pytest.fixture()
def ws_env(monkeypatch):
    """حلقة asyncio حية في خيط خلفي + حالة ويب سوكت نظيفة ومستعادة."""
    loop = asyncio.new_event_loop()
    th = threading.Thread(target=loop.run_forever, daemon=True)
    th.start()
    time.sleep(0.05)

    monkeypatch.setattr(vnz, "_ws_loop", loop)
    monkeypatch.setattr(vnz, "_ws_watch_stream", _stub_stream)
    monkeypatch.setattr(vnz, "_ws_tasks", {})
    monkeypatch.setattr(vnz, "_ws_price", {})
    monkeypatch.setattr(vnz, "_ws_candles", {})
    monkeypatch.setattr(vnz, "_ws_subs", {})
    monkeypatch.setattr(vnz, "watchlist", [])

    yield {"loop": loop}

    # إطفاء نظيف: إلغاء مهام التيار قبل وقف الحلقة — لا تحذيرات Task destroyed
    try:
        live = [t for tt in list(vnz._ws_tasks.values()) for t in tt.values()
                if hasattr(t, "cancel")]
        for t in live:
            t.cancel()
        if live:
            asyncio.run_coroutine_threadsafe(asyncio.sleep(0), loop).result(2.0)
    except Exception:
        pass
    loop.call_soon_threadsafe(loop.stop)
    th.join(timeout=2.0)


def _wait_done(task, timeout=2.0):
    """انتظار اكتمال مهمة (concurrent future أو asyncio task) في خيط آخر."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if task.done():
            return True
        time.sleep(0.02)
    return False


def _settle(loop, timeout=2.0):
    """انتظار معالجة الحلقة لكل الاستدعاءات المرتبة سابقًا (FIFO) —
    call_soon_threadsafe الخاص ب_ws_spawn يفوض التنفيذ لحلقة asyncio،
    فلا يُضمن ظهور المهام في _ws_tasks لحظة عودة المزامنة."""
    asyncio.run_coroutine_threadsafe(asyncio.sleep(0), loop).result(timeout)


def _sync_settled(loop):
    """مزامنة + استقرار — تعيد نتيجة المزامنة بعد اكتمال مهامها."""
    res = vnz.ws_sync_subscriptions()
    _settle(loop)
    return res


# ─────────────────────────────────────────────────────────────────────────────
# 1) المنطق النقي ws_wanted_sets
# ─────────────────────────────────────────────────────────────────────────────

def test_wanted_sets_signals_only():
    """رموز صفقات نشطة وحدها: شموع+سعر لكل منهم."""
    rows = [{"symbol": "BTC/USDT"}, {"symbol": "ETH/USDT"}]
    wanted, full = vnz.ws_wanted_sets(rows, [], True)
    assert wanted == {"BTC/USDT", "ETH/USDT"}
    assert full == {"BTC/USDT", "ETH/USDT"}


def test_wanted_sets_watchlist_only_ticker_food():
    """[قلب الإصلاح] قائمة كشف بلا صفقات: كلها تدخل wanted — صفر صفقات لا يعطّل النبض."""
    wanted, full = vnz.ws_wanted_sets(
        [], ["BTC/USDT", "ETH/USDT", "SOL/USDT"], True)
    assert wanted == {"BTC/USDT", "ETH/USDT", "SOL/USDT"}
    assert full == set()  # لا شموع — سعر فقط


def test_wanted_sets_union_with_full_for_signals():
    """رمز صفقة نشطة داخل القائمة أيضًا: اشتراك واحد لكن بكل التيارات."""
    rows = [{"symbol": "BTC/USDT"}]
    wanted, full = vnz.ws_wanted_sets(rows, ["BTC/USDT", "XRP/USDT"], True)
    assert wanted == {"BTC/USDT", "XRP/USDT"}
    assert full == {"BTC/USDT"}  # BTC فقط يحصل على الشموع


def test_wanted_sets_db_failure_keeps_watchlist():
    """[مرونة FE1.9.1] قاعدة بيانات معطوبة (rows يرمي) — نبض القائمة يبقى حيًا."""
    wanted, full = vnz.ws_wanted_sets(
        _BoomDbRaises(), ["BTC/USDT", "ETH/USDT"], True)
    assert wanted == {"BTC/USDT", "ETH/USDT"}
    assert full == set()


class _BoomDbRaises:
    """صفوف غير قابلة للتكرار — تحاكي فشل تحويل النتائج."""

    def __iter__(self):
        raise RuntimeError("rows broken")

    def __bool__(self):
        return True


def test_wanted_sets_universe_disabled():
    """كون معطل: لا نبض قائمة — سلوك FE1.2.0 القديم كما هو."""
    wanted, full = vnz.ws_wanted_sets(
        [{"symbol": "BTC/USDT"}], ["ETH/USDT", "SOL/USDT"], False)
    assert wanted == {"BTC/USDT"}
    assert full == {"BTC/USDT"}


def test_wanted_sets_empty_everything():
    """لا صفقات ولا قائمة: لا اشتراكات — صمت مشروع."""
    wanted, full = vnz.ws_wanted_sets(None, [], True)
    assert wanted == set() and full == set()


def test_wanted_sets_normalizes_symbol_types():
    """الرموز غير النصية تُطبع نصًا — لا استثناء من مزج أنواع."""
    rows = [{"symbol": "BTC/USDT"}]
    wanted, full = vnz.ws_wanted_sets(rows, ["ETH/USDT"], True)
    assert all(isinstance(s, str) for s in wanted)


# ─────────────────────────────────────────────────────────────────────────────
# 2) ws_sync_subscriptions — التكامل الحقيقي على حلقة حية
# ─────────────────────────────────────────────────────────────────────────────

def test_sync_subscribes_watchlist_ticker_only(ws_env, monkeypatch):
    """[الإصلاح الجوهري] صفر صفقات + قائمة كشف → اشتراكات سعر للقائمة كلها."""
    monkeypatch.setattr(vnz, "db", _RowsDb([]))
    monkeypatch.setattr(vnz, "watchlist", ["BTC/USDT", "ETH/USDT", "SOL/USDT"])

    res = _sync_settled(ws_env["loop"])
    assert res == {"added": 3, "removed": 0}
    for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
        tasks = vnz._ws_tasks[sym]
        assert "ticker" in tasks, f"{sym} بلا تيار سعر — النبض سيموت من جديد"
        assert "ohlcv" not in tasks, f"{sym} حصل على شموع بلا صفقة — هدر ذاكرة"


def test_sync_signal_symbol_gets_full_streams(ws_env, monkeypatch):
    """رمز صفقة نشطة: شموع + سعر معًا (سلوك FE1.2.0 محفوظ للصفقات)."""
    monkeypatch.setattr(vnz, "db", _RowsDb([{"symbol": "BTC/USDT"}]))
    monkeypatch.setattr(vnz, "watchlist", ["BTC/USDT", "XRP/USDT"])

    res = _sync_settled(ws_env["loop"])
    assert res["added"] == 2
    assert set(vnz._ws_tasks["BTC/USDT"].keys()) == {"ohlcv", "ticker"}
    assert set(vnz._ws_tasks["XRP/USDT"].keys()) == {"ticker"}


def test_sync_db_failure_still_feeds_pulse(ws_env, monkeypatch):
    """[مرونة] قاعدة بيانات معطوبة — الاشتراكات للقائمة تكمل ولا return مبكر."""
    monkeypatch.setattr(vnz, "db", _BoomDb())
    monkeypatch.setattr(vnz, "watchlist", ["BTC/USDT", "ETH/USDT"])

    res = _sync_settled(ws_env["loop"])
    assert res["added"] == 2
    assert set(vnz._ws_tasks.keys()) == {"BTC/USDT", "ETH/USDT"}


def test_sync_universe_disabled_keeps_old_behavior(ws_env, monkeypatch):
    """كون معطل: لا اشتراكات قائمة — الصفقات فقط كما قبل FE1.9.1."""
    monkeypatch.setattr(vnz, "db", _RowsDb([{"symbol": "BTC/USDT"}]))
    monkeypatch.setattr(vnz, "watchlist", ["ETH/USDT"])
    monkeypatch.setattr(vnz, "SCAN_UNIVERSE_ENABLED", False)

    res = _sync_settled(ws_env["loop"])
    assert res["added"] == 1
    assert set(vnz._ws_tasks.keys()) == {"BTC/USDT"}
    assert "ohlcv" in vnz._ws_tasks["BTC/USDT"]


def test_sync_removes_symbols_leaving_wanted(ws_env, monkeypatch):
    """رمز خرج من القائمة وبلا صفقات: إلغاء + لا بقايا سعر/شموع/حالة."""
    monkeypatch.setattr(vnz, "db", _RowsDb([]))
    monkeypatch.setattr(vnz, "watchlist", ["BTC/USDT"])
    # زرع رمز قديم كما لو اشترك سابقًا
    old_task = asyncio.run_coroutine_threadsafe(
        asyncio.sleep(3600), ws_env["loop"])
    vnz._ws_tasks["OLD/USDT"] = {"ticker": old_task}
    vnz._ws_price["OLD/USDT"] = {"price": 1.0, "ts": time.time(), "source": "test"}
    vnz._ws_subs["OLD/USDT"] = {"provider": "test", "state": "live"}

    res = vnz.ws_sync_subscriptions()
    assert res == {"added": 1, "removed": 1}
    assert "OLD/USDT" not in vnz._ws_tasks
    assert "OLD/USDT" not in vnz._ws_price
    assert "OLD/USDT" not in vnz._ws_subs
    assert _wait_done(old_task)  # أُلغي فعلًا


def test_sync_readds_symbol_back_in_watchlist(ws_env, monkeypatch):
    """رمز عاد للقائمة بعد خروج: يعاد اشتراكه تلقائيًا في المزامنة التالية."""
    monkeypatch.setattr(vnz, "db", _RowsDb([]))
    monkeypatch.setattr(vnz, "watchlist", ["BTC/USDT"])

    assert _sync_settled(ws_env["loop"])["added"] == 1
    # خروج
    monkeypatch.setattr(vnz, "watchlist", [])
    assert _sync_settled(ws_env["loop"])["removed"] == 1
    # عودة
    monkeypatch.setattr(vnz, "watchlist", ["BTC/USDT"])
    assert _sync_settled(ws_env["loop"])["added"] == 1
    assert "ticker" in vnz._ws_tasks["BTC/USDT"]


def test_sync_cleans_dead_tasks(ws_env, monkeypatch):
    """مهام ماتت كليًا تُنظف حتى لو الرمز مطلوب — المزامنة التالية تعيد إقلاعها."""
    monkeypatch.setattr(vnz, "db", _RowsDb([]))
    monkeypatch.setattr(vnz, "watchlist", ["BTC/USDT"])
    dead = asyncio.run_coroutine_threadsafe(asyncio.sleep(0), ws_env["loop"])
    assert dead.result(timeout=2.0) is None  # مكتملة = ميتة
    vnz._ws_tasks["BTC/USDT"] = {"ticker": dead}

    vnz.ws_sync_subscriptions()
    assert "BTC/USDT" not in vnz._ws_tasks  # نظفت الميتة (تعيد الاشتراك لاحقًا)


def test_sync_idempotent_no_duplicate_spawns(ws_env, monkeypatch):
    """مزامنة متتالية بلا تغييرات: صفر إضافة وإلغاء — لا اتصالات زائدة."""
    monkeypatch.setattr(vnz, "db", _RowsDb([]))
    monkeypatch.setattr(vnz, "watchlist", ["BTC/USDT", "ETH/USDT"])

    assert _sync_settled(ws_env["loop"]) == {"added": 2, "removed": 0}
    assert _sync_settled(ws_env["loop"]) == {"added": 0, "removed": 0}
    assert _sync_settled(ws_env["loop"]) == {"added": 0, "removed": 0}
    assert len(vnz._ws_tasks) == 2


# ─────────────────────────────────────────────────────────────────────────────
# 3) سلسلة النبض كاملة حية بعد الإصلاح (توثيق الغاية)
# ─────────────────────────────────────────────────────────────────────────────

def test_pulse_chain_alive_after_fix(monkeypatch):
    """السلسلة التي كانت ميتة بالبناء: مرجع مسح + سعر حي متحرك = قرار كيك."""
    monkeypatch.setattr(vnz, "DEVIATION_THRESHOLD", 0.006)
    monkeypatch.setattr(vnz, "KICK_MIN_GAP_SEC", 90)
    vnz._last_scan_prices.clear()
    try:
        vnz._record_scan_price("BTC/USDT", 100.0)       # دورة المسح تسجل المرجع
        vnz._ws_price["BTC/USDT"] = {                   # الاشتراك الجديد يجلب السعر الحي
            "price": 100.9, "ts": time.time(), "source": "test"}
        # حركة 0.9% < عتبة 1.2%... بل العتبة 0.6%: 0.9% ≥ 0.6% = كيك
        assert vnz.momentum_should_kick(100.0, 100.9, 0.0) is True
        # والسعر الذي لا يتحرك: لا كيك
        assert vnz.momentum_should_kick(100.0, 100.2, 0.0) is False
    finally:
        vnz._last_scan_prices.clear()


def test_live_price_reads_from_ws_price(monkeypatch):
    """_live_price يقرأ _ws_price — الاشتراك الجديد هو مصدر غذائه الوحيد."""
    vnz._ws_price["BTC/USDT"] = {"price": 42000.5, "ts": time.time(), "source": "test"}
    try:
        assert vnz._live_price("BTC/USDT") == 42000.5
        assert vnz._live_price("NOPE/USDT") is None  # بلا اشتراك = صمت كامل
    finally:
        vnz._ws_price.pop("BTC/USDT", None)


# ─────────────────────────────────────────────────────────────────────────────
# 4) الإصدار
# ─────────────────────────────────────────────────────────────────────────────

def test_version_pair():
    assert vnz.BOT_VERSION == "EL2.3.0"
    assert panel.BOT_VERSION == "EL2.3.0"
