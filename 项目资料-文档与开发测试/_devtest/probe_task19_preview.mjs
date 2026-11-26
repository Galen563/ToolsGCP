// probe_task19_preview.mjs —— 投稿表单「实时预览」提示不消失（第七轮需求①，m06914）
//
// 用户原话：「在提交软件界面我导入图片了可是实时预览那里还是提示这个，标签也是，这个整体修一下」。
// 两条都要**走真实链路**取证，不许只查代码字符串：
//   · 图标：真实点「导入图片」→ 真实 FileReader 读文件 → 真实 pickIcon 赋值 → 看预览 img 出图、
//     看状态行里那条「还没导入图片」是否消失。
//   · 标签：真实往标签输入框打字（input 事件走 v-model 的 setter）→ 看预览胶囊出现、
//     「（无标签）」消失。
// 环境垫片沿用 probe_task13_maker_ui.mjs 的 boot()（滚动尺寸桩 / getComputedStyle 覆盖）。
// jsdom 里 FileReader 与 File 都有，但 <input type=file>.click() 不会弹框，
// 所以这里捕获被创建的 input，再手动塞 files + 派发 change —— 走的仍是 pickIcon 自己的代码。
import fs from 'node:fs';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const pexec = promisify(execFile);
const HERE2 = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE2, '..', '..');
const SERVE = path.join(HERE2, 'serve.py');
const PORT = Number(process.env.GCP_PORT || 8913);
const BASE = 'http://127.0.0.1:' + PORT + '/';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
const add = (name, pass, detail) => results.push({ name, pass: !!pass, detail: detail === undefined ? '' : String(detail).slice(0, 200) });

async function fetchText(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error('HTTP ' + res.status + ' ' + url);
  return res.text();
}
function cutInlineScript(htmlText) {
  const s = [];
  let i = 0;
  while (i < htmlText.length) {
    const lt = htmlText.indexOf('<', i);
    if (lt < 0) { s.push(htmlText.slice(i)); break; }
    s.push(htmlText.slice(i, lt));
    if (htmlText.startsWith('<!--', lt)) {
      const end = htmlText.indexOf('-->', lt);
      if (end < 0) { s.push(htmlText.slice(lt)); break; }
      s.push(htmlText.slice(lt, end + 3));
      i = end + 3;
      continue;
    }
    const gt = htmlText.indexOf('>', lt);
    if (gt < 0) { s.push(htmlText.slice(lt)); break; }
    const tag = htmlText.slice(lt, gt + 1);
    if (/^<script\b/i.test(tag) && !/\ssrc=/i.test(tag)) {
      const close = htmlText.toLowerCase().indexOf('<' + '/script>', gt);
      if (close < 0) { s.push(tag); i = gt + 1; continue; }
      const end = close + 9;
      if (/tailwind/i.test(htmlText.slice(gt, close))) {
        s.push(tag + 'window.tailwind={config:{}};' + '<' + '/script>');
      } else {
        s.push(htmlText.slice(i, end));
      }
      i = end;
      continue;
    }
    s.push(tag);
    i = gt + 1;
  }
  return s.join('');
}
async function bootDom() {
  const { JSDOM, VirtualConsole } = await import('jsdom');
  const htmlText = cutInlineScript(await fetchText(BASE + '?page=maker&auditfile=task19_audit.json'));
  const vc = new VirtualConsole();
  vc.on('jsdomError', () => {});
  vc.on('error', () => {});
  const dom = new JSDOM(htmlText, {
    url: BASE, runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(win) {
      win.__pywebview = { api: {} };
      const clamp = (el) => {
        const max = Math.max(0, (el.__sh || 5000) - (el.__ch || 600));
        return Math.max(0, Math.min(max, el.__st || 0));
      };
      [win.Element.prototype, win.HTMLElement.prototype].forEach((proto) => {
        Object.defineProperty(proto, 'scrollTop', {
          configurable: true,
          get() { return this.__st || 0; },
          set(v) { this.__st = clamp(Object.assign(this, { __st: Number(v) || 0 })); },
        });
        Object.defineProperty(proto, 'scrollHeight', { configurable: true, get() { return this.__sh || 5000; } });
        Object.defineProperty(proto, 'clientHeight', { configurable: true, get() { return this.__ch || 600; } });
      });
      const rawCS = win.getComputedStyle.bind(win);
      win.getComputedStyle = (el) => {
        const cs = rawCS(el);
        const cls = String((el && el.className) || '');
        let oy = cs.overflowY;
        if (cls.includes('maker-body')) oy = 'hidden';
        if (cls.includes('maker-form-scroll') || cls.includes('maker-section-scroll') || cls.includes('page-scroll')) oy = 'auto';
        return new Proxy(cs, {
          get(t, k) {
            if (k === 'overflowY') return oy;
            const v = t[k];
            return typeof v === 'function' ? v.bind(t) : v;
          },
          getOwnPropertyDescriptor(t, k) {
            const d = Object.getOwnPropertyDescriptor(t, k);
            if (k === 'overflowY') return { value: oy, writable: false, configurable: true, enumerable: true };
            return d;
          },
        });
      };
    },
  });
  win = dom.window;
  doc = win.document;
  global.window = win;
  global.document = doc;
  for (let i = 0; i < 250; i++) {
    if (win.__TOOLSGCP_APP__) break;
    await sleep(100);
  }
  if (!win.__TOOLSGCP_APP__) throw new Error('Vue 未挂载');
  await sleep(300);
  return win.__TOOLSGCP_APP__;
}

let win = null;
let doc = null;
let vm = null;
let bridgeSpy = null;

// 真实驱动 pickIcon：捕获 document.createElement 造出来的 <input type=file>
async function realImportIcon(name, bytes) {
  const created = [];
  const rawCreate = doc.createElement.bind(doc);
  doc.createElement = (tag) => {
    const el = rawCreate(tag);
    if (String(tag).toLowerCase() === 'input') created.push(el);
    return el;
  };
  let done = null;
  const waiter = new Promise((resolve) => { done = resolve; });
  try {
    const file = new win.File([new Uint8Array(bytes)], name, { type: 'image/png' });
    const p = vm.pickIcon();
    let input = null;
    for (let i = 0; i < 60 && !input; i++) {
      input = created.find((el) => el.type === 'file') || null;
      if (!input) await sleep(20);
    }
    if (!input) return { ok: false, why: '没造出 file input（pickIcon 没走到 pickImageFile）' };
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    input.dispatchEvent(new win.Event('change'));
    const timer = new Promise((r) => setTimeout(() => r('timeout'), 8000));
    await Promise.race([p.then(() => 'resolved'), timer]);
    if (done) done();
    return { ok: true, why: '' };
  } finally {
    doc.createElement = rawCreate;
    void waiter;
  }
}

async function gotoMaker() {
  vm.page = 'maker';
  vm.activeSection = 'form';
  await sleep(400);
}
const q = (sel) => doc.querySelector(sel);

async function portLive() {
  /* Windows 的 SO_REUSEADDR 允许第二个进程绑同一个端口：serve.py 绑占用端口**不会**报错退出，
     旧写法 `await pexec(python serve.py)` 于是永远等不到子进程结束 → 探针卡死（实测 CPU 0.07s 挂 6 分钟）。
     先探一次活，活着就复用现有服务。 */
  try { return (await fetch(BASE, { cache: 'no-store' })).ok; } catch (e) { return false; }
}

async function main() {
  if (await portLive()) {
    console.log('[task19] 复用端口 ' + PORT + ' 上已有的 serve.py');
  } else {
    try {
      await pexec('python', [SERVE, String(PORT)], { cwd: ROOT });
    } catch (e) {
      console.log('[task19] 端口 ' + PORT + ' serve.py 退出：' + String(e && e.message).slice(0, 80));
    }
  }
  const appJs = fs.readFileSync(path.join(ROOT, '.ToolsGCP', 'webui', 'js', 'app.js'), 'utf8');
  const indexHtml = fs.readFileSync(path.join(ROOT, '.ToolsGCP', 'webui', 'index.html'), 'utf8');

  // ---------- S 静态契约 ----------
  const warnIcon = appJs.match(/if \(!maker\.iconName([^)]*)\) out\.push\(t\('还没导入图片/g);
  add('S1 图标警告必须把「预览中待保存」也算作已导入', warnIcon && /iconPending/.test(warnIcon[0]), warnIcon && warnIcon[0].slice(0, 120));
  const descWarn = appJs.match(/if \(!String\(maker\.i18n\['简体中文'\]\.description[^)]*\)\.trim\(\)\) \{\n\s*out\.push\(t\('「简介」留空了/g);
  add('S2 简介警告不能再只看简体中文那一份', !descWarn, descWarn ? '仍在只查 简体中文 池' : '已按分段/回退链判定');
  add('S3 预览图标仍绑 previewIcon（不改语义）', /<img v-if="previewIcon" :src="previewIcon"/.test(indexHtml));
  add('S4 previewIcon 仍取 maker.iconSource（内存预览优先）', /const previewIcon = computed\(\(\) => \(maker\.iconSource \? maker\.iconSource : ''\)\);/.test(appJs));

  vm = await bootDom();
  await gotoMaker();
  vm.maker.name = '探针软件';
  vm.maker.id = 'probe-task19';
  await sleep(150);

  // ---------- R1 导入图片：预览出图 + 提示消失 ----------
  const before = String(q('.preview-status') ? q('.preview-status').textContent : '');
  add('R1a 导入前状态行确实有「还没导入图片」提示', /还没导入图片/.test(before), before.slice(0, 90));
  const imp = await realImportIcon('probe-icon.png', 8);
  add('R1b 真实走完 pickIcon（FileReader → 赋值）', imp.ok, imp.why);
  await sleep(300);
  const img = q('.preview-icon img');
  add('R1c 预览出现 img 且 src 是 dataURL', !!(img && /^data:image/i.test(img.getAttribute('src') || '')),
    img ? String(img.getAttribute('src')).slice(0, 40) : '无 img，仍是占位「?」');
  const afterIcon = String(q('.preview-status') ? q('.preview-status').textContent : '');
  add('R1d 导入后「还没导入图片」提示消失', !/还没导入图片/.test(afterIcon), afterIcon.slice(0, 120));
  add('R1e 图标仍是待保存语义（没被提前写盘）', vm.maker.iconPending === true && !vm.maker.iconName,
    'pending=' + vm.maker.iconPending + ' iconName=' + JSON.stringify(vm.maker.iconName));

  // ---------- R2 标签：输入即出胶囊 ----------
  const tagInput = Array.from(doc.querySelectorAll('.tags-row input')).find((el) => /工具/.test(el.getAttribute('placeholder') || ''));
  add('R2a 找到标签输入框', !!tagInput, tagInput ? tagInput.getAttribute('placeholder') : '未找到');
  if (tagInput) {
    const capBefore = q('.preview-tags .cap');
    add('R2b 输入前预览是「（无标签）」占位', !!capBefore && /无标签/.test(capBefore.textContent), capBefore ? capBefore.textContent : '已有胶囊');
    tagInput.value = '工具, 网络';
    tagInput.dispatchEvent(new win.Event('input'));
    await sleep(300);
    const pills = Array.from(doc.querySelectorAll('.preview-tags .tag')).map((el) => el.textContent.trim());
    add('R2c 输入后预览出现标签胶囊', pills.length === 2, JSON.stringify(pills));
    add('R2d 「（无标签）」占位消失', !q('.preview-tags .cap'), q('.preview-tags .cap') ? q('.preview-tags .cap').textContent : '');
    add('R2e 池子里存的是规范值', /工具/.test(vm.maker.tags[vm.makerSegLang] || Object.values(vm.maker.tags)[0] || ''),
      JSON.stringify(vm.maker.tags));
  }

  // ---------- R3 简介只填 English 时不该再报「简介留空」 ----------
  vm.maker.i18n.简体中文.description = '';
  vm.maker.i18n.English.description = 'English only description';
  await sleep(250);
  const st3 = String(q('.preview-status') ? q('.preview-status').textContent : '');
  add('R3 只填英文简介时不再报「简介留空」', !/「简介」留空了/.test(st3), st3.slice(0, 120));

  // ---------- R6 载入现有资源（真实 editExistingEntry → resources.detail）后的预览 ----------
  const detailCalls = [];
  const spyDomain = {
    detail(code) {
      detailCalls.push(code);
      return Promise.resolve({
        ok: true,
        item: {
          code: 'TG-009999', name: '探针已存软件', id: 'probe-loaded',
          category: '工具',
          tags_i18n: { 简体中文: ['工具', '网络'], 繁體中文: ['工具', '網絡'], English: ['Tools', 'Network'] },
          icon: 'TG-009999.png', url: 'https://example.com',
          description: '一条已有的简介',
          name_i18n: { 简体中文: '探针已存软件', 繁體中文: '探針已存軟體', English: 'Probe Loaded' },
        },
      });
    },
  };
  if (!win.pywebview) win.pywebview = {};
  win.pywebview.api = Object.assign(win.pywebview.api || {}, { resources: spyDomain });
  if (win.__pywebview) win.__pywebview.api = win.pywebview.api;
  try { bridgeSpy = await vm.editExistingEntry({ code: 'TG-009999', name: 'x' }); } catch (e) { bridgeSpy = 'throw ' + e.message; }
  await sleep(900);
  const pills6 = Array.from(doc.querySelectorAll('.preview-tags .tag')).map((el) => el.textContent.trim());
  add('R6a 载入现有资源后预览有标签胶囊（不是占位）', pills6.length >= 2, JSON.stringify(pills6) + ' detail=' + JSON.stringify(detailCalls) + ' ret=' + String(bridgeSpy).slice(0, 60));
  add('R6b 载入现有资源后预览有图标 img', !!doc.querySelector('.preview-icon img'),
    'src=' + (doc.querySelector('.preview-icon img') ? String(doc.querySelector('.preview-icon img').getAttribute('src')).slice(0, 40) : '无') + ' iconSource=' + String(vm.maker.iconSource).slice(0, 40));
  const st6 = String(doc.querySelector('.preview-status') ? doc.querySelector('.preview-status').textContent : '');
  add('R6c 载入现有资源（有图标）后不再报「还没导入图片」', !/还没导入图片/.test(st6), st6.slice(0, 110));

  // ---------- R7 只填了非当前分段的池：预览该按回退链出内容 ----------
  vm.maker.tags = { 简体中文: '', 繁體中文: '', English: 'Tools, Network' };
  vm.i18nLangIndex = 0;            // 当前分段 = 简体中文（那份是空的）
  await sleep(300);
  const pills7 = Array.from(doc.querySelectorAll('.preview-tags .tag')).map((el) => el.textContent.trim());
  add('R7 当前分段空、English 有值时预览按回退链出胶囊', pills7.length === 2, JSON.stringify(pills7));
  const cap7 = doc.querySelector('.preview-tags .cap');
  add('R7b 此时不显示「（无标签）」占位', !cap7, cap7 ? cap7.textContent : '');

  // ---------- R4 清空表单后提示应回来（不能反向卡住） ----------
  vm.clearForm && vm.clearForm();
  await sleep(200);
  const okBtn = Array.from(doc.querySelectorAll('.modal-backdrop button')).find((b) => /确定|清空|OK/i.test(b.textContent));
  if (okBtn) okBtn.click();
  await sleep(300);
  add('R4a 清空后图标状态归零', !vm.maker.iconSource && vm.maker.iconPending === false && !vm.maker.iconName,
    'src=' + String(vm.maker.iconSource).slice(0, 24) + ' pending=' + vm.maker.iconPending);
  // makerWarnings 没暴露到 vm 上，所以把必填项补齐再读状态行（错误优先于警告）
  vm.maker.name = '再测一次';
  vm.maker.id = 'probe-task19-again';
  await sleep(250);
  const st4 = String(q('.preview-status') ? q('.preview-status').textContent : '');
  add('R4b 补齐必填后清空过的表单会重新报「还没导入图片」', /还没导入图片/.test(st4), st4.slice(0, 130));
  add('R5 清空后预览回到占位（img 消失、无标签占位回来）', !q('.preview-icon img') && !!q('.preview-tags .cap'),
    'img=' + !!q('.preview-icon img') + ' cap=' + (q('.preview-tags .cap') ? q('.preview-tags .cap').textContent : '无'));

  const pass = results.filter((r) => r.pass).length;
  console.log('\n===== task-19 实时预览提示（' + pass + '/' + results.length + '）=====');
  results.forEach((r) => console.log((r.pass ? 'OK   ' : 'FAIL ') + r.name + (r.detail ? '  <- ' + r.detail : '')));
  console.log(pass === results.length ? 'ALL PASS' : 'HAS FAILURES');
  process.exit(pass === results.length ? 0 : 1);
}
main().catch((e) => { console.log('[task19] 崩溃: ' + (e && e.stack ? e.stack : e)); process.exit(2); });
