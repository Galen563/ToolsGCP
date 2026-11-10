/* 诊断：jsdom 里这条 XHR 取语言包到底通不通（不通则整个英文扫描探针作废，
   通则说明是 app.js 那边的加载时机问题，不是探针问题）。
   跑法：GCP_PORT=88xx node diag_xhr_i18n.mjs
*/
import { JSDOM, VirtualConsole } from 'jsdom';
const BASE = `http://127.0.0.1:${process.env.GCP_PORT || 8841}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const MOCK = `
window.__MOCK_SETTINGS__ = { default_page: '搜索', theme: '深色主题', language: 'English',
  ai_enabled: true, ai_sidebar_mode: true, ai_polish_enabled: true,
  model_name: 'deepseek-v4.1-flash', ai_provider: 'deepseek', ai_thinking: 'off' };
window.pywebview = { api: {} };
window.pywebview.api.settings = {
  get: async function () { return { ok: true, settings: window.__MOCK_SETTINGS__ }; },
  set: async function (k, v) { window.__MOCK_SETTINGS__[k] = v; return { ok: true }; }
};
window.pywebview.api.i18n = {
  bundle: function (lang) {
    return new Promise(function (res) {
      var x = new XMLHttpRequest();
      x.open('GET', '/mock/i18n?lang=' + encodeURIComponent(String(lang || 'English')));
      x.onload = function () {
        window.__XHR_LOG__ = ['status=' + x.status, 'len=' + (x.responseText || '').length];
        try { res(JSON.parse(x.responseText)); }
        catch (e) { window.__XHR_LOG__.push('parse_fail ' + String(e).slice(0, 120)); res({ ok: false }); }
      };
      x.onerror = function () { window.__XHR_LOG__ = ['xhr onerror']; res({ ok: false, error: 'xhr' }); };
      x.ontimeout = function () { window.__XHR_LOG__ = ['xhr timeout']; res({ ok: false }); };
      try { x.send(); } catch (e) { window.__XHR_LOG__ = ['send_threw ' + String(e).slice(0, 120)]; res({ ok: false }); }
    });
  },
  language: async function () { return { ok: true, language: 'English' }; },
  text: async function () { return { ok: false }; }
};
window.pywebview.api.app = {
  ready: async function () { return { ok: true }; },
  info: async function () { return { ok: true, app: 'ToolsGCP', version: 't' }; },
  splash_remaining: async function () { return { ok: true, ms: 0 }; },
  privacy_state: async function () { return { ok: true, agreed: true }; },
  settings: async function () { return { ok: true }; }
};
window.pywebview.api.window = { state: async function () { return { ok: true }; } };
window.pywebview.api.log = { client: async function () { return { ok: true }; } };
window.pywebview.api.resources = { list: async function () { return { ok: true, items: [] }; }, favorites: async function () { return { ok: true, folders: [], map: {} }; } };
window.pywebview.api.plugins = { list: async function () { return { ok: true, plugins: [] }; } };
window.pywebview.api.notice = { list: async function () { return { ok: true, notices: [] }; } };
window.pywebview.api.update = { check: async function () { return { ok: true, has: false }; } };
window.pywebview.api.ai = { model_choices: async function () { return { ok: false }; }, sessions: async function () { return { ok: true, sessions: [] }; }, chat_hints: async function () { return { ok: true, hints: [] }; } };
window.pywebview.api.clipboard = { read: async function () { return { ok: true, text: '' }; }, write: async function () { return { ok: true }; } };
`;

function httpGet(url) {
  return import('node:http').then(({ default: http }) => new Promise((res, rej) => {
    http.get(url, (r) => { let b = ''; r.setEncoding('utf8');
      r.on('data', (c) => { b += c; }); r.on('end', () => res(b)); }).on('error', rej);
  }));
}
/* Tailwind CDN 运行时在 jsdom 里会崩（没有布局引擎），必须先剥掉 ——
   用 indexOf 切片，不用正则（正则从 Python 里写容易把反斜杠搞错）。 */
function cutExternalScript(html, src) {
  const open = '<script src="' + src + '"';
  const at = html.indexOf(open);
  if (at < 0) return html;
  const close = html.indexOf('</' + 'script>', at);
  return close < 0 ? html : html.slice(0, at) + html.slice(close + 9);
}
function cutInlineScript(html, marker) {
  let at = html.indexOf(marker), guard = 0;
  while (at >= 0 && guard++ < 10) {
    const open = html.lastIndexOf('<script', at);
    const close = html.indexOf('</' + 'script>', at);
    if (open < 0 || close < 0) break;
    html = html.slice(0, open) + html.slice(close + 9);
    at = html.indexOf(marker);
  }
  return html;
}

let html = await httpGet(`${BASE}/?page=search&auditfile=diag&js0=${encodeURIComponent(MOCK)}`);
html = cutExternalScript(html, '/static/js/vendor/tailwind.js');
html = cutInlineScript(html, 'tailwind.config');
console.log('tailwind 已剥:', html.indexOf('tailwind.js') < 0);

const vc = new VirtualConsole();
const errs = [];
vc.on('jsdomError', (e) => errs.push(String(e && e.message).slice(0, 140)));
const dom = new JSDOM(html, { url: `${BASE}/?page=search`, runScripts: 'dangerously',
  resources: 'usable', pretendToBeVisual: true, virtualConsole: vc });
const win = dom.window;

const t0 = Date.now();
while (!win.__TOOLSGCP_APP__ && Date.now() - t0 < 40000) await sleep(120);
console.log('mounted:', !!win.__TOOLSGCP_APP__, '耗时', Date.now() - t0, 'ms');

/* ① 直接调 api：证明 XHR 本身通不通 */
const bundle = await win.pywebview.api.i18n.bundle('English');
console.log('① 直接调 bundle: ok =', bundle && bundle.ok,
  'modules =', bundle && bundle.modules ? Object.keys(bundle.modules).length : 'N/A',
  'XHR_LOG =', JSON.stringify(win.__XHR_LOG__ || []));

/* ② 走 app 的 t()：证明 app 有没有把它灌进 I18N.map */
const vm = win.__TOOLSGCP_APP__;
if (vm) {
  for (const wait of [500, 1500, 3000, 6000]) {
    await sleep(wait);
    console.log(`② t('search') 在累计等待后 =`, JSON.stringify(String(vm.t('search', '__FB__'))));
  }
  console.log('② jsdom 错误:', JSON.stringify(errs.slice(0, 3)));
}
win.close();
