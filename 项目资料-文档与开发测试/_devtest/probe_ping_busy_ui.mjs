/* 第五轮需求①④回归探针：详情页「测 Ping」按钮的进行中状态 + 提示停留 4 秒。
 *  S) 源码级不变量：模板绑定、状态机四件套、CSS 那一族规则不许出现任何尺寸属性、时长口径
 *  R) 真链路（jsdom 挂载 + 可控 ping 桩）：忙态 / 防重复 / 点阵 1→2→3→1 / 忙闲两态盒子逐项
 *     相等 / 四条退出路径全部恢复 / 按行并发互不熄灭 / 结束后计时器停表 / 提示实测停留 4 秒
 * ⚠️ jsdom 没有布局引擎：尺寸比的是样式表声明的固定盒（.copy-btn 28×28）在各帧的计算值。
 * ⚠️ 两条探针自身的规矩（第一版就是踩了这两条才假失败）：
 *    ① 忙/闲一律先等**响应式标记**（vm.pingIsBusy）落定，再 sleep 让 Vue flush，最后才查 DOM；
 *       直接查 DOM 会读到上一帧的 className（点击后同帧内 DOM 还没更新）。
 *    ② 忙期里不要顺带做重 DOM 查询：jsdom 在事件循环被占时会把 setInterval 的多次回调
 *       合并成一次突发，试点阵节奏必须用只读 computed 的轻量采样环。
 * ⚠️ serve.py 的 mock 里没有 shell.ping（真实桌面端才有），桩由本探针自己挂；
 *    延迟与返回值按 **url** 指定（不按调用顺序），并发用例才不会串味。
 * 用法：python serve.py 8912 之后 GCP_PORT=8912 node probe_ping_busy_ui.mjs */
import { JSDOM, VirtualConsole } from 'jsdom';
import fs from 'node:fs';

const PORT = process.env.GCP_PORT || '8899';
const BASE = 'http://127.0.0.1:' + PORT;
const ROOT = process.env.GCP_ROOT || 'C:/Users/Administrator/Desktop/ToolsGCP开发/v1.1.4 - 12';
const out = [];
const record = (n, ok, d) => { out.push({ n, ok }); console.log((ok ? 'PASS' : 'FAIL') + '  ' + n + (d !== undefined ? '  ' + JSON.stringify(d) : '')); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const rd = (rel) => fs.readFileSync(ROOT + '/' + rel, 'utf8');

/* ============================ S) 源码级不变量 ============================ */
const html = rd('.ToolsGCP/webui/index.html');
const appjs = rd('.ToolsGCP/webui/js/app.js');
const layout = rd('.ToolsGCP/webui/css/layout.css');

record('S1 模板：ping 按钮绑 is-busy 类与 :disabled=pingIsBusy(row)',
  /class="copy-btn"[\s\S]{0,140}'is-busy':\s*pingIsBusy\(row\)[\s\S]{0,140}:disabled="pingIsBusy\(row\)"/.test(html));
record('S1 模板：忙时换掉的只是盒子里的内容（svg v-if / span.ping-dots v-else）',
  /<svg v-if="!pingIsBusy\(row\)"[\s\S]{0,140}#i-ping[\s\S]{0,60}\/svg>/.test(html)
  && /<span v-else class="ping-dots"[\s\S]{0,80}\{\{\s*pingDotsText\s*\}\}/.test(html));
record('S2 状态机四件套齐备 + 共享点阵计数',
  /function pingRowKey\(/.test(appjs) && /function pingBusyStart\(/.test(appjs)
  && /function pingBusyEnd\(/.test(appjs) && /function pingIsBusy\(/.test(appjs)
  && /const pingDotsText = computed/.test(appjs));
const drp = appjs.slice(appjs.indexOf('async function detailRowPing'), appjs.indexOf('function enterCardMenuKey'));
record('S2 detailRowPing 用 try/finally 收尾（四条退出路径共用一个恢复点）',
  /pingBusyStart\(key\)/.test(drp) && /finally\s*\{[\s\S]*pingBusyEnd\(key\)/.test(drp)
  && /if \(pingIsBusy\(row\)\) return;/.test(drp), { len: drp.length });
record('S2 pingBusyEnd 在表空时 clearInterval（不留常驻 tick 白重渲染整页）',
  /function pingBusyEnd[\s\S]{0,240}clearInterval\(pingTickTimer\);\s*pingTickTimer = null/.test(appjs));
/* 步进间隔从源码里**读出来**再判，不再写死数字：第七轮用户要求「间隔时间太长了 减小间隔时间」，
   于是 380ms → PING_TICK_MS=160ms。写死 380 的断言会把"以后继续微调"变成"必须改探针"，
   而真正要守住的是「间隔不超过 200ms」这条需求口径 + 「计时器确实读的是这个常量」。 */
const tickM = appjs.match(/const PING_TICK_MS = (\d+);/);
const tickMs = tickM ? Number(tickM[1]) : -1;
record('S2 点阵步进间隔抽成常量且 <=200ms（第七轮需求：间隔要短）',
  tickMs > 0 && tickMs <= 200, { PING_TICK_MS: tickMs });
record('S2 setInterval 用的是常量而非裸数字（避免"改常量探针测不到"）',
  /setInterval\(\(\) => \{ pingTickCount\.value = pingTickCount\.value % 3 \+ 1; \}, PING_TICK_MS\)/.test(appjs));
record('S2 暴露处含 pingIsBusy 与 pingDotsText（漏一个模板就取不到）',
  /pingIsBusy,\s*pingDotsText/.test(appjs));

function rulesFor(rx, src) {
  const hits = [];
  const g = new RegExp(rx.source, 'g');
  let m;
  while ((m = g.exec(src))) {
    const open = src.indexOf('{', m.index);
    const close = src.indexOf('}', open);
    if (open < 0 || close < 0) continue;
    hits.push({ sel: src.slice(m.index, open).replace(/\s+/g, ' ').trim(), body: src.slice(open + 1, close) });
  }
  return hits;
}
const SIZE_PROPS = ['width', 'height', 'padding', 'margin', 'border', 'gap', 'min-width', 'max-width', 'min-height', 'flex', 'font-family', 'transform', 'position'];
const busyRules = rulesFor(/\.copy-btn:disabled|\.copy-btn\.is-busy|\.copy-btn \.ping-dots/g, layout);
record('S3 busy 一族规则存在（>=3 条）', busyRules.length >= 3, { n: busyRules.length, sels: busyRules.map((r) => r.sel) });
const offenders = busyRules.filter((r) => SIZE_PROPS.some((p) => new RegExp('(^|[;\\s])' + p + '\\s*:').test(r.body)));
record('S3 busy 一族里没有任何尺寸类属性（盒子只由 .copy-btn 定死）', offenders.length === 0,
  offenders.map((r) => r.sel + ' { ' + r.body.replace(/\s+/g, ' ').slice(0, 90) + ' }'));
record('S3 .copy-btn 仍是固定 28×28 + flex 0 0 auto',
  /\.copy-btn\s*\{[^}]*width:\s*28px[^}]*height:\s*28px[^}]*flex:\s*0 0 auto/.test(layout));
record('S3 点阵等宽数字 + 不换行（跳字不撑宽）',
  /\.ping-dots[^}]*font-variant-numeric:\s*tabular-nums[^}]*white-space:\s*nowrap/.test(layout));

const pingBody = appjs.slice(appjs.indexOf('async function pingTarget'), appjs.indexOf('async function cardMenuPing'));
record('S4 需求①：结果与失败提示都写死 duration 4000',
  (pingBody.match(/duration: 4000/g) || []).length === 2, pingBody.match(/duration: \d+/g) || []);
record('S4 需求①：Ping 链路里不再残留 6000 或其它时长',
  !/duration:\s*(?!4000)\d+/.test(pingBody), pingBody.match(/duration: \d+/g) || []);
record('S4 需求①：四条退出路径的提前 return 都还在（改动没吃掉分支）',
  /ping_no_target/.test(pingBody) && /needApi\('shell\.ping'/.test(pingBody) && /ping_failed/.test(pingBody));

/* ============================ R) 真链路 ============================ */
function cutInlineScript(src, marker) {
  let at = src.indexOf(marker), guard = 0;
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
  const errs = [];
  vc.on('jsdomError', (e) => errs.push(String((e && (e.detail && e.detail.stack || e.message)) || e).replace(/\s+/g, ' ').slice(0, 200)));
  let page = await (await fetch(BASE + '/')).text();
  page = page.replace(/<script src="\/static\/js\/vendor\/tailwind\.js"[\s\S]*?<\/script>/, '');
  page = cutInlineScript(page, 'tailwind.config');
  const dom = new JSDOM(page, {
    url: BASE + '/', runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.fetch = (i, o) => fetch(new URL(String(i), BASE), o);
      w.Response = Response; w.Request = Request; w.Headers = Headers;
      w.Element.prototype.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 28, height: 28, toJSON() {} });
    },
  });
  const win = dom.window;
  const t0 = Date.now();
  while (!win.__TOOLSGCP_APP__ && Date.now() - t0 < 25000) await sleep(100);
  if (!win.__TOOLSGCP_APP__) throw new Error('app 未挂载');
  return { win, vm: win.__TOOLSGCP_APP__, errs };
}
let win = null, vm = null, errs = [];
for (let i = 0; i < 5; i += 1) { try { const r = await boot(); win = r.win; vm = r.vm; errs = r.errs; break; } catch (e) { await sleep(1500); } }
if (!vm) { console.log('FATAL app 未挂载（serve.py 起了吗 / 端口对吗）'); process.exit(1); }
await sleep(1700);
const t1 = Date.now();
while (!(vm.items && vm.items.length) && Date.now() - t1 < 20000) await sleep(150);
record('R0 应用挂载 + 资源加载（jsdomError ' + errs.length + ' 条）', (vm.items || []).length > 0 && errs.length === 0,
  { count: (vm.items || []).length, errs: errs.slice(0, 2) });

const PING = { calls: [], byUrl: {}, defDelay: 600, defResult: null };
const OK_RESULT = () => ({ ok: true, dns_ms: 12, tcp_ms: 30, tls_ms: 41, total_ms: 83 });
function setStub() {
  PING.calls.length = 0; PING.byUrl = {}; PING.defDelay = 600; PING.defResult = OK_RESULT();
  win.pywebview.api.shell.ping = async function (url) {
    const step = PING.byUrl[String(url)] || { delay: PING.defDelay, result: PING.defResult };
    PING.calls.push({ url, at: Date.now() });
    await sleep(step.delay);
    return step.result;
  };
}
function dropStub() { delete win.pywebview.api.shell.ping; }

vm.page = 'search';
await sleep(150);
let picked = null, pickedRows = null;
for (const it of (vm.items || []).slice(0, 24)) {
  await vm.openDetail(it);
  await sleep(220);
  const rows = (vm.detailRows || []).filter((r) => r.link);
  if (rows.length >= 2) { picked = it; pickedRows = rows; break; }
  if (!picked && rows.length === 1) { picked = it; pickedRows = rows; }
}
record('R1 打开详情且存在链接行（并发用例要两行）', !!picked && pickedRows.length >= 1,
  { name: picked && picked.name, linkRows: pickedRows ? pickedRows.length : 0 });
const doc = win.document;
const linkRowEls = () => Array.from(doc.querySelectorAll('.detail-grid .detail-val.row'));
const pingBtnOf = (rowEl) => { const b = rowEl.querySelectorAll('.copy-btn'); return b[b.length - 1]; };
const SIZE_KEYS = ['width', 'height', 'display', 'flexGrow', 'flexShrink', 'flexBasis', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'boxSizing', 'borderRadius', 'fontSize', 'lineHeight', 'borderWidth', 'alignItems', 'justifyContent', 'letterSpacing'];
const COSMETIC_KEYS = ['opacity', 'color', 'backgroundColor', 'cursor'];
const boxOf = (el, keys) => { const cs = win.getComputedStyle(el); const o = {}; keys.forEach((k) => { o[k] = cs[k]; }); return o; };
const sameBox = (a, b) => Object.keys(a).every((k) => a[k] === b[k]);
const dotsText = (btn) => { const s = btn && btn.querySelector('span.ping-dots'); return s ? (s.textContent || '') : null; };
const toastTexts = () => (vm.toasts || []).map((x) => String(x.message || '')).join('\n');
const click = (btn) => btn.dispatchEvent(new win.MouseEvent('click', { bubbles: true, cancelable: true }));
/* 规矩①：先等响应式标记落定，再让 Vue flush，最后才查 DOM */
async function waitBusy(row, want, limit) {
  const t0 = Date.now();
  while (vm.pingIsBusy(row) !== want && Date.now() - t0 < (limit || 5000)) await sleep(30);
  await sleep(90);
  return vm.pingIsBusy(row) === want;
}
async function waitAllIdle(rows, limit) {
  const t0 = Date.now();
  while (rows.some((r) => vm.pingIsBusy(r)) && Date.now() - t0 < (limit || 6000)) await sleep(30);
  await sleep(90);
  return rows.every((r) => !vm.pingIsBusy(r));
}

setStub();
PING.defDelay = 2600;
const row0 = pickedRows[0];
let btn = pingBtnOf(linkRowEls()[0]);
record('R2 空闲态：可点、盒子是 .copy-btn、里面是 #i-ping、无点阵',
  !!btn && !btn.disabled && !!btn.querySelector('use[href="#i-ping"]') && !dotsText(btn),
  { disabled: btn && btn.disabled, cls: btn && btn.className });
const idleSize = boxOf(btn, SIZE_KEYS);
record('R2 空闲计算盒 = 28×28（读不到样式表声明值的话尺寸断言就是空的）',
  idleSize.width === '28px' && idleSize.height === '28px', idleSize);

click(btn);
await waitBusy(row0, true, 1500);
btn = pingBtnOf(linkRowEls()[0]);
const busySize = boxOf(btn, SIZE_KEYS);
const ALL_KEYS = SIZE_KEYS.concat(COSMETIC_KEYS);
const idleAll = boxOf(btn, ALL_KEYS);
const busyAll = boxOf(btn, ALL_KEYS);
const d1 = dotsText(btn);
record('R3 点击后立即不可点（disabled + is-busy）且 svg 让位给点阵',
  btn.disabled === true && /is-busy/.test(btn.className) && !!d1 && !btn.querySelector('use[href="#i-ping"]'),
  { disabled: btn.disabled, cls: btn.className, dots: d1 });
record('R3 点阵首帧只有一个点（. 起步）', d1 === '.', { d: d1 });
record('R3 忙时盒子尺寸与空闲逐项相等（用户最怕的尺寸跳动）',
  sameBox(idleSize, busySize),
  { diff: SIZE_KEYS.filter((k) => idleSize[k] !== busySize[k]).map((k) => k + ':' + idleSize[k] + '→' + busySize[k]) });
/* 真正的"只变外观"证明：在尺寸 + 外观的全表里，忙态与空闲的差异必须**只落在外观四项**，
   且 opacity 确实在差异里（否则说明 is-busy 根本没生效，上面那条"只变外观"就是空话）。 */
record('R3 忙闲全表差异只落在外观四项且 opacity 确实生效（尺寸零跳动的正面证据）',
  (() => {
    const a = boxOf(pingBtnOf(linkRowEls()[0]), ALL_KEYS);
    const diff = ALL_KEYS.filter((k) => a[k] !== idleSize[k] && COSMETIC_KEYS.indexOf(k) < 0);
    return diff.length === 0 && COSMETIC_KEYS.some((k) => k === 'opacity' && a[k] === '0.78');
  })(),
  { sizeDiff: ALL_KEYS.filter((k) => SIZE_KEYS.indexOf(k) >= 0 && boxOf(btn, ALL_KEYS)[k] !== idleSize[k]) });
/* 规矩：jsdom 的 click() 不受 disabled 阻挡，正好用来验程序内兜底守卫 */
vm.detailRowPing(row0);
vm.detailRowPing(row0);
await sleep(80);
record('R4 测试期间重复调用不重发（桩只被调一次）', PING.calls.length === 1, { calls: PING.calls.length });
record('R4 pingIsBusy(row) 对模板用的同一行为 true', vm.pingIsBusy(row0) === true);

/* 规矩②：节奏采样环只读 computed，不碰 DOM */
const samples = [];
const tS = Date.now();
while (Date.now() - tS < 1400) { samples.push({ t: Date.now() - tS, n: String(vm.pingDotsText || '').length }); await sleep(10); }
const seq = samples.map((s) => s.n).filter((n, i, a) => i === 0 || n !== a[i - 1]);
const jumps = [];
for (let i = 1; i < samples.length; i += 1) if (samples[i].n !== samples[i - 1].n) jumps.push(samples[i].t - samples[i - 1].t);
const sorted = jumps.slice().sort((a, b) => a - b);
const median = sorted.length ? sorted[Math.floor(sorted.length / 2)] : -1;
record('R5 点阵严格按 1→2→3→1 循环（每步 = 上一值 % 3 + 1，至少 3 步）',
  seq.length >= 4 && seq.every((n, i) => i === 0 || n === (seq[i - 1] % 3) + 1), { seq: seq.join('') });
/* ⚠️ 节奏**不在这里实测**：隔离实验证明 jsdom 的定时器时钟不可信 ——
   裸 jsdom（无本应用）里 setInterval(380) + 10ms 采样环测出来的步长是 15–17ms，
   1600ms 墙上时间只跑到 101 次采样（每次 sleep(10) 实际 16ms）。
   ⇒ 间隔由上面 S2 的两条静态断言钉住（常量值 + setInterval 引用常量）；观感列入"待真机目测"清单。 */
record('R5 点阵值只在 1–3 之间且持续在转（间隔见静态断言；jsdom 定时器时钟不可用于测节奏）',
  jumps.length >= 3 && seq.every((n) => n >= 1 && n <= 3), { jumps, median, seq: seq.join('') });

record('R6 桩返回后忙态解除', await waitBusy(row0, false, 6000));
btn = pingBtnOf(linkRowEls()[0]);
record('R6 测试完毕恢复原样（可点、无 is-busy、#i-ping 回来、点阵消失）',
  btn.disabled === false && !/is-busy/.test(btn.className) && !!btn.querySelector('use[href="#i-ping"]') && !dotsText(btn),
  { cls: btn.className });
record('R6 恢复后的盒子与最初空闲态逐项相等', sameBox(idleSize, boxOf(btn, SIZE_KEYS)),
  SIZE_KEYS.filter((k) => idleSize[k] !== boxOf(btn, SIZE_KEYS)[k]));

/* 需求①：用"两点法"测时长，对 jsdom 定时器漂移不敏感
 *   3.4s 时仍在（排除 1500/2000 的默认值）+ 4.9s 时已消失（排除 6000） */
async function toastLifespan(matcher) {
  const born = Date.now();
  await sleep(3400);
  const at3400 = matcher(toastTexts());
  await sleep(1500);
  const at4900 = matcher(toastTexts());
  return { born, at3400, at4900 };
}
PING.byUrl[String(pickedRows[0].value)] = { delay: 120, result: OK_RESULT() };
click(pingBtnOf(linkRowEls()[0]));
const okLife = await toastLifespan((s) => /DNS/.test(s) && s.indexOf(String(vm.detail && vm.detail.name)) >= 0);
record('R7 结果提示出现（多行 DNS/TCP + 条目名称）', okLife.at3400 === true || okLife.at4900 === false, okLife);
record('R7 需求①：结果提示 3.4s 仍在、4.9s 已消失（= 停留 4 秒；原来 6s）',
  okLife.at3400 === true && okLife.at4900 === false, okLife);

PING.byUrl[String(pickedRows[0].value)] = { delay: 120, result: { ok: false, error: 'MOCK-ERR' } };
click(pingBtnOf(linkRowEls()[0]));
record('R8 失败分支忙态也解除（finally 覆盖 ping_failed 的提前 return）', await waitBusy(row0, false, 4000));
btn = pingBtnOf(linkRowEls()[0]);
record('R8 失败分支同样恢复原样', btn.disabled === false && !/is-busy/.test(btn.className) && !!btn.querySelector('use[href="#i-ping"]'));
const failLife = await toastLifespan((s) => /MOCK-ERR/.test(s));
record('R8 需求①：失败提示 3.4s 仍在、4.9s 已消失（原来只走默认 2s，比结果还先消失）',
  failLife.at3400 === true && failLife.at4900 === false, failLife);

dropStub();                                   /* 模拟"后端没这个接口" ⇒ tryCall 返回 null ⇒ needApi */
PING.calls.length = 0;
click(pingBtnOf(linkRowEls()[0]));
record('R9 接口不存在（needApi 提前 return）也能解除忙态 —— 这条最容易漏', await waitBusy(row0, false, 4000));
btn = pingBtnOf(linkRowEls()[0]);
record('R9 needApi 分支也恢复原样', btn.disabled === false && !/is-busy/.test(btn.className) && vm.pingIsBusy(row0) === false,
  { cls: btn.className });

if (pickedRows.length >= 2) {
  setStub();
  await waitAllIdle(pickedRows, 4000);
  const vA = String(pickedRows[0].value), vB = String(pickedRows[1].value);
  PING.byUrl[vA] = { delay: 1100, result: OK_RESULT() };
  PING.byUrl[vB] = { delay: 150, result: OK_RESULT() };
  const els = linkRowEls();
  click(pingBtnOf(els[0]));                    /* A 行：慢 */
  await sleep(40);
  click(pingBtnOf(els[1]));                    /* B 行：快 */
  await sleep(300);                            /* B 已结束（150ms），A 仍在测 */
  const btnA = pingBtnOf(linkRowEls()[0]);
  const btnB = pingBtnOf(linkRowEls()[1]);
  /* 300ms 时点：B（150ms）应该已经结束，A（1100ms）必须还在测。
     这一条就是"为什么状态表要按行 key 而不是一个布尔"的证据。 */
  record('R10 快的那行结束不熄灭仍在测的行（按行 key 的状态表）',
    vm.pingIsBusy(pickedRows[0]) === true && vm.pingIsBusy(pickedRows[1]) === false
    && btnA.disabled === true && btnB.disabled === false,
    { a: vm.pingIsBusy(pickedRows[0]), b: vm.pingIsBusy(pickedRows[1]), aDisabled: btnA.disabled, bDisabled: btnB.disabled });
  record('R10 两行都结束后全部恢复', await waitAllIdle(pickedRows, 5000));
  const frozen = String(vm.pingDotsText);
  await sleep(900);
  record('R10 全部结束后计时器停表（点阵计数不再变化 ⇒ 无常驻 tick）', String(vm.pingDotsText) === frozen, { was: frozen, now: String(vm.pingDotsText) });
} else {
  record('R10 并发两行（只找到一条链接行，SKIP）', true, { skip: true });
}

const bad = out.filter((x) => !x.ok).length;
console.log('---- 汇总 ' + (out.length - bad) + '/' + out.length + (bad ? '  失败 ' + bad : '') + ' ----');
if (errs.length) console.log('jsdomError:', errs.slice(0, 3).join(' | '));
process.exit(bad ? 1 : 0);

