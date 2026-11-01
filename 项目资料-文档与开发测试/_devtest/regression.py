"""独立回归验证驱动（，仅 _devtest 用，不属于产品代码）。
做什么：
  1. 自己起一个静态服务（默认 8795，先查端口占用，跑完 kill 自己的进程，绝不碰别人的 8791）；
  2. 用无头 Edge 逐页 / 逐交互跑探针，探针把**实测数字** POST 回 /audit?page=reg_<case>
     （用 serve.py 新增的 ?auditfile= 命名，绝不覆盖 audit_home/search/settings.json）；
  3. JS 报错由 serve.py 自带的 onerror/unhandledrejection 上报到 reg_<case>_err.json；
  4. 结果写 _devtest/reg_<case>.json，控制台打印摘要。
每个数字都标注冻结模式：fx=off（硬冻结，量终态） / fx=keep（不冻结，读过渡声明）。
用法：
    python _devtest/regression.py                 # 全量
    python _devtest/regression.py combo seg_frozen  # 只跑指定 case
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))   # 已下沉到 项目资料-文档与开发测试/_devtest/
PORT = 8795
PROFILE = os.path.join(os.environ.get("TEMP", "."), "gcp_reg_%d" % PORT)

# 探针前置：所有 case 共用的量测工具
PRELUDE = r"""
var REG = (function () {
  var R = { name: '__NAME__', pageSel: '__PAGE__', fx: '__FX__', steps: [], errors: [] };
  function px(v) { return Math.round(v * 100) / 100; }
  function q(sel) { return document.querySelector(sel); }
  function qa(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }
  function txt(el) { return el ? (el.textContent || '').trim() : null; }
  function r(el) {
    if (!el) return null;
    var b = el.getBoundingClientRect();
    return { x: px(b.left), y: px(b.top), w: px(b.width), h: px(b.height),
             right: px(b.right), bottom: px(b.bottom) };
  }
  function cs(el, props) {
    if (!el) return null;
    var c = getComputedStyle(el), o = {};
    props.forEach(function (k) { o[k] = c[k]; });
    return o;
  }
  /* 兄弟元素重叠检测：与 serve.py 的 AUDIT_JS 同一套选择器与阈值（ox>2 && oy>2），
     这样"每页 overlaps==0"这条要求由我自己的探针给出，不依赖别人的 audit_*.json。 */
  function overlaps() {
    var hits = [];
    var sel = '.toolbar-row, .plugin-head-text, .ai-head, .ai-input-row, .row, .filter-row, .card-head, .setting-row';
    qa(sel).forEach(function (host) {
      var kids = Array.prototype.filter.call(host.children, function (k) {
        return getComputedStyle(k).display !== 'none'; });
      for (var i = 0; i < kids.length; i++) {
        for (var j = i + 1; j < kids.length; j++) {
          var a = kids[i].getBoundingClientRect(), b = kids[j].getBoundingClientRect();
          if (a.width === 0 || b.width === 0) continue;
          var ox = Math.min(a.right, b.right) - Math.max(a.left, b.left);
          var oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
          if (ox > 2 && oy > 2) {
            var s = getComputedStyle(host);
            if (s.position === 'relative' || s.position === 'absolute') continue;
            hits.push({ host: String(host.className).slice(0, 50),
              a: String(kids[i].className).slice(0, 40), b: String(kids[j].className).slice(0, 40),
              ox: Math.round(ox), oy: Math.round(oy) });
          }
        }
      }
    });
    return hits.slice(0, 30);
  }
  /* 渲染健康度：冻结最容易被怀疑的副作用就是"元素卡在 enter-from / opacity:0"，
     所以每页都量一遍，并用 fx=keep 的同页数据做对照。 */
  function sanity() {
    var pg = q('.page');
    var all = pg ? Array.prototype.slice.call(pg.querySelectorAll('*')) : [];
    var zero = 0, hidden = 0, firstChild = null;
    all.forEach(function (el) {
      var c = getComputedStyle(el);
      if (c.display === 'none' || c.visibility === 'hidden') { hidden += 1; return; }
      if (parseFloat(c.opacity) === 0 && el.getBoundingClientRect().width > 0) zero += 1;
    });
    if (pg && pg.firstElementChild) firstChild = String(pg.firstElementChild.className).slice(0, 60);
    var stuck = qa('[class*="enter-"],[class*="leave-"]').map(function (e) {
      return String(e.className).slice(0, 50); });
    var tb = qa('.tb-btn').map(function (b) { return r(b); });
    return {
      vueLoaded: typeof Vue !== 'undefined',
      pageCount: qa('.page').length,
      appRoot: !!q('.app-root'),
      mustaches: (document.body.innerHTML.match(/\{\{/g) || []).length,
      titlebarButtons: tb.length,
      titlebarSizes: tb.map(function (x) { return x.w + 'x' + x.h; }),
      pageRoot: pg ? String(pg.className) : null,
      pageFirstChild: firstChild,
      pageTextLen: pg ? (pg.innerText || '').length : 0,
      pageElements: all.length,
      hiddenElements: hidden,
      zeroOpacityVisible: zero,
      stuckEnterCount: stuck.length,
      stuckEnterClasses: stuck.slice(0, 6),
      overlaps: overlaps().length,
      overlapSamples: overlaps().slice(0, 5),
      navWidth: q('.nav') ? r(q('.nav')).w : null,
      navExpanded: q('.nav') ? q('.nav').classList.contains('is-expanded') : null
    };
  }
  function navItem(label) {
    var hit = null;
    qa('.nav-item').forEach(function (b) { if ((b.getAttribute('title') || '') === label) hit = b; });
    return hit;
  }
  function moreItem(label) {
    var hit = null;
    qa('.more-item').forEach(function (b) { if ((b.textContent || '').trim() === label) hit = b; });
    return hit;
  }
  R.px = px; R.q = q; R.qa = qa; R.txt = txt; R.r = r; R.cs = cs;
  R.sanity = sanity; R.navItem = navItem; R.moreItem = moreItem;
  /* ⚠️ 虚拟时钟的坑（实测）：--virtual-time-budget 会让虚拟时间跑在**真实加载前面**，
     于是探针定时器触发时 app 还停在启动画面（.boot-screen），量到 appRoot=false /
     pageCount=0 这种"假失败"，或者 vendor 脚本还没执行完就报 "Vue is not defined"。
     解决办法：本驱动改用**真实时间**跑（不起虚拟时钟、由驱动轮询报告文件后 kill），
     并且统一先等启动画面消失再执行步骤。 */
  R.bootWait = function (cb) {
    var t0 = Date.now();
    (function loop() {
      if (!q('.boot-screen') || Date.now() - t0 > 8000) { R.bootMs = Date.now() - t0; return cb(); }
      setTimeout(loop, 100);
    })();
  };
  R.openMore = function () { var b = navItem('更多'); if (b) b.click(); return !!b; };
  R.mouse = function (el, type) {
    if (!el) return false;
    el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, clientX: 400, clientY: 300 }));
    return true;
  };
  R.post = function () {
    R.steps.push('post');
    R.sanityData = sanity();
    try {
      fetch('/audit?page=' + encodeURIComponent('__AUDITFILE__'), { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(R) });
    } catch (e) { R.errors.push('post: ' + e); }
  };
  R.step = function (tag, fn) {
    try { R.steps.push(tag); var v = fn(); if (v !== undefined) R[tag] = v; }
    catch (e) { R.errors.push(tag + ': ' + String(e)); }
  };
  return R;
})();
"""


def seq(steps):
    """把 [(delay_ms, js), ...] 串成顺序定时器链（第一段延迟从注入时刻算起）。"""
    out = ""
    for delay, js in reversed(steps):
        body = "try{\n%s\n}catch(e){REG.errors.push('step: '+String(e));}" % js
        out = "setTimeout(function(){\n%s\n%s},%d);" % (body, out, delay)
    return out


def case(name, page, steps, fx="off", auditfile=None, js0="", wall=30):
    return {"name": name, "page": page, "fx": fx, "js0": js0,
            "auditfile": auditfile or ("reg_" + name), "steps": steps, "wall": wall}


# 共用页面测量步：只做 sanity + 页面标记
def measure_only(extra=""):
    return "REG.post(); %s" % extra


# case 定义
def build_cases():
    C = []
    # ---- 15 个页面 ----
    C.append(case("page_home", "home", [
        (1900, "REG.post();"),
    ]))
    C.append(case("page_search", "search", [
        (1900, "REG.step('cards', function(){ return REG.qa('.card').length; }); REG.post();"),
    ]))
    C.append(case("page_detail", "search", [
        (1900, "REG.step('clicked', function(){ var c=REG.q('.card'); if(c) c.click(); return !!c; });"),
        (700, "REG.step('detail', function(){ return { detailWrap: !!REG.q('.detail-wrap'), "
              "heroTitle: REG.txt(REG.q('.detail-hero .detail-name')) }; }); REG.post();"),
    ]))
    C.append(case("page_customize", "customize", [(1900, "REG.post();")]))
    C.append(case("page_favorites", "favorites", [(1900, "REG.post();")]))
    C.append(case("page_workshop", "search", [
        (1900, "REG.step('navClick', function(){ var b=REG.navItem('GCP工坊'); if(b) b.click(); return !!b; });"),
        (700, "REG.post();"),
    ]))
    C.append(case("page_notice", "notice", [(1900, "REG.post();")]))
    C.append(case("page_github", "github", [(1900, "REG.post();")]))
    C.append(case("page_feedback", "feedback", [(1900, "REG.post();")]))
    C.append(case("page_log", "log", [(1900, "REG.post();")]))
    C.append(case("page_deploy", "deploy", [(1900, "REG.post();")]))
    C.append(case("page_plugins", "plugins", [(1900, "REG.post();")]))
    C.append(case("page_maker", "search", [
        (1900, "REG.step('openMore', function(){ return REG.openMore(); });"),
        (400, "REG.step('clickMaker', function(){ var b=REG.moreItem('提交软件'); if(b) b.click(); return REG.txt(b); });"),
        (700, "REG.post();"),
    ]))
    C.append(case("page_ai", "search",
                  [(1900, "REG.step('navAI', function(){ var b=REG.navItem('AI'); if(b) b.click(); return !!b; });"),
                   (700, "REG.step('aiRoot', function(){ return { aiPage: !!REG.q('.ai-page'), "
                         "drawer: !!REG.q('.ai-drawer') }; }); REG.post();")],
                  js0="window.__MOCK_SETTINGS__.ai_sidebar_mode = true;"))
    C.append(case("page_settings", "settings", [(1900, "REG.post();")]))
    C.append(case("ai_drawer", "search", [
        (1900, "REG.step('ball', function(){ var b=REG.q('.float-ball'); if(b) b.click(); return !!b; });"),
        (700, "REG.step('drawer', function(){ return { drawer: !!REG.q('.ai-drawer'), "
              "w: REG.r(REG.q('.ai-drawer')) ? REG.r(REG.q('.ai-drawer')).w : null }; }); REG.post();"),
    ]))

    # ---- 交互 ----
    C.append(case("int_combo", "search", [
        (1900, "REG.step('open', function(){ var t=REG.q('.combo-trigger'); if(!t) return false; "
                "REG._trig=t; REG._before=REG.txt(t.querySelector('.combo-label')); t.click(); return true; });"),
        (500, "REG.step('opened', function(){ var t=REG._trig, pop=REG.q('.combo-pop'); "
                "if(!pop) return { pop:false }; var pr=REG.r(pop), tr=REG.r(t); "
                "return { pop:true, popTopGap: REG.px(pr.y - tr.bottom), "
                "flippedUp: pr.bottom < tr.bottom, coversTrigger: pr.y < tr.bottom && pr.bottom > tr.y, "
                "items: REG.qa('.combo-item').length, transform: REG.cs(pop,['transform']).transform, "
                "maxH: REG.cs(pop,['maxHeight']).maxHeight }; });"),
        (300, "REG.step('pick', function(){ var it=REG.qa('.combo-item'); if(it.length<2) return {noItem:true}; "
                "REG._want=REG.txt(it[1]); it[1].click(); return REG._want; });"),
        (500, "REG.step('after', function(){ var t=REG._trig; return { before: REG._before, want: REG._want, "
                "after: REG.txt(t.querySelector('.combo-label')), "
                "labelChanged: REG.txt(t.querySelector('.combo-label')) === REG._want, "
                "popClosed: !REG.q('.combo-pop') }; }); REG.post();"),
    ]))
    C.append(case("int_carousel", "home", [
        (1900, "REG.step('carousel', function(){ var c=REG.q('.carousel'); if(!c) return {carousel:false}; "
                "var imgs=REG.qa('.carousel .slide img').filter(function(i){ return i.complete && i.naturalWidth>0; }); "
                "var aspects=imgs.map(function(i){ return i.naturalHeight/i.naturalWidth; }); "
                "var minA=aspects.length?Math.min.apply(null,aspects):0; "
                "var w=c.clientWidth; var expect=Math.max(200, Math.min(460, Math.round(w*minA))); "
                "var h=c.getBoundingClientRect().height; "
                "return { hostW: w, posterCount: imgs.length, "
                "aspects: aspects.map(function(a){ return Math.round(a*1000)/1000; }), "
                "minAspect: Math.round(minA*10000)/10000, expectH: expect, actualH: Math.round(h), "
                "inlineHeight: c.style.height, hMatches: Math.abs(h-expect)<=1, "
                "clampLow: expect===200, clampHigh: expect===460, "
                "imgOverflow: imgs.map(function(i){ var b=i.getBoundingClientRect(), p=i.parentElement.getBoundingClientRect(); "
                "return { dw: Math.round(b.width-p.width), dh: Math.round(b.height-p.height) }; }), "
                "slideCount: REG.qa('.slide').length, pips: REG.qa('.pip').length }; }); REG.post();"),
    ]))
    C.append(case("diag_seg", "search", [
        (1900, "REG.step('boot', function(){ var segs=REG.qa('.segmented'); "
                "return { segCount: segs.length, "
                "segs: segs.map(function(s){ return { cls: String(s.className), "
                "items: s.querySelectorAll('.seg-item').length, "
                "on: REG.txt(s.querySelector('.seg-item.is-on')), "
                "thumb: !!s.querySelector('.seg-thumb'), "
                "childClasses: Array.prototype.map.call(s.children, function(c){ return String(c.className); }) }; }), "
                "viewSeg: !!REG.q('.view-seg') }; });"),
        (300, "REG.step('resize', function(){ window.dispatchEvent(new Event('resize')); "
                "return true; });"),
        (500, "REG.step('afterResize', function(){ var s=REG.q('.view-seg')||REG.q('.segmented'); "
                "var th=s?s.querySelector('.seg-thumb'):null; var on=s?s.querySelector('.seg-item.is-on'):null; "
                "return { thumb: !!th, thumbRect: REG.r(th), onRect: REG.r(on), "
                "matches: th&&on ? (Math.abs(REG.r(th).x-REG.r(on).x)<1.5 && Math.abs(REG.r(th).w-REG.r(on).w)<1.5) : null, "
                "decl: REG.cs(th, ['transitionProperty','transitionDuration']) }; }); REG.post();"),
    ]))
    C.append(case("int_seg_frozen", "search", [
        # 冷启动时 .seg-thumb 不存在（见 diag_seg / 报告里的 bug#1），先触发一次 resize 得到稳定态，
        # 再验证"切一次后 thumb 是否与新的 .is-on 重合"（终态正确性）。
        (1900, "REG.step('bootThumb', function(){ var s=REG.q('.view-seg'); "
                "return { thumbAtBoot: !!(s&&s.querySelector('.seg-thumb')) }; });"),
        (200, "REG.step('warmup', function(){ window.dispatchEvent(new Event('resize')); return true; });"),
        (400, "REG.step('seg', function(){ var seg=REG.q('.view-seg')||REG.q('.segmented'); "
                "if(!seg) return {seg:false}; "
                "var on=seg.querySelector('.seg-item.is-on'), th=seg.querySelector('.seg-thumb'); "
                "REG._seg=seg; REG._on=on; "
                "return { items: seg.querySelectorAll('.seg-item').length, "
                "thumb: REG.r(th), onRect: REG.r(on), "
                "thumbMatchesOn: th&&on ? (Math.abs(REG.r(th).x-REG.r(on).x)<1.5 && Math.abs(REG.r(th).w-REG.r(on).w)<1.5) : null, "
                "onIsFirst: on === seg.querySelector('.seg-item') }; });"),
        (300, "REG.step('other', function(){ var seg=REG._seg; var other=null; "
                "REG.qa('.view-seg .seg-item, .segmented .seg-item').forEach(function(b){ if(!b.classList.contains('is-on')) other=b; }); "
                "if(other) other.click(); return { clicked: !!other }; });"),
        (600, "REG.step('after', function(){ var seg=REG._seg, on=seg.querySelector('.seg-item.is-on'), "
                "th=seg.querySelector('.seg-thumb'); "
                "return { thumb: REG.r(th), onRect: REG.r(on), "
                "thumbMatchesOn: Math.abs(REG.r(th).x-REG.r(on).x)<1.5 && Math.abs(REG.r(th).w-REG.r(on).w)<1.5, "
                "onChanged: REG._on !== on, onIsSecond: on === seg.querySelectorAll('.seg-item')[1] }; }); REG.post();"),
    ]))
    C.append(case("int_seg_nofx", "search", [
        # fx=keep：不冻结，用来读"过渡声明本身"（滑动 = 有 left/width 的 220ms 过渡 + 点击后有活跃 CSSTransition）
        (1900, "REG.step('warmup', function(){ window.dispatchEvent(new Event('resize')); return true; });"),
        (400, "REG.step('before', function(){ var seg=REG.q('.view-seg')||REG.q('.segmented'); "
                "var th=seg?seg.querySelector('.seg-thumb'):null; REG._seg=seg; REG._th=th; "
                "return { thumbExists: !!th, "
                "thumbDecl: REG.cs(th, ['transitionProperty','transitionDuration','transitionTimingFunction']), "
                "segDecl: REG.cs(REG.q('.seg-item'), ['transitionProperty','transitionDuration']) }; });"),
        (300, "REG.step('click', function(){ var other=null; "
                "REG.qa('.view-seg .seg-item, .segmented .seg-item').forEach(function(b){ if(!b.classList.contains('is-on')) other=b; }); "
                "if(other) other.click(); return !!other; });"),
        (250, "REG.step('anims', function(){ var th=REG._th; if(!th) return null; "
                "var a=th.getAnimations ? th.getAnimations() : []; "
                "return { runningCount: a.length, "
                "list: a.map(function(x){ return { prop: x.transitionProperty || null, "
                "dur: x.effect ? x.effect.getTiming().duration : null, state: x.playState }; }).slice(0,6), "
                "inlineStyle: { left: th.style.left, width: th.style.width, top: th.style.top }, "
                "computedNow: REG.cs(th, ['left','width']) }; }); REG.post();"),
    ], fx="keep"))
    C.append(case("int_cardmenu", "search", [
        (1900, "REG.step('ctx', function(){ var c=REG.q('.card'); if(!c) return false; "
                "c.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:420,clientY:320})); "
                "return true; });"),
        (400, "REG.step('menu', function(){ var m=REG.q('.card-menu'); "
                "return { exists: !!m, items: REG.qa('.card-menu-item').length, "
                "labels: REG.qa('.card-menu-item span').map(function(s){return REG.txt(s);}), "
                "rect: REG.r(m), z: REG.cs(m,['zIndex']).zIndex }; });"),
        (200, "REG.step('outside', function(){ REG.mouse(REG.q('.content'), 'mousedown'); return true; });"),
        (400, "REG.step('after', function(){ return { menuClosed: !REG.q('.card-menu') }; }); REG.post();"),
    ]))
    C.append(case("int_morepop", "search", [
        (1900, "REG.step('open', function(){ return { opened: REG.openMore(), pop: !!REG.q('.more-pop') }; });"),
        (400, "REG.step('clickContent', function(){ REG.mouse(REG.q('.content'), 'mousedown'); "
                "return { closedByContentClick: !REG.q('.more-pop') }; });"),
        (200, "REG.step('reopen', function(){ REG.openMore(); return !!REG.q('.more-pop'); });"),
        (300, "REG.step('pageSwitch', function(){ var b=REG.navItem('首页'); if(b) b.click(); "
                "return { clicked: !!b, closedByPageSwitch: !REG.q('.more-pop'), page: REG.q('.page')?REG.q('.page').className:null }; });"),
        (500, "REG.step('reopen2', function(){ REG.openMore(); return !!REG.q('.more-pop'); });"),
        (300, "REG.step('clickTitlebar', function(){ REG.mouse(REG.q('.titlebar'), 'mousedown'); "
                "return { closedByTitlebarClick: !REG.q('.more-pop') }; }); REG.post();"),
    ]))
    C.append(case("int_navz", "search", [
        (1900, "REG.step('expand', function(){ var b=REG.q('.nav-burger'); if(b) b.click(); return !!b; });"),
        (700, "REG.step('z', function(){ var nav=REG.q('.nav'), cont=REG.q('.content'); var nr=REG.r(nav); "
                "var el=document.elementFromPoint(Math.round(nr.x+nr.w-6), Math.round(nr.y+200)); "
                "return { navZ: REG.cs(nav,['zIndex']).zIndex, contentZ: REG.cs(cont,['zIndex']).zIndex, "
                "navW: nr.w, expanded: nav.classList.contains('is-expanded'), "
                "hitNav: !!(el && el.closest && el.closest('.nav')), hitClass: el?String(el.className).slice(0,40):null }; }); REG.post();"),
    ]))
    C.append(case("int_scrollspy", "settings", [
        (1900, "REG.step('sections', function(){ return REG.qa('.settings-side .list-item.plain').map(function(b){ return REG.txt(b); }); });"),
        (300, "REG.step('clickLast', function(){ var items=REG.qa('.settings-side .list-item.plain'); "
                "var last=items[items.length-1]; if(last) last.click(); return REG.txt(last); });"),
        (900, "REG.step('after', function(){ var on=REG.q('.settings-side .list-item.plain.is-on'); "
                "var host=REG.q('.settings-main'); var sc=REG.q('.settings-scroll')||host; "
                "return { selected: REG.txt(on), onRect: REG.r(on), "
                "mainScrollTop: host?Math.round(host.scrollTop):null, mainScrollH: host?host.scrollHeight:null, "
                "mainClientH: host?host.clientHeight:null }; }); REG.post();"),
    ]))
    C.append(case("int_hotkey", "settings", [
        (1900, "REG.step('findInput', function(){ var i=REG.q('.hotkey-input'); REG._inp=i; "
                "return { exists: !!i, value: i?i.value:null, placeholder: i?i.placeholder:null }; });"),
        (200, "REG.step('focusClick', function(){ if(REG._inp) REG._inp.click(); "
                "return { inputRecordingClass: REG._inp?REG._inp.classList.contains('is-recording'):null, "
                "bar: !!REG.q('.hotkey-recording'), barText: REG.txt(REG.q('.hotkey-recording')) }; });"),
        (300, "REG.step('pressKeys', function(){ var i=REG._inp; if(!i) return false; "
                "i.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,cancelable:true,key:'K',code:'KeyK',ctrlKey:true,altKey:true})); "
                "return true; });"),
        (500, "REG.step('afterBind', function(){ return { bar: !!REG.q('.hotkey-recording'), "
                "inputRecordingClass: REG._inp?REG._inp.classList.contains('is-recording'):null, value: REG._inp?REG._inp.value:null }; }); REG.post();"),
    ]))
    C.append(case("tags_plus", "search", [
        (1900, "REG.step('tagMore', function(){ var out=REG.qa('.card').map(function(c){ "
                "var more=c.querySelector('.tag-more'); if(!more) return null; "
                "var row=more.closest('.row'); var vis=row?row.querySelectorAll('.tag:not(.tag-more)').length:0; "
                "var total=(more.getAttribute('title')||'').split('、').filter(Boolean).length; "
                "return { shown: REG.txt(more), visibleTags: vis, totalTags: total, expect: '+'+Math.max(0,total-vis), "
                "rowClip: row? row.scrollWidth-row.clientWidth : null }; }).filter(Boolean); "
                "return { cards: REG.qa('.card').length, withPlusX: out.length, samples: out.slice(0,5), "
                "allOk: out.every(function(o){ return o.shown===o.expect; }) }; }); REG.post();"),
    ], js0=("(function(){var api=window.pywebview.api; var old=api.resources.all;"
            " api.resources.all=async function(){ var r=await old(); var items=(r.items||[]).slice();"
            " items.push({code:'REG-TAGS',name:'多标签自检样本',description:'验证 +X 隐藏标签数量用的样本',"
            "category:'工具',tags:['标签一二三','标签四五六','标签七八九','标签十一','标签十二','标签十三'],"
            "system:'全平台',arch:'x64',version:'1.0.0',listed_at:'2026-10-01 00:00:00',github:'',url:'',icon:''});"
            " r.items=items; return r; }; })();")))

    # ---- 冻结副作用对照（lead 要求：证明 fx=off 不会把页面搞成半渲染）----
    nav3 = [
        (1900, "REG.step('home', function(){ return REG.sanity(); });"),
        (400, "REG.step('toSearch', function(){ var b=REG.navItem('搜索'); if(b) b.click(); return !!b; });"),
        (700, "REG.step('search', function(){ return REG.sanity(); });"),
        (400, "REG.step('toSettings', function(){ var b=REG.navItem('设置'); if(b) b.click(); return !!b; });"),
        (900, "REG.step('settings', function(){ return REG.sanity(); }); REG.post();"),
    ]
    C.append(case("health_fxoff", "home", nav3, fx="off", wall=40))
    C.append(case("health_fxkeep", "home", nav3, fx="keep", wall=40))
    return C


# 运行
def port_busy(port):
    s = socket.socket()
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def pick_port():
    global PORT, PROFILE
    p = PORT
    while port_busy(p):
        p += 1
    PORT = p
    PROFILE = os.path.join(os.environ.get("TEMP", "."), "gcp_reg_%d" % PORT)
    return p


def start_server():
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, "serve.py"), str(PORT)],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/static/css/base.css" % PORT, timeout=1).read(64)
            return proc
        except Exception:
            time.sleep(0.25)
    proc.kill()
    raise RuntimeError("serve.py 起不来")


def run_case(c):
    if not os.path.isdir(PROFILE):
        os.makedirs(PROFILE, exist_ok=True)
    js = (PRELUDE.replace("__NAME__", c["name"]).replace("__PAGE__", c["page"])
          .replace("__FX__", c["fx"]).replace("__AUDITFILE__", c["auditfile"])
          + "REG.bootWait(function () {\n" + seq(c["steps"]) + "\n});")
    qs = [("page", c["page"]), ("fx", c["fx"]), ("auditfile", c["auditfile"]),
          ("js", js)]
    if c["js0"]:
        qs.append(("js0", c["js0"]))
    url = "http://127.0.0.1:%d/?%s" % (PORT, urllib.parse.urlencode(qs))
    # ⚠️ serve.py 的落盘路径是 audit_<name>.json（不是 <name>.json），auditfile 只替换中间那段
    out = os.path.join(HERE, "audit_%s.json" % c["auditfile"])
    err = os.path.join(HERE, "audit_%s_err.json" % c["auditfile"])
    for p in (out, err):
        if os.path.isfile(p):
            os.remove(p)
    cmd = [EDGE, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
           "--no-default-browser-check", "--user-data-dir=" + PROFILE,
           "--window-size=1440,900", "--hide-scrollbars", url]
    # 真实时间模式：跑到底就 kill（轮询报告文件），不设 --virtual-time-budget
    t0 = time.time()
    devnull = open(os.devnull, "wb")
    proc = subprocess.Popen(cmd, stdout=devnull, stderr=devnull)
    waited = 0.0
    while waited < c["wall"] and not os.path.isfile(out):
        time.sleep(0.1)
        waited += 0.1
    time.sleep(0.35)          # 等文件写完整
    try:
        proc.kill()
    except Exception:
        pass
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       stdout=devnull, stderr=devnull, timeout=15)
    except Exception:
        pass
    devnull.close()
    dt = time.time() - t0
    data = None
    if os.path.isfile(out):
        with open(out, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    errs = None
    if os.path.isfile(err):
        with open(err, "r", encoding="utf-8") as fh:
            errs = json.load(fh)
    return {"case": c["name"], "fx": c["fx"], "page": c["page"], "url": url,
            "secs": round(dt, 1), "report": data, "jsError": errs}


def main():
    only = set(sys.argv[1:])
    pick_port()
    print("port=%d profile=%s" % (PORT, PROFILE))
    proc = start_server()
    print("server up")
    results = []
    try:
        for c in build_cases():
            if only and c["name"] not in only:
                continue
            res = run_case(c)
            results.append(res)
            rep = res["report"] or {}
            s = rep.get("sanityData") or {}
            flag = "OK " if (rep and s.get("mustaches") == 0 and s.get("pageCount") == 1) else "!! "
            print("%s%-18s fx=%-6s %5.1fs  mustaches=%s pageCount=%s err=%s" %
                  (flag, res["case"], res["fx"], res["secs"], s.get("mustaches"),
                   s.get("pageCount"), "YES" if res["jsError"] else "-"))
    finally:
        proc.kill()
        print("server killed")
    with open(os.path.join(HERE, "reg_all.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)
    print("summary -> _devtest/reg_all.json (%d cases)" % len(results))


if __name__ == "__main__":
    main()
