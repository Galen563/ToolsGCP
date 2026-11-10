/* ToolsGCP 本轮需求的前端静态契约回归（Node 直接跑，无依赖）。
 *
 * 覆盖用户这轮提的、可以靠"读源码断言"守住的前端项：
 *   ① 「隐藏左侧栏元素」+F9 已按要求**删除**（反向断言，防留半个实现）
 *   ② AI 气泡按钮：放大 / 重新生成与复制换位 / 版本树在复制右边 / ◀ n ▶ 中间是纯文字
 *   ③ 定制页「已收藏 / 未收藏」= 筛选（不是排序）
 *   ④ 浏览器模式：顶部栏隐藏 + F11 交给浏览器原生
 *   ⑤ 图标：设置「快捷键」分区=键盘；GCP工坊=扳手（用户要求恢复原样）
 *
 * 为什么用"断言源码"而不是只靠肉眼：这些点全是**行为契约**（谁在谁右边、
 * 哪个键不落盘、切换后要不要过滤），下次有人"顺手重构"就会悄悄破掉；
 * 静态断言能在 CI/自查里一句话指出破了哪条。真正的交互手感仍需起预览页过一遍。
 *
 * 跑法： node "项目资料-文档与开发测试/_devtest/test_frontend_features.js"
 */
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const P = (...s) => path.join(ROOT, ...s);

const appJs = fs.readFileSync(P('.ToolsGCP', 'webui', 'js', 'app.js'), 'utf8');
const indexHtml = fs.readFileSync(P('.ToolsGCP', 'webui', 'index.html'), 'utf8');
const iconsJs = fs.readFileSync(P('.ToolsGCP', 'webui', 'js', 'icons.js'), 'utf8');
const baseCss = fs.readFileSync(P('.ToolsGCP', 'webui', 'css', 'base.css'), 'utf8');
const aiCss = fs.readFileSync(P('.ToolsGCP', 'webui', 'css', 'ai-fixes.css'), 'utf8');
const compCss = fs.readFileSync(P('.ToolsGCP', 'webui', 'css', 'components.css'), 'utf8');
const layoutCss = fs.readFileSync(P('.ToolsGCP', 'webui', 'css', 'layout.css'), 'utf8');

let fails = 0;
const results = [];
function check(label, cond, extra) {
  results.push((cond ? '  OK   ' : '  FAIL ') + label + (!cond && extra ? '  ← ' + extra : ''));
  if (!cond) fails += 1;
}
function section(name) { results.push('== ' + name + ' =='); }

/* ---------------------------------------------------------------- ① 隐藏左侧栏：已删除 */
section('① 「隐藏左侧栏元素」/ F9 已按要求删除（反向断言，防止留半个实现）');
{
  check('设置页里没有 nav_hide_* 行', !/key: 'nav_hide_elements'/.test(appJs)
        && !/key: 'nav_hide_search'/.test(appJs) && !/nav_hide_settings/.test(appJs));
  check('前端默认配置里没有 nav_hide_* 键', !/nav_hide_elements: false/.test(appJs));
  check('nav 的隐藏机制（navHiddenKeys/navVisible/navRevealAll/NAV_HIDEABLE）已移除',
        !/const navHiddenKeys/.test(appJs) && !/function navVisible/.test(appJs)
          && !/const navRevealAll/.test(appJs) && !/const NAV_HIDEABLE/.test(appJs));
  check('F9 分支已移除（onKeydown 里不再有 F9）', !/event\.key === 'F9'/.test(appJs));
  check('navTop / navBottom 不再做 navVisible 过滤',
        !/navVisible\(it\.key\)/.test(appJs));
  check('侧栏恢复原样：GCP工坊重新使用 developer（扳手）图标',
        /key: 'workshop'.*icon: 'developer'/.test(appJs));
  check('不再渲染 i-workshop（那个自定义图标已删除）',
        !/id="i-workshop"/.test(appJs) && !/^  workshop: /m.test(iconsJs));
}

/* ---------------------------------------------------------------- ①b 本轮新需求 */
section('①b 本轮：卡片等宽 / 编辑框不折行 / 重生成就地取代气泡');
{
  /* 定制页卡片"长度不规范、被强制拉伸"：flex 允许拉伸是根因 */
  check('网格卡片不再允许拉伸（flex: 0 0 272px）',
        /\.grid-static \.card \{[^}]*flex: 0 0 272px/.test(compCss),
        'components.css 里 .grid-static .card 还是可拉伸的');
  check('收藏夹那条覆盖也同步成不拉伸',
        /\.fav-main \.grid-static \.card \{[^}]*flex: 0 0 272px/.test(layoutCss),
        'layout.css 里 .fav-main 的卡片还在 flex:1 1 272px');

  /* 编辑框"一行变两行"：border 改 outline（border-box 下 border 会吃掉 2px 内容宽度）*/
  check('编辑框不再用 border（改用 outline，零布局影响）',
        /\.bubble\.ai-bubble-edit[^}]*border: 0;/.test(aiCss)
          && /\.bubble\.ai-bubble-edit[^}]*outline: 1px solid var\(--accent\)/.test(aiCss),
        'ai-bubble-edit 还在用 border');
  check('编辑框显式钉住 pre-wrap（换行行为与气泡一致）',
        /\.bubble\.ai-bubble-edit[^}]*white-space: pre-wrap/.test(aiCss));

  /* 重新生成：原气泡被"正在…"取代 + 下面旧分支让位 */
  check('原气泡被 aiRegenPlaceholder(i) 就地取代（不是多挂一颗）',
        indexHtml.indexOf('aiRegenPlaceholder(i)') >= 0
          && /function aiRegenPlaceholder/.test(appJs));
  check('两处 AI 模板都做了（独立 AI 页 + 悬浮球抽屉）',
        (indexHtml.match(/aiRegenPlaceholder\(i\)/g) || []).length >= 2,
        '只改了一处，另一处会不一致');
  check('处理期间把被改那条之后的既有内容藏起来（aiRowShown）',
        indexHtml.indexOf('aiRowShown(i)') >= 0 && /function aiRowShown/.test(appJs)
          && /aiCutAfter/.test(appJs));
  check('两处 AI 模板都用 aiRowShown 收尾藏尾',
        (indexHtml.match(/aiRowShown\(i\)/g) || []).length >= 2);
  check('重新生成会把 cutAfter 传下去', /cutAfter: index/.test(appJs));
  check('编辑重发也传 cutAfter（用户说"用户的编辑也一样"）',
        /userIndex: index, cutAfter: index/.test(appJs));
}


/* ---------------------------------------------------------------- ② AI 气泡按钮 */
section('② AI 气泡：按钮放大 / 换位 / 版本树在复制右边 / ◀ n ▶');
{
  const pageBlock = indexHtml.slice(indexHtml.indexOf('<!-- AI 侧边栏整页-->'),
                                    indexHtml.indexOf('「AI正在查看问题...」：只在这行渲染'));
  const aiRow = pageBlock.slice(pageBlock.indexOf('<template v-else>'));
  const iRegen = aiRow.indexOf('aiRegenerate(i)');
  const iCopy = aiRow.indexOf('copyText(m.text)');
  const iNav = aiRow.indexOf('class="variant-nav"');
  check('重新生成按钮在复制**左边**（两者换位）', iRegen >= 0 && iCopy >= 0 && iRegen < iCopy,
        `regen=${iRegen} copy=${iCopy}`);
  check('版本树 ◀ n ▶ 在复制**右边**', iNav > iCopy && iCopy >= 0, `nav=${iNav} copy=${iCopy}`);
  check('气泡按钮放大（≥ 24px，不再是 18px）',
        /\.bubble-btn \{\s*\n?\s*width: (2[4-9]|[3-9]\d)px/.test(compCss),
        '没在 components.css 找到放大后的 .bubble-btn 宽度');
  check('版本导航按钮同尺寸（不会一排高低不齐）',
        /\.variant-nav \.vn-btn \{\_[\s\S]{0,200}?width: (2[4-9]|[3-9]\d)px/
          .test(aiCss.replace(/[^\x00-\xFF]/g, (c) => c)) || /width: 26px;\n  height: 26px/.test(aiCss),
        'vn-btn 宽度未跟上');
  check('旧的 18px 覆盖已删除（否则放大无效）',
        !/\.bubble-actions \.bubble-btn \{ height: 18px/.test(aiCss));
  /* ◀ n ▶：中间那段文字必须是**普通文本节点**，不是"组件外壳" */
  check('中间 n 是 vn-page 里的纯插值文字',
        /<span class="vn-page">\{\{ aiVariantPage\(m\) \}\}\/\{\{ aiVariantCount\(m\) \}\}<\/span>/.test(indexHtml));
  check('版本外壳不再画底色（n 不是"一个组件 ui"）',
        /\.variant-nav \{\n?[\s\S]{0,420}?background: none/.test(aiCss),
        'variant-nav 还留着底色');
  check('只有一版时不渲染版本树', /v-if="aiVariantCount\(m\) > 1" class="variant-nav"/.test(indexHtml));
}

/* ---------------------------------------------------------------- ③ 定制页收藏筛选 */
section('③ 定制页：已收藏 / 未收藏 = 筛选（不是排序）');
{
  const seg = appJs.slice(appJs.indexOf('const recommendations = computed'),
                          appJs.indexOf('const recommendGroups = computed'));
  check('fav/unfav 走 filter 而不是 sort',
        /mode === 'fav' \|\| mode === 'unfav'/.test(seg) && /scored\.filter/.test(seg),
        '没找到筛选分支');
  check('筛选口径和搜索页一致（!!it._fav === want）',
        /const want = mode === 'fav';[\s\S]{0,120}!!it\._fav === want/.test(seg));
  check('旧那版"只排序不过滤"的写法已消失',
        !/Number\(!!b\._fav\) - Number\(!!a\._fav\)/.test(seg));
  check('收藏档全空时有专属空态文案（不说假话）', (() => {
    /* ⚠️ 这段断言要单独切：emptyRecommendTitle 在 recommendGroups **之后**，
       用上面那个 [recommendations, recommendGroups) 的片段去查永远查不到，
       假失败一次踩过就记住了。 */
    const title = appJs.slice(appJs.indexOf('const emptyRecommendTitle'),
                              appJs.indexOf('function onRecommendClick'));
    return /customSort\.value === 'fav'[\s\S]{0,160}empty_no_fav/.test(title)
        && /customSort\.value === 'unfav'[\s\S]{0,160}empty_no_unfav/.test(title);
  })());
  ['zh_CN', 'zh_TW', 'en_US'].forEach((l) => {
    const dict = JSON.parse(fs.readFileSync(P('.ToolsGCP', 'modules', 'languages', l,
                                              'customize_language.json'), 'utf8'));
    check(`${l}: empty_no_fav / empty_no_unfav 已补`,
          !!dict.empty_no_fav && !!dict.empty_no_unfav);
  });
  /* 「隐藏左侧栏元素」已删除 → 那几个文案键也必须一起清掉，
     否则语言文件里会留下一堆永远不会被引用的死文案。 */
  ['zh_CN', 'zh_TW', 'en_US'].forEach((l) => {
    const dict = JSON.parse(fs.readFileSync(P('.ToolsGCP', 'modules', 'languages', l,
                                              'set_language.json'), 'utf8'));
    const stale = ['nav_hide_elements', 'nav_hide_elements_tip', 'nav_hide_settings_tip',
                   'nav_f9_tip', 'nav_reveal_on', 'nav_reveal_off'].filter((k) => k in dict);
    check(`${l}: 已删功能的文案键不存在`, stale.length === 0, stale);
  });
}

/* ---------------------------------------------------------------- ④ 浏览器模式外壳 */
section('④ 浏览器模式：隐藏顶部栏 / F11 交浏览器原生');
{
  check('<html> 打 is-browser-mode 标记',
        /document\.documentElement\.classList\.add\('is-browser-mode'\)/.test(appJs));
  check('CSS：浏览器模式隐藏标题栏',
        /html\.is-browser-mode \.titlebar \{ display: none !important; \}/.test(baseCss));
  check('CSS：--tb-height 归零（浮层不再留 48px 空档）',
        /html\.is-browser-mode \{ --tb-height: 0px; \}/.test(baseCss));
  check('CSS：浏览器模式撤掉窗口缩放热区',
        /html\.is-browser-mode \.win-resize \{ display: none/.test(baseCss));
  check('桌面端不受影响（规则全部带 html.is-browser-mode 前缀）',
        !/\n\.titlebar \{ display: none/.test(baseCss));
  /* F11：浏览器模式下**不能** preventDefault，否则浏览器原生全屏也不来了 */
  const kd = appJs.slice(appJs.indexOf('function onKeydown(event)'),
                         appJs.indexOf('function onKeydown(event)') + 2200);
  const f11 = kd.slice(kd.indexOf("if (event.key === 'F11')"));
  check('F11 在浏览器模式下提前 return（不 preventDefault、不调后端）',
        /if \(window\.ToolsGCP\.browserMode \|\| httpBridge\.active\) return;/.test(f11));
  check('F11 在桌面端仍然 preventDefault + toggleFullscreen（行为不变）',
        /event\.preventDefault\(\);\s*\n?\s*toggleFullscreen\(\);/.test(f11));
  check('F11 分支排在 F9 之后（两个键互不干扰）',
        kd.indexOf("if (event.key === 'F9')") < kd.indexOf("if (event.key === 'F11')"));
}

/* ---------------------------------------------------------------- ⑤ 图标 */
section('⑤ 图标：快捷键=键盘（保留）；GCP工坊=扳手（已按要求恢复原样）');
{
  check('keyboard 图标仍在（设置·快捷键分区用）', /^  keyboard: /m.test(iconsJs));
  check('设置「快捷键」分区用 keyboard（不是齿轮）', /hotkey: 'keyboard'/.test(appJs));
  /* 本轮用户要求「GCP工坊图标恢复原样」→ 侧栏改回 developer(扳手)，自定义 workshop 图标删除 */
  check('侧栏 GCP工坊 用回 developer（扳手）图标',
        /key: 'workshop'.*icon: 'developer'/.test(appJs));
  check('自定义 workshop 图标已从精灵里删除', !/^  workshop: /m.test(iconsJs));
  check('developer（扳手）图标本身没被改坏',
        /^  developer: '<g transform=/m.test(iconsJs));
  check('dev 分区仍是 developer（没被顺手改掉）', /dev: 'developer'/.test(appJs));
  check('keyboard 是键盘形状（外壳 rect + 三排键）',
        /<rect x="3" y="6\.6" width="18" height="10\.8" rx="2"\/>/.test(iconsJs));
}

/* ---------------------------------------------------------------- ⑥ 常量登记 */
section('⑥ 后端 DEFAULT_SETTINGS 与配置一致性');
{
  const constants = fs.readFileSync(P('.ToolsGCP', 'modules', 'pymodels', 'constants.py'), 'utf8');
  /* 「隐藏左侧栏元素」已按要求删除：配置键也必须一起删干净，
     否则用户配置里会永远残留 9 个死键（合并循环还会把它们补回去）。 */
  check('constants.py 里不再有任何 nav_hide_* 键',
        !/nav_hide_/.test(constants));
  check('constants.py 里不再有 nav_reveal/nav_f9 之类的 F9 状态键',
        !/nav_reveal|nav_f9|hide_reveal/.test(constants));
  /* 本轮快捷键默认值：Ctrl+Shift+O（后端默认必须有，且不再用 Caps） */
  check('hotkey_browser 默认值是 Ctrl+Shift+O',
        /"hotkey_browser": "Ctrl\+Shift\+O"/.test(constants),
        'constants.py 里还不是 Ctrl+Shift+O');
  check('前端"恢复默认"与后端默认值一致（都是 Ctrl+Shift+O）',
        /hotkey_browser: 'Ctrl\+Shift\+O'/.test(appJs),
        'app.js 的 resetHotkey 默认值没跟上');
  /* 三语里不再残留已删功能的文案键 */
  ['zh_CN', 'zh_TW', 'en_US'].forEach((l) => {
    const dict = JSON.parse(fs.readFileSync(
      P('.ToolsGCP', 'modules', 'languages', l, 'set_language.json'), 'utf8'));
    const stale = Object.keys(dict).filter((k) =>
      k.startsWith('nav_hide') || k.startsWith('nav_reveal') || k === 'nav_f9_tip');
    check(`${l}: 已删功能的文案键全部清除`, stale.length === 0, stale);
  });
}

console.log(results.join('\n'));
console.log('\n=== 结论：' + (fails === 0 ? '全部通过（' + (results.length - results.filter((r) => r.startsWith('==')).length) + ' 项）' : fails + ' 项失败') + ' ===');
results.filter((r) => r.startsWith('  FAIL')).forEach((r) => console.log(r));
process.exit(fails === 0 ? 0 : 1);
