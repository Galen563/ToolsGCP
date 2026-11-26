/* task-23 取证（Edge 侧，由 probe_seg_thumb_live.py --js 注入）：
 *   用户报「滑动到其他地方再滑动回来，选中的那个长度明显短了」⇒ 专测 **away → back 的终态**，
 *   并覆盖四种前置状态：① 干净默认；② 先切页面/分区再回来；③ 容器被挤窄；④ 先切界面语言再点分段。
 *   每个 snap 记 inline 宽度、选中项真实宽度、各项宽度，用来区分「量到旧尺寸」还是「夹紧了」。
 */
(function () {
  var R = { steps: [], errors: [], note: "task-23 away->back thumb settle", ready: false };
  function p(v) { return Math.round(v * 100) / 100; }
  function rect(el) { if (!el) return null; var b = el.getBoundingClientRect();
    return { x: p(b.left), y: p(b.top), w: p(b.width), h: p(b.height) }; }
  function seg() { return document.querySelector(".i18n-seg"); }
  function items() { var s = seg(); return s ? [].slice.call(s.querySelectorAll(".seg-item")) : []; }
  function thumb() { var s = seg(); return s ? s.querySelector(".seg-thumb") : null; }
  function cs(el, props) { if (!el) return null; var c = getComputedStyle(el), o = {};
    props.forEach(function (k) { o[k] = c[k]; }); return o; }
  function snap(tag, ctx) {
    try {
      var s = seg(), on = s ? s.querySelector(".seg-item.is-on") : null, th = thumb();
      var t = rect(th), o = rect(on);
      R.steps.push({ tag: tag, ctx: ctx || null, onText: on ? (on.textContent || "").trim() : null,
        segRect: rect(s), thumb: t, on: o, dx: (t && o) ? p(Math.abs(t.x - o.x)) : null,
        dw: (t && o) ? p(t.w - o.w) : null,
        inline: th ? { left: th.style.left, width: th.style.width } : null,
        itemWidths: items().map(function (i) { return p(i.getBoundingClientRect().width); }),
        itemFlex: items().length ? cs(items()[0], ["flexGrow", "flexBasis", "minWidth", "paddingLeft", "paddingRight"]) : null,
        onStyle: on ? cs(on, ["fontWeight", "paddingLeft", "transitionProperty", "transitionDuration"]) : null,
        thumbDecl: th ? cs(th, ["transitionProperty", "transitionDuration", "boxSizing"]) : null,
        fonts: document.fonts ? document.fonts.status : "n/a",
        appLang: (window.__TOOLSGCP_APP__ && window.__TOOLSGCP_APP__.lang) || null,
        docW: window.innerWidth });
    } catch (e) { R.errors.push("snap " + tag + ": " + e); }
  }
  function after(ms, fn) { setTimeout(function () { try { fn(); } catch (e) { R.errors.push("step: " + e); } }, ms); }
  function post() { try { fetch("/audit?page=seg_live", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(R) }); }
    catch (e) { R.errors.push("post: " + e); } }
  function when(cond, cb, tag, tries) {
    if (cond()) { R[tag] = true; return cb(); }
    if ((tries || 0) > 300) { R[tag + "_timeout"] = true; R.errors.push("等不到 " + tag); post(); return; }
    setTimeout(function () { when(cond, cb, tag, (tries || 0) + 1); }, 100);
  }
  function clickItem(i, tag, cb) {
    var it = items();
    if (!it[i]) { R.errors.push("no item " + i + " @" + tag); return cb && cb(); }
    it[i].click(); cb && cb();
  }
  /* 一次 away->back 周期：起点 0 → 目标 k → 回 0，回来之后 400/1200ms 各量一次 */
  function cycle(name, k, t0, gap) {
    after(t0, function () { clickItem(k, name + "/away"); });
    after(t0 + (gap || 900), function () { snap(name + "_away_settled", { away: k }); });
    after(t0 + (gap || 900) + 60, function () { clickItem(0, name + "/back"); });
    after(t0 + (gap || 900) + 460, function () { snap(name + "_back_400ms", { away: k }); });
    after(t0 + (gap || 900) + 1260, function () { snap(name + "_back_1200ms", { away: k }); });
  }
  when(function () { return !!window.__TOOLSGCP_APP__; }, function () {
    var vm = window.__TOOLSGCP_APP__;
    after(300, function () { R.navMore = (function () { var b = [].slice.call(document.querySelectorAll(".nav-item"))
      .find(function (x) { return (x.textContent || "").trim() === "更多"; }); if (b) b.click(); return !!b; })(); });
    after(800, function () { R.openedMaker = (function () { var b = [].slice.call(document.querySelectorAll(".more-item"))
      .find(function (x) { return (x.textContent || "").trim() === "提交软件"; }); if (b) b.click(); return !!b; })(); });
    when(function () { return items().length >= 3 && !!thumb(); }, function () {
      R.ready = true;
      after(600, function () { snap("P0_baseline"); });
      /* ① 干净默认：away→back 两轮，目标分别是最右项和中间项 */
      cycle("Q1_to2", 2, 900, 1100);
      /* ② 切到别的分区（资源浏览）再切回来 —— 分段被 v-if 拆掉重挂的情况 */
      after(4400, function () { R.secBrowser = (function () { var b = [].slice.call(document.querySelectorAll(".maker-section .seg-item, .seg-item"))
        .find(function (x) { return (x.textContent || "").trim() === "资源浏览"; }); if (b) b.click(); return !!b; })(); });
      after(5200, function () { R.secForm = (function () { var b = [].slice.call(document.querySelectorAll(".seg-item"))
        .find(function (x) { return (x.textContent || "").trim() === "投稿表单"; }); if (b) b.click(); return !!b; })(); });
      after(5600, function () { snap("Q2_remounted"); });
      cycle("Q2_to1", 1, 5900, 1100);
      /* ③ 容器被挤窄 200px（等价于滚动条/侧栏挤一下）后再 away→back */
      after(9600, function () {
        var s = seg(); if (!s) return;
        var host = s.parentElement || s;
        host.style.maxWidth = Math.max(240, host.getBoundingClientRect().width - 200) + "px";
        R.narrowed = host.style.maxWidth;
      });
      after(10100, function () { snap("Q3_narrow_baseline"); });
      cycle("Q3_to2", 2, 10300, 1100);
      after(14100, function () { var s = seg(); var host = s && (s.parentElement || s); if (host) host.style.maxWidth = ""; R.unarrowed = true; });
      after(14600, function () { snap("Q3_unnarrow_baseline"); });
      cycle("Q3b_to2", 2, 14800, 1100);
      /* ④ 先在设置里切界面语言（app.js 全局 lang），再回 maker 点分段 away→back */
      after(18400, function () { if (vm && vm.setLang) { vm.setLang("en"); R.langSet = "en"; } else if (vm) { vm.lang = "en"; R.langSet = "direct"; } });
      after(19200, function () { snap("Q4_after_lang_switch"); });
      cycle("Q4_to1", 1, 19500, 1100);
      after(23000, function () { snap("Z_final"); post(); });
    }, "segReady");
  }, "appReady");
})();