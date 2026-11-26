/* 详情页 UI 回归探针（task-5 三项需求的长期回归证据）。
 *   A) 「官方」/「知名」金色标签：深色 #d4af37 + 浅色 #8a6100，
 *      且两条规则的特异度必须分别高于 :root[data-theme="light"] .tag 那条灰底 ——
 *      这正是历史上"浅色主题下官方标签变灰胶囊"的根因，必须钉死。
 *   B) 编号右侧的复制按钮（走真实入口 openDetail，别直接赋 detail 绕过 detailPage）
 *   C) 详情页名称/编号/应用介绍/详细信息可框选，而按钮/导航/卡片控件仍不可选
 *      （全局翻转 user-select 会误伤，这条断言专防它）
 * ⚠️ jsdom 没有布局引擎：这里验的是 CSSOM 规则与 getComputedStyle 计算值，不是像素。
 * 用法：python serve.py <port> 后 GCP_PORT=<port> node probe_detail_ui.mjs
 *
 * 原始出处：lead 独立验证 task-5 的三件事（不依赖队友自检）：
 *   A) 「知名」标签在深色/浅色主题下都是金色（浅色是当年那个 bug 的回归点）
 *   B) 编号右侧有同款复制按钮，点它复制的是编号本身
 *   C) 详情页名称/编号/应用介绍/详细信息可框选，而按钮/导航仍不可选（没有全局误伤）
 * jsdom 没有布局引擎，但 CSSOM 与 getComputedStyle 是可用的 —— 这里验的是**规则与计算值**，
 * 不是像素。 */
import { JSDOM, VirtualConsole } from 'jsdom';
const PORT = process.env.GCP_PORT || '8899';
const BASE = 'http://127.0.0.1:' + PORT;
const out = [];
const record = (n, ok, d) => { out.push({ n, ok }); console.log((ok ? 'PASS' : 'FAIL') + '  ' + n + (d !== undefined ? '  ' + JSON.stringify(d) : '')); };
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

/* 精确删掉包含 marker 的那段内联 <script>（只用 indexOf，避免正则跨标签误伤） */
function cutInlineScript(html, marker) {
  let at = html.indexOf(marker);
  let guard = 0;
  while (at >= 0 && guard++ < 10) {
    const open = html.lastIndexOf('<script', at);
    const close = html.indexOf('</' + 'script>', at);
    if (open < 0 || close < 0) break;
    html = html.slice(0, open) + html.slice(close + 9);
    at = html.indexOf(marker);
  }
  return html;
}
async function boot(theme) {
  const vc = new VirtualConsole(); vc.on('jsdomError', () => {});
  let html = await (await fetch(BASE + '/?page=search&theme=' + theme)).text();
  html = html.replace(/<script src="\/static\/js\/vendor\/tailwind\.js"[\s\S]*?<\/script>/, '');
  html = cutInlineScript(html, 'tailwind.config');
  const dom = new JSDOM(html, {
    url: BASE + '/?page=search&theme=' + theme, runScripts: 'dangerously',
    resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.fetch = (i, o) => fetch(new URL(String(i), BASE), o);
      w.Response = Response; w.Request = Request; w.Headers = Headers;
      w.Element.prototype.getBoundingClientRect = () => ({ x:0,y:0,top:0,left:0,right:0,bottom:0,width:120,height:32,toJSON(){} });
    },
  });
  const win = dom.window;
  const t0 = Date.now();
  while (!win.__TOOLSGCP_APP__ && Date.now() - t0 < 25000) await sleep(100);
  if (!win.__TOOLSGCP_APP__) throw new Error('app 未挂载（theme=' + theme + '）');
  return { win, vm: win.__TOOLSGCP_APP__ };
}

/* 队友并发写 index.html/app.js 时 serve.py 会吐回半截文件 → 挂载失败，重试几次
   （与 settings_probe_jsdom.mjs 的 bootPageRetry 同一套路） */
async function bootRetry(theme) {
  let last = null;
  for (let i = 0; i < 5; i += 1) {
    try { return await boot(theme); }
    catch (e) { last = e; await sleep(1500); }
  }
  throw last;
}

/* 从 CSSOM 里取某个选择器的声明（jsdom 会解析真实 CSS 文件） */
function ruleFor(doc, sel) {
  for (const sheet of doc.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch (e) { continue; }
    for (const r of rules) {
      if (r.type === 1 && r.selectorText && r.selectorText.replace(/\s+/g, ' ').includes(sel)) {
        return { selector: r.selectorText, css: r.style.cssText };
      }
    }
  }
  return null;
}

/* 等样式表真正落地再断言 CSS 规则。
   为什么需要：index.html 已把 13 个 CSS <link> 挪到脚本**之前**（需求②的根治点），
   于是 CSS 请求与脚本并发；app 挂载（Vue 就绪）可能早于最后一个 CSS 落地，
   此时 document.styleSheets 里还缺组件样式，规则断言必然假失败。
   浏览器里也是同一件事：CSS 是异步到达的，只是它到了会自己生效。
   判据用「已落地的样式表数量 ≥ 13」，等不到就超时继续（不让探针卡死）。 */
async function waitStyles(win, want, timeoutMs) {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const t0 = Date.now();
  let n = 0;
  while (Date.now() - t0 < (timeoutMs || 20000)) {
    n = 0;
    for (const sheet of win.document.styleSheets) {
      try { if (sheet.cssRules && sheet.cssRules.length) n += 1; } catch (e) { /* 跨域跳过 */ }
    }
    if (n >= (want || 13)) return n;
    await sleep(200);
  }
  return n;
}
const { win, vm } = await bootRetry('dark');
const loadedSheets = await waitStyles(win, 13, 20000);
record('A0 13 个样式表已落地（CSS 断言的前置条件）', loadedSheets >= 13, { loadedSheets });
/* ---- A) 金色标签：两条规则都在，且特异度关系正确 ---- */
const darkRule = ruleFor(win.document, '.tag.is-famous');
const lightRule = (() => {
  // 浅色那条带 [data-theme="light"]，切 data-theme 后再取
  return null;
})();
record('A1 深色主题下 .tag.is-famous 有金色规则（与 is-official 同色）',
  !!darkRule && /d4af37/i.test(darkRule.css), { found: !!darkRule, css: darkRule.css });
record('A2 该规则以 :root 开头（特异度 0,3,0，不被 .tag 灰底盖掉）',
  !!darkRule && /^:root(\s|\[)/.test(darkRule.selector), { selector: darkRule.selector });

const light = await bootRetry('light');
/* 第二个实例的 CSS 同样是异步落地，必须等它到齐再查浅色规则 */
await waitStyles(light.win, 13, 20000);
win.document.documentElement.setAttribute('data-theme', 'light');
light.win.document.documentElement.setAttribute('data-theme', 'light');
const lDark = ruleFor(light.win.document, '.tag.is-famous');
const lLight = (() => {
  for (const sheet of light.win.document.styleSheets) {
    let rules; try { rules = sheet.cssRules; } catch (e) { continue; }
    for (const r of rules) {
      if (r.type === 1 && r.selectorText && r.selectorText.includes('[data-theme="light"]')
          && r.selectorText.includes('.tag.is-famous')) return { selector: r.selectorText, css: r.style.cssText };
    }
  }
  return null;
})();
record('A3 浅色主题下 .tag.is-famous 有更深的金色规则（0,4,0）',
  !!lLight && /8a6100|#8a6100/i.test(lLight.css), { css: lLight && lLight.css });
/* selectorText 是**逗号分隔的多选择器列表**（jsdom 原样保留），
   所以要按逗号拆开逐个看，而不是 split(' ')[1]。 */
const lightParts = (lLight ? lLight.selector.split(',').map((s) => s.replace(/\s+/g, ' ').trim()) : []);
record('A4 浅色那条包含 :root[data-theme="light"] .tag.is-famous（0,4,0，压过 .tag 灰底）',
  lightParts.some((s) => s === ':root[data-theme="light"] .tag.is-famous'), { parts: lightParts });

/* ---- B) 编号复制按钮：渲染真实详情页 ---- */
/* ---- B) 编号复制按钮：走真实入口 openDetail ----
   ⚠️ 详情页的渲染条件是 (page in [search/customize/favorites/deploy]) && detail
      && page === detailPage —— 直接给 vm.detail 赋值会绕过 detailPage，
      整段根本不渲染（第一版就是这么误判成"按钮不存在"的）。
      openDetail(item) 内部会同时设 detail 与 detailPage，是唯一正确的驱动方式。 */
const { win: w2, vm: vm2 } = await bootRetry('dark');
const t1 = Date.now();
while (!(vm2.items && vm2.items.length) && Date.now() - t1 < 20000) await sleep(150);
record('B0 资源列表已加载', (vm2.items || []).length > 0, { count: (vm2.items || []).length });
vm2.page = 'search';
await sleep(200);
await vm2.openDetail(vm2.items[0]);
await sleep(700);
record('B0b 详情页已渲染（page === detailPage 且 detail 有值）',
  !!vm2.detail && vm2.page === vm2.detailPage,
  { page: vm2.page, detailPage: vm2.detailPage, hasDetail: !!vm2.detail });
const code = String(vm2.detail && vm2.detail.code || '');
const codeRow = w2.document.querySelector('.detail-code');
const btn = codeRow && codeRow.querySelector('button.copy-btn');
record('B1 编号右侧有 .detail-code 行 + 同款 copy-btn', !!codeRow && !!btn,
  { row: !!codeRow, btn: !!btn, code });
if (btn) {
  const svg = btn.querySelector('use');
  record('B2 按钮图标用 #i-copy（与详细信息那排一致）',
    !!svg && /#i-copy/.test(svg.getAttribute('href') || ''), { href: svg && svg.getAttribute('href') });
  w2.__MOCK_CLIPBOARD__ = 'SENTINEL';
  btn.click();
  await sleep(500);
  record('B3 点击复制的是编号本身（不带「编码：」前缀）',
    w2.__MOCK_CLIPBOARD__ === code, { clipboard: w2.__MOCK_CLIPBOARD__, code });
  record('B4 复制后按钮切到已复制态（is-done + #i-accept）',
    btn.classList.contains('is-done') || /#i-accept/.test((btn.querySelector('use') || {}).href || ''),
    { cls: btn.className, href: (btn.querySelector('use') || {}).href });
}

/* ---- C) 框选：详情页四类元素可选，交互控件仍不可选 ---- */
const sel = (w, selector) => {
  const el = w.document.querySelector(selector);
  if (!el) return null;
  return w.getComputedStyle(el).userSelect || w.getComputedStyle(el).getPropertyValue('user-select');
};
const targets = [
  ['名称 .detail-name', '.detail-name'],
  ['编号行 .detail-code .cap', '.detail-code .cap'],
  ['应用介绍 .para', '.detail-block .para'],
  ['详细信息值 .detail-val', '.detail-val'],
];
for (const [label, q] of targets) {
  const v = sel(w2, q);
  record('C 可框选：' + label, v === 'text', { value: v, found: v !== null });
}
const keep = [
  ['按钮 .btn', '.detail-topbar .btn'],
  ['左侧导航 .nav-item', '.nav-item'],
  ['卡片按钮 .card-btn', '.card-btn'],
];
for (const [label, q] of keep) {
  const el = w2.document.querySelector(q);
  if (!el) { record('C 不误伤：' + label + '（DOM 里没这个元素，跳过）', true, { skipped: true }); continue; }
  const v = w2.getComputedStyle(el).userSelect;
  record('C 不误伤：' + label + ' 仍不可选', v === 'none', { value: v });
}

process.exit(out.some(o => !o.ok) ? 1 : 0);