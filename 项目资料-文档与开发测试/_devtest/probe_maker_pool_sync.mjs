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

/* ================= 制作器落盘口径回归（段间独立 + 池里绝不落显示文本） =================
 * 语义基准 = 第一轮验收（同目录 probe_maker_i18n.mjs 的 ② 三条断言）：
 *   类别/标签是三语**独立**池，某一段写什么只影响那一段，绝不把别的段带跑。
 * 本探针锁两件事：
 *   A. 任何一种语言的写法（含显示文本）进池子都还原成规范中文 ⇒ 显示文本不落盘；
 *   B. 载入 dict 形态走 *_i18n 原文，不被 detail 压平后的那份 list 覆盖（0748a8e 回归）。
 * 已知代价（库里 TG-000055 / TG-000027 的形状）在第 ③ 条明确记成"当前语义"：
 *   未编辑的分段会停在 resetMakerForm 预填的默认「工具」。值本身合法，
 *   要不要让它跟随母语段属产品决定，已单独问用户，定下来前不改这里。
 */

const CAT = () => JSON.parse(JSON.stringify(vm.maker.category));
const TAGS = () => JSON.parse(JSON.stringify(vm.maker.tags));
const status = () => (win.document.querySelector(".preview-status") || {}).textContent || "";
const setSeg = (i) => { vm.i18nLangIndex = i; };
const j = (v) => JSON.stringify(v);

vm.clearForm(); await sleep(250); await clickConfirm("清空");
setSeg(0); await sleep(150);
record("① 初始态：类别三池都预填内置「工具」，标签三池空",
  CAT().简体中文 === "工具" && CAT().繁體中文 === "工具" && CAT().English === "工具"
  && !TAGS().简体中文 && !TAGS().繁體中文 && !TAGS().English, { cat: CAT(), tags: TAGS() });

vm.makerCategoryText = "编程"; await sleep(220);
record("② 简体段写「编程」只改这一段（段间互不污染 = 第一轮锁死的行为）",
  CAT().简体中文 === "编程" && CAT().繁體中文 === "工具" && CAT().English === "工具", CAT());
const e2 = vm.buildEntry();
record("③ 三池不同 → 落盘写字典（这就是库里 TG-000055 的形状；未编辑段留在默认值）",
  !Array.isArray(e2.category) && j(e2.category.简体中文) === j(["编程"])
  && j(e2.category.繁體中文) === j(["工具"]) && j(e2.category.English) === j(["工具"]), e2.category);

setSeg(2); await sleep(180);
record("④ English 段显示自己那一份的译名 Tools，不继承简体刚写的「编程」",
  String(vm.makerCategoryText).trim() === "Tools", vm.makerCategoryText);
vm.makerCategoryText = "Tools, System"; await sleep(220);
record("⑤ English 段敲显示文本 → 池里存规范中文（显示文本绝不落盘）",
  CAT().English === "工具, 系统" && CAT().简体中文 === "编程" && CAT().繁體中文 === "工具", CAT());
setSeg(1); await sleep(180);
vm.makerCategoryText = "遊戲"; await sleep(220);
record("⑥ 繁體段敲「遊戲」→ 还原成规范中文「游戏」",
  CAT().繁體中文 === "游戏" && CAT().简体中文 === "编程" && CAT().English === "工具, 系统", CAT());
const e6 = vm.buildEntry();
record("⑦ 三池各不相同 → 字典三段各写自己那份，值全是规范中文",
  j(e6.category.繁體中文) === j(["游戏"]) && j(e6.category.English) === j(["工具", "系统"])
  && j(e6.category.简体中文) === j(["编程"]), e6.category);

vm.clearForm(); await sleep(200); await clickConfirm("清空"); setSeg(0); await sleep(150);
vm.makerTagsText = "我的标签"; await sleep(200);
record("⑧ 自定义标签原样保留（术语表认不出来不吞）且只写当前段",
  TAGS().简体中文 === "我的标签" && !TAGS().繁體中文 && !TAGS().English, TAGS());
setSeg(2); await sleep(150);
vm.makerTagsText = "Clipboard"; await sleep(200);
record("⑨ English 段敲 Clipboard → 规范值 粘贴板（库里那批脏值的成因之一）",
  TAGS().English === "粘贴板" && TAGS().简体中文 === "我的标签", TAGS());
setSeg(0); await sleep(150);
const e9 = vm.buildEntry();
record("⑩ 分段不同 → 标签按语言各存自己那份，没有一处是显示文本",
  !Array.isArray(e9.tags) && j(e9.tags.English) === j(["粘贴板"]) && j(e9.tags.简体中文) === j(["我的标签"]), e9.tags);

vm.clearForm(); await sleep(200); await clickConfirm("清空"); setSeg(2); await sleep(150);
vm.onCategoryChanged("Programming"); await sleep(200);
record("⑪ combo 抛来的显示文本 → 还原规范值后只写当前段",
  CAT().English === "编程" && CAT().简体中文 === "工具" && CAT().繁體中文 === "工具", CAT());

/* ---- B. 载入形态 ---- */
const lib = win.__MOCK_RESOURCES__;
lib.push({ id: "probe-dict", code: "TG-900055", name: "ProbeDict",
  category: { 简体中文: ["编程"], 繁體中文: ["工具"], English: ["工具"] },
  category_i18n: { 简体中文: ["编程"], 繁體中文: ["工具"], English: ["工具"] },
  tags: ["官方"], tags_i18n: { 简体中文: ["官方"] }, url: "https://z", description: "d" });
await vm.editExistingEntry({ code: "TG-900055", id: "probe-dict" });
await sleep(450);
record("⑫ 载入三岔字典 → 三段各是 编程/工具/工具，没被压平的那份覆盖",
  CAT().简体中文 === "编程" && CAT().繁體中文 === "工具" && CAT().English === "工具", CAT());
/* 缺失语言继承 LANGUAGE_FALLBACK 链上最近的一份（读侧口径，和显示层完全一致）：
   tags_i18n 只写了简体 → 繁/英 池子拿到的也是 官方，落盘时三池同值塌回 list["官方"]，
   与磁盘上「只写简体一段」等价，所以不算改数据。 */
record("⑬ 标签只有简体一段有内容 → 另两段按 LANGUAGE_FALLBACK 继承同一份（等价，不是倒灌默认值）",
  TAGS().简体中文 === "官方" && TAGS().繁體中文 === "官方" && TAGS().English === "官方", TAGS());
const rt = vm.buildEntry();
record("⑭ 不改任何东西直接落盘 → 往返无损，仍是同一份字典",
  !Array.isArray(rt.category) && j(rt.category.简体中文) === j(["编程"]) && j(rt.category.繁體中文) === j(["工具"]), rt.category);
setSeg(0); await sleep(150);
vm.makerCategoryText = "编程, 系统"; await sleep(200);
record("⑮ 载入后编辑简体段只动简体（段间独立在载入路径上同样成立）",
  CAT().简体中文 === "编程, 系统" && CAT().繁體中文 === "工具" && CAT().English === "工具", CAT());

lib.push({ id: "probe-list", code: "TG-900056", name: "ProbeList",
  category: ["工具", "网络"], tags: ["官方"], url: "https://w", description: "d" });
await vm.editExistingEntry({ code: "TG-900056", id: "probe-list" });
await sleep(450);
record("⑯ 老数据 list 形态 → 三种语言灌同一份（无 *_i18n 时回退）",
  CAT().简体中文 === "工具, 网络" && CAT().繁體中文 === "工具, 网络" && CAT().English === "工具, 网络", CAT());
setSeg(0); await sleep(150);
vm.makerCategoryText = "工具"; await sleep(200);
const e16 = vm.buildEntry();
record("⑰ list 形态载入后只改简体 → 另两段留在「工具, 网络」→ 落盘成字典",
  !Array.isArray(e16.category) && j(e16.category.简体中文) === j(["工具"])
  && j(e16.category.English) === j(["工具", "网络"]), e16.category);

/* ---- 同名提示已删（用户 m07730 定夺），邻居提示要照常 ---- */
vm.clearForm(); await sleep(200); await clickConfirm("清空"); setSeg(0); await sleep(150);
vm.maker.name = "X"; vm.maker.id = "x-probe";
vm.onCategoryChanged("工具"); await sleep(150);
vm.makerTagsText = "工具, 系统"; await sleep(400);
record("⑱ 标签与类别同名时，状态行不再出现「同名」这句提示",
  status().indexOf("同名") < 0, status().slice(0, 160));
const same = vm.buildEntry();
record("⑲ 同名标签照写照存（不静默丢、不静默改）",
  same.tags && same.tags.indexOf("工具") >= 0 && same.tags.indexOf("系统") >= 0, same.tags);
vm.makerCategoryText = "工具, 系统"; await sleep(400);
record("⑳ 邻居提示没被删坏：类别填 2 个仍然提醒",
  status().indexOf("类别只填一个就够") >= 0, status().slice(0, 200));

vm.clearForm(); await sleep(200); await clickConfirm("清空"); setSeg(2); await sleep(150);
record("㉑ 清空后回到默认：类别三池「工具」（English 段显示 Tools）、标签空",
  CAT().English === "工具" && String(vm.makerCategoryText).trim() === "Tools" && !TAGS().English,
  { cat: CAT(), text: vm.makerCategoryText });
vm.makerCategoryText = "游戏"; await sleep(200);
record("㉒ 清空后编辑仍保持段间独立（复位没把状态弄脏）",
  CAT().English === "游戏" && CAT().简体中文 === "工具" && CAT().繁體中文 === "工具", CAT());

const fail = results.filter((r) => !r.ok);
console.log("\n" + "PASS " + (results.length - fail.length) + " / " + results.length);
fail.forEach((f) => console.log("  FAILED: " + f.name));
if (fail.length) process.exitCode = 1;
win.close();
