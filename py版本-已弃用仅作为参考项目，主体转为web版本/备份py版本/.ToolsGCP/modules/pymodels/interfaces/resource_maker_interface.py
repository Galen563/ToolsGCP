"""
提交软件（资源制作器）页面
==========================

左侧栏「更多 → 提交软件」点进来的就是这一页：页头 + 页内分节切换 + 四个功能页。
独立工具的 FluentWindow 不能嵌进主窗口，所以这里自己搭页头 / 分段控件 / QStackedWidget；
页面与主程序之间隔一层 ResourceMakerHost 适配器。用法：构造后塞进主窗口的 stackedWidget。

⚠️ 分节按需构建且分步建（见 build_steps / _pump_section_build）：一次全建要 0.9s，
   会堵死事件循环，被 Windows 标成"未响应"。
⚠️ 分节切换用 SegmentedWidget，不能用 NavigationInterface（那是外层主窗口的）。
"""

import os

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    CaptionLabel, FluentIcon as FIF, IndeterminateProgressBar, InfoBar,
    InfoBarPosition, SegmentedWidget, SubtitleLabel,
)

from .settings.theme import SIZES, apply_accent_color
from .settings.widgets import TipIcon
from .resource_maker_core import (
    ICON_DIR_NAME, accent_color_applied, is_dark_mode, load_library,
    project_root, resource_library_path, theme_tokens,
)
from .resource_maker_pages import (
    BatchPage, BrowserPage, FormPage, HelpPage, style_hint,
)

# 页内分节：(内部键, 按钮文字, 图标)
SECTIONS = [
    ("form", "投稿表单", FIF.EDIT),
    ("browser", "资源浏览", FIF.LIBRARY),
    ("batch", "批量合成", FIF.ZIP_FOLDER),
    ("help", "使用说明", FIF.HELP),
]

# 内容最大宽度：四个分节统一用投稿表单那一档，切分节时 root 宽度不变，
# 界面才不会"组件动来动去"（窄窗口时由 _apply_root_width 缩到可用宽度）。
FORM_MAX_WIDTH = 1600            # 投稿表单那一档 = 标准宽度（等于"用满可用宽度"）
SECTION_MAX_WIDTH = {
    "form": FORM_MAX_WIDTH,
    "browser": FORM_MAX_WIDTH,
    "batch": FORM_MAX_WIDTH,
    "help": FORM_MAX_WIDTH,
}
DEFAULT_MAX_WIDTH = FORM_MAX_WIDTH

SECTION_TITLES = {key: text for key, text, _icon in SECTIONS}


class SectionPlaceholder(QWidget):
    """分节还没建好时先顶上的占位页（进度是真的：就是 _pump_section_build 当前那一步）

    ⚠️ 四个功能页一次建完要 0.9s，会堵死事件循环、被 Windows 标成"未响应"。
    """

    def __init__(self, section_key: str, parent=None):
        super().__init__(parent)
        self.setObjectName("makerSectionPlaceholder")

        box = QVBoxLayout(self)
        margin = SIZES["content_margin"]
        box.setContentsMargins(margin, 0, margin, 0)
        box.setSpacing(10)
        box.addStretch(1)

        self.title_label = SubtitleLabel(
            self._t("section_preparing", "Preparing \"{title}\"…")
            .format(title=self._section_title(section_key)), self)
        self.title_label.setAlignment(Qt.AlignCenter)
        box.addWidget(self.title_label)

        self.bar = IndeterminateProgressBar(self)
        self.bar.setFixedWidth(180)
        box.addWidget(self.bar, 0, Qt.AlignHCenter)

        self.step_label = CaptionLabel("", self)
        self.step_label.setAlignment(Qt.AlignCenter)
        style_hint(self.step_label)
        box.addWidget(self.step_label)
        box.addStretch(1)

    # ---------- 文案 ----------
    def _t(self, key: str, fallback: str = "") -> str:
        """拿当前语言的文案（顺着父子链找能取文案的控件，找不到用中文兜底）"""
        node = self
        while node is not None:
            getter = getattr(node, "get_text", None)
            if callable(getter):
                try:
                    text = getter(key)
                    if text and text != key:
                        return text
                except Exception:
                    pass
                break
            node = node.parentWidget()
        return fallback or key

    def _section_title(self, key: str) -> str:
        """分节名（当前语言），查不到退回 SECTIONS 里的中文"""
        return self._t(f"section_{key}", SECTION_TITLES.get(key, key))

    def set_progress(self, label: str, index: int, total: int):
        """正在做哪一步、第几步（total 为 0 时只写这一步做什么）"""
        self.step_label.setText(
            self._t("step_progress", "{label} (step {n}/{total})")
            .format(label=label, n=index, total=total) if total else str(label))

    def set_error(self, message: str, section_key: str = ""):
        """某一步没建成功：转成"错误页"停在这里

        ⚠️ 不推半成品页面：漏了控件的页面看着正常、其实按不了。
        """
        self.title_label.setText(
            self._t("section_failed", "Could not prepare \"{title}\"")
            .format(title=self._section_title(section_key)))
        self.bar.hide()
        self.step_label.setText(str(message))


class ResourceMakerHost:
    """页面 ↔ 主程序之间的适配层（四个页面认的就是它）

    页面只用得到：路径（project_root / library_path / icon_dir）、兄弟页面（*_page）、
    互跳（switchTo / show_section）、提示（show_message）、写盘通知、主题。

    ⚠️ 四个 *_page 属性按需回填：没建过的分节是 None；投稿表单总是第一个建的。
    """

    def __init__(self, interface, language_manager=None, settings_manager=None):
        self.interface = interface
        self.language_manager = language_manager
        self.settings_manager = settings_manager
        self.form_page = None
        self.browser_page = None
        self.batch_page = None
        self.help_page = None

    # ---------- 路径 ----------
    @property
    def project_root(self) -> str:
        """项目根目录（含 .ToolsGCP 的那一层，也就是 ToolsGCP.pyw 所在目录）"""
        return project_root()

    def library_path(self) -> str:
        """本机资源库文件：<项目根>/.ToolsGCP/ToolsGCP-Resources.json（全程序只有这一个）"""
        return resource_library_path()

    def icon_dir(self) -> str:
        """图标目录的完整路径（跟资源库 metadata.icon_dir 保持一致）"""
        if self.form_page is not None:
            return self.form_page.icon_dir
        name = str((load_library(self.library_path()).get("metadata") or {})
                   .get("icon_dir") or ICON_DIR_NAME)
        return os.path.join(self.project_root, name.strip("/\\").replace("/", os.sep))

    # ---------- 页面互跳 ----------
    def switchTo(self, page):
        """切到某个页面（保留独立工具里的方法名，浏览页「载入到制作资源」在用）"""
        self.interface.show_page(page)

    def show_section(self, key: str):
        """按分节键切换（form / browser / batch / help）"""
        self.interface.show_section(key)

    # ---------- 文案 ----------
    def get_text(self, key: str) -> str:
        """文案（转发给界面，读 maker 段）

        ⚠️ 页面的 _t() 找的就是这个方法，缺了它所有 _t() 都会退回中文兜底。
        """
        getter = getattr(self.interface, "get_text", None)
        if callable(getter):
            try:
                text = getter(key)
                if text:
                    return text
            except Exception:
                pass
        return key

    # ---------- 提示 ----------
    def show_message(self, message: str, msg_type: str = "info", parent=None):
        """统一提示：页面自己也能直接用 InfoBar，这里是给界面/外部脚本用的口子"""
        self.interface.show_message(message, msg_type, parent)

    # ---------- 刷新 ----------
    def notify_library_changed(self):
        """资源库被写过之后的刷新通知

        ⚠️ 只刷新页头条数，不再回头 reload 别的页面（会来回递归）。
        """
        self.interface.refresh_library_status()

    # ---------- 主题 ----------
    def is_dark(self) -> bool:
        return is_dark_mode()

    def apply_theme(self, dark: bool = None):
        self.interface.apply_theme(dark)


class ResourceMakerInterface(QWidget):
    """提交软件页：页头 + 页内分节切换 + 四个功能页（投稿表单 / 资源浏览器 / 批量合成 / 使用说明）"""

    def __init__(self, language_manager=None, settings_manager=None, parent=None):
        super().__init__(parent)
        self.setObjectName("resourceMakerInterface")
        # ⚠️ 必须显式写 False：本页是从「更多」菜单 addWidget 进来的、属性默认 None，
        #    而 FluentWindow._updateStackedBackground 里 False == None 不成立，
        #    每次点开都会白跑一次 setStyle(QApplication.style())（实测 166ms）。
        self.setProperty("isStackedTransparent", False)
        self.lang = language_manager
        self.settings_manager = settings_manager

        self.host = ResourceMakerHost(self, language_manager, settings_manager)
        self._pages = {}                # 分节键 -> 页面对象（骨架建好就算）
        self._built = set()             # 已经**完全**建好的分节键
        self._placeholders = {}         # 分节键 -> 占位页
        self._current_key = ""
        # 按需构建的进度状态（见 _ensure_section / _pump_section_build）
        self._build_queue = []          # [(分节键, 步骤名, 要执行的函数)]
        self._build_steps_total = {}    # 分节键 -> 一共几步
        self._build_steps_done = {}     # 分节键 -> 已经做完几步
        self._build_failed = set()      # 有步骤崩了的分节（停在占位页上显示原因）
        self._pumping = False           # 事件循环里有没有排着"下一步"

        self.setup_ui()
        self.apply_theme()

    # ---------- UI ----------
    def setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ⚠️ 整页样式表趁还没有子控件时套上，且只有 setup_ui 这一处：
        #    setStyleSheet 会重渲染本页所有子控件样式，等四个分节建好再套是几百毫秒。
        self.setStyleSheet("""
            #resourceMakerInterface, #resourceMakerRoot { background: transparent; }
        """)

        self.root = QWidget(self)
        self.root.setObjectName("resourceMakerRoot")
        outer.addWidget(self.root, 1, Qt.AlignHCenter)

        box = QVBoxLayout(self.root)
        margin = SIZES["content_margin"]
        box.setContentsMargins(margin, 22, margin, 16)
        box.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.title_label = SubtitleLabel(self.get_text("title"), self.root)
        title_box.addWidget(self.title_label)
        self.subtitle_label = CaptionLabel(self.get_text("subtitle"), self.root)
        self.subtitle_label.setWordWrap(True)
        style_hint(self.subtitle_label)
        title_box.addWidget(self.subtitle_label)
        # ⚠️ 给标题行 stretch=1（而不是后面挂一个 addStretch）：说明文字是自动换行的，
        # 不给它弹性的话它只会拿到"最窄的 sizeHint"，几十个字被折成三四行。
        header.addLayout(title_box, 1)
        box.addLayout(header)

        # ---------- 1px 分隔线 ----------
        self.divider = QFrame(self.root)
        self.divider.setFixedHeight(1)
        box.addWidget(self.divider)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.segmented = SegmentedWidget(self.root)
        for key, text, icon in SECTIONS:
            self.segmented.addItem(key, self.section_title(key), icon=icon)
        self.segmented.currentItemChanged.connect(self.show_section)
        toolbar.addWidget(self.segmented)

        toolbar.addStretch(1)

        self.library_status = CaptionLabel("", self.root)
        style_hint(self.library_status)
        toolbar.addWidget(self.library_status)

        self.library_tip = TipIcon(self.get_text("library_tip"), self.root)
        toolbar.addWidget(self.library_tip, 0, Qt.AlignVCenter)
        box.addLayout(toolbar)

        self.stack = QStackedWidget(self.root)
        box.addWidget(self.stack, 1)

        # ⚠️ 四个分节按需构建：全建一遍要 0.9s（事件循环被堵 955ms，Windows 标"未响应"），
        #    只有当前这一节先建，其余第一次切过去时才建 —— 见 _ensure_section。
        self.show_section(SECTIONS[0][0])

    # ---------- 分节：按需构建 ----------
    def _page_builders(self) -> dict:
        """分节键 -> 建页函数（只建骨架，剩下的交给 build_steps）

        ⚠️ 建好就挂到宿主上（host.form_page / …），浏览页/批量页靠它拿资源库路径。
        """
        return {
            "form": lambda: FormPage(self.host, self.stack),
            "browser": lambda: BrowserPage(self.host, self.stack),
            "batch": lambda: BatchPage(self.host, self.stack),
            "help": lambda: HelpPage(self.host, self.stack),
        }

    def _ensure_section(self, key: str):
        """拿到某一节的页面；第一次访问时现建，返回"现在该显示在 stack 里的控件"

        已建好 → 真页面；正在建 → 占位页（建完由 _complete_section 换上）；无可拆步骤 → 真页面。
        """
        if key in self._built:
            return self._pages.get(key)
        if key in self._pages:                  # 已经在建（或排着队）
            return self._placeholders.get(key) or self._pages.get(key)

        builder = self._page_builders().get(key)
        if builder is None:
            return None

        page = builder()
        self._pages[key] = page
        setattr(self.host, f"{key}_page", page)
        if self.stack.indexOf(page) < 0:
            self.stack.addWidget(page)

        steps = list(getattr(page, "build_steps", lambda: [])() or [])
        self._build_steps_total[key] = len(steps)
        self._build_steps_done[key] = 0
        if not steps:                           # 没有可拆的步骤：立刻算建好
            self._complete_section(key)
            return page

        placeholder = self._placeholders.get(key)
        if placeholder is None:
            placeholder = SectionPlaceholder(key, self.stack)
            self._placeholders[key] = placeholder
            self.stack.addWidget(placeholder)
        placeholder.set_progress(steps[0][0], 1, len(steps))
        for label, fn in steps:
            self._build_queue.append((key, label, fn))
        self.stack.setCurrentWidget(placeholder)    # addWidget 会把新加的设成当前页，这里拉回来
        self._schedule_pump()
        return placeholder

    def _schedule_pump(self):
        """排下一步构建（走事件循环，让中间的重绘/点击有机会执行）"""
        if self._pumping:
            return
        self._pumping = True
        QTimer.singleShot(0, self._pump_section_build)

    def _pump_section_build(self):
        """构建泵：一次事件循环只做一步（一步≈一张卡片 10~40ms），避免长时间阻塞"""
        self._pumping = False
        if not self._build_queue:
            return
        key, label, fn = self._build_queue.pop(0)
        done = self._build_steps_done.get(key, 0)
        total = self._build_steps_total.get(key, 0)
        placeholder = self._placeholders.get(key)
        if placeholder is not None:
            placeholder.set_progress(label, min(done + 1, total), total)
        try:
            fn()
        except Exception as exc:                # 某一步崩了不该把整页拖死
            self._build_failed.add(key)
            if placeholder is not None:
                placeholder.set_error(
                    self.fmt_text("build_step_failed", "{label}: this step failed — {err}",
                                  label=label, err=exc), key)
            self.show_message(
                self.fmt_text("build_failed", "Failed to build \"{title}\": {err}",
                              title=self.section_title(key), err=exc), "error")
        self._build_steps_done[key] = done + 1
        if done + 1 >= total:
            self._complete_section(key)
        if self._build_queue:
            self._schedule_pump()

    def _complete_section(self, key: str):
        """某一节建完了：收尾 + 把占位页换成真页面"""
        page = self._pages.get(key)
        if page is None:
            return
        if key in self._build_failed:
            return          # 半成品不往用户面前推，占位页上已经写着原因了
        finish = getattr(page, "finish_build", None)
        if callable(finish):
            try:
                finish()
            except Exception as exc:
                self._build_failed.add(key)
                placeholder = self._placeholders.get(key)
                if placeholder is not None:
                    placeholder.set_error(
                        self.fmt_text("finish_failed", "Error while finishing up: {err}", err=exc), key)
                self.show_message(
                    self.fmt_text("init_failed", "Failed to initialize \"{title}\": {err}",
                                  title=self.section_title(key), err=exc), "error")
                return
        self._built.add(key)
        placeholder = self._placeholders.pop(key, None)
        if placeholder is None:
            return
        if self.stack.currentWidget() is placeholder:
            self.stack.setCurrentWidget(page)
        self.stack.removeWidget(placeholder)
        placeholder.deleteLater()

    # ---------- 宽度 ----------
    def _apply_root_width(self):
        """给内容区限宽 + 居中（按 SECTION_MAX_WIDTH，窄窗口缩到可用宽度）

        限宽理由：最大化后输入框会拉到最右，眼睛得横跨整屏才能对上标签。
        """
        max_width = SECTION_MAX_WIDTH.get(self._current_key, DEFAULT_MAX_WIDTH)
        available = self.width() - SIZES["content_margin"] * 2
        width = max(360, min(max_width, available))
        if self.root.width() != width:
            self.root.setFixedWidth(width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_root_width()

    # ---------- 分节切换 ----------
    def show_section(self, key: str):
        """切到某一节（同步分段控件选中态）；没建好时先显示占位页"""
        if key not in SECTION_TITLES:
            return
        page = self._ensure_section(key)
        if page is None:
            return
        self._current_key = key
        self.stack.setCurrentWidget(page)
        if self.segmented.currentRouteKey() != key:
            self.segmented.setCurrentItem(key)
        self._apply_root_width()
        self.refresh_library_status()
        # 切过来以后让页面重算一次自己的"宽/窄"布局（表单页见 FormPage._sync_columns）
        sync = getattr(page, "_sync_columns", None)
        if callable(sync):
            QTimer.singleShot(0, sync)

    def show_page(self, page):
        """按页面对象切节（页面里 host.switchTo(page) 走这里）

        ⚠️ 未建的分节不在 _pages 里，按宿主属性比对，避免误建一个已建好的分节。
        """
        for key in SECTION_TITLES:
            if getattr(self.host, f"{key}_page", None) is page:
                self.show_section(key)
                return

    def current_section(self) -> str:
        return self._current_key

    # ---------- 页头状态 ----------
    def refresh_library_status(self):
        """刷新页头右侧的「资源库 N 条」（写盘后由宿主通知）

        只显示条数，完整路径放悬停提示 —— 路径太长，摆页头会被截断。
        """
        path = self.host.library_path()
        exists = os.path.exists(path)
        count = len(load_library(path).get("resources", []))
        self.library_status.setText(
            self.get_text("library_count").format(n=count) if exists
            else self.get_text("library_missing"))
        self.library_status.setToolTip(
            f"{path}\n{self.get_text('library_tooltip')}")

    # ---------- 主题 ----------
    def apply_theme(self, dark: bool = None):
        """主题切换：页头 + 分隔线 + 已经建出来的分节各刷一遍

        ⚠️ 先问 accent_color_applied 再调 apply_accent_color：后者会让
        qfluentwidgets 无条件 updateStyleSheet() 重渲染全程序控件样式（实测 800ms）；
        正常情况下启动时已灌过一次，这里必然跳过。整页样式表不在这里重套（见 setup_ui）。
        """
        if dark is None:
            dark = is_dark_mode()
        if not accent_color_applied(dark):
            apply_accent_color(bool(dark))
        c = theme_tokens(dark)
        self.divider.setStyleSheet(f"background-color: {c['card_border']};")
        style_hint(self.subtitle_label)
        style_hint(self.library_status)
        self.library_tip.apply_theme(dark)
        for page in self._pages.values():
            apply = getattr(page, "apply_theme", None)
            if callable(apply):
                try:
                    apply(dark)
                except Exception:
                    pass
        for placeholder in self._placeholders.values():
            style_hint(placeholder.step_label)
        self._apply_root_width()

    def refresh_theme(self):
        """主题变了（设置页切主题时会调这个，和 PluginInterface.refresh_theme 对齐）"""
        self.apply_theme()

    # ---------- 文案 / 提示 ----------
    def section_title(self, key: str) -> str:
        """分节名（当前语言）：分段控件按钮和占位页里的名字都用它"""
        text = self.get_text(f"section_{key}")
        if text and text != f"section_{key}":
            return text
        return SECTION_TITLES.get(key, key)

    def fmt_text(self, key: str, fallback: str, **kwargs) -> str:
        """取一条带占位符的文案并填值

        ⚠️ get_text 找不到键会原样返回键名，据此判断是否退回中文兜底，format 才不会炸。
        """
        text = self.get_text(key)
        if not text or text == key:
            text = fallback
        return text.format(**kwargs)

    def get_text(self, key):
        """文案：先查语言文件（maker 段），查不到用这里的中文兜底

        ⚠️ 段名必须是 maker：语言管理器没有登记 resource_maker 这个段。
        """
        if self.lang is not None:
            for module in ("maker", "resource_maker"):
                try:
                    text = self.lang.get_text(module, key)
                except Exception:
                    text = key
                if text and text != key:
                    return text
        defaults = {
            "title": "提交软件",
            "subtitle": "制作 / 浏览 / 合并 ToolsGCP 资源库里的条目；"
                        "改动写进 .ToolsGCP/ToolsGCP-Resources.json，写盘前自动备份。",
            "library_tip": "资源库固定是程序目录下的 .ToolsGCP/ToolsGCP-Resources.json，"
                           "制作器不会另外生成一份；\n"
                           "每次写盘前会自动备份到同级 backups/ 目录，只保留最近 20 份。",
            "section_form": "投稿表单",
            "section_browser": "资源浏览",
            "section_batch": "批量合成",
            "section_help": "使用说明",
            "tip_success": "成功",
            "tip_error": "错误",
            "tip_warning": "提示",
            "tip_info": "信息",
        }
        return defaults.get(key, key)

    def show_message(self, message, msg_type="info", parent=None):
        """提示条（和主程序其它页面一样用 InfoBar）"""
        kwargs = dict(orient=Qt.Horizontal, isClosable=True,
                      position=InfoBarPosition.TOP, duration=3000,
                      parent=parent or self)
        if msg_type == "success":
            InfoBar.success(title=self.get_text("tip_success"), content=message, **kwargs)
        elif msg_type == "error":
            InfoBar.error(title=self.get_text("tip_error"), content=message, **kwargs)
        elif msg_type == "warning":
            InfoBar.warning(title=self.get_text("tip_warning"), content=message, **kwargs)
        else:
            InfoBar.info(title=self.get_text("tip_info"), content=message, **kwargs)


__all__ = ["ResourceMakerInterface", "ResourceMakerHost", "SectionPlaceholder",
           "SECTIONS"]
