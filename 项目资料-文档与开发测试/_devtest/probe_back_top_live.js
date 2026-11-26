/* task-25 取证脚本（真浏览器里跑，由 probe_back_top_live.py 经 serve.py 的 ?js= 注入）
 * 一次只测一个页面：URL 的 ?page=search|customize 决定（serve 把它当落盘名，同时也是应用初始页）。
 * 靠点导航 + <transition> 切页去测会把「过渡时机」混进被测对象，之前就是这样反复假失败。
 * 测两件用户能直接感知的行为：
 *   1. 出现阈值：翻过 1 排卡片不亮，翻过 1.6 排才亮（阈值 = 行距 × BACK_TOP_ROW_FACTOR）；
 *   2. 回顶动画：真 rAF 下必须慢到看得见（>=800ms），scrollTop 单调收敛到 0，末帧按钮熄灭。
 * ⚠️ 时序一律轮询，不写死毫秒：serve.py 偶发并发丢静态文件，页面会比预期晚挂载。
 */
(function () {
  var TARGET = ((location.search.match(/[?&]page=([^&]*)/) || [])[1] === 'customize') ? 'customize' : 'search';
  var LABEL = TARGET === 'customize' ? '定制页' : '搜索页';
  var R = { page: TARGET, label: LABEL, checks: [], skips: [], errors: [], ready: false };
  function p(v) { return Math.round(v * 100) / 100; }
  function ok(name, cond, info) { R.checks.push({ name: name, pass: !!cond, info: info }); }
  function skip(name, info) { R.skips.push({ name: name, info: info }); }
  function scroller() {
    var list = [].slice.call(document.querySelectorAll('.page-scroll[data-scroll-key]'));
    var fb = null;
    for (var i = 0; i < list.length; i++) {
      if (list[i].getAttribute('data-scroll-key') !== TARGET) continue;
      if (list[i].scrollHeight - list[i].clientHeight > 400) return list[i];
      if (!fb) fb = list[i];
    }
    return fb;
  }
  function ball() { return document.querySelector('.back-top'); }
  function ballOn() { var b = ball(); return b ? b.classList.contains('is-on') : null; }
  function ballStyle() {
    var b = ball();
    if (!b) return null;
    var c = getComputedStyle(b);
    return { opacity: c.opacity, visibility: c.visibility, display: c.display, pointerEvents: c.pointerEvents };
  }
  // 行距按同一口径自己量一遍（不复用 app.js 的函数，免得探针跟着产品一起错）：
  // 搜索页 = .vrow 行内 height + gap；定制页 = 第一张 .card 高度 + .grid-static 的 row-gap。
  function pitch() {
    if (TARGET === 'search') {
      var row = document.querySelector('.vrow');
      if (!row) return 0;
      var h = parseFloat(row.style.height || '0') || row.getBoundingClientRect().height;
      return h + (parseFloat(row.style.gap || '0') || 0);
    }
    var grid = document.querySelector('.grid-static');
    var card = grid ? grid.querySelector('.card') : null;
    if (!card) return 0;
    var cs = getComputedStyle(grid);
    return card.getBoundingClientRect().height + ((parseFloat(cs.rowGap) || parseFloat(cs.gap) || 0));
  }
  function post() {
    try {
      fetch('/audit?page=bt_live', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(R) });
    } catch (e) { R.errors.push('post: ' + e); }
  }
  function when(cond, cb, tag, tries) {
    if (cond()) return cb();
    if ((tries || 0) > 150) {
      var dump = {};
      try {
        var c = scroller();
        dump.html = c ? (c.innerHTML || '').replace(/\s+/g, ' ').slice(0, 480) : null;
        dump.cards = document.querySelectorAll('.grid-static .card').length;
        dump.vrows = document.querySelectorAll('.vrow').length;
        dump.onboard = !!document.querySelector('.onboard-center');
        dump.ball = !!ball();
      } catch (e) { dump.err = String(e); }
      R.errors.push('等不到 ' + tag);
      ok('页面就绪：' + tag + '（' + LABEL + '）', false, dump);
      post();
      return;
    }
    setTimeout(function () { when(cond, cb, tag, (tries || 0) + 1); }, 100);
  }
  function runAnim(tag, fromPx, cb) {
    var el = scroller();
    if (!el) { R.errors.push(tag + ': 找不到滚动容器'); return cb(); }
    el.scrollTop = fromPx;
    var wantY = el.scrollTop;   // 浏览器会按可滚范围夹紧：写 336 但只剩 200 空间就是 200
    setTimeout(function () {
      var b = ball();
      if (!b) { R.errors.push(tag + ': 找不到 .back-top'); return cb(); }
      // ⚠️ 必须记下「点击那一刻」的真实 scrollTop：LONG 之后紧跟 SHORT 时，
      //    若中间有布局重算把滚动位置打回 0，start=0 ⇒ 按钮「瞬间到底」看着像产品缺陷，其实是探针自摆乌龙。
      // LONG 动画刚结束就写 SHORT 的起点时，页面自身的滚动恢复可能把位置抹回 0；补写几次拿真实起点。
      for (var repair = 0; repair < 4 && el.scrollTop < fromPx * 0.8; repair += 1) el.scrollTop = fromPx;
      var atClickY = el.scrollTop;
      var t0 = performance.now();
      var samples = [{ t: 0, y: Math.round(el.scrollTop) }];
      var iv = setInterval(function () {
        samples.push({ t: Math.round(performance.now() - t0), y: Math.round(el.scrollTop) });
        if (el.scrollTop <= 0 || performance.now() - t0 > 3200) {
          clearInterval(iv);
          var last = samples[samples.length - 1];
          var mono = true;
          for (var i = 1; i < samples.length; i++) if (samples[i].y > samples[i - 1].y + 0.5) mono = false;
          R[tag] = { fromPx: fromPx, wantY: Math.round(wantY), atClickY: Math.round(atClickY), frames: samples.length, durMs: last.t, endY: last.y, mono: mono,
                     halfWayY: samples[Math.floor(samples.length / 2)].y };
          if (atClickY <= 0) {
            skip(tag + ' 点击时滚动位置已被打回 0，不构成动画样本：' + LABEL, { fromPx: fromPx, wantY: Math.round(wantY), atClickY: Math.round(atClickY) });
            cb();
            return;
          }
          ok(tag + ' 收敛到 0：' + LABEL, last.y === 0, last);
          // 标称下限 900ms；量的是「scrollTop 归零」那一帧，比标称早约 1 个采样步 + 缓动收尾，
          // 所以门槛取 800：再低就说明 dur 公式没兜住短距离（用户看到的又是「一瞬间」）。
          ok(tag + ' 时长看得见（>=800ms）：' + LABEL, last.t >= 800, { durMs: last.t, fromPx: fromPx, nominalMin: 900 });
          ok(tag + ' 时长不拖沓（<=1750ms）：' + LABEL, last.t <= 1750, { durMs: last.t, fromPx: fromPx });
          ok(tag + ' 单调下降不回头：' + LABEL, mono, samples.slice(0, 5));
          ok(tag + ' 帧数够多（>=12）：' + LABEL, samples.length >= 12, samples.length);
          cb();
        }
      }, 40);
      b.click();
    }, 300);
  }
  function stage() {
    var el = scroller();
    var P = pitch();
    if (!el || !P) { ok('量到滚动容器与行距：' + LABEL, false, { el: !!el, pitch: P }); return post(); }
    var maxS = el.scrollHeight - el.clientHeight;
    R.geo = { pitch: p(P), threshold: p(P * 1.5), maxScroll: maxS, clientH: el.clientHeight };
    if (maxS < P * 2.2) {   // 内容不足 2.2 排：阈值测不了，算 SKIP 不算缺陷
      skip('内容不足 2.2 排，跳过阈值与时长：' + LABEL, { maxScroll: maxS, need: Math.round(P * 2.2), pitch: p(P) });
      return post();
    }
    // 单独取证：写完滚动位置 500ms 后还在不在。若被打回 0，说明应用侧的滚动恢复在偷偷改位置，
    // 那会让「刚翻过半排就点回顶」一类操作看起来像动画太快（其实是起点被清了）。
    el.scrollTop = Math.round(P * 1.6);
    setTimeout(function () {
      var held = el.scrollTop;
      ok('滚动位置写完 500ms 不被应用打回：' + LABEL, held >= P * 1.6 * 0.9, { want: Math.round(P * 1.6), held: Math.round(held) });
      settleRun();
    }, 500);
    function settleRun() {
    el.scrollTop = Math.round(P * 1.0);
    setTimeout(function () {
      ok('翻过 1 排不亮：' + LABEL, ballOn() === false, { on: ballOn(), y: Math.round(el.scrollTop), pitch: p(P) });
      el.scrollTop = Math.round(P * 1.6);
      setTimeout(function () {
        var st = ballStyle();
        ok('翻过 1.6 排出现：' + LABEL, ballOn() === true, { on: ballOn(), y: Math.round(el.scrollTop) });
        ok('出现时确实看得见（opacity≈1 且可点）：' + LABEL, !!st && parseFloat(st.opacity) > 0.9 && st.pointerEvents !== 'none', st);
        runAnim('LONG', Math.max(1600, maxS), function () {
          runAnim('SHORT', Math.round(P * 1.6), function () {
            el.scrollTop = 0;
            setTimeout(function () {
              ok('回到顶部后按钮熄灭：' + LABEL, ballOn() === false, { on: ballOn(), y: Math.round(el.scrollTop) });
              post();
            }, 420);
          });
        });
      }, 420);
    }, 420);
    }
  }
  when(function () { return !!window.__TOOLSGCP_APP__; }, function () {
    R.boot = { hasApp: true };
    when(function () { return !document.querySelector('.boot-screen'); }, function () {
      when(function () { return !!scroller(); }, function () {
        if (TARGET === 'customize' && document.querySelector('.onboard-center')) {
          /* serve.py 的 mock 设置是「干净新装」，定制页于是停在喜好引导态。
             引导态里根本没有卡片网格，回顶按钮无从谈起 —— 所以按真人流程点一次「开始」，
             把页面推进到「为你推荐」态再量。点不开就如实 SKIP（不硬造结论）。 */
          var foot = document.querySelector('.onboard-center .onboard-foot .btn-primary');
          if (!foot) {
            skip('定制页停在喜好引导态且找不到「开始」按钮', { onboard: true });
            return post();
          }
          // 「全不选」的引导态推荐是 0 条 → 页面短到没有滚动空间，测不了阈值。
          // 按真人流程先勾几个喜好再保存，让推荐网格长出内容。
          var chips = [].slice.call(document.querySelectorAll('.onboard-center .interest-chip'));
          R.chipsSeen = chips.length;
          for (var ci = 0; ci < chips.length && ci < 10; ci += 1) { if (!/✓/.test(chips[ci].textContent || '')) chips[ci].click(); }
          R.onboardClicked = (foot.textContent || '').trim();
          foot.click();
          return when(function () {
            return !!document.querySelector('.grid-static .card') && !!ball();
          }, function () { R.ready = true; stage(); }, 'customizeRecommend');
        }
        R.ready = true;
        stage();
      }, TARGET + 'Scroller');
    }, 'bootGone');
  }, 'appReady');
})();
