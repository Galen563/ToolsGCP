"""
资源制作器 —— 四个功能页面

投稿表单 FormPage / 资源浏览器 BrowserPage / 批量合成 BatchPage / 使用说明 HelpPage。
文案统一走 self._t()（拿不到译文用中文兜底）；宿主依赖 ResourceMakerHost；
业务逻辑（读写、备份、图标回收、批量合并、表格编辑）逐行照搬独立工具，未作"优化"。
"""

import json
import os
import re
import shutil
import time
import zipfile
from datetime import datetime

from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QListWidgetItem, QScrollArea, QStackedWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, CardWidget, ComboBox, EditableComboBox,
    FluentIcon as FIF, InfoBar, InfoBarPosition, LineEdit, ListWidget,
    MessageBox, PillPushButton, PlainTextEdit, PrimaryPushButton, PushButton,
    SegmentedWidget, SimpleCardWidget, StrongBodyLabel, SwitchButton, TableWidget,
)

from ..utils.smooth_scroll import install_smooth_scroll
from ..widgets.chip_flow import ChipFlow

from .settings.theme import SIZES, tokens
from .settings.widgets import TipIcon
from .resource_maker_core import (
    ARCHITECTURES, CATEGORIES,
    FORM_LABEL_WIDTH, ICON_DIR_NAME, image_filter,
    REPO_PLATFORMS, RESOURCE_FILE_NAME, SCHEMA_VERSION, SYSTEM_PLATFORMS,
    apply_themed_scrollbar,
    as_list, auto_http_url, backup_library, copy_icon, detect_repo_platform,
    find_project_root, host_call, host_value, icon_base_from_name, last_backup_error,
    load_library, next_code, normalize_repo_url, now_listed_at, resolve_i18n_for_maker,
    slugify, split_categories, split_tags, theme_tokens, unique_name_in, write_json,
)
from ..core import resource_schema


class MakerPageMixin:
    """给四个功能页 / 预览卡提供文案（统一走 self._t(key, "中文原文")，拿不到就用它兜底）"""

    def _t(self, key: str, fallback: str = "") -> str:
        # 页面自己有 host 就直接问；预览卡这类小控件只能顺着父子链往上找
        getter = getattr(getattr(self, "host", None), "get_text", None)
        node = self if not callable(getter) else None
        while node is not None and not callable(getter):
            node = node.parentWidget()
            getter = getattr(node, "get_text", None)
        if callable(getter):
            try:
                text = getter(key)
                if text and text != key:
                    return text
            except Exception:
                pass
        return fallback or key

    # ---------- 资源库术语的多语言 ----------
    # 放在 mixin 上是因为浏览页 / 批量页也要用（类别下拉、胶囊、类别列都靠它）
    def _term(self, value: str) -> str:
        """资源库术语（类别 / 标签 / 系统 / 架构）的显示译名"""
        try:
            from ..core.language_manager import translate_term
            return translate_term(value)
        except Exception:
            return str(value or "")

    def _canonical_term(self, text: str) -> str:
        """把界面上的（可能是译名的）词还原成资源库里的规范值；认不出来原样返回"""
        text = str(text or "").strip()
        if not text:
            return ""
        try:
            from ..core.language_manager import translate_term
            for canonical in (tuple(CATEGORIES) + tuple(SYSTEM_PLATFORMS)
                              + tuple(ARCHITECTURES)):
                if canonical == text:
                    return canonical
                if translate_term(canonical) == text:
                    return canonical
        except Exception:
            pass
        return text

# 尺寸：全部取自设置页的设计规范（settings/theme.py）
CARD_RADIUS = SIZES["card_radius"]          # 10
CARD_PADDING = SIZES["card_padding"]        # 20
CARD_GAP = SIZES["card_gap"]                # 卡片之间 16
SECTION_GAP = SIZES["section_gap"]          # 板块之间 32
CONTROL_WIDTH = SIZES["control_width"]      # 右侧控件统一 200

# 右侧「预览 + 产出」列宽度（减掉卡片内边距 20×2 → 里面剩 240）
# ⚠️ 不要再放大（曾放大到 320 把左边表单列挤窄 40px）
SIDE_CARD_W = 280
PREVIEW_INNER_W = SIDE_CARD_W - CARD_PADDING * 2

# 表单两列布局的最低宽度：低于这个值就把右列挪到表单下面（见 FormPage._sync_columns）
TWO_COLUMN_MIN_WIDTH = 820

# 「使用说明」正文的最大宽度：说明书是长行文字，一行太长会串行（见 HelpPage._add_block）
HELP_TEXT_MAX_WIDTH = 900

# 滚动区底色一律透明，交给主程序画（自己刷 page 色会和别的页面对不上，像块补丁）
SCROLL_QSS = """
    QScrollArea { border: none; background: transparent; }
    QWidget#qt_scrollarea_viewport { background: transparent; }
    QScrollArea > QWidget > QWidget { background: transparent; }
"""

HELP_TEXT = """ToolsGCP 资源制作器 —— 使用说明

【这个工具是干什么的】
  把"我想让 ToolsGCP 收录这个软件"变成一份规范的数据。
  填完表单后可以：生成稿件发给作者、直接追加进本地资源库、或另存为一份私有资源库。

【哪些是必填的】
  只有两项是必填：名称、标识 id。
  其它全部可以留空（留空的字段不会写进 JSON，卡片上也不会显示那一项）。
  留空时程序只是提示一句，不会拦着你产出。

【怎么填】
  · 名称：软件的名字，会和官方叫法保持一致。填这里的时候，标识 id 会自动跟着生成。
  · 标识 id：资源库里的唯一标识，只允许小写字母/数字/连字符。
  · 简介：会显示在卡片上的一句话说明。
  · 补充：简介写不下的内容放这里（详细功能、系统要求、注意事项……），
          存进 JSON 的 supplement 字段，卡片上不显示。
  · 官网：只写 example.com 也会自动补成 https://。
  · 类别：决定它显示在搜索页的哪个分组下，也可以自己输入新类别。
  · 标签：默认跟着「类别」自动填；你自己改过标签以后就不再自动覆盖，
         想恢复联动就点标签右边的「跟随类别」按钮。写「官方」会显示成金色。

【图片（图标）怎么弄】
  点「导入图片」选一张图就行，剩下的交给程序：
  · 图片会自动复制到资源库的图标目录（.ToolsGCP/Icon）；
  · 不管原图叫什么名字，都会被改成「名称」里写的那个名字（例如 LocalSend.png）；
  · 之后改「名称」，图标文件也会跟着改名，不用你手动去文件夹里改；
  · 如果这个名字已经被别的资源占着，会自动加 -2、-3，绝不覆盖别人的图；
  · 复制完会再核对一遍文件，确认真的写进目录里了。
  建议用 256x256 以上的正方形 PNG，背景透明最好看；gif 也可以（卡片上会动）。

【上架时间（listed_at）】
  新资源第一次写进资源库时会自动记下时间（例如 2026-09-21 00:40:14），
  编辑已有条目不会改动它。搜索页的「更多筛选 → 更新时间」就是按它筛的。

【编码（code）是什么】
  每条资源会分配一个唯一编码（TG-000001 这种）。部署清单就是靠编码来指代程序的，
  所以请不要随便改已有资源的编码。

【几种产出方式的区别】
  · 写入资源库：直接改你本机的 .ToolsGCP/ToolsGCP-Resources.json（始终是这一个文件，不会
              再生成新的资源库 JSON）；改动前会自动备份到 .ToolsGCP/backups/ 并在那里轮换。
  · 生成稿件：输出到 ResourceDrafts/<id>/ 下，含 resource.json 和图片，
              还会打一个同名 zip，直接把这个 zip 发给作者就行。
  · 另存为独立资源库：生成一份只含这条资源的完整 JSON，
              适合做自己的私有资源库（图片会一起复制过去）。

【浏览 / 删除页怎么用】
  · 双击某个单元格（名称、类别、标签、官网、仓库、简介、上架时间……）就地变成输入框，改完自动保存；
  · 双击「图标」那一格会弹出选图窗口，选完自动存进图标目录并改成应用名；
  · 名称那一格不允许清空；其它可选字段清空就等于把它从 JSON 里删掉；
  · 想大改就选中一行点「载入到制作资源」，或者右键选「载入到制作资源」；
  · 每次修改写盘前都会自动备份，删条目也会顺手清理没人再用的图片。

【提示】
  表单里改了任何内容，右侧预览都会实时更新；点「生成/追加」前会自动做一次校验。
"""


# ---------- 通用小部件 ----------
def is_valid_id(text: str) -> bool:
    """标识 id 只允许小写字母/数字/连字符"""
    return bool(re.fullmatch(r"[a-z0-9\-]+", str(text or "")))


def has_http_scheme(text: str) -> bool:
    """链接是不是已经写了 http(s)://"""
    return bool(re.match(r"^https?://", str(text or ""), re.I))


def switch_to_page(host, page):
    """让宿主切到某一页（宿主没实现就安静跳过）"""
    host_call(host, "switchTo", page)


def elide_path(path: str, limit: int = 72) -> str:
    """路径太长时从中间省略（完整路径放 tooltip）；⚠️ 不能硬换行，会把左边标题挤出卡片"""
    text = str(path or "")
    if len(text) <= limit:
        return text
    head = text[: max(8, limit // 2 - 1)]
    tail = text[-(limit // 2 - 2):]
    return f"{head}…{tail}"


def make_divider(parent, color: str = "") -> QFrame:
    """1px 分隔线（颜色默认取当前主题的卡片描边色）"""
    line = QFrame(parent)
    line.setFixedHeight(1)
    line.setStyleSheet(
        f"background-color: {color or theme_tokens()['card_border']};")
    return line


def make_step_badge(parent, text: str) -> CaptionLabel:
    """卡片标题前面那个序号小徽标（① ② ③ 那种流程感）"""
    c = theme_tokens()
    badge = CaptionLabel(str(text), parent)
    badge.setAlignment(Qt.AlignCenter)
    badge.setFixedSize(20, 20)
    badge.setStyleSheet(
        f"background: {c['accent_soft']}; color: {c['accent']};"
        f"border-radius: 10px; font-weight: 600;")
    return badge


def make_card(parent, title: str = "", step: int = 0):
    """一张卡片：可选标题行（+ 序号徽标）+ 分隔线 + 内容区，返回 (卡片, 内容布局)"""
    card = CardWidget(parent)
    card.setBorderRadius(CARD_RADIUS)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(CARD_PADDING, CARD_PADDING - 2, CARD_PADDING, CARD_PADDING - 2)
    layout.setSpacing(12)

    card._makers_badges = []
    card._makers_dividers = []
    if title:
        head = QHBoxLayout()
        head.setSpacing(8)
        if step:
            badge = make_step_badge(card, str(step))
            card._makers_badges.append(badge)
            head.addWidget(badge, 0, Qt.AlignVCenter)
        head.addWidget(StrongBodyLabel(title, card))
        head.addStretch(1)
        layout.addLayout(head)
        line = make_divider(card)
        card._makers_dividers.append(line)
        layout.addWidget(line)
    return card, layout


def make_scroll(parent) -> QScrollArea:
    """统一的滚动区：无边框、横向不滚、主题化细滚动条 + 惯性滚动"""
    scroll = QScrollArea(parent)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setStyleSheet(SCROLL_QSS)
    apply_themed_scrollbar(scroll)
    install_smooth_scroll(scroll)
    return scroll


# ---------- 上色（qfluentwidgets 的标签/输入框只能从"自己身上"改色）----------
def style_role_color(label, key: str = "text_secondary"):
    """按 token 语义色给标签上色；⚠️ 只能用 setTextColor（父级属性选择器压不过库的样式表）"""
    light, dark = tokens(False)[key], tokens(True)[key]
    setter = getattr(label, "setTextColor", None)
    if callable(setter):
        setter(light, dark)
    else:
        label.setStyleSheet(f"color: {light};")
    return label


def style_hint(label):
    """次要文字：副说明、路径、计数这些小字"""
    return style_role_color(label, "text_secondary")


def style_readonly(widget):
    """只读输入框（编码 / 图标路径）：文字弱一档；⚠️ 只能用库的 setCustomStyleSheet"""
    light, dark = tokens(False)["text_disabled"], tokens(True)["text_disabled"]
    try:
        from qfluentwidgets import setCustomStyleSheet
        setCustomStyleSheet(widget, f"LineEdit{{color: {light};}}",
                            f"LineEdit{{color: {dark};}}")
    except Exception:
        widget.setStyleSheet(f"color: {light};")
    return widget


class FormGrid(QGridLayout):
    """表单网格：左列标签（定宽）+ 右列控件；标签列定宽才能让控件左边缘行行对齐"""

    def __init__(self, parent, label_width: int = FORM_LABEL_WIDTH):
        # ⚠️ 不能写 super().__init__(parent)：卡片身上已有标题用的 QVBoxLayout，会报
        #    "Attempting to add QLayout to CardWidget, which already has a layout"。
        super().__init__()
        self._parent_widget = parent
        self.label_width = int(label_width)
        self.setContentsMargins(0, 0, 0, 0)
        self.setHorizontalSpacing(10)
        self.setVerticalSpacing(12)
        self._row = 0
        self.tips = []              # ⓘ 图标：主题切换时要重新上色

    def add_row(self, label_text: str, control, tip: str = "", align=None):
        """加一行；返回控件本身（大多用不上，链式写起来方便）"""
        cell = QWidget(self._parent_widget)
        cell.setFixedWidth(self.label_width)
        box = QHBoxLayout(cell)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        label = BodyLabel(str(label_text), cell)
        label.setWordWrap(False)
        box.addWidget(label)
        if tip:
            icon = TipIcon(tip, cell)
            self.tips.append(icon)
            box.addWidget(icon, 0, Qt.AlignVCenter)
        box.addStretch(1)

        self.addWidget(cell, self._row, 0, Qt.AlignLeft | Qt.AlignVCenter)
        if align is None:
            self.addWidget(control, self._row, 1)
        else:
            self.addWidget(control, self._row, 1, align)
        self._row += 1
        return control

    def add_gap(self, height: int = 6):
        """行与行之间的额外空隙（同一张卡片里再分小段用）"""
        spacer = QWidget(self._parent_widget)
        spacer.setFixedHeight(int(height))
        self.addWidget(spacer, self._row, 0, 1, 2)
        self._row += 1

    def apply_theme(self, dark: bool = None):
        for icon in self.tips:
            icon.apply_theme(dark)


def apply_card_theme(card, dark: bool = None):
    """卡片上的徽标 / 分隔线跟着主题换色（卡片背景由 qfluentwidgets 自己管）"""
    c = theme_tokens(dark)
    for badge in getattr(card, "_makers_badges", []):
        badge.setStyleSheet(
            f"background: {c['accent_soft']}; color: {c['accent']};"
            f"border-radius: 10px; font-weight: 600;")
    for line in getattr(card, "_makers_dividers", []):
        line.setStyleSheet(f"background-color: {c['card_border']};")


# ---------- 实时预览卡 ----------
class PreviewCard(MakerPageMixin, SimpleCardWidget):
    """右侧实时预览：尽量还原卡片在程序里的样子"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBorderRadius(CARD_RADIUS)
        self.setFixedWidth(PREVIEW_INNER_W)
        self.setMinimumHeight(190)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        upper = QHBoxLayout()
        upper.setSpacing(12)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(72, 72)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet("background: transparent;")
        upper.addWidget(self.icon_label, 0, Qt.AlignTop)

        right = QVBoxLayout()
        right.setSpacing(6)
        self.name_label = StrongBodyLabel(self._t("preview_name", "(name)"), self)
        right.addWidget(self.name_label)
        self.desc_label = CaptionLabel(self._t("preview_desc", "(description)"), self)
        self.desc_label.setWordWrap(True)
        right.addWidget(self.desc_label, 1)
        upper.addLayout(right, 1)
        layout.addLayout(upper)

        self.divider = make_divider(self)
        layout.addWidget(self.divider)

        self.tags_label = CaptionLabel("", self)
        self.tags_label.setWordWrap(True)
        layout.addWidget(self.tags_label)

    def update_preview(self, entry: dict, icon_path: str):
        self.name_label.setText(str(entry.get("name") or self._t("preview_name", "(name)")))
        desc = str(entry.get("description") or self._t("preview_desc", "(description)"))
        self.desc_label.setText(desc[:60] + ("..." if len(desc) > 60 else ""))

        tags = entry.get("tags") or []
        self.tags_label.setText("  ".join(f"[{t}]" for t in tags) or self._t("（无标签）"))

        pixmap = QPixmap()
        if icon_path and os.path.exists(icon_path) and not icon_path.lower().endswith(".gif"):
            pixmap = QPixmap(icon_path)
        if pixmap.isNull():
            self.icon_label.setText("?")
            self.icon_label.setStyleSheet(
                "background: rgba(128,128,128,60); border-radius: 8px; color: gray;")
        else:
            self.icon_label.setStyleSheet("background: transparent;")
            self.icon_label.setPixmap(
                pixmap.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))


# ---------- 投稿表单页 ----------
class FormPage(MakerPageMixin, QWidget):
    """投稿表单：左边填表、右边实时预览 + 产出按钮"""

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.setObjectName("formPage")
        self.host = host
        # 项目根：宿主给哪个用哪个
        self.project_root = str(host_value(host, "project_root", "") or "") or \
            find_project_root(os.path.dirname(os.path.abspath(__file__)))
        self.icon_source = ""          # 当前图标用的磁盘路径
        self._icon_lib_name = ""        # 图标目录里那份的真实文件名
        self._icon_lib_path = ""        # 它的完整路径
        self._icon_is_src = False       # 还在原位置（外部图片），没进图标目录
        self._icon_picked = False       # 这份图片是不是"用户为本条刚导入的"
        self._icon_owner_id = ""        # 这份图片属于资源库里哪一条
        self._loaded_id = ""
        self._loaded_name = ""          # 载入时那条的名称（判断用户是不是又在做新的一条）
        self._is_new_entry = True       # 表单现在是"一条还没入库的新资源"
        self._icon_dir_cache = ""       # 资源库 metadata.icon_dir（没有就用默认）
        self._form_grids = []           # 所有表单网格（主题切换时统一刷新 ⓘ）
        self._cards = []                # 所有卡片（主题切换时刷徽标/分隔线）
        self._tips = []                 # 不在网格里的 ⓘ（多语言卡片头部那个）
        self._two_column = True         # 当前是不是两列布局（见 _sync_columns）
        # 标签是否还跟着「类别」自动填：用户自己改过标签就变成 False
        self._tags_auto = True
        # 编辑旧条目时保留原本的上架时间；新资源才会写上"现在"
        self._listed_at = ""
        # 表单里已没有「下载直链」，但老条目可能带着，保存时原样写回（见 build_entry）。
        self._loaded_download_url = ""

        # 改「名称」时顺手把图标文件也改成新名字（防抖：停止输入 0.8 秒后改一次）
        self._icon_rename_timer = QTimer(self)
        self._icon_rename_timer.setSingleShot(True)
        self._icon_rename_timer.setInterval(800)
        self._icon_rename_timer.timeout.connect(self.apply_pending_icon_rename)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = make_scroll(self)
        outer.addWidget(self.scroll)
        # ⚠️ 整页样式表在**还没有子控件**的时候套上（见 _apply_page_stylesheet）
        self._apply_page_stylesheet()

        content = QWidget()
        self.scroll.setWidget(content)
        # 左右留白由外层页面负责（见 ResourceMakerInterface），这里只管纵向
        self.body = QGridLayout(content)
        self.body.setContentsMargins(0, 10, 0, 18)
        # 两列间距用 24 而不是板块间距 32：表单和右侧预览本来就是同一屏的两半
        self.body.setHorizontalSpacing(24)
        self.body.setVerticalSpacing(CARD_GAP)

        self._left = QWidget(content)
        self._left_box = QVBoxLayout(self._left)
        self._left_box.setContentsMargins(0, 0, 0, 0)
        self._left_box.setSpacing(CARD_GAP)
        self._left_box.setAlignment(Qt.AlignTop)
        self.body.addWidget(self._left, 0, 0)

        self.right_host = QWidget(content)
        self.right_box = QVBoxLayout(self.right_host)
        self.right_box.setContentsMargins(0, 0, 0, 0)
        self.right_box.setSpacing(CARD_GAP)
        self.right_box.setAlignment(Qt.AlignTop)
        self.body.addWidget(self.right_host, 0, 1, Qt.AlignTop)
        self.body.setColumnStretch(0, 1)
        self.body.setColumnStretch(1, 0)

        # 卡片还没进来之前不许算"两列/一列"（见 _sync_columns）
        self._build_done = False

    # ---------- 按需构建（由 ResourceMakerInterface 分步调用）----------
    def build_steps(self) -> list:
        """把"建控件"的活拆成一步一张卡片，返回 [(步骤名, 函数)]

        ⚠️ 整页一次建完要 130ms 且是同步执行的（"未响应"的来源），拆开后每步 3~30ms。
        """
        return [
            (self._t("基本信息卡片"), lambda: self._left_box.addWidget(
                self._build_basic_card(self._left))),
            (self._t("链接与简介卡片"), lambda: self._left_box.addWidget(
                self._build_content_card(self._left))),
            # ⚠️ 多语言卡片必须紧跟「链接与简介」：它是那三个字段的其它语言版本，
            #    放远了会被当成又一组新字段。
            (self._t("多语言字段卡片"), lambda: self._left_box.addWidget(
                self._build_i18n_card(self._left))),
            (self._t("补充说明卡片"), lambda: self._left_box.addWidget(
                self._build_extra_card(self._left))),
            (self._t("实时预览卡片"), lambda: self.right_box.addWidget(
                self._build_preview_card(self.right_host))),
            (self._t("产出卡片"), lambda: self.right_box.addWidget(
                self._build_action_card(self.right_host))),
        ]

    def finish_build(self):
        """卡片都加进来了：上主题、读资源库、补标签和预览（顺序同以前的 __init__ 末尾）"""
        self._build_done = True
        self.apply_theme()
        self.reload_library_info()
        self._tags_auto = True
        self._set_tags_text(self.category_combo.currentText().strip())
        self.refresh_preview()
        # 建完立刻按真实宽度定一次"两列 / 一列"，再延后一拍补一次
        # （刚建完时滚动区视口宽度可能还没落实，见 _sync_columns 的守卫）
        self._sync_columns()
        QTimer.singleShot(0, self._sync_columns)
        QTimer.singleShot(120, self._sync_columns)

    # ---------- 卡片 ----------
    def _new_card(self, parent, title: str, step: int = 0):
        card, layout = make_card(parent, title, step)
        self._cards.append(card)
        return card, layout

    def _mark_readonly(self, widget):
        """只读输入框（编码 / 图标路径）：文字更弱一档"""
        return style_readonly(widget)

    def _card(self, parent, title: str, step: int = 0) -> tuple:
        """一张卡片：标题 + 序号徽标 + 一条淡分隔线 + 内容区"""
        card, layout = self._new_card(parent, title, step)
        grid = FormGrid(card)
        layout.addLayout(grid)
        self._form_grids.append(grid)
        return card, grid

    def _build_i18n_card(self, parent):
        """多语言字段（默认开启）：按语言分页，分段控件选语言，下面只摆这一种语言的字段"""
        card, layout = self._new_card(
            parent, self._t("lang_fields_default_on", "Localized fields (submit all three languages)"),
            step=3)

        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(BodyLabel(
            self._t("lang_fields_hint", "Provide name and description per language"), card))
        i18n_tip = TipIcon(self._t("lang_fields_tip"), card)
        self._tips.append(i18n_tip)
        head.addWidget(i18n_tip)
        head.addStretch(1)
        self.i18n_switch = SwitchButton(card)
        self.i18n_switch.setChecked(True)       # 默认开：三种语言一起提交
        self.i18n_switch.checkedChanged.connect(self.on_i18n_toggled)
        head.addWidget(self.i18n_switch)
        layout.addLayout(head)

        self.i18n_body = QWidget(card)
        body = QVBoxLayout(self.i18n_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)

        self.i18n_lang_keys = ("简体中文", "繁體中文", "English")
        self.i18n_lang_labels = (
            self._t("zh_cn", "Simplified Chinese"),
            self._t("zh_tw", "Traditional Chinese"),
            "English",
        )
        self.i18n_segmented = SegmentedWidget(self.i18n_body)
        for index, label in enumerate(self.i18n_lang_labels):
            self.i18n_segmented.addItem(f"i18n{index}", label)
        self.i18n_segmented.currentItemChanged.connect(self._on_i18n_lang_changed)
        body.addWidget(self.i18n_segmented, 0, Qt.AlignLeft)

        self.i18n_stack = QStackedWidget(self.i18n_body)
        body.addWidget(self.i18n_stack)

        self.i18n_edits = {}
        self._i18n_lang_index = 0
        # ⚠️ 字典键必须用固定的规范语言名，不能用 self._t("zh_cn") —— 那是显示译文，
        #    英文界面下会变成 "Simplified Chinese"，写进 JSON 就成了读不出来的语言键。
        for lang_key in self.i18n_lang_keys:
            page = QWidget(self.i18n_stack)
            grid = FormGrid(page, label_width=FORM_LABEL_WIDTH)
            grid.setContentsMargins(0, 2, 0, 2)

            name_edit = LineEdit(page)
            name_edit.setPlaceholderText(
                self._t("ph_name_l10n", "Name (falls back to the one above)"))
            name_edit.textChanged.connect(self.refresh_preview)

            desc_edit = LineEdit(page)
            desc_edit.setPlaceholderText(
                self._t("ph_desc_main",
                        "One line about what it is and what it does"))
            desc_edit.textChanged.connect(self.on_desc_changed)

            intro_edit = PlainTextEdit(page)
            intro_edit.setPlaceholderText(
                self._t("ph_intro_main",
                        "Body text shown in the \"About\" section on the detail "
                        "page (optional): what the app does, its main features, "
                        "who it is for, what makes it special…"))
            intro_edit.setFixedHeight(84)
            intro_edit.textChanged.connect(self.on_intro_changed)

            supplement_edit = PlainTextEdit(page)
            supplement_edit.setPlaceholderText(
                self._t("ph_supplement_main",
                        "Extra notes (optional): use cases, caveats, system "
                        "requirements… stored in the JSON 'supplement' field"))
            supplement_edit.setFixedHeight(84)
            supplement_edit.textChanged.connect(self.refresh_preview)

            grid.add_row(self._t("name_required"), name_edit)
            grid.add_row(self._t("description"), desc_edit)
            grid.add_row(self._t("intro"), intro_edit)
            grid.add_row(self._t("supplement"), supplement_edit)
            self._form_grids.append(grid)

            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.addLayout(grid)
            page_layout.addStretch(1)

            self.i18n_stack.addWidget(page)
            self.i18n_edits[lang_key] = (name_edit, desc_edit, intro_edit,
                                         supplement_edit)

        self.i18n_segmented.setCurrentItem("i18n0")
        self.i18n_body.setVisible(True)
        layout.addWidget(self.i18n_body)
        # 让 desc/intro/supplement 别名指向当前语言那一页（见 _select_i18n_language）
        self._select_i18n_language(self._current_language_index())
        return card

    def _select_i18n_language(self, index: int):
        """把 desc_edit / intro_edit / supplement_edit 别名指到第 index 种语言那一页"""
        keys = list(self.i18n_edits.keys())
        if not keys:
            return
        index = max(0, min(int(index), len(keys) - 1))
        self._i18n_lang_index = index
        seg = getattr(self, "i18n_segmented", None)
        if seg is not None:
            # 同步分段控件（屏蔽信号，避免又绕回 _on_i18n_lang_changed）
            try:
                seg.blockSignals(True)
                seg.setCurrentItem(f"i18n{index}")
            except Exception:
                pass
            finally:
                try:
                    seg.blockSignals(False)
                except Exception:
                    pass
        edits = self.i18n_edits[keys[index]]
        # 名称仍然以「基本信息」那张卡片为准，这里只接管这三个长文本字段
        self.desc_edit, self.intro_edit, self.supplement_edit = (
            edits[1], edits[2], edits[3])
        self.refresh_preview()

    def _on_i18n_lang_changed(self, key: str):
        """切换多语言卡片里的语言页（同时把别名指过去）"""
        try:
            index = int(str(key).replace("i18n", ""))
        except (TypeError, ValueError):
            return
        if 0 <= index < self.i18n_stack.count():
            self.i18n_stack.setCurrentIndex(index)
        self._select_i18n_language(index)

    def on_i18n_toggled(self, checked: bool):
        self.i18n_body.setVisible(bool(checked))

    def i18n_enabled(self) -> bool:
        return bool(self.i18n_switch.isChecked())

    # 多语言卡片里的四列：字段名 -> 第几个控件
    I18N_FIELDS = ("name", "description", "intro", "supplement")

    @staticmethod
    def _plain_text(widget) -> str:
        """取控件里的文字（LineEdit / PlainTextEdit 都能用）；多行框先把换行压成空格"""
        getter = getattr(widget, "toPlainText", None)
        text = getter() if callable(getter) else widget.text()
        return str(text or "").replace("\n", " ").strip()

    @staticmethod
    def _set_plain_text(widget, text: str):
        """往控件里写文字（LineEdit 和 PlainTextEdit 都能用）"""
        setter = getattr(widget, "setPlainText", None)
        if callable(setter):
            setter(str(text or ""))
        else:
            widget.setText(str(text or ""))

    def apply_i18n_to_entry(self, entry: dict):
        """把多语言输入写进条目；⚠️ 必须在 schema 规范化之后调用，否则多语言会被压成一种"""
        if not self.i18n_enabled():
            return entry
        for index, field in enumerate(self.I18N_FIELDS):
            if field == "name":
                # 「名称」以基本信息卡片为准，多语言页的名称只是可选翻译
                pass
            values = {}
            for lang, edits in self.i18n_edits.items():
                text = self._plain_text(edits[index])
                if text:
                    values[lang] = text
            if not values:
                continue
            # 只填了一种语言 → 不写字典（entry 里已有正文，见 build_entry）
            if len(set(values.values())) == 1:
                continue
            entry[field] = values
        return entry

    def load_i18n_from_entry(self, entry: dict):
        """从已有条目回填多语言输入框"""
        fields = self.I18N_FIELDS
        has_i18n = any(isinstance(entry.get(f), dict) for f in fields)
        self.i18n_switch.setChecked(has_i18n)
        self.i18n_body.setVisible(has_i18n)
        for lang, edits in self.i18n_edits.items():
            for index, field in enumerate(fields):
                value = entry.get(field)
                text = value.get(lang, "") if isinstance(value, dict) else ""
                # 老条目该字段是纯字符串 → 填进简中那格，想补翻译就在旁边接着写
                if not text and lang == "简体中文" and isinstance(value, str):
                    text = value
                self._set_plain_text(edits[index], text)
        # ⚠️ 回填完切回当前界面语言那一页，否则载入中文条目却停在 English 页，像丢内容
        self._select_i18n_language(self._current_language_index())

    def _current_language_index(self) -> int:
        """当前界面语言在多语言页里的下标（不是那三种就回 0）"""
        try:
            current = str(getattr(self.lang, "current_language", "") or "")
        except Exception:
            current = ""
        keys = list(self.i18n_edits.keys())
        return keys.index(current) if current in keys else 0

    # ---------- 适用系统 / 架构（可多选的胶囊按钮）----------
    def _make_pill_row(self, parent, options, tip, label_of=None) -> tuple:
        """一排可多选的胶囊按钮，返回 (容器, {选项: 按钮})；⚠️ 容器必须是 ChipFlow"""
        label_of = label_of or (lambda value: value)
        holder = ChipFlow(parent, spacing=6, row_spacing=6)
        buttons = {}
        for name in options:
            label = label_of(name)
            btn = PillPushButton(label, holder)
            btn.setCheckable(True)
            btn.setFixedHeight(26)
            btn.setToolTip(tip)
            fm = btn.fontMetrics()
            btn.setFixedWidth(fm.horizontalAdvance(label) + 26)
            btn.toggled.connect(lambda _c=False: self.refresh_preview())
            buttons[name] = btn
        holder.set_widgets(list(buttons.values()))
        return holder, buttons

    @staticmethod
    def _checked_pills(buttons) -> list:
        return [name for name, btn in buttons.items() if btn.isChecked()]

    def _set_checked_pills(self, buttons, values):
        """回填：只勾选给定的值（大小写不敏感，"全平台" 之类的按原样匹配）"""
        wanted = {str(v).strip().lower() for v in (values or []) if str(v).strip()}
        for name, btn in buttons.items():
            btn.blockSignals(True)
            btn.setChecked(name.lower() in wanted)
            btn.blockSignals(False)

    def _build_basic_card(self, parent):
        card, grid = self._card(parent, self._t("basic_info", "Basics"), step=1)
        self.name_edit = LineEdit(card)
        self.name_edit.setPlaceholderText(self._t("ph_name", "e.g. LocalSend"))
        self.name_edit.textChanged.connect(self.on_name_changed)
        grid.add_row(self._t("name_required", "Name *"), self.name_edit,
                     self._t("软件的名字；导入图片后图片会被自动改成这个名字"))

        self.id_edit = LineEdit(card)
        self.id_edit.setPlaceholderText(self._t("ph_id", "Lowercase, e.g. localsend"))
        self.id_edit.textChanged.connect(self.on_id_changed)
        grid.add_row(self._t("id", "ID *"), self.id_edit,
                     self._t("资源库里的唯一标识，只允许小写字母/数字/连字符"))

        self.code_edit = self._mark_readonly(LineEdit(card))
        self.code_edit.setReadOnly(True)
        grid.add_row(self._t("code", "Code"), self.code_edit,
                     self._t("tip_code", "System-assigned unique code (optional); deploy manifests reference it"))

        self.category_combo = EditableComboBox(card)
        # ⚠️ 这里列的是当前语言的类别译名，落盘时靠 _canonical_term 还原成规范中文
        self.category_combo.addItems([self._term(name) for name in CATEGORIES])
        self.category_combo.setCurrentIndex(0)
        self.category_combo.currentTextChanged.connect(self.on_category_changed)
        self.category_combo.currentTextChanged.connect(self.refresh_preview)
        grid.add_row(self._t("category", "Category"), self.category_combo,
                     self._t("决定它显示在搜索页的哪个分组下，也可以直接输入新类别；\n填好后标签会自动跟着写"))

        sys_row, self.system_buttons = self._make_pill_row(
            card, SYSTEM_PLATFORMS,
            self._t("tip_none_decided", "Click to toggle; empty means undecided"),
            label_of=self._term)
        grid.add_row(self._t("platforms", "Platforms"), sys_row,
                     self._t("可多选；不选就是留空。\n现在只存进 JSON，主程序搜索页也能按它筛"))

        arch_row, self.arch_buttons = self._make_pill_row(
            card, ARCHITECTURES,
            self._t("tip_none", "Click to toggle; empty means not set"),
            label_of=self._term)
        grid.add_row(self._t("arch", "CPU architecture"), arch_row,
                     self._t("可多选；留空表示没填。例如 Windows 版常见 x64 / x86，\n手机端常见 arm64"))

        icon_row = QWidget(card)
        icon_layout = QHBoxLayout(icon_row)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setSpacing(8)
        self.icon_edit = self._mark_readonly(LineEdit(icon_row))
        self.icon_edit.setReadOnly(True)
        self.icon_edit.setPlaceholderText(self._t("no_image", "No image selected"))
        icon_layout.addWidget(self.icon_edit, 1)
        pick_btn = PushButton(self._t("import_image", "Import image"), icon_row, FIF.FOLDER)
        pick_btn.setToolTip(self._t("tip_import", "The image is copied into the icon folder and renamed after the name field"))
        pick_btn.clicked.connect(self.pick_icon)
        icon_layout.addWidget(pick_btn)
        grid.add_row(self._t("icon", "Icon"), icon_row,
                     self._t("可选。导入的图片会自动存到 .ToolsGCP/Icon，\n并按「名称」自动改名，不用自己整理文件名。\n支持 png / jpg / gif / ico / webp / svg，建议 256x256 以上"))

        tags_row = QWidget(card)
        tags_layout = QHBoxLayout(tags_row)
        tags_layout.setContentsMargins(0, 0, 0, 0)
        tags_layout.setSpacing(8)
        self.tags_edit = LineEdit(tags_row)
        self.tags_edit.setPlaceholderText(self._t("ph_tags", "e.g. tools, system, official"))
        # textEdited 只在用户手打时触发（程序 setText 不会），用它判断"用户改过"
        self.tags_edit.textEdited.connect(self.on_tags_edited)
        self.tags_edit.textChanged.connect(self.refresh_preview)
        tags_layout.addWidget(self.tags_edit, 1)
        self.tags_follow_btn = PushButton(self._t("follow_category", "Follow category"), tags_row, FIF.SYNC)
        self.tags_follow_btn.setToolTip(self._t("tip_follow_category", "Restore tags from the current category (keeps following it)"))
        self.tags_follow_btn.clicked.connect(self.restore_tags_follow)
        tags_layout.addWidget(self.tags_follow_btn)
        grid.add_row(self._t("tags", "Tags"), tags_row,
                     self._t("默认跟着「类别」自动填；你自己改过之后就不再自动覆盖，\n想恢复联动就点右边的「跟随类别」。写「官方」会显示成金色标签"))
        return card

    def restore_tags_follow(self):
        """把标签恢复成跟着类别走"""
        self._tags_auto = True
        self._set_tags_text(self.category_combo.currentText().strip())
        self.refresh_preview()

    def _build_repo_row(self, card):
        """开源仓库这一行的控件：平台下拉 + 固定前缀 + 输入框"""
        row = QWidget(card)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.repo_platform_combo = ComboBox(row)
        # 「自定义 / 不开源」是中文，按当前语言显示（GitHub / Gitee 本来就是拉丁名）
        for key, name, _prefix in REPO_PLATFORMS:
            self.repo_platform_combo.addItem(self._term(name) if _prefix == "" else name,
                                             userData=key)
        self.repo_platform_combo.setCurrentIndex(0)
        self.repo_platform_combo.setFixedWidth(110)
        self.repo_platform_combo.currentIndexChanged.connect(self.on_repo_platform_changed)
        layout.addWidget(self.repo_platform_combo)

        self.repo_prefix_label = BodyLabel("https://github.com/", row)
        style_hint(self.repo_prefix_label)
        layout.addWidget(self.repo_prefix_label)

        layout.addWidget(self.github_edit, 1)

        self.repo_preview_label = CaptionLabel("", row)
        style_hint(self.repo_preview_label)
        return row

    def current_repo_platform(self) -> str:
        return self.repo_platform_combo.currentData() or "github"

    def on_repo_platform_changed(self, _index=None):
        key = self.current_repo_platform()
        prefix = next((p for k, _n, p in REPO_PLATFORMS if k == key), "")
        if key == "none":
            self.repo_prefix_label.setText("")
            self.repo_prefix_label.hide()
            self.github_edit.setReadOnly(True)
            self.github_edit.setPlaceholderText(self._t("已选择「不开源」"))
        elif key == "custom":
            self.repo_prefix_label.setText("")
            self.repo_prefix_label.hide()
            self.github_edit.setReadOnly(False)
            self.github_edit.setPlaceholderText(self._t("https://你的仓库地址"))
        else:
            self.repo_prefix_label.setText(prefix)
            self.repo_prefix_label.show()
            self.github_edit.setReadOnly(False)
            self.github_edit.setPlaceholderText("owner/repo")
        self.refresh_preview()

    def on_repo_text_changed(self, _text=None):
        url = normalize_repo_url(self.current_repo_platform(), self.github_edit.text())
        self.repo_preview_label.setText(f"→ {url}" if url else "")
        self.refresh_preview()

    def _build_content_card(self, parent):
        """❷ 链接（只剩「官网」和「开源仓库」）；简介等三个字段只在多语言卡片里填"""
        card, grid = self._card(parent, self._t("links_only", "Links"), step=2)

        self.url_edit = LineEdit(card)
        self.url_edit.setPlaceholderText(self._t("ph_url", "https://example.com (optional)"))
        self.url_edit.textChanged.connect(self.refresh_preview)
        grid.add_row(self._t("url", "Website"), self.url_edit,
                     self._t("可选。点卡片上的「官网」时跳转的地址；\n只写 example.com 也行，保存时会自动补上 https://"))

        self.github_edit = LineEdit(card)
        self.github_edit.setPlaceholderText(self._t("ph_github", "owner/repo (or paste the full URL)"))
        self.github_edit.textChanged.connect(self.on_repo_text_changed)
        grid.add_row(self._t("github", "Github"), self._build_repo_row(card),
                     self._t("选好平台后会自动补上前缀；卡片右下角会出现仓库按钮"))
        grid.add_row("", self.repo_preview_label, align=Qt.AlignLeft)
        return card

    def _build_extra_card(self, parent):
        card, grid = self._card(parent, self._t("other_links", "Other links (optional)"))

        self.author_url_edit = LineEdit(card)
        self.author_url_edit.setPlaceholderText(self._t("ph_author_page", "Author page (optional)"))
        self.author_url_edit.textChanged.connect(self.refresh_preview)
        grid.add_row(self._t("author_page", "Author page"), self.author_url_edit)

        self.chat_edit = LineEdit(card)
        self.chat_edit.setPlaceholderText(self._t("ph_chat", "Chat / community link (optional)"))
        self.chat_edit.textChanged.connect(self.refresh_preview)
        grid.add_row(self._t("chat_url", "Chat / community"), self.chat_edit)
        return card

    def _build_preview_card(self, parent):
        card, layout = self._new_card(parent, self._t("preview", "Live preview"))
        card.setFixedWidth(SIDE_CARD_W)
        self.preview = PreviewCard(card)
        layout.addWidget(self.preview, 0, Qt.AlignHCenter)
        self.status_label = CaptionLabel("", card)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        return card

    def _build_action_card(self, parent):
        card, layout = self._new_card(parent, self._t("output", "Output"))
        card.setFixedWidth(SIDE_CARD_W)
        tip = CaptionLabel(self._t("then_do_one", "Once the required fields are filled, pick one of the three actions below"), card)
        tip.setWordWrap(True)
        style_hint(tip)
        layout.addWidget(tip)

        load_btn = PushButton(self._t("load_existing", "Load an existing entry"), card, FIF.DOWNLOAD)
        load_btn.clicked.connect(self.load_existing)
        layout.addWidget(load_btn)

        draft_btn = PrimaryPushButton(self._t("gen_draft", "Generate draft (send to author)"), card, FIF.SHARE)
        draft_btn.clicked.connect(self.export_draft)
        layout.addWidget(draft_btn)

        append_btn = PrimaryPushButton(self._t("append_local", "Append to local library"), card, FIF.ADD)
        append_btn.clicked.connect(self.append_to_library)
        layout.addWidget(append_btn)

        standalone_btn = PushButton(self._t("save_as_new", "Save as a separate library"), card, FIF.SAVE_AS)
        standalone_btn.clicked.connect(self.save_standalone)
        layout.addWidget(standalone_btn)

        clear_btn = PushButton(self._t("clear_form", "Clear form"), card, FIF.DELETE)
        clear_btn.clicked.connect(self.clear_form)
        layout.addWidget(clear_btn)

        self.library_label = CaptionLabel("", card)
        self.library_label.setWordWrap(True)
        layout.addWidget(self.library_label)
        return card

    # ---------- 布局 / 主题 ----------
    def _sync_columns(self):
        """宽度不够时把「预览 + 产出」整列挪到表单下面

        ⚠️ 两个守卫缺一不可：_build_done 之前不算，视口宽度 < SIDE_CARD_W 不下结论。
        """
        if not self._build_done:        # 卡片还没建完，算出来的宽度没意义
            return
        viewport_w = self.scroll.viewport().width()
        if viewport_w < SIDE_CARD_W:    # 还没排版好（首次显示时常见），别下结论
            return
        wide = viewport_w >= TWO_COLUMN_MIN_WIDTH
        if wide == self._two_column:
            return
        self._two_column = wide
        self.body.removeWidget(self.right_host)
        if wide:
            self.body.addWidget(self.right_host, 0, 1, Qt.AlignTop)
        else:
            self.body.addWidget(self.right_host, 1, 0, Qt.AlignTop)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_columns()

    def refresh_scrollbars(self):
        """主题变了要重新给滚动条上色"""
        apply_themed_scrollbar(self.scroll)

    def _apply_page_stylesheet(self):
        """整页样式表：只在骨架阶段套这一次

        ⚠️ 不能放进 apply_theme：卡片建好后 setStyleSheet 要重渲染所有子控件（60~100ms）。
        """
        self.setStyleSheet(f"""
            #formPage {{ background: transparent; }}
            {SCROLL_QSS}
        """)

    def apply_theme(self, dark: bool = None):
        """主题切换：滚动条 + 卡片上的徽标/分隔线 + 预览状态色（不重套整页样式表）"""
        self.refresh_scrollbars()
        for grid in self._form_grids:
            grid.apply_theme(dark)
        for icon in self._tips:
            icon.apply_theme(dark)
        for card in self._cards:
            apply_card_theme(card, dark)
        if hasattr(self, "preview"):
            self.preview.divider.setStyleSheet(
                f"background-color: {theme_tokens(dark)['card_border']};")
        if hasattr(self, "status_label"):
            self.refresh_preview()

    # 兼容别名：老的独立工具里这个方法叫 set_theme_style
    def set_theme_style(self, dark: bool = None):
        self.apply_theme(dark)

    # ---------- 图标存放 ----------
    # ⚠️ 原则是"磁盘说了算"：每次操作都重新问磁盘、改完再校验，不用缓存变量互相推。

    def preferred_icon_base(self) -> str:
        """图片要改成的名字：直接用「名称」输入框里的文字（为空时退回标识 id）"""
        return icon_base_from_name(self.name_edit.text(), self.id_edit.text().strip())

    def preferred_icon_name(self, src: str = "") -> str:
        """图片最终的完整文件名（扩展名沿用原图）"""
        src = src or self.icon_source or self._icon_lib_path
        ext = os.path.splitext(str(src or ""))[1].lower() or ".png"
        return f"{self.preferred_icon_base()}{ext}"

    def icon_dir_name(self) -> str:
        """资源库里 metadata.icon_dir 写的相对目录名"""
        if not self._icon_dir_cache:
            data = load_library(self.library_path)
            self._icon_dir_cache = str(
                (data.get("metadata") or {}).get("icon_dir") or ICON_DIR_NAME)
        return self._icon_dir_cache

    def library_icon_dir(self) -> str:
        """图标目录的完整路径（跟资源库 metadata.icon_dir 保持一致）"""
        name = self.icon_dir_name().strip("/\\").replace("/", os.sep)
        root = self.project_root or os.path.dirname(os.path.abspath(__file__))
        return os.path.join(root, name)

    @staticmethod
    def _same_file(a: str, b: str) -> bool:
        """两个路径是不是同一个文件（⚠️ Windows 不区分大小写，必须用 normcase 兜底）"""
        if not a or not b:
            return False
        try:
            if os.path.exists(a) and os.path.exists(b) and os.path.samefile(a, b):
                return True
        except Exception:
            pass
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))

    def _icon_in_use_elsewhere(self, name: str, exclude_id: str = "") -> bool:
        """这个图标文件是不是还被资源库里别的条目用着"""
        if not name:
            return False
        data = load_library(self.library_path)
        for r in data.get("resources", []):
            if exclude_id and r.get("id") == exclude_id:
                continue
            if os.path.normcase(os.path.basename(str(r.get("icon") or ""))) == \
                    os.path.normcase(name):
                return True
        return False

    def _entry_id(self) -> str:
        """本条资源在资源库里的 id（正在编辑旧的就用旧的，否则用输入框里的）"""
        return (self._loaded_id or self.id_edit.text().strip())

    # ---------- 「现在到底在做哪一条」 ----------
    # ⚠️ 追加完表单不会清空，不区分"新资源 / 库里已存在那条"就会把上一条已发布的图片改名。
    # _is_new_entry：True = 还没入库（可改名图片），False = 代表库里那条（绝不动磁盘文件）。

    def _editing_published(self) -> bool:
        """当前表单是在编辑"已经入库的那一条"吗"""
        return not self._is_new_entry

    def _looks_like_new_entry(self) -> bool:
        """名称/id 已经跟载入的那条不一样了吗（用户接着在做下一条）"""
        if not self._loaded_id:
            return True
        if self._loaded_name and self.name_edit.text().strip() != self._loaded_name:
            return True
        rid = self.id_edit.text().strip()
        if rid and rid != self._loaded_id:
            return True
        return False

    def _icon_owner(self, name: str) -> str:
        """磁盘上这个图标文件名，是被资源库里哪一条引用的（没有则空）"""
        name = os.path.basename(str(name or ""))
        if not name:
            return ""
        for r in load_library(self.library_path).get("resources", []):
            if os.path.normcase(os.path.basename(str(r.get("icon") or ""))) == \
                    os.path.normcase(name):
                return str(r.get("id") or "")
        return ""

    def _adopt_icon(self):
        """记住"现在这份图片是本条在用的"（导入 / 载入已有条目时）"""
        if self._icon_lib_name:
            self._icon_owner_id = self._entry_id()

    def _discard_inherited_icon(self):
        """切到新资源时忘掉手里这份图片（⚠️ 上一条的图片名已被 JSON 引用，不能改名）"""
        if self._icon_picked and self._owns_icon_name(self._icon_lib_name):
            return                      # 这份图片是为本条**刚刚**导入的，留着
        if self._icon_lib_name:
            self.icon_source = ""
            self._icon_lib_path = ""
            self._icon_lib_name = ""
            self._icon_is_src = False
            self.icon_edit.clear()
        self._icon_owner_id = ""

    def _start_new_entry(self):
        """把表单切回"新资源"状态（换编码、忘掉上一条）"""
        self._discard_inherited_icon()
        self._is_new_entry = True
        self._loaded_id = ""
        self._loaded_name = ""
        self._listed_at = ""
        self._icon_picked = False
        self.reload_library_info()       # 顺便把编码换成一个新的

    def _sync_editing_state(self):
        """产出前对齐状态：名称/id 与载入那条不同就算新的一条，重新分配编码且不覆盖上一条"""
        if self._loaded_id and self._looks_like_new_entry():
            self._start_new_entry()
        return self._is_new_entry

    def _ensure_new_entry_for_icon(self):
        """图片要按名称改名前调用：如果其实是在做新的一条，先把状态切过去"""
        if self._loaded_id and self._looks_like_new_entry():
            self._start_new_entry()
        return self._is_new_entry

    def _owns_icon_name(self, name: str) -> bool:
        """这个文件名是不是"我这条"在用（自己新建的条目还没入库，也算自己的）"""
        if not name:
            return False
        if os.path.normcase(os.path.basename(self._icon_lib_name or "")) == \
                os.path.normcase(name):
            return True
        rid = self._entry_id()
        if rid:
            return not self._icon_in_use_elsewhere(name, exclude_id=rid)
        return True         # 新条目：资源库里还没有我，没人能占用这个名字

    def _recycle_icon(self, path: str, name: str = ""):
        """没人再引用这个图标时把它从图标目录里删掉"""
        if not path or not os.path.exists(path):
            return
        try:
            if self._same_file(path, self.icon_source):
                return
        except Exception:
            pass
        if self._icon_in_use_elsewhere(name or os.path.basename(path),
                                       exclude_id=self._entry_id()):
            return
        try:
            os.remove(path)
        except Exception:
            pass

    def refresh_icon_state(self):
        """重新看看当前图标文件到底是什么状态（磁盘说了算）"""
        path = self.icon_source
        if path and os.path.exists(path):
            self._icon_lib_path = path
            self._icon_lib_name = os.path.basename(path)
            self._icon_is_src = not self._same_file(
                path, os.path.join(self.library_icon_dir(), self._icon_lib_name))
        else:
            self._icon_lib_path = ""
            self._icon_lib_name = ""
            self._icon_is_src = False
        self.icon_edit.setText(self.icon_source or "")
        return self._icon_lib_name

    def set_icon_from_library(self, name: str):
        """直接指定用图标目录里的哪个文件（载入已有资源时用）"""
        name = os.path.basename(str(name or ""))
        path = os.path.join(self.library_icon_dir(), name) if name else ""
        self.icon_source = path if path and os.path.exists(path) else ""
        self._icon_picked = False           # 这是资源库里已有的图片，不算"刚导入"
        self._icon_owner_id = self._entry_id()
        return self.refresh_icon_state()

    def copy_into_icon_dir(self, src: str) -> str:
        """把图片复制进图标目录并改成应用名，返回最终文件名（失败返回空串）

        依次尝试：目标就是这份 → 不动；内容一样 → 复用；名字被占 → 换 <名称>-2/-3；再校验。
        """
        src = str(src or "")
        if not src or not os.path.exists(src):
            return ""
        target_dir = self.library_icon_dir()
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception as e:
            self.show_error(
                self._t("icon_dir_create_failed", "Could not create the icon folder: {err}").format(err=e))
            return ""

        want = self.preferred_icon_name(src)
        dest = os.path.join(target_dir, want)
        in_lib = bool(self._icon_lib_path) and os.path.exists(self._icon_lib_path)
        same_as_lib = in_lib and self._same_file(dest, self._icon_lib_path)

        if self._same_file(src, dest):
            self.icon_source = self._icon_lib_path if same_as_lib else dest
            self.refresh_icon_state()
            return self._icon_lib_name or want

        if os.path.exists(dest) and self._same_content(src, dest):
            self.icon_source = dest
            self.refresh_icon_state()
            return self._icon_lib_name or want

        if os.path.exists(dest) and not self._owns_icon_name(want):
            want = unique_name_in(target_dir, os.path.splitext(want)[0],
                                  os.path.splitext(want)[1])
            dest = os.path.join(target_dir, want)

        copied = False
        for _attempt in range(2):
            try:
                shutil.copyfile(src, dest)
            except Exception as e:
                if _attempt == 1:
                    self.show_error(
                        self._t("icon_copy_failed", "Failed to copy the image: {err}").format(err=e))
                    return ""
                time.sleep(0.1)
                continue
            try:
                copied = os.path.exists(dest) and \
                    os.path.getsize(dest) == os.path.getsize(src)
            except Exception:
                copied = os.path.exists(dest)
            if copied:
                break
            time.sleep(0.1)
        if not copied:
            self.show_error(self._t("图片没能复制进图标目录，请再试一次。"))
            return ""

        old_path, old_name = self._icon_lib_path, self._icon_lib_name
        self.icon_source = dest
        self.refresh_icon_state()
        if old_path and not self._same_file(old_path, dest) \
                and os.path.normcase(old_name) != os.path.normcase(self._icon_lib_name):
            self._recycle_icon(old_path, old_name)
        return self._icon_lib_name

    @staticmethod
    def _same_content(a: str, b: str) -> bool:
        try:
            if os.path.getsize(a) != os.path.getsize(b):
                return False
            with open(a, "rb") as f1, open(b, "rb") as f2:
                return f1.read() == f2.read()
        except Exception:
            return False

    def store_icon(self, src: str) -> str:
        """导入图片入口：马上复制进图标目录 + 改成应用名（外面都调这个）"""
        self._icon_rename_timer.stop()
        name = self.copy_into_icon_dir(src)
        if name:
            self._icon_picked = True        # 这是用户为本条刚导入的图片，可以跟着名称改名
            self._icon_owner_id = self._entry_id()
        return name

    def apply_pending_icon_rename(self):
        """「名称」改了以后，把图标目录里那份文件也改成新名字（⚠️ 只对还没入库的新资源做）"""
        if not self._ensure_new_entry_for_icon():
            return                      # 已发布的条目：图片文件不许在后台被动改名
        if not self._icon_picked:
            return                      # 这份图还没进图标目录，没得改
        path = self._icon_lib_path
        if not path or not os.path.exists(path):
            return
        # 最后一道保险：这个文件名已经被资源库里**别的**条目引用了就绝对不碰
        owner = self._icon_owner(os.path.basename(path))
        if owner and owner != self._entry_id():
            return
        target_dir = os.path.dirname(path)
        if os.path.normcase(os.path.abspath(target_dir)) != \
                os.path.normcase(os.path.abspath(self.library_icon_dir())):
            return

        base = self.preferred_icon_base()
        ext = os.path.splitext(path)[1]
        current = os.path.basename(path)
        name = f"{base}{ext}"
        new_path = os.path.join(target_dir, name)
        if self._same_file(path, new_path):
            self.refresh_icon_state()
            return
        if os.path.exists(new_path):
            name = unique_name_in(target_dir, base, ext)
            new_path = os.path.join(target_dir, name)
        if self._same_file(path, new_path):
            self.refresh_icon_state()
            return

        old_path, old_name = path, self._icon_lib_name
        moved = False
        for _attempt in range(2):
            try:
                os.replace(old_path, new_path)
                moved = True
                break
            except Exception:
                continue
        if not moved or not os.path.exists(new_path):
            return
        self.icon_source = new_path
        self.refresh_icon_state()
        if old_name and os.path.normcase(old_name) != os.path.normcase(name):
            self._recycle_icon(old_path, old_name)

    def flush_name_icon_rename(self):
        """立刻把待处理的改名做掉（产出前调用，保证 JSON 里的文件名和磁盘一致）"""
        if self._icon_rename_timer.isActive():
            self._icon_rename_timer.stop()
        self.apply_pending_icon_rename()
        self.refresh_icon_state()
        return self._icon_lib_name

    def resolve_icon_path(self, item: dict, data: dict) -> str:
        """把资源里的 icon 字段解析成磁盘上的真实路径（兼容旧的相对路径写法）"""
        icon = str(item.get("icon") or "").strip()
        if not icon:
            return ""
        if os.path.isabs(icon):
            return icon
        root = self.project_root or os.path.dirname(os.path.abspath(__file__))
        if "/" in icon or "\\" in icon:
            return os.path.join(root, icon.replace("/", os.sep))
        icon_dir = str((data.get("metadata") or {}).get("icon_dir")
                       or self.icon_dir_name())
        icon_dir = icon_dir.strip("/\\").replace("/", os.sep)
        return os.path.join(root, icon_dir, icon)

    def reload_library_info(self):
        """重新读一遍资源库：换一个可用编码 + 刷新"产出"卡片上的资源库说明"""
        data = load_library(self.library_path)
        resources = data["resources"]
        self._icon_dir_cache = ""        # 资源库可能换了 icon_dir，重新读
        self.code_edit.setText(next_code(resources))
        if os.path.exists(self.library_path):
            # ⚠️ 只写文件名，不写整条路径：卡片内宽只有 240px，整条路径会折成四五行
            #    把卡片撑得又高又乱；完整路径挂到悬停提示上。
            self.library_label.setText(
                self._t("library_path_hint",
                        "Library: {path}\n{n} entries in total").format(
                            path=os.path.basename(self.library_path),
                            n=len(resources)))
            self.library_label.setToolTip(self.library_path)
        else:
            self.library_label.setText(
                self._t("library_not_found_hint",
                        "No local library found.\n\"Append to library\" will create one."))
            self.library_label.setToolTip(self.library_path)
        host_call(self.host, "notify_library_changed")

    # ---------- 表单联动 ----------
    def on_name_changed(self, text):
        sid = slugify(text)
        if self.id_edit.text().strip() != sid[:40]:
            self.id_edit.setText(sid[:40])
        # 图标跟着「名称」改名（防抖，停手 0.8 秒后做一次）
        # ⚠️ 载入旧条目 / 清空表单时不能起这个定时器，否则 0.8 秒后会拿新载入那条的图标去改名
        if not getattr(self, "_loading", False) \
                and self._icon_lib_path and os.path.exists(self._icon_lib_path):
            self._icon_rename_timer.start()
        self.refresh_preview()

    def on_id_changed(self, _text=None):
        # 名称留空时图标名会退回用 id，所以这里也要立刻同步一次
        if getattr(self, "_loading", False):
            return
        self.flush_name_icon_rename()
        self.refresh_preview()

    def on_category_changed(self, text=None):
        """类别变了：标签还跟着自动填的时候，把标签也换成这个类别"""
        if getattr(self, "_tags_auto", True):
            category = (text if text is not None
                        else self.category_combo.currentText()).strip()
            if self.tags_edit.text().strip() != category:
                self._set_tags_text(category)
        self.refresh_preview()

    def _set_tags_text(self, text: str):
        """程序自己往标签框里写字（要屏蔽信号，否则会被当成"用户手改"）"""
        blocked = self.tags_edit.blockSignals(True)
        self.tags_edit.setText(text)
        self.tags_edit.blockSignals(blocked)

    def on_tags_edited(self):
        """用户在标签框里打字了 → 以后切类别不再自动覆盖标签"""
        self._tags_auto = False
        self.refresh_preview()

    # ---------- 数据 ----------
    @property
    def library_path(self) -> str:
        """本机资源库文件：<项目根>/.ToolsGCP/ToolsGCP-Resources.json（路径由宿主给）"""
        path = str(host_value(self.host, "library_path", "") or "")
        if path:
            return path
        if self.project_root:
            return os.path.join(self.project_root, RESOURCE_FILE_NAME)
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "ToolsGCP-Resources.json")

    @property
    def icon_dir(self) -> str:
        """图标目录（跟资源库 metadata.icon_dir 保持一致）"""
        return self.library_icon_dir()

    def on_desc_changed(self):
        """简介改了：刷新预览和校验"""
        self.refresh_preview()

    def on_intro_changed(self):
        """应用介绍改了：刷新预览和校验"""
        self.refresh_preview()

    def pick_icon(self):
        """导入图片：自动复制到图标目录，并按「名称」输入框里的文字改名"""
        self._icon_rename_timer.stop()
        if self.icon_source and os.path.exists(self.icon_source):
            start = os.path.dirname(self.icon_source)
        else:
            icon_dir = self.library_icon_dir()
            start = icon_dir if os.path.isdir(icon_dir) else os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, self._t("import_image", "Import image"), start, image_filter())
        if not path:
            return
        if not os.path.exists(path):
            self.show_error(self._t("这个图片文件不存在"))
            return
        name = self.store_icon(path)
        if not name:
            return          # 失败时 store_icon 已经弹过提示，保留原来的图标
        where = self._t("图标目录") if not self._icon_is_src else self._t("原位置")
        InfoBar.success(
            title=self._t("图片已导入"),
            content=self._t("image_saved_as", "Saved as {name} ({path})").format(
                name=name,
                path=(os.path.dirname(self._icon_lib_path)
                      if not self._icon_is_src else where)),
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=2500, parent=self)
        self.refresh_preview()

    def clear_form(self):
        box = MessageBox(self._t("clear_form", "Clear form"), self._t("确定要清空当前填写的所有内容吗？"), self)
        box.yesButton.setText(self._t("清空"))
        box.cancelButton.setText(self._t("取消"))
        if not box.exec():
            return
        self._icon_rename_timer.stop()
        self.name_edit.clear()
        self.id_edit.clear()
        self._tags_auto = True                  # 清空后标签重新跟着类别走
        self._set_tags_text(self.category_combo.currentText().strip())
        self.url_edit.clear()
        self.github_edit.clear()
        self.repo_platform_combo.blockSignals(True)
        self.repo_platform_combo.setCurrentIndex(0)
        self.repo_platform_combo.blockSignals(False)
        self.on_repo_platform_changed()
        # ⚠️ 这三个字段只活在多语言卡片里：要清所有语言页（desc_edit 只是当前页的别名）
        for edits in getattr(self, "i18n_edits", {}).values():
            for editor in edits:
                try:
                    editor.clear()
                except Exception:
                    pass
        self._loaded_download_url = ""
        self._set_checked_pills(getattr(self, "system_buttons", {}), [])
        self._set_checked_pills(getattr(self, "arch_buttons", {}), [])
        self.author_url_edit.clear()
        self.chat_edit.clear()
        self._loaded_id = ""
        self._loaded_name = ""
        self._is_new_entry = True       # 清空后就是新资源了
        self._listed_at = ""
        # 只清空表单，不删图标文件：这个文件可能已经被别的条目引用着
        self.icon_source = ""
        self.icon_edit.clear()
        self.refresh_icon_state()
        self.reload_library_info()
        self.refresh_preview()

    # ---------- 构建条目 ----------
    def current_icon_name(self) -> str:
        """当前条目在资源库里应该使用的图标文件名（磁盘上真实存在的那个）"""
        self.refresh_icon_state()
        if self._icon_lib_path and os.path.exists(self._icon_lib_path):
            return self._icon_lib_name
        return ""

    def build_entry(self) -> dict:
        entry = {
            "id": self.id_edit.text().strip(),
            "code": self.code_edit.text().strip(),
            "name": self.name_edit.text().strip(),
            # ⚠️ category 落盘是列表（schema 2.1.0）："工具, 游戏" 会拆成两项；
            #    每项都要过 _canonical_term —— 下拉框显示译名，库里存的是规范中文。
            "category": [self._canonical_term(c) for c in
                         split_categories(self.category_combo.currentText())],
            "tags": [self._canonical_term(t) for t in
                     split_tags(self.tags_edit.text())],
            "icon": self.current_icon_name(),
            "url": auto_http_url(self.url_edit.text()),
            "github": normalize_repo_url(self.current_repo_platform(), self.github_edit.text()),
            # ⚠️ 表单已无下载直链，但这里要原样保留已载入条目里的值（部署页还要用）
            "download_url": str(getattr(self, "_loaded_download_url", "") or ""),
            "chat_url": auto_http_url(self.chat_edit.text()),
            "author_url": auto_http_url(self.author_url_edit.text()),
            "description": self._plain_text(self.desc_edit).replace("\n", " ").strip(),
            "intro": self._plain_text(self.intro_edit).replace("\n", " ").strip(),
            "supplement": self._plain_text(self.supplement_edit).replace("\n", " ").strip(),
            "listed_at": now_listed_at() if self.is_new_entry() else self._listed_at,
            "systems": self._checked_pills(getattr(self, "system_buttons", {})),
            "architectures": self._checked_pills(getattr(self, "arch_buttons", {})),
        }
        # 字段顺序 / 空值过滤 / tags 去重（去掉与类别重复的）全部交给 schema
        normalized = resource_schema.normalize(entry)
        # ⚠️ 多语言字段必须在 normalize 之后合并：normalize() 会把 i18n 按当前语言
        #    压成一句话，先合并就会被压扁成一种语言（"提交不了三语言"的根因之一）。
        return self.apply_i18n_to_entry(normalized)


    def is_new_entry(self) -> bool:
        """这一条是不是新资源（不是从资源库里载入的旧条目）"""
        return not self._loaded_id

    def validate(self):
        """返回错误列表（空表示通过）

        必填只有「名称」和「标识 id」；其他问题（地址没写 http://、图标丢了）只提示不拦。
        """
        errors = []
        if not self.name_edit.text().strip():
            errors.append(self._t("「名称」必填"))
        sid = self.id_edit.text().strip()
        if not sid:
            errors.append(self._t("「标识 id」必填"))
        elif not is_valid_id(sid):
            errors.append(self._t("「标识 id」只能包含小写字母、数字和连字符"))
        if self.icon_source and not os.path.exists(self.icon_source):
            errors.append(self._t("图标文件不存在（重新导入一次图片）"))

        data = load_library(self.library_path)
        sid_editing = self._editing_id()
        for item in data["resources"]:
            if item.get("id") == sid and sid != sid_editing:
                errors.append(self._t("err_id_taken", "The id \"{id}\" is already taken ({name})")
                              .format(id=sid, name=item.get("name")))
                break
        current_code = self.code_edit.text().strip()
        if current_code:
            for item in data["resources"]:
                if item.get("code") == current_code and sid != sid_editing:
                    errors.append(self._t("err_code_taken", "The code \"{code}\" is already taken ({name})")
                                  .format(code=current_code, name=item.get("name")))
                    break
        return errors

    def validate_warnings(self):
        """可留空的字段：有就提示一句怎么写更好，不影响产出"""
        warns = []
        self.refresh_icon_state()
        if not self._icon_lib_path:
            warns.append(self._t("还没导入图片，卡片上会显示成默认图标"))
        url = self.url_edit.text().strip()
        if not url:
            warns.append(self._t("「官网」留空了，卡片上会没有「官网」按钮"))
        elif not has_http_scheme(url):
            warns.append(self._t("「官网」没写 http://，已按 https:// 处理"))
        if not self._plain_text(self.desc_edit).strip():
            warns.append(self._t("「简介」留空了，卡片上只有名称"))
        if not self.category_combo.currentText().strip():
            warns.append(self._t("「类别」留空了，这条不会出现在类别分组里"))
        for label, value in ((self._t("author_page", "Author page"), self.author_url_edit.text().strip()),
                             (self._t("chat_url", "Chat / community"), self.chat_edit.text().strip())):
            if value and not has_http_scheme(value):
                warns.append(self._t("warn_no_http_scheme",
                                     "\"{label}\" has no http:// prefix — https:// was assumed")
                             .format(label=label))
        platform = self.current_repo_platform()
        repo_url = normalize_repo_url(platform, self.github_edit.text())
        if platform not in ("none", "custom") and not repo_url:
            warns.append(self._t("「开源仓库」留空了，卡片上会没有仓库按钮"))
        return warns

    def _editing_id(self):
        return getattr(self, "_loaded_id", "")

    def refresh_preview(self):
        # ⚠️ 预览卡 / 状态行是后面几步才建的（build_steps 分步构建），而多语言卡片
        #    建好那一刻就会刷一次 —— 必须挡住"控件还没建出来"的调用，否则构建直接抛异常。
        if not hasattr(self, "preview") or not hasattr(self, "status_label"):
            return
        entry = self.build_entry()
        self.preview.update_preview(entry, self.icon_source)
        errors = self.validate()
        if errors:
            self.status_label.setText("· " + "\n· ".join(errors[:4]))
            style_role_color(self.status_label, "danger")
            return
        warns = self.validate_warnings()
        if warns:
            self.status_label.setText(
                self._t("status_all_ok_with_warns",
                        "All required fields are filled in — you can generate or append.\n(Also:\n· {list})")
                .format(list="\n· ".join(warns[:4])))
            style_role_color(self.status_label, "warning")
        else:
            self.status_label.setText(self._t("信息完整，可以生成/追加了。"))
            style_role_color(self.status_label, "success")

    # ---------- 产出 ----------
    def export_draft(self):
        errors = self.validate()
        if errors:
            self.show_error(
                self._t("errors_fix_first", "Please fix these problems first:\n· {list}")
                .format(list="\n· ".join(errors)))
            return

        self.flush_name_icon_rename()       # 先把待改名的图标落实，JSON 里才不会对不上
        base_dir = os.path.join(self.project_root or os.path.dirname(os.path.abspath(__file__)),
                                "ResourceDrafts")
        out_dir = QFileDialog.getExistingDirectory(self, self._t("选择稿件输出目录"), base_dir)
        if not out_dir:
            return

        entry = self.build_entry()
        draft_dir = os.path.join(out_dir, entry["id"])
        icon_sub = os.path.join(draft_dir, "Icon")
        os.makedirs(icon_sub, exist_ok=True)

        name = ""
        if self.icon_source and os.path.exists(self.icon_source):
            # 稿件里的图片沿用「名称」起的文件名（多个稿件混在一起也不会重名）
            name = copy_icon(self.icon_source, icon_sub, entry["name"] or entry["id"])
            entry["icon"] = name
        else:
            entry.pop("icon", None)

        payload = {
            "schema_version": SCHEMA_VERSION,
            "metadata": {
                "name": f"ToolsGCP Draft - {entry['name']}",
                "description": self._t("单条资源稿件，可直接提交给 ToolsGCP 作者"),
                "icon_dir": "Icon",
                "updated_at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
            },
            "resources": [entry],
        }
        json_path = os.path.join(draft_dir, "resource.json")
        write_json(json_path, payload)

        readme = os.path.join(draft_dir, self._t("说明.txt"))
        icon_line = (self._t("draft_readme_icon_line",
                             "Icon/{name} — the image (named after the app)").format(name=name) + "\n"
                     if name else
                     self._t("draft_readme_no_icon", "(This draft has no image)") + "\n")
        with open(readme, "w", encoding="utf-8") as f:
            f.write(
                self._t("draft_readme_head",
                        "This is the resource draft for {name}, generated by the ToolsGCP Resource Maker.")
                .format(name=entry['name']) + "\n\n"
                + self._t("draft_readme_json", "resource.json — the resource data (single entry)") + "\n"
                + icon_line + "\n"
                + self._t("draft_readme_howto",
                          "How to submit: send the whole folder (or the zip below) to the author,\nor append it to your own .ToolsGCP/ToolsGCP-Resources.json.") + "\n")

        zip_path = os.path.join(out_dir, f"{entry['id']}.zip")
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _dirs, files in os.walk(draft_dir):
                    for fn in files:
                        full = os.path.join(root, fn)
                        zf.write(full, os.path.relpath(full, draft_dir))
            zip_msg = self._t("zip_packed", "\nPacked: {path}").format(path=zip_path)
        except Exception as e:
            zip_msg = self._t("zip_pack_failed", "\n(Failed to create the zip: {err})").format(err=e)

        InfoBar.success(
            title=self._t("稿件已生成"),
            content=f"{draft_dir}{zip_msg}",
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=6000, parent=self)

    def append_to_library(self, confirm: bool = True):
        """把当前这条写进同一个 ToolsGCP-Resources.json（confirm=False 跳过覆盖确认框）"""
        # 可能是接着上一条继续填（没点清空），先对齐状态，免得张冠李戴
        self._sync_editing_state()
        errors = self.validate()
        if errors:
            self.show_error(
                self._t("errors_fix_first", "Please fix these problems first:\n· {list}")
                .format(list="\n· ".join(errors)))
            return

        self.flush_name_icon_rename()
        path = self.library_path
        data = load_library(path)

        # 兜底：图片还在原位置（没进图标目录）时，现在复制进去并改成名称
        if self.icon_source and os.path.exists(self.icon_source) and self._icon_is_src:
            if not self.store_icon(self.icon_source):
                self.show_error(self._t("图片没能存进图标目录，已中止写入（资源库没有被改动）"))
                return

        entry = self.build_entry()
        if not entry.get("icon"):
            # 一个图标都没有：不写 icon 字段，也别让它指向不存在的文件
            entry.pop("icon", None)

        existing = next((r for r in data["resources"] if r.get("id") == entry["id"]), None)
        if existing is not None and confirm:
            box = MessageBox(
                self._t("覆盖已有资源"),
                self._t("confirm_overwrite_entry",
                        "The library already has an entry with id \"{id}\" ({name}). Overwrite it with the current form contents?\n\nLibrary file: {path}")
                .format(id=entry["id"], name=existing.get("name"), path=path), self)
            box.yesButton.setText(self._t("覆盖"))
            box.cancelButton.setText(self._t("取消"))
            if not box.exec():
                return
        if existing is not None:
            # 保留原来的上架时间（编辑旧条目不算重新上架）
            if not entry.get("listed_at"):
                entry["listed_at"] = existing.get("listed_at", "")
            data["resources"] = [r for r in data["resources"] if r.get("id") != entry["id"]]
        if not entry.get("listed_at"):
            entry["listed_at"] = now_listed_at()        # 新条目：现在就是上架时间

        data["resources"].append(entry)
        data.setdefault("metadata", {})["updated_at"] = \
            datetime.now().astimezone().replace(microsecond=0).isoformat()
        data["metadata"]["total_count"] = len(data["resources"])

        if os.path.exists(path) and not backup_library(path):
            self.show_error(
                self._t("backup_failed_abort",
                        "Backup failed — the write was aborted (the library was left untouched)\n{err}")
                .format(err=last_backup_error()))
            return

        try:
            write_json(path, data)
        except Exception as e:
            self.show_error(
                self._t("write_failed", "Write failed: {err}").format(err=e))
            return

        if existing is not None:
            old_icon = os.path.basename(str(existing.get("icon") or ""))
            new_icon = str(entry.get("icon") or "")
            if old_icon and os.path.normcase(old_icon) != os.path.normcase(new_icon) \
                    and not self._icon_in_use_elsewhere(old_icon, exclude_id=entry["id"]):
                try:
                    os.remove(os.path.join(self.icon_dir, old_icon))
                except Exception:
                    pass

        self._loaded_id = entry["id"]
        self._loaded_name = str(entry.get("name") or "").strip()   # 表单现在代表这一条
        self._is_new_entry = False
        self._listed_at = str(entry.get("listed_at") or "")
        self.refresh_icon_state()
        self.reload_library_info()
        if getattr(self.host, "browser_page", None) is not None:
            self.host.browser_page.reload()
        InfoBar.success(
            title=self._t("已写入资源库"),
            content=self._t("written_to_library", "{name} ({code}) → {n} entries").format(
                name=entry['name'], code=entry.get('code') or self._t("无编码"),
                n=len(data['resources'])),
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=4000, parent=self)

    def save_standalone(self):
        errors = self.validate()
        if errors:
            self.show_error(
                self._t("errors_fix_first", "Please fix these problems first:\n· {list}")
                .format(list="\n· ".join(errors)))
            return

        self.flush_name_icon_rename()
        default = os.path.join(self.project_root or os.getcwd(), "ToolsGCP-Resources.json")
        path, _ = QFileDialog.getSaveFileName(self, self._t("save_as_new", "Save as a separate library"), default,
                                              self._t("JSON 文件 (*.json)"))
        if not path:
            return

        entry = self.build_entry()
        icon_dir = os.path.join(os.path.dirname(path), "Icon")
        if self.icon_source and os.path.exists(self.icon_source):
            name = copy_icon(self.icon_source, icon_dir, entry["name"] or entry["id"])
            entry["icon"] = name
        else:
            entry.pop("icon", None)

        payload = {
            "schema_version": SCHEMA_VERSION,
            "metadata": {
                "name": "ToolsGCP Resources",
                "description": self._t("ToolsGCP 资源索引文件"),
                "icon_dir": os.path.relpath(icon_dir, os.path.dirname(path)).replace("\\", "/"),
                "updated_at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
            },
            "resources": [entry],
        }
        try:
            write_json(path, payload)
        except Exception as e:
            self.show_error(
                self._t("write_failed", "Write failed: {err}").format(err=e))
            return
        InfoBar.success(
            title=self._t("已生成独立资源库"),
            content=path, orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=5000, parent=self)

    def load_existing(self):
        data = load_library(self.library_path)
        resources = data["resources"]
        if not resources:
            self.show_error(self._t("本机资源库是空的，没有可载入的条目。"))
            return

        items = [f"{r.get('code','')}  {r.get('name','')}  ({r.get('id','')})" for r in resources]
        # ⚠️ 不能用原生 QInputDialog.getItem：它不跟 qfluentwidgets 的主题，
        #    深色下字和底都是浅色、基本看不见，换成主题安全的 FluentChoiceDialog。
        from ..ui.fluent_dialogs import ask_choice
        ok, choice = ask_choice(self, self._t("载入现有资源"),
                                self._t("选择要编辑的资源："), items, 0)
        if not ok or not choice:
            return
        index = items.index(choice)
        self.load_resource(resources[index], data)
        InfoBar.info(
            title=self._t("已载入"), content=f"{resources[index].get('name')}（{resources[index].get('code')}）",
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=2500, parent=self)

    def load_resource(self, r: dict, data: dict = None):
        """把一条资源填进表单（浏览页「载入到制作资源」/ 载入按钮都走这里）"""
        if data is None:
            data = load_library(self.library_path)
        self._icon_rename_timer.stop()
        # 这一段算"程序自己在改表单"：不起改名定时器、不动上一条的图标
        self._loading = True
        try:
            self._is_new_entry = False      # 表单现在代表资源库里已有的这一条
            self._loaded_id = r.get("id", "")
            self._listed_at = str(r.get("listed_at") or "")  # 编辑旧条目：保留原上架时间

            self.load_i18n_from_entry(r)
            name_value = r.get("name", "")
            shown_name = (name_value if isinstance(name_value, str)
                          else resolve_i18n_for_maker(name_value))
            self.name_edit.setText(shown_name)
            self._loaded_name = str(shown_name or "").strip()
            self.id_edit.setText(r.get("id", ""))
            self.code_edit.setText(r.get("code", ""))
            # category 是列表 → 用 ", " 拼回输入框（build_entry 会再拆开，往返无损）；
            # 显示的是当前语言译名，落盘时 _canonical_term 会还原成规范值
            categories = resource_schema.categories_of(r)
            if categories:
                self.category_combo.setCurrentText(
                    ", ".join(self._term(c) for c in categories))
            self.set_icon_from_library(os.path.basename(str(r.get("icon") or "")))
            self._tags_auto = False     # 旧条目的标签是作者写好的，不覆盖
            self._set_tags_text(", ".join(
                self._term(t) for t in (r.get("tags", []) or [])))
            self.url_edit.setText(r.get("url", ""))
            # ⚠️ 表单没有下载直链了，但老条目可能带着：记下来，保存时原样写回
            self._loaded_download_url = str(r.get("download_url") or "")
            # 简介 / 应用介绍 / 补充说明由上面的 load_i18n_from_entry() 填，这里不再设
            # 适用系统 / 架构：JSON 里是数组（旧数据可能没有，或写成单个字符串）
            self._set_checked_pills(self.system_buttons,
                                    as_list(r.get("systems")))
            self._set_checked_pills(self.arch_buttons,
                                    as_list(r.get("architectures")))
            self.author_url_edit.setText(r.get("author_url", ""))
            self.chat_edit.setText(r.get("chat_url", ""))
        finally:
            self._loading = False

        repo_url = str(r.get("github") or "")
        platform = detect_repo_platform(repo_url)
        prefix = next((p for k, _n, p in REPO_PLATFORMS if k == platform), "")
        self.repo_platform_combo.blockSignals(True)
        idx = next((i for i, (k, _n, _p) in enumerate(REPO_PLATFORMS) if k == platform), 0)
        self.repo_platform_combo.setCurrentIndex(idx)
        self.repo_platform_combo.blockSignals(False)
        self.github_edit.setText(repo_url[len(prefix):] if prefix else repo_url)
        self.on_repo_platform_changed()
        self.author_url_edit.setText(r.get("author_url", ""))
        self.chat_edit.setText(r.get("chat_url", ""))
        self.refresh_preview()

    def show_error(self, message: str):
        InfoBar.error(
            title=self._t("请先处理这些问题"),
            content=message, orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=6000, parent=self)


# ---------- 资源浏览器页 ----------
class EditableTableWidget(TableWidget):
    """双击才进编辑的表格（表格设了 NoEditTriggers，这里只放行双击）"""

    def edit(self, index, trigger, event):
        if trigger == QAbstractItemView.DoubleClicked:
            trigger = QAbstractItemView.AllEditTriggers
        return super().edit(index, trigger, event)


class BrowserPage(MakerPageMixin, QWidget):
    """浏览本机资源库里的条目：可以搜索、双击就地修改、删除"""

    # 表格列 -> 资源里的字段（兜底文案, 字段名）；表头真正显示的是 _col_title() 查语言的
    COLUMNS = [
        ("图标", "icon"),
        ("编码", "code"),
        ("名称", "name"),
        ("类别", "category"),
        ("标签", "tags"),
        ("官网", "url"),
        ("开源仓库", "github"),
        ("简介", "description"),
        ("应用介绍", "intro"),
        ("补充", "supplement"),
        ("上架时间", "listed_at"),
    ]

    COLUMN_TEXT_KEYS = {
        "icon": "icon",
        "code": "code",
        "name": "name",
        "category": "category",
        "tags": "tags",
        "url": "url",
        "github": "github",
        "description": "description",
        "intro": "intro",
        "supplement": "supplement",
        "listed_at": "column_listed_at",
    }
    ICON_COLUMN = 0

    # 内容天然比列宽长的列 → 填表时挂整串的悬停提示（见 _fill_batch）
    TOOLTIP_FIELDS = {"url", "github", "description", "intro", "supplement", "tags"}

    # 一次填多少行（剩下的每轮回事件循环再填一批，见 _fill_rows）；120 行 ≈ 4ms
    FILL_CHUNK = 120

    # 每列的理想宽度（宽屏时想要的）和最小宽度（再挤也不能低于它）
    # ⚠️ 以前 11 列宽度写死共 1904px，而视口只有 ~1030px，右边四列永远在视野外，
    #    横向滚动条又是悬浮式（不滚不显示），看着像"被切掉半截又滚不过去"。
    # ⚠️ 编号列要留够：表格项两边留白比想象中大，"TG-000001" 本身 62px，
    #    列宽 < ~105 就会被截成 "TG-00…"。
    COLUMN_IDEAL_WIDTH = {
        "icon": 56, "code": 120, "name": 170, "category": 88, "tags": 130,
        "url": 160, "github": 170, "description": 200, "intro": 200,
        "supplement": 170, "listed_at": 130,
    }
    # ⚠️ 最小宽度之和必须小于常规窗口下的表格视口（1280 窗口 ≈ 1075，1180 ≈ 975），
    #    否则连最小宽度都放不下 → 又回到横向滚动（等于没修）。
    COLUMN_MIN_WIDTH = {
        "icon": 52, "code": 110, "name": 118, "category": 64, "tags": 74,
        "url": 78, "github": 78, "description": 88, "intro": 80,
        "supplement": 78, "listed_at": 86,
    }
    # 「图标」格显示 24×24 缩略图 + 悬停文件名（以前是文件名文本，110px 还被截成 "localsend...."）
    ICON_THUMB_SIZE = 24

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.setObjectName("browserPage")
        self.host = host
        self.data = {}                  # 资源库内容（reload 里填）
        self._rows = []
        self._edit_guard = False        # 刷新表格时屏蔽 itemChanged
        self._editing_icon = False      # 正在给图标列挑图片
        self._fill_token = 0            # 分帧填表的批次号（改筛选就 +1 作废旧批次）
        self._fill_state = None         # (行列表, 已填到第几行, 批次号)
        self._count_text = ""           # 表格条数那句（填表中会先写"正在填表"）
        self._applying_widths = False   # 正在自适应列宽（屏蔽 sectionResized）
        self._user_resized_columns = False   # 用户自己拖过列宽 → 之后不再自动改
        self._icon_cache = {}           # 图标路径 -> 缩略图（False = 读不出来）

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 18)
        layout.setSpacing(12)

        # ⚠️ 不再单放一行「资源库条目 共 N 条」大标题：页头右上角已有「资源库 N 条」，
        #    条数改到表格下面的脚注行（只在筛选时出现，见 _fill_rows）。
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.search_edit = LineEdit(self)
        self.search_edit.setPlaceholderText(self._t("search_library", "Search by code / name / tag / id"))
        self.search_edit.setFixedWidth(240)
        self.search_edit.textChanged.connect(self.apply_filter)
        toolbar.addWidget(self.search_edit)

        self.category_combo = ComboBox(self)
        self.category_combo.setFixedWidth(140)
        self.category_combo.addItem(self._t("all_categories", "All categories"), userData="")
        for name in CATEGORIES:
            # 显示译名、userData 存规范中文（筛选按 userData 匹配，见 apply_filter）
            self.category_combo.addItem(self._term(name), userData=name)
        self.category_combo.currentIndexChanged.connect(self.apply_filter)
        toolbar.addWidget(self.category_combo)

        self.reload_btn = PushButton(self._t("reload", "Reload"), self, FIF.SYNC)
        self.reload_btn.clicked.connect(self.reload)
        toolbar.addWidget(self.reload_btn)

        self.open_btn = PushButton(self._t("open_library", "Open library file"), self, FIF.FOLDER)
        self.open_btn.clicked.connect(self.open_library_file)
        toolbar.addWidget(self.open_btn)

        toolbar.addStretch()
        # ⚠️ 两个"动数据"的按钮和左边筛选之间留一段固定间隔：贴着右边缘又紧挨
        #    筛选控件时很容易点错（而且是删条目）。
        toolbar.addSpacing(12)
        self.edit_btn = PushButton(self._t("load_into_form", "Load into the form"), self, FIF.EDIT)
        self.edit_btn.clicked.connect(self.load_into_form)
        toolbar.addWidget(self.edit_btn)

        self.delete_btn = PushButton(self._t("delete_selected", "Delete selected"), self, FIF.DELETE)
        self.delete_btn.clicked.connect(self.delete_selected)
        toolbar.addWidget(self.delete_btn)
        layout.addLayout(toolbar)

        self.table = EditableTableWidget(self)
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([self._col_title(c[1]) for c in self.COLUMNS])
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(QHeaderView.Interactive)
        # ⚠️ 必须关掉 stretchLastSection：列宽由 _fit_columns 自己算，再让最后一列
        #    "吃掉剩余空间"会和它打架（一宽一窄来回跳）。
        header_view.setStretchLastSection(False)
        header_view.sectionResized.connect(self._on_section_resized)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setIconSize(QSize(self.ICON_THUMB_SIZE, self.ICON_THUMB_SIZE))
        header_view.setMinimumSectionSize(48)
        # ⚠️ 初始化列宽必须包在 _applying_widths 里：setColumnWidth 会发 sectionResized，
        #    否则"用户拖过列宽"的标志一开始就被置真，自适应列宽直接罢工。
        self._applying_widths = True
        try:
            for index, (title_text, field) in enumerate(self.COLUMNS):
                self.table.setColumnWidth(index, self.COLUMN_IDEAL_WIDTH.get(field, 140))
        finally:
            self._applying_widths = False
        self.table.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.table.itemChanged.connect(self.on_item_changed)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_row_menu)
        layout.addWidget(self.table, 1)
        self._fix_table_corner()

        self.hint_label = CaptionLabel(
            self._t("双击单元格直接修改内容，改完自动保存（写入前会自动备份到 backups/）；双击「图标」列的格子可以重新挑一张图片（自动存进图标目录并改成应用名）；\n「上架时间」是新资源入库的时间；想大改就选中一行点「载入到制作资源」。"),
            self)
        self.hint_label.setWordWrap(True)
        style_hint(self.hint_label)
        self.count_label = CaptionLabel("", self)
        style_hint(self.count_label)

        footer = QHBoxLayout()
        footer.setSpacing(12)
        footer.addWidget(self.hint_label, 1)
        footer.addWidget(self.count_label, 0, Qt.AlignTop | Qt.AlignRight)
        layout.addLayout(footer)
        # ⚠️ 这里不读资源库：读盘 + 填表是 build_steps 里的那一步（切到本节时才执行）

    # ---------- 按需构建（由 ResourceMakerInterface 分步调用）----------
    def build_steps(self) -> list:
        """整页控件很少（十几毫秒），花钱的是"把整个资源库读出来填进表格"，所以只有一步；
        填表本身还会分帧，见 _fill_rows。"""
        return [(self._t("读取资源库并填表"), self.reload)]

    # ---------- 列宽自适应 ----------
    # ⚠️ 以前 11 列写死 1904px，视口只有 ~1030px，右边四列永远在视野外（滚动条是悬浮式的）。
    def _on_section_resized(self, *_args):
        """用户手动拖过列宽 → 之后不再自动改（尊重用户的选择）"""
        if self._applying_widths:
            return
        self._user_resized_columns = True

    def _icon_path_of(self, entry: dict) -> str:
        """一条资源的图标在磁盘上的真实路径（解析不出来返回 ""；⚠️ 不能调 FormPage 那份）"""
        try:
            icon = str(entry.get("icon") or "").strip()
            if not icon:
                return ""
            if os.path.isabs(icon):
                return icon
            if "/" in icon or "\\" in icon:
                return os.path.join(str(self.host.project_root), icon.replace("/", os.sep))
            return os.path.join(str(self.host.icon_dir()), icon)
        except Exception:
            return ""

    def _icon_pixmap(self, entry: dict):
        """取一条资源的图标缩略图（取不到返回 None；⚠️ QPixmap 必须在 GUI 线程里建）"""
        path = self._icon_path_of(entry)
        if not path or not os.path.exists(path):
            return None
        cached = self._icon_cache.get(path)
        if cached is not None:
            return cached or None
        try:
            pixmap = QPixmap(path)
        except Exception:
            pixmap = None
        if pixmap is None or pixmap.isNull():
            self._icon_cache[path] = False      # 记下"这张读不出来"，别反复试
            return None
        scaled = pixmap.scaled(self.ICON_THUMB_SIZE, self.ICON_THUMB_SIZE,
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._icon_cache[path] = scaled
        return scaled

    def _fit_columns(self):
        """按视口宽度分配每一列的宽度（宽了就宽、窄了等比压到最小宽度为止）"""
        if self._user_resized_columns:
            return
        table = self.table
        available = table.viewport().width()
        if available <= 0:
            return
        fields = [field for _title, field in self.COLUMNS]
        ideal = [self.COLUMN_IDEAL_WIDTH.get(f, 140) for f in fields]
        minimum = [self.COLUMN_MIN_WIDTH.get(f, 80) for f in fields]
        total_ideal, total_min = sum(ideal), sum(minimum)

        if available >= total_ideal:
            # 够宽：理想宽度，剩下的都给「名称」那一列（最常看的一列）
            widths = list(ideal)
            widths[2] += available - total_ideal
        elif available <= total_min:
            # 连最小宽度都放不下：保持最小宽度，让它横向滚动（此时才该滚）
            widths = list(minimum)
        else:
            # 中间态：按"每一列能压缩多少"等比缩，缩到最小宽度为止
            slack = total_ideal - available
            room = total_ideal - total_min
            widths = [w - int(round((w - m) * slack / room))
                      for w, m in zip(ideal, minimum)]
            widths[2] += available - sum(widths)      # 抹掉四舍五入的误差

        self._applying_widths = True
        try:
            for index, width in enumerate(widths):
                table.setColumnWidth(index, max(40, int(width)))
        finally:
            self._applying_widths = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_columns()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_columns()

    def _fix_table_corner(self):
        """修掉表格左上角那一格：⚠️ 该角落按钮没有 WA_StyledBackground，必须补上再设透明样式"""
        try:
            from PyQt5.QtWidgets import QAbstractButton
            corner = self.table.findChild(QAbstractButton)
            if corner is None:
                return
            corner.setAttribute(Qt.WA_StyledBackground, True)
            corner.setStyleSheet(
                "QTableCornerButton::section, QAbstractButton {"
                " background-color: transparent; border: none; }")
        except Exception:
            pass

    # ---------- 主题 ----------
    def apply_theme(self, dark: bool = None):
        style_hint(self.hint_label)
        style_hint(self.count_label)

    def refresh_theme(self):
        self.apply_theme()

    # ---------- 数据 ----------
    def reload(self):
        # 用宿主的 library_path()（分节按需构建，不依赖表单页已建出来）
        self.data = load_library(self.host.library_path())
        self._rows = list(self.data.get("resources", []))
        self.apply_filter()
        host_call(self.host, "notify_library_changed")

    @staticmethod
    def _cell_text(entry: dict, field: str) -> str:
        value = entry.get(field)
        if value is None:
            return ""
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        if isinstance(value, dict):
            # ⚠️ 多语言字段直接 str() 会显示成 "{'简体中文': …}" 这种原文，要按当前语言取
            return resolve_i18n_for_maker(value)
        return str(value)

    def apply_filter(self):
        keyword = self.search_edit.text().strip().lower()
        category = self.category_combo.currentData() if hasattr(self, "category_combo") else ""
        rows = self._rows
        if category:
            # category 是列表：落在任意一个类别里就算命中
            rows = [r for r in rows if category in resource_schema.categories_of(r)]
        if keyword:
            # 关键词匹配 = 类别 ∪ 标签（和搜索页、AI 清单同一套取值）
            rows = [r for r in rows
                    if keyword in str(r.get("code", "")).lower()
                    or keyword in str(r.get("name", "")).lower()
                    or keyword in str(r.get("id", "")).lower()
                    or any(keyword in str(t).lower()
                           for t in resource_schema.keywords_of(r))]
        self._fill_rows(rows, filtered=bool(keyword or category))

    def _fill_rows(self, rows: list, filtered: bool = False):
        """把筛选结果填进表格：先填一屏，剩下的分帧填（见 _drip_rows）

        ⚠️ 必须分帧：一次填完 3000 行要 120ms，就是肉眼可见的卡顿。
        """
        self._fill_token += 1                  # 作废上一批还没填完的
        token = self._fill_token
        # ⚠️ 不筛选时不显示条数：页头右上角已有「资源库 N 条」，脚注再写就是同一件事说两次；
        #    只有筛选中才写"显示了多少 / 共多少"（这个数字页头没有）。
        self._count_text = (
            self._t("browser_shown", "Filtered · {n} of {total} shown")
            .format(n=len(rows), total=len(self._rows)) if filtered else "")
        self._edit_guard = True
        try:
            self.table.clearContents()
            self.table.setRowCount(len(rows))   # 行数先定下来，滚动条长度才准
        finally:
            self._edit_guard = False
        head = rows[:self.FILL_CHUNK]
        self._fill_batch(head, 0)
        QTimer.singleShot(0, self._fit_columns)
        offset = len(head)
        if offset >= len(rows):
            self.count_label.setText(self._count_text)
            return
        self._fill_state = (rows, offset, token)
        self.count_label.setText(
            self._t("browser_busy_filling", "{count}, filling the table {n}/{total}…")
            .format(count=self._count_text or
                    self._t("browser_total", "{n} entries").format(n=len(self._rows)),
                    n=offset, total=len(rows)))
        QTimer.singleShot(0, self._drip_rows)

    def _fill_batch(self, rows: list, offset: int):
        """填一批行（等价于原来 apply_filter 里的双层循环，只是可以分批）"""
        self._edit_guard = True
        try:
            for i, r in enumerate(rows, start=offset):
                for col, (_title, field) in enumerate(self.COLUMNS):
                    text = self._cell_text(r, field)
                    item = QTableWidgetItem(text)
                    if field == "icon":
                        # 原始文件名挂上，双击改图时要用
                        icon_name = str(r.get("icon") or "")
                        item.setData(Qt.UserRole + 1, icon_name)
                        item.setText("")        # 缩略图列不显示文字（见 ICON_THUMB_SIZE）
                        item.setToolTip(icon_name or self._t("双击这里可以换一张图片"))
                        pixmap = self._icon_pixmap(r)
                        if pixmap is not None:
                            item.setIcon(QIcon(pixmap))
                    elif field in self.TOOLTIP_FIELDS and text:
                        # 这些列天然比列宽长，表格里只能看到截断的半截 → 挂整串悬停提示
                        item.setToolTip(text)
                    self.table.setItem(i, col, item)
                self.table.item(i, 0).setData(Qt.UserRole, r.get("id"))
        finally:
            self._edit_guard = False

    def _drip_rows(self):
        """分帧填表的下一批（每轮事件循环一批，中间 Qt 正常重绘 / 响应操作）"""
        state = self._fill_state
        if not state:
            return
        rows, offset, token = state
        if token != self._fill_token:           # 期间又改过筛选：这一批不要了
            return
        nxt = offset + self.FILL_CHUNK
        self._fill_batch(rows[offset:nxt], offset)
        if nxt >= len(rows):
            self._fill_state = None
            self.count_label.setText(self._count_text)
            return
        self._fill_state = (rows, nxt, token)
        self.count_label.setText(
            self._t("browser_busy_filling", "{count}, filling the table {n}/{total}…")
            .format(count=self._count_text or
                    self._t("browser_total", "{n} entries").format(n=len(self._rows)),
                    n=nxt, total=len(rows)))
        QTimer.singleShot(0, self._drip_rows)

    def _selected_ids(self):
        ids = []
        for index in self.table.selectionModel().selectedRows() if self.table.selectionModel() else []:
            item = self.table.item(index.row(), 0)
            if item is not None:
                rid = item.data(Qt.UserRole)
                if rid:
                    ids.append(rid)
        return ids

    # ---------- 双击编辑 ----------
    def on_item_double_clicked(self, item):
        if item is None:
            return
        column = item.column()
        if column == self.ICON_COLUMN:
            self.pick_icon_for_row(item.row())
        else:
            self.table.editItem(item)

    def on_item_changed(self, item):
        if self._edit_guard or self._editing_icon or item is None:
            return
        field = self.COLUMNS[item.column()][1]
        head = self.table.item(item.row(), 0)
        if head is None:                # 这一行刚被刷新掉，别再动它
            return
        rid = head.data(Qt.UserRole)
        if not rid:
            return
        text = item.text()
        entry = next((r for r in self._rows if r.get("id") == rid), None)
        if entry is None:
            return
        value = text.strip()
        if field == "tags":
            value = split_tags(text)
        elif field == "category":
            # category 是列表：表格里一格可以写多个类别（分隔符同 schema）
            value = split_categories(text)
        if self._cell_text(entry, field) == self._cell_text({field: value}, field):
            return                      # 没真改，不写盘
        if field == "name" and not text.strip():
            self._revert_cell(item, self._t("「名称」不能留空"))
            return
        if entry.get(field) == value:
            return
        self._apply_cell_edit(entry, field, value)

    def _revert_cell(self, item, message: str):
        self._edit_guard = True
        try:
            entry = next((r for r in self._rows if r.get("id") ==
                          self.table.item(item.row(), 0).data(Qt.UserRole)), None)
            if entry is not None:
                field = self.COLUMNS[item.column()][1]
                if field == "icon":
                    item.setText("")
                    item.setData(Qt.UserRole + 1, str(entry.get("icon") or ""))
                else:
                    item.setText(self._cell_text(entry, field))
        finally:
            self._edit_guard = False
        InfoBar.warning(title=self._t("这一格没有改"), content=message, orient=Qt.Horizontal,
                        isClosable=True, position=InfoBarPosition.TOP,
                        duration=3000, parent=self)

    def _apply_cell_edit(self, entry: dict, field: str, value):
        """把一格修改写回资源库（⚠️ 多语言字段只覆盖当前语言那个键）"""
        rid = entry.get("id")

        if isinstance(entry.get(field), dict):
            value = self._merge_i18n_cell(entry, field, value)

        if self._write_field(rid, field, value):
            if field == "name":
                self._rename_icon_for_entry(
                    rid, resolve_i18n_for_maker(entry.get("name")))
            shown = "" if value is None else str(value)
            InfoBar.success(
                title=self._t("已修改"),
                content=self._t("cell_changed_backup",
                                "{column}: {value} (library backed up automatically)").format(
                    column=self._col_title(field),
                    value=(shown if len(shown) <= 20 else shown[:20] + '…')),
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=2500, parent=self)

    def _merge_i18n_cell(self, entry: dict, field: str, value):
        """只覆盖"表格里显示的那一种语言"对应的键，返回合并后的字典（键必须是规范语言名）"""
        values = dict(entry.get(field) or {})
        # 和 _cell_text 的显示口径保持一致：谁有内容就改谁，都没有就写简中
        key = next((k for k in ("简体中文", "繁體中文", "English")
                    if str(values.get(k) or "").strip()), "简体中文")
        values[key] = value
        entry[field] = values
        return values

    # ---------- 写盘 ----------
    def _find_entry(self, rid) -> dict:
        """从磁盘上重新读一份，避免用旧副本覆盖别人的改动"""
        data = load_library(self.host.form_page.library_path)
        entry = next((r for r in data.get("resources", []) if r.get("id") == rid), None)
        if entry is None:               # 理论上不会发生，兜底用内存里的
            entry = next((r for r in self._rows if r.get("id") == rid), None)
        return entry

    def _write_field(self, rid, field: str, value) -> bool:
        """只改这一条的这一格，再整份写回同一个 ToolsGCP-Resources.json（写前自动备份）"""
        form = self.host.form_page
        path = form.library_path
        data = load_library(path)
        entry = next((r for r in data.get("resources", []) if r.get("id") == rid), None)
        if entry is None:
            InfoBar.error(title=self._t("找不到这条资源"), content=str(rid), orient=Qt.Horizontal,
                          isClosable=True, position=InfoBarPosition.TOP,
                          duration=3000, parent=self)
            self.reload()
            return False
        if value in ("", [], None):
            entry.pop(field, None)          # 允许清空：清掉了就不写进 JSON
        else:
            entry[field] = value
        # ⚠️ 改了类别或标签之后必须重新保证"tags 里没有 category 的值"，
        #    否则在浏览器里手改一格就能破坏 schema 的约定。
        if field in ("category", "tags"):
            cats = set(resource_schema.categories_of(entry))
            tags = [t for t in resource_schema.tags_of(entry) if t not in cats]
            if tags:
                entry["tags"] = tags
            else:
                entry.pop("tags", None)
        data.setdefault("metadata", {})["updated_at"] = \
            datetime.now().astimezone().replace(microsecond=0).isoformat()

        if os.path.exists(path) and not backup_library(path):
            InfoBar.error(title=self._t("备份失败，已中止写入"),
                          content=last_backup_error() or self._t("资源库没有被改动"),
                          orient=Qt.Horizontal, isClosable=True,
                          position=InfoBarPosition.TOP, duration=4000, parent=self)
            return False
        try:
            write_json(path, data)
        except Exception as e:
            InfoBar.error(title=self._t("写入失败"), content=str(e), orient=Qt.Horizontal,
                          isClosable=True, position=InfoBarPosition.TOP,
                          duration=4000, parent=self)
            return False

        form.reload_library_info()
        self._schedule_reload()             # 重读磁盘并刷新表格（下一轮事件循环，避免在信号里重建表格）
        return True

    def _schedule_reload(self):
        QTimer.singleShot(0, self.reload)

    def _col_title(self, field: str) -> str:
        """字段名 -> 当前语言的表头文案（语言文件里没有就退回 COLUMNS 里的中文）"""
        for title, name in BrowserPage.COLUMNS:
            if name == field:
                return self._t(self.COLUMN_TEXT_KEYS.get(field, field), title)
        return field

    def col_of(self, field: str) -> int:
        """字段名 -> 列号（表头/列顺序改动时不用到处改数字）"""
        for i, (_title, name) in enumerate(self.COLUMNS):
            if name == field:
                return i
        return -1

    def _find_row(self, rid):
        for i in range(self.table.rowCount()):
            head = self.table.item(i, 0)
            if head is not None and head.data(Qt.UserRole) == rid:
                return i
        return None

    def _set_cell_text(self, rid, field: str, text: str):
        row = self._find_row(rid)
        if row is None:
            return
        col = [c[1] for c in self.COLUMNS].index(field)
        item = self.table.item(row, col)
        if item is not None:
            self._edit_guard = True
            try:
                if field == "icon":
                    # ⚠️ 图标格显示的是缩略图：不能再把文件名 setText 回去（会在缩略图旁
                    #    多出一串截断的文字）；文件名挂在 UserRole+1 和悬停提示上。
                    item.setData(Qt.UserRole + 1, text)
                    item.setText("")
                    entry = self._find_entry(rid)
                    if entry is not None:
                        entry["icon"] = text
                        pixmap = self._icon_pixmap(entry)
                        item.setIcon(QIcon(pixmap) if pixmap is not None else QIcon())
                    item.setToolTip(str(text or ""))
                else:
                    item.setText(text)
            finally:
                self._edit_guard = False

    # ---------- 图标 ----------
    def _rename_icon_for_entry(self, rid, new_name: str):
        """名称改了以后，把这条资源的图片文件也改成新名字；返回旧文件名（没改动返回 None）"""
        form = self.host.form_page
        entry = self._find_entry(rid)
        if entry is None:
            return None
        old_name = os.path.basename(str(entry.get("icon") or ""))
        if not old_name:
            return None
        src = os.path.join(form.icon_dir, old_name)
        if not os.path.exists(src):
            return None
        ext = os.path.splitext(old_name)[1]
        base = icon_base_from_name(new_name, entry.get("id"))
        if os.path.normcase(old_name) == os.path.normcase(f"{base}{ext}"):
            return None
        name = unique_name_in(form.icon_dir, base, ext)
        if os.path.normcase(name) == os.path.normcase(old_name):
            return None
        moved = False
        for _attempt in range(2):
            try:
                os.rename(src, os.path.join(form.icon_dir, name))
                moved = os.path.exists(os.path.join(form.icon_dir, name))
                break
            except Exception as e:
                if _attempt == 1:
                    InfoBar.warning(title=self._t("图片没能跟着改名"), content=str(e),
                                    orient=Qt.Horizontal, isClosable=True,
                                    position=InfoBarPosition.TOP, duration=3500, parent=self)
                    return None
        if not moved:
            return None
        if self._write_field(rid, "icon", name):
            self._set_cell_text(rid, "icon", name)
            return old_name
        return None

    def pick_icon_for_row(self, row):
        """双击「图标」格子：挑一张图片，自动存进图标目录并改成应用名"""
        if row is None or row < 0:
            return
        head = self.table.item(row, 0)
        rid = head.data(Qt.UserRole) if head is not None else None
        entry = self._find_entry(rid)
        if entry is None:
            return
        form = self.host.form_page
        icon_dir = form.icon_dir
        old_name = os.path.basename(str(entry.get("icon") or ""))
        start = icon_dir if os.path.isdir(icon_dir) else os.path.expanduser("~")

        self._editing_icon = True       # 弹窗期间别让表格发 itemChanged 捣乱
        try:
            path, _ = QFileDialog.getOpenFileName(
                self,
                self._t("pick_icon_dialog_title", "Choose an image for \"{name}\"")
                .format(name=entry.get('name') or rid), start, image_filter())
        finally:
            self._editing_icon = False
        if not path:
            return
        if not os.path.exists(path):
            InfoBar.error(title=self._t("这个文件不存在"), content=path, orient=Qt.Horizontal,
                          isClosable=True, position=InfoBarPosition.TOP,
                          duration=3000, parent=self)
            return

        # 借用制作页那套"复制进图标目录 + 改成应用名 + 校验"的逻辑：先把表单状态临时
        # 摆成这一条，做完再还原，避免两处逻辑各写一遍。
        keep_form = (form.icon_source, form._icon_lib_name, form._icon_lib_path,
                     form._icon_is_src, form._loaded_id)
        self._editing_icon = True
        try:
            form._loaded_id = rid
            form.name_edit.setText(str(entry.get("name") or rid))
            form.id_edit.setText(str(entry.get("id") or rid))
            form.set_icon_from_library(old_name)
            name = form.copy_into_icon_dir(path)
        finally:
            form.icon_source, form._icon_lib_name, form._icon_lib_path, \
                form._icon_is_src, form._loaded_id = keep_form
            form.icon_edit.setText(form.icon_source)
            self._editing_icon = False
        if not name:
            return          # copy_into_icon_dir 已经弹过提示，资源库没被动

        if not self._write_field(rid, "icon", name):
            return
        self._set_cell_text(rid, "icon", name)
        if old_name and os.path.normcase(old_name) != os.path.normcase(name) \
                and not form._icon_in_use_elsewhere(old_name, exclude_id=rid):
            try:
                os.remove(os.path.join(icon_dir, old_name))
            except Exception:
                pass
        InfoBar.success(title=self._t("图片已换好"),
                        content=self._t("icon_replaced_backup",
                                        "{name} → {file} (library backed up automatically)").format(
                            name=entry.get('name') or rid, file=name),
                        orient=Qt.Horizontal, isClosable=True,
                        position=InfoBarPosition.TOP, duration=3000, parent=self)

    # ---------- 右键菜单 ----------
    def show_row_menu(self, pos):
        item = self.table.itemAt(pos)
        if item is None:
            return
        from qfluentwidgets import Action, RoundMenu
        self.table.selectRow(item.row())
        menu = RoundMenu(parent=self.table)
        act_edit = Action(self._t("load_into_form", "Load into the form"), self.table)
        act_edit.triggered.connect(self.load_into_form)
        menu.addAction(act_edit)
        act_icon = Action(self._t("换一张图片（改图标）"), self.table)
        act_icon.triggered.connect(lambda: self.pick_icon_for_row(item.row()))
        menu.addAction(act_icon)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ---------- 操作 ----------
    def load_into_form(self):
        ids = self._selected_ids()
        if not ids:
            InfoBar.warning(title=self._t("没有选中任何条目"),
                            content=self._t("先在表格里点一行，再点「载入到制作资源」"),
                            orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=2500, parent=self)
            return
        target = next((r for r in self._rows if r.get("id") == ids[0]), None)
        if target is None:
            return
        self.host.form_page.load_resource(target, self.data)
        switch_to_page(self.host, self.host.form_page)

    def delete_selected(self):
        ids = self._selected_ids()
        if not ids:
            InfoBar.warning(title=self._t("没有选中任何条目"), content=self._t("先在表格里选一行"),
                            orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=2500, parent=self)
            return
        names = ", ".join(str(r.get("name")) for r in self._rows if r.get("id") in ids)
        box = MessageBox(
            self._t("删除条目"),
            self._t("confirm_delete_entries",
                    "Delete these entries from the library?\n{names}").format(names=names), self)
        box.yesButton.setText(self._t("删除"))
        box.cancelButton.setText(self._t("取消"))
        if not box.exec():
            return

        path = self.host.form_page.library_path
        data = load_library(path)
        before = len(data.get("resources", []))
        removed_icons = []
        kept_icons = set()
        for r in data["resources"]:
            if r.get("id") not in ids:
                kept_icons.add(os.path.basename(str(r.get("icon") or "")))
        for r in data["resources"]:
            if r.get("id") in ids:
                icon = os.path.basename(str(r.get("icon") or ""))
                if icon and icon not in kept_icons:
                    removed_icons.append(icon)
        data["resources"] = [r for r in data["resources"] if r.get("id") not in ids]
        data.setdefault("metadata", {})["updated_at"] = \
            datetime.now().astimezone().replace(microsecond=0).isoformat()

        if os.path.exists(path) and not backup_library(path):
            InfoBar.error(title=self._t("备份失败，已中止删除"), content=self._t("资源库没有被改动"),
                          orient=Qt.Horizontal, isClosable=True,
                          position=InfoBarPosition.TOP, duration=4000, parent=self)
            return
        try:
            write_json(path, data)
        except Exception as e:
            InfoBar.error(title=self._t("写入失败"), content=str(e), orient=Qt.Horizontal,
                          isClosable=True, position=InfoBarPosition.TOP,
                          duration=4000, parent=self)
            return

        icon_dir = self.host.form_page.icon_dir
        for icon in removed_icons:
            full = os.path.join(icon_dir, icon)
            if os.path.exists(full):
                try:
                    os.remove(full)
                except Exception:
                    pass

        self.host.form_page.reload_library_info()
        self.reload()
        InfoBar.success(
            title=self._t("已删除"),
            content=self._t("entries_backed_up", "{n} entries (library backed up automatically)").format(
                n=before - len(data['resources'])),
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=3000, parent=self)

    def open_library_file(self):
        path = self.host.form_page.library_path
        folder = os.path.dirname(path) if os.path.exists(path) else os.path.dirname(path)
        try:
            os.startfile(folder)
        except Exception as e:
            InfoBar.error(title=self._t("打不开"), content=str(e), orient=Qt.Horizontal,
                          isClosable=True, position=InfoBarPosition.TOP,
                          duration=3000, parent=self)


# ---------- 批量合成页 ----------

# 投稿 JSON 多了以后手工搬容易出错，所以单独一页：追加模式 = 合进本机资源库；
# 新建模式 = 合并输出成一个新 JSON 文件（不动原库）。
class BatchPage(MakerPageMixin, QWidget):
    """批量合成工具"""

    MODE_APPEND = "append"      # 追加到本机资源库（默认）
    MODE_MERGE = "merge"        # 多个 JSON 合并成新文件

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.setObjectName("batchPage")
        self.host = host
        self._sources = []          # 选中的源文件路径
        self._cards = []
        self._tips = []             # ⓘ 图标（主题切换时要重新上色）

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = make_scroll(self)
        outer.addWidget(self.scroll)
        # ⚠️ 整页样式表在还没有子控件的时候套上（理由同表单页：建完卡片再套要 30ms）
        self._apply_page_stylesheet()

        self._content = QWidget()
        self.scroll.setWidget(self._content)
        self._body = QVBoxLayout(self._content)
        self._body.setContentsMargins(0, 10, 0, 18)
        self._body.setSpacing(CARD_GAP)

    # ---------- 按需构建（由 ResourceMakerInterface 分步调用）----------
    def build_steps(self) -> list:
        """一步一张卡片（每步 2~5ms，见 FormPage.build_steps 的说明）"""
        return [
            (self._t("合成模式卡片"), lambda: self._body.addWidget(
                self._build_mode_card(self._content))),
            (self._t("选择文件卡片"), lambda: self._body.addWidget(
                self._build_files_card(self._content))),
            (self._t("输出位置卡片"), lambda: self._body.addWidget(
                self._build_output_card(self._content))),
            (self._t("执行卡片"), lambda: self._body.addWidget(
                self._build_run_card(self._content))),
        ]

    def finish_build(self):
        """四张卡片都加进来了：补弹簧 + 上主题 + 按当前模式显示/隐藏 + 写好文件计数"""
        self._body.addStretch(1)
        self.apply_theme()
        self.on_mode_changed()
        self.refresh_files()        # 先写上"已选 0 个文件"，别让右下角空着

    # ---------- 卡片 ----------
    def _card(self, parent, title: str, tip: str = ""):
        """一张卡片：标题 +（可选）一句说明 + 内容区"""
        card, layout = make_card(parent, title)
        self._cards.append(card)
        if tip:
            hint = CaptionLabel(tip, card)
            hint.setWordWrap(True)
            style_hint(hint)
            layout.addWidget(hint)
        return card, layout

    @staticmethod
    def _setting_row(parent, title: str, control, tip: str = "") -> QWidget:
        """一行设置：左标题（+ ⓘ）…… 右控件（统一 CONTROL_WIDTH、右对齐）"""
        row = QWidget(parent)
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(12)
        box.addWidget(BodyLabel(title, row))
        if tip:
            row._maker_tip = TipIcon(tip, row)
            box.addWidget(row._maker_tip, 0, Qt.AlignVCenter)
        box.addStretch(1)
        control.setFixedWidth(CONTROL_WIDTH)
        box.addWidget(control, 0, Qt.AlignVCenter)
        return row

    def _add_setting_row(self, card, layout, title: str, control, tip: str = ""):
        """加一行设置，并把它的 ⓘ 登记进主题刷新列表"""
        row = self._setting_row(card, title, control, tip)
        icon = getattr(row, "_maker_tip", None)
        if icon is not None:
            self._tips.append(icon)
        layout.addWidget(row)
        return row

    def _build_mode_card(self, parent):
        card, layout = self._card(
            parent, self._t("① 选择合成模式"),
            self._t("追加模式：把投稿的条目合进本机资源库，已经有的编码会自动跳过。\n新建模式：把多个投稿文件合并成一个新的 JSON，原来的文件不动。"))

        self.mode_combo = ComboBox(card)
        self.mode_combo.addItem(self._t("追加到本机资源库（默认）"), userData=self.MODE_APPEND)
        self.mode_combo.addItem(self._t("多个 JSON 合并成新文件"), userData=self.MODE_MERGE)
        # ⚠️ 必须显式给足宽度：ComboBox 按当前选中项算宽度，默认会挡掉最长选项的最后一个字符
        try:
            from PyQt5.QtGui import QFontMetrics
            fm = QFontMetrics(self.mode_combo.font())
            widest = max(fm.width(self.mode_combo.itemText(i))
                         for i in range(self.mode_combo.count()))
            self.mode_combo.setMinimumWidth(widest + 76)   # 76 ≈ 箭头 + 内边距
        except Exception:
            self.mode_combo.setMinimumWidth(240)
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        self._add_setting_row(card, layout, self._t("合成模式"), self.mode_combo)

        self.dup_combo = ComboBox(card)
        self.dup_combo.addItem(self._t("跳过重复（推荐）"), userData="skip")
        self.dup_combo.addItem(self._t("重复的覆盖旧条目"), userData="overwrite")
        self.dup_combo.addItem(self._t("全部保留（重新分配编码）"), userData="keep")
        self._add_setting_row(
            card, layout, self._t("重复条目"), self.dup_combo,
            self._t("判断重复的依据：编码相同，或者标识 id 相同"))
        return card

    def _build_files_card(self, parent):
        card, layout = self._card(
            parent, self._t("② 选择要合成的 JSON 文件"),
            self._t("batch_files_hint",
                    "You can select several at once; a plain list or {\"resources\": [...]} both work."))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.add_files_btn = PushButton(self._t("添加文件"), card, FIF.ADD)
        self.add_files_btn.clicked.connect(self.add_files)
        row.addWidget(self.add_files_btn)

        self.remove_file_btn = PushButton(self._t("移除选中"), card, FIF.DELETE)
        self.remove_file_btn.clicked.connect(self.remove_selected)
        row.addWidget(self.remove_file_btn)

        self.clear_files_btn = PushButton(self._t("清空列表"), card, FIF.CANCEL)
        self.clear_files_btn.clicked.connect(self.clear_files)
        row.addWidget(self.clear_files_btn)
        row.addStretch()
        self.files_count = CaptionLabel("", card)
        style_hint(self.files_count)
        row.addWidget(self.files_count)
        layout.addLayout(row)

        self.files_list = ListWidget(card)
        self.files_list.setMinimumHeight(150)
        self.files_list.setSelectionMode(ListWidget.ExtendedSelection)
        layout.addWidget(self.files_list)
        return card

    def _build_output_card(self, parent):
        self.output_card, layout = self._card(parent, self._t("③ 输出位置"))

        self.append_row = QWidget(self.output_card)
        arow = QHBoxLayout(self.append_row)
        arow.setContentsMargins(0, 0, 0, 0)
        arow.setSpacing(8)
        arow.addWidget(BodyLabel(self._t("目标资源库"), self.append_row))
        arow.addStretch()
        self.library_label = CaptionLabel("", self.append_row)
        style_hint(self.library_label)
        arow.addWidget(self.library_label)
        layout.addWidget(self.append_row)

        self.merge_row = QWidget(self.output_card)
        mrow = QHBoxLayout(self.merge_row)
        mrow.setContentsMargins(0, 0, 0, 0)
        mrow.setSpacing(8)
        mrow.addWidget(BodyLabel(self._t("保存到"), self.merge_row))
        self.output_edit = LineEdit(self.merge_row)
        self.output_edit.setPlaceholderText(self._t("选择新 JSON 的保存位置"))
        mrow.addWidget(self.output_edit, 1)
        self.output_btn = PushButton(self._t("选择…"), self.merge_row, FIF.SAVE_AS)
        self.output_btn.clicked.connect(self.choose_output)
        mrow.addWidget(self.output_btn)
        layout.addWidget(self.merge_row)

        self.mode_tip = CaptionLabel("", self.output_card)
        self.mode_tip.setWordWrap(True)
        style_hint(self.mode_tip)
        layout.addWidget(self.mode_tip)
        return self.output_card

    def _build_run_card(self, parent):
        card, layout = self._card(parent, self._t("④ 检查并执行"))
        self.preview_label = CaptionLabel(self._t("点「预览结果」看看会合并进来多少条。"), card)
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.preview_btn = PushButton(self._t("预览结果"), card, FIF.VIEW)
        self.preview_btn.clicked.connect(self.preview)
        row.addWidget(self.preview_btn)
        row.addStretch()
        self.run_btn = PrimaryPushButton(self._t("开始合成"), card, FIF.ACCEPT)
        self.run_btn.clicked.connect(self.run)
        row.addWidget(self.run_btn)
        layout.addLayout(row)
        return card

    # ---------- 主题 ----------
    def _apply_page_stylesheet(self):
        """整页样式表：只在骨架阶段套这一次（理由同 FormPage._apply_page_stylesheet）"""
        self.setStyleSheet(f"""
            #batchPage {{ background: transparent; }}
            {SCROLL_QSS}
        """)

    def apply_theme(self, dark: bool = None):
        """主题切换：卡片徽标/分隔线 + ⓘ + 说明字颜色（不重套整页样式表；本节按需构建）"""
        for card in self._cards:
            apply_card_theme(card, dark)
        for icon in self._tips:
            icon.apply_theme(dark)
        for label in (getattr(self, "files_count", None), getattr(self, "mode_tip", None),
                      getattr(self, "library_label", None)):
            if label is not None:
                style_hint(label)
        apply_themed_scrollbar(self.scroll)

    def refresh_theme(self):
        self.apply_theme()

    def refresh_scrollbars(self):
        apply_themed_scrollbar(self.scroll)

    # ---------- 输出位置 ----------
    def choose_output(self):
        """选择新 JSON 的保存位置"""
        start = self.output_edit.text().strip() or self.host.form_page.project_root
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("保存合并结果"), os.path.join(start, "ToolsGCP-Resources-merged.json"),
            self._t("JSON 文件 (*.json)"))
        if path:
            if not path.lower().endswith(".json"):
                path += ".json"
            self.output_edit.setText(path)

    # ---------- 模式 ----------
    def current_mode(self) -> str:
        return self.mode_combo.currentData() or self.MODE_APPEND

    def on_mode_changed(self, _index=None):
        mode = self.current_mode()
        is_append = (mode == self.MODE_APPEND)
        self.append_row.setVisible(is_append)
        self.merge_row.setVisible(not is_append)
        self.mode_tip.setText(
            self._t("会把合进来的条目直接写进本机资源库，写入前会自动备份一份。")
            if is_append else
            self._t("只生成一个新文件，本机资源库不受影响，之后可以再导进来。"))
        self.library_label.setText(elide_path(self.host.form_page.library_path))
        self.library_label.setToolTip(self.host.form_page.library_path)
        self.preview_label.setText(self._t("点「预览结果」看看会合并进来多少条。"))

    # ---------- 文件 ----------
    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, self._t("选择要合成的 JSON"), self.host.form_page.project_root,
            self._t("JSON 文件 (*.json)"))
        for path in paths:
            if path not in self._sources:
                self._sources.append(path)
        self.refresh_files()

    def remove_selected(self):
        rows = sorted((self.files_list.row(i) for i in self.files_list.selectedItems()),
                      reverse=True)
        for row in rows:
            if 0 <= row < len(self._sources):
                self._sources.pop(row)
        self.refresh_files()

    def clear_files(self):
        self._sources = []
        self.refresh_files()

    def refresh_files(self):
        self.files_list.clear()
        for path in self._sources:
            item = QListWidgetItem(path)
            self.files_list.addItem(item)
        self.files_count.setText(
            self._t("files_selected", "{n} file(s) selected").format(n=len(self._sources)))

    # ---------- 读取源文件 ----------
    @staticmethod
    def read_sources(paths):
        """读取一批 JSON，返回 (所有条目, 每个文件的条目数, 读不了的文件)"""
        entries = []
        per_file = []
        failed = []
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
            except Exception as e:
                failed.append((path, str(e)))
                continue
            if isinstance(data, dict):
                items = data.get("resources") or data.get("items") or []
            elif isinstance(data, list):
                items = data
            else:
                items = []
            items = [i for i in items if isinstance(i, dict)]
            per_file.append((path, len(items)))
            entries.extend(items)
        return entries, per_file, failed

    @staticmethod
    def entry_key(entry: dict) -> tuple:
        """判断重复用的键：优先编码，其次标识 id，再其次名称"""
        return (str(entry.get("code") or "").strip(),
                str(entry.get("id") or "").strip(),
                str(entry.get("name") or "").strip())

    def merge_entries(self, existing, incoming, strategy):
        """把 incoming 合进 existing，返回 (结果列表, 统计)"""
        result = list(existing)
        stat = {"added": 0, "skipped": 0, "overwritten": 0, "recoded": 0}

        codes = {str(r.get("code") or "").strip() for r in result}
        ids = {str(r.get("id") or "").strip() for r in result}
        names = {str(r.get("name") or "").strip() for r in result}

        def find_index(entry):
            code = str(entry.get("code") or "").strip()
            rid = str(entry.get("id") or "").strip()
            name = str(entry.get("name") or "").strip()
            for i, r in enumerate(result):
                if code and str(r.get("code") or "").strip() == code:
                    return i
                if rid and str(r.get("id") or "").strip() == rid:
                    return i
                if name and str(r.get("name") or "").strip() == name:
                    return i
            return -1

        for entry in incoming:
            item = dict(entry)
            index = find_index(item)
            is_duplicate = index >= 0

            if is_duplicate:
                if strategy == "skip":
                    stat["skipped"] += 1
                    continue
                if strategy == "overwrite":
                    result[index] = item
                    stat["overwritten"] += 1
                    continue
                # keep：两条都留，只给重复的那条重新分配编码和标识（不重复的保留原编码）
                item["code"] = next_code(result)
                base_id = str(item.get("id") or slugify(str(item.get("name") or "item")))
                new_id = base_id
                n = 2
                while new_id in ids:
                    new_id = f"{base_id}-{n}"
                    n += 1
                item["id"] = new_id
                stat["recoded"] += 1
            elif not str(item.get("code") or "").strip():
                item["code"] = next_code(result)

            result.append(item)
            codes.add(str(item.get("code") or ""))
            ids.add(str(item.get("id") or ""))
            names.add(str(item.get("name") or ""))
            stat["added"] += 1

        return result, stat

    # ---------- 预览 / 执行 ----------
    def preview(self):
        if not self._sources:
            InfoBar.warning(title=self._t("还没选文件"), content=self._t("先添加要合成的 JSON"),
                            orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=2500, parent=self)
            return None
        entries, per_file, failed = self.read_sources(self._sources)
        library = load_library(self.host.form_page.library_path)
        merged, stat = self.merge_entries(library.get("resources", []), entries,
                                          self.dup_combo.currentData() or "skip")

        lines = [self._t("merge_src_summary", "{files} source file(s), {n} entries in total:").format(
            files=len(per_file), n=len(entries))]
        for path, n in per_file[:8]:
            lines.append(self._t("merge_src_item", "    {name} — {n} entries").format(
                name=os.path.basename(path), n=n))
        if len(per_file) > 8:
            lines.append(self._t("merge_more_files", "    …and {n} more file(s)").format(
                n=len(per_file) - 8))
        lines.append(self._t("merge_result",
                             "Result: {added} added, {skipped} duplicates skipped, {overwritten} overwritten, {recoded} re-coded").format(
            added=stat['added'], skipped=stat['skipped'],
            overwritten=stat['overwritten'], recoded=stat['recoded']))
        lines.append(self._t("merge_count_change",
                             "The library will go from {before} to {after} entries").format(
            before=len(library.get('resources', [])), after=len(merged)))
        if failed:
            lines.append(self._t("⚠️ 读不了的文件：") + ", ".join(os.path.basename(p) for p, _ in failed))
        self.preview_label.setText("\n".join(lines))
        return merged, stat, library

    def run(self):
        if not self._sources:
            InfoBar.warning(title=self._t("还没选文件"), content=self._t("先添加要合成的 JSON"),
                            orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=2500, parent=self)
            return
        result = self.preview()
        if result is None:
            return
        merged, stat, library = result
        mode = self.current_mode()

        if mode == self.MODE_APPEND:
            target = self.host.form_page.library_path
            box = MessageBox(
                self._t("确认合成"),
                self._t("confirm_merge_write",
                        "{n} new entries will be written to the local library:\n{path}\n\n(A backup is made first)")
                .format(n=stat['added'], path=target), self)
            box.yesButton.setText(self._t("开始合成"))
            box.cancelButton.setText(self._t("取消"))
            if not box.exec():
                return
            data = dict(library)
            # 合成进来的可能是老格式（category 逗号串、tags 里重复类别）→ 写盘前过一遍 schema
            data["resources"] = [
                resource_schema.normalize(item) if isinstance(item, dict) else item
                for item in merged]
            data.setdefault("metadata", {})
            data["metadata"]["updated_at"] = \
                datetime.now().astimezone().replace(microsecond=0).isoformat()
            data["metadata"]["total_count"] = len(merged)
            for item in data["resources"]:
                if isinstance(item, dict) and not item.get("listed_at"):
                    item["listed_at"] = now_listed_at()
            try:
                if os.path.exists(target) and not backup_library(target):
                    self._error(self._t("备份失败，已中止写入（资源库没有被改动）"))
                    return
                write_json(target, data)
            except Exception as e:
                self._error(self._t("write_failed", "Write failed: {err}").format(err=e))
                return
            self.host.form_page.reload_library_info()
            # 浏览页是按需建的：没建过就别去碰它（下次切过去时它自己会读盘）
            browser = getattr(self.host, "browser_page", None)
            if browser is not None:
                browser.reload()
            self._ok(self._t("merged_ok",
                             "Merged {n} entries into the library (backed up to backups/)")
                     .format(n=stat['added']))
        else:
            out = self.output_edit.text().strip()
            if not out:
                self._error(self._t("先选一个保存位置"))
                return
            data = {
                "schema_version": library.get("schema_version", "2.0.0"),
                "metadata": {
                    "icon_dir": library.get("metadata", {}).get("icon_dir", ICON_DIR_NAME),
                    "updated_at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
                    "total_count": len(merged),
                },
                "resources": merged,
            }
            try:
                write_json(out, data)
            except Exception as e:
                self._error(self._t("write_failed", "Write failed: {err}").format(err=e))
                return
            self._ok(self._t("generated_ok", "Created {path} ({n} entries)")
                     .format(path=out, n=len(merged)))

    # ---------- 提示 ----------
    def _ok(self, message):
        InfoBar.success(title=self._t("完成"), content=message, orient=Qt.Horizontal,
                        isClosable=True, position=InfoBarPosition.TOP,
                        duration=4000, parent=self)

    def _error(self, message):
        InfoBar.error(title=self._t("出错了"), content=message, orient=Qt.Horizontal,
                      isClosable=True, position=InfoBarPosition.TOP,
                      duration=4000, parent=self)


# ---------- 使用说明页 ----------
def split_help_blocks(text: str, default_title: str = "使用说明",
                      drop_preamble: bool = True) -> list:
    """把使用说明按【小节】拆成 [(标题, 正文), …]（第一段没标题时算"使用说明"）

    ⚠️ 必须拆：4KB 整段塞给 WordWrap 的 BodyLabel 会反复重排（实测 684ms），拆成小卡片降到 186ms。
    """
    blocks = []          # [(显式小节标题 或 None, 正文), …]
    title = None
    body = []

    def flush():
        if body or title:
            blocks.append((title, "\n".join(body).strip("\n")))

    for line in str(text or "").splitlines():
        # ⚠️ 两种小节标题写法都认：中文用【】，英文翻译用 [ ]；不认后者的话，
        #    切到英文整篇会挤成一张卡片（又难看又撞上上面说的重排开销）。
        match = re.match(r"^\s*(?:【(.+?)】|\[(.+?)\])\s*$", line)
        if match:
            flush()
            title = match.group(1) or match.group(2)
            body = []
        else:
            body.append(line)
    flush()

    # 丢掉开头那段"整篇文档标题"（见 drop_preamble）：它没有【小节】标题且正文只有一行
    if drop_preamble and blocks and blocks[0][0] is None:
        first_body = blocks[0][1]
        if len([ln for ln in first_body.splitlines() if ln.strip()]) <= 1:
            blocks = blocks[1:]

    # 去掉纯空的小节（避免出现一张空卡片）；没有标题的那段用 default_title
    return [(t or default_title, b) for t, b in blocks if b.strip()]


class HelpPage(MakerPageMixin, QWidget):
    """内置手册：按小节拆成一张张卡片放在滚动区里（拆分理由见 split_help_blocks）"""

    def __init__(self, host=None, parent=None):
        super().__init__(parent)
        self.setObjectName("helpPage")
        self.host = host
        self._cards = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = make_scroll(self)
        outer.addWidget(self.scroll)

        self._content = QWidget()
        self.scroll.setWidget(self._content)
        self.body = QVBoxLayout(self._content)
        self.body.setContentsMargins(0, 10, 0, 18)
        self.body.setSpacing(CARD_GAP)
        self.body.setAlignment(Qt.AlignTop)

        # ⚠️ 使用说明是一整篇文档，所以整篇走一个语言键（help_text）；第一个小节没有
        #    【】标题，它的名字也走语言键（help_first_block_title）。
        self._blocks = split_help_blocks(
            self._t("help_text", HELP_TEXT),
            self._t("help_first_block_title", "Help"))

    # ---------- 按需构建（由 ResourceMakerInterface 分步调用）----------
    def build_steps(self) -> list:
        """一步一张卡片（每张 15~25ms），中间事件循环能回去重绘 / 响应点击"""
        return [(self._t("step_title_wrap", "「{title}」").format(title=title),
                 lambda t=title, b=text: self._add_block(t, b))
                for title, text in self._blocks]

    def _add_block(self, title: str, text: str):
        card, layout = make_card(self._content, title)
        label = BodyLabel(text, card)
        label.setWordWrap(True)
        # ⚠️ 正文限宽：卡片拉满 1000+px 后一行能塞三十多个字，眼睛从行尾找回行首容易串行。
        # ⚠️ 不能给 addWidget 传对齐标志：带 AlignLeft 时布局按 sizeHint 给宽度，
        #    而开了 WordWrap 的标签 sizeHint 很窄 → 文字被折成一条 360px 的窄柱子。
        label.setMaximumWidth(HELP_TEXT_MAX_WIDTH)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(label)
        self.body.addWidget(card)
        self._cards.append(card)
        apply_card_theme(card)

    def finish_build(self):
        """卡片都进来了：补上底部弹簧并上主题"""
        self.body.addStretch(1)
        self.apply_theme()

    def apply_theme(self, dark: bool = None):
        for card in self._cards:
            apply_card_theme(card, dark)
        apply_themed_scrollbar(self.scroll)

    def refresh_theme(self):
        self.apply_theme()


__all__ = [
    "HELP_TEXT", "CARD_GAP", "CARD_PADDING", "CARD_RADIUS", "CONTROL_WIDTH",
    "PreviewCard", "FormGrid", "FormPage", "BrowserPage", "BatchPage", "HelpPage",
    "make_card", "make_divider", "make_scroll", "apply_card_theme",
    "split_help_blocks",
]
