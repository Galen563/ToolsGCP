// probe_maker_status_sweep.mjs —— 投稿表单「实时预览底部状态行」逐场景取证（第七轮需求①的续集）
//
// 用户在 ask_user_question 里确认：「标签也是」指的是**预览卡片底部那行状态提示**。
// 所以这里不猜代码，直接把 12 个场景的状态行原文打出来，看哪一条提示在**内容已经填了之后**还赖着不走。
// 环境垫片沿用 probe_task19_preview.mjs（jsdom 没有布局，但状态行是纯计算属性，够用）。
import fs from 'node:fs';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const pexec = promisify(execFile);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');
const SERVE = path.join(HERE, 'serve.py');
const PORT = Number(process.env.GCP_PORT || 8914);
const BASE = 'http://127.0.0.1:' + PORT + '/';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let win = null, doc = null, vm = null;

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
  const htmlText = cutInlineScript(await (await fetch(BASE + '?page=maker&auditfile=sweep_audit.json')).text());
  const vc = new VirtualConsole();
  vc.on('jsdomError', () => {});
  vc.on('error', () => {});
  const dom = new JSDOM(htmlText, {
    url: BASE, runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(win) {
      win.__pywebview = { api: {} };
      const rawCS = win.getComputedStyle.bind(win);
      win.getComputedStyle = (el) => {
        const cs = rawCS(el);
        return new Proxy(cs, {
          get(t, k) { const v = t[k]; return typeof v === 'function' ? v.bind(t) : v; },
          getOwnPropertyDescriptor(t, k) { return Object.getOwnPropertyDescriptor(t, k); },
        });
      };
    },
  });
  win = dom.window; doc = win.document;
  global.window = win; global.document = doc;
  for (let i = 0; i < 250; i++) { if (win.__TOOLSGCP_APP__) break; await sleep(100); }
  if (!win.__TOOLSGCP_APP__) throw new Error('Vue 未挂载');
  await sleep(300);
  return win.__TOOLSGCP_APP__;
}

const out = [];
function status() {
  const el = doc.querySelector('.preview-status');
  return el ? String(el.textContent).replace(/\s*\n\s*/g, ' ⏎ ') : '(没有 .preview-status 节点)';
}
function tagInputEl() {
  return Array.from(doc.querySelectorAll('.tags-row input')).find((el) => /工具/.test(el.getAttribute('placeholder') || ''));
}
async function typeTags(text) {
  const el = tagInputEl();
  if (!el) return false;
  el.value = text;
  el.dispatchEvent(new win.Event('input'));
  await sleep(220);
  return true;
}
async function realImportIcon(name, bytes) {
  const created = [];
  const rawCreate = doc.createElement.bind(doc);
  doc.createElement = (tag) => {
    const el = rawCreate(tag);
    if (String(tag).toLowerCase() === 'input') created.push(el);
    return el;
  };
  try {
    const file = new win.File([new Uint8Array(bytes)], name, { type: 'image/png' });
    const p = vm.pickIcon();
    let input = null;
    for (let i = 0; i < 60 && !input; i++) {
      input = created.find((el) => el.type === 'file') || null;
      if (!input) await sleep(20);
    }
    if (!input) return { ok: false, why: '没造出 file input' };
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    input.dispatchEvent(new win.Event('change'));
    await Promise.race([p.then(() => 'ok'), sleep(8000)]);
    return { ok: true, why: '' };
  } finally {
    doc.createElement = rawCreate;
  }
}
function shot(tag) {
  out.push({ tag, status: status(), tags: JSON.stringify(vm.maker.tags), cat: JSON.stringify(vm.maker.category) });
  console.log('[' + tag + '] ' + status());
  console.log('      tags=' + out[out.length - 1].tags + '  cat=' + out[out.length - 1].cat + '  seg=' + vm.i18nLangIndex);
}

async function portLive() {
  /* 同 probe_task19_preview：Windows 上绑占用端口的 serve.py 不会失败退出，必须自己先探活。 */
  try { return (await fetch(BASE, { cache: 'no-store' })).ok; } catch (e) { return false; }
}

async function main() {
  if (await portLive()) console.log('[sweep] 复用端口 ' + PORT + ' 上已有的 serve.py');
  else { try { await pexec('python', [SERVE, String(PORT)], { cwd: ROOT }); }
         catch (e) { console.log('[sweep] 端口 ' + PORT + ' serve.py 退出：' + String(e && e.message).slice(0, 80)); } }
  vm = await bootDom();
  vm.page = 'maker';
  vm.activeSection = 'form';
  await sleep(400);
  vm.maker.name = '探针软件';
  vm.maker.id = 'probe-sweep';
  await sleep(220);
  shot('S1 只填名称+标识');

  const okTags = await typeTags('工具, 网络');
  console.log('  找到标签输入框 =', okTags);
  shot('S2 + 标签');

  vm.maker.category.简体中文 = '工具';
  await sleep(220);
  shot('S3 + 类别');

  vm.maker.url = 'https://example.com';
  await sleep(220);
  shot('S4 + 官网');

  vm.maker.i18n['简体中文'].description = '一句话简介';
  await sleep(220);
  shot('S5 + 简介');

  const imp = await realImportIcon('sweep.png', 8);
  await sleep(260);
  console.log('  导入图标 =', JSON.stringify(imp));
  shot('S6 + 导入图标');

  await typeTags('');
  shot('S7 标签清空（提示该回来）');

  await typeTags('工具, 网络');
  vm.maker.tags.繁體中文 = '';
  vm.maker.tags.English = '';
  await sleep(220);
  shot('S8 只留简体中文标签');

  vm.maker.tags.English = 'Tools, Popular';
  vm.i18nLangIndex = 2;
  await sleep(260);
  shot('S9 切到 English 分段填标签');

  await typeTags('工具');
  await sleep(120);
  shot('S10 标签与类别同名');

  vm.i18nLangIndex = 0;
  await typeTags('网络');
  if (vm.addLinkRow) vm.addLinkRow();
  await sleep(240);
  shot('S11 新增一条空自定义链接');

  vm.maker.github = 'Galen563/ToolsGCP';
  await sleep(240);
  shot('S12 填开源仓库');

  vm.maker.i18n.繁體中文.description = '一句話簡介';
  vm.maker.i18n.English.description = 'One line intro';
  vm.maker.category.繁體中文 = '工具';
  vm.maker.category.English = 'Tools';
  vm.maker.tags.繁體中文 = '網絡';
  vm.maker.tags.English = 'Network';
  if (vm.maker.links && vm.maker.links.length) {
    vm.maker.links[0].label = { 简体中文: '教程', 繁體中文: '教程', English: 'Docs' };
    vm.maker.links[0].url = { 简体中文: 'https://a.com', 繁體中文: 'https://a.com', English: 'https://a.com' };
  }
  await sleep(320);
  shot('S13 全部填齐（期望「信息完整」）');

  // ---- 第二轮追问：「标签」同名提示会不会赖着不走 ----
  vm.clearForm && vm.clearForm();
  await sleep(150);
  const okBtn = Array.from(doc.querySelectorAll('.modal-backdrop button')).find((b) => /确定|清空|OK/i.test(b.textContent));
  if (okBtn) okBtn.click();
  await sleep(300);
  vm.maker.name = '同名探针';
  vm.maker.id = 'probe-same';
  vm.maker.url = 'https://example.com';
  vm.maker.i18n['简体中文'].description = '简介';
  await sleep(240);
  shot('S14 清空后重填必填（看默认类别是什么）');

  await typeTags('工具, 系统, 官方');
  shot('S15 按占位符示例填标签');

  await typeTags('系统, 官方');
  shot('S16 去掉与类别同名的标签（提示该消失）');

  vm.maker.category.简体中文 = '办公';
  await typeTags('工具, 系统');
  await sleep(240);
  shot('S17 改类别为办公后再把工具当标签');

  vm.i18nLangIndex = 2;
  await sleep(240);
  shot('S18 只看 English 分段（该语言没填标签）');

  vm.maker.tags.English = 'Tools';
  await sleep(240);
  shot('S19 English 标签写 Tools（类别 English 空）');

  vm.maker.category.English = 'Tools';
  await sleep(240);
  shot('S20 English 类别也写 Tools（同名，提示该出现）');

  vm.maker.category.English = 'Office';
  await sleep(240);
  shot('S21 English 类别改 Office（同名解除，提示该消失）');

  console.log('\n共 ' + out.length + ' 个场景');
  process.exit(0);
}
main().catch((e) => { console.log('[sweep] 崩溃: ' + (e && e.stack ? e.stack : e)); process.exit(2); });
