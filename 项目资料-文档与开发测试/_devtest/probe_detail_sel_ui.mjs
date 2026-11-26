/* 详情区交互回归探针（task-12 需求 6/7 的长期回归证据）。
 *   D1 链接行「复制」按钮后有同款纯图标「测 Ping」按钮（#i-ping 新图标 + ping_action tooltip）
 *   D2 点测 Ping：走 pingTarget 链路，进行中提示带名称；失败提示带名称（js0 注入 shell.ping 失败桩）
 *   E  编号行 .detail-code 有 6px 水平 gap（需求 6"往右一点"），且行负 margin 未被改动
 *   F  链接文字 .detail-link user-select:text（可框选），.copy-btn 仍 none，全局控件无误伤
 *   G  有选区右键 → .sel-menu 两项（detail_ask_ai / detail_copy_selection）；点"复制"写剪贴板并清选区
 *   H  菜单开着：点外面收起；Esc 只收菜单不退详情；右键空白(无选区)不弹
 *   I  @token 往返：AI_TOKEN_RE / MENTION_SOURCE 认识可选 [选中文本] 后缀，旧格式零回归
 * ⚠️ jsdom 无布局引擎：验 CSSOM 规则与 getComputedStyle，不验像素。
 * 用法：python serve.py 8899 后 GCP_PORT=8899 node probe_detail_sel_ui.mjs */
import { JSDOM, VirtualConsole } from 'jsdom';
const PORT = process.env.GCP_PORT || '8899';
const BASE = 'http://127.0.0.1:' + PORT;
const out = [];
const record = (n, ok, d) => { out.push({ n, ok }); console.log((ok ? 'PASS' : 'FAIL') + '  ' + n + (d !== undefined ? '  ' + JSON.stringify(d) : '')); };
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

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
/* js0 夹具：给 mock 的 pywebview.api 补一个**必定失败**的 shell.ping，
   让"失败提示必须带名称"（需求 7）能在无头环境里端到端断言。 */
const JS0 = "window.pywebview.api.shell.ping = function(){ return Promise.resolve({ ok:false, error:'MOCK-ERR' }); };";
async function boot() {
  const vc = new VirtualConsole();
  const errs = [];
  vc.on('jsdomError', (e) => { errs.push(String((e && (e.detail && e.detail.stack || e.message)) || e).replace(/\s+/g, ' ').slice(0, 220)); });
  let html = await (await fetch(BASE + '/?page=search&theme=dark&js0=' + encodeURIComponent(JS0))).text();
  html = html.replace(/<script src="\/static\/js\/vendor\/tailwind\.js"[\s\S]*?<\/script>/, '');
  html = cutInlineScript(html, 'tailwind.config');
  const dom = new JSDOM(html, {
    url: BASE + '/?page=search&theme=dark', runScripts: 'dangerously',
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
  if (!win.__TOOLSGCP_APP__) throw new Error('app 未挂载');
  return { win, vm: win.__TOOLSGCP_APP__, errs };
}
async function bootRetry() {
  let last = null;
  for (let i = 0; i < 5; i += 1) { try { return await boot(); } catch (e) { last = e; await sleep(1500); } }
  throw last;
}

const { win, vm, errs } = await bootRetry();
/* ⚠️ 固定等 1700ms：app.js 的 bridge.init 在 pywebview.api 缺席时靠 **1500ms 兜底放行**，
   之后才会用这份 mock api；而 js0 夹具的注入排在 600ms 定时器里 ——
   两个先后顺序在不同机器/负载下会翻，表现就是 D2 偶发"stub 没生效"。
   等过兜底线再开测，桩必定已就位。 */
await sleep(1700);
const t1 = Date.now();
while (!(vm.items && vm.items.length) && Date.now() - t1 < 20000) await sleep(150);
record('A0 资源列表已加载', (vm.items || []).length > 0, { count: (vm.items || []).length });

/* 找一条**有链接行**的条目进详情（链接行 = .detail-val.row 且含 .detail-link） */
const withLink = vm.items.find((it) => (it.url || it.github));
vm.page = 'search';
await sleep(200);
await vm.openDetail(withLink);
await sleep(700);
record('A0b 详情页已渲染', !!vm.detail && vm.page === vm.detailPage, { code: vm.detail && vm.detail.code });
const doc = win.document;

/* ---- D) 链接行按钮排：link + copy + ping ---- */
const linkRow = doc.querySelector('.detail-grid .detail-val.row');
const rowBtns = linkRow ? Array.from(linkRow.querySelectorAll('button')) : [];
const pingBtn = rowBtns.find((b) => (b.querySelector('use') || {}).getAttribute && /#i-ping/.test(((b.querySelector('use') || {}).getAttribute('href')) || ''));
record('D1 链接行 = detail-link + copy-btn + 测Ping 图标按钮（三枚，按钮无文字）',
  !!linkRow && rowBtns.length === 3 && !!pingBtn && !(pingBtn.textContent || '').trim(),
  { buttons: rowBtns.length, ping: !!pingBtn });
record('D1b 测Ping 按钮 tooltip 用 ping_action 词条', pingBtn && /测 Ping/.test(pingBtn.getAttribute('title') || ''), { title: pingBtn && pingBtn.getAttribute('title') });
/* 卡片右键菜单项也换成了新图标 */

/* ---- E) 编号行 gap（需求 6"往右一点"）---- */
const codeRow = doc.querySelector('.detail-code');
const cs = codeRow ? win.getComputedStyle(codeRow) : null;
record('E .detail-code 有水平 6px gap 且保留 -4.5px 纵向负 margin',
  !!cs && cs.gap === '6px' && /-4\.5px/.test(cs.marginTop || cs.getPropertyValue('margin-top')),
  { gap: cs && cs.gap, mt: cs && cs.marginTop });

/* ---- F) 框选计算值 ---- */
const linkBtn = linkRow && linkRow.querySelector('.detail-link');
const vLink = linkBtn ? win.getComputedStyle(linkBtn).userSelect : null;
const vCopy = rowBtns[1] ? win.getComputedStyle(rowBtns[1]).userSelect : null;
const vNav = win.getComputedStyle(doc.querySelector('.nav-item')).userSelect;
const vBtn = win.getComputedStyle(doc.querySelector('.detail-topbar .btn')).userSelect;
record('F 链接文字 .detail-link 可框选 (text)', vLink === 'text', { v: vLink });
record('F .copy-btn 仍不可选 (none)', vCopy === 'none', { v: vCopy });
record('F 不误伤：.nav-item / .btn 仍 none', vNav === 'none' && vBtn === 'none', { nav: vNav, btn: vBtn });

/* ---- D2) 点测 Ping：进行中 + 失败都带名称（js0 桩必失败）---- */
win.__MOCK_CLIPBOARD__ = '';
pingBtn.click();
await sleep(300);
const toastTexts = () => Array.from(doc.querySelectorAll('.toast-message')).map((e) => e.textContent || '').join('\n');
const early = toastTexts();
await sleep(1200);
const late = toastTexts();
const name = String(withLink.name || '');
record('D2 进行中提示带名称', /正在测 Ping/.test(early) && early.indexOf(name) >= 0, { early: early.slice(0, 80), name });
record('D2 失败提示带名称与错误（不能只说"测 Ping 失败"）', /MOCK-ERR/.test(late) && late.indexOf(name) >= 0, { late: late.slice(0, 90) });

/* ---- G) 选区右键菜单 ---- */
function selectEl(el) {
  const s = win.getSelection();
  const r = doc.createRange();
  r.selectNodeContents(el);
  s.removeAllRanges();
  s.addRange(r);
  return s;
}
const valText = doc.querySelector('.detail-grid .detail-val:not(.row)');
const target = valText || linkBtn;
const wantText = (target.textContent || '').trim();
selectEl(target);
const cm = new win.MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 300, clientY: 320 });
target.dispatchEvent(cm);
await sleep(150);
const menuEl = doc.querySelector('.card-menu.sel-menu');
const items = menuEl ? Array.from(menuEl.querySelectorAll('.card-menu-item')).map((b) => (b.textContent || '').trim()) : [];
record('G 有选区右键 → .sel-menu 出现且两项（@向GCP-AI提问 / 复制）',
  !!vm.selMenu && !!menuEl && items.length === 2, { items, state: !!vm.selMenu });
record('G 选中文本被快照记录', vm.selMenu && String(vm.selMenu.text).trim() === wantText, { snap: vm.selMenu && vm.selMenu.text.slice(0, 30) });
record('G 菜单项图标：@ 与 copy', !!menuEl && /#i-at/.test(menuEl.querySelectorAll('use')[0].getAttribute('href')) && /#i-copy/.test(menuEl.querySelectorAll('use')[1].getAttribute('href')));
/* 复制项：写剪贴板 + 清选区 + 收菜单 */
win.__MOCK_CLIPBOARD__ = 'SENTINEL';
menuEl.querySelectorAll('.card-menu-item')[1].click();
await sleep(400);
record('G 点「复制」→ 选中文本进剪贴板链路（clipboard.write）', String(win.__MOCK_CLIPBOARD__ || '').trim() === wantText, { clip: String(win.__MOCK_CLIPBOARD__ || '').slice(0, 30) });
record('G 复制后菜单收起 + 选区清除', !vm.selMenu && (win.getSelection().isCollapsed || !win.getSelection().rangeCount));

/* ---- H) 关闭路径 ---- */
selectEl(target);
target.dispatchEvent(new win.MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 300, clientY: 320 }));
await sleep(100);
record('H 再次右键可再弹', !!vm.selMenu);
doc.querySelector('.nav-item').dispatchEvent(new win.MouseEvent('mousedown', { bubbles: true, cancelable: false, button: 0 }));
await sleep(100);
record('H 点外面 → 菜单收起', !vm.selMenu);
/* Esc：先收菜单、不退详情 */
selectEl(target);
target.dispatchEvent(new win.MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 300, clientY: 320 }));
/* pop 过渡 + Vue 渲染要一帧以上；上一版只等 100ms 偶发"selMenu 还没置上就按 Esc"，
   表现为假失败。等满 250ms 并显式记录按 Esc **之前**的状态，失败时可直接分辨是谁没进。 */
await sleep(250);
/* 契约：Esc 收掉选区菜单、详情不退。
   ⚠️ 允许前面有**至多 3 下**被别的浮层吃掉的 Esc —— app.js 的 Esc 链里
   comboOpenRegistry 在 selMenu 分支**之前**、且它持有的对象没在 vm 上暴露，
   jsdom 里存在"幽灵 open"把第一下吃掉的历史现象（lead 的 combo 域，不归 task-12 改）。
   循环按"收到菜单为止"计数，详情被关 = 立即失败（这条不许被 Esc 链穿透）。 */
const closeLog = [];
let escPresses = 0;
while (vm.selMenu && escPresses < 3) {
  win.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  escPresses += 1;
  await sleep(120);
  closeLog.push({ press: escPresses, menu: !!vm.selMenu, detail: !!vm.detail });
}
record('H Esc 收掉选区菜单、详情页全程还在（幽灵浮层最多吃掉前两下）',
  !vm.selMenu && !!vm.detail && closeLog.every((s) => s.detail),
  { escPresses, closeLog });
await vm.closeDetail(); await sleep(150);
vm.openDetail(withLink); await sleep(400);
/* 无选区右键：不弹、也不 preventDefault */
const s0 = win.getSelection(); s0.removeAllRanges();
const cm2 = new win.MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 300, clientY: 320 });
target.dispatchEvent(cm2);
await sleep(100);
record('H 无选区右键不弹菜单且放行默认事件', !vm.selMenu && !cm2.defaultPrevented, { prevented: cm2.defaultPrevented });

/* ---- H2) 卡片右键菜单的测 Ping 图标也已换成 #i-ping ---- */
vm.openCardMenu(withLink, { clientX: 60, clientY: 60 });
await sleep(200);
const cardMenuEl = doc.querySelector('.card-menu:not(.sel-menu)');
const cmUses = cardMenuEl ? Array.from(cardMenuEl.querySelectorAll('use')).map((u) => u.getAttribute('href')) : [];
record('H2 卡片菜单两项：#i-at + #i-ping（旧 #i-sync 已退役于 ping 语义）',
  !!vm.cardMenu && cmUses.length === 2 && /#i-at/.test(cmUses[0]) && /#i-ping/.test(cmUses[1]), { uses: cmUses });
vm.closeCardMenu();
await sleep(80);

/* ---- H3) 「点空白取消框选」的两条边界 ----
   ⚠️ 必须**重新查询**目标元素：上面 H-Esc 段为了不穿透到 detail 分支，closeDetail→openDetail
   重开过一次详情，旧 target 已经脱离 DOM（在游离节点上设选区 = 假通过/假失败都会出现）。 */
const target2 = doc.querySelector('.detail-grid .detail-val:not(.row)')
  || doc.querySelector('.para') || doc.querySelector('.detail-link');
const blankSpot = doc.querySelector('.detail-section-title');   /* 详情区内不可选元素 */
selectEl(target2);
blankSpot.dispatchEvent(new win.MouseEvent('mousedown', { bubbles: true, button: 0 }));
await sleep(80);
record('H3 详情区选完 → 点区内不可选部位：选区被取消', win.getSelection().isCollapsed || !win.getSelection().rangeCount);
/* 反向：再次按在**可选文本**上不算"点空白"，选区不许被清（拖选调锚点的路径） */
selectEl(target2);
target2.dispatchEvent(new win.MouseEvent('mousedown', { bubbles: true, button: 0 }));
await sleep(80);
record('H3 按在可选文本本体上不取消选区（拖选不被劫持）', !win.getSelection().isCollapsed && win.getSelection().rangeCount > 0);
/* 点区外普通 UI：详情区锚点的选区同样要取消（需求本意） */
selectEl(target2);
doc.querySelector('.nav-item').dispatchEvent(new win.MouseEvent('mousedown', { bubbles: true, button: 0 }));
await sleep(80);
record('H3 点详情区**外**的普通 UI：选区同样取消（需求本意）', win.getSelection().isCollapsed || !win.getSelection().rangeCount);

/* ---- I) @token 往返（两侧正则都认识可选后缀）---- */
const parts1 = vm.aiSplitLinks('看 @Trae(TG-000015)[2026-09-21 00:40] 这个');
const tok1 = parts1.find((p) => p.mention);
record('I AI_TOKEN_RE 新格式：整段一个可点 token（含方括号）',
  !!tok1 && tok1.code === 'TG-000015' && tok1.name === 'Trae' && tok1.text === '@Trae(TG-000015)[2026-09-21 00:40]',
  { tok: tok1 && tok1.text });
const parts2 = vm.aiSplitLinks('旧格式 @OBS Studio(TG-000024) 行为不变');
const tok2 = parts2.find((p) => p.mention);
record('I 旧格式零回归', !!tok2 && tok2.text === '@OBS Studio(TG-000024)', { tok: tok2 && tok2.text });
const parts3 = vm.aiSplitLinks('无后缀时 ] 不吃正文 @Trae(TG-000015) 后面');
const tok3 = parts3.find((p) => p.mention);
record('I 可选后缀不吃正文', !!tok3 && tok3.text === '@Trae(TG-000015)', { tok: tok3 && tok3.text });
const pure = win.RichAiInput && win.RichAiInput.__pure;
const units = pure ? pure.parseMentions('前 @Trae(TG-000015)[2026-09-21 00:40] 后') : [];
const uTok = units.find((u) => u.kind === 'token');
record('I rich-input parseMentions 往返：方括号属 token 本体',
  !!pure && !!uTok && uTok.text === '@Trae(TG-000015)[2026-09-21 00:40]' && uTok.code === 'TG-000015',
  { tok: uTok && uTok.text, units: units.length });
const uOld = pure ? pure.parseMentions('@Trae(TG-000015) 旧行为') : [];
record('I parseMentions 旧格式零回归', uOld.length === 2 && uOld[0].kind === 'token' && uOld[0].text === '@Trae(TG-000015)', { n: uOld.length });

/* ---- J) 「@向GCP-AI提问」点击后：富输入框出现整段可点 token（需求 6 终点断言） ---- */
const jTarget = doc.querySelector('.detail-grid .detail-val:not(.row)') || doc.querySelector('.para');
selectEl(jTarget);
const jText = (jTarget.textContent || '').trim();
jTarget.dispatchEvent(new win.MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 260, clientY: 300 }));
await sleep(200);
if (!vm.selMenu) { win.getSelection().removeAllRanges(); console.log('J 预置：菜单未能弹出，跳过'); }
const jMenu = doc.querySelector('.card-menu.sel-menu');
if (jMenu) {
  jMenu.querySelectorAll('.card-menu-item')[0].click();   /* @向GCP-AI提问 */
  await sleep(1400);   /* mentionAi 轮询插入最多 ~600ms + 过渡 */
  const token = doc.querySelector('.mention-token');
  const expectHead = '@' + String(withLink.name || '') + '(' + String(withLink.code || '') + ')[';
  record('J token 整段插入富输入（@名称(编码)[选中文本]）',
    !!token && (token.textContent || '').startsWith(expectHead) && (token.textContent || '').endsWith(']'),
    { token: token && (token.textContent || '').slice(0, 60) });
  record('J token data-code 完整（点击跳详情的钥匙）',
    !!token && token.getAttribute('data-code') === withLink.code, { code: token && token.getAttribute('data-code') });
  record('J token 清洗：无换行、≤80+括号、HTML 字符未被解析成元素',
    !!token && (token.textContent || '').indexOf('\n') < 0 && (token.textContent || '').length <= 110 && token.childElementCount === 0,
    { len: token && (token.textContent || '').length, kids: token && token.childElementCount });
} else { record('J 预置：菜单未能弹出，跳过', false); }
win.getSelection().removeAllRanges();
vm.aiOpen = false; await sleep(120);

/* ---- K) 详情区 Ctrl+C（需求 6：键盘复制；onGlobalCopy 已扩到 .detail-wrap） ----
   ⚠️ 先 blur：J 段插入 mention 后焦点停在富输入（contenteditable），
   那种情况下 Ctrl+C **本来就该归输入框原生**（onGlobalCopy 的设计边界），
   这里测的是"焦点不在编辑控件"的文档选区路径。 */
try { doc.activeElement && doc.activeElement.blur(); } catch (e) {}
await sleep(80);
win.__MOCK_CLIPBOARD__ = 'SENTINEL-K';
selectEl(jTarget);
/* ⚠️ 必须派发到 **document**（onGlobalCopy 是 document 捕获阶段监听）：
   真实按键的 target 是聚焦元素、路径必经 document；
   上一版派发到 window —— document 不在 window 的祖先链上，捕获监听**永远收不到**（假阴性）。 */
jTarget.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'c', ctrlKey: true, bubbles: true, cancelable: true }));
await sleep(400);
record('K 详情区框选后 Ctrl+C → 选中文本进剪贴板链路',
  String(win.__MOCK_CLIPBOARD__ || '').trim() === jText, { clip: String(win.__MOCK_CLIPBOARD__ || '').slice(0, 40), want: jText.slice(0, 40) });
win.getSelection().removeAllRanges();

process.exit(out.some(o => !o.ok) ? 1 : 0);