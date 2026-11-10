/* ToolsGCP · task-3（卡片/收藏页）静态契约回归 —— Node 直接跑，无浏览器、无窗口。
 *
 * 这些点全是**行为契约**（谁先谁后、哪个值以谁为真源、哪条 CSS 不许写死），
 * 下次有人"顺手重构"就会悄悄破掉；静态断言能在自查/CI 里一句话指出破了哪条。
 * 运行时行为（Vue 挂载时序、虚拟列表窗口）由同目录 test_cards_runtime.js（jsdom）
 * 与 test_cards_layout_matrix.js 覆盖；本文件只钉"代码里必须长这样"。
 *
 * 跑法（仓库根目录）： node "项目资料-文档与开发测试/_devtest/test_cards_contracts.js"
 */
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const P = (...s) => path.join(ROOT, ...s);

const appJs = fs.readFileSync(P('.ToolsGCP', 'webui', 'js', 'app.js'), 'utf8');
const indexHtml = fs.readFileSync(P('.ToolsGCP', 'webui', 'index.html'), 'utf8');
const favCss = fs.readFileSync(P('.ToolsGCP', 'webui', 'css', 'fav-fixes.css'), 'utf8');
const compCss = fs.readFileSync(P('.ToolsGCP', 'webui', 'css', 'components.css'), 'utf8');

let fails = 0;
const results = [];
function check(label, cond, extra) {
  results.push((cond ? '  OK   ' : '  FAIL ') + label + (!cond && extra ? '  ← ' + extra : ''));
  if (!cond) fails += 1;
}
function section(name) { results.push('== ' + name + ' =='); }

/* ---------------------------------------------------------------- ① 先量后渲染 */
section('① 收藏页：先量后渲染（favMeasured 门控），列数首帧即终值');
{
  check('收藏页滚动容器带 ref=favScroller + @vue:mounted=measureFavGrid',
    /<div class="page-scroll" data-scroll-key="favorites" ref="favScroller" @vue:mounted="measureFavGrid">/.test(indexHtml));
  check('网格 v-if 同时要求 favItems.length 与 favMeasured（量完才渲染）',
    /v-if="favItems\.length && favMeasured"/.test(indexHtml));
  check('空文案不再用 v-else（防"有收藏但还没量完"闪一句空）',
    /<p v-if="!favItems\.length" class="cap center pad40">/.test(indexHtml));
  check('measureFavGrid 量的是 favScroller（常驻容器），不是网格本身',
    /function measureFavGrid\(\)\s*\{\s*const el = favScroller\.value;/.test(appJs));
  check('量到 0 时不置 favMeasured、但有 rAF 兜底放行（绝不留空白页）',
    /else favMeasured\.value = true;/.test(appJs) && /favMeasureRetry/.test(appJs));
  check('favGridObserver 改成 watch(favScroller) 随页重挂（旧 observe(favGrid.value) 恒 null）',
    /watch\(favScroller, \(el\) =>/.test(appJs) && !/favGridObserver\.observe\(favGrid\.value\)/.test(appJs));
  check('favGrid 旧 ref 已删干净（app.js 无 const favGrid = ref）',
    !/const favGrid = ref\(/.test(appJs));
  check('滚动条槽常驻预留，断开"宽度↔列数"反馈回路',
    /\.fav-main \.page-scroll \{ scrollbar-gutter: stable; \}/.test(favCss));
}

/* ---------------------------------------------------------------- ② 星标真源 */
section('② 收藏状态唯一真源：资源库重建/详情打开都必须按收藏夹重算');
{
  check('loadResources 重建 items 后立刻 syncFavoriteState()（空心星根因）',
    /items\.value = result\.items\.map\(mapItem\)[\s\S]{0,900}?syncFavoriteState\(\);/.test(appJs));
  check('openDetail 的 _fav 取 favoriteCodeSet（不抄传入卡片的旧副本）',
    /merged\._fav = favoriteCodeSet\(\)\.has\(merged\.code\);/.test(appJs));
  check('收藏页模板星标恒实心（页面语义：这里的卡必然已收藏）',
    /<button class="card-btn is-fav"[\s\S]{0,400}?#i-star_solid/.test(indexHtml));
  check('收藏页星标不再依赖 it._fav 三元',
    !/<button class="card-btn" :class="\{ 'is-fav': it\._fav \}"[\s\S]{0,200}?it\._fav \? '#i-star_solid'/.test(
      indexHtml.slice(indexHtml.indexOf('page === \'favorites\''), indexHtml.indexOf('favMenu'))));
}

/* ---------------------------------------------------------------- ③ 卡片不写死高 */
section('③ 卡片高度自适应（AGENTS.md 第 5 条：禁止 CSS 写死卡片宽高）');
{
  check('收藏页卡片 height:auto（模板给 min-height 保底）',
    /\.fav-main \.grid-static\.fav-grid > \.card \{[\s\S]{0,700}?height: auto;/.test(favCss));
  check('收藏页模板内联 minHeight（不是 height）',
    /:style="\{ minHeight: cardPx\.height \+ 'px' \}"/.test(indexHtml));
  check('定制页 .grid-static .card 从 height:196px 改成 min-height:196px',
    /\.grid-static \.card \{ width: 272px; min-height: 196px;/.test(compCss)
      && !/\.grid-static \.card \{ width: 272px; height: 196px;/.test(compCss));
  check('搜索页虚拟列表行高计入"下载页按钮多的一行"（FOOT_LINKS_H）',
    /const FOOT_LINKS_H = 32;/.test(appJs)
      && /rowH = baseH \+ \(rowNeedsLinks\(slice\) \? FOOT_LINKS_H : 0\)/.test(appJs));
}

/* ---------------------------------------------------------------- ④ 空字段不渲染 */
section('④ 详情页空字段：整行不渲染，网格收缩不留空位');
{
  check('detailRows 统一按值过滤（旧 index<4 无条件保留已删）',
    /rows\.filter\(\(row\) => String\(row\.value \|\| ''\)\.trim\(\)\)/.test(appJs)
      /* ⚠️ 断言要盯**代码形态**：旧写法是 `filter((row, index) => index < 4 || row.value)`，
         我的修复注释里也引用了这段旧代码，用宽松子串会自己打自己。 */
      && !/filter\(\(row, index\) => index < 4/.test(appJs));
  check('模板不再画破折号占位（插值形态 {{ row.value || \'—\' }} 已删）',
    !/\{\{ row\.value \|\| '—' \}\}/.test(indexHtml)
      && /<span v-if="!row\.link" class="detail-val">\{\{ row\.value \}\}<\/span>/.test(indexHtml));
  check('详细信息块全空时整块不显示',
    /<div v-if="detailRows\.length" class="detail-block">/.test(indexHtml));
  check('标签行/作者聊天行空时整行不渲染（不留 flex gap 空位）',
    /<div v-if="detailTags\.length" class="row row-6">/.test(indexHtml)
      && /<div v-if="isHttp\(detail\.author_url\) \|\| isHttp\(detail\.chat_url\)" class="row row-8">/.test(indexHtml));
}

/* ---------------------------------------------------------------- ⑤ 虚拟列表窗口 */
section('⑤ 更多筛选展开时卡片不提前消失：可视区换算到 .vlist 行坐标系');
{
  check('vRows 窗口上界 = scrollTop − vlistTop（行坐标≠滚动坐标）',
    /const top = Math\.max\(0, scrollTop\.value - vlistTop\.value\);/.test(appJs));
  check('measureVlistTop 用 rect 差 + scrollTop 换算内容偏移',
    /function measureVlistTop\(\)/.test(appJs)
      && /list\.getBoundingClientRect\(\)\.top - el\.getBoundingClientRect\(\)\.top\s*\+\s*el\.scrollTop/.test(appJs));
  check('measureViewport 每次都带量 vlistTop',
    /function measureViewport\(\)[\s\S]{0,300}?measureVlistTop\(\);/.test(appJs));
  check('滚动每帧刷新 vlistTop（筛选 180ms 过渡期间窗口跟得上）',
    /rafId = requestAnimationFrame\(\(\) => \{\s*rafId = 0;\s*measureVlistTop\(\);/.test(appJs));
  check('toggleFilter 开合后重测（nextTick + 220ms 过渡结束各一次）',
    /function toggleFilter\(\)[\s\S]{0,500}?setTimeout\(\(\) => \{ measureVlistTop\(\); \}, 220\);/.test(appJs));
  check('vlistTop / measureViewport 已暴露给测试接缝',
    /vlistTop, measureViewport,/.test(appJs));
}

const total = results.filter((s) => /^  (OK|FAIL)/.test(s)).length;
console.log(results.join('\n'));
console.log(fails ? '\n=== 结论：' + fails + ' 项失败（共 ' + total + ' 项）==='
  : '\n=== 结论：全部通过（共 ' + total + ' 项）===');
process.exit(fails ? 1 : 0);
