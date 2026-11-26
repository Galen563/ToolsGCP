/* jsdom 探针：提交软件·类别下拉**最底下**追加的「官方」「知名」（第三轮需求 ③）。
 * 验证点：
 *   ① 候选列表最后两项就是「官方」「知名」，且顺序在 31 个内置类别之后；
 *   ② 三种语言分段下，这两项显示的是该语言的译名（Official / Popular）；
 *   ③ 手动输入「官方」「知名」（以及它们的英文写法）会被还原成规范值（内置项）；
 *   ④ 落盘形态：选了「知名」后能正常存进 maker.category 池；
 *   ⑤ makerCategories 本身仍��� 31 项、顺序不变（不许污染 py 侧 CATEGORIES 契约）。
 * 用法：python serve.py <port> 后 GCP_PORT=<port> node probe_category_extras.mjs
 */
import { JSDOM, VirtualConsole } from 'jsdom';

const PORT = process.env.GCP_PORT || '8899';
const BASE = `http://127.0.0.1:${PORT}`;
const results = [];
function record(name, ok, detail) {
  results.push({ name, ok });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail !== undefined ? '  ' + JSON.stringify(detail) : ''}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* 精确删掉包含 marker 的那段内联 <script>（只用 indexOf，避免正则跨标签误伤） */
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
async function boot() {
  const vc = new VirtualConsole();
  vc.on('jsdomError', () => {});
  let html = (await (await fetch(`${BASE}/?page=maker&auditfile=cat_extras_probe`)).text());
  html = html.replace(/<script src="\/static\/js\/vendor\/tailwind\.js"[\s\S]*?<\/script>/, '');
  html = cutInlineScript(html, 'tailwind.config');
  const dom = new JSDOM(html, {
    url: `${BASE}/?page=maker&auditfile=cat_extras_probe`,
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
  while (!win.document.querySelector('.maker-form-scroll') && Date.now() - t1 < 15000) await sleep(80);
  if (!win.document.querySelector('.maker-form-scroll')) throw new Error('投稿表单没渲染');
  return { dom, win, vm };
}

async function bootRetry() {
  let last = null;
  for (let i = 0; i < 5; i += 1) {
    try { return await boot(); }
    catch (e) { last = e; await sleep(500); }
  }
  throw last;
}

const { win, vm } = await bootRetry();

/* ① 候选末尾两项 */
const opts = vm.makerCategoryOptions || [];
const labels = opts.map((o) => o.label);
const tail = labels.slice(-2);
record('① 候选列表最后两项是「官方」「知名」',
  tail.length === 2 && tail[0] === '官方' && tail[1] === '知名', { tail, total: labels.length });

/* ② 三种语言分段下的译名 */
const segs = ['简体中文', '繁體中文', 'English'];
const seen = {};
for (let i = 0; i < segs.length; i += 1) {
  vm.i18nLangIndex = i;
  await sleep(60);
  const t = (vm.makerCategoryOptions || []).slice(-2).map((o) => o.label);
  seen[segs[i]] = t;
}
record('② 三种分段下末尾两项都存在（各语言自己的写法）',
  seen['简体中文'][0] === '官方' && seen['繁體中文'][0] === '官方'
  && seen['English'][0] === 'Official' && seen['English'][1] === 'Popular',
  seen);

/* ③ 手动输入还原成规范值（内置项） */
vm.i18nLangIndex = 0;
await sleep(60);
vm.makerCategoryText = '知名';
await sleep(60);
record('③ 简体分段输入「知名」→ 还原成规范值', vm.maker.category['简体中文'] === '知名',
  { pool: vm.maker.category['简体中文'] });
vm.i18nLangIndex = 2;
await sleep(60);
vm.makerCategoryText = 'Official';
await sleep(60);
record('③ English 分段输入「Official」→ 还原成规范值「官方」',
  vm.maker.category['English'] === '官方', { pool: vm.maker.category['English'] });

/* ④ 三语独立：切分段各自一份，互不覆盖 */
record('④ 三语独立：English 那份没影响简体那份',
  vm.maker.category['简体中文'] === '知名' && vm.maker.category['English'] === '官方',
  { pool: JSON.parse(JSON.stringify(vm.maker.category)) });

/* ⑤ makerCategories 仍是 31 项（不许污染 py 侧 CATEGORIES 契约） */
const cats = vm.makerCategories || [];
record('⑤ makerCategories 仍是 31 项且首项为「工具」', cats.length === 31 && cats[0] === '工具',
  { len: cats.length });

const failed = results.filter((r) => !r.ok);
console.log(`\n==== 汇总: ${results.length - failed.length}/${results.length} 通过 ====`);
process.exit(failed.length ? 1 : 0);
