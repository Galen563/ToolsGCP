/* 本轮"外观类"需求的验证 —— 用 jsdom 的**真实 CSS 解析 + 级联顺序**，
   不再手写正则解析 CSS（前几版那样反复出假 FAIL：注释里提到选择器名、
   逗号分组选择器、@media 嵌套……手写解析器永远在漏情况）。

   覆盖用户四条原话：
     ① 「GCP-AI用户的聊天气泡不要是特殊的颜色，和AI聊天气泡一致颜色就ok」
     ② 「用户编辑模式下…反馈感不强 感觉还像是在聊天气泡内输入而不是输入框ui的反馈感」
     ③ 「GCP-AI右侧边悬浮窗不要是半透明的」
     ④ 「框选字体的款选颜色有点浅 再蓝一点」
   外加源码级防回归（旧结构不残留、未保存弹窗已删）。

   做法：按 index.html 里的**真实加载顺序**把 CSS 塞进一个 JSDOM，
   然后对每个选择器找"级联里最后一条命中的规则"（= 浏览器实际生效的那条）来断言。

   跑法：node test_r2_visual_css.mjs
*/
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BASE = path.dirname(path.dirname(HERE));
const CSS = path.join(BASE, '.ToolsGCP', 'webui', 'css');
const R = [];
function check(name, ok, extra) {
  console.log((ok ? '  OK    ' : '  FAIL  ') + name + (extra ? '  <- ' + extra : ''));
  R.push({ name, ok });
}

/* 1) 从 index.html 里读出真实的 <link rel=stylesheet> 顺序（不能自己拍脑袋排：
      "同特异性谁赢"完全取决于这个顺序，写错顺序 = 断言在测一个不存在的级联） */
const html = fs.readFileSync(path.join(BASE, '.ToolsGCP', 'webui', 'index.html'), 'utf8');
const ORDER = [...html.matchAll(/<link rel="stylesheet" href="\/static\/css\/([\w.-]+)\.css">/g)]
  .map((m) => m[1]);
check(`从 index.html 解析出样式表顺序（${ORDER.length} 个）`, ORDER.length >= 8, ORDER.join(','));
check('ai-fixes.css 排在 components.css 之后（本轮覆盖靠的就是这个顺序）',
  ORDER.indexOf('ai-fixes') > ORDER.indexOf('components'));

/* 2) 按该顺序建一个 JSDOM，让真实 CSS 解析器建 styleSheets */
const styles = ORDER.filter((n) => fs.existsSync(path.join(CSS, `${n}.css`)))
  .map((n) => `<style>${fs.readFileSync(path.join(CSS, `${n}.css`), 'utf8')}</style>`)
  .join('\n');
const dom = new JSDOM(`<!doctype html><html><head>${styles}</head><body></body></html>`);
const sheets = [...dom.window.document.styleSheets];

/* 3) 收集所有规则（含 @media 里的），保留文档顺序 = 级联顺序 */
const rules = [];
const walk = (list, media) => {
  for (const r of list) {
    if (r.type === 1 || r.constructor?.name === 'CSSStyleRule') {
      rules.push({ selector: r.selectorText, style: r.style, media });
    } else if (r.cssRules) {
      walk(r.cssRules, r.conditionText || media);
    }
  }
};
sheets.forEach((s) => walk(s.cssRules, ''));
check(`解析出 ${rules.length} 条样式规则`, rules.length > 500);

/* 4) 级联查询：命中该选择器的规则里，**最后一条**才是生效的（同特异性看顺序） */
function matched(selector, mediaIncludes = null) {
  return rules.filter((r) => {
    if (mediaIncludes !== null && !(r.media || '').includes(mediaIncludes)) return false;
    if (mediaIncludes === null && r.media) return false;      // 只看非 @media 的顶层规则
    return r.selector.split(',').map((s) => s.trim()).includes(selector);
  });
}
function winning(selector) {
  const list = matched(selector);
  return list.length ? list[list.length - 1] : null;
}
function decl(selector, prop) {
  const w = winning(selector);
  if (!w) return null;
  const v = w.style.getPropertyValue(prop);
  return v ? String(v).trim() : null;
}

console.log('\n[1] 用户气泡 = AI 气泡同色（级联最终生效值）');
const aiBg = decl('.bubble.is-ai', 'background');
const userBg = decl('.bubble.is-user', 'background');
check('.bubble.is-user 有生效规则', !!winning('.bubble.is-user'));
check('用户气泡底色与 AI 气泡**完全相同**（不是渐变 --ball-*）',
  userBg && userBg === aiBg, `user=${userBg} ai=${aiBg}`);
check('用户气泡底色是 var(--card-solid)', userBg === 'var(--card-solid)', String(userBg));
const userBorder = decl('.bubble.is-user', 'border');
check('用户气泡带描边（和 .is-ai 同一套语言）',
  userBorder && userBorder.includes('var(--card-border)'), String(userBorder));
check('旧渐变已从生效值里消失', !String(userBg).includes('--ball-'), String(userBg));
const glassUser = winning(':root[data-theme][data-fx="glass"] .bubble.is-user, :root[data-theme][data-fx="acrylic"] .bubble.is-user')
  || winning(':root[data-theme][data-fx="glass"] .bubble.is-user');
check('glass 档也给了用户气泡同款半透明（否则一个糊一个实）',
  !!glassUser, glassUser ? glassUser.selector.slice(0, 60) : '无此规则');

console.log('\n[2] 编辑态 = 输入框反馈感（且尺寸不被写死）');
const edit = winning('.bubble.ai-bubble-edit');
check('有 .bubble.ai-bubble-edit 生效规则', !!edit);
if (edit) {
  const border = decl('.bubble.ai-bubble-edit', 'border');
  const shadow = decl('.bubble.ai-bubble-edit', 'box-shadow');
  check('强调色描边', border && border.includes('var(--accent)'), String(border));
  check('外发光光圈（输入框聚焦那套语言）',
    shadow && shadow.includes('var(--accent-soft)') && shadow.includes('3px'), String(shadow));
  check('圆角收成输入框的 10px（不再是气泡 16）',
    decl('.bubble.ai-bubble-edit', 'border-radius') === '10px',
    String(decl('.bubble.ai-bubble-edit', 'border-radius')));
  check('光标强调色 caret-color',
    decl('.bubble.ai-bubble-edit', 'caret-color') === 'var(--accent)',
    String(decl('.bubble.ai-bubble-edit', 'caret-color')));
  /* 上一轮的硬要求：点编辑不能突然缩小/跳位 → 盒尺寸只能由 JS 实测给，CSS 不许写死 */
  const bad = ['width', 'height', 'min-width', 'min-height', 'max-width', 'max-height']
    .filter((p) => edit.style.getPropertyValue(p));
  check('⚠️ 没有写死任何盒尺寸（width/height/min/max 都不许出现）',
    bad.length === 0, bad.join(','));
  check('resize: none（拖拽会破坏尺寸保持）',
    decl('.bubble.ai-bubble-edit', 'resize') === 'none',
    String(decl('.bubble.ai-bubble-edit', 'resize')));
}

console.log('\n[3] 抽屉不半透明（覆盖 glass/acrylic 那两条）');
/* ⚠️ glass/acrylic/浅色主题这些条件在本项目里是**选择器的一部分**
   （`:root[data-theme][data-fx="glass"] .ai-drawer`），不是 @media 包起来的，
   所以必须按完整选择器查 —— 上一版拿 mediaIncludes 去找，永远找不到（假 FAIL）。 */
const drawerGlass = winning(':root[data-theme][data-fx="glass"] .ai-drawer, :root[data-theme][data-fx="acrylic"] .ai-drawer')
  || winning(':root[data-theme][data-fx="glass"] .ai-drawer');
const drawerWin = drawerGlass;
check('glass 档下 .ai-drawer 有覆盖规则', !!drawerWin);
if (drawerWin) {
  check('背景完全不透明 var(--card-solid)',
    drawerWin.style.getPropertyValue('background') === 'var(--card-solid)',
    drawerWin.style.getPropertyValue('background'));
  check('backdrop-filter 关掉',
    drawerWin.style.getPropertyValue('backdrop-filter') === 'none',
    drawerWin.style.getPropertyValue('backdrop-filter'));
  check('没有 !important（靠特异性+顺序赢，不靠强推）',
    !drawerWin.style.getPropertyValue('background').includes('!important'));
}
const lightGlass = matched(':root[data-theme="light"][data-fx="glass"] .ai-drawer');
check('浅色主题单独给 #ffffff（否则会露深色 card-solid）',
  lightGlass.length > 0 && String(lightGlass[lightGlass.length - 1].style.getPropertyValue('background'))
    .toLowerCase() === '#ffffff',
  lightGlass.length ? lightGlass[lightGlass.length - 1].style.getPropertyValue('background') : '无此规则');

console.log('\n[4] 选区更蓝');
for (const sel of ['.ai-embedded ::selection', '.ai-drawer ::selection',
                   '.bubble ::selection', '.ai-rich-input ::selection']) {
  const v = decl(sel, 'background');
  check(`${sel} 生效规则用强调色`, v && v.includes('var(--accent)'), String(v));
  check(`${sel} 不透明度 46%（比系统默认深）`, v && v.includes('46%'), String(v));
}
const lightSel = winning(':root[data-theme="light"] .bubble ::selection, :root[data-theme="light"] .ai-rich-input ::selection')
  || winning(':root[data-theme="light"] .bubble ::selection')
  || winning(':root[data-theme="light"] .ai-embedded ::selection, :root[data-theme="light"] .ai-drawer ::selection, :root[data-theme="light"] .bubble ::selection, :root[data-theme="light"] .ai-rich-input ::selection');
check('浅色主题降到 34%（蓝字压在浅底上仍要可读）',
  !!lightSel && String(lightSel.style.getPropertyValue('background')).includes('34%'),
  lightSel ? lightSel.style.getPropertyValue('background') : '无');

console.log('\n[5] 启动遮罩：fixed 居中 + 跟随主题的半透明底（不再"叠加+偏 24px"）');
const boot = winning('.boot-screen');
check('.boot-screen 有生效规则', !!boot);
if (boot) {
  check('position: fixed（absolute 会被 48px 标题栏+导航挤偏右下各 24px）',
    boot.style.getPropertyValue('position') === 'fixed',
    boot.style.getPropertyValue('position'));
  const bg = boot.style.getPropertyValue('background');
  check('底色跟随 var(--page) 且高不透明（不再完全透明压住底下页面）',
    bg.includes('var(--page)') && !/transparent/.test(bg.split(')')[0]), bg);
  check('不再 pointer-events: none（点穿到底页会误触发）',
    boot.style.getPropertyValue('pointer-events') !== 'none',
    boot.style.getPropertyValue('pointer-events'));
}

console.log('\n[5.5] toast 里的 请填写<API Key> 是蓝字 + 下划线（jsdom 不解析 var()，只能在 CSSOM 这层验）');
const tl = winning('.toast-link');
check('.toast-link 有生效规则', !!tl);
if (tl) {
  check('颜色 = var(--accent)（用户点名"不是蓝色字体的普通字体是不对的"）',
    tl.style.getPropertyValue('color') === 'var(--accent)',
    tl.style.getPropertyValue('color'));
  check('有下划线 text-decoration: underline',
    /underline/.test(tl.style.getPropertyValue('text-decoration')
      || tl.style.getPropertyValue('text-decoration-line') || ''),
    tl.style.getPropertyValue('text-decoration'));
  check('看起来是文字而不是按钮（无背景无边框）',
    tl.style.getPropertyValue('background') === 'none'
    && tl.style.getPropertyValue('border') === '0px'
    || tl.style.getPropertyValue('border') === '0',
    `bg=${tl.style.getPropertyValue('background')} border=${tl.style.getPropertyValue('border')}`);
}

console.log('\n[6] 源码级防回归（旧结构 / 已删的弹窗 / 快捷键括号）');
const appjs = fs.readFileSync(path.join(BASE, '.ToolsGCP', 'webui', 'js', 'app.js'), 'utf8');
const aiFix = fs.readFileSync(path.join(CSS, 'ai-fixes.css'), 'utf8');
const htmlNoC = html.replace(/<!--[\s\S]*?-->/g, '');
const aiFixNoC = aiFix.replace(/\/\*[\s\S]*?\*\//g, '');   /* ⚠️ 注释里会**提到**旧类名，不剥就自己抓自己 */
check('未保存确认弹窗已删（api_unsaved_title 不再出现）', !appjs.includes('api_unsaved_title'));
check('apiKeyDirty/saveApiKey 本体保留（保存按钮还在用）',
  appjs.includes('function apiKeyDirty()') && appjs.includes('async function saveApiKey'));
check('气泡右键只剩复制', !html.includes('aiCtxSelectAll') && html.includes('aiCtxCopy'));
check('旧结构 .ai-input-col 不残留（HTML+CSS 都查，剥注释）',
  !htmlNoC.includes('ai-input-col') && !aiFixNoC.includes('.ai-input-col'));
check('旧结构 .ai-input-foot 不残留',
  !htmlNoC.includes('ai-input-foot') && !aiFixNoC.includes('.ai-input-foot'));
check('旧思考开关 .ai-think-toggle 不残留',
  !htmlNoC.includes('ai-think-toggle') && !aiFixNoC.includes('.ai-think-toggle'));
check('模型图标已换成 #i-model（不再是 #i-chip）',
  htmlNoC.includes('#i-model') && !htmlNoC.includes('#i-chip'));
check('润色按钮改纯图标 is-icon 且无文字 span',
  htmlNoC.includes('ai-polish is-icon') && !htmlNoC.includes('ai-polish-text'));
check('模型项对勾占位 .ai-model-mark 在名字**前面**',
  /ai-model-mark[\s\S]{0,400}ai-model-item-name/.test(htmlNoC));
check('输入框菜单快捷键在 JS 里加括号', /'（' \+ item\.hotkey \+ '）'/.test(appjs));
check('旧竖排容器 .imi-text 已从 HTML 移除', !htmlNoC.includes('imi-text'));
check('设置搜索"-"前板块名用强调色',
  /\.hit-merged \.hit-merged-section\s*\{[^}]*var\(--accent\)/.test(aiFixNoC)
  || /\.hit-merged-section\s*\{[^}]*var\(--accent\)/.test(
    fs.readFileSync(path.join(CSS, 'settings-fixes.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')));

console.log('\n[7] 防回归：前端不许有"裸中文兜底"（本轮扫出 15 处，全改了 t()）');
{
  /* ⚠️ 为什么需要这条守卫：泄漏扫描器只能扫**渲染出来**的文本，
     而 toast / 状态变量里的兜底文案要等错误发生才显示，扫不到。
     本轮就是靠"源码级"扫描才发现 `result.error || '删除失败'`、
     `.replace('{err}', result.error || '保存失败')`、`updateState.error = ... || '下载失败'`
     这类**赋值给变量**的兜底（第一版扫描器把匹配限定在 toast(...) 内，全漏了）。
     所以固化成断言：这类"|| '中文'"的兜底必须已经包进 t()。 */
  const src = appjs
    /* 先剥掉 t('key', '中文兜底') 的第二个参数（那是合法的，语言包缺键时才用） */
    .replace(/t\(\s*'[^']+'\s*,\s*'(?:[^'\\]|\\.)*'\s*(?:,\s*'[^']+'\s*)?\)/g, 'T()')
    /* 再剥注释 */
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  const BARE = /\|\|\s*'(?:该功能|取消|确定|保存失败|未知错误|清空失败|下载失败|收藏失败|移动失败|创建失败|重命名失败|删除失败|读取 API Key 失败|新建收藏夹失败|资源库读取失败|（空）)'/;
  const hits = src.split('\n').map((l, i) => ({ n: i + 1, l })).filter((x) => BARE.test(x.l));
  check('没有"|| 裸中文"兜底（都走 t()）', hits.length === 0,
    hits.slice(0, 3).map((x) => `${x.n}:${x.l.trim().slice(0, 40)}`).join(' | '));
  /* needApi 那句整句中文以前是硬编码，现在必须是 t() 拼出来的 */
  check('needApi 走语言包', /need_api_missing/.test(appjs));
  /* 托盘浮层四项：初始值不许是硬编码中文（后端 labels 没到时英文界面必露中文） */
  const trayInit = appjs.match(/const trayLabels = reactive\(\{([\s\S]{0,200}?)\}\)/);
  check('trayLabels 初始值不再硬编码中文', !!trayInit && !/[\u4e00-\u9fff]/.test(trayInit[1]),
    trayInit ? trayInit[1].replace(/\s+/g, ' ').slice(0, 70) : '没找到');
  /* 字体名 / 语言名是**数据取值**，不许被"顺手翻译"（CSS 会失效、比对会错） */
  check("CSS 字体名仍是数据值 '微软雅黑'（不是可译文案）", appjs.includes("|| '微软雅黑'"));
  check("语言数据值仍是 '简体中文'（不是可译文案）", appjs.includes("|| '简体中文'"));
}

const bad = R.filter((x) => !x.ok);
console.log('='.repeat(64));
console.log(bad.length ? `FAILED ${bad.length}: ${bad.map((b) => b.name).join(' | ')}` : 'ALL OK');
process.exit(bad.length ? 1 : 0);
