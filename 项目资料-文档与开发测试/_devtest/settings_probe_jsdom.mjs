/* jsdom 探针（task-4 验证 · 沙箱降级方案）。
 * 背景：本机沙箱禁命名管道，Chromium（Edge/Chrome）多进程起不来（regression.py 头部
 * 注释也写了"需要一台没有被沙箱限制的 Windows"）。这里用 jsdom 加载 serve.py 的
 * mock 页面，跑同一套逻辑断言（状态机 / 搜索 / Combo place / 右键菜单）。
 * 布局相关 API（getBoundingClientRect / offsetTop / clientHeight / scrollHeight /
 * scrollTo）jsdom 没有真实布局引擎，统一打桩成"虚拟布局"，验证的是**代码路径**，
 * 不是像素。像素级验证需要在不受限机器上跑 settings_probe.py（Edge 版）。
 * 用法：先起 serve.py（node 会自己 spawn），再 node settings_probe_jsdom.mjs
 */
import { JSDOM, VirtualConsole } from 'jsdom';

const SERVE_PORT = process.env.GCP_PORT || '8899';
const BASE = `http://127.0.0.1:${SERVE_PORT}`;

/* ---------- 虚拟布局参数（与断言一一对应） ---------- */
const VH = 900; const VW = 1440;
const MAIN_CLIENT_H = 700;
const MAIN_SCROLL_H = 6000;
const SECTION_TOP = {
  appearance: 0, animation: 600, startup: 1100, search: 1500, hotkey: 1900,
  download: 2400, notification: 3000, behavior: 3400, storage: 3800,
  ai: 4200, dev: 5200, about: 5600,
};

const results = [];
function record(name, ok, detail) {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  ' + JSON.stringify(detail) : ''}`);
}

async function bootPage(query = '') {
  const vc = new VirtualConsole();
  vc.on('jsdomError', () => {}); /* 屏蔽 CSS 解析等噪音 */
  let html = await (await fetch(`${BASE}/?page=settings&auditfile=jsdom_probe${query}`)).text();
  /* Tailwind CDN 运行时在 jsdom 里会因布局 API 缺失崩溃（与逻辑断言无关），剥掉 */
  html = html.replace(/<script src="\/static\/js\/vendor\/tailwind\.js"[\s\S]*?<\/script>/, '')
             .replace(/<script>[\s\S]*?tailwind\.config[\s\S]*?<\/script>/, '');
  const dom = new JSDOM(html, {
    url: `${BASE}/?page=settings&auditfile=jsdom_probe${query}`,
    runScripts: 'dangerously',
    resources: 'usable',
    pretendToBeVisual: true,
    virtualConsole: vc,
  });
  const win = dom.window;
  /* ---------- 打桩：布局 + 滚动 ---------- */
  Object.defineProperty(win, 'innerHeight', { value: VH, configurable: true });
  Object.defineProperty(win, 'innerWidth', { value: VW, configurable: true });
  const elProto = win.HTMLElement.prototype;
  win.Element.prototype.getBoundingClientRect = function () {
    if (this.__rect) return this.__rect();
    return { x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, toJSON() {} };
  };
  Object.defineProperty(elProto, 'offsetTop', {
    configurable: true,
    get() {
      if (this.__offsetTop != null) return this.__offsetTop;
      const host = this.closest ? this.closest('.settings-main') : null;
      if (host && this.classList && this.classList.contains('settings-section')) {
        return SECTION_TOP[this.getAttribute('data-key')] ?? 0;
      }
      return 0;
    },
  });
  Object.defineProperty(elProto, 'clientHeight', { configurable: true,
    get() { return this.classList && this.classList.contains('settings-main') ? MAIN_CLIENT_H : 0; } });
  Object.defineProperty(elProto, 'scrollHeight', { configurable: true,
    get() { return this.classList && this.classList.contains('settings-main') ? MAIN_SCROLL_H : 0; } });
  Object.defineProperty(elProto, 'offsetWidth', { configurable: true,
    get() { return this.__offsetWidth ?? 0; } });
  Object.defineProperty(elProto, 'offsetHeight', { configurable: true,
    get() { return this.__offsetHeight ?? 0; } });
  Object.defineProperty(elProto, 'clientWidth', { configurable: true,
    get() { return this.__clientWidth ?? (this.__offsetWidth ?? 0); } });
  /* scrollTo：记录目标并派发 scroll（smooth 用分帧中间位置模拟，专门喂状态机的坑） */
  win.Element.prototype.scrollTo = function (opts) {
    const top = typeof opts === 'object' && opts !== null ? Number(opts.top) : Number(opts);
    const el = this;
    const from = el.scrollTop || 0;
    const smooth = typeof opts === 'object' && opts && opts.behavior === 'smooth';
    el.scrollTop = Math.max(0, top);
    if (smooth && Math.abs(el.scrollTop - from) > 120) {
      /* 中间帧：真实浏览器平滑滚动会连续派发多个 scroll，位置在途中 */
      const mid = Math.round((from + el.scrollTop) / 2);
      el.scrollTop = mid;
      el.dispatchEvent(new win.Event('scroll'));
      el.scrollTop = Math.max(0, top);
    }
    el.dispatchEvent(new win.Event('scroll'));
  };
  /* jsdom 默认 scrollTop 可写（无布局），保险起见显式实现 */
  let stKey = Symbol('scrollTop');
  Object.defineProperty(elProto, 'scrollTop', {
    configurable: true,
    get() { return this[stKey] || 0; },
    set(v) { this[stKey] = Number(v) || 0; },
  });
  /* 菜单量尺寸打桩：#input-menu 有固定宽高，才能验证"不超窗"夹取 */
  const menu = win.document.getElementById('input-menu');
  if (menu) { menu.__offsetWidth = 172; menu.__offsetHeight = 230; }
  /* 等 app 挂载（app.js mount 后挂 window.__TOOLSGCP_APP__），再等设置页侧栏渲染出来 */
  const t0 = Date.now();
  while (!win.__TOOLSGCP_APP__ && Date.now() - t0 < 25000) {
    await new Promise((r) => setTimeout(r, 100));
  }
  if (!win.__TOOLSGCP_APP__) {
    /* 队友并发写 app.js 时 serve.py 可能吐回半截文件（语法错误 → 不挂载）。
       抛特殊标记让调用方重试。 */
    const err = new Error('app 未挂载（可能是读到半截 app.js）');
    err.retryable = true;
    try { win.close(); } catch (e) {}
    throw err;
  }
  const t1 = Date.now();
  while (!win.document.querySelector('.settings-side .list-item.plain') && Date.now() - t1 < 20000) {
    await new Promise((r) => setTimeout(r, 100));
  }
  if (!win.document.querySelector('.settings-side .list-item.plain')) {
    throw new Error('设置页侧栏没渲染（page=' + (win.__TOOLSGCP_APP__ && win.__TOOLSGCP_APP__.page) + '）');
  }
  return { dom, win, doc: win.document };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* 队友并发写 app.js 时可能读到半截文件 → 挂载失败重试几次 */
async function bootPageRetry(query = '') {
  let lastErr = null;
  for (let i = 0; i < 4; i += 1) {
    try { return await bootPage(query); }
    catch (e) {
      lastErr = e;
      if (!e.retryable) throw e;
      await sleep(1500);
    }
  }
  throw lastErr;
}

function sideButtons(doc) {
  return Array.from(doc.querySelectorAll('.settings-side .list-item.plain'));
}
function sideText(btn) { return (btn.textContent || '').trim(); }
function onSide(doc) {
  const on = doc.querySelector('.settings-side .list-item.plain.is-on');
  return on ? sideText(on) : null;
}
function findSide(doc, label) {
  return sideButtons(doc).find((b) => sideText(b) === label) || null;
}

/* ================= 用例 A：左栏状态机 ================= */
async function testSpy() {
  const { win, doc } = await bootPageRetry();
  const host = doc.querySelector('.settings-main');
  const fails = [];
  const order = ['外观', '快捷键', '存储', 'GCP-AI', '开发者功能', '关于', '外观', 'GCP-AI'];
  for (const label of order) {
    const btn = findSide(doc, label);
    if (!btn) { fails.push('找不到板块按钮：' + label); break; }
    btn.click();
    await sleep(40); /* 等 Vue flush：is-on 类是异步写的 */
    /* 程序化滚动途中（中间帧已派发 scroll）：选中必须仍是点击项 */
    if (onSide(doc) !== label) fails.push(`「${label}」滚动途中被改成「${onSide(doc)}」`);
    await sleep(120);
    if (onSide(doc) !== label) fails.push(`「${label}」滚动到位后被改成「${onSide(doc)}」`);
    await sleep(900); /* 远超旧版 700ms 锁定时长：延时补丁会在这里露馅 */
    if (onSide(doc) !== label) fails.push(`「${label}」稳定 1s 后跳到「${onSide(doc)}」（旧 bug 复现）`);
  }
  /* 触底 + locked：点「关于」（本来就触底）→ 用户 wheel 往上滚 → spy 恢复且准确 */
  const aboutBtn = findSide(doc, '关于');
  aboutBtn.click();
  await sleep(150);
  host.dispatchEvent(new win.WheelEvent('wheel', { bubbles: true, deltaY: -300 }));
  host.scrollTo({ top: SECTION_TOP.hotkey, behavior: 'auto' });
  await sleep(150);
  const onText = onSide(doc);
  if (onText !== '快捷键') fails.push(`用户滚到「快捷键」位置后选中是「${onText}」（spy 未恢复/不准）`);
  /* free 态再滚到底：允许跟随（触底选可见最后一节=关于） */
  host.dispatchEvent(new win.WheelEvent('wheel', { bubbles: true, deltaY: 9999 }));
  host.scrollTo({ top: MAIN_SCROLL_H, behavior: 'auto' });
  await sleep(150);
  const bottomOn = onSide(doc);
  if (['开发者功能', '关于'].indexOf(bottomOn) < 0) fails.push(`用户滚到底选中异常：${bottomOn}`);
  /* locked 态滚到底也不得改选：点「开发者功能」→ 程序化滚动（目标≈触底） */
  const devBtn = findSide(doc, '开发者功能');
  devBtn.click();
  await sleep(1000);
  if (onSide(doc) !== '开发者功能') fails.push(`点「开发者功能」触底后被改成「${onSide(doc)}」（跳「关于」回归）`);
  record('A 左栏选中状态机', fails.length === 0, fails.length ? fails : { order: 'all stable' });
  win.close();
}

/* ================= 用例 B：设置搜索 ================= */
async function testSearch() {
  const { win, doc } = await bootPageRetry();
  const fails = [];
  const inp = doc.querySelector('.settings-search input');
  if (!inp) { record('B 设置搜索', false, '搜索框不存在'); win.close(); return; }
  const setVal = (v) => {
    const setter = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value').set;
    setter.call(inp, v);
    inp.dispatchEvent(new win.Event('input', { bubbles: true }));
  };
  /* CSS 层面：不存在 ::first-letter / text-indent 污染 */
  const bad = [];
  for (const sheet of doc.styleSheets) {
    let rules; try { rules = sheet.cssRules; } catch (e) { continue; }
    if (!rules) continue;
    for (const r of rules) {
      if (r.selectorText && /first-letter|first-line/.test(r.selectorText)) bad.push(r.selectorText);
      if (r.style && r.style.textIndent && r.style.textIndent !== '0px' && /search-box input|settings-search/.test(r.selectorText)) {
        bad.push(r.selectorText + ' text-indent=' + r.style.textIndent);
      }
    }
  }
  if (bad.length) fails.push('污染规则：' + bad.join(' / '));
  setVal('浏');
  await sleep(150);
  const rows = Array.from(doc.querySelectorAll('.settings-side .search-hit'));
  const texts = rows.map((r) => (r.textContent || '').trim());
  if (!rows.length) fails.push('搜「浏」无结果');
  if (!texts.some((t) => /^快捷键-.*浏览器中打开/.test(t))) {
    /* 语言包现势文案是「在浏览器中打开」，用户示范写的「浏览器中打开」；格式对即可 */
    fails.push('没有「快捷键-…浏览器中打开」合并行：' + texts.slice(0, 6).join(' | '));
  }
  if (doc.querySelector('.settings-side .hit-section') || doc.querySelector('.settings-side .hit-row')) {
    fails.push('仍是旧的两 span 分开结构');
  }
  if (rows.length && doc.querySelectorAll('.settings-side .hit-merged').length !== rows.length) {
    fails.push('合并行 .hit-merged 数量与结果数不符');
  }
  /* 清除按钮 */
  const clear = doc.querySelector('.settings-search .search-clear');
  if (!clear) fails.push('没有清除按钮');
  else if (!clear.querySelector('use')) fails.push('清除按钮没有图标');
  clear.click();
  await sleep(150);
  if (inp.value !== '' || !sideButtons(doc).length) fails.push('点清除后未恢复板块列表');
  /* Esc 清空 */
  setVal('浏');
  await sleep(120);
  inp.dispatchEvent(new win.KeyboardEvent('keydown', { bubbles: true, cancelable: true, key: 'Escape' }));
  await sleep(150);
  if (inp.value !== '' || !sideButtons(doc).length) fails.push(`Esc 未清空（value=${inp.value}）`);
  record('B 设置搜索（合并行/清除/Esc/无污染）', fails.length === 0, fails.length ? fails : { samples: texts.slice(0, 3) });
  win.close();
}

/* ================= 用例 C：Combo place ================= */
async function testCombo() {
  const { win, doc } = await bootPageRetry();
  const fails = [];
  const host = doc.querySelector('.settings-main');
  const trig = doc.querySelector('.settings-main .combo .combo-trigger');
  if (!trig) { record('C Combo', false, '设置页没有 combo-trigger'); win.close(); return; }
  /* trigger 虚拟位置：在 appearance 段内，随 host.scrollTop 上移 */
  trig.__rect = () => {
    const top = 100 - host.scrollTop;
    return { x: 300, y: top, top, left: 300, right: 500, bottom: top + 32, width: 200, height: 32, toJSON() {} };
  };
  trig.click();
  await sleep(120);
  let pop = doc.querySelector('.combo-pop');
  if (!pop) { record('C Combo', false, '点触发器没弹层'); win.close(); return; }
  const gap = () => {
    const pr = parseFloat(pop.style.top), tr = trig.__rect();
    return Math.round(pr - tr.bottom);
  };
  if (gap() !== 4) fails.push('初始间距=' + gap() + '（应 4）');
  /* 内部容器滚动（触发器仍在视口）：rAF 跟踪必须重定位且保持 4px */
  host.scrollTo({ top: 80, behavior: 'auto' });
  await sleep(120);
  pop = doc.querySelector('.combo-pop');
  if (!pop) fails.push('容器滚动 80px 后弹层被误关（触发器未离开可视区）');
  else if (gap() !== 4) fails.push('容器滚动后间距=' + gap());
  /* ⚠️⚠️ 本轮契约**反转**（用户原话）：
     「下拉框滚动超出页面还是存在的而不是直接把下拉框给关闭了
       你需要修改保留在原地即可无需超出窗口边界自动关闭。」
     → 触发器滚出可视区时**不许**自动关闭；弹层跟着触发器一起滚（top 仍= trigger.bottom+4，
       只是这个 top 可能已经跑到窗口外，这是预期行为）。 */
  host.scrollTo({ top: 500, behavior: 'auto' });
  /* ⚠️ 必须等 rAF 跟踪那一帧跑完（place() 是 requestAnimationFrame 驱动的），
     不然断言的是**上一帧**的旧 top 值 —— 这不是产品 bug，是探针自己漏了 await。 */
  await sleep(200);
  pop = doc.querySelector('.combo-pop');
  if (!pop) fails.push('触发器滚出可视区后弹层被自动关闭了（本轮要求保留、不关闭）');
  else {
    /* ⚠️ 探针第 51 行把 getBoundingClientRect patch 成读 __rect，所以这里**同源**，
       可以精确断言"top == trigger.bottom + 4"（即跟着触发器一起滚到窗口外）。
       ⚠️ 断言**不能**写成"top 必须 ≤ VH"—— 那恰好是旧版"夹到窗口底"的行为，
          本轮已明确要求不夹、跟随。 */
    const pr = parseFloat(pop.style.top), tr = trig.__rect();
    if (!isFinite(pr)) fails.push('弹层 top 无效：' + pop.style.top);
    else if (Math.round(pr - tr.bottom) !== 4) {
      fails.push(`滚出视区后没跟着触发器走（pop.top=${pr} trigger.bottom=${tr.bottom}）`);
    }
  }
  /* 重新打开后测"贴窗口底部"：不再被夹到触发器中间 */
  /* ⚠️ 弹层现在不自动关闭 → 重开前先手动收起，否则 click 是"关"不是"开" */
  host.scrollTo({ top: 0, behavior: 'auto' });
  await sleep(60);
  if (doc.querySelector('.combo-pop')) { trig.click(); await sleep(400); }
  trig.click();
  await sleep(400);
  pop = doc.querySelector('.combo-pop');
  if (!pop) fails.push('重开失败');
  else {
    host.scrollTo({ top: 68, behavior: 'auto' }); /* trigger top=32, bottom=64… 需要 bottom≈vh-40 */
    /* 直接把 trigger 摆到窗口下缘：top = VH-40-32 */
    trig.__rect = () => {
      const top = VH - 72;
      return { x: 300, y: top, top, left: 300, right: 500, bottom: top + 32, width: 200, height: 32, toJSON() {} };
    };
    await sleep(120);
    pop = doc.querySelector('.combo-pop');
    if (!pop) fails.push('贴底场景弹层被误关（触发器仍完整可见时不该关）');
    else {
      const pr = parseFloat(pop.style.top);
      const tr = trig.__rect();
      if (pr < tr.bottom) fails.push(`贴底场景弹层盖住触发器（pop.top=${pr} < trigger.bottom=${tr.bottom}）—— 旧夹取 bug 复现`);
      if (Math.round(pr - tr.bottom) !== 4) fails.push(`贴底场景间距=${Math.round(pr - tr.bottom)}`);
    }
    /* 触发器滚到**下方**窗口外：同样要求"保留、跟随"，不自动关闭 */
    trig.__rect = () => {
      const top = VH + 10;
      return { x: 300, y: top, top, left: 300, right: 500, bottom: top + 32, width: 200, height: 32, toJSON() {} };
    };
    await sleep(160);
    pop = doc.querySelector('.combo-pop');
    if (!pop) fails.push('触发器滚到窗口下方后弹层被自动关闭了（本轮要求保留）');
    else {
      /* 触发器 top=VH+10、高 32 → bottom=VH+42 → 弹层 top 应正好 VH+46。
         这里**必须**允许 top 超过 VH（跟着滚出窗口），不许再被夹回窗口内。 */
      const pr = parseFloat(pop.style.top), tr = trig.__rect();
      if (!isFinite(pr)) fails.push('下方场景弹层 top 无效：' + pop.style.top);
      else if (Math.round(pr - tr.bottom) !== 4) {
        fails.push(`下方场景没跟随（pop.top=${pr} trigger.bottom=${tr.bottom} 应差 4）`);
      }
    }
  }
  record('C Combo 贴合/跟随不关闭/不遮挡', fails.length === 0, fails.length ? fails : 'gap=4 stable');
  win.close();
}

/* ================= 用例 D：输入框右键菜单 ================= */
async function testInputMenu() {
  const { win, doc } = await bootPageRetry();
  const fails = [];
  const menu = doc.getElementById('input-menu');
  if (!menu) { record('D 右键菜单', false, '#input-menu 不存在'); win.close(); return; }
  if (!menu.hidden) fails.push('初始未 hidden（会常驻左上角）');
  const inp = doc.querySelector('.settings-search input');
  const setter = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value').set;
  setter.call(inp, '');
  inp.dispatchEvent(new win.Event('input', { bubbles: true }));
  const openAt = (target, x, y) => {
    const ev = new win.MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: x, clientY: y });
    target.dispatchEvent(ev);
    return ev;
  };
  openAt(inp, 200, 120);
  await sleep(150);
  if (menu.hidden) fails.push('右键没打开菜单');
  else {
    const items = Array.from(menu.querySelectorAll('.input-menu-item'));
    if (items.length !== 6) fails.push('项数=' + items.length);
    const map = {};
    items.forEach((b) => {
      map[b.getAttribute('data-cmd')] = {
        label: (b.querySelector('.imi-label') || {}).textContent,
        hotkey: (b.querySelector('.imi-key') || {}).textContent,
        disabled: b.disabled || b.classList.contains('is-disabled'),
        icon: !!b.querySelector('use'),
      };
    });
    /* 本轮需求：快捷键**加括号** → 断言跟上（旧断言是过期断言，不是产品 bug） */
    const wantKeys = { copy: '（Ctrl+C）', paste: '（Ctrl+V）', cut: '（Ctrl+X）',
      'select-all': '（Ctrl+A）', undo: '（Ctrl+Z）', redo: '（Ctrl+Y）' };
    for (const cmd of Object.keys(wantKeys)) {
      if (!map[cmd]) { fails.push('缺项 ' + cmd); continue; }
      if (!map[cmd].icon) fails.push(cmd + ' 无图标');
      if (map[cmd].hotkey !== wantKeys[cmd]) fails.push(`${cmd} 快捷键小字=${map[cmd].hotkey}`);
      if (!map[cmd].label) fails.push(cmd + ' 无文案');
    }
    /* 空输入框无选区：copy/cut/select-all 禁用 */
    for (const cmd of ['copy', 'cut', 'select-all']) {
      if (map[cmd] && !map[cmd].disabled) fails.push(`空框无选区时 ${cmd} 应禁用`);
    }
    /* 不超窗：靠右下角打开 */
    openAt(inp, VW - 20, VH - 20);
    await sleep(150);
    const left = parseFloat(menu.style.left), top = parseFloat(menu.style.top);
    if (!(left >= 0 && top >= 0 && left + 172 <= VW && top + 230 <= VH)) {
      fails.push(`菜单超出窗口 left=${left} top=${top}`);
    }
    /* 点外部关闭 */
    doc.querySelector('.settings-side').dispatchEvent(new win.MouseEvent('mousedown', { bubbles: true, cancelable: true }));
    await sleep(50);
    if (!menu.hidden) fails.push('点外部没关闭');
  }
  /* 有选区 + 有内容：copy/cut 可用、select-all 可用 */
  setter.call(inp, '浏览器');
  inp.dispatchEvent(new win.Event('input', { bubbles: true }));
  try { inp.setSelectionRange(0, 2); } catch (e) {}
  openAt(inp, 200, 120);
  await sleep(150);
  if (!menu.hidden) {
    const dm = {};
    menu.querySelectorAll('.input-menu-item').forEach((b) => {
      dm[b.getAttribute('data-cmd')] = b.disabled || b.classList.contains('is-disabled');
    });
    if (dm.copy) fails.push('有选区时 copy 仍禁用');
    if (dm.cut) fails.push('有选区时 cut 仍禁用');
    if (dm['select-all']) fails.push('有内容时 select-all 仍禁用');
    /* 原生菜单被 preventDefault */
    const ev = openAt(inp, 200, 120);
    if (!ev.defaultPrevented) fails.push('没拦掉浏览器原生右键菜单');
    /* Esc 关闭 */
    win.dispatchEvent(new win.KeyboardEvent('keydown', { bubbles: true, key: 'Escape' }));
    await sleep(50);
    if (!menu.hidden) fails.push('Esc 没关菜单');
  } else {
    fails.push('有选区右键没打开菜单');
  }
  /* AI 区右键归属（Lead 与 ai 队友对齐后的口径，2026-11-06 修订本断言）：
       · AI **输入框**（.ai-input / .ai-rich-input）= 就是个输入框 → 归**本通用菜单**
         （用户原话"加入右键输入框有菜单弹出 包含复制 粘贴 剪切 全选 撤销 重做"，
          没有把 AI 输入框排除在外）；
       · AI **聊天气泡**（.bubble）= 归 AI 队友的"复制 / 全选↔取消全选"菜单，
         本通用菜单必须不接管（否则两套菜单打架）。
     ⚠️ 这里**不靠 Vue 真渲染抽屉**：jsdom 里 rich-ai-input 挂载 + drawer transition
        时机不稳（固定 sleep / 轮询都会假失败）。委托监听挂在 document 上，
        对任意节点都生效 → 直接造同构节点喂给监听，测的就是那两个判定函数本身。
     旧断言写的是"AI 输入框也要排除"，那是当时对需求的误读，已按上面口径改正。 */
  {
    const mk = (html) => {
      const holder = doc.createElement('div');
      holder.innerHTML = html;
      doc.body.appendChild(holder);
      return holder;
    };
    /* ① AI 输入框（contenteditable=true 的 div，和 rich-input 根节点同构）→ 通用菜单接管 */
    const aiBox = mk('<div class="ai-input ai-rich-input" contenteditable="true">'
      + '写点什么</div>').firstElementChild;
    openAt(aiBox, 300, 400);
    await sleep(200);
    if (menu.hidden) {
      fails.push('AI 输入框没被通用菜单接管（应给完整编辑菜单）');
    } else {
      const items = Array.from(menu.querySelectorAll('.input-menu-item'));
      if (items.length !== 6) fails.push('AI 输入框菜单项数=' + items.length + '（应 6 项）');
    }
    /* ② 气泡里可编辑的节点 → 必须让路（通用菜单不能开，归 AI 专属菜单）
       故意做成 contenteditable：这样 _isEditableField 会判 true，
       只有排除表真的命中 .bubble 才拦得住 —— 测的就是排除逻辑本身。 */
    doc.body.dispatchEvent(new win.MouseEvent('mousedown', {
      bubbles: true, clientX: 5, clientY: 5 }));      // 先关掉上一步的菜单
    await sleep(120);
    const bubble = mk('<div class="bubble-wrap is-ai"><div class="bubble is-ai">'
      + '<span contenteditable="true">回答正文</span></div></div>')
      .querySelector('.bubble');
    openAt(bubble, 300, 300);
    await sleep(200);
    if (!menu.hidden) fails.push('气泡被通用菜单接管（应让路给 AI 专属菜单）');
    /* ③ 普通输入框对照：证明②不是"整条链路都打不开"造成的假通过 */
    const plain = mk('<input type="text" value="abc">').firstElementChild;
    openAt(plain, 200, 200);
    await sleep(200);
    if (menu.hidden) fails.push('对照失败：普通 input 也没打开菜单（②的结论不可信）');
    doc.body.dispatchEvent(new win.MouseEvent('mousedown', {
      bubbles: true, clientX: 5, clientY: 5 }));
  }
  /* readonly（快捷键输入框）：菜单接管，但改内容的项（cut/paste/undo/redo）禁用 */
  const ro = doc.querySelector('.hotkey-input');
  if (!ro) {
    fails.push('找不到 .hotkey-input（readonly 接管断言没跑）');
  }
  if (ro) {
    openAt(ro, 200, 300);
    await sleep(150);
    if (menu.hidden) {
      fails.push('readonly 输入框没被全局菜单接管（需求=所有 input）');
    } else {
      const dm2 = {};
      menu.querySelectorAll('.input-menu-item').forEach((b) => {
        dm2[b.getAttribute('data-cmd')] = b.disabled || b.classList.contains('is-disabled');
      });
      if (!dm2.cut || !dm2.paste || !dm2.undo || !dm2.redo) {
        fails.push('readonly 框上 cut/paste/undo/redo 未禁用：' + JSON.stringify(dm2));
      }
      doc.querySelector('.settings-side').dispatchEvent(new win.MouseEvent('mousedown', { bubbles: true, cancelable: true }));
      await sleep(50);
    }
  }
  record('D 输入框右键菜单', fails.length === 0, fails.length ? fails : '6 items stable');
  win.close();
}

/* ================= 用例 E：英文三语格式 ================= */
async function testI18n() {
  /* jsdom 的 window 没有 fetch，而 serve.py 的 mock i18n.bundle 用 fetch('/mock/i18n')。
     不能全局打桩 win.fetch（会干扰 app.js 的浏览器模式探测），也不能把整包 JSON 塞进
     js0（超过 http.server 的请求行上限 → 414）。
     → 用 js0 把 mock 的 i18n.bundle 换成 jsdom 支持的 XMLHttpRequest 版本。 */
  const js0 = encodeURIComponent(
    'window.__MOCK_SETTINGS__.language = "English";'
    + 'window.pywebview.api.i18n.bundle = function (lang) { return new Promise(function (res) {'
    + 'var x = new XMLHttpRequest();'
    + 'x.open("GET", "/mock/i18n?lang=" + encodeURIComponent(lang || "English"));'
    + 'x.onload = function () { try { res(JSON.parse(x.responseText)); } catch (e) { res({ ok: false, error: String(e) }); } };'
    + 'x.onerror = function () { res({ ok: false, error: "xhr" }); };'
    + 'x.send(); }); };');
  const { win, doc } = await bootPageRetry('&js0=' + js0);
  const fails = [];
  const inp = doc.querySelector('.settings-search input');
  const setter = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value').set;
  /* 三语正确性 = 结果格式在英文界面同样成立；关键词用英文（"browser" 命中
     「Open in Browser」行），中文关键词在英文包里没有对应文本，属正常。 */
  setter.call(inp, 'browser');
  inp.dispatchEvent(new win.Event('input', { bubbles: true }));
  await sleep(200);
  const texts = Array.from(doc.querySelectorAll('.settings-side .search-hit')).map((r) => (r.textContent || '').trim());
  if (!texts.length) fails.push('英文态搜「browser」无结果');
  else {
    if (!texts.some((t) => /^Hotkeys-Open in Browser/.test(t))) {
      fails.push('没有 Hotkeys-Open in Browser：' + texts.slice(0, 5).join(' | '));
    }
    if (!texts.every((t) => t.indexOf('-') > 0)) fails.push('结果不是 板块-设置项 格式');
  }
  /* 菜单文案跟随语言 */
  const menu = doc.getElementById('input-menu');
  inp.dispatchEvent(new win.MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 200, clientY: 120 }));
  await sleep(150);
  const labels = Array.from(menu.querySelectorAll('.imi-label')).map((s) => s.textContent);
  if (!labels.some((l) => /Copy/i.test(l))) fails.push('菜单文案未切英文：' + labels.join('/'));
  record('E 英文态结果与菜单文案', fails.length === 0, fails.length ? fails : { labels });
  win.close();
}

async function main() {
  await testSpy();
  await testSearch();
  await testCombo();
  await testInputMenu();
  await testI18n();
  const failed = results.filter((r) => !r.ok);
  console.log('='.repeat(60));
  console.log(failed.length ? `SUMMARY: ${failed.length} FAIL / ${results.length} total` : 'SUMMARY: ALL PASS');
  process.exit(failed.length ? 1 : 0);
}

main().catch((e) => { console.error('探针自身异常：', e); process.exit(2); });
