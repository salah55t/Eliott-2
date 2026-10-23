#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
panel.py — لوحة تحكم Fibo-Elio السبرانية (عربية RTL، نيون مشع على أسود متحرك)
[FE1.4.0] إعادة تصميم بأسلوب منصات الهكر: خلفية سوداء متحركة (شبكة + هالات نيون
نابضة + خطوط مسح)، ألوان نيون مشعة بتوهج، خط Orbitron/Share Tech Mono.
[FE1.5.0] قسم «فحص أزواج باينانس (الكون الكامل)»: جدول درجات الملاءمة
للاستراتيجية + زر «فحص الآن» + بطاقة حالة الفحص.
[FE1.5.0] إصلاحات مراجعة اللوحة الحية: تهريب HTML (esc) لكل بيانات API (كان
innerHTML مكشوفًا على XSS مخزّن عبر رسائل الإشعارات)، جداول مغلقة/التقاطات/الفحص
ضمن .tbl-wrap (كانت تفيض على الموبايل بلا تمرير)، عارضة مستقلة لكل قسم (كان خطأ
واحد يجمّد تحديث اللوحة كاملة صامتًا)، usd/cls آمنة ضد null، حارس تكرار refresh
+ إيقاف عند إخفاء التبويب، لا اختطاف مفتاح التداول الحقيقي أثناء الطلب الجاري.
[FE1.9.13] «اللمسة الفنية»: إعادة تشطيب بصري كامل بأسلوب Neo-Glass Terminal — CSS خالص صفر مكتبات (حمية الذاكرة سليمة) وصفر تغيير في أي منطق بيانات: شفق قطبي طافٍ + نجوم متلألئة + فينييت سينمائي خلف الشبكة القديمة، شعار يطفو وعنوان بتدرج منساب (background-clip:text) بخط كوفي عربي للعناوين، بطاقات زجاجية بلمعان قُطري عند التحويم ودخول طافٍ، حد شعاعي دوّار حول الشارت (اتجاه الحدود المتحركة الحديث)، وميض القيم عند تغيّرها بمراقب MutationObserver عرضي، أشرطة تقدم بلمعان مستمر، نقطة حيوية بحلقة نبض، صفوف جداول بتدرج تحويم ودخول متدرج، حبوب حالات بتدرجات زجاجية، أزرار بلمعان يمسحها عند التحويم، أشرطة تمرير نيون، توست يطفو، حالات فراغ تتنفس، وإتاحة prefers-reduced-motion. كل الأصناف والمعرفات والدوال القديمة كما هي.
[FE1.9.12] «موجات المحرك»: طبقة مؤشر جديدة على الشارت تحسب بمنطق الاستراتيجية حرفيًا
عبر /api/ew_strategy — زيجزاج الكاشف ذاته (عتبة انعكاس 0.6% على الإغلاق) والبنية P0–P5
بقواعد wave_validator الثلاث ومنطقة الدخول 0.382×W3 والوقف P0−0.1% وسلّم الأهداف
المقصوص على قمة الأسبوع TP1→TP3 ومفاتيح فيبو W2/W4/W3 الكانونية — تُرسم خط زيجزاج
عنبري وشارات 0–5 وخطوط استراتيجية كاملة مع سطر حكم عربي. زرها: «موجات المحرك
(الاستراتيجية)»، وبإمكان المستخدم إبقاء طبقة LuxAlgo الموازية أو إيقافها.
[FE1.9.11] مؤشر «موجات إليوت (LuxAlgo)» على الشارت الحي: نقل حرفي لمنطق مؤشر
Elliott Wave [LuxAlgo] (Pine v5 — © LuxAlgo، CC BY-NC-SA 4.0 مع الإسناد) من
static/elliott-wave.js (/ew.js): زيجزاج بثلاثة أطوال (4/8/16) من المحاور المؤكدة،
كشف الدافع 12345 وتصحيح ABC، شارات (1)..(5)/(a)(b)(c)، خطوط فيبو 0.5–0.854 من نهاية
الموجة 5 (تُلغى فوق تصحيح مكتمل وتنقّط عند الكسر)، صندوق التصحيح وعلامة كسره —
الحساب كله في متصفح المستخدم من نفس شموع /api/klines (صفر حمل على الخادم) مع زر
تشغيل/إيقاف وتلخيص حالة أطول نمط تحت الشارت.
[FE1.9.10] قسم «الشارت الحي»: شموع فريم التنفيذ عبر TradingView Lightweight
Charts v5.2.1 (Apache-2.0 — يُقدَّم محليًا من /lwc.js بلا CDN خارجي) يُغذى من
/api/klines (كاش Postgres + الشمعة الجارية الحية) مع خطوط مرجعية (دخول/وقف/
الأهداف المتدرجة/سقف الأسبوع) وعلامات الملء/الغلق، والنقر على رمز أي صفقة يعرضه.
تعرض أيضًا: بطاقة اتصال باينانس الحية، زر التداول الحقيقي (مثل V9)، الحالة
الورقية، الصفقات المفتوحة/المعلقة بتتبع حي وفرز حقيقية/ورقية، إغلاق/إلغاء يدوي،
المغلقة، التقاطات الموجات، الإشعارات، شارة مصدر كل سعر (⚡WS/REST)، البقاء الحي
والذاكرة.
"""

BOT_VERSION = "EL2.2.0"

PANEL_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fibo-Elio — إليوت + فيبوناتشي</title>
<style>
  /* [FE1.9.13] «اللمسة الفنية» — نظام تصميم Neo-Glass Terminal: زجاج مصنفر + حدود شعاعية
     متحركة (اتجاه shadcn/aceternity الحديث) + شفق ونجوم متلألئة + وميض قيم حي — كل ذلك
     CSS خالص بلا أي مكتبة أو CDN إضافي (حمية ذاكرة 512MB سليمة) وعلى نفس كل الأصناف القديمة. */
  @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Share+Tech+Mono&family=Noto+Kufi+Arabic:wght@500;700;800&display=swap');
  :root {
    --bg:#010104; --panel:rgba(2,14,11,.78); --panel2:rgba(0,9,14,.82);
    --line:rgba(0,255,156,.22); --line2:rgba(0,229,255,.16);
    --neon:#00ff9c; --cyan:#00e5ff; --mag:#ff2bd6; --yel:#ffe600; --red:#ff3355; --vio:#b026ff;
    --txt:#c9f7e5; --mut:#5f8a80;
    --kufi:'Noto Kufi Arabic','Segoe UI',Tahoma,sans-serif;
  }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:var(--bg); color:var(--txt); font-family:'Segoe UI',Tahoma,Arial,sans-serif;
         padding:18px; overflow-x:hidden; min-height:100vh; }
  ::selection { background:rgba(0,255,156,.35); color:#fff; }
  :focus-visible { outline:2px solid rgba(0,229,255,.75); outline-offset:2px; border-radius:6px; }
  /* أشرطة تمرير نيون رفيعة (Webkit + Firefox) */
  ::-webkit-scrollbar { width:10px; height:10px; }
  ::-webkit-scrollbar-track { background:rgba(0,0,0,.4); }
  ::-webkit-scrollbar-thumb { background:linear-gradient(180deg,rgba(0,255,156,.5),rgba(0,229,255,.5));
    border-radius:999px; border:2px solid rgba(0,0,0,.4); }
  ::-webkit-scrollbar-thumb:hover { background:linear-gradient(180deg,rgba(0,255,156,.75),rgba(0,229,255,.75)); }
  * { scrollbar-width:thin; scrollbar-color:rgba(0,255,156,.45) rgba(0,0,0,.35); }
  /* ── الخلفية السوداء المتحركة: شبكة نيون + هالات نيون نابضة + خطوط مسح ── */
  .bg-grid { position:fixed; inset:0; z-index:-3;
    background-image:linear-gradient(rgba(0,255,156,.06) 1px,transparent 1px),
                     linear-gradient(90deg,rgba(0,255,156,.06) 1px,transparent 1px);
    background-size:44px 44px;
    animation:gridmove 14s linear infinite;
    -webkit-mask-image:radial-gradient(ellipse at 50% 0%,#000 25%,transparent 78%);
    mask-image:radial-gradient(ellipse at 50% 0%,#000 25%,transparent 78%); }
  @keyframes gridmove { from{background-position:0 0} to{background-position:0 44px} }
  /* [FE1.9.13] شفق قطبي طافٍ خلف الشبكة — عمق سينمائي بلا تكلفة */
  .aurora { position:fixed; top:-32vh; right:-18vw; width:74vw; height:64vh; z-index:-4; pointer-events:none;
    background:conic-gradient(from 200deg at 50% 50%, rgba(0,255,156,.10), rgba(0,229,255,.09) 25%,
               rgba(176,38,255,.09) 50%, rgba(255,43,214,.06) 70%, rgba(0,255,156,.10));
    border-radius:50%; filter:blur(85px); opacity:.6;
    animation:aurorafloat 26s ease-in-out infinite alternate; }
  @keyframes aurorafloat {
    from{ transform:translate(0,0) rotate(0deg) scale(1); }
    to{ transform:translate(-9vw,7vh) rotate(28deg) scale(1.18); } }
  /* [FE1.9.13] نجوم متلألئة — طبقات radial متكررة، بلا أي JS */
  .stars { position:fixed; inset:0; z-index:-2; pointer-events:none; opacity:.6;
    background-image:
      radial-gradient(1.2px 1.2px at 22% 31%, rgba(255,255,255,.9), transparent 100%),
      radial-gradient(1px 1px at 68% 12%, rgba(0,255,156,.9), transparent 100%),
      radial-gradient(1.4px 1.4px at 84% 57%, rgba(0,229,255,.85), transparent 100%),
      radial-gradient(1px 1px at 41% 74%, rgba(255,255,255,.7), transparent 100%),
      radial-gradient(1.1px 1.1px at 9% 88%, rgba(255,230,0,.7), transparent 100%),
      radial-gradient(1px 1px at 56% 45%, rgba(176,38,255,.8), transparent 100%);
    background-size:520px 520px, 390px 390px, 730px 730px, 610px 610px, 450px 450px, 680px 680px;
    animation:twinkle 8s ease-in-out infinite alternate; }
  @keyframes twinkle { from{opacity:.32} to{opacity:.68} }
  /* فينييت يغرق الأطراف ويبرز المركز */
  body::after { content:''; position:fixed; inset:0; z-index:-1; pointer-events:none;
    background:radial-gradient(ellipse at 50% 42%, transparent 52%, rgba(0,0,0,.52) 100%); }
  .orb { position:fixed; border-radius:50%; filter:blur(95px); z-index:-2; opacity:.15;
         animation:orbfloat 12s ease-in-out infinite alternate; }
  .orb1 { width:430px; height:430px; background:var(--neon); top:-130px; left:-110px; }
  .orb2 { width:390px; height:390px; background:var(--cyan); bottom:-150px; right:-90px; animation-delay:-4s; }
  .orb3 { width:310px; height:310px; background:var(--mag); top:38%; right:28%; opacity:.09; animation-delay:-8s; }
  @keyframes orbfloat { from{transform:translate(0,0) scale(1)} to{transform:translate(60px,44px) scale(1.14)} }
  .scanlines { position:fixed; inset:0; z-index:70; pointer-events:none; opacity:.30;
    background:repeating-linear-gradient(0deg,rgba(0,0,0,.28) 0 1px,transparent 1px 3px); }
  .scanbar { position:fixed; left:0; right:0; height:110px; z-index:71; pointer-events:none;
    background:linear-gradient(180deg,transparent,rgba(0,255,156,.05),transparent);
    animation:scanmove 7s linear infinite; }
  @keyframes scanmove { from{top:-120px} to{top:100%} }
  .wrap { max-width:1280px; margin:0 auto; position:relative; }
  /* ── الهيدر: زجاج أعمق + شعيرة عليا تسبح ── */
  header { display:flex; flex-wrap:wrap; align-items:center; gap:10px; margin-bottom:14px;
    padding:14px 16px; border:1px solid var(--line); border-radius:16px;
    background:linear-gradient(160deg,rgba(0,255,156,.05),transparent 38%),var(--panel);
    backdrop-filter:blur(9px); position:relative; overflow:hidden;
    box-shadow:0 0 26px rgba(0,255,156,.09), inset 0 0 24px rgba(0,255,156,.03); }
  header::before { content:''; position:absolute; top:0; right:0; left:0; height:1px; pointer-events:none;
    background:linear-gradient(90deg,transparent,rgba(0,255,156,.8),rgba(0,229,255,.8),transparent);
    background-size:220% 100%; animation:hairsheen 6.5s linear infinite; }
  @keyframes hairsheen { from{background-position:0 0} to{background-position:-220% 0} }
  h1 { font-family:'Orbitron',var(--kufi); font-size:1.5rem; color:var(--neon);
    letter-spacing:1px; display:flex; align-items:center; gap:9px; }
  /* [FE1.9.13] الشعار يطفو ونص العلامة ينساب بتدرج متحرك (background-clip:text) */
  .logo { display:inline-block; font-size:1.6rem; filter:drop-shadow(0 0 9px rgba(0,255,156,.65));
    animation:logofloat 3.6s ease-in-out infinite; }
  @keyframes logofloat { 0%,100%{transform:translateY(0) scale(1)} 50%{transform:translateY(-2.5px) scale(1.07)} }
  .brand { background:linear-gradient(100deg,#00ff9c,#00e5ff 32%,#b026ff 58%,#00ff9c 85%);
    background-size:230% 100%; -webkit-background-clip:text; background-clip:text; color:transparent;
    filter:drop-shadow(0 0 11px rgba(0,255,156,.35)); animation:titleflow 9s linear infinite; }
  @keyframes titleflow { to{background-position:-230% 0} }
  h1 small { color:var(--mut); font-weight:400; font-size:.72rem; text-shadow:none; display:block; margin-top:2px;
    -webkit-text-fill-color:var(--mut); }
  /* الشارات: انسياب خفيف عند التحويم */
  .badge { padding:4px 12px; border-radius:999px; font-size:.74rem; font-weight:700; border:1px solid;
    text-shadow:0 0 6px currentColor; white-space:nowrap; transition:transform .2s, box-shadow .2s; }
  .badge:hover { transform:translateY(-1px); }
  .b-orig { background:rgba(0,229,255,.08); color:var(--cyan); border-color:var(--cyan); }
  .b-paper { background:rgba(0,229,255,.06); color:var(--cyan); border-color:var(--cyan); border-style:dashed; }
  .b-real { background:rgba(255,51,85,.12); color:var(--red); border-color:var(--red); animation:realpulse 1.6s infinite; }
  .b-on { background:rgba(0,255,156,.1); color:var(--neon); border-color:var(--neon); }
  .b-off { background:rgba(95,138,128,.1); color:var(--mut); border-color:var(--mut); text-shadow:none; }
  .b-bin-ok { background:rgba(0,255,156,.08); color:var(--neon); border-color:var(--neon); }
  .b-bin-bad { background:rgba(255,51,85,.1); color:var(--red); border-color:var(--red); }
  .b-ws { background:rgba(0,229,255,.08); color:var(--cyan); border-color:var(--cyan); }
  .b-ws-off { background:rgba(95,138,128,.1); color:var(--mut); border-color:var(--mut); text-shadow:none; }
  @keyframes realpulse { 0%,100%{box-shadow:0 0 6px rgba(255,51,85,.5)} 50%{box-shadow:0 0 18px rgba(255,51,85,.95)} }
  .spacer { flex:1; }
  /* ── الأزرار: لمعان يمسح الزر عند التحويم + انكماش عند الضغط ── */
  button.act { position:relative; overflow:hidden; background:rgba(0,255,156,.05);
    border:1px solid var(--neon); color:var(--neon);
    border-radius:10px; padding:8px 14px; cursor:pointer; font-size:.82rem;
    font-family:'Share Tech Mono',monospace; text-shadow:0 0 6px currentColor;
    box-shadow:0 0 10px rgba(0,255,156,.12); transition:.2s; }
  button.act::after { content:''; position:absolute; top:0; bottom:0; right:-45%; width:32%;
    background:linear-gradient(105deg,transparent,rgba(255,255,255,.18),transparent);
    transform:skewX(-20deg); transition:right .55s ease; pointer-events:none; }
  button.act:hover { background:rgba(0,255,156,.14); box-shadow:0 0 18px rgba(0,255,156,.45); }
  button.act:hover::after { right:130%; }
  button.act:active { transform:scale(.96); }
  button.act:disabled { opacity:.55; cursor:wait; }
  button.act.danger { border-color:var(--red); color:var(--red); box-shadow:0 0 10px rgba(255,51,85,.12); }
  button.act.danger:hover { background:rgba(255,51,85,.14); box-shadow:0 0 18px rgba(255,51,85,.45); }
  /* ── زر التداول الحقيقي: مفتاح نيون أحمر مثل V9 ── */
  .real-ctl { display:flex; align-items:center; gap:10px; padding:6px 12px; border-radius:12px;
    border:1px solid rgba(255,51,85,.4); background:rgba(255,51,85,.05); }
  .real-ctl .rlbl { font-size:.8rem; font-weight:700; color:var(--red); text-shadow:0 0 6px rgba(255,51,85,.6); white-space:nowrap; }
  .switch { position:relative; display:inline-block; width:52px; height:27px; flex:none; }
  .switch input { opacity:0; width:0; height:0; }
  .slider { position:absolute; inset:0; background:#0a0f14; border:1px solid var(--red); border-radius:999px;
    transition:.25s; box-shadow:inset 0 0 8px rgba(255,51,85,.35); cursor:pointer; }
  .slider::before { content:''; position:absolute; width:19px; height:19px; top:3px; right:4px; border-radius:50%;
    background:#3a4a52; transition:.25s; }
  .switch input:checked + .slider { background:rgba(255,51,85,.28); border-color:var(--red);
    box-shadow:0 0 16px rgba(255,51,85,.8), inset 0 0 8px rgba(255,51,85,.4); }
  .switch input:checked + .slider::before { transform:translateX(-24px); background:var(--red);
    box-shadow:0 0 10px var(--red); }
  .banner { width:100%; text-align:center; font-size:.8rem; font-weight:700; padding:9px 12px;
    border-radius:10px; margin-bottom:14px; }
  .banner-paper { color:var(--cyan); border:1px dashed var(--cyan); background:rgba(0,229,255,.05);
    text-shadow:0 0 6px rgba(0,229,255,.5); }
  .banner-real { color:var(--red); border:1px solid var(--red); background:rgba(255,51,85,.07);
    text-shadow:0 0 8px rgba(255,51,85,.7); animation:realpulse 1.6s infinite; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(165px,1fr)); gap:12px; margin-bottom:16px; }
  /* ── البطاقات: زجاج متدرج + شعيرة عليا + لمعان قُطري عند التحويم + دخول طافٍ ── */
  .card { background:linear-gradient(165deg,var(--glass-hi),rgba(0,229,255,.028) 45%,transparent 80%),var(--panel);
    border:1px solid var(--line); border-radius:13px; padding:13px 15px;
    position:relative; overflow:hidden; transition:.25s; backdrop-filter:blur(6px);
    animation:cardin .45s ease backwards; }
  /* [FE1.9.13] شلال الدخول: تأخير متدرج لأول 8 بطاقات ثم موجة واحدة للبقية */
  .grid .card:nth-child(1){animation-delay:.02s} .grid .card:nth-child(2){animation-delay:.06s}
  .grid .card:nth-child(3){animation-delay:.10s} .grid .card:nth-child(4){animation-delay:.14s}
  .grid .card:nth-child(5){animation-delay:.18s} .grid .card:nth-child(6){animation-delay:.22s}
  .grid .card:nth-child(7){animation-delay:.26s} .grid .card:nth-child(8){animation-delay:.30s}
  .grid .card:nth-child(n+9){animation-delay:.34s}
  @keyframes cardin { from{ opacity:0; transform:translateY(7px); } }
  .card::before { content:''; position:absolute; top:0; right:0; left:0; height:1px;
    background:linear-gradient(90deg,transparent,var(--neon),transparent); opacity:.65;
    transition:opacity .25s; }
  .card::after { content:''; position:absolute; top:0; bottom:0; right:-55%; width:38%;
    background:linear-gradient(105deg,transparent,rgba(255,255,255,.08),transparent);
    transform:skewX(-18deg); transition:right .65s ease; pointer-events:none; }
  .card:hover { border-color:var(--neon); box-shadow:0 4px 22px rgba(0,255,156,.24), inset 0 0 16px rgba(0,255,156,.05);
    transform:translateY(-3px); }
  .card:hover::before { opacity:1; }
  .card:hover::after { right:125%; }
  .card .lbl { color:var(--cyan); font-family:'Share Tech Mono',monospace; font-size:.7rem;
    letter-spacing:.5px; margin-bottom:6px; text-shadow:0 0 6px rgba(0,229,255,.45); }
  .card .val { font-family:'Share Tech Mono',monospace; font-size:1.05rem; font-weight:700;
    text-shadow:0 0 8px currentColor; word-break:normal; overflow-wrap:anywhere; line-height:1.45; }
  /* [FE1.9.13] وميض القيمة عند تغيّرها — يضيفه مراقب عرضي (لا يلمس منطق البيانات) */
  .val.flash { animation:valflash .85s ease; }
  @keyframes valflash { 0%{ filter:brightness(2.1) drop-shadow(0 0 9px currentColor); }
                        100%{ filter:none; } }
  .pos { color:var(--neon); } .neg { color:var(--red); } .gld { color:var(--yel); } .tealc { color:var(--cyan); }
  .vioc { color:var(--vio); }
  /* ── الأقسام: زجاج + عنوان بخط كوفي أرقى ── */
  section { background:linear-gradient(170deg,rgba(0,229,255,.03),transparent 42%),var(--panel);
    border:1px solid var(--line2); border-radius:15px; padding:14px 16px;
    margin-bottom:16px; backdrop-filter:blur(6px);
    box-shadow:0 0 16px rgba(0,229,255,.04); transition:border-color .3s, box-shadow .3s; }
  section:hover { border-color:rgba(0,229,255,.3); box-shadow:0 0 22px rgba(0,229,255,.09); }
  section h2 { font-family:var(--kufi); font-size:.94rem; color:var(--cyan); margin-bottom:10px;
    display:flex; align-items:center; flex-wrap:wrap; gap:8px;
    text-shadow:0 0 8px rgba(0,229,255,.5); border-bottom:1px dashed rgba(0,229,255,.22);
    padding-bottom:8px; }
  table { width:100%; border-collapse:collapse; font-size:.78rem; font-variant-numeric:tabular-nums; }
  th { color:var(--cyan); text-align:right; padding:6px 8px; border-bottom:1px solid rgba(0,229,255,.3);
    font-weight:600; white-space:nowrap; font-family:'Share Tech Mono',monospace; font-size:.7rem;
    text-shadow:0 0 5px rgba(0,229,255,.35); }
  td { padding:7px 8px; border-bottom:1px solid rgba(0,255,156,.07); white-space:nowrap; transition:background .2s; }
  tr:hover td { background:linear-gradient(90deg,rgba(0,255,156,.085),rgba(0,229,255,.03) 60%,transparent); }
  tbody tr { animation:rowin .3s ease backwards; }
  @keyframes rowin { from{ opacity:0; } }
  /* ── الحبوب (الحالات): تدرجات زجاجية بدل الألوان المسطحة ── */
  .pill { padding:2px 10px; border-radius:999px; font-size:.7rem; font-weight:700;
    border:1px solid; text-shadow:0 0 5px currentColor; display:inline-block; }
  .p-pending { background:linear-gradient(180deg,rgba(255,230,0,.16),rgba(255,230,0,.05)); color:var(--yel); border-color:var(--yel); }
  .p-open { background:linear-gradient(180deg,rgba(0,229,255,.17),rgba(0,229,255,.05)); color:var(--cyan); border-color:var(--cyan); }
  .p-bull { background:linear-gradient(180deg,rgba(0,255,156,.18),rgba(0,255,156,.05)); color:var(--neon); border-color:var(--neon); }
  .p-bear { background:linear-gradient(180deg,rgba(255,51,85,.18),rgba(255,51,85,.05)); color:var(--red); border-color:var(--red); }
  .p-win { background:linear-gradient(180deg,rgba(0,255,156,.18),rgba(0,255,156,.05)); color:var(--neon); border-color:var(--neon); }
  .p-loss { background:linear-gradient(180deg,rgba(255,51,85,.18),rgba(255,51,85,.05)); color:var(--red); border-color:var(--red); }
  .p-real { background:linear-gradient(180deg,rgba(255,51,85,.2),rgba(255,51,85,.07)); color:var(--red); border-color:rgba(255,51,85,.6); }
  .p-exp { background:rgba(160,160,170,.12); color:var(--mut); border-color:var(--mut); text-shadow:none; }
  .p-cxl { background:rgba(255,51,85,.1); color:var(--red); border-color:rgba(255,51,85,.5); }
  .p-mcr { background:linear-gradient(180deg,rgba(255,51,85,.26),rgba(255,51,85,.1)); color:#ff6685; border-color:var(--red); font-weight:800; animation:mcrPulse 1.6s ease-in-out infinite; }
  /* [EL2.0.0] حبوب الاستراتيجيات المتوازية — شارات الصفوف وبطاقات القسم */
  .p-ew   { background:rgba(230,247,255,.07); color:#e6f7ff; border-color:rgba(230,247,255,.25); }
  .p-s1   { background:rgba(0,229,255,.12); color:var(--cyan); border-color:rgba(0,229,255,.45); font-weight:700; }
  .p-t    { background:rgba(100,216,203,.12); color:#64d8cb; border-color:rgba(100,216,203,.5); font-weight:700; }
  .p-z    { background:rgba(255,176,32,.14); color:#ffb020; border-color:rgba(255,176,32,.55); font-weight:700; }
  .scalp-cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:12px; }
  .scalp-card { position:relative; overflow:hidden; border:1px solid rgba(0,229,255,.22); border-radius:14px; padding:14px 16px; background:linear-gradient(160deg,rgba(0,229,255,.07),rgba(10,15,22,.35)); }
  .scalp-card.t { border-color:rgba(100,216,203,.25); background:linear-gradient(160deg,rgba(100,216,203,.07),rgba(10,15,22,.35)); }
  .scalp-card.z { border-color:rgba(255,176,32,.28); background:linear-gradient(160deg,rgba(255,176,32,.07),rgba(10,15,22,.35)); }
  .scalp-card h3 { margin:0 0 6px; font-size:15px; color:var(--cyan); display:flex; align-items:center; gap:8px; }
  .scalp-card.t h3 { color:#64d8cb; }
  .scalp-card.z h3 { color:#ffb020; }
  .scalp-card .srow { display:flex; justify-content:space-between; gap:8px; font-size:12.5px; padding:3px 0; border-bottom:1px dashed rgba(255,255,255,.06); }
  .scalp-card .srow:last-child { border-bottom:none; }
  .scalp-card .srow b { font-variant-numeric:tabular-nums; }
  @keyframes mcrPulse { 0%,100%{opacity:1} 50%{opacity:.55} }  /* [FE1.9.8] تنبيه نابض — غلق يدوي مطلوب */
  .p-paper { background:rgba(0,229,255,.08); color:var(--cyan); border-color:rgba(0,229,255,.4); }
  .zone-ok { color:var(--neon); font-weight:700; } .zone-no { color:var(--mut); }
  .mut { color:var(--mut); } .small { font-size:.7rem; }
  /* [FE1.9.13] حالات الفراغ: إطار متقطع يتنفس */
  .empty { color:var(--mut); text-align:center; padding:14px; font-size:.84rem;
    border:1px dashed rgba(95,138,128,.35); border-radius:12px; margin:4px 0;
    animation:emptypulse 3.2s ease-in-out infinite; }
  @keyframes emptypulse { 0%,100%{opacity:.72} 50%{opacity:1} }
  .notif { padding:7px 10px; border-right:3px solid var(--line); margin-bottom:6px; background:var(--panel2);
    border-radius:8px; font-size:.76rem; transition:transform .2s, border-color .2s;
    animation:notifin .32s ease backwards; }
  .notif:nth-child(1){animation-delay:.02s} .notif:nth-child(2){animation-delay:.05s}
  .notif:nth-child(3){animation-delay:.08s} .notif:nth-child(4){animation-delay:.11s}
  .notif:nth-child(5){animation-delay:.14s} .notif:nth-child(6){animation-delay:.17s}
  @keyframes notifin { from{ opacity:0; transform:translateX(-9px); } }
  .notif:hover { transform:translateX(-3px); border-right-width:5px; }
  .notif.warn { border-color:var(--yel); } .notif.err { border-color:var(--red); }
  .tbl-wrap { overflow-x:auto; }
  /* ── أشرطة التقدم: تدرج نيون + لمعان يمسح باستمرار ── */
  .prog { background:var(--panel2); border:1px solid var(--line2); border-radius:999px; height:10px;
    min-width:90px; position:relative; overflow:hidden; }
  .prog-fill { height:100%; border-radius:999px; transition:width .4s; position:relative; overflow:hidden;
    background:linear-gradient(90deg,var(--cyan),var(--neon)); box-shadow:0 0 8px rgba(0,255,156,.6); }
  .prog-fill::after { content:''; position:absolute; inset:0;
    background:linear-gradient(90deg,transparent,rgba(255,255,255,.4),transparent);
    transform:translateX(-100%); animation:shimmer 2.3s ease-in-out infinite; }
  @keyframes shimmer { to{ transform:translateX(100%); } }
  .prog-fill.pneg { background:linear-gradient(90deg,var(--mag),var(--red)); box-shadow:0 0 8px rgba(255,51,85,.6); }
  .prog-lbl { font-size:.66rem; color:var(--mut); margin-top:2px; }
  button.mini { background:var(--panel2); border:1px solid var(--line); color:var(--txt); border-radius:8px;
    padding:4px 10px; cursor:pointer; font-size:.7rem; white-space:nowrap; transition:.2s; }
  button.mini:hover { border-color:var(--neon); color:var(--neon); text-shadow:0 0 6px currentColor;
    transform:translateY(-1px); box-shadow:0 0 10px rgba(0,255,156,.25); }
  button.mini:active { transform:scale(.94); }
  button.mini.cxl:hover { border-color:var(--red); color:var(--red); box-shadow:0 0 10px rgba(255,51,85,.3); }
  .liveprice { font-weight:700; color:var(--cyan); text-shadow:0 0 6px rgba(0,229,255,.5); }
  .src { font-size:.58rem; padding:1px 6px; border-radius:6px; margin-left:6px; border:1px solid;
    font-weight:700; vertical-align:middle; }
  .src-ws { background:rgba(0,229,255,.1); color:var(--cyan); border-color:var(--cyan); }
  .src-rest { background:rgba(95,138,128,.1); color:var(--mut); border-color:var(--mut); }
  /* [FE1.9.13] نقطة الحيوية: حلقة تتمدد كنبض قلب */
  .dot { display:inline-block; width:9px; height:9px; border-radius:50%; margin-left:6px; position:relative;
    background:currentColor; box-shadow:0 0 9px currentColor; animation:dotpulse 1.8s infinite; }
  .dot::before { content:''; position:absolute; inset:-3px; border-radius:50%;
    border:1px solid currentColor; opacity:.7; animation:ripple 1.8s ease-out infinite; }
  @keyframes ripple { from{ transform:scale(.55); opacity:.85; } to{ transform:scale(2); opacity:0; } }
  @keyframes dotpulse { 0%,100%{opacity:1} 50%{opacity:.4} }
  footer { text-align:center; color:var(--mut); font-size:.7rem; padding:10px 0 20px; line-height:1.9;
    position:relative; }
  footer::before { content:''; position:absolute; top:0; right:15%; left:15%; height:1px;
    background:linear-gradient(90deg,transparent,rgba(0,255,156,.35),transparent); }
  footer a { color:var(--cyan); text-decoration:none; border-bottom:1px dotted transparent; transition:.2s; }
  footer a:hover { color:var(--neon); border-bottom-color:var(--neon); text-shadow:0 0 8px currentColor; }
  footer b { color:var(--neon); }
  /* ── التوست: يطفو من الأسفل بتوهج ── */
  #toast { position:fixed; bottom:18px; left:50%; transform:translateX(-50%); background:var(--panel2);
    border:1px solid var(--cyan); color:var(--cyan); padding:10px 20px; border-radius:12px; display:none;
    z-index:99; max-width:90vw; font-size:.8rem; text-shadow:0 0 6px rgba(0,229,255,.6);
    box-shadow:0 0 22px rgba(0,229,255,.4), 0 8px 30px rgba(0,0,0,.5);
    animation:toastin .35s ease; }
  @keyframes toastin { from{ opacity:0; transform:translateX(-50%) translateY(16px); }
                       to{ opacity:1; transform:translateX(-50%) translateY(0); } }
  .tf-ctl { display:flex; align-items:center; gap:4px; margin-inline-start:10px; }
  .tf-ctl .rlbl { font-size:.7rem; color:var(--mut); }
  button.tf-btn { background:rgba(0,229,255,.04); border:1px solid var(--line2); color:var(--cyan);
    border-radius:8px; padding:6px 9px; cursor:pointer; font-size:.72rem;
    font-family:'Share Tech Mono',monospace; transition:.2s; }
  button.tf-btn:hover { border-color:var(--cyan); box-shadow:0 0 8px rgba(0,229,255,.3); transform:translateY(-1px); }
  button.tf-btn:active { transform:scale(.94); }
  button.tf-btn.on { background:rgba(0,229,255,.14); border-color:var(--cyan); font-weight:bold;
    box-shadow:0 0 12px rgba(0,229,255,.35); animation:tfglow 2.4s ease-in-out infinite; }
  @keyframes tfglow { 0%,100%{ box-shadow:0 0 8px rgba(0,229,255,.3); } 50%{ box-shadow:0 0 16px rgba(0,229,255,.55); } }
  /* ── [FE1.9.13] إطار الشارت: حد شعاعي يدور (اتجاه الحدود المتحركة الحديث) ── */
  @property --beam { syntax:'<angle>'; inherits:false; initial-value:0deg; }
  .chart-frame { position:relative; border-radius:14px; }
  .chart-frame::before { content:''; position:absolute; inset:-1px; border-radius:15px; padding:1px;
    background:conic-gradient(from var(--beam), transparent 0deg 288deg,
      rgba(0,255,156,.9) 318deg, rgba(0,229,255,.9) 338deg, transparent 356deg);
    -webkit-mask:linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
    -webkit-mask-composite:xor;
    mask:linear-gradient(#000 0 0) content-box exclude, linear-gradient(#000 0 0);
    animation:beamspin 7s linear infinite; pointer-events:none; opacity:.95; }
  @keyframes beamspin { to{ --beam:360deg; } }
  /* احترام تفضيل تقليل الحركة — إتاحة وصول */
  @media (prefers-reduced-motion:reduce){
    *, *::before, *::after { animation-duration:.01ms !important; animation-iteration-count:1 !important;
      transition-duration:.01ms !important; }
  }
  @media (max-width:640px){ body{padding:10px} .grid{grid-template-columns:repeat(auto-fit,minmax(135px,1fr))}
    h1{font-size:1.15rem} button.act{padding:7px 10px; font-size:.74rem}
    .aurora,.stars{display:none} .orb{filter:blur(65px)} }
  /* [EL2.1.0] نافذة الإعدادات + دونات الأداء + أشرطة الإغلاقات المكدسة */
  #settings-modal { display:none; position:fixed; inset:0; z-index:999; background:rgba(0,0,0,.62);
    backdrop-filter:blur(3px); align-items:center; justify-content:center; }
  #settings-modal .modal-box { width:min(560px,92vw); max-height:86vh; overflow:auto;
    background:linear-gradient(160deg,rgba(2,20,16,.97),rgba(0,9,14,.97));
    border:1px solid var(--line); border-radius:16px; padding:18px 20px;
    box-shadow:0 0 40px rgba(0,255,156,.12); animation:modalIn .25s ease; }
  @keyframes modalIn { from{opacity:0; transform:translateY(14px) scale(.98)} to{opacity:1; transform:none} }
  #settings-modal h3 { color:var(--neon); font-family:var(--kufi); margin-bottom:12px; text-shadow:0 0 14px rgba(0,255,156,.4); }
  .set-row { display:flex; align-items:center; justify-content:space-between; gap:12px;
    padding:11px 12px; margin-bottom:8px; border:1px solid var(--line2); border-radius:12px;
    background:rgba(0,229,255,.03); transition:border-color .2s, background .2s, opacity .2s; }
  .set-row:hover { border-color:var(--neon); background:rgba(0,255,156,.05); }
  .set-row .set-name { font-weight:700; color:var(--txt); margin-bottom:2px; }
  .set-row.off { opacity:.62; }
  .cls-bars { display:flex; height:10px; border-radius:6px; overflow:hidden; margin:4px 0 2px; background:rgba(255,255,255,.06); }
  .cls-bars > i { display:block; height:100%; transition:width .5s ease; }
  .cls-lg { display:flex; flex-wrap:wrap; gap:8px; font-size:11px; color:var(--mut); margin-top:2px; }
  .donut-wrap { display:flex; align-items:center; gap:14px; margin:10px 0 4px; flex-wrap:wrap; }
  .donut { position:relative; width:110px; height:110px; flex:0 0 auto; }
  .donut svg { transform:rotate(-90deg); }
  .donut .donut-c { position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; }
  .donut .donut-c b { font-size:1.25rem; color:var(--neon); font-family:'Share Tech Mono',monospace; }
  .donut .donut-c span { font-size:10px; color:var(--mut); }
  .scalp-card.dim { opacity:.55; }
  /* [EL2.2.0] شريط معدل الربح في جدول مقارنة الاستراتيجيات */
  .wr-bar { height:4px; border-radius:3px; background:rgba(255,255,255,.07); overflow:hidden; margin-top:4px; max-width:120px; }
  .wr-bar i { display:block; height:100%; border-radius:3px; transition:width .6s ease; }
  /* [EL2.2.0] نافذة الشارت العائمة — سحب/تحجيم/تصغير/استعادة */
  #chart-float { display:none; position:fixed; top:72px; right:26px; z-index:998; width:min(780px,94vw); height:min(520px,72vh);
    min-width:320px; min-height:250px; flex-direction:column;
    background:linear-gradient(165deg,rgba(2,16,14,.97),rgba(0,8,13,.98));
    border:1px solid rgba(0,229,255,.28); border-radius:16px; overflow:hidden;
    box-shadow:0 18px 60px rgba(0,0,0,.55), 0 0 0 1px rgba(0,229,255,.06), 0 0 34px rgba(0,229,255,.10);
    animation:modalIn .22s ease; }
  #chart-float.min { height:auto !important; }
  #chart-float.min .cf-body, #chart-float.min .cf-handle { display:none; }
  .cf-bar { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:8px 12px;
    cursor:grab; user-select:none; -webkit-user-select:none; touch-action:none;
    background:linear-gradient(90deg,rgba(0,229,255,.10),rgba(0,255,156,.06));
    border-bottom:1px solid rgba(0,229,255,.18); }
  .cf-bar:active { cursor:grabbing; }
  .cf-bar .cf-title { color:#e6f7ff; font-size:13px; display:flex; align-items:center; gap:8px;
    white-space:nowrap; overflow:hidden; }
  .cf-btns { display:flex; gap:6px; flex:0 0 auto; }
  .cf-btn { background:rgba(0,229,255,.08); color:#9fe8ff; border:1px solid rgba(0,229,255,.30); border-radius:8px;
    width:28px; height:25px; cursor:pointer; font-size:12px; line-height:1; transition:.15s; }
  .cf-btn:hover { background:rgba(0,229,255,.20); transform:translateY(-1px); }
  .cf-btn.cf-close:hover { background:rgba(255,51,85,.25); border-color:rgba(255,51,85,.5); color:#ffb3c2; }
  .cf-body { flex:1 1 auto; min-height:0; }
  .cf-handle { position:absolute; bottom:0; left:0; width:24px; height:24px; cursor:nwse-resize; touch-action:none;
    background:linear-gradient(135deg, transparent 46%, rgba(0,229,255,.55) 50%, transparent 54%,
      rgba(0,229,255,.35) 66%, transparent 70%, rgba(0,229,255,.3) 82%, transparent 86%); }
  @media (max-width:640px){ #chart-float { right:8px; top:64px; } }
</style>
</head>
<body>
<div class="aurora"></div>
<div class="stars"></div>
<div class="bg-grid"></div>
<div class="orb orb1"></div><div class="orb orb2"></div><div class="orb orb3"></div>
<div class="scanlines"></div><div class="scanbar"></div>
<div class="wrap">
  <header>
    <h1><span class="logo">🌊</span><span class="brand">Fibo-Elio</span><small id="ver"></small></h1>
    <span class="badge b-orig">Elliott_Fibonacci (MIT)</span>
    <span class="badge" id="mode-badge">الوضع: —</span>
    <span class="badge" id="bin-badge" title="اتصال باينانس الحي">باينانس: —</span>
    <span class="badge" id="trade-badge"></span>
    <span class="badge" id="feed-badge" title="مصدر الأسعار الحية للصفقات النشطة">التغذية الحية: —</span>
    <div class="spacer"></div>
    <div class="real-ctl" title="تشغيل التداول الحقيقي على باينانس مثل V9">
      <span class="rlbl" id="real-status-text">التداول الحقيقي: —</span>
      <label class="switch"><input type="checkbox" id="real-toggle" onchange="toggleReal(this)"><div class="slider"></div></label>
    </div>
    <button class="act" onclick="toggleTrading()">تشغيل/إيقاف التوليد</button>
    <button class="act" id="settings-btn" title="تفعيل/تعطيل الاستراتيجيات الأربع — الحالة محفوظة وتصمد عبر إعادة النشر" onclick="openSettings()">⚙ الإعدادات</button>
    <div class="tf-ctl" title="فريم الكشف والتنفيذ — التبديل يلغي الأوامر الورقية المعلقة ويبدأ فحصًا جديدًا على الفريم المختار (الاختيار محفوظ ويصمد عبر إعادة النشر)">
      <span class="rlbl">الفريم:</span>
      <button class="tf-btn" data-tf="5m" onclick="setTimeframe('5m')">5m</button>
      <button class="tf-btn" data-tf="15m" onclick="setTimeframe('15m')">15m</button>
      <button class="tf-btn" data-tf="1h" onclick="setTimeframe('1h')">1h</button>
      <button class="tf-btn" data-tf="4h" onclick="setTimeframe('4h')">4h</button>
    </div>
    <button class="act danger" onclick="resetStats()">تصفير الإحصائيات</button>
  </header>

  <div id="mode-banner"></div>
  <div id="err-banner" style="display:none" class="banner banner-real"></div>
  <div class="grid" id="cards"></div>

  <section>
    <h2>🛰 فحص أزواج باينانس (الكون الكامل) <span class="mut small">— فلترة سيولة/سبريد/مدى على كل أسواق USDT ثم تحليل موجات زيجزاج 15م بعتبة الاستراتيجية نفسها — أعلى النتائج تُطبَّق تلقائيًا على قائمة المراقبة</span>
      <span class="spacer"></span><button class="act" id="scan-btn" onclick="scanNow()">🛰 فحص الآن</button></h2>
    <div id="scan-status" class="mut small" style="margin-bottom:8px">—</div>
    <div id="scan-box"></div>
  </section>

  <section>
    <h2>⚡🐂💥 الاستراتيجيات المتوازية — Eliott+2 <span class="mut small">— ثلاث استراتيجيات سكالبينغ سبوت على باينانس تعمل جنبًا إلى جنب مع موجات إليوت على نفس الرصيد: «انجلال التدفق» (زخم CVD + SuperTrend + جدران السيولة كأهداف) · «ركوب التيار» (تصحيح في ترند قائم + استئناف دلتا — EL2.2.0) · «انفجار الاختناق» (بولنجر داخل كيلتنر + انفجار حجم ودلتا — EL2.2.0) — الحماية نفسها: جزئي 50% عند الهدف الأول + BE + وقف أولًا. ارتداد القيمة أُزيل نهائيًا بعد فشله في بلوغ الأهداف</span></h2>
    <div id="scalp-box" class="scalp-cards"></div>
  </section>

  <section>
    <h2>📈 الصفقات المفتوحة والأوامر المعلقة <span class="mut small">— تتبع حي: الأسعار من ويب سوكت ⚡ (REST احتياطًا) · الحقيقية تُدار مباشرة من باينانس</span></h2>
    <div id="open-box"></div>
  </section>

  <section>
    <h2>🕯 الشارت الحي — البنية والأهداف <span class="mut small">— شموع فريم التنفيذ من كاش Postgres الدائم (صفر طلبات للمزودين) + الشمعة الجارية حية من التيار · خطوط: منطقة الدخول · الوقف · الأهداف المتدرجة TP1→TP3 · سقف الأسبوع — اضغط رمز أي صفقة أعلاه لعرضها هنا</span></h2>
    <div style="display:flex;gap:10px;align-items:center;margin-bottom:8px;flex-wrap:wrap">
      <select id="chart-sym" onchange="chartSelectSym()" style="background:#0a0f16;color:#e6f7ff;border:1px solid rgba(0,229,255,.3);border-radius:8px;padding:6px 10px;font-family:inherit"></select>
      <button class="tf-btn" id="chart-float-btn" onclick="chartFloatToggle()" title="إطلاق الشارت في نافذة عائمة قابلة للسحب والتحجيم — أو إعادته إلى الصفحة">⤢ عائم</button>
      <span id="chart-legend" class="mut small">
        <span style="color:#00e5ff">━ دخول</span> · <span style="color:#ff2d78">━ وقف</span> · <span style="color:#22e58c">━ أهداف</span> · <span style="color:#ffb020">⌈ سقف أسبوع</span>
      </span>
      <label for="ewx-toggle" title="مؤشر موجات المحرك — نفس حساب الاستراتيجية حرفيًا من /api/ew_strategy: زيجزاج الكاشف بعتبة الانعكاس + البنية P0–P5 بقواعدها الثلاث + منطقة الدخول 0.382×W3 + الوقف P0−0.1% + أهداف متدرجة مقصوصة على قمة الأسبوع + مفاتيح فيبو W2/W4/W3" style="display:flex;align-items:center;gap:5px;cursor:pointer;color:#f7c948;font-size:12px;border:1px solid rgba(247,201,72,.35);border-radius:8px;padding:5px 10px;background:rgba(247,201,72,.06)">
        <input type="checkbox" id="ewx-toggle" checked onchange="ewxToggle()" style="accent-color:#f7c948;cursor:pointer"> موجات المحرك (الاستراتيجية)
      </label>
      <label for="ew-toggle" title="مؤشر Elliott Wave [LuxAlgo] — ثلاثة زيجزاج (4/8/16) بمنطق Pine حرفي: دافع 12345 + تصحيح ABC + فيبو 0.5–0.854" style="display:flex;align-items:center;gap:5px;cursor:pointer;color:#e6f7ff;font-size:12px;border:1px solid rgba(0,229,255,.25);border-radius:8px;padding:5px 10px;background:rgba(0,229,255,.05)">
        <input type="checkbox" id="ew-toggle" checked onchange="ewToggle()" style="accent-color:#00e5ff;cursor:pointer"> موجات إليوت (LuxAlgo)
      </label>
      <label for="lvl-toggle" title="مستويات القيمة الحية من محرك السكالب: POC/VAH/VAL من Volume Profile + VWAP — نفس حسابات الاستراتيجية حرفيًا عبر /api/scalp/levels (كاش 45ث)" style="display:flex;align-items:center;gap:5px;cursor:pointer;color:#c792ea;font-size:12px;border:1px solid rgba(176,38,255,.35);border-radius:8px;padding:5px 10px;background:rgba(176,38,255,.06)">
        <input type="checkbox" id="lvl-toggle" checked onchange="lvlToggle()" style="accent-color:#b026ff;cursor:pointer"> مستويات القيمة (POC/VA)
      </label>
      <span id="chart-legend-ewx" class="mut small">
        <span style="color:#f7c948">━ زيجزاج المحرك + 0–5</span> · <span style="color:#c792ea">┈ مفاتيح فيبو W2/W3</span> · <span style="color:#64d8cb">┈ مفاتيح W4</span>
      </span>
      <span id="chart-legend-ew" class="mut small">
        <span style="color:#ff5b6a">━ زيجزاج 4</span> · <span style="color:#4da3ff">━ زيجزاج 8</span> · <span style="color:#e6edf3">━ زيجزاج 16</span>
      </span>
      <span id="chart-legend-lvl" class="mut small">
        <span style="color:#ffd24a">━ POC</span> · <span style="color:#b026ff">┈ VAH/VAL</span> · <span style="color:#00e5ff">┈ VWAP</span>
      </span>
    </div>
    <div id="chart-dock"><div id="lwc-chart" class="chart-frame" style="border:1px solid rgba(0,229,255,.12);border-radius:14px;background:rgba(0,229,255,.02)"></div></div>
    <div id="chart-note" class="mut small" style="margin-top:6px">—</div>
    <div id="ew-note" class="mut small" style="margin-top:2px"></div>
    <div id="ewx-note" class="mut small" style="margin-top:2px;color:#f7c948"></div>
    <div id="lvl-note" class="mut small" style="margin-top:2px;color:#c792ea"></div>
    <div class="mut small" style="margin-top:4px">الشارت: TradingView Lightweight Charts v5.2.1 (Apache-2.0) — يُقدَّم محليًا من الخادم بلا أي اعتماد خارجي · طبقة «موجات المحرك» تُحسب من محرك الاستراتيجية نفسه (زيجزاج 0.6% + قواعد P0–P5 + فيبو الاستراتيجية) · مؤشر الموجات الإضافي: منقول من Elliott Wave [LuxAlgo] © LuxAlgo (CC BY-NC-SA 4.0) — إسناد إلزامي</div>
  </section>

  <section>
    <h2>🧾 آخر الصفقات المغلقة</h2>
    <div id="closed-box"></div>
  </section>

  <section>
    <h2>📊 لوحة الأداء <span class="mut small">— مقتبسة من لوحة أداء V9.34.0 (اقتباسات OctoBot): صافي الربح · معدل الربح · عامل الربح · منحنى تراكمي بأعمدة الربح/الخسارة لكل صفقة</span></h2>
    <div class="grid" id="perf-cards"></div>
    <div class="donut-wrap" id="perf-donut"></div>
    <div id="perf-strats" style="margin:6px 0 2px"></div>
    <div id="pnl-chart-meta" class="mut small" style="margin:8px 0 4px"></div>
    <div id="pnl-chart"></div>
  </section>

  <section>
    <h2>🔍 آخر التقاطات الموجات (صاعدة تُنفَّذ — هابطة للاطلاع فقط في السبوت)</h2>
    <div id="gates-strip" class="mut small" style="margin-bottom:8px">—</div>
    <div id="det-box"></div>
  </section>

  <section>
    <h2>🔔 آخر الإشعارات</h2>
    <div id="notif-box"></div>
  </section>

  <footer>
    استراتيجية واحدة فقط: <b>موجة إليوت (دافع 5 موجات، قواعد صارمة ثلاث)</b> + <b>مستويات فيبوناتشي</b>
    (دخول 0.382 لتراجع الموجة 3 · وقف بنيوي خلف P0 · أهداف متدرجة TP1→TP3 لا تتجاوز قمة آخر 7 أيام — سكالبينج واقعي [FE1.9.9]) —
    ماسح الكون [FE1.5.0]: فحص أولي لكل أزواج باينانس USDT واختيار الأنسب للاستراتيجية تلقائيًا —
    التداول الحقيقي [FE1.4.0]: أمر LIMIT حقيقي عند فيبو 0.382 ← بيع سوق عند الوقف/الهدف، بقواعد باينانس
    (LOT_SIZE · NOTIONAL · دقة السعر/الكمية · كفاية الرصيد) —
    تتبع حي + إغلاق/إلغاء يدوي [FE1.1.0] + أسعار حية من ويب سوكت [FE1.2.0] + مضاد نوم محصّن [FE1.3.0]<br>
    المحرك منقول حرفيًا من <a href="https://github.com/dtwijesekara/Elliott_Waves_Algo_TradingBot" target="_blank">Elliott_Waves_Algo_TradingBot</a>
    (MIT) — مؤشر الموجات على الشارت منقول من <a href="https://www.tradingview.com/u/LuxAlgo/" target="_blank">Elliott Wave [LuxAlgo]</a>
    © LuxAlgo (<a href="https://creativecommons.org/licenses/by-nc-sa/4.0/" target="_blank">CC BY-NC-SA 4.0</a>) —
    مستودع المشروع: <a href="https://github.com/salah55t/fibo-elio" target="_blank">salah55t/fibo-elio</a>
  </footer>
</div>
<!-- [EL2.1.0] نافذة إعدادات الاستراتيجيات — تفعيل/تعطيل حي محفوظ -->
<div id="settings-modal">
  <div class="modal-box">
    <h3>⚙ إعدادات الاستراتيجيات</h3>
    <div id="settings-list"></div>
    <div class="mut small" style="margin-top:10px">التعطيل يوقف توليد إشارات جديدة فقط — الصفقات المفتوحة تستمر بالإدارة حتى الإغلاق. الحالة محفوظة في قاعدة البيانات وتصمد عبر إعادة النشر.</div>
    <div style="margin-top:12px;text-align:left"><button class="act" onclick="closeSettings()">إغلاق</button></div>
  </div>
</div>
<div id="toast"></div>
<!-- [EL2.2.0] نافذة الشارت العائمة — قابلة للسحب (الشريط) والتحجيم (الزاوية) والتصغير -->
<div id="chart-float">
  <div class="cf-bar" id="cf-drag">
    <span class="cf-title">🕯 الشارت العائم · <b id="cf-sym">—</b><span class="mut small" id="cf-mini"></span></span>
    <span class="cf-btns">
      <button class="cf-btn" id="cf-min" onclick="chartFloatMin()" title="تصغير / استعادة">—</button>
      <button class="cf-btn cf-close" onclick="chartFloatOff()" title="إعادة الشارت إلى داخل الصفحة">✕</button>
    </span>
  </div>
  <div class="cf-body" id="cf-body"></div>
  <div class="cf-handle" id="cf-resize" title="اسحب لتغيير الحجم"></div>
</div>

<script src="/lwc.js" onerror="window.__LWC_FAILED=true"></script>
<script src="/ew.js" onerror="window.__EW_FAILED=true"></script>
<script>
const $ = id => document.getElementById(id);
const fmt = (v, d=4) => (v===null||v===undefined||isNaN(v)) ? '—' : Number(v).toLocaleString('en-US',{maximumFractionDigits:d});
const pct = v => (v===null||v===undefined||isNaN(v)) ? '—' : (v>=0?'+':'') + Number(v).toFixed(2) + '%';
const usd = v => (v===null||v===undefined||isNaN(v)) ? '—' : ((v>=0?'+':'') + Number(v).toFixed(2) + '$');
const cls = v => (v===null||v===undefined||isNaN(v)) ? '' : (v>=0 ? 'pos' : 'neg');
const dt = s => s ? String(s).replace('T',' ').replace('Z','') : '—';
// [FE1.5.0] تهريب HTML لكل بيانات API — كانت innerHTML مكشوفة على XSS مخزّن
const esc = s => String(s??'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

let WSSTATE = null;    // حالة تغذية الويب سوكت [FE1.2.0] — من /api/ws/status
let REAL_MODE = false; // حالة زر التداول الحقيقي [FE1.4.0]
let REAL_BUSY = false; // [FE1.5.0] لا اختطاف للمفتاح أثناء طلب التبديل الجاري
let REFRESHING = false;

function toast(msg){ const t=$('toast'); t.textContent=msg; t.style.display='block'; setTimeout(()=>t.style.display='none',2500); }

async function api(path, opts){ const r = await fetch(path, opts); if(!r.ok) throw new Error(await r.text()); return r.json(); }

function renderFeed(ws){
  const b = $('feed-badge');
  if(!ws || !ws.enabled){ b.textContent='التغذية الحية: REST'; b.className='badge b-ws-off'; return; }
  if(!ws.loop_alive){ b.textContent='التغذية الحية: ويب سوكت متوقف — REST مؤقتًا'; b.className='badge b-ws-off'; return; }
  // [FE1.9.7] شارة تيك باينانس الخام: حيّ = أقصى لحظية (سعر على كل صفقة فعلية)
  const raw = ws.raw || {};
  const tickTag = raw.connected
    ? ` + تيك خام ⚡⚡ (${(raw.ticks||0).toLocaleString('en-US')} تيك، عمر ${raw.age_sec ?? '—'}ث)`
    : (raw.enabled ? ' + تيك خام يعيد الاتصال' : '');
  b.textContent = `التغذية الحية: ويب سوكت ⚡ (${ws.live_streams||0} تيار حي)${tickTag}`;
  b.className = 'badge b-ws';
}

function srcBadge(sym){
  const p = (WSSTATE && WSSTATE.enabled && WSSTATE.prices) ? WSSTATE.prices[sym] : null;
  if(p && p.age_sec !== undefined && p.age_sec < 90)
    return `<span class="src src-ws" title="ويب سوكت عبر ${esc(p.source)} — عمر آخر تحديث ${p.age_sec} ث">⚡WS</span>`;
  return '<span class="src src-rest" title="طلبات REST (احتياط عند غياب التيار)">REST</span>';
}

// [FE1.9.9] سطر الأهداف المتدرجة تحت الهدف النهائي — tp_stages من الخادم (صاعدة صارمة)
// + سقف الأسبوع إن توفر — «الهدف لا يتجاوز ما لمسته العملة خلال 7 أيام»
function stagesLine(s){
  const st = s.tp_stages || [];
  let html = '';
  if(st.length > 1){
    const chips = st.map((t,i)=>`<span class="mut small">هدف ${i+1}: ${fmt(t)}</span>`).join(' · ');
    html = `<div class="small mut">↳ ${chips}</div>`;
  }
  if(s.weekly_high)
    html += `<div class="small mut">⌈ سقف أسبوع: ${fmt(s.weekly_high)}</div>`;
  return html;
}

function renderCards(d){
  const s = d.stats || {};
  const eq = (d.paper_balance||0) + (s.unrealized||0);
  // [FE1.4.0] بطاقة اتصال باينانس + رصيد USDT الحقيقي + وضع التنفيذ
  const bn = d.binance || {};
  let bnTxt, bnCls, binBadge;
  if (bn.connected) {
    bnTxt = (bn.latency_ms !== null && bn.latency_ms !== undefined) ? bn.latency_ms + 'ms' : 'متصل';
    if (bn.usdt_free !== null && bn.usdt_free !== undefined) bnTxt += ' · ' + fmt(bn.usdt_free,2) + '$';
    bnCls = 'pos';
    binBadge = 'باينانس: <span class="dot"></span>متصل ' + (bn.latency_ms ?? '') + 'ms' + (bn.keys_present ? ' 🔑' : '');
    $('bin-badge').className = 'badge b-bin-ok';
  } else {
    bnTxt = bn.keys_present ? 'فشل الاتصال' : 'بلا مفاتيح API';
    // [FE1.8.5] نص الخطأ الحقيقي في البطاقة — كانت «فشل الاتصال» بلا أي تفاصيل وبلا أثر في السجل
    const bnErr = (bn.error || '').replace(/\s+/g,' ').slice(0, 90);
    if (bn.keys_present && bnErr) bnTxt += ' · ' + bnErr;
    bnCls = bn.keys_present ? 'neg' : '';
    binBadge = 'باينانس: ' + (bn.keys_present ? 'غير متصل ⚠' : 'بلا مفاتيح');
    if (bn.keys_present && bnErr) binBadge += ' — ' + esc(bnErr);
    $('bin-badge').className = 'badge ' + (bn.keys_present ? 'b-bin-bad' : 'b-off');
  }
  if (bn.testnet) binBadge += ' 🧪TESTNET';
  $('bin-badge').innerHTML = binBadge;
  const cards = [
    ['الرصيد الورقي', fmt(d.paper_balance,2)+'$', 'gld'],
    ['الإيجوتي (مع غير المحقق)', fmt(eq,2)+'$', eq>=d.paper_balance?'pos':'neg'],
    ['غير المحقق (مفتوح)', usd(s.unrealized||0), cls(s.unrealized||0)],
    ['اتصال باينانس', bnTxt, bnCls],
    ['رصيد USDT الحقيقي', (bn.usdt_free!==null&&bn.usdt_free!==undefined)? fmt(bn.usdt_free,2)+'$' : '—', bn.keys_present?'tealc':''],
    ['وضع التنفيذ', d.real_mode ? '🔴 حقيقي' : '🧪 ورقي', d.real_mode ? 'neg' : 'tealc'],
    ['نشطة / معلقة', `${s.open_n||0} / ${s.pending_n||0}`, 'tealc'],
    ['صفقات مغلقة', s.closed_n||0, ''],
    ['نسبة الفوز', (s.win_rate!==null&&s.win_rate!==undefined)? Number(s.win_rate).toFixed(1)+'%':'—', 'tealc'],
    ['عامل الربح PF', (s.profit_factor!==null&&s.profit_factor!==undefined)? Number(s.profit_factor).toFixed(2):'—', (s.profit_factor||0)>=1?'pos':'neg'],
    ['صافي الربح', usd(s.total_pnl||0), cls(s.total_pnl||0)],
    ['مزود البيانات', esc((d.data&&d.data.active)? d.data.active.toUpperCase() : '—'), 'tealc'],
    // [FE1.8.7] بطاقة حارس الوزن — اقتباس V9: شفافية كاملة لوزن باينانس والحظر
    (function(){
      const rg = d.rate_guard || {};
      let rgTxt = '—', rgCls = 'tealc';
      if (rg.budget_per_min) {
        if (rg.banned) {
          rgTxt = '🚫 حظر حتى ' + esc(((rg.banned_until_iso||'').slice(11,16)) || '—') + ' UTC';
          rgCls = 'neg';
        } else {
          rgTxt = (rg.used_weight_last_min||0) + '/' + rg.budget_per_min + ' وزن·د';
          if (rg.ban_count) rgTxt += ' · ' + rg.ban_count + ' حظرات سابقة';
        }
      }
      return ['حارس وزن باينانس (V9)', rgTxt, rgCls];
    })(),
    ['آخر مسح', s.last_scan_at? esc(s.last_scan_at.slice(11,16))+' UTC' : '—', ''],
  ];
  // [FE1.3.0] بطاقة البقاء الحي — دليل مرئي أن مضاد النوم يعمل
  const ka = d.keep_alive || {};
  let kaTxt = 'معطل', kaCls = '';
  if (ka.enabled) {
    kaTxt = (ka.last_ok === false ? '⚠ فشل آخر نبضة! كل ' : '💓 كل ') + Math.round((ka.interval_sec||600)/60) + ' د';
    kaCls = (ka.last_ok === false ? 'neg' : 'pos');
    if (ka.last_ping_at) kaTxt += ' · ' + ka.last_ping_at.slice(11,19) + ' UTC';
  }
  cards.push(['البقاء الحي (مضاد النوم)', kaTxt, kaCls]);
  // [FE1.3.1] بطاقة الذاكرة — العتبات من السيرفر نفسه (كانت افتراضيات قديمة 450/380)
  const mem = d.memory || {};
  let memTxt = '—', memCls = '';
  if (mem.rss_mb) {
    const crit = mem.critical_mb || 440, gc = mem.gc_threshold_mb || 360;
    memTxt = Math.round(mem.rss_mb) + ' / 512 MB';
    memCls = mem.rss_mb >= crit ? 'neg' : (mem.rss_mb >= gc ? 'gld' : 'pos');
  }
  cards.push(['الذاكرة (RAM)', memTxt, memCls]);
  // [FE1.5.0] بطاقة ماسح الكون
  const sc = d.scanner || {};
  let scTxt = 'معطل', scCls = '';
  if (sc.enabled) {
    if (sc.running) { scTxt = '⏳ جارٍ الآن...'; scCls = 'gld'; }
    else {
      const n = (sc.results && sc.results.length) || 0;
      scTxt = sc.last_scan_at ? sc.last_scan_at.slice(11,16) + ' UTC · ' + n + ' زوجًا' : 'بانتظار أول فحص';
      scCls = 'vioc';
    }
    if (sc.error) { scTxt = '⚠ فشل آخر فحص'; scCls = 'neg'; }
  }
  cards.push(['🛰 فحص أزواج باينانس', scTxt, scCls]);
  $('cards').innerHTML = cards.map(c =>
    `<div class="card"><div class="lbl">${c[0]}</div><div class="val ${c[2]}">${c[1]}</div></div>`).join('');
  const tb = $('trade-badge');
  tb.textContent = d.trading_enabled ? 'توليد الإشارات: مفعّل' : 'توليد الإشارات: معطّل';
  tb.className = 'badge ' + (d.trading_enabled ? 'b-on' : 'b-off');
  // [FE1.4.0] زر التداول الحقيقي + شارة الوضع + لافتة الوضع — [FE1.5.0] بلا اختطاف أثناء الطلب
  REAL_MODE = !!d.real_mode;
  const rt = $('real-toggle');
  if (!REAL_BUSY && rt.checked !== REAL_MODE) rt.checked = REAL_MODE;
  $('real-status-text').textContent = 'التداول الحقيقي: ' + (REAL_MODE ? 'مُفعّل ⚠' : 'متوقف');
  const mb = $('mode-badge');
  mb.textContent = 'الوضع: ' + (REAL_MODE ? 'حقيقي 🔴' : 'ورقي 🧪');
  mb.className = 'badge ' + (REAL_MODE ? 'b-real' : 'b-paper');
  $('mode-banner').innerHTML = REAL_MODE
    ? '<div class="banner banner-real">⚠ التداول الحقيقي نشط — الإشارات الجديدة تُنفَّذ بأوامر فعلية على حسابك في Binance (شراء LIMIT عند فيبو 0.382 ← بيع سوق عند الوقف/الهدف)</div>'
    : '<div class="banner banner-paper">🧪 وضع ورقي — الصفقات المعروضة للتقييم فقط، لا أوامر حقيقية على Binance · فعّل مفتاح التداول الحقيقي للتنفيذ الفعلي</div>';
  $('ver').textContent = (d.version||'—') + ' — ' + (d.strategy||'');
}

function modePill(isReal){
  return isReal ? '<span class="pill p-real">حقيقية 🔴</span>' : '<span class="pill p-paper">ورقية</span>';
}

// [FE1.5.0] قسم فحص الكون — جدول النتائج + حالة الفحص
function renderScanner(d){
  const sc = d.scanner || {};
  const st = $('scan-status');
  let txt = sc.enabled ? 'الفحص التلقائي مفعّل (كل 6 ساعات افتراضيًا)' : 'الفحص التلقائي معطل — استخدم «فحص الآن»';
  if (sc.running) txt = '⏳ فحص جارٍ الآن — يستغرق نحو دقيقة...';
  else if (sc.last_scan_at) txt += ' · آخر فحص: ' + dt(sc.last_scan_at) + ' UTC'
    + (sc.duration_ms ? ` · استغرق ${(sc.duration_ms/1000).toFixed(0)} ث` : '');
  if (sc.universe) txt += ` · الكون ${sc.universe} زوج ← ${sc.passed ?? '—'} مرشحًا ← حُلل ${sc.candidates ?? '—'}`;
  if (sc.next_scan_at && !sc.running) txt += ' · الفحص القادم: ' + dt(sc.next_scan_at) + ' UTC';
  if (sc.error) txt = '⚠ ' + esc(sc.error);
  st.innerHTML = txt;
  const list = sc.results || [];
  if(!list.length){ $('scan-box').innerHTML = '<div class="empty">لا نتائج فحص بعد — اضغط «🛰 فحص الآن» أو انتظر الفحص التلقائي</div>'; return; }
  let rows = list.map((r,i) => `<tr>
    <td class="mut">${i+1}</td>
    <td><b>${esc(r.symbol||'')}</b></td>
    <td><span class="pill ${r.final>=70?'p-bull':(r.final>=45?'p-pending':'p-loss')}">${fmt(r.final,1)}</span></td>
    <td>${fmt(r.pivots,0)}</td>
    <td>${fmt(r.atr_pct,2)}%</td>
    <td>${fmt(r.avg_wave_pct,2)}%</td>
    <td>${fmt(r.trend_eff,2)}</td>
    <td>${fmt(r.range_pct,2)}%</td>
    <td>${fmt(r.qv,0)}$</td>
    <td>${sc.applied ? '<span class="pill p-open">مطبق ✓</span>' : '<span class="mut small">نتيجة فقط</span>'}</td>
  </tr>`).join('');
  $('scan-box').innerHTML = `<div class="tbl-wrap"><table><thead><tr>
    <th>#</th><th>الزوج</th><th>درجة الملاءمة</th><th>انعكاسات الزيجزاج</th><th>ATR%</th>
    <th>متوسط الموجة</th><th>كفاءة الاتجاه</th><th>مدى 24h</th><th>سيولة 24h</th><th>الحالة</th>
  </tr></thead><tbody>${rows}</tbody></table></div>`;
}

// [EL2.0.0] شارة الاستراتيجية على كل صف — موجات/تدفق/قيمة
function stratChip(s){
  const n = s.strategy_name || 'Elliott_Fibonacci';
  if(n==='SCALP_FLOW')    return '<span class="pill p-s1" title="سكالب انجلال التدفق: زخم CVD + SuperTrend + جدران سيولة">⚡ تدفق</span> ';
  if(n==='SCALP_TREND')   return '<span class="pill p-t" title="سكالب ركوب التيار: تصحيح في ترند قائم + استئناف دلتا — EL2.2.0">🐂 تيار</span> ';
  if(n==='SCALP_SQUEEZE') return '<span class="pill p-z" title="سكالب انفجار الاختناق: بولنجر داخل كيلتنر + انفجار بجسمه وحجمه — EL2.2.0">💥 اختناق</span> ';
  return '';
}

// ================= [EL2.0.0→EL2.1.0] الاستراتيجيات المتوازية — بطاقات Eliott+2 =================
// [EL2.1.0] كل بطاقة تعكس: حالة المفتاح (زر ⚡⚙) + أعمدة إغلاقات مكدسة + أداء حقيقي
// محسوب من الصفقات المغلقة (آخر 25) لكل استراتيجية — صدق الأرقام لا الديكور.
const STRAT_META = {
  'SCALP_FLOW':    {icon:'⚡', color:'#00ff9c', env:'SCALP_S1_ENABLED'},
  'SCALP_TREND':   {icon:'🐂', color:'#64d8cb', env:'SCALP_TREND_ENABLED'},
  'SCALP_SQUEEZE': {icon:'💥', color:'#ffb020', env:'SCALP_SQUEEZE_ENABLED'},
};
function stratClosedStats(closed, key){
  const a = {n:0, w:0, pnl:0};
  (closed||[]).forEach(s=>{
    if((s.strategy_name||'Elliott_Fibonacci') !== key) return;
    if(!['closed','expired','cancelled'].includes(s.status)) return;
    a.n++;
    const p = parseFloat(s.pnl_usdt||0); if(!isNaN(p)){ a.pnl += p; if(p>0) a.w++; }
  });
  return a;
}
function clsBars(closes){
  const c = closes||{};
  const parts = [['tp','#22e58c','هدف'],['sl','#ff3355','وقف'],['time','#ffe600','مهلة'],['early','#ff9d2b','مبكر'],['other','#5f8a80','أخرى']];
  const total = parts.reduce((s,p)=>s+(c[p[0]]||0),0);
  if(!total) return '<div class="cls-bars"><i style="width:100%;background:rgba(255,255,255,.06)"></i></div><div class="cls-lg">لا إغلاقات بعد</div>';
  const bars = parts.map(([k,col,lbl])=>{
    const v = c[k]||0; if(!v) return '';
    return `<i style="width:${(100*v/total).toFixed(1)}%;background:${col}" title="${lbl}: ${v}"></i>`;
  }).join('');
  const lg = parts.filter(p=>(c[p[0]]||0)>0).map(p=>`<span style="color:${p[1]}">■ ${p[2]} ${c[p[0]]}</span>`).join(' ');
  return `<div class="cls-bars">${bars}</div><div class="cls-lg">${lg}</div>`;
}
function renderScalp(d){
  const scalp = (d && d.scalp) || {};
  const el = $('scalp-box'); if(!el) return;
  if(scalp.enabled === false && !scalp.strategies){
    el.innerHTML = '<div class="empty">الاستراتيجيات المتوازية معطلة (SCALP_ENABLED=0) — محرك الموجات يعمل وحده</div>';
    return;
  }
  const st = scalp.state || {};
  const closed = (d && d.closed_signals) || [];
  const defs = [
    ['SCALP_FLOW','⚡ انجلال التدفق (S1)','s1','زخم CVD + SuperTrend + جدران السيولة كأهداف'],
    ['SCALP_TREND','🐂 ركوب التيار (S2)','t','تصحيح إلى EMA20/VWAP في ترند قائم + شمعة استئناف دلتاها موجبة — وقف تحت قاع التصحيح (EL2.2.0)'],
    ['SCALP_SQUEEZE','💥 انفجار الاختناق (S3)','z','بولنجر داخل كيلتنر + انفجار بجسم اندفاعي وحجم 1.4× ودلتا موجبة — وقف تحت قاعدة الاختناق (EL2.2.0)'],
  ];
  el.innerHTML = defs.map(([key,title,cls,desc])=>{
    const s = (scalp.strategies||{})[key];
    if(!s) return `<div class="scalp-card ${cls}"><h3>${title}</h3><div class="mut small">غير مثبتة (${STRAT_META[key].env}=0)</div></div>`;
    const on = s.enabled !== false;
    const closes = s.closes||{};
    const rej = s.rejects||{};
    const rejTop = Object.entries(rej).sort((a,b)=>b[1]-a[1]).slice(0,3)
      .map(([k,v])=>`${esc(k)}: <b>${v}</b>`).join(' · ') || '—';
    const cds = Object.entries(s.cooldowns||{});
    const cdTxt = cds.length ? cds.map(([k,v])=>`${esc(k)} (${Math.ceil(v/60)}د)`).join(' · ') : 'لا شيء';
    const dailyCls = (s.daily_pnl||0) >= 0 ? 'pos' : 'neg';
    const cs = stratClosedStats(closed, key);
    const csWr = cs.n ? (100*cs.w/cs.n).toFixed(0)+'%' : '—';
    const statePill = on
      ? `<span class="pill ${{s1:'p-s1',t:'p-t',z:'p-z'}[cls]||'p-s1'}">مفعّلة</span>`
      : `<span class="pill p-cxl" title="من زر ⚙ الإعدادات — لا إشارات جديدة والصفقات المفتوحة تُدار">معطّلة (⚙)</span>`;
    return `<div class="scalp-card ${cls} ${on?'':'dim'}">
      <h3>${title} ${statePill}</h3>
      <div class="mut small" style="margin-bottom:6px">${desc}</div>
      <div class="srow"><span>مفتوح الآن</span><b>${s.open_n||0}</b></div>
      <div class="srow"><span>إشارات منذ الإقلاع</span><b>${s.signals||0}</b></div>
      <div class="srow"><span>جني جزئي / خروج مبكر</span><b>${s.partials||0} / ${s.early_exits||0}</b></div>
      <div class="srow"><span>إغلاقات</span><b>${(closes.tp||0)} هدف · ${(closes.sl||0)} وقف · ${((closes.time||0)+(closes.early||0)+(closes.other||0))} أخرى</b></div>
      <div style="margin:2px 0 4px">${clsBars(closes)}</div>
      <div class="srow"><span>الأداء (آخر 25 مغلقة)</span><b class="small">${cs.n} صفقة · WR ${csWr} · <span class="${cs.pnl>=0?'pos':'neg'}">${cs.pnl>=0?'+':''}${cs.pnl.toFixed(2)}$</span></b></div>
      <div class="srow"><span>ربح اليوم</span><b class="${dailyCls}">${(s.daily_pnl||0)>=0?'+':''}${(s.daily_pnl||0).toFixed(2)}$</b></div>
      <div class="srow"><span>${s.daily_loss_block?'⛔ قاطع خسارة اليوم مفعل':'تبريد الرموز'}</span><b class="small">${s.daily_loss_block?'أوقف الدخول حتى الغد':cdTxt}</b></div>
      <div class="srow"><span>آخر إشارة</span><b class="small">${s.last_signal_symbol?esc(s.last_signal_symbol)+' — '+esc((s.last_signal_at||'').slice(11,16)):('—'+' · أرفض: '+rejTop)}</b></div>
    </div>`;
  }).join('')
  + `<div class="scalp-card" style="border-color:rgba(255,255,255,.12)">
      <h3>🧭 إعدادات المدير</h3>
      <div class="srow"><span>فريم التنفيذ</span><b>${esc(scalp.exec_tf||'5m')}</b></div>
      <div class="srow"><span>دورات المسح / آخر مسح</span><b>${(st.cycles||0)} / ${st.last_scan_age===null||st.last_scan_age===undefined?'—':st.last_scan_age+'ث'}</b></div>
      <div class="srow"><span>مخاطرة الصفقة / سقف قيمتها</span><b>${scalp.config?scalp.config.risk_pct:0}% / ${scalp.config?scalp.config.max_notional_usdt:0}$</b></div>
      <div class="srow"><span>مهلة الصفقة / تبريد الرمز</span><b>${scalp.config?scalp.config.max_hold_min:0}د / ${scalp.config?Math.ceil(scalp.config.cooldown_sec/60):0}د</b></div>
      <div class="srow"><span>مصدر CVD الأخير</span><b>${scalp.state&&scalp.state.cvd_source_last==='taker'?'تاكير باينانس (حقيقة)':'تقريب صادق (proxy)'}</b></div>
      ${st.last_error?`<div class="srow"><span>خطأ أخير</span><b class="neg small">${esc(st.last_error)}</b></div>`:''}
    </div>`;
}

function renderOpen(list){
  if(!list.length){ $('open-box').innerHTML = '<div class="empty">لا صفقات مفتوحة ولا أوامر معلقة حاليا — البوت يراقب السوق بحثا عن دافع صالح ✨</div>'; return; }
  let rows = list.map(s => {
    const isPend = s.status==='pending';
    // [FE1.9.8] شارة «غلق يدوي مطلوب» — علم meta من الخادم (فشل غلق حقيقي عند بلوغ الوقف/الهدف)
    const mcr = (!isPend && s.meta && s.meta.manual_close_required)
      ? ' <span class="pill p-mcr" title="وصلت الصفقة مستوى خروجها وعجز البوت عن الغلق — أغلقها من باينانس أو أرسل /close في تلغرام">🚨 غلق يدوي</span>' : '';
    const st = isPend ? '<span class="pill p-pending">معلق</span>' : '<span class="pill p-open">مفتوح</span>'+mcr;
    const fib = s.fib || {};
    // تتبع حي [FE1.1.0] + شارة المصدر [FE1.2.0]
    const cp = s.current_price ? `${srcBadge(esc(s.symbol))}<span class="liveprice">${fmt(s.current_price)}</span>` : '<span class="mut">—</span>';
    let live;
    if(!isPend){
      const u = s.unrealized_usdt;
      const up = (u===null||u===undefined) ? '<span class="mut small">حسب السعر</span>'
        : `<span class="${cls(u)}"><b>${usd(u)}</b> <span class="small">(${pct(s.unrealized_pct)})</span></span>`;
      const pr = (s.progress_pct===null||s.progress_pct===undefined) ? '<span class="mut small">—</span>'
        : `<div class="prog"><div class="prog-fill ${s.progress_pct<0?'pneg':''}" style="width:${Math.max(2,Math.min(100,Math.abs(s.progress_pct)))}%"></div></div>` +
          `<div class="prog-lbl">${s.progress_pct>=0?'نحو الهدف':'تحت الدخول'} ${s.progress_pct.toFixed(0)}% · للهدف ${pct(s.dist_tp_pct)} · للوقف ${pct(s.dist_sl_pct)}</div>`;
      live = [cp, up, pr];
    } else {
      const de = (s.dist_entry_pct===null||s.dist_entry_pct===undefined) ? '<span class="mut small">—</span>'
        : `<span class="small">${s.dist_entry_pct>=0?'السعر تحت الدخول بـ':'فوق الدخول بـ'} <b class="${s.dist_entry_pct>=0?'tealc':'gld'}">${Math.abs(s.dist_entry_pct).toFixed(2)}%</b></span>`;
      live = [cp, '<span class="mut small">أمر منتظر</span>', de];
    }
    const act = isPend
      ? `<button class="mini cxl" onclick="cancelOrder(${s.id},'${esc(s.symbol)}')">✖ إلغاء</button>`
      : `<button class="mini" onclick="closeTrade(${s.id},'${esc(s.symbol)}')">🔒 إغلاق</button>`;
    return `<tr>
      <td>${stratChip(s)}<b style="cursor:pointer" title="عرض في الشارت 🕯" onclick="chartFocus('${esc(s.symbol)}')">${esc(s.symbol)}</b></td><td>${st}</td><td>${modePill(s.is_real)}</td>
      <td>${live[0]}</td><td>${live[1]}</td><td>${live[2]}</td>
      <td>${fmt(isPend?s.entry_price:s.fill_price)}</td>
      <td class="neg">${fmt(s.stop_loss)}</td><td class="pos">${fmt(s.take_profit)}${stagesLine(s)}</td>
      <td>${s.rr_ratio?Number(s.rr_ratio).toFixed(2):'—'}</td>
      <td>${fmt(s.quantity,6)}</td>
      <td class="mut small">${dt(s.created_at)}</td>
      <td class="mut small">${isPend?('تنتهي: '+dt(s.expires_at)):'—'}</td>
      <td>${act}</td>
    </tr>`;
  }).join('');
  $('open-box').innerHTML = `<div class="tbl-wrap"><table><thead><tr>
    <th>الزوج</th><th>الحالة</th><th>الوضع</th><th>السعر الآن</th><th>غير المحقق</th><th>التقدم نحو الهدف</th>
    <th>دخول/ملء</th><th>وقف</th><th>الأهداف (متدرجة)</th>
    <th>R:R</th><th>الكمية</th><th>أُنشئ</th><th>الصلاحية</th><th>إجراء</th>
  </tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderClosed(list){
  if(!list.length){ $('closed-box').innerHTML = '<div class="empty">لا صفقات مغلقة بعد</div>'; return; }
  // [FE1.9.6] لا اختفاء صامت: المنتهية/الملغاة تظهر بشاراتها — دورة حياة المعلق كاملة مرئية
  const stPill = s => s.status==='expired' ? '<span class="pill p-exp">منتهية</span>'
                  : s.status==='cancelled' ? '<span class="pill p-cxl">ملغاة</span>'
                  : '<span class="pill p-open">مغلقة</span>';
  let rows = list.map(s => {
    const inP = (s.fill_price===null||s.fill_price===undefined||isNaN(s.fill_price)) ? s.entry_price : s.fill_price;
    return `<tr>
    <td>${stratChip(s)}<b style="cursor:pointer" title="عرض في الشارت 🕯" onclick="chartFocus('${esc(s.symbol)}')">${esc(s.symbol)}</b></td><td>${modePill(s.is_real)}</td>
    <td>${stPill(s)}</td>
    <td>${fmt(inP)} → ${fmt(s.close_price)}</td>
    <td class="${cls(s.pnl_usdt)}"><b>${usd(s.pnl_usdt)}</b></td>
    <td class="${cls(s.pnl_pct)}">${pct(s.pnl_pct)}</td>
    <td class="mut small">${esc(s.close_reason||'')}</td>
    <td class="mut small">${dt(s.closed_at)}</td>
  </tr>`;
  }).join('');
  // [FE1.5.0] داخل .tbl-wrap — كانت تفيض على الموبايل بلا تمرير
  $('closed-box').innerHTML = `<div class="tbl-wrap"><table><thead><tr>
    <th>الزوج</th><th>الوضع</th><th>الحالة</th><th>دخول → خروج</th><th>النتيجة</th><th>%</th><th>السبب</th><th>التاريخ</th>
  </tr></thead><tbody>${rows}</tbody></table></div>`;
}

// ================= [FE1.8.1] حكم الالتقاط + شريط البوابات + لوحة الأداء =================
// الحكم: لماذا لم تصبح التقاطة توصية معلقة — من _reject_reason في الخادم
// (نسخة خفيفة من بطاقة «لماذا لا يتداول؟» المخطط لها في FE1.9.0)
function verdictCell(x){
  if(x.traded) return '<span class="pill p-open">أمر معلق بانتظار الدخول</span>';
  if(x.direction==='BEARISH') return '<span class="mut small">متابعة فقط — لا بيع في السبوت</span>';
  const v = x.verdict || 'مرفوض';
  return '<span class="small gld" title="بوابة الرفض الأخيرة">'+esc(v)+'</span>';
}

function renderGates(st){
  const el = $('gates-strip');
  if(!el) return;
  st = st || {};
  const gates = [['rejected_stale_premise','فرضية ميتة'],['rejected_old_structure','بنية قديمة'],
    ['rejected_deep_retrace','تصحيح عميق'],['rejected_cooldown','تبريد رمز'],['rejected_symbol_busy','رمز مشغول'],
    ['rejected_cluster','عنقود'],['rejected_active_limit','خانات ممتلئة'],['rejected_htf_bias','HTF هابط'],
    ['rejected_far_entry','مطاردة'],['rejected_target_invalid','هدف محقق'],
    ['rejected_no_target','لا هدف R:R'],['rejected_weekly_cap','فوق سقف الأسبوع'],
    ['rejected_rr_net','R:R صافٍ منخفض'],['rejected_daily_loss','حد يومي'],['rejected_risk_pause','تبريد مخاطر']];
  const parts = gates.filter(g=>st[g[0]]).map(g=>g[1]+' <b>'+st[g[0]]+'</b>');
  el.innerHTML = '🚦 بوابات هذه الفترة: ' + (parts.length? parts.join(' · ') : 'لا رفضات بعد') +
    ' — دورات المسح: <b>'+(st.cycles||0)+'</b> · رموز ممسوحة: <b>'+(st.scanned||0)+'</b>' +
    ' · ⚡ نبض الحركة (كشف لحظي): <b>'+(st.momentum_kicks||0)+'</b>';
}

// لوحة الأداء — اقتباس من V9.34.0 (اقتباسات OctoBot: /api/stats + pnl_history):
// بطاقات أساسية + تمديدات، ومنحنى أرباح تراكمي SVG خالص بلا CDN
// (خط تراكمي + أعمدة خضراء/حمراء لكل صفقة) بألوان هذه اللوحة
function renderPnlChart(trades){
  const box = document.getElementById('pnl-chart');
  if(!box) return;
  if(!trades || !trades.length){
    box.innerHTML = '<div class="empty">لا صفقات مغلقة بعد — المنحنى يُبنى من أول إغلاق</div>';
    return;
  }
  const W = 900, H = 260, PAD_L = 52, PAD_R = 12, PAD_T = 14, PAD_B = 26;
  const cums = trades.map(t => t.cum_usdt);
  let lo = Math.min(0, ...cums), hi = Math.max(0, ...cums);
  if(hi - lo < 0.5){ hi += 0.25; lo -= 0.25; }
  const rng = hi - lo;
  const x = i => PAD_L + (i / Math.max(1, trades.length - 1)) * (W - PAD_L - PAD_R);
  const y = v => PAD_T + (1 - (v - lo) / rng) * (H - PAD_T - PAD_B);
  const barW = Math.max(1.5, (W - PAD_L - PAD_R) / trades.length * 0.6);
  const bars = trades.map((t, i) => {
    const cx = x(i), v = t.net_usdt, y0 = y(0), y1 = y(v);
    const top = Math.min(y0, y1), h = Math.max(1, Math.abs(y0 - y1));
    const col = v > 0 ? 'rgba(0,255,156,.65)' : v < 0 ? 'rgba(255,51,85,.55)' : 'rgba(120,140,150,.4)';
    const tip = '#'+t.i+' '+(t.symbol||'')+' · '+(t.net_usdt>=0?'+':'')+t.net_usdt+'$ · تراكمي '+t.cum_usdt+'$';
    return '<rect x="'+(cx-barW/2).toFixed(1)+'" y="'+top.toFixed(1)+'" width="'+barW.toFixed(1)+'" height="'+h.toFixed(1)+'" fill="'+col+'"><title>'+esc(tip)+'</title></rect>';
  }).join('');
  const path = trades.map((t,i)=>(i===0?'M':'L')+x(i).toFixed(1)+','+y(t.cum_usdt).toFixed(1)).join(' ');
  const area = path + ' L'+x(trades.length-1).toFixed(1)+','+y(0).toFixed(1)+' L'+x(0).toFixed(1)+','+y(0).toFixed(1)+' Z';
  const last = trades[trades.length-1];
  const lastCol = last.cum_usdt >= 0 ? '#00ff9c' : '#ff3355';
  const grid = [hi, (hi+lo)/2, lo].map(v =>
    '<line x1="'+PAD_L+'" y1="'+y(v).toFixed(1)+'" x2="'+(W-PAD_R)+'" y2="'+y(v).toFixed(1)+'" stroke="rgba(0,255,156,.12)" stroke-dasharray="3,4" stroke-width="1"/>'+
    '<text x="'+(PAD_L-4)+'" y="'+(y(v)+3).toFixed(1)+'" fill="#5d8f6d" font-size="10" font-family="Share Tech Mono,monospace" text-anchor="end">'+v.toFixed(2)+'</text>').join('');
  const zero = '<line x1="'+PAD_L+'" y1="'+y(0).toFixed(1)+'" x2="'+(W-PAD_R)+'" y2="'+y(0).toFixed(1)+'" stroke="rgba(120,140,150,.5)" stroke-width="1"/>';
  box.innerHTML = '<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:260px" preserveAspectRatio="none">'+
    '<defs><linearGradient id="pnlgrad" x1="0" y1="0" x2="0" y2="1">'+
    '<stop offset="0%" stop-color="'+lastCol+'" stop-opacity=".28"/>'+
    '<stop offset="100%" stop-color="'+lastCol+'" stop-opacity=".02"/></linearGradient></defs>'+
    grid+zero+
    '<path d="'+area+'" fill="url(#pnlgrad)" stroke="none"/>'+
    bars+
    '<path d="'+path+'" fill="none" stroke="'+lastCol+'" stroke-width="2.2" opacity=".95"/>'+
    '<circle cx="'+x(trades.length-1).toFixed(1)+'" cy="'+y(last.cum_usdt).toFixed(1)+'" r="4" fill="'+lastCol+'"><animate attributeName="r" from="2" to="4" dur="0.5s" fill="freeze"/></circle>'+
    '<text x="'+(W-PAD_R)+'" y="'+(y(last.cum_usdt)-8).toFixed(1)+'" fill="'+lastCol+'" font-size="12" font-family="Share Tech Mono,monospace" text-anchor="end">'+(last.cum_usdt>=0?'+':'')+last.cum_usdt.toFixed(2)+'$</text>'+
  '</svg>';
}

// [EL2.1.0] عدّاد متحرك — القيمة تتسلق من قيمتها السابقة بدل القفز الصامت
function countUp(el, to, decimals, prefix, suffix){
  if(!el) return;
  const from = parseFloat(el.dataset.num != null ? el.dataset.num : (String(el.textContent).replace(/[^0-9.\-]/g,''))) || 0;
  el.dataset.num = to;
  if(!isFinite(from) || from === to || window.matchMedia('(prefers-reduced-motion: reduce)').matches){
    el.textContent = (prefix||'') + to.toFixed(decimals) + (suffix||''); return;
  }
  const t0 = performance.now(), dur = 650;
  (function step(t){
    const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    el.textContent = (prefix||'') + (from + (to - from) * e).toFixed(decimals) + (suffix||'');
    if(k < 1) requestAnimationFrame(step);
  })(t0);
}
// [EL2.1.0] دونات معدل الربح — حلقة متدرجة بحركة رسم SMIL (بلا مكتبات)
function renderWrDonut(p){
  const el = $('perf-donut'); if(!el) return;
  const wr = (p.win_rate==null) ? null : Math.max(0, Math.min(100, parseFloat(p.win_rate)));
  if(wr == null){ el.innerHTML = ''; return; }
  const n = p.total_closed_trades || 0;
  const R = 46, C = 2 * Math.PI * R;
  const arc = (C * wr / 100).toFixed(1), full = C.toFixed(1);
  const pf = (p.profit_factor == null) ? '—' : (p.profit_factor >= 99 ? '∞' : parseFloat(p.profit_factor).toFixed(2));
  const exp = (p.expectancy != null) ? parseFloat(p.expectancy).toFixed(2) : '—';
  el.innerHTML = `<div class="donut" title="معدل الربح الكلي">
    <svg width="110" height="110" viewBox="0 0 110 110">
      <circle cx="55" cy="55" r="${R}" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="10"/>
      <circle cx="55" cy="55" r="${R}" fill="none" stroke="url(#dgrad)" stroke-width="10" stroke-linecap="round"
        stroke-dasharray="0 ${full}">
        <animate attributeName="stroke-dasharray" from="0 ${full}" to="${arc} ${full}" dur="0.8s" fill="freeze"/>
      </circle>
      <defs><linearGradient id="dgrad" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="#00ff9c"/><stop offset="100%" stop-color="#00e5ff"/></linearGradient></defs>
    </svg>
    <div class="donut-c"><b>${wr.toFixed(0)}%</b><span>معدل الربح<br>${n} صفقة</span></div>
  </div>
  <div class="mut small">
    ⚖️ عامل الربح: <b style="color:#e6f7ff">${pf}</b> · 📊 توقع الصفقة: <b style="color:#e6f7ff">${exp}$</b><br>
    📈 الأفضل/الأسوأ: ${p.best_trade?'<b class="pos">'+esc(p.best_trade.symbol||'—')+' +'+parseFloat(p.best_trade.pnl).toFixed(2)+'$</b>':'—'} /
    ${p.worst_trade?'<b class="neg">'+esc(p.worst_trade.symbol||'—')+' '+parseFloat(p.worst_trade.pnl).toFixed(2)+'$</b>':'—'}
  </div>`;
}
// [EL2.1.0] تفصيل الأداء لكل استراتيجية — من الإغلاقات الفعلية (صدق لا تلفيق)
function renderPerfStrats(closed){
  const el = $('perf-strats'); if(!el) return;
  const agg = {};
  (closed||[]).forEach(s=>{
    const k = s.strategy_name || 'Elliott_Fibonacci';
    if(!['closed','expired','cancelled'].includes(s.status)) return;
    const a = agg[k] = agg[k] || {n:0, w:0, pnl:0};
    a.n++;
    const p = parseFloat(s.pnl_usdt||0); if(!isNaN(p)){ a.pnl += p; if(p>0) a.w++; }
  });
  const names = [['Elliott_Fibonacci','🌊 موجات إليوت','#00e5ff'],['SCALP_FLOW','⚡ انجلال التدفق','#00ff9c'],
    ['SCALP_TREND','🐂 ركوب التيار','#64d8cb'],['SCALP_SQUEEZE','💥 انفجار الاختناق','#ffb020']];
  const rows = names.filter(x=>agg[x[0]]).map(([k,lbl,col])=>{
    const a = agg[k], wr = a.n ? (100*a.w/a.n) : null;
    const wrTxt = (wr==null)?'—':wr.toFixed(0)+'%';
    const bar = (wr==null)?'':`<div class="wr-bar"><i style="width:${wr.toFixed(0)}%;background:${col}"></i></div>`;
    return `<tr><td style="color:${col}"><b>${lbl}</b></td><td>${a.n}</td><td>${wrTxt}${bar}</td>
      <td class="${a.pnl>=0?'pos':'neg'}"><b>${a.pnl>=0?'+':''}${a.pnl.toFixed(2)}$</b></td></tr>`;
  }).join('');
  el.innerHTML = rows ? `<div class="tbl-wrap"><table style="max-width:560px"><thead><tr>
    <th>الاستراتيجية (آخر 25 مغلقة)</th><th>صفقات</th><th>معدل الربح</th><th>النتيجة</th>
  </tr></thead><tbody>${rows}</tbody></table></div>` : '';
}

function renderPerformance(d){
  const p = d.performance || {};
  const cards = $('perf-cards');
  if(!cards) return;
  const pfTxt = (p.profit_factor == null) ? '—' : (p.profit_factor >= 99 ? '∞' : parseFloat(p.profit_factor).toFixed(2));
  const net = parseFloat(p.net_profit_usdt || 0);
  const today = parseFloat(p.today_pnl || 0);
  const wr = (p.win_rate == null) ? null : parseFloat(p.win_rate);
  const arr = [
    ['💵 صافي الربح', (net>=0?'+':'') + net.toFixed(2) + '$', net>0?'pos':(net<0?'neg':''), 'net'],
    ['🎯 معدل الربح', (wr==null?'—':wr.toFixed(1)+'%'), (wr!=null&&wr>=50)?'pos':'gld', 'wr'],
    ['⚖️ عامل الربح', pfTxt, (p.profit_factor!=null&&p.profit_factor>=1.15)?'pos':(p.profit_factor!=null&&p.profit_factor<0.85?'neg':'gld'), ''],
    ['🧾 الصفقات المغلقة', p.total_closed_trades||0, '', ''],
    ['📊 متوسط رابح/خاسر', (p.avg_win!=null?'+'+parseFloat(p.avg_win).toFixed(2):'—')+' / '+(p.avg_loss!=null?parseFloat(p.avg_loss).toFixed(2):'—')+'$', 'mut', ''],
    ['📉 أقصى تراجع', '-'+parseFloat(p.max_drawdown_usdt||0).toFixed(2)+'$', 'neg', ''],
    ['🗓 ربح اليوم', (today>=0?'+':'')+today.toFixed(2)+'$', today>=0?'pos':'neg', 'today'],
    ['⏱ متوسط المدة', p.avg_duration_min!=null?parseFloat(p.avg_duration_min).toFixed(0)+' دقيقة':'—', 'mut', ''],
  ];
  cards.innerHTML = arr.map(c =>
    `<div class="card"><div class="lbl">${c[0]}</div><div class="val ${c[2]}" ${c[3]?`data-k="${c[3]}"`:''}>${c[1]}</div></div>`).join('');
  // [EL2.1.0] العدّادات المتحركة على البطاقات الرئيسية فقط
  if(net != null) countUp(cards.querySelector('[data-k="net"]'), net, 2, net>=0?'+':'', '$');
  if(wr != null) countUp(cards.querySelector('[data-k="wr"]'), wr, 1, '', '%');
  countUp(cards.querySelector('[data-k="today"]'), today, 2, today>=0?'+':'', '$');
  const best = p.best_trade, worst = p.worst_trade;
  $('pnl-chart-meta').innerHTML =
    (best?'أفضل صفقة: <b class="pos">'+esc(best.symbol||'—')+' +'+parseFloat(best.pnl).toFixed(2)+'$</b>':'') +
    (worst?' · أسوأ صفقة: <b class="neg">'+esc(worst.symbol||'—')+' '+parseFloat(worst.pnl).toFixed(2)+'$</b>':'') +
    (p.expectancy!=null?' · توقع الصفقة: '+parseFloat(p.expectancy).toFixed(2)+'$':'');
  renderWrDonut(p);
  renderPerfStrats(d.closed_signals || []);
  renderPnlChart(p.trades || []);
}

function renderDetections(list){
  if(!list.length){ $('det-box').innerHTML = '<div class="empty">لا التقاطات بعد — بانتظار تكوّن موجات دافعة صالحة على فريم الكشف</div>'; return; }
  let rows = list.map(x => {
    const pivs = Array.isArray(x.pivots) ? x.pivots.map(p=>fmt(p)).join(' · ') : '—';
    return `<tr>
    <td><b>${esc(x.symbol)}</b> <span class="mut small">${esc(x.timeframe||'')}</span></td>
    <td><span class="pill ${x.direction==='BULLISH'?'p-bull':'p-bear'}">${x.direction==='BULLISH'?'صاعدة ↑':'هابطة ↓'}</span></td>
    <td class="small mut">P0…P5: ${pivs}</td>
    <td>${x.w2_retrace!==null&&x.w2_retrace!==undefined?(x.w2_retrace*100).toFixed(1)+'%':'—'} <span class="${x.w2_in_zone?'zone-ok':'zone-no'}">${x.w2_in_zone?'✔':''}</span></td>
    <td>${x.w4_retrace!==null&&x.w4_retrace!==undefined?(x.w4_retrace*100).toFixed(1)+'%':'—'} <span class="${x.w4_in_zone?'zone-ok':'zone-no'}">${x.w4_in_zone?'✔':''}</span></td>
    <td>${fmt(x.entry_zone_low)}</td><td class="neg small">${fmt(x.stop_loss)}</td><td class="pos small">${fmt(x.take_profit)}</td>
    <td>${verdictCell(x)}</td>
    <td class="mut small">${dt(x.detected_at)}</td>
  </tr>`; }).join('');
  // [FE1.5.0] داخل .tbl-wrap + pivots محمية ضد null (كان خطأ واحد يجمّد اللوحة)
  $('det-box').innerHTML = `<div class="tbl-wrap"><table><thead><tr>
    <th>الزوج</th><th>الاتجاه</th><th>المحاور</th><th>W2</th><th>W4</th>
    <th>منطقة الدخول</th><th>وقف</th><th>هدف</th><th>الحكم</th><th>وقت الالتقاط</th>
  </tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderNotifs(list){
  if(!list.length){ $('notif-box').innerHTML = '<div class="empty">لا إشعارات</div>'; return; }
  $('notif-box').innerHTML = list.map(n =>
    `<div class="notif ${n.level==='warning'?'warn':(n.level==='error'||n.level==='critical')?'err':''}">
      <b class="mut small">${dt(n.created_at)}</b> — ${esc(n.message)}</div>`).join('');
}

// ═══ [FE1.9.10] الشارت الحي — TradingView Lightweight Charts v5.2.1 (Apache-2.0) ═══
// الشموع من كاش Postgres (صفر طلبات للمزودين) + الشمعة الجارية من التيار — خطوط مرجعية:
// منطقة الدخول / الوقف البنيوي / الأهداف المتدرجة TP1→TP3 / سقف الأسبوع — «الأهداف
// البعيدة» صارت مرئية بصريًا فورًا: القصّ على قمة 7 أيام يُرى بالعين.
let ALLSTATE = null;          // آخر /api/all — يشترك فيه الشارت مع بقية الأقسام
let CHART = null, CSERIES = null, CMARKS = null;
let chartSym = null, chartKey = '', chartLastBar = null, chartBars = [];
let chartLevels = [], chartFetchAt = 0;
// [FE1.9.11] مؤشر موجات إليوت (LuxAlgo) — حالة الطبقة فوق الشارت
let EW_ON = true, EW_SIG = '', EW_SERIES = [], EW_MARKS = null;
// [FE1.9.12] موجات المحرك — الحساب من الاستراتيجية نفسها عبر /api/ew_strategy
let EWX_ON = true, EWX_SIG = '', EWX_LINES = [], EWX_ZZ = null, EWX_MARKS = null, EWX_BUSY = false;
// [EL2.1.0] طبقة مستويات القيمة — POC/VAH/VAL/VWAP من محرك السكالب نفسه (/api/scalp/levels)
let LVL_ON = true, LVL_SIG = '', LVL_LINES = [], LVL_BUSY = false;
const LVL_CACHE = {};

function chartSelectedRow(){
  const s = ALLSTATE; if(!s || !chartSym) return null;
  return (s.open_signals||[]).find(r=>r.symbol===chartSym) ||
         (s.closed_signals||[]).find(r=>r.symbol===chartSym) || null;
}
function chartInit(){
  if(CHART || window.__LWC_FAILED) return;
  const LW = window.LightweightCharts;
  if(!LW){ $('lwc-chart').innerHTML = '<div class="empty" style="padding:20px">تعذر تحميل مكتبة الشارت — تُعاد المحاولة تلقائيًا</div>'; return; }
  const box = $('lwc-chart');
  try{
    CHART = LW.createChart(box, {
      width: box.clientWidth || 640, height: 340,
      layout: { background: { type: (LW.ColorType&&LW.ColorType.Solid)||'solid', color: 'transparent' }, textColor: '#8fa3b8', fontFamily: 'Share Tech Mono, monospace' },
      grid: { vertLines: { color: 'rgba(0,229,255,0.05)' }, horzLines: { color: 'rgba(0,229,255,0.08)' } },
      rightPriceScale: { borderColor: 'rgba(0,229,255,0.15)' },
      timeScale: { borderColor: 'rgba(0,229,255,0.15)', timeVisible: true, secondsVisible: false },
      crosshair: { mode: (LW.CrosshairMode&&LW.CrosshairMode.Normal!=null) ? LW.CrosshairMode.Normal : 0 },
    });
    CSERIES = CHART.addSeries(LW.CandlestickSeries, {
      upColor: '#00e5ff', downColor: '#ff2d78', borderVisible: false,
      wickUpColor: '#00e5ff', wickDownColor: '#ff2d78',
    });
    if(LW.createSeriesMarkers) CMARKS = LW.createSeriesMarkers(CSERIES, []);
    // [FE1.9.11] مثيل علامات مستقل لمؤشر الموجات (يدخل/الغلق في CMARKS لا يُمسّ)
    try{ if(LW.createSeriesMarkers) EW_MARKS = LW.createSeriesMarkers(CSERIES, []); }catch(e){ EW_MARKS = null; }
    // [FE1.9.12] مثيل علامات مستقل لمحاور المحرك P0–P5
    try{ if(LW.createSeriesMarkers) EWX_MARKS = LW.createSeriesMarkers(CSERIES, []); }catch(e){ EWX_MARKS = null; }
  }catch(e){ CHART = null; $('lwc-chart').innerHTML = '<div class="empty" style="padding:20px">فشل تهيئة الشارت: ' + esc(String(e.message||e)) + '</div>'; }
}
function chartPopulate(s){
  const sel = $('chart-sym'); if(!sel) return;
  const syms = [];
  const add = x => { if(x && !syms.includes(x)) syms.push(x); };
  (s.open_signals||[]).forEach(r=>add(r.symbol));
  (s.closed_signals||[]).forEach(r=>add(r.symbol));
  ((s.scanner&&s.scanner.results)||[]).forEach(r=>add(r.symbol));
  if(!syms.length){ if(!sel.options.length) sel.innerHTML = '<option value="">— لا رموز بعد —</option>'; return; }
  sel.innerHTML = syms.map(x=>`<option value="${esc(x)}"${x===chartSym?' selected':''}>${esc(x)}</option>`).join('');
  if(!chartSym) chartSym = syms[0];
}
function chartSelectSym(){
  chartSym = $('chart-sym').value || null;
  chartKey = ''; chartFetchAt = 0;   // إعادة تحميل كاملة للرمز الجديد
  chartTick(true);
}
// النقر على رمز أي صفقة (مفتوحة أو مغلقة) → يُعرض فورًا في الشارت
function chartFocus(sym){
  chartSym = sym; chartKey = ''; chartFetchAt = 0;
  const sel = $('chart-sym');
  if(sel){ [...sel.options].forEach(o=>{ if(o.value===sym) o.selected = true; }); }
  chartTick(true);
  if(!CF_ON){ const el = $('lwc-chart'); if(el && el.scrollIntoView) try{ el.scrollIntoView({behavior:'smooth', block:'nearest'}); }catch(e){} }
}
function chartApplyOverlays(){
  if(!CSERIES) return;
  for(const pl of chartLevels){ try{ CSERIES.removePriceLine(pl); }catch(e){} }
  chartLevels = [];
  if(CMARKS){ try{ CMARKS.setMarkers([]); }catch(e){} }
  const row = chartSelectedRow(); if(!row || !chartBars.length) return;
  const LW = window.LightweightCharts;
  const defs = [];
  const zl = (row.entry_zone_low!=null) ? row.entry_zone_low : row.entry_price;
  const zh = row.entry_zone_high;
  if(zl!=null && !isNaN(+zl)) defs.push({price:+zl, color:'#00e5ff', title:'دخول', style:(LW.LineStyle&&LW.LineStyle.Dashed!=null)?LW.LineStyle.Dashed:2, width:1});
  if(zh!=null && !isNaN(+zh) && +zh!==+zl) defs.push({price:+zh, color:'#00e5ff', title:'دخول ▲', style:(LW.LineStyle&&LW.LineStyle.Dotted!=null)?LW.LineStyle.Dotted:1, width:1});
  if(row.stop_loss!=null && !isNaN(+row.stop_loss)) defs.push({price:+row.stop_loss, color:'#ff2d78', title:'وقف', style:(LW.LineStyle&&LW.LineStyle.Solid!=null)?LW.LineStyle.Solid:0, width:1});
  const tps = (row.tp_stages && row.tp_stages.length) ? row.tp_stages : [row.tp1,row.tp2,row.tp3].filter(v=>v!=null);
  tps.forEach((t,i)=>{ if(t!=null && !isNaN(+t)) defs.push({price:+t, color:'#22e58c', title:'هدف '+(i+1), style:(LW.LineStyle&&LW.LineStyle.Solid!=null)?LW.LineStyle.Solid:0, width:1}); });
  if(row.weekly_high!=null && !isNaN(+row.weekly_high)) defs.push({price:+row.weekly_high, color:'#ffb020', title:'سقف أسبوع', style:(LW.LineStyle&&LW.LineStyle.Dashed!=null)?LW.LineStyle.Dashed:2, width:2});
  for(const dv of defs){ try{ chartLevels.push(CSERIES.createPriceLine({ price:dv.price, color:dv.color, lineWidth:dv.width, lineStyle:dv.style, axisLabelVisible:true, title:dv.title })); }catch(e){} }
  // علامات الملء/الغلق على شمعتها (ضمن النطاق المعروض فقط)
  if(CMARKS){
    const tfSec = ({'5m':300,'15m':900,'1h':3600,'4h':14400})[(ALLSTATE&&ALLSTATE.entry_timeframe)||'5m'] || 300;
    const marks = [];
    const mk = (iso, obj) => {
      const t = Math.floor(Date.parse(iso)/1000); if(isNaN(t)) return;
      const bt = Math.floor(t/tfSec)*tfSec;
      if(bt >= chartBars[0].time && bt <= chartBars[chartBars.length-1].time) marks.push(Object.assign({time:bt}, obj));
    };
    if(row.fill_price && row.filled_at) mk(row.filled_at, {position:'belowBar', color:'#00e5ff', shape:'arrowUp', text:'ملء'});
    if(row.close_price && row.closed_at){
      const win = (row.pnl_usdt!=null && +row.pnl_usdt>0);
      mk(row.closed_at, {position:'aboveBar', color:win?'#22e58c':'#ff2d78', shape:'arrowDown', text:win?'ربح':'خسارة'});
    }
    marks.sort((a,b)=>a.time-b.time);
    if(marks.length){ try{ CMARKS.setMarkers(marks); }catch(e){} }
  }
}
async function chartTick(force){
  if(window.__LWC_FAILED || document.hidden) return;
  if(!CHART) chartInit();
  if(!CHART || !CSERIES) return;
  const s = ALLSTATE; if(!s) return;
  if(!chartSym){ $('chart-note').textContent = 'لا رموز متاحة بعد — يظهر الشارت مع أول التقاط أو فحص كون'; return; }
  const now = Date.now();
  if(!force && now - chartFetchAt < 8000) return;   // الكاش يكفي كل 8ث — بلا ضغط
  chartFetchAt = now;
  const tf = s.entry_timeframe || '5m';
  const key = chartSym + '|' + tf;
  try{
    const d = await api('/api/klines?symbol=' + encodeURIComponent(chartSym) + '&tf=' + encodeURIComponent(tf) + '&limit=180');
    if(!d.candles || !d.candles.length){ $('chart-note').textContent = 'لا شموع في الكاش لـ ' + chartSym + ' — تظهر بعد دورة المسح القادمة'; return; }
    const bars = d.candles.map(c => ({ time: Math.floor(c[0]/1000), open:+c[1], high:+c[2], low:+c[3], close:+c[4] }));
    const lastc = bars[bars.length-1].close;
    const prec = lastc>=1000?2:(lastc>=10?3:(lastc>=1?4:6));
    try{ CSERIES.applyOptions({ priceFormat: { type:'price', precision:prec, minMove:1/Math.pow(10,prec) } }); }catch(e){}
    if(key !== chartKey){
      CSERIES.setData(bars);
      try{ CHART.timeScale().fitContent(); }catch(e){}
      chartKey = key;
    } else {
      CSERIES.update(bars[bars.length-1]);
    }
    chartBars = bars; chartLastBar = bars[bars.length-1];
    // نبضة السعر الحي من صف اللوحة (تيار الويب سوكت ⚡) — الشمعة الجارية تتنفس بين جلبات الكاش
    const row = chartSelectedRow();
    if(row && row.current_price!=null && !isNaN(+row.current_price) && chartLastBar){
      const p = +row.current_price;
      chartLastBar = { time:chartLastBar.time, open:chartLastBar.open, high:Math.max(chartLastBar.high,p), low:Math.min(chartLastBar.low,p), close:p };
      CSERIES.update(chartLastBar);
    }
    chartApplyOverlays();
    try{ ewMaybe(); }catch(e){ console.error(e); }   // [FE1.9.11] إعادة بناء طبقة الموجات عند تغيّر البيانات
    try{ ewxMaybe(); }catch(e){ console.error(e); }  // [FE1.9.12] طبقة موجات المحرك (الاستراتيجية)
    try{ lvlMaybe(); }catch(e){ console.error(e); }  // [EL2.1.0] طبقة مستويات القيمة (POC/VA/VWAP)
    const srcTxt = d.source==='cache+live' ? 'كاش + شمعة حية' : (d.source==='cache' ? 'كاش Postgres' : d.source);
    $('chart-note').innerHTML = '<b>' + esc(chartSym) + '</b> · فريم ' + esc(tf) + ' · ' + d.count + ' شمعة · مصدر ' + esc(srcTxt)
      + (row ? ' · خطوط: دخول/وقف/' + ((row.tp_stages&&row.tp_stages.length)?(row.tp_stages.length+' أهداف'):'هدف') + (row.weekly_high?' + سقف أسبوع':'') : ' · لا صفقة على هذا الرمز (شموع فقط)');
    const cfSym = $('cf-sym'); if(cfSym) cfSym.textContent = chartSym;
    const cfMini = $('cf-mini'); if(cfMini) cfMini.textContent = ' · ' + tf + ' · ' + d.count + ' شمعة';
  }catch(e){ $('chart-note').textContent = 'خطأ جلب الشموع: ' + String(e.message||e).slice(0,120); }
}

// ═══ [FE1.9.11] مؤشر موجات إليوت (LuxAlgo) — طبقة حسابية في متصفح المستخدم ═══
// المنطق كله من static/elliott-wave.js (/ew.js) — نقل CC BY-NC-SA 4.0 © LuxAlgo.
// إعادة البناء عند تغيّر التوقيع فقط (رمز/فريم/عدد/آخر شمعة) — لا تخريب سلاسل كل نبضة.
function ewToggle(){
  EW_ON = !!($('ew-toggle') && $('ew-toggle').checked);
  EW_SIG = '';
  try{ chartTick(true); }catch(e){}
}
function ewClear(){
  if(CHART){ for(const s of EW_SERIES){ try{ CHART.removeSeries(s); }catch(e){} } }
  EW_SERIES = [];
  if(EW_MARKS){ try{ EW_MARKS.setMarkers([]); }catch(e){} }
}
function ewStyleOf(st){
  const LW = window.LightweightCharts;
  if(st === 'dotted') return (LW && LW.LineStyle && LW.LineStyle.Dotted != null) ? LW.LineStyle.Dotted : 1;
  if(st === 'dashed') return (LW && LW.LineStyle && LW.LineStyle.Dashed != null) ? LW.LineStyle.Dashed : 2;
  return 0;
}
function ewRebuild(){
  ewClear();
  if(!EW_ON || window.__EW_FAILED || !window.ElliottWaveLux || !CHART || !CSERIES || !chartBars.length) return;
  const LW = window.LightweightCharts;
  const lastT = chartBars[chartBars.length - 1].time;
  const CFGS = [
    { len: 4,  color: '#ff5b6a' },
    { len: 8,  color: '#4da3ff' },
    { len: 16, color: '#e6edf3' },
  ];
  const marks = [], infos = [];
  for(const cfg of CFGS){
    let res = null;
    try{ res = window.ElliottWaveLux.compute(chartBars, { len: cfg.len, color: cfg.color }); }catch(e){ continue; }
    if(res && res.info) infos.push('[' + cfg.len + '] ' + res.info);
    if(!res) continue;
    for(const ln of (res.lines || [])){
      if(ln.t1 > lastT) continue;
      try{
        const s = CHART.addSeries(LW.LineSeries, {
          color: ln.color || cfg.color, lineWidth: 1, lineStyle: ewStyleOf(ln.style || 'solid'),
          lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
          pointMarkersVisible: false,
        });
        s.setData([{ time: ln.t1, value: ln.p1 }, { time: Math.min(ln.t2, lastT), value: ln.p2 }]);
        EW_SERIES.push(s);
      }catch(e){}
    }
    for(const fb of (res.fibs || [])){
      try{
        const s = CHART.addSeries(LW.LineSeries, {
          color: fb.color || cfg.color, lineWidth: 1, lineStyle: ewStyleOf(fb.style || 'solid'),
          lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
          pointMarkersVisible: false,
        });
        s.setData([{ time: fb.t1, value: fb.price }, { time: Math.min(fb.t2, lastT), value: fb.price }]);
        EW_SERIES.push(s);
      }catch(e){}
    }
    for(const m of (res.marks || [])) marks.push(m);
  }
  marks.sort((a, b) => a.time - b.time);   // شرط المكتبة: تصاعدي صارم
  if(EW_MARKS && marks.length){ try{ EW_MARKS.setMarkers(marks); }catch(e){} }
  const noteEl = $('ew-note');
  if(noteEl) noteEl.textContent = (EW_ON && infos.length) ? ('موجات إليوت: ' + infos.join(' · ')) : '';
}
function ewMaybe(){
  if(window.__EW_FAILED || !window.ElliottWaveLux) return;
  if(!EW_ON){
    if(EW_SIG !== 'off'){
      ewClear(); EW_SIG = 'off';
      const n = $('ew-note'); if(n) n.textContent = '';
    }
    return;
  }
  if(!chartBars.length) return;
  const sig = [chartSym, (ALLSTATE && ALLSTATE.entry_timeframe) || '5m', chartBars.length, chartBars[chartBars.length - 1].time].join('|');
  if(sig === EW_SIG) return;
  EW_SIG = sig;
  ewRebuild();
}

// ═══ [FE1.9.12] موجات المحرك — الحساب من الاستراتيجية نفسها عبر /api/ew_strategy ═══
// الزيجزاج والبنية P0–P5 ومناطق الدخول/الوقف والأهداف والمفاتيح الفيبوناتشية تأتي جاهزة
// من محرك البوت ذاته (نفس الكائنات التي تولّد الأوامر المعلقة: كاشف 0.6% + قواعد wave_validator
// + سلّم الأهداف المقصوص على قمة الأسبوع) — لا تقريب ولا إعادة تنفيذ في المتصفح.
function ewxToggle(){
  EWX_ON = !!($('ewx-toggle') && $('ewx-toggle').checked);
  EWX_SIG = '';
  ewxClear();
  try{ chartTick(true); }catch(e){}
}
function ewxClear(){
  if(CHART){
    for(const s of EWX_LINES){ try{ CSERIES.removePriceLine(s); }catch(e){} }
    if(EWX_ZZ){ try{ CHART.removeSeries(EWX_ZZ); }catch(e){} }
  }
  EWX_LINES = []; EWX_ZZ = null;
  if(EWX_MARKS){ try{ EWX_MARKS.setMarkers([]); }catch(e){} }
}
function ewxLine(price, color, title, style, width){
  try{
    EWX_LINES.push(CSERIES.createPriceLine({ price:+price, color, lineWidth:width||1,
      lineStyle:(style==null)?0:style, axisLabelVisible:true, title }));
  }catch(e){}
}
function ewxApply(d){
  ewxClear();
  if(!CHART || !CSERIES || !EWX_ON) return;
  const LW = window.LightweightCharts;
  const LS = (LW && LW.LineStyle) || {};
  const zz = d.zigzag || [];
  // زيجزاج المحرك — خط عنبري يصل محاور الاستراتيجية المؤكدة (عتبة الانعكاس 0.6%)
  if(zz.length >= 2 && chartBars.length){
    try{
      const lastT = chartBars[chartBars.length - 1].time;
      const pts = zz.map(p => ({ time: Math.floor((+p.t)/1000), value: +p.price }))
                    .filter(p => !isNaN(p.time) && p.time > 0 && p.time <= lastT);
      if(pts.length >= 2){
        EWX_ZZ = CHART.addSeries(LW.LineSeries, {
          color:'#f7c948', lineWidth:2, lineStyle:0,
          lastValueVisible:false, priceLineVisible:false, crosshairMarkerVisible:false,
          pointMarkersVisible:false,
        });
        EWX_ZZ.setData(pts);
      }
    }catch(e){ EWX_ZZ = null; }
  }
  const s = d.setup;
  const marks = [];
  if(s){
    // شارات 0–5 على محاور البنية — أزمنة فريم الكشف محاذية لشبكة فريم التنفيذ (5m/15m/1h/4h متعامدة)
    const tfSec = ({'5m':300,'15m':900,'1h':3600,'4h':14400})[(ALLSTATE&&ALLSTATE.entry_timeframe)||'5m'] || 300;
    for(const p of (s.pivots||[])){
      const t = Math.floor((+p.t)/1000); if(isNaN(t) || t <= 0) continue;
      const bt = Math.floor(t/tfSec)*tfSec;
      const peak = (p.label === 'P1' || p.label === 'P3' || p.label === 'P5');
      marks.push({ time:bt, position: peak?'aboveBar':'belowBar', color:'#f7c948',
                   shape:'circle', text: String(+p.label.slice(1)) });
    }
    marks.sort((a,b)=>a.time-b.time);
    // خطوط الاستراتيجية: دخول/وقف/إبطال/أهداف/سقف — نفس لغة خطوط الصفقات
    ewxLine(s.entry_zone.low,  '#00e5ff', 'دخول 0.382×W3', LS.Dashed!=null?LS.Dashed:2, 1);
    ewxLine(s.entry_zone.high, '#00e5ff', 'دخول ▲',        LS.Dotted!=null?LS.Dotted:1, 1);
    ewxLine(s.stop,            '#ff2d78', 'وقف P0−0.1%',   LS.Solid!=null?LS.Solid:0, 1);
    ewxLine(s.p0_invalidation, '#ff7ab8', 'إبطال P0',      LS.Dotted!=null?LS.Dotted:1, 1);
    ((s.tp&&s.tp.stages)||[]).forEach((st,i)=> ewxLine(st[0], '#22e58c', 'هدف '+(i+1), LS.Solid!=null?LS.Solid:0, 1));
    if(s.tp && s.tp.weekly_high) ewxLine(s.tp.weekly_high, '#ffb020', 'سقف أسبوع', LS.Dashed!=null?LS.Dashed:2, 2);
    // مفاتيح فيبو الكانونية التي تفحصها الاستراتيجية: W2 على الموجة 1، W4 على الموجة 3، امتدادات W3 من P2
    const ov = s.fib_overlays || {};
    (ov.w2_zone||[]).forEach(lv => ewxLine(lv.price, lv.key?'#c792ea':'#8a6bb8', 'W2 '+lv.ratio, LS.Dotted!=null?LS.Dotted:1, 1));
    (ov.w4_zone||[]).forEach(lv => ewxLine(lv.price, lv.key?'#64d8cb':'#4b9e94', 'W4 '+lv.ratio, LS.Dotted!=null?LS.Dotted:1, 1));
    (ov.w3_ext||[]).forEach(lv => ewxLine(lv.price, lv.key?'#c792ea':'#8a6bb8', 'W3 ×'+lv.ratio, LS.Dotted!=null?LS.Dotted:1, 1));
  }
  if(EWX_MARKS && marks.length){ try{ EWX_MARKS.setMarkers(marks); }catch(e){} }
  const n = $('ewx-note');
  if(!n) return;
  if(!s){
    n.textContent = 'موجات المحرك: لا بنية صاعدة حالية على ' + (d.tf||'?') + (d.note? (' — ' + d.note) : '') + ' (زيجزاج المحرك مرسوم)';
    return;
  }
  const rls = (s.rules||[]).map(r => (r.passed?'✅':'❌') + r.name).join(' ');
  const tps = ((s.tp&&s.tp.stages)||[]).map(x=>fmt(x[0])).join(' → ');
  const pct = v => (v==null?'—':(v*100).toFixed(1)+'%');
  n.innerHTML = '<b>موجات المحرك</b> · ' + esc(s.direction==='BULLISH'?'صاعدة':'هابطة')
    + ' · ' + esc(s.verdict) + ' · قواعد ' + esc(rls)
    + ' · W2 ' + esc(pct(s.retrace.w2)) + (s.retrace.w2_in_zone?' ✅':' ⚠')
    + ' · W4 ' + esc(pct(s.retrace.w4)) + (s.retrace.w4_in_zone?' ✅':' ⚠')
    + ' · عمر P5 ' + s.age_bars + ' شمعة' + (s.fresh?' (حية)':' (متقادمة — السقف '+s.max_age_bars+')')
    + (tps? ' · أهداف: '+esc(tps) : ' · لا أهداف تحت سقف الأسبوع')
    + (s.tp&&s.tp.weekly_capped? ' 🎯مقصوصة على قمة الأسبوع':'');
}
async function ewxMaybe(){
  if(!EWX_ON){
    if(EWX_SIG !== 'off'){ ewxClear(); EWX_SIG='off'; const n=$('ewx-note'); if(n) n.textContent=''; }
    return;
  }
  if(!CHART || !CSERIES || !chartSym || document.hidden) return;
  const s = ALLSTATE; if(!s) return;
  const sig = [chartSym, s.signal_timeframe || '15m', chartBars.length, chartBars.length?chartBars[chartBars.length-1].time:0].join('|');
  if(sig === EWX_SIG || EWX_BUSY) return;
  EWX_SIG = sig; EWX_BUSY = true;
  try{
    const d = await api('/api/ew_strategy?symbol=' + encodeURIComponent(chartSym) + '&tf=' + encodeURIComponent(s.signal_timeframe || '15m'));
    if(EWX_ON) ewxApply(d);
  }catch(e){ /* طبقة عرض — لا تكسر الشارت عند الفشل */ }
  finally{ EWX_BUSY = false; }
}

// ═══ [EL2.1.0] طبقة مستويات القيمة — POC/VAH/VAL/VWAP من /api/scalp/levels ═══
// نفس حسابات strategies.indicators حرفيًا (Volume Profile + VWAP) — كاش 45ث في الخادم
// وكاش محلي هنا، والرموز تغيّرها تمسح الخطوط فورًا (لا خطوط قديمة على رمز جديد).
function lvlToggle(){
  LVL_ON = !!($('lvl-toggle') && $('lvl-toggle').checked);
  LVL_SIG = '';
  lvlClear();
  try{ chartTick(true); }catch(e){}
}
function lvlClear(){
  if(CHART){ for(const l of LVL_LINES){ try{ CSERIES.removePriceLine(l); }catch(e){} } }
  LVL_LINES = [];
  const n = $('lvl-note'); if(n) n.textContent = '';
}
function lvlApply(d){
  lvlClear();
  if(!CHART || !CSERIES || !LVL_ON || !d) return;
  const LW = window.LightweightCharts; const LS = (LW && LW.LineStyle) || {};
  const push = (price, color, title, style, w) => {
    if(price == null || isNaN(+price)) return;
    try{ LVL_LINES.push(CSERIES.createPriceLine({ price:+price, color, lineWidth:w||1,
      lineStyle:(style==null)?0:style, axisLabelVisible:true, title })); }catch(e){}
  };
  push(d.poc,  '#ffd24a', 'POC',  LS.Solid!=null?LS.Solid:0, 2);
  push(d.vah,  '#b026ff', 'VAH',  LS.Dashed!=null?LS.Dashed:2, 1);
  push(d.val,  '#b026ff', 'VAL',  LS.Dashed!=null?LS.Dashed:2, 1);
  push(d.vwap, '#00e5ff', 'VWAP', LS.Dotted!=null?LS.Dotted:1, 1);
  const n = $('lvl-note');
  if(n) n.textContent = (d.poc!=null ? '◈ مستويات القيمة: POC '+fmt(d.poc) : '')
    + (d.vah!=null&&d.val!=null ? ' · قيمة '+fmt(d.val)+'→'+fmt(d.vah) : '')
    + (d.vwap!=null ? ' · VWAP '+fmt(d.vwap) : '')
    + (d.source ? ' · ' + d.source : '');
}
async function lvlMaybe(){
  if(!LVL_ON){ if(LVL_SIG !== 'off'){ lvlClear(); LVL_SIG = 'off'; } return; }
  if(!CHART || !CSERIES || !chartSym || document.hidden) return;
  const s = ALLSTATE; if(!s) return;
  const tf = s.entry_timeframe || '5m';
  const sig = chartSym + '|' + tf;
  const cached = LVL_CACHE[sig];
  if(cached && Date.now() - cached._ts < 45000){
    if(LVL_SIG !== sig){ LVL_SIG = sig; lvlApply(cached); }
    return;
  }
  if(LVL_BUSY) return;
  LVL_BUSY = true;
  const reqSig = sig;
  try{
    const d = await api('/api/scalp/levels?symbol=' + encodeURIComponent(chartSym) + '&tf=' + encodeURIComponent(tf));
    if(d && d.poc != null){
      d._ts = Date.now(); LVL_CACHE[reqSig] = d;
      // سقف الكاش المحلي — درس SWR: أقدم إدخال يُطرد
      const keys = Object.keys(LVL_CACHE);
      if(keys.length > 60){
        let old = keys[0]; for(const k of keys) if(LVL_CACHE[k]._ts < LVL_CACHE[old]._ts) old = k;
        delete LVL_CACHE[old];
      }
      const curSig = chartSym + '|' + ((ALLSTATE && ALLSTATE.entry_timeframe) || '5m');
      if(LVL_ON && curSig === reqSig) lvlApply(d);
    }
  }catch(e){ /* طبقة عرض — لا تكسر الشارت */ }
  finally{ LVL_BUSY = false; }
}

// ═══ [EL2.2.0] نافذة الشارت العائمة — سحب بالشريط · تحجيم من الزاوية · تصغير · استعادة ═══
// الشارت نفسه (عنصر #lwc-chart) يتنقل بين المرساة المدمجة #chart-dock وجسم النافذة #cf-body —
// لا نسخ ولا إعادة تهيئة: نفس المثيل CHART يعمل في الموضعين وResizeObserver يعيد ملاءمته.
let CF_ON = false, CF_MIN = false;
const CF_SAVE = 'el2_chart_float_v1';
function chartFloatEls(){ return {win:$('chart-float'), body:$('cf-body'), dock:$('chart-dock')}; }
function chartFloatToggle(){ CF_ON ? chartFloatOff() : chartFloatOn(); }
function chartFloatOn(save){
  const e = chartFloatEls();
  if(!e.win || !e.body || !e.dock || CF_ON) return;
  CF_ON = true; CF_MIN = false;
  e.body.appendChild($('lwc-chart'));
  e.win.style.display = 'flex';
  e.win.classList.remove('min');
  const btn = $('chart-float-btn');
  if(btn){ btn.classList.add('on'); btn.textContent = '⤡ مدمج'; }
  requestAnimationFrame(()=>{ if(CHART){ try{ CHART.applyOptions({width: e.body.clientWidth, height: e.body.clientHeight}); CHART.timeScale().scrollToRealTime(); }catch(err){} } });
  if(save !== false){ try{ localStorage.setItem(CF_SAVE,'1'); }catch(err){} toast('الشارت في نافذة عائمة — اسحب شريطها للتحريك وزاويتها للتحجيم'); }
}
function chartFloatOff(save){
  const e = chartFloatEls();
  if(!e.win || !e.body || !e.dock || !CF_ON) return;
  CF_ON = false; CF_MIN = false;
  e.win.style.display = 'none';
  e.win.classList.remove('min');
  e.dock.appendChild($('lwc-chart'));
  const btn = $('chart-float-btn');
  if(btn){ btn.classList.remove('on'); btn.textContent = '⤢ عائم'; }
  requestAnimationFrame(()=>{ if(CHART){ try{ CHART.applyOptions({width: e.dock.clientWidth, height: 340}); }catch(err){} } });
  if(save !== false){ try{ localStorage.removeItem(CF_SAVE); }catch(err){} }
}
function chartFloatMin(){
  if(!CF_ON) return;
  CF_MIN = !CF_MIN;
  $('chart-float').classList.toggle('min', CF_MIN);
  if(!CF_MIN && CHART){ try{ CHART.applyOptions({width: $('cf-body').clientWidth, height: $('cf-body').clientHeight}); }catch(err){} }
}
(function chartFloatBind(){
  const win = $('chart-float'), bar = $('cf-drag'), hnd = $('cf-resize');
  if(!win || !bar || !hnd) return;
  // السحب — Pointer Events تغطي الفأرة واللمس مع setPointerCapture
  let sx=0, sy=0, ox=0, oy=0, dragging=false;
  bar.addEventListener('pointerdown', ev => {
    if(ev.target.closest('.cf-btn')) return;
    dragging = true;
    try{ bar.setPointerCapture(ev.pointerId); }catch(err){}
    sx = ev.clientX; sy = ev.clientY;
    const r = win.getBoundingClientRect(); ox = r.left; oy = r.top;
    ev.preventDefault();
  });
  bar.addEventListener('pointermove', ev => {
    if(!dragging) return;
    const nx = Math.max(4, Math.min(window.innerWidth - win.offsetWidth - 4, ox + ev.clientX - sx));
    const ny = Math.max(4, Math.min(window.innerHeight - 44, oy + ev.clientY - sy));
    win.style.left = nx + 'px'; win.style.top = ny + 'px';
    win.style.right = 'auto'; win.style.bottom = 'auto';
  });
  bar.addEventListener('pointerup', () => { dragging = false; });
  bar.addEventListener('pointercancel', () => { dragging = false; });
  // التحجيم من الزاوية
  let rsx=0, rsy=0, rsw=0, rsh=0, sizing=false;
  hnd.addEventListener('pointerdown', ev => {
    sizing = true;
    try{ hnd.setPointerCapture(ev.pointerId); }catch(err){}
    rsx = ev.clientX; rsy = ev.clientY;
    const r = win.getBoundingClientRect(); rsw = r.width; rsh = r.height;
    ev.preventDefault();
  });
  hnd.addEventListener('pointermove', ev => {
    if(!sizing) return;
    win.style.width  = Math.max(320, Math.min(window.innerWidth - 16, rsw + ev.clientX - rsx)) + 'px';
    win.style.height = Math.max(250, Math.min(window.innerHeight - 16, rsh + ev.clientY - rsy)) + 'px';
    if(CHART){ try{ CHART.applyOptions({width: $('cf-body').clientWidth, height: $('cf-body').clientHeight}); }catch(err){} }
  });
  hnd.addEventListener('pointerup', () => { sizing = false; });
  hnd.addEventListener('pointercancel', () => { sizing = false; });
  // ملاءمة الشارت لأي تغيّر حجم في حاويته (دمج/عائم/نافذة المتصفح) — بديل مستمع resize القديم
  if(window.ResizeObserver){
    new ResizeObserver(() => {
      if(!CHART) return;
      const b = $('lwc-chart');
      if(!b || !b.clientWidth) return;
      try{ CHART.applyOptions({width: b.clientWidth, height: b.clientHeight || 340}); }catch(err){}
    }).observe($('lwc-chart'));
  }
})();

async function refresh(){
  if (REFRESHING || document.hidden) return;  // [FE1.5.0] بلا تداخل طلبات ولا ضغط والإخفاء
  REFRESHING = true;
  try {
    const d = await api('/api/all');
    ALLSTATE = d;  // [FE1.9.10] الشارت يشترك في الحالة
    $('err-banner').style.display = 'none';
    try { WSSTATE = await api('/api/ws/status'); } catch(e){ WSSTATE = null; }
    renderFeed(WSSTATE);
    // [FE1.5.0] كل عارضة في حماية مستقلة — خطأ في جدول لا يجمّد البطاقات
    const safe = fn => { try { fn(); } catch(e){ console.error(e); } };
    safe(()=>renderCards(d)); safe(()=>renderScanner(d));
    safe(()=>paintTf(d.signal_timeframe || '15m'));  // [FE1.8.9] تلوين الفريم النشط
    safe(()=>chartPopulate(d));  // [FE1.9.10] قائمة رموز الشارت
    safe(()=>renderOpen(d.open_signals)); safe(()=>renderClosed(d.closed_signals));
    safe(()=>renderScalp(d));  // [EL2.0.0→EL2.1.0] الاستراتيجيات المتوازية + الأداء لكل استراتيجية
    safe(()=>renderDetections(d.detections)); safe(()=>renderNotifs(d.notifications));
    safe(()=>renderPerformance(d)); safe(()=>renderGates(d.stats));
    safe(()=>chartTick());  // [FE1.9.10] تحديث الشارت مع كل دورة
  } catch(e){
    console.error(e);
    const eb = $('err-banner');
    eb.style.display = 'block';
    eb.textContent = '⚠ فشل تحديث البيانات — ' + String(e.message||'').slice(0,140);
  } finally { REFRESHING = false; }
}

async function toggleTrading(){
  try {
    const d = await api('/api/trading/toggle', {method:'POST'});
    toast(d.message); refresh();
  } catch(e){ toast('فشل التبديل: '+e.message); }
}

// ═══ [EL2.1.0] نافذة الإعدادات — تفعيل/تعطيل الاستراتيجيات الثلاث حيًا ═══
// الحالة تُقرأ من settings.strategies في /api/all وتُحفظ في قاعدة البيانات بالخادم
// — تصمد عبر إعادة النشر. التعطيل يمنع إشارات جديدة فقط (لا مواضع يتيمة).
const STRAT_DEFS = [
  {k:'Elliott_Fibonacci', icon:'🌊', label:'موجات إليوت + فيبوناتشي', desc:'المحرك الأصلي — كشف 15م وأوامر معلقة عند 0.382'},
  {k:'SCALP_FLOW', icon:'⚡', label:'انجلال التدفق (سكالب زخم)', desc:'اندلاع CVD + SuperTrend + جدران سيولة على 5م'},
  {k:'SCALP_TREND', icon:'🐂', label:'ركوب التيار (سكالب تصحيح)', desc:'تصحيح إلى EMA20/VWAP في ترند قائم + استئناف دلتا على 5م (EL2.2.0)'},
  {k:'SCALP_SQUEEZE', icon:'💥', label:'انفجار الاختناق (سكالب تقلب)', desc:'بولنجر داخل كيلتنر + انفجار بجسمه وحجمه ودلتاه على 5م (EL2.2.0)'},
];
function openSettings(){
  renderSettingsList();
  const m = $('settings-modal'); if(m) m.style.display = 'flex';
}
function closeSettings(){ const m = $('settings-modal'); if(m) m.style.display = 'none'; }
function renderSettingsList(){
  const el = $('settings-list'); if(!el) return;
  const st = ((ALLSTATE||{}).settings||{}).strategies || {};
  el.innerHTML = STRAT_DEFS.map(t=>{
    const on = st[t.k] !== false;
    return `<div class="set-row ${on?'':'off'}">
      <div><div class="set-name">${t.icon} ${t.label}</div>
      <div class="mut small">${esc(t.desc)} · ${on?'<span style=\'color:#00ff9c\'>مفعّلة</span>':'<span style=\'color:#ff3355\'>معطّلة</span>'}</div></div>
      <label class="switch"><input type="checkbox" ${on?'checked':''} onchange="toggleStrategy('${t.k}', this)"><div class="slider"></div></label>
    </div>`;
  }).join('');
}
async function toggleStrategy(name, el){
  try{
    const d = await api('/api/strategy/toggle', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({strategy:name, enabled: el.checked})});
    toast(d.message || 'تم التبديل');
    if(ALLSTATE && d.settings) ALLSTATE.settings = d.settings;
    renderSettingsList(); refresh();
  }catch(e){ el.checked = !el.checked; toast('فشل التبديل: '+e.message); }
}

// [FE1.8.9] تبديل فريم الكشف/التنفيذ حيًا (5m/15m/1h/4h) — يحفظ في السيرفر ويصمد عبر النشر
function paintTf(cur){
  document.querySelectorAll('.tf-btn').forEach(b=>b.classList.toggle('on', b.dataset.tf===cur));
}
async function setTimeframe(tf){
  if (!confirm('تبديل فريم التحليل إلى '+tf+'؟\n\n• الأوامر الورقية المعلقة تُلغى فورًا (بلا تبريد على الرموز)\n• تُبدأ دورة كشف جديدة على الفريم المختار خلال ثوانٍ\n• الاختيار محفوظ ويصمد عبر إعادة النشر')) return;
  document.querySelectorAll('.tf-btn').forEach(b=>b.disabled=true);
  try {
    const d = await api('/api/config/timeframe', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({preset: tf})});
    toast(d.message || ('الفريم: '+tf));
    if (d.signal_timeframe) paintTf(d.signal_timeframe);
    refresh();
  } catch(e){ toast('فشل تبديل الفريم: '+e.message); }
  finally { document.querySelectorAll('.tf-btn').forEach(b=>b.disabled=false); }
}

// [FE1.4.0] زر التداول الحقيقي — مثل V9: تفعيل يتطلب مفاتيح + فحص اتصال ناجح من السيرفر
async function toggleReal(el){
  const target = el.checked;
  if (target && !confirm('⚠ تشغيل التداول الحقيقي؟\n\nستُنفَّذ الإشارات الجديدة بأوامر فعلية على حسابك في Binance:\n• شراء LIMIT حقيقي عند فيبو 0.382\n• بيع سوق حقيقي عند الوقف/الهدف\n• بقواعد باينانس الكاملة وسقف أمان لكل أمر\n\nتأكد من ضبط المفاتيح (BINANCE_API_KEY / SECRET) وتوفر رصيد USDT.')) {
    el.checked = REAL_MODE; return;
  }
  if (!target && !confirm('إيقاف التداول الحقيقي والعودة للوضع الورقي الآمن؟\n(الصفقات الحقيقية المفتوحة ستستمر بالإدارة حتى إغلاقها)')) {
    el.checked = REAL_MODE; return;
  }
  REAL_BUSY = true;  // [FE1.5.0] الاستقصاء لا يعيد ضبط المفتاح أثناء الطلب
  try {
    const d = await api('/api/trading/real', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({enable: target})});
    toast(d.message || 'تم التبديل'); refresh();
  } catch(e){ el.checked = !target; toast('فشل التبديل: ' + e.message); }
  finally { REAL_BUSY = false; }
}

// [FE1.5.0] زر فحص الكون — يبدأ الفحص في خيط منفصل بالسيرفر والنتائج تظهر تدريجيًا
let SCAN_BUSY = false;
async function scanNow(){
  if (SCAN_BUSY) { toast('الفحص بدأ بالفعل — انتظر النتائج'); return; }
  SCAN_BUSY = true;
  const btn = $('scan-btn');
  btn.disabled = true; btn.textContent = '⏳ جارٍ الفحص...';
  try {
    const d = await api('/api/scan/run', {method:'POST'});
    toast(d.message || 'بدأ الفحص');
    setTimeout(refresh, 5000); setTimeout(refresh, 25000); setTimeout(refresh, 55000);
  } catch(e){ toast('فشل بدء الفحص: '+e.message); }
  finally { SCAN_BUSY = false; btn.disabled = false; btn.textContent = '🛰 فحص الآن'; }
}

async function closeTrade(id, symbol){
  if(!confirm('إغلاق صفقة '+symbol+' بسعر السوق الحالي؟\n(الحقيقية: بيع سوق فعلي على باينانس)')) return;
  try {
    const d = await api('/api/trades/close', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id})});
    toast(d.message || 'أُغلقت الصفقة'); refresh();
  } catch(e){ toast('فشل الإغلاق: '+e.message); }
}

async function cancelOrder(id, symbol){
  if(!confirm('إلغاء الأمر المعلق على '+symbol+'؟\n(الحقيقية: إلغاء الأمر الفعلي على باينانس)')) return;
  try {
    const d = await api('/api/trades/cancel', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id})});
    toast(d.message || 'أُلغي الأمر'); refresh();
  } catch(e){ toast('فشل الإلغاء: '+e.message); }
}

async function resetStats(){
  if(!confirm('تصفير كل الإحصائيات والصفقات وإرجاع الرصيد الورقي للبداية؟\n(تُأرشف الصفقات تلقائيًا — آخر 3 أرشيفات)')) return;
  const word = (prompt('للتأكيد اكتب RESET ثم اضغط موافق:') || '').trim().toUpperCase();
  if(word !== 'RESET'){ toast('لم يُؤكد التصفير — أُلغي'); return; }
  try {
    const d = await api('/api/stats/reset', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({confirm:'RESET'})});
    toast(d.message || d.error || 'تم'); refresh();
  } catch(e){ toast('فشل التصفير: '+e.message); }
}

try{ if(localStorage.getItem(CF_SAVE)==='1') chartFloatOn(false); }catch(e){}
refresh();
setInterval(refresh, 30000);
// [FE1.9.10] نبض الشارت المستقل — أسرع من دورة اللوحة (30ث) ليشعر بالحياة: الشمعة الجارية
// تتنفس من السعر الحي كل 8ث (الكاش يُجلب كل 8ث، والخطوط تُعاد الرسم عند تغيّر الصف)
setInterval(()=>{ try{ chartTick(); }catch(e){} }, 8000);
// [FE1.5.0] إيقاف الضغط والإخفاء + تحديث فوري عند العودة للتبويب
// ═══ [FE1.9.13] اللمسة الفنية — طبقة حيوية عرضية خالصة ═══
// مراقب وميض القيم: عند تغيّر نص أي بطاقة يومض توهجها لحظة — لا يقرأ ولا يعدّل أي بيانات
(function(){
  if(!window.MutationObserver) return;
  const seen = new Map();
  let scheduled = false;
  const scan = () => {
    scheduled = false;
    document.querySelectorAll('.val').forEach(el => {
      const t = el.textContent;
      if(seen.has(el) && seen.get(el) !== t){
        el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
      }
      seen.set(el, t);
    });
  };
  new MutationObserver(() => {
    if(!scheduled){ scheduled = true; setTimeout(scan, 120); }
  }).observe(document.body, { subtree:true, childList:true, characterData:true });
})();
document.addEventListener('visibilitychange', () => { if(!document.hidden) refresh(); });
</script>
</body>
</html>"""
