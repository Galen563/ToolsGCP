"""设置页配色与尺寸规范（设计 token）—— 设置页唯一允许写颜色字面量的地方。

所有卡片 / 控件 / 行样式都从这里取色取尺寸，不要再各自写 `#F5F5F5` 这种值。
设计原则：对比靠描边不靠投影；全程序一套强调色（ACCENT，靠 setThemeColor 灌给 qfluentwidgets）；
尺寸成体系（行高 48、卡片内边距 20、控件宽 200、内容最大宽 880）。

用法：c = tokens(dark) 取色板；apply_accent_color(dark) 在切主题时调一次。
"""

from PyQt5.QtGui import QColor

# 强调色（全程序唯一的交互强调色）
ACCENT = "#4F7BF7"
# 深色主题下强调色要亮一档，否则会"糊"在深底上
ACCENT_DARK = "#6E93FF"
# 品牌渐变（用户气泡、悬浮球、发送按钮用的那套，设置页不直接用但保持一致）
BRAND_GRADIENT = ("#5B8DEF", "#8A6BEF")

# ---------- 组件配色（三选一，设置 → 外观 → 组件配色）----------
# 一个档位决定"组件"的颜色：强调色（灌给 qfluentwidgets → 开关 / 下拉框选中项 / 滑块 /
# 勾选框 / 进度条，以及 tokens 里的 accent / accent_soft）和品牌渐变（气泡 / 发送按钮，由 color 现算）。
# ⚠️ 只给一个颜色、深浅色不各写一套：库在深色下会把 PRIMARY 换成 v=1, s*0.84 的版本
# （见 style_sheet.ThemeColor.color），所以这里给的是"浅色下看到的那个色"，深色由库提亮。
# ⚠️ AI 悬浮球完全不跟这个颜色走：球体背景和液面固定成原来那套蓝紫，换配色时一动不动。
ACCENT_PRESETS = {
    "blue": {"color": "#009FAA"},
    "purple": {"color": "#8B6CF6"},
    "orange": {"color": "#D97757"},
}

DEFAULT_ACCENT_KEY = "blue"

# 悬浮球背景：**固定不变**（需求："AI 悬浮球现在改为主题不变"）
BALL_GRADIENT = ("#5B8DEF", "#8A6BEF")
BALL_GRADIENT_HOVER = ("#6E9BFF", "#9B7FFF")
BALL_GRADIENT_PRESSED = ("#4A7AD9", "#7858DF")

# 球里那层"流动液面"的颜色 (亮色, 深色)：恒定，不跟组件配色变
BALL_LIQUID_BRIGHT = "#7FD4FF"
BALL_LIQUID_DEEP = "#6C5CE7"

# 当前生效的那一档（模块级状态：很多地方只拿得到颜色，拿不到 settings_manager）
_current_accent_key = DEFAULT_ACCENT_KEY


def accent_key() -> str:
    """当前生效的组件配色档位（blue / purple / orange）"""
    return _current_accent_key


def set_accent_key(key: str) -> str:
    """设置当前档位（认不出来就退回默认，返回真正生效的那个）"""
    global _current_accent_key
    _current_accent_key = key if key in ACCENT_PRESETS else DEFAULT_ACCENT_KEY
    return _current_accent_key


def accent_preset(key: str = None) -> dict:
    """取某一档（不传就是当前档）的色值表"""
    return ACCENT_PRESETS.get(key or _current_accent_key,
                              ACCENT_PRESETS[DEFAULT_ACCENT_KEY])


def accent_base_color() -> str:
    """当前档位的"原始"强调色（浅色下看到的那个、也是灌给库的那个）"""
    return accent_preset()["color"]


def _brighten_for_dark(color) -> str:
    """深色主题下强调色实际显示成什么（照抄库的算法：s *= 0.84, v = 1）。"""
    c = QColor(color)
    h, s, v, a = c.getHsvF()
    return QColor.fromHsvF(h, min(1.0, max(0.0, s * 0.84)), 1.0, a).name()


def accent_color(dark: bool = False) -> str:
    """当前档位在浅色 / 深色主题下的强调色。

    ⚠️ 灌给 qfluentwidgets 的一律是 accent_base_color()（浅色那一版），深色由库自己提亮；
    这个函数主要给"设置页 token / 状态小字"这类需要自己上色的地方用。
    """
    base = accent_base_color()
    return _brighten_for_dark(base) if dark else base


def brand_gradient(hover: bool = False, pressed: bool = False) -> tuple:
    """当前档位的品牌渐变（用户气泡 / 发送按钮；常态 / 悬停 / 按下）"""
    base = QColor(accent_base_color())
    if pressed:
        return (base.darker(112).name(), base.lighter(105).name())
    if hover:
        return (base.lighter(112).name(), base.lighter(132).name())
    return (base.name(), base.lighter(118).name())


def ball_gradient(hover: bool = False, pressed: bool = False) -> tuple:
    """AI 悬浮球的背景渐变 —— 恒定的品牌蓝紫，不跟组件配色变。"""
    if pressed:
        return BALL_GRADIENT_PRESSED
    if hover:
        return BALL_GRADIENT_HOVER
    return BALL_GRADIENT


def ball_liquid_colors() -> tuple:
    """AI 悬浮球里那层"动态液面"的颜色 (亮色, 深色) —— 同样恒定，不跟组件配色（原来是跟着变的）。"""
    return (BALL_LIQUID_BRIGHT, BALL_LIQUID_DEEP)


def brand_gradient_qss(horizontal: bool = True, hover: bool = False,
                       pressed: bool = False, vertical: bool = False) -> str:
    """品牌渐变的 QSS 写法（给 QPushButton / QLabel 的 background 用）"""
    start, end = brand_gradient(hover=hover, pressed=pressed)
    if vertical:
        return (f"qlineargradient(x1:0, y1:0, x2:0, y2:1,"
                f" stop:0 {start}, stop:1 {end})")
    return (f"qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            f" stop:0 {start}, stop:1 {end})")


def brand_link_color() -> str:
    """品牌链接色（AI 面板里的可点文字）：跟着当前档位走"""
    return accent_base_color()


def _soft(color: str, alpha: float, dark: bool) -> str:
    """把强调色转成"淡底"用的 rgba（设置页选中行 / 徽标底）"""
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"

# ---------- 浅色 ----------
LIGHT = {
    "page": "#F3F4F7",          # 整页背景（略偏冷，白卡片浮得起来）
    "card": "#FFFFFF",          # 卡片背景
    "card_border": "#E6E9F0",   # 卡片描边（让卡片"看得见"的关键）
    "text": "#1F2329",          # 主文字：行标题、板块名
    "text_secondary": "#6B7280",  # 次文字：副说明、单位、路径
    "text_disabled": "#9AA1AC",   # 弱文字：占位符、禁用
    "divider": "#EFF1F5",       # 卡片内的行分隔线
    "icon": "#4B4F58",          # 图标
    "accent": ACCENT,
    "accent_soft": "rgba(79, 123, 247, 0.10)",   # 选中行 / hover 的浅底
    "hover": "rgba(0, 0, 0, 0.04)",
    "danger": "#E5484D",
    "success": "#2FA36B",
    "warning": "#D98E04",
}

# ---------- 深色 ----------
# ⚠️ 深色这套必须是中性灰、不能带蓝紫（需求："设置中深色主题下还是蓝紫色背景是不对的"）：
# 原来是 #1B1D24 / #23262F 这种偏冷的蓝灰，整页发紫，和 qfluentwidgets 的深色底 #202020 也对不上
DARK = {
    "page": "#1C1C1C",
    "card": "#272727",
    "card_border": "#343434",
    "text": "#E8E8E8",
    "text_secondary": "#A0A0A0",
    "text_disabled": "#6E6E6E",
    "divider": "#2E2E2E",
    "icon": "#C9C9C9",
    # 强调色仍然是品牌蓝（开关 / 选中项 / 链接用它）—— 那是主题强调色，不是背景色
    "accent": ACCENT_DARK,
    "accent_soft": "rgba(110, 147, 255, 0.16)",
    "hover": "rgba(255, 255, 255, 0.06)",
    "danger": "#F16A6E",
    "success": "#4CC46A",
    "warning": "#E0A33A",
}

# ---------- 尺寸 ----------
SIZES = {
    "content_max_width": 880,   # 内容区最大宽度（居中，两侧自动留白）
    "content_margin": 30,       # 内容区左右最小留白
    "section_gap": 32,          # 板块与板块之间
    "card_gap": 16,             # 同板块内卡片之间
    "card_padding": 20,         # 卡片上下左右内边距
    "card_radius": 10,          # 卡片圆角
    "row_height": 48,           # 单行高度（带副说明的那行 60）
    "row_height_with_desc": 60,
    "control_width": 200,       # 输入框/下拉框统一宽度
    "sidebar_width": 196,       # 左侧板块列表宽度
}

# 常用控件的固定宽度（卡片里统一用这个，不要各写各的）
CONTROL_WIDTH = SIZES["control_width"]


def accent_color_applied(dark: bool = False) -> bool:
    """当前 qfluentwidgets 的强调色是不是已经是这一档了（避免把同一个颜色又灌一遍）。

    ⚠️ 比的是存进去的那个原始色（qconfig._cfg.themeColor），不是 themeColor()：后者在深色下被库
    换成 v=1 的提亮版，拿它比会永远不相等 —— 于是每次切主题都要白刷一遍全程序样式表。
    """
    try:
        from qfluentwidgets.common.config import qconfig
        current = qconfig.get(qconfig._cfg.themeColor)
        return QColor(current).name().lower() == accent_base_color().lower()
    except Exception:
        return False


def apply_accent_color(dark: bool = False, lazy: bool = True):
    """把当前档位的强调色灌给 qfluentwidgets（切主题 / 换配色时调一次）。

    调完这一句，SwitchButton 打开态、ComboBox 选中项、Slider、CheckBox、ProgressBar 这些
    库内置控件全都会自动变成品牌色，不用一个个 setStyleSheet（那才是和库的主题机制打架）。
    ⚠️ 两个性能要点：颜色没变就直接返回（setThemeColor 末尾会无条件重刷全程序已注册控件，实测 ~520ms）；
    用 lazy=True（只立刻重刷当前可见的控件，藏着的打 dirty-qss、等被画出来时由库自己补刷，外观无差别）。
    """
    try:
        from qfluentwidgets import setThemeColor
        if accent_color_applied(dark):
            return
        # ⚠️ 灌的是原始色：深色主题下由库自己换成 v=1 的提亮版（见 ACCENT_PRESETS）
        setThemeColor(accent_base_color(), save=False, lazy=lazy)
    except Exception:
        pass


def tokens(dark: bool = False) -> dict:
    """取当前主题的色板（浅色/深色各一套，键名完全一致）。

    ⚠️ accent / accent_soft 跟着"组件配色"档位走：设置页左侧选中项、卡片序号徽标、行内强调文字
    都用这两个键，换了配色它们要跟着变，否则会出现"组件是橙色、设置页还是蓝色"的分裂。
    """
    base = dict(DARK if dark else LIGHT)
    accent = accent_color(dark)
    base["accent"] = accent
    base["accent_soft"] = _soft(accent, 0.16 if dark else 0.10, dark)
    return base


def panel_stylesheet(dark: bool) -> str:
    """设置页的整页样式表（页面底、卡片、标题、说明文字）。

    ⚠️ 只写"类名级"的规则，不要给具体控件写 objectName 选择器 —— 那样每加一个控件就要回来改这里，
    而且很容易和 qfluentwidgets 自己的主题样式互相覆盖。
    """
    c = tokens(dark)
    return f"""
        /* ⚠️ 背景：设置页**不自己铺整页底色**，跟别的页面一样交给主窗口。
           需求原话："公告和设置的背景去除 像其他页面一样"。
           （左侧板块列表、右侧滚动区、视口都跟着透明，
           卡片自己那层底色仍然保留 —— 那才是"卡片"。） */
        SettingsInterface {{
            background: transparent;
        }}
        QWidget#settingsSidebar {{
            background: transparent;
            border: none;
        }}
        /* 右侧内容区：一整页滚动，里面的每一块都是透明的 */
        QWidget#settingsHost, QWidget#settingsContent {{
            background-color: transparent;
        }}
        QScrollArea, QWidget#qt_scrollarea_viewport {{
            border: none;
            background: transparent;
        }}
        SimpleCardWidget {{
            background-color: {c['card']};
            border: 1px solid {c['card_border']};
            border-radius: {SIZES['card_radius']}px;
        }}
        BodyLabel, SubtitleLabel, StrongBodyLabel, CaptionLabel {{
            color: {c['text']};
        }}
        /* ⚠️ 行内的标题/副说明/置灰全部用**属性选择器**。
           以前是每个 SettingRow 给自己 setStyleSheet 一次 —— 一页 600 多个控件
           就是 600 多份私有样式表，Qt 每次布局/重绘都要逐控件跑一遍 CSS 匹配，
           设置页因此明显发滞。集中在这里定义一次，全页共享同一份规则。 */
        QLabel[role="rowTitle"] {{
            color: {c['text']};
            font-size: 14px;
            background: transparent;
        }}
        QLabel[role="rowDesc"] {{
            color: {c['text_secondary']};
            font-size: 12px;
            background: transparent;
        }}
        QLabel[disabledText="true"] {{
            color: {c['text_disabled']};
        }}
    """
