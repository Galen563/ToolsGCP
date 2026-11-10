/* 英文/繁体界面里的简体中文残留扫描。
   用户原话：「语言切换为其他语言部分地方还是只有简体中文文本内容，包括各种地方」

   ⚠️ 为什么不能只 grep 源码：
      · 语言包键集合一致 ≠ 界面没有中文（值本身可能写的是中文，或者代码里硬编码绕过了 t()）；
      · 源码里中文也可能是**数据结构取值**（分类名 / 系统名），那些本来就不该翻。
      所以判据必须是**渲染出来的可见文本**——用户在屏幕上看到什么就扫什么。

   做法：切到 English 启动，逐个页面走一遍，收集可见文本节点，
        正则扫 [\u4e00-\u9fff]（汉字），按"是否来自资源库数据"排除后报告。

   跑法：GCP_PORT=88xx I18N_LANG=English node test_i18n_english_leak.mjs
*/
import { JSDOM, VirtualConsole } from 'jsdom';

const BASE = `http://127.0.0.1:${process.env.GCP_PORT || 8841}`;
const LANG = process.env.I18N_LANG || 'English';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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

/* 带几条**真实资源**，这样"资源库数据本身是中文"能被识别并排除 */
const ITEMS = [
  { code: 'TG-000001', name: 'LocalSend', category: '工具', tags: ['传输'],
    description: '开源局域网传输', systems: ['Windows'], url: 'https://localsend.org' },
  { code: 'TG-000024', name: 'OBS', category: '直播', tags: ['录屏'],
    description: '录屏与直播', systems: ['Windows'], url: 'https://obsproject.com' },
];

const JS0 = `
window.__MOCK_SETTINGS__ = {
  ai_enabled: true, ai_sidebar_mode: true, model_name: 'deepseek-v4.1-flash',
  ai_provider: 'deepseek', ai_polish_enabled: true, ai_thinking: 'off',
  default_page: '搜索', theme: '深色主题', language: '${LANG}',
  search_show_github: true, ui_animation: true, notify_enabled: false
};
window.pywebview = { api: {} };
window.pywebview.api.settings = {
  get: async function () { return { ok: true, settings: window.__MOCK_SETTINGS__ }; },
  set: async function (k, v) { window.__MOCK_SETTINGS__[k] = v; return { ok: true }; },
  api_key_state: async function () { return { ok: true, configured: true }; }
};
window.pywebview.api.resources = {
  list: async function () { return { ok: true, items: ${JSON.stringify(ITEMS)}, total: ${ITEMS.length} }; },
  favorites: async function () { return { ok: true, folders: [{ id: 'f1', label: '默认', count: 1 }], map: { 'TG-000001': ['f1'] } }; },
  categories: async function () { return { ok: true, categories: ['工具', '直播'] }; },
  filters: async function () { return { ok: true, tags: ['传输'], systems: ['Windows'] }; }
};
window.pywebview.api.i18n = {
  /* ⚠️⚠️ 关键修正：jsdom 的 window **没有 fetch**，而这里原来用
     fetch('/mock/i18n') → 取语言包必然失败 → I18N.map 是空的 →
     页面上每一个 t() 都退回代码里的中文兜底 → 上一版扫出「282 处简体中文残留」
     **全是探针自己的假阳性**，不是产品 bug（语言包三语键集合审计是 0 缺口）。
     解法照搬已跑通的 settings_probe：用 jsdom 支持的 XMLHttpRequest 取语言包。
     （也不能把整包 JSON 塞进 js0——会超 http.server 请求行上限，直接 414。） */
  bundle: function (l) {
    var lang = String(l || '${LANG}');
    return new Promise(function (res) {
      var x = new XMLHttpRequest();
      x.open('GET', '/mock/i18n?lang=' + encodeURIComponent(lang));
      x.onload = function () { try { res(JSON.parse(x.responseText)); } catch (e) { res({ ok: false, error: String(e) }); } };
      x.onerror = function () { res({ ok: false, error: 'xhr' }); };
      x.send();
    });
  },
  language: async function () { return { ok: true, language: '${LANG}' }; },
  text: async function () { return { ok: false }; }
};
window.pywebview.api.app = {
  ready: async function () { return { ok: true }; },
  info: async function () { return { ok: true, app: 'ToolsGCP', version: 'test' }; },
  splash_remaining: async function () { return { ok: true, ms: 0 }; },
  privacy_state: async function () { return { ok: true, agreed: true }; },
  settings: async function () { return { ok: true }; }
};
window.pywebview.api.window = { state: async function () { return { ok: true }; }, center: async function () { return { ok: true }; } };
window.pywebview.api.log = { client: async function () { return { ok: true }; }, files: async function () { return { ok: true, files: [] }; } };
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

const CJK = /[\u4e00-\u9fff]/;
/* 资源库数据本身（名称/分类/标签/简介）不是 UI 文案，出现中文是**正常**的 */
const DATA_WORDS = new Set(['工具', '直播', '传输', '录屏', 'LocalSend', 'OBS',
  '开源局域网传输', '录屏与直播']);

function visibleTexts(doc) {
  const out = [];
  const walk = (node) => {
    if (node.nodeType === 3) {           // 文本节点
      const t = String(node.nodeValue || '').trim();
      if (t && CJK.test(t)) out.push(t);
      return;
    }
    if (node.nodeType !== 1) return;
    const el = node;
    if (el.tagName === 'SCRIPT' || el.tagName === 'STYLE' || el.tagName === 'NOSCRIPT') return;
    if (el.hidden || (el.style && el.style.display === 'none')) return;
    for (const kid of el.childNodes) walk(kid);
  };
  walk(doc.body);
  /* 控件上的可见文案：placeholder / title / aria-label（页面上看不见但工具提示是用户读的） */
  doc.querySelectorAll('[placeholder],[title],[aria-label]').forEach((el) => {
    ['placeholder', 'title', 'aria-label'].forEach((a) => {
      const v = el.getAttribute(a);
      if (v && CJK.test(v)) out.push('@' + a + '=' + v);
    });
  });
  return out;
}

/* ---------- HTML 切片小工具（只用 indexOf，避免正则转义踩坑） ---------- */
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

(async () => {
  const pages = ['search', 'customize', 'favorites', 'detail', 'deploy', 'plugin',
    'maker', 'log', 'notice', 'feedback', 'settings', 'ai', 'github'];
  const results = [];
  for (const page of pages) {
    const vc = new VirtualConsole();
    const errs = [];
    vc.on('jsdomError', (e) => errs.push(String(e && e.message).slice(0, 140)));
    let html = (await httpGet(`${BASE}/?page=${encodeURIComponent(page)}&theme=dark&auditfile=i18n_${page}&js0=${encodeURIComponent(JS0)}`)).body;
    /* Tailwind CDN 运行时在 jsdom 里会崩（MutationObserver + 没有布局引擎），
       和另外两个探针同一处理：剥掉外链与内联配置。它只影响排版，
       本探针只看**文本内容**，剥了不影响结论。 */
    html = cutExternalScript(html, '/static/js/vendor/tailwind.js');
    html = cutInlineScript(html, 'tailwind.config');
    /* ⚠️ 高负载下 jsdom 异步抓 <script>/<link> 会抖（maker 那次报
       "Could not load link …/ai-fixes.css" → app 根本没挂载）。
       挂载失败必须**整页重开**再判，否则会把环境抖动当成"这一页有中文残留"报上去
       —— 上一版就是这么误报的。 */
    let win = null;
    let mounted = false;
    for (let attempt = 0; attempt < 4 && !mounted; attempt += 1) {
      const dom = new JSDOM(html, {
        url: `${BASE}/?page=${encodeURIComponent(page)}`,
        runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
      });
      win = dom.window;
      const t0 = Date.now();
      while (!win.__TOOLSGCP_APP__ && Date.now() - t0 < 40000) await sleep(120);
      mounted = !!win.__TOOLSGCP_APP__;
      if (!mounted) { try { win.close(); } catch (e) {} await sleep(600); }
    }
    if (!mounted) { results.push([page, ['app 没挂载（重试 4 次仍失败 = 环境抖动，非产品问题）']]); continue; }
    const vm = win.__TOOLSGCP_APP__;
    /* 自证：t() 出来的到底是不是英文。若仍是兜底中文，说明语言包没加载，
       本轮扫描结果全部作废（上一版就是这种情况）。 */
    if (page === pages[0]) {
      /* 直接调一次 bundle：区分"XHR 不通"和"app 没把它灌进 I18N.map"两种失败，
         上一版只报"没加载"，害得我以为语言包真有问题。 */
      const raw = await win.pywebview.api.i18n.bundle(LANG);
      console.log('bundle 直调: ok =', raw && raw.ok,
        'modules =', raw && raw.modules ? Object.keys(raw.modules).length : 'N/A');
      console.log('jsdom 错误 =', JSON.stringify(errs.slice(0, 2)));
      /* ⚠️ 语言包是**挂载之后**异步加载的（boot 里才调 i18n.bundle），
         挂载那一瞬间 t() 必然还是兜底值 → 直接判"没加载"是竞态误判。
         轮询最多 12 秒再下结论。 */
      let probe = '__NO_BUNDLE__';
      for (let i = 0; i < 60; i += 1) {
        probe = String(vm.t('search', '__NO_BUNDLE__'));
        if (probe !== '__NO_BUNDLE__') break;
        await sleep(200);
      }
      const loaded = probe !== '__NO_BUNDLE__';
      console.log('语言包自检 t(search) =', JSON.stringify(probe), loaded ? '（已加载）' : '（**没加载 → 本轮结果全是假阳性，作废**）');
      if (!loaded) { console.log('ABORT: bundle not loaded'); win.close(); process.exit(3); }
    }
    try { vm.goto(page); } catch (e) { /* 有些页要参数，跳过即可 */ }
    await sleep(900);
    const texts = visibleTexts(win.document);
    const uniq = [...new Set(texts)].filter((t) => !DATA_WORDS.has(t.replace(/^@\w+=/, '')));
    results.push([page, uniq]);
    win.close();
    await sleep(120);
  }

  console.log(`语言 = ${LANG} —— 界面可见文本里的简体中文残留\n`);
  let total = 0;
  for (const [page, list] of results) {
    if (!list.length) { console.log(`  （干净）${page}`); continue; }
    console.log(`  ${page}: ${list.length} 处`);
    list.slice(0, 14).forEach((t) => console.log('      ·', t.slice(0, 90)));
    if (list.length > 14) console.log(`      …还有 ${list.length - 14} 处`);
    total += list.length;
  }
  console.log('='.repeat(64));
  console.log(total === 0 ? 'ALL OK（无中文残留）' : `共 ${total} 处残留`);
  process.exit(0);   /* 这是排查报表，不当作硬失败 */
})().catch((e) => { console.error('探针异常：', e); process.exit(1); });
