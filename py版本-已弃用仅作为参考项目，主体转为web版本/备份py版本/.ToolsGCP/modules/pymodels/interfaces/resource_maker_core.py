"""
资源制作器核心逻辑（无界面）

常量、路径推算、资源库读写（原子写 + 自动备份）、字段整理和几个纯函数；
不依赖任何页面对象，可以直接 import 进来自检。

⚠️ 本文件在 `.ToolsGCP/modules/pymodels/interfaces/` 下，项目根要到第 5 层才命中，
   所以 find_project_root 放宽到 8 层，结果缓存成模块级常量 PROJECT_ROOT。
"""

import json
import os
import re
import shutil
import time
from datetime import datetime

from .settings.theme import SIZES, tokens
# schema 版本/字段顺序/枚举的唯一事实来源，别处不要再抄一份
from ..core import resource_schema

SCHEMA_VERSION = resource_schema.SCHEMA_VERSION
ICON_DIR_NAME = ".ToolsGCP/Icon"
RESOURCE_FILE_NAME = ".ToolsGCP/ToolsGCP-Resources.json"

CATEGORIES = [
    "工具", "游戏", "平台", "编程", "游戏引擎",
    "视频平台", "建筑/设计", "AI", "个性化", "其他",
    "剪辑", "音频", "图像", "设计", "办公", "学习", "网络", "系统",
    "安全", "驱动", "开发工具", "数据库", "聊天", "音乐", "阅读",
    "下载工具", "压缩解压", "远程控制", "虚拟机", "直播", "浏览器",
]

# 适用系统：可多选，一个都不选 = JSON 里不写该字段；取值/顺序来自 resource_schema.SYSTEMS
SYSTEM_PLATFORMS = list(resource_schema.SYSTEMS)

# CPU 架构：可多选；也允许自己输入别的写法
ARCHITECTURES = list(resource_schema.ARCHITECTURES)

# 开源仓库平台：选中后自动补前缀，填 owner/repo 即可；粘完整地址会去掉重复前缀
REPO_PLATFORMS = [
    ("github", "GitHub", "https://github.com/"),
    ("gitcode", "GitCode", "https://gitcode.com/"),
    ("gitee", "Gitee", "https://gitee.com/"),
    ("gitlab", "GitLab", "https://gitlab.com/"),
    ("custom", "自定义", ""),
    ("none", "不开源", ""),
]

FIELD_ORDER = list(resource_schema.FIELD_ORDER)

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".webp", ".svg")
# ⚠️ 过滤器文案要跟运行时界面语言走，所以做成函数而不是常量
_IMAGE_FILTER_FALLBACK = {
    "简体中文": ("Image files (*.png *.jpg *.jpeg *.gif *.ico *.bmp *.webp *.svg);;All files (*.*)"),
    "繁體中文": ("Image files (*.png *.jpg *.jpeg *.gif *.ico *.bmp *.webp *.svg);;All files (*.*)"),
    "English": ("Image files (*.png *.jpg *.jpeg *.gif *.ico *.bmp *.webp *.svg)"
                ";;All files (*.*)"),
}


def image_filter() -> str:
    """图片选择框的过滤器文案（按当前界面语言）"""
    try:
        from ..core.language_manager import get_current_manager
        manager = get_current_manager()
        if manager is not None:
            text = manager.get_text("maker", "image_filter")
            if text and text != "image_filter":
                return str(text)
            language = getattr(manager, "current_language", "简体中文")
            # 语言文件没这条 → 英文兜底
            return _IMAGE_FILTER_FALLBACK.get(
                language) or _IMAGE_FILTER_FALLBACK["English"]
    except Exception:
        pass
    return _IMAGE_FILTER_FALLBACK["English"]


# 兼容老代码当字符串用（英文那份，与上面兜底一致）
IMAGE_FILTER = _IMAGE_FILTER_FALLBACK["English"]

# 「上架时间」写成这种格式：好读、也能直接按字符串排序比较
LISTED_AT_FORMAT = "%Y-%m-%d %H:%M:%S"

# 自动备份放子目录，只保留最近 BACKUP_KEEP 份
BACKUP_DIR_NAME = "backups"
BACKUP_KEEP = 20

# 表单里标签列的宽度（左列定宽、右列控件才能行行对齐）
FORM_LABEL_WIDTH = 104


def find_project_root(start_dir: str, max_levels: int = 8) -> str:
    """向上找第一个含 .ToolsGCP 的目录（项目根），找不到返回空串

    取最靠近起点的那个，外层再有同名目录也不会找错。
    """
    current = os.path.abspath(start_dir)
    for _ in range(max(1, int(max_levels))):
        if os.path.isdir(os.path.join(current, ".ToolsGCP")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return ""


# 模块级缓存：进程内只算一次
PROJECT_ROOT = find_project_root(os.path.dirname(os.path.abspath(__file__)))

# 找不到项目根时的兜底目录
_FALLBACK_DIR = os.path.dirname(os.path.abspath(__file__))


def project_root() -> str:
    """项目根目录（含 .ToolsGCP 的那一层），找不到时退回本文件所在目录"""
    return PROJECT_ROOT or _FALLBACK_DIR


def resource_library_path(root: str = "") -> str:
    """本机资源库文件路径：<项目根>/.ToolsGCP/ToolsGCP-Resources.json

    ⚠️ 全程序只有这一个文件，制作器不会另生成一份。
    """
    base = root or project_root()
    if base:
        return os.path.join(base, RESOURCE_FILE_NAME)
    return os.path.join(_FALLBACK_DIR, "ToolsGCP-Resources.json")


def normalize_repo_url(platform_key: str, text: str) -> str:
    """整理成完整仓库地址

    选了平台：去掉重复前缀再补平台前缀；自定义：原样；不开源：返回空串。
    """
    text = str(text or "").strip()
    if platform_key == "none" or not text:
        return ""
    if platform_key == "custom":
        return text

    prefix = next((p for k, _n, p in REPO_PLATFORMS if k == platform_key), "")
    if not prefix:
        return text

    value = text
    # 去掉 http(s):// 和 www.
    value = re.sub(r"^https?://", "", value, flags=re.I)
    value = re.sub(r"^www\.", "", value, flags=re.I)
    # 去掉该平台域名（用户粘完整地址时）
    host = prefix.split("//", 1)[-1].rstrip("/")
    if value.lower().startswith(host.lower()):
        value = value[len(host):]
    value = value.lstrip("/")
    return f"{prefix}{value}" if value else ""


def detect_repo_platform(url: str) -> str:
    """根据完整地址反推平台，反推不出来算自定义"""
    url = str(url or "").strip().lower()
    if not url:
        return "none"
    for key, _name, prefix in REPO_PLATFORMS:
        if prefix and url.startswith(prefix.lower()):
            return key
    return "custom"


def now_listed_at() -> str:
    """生成「上架时间」，形如 2026-09-21 00:40:14（可直接按字符串排序）"""
    return datetime.now().astimezone().strftime(LISTED_AT_FORMAT)


def listed_at_sort_key(value) -> str:
    """把上架时间转成可排序的字符串（读不出来的排到最后）"""
    text = str(value or "").strip().replace("T", " ")
    return text[:19] if text else "9999-99-99 99:99:99"


# 最近一次备份失败原因（界面提示用）
_LAST_BACKUP_ERROR = [""]


def last_backup_error() -> str:
    """最近一次备份失败的原因（成功时是空串）"""
    return _LAST_BACKUP_ERROR[0]


def backup_library(path: str) -> str:
    """备份到 <目录>/backups/，只留最近 BACKUP_KEEP 份；返回备份路径，失败返回空串（不抛异常）

    ⚠️ 资源库偶尔被杀软/编辑器占住，所以重试 3 次。
    """
    folder = os.path.join(os.path.dirname(os.path.abspath(path)), BACKUP_DIR_NAME)
    _LAST_BACKUP_ERROR[0] = ""
    for _attempt in range(3):
        try:
            os.makedirs(folder, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            dest = os.path.join(folder, f"ToolsGCP-Resources.backup-{stamp}.json")
            if os.path.exists(dest):        # 同一秒内多次写入，加序号
                n = 2
                while os.path.exists(os.path.join(
                        folder, f"ToolsGCP-Resources.backup-{stamp}-{n}.json")):
                    n += 1
                dest = os.path.join(folder, f"ToolsGCP-Resources.backup-{stamp}-{n}.json")
            shutil.copyfile(path, dest)
            _prune_backups(folder)
            return dest
        except Exception as e:
            _LAST_BACKUP_ERROR[0] = str(e)
            time.sleep(0.15)
    return ""


def _prune_backups(folder: str):
    """备份只留最近的若干份"""
    try:
        files = sorted(f for f in os.listdir(folder)
                       if f.startswith("ToolsGCP-Resources.backup-") and f.endswith(".json"))
        for name in files[:-BACKUP_KEEP] if len(files) > BACKUP_KEEP else []:
            try:
                os.remove(os.path.join(folder, name))
            except Exception:
                pass
    except Exception:
        pass


def atomic_write_json(path: str, data: dict):
    """先写临时文件再替换，避免写一半被打断把资源库写坏"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write_json(path: str, data: dict):
    """写 JSON（原子写，见 atomic_write_json）"""
    atomic_write_json(path, data)


def load_library(path: str) -> dict:
    """读取资源库；不存在返回空结构"""
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("resources"), list):
                return data
        except Exception:
            pass
    return {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "name": "ToolsGCP Resources",
            "description": "ToolsGCP 资源索引文件",
            "icon_dir": ICON_DIR_NAME,
            "updated_at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
        },
        "resources": [],
    }


def next_code(resources: list, prefix: str = "TG-") -> str:
    """分配下一个可用编码（6 位数字，例如 TG-000041）"""
    max_no = 0
    used = set()
    for item in resources:
        code = str(item.get("code") or "")
        if not code:
            continue
        used.add(code.upper())
        m = re.match(rf"^{re.escape(prefix)}(\d+)$", code.upper())
        if m:
            max_no = max(max_no, int(m.group(1)))
    no = max_no + 1
    while f"{prefix}{no:06d}" in used:
        no += 1
    return f"{prefix}{no:06d}"


def resolve_i18n_for_maker(value) -> str:
    """把可能是多语言字典的字段取一个能编辑的字符串（制作器用）"""
    if not isinstance(value, dict):
        return str(value or "")
    for key in ("简体中文", "繁體中文", "English"):
        v = value.get(key)
        if isinstance(v, str) and v.strip():
            return v
    for v in value.values():
        if isinstance(v, str) and v.strip():
            return v
    return ""


def slugify(name: str) -> str:
    """把名称转成 id：小写 + 连字符"""
    text = str(name or "").strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"[^a-z0-9\-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text


def split_tags(text: str) -> list:
    """标签输入框 → 列表（逗号/顿号/分号/竖线/空格都算分隔符）"""
    parts = re.split(r"[,，、;；|\s]+", str(text or ""))
    return [p.strip() for p in parts if p.strip()]


def split_categories(text) -> list:
    """类别输入框 → 列表（分隔符与 schema 一致）

    ⚠️ 只认 `, ， 、 ; ；`，不拆 `/` 和空格 ——「建筑/设计」是完整类别。
    """
    return resource_schema.parse_categories(text)


def as_list(value) -> list:
    """把 JSON 里的字段统一成列表（数组原样，单个字符串包一层，空值给空表）"""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()] if str(value).strip() else []


def auto_http_url(text: str) -> str:
    """链接兜底：只写 example.com 也能存成 https://example.com；留空返回空串"""
    value = str(text or "").strip()
    if not value or re.match(r"^https?://", value, re.I):
        return value
    return f"https://{value.lstrip('/')}"


def icon_base_from_name(name: str, fallback: str = "icon") -> str:
    """用「名称」当图片文件名（不含扩展名）

    去掉 Windows 非法字符；去掉后为空就退回 fallback（一般是资源 id）。
    """
    text = str(name or "").strip()
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", text)
    text = text.strip().rstrip(". ")
    return text or (str(fallback or "").strip() or "icon")


def unique_name_in(dest_dir: str, stem: str, ext: str) -> str:
    """在目录里找一个不冲突的文件名（冲突就加 -2 / -3 …）"""
    candidate = f"{stem}{ext}"
    n = 2
    while os.path.exists(os.path.join(dest_dir, candidate)):
        candidate = f"{stem}-{n}{ext}"
        n += 1
    return candidate


def copy_icon(src: str, dest_dir: str, preferred_name: str) -> str:
    """把图标复制到目标目录，返回最终文件名"""
    os.makedirs(dest_dir, exist_ok=True)
    base = os.path.basename(src)
    stem, ext = os.path.splitext(base)
    ext = ext.lower() or ".png"

    # 优先用 <id><ext>，避免同名资源互相覆盖
    safe_stem = re.sub(r"[^A-Za-z0-9_\-]+", "", preferred_name) or stem or "icon"
    candidates = [f"{safe_stem}{ext}", base]
    for name in candidates:
        dest = os.path.join(dest_dir, name)
        if not os.path.exists(dest):
            shutil.copyfile(src, dest)
            return name
        try:
            if os.path.getsize(dest) == os.path.getsize(src):
                with open(dest, "rb") as f1, open(src, "rb") as f2:
                    if f1.read() == f2.read():
                        return name        # 内容一样，直接复用
        except Exception:
            pass

    # 都冲突：加时间戳
    stamp = datetime.now().strftime("%H%M%S")
    name = f"{safe_stem}-{stamp}{ext}"
    shutil.copyfile(src, os.path.join(dest_dir, name))
    return name


def is_dark_mode() -> bool:
    """当前是不是深色主题（qfluentwidgets 的全局状态）"""
    from qfluentwidgets import isDarkTheme
    return bool(isDarkTheme())


def theme_tokens(dark: bool = None) -> dict:
    """取色板：dark=None 时按当前主题，传了就按传的来（见 settings/theme.py）"""
    return tokens(is_dark_mode() if dark is None else bool(dark))


def themed_scrollbar_qss(dark: bool = None) -> str:
    """细圆角滚动条 QSS，颜色跟主题走（取自 design token）

    ⚠️ 只能设在滚动条自己身上：写在 QScrollArea 上会顶掉所有子控件的样式。
    """
    c = theme_tokens(dark)
    track = "transparent"
    handle = c["text_disabled"]
    hover = c["text_secondary"]
    pressed = c["icon"]
    return f"""
        QScrollBar:vertical {{
            background: {track}; width: 10px; margin: 0px;
            border-radius: 5px; border: none;
        }}
        QScrollBar::handle:vertical {{
            background: {handle}; min-height: 36px; border-radius: 5px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {hover}; }}
        QScrollBar::handle:vertical:pressed {{ background: {pressed}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px; background: none; border: none;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
        }}
        QScrollBar:horizontal {{
            background: {track}; height: 10px; margin: 0px;
            border-radius: 5px; border: none;
        }}
        QScrollBar::handle:horizontal {{
            background: {handle}; min-width: 36px; border-radius: 5px;
        }}
        QScrollBar::handle:horizontal:hover {{ background: {hover}; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px; background: none; border: none;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: none;
        }}
    """


def apply_themed_scrollbar(widget) -> None:
    """给 QScrollArea 套上主题化滚动条（⚠️ 只能设在滚动条自己身上，见上）"""
    if widget is None:
        return
    qss = themed_scrollbar_qss()
    widget.verticalScrollBar().setStyleSheet(qss)
    widget.horizontalScrollBar().setStyleSheet(qss)


def accent_color_applied(dark: bool = None) -> bool:
    """qfluentwidgets 的全局强调色已经是本程序要的那个了吗

    ⚠️ setThemeColor() 会无条件 updateStyleSheet()，重渲染全部已注册控件，
    实测约 800ms（就是用户看到的"未响应"），所以先问再调；dark=None 按当前主题算。
    """
    try:
        from PyQt5.QtGui import QColor
        from qfluentwidgets import qconfig
    except Exception:
        return False            # 取不到库状态就照常去灌一次
    want = QColor(theme_tokens(dark)["accent"])
    try:
        current = qconfig.get(qconfig.themeColor)
    except Exception:
        return False
    return isinstance(current, QColor) and current == want


def card_qss(dark: bool = None) -> str:
    """卡片描边样式（背景由 qfluentwidgets 自己画）；圆角统一 SIZES["card_radius"]"""
    c = theme_tokens(dark)
    return (f"QFrame[role=\"makerCard\"] {{ border: 1px solid {c['card_border']};"
            f" border-radius: {SIZES['card_radius']}px; }}")


def host_value(host, name: str, default=""):
    """从宿主对象上取值：属性、无参方法都支持，没有就用默认值

    页面统一走这个（宿主适配器见 resource_maker_interface.ResourceMakerHost）。
    """
    if host is None:
        return default
    value = getattr(host, name, None)
    if value is None:
        return default
    if callable(value):
        try:
            return value()
        except Exception:
            return default
    return value


def host_call(host, name: str, *args, **kwargs):
    """调用宿主上的可选钩子（宿主没实现这个方法就安静跳过，不抛异常）"""
    if host is None:
        return None
    method = getattr(host, name, None)
    if not callable(method):
        return None
    try:
        return method(*args, **kwargs)
    except Exception:
        return None


__all__ = [
    "SCHEMA_VERSION", "ICON_DIR_NAME", "RESOURCE_FILE_NAME", "CATEGORIES",
    "SYSTEM_PLATFORMS", "ARCHITECTURES", "REPO_PLATFORMS", "FIELD_ORDER",
    "IMAGE_EXTS", "IMAGE_FILTER", "LISTED_AT_FORMAT",
    "BACKUP_DIR_NAME", "BACKUP_KEEP", "FORM_LABEL_WIDTH", "PROJECT_ROOT",
    "find_project_root", "project_root", "resource_library_path",
    "normalize_repo_url", "detect_repo_platform", "now_listed_at",
    "listed_at_sort_key", "backup_library", "last_backup_error",
    "atomic_write_json", "write_json", "load_library", "next_code",
    "resolve_i18n_for_maker", "slugify", "split_tags", "split_categories", "as_list",
    "auto_http_url", "icon_base_from_name", "unique_name_in", "copy_icon",
    "is_dark_mode", "theme_tokens", "themed_scrollbar_qss",
    "apply_themed_scrollbar", "accent_color_applied", "card_qss",
    "host_value", "host_call",
]
