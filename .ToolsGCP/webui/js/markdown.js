/* ============================================================================
 * ToolsGCP · 内置 Markdown → HTML 渲染器（零依赖，不用 marked/showdown）
 * ============================================================================
 * 为什么要有这个文件
 *   公告（GitHub Issue 正文）和「发现新版本」的更新说明（Release 正文）本来就是
 *   Markdown。以前前端要么用 stripMarkdown() 把它擦成纯文本、要么原样贴出，用户
 *   看到的是 `**加粗**` `# 标题` `[链接](url)` 这种**源码**。项目约定不引入运行
 *   时依赖也不上构建链（AGENTS.md 第 7 节），所以这里自研一个够用的子集：
 *     标题 / 段落 / 有序无序列表（任意层嵌套）/ 任务清单 / 引用 / 分隔线 /
 *     围栏代码块 / 行内代码 / 粗体·斜体·删除线 / 链接 / 自动链接 / 图片 /
 *     反斜杠转义，以及 GitHub 正文里常见的少量原生 HTML（<br> <img> <a> <b>…）。
 *
 * ⚠️ XSS 策略（这是本文件能存在的前提，改之前必须读懂）
 *   1) **先转义再转换**：所有文本在进入 HTML 之前一律做实体转义（& < > " '）。
 *      Markdown 语法字符不参与转义，所以后面插进结果的标签只有我们自己拼的那些。
 *   2) 原文里的裸 HTML **一律不保留**。只有白名单标签会被"翻译"成等价的安全标签，
 *      其余标签的标记直接丢掉（保留里面的文字），属性一个都不继承。
 *   3) 链接 / 图片的 URL 只允许 http / https / mailto；`javascript:` `data:`
 *      `file:` `v-for` 之类一律降级成纯文本（链接丢外壳、图片丢 alt 之外的一切）。
 *   4) 渲染出的链接是 `<a class="md-link" data-mdlink="…">`，**没有 href、没有
 *      target=_blank**：不会触发 WebView2 自己开新窗口那套行为（见 app.js 里
 *      onModifiedLinkClick 的长注释），点击由 app.js 统一拦截走 openLink →
 *      shell.open_url（系统浏览器）。
 *   5) 输入里的 C0 控制字符（含 \u0000）先清掉，避免我们用来占位的 \u0001 定界符
 *      被正文伪造。
 *
 * 用法（经典脚本，和 icons.js / rich-input.js 一样挂全局）
 *   ToolMarkdown.render(mdText)          → 可直接交给 v-html 的安全 HTML 片段
 *   ToolMarkdown.truncate(mdText, 2000)  → 按 Markdown 边界截断，不留半个语法标记
 *   ToolMarkdown.escapeHtml(text)        → 只做转义（调用方降级路径用）
 *   render() 内部**不会**抛异常到调用方以外的假设 —— 调用方仍应 try/catch 并降级，
 *   因为这段文本最终是要显示给用户的，宁可退回纯文本也不能显示空白。
 * ==========================================================================*/
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : globalThis;

  var TK = '\u2063';                              // 占位符定界符（ invisible separator）
  /* ⚠️ 分隔符**不能**选 C0 控制字符：inlineSpan() 一进来就要清掉正文里的控制字符
     （防止正文伪造 token），选 \u0001 那种会把我们自己生成的 token 一起清掉 ——
     表现就是嵌套语法（徽章 `[![img](src)](link)`）渲染成光秃秃的数字。
     所以选 \u2063 这种"格式字符"：正文里出现概率极低，且被 SENTINEL 清掉即可。 */
  var TK_RE = new RegExp(TK + '(\\d+)' + TK, 'g');
  var SENTINEL_RE = new RegExp(TK, 'g');
  var C0 = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g;
  var URL_OK = /^(?:https?|mailto):/i;             // 协议白名单（不引入其它）
  /* URL 部分：允许一层配对括号（真实链接里 `.../Foo_(bar)` 很常见，
     比如 Wikipedia / 部分 shields 徽章），也允许反斜杠转义的括号。 */
  var URL_ONE = '(?:\\\\.|[^\\s()\\\\]|\\((?:\\\\.|[^\\s()\\\\])*\\))*';
  var IMG_INLINE_RE = new RegExp('!\\[([^\\]]*)\\]\\(\\s*(?:<([^<>]*)>|(' + URL_ONE +
    '))(?:\\s+(?:"[^"]*"|\'[^\']*\'|\\([^)]*\\)))?\\s*\\)', 'g');
  var LINK_INLINE_RE = new RegExp('\\[([^\\]]+)\\]\\(\\s*(?:<([^<>]*)>|(' + URL_ONE +
    '))(?:\\s+(?:"[^"]*"|\'[^\']*\'|\\([^)]*\\)))?\\s*\\)', 'g');
  var LIST_RE = /^(\s*)(?:([-*+])|(\d{1,9})[.)])[ \t]+([\s\S]*)$/;
  var FENCE_RE = /^ {0,3}(`{3,}|~{3,})/;
  var HR_RE = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
  var HEAD_RE = /^ {0,3}(#{1,6})[ \t]+([\s\S]*?)[ \t]*#*[ \t]*$/;
  var QUOTE_RE = /^ {0,3}>[ \t]?([\s\S]*)$/;

  /* ---------- 基础工具 ---------- */

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /* 码点 → 字符（HTML 数字实体用）。代理区码点直接换成 U+FFFD：
     它单独出现时不是合法字符，String.fromCodePoint 也会产出一个坏字符串。 */
  function safeChar(code) {
    if (code >= 0xD800 && code <= 0xDFFF) return '\uFFFD';
    try { return String.fromCodePoint(code); } catch (e) { return '\uFFFD'; }
  }

  /* 校验协议并去掉控制字符；返回可安全写进属性的 URL（注意：调用方还要自己转义） */
  function safeUrl(raw) {
    var url = String(raw == null ? '' : raw).trim().replace(C0, '')
      .replace(/^<|>$/g, '');
    return URL_OK.test(url) ? url : '';
  }

  /* 链接外壳：不合法协议 → 只返回内部 HTML（等价降级为纯文本） */
  function linkHtml(href, inner) {
    var url = safeUrl(href);
    if (!url) return inner;
    return '<a class="md-link" data-mdlink="' + escapeHtml(url) + '">' + inner + '</a>';
  }

  /* 裸 URL 的收尾整形：把「句末标点」和「包住 URL 的那个右括号」从尾部剥掉；
     内部成对括号（Wikipedia 的 /wiki/Foo_(bar)）要保住。
     ⚠️ 必须在**贪心**匹配之后调用 —— 只有拿到最长候选，才知道尾巴上哪些是句子标点。 */
  function trimBareUrl(raw) {
    var u = String(raw == null ? '' : raw);
    /* 1) 反复剥句末标点：点 / 逗号 / 分号 / 冒号 / 感叹号 / 问号 / 引号 / 省略号 */
    for (;;) {
      var next = u.replace(/[.,;:!?'"\u2026]+$/, '');
      if (next === u) break;
      u = next;
    }
    /* 2) 括号配平：右括号比左括号多，说明这个 ")" 是句子里的（(见 https://…/x)） */
    while (/\)$/.test(u) &&
      (u.match(/\)/g) || []).length > (u.match(/\(/g) || []).length) {
      u = u.slice(0, -1);
    }
    /* 3) 只剩协议头的（"https://" 后面什么都没有）不当链接 */
    return u.length > 8 ? u : '';
  }

  function imgHtml(src, alt) {
    var url = safeUrl(src);
    if (!url) return escapeHtml(alt || '');
    return '<img class="md-img" loading="lazy" alt="' + escapeHtml(alt || '') +
      '" src="' + escapeHtml(url) + '">';
  }

  /* ---------- 成对语法（避免孤立标签造成"整段变粗体/整段变链接"） ----------
     先把**配对完整**的标签换成我们自己的标签，剩下的标签标记（包括没配对的）在
     通用那一步全部丢掉。这样产物里的开闭标签永远成对。 */
  var PAIRED = [
    [/(?:<b\b[^>]*>)([\s\S]{0,600}?)(?:<\/b>)/gi, '<strong class="md-strong">', '</strong>'],
    [/(?:<strong\b[^>]*>)([\s\S]{0,600}?)(?:<\/strong>)/gi, '<strong class="md-strong">', '</strong>'],
    [/(?:<i\b[^>]*>)([\s\S]{0,600}?)(?:<\/i>)/gi, '<em class="md-em">', '</em>'],
    [/(?:<em\b[^>]*>)([\s\S]{0,600}?)(?:<\/em>)/gi, '<em class="md-em">', '</em>'],
    [/(?:<(?:s|del|strike)\b[^>]*>)([\s\S]{0,600}?)(?:<\/(?:s|del|strike)>)/gi, '<del class="md-del">', '</del>'],
    [/(?:<code\b[^>]*>)([\s\S]{0,600}?)(?:<\/code>)/gi, '<code class="md-code">', '</code>'],
    [/(?:<kbd\b[^>]*>)([\s\S]{0,600}?)(?:<\/kbd>)/gi, '<kbd class="md-kbd">', '</kbd>'],
    [/(?:<u\b[^>]*>)([\s\S]{0,600}?)(?:<\/u>)/gi, '<span class="md-u">', '</span>'],
    [/(?:<sup\b[^>]*>)([\s\S]{0,600}?)(?:<\/sup>)/gi, '<sup class="md-sup">', '</sup>'],
    [/(?:<sub\b[^>]*>)([\s\S]{0,600}?)(?:<\/sub>)/gi, '<sub class="md-sub">', '</sub>'],
    /* 徽章排版：<a href="合法链接"><img src="合法图"></a> → 一个可点的图片链接 */
    [/<a\b[^>]*href\s*=\s*(?:"([^"]*)"|'([^']*)')[^>]*>\s*<img\b[^>]*src\s*=\s*(?:"([^"]*)"|'([^']*)')(?:[^>]*?)(?:alt\s*=\s*(?:"([^"]*)"|'([^']*)'))?[^>]*>\s*<\/a>/gi,
      function (m, h1, h2, s1, s2, a1, a2) {
        return linkHtml(h1 || h2, imgHtml(s1 || s2, a1 || a2 || ''));
      }],
    /* 普通 <a>…</a> 内联（不含图片的情况） */
    [/<a\b[^>]*href\s*=\s*(?:"([^"]*)"|'([^']*)')[^>]*>([\s\S]{0,600}?)<\/a>/gi,
      function (m, h1, h2, inner) { return linkHtml(h1 || h2, inner); }],
  ];

  /* ---------- 行内层：转义 + 我们自己的标签 ---------- */

  /* 入口净化：清掉正文里的控制字符 + 可能伪造的占位符分隔符。
     ⚠️ 只在 render() 入口做一次，**不要**放进 inlineSpan：inlineSpan 会被递归调用
        （链接文字里再套图片/粗体），第二次进去时字符串里已经是**我们自己生成的 token**，
        再清一次就会把 token 抹成裸数字（徽章 `[![img](src)](link)` 变 "0" 的真因）。 */
  function cleanse(value) {
    return String(value == null ? '' : value).replace(C0, '').replace(SENTINEL_RE, '');
  }

  function inlineSpan(raw, store) {
    var s = String(raw == null ? '' : raw);

    /* 0) 反斜杠转义（\* \[ 之类）先保护成"字面字符"，后面语法阶段不再当它是标记 */
    s = s.replace(/\\([\\`*_{}\[\]()#+\-.!>~|])/g, function (m, ch) {
      return keep(store, escapeHtml(ch));
    });

    /* 1) 行内代码：`x` / ``x`` —— 内容一律转义，内部不再做别的解析 */
    s = s.replace(/(`+)([\s\S]*?)\1/g, function (m, ticks, code) {
      return keep(store, '<code class="md-code">' +
        escapeHtml(code.replace(/^ (.*) $/, '$1')) + '</code>');
    });

    /* 2) 图片：![alt](url "title")（放在链接之前，否则会先被链接规则吃掉） */
    s = s.replace(IMG_INLINE_RE, function (m, alt, angle, url) {
      return keep(store, imgHtml(angle || url, alt));
    });

    /* 3) 链接：[文字](url "title")；文字部分再走一次行内解析（可以嵌套粗体等） */
    s = s.replace(LINK_INLINE_RE, function (m, label, angle, url) {
      return keep(store, linkHtml(angle || url, inlineSpan(label, store)));
    });

    /* 4) 引用式链接 [文字][编号]：没有链接表，退化成"文字" */
    s = s.replace(/\[([^\]]+)\]\[\w*\]/g, function (m, label) {
      return keep(store, inlineSpan(label, store));
    });

    /* 5) 尖括号自动链接 <https://…>；必须在转义前处理（此时 < 还是原文） */
    s = s.replace(/<((?:https?|ftp):\/\/[^\s<>]+)>/gi, function (m, url) {
      return keep(store, linkHtml(url, escapeHtml(url)));
    });

    /* 6) 原生 HTML：先处理需要属性的（br / img），再处理成对的，最后丢掉所有残留标记 */
    s = s.replace(/<img\b[^>]*>/gi, function (m) {
      var src = attrOf(m, 'src');
      return keep(store, imgHtml(src, attrOf(m, 'alt')));
    });
    PAIRED.forEach(function (rule) {
      var repl = rule[1], close = rule[2];
      if (typeof repl === 'function') { s = s.replace(rule[0], function () {
        var html = repl.apply(null, arguments);
        return html == null ? '' : keep(store, html);
      }); return; }
      s = s.replace(rule[0], function (m, inner) {
        return keep(store, repl) + inlineSpan(inner, store) + keep(store, close);
      });
    });
    s = s.replace(/<br\s*\/?>/gi, function () { return keep(store, '<br>'); });
    /* script / style 连同**内容**一起删（和 GitHub 的表现一致）：
       只删标记会把里面的代码留成一行可见文字，反而让人以为是正文。 */
    s = s.replace(/<(?:script|style)\b[^>]*>[\s\S]*?<\/(?:script|style)\s*>/gi, '');
    /* 其余标签：丢掉标记保留文字。孤立闭标签也在这里被清掉，产物不会不配平。
       ⚠️ 这里**不要**再补一条"吃掉没有 > 收尾的尾巴"的兜底：正文里 `a<b 就坏了`
       这种普通文本会被它整段吞掉（用户看到的就是"后半句没了"）。没配对的 < 交给
       下一步转义，浏览器会原样显示成 <，和 GitHub 的表现一致。 */
    s = s.replace(/<\/?[a-zA-Z][^>]*>/g, '');

    /* 6.5) HTML 实体还原（&amp; / &lt; / &nbsp; …）：GitHub 把实体当字符渲染，
       不还原的话 `A &amp; B` 会显示成 "A &amp; B"。
       单趟替换里 &amp; 天然排在最后被处理（`&amp;lt;` 先命中 &amp; → 还原成
       &lt; 文本，不会再被当成转义），不需要额外排序。 */
    s = s.replace(/&(?:#(\d{1,7})|#[xX]([0-9a-fA-F]{1,6})|(amp|lt|gt|quot|apos|nbsp));/g,
      function (m, dec, hex, name) {
        if (dec) { var code = Number(dec); return code > 0 && code <= 0x10FFFF ? safeChar(code) : m; }
        if (hex) { var code2 = parseInt(hex, 16); return code2 > 0 && code2 <= 0x10FFFF ? safeChar(code2) : m; }
        return { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: '\u00a0' }[name] || m;
      });

    /* 7) 现在才转义剩下的文本 */
    s = escapeHtml(s);

    /* 8) 自动链接裸 URL（转义后做，避免把 token 里的内容当文本）
          注意 & 已变成 &amp;，所以匹配时把 &amp; 也当作 URL 字符。
          ⚠️⚠️ 这里**必须贪心**取最长候选，再交给 trimBareUrl 剥尾巴。老版本写的是
             `(https?:\/\/[^…]+?[^…\.!?,:])`：这个懒量词后面只有一个字符类、又没有任何
             锚点，replace 里最小匹配就是"协议 + 2 个字符" —— 于是公告里写
             `https://github.com/xxx/yyy`，渲染出来只有 `https://gi` 是链接、后面全是纯文本
             （用户原话：「我写的是完整链接，结果程序公告上的链接只有一部分，后面的还是文本内容」）。 */
    s = s.replace(/(^|[\s(（【「『:：,，、;；])(https?:\/\/[^\s<>"'。；，、）】」》「『（《]+)/gi,
      function (m, pre, raw) {
        var url = trimBareUrl(raw);
        if (!url) return m;
        /* 被 trimBareUrl 剥掉的尾巴（句子里的 ")"、句末的 "." 等）是**正文**，
           必须原样接回链接后面；否则 "(见 https://a.com/b)" 会少一个右括号。 */
        var tail = raw.slice(url.length);
        var plain = url.replace(/&amp;/g, '&');
        return pre + keep(store, linkHtml(plain, url)) + tail;
      });

    /* 9) 粗体 / 斜体 / 删除线（只插我们自己的标签；跨行的不处理） */
    s = s.replace(/\*\*\*([^\s*][^*]*?)\*\*\*/g,
      '<strong class="md-strong"><em class="md-em">$1</em></strong>');
    s = s.replace(/\*\*([^\s*][^*]*?)\*\*/g, '<strong class="md-strong">$1</strong>');
    s = s.replace(/(^|[^0-9A-Za-z_])__([^_][^_]*?)__(?=[^0-9A-Za-z_]|$)/g,
      '$1<strong class="md-strong">$2</strong>');
    s = s.replace(/(^|[^0-9A-Za-z_*])\*([^*\s][^*]*?)\*(?=[^0-9A-Za-z_*]|$)/g,
      '$1<em class="md-em">$2</em>');
    s = s.replace(/(^|[^0-9A-Za-z_])_([^_\s][^_]*?)_(?=[^0-9A-Za-z_]|$)/g,
      '$1<em class="md-em">$2</em>');
    s = s.replace(/~~([^~][^~]*?)~~/g, '<del class="md-del">$1</del>');

    return s;
  }

  /* 从 HTML 标签原文里取属性（引号包起来或不带引号的单个 token） */
  function attrOf(tag, name) {
    var m = new RegExp('\\b' + name + '\\s*=\\s*(?:"([^"]*)"|\'([^\']*)\'|([^\\s"\'>]+))', 'i').exec(tag);
    return m ? (m[1] || m[2] || m[3] || '') : '';
  }

  /* ---------- 占位符（保护已生成的片段不被后续规则二次处理） ---------- */
  function keep(store, html) {
    store.push(html);
    return TK + (store.length - 1) + TK;
  }
  function restore(s, store) {
    var text = s, pass = 0;
    /* 产物里可能还嵌着 token（嵌套链接 / 粗体里的链接），迭代展开；上限防死循环 */
    while (pass < 12 && TK_RE.test(text)) {
      TK_RE.lastIndex = 0;
      text = text.replace(TK_RE, function (m, n) {
        var v = store[Number(n)];
        return v == null ? '' : v;
      });
      pass += 1;
    }
    /* 兜底：万一分隔符没配上，绝不让控制字符出现在 HTML 里 */
    return text.replace(new RegExp(TK + '\\d*' + TK, 'g'), '').replace(new RegExp(TK, 'g'), '');
  }

  /* ---------- 块级层 ---------- */
  /* ---------- 表格（GFM）----------
     GitHub 的公告 / Release 正文里会贴表格，老渲染器完全不认识，于是
     `| 版本 | 日期 |` 原样输出成一堆竖线 —— 用户看到的就是"部分显示不正确"。
     判定按 GFM：上一行是表头（含 |），下一行是 `---` / `:---:` 分隔行。 */

  /* 把一行拆成单元格：支持 \| 转义、首尾可选的边框竖线 */
  function splitTableRow(line) {
    var s = String(line == null ? '' : line).trim();
    if (s.indexOf('|') < 0) return null;
    if (s.charAt(0) === '|') s = s.slice(1);
    if (s.charAt(s.length - 1) === '|' && s.charAt(s.length - 2) !== '\\') s = s.slice(0, -1);
    var cells = [], buf = '', esc = false;
    for (var k = 0; k < s.length; k += 1) {
      var ch = s.charAt(k);
      if (esc) { buf += ch; esc = false; continue; }
      if (ch === '\\') { esc = true; continue; }
      if (ch === '|') { cells.push(buf.trim()); buf = ''; continue; }
      buf += ch;
    }
    if (esc) buf += '\\';
    cells.push(buf.trim());
    return cells;
  }

  /* 分隔行 → 每列对齐方式（'' / left / center / right）；不是分隔行返回 null */
  function tableAligns(line) {
    var cells = splitTableRow(line);
    if (!cells || !cells.length) return null;
    var out = [];
    for (var k = 0; k < cells.length; k += 1) {
      var c = cells[k];
      if (!/^:?-+:?$/.test(c)) return null;
      var left = c.charAt(0) === ':', right = c.charAt(c.length - 1) === ':';
      out.push(left && right ? 'center' : (right ? 'right' : (left ? 'left' : '')));
    }
    return out;
  }

  /* 这一行 + 下一行是否构成一张表（段落循环也要用它来提前收尾） */
  function tableStartsAt(lines, idx) {
    var head = splitTableRow(lines[idx]);
    if (!head) return false;
    var aligns = idx + 1 < lines.length ? tableAligns(lines[idx + 1]) : null;
    return !!(aligns && aligns.length === head.length);
  }

  function renderTable(head, aligns, rows, store) {
    var cols = head.length;
    function cell(tag, text, col) {
      var align = aligns[col] ? ' style="text-align:' + aligns[col] + '"' : '';
      return '<' + tag + ' class="md-td"' + align + '>' + inlineSpan(text, store) + '</' + tag + '>';
    }
    var thead = '<thead><tr>' + head.map(function (t, c) {
      return cell('th', t, c);
    }).join('') + '</tr></thead>';
    var tbody = rows.length ? '<tbody>' + rows.map(function (row) {
      var body = [];
      for (var c = 0; c < cols; c += 1) body.push(cell('td', row[c] == null ? '' : row[c], c));
      return '<tr>' + body.join('') + '</tr>';
    }).join('') + '</tbody>' : '';
    return '<div class="md-table-wrap"><table class="md-table">' + thead + tbody + '</table></div>';
  }

  function isBlockStart(line) {
    return HEAD_RE.test(line) || QUOTE_RE.test(line) || FENCE_RE.test(line) ||
      HR_RE.test(line) || LIST_RE.test(line);
  }

  function block(raw, store) {
    var lines = String(raw == null ? '' : raw).replace(/\r\n?/g, '\n').split('\n');
    var out = [];
    var i = 0;
    while (i < lines.length) {
      var line = lines[i];
      if (!line.trim()) { i += 1; continue; }

      var fence = FENCE_RE.exec(line);
      if (fence) {
        var mark = fence[1][0];
        var lang = line.trim().slice(fence[1].length).trim().split(/\s+/)[0] || '';
        var code = [];
        i += 1;
        var closeRe = new RegExp('^ {0,3}' + (mark === '`' ? '```' : '~~~') + '[ \\t]*$');
        while (i < lines.length && !closeRe.test(lines[i])) { code.push(lines[i]); i += 1; }
        if (i < lines.length) i += 1;                 // 跳过闭合围栏（没闭合就到文末）
        var cls = /^[A-Za-z0-9_+-]{1,20}$/.test(lang) ? ' data-lang="' + lang + '"' : '';
        out.push('<pre class="md-pre"' + cls + '><code>' + escapeHtml(code.join('\n')) +
          '</code></pre>');
        continue;
      }

      var head = HEAD_RE.exec(line);
      if (head) {
        var level = head[1].length;
        out.push('<h' + level + ' class="md-h md-h' + level + '">' +
          inlineSpan(head[2], store) + '</h' + level + '>');
        i += 1; continue;
      }

      if (HR_RE.test(line)) { out.push('<hr class="md-hr">'); i += 1; continue; }

      if (tableStartsAt(lines, i)) {
        var theadCells = splitTableRow(lines[i]);
        var aligns = tableAligns(lines[i + 1]);
        i += 2;
        var trows = [];
        while (i < lines.length && lines[i].trim()) {
          var trow = splitTableRow(lines[i]);
          if (!trow) break;                       // 表格被普通段落打断
          trows.push(trow);
          i += 1;
        }
        out.push(renderTable(theadCells, aligns, trows, store));
        continue;
      }

      var quote = QUOTE_RE.exec(line);
      if (quote) {
        var inner = [];
        while (i < lines.length) {
          var qm = QUOTE_RE.exec(lines[i]);
          if (qm) { inner.push(qm[1]); i += 1; continue; }
          if (!lines[i].trim()) break;               // 引用块被空行结束
          inner.push(lines[i]); i += 1;              // GitHub 允许续行不带 >
        }
        out.push('<blockquote class="md-quote">' + block(inner.join('\n'), store) +
          '</blockquote>');
        continue;
      }

      if (LIST_RE.test(line)) {
        var items = [];
        while (i < lines.length) {
          /* 条目之间隔了空行（松散列表）仍然算同一个列表 —— GitHub 就是这么渲染的。
             不合并的话每个条目会变成独立的 <ul>/<ol>，各自带 8px 下边距，
             视觉上就是条目之间"无故多出一个空行"。 */
          if (!lines[i].trim()) {
            var nj = i;
            while (nj < lines.length && !lines[nj].trim()) nj += 1;
            var peek = nj < lines.length ? LIST_RE.exec(lines[nj]) : null;
            if (peek && (!!peek[3] === !!items[0].ordered)) { i = nj; continue; }
            break;
          }
          var lm = LIST_RE.exec(lines[i]);
          if (lm) {
            items.push({
              indent: indentWidth(lm[1]),
              ordered: !!lm[3],
              order: lm[3] ? Number(lm[3]) : 0,
              lines: [lm[4]],
            });
            i += 1; continue;
          }
          /* 标题 / 围栏代码 / 引用 / 分隔线会打断列表：结束列表，把这一行交回外层，
             ⚠️ 绝不能像老代码那样 `i += 1` 直接吞掉（那会把标题整行弄没）。 */
          if (isBlockStart(lines[i])) break;
          /* CommonMark 的"惰性续行"：没缩进也算当前条目的续行（GitHub 同款）。
             老代码只认缩进续行、其余 break，于是 `- 1` 下一行直接写 URL 时，
             列表被劈成"单项列表 + 段落" —— 用户看到的就是"部分显示不正确"。 */
          items[items.length - 1].lines.push(lines[i].trim());
          i += 1;
        }
        var built = buildList(items, 0, store);
        out.push(built.html);
        continue;
      }

      /* 普通段落：连续非空、非块起始的行合并（段内换行按用户排版保留） */
      var para = [];
      while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i]) &&
        !tableStartsAt(lines, i)) {
        para.push(lines[i]); i += 1;
      }
      if (!para.length) { para.push(lines[i]); i += 1; }      // 防呆：绝不原地卡死
      out.push('<p class="md-p">' +
        para.map(function (one) { return inlineSpan(one, store); }).join('<br>') +
        '</p>');
    }
    return out.join('\n');
  }

  /* Tab 按 2 空格算：GitHub 的列表缩进本来就常混用 */
  function indentWidth(ws) {
    return String(ws || '').replace(/\t/g, '  ').length;
  }

  function buildList(items, level, store) {
    var ordered = items.length ? items[0].ordered : false;
    var tag = ordered ? 'ol' : 'ul';
    var lis = [];
    var pos = 0;
    while (pos < items.length && items[pos].indent >= level) {
      var item = items[pos];
      if (item.indent > level) {
        /* 更深一层 → 递归建子列表，挂到上一个 <li> 里 */
        var sub = buildList(items.slice(pos), item.indent, store);
        if (lis.length) lis[lis.length - 1].sub += sub.html;
        else lis.push({ text: '', sub: sub.html, ordered: false });
        pos += sub.used;
        continue;
      }
      var text = itemHtml(item, store);
      /* 任务清单的 <li> 要挂 is-task：否则浏览器还会再画一个列表圆点（•• ☐ 文本 双标记）。 */
      lis.push({ text: text, sub: '', ordered: item.ordered,
        task: /^<span class="md-task/.test(text) });
      pos += 1;
    }
    /* 有序列表从源里的数字起编（`3. ` 开头就是 start="3"），否则被打散成两块时
       后半段会从 1 重新数，看起来"编号不对"。无序列不需要。 */
    var startAttr = (ordered && items.length && items[0].order > 1)
      ? ' start="' + Math.min(items[0].order, 999999) + '"' : '';
    var html = '<' + tag + ' class="md-list md-' + tag + '"' + startAttr + '>' +
      lis.map(function (li) {
        return '<li class="md-li' + (li.task ? ' is-task' : '') + '">' +
          li.text + li.sub + '</li>';
      }).join('') + '</' + tag + '>';
    return { html: html, used: pos };
  }

  /* 任务清单 [ ] / [x]：换成一个字符标记（不引入 checkbox，避免被当成可交互控件） */
  function itemHtml(item, store) {
    var text = String(item.lines.join('\n').trim());
    var task = /^\[([ xX!])\]\s*/.exec(text);
    var body = '';
    if (task) {
      var done = task[1] !== ' ';
      body = '<span class="md-task' + (done ? ' is-done' : '') + '" aria-hidden="true">' +
        (done ? '☑' : '☐') + '</span> ';
      text = text.slice(task[0].length);
    }
    var parts = text.split('\n');
    body += parts.map(function (one) { return inlineSpan(one, store); }).join('<br>');
    return body;
  }

  /* ---------- 对外 API ---------- */
  function render(text) {
    try {
      var store = [];
      var html = block(cleanse(text), store);
      return restore(html, store).trim();
    } catch (error) {
      /* 渲染器出问题不该把公告整块变空白：退回"全转义 + 换行"的纯文本 */
      return escapeHtml(String(text == null ? '' : text)).replace(/\n/g, '<br>');
    }
  }

  /* 按 Markdown 边界截断：
     1) 先退到最近的**块边界**（空行），退不了再退到行首 —— 不会劈开半行；
     2) 围栏代码块没配上 → 丢掉最后一段围栏；
     3) 行内反引号没配上 → 从最后一个反引号前丢掉；
     4) 结尾残留 `[文字]( 这种没闭合的链接 → 丢掉外壳，只留文字。
     这样截断产物里不会留半个语法标记（用户看到的既不是碎代码也不是裸露的 `**`）。 */
  function truncate(text, limit) {
    var s = cleanse(text).replace(/\r\n?/g, '\n');
    var max = Math.floor(Number(limit) || 0);
    if (!max || s.length <= max) return s;
    var cut = max;
    var blank = s.lastIndexOf('\n\n', cut);
    if (blank >= Math.floor(max * 0.5)) cut = blank;
    else {
      var nl = s.lastIndexOf('\n', cut);
      if (nl >= Math.floor(max * 0.5)) cut = nl;
    }
    var head = s.slice(0, cut);

    var m;
    var fenceRe = /^ {0,3}(?:`{3,}|~{3,})/gm;
    var lastFence = -1, count = 0;
    while ((m = fenceRe.exec(head))) { lastFence = m.index; count += 1; }
    if (count % 2 === 1 && lastFence >= 0) head = head.slice(0, lastFence);

    var ticks = head.match(/`/g);
    if (ticks && ticks.length % 2 === 1) {
      var t = head.lastIndexOf('`');
      if (t >= 0) head = head.slice(0, t);
    }

    var openBracket = head.lastIndexOf('[');
    if (openBracket >= 0 && head.slice(openBracket).indexOf(']') < 0) {
      head = head.slice(0, openBracket);
    }
    /* `[文字](` / `![图](` 这种"外壳配了、括号没配"的尾巴：丢掉整个外壳，
       否则渲染时会剩一个字面量的 `[文字](`。 */
    var half = head.match(/!?\[[^\]]*\]\([^)]*$/);
    if (half) head = head.slice(0, half.index);

    /* 奇数个 ** / __ / ~~ / * 之类：从最后一个孤立标记处丢掉，
       避免截断产物里留半个粗体外壳（渲染器只认配对，孤立的会当文本显示出来）。 */
    var starCount = (head.match(/\*\*/g) || []).length;
    if (starCount % 2 === 1) {
      var p = head.lastIndexOf('**');
      if (p >= 0) head = head.slice(0, p);
    }
    var tildeCount = (head.match(/~~/g) || []).length;
    if (tildeCount % 2 === 1) {
      var q = head.lastIndexOf('~~');
      if (q >= 0) head = head.slice(0, q);
    }

    return head.replace(/\s+$/, '') + '…';
  }

  var api = { render: render, truncate: truncate, escapeHtml: escapeHtml };

  root.ToolMarkdown = api;
  /* 浏览器模式（serve.py 直接开）与桌面端都只需要全局；不引入模块系统 */
}());
