"""GCP-AI 界面：聊天抽屉 + 历史对话抽屉 + 侧边栏 AI 页。

⚠️ 所有网络动作必须经过 AIChatWorker（QThread），否则界面会卡死十几秒。会话存
core/ai/chat_store.py，问答走 core/ai/prompt.py + worker.py；文案走 language_manager
的 settings 模块（键名 ai_ 开头），缺失时用 texts.py 兜底。"""

from ..utils.fonts import ui_font
import copy
import os
import re
import webbrowser

from PyQt5.QtCore import (Qt, QEvent, QObject, QPropertyAnimation, QEasingCurve,
                          QPoint, QTimer, QSize, QThread, QUrl, pyqtSignal)
from PyQt5.QtGui import (QColor, QFont, QFontMetrics, QIcon, QPainter, QPixmap,
                         QSyntaxHighlighter, QTextCharFormat, QTextCursor)
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import (QApplication, QFrame, QGraphicsDropShadowEffect,
                             QHBoxLayout, QLabel, QLayout, QLineEdit,
                             QPlainTextEdit, QPushButton, QScrollArea,
                             QSizePolicy, QStackedLayout, QTextEdit,
                             QVBoxLayout, QWidget)

try:
    from qfluentwidgets import (isDarkTheme, IndeterminateProgressRing,
                                MessageBox, FluentIcon as FIF,
                                RoundMenu, Action as MenuAction)
except Exception:
    def isDarkTheme():
        return False

    IndeterminateProgressRing = None
    MessageBox = None
    FIF = None
    RoundMenu = None
    MenuAction = None

from ..core.ai.chat_store import ChatStore, ROLE_USER, ROLE_ASSISTANT
from ..core.ai import agent_tools
from ..core.ai import prompt as ai_prompt
from ..core.ai.worker import AIChatWorker
from ..core.resource_loader import ResourceLoader
from ..utils.logger import log
from ..utils.smooth_scroll import install_smooth_scroll, stop_smooth_scroll
from qfluentwidgets import SmoothScrollArea
from ..widgets.app_card import IconButton
from ..interfaces.settings.theme import brand_link_color

# AI 主色不留常量（用户可换配色档位）：用到的地方现取 brand_link_color()
# 危险操作色（历史对话卡片的删除按钮）
COLOR_DANGER = "#E5484D"


def _widget_at(global_pos, window=None):
    """屏幕坐标下面真正是哪个控件（拿不到就返回 None）

    ⚠️ 只用 QWidget.childAt()，不用 QApplication.widgetAt()：后者走系统 WindowFromPoint，窗口不在前台或被盖住时返回 None/别的窗口。"""
    if global_pos is None or window is None:
        return None
    try:
        local = window.mapFromGlobal(global_pos)
        if not window.rect().contains(local):
            return None
        return window.childAt(local)
    except Exception:
        return None


def _is_ai_mention_trigger(widget) -> bool:
    """这一下点的是不是搜索卡片上的「@给AI」按钮（或其子控件）

    ⚠️ 点它等于继续和 AI 对话，不能被"点外面就收起"的守卫当成外部点击（否则面板会闪一下）；标记 gcpAiMentionTrigger 由 app_card.py 打在按钮上。"""
    node = widget
    for _ in range(8):
        if node is None:
            return False
        try:
            if node.property("gcpAiMentionTrigger"):
                return True
        except Exception:
            return False
        try:
            node = node.parentWidget()
        except Exception:
            return False
    return False

# ---------- 尺寸 ----------
DRAWER_WIDTH = 420
SLIDE_DURATION_MS = 260
# 输入框 1~4 行的高度（和内部 padding 配套）
INPUT_MIN_H = 38
INPUT_MAX_H = 110
# 候选命令条目每条的上下内边距（px）。⚠️ 必须与 _style_command_popup /
# _highlight_command_item 里 QLabel 的 `padding: 5px 10px 7px` 一致，二者只能同改。
# 上小下大是故意的：Qt 画字的墨迹天然偏下，上下等值会显得字压在下边缘。
COMMAND_ITEM_PAD_TOP = 5
COMMAND_ITEM_PAD_BOTTOM = 7
# 一条文案占的总高度 = 字体行高 + 上下内边距
COMMAND_ITEM_PAD_V = COMMAND_ITEM_PAD_TOP + COMMAND_ITEM_PAD_BOTTOM
# 候选条目字号（px）⚠️ 同时是那两处 QSS 的值和量文字高度用的值，只能有这一个来源
COMMAND_ITEM_FONT_PX = 12
# 候选条目最小高度（兜底小字体时用）；真实高度按当前字体算
COMMAND_ITEM_MIN_H = 26
# 气泡按"每行 N 个字符"排版：13px 中文 30 字 ≈ 390px，抽屉宽 420
LINE_CHARS = 30
BUBBLE_CHAR_PX = 13.5
BUBBLE_PADDING_PX = 30          # 气泡左右 padding + 边框
# 内部自定义链接协议（避免和普通网址混淆）：
LINK_SETTINGS_API_KEY = "toolsgcp://api_key"   # 气泡里的 API Key 提示
LINK_RESOURCE_PREFIX = "toolsgcp://res/"       # toolsgcp://res/TG-000001 → 资源详情页
LINK_PLUGIN_PREFIX = "toolsgcp://plugin/"      # 切到插件中心、定位并闪烁对应卡片
# 输入框里 @ 提及的显示颜色（蓝色 + 下划线）
COLOR_MENTION = "#2F7BE0"

# ---------- @ 提及 ----------
# 输入框/气泡里 @ 提及的纯文本写法 `@名称(TG-000001)`；
# 编码必须带上：名称可能重复或被改口，编码才是资源库里唯一的。
MENTION_RE = re.compile(r"@([^()\n]{1,40}?)\(([A-Za-z]{1,6}-\d{1,8})\)")

# ---------- 气泡操作栏 ----------
# 按钮点击区尺寸（原来的 24×24 太小，不好点）
ACTION_BTN_SIZE = 28
ACTION_BTN_ICON = 14
# 气泡与其下操作栏的额外间距；正文那格已留了 BUBBLE_SHADOW_MARGIN 下边距，相加才是肉眼间距
BUBBLE_GAP = 2
# 消息与消息之间的间距
MESSAGE_SPACING = 16

# ---------- 气泡外观 ----------
# 主体圆角；朝向发送者的那个下角收窄成 6，形成"小尾巴"
BUBBLE_RADIUS = 16
BUBBLE_TAIL_RADIUS = 6
# 气泡正文内边距（⚠️ 必须和 apply_theme 里 QSS 的 padding 一致，高度测量用的就是它）
BUBBLE_PAD_V = 8
BUBBLE_PAD_H = 11
# 气泡投影的模糊半径与 Y 偏移
BUBBLE_SHADOW_BLUR = 20
BUBBLE_SHADOW_DY = 3
# ⚠️ 投影画在控件矩形之外，而 Qt 会把子控件裁到父矩形内，正文那格四周必须留这么多余量（高度也算进去）
BUBBLE_SHADOW_MARGIN = 8

# ---------- 复制按钮的"已复制"反馈 ----------
# 点复制后图标换成 ACCEPT、按钮变灰不可点，这么多毫秒之后回到 COPY
COPY_FEEDBACK_MS = 2000
# ⚠️ 下面几条文案故意写死中文、没走 _t()：要 i18n 需先补 set_language.json + texts.py 的键名
COPY_DONE_TIP = "已复制"
EDIT_ACCEPT_TIP = "保留并重新发送"
EDIT_CLOSE_TIP = "取消更改"

# 用户消息里存"每个编辑版本各自的后继消息"的字段名（见 _ensure_branches）
BRANCH_KEY = "branch_suffixes"

# 禁用按钮的文字色（复制成功后的灰字）
_DISABLED_ACTION_COLOR_DARK = "#5A5E6B"
_DISABLED_ACTION_COLOR_LIGHT = "#B4B7C0"

# ---------- Esc 路由 ----------
# 会用 Esc 的输入类控件：焦点在这些控件里（且在 AI 抽屉外）时，抽屉不抢 Esc
TEXT_INPUT_TYPES = (QLineEdit, QTextEdit, QPlainTextEdit)


def _widget_alive(obj) -> bool:
    """这个 Qt 控件还活着吗（C++ 侧没被 delete）

    ⚠️ 气泡是短命控件（重新渲染/切会话/翻版本都会 deleteLater），延时回调可能在它被析构后才跑到，直接访问会抛 RuntimeError: wrapped C/C++ object ... deleted。"""
    if obj is None:
        return False
    try:
        import sip
        return not sip.isdeleted(obj)
    except Exception:
        # 没有 sip 时退回"属性还读得出来就当它活着"
        try:
            obj.objectName()
            return True
        except Exception:
            return False


def _set_action_button(button, icon=None, tooltip: str = None,
                       enabled: bool = None):
    """统一改操作栏图标按钮的图标 / 提示 / 是否可点

    ⚠️ 图标必须走 IconButton.setThemedIcon()（会记住原始 FluentIcon 并在切主题时重新取色）；用 set_icon(icon.icon()) 会把颜色定死在调用那一刻。"""
    if not _widget_alive(button):
        return
    try:
        if icon is not None:
            try:
                button.setThemedIcon(icon)
            except Exception:
                # 极老的 qfluentwidgets 没有 setThemedIcon 时的兜底
                button.set_icon(icon)
        if tooltip:
            button.setToolTip(tooltip)
        if enabled is not None:
            button.setEnabled(bool(enabled))
    except RuntimeError:
        # 控件在调用过程中被销毁（析构和回调撞在一起），当没这回事
        pass


def _worker_running(worker) -> bool:
    """这个后台线程还在跑吗（已被 Qt 删掉的不算）

    ⚠️ 线程 finished 时连了 deleteLater，self.worker 过一会儿就指向 C++ 侧已销毁的对象，读 isRunning() 都会抛 RuntimeError；这类调用都在槽函数里，PyQt5 默认直接 abort 进程，所以先问 sip 再问 isRunning。"""
    if worker is None or not _widget_alive(worker):
        return False
    try:
        return bool(worker.isRunning())
    except RuntimeError:
        return False


def _release_worker(owner, attr: str = "worker"):
    """清掉 owner 上那个已跑完（或被销毁）的线程引用，免得下次再碰死对象（见 _worker_running）"""
    worker = getattr(owner, attr, None)
    if worker is not None and not _widget_alive(worker):
        try:
            setattr(owner, attr, None)
        except Exception:
            pass


# ---------- 两份 AI 面板之间的"当前对话"交接 ----------
# 同时存在两个 AIChatDrawer（悬浮球抽屉 + 左侧栏整页），是两棵独立的控件树。
# 设置里切换「改用侧边栏 AI 单独界面」时要把当前会话带过去：共享槽挂在**主窗口**上
# 而不是模块级全局，避免多窗口/测试里的假主窗口互相串味。
# 换会话写 publish_ai_session，面板显示时读 sync_shared_session。
_SHARED_SESSION_ATTR = "_ai_shared_session"


def _shared_slot(main_window):
    """主窗口上那个共享槽（第一次用到时建出来；拿不到主窗口就返回 None）"""
    if main_window is None:
        return None
    slot = getattr(main_window, _SHARED_SESSION_ATTR, None)
    if isinstance(slot, dict):
        return slot
    slot = {"session": None}
    try:
        setattr(main_window, _SHARED_SESSION_ATTR, slot)
    except Exception:
        return None
    return slot


def shared_ai_session(main_window):
    """当前"正在聊"的那个会话对象（还没人登记就 None）"""
    slot = _shared_slot(main_window)
    return slot.get("session") if slot else None


def publish_ai_session(main_window, session):
    """把会话登记成"当前正在聊的"（另一份 AI 界面显示时会接过去）"""
    slot = _shared_slot(main_window)
    if slot is None or session is None:
        return
    slot["session"] = session


def _popup_owns_escape() -> bool:
    """当前有没有"自己会用 Esc"的弹窗/弹出层盖在界面上

    ⚠️ 模态弹窗和右键菜单/下拉弹层都要让路，否则会出现"想关菜单，AI 面板先没了"。
    """
    app = QApplication.instance()
    if app is None:
        return False
    try:
        return (app.activeModalWidget() is not None
                or app.activePopupWidget() is not None)
    except Exception:
        return False


class _DrawerEscapeFilter(QObject):
    """抽屉专用的 Esc 事件过滤器（装在 QApplication 上，只在抽屉开着时存在）

    ⚠️ Esc 只发给有焦点的控件再沿父链冒泡，历史抽屉滑出时焦点在聊天输入框，于是"在历史页按 Esc"会把面板关掉；装在 QApplication 上才能看到所有按键。⚠️ 一个抽屉只建一个实例，装/摘只改"装没装"。"""

    def __init__(self, drawer):
        super().__init__(drawer)        # 父对象挂在抽屉上：抽屉销毁时它跟着一起走
        self._drawer = drawer

    def eventFilter(self, obj, event):
        if event.type() != QEvent.KeyPress or event.key() != Qt.Key_Escape:
            return False                    # 别的键一概不碰，免得影响输入
        drawer = self._drawer
        if drawer is None:
            return False
        try:
            return bool(drawer.handle_escape())
        except RuntimeError:
            # 抽屉的 C++ 对象已经销毁（关窗口的瞬间可能撞上），当没这回事
            return False


if MessageBox is not None:
    class _ConfirmMessageBox(MessageBox):
        """删对话用的确认框：绕开 qfluentwidgets 淡入/淡出两段动画的竞态

        ⚠️ showEvent 挂的 200ms 淡入会在结束时回调 setGraphicsEffect(None)，抹掉 done() 刚挂上的淡出效果、exec() 永不返回，所以弹出后立刻撤掉淡入效果。"""

        def showEvent(self, event):
            super().showEvent(event)
            self.setGraphicsEffect(None)
else:
    _ConfirmMessageBox = None


class BaseDrawer(QWidget):
    """右侧滑出抽屉的公共部分（滑动 / 贴窗口 / 上色 / Esc 收起）

    子类只搭内容（build_content），复用 sync_geometry() / open_drawer() / close_drawer() / toggle() / is_open()。"""

    def __init__(self, main_window, parent=None, embedded: bool = False):
        super().__init__(parent or main_window)
        self.main_window = main_window
        # ⚠️ embedded=True = 铺在页面里的侧边栏 AI 页；贴右边 / 滑进滑出 / 自藏这些行为
        #    都必须关掉，否则它会把自己 move 到窗口右侧，或一建出来就 hide() 导致页面永远空着。
        self._embedded = bool(embedded)
        self._dark = bool(isDarkTheme())
        self._open = False
        self._slide = None
        self._slide_overlay = None
        # 本抽屉自己的模态弹窗（删除确认框）开着 → Esc 和"点外面关闭"都要让路
        self._dialog_open = False
        # Esc 过滤器对象在这里建好，装/摘在 open_drawer / close_drawer 里做
        self._esc_filter = _DrawerEscapeFilter(self)
        self._esc_filter_installed = False

        self.setObjectName("aiDrawer")
        self._prepare_drawer_window()

    def _prepare_drawer_window(self):
        """抽屉形态的窗口属性（固定宽 420、背景透明、先藏起来；内嵌形态覆盖成空实现）"""
        self.setFixedWidth(DRAWER_WIDTH)
        self._make_background_transparent()
        self.hide()

    def _make_background_transparent(self):
        """让抽屉自己不画背景，整块面板交给里面的 container 去画

        ⚠️ 不透明的话 container 圆角切掉的区域会露出抽屉底色，深色主题下就是两块黑三角；样式表 transparent + WA_NoSystemBackground + WA_TranslucentBackground 三条缺一不可。"""
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("QWidget#aiDrawer { background: transparent; }")

    # ---------- 文案 ----------
    def _t(self, key: str) -> str:
        """取当前语言的文案（语言文件里没有就用设置页的兜底表，再没有就显示键名）"""
        lang = getattr(self.main_window, "language_manager", None)
        if lang is not None:
            try:
                text = lang.get_text("settings", key)
                if text and text != key:
                    return text
            except Exception:
                pass
        try:
            from ..interfaces.settings.texts import FALLBACK_TEXTS
            return FALLBACK_TEXTS.get(key, key)
        except Exception:
            return key

    # ---------- 几何 ----------
    def sync_geometry(self):
        """贴到主窗口内容区右侧（主窗口 resize/move 时都要调）

        高度从标题栏下方算起：FluentWindow 顶部那 48px 是标题栏，盖住会挡住窗口按钮。
        """
        if self._embedded:
            return                      # 内嵌在页面里，位置由布局决定
        if self.main_window is None:
            return
        top = 48
        try:
            top = max(48, self.main_window.titleBar.height())
        except Exception:
            pass
        height = max(200, self.main_window.height() - top)
        self.setFixedHeight(height)
        self.move(self.main_window.width() - DRAWER_WIDTH, top)

    def is_open(self) -> bool:
        if self._embedded:
            return True                 # 页面形态：永远"是打开状态"
        return self._open

    def toggle(self):
        if self._embedded:
            return
        if self._open:
            self.close_drawer()
        else:
            self.open_drawer()

    def open_drawer(self):
        """从右侧滑出（已在外面则什么都不做，交给子类决定要不要刷新内容）"""
        if self._embedded:
            return
        self.sync_geometry()
        if self._open:
            return
        self._open = True
        self.on_open()
        start_x = self.main_window.width()
        target_x = self.main_window.width() - DRAWER_WIDTH
        self.move(start_x, self.y())
        self.show()
        self.raise_()
        self._animate_x(start_x, target_x)
        # 滑出之后才装 Esc 过滤器：否则打开它的那一下点击/按键会被自己刚装的过滤器接住
        self._install_escape_filter()

    def close_drawer(self):
        """滑回右侧收起"""
        if self._embedded:
            return                      # 页面形态没有"收起"
        if not self._open:
            # 兜底：逻辑上已关、但覆盖层还留在屏幕上（动画被打断/重复调用）也要收掉
            self._hide_slide_overlay()
            return
        self._open = False
        # 关掉就摘：这是装在 QApplication 上的全局过滤器，留着会让 Esc 被"看不见的抽屉"吃掉
        self._remove_escape_filter()
        self.on_close()
        start_x = self.x()
        target_x = self.main_window.width()
        # reveal 参数保留只为兼容调用点：动画直接搬真控件，收尾由外面的 hide 负责
        self._animate_x(start_x, target_x, on_done=self.hide, reveal=False)

    def hideEvent(self, event):
        """隐藏时兜底摘掉 Esc 过滤器 + 收掉滑动快照（两件事都幂等）

        防的是"没走 close_drawer 就被隐藏"的路径（主窗口直接收面板、容器藏控件）。
        """
        self._remove_escape_filter()
        self._hide_slide_overlay()
        super().hideEvent(event)

    def _animate_x(self, start: int, end: int, on_done=None, reveal: bool = True):
        """滑入 / 滑出：动画直接搬真控件，不用任何额外的顶层窗口

        ⚠️ 别再改回"影子快照"（grab 出图用顶层 QLabel 演位移）：要么漏收尾回调、抽屉"打开了却不可见"，要么快照没收掉、在界面上留下静态残影。"""
        if self._slide is not None:
            try:
                self._slide.stop()
                # 目标可能是老版本的快照窗口，先解绑再销毁（不解绑会碰已回收对象）
                self._slide.setTargetObject(None)
            except Exception:
                pass
        # 老版本残留的快照窗口：彻底销毁，不留残影
        self._dispose_slide_overlay()

        anim = QPropertyAnimation(self, b"pos")
        anim.setDuration(SLIDE_DURATION_MS)
        anim.setStartValue(QPoint(start, self.y()))
        anim.setEndValue(QPoint(end, self.y()))
        anim.setEasingCurve(QEasingCurve.OutCubic)
        if on_done is not None:
            anim.finished.connect(on_done)
        anim.start()
        self._slide = anim

    # ---------- 老"影子快照"的清理（保留函数名，别处还在调） ----------
    def prewarm_slide(self):
        """空实现（兼容调用点）：动画直接搬真控件，没有首次 grab 卡顿这回事了"""
        return

    def _hide_slide_overlay(self):
        """把老版本可能存在的快照窗口藏起来（幂等）"""
        overlay = getattr(self, "_slide_overlay", None)
        if overlay is not None:
            try:
                overlay.hide()
            except RuntimeError:
                self._slide_overlay = None

    def _dispose_slide_overlay(self):
        """销毁快照窗口（老版本可能留下来的那一块残影）

        先 hide 再 deleteLater 并把引用清空，否则"只 hide 不删"在特殊时序下会被 Qt 又显示回来。"""
        overlay = getattr(self, "_slide_overlay", None)
        self._slide_overlay = None
        if overlay is None:
            return
        try:
            overlay.hide()
            overlay.setParent(None)
            overlay.deleteLater()
        except RuntimeError:
            pass

    # ---------- 子类钩子 ----------
    def on_open(self):
        """子类在这里刷新内容"""

    def on_close(self):
        """子类在这里做收尾（比如停掉请求）"""

    def keyPressEvent(self, event):
        """Esc 收起（历史页会覆盖成"返回聊天"）

        ⚠️ 这是兜底路径，只在焦点正好落在抽屉自己身上时才走到；正常的 Esc 由装在 QApplication 上的 _DrawerEscapeFilter 接住。"""
        if event.key() == Qt.Key_Escape and self.handle_escape():
            return
        super().keyPressEvent(event)

    # ---------- Esc 路由（历史页优先，聊天页其次） ----------
    def _install_escape_filter(self):
        """抽屉滑出时装上 Esc 过滤器（重复装不会叠加，见 _DrawerEscapeFilter）"""
        app = QApplication.instance()
        if app is None or self._esc_filter is None:
            return
        app.installEventFilter(self._esc_filter)
        self._esc_filter_installed = True

    def _remove_escape_filter(self):
        """摘掉 Esc 过滤器（没装就什么都不做）"""
        app = QApplication.instance()
        if app is None or self._esc_filter is None or not self._esc_filter_installed:
            return
        app.removeEventFilter(self._esc_filter)
        self._esc_filter_installed = False

    def _escape_stack(self) -> list:
        """当前这一摞 AI 抽屉，最上面那个排最前（聊天抽屉是底、历史抽屉盖在它上面）

        基类只知道"我自己"，"底下还有谁"由子类覆盖补全，这样不管两个过滤器谁先被调用，裁决结果都一样。"""
        return [self]

    def _on_escape(self):
        """"我是这一摞里最上面那个"时，Esc 该做什么（历史抽屉覆盖成"返回聊天"）"""
        self.close_drawer()

    def handle_escape(self) -> bool:
        """Esc 的统一裁决；返回 True = 这次 Esc 归 AI 面板，上层不用再管

        历史抽屉开着 → 只回聊天页；只有聊天抽屉 → 收起整个面板；都没开 → 放行。⚠️ 弹窗/菜单开着、或焦点在 AI 抽屉以外的输入类控件里时都要让路。"""
        opened = [drawer for drawer in self._escape_stack()
                  if drawer is not None and drawer.is_open()]
        if not opened:
            return False
        if _popup_owns_escape() or any(d._dialog_open for d in opened):
            return False
        if not self._focus_allows_escape(opened):
            return False
        # 最上面那个抽屉优先：历史页的 Esc 只回聊天页，不会连带把聊天抽屉关掉
        opened[0]._on_escape()
        return True

    @staticmethod
    def _focus_allows_escape(opened: list) -> bool:
        """焦点位置是否允许抽屉处理这次 Esc

        焦点在某个 AI 抽屉里、没有焦点、或焦点在普通控件上 → 允许；焦点在 AI 抽屉以外的输入框里（例如插件页的"备注"）→ 让给那个控件。"""
        focus = QApplication.focusWidget()
        if focus is None:
            return True
        for drawer in opened:
            try:
                if focus is drawer or drawer.isAncestorOf(focus):
                    return True
            except Exception:
                continue
        return not isinstance(focus, TEXT_INPUT_TYPES)

    # ---------- 主题 ----------
    def _theme_colors(self) -> dict:
        """当前主题下抽屉要用的一整套颜色

        ⚠️ 浅色那套是特意设计的（不是把深色反过来）：背景"白 → 淡蓝紫"竖向渐变 + 左侧品牌色描边，AI 气泡白底 + 淡蓝紫描边。"""
        if self._dark:
            return {
                "bg": "#242736",
                # 顶部微微偏亮的渐变，避免整块面板死板的一片深灰
                "bg_gradient": ("qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                                "stop:0 #2A2E42, stop:0.42 #242736, stop:1 #20232F)"),
                "border": "rgba(255,255,255,0.08)",
                "edge": "rgba(140,160,255,0.22)",      # 左侧那条品牌色描边
                "shadow": QColor(0, 0, 0, 120),
                "text": "#E8EAF0", "icon": "#C9CCD6",
                "input_bg": "rgba(255,255,255,0.06)",
                "input_border": "rgba(255,255,255,0.10)", "hover": "rgba(255,255,255,0.08)",
                "divider": "rgba(255,255,255,0.07)", "card": "rgba(255,255,255,0.05)",
                "card_hover": "rgba(255,255,255,0.10)", "muted": "#9BA0AD",
                "ai_bubble": "#2F3346", "ai_bubble_border": "rgba(255,255,255,0.07)",
                "ai_bubble_text": "#E8EAF0",
            }
        return {
            "bg": "#FFFFFF",
            "bg_gradient": ("qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                            "stop:0 #F3F6FE, stop:0.40 #F8FAFF, stop:1 #FFFFFF)"),
            "border": "rgba(0,0,0,0.08)",
            "edge": "rgba(91,141,239,0.38)",
            "shadow": QColor(70, 90, 140, 46),
            "text": "#1F2329", "icon": "#4B4F58",
            "input_bg": "#FFFFFF",
            "input_border": "rgba(91,141,239,0.22)", "hover": "rgba(91,141,239,0.08)",
            "divider": "rgba(0,0,0,0.07)", "card": "rgba(91,141,239,0.06)",
            "card_hover": "rgba(91,141,239,0.12)", "muted": "#8B8E99",
            "ai_bubble": "#FFFFFF", "ai_bubble_border": "rgba(91,141,239,0.20)",
            "ai_bubble_text": "#1F2329",
        }

    def apply_theme(self, dark: bool = None):
        """按当前深浅色给公共部件上色，再交给子类处理自己的部分"""
        if dark is None:
            dark = bool(isDarkTheme())
        self._dark = bool(dark)
        c = self._theme_colors()

        if self._embedded:
            # 内嵌形态是一整页：不要自己的背景 / 描边 / 圆角 / 投影，底色交给主窗口页面
            self.container.setStyleSheet("""
                QFrame#aiDrawerContainer { background: transparent; border: none; }
                QWidget#aiDrawerHeader, QWidget#aiDrawerInput { background: transparent; }
            """)
        else:
            self.container.setStyleSheet(f"""
                QFrame#aiDrawerContainer {{
                    background: {c['bg_gradient']};
                    /* 左侧一条品牌色描边：让面板和主窗口内容区分得开
                       （浅色主题下本来是"白对白"，完全糊在一起） */
                    border: none;
                    border-left: 1px solid {c['edge']};
                    border-top-left-radius: 14px;
                    border-bottom-left-radius: 14px;
                }}
                QWidget#aiDrawerHeader, QWidget#aiDrawerInput {{ background: transparent; }}
            """)
        self._apply_container_shadow(c)
        self.title_label.setStyleSheet(f"color: {c['text']}; background: transparent;")

        icon_button_style = f"""
            QPushButton {{
                background: transparent; border: none; border-radius: 8px;
                color: {c['icon']}; font-size: 17px; font-weight: bold;
            }}
            QPushButton:hover {{ background: {c['hover']}; }}
        """
        for button in self._icon_buttons():
            button.setStyleSheet(icon_button_style)
        self.apply_extra_theme(c)

    def _apply_container_shadow(self, colors: dict):
        """把 container 上的投影去掉，面板与页面的分界交给左侧 1px 品牌色描边

        ⚠️ QGraphicsDropShadowEffect 会把面板左侧和两个圆角外压暗一圈（"圆角黑边"）；要再加投影前先量一下色差。内嵌形态直接跳过。"""
        if self._embedded:
            return
        try:
            if self.container.graphicsEffect() is not None:
                self.container.setGraphicsEffect(None)
        except Exception:
            pass

    @staticmethod
    def _icon_buttons() -> list:
        return []

    def apply_extra_theme(self, colors: dict):
        """子类给"自己特有的部件"上色"""

    def _info(self, message: str):
        """短的界面提示"""
        try:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.info(title="GCP-AI", content=message, orient=Qt.Horizontal,
                         isClosable=True, position=InfoBarPosition.TOP,
                         duration=1800, parent=self.main_window)
        except Exception:
            log.info("AI", "info", message)


class LinkLabel(QLabel):
    """气泡正文用的 QLabel：单击左键就触发链接

    ⚠️ 不用 QLabel 自带的 linksAccessibleByMouse（单击落在链接上就发 linkActivated，拖选会误触）；先 hitTest 判断点击处是否有 anchor，且鼠标几乎没移动才发信号。普通左键 → 系统浏览器，Ctrl+左键 → 内置浏览器。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(False)
        self.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self._press_pos = None
        # 右键菜单接管者，由 ChatBubble 构造后挂上；签名 handler(label, global_pos)
        self._context_handler = None

    # ---------- 右键：只弹"复制 / 全选" ----------
    def contextMenuEvent(self, event):
        """右键气泡：交给抽屉弹圆角菜单（复制 / 全选）

        ⚠️ 不调 super()：QLabel 自带的右键菜单是系统样式（直角、可能还有 "Copy Link Location"），和整套 Fluent 观感不一致。"""
        handler = self._context_handler
        if callable(handler):
            try:
                handler(self, event.globalPos())
            except Exception:
                pass
            event.accept()
            return
        super().contextMenuEvent(event)

    # ---------- 命中判断 ----------
    def anchor_at(self, pos):
        """这个位置上的链接地址（没有链接返回空串）

        ⚠️ hitTest 返回的 format 在同一个 anchor 区间内是统一的，点到链接里任意一个字都能拿到 href。"""
        try:
            doc = self.document()
            hit = doc.documentLayout().hitTest(pos, Qt.FuzzyHit)
            if hit == -1:
                return ""
            cursor = QTextCursor(doc)
            cursor.setPosition(hit)
            cursor.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 1)
            return str(cursor.charFormat().anchorHref() or "")
        except Exception:
            return ""

    # ---------- 鼠标 ----------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._press_pos is not None:
            moved = (event.pos() - self._press_pos).manhattanLength()
            self._press_pos = None
            # 移动超过 4px 说明用户是在拖选文字，不当成"点链接"
            if moved <= 4 and self.rect().contains(event.pos()):
                url = self.anchor_at(event.pos())
                if url:
                    self.linkActivated.emit(url)
                    event.accept()
                    return
        super().mouseReleaseEvent(event)


def _mentions_to_html(text: str) -> str:
    """把消息里的 `@名称(TG-000001)` 换成蓝色下划线 + 可点的链接

    ⚠️ 必须在 ChatBubble._to_html 转义/软换行之前调用，否则括号已变成实体、MENTION_RE 匹配
    不上；且先按标签切开再替换，否则消息里本来就有的 `<a href=...>` 会被 sub 搅进去。"""
    raw = str(text or "")
    if "@" not in raw:
        return raw

    def _repl(match):
        name, code = match.group(1), match.group(2)
        return f'<a href="{LINK_RESOURCE_PREFIX}{code}">@{name}({code})</a>'

    parts = re.split(r"(<[^>]+>)", raw)
    for index, part in enumerate(parts):
        if part.startswith("<") and part.endswith(">"):
            continue
        parts[index] = MENTION_RE.sub(_repl, part)
    return "".join(parts)


class MentionTextEdit(QTextEdit):
    """输入框用的 QTextEdit：单击左键就能点开里面的 @ 提及

    ⚠️ QTextEdit 没有 anchorClicked 信号（那是 QTextBrowser 才有的），用 anchorAt(pos) 判断
    即可；且要保证 @ 提及框选时是一个整体，拖选碰到某条提及的一部分就扩到整条。"""

    anchorClicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_pos = None
        self._mention_select_guard = False

    # ---------- @ 提及整体选中 ----------
    def _mention_ranges(self):
        """当前文本里所有 @ 提及的 (起, 止)（止不含）"""
        try:
            text = self.toPlainText()
        except RuntimeError:
            return []
        return [(m.start(), m.end()) for m in MENTION_RE.finditer(text)]

    def _expand_selection_to_mention(self):
        """选区碰到提及的一部分 → 扩成整条提及（跨多条就一并扩到最外边界）"""
        if self._mention_select_guard:
            return
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        new_start, new_end = start, end
        changed = False
        for span_start, span_end in self._mention_ranges():
            if span_start < new_end and new_start < span_end:
                if span_start < new_start:
                    new_start = span_start
                    changed = True
                if span_end > new_end:
                    new_end = span_end
                    changed = True
        if not changed:
            return
        self._mention_select_guard = True
        try:
            cursor.setPosition(new_start)
            cursor.setPosition(new_end, QTextCursor.KeepAnchor)
            self.setTextCursor(cursor)
        finally:
            self._mention_select_guard = False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if event.buttons() & Qt.LeftButton:
            self._expand_selection_to_mention()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._press_pos is not None:
            moved = (event.pos() - self._press_pos).manhattanLength()
            self._press_pos = None
            # 拖选文字（移动超过 4px）不算点击，避免选字时误跳页面
            if moved <= 4:
                try:
                    url = str(self.anchorAt(event.pos()) or "")
                except Exception:
                    url = ""
                if url:
                    self.anchorClicked.emit(url)
                    event.accept()
                    return
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            self._expand_selection_to_mention()


def _panel_text(key: str, default: str = "") -> str:
    """AI 面板里"模块级"文案的三语言查询（拿不到语言管理器就返回 default）

    ⚠️ MessageActionsBar 这类独立小控件不继承 BaseDrawer，用不了它的 _t()，才另开这个。
    """
    try:
        from ..core.language_manager import get_current_manager
        manager = get_current_manager()
        if manager is not None:
            for module in ("settings", "plugin"):
                try:
                    text = manager.get_text(module, key)
                except Exception:
                    text = key
                if text and text != key:
                    return str(text)
    except Exception:
        pass
    return default


def _apply_app_scrollbar(area) -> bool:
    """把滚动区域换成 UI 库自带的平滑滚动（qfluentwidgets）

    ⚠️ 只能换控件类型成 SmoothScrollArea，不能用 setVerticalScrollBar（库的 SmoothScrollBar 不是 QScrollBar 子类，会抛 TypeError）；换了之后必须 stop_smooth_scroll() 卸掉项目自己那套。"""
    if area is None:
        return False
    try:
        stop_smooth_scroll(area)
    except Exception:
        pass
    try:
        return hasattr(area, "delegate")       # SmoothScrollArea 的标志
    except Exception:
        return False


class CommandHighlighter(QSyntaxHighlighter):
    """把输入框里被识别的正确指令染成主题蓝

    ⚠️ 只染开头那一段（正常聊天提到 "/plugin" 不该变色，染一大片会盖掉 @ 提及的锚点）；
    highlightBlock 里绝不能抛异常（Qt 在排版过程中调用），整段包 try。"""

    def __init__(self, document, owner):
        super().__init__(document)
        self._owner = owner

    def highlightBlock(self, text: str):
        try:
            text = str(text or "")
            if not text.startswith("/"):
                return
            word = text.split(" ", 1)[0].split("\t", 1)[0].split("\n", 1)[0]
            if not word:
                return
            if not self._owner._is_known_command(word):
                return
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(self._owner._command_color()))
            # 和 @ 提及一样加下划线：一眼能看出"这是一条能用的命令"
            self.setFormat(0, len(word), fmt)
        except Exception:
            pass


class MessageActionsBar(QWidget):
    """气泡下方那一条操作栏（用户消息靠右、AI 消息靠左，与气泡同一边）

    同一位置有两个及以上版本时中间长出翻页器：AI 消息 [复制] [重新生成] [‹ 2/3 ›]；用户消息 [‹ 2/3 ›] [编辑] [复制]。信号：copy_requested / edit_requested / sync_requested / page_changed(int)"""

    copy_requested = pyqtSignal()
    edit_requested = pyqtSignal()
    sync_requested = pyqtSignal()
    page_changed = pyqtSignal(int)

    def __init__(self, is_user: bool, colors: dict, parent=None):
        super().__init__(parent)
        self.is_user = is_user
        self._colors = colors
        self._busy = False
        self._page = 0
        self._page_count = 1
        # 忙碌态 = 按钮收起 + 底色透明，没有任何进度控件
        self._editing = False
        # "已复制"那 2 秒的计时器：父对象是本操作栏，跟着气泡一起销毁，
        # 不会留下指向死控件的回调
        self._copy_pending = False
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.setInterval(COPY_FEEDBACK_MS)
        self._copy_timer.timeout.connect(self._end_copy_feedback)

        row = QHBoxLayout(self)
        row.setContentsMargins(3, 1, 3, 1)
        row.setSpacing(3)
        # 靠左还是靠右：跟气泡同一边
        if is_user:
            row.addStretch(1)

        # ⚠️ 图标一律用 FluentIcon 矢量图标，别用 ✎/⟳/⧉ 这类字符：
        #    它们在 Windows 默认字体里经常缺字（实测画成方框）。
        # ⚠️ 按钮在 _make_button 里已 setParent 到本操作栏，没进布局的那个必须显式
        #    hide()，否则它带着"可见"状态停在 (0,0)，和第一个真按钮叠成一坨。
        self.edit_btn = self._make_button(
            FIF.EDIT, _panel_text("msg_edit", "重写这条消息"), self.edit_requested)
        self.copy_btn = self._make_button(
            FIF.COPY, _panel_text("msg_copy", "复制内容"), self.copy_requested)

        # ---- 翻页器（默认隐藏，2 页以上才出现）----
        self.pager = QWidget(self)
        pager_row = QHBoxLayout(self.pager)
        pager_row.setContentsMargins(0, 0, 0, 0)
        pager_row.setSpacing(0)

        self.prev_btn = self._make_button(FIF.PAGE_LEFT, _panel_text("msg_prev", "上一版"),
                                          None, width=24)
        self.prev_btn.clicked.connect(lambda: self.page_changed.emit(self._page - 1))
        pager_row.addWidget(self.prev_btn)

        self.page_label = QLabel("1/1")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setFixedWidth(40)
        self.page_label.setFont(ui_font(8))
        pager_row.addWidget(self.page_label)

        self.next_btn = self._make_button(FIF.PAGE_RIGHT, _panel_text("msg_next", "下一版"),
                                          None, width=24)
        self.next_btn.clicked.connect(lambda: self.page_changed.emit(self._page + 1))
        pager_row.addWidget(self.next_btn)

        self.pager.hide()

        self.sync_btn = self._make_button(
            FIF.SYNC, _panel_text("msg_regen", "重新生成这条回答"), self.sync_requested)

        # ⚠️ 翻页器的位置两边不同：AI 消息放最后，用户消息放 edit 左边
        #    AI：[复制] [重新生成] [‹ 1/2 ›]   用户：[‹ 1/2 ›] [编辑] [复制]
        #    编辑态下用户那排只剩 [✕ 取消更改] [✓ 保留并重新发送]（见 _restore_buttons）。
        if is_user:
            row.addWidget(self.pager)
            row.addWidget(self.edit_btn)
            row.addWidget(self.copy_btn)
            self.sync_btn.hide()
        else:
            row.addWidget(self.copy_btn)
            row.addWidget(self.sync_btn)
            row.addWidget(self.pager)
            self.edit_btn.hide()

        if is_user:
            row.addStretch(1)
        else:
            row.addStretch(1)

        self.apply_theme(colors)
    def _make_button(self, icon, tooltip: str, signal=None,
                     width: int = ACTION_BTN_SIZE):
        """一个统一的扁平小图标按钮（图标跟随主题换色，hover 时自画浅底）"""
        button = IconButton(None, tooltip, width, ACTION_BTN_ICON, self)
        button.setThemedIcon(icon)
        # ⚠️ 记下出厂长相（最初的图标 + 提示）：复制反馈 / 内联编辑都是临时换装，
        #    恢复时不能拿"当前图标"当依据，否则会把临时态当成常态记住
        button._normal_icon = icon
        button._normal_tip = tooltip
        if signal is not None:
            button.clicked.connect(signal.emit)
        return button

    def _normal_state(self, button) -> tuple:
        """按钮的出厂长相 (图标, 提示)"""
        return (getattr(button, "_normal_icon", FIF.COPY),
                getattr(button, "_normal_tip", "复制内容"))

    # ---------- 按钮状态机 ----------
    def _restore_buttons(self, editing: bool = False):
        """把这一排按钮放回应当的位置（不看"已复制"那 2 秒的临时态）

        编辑态只留 close + accept，复制按钮和翻页器一律藏起来；常态下用户气泡 = [翻页器] [edit] [copy]，AI 气泡 = [copy] [sync] [翻页器]。"""
        self._editing = bool(editing)
        if editing:
            # 编辑态：只留两个按钮
            self.edit_btn.setVisible(True)
            self.copy_btn.setVisible(True)
            self.sync_btn.setVisible(False)
            self.pager.setVisible(False)
            return
        self.edit_btn.setVisible(self.is_user)
        self.copy_btn.setVisible(True)
        self.sync_btn.setVisible(not self.is_user)
        # 翻页器要不要显示由 set_page 决定（>=2 版才显示）
        if self._page_count < 2:
            self.pager.setVisible(False)

    def reset_buttons(self, editing: bool = False):
        """把这一排按钮恢复成默认长相，顺便决定是否进入内联编辑态

        进编辑 / 取消 / 接受 / 复制结束四条路径都走这里。⚠️ 复制反馈没走完时不能覆写复制按钮，否则一次主题切换就会把"已复制"提前抹掉。"""
        self._editing = bool(editing)
        if editing:
            # 编辑态：edit → close（取消更改），copy → accept（保留并重新发送）
            _set_action_button(self.edit_btn, FIF.CLOSE, EDIT_CLOSE_TIP, True)
            _set_action_button(self.copy_btn, FIF.ACCEPT, EDIT_ACCEPT_TIP, True)
        else:
            icon, tip = self._normal_state(self.edit_btn)
            _set_action_button(self.edit_btn, icon, tip, True)
            if not self._copy_pending:
                icon, tip = self._normal_state(self.copy_btn)
                _set_action_button(self.copy_btn, icon, tip, True)
        if not self._busy:
            self._restore_buttons(editing)

    def set_copy_done(self):
        """复制按钮的"已复制"反馈态：图标换成 ✓、提示改成"已复制"、并且不可点

        ⚠️ 只动图标 / 提示 / 可用性，不碰 pyqtSignal（重新连接会攒出重复的槽）；禁用靠 IconButton 自己压暗（opacity 0.35）。"""
        if self._busy:
            return                      # 忙碌态期间按钮是藏起来的，别去动它
        self._copy_pending = True
        _set_action_button(self.copy_btn, FIF.ACCEPT, COPY_DONE_TIP, False)
        self._copy_timer.start()

    def _end_copy_feedback(self):
        """2 秒到：把复制按钮换回 COPY 图标并恢复可点

        ⚠️ 不用管编辑态：进编辑态时会先停掉倒计时，倒计时还活着就说明现在是常态。
        """
        self._copy_pending = False
        if not _widget_alive(self):
            return
        icon, tip = self._normal_state(self.copy_btn)
        _set_action_button(self.copy_btn, icon, tip, True)

    def set_editing(self, editing: bool):
        """气泡进出内联编辑态时换装

        进编辑态先收掉"已复制"的倒计时，否则它 2 秒后自己变回复制图标会把编辑态搅乱。
        """
        if editing:
            self._copy_timer.stop()
            self._copy_pending = False
        self.reset_buttons(editing)

    # ---------- 主题 ----------
    def apply_theme(self, colors: dict):
        """操作栏配色：给这组按钮一层很淡的圆角底，和气泡之间有分界

        图标颜色不归这里管（IconButton 在 StyleChange 时自己重取）。
        """
        self._colors = colors
        self.setStyleSheet(
            "MessageActionsBar {"
            f"  background: {colors.get('action_bg', 'transparent')};"
            "   border-radius: 9px;"
            "}")
        self.page_label.setStyleSheet(
            f"color: {colors['muted']}; background: transparent;")

    # ---------- 状态 ----------
    def set_page(self, page: int, count: int, emit: bool = False):
        """更新页码显示（count >= 2 才显示翻页器；首页禁用左箭头、末页禁用右箭头）"""
        count = max(1, int(count))
        page = max(0, min(int(page), count - 1))
        self._page = page
        self._page_count = count

        if count < 2:
            self.pager.hide()
            return
        self.pager.show()
        self.page_label.setText(f"{page + 1}/{count}")
        self.prev_btn.setEnabled(page > 0)
        self.next_btn.setEnabled(page < count - 1)

    def set_busy(self, busy: bool):
        """忙碌态：把这一排按钮和淡底一起收起来（不再有转圈的进度环）

        ⚠️ 恢复时不用忙碌前记下的可见性快照，而是按角色重算：内联编辑可能在忙碌期间开始或结束，快照会过期。"""
        if bool(busy) == self._busy:
            return
        self._busy = bool(busy)

        if self._busy:
            for widget in (self.edit_btn, self.copy_btn, self.sync_btn, self.pager):
                widget.hide()
            # 淡底也收掉，否则留一块空底色更像 UI 坏了
            self.setStyleSheet("MessageActionsBar { background: transparent; }")
        else:
            self._restore_buttons(self._editing)
            # 翻页器不归 _restore_buttons 管：它显不显示由页数决定（set_page 里）
            self.set_page(self._page, self._page_count)
            self.apply_theme(self._colors)

    def refresh_page(self):
        self.set_page(self._page, self._page_count)


class ChatBubble(QFrame):
    """一条消息气泡 + 它下面的操作栏

    用户消息靠右、品牌渐变底、白字；AI 消息靠左、跟随主题的气泡底 + 描边。内容支持极简富文本（加粗 / 换行 / 链接，见 _to_html）。"""

    # 气泡显示宽度兜底值（正常路径由容器按屏幕边距算好传进来，见 max_width 参数）
    MAX_WIDTH = int(LINE_CHARS * BUBBLE_CHAR_PX) + BUBBLE_PADDING_PX
    # 自适应宽度的下限 / 上限（上限防止超宽屏下一行太长、读起来累）
    MIN_BUBBLE_WIDTH = 220
    # 气泡本体（label 那层底色）的最小宽度；外层 QFrame 的下限是 MIN_BUBBLE_WIDTH
    MIN_CONTENT_WIDTH = 44
    MAX_ADAPTIVE_BUBBLE_WIDTH = 760

    def __init__(self, text: str, is_user: bool, dark: bool,
                 link_handler=None, actions: bool = True, parent=None,
                 max_width: int = None):
        super().__init__(parent)
        self._is_user = is_user
        self._link_handler = link_handler
        self._dark = dark
        self.actions = None
        # ⚠️ 气泡宽度由容器按"消息区视口宽度 − 两侧留白"传入（见 _apply_bubble_width）；
        #    没传就退回固定值 MAX_WIDTH。
        self._max_width = int(max_width or self.MAX_WIDTH)
        # 消息区一整行的宽度（由抽屉按视口传入）；靠右/靠左就是靠它撑满一行后由弹簧实现
        self._row_width = 0
        # 内联编辑（气泡原地变输入框）的状态
        self.inline_edit = None         # 当前那个 QTextEdit，没在编辑时是 None
        self._inline_original = ""      # 进编辑前的正文：取消时用它恢复
        # 编辑框最大宽度：抽屉在布局稳定后按消息区视口把它夹小（见 _sync_inline_geometry）
        self._inline_max_width = int(self._max_width)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        if is_user:
            outer.addStretch(1)

        # 竖着排：气泡在上面，操作栏在下面（跟气泡同一边对齐）
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        # ⚠️ 整列一起靠左/靠右：不要用 addWidget 的 AlignLeft/AlignRight，那是单元格内
        #    对齐，配合被拉高的一格会把控件垂直居中（操作栏会飘到气泡中间那一行）。
        column.setAlignment(Qt.AlignLeft if not is_user else Qt.AlignRight)
        # ⚠️ AI 这边必须去掉对齐：QVBoxLayout 一旦设了对齐，子项就按 sizeHint 摆放，
        #    而 wordWrap 的 QLabel 的 sizeHint 是"不折行宽度"，气泡会只剩百来像素宽。
        if not is_user:
            column.setAlignment(Qt.Alignment())

        # ⚠️ 正文和内联编辑框占同一格（QStackedLayout），这样"气泡变输入框"是原地换脸，
        #    位置 / 宽度 / 圆角都与原气泡对齐。
        # ⚠️ 必须用 StackAll + 自己切 visible：StackOne 的高度取所有孩子里最高的那个，
        #    编辑框缩到 38px 时旧正文还在背后撑着，气泡会被拉出大空档、按钮飘到很远。
        self._text_stack_host = QWidget(self)
        self._text_stack = QStackedLayout(self._text_stack_host)
        # 四周留出投影要用的余量（见 BUBBLE_SHADOW_MARGIN）。
        # ⚠️ 别用 setContentsMargins 去清 label 的边距：那是 QSS 的 padding，
        #    清掉气泡会矮一截（见 _text_block_height）。
        self._text_stack.setContentsMargins(BUBBLE_SHADOW_MARGIN, BUBBLE_SHADOW_MARGIN,
                                            BUBBLE_SHADOW_MARGIN, BUBBLE_SHADOW_MARGIN)
        self._text_stack.setStackingMode(QStackedLayout.StackAll)

        self.label = LinkLabel(self._text_stack_host)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.RichText)
        self.label.linkActivated.connect(self._on_link)
        self.label.setFont(ui_font(10))
        self.label.setToolTip(_panel_text(
            "link_tip_open",
            "单击链接用浏览器打开；按住 Ctrl 单击在程序内打开"))
        self.set_text(text)
        # ⚠️ 纵向必须 Fixed：默认的 Preferred 会让消息布局把多余高度平摊给每条气泡，
        #    实测一条 sizeHint=58 的气泡被拉成 220，正文只占 39（"聊天气泡空行"根因之一）。
        #    横向留 Preferred：宽度由 _apply_bubble_width() 按内容定。
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        # ⚠️ 只给 label 设宽度上限，不设固定宽度：定死宽度会和外层布局互相触发，
        #    实测把启动卡死（见 _apply_bubble_width）。
        self.label.setMaximumWidth(self._max_width)
        self.label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self._text_stack.addWidget(self.label)
        # StackAll 下两个孩子会叠在同一格，初始要把正文设为当前（编辑框建好后再切）
        self._text_stack.setCurrentWidget(self.label)
        # ⚠️ 这一格的横向策略 / 对齐两种气泡相反：
        #   · AI 气泡：必须 Expanding 且不加对齐参数（加了就按 sizeHint 摆，见上）；
        #   · 用户气泡：这一格宽度在 _sync_host_width() 里按内容钉死，必须 AlignRight
        #     才能贴到行右边界 —— 外层那列宽度取 max(正文, 操作栏)，带翻页器的操作栏
        #     比短消息宽得多，不对齐短消息会被按在列左边缘（实测差 84px）。
        #     QStackedLayout 自己的 setAlignment 不认这种按子项对齐，只能落在这一格上。
        #     纵向都是 Minimum：高度由 _refresh_text_host 定死，别让布局拉。
        self._text_stack_host.setSizePolicy(
            QSizePolicy.Expanding if not is_user else QSizePolicy.Fixed,
            QSizePolicy.Minimum)
        if is_user:
            column.addWidget(self._text_stack_host, 0, Qt.AlignTop | Qt.AlignRight)
        else:
            column.addWidget(self._text_stack_host, 0)

        if actions:
            # 气泡和操作栏之间留一点空
            column.addSpacing(BUBBLE_GAP)
            self.actions = MessageActionsBar(is_user, {"muted": "#8B8E99",
                                                        "text": "#1F2329",
                                                        "hover": "rgba(0,0,0,0.05)",
                                                        "divider": "rgba(0,0,0,0.07)"},
                                             self)
            # ⚠️ 横向也要给对齐：只写 AlignTop 会让这一格铺满整列，
            #    那层淡底就变成气泡下面一整条横带（按钮只挤在一头）。
            column.addWidget(self.actions, 0,
                             Qt.AlignTop | (Qt.AlignRight if is_user else Qt.AlignLeft))

        # ⚠️ AI 气泡必须给这一列拉伸因子，否则"列"和尾部 stretch 都按 sizeHint 分宽度，
        #    列只剩 label 那不折行的 sizeHint，气泡只有百来像素宽（实测 193，加了才到 760）。
        # ⚠️ 用户气泡反过来不能给：短句会被撑成一整行宽，靠外层 addStretch 推到右边即可。
        if is_user:
            outer.addLayout(column)
        else:
            outer.addLayout(column, 1)
            outer.addStretch(0)
        # 气泡本体宽度推迟到布局稳定后再收紧（见 apply_max_width）：在 __init__ 里按内容算
        # 会和外层布局互相触发，实测会把启动卡死。
        self._in_bubble_width = False

        self.apply_theme(dark)

    def _bubble_skin(self) -> dict:
        """这条气泡的"皮"：底色 / 文字色 / 描边

        抽出来是为了让内联编辑框穿同一份皮（见 _style_inline_editor），否则换脸瞬间颜色和圆角会跳一下。"""
        if self._is_user:
            from ..interfaces.settings.theme import brand_gradient_qss
            return {
                "background": brand_gradient_qss(),
                "color": "#FFFFFF",
                "border": "none",
            }
        c = self._theme_colors(self._dark)
        return {"background": c["ai_bubble"],
                "color": c["ai_bubble_text"],
                "border": f"1px solid {c['ai_bubble_border']}"}

    def _radius_css(self) -> str:
        """圆角声明：主体圆角 + 朝向发送者的那个下角收窄（"小尾巴"）

        ⚠️ border-radius 是四个角一起设，单独改一个角必须写在它后面，顺序反了会被覆盖。
        """
        corner = "right" if self._is_user else "left"
        return (f"border-radius: {BUBBLE_RADIUS}px;"
                f"border-bottom-{corner}-radius: {BUBBLE_TAIL_RADIUS}px;")

    def _apply_shadow(self):
        """给气泡本体加一层极淡的投影

        ⚠️ 只加在正文这一层（整条 QFrame 一起投的话按钮下面会出现一圈灰边）；重复 apply_theme 时复用已有的 effect，别反复新建。"""
        target = self.label
        try:
            effect = target.graphicsEffect()
            if effect is None:
                effect = QGraphicsDropShadowEffect(target)
                target.setGraphicsEffect(effect)
            # 深色主题给重一点、浅色给轻一点（深底上太淡看不见，浅底上太重像脏边）
            color = QColor(0, 0, 0, 110 if self._dark else 38)
            effect.setColor(color)
            effect.setBlurRadius(BUBBLE_SHADOW_BLUR)
            effect.setOffset(0, BUBBLE_SHADOW_DY)
        except Exception:
            pass

    def apply_theme(self, dark: bool):
        self._dark = dark
        skin = self._bubble_skin()
        # ⚠️ 内联编辑框的样式也要重刷（主题切换时它可能正开着）
        if self.inline_edit is not None and _widget_alive(self.inline_edit):
            self._style_inline_editor()
        self.label.setStyleSheet(f"""
            QLabel {{
                background: {skin['background']};
                color: {skin['color']};
                border: {skin['border']};
                {self._radius_css()}
                padding: {BUBBLE_PAD_V}px {BUBBLE_PAD_H}px;
                font-size: 13px;
                line-height: 150%;
            }}
            QLabel a {{ color: {brand_link_color()}; text-decoration: underline; }}
        """)
        self._apply_shadow()
        # ⚠️ 换完皮（内边距/行高可能变了）必须重算一次高度，否则气泡按旧内边距的高度
        #    停着、正文被裁一截（这是"切主题之后气泡坏了"的根因）。
        QTimer.singleShot(0, self._refresh_text_host)
        if self.actions is not None:
            self.actions.apply_theme({
                "muted": "#9BA0AD" if dark else "#8B8E99",
                "text": "#E8EAF0" if dark else "#1F2329",
                "hover": "rgba(255,255,255,0.08)" if dark else "rgba(0,0,0,0.05)",
                "divider": "rgba(255,255,255,0.10)" if dark else "rgba(0,0,0,0.07)",
                # 操作栏自己的淡底（很淡）：气泡已有投影，底色重了会像两个叠着的控件
                "action_bg": "rgba(255,255,255,0.035)" if dark
                             else "rgba(15,23,42,0.03)",
            })

    # ---------- 内联编辑：气泡原地变输入框 ----------
    def _style_inline_editor(self):
        """给内联编辑框刷上和气泡同款的样式（没有编辑框时什么都不做）

        ⚠️ background 与 background-color 分开写（底色可能是渐变，QTextEdit 的 background
        简写在带 padding / 圆角时不稳）；内边距比正文 label 各小 2px（自带边框和光标位置）。"""
        editor = self.inline_edit
        if editor is None or not _widget_alive(editor):
            return
        skin = self._bubble_skin()
        focus_border = (f"1px solid {brand_link_color()}" if self._is_user
                        else f"1px solid {brand_link_color()}")
        editor.setStyleSheet(f"""
            QTextEdit {{
                background: none;
                background-color: {skin['background']};
                color: {skin['color']};
                border: {skin['border']};
                {self._radius_css()}
                padding: {max(1, BUBBLE_PAD_V - 2)}px {max(1, BUBBLE_PAD_H - 2)}px;
                font-size: 13px;
                selection-background-color: rgba(91,141,239,0.45);
            }}
            QTextEdit:focus {{ border: {focus_border}; }}
            QScrollBar:vertical {{ background: transparent; width: 5px; }}
            QScrollBar::handle:vertical {{
                background: rgba(128,128,128,0.35); border-radius: 2px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

    def inline_text(self) -> str:
        """内联编辑框里的纯文本（没在编辑时返回正文）"""
        editor = self.inline_edit
        if editor is None or not _widget_alive(editor):
            return self._text
        try:
            return editor.toPlainText()
        except RuntimeError:
            return self._text

    def is_editing(self) -> bool:
        """这条气泡现在是不是"正文被换成了输入框"

        ⚠️ 判据必须是"当前显示的是不是编辑框"，不能写 self.inline_edit is not None：编辑框建好之后会留着复用（懒加载），一直不是 None。"""
        editor = self.inline_edit
        if editor is None or not _widget_alive(editor):
            return False
        try:
            return self._text_stack.currentWidget() is editor
        except RuntimeError:
            return False

    def begin_inline_edit(self) -> bool:
        """把这条气泡变成输入框（原地、同宽、同位置）；返回 True = 真进了编辑态

        正文 label 和编辑框放同一个 QStackedLayout 里切页签，宽度、对齐、圆角、间距沿用气泡
        原来那一套；⚠️ 编辑框懒加载（每条消息一个会白占内存），反复编辑复用同一个。"""
        if not self._is_user or self.actions is None:
            return False                # 只有用户自己的消息能重写
        if self.inline_edit is None:
            self.inline_edit = QTextEdit(self._text_stack_host)
            self.inline_edit.setAcceptRichText(False)
            self.inline_edit.setLineWrapMode(QTextEdit.WidgetWidth)
            self.inline_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.inline_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.inline_edit.setFont(ui_font(10))
            # 文档自带 margin 会和样式表 padding 叠加，1 行高度就算不准（同主输入框）
            self.inline_edit.document().setDocumentMargin(0)
            # 宽度在 _sync_inline_geometry 里定死（编辑时只有高度随行数走，才像一条气泡）；
            # 高度要等排版完再算，textChanged 时 Qt 还没排完
            self.inline_edit.document().documentLayout().documentSizeChanged.connect(
                lambda _size, b=self: b._adjust_inline_height())
            self._text_stack.addWidget(self.inline_edit)

        self._inline_original = self._text
        # ⚠️ 放纯文本而不是 HTML：用户要改的是消息本身，塞 <a href> 进去只会看到一堆标签
        try:
            self.inline_edit.setPlainText(self._text)
            self.inline_edit.moveCursor(QTextCursor.End)
        except RuntimeError:
            self.inline_edit = None
            return False
        # ⚠️ 这里同步拿到的父容器宽度还是上一轮的旧值，真正的宽度由抽屉在布局稳定之后
        #    按视口夹一次（见 AIChatDrawer._fit_inline_editor）
        self._sync_inline_geometry()
        self._adjust_inline_height()
        self._style_inline_editor()
        self._show_inline_editor(True)
        self.actions.set_editing(True)
        try:
            self.inline_edit.setFocus()
        except RuntimeError:
            pass
        return True

    def _show_inline_editor(self, editing: bool):
        """在两个替身之间切页签（StackAll 模式下必须自己管可见性）"""
        editor, label = self.inline_edit, self.label
        try:
            if editing and editor is not None and _widget_alive(editor):
                self._text_stack.setCurrentWidget(editor)
                label.hide()
                editor.show()
            else:
                self._text_stack.setCurrentWidget(label)
                if editor is not None and _widget_alive(editor):
                    editor.hide()
                label.show()
        except RuntimeError:
            pass
        # 换完替身这一格的高度会变，让布局重新算一遍。
        # ⚠️ 退出编辑时宽度要收回正文宽度，否则气泡会停在"编辑框那么宽"的样子；
        #    进编辑时不在这里动宽度（由 _sync_inline_geometry 定，且在本函数之前调用）。
        if not editing:
            self._sync_host_width()
        QTimer.singleShot(0, self._refresh_text_host)

    def _text_block_height(self, width: int) -> int:
        """正文在 width 宽度下真实需要的高度（含 QSS 内边距，单位像素）

        ⚠️ 绝不能对 label 调 setContentsMargins：QSS 的 padding 正是通过内容边距参与
        heightForWidth()，清零会让气泡矮约 30px、正文被裁并和操作栏叠在一起。"""
        label = self.label
        width = max(1, int(width))
        best = 0
        try:
            best = int(label.heightForWidth(width))
        except Exception:
            best = 0
        # ⚠️ 再和 sizeHint 取一次较大值：sizeHint 更大时多出来的行会画到这一格外面，
        #    被紧跟着的操作栏盖住（"后面字体全部被挡住"）。
        # ⚠️ 但不能无脑取大值：宽度还没定下来时 sizeHint 会按整行算高度、底下多一片空白，
        #    所以只在两者接近（说明量的是同一个宽度）时才让 sizeHint 说话。
        if best > 0:
            try:
                hint = int(label.sizeHint().height())
                if hint > best and hint - best <= max(8, best // 2):
                    best = hint
            except Exception:
                pass
        if best <= 0:
            try:
                best = int(label.sizeHint().height())
            except Exception:
                best = 0
        # 加上给投影留的上下余量
        return max(1, best) + 2 * BUBBLE_SHADOW_MARGIN

    def _refresh_text_host(self):
        """按当前显示的那个替身把这一格的高度定死

        ⚠️ 不做的话高度只增不减（QStackedLayout 的高度缓存），气泡下面就多一块空白；也不能对 label 调 setContentsMargins（见 _text_block_height）。"""
        editor, label = self.inline_edit, self.label
        try:
            if editor is not None and _widget_alive(editor) \
                    and self._text_stack.currentWidget() is editor:
                height = editor.height()
            else:
                # 按实际画出来的宽度算行数：自适应后 label 可能只占 556（上限 760），
                # 按上限算高度会偏高、气泡上方多出一片空白
                measure = label.width()
                if measure <= 0:
                    measure = self._max_width
                # ⚠️ label 还没被布局过时 width() 是默认值 100，会把长内容算成一行而不换行；
                #    这种情况直接按上限量（宁可高度略多，也不能不换行）。
                if measure < min(160, self._max_width):
                    measure = self._max_width
                height = self._text_block_height(
                    max(1, min(self._max_width, measure)))
            host = self._text_stack_host
            if host.height() != height:
                host.setFixedHeight(height)
            # ⚠️ 定死高度之后必须把这一格里所有东西都贴顶：QStackedLayout 默认把格子
            #    垂直居中，多出来的空隙上下平分，就是"聊天气泡空行"。边距不要碰（QSS padding）。
            # ⚠️ 横向的"用户气泡靠右"不归这里管（QStackedLayout 不认 setAlignment），
            #    靠的是这一格自己收成内容宽 + 列上给它 AlignRight（见 _sync_host_width）。
            try:
                self._text_stack.setAlignment(label, Qt.AlignTop | Qt.AlignLeft)
                if editor is not None and _widget_alive(editor):
                    self._text_stack.setAlignment(editor, Qt.AlignTop | Qt.AlignLeft)
            except Exception:
                pass
        except RuntimeError:
            pass

    def exit_inline_edit(self):
        """退出编辑态：把气泡换回原来的样子（取消 / 接受都走这里）

        ⚠️ 只负责界面（正文恢复成 _inline_original、按钮换回 edit/copy），会话和磁盘一个字都不碰，那是抽屉那边的事。"""
        if self.inline_edit is not None and _widget_alive(self.inline_edit):
            self._show_inline_editor(False)
        if self.actions is not None:
            # 复制倒计时也要清掉，否则它会在气泡回到常态后再改一次按钮（把 accept 换回 copy）
            self.actions.set_editing(False)
        self._inline_original = ""

    def _sync_inline_geometry(self, available_width: int = None):
        """把编辑框的宽度定下来（默认用气泡允许的最大宽度）

        ⚠️ 不能用 label.width()（wordWrap 的宽度跟着文字收缩，短消息只有二三十像素、会得到
        又窄又高的细条）；也不能只认 MAX_WIDTH（会把气泡顶出可视区）。"""
        if self.inline_edit is None or not _widget_alive(self.inline_edit):
            return
        try:
            if available_width is not None and int(available_width) > 80:
                # 记下来：resizeEvent 要按同一个上限重算，否则会退回旧上限、把编辑框顶出可视区
                self._inline_max_width = int(available_width)
            width = min(int(self._max_width), int(self._inline_max_width))
            self.inline_edit.setFixedWidth(width)
            # ⚠️ 正文那一格要跟着编辑框一起变宽（只对用户气泡），否则右对齐的编辑框
            #    会从停在正文宽度的那一格里溢出去（见 _sync_host_width）。
            self._sync_host_width(width)
        except RuntimeError:
            pass

    # ---------- 宽度自适应（按屏幕边距） ----------
    @staticmethod
    def adaptive_max_width(viewport_width: int, side_padding: int = 28,
                           cap: int = None) -> int:
        """按可用宽度算气泡的宽度上限 = 视口宽度 − 两侧留白（气泡 + 滚动条）

        窄到一定程度给一个下限、宽到一定程度给一个上限（超宽屏一行太长反而难读）。
        """
        cap = int(cap or ChatBubble.MAX_ADAPTIVE_BUBBLE_WIDTH)
        width = int(viewport_width) - 2 * int(side_padding)
        return max(ChatBubble.MIN_BUBBLE_WIDTH, min(cap, width))

    def apply_max_width(self, width: int, row_width: int = None):
        """容器算出新的可用宽度后调这里：更新上限并让正文重新折行

        row_width = 消息区一整行的宽度。⚠️ 气泡控件自己是那一行的整格（内部靠弹簧顶到该在的一边），只设内容宽度的话用户消息会贴在左边、看着像 AI 发的。"""
        width = int(width)
        if row_width:
            self._row_width = int(row_width)
        if width > 0 and width != self._max_width:
            self._max_width = width
            self._inline_max_width = width
            try:
                if self.inline_edit is not None and _widget_alive(self.inline_edit):
                    self.inline_edit.setMaximumWidth(width)
            except RuntimeError:
                pass
        self._sync_row_width()
        # ⚠️ 改完上限必须重算一次内容宽度：上面的 setMaximumWidth 会放开 label 的
        #    固定宽度上限，StackAll 又会把 label 拉满整格，短句也画成一条 760 宽的空气泡
        self._apply_bubble_width()
        # 宽度变了行数就变，重新量一次高度
        QTimer.singleShot(0, self._refresh_text_host)

    def _sync_row_width(self):
        """把气泡控件本身撑满消息区那一整行（内部弹簧负责靠左/靠右）

        ⚠️ 不能改回 setFixedWidth(内容宽 + 6)：那样用户消息整格都待在消息区左边，只有格内一小段是右对齐的，位置全错。"""
        if self._in_bubble_width:
            return
        width = int(self._row_width or 0)
        if width <= 0:
            return
        self._in_bubble_width = True
        try:
            self.setMaximumWidth(16777215)          # 清掉历史遗留的 fixed 上限
            if self.minimumWidth() != width:
                self.setMinimumWidth(width)
        except RuntimeError:
            pass
        finally:
            self._in_bubble_width = False

    # 气泡本体相对正文的额外宽度（外布局左右 padding + 描边）
    BUBBLE_EXTRA_WIDTH = 6

    def _natural_text_width(self) -> int:
        """正文"不折行时需要多宽"（像素）—— 按内容量气泡宽度的依据

        ⚠️ 用 QFontMetrics 量纯文本，不要用 QTextDocument.idealWidth()（字体未生效时偏大）；必须逐行量取最宽的一行，否则量出来的是各行宽度之和、气泡被顶到上限。"""
        from PyQt5.QtGui import QFontMetrics
        text = str(self._text or "").strip()
        if not text:
            return self.MIN_BUBBLE_WIDTH
        try:
            fm = QFontMetrics(self.label.font())
            widest = 0
            for line in _plain_lines(text):
                widest = max(widest, self._line_advance(fm, line))
            if widest <= 0:
                widest = self._line_advance(fm, _plain_text(text))
            # 末尾留余量（见 TEXT_SLACK）：正好等于最宽行时，四舍五入会让它再折一次；
            # 且 QLabel 内部的 QTextDocument 自己还有一点边距
            return int(widest) + self.TEXT_SIDE_PADDING + self.TEXT_SLACK
        except Exception:
            return int(self._max_width)

    # 量一行文字宽度时的余量（像素）；8 太小，短句会被文档边距挤到第二行
    TEXT_SLACK = 16

    @staticmethod
    def _line_advance(fm, line: str) -> int:
        """一行文字的推进宽度（取两种量法的较大值，宁宽不窄）

        ⚠️ boundingRect() 量的是墨迹范围（不含右侧留白），比排版用的推进宽度小，只按它算会把最后几个字挤到下一行。"""
        best = int(fm.boundingRect(line).width())
        try:
            best = max(best, int(fm.horizontalAdvance(line)))
        except Exception:
            pass
        return best

    def _apply_bubble_width(self, text_width: int = None):
        """按内容把气泡本体的宽度收紧到"刚好放得下"（不超过上限）

        ⚠️ 气泡的皮画在 label 上，决定观感宽度的是 label 宽度：右对齐的用户气泡那列会让 label 退化成 sizeHint（wordWrap 下只有 ~120px）；label 定内容宽度，QFrame 定"至少放得下操作栏"的宽度。"""
        if text_width is None:
            text_width = self._natural_text_width()
        # 气泡本体的宽度：短句贴身，长句到上限折行
        content = max(self.MIN_CONTENT_WIDTH,
                      min(int(self._max_width), int(text_width)))
        # QFrame 是那一整格：宽度取行宽（内部弹簧把气泡顶到该在的一边）；
        # 构造阶段还没拿到行宽，退回"内容宽 + 余量"
        row = int(self._row_width or 0) or (content + self.BUBBLE_EXTRA_WIDTH)
        total = max(self.MIN_BUBBLE_WIDTH, row)
        if self.width() == total and self.label.width() == content:
            # ⚠️ 宽度没变也要把"正文那一格"的宽度对一次（用户气泡靠右全靠它，
            #    见 _sync_host_width），它可能还停在编辑态留下的旧宽度。
            self._sync_host_width(content)
            return
        # 重入守卫：setFixedWidth 会立刻触发一次 resize，防御性挡一层
        if getattr(self, "_in_bubble_width", False):
            return
        self._in_bubble_width = True
        try:
            if self.label.width() != content:
                self.label.setFixedWidth(content)
            self._sync_host_width(content)
            self.setMaximumWidth(16777215)
            if self.minimumWidth() != total:
                self.setMinimumWidth(total)
        finally:
            self._in_bubble_width = False
        QTimer.singleShot(0, self._refresh_text_host)

    def _sync_host_width(self, width: int = None):
        """把正文那一格的宽度定死成内容宽（只对用户气泡）

        ⚠️ 外层那列宽度取 max(正文, 操作栏)（带翻页器时比短消息宽），这一格铺满的话短消息会被按在列左边缘，所以自己收成内容宽、再由列上的 AlignRight 顶到右边；编辑态传的是编辑框宽度。"""
        if not self._is_user:
            return
        if width is None:
            # 没给就用正文当前宽度（label 已被 setFixedWidth 钉过，准）
            try:
                width = int(self.label.width())
            except RuntimeError:
                return
        width = max(int(self.MIN_CONTENT_WIDTH), int(width or 0))
        host = getattr(self, "_text_stack_host", None)
        if host is None:
            return
        try:
            if host.minimumWidth() != width or host.maximumWidth() != width:
                host.setFixedWidth(width)
        except RuntimeError:
            pass

    def refresh_size(self):
        """正文内容变了之后重算一次尺寸（流式输出结束时、编辑接受后调）"""
        try:
            self._apply_bubble_width()
            self._refresh_text_host()
        except RuntimeError:
            pass

    # 正文左右 padding（必须与 apply_theme 里 QSS 的 padding 一致 —— 改一处要改两处）
    TEXT_SIDE_PADDING = 2 * BUBBLE_PAD_H

    def _fit_label_width(self) -> int:
        """算出正文"刚好放得下"的宽度（不是一律撑满上限）

        用 QFontMetrics 量纯文本的自然宽度再夹到 [下限, 上限]：短句贴身、长句到上限折行。⚠️ 不要用 QTextDocument.idealWidth()（字体未生效时量不准）。"""
        from PyQt5.QtGui import QFontMetrics
        text = str(self._text or "")
        if not text.strip():
            return self.MIN_BUBBLE_WIDTH
        try:
            plain = _plain_text(text)
            metrics = QFontMetrics(self.label.font())
            natural = metrics.boundingRect(plain).width() + self.TEXT_SIDE_PADDING + 4
        except Exception:
            natural = int(self._max_width)
        natural = max(self.MIN_BUBBLE_WIDTH, int(natural))
        return min(int(self._max_width), natural)

    def _adjust_inline_height(self):
        """内联编辑框按行数在 1~4 行之间跳档伸缩（和主输入框 _adjust_input_height 同一套）

        ⚠️ 高度要跳档、不能连续变（每敲一个字都长高会让整条抽屉抖）；超过 INPUT_MAX_H 就让编辑框内部自己滚。"""
        editor = self.inline_edit
        if editor is None or not _widget_alive(editor):
            return
        try:
            document = editor.document()
            if document.isEmpty():
                target = INPUT_MIN_H
            else:
                # +16 ≈ 上下 padding（BUBBLE_PAD_V-2 各一份，和 _style_inline_editor 对齐）
                content_height = int(document.size().height()) \
                    + 2 * max(1, BUBBLE_PAD_V - 2)
                if content_height <= INPUT_MIN_H:
                    target = INPUT_MIN_H
                elif content_height <= INPUT_MIN_H + 24:
                    target = INPUT_MIN_H + 24
                elif content_height <= INPUT_MIN_H + 48:
                    target = INPUT_MIN_H + 48
                else:
                    target = INPUT_MAX_H
            if editor.height() != target:
                editor.setFixedHeight(target)
                # 编辑框长高了那一格也要跟着长（否则文字会被裁掉）
                self._refresh_text_host()
        except RuntimeError:
            pass

    def resizeEvent(self, event):
        """气泡宽度变了（抽屉缩放）就把编辑框的宽度跟上"""
        super().resizeEvent(event)
        if self.inline_edit is not None and self.is_editing():
            self._sync_inline_geometry()

    @staticmethod
    def _theme_colors(dark: bool) -> dict:
        """气泡自己的配色（用户气泡是品牌渐变，只有 AI 气泡跟着主题走）

        ⚠️ 描边刻意调得很淡：气泡靠投影和底色分层，描边太重会像一张表单卡片。
        """
        if dark:
            return {"ai_bubble": "#333849",
                    "ai_bubble_border": "rgba(255,255,255,0.09)",
                    "ai_bubble_text": "#E8EAF0"}
        return {"ai_bubble": "#FFFFFF",
                "ai_bubble_border": "rgba(15,23,42,0.07)",
                "ai_bubble_text": "#1F2329"}

    def set_text(self, text: str):
        """设置内容（富文本）

        ⚠️ 这里不重算宽度：流式输出时每个字符都会跑一遍 _to_html + 量宽度、界面会卡死；宽度统一由 apply_max_width() 在布局稳定后算一次。"""
        self._text = str(text or "")
        self.label.setText(self._to_html(self._text))

    def text(self) -> str:
        return self._text

    def plain_text(self) -> str:
        """纯文本内容（复制按钮用：复制出去的应该是干净文字，不带 HTML 标签）"""
        return _plain_text(self._text if "<" in self._text else self._to_html(self._text))

    def _on_link(self, url: str):
        if callable(self._link_handler):
            self._link_handler(url)

    @staticmethod
    def _to_html(text: str) -> str:
        """把消息内容转成气泡用的 HTML

        两种输入：纯文本（转义 → 抠网址 → 插软换行 → 包链接 → 粗体）和本身就是 HTML 的固定文案（不能再转义，否则界面直接显示一堆标签），判据见 _looks_like_html。⚠️ 网址先换成占位符再插换行、且跳过标签内部。"""
        raw = _mentions_to_html(str(text or ""))

        if _looks_like_html(raw):
            return _wrap_html_text(raw)

        escaped = (raw.replace("&", "&amp;")
                      .replace("<", "&lt;")
                      .replace(">", "&gt;"))

        url_pattern = re.compile(r"(https?://[^\s<>\u4e00-\u9fff]+)")
        placeholders = []

        def _stash(match):
            trailing = ""
            url = match.group(1)
            while url and url[-1] in "。,.;:!?)]}）":
                trailing = url[-1] + trailing
                url = url[:-1]
            placeholders.append(f'<a href="{url}">{url}</a>{trailing}')
            return f"\x00{len(placeholders) - 1}\x00"

        html = url_pattern.sub(_stash, escaped)

        # 按用户/AI 自己写的换行切开，逐段插软换行，再拼回去
        html = "<br>".join(_wrap_soft_breaks(part) for part in html.split("\n"))

        # 把真链接放回来（必须在插完换行之后）
        for index, snippet in enumerate(placeholders):
            html = html.replace(f"\x00{index}\x00", snippet)

        # 粗体
        html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html, flags=re.S)
        return html


# 网址占位符：\x00数字\x00
_PLACEHOLDER_PATTERN = re.compile(r"\x00\d+\x00")

# 我们自己会生成的标签（用来判断"这段内容已经是 HTML 了"）
_HTML_TAG_PATTERN = re.compile(r"</?(a|b|br)\b[^>]*>", re.I)


def _looks_like_html(text: str) -> bool:
    """内容里有没有我们自己生成的标签（<a> / <b> / <br>）"""
    return bool(_HTML_TAG_PATTERN.search(str(text or "")))


def _wrap_html_text(html: str) -> str:
    """给已经是 HTML 的内容插软换行（标签内部一律跳过）

    逐字符扫一遍，用 in_tag 标记当前在不在标签里，只对标签外的文本段做软换行。⚠️ 别用简单的 split("<")：状态机才不会漏掉 <br> 这种自闭合标签。"""
    out = []
    buffer = []
    in_tag = False
    for ch in str(html or ""):
        if ch == "<":
            if buffer:
                out.append(_wrap_soft_breaks("".join(buffer)))
                buffer = []
            in_tag = True
            out.append(ch)
        elif ch == ">" and in_tag:
            in_tag = False
            out.append(ch)
        elif in_tag:
            out.append(ch)
        else:
            buffer.append(ch)
    if buffer:
        out.append(_wrap_soft_breaks("".join(buffer)))
    return "".join(out)


def _wrap_soft_breaks(text: str, limit: int = None) -> str:
    """给长段落插 <br>（limit=None 时默认什么都不做）

    ⚠️ 不要改回"固定按 LINE_CHARS 个字插 <br>"：那等于把每行字数写死在文本里，行宽由最长
    的半句决定。QLabel(wordWrap=True) + setMaximumWidth() 本来就会按字符折行。"""
    if not limit or limit <= 0:
        return text
    if len(text) <= limit:
        return text

    pieces = []
    # 按占位符切片，奇数下标是占位符 —— 原样保留，不参与字数计算
    for part in _PLACEHOLDER_PATTERN.split(text):
        for token in re.split(r"(\s+)", part):
            if not token or token.isspace() or len(token) <= limit:
                pieces.append(token)
                continue
            # 长串按 limit 切开
            pieces.append("<br>".join(token[i:i + limit]
                                      for i in range(0, len(token), limit)))
    return "".join(pieces)


def _plain_lines(html_text: str) -> list:
    """把气泡用的 HTML 拆成逐行的纯文本（量气泡宽度用）

    ⚠️ 不能用 _plain_text：它把 <br> 换成空格再压缩空白，多行消息会被拼成一行、量到的是所有行加起来的宽度；这里保留换行结构、其余标签剥掉。"""
    text = str(html_text or "")
    # <br> 和块级标签的结束都算换行
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<\s*/\s*(p|div|li|tr|h[1-6])\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    for entity, char in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                         ("&#39;", "'"), ("&nbsp;", " "), ("&amp;", "&")):
        text = text.replace(entity, char)
    lines = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if line:
            lines.append(line)
    return lines


def _plain_text(html_text: str) -> str:
    """把气泡用的 HTML 还原成纯文本（历史卡片预览用）

    去掉标签 → 还原常见实体 → 压缩空白。内容只有我们自己生成的 a/b/br 三种标签，正则足够，不值得为此引解析库。"""
    text = str(html_text or "")
    # <br> 换成空格（预览里不需要换行）
    text = re.sub(r"<\s*br\s*/?\s*>", " ", text, flags=re.I)
    # 其余标签直接删掉（保留标签里的文字）
    text = re.sub(r"<[^>]+>", "", text)
    # 常见实体还原（&amp; 放最后，避免二次转义）
    for entity, char in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                         ("&#39;", "'"), ("&nbsp;", " "), ("&amp;", "&")):
        text = text.replace(entity, char)
    return " ".join(text.split())


class HistoryListWorker(QThread):
    """后台把历史对话列表读出来（一次几十上百个 json，绝不能放主线程）

    ⚠️ ChatStore.list_sessions() 逐个文件 open + json.loads，会话一多会把主线程按住几百
    毫秒，界面看着就是"点了没反应"。
    ⚠️ 线程的生命期必须自己管住：QThread 在 run() 未结束时被析构会让 Qt 直接 abort。所以
    全部挂进模块级 _HISTORY_WORKERS 集合、不给它父对象、run() 里再兜一层 try/except；
    线程里只读文件、不碰任何 Qt 控件，结果通过信号回主线程建卡片。"""

    loaded = pyqtSignal(object)          # list[ChatSession]

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            sessions = self.store.list_sessions()
        except Exception as exc:
            log.err("AI", "history_list", f"读取历史对话列表失败: {exc}")
            sessions = []
        if self._cancelled:
            return
        try:
            self.loaded.emit(sessions)
        except Exception:
            # 接收方已经被销毁（抽屉关掉了）：Qt 一般会自己断开，这里是最后一道保险
            pass


# 正在跑的对话请求线程：模块级强引用（理由见 _start_request）
# ⚠️ 别改成 parent=self 或单个字段：线程可能在 run() 结束前被析构，进程直接 abort
_CHAT_WORKERS = set()


def _track_chat_worker(worker: AIChatWorker):
    """登记一个对话请求线程，跑完自动摘掉 + deleteLater"""
    _CHAT_WORKERS.add(worker)

    def _done(w=worker):
        _CHAT_WORKERS.discard(w)
        try:
            w.deleteLater()
        except Exception:
            pass

    worker.finished.connect(_done)


# 正在跑的历史列表线程：模块级强引用，保证 QThread 在 run() 结束前不被销毁
_HISTORY_WORKERS = set()


def _track_history_worker(worker: HistoryListWorker):
    """把一个历史列表线程登记进模块级集合，跑完自动摘掉 + deleteLater"""
    _HISTORY_WORKERS.add(worker)

    def _done(w=worker):
        _HISTORY_WORKERS.discard(w)
        try:
            w.deleteLater()
        except Exception:
            pass

    worker.finished.connect(_done)


def _make_history_loading_widget(text: str, parent=None) -> QWidget:
    """建一个加载动画：和搜索页同一个 LoadingWidget，只换文案

    ⚠️ apps_index_framework 有 50 多 KB，必须懒导入（只有点开历史对话才需要）；拿不到那套时退回最简单的文字标签 —— 加载 UI 缺失就退化成"点了没反应"。"""
    try:
        from ..widgets.apps_index_framework import LoadingWidget

        class _HistoryLoading(LoadingWidget):
            LOADING_TEXT = str(text or "正在加载历史对话")

        return _HistoryLoading(parent)
    except Exception as exc:
        log.err("AI", "history_loading_ui", f"加载动画建不出来，退回文字标签: {exc}")
        label = QLabel(str(text or "正在加载历史对话"), parent)
        label.setAlignment(Qt.AlignCenter)
        label.setFont(ui_font(10))
        return label


class HistoryCard(QFrame):
    """历史对话列表里的一张卡片（只显示对话内容本身，不显示标题）

    整张卡片可点 → 载入对话；左下角红色垃圾桶 → 删除对话；右下角是起止时间。⚠️ 删除按钮必须吃掉自己的鼠标事件，否则点击会冒泡到卡片上、变成"想删却把对话载入了"。"""

    clicked = pyqtSignal(str)          # 参数：会话 id
    delete_requested = pyqtSignal(str)  # 参数：会话 id（点左下角垃圾桶）

    PREVIEW_MAX = 120                  # 预览文字最多多少字（再长就用 … 截掉）

    def __init__(self, session, colors: dict, parent=None):
        super().__init__(parent)
        self.session_id = session.id
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("aiHistoryCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(6)

        preview = self._preview_text(session)
        self.preview_label = QLabel(preview)
        self.preview_label.setWordWrap(True)
        self.preview_label.setFont(ui_font(9))
        # ⚠️ 换成纯文本显示（默认会被当成富文本，对话里的网址/尖括号会被渲染）
        self.preview_label.setTextFormat(Qt.PlainText)
        layout.addWidget(self.preview_label)

        # ---- 底部一行：左 = 删除按钮（红色垃圾桶），右 = 起止时间 ----
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(6)

        self.delete_btn = IconButton(None, self._t_static("ai_delete_chat"), 24, 16, self)
        self.delete_btn.set_icon(_glyph_icon(ICON_TRASH, COLOR_DANGER))
        self.delete_btn.clicked.connect(
            lambda: self.delete_requested.emit(self.session_id))
        bottom.addWidget(self.delete_btn, 0, Qt.AlignBottom)
        bottom.addStretch(1)

        self.time_label = QLabel(self._time_text(session))
        self.time_label.setFont(ui_font(8))
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bottom.addWidget(self.time_label, 0, Qt.AlignBottom)
        layout.addLayout(bottom)

        self.apply_theme(colors)

    def apply_theme(self, colors: dict):
        # 卡片背景用 setStyleSheet（要配合 hover 变色），不走全局 QSS 选择器
        self.setStyleSheet(f"""
            QFrame#aiHistoryCard {{
                background: {colors['card']};
                border: 1px solid {colors['divider']};
                border-radius: 10px;
            }}
            QFrame#aiHistoryCard:hover {{ background: {colors['card_hover']}; }}
        """)
        self.preview_label.setStyleSheet(
            f"color: {colors['text']}; background: transparent;")
        self.time_label.setStyleSheet(
            f"color: {colors['muted']}; background: transparent;")
        # 删除按钮固定红色、不跟主题走：危险操作在两种主题下都要一眼认出来
        self.delete_btn.set_icon(_glyph_icon(ICON_TRASH, COLOR_DANGER))

    @classmethod
    def _preview_text(cls, session) -> str:
        """把整个对话压成一段预览（用户和 AI 的消息都取）

        取前几条拼起来，超过 PREVIEW_MAX 就截断加省略号，避免一条占满整屏。⚠️ 历史里存的是气泡用的 HTML，直接塞进卡片会把 <a href=...> 标签原样显示出来。"""
        pieces = []
        for message in session.messages:
            content = _plain_text(message.get("content") or "")
            content = " ".join(content.split())
            if not content:
                continue
            who = "我：" if message.get("role") == ROLE_USER else ""
            pieces.append(who + content)
            if sum(len(p) for p in pieces) >= cls.PREVIEW_MAX:
                break

        text = "  ".join(pieces)
        if not text:
            return cls._t_static("ai_history_empty_card")
        if len(text) > cls.PREVIEW_MAX:
            text = text[:cls.PREVIEW_MAX].rstrip() + "…"
        return text

    @staticmethod
    def _t_static(key: str) -> str:
        """静态场景下取兜底文案（卡片是纯展示控件，不持有 language_manager）"""
        try:
            from ..interfaces.settings.texts import FALLBACK_TEXTS
            return FALLBACK_TEXTS.get(key, key)
        except Exception:
            return key

    @staticmethod
    def _time_text(session) -> str:
        """右下角的时间：开始 → 结束（同一天则省掉后半段的日期）"""
        start = str(session.created_at or "")
        end = str(session.updated_at or start)
        if not start:
            return end
        if end and end[:10] == start[:10]:
            return f"{start} → {end[11:]}"
        return f"{start} → {end}" if end else start

    def mouseReleaseEvent(self, event):
        # 只处理"在卡片内按下并抬起"，跟普通按钮一致
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit(self.session_id)
        super().mouseReleaseEvent(event)


class AIHistoryDrawer(BaseDrawer):
    """历史对话抽屉（独立页面，从右侧滑出，盖在聊天抽屉上）

    左上角左箭头返回聊天（Esc 同）；列表按时间倒序，最新的在最上面；每张卡片 = 内容预览 + 右下角起止时间，点卡片载入该对话并返回聊天页。"""

    def __init__(self, main_window, chat_drawer, parent=None):
        self.chat_drawer = chat_drawer
        self._cards = []
        # 请求序号：慢的那次结果回来时若已不是最新请求就丢掉（连点历史按钮会覆盖成过期列表）
        self._loading = False
        self._request_seq = 0
        self._result_seq = 0
        # 加载期间又被要求刷新 → 读完自动补一次（不再起一个线程）
        self._pending_refresh = False
        # 当前列表的指纹：内容没变就不重建卡片（见 _build_cards）
        self._shown_signature = None
        self._worker = None
        self._loading_widget = None
        self._loading_timer = None
        # 基类构造里会调 on_open()，所以卡片列表要先建好
        super().__init__(main_window, parent or main_window)

        self._build_ui()
        self.apply_theme()

    # ---------- 界面 ----------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.container = QFrame()
        self.container.setObjectName("aiDrawerContainer")
        root.addWidget(self.container)

        box = QVBoxLayout(self.container)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        box.addWidget(self._build_header())

        self.divider = QFrame()
        self.divider.setFixedHeight(1)
        box.addWidget(self.divider)

        # 卡片列表（可滚动）
        # ⚠️ 用库自带的 SmoothScrollArea：和设置页 / 搜索页同一套细滚动条观感
        self.scroll = SmoothScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(12, 12, 12, 12)
        self.list_layout.setSpacing(10)
        self.list_layout.addStretch(1)      # 卡片从上往下排，底部留白吃在 stretch 上

        self.scroll.setWidget(self.list_host)
        box.addWidget(self.scroll, 1)

        # 加载中那一块（与 scroll 抢占同一位置：加载时只显示它）
        self.loading_host = QWidget(self.container)
        self.loading_layout = QVBoxLayout(self.loading_host)
        self.loading_layout.setContentsMargins(0, 0, 0, 0)
        self.loading_layout.setAlignment(Qt.AlignCenter)
        self.loading_host.hide()
        box.addWidget(self.loading_host, 1)

        self.empty_label = QLabel(self._t("ai_history_empty"))
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setFont(ui_font(10))
        self.empty_label.hide()
        box.addWidget(self.empty_label)

        # ⚠️ 不再装项目自己的平滑滚动：SmoothScrollArea 已带惯性，两套会打架
        _apply_app_scrollbar(self.scroll)

        # 加载慢于 LOADING_UI_DELAY_MS 才亮出加载动画（快的时候闪一下反而晃眼）
        self._loading_timer = QTimer(self)
        self._loading_timer.setSingleShot(True)
        self._loading_timer.setInterval(self.LOADING_UI_DELAY_MS)
        self._loading_timer.timeout.connect(self._reveal_loading_ui)

    # 加载动画的延迟显示时间（毫秒）
    LOADING_UI_DELAY_MS = 140

    def _build_header(self) -> QWidget:
        """顶栏：左箭头返回按钮 + 标题（按钮上不写文字）"""
        header = QWidget()
        header.setObjectName("aiDrawerHeader")
        header.setFixedHeight(48)
        row = QHBoxLayout(header)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(6)

        self.back_btn = QPushButton()
        self.back_btn.setFixedSize(30, 30)
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.setToolTip(self._t("ai_back"))
        self.back_btn.setIcon(_svg_icon(ICON_BACK, "#4B4F58"))
        self.back_btn.setIconSize(QSize(18, 18))
        self.back_btn.clicked.connect(self.go_back)
        row.addWidget(self.back_btn)

        self.title_label = QLabel(self._t("ai_history"))
        self.title_label.setFont(ui_font(12, bold=True))
        row.addWidget(self.title_label)
        row.addStretch(1)

        return header

    @staticmethod
    def _icon_buttons() -> list:
        # 基类 apply_theme 会统一给这些按钮上色
        return []

    # ---------- 内容 ----------
    def refresh(self):
        """刷新历史列表：后台读盘 + 加载 UI（最新的在最上面）

        ① 同一时间只跑一个读取任务：正在加载时再调 refresh() 只记个标记，读完自动补一次；② 加载期间列表整体收起、只显示加载 UI，避免"点了没反应"的空档。"""
        if self._loading:
            # 已经在读了：只记一个标记，读完自动再补一次。
            # ⚠️ 不能在这里再起线程，更不能把 self._worker 换成新的：旧线程的 Python
            #    引用一丢，Qt 会在它还在跑的时候把它析构掉，整个进程直接 abort。
            self._pending_refresh = True
            return
        self._loading = True
        self._pending_refresh = False
        self._request_seq += 1
        self._result_seq = self._request_seq
        # ⚠️ 先不收起旧列表：读得快时界面一动不动、没有闪烁；真的超过
        #    LOADING_UI_DELAY_MS 才由 _reveal_loading_ui 换成加载动画。
        self._loading_timer.start()

        # ⚠️ 不传 parent：线程生命期由模块级集合管（见 _track_history_worker）
        worker = HistoryListWorker(self.chat_drawer.store)
        # ⚠️ 用绑定方法连信号而不是 lambda：绑定方法在接收者被销毁时 Qt 会自动断开
        worker.loaded.connect(self._on_sessions_loaded)
        _track_history_worker(worker)
        self._worker = worker
        worker.start()

    def _reveal_loading_ui(self):
        """真的把加载动画亮出来（延迟到了才亮）

        到这一步说明读盘确实慢，把旧列表收起来：那些卡片马上就要被销毁，留在屏幕上给用户点也是没反应。"""
        if not self._loading or self._loading_widget is not None:
            return
        try:
            self.empty_label.hide()
            self.scroll.hide()
            self._loading_widget = _make_history_loading_widget(
                self._t("ai_history_loading"), self.loading_host)
            self.loading_layout.addWidget(self._loading_widget, 0, Qt.AlignCenter)
            self.loading_host.show()
        except Exception as exc:
            log.err("AI", "history_loading_ui", f"加载动画建不出来: {exc}")

    def _hide_loading_ui(self):
        """收掉加载动画（停掉里面的定时器/动画，再销毁）"""
        self._loading_timer.stop()
        widget = self._loading_widget
        self._loading_widget = None
        if widget is not None:
            try:
                stop = getattr(widget, "stop", None)
                if callable(stop):
                    stop()
            except Exception:
                pass
            try:
                self.loading_layout.removeWidget(widget)
                widget.setParent(None)
                widget.deleteLater()
            except Exception:
                pass
        try:
            self.loading_host.hide()
        except Exception:
            pass

    def _on_sessions_loaded(self, sessions: list):
        """后台读完了（主线程槽）：收加载态 + 建卡片，必要时补一次刷新

        ⚠️ 过期结果（读的过程中又刷新过）直接丢掉，别覆盖新列表。
        """
        if not _widget_alive(self):
            return
        try:
            self._loading = False
            self._hide_loading_ui()
            if self._result_seq != self._request_seq:
                return
            self._build_cards(sessions or [])
            if self._pending_refresh:
                self._pending_refresh = False
                QTimer.singleShot(0, self.refresh)
        except RuntimeError:
            # 抽屉在这中间被销毁了：什么都不用做
            pass
        except Exception as exc:
            log.err("AI", "history_list", f"刷新历史列表失败: {exc}")

    def _build_cards(self, sessions: list):
        """按会话列表重建卡片（最新的在最上面）

        ⚠️ 内容没变就不重建：open_history() 和抽屉 on_open() 会连着 refresh 两次，用户在中间
        点卡片时按下的旧卡片会在松开前被 deleteLater，这一下点击就凭空消失。"""
        signature = self._signature(sessions)
        if signature == self._shown_signature and (self._cards or not sessions):
            return
        self._shown_signature = signature

        for card in self._cards:
            try:
                self.list_layout.removeWidget(card)
                # 同 _clear_messages：先藏再删，否则旧卡片会停在原处叠在新卡片上
                card.hide()
                card.deleteLater()
            except Exception:
                pass
        self._cards = []

        if not sessions:
            self.empty_label.show()
            self.scroll.hide()
            return

        colors = self._theme_colors()
        self.empty_label.hide()
        self.scroll.show()
        for session in sessions:
            card = HistoryCard(session, colors, self.list_host)
            card.clicked.connect(self._on_card_clicked)
            card.delete_requested.connect(self._on_card_delete_requested)
            self.list_layout.insertWidget(self.list_layout.count() - 1, card)
            self._cards.append(card)

    @staticmethod
    def _signature(sessions: list):
        """一批会话的指纹（id + 更新时间）：内容没动就不必重建卡片"""
        out = []
        for session in sessions or []:
            try:
                out.append((str(session.id), str(session.updated_at),
                            len(session.messages or [])))
            except Exception:
                continue
        return tuple(out)

    def _on_card_clicked(self, session_id: str):
        """点卡片：载入对话并回到聊天页

        ⚠️ 只有真的载入成功才返回聊天页：失败也 go_back() 的话，用户想再试一次还得重新点开历史、重新等列表；失败时留在历史页并刷新一次列表。"""
        if self.chat_drawer.load_session(session_id):
            self.go_back()
            return
        # 载入失败：留在这一页，刷新列表让用户能再选一次
        self.refresh()

    def _on_card_delete_requested(self, session_id: str):
        """点卡片左下角的红色垃圾桶：先弹确认框，确认了才删掉这个对话

        删除不可逆（连同聊天记录一起没），确认框样式与插件页删插件那条保持一致。⚠️ 删完必须 refresh() 重建列表；删的若是当前正在聊的那个，聊天页也要换成新对话。"""
        if not self._ask_delete_confirm():
            return
        self.chat_drawer._delete_session(session_id)
        self.refresh()

    def _ask_delete_confirm(self) -> bool:
        """弹"删除对话"确认框；返回 True = 用户点了删除

        ⚠️ 确认框是盖在抽屉上的子控件盖层，弹着时"点外面就关闭"的守卫会误判成"点了抽屉
        外面"把抽屉先滑走；所以先摘守卫、再打 _dialog_open 标记，finally 里恢复。"""
        if _ConfirmMessageBox is None:
            # qfluentwidgets 没装 → 保持老行为直接删，总比对话永远删不掉强
            return True
        self._dialog_open = True
        self._remove_outside_close()
        try:
            box = _ConfirmMessageBox(self._t("ai_delete_title"),
                                     self._t("ai_delete_confirm"), self)
            box.yesButton.setText(self._t("ai_delete_btn"))
            box.cancelButton.setText(self._t("cancel"))
            # ⚠️ 让 Qt 自己销毁：确认框是本抽屉的子控件，否则每删一次就多留一个
            # 隐藏弹窗挂在抽屉上（exec() 里 Qt 会先存下 WA_DeleteOnClose，返回后删）
            box.setAttribute(Qt.WA_DeleteOnClose, True)
            return bool(box.exec())
        except Exception as exc:
            log.err("AI", "delete", f"删除确认框弹出失败: {exc}")
            return False        # 弹不出来就不删：危险操作宁可不动
        finally:
            self._dialog_open = False
            if self.is_open():
                self._install_outside_close()

    def go_back(self):
        """返回聊天页（左箭头按钮 / Esc）"""
        self.close_drawer()
        # 回到聊天抽屉并聚焦输入框
        QTimer.singleShot(SLIDE_DURATION_MS + 20, self.chat_drawer.focus_input)

    def _escape_stack(self) -> list:
        """历史抽屉在最上面，底下才是聊天抽屉（见 BaseDrawer.handle_escape）"""
        return [self] + ([self.chat_drawer] if self.chat_drawer is not None else [])

    def _on_escape(self):
        """Esc 在历史页 = 返回聊天页（不关闭整个 AI 面板）"""
        self.go_back()

    def keyPressEvent(self, event):
        """Esc = 返回聊天（不关闭整个界面）

        这里保留自己的处理：焦点真落在历史抽屉上时不依赖全局过滤器也能对；其余情况由基类那套全局 Esc 路由裁决（见 BaseDrawer.handle_escape）。"""
        if event.key() == Qt.Key_Escape and self.is_open():
            self.go_back()
            return
        super().keyPressEvent(event)

    def on_open(self):
        # 每次滑出都重建列表：期间可能聊过新内容
        self.refresh()
        # 装"点外面就关"的守卫（重复安装无副作用，见 _install_outside_close）
        self._install_outside_close()

    def on_close(self):
        self._remove_outside_close()
        # ⚠️ 关掉历史页时后台若还在读列表：只作废上报，不碰线程本身（它由模块级集合
        #    管着，会自己跑完再销毁）。丢掉引用会让正在跑的 QThread 被析构、进程 abort。
        worker = self._worker
        if _worker_running(worker):
            worker.cancel()
            self._pending_refresh = True     # 下次打开时补一次
        else:
            self._loading = False
            self._hide_loading_ui()
        if self.back_btn is not None:
            self.back_btn.setFocus()        # 让 Esc 事件落在本抽屉上

    # ---------- 点击界面内其它位置 → 关闭 ----------
    def _install_outside_close(self):
        """在本程序内部点"历史抽屉以外"的任意位置，就把历史抽屉关掉

        它是非模态的子控件、不是独立窗口，没有"失活"事件可用；所以用全局事件过滤器覆盖主窗口任意角落，再用 isAncestorOf 把"点在自己身上"的情况排除掉。"""
        app = QApplication.instance()
        if app is None or getattr(self, "_outside_filter_installed", False):
            return
        app.installEventFilter(self)
        self._outside_filter_installed = True

    def _remove_outside_close(self):
        app = QApplication.instance()
        if app is None or not getattr(self, "_outside_filter_installed", False):
            return
        app.removeEventFilter(self)
        self._outside_filter_installed = False

    def _is_inside(self, widget) -> bool:
        """这个控件是不是"历史抽屉自己"（包含子控件）"""
        if widget is None:
            return False
        if widget is self:
            return True
        try:
            return self.isAncestorOf(widget)
        except Exception:
            return False

    def eventFilter(self, obj, event):
        """本抽屉的全局过滤器：点外面就把历史页收起来

        ⚠️ 判断依据必须是鼠标坐标，不能只看事件落在哪个控件上：Qt 会把被忽略的鼠标按下沿
        父链重发（点卡片里的 QLabel、点列表空白都会落到 MainWindow），那时 obj 是主窗口、
        按下的瞬间就把抽屉关了，紧接着的"松开"无处可去、卡片收不到 click。
        口径与聊天抽屉一致：坐标在不在抽屉矩形里 + widgetAt 复核，都说是外面才关。"""
        if event.type() == QEvent.MouseButtonPress and self.is_open() \
                and not self._dialog_open:
            if not self._press_is_inside(event):
                # ⚠️ 延时 0ms 再关：立刻收起会把"按下—松开"拆到两个控件上，卡片就点不响了
                QTimer.singleShot(0, self._close_if_still_open)
        return super().eventFilter(obj, event)

    def _press_is_inside(self, event) -> bool:
        """这一下鼠标按下，从坐标上看算不算"在历史抽屉里"

        ⚠️ 两路证据取或（坐标落在抽屉矩形里 / widgetAt 的控件属于本抽屉），任一条成立就放行 —— 宁可少关一次，也不要吃掉用户的一次点击。"""
        try:
            global_pos = event.globalPos()
        except Exception:
            return True                      # 拿不到坐标就当"在里面"，绝不吃点击
        # 1) 坐标落在抽屉矩形里？
        try:
            if self.rect().contains(self.mapFromGlobal(global_pos)):
                return True
        except Exception:
            pass
        # 2) 屏幕坐标下的控件属于本抽屉？
        try:
            from PyQt5.QtWidgets import QApplication
            widget = QApplication.widgetAt(global_pos)
            if widget is not None and (widget is self or self.isAncestorOf(widget)):
                return True
        except Exception:
            pass
        return False

    def _close_if_still_open(self):
        """延时关闭（见 eventFilter 里的说明）"""
        try:
            if self.is_open():
                self.close_drawer()
        except Exception:
            pass

    # ---------- 主题 ----------
    def apply_extra_theme(self, colors: dict):
        style = f"""
            QPushButton {{
                background: transparent; border: none; border-radius: 8px;
            }}
            QPushButton:hover {{ background: {colors['hover']}; }}
        """
        self.back_btn.setStyleSheet(style)
        self.back_btn.setIcon(_svg_icon(ICON_BACK, colors["icon"]))
        self.divider.setStyleSheet(f"background: {colors['divider']}; border: none;")
        self.empty_label.setStyleSheet(
            f"color: {colors['muted']}; background: transparent;")
        # ⚠️ 这里不再给滚动条写 QSS：现在用的是库自带的 SmoothScrollBar（见
        #    _apply_app_scrollbar），写 QSS 会盖住它的自绘、变回手写的那一条。
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.list_host.setStyleSheet("background: transparent;")
        for card in self._cards:
            card.apply_theme(colors)


class AIChatDrawer(BaseDrawer):
    """右侧 AI 聊天抽屉（内嵌形态也用它）

    主窗口用到的接口：open_drawer() / close_drawer() / toggle() / sync_geometry() / focus_input() / apply_theme() / open_history()。"""

    def __init__(self, main_window, parent=None, embedded: bool = False):
        # ⚠️ 必须先 super().__init__() 再建那些拿 self 当父对象的部件：构造完成前
        # 建 QTimer(self) 会抛 "super-class __init__() ... was never called"。
        # （基类构造里的 on_open() 要等 open_drawer() 才调，那时这些字段都已就位。）
        super().__init__(main_window, parent, embedded=embedded)

        self.store = ChatStore()
        self.session = None
        # 当前界面上那串气泡对应的"内容指纹"（见 sync_shared_session）：
        # 和 self.session 现在的内容对不上，就说明"我藏起来的时候另一边改过它"
        self._render_fingerprint = None
        self.worker = None
        self.history_drawer = None
        self._placeholder_bubble = None
        self._resources_cache = None
        # 资源库文件的指纹（路径/修改时间/大小）：变了就重新读盘，见 _resources()
        self._resources_sig = None
        self._thinking_step = 0
        # 版本翻页相关（编辑重写 / 重新生成）：
        #   _variants: 消息下标 -> [版本内容, ...]（只在内存里，磁盘上仍只存当前版本）
        #   _variant_active: 消息下标 -> 当前显示第几版
        #   _edit_index: 正在重写哪条用户消息（发送时替换它并丢掉后面的内容）
        #   _regen_index: 正在重新生成哪个位置的回答
        #   _inline_edit_bubble: 当前正在原地当输入框的那条气泡（同时最多一条）
        self._variants = {}
        self._variant_active = {}
        # 载入历史时有没有修过"正文不在版本表里"的坏数据（见 _repair_variants）
        self._variants_repaired = False
        self._edit_index = None
        self._regen_index = None
        self._inline_edit_bubble = None
        # 关闭抽屉时记下的滚动位置 + 当时是哪个会话；重开时若还是同一会话就恢复
        self._remember_scroll = None
        self._remember_session = None
        # GCP-AI Agent 这一轮请求的临时上下文：
        #   _agent_scratch 工具调用与结果的记录，不落盘、不进历史，只拼在本次请求后面
        #   _agent_round   这一轮已经跑了几次工具往返（超过 MAX_ROUNDS 就收手）
        self._agent_scratch = []
        self._agent_round = 0
        self._agent_pending_regen = None
        # 这一轮 AI 动过的手（显示在"正在思考"气泡里，让用户看得见）
        self._agent_activity = []
        self._thinking_timer = QTimer(self)
        self._thinking_timer.setInterval(420)
        self._thinking_timer.timeout.connect(self._animate_thinking)

        self._build_ui()
        self.apply_theme()
        self._load_startup_session()

    # ================= 界面 =================
    def _prepare_drawer_window(self):
        """内嵌形态不做抽屉那套窗口设置（不固定宽、不透明化、不 hide）"""
        if self._embedded:
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
            # ⚠️ 必须显式 show()：未显示的控件不参与父布局的尺寸分配，漏了这一句
            #    整页 AI 会一直卡在 100×30 的 sizeHint 上，页面拉大也没用。
            self.show()
            return
        super()._prepare_drawer_window()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.container = QFrame()
        self.container.setObjectName("aiDrawerContainer")
        root.addWidget(self.container)

        box = QVBoxLayout(self.container)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        box.addWidget(self._build_header())

        self.divider = QFrame()
        self.divider.setFixedHeight(1)
        box.addWidget(self.divider)

        self.scroll = self._build_messages()
        # ⚠️ 消息区要存成字段：下面的"正在加载对话"遮罩要跟着它的几何走
        box.addWidget(self.scroll, 1)

        # ---------- 聊天区的加载遮罩 ----------
        # 打开很长的历史对话时"读文件 + 建几十个气泡"要几百毫秒到一秒多，这里盖一层
        # 和搜索页同款的加载动画。
        # ⚠️ 它是 container 的子控件、盖在滚动区上面（不塞进布局），不会把消息区尺寸算坏。
        self.chat_loading_host = QWidget(self.container)
        self.chat_loading_host.setObjectName("aiChatLoadingHost")
        self.chat_loading_layout = QVBoxLayout(self.chat_loading_host)
        self.chat_loading_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_loading_layout.setAlignment(Qt.AlignCenter)
        self.chat_loading_host.hide()
        self._chat_loading_widget = None

        self.input_divider = QFrame()
        self.input_divider.setFixedHeight(1)
        box.addWidget(self.input_divider)

        box.addWidget(self._build_input_row())

    # ================= 聊天区加载遮罩 =================
    def _show_chat_loading(self, on: bool):
        """亮出 / 收起聊天区的"正在加载对话"遮罩"""
        host = getattr(self, "chat_loading_host", None)
        if host is None:
            return
        if on:
            try:
                host.setGeometry(self.scroll.geometry())
            except Exception:
                pass
            if self._chat_loading_widget is None:
                self._chat_loading_widget = _make_history_loading_widget(
                    self._t("ai_chat_loading"), host)
                self.chat_loading_layout.addWidget(self._chat_loading_widget, 0,
                                                   Qt.AlignCenter)
            host.show()
            host.raise_()
            return
        widget = self._chat_loading_widget
        self._chat_loading_widget = None
        if widget is not None:
            try:
                stop = getattr(widget, "stop", None)
                if callable(stop):
                    stop()
                self.chat_loading_layout.removeWidget(widget)
                widget.setParent(None)
                widget.deleteLater()
            except Exception:
                pass
        try:
            host.hide()
        except Exception:
            pass

    def _build_header(self) -> QWidget:
        """顶栏：标题 + 新对话 + 历史对话 + 收起"""
        header = QWidget()
        header.setObjectName("aiDrawerHeader")
        header.setFixedHeight(48)
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 0, 10, 0)
        row.setSpacing(6)

        self.title_label = QLabel("GCP-AI")
        self.title_label.setFont(ui_font(12, bold=True))
        row.addWidget(self.title_label)
        row.addStretch(1)

        self.new_btn = QPushButton()
        self.new_btn.setFixedSize(30, 30)
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.setToolTip(self._t("ai_new_chat"))
        self.new_btn.clicked.connect(self.new_chat)
        row.addWidget(self.new_btn)

        self.history_btn = QPushButton()
        self.history_btn.setFixedSize(30, 30)
        self.history_btn.setCursor(Qt.PointingHandCursor)
        self.history_btn.setToolTip(self._t("ai_history"))
        self.history_btn.clicked.connect(self.open_history)
        row.addWidget(self.history_btn)

        # 「收起」按钮只在抽屉形态下存在（内嵌成页面之后没有意义）
        self.close_btn = None
        if not self._embedded:
            self.close_btn = QPushButton("×")
            self.close_btn.setFixedSize(30, 30)
            self.close_btn.setCursor(Qt.PointingHandCursor)
            self.close_btn.setToolTip(self._t("ai_close_drawer"))
            self.close_btn.clicked.connect(self.close_drawer)
            row.addWidget(self.close_btn)

        return header

    def _build_messages(self) -> QWidget:
        """消息区：竖向滚动 + 气泡贴顶排列"""
        # 库自带的平滑滚动区（自画细滚动条）
        self.scroll = SmoothScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.message_host = QWidget()
        self.message_layout = QVBoxLayout(self.message_host)
        self.message_layout.setContentsMargins(14, 12, 14, 12)
        self.message_layout.setSpacing(MESSAGE_SPACING)
        # ⚠️ AlignTop 是"气泡高度不被拉高"的关键：QVBoxLayout 没设对齐时，多余高度会
        #    平分给每个子项（实测三条气泡被拉成 141px，就是"气泡里一片空行"）。
        self.message_layout.setAlignment(Qt.AlignTop)
        # ⚠️ 弹簧必须在末尾（气泡贴顶）：开头的弹簧会把气泡全压到底部、顶部留一大片
        #    空白，就是被反复报的"聊天气泡空行 / 对话不在顶部"。不要改回贴底。
        self._embedded_layout = True

        self.scroll.setWidget(self.message_host)
        # 同上：惯性交给 SmoothScrollArea，不再叠一套
        _apply_app_scrollbar(self.scroll)
        # 末尾弹簧吃掉剩余高度 → 气泡贴顶（两种形态一致）
        self.message_layout.addStretch(0)
        return self.scroll

    def _build_input_row(self) -> QWidget:
        """输入行：上面一条圆角悬浮提示 + 多行输入框 + 右侧发送按钮

        竖着两格：上面 hint_bar（没内容时整条隐藏），下面是"输入框 + 发送"那一行。
        """
        holder = QWidget()
        holder.setObjectName("aiDrawerInput")
        outer = QVBoxLayout(holder)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---------- 悬浮提示条 ----------
        # ⚠️ 不放进 QScrollArea：它要"贴"在输入框上面、跟着输入框一样宽。
        self.hint_bar = QWidget(holder)
        self.hint_bar.setObjectName("aiInputHintBar")
        self.hint_layout = QHBoxLayout(self.hint_bar)
        self.hint_layout.setContentsMargins(12, 6, 12, 6)
        self.hint_layout.setSpacing(10)
        self.hint_bar.hide()
        self._hint_widgets = []
        self._hint_version = -1
        outer.addWidget(self.hint_bar)

        row_host = QWidget(holder)
        row = QHBoxLayout(row_host)
        row.setContentsMargins(12, 10, 12, 12)
        row.setSpacing(8)

        self.input_edit = MentionTextEdit()
        self.input_edit.setAcceptRichText(False)
        self.input_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        self.input_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.input_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.input_edit.setFont(ui_font(10))
        # 文档自带 margin 会和样式表 padding 叠加，导致 1 行高度算不准，先清零
        self.input_edit.document().setDocumentMargin(0)
        self.input_edit.setPlaceholderText(self._t("ai_input_placeholder"))
        self.input_edit.setFixedHeight(INPUT_MIN_H)
        # ⚠️ 高度用 documentSizeChanged 而不是 textChanged：textChanged 发出时 Qt 还没
        # 排完版，doc.size() 拿到的是旧值，输入框高度会永远慢一行。
        self.input_edit.document().documentLayout().documentSizeChanged.connect(
            self._adjust_input_height)
        # ⚠️ 再单独接一次 textChanged 给命令候选和悬浮提示用：documentSizeChanged 只在
        #    排版尺寸变了才发，打 /p 再打 l 宽度可能没变，候选列表会"卡在上一帧"。
        self.input_edit.textChanged.connect(self._on_input_text_changed)
        # 被识别的正确指令染成主题蓝
        self._command_highlighter = None
        try:
            self._command_highlighter = CommandHighlighter(
                self.input_edit.document(), self)
        except Exception:
            self._command_highlighter = None
        self.input_edit.installEventFilter(self)
        # 输入框里的 @ 提及是可点的锚点 → 点了跳对应资源的详情页
        self.input_edit.anchorClicked.connect(self._on_link_clicked)
        row.addWidget(self.input_edit, 1)

        self.send_btn = QPushButton(self._t("ai_send"))
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setFixedWidth(66)
        self.send_btn.setFixedHeight(INPUT_MIN_H)
        self.send_btn.setFont(ui_font(10, bold=True))
        self.send_btn.clicked.connect(self.on_send_clicked)
        row.addWidget(self.send_btn, 0, Qt.AlignBottom)

        # ⚠️ 这里故意没有"输入 @ 弹候选列表"那套东西：@ 提及只有搜索页卡片右上角的
        #    "@" 按钮一个入口（insert_mention），手打的 @名称(编码) 退格能整段删掉。
        outer.addWidget(row_host)
        self._style_hint_bar()
        return holder

    # ================= 输入框上方的悬浮提示（可以点的"命令"） =================
    def _on_input_text_changed(self):
        """"输入内容变了"的统一钩子（textChanged → 这里）

        ⚠️ 单独接 textChanged 的原因见 _build_input_row：documentSizeChanged 在"宽度没变"的那几次按键上不发信号，候选列表会卡在上一帧。"""
        self._refresh_command_ui()

    def _is_known_command(self, word: str) -> bool:
        """这个词是不是正好一条已登记的命令（给蓝色高亮用）

        ⚠️ 只认打完整的（/plugin 算、/plu 不算）。
        """
        word = str(word or "").strip()
        if not word:
            return False
        try:
            from ..core.ai.chat_hints import get_hint_registry
            registry = get_hint_registry()
            target = word.lower()
            for hint in registry.all():
                if not self._hint_source_active(getattr(hint, "source", "")):
                    continue
                if str(getattr(hint, "insert", "") or "").lower() == target:
                    return True
        except Exception:
            pass
        return False

    def _command_color(self) -> str:
        """指令高亮用的颜色（跟随主题色，和 @ 提及那种蓝保持一致）"""
        try:
            from ..interfaces.settings.theme import brand_link_color
            return brand_link_color()
        except Exception:
            return COLOR_MENTION

    def _refresh_command_ui(self):
        """把"/命令"相关的两样东西一起刷新（候选面板 + 悬浮提示条）

        ⚠️ 两个都要每次输入变化就重算（显隐取决于输入框内容，任何"版本没变就跳过"的短路都会让它们失灵）；且必须有重入保护：_position_command_popup 会改控件尺寸，Qt 会因此在事件循环里回头再发一次尺寸变化 → 又回到这里，没有保护会 RecursionError 打崩进程。"""
        if getattr(self, "_command_ui_busy", False):
            return
        self._command_ui_busy = True
        try:
            self._refresh_chat_hints()
        except Exception:
            pass
        try:
            self._refresh_command_popup()
        except Exception:
            pass
        finally:
            self._command_ui_busy = False

    def _style_hint_bar(self):
        """给提示条上"四个角都圆润"的样式

        圆角尺度和气泡 / 输入区一致；背景只取一点主题色，像浮在输入框上的小胶囊。
        """
        bar = getattr(self, "hint_bar", None)
        if bar is None:
            return
        dark = bool(self._dark)
        bg = "rgba(255,255,255,0.05)" if dark else "rgba(91,141,239,0.08)"
        bar.setStyleSheet(
            "QWidget#aiInputHintBar {"
            f"  background: {bg};"
            "   border: none;"
            "   border-radius: 14px;"
            "}")
        for widget in getattr(self, "_hint_widgets", []):
            try:
                widget.setStyleSheet(
                    f"color: {brand_link_color()}; background: transparent;"
                    " font-size: 12px;")
            except Exception:
                pass

    def _refresh_chat_hints(self, force: bool = False):
        """输入框上方的悬浮提示条（不是常驻的）

        ⚠️ 显示条件：整段以 / 开头且还没打出空格，并且这条命令还没输完整；文案形如 "/plugin AI帮你制作插件"。"""
        bar = getattr(self, "hint_bar", None)
        if bar is None:
            return
        try:
            from ..core.ai.chat_hints import get_hint_registry, locale_of
            registry = get_hint_registry()
            first_time = getattr(self, "_hint_version", None) != registry.version
            self._hint_version = registry.version
            # ⚠️ 只有注册表变了才 rehighlight：在"输入变化"这条路径上无条件调用会让
            #    文档内容变脏 → 再发一次 textChanged → 无限递归。
            if first_time:
                highlighter = getattr(self, "_command_highlighter", None)
                if highlighter is not None:
                    try:
                        highlighter.rehighlight()
                    except Exception:
                        pass
            language = "简体中文"
            try:
                language = self.main_window.language_manager.current_language
            except Exception:
                pass
            hint_dicts = [h for h in registry.to_dicts(locale_of(language))
                          if self._hint_source_active(h.get("source"))]
        except Exception:
            hint_dicts = []
        # ⚠️ 不能因为"注册表版本没变"就提前返回：这条提示条的显隐还取决于输入框里的
        #    内容（打了斜杠没打完才显示），加了版本短路就会永远不出现。重算代价可忽略。

        # ---------- 显示条件：有斜杠 + 没输完整 ----------
        word = self._command_word()
        visible = False
        if word and hint_dicts:
            exact = any(str(h.get("insert") or "").lower() == word.lower()
                        for h in hint_dicts)
            visible = not exact          # 已经输完整了就不用再提示

        # 只显示和当前输入匹配的那些（"/p" 时不该把别的命令也列出来）
        if visible:
            narrowed = [h for h in hint_dicts
                        if word == "/"
                        or str(h.get("insert") or "").lower().startswith(word.lower())]
            if not narrowed:
                visible = False
            else:
                hint_dicts = narrowed

        # 先清掉旧的
        while self.hint_layout.count():
            item = self.hint_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._hint_widgets = []

        # ⚠️ 不再单独挂一条常驻提示条：这句话交给 "/" 触发的候选面板显示（它本来就在
        #    "有斜杠且没输完整"时出现，位置、宽度、圆角都和原来的提示条一样）。
        #    这样屏幕上只有一个圆角框，不会同一个命令上下显示两遍。
        if not visible:
            bar.hide()
            return

        # 提示条本身保持隐藏（文案已经在候选面板里了）
        bar.hide()

    @staticmethod
    def _hint_label(insert: str, label: str) -> str:
        """提示条的文案："命令 + 空格 + 简短说明"（形如 /plugin AI帮你制作插件）

        ⚠️ 说明里如果已经包含那条命令，就不要再拼一遍，否则会变成 "/plugin 按 /plugin …"。
        """
        insert = str(insert or "").strip()
        label = str(label or "").strip()
        if not insert:
            return label
        if not label:
            return insert
        if insert.lower() in label.lower():
            return label
        return f"{insert} {label}"

    def _hint_visible(self) -> bool:
        bar = getattr(self, "hint_bar", None)
        try:
            return bool(bar is not None and bar.isVisible())
        except Exception:
            return False

    def _insert_hint_text(self, text: str):
        """点提示 → 把那句命令填进输入框（不直接发送，用户还能补参数）"""
        text = str(text or "")
        if not text:
            return
        try:
            current = self.input_edit.toPlainText()
            if current.strip():
                # 输入框里已经有内容：只把命令补在最前面，不冲掉用户打的字
                if not current.lstrip().lower().startswith(text.lower()):
                    self.input_edit.setPlainText(f"{text} {current}")
            else:
                self.input_edit.setPlainText(f"{text} ")
            self.focus_input()
            cursor = self.input_edit.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.input_edit.setTextCursor(cursor)
            self._adjust_input_height()
        except Exception as exc:
            log.err("AI", "chat_hint", f"插入提示失败: {exc}")

    # ================= 输入 "/" 时的命令候选列表 =================
    def _command_word(self) -> str:
        """输入框里正在输入的命令词（不是这个形状就返回空串）

        认的形状：整段文本以 / 开头，并且还没有空格（打完命令就该接参数了）。
        """
        try:
            text = self.input_edit.toPlainText()
        except Exception:
            return ""
        if not text.startswith("/"):
            return ""
        head = text.split("\n", 1)[0]
        if " " in head or "\t" in head:
            return ""
        return head

    def _command_candidates(self) -> list:
        """按当前输入过滤出来的候选命令（每条含 label / insert）"""
        word = self._command_word()
        if not word:
            return []
        try:
            from ..core.ai.chat_hints import get_hint_registry, locale_of
            language = "简体中文"
            try:
                language = self.main_window.language_manager.current_language
            except Exception:
                pass
            items = get_hint_registry().to_dicts(locale_of(language))
        except Exception:
            return []
        needle = word.lower()
        # 可用的候选（先按来源过滤）
        usable = [dict(i) for i in items
                  if self._hint_source_active(i.get("source"))
                  and str(i.get("insert") or "")]
        # ⚠️ 命令打完整了也照样留着，别在用户刚打完的一瞬间把面板抽走（看着像不稳定）。
        #    只有三种情况收起：没有"/"了、打了空格开始写参数、打成别的命令对不上。
        out = []
        for item in usable:
            insert = str(item.get("insert") or "")
            # "/" 阶段全部列出；继续打字就按前缀过滤（含正好打全）
            if needle == "/" or insert.lower().startswith(needle):
                # 面板里的文案 = "命令 + 空格 + 简短说明"
                item["display"] = self._hint_label(insert, str(item.get("label") or ""))
                out.append(item)
        return out

    def _ensure_command_popup(self):
        """懒建候选列表控件（一个圆角小面板 + 竖排的可点条目）"""
        popup = getattr(self, "_command_popup", None)
        if popup is not None and _widget_alive(popup):
            return popup
        popup = QFrame(self)
        popup.setObjectName("aiCommandPopup")
        popup.setFrameShape(QFrame.NoFrame)
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(2)
        popup._layout = layout
        popup._items = []          # [(insert, 控件)]
        popup._active = 0
        popup.hide()
        self._command_popup = popup
        return popup

    @staticmethod
    def _command_item_qss() -> str:
        """候选条目共用的那段 QSS（内边距 + 字号）

        ⚠️ 只此一处产出：整条默认样式和选中样式都调它（避免"面板一套、选中另一套"）；_fit_command_items 量高度用的也是这里的常量。"""
        return (f"padding: {COMMAND_ITEM_PAD_TOP}px 10px "
                f"{COMMAND_ITEM_PAD_BOTTOM}px;"
                f" font-size: {COMMAND_ITEM_FONT_PX}px;")

    def _style_command_popup(self, popup):
        dark = bool(self._dark)
        bg = "#2B2F3C" if dark else "#FFFFFF"
        border = "rgba(255,255,255,0.10)" if dark else "rgba(15,23,42,0.08)"
        text = "#E8EAF0" if dark else "#1F2329"
        popup.setStyleSheet(
            "QFrame#aiCommandPopup {"
            f"  background: {bg};"
            f"  border: 1px solid {border};"
            "   border-radius: 12px;"
            "}"
            f"QLabel {{ color: {text}; background: transparent;"
            f"  border-radius: 8px; {self._command_item_qss()} }}")
        return bg, text

    def _refresh_command_popup(self):
        """按当前输入刷新候选列表；没有候选就收起来"""
        popup = getattr(self, "_command_popup", None)
        candidates = self._command_candidates()
        if not candidates:
            if popup is not None and _widget_alive(popup) and popup.isVisible():
                popup.hide()
            return
        popup = self._ensure_command_popup()
        self._style_command_popup(popup)
        layout = popup._layout
        # 清掉旧的
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        popup._items = []
        for index, info in enumerate(candidates[:6]):
            label = QLabel("", popup)
            label.setCursor(Qt.PointingHandCursor)
            label.setWordWrap(False)
            # ⚠️ 字号必须显式设到控件字体上，不能只靠 QSS 的 font-size：QSS 要等控件
            #    polish 后才落到 font()，而面板高度是显示之前算的，那会儿还是应用字体，
            #    条目高度会虚高一圈（实测 39px vs 真实 29px）。
            _item_font = QFont(label.font())
            _item_font.setPixelSize(COMMAND_ITEM_FONT_PX)
            label.setFont(_item_font)
            # ⚠️ 这里只给一个临时下限，真正的高度在 _fit_command_items 里算
            label.setMinimumHeight(COMMAND_ITEM_MIN_H)
            # ⚠️ 候选项里已经打出来的那一段要染成主题蓝，一眼看出"打到哪了、还差什么"；
            #    用富文本实现（QLabel 支持 Qt.RichText），比自绘简单也不会跑版。
            label.setTextFormat(Qt.RichText)
            label.setText(self._candidate_html(str(info.get("display") or ""),
                                               self._command_word()))
            insert_text = str(info.get("insert") or "")
            label.mouseReleaseEvent = (
                lambda event, t=insert_text: self._accept_command_hint(t))
            layout.addWidget(label)
            popup._items.append((insert_text, label))
        # 先把布局跑一遍，定位时才能算出真高度
        try:
            layout.activate()
        except Exception:
            pass
        # ⚠️ 顺序必须是先 show() 再定位：隐藏状态下布局没真正跑过，高度会偏小，
        #    y = 输入框顶 - 高度 - 6 就会把面板压到输入框上（"一打 /p 它就跑到下面去了"）。
        #    这里先显示 → 布局跑 → 定高定宽 → 摆位置，并在下一拍再摆一次。
        popup._active = 0
        self._highlight_command_item(popup, 0)
        # ⚠️ 定高放在样式贴完之后：量出来的高度和画出来的样式用同一套值（见 _fit_command_items）
        self._fit_command_items(popup)
        popup.show()
        popup.raise_()
        self._position_command_popup(popup)
        QTimer.singleShot(0, lambda p=popup: self._position_command_popup(p))

    def _fit_command_items(self, popup):
        """按最终字体给每条候选定高，保证文字放得下、不被裁

        ⚠️ 高度写死 26px 会把字挤得贴着下边缘（12px 字体 + 上下内边距 12，一行要 29px）；且必须给固定高度而不是只给下限（QSS padding 计入 sizeHint 的口径在不同 Qt 版本上不一致）。"""
        item_h = COMMAND_ITEM_MIN_H
        for _insert, label in getattr(popup, "_items", []):
            try:
                item_h = max(COMMAND_ITEM_MIN_H,
                             QFontMetrics(label.font()).height() + COMMAND_ITEM_PAD_V)
                label.setFixedHeight(item_h)
            except Exception:
                pass
        # 面板定位时要用同一个高度估总高（见 _position_command_popup）
        popup._item_h = item_h
        try:
            popup._layout.activate()
        except Exception:
            pass

    @staticmethod
    def _candidate_html(display: str, typed: str) -> str:
        """候选项的富文本：把用户已经打出来的那段染成主题蓝

        ⚠️ 必须 html.escape（文案来自插件，可能含 < & 这类字符，直接拼进富文本会被当成
        标签）；且只认开头的前缀匹配，不能把文案里别处出现的同样字母也染了。"""
        import html as _html
        display = str(display or "")
        typed = str(typed or "")
        if not display:
            return ""
        head = ""
        tail = display
        # ⚠️ 从第一个字符（那根斜杠）起就染色：只打一个 "/" 时也要有"我对上了"的反馈。
        if typed.startswith("/") and display.lower().startswith(typed.lower()):
            head = display[:len(typed)]
            tail = display[len(typed):]
        if not head:
            return _html.escape(display)
        try:
            from ..interfaces.settings.theme import brand_link_color
            accent = brand_link_color()
        except Exception:
            accent = COLOR_MENTION
        return (f'<span style="color:{accent}; font-weight:600;">'
                f'{_html.escape(head)}</span>{_html.escape(tail)}')

    def _highlight_command_item(self, popup, index: int):
        """把第 index 条高亮（键盘上下键用）"""
        try:
            from ..interfaces.settings.theme import brand_link_color
            accent = brand_link_color()
        except Exception:
            accent = "#5B8DEF"
        items = getattr(popup, "_items", [])
        if not items:
            return
        index = max(0, min(int(index), len(items) - 1))
        popup._active = index
        # ⚠️ 选中项只换底色、不要改 color：候选项是富文本，"已经打出来的那段"是内联
        #    强调色，整条染色会把它盖掉（用户就看不出自己打到哪了）。
        for i, (_insert, label) in enumerate(items):
            try:
                if i == index:
                    label.setStyleSheet(
                        "background: rgba(128,128,128,0.16);"
                        f" border-radius: 8px; {self._command_item_qss()}")
                else:
                    label.setStyleSheet(self._command_item_qss())
            except Exception:
                pass

    def _position_command_popup(self, popup):
        """把候选面板摆在输入区正上方（和输入框等宽）

        ⚠️ 高度用布局的 minimumSize：adjustSize() 常偏小（会把面板叠到输入框上，就是"输入 /p 它跑到下面去了"），sizeHint() 的条目高度是 polish 前按应用字体算的、面板会虚胖。布局还没算好时按"每条自身高度 + 上下留白"估。"""
        try:
            layout = getattr(popup, "_layout", None)
            items = getattr(popup, "_items", [])
            width = max(200, self.input_edit.width())
            # ⚠️ 每条高度用刷新时按字体算出的那个值（popup._item_h），写死 28 在字体
            #    变大时会估矮，把面板压到输入框上。
            item_h = int(getattr(popup, "_item_h", COMMAND_ITEM_MIN_H))
            # panel 自己的上下留白（= 布局的 contentsMargins 6+6，和条目内边距同值）
            estimated = COMMAND_ITEM_PAD_V + max(1, len(items)) * item_h
            height = estimated
            if layout is not None:
                try:
                    height = max(int(layout.minimumSize().height()), estimated)
                except Exception:
                    height = estimated
            popup.setFixedSize(width, height)

            # 锚点：输入区整体的顶边（输入框上面还挂着那条提示条时以它为准）
            anchor = self.input_edit
            hint_bar = getattr(self, "hint_bar", None)
            if hint_bar is not None and hint_bar.isVisible():
                anchor = hint_bar
            top_left = anchor.mapTo(self, QPoint(0, 0))
            y = max(0, top_left.y() - height - 6)
            popup.move(top_left.x(), y)
        except Exception:
            pass

    def _accept_command_hint(self, insert_text: str):
        """选中一条命令：把输入框里的"/xxx"换成这条命令，并收起候选"""
        insert_text = str(insert_text or "")
        if not insert_text:
            return
        try:
            text = self.input_edit.toPlainText()
            rest = text[len(self._command_word()):] if self._command_word() else ""
            self.input_edit.setPlainText(f"{insert_text}{rest}")
            self.focus_input()
            cursor = self.input_edit.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.input_edit.setTextCursor(cursor)
            self._adjust_input_height()
        except Exception as exc:
            log.err("AI", "command_popup", f"填入命令失败: {exc}")
        self._hide_command_popup()

    def _hide_command_popup(self):
        popup = getattr(self, "_command_popup", None)
        if popup is not None and _widget_alive(popup):
            try:
                popup.hide()
            except Exception:
                pass

    def _command_popup_key(self, event) -> bool:
        """候选面板打开时的键盘约定；返回 True = 这个键已经被吃掉

        ↑/↓ 选择、Enter 采纳、Esc 关掉候选（不关整个面板）。
        """
        popup = getattr(self, "_command_popup", None)
        if popup is None or not _widget_alive(popup) or not popup.isVisible():
            return False
        key = event.key()
        if key == Qt.Key_Escape:
            self._hide_command_popup()
            return True
        if key in (Qt.Key_Up, Qt.Key_Down):
            items = getattr(popup, "_items", [])
            if items:
                step = -1 if key == Qt.Key_Up else 1
                self._highlight_command_item(
                    popup, (popup._active + step) % len(items))
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter):
            items = getattr(popup, "_items", [])
            if items:
                self._accept_command_hint(items[popup._active][0])
                return True
        return False

    # ================= 主题 =================
    def _icon_buttons(self) -> list:
        """顶栏图标按钮（基类 apply_theme 会统一给它们上色）

        ⚠️ 必须返回实际按钮：返回空列表的话样式表没人设，深色主题下会继承成浅色文字样式、看着"发白"；内嵌形态没有 close_btn，要过滤掉 None。"""
        return [b for b in (getattr(self, "new_btn", None),
                            getattr(self, "history_btn", None),
                            getattr(self, "close_btn", None)) if b is not None]

    def apply_extra_theme(self, colors: dict):
        """聊天抽屉特有的部件上色（图标、滚动条、输入框、发送按钮、已有气泡）"""
        icon = colors["icon"]
        self.new_btn.setIcon(_svg_icon(ICON_PLUS, icon))
        self.new_btn.setIconSize(QSize(16, 16))
        self.history_btn.setIcon(_svg_icon(ICON_HISTORY, icon))
        self.history_btn.setIconSize(QSize(16, 16))

        self.divider.setStyleSheet(f"background: {colors['divider']}; border: none;")
        self.input_divider.setStyleSheet(f"background: {colors['divider']}; border: none;")

        self.scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QWidget#qt_scrollarea_viewport {{ background: transparent; }}
            QScrollBar:vertical {{ background: transparent; width: 6px; margin: 0; }}
            QScrollBar::handle:vertical {{
                background: rgba(128,128,128,0.35); border-radius: 3px; min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{ background: rgba(128,128,128,0.55); }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
        """)
        self.message_host.setStyleSheet("background: transparent;")

        self.input_edit.setStyleSheet(f"""
            QTextEdit {{
                background: {colors['input_bg']};
                color: {colors['text']};
                border: 1px solid {colors['input_border']};
                border-radius: 10px;
                padding: 8px 10px;
                font-size: 13px;
            }}
            QTextEdit:focus {{ border: 1px solid {brand_link_color()}; }}
            QScrollBar:vertical {{ background: transparent; width: 5px; }}
            QScrollBar::handle:vertical {{ background: rgba(128,128,128,0.35); border-radius: 2px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        self._style_send_buttons(self.send_btn, busy=self._busy)

        # 已有气泡的配色也跟着换
        for bubble in self.message_host.findChildren(ChatBubble):
            bubble.apply_theme(self._dark)

        # 历史抽屉的配色也跟着走
        if self.history_drawer is not None:
            self.history_drawer.apply_theme(self._dark)

    def apply_theme(self, dark: bool = None):
        """按当前深浅色重新上色（主窗口切主题后要调一次）

        公共部分（容器背景、标题、图标按钮）由 BaseDrawer 处理，聊天抽屉特有的部件在 apply_extra_theme 里处理。"""
        super().apply_theme(dark)
        # 图标按钮的样式表由基类统一设置，这里只需要补上各自的图标
        self.new_btn.setIcon(_svg_icon(ICON_PLUS, self._theme_colors()["icon"]))
        self.history_btn.setIcon(_svg_icon(ICON_HISTORY, self._theme_colors()["icon"]))
        # ⚠️ 命令候选面板和指令高亮是按主题色临时上色的（内联样式表），切主题不重刷
        #    会留在旧配色上（深色切浅色时那句蓝字看不清）。
        try:
            popup = getattr(self, "_command_popup", None)
            if popup is not None and _widget_alive(popup) and popup.isVisible():
                self._style_command_popup(popup)
                self._highlight_command_item(popup, getattr(popup, "_active", 0))
            highlighter = getattr(self, "_command_highlighter", None)
            if highlighter is not None:
                highlighter.rehighlight()
        except Exception:
            pass

    def _style_send_buttons(self, button: QPushButton, busy: bool = False):
        """发送 / 停止按钮的样式（busy=True 时是"停止"态，用灰色）"""
        if busy:
            button.setStyleSheet(f"""
                QPushButton {{
                    background: {"rgba(255,255,255,0.10)" if self._dark else "rgba(0,0,0,0.08)"};
                    color: {"#E8EAF0" if self._dark else "#1F2329"};
                    border: none; border-radius: 9px;
                }}
                QPushButton:hover {{ background: rgba(245,108,108,0.18); color: #F56C6C; }}
            """)
        else:
            # 发送按钮：品牌渐变（跟随"组件配色"档位，见 settings/theme.py）
            from ..interfaces.settings.theme import brand_gradient_qss
            button.setStyleSheet(f"""
                QPushButton {{
                    background: {brand_gradient_qss()};
                    color: #FFFFFF; border: none; border-radius: 9px;
                }}
                QPushButton:hover {{
                    background: {brand_gradient_qss(hover=True)};
                }}
                QPushButton:pressed {{
                    background: {brand_gradient_qss(pressed=True)};
                }}
            """)

    def refresh_texts(self):
        """语言切换后刷新这里的文案（程序切语言会重启，所以主要给启动时用）"""
        self.input_edit.setPlaceholderText(self._t("ai_input_placeholder"))
        if not self._busy:
            self.send_btn.setText(self._t("ai_send"))
        self.new_btn.setToolTip(self._t("ai_new_chat"))
        self.history_btn.setToolTip(self._t("ai_history"))
        if self.close_btn is not None:
            self.close_btn.setToolTip(self._t("ai_close_drawer"))

    # ================= 开关（覆盖基类的钩子） =================
    def on_open(self):
        """滑出后：藏起悬浮球、恢复上次的滚动位置、聚焦输入框

        ⚠️ 不能无条件跳到底部：同一个会话（没换过对话）要恢复关闭前记下的滚动值，没有记录才滚到底部；滚动值是 on_close 里存的。"""
        self._sync_ball(False)
        QTimer.singleShot(60, self.focus_input)
        # 插件登记的"命令提示"可能刚变化（比如刚打开插件），这里对一次
        try:
            self._refresh_chat_hints()
        except Exception:
            pass
        # ⚠️ 先接上另一份 AI 界面正在聊的那段对话（见 _SHARED_SESSION_ATTR）；
        #    接过来了就不恢复旧滚动位置 —— 那是新内容，该看到最新的。
        adopted = self.sync_shared_session()
        # 只有在"还是关闭前那个会话"时才恢复滚动位置；换了对话就该从头看到最新
        same_session = (not adopted
                        and self._remember_session is not None
                        and self.session is not None
                        and self.session.id == self._remember_session)
        if self._remember_scroll is not None and same_session:
            QTimer.singleShot(0, self._restore_scroll)
        else:
            QTimer.singleShot(0, self._scroll_to_bottom)

    def on_close(self):
        """收起时：摘掉"点外面关闭"的守卫、记住滚动位置、作废请求、把悬浮球放回来

        球是重新打开抽屉的唯一入口，收起后必须让它出现。⚠️ 放在抽屉自己的开关钩子里、而不是让主窗口做：抽屉还能被 Ctrl+Caps 打开或被 Esc 关掉。"""
        # 先摘掉"点外面就关闭"的守卫（不然收起途中的鼠标事件又会触发一次关闭）
        self._remove_outside_close()
        # 收起抽屉 = 结束这次重写：不留一条开着编辑框（而且已经不可见）的气泡，
        # 下次打开又是"待发送"的状态，会给用户一种"我刚改的东西还在"的错觉。
        # ⚠️ 气泡在这时候还活着（deleteLater 要等事件循环），所以这里退出是安全的。
        self._cancel_inline_edit()
        # 再记滚动位置：_restore_ball_if_enabled 是延时回调，那时控件可能已经隐藏、值不可靠
        try:
            self._remember_scroll = self.scroll.verticalScrollBar().value()
            self._remember_session = self.session.id if self.session else None
        except Exception:
            self._remember_scroll = None

        if _worker_running(self.worker):
            self.worker.cancel()
        # 历史对话页跟着一起收，免得下次打开聊天时它还盖在上面
        if self.history_drawer is not None and self.history_drawer.is_open():
            self.history_drawer.close_drawer()
        # 等滑动动画收完再放球，否则球会在抽屉滑走的半路上冒出来。
        # ⚠️ 必须重新读一次 ai_enabled：关开关时程序会顺手收起抽屉，无脑放球会出现
        # "功能已经关了，球还在"的矛盾状态。
        QTimer.singleShot(SLIDE_DURATION_MS + 20, self._restore_ball_if_enabled)

    def open_drawer(self):
        """滑出聊天抽屉（并装上"点窗口内其它位置就自动关闭"的守卫）"""
        super().open_drawer()
        # ⚠️ 守卫必须在滑出之后才装：它是全局事件过滤器，装在打开它的那一下点击之前
        #    会立刻把刚开的面板又关掉。
        self._install_outside_close()

    def _restore_scroll(self):
        """把滚动条放回关闭前的位置"""
        stop_smooth_scroll(self.scroll)
        bar = self.scroll.verticalScrollBar()
        bar.setValue(max(bar.minimum(), min(int(self._remember_scroll or 0),
                                            bar.maximum())))

    def _restore_ball_if_enabled(self):
        """把球放回来 —— 前提是 GCP-AI 还开着"""
        enabled = True
        try:
            enabled = bool(self.main_window.settings_manager.settings.get(
                "ai_enabled", False))
        except Exception:
            pass
        if enabled:
            self._sync_ball(True)

    def _sync_ball(self, visible: bool):
        """通知主窗口显示/隐藏悬浮球（主窗口是它 owner，由它决定最终状态）

        ⚠️ 内嵌形态不碰悬浮球：它没有"打开/收起"这回事，而侧边栏 AI 模式本身就把球永久藏起来了（ai_sidebar_mode），再碰只会和主窗口的状态打架。"""
        if self._embedded:
            return
        window = self.main_window
        if window is not None and hasattr(window, "_set_ai_ball_visible"):
            try:
                window._set_ai_ball_visible(visible)
            except Exception as exc:
                log.err("AI", "ball", f"切换悬浮球失败: {exc}")

    # ---------- 点界面内其它位置 → 自动关闭（需求） ----------
    def _install_outside_close(self):
        """在本程序窗口里点"抽屉以外"的任意位置，就自动收起抽屉

        ⚠️ 用全局事件过滤器而不是 WindowDeactivate：抽屉是主窗口的子控件，永远不会"失活"，
        没有 deactivate 事件可用；装到 QApplication 上能覆盖主窗口任意角落。
        ⚠️ 必须放行悬浮球（点它走"球的点击 → 开关抽屉"的正常逻辑）和顶层弹窗（历史抽屉、
        RoundMenu、InfoBar、右键菜单）—— 它们不是本抽屉子控件，但点了不算"点了外面"。"""
        app = QApplication.instance()
        if app is None or getattr(self, "_outside_filter_installed", False):
            return
        app.installEventFilter(self)
        self._outside_filter_installed = True

    def _remove_outside_close(self):
        app = QApplication.instance()
        if app is None or not getattr(self, "_outside_filter_installed", False):
            return
        app.removeEventFilter(self)
        self._outside_filter_installed = False

    def _is_inside_drawer(self, widget) -> bool:
        """这个控件是不是"抽屉自己"（含它的子控件）

        ⚠️ 只能用 isAncestorOf 判断层级，不能用 widget.window() is self.window()：抽屉本身就是主窗口的子控件，那样写会让所有控件都被判成"在抽屉里"、永远不触发自动关闭。"""
        if widget is None:
            return False
        if widget is self:
            return True
        try:
            return self.isAncestorOf(widget)
        except Exception:
            return False

    def _is_ai_ball(self, widget) -> bool:
        """是不是 AI 悬浮球（点它要放行，见 _install_outside_close 的说明）"""
        ball = getattr(self.main_window, "ai_floating_button", None)
        if ball is None or widget is None:
            return False
        if widget is ball:
            return True
        try:
            return ball.isAncestorOf(widget)
        except Exception:
            return False

    def _escape_stack(self) -> list:
        """Esc 要按"从上到下"看这一摞抽屉：历史页（如果开着）在前，聊天页在后"""
        return ([self.history_drawer] if self.history_drawer is not None else []) + [self]

    def _on_escape(self):
        """聊天抽屉这一层的 Esc：编辑中只取消编辑、不关抽屉，否则收起面板

        Esc 是从 QApplication 上的过滤器进来的（和焦点无关），所以这里必须自己判一次，不能只靠内联编辑框那个 keyPress 过滤器。"""
        bubble = getattr(self, "_inline_edit_bubble", None)
        if bubble is not None and _widget_alive(bubble):
            self._cancel_inline_edit()
            log.op("AI", "escape", what="取消内联编辑")
            return
        self.close_drawer()

    # ================= 会话 =================
    def _mention_to_html(self, text: str) -> str:
        """（兼容旧调用点）转 @ 提及的实现在模块级 _mentions_to_html 里"""
        return _mentions_to_html(text)

    def _load_startup_session(self):
        """启动时的会话：每次都新开一个空对话（历史对话走顶栏历史按钮切回来）

        ⚠️ 例外：共享槽里已经有一段"正在聊"的会话时接过来（见 _SHARED_SESSION_ATTR）—— 侧栏整页 AI 是懒建的，用户先在悬浮球那边聊过，它必须显示同一段对话。"""
        shared = shared_ai_session(self.main_window)
        if shared is not None and getattr(shared, "id", ""):
            self.session = shared
            self._render_session()
            return
        self.session = self.store.new_session()
        self._publish_session()
        self._render_session()

    def _render_session(self):
        """把当前会话的消息全部渲染出来（切会话 / 载入历史时调用）

        渲染时给每条气泡标上它在 session.messages 里的下标。⚠️ 版本页要从消息本身读（_variants_of），不要读 self._variants 那个内存缓存：刚从历史载入时它是空的。"""
        self._clear_messages()
        if self.session is None or not self.session.messages:
            # ⚠️ 空会话一条气泡都不加（不要欢迎语）：新对话就是干净的空消息区
            pass
        else:
            for index, message in enumerate(self.session.messages):
                # 历史里的 @ 提及落盘时是纯文本 @名称(TG-000001)，显示前转成富文本
                raw = str(message.get("content", "") or "")
                bubble = self._add_bubble(self._mention_to_html(raw),
                                          is_user=message.get("role") == ROLE_USER,
                                          index=index)
                # 有多个版本时按消息里记的那一版显示（磁盘才是真源）
                variants = self._variants_of(index)
                if variants and len(variants) > 1:
                    page = self._active_variant_of(index)
                    self._variant_active[index] = page
                    bar = bubble.actions
                    if bar is not None:
                        bar.set_page(page, len(variants))
                    if variants[page] != raw:
                        bubble.set_text(self._mention_to_html(variants[page]))
        self._update_title()
        # 记下"界面上这串气泡对应的是哪个版本的内容"（见 sync_shared_session）
        self._render_fingerprint = self._session_fingerprint()
        QTimer.singleShot(30, self._scroll_to_bottom)

    # ================= 两个 AI 界面之间的交接（共享会话） =================
    def _session_fingerprint(self):
        """当前会话内容的指纹：判断"我藏起来这段时间里，另一边改过它没有"

        ⚠️ 不能只比会话 id：两份面板共享的是同一个 ChatSession 对象，追加消息时对象和 id 都没换，但界面上的气泡已经过期，所以还要带上"条数 + 每条正文的哈希"。"""
        session = self.session
        if session is None:
            return None
        messages = session.messages or []
        return (
            str(getattr(session, "id", "") or ""),
            len(messages),
            tuple((str(m.get("role") or ""), hash(str(m.get("content") or "")))
                  for m in messages if isinstance(m, dict)),
            str(getattr(session, "updated_at", "") or ""),
        )

    def _publish_session(self):
        """把当前会话登记到主窗口的共享槽（另一份 AI 界面显示时会接过去）"""
        try:
            publish_ai_session(self.main_window, self.session)
        except Exception:
            pass

    def _install_session(self, session):
        """立刻接管某段会话（作废在飞的请求 + 清干净临时状态 + 重画）

        和 load_session() 的区别：这里不读盘（会话对象已经在手上），也不亮加载遮罩 —— 它就是"把另一边的会话接过来"。"""
        if _worker_running(self.worker):
            self.worker.cancel()
            self._set_busy(False)
        try:
            self._thinking_timer.stop()
        except Exception:
            pass
        self._placeholder_bubble = None
        self._regen_index = None
        self._reset_variants()
        self.session = session
        self._render_session()
        self._publish_session()

    def _adopt_shared_session(self) -> bool:
        """接上"另一份 AI 界面正在聊的那段对话"；返回是否重画过

        两种情况都重画：共享槽换成了另一个会话对象（对面点了＋新对话 / 载入了历史），或者还是同一个对象但内容变过（对面刚发了一轮）。⚠️ 触发时机是"自己被显示出来"，不是拨开关那一下。"""
        try:
            shared = shared_ai_session(self.main_window)
        except Exception:
            shared = None
        if shared is not None and shared is not self.session:
            self._install_session(shared)
            return True
        if self.session is not None \
                and self._session_fingerprint() != self._render_fingerprint:
            self._render_session()
            return True
        return False

    def sync_shared_session(self) -> bool:
        """外部（内嵌形态的侧栏页）在"被显示出来"时调一次

        见 _adopt_shared_session；包一层把异常挡在里面 —— 交接失败最多是这段对话没接过来，绝不能把切页 / 滑出打断。"""
        try:
            return bool(self._adopt_shared_session())
        except Exception as exc:
            log.err("AI", "sync_session", f"接上另一份 AI 界面的对话失败: {exc}")
            return False

    def _reset_variants(self):
        """换会话时清掉版本记录和"记住的滚动位置"（on_open 于是会滚到最新）

        ⚠️ 顺手退出内联编辑态：正在编辑的那条气泡已经被 _render_session 销毁，留着 _edit_index 会在下一次发送时去改一条别的消息（下标对不上）。"""
        self._cancel_inline_edit()
        self._variants = {}
        self._variant_active = {}
        self._edit_index = None
        self._regen_index = None
        self._remember_scroll = None
        self._remember_session = None
        # 换会话 = 换上下文：智能体那一轮的临时记录必须清掉
        self._agent_scratch = []
        self._agent_round = 0
        self._agent_pending_regen = None
        self._agent_activity = []

    def _update_title(self):
        model = ""
        try:
            model = str(self.main_window.settings_manager.settings.get("model_name", "") or "")
        except Exception:
            pass
        self.title_label.setText(model.strip() or "GCP-AI")

    def new_chat(self):
        """顶栏 ＋：开一个新对话"""
        if _worker_running(self.worker):
            self.worker.cancel()
            self._set_busy(False)
        self._reset_variants()
        self.session = self.store.new_session()
        # 新对话要登记进共享槽：侧栏那整页 AI 再打开时接的就是这个新对话
        self._publish_session()
        self._render_session()
        self.focus_input()

    def load_session(self, session_id: str) -> bool:
        """从历史列表载入某个会话，返回是否真的载入成功

        ⚠️ 载入前必须作废正在飞的请求：_on_reply 是往 self.session 里写的，那会儿 session 已经
        换成刚点开的那一个了，旧对话的回答会被塞进新对话（作废 + 记住"这条请求属于哪个会话"
        两道一起上）。
        ⚠️ 返回值给历史抽屉判断"要不要退回聊天页"：失败也退回的话，用户想重试还得重新打开
        历史、重新等列表。"""
        if _worker_running(self.worker):
            self.worker.cancel()
            self._placeholder_bubble = None
            self._regen_index = None
            self._set_busy(False)
        # ⚠️ 顺手停掉"正在思考"的定时器：占位气泡马上会被 _render_session 删掉，
        #    定时器还活着就会每隔 420ms 去摸一个已经没了的控件。
        try:
            self._thinking_timer.stop()
        except Exception:
            pass
        self._placeholder_bubble = None
        # GCP-AI Agent 那一轮的临时上下文也要清掉，否则会把上个对话的工具结果带进新对话
        self._agent_scratch = []
        self._agent_round = 0

        loaded = self.store.load(session_id)
        if loaded is None:
            # 再读一次：极少数情况下第一次读正好撞上 os.replace 在换文件。
            loaded = self.store.load(session_id)
        if loaded is None:
            log.err("AI", "load_session", f"载入失败（读不到或 json 坏了）: {session_id}")
            self._info(self._t("ai_history_load_failed"))
            return False
        if not loaded.messages:
            # 文件在但一条消息都没有：载进去只看得到空白，和"点了没反应"没区别
            log.err("AI", "load_session", f"载入失败（会话里没有消息）: {session_id}")
            self._info(self._t("ai_history_load_failed"))
            return False

        self._reset_variants()
        self.session = loaded
        # 载入的历史对话也是"当前正在聊的"：另一份 AI 界面切过去时要显示同一段
        self._publish_session()
        # ⚠️ 渲染几十条消息要几百毫秒到一秒多，同步做完加载动画根本没机会画出来
        #    （主线程被占着）：先把遮罩亮出来 → 渲染推迟到下一拍事件循环 → 再收掉。
        self._show_chat_loading(True)
        QTimer.singleShot(0, self._render_loaded_session)
        log.op("AI", "load_session", id=session_id, messages=len(loaded.messages))
        return True

    def _render_loaded_session(self):
        """真正把刚载入的会话画出来（见 load_session 里为什么要推迟一拍）"""
        try:
            # ⚠️ 载入时就把坏的版本数据修好并落盘（见 _variants_of）：正文不在版本
            #    列表里的话，前后版 UI 是错的。
            self._repair_variants(save=True)
            self._render_session()
        except Exception as exc:
            log.err("AI", "load_session", f"渲染会话失败: {exc}")
        finally:
            self._show_chat_loading(False)

    def _repair_variants(self, save: bool = False):
        """把整个会话的版本数据过一遍（发现"正文不在版本表里"就补上）

        _variants_of() 里的修复是惰性的（谁读谁修），这里主动扫一遍让刚载入的历史立刻拿到正确的版本数；save=True 时把修好的结果写回磁盘。"""
        if self.session is None:
            return 0
        self._variants_repaired = False
        for index in range(len(self.session.messages)):
            try:
                self._variants_of(index)
            except Exception:
                continue
        repaired = 1 if getattr(self, "_variants_repaired", False) else 0
        if repaired and save:
            try:
                self.store.save(self.session)
                log.op("AI", "variants_repaired", id=self.session.id)
            except Exception:
                pass
        return repaired

    def open_history(self):
        """顶栏 🕘：滑出历史对话抽屉（独立页面，盖在聊天抽屉上面）

        ⚠️ 这里不再显式 refresh()：抽屉的 on_open() 里已经会刷一次，两边都刷会让列表刚画出来又被整体重建，用户正好在中间点卡片时那一下点击会凭空消失。"""
        if self.history_drawer is None:
            self.history_drawer = AIHistoryDrawer(self.main_window, self)
        self.history_drawer.sync_geometry()
        self.history_drawer.show()
        self.history_drawer.raise_()
        self.history_drawer.open_drawer()      # 内部会 on_open() → refresh()
        self.history_drawer.raise_()

    def _delete_session(self, session_id: str):
        """删除一个历史对话"""
        self.store.delete(session_id)
        # 删掉的正好是当前会话 → 换一个新对话
        if self.session is not None and self.session.id == session_id:
            self.session = self.store.new_session()
            # 新对话也要登记进共享槽（否则另一份 AI 界面还接着那个已经删掉的会话）
            self._publish_session()
            self._render_session()
        if self.history_drawer is not None:
            self.history_drawer.refresh()
        self._info(self._t("ai_deleted"))

    # ================= 消息渲染 =================
    def _clear_messages(self):
        """清空消息区，然后按当前形态补回弹簧

        ⚠️ 必须先把所有 item（含弹簧）都取出来，再补一个弹簧：在循环里把取到的弹簧又加回
        布局会让 count() 永不归零、死循环卡死。抽屉形态弹簧在最前，页面形态在最后。"""
        while self.message_layout.count():
            item = self.message_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # ⚠️ 必须先 hide() 再 deleteLater()：只从布局里摘掉的话控件还是父控件的
                #    可见子对象，会停在旧位置一直画到 deleteLater 真正执行 —— 整屏重排
                #    （切会话、切分支、翻版本）时就是"新旧两屏气泡叠在一起"。
                widget.hide()
                widget.deleteLater()
            # 弹簧直接丢：下面按形态重新加一个
        if self._embedded_layout:
            self.message_layout.addStretch(0)
        else:
            self.message_layout.addStretch(1)

    def _add_bubble(self, text: str, is_user: bool, index: int = None,
                    actions: bool = True) -> ChatBubble:
        """加一条气泡（插在弹簧之前）

        index 是这条消息在 session.messages 里的下标，版本翻页全靠它；actions=False 用于不是真实消息的气泡（不该有操作栏）。"""
        bubble = ChatBubble(text, is_user, self._dark,
                            link_handler=self._on_link_clicked,
                            actions=actions, parent=self.message_host,
                            max_width=self._bubble_width())
        if self._embedded_layout:
            # 页面形态：弹簧在末尾，新气泡要插在它前面（count-1）
            self.message_layout.insertWidget(self.message_layout.count() - 1, bubble)
        else:
            # 抽屉形态：弹簧在最前面（index 0，负责把气泡压到底部），新气泡追加到末尾。
            # ⚠️ 用 insertWidget(-1) 明确表示追加，不要用 count-1（会插到弹簧前面）
            self.message_layout.insertWidget(-1, bubble)
        bubble._message_index = index
        if actions:
            self._wire_bubble_actions(bubble)
        # 正文的右键菜单（复制 / 全选），与操作栏无关
        self._wire_bubble_context_menu(bubble)
        # ⚠️ 造完先按内容收紧一次宽度（短句贴身、长句到上限），并把"消息区一整行的
        #    宽度"给它（用户气泡靠右靠的就是这个）。
        bubble.apply_max_width(self._bubble_width(), self._row_width())
        bubble._apply_bubble_width()
        return bubble

    def _row_width(self) -> int:
        """消息区"一整行"的可用宽度（气泡控件本体要占满它，内部再靠左/靠右）"""
        try:
            viewport = self.scroll.viewport().width()
        except RuntimeError:
            return 0
        if viewport <= 0:
            return 0
        return max(1, viewport - 28)          # 28 = message_layout 左右内边距 14 + 14

    def _wire_bubble_actions(self, bubble: ChatBubble):
        """接上气泡操作栏的四个按钮

        ⚠️ 用默认参数把 bubble 绑死（闭包陷阱）；气泡销毁后回调仍可能被触发，所以处理函数里都要判活。"""
        bar = bubble.actions
        if bar is None:
            return
        bar.copy_requested.connect(lambda b=bubble: self._copy_bubble(b))
        bar.edit_requested.connect(lambda b=bubble: self._edit_bubble(b))
        bar.sync_requested.connect(lambda b=bubble: self._sync_bubble(b))
        bar.page_changed.connect(lambda page, b=bubble: self._switch_variant(b, page))
        self._refresh_pager(bubble)

    # ================= 气泡的右键菜单（复制 / 全选） =================
    def _wire_bubble_context_menu(self, bubble: ChatBubble):
        """给气泡正文挂上右键菜单的处理函数（见 _bubble_context_menu）"""
        try:
            bubble.label._context_handler = (
                lambda label, pos, b=bubble: self._bubble_context_menu(b, label, pos))
        except Exception:
            pass

    def _bubble_context_menu(self, bubble: ChatBubble, label, global_pos):
        """气泡右键：只出现"复制"和"全选"

        右键时若没有手动选中任何东西，就当场把正文全部框选（"全选"置灰）；已经手动选了一部分则保持用户的选择不动，两项都可用。"""
        if bubble is None or not _widget_alive(bubble) or label is None:
            return
        if RoundMenu is None or MenuAction is None:
            return
        try:
            plain = bubble.plain_text()
            try:
                manual = bool(label.hasSelectedText())
            except Exception:
                manual = False
            if not manual:
                label.setSelection(0, len(plain))
            menu = RoundMenu(parent=bubble)
            # ⚠️ 键名必须是 menu_copy / menu_select_all（settings 模块里的键）：
            #    写成 ai_menu_* 查不到就会**把键名原样显示出来**。
            copy_action = MenuAction(self._t("menu_copy"), menu)
            copy_action.triggered.connect(lambda: self._copy_text(plain))
            menu.addAction(copy_action)
            all_action = MenuAction(self._t("menu_select_all"), menu)
            # 已经全选了就置灰（用户手动选了一部分才可用）
            all_action.setEnabled(bool(manual))
            all_action.triggered.connect(lambda: label.setSelection(0, len(plain)))
            menu.addAction(all_action)
            menu.exec(global_pos, ani=True)
        except Exception as exc:
            log.err("AI", "bubble_menu", f"气泡右键菜单失败: {exc}")

    def _copy_text(self, text: str):
        """把一段文字放进剪贴板（右键菜单的"复制"用）"""
        try:
            QApplication.clipboard().setText(str(text or ""))
            log.op("AI", "copy_bubble_menu")
        except Exception as exc:
            log.err("AI", "copy", f"复制失败: {exc}")

    # ================= 版本（编辑 / 重新生成） =================
    def _variants_of(self, index: int) -> list:
        """取某个位置的版本列表（[0] 是磁盘上那份原始内容）

        ⚠️ 版本列表存进消息本身（message["variants"]）而不是只放内存：只在内存里的话落盘的永远只有当前选中那一版，重新加载对话时别的版本就"消失"了。"""
        if self.session is None or index is None:
            return []
        if not (0 <= index < len(self.session.messages)):
            return []
        message = self.session.messages[index]
        stored = message.get("variants")
        if isinstance(stored, list) and stored:
            variants = [str(v or "") for v in stored]
            # ⚠️ 修历史坏数据：老版本"编辑后发送"只改 content、没同步 variants，
            #    正文不在版本列表里 —— 一翻页就跳回旧内容，看着像"这一版丢了"。
            #    发现不一致就把当前正文补成最后一版。
            current = str(message.get("content") or "")
            if current and current not in variants:
                variants.append(current)
                message["variants"] = list(variants)
                message["variant_index"] = len(variants) - 1
                # 标记一下：调用方（load_session）据此决定要不要落盘修好它
                self._variants_repaired = True
        else:
            variants = [str(message.get("content") or "")]
            message["variants"] = variants
            message["variant_index"] = 0
        # 内存缓存只作为"跨会话快速查表"用，真源永远是 message
        self._variants[index] = variants
        return variants

    def _active_variant_of(self, index: int) -> int:
        """这个位置当前显示第几版（从消息里读，缺省取最后一版）"""
        if self.session is None or index is None \
                or not (0 <= index < len(self.session.messages)):
            return 0
        message = self.session.messages[index]
        try:
            value = int(message.get("variant_index", 0))
        except (TypeError, ValueError):
            value = 0
        count = len(self._variants_of(index))
        return max(0, min(value, max(0, count - 1)))

    def _set_variant(self, index: int, variant_index: int):
        """切换某个位置显示的版本，并把内容写回会话 + 落盘

        版本列表和"当前第几版"都写进消息里，所以重新加载对话之后还能继续翻页。⚠️ 只处理 AI 消息：用户消息翻页意味着换一整条分支（下面的 AI 回复也要跟着换）。"""
        variants = self._variants_of(index)
        if not variants or not (0 <= variant_index < len(variants)):
            return
        self._variant_active[index] = variant_index
        content = variants[variant_index]

        if 0 <= index < len(self.session.messages):
            message = self.session.messages[index]
            message["content"] = content
            message["variants"] = list(variants)
            message["variant_index"] = variant_index
            self.store.save(self.session)

        # 只更新这一个气泡的文字，不重排整个列表（重排会闪）
        for bubble in self.message_host.findChildren(ChatBubble):
            if getattr(bubble, "_message_index", None) == index:
                bubble.set_text(self._mention_to_html(content))
                bubble.refresh_size()
                self._refresh_pager(bubble)
                break

    # ================= 分支：用户 edit 的兄弟版本 + 各自的下游 =================
    def _ensure_branches(self, index: int):
        """取出/补齐某个用户消息的"分支后缀表"，返回 (variants, branches)

        用户消息的每个编辑版本都要带着自己那一串 AI 回复：只做"前后版"是不够的，切到 edit2
        时下面挂的必须是 edit2 的那串回复。
        做法：session.messages 永远就是当前显示的那条线（下标逻辑原样成立），每个用户消息额外
        带一份 branch_suffixes（第 k 项 = 第 k 个版本后面原本挂着的消息）；切换时先把当前后缀
        存回原项、再把目标项深拷贝放出来（独立副本，互不影响）。"""
        if self.session is None or index is None:
            return None, None
        if not (0 <= index < len(self.session.messages)):
            return None, None
        message = self.session.messages[index]
        if message.get("role") != ROLE_USER:
            return None, None
        variants = self._variants_of(index)
        stored = message.get(BRANCH_KEY)
        branches = list(stored) if isinstance(stored, list) else []
        # 版本表变了（新增/删除）就跟着对齐：多的截掉、少的补 None
        branches = branches[:len(variants)]
        while len(branches) < len(variants):
            branches.append(None)
        message[BRANCH_KEY] = branches
        return variants, branches

    def _save_branch_suffix(self, index: int, branch_index: int):
        """把"当前这条线"在 index 之后的消息存进第 branch_index 个分支"""
        variants, branches = self._ensure_branches(index)
        if branches is None:
            return
        if 0 <= branch_index < len(branches):
            branches[branch_index] = copy.deepcopy(self.session.messages[index + 1:])

    def _restore_branch_suffix(self, index: int, branch_index: int):
        """把第 branch_index 个分支的后继放出来（替换掉 index 之后的全部消息）"""
        variants, branches = self._ensure_branches(index)
        suffix = None
        if branches is not None and 0 <= branch_index < len(branches):
            suffix = branches[branch_index]
        del self.session.messages[index + 1:]
        if isinstance(suffix, list):
            self.session.messages.extend(copy.deepcopy(suffix))

    def _switch_user_branch(self, index: int, variant_index: int) -> bool:
        """把某条用户消息切到第 variant_index 个编辑版本，**连同它下面的 AI 回复**

        顺序很关键：先存后取。反过来的话，当前这支的后继会在"取目标分支"那一步被整个丢掉 —— 用户切过去再切回来就发现原来的 AI 回复不见了。"""
        variants, branches = self._ensure_branches(index)
        if not variants or not (0 <= variant_index < len(variants)):
            return False
        current = self._active_variant_of(index)
        if variant_index == current:
            return False

        self._save_branch_suffix(index, current)

        message = self.session.messages[index]
        message["content"] = variants[variant_index]
        message["variants"] = list(variants)
        message["variant_index"] = variant_index

        self._restore_branch_suffix(index, variant_index)
        self.store.save(self.session)
        # ⚠️ 这里必须**整屏重排**（不能只换那一条气泡）：下面的 AI 回复整段都换了，
        #    逐条改反而更慢、还容易漏。
        self._render_session()
        log.op("AI", "switch_user_branch", index=index, variant=variant_index)
        return True

    def _refresh_pager(self, bubble: ChatBubble):
        """刷新气泡操作栏上的页码显示"""
        bar = bubble.actions
        if bar is None:
            return
        index = getattr(bubble, "_message_index", None)
        variants = self._variants_of(index) if index is not None else []
        count = max(1, len(variants))
        # ⚠️ 当前第几版从消息里读（_active_variant_of）：重载对话后内存 map 是空的，
        #    猜出来的页码会和正文对不上。
        page = self._active_variant_of(index) if index is not None else 0
        bar.set_page(page, count)

    def _switch_variant(self, bubble: ChatBubble, page: int):
        """操作栏上翻页：AI 消息换回答版本，用户消息换整条分支

        ⚠️ 两条路必须分开：AI 气泡翻页只换这条回答（_set_variant）；用户气泡翻页 = 换一个"我说的话"，它下面那串 AI 回复整段一起换（_switch_user_branch）。"""
        index = getattr(bubble, "_message_index", None)
        if index is None or self.session is None:
            return
        if not (0 <= index < len(self.session.messages)):
            return
        # 翻页会让下标重排，正在原地编辑的那条气泡必须先收掉
        self._cancel_inline_edit()
        if self.session.messages[index].get("role") == ROLE_USER:
            self._switch_user_branch(index, page)
            return
        variants = self._variants_of(index)
        if not variants or not (0 <= page < len(variants)):
            return
        self._set_variant(index, page)

    def _update_edit_split(self):
        """（保留的兼容入口）把"用户重写过的那条"之后的内容裁掉

        ⚠️ 现在没有任何地方调它：分支化之后"裁掉后继"由 _save_branch_suffix（存进旧分支）+ _apply_edit（新分支从空开始）完成，旧后继不会丢。"""
        self._cancel_inline_edit()
        index = self._edit_index
        if self.session is None or index is None:
            return
        if 0 <= index < len(self.session.messages):
            del self.session.messages[index + 1:]
            self.store.save(self.session)
        self._edit_index = None
        self._render_session()

    def _copy_bubble(self, bubble: ChatBubble):
        """复制按钮：把气泡内容（纯文本）放进剪贴板

        成功后让按钮进入"已复制"的 2 秒反馈态（计时器以那条操作栏为父对象，气泡销毁时一起没）。⚠️ 气泡正在编辑时这个按钮的职责是 ✓ accept，信号仍是同一个 copy_requested。"""
        if bubble is not None and _widget_alive(bubble) and bubble.is_editing():
            self._inline_edit_accept(bubble)
            return
        text = bubble.plain_text()
        try:
            QApplication.clipboard().setText(text)
        except Exception as exc:
            log.err("AI", "copy", f"复制失败: {exc}")
            return
        bar = bubble.actions
        if bar is not None and _widget_alive(bar):
            bar.set_copy_done()

    # ================= 内联编辑（气泡原地变输入框） =================
    def _edit_bubble(self, bubble: ChatBubble):
        """编辑按钮：把这条用户气泡自己变成输入框（原地，不是塞回主输入框）

        记下 _edit_index（accept 时要靠它触发"重写"那套裁剪 + 重新请求），并让那条气泡进编辑态
        （正文换成 QTextEdit、两个按钮换成 close/accept）。
        ⚠️ 这个按钮是个开关：进编辑态后它显示 close，再点一次是"取消"而不是又进一遍编辑（那会
        把用户刚打的字冲掉）；同时只允许一条气泡在编辑，进新的之前先收掉旧的。"""
        if self.session is None or bubble is None or not _widget_alive(bubble):
            return
        if bubble.is_editing():
            self._cancel_inline_edit()
            return
        index = getattr(bubble, "_message_index", None)
        if index is None or not (0 <= index < len(self.session.messages)):
            return
        if self.session.messages[index].get("role") != ROLE_USER:
            # AI 气泡没有"重写"这回事（内容不是用户写的），静默忽略
            return
        self._begin_inline_edit(bubble)

    def _begin_inline_edit(self, bubble: ChatBubble):
        """让某条气泡进编辑态，并把抽屉的状态机切过去（只留一条在编辑）"""
        if bubble is None or not _widget_alive(bubble):
            return
        if not bubble.is_editing():
            self._cancel_inline_edit()          # 先收掉上一条（气泡或按钮可能已死）
        index = getattr(bubble, "_message_index", None)
        if not bubble.begin_inline_edit():
            return
        # ⚠️ 编辑框必须自己装一次事件过滤器：QTextEdit 处理完按键不会让它继续往父控件
        # 冒泡，光靠抽屉自己那一个过滤器收不到 Esc / Ctrl+Enter（见 _route_inline_editor_key）。
        # 过滤器对象就是抽屉自己，重复装不会叠加（Qt 对同一个过滤器对象去重）。
        try:
            bubble.inline_edit.installEventFilter(self)
        except RuntimeError:
            pass
        self._edit_index = index
        self._inline_edit_bubble = bubble
        # 编辑框可能比原气泡高，把它带进视野；并等布局稳定后按视口夹一次宽度
        QTimer.singleShot(0, lambda b=bubble: self._ensure_visible(b))
        log.op("AI", "inline_edit", index=index)

    def _cancel_inline_edit(self):
        """退出内联编辑态：气泡恢复原样，会话和磁盘一个字都不动

        close 按钮 / Esc / 换会话 / 关抽屉都走这里。全程判活 + 吞 RuntimeError：气泡是短命
        控件，"正在编辑的气泡刚好被重新渲染掉"随时会发生。"""
        bubble = getattr(self, "_inline_edit_bubble", None)
        self._inline_edit_bubble = None
        self._edit_index = None
        if bubble is None or not _widget_alive(bubble):
            return
        try:
            bubble.exit_inline_edit()
        except RuntimeError:
            pass

    def _inline_edit_accept(self, bubble: ChatBubble):
        """accept 按钮 / Ctrl+Enter：保留改完的文字并重新发送

        做法是把文字送进主输入框、设好 _edit_index，再调一次 send_message()（那条路径里已经写好了"替换这条消息 + 丢掉它之后的内容 + 重新请求回答"）。⚠️ 刻意不重写这套逻辑；空内容直接当成取消。"""
        if bubble is None or not _widget_alive(bubble):
            return
        text = bubble.inline_text().strip()
        if not text:
            self._cancel_inline_edit()
            return
        index = getattr(bubble, "_message_index", None)
        if index is None:
            self._cancel_inline_edit()
            return

        # ⚠️ 顺序很关键：先让气泡退出编辑态，再把文字交给主输入框；反过来的话
        # _cancel_inline_edit 会把刚设好的 _edit_index 清掉，accept 变成普通发送。
        bubble.exit_inline_edit()
        self._inline_edit_bubble = None
        self._edit_index = index

        self.input_edit.setPlainText(text)
        self._adjust_input_height()
        self.send_message()

    def _route_inline_editor_key(self, obj, event) -> bool:
        """内联编辑框的键盘约定；返回 True = 这个键已经被吃掉

        Esc → 取消更改（= close 按钮）；Ctrl+Enter → 保留并重新发送（= accept）；Enter → 换行。⚠️ Enter 不直接发送是故意的：这里编辑的多是多行内容，误触一次就会把后面整段历史裁掉。"""
        if event.type() != QEvent.KeyPress:
            return False
        key = event.key()
        if key == Qt.Key_Escape:
            self._cancel_inline_edit()
            event.accept()
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter):
            if not (event.modifiers() & Qt.ControlModifier):
                return False                # 交给 QTextEdit 自己插入换行
            bubble = getattr(self, "_inline_edit_bubble", None)
            if bubble is not None and _widget_alive(bubble) and obj is bubble.inline_edit:
                self._inline_edit_accept(bubble)
                event.accept()
                return True
        return False

    def _ensure_visible(self, bubble: ChatBubble):
        """把某条气泡滚进视野（编辑时气泡会变高，别让编辑框跑到可视区外面）"""
        if bubble is None or not _widget_alive(bubble):
            return
        # ⚠️ 必须等这一轮布局跑完（singleShot(0) 的时机）再量宽度：刚 setCurrentWidget 的
        # 这一刻父容器报的还是上一轮的宽度（实测 463，实际只有 405），照它算出来的编辑框
        # 会被顶出可视区、右边一截看不见。
        self._fit_inline_editor(bubble)
        try:
            self.scroll.ensureWidgetVisible(bubble, 0, 24)
        except RuntimeError:
            pass

    def _fit_inline_editor(self, bubble: ChatBubble):
        """按消息区视口的实际宽度把内联编辑框的宽度夹住（别顶出可视区）"""
        if bubble is None or not _widget_alive(bubble) or not bubble.is_editing():
            return
        try:
            width = self._bubble_width() + 14   # 14 ≈ 滚动条 + 一点余量
        except RuntimeError:
            return
        bubble._sync_inline_geometry(width)

    # ---------- 气泡宽度：按可用宽度自适应 ----------
    def _bubble_width(self) -> int:
        """当前消息区能给气泡的宽度（视口宽 − 两侧留白）

        ⚠️ 视口还没布局完（宽度 <= 0）时不能用它算：会算出下限 220，气泡就会用一个明显偏窄的宽度定稿；这种情况退回旧默认值，布局稳定后会再修正。"""
        try:
            viewport = self.scroll.viewport().width()
        except RuntimeError:
            return int(ChatBubble.MAX_WIDTH)
        if viewport < ChatBubble.MIN_BUBBLE_WIDTH + 40:
            return int(ChatBubble.MAX_WIDTH)
        # side_padding 里要加上投影余量：正文上限得扣掉左右各一份 BUBBLE_SHADOW_MARGIN，
        # 否则最长的那条气泡会顶到格子边上、投影被裁掉一条。
        return ChatBubble.adaptive_max_width(
            viewport, side_padding=14 + 7 + BUBBLE_SHADOW_MARGIN)

    def _apply_bubble_width(self):
        """视口宽度变了：把新上限推给所有气泡

        ⚠️ 只在宽度真的变了才做（见 ChatBubble.apply_max_width 的短路），否则每次
        resize 都要给所有气泡重算折行，滚动/拉伸会发滞。
        """
        try:
            viewport = self.scroll.viewport().width()
        except RuntimeError:
            return
        if viewport < ChatBubble.MIN_BUBBLE_WIDTH + 40:
            return                      # 布局还没跑完，等下一拍
        width = self._bubble_width()
        if width == getattr(self, "_last_bubble_width", None):
            return
        self._last_bubble_width = width
        # 消息区一整行的宽度 = 视口宽 − 消息区左右内边距（message_layout 的 14+14）
        try:
            row_width = max(1, self.scroll.viewport().width() - 28)
        except RuntimeError:
            row_width = 0
        try:
            bubbles = self.message_host.findChildren(ChatBubble)
        except RuntimeError:
            return
        for bubble in bubbles:
            if _widget_alive(bubble):
                bubble.apply_max_width(width, row_width)

    def sync_bubble_width(self):
        """外部（内嵌形态的页面）在布局稳定后调一次，让气泡按真实宽度重排"""
        self._apply_bubble_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 加载遮罩是"盖在滚动区上面"的独立子控件，窗口尺寸变了要跟着挪
        host = getattr(self, "chat_loading_host", None)
        if host is not None and host.isVisible():
            try:
                host.setGeometry(self.scroll.geometry())
            except Exception:
                pass
        # 宽度变了要重新算折行
        QTimer.singleShot(0, self._apply_bubble_width)

    def _sync_bubble(self, bubble: ChatBubble):
        """重新生成按钮：丢掉这条 AI 回答，用同一个问题再问一次

        把这条回答设成忙碌态，拿到新回答后作为该位置的一个新版本追加进去，
        再自动翻到最新那一版。
        """
        index = getattr(bubble, "_message_index", None)
        if self.session is None or index is None or index >= len(self.session.messages):
            return
        if self._busy:
            return
        message = self.session.messages[index]
        if message.get("role") != ROLE_ASSISTANT:
            return
        # 重新生成要删/插消息：先把"正在原地编辑的气泡"收掉，
        # 否则那条气泡的 _edit_index 会指向一个已经错位的下标
        self._cancel_inline_edit()
        # 找到它对应的那条用户消息（往前找最近的一条 user）
        user_text = ""
        for i in range(index - 1, -1, -1):
            if self.session.messages[i].get("role") == ROLE_USER:
                user_text = str(self.session.messages[i].get("content") or "")
                break
        if not user_text:
            return

        # 把当前的版本表**原样留着**（只补齐、不重置）
        # ⚠️ 这里只建表、不重置：无条件写 variants = [当前正文] 会把已有版本表整个冲掉
        #    （第 3 次重新生成时 [22,33] 被压成 [33]，用户看到"只剩两版"）。
        #    新版本由 _on_reply 追加在后面。
        variants = message.get("variants")
        if not isinstance(variants, list) or not variants:
            variants = [str(message.get("content") or "")]
            message["variants"] = variants
            message["variant_index"] = 0
        # 内存缓存同步成"消息里的那份"（真源永远是 message）
        self._variants[index] = list(variants)
        self._variant_active[index] = self._active_variant_of(index)
        self.store.save(self.session)      # 版本表先落盘，重载后还能翻页

        # 然后走一次正常的请求流程；回来时会挂到 index 这个位置上
        self._sync_busy_bar = bubble.actions
        if bubble.actions is not None:
            bubble.actions.set_busy(True)
        self._start_request(regen_index=index)

    def _set_bubble_text(self, bubble: ChatBubble, text: str):
        """换掉一条气泡的正文，并且按新内容重算尺寸

        ⚠️ 占位气泡是按"正在思考…"这个宽度建出来的；回答回来时只 set_text 换文字、不重算宽度
        的话，整段回答会被塞进几十像素宽的 label 里折成很多行，而高度还是"一行"，第二行往后
        落在气泡矩形之外、被操作栏盖住。所以换文字的同时必须调 refresh_size()。"""
        if bubble is None or not _widget_alive(bubble):
            return
        try:
            bubble.set_text(text)
            bubble.refresh_size()
        except RuntimeError:
            pass

    def _scroll_to_bottom(self):
        """滚到最底部

        ⚠️ 必须先停掉平滑滚动的惯性动画：它正把滚动条往自己算的位置带，我们这里直接
        设 maximum，几十毫秒后它会把滚动条拉回去（"新消息出来了，视图被弹回上面"）。
        """
        stop_smooth_scroll(self.scroll)
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ================= 发送 =================
    def on_send_clicked(self):
        """发送按钮：正在等回答时这个按钮是"停止" """
        if self._busy:
            self._stop_current()
            return
        self.send_message()

    def send_message(self):
        """发一条消息（Enter 和发送按钮都走这里）

        普通发送 = 追加新消息；重写 = 替换那条用户消息并丢掉它之后的所有内容。
        ⚠️ 内联编辑期间用户在**主输入框**里按 Enter：必须先收掉编辑态再当普通发送，否则会走进
        _apply_edit，用主输入框里另外一句话覆盖正在编辑的那条消息。"""
        if self._inline_edit_bubble is not None:
            self._cancel_inline_edit()
        text = self.input_edit.toPlainText().strip()
        if not text:
            return

        if self.session is None:
            # 兜底：真没有会话就现开一个，并登记进共享槽
            self.session = self.store.new_session()
            self._publish_session()

        if self._edit_index is not None:
            self._apply_edit(text)
            return

        # 1. 用户气泡 + 落盘
        index = len(self.session.messages)
        self._add_bubble(text, is_user=True, index=index)
        self.store.append(self.session, ROLE_USER, text)
        self.input_edit.clear()
        self._adjust_input_height()
        self._update_title()
        QTimer.singleShot(20, self._scroll_to_bottom)

        # 2. 没配 key → 给固定回答（不发请求）
        if not self._api_configured():
            reply = self._t("ai_no_key_reply")
            self.store.append(self.session, ROLE_ASSISTANT, reply)
            bubble = self._add_bubble(reply, is_user=False)
            # 气泡和会话里那条消息对上号（⟳/⧉ 靠这个下标工作）
            bubble._message_index = len(self.session.messages) - 1
            self._refresh_pager(bubble)
            QTimer.singleShot(20, self._scroll_to_bottom)
            log.op("AI", "no_key_hint")
            return

        # 3. 配置齐了 → 后台线程发请求
        self._start_request()

    def _apply_edit(self, text: str):
        """把"正在重写"的那条用户消息变成它的一个新版本，并从这一版重新问

        三件事，顺序不能换：1. 先把当前这一支的后继存进 branch_suffixes[当前版本]（旧回复不能
        删）；2. 把新文字追加成这个用户消息的一个新版本（版本表 + 当前页码一起写）；3. 清空它
        后面的消息（新版本还没有 AI 回复），然后照旧发一次请求。
        ⚠️ 正文 / 版本表 / 当前页码 / 分支表必须四样一起落盘：只写内存 map 而不改
        message["variants"] 的话，_variants_of() 会用旧表反过来覆盖内存，翻页器就不出现了。"""
        index = self._edit_index
        if self.session is None or index is None or index >= len(self.session.messages):
            self._edit_index = None
            return

        message = self.session.messages[index]
        if message.get("role") != ROLE_USER:
            # 只允许改用户自己的消息（正常路径进不来，防御一下）
            self._edit_index = None
            return

        # 0. 记账：先把当前这一支的后继存好（存的是"改之前"那一版的下游）
        variants, _branches = self._ensure_branches(index)
        current = self._active_variant_of(index)
        self._save_branch_suffix(index, current)

        # 1. 版本列表：把"改之前的那一版"留在里面，用户还能翻回去看
        if text not in variants:
            variants.append(text)
        message["variants"] = list(variants)
        message["variant_index"] = variants.index(text)
        message["content"] = text

        # 2. 新版本的后继从空开始（旧的那串已经安全地躺在 branch_suffixes 里了）
        del self.session.messages[index + 1:]
        # 版本表刚变长，分支表补齐到同样的长度（新分支暂时没有后继）
        self._ensure_branches(index)
        self.store.save(self.session)

        self._edit_index = None
        self.input_edit.clear()
        self._adjust_input_height()
        self._render_session()
        log.op("AI", "edit_message", index=index, variants=len(variants))

        if self._api_configured():
            self._start_request()
        else:
            reply = self._t("ai_no_key_reply")
            self.store.append(self.session, ROLE_ASSISTANT, reply)
            self._render_session()
    def _api_configured(self) -> bool:
        """接口地址有默认值，所以只要求 API Key 和模型名称"""
        try:
            settings = self.main_window.settings_manager
            return bool((settings.get_api_key() or "").strip()) and \
                bool(str(settings.settings.get("model_name", "") or "").strip())
        except Exception:
            return False

    def _build_request_messages(self) -> list:
        """按设置组装发给模型的 messages

        ⚠️ 这个方法不要改名叫 _build_messages：抽屉里已经有一个同名的界面构建方法，
        同名会把它覆盖掉，_build_ui 会拿到列表而不是控件、启动即报 addWidget 类型错。
        """
        settings = self.main_window.settings_manager.settings
        rounds = 0
        try:
            rounds = int(settings.get("ai_context_rounds", 0) or 0)
        except (TypeError, ValueError):
            rounds = 0

        language = "简体中文"
        try:
            language = self.main_window.language_manager.current_language
        except Exception:
            pass

        # 用户最后一句用来筛资源清单（让上下文里优先出现相关资源）
        last_user = ""
        if self.session is not None:
            for message in reversed(self.session.messages):
                if message.get("role") == ROLE_USER:
                    last_user = str(message.get("content") or "")
                    break
        keyword = ai_prompt.extract_keyword(last_user)
        mode = str(settings.get("ai_reply_mode", ai_prompt.DEFAULT_REPLY_MODE) or "")

        messages = ai_prompt.build_messages(
            self.session.messages if self.session else [],
            self._resources(), language, context_rounds=rounds, keyword=keyword,
            mode=mode)

        # ---------- 插件登记的"命令" ----------
        # 消息以某个插件命令开头（例如 /plugin）→ 把该插件的指令追加进 system，
        # 这就是"不仅要开启插件，还要输入命令它才真正启用"的实现。
        extra = self._chat_hint_prompt(last_user)
        if extra and messages:
            messages[0]["content"] = str(messages[0].get("content") or "") + extra

        # ---------- GCP-AI Agent：把"手"接上 ----------
        # ⚠️ 省 token 的关键：插件关着时 _agent_prompt_section() 返回空串，system 一个字
        #    都不多；工具往返记录（_agent_scratch）只挂在这一条请求上，不写进 session。
        section = self._agent_prompt_section()
        if section and messages:
            messages[0]["content"] = str(messages[0].get("content") or "") + section
        if self._agent_scratch:
            messages.extend(copy.deepcopy(self._agent_scratch))
        return messages

    # ================= GCP-AI Agent（内置插件给 AI 装的那双"手"） =================
    def _hint_source_active(self, source) -> bool:
        """登记这条提示的插件现在还开着吗（空 = 主程序自己登记的，永远算开）"""
        source = str(source or "").strip()
        if not source or source == "builtin":
            return True
        try:
            manager = getattr(self.main_window, "plugin_manager", None)
            if manager is None:
                return True
            for info in manager.plugins:
                if info.id == source:
                    return info.status == "ok"
        except Exception:
            pass
        return True

    def _chat_hint_prompt(self, user_text: str) -> str:
        """这条消息命中了某个插件命令的话，返回它要追加的 system 指令

        ⚠️ 每次现读注册表（插件可能刚被开关）；出错就当"没有命令"，不能拦住正常聊天。
        """
        try:
            from ..core.ai.chat_hints import get_hint_registry, locale_of
            language = "简体中文"
            try:
                language = self.main_window.language_manager.current_language
            except Exception:
                pass
            registry = get_hint_registry()
            hint = registry.matching(user_text)
            if hint is None:
                return ""
            # 来源插件被停用了就当没这条命令
            if not self._hint_source_active(getattr(hint, "source", "")):
                return ""
            return hint.prompt_for(locale_of(language))
        except Exception as exc:
            log.err("AI", "chat_hint", f"读取插件命令失败: {exc}")
            return ""

    def _agent(self):
        """取 AgentBridge（拿不到就返回 None，代表"这台机器上没有这双手"）"""
        try:
            from ..core.ai.agent_runtime import get_bridge
            return get_bridge(self.main_window)
        except Exception:
            return None

    def _agent_prompt_section(self) -> str:
        """Agent 开着 → 工具清单；关着 → "你没有手 + 原样回这句"的引导

        ⚠️ 关着时也必须发一小段（而不是空串）：不发的话模型会自由发挥，出现"我已经帮你
        打开了"这种假动作。发这一段的代价只有几十个 token。
        """
        bridge = self._agent()
        if bridge is None:
            return ""
        try:
            section = bridge.prompt_section()
            if section:
                return section
        except Exception as exc:
            log.err("AI", "agent_prompt", f"拼装 Agent 提示词失败: {exc}")
            return ""
        try:
            return agent_tools.build_agent_off_prompt(bridge.locale())
        except Exception as exc:
            log.err("AI", "agent_prompt", f"拼装「没有手」提示词失败: {exc}")
            return ""

    def _agent_note_activity(self, call: dict, result: dict):
        """把"AI 刚刚动了哪只手"记成一行，显示在"正在思考"气泡里

        把动作显示出来，用户才看得见这双手在干什么（否则界面只是转圈然后出结果）。
        """
        name = str(call.get("name") or "")
        args = call.get("args") or {}
        hint = ""
        for key in ("query", "code", "page", "text", "key", "id"):
            if args.get(key):
                hint = str(args[key])[:24]
                break
        ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
        line = f"{'🔧' if ok else '⚠️'} {name}{f'（{hint}）' if hint else ''}"
        self._agent_activity = (self._agent_activity + [line])[-4:]
        log.op("AI", "agent_tool", tool=name, ok=ok)

    def _agent_try_continue(self, content: str) -> bool:
        """这次回答里如果夹着工具调用就去执行，然后再问一次，返回 True

        循环上限是 agent_tools.MAX_ROUNDS：模型偶尔会陷进"一直要工具"的死循环，
        上下文越滚越大。到顶后 _on_reply 会照常把这条回答当最终答案显示出来。
        """
        bridge = self._agent()
        if bridge is None:
            return False
        try:
            if not bridge.enabled():
                return False
        except Exception:
            return False
        if self._agent_round >= agent_tools.MAX_ROUNDS:
            return False

        try:
            calls, cleaned = agent_tools.parse_tool_calls(content)
        except Exception as exc:
            log.err("AI", "agent_parse", f"解析工具调用失败: {exc}")
            return False
        if not calls:
            return False

        results = []
        for call in calls:
            name = str(call.get("name") or "")
            # ⚠️ 用户在配置界面把这一项关掉了 → 不执行（提示词里也没给它，
            #    这里是第二道闸：模型可能凭记忆硬写一个被关掉的名字）
            try:
                if not bridge.tool_on(name):
                    result = {"ok": False,
                              "error": f"{name} 已被用户在 GCP-AI Agent 配置界面关闭"}
                    self._agent_note_activity(call, result)
                    results.append(agent_tools.format_result(name, result))
                    continue
            except Exception:
                pass
            try:
                result = bridge.registry.execute(name, call.get("args") or {}, self)
            except Exception as exc:
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            self._agent_note_activity(call, result)
            results.append(agent_tools.format_result(name, result))

        # 记下这一轮往返：assistant 说了要调用什么，user 回给它结果
        self._agent_scratch.append({"role": ROLE_ASSISTANT, "content": str(content)})
        self._agent_scratch.append({"role": ROLE_USER, "content": "\n".join(results)})
        self._agent_round += 1

        # 模型在调用工具之前写的"人话"（比如"我来查一下"）先显示出来，
        # 免得用户看到一个空的思考气泡；剩下的话等下一轮。
        if cleaned and self._placeholder_bubble is not None:
            self._set_bubble_text(self._placeholder_bubble, cleaned)

        # 用同一个占位气泡接着跑（不要再冒一个新气泡出来）
        self._start_request(regen_index=self._agent_pending_regen,
                            reuse_placeholder=True)
        return True

    def append_agent_note(self, text: str):
        """外部（比如 GCP-AI Agent 插件页）往当前对话里插一条说明

        目前没人调用，留着是给插件"我帮你做了 X"这类主动汇报用的。
        """
        text = str(text or "").strip()
        if not text or self.session is None:
            return
        self.store.append(self.session, ROLE_ASSISTANT, text)
        self._render_session()

    def _resources(self) -> list:
        """读取资源库条目（按"文件指纹"缓存，避免每问一句都重新解析 JSON）

        ⚠️ 路径要与搜索页保持一致（云端/本地由设置决定），否则会出现"搜索页有这个资源、AI 却
        说库里没有"。上一次读失败时不能把空列表缓存住（会整轮都说"库里没有"），也不能记指纹。"""
        path = ""
        try:
            from ..core.cloud_resource_source import resolve_resource_file
            path = resolve_resource_file(self.main_window.settings_manager) or ""
        except Exception as exc:
            log.err("AI", "resources", f"解析资源库路径失败: {exc}")

        signature = self._resource_signature(path)
        if self._resources_cache is not None and self._resources_sig == signature:
            return self._resources_cache
        try:
            loader = ResourceLoader(resource_file=path or None)
            if loader.load_from_local():
                self._resources_cache = loader.get_all()
                self._resources_sig = signature
            elif self._resources_cache is None:
                # 读失败也先记着空表，但不记指纹，下次调用会重新尝试
                self._resources_cache = []
        except Exception as exc:
            log.err("AI", "resources", f"读取资源库失败: {exc}")
            if self._resources_cache is None:
                self._resources_cache = []
        return self._resources_cache

    @staticmethod
    def _resource_signature(path: str):
        """资源库文件的指纹（路径 + 修改时间 + 大小；拿不到就给个"无效"值）"""
        try:
            if path and os.path.isfile(path):
                stat = os.stat(path)
                return (path, int(stat.st_mtime), int(stat.st_size))
        except Exception:
            pass
        return None

    def invalidate_resources(self):
        """外部把资源库改了（新增/删除/改名）之后调一下，下次问话重新读盘"""
        self._resources_cache = None
        self._resources_sig = None

    def _find_resource(self, code: str):
        """按编码或 id 找一条资源（两边都试、忽略大小写）

        ⚠️ 资源没有 code 字段时卡片塞进输入框的是它的 id（见 AppCard.resource_code），只按
        code 查会报"资源不存在"，所以两种都认；查不到时强制重读一次磁盘（刚新增的也在）。"""
        wanted = str(code or "").strip()
        if not wanted:
            return None
        needle = wanted.upper()

        def _match(items):
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                if str(item.get("code") or "").strip().upper() == needle:
                    return item
                if str(item.get("id") or "").strip().upper() == needle:
                    return item
            return None

        found = _match(self._resources())
        if found is not None:
            return found

        # 缓存里没有：强制重读一次磁盘（可能是刚加进去的，或缓存过期）
        self.invalidate_resources()
        found = _match(self._resources())
        if found is not None:
            return found
        try:
            from ..core.cloud_resource_source import resolve_resource_file
            path = resolve_resource_file(self.main_window.settings_manager) or None
            loader = ResourceLoader(resource_file=path)
            if loader.load_from_local():
                return (loader.get_by_code(wanted)
                        or loader.get_by_id(wanted)
                        or _match(loader.get_all()))
        except Exception as exc:
            log.err("AI", "resources", f"兜底查询资源失败: {exc}")
        return None

    def _open_resource(self, code: str):
        """点 @ 提及 / 蓝色下划线的资源名：打开它的详情页

        要加载哪个条目由编码决定 —— 就是资源卡片 @ 按钮塞进输入框的
        `@名称(TG-000001)` 里的编码（没有编码的资源会是 id）。
        """
        code = str(code or "").strip()
        if not code:
            return
        window = self.main_window
        try:
            data = self._find_resource(code)
            if not data:
                self._info(self._t("ai_resource_not_found").format(code=code))
                return
            self.close_drawer()
            if hasattr(window, "_open_resource_detail"):
                QTimer.singleShot(int(SLIDE_DURATION_MS * 0.6),
                                  lambda d=data: window._open_resource_detail(d))
            log.op("AI", "open_resource", code=code)
        except Exception as exc:
            log.err("AI", "open_resource", f"打开资源详情失败: {exc}")

    def _start_request(self, regen_index: int = None,
                       reuse_placeholder: bool = False):
        """发一次请求

        regen_index 不为空 = "重新生成某条回答"：回答回来后要挂到那个下标上。
        reuse_placeholder=True 是 Agent 工具往返在用：沿用原来那个思考气泡，不要再冒一个新的
        （否则一次问答里会堆出一串"正在思考"）。"""
        settings = self.main_window.settings_manager
        max_tokens = 0
        if settings.settings.get("limit_token_output", False):
            try:
                max_tokens = int(settings.settings.get("max_token", 4096) or 4096)
            except (TypeError, ValueError):
                max_tokens = 4096

        try:
            messages = self._build_request_messages()
        except Exception as exc:
            self._fail(f"组装上下文失败：{exc}")
            return

        # 新一轮（不是工具往返）：把上一轮的临时记录清干净
        if not reuse_placeholder:
            self._agent_scratch = []
            self._agent_round = 0
            self._agent_activity = []
        self._agent_pending_regen = regen_index

        self._set_busy(True)
        self._regen_index = regen_index
        # 记下"这条请求属于哪个会话"：回来时用户已切走就直接丢弃（见 load_session）
        self._request_session_id = getattr(self.session, "id", None)
        if regen_index is None:
            if reuse_placeholder and self._placeholder_bubble is not None \
                    and _widget_alive(self._placeholder_bubble):
                # 工具往返：沿用原气泡，重新起一轮省略号动画
                self._thinking_step = 0
                self._animate_thinking()
                self._thinking_timer.start()
            else:
            # 普通提问：加一个占位气泡 + 省略号动画
                self._placeholder_bubble = self._add_bubble(self._t("ai_thinking"),
                                                            is_user=False)
                self._thinking_step = 0
                self._thinking_timer.start()
            QTimer.singleShot(20, self._scroll_to_bottom)

        self.worker = AIChatWorker(
            messages,
            api_key=settings.get_api_key(),
            model=str(settings.settings.get("model_name", "") or ""),
            api_base=str(settings.settings.get("api_base", "") or ""),
            max_tokens=max_tokens)
        # ⚠️ 不传 parent、并登记到模块级集合里（见 _track_chat_worker）：urllib 阻塞期间
        #    线程没法真的中断，"点停止 → 马上再发一条"会让 self.worker 指向新线程、
        #    旧线程的 Python 引用被丢掉；QThread 在 run() 未结束时被析构 → Qt 直接 abort
        #    （没有异常、没有日志，程序就没了）。挂到集合里才能跑到自然结束再销毁。
        self.worker.succeeded.connect(self._on_reply)
        self.worker.failed.connect(self._on_failed)
        _track_chat_worker(self.worker)
        self.worker.start()

    def _stop_current(self):
        """停止：作废请求

        普通提问 → 占位气泡换成"已停止"；重新生成 → 收掉忙碌态，回答内容保持原样。
        """
        if _worker_running(self.worker):
            self.worker.cancel()
        self._thinking_timer.stop()
        # 停止 = 这一轮结束：工具往返的临时记录一并清掉（下次提问不带旧结果）
        self._agent_scratch = []
        self._agent_round = 0
        self._agent_activity = []
        self._agent_pending_regen = None

        if self._regen_index is not None:
            self._regen_index = None
            self._render_session()
        elif self._placeholder_bubble is not None:
            self._set_bubble_text(self._placeholder_bubble, self._t("ai_reply_stopped"))
            if self.session is not None and self.session.messages:
                self.store.replace_last(self.session, ROLE_ASSISTANT,
                                        self._t("ai_reply_stopped"))
            self._placeholder_bubble = None
        self._set_busy(False)

    def _on_reply(self, content: str):
        """后台线程成功回包（主线程槽）

        普通提问 → 占位气泡换成回答并 replace_last 落盘；重新生成 → 作为那个位置的
        一个新版本插进会话，再翻到最新那一版。
        """
        self._thinking_timer.stop()

        # ⚠️ 请求发出后用户可能已经点了别的历史对话：这条回答属于旧会话，直接丢掉
        if getattr(self, "_request_session_id", None) != getattr(self.session, "id", None):
            log.op("AI", "reply_dropped", reason="会话已切换")
            self._set_busy(False)
            return

        # ---------- GCP-AI Agent：这次回答里有没有"要动手" ----------
        # 放在最前面：工具往返要沿用 _regen_index（重新生成时答案仍要落回那一条），
        # 所以不能先把它取出来清掉。
        try:
            if self._agent_try_continue(content):
                return
        except Exception as exc:
            log.err("AI", "agent_loop", f"工具往返失败，按普通回答处理: {exc}")

        index = self._regen_index
        self._regen_index = None

        if index is not None and self.session is not None:
            # 重新生成：**就地替换**原来那条（旧内容已经在 _variants[index][0] 里了）
            index = min(index, max(0, len(self.session.messages) - 1))
            if not self.session.messages:
                self.session.messages.append({
                    "role": ROLE_ASSISTANT, "content": content,
                    "ts": self.session.updated_at})
                index = 0
            else:
                self.session.messages[index]["content"] = content
                self.session.messages[index]["ts"] = self.session.updated_at
            # 版本列表：第 0 版是旧的，新的追加在后面（两版都能翻回去看）
            # ⚠️ 真源是 message["variants"]（存进消息才会落盘，重载后还能翻页），
            #    self._variants 只是内存缓存。
            message = self.session.messages[index]
            variants = message.get("variants")
            if not isinstance(variants, list) or not variants:
                variants = [str(message.get("content") or "")]
            if content not in variants:
                variants.append(content)
            message["variants"] = variants
            message["variant_index"] = len(variants) - 1
            message["content"] = content
            self._variants[index] = variants
            self._variant_active[index] = len(variants) - 1
            self.store.save(self.session)
            self._render_session()
            log.op("AI", "regenerate", index=index, variants=len(variants))
            self._set_busy(False)
            QTimer.singleShot(20, self._scroll_to_bottom)
            return

        answer_bubble = self._placeholder_bubble
        if answer_bubble is not None:
            self._set_bubble_text(answer_bubble, content)
            self._placeholder_bubble = None
        else:
            answer_bubble = self._add_bubble(content, is_user=False)

        if self.session is not None:
            self.store.replace_last(self.session, ROLE_ASSISTANT, content)
            # 记录这次用的模型和接口，方便以后翻历史时知道是哪套配置答的
            self.session.model = str(self.main_window.settings_manager.settings.get(
                "model_name", "") or "")
            self.session.api_base = str(self.main_window.settings_manager.settings.get(
                "api_base", "") or "")
            self.store.save(self.session)

            # ⚠️ 必须给这条气泡补上它在会话里的下标：占位气泡是 _start_request 里
            # 建出来的，那时还不知道最终位置；不补的话它下面的 ⟳/⧉ 根本没法工作
            # —— 它们都要靠这个下标去会话里找对应的消息。
            answer_bubble._message_index = len(self.session.messages) - 1
            self._refresh_pager(answer_bubble)

        self._set_busy(False)
        QTimer.singleShot(20, self._scroll_to_bottom)

    def _on_failed(self, message: str):
        """后台线程失败：把占位气泡换成错误说明

        ⚠️ 错误不写进历史（重开对话时不该看到一堆红色报错）。
        ⚠️ 重新生成失败时还要清掉 _regen_index 并重排一次，否则下一次提问会被当成"又一次
        重新生成"挂到那个位置上。"""
        self._thinking_timer.stop()
        if getattr(self, "_request_session_id", None) != getattr(self.session, "id", None):
            # 同上：属于旧会话的失败提示不必再显示
            self._set_busy(False)
            return
        # 失败也要把 Agent 那一轮的临时记录收干净，否则下次提问会带着旧工具结果
        self._agent_scratch = []
        self._agent_round = 0
        self._agent_activity = []
        self._agent_pending_regen = None
        if self._regen_index is not None:
            self._regen_index = None
            self._render_session()
            self._set_busy(False)
            self._info(f"⚠️ {self._t('ai_error_failed')}：{message}")
            return
        text = f"⚠️ {self._t('ai_error_failed')}：{message}"
        if self._placeholder_bubble is not None:
            self._set_bubble_text(self._placeholder_bubble, text)
            self._placeholder_bubble = None
        else:
            self._add_bubble(text, is_user=False)
        self._set_busy(False)
        QTimer.singleShot(20, self._scroll_to_bottom)

    def _fail(self, message: str):
        self._add_bubble(f"⚠️ {message}", is_user=False)
        self._set_busy(False)

    @property
    def _busy(self) -> bool:
        return getattr(self, "_is_busy", False)

    def _set_busy(self, busy: bool):
        """切换"发送 / 停止"按钮状态，并记住当前是否在等回答

        ⚠️ "正在思考…"只是界面气泡（不落盘）；回答回来后用 store.replace_last() 覆盖最后一条
        并落盘。把占位气泡写进历史的话，重载会话会看到一个内容为空的 AI 气泡。"""
        self._is_busy = bool(busy)
        if busy:
            self.send_btn.setText(self._t("ai_stop"))
            self._style_send_buttons(self.send_btn, busy=True)
        else:
            self.send_btn.setText(self._t("ai_send"))
            self._style_send_buttons(self.send_btn)

    def _animate_thinking(self):
        """"正在思考…"后面点上滚动的省略号，让用户知道还在跑；Agent 开着时还会附上它动了哪只手"""
        if self._placeholder_bubble is None:
            self._thinking_timer.stop()
            return
        self._thinking_step = (self._thinking_step + 1) % 4
        text = self._t("ai_thinking") + "." * self._thinking_step
        activity = getattr(self, "_agent_activity", None)
        if activity:
            text += "\n" + "\n".join(activity)
        self._set_bubble_text(self._placeholder_bubble, text)

    # ================= 链接 =================
    def _on_link_clicked(self, url: str):
        """气泡 / 输入框里的链接被点了

        三类链接：`toolsgcp://api_key` → 跳「设置 → API Key」并让卡片闪两下（左键直接生效）；
        `toolsgcp://res/<编码>` → 切到搜索页并打开该资源详情页；http(s) 外链 → 交给系统浏览器
        （单击和 Ctrl+左键都跳浏览器）。
        ⚠️ 绝不能自己在程序里做一个浏览器窗口：主窗口不跳转、不切页、不弹窗。"""
        url = str(url or "").strip()
        if url == LINK_SETTINGS_API_KEY:
            self._go_to_api_key_settings()
            return
        if url.startswith(LINK_PLUGIN_PREFIX):
            plugin_id = url[len(LINK_PLUGIN_PREFIX):].strip().strip("/")
            self._go_to_plugin(plugin_id)
            return
        if url.startswith(LINK_RESOURCE_PREFIX):
            code = url[len(LINK_RESOURCE_PREFIX):].strip()
            self._open_resource(code)
            return

        if not url.startswith(("http://", "https://")):
            return

        try:
            # ⚠️ 统一走 utils/url_open：普通左键到前台，Ctrl+左键静默打开不切走
            from ..utils.url_open import open_url
            open_url(url, "AI 链接")
            log.op("AI", "open_link", url=url)
        except Exception as exc:
            log.err("AI", "open_link", f"打开链接失败: {exc}")

    def _go_to_plugin(self, plugin_id: str):
        """跳转到 插件中心 → 对应的插件卡片，并让它闪两下

        行为与 _go_to_api_key_settings 一致：先收抽屉、切页面、再闪。
        """
        plugin_id = str(plugin_id or "").strip()
        if not plugin_id:
            return
        self.close_drawer()
        window = self.main_window
        try:
            page = getattr(window, "pluginInterface", None)
            if page is not None and hasattr(window, "switchTo"):
                window.switchTo(page)
                if hasattr(window, "navigationInterface"):
                    window.navigationInterface.setCurrentItem(page.objectName())
                # 页面切换 + 滚动要一点时间，延后再闪
                QTimer.singleShot(120,
                                  lambda p=page, i=plugin_id: p.flash_plugin(i))
            log.op("AI", "open_plugin_link", id=plugin_id)
        except Exception as exc:
            log.err("AI", "open_plugin_link", f"跳转插件页失败: {exc}")

    def _go_to_api_key_settings(self):
        """跳转到 设置 → API Key，并让那张卡片闪两下提示

        两处刻意行为：1. 普通左键点击就生效、不用按 Ctrl（Ctrl+左键那套只用于外部网址），
        站内的 API Key 是功能按钮；2. 每次点都闪：先等上一次高亮结束一小会儿再闪，避免
        "第二次点没反应"。"""
        self.close_drawer()
        window = self.main_window
        try:
            if hasattr(window, "switchTo") and hasattr(window, "settingsInterface"):
                window.switchTo(window.settingsInterface)
                if hasattr(window, "navigationInterface"):
                    window.navigationInterface.setCurrentItem(
                        window.settingsInterface.objectName())
            settings_interface = getattr(window, "settingsInterface", None)
            if settings_interface is not None and hasattr(settings_interface, "focus_api_key"):
                # 页面切换 + 滚动都需要一点时间，所以补一次"只滚动+聚焦、不再闪"的调用，
                # 保证输入框一定落在视野里；闪烁只由第一次触发，不然会连闪两轮。
                QTimer.singleShot(260, settings_interface.focus_api_key)
                QTimer.singleShot(900,
                                  lambda: settings_interface.focus_api_key(flash=False))
        except Exception as exc:
            log.err("AI", "goto_api_key", f"跳转 API Key 设置失败: {exc}")

    # ================= 输入框 =================
    def _adjust_input_height(self):
        """按实际行数把输入框在 1~4 行之间伸缩

        高度档位是"跳"的（38 → 62 → 86 → 110）而不是连续的，否则每敲一个字整条抽屉都会抖。
        ⚠️ 顺便刷新"/命令"候选列表和悬浮提示（本方法是 textChanged → documentSizeChanged
        链路的下游，每次内容变化都会走到）；这条链路对抽屉形态和侧边栏内嵌形态都成立，所以
        提示条绝不能在 on_open 里才刷新（侧边栏那个面板不走 on_open）。"""
        self._refresh_command_ui()

        document = self.input_edit.document()
        if document.isEmpty():
            if self.input_edit.height() != INPUT_MIN_H:
                self.input_edit.setFixedHeight(INPUT_MIN_H)
            return

        content_height = int(document.size().height()) + 12   # 12 ≈ 上下 padding
        if content_height <= INPUT_MIN_H:
            target = INPUT_MIN_H
        elif content_height <= INPUT_MIN_H + 24:
            target = INPUT_MIN_H + 24
        elif content_height <= INPUT_MIN_H + 48:
            target = INPUT_MIN_H + 48
        else:
            target = INPUT_MAX_H

        if self.input_edit.height() != target:
            self.input_edit.setFixedHeight(target)

    def eventFilter(self, obj, event):
        """本类唯一的事件过滤器入口

        ⚠️ 这个类里不能再定义第二个 eventFilter：Python 里后定义的会整个覆盖先定义的，"点外面
        自动收起"就是这样失效过。入口只有这一个：先判"点外面"，再处理按键。
        ⚠️ 内联编辑框的 Esc / Ctrl+Enter 也走这里且必须排在最前面 —— Esc 只有在这里被吃掉，
        全局 Esc 路由（BaseDrawer.handle_escape）才不会把整个面板关掉。"""
        self._outside_close_filter(obj, event)
        if getattr(self, "_inline_edit_bubble", None) is not None:
            bubble = self._inline_edit_bubble
            editor = bubble.inline_edit if _widget_alive(bubble) else None
            if editor is not None and obj is editor:
                if self._route_inline_editor_key(obj, event):
                    return True
        if obj is getattr(self, "input_edit", None):
            if event.type() == QEvent.KeyPress:
                key = event.key()
                # ⚠️ 候选面板打开时先让它吃键（↑/↓ 选择、Enter 采纳、Esc 收起），
                #    必须排在"Enter 发送"前面，否则按回车会把半截命令发出去。
                if self._command_popup_key(event):
                    return True
                # 打字前先断开从 @ 提及继承来的 anchor 格式
                if event.text() or key in (Qt.Key_Backspace, Qt.Key_Delete):
                    self._clear_bleeding_anchor_format()
                if key in (Qt.Key_Backspace, Qt.Key_Delete) \
                        and not (event.modifiers() & (Qt.ControlModifier
                                                      | Qt.ShiftModifier)):
                    if self._delete_mention_at_caret(backspace=(key == Qt.Key_Backspace)):
                        return True
                if key in (Qt.Key_Return, Qt.Key_Enter):
                    if event.modifiers() & Qt.ShiftModifier:
                        return False          # 交给 QTextEdit 自己插入换行
                    self.send_message()
                    return True
        return super().eventFilter(obj, event)

    def _outside_close_filter(self, obj, event):
        """全局守卫：按下鼠标时判断"这一下点在不在抽屉里"

        ⚠️ 由上面的 eventFilter 调用，不要再把它命名成 eventFilter（会互相覆盖）。
        ⚠️ 判断依据必须是鼠标坐标，不能只看事件落在哪个控件上：Qt 会把被忽略的鼠标按下沿父链
        重发（点气泡里的 QLabel、点消息区空白都会落到 MainWindow），那时用 isAncestorOf 会得出
        "点在抽屉外面"，点自己面板的空白也会把面板关掉。
        ⚠️ 也不能只信 obj：点搜索卡片的「@给AI」时有时收到的是按钮、有时是主窗口，所以再用屏幕
        坐标问一次 QApplication.widgetAt()，任一次认出该放行的控件就放行。"""
        if event.type() != QEvent.MouseButtonPress or not self.is_open():
            return False
        # 历史抽屉盖在上面时，外面这一下交给它处理（它只关自己，不会连带把聊天抽屉关掉）
        history = getattr(self, "history_drawer", None)
        if history is not None and history.is_open():
            return False

        global_pos = None
        inside = False
        try:
            global_pos = event.globalPos()
            if self.rect().contains(self.mapFromGlobal(global_pos)):
                inside = True
        except Exception:
            global_pos = None
            inside = False

        def _should_pass(widget) -> bool:
            if widget is None:
                return False
            # 悬浮球 / @ 按钮都在抽屉外面，但点它们不算"点外面"
            return (self._is_inside_drawer(widget)
                    or self._is_ai_ball(widget)
                    or _is_ai_mention_trigger(widget))

        if not inside:
            inside = _should_pass(obj if isinstance(obj, QWidget) else None)
        if not inside:
            inside = _should_pass(_widget_at(global_pos, self.main_window))

        if not inside:
            # ⚠️ 延时 0ms 再关：立刻收起会把"按下—抬起"拆到两个不同的控件上，按钮点不响
            QTimer.singleShot(0, self._close_if_still_open)
        return False

    def _close_if_still_open(self):
        """点抽屉外面时的延时关闭（见 _install_outside_close）"""
        if self.is_open():
            self.close_drawer()

    def focus_input(self):
        """把光标放进输入框（打开抽屉 / 从历史页返回时用）"""
        try:
            self.input_edit.setFocus()
        except Exception:
            pass

    # ================= @ 提及 =================
    def _mention_text(self, name: str, code: str) -> str:
        """输入框/气泡里 @ 提及的纯文本写法：`@名称(TG-000001)`"""
        name = str(name or "").strip() or str(code or "")
        return f"@{name}({code})" if code else f"@{name}"

    def _mention_char_format(self, code: str) -> QTextCharFormat:
        """@ 提及的显示格式：蓝色 + 下划线，并且可以点

        ⚠️ 关键在 setAnchor(True) + setAnchorHref()：只有这样才能让 QTextEdit.anchorAt() 认出
        链接、点击触发 anchorClicked，也才能被"退格删掉整段"认出来。只设颜色和下划线点不动。"""
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(COLOR_MENTION))
        fmt.setFontUnderline(True)
        fmt.setAnchor(True)
        fmt.setAnchorHref(f"{LINK_RESOURCE_PREFIX}{code}")
        fmt.setToolTip(_panel_text("mention_tip_detail",
                                   f"点击打开 {code} 的详情页").format(name=code))
        return fmt

    def _anchor_href_at(self, position: int) -> str:
        """文档里某个字符位置上的 anchorHref（没有就是空串）"""
        try:
            document = self.input_edit.document()
            total = document.characterCount() - 1
            if position < 0 or position >= total:
                return ""
            probe = QTextCursor(document)
            probe.setPosition(int(position))
            probe.setPosition(int(position) + 1, QTextCursor.KeepAnchor)
            return str(probe.charFormat().anchorHref() or "")
        except Exception:
            return ""

    def _mention_range_at(self, cursor) -> tuple:
        """光标挨着的那个 @ 提及在文档里的范围 → (开始, 结束)；不是提及就 (None, None)

        优先用字符格式里的锚点（连续的 anchor 就是一条完整提及）；认不出来时（比如从别处粘进来
        的纯文本）退回正则，在光标附近扫一遍 MENTION_RE。
        ⚠️ 取相邻字符不要用 cursor.movePosition(Right, KeepAnchor, 1)：在文档位置 0 上它返回
        False 且不移动，但选区已被扩一格，selectedText() 会拿到整个文档。统一用 setPosition。"""
        position = cursor.position()

        def anchor_span(index: int):
            """index 处那个字符的 anchor 区间（以字符位置表示）"""
            href = self._anchor_href_at(index)
            if not href.startswith(LINK_RESOURCE_PREFIX):
                return None
            start = index
            while start > 0 and self._anchor_href_at(start - 1) == href:
                start -= 1
            total = self.input_edit.document().characterCount() - 1
            end = index + 1
            while end < total and self._anchor_href_at(end) == href:
                end += 1
            return (start, end)

        # 退格看"光标左边那个字"，Delete 看"光标右边那个字"
        for index in (position - 1, position):
            span = anchor_span(index)
            if span:
                return span

        # 兜底：纯文本形态的提及（正则）
        for match in MENTION_RE.finditer(self.input_edit.toPlainText()):
            if match.end() == position or match.start() == position:
                return (match.start(), match.end())
        return (None, None)

    def _delete_mention_at_caret(self, backspace: bool) -> bool:
        """退格/删除键：如果挨着一个 @ 提及，就把整段删掉；返回 True = 按键已被处理

        ⚠️ 提及左右各有一个空格，只删提及会留下两个连着的空格，所以按方向多收一个：退格删
        左边那个、Delete 删右边那个。"""
        try:
            cursor = self.input_edit.textCursor()
            if cursor.hasSelection():
                return False            # 用户已经在选字了，按原生行为走
            start, end = self._mention_range_at(cursor)
            if start is None:
                return False

            # 先把要一起收掉的空格算进选区（左或右，看按的是哪个键）
            if backspace and start > 0:
                probe = QTextCursor(self.input_edit.document())
                probe.setPosition(start - 1)
                probe.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 1)
                if probe.selectedText() == " ":
                    start -= 1
            elif not backspace:
                probe = QTextCursor(self.input_edit.document())
                probe.setPosition(end)
                probe.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 1)
                if probe.selectedText() == " ":
                    end += 1

            # ⚠️ 必须先 setPosition(start, MoveAnchor) 把锚点钉在 start，再
            # setPosition(end, KeepAnchor)：只写后者的话锚点会跟到 end，选区变成
            # "从文档开头到 end"，一删就把前面的内容也带走了。
            cursor.setPosition(start, QTextCursor.MoveAnchor)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            # ⚠️ 删完如果只剩空白（典型场景：输入框里只有一条 @ 提及），就顺手清干净：
            # 留下一个看不见的空格会让用户觉得"删了但没删干净"，还会让"发送"以为有内容。
            if not self.input_edit.toPlainText().strip():
                cursor.select(QTextCursor.Document)
                cursor.removeSelectedText()
            self.input_edit.setTextCursor(cursor)
            self._adjust_input_height()
            return True
        except Exception as exc:
            log.err("AI", "mention_delete", f"删除 @ 提及失败: {exc}")
            return False

    def _insert_mention_at(self, start: int, name: str, code: str):
        """把一条 @ 提及写进输入框（蓝色下划线 + 可点的富文本）

        start 为空 = 插在光标处；start 有值 = 先清掉 start..光标 之间的内容再插。
        """
        name = str(name or "").strip()
        code = str(code or "").strip()
        if not code:
            return
        text = self._mention_text(name, code)
        fmt = self._mention_char_format(code)

        cursor = self.input_edit.textCursor()
        if start is not None and 0 <= start <= cursor.position():
            # 先 MoveAnchor 钉住起点，再 KeepAnchor 拉到光标处
            caret = cursor.position()
            cursor.setPosition(start, QTextCursor.MoveAnchor)
            cursor.setPosition(caret, QTextCursor.KeepAnchor)
            cursor.removeSelectedText()

        # ⚠️ 一次性 insertText 写进去：撤销栈里是一步，且整段同一份 charFormat → 一个整体
        cursor.insertText(text, fmt)
        after_mention = cursor.position()

        # 末尾补一格分隔（否则下一句话会跟编码粘在一起）。
        # ⚠️ 必须用没有 anchor 的空格式插这个空格，否则它会被当成提及的一部分一起删。
        cursor.insertText(" ", QTextCharFormat())

        # ⚠️ 光标回到提及末尾（不是文档末尾）：用户接着打字时字落在空格前面，
        # 这时按退格正好命中"光标左边是提及"，一次整段删掉。
        cursor.setPosition(after_mention)
        self.input_edit.setTextCursor(cursor)
        # ⚠️ 光标停在提及末尾时 document 还记着提及的 anchor 格式，这里立刻断一次，
        # 免得程序化插字继承出可点链接（正常打字那条路径由 eventFilter 提前断）。
        self._clear_bleeding_anchor_format()
        self._adjust_input_height()
        self.focus_input()

    def _clear_bleeding_anchor_format(self):
        """打字前把"从提及继承来的" anchor 格式清掉

        ⚠️ 这是 @ 提及最隐蔽的一个坑：提及是用带 anchor 的 charFormat 插进去的，光标停在它末尾
        时 QTextEdit 会继续沿用这个格式，于是紧接着打的字也带上同一个 anchor —— 整句都变成可点
        链接，甚至"退格删提及"会把后面一整段一起删掉。
        修法：按键生效之前，若光标正处于"左边是提及、右边不是提及"的位置，就把当前 cursor 的
        charFormat 重置成空，再交给 QTextEdit 正常处理（提及本身一个字符不动）。"""
        try:
            cursor = self.input_edit.textCursor()
            if cursor.hasSelection():
                return              # 替换选区时格式跟着选区走，不用管
            position = cursor.position()
            if str(cursor.charFormat().anchorHref() or ""):
                # 光标当前挂在提及格式上；右边还有提及字符说明在提及中间，属正常编辑，别动
                if self._anchor_href_at(position) == "":
                    cursor.setCharFormat(QTextCharFormat())
                    self.input_edit.setTextCursor(cursor)
        except Exception:
            pass

    def _char_at(self, position: int) -> str:
        """文档里某个位置上的那个字符（越界返回空串）"""
        try:
            document = self.input_edit.document()
            if position < 0 or position >= document.characterCount() - 1:
                return ""
            probe = QTextCursor(document)
            probe.setPosition(max(0, int(position)))
            probe.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 1)
            return str(probe.selectedText())
        except Exception:
            return ""

    def _apply_mention(self, name: str, code: str):
        """（兼容旧调用点）在光标处插入一条 @ 提及"""
        self._insert_mention_at(None, name, code)

    def insert_mention(self, name: str, code: str = ""):
        """把「@名称」追加到输入框末尾（搜索卡片上的 @ 按钮调这里）

        点卡片上的 @ 按钮 → 弹出 AI 对话框，并在对话最末尾追加一条蓝色下划线、可点击、整段可
        一次删掉的 @ 提及。⚠️ 用户已经空了一格就不要再补一格（不然会出现双空格）。"""
        name = str(name or "").strip()
        if not name:
            return
        if not self.is_open():
            window = self.main_window
            if window is not None and hasattr(window, "open_ai_drawer"):
                window.open_ai_drawer(focus=True)

        current = self.input_edit.toPlainText().rstrip()
        cursor = self.input_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.input_edit.setTextCursor(cursor)
        if current and not current.endswith((" ", "\n")):
            cursor.insertText(" ")
        self._insert_mention_at(None, name, code)


# 内联 SVG → QIcon 的缓存（同样的 SVG + 颜色 + 尺寸只渲染一次）
# ⚠️ 必须有：气泡操作栏每条 4 个图标，60 条消息就是 240 次 SVG 渲染 + 光栅化
_SVG_ICON_CACHE = {}


def _svg_icon(svg: str, color: str, size: int = 18) -> QIcon:
    """把内联 SVG 渲染成 QIcon（带缓存，同样的 SVG + 颜色 + 尺寸只渲染一次）

    用内联 SVG 而不是 png：颜色直接写进 SVG，深浅色主题各生成一次即可。
    ⚠️ 缓存键必须带上颜色和尺寸，漏掉颜色的话切主题后图标会留着上一套颜色。
    """
    key = (svg, str(color), int(size))
    cached = _SVG_ICON_CACHE.get(key)
    if cached is not None:
        return cached
    svg = svg.replace("{color}", color)
    renderer = QSvgRenderer(svg.encode("utf-8"))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    icon = QIcon(pixmap)
    _SVG_ICON_CACHE[key] = icon
    return icon


# 加号（新对话）
ICON_PLUS = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
 fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round">
 <path d="M12 5v14M5 12h14"/></svg>"""

# 时钟 + 回转箭头（历史对话）
ICON_HISTORY = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
 fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round"
 stroke-linejoin="round">
 <path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 8v4l3 2"/></svg>"""

# 左箭头（历史对话页的返回按钮，不写文字）
ICON_BACK = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
 fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round"
 stroke-linejoin="round">
 <path d="M15 5l-7 7 7 7"/></svg>"""

# 垃圾桶（历史对话卡片左下角的删除按钮）
# 不用 FIF.DELETE：FIF 的颜色在取用那一刻就定死了，这里要的是一枚始终红色的垃圾桶
ICON_TRASH = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
 fill="none" stroke="{color}" stroke-width="1.9" stroke-linecap="round"
 stroke-linejoin="round">
 <path d="M3 6h18"/><path d="M8 6V4h8v2"/>
 <path d="M6 6l1 14h10l1-14"/><path d="M10 10.5v6M14 10.5v6"/></svg>"""


def _glyph_icon(svg: str, color: str, size: int = 16) -> QIcon:
    """把一个内联 SVG 按指定颜色渲染成小图标（_svg_icon 的定色版）"""
    return _svg_icon(svg, color, size)
