"""اختبارات FE1.9.5 «الإقلاع مرئي»
====================================
الحادثة الحية التي ولّدت هذا الإصدار (15 أكتوبر 2026، 14:59:44 UTC):
أعادت Render تشغيل العملية بعد نشر FE1.9.4 بـ ~61 دقيقة — كل العدادات
(ok_count/cycles/kicks) وstarted_at للاشتراكات الثلاثين صفرت، واكتشاف
إعادة التشغيل تطلب استدلالًا عكسيًا يدويًا من طوابع started_at.
الإصلاح: /health يكشف boot_at وuptime_sec — أي إعادة تشغيل تُرى فورًا
من نبضة واحدة (قارن boot_at مع time).

ما يُغطيه الملف:
  1) /health يحمل boot_at بصيغة ISO وكامل التاريخ وuptime_sec عددًا ≥ 0
  2) uptime_sec متسق مع boot_at (فرق ≤ ثانيتين من لحظة الطلب)
  3) تزامن الإصدار FE1.9.5 (vnz + panel)

صفر تغيير سلوك: حقلان تشخيصيان جديدان فقط.
"""

import re
from datetime import datetime, timezone

import vnz
import panel


# ─────────────────────────────────────────────────────────────────────────────
# 1) حقول الإقلاع في /health
# ─────────────────────────────────────────────────────────────────────────────

def test_health_exposes_boot_at_and_uptime():
    client = vnz.app.test_client()
    r = client.get("/health")
    assert r.status_code == 200
    body = r.get_json()
    # boot_at: طابع UTC بصيغة %Y-%m-%dT%H:%M:%SZ
    assert isinstance(body["boot_at"], str) and body["boot_at"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", body["boot_at"]), body["boot_at"]
    # uptime_sec: عدد صحيح غير سالب
    assert isinstance(body["uptime_sec"], int) and body["uptime_sec"] >= 0


def test_uptime_consistent_with_boot_at():
    client = vnz.app.test_client()
    body = client.get("/health").get_json()
    boot = datetime.strptime(body["boot_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    now = datetime.strptime(body["time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    delta = (now - boot).total_seconds()
    # تسامح ثانيتين لفرق لحظة الالتقاط بين الحقلين داخل نفس الاستجابة
    assert abs(delta - body["uptime_sec"]) <= 2.0, (delta, body["uptime_sec"])


# ─────────────────────────────────────────────────────────────────────────────
# 2) الإصدار
# ─────────────────────────────────────────────────────────────────────────────

def test_version_pair():
    assert vnz.BOT_VERSION == "EL2.2.0"
    assert panel.BOT_VERSION == "EL2.2.0"
