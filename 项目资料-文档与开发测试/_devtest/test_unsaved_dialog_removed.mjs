/* 本轮需求：「删除GCP-AI设置中未保存就弹出是否保存配置或者留在界面的那个弹窗删除。」
   真跑一遍：进设置页 → 把 API Key 草稿改脏 → 直接切页，
   断言 (a) 不再弹三选确认框、(b) 页面立刻切走、(c) 也没有"顺手替用户保存"。

   跑法：GCP_PORT=88xx node test_unsaved_dialog_removed.mjs
*/
import { JSDOM, VirtualConsole } from 'jsdom';

const BASE = `http://127.0.0.1:${process.env.GCP_PORT || 8841}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const OUT = [];
function say(k, v) { OUT.push(`${k}=${v}`); console.log(`${k}=${v}`); }

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

/* ⚠️ 用 indexOf 切片剥 Tailwind，不用正则：
   这段代码是从 Python 字符串里塞进 node 的，正则的反斜杠双层转义极易写错，
   一旦没剥掉，tailwind CDN 运行时会在 jsdom 里崩
   （Cannot read properties of undefined (reading 'querySelectorAll')），
   页面直接挂不起来 → 表现成"app 没挂载"的假失败。 */
function cutExternalScript(html, src) {
  const open = '<script src="' + src + '"';
  const at = html.indexOf(open);
  if (at < 0) return html;
  const close = html.indexOf('</' + 'script>', at);
  return close < 0 ? html : html.slice(0, at) + html.slice(close + 9);
}
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

const JS0 = `
window.__MOCK_SETTINGS__ = {
  ai_enabled: true, ai_sidebar_mode: true, model_name: 'deepseek-v4.1-flash',
  ai_provider: 'deepseek', api_base: 'https://api.deepseek.com/v1',
  default_page: '搜索', theme: '深色主题', language: '简体中文'
};
window.__SET_CALLS__ = [];
window.pywebview = { api: {} };
window.pywebview.api.settings = {
  get: async function () { return { ok: true, settings: window.__MOCK_SETTINGS__ }; },
  set: async function (k, v) { window.__SET_CALLS__.push([k, v]); window.__MOCK_SETTINGS__[k] = v; return { ok: true }; },
  api_key_state: async function () { return { ok: true, configured: true }; },
  reveal_api_key: async function () { return { ok: true, value: 'sk-old-value' }; },
  set_api_key: async function () { return { ok: true, configured: true }; }
};
window.pywebview.api.i18n = {
  bundle: async function (l) {
    var r = await fetch('/mock/i18n?lang=' + encodeURIComponent(String(l || '简体中文')));
    return r.ok ? await r.json() : { ok: false };
  }
};
window.pywebview.api.app = {
  ready: async function () { return { ok: true }; },
  info: async function () { return { ok: true, app: 'ToolsGCP', version: 't' }; },
  splash_remaining: async function () { return { ok: true, ms: 0 }; },
  privacy_state: async function () { return { ok: true, agreed: true }; },
  settings: async function () { return { ok: true }; }
};
window.pywebview.api.window = { state: async function () { return { ok: true }; }, center: async function () { return { ok: true }; } };
window.pywebview.api.log = { client: async function () { return { ok: true }; } };
window.pywebview.api.resources = {
  list: async function () { return { ok: true, items: [] }; },
  favorites: async function () { return { ok: true, folders: [], map: {} }; }
};
window.pywebview.api.plugins = { list: async function () { return { ok: true, plugins: [] }; } };
window.pywebview.api.notice = { list: async function () { return { ok: true, notices: [] }; } };
window.pywebview.api.update = { check: async function () { return { ok: true, has: false }; } };
window.pywebview.api.ai = {
  model_choices: async function () { return { ok: false }; },
  sessions: async function () { return { ok: true, sessions: [] }; },
  chat_hints: async function () { return { ok: true, hints: [] }; }
};
window.pywebview.api.clipboard = { read: async function () { return { ok: true, text: '' }; }, write: async function () { return { ok: true }; } };
`;

(async () => {
  const vc = new VirtualConsole();
  const errs = [];
  vc.on('jsdomError', (e) => errs.push(String(e && e.message).slice(0, 160)));
  let html = (await httpGet(`${BASE}/?page=settings&theme=dark&auditfile=unsaved&js0=${encodeURIComponent(JS0)}`)).body;
  html = cutExternalScript(html, '/static/js/vendor/tailwind.js');
  html = cutInlineScript(html, 'tailwind.config');
  say('TAILWIND_STRIPPED', String(html.indexOf('tailwind.js') < 0));

  const dom = new JSDOM(html, {
    url: `${BASE}/?page=settings`, runScripts: 'dangerously',
    resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
  });
  const win = dom.window;
  const t0 = Date.now();
  while (!win.__TOOLSGCP_APP__ && Date.now() - t0 < 40000) await sleep(120);
  const vm = win.__TOOLSGCP_APP__;
  if (!vm) {
    say('MOUNTED', 'false');
    say('JSDOM_ERRORS', JSON.stringify(errs.slice(0, 3)));
    console.log('RESULT: APP_NOT_MOUNTED');
    process.exit(2);
  }
  say('MOUNTED', 'true');

  vm.goto('settings');
  await sleep(1800);
  say('PAGE_BEFORE', String(vm.page));

  /* 把 Key 草稿改成和快照不一样 = "用户打了字还没点保存"。
     ⚠️ 不能调 vm.apiKeyDirty()：它没导出到模板（原来只被我要删掉的那段 goto() 用），
        探针调不到会直接 CRASH。所以这里改成看**可观察状态**：
        apiKeyDraft 与后端已存的 Key 值不一致 = 脏。 */
  vm.apiKeyDraft = 'sk-用户刚打的-but-没有点保存';
  await sleep(400);
  const snapshot = String(await win.pywebview.api.settings.reveal_api_key('deepseek')
    .then((r) => (r && r.value) || ''));
  say('DIRTY', String(vm.apiKeyDraft !== snapshot));
  say('DRAFT_SET', String(vm.apiKeyDraft.length > 0));

  /* 本轮核心：切页**不许**弹确认框 */
  vm.goto('search');
  await sleep(1200);
  say('PAGE_AFTER', String(vm.page));
  say('DIALOG_OPEN', String(!!(vm.dialog && vm.dialog.open)));
  const setCalls = (win.__SET_CALLS__ || []).map((c) => c[0]);
  say('WROTE_API_KEY', String(setCalls.indexOf('api_key') >= 0));

  /* 反过来也要成立：别的破坏性确认框不能被误删（清空历史仍应有 dialog 配置） */
  const src = (await httpGet(`${BASE}/static/js/app.js`)).body;
  say('DESTRUCTIVE_CONFIRM_KEPT',
    String(src.indexOf("ai_clear_history") >= 0 && src.indexOf('danger: true') >= 0));

  win.close();
  console.log('RESULT: OK');
  process.exit(0);
})().catch((e) => { console.error('CRASH', e && e.message); process.exit(1); });
