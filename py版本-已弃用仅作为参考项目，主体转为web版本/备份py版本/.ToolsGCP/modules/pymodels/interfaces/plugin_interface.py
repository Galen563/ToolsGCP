"""插件界面：卡片式列出 .ToolsGCP/plugins 下的插件，可以打开 / 启停 / 删除。

右上角「我想开发」给开发者一份上手说明。
"""

import os
import shutil
import time

from PyQt5.QtCore import (QAbstractAnimation, QEasingCurve, QEvent,
                          QPropertyAnimation, QSize, QTimer, Qt, pyqtSignal)
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
    QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, FluentIcon as FIF, IndeterminateProgressRing, InfoBar,
    InfoBarPosition, LineEdit, MessageBox, MessageBoxBase, PrimaryPushButton,
    PushButton, SearchLineEdit, SegmentedToolWidget, SimpleCardWidget,
    StrongBodyLabel, SubtitleLabel, TextEdit, TransparentToolButton, isDarkTheme,
)

from ..widgets.responsive_grid import ResponsiveGrid
from ..ui.custom_widgets import ToggleSwitch
from .settings.theme import tokens

from ..core.plugin_manager import (
    STATUS_DISABLED, STATUS_ERROR, STATUS_OK, PluginManager,
)

# 卡片尺寸（宽度由网格按算，不写死）
CARD_W = 300          # 基准/最小宽度
CARD_H = 178
GRID_SPACING = 14

# 「备注」和它右边状态徽章之间留的空隙（间距越大备注越靠左，这一排是靠右排的）
NOTE_GAP_TO_BADGE = 220

# 卡片上那两个图标按钮的总开关（true / false 可自定义）
# ⚠️ 只控制"显示与否"；想彻底屏蔽删除还要看 _on_card_delete —— 它自己会再判一次 protected
SHOW_CONFIG_BUTTON = True
SHOW_DELETE_BUTTON = True

DEV_GUIDE = """插件 = .ToolsGCP/plugins 下的一个文件夹，最少只要两个文件

    plugins/我的插件/
    ├─ manifest.json     插件基本信息（名称 / 版本 / 作者 / 入口）
    └─ app.py            入口文件，必须提供 create_page(context)

create_page(context) 返回一个 QWidget，ToolsGCP 就把它当成插件页面显示。

────────────────────────────
三步开始
────────────────────────────
1. 复制 plugins/_template 整个文件夹，改名成你的插件 id（英文小写，例如 my-tool）
2. 改 manifest.json 里的 name / author / description
3. 在 app.py 里写界面（模板已经把界面拆到 ui/page.py）

写完回到本页点「重新加载」就能看到你的插件。

────────────────────────────
完整模板 _template 里已经准备好了
────────────────────────────
⚠️ `_template` 只是**给你复制用的开发模板**，它自己不是插件：
   程序不会加载它、插件列表里看不到它、也不会给它建数据目录
   （见 plugin_manager.RESERVED_DIR_NAMES）。照着它改就行。
    app.py              程序基本架构：装配各模块、创建页面
    core/config.py      读写插件自己的配置（存在 data_dir）
    core/i18n.py        多语言系统（跟随 ToolsGCP 当前语言自动切换）
    core/logic.py       功能与逻辑算法（写业务代码的地方）
    ui/sidebar.py       左侧栏模块
    ui/page.py          专属界面模块
    lang/zh_CN.json     简体中文文案
    lang/zh_TW.json     繁體中文文案
    lang/en_US.json     English
    assets/             图片等资源（模板里放了一个示例图标）

────────────────────────────
context 能拿到什么
────────────────────────────
    context.name / version / author        插件信息
    context.plugin_dir                     插件目录（放只读资源）
    context.data_dir                       可写目录（存插件数据）
    context.app_dir                        ToolsGCP 程序目录
    context.language                       当前语言（简体中文 / 繁體中文 / English）
    context.settings_manager               设置
    context.favorites_manager              收藏夹
    context.get_resources()                整个资源库 list[dict]
    context.log("消息")                    写日志（日志文件 + 终端都有）

────────────────────────────
安全提醒
────────────────────────────
插件就是普通的 Python 代码，权限和 ToolsGCP 一样。
只装你自己写的或信任来源的插件，装之前建议先打开代码看一眼。
"""


def status_text_and_color(info, texts: dict = None, dark: bool = None) -> tuple:
    """插件状态 → (显示文字, 颜色)；已启用绿色、已禁用红色，颜色取设置页 token。"""
    texts = texts or {}
    c = tokens(bool(isDarkTheme()) if dark is None else dark)
    if info.status == STATUS_OK:
        return texts.get("status_enabled", "已启用"), c["success"]
    if info.status == STATUS_DISABLED:
        return texts.get("status_disabled", "已禁用"), c["danger"]
    if info.status == STATUS_ERROR:
        return texts.get("status_error", "加载失败"), c["danger"]
    return texts.get("status_error", "不可用"), c["danger"]


class StatusBadge(QLabel):
    """插件卡片右上角的状态小徽章（已启用 / 已禁用）。

    ⚠️ 自绘而不是给 qfluentwidgets 的 Label setStyleSheet：那类 Label 切主题时会重写
    自己的颜色样式表，把设好的颜色冲掉。用法：badge.set_status("已启用", "#2FA36B")
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fg = QColor("#2FA36B")
        self._bg = QColor(47, 163, 107, 42)
        font = QFont(self.font())
        font.setPixelSize(11)
        self.setFont(font)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(22)
        self.setMinimumWidth(56)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_status(self, text: str, color: str, alpha: int = 42):
        self.setText(str(text or ""))
        self._fg = QColor(color)
        self._bg = QColor(color)
        self._bg.setAlpha(int(alpha))
        width = QFontMetrics(self.font()).horizontalAdvance(self.text()) + 20
        self.setMinimumWidth(max(52, width))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._bg)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.setPen(self._fg)
        painter.drawText(self.rect(), Qt.AlignCenter, self.text())
        painter.end()


def apply_dim(widget, dimmed: bool, opacity: float = 0.45):
    """把控件整体调暗（禁用状态用），dimmed=False 时恢复原样。"""
    if dimmed:
        effect = widget.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
        effect.setOpacity(opacity)
    else:
        widget.setGraphicsEffect(None)


def apply_dim_widgets(widgets, dimmed: bool, opacity: float = 0.45):
    """把指定的几个控件各自调暗（不碰操作区）。

    ⚠️ 不能对整张卡片下 opacity 效果，否则备注框/按钮一起糊掉、看着像点不了；
    一个控件一个 effect 是 Qt 的硬性限制（不能共享），只在禁用时才建。
    """
    for widget in widgets or ():
        if widget is None:
            continue
        try:
            apply_dim(widget, dimmed, opacity)
        except Exception:
            pass


class PluginRow(SimpleCardWidget):
    """列表排版下的一行插件：图标 → 名称 → v版本 → 作者 → 备注 → 徽章 → 开关 → 删除。

    简介另起一行压在名称下面；宽度不够时让 desc_label 自己省略，不跟备注抢位置。
    """

    toggle_clicked = pyqtSignal(object)
    delete_clicked = pyqtSignal(object)
    config_clicked = pyqtSignal(object)
    note_changed = pyqtSignal(str, str)      # (插件 id, 备注)

    # 78 → 96：这一行有三行文字，备注按钮本身 26px，内容最少要 80px，再加行内边距 8+8
    ROW_HEIGHT = 96

    def __init__(self, info, parent=None, texts=None):
        super().__init__(parent)
        self.info = info
        texts = texts or {}
        self._texts = texts
        self._desc_text = info.description or texts.get("no_desc", "")
        self._author_text = texts.get("by_author", "作者").replace(
            "{name}", info.author) if info.author else ""
        self.setFixedHeight(self.ROW_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(14)

        # ---- 图标 ----
        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(44, 44)
        self.icon_label.setPixmap(make_plugin_icon(info, 44))
        layout.addWidget(self.icon_label, 0, Qt.AlignVCenter)

        # ---- 文字列：名称 / 简介 / 版本 → 作者 → 备注 ----
        text_box = QVBoxLayout()
        text_box.setSpacing(1)

        self.name_label = StrongBodyLabel(info.name, self)
        self.name_label.setWordWrap(False)
        self.name_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        text_box.addWidget(self.name_label)

        self.desc_label = CaptionLabel("", self)
        self.desc_label.setWordWrap(False)
        self.desc_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        text_box.addWidget(self.desc_label)

        # 版本 → 作者（从左到右，遵守"作者放在版本后面"）
        meta_row = QHBoxLayout()
        meta_row.setSpacing(10)

        self.version_label = BodyLabel(f"v{info.version}" if info.version else "", self)
        self.version_label.setStyleSheet("color: #8A8A8A;")
        meta_row.addWidget(self.version_label)

        self.author_label = CaptionLabel("", self)
        self.author_label.setWordWrap(False)
        self.author_label.setStyleSheet("color: #8A8A8A;")
        meta_row.addWidget(self.author_label)
        meta_row.addStretch()

        text_box.addLayout(meta_row)
        layout.addLayout(text_box, 1)

        # 备注编辑器：和卡片用的是同一个控件，回车保存 / Esc 取消 / 点别处取消
        # ⚠️ 它和徽章 / 开关 / 删除同一行、排在它们左边；这一排靠右，所以"往左"= 加大这里的空隙
        self.note_edit = PluginNoteEdit(getattr(info, "note", "") or "", texts, self)
        self.note_edit.saved.connect(
            lambda note: self.note_changed.emit(str(self.info.id), note))
        layout.addWidget(self.note_edit, 0, Qt.AlignVCenter)
        layout.addSpacing(NOTE_GAP_TO_BADGE)

        # ---- 状态徽章（列表排版下放在开关左边，配色和卡片右上角那枚完全一致）----
        self.status_badge = StatusBadge(self)
        layout.addWidget(self.status_badge, 0, Qt.AlignVCenter)

        # ---- 开关（作者自制的 ToggleSwitch）----
        self.toggle_switch = ToggleSwitch(self, width=52, height=28)
        self.toggle_switch.setToolTip(texts.get("toggle_tip", "打开 / 关闭这个插件"))
        self.toggle_switch.toggled.connect(self._on_switch_toggled)
        layout.addWidget(self.toggle_switch, 0, Qt.AlignVCenter)

        # 「⚙ 配置界面」：进插件自己的界面；加载失败 / 被停用 / 没提供页面时置灰
        self.config_btn = None
        if SHOW_CONFIG_BUTTON:
            self.config_btn = TransparentToolButton(FIF.SETTING, self)
            self.config_btn.setFixedSize(32, 32)
            self.config_btn.clicked.connect(
                lambda: self.config_clicked.emit(self.info))
            if getattr(info, "page", None) is not None:
                self.config_btn.setToolTip(texts.get("config_button", "配置界面"))
            else:
                self.config_btn.setEnabled(False)
                self.config_btn.setToolTip(
                    texts.get("config_unavailable",
                              "这个插件没有配置界面（或没加载成功）"))
            layout.addWidget(self.config_btn)

        self.delete_btn = None
        if SHOW_DELETE_BUTTON:
            self.delete_btn = TransparentToolButton(FIF.DELETE, self)
            self.delete_btn.setFixedSize(32, 32)
            self.delete_btn.clicked.connect(
                lambda: self.delete_clicked.emit(self.info))
            if info.protected:
                self.delete_btn.setEnabled(False)
                self.delete_btn.setToolTip(
                    texts.get("builtin_tip", "内置插件，不可删除"))
            else:
                self.delete_btn.setToolTip(texts.get("delete", "删除插件"))
            layout.addWidget(self.delete_btn)

        self._apply_status()
        self._refresh_labels()

    def _on_switch_toggled(self, checked: bool):
        """开关只能由用户点动，这里只负责把意图传出去"""
        self.toggle_clicked.emit(self.info)

    def _refresh_labels(self):
        """按当前行宽重算名称 / 简介 / 作者的省略文本。

        构造中 resizeEvent 会先来（控件还没建好），先挡一下；三处都手动省略，免得把备注挤出行外。
        """
        if not hasattr(self, "note_edit"):
            return
        # 右边固定占位：图标 44 + 行边距 32 + 备注按钮约 90 + 与徽章的空隙 + 徽章/开关/删除约 200
        # ⚠️ 必须把 NOTE_GAP_TO_BADGE 算进来，否则它变大时简介会被布局直接裁掉而不是显示"…"
        reserved = 44 + 32 + 90 + NOTE_GAP_TO_BADGE + 200
        avail = max(120, self.width() - reserved)
        self.name_label.setText(
            PluginCard._elide(self.info.name, self.name_label.fontMetrics(), avail, 1))
        self.desc_label.setText(
            PluginCard._elide(self._desc_text, self.desc_label.fontMetrics(), avail, 1))
        self.author_label.setText(
            PluginCard._elide(self._author_text, self.author_label.fontMetrics(),
                              max(60, avail // 2), 1))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_labels()

    def _apply_status(self):
        text, color = status_text_and_color(self.info, self._texts)
        self.status_badge.set_status(text, color)
        if self.info.error:
            self.status_badge.setToolTip(self.info.error)
        # 开关状态跟插件状态一致（回填时不发信号，避免又被当成用户操作）
        self.toggle_switch.setChecked(self.info.status == STATUS_OK, emit=False)
        self.toggle_switch.apply_theme()        # 跟着当前深浅色主题上色
        usable = self.info.status in (STATUS_OK, STATUS_DISABLED)
        self.toggle_switch.setEnabled(usable)
        self.toggle_switch.setLocked(not usable)
        # 禁用时只把信息区调暗：备注 / 徽章 / 开关 / 配置 / 垃圾桶保持原样可点
        self._dim_info(self.info.status == STATUS_DISABLED)

    def _dim_info(self, dimmed: bool):
        """只把"信息区"（图标 / 名称 / 简介 / 版本·作者）调暗，操作区一律不碰。"""
        apply_dim_widgets(
            (getattr(self, "icon_label", None), getattr(self, "name_label", None),
             getattr(self, "desc_label", None), getattr(self, "version_label", None),
             getattr(self, "author_label", None)),
            dimmed)

    def refresh_theme(self):
        """主题变化：徽章颜色、插件图标与备注图标重新取色（和卡片那套保持一致）"""
        self._apply_status()
        # ⚠️ 插件图标是建卡那刻按主题取的 pixmap，不重取的话切深色后还是黑图标、几乎看不见
        if getattr(self, "icon_label", None) is not None:
            self.icon_label.setPixmap(make_plugin_icon(self.info, 44))
        if getattr(self, "note_edit", None) is not None:
            self.note_edit.refresh_theme()


def make_plugin_icon(info, size: int = 34) -> QPixmap:
    """插件图标：支持插件目录里的图片文件，或 FluentIcon 的名字"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    icon = None
    icon_name = str(info.icon or "").strip()
    candidate = os.path.join(info.dir, icon_name)
    if icon_name and os.path.exists(candidate):
        icon = QIcon(candidate)
    elif icon_name and hasattr(FIF, icon_name):
        icon = getattr(FIF, icon_name).icon()
    else:
        icon = FIF.APPLICATION.icon()

    painter = QPainter(pixmap)
    icon.paint(painter, 1, 1, size - 2, size - 2)
    painter.end()
    return pixmap


class _NoteButton(PushButton):
    """「备注」按钮：label 图标画在文字左边，两者是一个整体。

    ⚠️ 不能给 qfluentwidgets 的 PushButton setStyleSheet 了事：库自己按 minimumSizeHint 画图标、
    文字归 Qt 样式引擎画，setStyleSheet 后 sizeHint 只剩文字宽（33px vs 82px），图标就压在文字上。
    修法：不让库画图标，改由样式表一起画（QStyle::CE_PushButtonLabel），天然不会重叠。
    """

    ICON_SIZE = 13
    # 图标左内边距 / 图标与文字的间距（文字前不垫空格，间距完全由 padding 决定）
    PAD_LEFT = 4
    PAD_RIGHT = 6
    GAP = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        self._icon_size = QSize(self.ICON_SIZE, self.ICON_SIZE)
        self._full_text = ""
        # 我们自己那份样式表（见 apply_look / eventFilter 的说明）
        self._own_qss = ""
        self._applying_qss = False
        self.installEventFilter(self)

    def apply_look(self, color: str):
        """按当前主题上色：图标和文字用同一个颜色"""
        self.setIcon(None)          # 拔掉 qfluentwidgets 自己画的那份图标
        self.setIconSize(self._icon_size)
        self._own_qss = (
            f"PushButton {{ color: {color}; font-size: 11px;"
            f" background: transparent; border: none;"
            f" padding: 0px {self.PAD_RIGHT}px 0px"
            f" {self.PAD_LEFT + self.ICON_SIZE + self.GAP}px;"
            f" qproperty-icon: url({FIF.LABEL.path()});"
            f" qproperty-iconSize: {self.ICON_SIZE}px {self.ICON_SIZE}px; }}"
            "PushButton:hover { color: #5B8DEF; }")
        self._detach_from_style_manager()
        self._apply_own_qss()

    # ⚠️ 坑：库的 PushButton 构造时会注册进全局样式管理器，切主题时 DirtyStyleSheetWatcher
    #    会在它第一次被画出来时用库自己的 button.qss 冲掉我们设的样式（按钮就变成普通填充按钮）。
    #    修法：退出样式管理器 + 在 StyleChange 里发现样式表不是我们那份就补回来。
    def _detach_from_style_manager(self):
        """把这颗按钮从 qfluentwidgets 的全局样式管理器上摘下来"""
        try:
            from qfluentwidgets.common.style_sheet import styleSheetManager
            styleSheetManager.deregister(self)
        except Exception:
            pass
        try:
            self.setProperty("dirty-qss", False)
        except Exception:
            pass

    def _apply_own_qss(self):
        """套上我们自己的样式表（带去重，避免 StyleChange 递归）"""
        if not self._own_qss or self._applying_qss:
            return
        if self.styleSheet() == self._own_qss:
            return
        self._applying_qss = True
        try:
            self.setStyleSheet(self._own_qss)
        finally:
            self._applying_qss = False

    def eventFilter(self, obj, event):
        """样式表被库覆盖时补回来（见 _detach_from_style_manager 的说明）"""
        if obj is self and event.type() == QEvent.StyleChange:
            self._apply_own_qss()
        return super().eventFilter(obj, event)

    def setText(self, text: str):
        """记下完整文字，实际显示的那份由 paintEvent 按按钮实际宽度省略"""
        self._full_text = str(text or "")
        super().setText(self._full_text)
        self.update()

    def paintEvent(self, event):
        """文字放不下时自己省略。

        按钮有 maximumWidth 上限，但布局给的可能更小，Qt 只会把文字裁掉；这里按实际宽度省略到刚好放得下。
        """
        fm = QFontMetrics(self.font())
        # ⚠️ 少留 2px：样式表算文字可用宽度会比自估的多算一点，卡临界时省略号会被裁掉
        avail = (self.width() - self.PAD_LEFT - self.ICON_SIZE - self.GAP
                 - self.PAD_RIGHT) - 2
        if avail > 0 and fm.horizontalAdvance(self._full_text) > avail:
            elided = fm.elidedText(self._full_text, Qt.ElideRight, avail)
            if elided and self.text() != elided:
                super().setText(elided)
        elif self.text() != self._full_text:
            super().setText(self._full_text)
        super().paintEvent(event)


class PluginNoteEdit(QWidget):
    """插件卡片左下角 / 列表行里的「备注」编辑器。

    三态：空闲 =「🏷 备注」按钮（label 图标紧贴文字左边，两者是整体）；编辑中 = 输入框（限 NOTE_MAX_CHARS）；
    有备注 = 按钮文字就是备注内容。Enter 保存，Esc / 点到输入框以外 = 取消。

    做成卡片的一部分而不是弹窗：备注只有 20 字，弹窗太重，扫一眼卡片就能看到标注才是它的用处。
    """

    saved = pyqtSignal(str)          # 参数：新备注（已 strip，可能为空串 = 删除备注）

    NOTE_MAX_CHARS = 20              # 需求：显示 20 个字符

    def __init__(self, note: str = "", texts: dict = None, parent=None):
        super().__init__(parent)
        self._texts = texts or {}
        self._note = str(note or "")
        self._editing = False
        # "点别处就取消"的全局事件过滤器是否已经装上（见 _install_outside_close）
        self._outside_filter_installed = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.button = _NoteButton(self)
        # ⚠️ 用 label 图标紧贴文字左边：图标和文字在同一个按钮里，显示/隐藏/点击都是整体
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setToolTip(self._texts.get("note_tip", "给这个插件写个备注"))
        self.button.clicked.connect(self.start_edit)
        # 长度不固定：文本太长时让按钮自己去省略，绝不越过右边的开关/删除按钮
        self.button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.button.setMaximumWidth(170)
        layout.addWidget(self.button)

        self.edit = LineEdit(self)
        self.edit.setFixedHeight(26)
        self.edit.setMaxLength(self.NOTE_MAX_CHARS)
        self.edit.setPlaceholderText(self._texts.get("note_placeholder", "备注"))
        self.edit.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.edit.setMaximumWidth(150)
        self.edit.returnPressed.connect(self.commit)
        self.edit.installEventFilter(self)
        self.edit.hide()
        layout.addWidget(self.edit)

        self._refresh_button()

    # ---------- 显示 ----------
    def _refresh_button(self):
        """刷新按钮文字与样式（空闲态与"有备注"态共用一套样式）"""
        text = self._elided(self._note) if self._note \
            else self._texts.get("note_button", "备注")
        # 文字前不再垫空格：图标与文字之间的间距由样式表的 padding 给
        self.button.setText(text)
        # label 图标 + 文字由样式表一起画（见 _NoteButton），图标永远在文字左边
        self.button.apply_look(self._note_color())
        self.button.setVisible(not self._editing)
        self.edit.setVisible(self._editing)

    def _note_color(self) -> str:
        """备注按钮（含图标）的颜色：跟着主题走"""
        return "#C9CCD6" if isDarkTheme() else "#6B7280"

    def _elided(self, text: str) -> str:
        """超过 20 个字符就截断加省略号（输入框本身也限了长度，这里只兜底）"""
        text = str(text)
        if len(text) <= self.NOTE_MAX_CHARS:
            return text
        return text[:self.NOTE_MAX_CHARS] + "…"

    # ---------- 编辑 ----------
    def start_edit(self):
        self._editing = True
        self.edit.setText(self._note)
        self._refresh_button()
        self.edit.setFocus()
        self.edit.selectAll()
        self._install_outside_close()

    def commit(self):
        """Enter：保存并退出编辑"""
        self._remove_outside_close()
        note = self.edit.text().strip()[:self.NOTE_MAX_CHARS]
        self._note = note
        self._editing = False
        self._refresh_button()
        self.saved.emit(note)

    def cancel(self):
        """Esc / 点到别处：放弃改动并退出编辑"""
        self._remove_outside_close()
        self._editing = False
        self._refresh_button()

    # ---------- "点别处 = 取消" ----------
    def _install_outside_close(self):
        """开编辑时挂一个应用级事件过滤器，抓"点在输入框以外"。

        装到 QApplication 上：装在自己的窗口上收不到发给别的子控件的事件（同 ai_chat_panel 的做法）。
        """
        app = QApplication.instance()
        if app is None or self._outside_filter_installed:
            return
        app.installEventFilter(self)
        self._outside_filter_installed = True

    def _remove_outside_close(self):
        app = QApplication.instance()
        if app is None or not self._outside_filter_installed:
            return
        app.removeEventFilter(self)
        self._outside_filter_installed = False

    def _contains(self, widget) -> bool:
        """这个控件是不是备注编辑器自己（含子控件）"""
        if widget is None:
            return False
        try:
            return widget is self or self.isAncestorOf(widget)
        except RuntimeError:
            return False

    def eventFilter(self, obj, event):
        # Esc = 取消
        if obj is self.edit and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self.cancel()
                return True
        # 鼠标按下时判断"落点是不是编辑器自己"，不是就当成取消
        if event.type() == QEvent.MouseButtonPress and self._outside_filter_installed:
            target = obj if isinstance(obj, QWidget) else None
            if target is not None and not self._contains(target):
                self.cancel()
        return super().eventFilter(obj, event)

    # ---------- 外部 ----------
    def note(self) -> str:
        return self._note

    def set_note(self, note: str):
        self._note = str(note or "")[:self.NOTE_MAX_CHARS]
        self._refresh_button()

    def refresh_theme(self):
        """主题变了：重取 label 图标颜色"""
        self._refresh_button()


class PluginCard(SimpleCardWidget):
    """一个插件的卡片。

    左上：图标 + 名称/版本·作者；右上：已启用 / 已禁用（绿 / 红）；中间：简介（最多两行）；
    左下：🏷 备注（可点开成输入框）；右下：开关 + 删除（开关在删除左边）。
    """

    toggle_clicked = pyqtSignal(object)
    delete_clicked = pyqtSignal(object)
    config_clicked = pyqtSignal(object)
    note_changed = pyqtSignal(str, str)      # (插件 id, 备注)

    def __init__(self, info, parent=None, texts=None):
        super().__init__(parent)
        self.info = info
        texts = texts or {}
        self.setFixedSize(CARD_W, CARD_H)
        self._card_width = CARD_W
        self._texts = texts

        layout = QVBoxLayout(self)
        # 卡片左内边距 16 → 12（整块内容更贴边一点，备注自然也更靠左）
        layout.setContentsMargins(12, 12, 16, 12)
        layout.setSpacing(0)

        # ---- 第一行：图标 + 名称 + 版本/作者 ……… 右上角状态徽章 ----
        head = QHBoxLayout()
        head.setSpacing(10)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(34, 34)
        self.icon_label.setPixmap(self._make_icon())
        head.addWidget(self.icon_label, 0, Qt.AlignVCenter)

        name_box = QVBoxLayout()
        name_box.setSpacing(0)
        self.name_label = StrongBodyLabel(info.name, self)
        self.name_label.setWordWrap(False)
        name_box.addWidget(self.name_label)
        sub = " · ".join(x for x in [f"v{info.version}" if info.version else "",
                                     info.author] if x)
        # ⚠️ 存成字段：禁用时要**只把它这一块**调暗（见 _dim_info）
        self.meta_label = CaptionLabel(sub or info.id, self)
        name_box.addWidget(self.meta_label)
        head.addLayout(name_box, 1)

        # 状态徽章钉在卡片**右上角**（需求原话："已开启 已禁用放在卡片右上角"）
        self.status_badge = StatusBadge(self)
        head.addWidget(self.status_badge, 0, Qt.AlignTop)

        layout.addLayout(head)
        layout.addSpacing(6)

        divider = QFrame(self)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: rgba(128,128,128,80);")
        layout.addWidget(divider)
        layout.addSpacing(6)

        # ---- 说明（最多两行，宽度变了会重算）----
        self.desc_label = CaptionLabel("", self)
        self.desc_label.setWordWrap(True)
        self.desc_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        fm = self.desc_label.fontMetrics()
        self.desc_label.setFixedHeight(fm.height() * 2 + 2)
        layout.addWidget(self.desc_label)
        layout.addStretch()

        self.resizeEvent(None)

        # 底行：左备注 …… 右（开关 + 删除）
        # ⚠️ "备注再往左"：给容器设负内边距无效（Qt 忽略负值），只能靠卡片左内边距 16→12 + 本行容器内边距设 0
        buttons_host = QWidget(self)
        buttons = QHBoxLayout(buttons_host)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(6)
        self.note_edit = PluginNoteEdit(getattr(info, "note", "") or "", texts, self)
        self.note_edit.saved.connect(
            lambda note: self.note_changed.emit(str(self.info.id), note))
        buttons.addWidget(self.note_edit)
        buttons.addStretch()

        # 开关：**放在删除按钮左边**（需求原话）
        self.toggle_switch = ToggleSwitch(self, width=46, height=24)
        self.toggle_switch.setToolTip(texts.get("toggle_tip", "打开 / 关闭这个插件"))
        self.toggle_switch.toggled.connect(self._on_switch_toggled)
        buttons.addWidget(self.toggle_switch, 0, Qt.AlignVCenter)

        # 「⚙ 配置界面」：和列表排版那边同一个行为
        self.config_btn = None
        if SHOW_CONFIG_BUTTON:
            self.config_btn = TransparentToolButton(FIF.SETTING, self)
            self.config_btn.setFixedSize(30, 30)
            self.config_btn.clicked.connect(
                lambda: self.config_clicked.emit(self.info))
            if getattr(info, "page", None) is not None:
                self.config_btn.setToolTip(texts.get("config_button", "配置界面"))
            else:
                self.config_btn.setEnabled(False)
                self.config_btn.setToolTip(
                    texts.get("config_unavailable",
                              "这个插件没有配置界面（或没加载成功）"))
            buttons.addWidget(self.config_btn)

        self.delete_btn = None
        if SHOW_DELETE_BUTTON:
            self.delete_btn = TransparentToolButton(FIF.DELETE, self)
            self.delete_btn.setFixedSize(30, 30)
            self.delete_btn.clicked.connect(
                lambda: self.delete_clicked.emit(self.info))
            if info.protected:
                self.delete_btn.setEnabled(False)
                self.delete_btn.setToolTip(
                    texts.get("builtin_tip", "内置插件，不可删除"))
            else:
                self.delete_btn.setToolTip(texts.get("delete", "删除插件"))
            buttons.addWidget(self.delete_btn)
        layout.addWidget(buttons_host)

        self._apply_status()

    def _on_switch_toggled(self, checked: bool):
        """开关只由用户点动，这里把意图发给页面去真正启停"""
        self.toggle_clicked.emit(self.info)

    # ---------- 辅助 ----------
    def resizeEvent(self, event):
        """宽度变化时重新做省略（网格会把卡片拉宽）"""
        super().resizeEvent(event) if event is not None else None
        self._card_width = self.width() or CARD_W
        fm = self.desc_label.fontMetrics()
        text = self.info.description or self._texts.get("no_desc", "")
        self.desc_label.setText(self._elide(text, fm, self._card_width - 32, 2))
        self.name_label.setText(self._elide(self.info.name, self.name_label.fontMetrics(),
                                            self._card_width - 34 - 12 - 90, 1))

    def _make_icon(self) -> QPixmap:
        """插件图标：支持插件目录里的图片文件，或 FluentIcon 的名字"""
        pixmap = QPixmap(34, 34)
        pixmap.fill(Qt.transparent)

        icon = None
        icon_name = str(self.info.icon or "").strip()
        candidate = os.path.join(self.info.dir, icon_name)
        if icon_name and os.path.exists(candidate):
            icon = QIcon(candidate)
        elif icon_name and hasattr(FIF, icon_name):
            icon = getattr(FIF, icon_name).icon()
        else:
            icon = FIF.APPLICATION.icon()

        painter = QPainter(pixmap)
        icon.paint(painter, 1, 1, 32, 32)
        painter.end()
        return pixmap

    def _apply_status(self):
        # 状态在**卡片右上角的徽章**里：已启用=绿、已禁用=红（需求原话）
        text, color = status_text_and_color(self.info, self._texts)
        self.status_badge.set_status(text, color)
        if self.info.error:
            self.status_badge.setToolTip(self.info.error)
            self.desc_label.setToolTip(self.info.error)
            self.setToolTip(self.info.error)
        # 开关跟状态一致（回填不发信号，避免被当成用户点击）
        self.toggle_switch.setChecked(self.info.status == STATUS_OK, emit=False)
        self.toggle_switch.apply_theme()        # 跟着当前深浅色主题上色
        usable = self.info.status in (STATUS_OK, STATUS_DISABLED)
        self.toggle_switch.setEnabled(usable)
        self.toggle_switch.setLocked(not usable)
        # 禁用时只把信息区调暗（备注 / 开关 / 配置 / 垃圾桶保持原样可用）
        self._dim_info(self.info.status == STATUS_DISABLED)

    def _dim_info(self, dimmed: bool):
        """只把"信息区"（图标 / 名称 / 版本·作者 / 简介）调暗，操作区一律不碰。"""
        apply_dim_widgets(
            (getattr(self, "icon_label", None), getattr(self, "name_label", None),
             getattr(self, "meta_label", None), getattr(self, "desc_label", None)),
            dimmed)

    def refresh_theme(self):
        """主题变化：徽章颜色与备注图标重新取色"""
        self._apply_status()
        # 插件图标同理：它是按主题取色的 pixmap，不重取就会留在旧颜色上
        if getattr(self, "icon_label", None) is not None:
            self.icon_label.setPixmap(self._make_icon())
        if getattr(self, "note_edit", None) is not None:
            self.note_edit.refresh_theme()

    @staticmethod
    def _elide(text, fm, width, lines) -> str:
        text = str(text or "").replace("\n", " ").strip()
        if not text:
            return ""
        rows, current, consumed = [], "", 0
        for ch in text:
            if fm.horizontalAdvance(current + ch) > width:
                rows.append(current)
                current = ch
                if len(rows) == lines:
                    break
            else:
                current += ch
            consumed += 1
        if len(rows) < lines and current:
            rows.append(current)
            consumed = len(text)
        if consumed < len(text) and rows:
            last = rows[-1]
            while last and fm.horizontalAdvance(last + "…") > width:
                last = last[:-1]
            rows[-1] = last + "…"
        return "\n".join(rows)


class DevGuideDialog(MessageBoxBase):
    """「我想开发」弹窗：简明上手说明"""

    def __init__(self, parent=None, plugins_dir: str = ""):
        super().__init__(parent)
        self.plugins_dir = plugins_dir
        # 拿不到语言管理器时退回中文（键见 languages/plugin_language.json）
        parent_text = getattr(parent, "get_text", None)

        def _t(key, fallback):
            if callable(parent_text):
                try:
                    text = parent_text(key)
                    if text and text != key:
                        return text
                except Exception:
                    pass
            return fallback

        self.titleLabel = SubtitleLabel(_t("dev_guide_title", "I want to build a plugin"), self)
        self.viewLayout.addWidget(self.titleLabel)

        self.text = TextEdit(self)
        self.text.setReadOnly(True)
        self.text.setPlainText(DEV_GUIDE)
        self.text.setMinimumHeight(400)
        self.viewLayout.addWidget(self.text)

        self.yesButton.setText(_t("open_dir", "Open plugins folder"))
        self.cancelButton.setText(_t("dialog_close", "Close"))
        self.widget.setMinimumWidth(660)

    def validate(self) -> bool:
        """点「打开插件目录」只打开目录，窗口不关（方便边看边写）"""
        try:
            if self.plugins_dir:
                os.makedirs(self.plugins_dir, exist_ok=True)
                os.startfile(self.plugins_dir)
        except Exception:
            pass
        return False


class PluginInterface(QWidget):
    """插件页：插件列表 + 启停开关（不再提供"进入插件内部页面"的入口）"""

    def __init__(self, plugin_manager: PluginManager = None, language_manager=None, parent=None):
        super().__init__(parent)
        self.setObjectName("pluginInterface")
        self.manager = plugin_manager
        self.lang = language_manager
        self._cards = []
        self._rows = []
        self._layout_key = self._initial_layout()
        self.setup_ui()
        self.refresh_list()

    def _initial_layout(self) -> str:
        """读上次选的排版（默认井字形）"""
        try:
            if self.manager is not None and getattr(self.manager, "settings_manager", None):
                value = str(self.manager.settings_manager.settings.get("plugin_view") or "grid")
                return value if value in ("grid", "list") else "grid"
        except Exception:
            pass
        return "grid"

    # ---------- UI ----------
    def setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.stack = QStackedWidget(self)
        outer.addWidget(self.stack)

        # ================= 页 0：插件列表 =================
        list_page = QWidget(self.stack)
        layout = QVBoxLayout(list_page)
        layout.setContentsMargins(32, 26, 32, 20)
        layout.setSpacing(14)

        # ---------- 标题行：标题 + 条目数 ……… 我想开发 ----------
        header = QHBoxLayout()
        header.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.title_label = SubtitleLabel(self.get_text("plugins_title"), list_page)
        title_box.addWidget(self.title_label)
        self.count_label = CaptionLabel("", list_page)
        title_box.addWidget(self.count_label)
        header.addLayout(title_box)
        header.addStretch()

        self.dev_btn = PrimaryPushButton(self.get_text("want_dev"), list_page, FIF.EDIT)
        self.dev_btn.clicked.connect(self.show_dev_guide)
        header.addWidget(self.dev_btn)
        layout.addLayout(header)

        # ---------- 分隔线 ----------
        self.divider_widget = self._make_divider(list_page)
        layout.addWidget(self.divider_widget)

        # ---------- 工具行：搜索 + 操作 ……… 排版切换 ----------
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        # 插件变多以后一眼找不到，加个即时搜索（名称 / id / 作者 / 说明）
        self.search_edit = SearchLineEdit(list_page)
        self.search_edit.setPlaceholderText(self.get_text("search_plugin"))
        self.search_edit.setFixedWidth(220)
        self.search_edit.textChanged.connect(lambda _t: self.refresh_list())
        self.search_edit.searchSignal.connect(lambda _t: self.refresh_list())
        toolbar.addWidget(self.search_edit)

        self.reload_btn = PushButton(self.get_text("reload"), list_page, FIF.SYNC)
        self.reload_btn.clicked.connect(self.reload_plugins)
        toolbar.addWidget(self.reload_btn)

        self.open_dir_btn = PushButton(self.get_text("open_dir"), list_page, FIF.FOLDER)
        self.open_dir_btn.clicked.connect(self.open_plugins_dir)
        toolbar.addWidget(self.open_dir_btn)

        self.open_readme_btn = PushButton(self.get_text("open_readme"), list_page, FIF.DOCUMENT)
        self.open_readme_btn.clicked.connect(self.open_readme)
        toolbar.addWidget(self.open_readme_btn)

        # 先撑开，把排版切换顶到最右边
        toolbar.addStretch()

        # 排版切换（纯图标分段控件）
        self.view_segmented = SegmentedToolWidget(list_page)
        self.view_segmented.addItem("grid", FIF.TILES)
        self.view_segmented.addItem("list", FIF.MENU)
        for _key, _tip in (("grid", "layout_grid"), ("list", "layout_list")):
            try:
                self.view_segmented.items[_key].setToolTip(self.get_text(_tip))
            except Exception:
                pass
        # 两个方块图标 + 一点点内边距就够，太宽会显得空
        self.view_segmented.setFixedSize(68, 30)
        self.view_segmented.currentItemChanged.connect(self.change_layout)
        toolbar.addWidget(self.view_segmented)
        layout.addLayout(toolbar)

        # 一行小提示，说明插件怎么放进来（原来在标题下面，挪到这里更清爽）
        self.hint_label = CaptionLabel(self.get_text("plugins_hint"), list_page)
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: #8A8A8A;")
        layout.addWidget(self.hint_label)

        self.scroll_area = QScrollArea(list_page)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("pluginScrollContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 4, 0, 4)
        content_layout.setSpacing(0)
        content_layout.setAlignment(Qt.AlignTop)

        # 两种排版：井字网格 / 一行一个；切换用上面那个分段控件
        self.cards_grid = ResponsiveGrid(
            content, min_item_width=CARD_W, spacing=GRID_SPACING,
            margin=0, item_height=CARD_H)
        self.cards_grid.setObjectName("pluginCardsGrid")
        content_layout.addWidget(self.cards_grid)

        self.rows_host = QWidget(content)
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(10)      # 行和行之间留点空，列表更好读
        self.rows_layout.setAlignment(Qt.AlignTop)
        self.rows_host.hide()
        content_layout.addWidget(self.rows_host)

        self.scroll_area.setWidget(content)
        layout.addWidget(self.scroll_area, 1)

        self.empty_label = CaptionLabel(self.get_text("empty"), list_page)
        self.empty_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.empty_label)
        self.empty_label.hide()

        # ---------- 加载态（点「重新加载」时顶掉上面所有内容） ----------
        # 三个工具按钮的文字换成 IndeterminateProgressRing，标题/搜索/排版/列表全藏起来，换成搜索页那套 LoadingWidget
        self.loading_host = QWidget(list_page)
        self.loading_layout = QVBoxLayout(self.loading_host)
        self.loading_layout.setContentsMargins(0, 0, 0, 0)
        self.loading_layout.setAlignment(Qt.AlignCenter)
        self.loading_host.hide()
        layout.addWidget(self.loading_host, 1)
        self._loading_widget = None
        self._reloading = False

        self._apply_scrollbar_style()
        self.cards_grid.setVisible(self._layout_key == "grid")
        self.rows_host.setVisible(self._layout_key == "list")
        # 默认选中当前排版（不要空着，用户一眼能看出现在用的是哪种）
        try:
            self.view_segmented.setCurrentItem(self._layout_key)
        except Exception:
            pass
        self.stack.addWidget(list_page)

        # ================= 页 1：插件自己的界面（以前 page 建好却没入口能打开）=================
        self.stack.addWidget(self._build_config_page_host())

    def _build_config_page_host(self) -> QWidget:
        """页 1 的骨架：返回按钮 + 插件名 + 一块用来放插件页面的容器"""
        page = QWidget(self.stack)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget(page)
        header.setFixedHeight(52)
        row = QHBoxLayout(header)
        row.setContentsMargins(20, 0, 20, 0)
        row.setSpacing(10)

        self.page_back_btn = TransparentToolButton(FIF.RETURN, header)
        self.page_back_btn.setFixedSize(34, 34)
        self.page_back_btn.setToolTip(self.get_text("config_back"))
        self.page_back_btn.clicked.connect(self.close_config)
        row.addWidget(self.page_back_btn)

        self.page_title_label = SubtitleLabel("", header)
        row.addWidget(self.page_title_label)
        row.addStretch()
        layout.addWidget(header)

        divider = QFrame(page)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: rgba(128,128,128,60);")
        layout.addWidget(divider)

        # 插件页面就塞进这个容器里（同一个插件反复打开都是同一个 QWidget 实例）
        self.config_page_host = QWidget(page)
        self.config_page_layout = QVBoxLayout(self.config_page_host)
        self.config_page_layout.setContentsMargins(0, 0, 0, 0)
        self.config_page_layout.setSpacing(0)
        layout.addWidget(self.config_page_host, 1)

        self._hosted_plugin = None
        return page

    # ---------- 插件自己的界面 ----------
    def open_config(self, info):
        """打开某个插件的配置界面（卡片/行上的「⚙ 配置界面」）。

        ⚠️ 插件页面是复用的（info.page 加载时就建好了），这里只换父控件 —— 插件的数据和
        定时器都挂在它身上，不能每次新建。
        """
        if info is None:
            return
        page = getattr(info, "page", None)
        if page is None:
            self.show_message(self.get_text("config_unavailable"), "warning")
            return
        # 先把上一个插件页面摘掉（不然它会留在容器里跟新页面叠着）
        self._detach_hosted_plugin()
        try:
            page.setParent(self.config_page_host)
            self.config_page_layout.addWidget(page)
            page.show()
        except Exception as exc:
            self.show_message(f"{info.name}: {exc}", "error")
            return
        self._hosted_plugin = info
        try:
            self.page_title_label.setText(
                self.get_text("config_title").format(name=info.name))
        except Exception:
            try:
                self.page_title_label.setText(info.name)
            except Exception:
                pass
        self.stack.setCurrentIndex(1)
        # 配置页面里若有 on_show / refresh 之类的钩子，顺手叫一次
        for hook in ("on_show", "refresh", "refresh_theme"):
            fn = getattr(page, hook, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
                break
        if self.manager is not None:
            self.manager.plugin_log(info.name, "打开配置界面")

    def close_config(self):
        """返回插件列表（配置页面留在容器里，下次进来直接复用）"""
        # ⚠️ 插件可能在开着界面时被停用/重载（page 已销毁），必须退回列表，否则用户停在空白页出不去
        hosted = self._hosted_plugin
        if hosted is not None and getattr(hosted, "page", None) is None:
            self._hosted_plugin = None
        self.stack.setCurrentIndex(0)

    # ---------- 定位并闪两下某张插件卡片 ----------
    def flash_plugin(self, plugin_id: str, times: int = 2) -> bool:
        """切到插件列表，把某张卡片滚进视野并闪两下。

        ⚠️ 找不到卡片（被删 / 被搜索框过滤）时也要把列表切回来并清空搜索关键词；返回 False 表示没定位到。
        """
        plugin_id = str(plugin_id or "").strip()
        if not plugin_id:
            return False
        try:
            # 1) 先回到列表页（可能正停在某个插件的配置界面里）
            self.stack.setCurrentIndex(0)
            # 2) 搜索框里的关键词会把它过滤掉 —— 清空后再刷新
            if hasattr(self, "search_edit") and self.search_edit.text():
                self.search_edit.blockSignals(True)
                self.search_edit.clear()
                self.search_edit.blockSignals(False)
                self.refresh_list()
        except Exception:
            pass

        holder = None
        for item in list(getattr(self, "_cards", [])) + list(getattr(self, "_rows", [])):
            info = getattr(item, "info", None)
            if info is not None and str(getattr(info, "id", "")) == plugin_id:
                holder = item
                break
        if holder is None:
            return False

        try:
            self.scroll_area.ensureWidgetVisible(holder, 0, 40)
        except Exception:
            pass
        self._start_flash(holder, max(1, int(times)))
        return True

    def _start_flash(self, holder, times: int):
        """让一张卡片／一行闪 n 次。

        用 QGraphicsOpacityEffect + QPropertyAnimation 做"变淡 → 恢复"：卡片样式表是整套的
        （圆角/描边/hover），临时改边框颜色容易把 hover 态和选中态搅乱。
        """
        try:
            effect = QGraphicsOpacityEffect(holder)
            holder.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", holder)
            anim.setDuration(220)
            anim.setLoopCount(max(1, int(times)) * 2)
            anim.setStartValue(1.0)
            anim.setKeyValueAt(0.5, 0.25)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.InOutSine)

            def _cleanup():
                try:
                    holder.setGraphicsEffect(None)
                except Exception:
                    pass

            anim.finished.connect(_cleanup)
            # 保住引用：动画对象以 holder 为父，但也别让 Python 侧提前回收
            holder._flash_anim = anim
            anim.start(QAbstractAnimation.DeleteWhenStopped)
        except Exception as exc:
            # 闪不出来不影响主流程（跳转本身已经完成了），记一句就够了
            try:
                if self.manager is not None:
                    self.manager.plugin_log("插件", f"闪烁动画失败: {exc}", "err")
            except Exception:
                pass

    def _detach_hosted_plugin(self):
        """把当前挂着的插件页面摘下来（不销毁：插件对象要复用）"""
        hosted = self._hosted_plugin
        self._hosted_plugin = None
        if hosted is None:
            return
        page = getattr(hosted, "page", None)
        if page is None:
            return
        try:
            self.config_page_layout.removeWidget(page)
            page.setParent(None)
        except Exception:
            pass

    @staticmethod
    def _make_divider(parent) -> QFrame:
        """一条淡淡的分隔线，用来把标题区和操作区分开"""
        line = QFrame(parent)
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: rgba(128,128,128,60);")
        return line

    def _apply_scrollbar_style(self):
        from qfluentwidgets import isDarkTheme
        handle = "#555555" if isDarkTheme() else "#CCCCCC"
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{ border: none; background-color: transparent; }}
            QWidget#pluginScrollContent {{ background-color: transparent; }}
            QScrollBar:vertical {{ background-color: transparent; width: 8px;
                margin: 0px; border-radius: 4px; }}
            QScrollBar::handle:vertical {{ background-color: {handle};
                min-height: 30px; border-radius: 4px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px; background: none; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none; }}
        """)

    def get_text(self, key):
        if self.lang:
            # ⚠️ 先查 plugin 段（plugin_language.json）再退回 nav 段，否则切英文仍是中文兜底
            for module in ("plugin", "nav"):
                text = self.lang.get_text(module, key)
                if text != key:
                    return text
        defaults = {
            "plugins_title": "插件",
            "plugins_hint": "一个文件夹就是一个插件，放在 .ToolsGCP/plugins 下。"
                            "装好之后点「重新加载」即可生效。",
            "want_dev": "我想开发", "reload": "重新加载", "open_dir": "打开插件目录",
            "open_readme": "开发文档", "enable": "启用", "disable": "禁用",
            "delete": "删除插件", "no_desc": "（没有填写说明）",
            "empty": "还没有插件。点右上角「我想开发」看看怎么写一个。",
            "layout_grid": "井字排版", "layout_list": "列表排版",
            "builtin_tip": "内置示例插件，不可删除",
            "by_author": "作者：{name}",
            "deleted": "已删除插件",
            "confirm_delete": "确定要删除插件「{name}」吗？插件文件夹会被整个删掉。",
            "toggle_tip": "打开 / 关闭这个插件", "switch_on": "已开启",
            "switch_off": "已关闭", "toggle_hint": "启用",
            # 卡片右上角的状态徽章：已启用=绿、已禁用=红
            "status_enabled": "已启用", "status_disabled": "已禁用",
            "status_error": "加载失败",
            "search_plugin": "搜索插件（名称 / id / 作者）",
            "no_match": "没有匹配的插件，换个关键词试试。",
            "count": "共 {total} 个，已启用 {enabled} 个",
            "note_button": "备注", "note_placeholder": "写个备注（最多 20 字）",
            "note_tip": "给自己留个备注，Enter 保存，Esc 取消",
            "note_saved": "备注已保存",
            "config_button": "配置界面",
            "config_title": "{name} · 配置界面",
            "config_unavailable": "这个插件没有配置界面（或没加载成功）",
            "config_back": "返回插件列表",
        }
        return defaults.get(key, key)

    # ---------- 列表 ----------
    def _clear_cards(self):
        """清空两种排版下的所有条目"""
        self.cards_grid.clear()
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._cards = []
        self._rows = []

    def change_layout(self, key: str):
        """切换排版：grid（井字形）/ list（一行一个）。"""
        key = key or "grid"
        self._layout_key = key
        self.cards_grid.setVisible(key == "grid")
        self.rows_host.setVisible(key == "list")
        if self.manager is not None and getattr(self.manager, "settings_manager", None):
            self.manager.settings_manager.update_setting("plugin_view", key)
        self.refresh_list()

    def current_layout(self) -> str:
        return self._layout_key

    def refresh_list(self):
        self._clear_cards()
        if self.manager is None:
            self.count_label.setText("")
            return

        texts = {
            "delete": self.get_text("delete"),
            "no_desc": self.get_text("no_desc"),
            "builtin_tip": self.get_text("builtin_tip"),
            "by_author": self.get_text("by_author"),
            "toggle_tip": self.get_text("toggle_tip"),
            "toggle_hint": self.get_text("toggle_hint"),
            "switch_on": self.get_text("switch_on"),
            "switch_off": self.get_text("switch_off"),
            # 状态徽章（卡片右上角）：已启用 = 绿 / 已禁用 = 红
            "status_enabled": self.get_text("status_enabled"),
            "status_disabled": self.get_text("status_disabled"),
            "status_error": self.get_text("status_error"),
            # 备注（卡片左下角 / 列表行里的内联编辑器）；⚠️ 这三个原来漏了，切英文时按钮还是"备注"
            "note_button": self.get_text("note_button"),
            "note_placeholder": self.get_text("note_placeholder"),
            "note_tip": self.get_text("note_tip"),
            "config_button": self.get_text("config_button"),
            "config_unavailable": self.get_text("config_unavailable"),
        }
        # 搜索框里的关键词：名称 / id / 作者 / 说明 命中任意一个就显示
        keyword = ""
        if hasattr(self, "search_edit"):
            keyword = str(self.search_edit.text() or "").strip().lower()

        def matched(info) -> bool:
            if not keyword:
                return True
            haystack = " ".join(str(x or "") for x in (
                info.name, info.id, info.author, info.description)).lower()
            return keyword in haystack

        shown = [p for p in self.manager.plugins if matched(p)]

        if self._layout_key == "list":
            for info in shown:
                row = PluginRow(info, self.rows_host, texts)
                row.toggle_clicked.connect(self._on_card_toggle)
                row.delete_clicked.connect(self._on_card_delete)
                row.config_clicked.connect(self.open_config)
                # 列表排版下的备注和卡片一样要能存下来
                row.note_changed.connect(self._on_note_changed)
                self.rows_layout.addWidget(row)
                self._rows.append(row)
        else:
            for info in shown:
                card = PluginCard(info, self.scroll_area.widget(), texts)
                card.toggle_clicked.connect(self._on_card_toggle)
                card.delete_clicked.connect(self._on_card_delete)
                card.config_clicked.connect(self.open_config)
                card.note_changed.connect(self._on_note_changed)
                self.cards_grid.add_item(card)
                self._cards.append(card)
            self.cards_grid.set_items(self._cards)

        total = len(self.manager.plugins)
        enabled = len([p for p in self.manager.plugins if p.status == STATUS_OK])
        try:
            if keyword:
                self.count_label.setText(self.get_text("count_filtered").format(
                    total=total, enabled=enabled, shown=len(shown)))
            else:
                self.count_label.setText(self.get_text("count").format(
                    total=total, enabled=enabled))
        except Exception:
            # ⚠️ 兜底文案也要用当前语言（以前这里写死中文，英文/繁体用户会看到简体）
            if keyword:
                self.count_label.setText(self.get_text("count_filtered").format(
                    total=total, enabled=enabled, shown=len(shown)))
            else:
                self.count_label.setText(self.get_text("count").format(
                    total=total, enabled=enabled))
        # 一组都没显示出来时才提示（搜不到给一句提示，别让人以为列表坏了）
        if not self.manager.plugins:
            self.empty_label.setText(self.get_text("empty"))
            self.empty_label.setVisible(True)
        elif not shown:
            self.empty_label.setText(self.get_text("no_match"))
            self.empty_label.setVisible(True)
        else:
            self.empty_label.setVisible(False)

    # ---------- 卡片动作 ----------
    def _on_card_toggle(self, info):
        """开关被点了：真正启用/禁用这个插件。

        ⚠️ 不能立刻 refresh_list()：开关圆点在播动画，马上重建卡片会把控件销毁，看起来就没有过渡动画。
        所以先只同步这一个开关的状态，稍后再刷新列表。
        """
        if self.manager is None:
            return
        enable = info.status == STATUS_DISABLED
        self.manager.set_enabled(info, enable)
        self.manager.reload_plugin(info)

        # ⚠️⚠️ 插件中心这个「启用/停用」和插件配置界面里的「总开关」是两层，都满足才真的生效。
        #    只在插件中心打开、配置里总开关还关着的话，插件等于没生效（AI 会没有工具却照样回话）。
        #    manifest 里声明了 enabled_setting 的插件，这里跟着一起写。
        self._sync_enabled_setting(info, enable)

        # 停用/重载会把插件页面销毁 —— 如果用户正开着这个插件的界面，先退回列表
        if getattr(info, "page", None) is None:
            try:
                self.close_config()
            except Exception:
                pass

        # ⚠️ 制作器只是"配置 + 规则"，真正生成插件靠 Agent 的工具往返，所以启用时把搭子一起启用
        if enable:
            self._enable_companion(info)

        # 只更新这一个卡片/一行（不影响正在播的动画）
        for holder in list(self._cards) + list(self._rows):
            if getattr(holder, "info", None) is info:
                holder._apply_status()
        self.show_message(f"{info.name}: "
                          f"{self.get_text('enable') if enable else self.get_text('disable')}",
                          "success" if enable else "info")
        # 等动画播完再重建列表（240ms > 开关动画的 100ms）
        QTimer.singleShot(240, self.refresh_list)

    def _enable_companion(self, info) -> bool:
        """把"搭子插件"一起启用（manifest 里的 "companion": "插件id"）。

        ⚠️ 只开不关：单独关掉 Agent 不该反过来把制作器也关了；搭子的总开关设置也一并同步。
        """
        try:
            manifest = getattr(info, "manifest", None) or {}
            companion_id = str(manifest.get("companion") or "").strip()
        except Exception:
            return False
        if not companion_id or self.manager is None:
            return False
        for other in self.manager.plugins:
            if other.id != companion_id or other.status == STATUS_OK:
                continue
            try:
                self.manager.set_enabled(other, True)
                self.manager.reload_plugin(other)
                self._sync_enabled_setting(other, True)
                self.manager.plugin_log("管理器", f"随「{info.name}」一起启用了「{other.name}」")
            except Exception:
                return False
            return True
        return False

    def _sync_enabled_setting(self, info, enable: bool):
        """把插件中心这个开关同步到插件自己声明的"总开关"设置项。

        实现只有一份（PluginManager.sync_enabled_setting），两处各写一份迟早会跑偏。
        ⚠️ 写失败不能影响开关本身（用户的意图是启用插件，那件事已经做完了）。
        """
        manager = self.manager
        if manager is None:
            return
        try:
            manager.sync_enabled_setting(info, enable)
        except Exception:
            pass

    def _on_note_changed(self, plugin_id: str, note: str):
        """插件卡片左下角的备注存下来了（Enter 保存时触发）。

        不重建列表：用户刚敲完字，卡片一刷新输入框就没了，体验很跳。
        """
        if self.manager is None:
            return
        self.manager.set_note(plugin_id, note)
        self.show_message(f"{self.get_text('note_saved')}"
                          + (f"：{note}" if note else ""), "info")

    def _on_card_delete(self, info):
        if getattr(info, "protected", False):
            self.show_message(self.get_text("builtin_tip"), "warning")
            return
        box = MessageBox(self.get_text("delete"),
                         self.get_text("confirm_delete").format(name=info.name), self)
        box.yesButton.setText(self.get_text("delete"))
        box.cancelButton.setText(self.get_text("dialog_cancel"))
        if not box.exec():
            return
        try:
            shutil.rmtree(info.dir)
        except Exception as e:
            self.show_message(str(e), "error")
            return
        self.manager.plugins = [p for p in self.manager.plugins if p.id != info.id]
        self.manager.disabled.discard(info.id)
        self.manager._save_state()
        self.refresh_list()
        self.manager.plugin_log(info.name, "插件已删除")
        self.show_message(f"{self.get_text('deleted')}: {info.name}", "info")

    # ---------- 顶部按钮 ----------
    # 加载动画至少显示这么久，否则重载太快只看到"闪一下"，像没反应
    RELOAD_MIN_MS = 420

    def reload_plugins(self):
        """重新加载全部插件：按钮文字变成不确定进度环 + 整页加载动画。"""
        if self.manager is None or self._reloading:
            return
        self._set_reloading(True)
        # ⚠️ 先让界面把加载态画出来再干活：load_all() 是同步重活，直接干这一帧轮不到重绘
        QTimer.singleShot(0, self._do_reload)

    def _do_reload(self):
        started = time.monotonic()
        try:
            self.manager.load_all()
            self.refresh_list()
            self.manager.plugin_log("管理器", "已重新加载全部插件")
        except Exception as exc:
            self.show_message(str(exc), "error")
        finally:
            # 至少显示 RELOAD_MIN_MS，免得"闪一下"看着像没反应
            remain = self.RELOAD_MIN_MS - int((time.monotonic() - started) * 1000)
            QTimer.singleShot(max(0, remain), self._finish_reload)

    def _finish_reload(self):
        self._set_reloading(False)
        try:
            self.show_message(f"{self.get_text('reload')}: "
                              f"{len(self.manager.plugins)} 个", "success")
        except Exception:
            pass

    def _reload_buttons(self) -> list:
        """只有「重新加载」这一个按钮变进度环（别顺手把「打开插件目录」「开发文档」也换掉）。"""
        return [getattr(self, "reload_btn", None)]

    def _list_chrome(self) -> list:
        """加载时要藏起来的只有插件列表本身。

        标题、条目数、搜索框、工具按钮、排版切换、提示行一律保持原样，只把"插件们的显示区"换成加载动画。
        """
        return [getattr(self, name, None)
                for name in ("scroll_area", "empty_label")]

    def _set_reloading(self, loading: bool):
        """进 / 出"重新加载中"这个状态：只动 reload_btn 和插件列表区，其余控件一个都不碰。"""
        self._reloading = bool(loading)
        buttons = self._reload_buttons()
        if loading:
            # 1) 按钮上的文字**和图标**都收起来，中间换成不确定进度环（环是按钮的子控件、居中摆好）
            for button in buttons:
                if button is None:
                    continue
                try:
                    ring = getattr(button, "_loading_ring", None)
                    if ring is None:
                        ring = IndeterminateProgressRing(button)
                        ring.setFixedSize(18, 18)
                        ring.setStrokeWidth(2.4)
                        ring.setCursor(Qt.BusyCursor)
                        button._loading_ring = ring
                    button._plain_text = button.text()
                    try:
                        button._plain_icon = button.icon()
                        button.setIcon(QIcon())
                    except Exception:
                        button._plain_icon = None
                    button.setText("")
                    # ⚠️ 文字和图标清空后按钮 sizeHint 会缩水、工具栏跟着抖，
                    #    所以加载期间把尺寸钉死（min / max / size 三样都存，结束原样还回去）
                    try:
                        button._plain_min = button.minimumSize()
                        button._plain_max = button.maximumSize()
                        button._plain_size = button.size()
                        button.setFixedSize(button._plain_size)
                    except Exception:
                        button._plain_min = None
                        button._plain_max = None
                        button._plain_size = None
                    size = ring.size()
                    ring.move(max(0, (button.width() - size.width()) // 2),
                              max(0, (button.height() - size.height()) // 2))
                    ring.show()
                    ring.raise_()
                except Exception:
                    pass
            # 2) 只把"插件们的显示区"藏起来
            for widget in self._list_chrome():
                if widget is not None:
                    widget.hide()
            # 3) 同一块位置换成搜索页那套加载 ui
            try:
                from ..widgets.apps_index_framework import LoadingWidget
                if self._loading_widget is None:
                    self._loading_widget = LoadingWidget(self.loading_host)
                    self.loading_layout.addWidget(self._loading_widget, 0,
                                                  Qt.AlignCenter)
                self.loading_host.show()
            except Exception:
                self.loading_host.show()
        else:
            for button in buttons:
                if button is None:
                    continue
                try:
                    ring = getattr(button, "_loading_ring", None)
                    if ring is not None:
                        ring.hide()
                    if getattr(button, "_plain_text", None) is not None:
                        button.setText(button._plain_text)
                    icon = getattr(button, "_plain_icon", None)
                    if icon is not None:
                        button.setIcon(icon)
                        button._plain_icon = None
                    # 尺寸放开（重新交给布局自动算，见上面 setFixedSize 的说明）
                    if getattr(button, "_plain_size", None) is not None:
                        button.setMinimumSize(button._plain_min)
                        button.setMaximumSize(button._plain_max)
                        button._plain_size = None
                except Exception:
                    pass
            widget = self._loading_widget
            self._loading_widget = None
            if widget is not None:
                try:
                    stop = getattr(widget, "stop", None)
                    if callable(stop):
                        stop()
                    self.loading_layout.removeWidget(widget)
                    widget.setParent(None)
                    widget.deleteLater()
                except Exception:
                    pass
            self.loading_host.hide()
            # 插件列表按当前排版重新露出来
            try:
                self.cards_grid.setVisible(self._layout_key == "grid")
                self.rows_host.setVisible(self._layout_key == "list")
                has_items = bool(self._cards or self._rows)
                if has_items:
                    self.scroll_area.show()
                    self.empty_label.hide()
                else:
                    self.empty_label.show()
            except Exception:
                pass

    def open_plugins_dir(self):
        if self.manager is None:
            return
        os.makedirs(self.manager.plugins_dir, exist_ok=True)
        try:
            os.startfile(self.manager.plugins_dir)
        except Exception as e:
            self.show_message(str(e), "error")

    def open_readme(self):
        if self.manager is None:
            return
        path = os.path.join(self.manager.plugins_dir, "README.md")
        if not os.path.exists(path):
            self.show_message(f"找不到 {path}", "error")
            return
        try:
            os.startfile(path)
        except Exception as e:
            self.show_message(str(e), "error")

    def show_dev_guide(self):
        dialog = DevGuideDialog(self, self.manager.plugins_dir if self.manager else "")
        dialog.exec()

    # ---------- 提示 ----------
    def show_message(self, message, msg_type="info"):
        # ⚠️ 标题走 common 模块（成功 / 错误 / 提示 / 信息），不再写死中文
        from ..core.language_manager import get_toast_title
        kwargs = dict(orient=Qt.Horizontal, isClosable=True,
                      position=InfoBarPosition.TOP, duration=3000, parent=self)
        if msg_type == "success":
            InfoBar.success(title=get_toast_title("success", self.lang),
                            content=message, **kwargs)
        elif msg_type == "error":
            InfoBar.error(title=get_toast_title("error", self.lang),
                          content=message, **kwargs)
        elif msg_type == "warning":
            InfoBar.warning(title=get_toast_title("warning", self.lang),
                            content=message, **kwargs)
        else:
            InfoBar.info(title=get_toast_title("info", self.lang),
                         content=message, **kwargs)

    def refresh_theme(self):
        """主题变了：重上滚动条样式，并让所有自制开关/徽章跟着换配色"""
        self._apply_scrollbar_style()
        dark = bool(isDarkTheme())
        for holder in list(self._cards) + list(self._rows):
            switch = getattr(holder, "toggle_switch", None)
            if switch is not None:
                switch.apply_theme(dark)
            # 状态徽章（绿/红）和备注按钮的 label 图标也是自己画的，要重新上色
            if hasattr(holder, "refresh_theme"):
                holder.refresh_theme()
            elif hasattr(holder, "_apply_status"):
                holder._apply_status()
