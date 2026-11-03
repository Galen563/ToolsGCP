/* * =============================================================================
 * rich-input.js —— GCP-AI 输入框的@资源富文本组件（window.RichAiInput）
 * =============================================================================
 *
 * 【为什么有这个文件 / 它解决什么】
 *   用户需求原话：
 *   点击卡片 ui 上的 @ 按钮或者右键弹出菜单点击 @ 给 GCP-AI 都是同一个，他会出现在了
 *     输入框里；不过我要这个时蓝色并且带有下划线的，也可以点击直接跳转对应卡片；
 *     删除的话第一次删除点击自动全选这个整个 @ 部分的单独 text，再次点击则删除；
 *     框选 @ 部分的 text 会直接框选住全部，例如 "@OBS(TG-000024) " 想框选 ") "，
 *     他不会让你框选 ") "，而是直接给你框选住整个 "@OBS(TG-000024) "
 *   → 原来的 <textarea class="ai-input" v-model="aiDraft"> 只能放纯文本；这里换成
 *     contenteditable 富文本输入框：@资源 是一个 contenteditable=false 的
 *     <span class="mention-token">，视觉上（CSS 由 CSS 队友按 class 给）呈蓝色 + 下划线，
 *     能点击跳转、能整段选、能第一次选整段 / 第二次删。
 *
 * 【文件约束（见 AGENTS.md）】
 *   · 无构建链：本文件是**经典脚本**（不是 ES Module），没有 import / export。
 *   · 不引入依赖：只用全局 Vue 3（本地 vendor/CDN）与浏览器原生 DOM API；不碰 window.pywebview。
 *   · 只占用一个全局名：window.RichAiInput（纯逻辑函数挂在它的 __pure 属性上，方便离线自测）。
 *   · 组件**不自己** createApp / 不自己 mount，挂载与注册由 app.js 负责。
 *
 * =============================================================================
 * 【组件契约】
 * =============================================================================
 * 全局：window.RichAiInput —— Vue 3 Options API 组件对象。
 *
 * Props
 *   modelValue   String   纯文本（就是父组件的 aiDraft）；@资源 以 `@名称(编码)` 形式出现
 *   placeholder  String   默认 '说一个你想要的软件或网站…'（渲染到 data-placeholder，
 *                         由 CSS 的 .ai-rich-input:empty：before 显示 —— 不是原生 placeholder）
 *   title        String   根元素 title
 *   disabled     Boolean  为 true 时 contenteditable="false"
 *   commands     Array    新增：允许变蓝的 /命令词（不带斜杠），默认 ['plugin']。
 *                         以后后端 ai.chat_hints 新增命令时，父组件把命令词数组传进来即可。
 *
 * Emits
 *   update:modelValue(text: string)              每次内容变化后的纯文本
 *                                                （= 所有文本节点 + token 可见文本 顺序拼接）
 *   send()                                       Enter（不带 Shift、非输入法组合中）
 *   token-click({ code, name, text, event })     点击 @token（/命令 token 不触发）
 *
 * expose（父组件 ref.value.xxx() 可调）
 *   focus()                          聚焦；当前没有选区时把光标放到末尾
 *   setText(text)                    用纯文本重建内容；符合 `@名称(编码)` 的片段自动变 token
 *   insertMention({ name, code, text })  在**当前光标处**插入一个 token + 一个尾随空格，
 *                                    （仅当本输入框真的持有 DOM 焦点时才用光标位置；
 *                                    卡片 @ 按钮进来时输入框多半没聚焦 → 追加到末尾）
 *                                    插入后光标落在空格之后并 focus
 *   getPlainText()                   当前纯文本（与 update:modelValue 同源同算法）
 *   clear()                          清空（并 emit 一次 ''）
 *
 * DOM 结构（根元素就是 contenteditable 本身，class 固定含 ai-input / ai-rich-input）
 *   <div class="ai-input ai-rich-input" contenteditable="true"
 *        data-placeholder="说一个你想要的软件或网站…" title="…">
 *     普通文本节点…
 *     <span class="mention-token" contenteditable="false"
 *           data-code="TG-000024" data-name="OBS" data-text="@OBS(TG-000024)"
 *           >@OBS(TG-000024)</span>
 *     普通文本节点…
 *     <span class="slash-token" contenteditable="false"
 *           data-command="plugin" data-text="/plugin">/plugin</span>   ← /命令
 *     普通文本节点…
 *   </div>
 *   ★ class 名固定 `mention-token` / `slash-token`（颜色全部由 css 队友按 class 写，
 *     组件内**不写死任何颜色**）
 *   ★ 两种 token 都是 contenteditable=false 的原子块，序列化/选区/删除逻辑完全共用
 *   ★ token 内部只用 textContent / createTextNode 构造，绝不 innerHTML 拼不可信内容
 *
 * =============================================================================
 * 【（需求）：/plugin → 蓝色命令 token】
 * =============================================================================
 *   /plugin 输入后被识别后会变成蓝色字体。
 *   识别规则（刻意收紧，宁可不识别也不误伤普通输入）：
 *     · 只认**文本最开头**（index 0）的 /命令，前面不允许有空白或其它字符；
 *     · 命令词必须在白名单里：props.commands（默认 ['plugin']）；
 *     · 命令词后面必须是**空白或输入结束**（"/pluginx"、"/plugin是"、"/home/user" 都不识别）；
 *     · 输入 `/`、`/plu`、`/plugi` 的过程保持普通文本，敲完 `/plugin` 才变 token。
 *   纯文本序列化：命令 token 的 data-text 就是 `/plugin`，所以 getPlainText()/发送给 AI 的内容
 *   一个字都不丢（`/plugin ` 的尾随空格是独立文本节点）。
 *   与 slash hint 配合：app.js 的 applyAiHint 把 aiDraft 设成 '/plugin '，v-model watch → setText →
 *   parseRichText 直接渲染成 token，**父组件不需要额外调用**（本文件不用改 app.js）。
 *   动态切换：onInput / compositionend 里调 syncSlashToken()，只在该有 token 却没有 / 不该有却有
 *   时**重建一次并保住光标**（例如用户又敲了 `/pluginx` → 退回普通文本；在开头插了字符 → 同样退回）。
 *   删除/选择：完全复用 mention-token 的单元机制 —— 光标紧贴 token 时第一次整段选中、第二次才删；
 *   框选只碰到 token 一部分也会扩成整段。
 *   点击：**不 emit token-click、不跳详情**（/命令不是资源），点击行为与普通不可编辑文本一致。
 *
 * =============================================================================
 * 【集成示例（Lead 负责改 app.js / index.html；本文件不改它们）】
 * =============================================================================
 * 1) index.html：在 app.js **之前**加一行（经典脚本，全局 Vue 已在它之前加载）
 *      <script src="/static/js/rich-input.js"></script>
 *
 * 2) app.js：createApp 之后注册（和 combo 同一处）
 *      app.component('rich-ai-input', window.RichAiInput);
 *
 * 3) 两处 <textarea class="ai-input" …>（index.html 约 1539 / 1811 行，独立 AI 页 + 悬浮抽屉）
 *    换成（两处都要，各自有独立 ref，见第 4 点两个实例说明）：
 *      <rich-ai-input ref="aiInputPageRef" v-model="aiDraft"
 *                     :title="t('ai_input_hint', 'Enter 发送，Shift+Enter 换行')"
 *                     @send="aiSend" @token-click="onAiTokenClick"></rich-ai-input>
 *    · 发送按钮的 :disabled="aiDraft.trim() ? false : true" 不用改（aiDraft 仍是纯文本）
 *    · focusAiInput() 里的 document.querySelector('.ai-input') 也不用改（根元素保留 ai-input 类）
 *
 * 4) mentionAi(item) 改成调组件方法（不再拼字符串）：
 *      function mentionAi(item) {
 *        if (!settings.ai_enabled) { … return; }
 *        if (settings.ai_sidebar_mode) doGoto('ai'); else aiOpen.value = true;
 *        const target = settings.ai_sidebar_mode ? aiInputPageRef.value : aiInputDrawerRef.value;
 *        /* 抽屉/页面是 v-if 挂载的，必须等一帧再插（组件还没挂载时 insertMention 是无害的空操作） *
 *        nextTick(() => {
 *          if (target) target.insertMention({ name: item.name, code: item.code,
 *            text: '@' + (item.name || '') + '(' + (item.code || '') + ')' });
 *          else focusAiInput();
 *        });
 *        toast(t('ai_mention_hint', '已把该资源带入 AI 输入框'), 'info');
 *      }
 *    ⚠️ 两个输入框（页面版 / 抽屉版）是不同实例，各自 v-if 挂载；用两个 ref 或按当前
 *       settings.ai_sidebar_mode 选一个。若共用同一个 ref，v-if 切换时 ref 会变成另一实例。
 *
 * 5) token-click → openDetail：
 *      function onAiTokenClick(payload) {
 *        const item = (allItems.value || []).find((x) => x.code === payload.code);
 *        if (item) openDetail(item);
 *        else toast('资源库里没有 ' + payload.code, 'info');
 *      }
 *
 * 6) aiSend() 读文本：aiDraft 本身就是纯文本（v-model 同步），不需要额外处理。
 *    发送后清空：aiDraft.value = ''（watch 会把 DOM 一起清掉）或 aiInputRef.value.clear()。
 *
 * =============================================================================
 * 【关键行为】
 * =============================================================================
 *   · Enter（无 Shift、非组合中）→ preventDefault + emit('send')；组件**不**清空，父组件清
 *   · Shift+Enter → 交给浏览器插入换行（需要 CSS white-space: pre-wrap 才显示为换行）
 *   · 输入法组合（compositionstart…compositionend）期间不 emit、不重建 DOM；end 后补一次同步
 *   · Backspace / Delete：
 *       - 光标（collapsed）紧贴 token：第一次 preventDefault 并**选中整个 token**，第二次才删
 *       - 已有选区只部分覆盖token：第一次先扩成整段，第二次才删（与用户描述一致）
 *       - 其他普通文本删除：保持原生行为，紧接着的 input 事件里 emit update
 *   · 选择（拖选 / 双击 / 三击 / Shift+方向键）：只要 selection **部分**相交 token，就扩展到
 *     token 完整边界（document 级 selectionchange + mouseup/keyup 触发，幂等不会死循环）
 *   · 点击 token：mousedown 与 click 都 preventDefault + stopPropagation（不移动光标/不选中），
 *     然后 emit('token-click')
 *   · 粘贴：只取 text/plain，按 token 规则重建（粘贴进来的 @名称(编码) / 开头的 /plugin 也会变 token）
 *   · 空状态：没有 token 且只剩换行/空 → 清空 innerHTML（否则 :empty：before 占位符不显示）并 emit ''
 *   · /命令：文本开头出现白名单命令（`/plugin` + 空白/结束）→ 变 slash-token；
 *     敲 `/plu` 过程是普通文本；命令失效（如变成 `/pluginx`）自动退回普通文本；序列化始终是 `/plugin`；
 *     删除/选择/整段高亮与 @token 完全一致；点击不跳转、不 emit（见上方 小节）
 *
 * =============================================================================
 * 【CSS 队友需要配合的点（组件内故意不写任何颜色/尺寸）】
 * =============================================================================
 *   .ai-rich-input            { white-space: pre-wrap; word-break: break-word; }  ← 换行靠它
 *   .ai-rich-input:empty：before { content: attr(data-placeholder); color: var(--text-disabled); }
 *   .mention-token            { color: 蓝色; text-decoration: underline; cursor: pointer;
 *                               user-select: all? 不要，整段选择由 JS 管 }  ← 蓝字+下划线
 *   .mention-token：selection { … } 可选
 *   .slash-token              { color: var(--accent); font-weight: 600; }   ← /命令蓝色
 *   ⚠️ 旧 textarea 专用规则（field-sizing:content / :placeholder-shown / ：placeholder）
 *      对 div 不生效，需要给 .ai-rich-input 单独的 min-height / max-height（原为 38/110）
 *
 * =============================================================================
 * 【已知风险（需在真实 WebView2 里复验；离线沙箱跑不了浏览器）】
 * =============================================================================
 *   · selectionchange 里改选区在 Chromium 100+ 正常；若某内核忽略，拖选只会扩到 token 边界失败，
 *     不影响输入/发送（降级为可以框选半个 token，但删除逻辑仍走 first=选整段）。
 *   · 拖动选择时 first frame 会先显示出半截高亮，mouseup 后才扩成整段（有一帧跳动）。
 *   · 复制（Ctrl+C）整段 token 得到的是纯文本 `@OBS(TG-000024)`，符合预期；粘贴回来仍是 token。
 *   · Chromium 在某些输入路径会插入 \u00a0（nbsp）：序列化时统一替换成普通空格。
 *   · /命令 token：token 化发生在**敲完命令的那一次 input**（或 compositionend）；
 *     此后光标在 token 右侧，继续敲空格/文字都落在 token 后的文本节点里。
 *     · 若用户想把 `/plugin` 改成别的命令继续打字（如 `/pluginx`）→ 下一次 input 会
 *       自动退回普通文本（DOM 重建一次），光标保持在原字符偏移处。
 *     · 想删掉命令：Backspace 第一次整段高亮、第二次删除（与其他原子块一致）。
 *     · 识别只在文本**开头**：句中出现 `/plugin` 永远是普通文本（这是刻意行为，防止误伤）。*/

(function () {
  'use strict';

  if (typeof window === 'undefined') return;

  var TOKEN_CLASS = 'mention-token';
  /* /命令 token（如 /plugin）：蓝色、contenteditable=false，独立 class，颜色仍由 CSS 给*/
  var SLASH_CLASS = 'slash-token';
  /* 所有不可编辑原子块的统一选择器（@资源 + /命令）—— 序列化/选区/删除都按这个判定*/
  var ATOMIC_SELECTOR = '.' + TOKEN_CLASS + ', .' + SLASH_CLASS;
  /* 名称：不含 @ ( ) 与换行（允许中间有空格，例如 "Adobe Photoshop"）；非贪婪，遇到 ( 就停。
     编码：优先 TG-\d{6,}，同时兼容任意 [A-Z]{2,}-\d{4,}（VSCode / IDEA / JetBrains 之类）。*/
  var MENTION_SOURCE = /@([^@()\r\n]+?)\(([A-Z]{2,}-\d{4,})\)/.source;
  /* /命令词：只认/ + 字母开头的短词，避免把 "/home/user" 这种路径也吃掉*/
  var SLASH_RE = /^\/([A-Za-z][A-Za-z0-9_-]*)/;
  /* 命令词白名单默认值（组件 props.commands 可覆盖，方便后端 hints 以后加别的命令）*/
  var DEFAULT_COMMANDS = ['plugin'];

  /* =========================================================================
   * 一、纯函数（不碰 DOM，可离线 node 断言，挂在 window.RichAiInput.__pure）
   * =======================================================================*/

  /**
   * 纯文本 → 片段数组。片段只有两种：{kind:'text', text} / {kind:'token', name, code, text}
   * 不做任何 HTML 解析；token 的 text 就是原文片段，保证 setText→getPlainText 可逆。*/
  function parseMentions(text) {
    var src = text == null ? '' : String(text);
    var out = [];
    var re = new RegExp(MENTION_SOURCE, 'g');
    var last = 0;
    var m;
    while ((m = re.exec(src)) !== null) {
      var name = m[1].trim();
      if (!name) continue;                      /* 名称全空白 → 当普通文本（last 不推进）*/
      if (m.index > last) out.push({ kind: 'text', text: src.slice(last, m.index) });
      out.push({ kind: 'token', name: name, code: m[2], text: m[0] });
      last = m.index + m[0].length;
    }
    if (last < src.length) out.push({ kind: 'text', text: src.slice(last) });
    return out;
  }

  function unitLength(spec) {
    if (!spec) return 0;
    return String(spec.text == null ? '' : spec.text).length;
  }

  /* ---------------- /命令 token（新增，如 /plugin） ----------------
     /plugin 输入后被识别后会变成蓝色字体。
     规则（刻意收紧，宁可不识别也不要误伤普通输入）：
       · 只认**文本最开头**（index 0）的命令，前面不允许有空白/其它字符；
       · 命令词必须在白名单里（默认 ['plugin']，组件 props.commands 可覆盖）；
       · 命令词后面必须是**空白或输入结束**（"/pluginx"、"/plugin是" 都不算）。
     为什么要后面必须是空白/结束：用户敲 `/plu`、`/plugi` 的过程必须保持普通文本，
     只有敲完整命令（或 applyAiHint 直接写入 "/plugin "）才变色。*/

  function commandAllowed(word, commands) {
    var list = (commands && commands.length) ? commands : DEFAULT_COMMANDS;
    var w = String(word || '').toLowerCase();
    for (var i = 0; i < list.length; i += 1) {
      var item = String(list[i] == null ? '' : list[i]).replace(/^\//, '').toLowerCase();
      if (item === w) return true;
    }
    return false;
  }

  /**
   * 匹配文本开头的 /命令。
   * @returns {{command:string, text:string, end:number, rest:string}|null}
   *   text = 原样命令文本（如 '/plugin'，用于 token 可见文本与纯文本序列化）
   *   end  = 命令在原文里的结束下标；rest = 命令之后的剩余文本*/
  function matchSlashCommand(text, commands) {
    var src = text == null ? '' : String(text);
    if (src.charAt(0) !== '/') return null;
    var m = SLASH_RE.exec(src);
    if (!m) return null;
    if (!commandAllowed(m[1], commands)) return null;
    var end = m[0].length;
    var next = src.charAt(end);
    if (next && !/\s/.test(next)) return null;    /* 后面必须是空白或输入结束*/
    return { command: m[1].toLowerCase(), text: m[0], end: end, rest: src.slice(end) };
  }

  /** 纯文本 → 片段数组（/命令 token + @资源 token + 普通文本）。setText / 粘贴 / 初始化共用。*/
  function parseRichText(text, commands) {
    var src = text == null ? '' : String(text);
    var head = matchSlashCommand(src, commands);
    if (!head) return parseMentions(src);
    return [{ kind: 'slash', command: head.command, text: head.text }].concat(parseMentions(head.rest));
  }

  /**
   * DOM 现状与期望的命令 token是否不一致（纯函数，便于离线断言）。
   * @param units collectUnits() 的结果
   * @param want  matchSlashCommand() 的结果或 null*/
  function slashNeedsRebuild(units, want) {
    var list = units || [];
    var slashIdx = -1;
    for (var i = 0; i < list.length; i += 1) {
      if (list[i].kind === 'token' && list[i].role === 'slash') { slashIdx = i; break; }
    }
    if (!want) return slashIdx >= 0;             /* 不该有 token 却有 → 重建（退回普通文本）*/
    /* 正确状态只有一种：命令 token 就是第一个单元，且文本与期望一致*/
    return !(slashIdx === 0 && String(list[0].text || '') === String(want.text || ''));
  }

  /* ---------------- 纯文本扁平偏移（重建 DOM 时保住光标位置） ----------------*/

  /** 单元在纯文本里的宽度：文本按字符数，token 按可见文本长度，<br> 算 1（换行符）*/
  function unitWidth(unit) {
    if (!unit) return 0;
    return String(unit.text == null ? '' : unit.text).length;
  }

  /** 单元位置 {i, ch} → 纯文本扁平字符偏移*/
  function flatOffsetOfPos(units, pos) {
    var list = units || [];
    var i = pos ? pos.i : 0;
    var ch = (pos && pos.ch) || 0;
    var off = 0;
    for (var k = 0; k < list.length && k < i; k += 1) off += unitWidth(list[k]);
    if (i >= 0 && i < list.length) off += Math.max(0, Math.min(ch, unitWidth(list[i])));
    return off;
  }

  /** 纯文本扁平字符偏移 → 单元位置（偏移落在 token 内部时贴到 token 左边，光标不会钻进 token）*/
  function posFromFlatOffset(units, offset) {
    var list = units || [];
    var want = Math.max(0, offset || 0);
    var acc = 0;
    for (var i = 0; i < list.length; i += 1) {
      var u = list[i];
      var w = unitWidth(u);
      if (u.kind === 'text') {
        if (w > 0 && want <= acc + w) return { i: i, ch: want - acc };
      } else if (want < acc + w) {
        return { i: i, ch: 0 };
      }
      acc += w;
    }
    return { i: list.length, ch: 0 };
  }

  /** 把部分覆盖 token的选区位置扩到 token 完整边界（纯函数，幂等）。*/
  function expandPositions(specs, start, end) {
    var list = specs || [];
    var s = { i: start ? start.i : 0, ch: (start && start.ch) || 0 };
    var e = { i: end ? end.i : 0, ch: (end && end.ch) || 0 };
    if (s.i > e.i || (s.i === e.i && s.ch > e.ch)) { var tmp = s; s = e; e = tmp; }
    var changed = false;
    var su = list[s.i];
    /* 起点落在 token 内部（ch>0）→ 退到 token 起点，让整个 token 进选区*/
    if (su && su.kind === 'token' && s.ch > 0) { s = { i: s.i, ch: 0 }; changed = true; }
    /* 终点落在 token 内部（0 < ch < 长度）→ 进到 token 后面*/
    var eu = list[e.i];
    if (eu && eu.kind === 'token' && e.ch > 0 && e.ch < unitLength(eu)) {
      e = { i: e.i + 1, ch: 0 };
      changed = true;
    }
    return { start: s, end: e, changed: changed };
  }

  /**
   * 光标（collapsed）紧贴的 token 单元下标；-1 表示没有紧贴 token，走原生删除。
   * dir='back'（Backspace）看光标左边，dir='forward'（Delete）看光标右边。
   * 空文本节点（浏览器 split 残留）跳过，不算阻挡。*/
  function adjacentTokenIndex(specs, pos, dir) {
    var list = specs || [];
    var i = pos ? pos.i : 0;
    var ch = (pos && pos.ch) || 0;
    var j;
    if (dir === 'back') {
      if (ch > 0) return -1;                    /* 光标在文本中间：左边是字，不是 token*/
      for (j = i - 1; j >= 0; j -= 1) {
        var u = list[j];
        if (!u) break;
        if (u.kind === 'token') return j;
        if (u.kind !== 'text') return -1;       /* br 等：不跨过去*/
        if (String(u.text || '').replace(/[\u200b]/g, '').length === 0) continue;
        return -1;
      }
      return -1;
    }
    var startJ = i;
    if (ch > 0) {
      /* 光标在文本中间：只有正好停在**这段文本末尾**时才可能紧贴后面的 token
         （例如 "abc" + @token，光标在 c 后面按 Delete）*/
      var cur = list[i];
      if (!cur || cur.kind !== 'text' || ch < String(cur.text || '').length) return -1;
      startJ = i + 1;
    }
    for (j = startJ; j < list.length; j += 1) {
      var v = list[j];
      if (!v) break;
      if (v.kind === 'token') return j;
      if (v.kind !== 'text') return -1;
      if (String(v.text || '').replace(/[\u200b]/g, '').length === 0) continue;
      return -1;
    }
    return -1;
  }

  /* =========================================================================
   * 二、DOM 小工具（全部用原生 API；token 内容只用 textContent 造）
   * =======================================================================*/

  /**
   * 原子块的种类：'mention'（@资源） / 'slash'（/命令） / ''（普通元素）。
   * 两者都 contenteditable=false、都参与整段选 / 整段删，只是 class 和 data-* 不同。*/
  function atomicRole(node) {
    if (!node || node.nodeType !== 1 || !node.classList) return '';
    if (node.classList.contains(TOKEN_CLASS)) return 'mention';
    if (node.classList.contains(SLASH_CLASS)) return 'slash';
    return '';
  }

  function isAtomicEl(node) {
    return !!atomicRole(node);
  }

  function tokenText(el) {
    if (!el) return '';
    var attr = el.getAttribute('data-text');
    if (attr != null && attr !== '') return attr;
    return el.textContent || '';
  }

  function tokenMeta(el) {
    return {
      code: el ? (el.getAttribute('data-code') || '') : '',
      name: el ? (el.getAttribute('data-name') || '') : '',
      text: tokenText(el)
    };
  }

  function buildTokenEl(doc, spec) {
    var span = doc.createElement('span');
    span.className = TOKEN_CLASS;
    span.setAttribute('contenteditable', 'false');
    span.setAttribute('data-code', spec.code == null ? '' : String(spec.code));
    span.setAttribute('data-name', spec.name == null ? '' : String(spec.name));
    /* data-text 让序列化不受 DOM 变化影响；可见文本必须与 data-text 一致*/
    var text = spec.text == null ? '' : String(spec.text);
    if (!text) text = '@' + (spec.name || '') + '(' + (spec.code || '') + ')';
    span.setAttribute('data-text', text);
    span.textContent = text;                    /* ★ 不用 innerHTML*/
    return span;
  }

  /**
   * /命令 token：<span class="slash-token" contenteditable="false"
   *                  data-command="plugin" data-text="/plugin">/plugin</span>
   * 不加任何内联颜色 —— 蓝色由 CSS 的 .slash-token 规则给。*/
  function buildSlashEl(doc, spec) {
    var span = doc.createElement('span');
    span.className = SLASH_CLASS;
    span.setAttribute('contenteditable', 'false');
    span.setAttribute('data-command', spec.command == null ? '' : String(spec.command));
    var text = spec.text == null ? '' : String(spec.text);
    if (!text) text = '/' + (spec.command || '');
    span.setAttribute('data-text', text);
    span.textContent = text;                    /* ★ 不用 innerHTML*/
    return span;
  }

  /** 纯文本序列化：文本节点原样 + token 可见文本 + <br> 当换行（块元素补换行）。*/
  function getPlainTextFrom(root) {
    if (!root) return '';
    var out = '';
    var walk = function (parent) {
      var kids = parent.childNodes;
      for (var i = 0; i < kids.length; i += 1) {
        var node = kids[i];
        if (node.nodeType === 3) { out += node.data; continue; }
        if (node.nodeType !== 1) continue;
        if (isAtomicEl(node)) { out += tokenText(node); continue; }
        var tag = node.nodeName;
        if (tag === 'BR') { out += '\n'; continue; }
        var block = (tag === 'DIV' || tag === 'P' || tag === 'LI');
        if (block && out && out.charAt(out.length - 1) !== '\n') out += '\n';
        walk(node);
      }
    };
    walk(root);
    /* Chromium 某些路径会塞 nbsp / 零宽字符，统一成普通字符，避免 v-model 比不出来*/
    return out.replace(/\u00a0/g, ' ').replace(/\u200b/g, '');
  }

  /**
   * 把 DOM 内容拍平成单元序列：
   *   {kind:'text', node, text} | {kind:'token', el, text} | {kind:'br', el}
   * 位置用 {i, ch} 表示：i=单元下标（0..units.length），ch=文本单元内的字符偏移。*/
  function collectUnits(root) {
    var units = [];
    var walk = function (parent) {
      var kids = parent.childNodes;
      for (var i = 0; i < kids.length; i += 1) {
        var node = kids[i];
        if (node.nodeType === 3) {
          units.push({ kind: 'text', node: node, text: node.data });
          continue;
        }
        if (node.nodeType !== 1) continue;
        var role = atomicRole(node);            /* 'mention' / 'slash' / ''*/
        if (role) {
          units.push({ kind: 'token', el: node, text: tokenText(node), role: role });
          continue;
        }
        if (node.nodeName === 'BR') {
          units.push({ kind: 'br', el: node, text: '\n' });
          continue;
        }
        walk(node);                             /* 浏览器可能包一层 div/p，摊平即可*/
      }
    };
    walk(root);
    return units;
  }

  function unitSpec(unit) {
    if (!unit) return { kind: 'br', text: '' };
    if (unit.kind === 'token') return { kind: 'token', text: unit.text };
    if (unit.kind === 'text') return { kind: 'text', text: unit.text };
    return { kind: 'br', text: '' };
  }

  function domChildIndex(parent, node) {
    if (!parent || !node) return -1;
    var kids = parent.childNodes;
    for (var i = 0; i < kids.length; i += 1) if (kids[i] === node) return i;
    return -1;
  }

  function unitNode(unit) {
    return unit.node || unit.el;
  }

  /** child 所在的第一个单元下标（child 可能是文本/token/包裹块）*/
  function unitIndexContaining(units, child) {
    for (var i = 0; i < units.length; i += 1) {
      var n = unitNode(units[i]);
      if (n === child) return i;
      if (child.contains && child.contains(n)) return i;
    }
    return -1;
  }

  /** container 之后（不含 container 内部）的第一个单元下标*/
  function unitIndexAfterContainer(units, container) {
    for (var i = 0; i < units.length; i += 1) {
      var n = unitNode(units[i]);
      if (container.contains && container.contains(n)) continue;
      if (typeof container.compareDocumentPosition !== 'function') return i;
      if (container.compareDocumentPosition(n) & 4 /* DOCUMENT_POSITION_FOLLOWING*/) return i;
    }
    return units.length;
  }

  /** DOM 边界点 → 单元位置*/
  function pointToPos(units, root, container, offset) {
    if (!container) return { i: units.length, ch: 0 };
    if (container.nodeType === 3) {
      for (var i = 0; i < units.length; i += 1) {
        if (units[i].node === container) {
          var max = String(units[i].text || '').length;
          return { i: i, ch: Math.max(0, Math.min(offset, max)) };
        }
      }
      return { i: units.length, ch: 0 };
    }
    if (container.nodeType !== 1) return { i: units.length, ch: 0 };
    var child = container.childNodes[offset] || null;
    if (child) {
      var idx = unitIndexContaining(units, child);
      if (idx >= 0) return { i: idx, ch: 0 };
    }
    /* 边界在 container 末尾 → 取 container 之后的下一个单元*/
    return { i: unitIndexAfterContainer(units, container), ch: 0 };
  }

  /** 单元位置 → DOM 边界点*/
  function posToDomPoint(units, root, pos) {
    if (!units.length) return { c: root, o: 0 };
    if (!pos || pos.i >= units.length) {
      var last = units[units.length - 1];
      if (last.kind === 'text') return { c: last.node, o: String(last.text || '').length };
      var lp = last.el.parentNode || root;
      return { c: lp, o: domChildIndex(lp, last.el) + 1 };
    }
    var u = units[pos.i];
    if (u.kind === 'text') {
      return { c: u.node, o: Math.max(0, Math.min(pos.ch || 0, String(u.text || '').length)) };
    }
    var parent = u.el.parentNode || root;
    var base = domChildIndex(parent, u.el);
    return { c: parent, o: (pos.ch || 0) > 0 ? base + 1 : base };
  }

  function rangeFromPositions(units, root, start, end) {
    try {
      var s = posToDomPoint(units, root, start);
      var e = posToDomPoint(units, root, end);
      var r = document.createRange();
      r.setStart(s.c, s.o);
      r.setEnd(e.c, e.o);
      return r;
    } catch (err) {
      return null;
    }
  }

  function caretTo(root, offset) {
    var sel = window.getSelection();
    if (!sel) return;
    try {
      var r = document.createRange();
      r.setStart(root, offset || 0);
      r.collapse(true);
      sel.removeAllRanges();
      sel.addRange(r);
    } catch (err) { /* 选区正被浏览器回收时忽略即可*/ }
  }

  /* =========================================================================
   * 三、组件
   * =======================================================================*/

  var RichAiInput = {
    name: 'RichAiInput',

    /* 只暴露这 5 个方法给父组件 ref（Vue 3 Options API 的 expose 选项）*/
    expose: ['focus', 'setText', 'insertMention', 'getPlainText', 'clear'],

    props: {
      modelValue: { type: String, default: '' },
      placeholder: { type: String, default: '说一个你想要的软件或网站…' },
      title: { type: String, default: '' },
      disabled: { type: Boolean, default: false },
      /* 允许被识别成蓝色命令 token 的 /命令词（不带斜杠）。默认只认 plugin。
         以后后端 hints 里新增命令，父组件把命令词数组传进来即可，不用改组件。*/
      commands: { type: Array, default: function () { return DEFAULT_COMMANDS.slice(); } }
    },

    emits: ['update:modelValue', 'send', 'token-click'],

    /* 没有构建链，但项目用的是 Vue 完整版（含运行时编译器），template 字符串可用。
       这里根元素**永远没有子节点**（内容全部由我们自己用 DOM API 造），
       Vue 重渲染只会 patch 属性，不会碰我们的文本/token 子节点。*/
    template:
      '<div class="ai-input ai-rich-input"'
      + ' :contenteditable="disabled ? \'false\' : \'true\'"'
      + ' :data-placeholder="placeholder"'
      + ' :title="title"'
      + ' @input="onInput"'
      + ' @keydown="onKeydown"'
      + ' @mouseup="onMouseUp"'
      + ' @mousedown="onMouseDown"'
      + ' @paste="onPaste"'
      + ' @click="onClick"></div>',

    data: function () {
      return {
        /* 输入法组合中：不 emit、不重建 DOM、Enter 不发送*/
        composing: false,
        /* 正在改选区（防 selectionchange 递归）*/
        normalizing: false
      };
    },

    watch: {
      modelValue: function (value) {
        /* 外部赋值（父组件清空/回填）时重建；和当前内容一致就跳过，避免打断正在输入的用户*/
        if (!this.$el) return;
        var next = value == null ? '' : String(value);
        if (this.composing) return;             /* 组合中不重建，compositionend 之后再对齐*/
        if (next === this.getPlainText()) return;
        this.setText(next);
      },
      disabled: function (value) {
        if (this.$el) this.$el.setAttribute('contenteditable', value ? 'false' : 'true');
      }
    },

    mounted: function () {
      var self = this;
      this.setText(this.modelValue == null ? '' : String(this.modelValue));

      /* 输入法：composition 期间一律不同步（否则会把用户正在拼的字打回去）*/
      this._onCompStart = function () { self.composing = true; };
      this._onCompEnd = function () {
        self.composing = false;
        self.syncSlashToken();                 /* 组合结束补一次命令 token 同步*/
        self.normalizeEmpty();
        self.emitUpdate();                     /* 组合结束后补一次同步*/
      };
      this.$el.addEventListener('compositionstart', this._onCompStart);
      this.$el.addEventListener('compositionend', this._onCompEnd);

      /* 选择归一：document 级（拖选过程中 selection 可能落在本组件外的节点上，先判断再动）*/
      this._onSelChange = function () { self.normalizeSelection(); };
      document.addEventListener('selectionchange', this._onSelChange);
    },

    beforeUnmount: function () {
      if (this._onSelChange) document.removeEventListener('selectionchange', this._onSelChange);
      if (this.$el) {
        if (this._onCompStart) this.$el.removeEventListener('compositionstart', this._onCompStart);
        if (this._onCompEnd) this.$el.removeEventListener('compositionend', this._onCompEnd);
      }
      this._onSelChange = null;
      this._onCompStart = null;
      this._onCompEnd = null;
    },

    methods: {
      /* ---------------- 基础读写 ----------------*/

      /** 纯文本（与 update:modelValue 同源）*/
      getPlainText: function () {
        return getPlainTextFrom(this.$el);
      },

      /** 用纯文本重建内容（外部初始化 / 清空 / 回填都走这里）*/
      setText: function (text) {
        var root = this.$el;
        if (!root) return;
        var src = text == null ? '' : String(text);
        var hadFocus = false;
        try { hadFocus = document.activeElement === root; } catch (err) { hadFocus = false; }
        root.innerHTML = '';                    /* 只清自己造的内容，禁止拼 HTML*/
        root.appendChild(this.buildFragment(src));
        /* ⚠️ 重建会把原选区挤到 (root, 0)：正在输入的框必须把光标挪到末尾，
           否则下一次按键会插到内容最前面（例如 applyAiHint 写入 "/plugin " 后一打字变成 "帮我/plugin "）*/
        if (hadFocus) this.caretToEnd();
      },

      /** 纯文本 → DocumentFragment（文本节点 + @token + /命令 token 混合）*/
      buildFragment: function (text) {
        var frag = document.createDocumentFragment();
        var segs = parseRichText(text, this.commandList());
        for (var i = 0; i < segs.length; i += 1) {
          var seg = segs[i];
          if (seg.kind === 'token') frag.appendChild(buildTokenEl(document, seg));
          else if (seg.kind === 'slash') frag.appendChild(buildSlashEl(document, seg));
          else frag.appendChild(document.createTextNode(seg.text));
        }
        return frag;
      },

      /** 允许的命令词白名单（props.commands 优先，默认 ['plugin']）*/
      commandList: function () {
        var list = this.commands;
        if (list && list.length) return list;
        return DEFAULT_COMMANDS;
      },

      /** 当前光标的纯文本扁平字符偏移（token 按文本长度计）；不在本组件内返回 null*/
      caretOffset: function () {
        var root = this.$el;
        if (!root) return null;
        var sel = window.getSelection();
        if (!sel || !sel.rangeCount) return null;
        var range = sel.getRangeAt(0);
        if (!this.selectionInside(range)) return null;
        var units = collectUnits(root);
        var pos = pointToPos(units, root, range.startContainer, range.startOffset);
        return flatOffsetOfPos(units, pos);
      },

      /** 把光标还原到纯文本扁平字符偏移处（重建 DOM 后用）*/
      setCaretOffset: function (offset) {
        var root = this.$el;
        if (!root || offset == null) return;
        var units = collectUnits(root);
        var pos = posFromFlatOffset(units, offset);
        var pt = posToDomPoint(units, root, pos);
        var sel = window.getSelection();
        if (!sel) return;
        try {
          var r = document.createRange();
          r.setStart(pt.c, pt.o);
          r.collapse(true);
          sel.removeAllRanges();
          sel.addRange(r);
        } catch (err) { /* 选区正被浏览器回收时忽略*/ }
      },

      /**
       * 让 DOM 里的 /命令 token 与纯文本保持一致。
       * 只在该有 token 却没有 / 不该有却有 / 命令词变了时重建一次，并**保住光标**；
       * 文本节点自己的增删仍交给浏览器，绝不每敲一个字都重建 DOM（会丢输入法状态、光标乱跳）。
       * @returns {boolean} 是否发生了重建*/
      syncSlashToken: function () {
        var root = this.$el;
        if (!root) return false;
        var units = collectUnits(root);
        var text = getPlainTextFrom(root);
        var want = matchSlashCommand(text, this.commandList());
        if (!slashNeedsRebuild(units, want)) return false;

        /* 重建前记住光标（纯文本偏移），重建后放回去*/
        var offset = this.caretOffset();
        this.setText(text);
        if (offset != null) this.setCaretOffset(offset);
        return true;
      },

      /** 把当前纯文本 emit 给父组件（v-model 同步）*/
      emitUpdate: function () {
        this.$emit('update:modelValue', this.getPlainText());
      },

      clear: function () {
        this.setText('');
        this.emitUpdate();                      /* 让父组件 aiDraft 同步为 ''*/
      },

      /** 把光标放到内容末尾（程序性聚焦 / 重建 DOM 之后用）*/
      caretToEnd: function () {
        var root = this.$el;
        if (!root) return;
        var sel = window.getSelection();
        if (!sel) return;
        try {
          var r = document.createRange();
          r.selectNodeContents(root);
          r.collapse(false);
          sel.removeAllRanges();
          sel.addRange(r);
        } catch (err) { /* 选区正被浏览器回收时忽略*/ }
      },

      focus: function () {
        var root = this.$el;
        if (!root) return;
        var wasActive = false;
        try { wasActive = document.activeElement === root; } catch (err) { wasActive = false; }
        try { root.focus(); } catch (err2) { /* ignore*/ }
        if (wasActive) {
          /* 用户本来就在这个框里编辑 → 不要动他的光标*/
          var sel = window.getSelection();
          if (sel && sel.rangeCount > 0 && this.selectionInside(sel.getRangeAt(0))) return;
        }
        /* 程序性聚焦（父组件 applyAiHint / 打开输入框后调用）：
           setText 重建后旧选区会停在 (root, 0)，必须显式放到末尾，否则接着输入会插到最前面*/
        this.caretToEnd();
      },

      /**
       * 在光标处插入 @token + 尾随空格。
       * 没有光标/选区不在本组件内 → 追加到末尾（mentionAi 从卡片按钮调用时就是这条路径）。*/
      insertMention: function (mention) {
        var root = this.$el;
        if (!root) return;
        var payload = mention || {};
        var name = payload.name == null ? '' : String(payload.name);
        var code = payload.code == null ? '' : String(payload.code);
        var text = payload.text == null ? '' : String(payload.text);
        if (!text) text = '@' + name + '(' + code + ')';

        var sel = window.getSelection();
        var range = null;
        /* ★ 只有本输入框**真的握着焦点**时才用当前光标位置插；
           从卡片 @ 按钮进来时（打开抽屉/页面后 nextTick 调用）输入框通常还没聚焦，
           此时按契约追加到末尾，和旧版 mentionAi 的体验一致（不在旧光标处乱插）。*/
        var focused = false;
        try { focused = document.activeElement === root; } catch (err) { focused = false; }
        if (focused && sel && sel.rangeCount > 0) {
          var live = sel.getRangeAt(0);
          if (this.selectionInside(live)) {
            /* 光标若在 token 内部（contenteditable=false 的怪位置），先拉到 token 之后*/
            var inToken = this.tokenAtNode(live.startContainer);
            range = live.cloneRange();
            if (inToken) { range.selectNode(inToken); range.collapse(false); }
          }
        }
        if (!range) {
          range = document.createRange();
          range.selectNodeContents(root);
          range.collapse(false);                /* 末尾*/
        }

        range.deleteContents();
        var span = buildTokenEl(document, { name: name, code: code, text: text });
        var space = document.createTextNode(' ');
        var frag = document.createDocumentFragment();
        frag.appendChild(span);
        frag.appendChild(space);
        range.insertNode(frag);                 /* 文本节点会被自动 split，无副作用*/

        /* 光标落到空格之后*/
        var caretParent = space.parentNode || root;
        var caretIndex = domChildIndex(caretParent, space) + 1;
        try {
          var caret = document.createRange();
          caret.setStart(caretParent, caretIndex);
          caret.collapse(true);
          if (sel) { sel.removeAllRanges(); sel.addRange(caret); }
        } catch (err) { /* ignore*/ }
        try { root.focus(); } catch (err2) { /* ignore*/ }

        /* 万一 @token 被插到了 /命令 前面（光标原本在开头），命令就不再是文本开头了 → 退回普通文本*/
        this.syncSlashToken();
        this.emitUpdate();
      },

      /* ---------------- 事件：输入 / 键盘 ----------------*/

      onInput: function () {
        if (this.composing) return;
        this.syncSlashToken();                  /* /plugin 进/出命令状态时变蓝（保持光标）*/
        this.normalizeEmpty();
        this.emitUpdate();
      },

      onKeydown: function (event) {
        if (this.disabled) return;
        var composing = this.composing || event.isComposing || event.keyCode === 229;

        if (event.key === 'Enter') {
          if (composing) return;                /* 输入法选词的回车不当发送*/
          if (event.shiftKey) return;           /* Shift+Enter：浏览器插换行*/
          event.preventDefault();
          this.$emit('send');
          return;
        }
        if (composing) return;

        if (event.key === 'Backspace' || event.key === 'Delete') {
          this.handleDelete(event);
        }
      },

      /**
       * 删除键的两段式行为：
       *   · collapsed 光标紧贴 token → 第一次选整段（preventDefault），第二次（已整段选中）才删
       *   · 已有选区只部分覆盖 token → 第一次先把选区扩成整段，第二次才删
       *   · 纯文本删除 → 不拦截，原生删完由 input 事件同步*/
      handleDelete: function (event) {
        var root = this.$el;
        if (!root) return;
        var sel = window.getSelection();
        if (!sel || !sel.rangeCount) return;
        var range = sel.getRangeAt(0);
        if (!this.selectionInside(range)) return;
        var dir = event.key === 'Delete' ? 'forward' : 'back';

        if (!range.collapsed) {
          var expanded = this.expandedRange(range);
          if (expanded && expanded.changed) {
            event.preventDefault();             /* 第一次：只扩选，不删*/
            this.applyRange(sel, expanded.range);
            return;
          }
          if (this.rangeHasToken(range)) {      /* 选区已经是整段 token（或包住 token）→ 删*/
            event.preventDefault();
            try { range.deleteContents(); } catch (err) { /* ignore*/ }
            this.afterManualEdit();
          }
          return;
        }

        var units = collectUnits(root);
        var specs = units.map(unitSpec);
        var pos = pointToPos(units, root, range.startContainer, range.startOffset);
        var idx = adjacentTokenIndex(specs, pos, dir);
        if (idx < 0) return;                    /* 不紧贴 token → 原生删除*/
        event.preventDefault();
        this.selectUnit(units, idx);            /* 第一次：整段选中*/
      },

      /** 手动改完 DOM 后的收尾：空状态 + 同步 v-model*/
      afterManualEdit: function () {
        this.normalizeEmpty();
        this.emitUpdate();
      },

      /* ---------------- 事件：鼠标 / 粘贴 ----------------*/

      onMouseDown: function (event) {
        /* token 上按下：不移动光标、不产生选择，留给 click 去 emit*/
        if (!this.tokenFromEvent(event)) return;
        event.preventDefault();
        event.stopPropagation();
      },

      onMouseUp: function () {
        var self = this;
        setTimeout(function () { self.normalizeSelection(); }, 0);
      },

      onClick: function (event) {
        var token = this.tokenFromEvent(event);
        if (!token) return;
        event.preventDefault();
        event.stopPropagation();
        var meta = tokenMeta(token);
        this.$emit('token-click', {
          code: meta.code, name: meta.name, text: meta.text, event: event
        });
      },

      onPaste: function (event) {
        var root = this.$el;
        if (!root) return;
        var clip = event.clipboardData || window.clipboardData;
        if (!clip || !clip.getData) return;     /* 没数据 → 让浏览器原生处理*/
        var text = '';
        try { text = String(clip.getData('text/plain') || ''); } catch (err) { text = ''; }
        event.preventDefault();                 /* 永远不要 HTML/富文本粘贴*/
        if (!text) return;

        var sel = window.getSelection();
        var range = null;
        if (sel && sel.rangeCount > 0) {
          var live = sel.getRangeAt(0);
          if (this.selectionInside(live)) range = live.cloneRange();
        }
        if (!range) {
          range = document.createRange();
          range.selectNodeContents(root);
          range.collapse(false);
        }
        range.deleteContents();

        /* 末尾放一个空文本节点当光标锚点，插完就换成 (parent, index) 定位并移除*/
        var tail = document.createTextNode('');
        var frag = this.buildFragment(text);
        frag.appendChild(tail);
        try { range.insertNode(frag); } catch (err) { return; }

        var parent = tail.parentNode;
        var index = domChildIndex(parent, tail);
        if (parent) parent.removeChild(tail);
        if (sel && parent) {
          try {
            var caret = document.createRange();
            caret.setStart(parent, index < 0 ? 0 : index);
            caret.collapse(true);
            sel.removeAllRanges();
            sel.addRange(caret);
          } catch (err) { /* ignore*/ }
        }
        /* 粘贴可能把 /命令 挤离文本开头（或粘进来的内容本身是命令）→ 对齐一次 token 状态*/
        this.syncSlashToken();
        this.afterManualEdit();
      },

      /* ---------------- 选择归一 / token 工具 ----------------*/

      /** 选区是否完全落在本组件内*/
      selectionInside: function (range) {
        var root = this.$el;
        if (!root || !range) return false;
        var s = range.startContainer;
        var e = range.endContainer;
        var okS = s === root || (root.contains && root.contains(s));
        var okE = e === root || (root.contains && root.contains(e));
        return !!(okS && okE);
      },

      /** 事件目标里的 @token（且属于本组件）。
          ⚠️ 这里**只认 mention-token** —— /命令 token 不是资源，点了不跳详情、也不拦光标。*/
      tokenFromEvent: function (event) {
        var target = event && event.target;
        var root = this.$el;
        if (!target || target.nodeType !== 1 || !root) return null;
        var el = target.closest ? target.closest('.' + TOKEN_CLASS) : null;
        if (!el) {
          /* SVG/文本节点等极端情况：往上走一层再看*/
          var p = target.parentElement;
          el = p && p.closest ? p.closest('.' + TOKEN_CLASS) : null;
        }
        return el && root.contains(el) ? el : null;
      },

      /** 节点若落在某个原子块内（@资源 或 /命令），返回该元素*/
      tokenAtNode: function (node) {
        var root = this.$el;
        if (!root || !node) return null;
        var el = node.nodeType === 1 ? node : (node.parentElement || null);
        if (!el || !el.closest) return null;
        var token = el.closest(ATOMIC_SELECTOR);
        return token && root.contains(token) ? token : null;
      },

      /** 选区是否覆盖到原子块（@资源 或 /命令）—— 覆盖到就整段删，不留半截*/
      rangeHasToken: function (range) {
        var root = this.$el;
        if (!root || !range || !range.intersectsNode) return false;
        var tokens = root.querySelectorAll(ATOMIC_SELECTOR);
        for (var i = 0; i < tokens.length; i += 1) {
          try { if (range.intersectsNode(tokens[i])) return true; } catch (err) { /* ignore*/ }
        }
        return false;
      },

      /**
       * 计算扩到 token 完整边界的选区。
       * @returns {{range: Range|null, changed: boolean}}*/
      expandedRange: function (range) {
        var root = this.$el;
        if (!root || !range) return { range: null, changed: false };
        var units = collectUnits(root);
        if (!units.length) return { range: null, changed: false };
        var specs = units.map(unitSpec);
        var start = pointToPos(units, root, range.startContainer, range.startOffset);
        var end = pointToPos(units, root, range.endContainer, range.endOffset);
        var ex = expandPositions(specs, start, end);
        if (!ex.changed) return { range: null, changed: false };
        var r = rangeFromPositions(units, root, ex.start, ex.end);
        if (!r) return { range: null, changed: false };
        return { range: r, changed: true };
      },

      /**
       * 选择归一（核心需求）：任何 selection 只要部分相交 token，就扩展到 token 完整边界。
       * 幂等：扩展后的选区已经是 token 边界，下一次进来 changed=false 直接返回，不会死循环。*/
      normalizeSelection: function () {
        if (this.normalizing || this.composing) return;
        var sel = window.getSelection();
        if (!sel || !sel.rangeCount) return;
        var range = sel.getRangeAt(0);
        if (range.collapsed) return;            /* 光标不算框选，不动它*/
        var root = this.$el;
        if (!root || !this.selectionInside(range)) return;
        var expanded = this.expandedRange(range);
        if (!expanded || !expanded.changed || !expanded.range) return;
        this.normalizing = true;
        try {
          this.applyRange(sel, expanded.range);
        } finally {
          this.normalizing = false;
        }
      },

      applyRange: function (sel, range) {
        if (!sel || !range) return;
        try {
          sel.removeAllRanges();
          sel.addRange(range);
        } catch (err) { /* 选区正被浏览器回收时忽略*/ }
      },

      /** 选中整个单元（用于 Backspace 第一次按键）*/
      selectUnit: function (units, idx) {
        var unit = units[idx];
        var sel = window.getSelection();
        if (!unit || !unit.el || !sel) return;
        var parent = unit.el.parentNode;
        var i = domChildIndex(parent, unit.el);
        if (i < 0) return;
        try {
          var r = document.createRange();
          r.setStart(parent, i);
          r.setEnd(parent, i + 1);
          sel.removeAllRanges();
          sel.addRange(r);
        } catch (err) { /* ignore*/ }
      },

      /**
       * 空状态处理：没有 token 且只剩换行/空白换行 → 清空 innerHTML。
       * 原因：contenteditable 空着时浏览器常留一个 <br>，:empty：before 的 data-placeholder 就不显示。
       * @returns {boolean} 是否发生了清空*/
      normalizeEmpty: function () {
        var root = this.$el;
        if (!root) return false;
        if (!root.childNodes.length) return false;
        if (root.querySelector(ATOMIC_SELECTOR)) return false;
        var text = getPlainTextFrom(root);
        if (text.replace(/[\r\n]/g, '') !== '') return false;   /* 有真实字符就保留*/
        var hadFocus = false;
        try { hadFocus = document.activeElement === root; } catch (err) { hadFocus = false; }
        root.innerHTML = '';
        if (hadFocus) caretTo(root, 0);         /* 清空后把光标放回起点，不然看起来丢了光标*/
        return true;
      }
    },

    /* 纯逻辑函数也挂在组件对象上（离线自测用；不是新的全局名）*/
    __pure: {
      parseMentions: parseMentions,
      expandPositions: expandPositions,
      adjacentTokenIndex: adjacentTokenIndex,
      getPlainTextFrom: getPlainTextFrom,
      mentionSource: MENTION_SOURCE,
      tokenClass: TOKEN_CLASS,
      /* /命令 token*/
      slashClass: SLASH_CLASS,
      atomicSelector: ATOMIC_SELECTOR,
      defaultCommands: DEFAULT_COMMANDS,
      matchSlashCommand: matchSlashCommand,
      commandAllowed: commandAllowed,
      parseRichText: parseRichText,
      slashNeedsRebuild: slashNeedsRebuild,
      flatOffsetOfPos: flatOffsetOfPos,
      posFromFlatOffset: posFromFlatOffset,
      unitWidth: unitWidth,
      atomicRole: atomicRole,
      collectUnits: collectUnits
    }
  };

  window.RichAiInput = RichAiInput;
})();
