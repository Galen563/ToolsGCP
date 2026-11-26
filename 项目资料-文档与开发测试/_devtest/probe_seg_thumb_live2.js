/* task-20 取证第二轮：不量「空表单切语言」，量**内容真的不一样高**的时候切。
 * 覆盖三处分段：投稿页 .maker-seg（分节）、.i18n-seg（语言）、搜索页 .view-seg（排版）。
 * 每次 snap 除了 thumb/on 矩形，还记：容器宽、滚动条是否出现、maker 双栏内联样式、表单 scrollTop
 * —— 用来判断「量完之后布局又变了」这一类迟到布局（scroll 事件晚一帧才改列宽/滚动条）。
 */
(function () {
  var R = { steps: [], errors: [], note: 'task-20 round2: content-height switching', ready: false };
  function p(v) { return Math.round(v * 100) / 100; }
  function rect(el) {
    if (!el) return null;
    var b = el.getBoundingClientRect();
    return { x: p(b.left), y: p(b.top), w: p(b.width), h: p(b.height) };
  }
  function vm() { return window.__TOOLSGCP_APP__; }
  function segOf(cls) { return document.querySelector(cls); }
  function itemsOf(cls) { var s = segOf(cls); return s ? [].slice.call(s.querySelectorAll('.seg-item')) : []; }
  function thumbOf(cls) { var s = segOf(cls); return s ? s.querySelector('.seg-thumb') : null; }
  function scrollInfo() {
    var out = {};
    var f = document.querySelector('.maker-form-scroll');
    if (f) { out.form = { sw: f.scrollWidth, cw: f.clientWidth, sh: f.scrollHeight, ch: f.clientHeight, st: p(f.scrollTop), over: f.scrollHeight > f.clientHeight + 1 }; }
    var sec = document.querySelector('.maker-section-scroll');
    if (sec) { out.sec = { sw: sec.scrollWidth, cw: sec.clientWidth, sh: sec.scrollHeight, ch: sec.clientHeight, st: p(sec.scrollTop) }; }
    var b = document.querySelector('.maker-body');
    if (b) { out.body = { w: p(b.getBoundingClientRect().width), gtc: b.style.gridTemplateColumns || '(css)', ow: b.offsetWidth, cw: b.clientWidth }; }
    out.docW = window.innerWidth;
    out.hasVScroll = document.documentElement.scrollHeight > document.documentElement.clientHeight;
    return out;
  }
  function snap(tag, cls) {
    try {
      var s = segOf(cls), on = s ? s.querySelector('.seg-item.is-on') : null, th = thumbOf(cls);
      var t = rect(th), o = rect(on);
      R.steps.push({
        tag: tag + ' ' + cls, segFound: !!s, segRect: rect(s), thumbFound: !!th, thumb: t, on: o,
        onText: on ? (on.textContent || '').trim().slice(0, 12) : null,
        dx: (t && o) ? p(t.x - o.x) : null,
        dw: (t && o) ? p(t.w - o.w) : null,
        dh: (t && o) ? p(t.h - o.h) : null,
        inline: th ? { left: th.style.left, top: th.style.top, width: th.style.width, height: th.style.height } : null,
        itemWidths: itemsOf(cls).map(function (i) { return p(i.getBoundingClientRect().width); }),
        scroll: scrollInfo()
      });
    } catch (e) { R.errors.push('snap ' + tag + ': ' + e); }
  }
  function txt(el) { return el ? (el.textContent || '').trim() : null; }
  function clickText(sel, want) {
    var hit = null;
    [].slice.call(document.querySelectorAll(sel)).forEach(function (b) {
      if (txt(b) === want || (b.getAttribute('title') || '') === want) hit = b;
    });
    if (hit) hit.click();
    return !!hit;
  }
  function after(ms, fn) { setTimeout(function () { try { fn(); } catch (e) { R.errors.push('step: ' + e); } }, ms); }
  function post() {
    try { fetch('/audit?page=seg_live', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(R) }); }
    catch (e) { R.errors.push('post: ' + e); }
  }
  function when(cond, cb, tag, tries) {
    if (cond()) { R[tag] = true; return cb(); }
    if ((tries || 0) > 300) { R.errors.push('等不到 ' + tag); post(); return; }
    setTimeout(function () { when(cond, cb, tag, (tries || 0) + 1); }, 100);
  }
  var LONG = '这是一段很长的简介，用来把多语言卡片撑高，从而让滚动条与单双栏在切换语言时发生变化。'.repeat(6);
  var EMPTYISH = '短';
  function fillDesc(lang, text) {
    var v = vm();
    if (v && v.maker && v.maker.i18n && v.maker.i18n[lang]) { v.maker.i18n[lang].description = text; return true; }
    return false;
  }
  when(function () { return !!vm(); }, function () {
    after(300, function () { R.navMore = clickText('.nav-item', '更多'); });
    after(700, function () { R.openedMaker = clickText('.more-item', '提交软件'); });
    when(function () { return itemsOf('.i18n-seg').length >= 2 && !!thumbOf('.i18n-seg'); }, function () {
      R.ready = true;
      R.filled = { zh: fillDesc('简体中文', LONG), tw: fillDesc('繁體中文', EMPTYISH), en: fillDesc('English', EMPTYISH) };
      after(500, function () { snap('J0_简体长内容基线', '.i18n-seg'); });
      after(600, function () { var it = itemsOf('.i18n-seg'); if (it[2]) it[2].click(); });
      after(660, function () { snap('J1_切English_60ms', '.i18n-seg'); });
      after(900, function () { snap('J2_切English_300ms', '.i18n-seg'); });
      after(1500, function () { snap('J3_切English_900ms', '.i18n-seg'); });
      after(2200, function () { snap('J4_切English_1600ms', '.i18n-seg'); });
      // 反向：从短内容切回长内容
      after(2300, function () { var it = itemsOf('.i18n-seg'); if (it[0]) it[0].click(); });
      after(2600, function () { snap('K1_切回简体_300ms', '.i18n-seg'); });
      after(3900, function () { snap('K2_切回简体_1600ms', '.i18n-seg'); });
      // 分节切换（maker-seg）：内容高度必然变
      after(4000, function () { var it = itemsOf('.maker-seg'); R.makerSegItems = it.length; if (it[1]) it[1].click(); });
      after(4300, function () { snap('L1_换分节_300ms', '.maker-seg'); });
      after(5600, function () { snap('L2_换分节_1600ms', '.maker-seg'); });
      after(5700, function () { var it = itemsOf('.maker-seg'); if (it[0]) it[0].click(); });
      after(7300, function () { snap('L3_换回第一节_1600ms', '.maker-seg'); });
      // 搜索页排版切换
      after(7400, function () { R.navSearch = clickText('.nav-item', '搜索'); });
      when(function () { return itemsOf('.view-seg').length >= 2; }, function () {
        after(400, function () { snap('M0_view-seg基线', '.view-seg'); });
        after(500, function () { var it = itemsOf('.view-seg'); if (it[1]) it[1].click(); });
        after(800, function () { snap('M1_换排版_300ms', '.view-seg'); });
        after(2100, function () { snap('M2_换排版_1600ms', '.view-seg'); post(); });
      }, 'viewSegReady');
    }, 'segReady');
  }, 'appReady');
})();
