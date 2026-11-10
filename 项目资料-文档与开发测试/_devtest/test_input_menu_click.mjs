/* 实测"右键输入框菜单点了没效果"这条用户抱怨。
   用户原话：「右键输入框的弹出的菜单点击选项无效果」
   本探针真的右键一个输入框，然后**逐项点击**，断言每一项都产生了可观察的变化：
     · 全选 → selectionStart/End 覆盖全文
     · 剪切 → 选区文字从 value 里消失
     · 复制 → 走了 clipboard 通道（打桩记录）
     · 粘贴 → value 里插入剪贴板内容（打桩返回固定文本）
     · 撤销/重做 → contenteditable 走 execCommand；input 走提示（这是浏览器硬限制）
   跑法：GCP_PORT=88xx node test_input_menu_click.mjs
*/
import { JSDOM, VirtualConsole } from 'jsdom';

const BASE = `http://127.0.0.1:${process.env.GCP_PORT || 8841}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const R = [];
function check(name, ok, extra) {
  console.log((ok ? '  OK    ' : '  FAIL  ') + name + (extra ? '  <- ' + extra : ''));
  R.push({ name, ok });
}
function httpGet(url) {
  return import('node:http').then(({ default: http }) => new Promise((res, rej) => {
    http.get(url, (r) => {
      let b = '';
      r.setEncoding('utf8');
      r.on('data', (c) => { b += c; });
      r.on('end', () => res({ status: r.statusCode, body: b }));
    }).on('error', rej);
  }));
}

/* ---------- 桩：pywebview.api（只要 settings / i18n / clipboard） ---------- */
const MOCK = `
window.__CLIP__ = { text: '粘贴进来的内容', writes: [] };
window.__MOCK_SETTINGS__ = {
  ai_enabled: true, ai_sidebar_mode: true, model_name: 'deepseek-v4.1-flash',
  ai_provider: 'deepseek', ai_polish_enabled: true, ai_thinking: 'off',
  default_page: '搜索', theme: '浅色主题', language: '简体中文'
};
window.__SET_CALLS__ = [];
window.pywebview = { api: {} };
window.pywebview.api.settings = {
  get: async function () { return { ok: true, settings: window.__MOCK_SETTINGS__ }; },
  set: async function (k, v) { window.__SET_CALLS__.push([k, v]); window.__MOCK_SETTINGS__[k] = v; return { ok: true }; },
  api_key_state: async function () { return { ok: true, configured: true }; },
  reveal_api_key: async function () { return { ok: true, value: 'sk-test' }; }
};
window.pywebview.api.clipboard = {
  read: async function () { return { ok: true, text: window.__CLIP__.text }; },
  write: async function (t) { window.__CLIP__.writes.push(t); window.__CLIP__.text = t; return { ok: true }; }
};
window.pywebview.api.i18n = { bundle: async function () { return { ok: true }; } };
window.pywebview.api.app = { ready: async function () { return { ok: true }; }, info: async function () { return { ok: true, app: 'ToolsGCP', version: 'test' }; }, splash_remaining: async function () { return { ok: true, ms: 0 }; }, privacy_state: async function () { return { ok: true, agreed: true }; }, settings: async function () { return { ok: true }; } };
window.pywebview.api.window = { state: async function () { return { ok: true }; }, center: async function () { return { ok: true }; }, sync: async function () { return { ok: true }; } };
window.pywebview.api.log = { client: async function () { return { ok: true }; } };
window.pywebview.api.resources = { list: async function () { return { ok: true, items: [] }; }, favorites: async function () { return { ok: true, folders: [], map: {} }; } };
window.pywebview.api.plugins = { list: async function () { return { ok: true, plugins: [] }; } };
window.pywebview.api.notice = { list: async function () { return { ok: true, notices: [] }; } };
window.pywebview.api.update = { check: async function () { return { ok: true, has: false }; } };
`;

async function boot() {
  const vc = new VirtualConsole();
  vc.on('jsdomError', () => {});
  const html = (await httpGet(`${BASE}/?page=settings&theme=light&auditfile=inputmenu&js0=${encodeURIComponent(MOCK)}`)).body;
  const dom = new JSDOM(html, {
    url: `${BASE}/?page=settings`, runScripts: 'dangerously', resources: 'usable',
    pretendToBeVisual: true, virtualConsole: vc,
  });
  const win = dom.window;
  const t0 = Date.now();
  while (!win.__TOOLSGCP_APP__ && Date.now() - t0 < 40000) await sleep(120);
  if (!win.__TOOLSGCP_APP__) throw new Error('app 没挂载');
  await sleep(1600);
  return { win, doc: win.document, vm: win.__TOOLSGCP_APP__ };
}

(async () => {
  const { win, doc, vm } = await boot();
  /* ⚠️ 必须先切到设置页：mock 的 default_page 是「搜索」，
     设置页整段是 v-if，不 goto 的话页面上根本没有设置输入框（上一版就是这么假失败的）。
     选框用 .settings-search input —— 它在设置页**恒存在**（不依赖当前板块有没有 text 行）。 */
  vm.goto('settings');
  await sleep(1600);
  const menu = doc.getElementById('input-menu');
  check('#input-menu 存在', !!menu);
  if (!menu) { win.close(); process.exit(1); }

  /* 找一个设置页里可编辑的 text 输入框 */
  const input = doc.querySelector('.settings-search input')
    || doc.querySelector('.settings-main input.input:not([readonly])');
  check('设置页有可编辑文本输入框', !!input);
  if (!input) { win.close(); process.exit(1); }

  const setVal = (el, v) => {
    const setter = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value').set;
    setter.call(el, v);
    el.dispatchEvent(new win.Event('input', { bubbles: true }));
  };
  const openMenuAt = async (x = 200, y = 200) => {
    input.dispatchEvent(new win.MouseEvent('contextmenu', {
      bubbles: true, cancelable: true, clientX: x, clientY: y }));
    await sleep(260);
    return !menu.hidden;
  };
  const clickItem = async (cmd) => {
    const btn = menu.querySelector(`.input-menu-item[data-cmd="${cmd}"]`);
    if (!btn) return { missing: true };
    const disabled = btn.disabled || btn.classList.contains('is-disabled');
    btn.dispatchEvent(new win.MouseEvent('mousedown', { bubbles: true, cancelable: true }));
    btn.dispatchEvent(new win.MouseEvent('mouseup', { bubbles: true, cancelable: true }));
    btn.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
    await sleep(260);
    return { disabled, btn };
  };

  /* ① 全选：点完 value 应被整体选中 */
  setVal(input, '安排一下这个文本框');
  const okOpen = await openMenuAt();
  check('右键能打开菜单', okOpen);
  let r = await clickItem('select-all');
  check('"全选"项没有被误禁用', !r.disabled, JSON.stringify(r.disabled));
  check('点"全选"后选中了全文（点了真有反应）',
    input.selectionStart === 0 && input.selectionEnd === '安排一下这个文本框'.length,
    `sel=${input.selectionStart}-${input.selectionEnd}`);

  /* ② 剪切：选区文字应从 value 消失 */
  setVal(input, 'abcdef');
  input.setSelectionRange(0, 3);
  await openMenuAt();
  r = await clickItem('cut');
  check('"剪切"没被误禁用', !r.disabled);
  check('点"剪切"后选区被删掉（点了真有反应）', input.value === 'def', JSON.stringify(input.value));

  /* ③ 复制：应走 clipboard.write */
  win.__CLIP__.writes.length = 0;
  setVal(input, 'copy-me');
  input.setSelectionRange(0, 7);
  await openMenuAt();
  r = await clickItem('copy');
  check('"复制"没被误禁用', !r.disabled);
  check('点"复制"真的把选中文字写进剪贴板',
    win.__CLIP__.writes.length > 0 && win.__CLIP__.writes[win.__CLIP__.writes.length - 1] === 'copy-me',
    JSON.stringify(win.__CLIP__.writes));

  /* ④ 粘贴：值里应插入剪贴板内容 */
  win.__CLIP__.text = 'PASTED';
  setVal(input, 'X');
  input.setSelectionRange(1, 1);
  await openMenuAt();
  r = await clickItem('paste');
  check('"粘贴"没被误禁用', !r.disabled);
  check('点"粘贴"后内容真的插进输入框（点了真有反应）',
    input.value === 'XPASTED', JSON.stringify(input.value));

  /* ⑤ 撤销/重做：input 上是浏览器硬限制 → 必须给明确提示，不能"静默无反应" */
  const toastsBefore = (doc.querySelectorAll('.toast').length);
  setVal(input, 'undo-test');
  await openMenuAt();
  r = await clickItem('undo');
  await sleep(300);
  const toastsAfter = doc.querySelectorAll('.toast').length;
  check('点"撤销"不是静默无反应（要么生效、要么给出明确提示）',
    toastsAfter > toastsBefore || doc.body.textContent.includes('Ctrl+Z'),
    `toast ${toastsBefore}→${toastsAfter}`);

  /* ⑥ 菜单关掉了（点完就收） */
  check('点完菜单自动收起', menu.hidden);

  win.close();
  const bad = R.filter((x) => !x.ok);
  console.log('='.repeat(60));
  console.log(bad.length ? `FAILED ${bad.length}: ${bad.map((b) => b.name).join(' | ')}` : 'ALL OK');
  process.exit(bad.length ? 1 : 0);
})().catch((e) => { console.error('探针异常：', e); process.exit(1); });
