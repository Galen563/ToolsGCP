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
const SYSTEMS = ['全平台', 'Windows', 'macOS', 'Android', 'iOS', 'Linux', 'web', '其他'];    // resource_schema.py:22
const ARCHITECTURES = ['x64', 'x86', 'arm64', 'arm', 'Apple Silicon', '其他'];               // resource_schema.py:27
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
  splash_screen_duration: 2, auto_search: true, hotkey_enabled: true,
  hotkey_search: 'Ctrl+Q', hotkey_ai: 'Ctrl+Alt+G', search_card_size: 'medium',
  search_view: 'tile', search_show_github: true, search_show_view_switch: true,
  plugin_view: 'grid', resource_source: 'cloud', local_resource_dir: '',
  update_channel: 'all', api_key: '', api_key_enc: '', model_name: '',
  ai_provider: 'deepseek', api_base: 'https://api.deepseek.com/v1',
  ai_enabled: false, ai_sidebar_mode: false, limit_token_output: false,
  min_token: 0.5, max_token: 4096, ai_context_rounds: 0, ai_reply_mode: 'standard',
  /* GCP-AI 输入框的润色按钮开关（默认开；关掉后按钮消失，见 index.html .ai-polish）*/
  ai_polish_enabled: true,
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
  { id: 'custom', label: '自定义（OpenAI 兼容）', base: '', models: [] },
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
const I18N = reactive({ map: {}, modules: {}, language: '简体中文', version: 0 });
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
function pickI18n(value, fallback) {
  if (value == null) return fallback || '';
  if (typeof value === 'string') return value;
  if (typeof value !== 'object') return String(value);
  const lang = uiLanguage();
  return value[lang] || value['简体中文'] || value['繁體中文'] || value['English'] || fallback || '';
}
/* 类别/标签/系统/架构的**显示译名**（匹配仍用规范中文值 —— common_language.json 的 term_*）*/
function term(value) {
  if (!value) return '';
  const hit = I18N.map['term_' + value];
  return (typeof hit === 'string' && hit) ? hit : value;
}

/* ===================== 桥（pywebview js_api） =====================*/
const bridge = {
  ready: false,
  api: null,
  _initPromise: null,

  /* ⚠️ 必须缓存这个 Promise：以前每次 tryCall 在 api 未就绪时都 new 一个 Promise
     各等 4 秒，十几次调用叠起来就是 40 多秒 —— 表现就是"窗口出来了但永远卡在启动页"。
     现在整个进程只初始化一次，后续所有调用共用同一个 Promise。*/
  init() {
    if (this.ready && this.api) return Promise.resolve(this.api);
    if (this._initPromise) return this._initPromise;
    this._initPromise = new Promise((resolve) => {
      let settled = false;
      const attach = () => {
        if (settled) return;
        settled = true;
        this.api = (window.pywebview && window.pywebview.api) || null;
        this.ready = !!this.api;
        resolve(this.api);
      };
      if (window.pywebview && window.pywebview.api) { attach(); return; }
      window.addEventListener('pywebviewready', attach, { once: true });
      /* 兜底：2 秒还没注入就放行（调用方会用 tryCall 拿到 null 并降级）*/
      setTimeout(attach, 2000);
    });
    return this._initPromise;
  },

  has(path) {
    if (!this.api) return false;
    const parts = String(path).split('.');
    let target = this.api;
    for (let i = 0; i < parts.length; i += 1) target = target && target[parts[i]];
    return typeof target === 'function';
  },

  async call(path, ...args) {
    if (!this.api) await this.init();
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

/* ===================== 后端 → 前端事件（原版 pyqtSignal 的等价物） =====================*/
window.ToolsGCP = window.ToolsGCP || {};
window.ToolsGCP._listeners = window.ToolsGCP._listeners || {};
window.ToolsGCP.on = function (name, fn) {
  (window.ToolsGCP._listeners[name] = window.ToolsGCP._listeners[name] || []).push(fn);
};
window.ToolsGCP.emit = function (name, payload) {
  (window.ToolsGCP._listeners[name] || []).forEach((fn) => {
    try { fn(payload); } catch (error) { console.error('[ToolsGCP] listener error', error); }
  });
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
    /* ---------- 基础 ---------- */
    const booting = ref(true);
    const bootText = ref('正在加载资源库…');
    /* ---------- 云端资源库加载遮罩 ----------
        */
    const resourceLoading = ref(false);
    const resourceLoadFailed = ref(false);
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
      resourceLoading.value = true;
      startLoadingDots();
      const result = await bridge.tryCall('resources.cloud_retry');
      if (result && result.ok) {
        await loadResources();
        await runQuery();
        resourceLoading.value = false;
        stopLoadingDots();
        return;
      }
      resourceLoadFailed.value = true;
      hintSwitchMirror();
    }
    /* 放弃云端、退回本地资源库（别把用户卡在遮罩里） */
    async function useLocalResources() {
      resourceLoading.value = false;
      stopLoadingDots();
      await saveSetting('resource_source', 'local');
      await loadResources();
      await runQuery();
      toast(t('resource_use_local_done', '已切换到本地资源库'), 'info');
    }
    const win = reactive({ maximized: false, fullscreen: false, minimized: false });
    const info = reactive({ app: 'ToolsGCP', version: '', channel: 'beta', python: '',
                            dataDir: '', configDir: '', resourceFile: '', language: '简体中文', args: [] });
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
    /* 后端接口缺失时的统一说明（不静默、不假装成功） */
    function needApi(path, extra) {
      toast((extra || '该功能') + '需要桌面端接口 <' + path + '>（后端尚未提供）', 'warning');
      return false;
    }

    /* ---------- 对话框（确认 / 输入 / 公告 / 更新 / 密钥列表 共用外壳） ---------- */
    const dialog = reactive({
      open: false, title: '', body: '', extra: '', notes: '', rows: null,
      input: false, inputValue: '', inputPlaceholder: '',
      /* 通用对话框支持一个下拉框（收藏夹选择用）。inputWhen = 选中哪个值时
         才显示下面的输入框（选新建收藏夹才出现名称输入）。 */
      select: null, selectValue: '', inputWhen: '',
      /* 勾选组（收藏夹导出用）。每项 {value,label,checked}；
         确认时 answer() 回传已勾选 value 数组，取消回传 null。 */
      checks: null,
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
        dialog.cancelText = options.cancelText || '取消';
        dialog.buttons = options.buttons
          || (options.cancelable === false ? [options.confirmText || '确定']
            : [options.cancelText || '取消', options.confirmText || '确定']);
        dialog.danger = !!options.danger;
        dialog.wide = !!options.wide;
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
    const isDark = computed(() => {
      void systemTick.value;
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
    const toastClass = computed(() => TOAST_POS_CLASS[settings.toast_position] || 'is-top');
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
      if (!target) return;
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
    function onDocMoreDown(event) {
      /* 卡片右键菜单：点到菜单外面任何地方都收起 */
      if (cardMenu.value && !(event.target && event.target.closest
        && event.target.closest('.card-menu'))) cardMenu.value = null;
      /* 收藏夹右键菜单（重命名/删除）：点到菜单外面任何地方都收起 */
      if (favMenu.open && !(event.target && event.target.closest
        && event.target.closest('.fav-menu'))) favMenu.open = false;
      /* 下载任务条右键菜单（复制链接/重试）：点到外面就收起 */
      if (downloadMenu.open && !(event.target && event.target.closest
        && event.target.closest('.download-menu'))) closeDownloadMenu();
      /* 清空下拉菜单：点到外面就收起 */
      if (clearMenuOpen.value && !(event.target && event.target.closest
        && event.target.closest('.dropdown-btn'))) clearMenuOpen.value = false;
      /* 需求：侧边栏模式的 AI 抽屉，点界面外任何地方都自动关闭
         （点抽屉内部 / 悬浮球本身不算"外面"） */
      if (aiOpen.value && !settings.ai_sidebar_mode) {
        const t = event.target;
        if (!(t && t.closest && (t.closest('.ai-drawer') || t.closest('.float-ball')))) {
          aiOpen.value = false;
        }
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
      if (page.value === 'settings' && key !== 'settings' && apiKeyDirty()) {
        openDialog({ title: t('api_unsaved_title', '还有修改没有保存'),
          body: t('api_unsaved_body', '服务商 / 模型名称 / 接口地址 / API Key 有改动还没保存。\n选择「保存并继续」先存下来，或「放弃修改」丢掉这次的改动；点「留在当前界面」则停在原处不动。'),
          buttons: [t('discard', '放弃修改'), t('stay', '留在当前界面'), t('save_continue', '保存并继续')] })
          .then((value) => {
            if (value === t('stay', '留在当前界面')) return;
            if (value === t('save_continue', '保存并继续')) saveApiKey().then(() => doGoto(key));
            else { apiKeyDraft.value = ''; doGoto(key); }
          });
        return;
      }
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
    function findPageScroller(pageKey) {
      if (!pageKey) return null;
      const list = document.querySelectorAll('[data-scroll-key]');
      for (let i = 0; i < list.length; i += 1) {
        const el = list[i];
        if (el.getAttribute('data-scroll-key') === pageKey) return el;
      }
      return null;
    }
    function rememberPageScroll(pageKey) {
      const el = findPageScroller(pageKey);
      if (el) pageScrollMemory[pageKey] = el.scrollTop;
    }
    function restorePageScroll(pageKey, attempt = 0) {
      const key = pageKey;
      const want = Number(pageScrollMemory[key] || 0);
      const el = findPageScroller(key);
      if (!el) {
        /* 页面还在过渡中（out-in 的 enter 尚未挂载）→ 下一帧再试 */
        if (attempt < 12) requestAnimationFrame(() => restorePageScroll(key, attempt + 1));
        return;
      }
      if (key === 'search') {
        measureViewport();
        scrollTop.value = want;             /* 虚拟列表按目标位置先算出要渲染的行 */
      }
      if (el.scrollTop !== want) el.scrollTop = want;
      if (key === 'search') scrollTop.value = el.scrollTop;
      /* 内容高度可能晚一两帧才稳定（虚拟列表 / 图片 / 筛选面板），继续追几帧 */
      if (el.scrollTop !== want && attempt < 12) {
        requestAnimationFrame(() => restorePageScroll(key, attempt + 1));
      }
    }
    /* 页面 transition 真正结束（新页面已挂载）后由模板 @after-enter 调进来 */
    function onPageAfterEnter() {
      restorePageScroll(page.value);
      if (page.value === 'search') measureViewport();
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
    /* 窗口边缘热区 → 系统原生缩放（见 index.html .win-resize 的说明）
       —— 内容和标题栏拖动同一套：ReleaseCapture + WM_NCLBUTTONDOWN，
          后端只负责投递请求，缩放由系统的模态循环完成。 */
    async function startResize(direction) {
      const result = await bridge.tryCall('window.start_resize', String(direction || ''));
      if (!result) needApi('window.start_resize', t('resize_window', '调整窗口大小'));
      else if (!result.ok) {
        toast(t('resize_failed', '缩放窗口失败：') + (result.error || ''), 'error');
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
    function onTitleDown(event) {
      if (event.button !== 0 || interactive(event.target)) return;
      bridge.call('window.start_drag').then((result) => {
        if (!result || !result.ok || result.started === false) fallbackDrag();
      }).catch(() => fallbackDrag());
    }
    /* 兜底：原生通道确实不可用（hwnd 拿不到 / 后端未就绪）时，用增量让后端搬窗口，
       而不是改 DOM —— 改 DOM 只会让内容位移、窗口根本不动。 */
    function fallbackDrag() {
      let lastX = window.screenX || 0, lastY = window.screenY || 0;
      let busy = false;
      const move = (e) => {
        const x = e.screenX || 0, y = e.screenY || 0;
        const dx = x - lastX, dy = y - lastY;
        if (!dx && !dy) return;
        lastX = x; lastY = y;
        if (busy) return;
        busy = true;
        Promise.resolve(bridge.tryCall('window.drag_delta', dx, dy))
          .finally(() => { busy = false; });
      };
      const up = () => {
        window.removeEventListener('mousemove', move);
        window.removeEventListener('mouseup', up);
      };
      window.addEventListener('mousemove', move);
      window.addEventListener('mouseup', up);
    }
    function onTitleDouble(event) { if (!interactive(event.target)) maximizeWindow(); }

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
        icon: iconName ? (/^https?:/i.test(String(raw.icon)) ? String(raw.icon)
          : '/res/image/icon/' + encodeURIComponent(iconName)) : '',
        url: raw.url || '', github: raw.github || '', download_url: raw.download_url || '',
        /* 下载**页面**的网址（用户填的下载地址= 下载页的网页地址，
           和 download_url（安装包直链）是两种语义）。 */
        download_page_url: raw.download_page_url || '',
        author_url: raw.author_url || '', chat_url: raw.chat_url || '',
        listed_at: raw.listed_at || '',
        systems: Array.isArray(raw.systems) ? raw.systems : (raw.systems ? [raw.systems] : []),
        architectures: Array.isArray(raw.architectures) ? raw.architectures
          : (raw.architectures ? [raw.architectures] : []),
        variants: Array.isArray(raw.variants) ? raw.variants : [],
        default_variant: raw.default_variant || '',
        _fav: false, _sel: false,
      };
    }

    async function loadSettings() {
      const result = await bridge.tryCall('settings.get');
      if (result && result.ok && result.settings) Object.assign(settings, result.settings);
      /* 旧配置里 search_source / download_source 可能是空串（历史默认值就是空），
         空串会让下拉框显示空白 —— 需求：默认选中 Github。 */
      if (!String(settings.search_source || '').trim()) settings.search_source = 'Github';
      if (!String(settings.download_source || '').trim()) settings.download_source = 'Github';
      applyAppearance();
    }
    async function loadResources() {
      loading.value = true;
      loadError.value = '';
      resetIconRetries();                    // 资源库重载 → 图标重试次数清零，重新给一次机会
      const result = await bridge.tryCall('resources.all');
      if (result && result.ok && Array.isArray(result.items)) items.value = result.items.map(mapItem);
      else {
        loadError.value = (result && result.error)
          || (bridge.ready ? '资源库读取失败' : '桌面端接口未就绪（resources.all）');
        items.value = [];
      }
      const status = await bridge.tryCall('resources.status');
      if (status && status.ok && status.source) info.resourceFile = status.source;
      loading.value = false;
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
      const result = await bridge.tryCall('favorites.list');
      if (!result || !result.ok) return false;
      folders.value = (result.folders || []).map((f) => ({ ...f, label: f.label || f.name }));
      syncFavoriteState();
      /* 收藏数据是**异步**回来的 → 网格可能在这之后才出现。
         这时补一次量（否则首帧宽度用的是兜底值，要等"更新下这页"才准）。
         ⚠️ measureFavGrid 在页面不在收藏页时是空操作（favGrid.value 为 null）。 */
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
                               updated: [], system: [], arch: [] });
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
    const filterRows = computed(() => {
      const all = { value: '', label: t('filter_all', '全部') };
      const remote = remoteOptions.value;
      const cats = [];
      const tags = new Set();
      items.value.forEach((it) => {
        it.category.forEach((c) => { if (cats.indexOf(c) < 0) cats.push(c); });
        it.category.concat(it.tags || []).forEach((k) => tags.add(k));
      });
      const ordered = CATEGORY_ORDER.filter((c) => cats.indexOf(c) >= 0)
        .concat(cats.filter((c) => CATEGORY_ORDER.indexOf(c) < 0));
      const list = (values) => [all].concat(values.map((v) => ({ value: v, label: term(v) })));
      const fromRemote = (key, fallbackList) => {
        if (remote && Array.isArray(remote[key]) && remote[key].length) {
          return [all].concat(remote[key].map((o) => ({ value: o.value, label: o.label || term(o.value) })));
        }
        return fallbackList;
      };
      return [
        { key: 'category', label: t('filter_category', '类别'),
          options: fromRemote('category', list(ordered)) },
        { key: 'tag', label: t('filter_tag', '标签'), options: fromRemote('tag', list(Array.from(tags).sort())) },
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
        { key: 'arch', label: t('filter_arch', 'CPU 架构'), options: fromRemote('arch', list(ARCHITECTURES)) },
      ];
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
      return item.category.concat(item.tags || [])
        .some((k) => String(k).toLowerCase().indexOf(key) >= 0);
    }
    function passesFilters(item, state) {
      const f = state || filters;
      if (f.category.length && !item.category.some((c) => f.category.indexOf(c) >= 0)) return false;
      if (f.tag.length) {
        const keys = item.category.concat(item.tags || []);
        if (!f.tag.some((v) => keys.indexOf(v) >= 0)) return false;
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
      if (f.arch.length) {
        if (!item.architectures.length) return false;
        const values = item.architectures.map((v) => String(v).toLowerCase());
        if (!f.arch.some((v) => values.indexOf(String(v).toLowerCase()) >= 0)) return false;
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
    const rowModel = computed(() => {
      const cols = Math.max(1, layout.value.columns || 1);
      const rowH = cardPx.value.height;
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
          rows.push({ type: 'items', key: 'r' + (seed++), items: list.slice(i, i + cols),
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
      const top = Math.max(0, scrollTop.value);
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
      rafId = requestAnimationFrame(() => { rafId = 0; scrollTop.value = el.scrollTop; });
    }
    function measureViewport() {
      const el = searchScroll.value;
      if (!el) return;
      viewH.value = el.clientHeight;
      viewW.value = el.clientWidth;
      panelHeight();
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
    /* ---------- 卡片标签：放不下时把最后一个换成「+X」 ----------
       需求（原话）："比如 OBS 他多个标签都放不下了会挤压右侧的按钮，所以可以自动识别
       实例间计算后把最后一个标签改为 X+"。这里在**渲染前**用估算宽度做布局计算：
       tag 宽度 = 文字宽 + 左右 padding 20px（.tag padding 0 10px、字号 11.5）。
       中文按 11.5px/字、西文按 6.2px/字估宽（与 CSS 实测基本吻合，留一点余量）。
       空间不够时保留「+X」胶囊，X = 被隐藏的标签数量。 */
    const TAG_FONT = 11.5, TAG_PAD = 20, TAG_GAP = 6, PLUS_TAG_W = 40;
    function tagTextWidth(text) {
      let width = 0;
      for (const ch of String(text || '')) width += (/[\u2E80-\uFFFF]/.test(ch) ? TAG_FONT : TAG_FONT * 0.54);
      return width;
    }
    function tagWidth(tag) { return tagTextWidth(term(tag)) + TAG_PAD; }
    function tagListOf(item) {
      return item.category.concat((item.tags || []).filter((v) => item.category.indexOf(v) < 0));
    }
    function tagLayout(item, avail) {
      const all = tagListOf(item);
      /* 没给可用宽度（收藏页/定制页的自适应卡片）就退回原来的固定条数，不显示 +X */
      if (!avail || avail <= 0) {
        const fixed = all.slice(0, viewMode.value === 'grid' ? 2 : 4);
        return { shown: fixed, hidden: 0 };
      }
      const shown = [];
      let used = 0;
      for (let i = 0; i < all.length; i += 1) {
        const need = tagWidth(all[i]) + (shown.length ? TAG_GAP : 0);
        const remaining = all.length - (shown.length + 1);
        const reserve = remaining > 0 ? (PLUS_TAG_W + TAG_GAP) : 0;
        if (used + need + reserve > avail) break;
        used += need;
        shown.push(all[i]);
      }
      return { shown, hidden: all.length - shown.length };
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
    /* 重试时给 URL 加时间戳：不然浏览器会直接用缓存里的 404/失败结果 */
    function iconSrc(item) {
      const base = String((item && item.icon) || '');
      const state = item && iconRetry[item.code];
      if (!state || !state.tick) return base;
      return base + (base.indexOf('?') >= 0 ? '&' : '?') + 'r=' + state.n + '&t=' + state.tick;
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
      else toast(result.error || '收藏失败', 'error');
    }
    /* 打开外链。
       ⚠️ **普通点击 = 前台打开**（浏览器跳到前台，ToolsGCP 不要再抢回来）——
          之前后端无条件在三拍（150/400/800ms）后把窗口抢回前台，
          于是用户点了链接 → 浏览器跳出来 → 一瞬间又闪回 ToolsGCP（用户投诉的 bug）。
       ⚠️ **Ctrl + 点击 = 后台打开**（浏览器在后台开，ToolsGCP 保持在前台）——
          对齐原版 py 的 url_open.open_url（按着 Ctrl 才后台打开 + 抢回前台）。
       ⚠️ event 可能没有（某些调用点不传），这时按普通点击处理。 */
    async function openLink(url, event) {
      if (!isHttp(url)) { toast(t('link_empty', '这个链接是空的'), 'info'); return; }
      const ctrl = !!(event && event.ctrlKey);
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
    /* 测 Ping：走桌面端 `shell.ping` 做**真实**网络测量
       （DNS 解析 / TCP 握手 / https 的 TLS 握手），不再拿本地图标文件自测。
       没有可用地址时明确报错，不假装成功。 */
    async function cardMenuPing() {
      const item = cardMenuItem();
      closeCardMenu();
      if (!item) return;
      const url = item.url || item.github || item.download_url || '';
      if (!url) {
        toast(t('ping_no_target', '「{name}」没有可测的网站或仓库地址').replace('{name}', item.name), 'info');
        return;
      }
      toast(t('ping_running', '正在测 Ping：{name} …').replace('{name}', item.name), 'info');
      const result = await bridge.tryCall('shell.ping', url);
      if (!result) { needApi('shell.ping', '测 Ping'); return; }
      if (!result.ok) {
        toast(t('ping_failed', '测 Ping 失败：{msg}').replace('{msg}', result.error || url), 'error');
        return;
      }
      const level = result.total_ms < 200 ? 'success' : (result.total_ms < 600 ? 'info' : 'warning');
      /* 需求：不同项**各占一行**，不要挤成一行；提示再延长 3 秒（3s → 6s） */
      const lines = [
        t('ping_result', '测 Ping：{name} — {total} ms')
          .replace('{name}', item.name)
          .replace('{total}', result.total_ms),
        'DNS   ' + result.dns_ms + ' ms',
        'TCP   ' + result.tcp_ms + ' ms',
      ];
      if (result.tls_ms != null) lines.push('TLS   ' + result.tls_ms + ' ms');
      const text = lines.join(String.fromCharCode(10));
      toast(text, level, '', { copy: text, duration: 6000, pre: true });
    }
    function enterCardMenuKey(event) {
      if (event.key === 'Escape') closeCardMenu();
    }
    function mentionAi(item) {
      if (!settings.ai_enabled) { toast(t('ai_disabled', 'GCP-AI 还没有开启，可在设置里打开。'), 'info'); return; }
      if (!item || !item.code) return;
      /* 先把 AI 界面切出来（侧栏页或悬浮抽屉），再等一帧让 rich-ai-input 挂载，
         然后让它插入 token（蓝字下划线 + 可点击跳详情的那一段，而不是普通字符串）。 */
      if (settings.ai_sidebar_mode) doGoto('ai'); else aiOpen.value = true;
      const payload = {
        name: item.name || '',
        code: item.code || '',
        text: '@' + (item.name || '') + '(' + (item.code || '') + ')',
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
      const scroller = findPageScroller(page.value);
      if (scroller) {
        detailScrollMemory = scroller.scrollTop;
        pageScrollMemory[page.value] = detailScrollMemory;
      } else {
        detailScrollMemory = Number(pageScrollMemory[page.value] || 0);
      }
      /* 记下"这个详情是从哪个页面打开的" —— 切走再切回时要能回到这个详情。 */
      detailPage.value = page.value;
      detail.value = { ...item };
      activeVariant.value = item.default_variant || '';
      const result = await bridge.tryCall('resources.detail', item.code);
      if (sequence !== detailSequence || !detail.value) return;
      if (result && result.ok && result.item) {
        const merged = mapItem(result.item);
        merged._fav = item._fav;
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
        const el = findPageScroller(page.value);
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
      return (it.category || []).concat((it.tags || []).filter((v) => (it.category || []).indexOf(v) < 0));
    });
    const introParagraphs = computed(() => {
      const it = detail.value || {};
      const text = it.intro || it.description || '';
      return String(text).split(/\n{2,}/).map((v) => v.trim()).filter(Boolean);
    });
    const detailRows = computed(() => {
      const it = detail.value || {};
      const rows = [
        { label: t('row_systems', '适用系统'), value: (it.systems || []).map(term).join('、') },
        { label: t('row_architectures', 'CPU 架构'), value: (it.architectures || []).map(term).join('、') },
        { label: t('row_category', '类别'), value: (it.category || []).map(term).join('、') },
        { label: t('row_listed_at', '上架时间'), value: String(it.listed_at || '').slice(0, 16) },
      ];
      if (isHttp(it.url)) rows.push({ label: t('row_url', '官网'), value: it.url, link: true });
      if (isHttp(it.github)) rows.push({ label: t('row_github', 'GitHub'), value: it.github, link: true });
      /* 下载**页面**的网址（和 download_url 直链是两种语义） */
      if (isHttp(it.download_page_url)) {
        rows.push({ label: t('row_download_page', '下载地址'), value: it.download_page_url, link: true });
      }
      return rows.filter((row, index) => index < 4 || row.value);   // 全空 → 整块不显示
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
    const favGrid = ref(null);
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
      const avail = Math.max(0, favGridWidth.value);
      const spacing = TILE.spacing;
      if (avail <= 0 || !favItems.value.length) {
        return { columns: 3, itemW: TILE.minW, gap: spacing };
      }
      let columns = Math.max(1, Math.floor((avail + spacing) / (TILE.minW + spacing)));
      const cap = Math.max(TILE.base, Math.ceil(avail / TILE.maxCardW));
      columns = Math.max(1, Math.min(columns, cap));
      const usable = avail - spacing * (columns - 1);
      const itemW = Math.floor(usable / columns);
      // 余数摊给**间距**：等宽 + 左右留白相等（和搜索页 layout 完全一致）
      const remainder = usable - itemW * columns;
      const gap = columns > 1 ? spacing + remainder / (columns - 1) : spacing;
      return { columns, itemW, gap };
    });
    /* 量一次收藏页网格的可用宽度（用来算列数）。
       ⚠️ 量不到时**不写 0** —— 保留旧值，让 favLayout 继续用上一次正确的列数。 */
    function measureFavGrid() {
      const el = favGrid.value;
      if (!el) return;                       // 页面还没挂载 → 保留旧值
      /* 用 parentElement 的 clientWidth 减去自身 padding = 真正能放卡片的宽度 */
      const parent = el.parentElement;
      const style = el.ownerDocument.defaultView.getComputedStyle(el);
      const paddingX = parseFloat(style.paddingLeft || '0') + parseFloat(style.paddingRight || '0');
      const width = (parent ? parent.clientWidth : el.clientWidth) - paddingX;
      /* ⚠️ 量到 0（容器还没布局好）也保留旧值 */
      if (width > 0) favGridWidth.value = Math.round(width);
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
      } else toast(result.error || '移动失败', 'error');
    }
    async function createFolder() {
      const name = await openDialog({ title: t('new_folder', '新建收藏夹'), input: true,
        placeholder: t('new_folder', '新建收藏夹') });
      if (!name) return;
      const result = await bridge.tryCall('favorites.create_folder', name);
      if (!result) return needApi('favorites.create_folder', '新建收藏夹');
      if (result.ok && result.created) { await loadFavorites(); toast(t('folder_created', '已新建收藏夹'), 'success'); }
      else toast((result.message || result.error) || '创建失败', 'error');
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
      } else toast((result.message || result.error) || '重命名失败', 'error');
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
      } else toast((result.message || result.error) || '删除失败', 'error');
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
          .replace('{err}', result.error || '保存失败'), 'error');
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
          if (!created.ok) { toast(created.error || '新建收藏夹失败', 'error'); return; }
          if (!created.created) {
            remembered = NEW_FOLDER_VALUE;
            /* 后端失败提示可能是"语言键"（如 default_folder_reserved），也可能是一句中文；
               语言键能查到就翻译，查不到原样显示（绝不吞掉原因）。 */
            const reason = String(created.message || '');
            const text = /^[a-z][a-z0-9_]*$/.test(reason) ? t(reason, reason) : reason;
            toast(text || '新建收藏夹失败', 'error');
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
      items.value.forEach((it) => {
        it.category.forEach((v) => counter.set(v, (counter.get(v) || 0) + 1));
        (it.tags || []).forEach((v) => { if (it.category.indexOf(v) < 0) counter.set(v, (counter.get(v) || 0) + 1); });
      });
      return Array.from(counter.entries())
        .filter(([, count]) => count >= 2)
        .map(([name, count]) => ({ name, count,
          kind: items.value.some((it) => it.category.indexOf(name) >= 0) ? 'category' : 'tag' }))
        .sort((a, b) => (b.count - a.count) || a.name.localeCompare(b.name))
        .slice(0, 20);
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
      /* ⚠️ 不再强制"至少选一个"：页面副标题写的就是"不想选也可以直接保存"，
         原版也允许空喜好保存（推荐页会显示空状态，可再点「去设置喜好」回来挑）。
         之前这里弹"请至少选择一个喜好"，和自家 UI 文案自相矛盾。 */
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
                                     updated: [], system: [], arch: [] });
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
        it.category.forEach((c) => { if (picked.has(c)) score += 3; });
        (it.tags || []).forEach((v) => { if (picked.has(v)) score += 1; });
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
      } else if (mode === 'fav') {
        /* 已收藏优先（组内仍按匹配分） */
        scored.sort((a, b) => (Number(!!b._fav) - Number(!!a._fav)) || (b._score - a._score));
      } else if (mode === 'unfav') {
        /* 未收藏优先 */
        scored.sort((a, b) => (Number(!!a._fav) - Number(!!b._fav)) || (b._score - a._score));
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
        return {
          id: issue.id || issue.number, number: issue.number,
          title: String(issue.title || '').trim(),
          body: stripMarkdown(issue.body || '').slice(0, 2000),
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
    function openNotice(notice) { markRead(noticeKey(notice)); openLink(notice.url); }
    /* 公告弹窗：⚠️ 隐私弹窗开着的时候不许弹（它俩都是遮罩式，叠一起很难看） */
    let noticePopped = false;
    function maybePopup() {
      if (noticePopped || !unread.value.length) return;
      if (privacy.open) return;                       // 隐私政策没同意 → 公告让路
      const newest = unread.value[0];
      noticePopped = true;
      openDialog({
        title: t('notice_dialog_title', '新公告'),
        body: newest.title,
        notes: newest.body,
        extra: (unread.value.length > 1
          ? t('notice_dialog_more', '还有 {n} 条未读公告，请到公告页查看。').replace('{n}', unread.value.length - 1) + '\n' : '')
          + t('notice_dialog_read_tip', '点「全部已读」后，左侧栏的未读数字会清零。'),
        buttons: [t('notice_later', '稍后'), t('mark_all_read', '全部已读'), t('notice_view', '查看公告')],
        wide: true,
        /* 给公告的弹窗点击旁边空白处改为无反应 不要让窗口关掉。
           只影响这一个弹窗；其它对话框点空白仍然是取消。 */
        backdropClose: false,
      }).then((value) => {
        if (value === t('notice_view', '查看公告')) { doGoto('notice'); markRead(noticeKey(newest)); }
        else if (value === t('mark_all_read', '全部已读')) markAllRead();
      });
    }

    /* ---------- Github / 反馈 ---------- */
    const lightbox = ref('');
    const sponsorImage = '/res/image/' + encodeURIComponent('微信Galen563的ToolsGCP项目赞助.jpg');
    const feedbackUrl = 'https://github.com/Galen563/ToolsGCP/issues';
    const introLines = ['免费开源工具集合', '集中收录常用软件与网站', '支持按类别 / 标签 / 系统筛选',
      '可收藏、批量部署常用环境', '提供资源获取等功能'];
    const qqGroups = [
      { label: '改进建议群', number: '312751713',
        image: '/res/image/qq/' + encodeURIComponent('ToolsGCP-改进建议群.jpg') },
      { label: '投诉举报群', number: '973961899',
        image: '/res/image/qq/' + encodeURIComponent('ToolsGCP-投诉举报群.jpg') },
    ];

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
    /* 删除无二次确认（原版 delete 直接 pop + 存盘 + 刷新） */
    function removeDeployRow(row) {
      const target = activeListRef();
      target.value = target.value.filter((r) => r !== row);
      saveActiveList();
    }
    /* 部署页双击清单行 → 打开该资源的详情页。详情段已把 v-if 扩到 page==='deploy'。 */
    function openDeployDetail(row) {
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
          .replace('{err}', result.error || '保存失败'),
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
      const result = await bridge.tryCall('downloader.start', target.url, row.name, downloadDir.value);
      deployIndeterminate.value = false;
      if (result && result.ok) {
        setRowStatus(row, ST_DONE);
        deployStatusText.value = '';
        return true;
      }
      /* ⚠️ 桌面端没有下载接口（downloader.start）时退化为打开页面，绝不假装下载成功 */
      await openLink(target.url, null);
      setRowStatus(row, ST_OPENED);
      deployStatusText.value = '';
      if (!result) {
        toast(t('downloader_not_ready', '下载接口 <downloader.start> 未就绪，已改为打开页面'), 'warning', t('tip_warning', '提示', 'deploy'));
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
    /* 单条部署（:877-887）：kind 不是 direct/github 时退化成打开官网 */
    async function deployOne(row) {
      const kind = previewKindOf(row);
      if (kind === 'direct' || kind === 'github') { await startDownload(row); return; }
      const target = downloadTarget(row);
      if (target.kind === 'unknown') { setRowStatus(row, ST_FAILED + ': ' + target.error); return; }
      await openPageSingle(row);
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
        body: t('confirm_deploy_body', '将处理清单里的 {n} 个程序：\n· 能从 GitHub / 直链拿到安装包的会自动下载\n· 只能拿到官网的会帮你打开下载页面\n（开始前会让你选一个下载目录）', 'deploy')
          .replace('{n}', deployList.value.length),
        confirmText: t('start', '开始', 'deploy'), cancelText: t('cancel', '取消', 'deploy') });
      if (!yes) return;
      await ensureDownloadDir();
      deployRunning.value = true;
      deployIndeterminate.value = false;
      deployProgress.value = 0;
      let done = 0, opened = 0, failed = 0;
      for (let i = 0; i < deployList.value.length; i += 1) {
        const row = deployList.value[i];
        deployProgress.value = Math.round((i / deployList.value.length) * 100);
        deployStatusText.value = '正在处理: ' + row.name;
        const kind = previewKindOf(row);
        if (kind === 'direct' || kind === 'github') {
          await startDownload(row);
        } else {
          const target = downloadTarget(row);
          if (target.kind === 'unknown') setRowStatus(row, ST_FAILED + ': ' + target.error);
          else await openPageSingle(row);
          /* 只拿到官网的停 1200ms 再下一条，避免一次开几十个标签页（:1002-1004） */
          await new Promise((resolve) => setTimeout(resolve, 1200));
        }
        const value = String(row.status || '');
        if (value === ST_DONE) done += 1;
        else if (value === ST_OPENED) opened += 1;
        else if (value.indexOf(ST_FAILED) === 0) failed += 1;
        deployIndeterminate.value = false;
        saveDeployList();
      }
      deployProgress.value = 100;
      deployStatusText.value = '';
      deployIndeterminate.value = false;
      deployRunning.value = false;
      toast(t('batch_done_summary', '自动下载完成 {done} 个，已打开官网 {opened} 个，失败 {failed} 个', 'deploy')
        .replace('{done}', done).replace('{opened}', opened).replace('{failed}', failed),
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
          /* 开关状态同样走 settingOn()，旧配置字符串 "false" 不会再把卡片显示成"已启用" */
          const enabled = settingKey ? settingOn(settings[settingKey]) : !manifest.default_disabled;
          results.push({
            id: manifest.id || id, name: pickI18n(manifest.name, id),
            description: pickI18n(manifest.description, ''), author: manifest.author || '',
            version: manifest.version || '', builtin: !!manifest.builtin,
            protected: !!manifest.builtin, enabled_setting: settingKey, enabled,
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
      if (!plugin.enabled_setting) { toast(t('no_switch', '这个插件没有提供开关配置'), 'info'); return; }
      const next = !plugin.enabled;
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
      toast(t('note_saved', '备注已保存：{note}').replace('{note}', note || '（空）'), 'info');
    }
    function cancelNote(plugin) { plugin.editingNote = false; }
    async function deletePlugin(plugin) {
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
      } else toast(result.error || '删除失败', 'error');
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
    /* SYSTEMS / ARCHITECTURES：resource_schema.py:22 / :27 */
    const makerPlatforms = ['全平台', 'Windows', 'macOS', 'Android', 'iOS', 'Linux', 'web', '其他'];
    const makerArchs = ['x64', 'x86', 'arm64', 'arm', 'Apple Silicon', '其他'];
    /* REPO_PLATFORMS：resource_maker_core.py:41-48（顺序即下拉顺序） */
    const REPO_PLATFORMS = [
      { key: 'github', label: 'GitHub', prefix: 'https://github.com/' },
      { key: 'gitcode', label: 'GitCode', prefix: 'https://gitcode.com/' },
      { key: 'gitee', label: 'Gitee', prefix: 'https://gitee.com/' },
      { key: 'gitlab', label: 'GitLab', prefix: 'https://gitlab.com/' },
      { key: 'custom', label: '自定义', prefix: '' },
      { key: 'none', label: '不开源', prefix: '' },
    ];
    const repoPlatformOptions = REPO_PLATFORMS.map((p) => ({ value: p.key, label: p.label }));
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
      name: '', id: '', code: '', category: makerCategories[0],
      systems: [], architectures: [],
      icon: '', iconName: '', iconSource: '', iconPicked: false, iconExt: '',
      tags: makerCategories[0], _tagsAuto: true,
      url: '', repoPlatform: 'github', github: '', author_url: '', chat_url: '',
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
    /* 可编辑 combo 的选项（31 项，顺序与 py CATEGORIES 完全一致；label 走 term() 做语言映射）。
       允许自定义输入由 <combo editable> 负责，不再用原生 datalist。
       内容核对过 py（resource_maker_core.py:26-32 的 CATEGORIES 就是这 31 项、这个顺序），
            所以这里**不许**增删/重排；用户看到的"内容缺少"是弹层只露 9 项 + 输入框显示规范中文
            （英文界面里和列表项对不上），见下面 makerCategoryText + Combo 的 maxHeight/滚动修正。 */
    const makerCategoryOptions = computed(() => makerCategories.map((c) => ({ value: c, label: term(c) })));
    /* 类别输入框里显示的文本 = 规范值的**当前语言译名**（对齐 py：下拉显示译名、落盘存规范值）。
       ⚠️ 必须 void I18N.version 才能跟着语言切换重新计算（term() 读的是非响应式的 I18N.map）。 */
    const makerCategoryText = computed(() => {
      void I18N.version;
      return splitList(maker.category).map((c) => term(c)).join(', ');
    });
    /* 把界面上的译名（"Tools" / "工具"）还原成库里的规范值（"工具"）；
       认不出来的自定义值原样返回（对齐 py 的 _canonical_term）。 */
    function canonicalTerm(text) {
      void I18N.version;
      const value = String(text == null ? '' : text).trim();
      if (!value) return '';
      if (makerCategories.indexOf(value) >= 0) return value;
      const hit = makerCategories.find((c) => term(c) === value);
      return hit || value;
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
      + t('library_tooltip', '资源库固定是程序目录下的 .ToolsGCP/ToolsGCP-Resources.json，制作器不会另外生成一份；\n每次写盘前会自动备份到同级 backups/ 目录，只保留最近 20 份。', 'maker'));
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
      const def = REPO_PLATFORMS.find((p) => p.key === platform);
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
      const hit = REPO_PLATFORMS.find((p) => p.prefix && value.indexOf(p.prefix) === 0);
      return hit ? hit.key : 'custom';
    }
    const repoPrefix = computed(() => {
      const def = REPO_PLATFORMS.find((p) => p.key === maker.repoPlatform);
      return def ? def.prefix : '';
    });
    const repoPlaceholder = computed(() => {
      const key = maker.repoPlatform;
      if (key === 'none') return '已选择「不开源」';
      if (key === 'custom') return 'https://你的仓库地址';
      return 'owner/repo';
    });
    const repoPreviewText = computed(() => {
      const url = normalizeRepoUrl(maker.repoPlatform, maker.github);
      return url ? '→ ' + url : '';
    });
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
      if (want && want !== maker.iconName) maker.iconName = want;
    }
    function setI18nLang(index) { i18nLangIndex.value = index; }
    function refreshPreview() { /* 预览/状态行都是 computed，改动即刷新 */ }
    function toggleChip(list, value) {
      const index = list.indexOf(value);
      if (index >= 0) list.splice(index, 1); else list.push(value);
      refreshPreview();
    }

    /* 联动规则（:1414-1450）：名称 → id 与图标改名（防抖 800ms） */
    function onNameChanged() {
      const slug = slugify(maker.name).slice(0, 40);
      if (!maker._loading) maker.id = slug;
      clearTimeout(iconRenameTimer);
      iconRenameTimer = setTimeout(flushNameIconRename, 800);   // 防抖 800ms 才改名
      refreshPreview();
    }
    function onIdChanged() { flushNameIconRename(); refreshPreview(); }
    /* 类别改成可编辑 combo（py EditableComboBox）。combo 通过 change 事件把新值抛进来，
       这里负责写回 maker.category；标签仍是"自动跟随时才跟着变"。 */
    function onCategoryChanged(value) {
      if (value !== undefined) maker.category = value;
      if (maker._tagsAuto) maker.tags = maker.category;
      refreshPreview();
    }
    function onTagsEdited() { maker._tagsAuto = false; refreshPreview(); }
    function restoreTagsFollow() {
      maker._tagsAuto = true;
      maker.tags = maker.category;
      refreshPreview();
    }
    function onRepoPlatformChanged(value) {
      maker.repoPlatform = value;
      refreshPreview();
    }

    /* 实时预览（update_preview，:396-414）：不显示 intro/supplement/systems/url/github */
    const previewName = computed(() => String(maker.name || '').trim() || t('preview_name', '（名称）', 'maker'));
    const previewDesc = computed(() => {
      const text = String(maker.i18n['简体中文'].description || '').trim() || t('preview_desc', '（简介）', 'maker');
      return text.length > 60 ? text.slice(0, 60) + '...' : text;
    });
    const previewTagList = computed(() => splitList(maker.tags).map((tag) => '[' + tag + ']'));
    /* 有文件且不是 .gif → 显示图片；否则显示「?」 */
    const previewIcon = computed(() => ((maker.iconSource && !/\.gif$/i.test(maker.iconExt || ''))
      ? maker.iconSource : ''));

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
      if (maker.iconSource && !maker.iconName) {
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
      if (!maker.iconName) out.push(t('还没导入图片，卡片上会显示成默认图标', '还没导入图片，卡片上会显示成默认图标', 'maker'));
      const url = String(maker.url || '').trim();
      if (!url) out.push(t('「官网」留空了，卡片上会没有「官网」按钮', '「官网」留空了，卡片上会没有「官网」按钮', 'maker'));
      else if (!/^https?:\/\//i.test(url)) {
        out.push(t('「官网」没写 http://，已按 https:// 处理', '「官网」没写 http://，已按 https:// 处理', 'maker'));
      }
      if (!String(maker.i18n['简体中文'].description || '').trim()) {
        out.push(t('「简介」留空了，卡片上只有名称', '「简介」留空了，卡片上只有名称', 'maker'));
      }
      if (!String(maker.category || '').trim()) {
        out.push(t('「类别」留空了，这条不会出现在类别分组里', '「类别」留空了，这条不会出现在类别分组里', 'maker'));
      }
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
      const platform = maker.repoPlatform;
      if (platform !== 'none' && platform !== 'custom' && !normalizeRepoUrl(platform, maker.github)) {
        out.push(t('「开源仓库」留空了，卡片上会没有仓库按钮', '「开源仓库」留空了，卡片上会没有仓库按钮', 'maker'));
      }
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
    const MAKER_FIELD_ORDER = ['id', 'code', 'name', 'category', 'tags', 'icon', 'url', 'github',
      'download_url', 'chat_url', 'author_url', 'description', 'intro', 'supplement', 'listed_at',
      'systems', 'architectures', 'variants', 'default_variant'];
    function flattenText(value) { return String(value == null ? '' : value).replace(/\s*\n\s*/g, ' ').trim(); }
    function orderEntry(entry) {
      const out = {};
      MAKER_FIELD_ORDER.forEach((key) => { if (entry[key] !== undefined) out[key] = entry[key]; });
      Object.keys(entry).forEach((key) => { if (out[key] === undefined) out[key] = entry[key]; });
      return out;
    }
    /* apply_i18n_to_entry（:707-726）：全空跳过；去重后只剩 1 个 → 不写字典。
       多语言字段常开（多语言字段开关删除 我要常开而不是可关闭的），
       不再有 i18nEnabled 开关，这里无条件应用。 */
    function applyI18nToEntry(entry) {
      ['description', 'intro', 'supplement'].forEach((key) => {
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
    function buildEntry() {
      const id = String(maker.id || '').trim();
      const code = String(maker.code || '').trim();
      const entry = {};
      if (id) entry.id = id;
      if (code) entry.code = code;
      if (String(maker.name || '').trim()) entry.name = String(maker.name).trim();
      /* 类别 / 标签在界面上可能是**译名**（English 界面敲 "Tools"），落盘一律还原成
         规范值（"工具"）—— 对齐 py build_entry 的 _canonical_term（resource_maker_pages.py:1558-1564）。 */
      const category = splitList(maker.category).map(canonicalTerm).filter(Boolean);
      if (category.length) entry.category = category;
      const tags = splitList(maker.tags).map(canonicalTerm)
        .filter((tag) => tag && category.indexOf(tag) < 0);
      if (tags.length) entry.tags = tags;
      if (maker.iconName) entry.icon = maker.iconName;
      const url = autoHttpUrl(maker.url);
      if (url) entry.url = url;
      const repo = normalizeRepoUrl(maker.repoPlatform, maker.github);
      if (repo) entry.github = repo;
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
      if (maker.architectures.length) entry.architectures = maker.architectures.slice();
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
      maker.iconExt = ext;
      /* 目标文件名用编号（TG-000053.png）：同一条资源重复导入只会覆盖自己那一张，
         不会在图标目录里堆垃圾，也不会撞别人的图。 */
      const want = iconWantName();
      const result = await bridge.tryCall('maker.save_icon', want, dataUrl);
      if (result && result.ok) {
        maker.iconSource = result.url || ('/res/image/icon/' + encodeURIComponent(result.name || want));
        maker.iconName = result.name || want;
        maker.iconPicked = true;
        toast(t('image_saved_as', '已存为 {name}（{path}）', 'maker')
          .replace('{name}', maker.iconName)
          .replace('{path}', result.path || t('图标目录', '图标目录', 'maker')),
          'success', t('图片已导入', '图片已导入', 'maker'));
        return;
      }
      if (!result) {
        /* 后端还没有这个接口：图片没落盘，**绝不能**在 JSON 里写一个不存在的文件名。
           这里保留本地预览（dataURL）但清空 iconName，并明确告诉用户为什么。 */
        maker.iconSource = dataUrl;
        maker.iconName = '';
        maker.iconPicked = false;
        needApi('maker.save_icon', t('import_image', '导入图片', 'maker'));
        return;
      }
      maker.iconSource = dataUrl;
      maker.iconName = '';
      maker.iconPicked = false;
      toast(result.error || t('write_failed', '写入失败', 'maker'), 'error',
        t('image_import_failed', '图片没能存进图标目录', 'maker'));
    }

    /* 载入现有资源弹层 + loadExisting / applyLoadExisting 已删除 ——
       用户要求删掉载入到制作资源按钮后，这条路径没有任何入口（双击资源浏览一行
       已经等效：editExistingEntry → loadResourceIntoForm），留着只是死代码。 */
    function loadResourceIntoForm(raw) {
      maker._loading = true;
      maker.name = pickI18n(raw.name, '');
      maker.id = String(raw.id || '');
      maker.code = String(raw.code || maker.code);
      maker.codeAuto = false;
      /* 库里存的是规范值（工具/游戏…），表单显示译名（py load_resource 同样走 _term）：
         类别交给 makerCategoryText 统一翻译；标签是纯文本框，这里直接写译名，
         写盘时 canonicalTerm 再还原 —— 往返无损。 */
      maker.category = (Array.isArray(raw.category) ? raw.category : [raw.category]).filter(Boolean).join(', ');
      maker.tags = (Array.isArray(raw.tags) ? raw.tags : [raw.tags]).filter(Boolean)
        .map((tag) => term(tag)).join(', ');
      maker._tagsAuto = false;
      maker.systems = Array.isArray(raw.systems) ? raw.systems.slice() : [];
      maker.architectures = Array.isArray(raw.architectures) ? raw.architectures.slice() : [];
      maker.url = String(raw.url || '');
      maker.repoPlatform = detectRepoPlatform(raw.github);
      maker.github = String(raw.github || '');
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
      maker.iconPicked = false;
      /* （路线 A 的前端一半）：把多语言字段灌进三种语言。
         raw[key] 现在有两种形态：
           · 字典 {简体中文, 繁體中文, English} —— 来自 resources.detail
             （后端把磁盘上的**原始多语言字典**还回来了，见
              resource_loader.get_raw_i18n_by_code 与 desktop/api/resources.py 的 detail）；
           · 字符串 —— 列表接口那一路（mapItem 已按当前语言压平）或老后端。
         字典：按语言逐个灌满；字符串：只灌简体中文（其余两种留空串）。
         ⚠️ 两种形态都不会让 maker.i18n[lang][key] 变成 undefined。
         ⚠️ 语言键必须**精确**匹配 makerLanguages 的写法（是繁體中文不是繁体中文），
            磁盘上偶尔出现的简写繁体键在这里顺带回退一次（精确键优先）。 */
      const langTextOf = (dict, lang) => {
        if (!dict || typeof dict !== 'object') return '';
        if (dict[lang] != null) return String(dict[lang]);
        const alt = lang === '繁體中文' ? '繁体中文' : '';
        if (alt && dict[alt] != null) return String(dict[alt]);
        return '';
      };
      makerLanguages.forEach((lang) => {
        ['description', 'intro', 'supplement'].forEach((key) => {
          const value = raw[key];
          let text = '';
          if (value && typeof value === 'object' && !Array.isArray(value)) {
            text = langTextOf(value, lang);
          } else if (lang === '简体中文') {
            text = String(value == null ? '' : value);
          }
          maker.i18n[lang][key] = text;
        });
        const rawName = raw.name;
        maker.i18n[lang].name = (rawName && typeof rawName === 'object' && !Array.isArray(rawName))
          ? langTextOf(rawName, lang)
          : (lang === '简体中文' ? String(rawName == null ? '' : rawName) : '');
      });
      i18nLangIndex.value = 0;
      maker._loading = false;
      refreshPreview();
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
      toast(t('稿件已生成', '稿件已生成', 'maker') + '：' + (dirLabel || 'resource.json') + zipMsg,
        'success', t('稿件已生成', '稿件已生成', 'maker'));
    }

    /* 行为链 B：追加到本机资源库（:1748-1836）
       写盘前备份到 backups/、原子写、覆盖保留 listed_at —— 由桌面端接口负责 */
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
    }
    async function appendToLibrary() {
      if (!validateOrToast()) return;
      flushNameIconRename();
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
      /* 写盘成功后同步前端状态 + 重新拉资源库（浏览器列表/条数/预览全部刷新） */
      maker.loadedId = entry.id;
      maker.loadedName = entry.name || '';
      maker.loadedDownloadUrl = entry.download_url || maker.loadedDownloadUrl;
      maker.isNewEntry = false;
      maker.listedAt = entry.listed_at || maker.listedAt;
      maker.editingExisting = true;
      maker.editingId = String(entry.id || '');
      maker.editingCode = String(entry.code || '');
      await reloadMakerLibrary();
      const total = result.total != null ? result.total : (index >= 0 ? list.length : list.length + 1);
      const verb = result.action === 'update'
        ? t('library_updated', '已更新', 'maker') : t('library_added', '已追加', 'maker');
      toast(verb + ' ' + t('written_to_library', '{name}（{code}）→ {n} 条', 'maker')
        .replace('{name}', entry.name || entry.id)
        .replace('{code}', entry.code || '')
        .replace('{n}', total),
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
      maker.loadedId = entry.id;
      maker.loadedName = entry.name || '';
      maker.isNewEntry = false;
      maker.listedAt = entry.listed_at || maker.listedAt;
      await reloadMakerLibrary();
      toast(t('saved_to_original', '已保存回原条目：{name}（{code}）', 'maker')
        .replace('{name}', entry.name || entry.id).replace('{code}', entry.code || ''),
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
        if (fallback.canceled) return;              // 用户在「另存为」里点了取消：静默
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
      if (result.canceled) return;              // 用户在「另存为」里点了取消：静默
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
      maker.category = makerCategories[0];
      maker.tags = makerCategories[0];
      maker._tagsAuto = true;
      maker.systems = [];
      maker.architectures = [];
      maker.icon = '';
      maker.iconName = '';
      maker.iconSource = '';
      maker.iconPicked = false;
      maker.iconExt = '';
      maker.url = '';
      maker.repoPlatform = 'github';
      maker.github = '';
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
      makerLanguages.forEach((lang) => {
        ['name', 'description', 'intro', 'supplement'].forEach((key) => { maker.i18n[lang][key] = ''; });
      });
      i18nEnabled.value = true;
      i18nLangIndex.value = 0;
    }

    /* 资源浏览（BrowserPage，:1978-2781）：11 列，顺序即数组 */
    const browserQuery = ref('');
    const browserCategory = ref('');
    const browserSelected = ref('');
    const browserCategoryOptions = computed(() => [{ value: '', label: t('all_categories', '全部类别', 'maker') }]
      .concat(makerCategories.map((c) => ({ value: c, label: term(c) }))));
    const browserRows = computed(() => {
      const key = browserQuery.value.trim().toLowerCase();
      const category = browserCategory.value;
      return items.value.filter((r) => {
        if (category && (r.category || []).indexOf(category) < 0) return false;
        if (!key) return true;
        if (String(r.code).toLowerCase().indexOf(key) >= 0) return true;
        if (String(r.name).toLowerCase().indexOf(key) >= 0) return true;
        if (String(r.id).toLowerCase().indexOf(key) >= 0) return true;
        return (r.category || []).concat(r.tags || [])
          .some((item) => String(item).toLowerCase().indexOf(key) >= 0);
      }).map((r) => ({
        ...r,
        iconName: r.icon ? decodeURIComponent(String(r.icon).split('/').pop()) : '',
      }));
    });
    /* count_label 只在筛选时显示（browser_shown），不筛选时不重复页头的条数 */
    const browserCountText = computed(() => ((browserQuery.value.trim() || browserCategory.value)
      ? t('browser_shown', '筛选中 · 显示 {n} / 共 {total} 条', 'maker')
        .replace('{n}', browserRows.value.length).replace('{total}', items.value.length)
      : ''));
    function reloadLibrary() { loadResources().catch(() => {}); }
    function openLibraryFile() {
      bridge.tryCall('shell.open_path', libraryDir()).then((result) => {
        if (!result) { needApi('shell.open_path', '打开资源库文件'); return; }
        if (!result.ok) toast(t('打不开', '打不开', 'maker'), 'error', t('tip_error', '错误', 'maker'));
      });
    }
    /* 双击资源浏览里的一行 → 直接进入编辑已有资源界面。
       先拿 resources.detail 的完整数据（列表接口可能只带摘要），再灌进表单；失败就用列表那份。
       ⚠️ resources.detail 现在把 name/description/intro/supplement 以**原始三语言字典**
          返回（后端走的是"loader 保留原始副本"这条路），所以灌进表单后三种语言都有内容。
          ⚠️ 兜底（detail 接口不存在/失败）时用的是列表那份 —— 列表那一路是 mapItem 压平过的
             **字符串**，于是只有简体中文有内容（这是老后端的老行为，不是回归）。 */
    async function editExistingEntry(row) {
      if (!row) return;
      if (row.code) browserSelected.value = row.code;
      let raw = row;
      if (row.code) {
        const result = await bridge.tryCall('resources.detail', row.code);
        if (result && result.ok && result.item) {
          /* 以列表那份打底、再用 detail 覆盖：detail 缺字段时不会把列表里已有的值弄丢，
             而 detail 带回来的多语言**字典**会盖掉列表那份的单语言字符串。 */
          raw = Object.assign({}, row, result.item);
        }
      }
      loadResourceIntoForm(raw);
      activeSection.value = 'form';
      toast(t('editing_existing_tip', '正在编辑「{name}」（{code}）：产出区可用「保存到原列表」写回这一条。', 'maker')
        .replace('{name}', pickI18n(raw.name, '') || row.name || '')
        .replace('{code}', raw.code || row.code || ''),
        'info', t('edit_mode', '编辑已有资源', 'maker'));
    }
    /* 删掉载入到制作资源按钮对应的 loadSelectedIntoForm（双击已等效）。 */
    function deleteSelectedEntries() {
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
          body: t('confirm_merge_write', '将把 {n} 条新条目写入本机资源库：\n{path}\n\n（写入前会自动备份一份）', 'maker')
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
        toast(t('merged_ok', '已合并 {n} 条到资源库（已自动备份）', 'maker')
          .replace('{n}', written.added != null ? written.added : result.added)
          + (written.skipped ? t('，跳过重复 {n} 条', '，跳过重复 {n} 条', 'maker').replace('{n}', written.skipped) : ''),
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
      '类别的可选项来自内置类别表，也可以直接输入新类别；标签默认跟着类别走，',
      '手动改过标签之后就不会再自动覆盖，想恢复联动点「跟随类别」。',
      '适用系统与 CPU 架构都可以多选，留空表示还没确定。',
      '',
      '【图标】',
      '可选。导入的图片会按「名称」自动改名（保留中文），支持 png / jpg / gif / ico / webp / svg。',
      '生成给作者的稿件时，图片会按另一套规则命名（只留字母数字和 -_），',
      '两套规则不一样是原版行为。',
      '',
      '【多语言字段】',
      '默认开启。名称只是可选翻译，最终名称以「基本信息」里的为准；',
      '三种语言完全相同时不会写成字典，仍然是一个纯字符串。',
      '',
      '【产出】',
      '· 生成稿件：输出 <id>/resource.json + 说明文件（+ 图标），打包成 <id>.zip 发给作者；',
      '· 追加到本机资源库：写入前自动备份到同级 backups/，只保留最近 20 份；',
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

    /* 设置左侧栏每个板块的图标（需求：每项 text 前面加上对应图标，从外观到关于） */
    const SECTION_ICONS = {
      appearance: 'palette', animation: 'motion', startup: 'play', search: 'search',
      hotkey: 'setting', download: 'download', notification: 'megaphone',
      behavior: 'application', storage: 'folder',
      ai: 'robot', dev: 'developer', about: 'info',
    };
    function sectionIcon(key) { return SECTION_ICONS[key] || 'setting'; }

    const sections = computed(() => {
      const splashOn = !!draft.splash_screen_enabled;
      const speedOn = !!draft.download_speed_limit_enabled;
      const localSource = draft.resource_source === 'local';
      const tokenOn = !!draft.limit_token_output;
      const aiOn = !!draft.ai_enabled;
      const hotOn = !!draft.hotkey_enabled;
      const devVerified = !!(draft.dev_mode_enabled && draft.dev_mode_admin);
      const provider = AI_PROVIDERS.find((p) => p.id === draft.ai_provider) || AI_PROVIDERS[0];
      /* 模型选择下拉的选项：该服务商支持的模型 + （若手输过清单外的名字）当前值。
         保证「模型名称」里自定义的任意名字在下拉里也能显示为选中项，不会错位。 */
      const modelOptions = (provider.models || []).slice();
      const curModel = String(draft.model_name || '').trim();
      if (curModel && modelOptions.indexOf(curModel) < 0) modelOptions.push(curModel);
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
            tip: t('splash_screen_tip', '开启后，程序启动时将显示启动画面') },
          { key: 'splash_screen_duration', type: 'slider', indent: true, label: t('splash_screen_duration', '启动动画时长'),
            tip: t('splash_screen_duration_tip', '增加启动动画时长组件，是因为Python加载资源需要一点时间'),
            min: 1, max: 5, step: 1, unit: t('seconds', '秒'), visible: splashOn },
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
               settings_manager 迁移成「搜索」，所以这里不需要再留一个无效选项）。 */
            options: [{ value: '搜索', label: t('search_title', '搜索') },
              { value: '搜索', label: t('search_title', '搜索') },
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
          { key: 'download_source', type: 'select', width: 180, label: t('download_source', '下载源'),
            tip: t('github_mirror_hint', '下面的镜像站会把上面的链接原样转发一份，国内下载通常快很多。这条不通就换一条，或者直接用上面的「下载」走 GitHub 官方。'),
            options: SOURCE_OPTIONS.map((v) => ({ value: v, label: v })) },
          { key: 'update_channel', type: 'select', width: 180, label: t('update_channel', '更新下载渠道'),
            tip: t('update_channel_tip', '决定「检查更新」愿意接受哪种发布：正式版 + Beta 版（默认）、只要正式版、或只要 Beta 版。'),
            options: [{ value: 'all', label: t('update_channel_all', '下载正式版和Beta版') },
              { value: 'stable', label: t('update_channel_stable', '仅下载正式版') },
              { value: 'beta', label: t('update_channel_beta', '仅下载Beta版') }] },
          { key: 'download_speed_limit_enabled', type: 'checkbox', label: t('download_speed_limit', '下载限速'),
            statusText: speedOn ? (draft.download_speed_limit || 100) + ' MB/s' : t('unlimited', '无限制') },
          { key: 'download_speed_limit', type: 'slider', indent: true, label: t('limit_speed', '限速'),
            min: 1, max: 300, step: 1, unit: 'MB/s', visible: speedOn },
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
            { key: 'ai_polish_enabled', type: 'switch', label: t('ai_polish_enable', '输入框润色按钮'),
              tip: t('ai_polish_enable_tip', '开启后，GCP-AI 输入框最右侧（发送键左边）会出现一个 AI 小按钮，点一下把当前输入润色一遍；关闭后按钮消失。润色只改措辞，不发送、不进历史对话'),
              visible: aiOn },
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
          ],
          [
            { key: 'ai_provider', type: 'select', width: 240, visible: aiOn, label: t('ai_provider', '服务商'),
              tip: t('ai_provider_tip', '选择 AI 服务商后，下面的「模型名称」和「接口地址」会自动填好。两个下拉框都可以手动输入：清单之外的模型名或自建接口直接敲进去即可'),
              options: AI_PROVIDERS.map((p) => ({ value: p.id, label: t('ai_provider_' + p.id, p.label) })) },
            /* 需求（用户明确要求）：在「服务商」和「模型名称」之间**新增**「模型选择」
               下拉框 —— **纯下拉**（和其它下拉框一样，只可下拉选择、不可输入）；
               「模型名称」输入框保留（可自定义任意名称）。
               两者绑定同一个 model_name 键：下拉选一个 → 名称框同步显示；
               名称框手输任意名 → 实际发送用名称框的值。 */
            { key: 'model_name', type: 'select', width: 260, visible: aiOn,
              label: t('model_select', '模型选择'),
              tip: t('model_select_tip', '从该服务商支持的模型里选一个（清单随服务商切换，只列支持的模型）；自定义模型名请在下面的「模型名称」里输入'),
              options: modelOptions.map((m) => ({ value: m, label: m })) },
            { key: 'model_name', type: 'text', wide: true, visible: aiOn,
              label: t('model_name', '模型名称'),
              tip: t('model_name_tip', '填写要使用的 AI 模型名称（可自定义任意名称，与 API Key 一起保存）'),
              placeholder: t('model_name_placeholder', '请输入模型名称（如 gpt-4、claude-3 等）'),
              datalist: provider.models },
            { key: 'api_base', type: 'text', wide: true, visible: aiOn, label: t('ai_api_base', '接口地址'),
              tip: t('ai_api_base_tip', 'OpenAI 兼容格式的接口地址，通常以 /v1 结尾。跟着服务商自动填，也可以自己改（本地模型可填 http://127.0.0.1:端口/v1）'),
              placeholder: t('ai_api_base_placeholder', 'https://api.deepseek.com/v1') },
            { key: 'api_key', type: 'secret', wide: true, visible: aiOn, label: 'API Key',
              tip: t('api_key_tip', '填写用于调用第三方 API 服务的密钥，将保存在本地配置文件中') },
            { type: 'actions', visible: aiOn },
          ],
          [
            { key: 'limit_token_output', type: 'switch', visible: aiOn, label: t('limit_token_output', '限制token输出'),
              tip: t('limit_token_tip', '限制单次回复里最大的 token 数，避免回复过长') },
            /* ⚠️ 这里是 需求 8 的**真凶**：原来这两行写成了
               `visible: tokenOn && aiOn, ... unit: 'tokens', visible: tokenOn` ——
               同一个对象字面量里**.visible 出现了两次**，JS 后者覆盖前者，
               于是 visible 实际等于 tokenOn（只看限制token输出，不看 GCP-AI 总开关）。
               结果：关掉 GCP-AI 但限制token输出开着时，第 3 张卡的这两行**照样显示**，
               卡壳就留了一截 —— 正是用户说的还露着 2 部分。
               现在只保留 `visible: tokenOn && aiOn`（两个条件都要满足）。 */
            { key: 'min_token', type: 'text', wide: true, visible: tokenOn && aiOn, label: t('min_token', '最小token量:'),
              placeholder: t('min_token_placeholder', '最小token量'), unit: 'tokens' },
            { key: 'max_token', type: 'text', wide: true, visible: tokenOn && aiOn, label: t('max_token', '最大token量:'),
              placeholder: t('max_token_placeholder', '最大token量'), unit: 'tokens' },
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
      scrollSection(hit.sectionKey);
      flashRow.value = hit.sectionKey + '/' + (hit.key || 'x');
      setTimeout(() => { flashRow.value = ''; }, 900);
    }
    function scrollSection(key) {
      currentSection.value = key;
      const host = settingsScroll.value;
      const el = host && host.querySelector('.settings-section[data-key="' + key + '"]');
      if (!el || !host) return;
      /* 程序化滚动期间锁住 scrollspy：
         否则平滑滚动还没到位，spy 就按当前 scrollTop 把选中项改回上一个板块
         —— 用户反馈的"点『关于』却停在 GCP-AI，再点一次才恢复"。 */
      scrollLockUntil = Date.now() + 700;
      /* 关闭动画时连"平滑滚动"也关掉（它是 JS 行为，不走 CSS 过渡） */
      host.scrollTo({ top: Math.max(0, el.offsetTop - 6),
        behavior: settings.ui_animation === 'off' ? 'auto' : 'smooth' });
    }
    let scrollRaf = 0;
    let scrollLockUntil = 0;
    function syncSectionFromScroll() {
      if (Date.now() < scrollLockUntil) return;
      if (scrollRaf) return;
      scrollRaf = requestAnimationFrame(() => {
        scrollRaf = 0;
        const host = settingsScroll.value;
        if (!host) return;
        const nodes = Array.from(host.querySelectorAll('.settings-section'));
        if (!nodes.length) return;
        /* 已经滚到底：直接选最后一个板块。
           最后一个板块往往到不了容器顶部，只按 offsetTop 比较会永远停在倒数第二个。 */
        if (host.scrollTop + host.clientHeight >= host.scrollHeight - 4) {
          currentSection.value = nodes[nodes.length - 1].dataset.key;
          return;
        }
        const value = host.scrollTop + 60;
        let picked = nodes[0].dataset.key;
        nodes.forEach((node) => { if (node.offsetTop <= value) picked = node.dataset.key; });
        currentSection.value = picked;
      });
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
      if (key === 'gcp_ai_agent_enabled' && value === false && settings.gcp_plugin_maker_enabled) {
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
      if (key === 'ai_provider') { queue(() => onProviderChange(value)); return; }
      if (key === 'language') { queue(() => changeLanguage(value)); return; }
      if (key === 'hotkey_search' || key === 'hotkey_ai') { queue(() => changeHotkey(key, value)); return; }
      if (key === 'resource_source' || key === 'local_resource_dir') {
        queue(async () => {
          if (await saveSetting(key, value)) {
            /* 原来这里有一句误用的 `setStep('resources')` —— setStep 是启动分步
               工具（会改 bootText / document.title / 写 [boot] step= 日志），不是切页函数，
               放在设置里会把窗口标题改成ToolsGCP · resources。已删（同 toggleFavorite 的处理）。 */
        await loadResources();
            await loadFavorites();
            toast(t('resource_source', '资源来源') + '：已更新，正在重新读取资源库', 'info');
            /* 切到云端且后端有 cloud_refresh 接口时，后台检查/拉取一次最新资源库。
               刻意不 await —— 网络慢也不能卡住设置页；状态行自己会显示"正在检查…"→ 版本号。 */
            if (key === 'resource_source' && value === 'cloud') {
              refreshCloudLibrary(true).catch(() => { /* 拉取失败由状态行显示原因 */ });
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
      } else if (row.key === 'splash_screen_duration') {
        next = Math.max(1, Math.min(5, parseInt(value, 10) || 2));
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
      toast(t('language_switched', '界面语言已切换为 {lang}').replace('{lang}', value), 'success');
    }
    async function onProviderChange(value) {
      const provider = AI_PROVIDERS.find((p) => p.id === value) || AI_PROVIDERS[0];
      const known = AI_PROVIDERS.some((p) => p.base && p.base === draft.api_base);
      if (!draft.api_base || known) draft.api_base = provider.base || draft.api_base;
      if ((provider.models || []).length) draft.model_name = provider.models[0];
      await saveSetting('ai_provider', value);
      await saveSetting('api_base', draft.api_base);
      await saveSetting('model_name', draft.model_name);
      /* Key 跟着服务商走：切完立刻把该服务商的 Key 拉回来（或清空提示去填），
         绝不能把上一个服务商的 Key 继续发给新服务商（401 的常见来源）。 */
      await loadApiKeyForProvider(value);
    }
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
    /* 进入 / 退出"录制按键"状态。
       需求：点击输入框进入检测；绑定成功自动退出检测；期间点击其它 UI（blur）也退出。 */
    function startRecord(row, event) {
      recording.value = row.key;
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
      const mods = [];
      if (event.ctrlKey) mods.push('Ctrl');
      if (event.altKey) mods.push('Alt');
      if (event.shiftKey) mods.push('Shift');
      if (event.metaKey) mods.push('Win');
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
      changeHotkey(row.key, sequence);
    }
    async function changeHotkey(key, sequence) {
      const isSearch = key === 'hotkey_search';
      const label = isSearch ? t('hotkey_search', '呼出搜索框') : t('hotkey_ai', '呼出 GCP-AI');
      const slot = isSearch ? 'search' : 'ai';
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
      const fallback = row.key === 'hotkey_search' ? 'Ctrl+Q' : 'Ctrl+Alt+G';
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
    async function toggleKeyVisible() {
      if (!apiKeyVisible.value) {
        /* 只有在输入框为空时才去后端取已保存的明文；否则会把用户正在输入的新 key 覆盖掉
           ⚠️ 必须带当前服务商（Key 按服务商分槽存储，见 loadApiKeyForProvider）。 */
        if (!String(apiKeyDraft.value || '').trim()) {
          const result = await bridge.tryCall('settings.reveal_api_key',
            String(draft.ai_provider || 'deepseek'));
          if (!result) return needApi('settings.reveal_api_key', '读取 API Key');
          if (result.ok) {
            apiKeyDraft.value = result.value || '';
            apiKeySnapshot.value = result.value || '';
          } else toast(result.error || '读取 API Key 失败', 'error');
        }
      }
      apiKeyVisible.value = !apiKeyVisible.value;
    }
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
      if (key) {
        /* ⚠️ Key 按服务商分槽存储：必须带上当前 ai_provider，
           否则切过服务商后会把 Key 存进旧服务商槽，聊天时后端读不到。 */
        const saved = await bridge.tryCall('settings.set_api_key', key,
          String(draft.ai_provider || 'deepseek'));
        if (!saved) return needApi('settings.set_api_key', '保存 API Key'), false;
        if (!saved.ok) { toast('保存失败：' + (saved.error || ''), 'error'); return false; }
        apiKeyConfigured.value = !!saved.configured;
        /* 需求：保存后输入框内容**保留**（不回填明文、不清空），只更新"已保存"快照 */
        apiKeySnapshot.value = key;
        toast(t('api_key_saved', '模型名称与 API Key 已保存'), 'success');
      } else {
        toast(t('api_key_cleared', 'API Key 已清空'), 'info');
      }
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
        toast(t('api_key_cleared', 'API Key 已清空'), 'info');
      } else toast(result.error || '清空失败', 'error');
    }
    /* 切换服务商后把**该服务商**的 Key 拉回输入框；没有就清空并提示去填。
       ⚠️ 为什么必须做：Key 按服务商分槽存储，若切换后仍沿用上一个服务商的 Key，
          发请求就是 401「API Key 无效」（后端还会在错误里附上 Key 尾号帮你核对）。 */
    async function loadApiKeyForProvider(provider) {
      const pid = String(provider || 'deepseek');
      const state = await bridge.tryCall('settings.api_key_state', pid);
      if (state && state.ok) apiKeyConfigured.value = !!state.configured;
      if (state && state.ok && state.configured) {
        const revealed = await bridge.tryCall('settings.reveal_api_key', pid);
        if (revealed && revealed.ok) {
          apiKeyDraft.value = String(revealed.value || '');
          apiKeySnapshot.value = apiKeyDraft.value;
          return;
        }
      }
      apiKeyDraft.value = '';
      apiKeySnapshot.value = '';
      apiKeyConfigured.value = false;
      if (state && state.ok) {
        toast(t('ai_key_for_provider_missing',
          '当前服务商还没有保存 API Key，请填写后点「保存」'), 'info');
      }
    }
    async function logoutDev() {
      queue(async () => {
        const key = 'debug_info_enabled_' + (draft.dev_mode_admin || 'Galen563');
        await saveSetting(key, !!settings[key]);
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
      if (payload.ok === false) {
        updateState.error = String(payload.error || '下载失败');
        toast(t('update_download_failed', '更新包下载失败：{err}')
          .replace('{err}', updateState.error), 'error');
        return;
      }
      showUpdateReadyDialog(payload);
    });
    onEvent('update.error', (payload) => {
      updateState.downloading = false;
      updateState.error = String((payload && payload.error) || '下载失败');
      toast(t('update_download_failed', '更新包下载失败：{err}')
        .replace('{err}', updateState.error), 'error');
    });
    function showUpdateReadyDialog(payload) {
      const p = payload || {};
      const size = humanSize(p.size || updateState.total || updateState.received);
      const laterLabel = t('later', '稍后');
      const nowLabel = t('restart_and_update', '立即重启并更新');
      openDialog({
        title: t('update_ready_title', '更新包已下载'),
        wide: false,
        body: t('update_ready_body',
          '新版本已经下载到临时目录。现在重启程序就会替换成新版本；选择「稍后」则先不重启（更新包会保留在临时目录，下次仍可手动更新）。'),
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
          .replace('{err}', result.error || '未知错误'), 'error');
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
    async function checkUpdate() {
      if (checkingUpdate.value) return;
      checkingUpdate.value = true;
      const repo = 'Galen563/ToolsGCP';
      const url = 'https://api.github.com/repos/' + repo + '/releases?per_page=20&_=' + Date.now();
      const data = await fetchJson(url);
      if (!Array.isArray(data)) {
        checkingUpdate.value = false;
        toast(t('update_err_network', '网络连接失败，请检查网络后重试'), 'error');
        return;
      }
      if (!data.length) {
        checkingUpdate.value = false;
        toast(t('update_err_no_release', '作者还没有发布任何版本'), 'error');
        return;
      }
      const channel = draft.update_channel || 'all';
      const pool = channel === 'stable' ? data.filter((r) => !r.prerelease)
        : channel === 'beta' ? data.filter((r) => r.prerelease) : data;
      /* ⚠️⚠️ 只有**带了 ToolsGCP.exe 的版本**才算"可更新的版本"。
         ⚠️ 为什么要筛：仓库里可能有只带源码包 / 只带其它附件的 tag（比如测试版）。
            之前直接取 pool[0] 就说"已是最新版本"，但那个版本**根本没安装包**，
            用户点了也下不到 —— 现在只认有 ToolsGCP.exe的版本。
         ⚠️ 找 exe 时不区分大小写（GitHub 上传的可能是 toolsgcp.exe）。 */
      const hasExe = (rel) => (rel.assets || []).some(
        (a) => String(a.name || '').toLowerCase() === 'toolsgcp.exe');
      const usable = pool.filter(hasExe);
      const latest = usable[0];
      if (!latest) {
        checkingUpdate.value = false;
        /* ⚠️ 区分两种情况给不同的话：
           · 渠道里一个带 exe 的版本都没有 → 明确说"没有带安装包的版本"；
           · 渠道里有，但都比当前版本旧 → 才是"已是最新版本"。 */
        if (pool.length) {
          toast(t('update_latest', '当前已是最新版本（v{v}）').replace('{v}', info.version), 'success');
        } else {
          toast(t('update_err_no_exe', '所选更新渠道还没有带 ToolsGCP.exe 的版本'), 'info');
        }
        return;
      }
      const tag = String(latest.tag_name || '').replace(/^v/i, '');
      if (!isNewer(tag, info.version)) {
        checkingUpdate.value = false;
        toast(t('update_latest', '当前已是最新版本（v{v}）').replace('{v}', info.version), 'success');
        return;
      }
      /* ⚠️ 只认 ToolsGCP.exe（没有就当这个版本不可更新），不再退化到"第一个附件" ——
         那个附件可能是校验文件 / 源码包，下载下来根本不是程序。 */
      const asset = (latest.assets || []).find(
        (a) => String(a.name || '').toLowerCase() === 'toolsgcp.exe');
      checkingUpdate.value = false;
      openDialog({
        title: t('update_available', '发现新版本'), wide: true,
        rows: [
          { k: t('update_current_version', '当前版本'), v: 'v' + info.version },
          { k: t('update_latest_version', '最新版本'), v: latest.tag_name, strong: true },
          { k: t('update_asset', '更新文件'), v: asset ? asset.name : '—' },
          { k: t('update_size', '文件大小'), v: asset ? (Math.round(asset.size / 1048576 * 10) / 10) + ' MB' : '—' },
          { k: t('update_published', '发布日期'), v: String(latest.published_at || '').slice(0, 10) },
        ],
        notes: String(latest.body || '').slice(0, 2000) || t('update_no_notes', '（这个版本没有填写更新说明）'),
        buttons: [t('later', '稍后'), t('open_release', '打开发布页'), t('download_now', '立即下载')],
      }).then((value) => {
        const pageUrl = latest.html_url || 'https://github.com/' + repo + '/releases';
        if (value === t('download_now', '立即下载')) {
          startUpdateDownload(asset && asset.browser_download_url, asset);
        } else if (value === t('open_release', '打开发布页')) openLink(pageUrl);
      });
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
      toast(t('download_started', '已开始下载：') + (asset.name || '')
        + '（' + humanSize(asset.size) + '）', 'success');
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

    /* 历史对话列表：一条 = 一个对话页 */
    const aiHistoryOpen = ref(false);
    const aiHistoryList = ref([]);
    async function loadAiSessions() {
      const result = await bridge.tryCall('ai.sessions');
      if (result && result.ok) aiHistoryList.value = result.sessions || [];
      return aiHistoryList.value;
    }
    /* 后端消息 → 前端气泡（统一走这里，确保 error/kind 还原）
       ⚠️ 报错气泡（m.error）必须原样带回来，否则“从历史点进来报错没了”。 */
    function sessionToMessages(session) {
      return (session && Array.isArray(session.messages) ? session.messages : []).map((m) => ({
        role: m.role === 'assistant' ? 'ai' : 'user',
        text: String(m.content || ''),
        error: !!m.error,
        kind: String(m.kind || ''),
      }));
    }
    /* 打开程序时接上"最近一次对话"（和 PyQt 版共用同一份 chats/ 数据） */
    async function loadAiSession(sessionId) {
      const result = await bridge.tryCall('ai.session', sessionId || '');
      if (!result || !result.ok) return false;
      const session = result.session || {};
      aiSessionId.value = session.id || '';
      aiMessages.value = sessionToMessages(session);
      return true;
    }
    async function openAiSession(sessionId) {
      if (!sessionId) return;
      const ok = await loadAiSession(sessionId);
      if (!ok) {
        /* ⚠️ 加载失败绝不能静默关面板：用户看到的就是“对话没了”。 */
        toast(t('ai_history_load_failed', '这个对话文件读不出来了，可能已损坏'), 'error');
        return;
      }
      aiHistoryOpen.value = false;
      nextTick(scrollAiToEnd);
    }
    async function deleteAiSession(sessionId) {
      const yes = await openDialog({ title: t('ai_delete_session', '删除这个对话'),
        danger: true, body: t('ai_delete_session_body', '删除后无法恢复，确定要删除这个对话吗？'),
        confirmText: t('delete', '删除') });
      if (!yes) return;
      const result = await bridge.tryCall('ai.delete_session', sessionId);
      if (!result) return needApi('ai.delete_session', '删除对话');
      if (!result.ok) { toast(result.error || '删除失败', 'error'); return; }
      if (aiSessionId.value === sessionId) { aiSessionId.value = ''; aiMessages.value = []; }
      await loadAiSessions();                     // 立刻刷新列表（不用重进界面）
      toast(t('deleted', '已删除'), 'success');
    }
    function aiHistory() {
      aiHistoryOpen.value = true;
      loadAiSessions();                           // 每次打开都拉最新的一份
    }
    function closeAiHistory() { aiHistoryOpen.value = false; }
    function scrollAiToEnd() {
      const box = document.querySelector('.ai-messages');
      if (box) box.scrollTop = box.scrollHeight;
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
    /* 插件制作辅助 / AI 开关变化、界面语言切换都要重新取一遍提示词 */
    watch([() => settings.gcp_plugin_maker_enabled, () => settings.ai_enabled, () => I18N.version],
      () => { loadAiHints(); });
    async function aiNewChat() {
      const result = await bridge.tryCall('ai.new_session');
      aiSessionId.value = (result && result.ok && result.session && result.session.id) || '';
      aiMessages.value = [];
      aiHistoryOpen.value = false;
      focusAiInput();
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
      if (!result.ok) { toast(result.error || '清空失败', 'error'); return; }
      /* 立刻清空本地列表 + 重新拉一次（双保险：列表马上就是空的） */
      aiHistoryList.value = [];
      aiSessionId.value = '';
      aiMessages.value = [];
      await loadAiSessions();
      toast(t('ai_history_cleared', '历史对话已清空') + '（' + (result.cleared || 0) + '）', 'success');
    }
    function aiStop() {
      /* ⚠️ 请求已经交给后端同步执行，这里只能"停止等待"：立刻解冻界面，
         之后回来的回答会被丢弃（回答本身可能已经落盘，历史里还能看到 —— 如实说明）。 */
      aiAborted = true;
      aiBusy.value = false;
      aiThinkingText.value = t('ai_was_cancelled', '（已取消）');
      toast(t('ai_stop_hint', '已停止等待回答（服务端可能仍在生成）'), 'info');
    }
    /* 重新生成：把最后一条 AI 回答换成"正在思考…"，用同一条用户消息再发一次 */
    async function aiRegenerate(index) {
      if (aiBusy.value) return;
      const list = aiMessages.value;
      let userText = '';
      for (let i = index; i >= 0; i -= 1) {
        if (list[i] && list[i].role === 'user') { userText = list[i].text; break; }
      }
      if (!userText) return;
      list.splice(index);                        // 丢掉这条回答（以及它之后的内容）
      await aiSend(userText, true);              // resend=true → 不再往气泡里重复追加用户消息
    }
    function aiBubbleCopied(text) { return isCopied(text); }
    /* 说话（aiSend）：把消息交给桌面端 ai.send，由后端组装提示词 / 调接口 / 落盘 */
    async function aiSend(retryText, resend) {
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
      if (!resend) aiMessages.value.push({ role: 'user', text });
      aiDraft.value = '';
      aiBusy.value = true;
      aiAborted = false;
      aiThinkingText.value = t('ai_thinking', '正在思考…');
      nextTick(scrollAiToEnd);
      const step = setInterval(() => {                     // 原版 420ms 步进
        aiThinkingText.value = '正在思考' + '.'.repeat((Math.floor((Date.now() / 420) % 3)) + 1);
      }, 420);
      try {
        const result = await bridge.tryCall('ai.send', aiSessionId.value || '', text,
          String(settings.ai_reply_mode || 'standard'), !!resend);
        if (aiAborted) return;                             // 用户点了停止 → 丢弃这次结果
        if (!result) {
          aiMessages.value.push({ role: 'ai', error: true, text: t('ai_backend_missing',
            '桌面端接口 <ai.send> 还没就绪，暂时发不出请求。') });
          return;
        }
        if (result.session_id) aiSessionId.value = result.session_id;
        /* ⚠️ 一律以后端落盘后的 session.messages 为准重建气泡：成功/失败（含 no_key、
           401 等）后端都已把对应消息写进磁盘，界面和磁盘从此一致 ——
           “从历史点进来对话没了”的根因（失败只在前端内存里推气泡）就此堵死。 */
        const session = (result.session && Array.isArray(result.session.messages))
          ? result.session : null;
        if (session) {
          aiMessages.value = sessionToMessages(session);
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
        loadAiSessions();                                // 会话标题/时间会变，顺手刷新历史
      } catch (error) {
        aiMessages.value.push({ role: 'ai', error: true, text: '请求失败：'
          + (error && error.message ? error.message : error) });
      } finally {
        clearInterval(step);
        aiBusy.value = false;
        nextTick(scrollAiToEnd);
      }
    }

    /* ---------- 输入框润色按钮（设置里可关，见 设置 → GCP-AI） ----------
       需求原话：在 GCP-AI 的输入框内最右侧 也在发送按钮的左边放一个润色按钮 AI 的图标，
                   可以在设置中的 GCP-AI 区域中找到对应设置可以点击开关设置为关闭则按钮消失。
       设计取舍：只把当前草稿交给后端 `ai.polish`，回来后**替换输入框内容**（不发送、不落历史）；
                 失败只 toast，原文一个字都不动（不能"润色失败还把用户写的话弄丢"）。 */
    async function aiPolish() {
      if (aiPolishing.value || aiBusy.value) return;
      const text = String(aiDraft.value || '').trim();
      if (!text) { toast(t('ai_polish_empty', '输入框是空的，先写一句要润色的话'), 'info'); return; }
      if (!settings.ai_enabled) { toast(t('ai_disabled', 'GCP-AI 还没有开启，可在设置里打开。'), 'info'); return; }
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
        /* rich-ai-input 的 v-model watch 会把 DOM 文本一起换掉，光标由它自己保 */
        aiDraft.value = polished;
        toast(t('ai_polished', '已润色输入框内容（未发送）'), 'success');
        nextTick(() => {
          const target = settings.ai_sidebar_mode ? aiInputPageRef.value : aiInputDrawerRef.value;
          if (target && typeof target.focus === 'function') target.focus();
          else focusAiInput();
        });
      } catch (error) {
        toast(t('ai_polish_failed', '润色失败：') + ((error && error.message) || error), 'error');
      } finally {
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
    const trayLabels = reactive({ show_main_window: '呼出主窗口', show_search_box: '呼出搜索框',
      show_ai_search: '呼出AI', exit: '退出' });
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
      if (page.value !== 'search') doGoto('search');
      /* 需求：「点击呼出搜索栏没有自动变成输入状态」。
         根因：窗口刚从托盘显示出来时 WebView 还没拿到焦点，nextTick 立刻 focus 会丢。
         这里连着补三次（立刻 / 120ms / 320ms），只要有一次窗口已激活就能成功。 */
      const doFocus = () => {
        const el = searchInput.value;
        if (!el) return;
        try { el.focus(); el.select(); } catch (e) { /* ignore */ }
      };
      nextTick(doFocus);
      setTimeout(doFocus, 120);
      setTimeout(doFocus, 320);
    }
    /* 托盘「呼出AI」：要按当前 AI 形态分流（侧栏页 / 悬浮球抽屉），
       以前这里只写 aiOpen=true，侧栏模式下等于什么都没发生。 */
    function openAiFromTray() {
      if (!settings.ai_enabled) { toast(t('ai_disabled', 'GCP-AI 还没有开启，可在设置里打开。'), 'info'); return; }
      if (settings.ai_sidebar_mode) { doGoto('ai'); nextTick(() => focusAiInput()); }
      else { aiOpen.value = true; nextTick(() => focusAiInput()); }
    }
    function onKeydown(event) {
      if (event.key === 'F11') { event.preventDefault(); toggleFullscreen(); return; }
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
        if (detail.value) { event.preventDefault(); closeDetail(); return; }
        if (selectionBar.value) { exitSelection(); return; }
        if (recording.value) { recording.value = ''; return; }
        if (trayMenu.value) { trayMenu.value = false; return; }
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
    function setStep(name) {
      bootStep = name;
      bootText.value = '启动中[' + name + ']';
      try { document.title = 'ToolsGCP · ' + name; } catch (e) {}
      try { if (bridge.ready) bridge.call('log.client', 'info', '界面', '[boot] step=' + name).catch(function(){}); } catch (e) {}
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

    async function boot() {
      try {
        setStep('bridge');
        await bridge.init();
        bridge.call('log.client','info','界面','[boot] bridge ready=' + bridge.ready).catch(function(){});
        setStep('appinfo');
        await loadAppInfo();
        await loadPaths();
        setStep('settings');
        await loadSettings();
        Object.assign(draft, settings);
        setStep('window'); await syncWindow();

        const bundle = await bridge.tryCall('i18n.bundle');
        if (bundle && bundle.ok) flattenI18n(bundle);

        /* ========== ① 法律闸门：先于一切网络资源加载（本轮需求） ==========
           未同意 → 协议窗置顶显示，**窗口照常放出来**（app.ready 提前上报），
           后面的云端加载/AI/公告全部不跑（acceptPrivacy 里再继续）。
           ⚠️ 这就是"网络差时协议窗不出现"和"任务栏有图标但窗口不弹"的根治：
              旧版把 app.ready 押在 boot 末尾，云端一卡 + 启动页遮罩（z190）盖住
              协议窗（z140）→ 用户对着一个永远不出现的窗口等同意按钮。 */
        setStep('privacy');
        const agreed = await checkPrivacyState();
        if (!agreed) {
          privacy.open = true;
          booting.value = false;            // 撤掉启动页遮罩，让协议窗成为可见的最顶层
          setStep('consent');
          try { document.title = 'ToolsGCP'; } catch (e) {}
          bridge.tryCall('app.ready');      // 窗口放出来（后端仍会等启动画面播完）
          return;                            // 同意后由 acceptPrivacy() 继续启动
        }
        /* 已同意：也要**立刻**上报 ready —— 窗口显示不再等云端资源。
           （网络差时最多看到"正在寻找资源文件…"遮罩 + 重试按钮，窗口本身一定出来；
             后端 _try_show 自己还会等启动画面，这里提前调不会闪半成品。） */
        setStep('ready');
        bridge.tryCall('app.ready');
        await continueBoot();
      } catch (error) {
        console.error('[ToolsGCP] boot failed at step=' + bootStep, error);
        booting.value = false;
        bootText.value = '启动失败（' + bootStep + '）：' + (error && error.message ? error.message : error);
        toast('启动异常（' + bootStep + '）：' + (error && error.message ? error.message : error), 'error');
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
        const options = await bridge.tryCall('resources.filter_options');
        if (options && options.ok) remoteOptions.value = options;
        const keyState = await bridge.tryCall('settings.api_key_state',
          String(settings.ai_provider || 'deepseek'));
        if (keyState && keyState.ok) apiKeyConfigured.value = !!keyState.configured;
        /* 需求：「API Key 上次保存的内容，下次打开程序里面是空的，状态更新下又出现了」。
           根因：启动时只拿了"是否已配置"（configured），从没把明文取回输入框，所以空的。
           现在启动就把已保存的 Key 取回来填上（输入框是 password 类型，显示为圆点），
           同时写进 apiKeySnapshot，这样"未保存修改"的判定才是对的。
           ⚠️ 带当前服务商：Key 按服务商分槽存储，读错槽就显示成“空的”。 */
        if (keyState && keyState.ok && keyState.configured) {
          const revealed = await bridge.tryCall('settings.reveal_api_key',
            String(settings.ai_provider || 'deepseek'));
          if (revealed && revealed.ok) {
            apiKeyDraft.value = String(revealed.value || '');
            apiKeySnapshot.value = apiKeyDraft.value;
          }
        }
        /* GCP-AI：接上最近一次对话（数据在 .ToolsGCP/config/chats/，与 PyQt 版共用） */
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
        bootText.value = t('boot_cloud', '正在加载云端资源库…');
        /* ⚠️ 云端模式（且没有可用缓存）时，**先**把加载遮罩亮起来，
           让用户看到「正在寻找资源文件…」而不是一个干巴巴的启动页。 */
        const cloudMode = String(settings.resource_source || 'cloud') === 'cloud';
        if (cloudMode) {
          resourceLoading.value = true;
          resourceLoadFailed.value = false;
          startLoadingDots();
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
        bootText.value = '正在加载资源库…';
        /* ⚠️ loadResources() 本身要等网络往返（云端不通时会等到超时）。
           启动是关键路径，不能让它无限期拖住窗口 —— 加一道 8 秒的超时保护：
           超时就用本地资源库继续启动（程序照常出来，后面还能在设置里重试）。
           ⚠️ 只在 boot 的调用点加保护，**不改 loadResources() 本身**
              （设置页/搜索页还在用它，那里等久一点是对的）。 */
        await Promise.race([
          loadResources(),
          new Promise((resolve) => { setTimeout(resolve, 8000); }),
        ]);
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
          resourceLoading.value = false;
          resourceLoadFailed.value = true;
          stopLoadingDots();
          /* 非阻塞提示（toast 自己会消失，不挡界面） */
          toast(t('resource_load_failed', '云端资源库加载失败：{err}').replace('{err}', reason),
            'warning', '', { duration: 6000 });
          hintSwitchMirror();
        } else {
          resourceLoading.value = false;
          stopLoadingDots();
        }
        await loadFavorites();
        await runQuery();
        loadDeployList();
        Object.assign(draft, settings);
        applyAppearance();
        const chosen = new Set(settings.customize_interests || []);
        selectedInterests.value = interestCatalog.value.filter((i) => chosen.has(i.name));

        /* 默认启动页（default_page → 前端页面键；--open-settings / 重启后回到设置）
           ⚠️ 「首页」已从程序里整体移除：map 里不再认它。
              老用户配置里可能还存着 `default_page: "首页"`，落到 `|| 'search'`
              兜底 → 打开就是搜索页；后端 settings_manager 那边同时会把旧值迁移掉。 */
        const map = { 搜索: 'search', 定制页: 'customize', 收藏: 'favorites',
          部署: 'deploy', 应用部署: 'deploy', 设置: 'settings', Github: 'github', 查看日志: 'log',
          公告: 'notice', 反馈: 'feedback', GCP工坊: 'workshop', 插件: 'plugins', 提交软件: 'maker' };
        page.value = map[settings.default_page] || 'search';
        if (info.args.indexOf('--open-settings') >= 0 || settings.open_settings_on_restart) {
          page.value = 'settings';
          await bridge.call('settings.set', 'open_settings_on_restart', false).catch(() => {});
          settings.open_settings_on_restart = false;
        }

        await nextTick();
        /* ⚠️ 启动动画没播完之前，前端的 loading 遮罩与主界面都不许出现：
           需求「时长设 5 就要真的等 5 秒」。桌面端会把剩余毫秒数告诉我们。 */
        let waitMs = 0;
        try {
          const remaining = await bridge.tryCall('app.splash_remaining');
          waitMs = (remaining && remaining.ok) ? Math.max(0, Number(remaining.remaining) || 0) : 0;
        } catch {
          waitMs = 0;
        }
        /* 兜底：最多再等 10 秒，防止后端异常导致永远卡在启动页 */
        waitMs = Math.min(waitMs, 10000);
        if (waitMs > 0) {
          bootText.value = t('starting', '正在启动…');
          await new Promise((resolve) => setTimeout(resolve, waitMs));
        }
        setStep('render');
        booting.value = false;
        measureViewport();
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
        var readyRes = await bridge.tryCall('app.ready');
        console.log('[boot] app.ready ->', readyRes);
        const centered = await bridge.tryCall('window.center');
        if (!centered) syncWindow();
        /* ⚠️ 法律闸门已在 boot() 最前面过掉了（agree 之后才会走到这里），
           这里只做"同意之后才拉公告"的第二道（顺序仍然是：先同意、后公告）。 */
        await loadNotices(false);

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
        }
        /* 读一次默认下载目录（占位提示要显示真路径；不阻塞启动） */
        loadDownloadDefaultDir().catch(() => { /* 没有 downloader 域就退回通用文案 */ });
      } catch (error) {
        console.error('[ToolsGCP] boot failed at step=' + bootStep, error);
        booting.value = false;
        bootText.value = '启动失败（' + bootStep + '）：' + (error && error.message ? error.message : error);
        toast('启动异常（' + bootStep + '）：' + (error && error.message ? error.message : error), 'error');
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
        bridge.tryCall('app.ready');
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
      window.addEventListener('keydown', onKeydown);
      window.addEventListener('resize', onWindowResize);
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
            用 ResizeObserver 盯着网格容器才准。 */
      if (window.ResizeObserver && favGrid.value) {
        favGridObserver = new ResizeObserver(() => { measureFavGrid(); });
        favGridObserver.observe(favGrid.value);
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
      });

      /* ⚠️ 启动总兜底：无论 boot() 卡在哪一步，8 秒后一定撤掉启动遮罩，
         保证界面永远能出来（宁可少加载一点数据，也不能一直黑屏/卡启动页）。 */
      const bootWatchdog = setTimeout(() => {
        if (booting.value) {
          console.warn('[ToolsGCP] boot watchdog fired at step=' + bootStep);
          booting.value = false;
          toast(t('boot_slow', '启动较慢（卡在 ') + bootStep + '），已先显示界面', 'warning');
        }
      }, 8000);

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
      window.removeEventListener('resize', onWindowResize);
      document.removeEventListener('mousedown', onDocMoreDown, true);
      window.removeEventListener('scroll', _makerScrollHandler, true);
      if (resizeObserver) resizeObserver.disconnect();
      if (favGridObserver) favGridObserver.disconnect();
      /* 首页轮播定时器（stopSlide）随首页一起移除，这里不再需要停它。 */
      if (rafId) cancelAnimationFrame(rafId);
      if (scrollRaf) cancelAnimationFrame(scrollRaf);
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
        const ir = on.getBoundingClientRect();
        /* left/top 相对 .segmented 的 padding box（绝对定位 left:0 落在 border 内侧），
           所以减掉 1px 边框；这样 thumb 与选中项像素对齐。 */
        let left = ir.left - sr.left - 1;
        let top = ir.top - sr.top - 1;
        let width = ir.width;
        let height = ir.height;
        /* 夹紧到容器内容框：即使某一帧量到的是旧布局（见上面 resize 那段注释），
           thumb 也绝不会画到 .segmented 外面去（用户说的"撑破父容器"）。 */
        const boxW = Math.max(0, sr.width - 2);
        const boxH = Math.max(0, sr.height - 2);
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
      visibleTags, hiddenTagCount, tagAvail, onIconError, iconSrc, iconFailed, firstChar, isHttp,
      toggleDialogChecks,
      cardMenu, openCardMenu, closeCardMenu, cardMenuMention, cardMenuPing,
      selectionBar, selectedCount, allSelected, selState, selectionItems, selectAll, exitSelection,
      confirmSelection, setView, onCardClick, runQuery,
      /* 卡片 / 详情 */
      toggleFavorite, openLink, mentionAi, openDetail, closeDetail, detailTags, activeVariant,
      introParagraphs, detailRows, chooseVariant, copiedKeys, isCopied, copyText,
      /* 定制页 */
      customizeEditing, customizeOnboarded, selectedInterests, interestCatalog, interestGroups,
      pickedInterest, toggleInterest, interestsRatio, interestNamesText, clearInterests,
      saveInterests, resetInterests, recommendations, customSort, emptyRecommendTitle, onRecommendClick,
      recommendGroups, customSortOptions, customFilters, customFilterOpen, customPanelH, customChevronDeg,
      toggleCustomFilter, isCustomFilterOn, toggleCustomFilterValue,
      /* 收藏 */
      favFolder, isDefaultFolder, moveFolderOptions, favItems, favMoving, moveTarget, favSelectedCount, favAllChecked,
      favSelState, favSelectAll, toggleRowSelect, startMoveMode, cancelMoveMode, commitMove,
      createFolder, renameFolder, removeFolder, exportFavorites, importFavorites,
      /* 收藏页卡片网格列宽 + 收藏夹右键菜单 */
      favGrid, favGridWidth, favLayout, measureFavGrid,
      favMenu, openFavMenu, closeFavMenu, favMenuRename, favMenuRemove,
      /* 公告 */
      loadNotices, isRead, markRead, markAllRead, openNotice, noticeKey, isReadKey,
      /* Github / 反馈 */
      lightbox, sponsorImage, feedbackUrl, introLines, qqGroups,
      /* 日志 */
      loadLogFiles, exportLogs, openLogDir, openPath, previewLog, logPreviewName, confirmClearLogs,
      /* 部署 */
      deployList, deployRows, deployRunning, deployProgress, deployIndeterminate, deployStatusText, picker, pickerHits,
      toggleDeployMode, openPicker, togglePick, applyPicker,
      startDeploySelection, removeDeployRow, openDeployDetail, exportManifest, importManifest,
      confirmClearDeploy, confirmDeploy, deployOne, statusText, setRowStatus, previewKindOf,
      deployIconOf, deploySourceOf, openPageSingle, ST_SKIPPED,
      /* 插件 */
      pluginQuery, pluginCountText, filteredPlugins, flashPlugin, devGuide, pluginPage,
      pluginFrameRef, syncPluginTheme,
      loadPlugins, togglePlugin, startNote, saveNote, cancelNote, deletePlugin, openPluginPage,
      openPluginDir, pluginDirs, loadPluginDirs, setPluginView, DEV_GUIDE,
      /* 提交软件 */
      maker, makerLanguages, makerSections, activeSection, makerCategories, makerCategoryOptions,
      makerCategoryText,
      makerPlatforms, makerArchs,
      i18nEnabled, i18nLangIndex, repoPlatformOptions, repoPrefix, repoPlaceholder, repoPreviewText,
      libraryStatusText, libraryLabel, libraryTooltip, libraryFullPath,
      previewName, previewDesc, previewTagList, previewIcon, statusLine, statusLevel,
      formScroll, previewCard, makerLeft, makerRight, makerBody, syncMakerPreviewSticky,
      onNameChanged, onIdChanged, onCategoryChanged, onTagsEdited, restoreTagsFollow,
      toggleChip, onRepoPlatformChanged, setI18nLang, refreshPreview, pickIcon,
      buildEntry, exportDraft, appendToLibrary,
      saveToOriginal, exitEditing, editExistingEntry, saveStandalone, clearForm, browserQuery, browserCategory, browserSelected,
      browserCategoryOptions, browserRows, browserCountText, reloadLibrary, openLibraryFile,
      deleteSelectedEntries, batchMode, batchDup, batchFiles, batchFileIndex,
      batchOutput, batchPreviewText, batchModeOptions, batchDupOptions, batchAddFiles,
      batchRemoveSelected, batchClearFiles, batchChooseOutput, batchPreview, batchRun,
      makerHelpBlocks,
      /* AI */
      showBall, ballPaused, aiOpen, aiDraft, aiBusy, aiMessages, aiWelcomeText,
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
      /* 设置 */
      sections, draft, currentSection, settingQuery, settingHits, jumpFirstHit, jumpToRow,
      scrollSection, syncSectionFromScroll, settingsScroll, flashRow, recording, isVisible, rowKey, sectionIcon,
      cardHasVisibleRow, defaultDownloadDirText, downloadDefaultDir, loadDownloadDefaultDir,
      cloudStatusText, cloudSyncing, refreshCloudLibrary,
      onRowChange, onRowInput, onRowCommit, recordHotkey, resetHotkey, toggleKeyVisible,
      startRecord, stopRecording, onSliderWheel,
      apiKeyDraft, apiKeyVisible, saveApiKey, clearApiKey, logoutDev, fire, versionText,
      storageMigrate,
      checkingUpdate, checkUpdate, saveSetting,
      updateState, humanSize, applyUpdate, startUpdateDownload, openUpdateFolder,
      showUpdateReadyDialog,
      /* 隐私 / 托盘 */
      privacy, acceptPrivacy, rejectPrivacy, checkPrivacyThenNotices,
      showTip, hideTip,
      trayMenu, trayEl, trayLabels, trayAction, focusSearch, openNativeTrayMenu,
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
    /* 可编辑态输入框里显示什么和真正存的值可以不同。
       py 版 EditableComboBox 显示的是**当前语言译名**（category_combo.currentText()），
       落盘时才用 _canonical_term 还原成规范值。这里同理：modelValue 存规范值（如工具），
       displayValue 只负责显示（如 English 界面的 "Tools"）；为 null 时退回 modelValue。 */
    displayValue: { type: String, default: null },
  },
  emits: ['change'],
  data() {
    /* ⚠️ 故意没有 flip：需求明确"不管超不超出底部，下拉列表都固定在触发器下方"。
       空间不足时只压缩列表高度（maxHeight），绝不翻到触发器上面去。 */
    return { open: false, left: 0, top: 0, minWidth: 0, maxHeight: 300, highlightedIndex: -1 };
  },
  computed: {
    /* 可编辑输入框里显示的文本（见 displayValue 的注释） */
    editText() {
      return this.displayValue == null ? this.modelValue : this.displayValue;
    },
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
      /* 点到自己的触发器/根节点：由它自己的 click 处理，这里不动 */
      if (target.closest('.combo') === this.$el) return;
      /* 其它情况一律收起 —— 包括"点到**另一个**下拉框"，这正是之前漏掉的分支 */
      this.open = false;
    };
    this._onScroll = () => { if (this.open) this.place(); };
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
    if (this.open) comboOpenRegistry.forEach((c) => { if (c !== this) c.open = false; });
  },
  beforeUnmount() {
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
      if (!el) return;
      const r = el.getBoundingClientRect();
      this.left = r.left;
      /* 永远贴在触发器下方 4px；不做任何"向上翻转" */
      this.top = r.bottom + 4;
      /* ⚠️ 弹层最小宽度 = 触发器宽度，但**封顶 360**：
         提交软件的「类别」可编辑下拉现在铺满整格（≈475px），照抄会得到一个
         475px 宽的类别列表（py 版 EditableComboBox 只有 200，观感差很多）。
         CSS 的 .combo-pop 已有 max-width: 360 ⇒ 这里必须同步封顶，
         否则 inline minWidth 会压过 max-width（min 的优先级更高）。 */
      this.minWidth = Math.min(r.width, 360);
      /* 位置不变的前提下，只把列表高度限制在下方可用空间内（至少 96px），
         这样贴底部的下拉框仍然不会跑出窗口，也不会跳到上面去。
         上限 300 → 420。类别有 31 项，300px 只露出 9 项，看着像"内容缺了一大半"；
              420px 能露出 12 项，滚动意图明显，又不会把窗口撑满。 */
      const below = Math.max(0, window.innerHeight - r.bottom - 8);
      this.maxHeight = Math.max(96, Math.min(420, below));
      /* 保底 96px 时如果下方实在放不下，弹层会伸出窗口底部被截断
         （设置页滚到底时最后一个下拉框就是这种情况）。
         这里把 top 往回收，保证「弹出高度 + 8px 边距」始终落在视口内；
         下方空间充足时 r.bottom + 4 更小，行为与原来完全一致。 */
      this.top = Math.min(this.top, Math.max(8, window.innerHeight - this.maxHeight - 8));
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
      if (String(option.value) !== String(this.modelValue)) this.$emit('change', option.value);
    },
    /* 可编辑模式：输入框每次输入都把值抛给父组件（受控），父组件负责写回 model-value */
    onEditInput(event) {
      if (this.disabled) return;
      this.$emit('change', event && event.target ? event.target.value : '');
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
           role="combobox" :aria-expanded="open ? 'true' : 'false'">
        <input ref="editInput" class="combo-edit" type="text" :value="editText"
               :disabled="disabled" :placeholder="placeholder"
               @input="onEditInput" @keydown="onEditKeyDown" @click.stop>
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
  app.mount('#app');
})(0);
