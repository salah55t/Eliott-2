#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fe187.py — اختبارات FE1.8.7: اقتباس طبقة الاتصال وجلب المعلومات من بوت V9

طلب المستخدم: «اقتبس طريقة الاتصال وجلب المعلومات من بوت v9»

الجذور التي عولجت (من V9.9/V9.20/V9.22 حرفيًا):
  • fibo-elio كان يجلب الشموع من باينانس أولًا (ccxt) بلا أي محاسبة وزن —
    النتيجة الحية: حظر 418/-1003 متكرر (آخرها 13:07Z يوم النشر) يظهر في بطاقة
    اللوحة «فشل الاتصال».
  • V9 عاش شهورًا على نفس عنوان Render المشترك بلا حظرات متكررة لأنه:
    (1) يجلب بيانات السوق من البدائل الخام أولًا (bybit→okx→gate) عبر requests
        بلا ccxt وبلا load_markets، وباينانس احتياط أخير فقط؛
    (2) يحمي كل نداء باينانس بحارس وزن: نافذة دقيقة منزلقة + ميزانية تكيفية
        (خفض 40% عند الحظر، تعافي 8%/3د) + تبريد استئناف + تدرج فاصل ×4؛
    (3) الحظر يُسجل بإلغاء ازدواج (نفس الحظر لا يخفض مرتين).

العقود المختبرة:
  1) حارس الوزن: الحجز المسبق/الخنق/خفض الميزانية/إلغاء الازدواج/التعافي/
     اللقطات/is_banned غير الحاجب/مقدّر وزن الشموع.
  2) المزودون الخام: التطبيع [ts,o,h,l,c,v] من صيغ bybit/okx/gate الخام،
     خرائط الرموز والفريمات، ورفض الصفوف الفاسدة.
  3) التوجيه: البدائل أولًا ← باينانس أخيرًا خلف الحارس، تخطي باينانس أثناء
     الحظر، إشعارات الانتقال FE1.8.6 نفسها، وقاتل الطوارئ DATA_FEED_RAW=0.
  4) بوابات التنفيذ: لا نداء باينانس أثناء الحظر (فحص الاتصال/الأوامر/الحساب).
  5) النشر والحدود المحمية (قائمة 30، سقف 36، rr_net 0.3… بلا مساس).

تشغيل: pytest test_fe187.py -v   (من داخل مجلد المشروع)
"""

import time

import pytest

import vnz
vnz.DASHBOARD_PROTECTED = False  # بيئة الاختبار: بلا مصادقة (نفس عقد test_fe100)


# ─────────────────────────────────────────────────────────────────────────────
# تجهيزات
# ─────────────────────────────────────────────────────────────────────────────

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
def guard(clean_db, monkeypatch):
    """حارس وزن جديد نظيف حول كل اختبار — بلا بقايا حظر بين الاختبارات."""
    g = vnz.BinanceRateGuard(500, 0.0)
    monkeypatch.setattr(vnz, "rate_guard", g)
    return g


def _state(last_error: str = "", cooling: float = 0.0) -> dict:
    return {"ok": 0, "fail": 0, "last_error": last_error, "last_ok_at": None,
            "cooldown_until": time.time() + cooling, "markets_pruned": True}


class _FakeProv:
    """مزود خام وهمي — يرد صفوفًا جاهزة أو يرفع استثناء."""
    def __init__(self, name, rows=None, exc=None, empty=False):
        self.name = name
        self.rows = rows if rows is not None else [[1728900000000 + i * 900000,
                                                    1.0, 1.1, 0.9, 1.05, 10.0]
                                                   for i in range(30)]
        self.exc = exc
        self.empty = empty
        self.calls = 0

    def fetch_klines(self, symbol, interval, limit=300):
        self.calls += 1
        if self.exc:
            raise self.exc
        if self.empty:
            return None
        return self.rows[:max(2, min(limit, len(self.rows)))]


class _FakeBinanceEx:
    """نسخة ccxt باينانس وهمية — publicGetKlines يعمل أو يرفع حسب الإعداد."""
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def publicGetKlines(self, params):
        self.calls += 1
        if self.fail:
            raise RuntimeError('binance 429 Too Many Requests {"code":-1003,"msg":"Way too much request weight"}')
        return [[1728900000000, "1.0", "1.0", "1.0", "1.0", "1.0"]] * 30


@pytest.fixture()
def raw_world(clean_db, monkeypatch):
    """عالم الطبقة الخام: حارس نظيف + مزودون وهميون + باينانس وهمي + حالة معزولة."""
    g = vnz.BinanceRateGuard(500, 0.0)
    monkeypatch.setattr(vnz, "rate_guard", g)
    monkeypatch.setattr(vnz, "provider_state",
                        {"binance": _state(), "bybit": _state(),
                         "okx": _state(), "gate": _state()})
    monkeypatch.setattr(vnz, "active_source", {"name": None, "since": None})
    monkeypatch.setattr(vnz, "DATA_FEED_RAW", True)
    monkeypatch.setattr(vnz, "prune_markets", lambda ex: 0)
    bybit = _FakeProv("bybit")
    okx = _FakeProv("okx")
    gate = _FakeProv("gate")
    binex = _FakeBinanceEx()
    monkeypatch.setattr(vnz, "RAW_PROVIDERS", [bybit, okx, gate])
    monkeypatch.setattr(vnz, "EXCHANGES", {"binance": binex})
    return {"bybit": bybit, "okx": okx, "gate": gate, "binance": binex,
            "guard": g}


def _notif_n(like: str) -> int:
    rows = vnz.db.query(
        "SELECT COUNT(*) AS n FROM notifications WHERE message LIKE %s", (f"%{like}%",))
    return int(rows[0]["n"]) if rows else 0


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 1 — عقد حارس الوزن (اقتباس V9.9.1)
# ─────────────────────────────────────────────────────────────────────────────

class TestRateGuard:

    def test_acquire_under_budget_instant(self, guard):
        # حجز عادي يسجل الوزن في النافذة ويزيد عداد الطلبات
        guard.acquire(2)
        guard.acquire(1)
        assert guard.used_weight() == 3
        assert guard.total_requests == 2
        assert not guard.is_banned()

    def test_acquire_throttles_over_budget(self, guard, monkeypatch):
        # تجاوز الميزانية → خنق (نوم خارج القفل) حتى تنزاح النافذة
        slept = []
        monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
        guard.acquire(499)
        guard.acquire(2)  # 499+2 > 500 → انتظار
        assert slept, "يجب الخنق عند تجاوز الميزانية"
        assert guard.total_throttled_sec > 0

    def test_new_ban_shrinks_budget_40pct(self, guard):
        # حظر جديد → عدّاد + خفض ميزانية 40% حتى الأرضية (500→300)
        assert guard.budget == 500
        guard.register_ban()
        assert guard.ban_count == 1
        assert guard.budget == 300
        assert guard.is_banned()

    def test_long_ban_drops_to_floor(self, guard):
        # حظر طويل (>600ث) → الميزانية للأرضية مباشرة + تبريد استئناف ممتد
        guard.register_ban(int(time.time() * 1000) + 900_000)
        assert guard.budget == guard.budget_floor
        assert guard._active_cooldown == min(300, guard.resume_cooldown * 2)

    def test_same_ban_dedup_no_double_shrink(self, guard):
        # [V9.15.1] نفس الحظر الساري → تمديد فقط بلا عدّاد ولا خفض إضافي
        until = int(time.time() * 1000) + 60_000
        guard.register_ban(until)
        assert guard.ban_count == 1
        assert guard.budget == 300
        guard.register_ban(until)            # نفس الحظر
        guard.register_ban(until + 30_000)   # تمديد طفيف (<60ث)
        assert guard.ban_count == 1
        assert guard.budget == 300

    def test_escalated_ban_counts_new(self, guard):
        # حظر جديد أطول فعليًا (+120ث) → عدّاد جديد وخفض إضافي (إلى الأرضية)
        guard.register_ban(int(time.time() * 1000) + 60_000)
        guard.register_ban(int(time.time() * 1000) + 180_000)
        assert guard.ban_count == 2

    def test_budget_recovers_8pct_every_3min(self, guard):
        # [V9.9] التعافي: +8% كل 3 دقائق نظيفة حتى المستوى المُعدّ
        guard.register_ban()
        assert guard.budget == 300
        guard._last_ban_ts = time.time() - 181.0
        guard._maybe_recover(time.time())
        assert guard.budget == min(500, int(300 * 1.08) + 1)

    def test_recovery_does_not_exceed_configured(self, guard):
        guard.budget = 498
        guard._last_recover_ts = time.time() - 181.0
        guard._maybe_recover(time.time())
        assert guard.budget == 500  # سقف = المستوى المُعدّ

    def test_is_banned_and_remaining(self, guard):
        assert guard.ban_remaining_sec() == 0
        guard.register_ban(fallback_sec=100.0)
        assert guard.is_banned()
        rem = guard.ban_remaining_sec()
        assert 185 <= rem <= 200  # بقيّة الحظر (105) + تبريد الاستئناف (90) — عقد V9

    def test_ban_from_error_parses_until(self, guard):
        # نص باينانس الحقيقي يحمل موعد الانتهاء («banned until 1799999999999»)
        future_ms = int(time.time() * 1000) + 120_000
        guard.register_ban_from_error(RuntimeError(f"IP banned until {future_ms}"))
        assert guard.banned_until == pytest.approx(future_ms / 1000.0 + 5.0, abs=2.0)

    def test_ban_from_error_fallback(self, guard):
        # خطأ 429 بلا موعد صريح → تبريد احتياطي 120ث
        guard.register_ban_from_error(RuntimeError('{"code":-1003,"msg":"Too many requests"}'))
        assert guard.is_banned()
        assert guard.banned_until - time.time() == pytest.approx(125.0, abs=3.0)

    def test_resume_wait_activates_ramp_once(self, guard):
        # لحظة الاستئناف (انتهى الحظر وتجاوز تبريد الاستئناف): التدرج ×4 يُفعّل مرة واحدة فقط
        guard.banned_until = time.time() - 100.0  # الحظر انتهى قبل 100ث
        guard._active_cooldown = 90               # والتبريد انقضى أيضًا
        guard._effective_resume_wait(time.time())
        assert guard._resumed is True
        assert guard._ramp_until > time.time()
        first = guard._ramp_until
        guard._effective_resume_wait(time.time())
        assert guard._ramp_until == first  # لا إعادة تفعيل

    def test_resume_wait_holds_during_cooldown(self, guard):
        # انتهى الحظر لكن تبريد الاستئناف (90ث) ما زال يمنع — لا انفجار خيوط فوري
        guard.banned_until = time.time() + 0.05
        wait = guard._effective_resume_wait(time.time() + 0.2)
        assert wait > 0
        assert guard._resumed is False  # الاستئناف لم يبدأ بعد

    def test_snapshot_contract(self, guard):
        guard.acquire(5)
        snap = guard.snapshot()
        for k in ("used_weight_last_min", "budget_per_min", "configured_budget",
                  "banned_until", "banned", "banned_until_iso", "ban_remaining_sec",
                  "ban_count", "last_error", "total_requests", "throttled_sec_rounded"):
            assert k in snap, f"مفتاح اللقطة مفقود: {k}"
        assert snap["banned"] is False
        assert snap["banned_until_iso"] is None
        assert snap["used_weight_last_min"] == 5


class TestRateErrorAndWeight:

    def test_is_rate_error_variants(self):
        assert vnz._is_rate_error(RuntimeError('{"code":-1003}'))
        assert vnz._is_rate_error(RuntimeError("error -1015"))
        assert vnz._is_rate_error(RuntimeError("HTTP 418 banned until 1799999"))
        assert vnz._is_rate_error(RuntimeError("HTTP 429 Too many requests"))
        assert vnz._is_rate_error(RuntimeError("Way too much request weight"))
        assert not vnz._is_rate_error(RuntimeError("connection timeout"))

    def test_klines_weight_tiers(self):
        assert vnz._bin_klines_weight(50) == 1
        assert vnz._bin_klines_weight(100) == 1
        assert vnz._bin_klines_weight(101) == 2
        assert vnz._bin_klines_weight(200) == 2   # المسح 200
        assert vnz._bin_klines_weight(500) == 2   # الإشارة 500
        assert vnz._bin_klines_weight(501) == 5
        assert vnz._bin_klines_weight(1000) == 5
        assert vnz._bin_klines_weight(2000) == 5
        assert vnz._bin_klines_weight("x") == 5


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 2 — المزودون الخام: التطبيع إلى [ts,o,h,l,c,v]
# ─────────────────────────────────────────────────────────────────────────────

class TestRawProviders:

    def test_binance_row_valid_and_invalid(self):
        row = vnz.RawDataProvider._binance_row(1728900000000, "1.0", "1.1", "0.9", "1.05", "10")
        assert row == [1728900000000, 1.0, 1.1, 0.9, 1.05, 10.0]
        assert vnz.RawDataProvider._binance_row(0, 1, 1, 1, 1, 1) is None          # طابع صفر
        assert vnz.RawDataProvider._binance_row("x", 1, 1, 1, 1, 1) is None        # طابع فاسد
        assert vnz.RawDataProvider._binance_row(1728900000000, -1, 1, 1, 1, 1) is None  # سعر سالب
        assert vnz.RawDataProvider._binance_row(1728900000000, 1, 1, 1, None, 1) is None
        r = vnz.RawDataProvider._binance_row(1728900000000, 1, 1, 1, 1, None)      # حجم غائب → 0.0
        assert r[5] == 0.0

    def test_bybit_symbol_map(self):
        p = vnz.BybitRawProvider()
        assert p.to_symbol("BTC/USDT") == "BTCUSDT"
        assert p.to_symbol("BTCUSDT") == "BTCUSDT"
        assert p.to_symbol("BTC/BTC") is None
        assert p.to_symbol("USDT") is None  # أقصر من الحد

    def test_bybit_fetch_normalizes(self, monkeypatch):
        p = vnz.BybitRawProvider()
        calls = []
        payload = {"retCode": 0, "result": {"list": [
            ["1728900090000", "2", "3", "1", "2.5", "20", "45"],   # الأحدث أولًا (bybit)
            ["1728900000000", "1", "2", "0.5", "1.9", "10", "19"],
        ]}}

        def fake_get(path, params=None):
            calls.append((path, dict(params or {})))
            return payload

        monkeypatch.setattr(p, "_get_json", fake_get)
        rows = p.fetch_klines("BTC/USDT", "15m", 100)
        assert calls[0][0] == "/v5/market/kline"
        assert calls[0][1]["symbol"] == "BTCUSDT"
        assert calls[0][1]["interval"] == "15"
        assert calls[0][1]["category"] == "spot"
        # ترتيب زمني تصاعدي + 6 أعمدة فقط
        assert [r[0] for r in rows] == [1728900000000, 1728900090000]
        assert rows[1] == [1728900090000, 2.0, 3.0, 1.0, 2.5, 20.0]

    def test_bybit_fetch_error_returns_none(self, monkeypatch):
        p = vnz.BybitRawProvider()
        monkeypatch.setattr(p, "_get_json", lambda path, params=None: {"retCode": 10001, "retMsg": "err"})
        assert p.fetch_klines("BTC/USDT", "15m", 100) is None
        monkeypatch.setattr(p, "_get_json", lambda path, params=None: None)
        assert p.fetch_klines("BTC/USDT", "15m", 100) is None

    def test_bybit_unsupported_interval(self):
        p = vnz.BybitRawProvider()
        assert p.fetch_klines("BTC/USDT", "7m", 100) is None  # فريم غير موجود في الخريطة

    def test_okx_symbol_map_and_normalizes(self, monkeypatch):
        p = vnz.OKXRawProvider()
        assert p.to_symbol("BTC/USDT") == "BTC-USDT"
        payload = {"code": "0", "data": [
            ["1728900090000", "2", "3", "1", "2.5", "20", "25", "45", "1"],
            ["1728900000000", "1", "2", "0.5", "1.9", "10", "11", "19", "1"],
        ]}
        monkeypatch.setattr(p, "_get_json", lambda path, params=None: payload if path == "/api/v5/market/candles" else None)
        rows = p.fetch_klines("ETH/USDT", "1d", 50)
        assert [r[0] for r in rows] == [1728900000000, 1728900090000]
        assert rows[0] == [1728900000000, 1.0, 2.0, 0.5, 1.9, 10.0]

    def test_okx_bad_code_returns_none(self, monkeypatch):
        p = vnz.OKXRawProvider()
        monkeypatch.setattr(p, "_get_json", lambda path, params=None: {"code": "50011"})
        assert p.fetch_klines("BTC/USDT", "15m", 100) is None

    def test_gate_symbol_map_and_list_format(self, monkeypatch):
        p = vnz.GateRawProvider()
        assert p.to_symbol("BTC/USDT") == "BTC_USDT"
        # الصيغة الفعلية: [t(ث), quote_vol, o, c, h, l, base_vol, done]
        payload = [
            ["1728900090", "45", "2", "2.5", "3", "1", "20", "true"],
            ["1728900000", "19", "1", "1.9", "2", "0.5", "10", "true"],
        ]
        monkeypatch.setattr(p, "_get_json", lambda path, params=None: payload)
        rows = p.fetch_klines("BTC/USDT", "15m", 50)
        # ثوانٍ ← ميلي ثانية، والترتيب o,c,h,l من المواضع 2..5
        assert rows[0] == [1728900000000, 1.0, 2.0, 0.5, 1.9, 10.0]
        assert rows[1] == [1728900090000, 2.0, 3.0, 1.0, 2.5, 20.0]

    def test_gate_object_format_fallback(self, monkeypatch):
        p = vnz.GateRawProvider()
        payload = [{"time": 1728900000, "open": "1", "high": "2", "low": "0.5",
                    "close": "1.9", "volume": "10", "sum": "19"}]
        monkeypatch.setattr(p, "_get_json", lambda path, params=None: payload)
        rows = p.fetch_klines("BTC/USDT", "15m", 50)
        assert rows == [[1728900000000, 1.0, 2.0, 0.5, 1.9, 10.0]]

    def test_interval_support_matrix(self):
        bybit, okx, gate = vnz.BybitRawProvider(), vnz.OKXRawProvider(), vnz.GateRawProvider()
        for p in (bybit, okx, gate):
            assert p.supports("BTC/USDT", "15m")   # فريم الكشف
            assert p.supports("BTC/USDT", "1d")    # فريم التحيز الأعلى
        assert not gate.supports("BTC/USDT", "3m")  # Gate لا يدعم 3m — تُتخطى تلقائيًا

    def test_registry_and_default_order(self):
        assert [p.name for p in vnz.RAW_PROVIDERS] == ["bybit", "okx", "gate"]
        assert vnz.DATA_FEED_ORDER == ["bybit", "okx", "gate"]


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 3 — توجيه الجلب: البدائل أولًا ← باينانس أخيرًا خلف الحارس
# ─────────────────────────────────────────────────────────────────────────────

class TestFetchRouting:

    def test_alternates_first_binance_not_touched(self, raw_world):
        # طريق V9: bybit يخدم فورًا — باينانس صفر نداءات
        raw, src = vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 200)
        assert src == "bybit"
        assert len(raw) >= 2
        assert raw_world["binance"].calls == 0
        assert raw_world["guard"].total_requests == 0  # باينانس لم يُلمس إطلاقًا
        assert vnz.active_source["name"] == "bybit"

    def test_first_boot_provider_notifies(self, raw_world):
        # نفس عقد FE1.8.6: أول مزود ناجح منذ الإقلاع → إشعار info
        vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 200)
        assert _notif_n("مزود البيانات الفعّال منذ الإقلاع: BYBIT") == 1

    def test_failover_to_next_alternate(self, raw_world):
        # bybit يفشل ← okx يخدم — باينانس ما زال صفرًا
        raw_world["bybit"].exc = RuntimeError("bybit down")
        raw, src = vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 200)
        assert src == "okx"
        assert raw_world["bybit"].calls == 1
        assert raw_world["binance"].calls == 0

    def test_transition_notification(self, raw_world):
        # [تصحيح حي 14:29Z] التدوير بين البدائل طبيعي في الطبقة الخام — بلا إشعار انتقال
        # (5 إشعارات/26ث حيًا كانت ضجيجًا يدفس الأحداث الحقيقية) — الحالة تتحرك بصمت
        vnz.active_source["name"] = "bybit"
        raw_world["bybit"].exc = RuntimeError("bybit down hard")
        vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 200)
        assert vnz.active_source["name"] == "okx"  # التدوير يحدث فعلًا
        assert _notif_n("فشل مزود البيانات BYBIT — الانتقال إلى OKX") == 0

    def test_provider_cooldown_after_threshold_notifies_once(self, raw_world):
        # بلوغ العتبة (4 متتالية) = انقطاع فعلي ← إشعار تبريد واحد وليس لكل رمز
        raw_world["bybit"].empty = True
        for _ in range(4):
            vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 200)
        assert _notif_n("تبريد مزود البيانات BYBIT لمدة 300ث بعد 4 فشلات متتالية") == 1
        for _ in range(3):  # المزيد من الفشل أثناء التبريد؟ لا — المبرد يُتخطى بلا نداء
            vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 200)
        assert _notif_n("تبريد مزود البيانات BYBIT") == 1  # بلا تكرار

    def test_cooled_provider_skipped(self, raw_world):
        # المزود المبرد يُتخطى بلا نداء
        vnz.provider_state["bybit"]["cooldown_until"] = time.time() + 9999
        raw, src = vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 200)
        assert src == "okx"
        assert raw_world["bybit"].calls == 0

    def test_empty_rows_count_as_fail_and_move_on(self, raw_world):
        # استجابة فارغة = عدّاد متتالٍ بلا تبريد فوري [V9] — ثم المزود التالي
        raw_world["bybit"].empty = True
        raw, src = vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 200)
        assert src == "okx"
        st = vnz.provider_state["bybit"]
        assert st["fail"] == 1
        assert "فارغة/غير متاحة" in st["last_error"]
        assert st["consec_fail"] == 1
        assert st["cooldown_until"] <= time.time(), "رمز غير مدعوم لا يحبس المزود كله"

    def test_soft_fail_threshold_cooldowns_after_4(self, raw_world):
        # [V9] عتبة الفشل المتتالي: 4 فشلات متتالية (بلا نجاح يقطعها) ← تبريد 5د
        raw_world["bybit"].empty = True
        for _ in range(4):
            vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 200)  # bybit يفشل، okx يخدم
        st = vnz.provider_state["bybit"]
        assert st["fail"] == 4
        assert st["cooldown_until"] > time.time(), "العتبة (4) تفعّل التبريد"
        # المحاولة الخامسة تتخطى bybit المبرد — بلا نداء خامس
        vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 200)
        assert raw_world["bybit"].calls == 4

    def test_success_resets_consec_fail_chain(self, raw_world):
        # نجاح واحد يقطع سلسلة الفشل — لا تتراكم فشلات متباعدة على التبريد
        raw_world["bybit"].empty = True
        for _ in range(3):
            vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 200)
        raw_world["bybit"].empty = False  # رمز مدعوم مرة أخرى
        vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 200)
        assert vnz.provider_state["bybit"]["consec_fail"] == 0
        raw_world["bybit"].empty = True
        vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 200)
        st = vnz.provider_state["bybit"]
        assert st["consec_fail"] == 1 and st["cooldown_until"] <= time.time()  # سلسلة جديدة من الصفر

    def test_all_alternates_fail_binance_serves_rate_guarded(self, raw_world):
        # فشل الجميع ← باينانس أخيرًا عبر حارس الوزن (وزن الشموع محسوب مسبقًا)
        # bybit كان يخدم قبل هذا النداء (الانتقال يعكس تعاقب FE1.8.6 نفسه)
        vnz.active_source["name"] = "bybit"
        for p in (raw_world["bybit"], raw_world["okx"], raw_world["gate"]):
            p.empty = True
        raw, src = vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 200)
        assert src == "binance"
        assert len(raw) == 30
        assert raw_world["binance"].calls == 1
        assert raw_world["guard"].total_requests == 1  # الحجز المسبق تم
        # عودة الأساسي (binance أول DATA_PROVIDERS) → إشعار العودة بنفس عقد FE1.8.6
        assert _notif_n("عاد مزود البيانات الأساسي BINANCE") == 1

    def test_binance_rate_error_registers_ban(self, raw_world):
        # 429/-1003 من باينانس ← الحظر يُسجل بإلغاء الازدواج + يصل السجل (لا صمت)
        for p in (raw_world["bybit"], raw_world["okx"], raw_world["gate"]):
            p.empty = True
        raw_world["binance"].fail = True
        raw, src = vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 200)
        assert src is None and raw is None
        g = raw_world["guard"]
        assert g.ban_count == 1
        assert g.is_banned()
        assert "-1003" in g.last_error or "429" in g.last_error
        assert _notif_n("حظر وزن باينانس") == 1
        st = vnz.provider_state["binance"]
        assert st["fail"] == 1 and st["cooldown_until"] > time.time()

    def test_banned_binance_skipped_entirely(self, raw_world):
        # أثناء حظر ساري: باينانس يُتخطى فورًا (فحص غير حاجب) — لا نداءات ولا انتظار
        raw_world["guard"].register_ban(fallback_sec=300.0)
        for p in (raw_world["bybit"], raw_world["okx"], raw_world["gate"]):
            p.empty = True
        raw, src = vnz.fetch_ohlcv_raw("BTC/USDT", "15m", 200)
        assert src is None and raw is None
        assert raw_world["binance"].calls == 0

    def test_kill_switch_returns_legacy_path(self, raw_world, monkeypatch):
        # DATA_FEED_RAW=0 → قاتل الطوارئ: المسار القديم ccxt كما في FE1.0.1
        monkeypatch.setattr(vnz, "DATA_FEED_RAW", False)
        sentinel = ([[1, 1.0, 1.0, 1.0, 1.0, 1.0]], "legacy")
        seen = {}

        def fake_legacy(symbol, timeframe, limit):
            seen["args"] = (symbol, timeframe, limit)
            return sentinel

        monkeypatch.setattr(vnz, "_fetch_ohlcv_ccxt", fake_legacy)
        out = vnz.fetch_ohlcv_raw("ETH/USDT", "15m", 500)
        assert out == sentinel
        assert seen["args"] == ("ETH/USDT", "15m", 500)
        assert raw_world["bybit"].calls == 0


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 4 — بوابات التنفيذ والحالة: لا نداء باينانس أثناء الحظر
# ─────────────────────────────────────────────────────────────────────────────

class TestRestGates:

    def test_status_snapshot_during_ban(self, clean_db, guard, monkeypatch):
        # الحظر يمنع الـ ping: البطاقة تعرض بقيّة الحظر بلا أي نداء شبكي
        vnz._bin_status_cache.update({"ts": 0.0, "data": None, "last_connected": None, "last_notify": 0.0})
        guard.register_ban(fallback_sec=300.0)
        probe_calls = []

        class _Probe:
            def fetch_time(self):
                probe_calls.append(1)
                return 1728900000000

        monkeypatch.setattr(vnz, "_binance_public_probe", lambda: _Probe())
        data = vnz.binance_status_snapshot(force=True)
        assert data["connected"] is False
        assert "حظر وزن باينانس ساري" in (data["error"] or "")
        assert probe_calls == []
        assert _notif_n("فشل اتصال باينانس") == 1  # عقد FE1.8.6/1.8.5: الفشل يصل السجل
        vnz._bin_status_cache.update({"ts": 0.0, "data": None, "last_connected": None, "last_notify": 0.0})

    def test_real_order_blocked_during_ban(self, clean_db, guard, monkeypatch):
        # أمر شراء حقيقي أثناء الحظر → يُلغى بالبوابة ويصل السجل (لا ضرب باينانس أثناءه)
        guard.register_ban(fallback_sec=300.0)

        class _Ex:
            def privatePostOrder(self, params):
                raise AssertionError("لا يجوز النداء أثناء الحظر")

        monkeypatch.setattr(vnz, "binance_trade_exchange", lambda: _Ex())
        out = vnz.place_real_limit_buy("BTC/USDT", 50000.0, 0.001)
        assert out is None
        assert _notif_n("فشل أمر الشراء الحقيقي") == 1
        assert _notif_n("حظر وزن باينانس ساري") == 1

    def test_real_account_gated(self, clean_db, guard):
        # قراءة الحساب تمر عبر الحجز المسبق (وزن 10)
        calls = []

        class _Ex:
            def privateGetAccount(self):
                calls.append(1)
                return {"balances": [{"asset": "USDT", "free": "5.0", "locked": "0.0"}]}

        acc = vnz._real_account(_Ex())
        assert acc["balances"][0]["asset"] == "USDT"
        assert guard.total_requests == 1

    def test_market_rules_fail_open_during_ban(self, clean_db, guard):
        # قواعد السوق أثناء الحظر: الكاش يخدم إن وُجد وإلا {} (fail-open كما في الأصل)
        guard.register_ban(fallback_sec=300.0)
        assert vnz.real_market_rules("BTC/USDT") == {}


# ─────────────────────────────────────────────────────────────────────────────
# الجولة 5 — النشر والحدود المحمية (بلا مساس)
# ─────────────────────────────────────────────────────────────────────────────

class TestDeploymentAndBoundaries:

    def test_version_bumped_everywhere(self):
        import panel
        assert vnz.BOT_VERSION == "EL2.2.0"
        assert panel.BOT_VERSION == "EL2.2.0"

    def test_render_yaml_carries_v9_layer_keys(self):
        with open("render.yaml", "r", encoding="utf-8") as fh:
            content = fh.read()
        for key, val in (("DATA_FEED_RAW", '"1"'),
                         ("DATA_FEED_ORDER", '"bybit,okx,gate"'),
                         ("DATA_FEED_TIMEOUT_SEC", '"8"'),
                         ("DATA_FEED_FAIL_THRESHOLD", '"4"'),
                         ("DATA_FEED_COOLDOWN_SEC", '"300"'),
                         ("RATE_LIMIT_BUDGET_PER_MIN", '"500"'),
                         ("API_MIN_SPACING_SEC", '"0.15"'),
                         ("BAN_RESUME_COOLDOWN_SEC", '"90"'),
                         ("BAN_RESUME_RAMP_SEC", '"120"'),
                         ("BAN_LONG_THRESHOLD_SEC", '"600"')):
            assert f"- key: {key}" in content, f"مفتاح ناقص في render.yaml: {key}"
            assert f"value: {val}" in content, f"قيمة ناقصة لـ{key} في render.yaml"

    def test_v9_layer_defaults(self):
        assert vnz.DATA_FEED_RAW is True
        assert vnz.DATA_FEED_TIMEOUT_SEC == 8.0
        assert vnz.DATA_FEED_FAIL_THRESHOLD == 4
        assert vnz.DATA_FEED_COOLDOWN_SEC == 300.0
        assert vnz.RATE_LIMIT_BUDGET_PER_MIN == 500
        assert vnz.API_MIN_SPACING_SEC == 0.15
        assert vnz.BAN_RESUME_COOLDOWN_SEC == 90
        assert vnz.BAN_RESUME_RAMP_SEC == 120
        assert vnz.BAN_LONG_THRESHOLD_SEC == 600

    def test_execution_precision_pinned_to_binance(self, monkeypatch):
        # [FE1.8.7] دقة الكميات تتبع منصة التنفيذ (باينانس) لا مزود الشموع
        sentinel = object()
        monkeypatch.setattr(vnz, "EXCHANGES", {"binance": sentinel})
        assert vnz.current_exchange() is sentinel

    def test_api_all_exposes_rate_guard(self, clean_db, monkeypatch):
        # /api/all يحمّل لقطة الحارس للبطاقة الجديدة
        monkeypatch.setattr(vnz, "binance_status_snapshot",
                            lambda force=False: {"connected": True, "latency_ms": 100,
                                                 "keys_present": False, "testnet": False,
                                                 "usdt_free": None, "usdt_total": None,
                                                 "can_trade": None, "error": None,
                                                 "checked_at": "2026-10-14T00:00:00Z"})
        client = vnz.app.test_client()
        resp = client.get("/api/all")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "rate_guard" in body
        assert body["rate_guard"]["budget_per_min"] >= 400
        assert body["rate_guard"]["banned"] is False

    def test_protected_boundaries_untouched(self):
        # الحراسات المحمية من FE1.7.0→1.8.5 لم تُمس في الاقتباس
        assert vnz.SCAN_TOP_N == 30
        assert vnz.MAX_STRUCTURE_AGE_BARS == 36
        assert vnz.RR_NET_MIN == 0.3
        assert vnz.MAX_ENTRY_DISTANCE_PCT == 1.5
        assert vnz.SYMBOL_COOLDOWN_SEC == 5400
        assert vnz.KEEP_ALIVE_INTERVAL_SEC == 60.0
        assert vnz.PENDING_MAX_CANDLES == 6
        assert vnz.CLUSTER_MAX_SAME_DIRECTION == 3
