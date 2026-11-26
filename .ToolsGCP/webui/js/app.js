/* ============================================================================
 * ToolsGCP · Web 前端主程序（对应原版 ui/main_window.py + 各 interface）
 * ============================================================================
 * 结构与尺寸的出处（不再自创元素）：
 *   标题栏 48 / 窗口按钮 46×32                FluentTitleBar（main_window.py:308-309）
 *   侧栏 48 ↔ 240 **悬浮展开**                main_window.py:466-468
 *                                            （setExpandWidth(240) + minimumExpandWidth(1500)
 *                                             ⇒ 阈值 1418 > 窗口宽 ⇒ 永远是 flyout，不挤压内容）
 *   导航顺序 首页/搜索/定制页/收藏/GCP工坊 │ 公告/Github/更多/设置   init_navigation :380-434
 *   更多= 反馈 / 查看日志 / 应用部署 / 插件 / 提交软件            more_menu_pages :1473-1494
 *   AI 条目：只在开启 GCP-AI + 侧边栏 AI 模式时出现，紧跟 GCP工坊  apply_ai_sidebar_mode
 *   搜索页：搜索框居中 320~720 + 工具条一行 + 可展开筛选面板            search_interface.py:272-474
 *   **整页只有一个滚动容器**（原版 QScrollArea），列表不自己滚            同上 :278-282
 *   卡片：磁贴 196×min272 间距 14 / 网格 149×min168 间距 12；右上只有收藏；
 *        @给GCP-AI 走右键；hover 只做 140ms 灰阶叠色                     app_card.py:233-278/852-933/1363-1400
 *   分组标题带全角：、组间距 16                                       apps_index_framework.py:1144-1165
 *   筛选：无确定/重置，点胶囊即时生效；最新只在筛选变化时刷新          search_interface.py:1106-1120
 *   搜索/筛选/排序/分组**一律委托后端** resources.query（算法唯一真源）
 *   设置 12 个板块（顺序见 app.js 的 sections；为 外观/动画/启动/搜索/快捷键/下载/
 *   通知/功能/存储/GCP-AI/开发者功能/关于；原授权已并入功能）+ 行 48/60、控件 200、卡片圆角 10
 * 数据全部来自桌面端真实接口：resources / favorites / settings / i18n / shell / window / app
 * 后端没有的接口一律 tryCall → 明确提示"接口未就绪"，绝不假装成功。
 * ==========================================================================*/

const { createApp, ref, reactive, computed, watch, onMounted, onBeforeUnmount, nextTick } = Vue;

/* ===================== 原版常量 =====================*/
const CATEGORY_ORDER = ['工具', '游戏', '平台', '编程', '游戏引擎',
                        '视频平台', '建筑/设计', 'AI', '个性化'];      // resource_query.py:27-30
const FALLBACK_CATEGORY = '其他';                                      // resource_query.py:28
const LATEST_N = 10;                                                   // resource_query.py:39
const UPDATED_DAYS = { '10d': 10, '30d': 30, '180d': 180 };             // resource_query.py:41
/* 适用系统闭集：与 resource_schema.py 的 SYSTEMS **逐项同序**（顺序就是界面顺序）。
   ⚠️ m04188 第④项扩充过：新增 iPadOS / watchOS / tvOS / visionOS / HarmonyOS / ChromeOS，
      以后改动只改 resource_schema.py，然后同步这一行和下面的 makerPlatforms。 */
const SYSTEMS = ['全平台', 'Windows', 'macOS', 'Linux', 'Android', 'iOS',
                 'iPadOS', 'watchOS', 'tvOS', 'visionOS', 'HarmonyOS', 'ChromeOS',
                 'web', '其他'];
const CARD_PRESETS = {                                                   // app_card.py:233-278
  small: { height: 168, icon: 48, lines: 2, button: 22, buttonIcon: 14 },
  medium: { height: 196, icon: 64, lines: 2, button: 26, buttonIcon: 16 },
  large: { height: 240, icon: 80, lines: 3, button: 26, buttonIcon: 16 },
};
const TILE = { minW: 272, spacing: 14, base: 4, maxCardW: 400 };         // CARD_WIDTH / CARD_SPACING
const GRID = { minW: 168, spacing: 12, base: 6, maxCardW: 240 };         // GRID_MIN_WIDTH / GRID_SPACING
const GROUP_H = 40, GROUP_GAP = 16, PAGE_MARGIN = 24;
const DEPLOY_STATES = { pending: '待部署', downloading: '下载中', downloaded: '已下载',
                        opened: '已打开官网', skipped: '已跳过', failed: '失败' };

/* 原版 DEFAULT_SETTINGS（constants.py:156-249）：仅作前端兜底，真值一律来自 settings.get*/
const DEFAULT_SETTINGS = {
  theme: '跟随系统', accent_color: 'blue', language: '跟随系统', license_key: '',
  notify_enabled: true, last_search: '', startup_with_windows: false, minimize_to_tray: true,
  default_page: '搜索', close_mode: '彻底退出', open_settings_on_restart: false,
  dev_mode_enabled: false, dev_mode_admin: '', dev_mode_verify_time: '', dev_mode_key: '',
  debug_info_enabled_Galen563: false, debug_info_enabled_Cyric373: false,
  search_source: 'Github', download_source: 'Github', download_speed_limit_enabled: false,
  download_speed_limit: 100, deploy_mode: false, splash_screen_enabled: false,
  // ⚠️ `splash_screen_duration` 本轮已随需求删除（显示时长改由主流程决定，
  //    见 desktop/shell.py 的 _dismiss_splash）；后端 constants.py 同步删掉了这个键。
  auto_search: true, hotkey_enabled: true,
  hotkey_search: 'Ctrl+Q', hotkey_ai: 'Ctrl+Alt+G', search_card_size: 'medium',
  search_view: 'tile', search_show_github: true, search_show_view_switch: true,
  plugin_view: 'grid', resource_source: 'cloud', local_resource_dir: '',
  update_channel: 'all', update_auto_check: 'corner',
  /* 本轮：自动检查里被用户点「取消」跳过的那个版本号（空 = 没跳过过任何版本）。
     必须落盘（下次启动同一个版本不能再弹），见 app.js 的 muteUpdateTag / autoCheckUpdate。 */
  update_muted_tag: '',
  api_key: '', api_key_enc: '', model_name: '',
  ai_provider: 'deepseek', api_base: 'https://api.deepseek.com/v1',
  /* ⚠️ 本轮新增（与 pymodels/constants.py 同名键一一对应，别只加一边）：
     · ai_profile_id     —— 聊天框里显式选中的**档案 id**（同厂商两条档案靠它区分）
     · ai_thinking_level —— 按模型记的思考档位 { "<provider>|<model>": "high" } */
  ai_profile_id: '', ai_thinking_level: {},
  ai_enabled: false, ai_sidebar_mode: false, limit_token_output: false,
  min_token: 0.5, max_token: 4096, ai_context_rounds: 0, ai_reply_mode: 'standard',
  /* GCP-AI 输入框的润色按钮开关（默认开；关掉后按钮消失，见 index.html .ai-polish）*/
  ai_polish_enabled: true,
  /* GCP-AI 逐字（流式）输出开关（默认开）。
     ⚠️ 这个键**只在纯前端**（这份默认对象 + settings.set 落到用户配置），
        故意不加进 pymodels/constants.py 的 DEFAULT_SETTINGS（那边 Lead 在改，避免撞车）。
        后端 ai.send_stream 不读这个键 —— 由前端决定调哪个接口：
        开 → send_stream + 收 ai.stream 事件；关 / 后端没这个接口 → 退回原来的整段 ai.send。 */
  ai_stream_enabled: true,
  /* GCP-AI「思考」强度档位（输入框内下排左侧的滑块）：默认 off（需求"默认思考都为关闭"）。
     ⚠️ 本轮起这个键存**档位字符串**："off" / "low" / "medium" / "high"
       （= 官方 reasoning_effort，需求"改为对接官方API的多档位滑动强度而不是只有开和关"）。
       旧配置里存的布尔 True/False 由 normalizeAiThinking() 兜掉，后端同一套归一化口径。
       ⚠️ 别再对它用 settingOn()：那是布尔判定，`settingOn("off")` 会因为非空字符串判成真，
          滑块看着在高档位、后端其实关着 —— 用户报的"改了并没有立即变化"的一条根因。
       键已加进 pymodels/constants.py 的 DEFAULT_SETTINGS（两边同一默认值）。 */
  ai_thinking: 'off',
  /* GCP-AI 回复语言（新增设置项，后端 ai-backend 会在 model_choices 里回 reply_languages）：
     auto = 跟随输入语言；其余为强制回复语言。真值清单优先用后端给的，拿不到走前端兜底 4 项。
     ⚠️ 与 ai_thinking 一样是**字符串枚举**，别用 settingOn()。 */
  ai_reply_language: 'auto',
  /* 对话模式（本轮新增）：'chat' 只聊天（默认）/ 'agent' 允许动手。
     ⚠️ 和 gcp_ai_agent_enabled 分工不同：那是插件总开关（强制开启），
        这是"本次对话要不要真的动手"。前端按钮/胶囊都读它。 */
  ai_chat_mode: 'chat',
  gcp_ai_agent_enabled: false, gcp_ai_agent_tools_off: [], gcp_plugin_maker_enabled: false,
  gcp_plugin_maker_options: {}, ui_font_family: '微软雅黑',
  /* ---- 新增的四个设置（默认值按需求定）----*/
  theme_effect: 'mica',              // 主题效果：mica 云母 / glass 毛玻璃 / acrylic 亚克力
  ui_animation: 'on',                // UI 动画：on 开启 / reduced 减少动画 / off 关闭动画（默认开启）
  nav_hover_expand: false,           // 侧栏鼠标靠近自动展开（默认关）
  nav_indicator_bounce: false,        // 侧边栏指示 Q 弹（默认关 = 到位即停，没有回弹）
  toast_position: 'top',             // 提示框位置（默认顶端居中）
  scroll_inertia: false,             // 滚动惯性（默认关闭；开启后滚停会再滑一小段）
  scroll_inertia_strength: 35,       // 惯性大小（%，1~100，默认 35；只在滚动惯性开启时生效）
  /* ---- 下载相关的新设置（键名/默认值必须与 constants.py 的 DEFAULT_SETTINGS 一致）----
     download_save_dir   : 空 = 系统下载文件夹（去掉了自动生成的 ToolsGCP 子目录）
     download_threads    : 多线程下载并发数（1~100，默认 100）
     download_retry_count: 失败重试次数（1~20，默认 5，每次间隔 30s）
     releases_source     : Releases 弹窗下拉框 official（默认）/ all*/
  download_save_dir: '',
  download_threads: 100,
  download_retry_count: 5,
  releases_source: 'official',
  /* 原版也会写进配置、但不在 DEFAULT_SETTINGS 里的键*/
  customize_interests: [], customize_onboarded: false,
};

const SOURCE_OPTIONS = ['Github', 'ghfast.top', 'gh-proxy.com', 'ghproxy.net', 'gh.ddlc.top'];
/* 设置里的布尔值归一化（旧配置里可能是字符串 "true"/"false"、数字 1/0、undefined）。
   为什么要统一：/plugin 门控、插件卡片开关都直接读 settings，若各处各写一套判断，
   旧配置字符串 "false" 会被 `!!` 当成"开"（这就是"只开 Agent 却冒 /plugin"的一类泄漏）。
   ⚠️ 必须与后端 `desktop/api/plugins.py：maker_enabled()` 的严格判定保持一致：*/
function settingOn(value) {
  if (value === true) return true;
  if (value === false || value === null || value === undefined) return false;
  if (typeof value === 'number') return value !== 0;
  if (typeof value === 'string') {
    return ['true', '1', 'yes', 'on'].indexOf(value.trim().toLowerCase()) >= 0;
  }
  return false;
}
const VALID_LICENSE_KEYS = ['GCP-74G2-N052-8X42', 'GCP-N228-45G0-Y728', 'GCP-054N-2G82-4Z27', 'GCP-G782-N402-5K20'];
const SPECIAL_KEYS = ['Galen563-ToolsGCP', 'GCP License Key'];
const DEV_KEYS = { 'GCP-G756-23L4-N375': 'Galen563', 'GCP-76C2-P081-5Y60': 'Cyric373' };
const AI_PROVIDERS = [
  /* ⚠️ deepseek 的模型清单与后端 providers.py 一致，这里存**界面显示名**：
     deepseek-v4.1-flash（V4.1-Flash）和 deepseek-v4-pro。
     官方文档确认：V4.1-Flash 的 API 调用名另有其名，发送前由后端
     resolve_api_model 自动转换，这里只负责展示，不写 API 内部名。 */
  { id: 'deepseek', label: 'DeepSeek（深度求索）', base: 'https://api.deepseek.com/v1',
    models: ['deepseek-v4.1-flash', 'deepseek-v4-pro'] },
  { id: 'openai', label: 'OpenAI（ChatGPT）', base: 'https://api.openai.com/v1',
    models: ['gpt-5.1', 'gpt-5.1-mini', 'gpt-4.1'] },
  { id: 'claude', label: 'Anthropic（Claude）', base: 'https://api.anthropic.com/v1',
    models: ['claude-sonnet-4-6', 'claude-opus-4-1', 'claude-haiku-4-5'] },
  { id: 'grok', label: 'xAI（Grok）', base: 'https://api.x.ai/v1',
    models: ['grok-4', 'grok-4-fast', 'grok-3'] },
  { id: 'kimi', label: 'Kimi（月之暗面）', base: 'https://api.moonshot.cn/v1',
    models: ['kimi-k3', 'kimi-k2.7-code', 'kimi-k2.6'] },
  { id: 'qwen', label: '通义千问（阿里云百炼）',
    base: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: ['qwen3-max', 'qwen-plus', 'qwen-flash'] },
  { id: 'siliconflow', label: '硅基流动 SiliconFlow', base: 'https://api.siliconflow.cn/v1',
    models: ['deepseek-ai/DeepSeek-V3', 'Qwen/Qwen3-8B', 'Qwen/Qwen3-32B'] },
  { id: 'custom', label: '自定义', base: '', models: [] },
];
const FONT_PREFERED = ['微软雅黑', '等线', 'Segoe UI', 'SimSun', 'SimHei', 'KaiTi',
                       'FangSong', 'Consolas', 'JetBrains Mono'];
const DEV_GUIDE = [
  'ToolsGCP 插件开发约定（简版）',
  '',
  '1. 一个文件夹就是一个插件，放在 .ToolsGCP/plugins/<id>/ 下；',
  '2. 必须提供 manifest.json：id / name / version / author / description /',
  '   entry / icon / enabled_setting（可选，声明由哪个设置项控制开关）/ builtin；',
  '3. 语言包放在 lang/zh_CN.json、lang/zh_TW.json、lang/en_US.json，',
  '   取词优先级「当前语言 → 简体中文」，缺词回退 key 本身；',
  '4. 需要开关的插件在 manifest 里写 enabled_setting，',
  '   程序会自动把它和设置页、GCP-AI Agent 的开关同步；',
  '5. 有配置界面的插件在 manifest 里写 config_page（相对插件目录的 HTML），',
  '   程序会在插件页里用独立界面承载；',
  '6. 装好或改完点「重新加载」即可生效，不需要重启程序。',
].join('\n');

/* ===================== 文案（原版 15 个语言模块 + 三语回退） =====================*/
/* terms：三语「类别/标签译名表」`{zh_CN|zh_TW|en_US: {规范中文值: 该语言写法}}`
   由后端 i18n.bundle 一并下发（见 desktop/api/__init__.py 的 _read_all_terms）。
   ⚠️ 它和 map/terms 的区别：map 只有**界面语言**那一份，而制作器「多语言字段」卡片
   有自己的语言分段（用户点哪个分段就编辑哪一份），那个分段**不跟随界面语言**，
   所以必须三份都有 —— 提交软件的类别/标签就是靠它按分段显示译名的。 */
const I18N = reactive({ map: {}, modules: {}, language: '简体中文', terms: {}, version: 0 });
const settingsState = ref(null);

function t(key, fallback, module) {
  void I18N.version;
  const scoped = module && I18N.modules[module];
  if (scoped && typeof scoped[key] === 'string' && scoped[key]) return scoped[key];
  const value = I18N.map[key];
  if (typeof value === 'string' && value) return value;
  return fallback === undefined ? key : fallback;
}
function flattenI18n(payload) {
  if (!payload) return;
  I18N.language = payload.language || I18N.language;
  /* 三语译名表（老后端没这个键 → 保持空表，termIn 会退回规范值，界面照常可用） */
  if (payload.terms && typeof payload.terms === 'object') I18N.terms = payload.terms;
  I18N.map = {};
  I18N.modules = payload.modules || {};
  Object.keys(I18N.modules).forEach((name) => {
    const entry = I18N.modules[name] || {};
    Object.keys(entry).forEach((key) => {
      if (I18N.map[key] === undefined) I18N.map[key] = entry[key];
    });
  });
  I18N.version += 1;
}
function uiLanguage() {
  const value = settingsState.value && settingsState.value.language;
  if (value && value !== '跟随系统') return value;
  const lang = String(navigator.language || 'zh-CN').toLowerCase();
  if (lang.includes('zh-tw') || lang.includes('zh-hk') || lang.includes('zh-hant')) return '繁體中文';
  if (lang.startsWith('zh')) return '简体中文';
  return 'English';
}
/* 语言代码 → manifest 里的「语言名」键。
   ⚠️ 内置插件的 manifest.name / description 用的是语言名（简体中文 / 繁體中文 / English），
      而 uiLanguage() 返回的是代码（zh_CN / en_US）。旧实现只查代码，命中不了就一路退到简体中文，
      于是「界面切成英文、插件中心还是满屏中文」——用户反馈的插件页面不跟随语言就是这个。
      取值顺序与后端 plugins.py 的 _pick_locale 保持一致。 */
const LANG_NAME_BY_CODE = { zh_CN: '简体中文', zh_TW: '繁體中文', en_US: 'English' };
function pickI18n(value, fallback) {
  if (value == null) return fallback || '';
  if (typeof value === 'string') return value;
  if (typeof value !== 'object') return String(value);
  const lang = uiLanguage();
  const chain = [LANG_NAME_BY_CODE[lang], lang, '简体中文', 'zh_CN', 'English', 'en_US'];
  for (const key of chain) {
    if (key && value[key]) return String(value[key]);
  }
  for (const item of Object.values(value)) {   // 最后兜底：别让插件名退化成 id
    if (item) return String(item);
  }
  return fallback || '';
}
/* 类别/标签/系统/架构的**显示译名**（匹配仍用规范中文值 —— common_language.json 的 term_*）*/
function term(value) {
  if (!value) return '';
  const hit = I18N.map['term_' + value];
  if (typeof hit === 'string' && hit) return hit;
  /* 未命中再按规范值查一次（对齐 py 的 translate_term 两段查）：老数据/云端镜像里存的
     可能本身就是繁体或英文写法，直接原样显示会变成"只有外文"。 */
  const canon = canonicalAny(value);
  if (canon !== value) {
    const again = I18N.map['term_' + canon];
    if (typeof again === 'string' && again) return again;
  }
  return value;
}

/* ---------- 按**指定语言**取类别/标签的译名（制作器多语言分段专用） ----------
   与 term() 的差别：term() 只看界面语言，这里看调用方给的那一种语言。
   制作器「多语言字段」卡片里的类别/标签要跟着**卡片自己的分段**变，
   而分段可以是三种语言里的任意一种，与界面语言无关，所以必须有这一族函数。
   ⚠️ 全部读 I18N.terms（reactive）⇒ 设置里切语言、bundle 重新下发时会自动重算，
      不需要额外 void I18N.version。 */
const LANG_LOCALES = { 简体中文: 'zh_CN', 繁體中文: 'zh_TW', English: 'en_US' };
/* 规范中文值 → 该语言的写法；认不出来（自定义类别）原样返回 */
function termIn(lang, value) {
  if (!value) return '';
  const table = I18N.terms[LANG_LOCALES[lang] || 'zh_CN'] || {};
  const hit = table[value];
  return (typeof hit === 'string' && hit) ? hit : value;
}
/* 该语言的写法 → 规范中文值（落盘/匹配一律用规范值，界面只负责显示译名）。
   ⚠️ 三种语言的写法都认：用户在 English 分段敲 "Tools"、在繁體分段敲 "遊戲"，
      和在简体中文分段敲 "游戏" 是同一件事 —— 都还原成规范值存起来，
      所以"手动输入的文本只要和内置项一样，就同样视为内置的多语言"。
      规范值本身也认（zh_CN 表里 term_工具 的值就是 "工具"，天然覆盖这一种）。 */
function canonicalIn(lang, value) {
  const text = String(value == null ? '' : value).trim();
  if (!text) return '';
  const table = I18N.terms[LANG_LOCALES[lang] || 'zh_CN'] || {};
  for (const canonical of Object.keys(table)) {
    if (String(table[canonical]) === text) return canonical;
  }
  return text;                      // 自定义值：原样保留，可继续手动修改
}
/* ---------- 写法 → 规范中文值（对齐 py 的 language_manager.canonical_term） ----------
   第五轮需求③「更多筛选里很多只有简体中文」的地基：术语表一个概念只登记**规范简体中文值**
   一个键，繁简/英文只是同一概念的其它写法。候选列表必须先折叠成规范值，否则
   「游戏平台 / 遊戲平台 / Game platform」在下拉里并列三项，而简体中文界面里只有第一项
   显示成本地文字，后两项看着就是"没翻译"。

   ⚠️ 反查表按**界面语言优先**构建（当前语言的写法先入表）：库里存在同一个写法既是
      甲语言规范值、又是乙语言译名值的情况（Photo Tool 的简体译名「图片工具」），
      先到先得才能保证用户看到他自己语言里的写法。py 端固定 zh_CN→zh_TW→en_US，
      差异只落在极少数交叉写法上，规范值本身两边一致。
   ⚠️ 缓存失效依据是 I18N.terms 的**引用**：flattenI18n 是整体赋值（见 :197），
      换语言/重新下发 bundle 都会换引用；再按 locale 分桶，切语言不全表重建。
   ⚠️ 查不到（用户自己敲的类别/标签）原样返回 —— 绝不吞掉自定义值。 */
const CANON_ORDER = ['zh_CN', 'zh_TW', 'en_US'];
const CANON_CACHE = { source: null, byLang: {} };
function canonicalMap(lang) {
  const locale = LANG_LOCALES[lang] || 'zh_CN';
  if (CANON_CACHE.source !== I18N.terms) {
    CANON_CACHE.source = I18N.terms;
    CANON_CACHE.byLang = {};
  }
  if (CANON_CACHE.byLang[locale]) return CANON_CACHE.byLang[locale];
  /* Object.create(null)：术语表可能有 "__proto__" 这种键名，普通对象会被污染原型 */
  const map = Object.create(null);
  const order = [locale].concat(CANON_ORDER.filter((x) => x !== locale));
  order.forEach((loc) => {
    const table = I18N.terms[loc] || {};
    Object.keys(table).forEach((canon) => {
      const spell = String(table[canon]);
      if (!(spell in map)) map[spell] = canon;     // 先到先得 = 当前语言优先
    });
  });
  CANON_CACHE.byLang[locale] = map;
  return map;
}
function canonicalAny(value) {
  const text = String(value == null ? '' : value).trim();
  if (!text) return '';
  const hit = canonicalMap(uiLanguage())[text];
  return (typeof hit === 'string' && hit) ? hit : text;
}

/* 逗号/顿号/分号分隔的文本 ⇄ 规范值数组（显示按语言、存储按规范值） */
function termsToText(lang, list) {
  return (list || []).map((value) => termIn(lang, value)).join(', ');
}

/* ===================== 桥（pywebview js_api） =====================*/
const bridge = {
  ready: false,
  api: null,
  _initPromise: null,

  /* ⚠️ 必须缓存这个 Promise：以前每次 tryCall 在 api 未就绪时都 new 一个 Promise
     各等 4 秒，十几次调用叠起来就是 40 多秒 —— 表现就是"窗口出来了但永远卡在启动页"。
     现在整个进程只初始化一次，后续所有调用共用同一个 Promise。
     ⚠️⚠️ 但这条 Promise **必须先等"浏览器模式探测"落定**（bridge.probePromise，见下面
     installHttpBridge）：原来两边各跑各的 —— 探测是一个异步 fetch，而 init 只等
     pywebview 事件 + 2 秒兜底。浏览器里 pywebview 永远不会出现，于是 init 先以
     `api = null` 落定，并把这份 null **缓存进 _initPromise**；探测随后才把 bridge.init
     换成 HTTP 版，可所有调用方拿到的还是那份已经 resolve 成 null 的旧 Promise
     → `has()` 恒 false → 每个 tryCall 都走 needApi 降级。
     用户报的"浏览器模式下功能/配置/图片全部加载不上来"正是这个竞态，以及它引发的
     连锁降级（设置读不到、资源库读不到、语言包读不到）。
     桌面端同样受益：探测只是本地回环的一次 fetch（毫秒级），不再白等 2 秒兜底。 */
  probePromise: null,          // 由 installHttpBridge **同步**赋值；null = 无需探测（file://）

  async init() {
    if (this.ready && this.api) return this.api;
    if (this._initPromise) return this._initPromise;
    this._initPromise = (async () => {
      /* ① 先等浏览器模式探测落定（file:// 等场景 probePromise 为 null，直接跳过）*/
      if (this.probePromise) {
        try { await this.probePromise; } catch (e) { /* 探测失败 = 按桌面端处理 */ }
      }
      /* ② 探测判定为浏览器模式 → 用 HTTP 传输（api 是一个 Proxy，语义与 pywebview 一致：
         「域.方法」不在 capabilities 清单里 → get 返回 undefined → has() false → 调用方降级）*/
      if (httpBridge.active) {
        this.api = new Proxy({}, {
          get(_t, domain) {
            if (typeof domain !== 'string') return undefined;
            return new Proxy({}, {
              get(_t2, method) {
                if (typeof method !== 'string') return undefined;
                const path = `${domain}.${method}`;
                if (!httpBridge.has(path)) return undefined;
                return (...args) => httpBridge.call(path, args);
              },
            });
          },
        });
        this.ready = true;
        /* ⚠️⚠️ 把这份"伪 pywebview.api"再挂到 window.pywebview 上，给**插件配置页**用。
           插件的配置页是 iframe（/res/plugins/<id>/config.html），它自己有一套
           findApi()：先取 `window.pywebview.api`，取不到再退回 `parent.pywebview.api`
           （见 gcp-ai-agent/config.html）。浏览器模式里全系统都没有 pywebview，
           于是插件配置页永远拿到 null → 页面显示"预览模式 / Agent 暂时不可用"、
           设置读写全部失效 —— 这就是用户说的"浏览器模式下配置全部加载不上来"里
           属于插件页那一半。
           挂在这里的好处：插件页一行都不用改（它们本来就认 parent.pywebview.api），
           而且同源 iframe 读得到。桌面端永远走不到这个分支，不受任何影响。 */
        try {
          window.pywebview = window.pywebview || {};
          if (!window.pywebview.api) window.pywebview.api = this.api;
        } catch (e) { /* 挂不上也只是插件页退回原样，不影响主界面 */ }
        return this.api;
      }
      /* ③ 桌面端：等 pywebview 注入（1.5 秒兜底放行，调用方按 null 显式降级）*/
      return await new Promise((resolve) => {
        /* ⚠️⚠️⚠️ 这条兜底超时**绝不能把 Promise 一次性定死**（用 settled 直接 resolve 掉），
           因为整个结果会被缓存进 _initPromise：pywebview 万一在 1.5 秒**之后**才注入
           （WebView2 冷启动、或者用户从最小化恢复时才建好），这份缓存的 null 就会
           **永久**把界面钉死在"接口未就绪"上 —— 那是把老 bug 换个方式再犯一遍。
           正确做法：兜底到点先放行（不卡启动），但**监听一直留着**，
           pywebviewready 真来了就把 api/ready 补上并再 resolve 一次
           （第二次 resolve 是空操作，可状态修好了；后面 has()/call() 读的是
           this.api，自动就用上了真接口）。
           同理，`tryCall` 里 `if (!this.api) await this.init()` 的短路也靠
           has() 读最新 this.api 来兜住。 */
        const attach = (resolveOnce) => {
          const api = (window.pywebview && window.pywebview.api) || null;
          if (!api) return false;
          this.api = api;
          this.ready = true;
          if (resolveOnce) resolve(api);
          return true;
        };
        if (attach(true)) return;                       // 已经注入好了
        window.addEventListener('pywebviewready', () => {
          /* 事件来了：把 api 补上。**只在首次放行前**用它 resolve，
             放行之后再来也只是修状态，不需要（也不能）再 resolve 第二次。 */
          attach(this.ready !== true);
        });
        setTimeout(() => { if (!attach(false)) resolve(null); }, 1500);
      });
    })();
    return this._initPromise;
  },

  has(path) {
    /* 浏览器模式：清单就是唯一真源。不能走下面那条"逐段取属性"的路 ——
       capabilities 里除了「域.方法」还有**根级方法**（api.ping 这种一层的），
       而 Proxy 对一层路径只能返回"内层 Proxy"（不是 function）→ 一律判 false，
       表现就是启动探针失败、部分功能在浏览器里莫名不可用。 */
    if (httpBridge.active) return httpBridge.has(String(path));
    if (!this.api) return false;
    const parts = String(path).split('.');
    let target = this.api;
    for (let i = 0; i < parts.length; i += 1) target = target && target[parts[i]];
    return typeof target === 'function';
  },

  async call(path, ...args) {
    if (!this.api) await this.init();
    /* 浏览器模式：走 HTTP 桥（根级方法也能正确寻址，见 has 的同款说明）*/
    if (httpBridge.active) return await httpBridge.call(String(path), args);
    if (!this.api) throw new Error('pywebview api 未就绪');
    const parts = String(path).split('.');
    let target = this.api;
    for (let i = 0; i < parts.length - 1; i += 1) target = target && target[parts[i]];
    const fn = target && target[parts[parts.length - 1]];
    if (typeof fn !== 'function') throw new Error('缺少接口: ' + path);
    return await fn(...args);
  },

  /* 后端还没做的域返回 null —— 调用方必须显式降级（不假装成功）*/
  async tryCall(path, ...args) {
    if (!this.api) await this.init();
    if (!this.has(path)) return null;
    try { return await this.call(path, ...args); } catch (error) { return null; }
  },
};

/* ===================== 浏览器模式（Ctrl+Caps+O）：HTTP 桥适配器 =====================
   桌面端走 window.pywebview.api；系统默认浏览器里没有 pywebview 注入。
   需求"功能和操作完全一致，只是换到了浏览器中"→ 这里把 bridge 的两条传输换成
   HTTP（后端 desktop/browsermode.py 的 /jsbridge/*），**其余前端代码一行不改**：
   · call   → POST /jsbridge/call/<域.方法>   body {"args":[...]}
   · has    → capabilities 清单（启动时拉一次，照 pywebview 的函数存在性口径）
   · events → POST /jsbridge/events/poll 长轮询，拿到事件照常 window.ToolsGCP.emit
   ⚠️ 触发条件：window.pywebview 2 秒内没出现（bridge.init 的兜底超时就是 2s），
      且当前页面是从 http(s):// 打开的（file:// 或 WebView2 桌面端绝不启用，
      免得桌面端等 2 秒后又多走一遍 HTTP）。 */
const httpBridge = {
  active: false,          // true = 浏览器模式（HTTP 传输接管）
  caps: null,             // Set<string>：后端有哪些 "域.方法"
  _polling: false,

  async fetchCaps() {
    const r = await fetch('/jsbridge/capabilities', { method: 'POST', body: '{}' });
    if (!r.ok) throw new Error('capabilities ' + r.status);
    const data = await r.json();
    this.caps = new Set(data.methods || []);
    return data;
  },

  /* 桥在跑但清单还是空的（后端 shell.api 在启动过程中才挂上）→ 隔一会儿再取一次。
     ⚠️ 有上限：桥要是被关掉了，这里就自然停手，不会无限打请求。 */
  async retryCaps(times, gapMs) {
    const n = Math.max(1, times || 5);
    const gap = Math.max(200, gapMs || 600);
    for (let i = 0; i < n; i += 1) {
      await new Promise((res) => setTimeout(res, gap));
      if (!this.active) return;
      try {
        await this.fetchCaps();
        if (this.caps && this.caps.size) return;
      } catch (e) { return; }              // 服务没了 / 网络断了：不再重试
    }
  },

  has(path) { return !!(this.caps && this.caps.has(String(path))); },

  async call(path, args) {
    const r = await fetch('/jsbridge/call/' + String(path), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ args: args || [] }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
    return data.result;      // 桥把"方法返回值"包在 result 里；方法本身可能 ok:false
  },

  startPolling() {
    if (this._polling) return;
    this._polling = true;
    const loop = async () => {
      while (this._polling && this.active) {
        try {
          const r = await fetch('/jsbridge/events/poll', {
            method: 'POST', body: '{}',
            signal: AbortSignal.timeout ? AbortSignal.timeout(15000) : undefined,
          });
          if (r.status === 403) { this._polling = false; break; }   // 换端口了 → 停
          if (!r.ok) { await new Promise((res) => setTimeout(res, 1000)); continue; }
          const data = await r.json().catch(() => null);
          (data && data.events || []).forEach((ev) => {
            window.ToolsGCP.emit(ev.name, ev.payload);
          });
        } catch (e) {
          await new Promise((res) => setTimeout(res, 1500));      // 网络抖动 → 稍后重试
        }
      }
    };
    loop();
  },
};
(function installHttpBridge() {
  /* ⚠️⚠️ 激活判据必须是【/jsbridge/capabilities 返回 200】，绝不能是
     "location 是 http 且暂时没有 window.pywebview"：
     桌面端 WebView2 的页面**同样是** http://127.0.0.1:随机端口 加载的
     （pywebview 把 WSGI 应用转成 URL），而本脚本执行那一刻 pywebview 的注入
     还没完成 —— 按"没有 pywebview"判会误激活，随后 capabilities 在普通 webhost
     上 404 → caps 为空 → 所有 tryCall 全部降级 = 界面全瘫。
     capabilities 这条路由**只有** browsermode 的桥服务器才有（桌面端 webhost
     没有），200 = 浏览器模式，是决定性信号；404/网络错误 = 保持桌面行为。
     探测是本地回环请求，毫秒级，不拖慢启动。
     ⚠️ 这条 Promise 必须**同步**挂到 bridge.probePromise：bridge.init 用它把
     "探测落定"排在"判定桌面端降级"之前 —— 浏览器模式全线失效那个竞态就这么堵。
     （这里只置状态、不再改写 bridge.init：init 自己会按 httpBridge.active 选传输，
     两处都改一份逻辑迟早打架。） */
  const isHttp = location.protocol === 'http:' || location.protocol === 'https:';
  if (!isHttp) return;                       // file:// 等场景 → 桌面端
  bridge.probePromise = (async () => {
    try {
      const r = await fetch('/jsbridge/capabilities', { method: 'POST', body: '{}' });
      if (!r.ok) return;                     // 桌面端 webhost：404 → 不接管
      const caps = await r.json();
      /* 200 就说明这条路由存在 = 桥服务器在跑 → 判定浏览器模式。
         ⚠️ 这里**不再**拿 `methods.length` 当判据：后端 shell.api 万一还没建好，
         methods 会是空数组，按老写法就"不接管"→ 退回桌面行为 → 浏览器里根本没有
         pywebview → 全线降级。现在接管 + 稍后重取清单（has 每次都实时读 caps）。 */
      httpBridge.active = true;
      /* 浏览器模式的外壳标记**打在 <html> 上**（不是等 Vue 挂载）：
         · 顶部栏（logo + ToolsGCP + 最小化/最大化/关闭）在浏览器里毫无意义 ——
           窗口由浏览器管，那三个按钮点对真实窗口之外的东西，还会和页面抢位置；
           需求明确要求隐藏（base.css 里 `html.is-browser-mode .titlebar{display:none}`）。
         · 同时把 --tb-height 归零：AI 抽屉 / toast / 插件页这些浮层都按
           `top: var(--tb-height)` 定位，标题栏没了就不该再留那 48px 空档。
         写在 <html> 上还有一层意义：首帧就生效，不会出现"标题栏先闪一下再消失"。 */
      document.documentElement.classList.add('is-browser-mode');
      /* ⚠️ 不能直接写 `window.ToolsGCP.browserMode = true`：
         `window.ToolsGCP = window.ToolsGCP || {}` 在本文件**更后面**才执行
         （事件总线那一节），这里只是"恰好"靠 await 之后同步代码跑完才侥幸成立。
         自己先补一句 `|| {}`，不依赖任何执行顺序。 */
      window.ToolsGCP = window.ToolsGCP || {};
      window.ToolsGCP.browserMode = true;
      httpBridge.caps = new Set(caps && Array.isArray(caps.methods) ? caps.methods : []);
      if (!httpBridge.caps.size) {
        /* 桥在、清单还没好：给它几次重试的机会（后端 api 是启动过程中才挂上的）*/
        httpBridge.retryCaps(5);
      }
      httpBridge.startPolling();
    } catch (e) {
      httpBridge.active = false;             // 服务不在了 → 保持桌面行为
    }
  })();
})();

/* ===================== 后端 → 前端事件（原版 pyqtSignal 的等价物） =====================*/
window.ToolsGCP = window.ToolsGCP || {};
window.ToolsGCP._listeners = window.ToolsGCP._listeners || {};
window.ToolsGCP.on = function (name, fn) {
  (window.ToolsGCP._listeners[name] = window.ToolsGCP._listeners[name] || []).push(fn);
  return fn;
};
/* ⚠️ 必须有 off：插件配置页是 iframe，它往**父窗口**注册 settings-changed 监听
   （见各插件目录下的 config.html 里 hookHostEvents）。以前只有 on/emit，iframe 关闭时
   没法反注册 → 每开一次配置页就在父窗口的 _listeners 里永久留一个闭包。
   现在提供 off，并在 emit 时把**抛过错的**监听自动摘掉
   （监听器所在文档已销毁时调用它会抛，这比静默留着更明确）。 */
window.ToolsGCP.off = function (name, fn) {
  const list = window.ToolsGCP._listeners[name];
  if (!list) return false;
  if (!fn) { delete window.ToolsGCP._listeners[name]; return true; }
  const index = list.indexOf(fn);
  if (index < 0) return false;
  list.splice(index, 1);
  if (!list.length) delete window.ToolsGCP._listeners[name];
  return true;
};
window.ToolsGCP.emit = function (name, payload) {
  const list = window.ToolsGCP._listeners[name];
  if (!list || !list.length) return;
  /* 反向遍历：摘除元素时不打乱后续下标 */
  for (let i = list.length - 1; i >= 0; i -= 1) {
    try {
      list[i](payload);
    } catch (error) {
      console.error('[ToolsGCP] listener error', error);
      list.splice(i, 1);            /* 坏掉的监听不留（典型：iframe 已卸载） */
    }
  }
  if (list && !list.length) delete window.ToolsGCP._listeners[name];
};
window.ToolsGCP.t = t;
function onEvent(name, fn) { window.ToolsGCP.on(name, fn); }

/* ===================== 小工具 =====================*/
function debounce(fn, delay) {
  let timer = 0;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}
function firstChar(name) { return (String(name || '?').trim().charAt(0) || '?').toUpperCase(); }
function isHttp(url) { return /^https?:\/\//i.test(String(url || '').trim()); }
function parseDate(value) {                      // resource_query.parse_listed_at
  const text = String(value || '').trim().replace('T', ' ');
  if (!text) return null;
  for (const len of [19, 16, 10]) {
    const stamp = Date.parse(text.slice(0, len).replace(/-/g, '/'));
    if (Number.isFinite(stamp)) return stamp;
  }
  return null;
}
function versionParts(value) {
  return String(value || '').replace(/^v/i, '').split(/[.\-+]/).map((p) => parseInt(p, 10) || 0);
}
function isNewer(candidate, current) {
  const a = versionParts(candidate), b = versionParts(current);
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    if ((a[i] || 0) > (b[i] || 0)) return true;
    if ((a[i] || 0) < (b[i] || 0)) return false;
  }
  return false;
}
function readLocal(key, fallback) {
  try {
    const raw = localStorage.getItem('toolsgcp.' + key);
    return raw == null ? fallback : JSON.parse(raw);
  } catch (error) { return fallback; }
}
function writeLocal(key, value) {
  try { localStorage.setItem('toolsgcp.' + key, JSON.stringify(value)); } catch (error) { /* ignore*/ }
}
function stripMarkdown(text) {
  return String(text || '')
    .replace(/\r\n?/g, '\n').replace(/```[\s\S]*?```/g, '')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '$1 ($2)')
    .replace(/^\s{0,3}#{1,6}\s*/gm, '').replace(/^\s{0,3}>\s?/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '• ').replace(/\*\*|__|`/g, '')
    .replace(/<[^>]+>/g, '').replace(/\n{3,}/g, '\n\n').trim();
}
/* ---------- Markdown 渲染（公告 / 更新说明用） ----------
   渲染器在 webui/js/markdown.js（全局 ToolMarkdown，零依赖自研，先转义再转换）。
   ⚠️ 这里两层兜底是**必需**的：
     1) markdown.js 万一没加载（用户手抖删了文件 / 老资源包缺文件）→ 退回"转义 +
        换行"的纯文本，界面绝不会变成空白，也绝不会把原文当 HTML 插进去；
     2) 渲染器本身抛异常 → 同样退回纯文本。
   调用方拿到的是**已经安全**的 HTML，可以交给 v-html；未经这两层兜底的文本一律
   禁止进 v-html（AGENTS.md 第 5 节 + 本项目一贯的"不用 v-html"口径）。 */
function escapeHtmlText(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function mdEngine() {
  return (typeof ToolMarkdown !== 'undefined' && ToolMarkdown && ToolMarkdown.render)
    ? ToolMarkdown : null;
}
function renderMarkdown(text) {
  const raw = String(text == null ? '' : text);
  if (!raw.trim()) return '';
  const engine = mdEngine();
  if (engine) {
    try {
      const html = engine.render(raw);
      if (html) return html;
    } catch (error) { /* 退回纯文本，见上面注释 */ }
  }
  return escapeHtmlText(raw).replace(/\n/g, '<br>');
}
/* 截断也要"按 Markdown 边界"，否则截在半条 ** 或半个代码围栏上，渲染会串成一片 */
function mdTruncate(text, limit) {
  const raw = String(text == null ? '' : text);
  const max = Number(limit) || 2000;
  const engine = mdEngine();
  if (engine && engine.truncate) {
    try { return engine.truncate(raw, max); } catch (error) { /* 退化到硬截 */ }
  }
  return raw.length > max ? raw.slice(0, max) : raw;
}
function splitList(text) {                        // 拆 , ， 、 ; ；，**不拆 /**
  return String(text || '').split(/[,，、;；]/).map((v) => v.trim()).filter(Boolean);
}
function downloadJson(filename, text) {
  const blob = new Blob([text], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 400);
}

/* ===================== 主应用 ===================== */
const App = {
  setup() {
    /* ---------- 基础 ----------
       ⚠️ 本轮按用户需求删除了 .boot-screen 那层启动遮罩 UI（index.html / overlays.css /
          animations.css 里的启动画面整段移除）。但 **booting 状态机本身必须保留**：
          continueBoot / 隐私协议弹窗时序（booting.value=false 后才让协议窗可见）/
          启动步骤日志全靠它，撤掉状态会把启动流程弄断。现在它只是个"启动流程是否
          走完"的内部标志，不再渲染任何界面。bootText 同理（仍写 document.title / 日志）。 */
    const booting = ref(true);
    /* ★ 第 28 轮③：启动加载画面的进度（0-100）与"核心步骤"文案。
       ⚠️ 只显示 4 个核心阶段（用户原话："只显示几个核心的，已注册快捷键这类不用显示"）：
         正在启动 → 正在准备界面 → 正在加载资源 → 即将完成。 */
    /* ⚠️⚠️ bootText 必须在这里有定义，别删！
       第 28 轮③加「启动加载画面」时，补丁脚本把这一行**覆盖**掉了
       （原来这里是 `const bootText = ref('正在加载资源库…')`），
       而 setup() 的返回对象里仍然导出着 bootText ⇒ setup 执行到 return
       就抛 `ReferenceError: bootText is not defined` ⇒ Vue 根本没挂载成功
       ⇒ 窗口一片空白，后端也等不到「首屏就绪」上报（用户报的就是这个：
       日志里会出现「首屏在 20000 ms 内未上报就绪，已按超时继续显示窗口」）。
       ⚠️ 教训：给 app.js 打补丁时锚点行必须**新增**而不是替换；改完必须跑
       「setup 返回对象里的每个名字是否都有定义」的静态审计（见 round28 脚本）。 */
    const bootText = ref('正在启动…');
    /* ---------- 云端资源库加载遮罩 ----------
       ⚠️⚠️ 本轮修复用户报的「加载资源的那个 ui 不见了」。
       markup、组件注册、三处 <resource-loading /> 全都还在（不是被删了），
       真因是**显示时长**：日志证明缓存命中时资源 100ms 内就绪 ——
         [22:27:44.500] 已载入 52 条资源
         [22:27:44.510] 主窗口已显示
       遮罩亮起来和撤掉发生在**同一个 10ms 里**，窗口刚出来它就没了，
       用户自然"从来没看见过"。
       → 按用户确认的口径：**超过 ~400ms 才显示**（加载真慢时才提示，
         快的时候不闪）。所以这里不再直接写 resourceLoading，
         一律走 showResourceLoadingSoon() / hideResourceLoading() 这一对。
       ⚠️ 声明顺序：`resourceLoading` 这些 const 必须在下面那几个函数**之前**，
          否则会踩暂时性死区（TDZ）—— setup 一跑就 ReferenceError，整个界面白屏。 */
    const RESOURCE_LOADING_DELAY_MS = 400;
    const resourceLoading = ref(false);
    const resourceLoadFailed = ref(false);
    let resourceLoadingTimer = 0;
    /** 加载提示是否已经"挂上"（含还没到显示阈值的待命状态） */
    function resourceLoadingActive() {
      return !!resourceLoadingTimer || resourceLoading.value;
    }
    function showResourceLoadingSoon() {
      if (resourceLoadingActive()) return;         // 已经排上了/已经亮着：不重复计闹钟
      resourceLoadingTimer = setTimeout(() => {
        resourceLoadingTimer = 0;
        resourceLoading.value = true;
        resourceLoadFailed.value = false;
        startLoadingDots();                        /* 到点才启动动态点，省一次空转 */
      }, RESOURCE_LOADING_DELAY_MS);
    }
    function hideResourceLoading() {
      if (resourceLoadingTimer) { clearTimeout(resourceLoadingTimer); resourceLoadingTimer = 0; }
      resourceLoading.value = false;
      stopLoadingDots();
    }
    /** 立刻显示（不等 400ms）—— 用于**用户主动点「重试」**这种明确动作：
       提示框本来就摆在屏幕上，再让它先消失 400ms 才回来，等于自己闪一下。 */
    function showResourceLoadingNow() {
      if (resourceLoadingTimer) { clearTimeout(resourceLoadingTimer); resourceLoadingTimer = 0; }
      resourceLoading.value = true;
      startLoadingDots();
    }
    const loadingDots = ref('');
    let loadingDotsTimer = 0;
    /* 动态点：". " → ".. " → "... " → ". " 循环往复（用户明确要这个效果） */
    function startLoadingDots() {
      if (loadingDotsTimer) return;
      let step = 0;
      loadingDotsTimer = setInterval(() => {
        step = (step + 1) % 4;
        loadingDots.value = '.'.repeat(step) + ' ';
      }, 380);
    }
    function stopLoadingDots() {
      if (loadingDotsTimer) { clearInterval(loadingDotsTimer); loadingDotsTimer = 0; }
      loadingDots.value = '';
    }
    /* 长时间加载不出来 → 提示去换镜像源（停留 6 秒） */
    function hintSwitchMirror() {
      toast(t('resource_mirror_hint',
        '云端资源库加载不出来？可到「设置 → 下载 → 搜索源」换一个镜像源后重试。'),
        'warning', '', { duration: 6000 });
    }
    /* 重试：强制重新拉一次云端资源库 */
    async function retryResourceLoad() {
      resourceLoadFailed.value = false;
      /* 用户主动点的重试 → 立刻显示，不走 400ms 延迟（见 showResourceLoadingNow 注释）。
         动态点也由它内部启动，这里不要再 startLoadingDots() 一次。 */
      showResourceLoadingNow();
      const result = await bridge.tryCall('resources.cloud_retry');
      if (result && result.ok) {
        await loadResources();
        await runQuery();
        hideResourceLoading();
        return;
      }
      resourceLoadFailed.value = true;
      hintSwitchMirror();
    }
    /* 放弃云端、退回本地资源库（别把用户卡在遮罩里） */
    async function useLocalResources() {
      hideResourceLoading();
      await saveSetting('resource_source', 'local');
      await loadResources();
      await runQuery();
      toast(t('resource_use_local_done', '已切换到本地资源库'), 'info');
    }
    const win = reactive({ maximized: false, fullscreen: false, minimized: false });
    const info = reactive({ app: 'ToolsGCP', version: '', channel: 'beta', python: '',
                            dataDir: '', configDir: '', resourceFile: '', language: '简体中文', args: [],
                            // frameless：自绘标题栏模式开关（app.info 回填；默认 true = 老行为）
                            frameless: true });
    const settings = reactive({ ...DEFAULT_SETTINGS });
    settingsState.value = settings;

    const toasts = ref([]);
    let toastSeed = 0;
    /* ⚠️ 提示框的**标题**（成功/错误/提示/信息）原来写死中文
       → 切到英文/繁体界面时，"提示成功"这类提示的标题还是中文（切换成英文或繁体中文发现提示提示错误或者成功等都还是简体中文）。
       → 改成 computed：跟着当前语言走（t() 读的是非响应式的 I18N.map，
          所以要用 I18N.version 做依赖才能在切语言时重算）。 */
    const TOAST_TITLE_KEYS = {
      success: 'tip_success', error: 'tip_error', warning: 'tip_warning', info: 'tip_info',
    };
    const TOAST_TITLE_FALLBACK = {
      success: '成功', error: '错误', warning: '提示', info: '信息',
    };
    const toastTitleMap = computed(() => {
      void I18N.version;                       // 切语言时重算
      const out = {};
      Object.keys(TOAST_TITLE_KEYS).forEach((type) => {
        const key = TOAST_TITLE_KEYS[type];
        const fallback = TOAST_TITLE_FALLBACK[type];
        out[type] = t(key, fallback);
      });
      return out;
    });
    /* options: { copy: '可复制文本', duration: 毫秒 } —— 需求：测 Ping 的**结果**提示
       要在关闭按钮左边多一个复制按钮，并且停留时间延长到 3 秒；
       「正在测试 Ping…」这种过程提示不带复制按钮、用默认时长。 */
    function toast(message, type = 'info', title = '', options = {}) {
      /* 需求：「启用提示」关掉之后，任何提示都不再弹（连排队中的也不弹） */
      if (settingsState.value && settingsState.value.notify_enabled === false) return;
      if (message && typeof message === 'object') {
        type = message.type || type; title = message.title || title; message = message.message || '';
      }
      if (!message) return;
      const id = ++toastSeed;
      const copy = options && options.copy != null ? String(options.copy) : '';
      const duration = options && options.duration
        ? Number(options.duration) : (type === 'info' ? 1500 : 2000);
      /* pre=true → 保留换行（多行提示用；CSS 里由内联 white-space:pre-line 生效） */
      const pre = !!(options && options.pre);
      toasts.value.push({ id, message: String(message), type,
        title: title || toastTitleMap.value[type] || '', copy, pre });
      /* 原版 InfoBar 时长：info 1500ms，其它 2000ms；带复制按钮的按调用方指定 */
      setTimeout(() => { toasts.value = toasts.value.filter((x) => x.id !== id); }, duration);
    }
    function dismiss(id) { toasts.value = toasts.value.filter((x) => x.id !== id); }
    /* ---------- 本轮：提示(toast)里的 `请填写<API Key>` 要蓝色下划线可点 ----------
       用户原话：「当未填写API Key时或者填写有误会固定回复 其中包括"请填写<API Key>"
       这个是下滑线字体 点击跳转页面到设置中的GCP-AI 位置（现在的那个是不可点击状态
       无下划线 不是蓝色字体的普通字体是不对的 还有"<>"不是变量而是就是可点击文本的一部分）」。
       ⚠️⚠️ 真根因（和 AI 气泡那次是**两个不同的 bug**）：语言包 `ai_no_key_reply`
          三语都写着 `还没配置 <a href="toolsgcp://api_key">API Key</a>，填好就能聊。`
          —— 带 HTML 标签，而 toast 模板是 `{{ toast.message }}` **纯文本插值**，
          于是用户看到的就是字面的 "<a href=...>API Key</a>"：没下划线、不是蓝字、
          当然也点不动。他说的"<>"不是变量，指的正是这对**被当成占位符写进文案**的标签。
       修法：① 语言包删掉 HTML（见 languages 下的 set_language.json + en_fallback.py）；
             ② 这里把消息切成片段，命中字面量的渲染成可点 span（仍不用 v-html）；
             ③ toast 只显示、不接 click → 点链接时弹一个两项小菜单（去填写 / 知道了）。 */
    const toastLink = reactive({ open: false, x: 0, y: 0, target: '' });
    function toastParts(toastItem) {
      const text = String((toastItem && toastItem.message) || '');
      if (!text) return [];
      /* 复用气泡那套切分（AI_SETTINGS_TOKENS 认 设置<API Key> / 请填写<API Key> / 填写<API Key>），
         但**关掉 mention/编号/URL**：提示里出现 TG-xxxx 不该变成跳详情的链接；
         提示里的 http(s)（比如后端错误原文带的接口地址）也不该点亮 ——
         toast 的链接弹层只有「前往设置」一个动作，点 URL 会跳错地方（URL 可点只归气泡）。 */
      const parts = aiSplitLinks(text, { mention: false, codes: false, urls: false });
      return parts.map((p) => (p.t != null
        ? { text: p.t }
        : { text: p.text, link: p.link, code: p.code }));
    }
    function onToastLinkClick(event, part) {
      const vw = window.innerWidth; const vh = window.innerHeight;
      toastLink.target = part.text;
      toastLink.x = Math.max(8, Math.min(event.clientX || 0, vw - 190));
      toastLink.y = Math.max(8, Math.min((event.clientY || 0) + 6, vh - 84));
      toastLink.open = true;
    }
    function toastLinkGo() {
      toastLink.open = false;
      gotoSettingsAi();
    }
    function toastLinkClose() { toastLink.open = false; }

    /* 后端接口缺失时的统一说明（不静默、不假装成功） */
    function needApi(path, extra) {
      /* 本轮多语言：以前整句硬编码中文，英文界面下每个降级提示都是中文 */
      toast(t('need_api_missing', '{what}需要桌面端接口 <{path}>（后端尚未提供）')
        .replace('{what}', extra || t('need_api_default', '该功能'))
        .replace('{path}', path), 'warning');
      return false;
    }

    /* ---------- 对话框（确认 / 输入 / 公告 / 更新 / 密钥列表 共用外壳） ---------- */
    const dialog = reactive({
      open: false, title: '', body: '', extra: '', notes: '', rows: null,
      /* ⚠️ notesMd / bodyMd：显式开关，**默认 false**。
         true 时 notes / body 走 Markdown 渲染（内部已先转义，产物安全）；
         false 时维持原来的插值纯文本 —— openDialog 的其它调用点（确认框、密钥
         列表、存储重启提示…）行为一字不变，不会因为这次改动被"转 HTML"弄坏文案。
         目前只有两处显式开启：新公告弹窗（maybePopup）与发现新版本弹窗（checkUpdate）。 */
      notesMd: false, bodyMd: false,
      input: false, inputValue: '', inputPlaceholder: '',
      /* 通用对话框支持一个下拉框（收藏夹选择用）。inputWhen = 选中哪个值时
         才显示下面的输入框（选新建收藏夹才出现名称输入）。 */
      select: null, selectValue: '', inputWhen: '',
      /* 勾选组（收藏夹导出用）。每项 {value,label,checked}；
         确认时 answer() 回传已勾选 value 数组，取消回传 null。 */
      checks: null,
      /* ── 下面三个是「可选片段」，只有 openDialog 显式传了才渲染（其余对话框一律 null，
             行为和外观都不变）。版式照旧 PyQt 版 update_dialog / announcement_dialog 搬：
         head  = 抬头（{text 大字, sub 小字说明, badge 徽章文案, badgeKind 'stable'|'prerelease'|'unread'}）
         link  = 右上角纯图标跳转（{url, tip 悬浮提示}）—— 需求「只有一个图标、不需要文本信息在按钮中，
                 鼠标悬浮按钮会有相关提示」
         item  = 带边框的条目块（{title 标题, body 纯文本正文, bodyHtml Markdown 正文, meta 底部说明}）
                 标题单独再套一层框：需求「公告中的标题部分要用框框框起来不然用户会以为这个时正文内容」 */
      head: null, link: null, item: null, titleBadge: '',
      buttons: ['取消', '确定'], danger: false, cancelable: true, wide: false,
      /* 点遮罩空白处是否算「取消」。默认 true（原有行为）；
         新公告弹窗在 maybePopup 里传 false —— 用户会不小心点空白把公告弹窗关掉。 */
      backdropClose: true,
      cancelText: '取消', resolve: null,
    });
    function openDialog(options = {}) {
      return new Promise((resolve) => {
        dialog.title = options.title || '';
        dialog.body = options.body || '';
        dialog.extra = options.extra || '';
        dialog.notes = options.notes || '';
        dialog.rows = options.rows || null;
        dialog.select = Array.isArray(options.select) ? options.select : null;
        dialog.selectValue = (options.selectValue != null) ? options.selectValue
          : (dialog.select && dialog.select.length ? dialog.select[0].value : '');
        dialog.inputWhen = options.inputWhen || '';
        dialog.input = !!options.input
          || (!!dialog.inputWhen && String(dialog.selectValue) === String(dialog.inputWhen));
        dialog.inputValue = options.value || '';
        dialog.inputPlaceholder = options.placeholder || '';
        /* 勾选组。复制一份再挂进 dialog（调用方传进来的数组可能还会被复用） */
        dialog.checks = Array.isArray(options.checks)
          ? options.checks.map((c) => ({ value: String(c.value),
              label: String(c.label == null ? c.value : c.label), checked: !!c.checked }))
          : null;
        dialog.cancelText = options.cancelText || t('cancel', '取消');
        /* 三个可选片段：每次都重新赋值（不传就置 null），否则上一个弹窗的抬头/图标
           会残留到下一个弹窗上 —— dialog 是常驻 reactive，不是每次新建。 */
        dialog.head = options.head || null;
        dialog.link = options.link || null;
        dialog.item = options.item || null;
        /* 标题旁的小徽章（新公告弹窗的「N 条未读」）：每次重新赋值，防残留 */
        dialog.titleBadge = options.titleBadge || '';
        dialog.buttons = options.buttons
          || (options.cancelable === false
            ? [options.confirmText || t('confirm', '确定')]
            : [options.cancelText || t('cancel', '取消'),
               options.confirmText || t('confirm', '确定')]);
        dialog.danger = !!options.danger;
        dialog.wide = !!options.wide;
        dialog.notesMd = !!options.notesMd;
        dialog.bodyMd = !!options.bodyMd;
        dialog.cancelable = options.cancelable !== false;
        /* 只有显式传 backdropClose:false 才禁止点空白关闭；其余对话框维持旧行为 */
        dialog.backdropClose = options.backdropClose !== false;
        dialog.resolve = resolve;
        dialog.open = true;
        /* 收藏页点击重命名或 新建收藏夹弹出窗口默认是输入状态——
           弹窗一打开，**光标就已经在输入框里**，用户可以直接打字，不用再点一下。
           ⚠️ 用 nextTick：dialog.open 刚置 true 时 DOM 还没渲染出来。
           ⚠️ 顺带把光标放到**末尾**（重命名时是"在原名后面接着改"更顺手）。
           ⚠️ index.html 顶部那段"不要自动聚焦第一个按钮"的脚本不会抢走焦点 ——
              它的 isField() 对 <input> 直接 return true 放行。 */
        if (dialog.input) {
          nextTick(() => {
            const el = document.querySelector('.modal input.input');
            if (!el || !el.focus) return;
            el.focus();
            try {
              const len = (el.value || '').length;
              el.setSelectionRange(len, len);
            } catch (error) { /* 某些输入类型不支持 setSelectionRange，忽略 */ }
          });
        }
      });
    }
    /* 对话框勾选组的"全选"是**三态**（none / some 半选 / all）。
       条件 = 至少勾了一个、但没全勾 → 半选（显示"-"）。
       和搜索页选择条、收藏页批量移动选择条的口径一致。 */
    const dialogChecksSome = computed(() => {
      const list = dialog.checks || [];
      if (!list.length) return false;
      const some = list.some((c) => c.checked);
      const all = list.every((c) => c.checked);
      return some && !all;
    });
    /* 弹窗正文 / 更新说明的 Markdown 产物（index.html 里 v-if="dialog.notesMd" 才用）。
       关掉开关时这两个 computed 直接返回空串，模板继续走原来的 {{ dialog.notes }} 插值。 */
    const dialogNotesHtml = computed(() =>
      (dialog.notesMd && dialog.notes) ? renderMarkdown(dialog.notes) : '');
    const dialogBodyHtml = computed(() =>
      (dialog.bodyMd && dialog.body) ? renderMarkdown(dialog.body) : '');
    /* 公告正文（列表页 + 弹窗）：⚠️ 取值口径 `body_md || body`。
       后端新增的 body_md 是**未经擦除的原始 markdown**（已按行边界夹到 6000 字），
       body 是 markdown_to_text() 擦出来的纯文本 —— 老后端 / 老缓存没有 body_md，
       那时就用 body，渲染器对纯文本也是原样输出（转义 + 换行），不会显示成源码。 */
    function noticeSource(notice) {
      const n = notice || {};
      return String(n.body_md || n.body || '');
    }
    function noticeBodyHtml(notice) { return renderMarkdown(noticeSource(notice)); }

    /* ---------- 公告正文右键菜单（复制链接 / 复制 / 全选） ----------
       用户原话：「公告界面或公告弹窗新增可点击链接（蓝色带下划线字体，适配左键单击和
       ctrl+左键），右键连接部分自动框选此处连接部分 并且右键菜单为复制链接（适配三语言）；
       公告界面和公告弹窗支持右键菜单里面有复制和全选。」
       ⚠️ 链接的"可点"本来就成立：markdown.js 产出 <a class="md-link" data-mdlink>（故意不带
       href，避免 WebView2 自己开新窗口），app.js 的 onMarkdownLinkClick 在**捕获阶段**接住
       click/auxclick → openLink(url, event)，第三参 ctrl = 用后台浏览器标签打开。
       这里只补右键这一半：
         · 右键落在链接上 → 先用 Range 把这条链接整段框选（用户要的"自动框选此处连接部分"），
           菜单首项变成「复制链接」；
         · 右键落在正文其它位置 → 保留用户已有选区，菜单是「复制 / 全选」。
       菜单本体在 index.html（.card-menu.notice-menu），与气泡右键菜单同一套外观。 */
    const noticeCtx = ref(null);      // { x, y, link, hasSel }
    /* ⚠️ 正文容器是 DOM 元素，**不能**塞进响应式对象：被 Proxy 包一层后 Selection/Range
       仍能用，但身份比较和"当前作用域"会变得难以推理。用普通变量存。 */
    let _noticeCtxScope = null;
    function closeNoticeCtx() { noticeCtx.value = null; }
    function _noticeSelectNode(node) {
      try {
        const sel = window.getSelection && window.getSelection();
        if (!sel || !node) return;
        const range = document.createRange();
        range.selectNodeContents(node);
        sel.removeAllRanges();
        sel.addRange(range);
      } catch (e) { /* 选区 API 不可用：不框选，菜单照开 */ }
    }
    function onNoticeContext(event) {
      const scope = event.currentTarget || null;
      _noticeCtxScope = scope;
      const linkEl = (event.target && event.target.closest)
        ? event.target.closest('a[data-mdlink]') : null;
      const link = linkEl ? String(linkEl.getAttribute('data-mdlink') || '').trim() : '';
      /* 右键链接 = 立刻把这条链接框选出来（用户能看到"我复制的是哪一段"） */
      if (linkEl) _noticeSelectNode(linkEl);
      const vw = window.innerWidth; const vh = window.innerHeight;
      noticeCtx.value = {
        /* 菜单宽约 176、三项高约 110：夹进视口，别被右缘/下缘裁掉 */
        x: Math.max(8, Math.min(event.clientX || 0, vw - 190)),
        y: Math.max(8, Math.min(event.clientY || 0, vh - 116)),
        link: link,
        hasSel: !!link || aiHasSelection(),
        /* ⚠️ 选区**快照**：菜单项是 <button>，点它的时候浏览器可能先把文档选区收掉，
           那时再去读 window.getSelection() 就只剩空串，「复制选中内容」会变成复制全文。
           所以在这里就把文本抄下来，点击时优先用快照。 */
        selText: link
          ? String((linkEl && linkEl.textContent) || link)
          : (aiHasSelection()
            ? String((window.getSelection && window.getSelection().toString()) || '') : ''),
      };
    }
    function noticeCtxCopyLink() {
      const menu = noticeCtx.value;
      closeNoticeCtx();
      if (!menu || !menu.link) return;
      copyText(menu.link);
    }
    function noticeCtxCopy() {
      /* 有框选 → 复制框选；没有 → 复制整段正文（和"右键空白也想拷全文"的直觉一致）。
         ⚠️ 优先用打开菜单时的快照（见 onNoticeContext 的 selText 注释）：点菜单会收掉选区。 */
      const menu = noticeCtx.value;
      const live = aiHasSelection()
        ? String((window.getSelection && window.getSelection().toString()) || '') : '';
      const snap = String((menu && menu.selText) || '');
      const whole = _noticeCtxScope ? String(_noticeCtxScope.innerText || '') : '';
      closeNoticeCtx();
      const text = live.trim() ? live : (snap.trim() ? snap : whole);
      if (text) copyText(text);
    }
    function noticeCtxSelectAll() {
      const scope = _noticeCtxScope;
      closeNoticeCtx();
      if (scope) _noticeSelectNode(scope);
    }
    /* 右键点到公告正文以外的地方：先把菜单收掉（否则它会悬在别的页面上）。
       ⚠️ 在 window 捕获阶段判断——正文自己的 @contextmenu.prevent 是冒泡阶段，
          这里先关、随后再开，同一帧内不会有闪烁。 */
    window.addEventListener('contextmenu', (event) => {
      if (!noticeCtx.value) return;
      const t = event.target;
      if (t && t.closest && (t.closest('.notice-menu')
        || t.closest('.notice-body') || t.closest('.modal-body') || t.closest('.dlg-item-body'))) return;
      closeNoticeCtx();
    }, true);
    /* 滚动时菜单会与正文脱开：直接收起（和输入框右键菜单同一策略） */
    window.addEventListener('scroll', () => { if (noticeCtx.value) closeNoticeCtx(); }, true);
    /* 对话框里下拉框切换时调用；选中 inputWhen 指定的值时显示输入框 */
    function onDialogSelect(value) {
      dialog.selectValue = value;
      if (!dialog.inputWhen) return;
      const want = String(value) === String(dialog.inputWhen);
      if (want && !dialog.input) dialog.inputValue = '';
      dialog.input = want;
      if (want) {
        nextTick(() => {
          const el = document.querySelector('.modal input.input');
          if (el && el.focus) el.focus();
        });
      }
    }
    function answer(label) {
      dialog.open = false;
      /* Markdown 开关跟着本次对话结束一起清掉：下一次 openDialog 没传就还是纯文本 */
      dialog.notesMd = false;
      dialog.bodyMd = false;

      const resolve = dialog.resolve;
      dialog.resolve = null;
      if (!resolve) return;
      const yes = dialog.buttons[dialog.buttons.length - 1];
      /* 勾选组对话框 —— 确认回传勾选的 value 数组，取消（或点遮罩）回传 null。
         必须先于 input 分支判断（勾选组对话框不显示输入框）。 */
      if (dialog.checks) {
        if (label !== yes) return resolve(null);
        return resolve(dialog.checks.filter((c) => c.checked).map((c) => c.value));
      }
      /* ⚠️ 带 select + inputWhen 的对话框（收藏夹选择）点确认时要返回布尔，
         不能返回输入框文本；旧行为（纯 input 对话框返回字符串）保持不变。 */
      if (dialog.input && !dialog.inputWhen && label === yes) return resolve(dialog.inputValue);
      /* 三键以上（如「放弃 / 留在 / 保存并继续」）回传文字，两键回传布尔 */
      if (dialog.buttons.length > 2) return resolve(label);
      return resolve(label === yes);
    }
    function confirmDialog(title, body, confirmText = '确定', danger = false) {
      return openDialog({ title, body, confirmText, danger });
    }
    /* 勾选组对话框的全选 / 取消全选 */
    function toggleDialogChecks(value) {
      if (!dialog.checks) return;
      dialog.checks.forEach((c) => { c.checked = !!value; });
    }

    /* ---------- 主题 / 配色 / 字体 / 主题效果 / 提示框位置 ---------- */
    /* 插件配置页 iframe 的引用。宿主 → 插件页的主题同步（syncPluginTheme）要用它；
       提前声明在这里（applyAppearance 里就会调用），避免 setup 执行顺序上的 TDZ。 */
    const pluginFrameRef = ref(null);
    /* 宿主 → 插件配置页的主题同步协议
       为什么要有：配置页是 iframe（/res/plugins/<id>/config.html），它只在**加载那一刻**
       读一次 parent.document 的 data-theme。用户在主程序里切主题 / 主题效果 / 强调色 / 语言时，
       已经打开的配置页收不到通知（settings.set 走 notify=false，不广播 settings-changed），
       于是"深色主题下配置页还是白底、看不清"。
       现在改成：宿主在 iframe load、以及 applyAppearance()/changeLanguage() 触发时 postMessage
       一条 {type:'toolsgcp-theme', theme, fx, accent, language}；插件页监听消息后立刻改自己的
       <html data-theme/data-fx/data-accent>，原来"读父文档"的逻辑保留作为首帧兜底。 */
    function pluginThemePayload() {
      return {
        type: 'toolsgcp-theme',
        theme: isDark.value ? 'dark' : 'light',
        fx: settings.theme_effect || 'mica',
        accent: settings.accent_color || 'blue',
        /* 语言用后端解析后的实际语言（settings.language 可能是「跟随系统」） */
        language: I18N.language || settings.language || '',
      };
    }
    function syncPluginTheme(reason) {
      const frame = pluginFrameRef.value;
      if (!frame || !frame.contentWindow) return false;
      try {
        frame.contentWindow.postMessage(pluginThemePayload(), '*');
        return true;
      } catch (error) {
        /* iframe 还没就绪 / 被销毁：下一拍 load 或下次主题变化会再推一次，不算错误 */
        return false;
      }
    }
    const systemDark = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
    const systemTick = ref(0);
    /* ⚠️⚠️ 本轮修复「启动后深色背景又迅速切回浅色主题」（用户原话）。
       真根因不在首帧脚本 —— 日志证明后端注入的 `<meta id="tg-boot-theme">`、
       splash 底色、frame 的 Form.BackColor 三处**都已经是浅色**：
           [启动|splash] 启动画面底色: 浅色 … theme='浅色主题'
           [外壳|frame] 窗口底色已按主题刷新: 主题=light 页面底色=#F3F4F7
       深色是 **Vue 挂载那一刻**画出来的：
         ① `onMounted` 第一件事就调 `applyAppearance()`（见本文件末尾附近）；
         ② 那时 `boot()` 里的 `await loadSettings()` **还没回来**，
            `settings.theme` 仍是前端兜底值 `'跟随系统'`；
         ③ `isDark` 于是退回 `matchMedia('prefers-color-scheme: dark')`
            —— 本机 Windows 应用模式是深色（AppsUseLightTheme=0）⇒ 判成深色；
         ④ 它把 `data-theme` 改回 dark、底色刷成 #1C1C1C，
            还顺手 `bridge.call('window.set_theme', true)` 让原生层一起变黑；
         ⑤ 设置拉回来后再跑一次 `applyAppearance()` → 变回浅色。
       ⇒ 用户看到的"窗口出现一瞬间是深色、随即跳回浅色"就是 ④→⑤ 这一对来回。

       修法：**在真实设置到达之前，不要擅自改主题**。
       `firstFrameDark` 用首帧脚本同样的口径（后端注入的 meta，其次 localStorage）
       拿到"页面已经画出来的那个深浅"，设置未就绪时 isDark 直接沿用它 ——
       于是 ① 那次 applyAppearance 与首帧**完全幂等**（setAttribute 同值、
       底色同值、set_theme 同值），既不会变黑也不会多一次原生层刷新。
       设置回来后 isDark 改由 settings.theme 决定，行为和以前一样。 */
    const settingsLoaded = ref(false);
    const firstFrameDark = (() => {
      try {
        const meta = document.getElementById('tg-boot-theme');
        const attr = meta && meta.getAttribute('data-dark');
        if (attr === '0' || attr === '1') return attr === '1';
        const saved = window.localStorage && window.localStorage.getItem('toolsgcp.theme');
        if (saved === 'dark' || saved === 'light') return saved === 'dark';
      } catch (e) { /* 拿不到就退回"按系统判定"（= 以前的行为） */ }
      return null;
    })();
    const isDark = computed(() => {
      void systemTick.value;
      /* 冻结只在"设置还没到手 **且** 主题仍是前端兜底值"时生效。
         第二个条件是**故意**加的：浏览器模式（serve.py 的 mock 后端没有 settings.get）
         下 settingsLoaded 会永远是 false，如果只看它，用户后来在设置里改成
         深色/浅色就完全没反应了 —— 那是拿一个 bug 换另一个 bug。
         而 `settings.theme !== DEFAULT_SETTINGS.theme` 覆盖了**所有**真实变更入口
         （设置下拉框、AI 的 set_theme 工具、另一端广播 settings-changed），
         不需要额外记账。用户选的正好是"跟随系统"（= 默认值）时仍然冻结，
         但那种情况下 isDark 走的就是系统色，和首帧一致，看不出差别。 */
      if (!settingsLoaded.value && settings.theme === DEFAULT_SETTINGS.theme
        && firstFrameDark !== null) return firstFrameDark;
      if (settings.theme === '深色主题') return true;
      if (settings.theme === '浅色主题') return false;
      return systemDark ? systemDark.matches : true;
    });
    /* 提示框位置：设置里可选 顶端居中 / 右上 / 右下 / 左上 / 左下
       ⚠️ 默认值改成**顶端**（原来是右上角）；
          顶端改名成顶端居中（它本来就是横向居中的）；
          下拉框里顶端居中排在**右上角上面**（即列表第一项）。 */
    const TOAST_POS_CLASS = {
      top: 'is-top', top_right: 'is-tr', bottom_right: 'is-br',
      top_left: 'is-tl', bottom_left: 'is-bl',
    };
    /* ⚠️ 本轮需求（用户原话）：「左上角和左下角的提示位置应该再往左一点在左侧栏的右侧就行，
       如果点击左侧栏展开他还会跟随往右走 点击收起或者自动收起时也跟随回到原位。」
       → 除了贴收起态侧栏右边（CSS），还要把**展开态**告诉 CSS：navOpen 在栈上挂
         is-nav-open，宽度从 --nav-collapsed 过渡到 --nav-expanded（和侧栏自己
         220ms 的过渡同步），提示条就会跟着滑，而不是跳。 */
    const toastClass = computed(() =>
      (TOAST_POS_CLASS[settings.toast_position] || 'is-top')
      + (navOpen.value ? ' is-nav-open' : ''));
    function applyAppearance() {
      const dark = isDark.value;
      const root = document.documentElement;
      root.setAttribute('data-theme', dark ? 'dark' : 'light');
      root.setAttribute('data-accent', settings.accent_color || 'blue');
      /* 主题效果：云母（默认）/ 毛玻璃 / 亚克力 —— 只改模糊、底噪与高光描边 */
      root.setAttribute('data-fx', settings.theme_effect || 'mica');
      /* 动画强度 → <html data-motion>。CSS 用 [data-motion="reduced|off"] 统一降级/关闭；
         启动动画在 off 下由 animations.css 单独恢复，左侧指示标由 syncNavIndicator 瞬时跳转。 */
      root.setAttribute('data-motion', settings.ui_animation || 'on');
      root.style.background = dark ? '#1C1C1C' : '#F3F4F7';
      /* 宿主自身也声明 color-scheme —— 否则深色主题 + 浅色 Windows 时，
         主程序的原生滚动条/输入控件仍按浅色渲染（插件配置页已在 iframe 内部自己声明）。
         ⚠️ 不要只靠 index.html 的 <meta name="color-scheme" content="dark light">：
            它只表示"两种都支持"，实际选择仍跟系统。 */
      root.style.colorScheme = dark ? 'dark' : 'light';
      try {
        localStorage.setItem('toolsgcp.theme', dark ? 'dark' : 'light');
        localStorage.setItem('toolsgcp.accent', settings.accent_color || 'blue');
      } catch (error) { /* ignore */ }
      const font = settings.ui_font_family || '微软雅黑';
      root.style.setProperty('--ui-font', '"' + String(font).replace(/"/g, '') +
        '", "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", system-ui, sans-serif');
      if (bridge.ready) bridge.call('window.set_theme', dark).catch(() => {});
      /* 主题/效果/强调色一变就推给已打开的插件配置页（iframe 还没开时这里安全空转，
         等它 load 时会由 index.html 的 @load="syncPluginTheme('load')" 补一次）。 */
      syncPluginTheme('appearance');
    }
    if (systemDark && systemDark.addEventListener) {
      systemDark.addEventListener('change', () => {
        systemTick.value += 1;
        if (settings.theme === '跟随系统') applyAppearance();
      });
    }

    /* ---------- 导航 ---------- */
    const page = ref('search');
    const detail = ref(null);
    let detailSequence = 0;
    /* 详情页**记住是从哪个页面进来的**。
       搜索页 定制页和收藏页当打开一个卡片ui时切换其他页面再切换回来应该还是原本的页面里。
       ⚠️ 之前的行为：`doGoto()` 无条件 `detail.value = null` —— 从搜索页进了详情，
          切到收藏页再切回搜索页，详情就**没了**（回到列表页）。
       ⚠️ 现在的做法：
          · 记住 detailPage = 打开详情时所在的页面；
          · 切走时**保留** detail（不销毁），但把当前 page 记下来；
          · 切回 detailPage 时把 detail 重新挂上（详情还在原处）；
          · 切到**别的**页面时，详情仍然保留（下次切回 detailPage 还能看到）。
       ⚠️ 为什么不用每页各存一个 detail：详情页是全局唯一的（`detail` 是单个 ref），
          同时只可能有一个详情。多份会让"返回按钮该关哪一个"变复杂。 */
    const detailPage = ref('');
    /* 用户主动点「返回」时才真正关掉详情（并记下它来自哪个页面）。 */
    function rememberDetailPage() {
      if (detail.value && !detailPage.value) detailPage.value = page.value;
    }
    const navPinned = ref(false);
    const navHover = ref(false);
    const moreOpen = ref(false);
    const navOpen = computed(() => navPinned.value || navHover.value);

    /* 说明：上一轮这里曾实现过「隐藏左侧栏元素」（8 个子开关 + F9 临时恢复）。
       用户后来明确要求**删掉这个设置项、相关代码一并删除**，所以整套机制
       （navRevealAll / navHiddenKeys / navVisible / navHideOn / F9 分支）已移除，
       配置里的 nav_hide_* 键也一并删掉。若以后要重做，请重新评估需求再实现。*/

    const navTop = computed(() => {
      /* 首页（海报轮播页）已按需求整体移除，所以顶部导航从「搜索」开始。 */
      const items = [
        { key: 'search', label: t('search', '搜索'), icon: 'search' },
        { key: 'customize', label: t('customize', '定制页'), icon: 'palette' },
        { key: 'favorites', label: t('tools_gcp', '收藏'), icon: 'star' },
        { key: 'workshop', label: t('gcp_workshop', 'GCP工坊'), icon: 'developer' },
      ];
      if (settings.ai_enabled && settings.ai_sidebar_mode) {
        items.push({ key: 'ai', label: t('ai_page', 'AI'), icon: 'robot' });
      }
      return items;
    });
    const navBottom = computed(() => ([
      { key: 'notice', label: t('notice', '公告'), icon: 'megaphone' },
      { key: 'github', label: t('github', 'Github'), icon: 'github' },
      { key: 'more', label: t('more', '更多'), icon: 'more' },
      { key: 'settings', label: t('settings', '设置'), icon: 'setting' },
    ]));
    const moreItems = computed(() => ([
      { key: 'feedback', label: t('feedback', '反馈'), icon: 'feedback' },
      { key: 'log', label: t('log', '查看日志'), icon: 'document' },
      { key: 'deploy', label: t('deploy', '应用部署'), icon: 'library' },
      { key: 'plugins', label: t('plugins', '插件'), icon: 'puzzle' },
      /* 下载页放在插件和提交软件之间。的右下角悬浮球已删掉。 */
      { key: 'download', label: t('download', '下载'), icon: 'download' },
      { key: 'maker', label: t('submit_software', '提交软件'), icon: 'up' },
    ]));
    const MORE_KEYS = ['feedback', 'log', 'deploy', 'plugins', 'download', 'maker'];

    /* ---------- 侧栏「鼠标靠近自动展开」 ----------
       需求：这个功能**默认关闭**，在「设置 → 功能」里给开关。
       关掉时只有点汉堡按钮才展开（navPinned），鼠标划过不再触发。 */
    const hoverExpand = computed(() => !!settings.nav_hover_expand);
    function onNavEnter() {
      if (!hoverExpand.value) return;                 // 设置里关掉了 → 不响应悬停
      navHover.value = true;
    }
    function onNavLeave() {
      if (!navPinned.value) navHover.value = false;
    }

    function isActive(key) {
      if (key === 'more') return MORE_KEYS.indexOf(page.value) >= 0;
      return page.value === key;
    }

    /* ---------- 侧栏动态选中标（原版那种"滑来滑去"的选中块） ----------
       需求原话：「切换左侧栏不同界面这个左侧栏的反馈特别足，有动态选中标来回滑动，
                 物理加速也特别真实：起步慢、中间快、结束慢，而且不同长度加速速度不一样」。
       实现：整条侧栏只有**一个** .nav-indicator 元素（index.html 里 nav 的第一个子节点），
            JS 用 requestAnimationFrame 驱动它的 translateY + height：
              · 缓动 = easeInOutCubic（慢 → 快 → 慢）；
              · 时长按**移动距离**算（跨得越远越久），这就是"不同长度速度不同"的来源；
              · 高度变化（不同分类之间切换）同样按缓动走。
       侧栏展开/收起会改变条目宽度，但 top/height 不受影响，所以宽度交给 CSS。 */
    /* ---------- 侧栏"蓝色小标"（拉伸 + 弹簧跟上的物理动画） ----------
       需求原文：
         这个框住应该是直接切换到对应页面，而只有那个蓝色小标才是动态变化的；
           蓝色小标虽然动画很好了不过还欠缺，应该是有拉伸效果的 ——
           前身先出去、后身固定不动，然后前身移动好了后身立马像弹簧一样跟上，
           这里也要用到变速曲线；最后这个速度有点慢。
       实现：
         · 选中**背景块**由 CSS 瞬时切换（不动画），见 .nav-item.is-active；
         · 只有一根 3px 宽的蓝色小标在滑，它有两个边：front（运动方向的前沿）/ back（后沿）；
         · front 先用 easeOutCubic 冲出去（0 ~ 0.58×D），back 晚 0.42×D 再用 easeOutBack 弹上来；
           于是中途会前身先探出去、后身留在原地，back 追上时会过冲一点点再回弹 —— 就是弹簧感；
         · 时长按距离算，但整体比此前快约 35%（150~320ms，此前 170~430ms）。 */
    const navIndicator = reactive({ top: 0, height: 0, ready: false });
    let navIndicatorFrame = 0;
    /* 蓝标常态半高：总高 18px（和原版 .nav-pill 一致） */
    const NAV_PILL_HALF = 9;
    /* ⚠️ 用 getBoundingClientRect 相减而不是 offsetTop：侧栏展开/收起、滚动容器变化时更可靠 */
    function navIndicatorTarget() {
      const nav = document.querySelector('nav.nav');
      if (!nav) return null;
      const item = nav.querySelector('.nav-item.is-active');
      if (!item) return null;
      const navRect = nav.getBoundingClientRect();
      const itemRect = item.getBoundingClientRect();
      if (!itemRect.height) return null;
      return { top: itemRect.top - navRect.top + nav.scrollTop, height: itemRect.height };
    }
    function easeOutCubic(t) {
      return 1 - Math.pow(1 - t, 3);
    }
    /* 过冲后回弹：c1 越大冲得越远（1.25 ≈ 5% 过冲，克制但看得见） */
    function easeOutBack(t, c1) {
      const c = c1 == null ? 1.25 : c1;
      const x = t - 1;
      return 1 + (c + 1) * x * x * x + c * x * x;
    }
    function setPillEdges(a, b) {
      const top = Math.min(a, b);
      const height = Math.max(6, Math.abs(b - a));   // 6px 下限：两沿重合时也看得见
      navIndicator.top = top;
      navIndicator.height = height;
    }
    function syncNavIndicator(animate = true) {
      /* 关闭动画 → 左侧蓝色指示标也瞬时跳转。
         它是 requestAnimationFrame 驱动的（CSS 不参与），所以 data-motion 管不到，必须在这里关。 */
      if (settings.ui_animation === 'off') animate = false;
      const target = navIndicatorTarget();
      if (!target) {
        /* ⚠️「隐藏左侧栏元素」引入的新情况：**当前页的入口被藏起来了**
           （比如在设置里勾掉「搜索」，人正停在搜索页）。
           以前这里直接 return 没关系（拿不到目标 = 还没渲染好，蓝标停在上一处也行），
           但现在 return 会让蓝标**留在被移除那条的旧坐标**上 —— 侧栏补位之后那个位置
           已经属于别的页面，看起来就是"选中标指着错的条目"。
           所以量不到活动条目时把蓝标收起来（height 0），页面本身照常显示，不受影响。 */
        navIndicator.ready = false;
        navIndicator.height = 0;
        return;
      }
      const center = target.top + target.height / 2;
      const tTop = center - NAV_PILL_HALF;
      const tBottom = center + NAV_PILL_HALF;

      if (!navIndicator.ready || !animate) {
        setPillEdges(tTop, tBottom);
        navIndicator.ready = true;
        return;
      }
      /* 当前两沿（从渲染值反推：top / top+height） */
      const cTop = navIndicator.top;
      const cBottom = navIndicator.top + navIndicator.height;
      const curCenter = (cTop + cBottom) / 2;
      const distance = Math.abs(center - curCenter);
      if (distance < 0.5) { setPillEdges(tTop, tBottom); return; }

      const down = center > curCenter;
      /* 运动方向的前沿 / 后沿目标值 */
      const frontFrom = down ? cBottom : cTop;
      const frontTo = down ? tBottom : tTop;
      const backFrom = down ? cTop : cBottom;
      const backTo = down ? tTop : tBottom;

      /* 时长：近距离干脆、远距离能看出滑行；比此前整体快 ~35% */
      const duration = Math.max(150, Math.min(320, 150 + distance * 1.1));
      const FRONT_END = 0.58;        // 前沿在 58% 时长内冲到位
      const BACK_START = 0.42;       // 后沿从 42% 开始跟
      const started = performance.now();
      cancelAnimationFrame(navIndicatorFrame);
      const step = (now) => {
        const p = Math.min(1, (now - started) / duration);
        const pf = Math.min(1, p / FRONT_END);
        const pb = p <= BACK_START ? 0 : (p - BACK_START) / (1 - BACK_START);
        const front = frontFrom + (frontTo - frontFrom) * easeOutCubic(pf);
        /* 设置 → 功能里的关闭 Q 弹→ 后沿改用 easeOutCubic，到位即停、不再过冲回弹；
           前沿的 easeOutCubic 与"前身先出去、后身跟上"的拉伸逻辑保持不变。 */
        const backEase = settings.nav_indicator_bounce
          ? easeOutBack(pb, 1.25) : easeOutCubic(pb);
        const back = backFrom + (backTo - backFrom) * backEase;
        setPillEdges(down ? back : front, down ? front : back);
        if (p < 1) navIndicatorFrame = requestAnimationFrame(step);
        else setPillEdges(tTop, tBottom);
      };
      navIndicatorFrame = requestAnimationFrame(step);
    }
    /* 设置里切换关闭 Q 弹后立刻生效（当前已在目标位时只是对齐，不会乱跳） */
    watch(() => settings.nav_indicator_bounce, () => { syncNavIndicator(true); });
    function _onNavResize() { syncNavIndicator(false); }
    function closePops() { moreOpen.value = false; navHover.value = false; navPinned.value = false; }
    function closeSidebar() { if (navOpen.value) { navPinned.value = false; navHover.value = false; moreOpen.value = false; } }
    /* 「更多」浮层的兜底关闭：点内容区 / 标题栏 / 空白 / 其它 UI 都要收起。
       ⚠️ 不能只靠 .pop-backdrop：它的 z-index 低于内容区，点内容区根本收不到事件，
       之前就是"切页、点空白、点其它 UI 都不消失"。这里用捕获阶段的 mousedown 兜底：
       只有点在 .more-pop 内部或左侧栏内部才不处理（侧栏内部的关闭由 goto() 负责）。 */
    /* 「框选后点空白处取消框选」（task-12 需求 6）。
       ⚠️ 口径**严格限定在详情区自己的选区**：只有当现有选区的锚点落在 .detail-wrap 里、
       且这次左键按在详情区之外（或区内不可选部位）时才清。
       理由：Chromium 对 user-select:none 区域本来就会在 mousedown 收起选区，
       真正需要钉死的是"详情区选完、点同页不可选部位"这种内核行为不一致的情形。
       不这么限定的话，日志页 / 公告页拖选的锚点会被我们抢先把 removeAllRanges 清掉，
       等于用新 bug 换老需求。编辑控件（input/textarea/contenteditable）永远不碰。 */
    const SEL_KEEP_SELECTORS = [
      'input', 'textarea', 'select', '[contenteditable]', '.card-menu',
    ].join(', ');
    /* 详情区内部**允许框选**的那些元素：点在它们身上（含边缘空白）不算"点空白"，
       那是用户在继续调整选区。与 components.css 的 .detail-wrap 白名单同步。 */
    const SEL_TEXT_KEEP = [
      '.detail-desc', '.detail-name', '.detail-code', '.para',
      '.detail-key', '.detail-val', '.detail-link',
    ].join(', ');
    function onDocMoreDown(event) {
      /* 卡片右键菜单：点到菜单外面任何地方都收起 */
      if (cardMenu.value && !(event.target && event.target.closest
        && event.target.closest('.card-menu'))) cardMenu.value = null;
      /* task-12 需求 6：详情区选区菜单同样"点外面就收"。
         ⚠️ 菜单自身是 .card-menu，用 .sel-menu 进一步区分，
         否则两个菜单同时在场会互相顶掉。 */
      if (selMenu.value && !(event.target && event.target.closest
        && event.target.closest('.card-menu.sel-menu'))) selMenu.value = null;
      /* 需求 6 原文「框选后点空白处取消框选」，实现见 SEL_KEEP_SELECTORS 注释的口径。
         ⚠️ 只处理**左键**：右键 mousedown 正是"在已有选区上再右键"的路径
         （onSelContext 要读这个选区），这里清了它菜单就只有空文本。 */
      const _t = event.target;
      if (event.button === 0 && _t && _t.closest && !_t.closest(SEL_KEEP_SELECTORS)) {
        try {
          const _sel = window.getSelection && window.getSelection();
          if (_sel && !_sel.isCollapsed) {
            const _anchor = _sel.anchorNode;
            const _ael = _anchor && (_anchor.nodeType === 1 ? _anchor : _anchor.parentElement);
            /* 锚点在详情区 **且** 按下的位置不是详情区可选文本 → 取消框选 */
            if (_ael && _ael.closest('.detail-wrap') && !_t.closest(SEL_TEXT_KEEP)) {
              _sel.removeAllRanges();
            }
          }
        } catch (err) { /* 静默 */ }
      }
      /* 收藏夹右键菜单（重命名/删除）：点到菜单外面任何地方都收起 */
      if (favMenu.open && !(event.target && event.target.closest
        && event.target.closest('.fav-menu'))) favMenu.open = false;
      /* 下载任务条右键菜单（复制链接/重试）：点到外面就收起 */
      if (downloadMenu.open && !(event.target && event.target.closest
        && event.target.closest('.download-menu'))) closeDownloadMenu();
      /* 本轮新增：AI 气泡右键菜单 / 模型切换弹层 / @候选，点外面都收起。
         ⚠️ @候选不能在这里收：它靠输入内容（aiAtKeydown / syncAiAtPopup）自己收，
            点候选项本身要走 click；所以只排除 .ai-at-pop。 */
      if (aiCtx.open && !(event.target && event.target.closest
        && event.target.closest('.ai-ctx-menu'))) closeAiCtx();
      if (aiModelOpen.value && !(event.target && event.target.closest
        && event.target.closest('.ai-model-wrap'))) aiModelOpen.value = false;
      /* 对话模式弹层同理：点它外面就收起 */
      if (aiModeOpen.value && !(event.target && event.target.closest
        && event.target.closest('.ai-mode-wrap'))) aiModeOpen.value = false;
      /* 本轮（需求 4 + 用户新规格）：用量统计浮层**不**由"点外面"关闭 ——
         开合只认悬浮：进入 .ai-stats-wrap 显示、离开这块区域自动收（见 aiStatsHover）。
         全局"点外面收起弹层"这条链如果保留它，鼠标还停在区域内点一下就关了、
         mouseenter 又不会重新触发，面板会"悬着不出来"，正是用户要杜绝的。 */
      if (toastLink.open && !(event.target && event.target.closest
        && event.target.closest('.toast-link-menu'))) toastLink.open = false;
      /* 公告正文右键菜单：点菜单外面收起（菜单内部自己 .stop，不会走到这里） */
      if (noticeCtx.value && !(event.target && event.target.closest
        && event.target.closest('.notice-menu'))) closeNoticeCtx();
      /* 清空下拉菜单：点到外面就收起 */
      if (clearMenuOpen.value && !(event.target && event.target.closest
        && event.target.closest('.dropdown-btn'))) clearMenuOpen.value = false;
      /* 需求：侧边栏模式的 AI 抽屉，点界面外任何地方都自动关闭
         （点抽屉内部 / 悬浮球本身不算"外面"）。
         ⚠️️ 本轮修复「右侧边悬浮窗口点击菜单中按钮会自动关闭侧边GCP-AI聊天窗」：
            菜单类浮层（气泡右键 .ai-ctx-menu、通用输入框右键 #input-menu、
            模型弹层 .ai-model-pop、@ 候选 .ai-at-pop）在 DOM 上**都不在 .ai-drawer 里**
            （前两个挂在 body / #app 外，后两个虽然在同一棵子树里但点击目标可能落在
             弹层自身上），所以"点菜单项"会被这里判成"点了抽屉外面"→ 抽屉先关了，
            菜单的 click 也就丢了（表现就是"点菜单按钮会把聊天窗关掉"）。
            → 这些浮层一律算"抽屉内部"，点它们不关抽屉。 */
      if (aiOpen.value && !settings.ai_sidebar_mode) {
        const t = event.target;
        const inside = t && t.closest && (t.closest('.ai-drawer') || t.closest('.float-ball')
          || t.closest('.ai-ctx-menu') || t.closest('#input-menu')
          || t.closest('.ai-model-pop') || t.closest('.ai-at-pop'));
        if (!inside) aiOpen.value = false;
      }
      if (!moreOpen.value) return;
      const target = event.target;
      if (target && target.closest && (target.closest('.more-pop') || target.closest('.nav'))) return;
      moreOpen.value = false;
    }
    function goto(key) {
      if (key === 'more') { moreOpen.value = !moreOpen.value; return; }
      moreOpen.value = false;
      navHover.value = false;
      navPinned.value = false;  // 点击任意导航项（除 more）关闭侧边栏
      /* ⚠️⚠️ 本轮删除"未保存"拦截弹窗（用户原话）：
         「删除GCP-AI设置中未保存就弹出是否保存配置或者留在界面的那个弹窗删除。」
         原来这里在"从设置页切走 + API Key 草稿有改动"时弹一个
         三选框（放弃修改 / 留在当前界面 / 保存并继续）。
         取舍说明（写清楚，别再"顺手加回去"）：
           · 设置页里**只有 API Key 那一格**是"要点保存才落盘"的
             （文本行/下拉都是 onRowCommit 即时提交，见 index.html 的 @change）；
           · 所以这个弹窗真正在保护的只有"Key 打到一半没保存"这一种情况；
           · 用户嫌它烦 → 现在直接切页。代价是没保存的 Key 草稿会被丢掉，
             回来时 loadApiKeyForProvider() 重新从后端读（不会写出半截 Key，
             也不会把半截 Key 存进配置，数据不会坏）。
         保留 apiKeyDirty()/saveApiKey() 本身（保存按钮、离开前的其它判断还在用）。 */
      doGoto(key);
    }
    /* 需求：任何页面滚到某位置 → 切走 → 切回来，必须回到原位。
       背景（修复）：旧实现有两个硬伤，导致"切回来仍然回到最顶端"：
         ① 用 `document.querySelector('.page-scroll')` 取"当前页面"的滚动容器，
            但 `<transition mode="out-in">` 是**先退后进**：切页时旧页面还在（正在退场），
            nextTick 时 querySelector 取到的还是旧元素，scrollTop 写回旧元素 → 白写；
         ② 新页面 130~150ms 后才挂载，旧实现只在 nextTick 还原一次，早于新元素出现。
       修法：
         · 每个滚动容器在模板里带 `data-scroll-key="<页面>"`（settings 用 .settings-main，
           maker 用 .maker-form-scroll），按 key 精确定位，不会写错元素；
         · 切页前 remember 当前 key，切页后用 transition 的 @after-enter + 多帧重试
           （内容高度晚一拍才稳定，尤其搜索页虚拟列表），直到 scrollTop 真的等于目标值。 */
    const pageScrollMemory = Object.create(null);
    /* ⚠️ 「呼出搜索框」要强制回顶的**待办标记**。
       为什么需要它：`doGoto` 会把新页面的滚动位置**恢复**成上次记住的值
       （pageScrollMemory 那套机制，见上面的注释），所以托盘/热键呼出搜索框时
       看到的往往是搜索页的**中间**而不是顶端。
       而 `<transition name="page" mode="out-in">` 是**先退后进** —— 新页面要
       130~150ms 后才挂载，`focusSearch` 里立刻调 scrollToTop() 时
       `searchScroll.value` 还是旧元素/空 → 那一拍是白写的。
       → 所以先置这个标记，等 @after-enter（新页面真的挂上了）再回顶一次。
       ⚠️ 只影响「呼出搜索框」这条路径：「手动滚动 → 切走 → 切回要回原位」
          这个既有需求**不受影响**（那个由 pageScrollMemory 独立负责）。 */
    let pendingScrollTop = false;
    /* ⚠️ 同一个记忆 key 可能挂在**多个候选容器**上，必须由这里挑出"真正在滚的那一个"：
       · 投稿表单宽屏时 .maker-form-scroll 是滚动容器（layout.css:472 overflow-y:auto），
         而窗口宽 ≤1128px 时 CSS 把滚动权交给父级 .maker-body、同时把
         .maker-form-scroll 改成 overflow:visible（layout.css:1280-1286）⇒
         旧实现按文档顺序取第一个（父级 .maker-body），在窄窗口里量到的永远是 0，
         "切走再切回就回到顶端"就是这么来的；
       · 投稿页另外三个分节（资源浏览 / 批量合成 / 使用说明）各有各的
         .maker-section-scroll，也要能记住自己的位置。
       ⚠️ 判据不能只看 scrollHeight > clientHeight：overflow:hidden 的容器
          一样会"内容比盒子高"，必须先看计算样式的 overflow-y。 */
    function canScrollY(el) {
      try {
        const overflow = getComputedStyle(el).overflowY;
        return overflow === 'auto' || overflow === 'scroll' || overflow === 'overlay';
      } catch (error) { return false; }
    }
    /* 投稿页四个分节的滚动容器互不相同（v-if 切换），记忆也按分节分开存：
       否则"表单滚到 800 → 切到资源浏览（那里是 0）→ 切页 → 切回"会把表单那 800 冲掉。 */
    function scrollMemoryKey(pageKey) {
      return pageKey === 'maker' ? 'maker:' + activeSection.value : pageKey;
    }
    function findPageScroller(scrollerKey) {
      if (!scrollerKey) return null;
      const list = document.querySelectorAll('[data-scroll-key]');
      let first = null, scrolled = null, tall = null;
      for (let i = 0; i < list.length; i += 1) {
        const el = list[i];
        if (el.getAttribute('data-scroll-key') !== scrollerKey) continue;
        if (!first) first = el;
        if (!canScrollY(el)) continue;                 // 滚不动的容器不配当滚动容器
        if (el.scrollTop > 0) scrolled = el;           // 正在滚的那个（切走时量它）
        if (!tall && el.scrollHeight > el.clientHeight + 1) tall = el;   // 有溢出内容（切回时写它）
      }
      return scrolled || tall || first;
    }
    function rememberPageScroll(pageKey) {
      const key = scrollMemoryKey(pageKey);
      const el = findPageScroller(key);
      if (el) pageScrollMemory[key] = el.scrollTop;
    }
    function restorePageScroll(pageKey, attempt = 0, userMoved = null) {
      const key = scrollMemoryKey(pageKey);
      const want = Number(pageScrollMemory[key] || 0);
      const el = findPageScroller(key);
      if (!el) {
        /* 页面还在过渡中（out-in 的 enter 尚未挂载）→ 下一帧再试 */
        if (attempt < 12) requestAnimationFrame(() => restorePageScroll(key, attempt + 1, userMoved));
        return;
      }
      /* ⚠️ 别把用户刚滚出来的位置拽回去（真实缺陷，不是探针问题）：
         切页走 out-in 过渡，恢复位置要等 @after-enter（新页面真的挂上了）才跑，
         而新页面在这几百毫秒里已经"活"了 —— 用户完全可能已经先滚了一下
         （页面内容一进来就很长时尤其明显）。
         这时再按记忆值写一次 scrollTop ⇒ 画面被瞬间拽回顶部/中段，
         右下角"回到顶部"球也跟着熄灭（用户会以为滚动失灵）。
         判定：容器已经离开初始位置(0) 且不等于目标值 ⇒ 认定用户动过了，让用户的位置作数。
         ⚠️ 容器还在 0（刚挂载）时照常恢复 ⇒ "切走再切回要回原位"这个既有需求不受影响。
         ⚠️ 这个判定只做一次（第一次找到容器时），后面的重试沿用同一个结论：
            否则"内容高度晚一两帧才稳定"的重试链会把我们**自己**被浏览器截断的写入
            （scrollTop 被夹到内容上限）误判成"用户动过"，重试就断了。 */
      const moved = (userMoved === null)
        ? (el.scrollTop !== 0 && el.scrollTop !== want)
        : userMoved;
      if (moved) return;
      if (key === 'search') {
        measureViewport();
        scrollTop.value = want;             /* 虚拟列表按目标位置先算出要渲染的行 */
      }
      if (el.scrollTop !== want) el.scrollTop = want;
      if (key === 'search') scrollTop.value = el.scrollTop;
      /* 内容高度可能晚一两帧才稳定（虚拟列表 / 图片 / 筛选面板），继续追几帧 */
      if (el.scrollTop !== want && attempt < 12) {
        requestAnimationFrame(() => restorePageScroll(key, attempt + 1, moved));
      }
    }
    /* ---------- 右下角「回到顶部」悬浮球（第七轮需求） ----------
       用户要的形态：圆球 + 朝上箭头，只在**搜索页 / 定制页**（m06914 收紧过范围），
       页面不在最顶端时从下往上渐变出现，回到顶端时从上往下渐变消失，
       点击后按"两边慢中间快"的曲线滚回顶部。

       ⚠️ 可见性只在**跨越阈值时**才写响应式 ref（见 syncBackTop 的 if）：
          滚动事件每帧都来，直接 backTopVisible.value = (scrollTop > 8) 会让整个
          setup 作用域跟着重渲染评估 —— 搜索页是虚拟列表，那个代价付不起。
       ⚠️ backTopScroller 缓存"最后一次滚动的容器"：定制页的 .page-scroll 没有 ref，
          点击时再查一次 DOM 也行，但缓存能躲开"v-if 刚切换、querySelector 拿不到"的窗口。 */
    const BACK_TOP_PAGES = ['search', 'customize'];
    /* 出现阈值：用户第十轮（m08106）「页面往下翻一小段距离才出现，例如第二排一半
       高度的卡片高度长度距离才会出现这个 ui」⇒ 不再用"一动就亮"的字面像素，而是
       **按当前视图的排距现算 1.5 排**（第一排整排 + 第二排的一半）。
       为什么不能写死数字：搜索页排距随卡片尺寸档位（小/中/大）、视图（网格/磁贴）、
       列数余数摊分而变，定制页卡片另有 196px 起的高度；写死 300px 在某种档位下
       就是"刚露第二排就亮"或"翻两排还不亮"。
       ⚠️ 兜底顺序：量不到行距（容器还没挂载卡片 / 列表为空）时退回下面的下限，
          至少保证"顶端不闪现、往下滚一定出现"，绝不因为量不到就永不出现。 */
    const BACK_TOP_ROW_FACTOR = 1.5;
    /* 下限仍保留 8px（不是 >0）：高 DPI 下 WebView2 会报出 0.5 这类分数 scrollTop，
       用 >0 会让球在顶端反复闪现。行距量不到时它就是唯一闸门。 */
    const BACK_TOP_SHOW_PX = 8;
    /* 一行的"排距"= 行高 + 行间距。两处来源都是**页面自己怎么摆的就怎么量**：
       · 搜索页虚拟列表把 row.height / row.gap 写在 .vrow 行内样式上（app.js 的 rowModel
         算出来的），所以读行内样式即可，不必再复制一遍布局算法（复制了就会有两套真相）；
       · 定制页是 flex-wrap 的 .grid-static（components.css：gap 14px），卡片高度由内容
         撑出来，只能量真实 rect。 */
    function backTopRowPitch(el) {
      if (!el) return 0;
      const row = el.querySelector('.vrow');
      if (row) {
        const h = parseFloat(row.style.height) || 0;
        const g = parseFloat(row.style.gap) || 0;
        if (h > 0) return h + g;
      }
      const grid = el.querySelector('.grid-static');
      const card = grid && (grid.querySelector('.card') || grid.firstElementChild);
      if (card) {
        const cs = window.getComputedStyle(grid);
        const h = (card.getBoundingClientRect && card.getBoundingClientRect().height) || 0;
        const g = parseFloat(cs.rowGap) || parseFloat(cs.gap) || 0;
        if (h > 0) return h + g;
      }
      return 0;
    }
    function backTopShowPx(el) {
      const pitch = backTopRowPitch(el);
      return pitch > 0 ? Math.max(BACK_TOP_SHOW_PX, Math.round(pitch * BACK_TOP_ROW_FACTOR))
        : BACK_TOP_SHOW_PX;
    }
    const backTopVisible = ref(false);
    const backTopPage = computed(() => BACK_TOP_PAGES.indexOf(page.value) >= 0);
    let backTopScroller = null;
    let backTopRaf = 0;
    function backTopKey() { return scrollMemoryKey(page.value); }
    function syncBackTop(el) {
      const node = el || findPageScroller(backTopKey());
      if (!node) {
        /* 容器还没挂载（切页过渡中）：先熄灭，别把上一页的状态带过来 */
        if (backTopVisible.value) backTopVisible.value = false;
        return;
      }
      backTopScroller = node;
      const on = node.scrollTop > backTopShowPx(node);
      if (on !== backTopVisible.value) backTopVisible.value = on;
    }
    /* scroll 不冒泡 ⇒ 只能捕获阶段挂 document。
       搜索页已有 @scroll.passive（onScrollArea）、定制页什么都没挂，与其给定制页补一个
       模板绑定、再在两个处理器里各调一次，不如这一处统一接管：以后多放一个页面
       只改 BACK_TOP_PAGES。 */
    function onAnyScrollForBall(ev) {
      if (!backTopPage.value) return;
      const el = ev && ev.target;
      if (!el || el.nodeType !== 1 || typeof el.getAttribute !== 'function') return;
      if (el.getAttribute('data-scroll-key') !== backTopKey()) return;
      syncBackTop(el);
    }
    /* 用户自己动手（滚轮 / 触摸 / 方向键）就立刻放弃程序动画：
       动画中途还在写 scrollTop 会和用户的滚动打架（表现为"滚不动"或"跳回去"）。 */
    function abortBackTopAnim() {
      if (backTopRaf) { cancelAnimationFrame(backTopRaf); backTopRaf = 0; }
    }
    function onUserScrollInput(ev) {
      if (!backTopRaf) return;
      /* 键盘只拦真正会滚页面的那几个键，否则打字（AI 输入框）也会打断 */
      if (ev && ev.type === 'keydown') {
        const k = String(ev.key || '');
        if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '].indexOf(k) < 0) return;
      }
      abortBackTopAnim();
    }
    /* 原生 smooth 不可用时的兜底动画（老内核）。用户嫌慢之后时长压到 260~520ms，
       和原生 smooth 的手感对齐；曲线仍是 easeInOutCubic（两头慢中间快）。 */
    function runFallbackBackTop(el, start, isSearch) {
      if (!el || !el.isConnected) return;
      const from = Math.max(0, Number(el.scrollTop) || 0);
      if (from <= 0) { syncBackTop(el); return; }
      const dur = Math.min(520, Math.max(260, Math.round(from * 0.32)));
      const showPx = backTopShowPx(el);
      const t0 = (window.performance && performance.now) ? performance.now() : Date.now();
      const ease = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
      const step = (now) => {
        const t = (now - t0) / dur;
        const p = t >= 1 ? 1 : (t <= 0 ? 0 : t);
        el.scrollTop = from * (1 - ease(p));
        if (isSearch) { scrollTop.value = el.scrollTop; measureViewport(); }
        const on = el.scrollTop > showPx;
        if (on !== backTopVisible.value) backTopVisible.value = on;
        if (p < 1) { backTopRaf = requestAnimationFrame(step); return; }
        backTopRaf = 0;
        el.scrollTop = 0;
        if (isSearch) { scrollTop.value = 0; measureViewport(); }
        if (backTopVisible.value) backTopVisible.value = false;
      };
      backTopRaf = requestAnimationFrame(step);
    }
    function backToTop() {
      const key = backTopKey();
      const el = (backTopScroller && backTopScroller.isConnected)
        ? backTopScroller : findPageScroller(key);
      if (!el) return;
      const start = Math.max(0, Number(el.scrollTop) || 0);
      abortBackTopAnim();
      if (start <= 0) { syncBackTop(el); return; }
      /* 时长跟距离走（0.55ms/px，夹在 360~880ms）：几十 px 不该拖 0.9 秒，
         上万 px 也不该一帧闪完（用户要的是"看得见加减速"的曲线）。 */
      /* 时长跟距离走（用户第十轮：「速度要让用户能看清而不是特别快」）。
         旧口径 0.55ms/px、上限 880ms 的实际观感：翻十几屏也只 0.9 秒冲回去，
         中段快到人看不清自己在往哪走。改成 0.9ms/px、夹在 900~1600ms：
         近距离不低于 0.9 秒（起步/收尾都看得见），超远距离封顶 1.6 秒（再长就成拖沓）。 */
      /* ⚠️ 用户第十三轮：「搜索页/定制页那个回到顶部滑得太慢，GCP-AI 那颗按钮的速度就很好」。
         GCP-AI 用的是浏览器**原生 smooth**（约 300~500ms，和距离无关，所以多远都不觉得拖）。
         之前这里手写了 900~1600ms 的曲线，是上一轮为了「看得清加减速」特意放慢的，
         结果和 AI 页面对比之下就成了「太慢」—— 同一软件里两套滚动速度手感就是不一致。
         现在统一走原生：搜索页的虚拟列表靠 @scroll.passive=onScrollArea 驱动，
         原生平滑滚动一样会逐帧派发 scroll 事件（和用户滚轮滚到底同一条链路），
         所以不会露空白行；老内核没有 behavior 参数时才退回下面的手写动画。 */
      if (typeof el.scrollTo === 'function') {
        try {
          el.scrollTo({ top: 0, behavior: 'smooth' });
          /* 两帧后还没动 = 这个内核不认 smooth（老 Edge/WebView2 兼容模式），补手写动画；
             已经在动就交给原生 + scroll 事件，别再插手，否则两边抢 scrollTop。 */
          requestAnimationFrame(() => requestAnimationFrame(() => {
            const now = Number(el.scrollTop) || 0;
            if (now <= 0) { syncBackTop(el); return; }
            if (Math.abs(now - start) < 2) runFallbackBackTop(el, start, isSearch);
          }));
          return;
        } catch (err) { /* 不支持对象参数：落到下面的手写动画 */ }
      }
      const dur = Math.min(520, Math.max(260, Math.round(start * 0.32)));
      const showPx = backTopShowPx(el);   // 阈值在动画开始时定一次，见上面注释
      const t0 = (window.performance && performance.now) ? performance.now() : Date.now();
      const isSearch = el.getAttribute('data-scroll-key') === 'search';
      /* easeInOutCubic = 两边慢中间快（起步先加速、中段最快、快到顶端慢慢停） */
      const ease = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
      const step = (now) => {
        const t = (now - t0) / dur;
        const p = t >= 1 ? 1 : (t <= 0 ? 0 : t);
        el.scrollTop = start * (1 - ease(p));
        /* ⚠️ 搜索页是虚拟列表：光写 el.scrollTop 不会重算渲染窗口，
           必须和 restorePageScroll 一样同步 scrollTop.value + measureViewport()，
           否则动画期间会露出空白行。 */
        if (isSearch) {
          scrollTop.value = el.scrollTop;
          measureViewport();
        }
        const on = el.scrollTop > showPx;
        if (on !== backTopVisible.value) backTopVisible.value = on;
        if (p < 1) { backTopRaf = requestAnimationFrame(step); return; }
        backTopRaf = 0;
        el.scrollTop = 0;                      // 收尾对齐整数，别停在 0.4 这种残值
        if (isSearch) { scrollTop.value = 0; measureViewport(); }
        if (backTopVisible.value) backTopVisible.value = false;
      };
      backTopRaf = requestAnimationFrame(step);
    }
    /* ⚠️ 监听 page 本身，不能监听 backTopPage：搜索页 ⇄ 定制页两边都算"允许页"，
       布尔 computed 的值压根没变，watch 不触发 ⇒ 动画继续写已经被 v-if 摘掉的旧容器，
       还会按旧容器的位置去点亮新页面的球（probe_back_top_ball.mjs 的 R6 就是这么抓到的）。 */
    watch(page, () => {
      abortBackTopAnim();
      backTopScroller = null;
      if (!backTopPage.value) { backTopVisible.value = false; return; }
      nextTick(() => syncBackTop());
    });

    /* 页面 transition 真正结束（新页面已挂载）后由模板 @after-enter 调进来 */
    function onPageAfterEnter() {
      /* ⚠️ 「呼出搜索框」的强制回顶必须放在 restorePageScroll **之前**：
         restorePageScroll 会按 pageScrollMemory 把位置恢复回去，
         而回顶要求是 scrollTop = 0 —— 不先清记忆的话，恢复完又被顶回来，
         两个动作会互相打架（表现为"闪一下又跳回中间"）。 */
      if (pendingScrollTop) {
        pendingScrollTop = false;
        /* ⚠️ 只有真的落在搜索页才回顶：标记可能是在"本来就在搜索页"时置的，
           那时不会切页、@after-enter 不触发，标记会**滞留**到下一次切页 ——
           如果那时落到了收藏页还去回顶，就会顺手把 pageScrollMemory.search 清成 0，
           破坏「手动滚动 → 切走 → 切回要回原位」这个既有需求。
           → 任何一次切页都把标记消费掉，但只在落到搜索页时才真的回顶。 */
        if (page.value === 'search') {
          scrollToTop();
          /* 虚拟列表的内容高度晚一两帧才稳定 → 再补一拍，
             否则 scrollTop 写进去了、渲染窗口却还按旧位置算（看着像没回顶）。 */
          requestAnimationFrame(() => scrollToTop());
        }
      }
      restorePageScroll(page.value);
      if (page.value === 'search') measureViewport();
      /* 回到顶部球：restorePageScroll 恢复出来的位置可能本来就不在顶端（用户切走前
         滚在中段，切回来球就该是亮着的）。容器已挂载，这里直接对账一次。 */
      syncBackTop();
      /* 收藏页的网格是 `v-if="favItems.length"` 的 —— 页面**真正挂载后**
         才拿得到元素。doGoto 里的 nextTick 早于 out-in 的 enter，那时量不到宽度，
         卡片会用兜底宽度渲染；这里补一次真实测量，宽度就准了。
         ⚠️ 这也是"面条"bug 的另一半：之前只在 doGoto 里量 + 靠 ResizeObserver 兜，
            ResizeObserver 在**首次**插入元素时也会触发一次，但时机不可控。 */
      if (page.value === 'favorites') {
        measureFavGrid();
        /* 网格可能下一帧才有内容（收藏数据是异步的）→ 再补一拍 */
        requestAnimationFrame(() => measureFavGrid());
      }
      /* ⚠️ 必须在"新页面真的挂载"之后重排 segmented 滑块：
         doGoto 里的 nextTick 早于 out-in 的 enter（那时取到的是旧页面/没有 .view-seg），
         不在这里补一次，切页回来后视图切换器会丢掉 .seg-thumb，
         选中态退回 .seg-item.is-on 的兜底底色（用户说的"每项下面像选中的底"）。 */
      /* 切页不是"点 tab"，滑动块直接瞬时对齐（immediate），
         不在这里补一次会丢掉 .seg-thumb，补动画又会显得整页重新加载。 */
      requestAnimationFrame(() => syncSegThumbs(true));
    }
    /* 切页/打开配置页后头 ~120ms 静默运动 —— 防止开关/分段/导航指示标的入场过渡
       重新播放一遍（进入配置页面这个开关会重新播放开启动画…所有这种类型的都要修）。 */
    let silentMotionTimer = 0;
    function silentMotion() {
      const root = document.documentElement;
      root.classList.add('is-silent-motion');
      clearTimeout(silentMotionTimer);
      silentMotionTimer = setTimeout(() => root.classList.remove('is-silent-motion'), 120);
    }
    function doGoto(key) {
      /* 详情页打开时，列表页的滚动容器已经被 v-if 卸掉；此时"当前页"的滚动位置
         存在 detailScrollMemory 里（进详情时记的），不能再去 querySelector 找列表容器。
         ⚠️ 只有 `page === detailPage`（详情正挂在来源页上）才允许把这份记忆写到
            当前页 key —— 否则"在搜索页进的详情、切到收藏页再切回"时，会把**搜索页**
            的滚动位置记到收藏页 key 上（跨页污染，恢复出来位置永远是错的）。 */
      if (detail.value && page.value === detailPage.value) {
        pageScrollMemory[page.value] = detailScrollMemory;
      } else {
        /* 两种情况都走这里：① 没有详情；② 详情挂在**别的**页面上（detail 段 v-if 要求
           page === detailPage，所以当前页此刻渲染的是它自己的列表，容器在场、可直接量）。 */
        rememberPageScroll(page.value);
      }
      /* 切页**不再**无条件清掉详情 —— 切走再切回要能看到原来的详情。
         ⚠️ detailPage 记着"这个详情是从哪个页面打开的"，切回那个页面时自动挂上；
            切到别的页面时详情先留着（下次切回还能看到）。
         ⚠️ 只有用户主动点返回才真的关掉（closeDetail 里清 detailPage）。 */
      if (detail.value) rememberDetailPage();
      detailSequence += 1;
      moreOpen.value = false;          /* 切页必定收起「更多」浮层 */
      /* 插件配置页是覆盖在右侧内容区上的一层（不是独立页）；用户点导航切到别处时
         必须收起，否则它会一直盖着新页面。 */
      pluginPage.value = null;
      if (key === 'ai' && !(settings.ai_enabled && settings.ai_sidebar_mode)) key = 'search';
      page.value = key;
      silentMotion();
      selectionBar.value = false;
      /* 下载页是普通页面（page === 'download'）。
         · 进入下载页 → 拉一次列表 + 开始轮询；
         · 离开下载页 → 停轮询（红点靠 download.progress 事件维持）。 */
      if (key === 'download') {
        downloads.open = true;
        loadDownloads();
        startDownloadPoll();
      } else if (downloads.open) {
        downloads.open = false;
        stopDownloadPoll();
      }
      nextTick(() => {
        /* 切完页先把新页面的滚动位置还原（虚拟列表要重新量视口后再同步 scrollTop）。
           @after-enter 还会再兜一次；这里先做一次让首帧不跳。 */
        if (key === 'search') { measureViewport(); panelHeight(); }
        /* 收藏页的卡片列宽要按新页面的实际宽度算一次 */
        if (key === 'favorites') measureFavGrid();
        restorePageScroll(key);
        /* 首页已整体移除（海报轮播 / 边缘色 / 异步出图那一套代码一起删掉了），
           所以这里不再有"进首页重排轮播、离开首页停定时器"的分支。 */
        if (key === 'notice' && !notices.value.length) loadNotices(false);
        if (key === 'plugins' && !pluginList.value.length) loadPlugins(false);
        if (key === 'log') loadLogFiles();
        if (key === 'settings') currentSection.value = sections.value[0].key;
        if (key === 'ai') focusAiInput();
        nextTick(() => syncSegThumbs(true));
      });
    }
    function toggleNav() { navPinned.value = !navPinned.value; }
    function onNavLeave() { if (!navPinned.value) navHover.value = false; }
    const canBack = computed(() => !!detail.value);
    function goBack() { closeDetail(); }

    /* ---------- 窗口（原生：SC_MINIMIZE / SC_MAXIMIZE / WM_CLOSE / 原生拖动） ---------- */
    /* 全屏状态只有一个入口：applyFullscreenState()。
       背景（修复）：以前 toggleFullscreen 只改 win.fullscreen，而 F11 被 WebView2
       的浏览器快捷键吃掉时页面根本收不到 keydown；后端就算切了全屏，前端也不知道。
       现在：
         · 后端在切换成功后 push_event('window.fullscreen', {fullscreen})；
         · 前端这里监听事件 + 同步 #app 的 is-fullscreen 类（base.css 靠它隐藏标题栏）；
         · 按钮点击仍会 await window.toggle_fullscreen，失败时明确 toast，不再"点了没反应"。 */
    function applyFullscreenState(full) {
      win.fullscreen = !!full;
      const root = document.getElementById('app');
      if (root) root.classList.toggle('is-fullscreen', !!win.fullscreen);
      /* 全屏/窗口切换会改变左侧栏可用高度：底部导航条目（设置 / 更多…）由
         nav-spacer 撑到栏底，栏高一变它们整体上下移动。而这里只是切了个类名，
         **不会**触发 window resize（resize 在 SetWindowPos 时就已先于本函数触发，
         那时标题栏还没隐藏、量到的是旧高度），指示标会留在旧坐标上——
         看起来就是"切全屏后选中标指着错的条目"。所以状态落地、布局重排后补量一次。 */
      requestAnimationFrame(() => syncNavIndicator(false));
    }
    onEvent('window.fullscreen', (payload) => {
      if (payload && typeof payload === 'object' && 'fullscreen' in payload) {
        applyFullscreenState(payload.fullscreen);
      }
    });
    async function syncWindow() {
      const result = await bridge.tryCall('window.state');
      if (result && result.ok) {
        win.maximized = !!result.maximized;
        applyFullscreenState(!!result.fullscreen);
        win.minimized = !!result.minimized;
      }
      /* 把窗口状态同步到根节点：base.css 里 #app.is-maximized / .is-fullscreen
         的规则（标题栏分隔线颜色等）依赖这些类名，之前一直没人挂上。 */
      const root = document.getElementById('app');
      if (root) {
        root.classList.toggle('is-maximized', !!win.maximized);
        root.classList.toggle('is-fullscreen', !!win.fullscreen);
      }
    }
    async function minimizeWindow() { await bridge.call('window.minimize').catch(() => {}); setTimeout(syncWindow, 260); }
    async function maximizeWindow() {
      /* 中间按钮 = 最大化 / 还原整个程序（不是全屏，顶部栏保留）。
         后端 window.toggle_maximize 返回 {ok, maximized}；拿不到接口时明确提示，
         不静默失败（和 toggleFullscreen 的处理保持一致）。 */
      const result = await bridge.tryCall('window.toggle_maximize');
      if (result && result.ok) win.maximized = !!result.maximized;
      else if (result && result.error) {
        toast(t('maximize_failed', '最大化切换失败：{err}').replace('{err}', result.error), 'error');
      } else if (!result) needApi('window.toggle_maximize', '最大化');
      setTimeout(syncWindow, 260);
    }
    /* 窗口边缘热区 → 缩放。两条路，优先第一条：
       ① 确定性缩放会话（window.resize_begin/resize_drag/resize_end）：
          后端快照「起始物理矩形 + 最小尺寸 + CSS→物理系数」，我们每帧只报
          **相对按下点的位移**，窗口位置由后端重算。不吃 WS_THICKFRAME、
          不进系统模态循环 ⇒ 网友报的「拖边完全没反应」不再依赖对方机器上
          那条原生链路是否装成功（见 desktop/native/frame.py 会话区的注释）。
       ② 原生 start_resize（ReleaseCapture + WM_NCLBUTTONDOWN）：只在 ①
          明确不可用时回落 —— 最大化/全屏（这两种情况原生手感更好：会先还原
          再缩放、或根本不该缩），以及老后端没有会话接口。
       ⚠️ 位移用 **screenX/screenY** 的差值，不用 clientX/clientY：client 坐标是
          **相对视口**的，而拖左边/上边时视口本身正在被我们移动 —— 窗口挪 Δ，
          同一个物理位置的 clientX 就跟着变 Δ，下一帧算出的位移又小 Δ，于是
          缩回去一点、再放大一点，形成自激振荡。用户报的「左侧和斜角拉拽时窗口
          不停颤抖、越远越明显」（m05379 第②项）就是这个：只有**会移动窗口原点**
          的边和角抖，右边和下边不抖，完全对得上。screen 坐标相对物理屏幕，
          窗口怎么动都不影响它 ⇒ 回路断开。仍然是「只传差值、不传绝对坐标」：
          界面同时受 DPI 和页面 ZoomFactor 影响，绝对坐标混进链路就是越拖越偏。
       ⚠️ pointerdown 被 .prevent 掉是为了压住 Chromium 的默认行为（文字选择、
          以及最顶端那几像素会误触标题栏拖动），CSS 里已把顶端热区压到 4px。 */
    let _resizeSession = null;
    async function startResize(direction, event) {
      /* ⚠️ 最大化 / F11 全屏下一律不缩（用户 m00766：全屏时靠近边缘出现拉伸光标，
         会让人觉得「这不是真全屏，是自己画的」）。模板与 CSS 已经把热区去掉了，
         这里再挡一道：状态万一还没同步过来，也不会真的进缩放流程。 */
      if (win.maximized || win.fullscreen) return;
      const dir = String(direction || '');
      const zone = event && event.currentTarget ? event.currentTarget : null;
      const pointerId = event ? event.pointerId : undefined;
      const ox = (event && event.screenX) || 0;
      const oy = (event && event.screenY) || 0;
      let last = { x: ox, y: oy };
      let busy = false;
      let again = false;
      const stop = () => {
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
        window.removeEventListener('pointercancel', onUp);
        window.removeEventListener('blur', onBlur);
        if (zone && zone.releasePointerCapture && pointerId !== undefined) {
          try { zone.releasePointerCapture(pointerId); } catch (e) { /* 已释放 */ }
        }
        if (_resizeSession && _resizeSession.stop === stop) _resizeSession = null;
      };
      /* 焦点被抢走时 pointerup 可能永远收不到（无边框 + WebView2 尤其容易：
         系统弹窗、切窗口、浏览器抢前台都会让它漏掉）。漏掉的后果是会话一直挂着，
         之后鼠标每动一下都在缩放窗口 —— 比"拖不动"还诡异。blur 兜一道。 */
      const onBlur = () => {
        const live = !!_resizeSession;
        stop();
        if (live) bridge.tryCall('window.resize_end').catch(() => {});
      };
      const send = () => {
        /* 节流：一次调用在飞时只保留最后一次“鼠标动过”的信号，不排队
           （连续流丢中间帧没人察觉，排队反而让窗口跟在鼠标后面爬）。 */
        if (busy) { again = true; return; }
        busy = true;
        /* ⚠️ 一个坐标都不传：位移由后端 GetCursorPos 自己量（物理像素）。
           下面的 ox/oy/last 是 screen 坐标，**只用来判断这一帧到底动没动**，
           不参与任何窗口位置计算 —— 页面坐标受 DPI 与 ZoomFactor 双重影响，
           拿它算位移就是上一版「越拖越偏」的来源（详见 frame.resize_drag）。 */
        if (last.x === ox && last.y === oy) { busy = false; return; }
        bridge.tryCall('window.resize_drag').then(() => {
          busy = false;
          if (again && _resizeSession) { again = false; send(); }
        }).catch(() => { busy = false; again = false; });
      };
      const onMove = (e) => {
        if (!_resizeSession) return;
        last = { x: e.screenX, y: e.screenY };
        send();
      };
      const onUp = () => {
        const live = !!_resizeSession;
        stop();
        if (live) bridge.tryCall('window.resize_end').catch(() => {});
      };
      // 会话已经开着又被按了一次（多指/连点/上一次漏了 pointerup）：
      // ⚠️ 必须调**上一任**的 stop（`_resizeSession.stop`），不是本闭包的 stop() ——
      //    摘错函数的话旧 onMove 还挂在 window 上，两个闭包各按自己的原点发
      //    resize_drag，窗口会跟着跳。
      if (_resizeSession && _resizeSession.stop) {
        _resizeSession.stop();
        bridge.tryCall('window.resize_end').catch(() => {});
      }

      let begun = null;
      try {
        begun = await bridge.tryCall('window.resize_begin', dir, window.innerWidth || 0);
      } catch (e) { begun = null; }

      if (begun && begun.ok) {
        _resizeSession = { dir: dir, stop: stop };
        if (zone && zone.setPointerCapture && pointerId !== undefined) {
          // 捕获到热区元素上：指针滑出那 4px 也不会丢事件（否则一出边缘就停）
          try { zone.setPointerCapture(pointerId); } catch (e) { /* 不支持就算了 */ }
        }
        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', onUp);
        window.addEventListener('pointercancel', onUp);
        window.addEventListener('blur', onBlur);
        return;
      }

      // ② 回落原生：最大化/全屏（后端会话明确拒绝的两种）与老后端
      const result = await bridge.tryCall('window.start_resize', dir);
      if (!result) { needApi('window.start_resize', t('resize_window', '调整窗口大小')); return; }
      if (!result.ok && !(begun && begun.maximized)) {
        toast(t('resize_failed', '缩放窗口失败：') + (result.error || (begun && begun.error) || ''), 'error');
      }
    }
    /* 关闭程序时如果有**下载任务正在跑** → 弹窗确认
       （如果有下载任务正在执行关闭程序会弹窗提示有下载任务是否坚持退出）。
       ⚠️ 计数**问后端**（downloader.active_count）而不是只看前端列表 ——
          用户可能从头到尾没打开过下载页，前端列表是空的，光看它永远不会弹窗。
       ⚠️ 后端接口缺失时降级用前端列表（老后端兼容），不假装成功、也不崩。 */
    async function activeDownloadCount() {
      const active = await bridge.tryCall('downloader.active_count');
      if (active && typeof active.count === 'number') return active.count;
      return (downloads.items || []).filter(
        (it) => it.status === 'downloading' || it.status === 'paused').length;
    }
    /* 有下载在跑时的统一确认弹窗；返回 true = 用户同意退出。
       ⚠️ 同意后一定要调 shell.confirm_exit —— 否则后端的退出闸门还会**再弹一次**
          原生 MessageBox，用户就被弹两遍窗（前端一次 + 后端一次）。 */
    async function confirmExitWithDownloads() {
      const count = await activeDownloadCount();
      if (count <= 0) return true;
      const yes = await openDialog({
        title: t('download_exit_title', '还有下载任务在运行'),
        body: t('download_exit_body',
          '还有 {n} 个下载任务正在执行。\n现在退出会中断这些下载，确定要退出吗？')
          .replace('{n}', String(count)),
        danger: true,
        confirmText: t('download_exit_confirm', '仍然退出'),
        cancelText: t('download_exit_cancel', '继续下载'),
      });
      if (!yes) return false;                 // 取消 → 不退出
      /* 告诉后端「用户已经确认过了」—— 别再弹一次原生框 */
      await bridge.tryCall('shell.confirm_exit');
      return true;
    }
    async function closeWindow() {
      if (!await confirmExitWithDownloads()) return;
      await bridge.call('window.close').catch(() => {});
    }
    /* 托盘菜单「退出」走同一套确认（否则从托盘退出就绕过了下载确认）。 */
    async function confirmQuit() {
      if (!await confirmExitWithDownloads()) return;
      await bridge.tryCall('shell.quit');
    }
    async function hideToTray() { await bridge.call('window.hide_to_tray').catch(() => {}); }
    async function toggleFullscreen() {
      const result = await bridge.tryCall('window.toggle_fullscreen');
      if (result && result.ok) {
        applyFullscreenState(!!result.fullscreen);
      } else if (result && result.error) {
        toast(t('fullscreen_failed', '全屏切换失败：{err}').replace('{err}', result.error), 'error');
      } else if (!result) {
        needApi('window.toggle_fullscreen', '全屏');
      }
      /* 后端如果是异步 SetWindowPos（GUI 线程调度），260ms 后再同步一次兜底 */
      setTimeout(syncWindow, 260);
    }
    function interactive(target) {
      return !!(target && target.closest
        && target.closest('button, input, select, textarea, a, .no-drag, .card, .nav, .content'));
    }
    /* 自定义标题栏按下 → **拖动窗口**：**只走系统原生这一条**。
       用户原话：「标题栏拖拽……通过 ctypes 调用 ReleaseCapture() +
       SendMessage(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)。移除所有自定义 JS/Python 拖拽代码。」
       · 后端 frame.start_drag 做的是原生那套：ReleaseCapture + SendMessage(WM_NCLBUTTONDOWN,
         HTCAPTION)（F11 真全屏的 popup 窗口改用 WM_SYSCOMMAND/SC_MOVE，同样系统原生）；
       · 原来的「确定性移动会话」（window.drag_begin/drag_drag/drag_end）整条删除：
         自己算矩形落位 = 模拟，与系统行为不一致（最大化后拖动不会先还原、不吸附屏幕边缘），
         也是上一轮「窗口乱跳」的来源之一；
       · 拖动由系统模态循环接管，前端 fire-and-forget 即可，不需要等结果。 */
    let dragToken = 0;
    /* 拖动起点阈值（屏幕像素）：按下之后**真的移动了**才发拖动请求。
       ⚠️ 为什么必须有：最大化 / F11 全屏下，后端 start_drag 会**先把窗口还原成普通态**
          （_drag_restore_geometry，为了做到“光标下的那个点还原后还在原来的相对位置”）。
          如果按下就发，用户在标题栏上只是**点一下**（没拖），窗口也会莫名其妙地退出
          最大化/全屏 —— Windows 自己的行为是「移动超过拖动阈值才还原」，这里对齐它。
       ⚠️ 阈值判断用 screenX/screenY：client 坐标会随窗口移动而变（还原那一下窗口就动了），
          用它判断会把“窗口被还原”误当成“用户移动了”。 */
    const TITLE_DRAG_THRESHOLD = 3;
    function onTitleDown(event) {
      if (!event || event.button !== 0 || interactive(event.target)) return;
      dragToken += 1;
      const token = dragToken;
      const sx = Number(event.screenX) || 0;
      const sy = Number(event.screenY) || 0;
      let started = false;
      let finished = false;
      const cleanup = () => {
        finished = true;
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
        window.removeEventListener('pointercancel', onUp);
        window.removeEventListener('blur', onUp);
      };
      function onMove(e) {
        if (started || finished) return;
        const dx = Math.abs((Number(e.screenX) || 0) - sx);
        const dy = Math.abs((Number(e.screenY) || 0) - sy);
        if (dx < TITLE_DRAG_THRESHOLD && dy < TITLE_DRAG_THRESHOLD) return;
        started = true;
        cleanup();
        /* fire-and-forget：拖动由系统模态循环接管，前端不需要等结果；
           失败（非 Windows/窗口未就绪）时窗口不动，但不会留下任何僵尸监听。 */
        bridge.tryCall('window.start_drag', token).catch(() => {});
      }
      function onUp() { cleanup(); }
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp);
      window.addEventListener('pointercancel', onUp);
      window.addEventListener('blur', onUp);
    }
    function onTitleDouble(event) { if (!interactive(event.target)) maximizeWindow(); }

    /* ---------- 框选气泡文字后按 Ctrl+C 复制 ----------
       ⚠️ 本轮修复用户报的「鼠标框选选中气泡ui的文本按ctrl+c不复制」。
       为什么必须由我们接管（不是"用户操作不对"）：
         · `shell.py` 建窗时 `text_select=False`，pywebview 会往页面注入
           `body{user-select:none}`（见 webview/js/customize.js）；
         · 而 frame.py 又把 WebView2 的 `AreBrowserAcceleratorKeysEnabled`
           设成 False（为了 F11 归我们管）—— 这一项同时会**关掉浏览器默认的
           Ctrl+C/Ctrl+V 等编辑键**；
         · 我们能框选，是因为 ai-fixes.css / components.css 在 .bubble 上显式
           写了 `user-select: text`（把注入的那条压掉了）—— 选区有了，
           但**复制的默认动作仍然被 WebView2 那一层吞掉**，所以"选中了、按了、没进剪贴板"。
         · 项目里早就有**被验证可用**的复制通道：`copyText()` 走后端
           Win32 剪贴板（`clipboard.write`）+ 读回校验，正是"提示复制成功但剪贴板是空的"
           那个老 bug 的根治点。右键菜单的「复制」就是用它，所以那条一直是好的。
       ⇒ 这里给"选区落在气泡/思考正文里"这种情况补一条 Ctrl+C，复用同一个 copyText，
         与右键复制**完全同一条路**，行为一致、可预期。
       ⚠️ 边界（必须严格，否则会把正常输入框的复制搞坏）：
         · 焦点/选区在 input / textarea / contenteditable 里 → **一律不接管**，
           交回原生（输入框里的 Ctrl+C 由 WebView2 自己处理得好好的，
           而且我们的通用输入框右键菜单也在那边正常工作）；
         · 只有"文档级选区 + 选区在气泡内"才接管；
         · 只在**确实有选区**时 preventDefault；没选区就什么都不做
           （不能让 Ctrl+C 变成一个"吞掉但什么也不干"的死键）。 */
    /* ⚠️ 只列**页面里真实存在**的类（.ai-msg 并不存在，别留死选择器）：
       .bubble = 气泡本体，.ai-think-body = 思考正文，.ai-messages = 消息列表容器
       （覆盖容器内的"AI正在查看问题…"这类非气泡文本，复制它们同样是用户期望）。
       ⚠️ task-12 需求 6：详情区（.detail-wrap）的框选文字也要 Ctrl+C 可用 ——
       WebView2 的 AreBrowserAcceleratorKeysEnabled=False 会吞掉默认复制，这里整段接管。
       归属判定用**容器**而不是逐个文本类，一次覆盖名称/编码/介绍/详细信息/链接文字。 */
    const COPY_ON_CTRL_C_SELECTORS = '.bubble, .ai-think-body, .ai-messages, .detail-wrap';
    function onGlobalCopy(event) {
      if (!event.ctrlKey || event.altKey || event.shiftKey || event.metaKey) return;
      if (String(event.key || '').toLowerCase() !== 'c') return;
      if (event.isComposing || event.keyCode === 229) return;
      const active = document.activeElement;
      /* 输入控件里的复制归原生（见上面那条边界注释） */
      if (active && active !== document.body && isEditableTarget(active)) return;
      const sel = window.getSelection && window.getSelection();
      if (!sel || sel.isCollapsed) return;
      const text = String(sel.toString() || '');
      if (!text.trim()) return;
      /* 选区必须在气泡里；不在（比如选中了一段设置页说明文字）就别接管。
         ⚠️ 锚点+焦点两头都查：跨元素的选区 anchorNode 和 focusNode 可能落在不同子树，
            只查一头会漏判（漏判的后果是这条复制悄悄不生效）。 */
      const inBubble = [sel.anchorNode, sel.focusNode].some((node) => {
        try {
          const el = node && (node.nodeType === 1 ? node : node.parentElement);
          return !!(el && el.closest && el.closest(COPY_ON_CTRL_C_SELECTORS));
        } catch (e) { return false; }
      });
      if (!inBubble) return;
      event.preventDefault();
      event.stopPropagation();
      copyText(text);
    }

    /* ---------- 真数据 ---------- */
    const items = ref([]);
    const loading = ref(true);
    const loadError = ref('');
    const folders = ref([]);
    const notices = ref([]);
    const noticesLoading = ref(false);
    const noticesError = ref('');
    const readIds = ref(readLocal('readNotices', []));
    /* ⚠️ 公告的已读标识用 GitHub issue 的**编号**（#1 / #2 那种），
       不是数据库 id（内部主键，用户在界面上根本认不出来）。
       → 后端 announcements.json 里记的也是编号，两边一致。
       ⚠️ 兼容：老缓存里存的是数据库 id —— 这里两个都认
          （读的时候任一命中就算已读），所以升级后不会全部变未读。 */
    function noticeKey(notice) {
      const n = notice || {};
      const num = Number(n.number);
      if (Number.isFinite(num) && num > 0) return num;
      const id = Number(n.id);
      return Number.isFinite(id) ? id : 0;
    }
    function isReadKey(key) {
      const value = Number(key);
      if (!value) return false;
      if (readIds.value.indexOf(value) >= 0) return true;
      /* 兼容老缓存：数据库 id 也算已读 */
      return (notices.value || []).some((n) => Number(n.id) === value
        && readIds.value.indexOf(Number(n.id)) >= 0);
    }
    /* 首页海报列表（posters）随首页一起移除，这里不再声明。 */
    const apiKeyConfigured = ref(false);
    const unread = computed(() => notices.value.filter((n) => !isReadKey(noticeKey(n))));
    const unreadCount = computed(() => (unread.value.length > 99 ? '99+' : String(unread.value.length)));

    function mapItem(raw) {
      const name = pickI18n(raw.name, '');
      const iconName = raw.icon ? String(raw.icon).split(/[\\/]/).pop() : '';
      const description = pickI18n(raw.description, '');
      const intro = pickI18n(raw.intro, '');
      const category = Array.isArray(raw.category) ? raw.category : (raw.category ? [raw.category] : []);
      const tags = Array.isArray(raw.tags) ? raw.tags : (raw.tags ? [raw.tags] : []);
      /* 并集字段（task-6 后端契约）：三种语言池里出现过的**全部规范值**。
         · 显示/分组用 category/tags（= 当前界面语言那一份）；
         · 筛选候选、关键词匹配、喜好计数用 category_all/tags_all
           —— 否则"只在 English 池里填了「网络」"的条目在简体界面搜不到。
         ⚠️ 后端没给这两个字段时（旧后端/云端镜像）回退到 category/tags 本身，
            行为与改动前完全一致（向后兼容，不赌后端先上线）。 */
      const categoryAll = Array.isArray(raw.category_all) ? raw.category_all : category;
      const tagsAll = Array.isArray(raw.tags_all) ? raw.tags_all : tags;
      return {
        id: raw.id || raw.code || name,
        code: raw.code || raw.id || '',
        name,
        description: description || String(intro).split(/[。\n]/)[0] || '',
        intro,
        supplement: pickI18n(raw.supplement, ''),
        guide: pickI18n(raw.guide || raw.details, ''),
        category,
        tags,
        category_all: categoryAll,
        tags_all: tagsAll,
        icon: iconName ? (/^https?:/i.test(String(raw.icon)) ? String(raw.icon)
          : '/res/image/icon/' + encodeURIComponent(iconName)) : '',
        url: raw.url || '', github: raw.github || '', download_url: raw.download_url || '',
        /* 多组开源仓库：压成 [{platform, url}] 纯文本列表 —— 详情页要逐行列出来，
           列表页那一列要显示「第一组 +N」。老数据没有 repos 时为空数组，
           repoRowsFor 会退回 github 那一条。 */
        repos: (Array.isArray(raw.repos) ? raw.repos : [])
          .map((row) => (row && typeof row === 'object' && row.url
            ? { platform: String(row.platform || 'custom'), url: String(row.url) } : null))
          .filter(Boolean),
        /* 下载**页面**的网址（用户填的下载地址= 下载页的网页地址，
           和 download_url（安装包直链）是两种语义）。 */
        download_page_url: raw.download_page_url || '',
        author_url: raw.author_url || '', chat_url: raw.chat_url || '',
        /* 自定义链接：这里就按当前界面语言压成 {label, url} 纯文本，
           详情页与卡片只管显示，不必再判字典/字符串两种形态。 */
        links: (Array.isArray(raw.links) ? raw.links : [])
          .map((row) => (row && typeof row === 'object'
            ? { label: pickI18n(row.label, ''), url: pickI18n(row.url, '') } : null))
          .filter((row) => row && row.label && /^https?:\/\//i.test(row.url)),
        listed_at: raw.listed_at || '',
        systems: Array.isArray(raw.systems) ? raw.systems : (raw.systems ? [raw.systems] : []),
        /* 本轮删除 CPU 架构（用户：「删除所有的CPU架构……卡片ui界面里面的详细信息的
           CPU 架构都要删除」）：数据文件里的 architectures 已删，这里不再解析 ——
           留一个恒为 [] 的字段只会让后面每一处过滤/详情都要写"它永远是空的"注释。 */
        variants: Array.isArray(raw.variants) ? raw.variants : [],
        default_variant: raw.default_variant || '',
        _fav: false, _sel: false,
      };
    }

    async function loadSettings() {
      const result = await bridge.tryCall('settings.get');
      if (result && result.ok && result.settings) Object.assign(settings, result.settings);
      /* ⚠️ 本轮（修"启动瞬间深色再跳回浅色"）：真实设置到手，isDark 从此由
         settings.theme 决定。必须放在 applyAppearance() **之前**，
         否则这一次重画还是沿用首帧深浅、白跑一趟。
         注意 tryCall 失败（浏览器模式 / 后端未就绪）时 result 为 null，
         这里保持 false → isDark 继续用首帧值，不会退回"跟系统"再变一次。 */
      if (result && result.ok && result.settings) settingsLoaded.value = true;
      /* 旧配置里 search_source / download_source 可能是空串（历史默认值就是空），
         空串会让下拉框显示空白 —— 需求：默认选中 Github。 */
      if (!String(settings.search_source || '').trim()) settings.search_source = 'Github';
      if (!String(settings.download_source || '').trim()) settings.download_source = 'Github';
      applyAppearance();
    }
    async function loadResources() {
      /* ⚠️⚠️ 需求（用户原话）：「所有云端 ToolsGCP-Resources.json 加载或本地加载
         ToolsGCP-Resources.json 应该显示在**搜索页或者定制页的空白处**显示这个加载 UI，
         而不是显示在启动页上」。
         → 所以**本地**资源库加载时也要亮同一块"页面内"的加载 UI
           （云端那条路在 continueBoot 里已经亮了）。
         ⚠️ ⚠️ **状态归属**要搞清楚，否则会互相打架：
           · continueBoot（云端启动路径）自己管 resourceLoading —— 它要在
             cloud_prepare 期间一直亮着，中间不能被这里关掉；
           · 所以这里**只在自己把灯点亮**的情况下才负责关。
           → 用一个局部标记 `own` 记录"是不是我点的灯"：
             已经亮着（云端路径）→ own=false → 这里不关，交给 continueBoot 关；
             没亮（纯本地路径）→ own=true → 这里负责关。
         ⚠️ loadingDots 是共享的动态点，start/stop 必须成对。 */
      const own = !resourceLoadingActive();
      if (own) {
        showResourceLoadingSoon();
        resourceLoadFailed.value = false;
      }
      loading.value = true;
      loadError.value = '';
      resetIconRetries();                    // 资源库重载 → 图标重试次数清零，重新给一次机会
      let result = null;
      try {
        result = await bridge.tryCall('resources.all');
      } finally {
        loading.value = false;
        /* ⚠️ 只关"自己点的灯"（云端路径的灯归 continueBoot 管）*/
        if (own) hideResourceLoading();
      }
      if (result && result.ok && Array.isArray(result.items)) items.value = result.items.map(mapItem);
      else {
        /* ⚠️ 本轮英文扫描抓到的真漏翻：这两个兜底文案硬编码中文，
           会和 1889 行 t('resource_load_failed') 的英文整句拼成中英混排。 */
        loadError.value = (result && result.error)
          || (bridge.ready ? t('resource_load_failed_plain', '资源库读取失败')
            : t('resource_api_not_ready', '桌面端接口未就绪（{api}）').replace('{api}', 'resources.all'));
        items.value = [];
      }
      /* ⚠️ 收藏页"空心星"的根因（本文件 ~1509 行注释里承诺的"任何收藏变化后都必须
         syncFavoriteState"，唯独漏了**资源库重建**这一条路）：
         mapItem 把每个新对象都初始化成 `_fav:false`，重启后（以及云端后台刷新
         cloud.refresh.done → loadResources 时）items 整批换新，而 folders.value
         （后端 favorites.list 的结果）此时早已在内存里 —— 旧代码只有 loadFavorites
         会重算 _fav，这条路上没人调用 → favItems（从 items 筛出来的收藏页卡片）
         永远拿到 false → 星星空心。资源库一旦重建必须立刻按收藏夹重算一遍。 */
      syncFavoriteState();
      const status = await bridge.tryCall('resources.status');
      if (status && status.ok && status.source) info.resourceFile = status.source;
      await refreshLatest();
      await runQuery();
    }
    /* ---------- 收藏状态的唯一真源 ----------
       同一个 code 在页面里有四份对象：items（资源库全集）、filtered（查询结果）、
       groups[].items（卡片真正渲染的那份）、detail（详情页副本）；收藏页 favItems
       又是从 items 里筛出来的。以前各处只改自己那份 `_fav` —— 导入完成后收藏页星星
       不亮、点一下反而"取消收藏"把卡片弄没，根子就是这几份不同步。
       现在统一以 folders.value（后端 favorites.list 的结果）为准重算，
       任何收藏变化（toggle / 导入 / 移动 / 后端 favorites-changed 推送）后都必须调用。 */
    function favoriteCodeSet() {
      return new Set((folders.value || []).flatMap((f) => f.items || []));
    }
    function syncFavoriteState() {
      const codes = favoriteCodeSet();
      const apply = (it) => { if (it && it.code) it._fav = codes.has(it.code); };
      items.value.forEach(apply);
      filtered.value.forEach(apply);
      (groups.value || []).forEach((g) => (g.items || []).forEach(apply));
      if (detail.value) apply(detail.value);
      return codes;
    }
    /* favorites.list 不可用时的兜底：只按单条 toggle 的返回值同步该 code，
       避免"接口缺失 → 星星点了完全没反应"。 */
    function syncFavoriteByCode(code, fav) {
      const apply = (it) => { if (it && it.code === code) it._fav = !!fav; };
      items.value.forEach(apply);
      filtered.value.forEach(apply);
      (groups.value || []).forEach((g) => (g.items || []).forEach(apply));
      if (detail.value) apply(detail.value);
    }
    async function loadFavorites() {
      /* 显式带上界面语言：收藏夹的显示名由后端 display_folder_name() 决定
         （真名恒为 "Default"，显示要跟着设置里的语言走）。不传就退化成后端
         自己记的语言 —— 桌面端一般一致，但**切语言的那一刻**后端可能还没刷
         新到这份数据，界面上就会出现「English 界面却写着「默认收藏夹」」。 */
      const result = await bridge.tryCall('favorites.list', uiLanguage());
      if (!result || !result.ok) return false;
      folders.value = (result.folders || []).map((f) => ({ ...f, label: f.label || f.name }));
      syncFavoriteState();
      /* 收藏数据是**异步**回来的 → 网格可能在这之后才出现。
         ⚠️ task-3 ①：列数现在由 @vue:mounted（收藏页滚动容器插入时）先量后渲染保证，
         这里只是**补量**：favScroller 还没挂载时它是空操作（值为 null）。 */
      nextTick(() => { if (page.value === 'favorites') measureFavGrid(); });
      return true;
    }

    /* ===================== 搜索页 ===================== */
    const keyword = ref('');
    const applied = ref('');
    const sortKey = ref('category');                       // 原版 setCurrentIndex(1) = 类别
    const filterOpen = ref(false);
    const chevronDeg = ref(0);
    const filters = reactive({ category: [], tag: [], source: [], favorite: [],
                               updated: [], system: [] });
    const latestCodes = ref(new Set());
    const groups = ref([]);
    const filtered = ref([]);
    const totalCount = ref(0);
    const searchScroll = ref(null);
    const detailScroll = ref(null);
    const vlist = ref(null);
    const searchInput = ref(null);
    /* ---------- 列表动画策略（需求 ④） ----------
       1) 卡片入场动画**恢复**，但只在"本次会话第一次出结果"时播一次；
          之后切页面 / 从任务栏还原窗口重绘 DOM 时**不会**再播（之前就是全局 animation，
          导致每次窗口恢复都整屏重放）。
       2) 类别 / 视图切换时，给列表容器一个轻量的淡入上移，表示"内容换了一批"。
       实现：容器加类名，播完立刻摘掉；不依赖 animation 的 both 状态残留。 */
    const listAnim = ref('');
    let listAnimTimer = 0;
    function playListAnim(name, ms) {
      clearTimeout(listAnimTimer);
      listAnim.value = '';                    // 先摘掉，强制重启动画
      nextTick(() => {
        listAnim.value = name;
        listAnimTimer = setTimeout(() => { listAnim.value = ''; }, ms);
      });
    }
    /* 第一次出结果时播一次卡片入场（runQuery 首次完成后调用） */
    let cardAnimPlayed = false;
    function playFirstCardsAnim() {
      if (cardAnimPlayed) return;
      cardAnimPlayed = true;
      playListAnim('cards-anim', 420);
    }
    /* ⚠️ 必须延迟到 onMounted 再注册 watch：
       这里（setup 执行到本行时）`viewMode` / `selectionBar` 还没声明，
       直接 watch([sortKey, viewMode]) 会触发 TDZ ReferenceError → 整个 setup 抛错 → 白屏。 */
    onMounted(() => {
      watch([sortKey, viewMode],
        () => { if (!selectionBar.value) playListAnim('switch-anim', 300); });
    });
    const scrollTop = ref(0);
    const viewW = ref(1200);
    const viewH = ref(600);
    const panelH = ref(0);
    /* ⚠️ .vlist 在滚动容器**内容**里的起始偏移（task-3 ⑤ 的根因）：
       行坐标（rowModel 的 top）是相对 .vlist 的，而 .vlist 上面还压着
       搜索框行 + 工具栏行 + **展开的筛选面板** + 选择条。
       旧代码把 scrollTop 直接当行坐标用 → 窗口上边界比真实可视区高出 vlistTop 像素；
       筛选面板一展开（+400px 左右），顶部两三行卡片**还在屏幕上**就被裁掉，
       表现就是"更多筛选打开时往下滚，卡片没出视野就凭空消失"。 */
    const vlistTop = ref(0);

    const autoSearch = computed(() => settings.auto_search !== false);
    const viewMode = computed(() => settings.search_view || 'tile');
    const cardPx = computed(() => {                     // app_card._recompute_sizes：×0.76 / ×0.62
      const preset = CARD_PRESETS[settings.search_card_size] || CARD_PRESETS.medium;
      if (viewMode.value === 'grid') {
        return { height: Math.max(120, Math.round(preset.height * 0.76)),
          icon: Math.max(30, Math.round(preset.icon * 0.62)),
          lines: preset.lines, button: preset.button, buttonIcon: preset.buttonIcon };
      }
      return { ...preset };
    });
    const sortOptions = computed(() => ([
      { value: 'all', label: t('sort_all', '全部') },
      { value: 'category', label: t('sort_category', '类别') },
      { value: 'az', label: t('sort_az', 'A-Z') },
      { value: 'za', label: t('sort_za', 'Z-A') },
      /* 需求：在 Z-A 下面新增两档（本地筛选，见 localQuery） */
      { value: 'fav', label: t('sort_fav', '已收藏') },
      { value: 'unfav', label: t('sort_unfav', '未收藏') },
    ]));

    /* 选项优先取后端 filter_options（值 = 规范中文，显示名 = 译名），拿不到再本地算 */
    const remoteOptions = ref(null);
    /* ⚠️ 候选的 label 是**后端按传入语言翻好**送来的（desktop/api/resources.py:1270
       def filter_options(self, language: str = "") —— 不传则用 shell.current_language()），
       以前只在启动时拉一次且不传语言 ⇒ 设置里切到 English 后，「更多筛选」里
       类别 / 标签 / 系统三组候选仍是简体中文（其余几组是前端 t() 文案，会跟着变），
       看起来就像"只有三个字没翻"。所以：拉取时显式带上界面语言，切语言后重拉。
       值（value）永远保持规范中文，只有 label 本地化 —— 与后端约定一致，不要改。 */
    async function loadFilterOptions() {
      const options = await bridge.tryCall('resources.filter_options', uiLanguage());
      /* tryCall 返回 null = 后端没这个接口 ⇒ 显式降级：filterRows 走本地算出来的候选 */
      if (options && options.ok) remoteOptions.value = options;
    }
    const filterRows = computed(() => {
      const all = { value: '', label: t('filter_all', '全部') };
      const remote = remoteOptions.value;
      const cats = [];
      const seenCat = new Set();
      const tags = new Set();
      /* 候选值取**并集**（category_all/tags_all）：这样"只在 English 池里填了「网络」"
         的条目，在简体中文界面下也能从下拉里选到「网络」。
         ⚠️ 并集之后还要**折成规范中文值**再进候选（第五轮需求③）：新表单三个语言池各填
            各的写法，不折叠就会出现「游戏平台 / 遊戲平台 / Game platform 三项并列，
            简体中文界面里后两项显示为外文」。后端 filter_options 已按同一口径折叠，
            这里照做是**兜底**：浏览器模式（serve.py 的 mock）没有 filter_options，
            老后端与云端直连也不会折叠，只改后端会把这些场景漏在外面。
         显示仍走 term()（值恒为规范中文，翻不翻都由界面语言决定）。 */
      const pushCanon = (bag, value) => {
        const canon = canonicalAny(value);
        if (!canon || seenCat.has(canon)) return;
        seenCat.add(canon);
        bag.push(canon);
      };
      items.value.forEach((it) => {
        (it.category_all || it.category).forEach((c) => pushCanon(cats, c));
        (it.category_all || it.category).concat(it.tags_all || it.tags || [])
          .forEach((k) => tags.add(canonicalAny(k)));
      });
      const ordered = CATEGORY_ORDER.filter((c) => cats.indexOf(c) >= 0)
        .concat(cats.filter((c) => CATEGORY_ORDER.indexOf(c) < 0));
      const list = (values) => [all].concat(values.map((v) => ({ value: v, label: term(v) })));
      /* 远端候选同样折叠 + 去重（canon=true 只给类别/标签用）。
         label 优先用前端 term()：它跟着界面语言实时重算，切语言后到重拉落地的
         那一小段时间里不会残留旧语言的写法；术语表查不到才用后端给的 label。
         ⚠️「适用系统」必须 canon=false —— 系统名不在术语表里、后端也没折叠它，
            折了会把 value 改成对不上号的字符串，筛选直接失效（系统那组走另一张表）。 */
      const fromRemote = (key, fallbackList, canon) => {
        if (!(remote && Array.isArray(remote[key]) && remote[key].length)) return fallbackList;
        const seen = new Set();
        const out = [];
        remote[key].forEach((o) => {
          const raw = String((o && o.value != null) ? o.value : '');
          const value = canon ? canonicalAny(raw) : raw;
          if (!value) return;
          if (canon) {
            if (seen.has(value)) return;
            seen.add(value);
          }
          const localized = term(value);
          const backend = (o && o.label) || '';
          out.push({
            value,
            label: canon ? (localized !== value ? localized : (backend || value))
              : (backend || localized || value),
          });
        });
        return [all].concat(out);
      };
      return [
        { key: 'category', label: t('filter_category', '类别'),
          options: fromRemote('category', list(ordered), true) },
        { key: 'tag', label: t('filter_tag', '标签'), options: fromRemote('tag', list(Array.from(tags).sort()), true) },
        { key: 'source', label: t('filter_source', '来源'), options: [all,
          { value: 'site', label: t('source_site', '有官网') },
          { value: 'repo', label: t('source_repo', '有代码仓库') },
          { value: 'download', label: t('source_download', '可自动下载') }] },
        { key: 'favorite', label: t('filter_favorite', '收藏'), options: [all,
          { value: 'only', label: t('favorite_only', '仅看收藏') }] },
        { key: 'updated', label: t('filter_updated', '更新时间'), options: [all,
          { value: 'latest', label: t('updated_latest', '最新') },
          { value: '10d', label: t('updated_10d', '10 天前') },
          { value: '30d', label: t('updated_30d', '30 天前') },
          { value: '180d', label: t('updated_180d', '半年前') }] },
        { key: 'system', label: t('filter_system', '适用系统'), options: fromRemote('system', list(SYSTEMS)) },
      ];
    });

    /* ★ 本轮新增（只给定制页用，搜索页继续用 filterRows —— 用户明确「不要改错了，
       只更改制页的而不是搜索页的」）：定制页的「更多筛选」里，类别 / 标签的候选必须
       **只列资源库里真实存在的值**。
       filterRows 的候选来自 items 并集 **+ 后端 filter_options 的并集**，而后者可能带上
       资源库里已经一条都没有的陈旧值（资源删过、语言池改过）→ 选它必然 0 结果。
       这里按 items 实际值把这两组再过一遍（值已在 filterRows 里折成规范中文，
       所以直接用 same-value 比对即可），其余行（来源/收藏/更新时间/适用系统）原样透传。 */
    const customFilterRows = computed(() => {
      const present = new Set();
      const add = (v) => { const canon = canonicalAny(v); if (canon) present.add(canon); };
      items.value.forEach((it) => {
        (it.category_all || it.category || []).forEach(add);
        (it.tags_all || it.tags || []).forEach(add);
      });
      return filterRows.value.map((row) => {
        if (row.key !== 'category' && row.key !== 'tag') return row;
        /* 第一项是「全部」（value 为空）永远保留 */
        return Object.assign({}, row, { options: row.options.filter((o) => !o.value || present.has(o.value)) });
      });
    });

    /* 本地兜底：与 resource_query.py 逐条对齐（后端在时不会被用到） */
    function matchKeyword(item, value) {
      const key = String(value || '').trim().toLowerCase();
      if (!key) return true;
      const digits = (key.match(/\d/g) || []).join('');
      const code = String(item.code || '').toLowerCase();
      if (code.indexOf(key) >= 0) return true;
      if (digits && code.replace(/\D/g, '').indexOf(digits) >= 0) return true;
      if (String(item.id || '').toLowerCase() === key) return true;
      if (String(item.name || '').toLowerCase().indexOf(key) >= 0) return true;
      if (String(item.description || '').toLowerCase().indexOf(key) >= 0) return true;
      /* 并集：英文池里独有的类别/标签也要能被关键词搜到 */
      return (item.category_all || item.category)
        .concat(item.tags_all || item.tags || [])
        .some((k) => String(k).toLowerCase().indexOf(key) >= 0);
    }
    function passesFilters(item, state) {
      const f = state || filters;
      /* 筛选值恒为规范中文（来自并集候选），所以这里也用并集比对：
         用户在简体界面选「网络」，条目只在 English 池里填了它，同样应该命中。 */
      /* 两侧都折成规范中文值再比（与后端 passes_filters 的 category/tags 分支同口径）：
         候选是规范值，而条目可能写着三种语言里的任一写法（新表单各池独立填的），
         只折一侧会"选了「游戏平台」却筛不出只在 English 池填 Game platform 的条目"。 */
      const wantCats = f.category.map(canonicalAny);
      const itemCats = (item.category_all || item.category).map(canonicalAny);
      if (wantCats.length && !itemCats.some((c) => wantCats.indexOf(c) >= 0)) return false;
      if (f.tag.length) {
        const wantTags = f.tag.map(canonicalAny);
        const keys = itemCats.concat((item.tags_all || item.tags || []).map(canonicalAny));
        if (!wantTags.some((v) => keys.indexOf(v) >= 0)) return false;
      }
      if (f.source.length) {
        const repo = !!item.github, download = !!item.download_url || repo, site = !!item.url;
        if (!((f.source.indexOf('repo') >= 0 && repo)
          || (f.source.indexOf('download') >= 0 && download)
          || (f.source.indexOf('site') >= 0 && site))) return false;
      }
      if (f.favorite.indexOf('only') >= 0 && !item._fav) return false;
      if (f.updated.length) {
        const mode = f.updated[0];
        if (mode === 'latest') {
          if (latestCodes.value.size && !latestCodes.value.has(item.code)) return false;
        } else {
          const days = UPDATED_DAYS[mode];
          if (days == null) return true;               // ⚠️ 原版在这里直接 return True
          const stamp = parseDate(item.listed_at);
          if (stamp == null) return false;
          if (Math.floor((Date.now() - stamp) / 86400000) > days) return false;
        }
      }
      if (f.system.length) {
        if (!item.systems.length) return false;
        const values = item.systems.map((v) => String(v).toLowerCase());
        if (!f.system.some((v) => values.indexOf(String(v).toLowerCase()) >= 0)) return false;
      }
      return true;
    }
    function categoryGroups(list) {
      const map = new Map();
      list.forEach((it) => {
        const cats = (it.category && it.category.length) ? it.category : [FALLBACK_CATEGORY];
        cats.forEach((c) => { if (!map.has(c)) map.set(c, []); map.get(c).push(it); });
      });
      const ordered = CATEGORY_ORDER.filter((c) => map.has(c))
        .concat(Array.from(map.keys()).filter((c) => CATEGORY_ORDER.indexOf(c) < 0));
      return ordered.map((c) => ({ key: c, title: term(c) + t('group_suffix', '：'),
        items: map.get(c), count: map.get(c).length }));
    }
    function letterGroups(list, reverse) {
      const map = new Map();
      list.forEach((it) => {
        const head = String(it.name || '').trim().slice(0, 1).toUpperCase() || '#';
        const key = /^[A-Z]$/.test(head) ? head : '#';
        if (!map.has(key)) map.set(key, []);
        map.get(key).push(it);
      });
      let keys = Array.from(map.keys()).filter((k) => k !== '#').sort();
      if (reverse) keys = keys.reverse();
      if (map.has('#')) keys.push('#');
      return keys.map((k) => {
        let values = map.get(k).slice().sort((a, b) =>
          String(a.name || '').toLowerCase().localeCompare(String(b.name || '').toLowerCase()));
        if (reverse) values = values.reverse();
        return { key: k, title: k + t('group_suffix', '：'), items: values, count: values.length };
      });
    }
    function localQuery() {
      const list = items.value.filter((it) => matchKeyword(it, applied.value) && passesFilters(it));
      filtered.value = list;
      totalCount.value = list.length;
      if (!list.length) { groups.value = []; return; }
      if (sortKey.value === 'category') groups.value = categoryGroups(list);
      else if (sortKey.value === 'az') groups.value = letterGroups(list, false);
      else if (sortKey.value === 'za') groups.value = letterGroups(list, true);
      else if (sortKey.value === 'fav' || sortKey.value === 'unfav') {
        /* 新增排序：已收藏 / 未收藏（需求：排在 Z-A 下面）。
           这两档是**前端本地筛选**：后端 resources.query 没有这个 sort_key，
           传下去只会被当成未知排序。筛完不再分组，按名称排一遍。 */
        const want = sortKey.value === 'fav';
        const picked = list.filter((it) => !!it._fav === want)
          .slice().sort((a, b) => (String(a.name) < String(b.name) ? -1 : (String(a.name) > String(b.name) ? 1 : 0)));
        filtered.value = picked;
        totalCount.value = picked.length;
        groups.value = picked.length ? [{ key: 'all', title: '', items: picked, count: picked.length }] : [];
        return;
      }
      else groups.value = [{ key: 'all', title: '', items: list, count: list.length }];
    }
    /* 真正的过滤/排序/分组走后端（算法唯一真源），拿不到才退本地 */
    async function runQuery() {
      /* 已收藏 / 未收藏：后端没有这两个 sort_key，直接走本地筛选，避免多跑一次请求 */
      if (sortKey.value === 'fav' || sortKey.value === 'unfav') { localQuery(); return; }
      const result = await bridge.tryCall('resources.query', applied.value,
        { ...filters }, sortKey.value, false, true);
      if (!result || !result.ok) { localQuery(); return; }
      const favCodes = favoriteCodeSet();
      const list = (result.items || []).map(mapItem);
      list.forEach((it) => { it._fav = favCodes.has(it.code); });
      /* 后端复用同一批对象，这里把交互标记合并回去，保持卡片状态不丢 */
      const byCode = new Map(items.value.map((it) => [it.code, it]));
      list.forEach((it) => {
        const old = byCode.get(it.code);
        /* _fav 以后端收藏夹为唯一真源（旧代码 `old._fav || it._fav` 会把已取消的
           收藏又"复活"成 true，表现为取消失败 / 星星常亮）。只合并交互选择状态。 */
        if (old) { it._sel = old._sel; }
      });
      filtered.value = list;
      totalCount.value = result.total != null ? result.total : list.length;
      groups.value = (result.groups || []).map((g) => ({
        key: g.canonical || g.title || 'all',
        title: g.title ? g.title + t('group_suffix', '：') : '',
        items: (g.items || []).map((raw) => {
          const mapped = mapItem(raw);
          const old = byCode.get(mapped.code);
          mapped._fav = favCodes.has(mapped.code);
          mapped._sel = old && old._sel;
          return mapped;
        }),
        count: g.count,
      }));
      playFirstCardsAnim();          /* 本次会话第一次出结果：播一次卡片入场 */
      nextTick(() => { panelHeight(); requestAnimationFrame(measureViewport); });
    }
    async function refreshLatest() {
      const result = await bridge.tryCall('resources.refresh_latest');
      if (result && result.ok) latestCodes.value = new Set(result.codes || []);
      else {
        const rows = items.value.map((it) => ({ code: it.code, stamp: parseDate(it.listed_at) }))
          .filter((r) => r.stamp != null).sort((a, b) => (b.stamp - a.stamp)
            || String(b.code).localeCompare(String(a.code))).slice(0, LATEST_N);
        latestCodes.value = new Set(rows.map((r) => r.code));
      }
    }
    const resultText = computed(() =>
      t('result_count', '已搜索到 {n} 个相关内容').replace('{n}', filtered.value.length));
    const emptyText = computed(() => {
      if (loadError.value) return t('resource_load_failed', '资源库加载失败：') + loadError.value;
      if (keyword.value.trim() && !applied.value.trim()) return t('search_enter', '按回车或点搜索按钮');
      return t('search_no_result', '没有匹配的资源，换个关键词或清掉筛选试试。');
    });

    /* ---------- 虚拟列表：布局算法照 responsive_grid.layout_metrics ---------- */
    const cfg = computed(() => (viewMode.value === 'grid' ? GRID : TILE));
    const availW = computed(() => Math.max(0, viewW.value - PAGE_MARGIN * 2 - 8));
    const layout = computed(() => {
      const avail = availW.value, spacing = cfg.value.spacing;
      if (avail <= 0 || !filtered.value.length) return { columns: 0, itemW: 0, gap: spacing };
      let columns = Math.max(1, Math.floor((avail + spacing) / (cfg.value.minW + spacing)));
      const cap = Math.max(cfg.value.base, Math.ceil(avail / cfg.value.maxCardW));
      columns = Math.max(1, Math.min(columns, cap));
      const usable = avail - spacing * (columns - 1);
      const itemW = Math.floor(usable / columns);
      const remainder = usable - itemW * columns;         // 余数摊给**间距**：等宽 + 左右留白相等
      const gap = columns > 1 ? spacing + remainder / (columns - 1) : spacing;
      return { columns, itemW, gap };
    });
    /* ⚠️ 本轮删除 FOOT_LINKS_H / rowNeedsLinks（卡片"多一行下载页按钮"的加高逻辑）。
       需求原话：「删除搜索页或定制页的MT管理器上的卡片ui中的那个下载按钮，我估计是我
       之前和agent提了这个要求但是它只隐藏了固定软件有这个按钮的东西并没有按我要求删除
       这个页面上的这个按钮（只删除按钮按钮和相关的东西关于这个按钮的，不删除进入页面
       里面的下载地址部分）」。
       核实结论：上一轮 agent 确实**删了旧的 Releases/下载按钮，却又新增了这颗
       "打开下载页面"按钮**（搜索页/定制页/收藏页三处都有），等于没删。
       本轮把三处模板、这段行高补偿、r22-fixes.css 的 .card-foot-links、i18n 文案键
       一起删干净 —— 行高必须跟着删：虚拟列表的 height 是 JS 算的确定值，
       按钮没了还多留 32px，卡脚下方就会空出一条。
       ⚠️ 只删**卡片上**的入口：详情页"详细信息"里的「下载地址」行（detailRows 的
       row_download_page）按用户要求**保留**，Releases 入口也保留在详情页顶栏。 */
    const rowModel = computed(() => {
      const cols = Math.max(1, layout.value.columns || 1);
      const baseH = cardPx.value.height;
      const rows = [];
      let y = 0, seed = 0;
      groups.value.forEach((group) => {
        const list = group.items || [];
        if (!list.length) return;
        if (group.title) {
          rows.push({ type: 'group', key: 'g' + (seed++), title: group.title, top: y, height: GROUP_H });
          y += GROUP_H;
        }
        for (let i = 0; i < list.length; i += cols) {
          const slice = list.slice(i, i + cols);
          const rowH = baseH;
          rows.push({ type: 'items', key: 'r' + (seed++), items: slice,
            top: y, height: rowH, itemW: layout.value.itemW, gap: layout.value.gap });
          y += rowH + cfg.value.spacing;
        }
        y += Math.max(0, GROUP_GAP - cfg.value.spacing);
      });
      const last = rows[rows.length - 1];
      return { rows, total: last ? last.top + last.height + 30 : 0 };
    });
    const vTotal = computed(() => rowModel.value.total);
    function firstRowIndex(rows, y) {
      let lo = 0, hi = rows.length - 1, ans = rows.length;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (rows[mid].top + rows[mid].height >= y) { ans = mid; hi = mid - 1; } else { lo = mid + 1; }
      }
      return Math.max(0, ans);
    }
    const OVERSCAN = 3;
    const vRows = computed(() => {
      const rows = rowModel.value.rows;
      if (!rows.length) return [];
      /* ⚠️ 可视区换算到**行坐标系**：行 top 是相对 .vlist 的，
         所以窗口上下边界都要先减掉 vlistTop（.vlist 在滚动内容里的起始偏移）。
         筛选面板展开 → vlistTop 变大 → 窗口跟着下移，顶部卡片不再"提前消失"。 */
      const top = Math.max(0, scrollTop.value - vlistTop.value);
      const bottom = top + Math.max(1, viewH.value);
      const start = Math.max(0, firstRowIndex(rows, top) - OVERSCAN);
      const rowH = cardPx.value.height;
      let end = start;
      while (end < rows.length && rows[end].top <= bottom + OVERSCAN * rowH) end += 1;
      return rows.slice(start, Math.min(rows.length, end + OVERSCAN));
    });
    let rafId = 0;
    /* 需求：进详情再返回，必须回到原来的滚动位置，而且卡片不能消失。
       根因：详情打开时搜索页的 <section> 会被 v-if 卸载，.page-scroll 是**新元素**
       （scrollTop=0），但虚拟列表的 scrollTop.value 还停在旧值 → 渲染窗口算在旧位置，
       于是"界面上什么都没有，滚一下才出现"。这里把两端一起同步。 */
    let detailScrollMemory = 0;
    function currentScrollEl() {
      return document.querySelector('.page-scroll');
    }
    function syncScrollTop(force) {
      const el = searchScroll.value || currentScrollEl();
      if (!el) return;
      measureViewport();
      if (force != null) el.scrollTop = force;
      scrollTop.value = el.scrollTop;
    }
    function onScrollArea() {                          // 整页只有一个滚动容器（原版 QScrollArea）
      const el = searchScroll.value;
      if (!el) return;
      if (rafId) return;
      /* ⚠️ task-3 ⑤：每帧顺手刷新 vlistTop —— 筛选面板是 180ms 的 max-height 过渡，
         期间偏移一直在变；只靠 toggleFilter 里补一次会量到过渡中途的旧值。
         offsetTop 读一次的成本和已经在读的 scrollTop 同级，可接受。 */
      rafId = requestAnimationFrame(() => {
        rafId = 0;
        measureVlistTop();
        scrollTop.value = el.scrollTop;
      });
    }
    /* 量 .vlist 在滚动容器内容坐标系里的起始偏移（task-3 ⑤）。
       用 rect 差值 + 当前 scrollTop 换算：行坐标（rowModel.top）是相对 .vlist 的，
       而 .page-scroll 不是任何元素的 offsetParent（它没有 position），
       所以 offsetTop 链**走不到它**，rect 法才是这里正确的算法。
       页面过渡用的是 translateX（animations.css .page-enter-from），不影响纵向 rect。 */
    function measureVlistTop() {
      const list = vlist.value;
      const el = searchScroll.value;
      if (!list || !el) return;
      const top = list.getBoundingClientRect().top - el.getBoundingClientRect().top
        + el.scrollTop - (el.clientTop || 0);
      const next = Math.max(0, Math.round(top));
      if (next !== vlistTop.value) vlistTop.value = next;
    }
    function measureViewport() {
      const el = searchScroll.value;
      if (!el) return;
      viewH.value = el.clientHeight;
      viewW.value = el.clientWidth;
      panelHeight();
      measureVlistTop();
    }
    function panelHeight() {
      const inner = document.querySelector('.filter-inner');
      panelH.value = inner ? inner.scrollHeight + 4 : 600;
    }
    function scrollToTop() {
      const el = searchScroll.value;
      if (el) el.scrollTop = 0;
      scrollTop.value = 0;
      /* 主动回顶（搜索/切视图）后必须同步清掉记忆，
         否则之后任何一次 restorePageScroll('search') 都会把旧位置"恢复"回来。 */
      pageScrollMemory.search = 0;
    }
    /* ---------- 卡片标签：放不下时把最后一个换成「+X」（task-14 重做） ----------
       需求（原话）：「标签放不下应该最后一个变为那个+x的标签，而不是放不下就把所有标签
       变为+x标签；或者明明超出边界还是强硬显示而不变为+x标签ui导致最后一个被遮挡住」。
       旧实现的两条病根，这次都治：
       ① 宽度靠估算（西文 0.54×字号）⇒ 估小就超边界被 .card{overflow:hidden} 裁字。
          现在用 **canvas measureText 实测**（字体串取 body 的 computed fontFamily +
          .tag 钉死的 11.5px；胶囊 .tag-more 是 font-weight:600，测它时用 600），
          按「显示文本」缓存 —— 键是 term() 之后的文本，切语言自动换键、互不污染；
          虚拟列表每帧重渲染不会重复测。
       ② 「+X」胶囊写死 40px ⇒ "+3" 和 "+12" 一样宽，位数一多就估小。
          现在胶囊宽度**按它自己的文本实算**（tagTextPx('+N', true) + tagMetrics().pad）。
       安全余量：实测值 +2px 再向上取整（浮点宽度的最后一像素是渲染器拿不准的半像素，
       宁可空 2px 也不能裁字）。无 canvas 的老内核退回**偏大**的估算（0.65 系数，
       方向反过来：估大只会少放一个标签，估小才会裁字 —— 取不裁字这一边）。 */
    /* ⚠️ 两个视图的 .tag 尺寸**不一样**（components.css）：
         · 磁贴 tile：font-size 11.5 / padding 0 10px / 行间 gap 6
         · 网格 grid：font-size 10.5 / padding 0 7px  / 行间 gap 4（.card.is-grid .tag）
       所以度量必须**跟着 computed 走**（任务要求「按 .tag 实际 computed 字体」）——
       拿磁贴的尺寸去量网格卡会整体偏大 ≈15%，表现就是"明明还放得下却提前变 +N"。
       优先从**真实渲染出来的** .tag / .card-foot > .row 上读；读不到（卡片还没挂过、
       或人在别的页面）退回与 CSS 逐条对齐的常量表。
       注意 fallback **不写进缓存**：下次卡片渲染出来后还能读到真值再升级。 */
    const TAG_METRIC_FALLBACK = {
      tile: { font: 11.5, pad: 20, gap: 6, family: '' },
      grid: { font: 10.5, pad: 14, gap: 4, family: '' },
    };
    const _tagMetrics = { tile: null, grid: null };
    function tagMode() { return viewMode.value === 'grid' ? 'grid' : 'tile'; }
    function tagMetrics() {
      const mode = tagMode();
      if (_tagMetrics[mode]) return _tagMetrics[mode];
      const m = { font: TAG_METRIC_FALLBACK[mode].font, pad: TAG_METRIC_FALLBACK[mode].pad,
                  gap: TAG_METRIC_FALLBACK[mode].gap, family: '' };
      let got = false;
      try {
        /* 直接按**选择器**取对应视图的那枚标签：网格卡带 .is-grid，磁贴卡没有 ⇒
           即使当前只显示其中一种视图，两种度量也都能各取到一次真值。 */
        const sel = mode === 'grid' ? '.card.is-grid .card-foot > .row > .tag'
                                    : '.card:not(.is-grid) .card-foot > .row > .tag';
        const el = document.querySelector(sel);
        if (el && window.getComputedStyle) {
          const cs = window.getComputedStyle(el);
          const fs = parseFloat(cs.fontSize);
          const pl = parseFloat(cs.paddingLeft) || 0;
          const pr = parseFloat(cs.paddingRight) || 0;
          if (fs > 0) { m.font = fs; got = true; }
          if (pl + pr > 0) m.pad = pl + pr;
          m.family = cs.fontFamily || '';
          const row = el.parentElement;
          const rcs = row && window.getComputedStyle(row);
          if (rcs) {
            const g = parseFloat(rcs.columnGap || rcs.gap || '');
            if (!isNaN(g)) m.gap = g;
          }
        }
      } catch (error) { /* 拿不到就用常量表 */ }
      if (got) _tagMetrics[mode] = m;          // 只有读到真值才长期缓存
      return m;
    }
    let _tagCtx = null;                        // null=未探测；false=没有 2d；否则是复用上下文
    function getTagMeasureCtx() {
      if (_tagCtx !== null) return _tagCtx;
      try {
        const c = document.createElement('canvas');
        _tagCtx = c.getContext('2d') || false;
      } catch (error) { _tagCtx = false; }
      return _tagCtx;
    }
    /* canvas 字体串：字号/字族取自 tagMetrics()（= 真 .tag 的 computed 值），
       bold=true 对应 .tag-more 的 font-weight:600。 */
    function tagFontSpec(bold) {
      const m = tagMetrics();
      const family = m.family || (() => {
        try { return window.getComputedStyle(document.body).fontFamily || 'sans-serif'; }
        catch (error) { return 'sans-serif'; }
      })();
      return (bold ? '600 ' : '') + m.font + 'px ' + family;
    }
    function tagEstimateWidth(text) {
      const f = tagMetrics().font;
      let width = 0;
      for (const ch of String(text || '')) width += (/[\u2E80-\uFFFF]/.test(ch) ? f : f * 0.65);
      return width;
    }
    const TAG_W_CACHE = new Map();             // '视图|R|文本' → 实测 px
    function tagTextPx(text, bold) {
      /* 缓存键**必须带视图**：磁贴 11.5px、网格 10.5px，同一个 "工具" 两种宽。 */
      const key = tagMode() + '|' + (bold ? 'B' : 'R') + '\u0000' + text;
      const hit = TAG_W_CACHE.get(key);
      if (hit !== undefined) return hit;
      let px;
      const ctx = getTagMeasureCtx();
      if (ctx) {
        try { ctx.font = tagFontSpec(bold); px = ctx.measureText(text).width + 2; }
        catch (error) { px = tagEstimateWidth(text); }
      } else { px = tagEstimateWidth(text); }
      px = Math.ceil(px);
      /* 缓存防失控：语言/自定义标签极端多时清一次重来（重测成本 = 每文本一次 measure） */
      if (TAG_W_CACHE.size > 6000) TAG_W_CACHE.clear();
      TAG_W_CACHE.set(key, px);
      return px;
    }
    function tagBoxWidth(tag) { return tagTextPx(term(tag), false) + tagMetrics().pad; }
    function plusBoxWidth(hidden) { return tagTextPx('+' + hidden, true) + tagMetrics().pad; }
    /* 行间 gap 同样跟着 computed 走（磁贴 6 / 网格 4）—— 见 tagMetrics 的注释。 */
    function tagGap() { return tagMetrics().gap; }
    function tagListOf(item) {
      /* m06170 第 3 项 + m06395 定夺：**药丸只放标签**。以前这里把类别也拼进来当药丸显示，
         于是「类别」和「标签」在界面上长得一模一样（用户原话：「类别……是 text 的而不是标签，
         标签只有投稿表单的标签那个才是标签」）。类别并没有因此看不见：
           · 按类别分组时它是分组标题（index.html 的 .vgroup-title，纯文本）；
           · 详情页详细信息里有「类别」一行（detailRows 的 row_category，纯文本）。
         落盘数据一个字节都没动 —— 只是不再把 category 画成药丸。 */
      return (item.tags || []).filter(Boolean);
    }
    /* 一行已放标签的总宽 = Σ 胶囊宽 + 相邻间隙（空行 = 0，只有一个 = 不加 gap）。 */
    function tagRowWidth(list) {
      let w = 0;
      for (let i = 0; i < list.length; i += 1) w += tagBoxWidth(list[i]) + (i ? tagGap() : 0);
      return w;
    }
    function tagLayout(item, avail) {
      const all = tagListOf(item);
      /* 没给可用宽度（收藏页/定制页的自适应卡片）就退回原来的固定条数，不显示 +X */
      if (!avail || avail <= 0) {
        const fixed = all.slice(0, viewMode.value === 'grid' ? 2 : 4);
        return { shown: fixed, hidden: 0 };
      }
      /* ① 尽量放（需求原话「最后一个变为那个+x」）：按顺序逐个试放，
         **放不下的跳过、继续试后面的** —— 旧算法在第一个放不下的标签处 break，
         宽标签排在前时整排塌成 +N（病根①）。跳过中间某个宽标签时，
         「+N」的 N = 没渲染的总数（放不下的 + 尾部没放的），胶囊 title 仍是全量标签，
         信息不丢、也不谎报数量。 */
      const placed = [];
      let used = 0;
      let rest = 0;
      for (let i = 0; i < all.length; i += 1) {
        const w = tagBoxWidth(all[i]) + (placed.length ? tagGap() : 0);
        if (used + w <= avail) { used += w; placed.push(all[i]); } else { rest += 1; }
      }
      if (!rest) return { shown: placed, hidden: 0 };   // 全放下了：没有剩余就没有胶囊
      /* ② 收缩到「已放 + gap + 实算胶囊宽」放得下：胶囊要给 "+N" 腾位，
         放不下就从**尾部**吐回已放标签（每次至少省 ~28px；hidden 多一位数字
         只让胶囊变宽 ≤7px，净效果单调收窄）。尾部吐回保证：显示出来的永远是
         顺序最靠前的那批，"+N" 语义仍成立。 */
      for (let keep = placed.length; keep >= 0; keep -= 1) {
        const shown = placed.slice(0, keep);
        const hidden = all.length - shown.length;
        const total = tagRowWidth(shown) + (keep ? tagGap() : 0) + plusBoxWidth(hidden);
        if (total <= avail) return { shown, hidden };
      }
      /* ③ 退化：连"光杆 +X 胶囊"都放不下（avail < 胶囊 ≈30px）。
         这时**连胶囊都不渲染**（hidden 归 0，模板的 v-if 自然不出）——
         渲染一个必被裁的半截胶囊就是"遮挡"，正是需求禁止的；整卡行宽塌到
         30px 以下说明布局本身已崩，宁可标签区留空。注释此路径为任务要求的
         "退化策略说明"。真实卡宽下永远走不到（最窄验收形态 240px 卡余 134px）。 */
      return { shown: [], hidden: 0 };
    }
    function visibleTags(item, avail) { return tagLayout(item, avail).shown; }
    function hiddenTagCount(item, avail) { return tagLayout(item, avail).hidden; }
    /* 标签行可用宽度 = 卡片宽 − 左右 padding(16×2) − 右侧按钮组（github/官网各 26、其间隔 6）− 缝隙 8 */
    function tagAvail(item, itemW) {
      if (!itemW) return 0;
      /* ⚠️ 必须**所有视图**都给右侧两个外链按钮留位置：
         之前这里判断 `viewMode !== 'grid'`（网格视图不显示那两个按钮，所以不预留），
         后来把网格视图的按钮恢复了，但预留没跟着改 ⇒ 标签把整行占满、
         两个按钮被挤到 .card{overflow:hidden} 外面看不见 —— 就是"官网和 github 按钮消失了"。
         网格视图按钮是 22px（.card.is-grid .card-btn），磁贴是 26px。 */
      const btnW = viewMode.value === 'grid' ? 22 : 26;
      const gapW = viewMode.value === 'grid' ? 4 : 6;
      const hasRepo = !!settings.search_show_github && isHttp(item.github);
      const hasSite = isHttp(item.url);
      const count = (hasRepo ? 1 : 0) + (hasSite ? 1 : 0);
      const reserve = count * btnW + (count > 1 ? gapW : 0);
      /* slack 8 → 16：标签行除了"按钮 + 按钮间距"还有 tag 之间、tag 与 .grow、
         .grow 与按钮之间的 gap，以及 1px 边框；旧值只留 8px，标签会算得"刚好占满"，
         把按钮挤到卡片边缘（CSS 虽然能兜，但标签更难看得全）。多留 8px 更稳。 */
      return Math.max(0, itemW - 32 - reserve - 16);
    }
    /* ---------- 卡片图标加载失败自动重试 ----------
       用户报加载搜索页图标出现加载不出来，更新状态才恢复。根因两条：
       ① 卡片 <img loading="lazy"> 在虚拟列表（绝对定位 + 整页唯一滚动容器）里，
          首屏并不一定被判定为"即将进入视口"，于是图片请求被推迟/跳过；
       ② onIconError 一次失败就把 <img> 从 DOM 删掉、永久换成首字母 glyph，
          之后不会再试 —— "更新状态"重新渲染对象才恢复，正好是这个特征。
       现在：图标 eager 加载；失败后最多重试 2 次（250ms / 800ms，带 ?r=&t= 破坏缓存），
       仍失败才换成首字母；页面重新可见 / 资源库重载时清空重试计数，重新给一次机会。 */
    const ICON_MAX_RETRY = 2;
    const iconRetry = reactive({});          // code -> { n: 已重试次数, tick: 最近一次重试时间戳, failed }
    function iconFailed(item) {
      const state = item && iconRetry[item.code];
      return !!(state && state.failed);
    }
    /* 重试时给 URL 加时间戳：不然浏览器会直接用缓存里的 404/失败结果
       ⚠️ 还要带上 iconEpoch：云端图标（icon.zip）后台同步完成后，
         **从来没失败过**的图标 src 字符串不变 → 浏览器不会重新请求 →
         换了云端新图也看不到。epoch 变化 = 强制全部重取一次。
         （iconEpoch 声明在后面，但这里只在渲染时读取，那时 setup 早已跑完。） */
    function iconSrc(item) {
      const base = String((item && item.icon) || '');
      if (!base) return base;
      const state = item && iconRetry[item.code];
      let url = base;
      const sep = url.indexOf('?') >= 0 ? '&' : '?';
      if (iconEpoch.value) url += sep + 'e=' + iconEpoch.value;
      if (state && state.tick) {
        url += (url.indexOf('?') >= 0 ? '&' : '?') + 'r=' + state.n + '&t=' + state.tick;
      }
      return url;
    }
    function onIconError(event, item) {
      const code = String((item && item.code) || '');
      if (!code) return;
      const state = iconRetry[code] || (iconRetry[code] = { n: 0, tick: 0, failed: false });
      if (state.failed) return;
      if (state.n >= ICON_MAX_RETRY) { state.failed = true; return; }   // 重试也失败 → 模板换首字母
      state.n += 1;
      const attempt = state.n;
      setTimeout(() => {
        const fresh = iconRetry[code];
        /* 期间被 resetIconRetries() 清过（或已判定失败）→ 不再补刀 */
        if (!fresh || fresh.failed || fresh.n !== attempt) return;
        fresh.tick = Date.now();             // 响应式触发 src 变化 → 浏览器重新请求
      }, attempt === 1 ? 250 : 800);
    }
    function resetIconRetries() {
      Object.keys(iconRetry).forEach((key) => { delete iconRetry[key]; });
    }
    /* 切回这个页签 / 最小化还原时再给图标一次机会（用户「更新状态才恢复」的等价兜底） */
    onMounted(() => {
      document.addEventListener('visibilitychange', () => {
        if (!document.hidden) resetIconRetries();
      });
    });

    function toggleFilter() {
      filterOpen.value = !filterOpen.value;
      chevronDeg.value = filterOpen.value ? 180 : 0;      // 展开顺时针 180°（180ms OutCubic）
      if (filterOpen.value) nextTick(panelHeight);
      /* ⚠️ task-3 ⑤：筛选开合改变 .vlist 在滚动内容里的偏移（vlistTop），
         必须在过渡（180ms）**结束后**重测一次；滚动途中每帧也在补（onScrollArea）。
         不重测 → 窗口按旧偏移算 → 顶部卡片"没出视野就消失"。 */
      setTimeout(() => { measureVlistTop(); }, 220);
      nextTick(() => { measureVlistTop(); });
    }
    function isFilterOn(key, value) {
      if (!value) return filters[key].length === 0;
      return filters[key].indexOf(value) >= 0;
    }
    function toggleFilterValue(key, value) {
      if (!value) filters[key] = [];
      else if (key === 'updated') filters.updated = [value];       // 更新时间等效单选
      else {
        const index = filters[key].indexOf(value);
        if (index >= 0) filters[key].splice(index, 1); else filters[key].push(value);
      }
      onFilterChanged();
    }
    /* 筛选条件变化 → 先刷新「最新」集合，再过滤（直接搜索**不刷新**，与原版一致） */
    async function onFilterChanged() {
      await refreshLatest();
      await runQuery();
    }
    function runSearch() {
      applied.value = keyword.value;
      scrollToTop();
      if (settings.last_search !== keyword.value) saveSetting('last_search', keyword.value);
      runQuery();
    }
    function clearKeyword() { keyword.value = ''; runSearch(); }
    const debouncedSearch = debounce(() => { applied.value = keyword.value; runQuery(); }, 300);
    watch(keyword, () => { if (autoSearch.value) debouncedSearch(); });
    watch(sortKey, () => runQuery());

    function setView(mode) {
      if (viewMode.value === mode) return;
      saveSetting('search_view', mode);
      nextTick(() => { measureViewport(); scrollToTop(); });
      toast(t('search_view_mode', '搜索页视图') + '：'
        + (mode === 'grid' ? t('search_view_grid', '网格') : t('search_view_tile', '磁贴')), 'success');
    }
    /* 收藏页的视图切换（需求：收藏页右上角要和搜索页一样有视图切换 UI）。
       ⚠️ 为什么单独写一个函数，而不是直接调 setView：
          setView 里的 scrollToTop() 作用的是**搜索页**的滚动容器（searchScroll），
          在收藏页调用它既没有意义，还会顺手把 pageScrollMemory.search 清成 0
          —— 那会破坏「在搜索页手动滚动 → 切走 → 切回要回原位」这个既有需求。
          → 收藏页这套只做自己的事：存设置 + 重算收藏页网格 + 收藏页自己回顶。
       ⚠️ 视图模式本身是**共享**的（都用 settings.search_view），
          所以在收藏页切换也会改变搜索页的视图 —— 这是刻意的：
          需求说的是"和搜索页一样的视图切换 UI"，一套设置最直观。 */
    function setFavView(mode) {
      if (viewMode.value === mode) return;
      saveSetting('search_view', mode);
      nextTick(() => {
        measureFavGrid();
        /* 收藏页自己回顶（它的滚动容器是 [data-scroll-key="favorites"] 那个）*/
        const el = findPageScroller('favorites');
        if (el) el.scrollTop = 0;
      });
      toast(t('fav_view_mode', '收藏页视图') + '：'
        + (mode === 'grid' ? t('search_view_grid', '网格') : t('search_view_tile', '磁贴')), 'success');
    }

    /* ---------- 卡片动作 ---------- */
    async function toggleFavorite(item) {
      if (!item || !item.code) return;
      const result = await bridge.tryCall('favorites.toggle', item.code);
      if (result && result.ok) {
        const fav = !!result.favorite;
        /* 删掉这里误用的 `setStep('favorites')` —— setStep 是启动分步
           （会改 bootText / document.title / 写 [boot] step= 日志），不是切页函数。
           现在只刷新收藏夹，并由 syncFavoriteState 统一同步所有副本的 _fav。 */
        const refreshed = await loadFavorites();
        if (!refreshed) syncFavoriteByCode(item.code, fav);
        toast(fav ? t('added', '已收藏') : t('removed', '已取消收藏'), 'success');
        if (page.value === 'search') runQuery();
      } else if (!result) needApi('favorites.toggle', '收藏');
      else toast(result.error || t('favorite_failed', '收藏失败'), 'error');
    }
    /* 打开外链。
       ⚠️ **普通点击 = 前台打开**（浏览器跳到前台，ToolsGCP 不要再抢回来）——
          之前后端无条件在三拍（150/400/800ms）后把窗口抢回前台，
          于是用户点了链接 → 浏览器跳出来 → 一瞬间又闪回 ToolsGCP（用户投诉的 bug）。
       ⚠️ **Ctrl + 点击 = 后台打开**（浏览器在后台开，ToolsGCP 保持在前台）——
          对齐原版 py 的 url_open.open_url（按着 Ctrl 才后台打开 + 抢回前台）。
       ⚠️ event 可能没有（某些调用点不传），这时按普通点击处理。 */
    /* Ctrl+左键「后台打开」的第二道保险（用户：「这个 bug 修了很多次但是还是没有解决」）。
       根因是 ctrl 语义**只**从鼠标事件上取，而有一批调用点手里根本没有事件对象：
         · 下载接口未就绪时退化成打开页面（deploy 那段 `openLink(target.url, null)`）
         · 更新包没有下载接口时打开发布页（`openLink(downloadUrl)`）
         · 任何少写一个 `$event` 的模板调用点
       这些点按鼠标事件判定永远是 false ⇒ 明明按住 Ctrl 仍被浏览器抢到前台，
       而且表现成"有时"（取决于点的是哪颗按钮）。
       → 再记一份键盘上 Ctrl 的**物理按下状态**当兜底：事件里带了就用事件的，
         没带就认「此刻 Ctrl 是不是按着的」。 */
    if (!window.__toolsGcpCtrlTrack) {
      window.__toolsGcpCtrlTrack = true;
      window.__ctrlKeyDown = false;
      window.addEventListener('keydown', (e) => { if (e.key === 'Control') window.__ctrlKeyDown = true; });
      window.addEventListener('keyup', (e) => { if (e.key === 'Control') window.__ctrlKeyDown = false; });
      /* 窗口失焦必须清零：浏览器被别的程序抢到前台时我们收不到 keyup，
         不清零就会卡在"Ctrl 一直按着"，之后所有普通点击都变成后台打开。 */
      window.addEventListener('blur', () => { window.__ctrlKeyDown = false; });
    }
    function ctrlHeld(event) {
      return !!(event && event.ctrlKey) || !!window.__ctrlKeyDown;
    }

    async function openLink(url, event) {
      if (!isHttp(url)) { toast(t('link_empty', '这个链接是空的'), 'info'); return; }
      const ctrl = ctrlHeld(event);
      const result = await bridge.tryCall('shell.open_url', url, '', ctrl);
      if (!result) { needApi('shell.open_url', '打开链接'); return; }
      if (!result.ok) toast(t('open_failed', '打开失败：') + (result.error || url), 'error');
    }
    /* 原版：右键卡片 → @给GCP-AI→ 把 @名称(编码) 带进 AI 输入框。
       需求：右键先弹一个卡片菜单，里面两项@给GCP-AI测 Ping。 */
    const cardMenu = ref(null);        // { x, y, item, url }
    function openCardMenu(item, event) {
      const x = event && event.clientX ? event.clientX : 0;
      const y = event && event.clientY ? event.clientY : 0;
      /* 别让菜单跑出窗口（宽 160 / 高 78 是实际尺寸的保守估计） */
      const vw = window.innerWidth, vh = window.innerHeight;
      cardMenu.value = {
        x: Math.max(8, Math.min(x, vw - 168)),
        y: Math.max(8, Math.min(y, vh - 86)),
        item: item.code, name: item.name,
      };
    }
    function closeCardMenu() { cardMenu.value = null; }
    function cardMenuItem() {
      if (!cardMenu.value) return null;
      return items.value.find((it) => it.code === cardMenu.value.item)
        || (detail.value && detail.value.code === cardMenu.value.item ? detail.value : null);
    }
    function cardMenuMention() {
      const item = cardMenuItem();
      closeCardMenu();
      if (item) mentionAi(item);
    }
    /* ---------- task-12 需求 6：详情区「选区」右键菜单 ----------
       与卡片菜单是**两套独立状态**（cardMenu 按 item，selMenu 按选中文本）；
       共用 .card-menu 外观。数据：屏幕坐标 + 选中文本 + 所属条目 code。 */
    const selMenu = ref(null);         // { x, y, text, code }
    function closeSelMenu() { selMenu.value = null; }
    /* 在详情区里右键：有非空文档选区才接管（弹菜单 + 记下选区归属），
       没有选区就**原样放行**——保持"右键什么都不发生"的旧观感，
       也不抢 WebView2 原生右键（框架里没有我们能用的东西）。 */
    function onSelContext(event) {
      const sel = window.getSelection && window.getSelection();
      const text = sel && !sel.isCollapsed ? String(sel.toString() || '') : '';
      if (!text.trim()) { closeSelMenu(); return; }
      /* 菜单挂回后点内部会触发 contextmenu，模板已 .prevent；这里只管首次定位 */
      event.preventDefault();
      event.stopPropagation();
      /* 选区归属：anchor/focus 两头的公共祖先里最近的 [data-code]。
         详情页渲染时 .detail-wrap 带当前条目（模板里 detail.code 就挂在这），
         所以 code 直接取 detail —— 但选区可能是**旧条目**的残留（切卡片不清选区），
         用 DOM 归属判断太绕，这里以"当前打开的详情"为准：菜单出现即代表
         用户正对着这条详情提问。 */
      const vw = window.innerWidth, vh = window.innerHeight;
      selMenu.value = {
        x: Math.max(8, Math.min(event.clientX || 0, vw - 190)),
        y: Math.max(8, Math.min(event.clientY || 0, vh - 86)),
        text: text,
        code: (detail.value && detail.value.code) || '',
      };
    }
    /* 两个菜单项都**先取走文本快照再清选区**：copyText 用的是快照（不是活动选区），
       所以清掉不影响复制；清完用户不会再看到一条"已经消费掉的"蓝色高亮。 */
    function clearDocSelection() {
      try {
        const s = window.getSelection && window.getSelection();
        if (s) s.removeAllRanges();
      } catch (err) { /* 静默 */ }
    }
    function selMenuMention() {
      const menu = selMenu.value;
      closeSelMenu();
      if (!menu || !detail.value) return;
      clearDocSelection();
      /* 把**选中文本**带进 token：@名称(编码)[选中文本]，整段一个可点 token */
      mentionAi(detail.value, menu.text);
    }
    function selMenuCopy() {
      const menu = selMenu.value;
      closeSelMenu();
      if (!menu) return;
      copyText(menu.text);
      clearDocSelection();
    }
    /* 测 Ping：走桌面端 `shell.ping` 做**真实**网络测量
       （DNS 解析 / TCP 握手 / https 的 TLS 握手），不再拿本地图标文件自测。
       没有可用地址时明确报错，不假装成功。
       ⚠️ task-12 需求 7：抽成 pingTarget(name, url) —— 卡片右键菜单和详情页
       每条链接的测 Ping 按钮**共用同一条链路**，提示口径（尤其失败必须带名称）不会走偏。 */
    /* ---------- 第五轮需求④：测 Ping 的"进行中"状态 ----------
       用户原话：「点击……Ping测试按钮点击后按钮变为不可点击状态 测试完毕恢复原样，按钮内部的图标
       测试期间改为. .. ...循环……记得按钮大小不要改变这个是我最担心的一个bug。」
       口径已与用户确认：状态只加在**详情页链接行那枚图标按钮**上，卡片正面不新增按钮。
       ⚠️ 为什么这套状态是"按行 key 的表"而不是一个布尔：详情页一排里官网/GitHub/作者主页/聊天
          各有一枚 Ping 按钮，用户可以连着点不同行；用单个布尔会让先结束的那行把仍在测的行也"点亮"
          或提前熄灭。key = label|value（label 是显示文本，同一行在同一次打开里稳定且唯一）。
       ⚠️ 大小不许跳：盒子尺寸只由 .copy-btn 的固定 28×28（layout.css）决定，这里换的永远是
          盒子里的内容（SVG ↔ 点阵 span），点阵最宽 3 个点也远小于 28px，不参与任何布局计算。 */
    const pingBusy = reactive({});
    /* 点阵步进间隔（毫秒）：抽成常量是为了让 _devtest/probe_ping_busy_ui.mjs 能直接钉住它，
       不再写死 380 这种"改代码必改探针"的耦合。 */
    const PING_TICK_MS = 160;
    const pingTickCount = ref(1);
    let pingTickTimer = null;
    function pingRowKey(row) {
      return String((row && row.label) || '') + '|' + String((row && row.value) || '');
    }
    function pingBusyStart(key) {
      pingBusy[key] = true;
      /* 计时器只在"至少有一枚在测"时存在：全部测完立刻 clearInterval，不留常驻 tick（虚拟列表
         常驻 tick 会白白让整页重渲染）。
         ⚠️ 间隔 160ms：上一版取 380ms（一轮 . → .. → ... 要 1.14s），用户第七轮明确反馈
            「动画切换每个状态时的那个动画间隔时间太长了 减小间隔时间」⇒ 压到 160ms，
            一轮约 0.48s，仍然远慢于 60Hz 重绘、不会看着闪。 */
      if (!pingTickTimer) {
        pingTickCount.value = 1;
        pingTickTimer = setInterval(() => { pingTickCount.value = pingTickCount.value % 3 + 1; }, PING_TICK_MS);
      }
    }
    function pingBusyEnd(key) {
      delete pingBusy[key];
      if (pingTickTimer && !Object.keys(pingBusy).length) { clearInterval(pingTickTimer); pingTickTimer = null; }
    }
    function pingIsBusy(row) { return !!pingBusy[pingRowKey(row)]; }
    /* "." → ".." → "..." 三轮一循环（用户写的 . .. ... 就是这个序列） */
    const pingDotsText = computed(() => '.'.repeat(pingTickCount.value));
    async function pingTarget(name, url) {
      const label = String(name || '');
      if (!url) {
        toast(t('ping_no_target', '「{name}」没有可测的网站或仓库地址').replace('{name}', label), 'info');
        return;
      }
      toast(t('ping_running', '正在测 Ping：{name} …').replace('{name}', label), 'info');
      const result = await bridge.tryCall('shell.ping', url);
      if (!result) { needApi('shell.ping', '测 Ping'); return; }
      if (!result.ok) {
        /* 需求 7 原文：「测 Ping 失败时要写出名称（不能只说"测 Ping 失败"）」。
           词条 ping_failed 已带 {name} 与 {msg} 两个占位 —— {name} 用条目名称，不是 URL。 */
        /* 第五轮需求①：Ping 之后的提示统一停留 4 秒（用户口径，原来结果 6s / 失败 2s 不一致，
           失败信息往往比结果更长，反而消失得最快）。 */
        toast(t('ping_failed', '测 Ping 失败：{name} — {msg}')
          .replace('{name}', label)
          .replace('{msg}', result.error || url), 'error', '', { duration: 4000 });
        return;
      }
      const level = result.total_ms < 200 ? 'success' : (result.total_ms < 600 ? 'info' : 'warning');
      /* 需求：不同项**各占一行**，不要挤成一行。
         停留时长演进：3s →（上一轮）6s →（第五轮需求①，用户原话「还是改为停留4秒后再自动消失吧」）4s。 */
      const lines = [
        t('ping_result', '测 Ping：{name} — {total} ms')
          .replace('{name}', label)
          .replace('{total}', result.total_ms),
        'DNS   ' + result.dns_ms + ' ms',
        'TCP   ' + result.tcp_ms + ' ms',
      ];
      if (result.tls_ms != null) lines.push('TLS   ' + result.tls_ms + ' ms');
      const text = lines.join(String.fromCharCode(10));
      toast(text, level, '', { copy: text, duration: 4000, pre: true });
    }
    async function cardMenuPing() {
      const item = cardMenuItem();
      closeCardMenu();
      if (!item) return;
      await pingTarget(item.name, item.url || item.github || item.download_url || '');
    }
    /* task-12 需求 7：详情页每条链接的复制按钮后那枚"测 Ping"图标按钮。
       测的是**这一行自己的地址**（官网就测官网、GitHub 就测 GitHub），
       名称用条目名 —— 与卡片右键菜单同一口径。 */
    async function detailRowPing(row) {
      if (!detail.value || !row || !row.value) return;
      /* :disabled 已经挡住鼠标重复点击，这里是兜底（键盘回车 / 程序内直接调用同样走这条路），
         避免同一行并发测两次。 */
      if (pingIsBusy(row)) return;
      const key = pingRowKey(row);
      pingBusyStart(key);
      try {
        await pingTarget(detail.value.name, row.value);
      } finally {
        /* 三条退出路径都要恢复原样：没地址（ping_no_target 提前 return）、后端没这个接口
           （needApi 提前 return）、失败（ping_failed 提前 return）、成功。finally 是唯一
           能保证"测试完毕恢复原样"的地方 —— 漏一条按钮就会永远卡在转点状态。 */
        pingBusyEnd(key);
      }
    }
    function enterCardMenuKey(event) {
      if (event.key === 'Escape') { closeCardMenu(); closeSelMenu(); }
    }
    /* task-12 需求 6：selText 非空时 token 变成 @名称(编码)[选中文本] 整段一个 token。
       选中文本可能带换行 / nbsp / 超长 / 方括号（方括号是 token 语法边界，必须去掉，
       否则正则与用户手敲的变体都对不上）；清洗只做**空白折叠 + 去括号 + 截断**，
       全程走 textContent 赋值（buildTokenEl 不用 innerHTML），HTML 注入无路可走。 */
    function mentionTokenSuffix(selText) {
      const cleaned = String(selText == null ? '' : selText)
        .replace(/[\u00a0\r\n\t]+/g, ' ')
        .replace(/\s+/g, ' ')
        .replace(/[\[\]]/g, '')
        .trim()
        .slice(0, 80);
      return cleaned ? '[' + cleaned + ']' : '';
    }
    function mentionAi(item, selText) {
      if (!settings.ai_enabled) { toast(t('ai_disabled', 'GCP-AI 还没有开启，可在设置里打开。'), 'info'); return; }
      if (!item || !item.code) return;
      /* 先把 AI 界面切出来（侧栏页或悬浮抽屉），再等一帧让 rich-ai-input 挂载，
         然后让它插入 token（蓝字下划线 + 可点击跳详情的那一段，而不是普通字符串）。 */
      if (settings.ai_sidebar_mode) doGoto('ai'); else aiOpen.value = true;
      const payload = {
        name: item.name || '',
        code: item.code || '',
        text: '@' + (item.name || '') + '(' + (item.code || '') + ')' + mentionTokenSuffix(selText),
      };
      /* 刚切页 / 刚打开抽屉时 rich-ai-input 还没挂载（页面 transition 130ms、v-if 一帧），
         ref 会短暂为 null。这里轮询到它出现为止（最多 ~600ms），只插入一次。 */
      let inserted = false;
      const tryInsert = (attempt) => {
        if (inserted) return;
        const target = settings.ai_sidebar_mode ? aiInputPageRef.value : aiInputDrawerRef.value;
        if (target && typeof target.insertMention === 'function') {
          inserted = true;
          target.insertMention(payload);
          return;
        }
        if (attempt < 12) setTimeout(() => tryInsert(attempt + 1), 50);
        else focusAiInput();
      };
      nextTick(() => tryInsert(0));
      toast(t('ai_mention_hint', '已把该资源带入 AI 输入框'), 'info');
    }
    /* 点输入框里的 @token → 跳到对应资源详情。
       ⚠️ 详情页只在 search / customize 页下渲染，所以从 AI 页点击时先切到搜索页
          （doGoto 会清空 detail，因此要等下一帧再 openDetail）；悬浮抽屉先收起来，
          否则详情页会被抽屉盖住。 */
    function onAiTokenClick(payload) {
      if (!payload || !payload.code) return;
      const code = String(payload.code);
      const item = items.value.find((x) => x.code === code)
        || (detail.value && detail.value.code === code ? detail.value : null);
      if (!item) { toast(t('unknown_code_tip', '资源库里没有 {code}').replace('{code}', code), 'info'); return; }
      if (!settings.ai_sidebar_mode) aiOpen.value = false;   // 抽屉模式：先收起抽屉
      if (page.value !== 'search' && page.value !== 'customize') {
        doGoto('search');
        /* doGoto 的页面过渡是 out-in（~230ms），等新页挂载再开详情 */
        setTimeout(() => openDetail(item), 60);
        return;
      }
      openDetail(item);
    }
    function onCardClick(item) {
      if (selectionBar.value) { item._sel = !item._sel; return; }
      openDetail(item);
    }

    /* ---------- 详情 ---------- */
    const activeVariant = ref('');
    async function openDetail(item) {
      const sequence = ++detailSequence;
      /* 记下当前滚动位置（返回时还原，需求：从哪儿进去就回哪儿）。
         ⚠️ 只用 findPageScroller(page.value)，**去掉** querySelector('.page-scroll') 回落：
            详情页段（index.html key="detail"）自己也有一个没有 data-scroll-key 的
            .page-scroll，过渡期回落会拿到"别的页面的容器"→ 记错/写错位置（本轮修的 bug 之一）。
         ⚠️ 同时把这份位置**同步进 pageScrollMemory**：transition 的 @after-enter 会调
            restorePageScroll（比 closeDetail 的还原晚 ~100ms），以前它拿的是"上次切页时
            的陈旧值（常常是 0）"，把 closeDetail 刚写回的位置又覆盖成顶端 ——
            这就是"进卡片→返回，整页滚回最顶端"的根因。两处共用同一个真相后不再打架。
         ⚠️ 拿不到容器（如 AI 页 @token 进来时列表还没挂载）：不要清零，沿用上一次的记忆。 */
      /* key 走 scrollMemoryKey()：投稿页那份记忆是按分节存的（maker:form 之类），
         这里不换算就会量到 null、把记忆清零。 */
      const scrollerKey = scrollMemoryKey(page.value);
      const scroller = findPageScroller(scrollerKey);
      if (scroller) {
        detailScrollMemory = scroller.scrollTop;
        pageScrollMemory[scrollerKey] = detailScrollMemory;
      } else {
        detailScrollMemory = Number(pageScrollMemory[scrollerKey] || 0);
      }
      /* 记下"这个详情是从哪个页面打开的" —— 切走再切回时要能回到这个详情。 */
      detailPage.value = page.value;
      detail.value = { ...item };
      activeVariant.value = item.default_variant || '';
      const result = await bridge.tryCall('resources.detail', item.code);
      if (sequence !== detailSequence || !detail.value) return;
      if (result && result.ok && result.item) {
        const merged = mapItem(result.item);
        /* ⚠️ `_fav` 不能只抄传入卡片的那份：detail 是**新对象**（mapItem 出来恒 false），
           而 item 那份可能是上一次渲染的旧状态（例如刚在别处取消/收藏过、或资源库
           刚重建）。以收藏夹（favoriteCodeSet）为唯一真源，和 syncFavoriteState 同口径，
           保证"从收藏页进详情 / 取消再收藏后进详情"星星都对。 */
        merged._fav = favoriteCodeSet().has(merged.code);
        merged.variants = result.variants || merged.variants;
        merged.default_variant = result.default_variant || merged.default_variant;
        detail.value = merged;
        activeVariant.value = merged.default_variant || (merged.variants[0] || {}).key || '';
      }
      nextTick(() => { if (detailScroll.value) detailScroll.value.scrollTop = 0; });
    }
    function closeDetail() {
      detailSequence += 1;
      detail.value = null;
      /* 关掉详情时清掉"来自哪个页面"，
         并且**回到那个页面**（用户按返回应该回列表页，不是留在别的页面）。 */
      const back = detailPage.value;
      detailPage.value = '';
      if (back && back !== page.value) {
        /* 跨页返回：doGoto 会 rememberPageScroll(当前页) —— 当前页此刻挂的是详情，
           没有 [data-scroll-key] 容器，记不到东西；真正要保的是**来源页**的位置，
           它在 openDetail 时已写进 pageScrollMemory[back]，doGoto 的恢复链会用它。 */
        doGoto(back);
        return;
      }
      /* 等列表重新挂载后再量视口 + 还原滚动位置（否则虚拟列表会算到旧位置、整屏空白）。
         ⚠️ 只用 findPageScroller，去掉 || currentScrollEl() 回落：out-in 过渡期间
            唯一在场的 .page-scroll 是**详情段**那个（无 data-scroll-key），
            写到它身上等于白写，而原来的重试上限（4 帧）又追不上 ~230ms 的过渡，
            表现就是"返回列表后停在顶端"。
         ⚠️ 重试上限提到 12 帧，和 restorePageScroll 对齐；@after-enter 的
            restorePageScroll(page.value) 还会再兜一次（openDetail 已把同一个值
            写进 pageScrollMemory，两条恢复链**互认**，不会再互相覆盖）。 */
      const want = detailScrollMemory;
      const restore = (attempt) => {
        const el = findPageScroller(scrollMemoryKey(page.value));
        if (!el) {
          if (attempt < 12) requestAnimationFrame(() => restore(attempt + 1));
          return;
        }
        if (page.value === 'search') { measureViewport(); scrollTop.value = want; }
        if (el.scrollTop !== want) el.scrollTop = want;
        if (page.value === 'search') scrollTop.value = el.scrollTop;
        if (attempt < 12) requestAnimationFrame(() => restore(attempt + 1));
      };
      nextTick(() => requestAnimationFrame(() => restore(0)));
    }
    const detailTags = computed(() => {
      const it = detail.value || {};
      // 与 tagListOf 同一口径（m06170 第 3 项）：这一排药丸只放标签；类别走 detailRows 的文本行。
      return (it.tags || []).filter(Boolean);
    });
    const introParagraphs = computed(() => {
      const it = detail.value || {};
      const text = it.intro || it.description || '';
      return String(text).split(/\n{2,}/).map((v) => v.trim()).filter(Boolean);
    });
    const detailRows = computed(() => {
      const it = detail.value || {};
      /* ⚠️⚠️ 本轮两处改动（用户原话 m03713）：
         ①「删除所有的CPU架构……还有卡片ui界面里面的详细信息的CPU架构都要删除」
           → 这里不再产出 `row_architectures` 行。数据侧的 architectures 已从
             ToolsGCP-Resources.json 删除，前端如果还画这一行就是一条永远空的行。
         ②「进入页面里面中的作者和聊天都要放在这个详细信息里而不是有单独的按钮
            （作者改名为作者主页）」
           → 原来详情页顶栏有两颗独立的 btn-link（作者 / 聊天），现在删掉了，
             改成这里的两个链接行，和官网 / GitHub / 下载地址同一副面孔。
             键用一开始就存在的 `author_page`（作者主页）与 `row_chat`（聊天），
             三语都有，不新增键。 */
      const rows = [
        { label: t('row_systems', '适用系统'), value: (it.systems || []).map(term).join('、') },
        { label: t('row_category', '类别'), value: (it.category || []).map(term).join('、') },
        { label: t('row_listed_at', '上架时间'), value: String(it.listed_at || '').slice(0, 16) },
      ];
      if (isHttp(it.url)) rows.push({ label: t('row_url', '官网'), value: it.url, link: true });
      /* 开源仓库：可能有多组，逐行列出（标签 = 平台名）。
         老数据只有 github 一条 → repoRowsFor 内部会退回那一行。 */
      repoRowsFor(it).forEach((repo) => {
        if (isHttp(repo.url)) rows.push({ label: repo.label, value: repo.url, link: true });
      });
      /* 作者主页 / 聊天：本轮从"顶栏按钮"搬进详细信息的链接行（顺序放在 GitHub 之后、
         下载地址之前 —— 它们是"人/社群"的信息，比"去哪下载"更靠近来源）。 */
      if (isHttp(it.author_url)) {
        rows.push({ label: t('author_page', '作者主页'), value: it.author_url, link: true });
      }
      if (isHttp(it.chat_url)) {
        rows.push({ label: t('row_chat', '聊天 / 论坛'), value: it.chat_url, link: true });
      }
      /* 自定义链接（m05525：「他最终的效果在卡片ui页面里的详细信息一样」）：
         排在作者/聊天之后、下载地址之前，和固定链接同一副面孔（标签在左、可点开）。 */
      (it.links || []).forEach((row) => {
        if (row && row.label && isHttp(row.url)) {
          rows.push({ label: row.label, value: row.url, link: true });
        }
      });
      /* 下载**页面**的网址（和 download_url 直链是两种语义） */
      if (isHttp(it.download_page_url)) {
        rows.push({ label: t('row_download_page', '下载地址'), value: it.download_page_url, link: true });
      }
      /* ⚠️ 需求（task-3 ④）：空字段**整行不渲染**（label + value 都不出），
         网格自动收缩不留空位 —— 之前这里 `index < 4 || row.value` 让前四行
         （适用系统 / CPU 架构 / 类别 / 上架时间）**无条件保留**，空值就靠模板里
         `row.value || '—'` 画一条"—"占位。现在所有行统一：值为空 → 整行不进 rows。
         （链接行本来就由 isHttp 把关；作者 / 聊天 / 变体等其它信息项同口径：
         空 = 不渲染，不显示占位符。） */
      return rows.filter((row) => String(row.value || '').trim());
    });
    async function chooseVariant(variant) {
      if (!variant || !variant.key || !detail.value) return;
      activeVariant.value = variant.key;
      const result = await bridge.tryCall('resources.variant', detail.value.code, variant.key);
      if (result && result.ok && result.item) {
        detail.value = { ...detail.value, url: result.item.url || detail.value.url,
          github: result.item.github || detail.value.github,
          download_url: result.item.download_url || detail.value.download_url };
      }
    }
    /* 复制按钮的"已复制"状态：**按文本各自计时**，不再共用一个 copied。
       之前共用一个 ref，快速点另一个 copy 会把前一个的对勾立刻清掉（用户报的"串台"bug）。 */
    const copiedKeys = ref([]);
    function isCopied(value) { return copiedKeys.value.indexOf(String(value || '')) >= 0; }
    async function copyText(value) {
      const text = String(value || '');
      if (!text) return;
      let done = false;
      /* ① 首选**后端原生剪贴板**（desktop/api 的 clipboard.write → Win32 剪贴板）。
            这是"提示复制成功、剪贴板里其实什么都没有"的根治点：
            WebView2 里 navigator.clipboard.writeText() 经常被静默拒绝，
            而这里和原版 PyQt 的 QApplication.clipboard().setText() 等价，必定生效。 */
      try {
        const result = await bridge.tryCall('clipboard.write', text);
        if (result && result.ok) done = true;
      } catch (error) { done = false; }
      /* ② 还要**读回校验**：写入成功 ≠ 内容正确（剪贴板被别的程序抢走时就会这样）。
            校验不过就当失败，不再骗用户说"已复制"。 */
      if (done) {
        try {
          const back = await bridge.tryCall('clipboard.read');
          if (back && back.ok && typeof back.text === 'string') {
            done = back.text === text;
          }
        } catch (error) { /* 读不回来就信任写入结果 */ }
      }
      if (!done) {
        try { await navigator.clipboard.writeText(text); done = true; }
        catch (error) { done = false; }
      }
      if (!done) {
        /* 最后兜底：老式 execCommand（纯浏览器调试环境用） */
        try {
          const area = document.createElement('textarea');
          area.value = text;
          area.style.position = 'fixed';
          area.style.opacity = '0';
          document.body.appendChild(area);
          area.focus(); area.select();
          done = document.execCommand('copy');
          area.remove();
        } catch (error) { done = false; }
      }
      if (!done) {
        toast(t('copy_failed', '复制失败，请手动选中后按 Ctrl+C'), 'error');
        return;
      }
      if (!isCopied(text)) copiedKeys.value = copiedKeys.value.concat([text]);
      toast(t('copied_ok', '已复制到剪贴板'), 'success');
      setTimeout(() => {
        copiedKeys.value = copiedKeys.value.filter((key) => key !== text);
      }, 2000);
    }

    /* ---------- 收藏页 ---------- */
    const favFolder = ref('Default');
    const favMoving = ref(false);
    const moveTarget = ref('');
    const isDefaultFolder = computed(() => favFolder.value === 'Default');
    const moveFolderOptions = computed(() => folders.value.map((f) => ({ value: f.name, label: f.label })));
    const favItems = computed(() => {
      const folder = folders.value.find((f) => f.name === favFolder.value);
      const codes = new Set(folder ? (folder.items || []) : []);
      return items.value.filter((it) => codes.has(it.code));
    });
    const favSelectedCount = computed(() => favItems.value.filter((it) => it._sel).length);
    const favAllChecked = computed(() => favItems.value.length > 0 && favSelectedCount.value === favItems.value.length);
    /* 三态（none / some 半选 / all）—— 和搜索页的选择条一样。
       收藏页批量移动的『全选』也要有部分勾选状态也就是"-"状态。
       原生 checkbox 的 indeterminate 一旦被点击会自动变 checked=true → 全选；
       再点一次 → 取消全选，正好符合需求。 */
    const favSelState = computed(() => {
      if (!favSelectedCount.value) return 'none';
      return favAllChecked.value ? 'all' : 'some';
    });
    function favSelectAll(checked) { favItems.value.forEach((it) => { it._sel = checked; }); }
    function toggleRowSelect(item) { item._sel = !item._sel; }

    /* ---------- 收藏页卡片网格的列宽计算 ----------
       两个要点：
       ① **卡片宽度固定** —— 同一排等宽，最后一行只有 1~2 个时**留空**，不拉伸填满；
       ② **随窗口变化** —— 和搜索页同一套公式（TILE：minW 272 / spacing 14 /
          base 4 / maxCardW 400），窗口变宽 → 列数变多 → 卡片宽度跟着变。
       ⚠️ 为什么不能靠 CSS 的 flex：`.grid-static .card { flex: 1 1 272px }` 会把
          最后一行剩下的卡片拉宽（就是用户说的"拉伸填满一排"）；
          而 `flex: 0 0 auto` 配固定 width 又不会随窗口变（"完全大小不变"）。
       → 所以宽度必须**由 JS 算**，和搜索页的虚拟列表 layout 同一套算法。
    */
    /* ⚠️ task-3 ① 的根因（"重启后进收藏页 UI 混乱、像匀速整理"）：
       旧代码把 ref 挂在**网格本身**（`v-if="favItems.length"` 的 .fav-grid）上，
       于是"量宽度"必须等**页面挂载 + 收藏数据回来**两件事都完成：
         第一帧 favGridWidth=0 → favLayout 走兜底列数（cfg.base=4/6）渲染出卡片；
         随后 onPageAfterEnter / ResizeObserver 才量到真实宽度 → 列数变 →
         整屏卡片**宽度与换行位置二次跳变**（看起来就像在"匀速整理/排序"）。
       → 修法：**先量后渲染**。ref 改挂到常驻的滚动容器（.page-scroll，
         不随收藏数据 v-if 卸载），用 @vue:mounted 在**插入后、绘制前**同步量一次，
         量完才允许网格出现（favMeasured 门控）；列数在首帧就是终值。 */
    const favScroller = ref(null);
    const favMeasured = ref(false);
    const favGridWidth = ref(0);
    /* ---------- 收藏页卡片网格 —— 宽度改由 **CSS Grid** 算 ----------
       ⚠️⚠️ 之前的做法（"面条"bug 的根源）：JS 算出 itemW，用**内联 style** 设 width。
          问题：量容器宽度要等页面挂载 + 收藏数据回来，那之前 itemW=0
          → 卡片渲染成0 宽 × 196 高= 一根面条，等"更新下这页"才恢复。
          ⚠️ 现在的做法：**JS 只给"列数"（一个整数），宽度交给 CSS 的 1fr**。
             `grid-template-columns: repeat(var(--fav-cols), minmax(0, 1fr))`
             → 宽度**永远**是容器的等分，不可能出现 0 宽。
             · 列数用**搜索页同一套公式**算（含 maxCardW=400 的上限），
               所以卡片宽度和搜索页**完全一致**；
             · CSS Grid 的每条轨道等宽 ⇒ **最后一行剩下的卡片不会被拉伸**
               （这是 flex `flex: 1 1 272px` 做不到的 —— 那个会让最后一行被拉宽填满）。
             · JS 没量到宽度时用默认列数（3），布局依然正常，不会出现面条。 */
    const favLayout = computed(() => {
      /* ⚠️ 需求：收藏页右上角也加了"磁贴 / 网格"切换（和搜索页一样），
         所以列宽算法要**跟着视图模式走**：
         · tile（磁贴）：TILE —— 一行 4 张大卡片（minW 272 / maxCardW 400）
         · grid（网格）：GRID —— 一行 6 张小卡片（minW 168 / maxCardW 240）
         ⚠️ 搜索页的 layout computed（第 ~1560 行）用的是**完全相同**的公式，
            只是那边取 cfg = viewMode === 'grid' ? GRID : TILE —— 两边保持一致，
            收藏页的卡片宽度就和搜索页**完全一样**（需求原话）。 */
      const cfg = viewMode.value === 'grid' ? GRID : TILE;
      const avail = Math.max(0, favGridWidth.value);
      const spacing = cfg.spacing;
      if (avail <= 0 || !favItems.value.length) {
        return { columns: cfg.base, itemW: cfg.minW, gap: spacing };
      }
      let columns = Math.max(1, Math.floor((avail + spacing) / (cfg.minW + spacing)));
      const cap = Math.max(cfg.base, Math.ceil(avail / cfg.maxCardW));
      columns = Math.max(1, Math.min(columns, cap));
      const usable = avail - spacing * (columns - 1);
      const itemW = Math.floor(usable / columns);
      // 余数摊给**间距**：等宽 + 左右留白相等（和搜索页 layout 完全一致）
      const remainder = usable - itemW * columns;
      const gap = columns > 1 ? spacing + remainder / (columns - 1) : spacing;
      return { columns, itemW, gap };
    });
    /* 兜底重测的 rAF 句柄（同一时刻只允许排一次，见 measureFavGrid） */
    let favMeasureRetry = 0;
    /* 量一次收藏页网格的可用宽度（用来算列数）。
       ⚠️ task-3 ①：改量**常驻滚动容器**（favScroller），不再量网格本身 ——
         网格是 `v-if="favItems.length"` 的，量它必须等收藏数据回来，
         那之前列数只能走兜底 → 数据到齐后二次跳变（"匀速整理"的观感）。
         滚动容器随页面挂载就存在，@vue:mounted（插入后、绘制前）里量它，
         **第一帧的列数就是终值**；clientWidth 天然排除滚动条占位。
       ⚠️ 量到 0（容器还没布局好）不写 0、也不置 favMeasured —— 保留旧值等下一次。 */
    function measureFavGrid() {
      const el = favScroller.value;
      if (!el) return;                       // 页面还没挂载 → 保留旧值
      const width = el.clientWidth;
      if (width > 0) {
        favGridWidth.value = Math.round(width);
        favMeasured.value = true;
        return;
      }
      /* ⚠️ 兜底（防"空白收藏页"）：窗口隐藏/尺寸为 0 这类极端情况下 clientWidth 量不到，
         不能把门控永远关着。下一帧再试一次；还不行就**放行渲染**（用兜底列数），
         之后 ResizeObserver 拿到真实尺寸会自己纠正 —— 宁可退化成旧行为，
         也不能让收藏页一片空白。 */
      if (favMeasureRetry) return;
      favMeasureRetry = requestAnimationFrame(() => {
        favMeasureRetry = 0;
        const w2 = favScroller.value ? favScroller.value.clientWidth : 0;
        if (w2 > 0) { favGridWidth.value = Math.round(w2); favMeasured.value = true; }
        else favMeasured.value = true;
      });
    }

    /* ---------- 收藏夹右键菜单（重命名 / 删除）----------
       收藏页右键左侧的对应收藏夹会弹出菜单"重命名""删除"（删除这个红色图标和字体）
       ⚠️ 菜单里的操作针对**被右击的那一个**收藏夹（不是当前选中的），
          所以菜单要记住 folder.name。 */
    const favMenu = reactive({ open: false, x: 0, y: 0, name: '', label: '', isDefault: false });
    function openFavMenu(event, folder) {
      if (!folder) return;
      favMenu.open = false;
      favMenu.name = folder.name;
      favMenu.label = folder.label || folder.name;
      favMenu.isDefault = folder.name === 'Default';
      favMenu.x = event.clientX;
      favMenu.y = event.clientY;
      favMenu.open = true;
    }
    function closeFavMenu() { favMenu.open = false; }
    function favMenuRename() {
      const name = favMenu.name;
      closeFavMenu();
      if (!name || name === 'Default') return;
      renameFolder(name);
    }
    function favMenuRemove() {
      const name = favMenu.name;
      closeFavMenu();
      if (!name || name === 'Default') return;
      removeFolder(name);
    }

    function startMoveMode() {
      if (favMoving.value) { cancelMoveMode(); return; }
      if (!favItems.value.length) { toast(t('empty', '这个收藏夹还是空的，去搜索页点收藏图标添加吧'), 'warning'); return; }
      if (folders.value.length < 2) { toast(t('need_other_folder', '只有一个收藏夹，先新建一个再移动吧'), 'warning'); return; }
      favMoving.value = true;
      moveTarget.value = '';
    }
    function cancelMoveMode() { favMoving.value = false; favItems.value.forEach((it) => { it._sel = false; }); }
    async function commitMove() {
      const picked = favItems.value.filter((it) => it._sel).map((it) => it.code);
      if (!picked.length) { toast(t('nothing_selected', '你还没有勾选任何项'), 'warning'); return; }
      if (!moveTarget.value) { toast(t('move_to', '移动到') + '？', 'warning'); return; }
      const result = await bridge.tryCall('favorites.move_many', picked, favFolder.value, moveTarget.value);
      if (!result) return needApi('favorites.move_many', '批量移动');
      if (result.ok) {
        const target = (folders.value.find((f) => f.name === moveTarget.value) || {}).label || moveTarget.value;
        toast(t('moved', '已把 {n} 项移动到「{folder}」').replace('{n}', result.moved).replace('{folder}', target), 'success');
        favMoving.value = false;
        await loadFavorites();
      } else toast(result.error || t('move_failed', '移动失败'), 'error');
    }
    async function createFolder() {
      const name = await openDialog({ title: t('new_folder', '新建收藏夹'), input: true,
        placeholder: t('new_folder', '新建收藏夹') });
      if (!name) return;
      const result = await bridge.tryCall('favorites.create_folder', name);
      if (!result) return needApi('favorites.create_folder', '新建收藏夹');
      if (result.ok && result.created) { await loadFavorites(); toast(t('folder_created', '已新建收藏夹'), 'success'); }
      else toast((result.message || result.error) || t('create_failed', '创建失败'), 'error');
    }
    /* renameFolder / removeFolder 现在接受**目标收藏夹名**（可选）。
       为什么：从右键菜单触发时，要操作的是**被右击的那一个**收藏夹，
       而不是当前选中的（favFolder）。不传参数时仍然用 favFolder（向后兼容）。 */
    async function renameFolder(targetName) {
      const key = String(targetName || favFolder.value);
      const current = (folders.value.find((f) => f.name === key) || {}).label || '';
      if (!current) return;
      const name = await openDialog({ title: t('rename_folder', '重命名'), input: true, value: current });
      if (!name || name === current) return;
      const result = await bridge.tryCall('favorites.rename_folder', key, name);
      if (!result) return needApi('favorites.rename_folder', '重命名');
      if (result.ok && result.renamed) {
        /* 改的是当前选中的那个 → 跟着切过去（改的是别的 → 当前选中不变） */
        if (favFolder.value === key) favFolder.value = result.name;
        await loadFavorites(); toast(t('folder_renamed', '已重命名'), 'success');
      } else toast((result.message || result.error) || t('rename_failed', '重命名失败'), 'error');
    }
    async function removeFolder(targetName) {
      const key = String(targetName || favFolder.value);
      const folder = folders.value.find((f) => f.name === key);
      if (!folder) return;
      const yes = await openDialog({ title: t('delete_folder', '删除'), danger: true,
        body: t('confirm_delete_folder', '确定要删除收藏夹「{name}」吗？\n里面的 {n} 项收藏也会一起删除。')
          .replace('{name}', folder.label).replace('{n}', folder.count),
        confirmText: t('delete', '删除') });
      if (!yes) return;
      const result = await bridge.tryCall('favorites.delete_folder', folder.name);
      if (!result) return needApi('favorites.delete_folder', '删除收藏夹');
      if (result.ok && result.deleted) {
        /* 删的是当前选中的那个 → 切回默认夹；删的是别的 → 当前选中不变 */
        if (favFolder.value === folder.name) favFolder.value = 'Default';
        await loadFavorites(); toast(t('folder_deleted', '已删除收藏夹'), 'success');
      } else toast((result.message || result.error) || t('delete_failed', '删除失败'), 'error');
    }

    /* ---------- 收藏夹导出 / 导入 ----------
       用户改主意了，原话：还是把部署页里的关于一切收藏的代码删除，并且在收藏页合适位置
       放导出和导入按钮，导入的话会弹窗 是和之前说的一样选择收藏夹也可以新建的。
       所以 长在部署页的导入清单顺带导入收藏整体搬到这里：
       部署页只管清单本身，收藏的导入导出归收藏页。 */
    const NEW_FOLDER_VALUE = '__new_favorite_folder__';
    const FAV_SCHEMA = '1.0.0';

    /* 解析导入文件：兼容 {folders:[{name,label,items}]}、数组（codes 或 {code}/{items}）、
       {items:[...]}、纯 codes 数组 —— 用户手改过 / 别处生成的文件也能认。 */
    function parseFavoritePayload(data) {
      const folders = [];
      const codes = [];
      const pushCodes = (arr) => {
        (Array.isArray(arr) ? arr : []).forEach((entry) => {
          const code = (entry && typeof entry === 'object')
            ? String(entry.code || entry.id || '') : String(entry == null ? '' : entry);
          if (code && code.trim()) codes.push(code.trim());
        });
      };
      if (Array.isArray(data)) {
        const looksLikeFolder = data.some((row) => row && typeof row === 'object'
          && Array.isArray(row.items));
        if (looksLikeFolder) {
          data.forEach((row) => {
            if (!row || typeof row !== 'object') { pushCodes([row]); return; }
            folders.push({ name: String(row.name || row.label || ''),
                           label: String(row.label || row.name || '') });
            pushCodes(row.items || row.codes || []);
          });
        } else pushCodes(data);
      } else if (data && typeof data === 'object') {
        if (Array.isArray(data.folders)) {
          data.folders.forEach((row) => {
            const f = (row && typeof row === 'object') ? row : {};
            folders.push({ name: String(f.name || ''), label: String(f.label || f.name || '') });
            pushCodes(f.items || f.codes || []);
          });
        } else if (Array.isArray(data.items)) pushCodes(data.items);
        else if (Array.isArray(data.codes)) pushCodes(data.codes);
      }
      return { folders, codes: Array.from(new Set(codes)) };   // 去重、保持文件内顺序
    }

    /* 导出全部收藏夹（默认文件名 ToolsGCP-Favorites-YYYYMMDD.json）。
       与部署页 exportManifest 同一条链路：优先后端 shell.save_text_file（系统另存为 +
       真正写盘），桌面接口缺失才退回浏览器下载并明确提示 —— 绝不假装成功。 */
    /* 导出前先弹勾选对话框。勾选组复用 openDialog 的 checks；空选择提示并留在弹窗里。 */
    async function exportFavorites() {
      await loadFavorites();                 // 导出必须是后端最新状态，不能用过期缓存
      const all = (folders.value || []).map((f) => ({ name: f.name, label: f.label || f.name,
        items: (f.items || []).slice() }));
      const total = all.reduce((sum, f) => sum + f.items.length, 0);
      if (!total) {
        toast(t('fav_export_empty', '还没有任何收藏，先收藏几个再导出吧'), 'warning');
        return;
      }
      let picked = null;
      while (true) {
        picked = await openDialog({
          title: t('fav_export', '导出收藏'),
          body: t('fav_export_checks', '选择要导出的收藏夹（可多选）：'),
          checks: all.map((f) => ({ value: f.name,
            label: f.label + '（' + f.items.length + '）',
            checked: f.name === 'Default' })),
          buttons: [t('cancel', '取消'), t('fav_export_confirm', '导出')],
          cancelable: false,
        });
        if (!Array.isArray(picked)) return;            // 取消
        if (picked.length) break;
        toast(t('fav_export_none', '至少选择一个收藏夹'), 'warning');
      }
      const list = all.filter((f) => picked.indexOf(f.name) >= 0);
      const total2 = list.reduce((sum, f) => sum + f.items.length, 0);
      const filename = 'ToolsGCP-Favorites-' + deployStamp() + '.json';
      let content;
      try {
        content = JSON.stringify({ schema_version: FAV_SCHEMA, generator: 'ToolsGCP',
          exported_at: new Date().toISOString(), total: total2, folders: list }, null, 2) + '\n';
      } catch (error) {
        toast(t('fav_export_failed', '导出收藏失败：{err}')
          .replace('{err}', (error && error.message) || String(error)), 'error');
        return;
      }
      const result = await bridge.tryCall('shell.save_text_file', filename, content,
        'JSON 文件 (*.json)');
      if (result && result.ok) {
        if (result.canceled) return;                    // 用户在「另存为」里点取消：静默
        toast(t('fav_exported', '收藏已导出') + '：' + (result.path || filename), 'success');
        return;
      }
      if (result && !result.ok) {
        toast(t('fav_export_failed', '导出收藏失败：{err}')
          .replace('{err}', result.error || t('save_failed_short', '保存失败')), 'error');
        return;
      }
      try {
        downloadJson(filename, content);
        toast(t('fav_exported', '收藏已导出') + '：' + filename
          + t('fav_export_browser', '（浏览器下载，桌面端保存对话框接口未就绪）'), 'info');
      } catch (error) {
        toast(t('fav_export_failed', '导出收藏失败：{err}')
          .replace('{err}', (error && error.message) || String(error)), 'error');
      }
    }

    /* 把 codes 放进 targetFolder：目标夹已有的跳过；在别的夹的按「来源夹」分批
       move_many（后端每搬一条都推 favorites-changed，逐条 move 会很卡）；
       完全没收藏的用 add。不在资源库里的 code 也照样存（收藏本身合法），
       只单独统计并提示「暂不显示」—— 收藏页 favItems 只渲染资源库里的条目。 */
    async function applyImportedFavorites(codes, targetFolder) {
      await loadFavorites();
      const library = new Set(items.value.map((it) => it.code));
      const folderOf = new Map();
      (folders.value || []).forEach((f) => (f.items || []).forEach((code) => folderOf.set(code, f.name)));
      const moveGroups = new Map();                    // 来源夹 → 要移动的 codes
      const fresh = [];
      const missing = [];
      let skipped = 0;
      (codes || []).forEach((code) => {
        if (!code) return;
        if (!library.has(code)) missing.push(code);
        const from = folderOf.get(code) || '';
        if (!from) { fresh.push(code); return; }
        if (from === targetFolder) { skipped += 1; return; }
        if (!moveGroups.has(from)) moveGroups.set(from, []);
        moveGroups.get(from).push(code);
      });
      let moved = 0, added = 0, failed = 0;
      for (const pair of moveGroups.entries()) {
        const result = await bridge.tryCall('favorites.move_many', pair[1], pair[0], targetFolder);
        if (!result) return needApi('favorites.move_many', '导入收藏');
        if (result.ok) {
          const done = Number(result.moved) || 0;
          moved += done;
          failed += Math.max(0, pair[1].length - done);
        } else failed += pair[1].length;
      }
      for (const code of fresh) {
        const result = await bridge.tryCall('favorites.add', code, targetFolder);
        if (!result) return needApi('favorites.add', '收藏');
        if (!result.ok) failed += 1;
        else if (result.added) added += 1;
        else skipped += 1;                             // 后端认为已存在
      }
      /* 刷新收藏夹 + 全部星标 + 搜索页结果（单一真源；否则会重演"导入后星不亮"）。
         顺便切到目标收藏夹：导入完还停在别的夹，用户会以为"什么都没导进来"。 */
      await loadFavorites();
      if ((folders.value || []).some((f) => f.name === targetFolder)) favFolder.value = targetFolder;
      runQuery();
      let msg = t('fav_import_done', '已导入收藏：{moved} 项移动、{added} 项新增')
        .replace('{moved}', moved).replace('{added}', added);
      if (skipped) msg += t('fav_import_skipped', '，{n} 项已在该收藏夹').replace('{n}', skipped);
      if (failed) msg += t('fav_import_failed', '，{n} 项失败').replace('{n}', failed);
      if (missing.length) msg += t('fav_import_missing', '；{n} 条资源库中没有，暂不显示')
        .replace('{n}', missing.length);
      toast(msg, failed ? 'warning' : 'success');
    }

    /* 选「文件 → 解析 → 确认条目数 → 选目标收藏夹」的完整导入流程 */
    async function importFavorites() {
      const input = document.createElement('input');
      input.type = 'file'; input.accept = '.json,application/json';
      input.onchange = async () => {
        const file = input.files && input.files[0];
        if (!file) return;
        let parsed;
        try {
          parsed = parseFavoritePayload(JSON.parse(await file.text()));
        } catch (error) {
          toast(t('fav_import_bad_file', '导入失败：文件不是有效的 JSON')
            + '（' + ((error && error.message) || String(error)) + '）', 'error');
          return;
        }
        if (!parsed.codes.length) {
          toast(t('fav_import_empty', '文件里没有可导入的收藏'), 'warning');
          return;
        }
        const foldersInFile = parsed.folders.filter((f) => f.name || f.label).length;
        const yes = await openDialog({
          title: t('fav_import', '导入收藏'),
          body: t('fav_import_confirm', '文件里有 {n} 条收藏（{folders} 个收藏夹），确定导入吗？')
            .replace('{n}', parsed.codes.length).replace('{folders}', foldersInFile || 1),
          confirmText: t('fav_import_confirm_btn', '导入'),
        });
        if (!yes) return;
        await pickFolderAndImportFavorites(parsed.codes);
      };
      input.click();
    }

    /* 目标收藏夹选择：最后一项「新建收藏夹」→ 选中后同一个对话框里出现名称输入框。
       名称空 / 重名都提示并**留在弹窗里**继续改（不吞掉原因）。 */
    async function pickFolderAndImportFavorites(codes) {
      let remembered = '';
      while (true) {
        const options = (folders.value || []).map((f) => ({ value: f.name, label: f.label || f.name }));
        options.push({ value: NEW_FOLDER_VALUE, label: t('fav_import_new', '新建收藏夹') });
        const opened = await openDialog({
          title: t('fav_import', '导入收藏'),
          body: t('fav_import_pick', '选择要导入到的收藏夹（最后一项可以新建）：'),
          select: options,
          selectValue: remembered && options.some((o) => o.value === remembered)
            ? remembered : options[0].value,
          inputWhen: NEW_FOLDER_VALUE,
          /* ⚠️ 这里是 placeholder 不是 inputPlaceholder：openDialog() 只认 options.placeholder
             （旧实现传的是 inputPlaceholder，输入框一直是空白没提示，这轮一并修正） */
          placeholder: t('fav_import_name', '收藏夹名称'),
          buttons: [t('cancel', '取消'), t('fav_import_confirm_btn', '导入')],
          cancelable: false,
        });
        if (!opened) return;
        const target = String(dialog.selectValue || '');
        let folderName = target;
        if (target === NEW_FOLDER_VALUE) {
          const name = String(dialog.inputValue || '').trim();
          if (!name) {
            remembered = NEW_FOLDER_VALUE;
            toast(t('fav_import_name_empty', '请输入收藏夹名称'), 'warning');
            continue;
          }
          const created = await bridge.tryCall('favorites.create_folder', name);
          if (!created) { needApi('favorites.create_folder', '新建收藏夹'); return; }
          if (!created.ok) { toast(created.error || t('folder_create_failed', '新建收藏夹失败'), 'error'); return; }
          if (!created.created) {
            remembered = NEW_FOLDER_VALUE;
            /* 后端失败提示可能是"语言键"（如 default_folder_reserved），也可能是一句中文；
               语言键能查到就翻译，查不到原样显示（绝不吞掉原因）。 */
            const reason = String(created.message || '');
            const text = /^[a-z][a-z0-9_]*$/.test(reason) ? t(reason, reason) : reason;
            toast(text || t('folder_create_failed', '新建收藏夹失败'), 'error');
            continue;
          }
          folderName = String(created.name || name);
        }
        await applyImportedFavorites(codes, folderName);
        return;
      }
    }


    /* ---------- 定制页 ---------- */
    const customizeEditing = ref(false);
    const selectedInterests = ref([]);
    const customizeOnboarded = computed(() => !!settings.customize_onboarded);
    const interestCatalog = computed(() => {
      const counter = new Map();
      /* 计数与 kind 判定都用并集：否则"只在某个语言池出现两次的标签"进不了喜好目录。 */
      items.value.forEach((it) => {
        const cats = it.category_all || it.category;
        cats.forEach((v) => counter.set(v, (counter.get(v) || 0) + 1));
        (it.tags_all || it.tags || []).forEach((v) => {
          if (cats.indexOf(v) < 0) counter.set(v, (counter.get(v) || 0) + 1);
        });
      });
      /* ⚠️⚠️ 本轮修正（用户原话：「定制页类别和标签不是固定死的而且有的就要在里面
         没有的不能在里面」）：
         旧版这里 filter(count >= 2) + slice(0, 20) —— 只出现过 1 次的类别/标签被**整条丢掉**、
         超出 20 个的被截断，于是"资源库里明明有这个类别，定制页里却选不到"。
         现在：**资源库里出现过的全部列出**（类别按 category_all 并集、标签按 tags_all 并集），
         一个都不丢、也不设上限；排序仍是"资源越多越靠前"，同样数量按名称排。
         注意不是写死清单：将来资源库增删类别，这里自动跟着变。 */
      return Array.from(counter.entries())
        .map(([name, count]) => ({ name, count,
          kind: items.value.some((it) => (it.category_all || it.category).indexOf(name) >= 0) ? 'category' : 'tag' }))
        .sort((a, b) => (b.count - a.count) || a.name.localeCompare(b.name));
    });
    const interestGroups = computed(() => ([
      { kind: 'category', label: t('filter_category', '类别'),
        items: interestCatalog.value.filter((i) => i.kind === 'category') },
      { kind: 'tag', label: t('filter_tag', '标签'),
        items: interestCatalog.value.filter((i) => i.kind === 'tag') },
    ]));
    function pickedInterest(item) { return selectedInterests.value.some((i) => i.name === item.name); }
    function toggleInterest(item) {
      const index = selectedInterests.value.findIndex((i) => i.name === item.name);
      if (index >= 0) selectedInterests.value.splice(index, 1); else selectedInterests.value.push(item);
    }
    const interestsRatio = computed(() => Math.min(1, selectedInterests.value.length / 5) * 100 + '%');
    const interestNamesText = computed(() => {
      const names = selectedInterests.value.map((i) => term(i.name));
      return names.slice(0, 5).join('、') + (names.length > 5 ? '…' : '');
    });
    function clearInterests() { selectedInterests.value = []; }
    async function saveInterests() {
      /* ★ 本轮修正（用户原话：「开始是不可点击状态，至少选择其中一个标签则可点击」）：
         空选时主按钮本身已 :disabled（见 index.html），这里再加一道守卫，
         防止键盘回车 / 程序化调用绕过按钮状态 —— 两处用同一句文案。 */
      if (!selectedInterests.value.length) {
        toast(t('customize_need_one', '至少选择一个类别或标签，再点这里开始'), 'warning');
        return;
      }
      const order = interestCatalog.value.map((i) => i.name);
      const names = selectedInterests.value.map((i) => i.name)
        .sort((a, b) => order.indexOf(a) - order.indexOf(b));
      settings.customize_interests = names;
      settings.customize_onboarded = true;
      await saveSetting('customize_interests', names);
      await saveSetting('customize_onboarded', true);
      customizeEditing.value = false;
      toast(names.length
        ? t('interests_saved', '喜好已保存')
        : t('interests_saved_empty', '已保存（未选择喜好，推荐页会先空着）'), 'success');
    }
    async function resetInterests() {
      const yes = await openDialog({ title: t('restore_default', '恢复默认'),
        body: t('reset_confirm', '确定要删除所有喜好、恢复到默认状态吗？删除后推荐页会清空，需要重新挑一次。'),
        confirmText: t('restore_default', '恢复默认') });
      if (!yes) return;
      selectedInterests.value = [];
      settings.customize_interests = [];
      settings.customize_onboarded = false;
      await saveSetting('customize_interests', []);
      await saveSetting('customize_onboarded', false);
      toast(t('reset_done', '已恢复默认，请重新选择喜好'), 'info');
    }
    /* 定制页排序：默认 'match' = 按匹配分（类别+3/标签+1），其余复用搜索页那套选项 */
    const customSort = ref('match');
    /* 定制页的排序下拉：比搜索页多一档「匹配度」（默认），并且去掉"已收藏/未收藏"
       （定制页按喜好匹配，用不上这两档）。 */
    const customSortOptions = computed(() => [
      { value: 'match', label: t('sort_match', '匹配度') },
      { value: 'all', label: t('sort_all', '全部') },
      { value: 'category', label: t('sort_category', '类别') },
      { value: 'az', label: t('sort_az', 'A-Z') },
      { value: 'za', label: t('sort_za', 'Z-A') },
      /* 需求：定制页也要有和搜索页一样的「已收藏 / 未收藏」 */
      { value: 'fav', label: t('sort_fav', '已收藏') },
      { value: 'unfav', label: t('sort_unfav', '未收藏') },
    ]);
    /* 需求：「在定制页里的筛选要和搜索页一致」——所以定制页有自己的一份筛选状态
       （组件、外观、行为与搜索页完全相同，只是互不干扰：在定制页筛选不会顺手改掉搜索结果）。
       另外补上「类别」排序档：和搜索页一样，每个类别有自己的标题文字，而不是平铺成一种样式。 */
    const customFilters = reactive({ category: [], tag: [], source: [], favorite: [],
                                     updated: [], system: [] });
    const customFilterOpen = ref(false);
    const customPanelH = ref(0);
    const customChevronDeg = computed(() => (customFilterOpen.value ? 180 : 0));
    function toggleCustomFilter() {
      customFilterOpen.value = !customFilterOpen.value;
      if (customFilterOpen.value) {
        /* 和搜索页一样按内容高度动画（.filter-panel 的 max-height 从 0 过渡到实际高度） */
        nextTick(() => {
          const host = document.querySelector('.customize-filter');
          const inner = host ? host.querySelector('.filter-inner') : null;
          customPanelH.value = inner ? inner.scrollHeight + 4 : 320;
        });
      }
    }
    function isCustomFilterOn(key, value) {
      if (!value) return customFilters[key].length === 0;
      return customFilters[key].indexOf(value) >= 0;
    }
    function toggleCustomFilterValue(key, value) {
      if (!value) customFilters[key] = [];
      else if (key === 'updated') customFilters.updated = [value];
      else {
        const index = customFilters[key].indexOf(value);
        if (index >= 0) customFilters[key].splice(index, 1); else customFilters[key].push(value);
      }
    }
    const recommendations = computed(() => {           // 类别 +3 / 标签 +1，取前 24
      const picked = new Set(selectedInterests.value.map((i) => i.name));
      if (!picked.size) return [];
      const scored = [];
      items.value.forEach((it) => {
        /* ⚠️ 需求：点收藏后卡片**不能消失**。旧代码这里 `if (it._fav) return;`
           （照抄 py 的"推荐里排除已收藏"），结果在定制页点一下星星，卡片立刻没了 —— 用户明确不要。
           现在已收藏的照常在推荐列表里（星星变实心即可）。
           定制页自己的筛选条件仍然生效（和搜索页同一套判定）。 */
        if (!passesFilters(it, customFilters)) return;
        let score = 0;
        const cats = it.category_all || it.category;
        cats.forEach((c) => { if (picked.has(c)) score += 3; });
        (it.tags_all || it.tags || []).forEach((v) => { if (picked.has(v)) score += 1; });
        if (score > 0) scored.push({ ...it, _score: score });
      });
      /* 排序口径与 py `_rank_recommendations` 逐字对齐：
         分数降序 → 上架时间降序 → 名称。
         ⚠️ 名称用**码点比较**（a < b ? -1 : 1）而不是 localeCompare：
            py 那边是 `str(name)` 直接比较，localeCompare 会按拼音排，同分同时间的结果会不一致。 */
      scored.sort((a, b) => (b._score - a._score)
        || ((parseDate(b.listed_at) || 0) - (parseDate(a.listed_at) || 0))
        || (String(a.name) < String(b.name) ? -1 : (String(a.name) > String(b.name) ? 1 : 0)));
      const mode = customSort.value;
      /* 需求：A-Z / Z-A 之前"不太好用" —— 原因是按码点比较，中文名等于按 Unicode 排，
         完全不是用户心里的"字母顺序"。改成 localeCompare('zh-Hans-CN')：中文按拼音、英文按字母。 */
      const byName = (a, b) => String(a.name || '').localeCompare(
        String(b.name || ''), 'zh-Hans-CN', { numeric: true, sensitivity: 'base' });
      if (mode === 'az') {
        scored.sort((a, b) => byName(a, b));
      } else if (mode === 'za') {
        scored.sort((a, b) => byName(b, a));
      } else if (mode === 'fav' || mode === 'unfav') {
        /* 已收藏 / 未收藏：**和搜索页同口径 —— 是"筛选"，不是"排序"**。
           需求原话：「定制页的排序中的已收藏和未收藏切换后其他无关内容未隐藏」。
           旧实现只把收藏的那批排到前面（`sort`），不收藏的那批仍然留在列表里，
           所以用户切到「已收藏」看到的还是满满一屏没收藏的东西 = 没生效。
           搜索页那边是 `list.filter(it => !!it._fav === want)`（localQuery），
           这里照抄同一个判据：want=true 只留已收藏，want=false 只留未收藏。
           组内仍按匹配分排（收藏状态已经一致，分数就是唯一的次级依据）。 */
        const want = mode === 'fav';
        const picked = scored.filter((it) => !!it._fav === want);
        picked.sort((a, b) => b._score - a._score);
        return picked.slice(0, 24);
      } else if (mode === 'all') {
        /* 「全部」= 不额外排序（只按匹配分），和搜索页 sort_all 的语义一致 */
        scored.sort((a, b) => (b._score - a._score));
      }
      return scored.slice(0, 24);
    });
    /* 类别模式下按类别分组（复用搜索页同一个 categoryGroups），每组带自己的类别标题 */
    const recommendGroups = computed(() => {
      const list = recommendations.value;
      if (!list.length) return [];
      if (customSort.value !== 'category') return [{ key: '', title: '', items: list, count: list.length }];
      return categoryGroups(list);
    });
    const emptyRecommendTitle = computed(() => {
      if (!selectedInterests.value.length) return t('no_interest', '还没有选择喜好，先挑几个吧。');
      if (!interestCatalog.value.length) return t('onboard_empty', '资源库里暂时没有可选的喜好标签。');
      /* 已收藏 / 未收藏 现在是**筛选**（切了会把不相干的那批整个藏掉），
         所以完全可能"有匹配的资源、但这一档里一条都不剩"。
         这时候还提示"这几个喜好暂时没有匹配的资源"就是假话，用户会以为喜好选错了。 */
      if (customSort.value === 'fav') {
        return t('empty_no_fav', '这些喜好里还没有你收藏的资源，去搜索页点星星收藏几个再来。', 'customize');
      }
      if (customSort.value === 'unfav') {
        return t('empty_no_unfav', '这些喜好里的资源都已经收藏过了，换几个喜好试试。', 'customize');
      }
      return t('no_match_interest', '这几个喜好暂时没有匹配的资源，换几个试试。');
    });
    function onRecommendClick(item) {
      if (favMoving.value) { toggleRowSelect(item); return; }
      openDetail(item);
    }

    /* ---------- 公告（GitHub Issues：标签「公告」+ 作者本人） ---------- */
    const NOTICE_URL = 'https://api.github.com/repos/Galen563/ToolsGCP/issues';
    const NOTICE_MIRRORS = ['https://ghfast.top/', 'https://gh-proxy.com/', 'https://ghproxy.net/', 'https://gh.ddlc.top/'];
    /* 官方先试；失败再按设置里的「搜索源」优先试那个镜像，最后其余镜像挨个试
       （原版 core/announcements.py 与 updater.py 就是这个顺序） */
    async function fetchJson(url) {
      const tryUrl = async (target) => {
        try {
          const response = await fetch(target, { cache: 'no-store',
            headers: { Accept: 'application/vnd.github+json' } });
          return response.ok ? await response.json() : null;
        } catch (error) { return null; }
      };
      const direct = await tryUrl(url);
      if (direct !== null) return direct;
      const preferred = String(settings.search_source || '').trim();
      const ordered = preferred
        ? NOTICE_MIRRORS.filter((m) => m.indexOf(preferred) >= 0).concat(
          NOTICE_MIRRORS.filter((m) => m.indexOf(preferred) < 0))
        : NOTICE_MIRRORS;
      for (const mirror of ordered) {
        const data = await tryUrl(mirror + url);
        if (data !== null) return data;
      }
      return null;
    }
    async function loadNotices(force) {
      if (noticesLoading.value) return;
      noticesLoading.value = true;
      noticesError.value = '';
      /* 已读状态走桌面端（原版 AnnouncementStore：读/写 announcements.json），
         不再只存前端 localStorage —— 否则"每次启动都要重新点已读" */
      const store = await bridge.tryCall('announcements.list', force);
      if (store && store.ok) {
        /* ⚠️ 已读状态**要以本地缓存为准合并**，不能被后端返回的列表整个覆盖掉。
           根因（公告已读状态保存不下来）：
             markRead() 是**乐观更新**（先改本地、再异步通知后端）。
             如果这中间有一次 loadNotices 把 readIds 整个换成后端那份
             （后端还没来得及写盘 → 那份是旧的），用户刚点的"已读"就被**冲掉了**。
           → 合并：两边取并集（后端有的 + 本地有的），谁都不丢。 */
        if (Array.isArray(store.read_ids)) {
          readIds.value = Array.from(new Set(
            store.read_ids.concat(readIds.value).map((v) => Number(v)).filter((v) => Number.isFinite(v))));
          writeLocal('readNotices', readIds.value);
        }
        if (Array.isArray(store.items) && store.items.length) {
          notices.value = store.items;
          writeLocal('notices', notices.value);
          noticesLoading.value = false;
          if (force) toast(t('notice_loaded', '公告已刷新'), 'info');
          maybePopup();
          return;
        }
      }
      const url = NOTICE_URL + '?labels=' + encodeURIComponent('公告')
        + '&state=open&sort=created&direction=desc&per_page=100&_=' + Date.now();
      const raw = await fetchJson(url);
      if (!Array.isArray(raw)) {
        noticesError.value = t('notice_failed', '公告获取失败，请检查网络后重试。');
        const cached = readLocal('notices', []);
        if (cached.length) notices.value = cached;
        if (force) toast(noticesError.value, 'error');
        noticesLoading.value = false;
        return;
      }
      const pad = (n) => String(n).padStart(2, '0');
      notices.value = raw.filter((issue) => {
        if (!issue || issue.pull_request) return false;
        const login = ((issue.user || {}).login || '').toLowerCase();
        return login === 'galen563' || String(issue.author_association || '').toUpperCase() === 'OWNER';
      }).map((issue) => {
        const created = new Date(issue.created_at || '');
        /* ⚠️ body_md = **原始 Markdown**（这条路径是前端直连 GitHub Issue，拿到的
           本来就是原文，不需要也不应该再过 stripMarkdown 擦掉）；body 继续是擦过的
           纯文本 —— 老的 localStorage 缓存、以及"只要纯文本"的地方还在用它，
           渲染侧统一走 `body_md || body`（见 noticeSource）。
           截断按 Markdown 边界做，避免留下半个 ** 或没配对的代码围栏。 */
        const mdRaw = mdTruncate(issue.body || '', 2000);
        return {
          id: issue.id || issue.number, number: issue.number,
          title: String(issue.title || '').trim(),
          body: stripMarkdown(mdRaw).slice(0, 2000),
          body_md: mdRaw,
          author: (issue.user || {}).login || '', url: issue.html_url || '',
          date: Number.isNaN(created.getTime()) ? String(issue.created_at || '').slice(0, 16)
            : created.getFullYear() + '-' + pad(created.getMonth() + 1) + '-' + pad(created.getDate())
              + ' ' + pad(created.getHours()) + ':' + pad(created.getMinutes()),
        };
      }).filter((issue) => issue.title);
      writeLocal('notices', notices.value);
      /* ⚠️ 把内容**同步**给后端 store —— 否则后端 store 里没有这些公告，
         后面 mark_read 找不到对应的条目 → **已读状态存不下来**（用户报的 bug）。 */
      bridge.tryCall('announcements.sync_items', notices.value).catch(() => {});
      noticesLoading.value = false;
      if (force) toast(notices.value.length ? t('notice_loaded', '公告已刷新') : t('no_notice', '暂无公告'), 'info');
      maybePopup();
    }
    function isRead(id) { return isReadKey(Number(id)); }
    /* 已读状态同时写桌面端（announcements.json）与本地缓存：桌面端不可用时至少本地生效
       ⚠️ 存的是 issue **编号**（#1/#2 那种），不是数据库 id。
       ⚠️ **等后端写完**再收尾 —— 之前是 fire-and-forget，程序在写入完成前退出
          就会丢状态（公告已读状态保存不下来）。
          这里 await 一下（失败也不阻塞界面，本地已经先记上了）。 */
    async function markRead(id) {
      const key = Number(id);
      if (!key || isReadKey(key)) return;
      readIds.value = readIds.value.concat([key]);
      writeLocal('readNotices', readIds.value);
      try {
        await bridge.tryCall('announcements.mark_read', key);
      } catch (error) { /* 本地已记，后端失败不影响本次操作 */ }
    }
    async function markAllRead() {
      readIds.value = Array.from(new Set(
        readIds.value.concat(notices.value.map((n) => noticeKey(n)).filter(Boolean))));
      writeLocal('readNotices', readIds.value);
      await bridge.tryCall('announcements.mark_all_read');
      toast(t('mark_all_read', '全部已读'), 'success');
    }
    /* 第二个参数是鼠标事件：公告卡片的右上角标就是「在 GitHub 查看」，
       不带事件的话 Ctrl+左键的后台语义会在这里丢失（见 ctrlHeld 的注释）。 */
    function openNotice(notice, event) { markRead(noticeKey(notice)); openLink(notice.url, event); }
    /* 公告弹窗：⚠️ 隐私弹窗开着的时候不许弹（它俩都是遮罩式，叠一起很难看） */
    let noticePopped = false;
    function maybePopup() {
      if (noticePopped) return;
      if (privacy.open) return;                       // 隐私政策没同意 → 公告让路
      /* ⚠️⚠️ 本轮需求（用户原话）：「公告弹窗系统假设有2条未读消息只弹窗最新的消息永远，
         假设最新的标记为已读之前的也不要弹窗，每次只检测公告最新是什么如果已读则不弹窗，
         当然x条未读还是要正确显示数量的。」
         → 判定基准从"有没有任何未读"改成**只看最新一条公告**（notices[0]，
            loadNotices 已按 created 新→旧排好序）：
            · 最新一条已读 → 永远不弹（哪怕更早的还躺着未读——旧行为会弹更早那条，
              用户明确说这不对："之前的也不要弹窗"）；
            · 未读计数、侧栏红点、弹窗里的「N 条未读」胶囊仍按真实未读数显示，
              只是"弹不弹"与它们解耦。 */
      const latest = (notices.value || [])[0];
      if (!latest || isReadKey(noticeKey(latest))) return;
      noticePopped = true;
      const count = unread.value.length;
      openDialog({
        /* 「N 条未读」并入标题旁边（用户：有x条未读放到"新公告"旁边）：
           走现成的 titleBadge 通道，弹窗不再出现程序图标（head 整段删掉）。 */
        title: t('notice_dialog_title', '新公告'),
        titleBadge: t('notice_unread_count', '{n} 条未读').replace('{n}', count),
        /* ── 本轮版式改动（用户逐条点名）：
              · 「公告弹窗不要有程序图标出现」→ 不再传 head（logo 块整块消失）；
              · 「标题ui不要放在框框里而是上面」→ 公告标题走 item.title 但模板画在
                边框**外面**（见 index.html .dlg-item 结构），框里只剩正文 + meta；
              · 「框框下面的2行text删除」→ extra（"还有 N 条…"、"点全部已读…"两句）
                整段不再传。 ── */
        item: {
          title: String(latest.title || ''),
          bodyHtml: noticeBodyHtml(latest),
          body: String(noticeSource(latest) || ''),
          /* meta = 「作者 · #编号 · 日期」（字段由后端 normalize_issue 给：
             author / number / date）。放在框内底部（正文之下），与旧版一致。 */
          meta: t('notice_item_meta', '{author} · #{number}')
            .replace('{author}', String(latest.author || '')).replace('{number}', String(latest.number || ''))
            + (latest.date ? ' · ' + String(latest.date) : ''),
        },
        /* 右上角纯图标 = 在浏览器打开这条公告的 GitHub 页面（上轮需求保持）。 */
        link: { url: String(latest.url || ''),
          tip: t('notice_open_in_github', '在 GitHub 查看') },
        buttons: [t('notice_later', '稍后'), t('mark_all_read', '全部已读'), t('notice_view', '查看公告')],
        /* 点空白关闭时回传的就是 cancelText（answer(dialog.cancelText)）→ 与"稍后"
           同一个文案，避免遮罩点击后 resolve 出一个按钮行里不存在的『取消』。 */
        cancelText: t('notice_later', '稍后'),
        wide: true,
        /* ⚠️ 点空白可以关闭（本轮用户点名的 bug：「记住点击空白处窗口不会自行关闭的bug」）。
           旧注释"用户会不小心点空白把公告弹窗关掉"是旧需求，已被本轮推翻 →
           backdropClose 恢复默认 true。关掉 = 稍后（本次启动不再弹，公告不会丢）。 */
      }).then((value) => {
        if (value === t('notice_view', '查看公告')) { doGoto('notice'); markRead(noticeKey(latest)); }
        else if (value === t('mark_all_read', '全部已读')) markAllRead();
      });
    }

    /* ---------- Github / 反馈 ---------- */
    const lightbox = ref('');
    const sponsorImage = '/res/image/' + encodeURIComponent('微信Galen563的ToolsGCP项目赞助.jpg');
    const feedbackUrl = 'https://github.com/Galen563/ToolsGCP/issues';
    /* ⚠️ 本轮多语言修复（用户原话：「语言切换为其他语言部分地方还是只有简体中文文本内容，
       包括各种地方」）：介绍条目和 QQ 群名原来是**普通数组**，setup 时就固化了中文；
       而且 qqGroups 的 label 是"群名"这种用户可见文字。
       → 都改成 computed（切语言即时重算），文案走语言包；群名用语言包里**早就有**的
         `qq_group_label` / `qq_report_label`（feedback 模块，三语齐全，以前没用上）。
       ⚠️ 文件名（ToolsGCP-改进建议群.jpg）是磁盘上的**真实文件名**，绝不跟着语言变。 */
    /* ★ 本轮修复：以前这里用的 intro_line_1..5 在**任何语言包里都不存在**，
       t() 永远吃兜底中文 → GitHub 页的介绍列表切英/繁体不动（用户原话：
       「Github界面很多地方只有简体中文没有适配三语言」）。github 包里其实早就有
       tools_intro_point1..5 三语齐全（带 '- ' 前缀是旧 py 版纯文本时代的排版），
       这里接上并把行首装饰符剥掉（<li> 自带项目符号，不要双重圆点+横线）。 */
    const introLines = computed(() => [
      t('tools_intro_point1', '免费开源工具集合', 'github'),
      t('tools_intro_point2', '用于解决日常电脑软件查找问题', 'github'),
      t('tools_intro_point3', '提供软件下载、安装、介绍、使用方法', 'github'),
      t('tools_intro_point4', '避免下载到盗版、广告软件、找不到', 'github'),
      t('tools_intro_point5', '提供资源获取等功能', 'github'),
    ].map((line) => String(line || '').replace(/^[-·•*]\s*/, '')));
    const qqGroups = computed(() => [
      { label: t('qq_group_label', '官方QQ改进/建议群：').replace(/[：:]\s*$/, ''),
        number: '312751713',
        image: '/res/image/qq/' + encodeURIComponent('ToolsGCP-改进建议群.jpg') },
      { label: t('qq_report_label', '投诉/举报群：').replace(/[：:]\s*$/, ''),
        number: '973961899',
        image: '/res/image/qq/' + encodeURIComponent('ToolsGCP-投诉举报群.jpg') },
    ]);

    /* ---------- 日志页（读盘走桌面端；接口没有就只给目录入口） ---------- */
    const logFiles = ref([]);
    const logPreview = ref('');
    const logsReady = ref(false);
    async function loadLogFiles() {
      logFiles.value = []; logPreview.value = ''; logsReady.value = false;
      for (const path of ['log.files', 'logs.files', 'log.list']) {
        const result = await bridge.tryCall(path);
        if (result && result.ok) {
          logFiles.value = (result.files || result.logs || []).map((f) => (
            typeof f === 'string' ? { name: f.split(/[\\/]/).pop(), path: f } : { ...f }));
          logsReady.value = true;
          break;
        }
      }
      for (const path of ['log.read_current', 'logs.read_current']) {
        /* ⚠️ 位置参数的坑：以前写成 tryCall(path, 200000)，pywebview 会把它当**实参**
           塞给后端 `LogDomain.read_current()`，而那个方法当时没有形参 →
           控制台刷 `TypeError: read_current() takes 1 positional argument but 2 were given`。
           后端现在已经补上 `tail` 形参（desktop/api/__init__.py），这里保持显式传参。 */
        const result = await bridge.tryCall(path, 200000);
        if (result && result.ok) { logPreview.value = String(result.text || result.content || '').slice(-8000); break; }
      }
    }
    const hasHistory = computed(() => logFiles.value.length > 1);
    /* 点一行日志 → 读它的内容到下面的预览框（原版日志页的行为） */
    const logPreviewName = ref('');
    async function previewLog(file) {
      const path = typeof file === 'string' ? file : (file && file.path) || '';
      if (!path) return;
      const result = await bridge.tryCall('log.read', path);
      if (!result) return needApi('log.read', '读取日志');
      if (!result.ok) {
        toast(result.error || t('read_log_failed', '读取日志失败'), 'error',
          t('title_logs', '日志'));
        return;
      }
      logPreview.value = String(result.text || result.content || '').slice(-8000);
      logPreviewName.value = result.name || path.split(/[\\/]/).pop();
    }
    async function exportLogs(all) {
      /* 和 py 版一致（interfaces/log_interface.py:758-821）：
         弹系统「另存为」→ 用户选位置 → 打包成 zip（默认名 ToolsGCP_Log_<时间戳>.zip /
         ToolsGCP_AllLogs_<时间戳>.zip）。后端 log.export 里已经把这三件事做完了。 */
      const result = await bridge.tryCall('log.export', !!all);
      if (!result) {
        /* 后端还没就绪时不要假装成功 */
        return needApi('log.export', '导出日志');
      }
      if (result.canceled) {
        toast(t('export_canceled', '已取消导出'), 'info', '日志');
        return;
      }
      if (result.ok) {
        toast(t('export_ok', '导出成功') + (result.name ? '：' + result.name : ''), 'success', '日志');
      } else {
        toast(t('export_failed', '导出失败') + '：' + (result.error || ''), 'error', '日志');
      }
    }
    async function openLogDir() {
      const dir = String(info.dataDir || '').replace(/[\\/]+config[\\/]?$/i, '') + '\\logs';
      const result = await bridge.tryCall('shell.open_path', dir);
      if (!result) return needApi('shell.open_path', '打开日志目录');
      if (!result.ok) toast(t('open_log_dir_failed', '打开日志目录失败：') + result.error, 'error');
    }
    async function openPath(path) {
      const result = await bridge.tryCall('shell.open_path', path);
      if (!result) return needApi('shell.open_path', '打开该位置');
      if (!result.ok) toast(t('open_failed_2', '打开失败：') + result.error, 'error');
    }
    async function confirmClearLogs() {
      const yes = await openDialog({ title: t('clear_log', '清理历史日志'), danger: true,
        body: t('clear_confirm', '确定删除全部历史日志吗？\n当前日志（system_log.log）的内容会保留，不会被清除。'),
        confirmText: t('ok', '确定') });
      if (!yes) return;
      const result = await bridge.tryCall('log.clear_history');
      if (!result) return needApi('log.clear_history', '清理历史日志');
      if (result.ok) {
        const removed = (result.removed != null ? result.removed : result.cleared) || 0;
        toast(t('cleared', '已清理 {n} 条历史日志（当前日志已保留）')
          .replace('{n}', removed), 'success', '日志');
      } else toast(t('no_history', '没有可清理的历史日志'), 'info', '日志');
      loadLogFiles();
    }

    /* ---------- 应用部署（deploy_interface.py） ----------
       存盘值一律是**中文字面量**（不可翻译，只显示时查语言键）deploy_interface.py:43-51 */
    const ST_PENDING = '待部署';
    const ST_DOWNLOADING = '下载中';
    const ST_DONE = '已下载';
    const ST_OPENED = '已打开官网';
    const ST_SKIPPED = '已跳过';
    const ST_FAILED = '失败';
    const STATUS_KEYS = {};
    STATUS_KEYS[ST_PENDING] = 'pending';
    STATUS_KEYS[ST_DOWNLOADING] = 'st_downloading';
    STATUS_KEYS[ST_DONE] = 'st_done';
    STATUS_KEYS[ST_OPENED] = 'st_opened';
    STATUS_KEYS[ST_SKIPPED] = 'st_skipped';
    const DEPLOY_SCHEMA = '1.0.0';

    /* 原来这里的从收藏夹导入开关（folderImportOn）已删除 ——
       用户要求部署页不再管一切收藏的事，收藏的导入导出统一归收藏页。 */
    /* 导出模式 / 部署模式**两套独立清单**（各自 localStorage key），互不污染。
       旧版本两种模式共用一个 deploy_config：升级后它归部署模式，导出清单初始为空。 */
    const deployList = ref([]);                   // 部署模式清单
    const exportList = ref([]);                   // 导出模式清单
    const deployRows = computed(() => (settings.deploy_mode ? deployList.value : exportList.value));
    function activeListRef() { return settings.deploy_mode ? deployList : exportList; }
    const deployRunning = ref(false);
    const deployProgress = ref(0);
    const deployIndeterminate = ref(false);       // 不知道总量 → 不确定态滚动条
    const deployStatusText = ref('');
    const downloadDir = ref('~/Downloads/ToolsGCP-Deploy');
    const picker = reactive({ open: false, query: '', picked: [] });

    /* status_text（:414-421）：失败走前缀翻译，认不出来就原样回显存盘值 */
    function statusText(status) {
      const value = String(status == null ? '' : status);
      if (value.indexOf(ST_FAILED + ': ') === 0) {
        return t('st_failed', '失败', 'deploy') + ': ' + value.slice(4);
      }
      const key = STATUS_KEYS[value];
      return key ? t(key, value, 'deploy') : value;
    }
    function setRowStatus(row, status) { row.status = status; saveActiveList(); }
    function resourceOf(code) { return code ? items.value.find((it) => it.code === code) : null; }
    /* _source_text（:545-553）：只在部署模式下兜底 */
    function sourceTextOf(row) {
      const res = resourceOf(row.code);
      if (!res) return t('unknown_code', '资源库里没有这个编码', 'deploy');
      if (res.download_url) return t('source_direct', '直链', 'deploy');
      if (res.github) return 'GitHub Release';                 // 原版硬编码英文（:1044）
      return t('source_page', '官网', 'deploy');
    }
    /* 第 6 列：导出模式只看 path；部署模式看 source，空则 _source_text() */
    function deploySourceOf(row) {
      if (!settings.deploy_mode) return row.path || '';
      return row.source || sourceTextOf(row);
    }
    function deployIconOf(row) {
      const res = resourceOf(row.code);
      return res ? res.icon : '';
    }
    /* _preview_kind（:608-619） */
    function previewKindOf(row) {
      if (!row.code) return null;
      const res = resourceOf(row.code);
      if (!res) return null;
      if (res.download_url) return 'direct';
      if (res.github) return 'github';
      return 'page';
    }
    /* 每条 item 固定 6 键（_normalize_loaded，:450-470） */
    function normalizeItem(raw) {
      const src = (raw && typeof raw === 'object') ? raw : {};
      return { code: String(src.code || ''), name: String(src.name || ''),
        version: String(src.version || ''), path: String(src.path || ''),
        status: src.status ? String(src.status) : ST_PENDING, source: String(src.source || '') };
    }
    function legacyStatus(state) {
      const map = { pending: ST_PENDING, downloading: ST_DOWNLOADING, downloaded: ST_DONE,
        opened: ST_OPENED, skipped: ST_SKIPPED, failed: ST_FAILED };
      return map[state] || ST_PENDING;
    }
    /* 落盘（网页端用 localStorage 等价物，schema 1.0.0）。
       拆成两套：deploy_config = 部署模式，export_config = 导出模式。 */
    function readConfigList(key) {
      const cfg = readLocal(key, null);
      const raw = (cfg && Array.isArray(cfg.items)) ? cfg.items : null;
      return (raw || []).map(normalizeItem);
    }
    function configPayload(list) {
      return { schema_version: DEPLOY_SCHEMA, updated_at: new Date().toISOString(),
        items: list.map(normalizeItem) };
    }
    function loadDeployList() {
      /* 只有"完全没有 deploy_config"时才迁移更老的裸数组 key；
         用户主动清空（items: []）不能被旧数据复活。 */
      const hasDeployConfig = readLocal('deploy_config', null) != null;
      deployList.value = readConfigList('deploy_config');
      if (!hasDeployConfig) {
        const legacy = readLocal('deployList', null);
        if (Array.isArray(legacy)) {
          deployList.value = legacy.map((row) => normalizeItem({
            ...row, status: legacyStatus(row.state) }));
        }
      }
      exportList.value = readConfigList('export_config');
    }
    function saveDeployList() { writeLocal('deploy_config', configPayload(deployList.value)); }
    function saveExportList() { writeLocal('export_config', configPayload(exportList.value)); }
    function saveActiveList() { if (settings.deploy_mode) saveDeployList(); else saveExportList(); }
    async function toggleDeployMode() {
      const next = !settings.deploy_mode;
      await saveSetting('deploy_mode', next);
      const name = next ? t('deploy_mode', '部署模式', 'deploy') : t('export_mode', '导出模式', 'deploy');
      toast(t('current_mode', '当前模式: {name}', 'deploy').replace('{name}', name),
        'info', t('mode_switched', '模式切换', 'deploy'));
    }
    const pickerHits = computed(() => {
      const key = picker.query.trim().toLowerCase();
      const have = new Set(deployRows.value.map((r) => r.code));
      return items.value.filter((it) => !have.has(it.code)
        && (!key || String(it.code).toLowerCase().indexOf(key) >= 0
          || String(it.name).toLowerCase().indexOf(key) >= 0
          || String(it.id).toLowerCase().indexOf(key) >= 0)).slice(0, 500);
    });
    function openPicker() {
      if (!items.value.length) {
        toast(t('unknown_code', '资源库里没有这个编码', 'deploy'), 'error', t('tip_error', '错误', 'deploy'));
        return;
      }
      picker.open = true; picker.picked = []; picker.query = '';
    }
    function togglePick(code) {
      const index = picker.picked.indexOf(code);
      if (index >= 0) picker.picked.splice(index, 1); else picker.picked.push(code);
    }
    function toRow(it) {
      return { code: it.code, name: it.name || it.code, version: '', path: '', status: ST_PENDING, source: '' };
    }
    function applyPicker() {
      const codes = new Set(picker.picked);
      const target = activeListRef();
      const have = new Set(target.value.map((r) => r.code));
      const added = items.value.filter((it) => codes.has(it.code) && !have.has(it.code)).map(toRow);
      if (added.length) {
        target.value = target.value.concat(added);
        saveActiveList();
        toast(t('added_n_from_library', '已从资源库添加 {n} 条', 'deploy').replace('{n}', added.length),
          'success', t('tip_success', '成功', 'deploy'));
      } else {
        toast(t('all_selected_in_list', '选中的应用都已在清单里', 'deploy'), 'info', t('tip_info', '信息', 'deploy'));
      }
      picker.open = false;
    }
    /* 链路 2：从搜索页选择（不再有从收藏夹导入开关，选择条只负责勾选入清单） */
    function startDeploySelection() {
      if (selectionBar.value) exitSelection();
      selectionMode.value = 'deploy';
      doGoto('search');
      selectionBar.value = true;
      /* 需求：清单里已有的资源，进入选择页时应该**已经是勾选状态** */
      const have = new Set(deployRows.value.map((r) => r.code));
      nextTick(() => {
        selectionItems.value.forEach((it) => { it._sel = have.has(it.code); });
      });
    }
    /* 用户要求删掉行内的编辑按钮 —— 编辑函数一并移除，避免死代码。 */
    /* 删除无二次确认（原版 delete 直接 pop + 存盘 + 刷新）。
       ⚠️ 本轮 bug（用户原话）：「部署界面点击垃圾桶跳转到这个对应软件界面中的bug，
          连续速度越快点越容易出现」。
          根因是**事件冒泡 + 时间窗**：垃圾桶的 click 冒泡到行的 @dblclick 上，
          连点两下被浏览器合成 dblclick → 触发 openDeployDetail 跳进详情页；
          而且第一下已经把该行删掉，DOM 重排后第二下可能落到**滑上来的另一行**，
          于是还会连删两条。修法是三层，缺一层都还能复现：
            ① 按钮本身 @click.stop / @dblclick.stop（index.html）；
            ② 行 handler 里再按 target 过滤一次（防止将来又给按钮绑事件漏了 .stop）；
            ③ 这里加 300ms 冷却，挡住"两下都被识别成 click"的极快连点。 */
    let _deployRemoveAt = 0;
    function removeDeployRow(row) {
      const now = Date.now();
      if (now - _deployRemoveAt < 300) return;
      _deployRemoveAt = now;
      const target = activeListRef();
      target.value = target.value.filter((r) => r !== row);
      saveActiveList();
    }
    /* 部署页双击清单行 → 打开该资源的详情页。详情段已把 v-if 扩到 page==='deploy'。
       ⚠️ 操作列（GitHub / 官网 / 删除）上的双击一律不算"双击行"：
          这是垃圾桶误跳详情的第二道闸（见 removeDeployRow 的注释）。 */
    function openDeployDetail(row, event) {
      if (event && event.target && event.target.closest && event.target.closest('.col-op')) return;
      const res = resourceOf(String(row && row.code) || '');
      if (!res) {
        toast(t('deploy_no_resource', '资源库中没有这个编码：') + ((row && row.code) || ''), 'warning');
        return;
      }
      openDetail(res);
    }
    function deployStamp() {
      const d = new Date(), pad = (n) => String(n).padStart(2, '0');
      return String(d.getFullYear()) + pad(d.getMonth() + 1) + pad(d.getDate());
    }
    /* 导出清单（:797-824），默认文件名 ToolsGCP-Deploy-{YYYYMMDD}.json
       需求原话：导出清单是空壳，不能像导入清单那种点了弹出窗口，最后让我选择然后导出文件。
       旧实现走 Blob + <a download>：WebView2 里既不弹"另存为"，下载还可能被拦成空文件。
       现在优先走后端 `shell.save_text_file`（系统另存为对话框 + 真正写盘 + 返回路径）；
       桌面接口缺失时才退回浏览器下载（并明确提示，不假装成功）。 */
    async function exportManifest() {
      const rows = deployRows.value;
      if (!rows.length) {
        toast(t('empty_tip', '列表为空，先「从资源库添加」几条吧', 'deploy'), 'warning', t('tip_warning', '提示', 'deploy'));
        return;
      }
      const filename = 'ToolsGCP-Deploy-' + deployStamp() + '.json';
      let content;
      try {
        const payload = { schema_version: DEPLOY_SCHEMA, generator: 'ToolsGCP',
          exported_at: new Date().toISOString(), count: rows.length,
          items: rows.map(normalizeItem) };
        content = JSON.stringify(payload, null, 2) + '\n';
      } catch (error) {
        toast(t('export_failed', '{title}失败：{err}', 'deploy')
          .replace('{title}', t('export_list', '导出清单', 'deploy'))
          .replace('{err}', (error && error.message) || String(error)),
          'error', t('tip_error', '错误', 'deploy'));
        return;
      }
      const result = await bridge.tryCall('shell.save_text_file', filename, content,
        'JSON 文件 (*.json)');
      if (result && result.ok) {
        if (result.canceled) return;                    // 用户在"另存为"里点了取消：静默
        toast(t('exported', '清单已导出', 'deploy') + ': ' + (result.path || filename),
          'success', t('tip_success', '成功', 'deploy'));
        return;
      }
      if (result && !result.ok) {
        toast(t('export_failed', '{title}失败：{err}', 'deploy')
          .replace('{title}', t('export_list', '导出清单', 'deploy'))
          .replace('{err}', result.error || t('save_failed_short', '保存失败')),
          'error', t('tip_error', '错误', 'deploy'));
        return;
      }
      /* 后端还没有 save_text_file（旧版本桌面端）→ 退回浏览器下载，但明确告知 */
      try {
        downloadJson(filename, content);
        toast(t('exported', '清单已导出', 'deploy') + ': ' + filename
          + '（浏览器下载，桌面端保存对话框接口未就绪）', 'info', t('tip_success', '成功', 'deploy'));
      } catch (error) {
        toast(t('export_failed', '{title}失败：{err}', 'deploy')
          .replace('{title}', t('export_list', '导出清单', 'deploy'))
          .replace('{err}', (error && error.message) || String(error)),
          'error', t('tip_error', '错误', 'deploy'));
      }
    }
    /* 导入清单（:826-850）：**整体替换**，且所有行状态强制重置为「待部署」 */
    function importManifest() {
      const input = document.createElement('input');
      input.type = 'file'; input.accept = '.json,application/json';
      input.onchange = async () => {
        const file = input.files && input.files[0];
        if (!file) return;
        try {
          const data = JSON.parse(await file.text());
          const rows = Array.isArray(data) ? data
            : (Array.isArray(data.items) ? data.items
              : (Array.isArray(data.software) ? data.software : []));
          if (!rows.length) {
            toast(t('import_failed', '导入失败', 'deploy'), 'error', t('tip_error', '错误', 'deploy'));
            return;
          }
          const target = activeListRef();
          target.value = rows.map((row) => {
            const item = normalizeItem(row);
            item.status = ST_PENDING;
            return item;
          });
          saveActiveList();
          toast(t('imported_count', '清单已导入：{n} 项', 'deploy').replace('{n}', target.value.length),
            'success', t('tip_success', '成功', 'deploy'));
        } catch (error) {
          toast(t('import_failed', '导入失败', 'deploy') + ': ' + ((error && error.message) || String(error)),
            'error', t('tip_error', '错误', 'deploy'));
        }
      };
      input.click();
    }
    /* 删除了部署模式的导入清单顺带导入收藏整块逻辑（offerFavoriteImport /
       pickFavoriteFolderAndImport / applyFavoritesToFolder / NEW_FOLDER_VALUE）。
       用户改主意了：部署页不再管收藏，收藏页自己的导入/导出见上面的收藏夹导出 / 导入。 */

    async function confirmClearDeploy() {
      const yes = await confirmDialog(t('clear_list', '清空列表', 'deploy'),
        t('confirm_clear_list', '确定要清空当前清单吗？（本机保存的清单也会一起清空）', 'deploy'),
        t('confirm_clear', '清空', 'deploy'), true);
      if (!yes) return;
      const target = activeListRef();
      target.value = [];
      saveActiveList();
    }
    /* resolve_target 的网页端等价物（downloader.py:118-143）：direct / github / page / unknown */
    function downloadTarget(row) {
      const res = resourceOf(row.code);
      const kind = previewKindOf(row);
      if (kind === 'direct') return { kind: 'direct', url: res.download_url };
      if (kind === 'github') return { kind: 'github', url: res.github };
      if (kind === 'page') return { kind: 'page', url: res.url || res.github || '' };
      return { kind: 'unknown', url: '', error: '该资源没有可用地址' };
    }
    /* _ensure_download_dir（:889-899）：默认 ~/Downloads/ToolsGCP-Deploy，同一批只问一次 */
    async function ensureDownloadDir() {
      const picked = await bridge.tryCall('downloader.choose_dir');
      if (picked && picked.ok && picked.path) downloadDir.value = String(picked.path);
      return downloadDir.value;
    }
    /* 下载（2.6）：不确定态进度条 + 「正在处理: {name}」 */
    async function startDownload(row) {
      const target = downloadTarget(row);
      setRowStatus(row, ST_DOWNLOADING);
      deployProgress.value = 0;
      deployIndeterminate.value = true;
      deployStatusText.value = '正在处理: ' + row.name;
      /* ⚠️⚠️ 本轮修复（用户原话）：「部署页面的部署模式下载的release文件正确 错误文件」。
         根因：GitHub 类资源以前把 **仓库页 URL** 直接交给 downloader.start，
         而 start 只接受**直链**（见 downloader.py 的 _prepare_item：只校验 http(s)）——
         于是存下来的其实是 GitHub 的 HTML 页面（文件名还是资源名，没有扩展名），
         用户看到的就是"下载的文件不对"。
         正确链路（与 Releases 弹窗一致）：resolve_asset(仓库地址) 让后端按
         当前平台/架构挑出真正的 release 资产，再用 asset.download_url +
         asset.name（+ 精确大小）去 start。 */
      let downloadUrl = String(target.url || '');
      let downloadName = row.name;
      let downloadSize = 0;
      let downloadSource = '';
      if (target.kind === 'github') {
        const picked = await bridge.tryCall('downloader.resolve_asset', downloadUrl);
        if (!picked) {
          /* 老桌面端没有 resolve_asset：保持旧行为（打开页面），绝不假装下载成功 */
          deployIndeterminate.value = false;
          deployStatusText.value = '';
          await openLink(downloadUrl, null);
          setRowStatus(row, ST_OPENED);
          toast(t('downloader_not_ready', '下载接口 <downloader.start> 未就绪，已改为打开页面'),
            'warning', t('tip_warning', '提示', 'deploy'));
          return false;
        }
        const asset = (picked.ok && picked.asset) ? picked.asset : null;
        if (!asset || !isHttp(asset.download_url)) {
          /* 没有匹配当前系统的安装包（NO_MATCH / 无 release / 网络失败）：
             把 Releases 页打开让用户自己挑，并在提示里说清楚原因，不偷偷下别的文件。 */
          deployIndeterminate.value = false;
          deployStatusText.value = '';
          setRowStatus(row, ST_OPENED);
          await openLink(String(downloadUrl).replace(/\/+$/, '') + '/releases', null);
          toast(t('deploy_release_no_match',
            '这个项目没有匹配当前系统的安装包，已打开 Releases 页供你手动选择'),
            'warning', t('tip_warning', '提示', 'deploy'));
          return false;
        }
        downloadUrl = String(asset.download_url);
        downloadName = String(asset.name || downloadName);
        downloadSize = Number(asset.size) || 0;
        downloadSource = String(picked.repo || '');
      }
      const result = await bridge.tryCall('downloader.start', downloadUrl,
        downloadName, downloadDir.value, downloadSize, downloadSource);
      deployIndeterminate.value = false;
      if (result && result.ok) {
        setRowStatus(row, ST_DONE);
        deployStatusText.value = '';
        return true;
      }
      /* ⚠️ 桌面端没有下载接口（downloader.start）时退化为打开页面，绝不假装下载成功；
         有接口但下载失败时把后端错误码带出来，别让用户只看到"行变灰"却不知道原因。 */
      await openLink(target.url, null);
      setRowStatus(row, ST_OPENED);
      deployStatusText.value = '';
      if (!result) {
        toast(t('downloader_not_ready', '下载接口 <downloader.start> 未就绪，已改为打开页面'), 'warning', t('tip_warning', '提示', 'deploy'));
      } else {
        toast(t('download_fail', '下载失败：') + (result.error || ''), 'error');
      }
      return false;
    }
    async function openPageSingle(row, event) {
      const res = resourceOf(row.code);
      const url = (res && (res.url || res.github)) || '';
      if (!isHttp(url)) {
        setRowStatus(row, ST_FAILED + ': 该资源没有可用地址');
        return;
      }
      await openLink(url, event);
      setRowStatus(row, ST_OPENED);
    }
    /* ★ 本轮新增（用户原话：「部署模式的…对应的有搜索页卡片上那种官网按钮…
       每个都有，如果有 github 的也要有这个按钮 放在官网按钮左侧」）：
       表格行内的两个链接按钮，取值口径与搜索页卡片完全一致 —— 官网取 res.url、
       代码仓库取 res.github，都过 isHttp() 校验（空 / 非 http(s) 一律当没有）。
       GitHub 按钮是否显示还受设置项 search_show_github 控制（与卡片同一开关）。 */
    function rowSiteUrl(row) {
      const res = resourceOf(row.code);
      const url = (res && res.url) || '';
      return isHttp(url) ? url : '';
    }
    function rowRepoUrl(row) {
      const res = resourceOf(row.code);
      const url = (res && res.github) || '';
      return isHttp(url) ? url : '';
    }
    function openRowSite(row, event) {
      const url = rowSiteUrl(row);
      if (!url) {
        toast(t('deploy_no_site', '这条资源没有官网地址', 'deploy'), 'info', t('tip_info', '信息', 'deploy'));
        return;
      }
      openLink(url, event);
    }
    function openRowRepo(row, event) {
      const url = rowRepoUrl(row);
      if (url) openLink(url, event);
    }
    /* 单条部署（:877-887）：kind 不是 direct/github 时**不再**自动开官网，
       改由行内的「官网 / GitHub」按钮让用户自己点（本轮 user 要求）。 */
    async function deployOne(row) {
      const kind = previewKindOf(row);
      if (kind === 'direct' || kind === 'github') { await startDownload(row); return; }
      const target = downloadTarget(row);
      if (target.kind === 'unknown') { setRowStatus(row, ST_FAILED + ': ' + target.error); return; }
      setRowStatus(row, ST_SKIPPED);
      toast(t('deploy_manual_page', '这一条只有官网 / Releases，请用行右侧的「官网」或「GitHub」按钮打开', 'deploy'),
        'info', t('tip_info', '信息', 'deploy'));
    }
    /* 一键部署（deploy_all，:954-1008） */
    async function confirmDeploy() {
      if (deployRunning.value) {
        toast(t('batch_running', '正在处理', 'deploy'), 'info', t('tip_info', '信息', 'deploy'));
        return;
      }
      if (!deployList.value.length) {
        toast(t('empty_tip', '列表为空，先「从资源库添加」几条吧', 'deploy'), 'warning', t('tip_warning', '提示', 'deploy'));
        return;
      }
      const yes = await openDialog({ title: t('confirm_deploy', '开始部署', 'deploy'),
        body: t('confirm_deploy_body', '将处理清单里的 {n} 个程序：\n· 能从 GitHub / 直链拿到安装包的会自动下载\n· 只有官网 / Releases 的不会自动打开浏览器，请用行右侧的「官网 / GitHub」按钮打开\n（开始前会让你选一个下载目录）', 'deploy')
          .replace('{n}', deployList.value.length),
        confirmText: t('start', '开始', 'deploy'), cancelText: t('cancel', '取消', 'deploy') });
      if (!yes) return;
      await ensureDownloadDir();
      deployRunning.value = true;
      deployIndeterminate.value = false;
      deployProgress.value = 0;
      let done = 0, skipped = 0, failed = 0;
      for (let i = 0; i < deployList.value.length; i += 1) {
        const row = deployList.value[i];
        deployProgress.value = Math.round((i / deployList.value.length) * 100);
        deployStatusText.value = '正在处理: ' + row.name;
        const kind = previewKindOf(row);
        if (kind === 'direct' || kind === 'github') {
          await startDownload(row);
        } else {
          /* ★ 本轮（用户：「部署界面的部署模式就算没有 releases 的也不要自动打开官网」）：
             以前这里对只能拿到官网的条目直接 await openPageSingle() 并 sleep 1200ms，
             一键部署会"哐哐"开一堆浏览器标签页。现在**一律不自动开**：标成「已跳过」，
             由用户自己点行右侧的「官网 / GitHub」按钮（他明确说要有和搜索页卡片一样的按钮）。 */
          const target = downloadTarget(row);
          if (target.kind === 'unknown') setRowStatus(row, ST_FAILED + ': ' + target.error);
          else setRowStatus(row, ST_SKIPPED);
        }
        const value = String(row.status || '');
        if (value === ST_DONE) done += 1;
        else if (value === ST_SKIPPED) skipped += 1;
        else if (value.indexOf(ST_FAILED) === 0) failed += 1;
        deployIndeterminate.value = false;
        saveDeployList();
      }
      deployProgress.value = 100;
      deployStatusText.value = '';
      deployIndeterminate.value = false;
      deployRunning.value = false;
      toast(t('batch_done_summary', '自动下载完成 {done} 个，仅官网（需手动打开）{skipped} 个，失败 {failed} 个', 'deploy')
        .replace('{done}', done).replace('{skipped}', skipped).replace('{failed}', failed),
        'success', t('deploy_done', '部署完成', 'deploy'));
    }
    /* ---------- 搜索页勾选条 ----------
       ⚠️⚠️ 这里以前有个致命 bug：`selectedCount` 统计的是 `filtered`（runQuery 里 map 出来的
       一份**拷贝**），而卡片实际渲染、被点击勾选的是 `groups[].items`（`rowModel` 从 groups 取的）
       —— 勾的根本不是同一批对象，于是 `x / y` 的 x 永远 0、点「添加」永远提示"没勾选"。
       现在统一以 **groups 里的对象** 为唯一真源。 */
    const selectionBar = ref(false);
    const selectionMode = ref('deploy');
    const selectionItems = computed(() => {
      const out = [];
      (groups.value || []).forEach((g) => { (g.items || []).forEach((it) => out.push(it)); });
      return out;
    });
    const selectedCount = computed(() => selectionItems.value.filter((it) => it._sel).length);
    const allSelected = computed(() => selectionItems.value.length > 0
      && selectedCount.value === selectionItems.value.length);
    /* 三态：none / some（半选，显示横线）/ all */
    const selState = computed(() => {
      if (!selectedCount.value) return 'none';
      return allSelected.value ? 'all' : 'some';
    });
    function selectAll(checked) { selectionItems.value.forEach((it) => { it._sel = !!checked; }); }
    function exitSelection() {
      selectionBar.value = false;
      /* 两份对象都清：groups 是渲染真源，items/filtered 是别处的引用 */
      (groups.value || []).forEach((g) => { (g.items || []).forEach((it) => { it._sel = false; }); });
      items.value.forEach((it) => { it._sel = false; });
      filtered.value.forEach((it) => { it._sel = false; });
    }
    function confirmSelection() {
      const picked = selectionItems.value.filter((it) => it._sel);
      if (!picked.length) { toast(t('nothing_selected', '你还没有勾选任何项'), 'warning'); return; }
      const target = activeListRef();
      const have = new Set(target.value.map((r) => r.code));
      const added = picked.filter((it) => !have.has(it.code)).map(toRow);
      target.value = target.value.concat(added);
      saveActiveList();
      toast(t('added_n', '已从资源库添加 {n} 条').replace('{n}', added.length)
        + (added.length < picked.length ? '（' + (picked.length - added.length) + ' 已在清单里）' : ''), 'success');
      exitSelection();
      doGoto('deploy');
    }

    /* ---------- 插件（manifest 走 /res 静态目录，真实文件） ---------- */
    /* 后端 plugins.list 未就绪时的兜底 id。
       ⚠️ 不含 plugin-showcase：它是开发者示例（和 _template 一样）不显示在插件列表里。 */
    const PLUGIN_IDS = ['gcp-ai-agent', 'gcp-plugin-maker'];
    /* 这些 id 不进入插件列表。：
       · 目录/id 以 _ 开头：_template / _archive / _t …（下划线开头 = 开发者模板）
       · plugin-showcase：插件示例（目录名没有下划线，但同样只给开发者看）。
       规则与后端 plugin_manager.py 的 RESERVED_DIR_NAMES 保持一致。 */
    function isHiddenPluginId(id) {
      const text = String(id || '').trim();
      return !text || text.charAt(0) === '_' || text === 'plugin-showcase';
    }
    const pluginQuery = ref('');
    const pluginList = ref([]);
    const pluginsLoading = ref(false);
    const flashPlugin = ref('');
    const devGuide = ref(false);
    const pluginPage = ref(null);
    async function loadPlugins(notify) {
      pluginsLoading.value = true;
      /* 顺便拉一次两个插件根目录的路径（插件页底部那行提示要显示"该往哪放"）。
         失败不影响列表加载 —— 那只是提示文案。 */
      loadPluginDirs().catch(function () {});
      const results = [];
      const listed = await bridge.tryCall('plugins.list');
      const remote = (listed && listed.ok && Array.isArray(listed.plugins)) ? listed.plugins : null;
      const ids = (remote ? remote.map((p) => p.id || p) : PLUGIN_IDS)
        .filter((id) => !isHiddenPluginId(id));
      for (const id of ids) {
        try {
          const response = await fetch('/res/plugins/' + encodeURIComponent(id) + '/manifest.json',
            { cache: 'no-store' });
          if (!response.ok) continue;
          const manifest = await response.json();
          /* manifest.id 也兜一层：目录名正常但 id 以 _ 开头 / 是示例时同样隐藏 */
          if (isHiddenPluginId(manifest.id || id)) continue;
          const settingKey = manifest.enabled_setting || '';
          /* 强制开启（manifest.locked）：插件中心里开关锁死、也不能删。
             ⚠️ 必须在 enabled 之前算：locked 的插件不管设置值是啥都算"开"。 */
          const locked = manifest.locked === true;
          /* 开关状态同样走 settingOn()，旧配置字符串 "false" 不会再把卡片显示成"已启用"。
             ⚠️⚠️ 本轮修「default_disabled 是死字段」：
               原写法 settingKey ? settingOn(settings[settingKey]) : !manifest.default_disabled
               在**键还不存在**时 settingOn(undefined) === false → 声明了 default_disabled:false
               的第三方插件永远显示"已禁用"（和它自己配置页的判断相反）。
               现在：键存在才读它，不存在就按 manifest 的默认值。 */
          const hasValue = !!(settingKey && settings[settingKey] !== undefined
            && settings[settingKey] !== null);
          const enabled = locked ? true
            : (hasValue ? settingOn(settings[settingKey]) : !manifest.default_disabled);
          results.push({
            id: manifest.id || id, name: pickI18n(manifest.name, id),
            description: pickI18n(manifest.description, ''), author: manifest.author || '',
            version: manifest.version || '', builtin: !!manifest.builtin,
            locked, lockable: !locked,
            protected: !!manifest.builtin || locked, enabled_setting: settingKey, enabled,
            hasConfig: !!manifest.config_page,
            /* 联动信息（照 py core/plugin_manager.py + plugin_interface._enable_companion）：
               · companion    —— 启用"我"时把"搭子"一起启用（插件制作辅助 → GCP-AI Agent）；
               · generatedBy  —— "我"被停用时，把由我生成的那些插件全部停用。 */
            companion: String(manifest.companion || ''),
            generatedBy: String(manifest.generated_by || ''),
            frame: manifest.config_page ? '/res/plugins/' + encodeURIComponent(id) + '/'
              + String(manifest.config_page).replace(/^\/+/, '') : '',
            icon: manifest.icon ? '/res/plugins/' + encodeURIComponent(id) + '/'
              + String(manifest.icon).replace(/^\/+/, '') : '',
            note: readLocal('pluginNote.' + (manifest.id || id), ''),
            editingNote: false, noteDraft: '',
            status: enabled ? 'ok' : 'disabled', error: '',
          });
        } catch (error) { /* 单个读不到不影响其它 */ }
      }
      pluginList.value = results;
      if (notify) await new Promise((resolve) => setTimeout(resolve, 420));   // 原版最短显示 420ms
      pluginsLoading.value = false;
      if (notify) toast(t('reloaded', '重新加载: {n} 个').replace('{n}', results.length), 'success');
      else if (!results.length) loadPluginsFallbackNotice();
    }
    let notifiedEmpty = false;
    function loadPluginsFallbackNotice() { /* 空列表是正常状态，不打扰 */ }
    const filteredPlugins = computed(() => {
      const key = pluginQuery.value.trim().toLowerCase();
      if (!key) return pluginList.value;
      return pluginList.value.filter((p) => [p.name, p.id, p.author, p.description]
        .some((v) => String(v || '').toLowerCase().indexOf(key) >= 0));
    });
    const pluginCountText = computed(() => {
      const enabled = pluginList.value.filter((p) => p.enabled).length;
      let text = '共 ' + pluginList.value.length + ' 个，已启用 ' + enabled + ' 个';
      if (pluginQuery.value.trim()) text += '，筛出 ' + filteredPlugins.value.length + ' 个';
      return text;
    });
    /* 找到某个插件对象（联动时按 id 找） */
    function pluginById(id) { return pluginList.value.find((p) => p.id === id) || null; }
    /* 把某个插件的开关写下去（不弹提示，供联动用） */
    async function setPluginEnabled(plugin, enable) {
      if (!plugin) return false;
      plugin.enabled = enable;
      plugin.status = enable ? 'ok' : 'disabled';
      if (plugin.enabled_setting) await saveSetting(plugin.enabled_setting, enable);
      return true;
    }
    async function togglePlugin(plugin) {
      /* 强制开启的插件：开关是锁死的，后端也会拒绝 —— 这里先拦一道，别让它拨了又回弹 */
      if (plugin.locked) { toast(t('plugin_locked', '这是内置的强制开启插件，无法关闭'), 'info'); return; }
      if (!plugin.enabled_setting) { toast(t('no_switch', '这个插件没有提供开关配置'), 'info'); return; }
      const next = !plugin.enabled;
      /* ⚠️ 关闭插件时把它正开着的配置页一起收掉：
         插件关了、config.html 还挂在 iframe 里的话，它继续每秒/30 秒轮询、
         继续能写全局设置（用户的要求是"关掉就不占资源、也不该还能动"）。 */
      if (!next && pluginPage.value && pluginPage.value.id === plugin.id) pluginPage.value = null;
      plugin.enabled = next;
      plugin.status = next ? 'ok' : 'disabled';
      const saved = await saveSetting(plugin.enabled_setting, next);
      if (!saved) { plugin.enabled = !next; plugin.status = next ? 'disabled' : 'ok'; return; }
      /* ---------- 联动 ----------
         · 启用时 → `_enable_companion`：把 manifest 里的 `companion` 一起启用（**只开不关**；
           插件制作辅助开着时顺带启用 GCP-AI Agent，这条方向保留）。
         · 停用 插件制作辅助 → 把它生成的插件（manifest.generated_by == 自己）全部停用。
         · 删掉了停用 GCP-AI Agent → 连坐停用插件制作辅助——用户明确
           /plugin 只跟插件制作辅助走，Agent 开启不算、关掉当然也不该影响它，
           连坐会让"只开制作辅助、单独关 Agent"时 /plugin 直接失效。 */
      if (next) {
        const companion = pluginById(plugin.companion);
        if (companion && !companion.enabled) {
          await setPluginEnabled(companion, true);
          toast(t('companion_enabled', '已同时启用搭子插件：{name}')
            .replace('{name}', companion.name), 'info');
        }
      } else {
        if (plugin.id === 'gcp-ai-agent') {
          /* 关闭 AI Agent → 一并关闭插件制作辅助。 */
          const maker = pluginById('gcp-plugin-maker');
          if (maker && maker.enabled) {
            await setPluginEnabled(maker, false);
            toast(t('agent_off_maker_off', '已同时关闭「插件制作辅助」'), 'info');
          }
        }
        if (plugin.id === 'gcp-plugin-maker') {
          const generated = pluginList.value.filter((p) => p.generatedBy === plugin.id && p.enabled);
          for (const one of generated) await setPluginEnabled(one, false);
          if (generated.length) {
            toast(t('generated_disabled', '已同时停用它生成的 {n} 个插件')
              .replace('{n}', generated.length), 'info');
          }
        }
      }
      await new Promise((resolve) => setTimeout(resolve, 240));               // 保住开关动画
      toast(plugin.name + ': ' + (next ? '启用' : '禁用'), next ? 'success' : 'info');
    }
    function startNote(plugin) {
      plugin.noteDraft = plugin.note || '';
      plugin.editingNote = true;
      /* 点备注即进入输入态并自动聚焦/全选（需求：不要再点第二下） */
      nextTick(() => {
        const el = document.querySelector('.note-input[data-pid="' + plugin.id + '"]');
        if (el && el.focus) { el.focus(); if (el.select) el.select(); }
      });
    }
    function saveNote(plugin) {
      const note = String(plugin.noteDraft || '').slice(0, 20);
      plugin.note = note; plugin.editingNote = false;
      writeLocal('pluginNote.' + plugin.id, note);
      toast(t('note_saved', '备注已保存：{note}').replace('{note}', note || t('empty_paren', '（空）')), 'info');
    }
    function cancelNote(plugin) { plugin.editingNote = false; }
    async function deletePlugin(plugin) {
      if (plugin.locked) { toast(t('plugin_locked', '这是内置的强制开启插件，无法关闭'), 'info'); return; }
      if (plugin.protected) { toast(t('builtin_locked', '内置示例插件，不可删除'), 'warning'); return; }
      const yes = await openDialog({ title: t('delete_plugin', '删除插件'), danger: true,
        body: t('delete_plugin_confirm', '确定要删除插件「{name}」吗？插件文件夹会被整个删掉。')
          .replace('{name}', plugin.name), confirmText: t('delete', '删除') });
      if (!yes) return;
      const result = await bridge.tryCall('plugins.delete', plugin.id);
      if (!result) return needApi('plugins.delete', '删除插件');
      if (result.ok) {
        toast(t('plugin_deleted', '已删除插件: {name}').replace('{name}', plugin.name), 'info');
        await loadPlugins(false);
      } else toast(result.error || t('delete_failed', '删除失败'), 'error');
    }
    function openPluginPage(plugin) {
      /* ⚠️ 需求：「配置界面按钮并不是打开文件夹」，照着 py 版来 ——
         py `plugin_interface.open_config`：没有配置页面时**只提示**、什么都不打开
         （卡片上的⚙按钮直接置灰，tooltip 写「这个插件没有配置界面（或没加载成功）」）。 */
      if (!plugin.hasConfig || !plugin.frame) {
        toast(t('config_unavailable', '这个插件没有配置界面（或没加载成功）'), 'warning');
        return;
      }
      pluginPage.value = { name: plugin.name, frame: plugin.frame, id: plugin.id };
      silentMotion();
      /* iframe 刚挂载时 src 文档还没解析完，message 会丢 —— 等一帧再推一次，
         真正可靠的时点是 iframe 的 load 事件（index.html 的 @load 那一条）。 */
      nextTick(() => syncPluginTheme('open'));
    }
    async function openPluginDir() {
      /* ⚠️ 以前这里写死 `info.configDir + '\\plugins'`（= 程序目录旁的内置插件目录）。
         exe 打包后那个目录在 exe 本体里/可能只读，用户"打开插件目录想去放插件"
         结果既放不进去、也看不到自己装的插件 —— 这就是"插件做好了放不到原生插件文件夹"
         的前端那一半。现在交给后端 `plugins.open_dir`：
           · 默认打开**用户可写**的 `<数据根>\plugins`（不存在会先建出来）；
           · 后端拿不到路径时才退回内置目录。
         两个根都会扫描加载（见 desktop/api/plugins.py 的 plugins_dirs()），
         所以用户把插件放进哪个都能生效。 */
      const result = await bridge.tryCall('plugins.open_dir', 'user');
      if (!result) {
        /* 老后端没有这个接口：退回原来的 shell.open_path，至少别让按钮点了没反应 */
        const dir = (info.configDir || '') + '\\plugins';
        const legacy = await bridge.tryCall('shell.open_path', dir);
        if (!legacy) return needApi('plugins.open_dir', t('open_plugin_dir', '打开插件目录'));
        if (!legacy.ok) toast(t('open_plugin_dir_failed', '打开插件目录失败：') + legacy.error, 'error');
        return;
      }
      if (!result.ok) {
        toast(t('open_plugin_dir_failed', '打开插件目录失败：') + (result.error || ''), 'error');
        return;
      }
      toast(t('open_plugin_dir_done', '已打开插件目录：') + (result.path || ''), 'info');
    }
    /* 两个插件根目录的信息（插件页底部那行提示用：告诉开发者该往哪放） */
    const pluginDirs = ref({ user: '', builtin: '', list: [] });
    async function loadPluginDirs() {
      const result = await bridge.tryCall('plugins.dirs');
      if (result && result.ok) {
        pluginDirs.value = {
          user: String(result.user_dir || ''),
          builtin: String(result.builtin_dir || ''),
          list: Array.isArray(result.dirs) ? result.dirs : [],
        };
      }
    }
    function setPluginView(mode) { saveSetting('plugin_view', mode); }

    /* ---------- 提交软件（资源制作器）
       依据：resource_maker_interface.py / resource_maker_pages.py / resource_maker_core.py
       四个分节：投稿表单 / 资源浏览 / 批量合成 / 使用说明（:36-41） ---------- */
    const makerLanguages = ['简体中文', '繁體中文', 'English'];          // 固定规范名（:572）
    /* CATEGORIES：resource_maker_core.py:26-32（31 项，顺序即界面顺序） */
    const makerCategories = ['工具', '游戏', '平台', '编程', '游戏引擎', '视频平台', '建筑/设计',
      'AI', '个性化', '其他', '剪辑', '音频', '图像', '设计', '办公', '学习', '网络', '系统',
      '安全', '驱动', '开发工具', '数据库', '聊天', '音乐', '阅读', '下载工具', '压缩解压',
      '远程控制', '虚拟机', '直播', '浏览器'];
    /* 「官方」「知名」：用户要求放在**提交软件·类别下拉的最底下**（第三轮）。
       ⚠️ 故意**不**塞进 makerCategories：那 31 项与 py 侧 CATEGORIES 是契约
          （顺序即界面顺序，不许增删/重排），塞进去会连带把搜索页分组顺序、
          筛选候选一起搞乱。这里单独一份、只追加到制作器的下拉候选末尾。
       三语译名走 termIn —— common_language.json 里已有 term_官方 / term_知名
       （简体「官方/知名」、繁体「官方/知名」、English「Official/Popular」）。 */
    const makerCategoryExtras = ['官方', '知名'];
    /* 制作器「适用系统」胶囊：必须和 resource_schema.py 的 SYSTEMS 同序同项
       （顶层那份 SYSTEMS 是给搜索页筛选当兜底用的，这里是制作器自己的一份，
        两份不一致会出现"制作器里选不了、筛选里却有"或反过来）。
       ⚠️ m04188 第④项扩充：新增 iPadOS / watchOS / tvOS / visionOS / HarmonyOS / ChromeOS。
       （ARCHITECTURES 那一档已在 m03713 第⑤项整体删除，注释里的旧行号一并清掉。） */
    const makerPlatforms = ['全平台', 'Windows', 'macOS', 'Linux', 'Android', 'iOS',
                            'iPadOS', 'watchOS', 'tvOS', 'visionOS', 'HarmonyOS', 'ChromeOS',
                            'web', '其他'];
    /* REPO_PLATFORMS：resource_maker_core.py:41-48（顺序即下拉顺序） */
    /* ⚠️ 本轮多语言：最后两项（自定义 / 不开源）是用户可见文字，原来写死在数组里。
       → 改 computed + t()（专名 GitHub/GitCode/Gitee/GitLab 不翻）。
       ⚠️ 顺手把 key 保持不变（'custom'/'none' 是后端认的值，翻的是 label）。 */
    const REPO_PLATFORMS = computed(() => [
      { key: 'github', label: 'GitHub', prefix: 'https://github.com/' },
      { key: 'gitcode', label: 'GitCode', prefix: 'https://gitcode.com/' },
      { key: 'gitee', label: 'Gitee', prefix: 'https://gitee.com/' },
      { key: 'gitlab', label: 'GitLab', prefix: 'https://gitlab.com/' },
      { key: 'custom', label: t('repo_platform_custom', '自定义'), prefix: '' },
      { key: 'none', label: t('repo_platform_none', '不开源'), prefix: '' },
    ]);
    const repoPlatformOptions = computed(() => REPO_PLATFORMS.value
      .map((p) => ({ value: p.key, label: p.label })));

    /* ---------- 多组开源仓库 ----------
       用户原话：「提交软件中开源仓库支持多个同时有，所以增加一个加号图标的按钮
       点击增加一组，还有垃圾啊桶删除对应组。」
       形态：maker.repos = [{_key, platform, url}, ...]（每一组一行表单）。
       ⚠️ 这一整块必须放在 maker 的 reactive 之前：下面 let repoRowSeq = 0 是 TDZ
          （暂时性死区），而 maker 初始化时就会调用 newRepoRow()，
          声明写在后面会在 setup 一开始就 ReferenceError。
       ⚠️ 落盘形态（后端 resource_schema.repos）是 list[dict]{platform,url}，
          而 github 字段继续写**第一组**（= 主仓库）—— 卡片右下角的仓库按钮、
          下载部署、AI 工具那些只读 github 单值的代码因此一行都不用改，
          老数据（只有 github 一条）读出来也自动有一行。 */
    /* 行数上限：与后端 resource_schema 的 repos 行数上限（20）一致，
       到顶就明说为什么不能再加，而不是按钮默默没反应。 */
    const REPOS_MAX_ROWS = 20;
    let repoRowSeq = 0;
    /* 每行带一个自增内部键：模板 :key 用它而不是数组下标 ——
       删掉中间一行时按下标当 key，Vue 会复用错行，输入框里的文字会「串行」。 */
    function newRepoRow(platform, url) {
      repoRowSeq += 1;
      return {
        _key: repoRowSeq,
        platform: String(platform || 'github'),
        url: String(url || ''),
      };
    }
    function addRepoRow() {
      if (maker.repos.length >= REPOS_MAX_ROWS) {
        toast(t('repos_too_many', '开源仓库最多 20 组', 'maker'), 'warning',
          t('tip_warning', '提示', 'maker'));
        return;
      }
      maker.repos.push(newRepoRow());
      refreshPreview();
    }
    function removeRepoRow(index) {
      maker.repos.splice(index, 1);
      refreshPreview();
    }
    /* 落盘用：逐组补全平台前缀，丢掉「不开源」和空地址的组。
       判定口径必须和后端 resource_schema._normalize_repos 对齐（http(s) 开头才算数）。 */
    function reposForEntry() {
      const out = [];
      maker.repos.forEach((row) => {
        const platform = String((row && row.platform) || '').trim();
        if (!platform || platform === 'none') return;
        const url = normalizeRepoUrl(platform, String((row && row.url) || '').trim());
        if (!url) return;
        out.push({ platform: platform, url: url });
      });
      return out;
    }
    /* 读回来：优先按 raw.repos 还原每一组；老数据只有 github 一条 → 兜成一行。 */
    function loadReposFromRaw(raw) {
      const rows = [];
      const list = Array.isArray(raw && raw.repos) ? raw.repos : [];
      list.forEach((item) => {
        if (!item || typeof item !== 'object') return;
        const url = String(item.url || '').trim();
        if (!url) return;
        rows.push(newRepoRow(String(item.platform || '') || detectRepoPlatform(url), url));
      });
      if (!rows.length) {
        const legacy = String((raw && raw.github) || '').trim();
        if (legacy) rows.push(newRepoRow(detectRepoPlatform(legacy), legacy));
      }
      if (!rows.length) rows.push(newRepoRow());
      return rows;
    }
    /* 平台名（详情页逐行列出多组仓库时当标签用）。 */
    function repoPlatformLabel(platform) {
      const key = String(platform || '');
      const hit = REPO_PLATFORMS.value.find((p) => p.key === key);
      return hit ? hit.label : t('row_github', 'GitHub', 'maker');
    }
    /* 详情页/列表要显示的仓库组：repos 有就用它，没有就退回老的 github 单值。 */
    function repoRowsFor(item) {
      const out = [];
      const list = (item && Array.isArray(item.repos)) ? item.repos : [];
      list.forEach((row) => {
        if (!row || !row.url) return;
        out.push({ label: repoPlatformLabel(row.platform), url: String(row.url) });
      });
      if (!out.length && item && isHttp(item.github)) {
        out.push({ label: repoPlatformLabel('github'), url: String(item.github) });
      }
      return out;
    }
    /* 资源浏览表那一列：一条一行显示不下，多组就显示「第一组 +N」，悬停给出全部。 */
    function repoListText(item) {
      const list = repoRowsFor(item);
      if (!list.length) return '';
      return list.length > 1 ? (list[0].url + ' +' + (list.length - 1)) : list[0].url;
    }
    function repoListTitle(item) {
      return repoRowsFor(item).map((r) => r.label + '  ' + r.url).join('\n');
    }

    /* 必须是 computed —— 以前是普通数组，setup 时就把 `t()` 的返回值（当时语言包还没加载，
       只能是代码里的中文 fallback）冻结了，切到 English/繁體 后顶部四个分段标签仍是中文。 */
    const makerSections = computed(() => [
      { key: 'form', label: t('section_form', '投稿表单', 'maker'), icon: 'edit' },
      { key: 'browser', label: t('section_browser', '资源浏览', 'maker'), icon: 'library' },
      { key: 'batch', label: t('section_batch', '批量合成', 'maker'), icon: 'folder' },
      { key: 'help', label: t('section_help', '使用说明', 'maker'), icon: 'info' },
    ]);
    const activeSection = ref('form');
    const i18nEnabled = ref(true);           // 多语言开关默认开启（:562）
    const i18nLangIndex = ref(0);
    const maker = reactive({
      name: '', id: '', code: '',
      /* ⚠️ 本轮契约变更（用户原话）：「我其他输入框在多语言字段这里都是可以输入不同内容
         以达到真正的多语言这个功能，而我这个类别和标签三个语言来回切换我发现他们都是
         同一个输入池而不是独立的，他们不需要同步更改，他们是多语言字段部分的！」
         → category / tags 从"一个逗号字符串"改成**按语言独立的三个池**：
              { 简体中文: '工具, 系统', 繁體中文: '工具, 系统', English: '工具' }
           每个池里存的都是**规范中文值**（输入时按该语言还原，见 canonicalIn），
           所以三种语言可以填完全不同的内容、互不覆盖。
           落盘形态由 buildEntry 决定：三语一致 → 塌缩成 list[str]（与老数据同形）；
           不一致 → 写 {语言: list[str]} 字典（由后端 resource_schema/maker 支持，见 task-4）。
         默认：类别三语都是「工具」（内置项，各语言显示自己的译名），标签**全空**
         （本轮需求：「而且默认标签输入框为空」）。 */
      category: { 简体中文: makerCategories[0], 繁體中文: makerCategories[0], English: makerCategories[0] },
      tags: { 简体中文: '', 繁體中文: '', English: '' },
      systems: [],
      icon: '', iconName: '', iconSource: '', iconPicked: false, iconExt: '',
      /* iconPending / iconData（m05525「导入图片选择后应该是预览状态而不是直接保存替换」）：
         选中图片只进内存当预览，**不立刻写盘**；真正落盘推迟到点「追加到本机资源库」/
         「保存到原列表」/「另存为独立资源库」那一刻，用那时的最终文件名写。
         这同时治掉老毛病：以前选图立刻落盘、之后改名称只改内存里的 iconName，
         于是索引里写着一个从没存在过的文件名，而图片躺在图标目录里叫另一个名字。 */
      iconPending: false, iconData: '',
      /* 自定义链接（m05525）：一行 = 一个「标签 + 链接」，标签与链接都跟着语言走，
         所以每行存成 {label: {三语}, url: {三语}}，落盘前才由后端塌成字符串。 */
      links: [],
      /* _tagsAuto / restoreTagsFollow（「跟随类别」那套联动）已按本轮需求**整条删除**：
         用户原话「提交软件页面的标签跟随类别这个相关代码删除包括跟随类别按钮，
         而且默认标签输入框为空」。标签现在就是一个独立的、按语言分开填的输入框。 */
      /* 名称联动开关（m04188 ③）：true = 多语言卡片里的三种名称跟着上方「名称」一起变；
         用户在下面手动改过任何一种语言名称后置 false，此后上方再改也不覆盖下面。 */
      _nameAuto: true,
      url: '', author_url: '', chat_url: '',
      /* 开源仓库：可以同时挂多组（GitHub + Gitee + …），每一组一行表单。
         github 字段落盘时写第一组（主仓库），老代码读 github 照旧。 */
      repos: [newRepoRow()],
      i18n: {
        简体中文: { name: '', description: '', intro: '', supplement: '' },
        繁體中文: { name: '', description: '', intro: '', supplement: '' },
        English: { name: '', description: '', intro: '', supplement: '' },
      },
      listedAt: '', loadedId: '', loadedName: '', loadedDownloadUrl: '', isNewEntry: true,
      /* 下载**页面**的网址（用户填的下载地址）。
         ⚠️ 和 loadedDownloadUrl（安装包**直链**）是两种语义，别混。 */
      downloadPageUrl: '',
      /* 编辑已有资源模式（从资源浏览双击 / 载入到制作资源进入）：
         产出区多一个保存到原列表，写回时强制用载入时的 id/code，避免改 id 后新增重复条目。 */
      editingExisting: false, editingId: '', editingCode: '',
      codeAuto: true,
    });
    /* makerLoad（载入现有资源弹层的状态）已随弹层一起删除，不再需要。 */
    /* ---------- 类别 / 标签：「多语言字段」里的两个**独立语言池** ----------
       两轮需求合起来的最终形态（用户原话按时间顺序）：
         第 1 轮：「类别和标签没有和其他的一样切换而且他们是独立的…切换到不同语言
                   上面那个多语言字段 ui 也会变为不同的，包括下拉框的内容」
         第 2 轮：「我其他输入框在多语言字段这里都是可以输入不同内容以达到真正的多语言
                   这个功能，而我这个类别和标签三个语言来回切换我发现他们都是同一个输入池
                   而不是独立的，他们不需要同步更改，他们是多语言字段部分的！」
                   +「标签跟随类别这个相关代码删除包括跟随类别按钮，而且默认标签输入框为空」
       落地成四条规则：
         ① maker.category / maker.tags 是 {简体中文, 繁體中文, English} 三个池，
            切分段 = 切池子，三种语言各填各的、互不覆盖（这才是"真正的多语言"）；
         ② 每个池里存的永远是**规范中文值**（逗号分隔），显示时按该池的语言翻成译名；
         ③ 输入/选中的写法只要是内置项（三种语言的任一种写法）就还原成规范值，
            认不出来的自定义文本原样保留、可继续手改；
         ④ 落盘：三语相同 → list[str]（与老数据同形）；不同 → 三语字典（后端 task-4 支持）。
         ⚠️ 「跟随类别」联动已整条删除（含按钮）；标签默认全空。
       ⚠️ 依赖 I18N.terms（后端 i18n.bundle 下发的三语译名表）与 i18nLangIndex，
          两者都是 reactive ⇒ 切分段、设置里切语言都会自动重算。 */
    /* ⚠️ 下面三个 computed 都带 void I18N.version：term()/译名表读的是语言包，
       设置里切换界面语言（flattenI18n → version+1）时必须重算，
       否则分段显示会停在旧语言那一份写法上（项目里一贯的写法，别省）。 */
    const makerSegLang = computed(() => {
      void I18N.version;
      return makerLanguages[i18nLangIndex.value] || '简体中文';
    });
    /* 可编辑 combo 的选项（31 项，顺序与 py CATEGORIES 完全一致 —— 不许增删/重排）。
       ⚠️ value 也用译名：combo 靠 String(o.value)===String(modelValue) 判断"当前项"，
          而 model-value 交出去的是显示文本，两边必须是同一套写法，否则高亮项永远找不到。
          下拉内容跟着**分段语言**变（用户原话：「切换到不同语言…包括下拉框的内容」）。 */
    const makerCategoryOptions = computed(() => makerCategories.concat(makerCategoryExtras).map((c) => {
      const label = termIn(makerSegLang.value, c);
      return { value: label, label: label };
    }));
    /* ---------- 类别 / 标签 = 「多语言字段」里的两个独立输入池 ----------
       读写都只碰**当前分段**那一份（maker.category[分段] / maker.tags[分段]），
       切分段就是切池子，三种语言互不覆盖 —— 这正是本轮修的那个 bug
       （以前三个分段共用一个字符串，用户以为是"同一个输入池"）。
       · 池里存的永远是**规范中文值**（逗号分隔）；
       · 显示 = 该池按当前分段语言翻成译名（内置项有译名，自定义项原样）；
       · 输入 = 先按当前分段还原，再扫另外两种语言兜底（"和内置一样的文本同样视为内置"），
         认不出来的自定义文本原样保留、可继续手改；
        · 例外（本轮用户定夺）：**从下拉里选内置项**时三个语言池一起换成这一项 —— 见下面「分段写入的口径」。 */
        /* ---------- 分段写入的口径（本轮用户定夺后的最终版） ----------
       两种来源两种语义，别再混：
       ① **从下拉里选内置项**（Combo.pick 抛的 change 第二个参数 = true）⇒ 三个语言池
          **同时**换成这一项。用户原话：「如果切换内置的类别中的选项应该三语言一起
          同时切换而不是只切换一个语言的」。以前只写当前分段，没编辑过的分段会停在
          resetMakerForm 预填的默认「工具」，落盘成 {简体中文:[编程],繁體中文:[工具],
          English:[工具]} 这种三岔字典（实测就是资源库里的 TG-000055 Git）。
       ② **手打的文本**（Combo.onEditInput 抛的第二个参数 = false）⇒ 只写当前分段那一份
          池子，段间互不污染（第一轮锁死的行为，本轮保持不变）：自定义内容本来就没有
          另外两种语言的写法，替用户瞎填另外两段反而是一种污染。
       落盘侧：三池同值由 poolsForEntry() 塌缩成 list[str]，真不同才写字典。 */
    const makerCategoryText = computed({
      get: () => termsToText(makerSegLang.value, splitList(maker.category[makerSegLang.value])),
      set: (text) => {
        // 输入先过 canonicalTerm：任一种语言的写法都还原成规范中文，显示文本绝不落盘。
        // 只写当前分段这一份池子 —— 分段之间互不污染（第一轮定下的行为，手打口径不变）。
        maker.category[makerSegLang.value] = splitList(text).map(canonicalTerm).filter(Boolean).join(', ');
        refreshPreview();
      },
    });
    const makerTagsText = computed({
      get: () => termsToText(makerSegLang.value, splitList(maker.tags[makerSegLang.value])),
      set: (text) => {
        maker.tags[makerSegLang.value] = splitList(text).map(canonicalTerm).filter(Boolean).join(', ');
        refreshPreview();
      },
    });
    /* 把界面上的译名（"Tools" / "工具" / "遊戲"）还原成库里的规范值（"工具" / "游戏"）；
       认不出来的自定义值原样返回（对齐 py 的 _canonical_term）。
       ⚠️ 本轮：不再只认**界面语言**那一份写法 —— 三种语言的写法都要认。
          制作器的类别/标签现在跟着「多语言字段」的分段走，English 分段敲 "Tools"、
          繁體分段敲 "遊戲"、简体分段敲 "游戏"，指的都是同一个内置项，
          都必须还原成规范值落盘（用户原话：「手动输入在类别里的文本和内置一样的
          同样视为内置的多语言」）。
          顺序：先按当前分段还原（分段优先），再扫另外两种语言兜底。 */
    function canonicalTerm(text) {
      const value = String(text == null ? '' : text).trim();
      if (!value) return '';
      if (makerCategories.indexOf(value) >= 0) return value;
      /* 「官方」「知名」也是内置项（它们在译名表里，只是**不在**那 31 项类别里，
         所以不进 makerCategories —— 见 makerCategoryExtras 的注释） */
      if (makerCategoryExtras.indexOf(value) >= 0) return value;
      const segLang = makerLanguages[i18nLangIndex.value] || '简体中文';
      const bySeg = canonicalIn(segLang, value);
      if (bySeg !== value) return bySeg;
      for (const lang of makerLanguages) {
        const hit = canonicalIn(lang, value);
        if (hit !== value) return hit;
      }
      return value;                 // 自定义类别/标签：原样保留，可继续手动修改
    }
    /* 磁盘形态（list / 逗号串 / 三语字典）→ 三个规范值池 {语言: '规范值, 规范值'}。
       ⚠️ 每个池都过一遍 canonicalTerm：老数据里可能直接写着英文/繁体写法（历史脏值），
          灌进池子时顺手还原成规范值，避免"显示时又翻一次"造成串味。 */
    function poolsFromRaw(value) {
      const pools = { 简体中文: '', 繁體中文: '', English: '' };
      const fill = (lang, text) => {
        pools[lang] = splitList(text).map(canonicalTerm).filter(Boolean).join(', ');
      };
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        makerLanguages.forEach((lang) => {
          const one = value[lang] != null ? value[lang]
            : (lang === '繁體中文' && value['繁体中文'] != null ? value['繁体中文'] : value['简体中文']);
          fill(lang, Array.isArray(one) ? one.join(', ') : String(one == null ? '' : one));
        });
        return pools;
      }
      const shared = (Array.isArray(value) ? value : [value])
        .map((v) => String(v == null ? '' : v)).join(', ');
      makerLanguages.forEach((lang) => fill(lang, shared));
      return pools;
    }
    let iconRenameTimer = 0;

    /* 资源库 = 同一个 .ToolsGCP/ToolsGCP-Resources.json（四页共读） */
    const libraryExists = computed(() => items.value.length > 0);
    function libraryFullPath() {
      const base = String(info.configDir || '').replace(/[\\/]+$/, '');
      if (!base) return '.ToolsGCP\\ToolsGCP-Resources.json';
      return /\.ToolsGCP$/i.test(base) ? base + '\\ToolsGCP-Resources.json'
        : base + '\\.ToolsGCP\\ToolsGCP-Resources.json';
    }
    function libraryDir() { return libraryFullPath().replace(/[\\/][^\\/]*$/, ''); }
    const libraryTooltip = computed(() => libraryFullPath() + '\n'
      + t('library_tooltip', '资源库固定是程序目录下的 .ToolsGCP/ToolsGCP-Resources.json，制作器不会另外生成一份；\n每次写盘前会把旧文件滚动备份成固定名的 1 份：用户数据目录 backups/ToolsGCP-Resources.prev.json。', 'maker'));
    const libraryStatusText = computed(() => (libraryExists.value
      ? t('library_count', '资源库 {n} 条', 'maker').replace('{n}', items.value.length)
      : t('library_missing', '资源库还没建', 'maker')));
    /* library_label：只放文件名（卡片内宽 240px，整条路径会折四五行） */
    const libraryLabel = computed(() => (libraryExists.value
      ? t('library_path_hint', '资源库：{path}\n当前共 {n} 条', 'maker')
        .replace('{path}', 'ToolsGCP-Resources.json').replace('{n}', items.value.length)
      : t('library_not_found_hint', '未找到本机资源库，\n「追加到本机资源库」会新建一份。', 'maker')));

    function nowIso() { return new Date().toISOString().slice(0, 19); }
    function nowListedAt() {
      const d = new Date(), p = (n) => String(n).padStart(2, '0');
      return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' '
        + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
    }
    /* slugify：resource_maker_core.py:303-309 */
    function slugify(text) {
      return String(text || '').toLowerCase().replace(/[\s_]+/g, '-')
        .replace(/[^a-z0-9-]/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '');
    }
    /* auto_http_url：没有 scheme 就补 https://（:335-340） */
    function autoHttpUrl(value) {
      const text = String(value || '').trim();
      if (!text) return '';
      return /^[a-z][a-z0-9+.-]*:\/\//i.test(text) ? text : 'https://' + text;
    }
    /* normalize_repo_url：resource_maker_core.py:133-157 */
    function normalizeRepoUrl(platform, value) {
      const raw = String(value || '').trim();
      if (!raw || platform === 'none') return '';
      if (platform === 'custom') return raw;
      const def = REPO_PLATFORMS.value.find((p) => p.key === platform);
      if (!def || !def.prefix) return raw;
      let rest = raw.replace(/^https?:\/\//i, '').replace(/^www\./i, '').replace(/^\/+/, '');
      const host = def.prefix.replace(/^https?:\/\//i, '').replace(/\/+$/, '');
      if (rest.toLowerCase().indexOf(host.toLowerCase()) === 0) rest = rest.slice(host.length).replace(/^\/+/, '');
      return def.prefix + rest;
    }
    /* detect_repo_platform：resource_maker_core.py:160-168 */
    function detectRepoPlatform(url) {
      const value = String(url || '');
      if (!value) return 'none';
      const hit = REPO_PLATFORMS.value.find((p) => p.prefix && value.indexOf(p.prefix) === 0);
      return hit ? hit.key : 'custom';
    }
    /* repoPrefix / repoPreviewText 已按本轮需求删除（用户原话：「开源仓库那里我不需要这个
       提示 ui 了例如 https://github.com/ 这个 ui 了 相关代码也删除」）：
         · 输入框左边那块「https://github.com/」前缀标签（.repo-prefix）
         · 输入框下面那行「→ 完整地址」预览（.repo-preview）
       平台下拉**保留**（它决定保存时补哪个前缀，也提供"不开源"这个状态），
       补全逻辑 normalizeRepoUrl 照旧在 buildEntry 里生效，只是不再实时画给用户看。
       ⚠️ 别把这两个名字加回来 —— 前端模板与 layout.css 里的对应样式已一并清掉。 */
    /* 占位文字按**这一行**的平台给（多组以后每行平台可以不一样），
       所以从 computed 改成普通函数 —— computed 只能盯一个 maker.repoPlatform。 */
    function repoPlaceholderFor(row) {
      void I18N.version;
      const key = String((row && row.platform) || 'none');
      if (key === 'none') return t('repo_ph_none', '已选择「不开源」', 'maker');
      if (key === 'custom') return t('repo_ph_custom', '粘贴完整仓库地址', 'maker');
      return t('repo_ph_owner_repo', '例如：owner/repo（也可以直接粘贴完整地址）', 'maker');
    }
    /* ---------- 开源仓库「粘贴」按钮 ----------
       需求（用户原话）：「输入框边长些，它旁边右边有一个粘贴图标的按钮可以粘贴进输入框
       它粘贴板最近的一次链接文本，否则则提示相关粘贴失败提示。」
       做法：读剪贴板最近一次文本（复用模块级 _readClipboardText：后端原生 →
       navigator.clipboard 三级兜底），从里面**提取链接**填进**这一行**的地址框；
       提取不到（剪贴板空 / 没有链接 / 读不到）→ 明确的粘贴失败提示。
       ⚠️ 提取出的完整地址交给 normalizeRepoUrl：它会剥掉平台前缀，
          所以 GitHub 平台粘 "https://github.com/a/b" 与粘 "a/b" 等价，
          自定义平台则整条保留。 */
    async function pasteRepoUrl(row) {
      if (!row || row.platform === 'none') return;
      const raw = await _readClipboardText();
      const text = String(raw == null ? '' : raw).trim();
      if (!text) { pasteRepoFailed(); return; }
      /* 从任意文本里抓第一个 http(s) 链接；抓不到链接时，
         整段看起来像 "owner/repo" 这种仓库路径也接受（用户常常只复制这一段）。 */
      const urlMatch = text.match(/https?:\/\/\S+/i);
      const looksLikeRepo = /^[A-Za-z0-9._~-]+(?:\/[A-Za-z0-9._~%-]+)+$/.test(text)
        && text.indexOf(' ') < 0;
      const value = urlMatch ? urlMatch[0] : (looksLikeRepo ? text : '');
      if (!value) { pasteRepoFailed(); return; }
      row.url = value;
      /* 粘进来的是 Gitee 链接就把这一行切到 Gitee —— 否则「补前缀」会把它拼成
         https://github.com/… 变成一个并不存在的仓库。认不出平台（custom）时不动用户选的。 */
      const detected = detectRepoPlatform(value);
      if (detected !== 'custom') row.platform = detected;
      refreshPreview();
      toast(t('paste_repo_done', '已粘贴仓库地址', 'maker'), 'success',
        t('github', '开源仓库', 'maker'));
    }
    function pasteRepoFailed() {
      toast(t('paste_repo_failed', '粘贴失败：剪贴板里没有找到链接', 'maker'), 'warning',
        t('tip_warning', '提示', 'maker'));
    }
    /* next_code：TG- + 6 位数字，从现有最大值 +1（resource_maker_core.py:271-286） */
    function nextCodeFrom(list) {
      let max = 0;
      (list || []).forEach((it) => {
        const m = String(it.code || '').match(/^TG-(\d{6})$/);
        if (m) max = Math.max(max, parseInt(m[1], 10));
      });
      return 'TG-' + String(max + 1).padStart(6, '0');
    }
    function nextCode() { return nextCodeFrom(items.value); }

    /* 两套图标命名规则**不一样**（极易漏）：
       · 导入进本机图标目录 → 只去 Windows 非法字符与控制字符，**保留中文**（:1233-1298）
       · 稿件 / 独立库 → 非 [A-Za-z0-9_-] 全部清空，**中文会被清空**（core:364-391）
       需求：图标自动命名从"名称"改成"编号（code）"。
       · 新建条目时 maker.code 已经由 nextCode() 自动分配（TG-0000xx），图标也用它；
       · 载入现有资源时 iconName 来自资源库，老数据已批量改成 code 命名；
       · 导出稿件/独立库时 copyIconName 也以 code 为准。 */
    function iconBaseFromName(name, id) {
      let value = String(name || '').replace(/[\\/:*?"<>|\u0000-\u001f]/g, '').trim();
      if (!value) value = String(id || '').trim();
      return value;
    }
    function copyIconName(preferred, fallbackStem) {
      const clean = String(preferred == null ? '' : preferred).replace(/[^A-Za-z0-9_\-]+/g, '');
      if (clean) return clean;
      return String(fallbackStem || '').replace(/\.[^.]+$/, '') || 'icon';
    }
    function iconWantName() {
      /* 优先级：编号 code → id → 名称。编号形如 TG-000024，正好符合文件名规则。 */
      return iconBaseFromName(maker.code || maker.id || maker.name, maker.id)
        + (maker.iconExt || '.png');
    }
    /* flush_name_icon_rename（:1319-1374）：只在图标是用户刚为本条导入时才改名 */
    function flushNameIconRename() {
      clearTimeout(iconRenameTimer);
      iconRenameTimer = 0;
      if (!maker.iconPicked || !maker.iconSource) return;
      const want = iconWantName();
      if (!want || want === maker.iconName) return;
      /* ⚠️ 只有「这张图的字节还在内存里」才允许改名（m05525 交叉验证结论）。
         原来这里无条件改 maker.iconName，而磁盘文件从来不动（整个后端没有任何 rename 接口），
         于是「导入 → 保存 → 再改一次名称/编号 → 再保存」会让 entry.icon 指向一个盘上不存在的文件名，
         append_entry 查不到就把 icon **静默裁掉**（maker.py 的 _icon_name_if_exists），
         用户看到的现象是「图标自己没了」。现在：
           · 手里有 iconData → 改名 + 重新标记待保存 + 预览退回 dataURL，写盘时按新名重写一份；
           · 手里没 iconData（图是从资源库载入的）→ 不改名。宁可文件名继续用旧编号，
             也绝不写一个盘上没有的名字（悬空引用比难看的文件名危害大得多）。 */
      if (!maker.iconData) return;
      maker.iconName = want;
      maker.iconPending = true;
      maker.iconSource = maker.iconData;
    }
    function setI18nLang(index) { i18nLangIndex.value = index; }
    function refreshPreview() { /* 预览/状态行都是 computed，改动即刷新 */ }
    function toggleChip(list, value) {
      const index = list.indexOf(value);
      if (index >= 0) list.splice(index, 1); else list.push(value);
      refreshPreview();
    }

    /* 适用系统的互斥规则（m06170）：勾「全平台」就取消「其他」，反之亦然。
       取消勾选不做任何联动（用户可能就是想全清）。其它组合保持自由：
       resource_schema.SYSTEMS 里「全平台」是一个独立取值，没有「全平台蕴含全部」的
       语义，所以不能替用户把 Windows / web 之类一并勾上或清掉。*/
    function toggleSystem(value) {
      toggleChip(maker.systems, value);
      if (maker.systems.indexOf(value) < 0) return;
      const opposite = value === '全平台' ? '其他' : (value === '其他' ? '全平台' : '');
      if (!opposite) return;
      const index = maker.systems.indexOf(opposite);
      if (index >= 0) maker.systems.splice(index, 1);
    }

    /* 联动规则（:1414-1450）：名称 → id 与图标改名（防抖 800ms） */
    function onNameChanged() {
      const slug = slugify(maker.name).slice(0, 40);
      if (!maker._loading) maker.id = slug;
      /* 需求 m04188 第③项：上方「名称」一改，下面三种语言的名称跟着一起改。
         用户在多语言卡片里手动改过名称后 maker._nameAuto 变 false，这里就不再覆盖。
         （载入已有条目时同样不能覆盖：那时 maker.name 与 i18n 是成对灌进来的。） */
      if (maker._nameAuto && !maker._loading) {
        const synced = String(maker.name || '');
        makerLanguages.forEach((lang) => { maker.i18n[lang].name = synced; });
      }
      clearTimeout(iconRenameTimer);
      iconRenameTimer = setTimeout(flushNameIconRename, 800);   // 防抖 800ms 才改名
      refreshPreview();
    }
    /* 多语言卡片里手动改了某一种语言的名称 ⇒ 永久脱离跟随（同「标签跟着类别」那套语义）。
       不做"清空后自动恢复跟随"：用户明确说的是"只要发生了修改…不会再进行改变"。 */
    function onLocalNameEdited() {
      maker._nameAuto = false;
      refreshPreview();
    }
    function restoreNameFollow() {
      maker._nameAuto = true;
      const synced = String(maker.name || '');
      makerLanguages.forEach((lang) => { maker.i18n[lang].name = synced; });
      refreshPreview();
    }
    function onIdChanged() { flushNameIconRename(); refreshPreview(); }
    /* 类别可编辑 combo 的 change 回调。第二个参数 fromList 由 Combo 给出：
         true = 从下拉里点/键盘选中了一项（内置项）⇒ 三个语言池一起换；
         false/undefined = 手打的文本 ⇒ 只写当前分段。详见上面「分段写入的口径」。
       ⚠️ 上轮删掉了两件事：
         · 「标签自动跟着类别写」的联动（以前这里 if (maker._tagsAuto) maker.tags = …）
         · restoreTagsFollow / 「跟随类别」按钮
         用户原话：「提交软件页面的标签跟随类别这个相关代码删除包括跟随类别按钮，
         而且默认标签输入框为空」。 */
    function onCategoryChanged(value, fromList) {
      if (value === undefined) return;
      // combo 抛来的可能是当前分段的显示文本（English 段选 Tools），必须还原成规范值「工具」
      // 再进池子，否则显示文本被当成规范值落盘，筛选 / 索引 / 分组全对不上。
      const list = splitList(value).map(canonicalTerm).filter(Boolean);
      const text = list.join(', ');
      // 内置项 = 31 个类别 +「官方」「知名」两个角标项；判内置不看来源（手打 "Tools" 也算内置，第一轮口径）。
      const builtin = list.length > 0
        && list.every((v) => makerCategories.indexOf(v) >= 0 || makerCategoryExtras.indexOf(v) >= 0);
      if (fromList && builtin) {
        // 用户定夺：选内置项 = 三语一起切
        makerLanguages.forEach((lang) => { maker.category[lang] = text; });
      } else {
        maker.category[makerSegLang.value] = text;
      }
      refreshPreview();
    }
    function onRepoPlatformChanged(row, value) {
      if (!row) return;
      row.platform = value;
      refreshPreview();
    }

    /* 实时预览（update_preview，:396-414）：不显示 intro/supplement/systems/url/github。
       ⚠️ 需求（第四轮⑤，用户原话）：「切换到哪个语言就显示对应语言的内容，
          预览区域也跟随对应语言」⇒ 名称 / 简介 / 标签**三项统一跟「多语言字段」的分段语言**，
          和左边那三个框同一口径。以前的写法是三种口径混着来（名称取上方规范名、
          简介永远取简体中文、标签取界面语言），切分段毫无反应，看起来就像预览坏了。
       · 该分段没填时按后端 _collect_text 的回退链兜底
         （分段 → 简体中文 → 繁體中文 → English），与真实卡片取值的规则一致；
       · 标签用 termIn(分段语言, 规范值) 翻译：池子里存的永远是规范中文，
         预览要还原的是"这一语言下用户看到的那排药丸"。 */
    const previewFallbackOrder = computed(() => {
      const seg = makerSegLang.value;
      return [seg, '简体中文', '繁體中文', 'English'].filter((one, idx, arr) => one && arr.indexOf(one) === idx);
    });
    function pickBySegment(bag) {
      const order = previewFallbackOrder.value;
      for (let i = 0; i < order.length; i += 1) {
        const text = String((bag && bag[order[i]]) || '').trim();
        if (text) return text;
      }
      return '';
    }
    /* 把 maker.i18n 里某个字段（name/description）摊成 {语言: 文本} 再按分段取，
       读的是 reactive 的 maker.i18n ⇒ 切分段、在分段里打字都会即时重算。 */
    function i18nFieldBag(key) {
      const bag = {};
      makerLanguages.forEach((lang) => { bag[lang] = maker.i18n[lang] ? maker.i18n[lang][key] : ''; });
      return bag;
    }
    /* 名称兜底顺序：分段那份 → 上方规范名（_nameAuto 打开时两边本来就相同，
       手写过快照时可能只有上方有值）→ 占位文案。 */
    const previewName = computed(
      () => pickBySegment(i18nFieldBag('name')) || String(maker.name || '').trim()
        || t('preview_name', '（名称）', 'maker'),
    );
    const previewDesc = computed(() => {
      const text = pickBySegment(i18nFieldBag('description')) || t('preview_desc', '（简介）', 'maker');
      return text.length > 60 ? text.slice(0, 60) + '...' : text;
    });
    /* 标签行同理：取**分段那一份池**，用该分段的译名显示。
       （真实卡片走的是"界面语言那份 + term()"，见上面注释；预览这里刻意跟分段一致，
         因为用户需求就是"切分段 → 整块（含预览）换语言"。分段语言与界面语言一致时，
         两者显示完全相同，不会产生"预览和卡片说法不一"的新问题。） */
    const previewTagList = computed(() => {
      void I18N.version;
      const order = previewFallbackOrder.value;
      const pool = order.map((one) => maker.tags[one]).find((text) => splitList(text).length) || '';
      const seg = makerSegLang.value;
      return splitList(pool).map((tag) => '[' + termIn(seg, tag) + ']');
    });
    /* 有图标就原样显示。以前这里专门排除 .gif —— 那是 py 版 QIcon 画不动动画留下的限制，
       web 版只是一个普通 <img>，WebView2 自己会播 gif。判断留着的结果是：导入 gif 之后
       实时预览永远显示「?」（m06170「实时预览那里不支持gif它会显示问号的bug」）。*/
    const previewIcon = computed(() => (maker.iconSource ? maker.iconSource : ''));

    /* 「未保存」提示（m06170：双击进入编辑、发生了更改，在实时预览那里要有个未保存）。
       做法：载入完成那一刻把 buildEntry() 的产物存成字符串当基线，之后每次预览重算都拿
       现在的 buildEntry() 和它比。两边都走同一个函数，就不会出现「载入时压平一套、
       写盘时再压平一套」造成的假差异；基线为空（新建／清空表单）时不提示。*/
    const makerBaseline = ref('');
    function entrySnapshot() {
      try { return JSON.stringify(buildEntry()); } catch (error) { return ''; }
    }
    const previewDirty = computed(() => !!maker.editingExisting
      && !!makerBaseline.value && entrySnapshot() !== makerBaseline.value);

    /* 校验（validate / validate_warnings，:1589-1646） */
    function makerIdOf(item) { return String((item && item.id) || ''); }
    function validateErrors() {
      const out = [];
      if (!String(maker.name || '').trim()) out.push(t('「名称」必填', '「名称」必填', 'maker'));
      const id = String(maker.id || '').trim();
      if (!id) out.push(t('「标识 id」必填', '「标识 id」必填', 'maker'));
      else if (!/^[a-z0-9-]+$/.test(id)) {
        out.push(t('「标识 id」只能包含小写字母、数字和连字符', '「标识 id」只能包含小写字母、数字和连字符', 'maker'));
      }
      if (maker.iconSource && !maker.iconName && !maker.iconPending) {
        out.push(t('图标文件不存在（重新导入一次图片）', '图标文件不存在（重新导入一次图片）', 'maker'));
      }
      const editingCode = maker.loadedId ? String(maker.code || '') : '';
      const dupId = id ? items.value.find((it) => makerIdOf(it) === id && it.code !== editingCode) : null;
      if (dupId) {
        out.push(t('err_id_taken', '标识 id「{id}」已被占用（{name}）', 'maker')
          .replace('{id}', id).replace('{name}', dupId.name));
      }
      const code = String(maker.code || '').trim();
      const dupCode = code ? items.value.find((it) => it.code === code && it.code !== editingCode) : null;
      if (dupCode) {
        out.push(t('err_code_taken', '编码「{code}」已被占用（{name}）', 'maker')
          .replace('{code}', code).replace('{name}', dupCode.name));
      }
      return out;
    }
    function validateWarnings() {
      const out = [];
      /* 「导入图片」按 m05525 的语义**只进内存预览**：iconPending=true、iconData 有字节，
         而 iconName 要等点「追加到本机资源库 / 保存到原列表」那一刻才赋值。
         原来这条警告只盯 iconName ⇒ 用户刚导完图，实时预览的状态行还挂着「还没导入图片」，
         看上去就像导入根本没生效（用户第七轮反馈 m06914「我导入图片了可是实时预览那里还是提示这个」）。
         判据改成与预览出图同一口径：有待保存的预览图（iconPending / iconSource）就算已经导入。
         ⚠️ 不要改成检查 maker.icon —— 那是写盘之后才有的字段，比 iconName 更晚，只会更糟。
         文件真的丢了（iconSource 有值但既没落盘也没内存字节）由上面 5682 那条**错误**负责，
         两边不会同时冒出来。 */
      if (!maker.iconName && !maker.iconPending && !maker.iconSource) out.push(t('还没导入图片，卡片上会显示成默认图标', '还没导入图片，卡片上会显示成默认图标', 'maker'));
      const url = String(maker.url || '').trim();
      if (!url) out.push(t('「官网」留空了，卡片上会没有「官网」按钮', '「官网」留空了，卡片上会没有「官网」按钮', 'maker'));
      else if (!/^https?:\/\//i.test(url)) {
        out.push(t('「官网」没写 http://，已按 https:// 处理', '「官网」没写 http://，已按 https:// 处理', 'maker'));
      }
      /* 简介也是三语独立池。原来只查简体中文那一份：只在繁體/English 里写了简介时，
         预览（pickBySegment）早就把文字摆出来了，状态行却还在说「简介留空了」——
         和上面图标那条同一类病（填了内容、提示不消失）。改成走**与预览完全相同**的回退链，
         两边口径一致，用户不会再看到"预览有内容、提示说没有"。 */
      if (!pickBySegment(i18nFieldBag('description'))) {
        out.push(t('「简介」留空了，卡片上只有名称', '「简介」留空了，卡片上只有名称', 'maker'));
      }
      /* 类别是**三语独立池**，所以逐语言各看一遍，同一条问题最多只报一次
         （三种语言都空 ≠ 三条"留空了"）。标签没有需要报的问题（同名提示已按 m07730 删除）。 */
      const catPools = makerLanguages.map((lang) => splitList(maker.category[lang]).map(canonicalTerm).filter(Boolean));
      if (catPools.every((list) => !list.length)) {
        out.push(t('「类别」留空了，这条不会出现在类别分组里', '「类别」留空了，这条不会出现在类别分组里', 'maker'));
      }
      /* 「类别只为一个」（m06170 第 3 项 + m06395 定夺：只提醒、不改数据）。 */
      const categoryCount = Math.max.apply(null, catPools.map((list) => list.length));
      if (categoryCount > 1) {
        out.push(t('warn_multi_category',
          '「类别」填了 {n} 个：类别只填一个就够（多个会让它同时出现在几个分组里），' +
          '要表达附加属性请写进下面的「标签」', 'maker').replace('{n}', String(categoryCount)));
      }
      /* 「标签与类别同名」的提示已整段删除（用户 m07730 定夺：「删掉这条提示」）。
         前后端都不再动同名标签、照写照存，既然不改数据就没必要在状态行多说一句。 */
      [['author_page', maker.author_url], ['chat_url', maker.chat_url]].forEach((pair) => {
        const value = String(pair[1] || '').trim();
        if (value && !/^https?:\/\//i.test(value)) {
          out.push(t('warn_no_http_scheme', '「{label}」没写 http://，已按 https:// 处理', 'maker')
            .replace('{label}', t(pair[0], pair[0] === 'author_page' ? '作者主页' : '聊天地址', 'maker')));
        }
      });
      /* 下载地址（下载**页面**的网址）没写 http:// 时也给同样的提示 */
      const downloadPage = String(maker.downloadPageUrl || '').trim();
      if (downloadPage && !/^https?:\/\//i.test(downloadPage)) {
        out.push(t('warn_no_http_scheme', '「{label}」没写 http://，已按 https:// 处理', 'maker')
          .replace('{label}', t('download_page_url', '下载地址', 'maker')));
      }
      /* 自定义链接：后端 normalize_links 对「没有标签 / 任一语言地址不是 http(s) 开头」是**静默丢行**，
         用户填了却在详情页凭空消失，比报错更难查 —— 这里在状态行一条条点名（m05525：
         「最终效果要和卡片详细信息一样」）。两种全空的行不吭声：那是本来就打算留空。 */
      linksWarnRows().forEach((item) => {
        out.push(t('warn_link_dropped', '第 {n} 条自定义链接{why}，保存时会被丢弃', 'maker')
          .replace('{n}', String(item.n)).replace('{why}', item.why));
      });
      /* 多组开源仓库逐组点名：留空的组不会落盘（卡片上就没有那个仓库按钮），
         地址不是 http(s) 开头的组会被后端丢掉 —— 这两种都要说，
         别让用户填完了却发现「没保存上」却不知道哪一组出的问题。 */
      maker.repos.forEach((row, index) => {
        const platform = String((row && row.platform) || 'none');
        if (platform === 'none') return;
        const full = normalizeRepoUrl(platform, String((row && row.url) || '').trim());
        if (!full) {
          out.push(t('warn_repo_empty', '第 {n} 组开源仓库留空了，卡片上会没有仓库按钮', 'maker')
            .replace('{n}', String(index + 1)));
          return;
        }
        if (!/^https?:\/\//i.test(full)) {
          out.push(t('warn_repo_bad_scheme', '第 {n} 组开源仓库地址不是 http(s):// 开头，保存时会被丢弃', 'maker')
            .replace('{n}', String(index + 1)));
        }
      });
      return out;
    }
    const makerErrors = computed(() => validateErrors());
    const makerWarnings = computed(() => validateWarnings());
    const statusLevel = computed(() => (makerErrors.value.length ? 'danger'
      : (makerWarnings.value.length ? 'warning' : 'success')));
    /* status_label 的三种呈现（refresh_preview，:1651-1672）：错误/警告都只取前 4 条 */
    const statusLine = computed(() => {
      const errors = makerErrors.value;
      if (errors.length) return '· ' + errors.slice(0, 4).join('\n· ');
      const warns = makerWarnings.value;
      if (warns.length) {
        return t('status_all_ok_with_warns', '必填项都填好了，可以生成/追加。\n（另外：\n· {list}）', 'maker')
          .replace('{list}', warns.slice(0, 4).join('\n· '));
      }
      return t('信息完整，可以生成/追加了。', '信息完整，可以生成/追加了。', 'maker');
    });

    /* build_entry（:1553-1582）：字段顺序 = FIELD_ORDER（resource_schema.py:362-396） */
    const MAKER_FIELD_ORDER = ['id', 'code', 'name', 'category', 'tags', 'icon', 'url', 'github', 'repos',
      'download_url', 'chat_url', 'author_url', 'links', 'description', 'intro', 'supplement', 'listed_at',
      'systems', 'variants', 'default_variant'];
    function flattenText(value) { return String(value == null ? '' : value).replace(/\s*\n\s*/g, ' ').trim(); }
    function orderEntry(entry) {
      const out = {};
      MAKER_FIELD_ORDER.forEach((key) => { if (entry[key] !== undefined) out[key] = entry[key]; });
      Object.keys(entry).forEach((key) => { if (out[key] === undefined) out[key] = entry[key]; });
      return out;
    }
    /* apply_i18n_to_entry（:707-726）：全空跳过；去重后只剩 1 个 → 不写字典。
       多语言字段常开（多语言字段开关删除 我要常开而不是可关闭的），
       不再有 i18nEnabled 开关，这里无条件应用。
       ⚠️ 需求 m04188 第③项：name 也进来了（写"名称"要能三语言分别写）。
          三种语言完全相同时仍然**不写字典**（保持 build_entry 的纯字符串），
          所以老的资源库文件不会因为这次改动凭空多出一堆字典字段。 */
    function applyI18nToEntry(entry) {
      ['name', 'description', 'intro', 'supplement'].forEach((key) => {
        const values = {};
        makerLanguages.forEach((lang) => {
          const text = flattenText(maker.i18n[lang][key]);
          if (text) values[lang] = text;
        });
        const langs = Object.keys(values);
        if (!langs.length) return;
        const uniq = new Set(langs.map((lang) => values[lang]));
        if (uniq.size <= 1) return;                  // 保持 build_entry 里的纯字符串
        entry[key] = values;
      });
      return entry;
    }
    /* ---- 自定义链接：编辑 / 序列化助手（m05525）--------------------------------
       这一组输入框放在「多语言字段」卡片里，跟着分段器切语言：同一个 row 的
       label/url 都是三语言字典，切到 English 就编辑 English 那一份。 */
    /* 行数上限：前端这一处 + 后端 resource_schema.LINKS_MAX_ROWS 那一处，要改就一起改。
       后端超限是「截断 + validate 告警」，前端到顶是「不追加 + 说明原因」，两边都写不坏数据。 */
    const LINKS_MAX_ROWS = 20;
    function blankI18nText() {
      const obj = {};
      makerLanguages.forEach((lang) => { obj[lang] = ''; });
      return obj;
    }
    let linkRowSeq = 0;
    /* 每行带一个自增的内部键。模板 :key 用它而不是数组下标：按下标当 key 时删掉中间一行，
       Vue 会把后面几行的 DOM 往前挪，输入框里的文字看上去「串行」。
       下划线开头 = 只活在前端，linksForEntry() 重建对象时不会把它带进资源库 JSON。 */
    function newLinkRow() {
      linkRowSeq += 1;
      return { _key: linkRowSeq, label: blankI18nText(), url: blankI18nText() };
    }
    function addLinkRow() {
      /* 「可以无限点击添加」：只给一个很软的上限（20，与后端一致），
         到顶就明说为什么不能再加，而不是按钮默默没反应。 */
      if (maker.links.length >= LINKS_MAX_ROWS) {
        toast(t('links_too_many', '自定义链接最多 20 条', 'maker'), 'warning',
          t('tip_warning', '提示', 'maker'));
        return;
      }
      maker.links.push(newLinkRow());
    }
    function removeLinkRow(index) { maker.links.splice(index, 1); }
    /* 「这条链接会不会被丢掉」的预判：判定口径必须和 linksForEntry()、后端
       resource_schema._links_row 三方一致（标签任一语言非空 + 地址任一语言 http(s) 开头）。 */
    function linksWarnRows() {
      const out = [];
      maker.links.forEach((row, index) => {
        if (!row) return;
        const hasLabel = makerLanguages.some((lang) => String((row.label || {})[lang] || '').trim());
        const hasUrl = makerLanguages.some((lang) => String((row.url || {})[lang] || '').trim());
        if (!hasLabel && !hasUrl) return;
        if (!hasLabel) {
          out.push({ n: index + 1, why: t('link_no_label', '只有地址没有标签', 'maker') });
          return;
        }
        const bad = makerLanguages.some((lang) => {
          const value = String((row.url || {})[lang] || '').trim();
          return value && !/^https?:\/\//i.test(value);
        });
        if (bad) out.push({ n: index + 1, why: t('link_bad_scheme', '地址不是 http(s):// 开头', 'maker') });
      });
      return out;
    }
    /* 读/写「当前分段」那一格；字典缺键时按 pickI18n 的顺序回退，切来切去不会看不见。 */
    function linkCellText(cell) {
      if (cell == null) return '';
      if (typeof cell === 'string') return cell;
      const lang = makerLanguages[i18nLangIndex.value] || '简体中文';
      return String(cell[lang] || cell['简体中文'] || cell['繁體中文'] || cell['English'] || '');
    }
    function linkCellSet(cell, value) {
      if (!cell || typeof cell !== 'object') return;
      cell[makerLanguages[i18nLangIndex.value] || '简体中文'] = value;
    }
    /* 序列化：label 压平换行、url 去空白；标签或链接为空的整条不进 JSON
       （详情页那一行没有标签没法显示）。某语言留空时回退简体中文，
       保证后端拿到的每一格都有值、塌缩判断也不会误判。 */
    function linksForEntry() {
      const out = [];
      maker.links.forEach((row) => {
        if (!row || !row.label || !row.url) return;
        const label = {};
        const url = {};
        let hasLabel = false;
        let hasUrl = false;
        /* 逐语言**直接**取格子，不能走 linkCellText —— 那个函数读的是「当前分段」
           那一格，在这里按语言循环时会取错格子、把别的语言的值丢掉。 */
        makerLanguages.forEach((lang) => {
          label[lang] = flattenText(row.label[lang] || '');
          url[lang] = String(row.url[lang] || '').trim();
          if (label[lang]) hasLabel = true;
          if (url[lang]) hasUrl = true;
        });
        if (!hasLabel || !hasUrl) return;
        makerLanguages.forEach((lang) => {
          if (!label[lang]) label[lang] = label['简体中文'];
          if (!url[lang]) url[lang] = url['简体中文'];
        });
        out.push({ label: label, url: url });
      });
      return out;
    }
    /* 读回来：后端可能给三语言字典，也可能已经塌成字符串（三语相同）。 */
    function linkRawText(value, lang) {
      if (value == null) return '';
      if (typeof value === 'string') return value;
      return String(value[lang] || value['简体中文'] || value['繁體中文'] || value['English'] || '');
    }
    /* 从资源库读回来的行同样走 newLinkRow() ⇒ 自动带内部 _key，删中间行不会串位。 */
    function loadLinksFromRaw(raw) {
      const list = Array.isArray(raw) ? raw : [];
      const rows = [];
      list.forEach((item) => {
        if (!item || typeof item !== 'object') return;
        const row = newLinkRow();
        makerLanguages.forEach((lang) => {
          row.label[lang] = linkRawText(item.label, lang);
          row.url[lang] = linkRawText(item.url, lang);
        });
        if (row.label['简体中文'] || row.label['繁體中文'] || row.label['English']) rows.push(row);
      });
      return rows;
    }

    /* 三个语言池 → 磁盘形态：
       · 全空 → undefined（调用方据此**不写**这个字段，与"空的可选字段不落盘"一致）
       · **非空的那些池**内容完全相同（或只有一种语言非空）→ list[str]（老形态，紧凑）
       · 否则 → {语言: list[str]} 字典形态（只写非空的语言）
       ⚠️ 比较只看**非空**的池，且按原顺序比（用户要的就是 "工具, 系统" 而不是 "系统, 工具"）。
          这条口径必须与后端 maker._merge_i18n（texts 只收非空 → len(set)==1 就塌缩）
          以及前端 applyI18nToEntry（uniq.size<=1 就不写字典）**三方一致**，
          否则"前端写字典、后端又塌缩"会让同一份数据往返两次形态漂移。 */
    function poolsForEntry(pools) {
      const per = {};
      const filled = [];
      makerLanguages.forEach((lang) => {
        const list = splitList(pools[lang]).map(canonicalTerm).filter(Boolean);
        per[lang] = list;
        if (list.length) filled.push(lang);
      });
      if (!filled.length) return undefined;
      const signature = per[filled[0]].join(',');
      if (filled.every((lang) => per[lang].join(',') === signature)) return per[filled[0]];
      const dict = {};
      filled.forEach((lang) => { dict[lang] = per[lang]; });
      return dict;
    }
    function buildEntry() {
      const id = String(maker.id || '').trim();
      const code = String(maker.code || '').trim();
      const entry = {};
      if (id) entry.id = id;
      if (code) entry.code = code;
      if (String(maker.name || '').trim()) entry.name = String(maker.name).trim();
      /* 类别 / 标签：三个语言池 → 磁盘形态（本轮契约，见 maker 状态区的说明）
         · 三语内容**完全相同**（或只有一种语言非空）→ 塌缩成 list[str]，与老数据同形，
           资源库里不会多出一堆无意义的同内容字典（和 name/description 那套一致）；
         · 真的分语言不同 → 写 {简体中文: [...], 繁體中文: [...], English: [...]}，
           读侧 resource_schema 的 _collect_text 按语言取自己那一份（task-4 后端支持）。
         每个池里的值都已经过 canonicalTerm（输入时就还原过），这里再走一遍是幂等保险。 */
      const category = poolsForEntry(maker.category);
      if (category !== undefined) entry.category = category;
      /* ⚠️ m07514 用户报：「类别里有这个选项，我在标签里输入同一个名称，点保存后就不保存」。
         真因是把「与类别同名的标签」静默过滤掉了。现在照写照存：用户手填的标签一律保留。 */
      const tags = poolsForEntry(maker.tags);
      if (tags !== undefined) entry.tags = tags;
      if (maker.iconName) entry.icon = maker.iconName;
      /* 理论上三个写盘入口都会先 commitIconForWrite，走到这里说明还没落盘：
         用同一套规则算出目标文件名，和稍后那次写入一字不差，避免写出对不上的引用。 */
      else if (maker.iconPending) entry.icon = iconWantName();
      const url = autoHttpUrl(maker.url);
      if (url) entry.url = url;
      /* 多组开源仓库：每组一行 = {platform, url}；「不开源」和空地址的组直接不算。
         github 字段继续写**第一组**（= 主仓库）—— 卡片仓库按钮、下载部署、
         AI 工具那些只读 github 单值的代码因此一行都不用改。 */
      const repos = reposForEntry();
      if (repos.length) {
        entry.repos = repos;
        entry.github = repos[0].url;
      }
      if (maker.loadedDownloadUrl) entry.download_url = maker.loadedDownloadUrl;
      /* 下载**页面**的网址（用户填的下载地址）。
         ⚠️ 和上面的 download_url（安装包直链）是两个不同的字段。 */
      const downloadPage = autoHttpUrl(maker.downloadPageUrl);
      if (downloadPage) entry.download_page_url = downloadPage;
      const chat = autoHttpUrl(maker.chat_url);
      if (chat) entry.chat_url = chat;
      const author = autoHttpUrl(maker.author_url);
      if (author) entry.author_url = author;
      ['description', 'intro', 'supplement'].forEach((key) => {
        const text = flattenText(maker.i18n['简体中文'][key]);
        if (text) entry[key] = text;
      });
      entry.listed_at = (maker.loadedId && !maker.isNewEntry && maker.listedAt) ? maker.listedAt : nowListedAt();
      if (maker.systems.length) entry.systems = maker.systems.slice();
      const links = linksForEntry();
      if (links.length) entry.links = links;
      return applyI18nToEntry(orderEntry(entry));
    }
    function validateOrToast() {
      const errors = validateErrors();
      if (!errors.length) return true;
      toast(t('errors_fix_first', '还有问题需要先修好：\n· {list}', 'maker').replace('{list}', errors.join('\n· ')),
        'error', t('请先处理这些问题', '请先处理这些问题', 'maker'));
      return false;
    }
    function pickImageFile(accept) {
      return new Promise((resolve) => {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = accept;
        input.onchange = () => resolve((input.files && input.files[0]) || null);
        input.click();
      });
    }
    /* 导入图片（:1477-1503）：成功 → 图片已导入/ image_saved_as
       ⚠️ 必须把图片**真正写进图标目录**（`maker.save_icon`）。
       以前只在浏览器内存里放一个 dataURL，JSON 里写的 `icon` 文件名在磁盘上根本不存在 ——
       资源库/搜索页/独立资源库里的图标全是坏的（等于假装导入成功）。 */
    async function pickIcon() {
      const file = await pickImageFile('.png,.jpg,.jpeg,.gif,.ico,.bmp,.webp,.svg,image/*');
      if (!file) return;
      const ext = (String(file.name).match(/\.[^.]+$/) || ['.png'])[0].toLowerCase();
      const dataUrl = await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.readAsDataURL(file);
      });
      if (!dataUrl) {
        toast(t('icon_read_failed', '没能读出这张图片', 'maker'), 'error',
          t('image_import_failed', '图片没能存进图标目录', 'maker'));
        return;
      }
      /* 只进预览。dataURL 必然与旧的 URL 字符串不同 ⇒ <img> 一定会重新解码出新图，
         这正是「选了图预览也没变化」的根治点：原来同编号同名时 URL 一字不变，
         浏览器沿用内存里那张旧图，看上去就像什么都没发生。 */
      maker.iconExt = ext;
      maker.iconData = dataUrl;
      maker.iconSource = dataUrl;
      maker.iconPending = true;
      maker.iconPicked = true;
      refreshPreview();
      toast(t('icon_previewed', '已放进预览：点「追加到本机资源库」或「保存到原列表」时才会真正写入图标目录', 'maker'),
        'info', t('import_image', '导入图片', 'maker'));
    }

    /* 写盘前把预览里那张图真正存进图标目录（m05525）。
       文件名取 iconWantName() —— **此刻**的编号/名称，所以保存之前怎么改名称都不会
       留下悬空引用。返回 false 表示图片没落地，调用方必须中止写资源库：
       宁可整条资源不写，也不能写出一个指向不存在文件的索引。 */
    async function commitIconForWrite() {
      if (!maker.iconPending || !maker.iconData) return true;
      const want = iconWantName();
      let result = null;
      try {
        result = await bridge.tryCall('maker.save_icon', want, maker.iconData);
      } catch (error) {
        result = { ok: false, error: String((error && error.message) || error) };
      }
      if (!result) {
        needApi('maker.save_icon', t('import_image', '导入图片', 'maker'));
        return false;
      }
      if (!result.ok) {
        toast(String(result.error || t('write_failed', '写入失败', 'maker')), 'error',
          t('image_import_failed', '图片没能存进图标目录', 'maker'));
        return false;
      }
      maker.iconName = String(result.name || want);
      /* 落盘成功后把预览换成服务器地址，并挂一个一次性时间戳：
         webhost 那边本来就 no-store，但 <img> 在 src 字符串没变时根本不会再发请求，
         同名覆盖这种场景必须靠变 URL 才会重新拉图。 */
      const base = String(result.url || ('/res/image/icon/' + encodeURIComponent(maker.iconName)));
      maker.iconSource = base + (base.indexOf('?') >= 0 ? '&' : '?') + 'v=' + Date.now();
      maker.iconPending = false;
      /* iconData 故意不清空：改了编号/名称之后还要靠它按新名字重写磁盘文件（见 flushNameIconRename）。
         它只占这张图本身的大小，载入别的条目（loadResourceIntoForm）和清空表单（resetMakerForm）都会清。 */
      return true;
    }

    /* 图标输入框显示用：还在预览时把「将要写入的文件名」摆出来并标注待保存，
       用户才知道这张图还没进目录。 */
    const iconDisplayName = computed(() => (maker.iconName
      ? maker.iconName
      : (maker.iconPending ? iconWantName() + ' · ' + t('icon_pending', '待保存', 'maker') : '')));

    /* 载入现有资源弹层 + loadExisting / applyLoadExisting 已删除 ——
       用户要求删掉载入到制作资源按钮后，这条路径没有任何入口（双击资源浏览一行
       已经等效：editExistingEntry → loadResourceIntoForm），留着只是死代码。 */
    function loadResourceIntoForm(raw) {
      maker._loading = true;
      maker.name = pickI18n(raw.name, '');
      maker.id = String(raw.id || '');
      maker.code = String(raw.code || maker.code);
      maker.codeAuto = false;
      /* 类别 / 标签灌进**三个独立池**（本轮契约：它们属于「多语言字段」，按语言各填各的）。
         磁盘上有两种形态都要收：
           · 老形态：list[str]（或 "工具,系统" 这种逗号串）⇒ 三种语言灌同一份规范值，
             界面上各分段显示自己的译名 —— 与改动前观感一致，老数据零迁移；
           · 新形态：{简体中文: list|str, 繁體中文: …, English: …} ⇒ 各语言灌自己那一份，
             缺失的语言回退简体中文（与后端 first_text/LANGUAGE_FALLBACK 同一口径）。
         池子里永远存**规范中文值**（逗号分隔），显示译名交给 makerCategoryText/makerTagsText。
       ⚠️ 但灌池子取的是**原始形态** category_i18n / tags_i18n，不是 category / tags：
          后端 detail 出口把 category / tags 恒压成"当前界面语言那一份 list[str]"供卡片显示
          （desktop/api/resources.py 的 _display_str_list :631、DETAIL_RAW_SUFFIX = "_i18n" :617），
          规范中文只出现在 *_i18n 里。直接灌 category 的后果：English 界面下编辑一条资源，
          池子里装的是 "Tools"，写盘时 canonicalTerm 认不出来 ⇒ 当成自定义值落盘，规范值被污染。
       ⚠️ 老后端 / 老数据没有 *_i18n 时回退那份 list[str]（三种语言灌同一份），语义仍正确。
          直接灌压平后的 category 还会把作者分语言写的内容塌回同一份（编辑一次就丢两种写法）。 */
      const rawCategory = raw.category_i18n != null ? raw.category_i18n : raw.category;
      const rawTags = raw.tags_i18n != null ? raw.tags_i18n : raw.tags;
      maker.category = poolsFromRaw(rawCategory);
      maker.tags = poolsFromRaw(rawTags);
      maker.systems = Array.isArray(raw.systems) ? raw.systems.slice() : [];
      maker.url = String(raw.url || '');
      /* 多组开源仓库：优先按 raw.repos 还原每一组；
         老数据只有 github 一条 → 兜成一行（平台由地址前缀推断）。 */
      maker.repos = loadReposFromRaw(raw);
      maker.author_url = String(raw.author_url || '');
      maker.chat_url = String(raw.chat_url || '');
      maker.loadedDownloadUrl = String(raw.download_url || '');   // 表单没有这个字段，原样保留
      /* 灌入下载地址（下载**页面**的网址） */
      maker.downloadPageUrl = String(raw.download_page_url || '');
      maker.listedAt = String(raw.listed_at || '');
      maker.loadedId = String(raw.id || '');
      maker.loadedName = pickI18n(raw.name, '');
      maker.isNewEntry = false;
      /* 进入编辑模式（资源浏览双击 / 载入到制作资源都走这里） */
      maker.editingExisting = true;
      maker.editingId = String(raw.id || '');
      maker.editingCode = String(raw.code || '');
      const iconName = raw.icon ? String(raw.icon).split(/[\\/]/).pop() : '';
      maker.iconName = iconName;
      maker.iconSource = iconName ? '/res/image/icon/' + encodeURIComponent(iconName) : '';
      maker.iconExt = (iconName.match(/\.[^.]+$/) || [''])[0];
      maker.links = loadLinksFromRaw(raw.links);
      maker.iconPicked = false;
      maker.iconPending = false;
      maker.iconData = '';
      /* （路线 A 的前端一半）：把多语言字段灌进三种语言。
         raw[key] 现在有两种形态：
           · 字典 {简体中文, 繁體中文, English} —— 来自 resources.detail
             （后端把磁盘上的**原始多语言字典**还回来了，见
              resource_loader.get_raw_i18n_by_code 与 desktop/api/resources.py 的 detail）；
           · 字符串 —— 列表接口那一路（mapItem 已按当前语言压平）或老后端。
         字典：按语言逐个灌满；标量（字符串 / 逗号串 / list）：**摊给三种语言同一份**。
           这正是需求（第四轮④）"三种语言都填同一个文本 → 只保存一份文本"的读侧那一半：
           磁盘上只有一份时，三个分段都必须看得见它 —— 以前只灌简体中文，用户切到 English
           看到空框以为内容丢了，随手补一份再提交，反而把"三语同名"改成三语不同名。
           写侧本来就塌缩（applyI18nToEntry 去重后只剩 1 个值就不写字典），读侧补齐即闭环。
         ⚠️ 两种形态都不会让 maker.i18n[lang][key] 变成 undefined。
         ⚠️ 语言键必须**精确**匹配 makerLanguages 的写法（是繁體中文不是繁体中文），
            磁盘上偶尔出现的简写繁体键在这里顺带回退一次（精确键优先）。 */
      const langTextOf = (dict, lang) => {
        if (dict == null) return '';
        /* 标量 / 数组 = "整条只有一份"，不是"某一种语言那一份" ⇒ 三种语言都返回同一个文本。 */
        if (typeof dict !== 'object' || Array.isArray(dict)) return flattenText(dict);
        if (dict[lang] != null) return String(dict[lang]);
        const alt = lang === '繁體中文' ? '繁体中文' : '';
        if (alt && dict[alt] != null) return String(dict[alt]);
        return '';
      };
      /* ⚠️ 声明必须放在 forEach **外面**：下面「跟随状态」那块也要用它。
         上一轮我把它写在回调里、块外又引用了一次 ⇒ 运行时 `ReferenceError: rawName is not defined`
         ⇒ 整个 loadResourceIntoForm 中断在 `activeSection.value = 'form'` 之前
         ⇒ 用户看到的症状就是「资源浏览双击后还停留在浏览界面」（需求 m04892 第①项）。
         这类越界引用 node --check 与 Vue 编译都放行，只有真跑一遍才炸。 */
      const rawName = raw.name;
      makerLanguages.forEach((lang) => {
        /* 三种形态（字典 / 标量 / list）统一走 langTextOf，不要再写"只有简体中文才灌"的分支。 */
        ['description', 'intro', 'supplement'].forEach((key) => {
          maker.i18n[lang][key] = langTextOf(raw[key], lang);
        });
        maker.i18n[lang].name = langTextOf(rawName, lang);
      });
      /* 跟随状态也一并载入（需求 m04188 第③项的后半）：
         磁盘上的 name 已经是「各语言写法不同」的字典 ⇒ 说明这位作者手动分过语言，
         载入后继续跟随会把它们无脑覆盖成上方那一个值，等于把别人的多语言成果抹掉，
         所以这里直接把 _nameAuto 置 false；纯字符串（或三语言完全相同）才保持跟随。 */
      {
        const nameDict = (rawName && typeof rawName === 'object' && !Array.isArray(rawName)) ? rawName : null;
        const distinct = new Set(makerLanguages
          .map((lang) => String(maker.i18n[lang].name || '').trim())
          .filter((text) => text !== ''));
        maker._nameAuto = !(nameDict && distinct.size > 1);
      }
      /* 分段默认落在**当前界面语言**那一段（本轮需求"记得适配设置中的语言切换"）：
         界面是 English 时打开表单，第一眼就该看到 English 那份池子。 */
      i18nLangIndex.value = Math.max(0, makerLanguages.indexOf(uiLanguage()));
      maker._loading = false;
      refreshPreview();
      /* 载入完成 = 有了对照基线（预览那个「未保存」就是和它比出来的）。 */
      makerBaseline.value = entrySnapshot();
    }

    /* 行为链 A：生成稿件（:1675-1746）
       <目录>/<id>/resource.json + <目录>/<id>/<localized 说明.txt> + <目录>/<id>.zip */
    async function pickDirectory() {
      if (typeof window.showDirectoryPicker !== 'function') return null;
      try { return await window.showDirectoryPicker({ mode: 'readwrite' }); }
      catch (error) { return false; }                 // 用户取消 → 中止
    }
    async function writeFileInto(dir, name, text) {
      const handle = await dir.getFileHandle(name, { create: true });
      const writable = await handle.createWritable();
      await writable.write(text);
      await writable.close();
    }
    async function exportDraft() {
      if (!validateOrToast()) return;
      flushNameIconRename();
      const entry = buildEntry();
      const root = await pickDirectory();
      if (root === false) return;
      const id = entry.id || 'resource';
      const draft = {
        schema_version: '2.1.0',
        metadata: {
          name: 'ToolsGCP Draft - ' + (entry.name || id),
          description: '单条资源稿件，可直接提交给 ToolsGCP 作者',
          icon_dir: 'Icon', updated_at: nowIso(),
        },
        resources: [entry],
      };
      /* 说明文件名**随语言变**：简中 说明.txt / 繁中 說明.txt / English README.txt */
      const readmeName = t('说明.txt', '说明.txt', 'maker');
      const iconLine = maker.iconName
        ? t('draft_readme_icon_line', 'Icon/{name} —— 图片（已按编号命名）', 'maker').replace('{name}', maker.iconName)
        : t('draft_readme_no_icon', '（这份稿件没有附带图片）', 'maker');
      const readme = t('draft_readme_head', '这是 ToolsGCP 的单条资源稿件。', 'maker') + '\n\n'
        + t('draft_readme_json', 'resource.json 是资源条目本身，可直接提交给作者。', 'maker') + '\n'
        + iconLine + '\n'
        + t('draft_readme_howto', '把整个文件夹打包发给作者即可。', 'maker') + '\n';
      let dirLabel = '';
      let zipMsg = '';
      if (root && root.getDirectoryHandle) {
        try {
          const dir = await root.getDirectoryHandle(id, { create: true });
          await writeFileInto(dir, 'resource.json', JSON.stringify(draft, null, 2) + '\n');
          await writeFileInto(dir, readmeName, readme);
          if (maker.iconSource) {
            const iconDir = await dir.getDirectoryHandle('Icon', { create: true });
            /* 稿件里的图标也按编号命名（旧版用 maker.name，中文会被清空成 icon） */
            const iconFile = copyIconName(maker.code || maker.id, maker.iconName);
            const blob = await (await fetch(maker.iconSource)).blob();
            const handle = await iconDir.getFileHandle(iconFile + maker.iconExt, { create: true });
            const writable = await handle.createWritable();
            await writable.write(blob);
            await writable.close();
          }
          dirLabel = id;
        } catch (error) {
          toast(t('write_draft_dir_failed', '写入稿件目录失败：') + ((error && error.message) || String(error)),
            'error', t('tip_error', '错误', 'maker'));
          return;
        }
        /* 打包 zip：浏览器端没有 ZIP 能力，按 zip_pack_failed 追加（不假装已打包） */
        zipMsg = '\n' + t('zip_pack_failed', '打包 zip 失败', 'maker');
      } else {
        downloadJson('resource.json', JSON.stringify(draft, null, 2) + '\n');
        zipMsg = '\n（浏览器环境没有目录选择接口，已单独下载 resource.json；zip 未打包）';
      }
      /* 产出成功后清空表单（本轮需求：「点击清空表单或者点击产出类似之类的按钮应该全部清空
         的那个逻辑继续添加这个清空包括范围：标签和类别，类别则是恢复默认的工具」）。
         原来只有「追加到本机资源库 / 保存到原列表」会清，生成稿件/另存独立库留着一屏内容，
         用户接着做下一条就得手动清。现在四条产出路径口径一致，都走 resetMakerForm
         （里面 category 恢复默认「工具」、tags 跟着恢复默认并重新挂上跟随）。
         ⚠️ 顺序与「追加到本机资源库 / 保存到原列表」保持一致：先清、后 toast
            （toast 内容里已经带上生成的文件名/路径，不依赖表单里的值，先清不会丢信息）。 */
      resetMakerForm();
      toast(t('稿件已生成', '稿件已生成', 'maker') + '：' + (dirLabel || 'resource.json') + zipMsg,
        'success', t('稿件已生成', '稿件已生成', 'maker'));
    }

    /* 行为链 B：追加到本机资源库（:1748-1836）
       写盘前滚动备份固定名 1 份、原子写、覆盖保留 listed_at —— 由桌面端接口负责 */
    function libraryPayload(list) {
      return { schema_version: '2.1.0',
        metadata: { name: 'ToolsGCP Resources', description: 'ToolsGCP 资源索引文件',
          icon_dir: 'Icon', updated_at: nowIso(), total_count: list.length },
        resources: list };
    }
    /* 写完资源库后把前端那份也刷新（页面上的条数、资源浏览列表、收藏星标都跟着变），
       否则用户会以为"点了没反应/空壳"。 */
    async function reloadMakerLibrary() {
      try { await loadResources(); } catch (error) { /* 刷新失败不影响已经写盘的结果 */ }
      /* 资源浏览这一页读的是自己那一份（maker.browse），必须一起重载，
         否则刚写完盘回到列表看到的还是旧行 —— 用户会以为没写进去。 */
      try { await loadBrowserRows(); } catch (error) { /* 同上 */ }
    }
    /* 写盘目标与列表来源不是一回事（m04188 第②项的后续影响，必须提示）：
       「追加到本机资源库 / 保存到原列表」现在**始终**写程序的 .ToolsGCP/ToolsGCP-Resources.json，
       但资源来源=云端时，页面列表读的是 GitHub 发布的那份镜像缓存，新条目要等镜像更新才会出现。
       不写这句话，用户刚点完「已追加」却在看板上找不到，就会以为程序没写进去（正是本轮报的那个 bug 的观感）。
       所以成功提示后面补一行指路：想立刻看到就把资源来源切到「本地」。 */
    function librarySourceHint() {
      if (String(settings.resource_source || 'cloud') !== 'cloud') return '';
      return '\n' + t('cloud_mirror_hint',
        '提示：当前资源来源是「云端」，页面列表读的是云端镜像，新条目要等镜像更新才会出现；'
        + '想马上看到，把资源来源切成「本地」。', 'maker');
    }
    /* 条目名给人看的形态：三语言字典取当前界面语言那一份，纯字符串原样返回。
       ⚠️ 不能用 `String(entry.name)`：applyI18nToEntry 在三语不一致时会写成字典，
       直接插值到界面上就是用户报的「编辑已有资源后面是一堆程序内部代码」。 */
    function entryDisplayName(entry) {
      const raw = entry && entry.name;
      if (raw && typeof raw === 'object') return pickI18n(raw, '');
      return String(raw == null ? '' : raw);
    }
    async function appendToLibrary() {
      if (!validateOrToast()) return;
      flushNameIconRename();
      if (!(await commitIconForWrite())) return;   // 图片没落地就不写索引（m05525）
      const entry = buildEntry();
      const list = items.value.slice();
      const index = list.findIndex((it) => it.id === entry.id);
      const existing = index >= 0 ? list[index] : null;
      const editingSame = !!(maker.loadedId && maker.loadedId === entry.id);
      if (existing && !editingSame) {
        const yes = await openDialog({ title: t('覆盖已有资源', '覆盖已有资源', 'maker'),
          body: t('confirm_overwrite_entry', '资源库里已经有 id 为「{id}」的条目（{name}），要用现在的表单内容覆盖它吗？\n\n资源库文件：{path}', 'maker')
            .replace('{id}', entry.id).replace('{name}', existing.name).replace('{path}', libraryFullPath()),
          confirmText: t('覆盖', '覆盖', 'maker'), cancelText: t('取消', '取消', 'maker') });
        if (!yes) return;
      }
      const result = await bridge.tryCall('maker.append_entry', entry, { confirm: true });
      if (!result) {
        /* ⚠️ 桌面端没有写盘接口：**明确提示**，绝不下载 JSON 冒充"已写入" */
        needApi('maker.append_entry', t('append_local', '追加到本机资源库', 'maker'));
        return;
      }
      if (!result.ok) {
        toast(result.error || t('write_failed', '写入失败', 'maker'), 'error', t('tip_error', '错误', 'maker'));
        return;
      }
      /* 写盘成功后**清空表单**（m05525：「点击追加到本机资源库后应该自动清空吧表单」）。
         旧做法是把这条资源反过来设成编辑态（editingExisting=true），于是表单一直挂着
         刚提交的内容，用户再点一次就在库里堆一条重复资源。清空之后：
         · 徽标与「保存到原列表」一起消失（它们都挂在 editingExisting 上）；
         · resetMakerForm 会顺带重新分配下一个编号，正好用于下一条；
         · 条目信息已经在下面那条 toast 里报过了，不需要留在表单里。
         注意顺序：先 await reloadMakerLibrary() 再清 —— nextCode() 读的是刷新后的列表，
         早清会拿到旧的最大编号，下一条就可能和刚写的撞号。 */
      maker.loadedDownloadUrl = entry.download_url || maker.loadedDownloadUrl;
      await reloadMakerLibrary();
      resetMakerForm();
      const total = result.total != null ? result.total : (index >= 0 ? list.length : list.length + 1);
      const verb = result.action === 'update'
        ? t('library_updated', '已更新', 'maker') : t('library_added', '已追加', 'maker');
      toast(verb + ' ' + t('written_to_library', '{name}（{code}）→ {n} 条', 'maker')
        .replace('{name}', entryDisplayName(entry) || String(entry.id || ''))
        .replace('{code}', entry.code || '')
        .replace('{n}', total) + librarySourceHint(),
        'success', t('已写入资源库', '已写入资源库', 'maker'));
    }
    /* 保存到原列表——编辑模式下把表单写回载入时的那一条。
       ⚠️ 必须强制使用 editingId/editingCode：如果用户改了标识 id，直接按新 id 调 append_entry
       会被后端当成新条目追加（后端按 id 优先匹配），原条目还在 → 资源库出现重复。 */
    async function saveToOriginal() {
      if (!maker.editingExisting) {
        toast(t('not_editing_mode', '当前不在编辑模式：请到「资源浏览」双击一行进入编辑。', 'maker'),
          'warning', t('tip_warning', '提示', 'maker'));
        return;
      }
      if (!validateOrToast()) return;
      flushNameIconRename();
      if (!(await commitIconForWrite())) return;   // 同上：先落地图片再写索引
      const entry = buildEntry();
      if (maker.editingId) entry.id = maker.editingId;
      if (maker.editingCode) entry.code = maker.editingCode;
      const original = items.value.find((it) => (maker.editingCode && it.code === maker.editingCode)
        || (maker.editingId && it.id === maker.editingId));
      if (original && original.listed_at) entry.listed_at = original.listed_at;   // 保留原上架时间
      const result = await bridge.tryCall('maker.append_entry', entry, { confirm: true });
      if (!result) {
        needApi('maker.append_entry', t('save_to_original', '保存到原列表', 'maker'));
        return;
      }
      if (!result.ok) {
        toast(result.error || t('write_failed', '写入失败', 'maker'), 'error', t('tip_error', '错误', 'maker'));
        return;
      }
      /* 写回成功后同样清空表单（m06170「点击保存到原列表按钮也要保存成功后清空」）。
         以前留着一屏内容和编辑态：用户既不知道存没存，下一次点「保存到原列表」还会
         继续覆盖同一条。条目信息下面那条 toast 已经报过；顺序与「追加」一致 ——
         先 reload 再 reset，这样 nextCode() 读到的是刷新后的列表，下一条不会撞号。*/
      await reloadMakerLibrary();
      resetMakerForm();
      toast(t('saved_to_original', '已保存回原条目：{name}（{code}）', 'maker')
        .replace('{name}', entryDisplayName(entry) || String(entry.id || '')).replace('{code}', entry.code || '')
        + librarySourceHint(),
        'success', t('save_to_original', '保存到原列表', 'maker'));
    }

    /* 行为链 C：另存为独立资源库（:1838-1880）
       ⚠️ 真实现走 `maker.save_standalone` —— 系统另存为对话框 + 后端写盘 +
              把图标复制到 `目标目录/Icon/` 并改写 entry.icon（对齐 py save_standalone）。
       之前用 `shell.save_text_file` 只能写 JSON 文本，图标是 dataURL、复制不过去，
       导出的"独立资源库"在别人机器上图标全是坏的。
       降级顺序：maker.save_standalone → shell.save_text_file（老后端仍能导出，只是不带图标）
                 → needApi（明确提示，绝不假装成功）。 */
    async function saveStandalone() {
      if (!validateOrToast()) return;
      flushNameIconRename();
      /* 独立资源库要**把图标文件复制到目标目录/Icon**，所以预览里那张图必须先真的落地，
         否则后端拿不到源文件、导出的 JSON 会带一个空图标（m05525）。 */
      if (!(await commitIconForWrite())) return;
      const entry = buildEntry();
      const result = await bridge.tryCall('maker.save_standalone', entry,
        { default_name: 'ToolsGCP-Resources.json' });
      if (!result) {
        const text = JSON.stringify(libraryPayload([entry]), null, 2) + '\n';
        const fallback = await bridge.tryCall('shell.save_text_file',
          'ToolsGCP-Resources.json', text, 'JSON 文件 (*.json)');
        if (!fallback) {
          needApi('maker.save_standalone', t('save_as_new', '另存为独立资源库', 'maker'));
          return;
        }
        if (!fallback.ok) {
          toast(fallback.error || t('write_failed', '写入失败', 'maker'), 'error',
            t('tip_error', '错误', 'maker'));
          return;
        }
        if (fallback.canceled) return;              // 用户在「另存为」里点了取消：静默，不清
        /* 产出成功 → 清空表单（口径同 exportDraft / appendToLibrary，本轮需求） */
        resetMakerForm();
        toast(t('saved_standalone', '已另存为独立资源库：{path}', 'maker')
          .replace('{path}', fallback.path || 'ToolsGCP-Resources.json')
          + '\n' + t('standalone_no_icon', '（当前后端还不能复制图标，这份 JSON 里不包含图标文件）', 'maker'),
          'success', t('已生成独立资源库', '已生成独立资源库', 'maker'));
        return;
      }
      if (!result.ok) {
        toast(result.error || t('write_failed', '写入失败', 'maker'), 'error', t('tip_error', '错误', 'maker'));
        return;
      }
      if (result.canceled) return;              // 用户在「另存为」里点了取消：静默，不清
      /* 产出成功 → 清空表单（本轮需求：产出类按钮一律全清，含标签与类别） */
      resetMakerForm();
      toast(t('saved_standalone', '已另存为独立资源库：{path}', 'maker')
        .replace('{path}', result.path || 'ToolsGCP-Resources.json'),
        'success', t('已生成独立资源库', '已生成独立资源库', 'maker'));
    }

    /* 编辑态的出口（这个编辑界面要不同…避免卡在编辑态）。
       语义：**保留名称 / 类别 / 简介等内容**，但把它变成一条真正的新资源 ——
       · 标识 id 清空（它是唯一键；不清就等于还在改原来那条，追加时还会弹"覆盖"）；
       · 编码重新分配（沿用旧编码会被 validate 判成"编码已被占用"，导致根本追加不进去 ——
         这是实测踩到的坑）；
       · 上架时间清空（新条目入库时重新写）。
       想彻底重来用清空表单。 */
    function exitEditing() {
      if (!maker.editingExisting) return;
      maker.editingExisting = false;
      maker.editingId = '';
      maker.editingCode = '';
      maker.loadedId = '';
      maker.loadedName = '';
      maker.isNewEntry = true;
      maker.listedAt = '';
      maker.id = '';
      maker.code = nextCode();
      maker.codeAuto = true;
      toast(t('exited_edit', '已退出编辑：内容保留，但已改成新资源（标识 id 已清空、编码已重新分配），请补一个新的标识 id。',
        'maker'), 'info', t('exit_edit', '退出编辑（改成新建）', 'maker'));
    }

    /* clear_form（:1505-1543）：⚠️ 不删除磁盘上的图标文件 */
    function clearForm() {
      openDialog({ title: t('clear_form', '清空表单', 'maker'),
        body: t('确定要清空当前填写的所有内容吗？', '确定要清空当前填写的所有内容吗？', 'maker'),
        confirmText: t('清空', '清空', 'maker'), cancelText: t('取消', '取消', 'maker'), danger: true })
        .then((yes) => { if (yes) resetMakerForm(); });
    }
    function resetMakerForm() {
      maker.name = '';
      maker.id = '';
      maker.code = nextCode();
      /* 清空表单 = 回到初始态：类别三语都是内置默认「工具」（各分段显示自己的译名），
         标签三语**全空**（本轮需求：「而且默认标签输入框为空」，且不再有「跟随类别」）。 */
      maker.category = { 简体中文: makerCategories[0], 繁體中文: makerCategories[0], English: makerCategories[0] };
      maker.tags = { 简体中文: '', 繁體中文: '', English: '' };
      maker._nameAuto = true;          // 清空表单 = 回到「名称跟着上方走」的初始态
      maker.systems = [];
      maker.icon = '';
      maker.iconName = '';
      maker.iconSource = '';
      maker.iconPicked = false;
      maker.iconPending = false;
      maker.iconData = '';
      maker.links = [];
      maker.iconExt = '';
      maker.url = '';
      /* 下载地址（下载页面网址）以前漏清 —— 「保存到原列表」/「清空表单」之后那一栏
         还挂着上一条资源的网址就是这个原因（m06170 括号里那条）。*/
      maker.downloadPageUrl = '';
      /* 多组开源仓库复位成「一组空的 GitHub」——
         与老行为（清空后是一个空的 GitHub 输入框）等价。 */
      maker.repos = [newRepoRow()];
      maker.author_url = '';
      maker.chat_url = '';
      maker.loadedDownloadUrl = '';
      maker.listedAt = '';
      maker.loadedId = '';
      maker.loadedName = '';
      maker.isNewEntry = true;
      maker.editingExisting = false;
      maker.editingId = '';
      maker.editingCode = '';
      makerBaseline.value = '';            // 没有基线了，「未保存」提示自然消失
      makerLanguages.forEach((lang) => {
        ['name', 'description', 'intro', 'supplement'].forEach((key) => { maker.i18n[lang][key] = ''; });
      });
      i18nEnabled.value = true;
      i18nLangIndex.value = Math.max(0, makerLanguages.indexOf(uiLanguage()));
    }

    /* 资源浏览（BrowserPage，:1978-2781）：11 列，顺序即数组 */
    const browserQuery = ref('');
    const browserCategory = ref('');
    const browserSelected = ref('');
    /* 列表滚动位置（m06170：双击进编辑再回到「资源浏览」，列表被弹回最顶端）。
       这一页是 v-if 切的，DOM 整块重建，scrollTop 天生归零 ⇒ 只能自己记一份。*/
    const browserScroll = ref(null);
    let browserScrollTop = 0;
    /* 资源浏览自己的「本地 / 云端」下拉（m04892 第②项）。
       ⚠️ 三条硬约束，都是用户原话里点名的：
         1)「这个选择云端和本地也不会储存在配置里，一直默认为本地」
            ⇒ 只是一个组件内 ref：**不写 settings、不写 localStorage**，
              重启/重进制作器一律回到 local。谁以后想"顺手持久化"就是改需求。
         2) 它只影响这张表：设置里的「资源来源」照旧管搜索页/定制页/收藏页，
            两者互不干涉（用户这次报的痛点正是"设置改云端后这里也跟着乱"）。
         3) 云端那份**只读**：镜像每次同步都同名覆盖里面的一切，往里写=静默丢数据
            （上一轮 maker 写盘事故的同一条根因），所以云端下不许双击进表单、
            不许删除。 */
    const browserSource = ref('local');
    const browserSourceOptions = computed(() => [
      { value: 'local', label: t('browser_source_local', '本地', 'maker') },
      { value: 'cloud', label: t('browser_source_cloud', '云端', 'maker') },
    ]);
    const browserReadonly = computed(() => browserSource.value === 'cloud');
    const browserRowsSource = ref([]);      // 当前这一档（本地/云端）现读到的那份
    /* browserRowsLoaded：区分「这一档已经读到了」（可能是 0 条）与「还没读」。
       没读成（例如浏览器预览模式没有 maker.browse）才允许退回 items 那份。 */
    const browserRowsLoaded = ref(false);
    /* browse 返回的是**磁盘原始 dict**（三语言字段还是字典）。留一份是为了双击进表单时直接用它，
       而不是再调 resources.detail —— 后者跟着「设置 → 资源来源」解析，会出现
       「列表是本地那份、载入的是云端那份」的串台（m05525 第④项要求两个开关互相独立）。 */
    const browserRowsRaw = ref([]);
    const browserRowsPath = ref('');        // 本次实际读到的文件，给「打开资源库文件」用
    const browserRowsLoading = ref(false);
    const browserCategoryOptions = computed(() => [{ value: '', label: t('all_categories', '全部类别', 'maker') }]
      .concat(makerCategories.map((c) => ({ value: c, label: term(c) }))));
    /* 读云端镜像：走 maker.browse（**只读**后端，不触发网络同步、不写任何文件）。
       失败/接口不存在就把下拉退回本地 —— 宁可让用户看到本地那份，
       也不要留一张空表让人以为资源库被清空了。 */
    async function loadBrowserRows() {
      /* ⚠️ 两个档**都**走 maker.browse 现读磁盘（m05525）：
         下拉选「本地」就必须是本地那份，选「云端」就是镜像那份，
         完全不受 设置 → 资源来源 影响 —— 用户明确说这两个开关是独立的。
         （以前本地档直接复用搜索页的 items，而 items 是按设置里的来源解析的，
         于是设置=云端时，「本地」列出来的其实还是云端镜像。） */
      const want = browserSource.value === 'cloud' ? 'cloud' : 'local';
      browserRowsLoading.value = true;
      try {
        const result = await bridge.tryCall('maker.browse', want);
        if (!result) {
          needApi('maker.browse', '读取资源库');
          /* 桌面端没有这个接口（浏览器预览模式）：本地档退回 items 那份，
             云端档没得退，只能把下拉弹回本地，别让用户对着一张空表。 */
          if (want === 'cloud') browserSource.value = 'local';
          browserRowsRaw.value = [];
          browserRowsLoaded.value = false;
          return;
        }
        if (!result.ok) {
          toast(String(result.error || t('tip_error', '错误', 'maker')), 'error',
            t('section_browser', '资源浏览', 'maker'));
          if (want === 'cloud') browserSource.value = 'local';
          browserRowsRaw.value = [];
          browserRowsLoaded.value = false;
          return;
        }
        browserRowsPath.value = String(result.path || '');
        browserRowsRaw.value = Array.isArray(result.items) ? result.items : [];
        // 三语言字段是原始字典，必须过 mapItem（和搜索页同一套压平口径），
        // 否则这一列会显示 [object Object]。
        browserRowsSource.value = (result.items || []).map((raw) => mapItem(raw));
        browserRowsLoaded.value = true;
        /* 列表刚重建 → 把记下的位置放回去（重建之后 scrollTop 是 0）。 */
        nextTick(() => { if (browserScroll.value) browserScroll.value.scrollTop = browserScrollTop; });
        if (want === 'cloud' && !result.mirrored) {
          toast(t('cloud_not_cached', '云端还没有本地镜像，现在显示的是本地那份', 'maker'),
            'info', t('browser_source_cloud', '云端', 'maker'));
        }
      } catch (error) {
        if (want === 'cloud') browserSource.value = 'local';
        browserRowsRaw.value = [];
        browserRowsLoaded.value = false;
        toast(String((error && error.message) || error), 'error', t('section_browser', '资源浏览', 'maker'));
      } finally {
        browserRowsLoading.value = false;
      }
    }
    watch(browserSource, () => {
      browserScrollTop = 0;              // 换了一份文件，位置没有可比性，回到顶端
      browserSelected.value = '';      // 两份列表的 code 可能对不上，别留脏选中
      loadBrowserRows();
    });
    /* 每次切进「资源浏览」都现读一次：写盘/删条目之后回到这一页要看到最新的那份，
       不能依赖搜索页那份 items 的刷新时机（两者现在已经是两条独立的路）。 */
    watch(activeSection, (key, old) => {
      /* 离开这一页时记下滚动位置；回到这一页时由 loadBrowserRows 还原。
         Vue 的 watch 默认 pre-flush，回调跑在 DOM 更新之前，这里还读得到旧节点。*/
      if (old === 'browser' && browserScroll.value) browserScrollTop = browserScroll.value.scrollTop;
      if (key === 'browser') loadBrowserRows();
      /* 其余三个分节同样要记 / 恢复：四个分节容器是 v-if 重建的，切走就被销毁，
         不补这一句的话"表单滚到中间 → 看一眼资源浏览 → 切回表单"会掉回顶端 ——
         和需求①说的"切走再切回要回到原位"是同一件事，只是发生在投稿页内部。
         这里必须**显式带旧/新分节名**：watch 回调跑的时候 activeSection.value 已经是新值了，
         直接传 "maker" 会让 scrollMemoryKey 用新分节去记旧容器的位置（串味）。
         browser 跳过：它有自己那套（上面两行的 browserScrollTop + loadBrowserRows 里还原），
         两边同时驱动同一个容器只会互相覆盖。 */
      if (old && old !== 'browser') rememberPageScroll('maker:' + old);
      if (key && key !== 'browser') nextTick(() => restorePageScroll('maker:' + key));
    });
    const browserRows = computed(() => {
      const key = browserQuery.value.trim().toLowerCase();
      const category = browserCategory.value;
      const source = (browserRowsLoaded.value || browserSource.value === 'cloud')
        ? browserRowsSource.value : items.value;
      /* 与搜索页同一口径（passesFilters / matchKeyword）：筛选与关键词匹配都用**并集**，
         这样"只在某个语言池里填过的类别/标签"在资源浏览里也筛得出、搜得到。
         两个来源（maker.browse 现读的那份 / items 那份）都过 mapItem，都有并集字段。 */
      return source.filter((r) => {
        const cats = r.category_all || r.category || [];
        if (category && cats.indexOf(category) < 0) return false;
        if (!key) return true;
        if (String(r.code).toLowerCase().indexOf(key) >= 0) return true;
        if (String(r.name).toLowerCase().indexOf(key) >= 0) return true;
        if (String(r.id).toLowerCase().indexOf(key) >= 0) return true;
        return cats.concat(r.tags_all || r.tags || [])
          .some((item) => String(item).toLowerCase().indexOf(key) >= 0);
      }).map((r) => ({
        ...r,
        iconName: r.icon ? decodeURIComponent(String(r.icon).split('/').pop()) : '',
      }));
    });
    /* count_label 只在筛选时显示（browser_shown），不筛选时不重复页头的条数 */
    const browserCountText = computed(() => ((browserQuery.value.trim() || browserCategory.value)
      ? t('browser_shown', '筛选中 · 显示 {n} / 共 {total} 条', 'maker')
        .replace('{n}', browserRows.value.length)
        .replace('{total}', ((browserRowsLoaded.value || browserSource.value === 'cloud')
          ? browserRowsSource.value : items.value).length)
      : ''));
    /* 「重新载入」= 现读下拉选中的那一份（本地/云端都由 maker.browse 决定，
       与设置里的资源来源无关）；本地档顺带把搜索页那份 items 也刷一次，
       因为那一页显示的仍是「设置来源」的那份，用户可能马上就切过去看。 */
    function reloadLibrary() {
      loadBrowserRows().catch(() => {});
      if (browserSource.value !== 'cloud') loadResources().catch(() => {});
    }
    function openLibraryFile() {
      const target = (browserSource.value === 'cloud' && browserRowsPath.value)
        ? browserRowsPath.value : libraryDir();
      bridge.tryCall('shell.open_path', target).then((result) => {
        if (!result) { needApi('shell.open_path', '打开资源库文件'); return; }
        if (!result.ok) toast(t('打不开', '打不开', 'maker'), 'error', t('tip_error', '错误', 'maker'));
      });
    }

    /* 「打开图标文件夹」（m06170：导入的图标在 .ToolsGCP\images\icon 里找不到）。
       图标分三层，同名时生效的那层才是该打开的目录：
         ① <数据根>\config\icons              制作器导入的新图（现在都写这里）
         ② <程序目录>\.ToolsGCP\images\icon   程序自带
         ③ <数据根>\config\cloud\icons        云端镜像
       到底命中哪一层由后端算 —— 前端自己拼路径必然和 webhost 的取图口径打架。*/
    async function openIconFolder() {
      const info = await bridge.tryCall('maker.icon_dirs', maker.iconName);
      if (!info) { needApi('maker.icon_dirs', '打开图标文件夹'); return; }
      if (!info.ok) { toast(String(info.error || ''), 'error', t('tip_error', '错误', 'maker')); return; }
      const result = await bridge.tryCall('shell.open_path', info.current);
      if (!result) { needApi('shell.open_path', '打开图标文件夹'); return; }
      if (!result.ok) {
        toast(t('open_icon_folder_failed', '打不开这个文件夹', 'maker'), 'error',
          t('tip_error', '错误', 'maker'));
        return;
      }
      toast(t('icon_here_hint', '这张图当前用的是：{path}', 'maker')
        .replace('{path}', info.resolved || info.current),
        'info', t('icon', '图标', 'maker'));
    }
    /* 双击资源浏览里的一行 → 直接进入编辑已有资源界面。
       先拿 resources.detail 的完整数据（列表接口可能只带摘要），再灌进表单；失败就用列表那份。
       ⚠️ resources.detail 现在把 name/description/intro/supplement 以**原始三语言字典**
          返回（后端走的是"loader 保留原始副本"这条路），所以灌进表单后三种语言都有内容。
          ⚠️ 兜底（detail 接口不存在/失败）时用的是列表那份 —— 列表那一路是 mapItem 压平过的
             **字符串**，于是只有简体中文有内容（这是老后端的老行为，不是回归）。 */
    async function editExistingEntry(row) {
      /* 云端镜像只读（m04892 第②项）：不许从云端那份进编辑，
         否则用户改完点保存，写的是本地资源库，界面上那条云端记录却纹丝不动
         —— 看起来像"保存没生效"。要改请先切回本地。 */
      if (browserReadonly.value) {
        toast(t('browser_readonly_cloud', '云端镜像是只读的：要修改请先切回「本地」', 'maker'),
          'info', t('browser_source_cloud', '云端', 'maker'));
        return;
      }
      if (!row) return;
      if (row.code) browserSelected.value = row.code;
      let raw = row;
      /* 本地档且现读成功 → 用 browse 那份原始 dict：三语言字典齐全，而且来源和眼前的列表是同一份。
         读不到（后端没这个接口 / 这一档退回了 items）才走 resources.detail。 */
      const mine = String(row.code || '');
      const hit = mine && browserSource.value !== 'cloud' && browserRowsLoaded.value
        && (browserRowsRaw.value || []).find((it) => String(it.code || '') === mine);
      if (hit) raw = hit;
      if (row.code && raw === row) {
        const result = await bridge.tryCall('resources.detail', row.code);
        if (result && result.ok && result.item) {
          /* 以列表那份打底、再用 detail 覆盖：detail 缺字段时不会把列表里已有的值弄丢，
             而 detail 带回来的多语言**字典**会盖掉列表那份的单语言字符串。 */
          raw = Object.assign({}, row, result.item);
        }
      }
      /* 以前这里没有任何兜底：loadResourceIntoForm 里八十多行顺序赋值，中间抛异常就会把
         maker._loading 永久留在 true（函数开头置位、结尾才清），此后改名不再跟随、
         改编号不再跟随，而且界面停在浏览页不给任何提示 —— 只能重启。m05525 的
         「双击不跳转」正是同一类中断（rawName 越界），这次一并兜住。 */
      try {
        loadResourceIntoForm(raw);
      } catch (error) {
        maker._loading = false;
        toast(String((error && error.message) || error), 'error', t('tip_error', '错误', 'maker'));
        return;
      }
      activeSection.value = 'form';
      toast(t('editing_existing_tip', '正在编辑「{name}」（{code}）：产出区可用「保存到原列表」写回这一条。', 'maker')
        .replace('{name}', pickI18n(raw.name, '') || row.name || '')
        .replace('{code}', raw.code || row.code || ''),
        'info', t('edit_mode', '编辑已有资源', 'maker'));
    }
    /* 删掉载入到制作资源按钮对应的 loadSelectedIntoForm（双击已等效）。 */
    function deleteSelectedEntries() {
      if (browserReadonly.value) {
        toast(t('browser_readonly_cloud', '云端镜像是只读的：要修改请先切回「本地」', 'maker'),
          'info', t('browser_source_cloud', '云端', 'maker'));
        return;
      }
      if (!browserSelected.value) {
        toast(t('先在表格里选一行', '先在表格里选一行', 'maker'),
          'warning', t('没有选中任何条目', '没有选中任何条目', 'maker'));
        return;
      }
      needApi('maker.delete_entries', '删除选中条目');
    }

    /* 批量合成（BatchPage，:2788-3272） */
    const batchMode = ref('append');            // MODE_APPEND 默认
    const batchDup = ref('skip');
    const batchFiles = ref([]);                 // [{name, entries, count, error}]
    const batchFileIndex = ref(0);
    const batchOutput = ref('ToolsGCP-Resources-merged.json');
    const batchPreviewText = ref(t('点「预览结果」看看会合并进来多少条。', '点「预览结果」看看会合并进来多少条。', 'maker'));
    const batchModeOptions = computed(() => [
      { value: 'append', label: t('追加到本机资源库（默认）', '追加到本机资源库（默认）', 'maker') },
      { value: 'merge', label: t('多个 JSON 合并成新文件', '多个 JSON 合并成新文件', 'maker') },
    ]);
    const batchDupOptions = computed(() => [
      { value: 'skip', label: t('跳过重复（推荐）', '跳过重复（推荐）', 'maker') },
      { value: 'overwrite', label: t('重复的覆盖旧条目', '重复的覆盖旧条目', 'maker') },
      { value: 'keep', label: t('全部保留（重新分配编码）', '全部保留（重新分配编码）', 'maker') },
    ]);
    /* read_sources（:3071-3093）：utf-8-sig；dict 取 resources / items，list 直接用 */
    function batchAddFiles() {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = '.json,application/json';
      input.multiple = true;
      input.onchange = async () => {
        const files = Array.prototype.slice.call(input.files || []);
        for (let i = 0; i < files.length; i += 1) {
          const file = files[i];
          try {
            const data = JSON.parse((await file.text()).replace(/^\uFEFF/, ''));
            const rows = Array.isArray(data) ? data
              : (Array.isArray(data.resources) ? data.resources
                : (Array.isArray(data.items) ? data.items : []));
            const entries = rows.filter((row) => row && typeof row === 'object');
            batchFiles.value.push({ name: file.name, entries, count: entries.length, error: '' });
          } catch (error) {
            batchFiles.value.push({ name: file.name, entries: [], count: 0,
              error: (error && error.message) || String(error) });
          }
        }
        batchFileIndex.value = 0;
      };
      input.click();
    }
    function batchRemoveSelected() {
      if (batchFileIndex.value < 0 || batchFileIndex.value >= batchFiles.value.length) return;
      batchFiles.value.splice(batchFileIndex.value, 1);
      batchFileIndex.value = 0;
    }
    function batchClearFiles() { batchFiles.value = []; batchFileIndex.value = 0; }
    function batchChooseOutput() { batchOutput.value = 'ToolsGCP-Resources-merged.json'; }
    function uniqueId(id, list) {
      const base = String(id || 'resource');
      let n = 2;
      while (list.some((it) => it.id === base + '-' + n)) n += 1;
      return base + '-' + n;
    }
    /* merge_entries（:3111-3122）：逐条按 编码 → id → 名称 三级匹配 */
    function mergeEntries(base, incoming, dup) {
      const out = base.slice();
      let added = 0, skipped = 0, overwritten = 0, recoded = 0;
      incoming.forEach((raw) => {
        let hit = -1;
        if (raw.code) hit = out.findIndex((it) => it.code && it.code === raw.code);
        if (hit < 0 && raw.id) hit = out.findIndex((it) => it.id && it.id === raw.id);
        if (hit < 0 && raw.name) hit = out.findIndex((it) => it.name && it.name === raw.name);
        if (hit >= 0) {
          if (dup === 'skip') { skipped += 1; return; }
          if (dup === 'overwrite') { out[hit] = raw; overwritten += 1; return; }
          const copy = { ...raw };
          copy.id = uniqueId(copy.id, out);
          copy.code = nextCodeFrom(out);
          out.push(copy);
          recoded += 1;
          added += 1;
          return;
        }
        const copy = { ...raw };
        if (!copy.code) copy.code = nextCodeFrom(out);
        out.push(copy);
        added += 1;
      });
      return { out, added, skipped, overwritten, recoded };
    }
    /* preview（:3159-3188） */
    function batchPreview() {
      const good = batchFiles.value.filter((f) => !f.error);
      const bad = batchFiles.value.filter((f) => f.error);
      if (!batchFiles.value.length) {
        toast(t('先添加要合成的 JSON', '先添加要合成的 JSON', 'maker'), 'warning', t('还没选文件', '还没选文件', 'maker'));
        return;
      }
      const incoming = [];
      good.forEach((f) => { f.entries.forEach((row) => incoming.push(row)); });
      const before = items.value.length;
      const result = mergeEntries(items.value, incoming, batchDup.value);
      const lines = [t('merge_src_summary', '源文件 {files} 个，共 {n} 条：', 'maker')
        .replace('{files}', good.length).replace('{n}', incoming.length)];
      good.slice(0, 8).forEach((f) => {
        lines.push(t('merge_src_item', '    {name} — {n} 条', 'maker')
          .replace('{name}', f.name).replace('{n}', f.count));
      });
      if (good.length > 8) lines.push(t('merge_more_files', '    …还有 {n} 个文件', 'maker').replace('{n}', good.length - 8));
      lines.push(t('merge_result', '结果：新增 {added} 条，跳过重复 {skipped} 条，覆盖 {overwritten} 条，重新编号 {recoded} 条', 'maker')
        .replace('{added}', result.added).replace('{skipped}', result.skipped)
        .replace('{overwritten}', result.overwritten).replace('{recoded}', result.recoded));
      lines.push(t('merge_count_change', '资源库将从 {before} 条变成 {after} 条', 'maker')
        .replace('{before}', before).replace('{after}', result.out.length));
      if (bad.length) lines.push('⚠️ ' + t('⚠️ 读不了的文件：', '⚠️ 读不了的文件：', 'maker')
        + bad.map((f) => f.name).join(', '));
      batchPreviewText.value = lines.join('\n');
    }
    /* run（:3190-3261） */
    async function batchRun() {
      if (batchMode.value === 'append') {
        const incoming = [];
        batchFiles.value.forEach((f) => f.entries.forEach((row) => incoming.push(row)));
        if (!incoming.length) {
          toast(t('先添加要合成的 JSON', '先添加要合成的 JSON', 'maker'), 'warning', t('还没选文件', '还没选文件', 'maker'));
          return;
        }
        const result = mergeEntries(items.value, incoming, batchDup.value);
        const yes = await openDialog({ title: t('确认合成', '确认合成', 'maker'),
          body: t('confirm_merge_write', '将把 {n} 条新条目写入本机资源库：\n{path}\n\n（写入前会把旧资源库滚动备份一份）', 'maker')
            .replace('{n}', result.added).replace('{path}', libraryFullPath()),
          confirmText: t('开始合成', '开始合成', 'maker'), cancelText: t('取消', '取消', 'maker') });
        if (!yes) return;
        /* 后端 maker.append_entries 会自己做一遍合并（按 id/code 去重）+ 原子写盘 + 备份，
           这里把「模式 / 重复策略」一起传过去；返回的 added/skipped 才是真实结果。 */
        const written = await bridge.tryCall('maker.append_entries', result.out,
          { mode: 'append', duplicate: batchDup.value });
        if (!written) {
          downloadJson('ToolsGCP-Resources.json', JSON.stringify(libraryPayload(result.out), null, 2) + '\n');
          toast(t('maker_append_not_ready', '桌面端接口 <maker.append_entries> 未就绪：已导出合并后的资源库，请自行放回 ') + libraryFullPath(),
            'warning', t('tip_warning', '提示', 'maker'));
          return;
        }
        if (!written.ok) {
          toast(written.error || t('write_failed', '写入失败', 'maker'), 'error', t('tip_error', '错误', 'maker'));
          return;
        }
        toast(t('merged_ok', '已合并 {n} 条到资源库（写盘前已滚动备份 1 份）', 'maker')
          .replace('{n}', written.added != null ? written.added : result.added)
          + (written.skipped ? t('，跳过重复 {n} 条', '，跳过重复 {n} 条', 'maker').replace('{n}', written.skipped) : '')
          + librarySourceHint(),
          'success', t('完成', '完成', 'maker'));
        /* 写完把资源库重新拉一遍，页面上的条目列表立刻是最新的（不用手动刷新） */
        try { await loadResources(); } catch (e) { /* 刷新失败不影响已写入的结果 */ }
        return;
      }
      if (!String(batchOutput.value || '').trim()) {
        toast(t('先选一个保存位置', '先选一个保存位置', 'maker'), 'error', t('出错了', '出错了', 'maker'));
        return;
      }
      const incoming = [];
      batchFiles.value.forEach((f) => f.entries.forEach((row) => incoming.push(row)));
      const result = mergeEntries([], incoming, batchDup.value);
      let name = String(batchOutput.value).trim();
      if (!/\.json$/i.test(name)) name += '.json';
      /* 需求：批量合成要真的能产出文件，而不是"只下载到浏览器下载目录"。
         先让后端写进资源库同目录（原子写 + 不覆盖原文件），拿不到后端才退回下载。 */
      const written = await bridge.tryCall('maker.append_entries', result.out,
        { mode: 'new', output: name });
      if (written && written.ok) {
        toast(t('generated_ok', '已生成 {path}（{n} 条）', 'maker')
          .replace('{path}', written.path || name).replace('{n}', result.out.length),
          'success', t('完成', '完成', 'maker'));
        return;
      }
      if (written && !written.ok) {
        toast(written.error || t('write_failed', '写入失败', 'maker'), 'error', t('tip_error', '错误', 'maker'));
        return;
      }
      const payload = { schema_version: '2.0.0',
        metadata: { icon_dir: 'Icon', updated_at: nowIso(), total_count: result.out.length },
        resources: result.out };
      downloadJson(name, JSON.stringify(payload, null, 2) + '\n');
      toast(t('generated_ok', '已生成 {path}（{n} 条）', 'maker')
        .replace('{path}', name).replace('{n}', result.out.length),
        'success', t('完成', '完成', 'maker'));
    }

    /* 使用说明（HelpPage，:3276-3373）：按【小节】/[小节] 切块，每块一张卡 */
    const MAKER_HELP_FALLBACK = [
      '【这个页面能做什么】',
      '制作 / 浏览 / 合并 ToolsGCP 资源库里的条目。资源库固定是程序目录下的',
      '.ToolsGCP/ToolsGCP-Resources.json，制作器不会另外生成一份。',
      '',
      '【投稿表单】',
      '名称和标识 id 是必填项；编码由程序自动分配，不用手动改。',
      '类别的可选项来自内置类别表，也可以直接输入新类别；标签默认留空。',
      '类别和标签都属于「多语言字段」：切到哪个语言分段就填哪一种语言，三种语言各填各的；',
      '内置项会自动显示成该语言的写法（如 Tools / 遊戲），输入任一种语言的写法都会认得出来。',
      '适用系统与 CPU 架构都可以多选，留空表示还没确定。',
      '',
      '【图标】',
      '可选。导入的图片会按「名称」自动改名（保留中文），支持 png / jpg / gif / ico / webp / svg。',
      '生成给作者的稿件时，图片会按另一套规则命名（只留字母数字和 -_），',
      '两套规则不一样是原版行为。',
      '',
      '【多语言字段】',
      '默认开启，里面是六个各自独立的输入池：名称、简介、应用介绍、补充、类别、标签。',
      '切分段就是切池子，三种语言互不覆盖；名称默认跟着上方「名称」一起变，',
      '在下面单独改过任何一种语言后就脱离跟随（点「跟随名称」可恢复）。',
      '三种语言内容完全相同时不会写成字典，仍然是一个纯字符串/数组（老数据同形）。',
      '',
      '【产出】',
      '· 生成稿件：输出 <id>/resource.json + 说明文件（+ 图标），打包成 <id>.zip 发给作者；',
      '· 追加到本机资源库：写入前把旧文件滚动备份成固定名的 1 份（用户数据目录 backups/ToolsGCP-Resources.prev.json）；',
      '· 保存到原列表（仅编辑已有资源时出现）：把当前表单按原 id / 编码写回载入的那一条，不会新增重复条目；',
      '· 另存为独立资源库：走系统「另存为」，默认文件名 ToolsGCP-Resources.json，图标会复制到旁边的 Icon/；',
      '· 清空表单：只清界面，不会删除磁盘上的图片。',
      '',
      '【资源浏览】',
      '表格里能直接看到编码 / 名称 / 类别 / 标签 / 官网 / 仓库 / 简介 / 上架时间；',
      '双击一行直接进入编辑界面（表头出现「编辑已有资源」徽标，产出区多出「保存到原列表」）。',
      '',
      '【批量合成】',
      '追加模式：把投稿文件里的条目合进本机资源库，重复的按「重复条目」策略处理；',
      '新建模式：把多个 JSON 合并成一个新文件，本机资源库不受影响。',
    ].join('\n');
    const makerHelpText = computed(() => t('help_text', MAKER_HELP_FALLBACK, 'maker'));
    const makerHelpBlocks = computed(() => {
      const lines = String(makerHelpText.value || '').split('\n');
      const blocks = [];
      let current = null;
      lines.forEach((line) => {
        const hit = line.match(/^\s*[【\[](.+?)[】\]]\s*$/);
        if (hit) {
          if (current) blocks.push(current);
          current = { title: hit[1], body: '' };
        } else if (current) {
          current.body += (current.body ? '\n' : '') + line;
        }
      });
      if (current) blocks.push(current);
      const out = blocks.map((b) => ({ title: b.title, body: b.body.trim() })).filter((b) => b.body || b.title);
      return out.length ? out : [{ title: '', body: String(makerHelpText.value || '') }];
    });

    /* 双栏规则：≥1080 两列，否则右列落到表单下面（layout.css 的媒体查询） */
    const makerLeft = ref(null);
    const makerRight = ref(null);
    const formScroll = ref(null);
    const previewCard = ref(null);
    const makerBody = ref(null);
    function syncMakerPreviewSticky() { /* 预览卡由 CSS position:sticky 吸顶 */ }
    function syncMakerColumns() { /* 单栏 / 双栏由 layout.css 媒体查询决定，这里不需要内联样式 */ }

    /* 资源库条数变化时补一次自动编码（同一份资源库文件）
       ⚠️ 首次进页面时 items 还是空的，等资源库载入后必须重新按最大值 +1 分配 */
    watch(() => items.value.length, () => { if (!maker.code || maker.codeAuto) maker.code = nextCode(); });
    if (!maker.code) { maker.code = nextCode(); maker.codeAuto = true; }
    /* ---------- 设置页（10 个板块，顺序 = _section_definitions） ---------- */
    const draft = reactive({ ...DEFAULT_SETTINGS });
    const settingQuery = ref('');
    const currentSection = ref('appearance');
    const flashRow = ref('');
    /* 本轮新增：滚动停稳后闪**整个板块**（用户要的是"对应区域闪两下"；
       行级 flashRow 只服务搜索命中那条路径，两者独立、互不干扰）。 */
    const flashSection = ref('');
    const recording = ref('');
    const apiKeyDraft = ref('');
    const apiKeyVisible = ref(false);
    const checkingUpdate = ref(false);
    const settingsScroll = ref(null);
    const hotStatusMap = reactive({ search: '', ai: '' });

    function optionsFor(values, labels) {
      return values.map((v, i) => ({ value: v, label: (labels && labels[i]) || v }));
    }
    function fontLabel(value) {
      const map = { 微软雅黑: t('font_label_default', '微软雅黑'), 等线: t('font_label_dengxian', '等线 (DengXian)'),
        'Segoe UI': t('font_label_segoe', 'Segoe UI'), SimSun: t('font_label_simsun', '宋体 (SimSun)'),
        SimHei: t('font_label_simhei', '黑体 (SimHei)'), KaiTi: t('font_label_kaiti', '楷体 (KaiTi)'),
        FangSong: t('font_label_fangsong', '仿宋 (FangSong)'), Consolas: t('font_label_consolas', 'Consolas（等宽）'),
        'JetBrains Mono': t('font_label_jetbrains', 'JetBrains Mono（等宽）') };
      return map[value] || t('font_label_other', value);
    }
    /* 设置 → 存储只展示「存储位置」这一个路径（需求：去掉位置记录文件那一行）。
       数据根 = info.dataDir 去掉末尾的 config（…\.ToolsGCP\config → …\.ToolsGCP）。 */
    function storagePaths() {
      const data = String(info.dataDir || '');
      const root = data.replace(/[\\/]+config[\\/]?$/i, '');
      return { root: root || '—' };
    }
    /* 存储位置迁移进度（原版 cards_storage.py 的进度条 + “正在迁移 x/y”提示）。
       ⚠️ 迁移在**后端后台线程**里跑（settings.migrate_data_root 立刻返回），
          所以这里轮询 settings.data_root_progress 来更新百分比。 */
    const storageMigrate = reactive({ active: false, percent: 0, text: '', done: 0, total: 0,
                                      finished: false, ok: false, message: '' });
    let storagePollTimer = null;
    function stopStoragePoll() {
      if (storagePollTimer) { clearInterval(storagePollTimer); storagePollTimer = null; }
    }
    /* ---------- 迁移完成后的需要重启弹窗 ----------
       存储更改完配置后会立即弹窗提示要重启并且点击 esc 和空白处都关不掉。
       旧数据根已经搬走、不重启会继续读写旧路径，所以这个弹窗必须是**强制**的：
       cancelable:false（Esc 无效）+ backdropClose:false（点空白无效）。 */
    async function restartAfterStorageChange() {
      const result = await bridge.tryCall('shell.restart');
      if (!result) return needApi('shell.restart', '重启程序');
      if (result.ok === false) {
        toast(t('restart_failed', t('error', '错误')) + '：' + (result.error || ''), 'error');
      }
    }
    function promptStorageRestart(message) {
      /* 文案复用语言文件里已有的 restart_* / storage_restart_hint 键 → 三语立刻生效，
         不新造 key，后端不用跟着补词条；万一以后补了 storage_restart_body 会优先用它。
         ⚠️ 弹窗中只有一个重启按钮 删除稍后手动重启——
            存储位置改完必须重启才生效，给稍后等于让用户拿一个半生效的界面，
            所以这里**只留立即重启一个按钮**。
            ⚠️ answer() 的语义：只有一个按钮时 buttons.length === 1 → 走
               `resolve(label === yes)` → 点它得 true → 触发重启 ✅ */
      const now = t('restart_now', '立即重启');
      openDialog({
        title: t('restart_required', '需要重启'),
        body: t('storage_restart_body', t('storage_restart_hint', '重启程序后完全生效')),
        notes: String(message || ''),
        buttons: [now],
        wide: true,
        backdropClose: false,
        cancelable: false,
      }).then((value) => { if (value) restartAfterStorageChange(); });
    }
    function startStoragePoll() {
      stopStoragePoll();
      storagePollTimer = setInterval(async () => {
        const result = await bridge.tryCall('settings.data_root_progress');
        if (!result || !result.ok) return;
        storageMigrate.percent = Number(result.percent || 0);
        storageMigrate.text = String(result.text || '');
        storageMigrate.done = Number(result.done || 0);
        storageMigrate.total = Number(result.total || 0);
        if (!result.running && result.finished) {
          stopStoragePoll();
          storageMigrate.finished = true;
          /* ⚠️ 进度里的成败字段叫 success（不能叫 ok —— 会覆盖信封自己的 ok=True） */
          storageMigrate.ok = !!result.success;
          if (result.success) {
            loadPaths();
            /* 迁移成功 → 立刻弹「需要重启」对话框（不再只弹 toast）；
               Esc / 点空白都关不掉，原因见 promptStorageRestart 的注释。 */
            promptStorageRestart(result.message);
          } else {
            toast(t('storage_failed', '迁移失败') + '\\n' + (result.message || ''), 'error');
          }
          setTimeout(() => {
            storageMigrate.active = false;
            storageMigrate.percent = 0;
            storageMigrate.text = '';
          }, 2500);
        }
      }, 200);
    }

    /* 当前索引文件：xxx这行 note 已按用户要求删除（和资源目录重复），
       所以 currentIndexText() 一起删掉 —— 留着就是死代码。 */

    /* 下载保存位置输入框的占位提示 = 系统下载文件夹。
       ⚠️ 后端有真值：downloader.default_dir() → {ok, path}（= <用户主目录>\Downloads，
          去掉了自动生成的 ToolsGCP 子目录）。拿不到时也别显示空白 ——
          用一句通用文案兜底（那句文案只是**占位提示**，不是真路径，别当真值用）。 */
    const downloadDefaultDir = ref('');
    async function loadDownloadDefaultDir() {
      const result = await bridge.tryCall('downloader.default_dir');
      if (result && result.ok && result.path) {
        downloadDefaultDir.value = String(result.path);
      }
    }
    function defaultDownloadDirText() {
      const saved = String(draft.download_save_dir || '').trim();
      if (saved) return saved;
      /* 有后端真值就显示真路径（用户能一眼看到"下载到哪"） */
      if (downloadDefaultDir.value) return downloadDefaultDir.value;
      return t('set_download_default_dir', '系统「下载」文件夹');
    }

    /* ---------- 云端资源库状态（设置 → 资源来源 下方一行轻量提示） ----------
       需求原话：自动选择最新版本，程序自动判断，然后自动找到里面名为
                 ToolsGCP-Resources.json 然后加载进本地+在资源来源下面加一条轻量状态。
       后端接口约定（core-data 实现）：
         resources.cloud_status()        → {ok, configured, available, version, updated_at, count, error, path}
         resources.cloud_refresh(force)  → {ok, ...}
       ⚠️ 接口不存在（bridge.tryCall 返回 null）时**整行不显示** —— 不假装成功、
          也不拿"未配置/开发中"之类的话占位（那就是此前被用户骂的误导信息）。 */
    const cloudStatus = ref(null);
    const cloudSyncing = ref(false);
    function cloudTimeText(value) {
      const raw = String(value || '').trim();
      if (!raw) return '';
      /* 后端可能给 ISO 时间串：能解析就本地化成 "YYYY-MM-DD HH:mm"，解析不了就原样显示 */
      const parsed = new Date(raw);
      if (isNaN(parsed.getTime())) return raw;
      const pad = (n) => (n < 10 ? '0' + n : String(n));
      return parsed.getFullYear() + '-' + pad(parsed.getMonth() + 1) + '-' + pad(parsed.getDate())
        + ' ' + pad(parsed.getHours()) + ':' + pad(parsed.getMinutes());
    }
    /* 错误码 → 用户看得懂的话。
       后端约定错误只抛机器码：`error` = NETWORK / BAD_RESPONSE / ... ，
       `error_key` = 'cloud_error_<CODE>'，界面拿它查三语语言包。
       ⚠️ 语言包没这个词（旧版语言包 / 后端新增了码）时把机器码原样交出去，
          绝不编造"已修复/开发中"之类的假状态。 */
    function cloudErrorText(error, errorKey) {
      const code = String(error || '').trim();
      const key = String(errorKey || '').trim();
      if (!key) return code;                     // 旧后端没有 error_key → 回退显示机器码
      return t(key, code || key);
    }
    /* 一行字说完：版本 + 条数 + 更新时间（或拉取失败原因）；拿不到数据返回空串 → 整行不渲染 */
    const cloudStatusText = computed(() => {
      if (cloudSyncing.value) return t('cloud_lib_syncing', '云端资源库：正在检查最新版本…');
      const status = cloudStatus.value;
      if (!status) return '';
      const version = String(status.version || '').trim().replace(/^v/i, '');
      const count = Number(status.count) || 0;
      const error = String(status.error || '').trim();
      if (status.available) {
        const line = t('cloud_lib_ready', '云端资源库：v{version}（{count} 条）')
          .replace('{version}', version || '?').replace('{count}', String(count));
        const time = cloudTimeText(status.updated_at);
        return time ? line + ' · ' + t('cloud_lib_updated', '更新于 {time}').replace('{time}', time) : line;
      }
      if (error || status.error_key) {
        return t('cloud_lib_failed', '云端资源库：拉取失败（{error}）')
          .replace('{error}', cloudErrorText(status.error, status.error_key))
          + ' ' + t('set_cloud_lib_failed_hint', '可在「设置 → 下载 → 搜索源」换一个镜像源后重试。');
      }
      return '';                                    // 没数据也没原因 → 不显示（不编造状态）
    });
    async function readCloudStatus() {
      const status = await bridge.tryCall('resources.cloud_status');
      if (!status) { cloudStatus.value = null; return null; }        // 后端没这个接口 → 降级隐藏
      if (status.ok === false && !String(status.error || '').trim()) { cloudStatus.value = null; return null; }
      cloudStatus.value = status;
      return status;
    }
    /* 切到云端时顺手拉一次最新的（异步，绝不 await 在保存流程里阻塞 UI）；
       设置页右侧重试图标也走这里 —— 优先用 cloud_retry（强制完整重试链），
       旧后端没有 cloud_retry 时退回 cloud_refresh(true)。 */
    async function refreshCloudLibrary(force) {
      const status = await readCloudStatus();
      if (!status) return;                          // 接口不存在 → 什么都不做
      const canRetry = bridge.has('resources.cloud_retry');
      if (!force || (!canRetry && !bridge.has('resources.cloud_refresh'))) return;
      cloudSyncing.value = true;
      try {
        const result = canRetry
          ? await bridge.tryCall('resources.cloud_retry')
          : await bridge.tryCall('resources.cloud_refresh', true);
        if (result && result.ok === false) {
          /* 刷新失败：把原因（机器码 + 语言键）挂到状态上，界面显示"拉取失败（原因）"，
             不显示旧的版本号骗人。 */
          cloudStatus.value = { ok: false, available: false,
            error: String(result.error || '').trim(),
            error_key: String(result.error_key || '').trim() };
          /* 失败时**明确告诉用户可以换镜像源**。
             ⚠️ 状态行上也会写同一句（cloudStatusText 里），这里是额外的 toast 提醒，
                手动点重试图标时用户能马上看到。 */
          toast(t('set_cloud_lib_failed', '云端资源库拉取失败：{error}')
            .replace('{error}', cloudErrorText(cloudStatus.value.error, cloudStatus.value.error_key))
            + ' ' + t('set_cloud_lib_failed_hint', '可在「设置 → 下载 → 搜索源」换一个镜像源后重试。'),
            'error');
        } else {
          await readCloudStatus();
          /* 拉取成功**也要报提示**（云端资源拉取成功也会报提示）。
             ⚠️ 只在真的拉到东西时提示（available=true），否则"已是最新"也弹一次会很吵。 */
          const latest = cloudStatus.value;
          if (latest && latest.available) {
            const version = String(latest.version || '').trim().replace(/^v/i, '');
            const count = Number(latest.count) || 0;
            toast(t('set_cloud_lib_ok', '云端资源库已更新：v{version}（{count} 条）')
              .replace('{version}', version || '?').replace('{count}', String(count)), 'success');
          }
        }
      } finally {
        cloudSyncing.value = false;
      }
    }
    /* **启动时**后台刷新一次云端资源库用的"安静版"。
       ⚠️ 为什么不用 refreshCloudLibrary()：它失败时会弹一个 error toast
          （'set_cloud_lib_failed'）—— 启动时这个提示会和 boot 里那条
          云端资源库加载失败的提示重复，两个 toast 叠在一起很吵。
       ⚠️ 这个版本失败**只更新 cloudStatus**（设置页那一行状态会显示原因），
          不弹任何 toast，也不改用户的设置。 */
    async function refreshCloudLibraryQuiet() {
      /* ⚠️ **优先用异步版** `resources.cloud_refresh_async`。
         同步的 cloud_refresh / cloud_retry 会**同步跑网络**（单次超时 60s + 镜像回退，
         最坏一分多钟）—— 放在启动流程里即使不 await，也会长时间占住 js_api 的调用线程，
         而且窗口出来后设置页的正在同步会一直转。
         异步版**立刻返回** `{started:true}`，真正的拉取在后台线程，
         跑完推 `cloud.refresh.done` 事件（见下面 onEvent 的监听），前端零阻塞。 */
      if (bridge.has('resources.cloud_refresh_async')) {
        cloudSyncing.value = true;
        try {
          await bridge.tryCall('resources.cloud_refresh_async', true);
        } catch (error) { cloudSyncing.value = false; }
        /* ⚠️ 不在这里 finally 里清 cloudSyncing —— 真正的收尾在
           `cloud.refresh.done` 事件里（后台线程还没跑完）。 */
        return;
      }
      const canRetry = bridge.has('resources.cloud_retry');
      if (!canRetry && !bridge.has('resources.cloud_refresh')) return;
      cloudSyncing.value = true;
      try {
        const result = canRetry ? await bridge.tryCall('resources.cloud_retry')
                                : await bridge.tryCall('resources.cloud_refresh', true);
        if (result && result.ok === false) {
          cloudStatus.value = { ok: false, available: false,
            error: String(result.error || '').trim(),
            error_key: String(result.error_key || '').trim() };
        } else {
          await readCloudStatus();
          await loadResources();          // 拉到新版 → 刷新列表
        }
      } catch (error) { /* 静默：启动不该因为云端失败而打扰用户 */ }
      finally { cloudSyncing.value = false; }
    }
    function hotStatus(name) { return hotStatusMap[name] || ''; }

    /* ---------- 云端图标（icon.zip）后台同步 ----------
       和 JSON 一样的"安静版"：启动后丢后台跑（`resources.icons_sync_async`
       **立刻返回**），跑完推 `cloud-icons-updated` 事件 → 下面 onEvent 里
       把 iconRetry 清零 + iconEpoch+1，所有卡片重画一次 <img>。
       ⚠️ 为什么要 iconEpoch：只清 iconRetry 的话，**从来没失败过**的图标
         （从自带目录成功加载的那些）src 字符串不变 → 浏览器不会重新请求 →
         换成云端新图也看不到。epoch 拼进 URL 才是真正的"强制重取"。
       ⚠️ 本地模式 / 后端没这个接口：bridge.has 判空直接跳过（tryCall 返回 null
          也要显式降级，AGENTS 第 3 节）。 */
    const iconEpoch = ref(0);
    async function syncCloudIconsQuiet() {
      if (!bridge.has('resources.icons_sync_async')) return;
      try { await bridge.tryCall('resources.icons_sync_async', false); } catch (error) { /* 静默 */ }
    }

    /* 设置左侧栏每个板块的图标（需求：每项 text 前面加上对应图标，从外观到关于） */
    const SECTION_ICONS = {
      appearance: 'palette', animation: 'motion', startup: 'play', search: 'search',
      /* 快捷键分区：换掉原来的齿轮（setting）。需求：「设置中左侧面板中的快捷键的那个图标
         我不喜欢 换一个更贴切实际意思的图标」—— 齿轮在整个设置页到处都有，放这一行等于
         没有信息量；键盘才是"按哪几个键"的字面意思。dev 那条仍是 developer（开发者模式），
         两者不再撞同一个图标。 */
      hotkey: 'keyboard', download: 'download',
      /* 本轮新增的「更新」分区：图标沿用 download（下载箭头）会和左边那一项撞成两个
         一模一样的图标，看不出区别 —— 用 refresh（循环箭头 = "检查新版本"的字面意思），
         和通知的 megaphone、功能的 application 也都不撞。 */
      update: 'refresh', notification: 'megaphone',
      behavior: 'application', storage: 'folder',
      ai: 'robot', dev: 'developer', about: 'info',
    };
    function sectionIcon(key) { return SECTION_ICONS[key] || 'setting'; }

    const sections = computed(() => {
      const speedOn = !!draft.download_speed_limit_enabled;
      const localSource = draft.resource_source === 'local';
      const aiOn = !!draft.ai_enabled;
      const hotOn = !!draft.hotkey_enabled;
      const devVerified = !!(draft.dev_mode_enabled && draft.dev_mode_admin);
      /* ⚠️ 本轮删除三个局部变量：`tokenOn` / `provider` / `modelOptions`。
         它们只服务于已被整块删除的「服务商+模型+接口+Key」卡和「token 限制」卡
         （见下面 GCP-AI 分组里那条注释）。留着就是死代码，而且 `provider`
         这个名字和档案系统里的 provider 概念容易混淆。 */
      const fonts = FONT_PREFERED.slice();
      const font = draft.ui_font_family || '微软雅黑';
      if (fonts.indexOf(font) < 0) fonts.unshift(font);
      const paths = storagePaths();
      return [
        { key: 'appearance', label: t('appearance', '外观'), cards: [[          { key: 'theme', type: 'select', label: t('theme_mode', '主题模式'),
            tip: t('theme_mode_desc', '跟随 Windows 的浅色 / 深色设置'),
            options: optionsFor(['跟随系统', '浅色主题', '深色主题'],
              [t('follow_system', '跟随系统'), t('light_theme', '浅色主题'), t('dark_theme', '深色主题')]) },
          /* 主题效果和组件配色两行调换位置 → 主题效果在前。
             宽度 200 与下面的组件配色（不写 width，默认 200）对齐。 */
          { key: 'theme_effect', type: 'select', width: 200, label: t('theme_effect', '主题效果'),
            tip: t('theme_effect_tip', '云母：几乎不糊、带一点底噪；毛玻璃：强模糊高透明；亚克力：中模糊加亮高光边。只影响标题栏、侧栏与弹层，内容区永远清晰'),
            options: [{ value: 'mica', label: t('fx_mica', '云母') },
              { value: 'glass', label: t('fx_glass', '毛玻璃') },
              { value: 'acrylic', label: t('fx_acrylic', '亚克力') }] },
          { key: 'accent_color', type: 'select', label: t('accent_color', '组件配色'),
            tip: t('accent_color_desc', '改的是开关 / 下拉框 / 滑块这些组件的颜色（AI 悬浮球背景不变）'),
            options: [{ value: 'blue', label: t('accent_blue', '蓝色') },
              { value: 'purple', label: t('accent_purple', '紫罗兰') },
              { value: 'orange', label: t('accent_orange', 'Claude橙') }] },
          { key: 'language', type: 'select', label: t('language', '语言'),
            tip: t('language_desc', '切换后立即生效，整个界面（含资源库名称与简介）会直接换成所选语言'),
            options: optionsFor(['跟随系统', '简体中文', '繁體中文', 'English'],
              [t('follow_system', '跟随系统'), '简体中文', '繁體中文', 'English']) },
          { key: 'ui_font_family', type: 'select', label: t('ui_font', '字体'),
            tip: t('ui_font_desc', '整个界面的字体，选完立刻生效'),
            options: fonts.map((v) => ({ value: v, label: fontLabel(v) })) },
        ]] },
        /* 新增动画区（外观 → 动画 → 启动）：把 UI 动画强度、启动动画、滚动惯性
           这三类"会动的东西"从外观 / 功能里拆出来，分区不再混在一起。 */
        { key: 'animation', label: t('animation_section', '动画'), cards: [[
          { key: 'ui_animation', type: 'select', width: 200, label: t('ui_animation', '动画'),
            tip: t('ui_animation_tip', '开启：全部动画；减少动画：所有界面过渡缩短、反馈更利落；关闭动画：除程序启动动画外全部关闭（左侧栏选中标会直接跳过去）'),
            options: [{ value: 'on', label: t('motion_on', '开启') },
              { value: 'reduced', label: t('motion_reduced', '减少动画') },
              { value: 'off', label: t('motion_off', '关闭动画') }] },
          { key: 'splash_screen_enabled', type: 'switch', label: t('splash_screen', '启动动画'),
            /* 兜底文案与语言包 zh_CN 的 splash_screen_tip **逐字一致**（本轮需求：
               时长设置项删掉了，画面存活期改由主流程决定，提示必须说明"自动消失"，
               否则用户会以为还得自己去关它）。 */
            tip: t('splash_screen_tip', '开启后，程序启动时显示启动画面，直到主界面就绪后自动消失') },
          /* ⚠️ 本轮按需求**删除**了"启动动画时长"滑块（splash_screen_duration）：
             「设置中的启动动画时长删除，这个从此就不要了……显示时长相关代码改为
              程序什么时候出现这个悬浮启动画面就什么时候消失」。
             后端 constants.py / settings_manager.py / shell.py / splash.py 已同步去掉
             时长概念，app.splash_remaining 现在恒返回 0（见下面 boot 里的注释）。 */
          /* 滚动惯性（从功能搬进来）：滚停后保留一点点动量继续滑一小段。默认关闭。 */
          { key: 'scroll_inertia', type: 'switch', label: t('scroll_inertia', '滚动惯性'),
            tip: t('scroll_inertia_tip', '开启后，滚动页面停手时还会顺势滑行一小段（约 60~140px），像真实的惯性滚动。默认关闭') },
          { key: 'scroll_inertia_strength', type: 'slider', indent: true, label: t('scroll_inertia_strength', '惯性大小'),
            tip: t('scroll_inertia_strength_tip', '数值越大，松手后顺势滑行得越远。默认 35%，可调范围 1%~100%'),
            min: 1, max: 100, step: 1, unit: t('percent_unit', '%'), visible: !!draft.scroll_inertia },
        ]] },
        { key: 'startup', label: t('startup', '启动'), cards: [[
          { key: 'startup_with_windows', type: 'switch', label: t('startup_with_windows', '开机自启动') },
          { key: 'minimize_to_tray', type: 'switch', indent: true, label: t('minimize_to_tray', '启动时最小化到托盘'),
            tip: t('minimize_to_tray_tip', '开启后，开机自启动时将隐藏到托盘，不会显示主窗口'),
            visible: !!draft.startup_with_windows },
          { key: 'default_page', type: 'select', width: 180, label: t('default_page', '默认启动页面'),
            /* ⚠️ 「首页」这一项已随首页整体删除（老配置里的 "首页" 由后端
               settings_manager 迁移成「搜索」，所以这里不需要再留一个无效选项）。
               ⚠️ 本轮修复（用户原话：「删除设置界面中的启动中的默认启动页面的下拉框中的
               第一个搜索，保留第二个搜索即可」）：这里原本**重复列了两条一模一样的
               "搜索"**（5527/5528 两行 value 与 label 全同）—— 下拉里看着就是两个
               "搜索"，选中哪个都是同一个值，纯属冗余。删掉多余的那一条。 */
            options: [{ value: '搜索', label: t('search_title', '搜索') },
              { value: '定制页', label: t('home_title', '定制页') },
              { value: '收藏', label: t('tools_gcp_title', '收藏') },
              { value: '部署', label: t('deploy_title', '应用部署') },
              { value: '设置', label: t('settings_title', '设置') }] },
        ]] },
        { key: 'search', label: t('search_settings', '搜索'), cards: [[
          { key: 'auto_search', type: 'switch', label: t('auto_search', '自动搜索'),
            tip: t('auto_search_tip', '开启后，输入时自动搜索；关闭后，需按Enter或点击搜索按钮才搜索') },
          { key: 'search_show_github', type: 'switch', label: t('show_github_button', '显示 GitHub 按钮'),
            tip: t('show_github_button_tip', '开启后，搜索页卡片右下角会显示 GitHub 按钮；默认开启') },
          { key: 'search_show_view_switch', type: 'switch', label: t('show_view_switch', '在搜索页显示视图切换按钮'),
            tip: t('show_view_switch_tip', '关闭后搜索页工具栏上的磁贴 / 网格切换按钮会隐藏，排序会往右靠拢补齐位置') },
          { key: 'search_view', type: 'select', width: 180, label: t('search_view_mode', '搜索页视图'),
            tip: t('search_view_mode_tip', '磁贴：一行 4 个大卡片；网格：一行 6 个小卡片，只保留收藏按钮'),
            options: [{ value: 'tile', label: t('search_view_tile', '磁贴') },
              { value: 'grid', label: t('search_view_grid', '网格') }] },
        ]] },
        { key: 'hotkey', label: t('hotkey_section', '快捷键'), cards: [[
          { key: 'hotkey_enabled', type: 'switch', label: t('hotkey_enable', '启用全局快捷键'),
            tip: t('hotkey_enable_tip', '开启后，快捷键由本程序独占，其它程序收不到该按键') },
          /* 启用全局快捷键关闭时，下面两项不显示（启用全局快捷键和GCP-AI更改一样 需要不显示）；
             并删除底部那句 hint note。 */
          { key: 'hotkey_search', type: 'hotkey', indent: true, disabled: !hotOn, visible: hotOn,
            label: t('hotkey_search', '呼出搜索框'),
            tip: t('hotkey_search_tip', '在任何程序里按下该组合键，都会把 ToolsGCP 拉到最前并聚焦搜索框'),
            statusText: hotStatus('search') },
          { key: 'hotkey_ai', type: 'hotkey', indent: true, disabled: !hotOn, visible: hotOn,
            label: t('hotkey_ai', '呼出 GCP-AI'),
            tip: t('hotkey_ai_tip', '在任何程序里按下该组合键，都会把 ToolsGCP 拉到最前并打开 AI 面板'),
            statusText: hotStatus('ai') },
          /* ★ 浏览器模式快捷键。
             本轮默认改成 **Ctrl+Shift+O**（不再用 Caps 做修饰键）→ 这条走普通的
             RegisterHotKey 那条路；含 Caps 的组合才会分流到低级键盘钩子
             （Caps Lock 既不能做主键也不能做修饰键，见 desktop/native/capskeyhook.py）。 */
          { key: 'hotkey_browser', type: 'hotkey', indent: true, disabled: !hotOn, visible: hotOn,
            label: t('hotkey_browser', '在浏览器中打开'),
            tip: t('hotkey_browser_tip', '在本机端口启动界面服务并用系统默认浏览器打开，桌面窗口同时隐藏到托盘；功能与桌面端完全一致。浏览器里的操作仍然由本程序响应，请不要退出程序（可从托盘图标恢复窗口）。'),
            statusText: hotStatus('browser') },
        ]] },
        { key: 'download', label: t('download', '下载'), cards: [[
          /* 删除第一行多余的资源来源subtitle（保留下面那个 select 行） */
          { key: 'resource_source', type: 'select', width: 170, label: t('resource_source_mode', '资源来源'),
            tip: t('resource_source_tip', '云端：使用作者发布在 GitHub Release 里的最新资源库，程序自动挑最新版本并读取其中的 ToolsGCP-Resources.json。本地：使用你自己电脑上的 ToolsGCP-Resources.json，适合改过资源库或离线调试。这里只决定资源库从哪读取，不影响下面的搜索源 / 下载源。'),
            options: [{ value: 'cloud', label: t('source_cloud', '云端（推荐）') },
              { value: 'local', label: t('source_local', '本地文件') }] },
          /* 云端资源库状态行。**往右缩进**，表示它归属于上面那个资源来源 = 云端；
             选了本地文件时这行**整个消失**（云端状态跟本地文件无关）。
             ⚠️ 缩进靠 row.indent → 模板给 .setting-row 加 is-indent（padding-left 20px）。 */
          { type: 'cloud-status', indent: true,
            visible: draft.resource_source === 'cloud' && !!cloudStatusText.value },
          /* 资源目录也往右缩进（它归属于资源来源 = 本地文件这个选项） */
          { key: 'local_resource_dir', type: 'dir', wide: true, indent: true, label: t('local_dir', '资源目录'),
            action: 'choose_resource_dir', actionLabel: t('choose_dir', '选择文件夹'),
            placeholder: info.configDir || '.ToolsGCP', visible: localSource },
          /* 删掉当前索引文件：xxx这行 note（删除当前索引文件text）——
             它和上面的资源目录重复，而且路径信息本身没什么用。 */
          /* 删掉本地资源功能还在开发中…警告 —— 云端拉取已经实现，留着纯属误导。
             也删掉资源来源与搜索源之间那条 divider（用户要求"删除中间多余的分割线"）。 */
          { key: 'search_source', type: 'select', width: 180, label: t('search_source', '搜索源'),
            tip: t('github_mirror_hint', '下面的镜像站会把上面的链接原样转发一份，国内下载通常快很多。这条不通就换一条，或者直接用上面的「下载」走 GitHub 官方。'),
            options: SOURCE_OPTIONS.map((v) => ({ value: v, label: v })) },
          /* ⚠️⚠️ 本轮（用户：「把下载来源改为下载源」）：这一行界面上一直显示「下载来源」而不是语言包里 settings 模块的「下载源」。
             根因**不在文案**，在取值：app.js 的 t() 先查扁平 map，而扁平 map 是
             I18nDomain.MODULES 声明序「先到先得」合并的 —— deploy(下载来源) 排在
             settings(下载源) 之前，同一个 key 谁先入表谁赢，settings 那份永远被遮住。
             修法 = t() 的第三参数按模块精确取值（t(key, fallback, 'settings') 直接读
             I18N.modules.settings，优先于扁平 map）。
             ⚠️ 刻意**不**去改 deploy_language.json 的那个键：部署页表头「安装路径·下载来源」
                本来就该叫「下载来源」（那是软件自己的下载页），它没错；两边共用一个 key 才是问题，
                按模块取值是代价最小的解法。同类重复键共 14 个，目前只有这一处会露出来。 */
          { key: 'download_source', type: 'select', width: 180,
            label: t('download_source', '下载源', 'settings'),
            tip: t('github_mirror_hint', '下面的镜像站会把上面的链接原样转发一份，国内下载通常快很多。这条不通就换一条，或者直接用上面的「下载」走 GitHub 官方。'),
            options: SOURCE_OPTIONS.map((v) => ({ value: v, label: v })) },
          /* 本轮拆卡（用户：「设置中的下载像GCP-AI那样分成几个卡片ui板块」）。
             分界按语义：卡 1 = 从哪取数据（资源来源 / 搜索源 / 下载源）；
             卡 2 = 怎么落盘（多线程下载 / 失败重试次数 / 下载保存位置 / 下载限速）。
             注意限速被挪到卡 2 的**最后一位**：用户原话是「把现在限制放到他们三个的
                下面的位置也就是第四个位置，不要放到第一个位置」 —— 它原来排在卡 2 开头，
                顺序错了会让人以为限速是下载的第一个开关。
             cards 是多数组结构（和 GCP-AI 分区同款），模板对每个数组各画一张
             .settings-card；整组都没有可见行时那张卡不画（cardHasVisibleRow）。 */
        ], [
          /* ---------- 下载相关的新设置 ----------
             顺序按在下载保存位置上面位置新增一个多线程下载…和失败重试次数→
             多线程、失败重试在**上**，下载保存位置在**下**。
             ⚠️ 多线程和失败重试都用 slider 行类型 —— 它渲染成
                **range 滑块 + 数字输入框**两件套，正好满足用户要的
                输入框样式的，还可以拉动进度条来调整大小。 */
          { key: 'download_threads', type: 'slider', label: t('set_download_threads', '多线程下载'),
            tip: t('set_download_threads_tip', '把一个文件拆成多段同时下载，段数越多速度上限越高（默认 100）。服务器不支持分段下载时会自动退回单线程。'),
            min: 1, max: 100, step: 1, unit: t('set_threads_unit', '个线程') },
          { key: 'download_retry_count', type: 'slider', label: t('set_download_retry', '失败重试次数'),
            tip: t('set_download_retry_tip', '下载失败后自动重试几次，每次间隔 30 秒。一旦连接成功，重试次数就回到默认值 5。'),
            min: 1, max: 20, step: 1, unit: t('set_times_unit', '次') },
          { key: 'download_save_dir', type: 'dir', wide: true, label: t('set_download_save_dir', '下载保存位置'),
            tip: t('set_download_save_dir_tip', '下载的文件存到哪里。留空 = 系统的「下载」文件夹（不再自动建 ToolsGCP 子目录）。'),
            action: 'choose_download_dir', actionLabel: t('choose_dir', '选择文件夹'),
            placeholder: defaultDownloadDirText() },
          { key: 'download_speed_limit_enabled', type: 'checkbox', label: t('download_speed_limit', '下载限速'),
            statusText: speedOn ? (draft.download_speed_limit || 100) + ' MB/s' : t('unlimited', '无限制') },
          { key: 'download_speed_limit', type: 'slider', indent: true, label: t('limit_speed', '限速'),
            min: 1, max: 300, step: 1, unit: 'MB/s', visible: speedOn },
        ]] },
        /* 「更新」分区（本轮需求：「新增一个更新板块 左侧栏也要同步有 把更新下载渠道和
           自动检查更新放进这里面，左侧在下载和通知之间 右侧区域也是这个位置之间」）。
           这两行原来混在下载区，但讲的是「更新怎么进行」，和下载文件本身无关，
           拆出来语义才对得上。顺序 = download → update → notification：左侧栏与右侧内容区
           用的是同一个 sections computed（模板 v-for sections），所以这里顺序对了，
           两处位置会一起对上，不需要再维护第二份清单。 */
        { key: 'update', label: t('update_section', '更新'), cards: [[
          { key: 'update_channel', type: 'select', width: 180, label: t('update_channel', '更新下载渠道'),
            tip: t('update_channel_tip', '决定「检查更新」愿意接受哪种发布：正式版 + Beta 版（默认）、只要正式版、或只要 Beta 版。'),
            options: [{ value: 'all', label: t('update_channel_all', '下载正式版和Beta版') },
              { value: 'stable', label: t('update_channel_stable', '仅下载正式版') },
              { value: 'beta', label: t('update_channel_beta', '仅下载Beta版') }] },
          /* ⚠️⚠️ 本轮新增（用户原话：「设置中的下载的更新下载渠道下面位置新增一个自动检查更新，
             默认下拉框选择在右上角提示，还有弹窗提示和关闭，……关闭则是开启程序后不进行自动更新检查」）：
             三态下拉，而不是开关 —— "发现新版后怎么打扰用户"本身就是三档：
               corner（默认）= 启动后静默检查，发现新版从右上角滑出精简提示；
               dialog        = 启动后静默检查，发现新版直接弹完整「发现新版本」窗；
               off           = 启动后完全不检查（设置里的「检查更新」按钮仍可随时手动点）。
             "在右上角提示"那句 = 本行下拉的悬浮说明（tip），和 update_channel_tip 同款形式。
             ⚠️ 键名必须同步进 constants.py DEFAULT_SETTINGS + 浏览器模式兜底（见下一行注释），
                不然后端设置合并/前端 draft 两边默认值会分叉。 */
          { key: 'update_auto_check', type: 'select', width: 180, label: t('update_auto_check', '自动检查更新'),
            tip: t('update_auto_check_tip', '打开程序后自动到 GitHub 看一眼有没有新版本。选「右上角提示」= 发现新版本时从屏幕右上角滑出一条精简提示（默认）；选「弹窗提示」= 直接弹完整的发现新版本窗口；选「关闭」= 启动后不自动检查，需要时自己去点「检查更新」。'),
            options: [{ value: 'corner', label: t('update_auto_check_corner', '右上角提示') },
              { value: 'dialog', label: t('update_auto_check_dialog', '弹窗提示') },
              { value: 'off', label: t('update_auto_check_off', '关闭') }] },
        ]] },
        /* 分区整理：原功能区里混着的 通知 / 行为 / 授权 各自独立成区 */
        { key: 'notification', label: t('notification_section', '通知'), cards: [[
          /* 需求：「启用提示」在最前（默认开启），「提示框位置」紧跟其后；
             关掉「启用提示」时，位置这一行**整行隐藏**。 */
          { key: 'notify_enabled', type: 'switch', label: t('enable_notification', '启用提示'),
            tip: t('enable_notification_tip', '关闭后不再弹出任何操作提示（成功 / 失败 / 警告那些小提示条）') },
          { key: 'toast_position', type: 'select', width: 180, label: t('toast_position', '提示框位置'),
            tip: t('toast_position_tip', '操作成功 / 失败那些从边上滑进来的小提示条，出现在屏幕哪个位置'),
            visible: !!draft.notify_enabled,
            /* ⚠️ 顶端改名顶端居中，并**排到右上角上面**（列表第一项）。
               ⚠️ value 保持 'top' 不变（老配置里的值还得能用）。 */
            options: [{ value: 'top', label: t('pos_top', '顶端居中') },
              { value: 'top_right', label: t('pos_top_right', '右上角') },
              { value: 'bottom_right', label: t('pos_bottom_right', '右下角') },
              { value: 'top_left', label: t('pos_top_left', '左上角') },
              { value: 'bottom_left', label: t('pos_bottom_left', '左下角') }] },
        ]] },
        /* 行为改回功能，并把原来的授权区合并进来（不再单独一区）。
           key 仍保留 behavior —— 搜索 / 滚动联动都按 key 走，改 key 没有收益。 */
        { key: 'behavior', label: t('functions', '功能'), cards: [[
          { key: 'nav_hover_expand', type: 'switch', label: t('nav_hover_expand', '侧栏鼠标靠近自动展开'),
            tip: t('nav_hover_expand_tip', '开启后，鼠标移到左侧栏上就会自动展开；关闭时只有点左上角的汉堡按钮才展开。默认关闭') },
          /* ---------- 「隐藏左侧栏元素」（本轮新增需求）----------
          /* Q 弹改为正向开关侧边栏指示Q弹效果，默认关闭（默认没有回弹）。
             新键 nav_indicator_bounce（旧键 nav_indicator_bounce_off 不再读取）。 */
          { key: 'nav_indicator_bounce', type: 'switch',
            label: t('nav_indicator_bounce', '侧边栏指示Q弹效果'),
            tip: t('nav_indicator_bounce_tip', '开启后蓝色选中标滑过去会带一点过冲回弹（拉伸保留）；默认关闭 = 干脆利落，到位即停') },
          { key: 'close_mode', type: 'select', width: 180, label: t('close_mode', '关闭模式'),
            tip: t('close_mode_tip', '选择点击关闭按钮时的行为：彻底退出或隐藏到托盘中'),
            options: [{ value: '彻底退出', label: t('close_mode_exit', '彻底退出') },
              { value: '隐藏到托盘中', label: t('close_mode_tray', '隐藏到托盘中') }] },
          /* 原授权区内容，合并到功能末尾 */
          { key: 'license_key', type: 'text', wide: true, label: t('gcp_license_key', 'GCP License Key'),
            tip: t('gcp_key_tip', '输入正确的GCP License Key可以解锁隐藏功能'),
            placeholder: t('input_gcp_key', '输入GCP License Key密钥'),
            action: 'verify_license', actionLabel: t('verify', '验证') },
        ]] },
        { key: 'storage', label: t('storage_section', '存储'), cards: [[
          /* 需求：设置 → 存储只留「存储位置」，不要「位置记录文件」行，
             也不要底下那句「这里只存放配置文件…」的说明。 */
          { type: 'path-ro', label: t('config_storage', '配置存储'), wide: true,
            desc: t('storage_location_desc', '配置、对话记录、日志都保存在这里'),
            tip: t('storage_location_tip', '资源文件（资源库、图标、语言包）不在这个目录里，它们跟着程序走'),
            value: paths.root, action: 'change_storage', actionLabel: t('storage_change', '更改') },
          /* 迁移进度（原版 cards_storage.py 的 ProgressBar + 提示；不迁移时不渲染） */
          { type: 'progress', key: 'storage_migrate', visible: !!storageMigrate.active },
        ]] },
        { key: 'ai', label: t('ai_section', 'GCP-AI'), cards: [
          [
            { key: 'ai_enabled', type: 'switch', label: t('ai_enable', '开启GCP-AI') },
            { key: 'ai_sidebar_mode', type: 'switch', label: t('ai_sidebar_mode', '改用侧边栏 AI 单独界面'),
              tip: t('ai_sidebar_mode_tip', '把 AI 从右下角悬浮球改成左侧栏里的一整页（位置在 GCP工坊下面）；开启后悬浮球会消失'),
              visible: aiOn },
            /* ⚠️ 本轮需求（用户确认）：设置行文案 + 按钮悬停提示都改成「启用润色」相关。
               key 仍是 ai_polish_enabled（不动配置），只改 label/tip 的**值**（三语一起改）。 */
            { key: 'ai_polish_enabled', type: 'switch', label: t('ai_polish_enable', '启用润色按钮'),
              tip: t('ai_polish_enable_tip', '开启后，GCP-AI 输入框最右侧（发送键左边）会出现一个「启用润色」小按钮，点一下把当前输入润色一遍；关闭后按钮消失。润色只改措辞，不发送、不进历史对话'),
              visible: aiOn },
            /* ⚠️ 本轮需求（用户原话）：「删除设置中的回答逐字输出选项 我本来设计的就是
               逐字输出不需要这个选项控制」—— 「回答逐字输出」这一行**整条删除**。
               设置项 ai_stream_enabled 这个**键仍然保留**（DEFAULT_SETTINGS / 旧配置文件里
               都还在），只是：前端不再画这一行、发送路径也不再读它（永远走流式，
               见 aiSend 里的 wantStream）。留着键是为了老用户配置不用迁移，
               删键反而会让 settings.set 报未知键 / 老配置带脏值。
               后端也不读它（是前端决定调 send_stream 还是 send）。 */
            { key: 'ai_context_rounds', type: 'select', width: 220, visible: aiOn, label: t('ai_context_window', '上下文范围'),
              tip: t('ai_context_tip', '每次提问时，把多少历史对话一起发给模型。历史记录永远完整保存，这里只影响发给模型的条数；选得越长越连贯，消耗的 token 也越多'),
              options: [{ value: 0, label: t('ai_context_full', '整个会话（最长记忆）') },
                { value: 10, label: t('ai_context_10', '最近 10 轮对话') },
                { value: 20, label: t('ai_context_20', '最近 20 轮对话') },
                { value: 30, label: t('ai_context_30', '最近 30 轮对话') }] },
            { key: 'ai_reply_mode', type: 'select', width: 220, visible: aiOn, label: t('ai_reply_mode', '回复模式'),
              tip: t('ai_reply_mode_tip', '控制回答的长度和细节。简洁：最多 4 行只给结论；标准：6 行内给推荐 + 一个备选；专业：10 行左右，带关键差异对比。任何模式都不会输出代码'),
              options: [{ value: 'standard', label: t('ai_mode_standard', '标准') },
                { value: 'concise', label: t('ai_mode_concise', '简洁') },
                { value: 'professional', label: t('ai_mode_professional', '专业') }] },
            /* 本轮需求：GCP-AI 分组新增「回复语言」下拉（值写 ai_reply_language）。
               选项优先用后端 model_choices().reply_languages，拿不到走前端兜底 4 项（同一套 value）。
               ⚠️ 沿用现有 type:'select' 行类型（自绘 combo，不是原生 select）。 */
            { key: 'ai_reply_language', type: 'select', width: 220, visible: aiOn,
              label: t('ai_reply_language', '回复语言'),
              tip: t('ai_reply_language_tip', '强制 GCP-AI 用某种语言回答；跟随输入语言 = 你用中文问就中文答。后端未就绪时此项仍可选，值照常保存'),
              options: aiReplyLangOptions() },
            /* ★ 本轮按需求**删除**了设置页里的「对话模式」这一行（用户原话：
               「删除对话模式的选项，但是 GCP-AI 聊天界面中的这个切换 ui 还是正常的，
                只是删除设置中的这个」）。
               注意：设置键 ai_chat_mode **保留**（constants.DEFAULT_SETTINGS、
               后端 chat_mode()、输入框旁的 Chat/Agent 胶囊全都还认它），
               胶囊继续读写同一个键并落盘 —— 删掉的只是设置页这一行 UI。 */
          ],
          [
            /* ══════════════════ 服务商配置（本轮设置页重构） ══════════════════
               需求原话：「把这个设置中的GCP-AI第二个部分的ui狂款删除和三部分的token限制也删除，
               添加服务商，点击之后下面大列表中出现一个类似卡片ui…」

               旧结构（已整块删除）：
                 · 第二张卡：服务商下拉 + 模型选择下拉 + 模型名称 + 接口地址 + API Key + 操作按钮
                 · 第三张卡：限制token输出开关 + 最小token量 + 最大token量
               为什么删：这两张卡把"服务商"做成了**全局单选**，于是
                 · 在设置里保存一个新厂商的 Key，就会把全局 model_name/ai_provider 覆盖掉
                   → 聊天"偷偷换了模型"（用户实测 bug）；
                 · token 上限只有全局一份，而各家输出上限差异很大。
               新结构：**有序的服务商档案列表**（顺序即优先级，第 0 条自动生效），
               每张长条卡片自带「支持模型 / 当前模型 / 接口地址 / API Key / token 上限」，
               数据源是后端 ai.profiles()（settings 里的 ai_provider_profiles）。
               ⚠️ 这一行只是**入口**，卡片/编辑器的 DOM 在 index.html 的
                  `row.type === 'provider-profiles'` 那一段。 */
            { type: 'provider-profiles', visible: aiOn },
          ],
        ] },
        { key: 'dev', label: t('developer_functions', '开发者功能'), cards: [[
          ...(devVerified ? [
            { type: 'dev-state', label: t('developer_identity_token', '开发者身份令牌'),
              admin: draft.dev_mode_admin, time: draft.dev_mode_verify_time },
            { key: 'debug_info_enabled_' + draft.dev_mode_admin, type: 'switch', label: t('debug_info', '调试信息'),
              tip: t('debug_info_tip', '开启后将在界面显示组件编号、对象名称、内存占用、渲染层级等底层调试信息，用于开发排错') },
          ] : [
            { key: 'dev_mode_key', type: 'text', wide: true, label: t('developer_identity_token', '开发者身份令牌'),
              tip: t('dev_mode_tip', '输入正确的密钥可解锁更多隐藏内容、调试功能及开放更多权限和指令'),
              placeholder: t('input_dev_key', '输入管理员身份验证密钥'),
              action: 'save_dev_key', actionLabel: t('verify', '验证') },
          ]),
        ]] },
        { key: 'about', label: t('about', '关于'), cards: [] },
      ];
    });

    function isVisible(row) { return row.visible !== false; }
    /* 一整张设置卡片里**没有任何可见行**时，卡片外壳也要一起隐藏。
       根因：模板里 `<div class="settings-card">` 一直渲染，里面每一行才各自判断
       `isVisible(row)`。所以关闭 GCP-AI之后，AI 分区的第 2、3 张卡片**每一行**
       都不可见，但**空卡片壳**（圆角 + padding + 阴影）还留在页面上 ——
       这就是用户说的并没有完全隐藏还是留了 2 部分露了出来。
       ⚠️ 注意 isVisible 的语义是没有 visible 字段 = 可见，
          所以开启GCP-AI那一行（总开关，必须常显）会让第 1 张卡保留 —— 这是对的。 */
    function cardHasVisibleRow(card) {
      return (card || []).some((row) => isVisible(row));
    }
    function rowKey(section, row) { return section.key + '/' + (row.key || row.type); }
    const settingHits = computed(() => {
      const key = settingQuery.value.trim().toLowerCase();
      if (!key) return [];
      const hits = [];
      sections.value.forEach((section) => {
        section.cards.forEach((card) => card.forEach((row) => {
          const words = [row.label, row.text, row.desc, row.placeholder]
            .concat((row.options || []).map((o) => o.label));
          if (words.some((v) => String(v || '').toLowerCase().indexOf(key) >= 0)) {
            hits.push({ section: section.label, label: row.label || row.text || row.type,
              key: row.key, sectionKey: section.key });
          }
        }));
      });
      return hits.slice(0, 40);
    });
    function jumpFirstHit() { if (settingHits.value.length) jumpToRow(settingHits.value[0]); }
    function jumpToRow(hit) {
      currentSection.value = hit.sectionKey;
      /* 行级闪光也要**等滚动停稳再闪**（以前是立刻置位：人还在滚，闪光在被滚走的
         画面上演完，等于没闪）；传进 scrollSection 的 second 参数统一调度。 */
      scrollSection(hit.sectionKey, hit.key || hit.sectionKey);
    }
    /* ⚠️⚠️ 本轮需求（用户原话）：「点击设置中的左侧栏选项会滚动页面到对应位置时应该在
       停止滚动页面时这个对应区域应该有那种闪两下的那种，之前我记得做过可以参考一下，
       对了如果之前的没有做成停指滚动到对应位置时就闪修一下。」
       旧实现的两个不合格点：① `jumpToRow`（搜索命中）是**立刻**闪、不等滚动停止；
       ② `.setting-row.is-flash` 只闪一下（900ms ease 无 iteration）。
       → 现在：scrollSection 之后启动 stopThenFlash —— 平滑滚动没有 scrollend 可用
          （WebView2 的内核不保证支持），就用 rAF 轮询 scrollTop：**连续 100ms 不动
          才算停稳**，2000ms 兜底（超远距离 + 低帧率也够）；停稳后给整个
          `.settings-section` 挂 is-flash，CSS 侧 `flashSection … 2` 闪两下；
          搜索命中额外再闪那一行。ui_animation=off 时滚动是瞬时的，轮询第一轮就判停，
          闪光照常。 */
    let flashStopToken = 0;
    function stopThenFlash(sectionKey, rowKey) {
      const host = settingsScroll.value;
      if (!host) return;
      /* 连点两个不同栏目：旧的轮询作废（token 自增），不作废的话两条轮询会
         各自把 is-flash 挂到自己那一块上 —— 用户看到的是"两块同时在闪"。 */
      const token = ++flashStopToken;
      let last = host.scrollTop, stableMs = 0, waited = 0, prev = performance.now();
      const tick = () => {
        if (token !== flashStopToken) return;
        const now = performance.now();
        const dt = now - prev; prev = now; waited += dt;
        stableMs = Math.abs(host.scrollTop - last) < 1 ? stableMs + dt : 0;
        last = host.scrollTop;
        if (stableMs >= 100 || waited >= 2000) {
          flashSection.value = sectionKey;
          if (rowKey) flashRow.value = sectionKey + '/' + rowKey;
          setTimeout(() => {
            if (token !== flashStopToken) return;
            if (flashSection.value === sectionKey) flashSection.value = '';
            if (rowKey && flashRow.value === sectionKey + '/' + rowKey) flashRow.value = '';
          }, 1400);                          // 650ms × 2 下 + 余量（CSS 改时长记得同步这里）
          return;
        }
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }
    function scrollSection(key, flashRowKey) {
      currentSection.value = key;
      const host = settingsScroll.value;
      const el = host && host.querySelector('.settings-section[data-key="' + key + '"]');
      if (!el || !host) return;
      /* ⚠️ 状态机（task-4 ①，替换旧的 scrollLockUntil=700ms 延时补丁）：
         点左栏 = 进入 locked。程序化滚动期间**和滚动稳定之后**，选中项都保持点击项，
         scroll 事件一概不改 currentSection —— 不看时间戳，只看"是不是用户自己动手滚"。
         旧版两个硬伤：① 延时 700ms 一过，长距离平滑滚动还没停，spy 照样把
         「GCP-AI/开发者功能」改成「关于」；② spy 里"触底就选最后一个板块"的分支
         正好命中靠底的这两个板块。现在 locked 只能被**用户滚动意图**（wheel /
         touch / 键盘翻页键 / 拖动滚动条）解除，见 markUserScrollIntent。 */
      spyMode = 'locked';
      userScrollIntent = false;
      /* 关闭动画时连"平滑滚动"也关掉（它是 JS 行为，不走 CSS 过渡） */
      host.scrollTo({ top: Math.max(0, el.offsetTop - 6),
        behavior: settings.ui_animation === 'off' ? 'auto' : 'smooth' });
      /* 本轮：点左栏 → 滚动**停稳后**闪这个板块两下（flashRowKey 传了则连带闪那一行） */
      stopThenFlash(key, flashRowKey || '');
    }
    /* ---------- 左栏选中 ↔ 滚动 的状态机 ----------
       spyMode：'free' = scrollspy 跟随滚动；'locked' = 程序化滚动（点左栏/点搜索结果），
       选中项钉在点击项上。userScrollIntent 由"用户自己动手滚"的四类事件置位，
       scroll 事件里看到它才把 locked 交还给 free —— 延时假装正常的做法已删除。 */
    let spyMode = 'free';
    let spyRaf = 0;
    let userScrollIntent = false;
    function markUserScrollIntent() { userScrollIntent = true; }
    function isEditableTarget(el) {
      if (!el || !el.tagName) return false;
      const tag = el.tagName.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
      return !!(el.isContentEditable);
    }
    /* 用户滚动意图检测：监听挂在 document 捕获阶段（设置页没挂载时 host 为 null，直接忽略）。
       ⚠️ 只认"真的会滚 .settings-main 的操作"：
         · wheel / touch 必须发生在容器内部；
         · 键盘只认翻页类按键，且焦点不在输入控件里（输入框里方向键是移光标，不是滚页面）；
         · 滚动条拖动：mousedown 落在容器自身且横坐标进入滚动条区域。 */
    document.addEventListener('wheel', (e) => {
      const host = settingsScroll.value;
      if (host && host.contains(e.target)) markUserScrollIntent();
    }, { capture: true, passive: true });
    document.addEventListener('touchstart', (e) => {
      const host = settingsScroll.value;
      if (host && host.contains(e.target)) markUserScrollIntent();
    }, { capture: true, passive: true });
    document.addEventListener('mousedown', (e) => {
      const host = settingsScroll.value;
      if (!host || e.target !== host) return;
      const barWidth = host.offsetWidth - host.clientWidth;
      if (barWidth > 0 && e.clientX >= host.getBoundingClientRect().right - barWidth) {
        markUserScrollIntent();
      }
    }, { capture: true });
    document.addEventListener('keydown', (e) => {
      if (page.value !== 'settings') return;
      const nav = ['ArrowDown', 'ArrowUp', 'PageDown', 'PageUp', 'Home', 'End', ' '];
      if (nav.indexOf(e.key) < 0) return;
      const host = settingsScroll.value;
      if (!host) return;
      const target = e.target;
      /* 输入控件里的方向键/空格是编辑行为，不算"滚页面" */
      if (isEditableTarget(target)) return;
      if (target === document.body || target === document.documentElement || host.contains(target)) {
        markUserScrollIntent();
      }
    }, { capture: true });
    /* 离开设置页 → 解除 locked：下次进来时 spy 该按恢复的滚动位置正常工作 */
    watch(page, (v) => { if (v !== 'settings') { spyMode = 'free'; userScrollIntent = false; } });
    /* 进入设置页 → 载入服务商档案列表（本轮重构：卡片数据来自后端 ai.profiles()）。
       ⚠️ 只在**进入**时拉一次；保存/删除后由各自函数就地更新返回的列表，
          不在这里做轮询（设置页不是实时数据）。 */
    watch(page, (v) => {
      if (v !== 'settings') return;
      loadAiProviderCatalog();
      loadAiProfiles();
    });
    function syncSectionFromScroll() {
      if (spyMode === 'locked') {
        /* 程序化滚动（或它刚稳定下来）期间的 scroll 事件：保持点击项，什么都不做。
           只有带着"用户动手滚了"的标记才交还 scrollspy —— 状态切换由意图驱动，不由时间驱动。 */
        if (!userScrollIntent) return;
        userScrollIntent = false;
        spyMode = 'free';
      }
      if (spyRaf) return;
      spyRaf = requestAnimationFrame(() => {
        spyRaf = 0;
        /* 排队期间用户点了左栏 → 已进 locked：这一帧作废，别把选中改回滚动位置 */
        if (spyMode === 'locked') return;
        const host = settingsScroll.value;
        if (!host) return;
        const nodes = Array.from(host.querySelectorAll('.settings-section'));
        if (!nodes.length) return;
        /* ⚠️ 删掉了旧版"触底就选最后一个板块"的分支 —— 它正是"点 GCP-AI/开发者功能
           自己跳到关于"的另一半根因（这两个板块本来就靠底，滚动到位≈触底）。
           触底时改为选**视口里真正可见的最后一节**：板块顶边落在视口内即可当选，
           既不会永远停在倒数第二，也不会无故跳到没露脸的板块。 */
        if (host.scrollTop + host.clientHeight >= host.scrollHeight - 4) {
          const bottom = host.scrollTop + host.clientHeight;
          let last = nodes[0].dataset.key;
          nodes.forEach((node) => { if (node.offsetTop < bottom - 8) last = node.dataset.key; });
          currentSection.value = last;
          return;
        }
        const value = host.scrollTop + 60;
        let picked = nodes[0].dataset.key;
        nodes.forEach((node) => { if (node.offsetTop <= value) picked = node.dataset.key; });
        currentSection.value = picked;
      });
    }
    /* 设置搜索：清空关键词并恢复左栏板块列表（点清除按钮 / Esc 都走这里）。
       Esc 传 $event 并阻断冒泡：不然 app 的 onKeydown Esc 链会把详情页/弹窗一起关掉，
       用户在搜索框里按 Esc 只想清字。⚠️ 已经是空的时候**不拦**——空框里按 Esc
       应该继续走全局 Esc 链（关弹窗/退详情），别把那条链掐断。 */
    function clearSettingQuery(event) {
      if (!settingQuery.value) return;
      if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
      settingQuery.value = '';
    }

    /* ---------- 写设置（走 settings.set：落盘 + OP 日志；失败回滚） ---------- */
    async function saveSetting(key, value) {
      const previous = settings[key];
      settings[key] = value;
      draft[key] = value;
      settingsState.value = settings;
      if (key === 'theme' || key === 'accent_color' || key === 'ui_font_family'
        || key === 'theme_effect' || key === 'ui_animation') applyAppearance();
      const result = await bridge.tryCall('settings.set', key, value, false);
      if (!result) { settings[key] = previous; draft[key] = previous; needApi('settings.set', '保存设置'); return false; }
      if (!result.ok) {
        settings[key] = previous; draft[key] = previous;
        if (key === 'theme' || key === 'accent_color' || key === 'ui_font_family'
          || key === 'theme_effect' || key === 'ui_animation') applyAppearance();
        toast(t('save_failed', '保存失败：') + (result.error || key), 'error');
        return false;
      }
      /* 插件联动（用户最新要求，覆盖 的完全独立）：
         · 启用插件制作辅助 → 一并启用AI Agent（manifest.companion 方向）；
         · 关闭AI Agent     → 一并关闭插件制作辅助；
         · 只开AI Agent**不**会自动开插件制作辅助（/plugin 门控保持独立，见 ）。
         后端 ai.set_agent_enabled 的配置页开关同一口径（desktop/api/ai.py）。 */
      /* ⚠️ gcp_ai_agent_enabled 现在是**强制开启**（manifest.locked）：这里不再做
         "关 Agent → 连带关制作辅助"的联动（那个方向已经没有意义了）。
         保留"开制作辅助 → 带开 Agent"这一条（虽然 Agent 恒开，但设置值要一致）。 */
      if (key === 'gcp_ai_agent_enabled' && value === false) {
        /* 强制开启：写回去 true，别让界面显示成"关"而实际还在工作 */
        settings.gcp_ai_agent_enabled = true;
        draft.gcp_ai_agent_enabled = true;
        settingsState.value = settings;
        bridge.tryCall('settings.set', 'gcp_ai_agent_enabled', true, false).catch(() => {});
      }
      if (false && key === 'gcp_ai_agent_enabled' && value === false && settings.gcp_plugin_maker_enabled) {
        settings.gcp_plugin_maker_enabled = false;
        draft.gcp_plugin_maker_enabled = false;
        settingsState.value = settings;
        bridge.tryCall('settings.set', 'gcp_plugin_maker_enabled', false, false).catch(() => {});
        loadPlugins(false);
      } else if (key === 'gcp_plugin_maker_enabled' && value === true && !settings.gcp_ai_agent_enabled) {
        settings.gcp_ai_agent_enabled = true;
        draft.gcp_ai_agent_enabled = true;
        settingsState.value = settings;
        bridge.tryCall('settings.set', 'gcp_ai_agent_enabled', true, false).catch(() => {});
        loadPlugins(false);
      }
      return true;
    }
    const chain = { tail: Promise.resolve() };
    function queue(fn) { chain.tail = chain.tail.then(fn).catch(() => {}); return chain.tail; }
    const debouncedCommit = debounce((key, value) => queue(() => saveSetting(key, value)), 400);
    function onRowChange(row, value) {
      const key = row.key;
      if (!key) return;
      /* ⚠️ 本轮删除 `ai_provider` 专用分支（原来走 onProviderChange）。
         那个函数是用户实测 bug 的**元凶**：
           「当我对话框内选择了一个模型，我又去设置搞了一个新厂商的apikey保存后
             他会给我直接默认选择模型为刚刚厂商的第一个模型」
         它里面写着 `draft.model_name = provider.models[0]` —— 一切服务商就把模型
         顶成那家的第一个。现在服务商配置改由**档案卡片**管理（后端
         ai.save_profile 只写 ai_provider_profiles，并按"顺序+Key"派生平铺键），
         这条联动路径整个作废。ai_provider 现在是**派生值**，设置页也不再画这一行；
         万一有别处改它，就按普通设置项落盘，绝不做"顺手改模型"的联动。 */
      if (key === 'language') { queue(() => changeLanguage(value)); return; }
      if (key === 'hotkey_search' || key === 'hotkey_ai' || key === 'hotkey_browser') {
        queue(() => changeHotkey(key, value)); return;
      }
      if (key === 'resource_source' || key === 'local_resource_dir') {
        queue(async () => {
          if (await saveSetting(key, value)) {
            /* 原来这里有一句误用的 `setStep('resources')` —— setStep 是启动分步
               工具（会改 bootText / document.title / 写 [boot] step= 日志），不是切页函数，
               放在设置里会把窗口标题改成ToolsGCP · resources。已删（同 toggleFavorite 的处理）。 */
        await loadResources();
            await loadFavorites();
            /* 浏览表的「云端」档读的是本地镜像文件；来源切到云端后镜像可能被后台拉新，
               不重读这张表就会停在旧内容上。表格选择本身仍与设置解耦（两档各读各的文件），
               这里只是让「镜像变了」这件事及时反映出来。 */
            if (browserSource.value === 'cloud') loadBrowserRows().catch(() => {});
            toast(t('resource_source', '资源来源') + '：已更新，正在重新读取资源库', 'info');
            /* 切到云端且后端有 cloud_refresh 接口时，后台检查/拉取一次最新资源库。
               刻意不 await —— 网络慢也不能卡住设置页；状态行自己会显示"正在检查…"→ 版本号。 */
            if (key === 'resource_source' && value === 'cloud') {
              refreshCloudLibrary(true).catch(() => { /* 拉取失败由状态行显示原因 */ });
              /* 切到云端也要一起同步图标（icon.zip 在同一个 Release）*/
              syncCloudIconsQuiet().catch(() => {});
            }
          }
        });
        return;
      }
      if (key === 'search_view') { setView(value); return; }
      queue(async () => {
        if (!await saveSetting(key, value)) return;
        if (row.type === 'switch') {
          toast(row.label + ': ' + (value ? t('switch_on', '已开启') : t('switch_off', '已关闭')), 'info');
        } else if (row.type === 'select') {
          const option = (row.options || []).find((o) => String(o.value) === String(value));
          toast(row.label + ': ' + ((option && option.label) || value), 'success');
        } else if (row.type === 'checkbox') {
          toast(row.label + ': ' + (value ? t('enabled', '已开启') : t('disabled', '已关闭')),
            value ? 'success' : 'info');
        }
        if (key === 'ai_sidebar_mode' && page.value === 'ai' && !value) doGoto('search');
        if (key === 'theme' || key === 'accent_color') nextTick(() => window.dispatchEvent(new Event('resize')));
      });
    }
    function onRowInput(row, value) {
      const numeric = row.type === 'slider';
      draft[row.key] = numeric ? Number(value) : value;
      debouncedCommit(row.key, draft[row.key]);
    }
    /* 滑块 / 数字框接管滚轮：一格 ±1（原版 cards_download.py 明确接管了滚轮，
       因为 Qt 默认滚一格跳 3、数字框则完全不响应）。 */
    function onSliderWheel(row, event) {
      const step = Number(row.step) || 1;
      const min = row.min != null ? Number(row.min) : 0;
      const max = row.max != null ? Number(row.max) : 100;
      const raw = Number(draft[row.key]);
      const base = Number.isFinite(raw) ? raw : min;
      const next = Math.max(min, Math.min(max, base + ((event.deltaY || 0) > 0 ? -step : step)));
      if (next === base) return;
      onRowInput(row, next);
    }
    /* 把用户手输的整数**解析 + 夹到合法区间**。
       ⚠️ 为什么要单独一个函数：老写法 `Math.max(min, Math.min(max, parseInt(v,10) || 默认))`
          有两个毛病：
            ① `parseInt("0")` = 0 是 falsy → `|| 默认` 触发 → 用户输入 0 反而变成默认值；
            ② `parseInt("abc")` = NaN → NaN 参与 Math.min/max 会得到 NaN，落盘就是坏值。
          这里：**解析失败**（NaN / 空）才用默认值；**解析成功**就夹到 [min, max]（0 → min）。
       与后端 settings_manager.py 的类型修正口径一致（先 int()，再夹区间）。 */
    function clampInt(value, min, max, fallback) {
      const parsed = parseInt(value, 10);
      if (!Number.isFinite(parsed)) return fallback;
      return Math.max(min, Math.min(max, parsed));
    }
    function onRowCommit(row, value) {
      let next = value;
      if (row.key === 'download_speed_limit') {
        next = Math.max(1, Math.min(300, parseInt(value, 10) || 100));
      } else if (row.key === 'scroll_inertia_strength') {
        /* 惯性大小：手输时也钉在 1~100，非法输入回落到默认 35（与 constants.py 一致） */
        next = Math.max(1, Math.min(100, parseInt(value, 10) || 35));
      } else if (row.key === 'min_token') next = parseFloat(value) || 0.5;
      else if (row.key === 'max_token') next = parseInt(value, 10) || 4096;
      /* 多线程下载（1~100）与失败重试次数（1~20）手输时也要钉在合法区间。
         ⚠️ 区间与 constants.py / settings_manager.py 一致（100 / 20）。
         ⚠️ 用 clampInt 而不是 `parseInt(v) || 默认值`：后者会把用户输入的 "0"
            当成"没填"（0 是 falsy）→ 跳成默认值 100/5；正确做法是
            "解析失败才用默认值，解析成功就夹到区间"（0 → 夹到下限 1）。 */
      else if (row.key === 'download_threads') {
        next = clampInt(value, 1, 100, 100);
      } else if (row.key === 'download_retry_count') {
        next = clampInt(value, 1, 20, 5);
      }
      draft[row.key] = next;
      if (row.key === 'min_token' || row.key === 'max_token') { saveSetting(row.key, next); return; }
      if (row.type === 'slider') { debouncedCommit(row.key, next); return; }
      onRowChange(row, next);
    }
    /* 语言切换：**直接生效**，不再弹"是否重启"。
       ⚠️ 词条包来自后端 I18nDomain.bundle(language)，后端用的就是 py 版那套
       LanguageManager + .ToolsGCP/modules/languages/*.json（含 当前语言→简体→英文 回退链），
       所以这里只要按新语言重新取一次并 flattenI18n，整个界面（所有 t()/term()）立刻重渲染。
       资源库里的名称/简介是加载时按语言拍平的，所以还要重新拉一次资源列表。 */
    async function changeLanguage(value) {
      if (!await saveSetting('language', value)) return;
      const bundle = await bridge.tryCall('i18n.bundle', value);
      if (bundle && bundle.ok) {
        flattenI18n(bundle);
      } else if (!bridge.ready) {
        needApi('i18n.bundle', '切换语言');
      }
      const active = (bundle && bundle.language) || value;
      const langTag = ({ '简体中文': 'zh-CN', '繁體中文': 'zh-TW', 'English': 'en' })[active];
      try {
        if (langTag) document.documentElement.setAttribute('lang', langTag);
      } catch (error) { /* ignore */ }
      /* 语言切换后统一重设一次外观属性（data-theme / data-fx / data-motion 都走这一个入口） */
      applyAppearance();
      /* 资源库的 name/description/intro 已按旧语言拍平，重取一次 */
      try { await loadResources(); } catch (error) { /* 列表刷新失败不影响语言本身 */ }
      /* 「更多筛选」里类别/标签/系统三组候选的中文名是后端翻好送来的，
         前端 t() 换不掉 ⇒ 跟着新语言重拉（需求：第四轮②）。 */
      try { await loadFilterOptions(); } catch (error) { /* 失败就沿用旧候选，不影响语言切换本身 */ }
      /* 收藏夹列表同理：默认夹显示名是后端按语言算的（favorites.list），
         不重拉就会一直停在切换前那门语言（用户报：界面切了语言、收藏夹那侧不动）。 */
      try { await loadFavorites(); } catch (error) { /* 拉不到不影响语言本身 */ }
      /* 投稿表单的「多语言字段」分段也要跟上界面语言（用户报的 bug：
         在设置里切到 English 后，投稿页的类别/标签（含下拉框内容）还是简体中文）。
         原因：类别/标签按**分段语言**显示（makerCategoryText 用 termIn(makerSegLang)），
         而分段索引以前只在「清空表单」「载入条目」时落到界面语言那一份，
         切语言本身没同步 ⇒ 分段还停在旧语言，于是整块还是旧语言的写法。
         这里跟 clearForm / loadResourceIntoForm 的口径保持一致：
         分段 = 界面语言 ⇒ 切语言后分段、类别/标签输入框、下拉框候选一起换语言。 */
      const segIndex = makerLanguages.indexOf(uiLanguage());
      if (segIndex >= 0 && i18nLangIndex.value !== segIndex) i18nLangIndex.value = segIndex;
      toast(t('language_switched', '界面语言已切换为 {lang}').replace('{lang}', value), 'success');
    }
    /* ⚠️ 本轮删除 onProviderChange()（原实现会在切换服务商时执行
       `draft.model_name = provider.models[0]` + 连写 ai_provider/api_base/model_name）。
       服务商配置现在由**档案卡片**管理：编辑器里换厂商走 aiProfilePickVendor（只改本地草稿），
       点保存才走 ai.save_profile 落盘；聊天读的是"数组里第一条有 Key 的档案"。
       保留这个函数就等于保留一条"改服务商顺手顶掉模型"的暗道 —— 正是用户报的 bug。 */
    function hotkeyError(sequence) {
      const parts = String(sequence || '').split(/[+\-\s]/).filter(Boolean);
      if (!parts.length) return t('hotkey_err_empty', '快捷键至少需要一个修饰键（Ctrl / Alt / Shift / Win），或使用 F1~F24');
      const main = String(parts[parts.length - 1]).toUpperCase();
      if (['CAPS', 'CAPSLOCK', 'NUMLOCK', 'SCROLLLOCK'].indexOf(main) >= 0) {
        return t('hotkey_err_system_key',
          'Caps Lock / Num Lock / Scroll Lock 不能做快捷键的主键（系统占用了这个键），请换一个组合');
      }
      return '';
    }
    /* Caps Lock 可以当**修饰键**录制：用户自己仍可能把浏览器模式快捷键录成含 Caps 的组合
       （默认值已经不是它了 —— 现在是 Ctrl+Shift+O，走普通 RegisterHotKey）。
       键盘事件里 Caps Lock 的特征：event.key === 'CapsLock'，而且它是**切换键**——
       按下即翻转灯，所以 event.getModifierState('CapsLock') 反映的是"翻转后"的状态，
       用它判断"有没有按住"不可靠。录制时只认 event.key === 'CapsLock' 这一种情形。 */
    function isCapsKey(key) {
      return String(key || '') === 'CapsLock';
    }
    /* 进入 / 退出"录制按键"状态。
       需求：点击输入框进入检测；绑定成功自动退出检测；期间点击其它 UI（blur）也退出。 */
    /* Caps Lock 录制状态（见 recordHotkey 的注释）：
       · `capsPending`  = 录制期间收到过 key='CapsLock'（用户敲了 Caps）；
       · `capsLedBefore`= 进入录制时大写灯的状态，退出时还原回去。
       ⚠️ 为什么要还原：Caps Lock 是切换键，用户按下它录制的那一瞬间，
         系统**已经翻了灯**。不还原的话录完快捷键打字全是大写 —— 这属于
         "设置个快捷键把键盘弄坏了"级别的糟糕体验。 */
    let capsPending = false;
    let capsLedBefore = false;
    function readCapsLed(event) {
      /* KeyboardEvent.getModifierState('CapsLock') 是浏览器唯一能读到大写灯状态的办法 */
      try {
        if (event && typeof event.getModifierState === 'function') {
          return !!event.getModifierState('CapsLock');
        }
      } catch (e) { /* 不支持就当不知道 */ }
      return false;
    }
    function startRecord(row, event) {
      recording.value = row.key;
      capsPending = false;
      capsLedBefore = readCapsLed(event);
      const el = (event && event.target) || document.activeElement;
      if (el && el.focus && document.activeElement !== el) el.focus();
    }
    function stopRecording(revert) {
      const key = recording.value;
      if (!key) return;
      if (revert && settings[key] !== undefined) draft[key] = settings[key];
      recording.value = '';
      const el = document.activeElement;
      if (el && el.blur && el.classList && el.classList.contains('hotkey-input')) el.blur();
    }
    function recordHotkey(row, event) {
      event.preventDefault();
      event.stopPropagation();
      if (event.key === 'Escape') { stopRecording(true); return; }
      if (event.key === 'Backspace' || event.key === 'Delete') {
        changeHotkey(row.key, '');
        stopRecording(false);
        return;
      }
      /* ★ Caps Lock 当修饰键录制（用户仍可自行把某条快捷键录成含 Caps 的组合）
         ⚠️ 两个坑：
         ① 它是**切换键**，keydown 那一刻系统就把大写灯翻了 —— 用户录完快捷键
            会发现灯还亮着、之后打字全是大写。所以录制结束后要把灯**还原成录制前
            的状态**（`hotkey.restore_caps_led`，见后端）。
         ② 原生钩子在"Ctrl 按着"时会**吞掉** Caps 的按键（就是为了不误翻灯），
            那种情况下浏览器根本收不到 key='CapsLock' → 用户得**先单独按一下 Caps**
            再按 Ctrl+主键。所以这里不要求 Caps 和主键同时按下，只记"录制期间
            有没有出现过 CapsLock 按键 / 灯有没有被打开"。 */
      if (isCapsKey(event.key)) {
        capsPending = true;
        return;                                   // 还没敲主键 → 保持检测状态
      }
      const mods = [];
      if (event.ctrlKey) mods.push('Ctrl');
      if (event.altKey) mods.push('Alt');
      if (event.shiftKey) mods.push('Shift');
      if (event.metaKey) mods.push('Win');
      /* 用过 Caps 的两种证据：① 直接收到过 key='CapsLock'；
         ② 大写灯的状态和"进入录制时"不一样了（灯被翻过 = 按过 Caps）。 */
      const capsUsed = capsPending || (readCapsLed(event) !== capsLedBefore);
      if (capsUsed && mods.indexOf('Caps') < 0) mods.push('Caps');
      let main = event.key;
      if (['Control', 'Alt', 'Shift', 'Meta'].indexOf(main) >= 0) return;
      if (/^F\d{1,2}$/.test(main)) { /* 功能键原样 */ }
      else if (main.length === 1) main = main.toUpperCase();
      else return;
      if (!mods.length && !/^F\d{1,2}$/.test(main)) {
        toast(t('hotkey_err_need_modifier', '快捷键至少需要一个修饰键（Ctrl / Alt / Shift / Win），或使用 F1~F24'), 'error');
        return;                                   // 没绑成功 → 保持检测状态，让用户再按一次
      }
      const sequence = mods.concat(main).join('+');
      draft[row.key] = sequence;
      stopRecording(false);                       // 绑定成功 → 自动退出检测状态
      if (capsUsed) restoreCapsLed(event);        // 把大写灯还原成录制前的样子
      changeHotkey(row.key, sequence);
    }
    function restoreCapsLed(event) {
      /* 录完把大写灯**还原**：现在灯的状态（readCapsLed）不等于录制前的状态
         （capsLedBefore）就说明确实被翻过一次 → 让后端按一次 VK_CAPITAL 翻回去。
         ⚠️ 只有桌面端能翻（浏览器/WebView2 里没有 setCapsLockState 这种 API），
            后端不在就静默跳过：灯还亮着只是小瑕疵，绝不能因此让绑定失败。 */
      if (readCapsLed(event) === capsLedBefore) return;
      capsPending = false;
      bridge.tryCall('hotkey.set_caps_led', capsLedBefore).catch(() => {});
    }
    async function changeHotkey(key, sequence) {
      /* slot 必须和后端 HOTKEYS 的 name 一致（search / ai / browser）：
         hotStatus(name) 读的就是这个键，写错就永远显示"未生效"。 */
      const slot = key === 'hotkey_search' ? 'search'
        : key === 'hotkey_ai' ? 'ai'
        : key === 'hotkey_browser' ? 'browser' : '';
      const label = slot === 'search' ? t('hotkey_search', '呼出搜索框')
        : slot === 'ai' ? t('hotkey_ai', '呼出 GCP-AI')
        : t('hotkey_browser', '在浏览器中打开');
      const bad = hotkeyError(sequence);
      if (bad && sequence) { draft[key] = settings[key]; toast(bad, 'error'); return; }
      if (!sequence) {
        if (await saveSetting(key, '')) { hotStatusMap[slot] = ''; toast(label + '：' + t('hotkey_status_unset', '未设置'), 'info'); }
        return;
      }
      if (!await saveSetting(key, sequence)) return;
      const result = await bridge.tryCall('hotkey.apply_settings');
      if (!result) {
        hotStatusMap[slot] = '';
        toast(label + ': ' + sequence + '（' + t('hotkey_note_no_api', '注册接口未就绪，重启后生效') + '）', 'info');
        return;
      }
      if (result.ok && result.error) {
        hotStatusMap[slot] = '✕ 未生效（被占用或不可用）';
        toast(result.error, 'error');
      } else {
        hotStatusMap[slot] = '';
        toast(label + ': ' + sequence, 'success');
      }
    }
    async function resetHotkey(row) {
      /* 回退到这条快捷键的**默认值**（必须逐条对应，别把浏览器模式的默认值
         错写成 Ctrl+Alt+G —— 以前只有两条时的三元写法就是这样坑的） */
      const defaults = { hotkey_search: 'Ctrl+Q', hotkey_ai: 'Ctrl+Alt+G',
        /* 本轮需求：浏览器模式默认改成 Ctrl+Shift+O（不再用 Caps 做修饰键）。
           ⚠️ 必须与 pymodels/constants.py 的 DEFAULT_SETTINGS 保持一致，
              否则"恢复默认"和后端默认值会分叉。 */
        hotkey_browser: 'Ctrl+Shift+O' };
      const fallback = defaults[row.key] || '';
      draft[row.key] = fallback;
      await changeHotkey(row.key, fallback);
    }

    /* ---------- API Key（只有 set_api_key / reveal_api_key / api_key_state 三个入口） ---------- */
    /* ⚠️ 需求：点「保存」之后输入框**不能被清空**（旧代码保存成功就 apiKeyDraft.value = ''）。
       清空后输入框变成空白，用户以为"保存的内容丢了/没保存上"。
       现在保存后保留原值；同时用 apiKeySnapshot 记录"上一次已知的已保存值"，
       这样"未保存修改"的判定不会因为输入框里有内容就永远为真。 */
    const apiKeySnapshot = ref('');
    function apiKeyDirty() {
      if (page.value !== 'settings') return false;
      return String(apiKeyDraft.value || '') !== String(apiKeySnapshot.value || '');
    }
    /* ⚠️⚠️ 本轮（用户原话）：「apikey新增加密功能，保存后下次再打开编辑服务商或者
       直接找到相对应配置文件都不直接是apikey保存，而且编辑服务商界面的apikey输入框
       会提示已填写apikey，以进行相对应加密服务…」
       → 输入框里**永远不再回显明文**：小眼睛只负责"把你自己刚敲的新 Key 从圆点变明文"。
       已保存的 Key 走 DPAPI 密文槽（settings_manager.py 的 api_key_enc_<槽位>），
       界面只知道"配没配"（apiKeyConfigured），拿不到也不需要拿明文。
       所以这里**不再**调 ai.reveal_profile_key / settings.reveal_api_key。 */
    function toggleKeyVisible() {
      if (!String(apiKeyDraft.value || '').trim()) return;   // 没有新输入 ⇒ 无内容可显示
      apiKeyVisible.value = !apiKeyVisible.value;
    }
    /* 输入框占位文案：已配置时明确告诉用户"已经有了、是加密存的"，只是不回显 */
    const apiKeyPlaceholder = computed(() => (apiKeyConfigured.value
      ? t('api_key_saved_ph', '已填写（已加密），输入新的 Key 可替换')
      : t('api_key_placeholder', '请输入 API Key')));
    /* 已配置时才显示的一行说明（放在输入框下面） */
    const apiKeySavedHint = computed(() => (apiKeyConfigured.value
      ? t('api_key_saved_hint',
        '已用 Windows DPAPI 加密保存在本机，出于安全不再回显；需要更换时直接输入新的 Key。')
      : ''));
    function normalizeApiBase(base) {
      let value = String(base || '').trim();
      if (value && !/^https?:\/\//i.test(value)) value = 'https://' + value;
      value = value.replace(/\/chat\/completions\/?$/i, '');
      return value.replace(/\/+$/, '');
    }
    async function saveApiKey() {
      const base = normalizeApiBase(draft.api_base);
      if (!/^https?:\/\/[^/]+/i.test(base)) {
        toast(t('ai_api_base_invalid', '接口地址必须以 http:// 或 https:// 开头，且要带上主机名'), 'error');
        return false;
      }
      if (!String(draft.model_name || '').trim()) {
        toast(t('model_name_required', '请先选择或填写模型名称'), 'error');
        return false;
      }
      draft.api_base = base;
      if (await saveSetting('api_base', base) === false) return false;
      if (await saveSetting('model_name', String(draft.model_name).trim()) === false) return false;
      const key = String(apiKeyDraft.value || '').trim();
      /* ⚠️⚠️ 本轮（Key 不再回显之后的新语义）：
         输入框空着**不再等于**"用户要清空" —— 已保存的 Key 从不出现在框里，空框是常态。
         真正的清空走旁边那颗「清空」按钮（clearApiKey）。所以这里：
           · 已配置 + 空框 ⇒ 视为「没改动」，不发请求，原 DPAPI 密文槽原样保留；
           · 未配置 + 空框 ⇒ 明确提示先填 Key（旧版会静默发空串，等于什么都没做
             却弹一句"已清空"，用户以为存上了）。 */
      if (!key) {
        if (apiKeyConfigured.value) {
          apiKeySnapshot.value = '';
          toast(t('api_key_kept', '已保存的 API Key 未改动（已加密存储）'), 'info');
          return true;
        }
        toast(t('api_key_required', '请先填写 API Key'), 'error');
        return false;
      }
      /* ⚠️ Key 按服务商分槽存储：必须带上当前 ai_provider，
         否则切过服务商后会把 Key 存进旧服务商槽，聊天时后端读不到。 */
      const saved = await bridge.tryCall('settings.set_api_key', key,
        String(draft.ai_provider || 'deepseek'));
      if (!saved) return needApi('settings.set_api_key', '保存 API Key'), false;
      if (!saved.ok) { toast(t('save_failed', '保存失败：') + (saved.error || ''), 'error'); return false; }
      /* 状态**立即**以后端返回值为准（saved.configured），不再靠前端自己猜：
         这样清空后 AI 页胶囊/模型下拉与设置页"已配置"标记同一时刻就一致了。 */
      apiKeyConfigured.value = !!saved.configured;
      /* 需求：保存后输入框内容**保留**（不回填明文、不清空），只更新"已保存"快照 */
      apiKeySnapshot.value = key;
      /* ⚠️ Key 是敏感项，后端**不会**广播 settings-changed（见 resources.py 的
         is_secret_key 分支，防串扰），所以前端这里的 'ai_thinking'/... 那条
         事件驱动重载**收不到**（app.js:9439）。必须手动让模型候选重载：
         未填 Key 的服务商整组都不该再出现在模型切换 UI 里（需求原话）。 */
      loadAiModelChoices();
      /* 走到这里 key 一定非空（空值在上面两条分支里就返回了），所以只有"已保存"一种结果 */
      toast(t('api_key_saved', '模型名称与 API Key 已保存'), 'success');
      return true;
    }
    async function clearApiKey() {
      const result = await bridge.tryCall('settings.set_api_key', '',
        String(draft.ai_provider || 'deepseek'));
      if (!result) return needApi('settings.set_api_key', '清空 API Key');
      if (result.ok) {
        apiKeyDraft.value = '';
        apiKeySnapshot.value = '';
        apiKeyConfigured.value = false;
        /* 同 saveApiKey：清空后要让模型候选立刻重载（该服务商整组模型应消失） */
        loadAiModelChoices();
        toast(t('api_key_cleared', 'API Key 已清空'), 'info');
      } else toast(result.error || t('clear_failed', '清空失败'), 'error');
    }
    /* 切换服务商后把**该服务商**的 Key 拉回输入框；没有就清空并提示去填。
       ⚠️ 为什么必须做：Key 按服务商分槽存储，若切换后仍沿用上一个服务商的 Key，
          发请求就是 401「API Key 无效」（后端还会在错误里附上 Key 尾号帮你核对）。 */
    async function loadApiKeyForProvider(provider) {
      const pid = String(provider || 'deepseek');
      const state = await bridge.tryCall('settings.api_key_state', pid);
      /* ⚠️ 只读"配没配"，**不取明文**（见 toggleKeyVisible 上方那段说明：界面永不回显）。 */
      apiKeyConfigured.value = !!(state && state.ok && state.configured);
      apiKeyDraft.value = '';
      apiKeySnapshot.value = '';
      /* ⚠️ 本轮需求（用户原话）：「设置中切换服务商弹出未填写apikey提示不要了」。
         切服务商时这家没存 Key 是**常态**（用户就是在挨个试服务商），
         每次切都弹一条 info toast 只是噪音；输入框空着 + 「已配置」标记灭
         已经足够表达状态。所以这里**静默**返回。
         ⚠️ 别把别的提示一起删掉：点发送时没 Key 的引导（aiSend 的 no_key 分支）、
            清空 Key 的确认 toast 都照常保留。 */
    }
    /* ==========================================================================
     * · 服务商配置档案（本轮设置页重构的前端状态层）
     * ========================================================================
     * 需求原话见 index.html 里 `row.type === 'provider-profiles'` 那一段的注释。
     * 数据**全部来自后端** `ai.profiles()`（单一事实源 = settings.ai_provider_profiles
     * 有序数组；数组顺序即优先级，第 0 条自动作为"当前使用"）。
     *
     * 前端只做三件事：
     *   ① 展示后端给的列表（长条卡片）；
     *   ② 编辑时在本地维护一份 draft（不点保存不落盘）；
     *   ③ 保存/删除/测试都调后端接口，拿返回值重画列表。
     * ⚠️ 前端的 draft 里**不含 API Key 明文**（Key 走后端 DPAPI 分槽，
     *    输入框用的是既有的 apiKeyDraft + settings.set_api_key 那条老通道）。
     * ========================================================================== */
    const aiProfiles = ref([]);          // 后端返回的档案列表（含派生字段）
    const aiProfilesActive = ref('');    // 当前真正生效的服务商 id
    const aiProfileEditing = ref(null);  // 正在编辑的档案 draft（null = 不在编辑）
    /* ⚠️ 本轮：卡片高亮"当前生效那条"必须用 **id**，不能用 provider ——
       同厂商两条档案 provider 相同，用 provider 比会把两条一起点亮（用户要的正是独立）。
       后端 profiles() 现在返回 active_id；拿不到时退回 provider 比对（旧后端兼容）。 */
    const aiProfilesActiveId = ref('');
    /* ⚠️⚠️ 本轮修复用户报的「列表里有 ≥2 条时，点 A 的测试连接、再点 B 的，
       A 还在测却被提前解禁」：
       旧实现是**一个 ref 存一个值**（aiProfTesting = id 或 'draft'），
       谁的 finally 跑完都把整体清空 ⇒ 并发测试时第一个结束的那个
       会把还在等待的那个的 busy 标记一起抹掉（按钮当场恢复可点，
       而它的请求其实还在跑；再点一次就是两次并发请求，结果互相盖）。
       改成**集合**：每条测试登记自己的 token，结束只删自己那一个。 */
    const aiProfTestingSet = ref([]);
    function aiProfTestingAdd(token) {
      if (aiProfTestingSet.value.indexOf(token) < 0) {
        aiProfTestingSet.value = aiProfTestingSet.value.concat([token]);
      }
    }
    function aiProfTestingDrop(token) {
      aiProfTestingSet.value = aiProfTestingSet.value.filter((x) => x !== token);
    }
    /** 模板用：某条（id / 'draft'）当前是不是正在测试 */
    function aiProfBusy(token) {
      return aiProfTestingSet.value.indexOf(String(token || '')) >= 0;
    }
    /* ⚠️ 本轮：弹窗里那个 API Key 输入框**当前绑的是哪条档案**（档案槽 id）。
       Key 是按档案 id 分槽存的（settings_manager._profile_slot），
       而旧代码一律按 provider 读写 → 写进 `api_key_enc_deepseek`、
       读的是 `api_key_enc_<档案id>`，永远读不到 ⇒ "列表里有服务商，
       但模型切换下拉一个都不显示"（用户报的 bug）。
       空串 = 新建还没落盘的档案（没有 id，只能退回厂商槽）。 */
    const apiKeyProfileId = ref('');
    const aiProfileNewModel = ref('');   // 「清单外模型名」输入框
    const aiProviderCatalog = ref([]);   // 厂商清单 + 每家官方模型候选

    /** 厂商下拉选项（"服务商"字段用） */
    const aiProviderOptions = computed(() => (aiProviderCatalog.value || []).map((p) => ({
      value: p.provider,
      label: t('ai_provider_' + p.provider, p.label || p.provider),
    })));

    /** 编辑器里"支持模型"的候选：当前厂商的官方清单 ∪ 已勾选的（手输的也要显示出来） */
    const aiProfileModelChoices = computed(() => {
      const editing = aiProfileEditing.value;
      if (!editing) return [];
      const official = (aiProviderCatalog.value || [])
        .find((p) => p.provider === editing.provider);
      const list = (official && Array.isArray(official.models)) ? official.models.slice() : [];
      for (const m of (editing.models || [])) {
        if (list.indexOf(m) < 0) list.push(m);       // 手输的补在后面
      }
      return list;
    });

    /** 长条卡片上那个"（厂商）"——用厂商全称，灰色字体 */
    function aiProfVendorLabel(prof) {
      const pid = String((prof && prof.provider) || '');
      return prof.provider_label || t('ai_provider_' + pid, pid);
    }
    /** 长条卡片上的「x 个模型」—— 用户明确要求这个是变量、不能写死 */
    function aiProfCountText(prof) {
      const n = Number(prof && prof.model_count) || 0;
      return t('ai_prof_model_count', '{n} 个模型').replace('{n}', n);
    }

    /** 拉厂商清单（"添加服务商"和"支持模型"候选都要它） */
    async function loadAiProviderCatalog() {
      const result = await bridge.tryCall('ai.provider_catalog');
      if (result && result.ok && Array.isArray(result.providers)) {
        aiProviderCatalog.value = result.providers;
        return true;
      }
      /* 后端未就绪：退回前端内置的 AI_PROVIDERS（只用于画下拉，不能当事实源） */
      if (!aiProviderCatalog.value.length) {
        aiProviderCatalog.value = AI_PROVIDERS.map((p) => ({
          provider: p.id, label: p.label, api_base: p.base, models: p.models || [],
        }));
      }
      return false;
    }

    /** 拉档案列表（保存/删除/进入设置页时都调它） */
    async function loadAiProfiles() {
      const result = await bridge.tryCall('ai.profiles');
      if (result && result.ok) {
        aiProfiles.value = Array.isArray(result.profiles) ? result.profiles : [];
        aiProfilesActive.value = String(result.active_provider || '');
        aiProfilesActiveId.value = String(result.active_id || '');
        return true;
      }
      aiProfiles.value = [];
      aiProfilesActive.value = '';
      aiProfilesActiveId.value = '';
      return false;
    }

    /** 厂商 → 默认「模型名称」标签（品牌简称，不是型号名）。
       和后端 profiles.default_label_for() 同一份口径，别在前端另造一张表。 */
    function aiProfBrandLabel(pid) {
      const map = {
        deepseek: 'DeepSeek', openai: 'OpenAI', claude: 'Claude', grok: 'Grok',
        kimi: 'Kimi', qwen: 'Qwen', siliconflow: 'SiliconFlow', custom: '自定义',
      };
      return map[String(pid || '').toLowerCase()] || String(pid || '');
    }

    /** 「添加服务商」的**空白草稿**（现在它就是唯一的初始状态，不再是"后端不可用"的兜底）
       ⚠️ 本轮需求（用户原话）：「设置中GCP-AI中的服务商那里不要有默认的服务商」→
          provider / label 一律**留空**，由用户自己选；
          api_base 也留空（内置厂商由后端按官方值补齐，只有 custom 需要用户填）。 */
    function aiProfileBlankDraft() {
      return {
        provider: '', label: '',
        api_base: '',
        models: [], model: '',
        limit_token: false, min_token: 0.5, max_token: 4096,
      };
    }

    /** 「添加服务商」：打开一个**空白草稿**弹窗
       ⚠️ 本轮两处改动（都是用户原话）：
         ① 「服务商那里不要有默认的服务商」→ 不再向后端要预填了 provider 的草稿，
            打开时厂商下拉是空的（显示"请选择服务商"），选完才带出支持模型清单；
         ② 「这个ui上面不要放接口地址这个」→ 内置厂商不再画地址输入框，
            地址由后端按厂商官方默认值落盘（save_profile 里已有这条兜底）；
            只有「自定义」保留地址输入框（那家没有官方地址可补）。
       ⚠️ 顺带一个好处：不依赖后端也能开弹窗（浏览器模式 / 后端未就绪时不再空转）。 */
    async function aiAddProfile() {
      /* ⚠️ 每次打开"添加服务商"都从**空暂存**开始：上一次弹窗里没保存就关掉的
         各家草稿不能复活到这一次（用户没见过那个状态，比丢失更让人困惑）。
         暂存只活在"本次弹窗开着"的这段时间内，也绝不落盘。 */
      scratchReset();
      await loadAiProviderCatalog();
      const draft = Object.assign(aiProfileBlankDraft(), { _editing: false });
      aiProfileEditing.value = draft;
      aiProfileNewModel.value = '';
      /* Key 输入框清空（新档案不该显示上一家的 Key） */
      apiKeyDraft.value = '';
      apiKeySnapshot.value = '';
      apiKeyVisible.value = false;
      apiKeyProfileId.value = '';
    }

    /** 「编辑」：把已保存的档案灌进弹窗；**这条档案自己的** Key 拉回输入框
       ⚠️ 本轮：Key 必须按 **profile id** 读写（见 aiEditProfile / aiSaveProfile 的注释），
          按 provider 读写是"列表里有服务商但模型下拉全空"的根因。 */
    async function aiEditProfile(prof) {
      if (!prof) return;
      scratchReset();          // 同 aiAddProfile：编辑态也不携带上一次的临时草稿
      await loadAiProviderCatalog();
      aiProfileEditing.value = {
        id: String(prof.id || ''),
        provider: String(prof.provider || ''),
        label: String(prof.label || ''),
        api_base: String(prof.api_base || ''),
        models: Array.isArray(prof.models) ? prof.models.slice() : [],
        model: String(prof.model || ''),
        limit_token: !!prof.limit_token,
        min_token: Number(prof.min_token) || 0.5,
        max_token: Number(prof.max_token) || 4096,
        _editing: true,
      };
      aiProfileNewModel.value = '';
      await loadProfileKey(prof.id, prof.provider);
      /* ⚠️ 编辑已有档案时**不要**用后端草稿的默认 label/地址覆盖用户填过的值 */
    }

    /** 把某条档案的 Key 拉进输入框。
       ⚠️⚠️ 本轮（修"已配服务商却不显示模型"）：优先按 **profile id** 读档案槽；
          id 为空（老数据 / 新建）才退回厂商槽。 */
    async function loadProfileKey(profileId, provider) {
      apiKeyProfileId.value = String(profileId || '');
      const state = await bridge.tryCall('ai.profile_key_state', String(profileId || ''));
      if (state && state.ok) {
        /* ⚠️ 只取"配没配"这一个布尔值：已保存的 Key 是 DPAPI 密文，界面不回显明文，
           输入框留给"输入新 Key 替换"。见 toggleKeyVisible 上方那段说明。 */
        apiKeyConfigured.value = !!state.configured;
        apiKeyDraft.value = '';
        apiKeySnapshot.value = '';
        return;
      }
      /* 后端还没有档案槽接口：退回旧的厂商槽口径（行为不比旧版差） */
      await loadApiKeyForProvider(provider);
    }

    /** 弹窗里换厂商：支持模型清单 / 默认名称跟着换，地址由后端按厂商官方值落盘。
       ⚠️ 本轮（弹窗里删掉了"接口地址"这一项 UI）：不再在前端记 api_base，
          留空即可 —— `ai.save_profile` 会用 `providers.default_api_base(pid)` 补齐。
       ⚠️ 并且**清空与上一家绑定的东西**（用户原话：「接口和支持模型什么的都要是配
          有的需要清空」—— 换厂商后还留着上一家的 Key 草稿是最典型的错配：
          看着填了、保存的却是另一家的槽，聊天必然 401）。
       ⚠️ 只在新建时重置模型名称标签；编辑已有档案时厂商下拉本来就 disabled，
          不会走到这里覆盖用户自己起的名字。 */
    /* ══════════ 添加服务商弹窗：未选厂商时锁定下方 + 切换厂商的**临时**暂存 ══════════
       本轮需求（用户原话）：「GCP-AI的添加服务商弹窗默认为请选择服务商的下拉框，
       那下面所有的包括 API Key 和支持模型 和 token限制输出 都要变为灰色不可点击状态，
       期间切换服务商下面的状态也应该不变 再切回来还是之前的状态
       （**不是永久存储是临时的，不要存储在文件中**）。」

       两件事分开做：
       ① 锁定：`aiProfLocked`（弹窗打开 且 没选中厂商 且 不是"编辑已有档案"）
          → 模板给表单加 is-locked，CSS 置灰 + pointer-events:none，
            并且**所有控件同时带 :disabled**（只靠 CSS 的话键盘 Tab 还能聚焦进去改值，
            那正是"看着灰着其实还能填"的经典假禁用）。
       ② 暂存：`profScratch` —— 一个**只在本次弹窗生命周期内存在**的内存对象，
          按厂商 id 分格存 模型名称标签 / 支持模型 / token 三项 / API Key 草稿。
          ⚠️ 三条红线：
            · 绝不写进 settings / 后端（写了就是"永久存储"，用户明确否决）；
            · Key 草稿也在里面 —— 它本来就是内存态（apiKeyDraft），
              这里只是把"切走再切回不丢"补齐，不新增任何落盘路径；
            · 关闭 / 取消 / 保存 三个出口都清空（aiCancelProfile / aiSaveProfile /
              aiAddProfile / aiEditProfile），否则上一次没保存的草稿会"复活"到
              下一次弹窗里 —— 那是用户没见过的状态，比丢失更糟。 */
    const profScratch = {};
    function scratchReset() {
      Object.keys(profScratch).forEach((k) => { delete profScratch[k]; });
    }
    function scratchStore(pid, editing) {
      if (!pid || !editing) return;
      profScratch[pid] = {
        label: editing.label || '',
        models: (editing.models || []).slice(),
        api_base: editing.api_base || '',
        limit_token: !!editing.limit_token,
        min_token: editing.min_token,
        max_token: editing.max_token,
        key: apiKeyDraft.value || '',
        keyConfigured: !!apiKeyConfigured.value,
      };
    }
    function scratchTake(pid, editing) {
      const saved = profScratch[pid];
      if (!saved || !editing) return false;
      editing.label = saved.label;
      editing.models = saved.models.slice();
      editing.model = editing.models.length ? editing.models[0] : '';
      editing.api_base = saved.api_base;
      editing.limit_token = saved.limit_token;
      editing.min_token = saved.min_token;
      editing.max_token = saved.max_token;
      apiKeyDraft.value = saved.key;
      apiKeyConfigured.value = saved.keyConfigured;
      apiKeySnapshot.value = '';
      apiKeyVisible.value = false;
      return true;
    }
    /* 锁定判定：新建（非编辑）+ 厂商还没选 ⇒ 下方一切不可用 */
    const aiProfLocked = computed(() => {
      const e = aiProfileEditing.value;
      if (!e || e._editing) return false;
      return !String(e.provider || '').trim();
    });

    async function aiProfilePickVendor(pid) {
      const editing = aiProfileEditing.value;
      if (!editing) return;
      const next = String(pid || '');
      const prev = String(editing.provider || '');
      /* ② 先把**当前厂商**的填写暂存起来（含只是切走没保存的），
         再决定新厂商显示什么 —— 顺序反了会把 A 的内容存到 B 的名下。 */
      scratchStore(prev, editing);
      editing.provider = next;
      /* 接口地址：只有「自定义」这一家需要用户自己填（内置厂商交给后端按官方值补齐），
         所以只在 custom 上暂存/恢复。
         ⚠️ 内置厂商这一支**不能无条件清空 api_base**：模板里厂商下拉在"编辑已有档案"时
            是禁用的，但"依赖另一个组件的禁用状态"是脆弱契约 —— 万一以后这里被别处
            调用（或下拉改成可换厂商），无条件清空就会把用户已存档案的地址抹掉。
            编辑态一律不动 api_base。 */
      if (next === 'custom') {
        editing.api_base = (profScratch[next] && profScratch[next].api_base) || editing.api_base || '';
      } else if (!editing._editing) {
        editing.api_base = '';
      }
      /* 命中暂存 = "切回来还是之前的状态"；没命中 = 该厂商第一次选，铺官方初值。
         ⚠️ 暂存命中时**不能**再跑下面那段"重新取官方清单覆盖 models"，
            否则用户刚勾掉的模型会被重新勾回来（= 切回来状态变了）。 */
      if (scratchTake(next, editing)) {
        /* 命中暂存 ⇒ 标签**不重算**：scratchTake 恢复的就是用户上一次给这家填的值
           （哪怕他手动改成"我的 DeepSeek"也原样回来）。
           ⚠️ 这里绝不能再按"新建"去覆盖 label —— 覆盖一次就等于"切回来状态变了"，
              正是本轮要修掉的点。 */
        apiKeyProfileId.value = '';
        return;
      }
      const entry = (aiProviderCatalog.value || [])
        .find((p) => p.provider === next) || {};
      /* 支持模型：重新取官方清单，并把它作为"已勾选"的初始状态 */
      const models = Array.isArray(entry.models) ? entry.models.slice() : [];
      editing.models = models;
      editing.model = models.length ? models[0] : '';
      /* 模型名称标签：没被用户改过时跟着换成新厂商的品牌名 */
      if (!editing._editing) editing.label = aiProfBrandLabel(next);
      /* Key 草稿清空：新建的档案还没有 id，槽自然是空的 */
      apiKeyDraft.value = '';
      apiKeySnapshot.value = '';
      apiKeyVisible.value = false;
      apiKeyProfileId.value = '';
      apiKeyConfigured.value = false;
    }

    /** 勾选/取消某个支持模型 */
    function aiProfileToggleModel(model, checked) {
      const editing = aiProfileEditing.value;
      if (!editing) return;
      const list = Array.isArray(editing.models) ? editing.models.slice() : [];
      const at = list.indexOf(model);
      if (checked && at < 0) list.push(model);
      else if (!checked && at >= 0) list.splice(at, 1);
      editing.models = list;
      /* 当前模型被取消了 → 落到剩下第一个（列表空了就先留空，保存时后端会补） */
      if (list.indexOf(editing.model) < 0) editing.model = list[0] || '';
    }

    /** 手输追加一个清单外的模型名 */
    function aiProfileAddModel() {
      const editing = aiProfileEditing.value;
      const name = String(aiProfileNewModel.value || '').trim();
      if (!editing || !name) return;
      if ((editing.models || []).indexOf(name) < 0) {
        editing.models = (editing.models || []).concat([name]);
      }
      if (!editing.model) editing.model = name;
      aiProfileNewModel.value = '';
    }

    /** 遮罩点击关闭 —— 但**只有关闭目标真的是面板之外**时才关。
       ⚠️ 不能再用 `@click.self`（本轮 bug 的成因，见 index.html 弹窗那段注释）：
          `.btn:disabled{pointer-events:none}`（components.css:14）让"按在
          正被禁用的按钮上"的那一下**穿透**到遮罩，此时 target 恰好就是遮罩本身，
          `.self` 判定成立 → 弹窗被误关（= 用户报的"按功能按钮直接关掉窗口"）。
          改成拿**点击坐标**和面板矩形比：穿透的那一下坐标仍在面板内 → 不关；
          真的点到遮罩空白处 → 坐标在面板外 → 关。几何判断不受 pointer-events 影响。
       ⚠️ 必须走 getBoundingClientRect 而不是 `event.target === 面板`：
          面板里的任何元素冒泡上来的 click，target 都不是遮罩，但坐标都在内部。 */
    function aiBackdropClose(event) {
      const backdrop = event && event.currentTarget;
      if (!backdrop || !backdrop.querySelector) return;
      if (event.button !== 0) return;             // 只认左键（中键/右键别关）
      /* ★ 本轮修复（用户原话：「添加服务商的弹窗口如果按功能按键这个窗口会消失」）：
         用键盘（Enter/Space 等"功能按键"）激活弹窗里的按钮时，浏览器会补发一个
         **合成 click**，它的 clientX/clientY 恒为 0（左上角）—— 0,0 永远落在面板
         矩形之外，几何判定就把它当成"点了遮罩空白处" → 弹窗当场消失。
         Event.detail 是点击次数：鼠标真实点击 ≥1，键盘合成 click = 0。
         ⇒ detail=0（外加坐标恰为 (0,0) 这道保险）一律不认，键盘激活绝不再误关弹窗。 */
      if (event.detail === 0) return;
      if (!event.clientX && !event.clientY) return;
      const panel = backdrop.querySelector('.ai-prof-modal');
      if (!panel) return;
      const rect = panel.getBoundingClientRect();
      const x = Number(event.clientX) || 0, y = Number(event.clientY) || 0;
      const inside = x >= rect.left && x <= rect.right
        && y >= rect.top && y <= rect.bottom;
      if (inside) return;                          // 面板内（含穿透到按钮的那一下）：不关
      aiCancelProfile();
    }

    function aiCancelProfile() {
      scratchReset();          // 本轮新增的临时暂存随弹窗一起作废（本来就不落盘）
      aiProfileEditing.value = null;
      aiProfileNewModel.value = '';
      apiKeyDraft.value = '';
      apiKeySnapshot.value = '';
      apiKeyProfileId.value = '';
    }

    /** 「保存」：先存 Key（若有填），再存档案，最后重画列表 */
    async function aiSaveProfile() {
      const editing = aiProfileEditing.value;
      if (!editing) return false;
      if (!editing.provider) {
        toast(t('ai_prof_need_vendor', '请先选择服务商'), 'error');
        return false;
      }
      if (!(editing.models || []).length) {
        toast(t('ai_prof_need_model', '至少要勾选一个支持模型'), 'error');
        return false;
      }
      if (!editing.model) editing.model = editing.models[0];
      if (!String(editing.label || '').trim()) editing.label = aiProfBrandLabel(editing.provider);
      /* ① 档案本体（支持模型 / token 开关与上下限）。
         ⚠️⚠️ 本轮两处关键改动：
           a) **必须先存档案、再存 Key**。Key 按档案 id 分槽，而新建档案的 id
              是后端 normalize_profile() 现生成的 —— 先存 Key 根本没有 id 可写。
              （旧写法先写厂商槽 `api_key_enc_deepseek`，读的却是档案槽，
                于是"配过 Key 却不显示任何模型"。这就是用户报的 bug。）
              新建时拿不到返回 id（旧后端）才退回厂商槽，保证不比旧版差。
           b) 不再传 `model`：用户删掉了「当前模型」这一项 UI，
              实际调用哪个模型由后端 profiles.normalize_profile() 统一取
              models[0] —— 前后端只留一处决定，避免两边各算各的。
         ⚠️ `id` 只在**编辑已有档案**时带上：后端 save_profile 按 id 原地替换，
            不带 id 就一律追加新档案 —— 这正是"点编辑保存后多出一条新卡片"的根因。 */
      const payload = {
        provider: editing.provider,
        label: editing.label,
        /* 接口地址：界面上只有「自定义」那一格才会出现这个输入框（内置厂商不给填），
           所以这里非 custom 时恒为空串 → 后端用 providers.default_api_base(pid) 补齐。 */
        api_base: String(editing.api_base || '').trim(),
        models: editing.models,
        limit_token: !!editing.limit_token,
        min_token: Number(editing.min_token) || 0,
        max_token: Number(editing.max_token) || 0,
      };
      if (editing._editing && editing.id) payload.id = editing.id;
      const result = await bridge.tryCall('ai.save_profile', payload);
      if (!result) { needApi('ai.save_profile', t('save', '保存')); return false; }
      if (!result.ok) {
        toast(t('save_failed', '保存失败：') + (result.error || ''), 'error');
        return false;
      }
      /* ② Key：只有用户真的填了才写（空 = 不动已存的 Key，避免"保存档案顺手清空 Key"）。
         ⚠️⚠️ 必须**紧跟在档案落盘之后**：新建档案的 id 是后端现生成的，
            没有 `result.saved` 就不知道往哪个档案槽写。 */
      const key = String(apiKeyDraft.value || '').trim();
      const savedId = String(result.saved || editing.id || '');
      if (key) {
        let savedKey = savedId
          ? await bridge.tryCall('ai.set_profile_key', savedId, key) : null;
        if (!savedKey) {
          savedKey = await bridge.tryCall('settings.set_api_key', key, editing.provider);
          if (!savedKey) { needApi('settings.set_api_key', t('save', '保存')); return false; }
        }
        if (!savedKey.ok) {
          toast(t('save_failed', '保存失败：') + (savedKey.error || ''), 'error');
          return false;
        }
        apiKeySnapshot.value = key;
      }
      /* ⚠️⚠️ 本轮修复用户报的「保存后这一条显示未填 Key，点测试连接也无效，
         必须再进一次编辑再保存才正常」—— 是**我自己上一轮埋的回归**：
         列表数据取的是 `result.profiles`，那是 `save_profile` 在 **Key 落盘之前**
         返回的快照（`has_key` 当然是 False）；而"测试连接无效"是同一条路的另一半：
         它读的是列表里那条档案，前端以为它没 Key。
         正确做法：Key 写完之后**重新拉一次 profiles**，让 has_key / key_tail
         以磁盘上的真实状态为准。旧后端没有 ai.set_profile_key 时也要重拉，
         所以这里放在"有没有存 Key"之外，无条件执行。 */
      await loadAiProfiles();
      scratchReset();          // 已落盘 ⇒ 暂存作废（下次弹窗从干净状态开始）
      aiProfileEditing.value = null;
      apiKeyVisible.value = false;
      apiKeyProfileId.value = '';
      /* 模型候选（输入框右下角那个弹层）要跟着重载：新档案改了可用模型 + 刚落盘的 Key */
      loadAiModelChoices();
      toast(t('ai_prof_saved', '服务商配置已保存'), 'success');
      return true;
    }

    /** 「删除」（红色按钮）：二次确认后调后端，再重画列表 */
    async function aiDeleteProfile(prof) {
      if (!prof) return;
      const name = prof.label || prof.provider;
      /* ⚠️⚠️ 本轮修复（用户原话：「垃圾桶点击之后弹窗确认是否删除而不是顶部标签页弹出提示」）：
         旧写法用 `window.confirm()` —— 那是**浏览器/WebView2 的原生对话框**，
         在我们这种无边框自绘标题栏的窗口里由系统画成一个不属于本程序风格的弹窗
         （用户看到的"顶部标签页弹出提示"就是它），既不跟随主题也不走语言包。
         项目本来就有自绘的 confirmDialog（.modal-backdrop + .modal，跟主题、走 i18n、
         danger 态本身就该是红色），必须用它，不要再造第二套确认 UI。 */
      const yes = await confirmDialog(
        t('ai_prof_delete_title', '删除服务商'),
        t('ai_prof_delete_confirm', '确定删除服务商「{name}」的配置吗？它的 API Key 也会一起清除。')
          .replace('{name}', name),
        t('delete', '删除'), true);
      if (!yes) return;
      /* ⚠️ 本轮：必须传 **profile_id**。同厂商两条档案只传 provider 的话，
         后端无法知道要删哪一条（会退化成"删第一条"，删错对象）。
         旧后端不认 id 时它自己按 provider 兜底，行为不比旧版差。 */
      const result = await bridge.tryCall('ai.delete_profile', prof.id || '', prof.provider);
      if (!result) { needApi('ai.delete_profile', t('delete', '删除')); return; }
      if (!result.ok) {
        toast(t('delete_failed', '删除失败：') + (result.error || ''), 'error');
        return;
      }
      aiProfiles.value = Array.isArray(result.profiles) ? result.profiles : [];
      aiProfilesActive.value = String(result.active_provider || '');
      aiProfilesActiveId.value = String(result.active_id || '');
      /* ⚠️⚠️ 本轮需求（用户原话）：「某个配置删除后也要连着把**模型思考状态存储**一并删除」。
         后端已经把 `ai_thinking_level` 里该档案前缀的条目清了并广播 settings-changed，
         但前端本地那份镜像**现在就得同步删**：
           · 不删的话，`aiThinkStoredLevel()` 还会从本地镜像查到**已删档案**的档位，
             而档案 id 一旦在别的档案上出现（重建、或用户正好选了另一条同 id 的旧数据），
             那个幽灵档位就会"复活"；
           · 也防止 settings-changed 因为窗口隐藏/时序问题没回来时两边不一致。
         按 `档案id|` 前缀删，**同厂商其它档案的记忆一条都不碰**
         （正是用户要的"而不是同厂商的就允许相同"）。 */
      const goneId = String((prof && prof.id) || '').trim().toLowerCase();
      if (goneId) {
        const store = (settings.ai_thinking_level
          && typeof settings.ai_thinking_level === 'object') ? settings.ai_thinking_level : {};
        const pruned = {};
        let removedCount = 0;
        Object.keys(store).forEach((k) => {
          if (k.toLowerCase().indexOf(goneId + '|') === 0) { removedCount += 1; return; }
          pruned[k] = store[k];
        });
        if (removedCount) settings.ai_thinking_level = pruned;
      }
      /* 删掉的正好是**正在编辑的那一条** → 退出编辑。
         ⚠️⚠️ 本轮修掉这里的一个真实 bug（同上一轮"两组一起变"同源）：
            旧判据是 `provider === prof.provider` —— **同厂商两条档案**时，
            在 B 的编辑弹窗里删 A，B 的弹窗会被**误关**（厂商名一样就命中）。
            既然档案 id 才是唯一身份，这里就必须比 id。 */
      if (aiProfileEditing.value && String(aiProfileEditing.value.id || '') === goneId) {
        aiCancelProfile();
      }
      loadAiModelChoices();
      toast(t('ai_prof_deleted', '已删除服务商配置'), 'info');
    }

    /** 长条列表上的「测试连接」：用该档案自己的地址/模型/Key 测
       ⚠️ 本轮：必须把 **profile_id** 传给后端。Key 是按档案槽存的，
          后端只按 provider 读厂商槽会读不到 ⇒ "明明配了 Key 却说没配置"。 */
    async function aiTestProfile(prof) {
      if (!prof) return false;
      /* busy 标记按 **档案 id** 登记在集合里（见 aiProfTestingSet 的注释）：
         并发测试互不影响，先结束的那个只会解除自己的置灰。 */
      const token = String(prof.id || prof.provider);
      aiProfTestingAdd(token);
      try {
        const result = await bridge.tryCall('ai.test_connection', prof.provider,
          prof.model || '', prof.api_base || '', '', token);
        return aiReportTestResult(result);
      } finally {
        aiProfTestingDrop(token);
      }
    }

    /** 弹窗里的「测试连接」：用**还没保存的草稿**测（这才是用户要的"先测再存"） */
    async function aiTestProfileDraft() {
      const editing = aiProfileEditing.value;
      if (!editing) return false;
      if (!editing.provider) {
        toast(t('ai_prof_need_vendor', '请先选择服务商'), 'error');
        return false;
      }
      aiProfTestingAdd('draft');
      try {
        const key = String(apiKeyDraft.value || '').trim();
        const result = await bridge.tryCall('ai.test_connection', editing.provider,
          editing.model || '', editing.api_base || '', key,
          (editing._editing && editing.id) ? editing.id : '');
        return aiReportTestResult(result);
      } finally {
        aiProfTestingDrop('draft');
      }
    }

    /** 测试结果统一提示（成功带延迟，失败带原因） */
    function aiReportTestResult(result) {
      if (!result) { needApi('ai.test_connection', t('ai_prof_test', '测试连接')); return false; }
      if (result.ok) {
        const ms = Number(result.latency_ms) || 0;
        toast(t('ai_test_ok_detail', '连接正常（{ms}ms）').replace('{ms}', ms), 'success');
        return true;
      }
      toast(t('ai_test_failed', '连接失败：') + (result.error || ''), 'error');
      return false;
    }

    async function logoutDev() {
      queue(async () => {
        const key = 'debug_info_enabled_' + (draft.dev_mode_admin || 'Galen563');        await saveSetting(key, !!settings[key]);
        await saveSetting('dev_mode_enabled', false);
        await saveSetting('dev_mode_admin', '');
        await saveSetting('dev_mode_verify_time', '');
        await saveSetting('dev_mode_key', '');
        toast(t('dev_logout', '已退出开发者模式'), 'info');
      });
    }

    /* ---------- 设置页里的按钮动作（License / 开发者密钥 / 存储 / 目录） ---------- */
    async function fire(action, row) {
      if (action === 'verify_license') {
        const key = String(draft.license_key || '').trim();
        await saveSetting('license_key', key);            // 原版：点验证先无条件保存
        if (!key) { toast(t('key_empty', '请输入GCP License Key'), 'warning'); return; }
        if (SPECIAL_KEYS.indexOf(key) >= 0) { showKeys('可用的GCP License Keys', VALID_LICENSE_KEYS.map((v) => ({ key: v }))); return; }
        if (VALID_LICENSE_KEYS.indexOf(key) >= 0) toast(t('key_valid', 'GCP License Key验证成功'), 'success');
        else toast(t('key_invalid', 'GCP License Key无效'), 'error');
      } else if (action === 'save_dev_key') {
        const key = String(draft.dev_mode_key || '').trim();
        if (!key) { toast(t('dev_key_empty', '请输入开发者身份令牌'), 'warning'); return; }
        if (SPECIAL_KEYS.indexOf(key) >= 0) {
          showKeys('可用的开发者密钥', Object.keys(DEV_KEYS).map((v) => ({ key: v, admin: DEV_KEYS[v] })));
          return;
        }
        if (DEV_KEYS[key]) {
          const admin = DEV_KEYS[key];
          const now = new Date();
          const pad = (n) => String(n).padStart(2, '0');
          const time = now.getFullYear() + '年' + pad(now.getMonth() + 1) + '月' + pad(now.getDate())
            + '日 ' + pad(now.getHours()) + '时' + pad(now.getMinutes()) + '分' + pad(now.getSeconds()) + '秒';
          await saveSetting('dev_mode_enabled', true);
          await saveSetting('dev_mode_admin', admin);
          await saveSetting('dev_mode_verify_time', time);
          await saveSetting('dev_mode_key', key);
          toast(admin + ' 开发者身份令牌验证成功', 'success');
        } else toast(t('dev_key_invalid', '开发者身份令牌无效'), 'error');
      } else if (action === 'change_storage') {
        /* 原版 cards_storage.py 的「更改」流程，一步不减：
           ① 系统对话框选目录（只选不定）→ ② 校验目标 → ③ **二次确认**（路径单独一行）
           → ④ 后台迁移 + 进度条 + 完成提示 → ⑤ 地址框刷新。
           ⚠️ 这里**不再**降级成"打开文件夹" —— 需求明确：这个按钮是"更改位置"。 */
        const picked = await bridge.tryCall('settings.pick_data_root');
        if (!picked) return needApi('settings.pick_data_root', '更改存储位置');
        if (picked.canceled) return;                        // 用户取消：什么都不做
        if (!picked.ok) {
          toast(t('storage_invalid_target', '无法使用该位置：{reason}')
            .replace('{reason}', picked.error || ''), 'error');
          return;
        }
        const newRoot = String(picked.path || '');
        const yes = await openDialog({
          title: t('storage_confirm_title', '迁移存储位置'),
          danger: true,
          body: t('storage_confirm_body', '是否确认迁移 .ToolsGCP 至'),
          extra: newRoot,                                   // 路径单独一行（可选中复制）
          confirmText: t('storage_confirm_ok', '确认迁移'),
        });
        if (!yes) return;                                   // 取消：弹窗消失，什么都不动
        storageMigrate.active = true;
        storageMigrate.finished = false;
        storageMigrate.ok = false;
        storageMigrate.percent = 0;
        storageMigrate.text = t('storage_preparing', '正在准备…');
        storageMigrate.done = 0;
        storageMigrate.total = 0;
        const started = await bridge.tryCall('settings.migrate_data_root', newRoot);
        if (!started) { storageMigrate.active = false; return needApi('settings.migrate_data_root', '迁移存储位置'); }
        if (!started.ok) {
          storageMigrate.active = false;
          toast(t('storage_failed', '迁移失败') + '：' + (started.error || ''), 'error');
          return;
        }
        startStoragePoll();
      } else if (action === 'choose_resource_dir') {
        /* ⚠️ 复核发现：**后端从来没有 settings.pick_dir 这个接口**。
           SettingsDomain（desktop/api/resources.py）只有
             get / set / set_api_key / api_key_state / reveal_api_key / paths /
             data_root_info / pick_data_root / migrate_data_root / data_root_progress / reset_data_root
           —— 没有任何 pick_dir。所以旧代码 bridge.tryCall('settings.pick_dir')
           **永远返回 null**，点选择文件夹只会弹一句"接口未就绪"，什么都不会发生。
           真正存在的通用接口是 ShellDomain.pick_folder(title, initial)
           （desktop/api/__init__.py），返回 {ok, path, canceled}，正是这里要的。
           ⚠️ 以后新增选文件夹类动作一律用 shell.pick_folder，不要再写 settings.pick_dir。 */
        const result = await bridge.tryCall('shell.pick_folder',
          t('choose_dir', '选择文件夹'),
          String(draft.local_resource_dir || info.configDir || ''));
        if (!result) return needApi('shell.pick_folder', '选择文件夹');
        if (result.ok === false) {
          toast(t('set_choose_dir_failed', '选择文件夹失败：{err}')
            .replace('{err}', result.error || ''), 'error');
          return;
        }
        if (result.canceled) return;                 // 用户取消：什么都不做
        if (result.path) {
          draft.local_resource_dir = result.path;
          if (await saveSetting('local_resource_dir', result.path)) {
            toast(t('choose_dir', '选择文件夹') + '：' + result.path, 'success');
            await loadResources(); await loadFavorites();
          }
        }
      } else if (action === 'choose_download_dir') {
        /* 选下载保存位置。用 downloader 域的 choose_dir —— 它比通用弹框更贴切：
           默认打开的初始位置就是**当前生效的下载目录**（用户设过的值），
           而不是配置目录。
           ⚠️ 降级路径必须是 shell.pick_folder（真实存在），不是 settings.pick_dir
              （后端从来没有这个接口 → tryCall 永远 null → 老后端也用不了）。 */
        let result = await bridge.tryCall('downloader.choose_dir');
        if (!result) {
          result = await bridge.tryCall('shell.pick_folder',
            t('choose_dir', '选择文件夹'), String(draft.download_save_dir || ''));
        }
        if (!result) return needApi('downloader.choose_dir', t('set_download_save_dir', '下载保存位置'));
        /* ⚠️ 顺序很重要：**先判失败、再判取消**。
           downloader.choose_dir 失败时返回 {ok:false, error:'BAD_RESPONSE', canceled:true}，
           如果先看 canceled 就会把真错误吞掉（用户看不到任何提示）。 */
        if (result.ok === false) {
          toast(t('set_download_dir_failed', '选择下载目录失败：{err}')
            .replace('{err}', result.error || ''), 'error');
          return;
        }
        /* ⚠️ 用户取消时后端会回传**初始目录**（ok=true, canceled=true, path=初始路径）——
           这里必须先 return，否则会把"取消"当成"用户选中了那个目录"而误存。
           （shell.pick_folder 取消时 path 为空串，同样靠 canceled 兜住。） */
        if (result.canceled) return;
        if (result.path) {
          if (await saveSetting('download_save_dir', result.path)) {
            toast(t('set_download_save_dir', '下载保存位置') + '：' + result.path, 'success');
          }
        }
      } else if (action === 'open_data_dir') { await openPath(info.dataDir); }
      else if (action === 'open_program_dir') { await openPath(info.configDir); }
    }
    function showKeys(title, rows) {
      rows.forEach((r) => copyText(r.key));               // 原版：复制后不再弹提示
      openDialog({ title, notes: rows.map((r) => r.key + (r.admin ? '  (' + r.admin + ')' : '')).join('\n'),
        extra: t('copied_no_more_tip', '复制后不再弹提示'), buttons: [t('back', '返回')], wide: true, cancelable: false });
    }

    /* ---------- 检查更新（真调 GitHub Releases；有镜像就走镜像） ----------
       需求（用户思路）：下载到 temp\ToolsGCP\update，下载完成后弹窗问
       是否立即重启更新，可以选稍后或立即重启并更新。
       后端契约（desktop/api/update.py）：
         update.download(url, filename, expected_size) → {ok, started, path}
           然后 push_event：update.progress {received,total,percent} /
                            update.done {ok,path,size,filename} / update.error {error}
         update.install_and_restart() → {ok, restarting} / {ok:false,error}
         update.open_folder() → {ok}
       前端只负责展示与确认，下载/替换全部在 Python 侧做。 */
    const updateState = reactive({
      downloading: false, percent: 0, received: 0, total: 0,
      path: '', filename: '', error: '',
    });
    function humanSize(bytes) {
      const n = Number(bytes) || 0;
      if (n >= 1048576) return (Math.round(n / 1048576 * 10) / 10) + ' MB';
      if (n >= 1024) return Math.round(n / 1024) + ' KB';
      return n + ' B';
    }
    onEvent('update.progress', (payload) => {
      if (!payload) return;
      updateState.downloading = true;
      updateState.received = Number(payload.received) || 0;
      updateState.total = Number(payload.total) || 0;
      updateState.percent = Math.max(0, Math.min(100, Number(payload.percent) || 0));
    });
    onEvent('update.done', (payload) => {
      if (!payload) return;
      updateState.downloading = false;
      updateState.percent = 100;
      updateState.path = String(payload.path || '');
      updateState.filename = String(payload.filename || 'ToolsGCP.exe');
      /* 右上角精简卡收起：下载已经有结果了，它的使命（"发现新版"）结束，
         继续挂着会和下面的"更新包已下载"弹窗重复。 */
      updateCorner.show = false;
      if (payload.ok === false) {
        updateState.error = String(payload.error || t('download_failed_short', '下载失败'));
        toast(t('update_download_failed', '更新包下载失败：{err}')
          .replace('{err}', updateState.error), 'error');
        return;
      }
      showUpdateReadyDialog(payload);
    });
    onEvent('update.error', (payload) => {
      updateState.downloading = false;
      updateCorner.show = false;               // 同 update.done：有结果就别再挂着精简卡
      updateState.error = String((payload && payload.error) || t('download_failed_short', '下载失败'));
      toast(t('update_download_failed', '更新包下载失败：{err}')
        .replace('{err}', updateState.error), 'error');
    });
    function showUpdateReadyDialog(payload) {
      const p = payload || {};
      const size = humanSize(p.size || updateState.total || updateState.received);
      /* 「稍后」→「取消」（用户：把之前**所有的**更新弹窗的稍后改为取消）。
         正文里那句"选择「稍后」"同步改成「取消」，不然文案和按钮对不上。 */
      const laterLabel = t('update_btn_cancel', '取消');
      const nowLabel = t('restart_and_update', '立即重启并更新');
      openDialog({
        title: t('update_ready_title', '更新包已下载'),
        wide: false,
        body: t('update_ready_body',
          '新版本已经下载到临时目录。现在重启程序就会替换成新版本；选择「取消」则先不重启（更新包会保留在临时目录，下次仍可手动更新）。'),
        rows: [
          { k: t('update_file', '更新文件'), v: p.filename || updateState.filename || 'ToolsGCP.exe' },
          { k: t('update_file_size', '文件大小'), v: size, strong: true },
          { k: t('update_file_path', '保存位置'), v: p.path || updateState.path || '—' },
        ],
        buttons: [laterLabel, nowLabel],
      }).then((value) => {
        /* openDialog 的约定：两个按钮时 resolve 布尔（true = 点的是最后一个按钮） */
        if (value === true) applyUpdate();
      });
    }
    async function applyUpdate() {
      const result = await bridge.tryCall('update.install_and_restart');
      if (!result) {
        needApi('update.install_and_restart', '自动替换更新');
        openUpdateFolder();
        return;
      }
      if (!result.ok) {
        toast(t('update_apply_failed', '无法自动替换更新：{err}')
          .replace('{err}', result.error || t('unknown_error', '未知错误')), 'error');
        openUpdateFolder();                              /* 至少把更新包目录打开，方便手动替换 */
        return;
      }
      toast(t('update_restarting', '正在退出并应用更新，请稍候…'), 'success');
    }
    async function openUpdateFolder() {
      const result = await bridge.tryCall('update.open_folder');
      if (!result || !result.ok) {
        if (updateState.path) toast(t('update_file_path', '更新文件位置') + '：' + updateState.path, 'info');
      }
    }
    async function startUpdateDownload(downloadUrl, asset) {
      if (!downloadUrl) return;
      updateState.downloading = true;
      updateState.percent = 0;
      updateState.received = 0;
      updateState.total = Number(asset && asset.size) || 0;
      updateState.error = '';
      const filename = (asset && asset.name) || 'ToolsGCP.exe';
      const result = await bridge.tryCall('update.download', downloadUrl, filename,
        Number(asset && asset.size) || 0);
      if (result && result.ok) {
        toast(t('update_download_started', '更新包开始下载，下载完成后需重启程序'), 'success');
        return;
      }
      updateState.downloading = false;
      if (result && result.error) {
        toast(t('update_download_failed', '更新包下载失败：{err}').replace('{err}', result.error), 'error');
        return;
      }
      /* 兼容旧桌面端：以前前端喊的是 downloader.start（其实后端从没实现过） */
      const legacy = await bridge.tryCall('downloader.start', downloadUrl, filename);
      if (legacy && legacy.ok) {
        toast(t('update_download_started', '更新包开始下载，下载完成后需重启程序'), 'success');
        return;
      }
      /* 没有任何下载接口 → 打开发布页让用户手动下载，并说明原因 */
      needApi('update.download', '下载更新包');
      openLink(downloadUrl);
    }
    /* ══════════ 更新检查（本轮重构，用户原话拆四条）══════════
       · 「新增一个自动检查更新…开启程序后如果发现新版本从右上角滑动出来精简通知，
          点击查看详情变成弹窗形式；精简态有 取消/立即下载；弹窗提示和主动点
          「检查更新」的弹窗一样，不过点空白处要能关闭」
       · 所以网络与判定逻辑抽成 _fetchNewRelease()，三个入口共用：
           手动检查（设置/关于页按钮）、自动-弹窗模式、自动-右上角提示模式。
       ⚠️ manual=false 时**任何失败路径都静默**（网络不通/渠道没 exe/已是最新
          都不许弹 toast）：开机自动检查弹一串错误提示是打扰。 */
    const UPDATE_REPO = 'Galen563/ToolsGCP';
    async function _fetchNewRelease(manual) {
      const url = 'https://api.github.com/repos/' + UPDATE_REPO
        + '/releases?per_page=20&_=' + Date.now();
      const data = await fetchJson(url);
      if (!Array.isArray(data)) {
        if (manual) toast(t('update_err_network', '网络连接失败，请检查网络后重试'), 'error');
        return null;
      }
      if (!data.length) {
        if (manual) toast(t('update_err_no_release', '作者还没有发布任何版本'), 'error');
        return null;
      }
      const channel = draft.update_channel || settings.update_channel || 'all';
      const pool = channel === 'stable' ? data.filter((r) => !r.prerelease)
        : channel === 'beta' ? data.filter((r) => r.prerelease) : data;
      /* ⚠️⚠️ 只有**带了 ToolsGCP.exe 的版本**才算"可更新的版本"（找 exe 不区分大小写）。 */
      const hasExe = (rel) => (rel.assets || []).some(
        (a) => String(a.name || '').toLowerCase() === 'toolsgcp.exe');
      const usable = pool.filter(hasExe);
      const latest = usable[0];
      if (!latest) {
        if (manual) {
          if (pool.length) {
            toast(t('update_latest', '当前已是最新版本（v{v}）').replace('{v}', info.version), 'success');
          } else {
            toast(t('update_err_no_exe', '所选更新渠道还没有带 ToolsGCP.exe 的版本'), 'info');
          }
        }
        return null;
      }
      const tag = String(latest.tag_name || '').replace(/^v/i, '');
      if (!isNewer(tag, info.version)) {
        if (manual) toast(t('update_latest', '当前已是最新版本（v{v}）').replace('{v}', info.version), 'success');
        return null;
      }
      const asset = (latest.assets || []).find(
        (a) => String(a.name || '').toLowerCase() === 'toolsgcp.exe');
      return {
        latest, tag, asset,
        pageUrl: latest.html_url || 'https://github.com/' + UPDATE_REPO + '/releases',
      };
    }
    /* 完整"发现新版本"弹窗。closable：点遮罩空白能不能关 ——
       ⚠️ 用户点名：「记住点击空白处窗口不会自行关闭的bug」（更新类弹窗必须能点空白关）。
       默认 true；只有历史行为明确要"拦住误关"的场景才传 false。
       fromAuto（本轮新增）：这次弹窗是**自动检查**（弹窗提示模式 / 右上角卡的查看详情）
       引出来的 —— 只有这种情况下点「取消」才记成"跳过该版本"；
       用户在设置里主动点「检查更新」时传 false（那是他自己要查的，不该顺手静音，
       否则会出现"我点检查更新点了个寂寞，下次自动检查再也不提示了"）。 */
    function openUpdateDialog(hit, closable, fromAuto) {
      const latest = hit.latest, asset = hit.asset;
      openDialog({
        title: t('update_available', '发现新版本'), wide: true,
        backdropClose: closable !== false,
        /* ── 版式参考旧 PyQt 版 update_dialog.UpdateAvailableDialog：
              抬头（56×56 logo + 大字版本 + 版本类型徽章）→ 事实表 → 更新说明面板。
           ⚠️ 预发布判定只看 Release 的 prerelease 字段，**不拿版本号猜**。 */
        head: {
          text: String(latest.tag_name || '').trim() || ('v' + hit.tag),
          badge: latest.prerelease ? t('update_badge_prerelease', 'Beta 版')
            : t('update_badge_stable', '正式版'),
          badgeKind: latest.prerelease ? 'prerelease' : 'stable',
        },
        /* 右上角纯图标 = 打开发布页；提示文案用语言包早就有的 update_btn_open_page。 */
        link: { url: hit.pageUrl, tip: t('update_btn_open_page', '打开发布页') },
        /* ⚠️⚠️ 排版（本轮需求：「文件大小和发布日期太挤了…分别放在当前版本和
           最新版本的右侧位置」）：四格栅格 ——
             当前版本 | 最新版本
             文件大小 | 发布日期
           原来五行竖排时"更新文件(exe 名)"和"文件大小"挤在一栏；exe 名这一行
           按用户话移除（抬头已经有版本号大字 + 右上角就能打开发布页）。
           side 属性由模板画成右侧第二格的值。 */
        /* ⚠️⚠️ 本轮两处纠正（用户原话：「更新弹窗中的文件大小和最新版本位置交换，
           并在[新]版本下面新增一个更新文件（这个我上个对话没跟你说要删除）」）：
           ① 上一轮我把"文件大小和发布日期分别放在当前版本和最新版本的右侧"
              实现成了「当前版本|最新版本 / 文件大小|发布日期」（两行同类并排），
              读错了语义 —— 要的是一行一个版本、右边跟着它自己的附属信息：
                当前版本 | 文件大小
                最新版本 | 发布日期
                更新文件（跨右侧整列，文件名长也不挤）
           ② 「更新文件」那一行是**我擅自删掉的**（当时觉得抬头已有版本号、右上角
              又能跳发布页），用户明确说他没要求删 → 恢复。 */
        rows: [
          { k: t('update_current_version', '当前版本'), v: 'v' + info.version,
            side: { k: t('update_size', '文件大小'), v: asset ? (Math.round(asset.size / 1048576 * 10) / 10) + ' MB' : '—' } },
          { k: t('update_latest_version', '最新版本'), v: String(latest.tag_name || hit.tag), strong: true,
            side: { k: t('update_published', '发布日期'), v: String(latest.published_at || '').slice(0, 10) } },
          { k: t('update_asset', '更新文件'), v: asset ? asset.name : '—', wide: true },
        ],
        notes: mdTruncate(latest.body || '', 2000) || t('update_no_notes', '（这个版本没有填写更新说明）'),
        notesMd: true,
        /* 「稍后」→「取消」（用户：把之前所有的更新弹窗的稍后改为取消）；
           两键 → answer() 回布尔，true = 立即下载。 */
        buttons: [t('update_btn_cancel', '取消'), t('download_now', '立即下载')],
      }).then((value) => {
        /* 两键 → answer() 回布尔：true = 「立即下载」，false = 「取消」或点遮罩。
           ⚠️ 点遮罩关闭在语义上**就是取消**（遮罩那条路径调的正是 cancelText，
              而按钮行里"取消"就是它），所以 false 一律按"跳过该版本"处理 ——
              与用户原话「点击取消则此次版本将不再进行提示」一致。 */
        if (value === true) {
          startUpdateDownload(asset && asset.browser_download_url, asset);
        } else if (fromAuto) {
          muteUpdateTag(hit.tag);
        }
      });
    }
    async function checkUpdate() {
      if (checkingUpdate.value) return;
      checkingUpdate.value = true;
      const hit = await _fetchNewRelease(true);
      checkingUpdate.value = false;
      if (hit) openUpdateDialog(hit, true);
    }
    /* ---- 启动后的自动检查（设置 update_auto_check：corner 右上角提示 / dialog 弹窗 / off 关闭）----
       ⚠️ 绝对不能 await、绝对不挡启动：GitHub 不通时这条链路可能要几十秒，
          所以调用方用 setTimeout(0) 甩后台（和云端资源库同一纪律）。 */
    const updateCorner = reactive({
      show: false, version: '', size: '', released: '', prerelease: false,
      downloading: false, asset: null, hit: null, tag: '',
    });
    /* ⚠️⚠️ 本轮需求（用户原话）：「假设设置中的自动检查更新选择在右上角提示，点击取消
       则此次版本将不再进行提示，弹窗提示也同理。」
       → "跳过此版本"。被跳过的 tag 存进设置（`update_muted_tag`）：
         · 必须落盘 —— 只存内存的话下次启动同一个版本又弹出来，等于没记住；
           这和上一轮"服务商弹窗暂存不许落盘"不冲突：那个是**没做完的草稿**，
           这个是**用户明确做出的决定（点了取消）**，性质不同。
         · 只对**自动检查**生效；设置里手动点「检查更新」永远照常弹
           （用户主动查询，结果不给看就是"点了没反应"）。
         · 只按 tag 精确匹配：作者发布了更新的版本（tag 不同）自然会重新提示，
           不需要额外做"解除跳过"的设置项。 */
    function updateMutedTag() {
      return String(settings.update_muted_tag || '').trim();
    }
    function muteUpdateTag(tag) {
      const muted = String(tag || '').trim();
      if (!muted) return;
      settings.update_muted_tag = muted;       // 先更新内存，后续判断立刻一致
      saveSetting('update_muted_tag', muted);  // 再落盘（走后端 settings.set）
    }
    async function autoCheckUpdate() {
      const mode = String(settings.update_auto_check || 'corner');
      if (mode === 'off') return;                 // 需求：「关闭 = 开启程序后不进行自动更新检查」
      const hit = await _fetchNewRelease(false);  // manual=false：任何失败都静默
      if (!hit) return;
      /* 本轮：这个版本用户已经点过「取消」→ 不再打扰。
         放在 mode 分流**之前**：右上角提示与弹窗提示两种模式共用同一道闸门。 */
      if (updateMutedTag() && updateMutedTag() === hit.tag) {
        console.log('[update] 版本 ' + hit.tag + ' 已被用户跳过，本次不再提示');
        return;
      }
      if (mode === 'dialog') { openUpdateDialog(hit, true, true); return; }
      updateCorner.hit = hit;
      updateCorner.tag = hit.tag;
      updateCorner.version = String(hit.latest.tag_name || hit.tag);
      updateCorner.prerelease = !!hit.latest.prerelease;
      updateCorner.size = hit.asset ? (Math.round(hit.asset.size / 1048576 * 10) / 10) + ' MB' : '';
      updateCorner.released = String(hit.latest.published_at || '').slice(0, 10);
      updateCorner.asset = hit.asset;
      updateCorner.downloading = false;
      updateCorner.show = true;
    }
    /* 右上角卡「取消」= 跳过这个版本（用户原话：点击取消则此次版本将不再进行提示） */
    function cornerCancel() {
      muteUpdateTag(updateCorner.tag);
      updateCorner.show = false;
    }
    function cornerDownload() {
      if (!updateCorner.asset || updateCorner.downloading) return;
      updateCorner.downloading = true;
      startUpdateDownload(updateCorner.asset.browser_download_url, updateCorner.asset);
    }
    function cornerDetail() {
      const hit = updateCorner.hit;
      updateCorner.show = false;
      /* 「查看详情」= 用户还想看，**不算取消**、不静音；但从这里进弹窗之后，
         如果他在弹窗里点「取消」，语义与"弹窗提示模式点取消"一致
         → fromAuto 传 true，让弹窗的取消把这个版本记成已跳过。 */
      if (hit) openUpdateDialog(hit, true, true);
    }
    const versionText = computed(() => {
      let text = String(info.version || '');
      if (text && !/^[vV]/.test(text)) text = 'v' + text;
      if (info.channel === 'beta' && text.indexOf('-') < 0) text += ' Beta';
      return text;
    });

    /* ---------- 隐私同意（首次启动） ---------- */
    const privacy = reactive({ open: false });
    async function loadPaths() {
      const result = await bridge.tryCall('settings.paths');
      if (result && result.ok) {
        info.configDir = result.config_dir || info.configDir;
        info.dataDir = result.data_dir || info.dataDir;
        info.resourceFile = result.resource_file || info.resourceFile;
        info.version = result.version || info.version;
      }
    }
    async function loadAppInfo() {
      const result = await bridge.tryCall('app.info');
      if (result && result.ok) {
        info.app = result.app || 'ToolsGCP';
        info.version = result.version || '';
        info.python = result.python || '';
        info.dataDir = result.data_dir || '';
        info.configDir = result.config_dir || '';
        info.language = result.language || '简体中文';
        info.args = Array.isArray(result.args) ? result.args : [];
        // 系统原生标题栏模式：自绘标题栏与缩放热区整条撤掉（原生 caption 提供
        // 真正的最小化/最大化/关闭按钮与拖边缩放）。旧后端没这个字段 → 保持自绘。
        if (result.frameless !== undefined && result.frameless !== null) {
          info.frameless = !!result.frameless;
          try { document.documentElement.classList.toggle('is-native-chrome', !result.frameless); } catch (e) {}
        }
      }
    }
    /* 隐私条款正文已改为**官网外链**（用户协议 / 隐私政策及免责声明都放 pages.dev），
       所以本地不再保存/缓存长文，也不再调后端取词接口（该接口已移除）。
       ⚠️ 本轮重构：boot() 的第一步就是这道闸门 —— 未同意时窗口照常放出、
       协议窗置顶（z280），其余启动资源加载**全部推迟到同意之后由这里续跑**。 */
    function acceptPrivacy() {
      privacy.open = false;
      writeLocal('privacyAgreed', true);
      /* 同意 → 继续被暂停的启动流程（云端资源/AI/公告…；重复调用安全） */
      continueBoot();
      /* 同意记录落盘（原版 PrivacyManager：写 json + 哈希），
         所以下次启动不会再问一次 —— 不再只存前端 localStorage */
      bridge.tryCall('app.accept_privacy', 'V1.0').then((result) => {
        if (!result) {
          toast(t('privacy_saved_local', '已记录同意（本地）：桌面端同意接口未就绪时只存本地'), 'info');
          return;
        }
        if (result.ok === false) {
          toast(t('privacy_save_failed', '同意记录保存失败：') + (result.error || t('unknown_error', '未知错误')), 'warning');
          return;
        }
        toast(t('privacy_agreed_toast', '已记录同意，感谢支持'), 'success');
        /* 同意之后才拉公告 → 才会弹「新公告」 */
        loadNotices(false);
      });
    }
    function rejectPrivacy() {
      toast(t('privacy_rejected', '未同意用户协议，程序将退出'), 'warning');
      bridge.tryCall('shell.quit');
    }

    /* ---------- AI（会话走桌面端 ai 域；历史对话 = 一个个对话页） ----------
       ⚠️ 需求：「历史对话完全搞错逻辑了，学习 py 的 —— 它是**对话页**记录而不是聊天对话条记录，
          一个对话页的所有内容为一条」。
       旧实现把消息数组塞在 localStorage，历史面板列的是**每一条消息**。
       现在后端接的是原版 `core/ai/chat_store.py`：一个会话 = 一个 json 文件，
       历史列表里一条 = 一个对话页（标题 = 第一句话，时间 = 会话更新时间）。 */
    /* ---------- GitHub Releases 下载（弹窗 + 独立下载页） ----------
       后端接口：downloader.releases / resolve_asset / start / cancel / list / retry /
                 open_file / open_folder（见 desktop/api/downloader.py 的契约）。
       事件：`download.progress`（节流推送，含 id/status/received/total/percent/speed/eta）。 */
    const releasesDialog = reactive({
      open: false, loading: false, error: '', repo: '', item: null,
      releases: [], page: 1, perPage: 30, hasMore: false,
    });
    const downloads = reactive({
      open: false, items: [], active: 0, dir: '',
      timer: 0, busy: false, error: '',
    });
    /* 下载红点（替代 的右下角悬浮球）。
       · count = 有多少个**未完成**的下载任务（有红点）；
       · fly   = 正在从点击位置蹦到侧栏的那一小段时间（飞行动画）；
       · x / y  = 飞行起点（点击位置，屏幕坐标）。
       ⚠️ 侧栏收起时红点挂在更多按钮上、展开时挂在下载条目上 ——
          这一步在模板里用 `navOpen` 判断（见 index.html 的 nav-badge 两处）。 */
    const downloadBadge = reactive({ count: 0, fly: false, x: 0, y: 0, tx: 0, ty: 0 });

    function downloadIconOf() { return '#i-download'; }

    function refreshDownloadBall() {
      /* 的悬浮球已删除，这里改成维护**红点计数**。
         计数口径 = 还没完成的任务（downloading / failed / paused）。
         ⚠️ failed / paused 也算 —— 任务还没真正结束，用户还得去下载页处理（重试/继续），
            红点不该消失。
         ⚠️ done 不算 —— 已经下完了。 */
      const pending = downloads.items.filter(
        (it) => it.status === 'downloading' || it.status === 'failed'
          || it.status === 'paused');
      downloadBadge.count = pending.length;
    }

    /* 红点飞行：从**点击位置**蹦到左侧栏「更多」按钮上。
       ⚠️ 为什么要算终点：用户要的是「蹦出来然后跳到左侧栏更多里」——
          光在原地闪一下不算"跳过去"。
          终点 = 侧栏里「更多」那个按钮的中心（data-nav-key="more"）。
       ⚠️ 侧栏收起时「更多」按钮在收起态的位置，展开时在展开态的位置 ——
          每次飞行都重新量，所以始终是当前的位置。
       ⚠️ 用 requestAnimationFrame 分两帧改坐标：先放到起点（CSS 过渡的起点），
          再改到终点 —— 浏览器才会把它当成"位置变化"来补间（Vue 的数据更新是异步的，
          同一帧内改两次浏览器只会看到最终值）。 */
    function flyDownloadBadge(event) {
      const source = event && event.currentTarget;
      const moreItem = document.querySelector('.nav-item[data-nav-key="more"]');
      if (!source || !source.getBoundingClientRect) return;
      const rect = source.getBoundingClientRect();
      downloadBadge.x = rect.left + rect.width / 2;
      downloadBadge.y = rect.top + rect.height / 2;
      downloadBadge.tx = downloadBadge.x;
      downloadBadge.ty = downloadBadge.y;
      if (moreItem && moreItem.getBoundingClientRect) {
        const dest = moreItem.getBoundingClientRect();
        downloadBadge.tx = dest.left + dest.width / 2;
        downloadBadge.ty = dest.top + dest.height / 2;
      }
      downloadBadge.fly = true;
      /* 两帧：第一帧确保起点已生效，第二帧再改终点 → 浏览器补间这段位移 */
      requestAnimationFrame(() => requestAnimationFrame(() => {
        downloadBadge.x = downloadBadge.tx;
        downloadBadge.y = downloadBadge.ty;
      }));
      setTimeout(() => { downloadBadge.fly = false; }, 700);
    }

    /* 墓碑：被用户手动删掉（✕ / 清空）的任务 id。
       成因：
         记录从后端 _items 里删了，但下载线程要 ≤1 秒才发现取消标记，
         这期间它还在推该任务的进度事件 → mergeDownloadItem 找不到 id 就
         **凭空新建一条**（复活）→ 再点删除时后端已经查无此记录 → NOT_FOUND。
       后端已同步加了 _push 幽灵防护（记录不在就不推），这里是前端第二道防线。
       ⚠️ id 是后端自增不复用的，墓碑只增不减（一次会话内量级极小）。 */
    const removedDownloadIds = new Set();

    function mergeDownloadItem(payload) {
      if (!payload || !payload.id) return;
      const id = String(payload.id);
      if (removedDownloadIds.has(id)) return;       // 已删除的任务：任何事件都不许把它复活
      let item = downloads.items.find((it) => it.id === id);
      if (!item) { item = { id }; downloads.items.push(item); }
      /* ⚠️ 进度事件里的 status **不能覆盖**已暂停 / 已取消。
         成因（暂停/继续/取消按钮点击无效）：
           下载线程推进度时把状态写死成 "downloading" 推出来
           （后端 downloader.py 里 `self._push(item, "downloading")`），
           而前端这里是 `Object.assign(item, payload)` —— payload 的 status
           会把本地状态直接盖掉。于是：
             点暂停→ 推 'paused' → 界面变已暂停✅
             → 200ms 后下载线程又推 'downloading' → 界面被盖回下载中❌
             → 1.2s 后轮询又纠正回 'paused' → 界面来回跳，按钮跟着闪
           看起来就像"点了没反应"。
         所以这里加一道**前端防线**：已经是 paused / canceled 的条目，
         收到 downloading 的进度事件时**丢掉它的 status**（其它进度照常更新）。
         ⚠️ 新建的条目 item.status 是 undefined，不在 KEEP 里 → 不受影响。 */
      const KEEP = ['paused', 'canceled'];
      const incoming = Object.assign({}, payload);
      if (KEEP.indexOf(String(item.status || '')) >= 0) {
        /* 进度冻结：
           暂停/取消后那 ≤1 秒里下载线程还会推几条"percent 在涨"的收尾事件
           （100 个分段线程每人手里还有一块没读完）。后端已把过冲压到 ~3MB，
           这里再把**进度数字**就地冻结：状态字段照常合并（取消要能变 canceled），
           但 received/percent/speed/eta 不再更新 —— 暂停瞬间进度条就停住。
           恢复下载（resume）后状态变回 downloading，自然解冻。 */
        delete incoming.received;
        delete incoming.percent;
        delete incoming.speed;
        delete incoming.eta;
        if (String(incoming.status || '') === 'downloading') delete incoming.status;
      }
      Object.assign(item, incoming, { id });
      /* G 项：进度事件的 payload 里**没有** finished_at（后端 _push 只推进度字段），
         所以「完成/取消/失败」那一刻前端收不到时间。
         这里用本地时间兜一个：状态变成终态且没有 finished_at 时，记下当前时刻。
         ⚠️ 列表接口（downloader.list → _snapshot）里是带 finished_at 的，
            轮询到之后会覆盖掉这里的兜底值（后端的真值更准）。 */
      if (!item.finished_at
          && ['done', 'failed', 'canceled'].indexOf(String(incoming.status || '')) >= 0) {
        item.finished_at = Date.now() / 1000;
      }
      refreshDownloadBall();
    }

    async function loadDownloads() {
      const result = await bridge.tryCall('downloader.list');
      if (!result || !result.ok) {
        downloads.error = (result && result.error) || '';
        return false;
      }
      /* 过滤墓碑 id —— 后端刚删的记录可能还残留在 list 快照里
         （删除和轮询竞态），不滤掉就是"删了又回来"的另一条路。 */
      const FROZEN = ['paused', 'canceled'];
      const old = downloads.items;
      downloads.items = (result.items || [])
        .filter((it) => !removedDownloadIds.has(String(it.id)))
        .map((it) => {
          /* ⚠️ 进度冻结的**第二条路**：事件推送那条已经挡了，但轮询
             （每 1.2s 一次 downloader.list）拿的是后端**实时** received/percent ——
             暂停/取消后那 ≤1 秒里下载线程还在收尾（手里最后一块没读完），
             list 返回的数字仍在涨 → 进度条"暂停了还在跑一段"。
             本地已是 paused/canceled 的条目：进度数字保持冻结，
             其它字段（status/error/finished_at/path…）照常取服务端真值。
             恢复下载后状态回到 downloading，下一轮自然解冻。 */
          const prev = old.find((x) => String(x.id) === String(it.id));
          if (prev && FROZEN.indexOf(String(prev.status || '')) >= 0
              && FROZEN.indexOf(String(it.status || '')) >= 0) {
            return Object.assign({}, it, {
              received: prev.received, percent: prev.percent,
              speed: prev.speed, eta: prev.eta,
            });
          }
          return { ...it };
        });
      downloads.active = Number(result.active) || 0;
      downloads.dir = String(result.dir || '');
      refreshDownloadBall();
      return true;
    }

    function startDownloadPoll() {
      if (downloads.timer) return;
      downloads.timer = setInterval(() => {
        /* 只要还有**未完成**的任务就继续轮询（不管用户有没有打开下载页）——
           红点上的数字要实时更新。 */
        if (!downloads.open && !downloadBadge.count) { stopDownloadPoll(); return; }
        loadDownloads();
      }, 1200);
    }
    function stopDownloadPoll() {
      if (downloads.timer) { clearInterval(downloads.timer); downloads.timer = 0; }
    }

    /* 下载页现在是**左侧栏里的一个普通页面**（page === 'download'），
       不是 那个盖住内容的浮层。所以打开/关闭= 切页。
       ⚠️ 用 doGoto 而不是直接改 page —— doGoto 负责关掉详情页、记住滚动位置、
          收起更多浮层等一整套切页动作。 */
    function openDownloads() {
      descendingSeen = true;
      doGoto('download');
      loadDownloads();
      startDownloadPoll();
      refreshDownloadBall();
    }
    function closeDownloads() {
      /* 从下载页离开（切到别的页面）时停掉轮询，红点靠事件推送维持。 */
      stopDownloadPoll();
      refreshDownloadBall();
    }
    let descendingSeen = false;

    /* ---------- 下载页的交互 ----------
       这个取消按钮点击好几次得过好一会才会停指而且我要需要增加一个暂停按钮，
                  对了右键弹出菜单有复制下载链接和重试；对了如果变成取消状态最右侧有个叉叉按钮
                  点击即可删除对应任务条 对了这个任务名称也是变成被划掉而且灰色斜体字；
                  打开文件夹直接就一个文件夹图标就ok，打开程序图标是一个朝右上角的箭头，
                  对了如果下载成功会有在程序名称下面的绿色text"下载成功"再次右键菜单中的这个重试按钮会消失，
                  如果是正在下载则是默认的字体颜色，如果是取消的则为橙黄色；
                  如果有下载任务正在执行关闭程序会弹窗提示有下载任务是否坚持退出；
                  清空已完成改为清空下拉框按钮，点击旁边的下拉框三角会展开清除全部 清除已完成 清除未完成，
                  选择好后点击这个ui组件的按钮弹窗再次确认后删除 */

    /* 暂停 */
    async function pauseDownload(item) {
      if (!item) return;
      const result = await bridge.tryCall('downloader.pause', item.id);
      if (!result) { needApi('downloader.pause', t('download_pause', '暂停')); return; }
      if (!result.ok) { toast(result.error || t('download_pause_failed', '暂停失败'), 'error'); return; }
      /* 乐观更新：不等轮询就变成「已暂停」，按钮立刻换成「继续」。 */
      item.status = 'paused';
      loadDownloads();
    }
    /* 恢复 */
    async function resumeDownload(item) {
      if (!item) return;
      const result = await bridge.tryCall('downloader.resume', item.id);
      if (!result) { needApi('downloader.resume', t('download_resume', '继续')); return; }
      if (!result.ok) { toast(result.error || t('download_resume_failed', '恢复失败'), 'error'); return; }
      /* 乐观更新：立刻回到「下载中」。 */
      item.status = 'downloading';
      loadDownloads();
    }
    /* 删掉一条任务记录（不删文件）
       ⚠️ **先立墓碑 + 本地秒删**，再调后端。
         旧顺序（先 await 后端再删本地）有两个用户报的症状：
           · 点✕后"消失一瞬又回来"—— 下载线程还在推这条的进度，
             mergeDownloadItem 凭空把它新建回来（墓碑挡掉，见 removedDownloadIds）；
           · 重复点击弹 NOT_FOUND 报错 —— 记录本来就不在就是"删除目标已达成"，
             后端已改成幂等 {ok:true, removed:false}；就算对着旧后端
             回 NOT_FOUND，这里也当成功（不弹提示）。 */
    async function removeDownload(item) {
      if (!item) return;
      const id = String(item.id);
      removedDownloadIds.add(id);                       // 先立墓碑：挡复活
      const idx = downloads.items.findIndex((x) => String(x.id) === id);
      if (idx >= 0) downloads.items.splice(idx, 1);     // 本地立刻移除：秒没
      refreshDownloadBall();
      const result = await bridge.tryCall('downloader.remove', item.id);
      if (!result) {
        removedDownloadIds.delete(id);                  // 接口都没有：回滚，别把任务藏丢
        return needApi('downloader.remove', t('download_remove_task', '删除这条任务'));
      }
      if (result.ok === false && String(result.error || '') !== 'NOT_FOUND') {
        toast(result.error || t('download_remove_task', '删除这条任务'), 'error');
        removedDownloadIds.delete(id);                  // 真失败才回滚，让轮询把它拉回来
      }
      loadDownloads();
    }
    /* 任务条右键菜单 */
    const downloadMenu = reactive({ open: false, x: 0, y: 0, item: null });
    function openDownloadMenu(event, item) {
      if (!item) return;
      const x = event && event.clientX ? event.clientX : 0;
      const y = event && event.clientY ? event.clientY : 0;
      const vw = window.innerWidth, vh = window.innerHeight;
      downloadMenu.item = item;
      downloadMenu.x = Math.max(8, Math.min(x, vw - 200));
      downloadMenu.y = Math.max(8, Math.min(y, vh - 100));
      downloadMenu.open = true;
    }
    function closeDownloadMenu() { downloadMenu.open = false; downloadMenu.item = null; }
    /* 复制下载链接 */
    async function copyDownloadUrl() {
      const item = downloadMenu.item;
      closeDownloadMenu();
      if (!item || !item.url) return;
      await copyText(item.url);
    }
    /* 「清空」下拉按钮：当前选中的范围 */
    const clearMenuOpen = ref(false);
    const clearScope = ref('finished');
    const CLEAR_SCOPES = {
      all: { label: 'download_clear_all', fallback: '清除全部' },
      finished: { label: 'download_clear_finished', fallback: '清除已完成' },
      unfinished: { label: 'download_clear_unfinished', fallback: '清除未完成' },
    };
    /* 主按钮上显示的文案：让用户点之前就知道会清哪一类（选择好后点击这个ui组件的按钮弹窗再次确认后删除）。
       ⚠️ 用 download_clear_button（清空/ Clear）而不是 download_clear ——
          语言包里 download_clear 的值是"清除已完成"，语义跟这个按钮对不上。
       ⚠️ 范围词从**已翻译好的** download_clear_* 里剥掉前缀动词得到
          （中文清除已完成→ 已完成；英文 "Clear finished" → finished），
          这样不用为短词新增语言 key，i18n 改动词也能自动跟上；
          剥不掉时（换了别的动词）就整个显示完整标签。 */
    function clearScopeLabel() {
      const meta = CLEAR_SCOPES[clearScope.value] || CLEAR_SCOPES.finished;
      const full = String(t(meta.label, meta.fallback));
      let short = full.replace(/^(清除|清理|Clear)\s*/i, '').trim() || full;
      /* 英文剥完是小写的（"Clear finished" → "finished"），首字母补大写更像标签 */
      if (/^[a-z]/.test(short)) short = short.charAt(0).toUpperCase() + short.slice(1);
      return t('download_clear_button', '清空') + ' · ' + short;
    }
    /* 选中范围 —— **只改选中状态，不执行**。
       选择好后点击这个ui组件的按钮弹窗再次确认后删除
       → 选完还得再点主按钮，才会弹二次确认并真删。 */
    function chooseClearScope(scope) {
      clearScope.value = scope;
      clearMenuOpen.value = false;
    }
    /* 执行清理（**先弹窗二次确认**） */
    async function runClearDownloads() {
      const scope = clearScope.value || 'finished';
      const meta = CLEAR_SCOPES[scope] || CLEAR_SCOPES.finished;
      const count = scope === 'all' ? downloads.items.length
        : scope === 'unfinished'
          ? downloads.items.filter((it) => it.status === 'downloading' || it.status === 'paused').length
          : downloads.items.filter((it) => ['done', 'failed', 'canceled'].indexOf(it.status) >= 0).length;
      if (!count) {
        toast(t('download_nothing_to_clear', '没有需要清理的任务'), 'info');
        return;
      }
      const yes = await openDialog({
        title: t('download_clear_confirm_title', '确认清理'),
        body: t('download_clear_confirm_body', '确定要{action} {n} 个下载任务吗？（只删列表记录，不删文件）')
          .replace('{action}', t(meta.label, meta.fallback))
          .replace('{n}', String(count)),
        danger: true,
        confirmText: t('download_clear_confirm_ok', '确定清理'),
      });
      if (!yes) return;
      /* **先按范围立墓碑 + 本地秒删**，再调后端 ——
         用户报不管是点击哪个清除按钮都不会删除正在执行下载的任务：
         后端删了记录，但正在跑的线程还残着 ≤1 秒的推送窗口，
         旧版前端照单全收 → 任务"复活"，看起来就是什么都没清掉。
         （后端已同步加 _push 幽灵防护，这里是第二道防线。） */
      const hitIds = (scope === 'all' ? downloads.items
        : scope === 'unfinished'
          ? downloads.items.filter((it) => it.status === 'downloading' || it.status === 'paused')
          : downloads.items.filter((it) => ['done', 'failed', 'canceled'].indexOf(it.status) >= 0)
      ).map((it) => String(it.id));
      hitIds.forEach((id) => removedDownloadIds.add(id));
      downloads.items = downloads.items.filter((it) => removedDownloadIds.has(String(it.id)) === false);
      refreshDownloadBall();
      const result = await bridge.tryCall('downloader.clear_finished', scope);
      if (!result) {
        hitIds.forEach((id) => removedDownloadIds.delete(id));   // 接口缺失：回滚
        return needApi('downloader.clear_finished', t('download_clear_button', '清空'));
      }
      if (!result.ok) {
        hitIds.forEach((id) => removedDownloadIds.delete(id));   // 真失败：回滚，让轮询拉回来
        toast(result.error || t('download_clear_failed', '清理失败'), 'error');
        return;
      }
      toast(t('download_cleared', '已清理 {n} 个下载任务').replace('{n}', String(result.removed || 0)), 'success');
      loadDownloads();
    }
    /* 速度文字（放在**进度条右边**）
       把进度条后面的那个总进度给删掉，把下载速度放在那里而不是前面
       ⚠️ 只在下载中显示 —— 暂停时速度是 0，显示出来是误导。 */
    function downloadSpeedText(item) {
      const status = String((item && item.status) || '');
      if (status !== 'downloading') return '';
      const speed = Number(item && item.speed) || 0;
      if (!speed) return '';
      return humanSize(speed) + '/s';
    }
    /* 完成 / 取消 / 失败的时间（显示在文件名后面，悬浮提示下载时间）
       ⚠️ 时间戳来源：后端 item.finished_at（秒级浮点）。
          列表接口（_snapshot）里带这个字段；进度事件里没有 —— 在 mergeDownloadItem
          里用本地时间兜了一个（见那里的注释），轮询到后端真值后会覆盖掉。 */
    function downloadTimeText(item) {
      const status = String((item && item.status) || '');
      /* 只有终态才有"完成/取消/失败的时间"；下载中/暂停没有 */
      if (['done', 'failed', 'canceled'].indexOf(status) < 0) return '';
      const ts = Number(item && item.finished_at) || 0;
      if (!ts) return '';
      const d = new Date(ts * 1000);
      if (isNaN(d.getTime())) return '';
      const pad = (n) => (n < 10 ? '0' + n : String(n));
      return d.getFullYear() + '/' + pad(d.getMonth() + 1) + '/' + pad(d.getDate());
    }

    /* ---------- Releases 弹窗顶部的官方 / 全部下拉框 ----------
       ⚠️ 选择保存在 settings.releases_source（后端常量 constants.py 是唯一事实来源）。 */
    const releasesSource = ref('official');
    const releasesSourceOptions = computed(() => ([
      { value: 'official', label: t('dl_releases_source_official', '官方') },
      { value: 'all', label: t('dl_releases_source_all', '全部') },
    ]));
    function changeReleasesSource(value) {
      const next = String(value || '') === 'all' ? 'all' : 'official';
      if (next === releasesSource.value) return;
      releasesSource.value = next;
      /* 存进配置（下次的默认选择就是它）—— 失败也不阻塞界面。 */
      saveSetting('releases_source', next);
      /* 立刻按新来源重新拉一次列表。 */
      if (releasesDialog.open && releasesDialog.item) {
        reloadReleases();
      }
    }
    /* ---------- Releases 弹窗的重新刷新/加载全部 ----------
       ⚠️ hasMore 的判定之前是这一页返回的条数 >= perPage——
          **筛选之后**条数会变少（比如官方模式把没有产物的过滤掉了），
          于是 hasMore 会误判成 false、加载更多按钮直接消失。
          ⚠️ 正确做法：让**后端**告诉我们"还有没有下一页"（它知道原始条数）。
          后端返回里加了 `raw_count`（筛选前的原始条数）和 `has_more`。
          前端优先用后端给的 has_more；后端没给（旧版本）再退回老的判定。 */
    function updateReleasesHasMore(result) {
      if (result && typeof result.has_more === 'boolean') {
        releasesDialog.hasMore = result.has_more;
        return;
      }
      const raw = Number(result && result.raw_count);
      if (Number.isFinite(raw) && raw > 0) {
        releasesDialog.hasMore = raw >= releasesDialog.perPage;
        return;
      }
      releasesDialog.hasMore = (result && result.releases || []).length >= releasesDialog.perPage;
    }
    /* 加载全部：把剩下的页**一次全拉完**（在加载更多旁边新增加载全部）。
       ⚠️ 逐页请求（GitHub 的 releases API 不支持一次拿完），但循环里不停，
          用户看到的是一条条补上来，最后一次到底。 */
    async function loadAllReleases() {
      if (releasesDialog.loading || !releasesDialog.item) return;
      releasesDialog.loading = true;
      const base = releasesDialog.releases.slice();
      let page = releasesDialog.page;
      let more = true;
      /* ⚠️ 最多连拉 20 页（GitHub 单页最多 100 条 → 2000 个 release，够用了）；
            防止个别仓库无限翻页把界面卡住。 */
      for (let guard = 0; guard < 20 && more; guard += 1) {
        page += 1;
        const result = await bridge.tryCall('downloader.releases',
          releasesDialog.item.github, page, releasesDialog.perPage, releasesSource.value);
        if (!result || !result.ok) break;
        const list = result.releases || [];
        releasesDialog.releases = releasesDialog.releases.concat(list);
        updateReleasesHasMore(result);
        more = releasesDialog.hasMore && list.length > 0;
      }
      releasesDialog.page = page;
      releasesDialog.loading = false;
    }
    /* 按当前来源重新拉 Releases（切下拉框 / 点刷新时用） */
    async function reloadReleases() {
      if (!releasesDialog.item) return;
      const github = releasesDialog.item.github;
      releasesDialog.loading = true;
      releasesDialog.error = '';
      releasesDialog.page = 1;
      const result = await bridge.tryCall('downloader.releases', github, 1,
        releasesDialog.perPage, releasesSource.value);
      releasesDialog.loading = false;
      if (!result) {
        releasesDialog.error = t('releases_missing_api', '桌面端的下载接口还没就绪（downloader.releases）');
        return;
      }
      if (!result.ok) {
        releasesDialog.error = t('releases_fail', '拉取 Releases 失败：') + (result.error || '');
        return;
      }
      releasesDialog.repo = String(result.repo || '');
      releasesDialog.releases = result.releases || [];
      updateReleasesHasMore(result);
    }

    /* Releases 弹窗：点卡片/详情里的「查看 Releases」打开（弹窗比普通 modal 大一点） */
    async function openReleases(item) {
      if (!item) return;
      const url = String(item.github || '').trim();
      releasesDialog.open = true;
      releasesDialog.loading = true;
      releasesDialog.error = '';
      releasesDialog.repo = '';
      releasesDialog.releases = [];
      releasesDialog.page = 1;
      releasesDialog.item = { code: item.code, name: item.name, github: url };
      if (!isHttp(url)) {
        releasesDialog.loading = false;
        releasesDialog.error = t('releases_no_repo', '这条资源没有填写 GitHub 仓库地址');
        return;
      }
      /* 带上官方 / 全部来源（后端也支持不传时用配置里的值） */
      const result = await bridge.tryCall('downloader.releases', url, 1,
        releasesDialog.perPage, releasesSource.value);
      releasesDialog.loading = false;
      if (!result) {
        releasesDialog.error = t('releases_missing_api', '桌面端的下载接口还没就绪（downloader.releases）');
        return;
      }
      if (!result.ok) {
        releasesDialog.error = t('releases_fail', '拉取 Releases 失败：') + (result.error || '');
        return;
      }
      releasesDialog.repo = String(result.repo || '');
      releasesDialog.releases = result.releases || [];
      updateReleasesHasMore(result);
    }
    function closeReleases() { releasesDialog.open = false; }

    async function loadMoreReleases() {
      if (releasesDialog.loading || !releasesDialog.item) return;
      releasesDialog.loading = true;
      releasesDialog.page += 1;
      const result = await bridge.tryCall('downloader.releases',
        releasesDialog.item.github, releasesDialog.page, releasesDialog.perPage,
        releasesSource.value);
      releasesDialog.loading = false;
      if (result && result.ok) {
        releasesDialog.releases = releasesDialog.releases.concat(result.releases || []);
        updateReleasesHasMore(result);
      } else {
        releasesDialog.page -= 1;
        toast(t('releases_fail', '拉取 Releases 失败：') + ((result && result.error) || ''), 'error');
      }
    }

    /* 点某个资产直接下载（文件名原样带上，方便用户认出） */
    async function downloadAsset(asset, release, event) {
      if (!asset || !asset.download_url) return;
      const result = await bridge.tryCall('downloader.start', asset.download_url,
        asset.name || '', '', Number(asset.size) || 0, releasesDialog.repo || '');
      if (!result) { needApi('downloader.start', t('download', '下载')); return; }
      if (!result.ok) { toast(t('download_fail', '下载失败：') + (result.error || ''), 'error'); return; }
      /* ★ 本轮（用户：「releases 点击一个它会下载，应该有个提示来提示 xxx（完整文件名）
         已经开始下载（三语言做好）」）：
         旧提示是「已开始下载：<文件名>（大小）」，前缀压在名字前面、名字还可能被
         右缘截断，看起来不像"某个文件开始下载了"。现在把它做成**一句话**
         「<完整文件名>」已开始下载 —— 名字原样整串（不省略、不截断），下一行给大小；
         停留 3.5s（比默认 2s 长一点，够看清长文件名）。
         ⚠️ toast 容器宽度 min(340px, 100vw-32px) + .toast-message 的 word-break，
            长文件名会整词换行，不会被裁。 */
      const fullName = String(asset.name || (result && result.name) || '').trim();
      const sizeText = Number(asset.size) > 0 ? humanSize(asset.size) : '';
      toast(t('download_started_named', '「{name}」已开始下载').replace('{name}', fullName || t('download', '文件'))
        + (sizeText ? '\n' + sizeText : ''), 'success', '', { duration: 3500, pre: true });
      /* **不再**直接跳到下载页（用户要的是"红点蹦到侧栏"，用户自己点进去）。
         红点从**点击的那个按钮**位置蹦出来 → 飞到左侧栏更多上。 */
      flyDownloadBadge(event);
      mergeDownloadItem({
        id: result.id, url: asset.download_url, name: asset.name || result.name || '',
        status: 'downloading', received: 0, total: Number(asset.size) || 0,
        percent: 0, speed: 0, eta: null, path: result.path || '', error: '',
        dir: result.dir || '', source: releasesDialog.repo || '',
      });
      startDownloadPoll();
    }

    async function cancelDownload(item) {
      if (!item) return;
      const result = await bridge.tryCall('downloader.cancel', item.id);
      if (!result) { needApi('downloader.cancel', t('cancel', '取消')); return; }
      if (result && result.ok === false) {
        toast(result.error || t('download_cancel_failed', '取消失败'), 'error');
        return;
      }
      /* 乐观更新：不等轮询，立刻把这条改成已取消。
         ⚠️ 这个取消按钮点击好几次得过好一会才会停——
            以前要等下载线程自己发现取消标记才改状态，用户看着还是"下载中"，
            就以为没点生效，连点好几次。现在点一下界面马上变已取消。 */
      item.status = 'canceled'; item.speed = 0; item.eta = null;
      refreshDownloadBall();
      loadDownloads();
    }
    async function retryDownload(item) {
      if (!item) return;
      const result = await bridge.tryCall('downloader.retry', item.id);
      if (!result) { needApi('downloader.retry', t('download_retry', '重试')); return; }
      if (result && result.ok === false) {
        toast(result.error || t('download_retry', '重试') + '失败', 'error');
        return;
      }
      /* 乐观更新：后端复用同一个 id，状态直接回到「下载中」。 */
      item.status = 'downloading';
      item.error = '';
      refreshDownloadBall();
      loadDownloads();
    }
    async function openDownloaded(item) {
      const result = await bridge.tryCall('downloader.open_file', item.id);
      if (!result || !result.ok) {
        toast(t('download_open_failed', '打开文件失败：') + ((result && result.error) || ''), 'error');
      }
    }
    async function openDownloadFolder(item) {
      const result = await bridge.tryCall('downloader.open_folder', item && item.id ? item.id : '');
      if (!result || !result.ok) {
        toast(t('download_open_failed', '打开目录失败：') + ((result && result.error) || ''), 'error');
      }
    }
    async function clearDownloads() {
      /* ⚠️ 现在清空走下拉按钮（runClearDownloads，带范围 + 二次确认）。
         这个函数保留给可能还有的调用点 —— 默认清已完成。 */
      clearScope.value = 'finished';
      await runClearDownloads();
    }
    function downloadStatusText(item) {
      const status = String((item && item.status) || '');
      if (status === 'downloading') {
        const pct = Math.round(Number(item.percent) || 0);
        const eta = Number(item.eta) || 0;
        /* ⚠️ 这里**不显示速度** —— 速度已经在任务名那一行的右侧显示了，
           状态行只留「百分比 · 剩余时间」，免得同一行里出现两遍。 */
        let text = pct + '%';
        if (eta > 0) text += ' · ' + t('download_eta', '剩余 {s}').replace('{s}', fmtDuration(eta));
        return text;
      }
      /* done → 空字符串：成功状态单独用绿色的「下载成功」那一行显示，
         别在这里再显示一遍「已完成」。 */
      if (status === 'done') return '';
      if (status === 'failed') return t('download_failed', '失败') + (item.error ? '：' + item.error : '');
      if (status === 'canceled') return t('download_canceled', '已取消');
      /* 暂停状态 */
      if (status === 'paused') {
        const pct = Math.round(Number(item.percent) || 0);
        return t('download_paused', '已暂停') + ' · ' + pct + '%';
      }
      return status;
    }
    function fmtDuration(seconds) {
      const total = Math.max(0, Math.round(Number(seconds) || 0));
      if (total >= 3600) return Math.floor(total / 3600) + 'h' + Math.floor((total % 3600) / 60) + 'm';
      if (total >= 60) return Math.floor(total / 60) + 'm' + (total % 60) + 's';
      return total + 's';
    }

    const aiOpen = ref(false);
    const aiDraft = ref('');
    /* 两个输入框实例（独立 AI 页 / 悬浮抽屉）是 v-if 二选一挂载的，
       mentionAi() 要按当前模式选对应的 ref 才能把 token 插进可见的那个。 */
    const aiInputPageRef = ref(null);
    const aiInputDrawerRef = ref(null);
    const aiBusy = ref(false);
    /* 润色按钮的忙状态（与发送互斥：润色中不发送、发送中不润色） */
    const aiPolishing = ref(false);
    /* 设置页「测试连接」按钮的忙状态（防止连点发起多个请求） */
    const aiTesting = ref(false);
    const aiMessages = ref([]);
    const aiSessionId = ref('');
    let aiAborted = false;

    /* ---------- 等待提示（「AI正在查看问题...」） ----------
       ⚠️ 这**不是一条消息**：只用一个独立标记驱动模板里那颗灰色气泡，
          既不进 aiMessages（不渲染成气泡、不进复制/翻版本），
          也永远不落盘（后端只认它自己写进 messages 的东西）。
          收到第一段流式正文（或整段回答回来）就关掉。 */
    const aiPending = ref(false);
    /* 「正在生成」占位要**落在那条气泡自己身上**（取代它原本的正文），用这条下标指认。
       -1 = 没有可取代的气泡（普通提问：那时下面还没有 AI 气泡）→ 由列表末尾那一行渲染。
       ≥0 = 重新生成/编辑重发：那颗气泡本体先变成"正在…"，等新内容到了再被接管。
       需求原话：「点击重新生成…应该是原本位置的AI聊天气泡**消失**，用那个正在xxx的代替，
       而不是原本的聊天气泡ui还在」。 */
    const aiPendingAfter = ref(-1);
    /* 处理期间要把**哪条之后的既有内容先藏起来**（-1 = 不藏任何东西）：
       · 重新生成某条 AI → 藏它下面那串（那些属于"旧版本分支"）；
       · 编辑重发某条用户消息 → 藏它下面那串（同上）。
       需求原话：「下面的内容是上一版AI的对话，bug 性的下面所有内容属于所有版了，
       **全都不消失**，存在着；用户的编辑也一样」。
       ⚠️ 这只是**渲染层**先藏起来：后端在落盘时才会真的把旧尾部挪进
         `branch_suffixes[旧版本]` 并 del 掉（见 versions.py）。
         两边必须一致 —— 所以前端在请求结束时（done / 失败收尾）一定要把它清回 -1，
         否则请求失败后旧内容会"藏了不还"。 */
    const aiCutAfter = ref(-1);
    /* 某一行现在要不要渲染：处理期间，被改那条**之后**的既有内容先让位 */
    /* 最后一条 AI 气泡的下标（-1 = 还没有 AI 回复）。
       ⚠️⚠️ 为什么需要它：Agent 执行过程卡片必须**只画一次**。
       上一版卡片的条件只写了 v-if="aiAgentStepsVisible"（一个全局布尔），
       而它挂在 v-for 的**每条 AI 气泡内部** —— 聊了 5 轮就有 5 条 AI 气泡，
       于是界面上出现 5 个一模一样的"已完成 N 步"，用户原话：
         「为什么会有几个相同的agent动作的那个ui」「为什么我的聊天气泡内会有ai的这个操作什么的」。
       正确做法：步骤属于**最后一条 AI 回复**，只在那一条里渲染。 */
    const aiLastAiIndex = computed(() => {
      const list = aiMessages.value || [];
      for (let i = list.length - 1; i >= 0; i -= 1) {
        if (list[i] && list[i].role === 'ai') return i;
      }
      return -1;
    });

    function aiRowShown(index) {
      const cut = aiCutAfter.value;
      return cut < 0 || index <= cut;
    }
    /* 这一行是不是正在"就地重生"（原气泡被"正在…"取代） */
    function aiRegenPlaceholder(index) {
      return aiBusy.value && aiPending.value && aiPendingAfter.value === index;
    }
    /* ==========================================================================
       运行中过程卡片的**落位**（本轮修复用户报的「Agent 确实执行了，但期间
       思考/执行/正文的 UI 一个都没有」）：
         旧写法卡片挂在"最后一条 AI 气泡"里 —— 新一轮提问时最后一条 AI 气泡还是
         **上一轮**的回答（用户消息刚 push，AI 气泡要等第一个 delta 才存在），
         于是执行卡片画在上一条气泡下面、被"重新生成藏尾部/滚动位置/上一条已折叠
         卡片"各种遮挡，用户在当前问题下面看到的就是一片空白。
         现在：运行中的卡片 = **独立一行**，永远挂在消息列表末尾（本轮自己的位置），
         done/停止/出错后由 aiRunCardIndex 交还给那条回答气泡自带的磁盘 steps。
       ========================================================================== */
    const aiRunCardIndex = computed(() => {
      if (!aiBusy.value) return -1;
      // 流式气泡已经存在（新问答挂在末尾；重新生成/编辑重发**就地**在原下标）
      // → 卡片并进那颗气泡（返回它的下标，模板气泡内条件 aiRunCardIndex === i 命中）。
      if (aiStreamingIndex.value >= 0) return aiStreamingIndex.value;
      return -2;   // -2 = 挂独立行（本轮还没有任何气泡）
    });
    const aiLiveSteps = computed(() => aiAgentSteps.value);
    /* 流式逐字要**写进哪一格**（和上面同一个口径，别搞两份真值）：
       -1 = 还没有对应气泡 → 在末尾挂一颗临时气泡承载（新回答）；
       ≥0 = 就地写进那条气泡（重新生成回答1 = 新文字直接出现在回答1 那颗气泡里）。
       不这么做的话，逐字输出会先跑到整段最末尾、等 done 再"跳回"原位置，
       用户看到的正是「气泡在回答3 的空白位置闪一下又消失」。 */
    const aiStreamSlot = ref(-1);
    /* 正在流式输出的那条气泡的下标 + 累计文本（渲染层临时状态，切会话/落盘后一起清掉）。
       ⚠️ 只有下标指向"最后一条 AI 气泡"时才有效：中途切会话/翻版本会让下标漂移，
          所以任何重建 aiMessages 的地方都要 clearStreamBubble()。 */
    const aiStreamingIndex = ref(-1);
    const aiStreamingText = ref('');
    /* 当前这条流的 id：迟到的 delta 只认它，否则会出现
       "切了会话还在往旧气泡里写字"（Lead 特别提醒的那条）。 */
    let aiStreamId = '';
    /* 看门狗时限：后端 non-stream 超时给 90s，这里留 110s —— 只要还在收 delta 就会重新计时，
       只有"彻底没声息"才会触发降级（把 aiBusy 解冻并按磁盘重建气泡）。 */
    const AI_STREAM_WATCHDOG_MS = 110000;

    /* ==========================================================================
     * · 逐字输出：**直通**（本轮按用户要求重写）
     * ========================================================================
     * 用户原话：「出现思考未完成就直接输出回答文本的不过，或者是逐字输出的bug，
     *   我的原意是 ai 输出多快软件这个逐字功能输出就有多快」，并确认「完全跟随到达速度」。
     *
     * 旧实现是一台"打字机"：后端推来的累计全文只当**目标值**，前端用 rAF
     * 按 26~320 字/秒的速度去追差距。那是我在上一轮自作主张加的限速 ——
     * 后果正是用户报的两个现象：
     *   ① 限速让显示**慢于**到达，用户看到"卡住不动然后突然一大截"（追不上时
     *      还有 6 秒兜底直接贴完，观感就是整段突然出现）；
     *   ② 正文被限速、思考没被限速时两者进度不一致 → "思考还没完正文就先出来了"。
     * 现在：**收到什么就贴什么**，一个字节都不等、不排队、不分帧。
     *   后端也已经取消 120ms 节流（ai-backend 侧），所以整条链路的速度
     *   就等于模型自己的输出速度 —— 这才是用户要的"逐字"。
     *
     * 保留的约束（都是用户之前明确要的，别退回）：
     *   · `aiStreamTarget` / `aiStreamThinkTarget` 两个 ref 仍然保留：
     *     渲染层读的是 `aiStreamingText` / `aiStreamingReasoning`，
     *     直通就是把 target 原样赋给它们；留着 target 是为了
     *     ① 看门狗/停止时能拿到"最后一份完整文本"，② 将来要做限速只改一处。
     *   · 滚动跟随只在贴完字之后调 `scrollAiToEnd`（它内部已按 aiStickBottom 判断，
     *     用户往上翻时不会被拽回 —— 上一轮的修复不能因为这次改动丢掉）。
     *   · `cancelAiTyper()` 作为**空壳保留**：多处清理路径（切会话/停止/看门狗）
     *     都在调它，删掉要改一片调用点，收益为零。它现在只需要把两个 ref 归零。
     * ========================================================================== */
    const aiStreamTarget = ref('');       // 后端最新累计正文（真值）
    const aiStreamThinkTarget = ref('');  // 后端最新累计思考（真值）
    const aiStreamingReasoning = ref(''); // 界面上显示的思考（直通 = 和 target 同一个值）
    /* 思考用时：从"第一个思考包"到"第一个正文包"的秒数（DeepSeek 网页版那句"用时 N 秒"） */
    let aiThinkStartedAt = 0;
    let aiThinkSeconds = 0;

    /** 直通：把后端刚推来的累计值原样贴到界面（不限速、不分帧、不排队）
       ⚠️ 正文和思考**必须一起贴**：只贴一个就会重现"思考没完正文先出"的错位观感。
       ⚠️ 只在内容真的变了的时候滚一次，避免空包触发滚动抖动。 */
    function aiApplyStreamText() {
      const before = aiStreamingText.value.length + aiStreamingReasoning.value.length;
      aiStreamingText.value = aiStreamTarget.value;
      aiStreamingReasoning.value = aiStreamThinkTarget.value;
      if (aiStreamingText.value.length + aiStreamingReasoning.value.length !== before) {
        scrollAiToEnd(aiStreamingIndex.value);
      }
    }

    /* 兼容旧调用点的空壳：以前这里是"起一台打字机"，现在是"直接贴"。
       保留函数名是为了不动 cancelAiTyper / startAiTyper 的十几处调用；
       语义变成"把当前已到达的内容立刻贴上去"。 */
    function startAiTyper() { aiApplyStreamText(); }
    function cancelAiTyper() { /* 没有循环要取消了；清理由 clearStreamBubble 负责 */ }

    /* ---------- 思考折叠（DeepSeek 网页版那种"展开/收起 + 状态文字"） ----------
       需求：「把模型思考的内容搞成那种 deepseek 网页版那种展开关上的 ui 和对应 text 表示状态」。
       · 流式期间自动展开、状态写「思考中…」；结束自动收起、状态写「已深度思考（用时 N 秒）」；
       · 用户可以手动点开/折上（aiThinkOpen 按气泡下标记，切会话清空）。 */
    const aiThinkOpen = ref({});            // { [下标或'stream']: true=展开 }
    function aiThinkIsOpen(key) {
      const map = aiThinkOpen.value || {};
      return map[key] !== false;            // 默认展开（用户要求"展开关上的 ui"，默认给展开态）
    }
    /* ⚠️ 本轮（任务 4）：「思考ui展开或关闭也一样（保持位置）」——
       展开/收起会让整块气泡突然变高/变矮，**它下面的内容整段位移**，
       观感就是"点一下思考，聊天记录跳了一下"。
       做法：切换**前**记住 .ai-messages 的 scrollTop，切换后（nextTick + 一帧）再写回去；
       原本贴底就保持贴底（收起时高度变小，scrollTop 会被浏览器夹到最大值，天然贴底）。
       ⚠️ 明确**不持久化**展开状态（用户："下次重启程序进入还是老样子全部展开所以无需存储状态"）：
          aiThinkOpen 就是内存 ref，切会话/重启自然回到默认展开，别往 settings/localStorage 里写。
       ⚠️ 恢复期间要临时屏蔽 scroll 监听（aiWithScrollGuard），否则程序自己写 scrollTop
          会被那条"距底 <= 阈值 = 贴底"的判定当成用户行为，把 aiStickBottom 判错。 */
    function aiThinkToggle(key) {
      const box = aiScrollBox();
      const stick = aiStickBottom.value;
      const keep = box ? box.scrollTop : 0;
      const map = Object.assign({}, aiThinkOpen.value || {});
      map[key] = !aiThinkIsOpen(key);
      aiThinkOpen.value = map;
      if (!box) return;
      const restore = () => {
        const el = aiScrollBox();
        if (!el) return;
        aiWithScrollGuard(() => {
          /* 原本贴底 → 继续贴底（内容变矮时 scrollTop 会被自动夹到最大，正是想要的效果）。
             原本不贴底 → 回到切换前的 scrollTop，视觉锚点不动。 */
          el.scrollTop = stick ? el.scrollHeight : keep;
          if (stick) aiStickBottom.value = true;
        });
      };
      /* 两次：nextTick 后 Vue 已 patch，再一帧后浏览器高度重算稳定 */
      nextTick(() => { restore(); requestAnimationFrame(restore); });
    }
    /** 思考块那行状态文字（收起/展开 + 用时） */
    function aiThinkLabel(meta) {
      if (!meta) return '';
      if (meta.streaming) return t('ai_think_streaming', '思考中…');
      const secs = Number(meta.seconds) || 0;
      const base = secs > 0
        ? t('ai_thought_seconds', '已深度思考（用时 {n} 秒）').replace('{n}', secs)
        : t('ai_thought_done', '已思考');
      return aiThinkIsOpen(meta.key)
        ? t('ai_think_collapse', '{text} · 收起').replace('{text}', base)
        : t('ai_think_expand', '{text} · 展开').replace('{text}', base);
    }
    /** 这条气泡有没有思考可展示（后端只在开了思考时才带 reasoning；老会话没有该字段）
       ⚠️⚠️ 本轮修复（用户原话：「出现思考未完成就直接输出回答文本的不过」）。
       旧写法：正在流式的那颗气泡**无条件** streaming=true → 状态文字永远是「思考中…」，
       于是正文都已经往外吐了、上面还挂着"思考中…"，用户读到的就是
       "思考还没完成就开始回答"。而模型本来就是**先想完才答**：
       第一个正文 delta 到达的那一刻，思考就已经结束了。
       所以这里按"正文有没有开始"来判定思考是否还在进行，
       并在正文出现时立刻把用时（aiThinkSeconds，第一个思考包→第一个正文包）显示出来。 */
    function aiThinkOf(m, index) {
      if (index === aiStreamingIndex.value) {
        const text = aiStreamingReasoning.value;
        if (!text) return null;
        /* ★ 本轮（用户原话：「没有任何东西是同时进行的」）：Agent 模式下正文要等
           所有工具轮跑完才放出来，所以「思考结束」的标志不只是正文字符 ——
           步骤卡片出现也算思考结束。否则思考块会一直挂着「思考中…」，
           而下面步骤已经在跑，看着就是"边想边干"。
           顺序因此恒为：思考中… → 步骤 → 正文。 */
        const answered = String(aiStreamingText.value || '').length > 0
          || (Array.isArray(aiAgentSteps.value) && aiAgentSteps.value.length > 0);
        return { key: 'stream', text, streaming: !answered,
                 seconds: answered ? aiThinkSeconds : 0 };
      }
      const text = String((m && m.reasoning) || '');
      if (!text) return null;
      return { key: 'm' + index, text, streaming: false,
               seconds: Number(m && m.reasoning_seconds) || 0 };
    }

    /* ---------- 气泡里的「可点击蓝链」与 @token 渲染 ----------
       需求：①「@ 内容发送后变成不可点击、无下划线」→ 用户气泡里的 @名称(编码) 必须还是
       蓝色下划线、点了跳详情；② 独有的字面量 **设置<API Key>** 可点、跳 设置 → GCP-AI；
       ③ 链接**只由 AI 显式表达**（@名称(编码) / 裸编号 TG-xxxxx / 设置<API Key>），
          程序**不**拿资源库名字在正文里找子串 —— 见下面 aiBubbleParts 的注释。
       ⚠️ 渲染方式：算出片段数组、模板 v-for 画 <span>，**不用 v-html** ——
          AI 返回的是不可信文本，v-html 等于把 XSS 开门。 */
    const AI_CODE_RE = /TG-\d{4,8}/g;
    /* ⚠️ 本轮（任务 7）：普通 http(s) 链接也要渲染成蓝色下划线可点击。
       字符类里排掉空白/引号/尖括号和成对符号（URL 里极少见），末尾标点单独夹掉。 */
    /* ⚠️⚠️ 本轮修复（用户实测）：后端报错文案里的
       「接口：https://api.openai.com/v1，Key 尾号：****1234」被整段认成链接 ——
       用户看到的是「https://api.openai.com/v1，Key」可点击，点了打开一个坏地址。
       根因：URL 字符类只排除了 ASCII 空白和几个 ASCII 符号，**中文标点和汉字本身
       都是合法 URL 字符**（`，` `。` `、` `）` `Key` 全被吃进去）。
       治法两层，缺一条都会漏：
         ① 字符类里**直接排除 CJK**（汉字 + 中文标点 + 全角符号三个 Unicode 区段），
            URL 一遇到中文就结束 —— 这是主防线；
         ② 尾部标点表补上中文标点（①已经把中文排除掉了，但 ASCII 的 `)` `,` 等
            仍要靠这张表收尾，两边语义保持一致才不会再出现"链接带个尾巴"）。 */
    const AI_URL_RE = /https?:\/\/[^\s<>"'{}|\\^`\[\]\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]+/g;
    /* 尾部标点：因为 ① 已经把 CJK 从 URL 字符里排除了，链接后面**只可能是 ASCII 标点**
       （`)` `.` `,` `"` `'` 之类），这张表只负责把那些收尾收掉；
       中文标点仍然列在进来当保险（万一某条路径没走 ① 的排除类，比如 markdown
       链接的 url 分组是另一个正则抓的）。 */
    const AI_URL_TRAIL = /[,.;:!?)\]}"'`，。；：！？、）（】〔〕《》“”‘’]+$/;
    /* Markdown 链接 [文字](https://…)：AI 很常见这种写法，整段吃掉换成**可点的文字本体**
       （否则正文里会剩一串 "[文字](https://…" 的方括号源码）。 */
    const AI_MD_LINK_RE = /\[([^\]\n]{1,80})\]\((https?:\/\/[^)\s]+)\)/;
    /* ⚠️ token 的**名字里可以有空格**（"@OBS Studio(TG-000024)"、"@Visual Studio Code(TG-…)"）：
       名字段只禁 @ ( ) 和换行，不能禁空格 —— 之前写成 [^\s@()] 会把带空格的应用名整个漏掉，
       用户气泡里就只剩普通文本（正是"@ 发送后不可点击、无下划线"的一种表现）。 */
    /* task-12 需求 6：新增**可选** [选中文本] 后缀（与 rich-input.js MENTION_SOURCE 同步）。
       方括号内容排除换行与右方括号（] 是唯一终止符；[ 允许，截断已保证不嵌套）；
       1–200 覆盖清洗上限 80 + 前后括号；后缀用 (?:…)? —— 不带时与旧正则行为完全一致。 */
    const AI_TOKEN_RE = /@([^@\n()]{1,60})\((TG-\d{4,8})\)(?:\[([^\n\[\]]{1,200})\])?/g;
    /* ⚠️ 本轮：用户原话是「其中"请填写<API Key>"这个是下滑线字体 点击跳转页面到设置中的
       GCP-AI 位置（现在那个是不可点击状态 无下划线 不是蓝色字体的普通字体是不对的
       还有"<>"不是变量而是就是可点击文本的一部分）」。
       上一轮实现的字面量是 `设置<API Key>`，两种都认（数组匹配，取最早出现的那个），
       尖括号是**文本本身**、不是变量占位符。 */
    /* ⚠️ 顺序 = 匹配优先级，**必须长的在前**（否则 "请填写<API Key>" 会被
       短的 "<API Key>" 先吃掉，链接文字就少了一截）。
       裸 `<API Key>` 放最后当**跨语言兜底**：后端固定回复现在按界面语言出文案
       （英文是 "fill in <API Key>"），每种语言都加一条字面量迟早漏，
       而 `<API Key>` 这个带尖括号的串足够独特、不会误伤普通正文
       —— 用户强调的正是「"<>"不是变量而是就是可点击文本的一部分」。 */
    const AI_SETTINGS_TOKENS = [
      '设置<API Key>', '请填写<API Key>', '請填寫<API Key>', '填写<API Key>',
      'fill in <API Key>', 'Fill in <API Key>', '<API Key>',
    ];
    /** 把一段文本切成 [{t}|{mention,code,name}|{link,kind,code}] 片段（纯函数，可离线测） */
    function aiSplitLinks(text, options) {
      const src = String(text == null ? '' : text);
      if (!src) return [];
      const opt = options || {};
      const out = [];
      let rest = src;
      const pushText = (chunk) => { if (chunk) out.push({ t: chunk }); };
      const allowMention = opt.mention !== false;
      const allowSettings = opt.settingsLink !== false;
      // 逐个消费"最早出现的一个可点片段"，其余原样保留
      for (let guard = 0; guard < 400; guard += 1) {
        let best = null;   // {index, length, part}
        const take = (index, length, part) => {
          if (index < 0) return;
          if (!best || index < best.index) best = { index, length, part };
        };
        if (allowMention) {
          AI_TOKEN_RE.lastIndex = 0;
          const mt = AI_TOKEN_RE.exec(rest);
          if (mt) take(mt.index, mt[0].length,
            { mention: true, code: mt[2], name: mt[1], text: mt[0] });
        }
        /* ⚠️ 本轮：编号链接也要能单独关掉（codes:false）。
           toast 提示里如果混进 TG-xxxx（比如后端错误原文带了编码），
           不该被渲染成"点了跳详情"的链接 —— 提示的语气是"去做设置"。 */
        if (opt.codes !== false) {
          AI_CODE_RE.lastIndex = 0;
          const cd = AI_CODE_RE.exec(rest);
          if (cd) take(cd.index, cd[0].length, { link: 'code', text: cd[0], code: cd[0] });
        }
        if (allowSettings) {
          for (const token of AI_SETTINGS_TOKENS) {
            const si = rest.indexOf(token);
            if (si >= 0) take(si, token.length, { link: 'settings', text: token });
          }
        }
        /* ⚠️ 本轮（任务 7）：普通 http(s) 链接 → 蓝色下划线可点击（走 shell.open_url 外链）。
           放在最后登记：同一位置 @token / 编号 / 设置<API Key> 优先（更具体的语法赢）。
           Markdown 链接 [文字](url) **先于**裸 URL 登记：整段吃掉、只显示"文字"，
           否则正文会剩下 "[文字](" 这种方括号源码 + 一段裸 URL 双链接。
           末尾的逗号/括号等标点**不吃进链接**（"看这个 https://x.com/a，很好" 不应把"，"带上）。 */
        if (opt.urls !== false) {
          const md = AI_MD_LINK_RE.exec(rest);
          if (md) {
            take(md.index, md[0].length,
              { link: 'url', text: md[1], url: md[2] });
          }
          AI_URL_RE.lastIndex = 0;
          const ur = AI_URL_RE.exec(rest);
          if (ur) {
            let urlText = ur[0];
            const tp = urlText.match(AI_URL_TRAIL);
            if (tp) urlText = urlText.slice(0, urlText.length - tp[0].length);
            if (urlText && (!md || ur.index !== md.index + md[1].length + 3)) {
              /* 同一位置已是 markdown 链接的内层 URL → 不再重复登记裸链 */
              take(ur.index, urlText.length, { link: 'url', text: urlText, url: urlText });
            }
          }
        }
        if (!best) break;
        pushText(rest.slice(0, best.index));
        out.push(best.part);
        rest = rest.slice(best.index + best.length);
      }
      pushText(rest);
      return out;
    }
    /** 渲染一条气泡：用户与 AI 都只认**显式**写法（@token / 编号 / 设置<API Key>）。
       ⚠️ 本轮去掉了"拿资源库名字在正文里找子串"的模糊匹配 ——
          那会让 AI 说"我选择 deepseek-v4.1-flash 模型"时撞上库名就变成链接、
          一点跳资源库（用户明确说"是不对的"）。链接必须由 AI 自己显式表达。
       ⚠️⚠️ 本轮修复（任务 5）：发送 `/plugin` 之后气泡里那段命令**丢了蓝色**（输入框里
          rich-ai-input 把 /plugin 画成 slash-token，进气泡后是纯文本插值 → 灰色普通字，
          看起来"这条消息没被当成 slash 命令"）。气泡侧补齐同样的识别：
          文本**开头**的白名单命令（后面必须跟空白或结束）单独切成一个 command 片段，
          由 .bubble .ai-slash-cmd 上蓝色；**其它 slash 命令同一条规则**，不再只认 /plugin。
          注意这只加一个 class，气泡底色/对齐仍是普通用户气泡（is-user），
          后端把这条当命令处理（kind:'no_key'/工具循环）也不会改变用户气泡样式。 */
    const AI_BUBBLE_CMD_RE = /^\/([A-Za-z][A-Za-z0-9_-]*)(?=$|[\s\u3000])/;
    function aiBubbleParts(m, index) {
      const text = aiBubbleText(m, index);
      if (!text) return [];
      /* 命令词白名单与输入框同一份（只开 GCP-AI Agent 不算，见 aiCommandWords） */
      const words = (aiCommandWords.value || []).filter((w) => w && w.indexOf('__') !== 0);
      if (words.length) {
        const hit = AI_BUBBLE_CMD_RE.exec(text);
        if (hit && words.indexOf(hit[1].toLowerCase()) >= 0) {
          const head = { cmd: hit[0], text: hit[0] };
          const rest = text.slice(hit[0].length);
          return [head].concat(aiSplitLinks(rest, { mention: true }));
        }
      }
      return aiSplitLinks(text, { mention: true });
    }
    /** 点蓝链：编号 / @token → 跳详情；设置<API Key> → 跳 设置 → GCP-AI；
       http(s) → 走项目既有外链方式（openLink → shell.open_url，pywebview 里由后端交给系统浏览器，
       Ctrl+点击后台打开；绝不用 window.open —— WebView2 里那个会被拦截或开空白窗） */
    function onAiLinkClick(part, event) {
      if (!part) return;
      if (part.link === 'settings') {
        gotoSettingsAi();
        return;
      }
      if (part.link === 'url') {
        /* Ctrl+点击 = 后台打开（和卡片打开外链同一口径，openLink 里判 ctrlKey） */
        openLink(String(part.url || part.text || ''), event || null);
        return;
      }
      const code = String(part.code || '');
      if (!code) return;
      const item = (items.value || []).find((x) => x.code === code);
      if (!item) {
        toast(t('unknown_code_tip', '资源库里没有 {code}').replace('{code}', code), 'info');
        return;
      }
      if (!settings.ai_sidebar_mode) aiOpen.value = false;   // 抽屉先收起，否则详情页被盖住
      if (page.value !== 'search' && page.value !== 'customize') {
        doGoto('search');
        setTimeout(() => openDetail(item), 60);
        return;
      }
      openDetail(item);
    }
    /* 「去填写 API Key」/「设置<API Key>」这类跳转。
       ⚠️ 需求历史：曾经要求"滚到 GCP-AI 第二板块 + 自动展开编辑器 + 聚焦 Key 输入框"。
       ⚠️⚠️ 本轮需求（用户原话）：「点击去设置里填写或者AI回复相关API设置跳转
          直接跳转到设置中的GCP-AI，但是不需要自动创建服务商选中APIKey输入框，
          停留在那个位置即可」→
          · **不再**自动打开服务商弹窗（旧写法一家都没有时会 `aiAddProfile()`
            凭空建一条草稿弹窗，用户没点"添加"就被塞了一个编辑器）；
          · **不再**聚焦/进入 API Key 输入模式；
          · 只做两件事：切到设置页 + 滚到 GCP-AI 板块，停在那里。
       ⚠️ 滚动仍然分两拍：页面过渡 ~230ms 后 `.settings-section` 才挂得上去。 */
    function gotoSettingsAi() {
      if (!settings.ai_sidebar_mode) aiOpen.value = false;
      doGoto('settings');
      // 等页面挂载再定位板块（页面过渡 ~230ms）
      setTimeout(() => {
        try { scrollSection('ai'); } catch (e) { /* 设置页还没挂载：忽略 */ }
        setTimeout(() => {
          try {
            const host = settingsScroll.value;
            const wrap = host && host.querySelector(
              '.settings-section[data-key="ai"] .ai-prof-wrap');
            /* 滚到服务商这一区（"停留在那个位置"= 让用户一眼看到列表和
               「添加服务商」按钮，而不是板块大标题）。失败就算了，
               板块级滚动已经足够定位。 */
            if (wrap) {
              wrap.scrollIntoView({ block: 'center',
                behavior: settings.ui_animation === 'off' ? 'auto' : 'smooth' });
            }
          } catch (e) { /* 后端未就绪 / 还没挂载：跳转本身已生效，不报错 */ }
        }, 140);
      }, 260);
    }

    /* ---------- AI 气泡右键菜单（本轮：只留「复制」） ----------
       需求原话：「右键聊天气泡的全选选项删除保留复制」。
       ⚠️ 同时修「款选文本右键不弹出菜单bug」：以前这里用
          `String(sel.toString || '')().length` 判有没有选区 —— 那是**调用函数本身**
          （toString 是函数，不是它的返回值），永远返回 undefined → 长度判定恒为假。
          现在改成正常调用 sel.toString()。
          另外菜单不再依赖"有没有选区"来决定要不要弹（有选区只影响复制的内容范围）。
       ⚠️⚠️ 本轮（任务 6）：「右键复制也是一样的 在思考那里复制应该也是复制思考中的内容
          而不是文本的内容（注意我说的是**直接未框选状态**点击复制的时候）」。
          所以菜单要记住"右键落在了哪个区"：
            · event.target.closest('.ai-think-body') 命中 → zone='think'
            · 否则（正文区域）→ zone='text'
          aiCtxCopy 再按 zone 决定"没框选时复制什么"。 */
    const aiCtx = reactive({ open: false, x: 0, y: 0, index: -1, selected: false, zone: 'text' });
    /** 当前有没有有效选区（框选了文字）—— 本轮修掉上面那个 toString 写法错误 */
    function aiHasSelection() {
      try {
        const sel = window.getSelection && window.getSelection();
        if (!sel || sel.isCollapsed) return false;
        return String(sel.toString()).trim().length > 0;
      } catch (e) { return false; }
    }
    /** 右键落点区域：'think' = 思考正文；'text' = 气泡正文（含 @token / 蓝链） */
    function aiCtxZoneOf(target) {
      try {
        if (target && target.closest && target.closest('.ai-think-body')) return 'think';
      } catch (e) { /* 非 Element 目标：按正文处理 */ }
      return 'text';
    }
    /** 取某条气泡当前的思考文本（流式中要用渲染层的临时累计值，不是磁盘里的旧值） */
    function aiReasoningOf(index) {
      const i = Number(index);
      if (!Number.isFinite(i) || i < 0) return '';
      if (i === aiStreamingIndex.value) return String(aiStreamingReasoning.value || '');
      return String((aiMessages.value[i] && aiMessages.value[i].reasoning) || '');
    }
    function openAiCtx(event, index) {
      aiCtx.index = Number(index);
      aiCtx.selected = aiHasSelection();
      /* 任务 6：记录右键落在思考区还是正文区（没框选时决定复制哪一份） */
      aiCtx.zone = aiCtxZoneOf(event && event.target);
      const vw = window.innerWidth; const vh = window.innerHeight;
      aiCtx.x = Math.max(8, Math.min(event.clientX || 0, vw - 168));
      aiCtx.y = Math.max(8, Math.min(event.clientY || 0, vh - 64));
      aiCtx.open = true;
    }
    function closeAiCtx() { aiCtx.open = false; }
    /** 复制：有框选 → 只复制选中部分；没框选 → 按右键落点复制（思考 / 正文）
       ⚠️ 菜单项文案不变（仍然只有「复制」），只是"复制哪一份"更聪明了。 */
    function aiCtxCopy() {
      const i = aiCtx.index;
      const zone = aiCtx.zone === 'think' ? 'think' : 'text';
      const sel = aiHasSelection()
        ? String((window.getSelection && window.getSelection().toString()) || '') : '';
      closeAiCtx();
      let text = sel;
      if (!sel.trim()) {
        text = zone === 'think'
          ? aiReasoningOf(i)                                   // 任务 6：思考区 → 思考内容
          : String((aiMessages.value[i] && aiMessages.value[i].text) || '');
      }
      if (!text) return;
      copyText(text);
    }



    /* ---------- 润色 ↔ 撤销润色 ----------
       aiPolishOriginal 存的是**润色前那句原文**（只在内存，不进历史、不落盘）。
       非空 = 输入框现在是"润色后的版本"，按钮画成"返回上一个"，点一下恢复原文。
       ⚠️ 关键：用户在润色后**又自己动了输入框**，就必须清掉这个可撤销状态 ——
          否则撤销会把用户刚打的字整段吃掉（用户最恨这个）。
          做法：程序自己赋值时先立 aiPolishApplying 标记，watch 见到标记就跳过清理。 */
    const aiPolishOriginal = ref('');
    let aiPolishApplying = false;

    /* ---------- 气泡原地编辑（用户消息） ----------
       aiEditingIndex = 正在编辑的那条消息下标（-1 = 没有）；
       aiEditDraft    = 编辑框里的文本。
       ⚠️ 编辑态**只存在于内存**：不落盘、不发送，✓ 才提交（作为新版本），✕ 直接丢弃。
       ⚠️ 下标会漂移（翻版本会整段换 messages），所以每次切换版本/发消息前都要先退出编辑。 */
    const aiEditingIndex = ref(-1);
    const aiEditDraft = ref('');
    /* ⚠️⚠️ 本轮**删掉 JS 量宽那一套**（原来的 aiComputeEditBox / aiMeasureTextWidth
       已整块移除），宽高交给浏览器：
       用户连着两轮报同一个功能 —— 上一轮「短文本变成固定长条」、本轮
       「编辑模式这个聊天气泡 ui 长度就固定了，它不会继续变长，就维持文本原本有多长」。
       根因不在"量得准不准"，而在**这条链路本身**：
         ① 一旦用 `:style` 给 textarea 写死 `width: <数字>px`，它就是**固定宽度**——
            之后用户多打字，宽度再也不跟着走（本轮报的现象）。
            想靠 @input 再算一遍来"持续自适应"也不可靠：Vue 的 v-model 和我们自己的
            input 监听挂在同一个事件上，**先后顺序不保证**，读到上一次的值就算出旧宽度；
            而且 canvas 量字宽要用 `ctx.font`，可 `getComputedStyle().font` 这个**简写**
            在 Chromium 里只有 CSS 显式写了 `font:` 才有值，本项目写的是
            font-size / font-family **分写** → 拿到空串 → canvas 退回默认 10px 字体
            → 量出来的宽度成倍偏小。每一环都脆弱，合起来就是"宽度不动"。
         ② 项目里**早就有浏览器原生方案**并且在用：`field-sizing: content`
            （Chromium 123+，WebView2 Evergreen 必然支持；主输入框那圈就靠它自适应）。
       ⇒ 正解：**让排版引擎按内容给尺寸**，前端一个像素都不算。
             短文本 = 小框（上一轮的"别固定长条"）；打字变长 = 跟着长（本轮这条）；
             到 max-width（父级 88%）才折行（"到一定长度自动换行"）；
             而"你好呀"被压在窄框里折成"你好↵呀"那种**不会有**：
             field-sizing 的框宽恒等于内容宽，压根不会先于内容折行。
       aiEditBox 现在只保留**高度兜底**（别让框塌成一条线）。 */
    const aiEditBox = ref({ width: 0, height: 0 });
    const aiEditBoxStyle = computed(() => {
      const box = aiEditBox.value || {};
      const style = {};
      /* ⚠️ 故意**不再写 width**：写了就把 field-sizing 的自适应钉死 = 本轮 bug 的成因。
         只给 min-height（进入编辑瞬间先按那颗气泡的高度垫一下，避免塌一条）。 */
      if (box.height) style.minHeight = box.height + 'px';
      return style;
    });

    /* 历史对话列表：一条 = 一个对话页 */
    const aiHistoryOpen = ref(false);
    const aiHistoryList = ref([]);
    async function loadAiSessions() {
      const result = await bridge.tryCall('ai.sessions');
      if (result && result.ok) aiHistoryList.value = result.sessions || [];
      return aiHistoryList.value;
    }
    /* 后端消息 → 前端气泡（统一走这里，确保 error/kind/版本 还原）
       ⚠️ 报错气泡（m.error）必须原样带回来，否则"从历史点进来报错没了"。
       ⚠️ 版本字段也要带回来（variants / variant_index），否则气泡上的 ◀ 2/3 ▶ 画不出来，
          翻过的版本在界面上"消失"（磁盘里其实还在）。
       ⚠️ 下标 i 就是后端 messages 的绝对下标（这里保持 1:1，不做任何过滤/排序）——
          翻版本、重新生成、编辑重发都要把这个下标传给后端，混了就改错条目。 */
    function sessionToMessages(session) {
      return (session && Array.isArray(session.messages) ? session.messages : []).map((m) => ({
        role: m.role === 'assistant' ? 'ai' : 'user',
        text: String(m.content || ''),
        error: !!m.error,
        kind: String(m.kind || ''),
        /* 思考文本（后端只在"思考开着"的回答里带；老会话/没开思考 = 空串 → 不画折叠块） */
        reasoning: String(m.reasoning || ''),
        /* 每一版的正文（老会话文件没有 → 只有当前这一条，等于"只有 v1"） */
        variants: Array.isArray(m.variants) ? m.variants.map((v) => String(v || '')) : null,
        /* 每一版的思考（和 variants 等长；翻版本时思考跟着翻） */
        thinkVariants: Array.isArray(m.variant_reasoning)
          ? m.variant_reasoning.map((v) => String(v || '')) : null,
        /* 当前第几版（0 基）；缺省时按"最后一版"显示（用户要求默认停在最后一版） */
        vIndex: Number.isFinite(m.variant_index) ? m.variant_index : 0,
        ts: String(m.ts || ''),
        /* ★ 本轮修复（用户报「Agent 执行步骤存储不到对应对话文件中，有时甚至出现缺失」
           的前端那一半）：后端每条 assistant 消息都带 steps（见 ai.py _message_view），
           这里**逐条**带进气泡对象。旧版只有一份全局数组 + "卡片画在最后一颗 AI 气泡
           下面"，多轮 Agent 的历史里早先几轮的步骤全部隐形（磁盘有、界面无 =
           用户说的"缺失"），翻版本/切会话时还会串位。 */
        steps: (Array.isArray(m.steps) && m.steps.length) ? m.steps.slice(0, 40) : null,
        /* 这一问自己的用量（缓存命中/统计）：done 事件与 _message_view 都带 */
        usage: (m.usage && typeof m.usage === 'object') ? m.usage : null,
        /* 这一问的延迟（done/send 回包里带的 latency_ms，本轮新增） */
        latency: Number.isFinite(m.latency_ms) ? m.latency_ms : null,
      }));
    }

    /* ---------- 每颗气泡自己的"执行过程"卡片（本轮，见上面 steps 注释） ----------
       数据源优先级：正在跑的这一轮（最后一颗 AI 气泡 + 运行中）用实时数组；
       其余一律用消息自带的 m.steps（历史 / 重开程序 / 翻版本都走这条路）。
       旧的"全局卡片挂最后一颗气泡"渲染点已改成调用这几个函数取"这一条"的数据。 */
    function aiBubbleSteps(m, i) {
      if (aiRunActive && aiRunCardIndex.value === i && aiAgentSteps.value.length > 0) {
        return aiAgentSteps.value;
      }
      if (m && Array.isArray(m.steps) && m.steps.length) {
        return m.steps.map((raw, si) => ({
          key: si,
          phase: 'result',
          round: Number(raw.round || 0) || 0,
          tool: String(raw.tool || ''),
          summary: String(raw.summary || raw.tool || t('agent_step_done', '已执行')),
          argsText: String(raw.args || ''),
          ok: raw.ok !== false,
          detail: String(raw.detail || ''),
        }));
      }
      return [];
    }
    function aiBubbleStepsOpen(m, i) {
      if (aiRunActive && aiRunCardIndex.value === i) return aiAgentStepsOpen.value;
      return !!(m && m._stepsOpen);
    }
    function aiToggleBubbleSteps(m, i) {
      if (aiRunActive && aiRunCardIndex.value === i) { toggleAgentSteps(); return; }
      if (!m) return;
      m._stepsOpen = !m._stepsOpen;
      aiAgentStepsTouched = true;
    }
    function aiBubbleStepsDone(m, i) {
      if (aiRunActive && aiRunCardIndex.value === i) return aiAgentStepsDone.value;
      return true;   // 历史里的步骤全是收尾状态
    }
    function aiBubbleStepsSummary(m, i) {
      if (aiRunActive && aiRunCardIndex.value === i) return aiAgentStepsSummary.value;
      const list = (m && Array.isArray(m.steps)) ? m.steps : [];
      const fail = list.filter((s) => s && s.ok === false).length;
      if (fail) {
        return t('ai_agent_finished_fail', '已完成 {n} 步（{fail} 步失败）')
          .replace('{n}', String(list.length)).replace('{fail}', String(fail));
      }
      return t('ai_agent_finished', '已完成 {n} 步').replace('{n}', String(list.length));
    }
    /* ---------- 版本相关的渲染小工具（模板里要用，必须在 setup 返回值里） ---------- */
    /** 这条气泡有几个版本（决定要不要画 ◀ n ▶） */
    function aiVariantCount(m) {
      return (m && Array.isArray(m.variants) && m.variants.length) || 1;
    }
    /** 当前第几版（1 基，画成 "2/3"） */
    function aiVariantPage(m) {
      if (!m) return 1;
      const count = aiVariantCount(m);
      const raw = Number.isFinite(m.vIndex) ? m.vIndex : count - 1;
      return Math.min(count, Math.max(1, raw + 1));
    }
    /** 气泡正文：流式中的那一条优先用临时累计文本
       ⚠️ 流式文本只活在渲染层，**不进会话文件**（落盘由后端在 done 时一次做完）。 */
    function aiBubbleText(m, index) {
      if (index === aiStreamingIndex.value && aiStreamingText.value) return aiStreamingText.value;
      return String((m && m.text) || '');
    }
    /** 能不能翻版本：忙 / 流式中不许（会把正在写的字冲掉，下标也会漂） */
    function aiCanSwitchVariant() {
      return !aiBusy.value && aiStreamingIndex.value < 0 && aiEditingIndex.value < 0;
    }
    /** 该条气泡是不是正在被编辑 */
    function aiIsEditing(index) { return aiEditingIndex.value === index; }

    function clearStreamBubble() {
      aiStreamId = '';
      /* ⚠️ 本轮（任务 4）：等 id 落定的"缓冲模式"也必须一起关 —— 否则上一条流被
         停止/切会话之后，下一条 send_stream 还没发出时，旧流的迟到事件会继续
         塞进缓冲，等新 id 一落定就被"重放"进新气泡（等于把旧流写进新会话）。 */
      if (typeof resetAiStreamBuffer === 'function') resetAiStreamBuffer();
      aiStreamingIndex.value = -1;
      aiStreamingText.value = '';
      /* 逐字打字机 + 思考流一起清：cancelAiTyper 会把攒着的收尾包丢掉，
         所以**只有"这条流彻底作废"（切会话/新发送）才这么调**；
         done/cancelled/error 那三个收尾走 finishAiStream（它会自己清）。 */
      cancelAiTyper();
      aiStreamTarget.value = '';
      aiStreamThinkTarget.value = '';
      aiStreamingReasoning.value = '';
      aiThinkStartedAt = 0;
      aiThinkSeconds = 0;
      aiThinkOpen.value = {};
      aiPending.value = false;
      aiPendingAfter.value = -1;               // 「正在生成」的落点也一起清（避免残留跑偏）
      aiStreamSlot.value = -1;
      /* 藏起来的那段也要立刻还回来：清空意味着"渲染层临时状态结束"，
         真正的内容以后端落盘后的会话为准（done 之后会用磁盘版重建）。 */
      aiCutAfter.value = -1;
      /* 流结束了 / 换会话了：看门狗就没意义了，必须撤掉，
         否则它会在**新**会话上弹一次"实时输出中断"的假警告。
         （arm/disarm 是 setup 里的函数声明，会被提升，这里直接调没问题） */
      disarmAiStreamWatchdog();
    }
    function cancelAiEdit() {
      aiEditingIndex.value = -1;
      aiEditDraft.value = '';
    }

    /* 打开程序时接上"最近一次对话"（和 PyQt 版共用同一份 chats/ 数据） */
    async function loadAiSession(sessionId) {
      const result = await bridge.tryCall('ai.session', sessionId || '');
      if (!result || !result.ok) return false;
      const session = result.session || {};
      aiSessionId.value = session.id || '';
      /* ⚠️ 换会话 = 这一份 messages 的下标全作废：正在编辑的气泡、正在流式的气泡、
         以及旧流的 stream_id 都要清掉，否则迟到的 delta 会往**新会话**的气泡里写字。 */
      cancelAiEdit();
      clearStreamBubble();
      aiMessages.value = sessionToMessages(session);
      /* ⚠️⚠️ 修用户报的两个问题：
         ①「切换历史/新建对话时调用工具的 ui 一直在这个界面里」→ 换会话必须清掉；
         ②「加载历史对话里面的"调用工具完成几步"那个不见了」→ 历史里应该**恢复**出来。
         所以这里不是简单清空，而是从会话数据里**还原**最后一条 AI 消息的步骤记录
         （后端把 steps 存在那条 assistant 消息上，见 ai.py 的 _persist_assistant）。
         恢复完后默认**折叠**（历史对话里不需要展开占地方）。 */
      restoreAgentStepsFromSession(session);
      /* ★ 本轮（统计面板）：重开会话时把磁盘上的会话累计/最近一问用量带回来，
         面板不至于"重启就清零"（数据本来就在 usage_total 里）。 */
      try {
        const t = session && session.usage_total;
        aiUsageTotal.value = (t && typeof t === 'object') ? { ...t } : null;
        let lastU = null;
        const msgs = (session && Array.isArray(session.messages)) ? session.messages : [];
        for (let k = msgs.length - 1; k >= 0; k -= 1) {
          const mm = msgs[k];
          if (mm && mm.role === 'assistant' && mm.usage && typeof mm.usage === 'object') {
            lastU = mm.usage; break;
          }
        }
        aiUsageLast.value = lastU ? { ...lastU } : null;
      } catch (e) { /* 统计不影响加载 */ }
      /* ★ 本轮修复：进历史对话同样要重新对一次思考档位（同 aiNewChat 那条注释）。
         不等它：会话内容已经可以看了，档位同步是后台的一次 model_choices。 */
      refreshAiThinking();
      return true;
    }
    async function openAiSession(sessionId) {
      if (!sessionId) return;
      /* 切会话前先把**当前**会话的位置存一份（任务 3：每个会话一份 scrollTop） */
      rememberAiScroll();
      const ok = await loadAiSession(sessionId);
      if (!ok) {
        /* ⚠️ 加载失败绝不能静默关面板：用户看到的就是“对话没了”。 */
        toast(t('ai_history_load_failed', '这个对话文件读不出来了，可能已损坏'), 'error');
        return;
      }
      aiHistoryOpen.value = false;
      /* 新开会话按它自己记住的位置恢复（没记过 → 到底），不强行拉到底 */
      nextTick(() => restoreAiScroll());
    }
    async function deleteAiSession(sessionId) {
      const yes = await openDialog({ title: t('ai_delete_session', '删除这个对话'),
        danger: true, body: t('ai_delete_session_body', '删除后无法恢复，确定要删除这个对话吗？'),
        confirmText: t('delete', '删除') });
      if (!yes) return;
      const result = await bridge.tryCall('ai.delete_session', sessionId);
      if (!result) return needApi('ai.delete_session', '删除对话');
      if (!result.ok) { toast(result.error || t('delete_failed', '删除失败'), 'error'); return; }
      if (aiSessionId.value === sessionId) { aiSessionId.value = ''; aiMessages.value = []; }
      await loadAiSessions();                     // 立刻刷新列表（不用重进界面）
      toast(t('deleted', '已删除'), 'success');
    }
    function aiHistory() {
      /* 开/关都走这个按钮（以前只会打开，于是"再点一次想关"没反应） */
      aiHistoryOpen.value = !aiHistoryOpen.value;
      if (aiHistoryOpen.value) loadAiSessions();  // 每次打开都拉最新的一份
    }
    function closeAiHistory() { aiHistoryOpen.value = false; }
    /* 需求（用户实测）：独立 AI 页的历史侧栏打开后，点**面板外面**的空白处不会自动收起。
       修法：document 上挂一次 mousedown（捕获阶段），点在 .ai-history 之外就关；
       打开它的那个按钮（[data-ai-history-toggle]）要排除，否则"点第二次想关"会先关再开。
       ⚠️ 用 mousedown 不用 click：在气泡里拖选文字时 click 根本不会发，mousedown 更直接；
          面板是 fixed 定位、独立页里和页面内容没有共同父级，挂在 document 上才收得到。 */
    function aiHistoryOutsideDown(event) {
      if (!aiHistoryOpen.value) return;
      const el = event && event.target;
      if (!el || typeof el.closest !== 'function') return;
      if (el.closest('.ai-history')) return;               // 面板内部：历史项/删除按钮等
      if (el.closest('[data-ai-history-toggle]')) return;  // 打开它的按钮：交给它自己切换
      closeAiHistory();
    }
    document.addEventListener('mousedown', aiHistoryOutsideDown, true);
    /* ===========================================================================
     * · 本轮任务 1 / 2 / 3：贴着底部？回到底部按钮；切窗/切页后的滚动恢复
     * ========================================================================
     * 用户原话（任务 1）：「当AI输出内容时我想往上滚动页面结果他给我锁在跟随它
     *   一起在页面位置最底部」。
     * 根因：旧 scrollAiToEnd() 无条件 `box.scrollTop = box.scrollHeight`，
     *   而流式每吐一次 delta 都会调它 → 用户往上滚一格就被拽回底部。
     * 修法：维护一个"用户是否贴底"的状态 aiStickBottom：
     *   · 滚动监听（passive）按"距底 <= 48px"实时刷新它；
     *   · scrollAiToEnd() 不再无条件到底 —— 只有贴底（或显式 force）才跟到底；
     *   · 用户自己发消息 / 点回到底部 / 切会话 → 显式 force（这些场合本来就该到底）。
     * ⚠️ 阈值取 48：太小（1~2px）会让"几乎贴底"被误判成"离开底部"，
     *    表现为输入框在动、内容不再跟随；太大又会让"已经明显上翻"仍被算贴底。
     * ======================================================================== */
    const AI_STICK_THRESHOLD = 48;
    const aiStickBottom = ref(true);
    /* 程序自己写 scrollTop 时置位 —— 否则下面那条滚动监听会把"恢复动作"
       当成用户行为，把 aiStickBottom 判错（任务 3 明确要求屏蔽）。
       ⚠️ 用计数器而不是布尔：一次恢复里可能连续写几帧（restoreAiScroll 的追帧），
          布尔会被第一帧的 rAF 提前放开，后面的写又被当成用户滚动。
          计数到 0 才算恢复结束。 */
    let aiScrollGuard = 0;
    /** 在"屏蔽滚动监听"的保护下写 scrollTop：写入 + 放开都压在同一个 rAF 之后 */
    function aiWithScrollGuard(fn) {
      aiScrollGuard += 1;
      try { return fn(); } finally {
        /* 写 scrollTop 触发的 scroll 事件是**异步派发**的（同一帧末尾），
           所以至少压到下一帧再放开；连写几帧时计数不会提前归零。 */
        requestAnimationFrame(() => {
          requestAnimationFrame(() => { aiScrollGuard = Math.max(0, aiScrollGuard - 1); });
        });
      }
    }
    /* 每个会话一份滚动状态 { top, stick }（内存 Map，用户没要求持久化到磁盘）。
       ⚠️ 为什么还要存 stick（是否贴底）而不是只存 top：
         用户走之前是"贴底看最新回答"的，回来时如果只按旧的 top 恢复，
         期间有新内容进来（或者面板宽度变了导致换行变多）就**不再是底部**了，
         观感等于"回来没跟上最新一条"。存了 stick 就能"原本贴底 → 恢复到底"（任务 3 第 2 条）。 */
    const aiScrollMemory = new Map();
    function aiScrollKey() { return aiSessionId.value || '__default__'; }
    function aiIsNearBottom(box) {
      if (!box) return true;
      return (box.scrollHeight - box.scrollTop - box.clientHeight) <= AI_STICK_THRESHOLD;
    }
    function aiMemoryWrite(box) {
      const el = box || aiScrollBox();
      if (!el) return;
      aiScrollMemory.set(aiScrollKey(), { top: el.scrollTop, stick: aiIsNearBottom(el) });
    }
    /** 记下当前会话的滚动位置（切会话 / 切页 / 关抽屉前都调一次） */
    function rememberAiScroll() { aiMemoryWrite(null); }
    /* ⚠️ 用**捕获阶段**的 document 监听：scroll 不冒泡，但会在捕获阶段路过 document。
       这样独立 AI 页 / 悬浮抽屉两处 .ai-messages（v-if 挂载、随时换节点）都不用
       逐个 addEventListener，也不存在"挂载时机没对上、监听丢了"的坑。 */
    function aiOnMessagesScroll(event) {
      const box = event && event.target;
      if (!box || !box.classList || !box.classList.contains('ai-messages')) return;
      /* 程序自己恢复位置时段的滚动不算"用户意图"（任务 3 的硬要求） */
      if (aiScrollGuard > 0) return;
      aiStickBottom.value = aiIsNearBottom(box);
      aiMemoryWrite(box);
    }
    /* 只注册一次（setup 只跑一次；.ai-messages 是 v-if 挂载的，所以监听挂在 document 上、按 target 过滤） */
    document.addEventListener('scroll', aiOnMessagesScroll, { capture: true, passive: true });
    /** 恢复当前会话的滚动位置（任务 3）：没记过 → 到底；记过 → 贴底恢复到底、否则回原位。
        ⚠️ 重试条件不能只看"写进去的值没生效"：刚挂载的那一帧 .ai-messages 里
           **气泡还没渲染完**，scrollHeight 等于可视高度 → 能滚的范围是 0，
           任何 scrollTop 都会被夹成 0（写成功了、看着也"生效"了）。
           于是旧写法（只在值不等时重试）当场放弃 → 用户回来还是停在最顶端。
           现在改成：只要**还没到目标**就继续追帧；目标本身每帧按最新的
           scrollHeight 重算（内容长高后 500 就真的能停住了）。 */
    function restoreAiScroll(attempt = 0) {
      const box = aiScrollBox();
      if (!box) {
        /* 面板/页面还在过渡中（抽屉展开、页面 enter）→ 下一帧再试，最多 40 帧
           （≈650ms；比 restorePageScroll 的 12 帧宽，因为 AI 气泡渲染 + 高度重排更慢） */
        if (attempt < 40) requestAnimationFrame(() => restoreAiScroll(attempt + 1));
        return;
      }
      const memo = aiScrollMemory.get(aiScrollKey());
      const has = !!memo;
      /* 原本贴底 → 恢复到底；否则回到记下的那个位置。
         目标每帧重算：内容还在长高时，"最大可滚位置"也在变。 */
      const maxTop = Math.max(0, box.scrollHeight - box.clientHeight);
      const wantRaw = (!has || memo.stick) ? box.scrollHeight : Number(memo.top || 0);
      const want = Math.max(0, Math.min(wantRaw, maxTop));
      aiWithScrollGuard(() => {
        box.scrollTop = want;
        aiStickBottom.value = (!has || memo.stick) ? true : aiIsNearBottom(box);
      });
      /* 还没到位就继续追（内容高度晚一两帧才稳定：气泡挂载 / 图片 / 字体）。
         ⚠️⚠️ 两个停止条件缺一不可：
           ① 写进去的值和期望不一致（浏览器夹住了）；
           ② **可滚范围还不够大**（maxTop < wantRaw）—— 这一条是本轮 jsdom 自验
              抓到的真 bug：刚挂载那一帧气泡还没渲染，scrollHeight == clientHeight
              → maxTop = 0 → want 被夹成 0 → 写 0 成功、和 want 相等 → 当场停止，
              用户切回来看到的还是最顶端。必须等高度长出来再写一次。 */
      const clamped = maxTop + 1 < wantRaw;
      if (attempt < 40 && (clamped || Math.abs(box.scrollTop - want) > 1)) {
        requestAnimationFrame(() => restoreAiScroll(attempt + 1));
      }
    }
    /** 任务 2：回到底部按钮点了之后 —— 平滑到底 + 重新置为贴底 */
    function aiBackToBottom() {
      const box = aiScrollBox();
      if (!box) return;
      aiStickBottom.value = true;
      const behavior = settings.ui_animation === 'off' ? 'auto' : 'smooth';
      /* ⚠️ 老内核 / 测试环境可能没有 Element.scrollTo：退回直接写 scrollTop
         （不平滑，但"回到底部"这件事照样成立，绝不能因为方法缺失就点不动）。 */
      if (typeof box.scrollTo === 'function') {
        box.scrollTo({ top: box.scrollHeight, behavior });
      } else {
        box.scrollTop = box.scrollHeight;
      }
      /* 平滑滚动要一会儿才到底，现在就把"这笔账"记成贴底（否则中途用户不再操作时
         记忆里还是旧的上翻位置，切页回来又跑回上面去了）。 */
      aiScrollMemory.set(aiScrollKey(), { top: box.scrollHeight, stick: true });
    }

    /* ---------- 任务 3：关窗/切页再回来，滚动位置不能丢 ----------
       用户原话：「当我关闭GCP-AI窗口或者切换窗口再回来这个页面会回到最顶端bug
         而不是停留在我走之前的页面滚动到的位置」。
       两个入口要分别接：
         · 独立 AI 页（sidebar 模式）：page 切走 / 切回 'ai' —— 切走前 DOM 还在，先 remember；
         · 悬浮抽屉：aiOpen 变 false / true —— 同理。
       ⚠️ 两个 watch 都用默认的 pre flush：**DOM 更新前**触发，
          "切走"那一拍 .ai-messages 还在，能把真实 scrollTop 读出来。
          "切回"那一拍还没挂载，所以恢复要交给 restoreAiScroll 的"重试最多 12 帧"。 */
    watch(page, (now, prev) => {
      if (prev === 'ai' && now !== 'ai') rememberAiScroll();
      if (now === 'ai') { nextTick(() => restoreAiScroll()); }
    });
    watch(aiOpen, (now) => {
      /* 抽屉模式才有意义（sidebar 模式 aiOpen 不参与渲染），但多判一次无害 */
      if (!now) rememberAiScroll();
      else nextTick(() => restoreAiScroll());
    });

    /* ---------- 任务 2：右下角「回到底部」圆形按钮 ----------
       用户原话：「当页面不是最底部时对话框上面也是页面的右小角有一个按钮是圆形
         里面有个朝下的图标很像V的那个图标，普通状态就这样，如果是正在输出的时候
         他的边框还会有一个在轮廓围绕转圈的发淡淡的光圈」。
       · 只在**不在底部**时出现（aiStickBottom 为 false）；
       · 只在 AI 面板真的可见时出现（独立 AI 页 / 展开的悬浮抽屉），
         否则 aiStickBottom 是 false 的时候会在别的页面上冒出一颗孤立按钮；
       · 正在输出（aiBusy 或还在流式）→ 按钮外轮廓那圈光开始转（见 ai-fixes.css）。 */
    const aiPanelVisible = computed(() =>
      page.value === 'ai' || (!!settings.ai_enabled && !settings.ai_sidebar_mode && aiOpen.value));
    const aiBackBottomVisible = computed(() => aiPanelVisible.value && !aiStickBottom.value);
    const aiStreaming = computed(() => aiBusy.value || aiStreamingIndex.value >= 0);

    function scrollAiToEnd(index, force) {
      /* 默认滚到最底部（新提问/新回答在下面，逐字输出要一路跟着底部走）。
         ⚠️ 任务 1（本轮）：**只有贴底才跟**。用户往上翻看历史时（aiStickBottom=false），
            流式 delta 再调这里必须什么都不做 —— 否则就是"被锁在页面最底部"。
            force = 新发送 / 切会话 / 点回到底部 这类必须到底的显式场合。
         ⚠️ 但**就地重新生成**时被重生的那条可能在中间：跟着滚到底会让用户
         看不见正在变的那颗气泡 → 传入下标时改成"把它滚进视野"：
           · 它就是最后一条 → 照常滚到底（逐字变高时贴着底部，和平时一致）；
           · 在中间 → block:'nearest'（已经在视野里就一动不动，看不见才挪最少一点），
             绝不打断用户正在看的位置。
         ⚠️ 不用 scrollIntoView 处理"最后一条"那一支：它只保证元素进视野，
         元素一边变高一边贴底要靠 scrollTop = scrollHeight 才对。 */
      const box = document.querySelector('.ai-messages');
      if (!box) return;
      /* ⚠️⚠️ 用户反馈：「我发现页面往下的速度太快了些」。
         根因：Agent 执行期间**每一步**都会触发一次滚动（calling / result 各一次，
         8 步就是 16 次，再加上步骤卡片变高），滚动条一路往下窜，看着很晕。
         取舍（用户 Q4 选 c「保持现状」= 仍跟到底，但要顺）：
           · Agent 正在干活时（有步骤且未完成）**不自动跟**—— 过程卡片就在视野里，
             不需要滚；等它做完再一次性滚到最终回答。
           · 其余情况照旧（贴底才跟），并且用 smooth 让位移是滑过去而不是瞬移。
         force（新发送/切会话/点回到底部）永远立即滚，不受上面限制。 */
      const running = aiAgentStepsVisible.value && !aiAgentStepsDone.value;
      const pinned = force === true || aiStickBottom.value;
      if (running && force !== true) return;
      const i = Number(index);
      if (Number.isFinite(i) && i >= 0 && i < aiMessages.value.length - 1) {
        const bubble = box.querySelector(`.bubble[data-i="${i}"]`);
        if (bubble && bubble.scrollIntoView) {
          try { bubble.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
          catch (e) { bubble.scrollIntoView({ block: 'nearest' }); }
          return;
        }
      }
      if (!pinned) return;
      /* 平滑滚动：位移是"滑"过去的，不会一步到头（关动效档则瞬时，尊重设置） */
      const smooth = settings.ui_animation !== 'off';
      if (smooth && typeof box.scrollTo === 'function') {
        try {
          box.scrollTo({ top: box.scrollHeight, behavior: 'smooth' });
          return;
        } catch (e) { /* 老内核不支持对象参数 → 退回直接赋值 */ }
      }
      box.scrollTop = box.scrollHeight;
    }
    /* ---------- 本轮需求：「使用版本树来回切换每次页面都会自动到最底部bug
       而不是保留在当前位置」----------
       翻版本走的是"整会话重建"（下标语义要求，见 aiSwitchVariant），
       而旧代码重建完就 nextTick(scrollAiToEnd) —— 不管用户在看第几条都拉到底。
       修法：重建**前**记下被翻那条气泡在视口里的位置，重建**后**把它挪回原处。
       用"锚点"而不是"记住 scrollTop"：新版本正文长短不同会让内容高度变化，
       固定 scrollTop 会跳到别的消息上；锚住那条气泡才叫"停在当前位置"。
       ⚠️ 用户正在往上翻看历史时（离底部很远）绝不自动滚到底 —— 这条也顺带解决。 */
    function aiScrollBox() {
      return document.querySelector('.ai-messages');
    }
    function captureAiAnchor(index) {
      const box = aiScrollBox();
      const bubble = box && box.querySelector(`.bubble[data-i="${index}"]`);
      if (!box || !bubble) return null;
      return {
        /* ⚠️ 必须把 index 一起存下来（本轮自查发现的 bug）：
           restore 里原来写的是 `box.querySelector('.bubble[data-i]')` —— 那取的是
           **第一个**带 data-i 的气泡，不是被锚定的那一条。翻 AI 版本时"它前面"的消息
           没变高，两者算出来的 delta 都恰好是 0，所以表面上看不出来；
           可一旦锚定的不是第一条、且它前面的内容也变了（比如编辑重发产生的新分支），
           就会拿错基准、滚到别的位置去。 */
        index, box,
        top: bubble.getBoundingClientRect().top - box.getBoundingClientRect().top,
      };
    }
    function restoreAiAnchor(anchor) {
      if (!anchor || anchor.index == null) return;
      /* box 也可能是切页后已经脱离文档的旧节点，重新查一次 */
      const box = (anchor.box && document.contains(anchor.box)) ? anchor.box : aiScrollBox();
      if (!box) return;
      const bubble = box.querySelector(`.bubble[data-i="${anchor.index}"]`);
      if (!bubble) return;
      const now = bubble.getBoundingClientRect().top - box.getBoundingClientRect().top;
      const delta = now - anchor.top;
      if (Math.abs(delta) < 1) return;
      /* 上限交给浏览器自己夹（内容变短时想保持的位置可能已超出可滚动范围，
         这时夹在最大处是正确行为，绝不能再手动 scrollIntoView/scrollAiToEnd） */
      box.scrollTop = Math.max(0, box.scrollTop + delta);
    }

    /* 悬浮球只在「开了 AI + 用的是悬浮球模式 + 抽屉没打开」时才显示。
       ⚠️ 需求：抽屉打开后悬浮球要消失隐藏（不然它压在抽屉右上角很丑）。 */
    const showBall = computed(() => !!settings.ai_enabled && !settings.ai_sidebar_mode && !aiOpen.value);
    const ballPaused = ref(false);
    const aiWelcomeText = computed(() => t('ai_welcome',
      '你好，我是 GCP-AI。说一个你想要的软件或网站，我来帮你找。'));
    const aiThinkingText = ref('正在思考…');
    function focusAiInput() {
      nextTick(() => { const el = document.querySelector('.ai-input'); if (el) el.focus(); });
    }
    /* ---------- 输入框 "/" 悬浮提示（插件制作辅助） ----------
       在 GCP-AI 不管哪个界面中输入 / 就会跳出 /plugin 悬浮提示，
       并且一旦开启（插件制作辅助）输入 / 才会有反应。
       数据来自后端 `ai.chat_hints()`（只在制作辅助开启时才有条目）；旧后端没有这个接口，
       就用内置默认提示兜底，保证插件制作辅助一开、两个输入框都能用 /plugin。 */
    const aiHints = ref([]);
    async function loadAiHints() {
      /* 插件制作辅助没开 → 一条提示都不给（用户要求："开了才会对 / 有反应"）。
         用 settingOn() 严格归一化，旧配置的字符串 "false" 也算关。 */
      if (!settingOn(settings.gcp_plugin_maker_enabled)) { aiHints.value = []; return; }
      const result = await bridge.tryCall('ai.chat_hints');
      const remote = (result && result.ok && Array.isArray(result.hints)) ? result.hints : null;
      if (remote && remote.length) {
        aiHints.value = remote.slice().sort((a, b) =>
          (Number(b.priority) || 0) - (Number(a.priority) || 0));
        return;
      }
      /* 旧后端没有 ai.chat_hints（或暂时还没登记条目）→ 内置默认提示兜底 */
      aiHints.value = [{ id: 'plugin-maker', label: t('ai_hint_plugin_maker', 'AI帮你制作插件'),
        insert: '/plugin', prompt: '', priority: 100 }];
    }
    /* 只在「开头是 / 且还是某条命令的前缀」时显示：打完 /plugin 再敲空格自动消失，
       发送/清空（aiDraft 变空）同理 → 不会一直挂在输入框上面。 */
    const aiSlashHints = computed(() => {
      /* /硬校验：只有插件制作辅助为开才可能有 / 命令提示。
         用户要求：只开启 GCP-AI Agent 时输入 / 不能冒出 /plugin；
         settings 里的值可能来自旧配置（undefined / 字符串 "true"/"false"），
         统一走 settingOn()（与后端 maker_enabled 同一套严格判定）。 */
      if (!settingOn(settings.gcp_plugin_maker_enabled)) return [];
      const raw = String(aiDraft.value || '');
      const text = raw.trim();
      /* 只在"刚输入 / 前缀"时显示：已经敲完整命令并补了空格（/plugin ）就收起，
         否则提示条会一直压在输入框上方。 */
      if (!text || text.charAt(0) !== '/' || raw !== text) return [];
      const typed = text.toLowerCase();
      return aiHints.value.filter((hint) =>
        String(hint.insert || '').toLowerCase().indexOf(typed) === 0);
    });
    function applyAiHint(hint) {
      const insert = String((hint && hint.insert) || '/plugin').trim() || '/plugin';
      aiDraft.value = insert + ' ';      // rich-ai-input 的 v-model watch 会把 DOM 一起更新
      /* ⚠️ 必须用组件自己的 focus()：setText 重建 DOM 后原生 focus() 会把光标放回开头，
         接着输入就会插到 "/plugin " 前面。两个 ref 按当前模式二选一（同 mentionAi）。 */
      nextTick(() => {
        const target = settings.ai_sidebar_mode ? aiInputPageRef.value : aiInputDrawerRef.value;
        if (target && typeof target.focus === 'function') target.focus();
        else focusAiInput();
      });
    }
    /* /rich-ai-input 的 / 命令白名单只跟插件制作辅助走（只开 GCP-AI Agent 不算）。
       ⚠️ 组件内部是 `(commands && commands.length) ? commands : DEFAULT_COMMANDS(['plugin'])`，
          传空数组会**回退成默认值**，/plugin 照样变蓝；所以"关闭"时传一个永不命中的哨兵。
       开启判定用 settingOn()，和后端 / 提示条三处保持同一套口径。 */
    const aiCommandWords = computed(() => (settingOn(settings.gcp_plugin_maker_enabled)
      ? ['plugin'] : ['__plugin_disabled__']));

    /* =====================================================================
     * · 输入框右下角「模型切换 UI」+ 弹层底部「思考」区（本轮改造）
     * =====================================================================
     * 本轮需求：输入框区域**不再有任何思考 UI**（原 .ai-think-slider 已删），
     * 思考档位选择搬进模型切换弹层的**底部固定区**（Codex 风格分段滑块）。
     * 数据源 = 后端 `ai.model_choices()`：
     *   · 它已经**按 Key 过滤**（没填 Key 的服务商整组不出现）—— 前端不猜 Key 状态；
     *   · 每个模型带 `supports_thinking`（能不能思考）；不支持的模型不画思考开关。
     * 换模型 = 写 settings.model_name + ai_provider（+ 思考**一律拨回关闭**，需求默认关）。
     * ⚠️ 旧后端没有 model_choices：aiModelSupported=false → 整个胶囊不渲染（needApi 降级）。 */
    const aiModelGroups = ref([]);          // [{provider,label,models:[{name,api_model,supports_thinking,thinking_levels}]}]
    const aiModelOpen = ref(false);
    const aiModelCurrent = computed(() => String(settings.model_name || ''));
    const aiModelLoading = ref(false);
    /* 回复语言候选（后端 model_choices().reply_languages：[{value,label}]）。
       null = 后端还没这个字段 → 前端用兜底 4 项（值必须和后端契约一致：auto|zh_CN|zh_TW|en）。 */
    const aiReplyLangsRemote = ref(null);
    async function loadAiModelChoices() {
      if (aiModelLoading.value) return;
      aiModelLoading.value = true;
      try {
        const result = await bridge.tryCall('ai.model_choices');
        if (result && result.ok) {
          aiModelGroups.value = Array.isArray(result.groups) ? result.groups : [];
          aiModelHasApi.value = true;
          /* ⚠️⚠️ 本轮修复用户报的两件事（其实是**同一个根因**）：
             「添加服务商之后模型选择ui并没有默认选择第一个模型」
             「模型选择ui并没有选择任何模型但是还是发送了消息成功回复了」
             前端胶囊显示的是 `settings.model_name`，而**发请求用的是后端推导的
             active_profile**（第一条有 Key 的档案）—— 两者从来不是同一个来源。
             新装/新加档案时 model_name 是空串 → 界面显示"选择模型"（像没选），
             可后端照样能用 active 档案回复 ⇒ "没选却发得出去"。
             修法：**以后端返回的 current 为准把界面选择补齐**，只在
             "当前选择无效"时补（空 / 不属于任何一条有 Key 的档案）。
             ⚠️ 必须保持上一轮那条需求：「保存新厂商不该改掉我已选模型」——
                所以这里绝不在"已经有一个有效选择"时覆盖它，只救"无效/空"这一种。 */
          aiSyncModelSelection(result.current);
          /* 回复语言清单：拿到就用官方的（label 跟随后端语言），拿不到留 null 走前端兜底 */
          aiReplyLangsRemote.value = (Array.isArray(result.reply_languages)
            && result.reply_languages.length)
            ? result.reply_languages.filter((l) => l && l.value) : null;
        } else if (result === null) {
          aiModelHasApi.value = false;      // 后端没这个接口：降级隐藏胶囊
        }
      } catch (error) { aiModelHasApi.value = false; } finally { aiModelLoading.value = false; }
    }
    /** 当前界面选择无效（空 / 不在任何有 Key 的档案里）时，跟随后端生效的那一条。
       后端 `current` 与 _credentials() **完全同一口径**（同一份 active_profile 推导），
       所以以它为准 = 界面显示的就是这次真正会发出去的那个模型，不会再"各说各话"。 */
    function aiSyncModelSelection(current) {
      if (!current) return;
      const curModel = String(settings.model_name || '').trim();
      const curProvider = String(settings.ai_provider || '').trim().toLowerCase();
      const curId = String(settings.ai_profile_id || '').trim();
      /* 已经有效？—— 用档案 id 判（同厂商两条档案靠它区分），其次厂商+模型名。
         有效就一个字节都不动（保住"保存新厂商不改我已选模型"那条需求）。 */
      if (curModel) {
        if (curId) {
          if ((aiModelGroups.value || []).some((g) => String(g.id || '') === curId)) return;
        } else if ((aiModelGroups.value || []).some((g) => String(g.provider || '') === curProvider)) {
          return;
        }
      }
      const model = String(current.model || '').trim();
      if (!model) return;                     // 后端也没有可用模型（一家 Key 都没填）：保持"未选择"
      settings.model_name = model;
      settings.ai_provider = String(current.provider || '') || curProvider;
      if (current.id) settings.ai_profile_id = String(current.id);
    }
    /** 设置页「回复语言」下拉的 options（后端清单优先，兜底 4 项；自绘 combo 只吃 [{value,label}]） */
    function aiReplyLangOptions() {
      /* 用户实测：切了界面语言，这个下拉还是「简体中文」——因为 label 用的是后端
         那次 model_choices 回传的旧文案（抓的时候还是旧语言），之后再没刷新过。
         正确做法：**value 用后端的**（将来加语种不用动前端），**label 现取当前语言包**。
         sections 是 computed 且 t() 读 I18N.version，所以切语言立刻跟着变。 */
      const LOCAL = [
        { value: 'auto', key: 'ai_reply_lang_auto', zh: '跟随输入语言' },
        { value: 'zh_CN', key: 'ai_reply_lang_zh_CN', zh: '简体中文' },
        { value: 'zh_TW', key: 'ai_reply_lang_zh_TW', zh: '繁体中文' },
        { value: 'en', key: 'ai_reply_lang_en', zh: '英文' },
      ];
      const labelOf = (value, fallback) => {
        const hit = LOCAL.filter((l) => l.value === value)[0];
        return t(hit ? hit.key : 'ai_reply_lang_' + value, fallback || value);
      };
      const remote = aiReplyLangsRemote.value;
      if (remote && remote.length) {
        return remote.map((l) => {
          const value = String(l.value);
          return { value: value, label: labelOf(value, l.label) };
        });
      }
      return LOCAL.map((l) => ({ value: l.value, label: t(l.key, l.zh) }));
    }
    /* 后端有没有这个接口（旧后端 → 不画胶囊，而不是画一个空的） */
    const aiModelHasApi = ref(true);
    const aiModelVisible = computed(() => aiModelHasApi.value && !!settings.ai_enabled);

    /* =====================================================================
       对话模式胶囊（Chat / Agent）—— 本轮新增
       =====================================================================
       用户原话：「在GCP-AI页面或者右侧窗这个模型选择左侧新增一个一样的ui，不过点击出来
         里面的不一样，只有一个Chat和Agent选项，Chat只能聊天也是默认选项，Agent则可以
         调用AI Agent获取可以行动起来的能力，不单单是只能聊天，不过确实也可以只把它当作
         聊天对象（这两个模式切换也出储存在配置里面）。」

       语义（和后端 ai._agent_tools_ready 的闸门一一对应）：
         · Chat  —— 默认。**不注入工具清单、不跑工具循环**：就是普通聊天，省 token，
                    也不会出现"我只是想聊聊，它却去改我的设置"。
         · Agent —— 才把 38 只「手」的清单塞进 system 并允许 [TOOL] 循环。
        ⚠️ 和插件总开关（强制开启）不是一回事：插件决定了"这套能力在不在"，
           这颗胶囊决定"这次对话要不要真的动手"。强制开启 ≠ 每次都要动手。
        ⚠️ **落盘**：写 settings.ai_chat_mode（用户明确要求"这两个模式切换也出储存在
           配置里面"），走 saveSetting 同一条链路（settings.set → 广播 → 另一端同步）。
       --------------------------------------------------------------------- */
    const CHAT_MODE_KEY = 'ai_chat_mode';
    const CHAT_MODE_OPTIONS = [
      { value: 'chat', label: 'Chat',
        tipKey: 'ai_mode_chat_tip', tipFallback: '只聊天：不会调用工具、不会改动程序（默认）' },
      { value: 'agent', label: 'Agent',
        tipKey: 'ai_mode_agent_tip', tipFallback: '可以动手：允许 AI 操作 ToolsGCP（仍有逐项开关约束）' },
    ];
    const aiModeOpen = ref(false);
    /* =====================================================================
       Agent 执行过程（大厂 Agent 那种"正在调用工具"）
       =====================================================================
       用户原话：「我希望他有那种大厂agent软件会提示正在调用工具什么的 调用什么和规划
         之类的都要有」「而且我希望它输出的内容是人话」。

       数据源：后端 ai.py 工具循环里 push_event("ai.agent_progress", {...})
         phase: 'calling' | 'result'
         round / tool / summary（后端给的中文摘要，直接用，前端不翻译工具名）/ ok / detail
       ⚠️ 为什么摘要由后端给：前端只认识 create_favorite_folder 这种英文 id，
          翻成人话要维护一张映射表、加工具就漏；后端手上有 args，能拼出
          "正在创建收藏夹「GCP」"这种带具体对象的话。
       ⚠️ 这只在 Agent 模式出现：Chat 模式没有工具循环，自然没有这些步骤。 */
    const aiAgentSteps = ref([]);
    /* 正在规划/思考中（后端每轮推 planning）—— 让界面先给出"正在思考"的反馈，
       而不是等思考和正文一起蹦出来 */
    const aiAgentPlanning = ref(false);        // [{phase, round, tool, summary, ok, detail, key}]
    let aiAgentStepSeq = 0;
    /* ★ 本轮修复（用户报 Agent 步骤"重复/串会话"）：ai.agent_progress 事件**不带
       stream_id/session_id**（后端 push 直接走 shell.push_event），换会话/按停止之后
       旧运行的尾事件照样会推过来，把卡片混进新会话。现在加一道运行闸门：只有
       "本端正有一次发送在飞"时才接受这些事件；发送开始置真、done/cancel/error/
       切会话一律置假，旧尾事件全部丢弃。 */
    let aiRunActive = false;
    function onAgentProgress(payload) {
      if (!payload || typeof payload !== 'object') return;
      if (!aiRunActive) return;
      const phase = String(payload.phase || '');
      const tool = String(payload.tool || '');
      const round = Number(payload.round || 0) || 0;
      /* planning：模型开始规划这一步（用户要求"先思考再工具最后正文"）。
         它不清空已有步骤，只标记"当前正在思考"，让界面先给出反馈。 */
      if (phase === 'planning') {
        aiAgentPlanning.value = true;
        return;
      }
      aiAgentPlanning.value = false;
      if (phase === 'calling') {
        aiAgentSteps.value.push({
          key: ++aiAgentStepSeq, phase: 'calling', round, tool,
          /* 本轮 i18n：兜底文案改走语言包（后端 summary 缺失时英文界面不再露中文） */
          summary: String(payload.summary || tool || t('agent_step_executing', '正在执行')),
          /* ⚠️ 把参数也存下来展示成子项（用户原话：「具体内容什么的都没有没有子项在
             这个分别的里面」）—— 光有一句"正在创建收藏夹「GCP」"不够，
             用户想看到这一步具体带了什么参数（folder=GCP / code=TG-000050）。 */
          argsText: agentArgsText(payload.args),
          ok: null, detail: '',
        });
      } else if (phase === 'result') {
        /* 把这一轮这个工具的最后一条 calling 标成结果（同一个工具可能连调多次，
           所以从后往前找第一条还没结果的）。找不到就补一条（后端可能先 result）。 */
        let target = null;
        for (let i = aiAgentSteps.value.length - 1; i >= 0; i -= 1) {
          const step = aiAgentSteps.value[i];
          if (step.phase === 'calling' && step.tool === tool && step.ok === null) {
            target = step;
            break;
          }
        }
        if (target) {
          target.phase = 'result';
          target.ok = payload.ok !== false;
          target.detail = String(payload.detail || '');
        } else {
          aiAgentSteps.value.push({
            key: ++aiAgentStepSeq, phase: 'result', round, tool,
            summary: String(payload.summary || tool || t('agent_step_done', '执行完成')),
            ok: payload.ok !== false, detail: String(payload.detail || ''),
          });
        }
      }
    }
    /* 把工具参数压成一行可读的子项文本（空参数返回空串 = 不显示子项） */
    function agentArgsText(args) {
      if (!args || typeof args !== 'object') return '';
      const parts = [];
      Object.keys(args).forEach((key) => {
        let value = args[key];
        if (value === undefined || value === null || value === '') return;
        if (typeof value === 'object') {
          try { value = JSON.stringify(value); } catch (e) { value = String(value); }
        }
        const text = String(value);
        if (text.length > 60) return;      /* 超长参数（run_python 的代码）不进子项 */
        parts.push(key + '=' + text);
        if (parts.length >= 5) return;
      });
      return parts.join('  ');
    }
    function aiResetStats() {
      /* 新对话 = 新账本：累计与最近一问都清空（后端那边新会话本来也没有 usage_total） */
      aiUsageLast.value = null;
      aiUsageTotal.value = null;
    }

    function resetAgentSteps() {
      aiAgentSteps.value = [];
      aiAgentStepSeq = 0;
      aiAgentPlanning.value = false;
      /* 换会话/新发送都会先走这里：闸门一并关掉，旧运行的尾事件不再混进新卡片。
         （发送路径紧接着会重新置 true，顺序见 aiSend 里 resetAgentSteps 之后的赋值。） */
      aiRunActive = false;
    }

    /* 从会话数据里恢复"上次执行了几步"
       ⚠️⚠️ 修用户报的：「我加载历史对话里面的调用工具完成几步那个不见了，没有存储起来的bug」
       步骤原本只活在内存里，换会话/重启就没了。现在后端把它**存进那条 assistant 消息**
       （字段 steps），这里读回来重建卡片。恢复后默认折叠（历史里不需要展开占地方）。
       数据形状：[{tool, summary, args, ok, detail}, ...]（后端存的是紧凑版） */
    function restoreAgentStepsFromSession(session) {
      resetAgentSteps();
      aiAgentStepsOpen.value = false;
      aiAgentStepsTouched = false;
      let steps = null;
      try {
        const list = (session && Array.isArray(session.messages)) ? session.messages : [];
        /* 从后往前找第一条带 steps 的 assistant（最新那条回复的执行记录） */
        for (let i = list.length - 1; i >= 0; i -= 1) {
          const m = list[i];
          if (m && m.role === 'assistant' && Array.isArray(m.steps) && m.steps.length) {
            steps = m.steps;
            break;
          }
        }
      } catch (e) { steps = null; }
      if (!steps) return;
      steps.forEach((raw) => {
        if (!raw || typeof raw !== 'object') return;
        aiAgentSteps.value.push({
          key: ++aiAgentStepSeq,
          phase: 'result',
          round: Number(raw.round || 0) || 0,
          tool: String(raw.tool || ''),
          summary: String(raw.summary || raw.tool || t('agent_step_done', '已执行')),
          argsText: String(raw.args || ''),
          ok: raw.ok !== false,
          detail: String(raw.detail || ''),
        });
      });
    }
    /* 执行过程卡片是否显示：有步骤 且 正在忙（或刚结束还没清） */
    /* ★ 本轮（用户 m02381：「agent模式或chat模式下，ai每次都会先出现一个『v』
       大概是这个样子的ui然后后面消失了，因为agent和chat没让它干活但是还显示这个
       就不对了」）：
       卡片**只由真实步骤撑起来**（aiAgentSteps.length > 0）。
       原来「正在规划」也能单独把卡片撑出来 —— 那张卡片头上是一个 #i-chevron_down
       的 V 形折叠箭头，于是每轮（哪怕模型压根没调工具、这一轮就是最终回答）
       都先闪出一个「v」，等这一轮结束卡片又被收掉 → 用户看到的就是「先出现一个 v
       然后后面消失」。
       现在后端也只在**真的解析出工具调用**时才推 planning（见 desktop/api/ai.py），
       两边一起改：没有活要干的时候，界面上一个「v」都不会冒出来。 */
    const aiAgentStepsVisible = computed(() =>
      aiAgentSteps.value.length > 0);
    /* 折叠：全部完成后自动收起成一行「已完成 N 步」。
       ⚠️ 用「用户手动展开过」做覆盖：他点开了就一直开着，别自动又收回去。 */
    const aiAgentStepsOpen = ref(true);
    let aiAgentStepsTouched = false;
    const aiAgentStepsDone = computed(() =>
      aiAgentSteps.value.length > 0
      && aiAgentSteps.value.every((s) => s.phase === 'result'));
    const aiAgentStepsSummary = computed(() => {
      /* 还没开始调工具、只收到 planning → 先显示"正在思考"，
         避免界面上什么都没有（用户会以为卡住） */
      if (!aiAgentSteps.value.length) {
        return aiAgentPlanning.value
          ? t('ai_agent_planning', '正在思考怎么处理…') : '';
      }
      const total = aiAgentSteps.value.length;
      const failed = aiAgentSteps.value.filter((s) => s.phase === 'result' && s.ok === false).length;
      const doneCount = aiAgentSteps.value.filter((s) => s.phase === 'result').length;
      if (!aiAgentStepsDone.value) {
        return t('ai_agent_running', '正在处理 {done}/{total} 步...')
          .replace('{done}', doneCount).replace('{total}', total);
      }
      return failed
        ? t('ai_agent_finished_fail', '已完成 {n} 步（{fail} 步失败）')
          .replace('{n}', total).replace('{fail}', failed)
        : t('ai_agent_finished', '已完成 {n} 步').replace('{n}', total);
    });
    function toggleAgentSteps() {
      aiAgentStepsTouched = true;
      aiAgentStepsOpen.value = !aiAgentStepsOpen.value;
    }
    /* 当前模式：设置里的值，认不出来一律当 chat（和后端 chat_mode() 同一口径 ——
       宁可少动手，也不能因为一个脏配置让 AI 突然开始改东西）。 */
    const aiChatMode = computed(() => (String(settings.ai_chat_mode || '') === 'agent'
      ? 'agent' : 'chat'));
    const aiChatModeLabel = computed(() => (aiChatMode.value === 'agent' ? 'Agent' : 'Chat'));
    const aiChatModeTip = computed(() => {
      const opt = CHAT_MODE_OPTIONS.find((o) => o.value === aiChatMode.value) || CHAT_MODE_OPTIONS[0];
      return t(opt.tipKey, opt.tipFallback);
    });
    /* 胶囊可见性：和模型胶囊同一条件（AI 开着才显示）。
       ⚠️ 不依赖后端新接口：settings.ai_chat_mode 有默认值（constants），
          老后端即使没有 ai.set_chat_mode，写 settings 也照样能存下来。 */
    const aiModeVisible = computed(() => !!settings.ai_enabled);
    function toggleAiModeMenu() {
      if (!aiModeVisible.value) return;
      aiModeOpen.value = !aiModeOpen.value;
      /* 和模型弹层互斥：两个都开就叠在一起了 */
      if (aiModeOpen.value) aiModelOpen.value = false;
    }
    async function aiPickChatMode(value) {
      const want = String(value || '') === 'agent' ? 'agent' : 'chat';
      aiModeOpen.value = false;
      if (want === aiChatMode.value) return;
      /* 先乐观更新（点一下就变，不等往返），失败再回滚 */
      const previous = settings.ai_chat_mode;
      settings.ai_chat_mode = want;
      const saved = await saveSetting(CHAT_MODE_KEY, want);
      if (!saved) {
        settings.ai_chat_mode = previous;
        return;
      }
      toast(want === 'agent'
        ? t('ai_mode_switched_agent', '已切换到 Agent 模式：这次对话 AI 可以动手操作')
        : t('ai_mode_switched_chat', '已切换到 Chat 模式：只聊天，不会改动程序'),
        'info');
    }
    /* =====================================================================
     * · 思考档位（本轮需求：思考 UI 从输入框搬进「模型切换弹层」底部）
     * =====================================================================
     * 存的值是档位字符串（= 后端 thinking_levels[].value，官方 reasoning_effort 口径）。
     * ⚠️ 上一轮这里写的是 `settingOn(settings.ai_thinking)`（布尔判定）—— 换成档位后
     *    `settingOn("off")` 会因为非空字符串而判成**真**，滑块看着像在高档位、
     *    实际后端是关的。这就是用户报的"模型和思考在设置里改了并没有立即变化"的一条根因。
     *    现在统一走 normalizeAiThinking()，前端后端一套归一化口径。
     * ⚠️ 本轮（lead 契约 v2，官方核实后）：thinking_levels 是 [{value,label,effort}]，
     *    **档数与档位名完全由各家官方 API 决定，第一档不再恒为 off** ——
     *    kimi-k3/k3.1-pro 官方是 low/high/max（思考恒开、没有关这一档），
     *    k2.7-code 只有单档（恒开）。所以下面所有"第 0 档 = off"的老假设都已改掉：
     *    回落一律取 `levels[0]`（表内第一档），绝不写死 'off'。
     *    显示名一律用后端 label（前端兜底表只兜"后端没给 label"的旧数据）。
     */
    const AI_THINK_LEVELS = ['off', 'low', 'medium', 'high'];   // 仅旧后端兜底（没有 thinking_levels 字段时）
    function normalizeAiThinking(value) {
      /* 与后端 providers.normalize_thinking 同口径（旧配置是布尔 True/False）
         ⚠️ 'max' 是 DeepSeek 官方独立档位，**不能再折成 'high'**（后端 providers 已经
            按官方表识别 max；这里折一下会让"存的值"和"表里的值"对不上，
            aiThinkingLevel 就命中不了原始存档值、界面看着像没反应）。 */
      if (value === true) return 'medium';
      if (value === false || value === null || value === undefined || value === '') return 'off';
      const text = String(value).trim().toLowerCase();
      if (['off', 'none', 'false', '0', '关', '关闭'].indexOf(text) >= 0) return 'off';
      if (['on', 'true', '1', '开', '开启', 'enabled'].indexOf(text) >= 0) return 'medium';
      if (['low', 'minimal', '低'].indexOf(text) >= 0) return text === 'minimal' ? 'minimal' : 'low';
      if (['medium', 'mid', '中'].indexOf(text) >= 0) return 'medium';
      if (['high', '高'].indexOf(text) >= 0) return 'high';
      if (text === 'max') return 'max';
      return 'off';
    }
    /* ⚠️ 这里原来有个 `aiThinkModelKey` computed（只给 provider + model 两项）。
       本轮被下面的 `aiThinkModelEntry()` 取代了：查档位表**和**查档位都必须
       带上"档案 id"，只成对取 (provider, model) 的那个键本身就不够用了
       —— 留着它就是一处"看着还在用、实际没人调"的误导，直接删。 */
    /** 当前选中的 (档案 id + 厂商 + 模型) 在后端 groups 里命中的**那一个模型对象**。
       ⚠️ 抽成一个函数是有原因的：档位表（thinking_levels）和这条档案×这个模型
          自己存过的档位（thinking）必须按**同一套匹配规则**取出来。
          以前是"档位表在这里匹配一遍、档位去查本地镜像表"，两套口径 →
          同厂商两条档案列同名模型时，档位表是 A 的、显示的值是 B 的（用户报的"相通"）。
          现在两处都走这个函数，物理上不可能再对不上。
       ⚠️ 分组匹配顺序：先**档案 id**（用户显式选中的那条），其次才按厂商。
          同厂商两条档案的模型清单可能不同（一条勾了 2 个、另一条 5 个），
          只看 provider 会拿错档位表。 */
    function aiThinkModelEntry(providedId, provider, name) {
      const pid = String(providedId != null ? providedId
        : (settings.ai_profile_id || '')).trim().toLowerCase();
      const prov = String(provider != null ? provider
        : (settings.ai_provider || '')).trim().toLowerCase();
      const modelName = String(name != null ? name : (aiModelCurrent.value || '')).trim();
      if (!modelName) return null;
      for (const group of aiModelGroups.value || []) {
        const groupProvider = String(group.provider || '').toLowerCase();
        const groupId = String(group.id || '').toLowerCase();
        if (pid) {
          /* 有档案 id：只认同 id 的那条；id 对不上但厂商也不同 → 跳过。
             （老后端不给 group.id 时退化成按厂商匹配，不至于整块画不出来。） */
          if (groupId && groupId !== pid && groupProvider === prov) continue;
        }
        for (const model of group.models || []) {
          if (String(model.name || '').trim() !== modelName) continue;
          return model;
        }
      }
      return null;
    }
    /** 后端算好的"这条档案 × 这个模型"的档位；老后端没这个字段就返回 ''。
       ⚠️ 这是档位的**权威来源**：后端按 `档案id|厂商|模型` 查表，没记录就是 off。
          前端本地那份 `settings.ai_thinking_level` 只包含前端自己写过的条目，
          查不到时**绝不能**回落到全局 `settings.ai_thinking` —— 那个值每次切模型
          都会被刷新成"上一个模型的档位"，拿它当默认值就是用户报的
          「厂商添加好了后，每个思考 ui 都应该是关闭状态」不成立的前端半边。 */
    function aiThinkBackendLevel() {
      const model = aiThinkModelEntry();
      if (!model || model.thinking == null) return '';
      return String(model.thinking).trim();
    }
    /** 当前模型的档位表（对象数组 [{value,label,effort}]）：不支持思考 → 只有 off 一档 */
    const aiThinkLevelsFull = computed(() => {
      const model = aiThinkModelEntry();
      if (!model) {
        /* 模型认不出来（清单没拉到/自定义模型名）：只给 off —— 宁可不给滑块 */
        return [{ value: 'off', label: 'off' }];
      }
      if (Array.isArray(model.thinking_levels) && model.thinking_levels.length) {
        return model.thinking_levels
          .filter((l) => l && l.value)
          .map((l) => ({ value: String(l.value), label: String(l.label || l.value) }));
      }
      /* 旧后端没有 thinking_levels：按 supports_thinking 兜成默认 4 档表 */
      if (model.supports_thinking) {
        return AI_THINK_LEVELS.map((v) => ({ value: v, label: v }));
      }
      return [{ value: 'off', label: 'off' }];
    });
    /** 档位值数组（内部逻辑用；显示走 label） */
    const aiThinkLevels = computed(() => aiThinkLevelsFull.value.map((l) => l.value));
    /** 当前模型支持思考吗（只有 off 一档 = 不支持；弹层里思考区显示禁用态而不是消失） */
    const aiThinkSupported = computed(() => aiThinkLevelsFull.value.length > 1);
    const aiThinkingLevel = computed(() => {
      /* 需求（用户原话）：「（同厂商或不同厂商多个同时至少 2 个存在时，或单个厂商
         在设置中的 GCP-AI 厂商设置添加好了后）每个思考 ui 都应该是关闭状态，
         并且每个都是独立存储的思考强度挡位」。
         ⚠️⚠️ 回落顺序本轮重排过，顺序本身就是修复：
           ① **后端算好的** `model.thinking`（按 档案id|厂商|模型 查表，
              没记录就是 off）—— 事实源，永远优先；
           ② 本地镜像表里**这条档案 × 这个模型**存过的档位 —— 只在后端没给
              这个字段（老后端）时兜底；
           ③ 表内第一档 levels[0]（各家官方表第一档通常是 off；
              kimi-k3 那类"思考恒开"的表取官方最小档，绝不写死 'off'）。
         ⚠️ 这里**不再有**"退回全局 settings.ai_thinking"那一步：它是
            "上一个模型的档位"快照，任何新厂商/新模型都会被它点亮成 high/max
            —— 正是用户报的"默认不是关闭"。
         候选值先直接对表：命中就用官方原值（'max'/'minimal' 这种本地归一化表
         没有的官方档位，绝不能在显示层被 normalize 改掉）。命不中才归一化。 */
      const levels = aiThinkLevels.value;
      /* ⚠️⚠️ 本轮修滑块"被锁定"时翻转了上一轮的优先级（上一轮那句"后端值永远优先"
         是我的设计失误）：
           用户拨档位 → setAiThinkingLevel 先写本地镜像，再 saveSetting('ai_thinking')；
           这条写入会广播 settings-changed → 触发 loadAiModelChoices() 重拉 groups，
           而那一刻后端的表**可能还没收到这次档位**（请求在路上/失败/老后端没接口）。
           "后端优先"于是把旧值盖回显示 ⇒ 滑块**立刻弹回原位**，看着就是"点了没反应/
           被锁住"，用户报的正是这个现象。
         正确语义：本地镜像 = **用户刚刚的显式操作**，必须优先；
                   后端 `model.thinking` = 没本地记录时的权威初值（保证"新模型默认关闭"），
                   以及跨端（浏览器模式改过）同步进来时的来源。
         两者对同一 (档案,模型) 的正常值本来就相同，只在"刚拨完还没落库"这几十毫秒里
         分胜负 —— 那几十毫秒恰恰是用户唯一在看的时间。
         最后再兜 levels[0]（各家官方表第一档；kimi-k3 那类恒开表取官方最小档，
         绝不写死 'off'）。绝不回落全局 settings.ai_thinking（那是"上一个模型的档位"，
         用它当默认值就是上一轮修的「新厂商默认不是关闭」）。 */
      const raw = aiThinkStoredLevel() || aiThinkBackendLevel();
      if (raw && levels.indexOf(raw) >= 0) return raw;
      const cur = normalizeAiThinking(raw);
      return levels.indexOf(cur) >= 0 ? cur : (levels[0] || 'off');
    });
    /* 思考档位本地镜像的键：**档案 id + 厂商 + 模型名**。
       ⚠️⚠️ 本轮需求（用户原话）：「服务商的模型列表里有同一个服务商时，他的模型很多设置
          都是相通的，例如思考强度 ui 他们就是相通的，可我需要的是**每个模型独立存储**，
          删除厂商也跟随删除，而不是同厂商的就允许相同」。
          旧键 `provider|model`：同一家厂商的两条档案（两套 Key / 一个官方一个中转）
          列了同一个模型名时**共用一条记录** → 在 A 上拨到 high，B 也跟着变。
          ⇒ 键里必须带**档案 id**，和后端 ai_profiles.thinking_key 逐字一致
             （`profile_id|provider|model`），两端算出来的键不同就会互相看不见对方写的值。
       ⚠️ 没有档案 id 时（老配置直接跑）退回旧格式，和后端同样兼容。 */
    function aiThinkMirrorKey(providedId, provider, name) {
      /* ⚠️ 三个参数都可省略（省略 = 按"当前界面上选中的那条"算）。
         但在 `pickAiModel` 那种"新的选择还没写进 settings"的时点**必须显式传**，
         否则算出来的是**上一个**模型/档案的键 —— 于是档位被记到别人身上
         （本轮自测真踩过：给 A 设完档位，切到 B 时把 A 的键改了）。 */
      const prov = String(provider != null ? provider
        : (settings.ai_provider || '')).trim().toLowerCase();
      const model = String(name != null ? name : (settings.model_name || '')).trim();
      const pid = String(providedId != null ? providedId
        : (currentAiProfileId() || '')).trim().toLowerCase();
      if (!prov || !model) return '';
      const body = prov + '|' + model;
      return pid ? (pid + '|' + body) : body;
    }
    /** 本地镜像表里"这条档案 × 这个模型"**自己存过**的档位；没存过就返回 ''。
       ⚠️⚠️ 本轮改动（用户报的"添加好厂商后思考强度默认不是关闭"的前端半边）：
          旧写法最后一行是 `return settings.ai_thinking` —— 那是"上一个模型的档位"
          快照，任何没设过的新厂商/新模型都会继承它，界面显示出来就是 high/max。
          现在查不到就返回 **空串**，由 aiThinkingLevel 按"后端值 → 表内第一档"回落，
          绝不拿快照当默认值（与后端 _thinking_level_for 本轮同一口径）。
       ⚠️ 只认**带档案 id** 的键：旧格式 `provider|model` 同厂商两条档案共用，
          读它就会让"删了一条档案、另一条又复活成旧档位"，正是要修的现象。
          （写入端同理，见 setAiThinkingLevel / pickAiModel。） */
    function aiThinkStoredLevel() {
      const key = aiThinkMirrorKey();
      if (!key) return '';
      const store = settings.ai_thinking_level;
      if (!store || typeof store !== 'object') return '';
      const hit = store[key];
      if (hit == null || !String(hit).trim()) return '';
      return String(hit).trim();
    }
    /** 档位刻度点是不是该整排隐藏：滑块推到**最右**（最高档）时全隐
        （本轮需求原话：「滑动条到最右处中间的小圆点全部隐藏」——
         语义就是"已经到头了，中间的候选点没有意义"）。 */
    const aiThinkAtMax = computed(() => {
      const count = Math.max(1, aiThinkLevelsFull.value.length);
      return count > 1 && aiThinkSliderValue.value >= count - 1;
    });
    /** 该画哪些"中间小圆点"的**下标列表**（本轮需求：刻度改圆点 + 最右全隐）。
       ⚠️⚠️ 为什么做成 computed 而不是在模板里 `v-for` + `v-if` 同一元素：
          Vue 3 里 **v-if 的优先级高于 v-for**，v-if 表达式**读不到** v-for 的循环变量
          （`li` 会是未定义 → 运行时报错、整块弹层画不出来）。
          过滤逻辑放在这里，模板只 `v-for="li in aiThinkNotches"`，一处判断、两处弹层共用。
       规则：
         · 只画中间档（下标 0 = 关/最低、n-1 = 满档，两端都不画：圆点本来就会压在最右）；
         · 单档（模型不支持思考）没有"中间" → 空数组，一个都不画；
         · 滑块停在**最右** → 空数组（用户原话「滑动条到最右处中间的小圆点全部隐藏」）。 */
    const aiThinkNotches = computed(() => {
      const count = aiThinkLevelsFull.value.length;
      if (count <= 2) return [];                       // 0/1 档没有中间点；2 档也只有两端
      if (aiThinkAtMax.value) return [];               // 推到最右：整排隐掉
      const out = [];
      for (let i = 1; i < count - 1; i += 1) out.push(i);
      return out;
    });
    /** 分段滑块的格数（下标 0..n-1；⚠️ 第 0 档**不一定是 off**，各家官方表说了算） */
    const aiThinkSliderMax = computed(() => Math.max(0, aiThinkLevelsFull.value.length - 1));
    const aiThinkSliderValue = computed(() => {
      const at = aiThinkLevels.value.indexOf(aiThinkingLevel.value);
      return at < 0 ? 0 : at;
    });
    /** 分段滑块头（纯白色正圆形，尺寸固定 18px，见 ai-fixes.css 的 .ai-think-seg-thumb）。
       ⚠️ 本轮需求（用户原话）：「圆点要在那个ui里面条的右侧尽头处 而不是在条的中央位置，
          还有如果是关闭状态ui这个圆应该在最左侧尽头处 条完全不露出来」——
          thumb 位置**不再取格子中心**，而是与填充条右端**完全重合**：
          left = 100% * at / (n - 1)（n<=1 → 0%）。
          配 CSS 的 `transform: translateX(-50%)` 后：at=0 → 圆心压轨道最左（圆贴左边缘），
          at=n-1 → 圆心压最右（圆贴右边缘）；中间档位圆心永远在填充条末端。
          ⚠️ 轨道左右各用 padding 9px（=圆半径）让出半圆位置（见 ai-fixes.css
             .ai-think-seg / .ai-think-seg-rail），0% / 100% 时圆不会露到控件外面。
          全部百分比表达，档数 N 变化（各家官方档位不同）时 CSS 不用改；
          平滑跟随靠 .ai-think-seg-thumb 的 transition。 */
    const aiThinkSegHeadStyle = computed(() => {
      const count = Math.max(1, aiThinkLevelsFull.value.length);
      const at = aiThinkSliderValue.value;
      /* 单档/不支持思考：本轮需求把这条改成"整条实心蓝、无粒子"（见 aiThinkFillStyle
         的注释），所以圆点也要跟着挪到**右端** —— 项目里一直有一条硬约束
         "圆永远压在填充条右端"（用户上一轮点名过），填充变成 100% 时圆停左边就破了。 */
      if (count <= 1) return { left: '100%' };
      return { left: 'calc(100% * ' + at + ' / ' + (count - 1) + ')' };
    });
    /** 进度填充条（蓝紫渐变 + 星光粒子，渐变/粒子在 CSS 里，这里只给几何）。
       本轮需求：**圆点永远压在填充条右端** → 宽度与 thumb 的 left 用**同一个公式**：
       width = 100% * at / (n - 1)，n<=1 → 0%。
       ⚠️ 旧写法是 (at + 1) / count（每档都留一格宽）：off 档也会露一格彩色，
          用户点名"关闭状态条完全不露出来"；而且圆会落在条中央而不是右端。
       ⚠️ 这就是"off 时圆在最左、条完全看不见"的几何来源：at=0 → 宽度 0%。 */
    const aiThinkFillStyle = computed(() => {
      const count = Math.max(1, aiThinkLevelsFull.value.length);
      const at = aiThinkSliderValue.value;
      /* ⚠️⚠️ 本轮需求（用户原话）：「模型选择ui的思考ui条为 1 段时里面要是这个里面的
         蓝色，其他颜色都不要了，还有粒子效果也消失。**其他除思考强度大于等级 1 的
         ui 状态不用更改**」。
         "只有 1 段" = 这家这个模型**没有可选档位**（官方表里只有 off 一档，
         或者干脆不支持思考）→ 整条 UI 只剩一个"状态灯"，没有可滑动的东西。
         旧写法这里给 `width: 0%`，于是那根条画成**空的灰轨**，
         而用户要的是"实心蓝色 = 这一档就是它的全部"，并且**不要蓝紫渐变、
         不要粒子**（`is-single` 类负责换色与关粒子，见 ai-fixes.css）。
         ⚠️ 只改 count<=1 这一支；count>1（正常多档）走下面原来的公式，一个字节都没动。 */
      if (count <= 1) return { width: '100%' };
      return { width: 'calc(100% * ' + at + ' / ' + (count - 1) + ')' };
    });
    /** 是否"只有一段"（不支持思考 / 官方只有 off 一档）—— 模板据此加 is-single 类 */
    const aiThinkIsSingle = computed(() => aiThinkLevelsFull.value.length <= 1);
    /** 星光粒子的速度/密度参数（纯 CSS 变量，绑在 .ai-think-seg 上）。
       ⚠️⚠️ 本轮按用户原话重写速度模型：
         「粒子效果速度要有一个固定值，然后每个模型有不同的速度值，
           假设如果有 4 个档位，那么（第）一个是最大速度除以 4，每个增加一个（快一档）时
           （就）增加一个（单位）的速度」
       翻成公式（SPARK_MAX_SPEED_S = 最右档那一轮固定时长，各家都一样）：
           速度档位 i（1 起）的"速度" = 满速 × i / n
           一轮时长 = 满速时长 ÷ 速度 = SPARK_MAX_SPEED_S × n / i
       ⇒ 满档（最右）= SPARK_MAX_SPEED_S（固定值）；4 档时第 1 档 = 4× 满速时长（=慢 4 倍），
          第 2 档 2×、第 3 档 4/3×；档数不同的模型（kimi 3 档 / DeepSeek 4 档）
          每档速度自然不同，正是"每个模型有不同的速度值"。
       另外两条本轮需求：
         · 「如果只有一节那么只有这个蓝色而且没有粒子」→ count<=1 时 density=0
           （单档 = 这个模型压根不支持思考，画粒子只会让人以为它在思考）；
         · 「粒子方向弄反了，应该是从右往左」→ 位移方向在 CSS keyframes 里翻。
       ⚠️ 不能把"关"写死成第 0 档：kimi-k3 系官方只有 low/high/max（根本没有 off），
          那种表的第一档是"低档思考"，必须照样给粒子。所以 off 判定看档位**值**。 */
    const SPARK_MAX_SPEED_S = 1.6;   // 最右档（满强度）一轮的固定时长，秒
    const aiThinkSparkStyle = computed(() => {
      const count = Math.max(1, aiThinkLevelsFull.value.length);
      const at = aiThinkSliderValue.value;
      const isOff = String(aiThinkingLevel.value || '').toLowerCase() === 'off';
      /* 单档 = 不支持思考：只有蓝色实心条，不画任何粒子（本轮需求） */
      if (count <= 1) {
        return { '--think-spark-speed': SPARK_MAX_SPEED_S.toFixed(2) + 's',
                 '--think-spark-density': '0' };
      }
      const speed = SPARK_MAX_SPEED_S * count / Math.max(1, at + 1);
      /* ⚠️⚠️ 本轮需求（用户原话）：「确保**所有**思考强度 ui 里面的粒子效果密度
         和**满级**思考强度的密集程度一致」。
         旧写法 `density = 0.35 + at * 0.22` 是"越高越密"（上一轮的需求），
         这一轮被明确推翻了：密度**不再跟着档位变**，一律取满级那一档的值 = 1。
         档位之间剩下的差异只有**速度**（上一条公式，用户没要求改）。
         ⚠️ 两个例外必须保留，否则观感立刻不对：
           · off 档（当前强度是"关"）→ 0 粒子：用户之前明确要求"关了就别流光"；
           · 只有一段（不支持思考）→ 0 粒子：本轮第一条需求。 */
      const density = isOff ? 0 : 1;
      return {
        '--think-spark-speed': speed.toFixed(2) + 's',
        '--think-spark-density': String(density),
      };
    });
    /** 每格中心的刻度点（档位刻度）：模板按 aiThinkLevelsFull 画就行，这里不用额外算 */
    /** 档位显示名 —— ⚠️ 本轮需求（用户点名）：必须显示各家**官方文档的英文档位名**
       （DeepSeek 的 off/low/high/max、OpenAI 的 minimal…、Kimi 的 low/high/max/on），
       绝不显示"关/低/中/高"这类本地化词，也绝不自己发明。
       所以顺序很简单：**后端 label 优先 → 没有 label 就用 value 本身**，
       两者都没有（旧后端连 thinking_levels 都没给）才退 'off'。
       ⚠️ 旧写法有个坑：`found.label !== found.value` 才用 label —— 而后端官方表里
          绝大多数档位就是 label==value（label 就是官方英文名本身），这个条件把它们
          全推给了 `t('ai_think_level_' + level)` 去查三语文案，
          一旦语言包里存在这种 key 就会显示中文（用户报的"强度名不是官方的"）。
          现在不做任何本地化查询。 */
    function aiThinkLevelText(level) {
      const found = aiThinkLevelsFull.value.find((l) => l.value === level);
      if (found && found.label) return String(found.label);
      if (found && found.value) return String(found.value);
      const text = String(level || '').trim();
      return text || 'off';
    }
    /** 点选/拖动分段滑块：立刻落盘（档位是持久设置，两端要同步）
       ⚠️ 用户明确不要"切换提示"：「切换思考强度ui弹出的切换提示为xxx不要了，
          我不需要弹出这个提示」→ 这里**只落盘，不 toast**（滑块圆点/填充条本身就是反馈）。
          语言包里那个 ai_think_level_toast 键保留不用（别的分支没引用它）。 */
    function setAiThinkingLevel(level) {
      const levels = aiThinkLevels.value;
      if (levels.indexOf(level) < 0) return;          // 不在当前模型档位表内（旧档位）：忽略
      if (level === aiThinkingLevel.value) return;
      /* ⚠️ 本轮：档位**按模型分别落盘**（用户原话「每个思考强度都有单独的存储等级几的强度」）。
         字典的**合并**放在后端 set_model_choice 里做（那里读的是磁盘上的表），
         避免两端同时在线时前端读-改-写整张表互相覆盖丢条目 —— 和 Key 分槽同一套纪律。
         这里先把本地值更新好（界面立刻反馈），再把 provider/model/档位一起交给后端。 */
      /* ★ 本轮：先把「档案 id」补齐再算键。
         ⚠️ 冷启动 / 刚进历史对话时 settings.ai_profile_id 可能还是空串（模型候选还没拉回来），
         这时算出来的键是旧格式 `厂商|模型`，写进去以后带 id 的键永远读不到它；
         后端那边更严重 —— set_model_choice **必须**带档案 id，缺了直接失败，
         档位只活在前端 ⇒ 用户看到的就是「开思考，新建/进历史对话又变回无思考」。
         所以：空 id 时按厂商从已拉到的分组里认领一条（认领结果写回 settings，
         让模型胶囊的显示也跟着正确），认领不到才退回旧格式键。 */
      let pid = currentAiProfileId();
      const prov = String(settings.ai_provider || '').trim().toLowerCase();
      const model = String(settings.model_name || '').trim();
      if (!pid && prov) {
        const host = (aiModelGroups.value || []).find((g) =>
          g && g.id && String(g.provider || '').toLowerCase() === prov);
        if (host) { pid = String(host.id); settings.ai_profile_id = pid; }
      }
      const mirrorKey = aiThinkMirrorKey(pid, prov, model);
      if (mirrorKey) {
        const store = Object.assign({}, (settings.ai_thinking_level
          && typeof settings.ai_thinking_level === 'object') ? settings.ai_thinking_level : {});
        /* ⚠️ 键必须带档案 id（见 aiThinkMirrorKey）：旧写法写 `provider|model`，
           同厂商两条档案列同一个模型名时互相覆盖 —— 正是用户本轮报的"相通的"。 */
        store[mirrorKey] = level;
        settings.ai_thinking_level = store;
        /* ★ 本轮：镜像表必须**落盘**（用户原话：「开思考新建对话或进入历史对话他会
           默认是无思考，就算你思考开着，必须刷新下状态才会调用思考」）。
           以前这里只写内存对象，换会话 / 重开程序就退回 off ——
           磁盘上那张表才是下次进会话能读到的东西。 */
        saveSetting('ai_thinking_level', store);
      }
      saveSetting('ai_thinking', level);
      /* ⚠️⚠️ 本轮修复我自己上一轮留下的回归（用户原话：「模型思考ui的思考组件出bug了，
         无法切换被锁定住了」）：这里原来写的是
             bridge.tryCall('ai.set_model_choice', currentAiProfileId(), provider, model, level)
         但 setup() 作用域里**从来没有** provider / model 这两个顶层变量
         （grep 核实：它们只在各函数内部作为局部量存在，见 aiPickModel / aiThinkMirrorKey）。
         → 一点滑块就 ReferenceError: provider is not defined，而且抛点位置极坏：
           `settings.ai_thinking_level = store`（本地已改）已经执行完，
           但 pointermove / pointerup 监听是在这句之后注册的 ⇒ 从没注册上，
           aiThinkDragging 被置上后再没人清 —— 用户看到的就是"滑块点不动 / 拖一半卡死"，
           而本地档位又已经改过一次，重试更乱。这就是"被锁定"的完整链路。
         → 参数从 settings 现取（mirror key 同源，见 aiThinkMirrorKey），不依赖任何
           外层同名变量；整段再包一层 try/catch：**任何异常都不许再打断滑块交互**。
           后端调用失败最多是档位没落盘（saveSetting 已经保住当前档），
           绝不能因为后端不可用就把 UI 冻住。 */
      try {
        bridge.tryCall('ai.set_model_choice', pid, prov, model, level)
          .then((res) => {
            /* 后端已经把档位记进它那张表了 —— 顺手校准一次本地：
               后端可能把别名/非法档归一成官方档（ai.py set_model_choice），
               界面显示的必须等于**真正会发给模型的**那一档。 */
            if (!res || !res.ok) return;
            const got = String(res.thinking || '').trim() || level;
            if (got === level || aiThinkLevels.value.indexOf(got) < 0) return;
            const fix = Object.assign({}, settings.ai_thinking_level || {});
            fix[mirrorKey] = got;
            saveSetting('ai_thinking_level', fix);
            saveSetting('ai_thinking', got);
          })
          .catch(() => { /* 后端没这个接口：上面的 saveSetting 已经保住"当前档" */ });
      } catch (error) {
        /* 兜底给取证用：模块级没有 toast（它在 setup 里），console + 后端日志双落，
           下次这类"点不动"的问题能直接从日志定位。 */
        console.error('[GCP-AI] 保存思考档位失败:', error);
      }
    }
    /** 让「思考档位」回到后端**真正生效**的那一档 —— 新对话 / 进历史对话 / 冷启动各调一次
       ⚠️ 用户原话：「chat或agent开思考新建对话或进入历史对话他会默认是无思考，
          就算你思考开着，必须刷新下状态才会调用思考」。
       根因有两半，缺一不可：
         ① 换会话（新建 / 进历史）时代码**从没重拉过**模型候选 —— 档位表和档案 id
            停在旧会话那一刻（冷启动时甚至还是空的），滑块只能画成「无思考」；
         ② 本地镜像里这条「档案×模型」存过的档位，可能因为那次 set_model_choice
            缺档案 id 失败而没进后端 —— 这时要以**用户拨过的**为准推回后端，
            绝不能反过来把用户的选择降级成 off。
       顺序：重拉候选 → 有本地合法档就先推给后端（推不上去也保持本地）→
       没有本地档才认后端那一档并写回镜像表。整段失败只记日志，不阻断界面。 */
    async function refreshAiThinking() {
      try {
        await loadAiModelChoices();
        const levels = aiThinkLevels.value;
        if (!levels || !levels.length) return;
        const local = aiThinkStoredLevel();
        const localOk = (local && levels.indexOf(local) >= 0) ? local : '';
        const raw = aiThinkBackendLevel();
        const backend = (raw && levels.indexOf(raw) >= 0) ? raw : normalizeAiThinking(raw);
        if (localOk) {
          /* 用户拨过且合法 → 用户意图优先，顺便自愈「那次没进后端」的档位 */
          if (localOk === backend) return;
          const pid = currentAiProfileId();
          const prov = String(settings.ai_provider || '').trim().toLowerCase();
          const model = String(settings.model_name || '').trim();
          if (pid && prov && model) {
            const res = await bridge.tryCall('ai.set_model_choice', pid, prov, model, localOk)
              .catch(() => null);
            if (res && res.ok) return;
          }
          return;                       // 推不上去也保持用户本地选择，绝不擅自降级
        }
        /* 没有本地档（新装 / 新模型 / 首次进这个历史会话）→ 认后端那一档 */
        const want = backend || levels[0] || 'off';
        const key = aiThinkMirrorKey();
        if (key) {
          const store = Object.assign({}, (settings.ai_thinking_level
            && typeof settings.ai_thinking_level === 'object') ? settings.ai_thinking_level : {});
          if (String(store[key] || '') !== want) {
            store[key] = want;
            await saveSetting('ai_thinking_level', store);
          }
        }
        if (String(settings.ai_thinking || '') !== want) await saveSetting('ai_thinking', want);
      } catch (error) {
        console.warn('[GCP-AI] 同步思考档位失败:', error);
      }
    }
    /** 分段滑块按下：第 n 格 → 该格档位（跟手，按下即生效） */
    function aiThinkSegPick(index) {
      const level = aiThinkLevels.value[Math.max(0, Math.min(aiThinkLevels.value.length - 1, Number(index) || 0))];
      if (level) setAiThinkingLevel(level);
    }
    /* 拖动分段滑块（Codex 风格：按住滑，档位跟着指针所过的格子走）。
       ⚠️ 只在 aiThinkSupported（>=2 档）时启动；用 window 级 move/up，
          指针滑出弹层也继续跟手，松手才落定 —— 和原生 range 的体验对齐。 */
    let aiThinkDragging = null;   // { rail, lastAt }
    function aiThinkSegDown(event) {
      if (!aiThinkSupported.value) return;
      const rail = event.currentTarget;
      if (!rail || !rail.getBoundingClientRect) return;
      event.preventDefault();                      // 防止拖字选中 / 抢焦点
      const move = (e) => {
        if (!aiThinkDragging) return;
        const next = aiThinkSegPointer(e, aiThinkDragging.rail);
        if (next >= 0 && next !== aiThinkDragging.lastAt) {
          aiThinkDragging.lastAt = next;
          aiThinkSegPick(next);
        }
      };
      const up = () => {
        aiThinkDragging = null;
        window.removeEventListener('pointermove', move, true);
        window.removeEventListener('pointerup', up, true);
        window.removeEventListener('pointercancel', up, true);
      };
      /* ⚠️⚠️ 本轮修滑块"被锁定"的第二层（第一层是 setAiThinkingLevel 的 ReferenceError）：
         旧写法把**首次 aiThinkSegPick 放在注册监听之前**。首次 pick 里任何异常都会让
         `window.addEventListener(...)` 三行整段不执行，而 `aiThinkDragging` 已经被置上
         → 状态机永久泄漏：之后每次 pointerdown 都因残留状态错乱、每次 pick 都"没反应"，
         表现就是用户说的"无法切换，被锁定住了"。
         → 现在：先注册监听再首次 pick，并把首次 pick 包进 try/finally ——
           成功：正常跟手；失败：立刻复位并摘掉监听，**滑块下一下点击照样能用**，
           绝不会因为一次异常把整个控件永久冻死。 */
      window.addEventListener('pointermove', move, true);
      window.addEventListener('pointerup', up, true);
      window.addEventListener('pointercancel', up, true);
      try {
        const at = aiThinkSegPointer(event, rail);
        if (at >= 0) { aiThinkDragging = { rail, lastAt: at }; aiThinkSegPick(at); }
        else { aiThinkDragging = { rail, lastAt: -1 }; }
      } catch (error) {
        console.error('[GCP-AI] 思考档位首次选择失败（已复位，可继续操作）:', error);
        up();
      }
    }
    /** 拖动中：按指针 x 相对轨道的位置算落在**最近的档位点**
       ⚠️ 本轮几何变了：档位点不再是"每格中心"，而是均匀分布的点 i/(n-1)
          （第 0 档在最左、第 n-1 档在最右，圆点/填充条都用这套坐标）。
          所以映射也必须跟着改：**四舍五入 ratio*(n-1)** 才是"离指针最近的那一档"；
          旧写法 floor(ratio*n) 是"指针落在第几格"的格模型 —— 和圆点错位一档（n=4 时
          指针压着 33% 的 low 圆点，floor 会算到 1 → 刚好对；但指针在 60% 时 floor*4=2，
          而 high 的点在 66.7%，手感上"还没到就跳"，与视觉不一致）。 */
    function aiThinkSegPointer(event, railEl) {
      if (!railEl || !railEl.getBoundingClientRect) return -1;
      const rect = railEl.getBoundingClientRect();
      if (rect.width <= 0) return -1;
      const count = aiThinkLevelsFull.value.length;
      if (count <= 1) return 0;
      const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
      return Math.max(0, Math.min(count - 1, Math.round(ratio * (count - 1))));
    }
    /** 键盘 ←/→：在档位表里前后挪一格
       ⚠️ 表是各家官方的，**第一档不一定是 off**（kimi-k3 系只有 low/high/max）；
          Home 就是"表内最低档"，不是"关"。 */
    function aiThinkSegKeydown(event) {
      if (!aiThinkSupported.value) return;
      let at = aiThinkSliderValue.value;
      if (event.key === 'ArrowRight' || event.key === 'ArrowUp') at = Math.min(aiThinkSliderMax.value, at + 1);
      else if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') at = Math.max(0, at - 1);
      else if (event.key === 'Home') at = 0;
      else if (event.key === 'End') at = aiThinkSliderMax.value;
      else return;
      event.preventDefault();
      event.stopPropagation();
      aiThinkSegPick(at);
    }
    /** 选中态判定（本轮：同厂商两条档案必须**互相独立**）
       ⚠️ 不能只比模型名：两条 DeepSeek 档案都列了 DeepSeek-V4.1-Flash 时，
          只比名字会让两边同时打勾（用户报的"2个同时切换、同时改变切换状态"）。
          必须比 **档案 id + 模型名** 这一整对；后端 model_choices 每个 group 都带 id，
          当前选中的档案 id 存在 settings.ai_profile_id（见 ai.set_model_choice）。
       ⚠️ 老数据/旧后端没有 ai_profile_id：退回"厂商 + 模型名"的旧口径，
          同时只认**第一条**匹配该厂商的分组（避免两组同时亮）。 */
    function aiModelIsOn(group, model) {
      if (!model) return false;
      const name = String(settings.model_name || '');
      if (String(model.name || '') !== name) return false;
      const gid = String((group && group.id) || '');
      const cur = String(settings.ai_profile_id || '');
      if (gid && cur) return gid === cur;
      /* 没有档案 id 可比：按厂商匹配，并且只点亮该厂商的第一条分组 */
      const firstOfProvider = (aiModelGroups.value || []).find(
        (g) => String(g.provider || '').toLowerCase() === String((group && group.provider) || '').toLowerCase());
      return !!firstOfProvider && firstOfProvider === group
        && String(group && group.provider || '').toLowerCase() === String(settings.ai_provider || '').toLowerCase();
    }
    /** 当前选中的档案 id（没存过时按 厂商+模型名 反查分组，兜底空串） */
    function currentAiProfileId() {
      const cur = String(settings.ai_profile_id || '');
      if (cur) return cur;
      const hit = (aiModelGroups.value || []).find((g) => aiModelIsOn(g, { name: settings.model_name }));
      return String((hit && hit.id) || '');
    }
    /* 点某个模型：写 model_name + ai_provider（本轮起还要带上**档案 id**，见下面）。
       ⚠️ 需求（用户原话）：「点击模型选择选择一个模型后不应该关闭ui界面」——
          旧写法一选就 `aiModelOpen.value = false`，用户想顺便把下面的思考档位也调一下
          就得重新点开弹层。现在**保持打开**：选完模型档位表就地跟着变，
          关闭只由"点弹层外部 / Esc / 再点胶囊"决定。
       ⚠️ 本轮变化：**不再无条件把 ai_thinking 写回 off** —— 档位按模型分别记忆
          （见 aiThinkStoredLevel / ai.set_model_choice），
          避免每次换模型都多写一次盘、也不会把别的模型的档位冲掉。 */
    function aiPickModel(group, model) {
      if (!group || !model) return;
      if (aiModelIsOn(group, model)) return;
      const provider = String(group.provider || '');
      /* ⚠️ 本轮：切模型 = 切**档案**。旧写法只写 model_name / ai_provider，
         同厂商两条档案后端永远只认数组里靠前那条（active_profile 按顺序推），
         于是"点第二条那组的模型"实际没换档案 —— Key、地址、token 上限全都还是
         另一条的，界面上两组勾选却一起变。现在把档案 id 一起交给后端。 */
      settings.ai_profile_id = String(group.id || '');
      settings.ai_provider = provider;
      settings.model_name = String(model.name || '');
      bridge.tryCall('ai.set_model_choice', String(group.id || ''), provider,
        String(model.name || ''), '').then((result) => {
        if (!result) {
          /* 后端没有这个接口（旧版本）：不能只提示一句就完事 —— 那样
             model_name / ai_provider 只改了内存，重启就回到旧模型，用户看着像"没生效"。
             显式降级到旧的两条 settings.set（档案 id 存不了，但至少选中的模型会落盘）。
             见 AGENTS.md 第 3 节："tryCall 返回 null 时调用方必须显式降级"。 */
          needApi('ai.set_model_choice', t('ai_model_pick', '选择模型'));
          saveSetting('model_name', String(model.name || ''));
          saveSetting('ai_provider', provider);
          return;
        }
        if (!result.ok) { toast(result.error || t('save_failed', '保存失败'), 'error'); return; }
        /* 后端可能把档位就近修正过（各家档位表不同）→ 以返回值为准刷新界面 */
        if (result.thinking) settings.ai_thinking = result.thinking;
      }).catch(() => needApi('ai.set_model_choice', t('ai_model_pick', '选择模型')));
      /* 新模型的档位表（直接按这台 model 算，不等 watch 重拉）。
         ⚠️⚠️ 本轮修掉一个"看着像没反应"的错配：旧写法拿 `stored`
            （= **上一个**模型的档位）去对新模型的档位表，命不中就把
            `nextLevels[0]` 写进设置。后果有两个：
              ① 用户从没设过的新模型被凭空写出一条记录 → "没设过"和"设成 off"
                 再也区分不开，同厂商再加档案时又会带上这个值（用户报的"相通"）；
              ② 写入用的还是**厂商级旧键** `provider|model`（和后端
                 `profiles.thinking_key` 的 `档案id|provider|model` 不一致）
                 → 同厂商两条档案串档。
            现在：档位只认**这台模型自己**的记录 —— 优先后端给的 `model.thinking`
            （后端按 档案id|厂商|模型 查表，没记录就是 off），其次这台自己的镜像键；
            这台确实存过一个"不在自己档位表里"的值时才纠正，且用**带档案 id 的键**写。 */
      const nextLevels = (Array.isArray(model.thinking_levels) && model.thinking_levels.length)
        ? model.thinking_levels.filter((l) => l && l.value).map((l) => String(l.value))
        : (model.supports_thinking ? AI_THINK_LEVELS : ['off']);
      const targetId = String(group.id || '');
      const targetKey = aiThinkMirrorKey(targetId, provider, String(model.name || ''));
      const targetStore = (settings.ai_thinking_level
        && typeof settings.ai_thinking_level === 'object') ? settings.ai_thinking_level : {};
      const ownLevel = String(
        (model.thinking != null && String(model.thinking).trim())
          || (targetKey && targetStore[targetKey] != null ? String(targetStore[targetKey]) : '')
      ).trim();
      if (ownLevel && nextLevels.indexOf(ownLevel) < 0) {
        const level = nextLevels[0] || 'off';
        settings.ai_thinking = level;
        if (targetKey) {
          const store = Object.assign({}, targetStore);
          store[targetKey] = level;
          settings.ai_thinking_level = store;
        }
      }
      /* ⚠️ 本轮需求（用户原话）：「聊天框切换模型不要弹提示」→ 不弹 toast。 */
    }
    function toggleAiModelMenu() {
      if (!aiModelVisible.value) return;
      aiModelOpen.value = !aiModelOpen.value;
      /* 和对话模式弹层互斥（两个都开就叠在一起了） */
      if (aiModelOpen.value) aiModeOpen.value = false;
      if (aiModelOpen.value && !(aiModelGroups.value || []).length) loadAiModelChoices();
    }
    /** 服务商分组名（本轮多语言修复）
     *  ⚠️ 后端 `ai.model_choices()` 返回的 `group.label` 是 **Python 侧写死的简体中文**
     *     （modules/pymodels/core/ai/providers.py 的 PROVIDERS[].label），
     *     前端原来直接渲染 → 切到 English / 繁體中文 后，模型弹层的分组标题
     *     仍然是"DeepSeek（深度求索）"这类简体文案
     *     （用户本轮报的「语言切换为其他语言部分地方还是只有简体中文文本内容，包括各种地方」）。
     *     语言包里**早就有三语**的 `ai_provider_<id>`（设置页那个服务商下拉一直在用），
     *     所以按 id 取当前语言，取不到才退回后端给的 label —— 绝不显示空字符串。
     *     ⚠️ 不改后端那份 label：它是"跨语言的默认兜底名"，翻译归前端 t()，
     *        和设置页同一口径，避免后端/前端各维护一张表以后对不上。 */
    function aiProviderLabel(group) {
      const id = String((group && group.provider) || '');
      const fallback = String((group && group.label) || id || '');
      if (!id) return fallback;
      return t('ai_provider_' + id, fallback) || fallback;
    }

    /* 一个都没配 Key：胶囊显示引导，点开只给一句"去设置里填 Key"
       ⚠️ 本轮需求：这个状态还决定**思考区画不画** —— 用户「未填写任何APIkey时
          模型展开ui后里面不应该有思考ui组件」（弹层里只剩一句引导文字，
          灰滑块没有任何可选项，画出来只是噪音）。有 Key 但模型不支持思考
          才走"禁用占位"那条路。见 index.html 两处弹层的 `v-if="!aiModelNoKey"`。 */
    const aiModelNoKey = computed(() => aiModelHasApi.value
      && (aiModelGroups.value || []).length === 0);

    /* =====================================================================
     * · 主动输入「@」弹资源候选（和 /plugin 提示同一套交互）
     * =====================================================================
     * 需求原话：「主动输入"@"可以像"/plugin"这样出来类似的提示，可以选择，顺序从小到大
     *             从上往下排序，可以滚动这个ui选择」。
     * 规则：草稿**末尾**是 `@` 或 `@一段还没写完的名字/编码`（后面没有空格、没有右括号）
     *       才弹；选中后把这段 "@查询词" 删掉，换成富文本 token（蓝字下划线可点击）。
     * ⚠️ 排序按 code 升序（TG-000001 → TG-000052），从上往下 = 从小到大（需求原话）。 */
    const aiAtQuery = ref('');
    const aiAtOpen = ref(false);
    const aiAtPicked = ref(0);
    const AI_AT_RE = /(?:^|\s)@([^\s@()]{0,30})$/;
    const aiAtCandidates = computed(() => {
      if (!aiAtOpen.value) return [];
      const q = aiAtQuery.value.toLowerCase();
      const list = [];
      const source = items.value && items.value.length ? items.value : [];
      for (const it of source) {
        if (!it || !it.code) continue;
        const name = String(it.name || '');
        if (q && name.toLowerCase().indexOf(q) < 0
          && String(it.code).toLowerCase().indexOf(q) < 0) continue;
        list.push(it);
        if (list.length >= 60) break;
      }
      list.sort((a, b) => String(a.code).localeCompare(String(b.code)));
      return list;
    });
    /** 从草稿里认出 "@查询词"（输入 / 粘贴 / 程序赋值都走这里，同一份判定） */
    function syncAiAtPopup() {
      const raw = String(aiDraft.value || '');
      const hit = AI_AT_RE.exec(raw);
      if (!hit) { aiAtOpen.value = false; aiAtQuery.value = ''; return; }
      aiAtQuery.value = hit[1] || '';
      aiAtOpen.value = true;
      aiAtPicked.value = 0;
    }
    function closeAiAt() { aiAtOpen.value = false; aiAtQuery.value = ''; }
    /** 选中一条：删掉 "@查询词" → 插入 token（rich-ai-input 的 insertMention） */
    async function applyAiAt(item) {
      if (!item) return;
      const raw = String(aiDraft.value || '');
      const hit = AI_AT_RE.exec(raw);
      const cut = hit ? hit[1].length + 1 : 0;          // "@query" 整段长度
      const next = cut ? raw.slice(0, raw.length - cut) : raw;
      closeAiAt();
      setAiDraftProgrammatically(next);
      await nextTick();
      const target = settings.ai_sidebar_mode ? aiInputPageRef.value : aiInputDrawerRef.value;
      if (target && typeof target.insertMention === 'function') {
        target.insertMention({ name: item.name || '', code: item.code || '',
          text: '@' + (item.name || '') + '(' + (item.code || '') + ')' });
      } else {
        setAiDraftProgrammatically(next + '@' + (item.name || '') + '(' + (item.code || '') + ') ');
      }
      nextTick(() => {
        const el = settings.ai_sidebar_mode ? aiInputPageRef.value : aiInputDrawerRef.value;
        if (el && typeof el.focus === 'function') el.focus();
      });
    }
    /** 候选列表的键盘操作（在输入行的 keydown 捕获里调）：返回 true = 已消费 */
    function aiAtKeydown(event) {
      if (!aiAtOpen.value || !aiAtCandidates.value.length) {
        if (aiAtOpen.value && event.key === 'Escape') { closeAiAt(); return true; }
        return false;
      }
      const count = aiAtCandidates.value.length;
      if (event.key === 'ArrowDown') {
        event.preventDefault(); event.stopPropagation();
        aiAtPicked.value = (aiAtPicked.value + 1) % count;
        scrollAiAtItem();
        return true;
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault(); event.stopPropagation();
        aiAtPicked.value = (aiAtPicked.value - 1 + count) % count;
        scrollAiAtItem();
        return true;
      }
      if (event.key === 'Enter' || event.key === 'Tab') {
        event.preventDefault(); event.stopPropagation();
        applyAiAt(aiAtCandidates.value[aiAtPicked.value]);
        return true;
      }
      if (event.key === 'Escape') {
        event.preventDefault(); event.stopPropagation();
        closeAiAt();
        return true;
      }
      return false;
    }
    /** 高亮项滚进可视区（列表最多 8 行高，选到第 20 条不能看不见） */
    function scrollAiAtItem() {
      nextTick(() => {
        const box = document.querySelector('.ai-at-list');
        if (!box) return;
        const el = box.querySelector('.ai-at-item.is-on');
        if (el && el.scrollIntoView) {
          try { el.scrollIntoView({ block: 'nearest' }); } catch (e) { /* 老内核 */ }
        }
      });
    }
    watch(aiDraft, () => { syncAiAtPopup(); });

    /* 插件制作辅助 / AI 开关变化、界面语言切换都要重新取一遍提示词 */
    watch([() => settings.gcp_plugin_maker_enabled, () => settings.ai_enabled, () => I18N.version],
      () => { loadAiHints(); });
    /* 服务商 / Key 配置状态变了 → 模型候选要重新取（"未填 Key 的服务商不显示"） */
    /* 服务商 / 模型 / Key 配置状态变了 → 模型候选与**思考档位表**要重新取
       （"未填 Key 的服务商不显示" 由后端过滤；不同模型支持的档位不同）。
       ⚠️ 本轮修复"在 GCP-AI 设置里改了模型/思考，输入框那边并没有立即变化"：
          以前只 watch 了 ai_provider + apiKeyConfigured，**漏了 model_name** ——
          而设置页那个「模型选择」下拉框改的正是 model_name，所以档位表
          （thinking_levels）一直停在旧模型的，滑块看着没反应。 */
    watch([() => settings.ai_provider, () => settings.model_name, () => apiKeyConfigured],
      () => { loadAiModelChoices(); });
    async function aiNewChat() {
      /* ★ 本轮（统计）：新对话 = 新账本 */
      aiResetStats();
      rememberAiScroll();                       // 先把旧会话的位置存起来（任务 3）
      const result = await bridge.tryCall('ai.new_session');
      aiSessionId.value = (result && result.ok && result.session && result.session.id) || '';
      aiMessages.value = [];
      aiHistoryOpen.value = false;
      /* 新对话 = 旧的下标/旧流全部作废（和 loadAiSession 同一套清理） */
      cancelAiEdit();
      clearStreamBubble();
      /* ⚠️⚠️ 修用户报的「我切换历史或者新建对话这个调用工具的ui一直在这个界面里」：
         步骤卡片是**上一个会话的执行过程**，换会话必须清掉，否则它会一直挂在新界面。
         （它本来就不该跨会话残留 —— 它描述的是"上一次 AI 干了什么"。） */
      resetAgentSteps();
      aiAgentStepsOpen.value = true;
      aiAgentStepsTouched = false;
      aiStickBottom.value = true;               // 空会话当然贴底
      focusAiInput();
      /* ★ 本轮修复（用户原话：「开思考新建对话…他会默认是无思考，必须刷新下状态
         才会调用思考」）：新对话必须重新对一次档位 —— 换会话时档案 id / 档位表
         可能还停在上一刻（甚至空），不同步就会显示成无思考。 */
      refreshAiThinking();
    }
    async function clearAiHistory() {
      /* 需求：点清除要**二次确认**，不能直接删；而且删完要**立刻**把下面的列表清空
         （旧实现只清了 localStorage，列表要重新进一次才刷新）。 */
      const yes = await openDialog({ title: t('ai_clear_history', '清空历史对话'),
        danger: true,
        body: t('ai_clear_history_body', '会删除全部历史对话（每个对话一个记录），删除后无法恢复。确定要清空吗？'),
        confirmText: t('clear', '清空') });
      if (!yes) return;
      const result = await bridge.tryCall('ai.clear');
      if (!result) return needApi('ai.clear', '清空历史对话');
      if (!result.ok) { toast(result.error || t('clear_failed', '清空失败'), 'error'); return; }
      /* 立刻清空本地列表 + 重新拉一次（双保险：列表马上就是空的） */
      aiHistoryList.value = [];
      aiSessionId.value = '';
      aiMessages.value = [];
      await loadAiSessions();
      toast(t('ai_history_cleared', '历史对话已清空') + '（' + (result.cleared || 0) + '）', 'success');
    }
    function aiStop() {
      /* 两种"停止"：
         ① 流式（新）：告诉后端 cancel_stream，读流线程会尽快收尾并推一个 cancelled 事件，
            **已经打出来的那半段会落盘**（用户看到的字不会凭空消失）；
         ② 同步（旧后端 / 关掉流式）：请求已经在后端阻塞跑着，这里只能"停止等待"，
            之后回来的结果被丢弃（回答本身可能已经落盘，历史里还能看到 —— 如实说明）。 */
      if (aiStreamId) {
        const id = aiStreamId;
        bridge.tryCall('ai.cancel_stream', id).catch(() => {});
      }
      aiAborted = true;
      aiBusy.value = false;
      aiPending.value = false;
      toast(t('ai_stop_hint', '已停止等待回答（服务端可能仍在生成）'), 'info');
    }
    /* 重新生成：这条 AI 回答**不删**，新回答作为它的第二个版本（气泡上出现 ◀ 1/2 ▶）。
       ⚠️ 必须把"这条回答的绝对下标"交给后端：切过分支之后下标会变，
          所以只能用**当前** aiMessages 里的 index，不能缓存旧值。
       ⚠️ pendingAfter = 同一个 index：需求「点击重新生成回复应该在聊天气泡**原有位置**上
          出现正在xxx的聊天气泡」。
          旧行为是"进度气泡/逐字文本一律挂在整段最末尾"，于是（用户原话的场景）
          点上面那条回答的重新生成 → 进度气泡跑到**下面那条回答的空白位**闪一下又消失，
          界面上看起来就是"下面那条回答被搬到了最新版本里"。
          就地写只替换**这一颗气泡**的正文：它下面那些消息（属于别的轮次）原样不动，
          和后端落盘的结果（只给这一格加版本、后面的消息不搬家）完全一致。
       ⚠️ assistantIndex 一定要给准：后端拿不到下标时会**退回"最后一条 assistant"**，
          那样翻版就翻到别人身上了（所以我们**永远**按用户点的那条传下标）。 */
    async function aiRegenerate(index) {
      if (aiBusy.value) return;
      const list = aiMessages.value;
      let userText = '';
      for (let i = index; i >= 0; i -= 1) {
        if (list[i] && list[i].role === 'user') { userText = list[i].text; break; }
      }
      if (!userText) return;
      cancelAiEdit();                          // 正在编辑的那条要收掉（下标会漂）
      /* cutAfter = 同一个下标：**点击这一刻**就把这条下面的旧分支内容藏起来
         （那些属于旧版本，后端要到落盘时才真挪走）。用户报的"下面所有内容属于所有版、
         全都不消失"就是缺了这一下。 */
      await aiSend(userText, {
        resend: true, assistantIndex: index, pendingAfter: index, cutAfter: index,
      });
    }
    /* ---------- 气泡版本导航 ◀ n/m ▶ ----------
       翻版本 = 让后端改会话并**返回整个 session**，前端整体重建气泡：
       · AI 气泡翻页只换这一条回答；
       · 用户气泡翻页 = 换整条分支（它下面挂的 AI 回复整段都换、后面的下标全漂）。
       所以这里绝不"只更新那一条"，一律用返回的 messages 重建 —— 只拿增量拼必然画歪。 */
    async function aiSwitchVariant(index, target) {
      if (!aiCanSwitchVariant()) return;
      const list = aiMessages.value;
      const current = list[index];
      if (!current) return;
      const count = aiVariantCount(current);
      const next = Math.min(count, Math.max(1, target));
      if (next === aiVariantPage(current)) return;
      const result = await bridge.tryCall('ai.switch_variant', aiSessionId.value || '',
        index, next - 1);                        // 前端 1 基显示，后端 0 基存储
      if (!result) return needApi('ai.switch_variant', '切换版本');
      if (!result.ok) {
        /* 下标失效（并发改过会话）：重新拉一次这份对话，让用户对着最新的一条再翻 */
        toast(result.error || t('ai_variant_stale', '这条对话刚刚变过，已重新载入'), 'error');
        await loadAiSession(aiSessionId.value);
        return;
      }
      cancelAiEdit();
      clearStreamBubble();
      /* ⚠️ 本轮：翻版本**保持当前位置**（需求原话"每次页面都会自动到最底部bug
         而不是保留在当前位置"）。锚点必须在改 aiMessages **之前**取，
         取的是"被翻那条气泡"相对滚动容器的位置。 */
      const anchor = captureAiAnchor(index);
      if (result.session_id) aiSessionId.value = result.session_id;
      aiMessages.value = sessionToMessages(result.session);
      nextTick(() => restoreAiAnchor(anchor));
    }
    /* ---------- 用户消息原地编辑（✓ 保存并发送 / ✕ 取消） ----------
       ⚠️ "尺寸保持"的做法：编辑框复用**同一个 .bubble 类**（见 ai-fixes.css 的
          .ai-bubble-edit：不覆盖 max-width / font-size / line-height / padding），
          所以点编辑不会突然缩小或跳位。
       ⚠️ ✓ = 把这句作为该用户消息的**新版本**发出去（后端会把它旧的那串回复
          存进 branch_suffixes[旧版本]，翻回旧版本还看得见）。 */
    function aiStartEdit(index) {
      if (aiBusy.value) return;
      const message = aiMessages.value[index];
      if (!message || message.role !== 'user') return;
      clearStreamBubble();
      /* ⚠️⚠️ 本轮**不再由 JS 计算宽高**（旧写法用 canvas 量字宽 + 内联 px 钉死，
         结果就是用户报的「编辑模式这个聊天气泡 ui 长度就固定了，他不会继续变长了，
         就维持文本原本有多长」—— 只要内联写了 width，打字再多人家也不会长）。
         尺寸全部交给 CSS 的 `field-sizing: content` + `max-width: 78%`
         （见 ai-fixes.css `.bubble.ai-bubble-edit`，那里写了完整的取舍说明）。
         这里只留一件 CSS 做不到的事：**进入编辑瞬间别塌成一条线**——
         把展示态那颗气泡的实测高度当 min-height 垫一下。 */
      const bubble = document.querySelector('.bubble[data-i="' + index + '"]');
      aiEditBox.value = { width: 0, height: bubble ? Math.round(bubble.getBoundingClientRect().height) : 0 };
      aiEditingIndex.value = index;
      aiEditDraft.value = String(message.text || '');
      nextTick(() => {
        const el = document.querySelector('.ai-bubble-edit');
        if (!el) return;
        /* 浏览器不支持 field-sizing 时，进入编辑这一刻就要按内容量一次
           （不然它顶着重置前的旧内联宽度，用户看到的还是"固定长条"）。
           量之前先把 :style 那份 min-height 垫值留着即可 —— aiEditBoxAutoGrow
           自己会写 width/height 到元素上，不经过 aiEditBox。 */
        if (!aiFieldSizingSupported()) aiEditBoxAutoGrow();
        /* 支持的那条路由排版引擎负责，这里只校准"别比展示态矮"那个垫值。 */
        const real = Math.round(el.getBoundingClientRect().height);
        const seed = aiEditBox.value.height || 0;
        if (seed && real && real < seed) {
          aiEditBox.value = { width: 0, height: seed };
        }
        el.focus();
        el.setSelectionRange(el.value.length, el.value.length);
      });
    }
    /** 打字时的"持续自适应"由 CSS 的 field-sizing: content 负责。
       ⚠️ 保留这个空函数与模板上的 @input 绑定，是为了**明确记录这里不该写代码**：
           旧版在这里用 canvas 重算宽度并写进内联 style，那一套每一环都脆弱
           （v-model 与本监听的先后顺序不保证、getComputedStyle().font 在
           Chromium 里对分写字体返回空串导致量出来偏小），而且只要写了内联宽度，
           框就永远固定 —— 正是本轮用户报的现象。 */
    /** 打字时的尺寸自适应：**优先交给 CSS 的 `field-sizing: content`**。
       ⚠️ 但这条能力是 Chromium 123+ 才有（WebView2 Evergreen 一般都有，
           可**不能假设**：企业机器可能停在较旧的 Runtime）。
           一旦不支持，`width: auto` 的 textarea 会退回默认的约 20 列、
           而且**永远不会变长** —— 又变成本轮用户报的那个 bug。
           所以这里做一次特性检测：支持就什么都不做（最省事也最准），
           不支持就自己按内容长宽（用 scrollWidth/scrollHeight，
           这是浏览器**已经排好版**的真实值，不需要 canvas 量字宽，
           也就不会踩旧版那些坑：字体简写取不到值、v-model 与本监听的先后顺序）。 */
    let aiFieldSizingOk = null;
    function aiFieldSizingSupported() {
      if (aiFieldSizingOk !== null) return aiFieldSizingOk;
      try {
        aiFieldSizingOk = !!(window.CSS && CSS.supports && CSS.supports('field-sizing', 'content'));
      } catch (e) { aiFieldSizingOk = false; }
      return aiFieldSizingOk;
    }
    function aiEditBoxAutoGrow() {
      if (aiEditingIndex.value < 0) return;
      if (aiFieldSizingSupported()) return;     // 浏览器自己会长，别多此一举去钉尺寸
      const el = document.querySelector('.ai-bubble-edit');
      if (!el) return;
      /* 先放窄再量：直接读 scrollWidth 量到的是"上一次那个宽度"，
         因为 textarea 已经按内容撑开了 —— 必须先让它回落到最窄。
         ⚠️ 宽度按内容量完后要**夹到 max-width**（CSS 里是 78%），
            超出就该由换行负责，不能把框撑出容器。 */
      el.style.width = '0px';
      el.style.height = '0px';
      const pad = 4;
      const host = document.querySelector('.ai-messages');
      const cap = host ? Math.round((host.clientWidth - 32) * 0.78) : 99999;
      const want = el.scrollWidth + pad;
      const width = Math.min(cap, Math.max(32, want));
      el.style.width = width + 'px';
      /* 宽度定了之后高度才能量准（换行结果取决于最终宽度），所以要**分两步**。 */
      el.style.height = 'auto';
      const height = Math.min(Math.round(window.innerHeight * 0.4), el.scrollHeight + pad);
      el.style.height = Math.max(24, height) + 'px';
    }
    function aiCancelEdit() { cancelAiEdit(); }
    async function aiAcceptEdit(index) {
      if (aiBusy.value) return;
      const text = String(aiEditDraft.value || '').trim();
      if (!text) { toast(t('ai_edit_empty', '消息不能是空的'), 'info'); return; }
      const original = aiMessages.value[index];
      cancelAiEdit();
      /* ⚠️ 本轮需求（用户原话）：「当用户点击编辑直接未修改点对勾还是应该直接发送
         而不是视为取消」。旧写法这里有一句"文本没变就 return"，
         等于把"原样确认"当成取消 —— 用户的语义是"我要重新问一遍这句"，
         走 resend 正好生成一个新版本（版本树本来就有这个能力），不该拦。
         ⚠️ 只删这一个早退，上面的空文本校验（不能发空）保留。 */
      /* cutAfter = 这条用户消息的下标：编辑重发会换整条分支，它下面那串（旧版本的后继）
         要在**点击这一刻**就先让位 —— 与重新生成同一口径（用户说"用户的编辑也一样"）。 */
      await aiSend(text, { resend: true, userIndex: index, cutAfter: index });
    }
    function aiBubbleCopied(text) { return isCopied(text); }
    /* 说话（aiSend）：把消息交给桌面端 ai.send / ai.send_stream，
       由后端组装提示词 / 调接口 / 落盘（**一律以后端落盘后的会话为准**）。
       opts = { resend, userIndex, assistantIndex }：
         · resend + userIndex      → 编辑后重发（该用户消息新增一个版本，回复整段换新分支）
         · resend + assistantIndex → 重新生成（那条回答新增一个版本）
         · 都不带                  → 普通提问（新增一条用户消息 v1） */
    async function aiSend(retryText, opts) {
      const options = (opts && typeof opts === 'object') ? opts : { resend: !!opts };
      const resend = !!options.resend;
      const userIndex = options.userIndex;
      const assistantIndex = options.assistantIndex;
      const text = String((typeof retryText === 'string' ? retryText : aiDraft.value) || '').trim();
      if (!text || aiBusy.value) return;
      if (!settings.ai_enabled) { toast(t('ai_disabled', 'GCP-AI 还没有开启，可在设置里打开。'), 'info'); return; }
      /* **不再**在没有 Key时前端早退 —— 那样 ai.send 根本不会被调用，
         chats/ 下永远没有会话文件（用户报的"历史对话不存储"根因）。
         现在一律交给后端：ai.send 会先把用户消息落盘，再返回 kind:'no_key' 的固定引导回答。
         输入框里可能填了还没保存的临时 Key→ 先按原有保存流程落盘再发；
         保存失败也不阻塞发送（后端照样按 no_key 处理并落盘用户消息）。 */
      const tempKey = String(apiKeyDraft.value || '').trim();
      if (tempKey && tempKey !== String(apiKeySnapshot.value || '').trim()) {
        try { await saveApiKey(); } catch (error) { /* 保存失败不阻塞发送 */ }
      }
      /* 普通提问才本地先推一颗用户气泡；重新生成/编辑重发**不能**再追加，
         否则等后端返回整会话重建时会出现两条一样的提问。 */
      if (!resend) aiMessages.value.push({ role: 'user', text });
      aiDraft.value = '';
      clearPolishUndo();                         // 发出去了，这次的"可撤销润色"没有意义了
      /* ⚠️ 先丢掉上一条流的状态（用户按过"停止"后流还挂着 aiStreamId）：
         不清的话 finally 会以为"还在流式"而不解冻 aiBusy，界面就永远点不动了。 */
      clearStreamBubble();
      aiBusy.value = true;
      aiAborted = false;
      aiPending.value = true;                    // 「AI正在查看问题...」（不进历史、不落盘）
      /* Agent 执行过程卡片：每次发送从零开始，执行中默认展开（用户要看它在干什么） */
      resetAgentSteps();
      aiRunActive = true;               // 本轮运行开始：接受 ai.agent_progress 事件（见其定义）
      aiAgentStepsOpen.value = true;
      aiAgentStepsTouched = false;
      /* 「正在生成」气泡 + 逐字文本的**落点**（必须在 clearStreamBubble 之后设，
         因为它会把这两个也清回 -1）。
         pendingAfter：重新生成时 = 被重生的那条回答的下标 → 进度气泡挂在它正下方
         （需求"在原有位置上出现正在xxx的聊天气泡"）；普通提问/编辑重发 = -1（挂末尾）。
         逐字输出同理：aiStreamSlot 给定时 delta 直接写进那条气泡，不再"跑到末尾闪一下
         再跳回来"。 */
      const slot = Number(options.pendingAfter);
      const inPlace = Number.isFinite(slot) && slot >= 0;
      aiPendingAfter.value = inPlace ? slot : -1;
      aiStreamSlot.value = inPlace ? slot : -1;
      /* cutAfter 独立于 pendingAfter：编辑重发时 pendingAfter=-1（没有可取代的 AI 气泡，
         新回答挂在末尾），但**它下面那串旧分支同样要让位**，所以两个参数分开传。
         ⚠️ 必须排在 clearStreamBubble() 之后 —— 那个函数会把 aiCutAfter 清回 -1。 */
      const cut = Number(options.cutAfter);
      aiCutAfter.value = (Number.isFinite(cut) && cut >= 0) ? cut : -1;
      aiThinkingText.value = t('ai_thinking', '正在思考…');
      cancelAiEdit();
      /* ⚠️ 任务 1 配套：**用户自己发消息**必须重新贴底并滚到底 ——
         哪怕他刚才正在往上翻历史（翻完想提问，新气泡当然要看得见）。
         先置 aiStickBottom=true 再 force 一次，两件事缺一不可：
         只 force 的话下一次 delta 又会被"false"拦住。 */
      aiStickBottom.value = true;
      nextTick(() => scrollAiToEnd(undefined, true));
      try {
        /* ---- ① 优先走流式（逐字输出）----
           ⚠️ 本轮需求：「回答逐字输出」设置项已删除（用户：逐字输出本来就是我的设计，
              不要选项控制）。所以这里**恒走流式**，不再读 settings.ai_stream_enabled。
              三条降级路径照样保留（都不是"用户选项"，是能力/时序问题）：
                a) 后端没有 ai.send_stream（旧后端）→ tryCall 返回 null；
                b) 后端明确说 kind:'fallback'（缺 Key / /plugin 工具循环 / 窗口正在退出）；
                c) 启动流式失败（start_failed）→ 退回整段 send()。 */
        const wantStream = true;
        if (wantStream) {
          /* ⚠️ 任务 4 的命门：事件推送比 js_api 返回值先到是**合法时序**
             （后端线程先起再 return），旧代码在 id 落定前把这些包全判成"迟到"丢掉，
             每个对话第一句的思考包（只有 reasoning、没有 text）几乎必丢。
             现在：调用**前**置 await 标志 → 早到的包进缓冲；返回值到了再补 id 重放。 */
          aiStreamAwait = true;
          /* ⚠️ 最后一个参数是**界面当前那一档思考**：后端以前只按档案表查，前端刚改的档位、
             或两端档案 id / 模型写法差一点，都会查成 off —— 用户看到的就是「每个对话
             发送第一句就算你带思考也没用，他就是当没开思考」。后端以这个值为准（模型
             不支持思考时仍会自动忽略），所以这里必须每次都带上，不能只在设置里改的时候带。 */
          const started = await bridge.tryCall('ai.send_stream', aiSessionId.value || '', text,
            String(settings.ai_reply_mode || 'standard'), resend,
            (userIndex === undefined || userIndex === null) ? '' : userIndex,
            (assistantIndex === undefined || assistantIndex === null) ? '' : assistantIndex,
            String(aiThinkingLevel.value || ''));
          if (started && started.ok && started.stream_id) {
            /* 用户消息已经落盘：先按后端返回的会话重建气泡（下标从此以磁盘为准），
               然后把"等回答"这件事整个交给 ai.stream 事件。 */
            aiStreamId = started.stream_id;
            armAiStreamWatchdog();               // 收尾包没到也不能把界面卡死
            if (started.session_id) aiSessionId.value = started.session_id;
            if (started.session && Array.isArray(started.session.messages)) {
              aiMessages.value = sessionToMessages(started.session);
              /* 重建后**重新校验落点**：aiStreamSlot / aiPendingAfter 是发请求前那份
                 列表的下标，磁盘版万一多/少了一条（比如用户消息被补进去），
                 不校验就会把逐字文本写进别人的气泡里。
                 规则很简单：那一格必须是 AI 气泡，才允许就地输出；否则退回"末尾临时气泡"。 */
              const slotMsg = aiMessages.value[aiStreamSlot.value];
              if (aiStreamSlot.value < 0 || !slotMsg || slotMsg.role !== 'ai') {
                aiStreamSlot.value = -1;
              }
              const pendMsg = aiMessages.value[aiPendingAfter.value];
              if (aiPendingAfter.value >= 0 && (!pendMsg || pendMsg.role !== 'ai')) {
                aiPendingAfter.value = -1;
              }
            }
            loadAiSessions();
            /* ---- 重放早到的事件（任务 4：以前这些全被"迟到"分支扔了）----
               缓冲里可能已经有 delta、甚至整条 done（秒回的回答）：
               · done 在重放里就地收尾（finishAiStream 用磁盘会话重建），这时**不能**
                 再走下面那段同步路径（会重复落一次用户消息 / 覆盖重建结果），直接 return；
               · 还没收尾就只管继续等后面的事件，由 done/error 收尾。 */
            aiStreamAwait = false;
            const early = aiStreamEarlyEvents;
            aiStreamEarlyEvents = [];
            for (const ev of early) {
              if (String(ev && ev.stream_id || '') !== aiStreamId) continue;
              dispatchAiStreamEvent(ev);
            }
            return;                              // finally 里不放行 aiBusy：由 done/error 收尾
          }
          /* fallback（缺 Key / /plugin / 没有事件通道 / 起流失败）或旧后端没有 send_stream：
             缓冲里若有这个流的包（理论上不该有），一并作废，走同步整段路径。 */
          resetAiStreamBuffer();
          /* 诊断（dev_mode_enabled 打开才有输出）：/plugin 与缺 Key 都是**后端主动要求
             走整段**的 fallback，属预期；但事件流水如果显示"前端一个 ai.stream 包都没收到、
             而 ai_stream_enabled 是开着的"，那就是后端推流断了 —— 把这行证据交给 lead/ai-backend。 */
          if (settingOn(settings.dev_mode_enabled) && wantStream
            && started && started.kind === 'fallback') {
            /* 诊断只在 bridge 就绪时写日志（浏览器预览模式没有 log.client） */
            if (bridge.ready) {
              bridge.call('log.client', 'info', 'AI',
                'stream-fallback reason=' + (started.reason || '?')
                + ' textLen=' + String(text || '').length).catch(() => {});
            }
          }
          /* 没有 send_stream / 明确 fallback → 继续往下走同步那条路 */
        }
        /* ---- ② 同步整段返回（原有路径）---- */
        const result = await bridge.tryCall('ai.send', aiSessionId.value || '', text,
          String(settings.ai_reply_mode || 'standard'), !!resend,
          (userIndex === undefined || userIndex === null) ? '' : userIndex,
          (assistantIndex === undefined || assistantIndex === null) ? '' : assistantIndex,
          String(aiThinkingLevel.value || ''));     /* 同流式：带上界面当前思考档位 */
        if (aiAborted) return;                             // 用户点了停止 → 丢弃这次结果
        if (!result) {
          aiMessages.value.push({ role: 'ai', error: true, text: t('ai_backend_missing',
            '桌面端接口 <ai.send> 还没就绪，暂时发不出请求。') });
          return;
        }
        if (result.session_id) aiSessionId.value = result.session_id;
        /* ⚠️ 一律以后端落盘后的 session.messages 为准重建气泡：成功/失败（含 no_key、
           401 等）后端都已把对应消息写进磁盘，界面和磁盘从此一致 ——
           "从历史点进来对话没了"的根因（失败只在前端内存里推气泡）就此堵死。 */
        const session = (result.session && Array.isArray(result.session.messages))
          ? result.session : null;
        if (session) {
          aiMessages.value = sessionToMessages(session);
          /* ⚠️ 任务 4 的第二个坑（防御式，不依赖后端版本）：
             旧后端的 session dump 不带 reasoning 镜像，但 send() 的**顶层**返回里有
             `reasoning`。这里把顶层 reasoning 兜底补到最后一条 AI 气泡上（界面立刻有
             思考块；重新打开该对话仍没有 = 后端落盘缺字段，需要 ai-backend 配合，见汇报）。
             result.thinking 是新字段（布尔）：明确说"这次没开思考"就不补，防止串台。 */
          const topThink = String(result.reasoning || '');
          const thinkFlag = (result.thinking === undefined) ? null : !!result.thinking;
          if (topThink && thinkFlag !== false) {
            for (let i = aiMessages.value.length - 1; i >= 0; i -= 1) {
              if (aiMessages.value[i].role === 'ai' && !aiMessages.value[i].reasoning) {
                aiMessages.value[i].reasoning = topThink;
                break;
              }
            }
          }
          /* 本轮：这里不再给同步结果装打字机。
             上一轮我为了治"整段突然出现"，把 ai.send 的整段回答也塞进打字机逐字追 ——
             那是给"人为限速"打补丁。用户这轮把语义讲清楚了：
             「我的原意是 ai 输出多快软件这个逐字功能输出就有多快」，也就是不要限速。
             所以现在的口径是：
               · 流式路径 → 直通（见 aiApplyStreamText）；
               · 同步路径（/plugin 工具循环、缺 Key 引导、网关拒绝思考参数后重跑、
                 旧后端没有 send_stream）→ 本来就是一次性拿到整段，
                 直接显示就是正确行为，不该假装逐字。
             磁盘会话重建上面已经做过（aiMessages = sessionToMessages(session)），
             这里什么都不用补。 */
        } else if (result.ok) {
          aiMessages.value.push({ role: 'ai', text: String(result.reply || '') });
        } else {
          aiMessages.value.push({ role: 'ai', error: true,
            text: t('ai_request_failed', '请求失败：') + (result.error || '') });
        }
        if (result.kind === 'no_key') {
          /* 复用语言包里已有的 ai_no_key_reply（三语齐全），不新造 key */
          toast(t('ai_no_key_reply', '还没配置 API Key，填好就能聊。'), 'info');
        }
        if (result.persisted === false) {
          toast(t('ai_chat_not_saved', '对话没能保存到磁盘'), 'warning');
        }
        /* 本轮：AI 通过 /plugin 工具循环**造出了新插件** → 立刻刷新插件中心。
           后端一直在回包里给 created_plugins（desktop/api/ai.py 的 _chat_with_tools），
           但前端以前完全没消费它 —— 用户让 AI 做完插件，还得自己点「重新加载」才看得见。 */
        /* ★ 本轮（统计面板）：整段 send() 这条路也要吃到 usage（流式在 finishAiStream） */
        if (result && result.usage) aiTakeUsage(result);
        if (Array.isArray(result.created_plugins) && result.created_plugins.length) {
          loadPlugins(false);
          toast(t('plugin_created', '已生成 {n} 个插件，去插件中心开启它')
            .replace('{n}', result.created_plugins.length), 'success');
        }
        loadAiSessions();                                // 会话标题/时间会变，顺手刷新历史
      } catch (error) {
        aiMessages.value.push({ role: 'ai', error: true,
          text: t('ai_request_failed', '请求失败：')
          + (error && error.message ? error.message : error) });
      } finally {
        /* ⚠️ 流式那条路 return 之前**不能**解冻 aiBusy（否则用户可以连点两次发送，
           第二个流会把第一个的气泡冲掉）。所以用 aiStreamId 判断：还在流上就交给
           done/error/cancelled 事件去收尾，这里只清"等待提示"以外的东西。 */
        if (!aiStreamId) {
          aiRunActive = false;   // 同步/降级路径也到此为止：关闭 Agent 进度闸门
          /* 异常/同步路径收尾：await 标志万一还挂着（tryCall 抛错、fallback 前异常），
             必须关掉缓冲，否则无关事件会攒到**下一条**流里被重放。 */
          resetAiStreamBuffer();
          /* 本轮：直通模式下没有"还没打完的字"，
             同步路径走完就可以立刻解冻 aiBusy / 等待提示。
             （流式那条路在 return 之前就不进这个分支，靠 done/error/cancelled 收尾。） */
          aiBusy.value = false;
          aiPending.value = false;
          /* 同步这条路到此为止了：把"让位"还回去。
             两种情况都是对的 ——
               · 成功：上面已经拿磁盘会话重建过，真内容已经在列表里，还位不影响；
               · 失败/异常（比如 catch 里补了一条报错气泡）：磁盘**没被改**，
                 还位才能让被藏起来的旧分支重新显示，不留"藏了不还"的空洞。 */
          aiCutAfter.value = -1;
        }
        /* Agent 执行全部结束后自动折叠成一行「已完成 N 步」
           （执行中一直展开；用户手动点过就以他的选择为准，不再自动改） */
        if (aiAgentStepsDone.value && !aiAgentStepsTouched) aiAgentStepsOpen.value = false;
        nextTick(scrollAiToEnd);
      }
    }

    /* ---------- 流式事件（后端 shell.push_event("ai.stream", …)） ----------
       ⚠️ 迟到事件必须丢：切会话 / 新一次发送之后，旧流的 stream_id 已经不是 aiStreamId，
          还往气泡里写字就会出现"切了会话还在往旧气泡里打字"，dispatch 第一句照旧校验。
       ⚠️ 但 **"id 还没到" ≠ "迟到"**：send_stream 是"先起线程推事件、后 return id"，
          id 落定之前到的包是本流自己的**早到包**，一律缓冲待重放（见下面的 aiStreamAwait
          与 aiSend 里的重放）—— 旧版把它们全丢了，就是"每个对话第一句没有思考内容"的根因。 */
    /* 收尾看门狗：万一 done/error/cancelled 一个都没到达（后端事件推送刚好撞上窗口销毁、
       或者线程被杀），界面不能永远灰着不能点。到点就**以磁盘为准**重新拉一次会话：
       回答其实已经落盘，拉回来就是正确结果，同时解冻 aiBusy。 */
    let aiStreamWatchdog = 0;
    function armAiStreamWatchdog() {
      if (aiStreamWatchdog) clearTimeout(aiStreamWatchdog);
      aiStreamWatchdog = setTimeout(async () => {
        aiStreamWatchdog = 0;
        if (!aiStreamId) return;
        clearStreamBubble();                     // 里面会把 aiStreamId 清掉（旧流迟到的包就都丢了）
        aiBusy.value = false;
        aiPending.value = false;
        /* 磁盘才是真源：把这一轮真正落盘的结果拿回来（可能已有回答，也可能没有）*/
        await loadAiSession(aiSessionId.value);
        loadAiSessions();
        toast(t('ai_stream_lost', '这次回答的实时输出中断了，已按已保存的内容显示'), 'warning');
      }, AI_STREAM_WATCHDOG_MS);
    }
    function disarmAiStreamWatchdog() {
      if (aiStreamWatchdog) { clearTimeout(aiStreamWatchdog); aiStreamWatchdog = 0; }
    }

    /* ---------- ai.stream 事件分发 ----------
       ⚠️⚠️ 任务 4 的根因曾在旧写法上：每个包第一句 `id !== aiStreamId → 丢`，而
          aiStreamId 要等 ai.send_stream 的返回值到了才赋值 —— 后端是"先起线程推事件、
          后 return"，早到的包（尤其只有 reasoning 的第一包）会被全部丢掉，
          于是"每个对话第一句没有思考内容"。现在的做法：send_stream 已发出但 id 还没
          回来时（aiStreamAwait），事件先进缓冲区，id 一到统一重放。
       ⚠️ 本轮（直通模式，用户确认"输出多快显示多快"）：delta 到达即贴
          （aiApplyStreamText），前端不再限速、不再攒收尾包。 */
    let aiStreamAwait = false;
    let aiStreamEarlyEvents = [];
    /* 任务 3/4 取证：每次发送记一份事件流水（几次、每次多大、是否走了流式），
       dev_mode_enabled 打开时挂到 window.__AI_STREAM_DEBUG__ 供控制台核对 ——
       用户/lead 要"前端收到了几次事件、每次 payload 大小"就查这里。 */
    const aiStreamLog = [];
    function _aiStreamProbe(payload, where) {
      if (!settingOn(settings.dev_mode_enabled)) return;
      const size = JSON.stringify(payload || {}).length;
      aiStreamLog.push({ t: Math.round(performance.now()), type: String((payload && payload.type) || ''),
        textLen: String((payload && payload.text) || '').length,
        thinkLen: String((payload && payload.reasoning) || '').length,
        bytes: size, where, early: aiStreamAwait && !aiStreamId });
      if (aiStreamLog.length > 400) aiStreamLog.splice(0, aiStreamLog.length - 400);
      window.__AI_STREAM_DEBUG__ = aiStreamLog;
    }
    function resetAiStreamBuffer() {
      aiStreamAwait = false;
      aiStreamEarlyEvents = [];
    }

    function dispatchAiStreamEvent(payload) {
      const type = String(payload.type || '');
      const id = String(payload.stream_id || '');
      if (id !== aiStreamId) return;             // 迟到 / 别的流：一律丢（含它的收尾包）
      if (type === 'delta') {
        /* 第一段正文到达 → 等待提示（「AI正在查看问题...」）立刻消失 */
        const text = String(payload.text || '');
        const think = String(payload.reasoning || '');
        if (text) aiPending.value = false;
        if (aiStreamingIndex.value < 0) {
          /* ⚠️⚠️ 落点分两种（需求："重新生成要在**原有位置**上出现正在生成的气泡"）：
             · aiStreamSlot ≥ 0（重新生成回答1）→ 逐字文本**就地写进那条回答**：
               先把它认领成"正在流式的那一格"，回答1 那颗气泡当场开始往外吐新内容。
               旧版本已经在后端进 variants 表，done 之后 ◀ 1/2 ▶ 就能翻回去，不丢。
             · aiStreamSlot < 0（普通提问 / 编辑重发）→ 回答还没落盘（磁盘上此刻只有
               用户那句），在列表**尾部**挂一颗临时气泡承载逐字文本。
             以前这里不分情况一律"往尾部挂"，于是重新生成时文字先跑到整段最末尾
             （下一条回答的空白位）出现、done 后又跳回原位 —— 就是用户描述的
             「在回答3的空白位置上出现一个正在xxx聊天气泡然后突然消失」。
             ⚠️ 这颗临时气泡是渲染层的东西：不进历史、不落盘，done 时被磁盘版替换。 */
          const slot = aiStreamSlot.value;
          if (slot >= 0 && slot < aiMessages.value.length) {
            aiStreamingIndex.value = slot;
          } else {
            aiMessages.value.push({ role: 'ai', streaming: true });
            aiStreamingIndex.value = aiMessages.value.length - 1;
          }
        }
        /* ⚠️ 本轮（用户确认「完全跟随到达速度」）：后端已经取消 120ms 节流，
           前端也不再限速 —— 正文和思考都**原样贴上去**（aiApplyStreamText）。
           仍然写 target 再贴（而不是直接写 aiStreamingText）是为了：
             ① 看门狗/停止时能拿到"最后一份完整文本"；
             ② 网关 400 降级重试时后端会把 latest 清零重推，覆盖式写法能跟着回退
                （长度夹取反而会卡在旧长文上）。 */
        aiStreamTarget.value = text;
        if (think) {
          if (!aiThinkStartedAt) aiThinkStartedAt = Date.now();
          aiStreamThinkTarget.value = think;
          // 思考先到、正文后到 → 正文第一次到达时算出"思考用时"
          if (text && !aiThinkSeconds) {
            aiThinkSeconds = Math.max(1, Math.round((Date.now() - aiThinkStartedAt) / 1000));
          }
        }
        startAiTyper();                    /* 直通：等价于 aiApplyStreamText() */
        /* 每收到一段就重新计时：只要字还在往外蹦，就不该判"输出中断" */
        armAiStreamWatchdog();
        return;
      }
      if (type === 'done' || type === 'cancelled' || type === 'error') {
        /* ★ 本轮运行结束：关闭 ai.agent_progress 闸门（旧运行的尾事件不再混进来） */
        aiRunActive = false;
        /* 本轮（直通模式）：done 立刻落地，不再"等字打完"。
           以前要攒着收尾包是因为打字机可能还没追完、整段替换会跳一下；
           现在显示内容始终等于最后一次 delta 的累计全文，done 带的就是同一份文本
           （磁盘版），替换过去逐字节相同，不会跳。
           ⚠️ 落地前先把"最后一份 target"对齐到 done 的文本：万一最后一个 delta
              和 done 之间 reader 又写了几个字没来得及推，这一步保证界面不缺一截。 */
        aiStreamTarget.value = String(payload.text || aiStreamTarget.value || '');
        if (payload.reasoning) aiStreamThinkTarget.value = String(payload.reasoning);
        aiApplyStreamText();
        finishAiStream(payload);
      }
    }

    onEvent('ai.stream', (payload) => {
      if (!payload) return;
      _aiStreamProbe(payload, 'event');
      if (!aiStreamId && aiStreamAwait) {
        /* send_stream 还没返回（id 未知）：先进缓冲，等 id 落定统一重放。
           上限保护：只挤最旧的 delta（收尾包永远保留），别把内存当流用。 */
        if (aiStreamEarlyEvents.length >= 512) {
          const dropAt = aiStreamEarlyEvents.findIndex((p) => String(p.type || '') === 'delta');
          if (dropAt >= 0) aiStreamEarlyEvents.splice(dropAt, 1);
        }
        aiStreamEarlyEvents.push(payload);
        return;
      }
      dispatchAiStreamEvent(payload);
    });

    /** 收尾（done / cancelled / error）：以磁盘为准重建气泡、解冻 aiBusy。
     *  ⚠️ 本轮（直通模式）：done 到达即调用，不再有"攒着等打完"那条路。 */
    /* =====================================================================
       GCP-AI 用量统计（本轮需求 4/5：缓存命中 / 上下文 / 会话统计小面板）
       =====================================================================
       数据链路（全部是网关**原样回传**的 usage，不改用户任何对话内容）：
         · provider 响应 usage（含 prompt_cache_hit_tokens / cached_tokens）
           → client.py extract_usage() 归一成 {prompt, completion, total, cached}
         · 每次请求 ai.py _usage_of()：折进 session.usage_total（会话累计）
           + 本次那份挂到那条消息上；send/done 信封都带 usage
         · 前端只存两份：aiUsageLast（本次）/ aiUsageTotal（会话累计）。
       ⚠️ 拿不到 usage（老后端 / 网关不给 / 离线）时面板**如实显示"暂无数据"**，
          绝不显示 0% 骗人。 */
    const aiStatsOpen = ref(false);
    /* ★ 本轮（用户新规格）：悬浮打开；鼠标在按钮/面板这块区域内**不自动关**，
       离开这块区域才收。面板是 .ai-stats-wrap 的 DOM 子节点，鼠标移到面板上
       不会触发父级 mouseleave；但按钮与面板之间有 8px 视觉间隙，跨过的瞬间会
       误报"离开" → 关动作一律延迟 300ms（grace），期间任何 mouseenter 取消关闭。
       点按钮仍可手动开/关（触屏 / 键盘用户同样能操作）。 */
    let aiStatsCloseTimer = 0;
    function aiStatsHover(inside) {
      if (inside) {
        if (aiStatsCloseTimer) { clearTimeout(aiStatsCloseTimer); aiStatsCloseTimer = 0; }
        aiStatsOpen.value = true;
        return;
      }
      if (aiStatsCloseTimer) clearTimeout(aiStatsCloseTimer);
      aiStatsCloseTimer = setTimeout(function () {
        aiStatsCloseTimer = 0;
        aiStatsOpen.value = false;
      }, 300);
    }
    const aiUsageLast = ref(null);
    const aiUsageTotal = ref(null);
    function aiTakeUsage(payload) {
      try {
        const u = payload && payload.usage;
        if (!u || typeof u !== 'object') return;
        if (u.last && typeof u.last === 'object') aiUsageLast.value = { ...u.last };
        if (u.total && typeof u.total === 'object') aiUsageTotal.value = { ...u.total };
      } catch (e) { /* 统计是锦上添花，坏了不许影响聊天 */ }
    }
    /* 会话累计缓存命中：后端 _fold_usage 把每次请求的 cached 加总到 cached_total */
    const aiCacheStats = computed(() => {
      const t = aiUsageTotal.value;
      if (!t || !Number(t.prompt)) return null;
      const prompt = Number(t.prompt) || 0;
      // 只认后端累计的**精确** cached_total；没有 → 这块显示"暂未可用"，
      // 绝不拿"最近一问"或估算冒充会话级命中率（用户明确不许假数）。
      const ct = t.cached_total;
      if (!Number.isFinite(ct) || prompt <= 0) return null;
      const cached = Math.min(Number(ct) || 0, prompt);
      return { prompt, cached, rate: Math.min(100, Math.round(cached / prompt * 1000) / 10) };
    });
    const aiTokenStats = computed(() => {
      const t = aiUsageTotal.value;
      if (!t) return null;
      return {
        prompt: Number(t.prompt) || 0,
        completion: Number(t.completion) || 0,
        total: Number(t.total) || 0,
        requests: Number(t.requests) || 0,
      };
    });
    /* 最近一问的命中率（prompt/cached/rate） */
    const aiLastHit = computed(() => {
      const l = aiUsageLast.value;
      if (!l || !Number(l.prompt)) return null;
      const prompt = Number(l.prompt) || 0;
      const cached = Number(l.cached) || 0;
      return { prompt, cached, rate: Math.min(100, Math.round(cached / prompt * 1000) / 10) };
    });
    /* 上下文：大数字只显**服务端实测**的 prompt_tokens（= 本次真正发给模型的全部
       输入：system + 资源清单 + 历史 + 这一问，由网关算出来，不是本地估算）。
       ⚠️ 用户点名「上下文只是大约而不是真实准确数值」是缺陷 —— 旧版按字符数
       粗估的 approxTokens 整条删掉；没有实测值时如实显示"暂未可用"，不给估数。
       下面的「发送范围 / 会话条数」是对设置与会话的事实描述（不是测量值），保留。 */
    const aiContextStats = computed(() => {
      const list = aiMessages.value || [];
      const rounds = Number(settings.ai_context_rounds || 0);
      let count = 0;
      list.forEach((m) => { if (m && !m.error) count += 1; });
      return {
        rounds,
        messages: count,
        /* 服务端实测值：最近一次请求 usage 里的 prompt_tokens（Agent 模式已合并
           工具循环的每一轮，见 ai.py _merge_usage）；没有 = 0（面板显示暂未可用）。
           重开会话时 aiUsageLast 为空，退回累计里落盘的 last_prompt（同样是实测值）。 */
        realPrompt: Number((aiUsageLast.value && aiUsageLast.value.prompt)
          || (aiUsageTotal.value && aiUsageTotal.value.last_prompt) || 0),
      };
    });
    /* ★ 本轮新增：本次输入的构成（系统提示词 / 工具定义 / 对话消息）。
       数据链路：后端 _context_mix() 把组装完的 messages 按**字符数**分成三段
       （工具清单本来拼在 system 正文里，后端已从 system 里扣出来单算），
       随 usage 一起回传（本次的 last.mix，累计里落盘为 last_mix）。
       前端只做"比例 → tokens"的折算，不另做估算：
         · 总量 = 服务端实测的 prompt_tokens（真值）；
         · 三段 tokens = 各段字符占比 × 总量，四舍五入后**最后一段吃掉尾差**，
           保证三段相加严格等于实测总量；
         · 面板上显式带 ≈ 并注明"按字符占比折算"，免得被读成三段各自实测。
       没有实测值（没发过请求 / 服务商没回 usage）→ null，面板写暂未可用。 */
    const aiContextMix = computed(() => {
      const lastUsage = aiUsageLast.value || null;
      const totUsage = aiUsageTotal.value || null;
      const mix = (lastUsage && lastUsage.mix) || (totUsage && totUsage.last_mix) || null;
      if (!mix || typeof mix !== 'object') return null;
      const chars = {
        system: Number(mix.system_chars) || 0,
        tools: Number(mix.tools_chars) || 0,
        messages: Number(mix.messages_chars) || 0,
      };
      const totalChars = chars.system + chars.tools + chars.messages;
      if (!(totalChars > 0)) return null;
      const totalTokens = Number((lastUsage && lastUsage.prompt) || (totUsage && totUsage.last_prompt) || 0);
      if (!(totalTokens > 0)) return null;
      const parts = [
        { key: 'system', labelKey: 'ai_stats_mix_system', label: '系统提示词' },
        { key: 'tools', labelKey: 'ai_stats_mix_tools', label: '工具定义' },
        { key: 'messages', labelKey: 'ai_stats_mix_messages', label: '对话消息' },
      ].filter((p) => chars[p.key] > 0);
      let used = 0;
      const segments = parts.map((p, i) => {
        const isLast = i === parts.length - 1;
        const tk = isLast
          ? Math.max(0, totalTokens - used)
          : Math.round(totalTokens * chars[p.key] / totalChars);
        used += tk;
        return {
          key: p.key,
          name: t(p.labelKey, p.label),
          chars: chars[p.key],
          tokens: tk,
          pct: Math.round(chars[p.key] / totalChars * 1000) / 10,
        };
      });
      return {
        totalChars,
        totalTokens,
        messageCount: Number(mix.message_count) || 0,
        segments,
      };
    });

    /* ★ 本轮新增（用户：「新建对话也能看到统计 UI 还是没解决」）：
       面板里的"系统提示词 / 工具定义 / 对话消息"三行改成**常显骨架** ——
       不管有没有发过请求，这三行标签与配色都先摆出来（没数据时值是 '—'），
       否则新对话里整块 v-if="aiContextMix" 不渲染，用户只看到一行"暂未可用"，
       观感就是"统计 UI 没显示"。
       有实测构成时直接复用 aiContextMix.segments 的折算值，口径不变。 */
    const aiMixLegend = computed(() => {
      const parts = [
        { key: 'system', labelKey: 'ai_stats_mix_system', label: '系统提示词' },
        { key: 'tools', labelKey: 'ai_stats_mix_tools', label: '工具定义' },
        { key: 'messages', labelKey: 'ai_stats_mix_messages', label: '对话消息' },
      ];
      const mx = aiContextMix.value;
      return parts.map((p) => {
        const seg = mx ? mx.segments.find((s) => s.key === p.key) : null;
        return {
          key: p.key,
          name: t(p.labelKey, p.label),
          tokens: seg ? seg.tokens : null,
          pct: seg ? seg.pct : null,
        };
      });
    });

    function aiNumberFmt(n) {
      const v = Number(n) || 0;
      if (v >= 1000000) return (v / 1000000).toFixed(1) + 'M';
      if (v >= 1000) return (v / 1000).toFixed(1) + 'k';
      return String(v);
    }
    async function copyAiStats() {
      /* 复制出去的内容和面板**同一口径**：三块各自要么是真值、要么明说暂未可用 */
      const out = [];
      const tk = aiTokenStats.value;
      const cs = aiCacheStats.value;
      const ctx = aiContextStats.value;
      if (cs) out.push(t('ai_stats_cache', '缓存命中') + ': ' + cs.rate + '% (' + cs.cached + ' / ' + cs.prompt + ' tokens)');
      else out.push(t('ai_stats_cache', '缓存命中') + ': ' + t('ai_stats_cache_na', '暂未可用：服务商未回传缓存命中数据'));
      if (ctx.realPrompt > 0) out.push(t('ai_stats_context', '上下文') + ': ' + ctx.realPrompt + ' tokens');
      else out.push(t('ai_stats_context', '上下文') + ': ' + t('ai_stats_context_na', '暂未可用：发送后才有服务端实测值'));
      if (tk) out.push(t('ai_stats_session', '会话统计') + ': ' + tk.prompt + ' in / ' + tk.completion + ' out / ' + tk.total + ' total / ' + tk.requests + ' req');
      else out.push(t('ai_stats_session', '会话统计') + ': ' + t('ai_stats_session_na', '暂未可用：还没有带回用量的请求'));
      const mx = aiContextMix.value;
      if (mx) {
        out.push(t('ai_stats_mix_title', '本次输入构成') + ': '
          + mx.segments.map((s) => s.name + ' ≈' + s.tokens + ' (' + s.pct + '%)').join(' / '));
      }
      await copyText(out.join('\n'));
    }

    function finishAiStream(payload) {
      aiTakeUsage(payload);
      const type = String(payload.type || '');
      const session = (payload.session && Array.isArray(payload.session.messages))
        ? payload.session : null;
      const seconds = aiThinkSeconds;
      cancelAiTyper();
      clearStreamBubble();
      aiBusy.value = false;
      if (session) {
        aiMessages.value = sessionToMessages(session);
        // 刚结束这条流：把"思考用时"挂到最后一条 AI 气泡上（磁盘里没有这个信息）
        if (seconds > 0) {
          for (let i = aiMessages.value.length - 1; i >= 0; i -= 1) {
            if (aiMessages.value[i].role === 'ai') {
              aiMessages.value[i].reasoning_seconds = seconds;
              break;
            }
          }
        }
      }
      if (type === 'error') {
        toast(String(payload.error || payload.text || t('ai_request_failed', '请求失败：')),
          'error');
      }
      if (type === 'cancelled') {
        /* 后端可能因为"一个字都没打出来"而没有落盘：这时补一颗说明气泡，
           界面上不能出现"发了但什么都没有"。 */
        const last = session && session.messages && session.messages[session.messages.length - 1];
        if (!last || last.role !== 'assistant') {
          aiMessages.value.push({ role: 'ai', text: t('ai_stopped', '已停止本次回答') });
        }
      }
      if (payload.persisted === false) {
        toast(t('ai_chat_not_saved', '对话没能保存到磁盘'), 'warning');
      }
      loadAiSessions();
      nextTick(scrollAiToEnd);
    }

    /* ---------- 输入框润色按钮（设置里可关，见 设置 → GCP-AI） ----------
       需求原话：在 GCP-AI 的输入框内最右侧 也在发送按钮的左边放一个润色按钮 AI 的图标，
                   可以在设置中的 GCP-AI 区域中找到对应设置可以点击开关设置为关闭则按钮消失。
       设计取舍：只把当前草稿交给后端 `ai.polish`，回来后**替换输入框内容**（不发送、不落历史）；
                 失败只 toast，原文一个字都不动（不能"润色失败还把用户写的话弄丢"）。 */
    /** 清掉「可撤销润色」状态（按钮回到普通「润色」） */
    function clearPolishUndo() { aiPolishOriginal.value = ''; }
    /** 程序自己改 aiDraft 时包住赋值，避免被 watch 误判成"用户又编辑了" */
    function setAiDraftProgrammatically(value) {
      aiPolishApplying = true;
      try { aiDraft.value = value; } finally { aiPolishApplying = false; }
    }
    /* ⚠️ flush:'sync' 是这条逻辑的命门：默认的 'pre' 会把回调排到下一个 tick，
       那时 aiPolishApplying 早被 finally 清掉了 → 程序赋值也会被当成用户编辑，
       润色刚做完可撤销状态就自己没了（按钮永远变不回「返回上一个」）。 */
    watch(aiDraft, () => {
      if (aiPolishApplying) return;
      if (!aiPolishOriginal.value) return;
      /* 用户在润色之后自己动过输入框（打一个字都算）→ 撤销会把他的修改整段吃掉，
         所以这里主动放弃可撤销状态。 */
      clearPolishUndo();
    }, { flush: 'sync' });

    /* 润色按钮可用吗（本轮需求：「当未填写任何API Key时输入文字 润色按钮还是灰色不可点击状态」）。
       判定口径和模型弹层"有没有 Key"完全同一个（aiModelNoKey：后端 model_choices 里
       一个 has_key 的服务商都没有），不另起一套 —— 两处 UI 说不一致最容易被当成 bug。
       ⚠️ 后端还没就绪（aiModelHasApi=false，拿不到 model_choices）时**不拦**：
          没 Key 由后端返回 no_key 引导文案兜底，前端不能因为"拿不到清单"就把功能按钮全灰掉。 */
    const aiPolishBlocked = computed(() => aiModelHasApi.value && aiModelNoKey.value);
    /* 润色期间输入框只读锁（本轮需求原话：「润色按钮点击后为润色中，期间输入框状态
       被锁定为不可输入模式」）。
       ⚠️ 只锁**当前这个 AI 输入框**（模板把 aiInputLocked 传给 rich-ai-input 的 :disabled，
          由它把 contenteditable 切成 false + 挂 is-locked），
          不碰模型弹层/设置页任何输入框 —— 那边是独立的 DOM，跟这个 computed 无关。 */
    const aiInputLocked = computed(() => aiPolishing.value);
    async function aiPolish() {
      if (aiPolishing.value || aiBusy.value) return;
      if (aiPolishBlocked.value) return;          /* disabled 已经是真禁用，这层是防键盘回车绕过 */
      /* ---- 第二态：撤销润色（此时按钮图标已经是「返回上一个」）---- */
      if (aiPolishOriginal.value) {
        const original = aiPolishOriginal.value;
        clearPolishUndo();
        setAiDraftProgrammatically(original);
        toast(t('ai_polish_undone', '已恢复润色前的原文'), 'info');
        nextTick(() => {
          const target = settings.ai_sidebar_mode ? aiInputPageRef.value : aiInputDrawerRef.value;
          if (target && typeof target.focus === 'function') target.focus();
          else focusAiInput();
        });
        return;
      }
      const text = String(aiDraft.value || '').trim();
      if (!text) { toast(t('ai_polish_empty', '输入框是空的，先写一句要润色的话'), 'info'); return; }
      if (!settings.ai_enabled) { toast(t('ai_disabled', 'GCP-AI 还没有开启，可在设置里打开。'), 'info'); return; }
      /* ⚠️ 锁的开启必须紧挨着 try：aiInputLocked 派生自 aiPolishing，
         这里一置位输入框立刻 contenteditable=false，用户改不到草稿；
         而 finally 一定会在成功/失败/异常/提前 return（needApi 等）四条路上解锁。 */
      aiPolishing.value = true;
      try {
        const result = await bridge.tryCall('ai.polish', text);
        if (!result) { needApi('ai.polish', t('ai_polish', '润色')); return; }
        if (!result.ok) {
          toast(t('ai_polish_failed', '润色失败：') + (result.error || ''), 'error');
          return;
        }
        const polished = String(result.text || '').trim();
        if (!polished) {
          toast(t('ai_polish_failed', '润色失败：') + '（模型没有返回内容）', 'error');
          return;
        }
        /* ⚠️ 顺序很重要：**先存原文**（后端带回的 original 优先，没有就用本次送出去的 text），
           再程序化改草稿 —— 改草稿会触发上面那个 watch，靠 aiPolishApplying 标记
           才不会把刚存的原文立刻清掉。
           ⚠️ 锁定期间（aiPolishing 仍为 true）用户改不了输入框，所以这里替换草稿
              不会被"用户同时还在打字"打断；解锁统一交给下面的 finally。 */
        aiPolishOriginal.value = String(result.original || text || '');
        setAiDraftProgrammatically(polished);
        if (aiPolishOriginal.value.trim() === polished.trim()) {
          /* 模型没改（原句本来就通顺）：撤销没有意义，回到普通态，别画个假的可撤销按钮 */
          clearPolishUndo();
        }
        /* rich-ai-input 的 v-model watch 会把 DOM 文本一起换掉，光标由它自己保 */
        toast(t('ai_polished', '已润色输入框内容（未发送）'), 'success');
        nextTick(() => {
          const target = settings.ai_sidebar_mode ? aiInputPageRef.value : aiInputDrawerRef.value;
          if (target && typeof target.focus === 'function') target.focus();
          else focusAiInput();
        });
      } catch (error) {
        toast(t('ai_polish_failed', '润色失败：') + ((error && error.message) || error), 'error');
      } finally {
        /* 解锁唯一出口：不管上面走哪条 return / 抛没抛异常，输入框都会恢复可输入 */
        aiPolishing.value = false;
      }
    }

    /* ---------- 设置页「测试连接」按钮 ----------
       测的是“设置页草稿”那套配置：把输入框里当前的 Key/模型/接口地址交给后端
       ai.test_connection 发一次最小请求；成功/失败都只 toast，绝不假装成功。
       不落盘、不建会话（和润色同一设计取舍）。 */
    async function testAiConnection() {
      if (aiTesting.value) return;
      aiTesting.value = true;
      try {
        const result = await bridge.tryCall('ai.test_connection',
          String(draft.ai_provider || 'deepseek'),
          String(draft.model_name || '').trim(),
          normalizeApiBase(String(draft.api_base || '')),
          String(apiKeyDraft.value || '').trim());
        if (!result) { needApi('ai.test_connection', t('ai_test_connection', '测试连接')); return; }
        if (!result.ok) {
          toast(t('ai_test_failed', '连接失败：{err}').replace('{err}', result.error || ''), 'error');
          return;
        }
        const ms = Number(result.latency_ms) || 0;
        toast(t('ai_test_ok', '连接正常：{model}（{ms} ms）')
          .replace('{model}', result.model || '').replace('{ms}', ms), 'success');
      } catch (error) {
        toast(t('ai_test_failed', '连接失败：{err}')
          .replace('{err}', (error && error.message) || error), 'error');
      } finally {
        aiTesting.value = false;
      }
    }

    /* ---------- 托盘 ----------
       ⚠️ 菜单由**后端原生层**绘制（desktop/native/traymenu.py 分层窗口）：
          托盘菜单会超出窗口边界、且要在窗口失焦时保持最上层，HTML 做不到。
          前端只负责在需要时调用 api.window.tray_menu() 让后端弹出来。 */
    const trayMenu = ref(false);          // 保留给"后端推 HTML 菜单"的兼容路径
    const trayEl = ref(null);
    /* 托盘浮层的四项文字。
       ⚠️ 本轮英文残留扫描抓到：以前初始值是**硬编码中文**，而后端 labels 要等
          `tray` 事件（用户真的点托盘时）才带过来 → 英文界面下从启动到第一次点托盘
          这段时间里，浮层整排中文（「呼出主窗口 / 呼出搜索框 / 呼出AI / 退出」）。
       ⚠️ 语言包 nav 模块**三语早就齐全**（后端 shell.py 也是按 nav 模块取的），
          所以初始值直接 t()，不新增任何 key。
       ⚠️ 必须是 computed 语义的"每次渲染都取当前语言"，而不是 setup 时冻结一次：
          所以用函数取初值 + 切语言时由 t() 重新求值（见下面 trayLabel(key)）。 */
    const trayLabels = reactive({ show_main_window: '', show_search_box: '',
      show_ai_search: '', exit: '' });
    /** 取某一项托盘文字：后端推来的 labels 优先，否则按当前语言查语言包 */
    function trayLabel(key) {
      const fromBackend = String(trayLabels[key] || '');
      if (fromBackend) return fromBackend;
      return t(key, { show_main_window: '呼出主窗口', show_search_box: '呼出搜索框',
        show_ai_search: '呼出AI', exit: '退出' }[key] || key, 'nav');
    }
    const lastTrayPos = ref({ x: 0, y: 0 });

    /** 让后端弹出原生托盘菜单（自绘圆角菜单） */
    async function openNativeTrayMenu(x, y) {
      const result = await bridge.tryCall('window.tray_menu', x, y);
      if (result === null) return needApi('window.tray_menu', '托盘菜单');
      if (result && result.ok === false) {
        toast(t('tray_menu_failed', '弹出托盘菜单失败：') + (result.error || ''), 'error');
        return false;
      }
      return true;
    }

    function trayAction(key) {
      trayMenu.value = false;
      if (key === 'home') bridge.tryCall('window.show');
      else if (key === 'search') { bridge.tryCall('window.show'); focusSearch(); }
      else if (key === 'ai') { bridge.tryCall('window.show'); openAiFromTray(); }
      else if (key === 'exit') confirmQuit();
    }

    /* 托盘菜单显示时自动定位（v-show 保证元素常在 DOM） */
    watch(trayMenu, (val) => {
      if (val) {
        nextTick(() => {
          const el = trayEl.value;
          if (!el) return;
          const pos = lastTrayPos.value;
          const x = pos.x || window.screenX + window.outerWidth / 2;
          const y = pos.y || window.screenY + window.outerHeight / 2;
          el.style.left = Math.max(0, x) + 'px';
          el.style.top = Math.max(0, y) + 'px';
        });
      }
    });

    /* ---------- 搜索框聚焦（Ctrl+F / 全局热键 / 托盘） ---------- */
    function focusSearch() {
      /* ⚠️ 需求修复：这里以前直接 `detail.value = null` 绕过 closeDetail ——
         结果 detailPage 没清、滚动记忆没同步，列表重新挂载后 scrollTop 天然为 0，
         表现也是"从卡片界面被拉回顶端"。改成走 closeDetail()，行为与点返回一致。 */
      if (detail.value) closeDetail();
      /* ⚠️ 需求（用户原话）：「右键托盘点呼出搜索框 → 跳到搜索页，但没自动滚到最顶端」。
         根因：doGoto 会按 pageScrollMemory 把搜索页的滚动位置**恢复**成上次记住的值，
         所以停在中间、看不到顶部的搜索框。
         → 这里强制回顶：先清掉搜索页的滚动记忆（scrollToTop 内部会做），
           再置"待回顶"标记，等新页面真正挂载后（@after-enter）再回顶一次。
         ⚠️ 必须**无条件**调 scrollToTop()：当本来就在搜索页时不会走 doGoto，
            onPageAfterEnter 也就不会触发 → 那一路只能靠这里直接回顶。 */
      pendingScrollTop = true;
      scrollToTop();
      if (page.value !== 'search') doGoto('search');
      /* 需求：「点击呼出搜索栏没有自动变成输入状态」。
         ⚠️ 根因（两层，缺一不可）：
           ① **原生层**：pywebview 只在 `Form.Shown` 里给 WebView2 焦点
              （platforms/winforms.py:367-370），而从托盘呼出时窗口**早就 Shown 过了**
              （只是被 hide 起来）→ Form.Show() 不会再触发 Shown → WebView2 拿不到焦点
              → 键盘事件根本不在 WebView2 里，input.focus() 只是把 DOM 焦点设上了。
              → 这一层由后端 `frame.focus_webview()` 负责（shell.show_window 里已调用）。
           ② **DOM 层**：原生焦点到位后，还要把焦点**落到输入框**上。
           → 所以这里连着补四次（立刻 / 120ms / 320ms / 600ms）：
             原生焦点是**异步**生效的（BeginInvoke + WaitOne），JS 这边的调用
             可能比它早 → 多补几次，只要有一次窗口已激活且焦点已到位就能成功。 */
      const doFocus = () => {
        const el = searchInput.value;
        if (!el) return;
        try {
          /* ⚠️ 必须先确认 DOM 里真的有焦点 —— 否则 select() 会把"选中"状态
             设在一个没有焦点的输入框上，看起来还是"不是输入状态"。 */
          el.focus();
          if (document.activeElement === el) el.select();
        } catch (e) { /* ignore */ }
      };
      nextTick(doFocus);
      setTimeout(doFocus, 120);
      setTimeout(doFocus, 320);
      setTimeout(doFocus, 600);
    }
    /* 托盘「呼出AI」：要按当前 AI 形态分流（侧栏页 / 悬浮球抽屉），
       以前这里只写 aiOpen=true，侧栏模式下等于什么都没发生。 */
    function openAiFromTray() {
      if (!settings.ai_enabled) { toast(t('ai_disabled', 'GCP-AI 还没有开启，可在设置里打开。'), 'info'); return; }
      if (settings.ai_sidebar_mode) { doGoto('ai'); nextTick(() => focusAiInput()); }
      else { aiOpen.value = true; nextTick(() => focusAiInput()); }
    }
    function onKeydown(event) {
      if (event.key === 'F11') {
        /* 浏览器模式下 **F11 完全交给浏览器原生全屏**：
           需求原话「F11全屏也在浏览器版失效因为浏览器原生就有F11全屏」。
           这里的坑是 `event.preventDefault()`：一旦拦下来，浏览器的全屏就不会发生，
           而我们的 toggleFullscreen 是**原生窗口**命令（在浏览器里根本没有对应窗口，
           只会走 needApi 降级或失败 toast）→ 两头都没做成。
           所以浏览器模式下直接 return，不拦、不调后端，让事件正常冒到浏览器。 */
        if (window.ToolsGCP.browserMode || httpBridge.active) return;
        event.preventDefault();
        toggleFullscreen();
        return;
      }
      if (event.key === 'Escape') {
        /* 只有 F11 会完全全屏和退出完全全屏。
           原先这里有一段全屏时 Esc 退出全屏的分支，已整段删除 —— 现在 Esc 只做
           原本关闭弹层的事；即使正处在 F11 完全全屏里，Esc 也不会退出全屏。 */
        if (dialog.open) { if (dialog.cancelable) { event.preventDefault(); answer(dialog.cancelText); } return; }
        if (privacy.open) return;                        // 原版：隐私弹窗屏蔽 Esc
        /* 自绘下拉框（combo）展开时按 Esc → 只收起下拉框本身。
           ⚠️ 必须排在所有"关页面/关弹窗"分支**之前**：combo 是在弹窗打开时才挂载的，
              它的 window keydown 监听注册得比这里晚（同队列里排在后面），
              不先拦的话一次 Esc 会"下拉框和弹窗一起关"。 */
        let comboEscaped = false;
        comboOpenRegistry.forEach((c) => { if (c.open) { c.open = false; comboEscaped = true; } });
        if (comboEscaped) { event.preventDefault(); return; }
        if (pluginPage.value) { pluginPage.value = null; return; }
        if (devGuide.value) { devGuide.value = false; return; }
        if (picker.open) { picker.open = false; return; }
        if (lightbox.value) { lightbox.value = ''; return; }
        /* Releases 弹窗（从卡片详情页里点「Releases」打开的 modal）：
           需求：在 Releases 界面里按 Esc 应该**先退出 Releases 弹窗**，
           回到卡片界面，而不是越过它直接把卡片界面关掉。
           ⚠️ 这一条必须排在 detail 之前 —— 弹窗是盖在详情页之上的浮层，
              没有这个分支时 Esc 直接命中 detail 分支，弹窗还开着页面先退了。 */
        if (releasesDialog.open) { event.preventDefault(); closeReleases(); return; }
        /* task-12 需求 6：选区右键菜单开着时，Esc **先收菜单**再谈退出详情
           （与 releasesDialog 排在 detail 之前同一论证：浮层优先）。 */
        if (selMenu.value) { closeSelMenu(); return; }
        if (detail.value) { event.preventDefault(); closeDetail(); return; }
        if (selectionBar.value) { exitSelection(); return; }
        if (recording.value) { recording.value = ''; return; }
        if (trayMenu.value) { trayMenu.value = false; return; }
        /* 公告正文右键菜单：Esc 先收它（浮层优先于页面/详情） */
        if (noticeCtx.value) { closeNoticeCtx(); return; }
        /* 本轮新增（AI 区）：气泡右键菜单 / 模型弹层 / @候选 —— Esc 优先收起它们 */
        if (aiCtx.open) { closeAiCtx(); return; }
        if (aiModeOpen.value) { aiModeOpen.value = false; return; }
        if (aiModelOpen.value) { aiModelOpen.value = false; return; }
        if (aiAtOpen.value) { closeAiAt(); return; }
        /* 收藏夹右键菜单（重命名/删除）—— Esc 关掉它 */
        if (favMenu.open) { favMenu.open = false; return; }
        if (moreOpen.value) { moreOpen.value = false; return; }
        if (aiOpen.value) { aiOpen.value = false; return; }
        return;
      }
      if (event.key === 'F12') { event.preventDefault(); return; }
      if ((event.ctrlKey || event.metaKey) && String(event.key).toLowerCase() === 'f') {
        event.preventDefault();
        focusSearch();
      }
    }

    /* ---------- 启动 ---------- */
    /* 启动分步进度（出问题时能一眼看出卡在哪一步；也用于超时兜底） */
    let bootStep = 'init';
    /* 启动步骤 → 屏幕文案/进度（只有核心阶段上屏；其余只进日志）
       ⚠️ 这里刻意不逐一列每步，而是把"准备阶段"折叠成一个区间：用户不想看到
          `启动中[paths]` 这种内部名词，只想大概知道走到哪儿了。 */
    const BOOT_STAGE = {
      bridge: [10, 'boot_starting', '正在启动…'],
      appinfo: [16, 'boot_starting', '正在启动…'],
      paths: [22, 'boot_ui', '正在准备界面…'],
      settings: [30, 'boot_ui', '正在准备界面…'],
      window: [38, 'boot_ui', '正在准备界面…'],
      privacy: [44, 'boot_starting', '正在启动…'],
      ready: [50, 'boot_ui', '正在准备界面…'],
      render: [58, 'boot_ui', '正在准备界面…'],
    };

    function setStep(name) {
      bootStep = name;
      const stage = BOOT_STAGE[name];
      if (stage) {
        bootText.value = t(stage[1], stage[2]);
      } else {
        /* 非核心步骤：界面上保持当前那句话（不再刷成"启动中[xxx]"这种内部步骤名，
           用户只想知道大概走到哪儿了）；排查仍然靠 document.title + [boot] step= 日志。
           ⚠️ 这里**不写任何兜底文案**：bootText 一开始就是"正在启动…"，不会为空。 */
        if (!bootText.value) bootText.value = t('boot_starting', '正在启动…');
      }
      /* ⚠️⚠️ 本轮修复「浏览器模式标签页标题只能是 ToolsGCP，右边还有 " · render"，
         给我删除」：这里以前会把**启动步骤名**拼进 document.title（排查启动卡死用的），
         而 boot 的最后一步正好叫 `render`（8893 行 `setStep('render')`），
         走完之后再没人改回来 → 浏览器模式下页签标题**永久**显示
         `ToolsGCP · render`（桌面 WebView2 没有页签，所以只在浏览器模式暴露）。
         标题是用户能看见的东西，不能拿来当调试面板：现在**恒等于 'ToolsGCP'**。
         启动步骤仍然照旧写进 bootText（界面上的"启动中[xxx]"）和
         [boot] step= 日志（log.client），排查能力一点没丢 ——
         要查卡在哪儿看那两处，别看页签。 */
      try { document.title = 'ToolsGCP'; } catch (e) {}
      try { if (bridge.ready) bridge.call('log.client', 'info', '界面', '[boot] step=' + name).catch(function(){}); } catch (e) {}
    }

    /* 收尾启动画面：100% → 下一帧淡出（幂等：资源落定与 9 秒兜底都会调）
       ⚠️ 必须幂等：快机器上资源 100ms 就回来了，兜底定时器 9 秒后还会再调一次。 */
    let bootFinished = false;
    function finishBoot() {
      if (bootFinished) return;
      bootFinished = true;
      bootText.value = t('boot_finishing', '即将完成…');
      setTimeout(() => { booting.value = false; }, 200);
    }

    /* ---------- 法律同意状态检查（纯本地读取，**绝不联网**） ----------
       同意记录 = `<数据根>/config/privacy_policy.json`（带哈希校验，后端同一份文件）。
       ⚠️ 需求（本轮修复）：协议窗口必须**最高优先级** —— 每次启动第一步就校验它，
          而且它不能排在任何网络操作（云端资源库/AI/公告）之后。以前的启动顺序是
          "先拉完 i18n/AI/云端资源库，最后才 checkPrivacyThenNotices"，网络一差
          协议窗就永远出不来。现在它是 boot() 的第一道闸门。 */
    async function checkPrivacyState() {
      const state = await bridge.tryCall('app.privacy_state');
      const agreed = (state && state.ok) ? !!state.agreed : !!readLocal('privacyAgreed', false);
      if (agreed) writeLocal('privacyAgreed', true);
      return agreed;
    }

    /* ---------- 启动自检：样式表是不是真的到位了（需求②） ----------
       症状（用户原话）：「启动后 UI 被堆叠在一起、样式是最基础底层的」，
       偶发，50 多次遇到一次。
       真因：13 个 CSS 里只要少了 variables.css（设计变量）和 base.css（reset），
             页面就退回浏览器默认排版 —— 正是「都堆在一起、最基础底层样式」的样子。
       以前不会自愈：app.js 里没有重挂逻辑，资源一旦没加载成功，
             界面就一直裸奔到用户手动刷新为止。
       做法：盯住每个 CSS <link> 的 load / error 事件，
             **明确报错**的才就地重挂（改 href 加时间戳，位置不动 ⇒ CSS 覆盖顺序不变），
             重挂完再复查；还是不行才弹提示告诉用户。
       ⚠️ 三个坑，都是这次真踩到的：
         1) **不能用「link 元素在不在」当判据**。link 在 HTML 解析时就有了，
            样式表还没下载完 —— 早判一次会把「还在路上」当成「没加载」，
            反而把 13 个 CSS 全部再请求一遍（把偶发的排队问题变成常态）。
         2) **不能用 document 的 load 事件当结算点**。各浏览器/jsdom 对
            「load 触发时样式表是否已进 document.styleSheets」的处理不一致，
            早判同样会误判。唯一可靠的信号是 link 自己的 load / error 事件。
         3) **不能用「某个 CSS 变量能不能算出来」当判据**。jsdom 等无布局环境
            不支持自定义属性取值，会把一切误判成「样式没加载」。
            所以判据只用「link 有没有报 error」。 */
    const STYLE_GUARD_FILES = [
      '/static/css/variables.css',
      '/static/css/base.css',
      '/static/css/components.css',
      '/static/css/layout.css',
      '/static/css/animations.css',
      '/static/css/overlays.css',
      '/static/css/fav-fixes.css',
      '/static/css/settings-fixes.css',
      '/static/css/download-fixes.css',
      '/static/css/r22-fixes.css',
      '/static/css/r24-fixes.css',
      '/static/css/download-ui.css',
      '/static/css/ai-fixes.css',
    ];
    /* rel -> 'loading' | 'ok' | 'fail' */
    const styleStates = Object.create(null);
    function styleLinkElement(rel) {
      const links = document.getElementsByTagName('link');
      for (let i = 0; i < links.length; i += 1) {
        const l = links[i];
        const relAttr = (l.getAttribute('rel') || '').toLowerCase();
        if (relAttr.indexOf('stylesheet') < 0) continue;
        const href = l.getAttribute('href') || '';
        if (href.indexOf(rel) >= 0) return l;
      }
      return null;
    }
    function watchStyleLink(link, rel) {
      if (!link) return;
      if (link.__tgStyleWatched) return;
      link.__tgStyleWatched = true;
      if (styleStates[rel] === undefined) styleStates[rel] = 'loading';
      link.addEventListener('load', function () { styleStates[rel] = 'ok'; });
      link.addEventListener('error', function () { styleStates[rel] = 'fail'; });
      /* 已经加载完的（脚本晚于 CSS 执行时 link.sheet 已存在）直接记 ok */
      if (link.sheet) styleStates[rel] = 'ok';
    }
    function missingStyleFiles() {
      /* 只有两种算「缺」：link 元素压根不在，或者 link 明确报了 error。
         还在 loading 的一律不算（那是正常下载中）。 */
      return STYLE_GUARD_FILES.filter(function (rel) {
        const link = styleLinkElement(rel);
        if (!link) return true;
        return styleStates[rel] === 'fail';
      });
    }
    function reloadStyleFile(rel) {
      const stamp = '?tg=' + Date.now();
      let link = styleLinkElement(rel);
      if (link) {
        /* 就地改写 href：位置不动 ⇒ CSS 覆盖顺序不变
           （追加到 head 末尾会把补丁样式排到基础样式前面，覆盖关系就反了） */
        styleStates[rel] = 'loading';
        link.setAttribute('href', rel + stamp);
        watchStyleLink(link, rel);
        return link;
      }
      /* 元素本身都不在了（被人动过）：按标准顺序插到它该在的位置 */
      link = document.createElement('link');
      link.setAttribute('rel', 'stylesheet');
      link.setAttribute('href', rel + stamp);
      const idx = STYLE_GUARD_FILES.indexOf(rel);
      let anchor = null;
      for (let i = idx + 1; i < STYLE_GUARD_FILES.length && !anchor; i += 1) {
        anchor = styleLinkElement(STYLE_GUARD_FILES[i]);
      }
      if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(link, anchor);
      else (document.head || document.documentElement).appendChild(link);
      watchStyleLink(link, rel);
      return link;
    }
    function waitForStyles(links, timeoutMs) {
      return new Promise(function (resolve) {
        if (!links.length) { resolve(false); return; }
        let left = links.length;
        let done = false;
        const finish = function () { if (!done) { done = true; resolve(true); } };
        const timer = setTimeout(finish, timeoutMs || 8000);
        links.forEach(function (link) {
          const one = function () {
            left -= 1;
            if (left <= 0) { clearTimeout(timer); finish(); }
          };
          link.addEventListener('load', one, { once: true });
          link.addEventListener('error', one, { once: true });
        });
      });
    }
    async function ensureStylesLoaded() {
      /* 先把已有的 13 个 link 都挂上 load/error 监听 */
      STYLE_GUARD_FILES.forEach(function (rel) { watchStyleLink(styleLinkElement(rel), rel); });
      /* 等一轮：给还在路上的样式表时间落定（不阻塞启动，只是让判定更准） */
      await waitForStyles(
        STYLE_GUARD_FILES.map(styleLinkElement).filter(function (l) { return !!l; }),
        6000
      );
      const missing = missingStyleFiles();
      if (!missing.length) return true;
      console.warn('[ToolsGCP] 样式表加载失败，准备就地重挂：', missing.join(', '));
      const links = [];
      missing.forEach(function (rel) { links.push(reloadStyleFile(rel)); });
      await waitForStyles(links, 8000);
      const still = missingStyleFiles();
      if (still.length) {
        console.warn('[ToolsGCP] 样式表重挂后仍然缺失：', still.join(', '));
        toast(t('style_load_failed', '界面样式未能完整加载，已尝试重新载入。'), 'warning');
        return false;
      }
      return true;
    }

    /* ★★ 窗口显示的唯一保险丝：app.ready 必须**送达**后端。
       背景（用户原话：「网速慢/无网状态下第一次启动，任务栏和托盘都已经出现程序，
       但是程序窗口就是不出现」）：
         · 冷启动 WebView2 首次初始化要 8 秒上下，pywebview 的 api 注入往往**晚于**
           boot() 跑到那几处 app.ready —— bridge.tryCall 在 api 还没挂上时是
           **静默返回 null**（调用根本没发出去，不报错）；
         · 旧版没有任何补发：ready 丢了 → 后端只能等它自己 20 秒的兜底超时，
           期间任务栏/托盘图标都已出现（建窗时 pywebview 真的 Show/Hide 过一轮），
           窗口却停在屏幕外 → 用户看到的就是"程序启动了但窗口不弹"。
       现在：没送达就退避重试（0.2s 起指数递增、封顶 2s，最长约 30 秒），
       api 一旦注入好，下一跳重试立刻生效；成功后永不再发。 */
    var readyDelivered = false;
    var readyTimer = 0;
    var readyDelay = 200;
    var readyTries = 0;
    function reportReady() {
      if (readyDelivered) return Promise.resolve(true);
      readyTries += 1;
      return Promise.resolve(bridge.tryCall('app.ready')).then(function (res) {
        if (res && res.ok) {
          readyDelivered = true;
          if (readyTimer) { clearTimeout(readyTimer); readyTimer = 0; }
          console.log('[boot] app.ready 已送达后端（第 ' + readyTries + ' 次）');
          return true;
        }
        /* 封顶：约 16 次（200ms 起指数退避、单次最长 2s → 覆盖 ~25 秒）。
           后端有 20s 总兜底 + 6s 资源加载兜底，重试再久也撞不过它们；
           真后端连 app.ready 都没有（旧版本）时这里也只是安静收手。 */
        if (!readyTimer && readyTries < 16) {
          readyTimer = setTimeout(function () {
            readyTimer = 0;
            readyDelay = Math.min(readyDelay * 2, 2000);
            reportReady();
          }, readyDelay);
        }
        return false;
      }, function () { return false; });
    }

    /* boot_pack 的落地：字段形状与各单独接口**逐字一致**（后端就是直接复用那些
       方法拼的），所以这里等于把四个老函数各自的赋值搬进一个函数。 */
    function applyBootPack(pack) {
      const infoRes = pack.info;
      if (infoRes && infoRes.ok) {
        info.app = infoRes.app || 'ToolsGCP';
        info.version = infoRes.version || '';
        info.python = infoRes.python || '';
        info.dataDir = infoRes.data_dir || '';
        info.configDir = infoRes.config_dir || '';
        info.language = infoRes.language || '简体中文';
        info.args = Array.isArray(infoRes.args) ? infoRes.args : [];
        if (infoRes.frameless !== undefined && infoRes.frameless !== null) {
          info.frameless = !!infoRes.frameless;
          try { document.documentElement.classList.toggle('is-native-chrome', !infoRes.frameless); } catch (e) {}
        }
      }
      const pathsRes = pack.paths;
      if (pathsRes && pathsRes.ok) {
        info.configDir = pathsRes.config_dir || info.configDir;
        info.dataDir = pathsRes.data_dir || info.dataDir;
        info.resourceFile = pathsRes.resource_file || info.resourceFile;
        info.version = pathsRes.version || info.version;
      }
      const setRes = pack.settings;
      if (setRes && setRes.ok && setRes.settings) {
        Object.assign(settings, setRes.settings);
        settingsLoaded.value = true;
        /* 与 loadSettings 逐字同口径的两个历史默认值修复（空串下拉显示空白） */
        if (!String(settings.search_source || '').trim()) settings.search_source = 'Github';
        if (!String(settings.download_source || '').trim()) settings.download_source = 'Github';
        applyAppearance();
      }
      bootPackPrivacy = (pack.privacy && pack.privacy.ok) ? pack.privacy : null;
    }
    var bootPackPrivacy = null;

    async function boot() {
      try {
        setStep('bridge');
        await bridge.init();
        bridge.call('log.client','info','界面','[boot] bridge ready=' + bridge.ready).catch(function(){});
        /* ★★ 本轮启动优化（用户：「程序经常在启动时未响应，经常发生」）：
           旧 boot() 开头是 **四次串行** js_api 往返（app.info → settings.paths →
           settings.get → window.state）。每一次往返都要"起 Python 线程执行 +
           回 GUI 线程 evaluate_js 投递结果"，而冷启动阶段 GUI 线程正被 WebView2
           初始化压着 —— 慢机器上这四次能累计 1~3 秒，全花在"窗口还没显示"之前，
           体感就是"双击图标半天没反应 / 任务栏图标闪一下白边未响应"。
           后端新增 app.boot_pack 一次带回 info+paths+settings+privacy；旧后端没有
           这个接口时 tryCall 返回 null → **原样退回**下面四个老调用（向后兼容）。 */
        setStep('appinfo');
        const pack = await bridge.tryCall('app.boot_pack');
        if (pack && pack.ok) {
          applyBootPack(pack);
        } else {
          await loadAppInfo();
          await loadPaths();
          setStep('settings');
          await loadSettings();
        }
        Object.assign(draft, settings);
        /* ★ 同步窗口状态（maximized/fullscreen）挪出关键路径：它只是给根节点挂
           类名用的，不参与任何显示判定 —— 但**必须**在启动时来一次（旧版 await 在
           boot 头部白占一次往返）。fire-and-forget：迟到也无妨，window.state 事件
           和 done 之后的 syncWindow 都会再校准。 */
        syncWindow().catch(function () {});

        const bundle = await bridge.tryCall('i18n.bundle');
        if (bundle && bundle.ok) flattenI18n(bundle);
        /* 样式自检 + 自愈（需求②）：样式表缺了就地重挂，别让界面一直裸奔。
           放在 i18n 之后是为了能拿到三语文案（style_load_failed）。 */
        /* 不 await：自检要等文档 load 结算，await 会把启动流程卡住 */
        try { ensureStylesLoaded().catch(function (error) { /* 自检失败不影响启动 */ }); } catch (error) {}

        /* ========== ① 法律闸门：先于一切网络资源加载（本轮需求） ==========
           未同意 → 协议窗置顶显示，**窗口照常放出来**（app.ready 提前上报），
           后面的云端加载/AI/公告全部不跑（acceptPrivacy 里再继续）。
           ⚠️ 这就是"网络差时协议窗不出现"和"任务栏有图标但窗口不弹"的根治：
              旧版把 app.ready 押在 boot 末尾，云端一卡 + 启动页遮罩（z190）盖住
              协议窗（z140）→ 用户对着一个永远不出现的窗口等同意按钮。 */
        setStep('privacy');
        /* pack 带回的同意状态与 checkPrivacyState 同语义：同意过就顺手把本地
           镜像也写上（老浏览器/无 localStorage 时 writeLocal 自己会吞异常）。 */
        let agreed;
        if (bootPackPrivacy) {
          agreed = !!bootPackPrivacy.agreed;
          if (agreed) writeLocal('privacyAgreed', true);
        } else {
          agreed = await checkPrivacyState();
        }
        if (!agreed) {
          privacy.open = true;
          booting.value = false;            // 撤掉启动页遮罩，让协议窗成为可见的最顶层
          setStep('consent');
          try { document.title = 'ToolsGCP'; } catch (e) {}
          reportReady();                     // 窗口放出来（带重发保险，见 reportReady）
          return;                            // 同意后由 acceptPrivacy() 继续启动
        }
        /* 已同意：也要**立刻**上报 ready —— 窗口显示不再等云端资源。
           （网络差时最多看到"正在寻找资源文件…"遮罩 + 重试按钮，窗口本身一定出来；
             后端 _try_show 自己还会等启动画面，这里提前调不会闪半成品。） */
        setStep('ready');
        reportReady();
        await continueBoot();
      } catch (error) {
        console.error('[ToolsGCP] boot failed at step=' + bootStep, error);
        booting.value = false;
        /* ⚠️ 启动脚本自己崩了也**必须**放窗口出来：页面资源已加载完毕，
           用户至少看得见界面、看得见错误提示，绝不能退化成"图标在、窗口不弹"。 */
        reportReady();
        bootText.value = '启动失败（' + bootStep + '）：' + (error && error.message ? error.message : error);
        /* 本轮多语言：硬编码中文 → t()（"启动异常（step）：" 这段以前英文界面也露中文） */
        toast(t('boot_error_prefix', '启动异常（') + bootStep + '）：'
          + (error && error.message ? error.message : error), 'error');
      }
    }

    /* ---------- ② 同意（或已同意）之后的其余启动步骤 ----------
       ⚠️ 这一段整体**不允许**挡窗口显示：窗口在 boot() 里已经放出来了。
       网络类加载都有超时/后台兜底；任何一步失败都只降级、不回退启动页。 */
    let bootResumed = false;
    async function continueBoot() {
      if (bootResumed) return;
      bootResumed = true;
      try {
        /* ⚠️ 不要把 booting 设回 true：从"刚点同意"进来时启动遮罩已撤、界面已可见，
           再盖回去就是"同意后反而又黑一次启动页"；已同意的老用户路径里 booting
           本来就还是 true，到 render 步自然撤。 */
        /* "/" 命令提示（插件制作辅助）：启动预取一次，之后靠 watch 重载 */
        try { await loadAiHints(); } catch (error) { /* 提示加载失败不影响启动 */ }
        /* 模型切换 UI 的候选（按 Key 过滤后的服务商/模型）：启动预取一次，
           之后填 Key / 换服务商时靠 watch 重载（见下面 ai_provider / apiKeyConfigured） */
        try { await loadAiModelChoices(); } catch (error) { /* 拿不到就隐藏胶囊 */ }
        /* 「更多筛选」候选预取（按当前界面语言，见 loadFilterOptions 的注释） */
        try { await loadFilterOptions(); } catch (error) { /* 拉不到就用本地候选，筛选照常可用 */ }
        const keyState = await bridge.tryCall('settings.api_key_state',
          String(settings.ai_provider || 'deepseek'));
        if (keyState && keyState.ok) apiKeyConfigured.value = !!keyState.configured;
        /* ⚠️⚠️ 本轮（用户要求 API Key 加密 + 界面不回显）：启动时**不再**调用
           settings.reveal_api_key 把明文塞进输入框。已保存的 Key 只以 DPAPI 密文
           存在本机（settings_manager 的 api_key_enc_<槽位>），界面拿到的只有
           "配没配"这一个布尔值；输入框用占位文案告诉用户"已填写（已加密）"，
           想换 Key 时直接输入新的即可（见 apiKeyPlaceholder / apiKeySavedHint）。 */
        apiKeyDraft.value = '';
        apiKeySnapshot.value = '';
        try { await loadAiOnBoot(); } catch (error) { /* AI 不可用不影响启动 */ }
        const hotkeyState = await bridge.tryCall('shell.environment');
        if (hotkeyState && hotkeyState.ok && hotkeyState.hotkeys) {
          Object.keys(hotkeyState.hotkeys).forEach((k) => {
            const one = hotkeyState.hotkeys[k] || {};
            hotStatusMap[k] = (!one.ok && one.text) ? ('✕ ' + one.text) : '';
          });
        }

        /* + + 云端模式启动加载 —— 。
           ⚠️ 曾经要求没加载出来就不让程序显示出来——
              那正是用户抱怨的云端就卡着不让程序窗口出现。
           ⚠️ 改成：**窗口照常出来**。
              · 云端失败 → **不再 await openDialog**（那个阻塞对话框就是窗口出不来的元凶），
                改成弹一个非阻塞 toast + 资源库退回本地，程序照常可用；
              · 启动后再**后台**刷新一次云端（不 await，绝不挡首屏）。
           ⚠️ 加载**成功**后：正常进主界面；资源库已在搜索页/定制页/收藏页就绪，
              那一侧的遮罩（resourceLoading）不需要出现（加载已经完成了）。
           ⚠️ 本地模式 / 已有可用缓存时 cloud_prepare 会立即返回（skipped=true），不拖慢启动。 */
        /* ⚠️⚠️ 需求（用户原话）：「所有云端 ToolsGCP-Resources.json 加载或本地加载
           ToolsGCP-Resources.json 应该显示在**搜索页或者定制页的空白处**显示这个加载 UI，
           **而不是显示在启动页上**」。
           → 关键：**启动页必须在资源库加载开始之前就撤掉**，
             否则启动页（z190，盖在内容区上）会把页面内的那块加载 UI **整个盖住**，
             用户看到的就还是"启动页"而不是"搜索页/定制页里的加载提示"。
           → 所以这里先把启动页撤了（booting=false），并让搜索页先显示出来，
             加载 UI 就会**长在搜索页的空白中心**。
           ⚠️ 顺序：先定好起始页（page.value）再撤启动页 —— 否则撤的瞬间
             页面还没切好，用户会看到一瞬间的空白。 */
        const map = { 搜索: 'search', 定制页: 'customize', 收藏: 'favorites',
          部署: 'deploy', 应用部署: 'deploy', 设置: 'settings', Github: 'github', 查看日志: 'log',
          公告: 'notice', 反馈: 'feedback', GCP工坊: 'workshop', 插件: 'plugins', 提交软件: 'maker' };
        page.value = map[settings.default_page] || 'search';
        if (info.args.indexOf('--open-settings') >= 0 || settings.open_settings_on_restart) {
          page.value = 'settings';
          await bridge.call('settings.set', 'open_settings_on_restart', false).catch(() => {});
          settings.open_settings_on_restart = false;
        }
        /* ⚠️ 本轮**删掉**了"等原生启动画面播完再撤启动遮罩"这段等待。
           旧写法是 `app.splash_remaining` 拿一个毫秒数然后 sleep 等够 —— 那是配合
           已删除的"启动动画时长"设置项用的。现在不能再等，原因是死锁：
             原生画面的存活期 = 「入口顶起 → **主窗口显示之后** → 关掉」，
             而主窗口显示要等前端上报 ready，ready 就在这段代码之后；
             前端再等画面关 = 画面等前端 = 谁也等不到谁（只能靠后端超时兜底挣脱）。
           后端已经把 app.splash_remaining 恒返回 0、app.splash_wait 立刻放行，
           所以即使有缓存的旧前端在调它们也不会卡住；这里直接把等待整段去掉。 */
        /* ★★★ 撤掉启动页 —— 从这一刻起，用户看到的是**真实的页面**，
           资源库加载提示会长在搜索页/定制页的空白中心（而不是启动页上）。 */
        setStep('render');
        /* ★ 第 28 轮③：这里**不再立刻撤掉启动画面**，而是把它继续当"加载画面"用：
           用户要的就是"先看加载画面、资源好了再进界面"。窗口本身早就放出来了
           （app.ready 已在 boot() 里提前上报），所以不违反"窗口要尽快出现"。
           ⚠️ 撤画面统一走 finishBoot()：资源落定 → 100% → 淡出；另有 9 秒兜底。 */
        bootText.value = t('boot_resources', '正在加载资源库…');
        setTimeout(() => { finishBoot(); }, 9000);      /* 兜底：绝不把启动画面挂死 */
        await nextTick();
        measureViewport();

        bootText.value = t('boot_cloud', '正在加载云端资源库…');
        /* ⚠️ 云端模式：把页面内的加载提示**排上**（超过 400ms 才真的显示出来，
           见 showResourceLoadingSoon 的注释 —— 缓存命中时 100ms 就好了，
           立刻显示反而会在窗口出现的那一瞬间闪一下，就是用户说的"不见了"的另一种表现）。
           ⚠️ 此刻启动页已经撤了 → 这个提示显示在**搜索页/定制页的空白中心**。 */
        const cloudMode = String(settings.resource_source || 'cloud') === 'cloud';
        if (cloudMode) {
          resourceLoadFailed.value = false;
          showResourceLoadingSoon();
        }
        let cloudBoot = null;
        /* ⚠️ 需求修复（网络差窗口不弹出）：cloud_prepare 内部要等多个网络往返
           （不通时可能几十秒），以前**没有超时**地 await 它，窗口只能干等
           （后端 20 秒兜底超时也才勉强救场）。加 12 秒超时：超时就按"没加载出来"
           继续启动（窗口照常出来，失败走下面既有的非阻塞提示 + 后台重试）。 */
        try {
          cloudBoot = await Promise.race([
            bridge.tryCall('resources.cloud_prepare', false),
            new Promise((resolve) => { setTimeout(() => resolve(null), 12000); }),
          ]);
        } catch (error) { cloudBoot = null; }
        bootText.value = t('boot_resources', '正在加载资源库…');
        /* ⚠️ loadResources() 本身要等网络往返（云端不通时会等到超时）。
           启动是关键路径，不能让它无限期拖住窗口 —— 加一道 8 秒的超时保护：
           超时就用本地资源库继续启动（程序照常出来，后面还能在设置里重试）。
           ⚠️ 只在 boot 的调用点加保护，**不改 loadResources() 本身**
              （设置页/搜索页还在用它，那里等久一点是对的）。 */
        await Promise.race([
          loadResources(),
          new Promise((resolve) => { setTimeout(resolve, 8000); }),
        ]);
        finishBoot();
        const cloudFailed = !!(cloudBoot && cloudBoot.ok === false && !cloudBoot.skipped);
        if (cloudFailed) {
          /* ⚠️ **不再阻塞**。
             以前这里是 `await openDialog(...)` —— 那个加载失败对话框会把启动卡住，
             窗口一直不出现（云端就卡着不让程序窗口出现）。
             现在：正常进主界面，失败只用一个**非阻塞 toast** 告诉用户，
             外加 hintSwitchMirror() 那个 6 秒的去换镜像源提示。
             ⚠️ 失败**不**改用户的设置（resource_source 仍保持 cloud）——
                后台那次刷新成功了就自动有内容了；失败的话设置页里能重试/切本地。 */
          const reason = cloudErrorText(cloudBoot.error, cloudBoot.error_key) || cloudBoot.error || '';
          bootText.value = t('resource_load_failed', '云端资源库加载失败：{err}')
            .replace('{err}', reason);
          /* ⚠️ 失败必须**立刻**显示（不走 400ms 延迟）：模板是
             `v-if="resourceLoading"`，而"加载超时"这件事经常**发生得很快**
             （DNS 直接失败 / 后端秒回错误）→ 如果只把 resourceLoadFailed 置真、
             闹钟却还没响，那块 UI 根本没挂上，用户看不到"加载资源文件用时过长"
             这句话和两个按钮 —— 等于把唯一的补救入口藏起来了。 */
          showResourceLoadingNow();
          resourceLoadFailed.value = true;
          /* 非阻塞提示（toast 自己会消失，不挡界面） */
          toast(t('resource_load_failed', '云端资源库加载失败：{err}').replace('{err}', reason),
            'warning', '', { duration: 6000 });
          hintSwitchMirror();
        } else {
          hideResourceLoading();
        }
        await loadFavorites();
        await runQuery();
        loadDeployList();
        Object.assign(draft, settings);
        applyAppearance();
        const chosen = new Set(settings.customize_interests || []);
        selectedInterests.value = interestCatalog.value.filter((i) => chosen.has(i.name));

        /* ⚠️ 起始页 / 启动页 / 启动动画等待 **已经挪到资源库加载之前**了
           （见上面"撤掉启动页"那段）—— 需求是「加载提示显示在搜索页/定制页的空白处，
           而不是显示在启动页上」，所以启动页必须在加载开始**之前**就撤掉。
           ⚠️ 这里只剩首帧的排版收尾。 */
        await nextTick();
        /* 首帧 segmented 的滑动块必须在这里对齐一次：
           之前的 syncSegThumbs 只挂在 watch 与切页上，首次进来的视图切换器没有 thumb，
           `.seg-item.is-on` 的兜底底色就会露出来（用户说的"每项下面像选中的底"）。
           字体加载会改文字宽度，再补一拍。
           首帧 / 字体就位都走 immediate —— 页面刚出来时不该看到滑块"滑"一下。 */
        nextTick(() => syncSegThumbs(true));
        setTimeout(() => syncSegThumbs(true), 120);
        try {
          if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => syncSegThumbs(true));
        } catch (e) { /* ignore */ }
        /* 首帧画完 → **再**上报一次 ready（幂等，boot 里已提前调过；这里是保险），
           再把窗口摆回工作区正中（消除建窗时的偏移） */
        await reportReady();   // 幂等保险：boot 里已提前调过；这里再确认一次送达
        const centered = await bridge.tryCall('window.center');
        if (!centered) syncWindow();
        /* ⚠️ 法律闸门已在 boot() 最前面过掉了（agree 之后才会走到这里），
           这里只做"同意之后才拉公告"的第二道（顺序仍然是：先同意、后公告）。 */
        await loadNotices(false);

        /* ⚠️ 本轮需求：「自动检查更新…开启程序后如果发现新版本从右上角滑动出来」——
           挂在公告拉取之后（法律闸门已过关、界面已就绪），且**绝不 await**：
           GitHub 不通时这条要等几十秒，挡启动就是事故（与云端资源库同一纪律）。
           mode=off（设置里关了）时 autoCheckUpdate 内部立刻返回，一个请求都不发。 */
        setTimeout(() => { autoCheckUpdate().catch(() => {}); }, 1200);

        loadPlugins(false);
        /* 后台读一次云端资源库状态（有接口才显示；不阻塞启动） */
        readCloudStatus().catch(() => { /* 接口不存在 / 出错都静默降级为不显示 */ });
        /* 启动时**自动重新更新一遍**云端资源库（前提：资源来源 = 云端）。
           ⚠️ **绝对不能 await**：云端不通时可能要等几十秒，会把窗口卡住不出现。
              这里用 setTimeout(0) 把它甩到后台跑，窗口照常出来。
           ⚠️ 用安静版refreshCloudLibraryQuiet —— 失败只更新设置页那一行状态，
              不弹 toast（boot 里已经提示过"加载失败"了，别再弹第二遍）。 */
        if (String(settings.resource_source || 'cloud') === 'cloud') {
          setTimeout(() => { refreshCloudLibraryQuiet().catch(() => {}); }, 0);
          /* 云端图标（icon.zip）：和 JSON 同一个 Release，同样后台同步、同样安静
             （接口是**立刻返回**的异步版，跑完推 cloud-icons-updated）。
             ⚠️ 不 await：网络不通时它可能要等几十秒，绝不能挡启动。 */
          setTimeout(() => { syncCloudIconsQuiet().catch(() => {}); }, 0);
        }
        /* 读一次默认下载目录（占位提示要显示真路径；不阻塞启动） */
        loadDownloadDefaultDir().catch(() => { /* 没有 downloader 域就退回通用文案 */ });
      } catch (error) {
        console.error('[ToolsGCP] boot failed at step=' + bootStep, error);
        booting.value = false;
        bootText.value = '启动失败（' + bootStep + '）：' + (error && error.message ? error.message : error);
        /* 本轮多语言：硬编码中文 → t()（"启动异常（step）：" 这段以前英文界面也露中文） */
        toast(t('boot_error_prefix', '启动异常（') + bootStep + '）：'
          + (error && error.message ? error.message : error), 'error');
      }
    }

    /* ---------- 启动闸门（法律同意 → 公告） ----------
       ⚠️ 本轮重构：法律同意校验挪到了 boot() **最前面**（第一步、纯本地、不依赖网络），
       这个函数保留给外部（emit/旧调用点）做"再确认一次"的入口：
         · 已同意 → 直接拉公告 + 兜底续跑 continueBoot（防止早期异常路径没走到）；
         · 未同意 → 置顶弹协议窗（同 boot()），同意后由 acceptPrivacy 续跑。 */
    async function checkPrivacyThenNotices() {
      const agreed = await checkPrivacyState();
      if (!agreed) {
        privacy.open = true;
        booting.value = false;
        reportReady();
        return;
      }
      await continueBoot();
      await loadNotices(false);
    }

    let resizeObserver = null;
    /* 收藏页网格的 ResizeObserver（见 onMounted 里的用法） */
    let favGridObserver = null;
    onMounted(() => {
      applyAppearance();
      /* 服务商档案 + 厂商清单：启动就先拉一次。
         ⚠️ 为什么在 mounted 就拉而不是等进设置页：`default_page` 可能直接是"设置"，
           那时 watch(page) 不会触发（page 一开始就是 settings）→ 卡片列表会空着，
           用户看到的是一块空白的服务商区域。
         两个调用都 fire-and-forget（失败有各自的降级，不阻塞启动）。 */
      loadAiProviderCatalog();
      loadAiProfiles();
      window.addEventListener('keydown', onKeydown);
      /* 框选气泡文字后的 Ctrl+C（见 onGlobalCopy 的长注释）。
         ⚠️ 必须**捕获阶段**：输入法候选、以及页面里其它 keydown 处理器都注册得更晚，
            捕获阶段才能保证我们看到的 event.key 是用户真正按下的那个键。 */
      document.addEventListener('keydown', onGlobalCopy, true);
      window.addEventListener('resize', onWindowResize);
      /* 窗口重新获得焦点时重读一次真实窗口状态（syncWindow → window.state）。
         ⚠️ 为什么需要：最大化在系统里是「还原点 + 最大化标志」两个东西，用户用
            Win+↑ / 双击标题栏 / 系统菜单切换时不一定有 resize 事件（尺寸没变的那种，
            比如最大化 ↔ F11 全屏），win.maximized 一旦漂了，前端就会在最大化窗口上
            继续显示缩放热区 —— 正是用户报的「全屏后靠近边缘变成拉伸光标」。 */
      window.addEventListener('focus', () => { syncWindow(); });
      /* 「回到顶部」悬浮球（见 backToTop 的长注释）：
         ⚠️ scroll 不冒泡 ⇒ 必须捕获阶段；abort 那三个用冒泡就够（只为用户输入服务）。 */
      document.addEventListener('scroll', onAnyScrollForBall, true);
      window.addEventListener('wheel', onUserScrollInput, { passive: true });
      window.addEventListener('touchstart', onUserScrollInput, { passive: true });
      document.addEventListener('keydown', onUserScrollInput);
      /* 插件配置页 iframe 按 Esc → 它 postMessage 给宿主，这里把配置页收起回到插件列表。
         同时也用于主题同步之外的少量协议（保留 type 前缀 toolsgcp-）。 */
      window.addEventListener('message', (event) => {
        const data = event && event.data;
        if (!data || typeof data !== 'object') return;
        if (data.type === 'toolsgcp-close-plugin' && pluginPage.value) {
          pluginPage.value = null;
        }
      });
      /* ---------- Ctrl/⌘/中键 点链接的兜底（需求 ①：偶发"跳到新窗口出去了"） ----------
         WebView2 对「Ctrl+点 <a href>」有**自己的**处理：会尝试开新窗口/新标签。
         只要页面上有任何一处真实 <a href="http…">，Ctrl+点就有概率走 WebView2 的原生分支，
         表现就是"时不时弹出一个窗口，而不是只交给系统浏览器"。
         这里在**捕获阶段**拦下所有带修饰键的链接点击，统一 preventDefault 并走 openLink，
         从源头保证只有一条路径（系统浏览器 + 程序内不开窗）。顺带记一条日志便于复现。 */
      const onModifiedLinkClick = (event) => {
        /* 右键同样会派发 auxclick：Ctrl+右键 也不该走"打开链接" */
        if (!event || event.button === 2) return;
        if (!(event.ctrlKey || event.metaKey || event.button === 1)) return;
        const target = event.target;
        const anchor = target && target.closest ? target.closest('a[href]') : null;
        if (!anchor) return;
        const href = anchor.getAttribute('href') || '';
        if (!/^https?:/i.test(href)) return;
        event.preventDefault();
        event.stopPropagation();
        try {
          bridge.call('log.client', 'info', '界面',
            'Ctrl+点击链接（已拦截 WebView2 原生开窗）: ' + href).catch(() => {});
        } catch (error) { /* 日志失败不影响打开 */ }
        openLink(href, event);
      };
      window.addEventListener('click', onModifiedLinkClick, true);
      window.addEventListener('auxclick', onModifiedLinkClick, true);
      window._onModifiedLinkClick = onModifiedLinkClick;
      /* ---------- Markdown 渲染产物里的链接（公告 / 更新说明） ----------
         渲染器生成的 <a class="md-link" data-mdlink="…"> **没有 href**，所以浏览器
         不会导航、也不会触发上面那条"Ctrl+点 <a href> 被 WebView2 开新窗口"的问题；
         这里在捕获阶段统一拦下来交给 openLink（→ shell.open_url → 系统浏览器）。
         ⚠️ 只认 data-mdlink 这个属性，别的 a 标签一律不碰（其它弹窗/页面的链接行为不变）。 */
      const onMarkdownLinkClick = (event) => {
        /* ⚠️⚠️ 右键也会派发 auxclick（button === 2）：不挡的话"右键公告链接"会像左键
           一样直接把链接丢给系统浏览器，右键菜单还没来得及弹人就跳走了
           （用户报的 bug：右键公告的链接直接跳转）。右键只归 contextmenu 管。 */
        if (!event || event.button === 2) return;
        const anchor = event && event.target && event.target.closest
          ? event.target.closest('a[data-mdlink]') : null;
        if (!anchor) return;
        const url = anchor.getAttribute('data-mdlink') || '';
        if (!url) return;
        event.preventDefault();
        event.stopPropagation();
        openLink(url, event);
      };
      window.addEventListener('click', onMarkdownLinkClick, true);
      window.addEventListener('auxclick', onMarkdownLinkClick, true);
      /* 侧栏动态选中标：窗口尺寸/侧栏展开态/语言/页面变化都要重新量一次 */
      window.addEventListener('resize', _onNavResize);
      /* ---------- 滚动惯性（设置 → 功能 → 滚动惯性，默认关闭） ----------
         需求：① 惯性比原来"稍微大一点点"；② 对**所有可滚动区域**都生效，
         不再只认搜索页的 .page-scroll（设置 .settings-main、提交软件 .maker-form-scroll、
         AI 消息 .ai-messages、日志 / 公告 / 详情等一切滚动容器都要有）。
         实现要点：
           · 只监听 wheel（passive，绝不 preventDefault，不干扰原生滚动 / 触控板）；
           · 从 event.target 向上找**最近的可滚动祖先**（overflow-y 为 auto/scroll/overlay，
             且内容确实超出可视区），找不到再兜底 body/html；
           · input / textarea / select / contenteditable 内部不接管（它们自己有滚动或要输入）；
           · 用户停手 90ms 后，用最后一格的势头继续滑，衰减系数按惯性大小换算；
           · 同一个 handler 只维护一份速度；新 wheel 先停旧的，滚到底自动停，
             切换页面 / 窗口失焦时也停掉。 */
      const INERTIA_DEFAULT_STRENGTH = 35;  // 设置缺失 / 非法时的默认值（%）
      const INERTIA_STOP_THRESHOLD = 0.6;   // px/帧：低于这个就停（旧值 0.8，略降更顺）
      const INERTIA_MAX_DISTANCE = 200;     // 单次惯性总距离上限，避免"一滚飞出去"
      const INERTIA_SCROLL_OVERFLOW = /^(auto|scroll|overlay)$/;
      let inertiaVel = 0;
      let inertiaTimer = 0;
      let inertiaRaf = 0;
      let inertiaDistance = 0;
      function inertiaStrength() {
        /* 只认 1~100 的整数；缺失 / 非法（含老配置没有这个键）按 35% 处理 */
        const raw = settings.scroll_inertia_strength != null
          ? settings.scroll_inertia_strength : draft.scroll_inertia_strength;
        const value = Number(raw);
        return (Number.isFinite(value) && value >= 1 && value <= 100)
          ? value : INERTIA_DEFAULT_STRENGTH;
      }
      function findScrollable(target) {
        if (!target || (target.nodeType !== 1 && !target.parentElement)) return null;
        /* 输入类元素内部不接管：textarea 自己有滚动条，input/select 的滚轮另有语义 */
        const editing = target.closest
          ? target.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"]')
          : null;
        if (editing) return null;
        let node = target.nodeType === 1 ? target : target.parentElement;
        while (node && node.nodeType === 1) {
          let style = null;
          try { style = window.getComputedStyle(node); } catch (e) { style = null; }
          if (style && INERTIA_SCROLL_OVERFLOW.test(style.overflowY || '')
            && node.scrollHeight > node.clientHeight + 2) return node;
          node = node.parentElement;
        }
        /* 兜底：整页滚动（body / html） */
        const docEl = document.scrollingElement || document.documentElement;
        if (docEl && docEl.scrollHeight > docEl.clientHeight + 2) return docEl;
        if (document.body && document.body.scrollHeight > document.body.clientHeight + 2) {
          return document.body;
        }
        return null;
      }
      function inertiaStop() {
        inertiaVel = 0;
        inertiaDistance = 0;
        if (inertiaTimer) { clearTimeout(inertiaTimer); inertiaTimer = 0; }
        if (inertiaRaf) { cancelAnimationFrame(inertiaRaf); inertiaRaf = 0; }
      }
      function inertiaRun(scroller) {
        if (inertiaRaf) cancelAnimationFrame(inertiaRaf);
        const strength = inertiaStrength();
        /* 旧参数：decay 0.82 / maxStep 22 / 阈值 0.8；整体略加一点惯性 ——
           35% → decay 0.8395、maxStep 26.2；越往上越滑，但 decay 封顶 0.90（不会失控）。 */
        const decay = Math.min(0.90, 0.78 + 0.0017 * strength);
        const maxStep = 22 + 0.12 * strength;
        inertiaVel = Math.max(-maxStep, Math.min(maxStep, inertiaVel));
        const step = () => {
          inertiaVel *= decay;
          if (Math.abs(inertiaVel) < INERTIA_STOP_THRESHOLD) { inertiaRaf = 0; inertiaVel = 0; return; }
          const before = scroller.scrollTop;
          scroller.scrollTop = before + inertiaVel;
          const moved = scroller.scrollTop - before;
          inertiaDistance += Math.abs(moved);
          /* 到顶 / 到底（scrollTop 没变）或总距离超过上限 → 收手 */
          if (moved === 0 || inertiaDistance >= INERTIA_MAX_DISTANCE) {
            inertiaRaf = 0; inertiaVel = 0; return;
          }
          inertiaRaf = requestAnimationFrame(step);
        };
        inertiaRaf = requestAnimationFrame(step);
      }
      window.addEventListener('wheel', (event) => {
        /* 任何一次新的滚轮都先停掉上一条惯性，保证全局只有一份在跑 */
        inertiaStop();
        if (!settings.scroll_inertia) return;
        /* 关闭动画时不留惯性滑行（惯性也是"动效"，跟设置 → 动画的关闭对应） */
        if (settings.ui_animation === 'off') return;
        if (event.ctrlKey || event.altKey || event.shiftKey) return;  // Ctrl=缩放 / Alt / Shift=横向
        /* 页面内已经 preventDefault 的滚轮（首页轮播 @wheel.prevent、设置滑块等）不重复接管，
           否则轮播切换幻灯片的同时外层页面会被惯性带走一段。 */
        if (event.defaultPrevented) return;
        const deltaY = Number(event.deltaY) || 0;
        const deltaX = Number(event.deltaX) || 0;
        /* 横向滚轮（|deltaX| > |deltaY|）不接管 */
        if (!deltaY || Math.abs(deltaX) > Math.abs(deltaY)) return;
        const scroller = findScrollable(event.target);
        if (!scroller) return;
        const maxStep = 22 + 0.12 * inertiaStrength();
        inertiaVel = Math.max(-maxStep, Math.min(maxStep, deltaY * 0.18));
        inertiaDistance = 0;
        clearTimeout(inertiaTimer);
        inertiaTimer = setTimeout(() => inertiaRun(scroller), 90);
      }, { passive: true });
      window.addEventListener('mousedown', inertiaStop, { passive: true });
      window.addEventListener('blur', inertiaStop);
      /* 切页面时停掉：旧容器可能已被 v-if 卸载，继续滚会滚到新页面上去 */
      watch(page, inertiaStop);
      nextTick(() => syncNavIndicator(false));
      watch([page, navOpen, () => I18N.version, () => navTop.value.length, () => navBottom.value.length],
        () => nextTick(() => syncNavIndicator(true)));
      document.addEventListener('mousedown', onDocMoreDown, true);
      // 防止启动时标题栏按钮获得焦点（框选高亮）
      nextTick(() => {
        document.querySelectorAll('.tb-btn').forEach(btn => btn.blur());
      });
      if (window.ResizeObserver && searchScroll.value) {
        resizeObserver = new ResizeObserver(() => {
          measureViewport();
          ballPaused.value = true;                       // 滚动/缩放时悬浮球让路（原版 pause_for(200)）
          clearTimeout(onWindowResize.pause);
          onWindowResize.pause = setTimeout(() => { ballPaused.value = false; }, 200);
        });
        resizeObserver.observe(searchScroll.value);
      }
      /* 收藏页网格宽度变化时重算列宽。
         ⚠️ 为什么不能只靠 window resize：收藏页的可用宽度还受左侧栏展开/收起影响
            （侧栏展开 → 内容区变窄 → 列数变少），那个变化**不会**触发 window resize。
            用 ResizeObserver 盯着滚动容器才准。
         ⚠️ task-3 ①：旧代码在 onMounted 里 observe(favGrid.value) —— 那时收藏页
            还没挂载（启动落在搜索页），favGrid.value 恒为 null，**这个观察器从来没
            生效过**，列数只靠 onPageAfterEnter 补拍。现在改成 watch favScroller：
            收藏页挂载 → 观察；卸载（切页 v-if）→ 断开，随页重挂。 */
      if (window.ResizeObserver) {
        watch(favScroller, (el) => {
          if (favGridObserver) { favGridObserver.disconnect(); favGridObserver = null; }
          if (el) {
            favGridObserver = new ResizeObserver(() => { measureFavGrid(); });
            favGridObserver.observe(el);
          }
        });
      }
      // Maker 页面：预览卡片吸顶同步 + 双栏响应式
      const _makerScrollHandler = () => {
        if (page.value === 'maker') {
          syncMakerPreviewSticky();
          syncMakerColumns();
        }
      };
      window.addEventListener('scroll', _makerScrollHandler, true);
      window.addEventListener('resize', _makerScrollHandler);

      /* 后端事件（原版 pyqtSignal 的等价物） */
      onEvent('hotkey', (payload) => {
        if (!payload) return;
        if (payload.action === 'focus_search') focusSearch();
        else if (payload.action === 'open_ai') {
          if (settings.ai_enabled && settings.ai_sidebar_mode) doGoto('ai'); else aiOpen.value = true;
        }
      });
      onEvent('tray', (payload) => {
        if (!payload) return;
        if (payload.action === 'focus_search') focusSearch();
        else if (payload.action === 'open_ai') openAiFromTray();
        else if (payload.action === 'menu') {
          Object.assign(trayLabels, payload.labels || {});
          // 记录托盘菜单弹出位置
          if (payload.x !== undefined && payload.y !== undefined) {
            lastTrayPos.value = { x: Number(payload.x), y: Number(payload.y) };
          }
          trayMenu.value = true;
        }
      });
      onEvent('window-state', (payload) => {
        if (!payload) return;
        win.maximized = !!payload.maximized;
        win.fullscreen = !!payload.fullscreen;
        win.minimized = !!payload.minimized;
        /* 原生侧改了窗口状态（比如系统快捷键最大化）时同步根类，
           标题栏分隔线样式和 syncWindow 保持同一套判断 */
        const root = document.getElementById('app');
        if (root) {
          root.classList.toggle('is-maximized', !!win.maximized);
          root.classList.toggle('is-fullscreen', !!win.fullscreen);
        }
        /* 原生侧（系统快捷键等）改了窗口状态时，同样要补量指示标：
           全屏/还原会改变左侧栏高度、底部条目位置，而状态事件本身不触发 resize。 */
        requestAnimationFrame(() => syncNavIndicator(false));
      });
      onEvent('favorites-changed', () => loadFavorites().then(() => runQuery()));
      /* 启动时那个**后台**云端刷新跑完了（resources.cloud_refresh_async 的回调）。
         ⚠️ 这个事件是**后台线程**推的，收到时窗口早就出来了 ——
            所以这里**只做静默更新**：成功就刷新列表 + 设置页那行状态；
            失败只更新状态（不弹 toast，绝不挡界面）。 */
      onEvent('cloud.refresh.done', (payload) => {
        cloudSyncing.value = false;
        if (!payload) return;
        if (payload.ok === false) {
          cloudStatus.value = { ok: false, available: false,
            error: String(payload.error || '').trim(),
            error_key: String(payload.error_key || '').trim() };
          return;
        }
        /* 成功：重新读一次状态 + 刷新资源列表（拉到新版时 loadResources 会拿到新内容） */
        readCloudStatus().then(() => loadResources()).catch(() => {});
      });
      /* 下载进度（节流推送）→ 合并到本地任务表；右上/右下小圆点显示"有下载在进行" */
      onEvent('download.progress', (payload) => { mergeDownloadItem(payload); });
      /* 云端图标（icon.zip）后台同步完成 → 全部图标强制重取一次
         ⚠️ 只清 iconRetry 不够：从没失败过的图标 src 字符串不变、浏览器直接用缓存
            → 云端换了图也看不到。所以 epoch+1 拼进 URL 才是真刷新。 */
      onEvent('cloud-icons-updated', (payload) => {
        if (!payload) return;
resetIconRetries();
        iconEpoch.value += 1;
      });
      /* ===================== Agent 工具 → 界面动作（agent.ui） =====================
         Web 版没有 Qt 主窗口，core/ai/agent_web.py 里那些"要动界面"的工具
         （切页 / 开详情 / 弹提示 / 开插件配置页 / 新建会话 / 部署清单回值）
         没法直接操作 DOM，所以后端推事件、前端在这里落地。
         ⚠️ 每个 op 都必须**有真实实现**，做不到就回一句失败 —— 不要静默吞掉，
            否则模型会以为"已经帮你做了"（这是 AGENT_PROMPT_FOOTER 明令禁止的）。 */
      /* Agent 工具执行过程：大厂 Agent 那种「正在调用 XX」提示（用户点名要的） */
      onEvent('ai.agent_progress', (payload) => { onAgentProgress(payload); });

      onEvent('agent.ui', (payload) => {
        const req = (payload && typeof payload === 'object') ? payload : {};
        const op = String(req.op || '');
        const reqId = String(req.reqId || '');
        const reply = (data) => {
          if (!reqId) return;
          bridge.tryCall('ai.agent_reply', reqId, data).catch(() => {});
        };
        try {
          if (op === 'goto_page') {
            const target = String(req.page || '');
            if (!target) { reply({ ok: false, error: '没有指定页面' }); return; }
            doGoto(target);
            reply({ ok: true, page: target });
            return;
          }
          if (op === 'open_resource') {
            const code = String(req.code || '').trim();
            if (!code) { reply({ ok: false, error: '没有指定资源' }); return; }
            /* 资源清单在 items 里（搜索页那份）。找不到就用后端给的名字兜底 —
               openDetail 只要求能显示出东西，不必强求和本地列表完全同一对象。 */
            const item = (items.value || []).find((r) =>
              String(r.code || r.id || '').toUpperCase() === code.toUpperCase());
            if (!item) { reply({ ok: false, error: '当前列表里没有 ' + code + '，请先搜索或刷新' }); return; }
            openDetail(item);
            reply({ ok: true });
            return;
          }
          if (op === 'notify') {
            toast(String(req.text || ''), String(req.level || 'info'));
            reply({ ok: true });
            return;
          }
          if (op === 'open_plugin_config') {
            const id = String(req.id || '');
            let plugin = pluginById(id);
            /* 列表可能还没加载过（用户没进过插件页）：先拉一次再找 */
            if (!plugin) { loadPlugins(false).then(() => {}); }
            plugin = pluginById(id);
            if (!plugin) { reply({ ok: false, error: '没有找到插件 ' + id }); return; }
            if (!plugin.hasConfig) { reply({ ok: false, error: '这个插件没有配置界面' }); return; }
            openPluginPage(plugin);
            reply({ ok: true });
            return;
          }
          if (op === 'new_chat') {
            aiNewChat().catch(() => {});
            reply({ ok: true });
            return;
          }
          /* ⚠️⚠️ 修「切换主题成功了但要重启才生效」：
             旧写法只调 applyAppearance()，而它读的是前端 settings 快照 ——
             后端写盘后推的 settings-changed 何时到达不确定，set_theme 这条
             agent.ui 事件经常**先到**，于是 applyAppearance 用的是旧值 = 没变化。
             现在：事件里带齐了最新值（后端从磁盘刚读的），前端**先落到本地
             settings 再应用**，不依赖事件先后顺序。 */
          if (op === 'set_theme') {
            /* ★ 本轮（字体等 bug 的前端兜底）：draft 是设置页控件绑定的那份，
               只写 settings 不写 draft 的话，后端 settings-changed 万一没到
               （旧版 agent 写设置走错域就从没发过），设置页下拉框还是旧值。
               两个一起写，事件到不到都一致。 */
            if (req.theme !== undefined) {
              settings.theme = req.theme;
              draft.theme = req.theme;
            }
            applyAppearance();
            reply({ ok: true });
            return;
          }
          if (op === 'apply_appearance') {
            /* AI 改完任意外观项后后端推这个：把所有外观相关值一次性落地再重画。
               （theme_effect / accent_color / ui_font_family / ui_animation 都要带上，
                 否则"切了毛玻璃但没反应"就是漏了某个字段。） */
            ['theme', 'theme_effect', 'accent_color', 'ui_font_family', 'ui_animation']
              .forEach((k) => {
                if (req[k] !== undefined && req[k] !== null) {
                  /* 同 set_theme 的兜底：settings（应用层）与 draft（设置页控件层）
                     一起落地，agent 改外观后设置页选中项立刻跟得上实际效果。 */
                  settings[k] = req[k];
                  draft[k] = req[k];
                }
              });
            applyAppearance();
            reply({ ok: true });
            return;
          }
          if (op === 'apply_language') {
            /* ⚠️⚠️ 必须走完整的 changeLanguage 链路（这是用户要的"模仿人类操作"）：
               人类在设置里选语言 → onRowChange → changeLanguage() → 重拉语言包
               → flattenI18n → 重取资源/筛选/收藏 → 投稿表单分段重算 → 整页重渲染。
               AI 改语言必须走**同一条**路；只写 settings 就会出现用户报的
               「小部分成功切换、大部分还是老样子」。 */
            reply({ ok: true });
            if (req.language) {
              queue(() => changeLanguage(req.language)).catch(() => {});
            }
            return;
          }
          if (op === 'reload_data') {
            reply({ ok: true });
            /* 资源来源/卡片尺寸这类改完要重新读数据 */
            loadResources().then(() => loadFavorites()).catch(() => {});
            return;
          }
          if (op === 'deploy_list') {
            /* 需要回值：把当前部署清单回给后端（agent_web.deploy_list 在等这个） */
            reply({ ok: true, items: (deployList.value || []).map((row) => ({
              code: String(row.code || ''), name: String(row.name || ''),
              status: String(row.status || ''),
            })) });
            return;
          }
          reply({ ok: false, error: '不认识的界面动作: ' + op });
        } catch (error) {
          reply({ ok: false, error: (error && error.message) || String(error) });
        }
      });

      onEvent('settings-changed', (payload) => {
        if (!payload || !payload.key) return;
        settings[payload.key] = payload.new;
        draft[payload.key] = payload.new;
        if (['theme', 'accent_color', 'ui_font_family', 'theme_effect',
          'ui_animation'].indexOf(payload.key) >= 0) applyAppearance();
        /* 插件开关可能在配置页被改（后端 ai.set_agent_enabled）→ 刷新插件卡与 /plugin 提示 */
        if (payload.key === 'gcp_ai_agent_enabled' || payload.key === 'gcp_plugin_maker_enabled') {
          loadPlugins(false);
        }
        /* 本轮：另一端（桌面窗口 / 浏览器页签）改了服务商、模型或思考档位 →
           模型候选与**思考档位表**要重拉，否则本端输入框里的胶囊还显示旧模型、
           滑块档位表还是上一个模型的（用户报的"改了并没有立即变化"的另一半）。
           ⚠️ 只有值真的变了才重拉（上面已把 payload.new 写进 settings，
              watch 里那三个源会自己触发一次，这里再兜住"watch 没覆盖到的键"）。 */
        if (payload.key === 'ai_provider' || payload.key === 'model_name'
          || payload.key === 'ai_thinking') loadAiModelChoices();
      });

      /* ⚠️ 启动总兜底：无论 boot() 卡在哪一步，8 秒后一定撤掉启动遮罩，
         保证界面永远能出来（宁可少加载一点数据，也不能一直黑屏/卡启动页）。 */
      /* ⚠️ 第 28 轮③：启动画面现在要挂到"资源落定"为止（云端最多 12+8 秒），
         8 秒的看门狗会把"正在加载资源"误报成"启动较慢"。所以：
         · 时限放宽到 20 秒；
         · step=render（正在加载资源库）时不弹警告 —— 那是正常阶段，不是卡死；
         · 任何情况下都保证 booting=false（界面/启动画面一定会撤）。 */
      const bootWatchdog = setTimeout(() => {
        if (booting.value) {
          console.warn('[ToolsGCP] boot watchdog fired at step=' + bootStep);
          booting.value = false;
          if (bootStep !== 'render') {
            toast(t('boot_slow', '启动较慢（卡在 ') + bootStep + '），已先显示界面', 'warning');
          }
        }
      }, 20000);

      boot()
        .then(() => clearTimeout(bootWatchdog))
        .catch((error) => {
          clearTimeout(bootWatchdog);
          console.error('[ToolsGCP] boot failed', error);
          booting.value = false;
          toast(t('boot_error', '启动异常：') + (error && error.message ? error.message : error), 'error');
        });
    });
    onBeforeUnmount(() => {
      window.removeEventListener('keydown', onKeydown);
      /* ⚠️ 移除必须带**同样的 capture 标志**：add 用了 true，remove 不传 third arg
         移除的是冒泡阶段那个（不存在）→ 监听器会永久留在 document 上。 */
      document.removeEventListener('keydown', onGlobalCopy, true);
      window.removeEventListener('resize', onWindowResize);
      /* ⚠️ remove 的 capture 标志必须和 add 一致（见上面 onBeforeUnmount 的同类坑） */
      document.removeEventListener('scroll', onAnyScrollForBall, true);
      window.removeEventListener('wheel', onUserScrollInput);
      window.removeEventListener('touchstart', onUserScrollInput);
      document.removeEventListener('keydown', onUserScrollInput);
      abortBackTopAnim();
      document.removeEventListener('mousedown', onDocMoreDown, true);
      window.removeEventListener('scroll', _makerScrollHandler, true);
      if (resizeObserver) resizeObserver.disconnect();
      if (favGridObserver) favGridObserver.disconnect();
      /* 分段滑块的观察器随组件一起断，否则切页后回调还在写已经不存在的 thumb */
      if (segResizeObserver) segResizeObserver.disconnect();
      /* 首页轮播定时器（stopSlide）随首页一起移除，这里不再需要停它。 */
      if (rafId) cancelAnimationFrame(rafId);
      /* ⚠️ 变量名跟 task-4 状态机同步：旧 scrollRaf 已改名 spyRaf（引用不存在的名字会抛
         ReferenceError 把整个卸载钩子打断） */
      if (spyRaf) cancelAnimationFrame(spyRaf);
    });
    /* 窗口缩放 / 最大化还原时的顺序修正（我切换窗口回来这个分段控制器溢出撑破了父容器，而且它切换这个分段控制器的动画会全部重新加载一遍）。
       ⚠️ 根因（CDP 实测）：resize 时 onWindowResize 先跑，它量到的是**还没切单/双栏**的旧布局 ——
          最大化那一帧 .maker-body 还是单栏（实测 i18n-seg 瞬时 1278px → 每项 421px），
          于是 syncSegThumbs 把 thumb 写成 421px；接着 _makerScrollHandler 才把网格切成双栏，
          但没人再量一次 ⇒ thumb 永久停在 421px（选中项只有 320px），看起来"溢出/撑破"。
       修法：① 先 syncMakerColumns() 再量几何；② 布局稳定后再补一拍 scheduleSegSync()；
             ③ 这次同步用 immediate（关过渡），窗口变化时只对齐、不播那 220ms 滑动动画 ——
                只有"点分段 tab"（watch 驱动）才该有动画。 */
    function onWindowResize() {
      measureViewport();
      syncWindow();
      if (page.value === 'maker') syncMakerColumns();   // 先按新宽度定单/双栏，再量几何
      /* 收藏页卡片宽度随窗口变（拉伸窗口改变收藏页内的卡片长度要和搜索页的一致）*/
      if (page.value === 'favorites') measureFavGrid();
      syncSegThumbs(true);                              // 窗口缩放：瞬时对齐，不重播动画
      scheduleSegSync();                                // 布局稳定后再兜一次（双栏切换晚一帧）
      /* 变矮之后内容可能不再溢出，浏览器会把 scrollTop 夹回去（也会发 scroll 事件，
         但那条要等下一帧）—— 这里主动对账，避免球在窗口缩小后还亮着。 */
      syncBackTop();
    }

    /* ---------- 分段按钮的"滑动选中块" ----------
       给每个 .segmented 注入一层 .seg-thumb，定位到当前 .is-on 项；
       切换时 left/width 有 220ms 过渡，所以是"滑过去"而不是"闪一下"。
       DOM 结构不改模板，任何 .segmented（视图切换 / 版本变体 / 插件排版 / 多语言）都自动生效。
       immediate=true：本次同步关掉过渡（窗口缩放/首次挂载/切页），避免"动画全部重播一遍"。 */
    function syncSegThumbs(immediate) {
      const list = document.querySelectorAll('.segmented');
      Array.prototype.forEach.call(list, (seg) => {
        const on = seg.querySelector('.seg-item.is-on');
        let thumb = seg.querySelector('.seg-thumb');
        if (!on) { if (thumb) thumb.remove(); return; }
        const sr = seg.getBoundingClientRect();
        if (!sr.width) { if (thumb) thumb.remove(); return; }
        if (!thumb) {
          thumb = document.createElement('span');
          thumb.className = 'seg-thumb';
          seg.insertBefore(thumb, seg.firstChild);
        }
        /* 量选中项一律用布局口径（offset*），不要用 getBoundingClientRect。
           原因（用户报「滑动到别处再滑回来，选中块明显短了」，实测差 13px / 4%）：
           components.css 给 .seg-item:active 写了 transform: scale(.96)，真人点击是
           「按下 → 缩放 → 松手 → 回弹过渡 → click」，而 click 触发的这次同步正好量在回弹里
           —— rect 会把 transform 折算进去，于是写进 thumb 的宽度只有真实宽度的 96%。
           更糟的是 transform 不改变边框盒，segResizeObserver 永远不会为此回调补刀，
           所以这个偏短会**永久**留在滑块上。offsetLeft/Top/Width/Height 只反映布局，
           与任何 transform 无关，量出来天然正确。
           offsetParent 是 .segmented（position:relative）时，offsetLeft/Top 本来就是相对它的
           padding box，和绝对定位 left/top 同一个坐标系（等价于旧算式 ir.left - sr.left - 1
           里那个减 1），不需要再修边框；只有 DOM 意外套了层（offsetParent 不是 seg）
           才退回 rect 算术。 */
        let left, top, width, height;
        if (on.offsetParent === seg) {
          left = on.offsetLeft;
          top = on.offsetTop;
          width = on.offsetWidth;
          height = on.offsetHeight;
        } else {
          const ir = on.getBoundingClientRect();
          left = ir.left - sr.left - 1;
          top = ir.top - sr.top - 1;
          width = ir.width;
          height = ir.height;
        }
        /* 夹紧到容器内容框：即使某一帧量到的是旧布局（见上面 resize 那段注释），
           thumb 也绝不会画到 .segmented 外面去（用户说的"撑破父容器"）。
           clientWidth/Height = padding box = 绝对定位的 containing block，
           同样比 rect.width - 2 更准（rect 也会被 transform 污染）。 */
        const boxW = Math.max(0, seg.clientWidth);
        const boxH = Math.max(0, seg.clientHeight);
        if (width > boxW) width = boxW;
        if (height > boxH) height = boxH;
        if (left < 0) left = 0;
        if (left + width > boxW) left = Math.max(0, boxW - width);
        if (top < 0) top = 0;
        if (top + height > boxH) top = Math.max(0, boxH - height);
        if (immediate) thumb.style.transition = 'none';
        thumb.style.left = left + 'px';
        thumb.style.top = top + 'px';
        thumb.style.width = width + 'px';
        thumb.style.height = height + 'px';
        if (immediate) {
          /* 强制回流：让上面的 no-transition 值立刻生效，再把过渡交还给样式表。
             因为随后没有属性变化，浏览器不会补播过渡动画。 */
          void thumb.offsetWidth;
          thumb.style.transition = '';
        }
      });
      /* 每次同步都顺手把观察器补齐：新挂载的分段（换页 v-if、设置开关）第一次
         由这里登记，之后它自己变宽变窄就能回调到同步。 */
      observeSegContainers();
    }
    /* 布局可能晚一两帧才稳定（单/双栏切换、字体、滚动条出现）——再补一次瞬时对齐。 */
    let segSyncRaf = 0;
    function scheduleSegSync() {
      if (segSyncRaf) cancelAnimationFrame(segSyncRaf);
      segSyncRaf = requestAnimationFrame(() => {
        segSyncRaf = requestAnimationFrame(() => {
          segSyncRaf = 0;
          syncSegThumbs(true);
        });
      });
    }

    /* ---------- 容器宽度变了、但**没有** window resize 的那一类 ----------
       ⚠️ 真机取证（_devtest/probe_seg_thumb_live3.js，无头 Edge 实测）：
          只把 .i18n-seg 的容器改窄 200px（等价于滚动条出现/侧栏展开/单双栏切换挤窄），
          每项从 312px 变成 245.33px，thumb 仍停在 312px —— dw=66.67，1500ms 后依旧错；
          切到 English 再挤窄时 dx=100 / dw=50，选中块压到邻居身上。
          用户说的"一切换选中 UI 大小和形状就不对"就是这个：**尺寸过期的滑块**，
          而不是测量口径错（终态在等宽容器上永远重合，已实测）。
       旧代码只在 watch 响应式变化 + window resize 时重量，所以"布局自己变了"没人补量。
       修法：给每个 .segmented 和它的 .seg-item 挂 ResizeObserver —— 任何原因导致的
             宽度/高度变化都会再量一次。三处（maker-seg / i18n-seg / view-seg）共用同一套，
             因为 syncSegThumbs 本来就是遍历全部 .segmented 的。
       ⚠️ 为什么这里用 immediate=false（保留过渡）：挤窄往往发生在点击动画还在飞的 220ms 内，
          瞬时对齐会把动画掐成一次跳变；写新目标值让过渡自己追，视觉上仍是"滑过去"。
          而 window resize 那条路径已经先做过 immediate 对齐，RO 随后量到同样的值，
          属性没变化就不会补播动画 —— 两种诉求同时满足。
       ⚠️ 回调里排到下一帧再写样式：在 RO 回调里同步改布局会触发
          "ResizeObserver loop completed with undelivered notifications" 报错。 */
    let segResizeObserver = null;
    let segRoPending = false;
    const segRoSeen = typeof WeakSet === 'function' ? new WeakSet() : null;
    if (window.ResizeObserver) {
      segResizeObserver = new ResizeObserver(() => {
        if (segRoPending) return;
        segRoPending = true;
        requestAnimationFrame(() => {
          segRoPending = false;
          syncSegThumbs(false);
          observeSegContainers();
        });
      });
    }
    /* 新出现的分段（v-if 换页、设置里开关切换出来的）也要挂上观察器。
       同一元素重复 observe 是幂等的，WeakSet 只是省掉无谓调用。
       滑块 .seg-thumb 是绝对定位（不占 flex 空间），写它的尺寸不会反过来撑大容器 ⇒ 不会自激。 */
    function observeSegContainers() {
      if (!segResizeObserver) return;
      Array.prototype.forEach.call(document.querySelectorAll('.segmented'), (seg) => {
        if (segRoSeen && !segRoSeen.has(seg)) { segRoSeen.add(seg); segResizeObserver.observe(seg); }
        Array.prototype.forEach.call(seg.querySelectorAll('.seg-item'), (it) => {
          if (segRoSeen && !segRoSeen.has(it)) { segRoSeen.add(it); segResizeObserver.observe(it); }
        });
      });
    }
    /* 页面 / 视图 / 插件排版 / 设置板块变化后重新对齐滑动块（渲染完成再量尺寸）。
       ⚠️ 补全：之前只 watch 了 page/viewMode/plugin_view/search_show_view_switch/
       currentSection，所以提交软件的 maker-seg、多语言 i18n-seg、详情页 variant-seg
       切换时 thumb 不重新定位 —— 用户看到的就是"这些切换 UI 没有动画"。
       每加一个 .segmented 数据源，必须在这里补一个 getter。 */
    watch([page, viewMode, () => settings.plugin_view, () => settings.search_show_view_switch,
      currentSection, activeSection, activeVariant, i18nLangIndex, i18nEnabled,
      () => settings.ai_sidebar_mode],
      () => { nextTick(syncSegThumbs); });
    function syncMakerColumns() {
      if (!makerBody.value || !makerLeft.value || !makerRight.value) return;
      const viewportW = makerBody.value.clientWidth;
      const TWO_COL_MIN = 1080;
      const SIDE_W = 280;
      const wide = viewportW >= TWO_COL_MIN;
      const isSingle = makerBody.value.style.gridTemplateColumns === '1fr';
      if (wide && isSingle) {
        makerBody.value.style.gridTemplateColumns = '1fr ' + SIDE_W + 'px';
      } else if (!wide && !isSingle) {
        makerBody.value.style.gridTemplateColumns = '1fr';
      }
    }

    /* 启动时进入 AI 界面**总是新对话**（需求变更，覆盖旧的"接上最近一次对话"）：
       · 历史内容仍完整保存在 .ToolsGCP/config/chats/（历史面板可查），不删不动；
       · 只是聊天区不再自动铺上一段旧对话 —— 每次重启都是干净的输入框；
       · 后端 ai.new_session 只发 id、不落盘，等第一条消息发出才写文件。 */
    const loadAiOnBoot = async () => {
      const created = await bridge.tryCall('ai.new_session');
      if (created && created.ok && created.session) {
        aiSessionId.value = created.session.id || '';
        aiMessages.value = [];
      }
    };

    return {
      /* 基础 */
      t, term, info, settings, win, booting, bootText, toasts, toast, dismiss,
      toastClass,
      dialog, openDialog, answer, confirmDialog, onDialogSelect, dialogChecksSome,
      /* Markdown 弹窗渲染（notesMd/bodyMd 开关 + 产物 computed） */
      dialogNotesHtml, dialogBodyHtml,
      /* 导航 */
      page, detail, detailPage, navHover, navPinned, navOpen, navTop, navBottom, moreItems, moreOpen,
      /* 云端资源库加载遮罩 */
      resourceLoading, resourceLoadFailed, loadingDots,
      retryResourceLoad, useLocalResources, hintSwitchMirror,
      goto, doGoto, isActive, toggleNav, onNavEnter, onNavLeave, closePops, closeSidebar,
      hoverExpand, navIndicator,
      /* 窗口 */
      onTitleDown, onTitleDouble, minimizeWindow, maximizeWindow, closeWindow,
      startResize,
      toggleFullscreen, syncWindow, onPageAfterEnter,
      /* 数据 */
      items, loading, loadError, folders, notices, noticesLoading, noticesError,
      unread, unreadCount, logFiles, logPreview, hasHistory, logsReady,
      pluginList, pluginsLoading, apiKeyConfigured,
      /* 搜索页 */
      keyword, sortKey, sortOptions, filterOpen, chevronDeg, panelH, filters, filterRows,
      toggleFilter, isFilterOn, toggleFilterValue, onFilterChanged, runSearch, clearKeyword,
      autoSearch, viewMode, cardPx, resultText, emptyText, filtered, groups,
      vlist, searchScroll, detailScroll, searchInput, vTotal, vRows, onScrollArea, listAnim,
      /* task-3 ⑤：vlistTop / measureViewport 一并暴露（模板不用，
         给 _devtest 的运行时回归留测试接缝；measureViewport 本来就是页面重排入口）。 */
      vlistTop, measureViewport,
      visibleTags, hiddenTagCount, tagAvail, onIconError, iconSrc, iconFailed, firstChar, isHttp,
      /* task-14：标签折叠算法的测试接缝（模板不用）—— _devtest/probe_tag_fold.mjs
         直接喂构造 item + avail 断言五种形态，不用真把卡片滚进视口。 */
      tagLayout, tagBoxWidth, plusBoxWidth, tagTextPx, tagGap, tagMetrics,
      toggleDialogChecks,
      cardMenu, openCardMenu, closeCardMenu, cardMenuMention, cardMenuPing,
      /* task-12 需求 6/7：详情区选区菜单 + 每条链接的测 Ping */
      selMenu, onSelContext, selMenuMention, selMenuCopy, detailRowPing,
      /* 第五轮需求④：详情页 Ping 按钮的进行中状态（模板要拿它做 :disabled 和点阵） */
      pingIsBusy, pingDotsText,
      selectionBar, selectedCount, allSelected, selState, selectionItems, selectAll, exitSelection,
      confirmSelection, setView, setFavView, onCardClick, runQuery,
      /* 卡片 / 详情 */
      toggleFavorite, openLink, mentionAi, openDetail, closeDetail, detailTags, activeVariant,
      introParagraphs, detailRows, chooseVariant, copiedKeys, isCopied, copyText,
      /* 定制页 */
      customizeEditing, customizeOnboarded, selectedInterests, interestCatalog, interestGroups,
      pickedInterest, toggleInterest, interestsRatio, interestNamesText, clearInterests,
      saveInterests, resetInterests, recommendations, customSort, emptyRecommendTitle, onRecommendClick,
      recommendGroups, customSortOptions, customFilters, customFilterRows, customFilterOpen, customPanelH, customChevronDeg,
      toggleCustomFilter, isCustomFilterOn, toggleCustomFilterValue,
      /* 收藏 */
      favFolder, isDefaultFolder, moveFolderOptions, favItems, favMoving, moveTarget, favSelectedCount, favAllChecked,
      favSelState, favSelectAll, toggleRowSelect, startMoveMode, cancelMoveMode, commitMove,
      createFolder, renameFolder, removeFolder, exportFavorites, importFavorites,
      /* 收藏页卡片网格列宽 + 收藏夹右键菜单 */
      favScroller, favMeasured, favGridWidth, favLayout, measureFavGrid,
      favMenu, openFavMenu, closeFavMenu, favMenuRename, favMenuRemove,
      /* 公告 */
      loadNotices, isRead, markRead, markAllRead, openNotice, noticeKey, isReadKey,
      noticeSource, noticeBodyHtml,
      /* Github / 反馈 */
      lightbox, sponsorImage, feedbackUrl, introLines, qqGroups,
      /* 日志 */
      loadLogFiles, exportLogs, openLogDir, openPath, previewLog, logPreviewName, confirmClearLogs,
      /* 部署 */
      deployList, deployRows, deployRunning, deployProgress, deployIndeterminate, deployStatusText, picker, pickerHits,
      toggleDeployMode, openPicker, togglePick, applyPicker,
      startDeploySelection, removeDeployRow, openDeployDetail, exportManifest, importManifest,
      confirmClearDeploy, confirmDeploy, deployOne, statusText, setRowStatus, previewKindOf,
      deployIconOf, deploySourceOf, openPageSingle, rowSiteUrl, rowRepoUrl, openRowSite, openRowRepo, ST_SKIPPED,
      /* 插件 */
      pluginQuery, pluginCountText, filteredPlugins, flashPlugin, devGuide, pluginPage,
      pluginFrameRef, syncPluginTheme,
      loadPlugins, togglePlugin, startNote, saveNote, cancelNote, deletePlugin, openPluginPage,
      openPluginDir, pluginDirs, loadPluginDirs, setPluginView, DEV_GUIDE,
      /* 提交软件 */
      maker, makerLanguages, makerSections, activeSection, makerCategories, makerCategoryOptions,
      makerCategoryText,
      makerPlatforms,
      i18nEnabled, i18nLangIndex, repoPlatformOptions, pasteRepoUrl,
      /* 多组开源仓库 */
      repoPlaceholderFor, addRepoRow, removeRepoRow, repoRowsFor, repoListText, repoListTitle,
      libraryStatusText, libraryLabel, libraryTooltip, libraryFullPath,
      addLinkRow, removeLinkRow, linkCellText, linkCellSet,
      previewName, previewDesc, previewTagList, previewIcon, iconDisplayName, statusLine, statusLevel,
      previewDirty, browserScroll,
      formScroll, previewCard, makerLeft, makerRight, makerBody, syncMakerPreviewSticky,
      onNameChanged, onIdChanged, onCategoryChanged, makerCategoryText, makerTagsText,
      /* 名称三语言联动（m04188 ③）：下方手改 → onLocalNameEdited 脱离跟随；
         「跟随名称」按钮 → restoreNameFollow 恢复联动并把上方值刷进三种语言。 */
      onLocalNameEdited, restoreNameFollow,
      toggleChip, toggleSystem, onRepoPlatformChanged, setI18nLang, refreshPreview, pickIcon, openIconFolder,
      buildEntry, exportDraft, appendToLibrary,
      saveToOriginal, exitEditing, editExistingEntry, saveStandalone, clearForm, browserQuery, browserCategory, browserSelected,
      browserCategoryOptions, browserRows, browserCountText, reloadLibrary, openLibraryFile,
      browserSource, browserSourceOptions, browserReadonly, browserRowsLoading,
      deleteSelectedEntries, batchMode, batchDup, batchFiles, batchFileIndex,
      batchOutput, batchPreviewText, batchModeOptions, batchDupOptions, batchAddFiles,
      batchRemoveSelected, batchClearFiles, batchChooseOutput, batchPreview, batchRun,
      makerHelpBlocks,
      /* AI */
      showBall, ballPaused, backTopPage, backTopVisible, backToTop, aiOpen, aiDraft, aiBusy, aiMessages, aiWelcomeText,
      /* 下载 */
      releasesDialog, downloads, downloadBadge, downloadIconOf, flyDownloadBadge,
      releasesSource, releasesSourceOptions, changeReleasesSource, reloadReleases,
      loadAllReleases, updateReleasesHasMore,
      /* 下载页交互 */
      pauseDownload, resumeDownload, removeDownload,
      downloadMenu, openDownloadMenu, closeDownloadMenu, copyDownloadUrl,
      clearMenuOpen, clearScope, chooseClearScope, runClearDownloads,
      clearScopeLabel, downloadSpeedText,
      /* 文件名后面的时间（完成/取消/失败才有） */
      downloadTimeText,
      openReleases, closeReleases,
      loadMoreReleases, downloadAsset, cancelDownload, retryDownload, openDownloaded,
      openDownloadFolder, clearDownloads, downloadStatusText, openDownloads, closeDownloads,      fmtDuration,
      /* 退出确认（有下载任务时弹窗） */
      confirmQuit, confirmExitWithDownloads, activeDownloadCount,
      /* 启动时后台刷新云端资源库（安静版） */
      refreshCloudLibraryQuiet,
      aiSlashHints, applyAiHint, aiCommandWords, aiPolishing, aiPolish,
      aiTesting, testAiConnection,
      aiThinkingText, aiNewChat, aiHistory, aiHistoryOpen, aiHistoryList,
      aiInputPageRef, aiInputDrawerRef, onAiTokenClick,
      aiSessionId, openAiSession, deleteAiSession, aiRegenerate, loadAiSessions,
      aiBubbleCopied,
      closeAiHistory, clearAiHistory, aiSend, aiStop, focusAiInput,
      /* 本次 5 项改造新增的状态与方法（版本导航 / 原地编辑 / 等待提示 / 撤销润色） */
      aiPending, aiPendingAfter, aiStreamSlot, aiStreamingIndex, aiStreamingText,
      aiRowShown, aiRegenPlaceholder, aiLastAiIndex,
      aiVariantCount, aiVariantPage, aiBubbleText, aiCanSwitchVariant, aiIsEditing,
      aiSwitchVariant, aiStartEdit, aiCancelEdit, aiAcceptEdit,
      aiEditingIndex, aiEditDraft, aiPolishOriginal, aiEditBoxStyle, aiEditBoxAutoGrow,
      /* 本轮改造：逐字打字机 / 思考折叠 / 模型切换 / @候选 / 蓝链 / AI 右键菜单 */
      aiStreamingReasoning, aiThinkOf, aiThinkIsOpen, aiThinkToggle, aiThinkLabel,
      aiBubbleParts, onAiLinkClick, gotoSettingsAi,
      /* 与 vlistTop/measureViewport 同一套路：给 _devtest 运行时回归留的测试接缝（模板不用），
         task-12 需求 6 的 @token 往返（含 [选中文本] 后缀）靠它离线断言。 */
      aiSplitLinks,
      toastLink, toastParts, onToastLinkClick, toastLinkGo, toastLinkClose,
      aiCtx, openAiCtx, closeAiCtx, aiCtxCopy,
      noticeCtx, onNoticeContext, closeNoticeCtx,
      noticeCtxCopyLink, noticeCtxCopy, noticeCtxSelectAll,
      /* 本轮（任务 1 / 2 / 3 / 4）：贴底判定 + 回到底部按钮 + 会话滚动恢复 + 思考块保位 */
      aiStickBottom, aiBackBottomVisible, aiStreaming, aiBackToBottom,
      aiScrollMemory, rememberAiScroll, restoreAiScroll, aiScrollBox,
      aiModelGroups, aiModelOpen, aiModelCurrent, aiModelVisible, aiModelNoKey,
      /* 对话模式胶囊（Chat / Agent） */
      aiModeOpen, aiChatMode, aiChatModeLabel, aiChatModeTip, aiModeVisible,
      CHAT_MODE_OPTIONS, toggleAiModeMenu, aiPickChatMode,
      /* Agent 执行过程卡片 */
      aiAgentSteps, aiAgentStepsVisible, aiAgentStepsOpen, aiAgentStepsDone,
      /* ★ 本轮：逐条气泡的执行过程卡片（页面 + 抽屉两处模板共用这一组函数） */
      aiBubbleSteps, aiBubbleStepsOpen, aiToggleBubbleSteps,
      aiBubbleStepsDone, aiBubbleStepsSummary,
      aiAgentStepsSummary, toggleAgentSteps, restoreAgentStepsFromSession, aiAgentPlanning,
      /* ★ 本轮（需求 4）：用量统计面板（缓存命中 / 上下文 / 会话统计） */
      aiStatsOpen, aiStatsHover, aiUsageLast, aiUsageTotal,
      /* ★ 本轮：运行中过程卡片独立行（见 aiRunCardIndex 注释） */
      aiRunCardIndex, aiLiveSteps,
      aiCacheStats, aiTokenStats, aiLastHit, aiContextStats, aiContextMix, aiMixLegend,
      aiNumberFmt, copyAiStats,
      aiProviderLabel,
      normalizeAiThinking,
      aiThinkSupported, aiThinkingLevel, aiThinkLevels, aiThinkLevelsFull,
      aiThinkSliderMax, aiThinkSliderValue, aiThinkSegHeadStyle, aiThinkFillStyle,
      aiThinkSparkStyle, aiThinkNotches, aiThinkIsSingle,
      aiThinkLevelText, setAiThinkingLevel, aiThinkSegPick, aiThinkSegDown, aiThinkSegKeydown,
      aiModelIsOn, currentAiProfileId,
      aiPickModel, toggleAiModelMenu, aiPolishBlocked, aiInputLocked,
      loadAiModelChoices,
      aiAtOpen, aiAtQuery, aiAtCandidates, aiAtPicked, closeAiAt, applyAiAt, aiAtKeydown,
      /* 设置 */
      sections, draft, currentSection, settingQuery, settingHits, jumpFirstHit, jumpToRow,
      scrollSection, syncSectionFromScroll, settingsScroll, flashRow, flashSection, recording, isVisible, rowKey, sectionIcon,
      clearSettingQuery,
      cardHasVisibleRow, defaultDownloadDirText, downloadDefaultDir, loadDownloadDefaultDir,
      cloudStatusText, cloudSyncing, refreshCloudLibrary,
      onRowChange, onRowInput, onRowCommit, recordHotkey, resetHotkey, toggleKeyVisible,
      startRecord, stopRecording, onSliderWheel,
      apiKeyDraft, apiKeyVisible, apiKeyPlaceholder, apiKeySavedHint,
      saveApiKey, clearApiKey, logoutDev, fire, versionText,
      /* 服务商配置档案（本轮设置页重构）：状态 + 操作 */
      aiProfiles, aiProfilesActive, aiProfilesActiveId, aiProfileEditing,
      aiProfBusy, aiProfileNewModel, aiProfLocked,
      aiProviderCatalog, aiProviderOptions, aiProfileModelChoices,
      aiProfVendorLabel, aiProfCountText, aiProfBrandLabel, loadAiProfiles, loadAiProviderCatalog,
      aiAddProfile, aiEditProfile, aiProfilePickVendor, aiProfileToggleModel,
      aiProfileAddModel, aiCancelProfile, aiSaveProfile, aiDeleteProfile, aiBackdropClose,
      aiTestProfile, aiTestProfileDraft,
      storageMigrate,
      checkingUpdate, checkUpdate, saveSetting,
      updateState, humanSize, applyUpdate, startUpdateDownload, openUpdateFolder,
      showUpdateReadyDialog,
      /* 自动检查更新（右上角精简提示 + 三态设置） */
      updateCorner, cornerCancel, cornerDownload, cornerDetail,
      /* 隐私 / 托盘 */
      privacy, acceptPrivacy, rejectPrivacy, checkPrivacyThenNotices,
      showTip, hideTip,
      trayMenu, trayEl, trayLabels, trayLabel, trayAction, focusSearch, openNativeTrayMenu,
    };
  },
};

/* ===================== 自绘下拉框（替代原生 <select>） =====================
   原生 select 的弹层由系统绘制：WebView2 里是白底黑字的 Windows 经典样式，
   跟深色主题完全不搭（需求："下拉框弹出的太丑了"）。
   这里用 fixed 定位的浮层自己画：行高 32、圆角 7、当前项高亮、跟随主题色。
   支持键盘导航、点击外部关闭、滚动/缩放重定位；弹层**始终**在触发器下方。 */

/* ⚠️ 全局「同时只允许一个下拉框展开」的登记表。
   需求：点开 A 之后再点 B，A 必须自己收起 —— 旧实现里每个 Combo 各自监听文档 mousedown，
   而 `_onDocDown` 看到事件目标是 .combo（B 的触发器）就 `return` 认为"点到自己"，
   于是 A 永远不会被关掉。现在改成：① 打开时主动关掉登记表里其它实例；
   ② mousedown 命中的是**别的** .combo 时也关掉自己（不再无条件放行）。 */
const comboOpenRegistry = new Set();

/* ---------- 资源库加载提示（页面内嵌版） ----------
   需求（用户原话）：「程序启动时如果还在这个默认的加载页面，这个加载页面不要用弹窗样式，
   而是在搜索页这个页面内的空白中心位置显示这个 UI，定制页同理。」
   ⚠️ 以前它是 `#app` 顶层的一个**全屏浮层卡片**（毛玻璃 + 圆角 + 阴影），
      连标题栏和左侧导航都一起盖住 → 观感就是"弹了个窗"。
   → 现在改成**页面内**的一小块 UI：由各页面 section 内部放一个 <resource-loading />，
      它**盖住该页内容**但**不遮**标题栏和左侧导航，也没有任何"浮起来的卡片"观感。
   ⚠️ 做成组件而不是把同一段 markup 抄三遍：改文案/样式时只改这一处，
      不会出现"三个页面长得不一样"的经典问题（项目里 combo 就是这个套路）。 */
const ResourceLoading = {
  name: 'ResourceLoading',
  props: {
    /* 文案与状态都由父组件（App）提供 —— 组件本身不碰后端 */
    dots: { type: String, default: '' },
    failed: { type: Boolean, default: false },
  },
  emits: ['retry', 'use-local'],
  /* ⚠️ `t` 是 app.js 里的**模块级**函数，不是全局的 —— 独立注册的组件
     （app.component(...)）在模板里**看不到** App 实例的 setup 返回值。
     → 把它挂成组件自己的 method，模板里就能用了。
     同样地，Combo 组件当初之所以没踩这个坑，是因为它模板里根本没用 t()。 */
  methods: {
    /* ⚠️ `t` 是 app.js 里的**模块级**函数，不是全局的 —— 独立注册的组件
       （app.component(...)）在模板里**看不到** App 实例的 setup 返回值。
       → 把它挂成组件自己的 method，模板里就能用了。
       同样地，Combo 组件当初之所以没踩这个坑，是因为它模板里根本没用 t()。
       ⚠️ void I18N.version：t() 读的是**非响应式**的 I18N.map，
          必须显式建立依赖，切语言时这段文案才会跟着重算。 */
    t(key, fallback) { void I18N.version; return t(key, fallback); },
  },
  template: `
    <div class="resource-loading">
      <div class="resource-loading-inner">
        <div class="resource-loading-text">
          {{ t('resource_searching', '正在寻找资源文件') }}<span class="dots">{{ dots }}</span>
        </div>
        <div class="resource-loading-bar"><span></span></div>
        <p v-if="failed" class="cap is-warn">{{ t('resource_load_timeout', '加载资源文件用时过长，可能是网络不通') }}</p>
        <div class="row gap10">
          <button class="btn btn-sm" @click="$emit('retry')">
            <svg class="ic" width="14" height="14"><use href="#i-sync"></use></svg>{{ t('resource_retry', '重试') }}
          </button>
          <button class="btn btn-sm" @click="$emit('use-local')">
            {{ t('resource_use_local', '用本地资源库') }}
          </button>
        </div>
      </div>
    </div>
  `,
};

const Combo = {
  name: 'Combo',
  props: {
    modelValue: { type: [String, Number], default: '' },
    options: { type: Array, default: () => [] },
    width: { type: Number, default: 0 },
    disabled: { type: Boolean, default: false },
    placeholder: { type: String, default: '' },
    /* （提交软件·类别）：可编辑下拉 —— 对齐 py 的 EditableComboBox（QComboBox editable）。
       触发器变成一个输入框，既能从列表里选，也能直接敲任何自定义值。 */
    editable: { type: Boolean, default: false },
    /* ⚠️ 本轮删除 displayValue prop（连同 editText computed）：
       它当初是为「modelValue 存规范中文、框里显示译名」而加的，只跟**界面语言**；
       而提交软件的类别/标签现在要跟着「多语言字段」的**分段语言**显示，
       调用方（index.html 的类别 combo）改为直接交显示文本进 model-value、
       并在 @change 里自己还原规范值（见 app.js 的 makerCategoryText / onCategoryChanged）。
       全站已无任何地方再传 display-value（grep 实证）⇒ 留着就是死代码。 */
  },
  emits: ['change'],
  data() {
    /* ⚠️ 故意没有 flip：需求明确"不管超不超出底部，下拉列表都固定在触发器下方"。
       空间不足时只压缩列表高度（maxHeight），绝不翻到触发器上面去。 */
    return { open: false, left: 0, top: 0, minWidth: 0, maxHeight: 300, highlightedIndex: -1 };
  },
  computed: {
    current() {
      const hit = this.options.find((o) => String(o.value) === String(this.modelValue));
      if (hit) return hit.label;
      /* ⚠️ 找不到就回退：先 placeholder，再落到第一项 —— 这是原版 Qt ComboBox 的语义
         （cards_download.py:463-472：配置值不在选项里就 index 0）。之前直接返回 ''，
         导致 search_source / download_source 这种"历史配置是空串"的下拉框**显示一片空白**。 */
      if (this.placeholder) return this.placeholder;
      return this.options.length ? this.options[0].label : '';
    },
  },
  mounted() {
    /* ⚠️ 弹层被 <teleport to="body"> 挪到了 .combo 外面，所以**不能**用
       this.$el.contains(e.target) 判断"点到自己"——那样点击菜单项会先被这里
       关掉（mousedown 早于 click），item 的 click 根本没机会触发，表现为
       "下拉框打不开/选不了"。
       正确做法：用事件目标向上找最近的 .combo-pop / .combo，找不到才关闭。 */
    this._onDocDown = (e) => {
      if (!this.open) return;
      const target = e.target;
      if (!target || !target.closest) { this.open = false; return; }
      /* 弹层是 teleport 到 body 的，点条目不能被当成"点外部" */
      if (target.closest('.combo-pop')) return;
      /* 点到自己的触发器/根节点：由它自己的 click 处理，这里不动。
         ⚠️ 这里**绝不能**抢先关掉自己的弹层：mousedown 早于 click，而触发器
         （普通模式的 button、可编辑模式的箭头）绑的是 @click="toggle" ——
         这里关一次、它再 toggle 一次，净效果就是"点了没反应/关了又开"。
         "点触发器空白处要退出展开态"这条需求改在 onEditableBlankClick 里用 click 处理。 */
      if (target.closest('.combo') === this.$el) return;
      /* 其它情况一律收起 —— 包括"点到**另一个**下拉框"，这正是之前漏掉的分支 */
      this.open = false;
    };
    /* ⚠️ 滚动 / 缩放 / 内容尺寸变化都要重定位；触发器一旦**部分或完全**离开可视区就收起弹层。
       window 的 scroll 走**捕获阶段**，所以内部滚动容器（设置页 .settings-main、
       Releases 弹窗 .releases-body、AI 抽屉…）的滚动同样会进来 —— 旧版"在容器里滚动
       弹层不跟着动、留在屏幕底部原 x 位置"就是这么修的。
       但滚动弹层自己（列表内部滚动）必须跳过：place() 会把弹层拽回触发器下方，
       31 项的类别列表等于滚不动（实测过）。 */
    this._onScroll = (e) => {
      if (!this.open) return;
      const pop = this.$refs.pop;
      if (pop && e && e.target && pop.contains(e.target)) return;
      this.place();
    };
    this._onKeyDown = (e) => {
      if (!this.open) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        this.open = false;
        /* ⚠️ 需求修复（Esc 优先级链）：下拉框展开时按 Esc 只该收起下拉框。
           combo 的监听在组件 mounted 注册、**早于** app 的 onKeydown，
           不阻断的话事件会继续走到 app 那条链，把 Releases 弹窗/详情页
           跟着一起关掉（"一次 Esc 关两层"）。 */
        e.stopImmediatePropagation();
        return;
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        this.highlightedIndex = Math.min(this.highlightedIndex + 1, this.options.length - 1);
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        this.highlightedIndex = Math.max(this.highlightedIndex - 1, 0);
      }
      if (e.key === 'Enter' && this.highlightedIndex >= 0) {
        e.preventDefault();
        this.pick(this.options[this.highlightedIndex]);
      }
    };
    document.addEventListener('mousedown', this._onDocDown, true);
    window.addEventListener('resize', this._onScroll);
    window.addEventListener('scroll', this._onScroll, true);
    window.addEventListener('keydown', this._onKeyDown);
    comboOpenRegistry.add(this);
    /* 初次挂载就处于打开态的情况（几乎不会发生，但保持登记表一致） */
    if (this.open) {
      comboOpenRegistry.forEach((c) => { if (c !== this) c.open = false; });
      this._startTrack();
    }
  },
  /* ⚠️ 打开期间用 rAF 逐帧跟踪触发器（task-4 ③）：
     scroll 捕获监听虽然覆盖内部滚动容器，但布局位移（上方行隐藏/显示、
     图片撑高、窗口缩放过渡）不会发 scroll —— 逐帧量一次 rect 才是真状态。
     只在数值变化时才写响应式字段，位置稳定时等于空转，成本可忽略。 */
  watch: {
    open(value) {
      if (value) this._startTrack();
      else this._stopTrack();
    },
  },
  beforeUnmount() {
    this._stopTrack();
    document.removeEventListener('mousedown', this._onDocDown, true);
    window.removeEventListener('resize', this._onScroll);
    window.removeEventListener('scroll', this._onScroll, true);
    window.removeEventListener('keydown', this._onKeyDown);
    comboOpenRegistry.delete(this);
  },
  methods: {
    toggle() {
      if (this.disabled) return;
      if (this.open) { this.open = false; return; }
      /* 需求：打开自己之前，先把别处已经展开的下拉框全部收起 */
      comboOpenRegistry.forEach((c) => { if (c !== this && c.open) c.open = false; });
      const idx = this.options.findIndex((o) => String(o.value) === String(this.modelValue));
      this.highlightedIndex = idx >= 0 ? idx : 0;
      this.open = true;
      this.$nextTick(this.place);
      /* ⚠️ 滚到当前项只在**打开的那一下**做。
         不能挂在 place() 里：place() 会被 window 的 scroll 捕获监听反复调用，
         而"滚动弹层本身"也会冒泡到那里 —— 那样用户往下滚类别列表，弹层会被
         立刻拽回选中项，31 项的列表等于滚不动（实测过）。 */
      this.$nextTick(this.scrollActiveIntoView);
    },
    place() {
      const el = this.$refs.trigger;
      if (!el || !this.open) return;
      const r = el.getBoundingClientRect();
      const vw = window.innerWidth; const vh = window.innerHeight;
      /* ⚠️ task-4 ③：触发器**部分或完全**离开可视区 → 直接收起弹层。
         旧版两个硬伤：
           ① 触发器滚出视口后弹层仍原地重定位，"一直留在屏幕底部之前 x 轴的位置"；
           ② 末尾那条 `top = Math.min(top, Math.max(8, vh - maxHeight - 8))` 夹取，
              在触发器上移（下方空间不足 96+8）时把弹层**拽到窗口底部**、
              正好"抵到触发器原位置的中间"造成遮挡。
         现在：离开可视区是唯一出口；未离开时弹层永远贴触发器下方 4px，
         绝不覆盖触发器本身（下方实在放不下就自然截断，也不翻上去压触发器）。 */
      /* ⚠️⚠️ 本轮推翻上一轮的做法（用户原话）：
         「下拉框滚动超出页面还是存在的而不是直接把下拉框给关闭了
           你需要修改保留在原地即可无需超出窗口边界自动关闭。」
         → 上一轮做的"触发器部分/完全滚出可视区就自动关闭弹层"**删掉**。
           现在：弹层永远贴着触发器下方 4px，**跟着触发器一起滚**——
           触发器滚出屏幕，弹层就跟着滚出屏幕（不主动关闭、不夹到窗口底部、
           也不固定留在屏幕边缘）。关闭只由用户自己的动作决定：
           再点一次触发器 / 选中一项 / Esc / 点到别处（_onDocDown）。
         ⚠️ 只保留"尺寸为 0"这一条真·异常兜底（display:none 或组件被卸载，
            这时位置本来就没意义）；不再拿 r.top<0 / r.bottom>vh 判"滚出去了"。 */
      if (!r.width && !r.height) { this.open = false; return; }
      this.left = r.left;
      /* 永远贴在触发器下方 4px；不做任何"向上翻转" */
      this.top = r.bottom + 4;
      /* ⚠️ 弹层最小宽度 = 触发器宽度，但**封顶 360**：
         提交软件的「类别」可编辑下拉现在铺满整格（≈475px），照抄会得到一个
         475px 宽的类别列表（py 版 EditableComboBox 只有 200，观感差很多）。
         CSS 的 .combo-pop 已有 max-width: 360 ⇒ 这里必须同步封顶，
         否则 inline minWidth 会压过 max-width（min 的优先级更高）。 */
      this.minWidth = Math.min(r.width, 360);
      /* 位置不变的前提下，只把列表高度限制在下方可用空间内（至少 96px）。
         上限 300 → 420。类别有 31 项，300px 只露出 9 项，看着像"内容缺了一大半"；
              420px 能露出 12 项，滚动意图明显，又不会把窗口撑满。 */
      const below = Math.max(0, vh - r.bottom - 8);
      this.maxHeight = Math.max(96, Math.min(420, below));
    },
    /* 打开期间逐帧跟踪触发器：滚动（含内部滚动容器）、缩放、布局位移统一覆盖；
       关闭 / 卸载时停掉，不留孤儿弹层也不空转。 */
    _startTrack() {
      this._stopTrack();
      const step = () => {
        if (!this.open) { this._trackFrame = 0; return; }
        this.place();
        this._trackFrame = this.open ? requestAnimationFrame(step) : 0;
      };
      this._trackFrame = requestAnimationFrame(step);
    },
    _stopTrack() {
      if (this._trackFrame) { cancelAnimationFrame(this._trackFrame); this._trackFrame = 0; }
    },
    /* 弹层打开后把当前选中项滚进可视区（py 版 QComboBox 也是这样，
       否则 31 个类别里"当前项"可能正好在滚动区外，用户以为没选中）。 */
    scrollActiveIntoView() {
      const pop = this.$refs.pop;
      if (!pop) return;
      const hit = pop.querySelector('.combo-item.is-on');
      if (hit && hit.scrollIntoView) {
        try { hit.scrollIntoView({ block: 'nearest' }); } catch (e) { /* 老内核忽略参数 */ }
      }
    },
    pick(option) {
      if (!option) return;
      this.open = false;
      if (String(option.value) !== String(this.modelValue)) this.$emit('change', option.value, true);
    },
    /* 可编辑模式：输入框每次输入都把值抛给父组件（受控），父组件负责写回 model-value */
    /* 点击输入框：没开就开，开着不动（开着时用户可能在选文字，不能一反弹就收起）。
       箭头仍走 toggle，所以"点箭头收起"这条老语义不变。 */
    openOnEditClick() {
      if (this.disabled) return;
      if (this.open) return;
      const idx = this.options.findIndex((o) => String(o.value) === String(this.modelValue));
      this.highlightedIndex = idx >= 0 ? idx : 0;
      this.open = true;
      this.$nextTick(this.place);
    },
    /* ⚠️ 本轮修复（用户原话：「输入框点击之后点击附近的空白处结果还是不能退出输入状态，
       必须要远一点才行的bug」）：可编辑下拉的触发器整块是 cursor:text 的自绘控件，
       点它自己的内边距/空白时焦点不会自己离开输入框，弹层和"正在输入"的观感就一直挂着。
       输入框本体与箭头都用 @click.stop 拦掉了冒泡，所以**只有真·空白处**会走到这里：
       展开着 → 收起 + 主动 blur（退出输入状态）；收起着 → 当作点开了控件，聚焦并展开。 */
    onEditableBlankClick(event) {
      if (this.disabled) return;
      const edit = this.$refs.editInput;
      if (event && event.target && edit && (event.target === edit || edit.contains(event.target))) return;
      if (this.open) {
        this.open = false;
        if (edit) { try { edit.blur(); } catch (e) { /* 忽略 */ } }
        return;
      }
      if (edit) { try { edit.focus(); } catch (e) { /* 忽略 */ } }
      this.openOnEditClick();
    },
    /* Tab 进到输入框时不自动展开（那是"路过了"，不是"要点"）；
       这里只为**鼠标按住时先把别的下拉收起**保持一致性，故空实现留档 ——
       如果以后要做"聚焦即展开"，记得先确认不会打断输入法。 */
    openOnEditFocus() { /* 故意不展开：聚焦≠想打开列表（输入法/Tab 顺序都会误触发） */ },
    /* 输入框内容变化（受控） */
    onEditInput(event) {
      if (this.disabled) return;
      // 第二个参数 false = 用户手打的文本（区别于 pick() 的「从列表里选了一项」）。
      this.$emit('change', event && event.target ? event.target.value : '', false);
    },
    /* 可编辑模式键盘：↓/↑ 开列表并高亮，Enter 选当前高亮项（没有高亮就收起），Esc 收起；
       其余键（字母/中文/退格/左右移动光标）一律放行，不能拦输入。 */
    onEditKeyDown(event) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (!this.open) {
          const idx = this.options.findIndex((o) => String(o.value) === String(this.modelValue));
          this.highlightedIndex = idx >= 0 ? idx : 0;
          this.open = true;
          this.$nextTick(this.place);
          this.$nextTick(this.scrollActiveIntoView);
        } else {
          this.highlightedIndex = event.key === 'ArrowDown'
            ? Math.min(this.highlightedIndex + 1, this.options.length - 1)
            : Math.max(this.highlightedIndex - 1, 0);
        }
        return;
      }
      if (event.key === 'Enter') {
        if (this.open && this.highlightedIndex >= 0) {
          event.preventDefault();
          this.pick(this.options[this.highlightedIndex]);
        } else if (this.open) {
          this.open = false;
        }
        return;
      }
      if (event.key === 'Escape') { this.open = false; }
    },
    onItemMouseEnter(index) { this.highlightedIndex = index; },
    onTriggerKeyDown(e) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (!this.open) {
          const idx = this.options.findIndex((o) => String(o.value) === String(this.modelValue));
          this.highlightedIndex = idx >= 0 ? idx : 0;
          this.open = true;
          this.$nextTick(this.place);
          this.$nextTick(this.scrollActiveIntoView);
        } else {
          this.highlightedIndex = e.key === 'ArrowDown'
            ? Math.min(this.highlightedIndex + 1, this.options.length - 1)
            : Math.max(this.highlightedIndex - 1, 0);
        }
      } else if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        if (this.open && this.highlightedIndex >= 0) this.pick(this.options[this.highlightedIndex]);
        else this.toggle();
      } else if (e.key === 'Escape') {
        this.open = false;
      }
    },
  },
  template: `
    <div class="combo" :class="{ 'is-open': open, 'is-disabled': disabled, 'is-editable': editable }">
      <!-- 可编辑模式：触发器保留 .combo-trigger 的外观，里面换成输入框 -->
      <div v-if="editable" ref="trigger" class="combo-trigger combo-trigger-editable"
           :style="width ? { width: width + 'px' } : null"
           role="combobox" :aria-expanded="open ? 'true' : 'false'"
           @click="onEditableBlankClick">
        <!-- ⚠️ 本轮修复（用户原话：「类别那里的ui这个列表点不出来……点击这个ui没用展开的问题」）：
             可编辑模式下点击**输入框本体**也要能展开列表。以前只有右侧 12px 的箭头绑了 toggle，
             而 .combo-trigger-editable 是 cursor:text 的整块区域，用户自然去点宽的那块 →
             看起来就是"这个下拉点不开"。用 @click.stop 阻断冒泡（避免外层再收到一次），
             展开/收起都由 openOnEditClick 统一决定。 -->
        <input ref="editInput" class="combo-edit" type="text" :value="modelValue"
               :disabled="disabled" :placeholder="placeholder"
               @input="onEditInput" @keydown="onEditKeyDown"
               @click.stop="openOnEditClick" @focus="openOnEditFocus">
        <svg class="ic combo-arrow" width="12" height="12"
             @click.stop="toggle"><use href="#i-chevron_down"></use></svg>
      </div>
      <button v-else ref="trigger" type="button" class="combo-trigger"
              :style="width ? { width: width + 'px' } : null"
              :disabled="disabled" :aria-expanded="open ? 'true' : 'false'"
              @click.stop="toggle" @keydown="onTriggerKeyDown">
        <span class="combo-label">{{ current }}</span>
        <svg class="ic combo-arrow" width="12" height="12"><use href="#i-chevron_down"></use></svg>
      </button>
      <teleport to="body">
        <div v-if="open" ref="pop" class="combo-pop"
             :style="{ left: left + 'px', top: top + 'px', minWidth: minWidth + 'px',
                       maxHeight: maxHeight + 'px',
                       transformOrigin: 'top left' }"
             @mouseleave="highlightedIndex = -1">
          <button v-for="(option, index) in options" :key="String(option.value)" type="button"
                  class="combo-item"
                  :style="{ '--i': index }"
                  :class="{ 'is-on': String(option.value) === String(modelValue),
                            'is-highlighted': highlightedIndex === index }"
                  @click.stop="pick(option)"
                  @mouseenter="onItemMouseEnter(index)">{{ option.label }}</button>
        </div>
      </teleport>
    </div>
  `,
};

/* ===================== 全局 tooltip（「i」提示） =====================
   ⚠️ 必须用**一个** fixed 定位的真 DOM 元素：设置页的卡片 overflow:hidden、
      侧栏 z-index 46、抽屉 z-index 88 … 任何祖先容器都会把 ::after 裁掉。
      fixed + z-index 300（全场最高）才能保证"提示永远在最上面、永远完整"。 */
const TIP_GAP = 8;
let tipHideTimer = 0;

function _tipEl() { return document.getElementById('tip-bubble'); }

function showTip(event) {
  const host = event && event.currentTarget;
  const bubble = _tipEl();
  if (!host || !bubble) return;
  const text = host.getAttribute('data-tip') || '';
  if (!text) return;
  clearTimeout(tipHideTimer);
  bubble.textContent = text;
  bubble.classList.add('is-on');
  requestAnimationFrame(() => _placeTip(host, bubble));
}

function _placeTip(host, bubble) {
  const rect = host.getBoundingClientRect();
  const bw = bubble.offsetWidth, bh = bubble.offsetHeight;
  const vw = window.innerWidth, vh = window.innerHeight;
  let left = rect.left + rect.width / 2 - bw / 2;
  let top = rect.bottom + TIP_GAP;
  if (top + bh > vh - 8) top = rect.top - bh - TIP_GAP;
  if (top < 8) {
    top = Math.min(rect.top, vh - bh - 8);
    left = rect.right + TIP_GAP;
  }
  left = Math.max(8, Math.min(left, vw - bw - 8));
  top = Math.max(8, Math.min(top, vh - bh - 8));
  bubble.style.left = left + 'px';
  bubble.style.top = top + 'px';
}

function hideTip() {
  const bubble = _tipEl();
  if (!bubble) return;
  clearTimeout(tipHideTimer);
  tipHideTimer = setTimeout(() => bubble.classList.remove('is-on'), 60);
}

/* 滚动 / 缩放 / 失焦时立刻收起（不然气泡会停在原地很别扭） */
window.addEventListener('scroll', hideTip, true);
window.addEventListener('resize', hideTip);
window.addEventListener('blur', hideTip);

/* ===================== 全局输入框右键菜单（task-4 ④） =====================
   给所有 input / textarea / contenteditable 加自绘右键菜单：
   复制 / 粘贴 / 剪切 / 全选 / 撤销 / 重做（用户说的"左撤回/右撤回"= Undo/Redo），
   每项前置图标 + 文字下方灰色小字快捷键；按状态禁用置灰。
   ⚠️ **排除 AI 输入框与 AI 气泡**：.ai-input / .ai-rich-input / .bubble* 上的右键
      由 AI 队友的专属菜单负责（复制/全选/取消全选），这里必须让路，避免双菜单打架。
      排除只靠 class 匹配，不给 AI 区加任何代码。
   实现走 #app 外的常驻 DOM（index.html 的 #input-menu）+ 纯 JS 事件委托：
   不占 Vue 状态，切页/组件卸载天然不残留弹层。 */
const INPUT_MENU_EXCLUDE = [
  /* ⚠️ 只排除**聊天气泡**（.bubble*）—— 气泡上的右键归 AI 队友的"复制/全选"菜单
     （openAiCtx）。**AI 输入框（.ai-input / .ai-rich-input）不排除**：它就是个输入框，
     用户要的是和其它输入框一样的"复制/粘贴/剪切/全选/撤销/重做"完整编辑菜单，
     交给本通用菜单处理才对（AI 队友的菜单只管气泡，不接管输入框）。 */
  '.bubble', '.bubble-wrap', '.bubble-row',
  '.ai-msg', '.ai-bubble-edit', '.ai-no-input-menu',
];
/* 命中排除区（自身或祖先）= 交给 AI 专属菜单，这里什么都不做。 */
function _isInputMenuExcluded(el) {
  if (!el || !el.closest) return false;
  for (let i = 0; i < INPUT_MENU_EXCLUDE.length; i += 1) {
    if (el.closest(INPUT_MENU_EXCLUDE[i])) return true;
  }
  return false;
}
function _isEditableField(el) {
  if (!el || !el.tagName) return false;
  const tag = el.tagName.toLowerCase();
  if (tag === 'textarea') return true;
  if (tag === 'input') {
    /* 真正能承载文本的 input 都接管（含 readonly：快捷键输入框、只读路径框 —— 需求说
       "所有 input"，只读框同样要能复制/全选；粘贴/剪切/撤销这些**改内容**的项按
       editable 状态禁用，见 openInputMenu 里的 editable 判定）。
       checkbox/range/color 之类不承载文本，放行原生行为。 */
    const type = (el.getAttribute('type') || 'text').toLowerCase();
    return ['text', 'search', 'url', 'tel', 'password', 'email', 'number'].indexOf(type) >= 0;
  }
  if (el.isContentEditable === true) return true;
  /* ⚠️ jsdom / 个别老内核**没有** isContentEditable（返回 undefined），
     单靠上面那行会让 contenteditable 输入框（AI 富文本框就是）在自检里"永远打不开菜单"
     —— 队友探针那条"AI 输入框排除"以前就是**假通过**（根本没接管，谈不上排除）。
     兜底：直接看 contenteditable 属性（自己或最近的祖先），值不是 false/inherit 就算可编辑。
     真浏览器两条都成立，这条只是把"检测不到"补成"检测得到"。 */
  const host = el.closest && el.closest('[contenteditable]');
  if (host) {
    const v = (host.getAttribute('contenteditable') || '').toLowerCase();
    if (v !== 'false' && v !== 'inherit') return true;
  }
  return false;
}
const INPUT_MENU_ITEMS = [
  /* fallback 按当前语言取：copy/paste/cut/undo/redo 这几个键**不在**三语语言包里
     （语言包目录不归本任务改），t() 查不到时如果只给中文 fallback，英文界面会露中文。
     所以每项带 zh / en 两套兜底文案，按 I18N.language 选（繁体与简体共用汉字兜底，
     词形差异极小；后端语言包补键后可删这层）。 */
  { cmd: 'copy', key: 'copy', zh: '复制', en: 'Copy', icon: 'i-copy', hotkey: 'Ctrl+C' },
  { cmd: 'paste', key: 'paste', zh: '粘贴', en: 'Paste', icon: 'i-paste', hotkey: 'Ctrl+V' },
  { cmd: 'cut', key: 'cut', zh: '剪切', en: 'Cut', icon: 'i-cut', hotkey: 'Ctrl+X' },
  { cmd: 'select-all', key: 'select_all', zh: '全选', en: 'Select All', icon: 'i-select_all', hotkey: 'Ctrl+A' },
  { cmd: 'undo', key: 'undo', zh: '撤销', en: 'Undo', icon: 'i-undo', hotkey: 'Ctrl+Z' },
  { cmd: 'redo', key: 'redo', zh: '重做', en: 'Redo', icon: 'i-redo', hotkey: 'Ctrl+Y' },
];
/* 「取消全选」不是独立命令：同一个按钮（data-cmd="select-all"）在"已全选"状态下
   换成这条文案（任务 8）。快捷键仍是 Ctrl+A（浏览器全选行为不变）。 */
const INPUT_MENU_DESELECT_ITEM =
  { cmd: 'deselect-all', key: 'deselect_all', zh: '取消全选', en: 'Deselect All', icon: 'i-select_all', hotkey: 'Ctrl+A' };
function _inputMenuLabel(item) {
  void I18N.version;
  const hit = I18N.map[item.key];
  if (typeof hit === 'string' && hit) return hit;
  return String(I18N.language || '').indexOf('English') >= 0 ? item.en : item.zh;
}
const inputMenuState = { open: false, target: null, allSelected: false };
/* 「已全选」快照：contextmenu **捕获阶段最前面**记一次（见文件下方 document 监听），
   因为右键可能让 target 先失焦、把 selectionStart/End 清掉 ——
   等 openInputMenu 里再读就永远读不到"已全选"了（用户报的"怎么全选都没有取消全选"）。
   记录 el + 那一刻是否全选；只认"同一个元素"的快照，换框/换页面自动失效。 */
/* 右键前的选区快照：WebView2 里 contextmenu 之后可能立刻改焦点/清选区，
   所以"有没有选内容"和"是不是全选"都要在**第一行**就记下来（见 contextmenu 监听）。 */
const _lastSelectionSnapshot = { el: null, allSelected: false, hasSelection: false, at: 0 };

function _inputMenuEl() { return document.getElementById('input-menu'); }

function closeInputMenu() {
  const menu = _inputMenuEl();
  if (menu) menu.hidden = true;
  inputMenuState.open = false;
  inputMenuState.target = null;
  inputMenuState.allSelected = false;
}

/* 当前状态探测：无选区 → 复制/剪切禁用；无内容 → 全选禁用；
   剪贴板读不到时**保守视为可用**（权限/后端缺失都不能把功能点灰）。 */
function _fieldSelection(el) {
  if (!el) return false;
  const tag = el.tagName ? el.tagName.toLowerCase() : '';
  /* ⚠️ textarea 必须和 input 一样读 selectionStart/End。
     根因（用户原话：「我框选了内容点击右键结果很多按钮都是灰色包括复制按钮都无法使用」）：
     以前这里只判了 input，textarea 掉进下面的 window.getSelection() 分支 —— 而
     textarea 的选区**不属于文档选区**（window.getSelection() 对它恒为 collapsed），
     于是文本框里明明框选了一整段，菜单里的复制/剪切仍然全灰。 */
  if (tag === 'input' || tag === 'textarea') {
    try { return (el.selectionEnd || 0) > (el.selectionStart || 0); } catch (e) { return false; }
  }
  const sel = window.getSelection && window.getSelection();
  return !!(sel && !sel.isCollapsed && String(sel).length);
}
function _fieldHasContent(el) {
  if (!el) return false;
  if (el.tagName) {
    const tag = el.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea') return String(el.value || '').length > 0;
  }
  return String(el.innerText || el.textContent || '').replace(/\u200b/g, '').trim().length > 0
    || !!(el.querySelector && el.querySelector('img,br'));
}
/* 本轮需求（任务 8）：textarea/input 处于「已全选」（非空、selectionStart===0 且
   selectionEnd===value.length）时，菜单里那一项显示「取消全选」，点击清空选区。
   contenteditable（AI 富文本框就是）用 Range 边界比较：选区起止恰好贴着内容首尾。
   认不出来一律 false（宁可继续显示「全选」，也不能把「取消全选」误挂到没全选的框上）。 */
function _fieldAllSelected(el) {
  if (!el) return false;
  const tag = (el.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea') {
    const len = String(el.value || '').length;
    if (!len) return false;
    try {
      return (el.selectionStart || 0) === 0 && (el.selectionEnd || 0) === len;
    } catch (e) { return false; }
  }
  try {
    const sel = window.getSelection && window.getSelection();
    if (!sel || sel.isCollapsed || sel.rangeCount <= 0) return false;
    const full = document.createRange();
    full.selectNodeContents(el);
    const r = sel.getRangeAt(0);
    /* r 一定落在 full 内部：与 full 首尾对齐 = 已全选 */
    return full.compareBoundaryPoints(Range.START_TO_START, r) === 0
      && full.compareBoundaryPoints(Range.END_TO_END, r) === 0;
  } catch (e) { return false; }
}
function _clearFieldSelection(el) {
  const tag = (el.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea') {
    const at = String(el.value || '').length;
    try { el.setSelectionRange(at, at); } catch (e) {}   // 收拢到末尾，不丢焦点
    return;
  }
  try {
    const sel = window.getSelection && window.getSelection();
    if (!sel) return;
    const at = String(el.textContent || '').length;
    /* 光标放到内容末尾（collapsed 选区 = 无高亮） */
    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    sel.removeAllRanges();
    sel.addRange(range);
    void at;
  } catch (e) { /* 静默 */ }
}
function _fieldEditable(el) {
  if (!el || !el.tagName) return false;
  const tag = el.tagName.toLowerCase();
  if (tag === 'input') return !el.readOnly && !el.disabled;
  if (tag === 'textarea') return !el.readOnly && !el.disabled;
  return el.isContentEditable === true;
}
async function _clipboardLooksEmpty() {
  /* ① 后端原生剪贴板（pywebview 场景最可靠）；② navigator.clipboard（浏览器模式）；
     都拿不到 → 返回 false（视为"有内容"，粘贴保持可点，点了失败再 toast）。 */
  try {
    const result = await bridge.tryCall('clipboard.read');
    if (result && result.ok && typeof result.text === 'string') return result.text.length === 0;
  } catch (e) { /* 落到下一级 */ }
  try {
    if (navigator.clipboard && navigator.clipboard.readText) {
      const text = await navigator.clipboard.readText();
      return String(text || '').length === 0;
    }
  } catch (e) { /* 无权限：保守放行 */ }
  return false;
}
function _applyInputMenuStates(states) {
  const menu = _inputMenuEl();
  if (!menu) return;
  Array.prototype.forEach.call(menu.querySelectorAll('.input-menu-item'), (btn) => {
    const cmd = btn.getAttribute('data-cmd');
    const enabled = !!states[cmd];
    btn.disabled = !enabled;
    btn.classList.toggle('is-disabled', !enabled);
  });
}
async function openInputMenu(event, target) {
  const menu = _inputMenuEl();
  if (!menu) return;
  /* ⚠️⚠️ 本轮修复（用户原话：「全选不管我怎么全选右键还是没有取消全选」）。
     根因就在这几行之前的写法上：判定"已全选"用的是**打开菜单那一刻**的实时选区，
     但右键（contextmenu）在部分浏览器/WebView2 上会让 target **先失焦**，
     失焦时 input/textarea 的 selectionStart/End 被重置成同一位置（或 0），
     `_fieldAllSelected()` 于是永远返回 false → 菜单永远显示「全选」。
     修法（两层，缺一不可）：
       ① 打开菜单**之前**，若"这一轮右键的落点元素"与上次记录的全选元素一致，
          就用**记住的状态**，而不是重新读可能已被失焦清掉的选区；
       ② 在 contextmenu 的**捕获阶段最前面**（见下面 document 监听）先抓一次
          选区快照存进 _lastSelectionSnapshot，openInputMenu 优先读它。
     同时把"点菜单项时 target 可能已变"的校验补上（点击时 target 必须还在文档里）。 */
  const liveAll = _fieldAllSelected(target);
  const snap = _lastSelectionSnapshot;
  const snapAll = !!(snap && snap.el === target && snap.allSelected);
  /* 两者取或：实时候选中就准；实时判定因失焦丢了，但快照证明刚才确实全选 → 也算全选 */
  inputMenuState.target = target;
  inputMenuState.open = true;
  inputMenuState.allSelected = liveAll || snapAll;
  /* 文案跟随语言：每次打开用 t() 重刷（I18N 是全局 map，切语言即生效） */
  const items = menu.querySelectorAll('.input-menu-item');
  INPUT_MENU_ITEMS.forEach((item, i) => {
    const btn = items[i];
    if (!btn) return;
    /* 「取消全选」在"已全选"时用它自己的文案与 command（**不是**只换字：
       以前把 cmd 也换成 deselect-all 的下标会导致 state 查表错位）。
       这里保持按钮的 data-cmd 不变（select-all），只换 label —— 点击时按
       `inputMenuState.allSelected` 决定是"清空选区"还是"全选"。 */
    btn.setAttribute('data-cmd', item.cmd);
    const label = btn.querySelector('.imi-label');
    if (label) {
      label.textContent = (item.cmd === 'select-all' && inputMenuState.allSelected)
        ? _inputMenuLabel(INPUT_MENU_DESELECT_ITEM)
        : _inputMenuLabel(item);
    }
    /* 本轮需求：快捷键放到文字**右侧**并且**加括号包起来** → "复制（Ctrl+C）"。
       左右位置由 CSS 排（.imi-key 与 .imi-label 同级 + margin-left:auto），
       括号在这里加（写死在 HTML 里的话切语言重刷文案会丢括号）。 */
    const hotkey = btn.querySelector('.imi-key');
    if (hotkey) hotkey.textContent = item.hotkey ? '（' + item.hotkey + '）' : '';
  });
  menu.hidden = false;
  /* 先摆到屏幕外量尺寸，再夹到窗口内（不超出窗口） */
  menu.style.left = '-9999px';
  menu.style.top = '-9999px';
  const x = event.clientX; const y = event.clientY;
  await nextFrameMeasurePlace(menu, x, y);
  /* 状态：先同步算好（选区/内容），剪贴板异步补刀 */
  /* 实时选区 + 右键那一瞬的快照，两者取或：实时读得到就以实时为准；
     读不到（失焦/引擎清了选区）但快照证明刚才确实选了 → 仍然可用。 */
  const liveSel = _fieldSelection(target);
  const hasSel = liveSel || !!(snap && snap.el === target && snap.hasSelection);
  const hasContent = _fieldHasContent(target);
  const editable = _fieldEditable(target);
  const hist = _fieldHistories.get(target);
  /* 撤销/重做按"栈里真的有东西"决定是否可点：以前恒为可点，点了才弹
     「没有可撤销的操作了」，等于把状态错误推给用户。*/
  const canUndo = !!hist && (hist.past.length > 0
    || !_histEqual(_fieldSnapshot(target), hist.last));
  const canRedo = !!hist && hist.future.length > 0;
  _applyInputMenuStates({
    copy: hasSel,
    cut: hasSel && editable,
    /* 粘贴：只读框改了内容也存不进去（快捷键框 readonly），一并禁用；
       可编辑框先置可用，剪贴板确认是空的再置灰（保守：读不到=可用） */
    paste: editable,
    'select-all': hasContent,
    undo: editable && canUndo,
    redo: editable && canRedo,
  });
  const empty = await _clipboardLooksEmpty();
  if (inputMenuState.open && inputMenuState.target === target) {
    const btn = menu.querySelector('[data-cmd="paste"]');
    if (btn) {
      /* 只读框保持禁用（上面已置）；可编辑框只在"确认剪贴板为空"时置灰 */
      const off = empty || !editable;
      btn.disabled = off;
      btn.classList.toggle('is-disabled', off);
    }
  }
}
function nextFrameMeasurePlace(menu, x, y) {
  return new Promise((resolve) => {
    /* 双帧：第一帧让 Vue 的 DOM patch 落地，第二帧量尺寸（transition 的 enter-from
       只有 opacity/scale，不影响 offsetWidth/Height，量出来的就是菜单真实大小）。 */
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const w = menu.offsetWidth; const h = menu.offsetHeight;
      const vw = window.innerWidth; const vh = window.innerHeight;
      let left = x; let top = y;
      if (left + w > vw - 8) left = Math.max(8, vw - w - 8);
      if (top + h > vh - 8) top = Math.max(8, vh - h - 8);
      menu.style.left = left + 'px';
      menu.style.top = top + 'px';
      resolve();
    }));
  });
}
function _execInputMenuCommand(cmd) {
  const target = inputMenuState.target;
  const wasAllSelected = inputMenuState.allSelected;
  closeInputMenu();
  if (!target || !document.contains(target)) return;
  /* ⚠️ 本轮（F9 关联修复）：确认 target 仍然是"当前这个输入框"。
     用户报的另一个症状是"点了菜单项，结果动的是别的页面/别的框" ——
     菜单打开期间页面切换/组件重渲染会把原元素换掉，此时必须收手而不是
     对着一份"孤儿节点"执行编辑命令（那是无效写入，还容易把焦点抢到别处）。 */
  const active = document.activeElement;
  if (active && active !== target && _isEditableField(active)
      && !target.contains(active) && target.tagName) {
    /* 有另一个输入框抢到了焦点：那说明用户已经换框了，这一击不该作用于旧框 */
    return;
  }
  /* ⚠️ 不无脑 focus：快捷键输入框 @focus 会进入"请按下组合键"录制态，
     右键复制不该触发它。只有**要改内容/改选区**的命令、且目标真的可编辑时才聚焦；
     copy 直接读选区，不需要焦点。readonly 框的 select-all 用 setSelectionRange，
     同样不依赖 focus。 */
  const editable = _fieldEditable(target);
  if (editable && cmd !== 'copy') {
    try { target.focus({ preventScroll: true }); } catch (e) { try { target.focus(); } catch (_) {} }
  }
  const tag = (target.tagName || '').toLowerCase();
  if (cmd === 'copy') {
    _copySelectionFrom(target, tag);
  } else if (cmd === 'cut') {
    _copySelectionFrom(target, tag);
    _deleteSelection(target, tag);
  } else if (cmd === 'select-all') {
    /* 打开菜单那一刻就是"已全选"→ 这一项是「取消全选」：清空选区而不是再全选一遍。
       ⚠️ 本轮（F9 关联）：清空选区后还要**保住焦点**（否则用户看到的是"选区没了、
          光标也不知道跑哪去了"）；_clearFieldSelection 内部已经 setSelectionRange 到末尾。 */
    if (wasAllSelected) _clearFieldSelection(target);
    else _selectAllIn(target, tag);
  } else if (cmd === 'paste') {
    _pasteInto(target, tag);
  } else if (cmd === 'undo' || cmd === 'redo') {
    _undoRedo(target, cmd);
  }
}
async function _readClipboardText() {
  try {
    const result = await bridge.tryCall('clipboard.read');
    if (result && result.ok && typeof result.text === 'string') return result.text;
  } catch (e) { /* 下一级 */ }
  try {
    if (navigator.clipboard && navigator.clipboard.readText) return await navigator.clipboard.readText();
  } catch (e) { /* 无权限 */ }
  return null;
}
function _copySelectionFrom(target, tag) {
  let text = '';
  if (tag === 'input' || tag === 'textarea') {
    const start = target.selectionStart || 0;
    const end = target.selectionEnd || 0;
    text = String(target.value || '').slice(start, end);
  } else {
    const sel = window.getSelection && window.getSelection();
    text = sel ? String(sel) : '';
  }
  if (!text) return;
  /* 与 copyText 同款三级兜底：后端原生 → navigator.clipboard → execCommand */
  bridge.tryCall('clipboard.write', text).then((result) => {
    if (result && result.ok) return;
    try { navigator.clipboard.writeText(text); } catch (e) { _execFallback('copy', text); }
  }).catch(() => { _execFallback('copy', text); });
}
function _execFallback(command, value) {
  try { document.execCommand(command, false, value === undefined ? null : value); } catch (e) {}
}
/* 模块级代码拿不到 setup 里的 toast()；这里做一层"有 Vue 实例就用真提示、没有就静默"的兜底。
   （App 挂载后把实例挂到 window.__TOOLSGCP_APP__，见文件末尾 start() 的 mount 之后） */
function _menuToast(message, type) {
  try {
    const vm = window.__TOOLSGCP_APP__;
    if (vm && typeof vm.toast === 'function') { vm.toast(message, type || 'info'); return; }
  } catch (e) { /* 静默 */ }
}
function _deleteSelection(target, tag) {
  if (tag === 'input' || tag === 'textarea') {
    const start = target.selectionStart || 0;
    const end = target.selectionEnd || 0;
    if (end <= start) return;
    const next = String(target.value || '').slice(0, start) + String(target.value || '').slice(end);
    _setFieldValue(target, next);
    try { target.setSelectionRange(start, start); } catch (e) {}
  } else {
    _execFallback('delete');
  }
}
function _setFieldValue(target, value) {
  /* 原生 setter + input 事件：Vue v-model / 监听 input 的组件都能收到 */
  const proto = target.tagName.toLowerCase() === 'input'
    ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(target, value);
  target.dispatchEvent(new Event('input', { bubbles: true }));
  target.dispatchEvent(new Event('change', { bubbles: true }));
}
function _selectAllIn(target, tag) {
  if (tag === 'input' || tag === 'textarea') {
    try { target.setSelectionRange(0, String(target.value || '').length); } catch (e) {}
  } else {
    _execFallback('selectAll');
  }
}
async function _pasteInto(target, tag) {
  const text = await _readClipboardText();
  if (text == null) { _menuToast(t('paste_failed', '读取剪贴板失败，请用 Ctrl+V'), 'error'); return; }
  if (!text) return;
  if (tag === 'input' || tag === 'textarea') {
    const start = target.selectionStart || 0;
    const end = target.selectionEnd || 0;
    const next = String(target.value || '').slice(0, start) + text + String(target.value || '').slice(end);
    _setFieldValue(target, next);
    try { target.setSelectionRange(start + text.length, start + text.length); } catch (e) {}
  } else {
    try {
      /* contenteditable：insertText 走浏览器编辑事务，撤销栈与输入法都正常 */
      document.execCommand('insertText', false, text);
    } catch (e) { _execFallback('paste'); }
  }
}
/* ===========================================================================
 * 每个输入框**独立的**撤销/重做栈（本轮修复，用户原话：
 *   「输入框我发现在一个输入框内一直点菜单中的撤回或重做如果上一步或者之前的下一步
 *     在其他输入框他会直接到其他页面或者地方的那个输入框变为输入状态撤回或重做bug，
 *     但我的意思是只要当前输入框内的这个状态所以每个输入框这个状态是要独立的」）
 *
 * 根因：以前 `_undoRedo` 走的是 `document.execCommand('undo'/'redo')` ——
 *   那是**文档级**编辑历史（浏览器的 undo manager 全局一份），
 *   在 A 框里撤销一下，可能把 B 框（甚至别的页面/另一个组件）的上一步操作回滚掉，
 *   表现就是"撤销把别的输入框变成输入状态 / 内容乱跳"。
 *
 * 现在：每个元素一份快照栈（WeakMap，元素回收即释放）：
 *   · 记录时机 = 元素上的 input 事件（含粘贴/剪切/程序化写入），**按时间合并**
 *     （300ms 内的连续输入算一步，否则打 20 个字要按 20 次撤销）；
 *   · 撤销 = 弹一步恢复 value + 光标位置；重做 = 反向栈；
 *   · 只作用于**当前这一个元素**，跟别的框、别的页面完全无关；
 *   · 上限 100 步（够用且不会吃内存）；
 *   · 我们自己写入时置 `_selfWrite` 标志，避免把"撤销本身"又记成新的一步。
 * ⚠️ 快捷键 Ctrl+Z / Ctrl+Y(Shift+Z) 也走这套栈（否则键盘撤销还是文档级的，
 *    等于 bug 只修了右键菜单那一半）。中文输入法 composition 期间不拦。
 * =========================================================================*/
const _fieldHistories = new WeakMap();
const FIELD_HISTORY_MAX = 100;
const FIELD_HISTORY_MERGE_MS = 300;
let _fieldSelfWrite = false;

function _fieldSnapshot(el) {
  if (!el) return null;
  const tag = (el.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea') {
    let at = 0;
    try { at = el.selectionStart || 0; } catch (e) { at = 0; }
    return { value: String(el.value || ''), at };
  }
  /* contenteditable：存 innerHTML（富文本输入框里有 @token/slash-token 这些 DOM） */
  return { html: String(el.innerHTML || ''), at: 0 };
}
function _fieldHistory(el) {
  let h = _fieldHistories.get(el);
  if (!h) {
    h = { past: [], future: [], last: _fieldSnapshot(el), timer: 0, stamp: 0 };
    _fieldHistories.set(el, h);
  }
  return h;
}
function _histEqual(a, b) {
  if (!a || !b) return false;
  if (a.value !== undefined || b.value !== undefined) {
    return String(a.value === undefined ? '' : a.value) === String(b.value === undefined ? '' : b.value);
  }
  return String(a.html || '') === String(b.html || '');
}
/** 记录一步（input 事件驱动，合并短时间内的连续输入） */
function _fieldHistoryPush(el) {
  if (!el || _fieldSelfWrite) return;
  const h = _fieldHistory(el);
  const snap = _fieldSnapshot(el);
  if (!snap) return;
  if (_histEqual(snap, h.last)) { h.last = snap; return; }   // 内容没变（如纯移动光标）
  const now = Date.now();
  const merged = h.timer && (now - h.stamp) < FIELD_HISTORY_MERGE_MS;
  if (h.timer) { clearTimeout(h.timer); h.timer = 0; }
  if (!merged) {
    /* 把"上一步的内容"推进 past；last 永远保存"当前内容之前那份" */
    if (h.last) h.past.push(h.last);
    if (h.past.length > FIELD_HISTORY_MAX) h.past.splice(0, h.past.length - FIELD_HISTORY_MAX);
    h.future.length = 0;                                      // 新输入让"重做"作废
  }
  h.last = snap;
  h.stamp = now;
  /* 合并窗口：窗口内继续输入就不再另起一步 */
  h.timer = setTimeout(() => { h.timer = 0; }, FIELD_HISTORY_MERGE_MS);
}
function _fieldApplySnapshot(el, snap) {
  if (!el || !snap) return;
  const tag = (el.tagName || '').toLowerCase();
  _fieldSelfWrite = true;
  try {
    if (tag === 'input' || tag === 'textarea') {
      _setFieldValue(el, String(snap.value === undefined ? '' : snap.value));
      const at = Math.max(0, Math.min(String(snap.value || '').length, snap.at || 0));
      try { el.setSelectionRange(at, at); } catch (e) { /* 某些类型不支持 */ }
    } else {
      el.innerHTML = String(snap.html || '');
      el.dispatchEvent(new Event('input', { bubbles: true }));
      try { el.focus({ preventScroll: true }); } catch (e) { /* 忽略 */ }
    }
  } finally {
    _fieldSelfWrite = false;
  }
}
/** 统一的撤销/重做（右键菜单与 Ctrl+Z/Y 共用这一条实现） */
function _undoRedo(target, cmd) {
  if (!target || !_fieldEditable(target)) return false;
  const h = _fieldHistory(target);
  /* ⚠️ 先把"还没提交的当前内容"落定：用户打完字立刻撤销时，
     last 可能还是旧值（合并定时器没到），不补这一步就会"撤销没反应"。 */
  const now = _fieldSnapshot(target);
  if (now && !_histEqual(now, h.last)) {
    if (h.timer) { clearTimeout(h.timer); h.timer = 0; }
    if (h.last) h.past.push(h.last);
    if (h.past.length > FIELD_HISTORY_MAX) h.past.splice(0, h.past.length - FIELD_HISTORY_MAX);
    h.last = now;
    h.future.length = 0;
  }
  if (cmd === 'undo') {
    const prev = h.past.pop();
    if (!prev) { _menuToast(t('undo_none', '没有可撤销的操作了'), 'info'); return false; }
    if (h.last) h.future.push(h.last);
    h.last = prev;
    _fieldApplySnapshot(target, prev);
    return true;
  }
  const next = h.future.pop();
  if (!next) { _menuToast(t('redo_none', '没有可重做的操作了'), 'info'); return false; }
  if (h.last) h.past.push(h.last);
  h.last = next;
  _fieldApplySnapshot(target, next);
  return true;
}
/* ⚠️⚠️ 撤销栈的**基线**必须在内容变化之前种下（用户原话：
   「我刚刚不小心删除了一个字我按撤回...结果他说没有可撤回的东西了」）。
   根因：_fieldHistory(el) 首次被调用是在**第一次 input 事件里**，而那时 el.value
   已经是改后内容 → h.last 直接等于"改后"，紧接着 _histEqual(snap, h.last) 相等
   直接 return ⇒ 第一次修改永远不会入栈 ⇒ past 恒空 ⇒ 撤销永远说"没有可撤销的操作"。
   修法：在 beforeinput（改动发生**前**触发）与 focusin 时先建好历史对象，
   让 h.last 保存"未改之前"的内容；这样第一次 input 就能把真正的旧值推进 past。
   （focusin 兜住不触发 beforeinput 的写入路径：右键粘贴、拖拽、脚本 setRangeText 等；
     beforeinput 兜住"已聚焦后才开始输入"这条最常见路径。两处都只在**没有历史**时
     建对象，已有历史绝不覆盖 last。）*/
function _fieldHistorySeed(el) {
  if (!el || _fieldSelfWrite) return;
  if (_fieldHistories.has(el)) return;
  const snap = _fieldSnapshot(el);
  if (snap) _fieldHistories.set(el, { past: [], future: [], last: snap, timer: 0, stamp: 0 });
}
document.addEventListener('focusin', (event) => {
  const el = event.target;
  if (el && _fieldEditable(el)) _fieldHistorySeed(el);
}, true);
document.addEventListener('beforeinput', (event) => {
  const el = event.target;
  if (el && _fieldEditable(el)) _fieldHistorySeed(el);
}, true);
/* 记录来源：document 捕获阶段的 input 事件（覆盖所有 input/textarea/contenteditable，
   包括 Vue 组件内部自己渲染出来的那些，不用逐个元素 addEventListener）。 */
document.addEventListener('input', (event) => {
  const el = event.target;
  if (!el || !_fieldEditable(el)) return;
  _fieldHistoryPush(el);
}, true);
/* ⚠️ Ctrl+C / Ctrl+X：改走我们自己的 Win32 剪贴板（用户原话：
   「我用快捷键ctrl+c复制了但是我win+v查看粘贴板发现没有它」）。
   根因：浏览器原生 copy 用的是 WebView2 内部那条延迟渲染剪贴板路径，
   写进去的文本不参与 Windows 剪贴板历史（Win+V），所以粘贴板上什么都没有。
   修法：有选区时拦下来，调 _copySelectionFrom（三级兜底第一级就是
   bridge 'clipboard.write' = Win32 SetClipboardData，会进 Win+V 历史），
   并 preventDefault 防止浏览器再覆盖一次。Ctrl+V 不拦：系统剪贴板写入后浏览器原生
   粘贴本来就能读到，自己造 insertText 反而更容易破坏输入法/富文本事务。 */
document.addEventListener('keydown', (event) => {
  if (!event.ctrlKey || event.altKey || event.metaKey) return;
  if (event.isComposing || event.keyCode === 229) return;
  const key = String(event.key || '').toLowerCase();
  if (key !== 'c' && key !== 'x') return;
  if (event.shiftKey) return;                 // Ctrl+Shift+C 常是开发者工具/别的语义，放过
  const el = event.target;
  if (!el || !_isEditableField(el)) return;
  if (!_fieldSelection(el)) return;           // 没选区：交回浏览器原生（选中空白/光标态）
  event.preventDefault();
  event.stopPropagation();
  const tag = (el.tagName || '').toLowerCase();
  _copySelectionFrom(el, tag);
  if (key === 'x' && _fieldEditable(el)) _deleteSelection(el, tag);
}, true);
/* 快捷键：Ctrl+Z 撤销 / Ctrl+Y 或 Ctrl+Shift+Z 重做（走同一套 per-field 栈）
   ⚠️ composition（中文输入法组词）期间不拦：那时浏览器的输入事务不能被我们打断。
   ⚠️ 只处理"我们的栈里有记录"的可编辑元素，其余（比如 body 级）保持浏览器原生行为。 */
document.addEventListener('keydown', (event) => {
  if (!event.ctrlKey || event.altKey) return;
  if (event.isComposing || event.keyCode === 229) return;
  const key = String(event.key || '').toLowerCase();
  let cmd = '';
  if (key === 'z' && !event.shiftKey) cmd = 'undo';
  else if (key === 'y' || (key === 'z' && event.shiftKey)) cmd = 'redo';
  if (!cmd) return;
  const el = event.target;
  if (!el || !_fieldEditable(el)) return;
  const h = _fieldHistories.get(el);
  if (!h) return;                       // 没有历史：交回浏览器原生，别抢
  event.preventDefault();
  event.stopPropagation();
  _undoRedo(el, cmd);
}, true);
/* document 级委托：contextmenu 命中可编辑控件（排除 AI 区）→ 拦原生菜单、开自绘菜单。
   ⚠️ 只 preventDefault 菜单本身，不拦任何 keydown / 不碰 beforeinput：
      Ctrl+C/V/X/A/Z/Y 快捷键与中文输入法 composition 全程不受影响。 */
document.addEventListener('contextmenu', (event) => {
  const target = event.target;
  /* ⚠️ 第一件事：抓「全选状态」快照（见 _lastSelectionSnapshot 的注释）。
     必须放在**任何可能失焦的动作之前**（preventDefault/聚焦切换都会影响选区），
     所以这里是捕获阶段的第一行，连 _isEditableField 判断都排在它后面。 */
  try {
    _lastSelectionSnapshot.el = null;
    _lastSelectionSnapshot.hasSelection = false;
    if (target && _isEditableField(target)) {
      _lastSelectionSnapshot.el = target;
      _lastSelectionSnapshot.allSelected = _fieldAllSelected(target);
      _lastSelectionSnapshot.hasSelection = _fieldSelection(target);
      _lastSelectionSnapshot.at = Date.now();
    }
  } catch (e) { /* 拿不到就按"未全选"处理，行为不比旧版差 */ }
  if (!_isEditableField(target)) {
    /* 菜单开着时右键别处：关掉，让该处自己的处理继续（如卡片菜单） */
    if (inputMenuState.open) closeInputMenu();
    return;
  }
  if (_isInputMenuExcluded(target)) return;
  event.preventDefault();
  openInputMenu(event, target);
}, true);
/* ⚠️ 本轮修复（用户原话：「输入框点击之后点击附近的空白处结果还是不能退出输入状态
   必须要远一点才行的bug」）——「退出输入状态」= 焦点真的离开输入框。
   Chromium 正常情况下点空白会把焦点交给 body，但这个界面里输入框四周几乎全是
   **自绘控件**（下拉触发器整块 cursor:text、chip、分段控制器、卡片、图标按钮…），
   点在"看起来是空白、其实还待在同一个自绘控件里"的位置时焦点并不会走，
   于是聚焦环、下拉弹层、以及"正在输入"的观感一直挂着，必须点到很远才生效。
   这里加一层明确兜底：按下的位置既不是输入区、也不是会自己处理焦点的交互元素
   （按钮/链接/标签/下拉弹层/右键菜单/分段项）时，主动把焦点从当前输入框收回。
   ⚠️ 只 blur，**不 preventDefault**：文本选择、滚动条拖动、按钮点击全部照常。 */
document.addEventListener('mousedown', (event) => {
  const active = document.activeElement;
  if (!active || active === document.body || !_isEditableField(active)) return;
  const target = event.target;
  if (!target || !target.closest) return;
  /* 属性写法要和项目里既有的判定一致（app.js 滚动接管那条用的是
     `[contenteditable=""], [contenteditable="true"]` 两种都列）——
     富文本框在某些状态下就是空值写法，只认 "true" 会把它误判成"空白处"。 */
  if (target.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"], button, a, label')) return;
  /* .combo-trigger 也豁免：可编辑下拉的空白处由组件自己的 onEditableBlankClick 处理
     （它要区分"收起着点开来"和"展开着收掉"），这里抢先 blur 会让它随后 focus 回去，
     白白制造一次 blur→focus 抖动。 */
  if (target.closest('.combo-trigger')) return;
  if (target.closest('.combo-pop, #input-menu, .seg-item, .chip, .dropdown-panel')) return;
  try { active.blur(); } catch (e) { /* 老内核偶发抛错，忽略即可 */ }
}, true);
/* 点其它地方 / 滚动 / 缩放 / 失焦：收起（菜单项自己的 mousedown 不算"外面"） */
document.addEventListener('mousedown', (event) => {
  if (!inputMenuState.open) return;
  const menu = _inputMenuEl();
  if (menu && event.target.closest && event.target.closest('#input-menu')) return;
  closeInputMenu();
}, true);
document.addEventListener('click', (event) => {
  const btn = event.target && event.target.closest && event.target.closest('#input-menu .input-menu-item');
  if (!btn || btn.disabled) return;
  _execInputMenuCommand(btn.getAttribute('data-cmd'));
});
window.addEventListener('scroll', () => { if (inputMenuState.open) closeInputMenu(); }, true);
window.addEventListener('resize', () => { if (inputMenuState.open) closeInputMenu(); });
window.addEventListener('blur', () => { if (inputMenuState.open) closeInputMenu(); });
/* Esc：菜单开着先关菜单（捕获阶段先于 combo/app 的 Esc 链，且关掉后不再传播拦截） */
window.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape' || !inputMenuState.open) return;
  closeInputMenu();
  event.stopPropagation();
}, true);

/* ===================== 启动 ===================== */
(function start(attempt) {
  if (typeof Vue === 'undefined') {
    if (attempt > 80) {
      const host = document.getElementById('app');
      if (host) {
        host.innerHTML = '<div style="padding:40px;font:14px/1.7 Consolas,monospace;color:#e8e8e8">'
          + '<b>Vue 未加载</b><br>本地 webui/js/vendor/vue.global.prod.js 缺失，且 CDN 兜底也没成功。'
          + '<br>请检查网络或补回 vendor 文件。</div>';
      }
      return;
    }
    setTimeout(() => start(attempt + 1), 100);
    return;
  }

  const app = createApp(App);
  app.component('combo', Combo);
  /* 资源库加载提示（页面内嵌版，见 ResourceLoading 的注释）*/
  app.component('resource-loading', ResourceLoading);
  /* AI 输入框富文本组件（rich-input.js，经典脚本先于本文件加载）。
     ⚠️ 不用 <script type="module">：项目 webui 没有构建链，所有 js 都是全局经典脚本。 */
  if (window.RichAiInput) app.component('rich-ai-input', window.RichAiInput);

  /* setup() 抛错时把原因写进标题，避免"黑屏无提示" */
  const _origSetup = App.setup;
  App.setup = function () {
    try {
      return _origSetup.apply(this, arguments);
    } catch (e) {
      console.error('[ToolsGCP] setup() threw:', e);
      try { document.title = 'SETUP_ERR: ' + (e && e.message ? e.message : e); } catch (_) {}
      throw e;
    }
  };

  app.config.errorHandler = (error) => {
    console.error('[ToolsGCP] vue error', error);
    if (bridge.ready) {
      bridge.call('log.client', 'err', '界面',
        '前端异常: ' + (error && error.message ? error.message : String(error))).catch(() => {});
    }
  };
  const _vm = app.mount('#app');
  /* 全局输入框右键菜单（模块级代码）借实例调用 setup 里的 toast；
     只读引用，不在菜单逻辑里碰任何 Vue 状态。 */
  window.__TOOLSGCP_APP__ = _vm;
})(0);
