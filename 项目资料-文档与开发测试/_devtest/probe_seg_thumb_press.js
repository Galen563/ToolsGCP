/* task-23 复现/验收探针（Edge 侧，由 probe_seg_thumb_live.py --js 注入）
 *
 * 根因（已取证）：components.css:294 给 .seg-item:active 写了 transform: scale(.96)。
 *   真人点击 = 按下(缩放) → 松手(回弹过渡) → click → nextTick(syncSegThumbs)。
 *   旧代码用 getBoundingClientRect() 量选中项，rect 把 transform 折算进去，
 *   于是写进 .seg-thumb 的宽度只有真实宽度的 96%（实测 312 → 298.98，差 13.02px，
 *   left 也偏 6.5px）；而 transform 不改变边框盒 ⇒ ResizeObserver 永不回调补刀
 *   ⇒ 滑块永久偏短 = 用户说的「滑动到其他地方再滑回来，选中的那个明显短了」。
 *   修复 = 改用 offsetLeft/offsetTop/offsetWidth/offsetHeight + seg.clientWidth/clientHeight。
 *
 * 本探针同时留对照证据：按住不放时记录同一项的 rect.width 与 offsetWidth
 *   （rect 应当明显小于 offset，证明污染真实存在），再证明写进 thumb 的是 offset 口径。
 *
 * 命名规则：驱动把以 A_/D_/E_/G_/H_/I_ 开头的采样当终态，用 TOL=1.5 判 dx/dw/dh；
 *   过渡中的采样用 X_ 前缀、按住中段用 P_ 前缀（都不参与判定）。
 * 只在时间线末尾 POST 一次：驱动看到报告文件后等 0.4s 就 taskkill Edge。
 */
(function () {
  var R = { steps: [], checks: [], errors: [], note: "task-23 按压态验收", ready: false };
  function p(v) { return Math.round(v * 100) / 100; }
  function ok(cond, name, detail) { R.checks.push({ name: name, pass: !!cond, detail: detail }); }
  function seg() { return document.querySelector(".i18n-seg"); }
  function items() { var s = seg(); return s ? [].slice.call(s.querySelectorAll(".seg-item")) : []; }
  function thumb() { var s = seg(); return s ? s.querySelector(".seg-thumb") : null; }

  function snap(tag, ctx) {
    try {
      var s = seg(), th = thumb();
      /* elFor：按住中段那一次，被按的那项还不是 .is-on（click 尚未发生），
         不指定它就会量到旧选中项，看不出缩放污染。 */
      var on = (ctx && ctx.el) || (s ? s.querySelector(".seg-item.is-on") : null);
      if (!s || !th || !on) {
        R.steps.push({ tag: tag, segFound: !!s, thumbFound: !!th, onFound: !!on });
        return null;
      }
      var tr = th.getBoundingClientRect(), or = on.getBoundingClientRect();
      var d = {
        tag: tag, ctx: (ctx && typeof ctx === "object") ? { away: ctx.away, pressing: ctx.pressing, el: (ctx.el ? "指定项" : null) } : (ctx || null),
        segFound: true, thumbFound: true, onFound: true,
        onText: (on.textContent || "").trim(),
        thumb: [p(tr.left), p(tr.top), p(tr.width), p(tr.height)],
        on: [p(or.left), p(or.top), p(or.width), p(or.height)],
        dx: p(Math.abs(tr.left - or.left)), dw: p(Math.abs(tr.width - or.width)),
        dh: p(Math.abs(tr.height - or.height)),
        onRectW: p(or.width), onOffsetW: p(on.offsetWidth),
        onRectL: p(or.left), onOffsetL: p(on.offsetLeft),
        thumbInline: { left: th.style.left, width: th.style.width },
        onTransform: getComputedStyle(on).transform,
        offsetParentIsSeg: on.offsetParent === s,
        segClientW: s.clientWidth,
        docW: window.innerWidth
      };
      R.steps.push(d);
      return d;
    } catch (e) { R.errors.push("snap " + tag + ": " + e); return null; }
  }

  function after(ms, fn) {
    setTimeout(function () { try { fn(); } catch (e) { R.errors.push("step: " + e); } }, ms);
  }
  function post() {
    try {
      fetch("/audit?page=seg_live", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(R)
      });
    } catch (e) { R.errors.push("post: " + e); }
  }
  function when(cond, cb, tag, tries) {
    if (cond()) { R[tag] = true; return cb(); }
    if ((tries || 0) > 300) { R[tag + "_timeout"] = true; R.errors.push("等不到 " + tag); post(); return; }
    setTimeout(function () { when(cond, cb, tag, (tries || 0) + 1); }, 100);
  }

  /* 真人时序：按下并保持 hold 毫秒 → 松手（回弹开始）+ 立刻 click。 */
  function pressClick(i, hold, tag) {
    var it = items()[i];
    if (!it) { R.errors.push("no item " + i + " @" + tag); return; }
    it.style.transform = "scale(.96)";
    try { it.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true })); }
    catch (e) { R.errors.push("mousedown: " + e); }
    after(hold, function () {
      it.style.transform = "";
      try { it.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true })); }
      catch (e) { R.errors.push("mouseup: " + e); }
      it.click();
      R[tag] = "clicked";
    });
  }

  /* 一轮：点住某项 → 中途采样（证明污染存在）→ 终态两次采样（交驱动判 TOL） */
  function pressCycle(t0, away, hold, name) {
    after(t0, function () { pressClick(away, hold, name + "_press"); });
    after(t0 + hold - 10, function () {
      var d = snap("P_" + name + "_held", { el: items()[away], pressing: away });
      if (d) {
        /* 快点击（hold<100）时 CSS 过渡还没走完，缩放幅度可能只有一两个百分点，
           所以只要求「按压声明确实生效 + rect 不放大」；长按压要求真的缩到肉眼级。 */
        if (hold >= 100) {
          ok(d.onTransform !== "none" && d.onRectW < d.onOffsetW - 5,
            name + " 按住时 rect 被 transform 缩短（污染确实存在）",
            "rect=" + d.onRectW + " offset=" + d.onOffsetW + " transform=" + d.onTransform);
        } else {
          ok(d.onTransform !== "none" && d.onRectW <= d.onOffsetW + 0.5,
            name + " 按压态生效（短按压，缩放幅度按过渡进度算）",
            "rect=" + d.onRectW + " offset=" + d.onOffsetW + " transform=" + d.onTransform);
        }
      }
    });
    after(t0 + hold + 25, function () { snap("X_" + name + "_click+25ms"); });
    after(t0 + hold + 90, function () { snap("X_" + name + "_click+90ms"); });
    after(t0 + hold + 520, function () {
      var d = snap("D_" + name + "_settled_500ms", { away: away });
      if (d) {
        var iw = parseFloat(d.thumbInline.width);
        ok(Math.abs(d.dw) <= 1.5 && Math.abs(iw - d.onOffsetW) <= 1.5,
          name + " 终态 thumb 宽度 = 真实项宽（offset 口径）",
          "inline=" + d.thumbInline.width + " offset=" + d.onOffsetW + " rect=" + d.onRectW);
      }
    });
    var s2 = t0 + hold + 1300;
    after(s2, function () { snap("E_" + name + "_settled_1300ms", { away: away }); });
    return s2 + 100;
  }

  function clickItem(i, tag) {
    var it = items()[i];
    if (!it) { R.errors.push("no item " + i + " @" + tag); return; }
    it.click();
    R[tag] = "clicked";
  }

  when(function () { return !!window.__TOOLSGCP_APP__; }, function () {
    after(300, function () {
      var b = [].slice.call(document.querySelectorAll(".nav-item"))
        .find(function (x) { return (x.textContent || "").trim() === "更多"; });
      if (b) b.click(); R.navMore = !!b;
    });
    after(800, function () {
      var b = [].slice.call(document.querySelectorAll(".more-item"))
        .find(function (x) { return (x.textContent || "").trim() === "提交软件"; });
      if (b) b.click(); R.openedMaker = !!b;
    });
    when(function () { return items().length >= 3 && !!thumb(); }, function () {
      R.ready = true;
      var base = items()[0].offsetWidth;
      ok(base > 0, "基线 offsetWidth 可用", "base=" + base);
      var t = 700;
      after(t, function () { snap("A_baseline"); });
      t = pressCycle(t + 200, 2, 40, "Q1");          /* ① 快点击：最日常的手感 */
      t = pressCycle(t + 200, 2, 250, "Q2");        /* ② 按住 250ms：旧代码必现 13px 偏短 */
      t = pressCycle(t, 0, 250, "Q3_back");         /* ③ away → back：用户原话的路径 */
      after(t, function () { clickItem(2, "R_away"); });
      after(t + 600, function () { snap("G_pureclick_settled_600ms"); });
      after(t + 700, function () { clickItem(0, "R_back"); });
      after(t + 1400, function () { snap("H_pureclick_back_settled"); });
      var t5 = t + 1600;                            /* ④ 纯 click 对照组 */
      after(t5, function () { pressClick(1, 40, "S_a"); });
      after(t5 + 260, function () { pressClick(2, 40, "S_b"); });
      after(t5 + 520, function () { pressClick(0, 40, "S_c"); });
      after(t5 + 1400, function () {
        var d = snap("I_rapid_final", { rapid: true });
        if (d) ok(Math.abs(d.dw) <= 1.5 && d.thumbInline.width === items()[0].offsetWidth + "px",
          "连点三次后终态仍与真实项同宽", "inline=" + d.thumbInline.width + " offset=" + items()[0].offsetWidth);
      });
      after(t5 + 1500, function () {
        var fails = R.checks.filter(function (c) { return !c.pass; });
        R.verdict = fails.length ? "FAIL" : "PASS";
        R.counts = { total: R.checks.length, fails: fails.length };
        post();
      });
    }, "segReady");
  }, "appReady");
})();