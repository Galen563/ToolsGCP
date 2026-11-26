/* jsdom 探针：第四轮 task-13 的四项前端契约
 *   ① 投稿页滚动记忆：宽屏 / 窄屏两套布局都要记得住，四个分节各自独立
 *      （窄屏 bug 本体：1128px 断点把滚动权从 .maker-form-scroll 交给父级 .maker-body，
 *        旧实现按文档顺序取第一个 ⇒ 量到的永远是 0，"切走再切回"就掉回顶端）
 *   ② 「更多筛选」候选跟随界面语言：切语言要重拉一次 filter_options（并把语言传给后端）
 *   ④ 读侧：纯字符串的 name/description 要摊给三个分段（以前只灌简体中文）
 *      + 灌池必须优先取 *_i18n 原始形态，不能取被后端压平成"当前界面语言那份"的 category/tags
 *   ⑤ 预览卡三项（名称 / 简介 / 标签）跟随「多语言字段」分段，而不是界面语言
 * 用法：python serve.py <port> 后 GCP_PORT=<port> node probe_task13_maker_ui.mjs
 * ⚠️ 三个环境垫片（都是 jsdom 的限制，不是产品问题）：
 *   1) 滚动尺寸：jsdom 没有布局引擎 ⇒ scrollHeight/clientHeight 恒为 0、写 scrollTop 被静默丢掉；
 *      而且四个分节是 v-if 重建的 ⇒ 桩必须挂在**原型**上（逐元素 defineProperty 一换分节就没了）。
 *   2) getComputedStyle：jsdom 不解析 layout.css ⇒ overflowY 恒为空串，canScrollY 会把所有容器
 *      判成"滚不动"。这里按 class 映射表只覆盖 overflowY，其余属性透传真实现
 *      （Vue 的 transition 要读 duration，不能整体造假）。
 *   3) 页面 transition 的 @after-enter 在无头环境不一定触发 ⇒ 轮询不到恢复结果时手动补一次
 *      vm.onPageAfterEnter()（真实 WebView2 里这一步由浏览器驱动），并在汇总里报补拍次数。
 */
import { JSDOM, VirtualConsole } from 'jsdom';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const PORT = process.env.GCP_PORT || '8899';
const BASE = 'http://127.0.0.1:' + PORT;
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const results = [];
function record(name, ok, detail) {
  results.push({ name, ok });
  console.log((ok ? 'PASS' : 'FAIL') + '  ' + name
    + (detail !== undefined ? '  ' + JSON.stringify(detail) : ''));
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms, step) {
  const t0 = Date.now();
  for (;;) {
    let v = null;
    try { v = fn(); } catch (e) { v = null; }
    if (v) return v;
    if (Date.now() - t0 > (ms || 4000)) return null;
    await sleep(step || 60);
  }
}

/* ========================= 静态契约：先把"前提"钉住 ========================= */
const html = await fs.readFile(path.join(ROOT, '.ToolsGCP/webui/index.html'), 'utf8');
const css = await fs.readFile(path.join(ROOT, '.ToolsGCP/webui/css/layout.css'), 'utf8');
const app = await fs.readFile(path.join(ROOT, '.ToolsGCP/webui/js/app.js'), 'utf8');
const countOf = (src, needle) => src.split(needle).length - 1;

const KEY_FORM = 'data-scroll-key="maker:form"';
const keyHits = {
  form: countOf(html, KEY_FORM),
  browser: countOf(html, 'data-scroll-key="maker:browser"'),
  batch: countOf(html, 'data-scroll-key="maker:batch"'),
  help: countOf(html, 'data-scroll-key="maker:help"'),
};
record('① 四个分节都有 data-scroll-key（表单那对宽窄容器共用一个 key = 2）',
  keyHits.form === 2 && keyHits.browser === 1 && keyHits.batch === 1 && keyHits.help === 1, keyHits);
/* 窄屏媒体查询是本需求的前提；它要是被改掉了，本探针的映射表就得同步改 */
const mqAt = css.indexOf('@media (max-width: 1128px)');
const mq = mqAt < 0 ? '' : css.slice(mqAt, mqAt + 1400);
record('① 1128px 断点仍把滚动权交给 .maker-body、收掉 .maker-form-scroll（改动依据未失效）',
  mq.indexOf('.maker-body') >= 0 && mq.indexOf('overflow-y: auto') >= 0
  && mq.indexOf('.maker-form-scroll') >= 0 && mq.indexOf('overflow: visible') >= 0,
  { mqAt });
const formRuleAt = css.indexOf('.maker-form-scroll');
const secRuleAt = css.indexOf('.maker-section-scroll');
record('① 宽屏那两个默认滚动容器仍是 overflow-y:auto（不是被别处改成 hidden）',
  css.slice(formRuleAt, formRuleAt + 200).indexOf('overflow-y: auto') >= 0
  && css.slice(secRuleAt, secRuleAt + 200).indexOf('overflow-y: auto') >= 0);
record('① 选择器同时认"正在滚的那个"和"有溢出的那个"（宽窄两套布局共用一个 key 才不串）',
  app.indexOf('function canScrollY') > 0 && app.indexOf('scrollMemoryKey') > 0
  && app.indexOf('return scrolled || tall || first') > 0);
record('① 换分节也记 / 也恢复（v-if 会销毁旧容器，必须显式带上旧 / 新分节名）',
  app.indexOf("rememberPageScroll('maker:' + old)") > 0
  && app.indexOf("restorePageScroll('maker:' + key)") > 0);
record('④ 灌池优先取 *_i18n（后端 detail 把 category/tags 压平成界面语言那一份）',
  app.indexOf('raw.category_i18n != null ? raw.category_i18n : raw.category') > 0
  && app.indexOf('raw.tags_i18n != null ? raw.tags_i18n : raw.tags') > 0);
record('④ langTextOf 对标量 / 数组走 flattenText（"三语同名"回填的读侧那一半）',
  app.indexOf("if (typeof dict !== 'object' || Array.isArray(dict)) return flattenText(dict);") > 0
  && app.indexOf("maker.i18n[lang].name = langTextOf(rawName, lang);") > 0);
record('⑤ 预览三项统一走分段回退链，标签用该分段的译名',
  app.indexOf('previewFallbackOrder') > 0 && app.indexOf('pickBySegment') > 0
  && app.indexOf('termIn(seg, tag)') > 0 && app.indexOf('const seg = makerSegLang.value;') > 0);
const bootAt = app.indexOf('await loadFilterOptions()');
const changeAt = app.indexOf('async function changeLanguage');
record('② 候选重拉函数存在且把界面语言当参数传给后端',
  bootAt > 0 && app.indexOf("bridge.tryCall('resources.filter_options', uiLanguage())") > 0);
record('② 启动与切语言两条路都调了它（changeLanguage 之后那一次是关键）',
  changeAt > 0 && app.indexOf('await loadFilterOptions()', changeAt) > changeAt, { bootAt, changeAt });

/* ========================= jsdom 垫片 ========================= */
const layoutMode = { narrow: false };
/* 精确删掉包含 marker 的那段内联 / 外链 <script>（只用 indexOf，避免正则跨标签误伤） */
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
  let page = await (await fetch(BASE + '/?page=maker&auditfile=task13_probe')).text();
  page = cutInlineScript(page, 'js/vendor/tailwind.js');
  page = cutInlineScript(page, 'tailwind.config');
  const dom = new JSDOM(page, {
    url: BASE + '/?page=maker&auditfile=task13_probe',
    runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(window) {
      window.fetch = (input, init) => fetch(new URL(String(input), BASE), init);
      window.Response = Response; window.Request = Request; window.Headers = Headers;
      window.Element.prototype.getBoundingClientRect = () => ({
        x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 100, height: 32, toJSON() {},
      });
      /* 垫片 1：滚动尺寸挂在原型上（v-if 重建也不丢）；写入按 maxScroll 夹紧，与浏览器一致，
         免得把"环境量不出真实溢出"误报成产品 bug。 */
      [window.Element.prototype, window.HTMLElement.prototype].forEach((proto) => {
        Object.defineProperty(proto, 'scrollTop', {
          configurable: true,
          get() { return this.__st || 0; },
          set(v) {
            const max = Math.max(0, (this.scrollHeight || 0) - (this.clientHeight || 0));
            this.__st = Math.max(0, Math.min(Number(v) || 0, max));
          },
        });
        Object.defineProperty(proto, 'scrollHeight', {
          configurable: true,
          get() { return this.__sh === undefined ? 5000 : this.__sh; },
          set(v) { this.__sh = Number(v) || 0; },
        });
        Object.defineProperty(proto, 'clientHeight', {
          configurable: true,
          get() { return this.__ch === undefined ? 600 : this.__ch; },
          set(v) { this.__ch = Number(v) || 0; },
        });
      });
      /* 垫片 2：只覆盖 overflowY（映射表按 layout.css 的真实规则抄），其它属性透传 */
      const realCS = window.getComputedStyle.bind(window);
      const RULES = [
        { sel: '.maker-body', wide: 'hidden', narrow: 'auto' },
        { sel: '.maker-form-scroll', wide: 'auto', narrow: 'visible' },
        { sel: '.maker-section-scroll', wide: 'auto', narrow: 'auto' },
      ];
      window.getComputedStyle = (el, pseudo) => {
        const cs = realCS(el, pseudo);
        if (el && el.matches) {
          for (const r of RULES) {
            if (!el.matches(r.sel)) continue;
            const val = layoutMode.narrow ? r.narrow : r.wide;
            return new Proxy(cs, {
              get(t, p) {
                if (p === 'overflowY' || p === 'overflow-y') return val;
                const v = Reflect.get(t, p);
                return typeof v === 'function' ? v.bind(t) : v;
              },
            });
          }
        }
        return cs;
      };
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
  return { win, vm };
}
/* serve.py 正被队友并发写时会吐回半截文件 ⇒ 重试，别把环境问题报成断言失败 */
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
const byKey = (k) => doc().querySelector('[data-scroll-key="' + k + '"]');
const formEl = () => doc().querySelector('.maker-form-scroll');
const bodyEl = () => doc().querySelector('.maker-body');
let nudged = 0;
function clickConfirm(label) {
  const btn = Array.from(doc().querySelectorAll('.modal-backdrop button'))
    .find((b) => b.textContent.trim() === label);
  if (btn) { btn.click(); return true; }
  return false;
}
/** 切页：走真实导航入口 doGoto(key)（它自己会 rememberPageScroll），轮询等页面 / 容器落定；
    无头环境里 Vue 不一定触发 @after-enter，到位后补拍一次（垫片 3）。
    过渡是 mode="out-in"，实测 jsdom 里挂新页面可能要一两秒，所以是轮询不是固定 sleep。 */
async function gotoPage(key, wantSel) {
  vm.doGoto(key);
  for (let i = 0; i < 60; i += 1) {
    await sleep(100);
    if (vm.page === key && (!wantSel || doc().querySelector(wantSel))) break;
  }
  if (vm.onPageAfterEnter) { nudged += 1; vm.onPageAfterEnter(); await sleep(120); }
}
async function switchSection(key) {
  vm.activeSection = key;
  await until(() => byKey('maker:' + key), 2000);
  await sleep(200);                      // watch 里那次 nextTick 恢复
}

/* ========================= ① 滚动记忆 ========================= */
layoutMode.narrow = false;
if (bodyEl()) bodyEl().scrollTop = 0;
if (formEl()) formEl().scrollTop = 800;
await sleep(80);
record('① 宽屏：位置写进 .maker-form-scroll（垫片 1 生效，800 读得回来）',
  formEl().scrollTop === 800, { got: formEl().scrollTop });
await gotoPage('search');
await gotoPage('maker', '.maker-form-scroll');
record('① 宽屏：切到搜索页再切回投稿页，表单仍是 800（不是掉回顶端）',
  !!formEl() && formEl().scrollTop === 800, { got: formEl() && formEl().scrollTop });
record('① 宽屏：恢复落在 .maker-form-scroll 上，父级 .maker-body 保持 0（没选错容器）',
  !!bodyEl() && bodyEl().scrollTop === 0, { body: bodyEl() && bodyEl().scrollTop });

/* 窄屏：滚动权在 .maker-body —— 用户报的那条 bug 本体 */
layoutMode.narrow = true;
if (formEl()) formEl().scrollTop = 0;
if (bodyEl()) bodyEl().scrollTop = 550;
await sleep(80);
await gotoPage('search');
await gotoPage('maker', '.maker-body');
if (bodyEl().scrollTop !== 550 && vm.onPageAfterEnter) { nudged += 1; vm.onPageAfterEnter(); await sleep(300); }
record('① 窄屏：滚动容器换成 .maker-body 后也要记得住 550（本轮修的 bug）',
  bodyEl().scrollTop === 550, { body: bodyEl().scrollTop, form: formEl() && formEl().scrollTop });
record('① 窄屏：记忆没被写到"滚不动"的 .maker-form-scroll 上（canScrollY 在起作用）',
  !formEl() || formEl().scrollTop === 0, { form: formEl() && formEl().scrollTop });
layoutMode.narrow = false;

/* 分节之间互不覆盖 + 换分节也会恢复 */
await switchSection('form');
if (formEl()) formEl().scrollTop = 700;
await sleep(60);
await switchSection('batch');
const batchEl = byKey('maker:batch');
record('① 切到「批量合成」：它自己的容器从 0 开始（没被表单位置污染），旧容器已销毁',
  !!batchEl && batchEl.scrollTop === 0 && formEl() === null,
  { batch: batchEl && batchEl.scrollTop, formAlive: formEl() !== null });
if (batchEl) batchEl.scrollTop = 200;
await switchSection('help');
await switchSection('batch');
record('① 换分节也会恢复：批量合成回到它自己的 200',
  byKey('maker:batch').scrollTop === 200, { batch: byKey('maker:batch').scrollTop });
await switchSection('form');
record('① 分节记忆互不覆盖：表单仍是 700（没被批量的 200 冲掉）',
  formEl() && formEl().scrollTop === 700, { form: formEl() && formEl().scrollTop });
await switchSection('browser');
await sleep(300);
await switchSection('form');
record('① 经资源浏览（它自己那套 browserScrollTop）绕一圈，表单位置不丢',
  formEl().scrollTop === 700, { form: formEl().scrollTop });
await gotoPage('search');
await gotoPage('maker', '.maker-form-scroll');
record('① 停在表单分节时切页再切回，同样按分节 key 恢复',
  formEl().scrollTop === 700, { form: formEl().scrollTop });

/* ========================= ⑤ 预览跟随分段 ========================= */
vm.clearForm(); await sleep(250); clickConfirm('清空'); await sleep(250);
vm.i18nEnabled = true;
vm.maker.i18n['简体中文'].name = '测试工具';
vm.maker.i18n['繁體中文'].name = '測試工具';
vm.maker.i18n['English'].name = 'TestTool';
vm.maker.i18n['简体中文'].description = '简体中文的一段简介';
vm.maker.i18n['繁體中文'].description = '繁體中文的一段簡介';
vm.maker.i18n['English'].description = 'English description here';
vm.maker.tags = { '简体中文': '', '繁體中文': '', 'English': '工具' };
vm.i18nLangIndex = 0; await sleep(200);
const pZh = { name: vm.previewName, desc: vm.previewDesc, tags: vm.previewTagList.slice() };
vm.i18nLangIndex = 2; await sleep(200);
const pEn = { name: vm.previewName, desc: vm.previewDesc, tags: vm.previewTagList.slice() };
record('⑤ 分段=简体中文：预览名称 / 简介取简体那一份',
  pZh.name === '测试工具' && pZh.desc === '简体中文的一段简介', { pZh });
record('⑤ 分段切到 English：预览名称 / 简介立刻跟着换（本轮需求⑤）',
  pEn.name === 'TestTool' && pEn.desc === 'English description here', { pEn });
record('⑤ 预览标签用当前分段的译名（English 分段出 [Tools]）',
  pEn.tags.length === 1 && pEn.tags[0] === '[Tools]', { tags: pEn.tags });
vm.maker.i18n['English'].name = '';
vm.maker.i18n['English'].description = '';
await sleep(200);
record('⑤ 当前分段没填时按回退链兜住（不空白，顺序：分段 → 简体 → 繁体）',
  vm.previewName === '测试工具' && vm.previewDesc === '简体中文的一段简介',
  { name: vm.previewName, desc: vm.previewDesc });
vm.i18nLangIndex = 1;
vm.maker.tags = { '简体中文': '工具', '繁體中文': '', 'English': '' };
await sleep(200);
record('⑤ 分段=繁體且该池为空 ⇒ 标签回退到非空那份（不是空白）',
  vm.previewTagList.length === 1, { tags: vm.previewTagList });
vm.i18nLangIndex = 0; await sleep(150);

/* ========================= ④ 读侧：灌池来源 + 三语同名回填 ========================= */
let LAST_RAW = null;
win.pywebview.api.resources.detail = async () => ({ ok: true, item: LAST_RAW });
async function loadInto(raw, code) {
  LAST_RAW = raw;
  vm.clearForm(); await sleep(220); clickConfirm('清空'); await sleep(200);
  await vm.editExistingEntry({ code: code || 'TG-PROBE1', name: 'probe' });
  await sleep(260);
}
/* D1/D2：磁盘只有一份（纯字符串）⇒ 三个分段都看得见，且名称继续跟随 */
await loadInto({
  code: 'TG-PROBE1', id: 'TG-PROBE1', name: 'OnlyOneName', description: '只有一份的简介',
  intro: '只有一份的介绍', supplement: '只有一份的补充',
  category: ['工具'], tags: ['办公'], systems: ['Windows'],
}, 'TG-PROBE1');
const bag = (key) => ['简体中文', '繁體中文', 'English'].map((l) => vm.maker.i18n[l][key]);
record('④ 磁盘只有一份 name（纯字符串）⇒ 三个分段都回填同一份（不再只有简体中文）',
  bag('name').every((v) => v === 'OnlyOneName'), { bag: bag('name') });
record('④ description / intro / supplement 同样三语摊平',
  bag('description').every((v) => v === '只有一份的简介')
  && bag('intro').every((v) => v === '只有一份的介绍')
  && bag('supplement').every((v) => v === '只有一份的补充'), { desc: bag('description') });
record('④ 三语同名 ⇒ 名称仍跟随上方规范名（不被踢成手动）',
  vm.maker._nameAuto === true && vm.maker.name === 'OnlyOneName',
  { auto: vm.maker._nameAuto, name: vm.maker.name });
record('④ 老数据（无 *_i18n）：类别 / 标签三池同值，观感与改动前一致（零迁移）',
  vm.maker.category['简体中文'] === '工具' && vm.maker.category['English'] === '工具'
  && vm.maker.tags['English'] === '办公' && vm.maker.tags['繁體中文'] === '办公',
  { cat: vm.maker.category, tags: vm.maker.tags });
/* D4：后端 detail 把 category/tags 压平成界面语言那份 ⇒ 必须优先吃 *_i18n */
await loadInto({
  code: 'TG-PROBE2', id: 'TG-PROBE2',
  name: { '简体中文': '甲', '繁體中文': '甲', 'English': 'B' },
  category: ['Tools', 'in-house'],          // 后端出口那份（English 界面压平的结果）
  category_i18n: {
    '简体中文': ['工具', '自研工具'],        // 规范中文只在这里
    '繁體中文': ['工具', '自研工具'],
    'English': ['Tools', 'in-house'],
  },
  tags: ['Beta'],
  tags_i18n: { '简体中文': ['测试版'], '繁體中文': ['測試版'], 'English': ['Beta'] },
}, 'TG-PROBE2');
record('④ 灌池取 category_i18n 而非被压平的 category（简体池必须是规范中文）',
  vm.maker.category['简体中文'] === '工具, 自研工具',
  { zh: vm.maker.category['简体中文'], en: vm.maker.category['English'] });
/* 池子保持输入的原始顺序（规范值在前、自定义在后），与改动前的 poolsFromRaw 一致：
   ["Tools","in-house"] ⇒ canonicalTerm 把 Tools 还原成「工具」，in-house 认不出来 ⇒ 原样留着。 */
record('④ 英文写法还原成规范值、自定义值原样保留（canonicalTerm 口径不变）',
  vm.maker.category['English'] === '工具, in-house', { en: vm.maker.category['English'] });
record('④ 标签同理：各分段灌自己那一份',
  vm.maker.tags['简体中文'] === '测试版' && vm.maker.tags['繁體中文'] === '測試版',
  { tags: vm.maker.tags });
record('④ 名称是"各语言写法不同"的字典 ⇒ 退出跟随（不覆盖作者分好的多语言名）',
  vm.maker._nameAuto === false, { auto: vm.maker._nameAuto });
vm.clearForm(); await sleep(220); clickConfirm('清空'); await sleep(200);

/* ========================= ② 候选跟随界面语言 ========================= */
const filterCalls = [];
win.pywebview.api.resources.filter_options = async (language) => {
  filterCalls.push(String(language));
  const en = language === 'English';
  return {
    ok: true,
    category: [{ value: '工具', label: en ? 'Tools' : '工具' }, { value: '网络', label: en ? 'Network' : '网络' }],
    tag: [{ value: '办公', label: en ? 'Office' : '办公' }],
    system: [{ value: 'Windows', label: 'Windows' }],
  };
};
const langRow = (vm.sections || []).reduce((acc, sec) => {
  (sec.cards || []).forEach((card) => card.forEach((row) => { if (row.key === 'language') acc = acc || row; }));
  return acc;
}, null);
record('② 找到设置里的语言行（真实切换入口）', !!langRow, { found: !!langRow });
const rowOf = (key) => (vm.filterRows || []).find((r) => r.key === key) || { options: [] };
if (langRow) {
  vm.onRowChange(langRow, 'English');
  await sleep(1500);                       // queue + bundle 拉取 + 资源重载 + 候选重拉
  record('② 切语言确实重拉了候选，并把语言传给后端',
    filterCalls.indexOf('English') >= 0, { filterCalls });
  record('② 「更多筛选」类别候选变英文译名（value 仍是规范中文）',
    rowOf('category').options.some((o) => o.label === 'Tools' && o.value === '工具'),
    { options: rowOf('category').options });
  record('② 标签候选一起翻（办公 → Office）',
    rowOf('tag').options.some((o) => o.label === 'Office' && o.value === '办公'),
    { options: rowOf('tag').options });
  record('② 切语言后分段照旧落到界面语言（上一轮那条契约没被破坏）',
    vm.settings.language === 'English' && vm.i18nLangIndex === 2,
    { language: vm.settings.language, idx: vm.i18nLangIndex });
  vm.onRowChange(langRow, '简体中文');
  await sleep(1500);
  record('② 切回简体中文：参数换回简体中文、候选 label 也换回中文',
    filterCalls.lastIndexOf('简体中文') > filterCalls.lastIndexOf('English')
    && rowOf('category').options.some((o) => o.label === '工具'),
    { filterCalls, options: rowOf('category').options });
}

/* ========================= 汇总 ========================= */
const fail = results.filter((r) => !r.ok);
console.log('');
console.log((results.length - fail.length) + '/' + results.length + ' 通过'
  + '（垫片 3 补拍 @after-enter ' + nudged + ' 次）');
if (fail.length) {
  console.log('失败项：');
  fail.forEach((f) => console.log('  - ' + f.name));
  process.exitCode = 1;
}
