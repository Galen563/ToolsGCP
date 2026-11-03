"""字体工具模块

设置页「外观 → 字体」的后端：列可选字体、把选中的字体铺到整个程序。字体要在主窗口
建控件之前生效，所以单独一个模块。

⚠️ 默认值用空字符串表示"没设置过"：`QApplication.setFont(QFont())` 不会把字体还原成
   系统默认，"跟随系统"只能靠撤掉自定义字体实现。
"""

from PyQt5.QtGui import QFont, QFontDatabase
from PyQt5.QtWidgets import QApplication

# 设置项里的键名（toolsgcp.config）
SETTING_KEY = "ui_font_family"

# 默认字体候选（按优先级）：没有"跟随系统"这一项，取第一个装得上的无衬线字体
DEFAULT_FONT_CANDIDATES = ("微软雅黑", "Microsoft YaHei UI", "等线", "DengXian",
                           "Segoe UI", "Arial")
# 候选表里的显示名（已废弃，保留给老调用点；它是写死的简中，别拿去填界面）
DEFAULT_FONT_LABEL = "微软雅黑"

# 常用字体候选：(设置里存的值, 语言文件 key, 别名)。
# ⚠️ 第二项是语言 key、不能写死中文，否则切 English / 繁體中文时下拉框还是简中。
COMMON_FONTS = [
    ("微软雅黑", "font_label_default", "Microsoft YaHei UI"),
    # "Microsoft YaHei UI" 与"微软雅黑"是同一套字体，不再单列第二项
    # （resolve_family 仍认这个别名，老配置存着它也能解析）
    ("等线", "font_label_dengxian", "DengXian"),
    ("Segoe UI", "font_label_segoe", "微软雅黑"),
    ("SimSun", "font_label_simsun", "宋体"),
    ("SimHei", "font_label_simhei", "黑体"),
    ("KaiTi", "font_label_kaiti", "楷体"),
    ("FangSong", "font_label_fangsong", "仿宋"),
    ("Consolas", "font_label_consolas", "Courier New"),
    ("JetBrains Mono", "font_label_jetbrains", "Consolas"),
]

# 语言文件里查不到时的英文兜底（和语言 JSON 的 English 一列保持一致）
_FONT_LABEL_EN = {
    "font_label_default": "Microsoft YaHei",
    "font_label_dengxian": "DengXian",
    "font_label_segoe": "Segoe UI",
    "font_label_simsun": "SimSun",
    "font_label_simhei": "SimHei",
    "font_label_kaiti": "KaiTi",
    "font_label_fangsong": "FangSong",
    "font_label_consolas": "Consolas (monospace)",
    "font_label_jetbrains": "JetBrains Mono (monospace)",
}


def font_label(key: str, fallback: str = "") -> str:
    """字体下拉框里的显示名（按当前界面语言）

    ⚠️ 必须走当前语言管理器：LanguageManager 每次 new 都重读全部 json，而且新实例不知道
       用户选的语言，会一律退回简体中文。
    """
    key = str(key or "")
    if not key:
        return fallback
    try:
        from ..core.language_manager import get_current_manager
        manager = get_current_manager()
        if manager is not None:
            text = manager.get_text("settings", key)
            if text and text != key:
                return str(text)
    except Exception:
        pass
    return fallback or _FONT_LABEL_EN.get(key, key)


_cache_families = None
# 应用**原始**字体（第一次改字体之前抓一份）
# ⚠️ 必须自己留底：`QApplication.setFont(QFont())` 不会把字体还原成系统默认
_default_font = None


def dark_default_family() -> str:
    """默认字体族名：候选表里第一个系统装了的；都装不上返回空串（用 Qt 默认字体）"""
    families = installed_families()
    lowered = {f.lower(): f for f in families}
    for name in DEFAULT_FONT_CANDIDATES:
        if name in families:
            return name
        if name.lower() in lowered:
            return lowered[name.lower()]
    return ""


def _snapshot_default_font():
    global _default_font
    if _default_font is not None:
        return _default_font
    app = QApplication.instance()
    if app is None:
        return None
    _default_font = QFont(app.font())
    return _default_font


def installed_families() -> list:
    """系统已安装的字体族名（结果缓存：QFontDatabase 查询一次要几毫秒）"""
    global _cache_families
    if _cache_families is None:
        try:
            _cache_families = list(QFontDatabase().families())
        except Exception:
            _cache_families = []
    return _cache_families


def resolve_family(name: str) -> str:
    """把设置里存的字体名解析成系统真正认识的族名（传空 / 找不到 → 默认字体）"""
    name = str(name or "").strip()
    if not name:
        return dark_default_family()
    families = installed_families()
    if name in families:
        return name
    # 再用候选表里的别名试一次（中英文名互为别名）
    lowered = {f.lower(): f for f in families}
    for key, _label, alias in COMMON_FONTS:
        if key and key.lower() == name.lower():
            for candidate in (key, alias):
                if candidate in families:
                    return candidate
                if candidate.lower() in lowered:
                    return lowered[candidate.lower()]
    return dark_default_family()


# 同一套字体的"别名"归并表：键是去掉空格/连字符/下划线并转小写的名字。
# ⚠️ "微软雅黑"和"Microsoft YaHei UI"是同一套字体，必须按实体去重，
#    否则下拉框里会出现两条一模一样的字体。
_FAMILY_ALIASES = {
    "microsoftyahei": "microsoftyahei",
    "microsoftyaheiui": "microsoftyahei",
    "微软雅黑": "microsoftyahei",
    "simsun": "simsun", "宋体": "simsun", "nsimsun": "simsun",
    "simhei": "simhei", "黑体": "simhei",
    "kaiti": "kaiti", "楷体": "kaiti",
    "fangsong": "fangsong", "仿宋": "fangsong",
    "dengxian": "dengxian", "等线": "dengxian",
    "consolas": "consolas",
}


def _family_key(name: str) -> str:
    """字体族的"实体"标识（中文名/英文名归到同一个键）"""
    normalized = "".join(str(name or "").split()).replace("-", "").replace("_", "")
    return _FAMILY_ALIASES.get(normalized.lower(), normalized.lower())


def available_fonts() -> list:
    """[(设置里存的值, 下拉框显示的文字), ...]

    先列候选表里系统确实装了的，再把其它系统字体按字母序接上；
    默认字体永远排第一，没有"跟随系统"这一项。
    """
    families = installed_families()
    result = []
    seen = set()          # 已经列过的"字体实体"（见 _family_key）
    default = dark_default_family()
    for key, label_key, alias in COMMON_FONTS:
        resolved = key if key in families else (alias if alias in families else "")
        identity = _family_key(resolved)
        if resolved and identity not in seen:
            seen.add(identity)
            # 显示名按当前界面语言解析
            result.append((resolved, font_label(label_key)))
            # 同一套字体的另一个名字也记上，下面那个循环才不会重复列出来
            seen.add(_family_key(key))
            seen.add(_family_key(alias))
    # 其它系统字体（按名字排序，跳过已经列过的）
    for family in sorted(families, key=lambda s: s.lower()):
        if family.startswith("@"):            # @ 开头是竖排变体，别列
            continue
        identity = _family_key(family)
        if identity in seen:
            continue
        seen.add(identity)
        result.append((family, family))
    return result


def apply_font(family: str = None):
    """把字体铺到整个程序（family 传空 / 解析不到 → 用默认字体）；返回真正生效的族名"""
    app = QApplication.instance()
    if app is None:
        return ""
    if family is None:
        family = ""
    resolved = resolve_family(family)
    if not resolved:
        # 连默认候选都装不上（罕见）：撤掉自定义字体，交给 Qt 自己挑
        default = _snapshot_default_font()
        app.setFont(QFont(default) if default is not None else QFont())
        return ""
    font = QFont(resolved)
    font.setPointSize(max(9, app.font().pointSize()))   # 字号保持不变
    app.setFont(font)
    set_current_family(resolved)
    _apply_qfluent_font_families(resolved)
    # ⚠️ 光调 app.setFont() 是不够的，见 _restyle_existing_widgets 的说明
    _restyle_existing_widgets(resolved)
    _schedule_restyle(resolved)
    return resolved


def _schedule_restyle(resolved: str):
    """稍后再补刷几遍（有的控件在刷完之后才被样式表重新 polish）

    ⚠️ qfluentwidgets 有部分控件收到 StyleChange 后会重新套用它建时生成的那份样式表
       （里面带着旧的字体族），刚刷完的又被打回原样，补刷两遍才收敛。
    """
    try:
        from PyQt5.QtCore import QTimer
    except Exception:
        return
    for delay in (0, 60, 240):
        QTimer.singleShot(delay, lambda r=resolved: _apply_scheduled_restyle(r))


def _apply_scheduled_restyle(resolved: str):
    """补刷的那一次（先确认"要刷的字体"还是当前那个）

    ⚠️ 用户连点两下字体下拉框时，第一次的延迟任务会晚于第二次的赋值执行 ——
       不校验就会把界面刷回上一个字体（看着像"切了又弹回去"）。
    """
    if resolved != _current_family:
        return
    _restyle_existing_widgets(resolved)
    # 再收一次"样式表里写死了字体"的漏网之鱼
    _refresh_qfluent_stylesheets(resolved)


def _refresh_qfluent_stylesheets(resolved: str) -> int:
    """把 qfluentwidgets 自己生成过的样式表按新字体重新渲染一遍

    ⚠️ 部分控件的字体来自它自己生成的样式表（模板里的 `$FontFamilies` 在 apply() 那刻就
       渲染成了写死的字体名），而样式表里的 font 优先级**高于** widget.setFont() —— 上层
       那轮 setFont 对它们是白做的。这里借 styleSheetManager 重新渲染。

    ⚠️ 只处理"字体还没换过来"的控件：重新 setStyleSheet 会覆盖控件自己设过的自定义样式。
    """
    try:
        from qfluentwidgets.common.style_sheet import styleSheetManager
    except Exception:
        return 0
    fixed = 0
    for widget, source in list(styleSheetManager.items()):
        try:
            font = widget.font()
            families = font.families() or [font.family()]
        except (RuntimeError, TypeError):
            continue
        if families and families[0] == resolved:
            continue
        try:
            source.apply(widget)
            fixed += 1
        except Exception:
            continue
    if fixed:
        # 样式表重刷之后字体链会变，再走一遍 setFont 兜底
        _restyle_existing_widgets(resolved)
    return fixed


def _apply_qfluent_font_families(resolved: str):
    """把字体族同步给 qfluentwidgets 的全局字体配置

    ⚠️ 它有自己的 fontFamilies，一部分控件（标题/图表标签）走 common/font.getFont()
       取字体、完全不看 QApplication.setFont()，不设这里就会留下十几处"切了字体却没变"。
       save=False：不往磁盘写它的配置。
    """
    try:
        from qfluentwidgets import setFontFamilies
        setFontFamilies([resolved], save=False)
    except Exception:
        pass


# ========== 全程序统一字体族（ui_font） ==========
# ⚠️ 程序里到处是 `QFont("Microsoft YaHei", 12, QFont.Bold)` 这种写死字体族的写法，
#    而 `QApplication.setFont()` 只影响"没自己设过字体"的控件 —— 所以界面文字一律
#    走 `ui_font()`，它按当前选中的字体族取字体：
#         label.setFont(ui_font(12, bold=True))
_current_family = ""

# 被"接管"过的字体族名（默认字体 + 用户历次选过的）。
# 换字体时只动这些，**不动** Consolas 这类刻意写死的等宽字体。
_managed_families = set()

# 这些"界面字体"也一并接管：qfluentwidgets 内部有少量控件自己写死了
# Segoe UI 等，不跟着换就会留下几处"没变"的漏网之鱼。
_MANAGED_FAMILY_EXTRAS = ("Segoe UI", "Microsoft YaHei UI", "等线", "DengXian")
for _extra in _MANAGED_FAMILY_EXTRAS:
    _managed_families.add(_extra)


def set_current_family(family: str):
    """记下当前生效的字体族（apply_font 内部会调；单测里也可以手动设）"""
    global _current_family
    _current_family = str(family or "")
    if _current_family:
        _managed_families.add(_current_family)
    return _current_family


def current_family() -> str:
    """当前生效的界面字体族（没设过就取默认候选里第一个装得上的）"""
    global _current_family
    if not _current_family:
        set_current_family(dark_default_family())
    return _current_family


def ui_font(size: int = None, weight=None, bold: bool = False,
            italic: bool = False, family: str = None) -> QFont:
    """按当前界面字体造一个 QFont（参数对齐 QFont(family, pointSize, weight)；字号不传就用当前字号）"""
    app = QApplication.instance()
    resolved = family or current_family()
    font = QFont(resolved) if resolved else QFont()
    point = size
    if point is None and app is not None:
        point = app.font().pointSize()
    if point and point > 0:
        font.setPointSize(int(point))
    if bold:
        font.setBold(True)
    if weight is not None:
        font.setWeight(int(weight))
    if italic:
        font.setItalic(True)
    return font


def _restyle_existing_widgets(resolved: str) -> int:
    """把已经建出来的控件上的字体族换成新的（切字体立刻生效的关键）

    ⚠️ 必须遍历：控件一旦 setFont(QFont(...)) 过就不再跟随 QApplication.setFont()，这是 Qt
       的既定行为（应用字体只是"没设过时的默认值"）。只替换族名，字号/粗细/斜体原样保留。
    """
    app = QApplication.instance()
    if app is None or not resolved:
        return 0
    changed = 0
    for widget in app.allWidgets():
        try:
            font = widget.font()
            families = font.families() or [font.family()]
        except (RuntimeError, TypeError):
            continue
        if not families or families[0] == resolved:
            continue
        # ⚠️ 用 families() 而不是 family()：qfluentwidgets 控件拿到的是
        #    setFamilies(['Segoe UI', ...]) 这种列表，只看 family() 会漏掉它们
        if not any(f in _managed_families for f in families if f):
            continue
        font.setFamilies([resolved])
        try:
            widget.setFont(font)
            changed += 1
        except RuntimeError:
            continue
    return changed
