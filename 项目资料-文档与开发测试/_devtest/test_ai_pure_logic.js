// GCP-AI 本轮新增的**纯函数**离线自测（不需要浏览器 / 不需要 Vue）。
// 做法：从 app.js 里按名字抠出函数源码，eval 出来直接断言 ——
// 沙箱里跑不动无头 Edge（Chromium 多进程要命名管道），所以逻辑层只能用这种方式验。
// 跑法：node "项目资料-文档与开发测试/_devtest/test_ai_pure_logic.js"
const fs = require('fs');
const path = require('path');

// __dirname = <ROOT>/项目资料-文档与开发测试/_devtest → 上两级才是仓库根
const ROOT = path.dirname(path.dirname(__dirname));
const APP = path.join(ROOT, '.ToolsGCP', 'webui', 'js', 'app.js');
const src = fs.readFileSync(APP, 'utf8');

let fails = 0;
function check(name, cond, detail) {
  console.log(`  ${cond ? 'OK  ' : 'FAIL'}  ${name}` + (detail ? `  <- ${detail}` : ''));
  if (!cond) fails += 1;
}

/** 从 app.js 里抠出一个函数（按大括号配平，不靠行号 —— 行号会被别人的改动冲掉） */
function extract(name) {
  const at = src.indexOf(`function ${name}(`);
  if (at < 0) throw new Error(`找不到函数 ${name}`);
  let i = src.indexOf('{', at);
  let depth = 0;
  for (let j = i; j < src.length; j += 1) {
    const c = src[j];
    if (c === '{') depth += 1;
    else if (c === '}') {
      depth -= 1;
      if (depth === 0) return src.slice(at, j + 1);
    }
  }
  throw new Error(`${name} 大括号没配平`);
}

// aiSplitLinks 依赖的两个正则 + 边界函数 + 常量，一起抠出来喂给它。
// ⚠️ 正则/常量**从 app.js 原样取**（不在这里抄一份）：抄一份就会和源码慢慢不同步，
//    上一轮就是这么漏掉了"token 名字里可以有空格"的修复。
function extractLine(prefix) {
  const at = src.indexOf(prefix);
  if (at < 0) throw new Error(`找不到 ${prefix}`);
  const end = src.indexOf('\n', at);
  return src.slice(at, end);
}
/* ⚠️ 至少要有一条语句：删掉 aiNameBoundary 之后 ctxSrc 只剩三条 const 声明，
   `return {...}` 出现在脚本顶层会 SyntaxError（new Function 的函数体也是脚本语法）。 */
/* ⚠️ AI_SETTINGS_TOKENS 本轮改成了**多行数组**，extractLine 只取到第一个换行 →
   抠出个没闭合的 `[`，new Function 直接 SyntaxError（就是刚才那次崩溃）。
   所以给它一个"取到语句结束分号"的抽取器。 */
function extractStatement(prefix) {
  const at = src.indexOf(prefix);
  if (at < 0) throw new Error(`找不到 ${prefix}`);
  const end = src.indexOf(';', at);
  if (end < 0) throw new Error(`${prefix} 没找到语句结束分号`);
  return src.slice(at, end + 1);
}
const ctxSrc = [
  'void 0;',
  extractLine('const AI_CODE_RE = '),
  extractLine('const AI_TOKEN_RE = '),
  extractStatement('const AI_SETTINGS_TOKENS = '),
  extract('aiSplitLinks'),
].join('\n');
// eslint-disable-next-line no-new-func
const makeApi = new Function(`${ctxSrc}\nreturn { aiSplitLinks };`);
const { aiSplitLinks } = makeApi();

console.log('[1] 本轮回归：链接只认**显式**写法，不再拿资源库名字在正文里找子串');
/* 用户原话：「我发现一个bug 我选择一个模型他之中会说xxx模型 我点击之后直接跳转到了
   对应资源页面是不对的 AI不是资源文件中含有的内容所有内容都要打下划线可点击文本的
   而是真正需要的时候才弹」→ 上一轮的 names 模糊匹配已整体移除。 */
let p1 = aiSplitLinks('我选择 Code 编辑器 和 OBS Studio 都很好用', { mention: true });
check('应用名不再被做成链接（Code / OBS Studio 都是普通文本）',
  !p1.some((p) => p.link), JSON.stringify(p1));
check('拼回去 = 原文（不吞字）',
  p1.map((p) => (p.t != null ? p.t : p.text)).join('')
    === '我选择 Code 编辑器 和 OBS Studio 都很好用',
  p1.map((p) => (p.t != null ? p.t : p.text)).join(''));
p1 = aiSplitLinks('推荐 OBS，编号 TG-000024', { mention: true });
check('裸编号仍然是链接（编号本身就是显式标识符，不会误伤）',
  p1.some((p) => p.link === 'code' && p.text === 'TG-000024'), JSON.stringify(p1));
p1 = aiSplitLinks('我用的是 deepseek-v4.1-flash 模型', { mention: true });
check('模型名/带连字符的词不会被误做成链接',
  !p1.some((p) => p.link), JSON.stringify(p1));

console.log('[2] aiSplitLinks：只认 显式 @token / 裸编号 / 设置<API Key>（无应用名匹配）');
const names = new Map([['OBS Studio', 'TG-000024'], ['Code', 'TG-000007']]);

let parts = aiSplitLinks('推荐 OBS Studio，编号 TG-000024。没 Key 去 设置<API Key> 填。',
  { names, mention: false });
const linkTexts = parts.filter((p) => p.link).map((p) => `${p.link}:${p.text}`);
check('应用名不再成链接（names 参数已废弃，传了也不生效）',
  linkTexts.indexOf('name:OBS Studio') < 0, linkTexts.join(' | '));
check('资源编号 → code 链接', linkTexts.indexOf('code:TG-000024') >= 0, linkTexts.join(' | '));
check('设置<API Key> → settings 链接', linkTexts.indexOf('settings:设置<API Key>') >= 0,
  linkTexts.join(' | '));
check('拼回去 = 原文（一个字符都不丢，纯文本可逆）',
  parts.map((p) => (p.t != null ? p.t : p.text)).join('')
  === '推荐 OBS Studio，编号 TG-000024。没 Key 去 设置<API Key> 填。',
  parts.map((p) => (p.t != null ? p.t : p.text)).join(''));

parts = aiSplitLinks('帮我看看 @OBS Studio(TG-000024) 怎么样', { names: null, mention: true });
check('用户气泡里的 @token 认成 mention（带 code + name）',
  parts.some((p) => p.mention && p.code === 'TG-000024' && p.name === 'OBS Studio'),
  JSON.stringify(parts));
check('@token 不会被拆成两段（整块可点）',
  parts.filter((p) => p.mention).length === 1);

parts = aiSplitLinks('纯文本没有可点的东西', { names, mention: true });
check('普通文本 → 只有一个纯文本片段（不产生链接）',
  parts.length === 1 && parts[0].t === '纯文本没有可点的东西', JSON.stringify(parts));

parts = aiSplitLinks('VSCode 很好用', { names, mention: false });
check('嵌在单词里的应用名不误伤（整段都该是普通文本）',
  !parts.some((p) => p.link), JSON.stringify(parts));

parts = aiSplitLinks('', { names, mention: false });
check('空串 → 空数组（模板 v-for 不画东西）', Array.isArray(parts) && parts.length === 0);

parts = aiSplitLinks('TG-000001 和 TG-000002', { names, mention: false });
check('多个编号都各自成链接',
  parts.filter((p) => p.link && p.link === 'code').length === 2,
  JSON.stringify(parts.map((p) => p.text || p.t)));

parts = aiSplitLinks('https://github.com/OBS-Studio/obs-studio 是仓库', { names, mention: false });
check('URL 不被应用名误伤成链接（OBS 出现在 URL 里）',
  !parts.some((p) => p.link && p.text === 'OBS Studio'), JSON.stringify(parts));

// 名字命中与编号命中重叠时：取**更早**的那个，且不能丢字
parts = aiSplitLinks('OBS Studio(TG-000024)', { names, mention: false });
check('重叠命中也保证可逆',
  parts.map((p) => (p.t != null ? p.t : p.text)).join('') === 'OBS Studio(TG-000024)',
  JSON.stringify(parts));

console.log('[3] 打字机步长：差距越大打得越快，但有上限（不会瞬间贴完）');
// aiTyperStep 依赖两个阈值常量，从 app.js 里原样取出来（不写死，改了也能跟上）
const cpsMin = (src.match(/AI_TYPE_MIN_CPS\s*=\s*([\d.]+)/) || [])[1];
const cpsMax = (src.match(/AI_TYPE_MAX_CPS\s*=\s*([\d.]+)/) || [])[1];
if (!cpsMin || !cpsMax) { console.log('FAIL  取不到 AI_TYPE_*_CPS 常量'); fails += 1; }
const stepSrc = extract('aiTyperStep');
const aiTyperStep = new Function(
  `const AI_TYPE_MIN_CPS = ${cpsMin}; const AI_TYPE_MAX_CPS = ${cpsMax};\n`
  + `${stepSrc}\nreturn aiTyperStep;`)();
check('16ms 一帧、差 10 字 → 至少 1 字', aiTyperStep(10, 16) >= 1);
check('差 3000 字时明显加速', aiTyperStep(3000, 16) > aiTyperStep(30, 16));
check('单帧不会超过 320cps×16ms ≈ 5 字的上限太多', aiTyperStep(20000, 16) <= 6,
  String(aiTyperStep(20000, 16)));
check('差距 0 → 0（不空转）', aiTyperStep(0, 16) === 0);
check('时间 0 → 0', aiTyperStep(100, 0) === 0);

console.log('');
if (fails) {
  console.log(`FAILED ${fails} 项`);
  process.exit(1);
}
console.log('ALL OK');
