/* task-20 机制取证：不靠 window resize，只让**容器宽度**变（侧栏展开/收起、滚动条出现、
 * 单双栏切换都属于这一类），看滑块会不会停在旧尺寸。
 * 三个变体：N=直接改 .i18n-seg 宽度；P=改卡片宽度（模拟滚动条挤窄）；Q=切 vm.navOpen（真实侧栏）。
 */
(function () {
  var R = { steps: [], errors: [], note: 'task-20 mechanism: width change without resize', ready: false };
  function p(v) { return Math.round(v * 100) / 100; }
  function rect(el) { if (!el) return null; var b = el.getBoundingClientRect(); return { x: p(b.left), y: p(b.top), w: p(b.width), h: p(b.height) }; }
  function vm() { return window.__TOOLSGCP_APP__; }
  function segOf(cls) { return document.querySelector(cls); }
  function itemsOf(cls) { var s = segOf(cls); return s ? [].slice.call(s.querySelectorAll('.seg-item')) : []; }
  function thumbOf(cls) { var s = segOf(cls); return s ? s.querySelector('.seg-thumb') : null; }
  function snap(tag, cls) {
    try {
      var s = segOf(cls), on = s ? s.querySelector('.seg-item.is-on') : null, th = thumbOf(cls);
      var t = rect(th), o = rect(on);
      R.steps.push({ tag: tag, segFound: !!s, segRect: rect(s), thumb: t, on: o, onText: on ? (on.textContent || '').trim().slice(0, 8) : null,
        dx: (t && o) ? p(t.x - o.x) : null, dw: (t && o) ? p(t.w - o.w) : null,
        inline: th ? { left: th.style.left, width: th.style.width } : null,
        itemWidths: itemsOf(cls).map(function (i) { return p(i.getBoundingClientRect().width); }) });
    } catch (e) { R.errors.push('snap ' + tag + ': ' + e); }
  }
  function txt(el) { return el ? (el.textContent || '').trim() : null; }
  function clickText(sel, want) { var hit = null; [].slice.call(document.querySelectorAll(sel)).forEach(function (b) { if (txt(b) === want) hit = b; }); if (hit) hit.click(); return !!hit; }
  function after(ms, fn) { setTimeout(function () { try { fn(); } catch (e) { R.errors.push('step: ' + e); } }, ms); }
  function post() { try { fetch('/audit?page=seg_live', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(R) }); } catch (e) { R.errors.push('post: ' + e); } }
  function when(cond, cb, tag, tries) { if (cond()) { R[tag] = true; return cb(); } if ((tries || 0) > 300) { R.errors.push('等不到 ' + tag); post(); return; } setTimeout(function () { when(cond, cb, tag, (tries || 0) + 1); }, 100); }
  when(function () { return !!vm(); }, function () {
    after(300, function () { R.navMore = clickText('.nav-item', '更多'); });
    after(700, function () { R.openedMaker = clickText('.more-item', '提交软件'); });
    when(function () { return itemsOf('.i18n-seg').length >= 2 && !!thumbOf('.i18n-seg'); }, function () {
      R.ready = true;
      snap('N0_基线', '.i18n-seg');
      // N：直接把分段改窄 200px（等价于"内容区被挤窄"，但没有任何 resize 事件）
      after(200, function () { var s = segOf('.i18n-seg'); s.style.width = (s.getBoundingClientRect().width - 200) + 'px'; });
      after(500, function () { snap('N1_容器变窄300ms', '.i18n-seg'); });
      after(1700, function () { snap('N2_容器变窄1500ms', '.i18n-seg'); });
      after(1800, function () { segOf('.i18n-seg').style.width = ''; });
      after(2100, function () { snap('N3_还原后', '.i18n-seg'); });
      // P：切到 English 之后再挤窄（同时有点击动画，验证动画结束后的终态）
      after(2200, function () { var it = itemsOf('.i18n-seg'); if (it[2]) it[2].click(); });
      after(2600, function () { var s = segOf('.i18n-seg'); s.style.width = (s.getBoundingClientRect().width - 150) + 'px'; });
      after(3200, function () { snap('P1_切English后挤窄', '.i18n-seg'); });
      after(4400, function () { snap('P2_挤窄后1200ms', '.i18n-seg'); });
      after(4500, function () { segOf('.i18n-seg').style.width = ''; });
      // Q：真实的侧栏展开/收起（若 vm 暴露了开关）
      after(4600, function () {
        var v = vm();
        R.navKeys = v ? Object.keys(v).filter(function (k) { return /nav/i.test(k); }) : [];
        if (v && typeof v.navOpen === 'boolean') { v.navOpen = !v.navOpen; R.toggled = 'navOpen'; }
        else if (v && v.navOpen) { v.navOpen.value = !v.navOpen.value; R.toggled = 'navOpen.value'; }
      });
      after(5200, function () { snap('Q1_侧栏切换后', '.i18n-seg'); });
      after(6400, function () { snap('Q2_侧栏切换1200ms', '.i18n-seg'); post(); });
    }, 'segReady');
  }, 'appReady');
})();
