/* 版本树来回切换 → 必须停在用户当前位置，不能被拉到最底部。
   用户原话：「使用版本树来回切换每次页面都会自动到最底部bug 而不是保留在当前位置」

   旧实现：翻版本走"整会话重建"（下标语义要求），重建完无脑 `nextTick(scrollAiToEnd)`
          → 不管用户在看第几条都拉到底。
   新实现：重建**前**记下被翻那条气泡在视口里的位置（锚点），重建**后**按 delta 挪回去。
          用锚点而不是记 scrollTop：新版本正文长短不同会让文档高度变化，
          固定 scrollTop 会跳到别的消息上。

   ⚠️ jsdom 没有排版引擎（getBoundingClientRect 恒 0、clientHeight 恒 0），
      所以这里自己装一个假布局：气泡高度 = 文本长度×2 + 20，依次纵向排列，
      视口高 300，scrollTop 上限 = 文档高 - 300（和真实浏览器同规则）。

   ⚠️ 断言分两种，不能一刀切"必须精确保持"：
      · 内容变长 → 可滚动范围变大，位置**可以**精确保持 → 断言 ±2px；
      · 内容变短 → 可滚动范围收缩，"原像素位置"物理上做不到（真实浏览器也一样被上限夹住），
        这时正确行为是**夹住且气泡仍在视野内**，而不是甩出视野或跳到别的气泡。

   跑法：GCP_PORT=88xx node test_ai_version_scroll.mjs
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

/* 三个版本正文长短差别很大 → 翻版本会真的改变文档高度，这才测得出"位置"问题 */
const V_TEXT = [
  '短回答。',
  '中等的回答，' + '字'.repeat(120),
  '很长的回答，' + '字'.repeat(400),
];

/* 与 app.js 的 sessionToMessages **同构**（role/text/variants/vIndex…）。
   ⚠️ role 必须是 'assistant'：sessionToMessages 是按 `role==='assistant' → 'ai'` 映射的，
      直接给 'ai' 会被当成用户消息，就没有版本树了（第一版探针就是这么假失败的）。 */
function sessionMessages(vIndex) {
  return [
    { role: 'user', text: '第一条用户消息' },
    { role: 'ai', text: V_TEXT[vIndex], variants: V_TEXT.slice(), vIndex },
    { role: 'user', text: '后面还有一条消息' },
  ];
}
function sessionPayload(vIndex) {
  return {
    id: 'sess-scroll',
    messages: [
      { role: 'user', content: '第一条用户消息' },
      { role: 'assistant', content: V_TEXT[vIndex], variants: V_TEXT.slice(), variant_index: vIndex },
      { role: 'user', content: '后面还有一条消息' },
    ],
  };
}

const JS0 = `
window.__MOCK_SETTINGS__ = {
  ai_enabled: true, ai_sidebar_mode: true, model_name: 'deepseek-v4.1-flash',
  ai_provider: 'deepseek', ai_polish_enabled: true, ai_thinking: 'off',
  default_page: '搜索', theme: '深色主题', language: '简体中文'
};
window.pywebview = { api: {} };
window.pywebview.api.settings = {
  get: async function () { return { ok: true, settings: window.__MOCK_SETTINGS__ }; },
  set: async function (k, v) { window.__MOCK_SETTINGS__[k] = v; return { ok: true }; },
  api_key_state: async function () { return { ok: true, configured: true }; }
};
window.pywebview.api.ai = {
  model_choices: async function () { return { ok: false }; },
  sessions: async function () { return { ok: true, sessions: [] }; },
  session: async function () { return { ok: true, session: window.__SESSION__ }; },
  switch_variant: async function (sid, index, target) {
    var s = JSON.parse(JSON.stringify(window.__SESSION__));
    s.messages[index].variant_index = target;
    s.messages[index].content = s.messages[index].variants[target];
    window.__SESSION__ = s;
    return { ok: true, session_id: sid, session: s };
  },
  send: async function () { return { ok: true, reply: '', session: window.__SESSION__ }; },
  send_stream: async function () { return { ok: false, kind: 'fallback' }; },
  cancel_stream: async function () { return { ok: true }; },
  chat_hints: async function () { return { ok: true, hints: [] }; },
};
window.pywebview.api.i18n = { bundle: async function () { return { ok: true }; } };
window.pywebview.api.app = {
  ready: async function () { return { ok: true }; },
  info: async function () { return { ok: true, app: 'ToolsGCP', version: 'test' }; },
  splash_remaining: async function () { return { ok: true, ms: 0 }; },
  privacy_state: async function () { return { ok: true, agreed: true }; },
  settings: async function () { return { ok: true }; }
};
window.pywebview.api.window = { state: async function () { return { ok: true }; }, center: async function () { return { ok: true }; } };
window.pywebview.api.log = { client: async function () { return { ok: true }; } };
window.pywebview.api.resources = { list: async function () { return { ok: true, items: [] }; }, favorites: async function () { return { ok: true, folders: [], map: {} }; } };
window.pywebview.api.plugins = { list: async function () { return { ok: true, plugins: [] }; } };
window.pywebview.api.notice = { list: async function () { return { ok: true, notices: [] }; } };
window.pywebview.api.update = { check: async function () { return { ok: true, has: false }; } };
window.pywebview.api.clipboard = { read: async function () { return { ok: true, text: '' }; }, write: async function () { return { ok: true }; } };
window.__SESSION__ = ${JSON.stringify(sessionPayload(2))};
`;

const VIEW_H = 300;

/* ---------- 假布局 ---------- */
function installFakeLayout(win, box) {
  let _scrollTop = 0;
  const metrics = () => {
    const bubbles = Array.from(box.querySelectorAll('.bubble[data-i]'));
    const map = new Map();
    let y = 0;
    bubbles.forEach((b) => {
      const h = 20 + String(b.textContent || '').length * 2;
      map.set(b, { top: y, height: h });
      y += h + 16;
    });
    return { map, total: y };
  };
  const maxScroll = () => Math.max(0, metrics().total - VIEW_H);
  Object.defineProperty(box, 'clientHeight', { configurable: true, get: () => VIEW_H });
  Object.defineProperty(box, 'scrollHeight', { configurable: true, get: () => metrics().total });
  Object.defineProperty(box, 'scrollTop', {
    configurable: true,
    get: () => _scrollTop,
    set: (v) => { _scrollTop = Math.max(0, Math.min(Number(v) || 0, maxScroll())); },
  });
  const proto = win.Element.prototype;
  const real = proto.getBoundingClientRect;
  proto.getBoundingClientRect = function () {
    if (this === box) {
      return { x: 0, y: 0, top: 0, left: 0, right: 900, bottom: VIEW_H,
        width: 900, height: VIEW_H, toJSON() {} };
    }
    const m = metrics().map.get(this);
    if (m) {
      const top = m.top - _scrollTop;
      return { x: 0, y: top, top, left: 0, right: 900, bottom: top + m.height,
        width: 900, height: m.height, toJSON() {} };
    }
    return real.call(this);
  };
  return { maxScroll };
}

(async () => {
  const vc = new VirtualConsole();
  vc.on('jsdomError', () => {});
  const html = (await httpGet(`${BASE}/?page=ai&theme=dark&auditfile=vscroll&js0=${encodeURIComponent(JS0)}`)).body;
  const dom = new JSDOM(html, {
    url: `${BASE}/?page=ai`, runScripts: 'dangerously', resources: 'usable',
    pretendToBeVisual: true, virtualConsole: vc,
  });
  const win = dom.window;
  const doc = win.document;
  const t0 = Date.now();
  while (!win.__TOOLSGCP_APP__ && Date.now() - t0 < 40000) await sleep(120);
  if (!win.__TOOLSGCP_APP__) { console.log('FAIL  app 没挂载（环境抖动，重跑）'); process.exit(1); }
  const vm = win.__TOOLSGCP_APP__;

  vm.goto('ai');
  await sleep(1500);
  vm.aiSessionId = 'sess-scroll';
  vm.aiMessages = sessionMessages(2);
  await sleep(1000);

  const box = doc.querySelector('.ai-messages');
  check('拿到 .ai-messages', !!box);
  if (!box) { win.close(); process.exit(1); }
  installFakeLayout(win, box);

  const bubbleAt = (i) => doc.querySelector(`.ai-messages .bubble[data-i="${i}"]`);
  check('三条消息都渲染了', !!bubbleAt(0) && !!bubbleAt(1) && !!bubbleAt(2));
  check('第二条是 AI 消息（role 映射对了）', vm.aiMessages[1].role === 'ai', vm.aiMessages[1].role);
  check('该气泡有 3 个版本可翻', vm.aiVariantCount(vm.aiMessages[1]) === 3,
    String(vm.aiVariantCount(vm.aiMessages[1])));

  const topOf = () => {
    const b = bubbleAt(1);
    return b ? b.getBoundingClientRect().top : NaN;
  };

  /* ===== 场景 1：停在会话开头，短版 → 长版（文档变高，位置可精确保持） ===== */
  await vm.aiSwitchVariant(1, 0);   // 先切到最短那版做基线
  await sleep(900);
  box.scrollTop = 0;
  const base = topOf();
  check('场景1 起点：被翻气泡在视野内', base >= 0 && base < VIEW_H, 'top=' + Math.round(base));

  await vm.aiSwitchVariant(1, 2);   // 短 → 长
  await sleep(1000);
  check('场景1 短翻长：视口位置**精确保持**（±2px，没被拉到底）',
    Math.abs(topOf() - base) <= 2, `${Math.round(base)} → ${Math.round(topOf())}`);
  check('场景1 没有被滚到最底部',
    box.scrollTop < box.scrollHeight - VIEW_H - 1 || box.scrollTop === 0,
    `scrollTop=${box.scrollTop} max=${box.scrollHeight - VIEW_H}`);

  /* ===== 场景 2：停在中间，长版 → 短版（文档变矮，只能夹住，但气泡必须仍在视野内） ===== */
  box.scrollTop = 0;
  await vm.aiSwitchVariant(1, 2);
  await sleep(900);
  box.scrollTop = topOf() - 40;                 // 把被翻气泡放到视野内 40px 处
  const before = topOf();
  check('场景2 起点：气泡在视野内', before >= 0 && before < VIEW_H, 'top=' + Math.round(before));

  await vm.aiSwitchVariant(1, 0);               // 长 → 短
  await sleep(1000);
  const after = topOf();
  check('场景2 长翻短：气泡**仍在视野内**（没被甩出屏幕、也没跳到别的气泡）',
    after >= -24 && after < VIEW_H,
    `${Math.round(before)} → ${Math.round(after)}（scrollTop=${box.scrollTop} max=${box.scrollHeight - VIEW_H}）`);
  check('场景2 要么精确保持、要么是被可滚动上限夹住（不是乱跳）',
    Math.abs(after - before) <= 2 || box.scrollTop >= box.scrollHeight - VIEW_H - 1,
    `top ${Math.round(before)}→${Math.round(after)} scrollTop=${box.scrollTop}/${box.scrollHeight - VIEW_H}`);

  /* ===== 场景 3：连续来回翻三趟都不报错、条数稳定 ===== */
  await vm.aiSwitchVariant(1, 1); await sleep(700);
  await vm.aiSwitchVariant(1, 2); await sleep(700);
  await vm.aiSwitchVariant(1, 0); await sleep(700);
  check('来回翻三趟后仍是 3 条气泡', doc.querySelectorAll('.ai-messages .bubble[data-i]').length === 3);
  check('来回翻三趟后停在第 1 版', vm.aiVariantPage(vm.aiMessages[1]) === 1,
    'page=' + vm.aiVariantPage(vm.aiMessages[1]));

  /* ===== 反向防回归：真正的新提问**应该**继续滚到底（别把这条修坏） ===== */
  const src = await httpGet(`${BASE}/static/js/app.js`).then((r) => r.body);
  const seg = src.slice(src.indexOf('async function aiSwitchVariant'),
    src.indexOf('async function aiSwitchVariant') + 2200);
  check('aiSwitchVariant 里不再有 nextTick(scrollAiToEnd)（拉到底的来源已删）',
    !/nextTick\(scrollAiToEnd\)/.test(seg));
  check('aiSwitchVariant 走的是锚点（capture + restore 成对）',
    /captureAiAnchor\(index\)/.test(seg) && /restoreAiAnchor\(anchor\)/.test(seg));

  win.close();
  const bad = R.filter((x) => !x.ok);
  console.log('='.repeat(64));
  console.log(bad.length ? `FAILED ${bad.length}: ${bad.map((b) => b.name).join(' | ')}` : 'ALL OK');
  process.exit(bad.length ? 1 : 0);
})().catch((e) => { console.error('探针异常：', e); process.exit(1); });
