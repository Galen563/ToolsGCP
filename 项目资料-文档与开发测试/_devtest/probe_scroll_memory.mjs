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


/* ========================= 交叉验证：切走再切回要回原位 ========================= */

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
async function bootX() {
  const vc = new VirtualConsole();
  vc.on('jsdomError', () => {});
  let page = await (await fetch(BASE + '/?page=search&auditfile=backtop_probe2')).text();
  page = cutInlineScript(page, 'js/vendor/tailwind.js');
  page = cutInlineScript(page, 'tailwind.config');
  const dom = new JSDOM(page, {
    url: BASE + '/?page=search&auditfile=backtop_probe2',
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
async function bootXRetry() {
  let last = null;
  for (let i = 0; i < 5; i += 1) {
    try { return await bootX(); } catch (e) { last = e; await sleep(1500); }
  }
  throw last;
}
const X = await bootXRetry();
await sleep(600);
const xdoc = () => X.win.document;
const xscroller = (key) => xdoc().querySelector('[data-scroll-key="' + key + '"]');
function xscrollTo(key, v) {
  const el = xscroller(key);
  if (!el) return false;
  el.scrollTop = v;
  el.dispatchEvent(new X.win.Event('scroll'));
  return true;
}
async function xsettle(ms) { await sleep(ms || 60); }

X.vm.page = 'search';
await xsettle(300);
xscrollTo('search', 800);
await xsettle(150);
const before = xscroller('search').scrollTop;
/* 切走：rememberPageScroll 会把 800 记进 pageScrollMemory.search */
X.vm.doGoto('favorites');
await xsettle(700);
X.vm.doGoto('search');
await xsettle(900);
const after = xscroller('search') ? xscroller('search').scrollTop : -1;
record('X1 搜索页切走再切回 → 恢复到原位（本次修复不得破坏这个既有需求）',
  before === 800 && after === 800, { before, after });

/* 切回后再滚动 → 仍要能自由滚（修复不得把容器锁死在恢复值上） */
xscrollTo('search', 1200);
await xsettle(150);
record('X2 切回后继续滚动正常（修复不得锁死容器）', xscroller('search').scrollTop === 1200,
  { at: xscroller('search').scrollTop });

/* 切到定制页 → 切回搜索页：定制页不写记忆，搜索页恢复仍要生效 */
xscrollTo('search', 900);
await xsettle(150);
X.vm.doGoto('customize');
await xsettle(700);
X.vm.doGoto('search');
await xsettle(900);
const after2 = xscroller('search') ? xscroller('search').scrollTop : -1;
record('X3 经定制页中转切回搜索页 → 仍恢复原位', after2 === 900, { after2 });

console.log('\n合计 ' + results.length + ' 项，通过 ' + results.filter((r) => r.ok).length
  + '，失败 ' + results.filter((r) => !r.ok).length);
console.log(results.every((r) => r.ok) ? 'ALL OK' : 'FAIL');
process.exit(results.every((r) => r.ok) ? 0 : 1);
