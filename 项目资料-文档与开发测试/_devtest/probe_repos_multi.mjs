/* jsdom 探针：多组开源仓库（用户 m08848：「提交软件中开源仓库支持多个同时有，
 *   所以增加一个加号图标的按钮点击增加一组，还有垃圾啊桶删除对应组。」）
 * 用法：python 项目资料-文档与开发测试/_devtest/serve.py <port> 后
 *      GCP_PORT=<port> node probe_repos_multi.mjs
 * ⚠️ 语言无关写法：按钮文案跟着界面语言变 ⇒ 找按钮一律按 class（.repo-del-btn / .repo-paste-btn）
 *   或按函数调用，绝不按文案。
 */
import { JSDOM, VirtualConsole } from 'jsdom';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const PORT = process.env.GCP_PORT || '8912';
const BASE = 'http://127.0.0.1:' + PORT;
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const results = [];
function record(name, ok, detail) {
  results.push({ name, ok });
  console.log((ok ? 'PASS' : 'FAIL') + '  ' + name
    + (detail !== undefined ? '  ' + JSON.stringify(detail) : ''));
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ========================= 静态契约 ========================= */
const html = await fs.readFile(path.join(ROOT, '.ToolsGCP/webui/index.html'), 'utf8');
const css = await fs.readFile(path.join(ROOT, '.ToolsGCP/webui/css/layout.css'), 'utf8');
const app = await fs.readFile(path.join(ROOT, '.ToolsGCP/webui/js/app.js'), 'utf8');
const countOf = (src, needle) => src.split(needle).length - 1;

record('① 模板里开源仓库是 v-for 多行（每组一行）',
  /class="repo-row"\s+v-for="\(row, ri\) in maker\.repos"/.test(html),
  { hits: countOf(html, 'v-for="(row, ri) in maker.repos"') });
record('① 每行含平台下拉 / 地址输入 / 粘贴按钮 / 垃圾桶删除按钮',
  countOf(html, 'onRepoPlatformChanged(row, $event)') === 1
  && countOf(html, 'v-model="row.url"') === 1
  && countOf(html, 'pasteRepoUrl(row)') === 1
  && countOf(html, 'removeRepoRow(ri)') === 1
  && countOf(html, '#i-delete') >= 1
  && countOf(html, '#i-add') >= 1);
record('① 下方有加号按钮新增一组',
  countOf(html, '@click="addRepoRow"') === 1);
/* ⚠️ 只查**真正的元素与样式规则**；注释里写着「.repo-prefix 已删、别加回来」
   是有意留的提醒（app.js:5612 / layout.css:521），所以不能对整份文件做字符串否定。 */
record('① 旧的前缀提示 UI 没被加回来（模板里没有该元素、样式表里没有该规则）',
  html.indexOf('class="repo-prefix') < 0 && html.indexOf('class="repo-preview') < 0
  && !/\.repo-prefix\s*\{/.test(css) && !/\.repo-preview\s*\{/.test(css));
record('① CSS 有垃圾桶按钮与加号行的样式',
  css.indexOf('.repo-del-btn') >= 0 && css.indexOf('.repo-add-row') >= 0);
record('① app.js 有多组仓库助手（新增 / 删除 / 落盘 / 读回）',
  app.indexOf('function addRepoRow()') > 0 && app.indexOf('function removeRepoRow(index)') > 0
  && app.indexOf('function reposForEntry()') > 0 && app.indexOf('function loadReposFromRaw(raw)') > 0);
record('① 行数上限 20 与后端一致',
  /const REPOS_MAX_ROWS = 20;/.test(app), { m: app.match(/REPOS_MAX_ROWS = \d+/) ? app.match(/REPOS_MAX_ROWS = \d+/)[0] : null });
record('① buildEntry 同时写 repos 与 github（github = 第一组 = 主仓库）',
  app.indexOf('entry.repos = repos;') > 0 && app.indexOf('entry.github = repos[0].url;') > 0);
record('① 字段顺序里 repos 排在 github 之后',
  /'github', 'repos'/.test(app));

/* ========================= jsdom 启动 ========================= */
function cutInlineScript(src, marker) {
  let at = src.indexOf(marker);
  let guard = 0;
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
  vc.on('jsdomError', () => {});
  let page = await (await fetch(BASE + '/?page=maker&auditfile=repos_probe')).text();
  page = cutInlineScript(page, 'js/vendor/tailwind.js');
  page = cutInlineScript(page, 'tailwind.config');
  const dom = new JSDOM(page, {
    url: BASE + '/?page=maker&auditfile=repos_probe',
    runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(window) {
      window.fetch = (input, init) => fetch(new URL(String(input), BASE), init);
      window.Response = Response; window.Request = Request; window.Headers = Headers;
      window.Element.prototype.getBoundingClientRect = () => ({
        x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 100, height: 32, toJSON() {},
      });
    },
  });
  const win = dom.window;
  const t0 = Date.now();
  while (!win.__TOOLSGCP_APP__ && Date.now() - t0 < 25000) await sleep(100);
  if (!win.__TOOLSGCP_APP__) throw new Error('app 未挂载');
  const vm = win.__TOOLSGCP_APP__;
  vm.page = 'maker';
  vm.activeSection = 'form';
  const t1 = Date.now();
  while (!win.document.querySelector('.repo-row') && Date.now() - t1 < 15000) await sleep(80);
  if (!win.document.querySelector('.repo-row')) throw new Error('开源仓库行没渲染');
  return { win, vm };
}
async function bootRetry() {
  let last = null;
  for (let i = 0; i < 5; i += 1) {
    try { return await boot(); } catch (e) { last = e; await sleep(1500); }
  }
  throw last;
}
const { win, vm } = await bootRetry();
await sleep(400);
const doc = () => win.document;

/* 语言无关的确认弹窗点击（清空表单要确认）。
 * ⚠️ 必须**先等 vm.dialog.open === true**再去找按钮，而且要取**最后一个** .modal-backdrop：
 *   弹窗被 <transition name="modal"> 包着，jsdom 里 leave 动画不推进 ⇒ 上一轮弹窗的
 *   遮罩会赖在 DOM 里。直接 querySelectorAll('.modal-backdrop button')[0] 有可能点到
 *   **旧弹窗**的按钮（那次的 dialog.resolve 已经是 null，点了什么也不会发生）——
 *   表现就是「点了清空但表单没清空」的偶发假失败。 */
async function clickConfirm() {
  for (let i = 0; i < 120; i += 1) {
    if (vm.dialog && vm.dialog.open) {
      const backdrops = Array.from(doc().querySelectorAll('.modal-backdrop'));
      const bd = backdrops[backdrops.length - 1];
      if (bd) {
        const btns = Array.from(bd.querySelectorAll('button'));
        /* 确认按钮 = dialog.buttons 的最后一项（语言无关：取状态，不取文案） */
        const want = String((vm.dialog.buttons || [])[(vm.dialog.buttons || []).length - 1] || '');
        const btn = btns.find((b) => /danger/.test(String(b.className)))
          || btns.find((b) => b.textContent.trim() === want)
          || btns[btns.length - 1];
        if (btn) {
          btn.click();
          for (let j = 0; j < 100; j += 1) {
            if (!(vm.dialog && vm.dialog.open)) return;
            await sleep(50);
          }
          throw new Error('点了确认但弹窗仍开着');
        }
      }
    }
    await sleep(50);
  }
  throw new Error('确认弹窗没出现');
}

/* ========================= ① 加号 / 垃圾桶 ========================= */
record('① 初始只有一组仓库', vm.maker.repos.length === 1, { n: vm.maker.repos.length });
vm.addRepoRow(); await sleep(120);
record('① 点加号后变成两组', vm.maker.repos.length === 2, { n: vm.maker.repos.length });
record('① 模板里真的渲染出两行 .repo-row',
  doc().querySelectorAll('.repo-row').length === 2,
  { dom: doc().querySelectorAll('.repo-row').length });
record('① 每行都有垃圾桶删除按钮',
  doc().querySelectorAll('.repo-del-btn').length === 2,
  { dom: doc().querySelectorAll('.repo-del-btn').length });

/* 删除中间一行：按内容删，不按下标（Vue :key 用自增 _key，删中间行不会串行） */
vm.maker.repos[0].url = 'https://github.com/first/one';
vm.maker.repos[1].url = 'https://gitee.com/second/two';
await sleep(120);
vm.removeRepoRow(0); await sleep(120);
record('① 垃圾桶删掉第一组后剩一组，且内容是第二组（没串行）',
  vm.maker.repos.length === 1 && vm.maker.repos[0].url === 'https://gitee.com/second/two',
  { rows: JSON.parse(JSON.stringify(vm.maker.repos)) });

/* ========================= ② 粘贴 ========================= */
win.__MOCK_CLIPBOARD__ = 'https://gitee.com/paste/one';
vm.addRepoRow(); await sleep(120);
await vm.pasteRepoUrl(vm.maker.repos[1]);
await sleep(200);
record('② 粘贴按钮把剪贴板链接填进**这一行**',
  vm.maker.repos[1].url === 'https://gitee.com/paste/one',
  { url: vm.maker.repos[1].url });
record('② 粘的是 Gitee 链接 ⇒ 这一行平台自动切到 Gitee',
  vm.maker.repos[1].platform === 'gitee', { platform: vm.maker.repos[1].platform });

/* 剪贴板里没有链接 ⇒ 给粘贴失败提示 */
win.__MOCK_CLIPBOARD__ = '';
const toastBefore = (vm.toasts || []).length;
await vm.pasteRepoUrl(vm.maker.repos[1]);
await sleep(200);
record('② 剪贴板没有链接 ⇒ 弹了提示（不是静默）',
  (vm.toasts || []).length > toastBefore,
  { toasts: (vm.toasts || []).map((t) => t.message) });

/* owner/repo 形态也能粘 */
win.__MOCK_CLIPBOARD__ = 'someone/somerepo';
await vm.pasteRepoUrl(vm.maker.repos[1]);
await sleep(200);
record('② 只复制了 owner/repo 形态也能贴进来',
  vm.maker.repos[1].url === 'someone/somerepo', { url: vm.maker.repos[1].url });

/* ========================= ③ 落盘形态 ========================= */
vm.maker.repos[0].platform = 'github';
vm.maker.repos[0].url = 'owner/repo';
vm.maker.repos[1].platform = 'gitee';
vm.maker.repos[1].url = 'https://gitee.com/paste/one';
await sleep(120);
const entry = vm.buildEntry();
record('③ 落盘 repos 是 list[{platform,url}]，且平台各自保留',
  Array.isArray(entry.repos) && entry.repos.length === 2
  && entry.repos[0].platform === 'github' && entry.repos[1].platform === 'gitee',
  { repos: entry.repos });
record('③ github 字段 = 第一组（主仓库），前缀已补全',
  entry.github === 'https://github.com/owner/repo', { github: entry.github });
record('③ 第一组的 owner/repo 也补了平台前缀',
  entry.repos[0].url === 'https://github.com/owner/repo', { u: entry.repos[0].url });
record('③ 空地址的组不落盘（「不开源」那组不算）',
  !entry.repos.some((r) => !r.url), { repos: entry.repos });

/* 「不开源」那一组整个不算数 */
vm.maker.repos.push({ _key: 9999, platform: 'none', url: 'https://x/y' });
await sleep(120);
const entry2 = vm.buildEntry();
record('③ 平台选「不开源」的组不落盘',
  entry2.repos.length === 2 && !entry2.repos.some((r) => r.platform === 'none'),
  { repos: entry2.repos });
vm.maker.repos.pop(); await sleep(80);

/* ========================= ④ 清空 ========================= */
vm.clearForm(); await sleep(250); await clickConfirm(); await sleep(250);
record('④ 清空表单后仓库恢复成一组空的',
  vm.maker.repos.length === 1 && vm.maker.repos[0].url === ''
  && vm.maker.repos[0].platform === 'github',
  { rows: JSON.parse(JSON.stringify(vm.maker.repos)) });

/* ========================= ⑤ 载入（老数据 + 新数据） ========================= */
let LAST_RAW = null;
win.pywebview.api.resources.detail = async () => ({ ok: true, item: LAST_RAW });
async function loadInto(raw) {
  LAST_RAW = raw;
  vm.clearForm(); await sleep(220); await clickConfirm(); await sleep(200);
  await vm.editExistingEntry({ code: raw.code, id: raw.id });
  await sleep(300);
}
await loadInto({
  code: 'TG-LEGACY', id: 'TG-LEGACY', name: '老数据',
  github: 'https://github.com/legacy/one',
});
record('⑤ 老数据只有 github 一条 ⇒ 载入后自动变成一组（平台由前缀推断）',
  vm.maker.repos.length === 1 && vm.maker.repos[0].url === 'https://github.com/legacy/one'
  && vm.maker.repos[0].platform === 'github',
  { rows: JSON.parse(JSON.stringify(vm.maker.repos)) });

await loadInto({
  code: 'TG-MULTI', id: 'TG-MULTI', name: '多组',
  github: 'https://github.com/a/one',
  repos: [
    { platform: 'github', url: 'https://github.com/a/one' },
    { platform: 'gitlab', url: 'https://gitlab.com/b/two' },
  ],
});
record('⑤ 新数据按 repos 还原每一组（两行，平台各自保留）',
  vm.maker.repos.length === 2 && vm.maker.repos[1].platform === 'gitlab'
  && vm.maker.repos[1].url === 'https://gitlab.com/b/two',
  { rows: JSON.parse(JSON.stringify(vm.maker.repos)) });
record('⑤ 载入后再落盘是同一份（往返无损）',
  JSON.stringify(vm.buildEntry().repos) === JSON.stringify([
    { platform: 'github', url: 'https://github.com/a/one' },
    { platform: 'gitlab', url: 'https://gitlab.com/b/two' },
  ]), { repos: vm.buildEntry().repos });

/* ========================= ⑥ 详情 / 列表显示 ========================= */
const rows = vm.repoRowsFor({ repos: [
  { platform: 'github', url: 'https://github.com/a/one' },
  { platform: 'gitee', url: 'https://gitee.com/b/two' },
] });
record('⑥ 详情页逐行列出多组仓库', rows.length === 2, { rows });
record('⑥ 老数据（只有 github）详情页仍显示一行',
  vm.repoRowsFor({ github: 'https://github.com/legacy/one' }).length === 1);
record('⑥ 列表那一列多组显示「第一组 +N」',
  vm.repoListText({ repos: [
    { platform: 'github', url: 'https://github.com/a/one' },
    { platform: 'gitee', url: 'https://gitee.com/b/two' },
  ] }) === 'https://github.com/a/one +1',
  { text: vm.repoListText({ repos: [
    { platform: 'github', url: 'https://github.com/a/one' },
    { platform: 'gitee', url: 'https://gitee.com/b/two' },
  ] }) });
record('⑥ 悬停提示给出全部组',
  vm.repoListTitle({ repos: [
    { platform: 'github', url: 'https://github.com/a/one' },
    { platform: 'gitee', url: 'https://gitee.com/b/two' },
  ] }).split('\n').length === 2);

/* ========================= ⑦ 逐组警告 ========================= */
vm.clearForm(); await sleep(220); await clickConfirm(); await sleep(200);
/* ⚠️ statusLine 优先显示**错误**（必填项），警告排在后面 —— 先把必填项填上，
   否则状态行只报「名称/标识必填」，仓库那条警告根本轮不到显示（探针自身的坑）。 */
vm.maker.name = '测试工具';
vm.maker.id = 'probe-repos';
await sleep(150);
/* ⚠️ 第一组默认是空的 —— 它**本来就应该**被点名（第 1 组留空了）。
   所以不误报的判据要写成「第 1 组不出声」而不是「整句都不出现」。
   另外平台必须选 custom：github 平台下 normalizeRepoUrl 会把 'notaurl'
   补成 https://github.com/notaurl，本来就是 http，压根不构成问题。 */
vm.maker.repos[0].url = 'https://github.com/ok/one';
vm.maker.repos.push({ _key: 8888, platform: 'custom', url: 'notaurl' });
await sleep(200);
const warns = vm.statusLine || '';
record('⑦ 非法地址那一组被点名（且能看出是第 2 组）',
  /第 2 组开源仓库地址不是/.test(String(warns)), { warns });
record('⑦ 合法地址那一组不误报',
  !/第 1 组开源仓库地址不是/.test(String(warns))
  && !/第 1 组开源仓库留空/.test(String(warns)), { warns });

/* ========================= 汇总 ========================= */
const fail = results.filter((r) => !r.ok);
console.log('');
console.log((results.length - fail.length) + '/' + results.length + ' 通过');
if (fail.length) {
  console.log('失败项：');
  fail.forEach((f) => console.log('  - ' + f.name));
  process.exitCode = 1;
}
