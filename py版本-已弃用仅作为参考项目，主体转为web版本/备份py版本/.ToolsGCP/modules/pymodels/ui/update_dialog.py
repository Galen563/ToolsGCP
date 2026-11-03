"""自更新的三个弹窗：发现新版本 / 下载进度 / 替换失败说明。

都是窗口内弹窗（MessageBoxBase），不是独立小窗口：遮罩铺在父窗口内部，所以
parent 必须是顶层窗口（用 self.window() 拿），否则只盖得住设置页那一块。

⚠️ 本模块不 import 界面层的任何东西，文案一律通过构造时传进来的 t 回调取，
避免 ui → interfaces 的反向依赖。
"""

import os
import re

from PyQt5.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QPixmap
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QVBoxLayout, QWidget)

from qfluentwidgets import (BodyLabel, CaptionLabel, MessageBoxBase,
                            PrimaryPushButton, ProgressBar, PushButton,
                            SmoothScrollArea, StrongBodyLabel, SubtitleLabel,
                            isDarkTheme)

from ..constants import APP_CHANNEL, APP_RELEASES_PAGE, APP_VERSION, resource_path

# 下载进度弹窗底部两个按钮的宽度（等宽才不会一宽一窄）
PROGRESS_BUTTON_WIDTH = 120

# 下载完、校验通过之后自动替换并重启前的停留时间（毫秒）。
# 完成态不等用户点「立即重启并更新」，给一小段看清提示的时间就走；
# 这期间「稍后」仍可点，用户想晚点装还来得及拦下来。
AUTO_RESTART_DELAY_MS = 1500


# 小工具

def logo_pixmap(size):
    """取 .ToolsGCP/logo.png 并缩放到 size×size；拿不到返回 None

    resource_path 会同时试"程序目录旁的 .ToolsGCP"和"onefile 打包后的 _MEIPASS"。
    """
    try:
        path = resource_path("logo.png")
        if path and os.path.exists(path):
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                return pixmap.scaled(size, size, Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)
    except Exception:
        pass
    return None


def _is_dark():
    try:
        return bool(isDarkTheme())
    except Exception:
        return False


def _panel_colors():
    """说明面板的 (底色, 边框色)，跟随深浅主题"""
    if _is_dark():
        return "rgba(255,255,255,0.045)", "rgba(255,255,255,0.08)"
    return "rgba(0,0,0,0.028)", "rgba(0,0,0,0.07)"


def _badge_style(is_prerelease):
    """版本标签的配色：正式版绿色、预发布琥珀色（黄）"""
    if is_prerelease:
        if _is_dark():
            return "#E8C46A", "rgba(232,196,106,0.16)"
        return "#B8860B", "rgba(184,134,11,0.13)"
    if _is_dark():
        return "#6CCB8F", "rgba(108,203,143,0.16)"
    return "#107C41", "rgba(16,124,65,0.12)"


def _plain_notes(text):
    """把 GitHub 的 markdown 说明擦成人能直接读的纯文本

    只做最轻的处理（去标题井号、去粗体星号、把 [文字](链接) 变成"文字 (链接)"），
    不引入 markdown 渲染库。
    """
    text = str(text or "").replace("\r\n", "\n").strip()
    if not text:
        return ""
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)             # ## 标题
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1 (\2)", text)  # 链接
    text = text.replace("**", "").replace("__", "")                # 粗体
    text = re.sub(r"`([^`]*)`", r"\1", text)                       # 行内代码
    text = re.sub(r"\n{3,}", "\n\n", text)                         # 压缩空行
    return text.strip()


def reveal_in_explorer(path):
    """在资源管理器里定位到文件（打不开就算了，不能因此报错）"""
    target = str(path or "")
    try:
        if not target:
            return
        if os.path.isfile(target):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(target)))
        elif os.path.isdir(target):
            QDesktopServices.openUrl(QUrl.fromLocalFile(target))
    except Exception:
        pass


def _format_size(size):
    """字节数 → 人能读的大小（本模块自带，避免 ui 层反向 import core）"""
    try:
        value = float(size or 0)
    except Exception:
        return "—"
    if value <= 0:
        return "—"
    units = ("B", "KB", "MB", "GB", "TB")
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024.0
        index += 1
    if index == 0:
        return f"{int(value)} {units[index]}"
    return f"{value:.2f} {units[index]}"


def current_version_text():
    """当前版本（带 v；只有版本号本身看不出是预发布时才补 Beta）"""
    text = str(APP_VERSION)
    if text[:1] not in ("v", "V"):
        text = f"v{text}"
    if str(APP_CHANNEL).lower() == "beta" and "-" not in text:
        return f"{text} Beta"
    return text


# 弹窗 1：发现新版本

class UpdateAvailableDialog(MessageBoxBase):
    """窗口内弹窗：展示"有新版可用"，让用户决定下不下

    显示版本 / 版本信息 / 更新文件名称 / 文件大小，另加当前版本、发布日期，
    以及正式版(绿) / Beta版(黄) 标签。
    """

    def __init__(self, parent, t, info):
        super().__init__(parent)
        self.t = t
        self.info = dict(info or {})

        self.titleLabel = SubtitleLabel(t("update_dialog_available"), self.widget)
        self.viewLayout.addWidget(self.titleLabel)

        self.viewLayout.addLayout(self._build_header())
        self.viewLayout.addLayout(self._build_facts())
        self.viewLayout.addWidget(self._build_notes())

        self.yesButton.setText(t("update_btn_download"))
        self.cancelButton.setText(t("update_btn_later"))
        self.pageButton = PushButton(t("update_btn_open_page"), self.buttonGroup)
        self.pageButton.clicked.connect(self._open_page)
        self._reorder_buttons()

        self.widget.setMinimumWidth(560)

    # ---------- 顶部：图标 + 版本号 + 版本类型标签 ----------

    def _build_header(self):
        row = QHBoxLayout()
        row.setSpacing(14)

        logo = CaptionLabel("", self.widget)
        logo.setFixedSize(56, 56)
        logo.setAlignment(Qt.AlignCenter)
        pixmap = logo_pixmap(56)
        if pixmap is not None:
            logo.setPixmap(pixmap)
        row.addWidget(logo)

        column = QVBoxLayout()
        column.setSpacing(4)

        version = StrongBodyLabel(self.info.get("display_version") or "v?", self.widget)
        column.addWidget(version)

        # 版本类型标签：正式版绿、Beta 版黄
        # ⚠️ 完全以 GitHub Release 上的「Set as a pre-release」为准，
        #    不拿版本号里有没有 "-beta" 去猜。
        prerelease = bool(self.info.get("prerelease"))
        text = self.t("update_badge_prerelease" if prerelease
                      else "update_badge_stable")
        foreground, background = _badge_style(prerelease)
        badge = CaptionLabel(text, self.widget)
        badge.setStyleSheet(
            f"color: {foreground}; background: {background};"
            "border-radius: 4px; padding: 1px 7px;")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedHeight(20)

        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.addWidget(badge)
        badge_row.addStretch(1)
        column.addLayout(badge_row)

        column.addStretch(1)
        row.addLayout(column, 1)
        return row

    # ---------- 中间：事实表格 ----------

    def _build_facts(self):
        from PyQt5.QtWidgets import QGridLayout

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        rows = [
            (self.t("update_fact_current"), current_version_text(), False),
            (self.t("update_fact_latest"),
             self.info.get("display_version") or "v?", True),
            (self.t("update_fact_file"), self.info.get("asset_name") or "—", False),
            (self.t("update_fact_size"),
             _format_size(self.info.get("asset_size")), False),
        ]
        if self.info.get("published_at"):
            rows.append((self.t("update_fact_published"),
                         self.info.get("published_at"), False))

        for index, (label, value, emphasize) in enumerate(rows):
            key = CaptionLabel(str(label), self.widget)
            key.setMinimumWidth(76)
            if not emphasize:
                key.setStyleSheet("color: rgba(128,128,128,1);")
            grid.addWidget(key, index, 0, Qt.AlignTop | Qt.AlignLeft)

            val = BodyLabel(str(value), self.widget)
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if emphasize:
                font = val.font()
                font.setBold(True)
                val.setFont(font)
            grid.addWidget(val, index, 1)
        return grid

    # ---------- 版本信息（release 说明正文） ----------

    def _build_notes(self):
        wrapper = QWidget(self.widget)
        box = QVBoxLayout(wrapper)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)

        heading = CaptionLabel(self.t("update_fact_notes"), wrapper)
        heading.setStyleSheet("color: rgba(128,128,128,1);")
        box.addWidget(heading)

        # 面板只负责给块底色；滚动条交给库自带的 SmoothScrollArea
        panel = QFrame(wrapper)
        background, border = _panel_colors()
        # ⚠️ 第二段必须是普通字符串（不是 f-string），花括号不用写成 }}，
        #    否则整条样式表解析失败（Qt 报 Could not parse stylesheet）。
        panel.setStyleSheet(
            f"QFrame {{ background: {background}; border: 1px solid {border}; "
            "border-radius: 6px; }")
        inner = QVBoxLayout(panel)
        inner.setContentsMargins(12, 10, 4, 10)

        notes = _plain_notes(self.info.get("notes")) or self.t("update_notes_empty")
        label = BodyLabel(notes, panel)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        area = SmoothScrollArea(panel)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setFixedHeight(150)
        area.setWidget(label)
        # 让滚动区域透明，露出面板底色
        area.enableTransparentBackground()
        inner.addWidget(area)
        box.addWidget(panel)
        return wrapper

    # ---------- 底部按钮 ----------

    def _reorder_buttons(self):
        """把按钮排成 [稍后] [打开发布页] [立即下载]（主按钮在最右）"""
        layout = self.buttonLayout
        for button in (self.yesButton, self.cancelButton):
            layout.removeWidget(button)
        layout.addWidget(self.cancelButton, 1, Qt.AlignVCenter)
        layout.addWidget(self.pageButton, 1, Qt.AlignVCenter)
        layout.addWidget(self.yesButton, 1, Qt.AlignVCenter)

    def _open_page(self):
        url = self.info.get("page_url") or APP_RELEASES_PAGE
        try:
            QDesktopServices.openUrl(QUrl(url))
        except Exception:
            pass
        self.reject()


# 弹窗 2：下载进度

class UpdateProgressDialog(MessageBoxBase):
    """窗口内弹窗：下载进度 / 结果反馈

    点"取消"、按 Esc、或在遮罩上点一下，都会发 cancelled 信号，由调用方掐掉下载线程。
    下载完成后同一个弹窗切成完成态：能自动替换就提示"正在替换并重启"并倒计时，
    不能就亮出「查看原因」，不用再弹第二个窗。

    ⚠️ allow_replace 是三态：True / False = 调用方已经判过了；None = 还没判，
    等下载成功那一刻调 set_replace_blockers() 补上结论（"程序目录里有没有那个 exe"
    在下载前后是两个答案，下载前算会把结果钉死成"不能替换"）。
    """

    cancelled = pyqtSignal()

    def __init__(self, parent, t, filename, total_size=0, allow_replace=False):
        super().__init__(parent)
        self.t = t
        self.filename = str(filename or "")
        self.total_size = int(total_size or 0)
        # ⚠️ allow_replace 传 None 表示"还没判，等下载完再判"（见类注释）
        self.allow_replace = bool(allow_replace)
        self._decided = allow_replace is not None
        # 替换阻塞原因（机器码），调用方拿它去弹统一提示
        self.blockers = []
        # "完成"态用户点了哪个按钮
        self.restart_requested = False
        self.reasons_requested = False
        self._finished = False
        self._saved_path = ""
        self._warning = ""
        # 自动替换的倒计时
        self._auto_timer = None

        self.titleLabel = SubtitleLabel(t("update_download_title"), self.widget)
        self.viewLayout.addWidget(self.titleLabel)

        self.fileLabel = CaptionLabel(self._file_text(), self.widget)
        self.fileLabel.setStyleSheet("color: rgba(128,128,128,1);")
        self.fileLabel.setWordWrap(True)
        self.viewLayout.addWidget(self.fileLabel)

        self.bar = ProgressBar(self.widget)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.viewLayout.addWidget(self.bar)

        self.statusLabel = BodyLabel(t("update_download_starting"), self.widget)
        self.statusLabel.setWordWrap(True)
        self.viewLayout.addWidget(self.statusLabel)

        self.hideYesButton()
        self.cancelButton.setText(t("update_btn_cancel"))

        self.folderButton = PushButton(t("update_btn_open_folder"), self.buttonGroup)
        self.folderButton.clicked.connect(self._open_folder)
        self.folderButton.hide()

        self.reasonsButton = PushButton(t("update_btn_see_reasons"), self.buttonGroup)
        self.reasonsButton.clicked.connect(self._request_reasons)
        self.reasonsButton.hide()

        self.restartButton = PrimaryPushButton(t("update_btn_restart_now"),
                                               self.buttonGroup)
        self.restartButton.clicked.connect(self._request_restart)
        self.restartButton.hide()

        self._layout_progress_buttons()
        self.widget.setMinimumWidth(460)

    def _layout_progress_buttons(self):
        """底部按钮排匀：等宽 + 居中

        ⚠️ 不能沿用 MessageBoxBase 原来的排布：cancelButton 带 stretch=1 会被拉宽，
        隐藏掉的 yesButton 还占着一个拉伸项，中间会空出一截。
        所以取走全部布局项后自己重排，并且只排当前可见的那些。
        """
        layout = self.buttonLayout
        while layout.count():
            layout.takeAt(0)          # 只取走布局项；控件本身仍挂在 buttonGroup 上
        visible = [button for button in (self.folderButton, self.reasonsButton,
                                         self.restartButton, self.cancelButton)
                   if not button.isHidden()]
        for button in visible:
            button.setFixedWidth(PROGRESS_BUTTON_WIDTH)
        layout.addStretch(1)
        for button in visible:
            layout.addWidget(button)
        layout.addStretch(1)

    # ---------- 对外接口 ----------

    def update_progress(self, received, total, speed):
        """由下载线程的 progressed 信号驱动"""
        if self._finished:
            return
        total = int(total or 0) or self.total_size
        if total > 0:
            self.bar.setValue(max(0, min(100, int(received * 100 / total))))
        pieces = []
        if total > 0:
            pieces.append(f"{_format_size(received)} / {_format_size(total)}")
        else:
            pieces.append(_format_size(received))
        if speed:
            pieces.append(f"{_format_size(speed)}/s")
        self.statusLabel.setText("　·　".join(pieces))

    def finish_ok(self, path, warning=""):
        """下载完成（哈希通过）

        warning 是逗号分隔的警告码（体积太小 / 没有 PE 头），不影响成功，
        只是让提示语更诚实。

        完成态分两种（见类注释）：能自动替换就亮「立即重启并更新」，
        不能就亮「查看原因」。
        """
        self._finished = True
        self._saved_path = str(path or "")
        self._warning = str(warning or "")
        self._apply_finish_state()

    def set_replace_blockers(self, blockers):
        """调用方在下载成功那一刻重新算出来的替换阻塞原因（机器码列表）

        空列表 = 可以自动替换；这里顺手存下来给调用方读（它要拿同一份去弹统一提示）。
        """
        self.blockers = [code for code in (blockers or [])]
        self.allow_replace = not self.blockers
        self._decided = True
        # 调用方顺序反了（先 finish_ok 再 set_replace_blockers）时补一次
        if self._finished:
            self._apply_finish_state()

    def _apply_finish_state(self):
        """按 allow_replace 画出完成态（finish_ok / set_replace_blockers 共用）"""
        tip = describe_warning(self.t, self._warning)
        self.bar.setValue(100)
        self.titleLabel.setText(self.t("update_download_done_warn") if tip
                                else self.t("update_download_done"))
        self.fileLabel.setText(self._saved_path or self._file_text())
        self.folderButton.setVisible(bool(self._saved_path))
        if not self._decided:
            # 还没判：先按"不能自动替换"画，等 set_replace_blockers 再改
            self.statusLabel.setText(tip or self.t("update_download_cannot_replace"))
            self.reasonsButton.setVisible(True)
            self.cancelButton.setText(self.t("update_btn_close"))
        elif self.allow_replace:
            # 能换就不问了：提示一句"正在替换并重启"，倒计时到点自己走
            self.statusLabel.setText(tip or self.t("update_download_auto_restart"))
            self.cancelButton.setText(self.t("update_btn_later"))
            self._start_auto_restart()
        else:
            self.statusLabel.setText(tip or self.t("update_download_cannot_replace"))
            self.reasonsButton.setVisible(True)
            self.cancelButton.setText(self.t("update_btn_close"))
        self._layout_progress_buttons()

    # ---------- 自动替换倒计时 ----------

    def _start_auto_restart(self):
        """起一个一次性定时器：到点自动"点"下重启（用户还是能点「稍后」拦下来）"""
        if self._auto_timer is not None or self.restart_requested:
            return
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._request_restart)
        self._auto_timer.start(AUTO_RESTART_DELAY_MS)

    def _stop_auto_restart(self):
        """收掉倒计时（弹窗被关掉/已经决定时调，避免定时器打到已销毁的对象上）"""
        timer = self._auto_timer
        self._auto_timer = None
        if timer is not None:
            try:
                timer.stop()
                timer.deleteLater()
            except RuntimeError:
                pass

    def finish_error(self, reason):
        """失败 / 被取消"""
        self._finished = True
        title_key = ("update_download_cancelled" if str(reason) == "CANCELLED"
                     else "update_download_failed")
        self.titleLabel.setText(self.t(title_key))
        self.statusLabel.setText(describe_error(self.t, reason))
        self.folderButton.hide()
        self.reasonsButton.hide()
        self.restartButton.hide()
        self.cancelButton.setText(self.t("update_btn_close"))
        self._layout_progress_buttons()

    # ---------- 内部 ----------

    def _request_restart(self):
        """要替换重启了：记住意图，关掉弹窗，交给调用方去替换

        正常路径是倒计时自动调（见 _start_auto_restart）；「立即重启并更新」按钮也走这里。
        """
        self._stop_auto_restart()
        self.restart_requested = True
        self.accept()

    def _request_reasons(self):
        """点了「查看原因」：记住意图，关掉弹窗，由调用方弹统一提示"""
        self._stop_auto_restart()
        self.reasons_requested = True
        self.accept()

    def reject(self):
        """关掉弹窗前，如果还在下载就先通知调用方去掐线程

        ⚠️ 必须拦 reject() 而不是 closeEvent()：点"取消"、按 Esc 走的都是
        QDialog.reject()，它不会触发 closeEvent。
        """
        self._stop_auto_restart()
        if not self._finished:
            self.cancelled.emit()
        super().reject()

    def _file_text(self):
        text = self.filename or "—"
        if self.total_size > 0:
            text = f"{text}　·　{_format_size(self.total_size)}"
        return text

    def _open_folder(self):
        reveal_in_explorer(self._saved_path)


# 弹窗 3：替换失败（统一提示"到底是哪几种原因"）

# 原因码 → 语言键。码来自 core/self_update.py（那边只给码，文案在这里查）
_REASON_TEXT_KEYS = {
    "SOURCE_RUN": "update_replace_reason_source_run",
    "NO_EXE": "update_replace_reason_no_exe",
    "RENAMED": "update_replace_reason_renamed",
    "NOT_WRITABLE": "update_replace_reason_not_writable",
    "STAGE_FAILED": "update_replace_reason_stage",
    "SCRIPT_FAILED": "update_replace_reason_script",
    "NOT_WINDOWS": "update_replace_reason_not_windows",
}

# 「统一提示」里按这个顺序列原因
_ALL_REASONS = tuple(_REASON_TEXT_KEYS)


class UpdateReplaceFailedDialog(MessageBoxBase):
    """统一提示：没能自动替换成新版本，可能是哪几种原因

    两种都列：本次真正检测到的（detected 传进来的码）+ 其它同样会导致失败、
    但程序没法自动判断的。
    """

    def __init__(self, parent, t, detected=None, path=""):
        super().__init__(parent)
        self.t = t
        self.path = str(path or "")
        self.detected = [code for code in (detected or []) if code in _REASON_TEXT_KEYS]
        self.open_folder_requested = False

        self.titleLabel = SubtitleLabel(t("update_replace_failed_title"), self.widget)
        self.viewLayout.addWidget(self.titleLabel)

        intro = BodyLabel(t("update_replace_failed_intro"), self.widget)
        intro.setWordWrap(True)
        self.viewLayout.addWidget(intro)

        self.viewLayout.addWidget(self._build_reasons())

        if self.path:
            tip = CaptionLabel(t("update_replace_manual_tip").format(path=self.path),
                               self.widget)
            tip.setWordWrap(True)
            tip.setTextInteractionFlags(Qt.TextSelectableByMouse)
            tip.setStyleSheet("color: rgba(128,128,128,1);")
            self.viewLayout.addWidget(tip)

        self.hideYesButton()
        self.cancelButton.setText(t("update_btn_know"))
        self.folderButton = PushButton(t("update_btn_open_folder"), self.buttonGroup)
        self.folderButton.clicked.connect(self._on_open_folder)
        self.folderButton.setEnabled(bool(self.path))
        layout = self.buttonLayout
        while layout.count():
            layout.takeAt(0)
        for button in (self.folderButton, self.cancelButton):
            button.setFixedWidth(PROGRESS_BUTTON_WIDTH)
        layout.addStretch(1)
        layout.addWidget(self.folderButton)
        layout.addWidget(self.cancelButton)
        layout.addStretch(1)

        self.widget.setMinimumWidth(520)

    def _build_reasons(self):
        """原因清单：先列"本次检测到"的，再列"其它可能"的"""
        panel = QFrame(self.widget)
        background, border = _panel_colors()
        panel.setStyleSheet(
            f"QFrame {{ background: {background}; border: 1px solid {border}; "
            "border-radius: 6px; }")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        others = [code for code in _ALL_REASONS if code not in self.detected]

        if self.detected:
            heading = CaptionLabel(self.t("update_replace_detected"), panel)
            heading.setStyleSheet("color: rgba(128,128,128,1);")
            layout.addWidget(heading)
            for code in self.detected:
                layout.addWidget(self._reason_label(code, panel, hit=True))

        if others:
            heading = CaptionLabel(
                self.t("update_replace_detected" if not self.detected
                       else "update_replace_other"), panel)
            heading.setStyleSheet("color: rgba(128,128,128,1);")
            layout.addWidget(heading)
            for code in others:
                layout.addWidget(self._reason_label(code, panel, hit=False))
        return panel

    def _reason_label(self, code, parent, hit):
        """一条原因；本次检测到的那条标个红点 + 加粗"""
        key = _REASON_TEXT_KEYS.get(code)
        text = self.t(key) if key else str(code)
        label = BodyLabel(f"{'●' if hit else '○'} {text}", parent)
        label.setWordWrap(True)
        if hit:
            label.setStyleSheet("color: #D13438;")
            font = label.font()
            font.setBold(True)
            label.setFont(font)
        else:
            label.setStyleSheet("color: rgba(128,128,128,1);")
        return label

    def _on_open_folder(self):
        self.open_folder_requested = True
        self.accept()


# 文案辅助（弹窗和设置页共用）

# 错误码 → 语言键。码是给机器用的，文案一律"码→键"查出来，
# 否则英文/繁中用户会看到简体中文的报错。
_ERROR_TEXT_KEYS = {
    "REPO_NOT_FOUND": "update_err_no_release",
    "RATE_LIMITED": "update_err_rate_limit",
    "NETWORK": "update_err_network",
    "BAD_RESPONSE": "update_err_bad_response",
    "NO_CHANNEL_RELEASE": "update_err_no_channel_release",
    "NO_ASSET": "update_err_no_asset",
    "TIMEOUT": "update_err_timeout",
    "CANCELLED": "update_was_cancelled",
    "CHECKSUM": "update_err_checksum",
    "TOO_SMALL": "update_err_too_small",
    "NOT_EXE": "update_err_not_exe",
    "DISK": "update_err_disk",
}


def describe_error(t, code):
    """把错误码翻译成当前语言的说明；未知码带上原始值方便排查"""
    code = str(code or "")
    if code.startswith("HTTP_"):
        return f"{t('update_err_http')} ({code[5:]})"
    key = _ERROR_TEXT_KEYS.get(code)
    if key:
        return t(key)
    return f"{t('update_err_unknown')}（{code or '?'}）"


# 警告码 → 语言键（警告不阻止下载成功，只是提醒）
_WARNING_TEXT_KEYS = {
    "WARN_TOO_SMALL": "update_warn_too_small",
    "WARN_NOT_EXE": "update_warn_not_exe",
}


def describe_warning(t, warning):
    """把逗号分隔的警告码翻成一句话；没有警告返回 "" """
    codes = [c.strip() for c in str(warning or "").split(",") if c.strip()]
    parts = []
    for code in codes:
        key = _WARNING_TEXT_KEYS.get(code)
        if key:
            parts.append(t(key))
    return "　".join(parts)
