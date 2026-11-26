/* task-23 全量分段验收（Edge 侧，由 probe_seg_thumb_live.py --js 注入）
 *
 * 覆盖：页面上出现的**每一个** .segmented（分节 maker-seg / 多语言 i18n-seg /
 *   视图切换 view-seg / 版本变体 variant-seg / 设置页各分段），逐组做「按压态滑走 → 按压态滑回」，
 *   在终态（500ms / 1400ms）量 thumb 与选中项的 dx/dw/dh。
 *   按压态 = 先给目标项加 transform: scale(.96)（与 .seg-item:active 同一条声明），
 *   保持 150ms 后「松手 + click」，正是旧代码写坏 thumb 宽度的那条路径。
 *
 * 踩过的坑（别再犯）：旧版把分组作业在**运行中** push 到 jobs 尾部，
 *   而 "R.done + post()" 是构建期就排在尾部的作业，于是 done 先跑、驱动 0.4s 后 taskkill Edge，
 *   整轮 samples=0 空转。现在改成：一次收集整页所有分组作业，splice 到当前游标 ri 处，
 *   顺序保证「先把本页扫完，再走下一页」。
 * 只在时间线末尾 POST 一次（驱动看到报告文件就杀进程）。
 */
(function () {
  var R = { steps: [], census: {}, checks: [], errors: [], note: "task-23 sweep v2 按压态全量", done: false };
  function p(v) { return Math.round(v * 100) / 100; }
  function ok(cond, name, detail) { R.checks.push({ name: name, pass: !!cond, detail: detail }); }
  function groups() { return [].slice.call(document.querySelectorAll(".segmented")); }
  function label(el) { return (el.getAttribute("title") || (el.textContent || "")).trim().slice(0, 28); }
  function itemsOf(seg) { return [].slice.call(seg.querySelectorAll(".seg-item")); }

  function snap(wantCls, gi, name, mark) {
    try {
      var seg = resolveSeg(wantCls, gi);
      if (!seg) {
        R.steps.push({ mark: name + "|" + mark + "|GONE", idx: gi, wantCls: wantCls, groupsNow: groups().length });
        ok(false, name + " 分组#" + gi + " " + mark + " 时分组还在", "detached/缺失 cls=" + wantCls);
        return;
      }
      var on = seg.querySelector(".seg-item.is-on"), th = seg.querySelector(".seg-thumb");
      if (!on || !th) {
        R.steps.push({ mark: name + "|" + mark + "|缺件", idx: gi, cls: String(seg.className),
          onFound: !!on, thumbFound: !!th });
        return;
      }
      var tr = th.getBoundingClientRect(), or = on.getBoundingClientRect();
      R.steps.push({
        /* tag / thumb / on 是给 probe_seg_thumb_live.py 驱动看的：
           它按 tag 前缀挑终态、拿 thumb[] 与 on[] 自己算 dx/dw/dh 判 TOL=1.5，
           缺这三样它会把每一步都当"缺滑块"报 FAIL（上一轮 exit=1 就是这个）。 */
        tag: (/(500|1400)/.test(mark) ? "D_" : "X_") + name + "_" + mark,
        mark: name + "|" + mark, idx: gi, cls: String(seg.className),
        thumb: [p(tr.left), p(tr.top), p(tr.width), p(tr.height)],
        on: [p(or.left), p(or.top), p(or.width), p(or.height)],
        onText: label(on), items: itemsOf(seg).map(label),
        segW: p(seg.getBoundingClientRect().width), segClientW: seg.clientWidth,
        thumbW: p(tr.width), onW: p(or.width), onOffsetW: p(on.offsetWidth),
        thumbInline: th.style.width,
        dw: p(tr.width - or.width), dx: p(tr.left - or.left), dh: p(tr.height - or.height),
        dwLayout: p(tr.width - on.offsetWidth),
        docW: window.innerWidth
      });
    } catch (e) { R.errors.push("snap " + name + "/" + mark + ": " + e); }
  }

  /* 真人时序：按下缩放 → 保持 hold → 松手 + click */
  function pressClick(seg, i, hold, tag) {
    var its = itemsOf(seg);
    var it = its[i];
    if (!it) { R.errors.push("no item " + i + " @" + tag); return; }
    it.style.transform = "scale(.96)";
    try { it.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true })); }
    catch (e) { R.errors.push("mousedown: " + e); }
    setTimeout(function () {
      it.style.transform = "";
      try { it.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true })); }
      catch (e) { R.errors.push("mouseup: " + e); }
      it.click();
      R[tag] = "clicked";
    }, hold);
  }

  var HOLD = 160;
  /* 每步都要重新解析：maker-seg 点「使用说明」会把整张投稿卡片 v-if 掉再重建，
     构建期抓住的节点必然 detached —— 上一版 sweep 的 samples=0 之外，
     这版曾经把 i18n-seg 报成 GONE 就是这个原因（探针问题，不是产品问题）。 */
  function resolveSeg(cls, gi) {
    var gs = groups();
    if (gs[gi] && String(gs[gi].className) === cls) return gs[gi];
    for (var k = 0; k < gs.length; k++) { if (String(gs[k].className) === cls) return gs[k]; }
    return null;
  }
  /* 一组分段的一轮：整页收集好再一次性插到游标处 */
  function collectGroup(seg0, gi, name, batch) {
    var wantCls = String(seg0.className);
    var n = itemsOf(seg0).length;
    if (n < 2) {
      batch.push({ gap: 30, fn: function () {
        R.steps.push({ mark: name + "|SKIP-项数不足", idx: gi, items: n, cls: wantCls });
      } });
      return;
    }
    batch.push({ gap: HOLD + 600, fn: function () {
      var seg = resolveSeg(wantCls, gi);
      if (!seg) { R.steps.push({ mark: name + "|away|GONE", idx: gi, wantCls: wantCls }); return; }
      var its = itemsOf(seg);
      if (its.length < 2) { R.steps.push({ mark: name + "|SKIP-重解析后项数不足", idx: gi, items: its.length, cls: wantCls }); return; }
      pressClick(seg, its.length - 1, HOLD, name + "#" + gi + "_away");
    } });
    batch.push({ gap: 60, fn: function () {
      var seg = resolveSeg(wantCls, gi);
      if (!seg) { R.steps.push({ mark: name + "|back|GONE", idx: gi, wantCls: wantCls }); return; }
      pressClick(seg, 0, HOLD, name + "#" + gi + "_back");
    } });
    batch.push({ gap: 520, fn: function () {
      snap(wantCls, gi, name, "back500");
      var s = R.steps[R.steps.length - 1];
      if (s && s.dwLayout !== undefined) {
        ok(Math.abs(s.dwLayout) <= 1.5 && Math.abs(s.dx) <= 1.5 && Math.abs(s.dh) <= 1.5,
          name + " 分组#" + gi + " 滑回后 thumb 与真实项对齐（layout 口径）",
          "dwLayout=" + s.dwLayout + " dx=" + s.dx + " dh=" + s.dh +
          " thumbInline=" + s.thumbInline + " onOffsetW=" + s.onOffsetW + " onW=" + s.onW + " cls=" + s.cls);
      }
    } });
    batch.push({ gap: 900, fn: function () {
      snap(wantCls, gi, name, "back1400");
      var s = R.steps[R.steps.length - 1];
      if (s && s.dwLayout !== undefined) {
        ok(Math.abs(s.dwLayout) <= 1.5, name + " 分组#" + gi + " 1.4s 后仍未走形", "dwLayout=" + s.dwLayout);
      }
    } });
  }

  var jobs = [];
  var ri = 0;
  function push(fn, gap) { jobs.push({ fn: fn, gap: gap || 900 }); }
  function clickText(sel, want) {
    var hit = null;
    [].slice.call(document.querySelectorAll(sel)).forEach(function (b) {
      if (label(b) === want) hit = b; });
    if (hit) hit.click();
    return !!hit;
  }
  /* 本页所有 .segmented 逐组扫一遍：census 先记账，再把作业插到当前游标 */
  function sweepPage(name) {
    push(function () {
      var gs = groups();
      R.census[name] = gs.map(function (g, gi) {
        return { gi: gi, cls: String(g.className), visible: g.getBoundingClientRect().width > 0,
          items: itemsOf(g).map(label), hasThumb: !!g.querySelector(".seg-thumb") };
      });
      var batch = [];
      gs.forEach(function (g, gi) { collectGroup(g, gi, name, batch); });
      R.census[name + "_queued"] = batch.length;
      Array.prototype.splice.apply(jobs, [ri, 0].concat(batch));
    }, 200);
  }

  function run() {
    (function step() {
      if (ri >= jobs.length) { if (!R.done) post(); return; }
      var j = jobs[ri++];
      try { j.fn(); } catch (e) { R.errors.push("job@" + ri + ": " + e); }
      setTimeout(step, j.gap);
    })();
  }
  function post() {
    if (R.posted) return;
    R.posted = true;
    try {
      fetch("/audit?page=seg_live", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(R)
      });
    } catch (e) { R.errors.push("post: " + e); }
  }

  push(function () { R.boot = { hasApp: !!window.__TOOLSGCP_APP__ }; }, 300);
  push(function () { R.navMore = clickText(".nav-item", "更多"); }, 700);
  push(function () { R.openedMaker = clickText(".more-item", "提交软件"); }, 1500);
  sweepPage("MAKER");
  push(function () { R.toSearch = clickText(".nav-item", "搜索"); }, 1500);
  sweepPage("SEARCH");
  push(function () {
    var card = document.querySelector(".vlist .card, .card-grid .card, .card");
    R.openedDetail = !!card; if (card) card.click();
  }, 1800);
  sweepPage("DETAIL");
  push(function () { R.toSettings = clickText(".nav-item", "设置"); }, 1500);
  sweepPage("SETTINGS");
  /* 第二轮：切到 English 再回制作器 —— 分节/多语言分段的**文案宽度**会变，
     这正是旧代码里「量到旧格子」最容易露馅的时刻（第一轮就靠这类场景定位过 bug）。 */
  push(function () { var vm = window.__TOOLSGCP_APP__; if (vm) { vm.lang = "en"; R.langEn = vm.lang; } }, 1500);
  push(function () { R.navMore2 = clickText(".nav-item", "More") || clickText(".nav-item", "更多"); }, 700);
  push(function () { R.openedMaker2 = clickText(".more-item", "Submit software") || clickText(".more-item", "提交软件"); }, 1800);
  sweepPage("MAKER_EN");
  push(function () {
    var fails = R.checks.filter(function (c) { return !c.pass; });
    R.verdict = {
      samples: R.steps.length, checks: R.checks.length, fails: fails.length,
      groupsSwept: Object.keys(R.census).filter(function (k) { return !/_queued$/.test(k); }).length,
      failNames: fails.map(function (c) { return c.name; })
    };
    R.done = true; post();
  }, 200);

  (function waitApp(n) {
    if (window.__TOOLSGCP_APP__) { R.ready = true; run(); return; }
    if (n > 250) { R.errors.push("app 未挂载"); post(); return; }
    setTimeout(function () { waitApp((n || 0) + 1); }, 100);
  })(0);
})();