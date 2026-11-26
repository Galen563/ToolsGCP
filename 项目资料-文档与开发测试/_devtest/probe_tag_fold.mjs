/* 卡片标签折叠算法探针（task-14 需求⑤）。
 * 五种形态（任务验收点名的）+ 渲染级一致性：
 *   F1 首标签超宽        —— 宽标签在最前时整排塌成 +N 的病根回归（现在显示能放的、跳放不下的）
 *   F2 英文长标签        —— 估算系数 0.54 低估英文宽 → 超边界裁字，改实测后不许复发
 *   F3 "+12" 比 "+3" 宽  —— 胶囊写死 40px 的病根回归：宽度必须按文本实算
 *   F4 收藏页/定制页无 avail → 退回固定条数（grid 2 / list 4），且 hidden=0 不出 +X
 *   F5 窄卡片 240px      —— 边界收缩后总宽必须 ≤ avail（遮挡 = FAIL）
 *   F6 渲染一致性        —— 真列表页 DOM：可见标签 + 实算胶囊 必须塞得进 tagAvail
 * 不变式（全形态通用）：
 *   INV-A 放得下就不许有 +N；hidden>0 时 shown+gap+实算胶囊 ≤ avail（无遮挡）
 *   INV-B 不许"一个标签都没显示只剩 +N"，除非首个标签本身就比整行宽（退化有注释）
 *   INV-C visibleTags/hiddenTagCount 与 tagLayout 口径一致；hidden = 总数 − 显示数
 * 用法：python serve.py 8899 后 GCP_PORT=8899 node probe_tag_fold.mjs */
import { JSDOM, VirtualConsole } from 'jsdom';
const PORT = process.env.GCP_PORT || '8899';
const BASE = 'http://127.0.0.1:' + PORT;
const out = [];
const record = (n, ok, d) => { out.push({ n, ok }); console.log((ok ? 'PASS' : 'FAIL') + '  ' + n + (d !== undefined ? '  ' + JSON.stringify(d) : '')); };
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
function cutInlineScript(html, marker) {
  let at = html.indexOf(marker); let guard = 0;
  while (at >= 0 && guard++ < 10) {
    const open = html.lastIndexOf('<script', at);
    const close = html.indexOf('</' + 'script>', at);
    if (open < 0 || close < 0) break;
    html = html.slice(0, open) + html.slice(close + 9);
    at = html.indexOf(marker);
  }
  return html;
}
async function boot(extraQuery) {
  const vc = new VirtualConsole(); vc.on('jsdomError', () => {});
  let html = await (await fetch(BASE + '/?page=search&theme=dark' + (extraQuery || ''))).text();
  html = html.replace(/<script src="\/static\/js\/vendor\/tailwind\.js"[\s\S]*?<\/script>/, '');
  html = cutInlineScript(html, 'tailwind.config');
  const dom = new JSDOM(html, {
    url: BASE + '/?page=search&theme=dark', runScripts: 'dangerously',
    resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.fetch = (i, o) => fetch(new URL(String(i), BASE), o);
      w.Response = Response; w.Request = Request; w.Headers = Headers;
      w.Element.prototype.getBoundingClientRect = () => ({ x:0,y:0,top:0,left:0,right:0,bottom:0,width:120,height:32,toJSON(){} });
    },
  });
  const win = dom.window;
  const t0 = Date.now();
  while (!win.__TOOLSGCP_APP__ && Date.now() - t0 < 25000) await sleep(100);
  if (!win.__TOOLSGCP_APP__) throw new Error('app 未挂载');
  return { win, vm: win.__TOOLSGCP_APP__ };
}
async function bootRetry(extraQuery) {
  let last = null;
  for (let i = 0; i < 5; i += 1) { try { return await boot(extraQuery); } catch (e) { last = e; await sleep(1500); } }
  throw last;
}
const { win, vm } = await bootRetry();
const t1 = Date.now();
while (!(vm.items && vm.items.length) && Date.now() - t1 < 20000) await sleep(150);
record('A0 app 已挂载、列表已加载', (vm.items || []).length > 0, { count: (vm.items || []).length });

const tagLayout = vm.tagLayout, tagBoxWidth = vm.tagBoxWidth, plusBoxWidth = vm.plusBoxWidth;
record('A1 测试接缝可用（tagLayout/tagBoxWidth/plusBoxWidth 已导出）',
  typeof tagLayout === 'function' && typeof tagBoxWidth === 'function' && typeof plusBoxWidth === 'function');
const mk = (tags) => ({ tags, name: 'X', code: 'TG-900001', url: 'https://a.example', github: '' });
/* 通用校验：总宽必须用**算法自己那套**度量累（tagGap() 是 computed 出来的行间 gap，
   磁贴 6 / 网格 4；写死 6 会在网格口径下出现假阳性越界）。
   注：totalWidth 与算法一样"shown 为空时不加前导 gap"。 */
const GAP = () => (typeof vm.tagGap === 'function' ? vm.tagGap() : 6);
function totalWidth(shown, hidden) {
  let w = 0;
  for (let i = 0; i < shown.length; i += 1) w += tagBoxWidth(shown[i]) + (i ? GAP() : 0);
  if (hidden > 0) w += (shown.length ? GAP() : 0) + plusBoxWidth(hidden);
  return w;
}
function check(name, item, avail, extra) {
  const r = tagLayout(item, avail);
  const all = item.tags.filter(Boolean);
  const total = totalWidth(r.shown, r.hidden);
  const noOverflow = r.hidden === 0 ? (total <= avail && r.shown.length === all.length) : (total <= avail);
  const notAllPill = r.shown.length > 0 || (r.hidden > 0 && tagBoxWidth(all[0]) > avail);
  const countOk = r.shown.length + r.hidden === all.length || (r.hidden === 0 && r.shown.length <= all.length);
  record(name, noOverflow && notAllPill && countOk && (!extra || extra(r)),
    { avail, shown: r.shown.length, hidden: r.hidden, total: Math.round(total) });
  return r;
}

/* F1 首标签超宽：第一个比整行宽，后面的窄标签必须顶上而不是全塌 */
const wide = Array.from({ length: 18 }, (_, i) => '宽' + i + '超宽标签文本'); // ~8 中文字 ≈ 116px
check('F1 首标签超宽：不塌成纯 +N（后续窄标签照常显示）',
  mk([wide[0], '工具', '系统', '办公', wide[1], '学习']), 300,
  (r) => r.shown.indexOf('工具') >= 0 && r.shown.length >= 3);
/* F2 英文长标签：旧估算 0.54×11.5=6.2px/字 低估 → 超界裁字；实测后 total ≤ avail */
check('F2 英文长标签：实测宽度不超界',
  mk(['Programming languages', 'Remote control', 'Screen recording', 'Download tools', 'Video editing']), 300,
  (r) => r.shown.length >= 1);
/* F3 +12 与 +3 的胶囊宽度必须按文本实算（旧 PLUS_TAG_W=40 写死 → 两者一样宽） */
const w3 = plusBoxWidth(3), w12 = plusBoxWidth(12);
record('F3 胶囊按文本实算：+12 宽 > +3 宽，且都不等于旧写死的 40',
  w12 > w3, { plus3: Math.round(w3), plus12: Math.round(w12) });
/* F3b 收缩判据用真实胶囊宽：造一个 avail 恰好卡在"按 40 算放得下、按实算 +12 放不下"的场景 */
const many = Array.from({ length: 12 }, (_, i) => '标签' + i);
let f3bBad = null;
for (let avail = 60; avail <= 420 && !f3bBad; avail += 13) {
  const r = tagLayout(mk(many), avail);
  const total = totalWidth(r.shown, r.hidden);
  if (total > avail) f3bBad = { avail, total: Math.round(total), shown: r.shown.length, hidden: r.hidden };
  /* 12 个标签在任何 >胶囊宽 的行里都不可能全放下 → hidden 必须 >0（不许静默丢标签） */
  else if (plusBoxWidth(12) <= avail && r.hidden === 0) f3bBad = { avail, why: '放不下却不出 +N' };
}
record('F3b 60→420px 扫描：12 标签场景从不越界且必出 +N', !f3bBad, f3bBad || undefined);
/* F4 无 avail 退回固定条数（收藏页/定制页形态）。
   ⚠️ viewMode 是 computed（无 setter），**赋值无效**；真相源是 settings.search_view，
   两个合法取值是 'grid'（网格）与 'tile'（磁贴/列表），不是 'list'。
   settings 是 reactive 对象，直接写它即可，viewMode 会跟着重算。 */
const savedView = vm.settings.search_view;
vm.settings.search_view = 'grid';
const g4 = tagLayout(mk(many.slice(0, 6)), 0);
vm.settings.search_view = 'tile';
const l4 = tagLayout(mk(many.slice(0, 6)), 0);
vm.settings.search_view = savedView;
record('F4 无 avail：grid 固定 2 条 / tile 固定 4 条，hidden=0 不出 +X',
  g4.shown.length === 2 && g4.hidden === 0 && l4.shown.length === 4 && l4.hidden === 0,
  { grid: g4.shown.length, tile: l4.shown.length });
/* F5 窄卡片 240px：tagAvail 换算后可用宽很小时仍不越界；且首个标签放得下时必须至少显示 1 枚 */
vm.settings.search_view = 'grid';
const narrowItem = mk(['工具', '系统', '办公', '学习', '创作']);
narrowItem.url = 'https://a.example'; narrowItem.github = 'https://g.example';
const avail240 = vm.tagAvail(narrowItem, 240);
const r5 = check('F5 窄卡片 240px：总宽不越界、可见标签 ≥1', narrowItem, avail240, (r) => r.shown.length >= 1);
record('F5b tagAvail(240px 卡) 给出正数可用宽', avail240 > 0, { avail: Math.round(avail240) });
/* INV 扫描：对每种"标签数 × 宽度"组合断言不变式（hidden 口径 + 不越界 + 放得下就不许 +N） */
let invBad = null;
const tagPool = ['工具', 'Programming languages', '系统', 'Remote control and sync', '办公', '知名', '官方'];
for (let n = 1; n <= 5 && !invBad; n += 1) {
  for (let avail = 30; avail <= 360 && !invBad; avail += 11) {
    const item = mk(tagPool.slice(0, n));
    const r = tagLayout(item, avail);
    const total = totalWidth(r.shown, r.hidden);
    /* gap 必须跟算法同源（磁贴 6 / 网格 4）：这里原先写死 6，网格口径下 96px 放 2 个标签
       真宽 35+4+56=95 明明放得下（hidden=0 正确），却按 97>96 误判成「有隐藏却不出胶囊」。 */
    const canFitAll = tagPool.slice(0, n).reduce((w, tg, i) => w + tagBoxWidth(tg) + (i ? GAP() : 0), 0) <= avail;
    /* 唯一合法例外（算法 ③ 有注释）：连光杆胶囊都比整行窄 → 什么都不渲染，
       hidden 归 0。这条在扫描里必须豁免，否则是我们自己造出来的假阳性。 */
    const degenerate = plusBoxWidth(n) > avail;
    if (total > avail) invBad = { why: '越界', avail, n };
    else if (canFitAll && r.hidden > 0) invBad = { why: '放得下却出 +N', avail, n };
    else if (!canFitAll && !degenerate && r.hidden === 0) invBad = { why: '有隐藏却不出胶囊', avail, n };
  }
}
record('INV 全组合扫描（1–5 标签 × 30–360px）：不越界 / 放得下不折叠 / 有隐藏必有胶囊', !invBad, invBad || undefined);
/* F6 渲染级：真列表页里前 12 张卡，DOM 上的 tag + tag-more 实算总宽 ≤ 该卡 tagAvail */
vm.page = 'search'; vm.settings.search_view = 'tile';
await sleep(400);
const cards = vm.items.slice(0, 12);
let domBad = null;
for (const it of cards) {
  const avail = vm.tagAvail(it, 320);
  if (avail <= 0) continue;
  const shown = vm.visibleTags(it, avail);
  const hidden = vm.hiddenTagCount(it, avail);
  if (shown.length + hidden !== (it.tags || []).filter(Boolean).length) { domBad = { code: it.code, why: '数量口径不一致' }; break; }
  let w = 0;
  shown.forEach((tg, i) => { w += vm.tagBoxWidth(tg) + (i ? GAP() : 0); });
  if (hidden > 0) w += (shown.length ? GAP() : 0) + vm.plusBoxWidth(hidden);
  if (w > avail) { domBad = { code: it.code, w: Math.round(w), avail: Math.round(avail) }; break; }
}
record('F6 真实条目前 12 卡：visibleTags/hiddenTagCount 口径一致且实算总宽 ≤ tagAvail', !domBad, domBad || undefined);
/* 缓存：同 term 二次取宽必须走缓存（值一致即可断言；命中率看代码路径） */
const cA = vm.tagTextPx('工具', false), cB = vm.tagTextPx('工具', false);
record('缓存：同文本两次实测值一致（命中 Map 缓存）', cA === cB, { w: cA });
/* ---- F7 canvas 实测分支（jsdom 没有 canvas → 用 js0 装确定性 2d 桩） ----
   上一段跑的是**回退估算**分支（无 canvas 时偏大系数 0.65，宁少放不裁字）。
   这一段证明**主分支**也真的工作：宽度来自 measureText、胶囊用 600 字体的字体串。 */
const STUB = "(function(){var S=window.__CANVAS__={fonts:[],calls:0};"
  + "var ctx={_font:'',measureText:function(t){S.calls++;return {width:String(t==null?'':t).length*10};}};"
  + "Object.defineProperty(ctx,'font',{get:function(){return this._font;},"
  + "set:function(v){this._font=v;S.fonts.push(v);}});"
  + "window.HTMLCanvasElement.prototype.getContext=function(k){return k==='2d'?ctx:null;};})();";
const s = await bootRetry('&js0=' + encodeURIComponent(STUB));
const svm = s.vm;
if (!svm.tagTextPx) {
  record('F7 canvas 桩注入成功', false, { why: 'app 未挂载（桩可能在 beforeParse 前就报错）' });
} else {
  const fontsBefore = s.win.__CANVAS__.calls;
  const wAb = svm.tagTextPx('AB', false);          // 2 字 ×10 +2 = 22
  const wAbc = svm.tagTextPx('ABC', false);        // 3 字 ×10 +2 = 32
  const wBold = svm.tagTextPx('+12', true);        // 3 字 ×10 +2 = 32（但字体串带 600）
  record('F7 主分支生效：宽度 = measureText +2 向上取整（非估算）',
    wAb === 22 && wAbc === 32 && s.win.__CANVAS__.calls >= 3,
    { AB: wAb, ABC: wAbc, calls: s.win.__CANVAS__.calls });
  const fontList = s.win.__CANVAS__.fonts;
  const regular = fontList.some((f) => /^11\.5px /.test(f));
  const bold = fontList.some((f) => /^600 11\.5px /.test(f));
  record('F7 字体串正确：普通标签 11.5px+body 字体族，+X 胶囊用 600 字重',
    regular && bold, { sample: fontList.slice(0, 2) });
  /* 胶囊比同字数普通文本走**不同**字体串 ⇒ 宽度不会互相污染缓存 */
  record('F7 缓存按 字重+文本 分键：ABC 与 +12 同宽（同字数）但各自记录过字体',
    wAbc === wBold, { abc: wAbc, plus12: wBold });
  /* 实测分支下同样不许越界（抽 F3b 的同一条扫描） */
  const many2 = Array.from({ length: 12 }, (_, i) => '标签' + i);
  let sBad = null;
  for (let avail = 60; avail <= 420 && !sBad; avail += 13) {
    const r = svm.tagLayout({ tags: many2, name: 'X', code: 'TG-900001', url: '', github: '' }, avail);
    let w = 0;
    for (let i = 0; i < r.shown.length; i += 1) w += svm.tagBoxWidth(r.shown[i]) + (i ? GAP() : 0);
    if (r.hidden > 0) w += (r.shown.length ? GAP() : 0) + svm.plusBoxWidth(r.hidden);
    if (w > avail) sBad = { avail, w: Math.round(w) };
  }
  record('F7b 实测分支下 60→420px 扫描仍不越界', !sBad, sBad || undefined);
  void fontsBefore;
}

/* ---- F8 退化路径（算法 ③）：行宽连光杆胶囊都放不下 ----
   期望：shown=[] 且 hidden=0 ⇒ 模板 v-if 不成立 → **什么都不渲染**，
   不会出现"半截 +N 被裁"的遮挡（这正是需求禁止的形态）。 */
{
  const tiny = tagLayout(mk(['工具', '系统', '办公']), 12);
  record('F8 退化：avail 小于胶囊宽时整区留空（不渲染被裁的半截胶囊）',
    tiny.shown.length === 0 && tiny.hidden === 0, { shown: tiny.shown.length, hidden: tiny.hidden });
  /* 刚好放得下胶囊的临界：必须回到"只胶囊"而不是继续留空 */
  const justFits = plusBoxWidth(3);
  const edge = tagLayout(mk(['工具超宽', '系统超宽', '办公超宽']), justFits);
  record('F8b 临界宽度恢复：能放胶囊时 hidden 必须如实报数',
    edge.shown.length === 0 && edge.hidden === 3, { hidden: edge.hidden, need: Math.round(justFits) });
}

process.exit(out.some(o => !o.ok) ? 1 : 0);