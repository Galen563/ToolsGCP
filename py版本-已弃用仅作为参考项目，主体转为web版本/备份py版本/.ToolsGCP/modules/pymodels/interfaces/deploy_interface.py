"""部署界面：导出模式把本机常用软件整理成一份清单（每条对应资源库里的一个编码）导出 JSON；
部署模式导入清单，一键把清单里的软件自动下载 / 打开官网，快速还原环境。

下载来源解析优先级（见 utils/downloader.py）：download_url 直链 → GitHub 最新 Release 安装包 → 打开官网。
"""

from ..utils.fonts import ui_font
import json
import os
import sys
import webbrowser
from datetime import datetime

from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtGui import QFont, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QListWidgetItem,
    QProgressBar, QTableWidgetItem, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, FluentIcon as FIF, InfoBar, InfoBarPosition,
    ListWidget, MessageBox, MessageBoxBase, PrimaryPushButton, PushButton,
    SearchLineEdit, SubtitleLabel, SwitchButton, TableWidget, ToolButton,
)

from ..core.language_manager import LanguageManager
from ..core.resource_loader import ResourceLoader
from ..core.settings_manager import SettingsManager
from ..utils.downloader import DownloadWorker, resolve_target, safe_filename
from ..utils.logger import log
from ..utils.url_open import open_url, watch_ctrl
from ..constants import SCRIPT_DIR, DATA_DIR

if sys.platform == 'win32':
    import winreg

# 部署清单的落盘位置：.ToolsGCP/config/deploy_config.json
# ⚠️ 用绝对路径而不是相对路径：工作目录会被别处改（主窗口启动时就 os.chdir 过），
# 一旦不一致就会"读到别的文件"或"写到别处"，极难查
DEPLOY_FILE = os.path.join(DATA_DIR, "deploy_config.json")
DEPLOY_FILE_SCHEMA = "1.0.0"

# 状态文案
# ⚠️ 下面这六个常量是存盘 + 比较用的稳定值（写进 deploy_config.json，startswith(ST_FAILED) 之类的判断也靠它们），
# 不能跟着语言变；要显示给用户看时走 DeployInterface.status_text()（见 STATUS_KEYS）
ST_PENDING = "待部署"
ST_DOWNLOADING = "下载中"
ST_DONE = "已下载"
ST_OPENED = "已打开官网"
ST_SKIPPED = "已跳过"
ST_FAILED = "失败"

# 状态值 -> deploy 语言键（只影响**显示**，见上面那段说明）
STATUS_KEYS = {
    ST_PENDING: "pending",
    ST_DOWNLOADING: "st_downloading",
    ST_DONE: "st_done",
    ST_OPENED: "st_opened",
    ST_SKIPPED: "st_skipped",
}


# 列表 / 表格里资源图标的显示尺寸
RESOURCE_ICON_SIZE = 24
# 图标解码缓存：(路径, 尺寸) -> QIcon。列表和表格共用 —— 不缓存的话每次筛选都要重解码 53 张 PNG（输入会顿）
_RESOURCE_ICON_CACHE = {}


def resource_icon(resource: dict, size: int = RESOURCE_ICON_SIZE) -> QIcon:
    """一条资源对应的图标（取不到就退回库里的通用应用图标）。

    资源里的 icon 是相对于程序目录的路径（ResourceLoader 补全的），所以这里拼上程序目录再读。
    """
    raw = str((resource or {}).get("icon") or "").strip()
    if not raw:
        return FIF.APPLICATION.icon()
    path = raw if os.path.isabs(raw) else os.path.join(
        SCRIPT_DIR, raw.replace("/", os.sep))
    key = (path, int(size))
    cached = _RESOURCE_ICON_CACHE.get(key)
    if cached is not None:
        return cached
    icon = FIF.APPLICATION.icon()
    try:
        if os.path.exists(path):
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                icon = QIcon(pixmap.scaled(
                    int(size), int(size), Qt.KeepAspectRatio,
                    Qt.SmoothTransformation))
    except Exception:
        icon = FIF.APPLICATION.icon()
    _RESOURCE_ICON_CACHE[key] = icon
    return icon


class ResourcePickerDialog(MessageBoxBase):
    """从本机资源库里挑资源（**支持多选**），返回一个资源列表"""

    # 列表项前面那个图标显示多大
    ICON_SIZE = RESOURCE_ICON_SIZE

    def __init__(self, resources: list, parent=None, selected_codes=None):
        super().__init__(parent)
        self._resources = resources
        self._chosen = []
        # 已经加进清单的编码：默认**选中它们**，用户一眼能看出哪些已经在列表里
        self._selected_codes = {str(c) for c in (selected_codes or [])}

        self.titleLabel = SubtitleLabel(self.get_text("add_from_library"), self)
        self.viewLayout.addWidget(self.titleLabel)

        self.search = SearchLineEdit(self)
        self.search.setPlaceholderText(self.get_text("search_placeholder"))
        self.search.textChanged.connect(self._apply_filter)
        self.viewLayout.addWidget(self.search)

        self.list = ListWidget(self)
        self.list.setMinimumHeight(340)
        # ⚠️ 需求："从资源库添加弹窗里是可以多选而不是单选"；ExtendedSelection = Ctrl / Shift 多选，双击=确认
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setIconSize(QSize(self.ICON_SIZE, self.ICON_SIZE))
        self.list.itemDoubleClicked.connect(lambda _i: self._confirm())
        self.viewLayout.addWidget(self.list)

        self.hint = CaptionLabel(self.get_text("picker_multi_hint"), self)
        self.hint.setWordWrap(True)
        self.viewLayout.addWidget(self.hint)

        self.yesButton.setText(self.get_text("add"))
        self.cancelButton.setText(self.get_text("cancel"))
        self.widget.setMinimumWidth(460)

        self._fill(self._resources)

    # ---------- 图标 ----------

    def _icon_of(self, resource: dict) -> QIcon:
        return resource_icon(resource, self.ICON_SIZE)

    def _fill(self, items: list):
        self.list.clear()
        for r in items:
            code = str(r.get("code") or "")
            label = f"{code}   {r.get('name', '')}"
            item = QListWidgetItem(label)
            item.setIcon(self._icon_of(r))
            item.setData(Qt.UserRole, r)
            self.list.addItem(item)

    # ---------- 文案 ----------
    def get_text(self, key):
        """文案转发给父级部署页。

        ⚠️ MessageBoxBase 没有 get_text，所以顺着父子链往上找"能取文案的控件"（最终是 DeployInterface.get_text）。
        """
        node = self.parentWidget()
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
        return key

    def _apply_filter(self, text: str):
        keyword = (text or "").strip().lower()
        if not keyword:
            self._fill(self._resources)
            return
        self._fill([
            r for r in self._resources
            if keyword in str(r.get("code", "")).lower()
            or keyword in str(r.get("name", "")).lower()
            or keyword in str(r.get("id", "")).lower()
        ])

    def _confirm(self):
        """确认当前选中的全部条目（多选时一个不落）。

        ⚠️ 以前是 currentItem()（单选），多选之后只能加进去一条。
        """
        items = self.list.selectedItems()
        if not items:
            current = self.list.currentItem()
            items = [current] if current is not None else []
        chosen = []
        for item in items:
            data = item.data(Qt.UserRole)
            if isinstance(data, dict) and data:
                chosen.append(data)
        self._chosen = chosen
        if chosen:
            self.accept()

    def validate(self) -> bool:
        """MessageBoxBase 点「添加」时调用"""
        self._confirm()
        return bool(self._chosen)

    def chosen(self) -> list:
        """用户选中的资源列表（可能多条）"""
        return list(self._chosen or [])


class DeployInterface(QWidget):
    """部署页面 - 软件部署中心"""

    # 表格列（本轮重排：最前面加了图标列）
    COL_ICON = 0        # 图标
    COL_INDEX = 1       # 序数
    COL_CODE = 2        # 编码
    COL_NAME = 3        # 软件名称（拉伸，吃掉剩余宽度）
    COL_VERSION = 4     # 版本
    COL_SOURCE = 5      # 下载来源 / 安装路径
    COL_STATUS = 6      # 状态
    COL_OPS = 7         # 操作
    COLUMN_COUNT = 8
    COLUMN_WIDTHS = {
        COL_ICON: 52,
        COL_INDEX: 52,
        # ⚠️ 编码列要留够：qfluentwidgets 表格项两边留白比想象中大，96px 会把 "TG-000001" 截成 "TG-00…"
        COL_CODE: 112,
        COL_NAME: 200,      # 只是初始值，实际由 Stretch 决定
        COL_VERSION: 96,
        COL_SOURCE: 150,
        COL_STATUS: 110,
        COL_OPS: 110,
    }

    def __init__(self, language_manager: LanguageManager = None,
                 settings_manager: SettingsManager = None,
                 main_window=None):
        super().__init__()
        self.setObjectName("deployInterface")
        self.lang = language_manager
        self.settings_manager = settings_manager
        self.main_window = main_window

        self.software_list = []
        self.is_deploy_mode = bool(
            settings_manager.settings.get("deploy_mode", False)) if settings_manager else False

        self._loader = None
        self._worker = None
        self._batch_index = 0
        self._batch_running = False
        self._download_dir = ""

        self.setup_ui()

    # ================= UI =================
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 28)
        layout.setSpacing(16)

        # ---- 模式行 ----
        mode_widget = QWidget()
        mode_layout = QHBoxLayout(mode_widget)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(10)

        self.mode_switch = SwitchButton()
        self.mode_switch.setChecked(self.is_deploy_mode)
        self.mode_switch.checkedChanged.connect(self.on_mode_changed)
        self.mode_switch.setOnText("")
        self.mode_switch.setOffText("")
        mode_layout.addWidget(self.mode_switch)

        self.mode_label = BodyLabel(self.get_text("export_mode"))
        self.mode_label.setFont(ui_font(12))
        mode_layout.addWidget(self.mode_label)
        mode_layout.addSpacing(16)

        self.mode_hint = CaptionLabel("")
        mode_layout.addWidget(self.mode_hint)
        mode_layout.addStretch()
        layout.addWidget(mode_widget)

        # ---- 工具栏 ----
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.add_btn = PushButton(self.get_text("add_from_library"), self, FIF.ADD)
        self.add_btn.clicked.connect(self.add_from_library)
        toolbar.addWidget(self.add_btn)

        self.pick_btn = PushButton(self.get_text("pick_from_search"), self, FIF.SEARCH)
        self.pick_btn.clicked.connect(self.open_picker)
        toolbar.addWidget(self.pick_btn)

        # 从收藏夹导入（默认关闭）：打开后，勾选页会多一个"从收藏夹导入"下拉
        self.fav_import_switch = SwitchButton(self)
        self.fav_import_switch.setOnText("")
        self.fav_import_switch.setOffText("")
        self.fav_import_switch.setChecked(False)
        self.fav_import_switch.setToolTip(self.get_text("import_favorites_tip"))
        toolbar.addSpacing(6)
        self.fav_import_label = BodyLabel(self.get_text("import_favorites"), self)
        toolbar.addWidget(self.fav_import_switch)
        toolbar.addWidget(self.fav_import_label)

        self.import_btn = PushButton(self.get_text("import_list"), self, FIF.DOWNLOAD)
        self.import_btn.clicked.connect(self.import_list)
        toolbar.addWidget(self.import_btn)

        self.export_btn = PushButton(self.get_text("export_list"), self, FIF.SAVE_AS)
        self.export_btn.clicked.connect(self.export_list)
        toolbar.addWidget(self.export_btn)

        self.deploy_btn = PrimaryPushButton(self.get_text("deploy_all"), self, FIF.PLAY)
        self.deploy_btn.clicked.connect(self.deploy_all)
        toolbar.addWidget(self.deploy_btn)

        self.clear_btn = PushButton(self.get_text("clear_list"), self, FIF.DELETE)
        self.clear_btn.clicked.connect(self.clear_list)
        toolbar.addWidget(self.clear_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # ---- 表格 ----
        # 需求："添加进来不管是导出还是部署页都要整改这个 ui 表格排版，而且要加个图标在最前方。"
        # 以前 7 列全 Stretch（序数白占一大片、名称/操作被压窄，操作列按钮挤成一团）；
        # 现在最前面加图标列、改成 Interactive 逐列定宽，软件名称吃掉剩余空间，操作列固定够放下两个按钮
        self.table = TableWidget(self)
        self.table.setObjectName("deployTable")
        self.table.setColumnCount(self.COLUMN_COUNT)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setIconSize(QSize(RESOURCE_ICON_SIZE, RESOURCE_ICON_SIZE))
        self.table.verticalHeader().setDefaultSectionSize(36)
        # 「软件名称」列吃掉剩余宽度，其余列按下面这张表定宽
        header.setSectionResizeMode(self.COL_NAME, QHeaderView.Stretch)
        for column, width in self.COLUMN_WIDTHS.items():
            if column != self.COL_NAME:
                self.table.setColumnWidth(column, width)
        layout.addWidget(self.table, 1)

        # ---- 进度 ----
        bottom = QHBoxLayout()
        bottom.setSpacing(12)

        self.progress = QProgressBar(self)
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.hide()
        bottom.addWidget(self.progress, 1)

        self.progress_label = CaptionLabel("", self)
        bottom.addWidget(self.progress_label)
        layout.addLayout(bottom)

        self.load_software_list()
        self.update_mode_ui()

    def get_text(self, key):
        if self.lang:
            text = self.lang.get_text("deploy", key)
            if text != key:
                return text
        defaults = {
            "sequence": "序数", "software_name": "软件名称", "version": "版本",
            "install_path": "安装路径", "download_source": "下载来源", "code": "编码",
            "status": "状态", "operation": "操作", "edit": "编辑", "delete": "删除",
            "deploy": "部署", "no_software": "暂无软件", "export_mode": "导出模式",
            "deploy_mode": "部署模式", "mode_switched": "模式切换", "current_mode": "当前模式",
            "add_from_library": "从资源库添加", "add_manual": "手动添加",
            "added_n_from_library": "已从资源库添加 {n} 条",
            "picker_multi_hint": "可以多选（Ctrl / Shift），双击也会直接添加",
            "pick_from_search": "从搜索页选择",
            "import_favorites": "从收藏夹导入",
            "import_favorites_tip": "打开后，从搜索页选择时可以整夹导入收藏夹里的程序",
            "import_list": "导入清单", "export_list": "导出清单",
            "deploy_all": "一键部署", "clear_list": "清空列表",
            "export_hint": "把本机常用软件整理成清单，导出后拷到新电脑",
            "deploy_hint": "导入清单后一键自动下载 / 打开官网，快速还原环境",
            "open_page": "打开官网", "download": "下载", "retry": "重试",
            "skip": "跳过", "empty_tip": "列表为空，先「从资源库添加」几条吧",
            "exported": "清单已导出", "imported": "清单已导入",
            "import_failed": "导入失败", "unknown_code": "资源库里没有这个编码",
            "deploy_done": "部署完成", "download_dir": "选择下载目录",
            "confirm_deploy": "开始部署", "batch_running": "正在处理",
            "manual_add_title": "手动添加一行",
            "manual_add_hint": "填写编码（可留空）和软件名称",
            # 提示条标题（InfoBar 的那四个）
            "tip_success": "成功",
            "tip_error": "错误",
            "tip_warning": "提示",
            "tip_info": "信息",
        }
        return defaults.get(key, key)

    def fmt_text(self, key, fallback, **kwargs):
        """取一条带占位符的文案并填值。

        ⚠️ get_text 找不到键时会原样返回键名，所以按"拿到的还是不是键名"判断要不要退回中文兜底
        （两边占位符名完全一致，format 才不会炸）。
        """
        text = self.get_text(key)
        if not text or text == key:
            text = fallback
        return text.format(**kwargs)

    def status_text(self, status) -> str:
        """状态值 -> 当前语言的显示文案（存盘值本身不变，见 STATUS_KEYS 的说明）"""
        status = str(status or "")
        # 失败状态是 "失败: 具体原因" 拼出来的，前缀翻掉、后面的原因原样保留
        if status.startswith(ST_FAILED + ": "):
            return "%s: %s" % (self.get_text("st_failed"),
                               status[len(ST_FAILED) + 2:])
        return self.get_text(STATUS_KEYS.get(status, status))

    # ================= 资源库 =================
    def loader(self) -> ResourceLoader:
        if self._loader is None:
            self._loader = ResourceLoader()
            self._loader.load_from_local()
        return self._loader

    def resource_of(self, item: dict):
        code = str(item.get("code") or "").strip()
        if not code:
            return None
        return self.loader().get_by_code(code)

    # ================= 数据 =================
    def load_software_list(self):
        path = DEPLOY_FILE
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.software_list = self._normalize_loaded(data)
                log.info("部署", "deploy", f"加载软件列表: {len(self.software_list)} 项")
            except Exception as e:
                log.err("部署", "deploy", f"加载部署配置失败: {e}")
        else:
            log.info("部署", "deploy", "未找到部署配置文件")

    def _normalize_loaded(self, data):
        """兼容旧格式（纯 list）与新格式（{"items": [...]}）"""
        if isinstance(data, dict):
            items = data.get("items") or data.get("software") or []
        elif isinstance(data, list):
            items = data
        else:
            items = []
        result = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            result.append({
                "code": str(raw.get("code") or ""),
                "name": str(raw.get("name") or ""),
                "version": str(raw.get("version") or ""),
                "path": str(raw.get("path") or ""),
                "status": str(raw.get("status") or ST_PENDING),
                "source": str(raw.get("source") or ""),
            })
        return result

    def save_software_list(self):
        path = DEPLOY_FILE
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({"schema_version": DEPLOY_FILE_SCHEMA,
                           "updated_at": datetime.now().isoformat(timespec="seconds"),
                           "items": self.software_list},
                          f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.err("部署", "deploy", f"保存部署配置失败: {e}")

    # ================= 表格 =================
    def update_mode_ui(self):
        self.mode_label.setText(self.get_text("deploy_mode") if self.is_deploy_mode
                                else self.get_text("export_mode"))
        self.mode_hint.setText(self.get_text("deploy_hint") if self.is_deploy_mode
                               else self.get_text("export_hint"))
        headers = [
            "",                                     # 图标列没有表头文字
            self.get_text("sequence"),
            self.get_text("code"),
            self.get_text("software_name"),
            self.get_text("version"),
            self.get_text("download_source") if self.is_deploy_mode
            else self.get_text("install_path"),
            self.get_text("status"),
            self.get_text("operation"),
        ]
        self.table.setHorizontalHeaderLabels(headers)

        # 部署模式才有意义的按钮
        self.deploy_btn.setVisible(self.is_deploy_mode)
        self.import_btn.setVisible(self.is_deploy_mode)
        self.export_btn.setVisible(not self.is_deploy_mode)
        self.add_btn.setVisible(not self.is_deploy_mode)
        self.pick_btn.setVisible(not self.is_deploy_mode)
        self.fav_import_switch.setVisible(not self.is_deploy_mode)
        self.fav_import_label.setVisible(not self.is_deploy_mode)

        self.refresh_table()

    def refresh_table(self):
        self.table.setRowCount(len(self.software_list))
        for i, software in enumerate(self.software_list):
            # 图标列：拿资源库里那条资源的图标（拿不到就是通用图标）
            icon_item = QTableWidgetItem("")
            resource = self.resource_of(software)
            if resource:
                icon_item.setIcon(resource_icon(resource, RESOURCE_ICON_SIZE))
            icon_item.setToolTip(str(software.get("name") or ""))
            self.table.setItem(i, self.COL_ICON, icon_item)

            self.table.setItem(i, self.COL_INDEX, QTableWidgetItem(str(i + 1)))
            self.table.setItem(i, self.COL_CODE,
                               QTableWidgetItem(software.get("code") or "—"))
            self.table.setItem(i, self.COL_NAME,
                               QTableWidgetItem(software.get("name", "")))
            self.table.setItem(i, self.COL_VERSION,
                               QTableWidgetItem(software.get("version", "")))

            if self.is_deploy_mode:
                source = software.get("source") or self._source_text(software)
                self.table.setItem(i, self.COL_SOURCE, QTableWidgetItem(source))
            else:
                self.table.setItem(i, self.COL_SOURCE,
                                   QTableWidgetItem(software.get("path", "")))

            # 「状态」列显示当前语言的文案（存盘值仍是 ST_*，见 STATUS_KEYS）
            self.table.setItem(i, self.COL_STATUS, QTableWidgetItem(
                self.status_text(software.get("status", ST_PENDING))))
            self.table.setCellWidget(i, self.COL_OPS, self._make_ops(i))

    def _source_text(self, software) -> str:
        resource = self.resource_of(software)
        if not resource:
            return self.get_text("unknown_code")
        if resource.get("download_url"):
            return self.get_text("source_direct")
        if resource.get("github"):
            return "GitHub Release"
        return self.get_text("source_page")

    def _make_ops(self, index: int) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        if self.is_deploy_mode:
            item = self.software_list[index]
            target_kind = None
            try:
                target_kind = self._preview_kind(item)
            except Exception:
                pass

            if target_kind in ("direct", "github"):
                btn = ToolButton(FIF.DOWNLOAD)
                btn.setToolTip(self.get_text("download"))
                btn.clicked.connect(lambda _c, i=index: self.deploy_single(i))
                layout.addWidget(btn)
            else:
                btn = ToolButton(FIF.LINK)
                # ⚠️ 需求：只要是左键点开浏览器的地方，都要补上 Ctrl+左键逻辑
                btn.setToolTip(self.get_text("open_page") + chr(10)
                               + self.get_text("ctrl_open_tip"))
                self._ctrl_of(btn)
                btn.clicked.connect(lambda _c, i=index: self.open_page_single(i))
                layout.addWidget(btn)

            page_btn = ToolButton(FIF.GLOBE)
            page_btn.setToolTip(self.get_text("open_page") + chr(10)
                                + self.get_text("ctrl_open_tip"))
            self._ctrl_of(page_btn)
            page_btn.clicked.connect(lambda _c, i=index: self.open_page_single(i))
            layout.addWidget(page_btn)

            skip_btn = ToolButton(FIF.CANCEL)
            skip_btn.setToolTip(self.get_text("skip"))
            skip_btn.clicked.connect(lambda _c, i=index: self.set_status(i, ST_SKIPPED))
            layout.addWidget(skip_btn)
        else:
            edit_btn = ToolButton(FIF.EDIT)
            edit_btn.setToolTip(self.get_text("edit"))
            edit_btn.clicked.connect(lambda _c, i=index: self.edit_software(i))
            layout.addWidget(edit_btn)

            delete_btn = ToolButton(FIF.DELETE)
            delete_btn.setToolTip(self.get_text("delete"))
            delete_btn.clicked.connect(lambda _c, i=index: self.delete_software(i))
            layout.addWidget(delete_btn)

        layout.addStretch()
        return widget

    def _preview_kind(self, item: dict):
        code = str(item.get("code") or "")
        if not code:
            return None
        resource = self.loader().get_by_code(code)
        if not resource:
            return None
        if resource.get("download_url"):
            return "direct"
        if resource.get("github"):
            return "github"
        return "page"

    def set_status(self, index: int, status: str):
        if 0 <= index < len(self.software_list):
            self.software_list[index]["status"] = status
            # 数据里存的是 ST_*（稳定值），单元格里显示的是当前语言的文案
            self.table.setItem(index, self.COL_STATUS,
                               QTableWidgetItem(self.status_text(status)))

    # ================= 增删改 =================
    def add_from_library(self):
        """从资源库挑若干条加进清单（弹窗支持多选）"""
        resources = self.loader().get_all()
        if not resources:
            self.show_message(self.get_text("unknown_code"), "error")
            return
        existing = {str(s.get("code") or "") for s in self.software_list}
        dlg = ResourcePickerDialog(resources, self, selected_codes=existing)
        if not dlg.exec():
            return
        chosen = dlg.chosen()
        if not chosen:
            return

        added = 0
        for resource in chosen:
            code = str(resource.get("code") or "")
            if not code or code in existing:
                continue
            existing.add(code)
            self.software_list.append({
                "code": code,
                "name": resource.get("name", ""),
                "version": "",
                "path": "",
                "status": ST_PENDING,
                "source": "",
            })
            added += 1

        self.save_software_list()
        self.refresh_table()
        if added:
            self.show_message(
                self.fmt_text("added_n_from_library", "Added {n} item(s)", n=added),
                "success")
        else:
            self.show_message(self.get_text("all_selected_in_list"), "info")

    def open_picker(self):
        """跳到搜索页，用勾选框挑应用（可以顺带从收藏夹整夹导入）"""
        window = self.main_window or self.window()
        search = getattr(window, "searchInterface", None)
        if search is None:
            self.show_message(self.get_text("search_page_missing"), "error")
            return
        allow_favorites = self.fav_import_switch.isChecked()
        search.begin_selection("deploy", allow_favorites=allow_favorites)
        if hasattr(window, "switchTo"):
            window.switchTo(search)
            window.navigationInterface.setCurrentItem(search.objectName())
        log.info("部署", "deploy",
                 f"进入勾选模式（从收藏夹导入={'开' if allow_favorites else '关'}）")

    def add_codes(self, codes, switch_back=True):
        """把选中的资源编码加进部署清单。

        ⚠️ 加完就切回部署页（需求："选择好后点击添加到部署清单后会跳转回应用部署"），
        否则人还留在搜索页，完全不知道清单变了没有。
        """
        if not codes:
            return
        added = 0
        for code in codes:
            if any(s.get("code") == code for s in self.software_list):
                continue
            resource = self.loader().get_by_code(code)
            self.software_list.append({
                "code": code,
                "name": (resource or {}).get("name", code),
                "version": "",
                "path": "",
                "status": ST_PENDING,
                "source": "",
            })
            added += 1
        self.save_software_list()
        self.refresh_table()
        if added:
            self.show_message(
                self.fmt_text("added_n_from_library", "Added {n} item(s)", n=added),
                "success")
        else:
            self.show_message(self.get_text("all_selected_in_list"), "info")
        if switch_back:
            self.go_to_self_page()

    def go_to_self_page(self):
        """把主窗口切到「应用部署」这一页（拿不到主窗口就安静地算了）"""
        window = self.main_window or self.window()
        try:
            if window is None or not hasattr(window, "switchTo"):
                return
            window.switchTo(self)
            nav = getattr(window, "navigationInterface", None)
            if nav is not None:
                nav.setCurrentItem(self.objectName())
        except Exception:
            pass

    def add_manual(self):
        from qfluentwidgets import LineEdit
        text, ok = self._ask_two_lines()
        if not ok or not text[1].strip():
            return
        self.software_list.append({
            "code": text[0].strip(),
            "name": text[1].strip(),
            "version": "",
            "path": "",
            "status": ST_PENDING,
            "source": "",
        })
        self.save_software_list()
        self.refresh_table()

    def _ask_two_lines(self):
        """简单的两行输入对话框（不引入额外的 Dialog 依赖）"""
        from PyQt5.QtWidgets import QDialog, QFormLayout, QDialogButtonBox, QLineEdit
        dlg = QDialog(self)
        dlg.setWindowTitle(self.get_text("manual_add_title"))
        form = QFormLayout(dlg)
        code_edit = QLineEdit(dlg)
        code_edit.setPlaceholderText(self.get_text("code_placeholder"))
        name_edit = QLineEdit(dlg)
        name_edit.setPlaceholderText(self.get_text("software_name_placeholder"))
        form.addRow(self.get_text("code"), code_edit)
        form.addRow(self.get_text("name_label"), name_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dlg)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        result = dlg.exec()
        return (code_edit.text(), name_edit.text()), bool(result)

    def edit_software(self, index):
        if not (0 <= index < len(self.software_list)):
            return
        item = self.software_list[index]
        (code, name), ok = self._ask_two_lines()
        if not ok:
            return
        item["code"] = code.strip() or item["code"]
        item["name"] = name.strip() or item["name"]
        self.save_software_list()
        self.refresh_table()

    def delete_software(self, index):
        if not (0 <= index < len(self.software_list)):
            return
        self.software_list.pop(index)
        self.save_software_list()
        self.refresh_table()

    def clear_list(self):
        if not self.software_list:
            return
        box = MessageBox(self.get_text("clear_list"),
                         self.get_text("confirm_clear_list"), self)
        box.yesButton.setText(self.get_text("confirm_clear"))
        box.cancelButton.setText(self.get_text("cancel"))
        if not box.exec():
            return
        self.software_list = []
        self.save_software_list()
        self.refresh_table()

    # ================= 导入 / 导出 =================
    def export_list(self):
        if not self.software_list:
            self.show_message(self.get_text("empty_tip"), "warning")
            return
        default = os.path.join(SCRIPT_DIR, f"ToolsGCP-Deploy-{datetime.now():%Y%m%d}.json")
        path, _ = QFileDialog.getSaveFileName(
            self, self.get_text("export_list"), default, self.get_text("json_file_filter"))
        if not path:
            return
        payload = {
            "schema_version": DEPLOY_FILE_SCHEMA,
            "generator": "ToolsGCP",
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "count": len(self.software_list),
            "items": self.software_list,
        }
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except Exception as e:
            # ⚠️ title 用"导出清单"这种名词短语（不是"清单已导出"那句陈述），否则拼出来是"清单已导出 失败: xxx"
            self.show_message(
                self.fmt_text("export_failed", "{title} failed: {err}",
                              title=self.get_text("export_list"), err=e), "error")
            return
        log.info("部署", "deploy", f"导出清单 {len(self.software_list)} 项 -> {path}")
        self.show_message(f"{self.get_text('exported')}: {path}", "success")

    def import_list(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.get_text("import_list"), SCRIPT_DIR, self.get_text("json_file_filter"))
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = self._normalize_loaded(data)
        except Exception as e:
            self.show_message(f"{self.get_text('import_failed')}: {e}", "error")
            return
        if not items:
            self.show_message(self.get_text("import_failed"), "error")
            return

        for item in items:
            item["status"] = ST_PENDING
        self.software_list = items
        self.save_software_list()
        self.refresh_table()
        log.info("部署", "deploy", f"导入清单 {len(items)} 项 <- {path}")
        self.show_message(
            self.fmt_text("imported_count", "{title}: {n} item(s)",
                          title=self.get_text("imported"), n=len(items)), "success")

    # ================= 单条部署 =================
    def _ctrl_of(self, widget):
        """给"打开官网"这类按钮装上 Ctrl 观察器，并把状态记在本页上。

        ⚠️ 状态要挂在页面上而不是按钮上：open_page_single 是 clicked 之后才跑的，它拿不到按钮对象，
        只能读页面自己记下来的这一份。
        """
        try:
            self._open_page_ctrl = watch_ctrl(widget)
        except Exception:
            self._open_page_ctrl = {"ctrl": False}

    def open_page_single(self, index):
        item = self.software_list[index]
        resource = self.resource_of(item)
        target = resolve_target(resource)
        if target["kind"] == "unknown" or not target["url"]:
            self.set_status(index, f"{ST_FAILED}: {target['error'] or self.get_text('unknown_code')}")
            self.show_message(target["error"] or self.get_text("unknown_code"), "error")
            return
        # Ctrl+左键 = 浏览器打开但不抢焦点；不传 background，交给 open_url 自己判断 Ctrl
        open_url(target["url"], str(item.get("name") or ""))
        self.set_status(index, ST_OPENED)
        log.info("部署", "deploy", f"打开 {item.get('name')} -> {target['url']}")

    def deploy_single(self, index):
        """单独下载一条"""
        item = self.software_list[index]
        resource = self.resource_of(item)
        target = resolve_target(resource)
        if target["kind"] not in ("direct", "github"):
            self.open_page_single(index)
            return
        if not self._ensure_download_dir():
            return
        self._start_download(index, target)

    def _ensure_download_dir(self) -> bool:
        if self._download_dir and os.path.isdir(self._download_dir):
            return True
        default = os.path.join(os.path.expanduser("~"), "Downloads", "ToolsGCP-Deploy")
        os.makedirs(default, exist_ok=True)
        chosen = QFileDialog.getExistingDirectory(
            self, self.get_text("download_dir"), default)
        if not chosen:
            return False
        self._download_dir = chosen
        return True

    def _start_download(self, index, target):
        item = self.software_list[index]
        filename = safe_filename(target["filename"] or f"{item.get('name', 'download')}.bin")
        dest = os.path.join(self._download_dir, filename)

        limit = 0.0
        if self.settings_manager and self.settings_manager.is_download_speed_limited():
            limit = float(self.settings_manager.get_download_speed_limit())

        worker = DownloadWorker(target["url"], dest, limit, self)
        self._worker = worker

        self.progress.show()
        self.progress.setRange(0, 0)
        self.progress_label.setText(f"{self.get_text('batch_running')}: {item.get('name')}")
        self.set_status(index, ST_DOWNLOADING)

        def on_progress(received, total):
            if total > 0:
                self.progress.setRange(0, 100)
                self.progress.setValue(int(received * 100 / total))
                self.progress_label.setText(
                    f"{self.get_text('batch_running')}: {item.get('name')}  "
                    f"{received / 1048576:.1f} / {total / 1048576:.1f} MB")
            else:
                self.progress_label.setText(
                    f"{self.get_text('batch_running')}: {item.get('name')}  "
                    f"{received / 1048576:.1f} MB")

        def on_ok(path):
            self.progress.hide()
            self.progress_label.setText("")
            self.set_status(index, ST_DONE)
            item["path"] = path
            log.info("部署", "deploy", f"下载完成: {path}")
            self.show_message(f"{item.get('name')} → {path}", "success")
            if self._batch_running:
                QTimer.singleShot(200, self._next_in_batch)

        def on_fail(message):
            self.progress.hide()
            self.progress_label.setText("")
            self.set_status(index, f"{ST_FAILED}: {message}")
            log.err("部署", "deploy", f"下载失败 {item.get('name')}: {message}")
            if self._batch_running:
                QTimer.singleShot(200, self._next_in_batch)

        worker.progressed.connect(on_progress)
        worker.succeeded.connect(on_ok)
        worker.failed.connect(on_fail)
        worker.start()

    # ================= 一键部署 =================
    def deploy_all(self):
        if self._batch_running:
            self.show_message(self.get_text("batch_running"), "info")
            return
        if not self.software_list:
            self.show_message(self.get_text("empty_tip"), "warning")
            return

        box = MessageBox(
            self.get_text("confirm_deploy"),
            self.fmt_text("confirm_deploy_body",
                          "{n} apps in the list will be processed:\n· those available from GitHub or a direct link are downloaded automatically\n· the rest open their download page for you\n(You will choose a download folder first)",
                          n=len(self.software_list)), self)
        box.yesButton.setText(self.get_text("start"))
        box.cancelButton.setText(self.get_text("cancel"))
        if not box.exec():
            return
        if not self._ensure_download_dir():
            return

        self._batch_running = True
        self._batch_index = 0
        self.deploy_btn.setEnabled(False)
        self._ok_count = 0
        self._fail_count = 0
        log.info("部署", "deploy", f"开始一键部署，共 {len(self.software_list)} 项")
        self._next_in_batch()

    def _next_in_batch(self):
        if self._batch_index >= len(self.software_list):
            self._finish_batch()
            return

        index = self._batch_index
        self._batch_index += 1
        item = self.software_list[index]
        resource = self.resource_of(item)
        target = resolve_target(resource)

        if target["kind"] in ("direct", "github"):
            self._start_download(index, target)
            return

        if target["kind"] == "page":
            open_url(target["url"], str(item.get("name") or ""))
            self.set_status(index, ST_OPENED)
            log.info("部署", "deploy", f"打开官网: {item.get('name')}")
            self._ok_count += 1
            # 给浏览器留点时间，避免一次开几十个标签页把机器拖死
            QTimer.singleShot(1200, self._next_in_batch)
            return

        self.set_status(index, f"{ST_FAILED}: {target['error'] or self.get_text('unknown_code')}")
        self._fail_count += 1
        QTimer.singleShot(120, self._next_in_batch)

    def _finish_batch(self):
        self._batch_running = False
        self.deploy_btn.setEnabled(True)
        self.progress.hide()
        self.progress_label.setText("")
        done = sum(1 for s in self.software_list if s.get("status") == ST_DONE)
        opened = sum(1 for s in self.software_list if s.get("status") == ST_OPENED)
        failed = sum(1 for s in self.software_list if str(s.get("status", "")).startswith(ST_FAILED))
        message = self.fmt_text("batch_done_summary",
                                "{done} downloaded, {opened} website(s) opened, {failed} failed",
                                done=done, opened=opened, failed=failed)
        log.info("部署", "deploy", message)
        InfoBar.success(
            title=self.get_text("deploy_done"), content=message,
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=6000, parent=self)

    # ================= 模式切换 =================
    def on_mode_changed(self, checked):
        self.is_deploy_mode = checked
        if self.settings_manager:
            self.settings_manager.update_setting("deploy_mode", checked)
        self.update_mode_ui()

        mode_text = self.get_text("deploy_mode") if checked else self.get_text("export_mode")
        log.info("部署", "deploy", f"切换模式: {mode_text}")
        InfoBar.info(
            title=self.get_text("mode_switched"),
            content=f"{self.get_text('current_mode')}: {mode_text}",
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP, duration=1500, parent=self)

    # ================= 工具 =================
    def show_message(self, message, msg_type="info"):
        kwargs = dict(orient=Qt.Horizontal, isClosable=True,
                      position=InfoBarPosition.TOP, duration=3000, parent=self)
        if msg_type == "success":
            InfoBar.success(title=self.get_text("tip_success"), content=message, **kwargs)
        elif msg_type == "error":
            InfoBar.error(title=self.get_text("tip_error"), content=message, **kwargs)
        elif msg_type == "warning":
            InfoBar.warning(title=self.get_text("tip_warning"), content=message, **kwargs)
        else:
            InfoBar.info(title=self.get_text("tip_info"), content=message, **kwargs)
