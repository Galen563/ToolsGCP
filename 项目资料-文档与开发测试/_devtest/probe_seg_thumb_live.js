/* task-20 取证脚本（真浏览器里跑，由 probe_seg_thumb_live.py 经 serve.py 的 ?js= 注入）
 * 量「多语言字段」卡片顶部语言分段 .i18n-seg 里那枚由 app.js 写 inline 几何的 .seg-thumb。
 * 每个 snap 同时记：滑块矩形、选中项矩形、dx/dw/dh、inline 样式、各项宽度、过渡声明。
 * ⚠️ 时序不写死毫秒：serve.py 的静态资源偶尔并发失败（vendor 大文件重试比 app.js 晚到），
 *    写死 3200ms 会量到一个没挂载的页面。改成「轮询到 app 就绪 + 分段出现」后再走时间线。
 */
(function () {
  var R = { steps: [], errors: [], note: 'task-20 i18n-seg thumb geometry', ready: false };
  function p(v) { return Math.round(v * 100) / 100; }
  function rect(el) {
    if (!el) return null;
    var b = el.getBoundingClientRect();
    return { x: p(b.left), y: p(b.top), w: p(b.width), h: p(b.height) };
  }
  function seg() { return document.querySelector('.i18n-seg'); }
  function items() { var s = seg(); return s ? [].slice.call(s.querySelectorAll('.seg-item')) : []; }
  function thumb() { var s = seg(); return s ? s.querySelector('.seg-thumb') : null; }
  function cs(el, props) {
    if (!el) return null;
    var c = getComputedStyle(el), o = {};
    props.forEach(function (k) { o[k] = c[k]; });
    return o;
  }
  function snap(tag) {
    try {
      var s = seg(), on = s ? s.querySelector('.seg-item.is-on') : null, th = thumb();
      var t = rect(th), o = rect(on);
      R.steps.push({
        tag: tag,
        segFound: !!s,
        segRect: rect(s),
        thumbFound: !!th,
        thumb: t,
        on: o,
        onText: on ? (on.textContent || '').trim() : null,
        dx: (t && o) ? p(Math.abs(t.x - o.x)) : null,
        dw: (t && o) ? p(Math.abs(t.w - o.w)) : null,
        dh: (t && o) ? p(Math.abs(t.h - o.h)) : null,
        inline: th ? { left: th.style.left, top: th.style.top, width: th.style.width, height: th.style.height } : null,
        thumbDecl: th ? cs(th, ['transitionProperty', 'transitionDuration', 'position', 'boxSizing']) : null,
        itemWidths: items().map(function (i) { return p(i.getBoundingClientRect().width); }),
        itemMinWidth: items().length ? cs(items()[0], ['minWidth', 'flexGrow', 'flexBasis']) : null,
        segClasses: s ? String(s.className) : null,
        docW: window.innerWidth
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
    try {
      fetch('/audit?page=seg_live', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(R) });
    } catch (e) { R.errors.push('post: ' + e); }
  }
  // 轮询到「app 挂载 + 分段可见」为止；超时则回报 ready:false 让驱动层重试
  function when(cond, cb, tag, tries) {
    if (cond()) { R[tag] = true; return cb(); }
    if ((tries || 0) > 250) { R[tag + '_timeout'] = true; R.errors.push('等不到 ' + tag); post(); return; }
    setTimeout(function () { when(cond, cb, tag, (tries || 0) + 1); }, 100);
  }
  when(function () { return !!window.__TOOLSGCP_APP__; }, function () {
    R.boot = { hasApp: true, bootScreen: !!document.querySelector('.boot-screen') };
    after(300, function () { R.navMore = clickText('.nav-item', '更多'); });
    after(700, function () { R.openedMaker = clickText('.more-item', '提交软件'); });
    when(function () { return items().length >= 2 && !!thumb(); }, function () {
      R.ready = true;
      snap('Z_just_ready');
      after(1500, function () { snap('A_settled_default'); });
      after(1600, function () { var it = items(); if (it[1]) it[1].click(); });
      after(1660, function () { snap('B_60ms_after_click1'); });
      after(1720, function () { snap('C_120ms_after_click1'); });
      after(1900, function () { snap('D_300ms_after_click1'); });
      after(2500, function () { snap('E_900ms_after_click1'); });
      after(2600, function () { var it = items(); if (it[2]) it[2].click(); });
      after(2720, function () { snap('F_120ms_after_click2'); });
      after(3500, function () { snap('G_900ms_after_click2'); });
      after(3600, function () { var it = items(); if (it[0]) it[0].click(); });
      after(4500, function () { snap('H_900ms_back_to_0'); });
      after(4600, function () { window.dispatchEvent(new Event('resize')); });
      after(5300, function () { snap('I_after_forced_resize'); post(); });
    }, 'segReady');
  }, 'appReady');
})();
