"""收藏界面：左侧收藏夹列表 + 右侧卡片网格。

默认收藏夹不可删除 / 不可重命名；卡片上的收藏图标可直接取消收藏。
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout, QInputDialog, QListWidgetItem, QVBoxLayout, QWidget,
    QScrollArea, QFrame,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, ComboBox, FluentIcon as FIF, InfoBar, InfoBarPosition,
    ListWidget, MessageBox, PrimaryPushButton, PushButton, SubtitleLabel,
)

from ..core.favorites_manager import (DEFAULT_FOLDER, FavoritesManager,
                                      display_folder_name)
from ..core.language_manager import LanguageManager
from ..core.resource_loader import ResourceLoader
from ..utils.smooth_scroll import install_smooth_scroll
from ..widgets import AppsIndexFramework, SelectionBar


class ToolsGCPInterface(QWidget):
    """收藏页面"""

    # 收藏发生变化（新增/移除/换夹），通知搜索页刷新卡片上的收藏图标
    favorites_changed = pyqtSignal()

    def __init__(self, language_manager: LanguageManager = None,
                 favorites_manager: FavoritesManager = None,
                 resource_loader: ResourceLoader = None,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("toolsGCPInterface")
        self.lang = language_manager
        self.favorites = favorites_manager or FavoritesManager()
        self._loader = resource_loader
        self.current_folder = DEFAULT_FOLDER

        self.setup_ui()
        self.reload_folders()
        self.refresh_items()

    # ---------- 数据 ----------
    @property
    def loader(self) -> ResourceLoader:
        if self._loader is None:
            self._loader = ResourceLoader()
            self._loader.load_from_local()
        return self._loader

    # ---------- UI ----------
    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        # ---- 左：收藏夹列表 ----
        left_widget = QWidget(self)
        left_widget.setFixedWidth(230)
        left = QVBoxLayout(left_widget)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(10)

        self.folder_title = SubtitleLabel(self.get_text("folders"), left_widget)
        left.addWidget(self.folder_title)

        self.folder_list = ListWidget(left_widget)
        self.folder_list.currentRowChanged.connect(self._on_folder_changed)
        left.addWidget(self.folder_list, 1)

        self.new_folder_btn = PushButton(self.get_text("new_folder"), left_widget, FIF.FOLDER_ADD)
        self.new_folder_btn.clicked.connect(self.create_folder)
        left.addWidget(self.new_folder_btn)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.rename_btn = PushButton(self.get_text("rename_folder"), left_widget, FIF.EDIT)
        self.rename_btn.clicked.connect(self.rename_folder)
        row.addWidget(self.rename_btn)

        self.delete_btn = PushButton(self.get_text("delete_folder"), left_widget, FIF.DELETE)
        self.delete_btn.clicked.connect(self.delete_folder)
        row.addWidget(self.delete_btn)
        left.addLayout(row)

        # 批量移动：勾选当前收藏夹里的程序整批挪走；进入后按钮变「取消移动」，再点退出
        self.move_btn = PushButton(self.get_text("move_items"), left_widget, FIF.MOVE)
        self.move_btn.setCheckable(True)
        self.move_btn.clicked.connect(self._on_move_btn_clicked)
        left.addWidget(self.move_btn)

        layout.addWidget(left_widget)

        # ---- 右：卡片区 ----
        right = QVBoxLayout()
        right.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.count_label = BodyLabel("", self)
        header.addWidget(self.count_label)
        header.addStretch()

        self.hint_label = CaptionLabel(self.get_text("hint"), self)
        header.addWidget(self.hint_label)
        right.addLayout(header)

        self.move_bar = SelectionBar(self, self.get_text("select_all"))
        self.move_bar.toggled.connect(self._on_move_select_all)
        self.move_target_label = BodyLabel(self.get_text("move_to"), self)
        self.move_target_combo = ComboBox(self)
        self.move_target_combo.setFixedWidth(160)
        # 注意插入顺序：add_leading 后插的排在前面，先插下拉才能让「移动到」在左
        self.move_bar.add_leading(self.move_target_combo)
        self.move_bar.add_leading(self.move_target_label)

        self.move_cancel_btn = PushButton(self.get_text("cancel"), self)
        self.move_cancel_btn.clicked.connect(self.end_move)
        self.move_bar.add_action(self.move_cancel_btn)

        self.move_confirm_btn = PrimaryPushButton(self.get_text("move_confirm"), self)
        self.move_confirm_btn.clicked.connect(self.confirm_move)
        self.move_bar.add_action(self.move_confirm_btn)

        self.move_bar.hide()
        self.move_target_label.hide()
        self.move_target_combo.hide()
        right.addWidget(self.move_bar)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        scroll_content = QWidget()
        scroll_content.setObjectName("favoritesScrollContent")
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(0, 4, 0, 4)

        self.framework = AppsIndexFramework(scroll_content)
        self.framework.set_empty_text(self.get_text("empty"))
        self.framework.ready.connect(self._on_ready)
        self.framework.card_clicked.connect(self._on_card_clicked)
        self.framework.favorite_toggled.connect(self._on_favorite_toggled)
        self.framework.selection_toggled.connect(self._on_card_selection_changed)
        content_layout.addWidget(self.framework, 1)

        self.scroll_area.setWidget(scroll_content)
        right.addWidget(self.scroll_area, 1)

        install_smooth_scroll(self.scroll_area)
        self._apply_scrollbar_style()

        layout.addLayout(right, 1)

    def _apply_scrollbar_style(self):
        from qfluentwidgets import isDarkTheme
        is_dark = isDarkTheme()
        handle = "#555555" if is_dark else "#CCCCCC"
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{ border: none; background-color: transparent; }}
            QWidget#favoritesScrollContent {{ background-color: transparent; }}
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
            text = self.lang.get_text("tools_gcp", key)
            if text != key:
                return text
        defaults = {
            "folders": "收藏夹", "new_folder": "新建收藏夹", "rename_folder": "重命名",
            "delete_folder": "删除", "empty": "这个收藏夹还是空的，去搜索页点收藏图标添加吧",
            "hint": "点卡片上的收藏图标可以取消收藏",
            "folder_created": "已新建收藏夹", "folder_renamed": "已重命名",
            "folder_deleted": "已删除收藏夹", "removed": "已取消收藏",
            "count": "共 {n} 项", "cannot_delete_default": "默认收藏夹不能删除",
            "move_items": "批量移动", "cancel_move": "取消移动",
            "move_to": "移动到", "move_confirm": "确定移动",
            "select_all": "全选", "cancel": "取消",
            "nothing_selected": "还没有勾选任何项",
            "need_other_folder": "只有一个收藏夹，先新建一个再移动吧",
            "moved": "已把 {n} 项移动到「{folder}」",
            "default_folder_reserved":
                f"「{display_folder_name(DEFAULT_FOLDER, getattr(self.lang, 'current_language', '简体中文') if self.lang else '简体中文')}」是保留名称",
            # 删除收藏夹的确认文案（三语言都在 json 里，这里是最后的兜底）
            "confirm_delete_folder":
                "确定要删除收藏夹「{name}」吗？\n里面的 {n} 项收藏也会一起删除。",
        }
        return defaults.get(key, key)

    # ---------- 收藏夹 ----------
    def _translate_result(self, message: str) -> str:
        """把管理器返回的标记翻成当前语言（比如 default_folder_reserved）"""
        if message == "default_folder_reserved":
            return self.get_text("default_folder_reserved")
        return message

    def folder_display_name(self, name: str) -> str:
        """文件夹的显示名（默认收藏夹按当前语言翻译）"""
        language = getattr(self.lang, "current_language", "简体中文") if self.lang else "简体中文"
        return display_folder_name(name, language)

    def reload_folders(self):
        self.folder_list.blockSignals(True)
        self.folder_list.clear()
        for name in self.favorites.folders():
            item = QListWidgetItem(
                f"{self.folder_display_name(name)}  ({self.favorites.count(name)})")
            item.setData(Qt.UserRole, name)
            self.folder_list.addItem(item)
        index = self.favorites.folders().index(self.current_folder) \
            if self.current_folder in self.favorites.folders() else 0
        self.folder_list.setCurrentRow(index)
        self.folder_list.blockSignals(False)
        self.current_folder = self.favorites.folders()[index]
        self._update_folder_buttons()

    def _update_folder_buttons(self):
        is_default = self.current_folder == DEFAULT_FOLDER
        self.rename_btn.setEnabled(not is_default)
        self.delete_btn.setEnabled(not is_default)
        self.delete_btn.setToolTip(self.get_text("cannot_delete_default") if is_default else "")

    def _on_folder_changed(self, row: int):
        if row < 0:
            return
        item = self.folder_list.item(row)
        if item is None:
            return
        self.current_folder = item.data(Qt.UserRole)
        self._update_folder_buttons()
        self.refresh_items()

    def create_folder(self):
        # ⚠️ 原生 QInputDialog 不跟主题（深色下字和底都浅、看不见），改用主题安全的输入框
        from ..ui.fluent_dialogs import ask_text
        ok, name = ask_text(self, self.get_text("new_folder"),
                            self.get_text("new_folder"))
        if not ok or not str(name).strip():
            return
        success, message = self.favorites.create_folder(name)
        if success:
            self.current_folder = message
            self.reload_folders()
            self.refresh_items()
            self.show_message(f"{self.get_text('folder_created')}: {message}", "success")
        else:
            self.show_message(message, "error")

    def rename_folder(self):
        if self.current_folder == DEFAULT_FOLDER:
            self.show_message(self.get_text("cannot_delete_default"), "warning")
            return
        old = self.current_folder
        from ..ui.fluent_dialogs import ask_text
        ok, name = ask_text(self, self.get_text("rename_folder"),
                            self.get_text("rename_folder"), text=old)
        if not ok or not str(name).strip():
            return
        success, message = self.favorites.rename_folder(old, name)
        if success:
            self.current_folder = message
            self.reload_folders()
            self.show_message(f"{self.get_text('folder_renamed')}: {message}", "success")
        else:
            self.show_message(message, "error")

    def delete_folder(self):
        if self.current_folder == DEFAULT_FOLDER:
            self.show_message(self.get_text("cannot_delete_default"), "warning")
            return
        name = self.current_folder
        # ⚠️ 文案不能写死中文：取 ToolsGCPcenter_language.json 的 confirm_delete_folder（三语言，占位符 {name} / {n} 一致）
        box = MessageBox(self.get_text("delete_folder"),
                         self.get_text("confirm_delete_folder").format(
                             name=name, n=self.favorites.count(name)), self)
        box.yesButton.setText(self.get_text("delete_folder"))
        box.cancelButton.setText(self.get_text("cancel"))
        if not box.exec():
            return
        success, message = self.favorites.delete_folder(name)
        if success:
            self.current_folder = DEFAULT_FOLDER
            self.reload_folders()
            self.refresh_items()
            self.favorites_changed.emit()
            self.show_message(f"{self.get_text('folder_deleted')}: {message}", "info")
        else:
            self.show_message(message, "error")

    # ---------- 批量移动 ----------
    def _on_move_btn_clicked(self, checked: bool):
        """批量移动按钮：进入 / 退出移动模式"""
        if checked:
            self.start_move()
        else:
            self.end_move()

    def start_move(self):
        """进入批量移动模式：所有卡片右上角出现勾选框，官网/GitHub 按钮隐藏"""
        codes = self.favorites.folder_items(self.current_folder)
        if not codes:
            self.show_message(self.get_text("empty"), "warning")
            self._reset_move_btn()
            return

        others = [f for f in self.favorites.folders() if f != self.current_folder]
        if not others:
            self.show_message(self.get_text("need_other_folder"), "warning")
            self._reset_move_btn()
            return

        self.move_btn.setText(self.get_text("cancel_move"))
        self.move_btn.blockSignals(True)
        self.move_btn.setChecked(True)
        self.move_btn.blockSignals(False)

        self.move_target_combo.blockSignals(True)
        self.move_target_combo.clear()
        for name in others:
            self.move_target_combo.addItem(self.folder_display_name(name), userData=name)
        self.move_target_combo.setCurrentIndex(0)
        self.move_target_combo.blockSignals(False)

        self._moving = True
        self.framework.set_selection_mode(True)
        self.move_bar.setVisible(True)
        self.move_target_label.setVisible(True)
        self.move_target_combo.setVisible(True)
        # 按钮保持可点：用户要能再点一次取消移动
        self.hint_label.setVisible(False)
        self._update_move_bar()

    def end_move(self):
        self._moving = False
        self.framework.set_selection_mode(False)
        self.move_bar.setVisible(False)
        self.move_target_label.setVisible(False)
        self.move_target_combo.setVisible(False)
        self.hint_label.setVisible(True)
        self._reset_move_btn()

    def _reset_move_btn(self):
        """按钮恢复成「批量移动」且不勾选"""
        self.move_btn.setText(self.get_text("move_items"))
        self.move_btn.blockSignals(True)
        self.move_btn.setChecked(False)
        self.move_btn.blockSignals(False)
        self.move_btn.setEnabled(True)

    def _update_move_bar(self):
        self.move_bar.set_counts(*self.framework.selection_counts())

    def _on_move_select_all(self, checked: bool):
        self.move_bar.blockSignals(True)
        if checked:
            self.framework.select_all()
        else:
            self.framework.clear_selection()
        self.move_bar.blockSignals(False)
        self._update_move_bar()

    def _on_card_selection_changed(self, *_):
        if getattr(self, "_moving", False):
            self._update_move_bar()

    def confirm_move(self):
        codes = self.framework.selected_codes()
        if not codes:
            self.show_message(self.get_text("nothing_selected"), "warning")
            return
        target = self.move_target_combo.currentData()
        if not target:
            return
        moved = 0
        for code in codes:
            if self.favorites.move(code, self.current_folder, target):
                moved += 1
        self.end_move()
        self.reload_folders()
        self.refresh_items()
        self.show_message(
            self.get_text("moved").format(n=moved, folder=target), "success")

    # ---------- 内容 ----------
    def refresh_items(self):
        codes = self.favorites.folder_items(self.current_folder)
        items = []
        for code in codes:
            resource = self.loader.get_by_code(code)
            if resource:
                items.append(resource)
        self.framework.set_data(items, sort_key="all")
        self.framework.set_favorites(codes)
        self.count_label.setText(self.get_text("count").format(n=len(items)))

        # 收藏夹列表里的数量也要跟着更新
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            name = item.data(Qt.UserRole)
            # ⚠️ 必须用显示名，用内部名会把「默认收藏夹」覆盖成 "Default"
            item.setText(
                f"{self.folder_display_name(name)}  ({self.favorites.count(name)})")

    def _on_ready(self):
        self.framework.set_favorites(self.favorites.all_codes())

    def _on_favorite_toggled(self, code: str):
        """在收藏页点收藏图标 = 取消收藏"""
        if self.favorites.remove(code):
            list(self.loader.get_all())
            self.refresh_items()
            self.favorites_changed.emit()
            name = ""
            resource = self.loader.get_by_code(code)
            if resource:
                name = resource.get("name", "")
            self.show_message(f"{self.get_text('removed')}: {name or code}", "info")

    def _on_card_clicked(self, data: dict):
        rid = data.get("id")
        full = self.loader.get_by_id(rid) if rid else None
        detail = getattr(self, "detail_opener", None)
        if callable(detail):
            detail(full or data)

    # ---------- 外部接口 ----------
    def on_favorites_changed(self):
        """搜索页改了收藏之后，收藏页同步刷新"""
        self.reload_folders()
        self.refresh_items()

    def refresh_theme(self):
        self._apply_scrollbar_style()
        if hasattr(self, "framework"):
            self.framework.refresh_theme()

    # ---------- 提示 ----------
    def show_message(self, message, msg_type="info"):
        # 标题走 common 模块，不再写死中文（见 plugin_interface.show_message 的说明）
        from ..core.language_manager import get_toast_title
        kwargs = dict(orient=Qt.Horizontal, isClosable=True,
                      position=InfoBarPosition.TOP, duration=2500, parent=self)
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
