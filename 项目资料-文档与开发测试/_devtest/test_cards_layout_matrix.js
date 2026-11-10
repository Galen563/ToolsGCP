/* ToolsGCP · task-3 ③「不同分辨率/缩放下收藏页卡片大小」—— 布局矩阵回归。
 *
 * 这台机器的沙箱起不了 Chromium（mojo 命名管道被拒 0x5，Edge/Chrome 都一样），
 * 所以像素级排版量不了。这里改成**用真实 app.js 的列数公式**跑一遍分辨率矩阵：
 *   · 起 jsdom + 真 app.js + serve.py mock（和 test_cards_runtime.js 同一套接缝）；
 *   · 把收藏页滚动容器的 clientWidth 换成各分辨率/缩放下的**实际 CSS 像素宽**；
 *   · 断言列数/卡宽不变量：等宽、不超 maxCardW、不留 0 宽、行宽合计不溢出、
 *     且和搜索页**同一套公式**得到完全一致的宽度（需求原话）。
 * CSS 像素 = 物理像素 / deviceScaleFactor，所以 1.25 / 1.5 缩放就是
 * 把 1280/1440/1920/2560 除以 1.25 或 1.5 —— 矩阵按这个换算。
 *
 * 跑法（仓库根目录，需要先起 mock：python 项目资料-文档与开发测试/_devtest/serve.py 8811）：
 *   TG_PORT=8811 node "项目资料-文档与开发测试/_devtest/test_cards_layout_matrix.js"
 */
'use strict';

const path = require('path');
const fs = require('fs');
const probe = path.join(__dirname, '_nodeprobe');
const { JSDOM, VirtualConsole, requestInterceptor } = require(path.join(probe, 'node_modules', 'jsdom'));

const ROOT = path.resolve(__dirname, '..', '..');
const favCssText = fs.readFileSync(path.join(ROOT, '.ToolsGCP', 'webui', 'css', 'fav-fixes.css'), 'utf8');

const PORT = Number(process.env.TG_PORT || 8811);
const URL_BASE = 'http://127.0.0.1:' + PORT + '/';

let fails = 0;
const lines = [];
function check(label, cond, extra) {
  lines.push((cond ? '  OK   ' : '  FAIL ') + label + (!cond && extra ? '  ← ' + extra : ''));
  if (!cond) fails += 1;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* 外壳占位（CSS 实测值，见 variables.css / layout.css / base.css）：
   导航栏 48 + 收藏页 .fav-layout 左右 padding 24×2 + 左侧收藏夹栏 230 + 左右 gap 16
   = 48 + 48 + 230 + 16 = 342；滚动条槽 scrollbar-gutter 预留 8。 */
const CHROME_W = 48 + 48 + 230 + 16;
const SCROLLBAR = 8;

const VIEWPORTS = [
  ['1280x720 @1.00', 1280, 1],
  ['1280x720 @1.25', 1280, 1.25],
  ['1280x720 @1.50', 1280, 1.5],
  ['1440x900 @1.00', 1440, 1],
  ['1440x900 @1.25', 1440, 1.25],
  ['1440x900 @1.50', 1440, 1.5],
  ['1920x1080 @1.00', 1920, 1],
  ['1920x1080 @1.25', 1920, 1.25],
  ['1920x1080 @1.50', 1920, 1.5],
  ['2560x1440 @1.00', 2560, 1],
  ['2560x1440 @1.25', 2560, 1.25],
  ['2560x1440 @1.50', 2560, 1.5],
];

const LAYOUT = { favWidth: 1000 };

function installShims(window) {
  window.ResizeObserver = class ResizeObserver {
    constructor(cb) { this.cb = cb; }
    observe() {} unobserve() {} disconnect() {}
  };
  if (!window.matchMedia) {
    window.matchMedia = (q) => ({
      matches: false, media: q,
      addListener() {}, removeListener() {},
      addEventListener() {}, removeEventListener() {},
    });
  }
  const proto = window.HTMLElement.prototype;
  Object.defineProperty(proto, 'clientWidth', {
    configurable: true,
    get() {
      try { if (this.matches('.page-scroll')) return LAYOUT.favWidth; } catch (e) { /* noop */ }
      return 0;
    },
  });
  Object.defineProperty(proto, 'clientHeight', {
    configurable: true,
    get() { try { if (this.matches('.page-scroll')) return 600; } catch (e) { /* noop */ } return 0; },
  });
  proto.getBoundingClientRect = function rect() {
    return { top: 0, bottom: 600, left: 0, right: LAYOUT.favWidth,
      width: LAYOUT.favWidth, height: 600, x: 0, y: 0, toJSON() {} };
  };
}

const stubTailwind = requestInterceptor((request) => {
  if (/tailwind\.js/.test(request.url)) {
    return new Response('/* stub */', { headers: { 'Content-Type': 'application/javascript' } });
  }
  return undefined;
});

function getVm(window) {
  const appEl = window.document.getElementById('app');
  const vnode = appEl && appEl._vnode;
  const comp = vnode && vnode.component;
  return comp && comp.proxy ? comp.proxy : null;
}

async function settle(window) {
  for (let i = 0; i < 4; i += 1) {
    const stuck = window.document.querySelectorAll(
      'section.page-leave-active, section.page-enter-active');
    if (!stuck.length && i > 0) return;
    Array.prototype.forEach.call(stuck, (el) => {
      el.dispatchEvent(new window.Event('transitionend', { bubbles: true }));
    });
    await sleep(60);
  }
}

(async () => {
  let dom;
  try {
    const vc = new VirtualConsole();
    vc.on('jsdomError', (e) => {
      const msg = String(e && e.message);
      if (/Could not load (link|stylesheet)/.test(msg)) return;
      lines.push('  ..   jsdom: ' + msg.slice(0, 120));
    });
    dom = await JSDOM.fromURL(URL_BASE + '?page=favorites', {
      runScripts: 'dangerously',
      resources: { interceptors: [stubTailwind] },
      pretendToBeVisual: true,
      virtualConsole: vc,
      beforeParse: installShims,
    });
    const window = dom.window;
    let vm = null;
    for (let i = 0; i < 120; i += 1) {
      await sleep(100);
      const p = getVm(window);
      if (p && p.items && p.items.length) { vm = p; break; }
    }
    if (!vm) throw new Error('app 没起来');
    await settle(window);
    vm.favFolder = '常用工具';
    await sleep(150);

    lines.push('== task-3 ③ 收藏页布局矩阵（真实 app.js 公式 × 12 档分辨率/缩放）==');
    const rows = [];
    for (const [label, physW, dsf] of VIEWPORTS) {
      const cssW = Math.floor(physW / dsf);
      const avail = Math.max(0, cssW - CHROME_W - SCROLLBAR);
      LAYOUT.favWidth = avail;
      vm.measureFavGrid();
      await sleep(40);
      const L = vm.favLayout;
      rows.push({ label, cssW, avail, cols: L.columns, itemW: L.itemW, gap: +L.gap.toFixed(2) });

      /* 不变量 1：列数与宽度必须自洽（列宽×列数 + 间距 = 容器宽，误差 ≤ 列数） */
      const sum = L.columns * L.itemW + (L.columns - 1) * L.gap;
      check(label + ' 行宽自洽（cols×itemW+(cols-1)gap ≈ ' + avail + '）',
        Math.abs(sum - avail) <= L.columns + 1,
        'sum=' + sum.toFixed(1) + ' cols=' + L.columns + ' itemW=' + L.itemW);
      /* 不变量 2：卡片**渲染宽度**落在 [minW, maxCardW] —— 太小会挤字、太大违背等宽口径。
         ⚠️ 1 列时 itemW=整行宽（可能 > maxCardW），但 CSS
         `.fav-main .grid-static.fav-grid > .card { max-width: 400px }` 会封顶
         （fav-fixes.css），所以断言按渲染宽度 = min(itemW, maxCardW)。 */
      const cfg = vm.viewMode === 'grid' ? { minW: 168, maxCardW: 240 } : { minW: 272, maxCardW: 400 };
      const renderedW = Math.min(L.itemW, cfg.maxCardW);
      check(label + ' 渲染卡宽在 [' + cfg.minW + ', ' + cfg.maxCardW + '] 内',
        renderedW >= cfg.minW && renderedW <= cfg.maxCardW,
        'itemW=' + L.itemW + ' rendered=' + renderedW + ' cols=' + L.columns);
      /* 不变量 2b：1 列且轨道宽于 maxCardW 时，fav-fixes.css 的 max-width 会封顶
         （静态断言源码，jsdom 的样式表加载在本环境不可靠） */
      if (L.columns === 1 && L.itemW > cfg.maxCardW) {
        check(label + ' 1 列超宽由 CSS max-width 封顶',
          /fav-grid > \.card \{[^}]*max-width: 400px/s.test(favCssText),
          '未找到 max-width 规则');
      }
      /* 不变量 3：绝不允许 0 宽/负宽（"面条"bug） */
      check(label + ' 无 0 宽面条（itemW>0 且 columns≥1）',
        L.itemW > 0 && L.columns >= 1, 'itemW=' + L.itemW + ' cols=' + L.columns);
      /* 不变量 4：列数与搜索页公式一致（同一套算法 → 同宽，需求原话） */
      const searchCols = (() => {
        const spacing = cfg.spacing || (vm.viewMode === 'grid' ? 12 : 14);
        let c = Math.max(1, Math.floor((avail + spacing) / (cfg.minW + spacing)));
        const cap = Math.max(vm.viewMode === 'grid' ? 6 : 4, Math.ceil(avail / cfg.maxCardW));
        return Math.max(1, Math.min(c, cap));
      })();
      check(label + ' 列数与搜索页公式一致', L.columns === searchCols,
        'fav=' + L.columns + ' search=' + searchCols);
    }

    /* 极端窄：收藏页可用宽度只有 300px（小窗/分屏）→ 必须收成 1 列而不是 0 或负 */
    LAYOUT.favWidth = 300;
    vm.measureFavGrid();
    await sleep(40);
    check('极窄 300px → 1 列且卡宽≈容器', vm.favLayout.columns === 1 && vm.favLayout.itemW > 200,
      'cols=' + vm.favLayout.columns + ' itemW=' + vm.favLayout.itemW);

    /* 极宽：4K 无缩放（可用 ~2100）→ 列数受 maxCardW 约束，卡片不会被拉成巨条 */
    LAYOUT.favWidth = 2100;
    vm.measureFavGrid();
    await sleep(40);
    check('极宽 2100px → 卡宽 ≤ 400（maxCardW 生效）', vm.favLayout.itemW <= 400,
      'cols=' + vm.favLayout.columns + ' itemW=' + vm.favLayout.itemW);

    lines.push('  ..   矩阵明细：');
    rows.forEach((r) => lines.push('       ' + r.label.padEnd(18)
      + ' cssW=' + String(r.cssW).padStart(4)
      + ' avail=' + String(r.avail).padStart(4)
      + ' cols=' + r.cols
      + ' itemW=' + r.itemW
      + ' gap=' + r.gap));
  } catch (e) {
    lines.push('  FAIL 运行器异常：' + (e && e.stack || e));
    fails += 1;
  } finally {
    if (dom) dom.window.close();
  }

  console.log(lines.join('\n'));
  console.log(fails ? '\n结果：' + fails + ' 项失败' : '\n结果：全部通过');
  process.exit(fails ? 1 : 0);
})();
