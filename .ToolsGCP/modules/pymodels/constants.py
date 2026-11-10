"""
常量定义模块
"""

import os
import sys

# 应用信息
# 版本号只在这里定义一次，其它地方一律 import 使用，避免多处不一致
APP_NAME = "ToolsGCP"
# ⚠️ 版本号**只此一份**，别再往别处写第二份（pymodels/__init__.py 已经改成从这里转发）。
#    格式是语义化版本 SemVer：主版本.次版本.修订号[-预发布标识]
#    完整规则见 docs/VERSIONING.md。这里**不带 v**（只有 git tag 和界面显示才带 v）。
APP_VERSION = "1.0.0-beta.3"
APP_AUTHOR = "Galen563"
# 本构建自身的通道：beta（预发布）/ stable（正式）。**只影响界面上的标识显示**，
# "用户想收哪种版本"是另一个概念，存在设置里（见下面的 update_channel）。
APP_CHANNEL = "beta"

# ---------- 程序自更新（检查 / 下载）----------
# 目标仓库与发布地址
APP_REPO = "Galen563/ToolsGCP"
# ---------- 云端"资源索引"仓库（本轮需求，用户原话）----------
# 「把索引云端的 ToolsGCP-Resources.json 和 icon.zip 文件夹的地址改为
#   https://github.com/Galen563/ToolsGCP-Resources/releases，
#   其他不变例如更新什么的还是在旧的仓库」
#   → 只有**资源索引 JSON + 图标包 icon.zip** 这两样去新仓库找；
#     自更新（ToolsGCP.exe / 校验清单）、公告、GitHub 页、版本发布页
#     仍然全部走 APP_REPO（Galen563/ToolsGCP），一个字不动。
# ⚠️ 为什么不是"直接改常量"就完事：实测新仓库此刻**还没有任何 release，
#    源码树里也还没有 ToolsGCP-Resources.json**（只有 LICENSE / README，
#    已用 GitHub API 核过）。裸替换会让所有用户的云端资源库和图标当场失效，
#    而且资源库缓存为空时程序连 52 条资源都列不出来。
#    → 所以这两个模块实现成「新仓库优先 → 拿不到再退回旧仓库」：
#      今天行为完全不变（继续从旧仓库拿），作者一发布到新建仓库就自动切换，
#      不需要再改代码、也不需要发版。
RESOURCES_REPO = "Galen563/ToolsGCP-Resources"
RESOURCES_RELEASES_PAGE = "https://github.com/Galen563/ToolsGCP-Resources/releases"
# 资源索引/图标包的候选仓库顺序：新仓库在前，旧仓库兜底
RESOURCES_REPO_CHAIN = (RESOURCES_REPO, APP_REPO)
APP_HOMEPAGE = "https://github.com/Galen563/ToolsGCP"
APP_RELEASES_PAGE = "https://github.com/Galen563/ToolsGCP/releases"
# 🔒 自更新的目标文件名：**永远不改名**。
#    更新器就是按这个字符串精确匹配 Release 里的资产，所以它必须和
#    .github/workflows/release.yml 里 pyinstaller --name ToolsGCP 的产物名一致。
#    详见 docs/UPDATE_PLAN.md 第三节更新目标的识别契约。
APP_ASSET_NAME = "ToolsGCP.exe"
# 校验清单的资产名（构建流水线产出；有就用它校验下载完整性，没有就跳过）
APP_CHECKSUM_ASSET = "SHA256SUMS.txt"
UPDATE_RELEASES_API = "https://api.github.com/repos/{repo}/releases"

# ---------- 公告（仓库里带公告标签的 Issue）----------
# 公告的载体就是**这个仓库里的 Issue**：作者给 Issue 打上公告标签，它就成为一条公告。
# ⚠️ 只认"作者本人发的"（见 ANNOUNCEMENTS_OWNER / ANNOUNCEMENTS_OWNER_ASSOCIATION）：
#    别人在仓库里开一个带公告标签的 Issue 不该出现在客户端里 ——
#    否则任何人都能往所有用户的公告页里推内容。
ANNOUNCEMENTS_API = "https://api.github.com/repos/{repo}/issues"
ANNOUNCEMENTS_LABEL = "公告"              # 只认这个标签的 Issue
ANNOUNCEMENTS_OWNER = "Galen563"          # 作者是 TA
ANNOUNCEMENTS_OWNER_ASSOCIATION = "OWNER"  # 或者 author_association 是 OWNER（两者满足其一）

# 更新下载渠道：决定检查更新愿意接受哪种发布
#   all    = 正式版 + Beta 版（默认）
#   stable = 仅正式版
#   beta   = 仅 Beta 版
UPDATE_CHANNEL_ALL = "all"
UPDATE_CHANNEL_STABLE = "stable"
UPDATE_CHANNEL_BETA = "beta"
UPDATE_CHANNELS = (UPDATE_CHANNEL_ALL, UPDATE_CHANNEL_STABLE, UPDATE_CHANNEL_BETA)

# 运行参数
IS_AUTOSTART = "--autostart" in sys.argv
OPEN_SETTINGS = "--open-settings" in sys.argv

# 路径相关
def get_script_dir():
    """获取脚本所在目录"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        return os.path.dirname(os.path.abspath(sys.argv[0]))

SCRIPT_DIR = get_script_dir()
# .ToolsGCP：**程序目录旁**的数据根。里面既有"随程序发布"的东西（资源库、图标、语言文件），
# 也有老版本残留的配置。⚠️ 现在"程序自己写出来的配置"改存到用户主目录了（见下面 USER_DATA_ROOT），
#    这一个是**资源**的大本营（modules / images / Icon / logo.png / ToolsGCP-Resources.json），
#    永远不搬走 —— resource_path() 全靠它定位语言文件和图标。
CONFIG_DIR = os.path.join(SCRIPT_DIR, ".ToolsGCP")
LANGUAGES_DIR = os.path.join(CONFIG_DIR, "modules", "languages")
IMAGES_DIR = os.path.join(CONFIG_DIR, "images")


def resource_path(*parts):
    """定位一个"随程序发布"的资源（logo.png / Icon / languages / 资源库…）
    要查两个地方，因为打包方式是 `--onefile --add-data ".ToolsGCP;.ToolsGCP"`：
      1. 程序目录旁的 .ToolsGCP   —— 解压安装、或直接跑源码时在这儿
      2. sys._MEIPASS/.ToolsGCP   —— onefile 打包后，.ToolsGCP 被塞进了 exe 内部，
                                     运行时才解压到这个临时目录
    两边都试一遍，谁先命中用谁；都没命中就返回第一个候选路径（调用方自己判存在）。
    这样无论用户是"绿色包 + 旁边一个 .ToolsGCP"还是"光秃秃一个 exe"，
    图标 / 语言文件都还能找到。
    """
    candidates = []
    if CONFIG_DIR:
        candidates.append(os.path.join(CONFIG_DIR, *parts))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, ".ToolsGCP", *parts))
    for path in candidates:
        try:
            if os.path.exists(path):
                return path
        except Exception:
            continue
    return candidates[0] if candidates else ""

# ---------- 程序自己产出的配置（**用户主目录下的 .ToolsGCP**） ----------
# 需求：对话 / 配置文件 / 免责声明这些"程序开启后自动创建的文件"改存到用户电脑的用户目录
#       （自适应，不是写死 C:\Users\Administrator），并在用户主目录里放一个 ToolsGCP.json
#       记录"这个 .ToolsGCP 到底在哪"（用户以后可以在设置里改位置）。
# ⚠️ 这里**只管配置文件**：资源库（ToolsGCP-Resources.json）、图标、模块代码、语言文件
#    仍然留在 CONFIG_DIR（程序目录旁），原因见 core/data_root.py 的开头说明。
from .core.data_root import ensure_user_data_root as _ensure_user_data_root  # noqa: E402

# 解析顺序：ToolsGCP.json 指针 → 坏了/丢了就自动回落到 <用户主目录>\.ToolsGCP 并重建
USER_DATA_ROOT = _ensure_user_data_root()

DATA_DIR = os.path.join(USER_DATA_ROOT, "config")
CHATS_DIR = os.path.join(DATA_DIR, "chats")            # GCP-AI 历史对话（每会话一个 json）
PLUGIN_DATA_DIR = os.path.join(DATA_DIR, "plugin_data")  # 插件自己的可写目录

# ========== 日志相关路径 ==========
# 日志跟着用户数据根走（同样是程序自动产出）
#   system_log.log     当前会话日志（追加写，记录系统信息/操作行为）
#   history/           历史日志归档（按启动时间命名）
LOGS_DIR = os.path.join(USER_DATA_ROOT, "logs")
LOG_HISTORY_DIR = os.path.join(LOGS_DIR, "history")
LOG_CURRENT_FILE = "system_log.log"
LOG_FILE_PREFIX = "ToolsGCP"
LOG_MAX_HISTORY = 30  # 历史日志保留数量（超出按修改时间删旧）

# GCP密钥
VALID_GCP_KEYS = [
    "GCP-74G2-N052-8X42", 
    "GCP-N228-45G0-Y728",
    "GCP-054N-2G82-4Z27", 
    "GCP-G782-N402-5K20"
]

# 开发者密钥
DEV_KEYS = {
    "GCP-G756-23L4-N375": "Galen563",
    "GCP-76C2-P081-5Y60": "Cyric373"
}

# 特殊密钥
SPECIAL_KEYS = ["Galen563-ToolsGCP", "GCP License Key"]

# 源选项
# ⚠️ 国内源已按需求删除。现在下拉框里是"GitHub 官方 + 一组公益镜像站"：
#    镜像站就排在 GitHub 下面（需求原话："在他们每个 github 下面分别写如图所示
#    的内容" —— 写进下拉框里，不要再在下面另加一段说明文字，那两段 text 已经删掉）。
#    镜像站目前只是"可选项"（真正走镜像下载的功能还没做）。
GITHUB_MIRRORS = ["ghfast.top", "gh-proxy.com", "ghproxy.net", "gh.ddlc.top"]
SOURCE_OPTIONS = ["Github"] + GITHUB_MIRRORS

# 反馈地址
FEEDBACK_URL = "https://github.com/Galen563/ToolsGCP/issues"

# 默认设置
DEFAULT_SETTINGS = {
    "theme": "跟随系统",
    # 组件配色：blue（默认）/ purple / orange —— 见 interfaces/settings/theme.py
    "accent_color": "blue",
    "language": "跟随系统",
    "license_key": "",
    "notify_enabled": True,
    "last_search": "",
    "startup_with_windows": False,
    "minimize_to_tray": True,
    "default_page": "搜索",
    "close_mode": "彻底退出",
    "open_settings_on_restart": False,
    "dev_mode_enabled": False,
    "dev_mode_admin": "",
    "dev_mode_verify_time": "",
    "dev_mode_key": "",
    "debug_info_enabled_Galen563": False,
    "debug_info_enabled_Cyric373": False,
    "search_source": "",
    "download_source": "",
    "download_speed_limit_enabled": False,
    "download_speed_limit": 100,
    # 下载保存位置（空 = 系统下载文件夹 `<用户主目录>\Downloads`）。
    # ⚠️ 以前默认目录是 `<用户主目录>\Downloads\ToolsGCP`（自动生成的子文件夹），
    #    删除之前自动生成ToolsGCP文件，干净点直接在下载目录下下载→
    #    现在空值 = 直接用系统下载目录，不再套一层 ToolsGCP。
    "download_save_dir": "",
    # 多线程下载并发数（1~100，默认 100）。用户要输入框样式的，还能拉动进度条调整。
    "download_threads": 100,
    # 失败重试次数（1~20，默认 5，每次间隔 30s）。
    # ⚠️ 连接上则这个重试次数回归5= **单次下载任务内部**的策略：一旦连接成功，
    #    后续失败不再按用户设的次数重试（用户设的值要保留，所以这里不改配置）。
    "download_retry_count": 5,
    # Releases 弹窗顶部下拉框：official（官方，已筛选）/ all（全部，含 GitHub 自动生成的
    # 源码包 zip / tar.gz）。选择会保存，下次进弹窗沿用。
    "releases_source": "official",
    "deploy_mode": False,  # False=导出模式, True=部署模式（持久化）
    "splash_screen_enabled": False,  # 启动动画开关（需求：默认关闭）
    "splash_screen_duration": 2,    # 启动动画时长（秒）
    # 主题效果：mica=云母（默认）/ glass=毛玻璃 / acrylic=亚克力
    # 只影响标题栏、侧栏与弹层的模糊/底噪/高光，内容区永远清晰
    "theme_effect": "mica",
    # UI 动画强度（设置 → 动画，默认开启）：
    #   on      = 全部动画
    #   reduced = 减少动画（所有过渡 / 有限的 UI 动画压到 ~110ms；左侧栏指示标照常滑动）
    #   off     = 关闭动画（除程序启动动画外全部关闭；左侧栏指示标瞬时跳转）
    "ui_animation": "on",
    # 左侧栏鼠标靠近自动展开（需求：默认关闭，只在设置 → 功能里开）
    "nav_hover_expand": False,
    # 关闭左侧栏蓝色选中标的Q 弹回弹（设置 → 功能，默认关闭本开关 = 保留弹簧手感）：
    #   False = 保留后沿 easeOutBack 的过冲 / 回弹（原版手感）
    #   True  = 后沿改用 easeOutCubic，只跟到位、不过冲（前身先出去的拉伸仍保留）
    "nav_indicator_bounce": False,    # 侧边栏指示 Q 弹（默认关 = 到位即停）
    # 滚动惯性（需求：默认关闭）。开启后滚停会顺势再滑一小段（60~140px），物理但不夸张。
    "scroll_inertia": False,
    # 滚动惯性大小（单位 %，1~100，默认 35）。只在 scroll_inertia 开启时生效：
    # 数值越大，松手后顺势滑得越远（前端换算：decay = 0.78 + 0.0017*strength，封顶 0.90）。
    "scroll_inertia_strength": 35,
    # 提示框（InfoBar）位置：top=顶端居中（默认）/ top_right=右上 / bottom_right=右下 /
    #   top_left=左上 / bottom_left=左下
    # ⚠️ 默认改成 **top**（顶端居中），以前是 top_right（右上角）。
    "toast_position": "top",
    "auto_search": True,            # 自动搜索（默认开启；关闭时需按Enter或点击搜索按钮）
    "hotkey_enabled": True,         # 全局快捷键开关
    "hotkey_search": "Ctrl+Q",      # 全局呼出搜索框的快捷键
    # 全局呼出 GCP-AI 的快捷键。⚠️ 这里**不能**用 Caps Lock 做主键：
    # Windows 的 RegisterHotKey 拿 VK_CAPITAL 注册必然失败（错误码 1409），
    # 老默认值 Ctrl+Caps 就是这么坏掉的（见 utils/global_hotkey.unusable_main_key）。
    "hotkey_ai": "Ctrl+Alt+G",
    # 全局"在浏览器里打开 ToolsGCP"的快捷键（需求：功能和桌面端完全一致，只是换到浏览器）。
    # ⚠️ 默认值 Ctrl+Shift+O **不含 Caps Lock**，所以它正常落回 RegisterHotKey 那条路
    #   （shell.apply_hotkey_settings 按 capskeyhook.sequence_has_caps 分流）。
    #   为什么不再用 Caps 做默认：RegisterHotKey 既不接受 VK_CAPITAL 做主键（错误码 1409），
    #   也没有"Caps Lock 修饰位"（MOD_* 只有 Alt/Ctrl/Shift/Win，0x04 那一位被系统自己占着）
    #   → **含 Caps 的组合只能**交给 `desktop/native/capskeyhook.py` 的低级键盘钩子
    #   （WH_KEYBOARD_LL）自己判。那条钩子仍保留：用户自己录成带 Caps 的组合时由它接管；
    #   但默认值不再依赖它 —— 走系统级 RegisterHotKey 更省资源，和别的程序抢键也看得见。
    #   见 desktop/shell.py 的 HOTKEYS 与 apply_hotkey_settings 的分流注释。
    "hotkey_browser": "Ctrl+Shift+O",
    # ⚠️⚠️ 两条迁移标记 `_migrated_browser_hotkey_caps` / `_migrated_browser_hotkey_shift`
    #    **故意不写进 DEFAULT_SETTINGS**：
    #    load_settings 开头会"把 DEFAULT_SETTINGS 里缺的键补进用户配置"，
    #    标记一旦进了这份表，老配置读进来时**先被补成 True**，
    #    后面 `if not settings.get(标记)` 永远不成立 → 迁移变成死代码
    #    （"老用户的 Ctrl+D 永远迁不掉"这个 bug 就是这么来的，实测踩过）。
    #    新装用户不需要标记：配置文件不存在时直接整份写 DEFAULT_SETTINGS，
    #    里面本来就是新默认值，迁移判据（值等于旧默认值）自然不成立。
    #    迁移本身见 core/settings_manager.load_settings 的"浏览器模式快捷键"那一段。
    # 浏览器模式的本地端口：0 = 自动挑一个空闲端口（默认）。
    # 固定端口的好处是书签稳定，代价是"端口被别人占了就起不来"，所以默认 0。
    "browser_port": 0,
    # 搜索页卡片大小：small / medium / large
    "search_card_size": "medium",
    # 搜索页视图：tile=磁贴（一行 4 个大卡片，默认）/ grid=网格（一行 6 个小卡片）
    "search_view": "tile",
    # 搜索页卡片上是否显示 GitHub 按钮（**默认开启**，设置里可关）
    "search_show_github": True,
    # 内部标记：GitHub 按钮默认值"关 → 开"的一次性迁移是否已经做过。
    # 新装用户直接带着这个标记，所以不需要迁移（见 settings_manager.load_settings）。
    "_migrated_show_github_default": True,
    # 搜索页工具栏上是否显示"磁贴 / 网格"切换按钮（默认显示；关掉之后排序会右移补齐）
    "search_show_view_switch": True,
    # 插件页排版：grid（井字形，默认）/ list（一行一个）
    "plugin_view": "grid",
    # 资源来源：cloud（云端，默认）/ local（本地文件）
    "resource_source": "cloud",
    # 本地资源目录（留空就用程序自带的 .ToolsGCP）
    "local_resource_dir": "",
    # 更新下载渠道（决定检查更新愿意接受哪种发布）：
    #   all    = 正式版 + Beta 版（默认）
    #   stable = 仅正式版
    #   beta   = 仅 Beta 版
    "update_channel": "all",
    "api_key": "",                   # 自定义 API Key（旧字段，已迁移到 api_key_enc_<服务商>）
    "api_key_enc": "",               # 加密后的 API Key 旧单槽（首次读取时迁移到当前服务商槽）
    "model_name": "",                # 模型名称（界面显示名，如 deepseek-v4.1-flash；发送时按官方文档转换）
    # AI 服务商 id（deepseek / kimi / qwen / siliconflow / custom）。
    # 只用来决定设置页两个下拉框的默认值，**发请求时仍然只用 api_base + model_name**，
    # 所以用户手填的服务商/模型永远能用，不受这张表限制。
    "ai_provider": "deepseek",
    "api_base": "https://api.deepseek.com/v1",  # 接口地址（OpenAI 兼容，末尾带 /v1）
    "ai_enabled": False,             # 开启 GCP-AI
    # 侧边栏 AI 单独界面：开启后悬浮球消失、左侧栏 GCP工坊下面出现AI整页界面。
    # 默认关（需求："默认不开启"）。只有在 ai_enabled 打开时才在设置里露出这一行。
    "ai_sidebar_mode": False,
    # 输入框润色按钮。默认开；关掉后 GCP-AI 输入框最右侧（发送键左边）的
    # AI 小按钮消失（前端 v-if 判定，后端 ai.polish 仍可调用）。
    "ai_polish_enabled": True,
    # GCP-AI「思考」强度档位（输入框内下排左侧那个滑块）：**默认 off**
    # （需求："选择不同模型下面的思考也会默认跟随对应模型变化，默认思考都为关闭"
    #  + 本轮："把思考开关改为对接官方API的多档位滑动强度而不是只有开和关（类似Codex）"）。
    # ⚠️ 本轮起这个键存的是**档位字符串**："off" / "low" / "medium" / "high"
    #   （对应官方 OpenAI 兼容接口的 reasoning_effort 字段）。
    #   ⚠️ 旧配置里存的是布尔 True/False —— 一律由 providers.normalize_thinking() 兜掉
    #      （False→"off"、True→"medium"），所以这里改默认值**不需要**做配置迁移。
    # ⚠️ 后端发送时读这个键（desktop/api/ai.py 的 _thinking_state）：
    #   · low/medium/high → 请求体带 reasoning_effort + thinking.enabled，
    #     回答里的 reasoning 存进会话并画折叠块；
    #   · "off" → 请求体**只**带 thinking.disabled —— 推理模型（deepseek-v4 等）在服务端
    #     默认就是开着的，不显式关掉它就会一直吐 reasoning_content（用户报的
    #     "我也没有思考按钮但是为什么 AI 会输出带有思考内容的句子"的根因）；
    #   · 该模型不支持思考时**不发**这些参数（老网关会因未知参数 400）；
    #   · 网关把档位判成 400 时，后端发送路径会**自动去掉思考参数重试一次**
    #     （用户填的中转/自建网关很多不认，不能因为想开思考就整条消息发不出去）。
    "ai_thinking": "off",
    # GCP-AI 回复语言（需求 3 新增）："auto"（跟随用户最新消息语言）/ "zh_CN" / "zh_TW" / "en"。
    # ⚠️ 为什么必须有这项：模型默认"跟着输入语言走"，但中英混输、系统提示词是中文时
    #    它经常整段切错语言（用户抱怨英文界面问中文问题却收英文回答这类）。语言指令
    #    由 core/ai/prompt.py 的 language_rule() 生成一句**极短有力**的强制指令拼进
    #    system 靠后位置（越靠后越遵守）。可选列表与显示名由 desktop/api/ai.py 的
    #    model_choices() 返回值里的 reply_languages 提供给前端画下拉。
    "ai_reply_language": "auto",
    # ---------- 服务商配置档案（本轮设置页重构新增） ----------
    # 需求原话：「添加服务商，点击之后下面大列表中出现一个类似卡片ui，里面的原本是模型选择
    #   改为支持模型，之后模型名称和接口和API Key不变 不过下面还要有一个token限制输出ui，
    #   好了之后里面有测试连接和保存 没有清除按钮；保存好后这个ui会变成一个长条卡片ui…
    #   我需要他不变 如果期间我删除了原本选择模型厂商的apikey则选择一个更靠上的厂商的
    #   第一个模型。」
    #
    # 数据形状：**有序数组**，每项一条已配置的服务商：
    #   {
    #     "provider": "deepseek",              # 厂商 id（providers.PROVIDERS 里的 id）
    #     "label":    "DeepSeek",              # 模型名称 —— 纯**显示标签/备注**，
    #                                          # 默认取厂商品牌名；不参与真实调用
    #                                          # （用户原话："这个模型名称不影响真实回答和
    #                                          #  厂商调用和使用模型…只是一个单纯的标签"）
    #     "api_base": "https://api.deepseek.com/v1",
    #     "models":   ["deepseek-v4.1-flash"], # 支持模型（官方清单勾选 + 可手输补充）
    #     "model":    "deepseek-v4.1-flash",   # 当前实际调用哪一个（∈ models）
    #     "max_token": 4096,                   # 该服务商独立的输出 token 上限
    #   }
    # ⚠️ **数组顺序即优先级**：第 0 项最优先、自动作为"当前使用"。
    #    删掉最上面那家（或它的 Key）就自动落到下一家 —— 用户确认的口径。
    # ⚠️ API Key **不放在这里**：它仍然走 `api_key_enc_<pid>` 的 DPAPI 加密分槽
    #    （settings_manager.get/set_api_key），绝不进这份明文 JSON。
    # ⚠️ 老用户升级：数组为空时由 desktop/api/ai.py 自动从旧的
    #    `ai_provider` / `model_name` / `api_base` 三个键合成一条，不用手动迁移。
    "ai_provider_profiles": [],
    # ⚠️ 配套标记：用户**第一次真正写档案**（新增/保存/删除）后置 True。
    #    作用是防止"删掉最后一条档案 → 旧平铺键还在 → 下次读列表又合成出一条
    #    幽灵档案"。判据不能靠"配置里有没有 ai_provider_profiles 键"，
    #    因为 SettingsManager 会把 DEFAULT_SETTINGS 合并进来并落盘，那个键永远存在。
    "ai_profiles_migrated": False,
    # ⚠️ 本轮新增（修「同厂商两条档案的模型切换会同时变」+ 思考档位按模型独立）：
    #   `ai_profile_id` —— 用户在聊天框模型弹层里**显式选中**的那条档案 id。
    #     以前"当前用哪条档案"完全由数组顺序推（active_profile = 第一条有 Key 的），
    #     于是同厂商两条档案在界面上是两条独立分组、后端却永远只认靠前那条：
    #     点第二条的模型 = 看着切了、实际没切（用户报的"两个同时改变切换状态"）。
    #     有值且能在数组里找到时，它优先于顺序推导。
    #   `ai_thinking_level` —— **按模型**分别记住思考档位：{ "<provider>|<model>": "high" }。
    #     旧设计只有一个全局 `ai_thinking`，换模型就被顶掉（用户原话：
    #     "每个思考强度都有单独的存储等级几的强度"）。默认档仍然是关（需求"默认关闭"），
    #     查不到这个模型的记录时回落到 `ai_thinking`（保持旧行为）。
    "ai_profile_id": "",
    "ai_thinking_level": {},
    "limit_token_output": False,     # 限制 token 输出（⚠️ 新一轮已从设置页移除，
                                     #   仅作旧配置兼容；服务商卡片自带 max_token）
    "min_token": 0.5,                # 最小 token 量
    "max_token": 4096,               # 最大 token 量
    # 发给模型的对话上下文范围：0=整个会话（最长记忆），10/20/30=最近 N 轮。
    # ⚠️ 注意：这只是"发多少条给模型"，磁盘上的历史永远完整保存。
    "ai_context_rounds": 0,
    # AI 回复模式：standard（标准）/ concise（简洁）/ professional（专业）。
    # 决定回答的长度和细节程度，对应 core/ai/prompt.py 里的 MODE_PROMPTS。
    # ---------- 内置插件 GCP-AI Agent ----------
    # 打开后 GCP-AI 拥有"操作 ToolsGCP 的手"（见 core/ai/agent_tools.py）。
    # ⚠️ **默认关闭**（需求：插件 GCP-AI Agent 改为默认关闭）：
    #    关着的时候发请求连一个字的工具提示词都不带，模型只会正常聊天；
    #    用户要求它"干活"时，它会按固定文案引导用户去插件页打开。
    "gcp_ai_agent_enabled": False,
    # 单个"手"的开关：{工具名: False} 表示这一项被用户关掉了。
    # ⚠️ 只记**被关掉的**（默认全开），新加的工具自动是开的。
    "gcp_ai_agent_tools_off": [],
    # ---------- 内置插件插件制作辅助（旧名：插件制作器） ----------
    # 默认关闭。开启后可以通过提示词让 AI 按模板做一个新插件并装到 plugins/ 下。
    "gcp_plugin_maker_enabled": False,
    # 制作辅助给它生成的插件"强制要求"的那几项（README 必写等），默认全开：
    #   require_readme      必须生成 README.md
    #   readme_strict       README 要写得缜密（核心功能 / 用法 / 结构说明）
    #   readme_languages    README 的多语言版本（zh_CN / zh_TW / en_US，可各自开关）
    #   three_languages     插件本体默认带简体中文 / 繁體中文 / English 三套语言
    "gcp_plugin_maker_options": {},
}
