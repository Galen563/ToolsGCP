"""设置 → 「存储」板块：显示/更改 .ToolsGCP 的位置，并带进度迁移。

需求原话：
  · 有一个"存放 .ToolsGCP 的地址"的 UI 组件，默认是用户主目录（自动，不写死 Administrator）；
  · 在用户主目录放一个 ToolsGCP.json，里面写的就是这个路径；
  · 最核心的是**可以改成别的地址**，改的时候弹窗问"是否确认迁移 .ToolsGCP 至
    <换行>xxx"，取消就什么都不做；
  · 确认后要显示**进度条 + 进度提示**，完成后提示成功，并且 ToolsGCP.json 里的路径跟着变；
  · ToolsGCP.json 丢了/坏了要能自动建回默认位置。

⚠️ 后端全部在 pymodels.core.data_root（不依赖 PyQt），这里只做 UI。
⚠️ 颜色一律走 .theme 的 tokens，不写死十六进制。
"""

import os
import threading

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QFileDialog, QDialog)
from qfluentwidgets import (
    SimpleCardWidget, PushButton, PrimaryPushButton, BodyLabel, CaptionLabel,
    LineEdit, ProgressBar, MessageBoxBase, SubtitleLabel, isDarkTheme,
    InfoBar, InfoBarPosition, FluentIcon as FIF,
)

from ...core import data_root
from .theme import SIZES, tokens
from .widgets import SettingRow


class _PathRow(QWidget):
    """卡片内的一行：「标题 + 副说明/ⓘ」在左，一个**占满剩余宽度**的只读地址框 + 按钮在右。

    ⚠️ 不用现成的 SettingRow：它把右侧控件钉死成 200px（SIZES["control_width"]），
       而 .ToolsGCP 的路径经常上百个字符，200px 里什么也看不见。
    """

    def __init__(self, title: str, desc: str = "", tip: str = "",
                 button_text: str = "", button_icon=None, parent=None):
        super().__init__(parent)
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(12)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        self.title_label = QLabel(title, self)
        self.title_label.setProperty("role", "rowTitle")
        title_row.addWidget(self.title_label)
        if tip:
            try:
                from .widgets import TipIcon
                title_row.addWidget(TipIcon(tip, self))
            except Exception:
                pass
        title_row.addStretch(1)
        left.addLayout(title_row)
        if desc:
            self.desc_label = QLabel(desc, self)
            self.desc_label.setProperty("role", "rowDesc")
            self.desc_label.setWordWrap(True)
            left.addWidget(self.desc_label)
        else:
            self.desc_label = None
        # 左侧固定不要抢太多宽度，地址框才是主体
        box.addLayout(left, 0)

        self.path_edit = LineEdit(self)
        self.path_edit.setReadOnly(True)
        self.path_edit.setMinimumWidth(280)
        self.path_edit.setCursorPosition(0)
        box.addWidget(self.path_edit, 1)

        self.button = PushButton(button_text, self)
        if button_icon is not None:
            self.button.setIcon(button_icon)
        box.addWidget(self.button, 0)

        self.setMinimumHeight(SIZES["row_height_with_desc"] if desc
                              else SIZES["row_height"])

    def set_path(self, path: str):
        self.path_edit.setText(str(path or ""))
        self.path_edit.setToolTip(str(path or ""))
        self.path_edit.setCursorPosition(0)


class StorageLocationCard(SimpleCardWidget):
    """「存储位置」卡片：地址展示 + 更改 + 恢复默认 + 迁移进度"""

    # 迁移进度（从工作线程回 UI 线程用信号，避免在工作线程摸控件）
    progress_changed = pyqtSignal(int, int, str)
    migrate_finished = pyqtSignal(bool, str)

    def __init__(self, get_text, parent=None):
        super().__init__(parent)
        self._t = get_text
        self._busy = False
        self._new_root = ""

        box = QVBoxLayout(self)
        pad = SIZES["card_padding"]
        box.setContentsMargins(pad, pad - 4, pad, pad - 4)
        box.setSpacing(14)

        # ---- 数据目录一行 ----
        # ⚠️ 地址很长：不要用 SettingRow 的固定 control_width（200px），
        #    这里直接自己搭一张卡片内的"行"，让地址框吃掉整行剩余宽度。
        self.data_row = _PathRow(
            self._t("storage_location"),
            self._t("storage_location_desc"),
            self._t("storage_location_tip"),
            button_text=self._t("storage_change"),
            button_icon=FIF.FOLDER,
            parent=self)
        self.data_path_edit = self.data_row.path_edit
        self.change_btn = self.data_row.button
        self.change_btn.clicked.connect(self._on_change_clicked)
        box.addWidget(self.data_row)

        # ---- 指针文件一行 ----
        self.pointer_row = _PathRow(
            self._t("storage_pointer_file"),
            self._t("storage_pointer_file_desc"),
            "",
            button_text=self._t("storage_reset"),
            button_icon=FIF.SYNC,
            parent=self)
        self.pointer_path_edit = self.pointer_row.path_edit
        self.reset_btn = self.pointer_row.button
        self.reset_btn.clicked.connect(self._on_reset_clicked)
        box.addWidget(self.pointer_row)

        # ---- 进度区（平时隐藏）----
        self.progress_box = QWidget(self)
        pbox = QVBoxLayout(self.progress_box)
        pbox.setContentsMargins(0, 0, 0, 0)
        pbox.setSpacing(6)
        self.progress_bar = ProgressBar(self.progress_box)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label = CaptionLabel("", self.progress_box)
        pbox.addWidget(self.progress_bar)
        pbox.addWidget(self.progress_label)
        self.progress_box.hide()
        box.addWidget(self.progress_box)

        # ---- 提示小字（"资源文件不在这里"）----
        self.note_label = CaptionLabel(self._t("storage_note"), self)
        self.note_label.setWordWrap(True)
        box.addWidget(self.note_label)

        self.progress_changed.connect(self._on_progress)
        self.migrate_finished.connect(self._on_finished)

        self.refresh_paths()
        self.apply_theme()

    # ---------- 取值 / 展示 ----------
    def refresh_paths(self):
        """把当前数据根和指针路径显示出来（都来自后端，不写死）"""
        root = data_root.resolve_data_root()
        self.data_row.set_path(root)
        pointer = data_root.pointer_file_path()
        self.pointer_row.set_path(pointer)

    def apply_theme(self, dark: bool = None):
        if dark is None:
            dark = bool(isDarkTheme())
        c = tokens(dark)
        self.setStyleSheet(
            f"SimpleCardWidget {{"
            f" background-color: {c['card']};"
            f" border: 1px solid {c['card_border']};"
            f" border-radius: {SIZES['card_radius']}px;"
            f"}}")
        self.note_label.setStyleSheet(
            f"color: {c['text_secondary']}; background: transparent;")

    # ---------- 更改位置 ----------
    def _on_change_clicked(self):
        if self._busy:
            return
        start = self.data_path_edit.text() or data_root.default_data_root()
        # 选"父目录"，用户选的这一层下面就放 .ToolsGCP
        chosen = QFileDialog.getExistingDirectory(
            self, self._t("storage_choose_dir"), start)
        if not chosen:
            return
        chosen = os.path.normpath(chosen)
        # 如果用户直接选了一个以 .ToolsGCP 结尾的目录，就用它本身；否则在下面建 .ToolsGCP
        new_root = chosen if os.path.basename(chosen).lower() == ".toolsgcp" \
            else os.path.join(chosen, ".ToolsGCP")
        if os.path.normcase(os.path.abspath(new_root)) == \
                os.path.normcase(os.path.abspath(self.data_path_edit.text() or "")):
            self._toast(self._t("storage_same_path"), success=False)
            return
        ok, reason = data_root.validate_target(new_root)
        if not ok:
            self._toast(f"{self._t('storage_invalid_target')}：{reason}", success=False)
            return

        # ⚠️ 弹窗文案按需求：路径**另起一行**
        dlg = _MigrateConfirmDialog(
            self._t("storage_confirm_title"),
            self._t("storage_confirm_body"),   # 形如 "是否确认迁移 .ToolsGCP 至"
            new_root,
            self._t("storage_confirm_ok"),
            self._t("storage_confirm_cancel"),
            self)
        if dlg.exec_() != QDialog.Accepted:
            return                      # 取消：什么都不动，弹窗消失
        self._start_migration(new_root)

    def _start_migration(self, new_root: str):
        self._busy = True
        self._new_root = new_root
        self.change_btn.setEnabled(False)
        self.reset_btn.setEnabled(False)
        self.progress_box.show()
        self.progress_bar.setValue(0)
        self.progress_label.setText(self._t("storage_preparing"))
        self._set_controls_enabled(False)

        def work():
            try:
                ok, message = data_root.migrate_data_root(
                    new_root,
                    progress_cb=lambda done, total, text:
                    self.progress_changed.emit(done, total, text))
            except Exception as exc:            # 后端理论上不抛，这里兜底
                ok, message = False, str(exc)
            self.migrate_finished.emit(bool(ok), str(message))

        # 后台线程跑：迁移要搬不少文件，不能冻界面
        threading.Thread(target=work, daemon=True).start()

    def _set_controls_enabled(self, enabled: bool):
        self.data_path_edit.setEnabled(enabled)
        self.pointer_path_edit.setEnabled(enabled)

    # ---------- 进度回调（UI 线程） ----------
    def _on_progress(self, done: int, total: int, text: str):
        total = max(1, int(total))
        pct = int(max(0, min(100, round(done * 100.0 / total))))
        self.progress_bar.setValue(pct)
        self.progress_label.setText(
            f"{text}（{done}/{total}）" if text else f"{done}/{total}")

    def _on_finished(self, ok: bool, message: str):
        self._busy = False
        self.change_btn.setEnabled(True)
        self.reset_btn.setEnabled(True)
        self._set_controls_enabled(True)
        self.progress_bar.setValue(100 if ok else self.progress_bar.value())
        if ok:
            self.progress_label.setText(self._t("storage_done"))
            self.refresh_paths()
            self._toast(f"{self._t('storage_success')}\n{message}", success=True)
            # 迁移后各 Manager 还握着旧路径，提示需要重启才完全生效
            QTimer.singleShot(400, lambda: self._toast(
                self._t("storage_restart_hint"), success=True))
        else:
            self.progress_label.setText(self._t("storage_failed"))
            self._toast(f"{self._t('storage_failed')}\n{message}", success=False)
        QTimer.singleShot(2200, self.progress_box.hide)

    def _on_reset_clicked(self):
        if self._busy:
            return
        ok, message = data_root.reset_to_default_root()
        if ok:
            self.refresh_paths()
            self._toast(f"{self._t('storage_reset_done')}\n{message}", success=True)
        else:
            self._toast(f"{self._t('storage_failed')}\n{message}", success=False)

    # ---------- 小提示 ----------
    def _toast(self, text: str, success: bool = True):
        try:
            InfoBar.success if success else InfoBar.warning
            (InfoBar.success if success else InfoBar.warning)(
                title="", content=str(text), orient=Qt.Horizontal,
                isClosable=True, position=InfoBarPosition.TOP_RIGHT,
                duration=3200, parent=self.window())
        except Exception:
            pass


class _MigrateConfirmDialog(MessageBoxBase):
    """「是否确认迁移 .ToolsGCP 至」确认窗（路径单独一行）"""

    def __init__(self, title: str, body: str, path: str,
                 ok_text: str, cancel_text: str, parent=None):
        super().__init__(parent)
        self.title_label = SubtitleLabel(title, self)
        self.body_label = BodyLabel(body, self)
        self.body_label.setWordWrap(True)
        # ⚠️ 路径单独一行 + 可选中复制 + 自动换行（长路径不会把窗口撑爆）
        self.path_label = BodyLabel(path, self)
        self.path_label.setWordWrap(True)
        self.path_label.setCursor(Qt.IBeamCursor)
        try:
            self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        except Exception:
            pass

        self.viewLayout.addWidget(self.title_label)
        self.viewLayout.addWidget(self.body_label)
        self.viewLayout.addWidget(self.path_label)

        self.yesButton.setText(ok_text)
        self.cancelButton.setText(cancel_text)
        self.widget.setMinimumWidth(460)
        self.apply_theme()

    def apply_theme(self, dark: bool = None):
        if dark is None:
            dark = bool(isDarkTheme())
        c = tokens(dark)
        self.path_label.setStyleSheet(
            f"color: {c['accent']}; background: transparent;")


class SettingsCardsStorageMixin:
    """把「存储」卡片挂进设置页（由 SettingsInterface 组合进去）"""

    def _create_storage_card(self):
        """「存储」板块的卡片：显示 / 更改 .ToolsGCP 的位置"""
        try:
            card = StorageLocationCard(self.get_text, self)
            self.storage_card = card
            return card
        except Exception:
            # 这张卡出问题也不能让整个设置页打不开
            from ...utils.logger import log
            log.err("设置", "storage", "构建存储卡片失败")
            return None
