/*!
 * elliott-wave.js — [FE1.9.11] مؤشر «Elliott Wave» على الشارت الحي
 * نقل حرفي لمنطق مؤشر Pine Script v5: «Elliott Wave [LuxAlgo]»
 *   © LuxAlgo — https://www.tradingview.com/u/LuxAlgo/
 *   الترخيص الأصلي: CC BY-NC-SA 4.0 (Attribution-NonCommercial-ShareAlike)
 *   https://creativecommons.org/licenses/by-nc-sa/4.0/
 * الاستخدام هنا: عرض شخصي/تعليمي داخل لوحة تحكم بوت خاص (غير تجاري) مع الإسناد
 * الكامل أعلاه وفي تذييل اللوحة — لا يُستخدم هذا الملف تجاريًا بموجب الرخصة.
 *
 * المنطق المنقول (بنفس دلالات Pine شمعةً شمعة):
 *   - زيجزاج بثلاثة أطوال (4/8/16) من المحاور المؤكدة pivothigh/pivotlow(left,1)
 *   - كشف الموجة الدافعة 12345 (قواعد LuxAlgo: W3 ليست الأقصر + عدم التداخل)
 *   - كشف التصحيح ABC بعد الدافع (حدود 0.854 من مدى الدافع + صندوق التصحيح)
 *   - إبطال الأنماط: الدافع يُنقَّط (dot) والتصحيح يُشرَّط (dash) مع إخفاء شاراته
 *   - دمج الشارات '(5) (1)' و'(b) (1)'/'(c) (2)' عند التطابق (كما في islast)
 *   - خطوط فيبو 0.500/0.618/0.764/0.854 من نهاية الموجة 5 للنمط الأخير السليم
 *     (تُلغى إن طُوّر تصحيح ABC فوقها، وتنقّط عند كسر مستوى 0.854)
 *   - دائرة «بداية موجة جديدة محتملة» بعد اكتمال دافع + تصحيح
 *   - علامة ✕ عند كسر صندوق التصحيح (استئناف الاتجاه)
 *
 * الواجهة: ElliottWaveLux.compute(bars, {len, color}) →
 *   { lines:[{t1,p1,t2,p2,style,color}], fibs:[{t1,t2,price,level,style,color}],
 *     marks:[{time,position,shape,text,color}], info:'...' }
 *   bars = [{time(ثوانٍ), open, high, low, close}] تصاعدية — نفس تغذية الشارت.
 * فارق عرضي مقصود واحد: خطوط فيبو تنتهي عند آخر شمعة بدل التمدد 10 شموع
 * مستقبلًا (يمنع تغيّر مدى الزمن في المكتبة)، والعمود الوصّيل للفيبو يُترك
 * (زخرفة ثانوية لا تؤثر على القراءة).
 */
(function (global) {
  'use strict';

  function hexToRgba(hex, a) {
    var h = String(hex || '#e6edf3').replace('#', '');
    if (h.length === 3) h = h.split('').map(function (c) { return c + c; }).join('');
    var n = parseInt(h, 16);
    if (isNaN(n)) return 'rgba(230,237,243,' + a + ')';
    return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
  }

  // ta.pivothigh(src, left, 1) — المرشح عند الشمعة i-1 ونافذته [i-1-left .. i]، صرامة تامة (أي تعادل يُسقط)
  function pivotHigh(v, left, i) {
    var c = i - 1;
    if (c < left) return null;
    var p = v[c];
    for (var k = c - left; k <= c + 1; k++) {
      if (k === c) continue;
      if (v[k] >= p) return null;
    }
    return p;
  }
  function pivotLow(v, left, i) {
    var c = i - 1;
    if (c < left) return null;
    var p = v[c];
    for (var k2 = c - left; k2 <= c + 1; k2++) {
      if (k2 === c) continue;
      if (v[k2] <= p) return null;
    }
    return p;
  }

  function compute(bars, opts) {
    opts = opts || {};
    var len = Math.max(1, (opts.len | 0) || 4);
    var color = opts.color || '#e6edf3';
    var out = { lines: [], fibs: [], marks: [], info: '' };
    if (!Array.isArray(bars) || bars.length < len + 4) return out;

    var N = bars.length;
    var hi = [], lo = [], times = [];
    for (var b = 0; b < N; b++) {
      hi.push(+bars[b].high); lo.push(+bars[b].low); times.push(bars[b].time);
    }
    var idxOf = null; // (مستغنى — الحالة الداخلية بأرقام الشموع كما في Pine، والتحويل للزمن عند المخرجات)
    var tfSec = N > 1 ? Math.max(1, (times[N - 1] - times[N - 2]) || 300) : 300;
    var lastT = times[N - 1];
    var tOf = function (x) { return (x != null && times[x] != null) ? times[x] : lastT; };
    function hasABCLocal(g) { return !!(g.bC && g.bC.x > g.b[4].x); }

    var zz = [];    // [0] الأحدث {d,x,y} — مكدس الزيجزاج (كما مصفوفات Pine)
    var aew = [];   // [0] الأحدث — الموجات الدافعة مع تصحيحاتها
    var A = function (k) { return zz[k] || null; };
    var seg = function (p1, p2) { return { x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y }; };
    var pushZ = function (d, x, y) { zz.unshift({ d: d, x: x, y: y }); if (zz.length > 12) zz.pop(); };

    // isSame — مواضع _1.._4 الحالية تطابق نقاط الإنشاء (يحدث فقط مع استبدال/تجاهل المحور)
    function sameStack(g) {
      var a1 = A(5), a2 = A(4), a3 = A(3), a4 = A(2);
      if (!g || !g.l || !a1 || !a2 || !a3 || !a4) return false;
      return a1.x === g.l[0].x1 && a2.x === g.l[1].x1 && a3.x === g.l[2].x1 && a4.x === g.l[3].x1;
    }
    function dotWave(g) {  // method dot() — إبطال الدافع: تنقيط الخطوط وإخفاء الشارات
      g.on = false; g.dotted = true;
      for (var i = 0; i < g.b.length; i++) g.b[i].hidden = true;
    }
    function dashWave(g) { // method dash() — إبطال التصحيح: شرططة الخطوط وإخفاء الشارات والصندوق
      g.dashed = true;
      if (g.bA) g.bA.hidden = true;
      if (g.bB) g.bB.hidden = true;
      if (g.bC) g.bC.hidden = true;
    }

    // ── فرع القمة: كشف دافع صاعدة + تصحيح دافع هابطة ──
    function processPH(x6, y6) {
      var p5 = A(1), p4 = A(2), p3 = A(3), p2 = A(4), p1 = A(5);
      if (!(p1 && p2 && p3 && p4 && p5)) return;
      var g0 = aew[0] || null;
      var W5 = y6 - p5.y, W3 = p4.y - p3.y, W1 = p2.y - p1.y;
      var mn = Math.min(W1, W3, W5);
      var isWave = (W3 !== mn) && (y6 > p4.y) && (p3.y > p1.y) && (p5.y > p2.y);
      var same = sameStack(g0);
      if (isWave) {
        if (same) {                       // تمديد الموجة 5 إلى القمة الأعلى (مسار الاستبدال)
          g0.l[4].x2 = x6; g0.l[4].y2 = y6;
          g0.b[4].x = x6; g0.b[4].y = y6;
        } else {
          var tx = '(1)';
          var prev = aew[0] || null;      // دمج '(5) (1)' حين تبدأ موجة جديدة من قمة (5) السابقة
          if (prev && prev.b && prev.b[4] && p2.x === prev.b[4].x) {
            tx = '(5) (1)'; prev.b[4].text = '';
          }
          aew.unshift({
            l: [seg(p1, p2), seg(p2, p3), seg(p3, p4), seg(p4, p5), seg(p5, { x: x6, y: y6 })],
            b: [
              { x: p2.x, y: p2.y, text: tx, pos: 'above' },
              { x: p3.x, y: p3.y, text: '(2)', pos: 'below' },
              { x: p4.x, y: p4.y, text: '(3)', pos: 'above' },
              { x: p5.x, y: p5.y, text: '(4)', pos: 'below' },
              { x: x6, y: y6, text: '(5)', pos: 'above' }
            ],
            on: true, dir: 1, dotted: false, dashed: false,
            lA: null, lB: null, lC: null, bA: null, bB: null, bC: null,
            bx: null, next: false, lb: null
          });
          if (aew.length > 8) aew.pop();
        }
      } else if (same && g0 && g0.on) {
        dotWave(g0);
      }
      // [ABC] تصحيح دافع هابعة — يُبنى عند قمة (c) بأثر رجعي من المكدس
      var gw = aew[0] || null;
      if (gw && gw.l) {
        var diff = Math.abs(gw.l[4].y2 - gw.l[0].y1);
        if (gw.dir === -1 && diff > 0) {
          var getX = gw.l[4].x2, getY = gw.l[4].y2;
          var a5 = A(5), a4 = A(4), a3 = A(3), a2 = A(2), a1 = A(1);
          var s2 = !!(a5 && a4 && a3 && a5.x === gw.l[2].x2 && a4.x === gw.l[3].x2 && a3.x === gw.l[4].x2);
          var valid = !!(a3 && a3.x === getX) && (y6 < getY + diff * 0.854) &&
                      (a2.y < getY + diff * 0.854) && (a1.y > getY);
          if (valid) {
            var width = x6 - a4.x;
            if (s2 && gw.bA && gw.bA.x > a3.x) {          // تمديد (c)
              gw.lC.x1 = a1.x; gw.lC.y1 = a1.y; gw.lC.x2 = x6; gw.lC.y2 = y6;
              gw.bC.x = x6; gw.bC.y = y6;
              if (gw.bx) { gw.bx.x1 = x6; gw.bx.top = y6; gw.bx.x2 = x6 + width; }
            } else {
              gw.lA = seg(a3, a2); gw.lB = seg(a2, a1); gw.lC = seg(a1, { x: x6, y: y6 });
              gw.bA = { x: a2.x, y: a2.y, text: '(a)', pos: 'above' };
              gw.bB = { x: a1.x, y: a1.y, text: '(b)', pos: 'below' };
              gw.bC = { x: x6, y: y6, text: '(c)', pos: 'above' };
              gw.bx = { x1: x6, top: y6, x2: x6 + width, bottom: a2.y };
            }
          } else if (s2 && gw.bA && gw.bA.x > a3.x) {
            dashWave(gw);
          }
        }
        // [بداية دافع جديدة محتملة؟] بعد دافع صاعدة + اكتمال تصحيحه
        if (gw.dir === 1 && !gw.next && gw.bC && aew[0] === gw && A(1) && A(1).x === gw.bC.x && y6 > gw.b[4].y) {
          gw.next = true;
          gw.lb = { x: x6, pos: 'above' };
        }
      }
    }

    // ── فرع القاع: كشف دافع هابعة + تصحيح دافع صاعدة (مرآة مقيدة بحروف Pine) ──
    function processPL(x6, y6) {
      var p5 = A(1), p4 = A(2), p3 = A(3), p2 = A(4), p1 = A(5);
      if (!(p1 && p2 && p3 && p4 && p5)) return;
      var g0 = aew[0] || null;
      var W5 = p5.y - y6, W3 = p3.y - p4.y, W1 = p1.y - p2.y;
      var mn = Math.min(W1, W3, W5);
      var isWave = (W3 !== mn) && (p4.y > y6) && (p1.y > p3.y) && (p2.y > p5.y);
      var same = sameStack(g0);
      if (isWave) {
        if (same) {
          g0.l[4].x2 = x6; g0.l[4].y2 = y6;
          g0.b[4].x = x6; g0.b[4].y = y6;
        } else {
          var tx = '(1)';
          var prev = aew[0] || null;
          if (prev && prev.b && prev.b[4] && p2.x === prev.b[4].x) {
            tx = '(5) (1)'; prev.b[4].text = '';
          }
          aew.unshift({
            l: [seg(p1, p2), seg(p2, p3), seg(p3, p4), seg(p4, p5), seg(p5, { x: x6, y: y6 })],
            b: [
              { x: p2.x, y: p2.y, text: tx, pos: 'below' },
              { x: p3.x, y: p3.y, text: '(2)', pos: 'above' },
              { x: p4.x, y: p4.y, text: '(3)', pos: 'below' },
              { x: p5.x, y: p5.y, text: '(4)', pos: 'above' },
              { x: x6, y: y6, text: '(5)', pos: 'below' }
            ],
            on: true, dir: -1, dotted: false, dashed: false,
            lA: null, lB: null, lC: null, bA: null, bB: null, bC: null,
            bx: null, next: false, lb: null
          });
          if (aew.length > 8) aew.pop();
        }
      } else if (same && g0 && g0.on) {
        dotWave(g0);
      }
      // [ABC] تصحيح دافع صاعدة — يُبنى عند قاع (c)
      var gw = aew[0] || null;
      if (gw && gw.l) {
        var diff = Math.abs(gw.l[4].y2 - gw.l[0].y1);
        if (gw.dir === 1 && diff > 0) {
          var getX = gw.l[4].x2, getY = gw.l[4].y2;
          var a5 = A(5), a4 = A(4), a3 = A(3), a2 = A(2), a1 = A(1);
          var s2 = !!(a5 && a4 && a3 && a5.x === gw.l[2].x2 && a4.x === gw.l[3].x2 && a3.x === gw.l[4].x2);
          var valid = !!(a3 && a3.x === getX) && (y6 > getY - diff * 0.854) &&
                      (a2.y > getY - diff * 0.854) && (a1.y < getY);
          if (valid) {
            var width = x6 - a4.x;
            if (s2 && gw.bA && gw.bA.x > a3.x) {
              gw.lC.x1 = a1.x; gw.lC.y1 = a1.y; gw.lC.x2 = x6; gw.lC.y2 = y6;
              gw.bC.x = x6; gw.bC.y = y6;
              if (gw.bx) { gw.bx.x1 = x6; gw.bx.top = y6; gw.bx.x2 = x6 + width; }
            } else {
              gw.lA = seg(a3, a2); gw.lB = seg(a2, a1); gw.lC = seg(a1, { x: x6, y: y6 });
              gw.bA = { x: a2.x, y: a2.y, text: '(a)', pos: 'below' };
              gw.bB = { x: a1.x, y: a1.y, text: '(b)', pos: 'above' };
              gw.bC = { x: x6, y: y6, text: '(c)', pos: 'below' };
              gw.bx = { x1: x6, top: y6, x2: x6 + width, bottom: a2.y };
            }
          } else if (s2 && gw.bA && gw.bA.x > a3.x) {
            dashWave(gw);
          }
        }
        // [بداية دافع هابعة جديدة محتملة؟]
        if (gw.dir === -1 && !gw.next && gw.bC && aew[0] === gw && A(1) && A(1).x === gw.bC.x && y6 < gw.b[4].y) {
          gw.next = true;
          gw.lb = { x: x6, pos: 'below' };
        }
      }
    }

    // ── المحاكاة شمعةً شمعة (كما ينفذ Pine كل شريط) ──
    for (var i = 1; i < N; i++) {
      var ph = pivotHigh(hi, len, i);
      var pl = pivotLow(lo, len, i);
      if (ph !== null) {
        var xh = i - 1;
        var topH = zz[0];
        var dirH = topH ? topH.d : 0;
        if (dirH < 1) pushZ(1, xh, ph);
        else if (topH && dirH === 1 && ph > topH.y) { topH.x = xh; topH.y = ph; }
        processPH(xh, ph);
      }
      if (pl !== null) {
        var xl = i - 1;
        var topL = zz[0];
        var dirL = topL ? topL.d : 0;
        if (dirL > -1) pushZ(-1, xl, pl);
        else if (topL && dirL === -1 && pl < topL.y) { topL.x = xl; topL.y = pl; }
        processPL(xl, pl);
      }
    }

    // ── كسر صندوق التصحيح (علامة ✕ — استئناف الاتجاه بعد التصحيح) ──
    var gB = aew[0] || null;
    if (gB && gB.bx && !gB.dashed) {
      var bx = gB.bx;
      var kEnd = Math.min(bx.x2, N - 1);
      for (var k = bx.x1 + 1; k <= kEnd; k++) {
        var broke = false;
        if (gB.dir === 1) broke = (lo[k] < bx.bottom) && (lo[k - 1] >= bx.bottom);
        else broke = (hi[k] > bx.top) && (hi[k - 1] <= bx.top);
        if (broke) {
          out.marks.push({
            time: times[k],
            position: gB.dir === 1 ? 'belowBar' : 'aboveBar',
            shape: 'square', text: '✕', color: '#ff2d78'
          });
          break;
        }
      }
    }

    // ── التسوية النهائية: دمج الشارات المتطابقة + خطوط فيبو (كتلة islast) ──
    var g0 = aew[0] || null, g1 = aew[1] || null;
    if (g0 && g1 && g0.b && g0.b[1] && g1.bC && (g0.b[1].x === g1.bC.x)) {
      // (2) الحالية فوق (c) السابقة → إخفاء (1)(2) الجديدتين ودمج النصين في السابقة
      g0.b[0].hidden = true; g0.b[1].hidden = true;
      g1.bB.text = String(g1.bB.text || '').replace('(b)', '(b) (1)');
      g1.bC.text = String(g1.bC.text || '').replace('(c)', '(c) (2)');
    }

    if (g0 && g0.l) {
      var hasABC = !!(g0.bC && g0.bC.x > g0.b[4].x);
      if (g0.on && !hasABC) {
        var y0 = g0.l[0].y1, y6f = g0.l[4].y2, x6f = g0.l[4].x2;
        var difff = Math.abs(y6f - y0);
        var startK = x6f;
        if (difff > 0 && startK != null && startK < N) {
          var bull = g0.dir === 1;
          var L854 = y6f + (bull ? -1 : 1) * difff * 0.854;
          var broken = false;
          for (var k2 = startK; k2 < N; k2++) {
            if (bull ? (lo[k2] < L854) : (hi[k2] > L854)) { broken = true; break; }
          }
          var endT = Math.min(times[x6f] + 10 * tfSec, lastT);
          var alphas = { '0.5': 0.5, '0.618': 0.62, '0.764': 0.76, '0.854': 0.85 };
          var levels = [0.5, 0.618, 0.764, 0.854];
          for (var li = 0; li < levels.length; li++) {
            var lv = levels[li];
            out.fibs.push({
              t1: times[x6f], t2: endT,
              price: y6f + (bull ? -1 : 1) * difff * lv,
              level: lv,
              style: broken ? 'dotted' : 'solid',
              color: hexToRgba(color, alphas[String(lv)])
            });
          }
        }
      }
    }

    // ── تجهيز العرض: آخر 4 أنماط لكل طول (السطر والشارات والصندوق) — تحويل أرقام الشموع إلى أزمنة ──
    var RENDER_WAVES = 4;
    for (var w = 0; w < Math.min(aew.length, RENDER_WAVES); w++) {
      var g = aew[w];
      for (var li2 = 0; li2 < 5; li2++) {
        out.lines.push({
          t1: tOf(g.l[li2].x1), p1: g.l[li2].y1, t2: tOf(g.l[li2].x2), p2: g.l[li2].y2,
          style: g.dotted ? 'dotted' : 'solid', color: color
        });
      }
      if (g.lA && !g.dashed) {
        out.lines.push({ t1: tOf(g.lA.x1), p1: g.lA.y1, t2: tOf(g.lA.x2), p2: g.lA.y2, style: 'solid', color: color });
        out.lines.push({ t1: tOf(g.lB.x1), p1: g.lB.y1, t2: tOf(g.lB.x2), p2: g.lB.y2, style: 'solid', color: color });
        out.lines.push({ t1: tOf(g.lC.x1), p1: g.lC.y1, t2: tOf(g.lC.x2), p2: g.lC.y2, style: 'solid', color: color });
        var tEnd = Math.min(tOf(g.bx.x1) + (g.bx.x2 - g.bx.x1) * tfSec, lastT);
        var tStart = tOf(g.bx.x1);
        out.lines.push({ t1: tStart, p1: g.bx.top, t2: tEnd, p2: g.bx.top, style: 'solid', color: hexToRgba(color, 0.4) });
        out.lines.push({ t1: tStart, p1: g.bx.bottom, t2: tEnd, p2: g.bx.bottom, style: 'solid', color: hexToRgba(color, 0.4) });
      }
      if (!g.dotted) {
        for (var bi = 0; bi < 5; bi++) {
          var lb = g.b[bi];
          if (lb.text && !lb.hidden) {
            out.marks.push({ time: tOf(lb.x), position: lb.pos === 'above' ? 'aboveBar' : 'belowBar', shape: 'circle', text: lb.text, color: color });
          }
        }
        if (!g.dashed) {
          if (g.bA && !g.bA.hidden) out.marks.push({ time: tOf(g.bA.x), position: g.bA.pos === 'above' ? 'aboveBar' : 'belowBar', shape: 'circle', text: g.bA.text, color: color });
          if (g.bB && !g.bB.hidden) out.marks.push({ time: tOf(g.bB.x), position: g.bB.pos === 'above' ? 'aboveBar' : 'belowBar', shape: 'circle', text: g.bB.text, color: color });
          if (g.bC && !g.bC.hidden) out.marks.push({ time: tOf(g.bC.x), position: g.bC.pos === 'above' ? 'aboveBar' : 'belowBar', shape: 'circle', text: g.bC.text, color: color });
        }
        if (g.lb) out.marks.push({ time: tOf(g.lb.x), position: g.lb.pos === 'above' ? 'aboveBar' : 'belowBar', shape: 'circle', text: '', color: color });
      }
    }

    // ── ملخص عربي لحالة أطول نمط ──
    if (g0 && g0.l) {
      var dirw = g0.dir === 1 ? 'دافعة صاعدة' : 'دافعة هابطة';
      var stw = g0.dotted ? 'باطلة (منقّطة)' : (g0.on ? 'نشطة' : 'مكتملة');
      var abcw = (g0.bC && !g0.dashed) ? ' · تصحيح ABC' : '';
      var fibw = (out.fibs.length && !hasABCLocal(g0)) ? ' · فيبو 0.5→0.854' : '';
      out.info = 'موجة ' + dirw + ' ' + stw + abcw + fibw;
    } else {
      out.info = 'لا نمط 12345 مكتملًا بعد';
    }

    return out;
  }

  var api = { compute: compute, hexToRgba: hexToRgba };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else global.ElliottWaveLux = api;
})(typeof window !== 'undefined' ? window : this);
