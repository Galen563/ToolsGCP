/* jsdom 探针：本轮「提交软件」改动端到端验证。
 *   ① 类别 / 标签跟着「多语言字段」的语言分段切换（含下拉候选项内容）
 *   ② 手动输入的文本只要等于内置项（任一种语言的写法）→ 视为内置项、还原成规范值；自定义值原样保留
 *   ③ 开源仓库：前缀提示 UI 已删；粘贴按钮读剪贴板最近一次链接，失败不填值
 *   ④ 清空表单 / 产出类按钮 → 全清（含标签与类别，类别恢复默认）
 *   ⑤ 设置里切换界面语言后，分段显示仍正确（三语译名表随 bundle 下发）
 * 用法：python serve.py <port> 后 GCP_PORT=<port> node probe_maker_i18n.mjs
 * ⚠️ 两个环境垫片（都是 jsdom 的限制，不是产品问题）：
 *    · beforeParse 里补 window.fetch —— mock 的 i18n.bundle 用 fetch 打 /mock/i18n，
 *      jsdom 默认没有 window.fetch，不补就永远拿不到三语译名表（第一轮全 FAIL 的真因）。
 *    · 打桩 getBoundingClientRect（无布局引擎）。
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
  let html = (await (await fetch(`${BASE}/?page=maker&auditfile=maker_i18n_probe`)).text());
  html = html.replace(/<script src="\/static\/js\/vendor\/tailwind\.js"[\s\S]*?<\/script>/, '');
  html = cutInlineScript(html, 'tailwind.config');
  const dom = new JSDOM(html, {
    url: `${BASE}/?page=maker&auditfile=maker_i18n_probe`,
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

/* 队友/自己并发写 app.js、index.html 时 serve.py 会吐回半截文件 → 挂载失败，
   重试几次（与 settings_probe_jsdom.mjs 的 bootPageRetry 同一套路）。
   ⚠️ 上一轮就是没重试，把"读到半截文件"误报成断言失败。 */
async function bootRetry() {
  let last = null;
  for (let i = 0; i < 5; i += 1) {
    try { return await boot(); }
    catch (e) { last = e; await sleep(1500); }
  }
  throw last;
}
const { win, vm } = await bootRetry();
await sleep(400);

/* ================= 本轮契约：类别/标签 = 三语独立输入池 ================= */
const comboEdit = () => win.document.querySelector('.combo-trigger-editable .combo-edit');

/* ---- ① 默认态：类别三语都是内置「工具」（各显示自己的译名），标签三语全空 ---- */
/* 清空走真实入口 clearForm + 确认按钮（resetMakerForm 没导出，别用 && 短路空跑） */
vm.clearForm(); await sleep(250);
{
  const btn = Array.from(win.document.querySelectorAll('.modal-backdrop button'))
    .find((b) => b.textContent.trim() === '清空');
  if (btn) { btn.click(); await sleep(250); }
}
vm.i18nLangIndex = 0; await sleep(150);
const defZh = { cat: vm.makerCategoryText, tags: vm.makerTagsText };
vm.i18nLangIndex = 2; await sleep(150);
const defEn = { cat: vm.makerCategoryText, tags: vm.makerTagsText };
record('① 默认类别 = 内置「工具」，各分段显示该语言译名（工具 / Tools）',
  defZh.cat === '工具' && defEn.cat === 'Tools', { zh: defZh.cat, en: defEn.cat });
record('① 默认标签三语全空（本轮需求：默认标签输入框为空）',
  defZh.tags === '' && defEn.tags === '', { zh: JSON.stringify(defZh.tags), en: JSON.stringify(defEn.tags) });
record('① 「跟随类别」按钮已消失',
  !Array.from(win.document.querySelectorAll('button')).some((b) => /跟随类别/.test(b.textContent)),
  Array.from(win.document.querySelectorAll('.tags-row button')).map((b) => b.textContent.trim()));

/* ---- ② 三语独立：各分段填不同内容，互不覆盖 ---- */
vm.i18nLangIndex = 0; await sleep(120);
vm.makerTagsText = '工具, 系统';
vm.i18nLangIndex = 2; await sleep(120);
const enAfterZh = vm.makerTagsText;
vm.makerTagsText = 'Tools';
vm.i18nLangIndex = 1; await sleep(120);
const twAfterBoth = vm.makerTagsText;
vm.i18nLangIndex = 0; await sleep(120);
const zhStill = vm.makerTagsText;
record('② 简体中文填「工具, 系统」后切到 English：English 池不受污染（本轮修的 bug）',
  enAfterZh === '' && zhStill === '工具, 系统',
  { enAfterZh, zhStill });
record('② 三种语言各自独立：简体=工具,系统 / English=Tools / 繁體=空',
  zhStill === '工具, 系统'
  && vm.maker.tags['English'] === '工具'
  && vm.maker.tags['繁體中文'] === '',
  { pools: JSON.parse(JSON.stringify(vm.maker.tags)) });
/* 类别同理 */
vm.i18nLangIndex = 0; await sleep(120);
vm.onCategoryChanged('游戏');
vm.i18nLangIndex = 2; await sleep(120);
vm.onCategoryChanged('Tools, Network');
record('② 类别也各自独立：简体=游戏 / English=Tools, Network',
  vm.maker.category['简体中文'] === '游戏'
  && vm.maker.category['English'] === '工具, 网络'
  && vm.maker.category['繁體中文'] === '工具',
  JSON.parse(JSON.stringify(vm.maker.category)));

/* ---- ③ 内置项识别：任一种语言的写法都还原成规范值（存在各自池里） ---- */
const cases = [
  ['Tools', '工具'], ['游戏', '游戏'], ['遊戲', '游戏'], ['Games', '游戏'],
  ['Official', '官方'], ['知名', '知名'], ['我的自定义', '我的自定义'],
];
vm.i18nLangIndex = 2; await sleep(120);
const canon = cases.map(([input, want]) => {
  vm.onCategoryChanged(input);
  return { input, got: vm.maker.category['English'], want };
});
record('③ English 分段输入内置项（三种语言写法都认）还原成规范值；自定义值原样',
  canon.every((c) => c.got === c.want), canon);
vm.makerTagsText = 'Tools, Official';
await sleep(100);
record('③ 标签同样还原（Tools, Official → 存 工具, 官方）',
  vm.maker.tags['English'] === '工具, 官方', { en: vm.maker.tags['English'] });

/* ---- ④ 落盘形态：三语相同 → list[str]；不同 → 三语字典 ---- */
/* ⚠️ resetMakerForm / changeLanguage / loadResourceIntoForm 都没有导出到模板作用域，
   探针只能走真实入口：清空 = clearForm() + 点确认按钮；切语言 = onRowChange(语言行)；
   载入 = editExistingEntry（内部调 loadResourceIntoForm）。
   "vm.xxx && vm.xxx()" 这种写法在未导出时会**静默空跑**，把断言变成假绿/假红——
   第一版就栽在这里（④⑤ 状态残留）。 */
/* ⚠️ 按钮文案跟着界面语言变（切到 English 后"清空"变成 Clear），
   所以这里**不能**按文案找按钮。语言无关的做法：
   弹窗里 .btn-danger / 最后一个按钮 = 确认（取消永远在前）。text 参数只用于报错信息。 */
async function clickConfirm(text) {
  /* ⚠️ 这里必须**等条件**，不能用固定 sleep：
     ① 弹窗是 <transition> 渲染的，机器忙时 250ms 内按钮可能还没进 DOM；
     ② 确认回调里可能跨一个 bridge（mock）往返才把 dialog.open 置回 false。
     实测同一份代码连跑三次会有一次卡在"点了确认但弹窗仍开着"、
     或者更隐蔽的"清空没生效 ⇒ 池子里残留上一条的值"。
     改成轮询两个状态（最多 5s），既不放松断言也不会偶发假红。 */
  let all = [];
  for (let i = 0; i < 100; i += 1) {
    all = Array.from(win.document.querySelectorAll('.modal-backdrop button'));
    if (all.length) break;
    await sleep(50);
  }
  if (!all.length) throw new Error('确认弹窗没出现（' + text + '）');
  const btn = all.find((b) => /danger/.test(String(b.className))) || all[all.length - 1];
  btn.click();
  /* ⚠️ 不能用"DOM 里还有 .modal-backdrop"判定弹窗没关：
     它是 <transition> 包着的，leave 动画在 jsdom 里不一定推进（serve.py 顶部
     那段 fx 注释讲的就是同一件事），元素会赖在 DOM 里。
     真实状态看 vm.dialog.open —— 语言无关、动画无关。 */
  for (let i = 0; i < 100; i += 1) {
    if (!(vm.dialog && vm.dialog.open)) return;
    await sleep(50);
  }
  throw new Error('点了确认但弹窗仍开着（' + text + '）');
}
vm.clearForm(); await sleep(250); await clickConfirm('清空');
vm.i18nLangIndex = 0;
vm.maker.name = 'X'; vm.maker.id = 'x';
vm.onCategoryChanged('工具');
vm.i18nLangIndex = 1; await sleep(120); vm.onCategoryChanged('工具');
vm.i18nLangIndex = 2; await sleep(120); vm.onCategoryChanged('工具');
const sameEntry = vm.buildEntry();
record('④ 三语类别相同 → 落盘是数组（与老数据同形，不产生冗余字典）',
  JSON.stringify(sameEntry.category) === JSON.stringify(['工具']), { category: sameEntry.category });
record('④ 三语标签都空 → tags 字段不写（空可选字段不落盘）',
  sameEntry.tags === undefined, { tags: sameEntry.tags });
/* 真的分语言不同：简体一份、English 两份（注意 "Tools" 会被还原成规范值"工具"，
   所以要比的是**内容条数/集合**不同，而不是写法不同） */
vm.i18nLangIndex = 2; await sleep(120);
vm.onCategoryChanged('Tools, Network');
vm.makerTagsText = 'Official';
const diffEntry = vm.buildEntry();
record('④ 三语类别不同 → 落盘是三语字典（后端 task-4 支持该形态）',
  !!(diffEntry.category && !Array.isArray(diffEntry.category)
     && JSON.stringify(diffEntry.category['简体中文']) === JSON.stringify(['工具'])
     && JSON.stringify(diffEntry.category['English']) === JSON.stringify(['工具', '网络'])),
  { category: diffEntry.category });
record('④ 标签只有 English 非空 → 塌缩成该语言的数组（不写冗余字典）',
  JSON.stringify(diffEntry.tags) === JSON.stringify(['官方']), { tags: diffEntry.tags });

/* ---- ⑤ 载入：老形态灌三池同值、新形态各灌各的（走真实 editExistingEntry） ---- */
/* mock 的 resources.detail 按 code 返回库里那条真实条目 ⇒ 想测哪种形态，
   就把哪种形态写进 __MOCK_RESOURCES__ 再双击载入，完全走真实链路。 */
const lib = win.__MOCK_RESOURCES__;
const oldForm = { id: 'probe-old', code: 'TG-900001', name: 'ProbeOld',
  category: ['工具', '网络'], tags: ['官方'], url: 'https://x', description: 'd' };
const newForm = { id: 'probe-new', code: 'TG-900002', name: 'ProbeNew',
  category: { 简体中文: ['工具'], 繁體中文: ['工具'], English: ['工具', '网络'] },
  tags: { 简体中文: ['官方'], English: ['官方', '知名'] },
  url: 'https://y', description: 'd' };
lib.push(oldForm, newForm);
await vm.editExistingEntry({ code: 'TG-900001', id: 'probe-old' });
await sleep(400);
record('⑤ 载入老形态（数组）→ 三个池灌同一份规范值',
  vm.maker.category['简体中文'] === '工具, 网络'
  && vm.maker.category['English'] === '工具, 网络'
  && vm.maker.tags['繁體中文'] === '官方',
  { cat: JSON.parse(JSON.stringify(vm.maker.category)), tags: JSON.parse(JSON.stringify(vm.maker.tags)) });
vm.i18nLangIndex = 2; await sleep(150);
record('⑤ 老形态载入后 English 分段显示英文译名（Tools, Network）',
  vm.makerCategoryText === 'Tools, Network', { shown: vm.makerCategoryText });

await vm.editExistingEntry({ code: 'TG-900002', id: 'probe-new' });
await sleep(400);
vm.i18nLangIndex = 2; await sleep(150);
record('⑤ 载入三语字典形态 → English 池拿到自己那份（工具, 网络）',
  vm.maker.category['English'] === '工具, 网络'
  && vm.maker.category['简体中文'] === '工具',
  { pools: JSON.parse(JSON.stringify(vm.maker.category)) });
record('⑤ 字典形态里缺失的语言（繁體没写 tags）回退简体中文',
  vm.maker.tags['繁體中文'] === '官方', { tw: vm.maker.tags['繁體中文'] });
vm.i18nLangIndex = 0; await sleep(150);
record('⑤ 同一份数据切回简体分段显示自己那份（工具）—— 独立池而非翻译同一份',
  vm.makerCategoryText === '工具', { shown: vm.makerCategoryText });
/* 往返无损：载入字典形态后不改任何东西直接落盘，应该还是同样的字典 */
const roundTrip = vm.buildEntry();
record('⑤ 载入三语字典 → 原样落盘（往返无损）',
  !Array.isArray(roundTrip.category)
  && JSON.stringify(roundTrip.category['English']) === JSON.stringify(['工具', '网络'])
  && JSON.stringify(roundTrip.category['简体中文']) === JSON.stringify(['工具']),
  { category: roundTrip.category });

/* ---- ⑥ 设置里切换界面语言：真实入口 onRowChange(语言行) ---- */
const langRow = (vm.sections || []).reduce((acc, sec) => {
  (sec.cards || []).forEach((card) => card.forEach((row) => {
    if (row.key === 'language') acc = acc || row;
  }));
  return acc;
}, null);
record('⑥ 找到设置里的语言行（真实切换入口）', !!langRow, { found: !!langRow });
if (langRow) {
  vm.onRowChange(langRow, 'English');
  await sleep(1200);                       // queue + bundle 拉取 + 资源重载
  record('⑥ 界面语言已切到 English', vm.settings.language === 'English',
    { language: vm.settings.language });
  /* ⑥a 切语言后**不用先清空表单**，「多语言字段」分段 / 类别输入框 / 下拉候选
     就该立刻跟着切（用户原话：「设置切换到其他语言时，提交软件页面类别和标签
     （包括类别下拉列表）都还是简体中文」）。 */
  record('⑥a 切语言后分段立刻落到 English', vm.i18nLangIndex === 2,
    { idx: vm.i18nLangIndex, language: vm.settings.language });
  /* 断言不写死具体内容：此刻池子里可能还留着前面用例填的值（简体池「工具, 网络」），
     英文分段显示的应是它们的英文写法（"Tools, Network"），关键是**不含中文**。 */
  const catEn = String(vm.makerCategoryText || '');
  record('⑥a 类别输入框显示英文写法（不含中文）',
    catEn.length > 0 && !/[\u4e00-\u9fa5]/.test(catEn),
    { cat: catEn });
  const optSample = (vm.makerCategoryOptions || []).slice(0, 3).map((o) => o.label);
  record('⑥a 类别下拉候选内容也是英文',
    optSample.length === 3 && optSample.every((label) => label && !/[\u4e00-\u9fa5]/.test(label)),
    { options: optSample });
  vm.clearForm(); await sleep(250); await clickConfirm('清空');
  record('⑥ 切语言后清空表单：分段默认落到界面语言（English）',
    vm.i18nLangIndex === 2, { idx: vm.i18nLangIndex });
  record('⑥ 此时默认类别显示 Tools、标签仍为空',
    vm.makerCategoryText === 'Tools' && vm.makerTagsText === '',
    { cat: vm.makerCategoryText, tags: vm.makerTagsText });
  /* 切回简体中文，别影响后续断言 */
  vm.onRowChange(langRow, '简体中文'); await sleep(1000);
}

/* ---- ⑦ 预览取「界面语言那一份池」+ 回退链 ---- */
vm.i18nLangIndex = 2; await sleep(150);
vm.makerTagsText = '官方, 知名';
const previewEn = vm.previewTagList.slice();
vm.i18nLangIndex = 0; await sleep(150);
vm.makerTagsText = '';
const previewFallback = vm.previewTagList.slice();
/* 第四轮需求⑤改了口径：预览跟**多语言字段分段**，不再跟界面语言。
   这一段此刻界面是简体中文、分段是 English ⇒ 预览应显示 English 那份池的英文译名。 */
record('⑦ 预览按分段取池并用该分段译名（分段 English ⇒ [Official]）',
  previewEn.length === 2 && previewEn[0] === '[Official]', { previewEn });
record('⑦ 简体池为空时预览回退到其它语言那份（不是空白，与后端 first_text 同口径）',
  previewFallback.length === 2, { previewFallback });

/* ---- ⑦b 内置标签译名必须真的存在（漏加 term_知名 时 termIn 会**原样返回**，
       金色标签照常生效、其它断言照常通过 —— 只有这条硬断言能抓到它） ---- */
{
  const bundle = await win.pywebview.api.i18n.bundle('English');
  const t = (bundle && bundle.terms) || {};
  record('⑦b term_知名 三语齐备（en_US 必须是英文写法，不能漏键）',
    !!(t.zh_CN && t.zh_CN['\u77e5\u540d'] && t.zh_TW && t.zh_TW['\u77e5\u540d']
       && t.en_US && t.en_US['\u77e5\u540d'] && t.en_US['\u77e5\u540d'] !== '\u77e5\u540d'),
    { zh: t.zh_CN && t.zh_CN['\u77e5\u540d'], tw: t.zh_TW && t.zh_TW['\u77e5\u540d'],
      en: t.en_US && t.en_US['\u77e5\u540d'] });
   /* 第四轮需求⑤：预览跟**多语言字段分段**取池、并用**该分段**的译名。
      想断言英文写法就必须把分段切到 English（界面语言只决定卡片那一路）。
      上一版留的是"界面 English + 分段简体"却期望 [Popular] —— 那是旧口径，已过期。 */
  if (langRow) {
    vm.onRowChange(langRow, 'English'); await sleep(1200);
    vm.i18nLangIndex = 2; await sleep(150);          // 分段 = English
    vm.makerTagsText = '\u77e5\u540d';            // 输入「知名」⇒ 还原规范值后用 English 译名显示
    await sleep(150);
    const shownEn = vm.previewTagList.slice();
    record('⑦b 分段 English 时预览显示「知名」的英文译名 Popular（漏 term_知名 会抓到）',
      shownEn.includes('[Popular]') && !shownEn.some((s) => /\u77e5\u540d|\u5b98\u65b9/.test(s)),
      { shown: shownEn, language: vm.settings.language });
    vm.onRowChange(langRow, '\u7b80\u4f53\u4e2d\u6587'); await sleep(1000);
  }
}

/* ---- ⑦c 预览的取值口径（第四轮需求⑤定稿，m04147 用户原话："切换到不同语言上面那个
        多语言字段ui也会变为不同的 包括下拉框的内容"）----
   · **预览 / 表单输入框 / 下拉候选**：跟着「多语言字段」的分段走，用该分段的池与该分段的译名；
   · **真实卡片显示 + 筛选**：仍按界面语言取（第二轮 task-6 的定夺没变，见 ⑥a 那组）。
   两者在"分段语言 == 界面语言"时完全一致，所以不会出现自相矛盾的观感。 */
{
  vm.i18nLangIndex = 0; await sleep(150);
  vm.makerTagsText = '\u5de5\u5177';                 // 简体池：工具
  vm.i18nLangIndex = 2; await sleep(150);
  vm.makerTagsText = '\u5b98\u65b9, \u77e5\u540d';  // English 池：官方, 知名
  /* 此刻分段停在 English（⑦b 段留下的）⇒ 预览取 English 池；再把分段切回简体验证另一头 */
  vm.i18nLangIndex = 0; await sleep(200);
  const previewZh = vm.previewTagList.slice();
  record('⑦c 分段=简体中文：预览取简体池（工具）',
    previewZh.length === 1 && previewZh[0] === '[\u5de5\u5177]',
    { preview: previewZh, zhPool: vm.maker.tags['\u7b80\u4f53\u4e2d\u6587'],
      enPool: vm.maker.tags['English'], language: vm.settings.language });
  /* 切到 English 界面 ⇒ 预览必须换成 English 池那份（这才是"卡片显示取自己那份"） */
  if (langRow) {
    vm.onRowChange(langRow, 'English'); await sleep(1200);
    const previewEn = vm.previewTagList.slice();
    record('⑦c English 界面：预览换成 English 池那份（官方/知名），不再是简体池',
      previewEn.length === 2 && previewEn.includes('[Official]') && previewEn.includes('[Popular]')
        && !previewEn.includes('[\u5de5\u5177]'),
      { preview: previewEn, language: vm.settings.language });
    vm.onRowChange(langRow, '\u7b80\u4f53\u4e2d\u6587'); await sleep(1000);
  }
}

/* ---- ⑧ 开源仓库与清空范围（上一轮契约回归检查，别被我改坏） ---- */
record('⑧ 前缀提示 UI 仍不存在',
  !win.document.querySelector('.repo-prefix') && !win.document.querySelector('.repo-preview'), {});
const row = win.document.querySelector('.repo-row');
const kids = row ? Array.from(row.children).map((el) => {
  const cls = String(el.className || '');
  if (cls.indexOf('combo') >= 0) return 'combo';
  if (el.tagName === 'INPUT') return 'input';
  if (el.tagName === 'BUTTON') return 'button';
  return el.tagName.toLowerCase();
}) : [];
/* ⚠️ 多组仓库后契约变了：一行 = 平台下拉 + 地址输入 + 粘贴按钮 + 垃圾桶删除按钮（4 个子节点），
 * 粘贴目标是**这一行**（maker.repos[i].url），不再有 maker.github / maker.repoPlatform。 */
record('⑧ 仓库行顺序仍是 下拉→输入框→粘贴→删除', kids.join(',') === 'combo,input,button,button', kids);
win.__MOCK_CLIPBOARD__ = '看这个 https://github.com/foo/bar';
const repoRow0 = vm.maker.repos[0];
repoRow0.url = '';
await vm.pasteRepoUrl(repoRow0); await sleep(120);
record('⑧ 粘贴仍能提取链接', repoRow0.url === 'https://github.com/foo/bar', { url: repoRow0.url });
win.__MOCK_CLIPBOARD__ = '没有链接';
repoRow0.url = '';
await vm.pasteRepoUrl(repoRow0); await sleep(120);
record('⑧ 无链接时不填值', repoRow0.url === '', {});
vm.maker.name = 'Y'; vm.maker.id = 'y';
vm.i18nLangIndex = 0; await sleep(120);
vm.makerTagsText = 'A, B';
vm.onCategoryChanged('游戏');
await vm.saveStandalone(); await sleep(300);
record('⑧ 产出后全清：类别回默认、标签回空',
  vm.maker.name === '' && vm.maker.category['简体中文'] === '工具'
  && vm.maker.tags['简体中文'] === '' && vm.maker.tags['English'] === '',
  { cat: JSON.parse(JSON.stringify(vm.maker.category)), tags: JSON.parse(JSON.stringify(vm.maker.tags)) });

/* ---- ⑨ 内置项「三语同时切换」（用户 m08090 定夺）：下拉里选内置项 = 三个语言池一起换；
         手打的文本 = 只改当前分段（第一轮「段间互不污染」不变）---- */
{
  /* 9-静态：Combo 必须把「来源」作为 change 的第二个参数抛出来，否则 onCategoryChanged
     分不清用户是**从列表里选的**还是**一路打进来的**（这就是本轮 bug 的技术根源）。 */
  const appSrc = await (await fetch(BASE + '/static/js/app.js')).text();
  record('⑨ Combo.pick 抛 change 时带 fromList=true',
    appSrc.indexOf("$emit('change', option.value, true)") >= 0, {});
  record('⑨ Combo.onEditInput 抛 change 时带 fromList=false',
    appSrc.indexOf("$emit('change', event && event.target ? event.target.value : '', false)") >= 0, {});

  const POOLS = () => JSON.parse(JSON.stringify(vm.maker.category));
  async function pickFromList(wantLabel) {
    const input = comboEdit();
    if (!input) return { err: '找不到类别输入框' };
    input.click();                                 // 可编辑模式：点输入框本体就该展开列表
    await sleep(200);
    const items = Array.from(win.document.querySelectorAll('.combo-pop .combo-item'));
    if (!items.length) return { err: '下拉列表没展开', items: 0 };
    const hit = items.find((b) => b.textContent.trim() === wantLabel);
    if (!hit) return { err: '列表里没有这一项', want: wantLabel, sample: items.slice(0, 4).map((b) => b.textContent.trim()) };
    hit.click();
    await sleep(250);
    return { ok: true, count: items.length };
  }

  /* 9-1 分段=简体中文，从下拉里点内置项「编程」⇒ 三个池同时换成规范值 编程 */
  vm.clearForm(); await sleep(250); await clickConfirm('清空');
  vm.i18nLangIndex = 0; await sleep(180);
  const before9 = POOLS();
  const r9a = await pickFromList('编程');
  const after9 = POOLS();
  record('⑨ 下拉里选内置项「编程」：三个语言池同时切换（用户要的修复）',
    !r9a.err && after9['简体中文'] === '编程' && after9['繁體中文'] === '编程' && after9['English'] === '编程',
    { r: r9a, before: before9, after: after9 });
  record('⑨ 三池同值 → 落盘塌缩成数组 ["编程"]（不产生冗余三语字典）',
    JSON.stringify(vm.buildEntry().category) === JSON.stringify(['编程']), { category: vm.buildEntry().category });
  vm.i18nLangIndex = 2; await sleep(180);
  record('⑨ 切到 English 分段：显示的是这一项的英文写法（Programming）',
    String(vm.makerCategoryText).trim() === 'Programming', { shown: vm.makerCategoryText });

  /* 9-2 手打文本（走真实 input 事件 ⇒ Combo.onEditInput ⇒ change(value, false)）
     只改当前分段，另外两段绝不跟着变 */
  const inp = comboEdit();
  if (inp) {
    inp.value = '我的自定义';
    inp.dispatchEvent(new win.Event('input', { bubbles: true }));
    await sleep(250);
  }
  const typed9 = POOLS();
  record('⑨ 手打自定义文本只写 English 池，简体/繁體不受污染（第一轮口径不变）',
    typed9['English'] === '我的自定义' && typed9['简体中文'] === '编程' && typed9['繁體中文'] === '编程',
    { pools: typed9, inpFound: !!inp });
  /* 此刻三池不同 ⇒ 落盘必须回到三语字典形态 */
  const dictEntry = vm.buildEntry().category;
  record('⑨ 三池不同 → 落盘是三语字典', !Array.isArray(dictEntry)
    && JSON.stringify(dictEntry['English']) === JSON.stringify(['我的自定义'])
    && JSON.stringify(dictEntry['简体中文']) === JSON.stringify(['编程']), { category: dictEntry });

  /* 9-3 在 English 分段里改选内置项「网络」⇒ 又把三个池拉回同值（含覆盖手打的自定义） */
  const enOpt = (vm.makerCategoryOptions || []).find((o) => o.value === 'Network');
  record('⑨ English 分段的下拉候选里有 Network（内置项随分段翻译）', !!enOpt,
    { sample: (vm.makerCategoryOptions || []).slice(0, 3).map((o) => o.value) });
  const r9b = enOpt ? await pickFromList('Network') : { err: '没有 Network 候选' };
  const after9b = POOLS();
  record('⑨ English 分段选内置项 Network：三池同时变成 网络（自定义值被整条换掉）',
    !r9b.err && after9b['简体中文'] === '网络' && after9b['繁體中文'] === '网络' && after9b['English'] === '网络',
    { r: r9b, pools: after9b });

  /* 9-4 「官方」「知名」这两个角标内置项同样三语同步（它们不在 31 项类别里，容易漏判内置） */
  vm.i18nLangIndex = 0; await sleep(180);
  const r9c = await pickFromList('官方');
  const after9c = POOLS();
  record('⑨ 选「官方」（角标内置项）同样三池同步',
    !r9c.err && after9c['简体中文'] === '官方' && after9c['English'] === '官方', { r: r9c, pools: after9c });
  vm.clearForm(); await sleep(250); await clickConfirm('清空');
}

const fails = results.filter((r) => !r.ok);
console.log('\n==== 汇总: ' + (results.length - fails.length) + '/' + results.length + ' 通过 ====');
if (fails.length) console.log('失败项: ' + fails.map((f) => f.name).join(' | '));
process.exit(fails.length ? 1 : 0);