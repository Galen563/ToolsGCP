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
APP_VERSION = "1.0.0-beta.1"
APP_AUTHOR = "Galen563"
# 本构建自身的通道：beta（预发布）/ stable（正式）。**只影响界面上的标识显示**，
# "用户想收哪种版本"是另一个概念，存在设置里（见下面的 update_channel）。
APP_CHANNEL = "beta"

# ---------- 程序自更新（检查 / 下载）----------
# 目标仓库与发布地址
APP_REPO = "Galen563/ToolsGCP"
APP_HOMEPAGE = "https://github.com/Galen563/ToolsGCP"
APP_RELEASES_PAGE = "https://github.com/Galen563/ToolsGCP/releases"
# 🔒 自更新的目标文件名：**永远不改名**。
#    更新器就是按这个字符串精确匹配 Release 里的资产，所以它必须和
#    .github/workflows/release.yml 里 pyinstaller --name ToolsGCP 的产物名一致。
#    详见 docs/UPDATE_PLAN.md 第三节「更新目标的识别契约」。
APP_ASSET_NAME = "ToolsGCP.exe"
# 校验清单的资产名（构建流水线产出；有就用它校验下载完整性，没有就跳过）
APP_CHECKSUM_ASSET = "SHA256SUMS.txt"
UPDATE_RELEASES_API = "https://api.github.com/repos/{repo}/releases"

# ---------- 公告（仓库里带「公告」标签的 Issue）----------
# 公告的载体就是**这个仓库里的 Issue**：作者给 Issue 打上「公告」标签，它就成为一条公告。
# ⚠️ 只认"作者本人发的"（见 ANNOUNCEMENTS_OWNER / ANNOUNCEMENTS_OWNER_ASSOCIATION）：
#    别人在仓库里开一个带「公告」标签的 Issue 不该出现在客户端里 ——
#    否则任何人都能往所有用户的公告页里推内容。
ANNOUNCEMENTS_API = "https://api.github.com/repos/{repo}/issues"
ANNOUNCEMENTS_LABEL = "公告"              # 只认这个标签的 Issue
ANNOUNCEMENTS_OWNER = "Galen563"          # 作者是 TA
ANNOUNCEMENTS_OWNER_ASSOCIATION = "OWNER"  # 或者 author_association 是 OWNER（两者满足其一）

# 更新下载渠道：决定「检查更新」愿意接受哪种发布
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
# ⚠️ 「国内源」已按需求删除。现在下拉框里是"GitHub 官方 + 一组公益镜像站"：
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
    "deploy_mode": False,  # False=导出模式, True=部署模式（持久化）
    "splash_screen_enabled": True,  # 启动动画开关
    "splash_screen_duration": 2,    # 启动动画时长（秒）
    "auto_search": True,            # 自动搜索（默认开启；关闭时需按Enter或点击搜索按钮）
    "hotkey_enabled": True,         # 全局快捷键开关
    "hotkey_search": "Ctrl+Q",      # 全局呼出搜索框的快捷键
    # 全局呼出 GCP-AI 的快捷键。⚠️ 这里**不能**用 Caps Lock 做主键：
    # Windows 的 RegisterHotKey 拿 VK_CAPITAL 注册必然失败（错误码 1409），
    # 老默认值 Ctrl+Caps 就是这么坏掉的（见 utils/global_hotkey.unusable_main_key）。
    "hotkey_ai": "Ctrl+Alt+G",
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
    # 更新下载渠道（决定「检查更新」愿意接受哪种发布）：
    #   all    = 正式版 + Beta 版（默认）
    #   stable = 仅正式版
    #   beta   = 仅 Beta 版
    "update_channel": "all",
    "api_key": "",                   # 自定义 API Key（旧字段，已迁移到 api_key_enc）
    "api_key_enc": "",               # 加密后的 API Key（DPAPI）
    "model_name": "",                # 模型名称（如 deepseek-v4.1-flash）
    # AI 服务商 id（deepseek / kimi / qwen / siliconflow / custom）。
    # 只用来决定设置页两个下拉框的默认值，**发请求时仍然只用 api_base + model_name**，
    # 所以用户手填的服务商/模型永远能用，不受这张表限制。
    "ai_provider": "deepseek",
    "api_base": "https://api.deepseek.com/v1",  # 接口地址（OpenAI 兼容，末尾带 /v1）
    "ai_enabled": False,             # 开启 GCP-AI
    # 侧边栏 AI 单独界面：开启后悬浮球消失、左侧栏 GCP工坊下面出现「AI」整页界面。
    # 默认关（需求："默认不开启"）。只有在 ai_enabled 打开时才在设置里露出这一行。
    "ai_sidebar_mode": False,
    "limit_token_output": False,     # 限制 token 输出
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
    # ---------- 内置插件「插件制作辅助」（旧名：插件制作器） ----------
    # 默认关闭。开启后可以通过提示词让 AI 按模板做一个新插件并装到 plugins/ 下。
    "gcp_plugin_maker_enabled": False,
    # 制作辅助给它生成的插件"强制要求"的那几项（README 必写等），默认全开：
    #   require_readme      必须生成 README.md
    #   readme_strict       README 要写得缜密（核心功能 / 用法 / 结构说明）
    #   readme_languages    README 的多语言版本（zh_CN / zh_TW / en_US，可各自开关）
    #   three_languages     插件本体默认带简体中文 / 繁體中文 / English 三套语言
    "gcp_plugin_maker_options": {},
}
