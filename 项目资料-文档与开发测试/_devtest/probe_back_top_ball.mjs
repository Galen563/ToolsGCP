/* jsdom 探针：第七轮 task-22「回到顶部」悬浮球（m06914 第 4 条）
 *   范围：只允许出现在搜索页与定制页右下角，其它页面连节点都不该挂（v-if 闸门）
 *   出现/消失：向下滚出现（下往上渐变）；回到顶端消失（上往下淡出）
 *   点击：回到顶部，缓动必须"两头慢中间快"（easeInOutCubic），不能硬跳
 *   干扰：动画期间滚轮 / 触摸 / 翻页键要立刻接管；切页要取消动画并熄灭
 *   与 AI 悬浮球共存：z-index 更低 + .above-ball 上移让位
 * 用法：python serve.py <port> 后 GCP_PORT=<port> node probe_back_top_ball.mjs
 * ⚠️ 环境垫片同 probe_task13_maker_ui.mjs：jsdom 没有布局引擎（scrollHeight/clientHeight 恒 0、
 *   写 scrollTop 被静默丢掉），也不会在写 scrollTop 时自发派发 scroll 事件 ⇒ 本探针手动 dispatch。
 */
import { JSDOM, VirtualConsole } from 'jsdom';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const PORT = process.env.GCP_PORT || '8899';
const BASE = 'http://127.0.0.1:' + PORT;
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const require = createRequire(import.meta.url);
const results = [];
function record(name, ok, detail) {
  results.push({ name, ok });
  console.log((ok ? 'PASS' : 'FAIL') + '  ' + name
    + (detail !== undefined ? '  ' + JSON.stringify(detail) : ''));
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const Q = String.fromCharCode(39);

/* ========================= 静态契约 ========================= */
const html = await fs.readFile(path.join(ROOT, '.ToolsGCP/webui/index.html'), 'utf8');
const css = await fs.readFile(path.join(ROOT, '.ToolsGCP/webui/css/components.css'), 'utf8');
const app = await fs.readFile(path.join(ROOT, '.ToolsGCP/webui/js/app.js'), 'utf8');
/* 按窗口切片：默认 1200 字符，函数体这种要读到底的传 span */
const L = (s, sel, span) => {
  const at = s.indexOf(sel);
  return at < 0 ? '' : s.slice(at, at + (span || 1200));
};

const nodeSrc = L(html, 'class="back-top"');
record('S1 模板：节点只在 backTopPage 为真时挂，并绑齐 is-on / above-ball / 点击 / 图标 / 三语提示',
  html.indexOf('v-if="backTopPage"') >= 0 && nodeSrc.length > 0
  && nodeSrc.indexOf("'is-on': backTopVisible") >= 0
  && nodeSrc.indexOf("'above-ball': showBall") >= 0
  && nodeSrc.indexOf('@click="backToTop"') >= 0
  && nodeSrc.indexOf('#i-up') >= 0
  && nodeSrc.indexOf("t('back_to_top'") >= 0);

const pagesSrc = L(app, 'const BACK_TOP_PAGES', 400);
const OUT_OF_SCOPE = ['favorites', 'workshop', 'notice', 'github', 'more', 'settings', 'maker', 'ai', 'feedback'];
record('S2 范围只有搜索页与定制页（用户明确「其它页面不加入」）',
  app.indexOf("const BACK_TOP_PAGES = ['search', 'customize'];") >= 0
  && OUT_OF_SCOPE.every((k) => pagesSrc.indexOf("'" + k + "'") < 0), pagesSrc.slice(0, 80));

record('S3 监听对称：scroll 用捕获阶段注册（scroll 不冒泡）且卸载时同样带 true',
  app.indexOf("document.addEventListener('scroll', onAnyScrollForBall, true)") >= 0
  && app.indexOf("document.removeEventListener('scroll', onAnyScrollForBall, true)") >= 0
  && app.indexOf("window.addEventListener('wheel', onUserScrollInput") >= 0
  && app.indexOf("window.removeEventListener('wheel', onUserScrollInput)") >= 0);

const backTopCss = L(css, '.back-top {');
const aiDrawer = L(css, '.ai-drawer {');
const floatBall = L(css, '.float-ball {');
const zOf = (s) => { const m = /z-index:\s*(\d+)/.exec(s); return m ? Number(m[1]) : -1; };
record('S4 出现=下往上、消失=上往下（隐藏态 translateY(+14px)，.is-on 复位），不靠 <transition>',
  backTopCss.indexOf('transform: translateY(14px) scale(.94)') >= 0
  && backTopCss.indexOf('visibility: hidden') >= 0
  && backTopCss.indexOf('pointer-events: none') >= 0
  && backTopCss.indexOf('.back-top.is-on') >= 0 && backTopCss.indexOf('transform: none') >= 0
  && backTopCss.indexOf('opacity 180ms ease-out') >= 0
  && backTopCss.indexOf('visibility 0s linear 180ms') >= 0);
record('S4 与 AI 悬浮球共存：层级更低 + 有让位规则',
  zOf(backTopCss) >= 0 && zOf(backTopCss) < zOf(aiDrawer) && zOf(backTopCss) < zOf(floatBall)
  && css.indexOf('.back-top.above-ball') >= 0 && css.indexOf('bottom: 100px') >= 0,
  { backTop: zOf(backTopCss), aiDrawer: zOf(aiDrawer), floatBall: zOf(floatBall) });

const fnSrc = L(app, 'function backToTop', 3200);
/* 时长字面量是 tripwire：用户第十轮（m08106）要求看得清，从 0.55ms/px、360~880ms
   改成 0.9ms/px、900~1600ms。改回小数字会让这条 FAIL，逼人回看需求。 */
record('S5 缓动 = easeInOutCubic（两头慢中间快），时长随距离夹紧且下限看得见（不是瞬间硬跳）',
  fnSrc.indexOf('x < 0.5 ? 4 * x * x * x') >= 0 && fnSrc.indexOf('Math.pow(-2 * x + 2, 3) / 2') >= 0
  && fnSrc.indexOf('Math.min(1600, Math.max(900, Math.round(start * 0.9)))') >= 0);

const thrSrc = L(app, 'function backTopShowPx', 900);
const syncSrc = L(app, 'function syncBackTop', 700);
record('S5b 出现阈值按排距 × 1.5 现算，不再用一动就亮的字面 8px（用户 m08106 第二问）',
  app.indexOf('const BACK_TOP_ROW_FACTOR = 1.5;') >= 0
  && thrSrc.indexOf('backTopRowPitch(el)') >= 0
  && thrSrc.indexOf('pitch * BACK_TOP_ROW_FACTOR') >= 0
  && thrSrc.indexOf('BACK_TOP_SHOW_PX') >= 0
  && syncSrc.indexOf('node.scrollTop > backTopShowPx(node)') >= 0
  && fnSrc.indexOf('el.scrollTop > BACK_TOP_SHOW_PX') < 0
  && fnSrc.indexOf('el.scrollTop > showPx') >= 0, thrSrc.slice(0, 160));
/* 行距那段代码在 backTopRowPitch 里（backTopShowPx 只是乘系数），切片要按它取 */
const pitchSrc = L(app, 'function backTopRowPitch', 1200);
record('S5c 行距来源：搜索页读 .vrow 行内 height/gap（不复制布局算法），定制页读 .grid-static + 卡片 rect',
  pitchSrc.indexOf('querySelector(' + Q + '.vrow' + Q + ')') >= 0 && pitchSrc.indexOf('row.style.height') >= 0
  && pitchSrc.indexOf('row.style.gap') >= 0
  && pitchSrc.indexOf('querySelector(' + Q + '.grid-static' + Q + ')') >= 0 && pitchSrc.indexOf('rowGap') >= 0,
  pitchSrc.slice(0, 120));
record('S5 动画期间同步虚拟列表窗口量（搜索页滚动是 JS 量的，不同步会露空白行）',
  fnSrc.indexOf('scrollTop.value = el.scrollTop;') >= 0 && fnSrc.indexOf('measureViewport();') >= 0);
record('S5 用户接管：滚轮/触摸直接停，键盘只认滚动相关键（否则 AI 输入框打字会打断动画）',
  app.indexOf("if (ev && ev.type === 'keydown')") >= 0
  && app.indexOf("['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' ']") >= 0);

const i18nOk = [
  path.join(ROOT, '.ToolsGCP/modules/languages/zh_CN/common_language.json'),
  path.join(ROOT, '.ToolsGCP/modules/languages/zh_TW/common_language.json'),
  path.join(ROOT, '.ToolsGCP/modules/languages/en_US/common_language.json'),
].map((f) => require(f).back_to_top);
record('S6 提示文案三语齐备（不硬编码）', i18nOk.every((v) => typeof v === 'string' && v.length > 0), i18nOk);

/* ========================= jsdom 运行 ========================= */
function cutInlineScript(src, marker) {
  let at = src.indexOf(marker);
  let guard = 0;
  while (at >= 0 && guard++ < 10) {
    const open = src.lastIndexOf('<script', at);
    const close = src.indexOf('</' + 'script>', at);
    if (open < 0 || close < 0) break;
    src = src.slice(0, open) + src.slice(close + 9);
    at = src.indexOf(marker);
  }
  return src;
}
async function boot() {
  const vc = new VirtualConsole();
  vc.on('jsdomError', () => {});
  let page = await (await fetch(BASE + '/?page=search&auditfile=backtop_probe')).text();
  page = cutInlineScript(page, 'js/vendor/tailwind.js');
  page = cutInlineScript(page, 'tailwind.config');
  const dom = new JSDOM(page, {
    url: BASE + '/?page=search&auditfile=backtop_probe',
    runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(window) {
      window.fetch = (input, init) => fetch(new URL(String(input), BASE), init);
      window.Response = Response; window.Request = Request; window.Headers = Headers;
      window.Element.prototype.getBoundingClientRect = () => ({
        x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 100, height: 32, toJSON() {},
      });
      [window.Element.prototype, window.HTMLElement.prototype].forEach((proto) => {
        Object.defineProperty(proto, 'scrollTop', {
          configurable: true,
          get() { return this.__st || 0; },
          set(v) {
            const max = Math.max(0, (this.scrollHeight || 0) - (this.clientHeight || 0));
            this.__st = Math.max(0, Math.min(Number(v) || 0, max));
          },
        });
        Object.defineProperty(proto, 'scrollHeight', {
          configurable: true,
          get() { return this.__sh === undefined ? 5000 : this.__sh; },
          set(v) { this.__sh = Number(v) || 0; },
        });
        Object.defineProperty(proto, 'clientHeight', {
          configurable: true,
          get() { return this.__ch === undefined ? 600 : this.__ch; },
          set(v) { this.__ch = Number(v) || 0; },
        });
      });
      /* .page-scroll 在 layout.css 里是 overflow-y:auto；jsdom 不解析样式表 ⇒ 只覆盖这一个属性 */
      const realCS = window.getComputedStyle.bind(window);
      window.getComputedStyle = (el, pseudo) => {
        const cs = realCS(el, pseudo);
        if (el && el.matches && el.matches('.page-scroll')) {
          return new Proxy(cs, {
            get(t, p) {
              if (p === 'overflowY' || p === 'overflow-y') return 'auto';
              const v = Reflect.get(t, p);
              return typeof v === 'function' ? v.bind(t) : v;
            },
          });
        }
        return cs;
      };
    },
  });
  const win = dom.window;
  const t0 = Date.now();
  while (!win.__TOOLSGCP_APP__ && Date.now() - t0 < 25000) await sleep(100);
  if (!win.__TOOLSGCP_APP__) throw new Error('app 未挂载');
  return { win, vm: win.__TOOLSGCP_APP__ };
}
async function bootRetry() {
  let last = null;
  for (let i = 0; i < 5; i += 1) {
    try { return await boot(); } catch (e) { last = e; await sleep(1500); }
  }
  throw last;
}
const { win, vm } = await bootRetry();
await sleep(600);

const doc = () => win.document;
const ball = () => doc().querySelector('.back-top');
const scroller = (key) => doc().querySelector('[data-scroll-key="' + key + '"]');
/** 模拟用户滚动：jsdom 写 scrollTop 不会自发发 scroll 事件 */
function scrollTo(key, v) {
  const el = scroller(key);
  if (!el) return false;
  el.scrollTop = v;
  el.dispatchEvent(new win.Event('scroll'));
  return true;
}
async function settle(ms) { await sleep(ms || 60); }

vm.page = 'search';
await settle(200);
record('R1 搜索页挂了球，顶端时不亮', !!ball() && vm.backTopVisible === false,
  { node: !!ball(), visible: vm.backTopVisible });
/* 排距从页面自己渲染出来的 .vrow 行内样式读：与产品代码同源，但探针不复用
   backTopShowPx()，只拿 height/gap 两个数自己乘 1.5，算独立判定。 */
function pitchOf(key) {
  const el = scroller(key);
  if (!el) return 0;
  const row = el.querySelector('.vrow');
  if (row) {
    const h = parseFloat(row.style.height) || 0;
    const g = parseFloat(row.style.gap) || 0;
    if (h > 0) return h + g;
  }
  return 0;
}
const PITCH = pitchOf('search');
const THRESH = Math.round(PITCH * 1.5);
record('R1 前置：搜索页量到了行距（虚拟列表已渲染出 .vrow）', PITCH > 0,
  { pitch: PITCH, threshold: THRESH });
scrollTo('search', Math.round(PITCH * 0.5));
await settle(100);
record('R1 只翻半排 → 不亮（旧口径 8px 在这里会亮，正是要修的）', vm.backTopVisible === false,
  { at: Math.round(PITCH * 0.5), threshold: THRESH, visible: vm.backTopVisible });
scrollTo('search', PITCH + 2);
await settle(100);
record('R1 刚过一排（第二排还没到一半）→ 仍不亮', vm.backTopVisible === false,
  { at: PITCH + 2, threshold: THRESH, visible: vm.backTopVisible });
scrollTo('search', THRESH + 40);
await settle(100);
record('R1 翻过约 1.5 排 → 出现（scroll 捕获监听真的收到了）', vm.backTopVisible === true,
  { at: THRESH + 40, visible: vm.backTopVisible });
scrollTo('search', 0);
await settle(100);
record('R1 滚回顶端 → 消失（上往下淡出）', vm.backTopVisible === false, { visible: vm.backTopVisible });
scrollTo('search', THRESH + 200);
await settle(100);
scrollTo('search', 5);
await settle(100);
record('R1 半路回滚到 5px（还没到 0）也按阈值熄灭', vm.backTopVisible === false,
  { visible: vm.backTopVisible });

/* 点击回到顶部：逐帧采样，验证曲线形状与落点 */
scrollTo('search', Math.max(1200, THRESH + 600));
await settle(100);
const elSearch = scroller('search');
const seq = [];
const clickAt = Date.now();
ball().click();
/* 采样窗口要盖住最坏时长（上限 1600ms）：旧窗口 40×25ms 只有 1 秒，慢动画会被误判成没收敛 */
for (let i = 0; i < 140; i += 1) { await sleep(25); seq.push(elSearch.scrollTop); if (elSearch.scrollTop === 0) break; }
const animMs = Date.now() - clickAt;
await settle(120);
record('R3 滚动时长看得见（>= 850ms，用户 m08106：速度要让用户能看清而不是特别快）', animMs >= 850,
  { animMs, start: Math.max(1200, THRESH + 600) });
const deltas = [];
for (let i = 1; i < seq.length; i += 1) deltas.push(seq[i - 1] - seq[i]);
const maxD = Math.max.apply(null, deltas);
record('R3 点击后逐帧收敛到 0（不是瞬间硬跳）', seq.length >= 4 && elSearch.scrollTop === 0,
  { frames: seq.length, head: seq.slice(0, 4), tail: seq.slice(-3) });
record('R3 两头慢中间快：首帧步长与末帧步长都明显小于中段最大步长',
  deltas.length >= 3 && deltas[0] < maxD && deltas[deltas.length - 1] < maxD,
  { first: deltas[0], last: deltas[deltas.length - 1], max: maxD });
record('R3 全程单调不回弹、落定后球熄灭', deltas.every((d) => d >= 0) && vm.backTopVisible === false);

/* 用户滚轮打断 */
scrollTo('search', 1500);
await settle(100);
ball().click();
await sleep(70);
const beforeAbort = scroller('search').scrollTop;
win.dispatchEvent(new win.WheelEvent('wheel', { deltaY: 120 }));
await sleep(320);
record('R4 动画期间滚轮立即接管（位置不再被动画改写）',
  beforeAbort > 0 && scroller('search').scrollTop === beforeAbort,
  { at: beforeAbort, after: scroller('search').scrollTop });
scrollTo('search', 0);
await settle(100);

/* 其它页面不挂 */
vm.page = 'favorites';
await settle(400);
record('R2 收藏页连节点都不挂（范围=只加搜索页与定制页）', !ball() && vm.backTopVisible === false,
  { node: !!ball(), visible: vm.backTopVisible });
vm.page = 'maker';
await settle(400);
record('R2 投稿页同样不挂', !ball());
vm.page = 'customize';
await settle(500);
record('R2 定制页挂了球', !!ball());
scrollTo('customize', 300);   /* jsdom 量不到卡片真实高度 ⇒ 走 8px 下限，300 足够越过 */
await settle(100);
record('R2 定制页滚动生效：滚下去会亮', vm.backTopVisible === true, { visible: vm.backTopVisible });

/* ⚠️ 回归锁：切页过渡的 @after-enter 会跑 restorePageScroll（把位置恢复成记忆里的值），
   它发生在新页面挂载之后几百毫秒 —— 如果用户已经先滚了一下，就会被**拽回去**
   （真实缺陷：画面瞬间跳回顶部，右下角球跟着熄灭，像滚动失灵）。
   这里等够长（覆盖 out-in 过渡 + @after-enter），确认位置没有被篡改。 */
await settle(700);
const custAfter = scroller('customize');
record('R2b 定制页：恢复位置不会把用户刚滚出来的位置拽回去（restorePageScroll 不得覆盖用户操作）',
  custAfter && custAfter.scrollTop === 300 && vm.backTopVisible === true,
  { after: custAfter && custAfter.scrollTop, visible: vm.backTopVisible });

/* 切页熄灭 + 取消动画（⚠️ 引用必须在切页前拿：v-if 会把整段摘掉） */
scrollTo('customize', 900);
await settle(100);
const cust = scroller('customize');
ball().click();
vm.page = 'search';
await settle(500);
record('R6 动画没跑完就切页：旧容器不再被改写（rAF 已取消）、球熄灭',
  vm.backTopVisible === false && cust.scrollTop === 900 && cust.isConnected === false,
  { custTop: cust.scrollTop, connected: cust.isConnected, visible: vm.backTopVisible });
record('R6 切回搜索页后球重新挂上并按当前位置判定（顶端 ⇒ 不亮）',
  !!ball() && vm.backTopVisible === false);

/* 与 AI 悬浮球的互斥类 */
scrollTo('search', 400);
await settle(100);
/* 两种状态都可能出现（取决于本机 AI 设置），要求是"严格同步"：AI 球开着就得让位 */
record('R5 .above-ball 与 showBall 严格同步（AI 悬浮球开着时上移让位）',
  ball().classList.contains('above-ball') === !!vm.showBall, { showBall: !!vm.showBall });

const failed = results.filter((r) => !r.ok);
console.log('----------------------------------------------------------');
console.log('合计 ' + results.length + ' 项，通过 ' + (results.length - failed.length) + '，失败 ' + failed.length);
if (failed.length) {
  failed.forEach((f) => console.log('  ✗ ' + f.name));
  process.exit(1);
}
console.log('ALL OK');

