/* ToolsGCP · task-3（卡片/收藏页 5 项）运行时回归 —— jsdom 版。
 *
 * 为什么用 jsdom 而不是无头 Edge：
 *   这台机器的 OS 沙箱**禁止 Chromium 多进程**（mojo 命名管道 CreateFile 被拒 0x5，
 *   Edge 和 Chrome 都起不来，AGENTS.md 第 6 节也写了这条限制）。
 *   jsdom 能跑真实 Vue + 真实 app.js + 真实 serve.py mock 接口，
 *   所以**数据流/时序类**的 bug（收藏状态、先量后渲染、虚拟列表窗口、空字段行）
 *   都能端到端断言；只有**像素级排版**（真实字体高度、DPI）量不到 ——
 *   那部分用 layout_model.js（把 app.js 的列数/宽度公式原样搬进 Node）覆盖，
 *   并另备 edge_matrix.ps1 给能跑浏览器的机器一键出截图矩阵。
 *
 * 跑法（仓库根目录）：
 *   node "项目资料-文档与开发测试/_devtest/test_cards_runtime.js"
 *   端口可用环境变量 TG_PORT 覆盖（默认 8823，自己起 serve.py，跑完自己收）。
 *   依赖：_devtest/_nodeprobe/node_modules/jsdom（npm --prefix 装的，不参与运行）。
 */
'use strict';

const path = require('path');
const { spawn } = require('child_process');

const ROOT = path.resolve(__dirname, '..', '..');
const PORT = Number(process.env.TG_PORT || 8823);
const URL_BASE = 'http://127.0.0.1:' + PORT + '/';

/* jsdom 装在 _devtest/_nodeprobe 下（npm --prefix），从这里显式解析 */
const probe = path.join(__dirname, '_nodeprobe');
function reqLocal(name) {
  return require(path.join(probe, 'node_modules', name));
}
const { JSDOM, VirtualConsole, requestInterceptor } = reqLocal('jsdom');

/* Tailwind 运行时在 jsdom 里既跑不动也没意义（我们不断言样式），
   用请求拦截器把它换成空脚本；其余同源资源走默认加载（本地 mock 服务）。 */
const stubTailwind = requestInterceptor((request) => {
  if (/tailwind\.js/.test(request.url)) {
    return new Response('/* tailwind stubbed in jsdom */', {
      headers: { 'Content-Type': 'application/javascript' },
    });
  }
  return undefined;
});

let fails = 0;
const lines = [];
function check(label, cond, extra) {
  lines.push((cond ? '  OK   ' : '  FAIL ') + label + (!cond && extra ? '  ← ' + extra : ''));
  if (!cond) fails += 1;
}
function section(name) { lines.push('== ' + name + ' =='); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ------------------------------------------------------------------ 虚拟排版模型
   jsdom 没有排版引擎（clientWidth/getBoundingClientRect 恒 0）。
   这里给"收藏页滚动容器"和"搜索页 .vlist"喂**可控的几何值**，
   让 app.js 的测量函数真的量到东西，从而验证它量到之后做的事对不对。 */
const LAYOUT = {
  pageScrollClientWidth: 1280 - 48 - 230 - 16,   // 视口宽 - 导航 - fav 左右 padding（近似）
  pageScrollClientHeight: 720 - 48,
  vlistContentTop: 190,          // .vlist 在滚动内容里的起始偏移（搜索框+工具栏）
  filterPanelH: 400,             // 更多筛选展开后新增的高度
  scrollTop: 0,
  filterOpen: false,
};

function installLayout(window) {
  const proto = window.HTMLElement.prototype;
  /* clientWidth / clientHeight：只对关心的容器返回模型值 */
  Object.defineProperty(proto, 'clientWidth', {
    configurable: true,
    get() {
      if (this.matches && this.matches('.page-scroll')) return LAYOUT.pageScrollClientWidth;
      return 0;
    },
  });
  Object.defineProperty(proto, 'clientHeight', {
    configurable: true,
    get() {
      if (this.matches && this.matches('.page-scroll')) return LAYOUT.pageScrollClientHeight;
      return 0;
    },
  });
  /* scrollTop：可写可读（jsdom 默认写死 0） */
  Object.defineProperty(proto, 'scrollTop', {
    configurable: true,
    get() {
      if (this.matches && this.matches('.page-scroll')) return LAYOUT.scrollTop;
      return 0;
    },
    set(v) {
      if (this.matches && this.matches('.page-scroll')) LAYOUT.scrollTop = Number(v) || 0;
    },
  });
  const rect = (top, height) => ({
    top, bottom: top + height, left: 0, right: LAYOUT.pageScrollClientWidth,
    width: LAYOUT.pageScrollClientWidth, height, x: 0, y: top, toJSON() {},
  });
  proto.getBoundingClientRect = function getBoundingClientRect() {
    if (this.matches && this.matches('.page-scroll')) return rect(0, LAYOUT.pageScrollClientHeight);
    if (this.matches && this.matches('.vlist')) {
      const extra = LAYOUT.filterOpen ? LAYOUT.filterPanelH : 0;
      /* 屏幕上的位置 = 内容偏移 - 已滚动量 */
      return rect(LAYOUT.vlistContentTop + extra - LAYOUT.scrollTop, 2000);
    }
    return rect(0, 0);
  };
}

function installBrowserShims(window) {
  /* ResizeObserver：jsdom 没有；记录被观察的元素，手动触发用 */
  const observers = [];
  window.ResizeObserver = class ResizeObserver {
    constructor(cb) { this.cb = cb; observers.push(this); this.targets = []; }
    observe(el) { this.targets.push(el); }
    unobserve(el) { this.targets = this.targets.filter((t) => t !== el); }
    disconnect() { this.targets = []; }
    trigger() { this.cb(this.targets.map((t) => ({ target: t })), this); }
  };
  window.__TG_OBSERVERS__ = observers;
  /* matchMedia：app.js 用（深色跟随系统） */
  if (!window.matchMedia) {
    window.matchMedia = (q) => ({
      matches: false, media: q, onchange: null,
      addListener() {}, removeListener() {},
      addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
    });
  }
  window.__TG_FAKE_ENV__ = true;
}

/* ------------------------------------------------------------------ 起 mock 服务 */
async function pingServer() {
  try {
    const r = await fetch(URL_BASE, { method: 'GET' });
    return r.ok;
  } catch (e) {
    return false;
  }
}
async function startServer() {
  /* 已有服务（比如手动起的 serve.py）就直接复用：这台机器的沙箱里
     Node 不能 spawn 子进程（EPERM），所以复用是主路径。 */
  if (await pingServer()) {
    lines.push('  ..   复用已在运行的 mock 服务 ' + URL_BASE);
    return null;
  }
  const py = process.env.PYTHON || 'python';
  const child = spawn(py, [path.join(__dirname, 'serve.py'), String(PORT)], {
    cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
  });
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('serve.py 启动超时')), 15000);
    const tryPing = async () => {
      if (await pingServer()) { clearTimeout(timer); resolve(child); }
      else setTimeout(tryPing, 200);
    };
    child.on('exit', (code) => { clearTimeout(timer); reject(new Error('serve.py 退出 ' + code)); });
    tryPing();
  });
}

/* 生产版 Vue 的 app._instance 是 null，根组件实例挂在挂载点的 _vnode.component 上 */
function getVm(window) {
  const appEl = window.document.getElementById('app');
  const vnode = appEl && appEl._vnode;
  const comp = vnode && vnode.component;
  return comp && comp.proxy ? comp.proxy : null;
}

/* jsdom 不派发 transitionend（Vue 的兜底计时器要等好几帧 + 真实时长），
   页面 out-in 过渡会**卡住** → 收藏页段一直没挂载。
   手动给带过渡类名的 section 派发 transitionend，模拟过渡结束。 */
async function settleTransitions(window, rounds) {
  for (let i = 0; i < (rounds || 3); i += 1) {
    const stuck = window.document.querySelectorAll(
      'section.page-leave-active, section.page-enter-active');
    if (!stuck.length && i > 0) return;
    Array.prototype.forEach.call(stuck, (el) => {
      el.dispatchEvent(new window.Event('transitionend', { bubbles: true }));
    });
    await sleep(60);
  }
}

/* ------------------------------------------------------------------ 启动 app */
async function bootApp(page) {
  const vc = new VirtualConsole();
  const errors = [];
  vc.on('jsdomError', (e) => {
    const msg = String(e && e.message);
    /* CSS 链接加载失败是队友正在写这些文件造成的瞬时噪音，与运行时行为无关 */
    if (/Could not load (link|stylesheet)/.test(msg)) return;
    errors.push(msg);
  });
  vc.on('error', (e) => errors.push(String(e && e.message)));
  LAYOUT.scrollTop = 0;
  LAYOUT.filterOpen = false;
  const dom = await JSDOM.fromURL(URL_BASE + '?page=' + page, {
    runScripts: 'dangerously',
    resources: { interceptors: [stubTailwind] },
    pretendToBeVisual: true,
    virtualConsole: vc,
    beforeParse(window) {
      installBrowserShims(window);
      installLayout(window);
    },
  });
  const window = dom.window;
  /* 等 Vue 挂载 + boot() 把资源库/收藏都拉完（收藏页要等 favItems 才有网格） */
  let vm = null;
  for (let i = 0; i < 120; i += 1) {
    await sleep(100);
    const p = getVm(window);
    if (p && p.items && p.items.length) {
      vm = p;
      break;
    }
  }
  if (!vm) throw new Error('app 没起来：' + errors.join(' | '));
  /* 把卡住的页面过渡推进完（jsdom 不发 transitionend），并确认落在目标页 */
  await settleTransitions(window, 4);
  if (vm.page !== page) {
    vm.doGoto(page);
    await settleTransitions(window, 4);
  }
  await sleep(120);
  await settleTransitions(window, 2);
  return { dom, window, vm, errors };
}

/* ================================================================ 测试主体 */
(async () => {
  const server = await startServer();
  try {
    /* ------------------------------------------------ ① 收藏页：先量后渲染 + 星标实心 */
    const fav = await bootApp('favorites');
    const { window, vm, errors } = fav;
    section('① 收藏页首帧列数正确（先量后渲染）+ ② 星标实心');

    /* 切到"常用工具"（mock 里这个收藏夹有 3 条收藏） */
    vm.favFolder = '常用工具';
    await sleep(150);
    check('favItems 有 3 条（mock：常用工具）', vm.favItems.length === 3,
      '实际 ' + vm.favItems.length);

    /* ② 收藏页里每张卡的 _fav 必须为 true（数据层），星标必须实心（DOM 层） */
    check('收藏页卡片 _fav 全为 true（数据层）',
      vm.favItems.every((it) => it._fav === true),
      JSON.stringify(vm.favItems.map((it) => [it.code, it._fav])));
    const doc = window.document;
    /* 只看**右上角按钮组里那颗星**（card-btn-group 的第一个 .card-btn），
       别把卡脚的 GitHub / 官网按钮也捞进来 */
    const starIcon = (card) => {
      const btn = card.querySelector('.card-btn-group > .card-btn .ic use');
      return btn ? (btn.getAttribute('href') || btn.getAttribute('xlink:href')) : null;
    };
    const starUses = Array.from(doc.querySelectorAll('.fav-grid > .card')).map(starIcon);
    check('收藏页星标渲染为 #i-star_solid（实心）',
      starUses.length > 0 && starUses.every((h) => h === '#i-star_solid'),
      JSON.stringify(starUses));

    /* ① 门控：favMeasured 必须为 true，且列数是按**真实宽度**算出来的（不是兜底 4/6） */
    check('favMeasured=true（量到宽度才渲染）', vm.favMeasured === true);
    const expectedW = LAYOUT.pageScrollClientWidth;
    check('favGridWidth 取到模型宽度', vm.favGridWidth === expectedW,
      vm.favGridWidth + ' vs ' + expectedW);
    const cols = vm.favLayout.columns;
    const gap = vm.favLayout.gap;
    const itemW = vm.favLayout.itemW;
    check('列数公式：columns 与 gap/itemW 自洽（cols*itemW+(cols-1)*gap ≈ avail）',
      Math.abs(cols * itemW + (cols - 1) * gap - expectedW) <= cols + 1,
      'cols=' + cols + ' itemW=' + itemW + ' gap=' + gap.toFixed(2));
    check('列数在 [1, 上限] 内且卡片不超 400px（maxCardW）',
      cols >= 1 && itemW > 0 && itemW <= 400, 'cols=' + cols + ' itemW=' + itemW);
    const gridEl = doc.querySelector('.fav-grid');
    check('网格 --fav-cols 与 JS 列数一致',
      gridEl && gridEl.style.getPropertyValue('--fav-cols') === String(cols),
      gridEl ? gridEl.style.getPropertyValue('--fav-cols') : 'no .fav-grid');

    /* 二次跳变检查：宽度不变时，重新测量**不得**改变列数（幂等） */
    const before = { c: vm.favLayout.columns, w: vm.favGridWidth };
    vm.measureFavGrid();
    await sleep(60);
    check('重复测量幂等（列数不再变化，无二次跳变）',
      vm.favLayout.columns === before.c && vm.favGridWidth === before.w,
      before.c + '→' + vm.favLayout.columns);

    /* 窗口变窄（ResizeObserver 触发）→ 列数应随之减少，这是唯一允许重排的路径 */
    LAYOUT.pageScrollClientWidth = 700;
    (window.__TG_OBSERVERS__ || []).forEach((o) => { if (o.targets.length) o.trigger(); });
    await sleep(80);
    check('容器变窄 → 列数变少（真 resize 才重排）',
      vm.favLayout.columns < before.c, before.c + '→' + vm.favLayout.columns);
    LAYOUT.pageScrollClientWidth = expectedW;
    (window.__TG_OBSERVERS__ || []).forEach((o) => { if (o.targets.length) o.trigger(); });
    await sleep(80);
    check('容器变宽 → 列数回到原值', vm.favLayout.columns === before.c,
      before.c + '→' + vm.favLayout.columns);

    /* ② 根因回归：资源库**重建**（loadResources）后 _fav 不能丢
       —— 这就是"重启后进收藏页空心星"的那条路 */
    await vm.runQuery();
    const reloaded = vm.items ? vm.items.length : 0;
    check('资源库条目仍在', reloaded > 0);
    vm.favFolder = '常用工具';
    await sleep(120);
    check('资源库重建后收藏页 _fav 仍为 true（syncFavoriteState 已补）',
      vm.favItems.length === 3 && vm.favItems.every((it) => it._fav === true),
      JSON.stringify(vm.favItems.map((it) => [it.code, it._fav])));

    /* 取消收藏 → 卡片从收藏页消失；再收藏 → 回来（mock 的 toggle 会把新收藏
       放进 Default，所以回到 Default 收藏夹验证），且 _fav=true */
    const first = vm.favItems[0];
    await vm.toggleFavorite(first);
    await sleep(250);
    check('取消收藏后该条不在收藏页', !vm.favItems.some((it) => it.code === first.code),
      'favItems=' + vm.favItems.length);
    check('取消后收藏页剩 2 张', vm.favItems.length === 2, '实际 ' + vm.favItems.length);
    const starUses2 = Array.from(doc.querySelectorAll('.fav-grid > .card')).map(starIcon);
    check('取消后网格剩 2 张卡且星仍全实心',
      starUses2.length === 2 && starUses2.every((h) => h === '#i-star_solid'),
      JSON.stringify(starUses2));
    await vm.toggleFavorite(first);
    await sleep(250);
    const inItems = vm.items.find((it) => it.code === first.code);
    check('再收藏后 items 的 _fav 同步为 true（搜索页一致性）',
      !!inItems && inItems._fav === true);
    vm.favFolder = 'Default';
    await sleep(150);
    const back = vm.favItems.find((it) => it.code === first.code);
    check('再收藏后出现在 Default 收藏夹且 _fav=true', !!back && back._fav === true);

    check('收藏页运行无 JS 错误', errors.length === 0, errors.slice(0, 2).join(' | '));
    fav.dom.window.close();

    /* ------------------------------------------------ ④ 详情页空字段整行不渲染 */
    const d = await bootApp('search');
    const { window: dw, vm: dvm } = d;
    section('④ 详情页空字段（CPU 架构等）整行不渲染');

    /* 找一条 architectures 为空的资源（TG-000005 / TG-000006 这类） */
    const noArch = dvm.items.find((it) => (!it.architectures || !it.architectures.length));
    check('资源库里存在"CPU 架构"为空的样本', !!noArch, '没有样本就无法验证');
    if (noArch) {
      await dvm.openDetail(noArch);
      await settleTransitions(dw, 4);
      await sleep(150);
      const labels = dvm.detailRows.map((r) => r.label);
      check('detailRows 不含"CPU 架构"行（空值整行剔除）',
        !labels.some((s) => /架构/.test(s)), JSON.stringify(labels));
      check('detailRows 不含任何空值行',
        dvm.detailRows.every((r) => String(r.value || '').trim().length > 0),
        JSON.stringify(dvm.detailRows.filter((r) => !String(r.value || '').trim())));
      const ddoc = dw.document;
      const keys = Array.from(ddoc.querySelectorAll('.detail-key')).map((e) => e.textContent.trim());
      check('DOM 里也查不到"CPU 架构"这个 label',
        !keys.some((s) => /架构/.test(s)), JSON.stringify(keys));
      const vals = Array.from(ddoc.querySelectorAll('.detail-val')).map((e) => e.textContent.trim());
      check('DOM 里没有任何"—"占位值', !vals.some((s) => s === '—' || s === '-'),
        JSON.stringify(vals));
      /* 有值的字段照常显示 */
      check('非空字段（类别/官网等）仍在', keys.length > 0, JSON.stringify(keys));
      dvm.closeDetail();
      await settleTransitions(dw, 4);
      await sleep(150);
    }

    /* ------------------------------------------------ ⑤ 虚拟列表可视区 */
    section('⑤ 更多筛选展开时顶部卡片不提前消失（可视区含 vlist 偏移）');
    const scdoc = dw.document;
    const scroller = scdoc.querySelector('[data-scroll-key="search"]');
    check('搜索页滚动容器在场（详情已关闭、过渡已落定）', !!scroller);
    check('searchScroll ref 已挂上', !!dvm.searchScroll);
    /* 先量一次：筛选收起时的偏移 */
    dvm.measureViewport();
    await sleep(60);
    const topClosed = dvm.vlistTop;
    check('筛选收起时 vlistTop = 头部高度（>0，量到了）', topClosed > 0, String(topClosed));

    /* 展开筛选 → 偏移必须变大约一个面板高 */
    dvm.toggleFilter();
    LAYOUT.filterOpen = true;
    await sleep(300);
    dvm.measureViewport();
    const topOpen = dvm.vlistTop;
    check('筛选展开后 vlistTop 变大（面板高度计入）',
      topOpen >= topClosed + 200, topClosed + ' → ' + topOpen);

    /* 关键断言：滚到 300（< topOpen）时，**第一行卡片必须还在渲染窗口里**。
       旧代码窗口上界 = scrollTop（300），而第一行 top=0 → 被裁掉 = 屏幕上有、DOM 里没有。
       新代码窗口上界 = scrollTop - vlistTop = 300-590 < 0 → clamp 到 0 → 第一行在场。 */
    LAYOUT.scrollTop = 300;
    dvm.onScrollArea();
    await sleep(120);
    const rows = dvm.vRows;
    check('滚动 300px（筛选展开）后 vRows 非空', rows.length > 0);
    /* 窗口必须从**内容最顶端**开始（rows[0].top===0）：默认按类别分组时
       第一行是组标题（top=0），卡片行紧随其后 —— 关键是"顶部的行没有被提前裁掉"。 */
    check('第一行仍在 DOM 窗口内（未提前消失）',
      rows.length > 0 && rows[0].top === 0,
      rows.length ? 'first top=' + rows[0].top : 'empty window');
    const firstItemsRow = rows.find((r) => r.type === 'items');
    check('首个卡片行也在窗口内（top=组标题高度）',
      !!firstItemsRow && firstItemsRow.top <= 40,
      firstItemsRow ? 'items row top=' + firstItemsRow.top : 'no items row');
    const rendered = scdoc.querySelectorAll('.vrow .card').length;
    check('渲染出的卡片数 > 0（屏幕上有卡片时 DOM 必须有）', rendered > 0, String(rendered));

    /* 真滚出可视区后，顶部行**应该**被裁掉（虚拟列表照常工作，不是不回收） */
    LAYOUT.scrollTop = 300 + topOpen + 4 * dvm.cardPx.height + 200;
    dvm.onScrollArea();
    await sleep(120);
    const rows2 = dvm.vRows;
    check('真正滚出后窗口前移（虚拟列表仍生效）',
      rows2.length > 0 && rows2[0].top > 0, 'first top=' + (rows2[0] && rows2[0].top));

    /* 收起筛选后重测：偏移回到小值 */
    LAYOUT.filterOpen = false;
    dvm.toggleFilter();
    await sleep(300);
    dvm.measureViewport();
    check('收起筛选后 vlistTop 回到收起值',
      Math.abs(dvm.vlistTop - topClosed) <= 2, dvm.vlistTop + ' vs ' + topClosed);

    check('搜索页运行无 JS 错误', d.errors.length === 0, d.errors.slice(0, 2).join(' | '));
    d.dom.window.close();
  } catch (e) {
    lines.push('  FAIL 运行器异常：' + (e && e.stack || e));
    fails += 1;
  } finally {
    if (server) server.kill();
  }

  console.log(lines.join('\n'));
  console.log(fails ? '\n结果：' + fails + ' 项失败' : '\n结果：全部通过');
  process.exit(fails ? 1 : 0);
})();
