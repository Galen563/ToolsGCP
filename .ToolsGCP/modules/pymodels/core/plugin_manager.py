"""插件管理：一个文件夹 = 一个插件，放在 .ToolsGCP/plugins/ 下。
    plugins/my-plugin/manifest.json  +  app.py（入口，必须提供 create_page(context)）
⚠️ `_template` 和 `plugin-showcase` 只是给开发者看的模板，不加载、不进列表、
不建数据目录，但文件原封不动保留（见 RESERVED_DIR_NAMES）。
"""

import importlib.util
import json
import os
import shutil
import sys
import traceback
import types

from PyQt5.QtWidgets import QWidget

PLUGINS_DIR_NAME = "plugins"
# .ToolsGCP 这一层目录名（插件目录在它里面）
CONFIG_DIR_NAME = ".ToolsGCP"

# ---------- 内置插件的固定 id（别处靠它们做联动） ----------
AI_AGENT_PLUGIN_ID = "gcp-ai-agent"
MAKER_PLUGIN_ID = "gcp-plugin-maker"
# 关掉这些插件时，要连坐停用"制作器生成的插件"
MAKER_COMPANION_IDS = (AI_AGENT_PLUGIN_ID,)
# ---------- 首页推荐插件里**不展示**的内置插件 ----------
# ⚠️ 只是首页不展示：插件照常扫描、加载、出现在插件中心，文件更不能删。
HOME_HIDDEN_PLUGIN_IDS = (AI_AGENT_PLUGIN_ID, MAKER_PLUGIN_ID)
MANIFEST_NAME = "manifest.json"
# 兼容更早的写法（旧插件放的是 plugin.json）
LEGACY_MANIFEST_NAME = "plugin.json"
DEFAULT_ENTRY = "app.py"
STATE_FILE = "plugins.json"
# 插件备注（用户在插件卡片左下角写的那 20 个字）
NOTES_FILE = "plugin_notes.json"
# 插件可写目录，位于程序配置目录下（.ToolsGCP/config/plugin_data）
DATA_SUBDIR = "plugin_data"
# 开发模板目录名（**永不作为插件加载**，只被 create_from_template 复制）
TEMPLATE_DIR_NAME = "_template"
# 插件示例（plugin-showcase）只是给开发者照着写的模板，不是给用户用的插件：
# 不扫描、不加载、不进插件列表、不建数据目录，文件夹原样留在 plugins/ 下。
SHOWCASE_DIR_NAME = "plugin-showcase"
# 保留目录名：这些目录既不扫描、也不建数据目录（全是开发/示例/杂项目录）
RESERVED_DIR_NAMES = (TEMPLATE_DIR_NAME, SHOWCASE_DIR_NAME, "_t", "_archive")

# 状态
STATUS_OK = "ok"
STATUS_DISABLED = "disabled"
STATUS_ERROR = "error"
STATUS_MISSING = "missing"

# 插件语言文件名 ↔ ToolsGCP 的界面语言
LANGUAGE_TO_LOCALE = {
    "简体中文": "zh_CN",
    "繁體中文": "zh_TW",
    "English": "en_US",
}


class PluginInfo:
    """一个插件的元信息与运行状态"""

    def __init__(self, folder: str):
        self.folder = folder
        self.dir = ""
        self.manifest = {}
        self.id = ""
        self.name = ""
        self.version = ""
        self.author = ""
        self.description = ""
        self.icon = "APPLICATION"
        self.entry = DEFAULT_ENTRY
        self.status = STATUS_OK
        self.error = ""
        self.page = None
        self.module = None
        # 受保护的插件（内置示例）不允许删除
        self.protected = False
        # 用户给这个插件写的备注（存在 config/plugin_notes.json，由 PluginManager 填充）
        self.note = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK and self.page is not None

    def __repr__(self):
        return f"<Plugin {self.id} {self.status}>"


class PluginContext:
    """传给插件的上下文对象（插件能用什么，这里就给什么）"""

    def __init__(self, manager, info: PluginInfo):
        self._manager = manager
        self.info = info
        self.id = info.id
        self.name = info.name
        self.version = info.version
        self.author = info.author
        self.description = info.description
        self.plugin_dir = info.dir
        self.app_dir = manager.app_dir
        self.data_dir = os.path.join(manager.data_root, info.id)
        try:
            os.makedirs(self.data_dir, exist_ok=True)
        except Exception:
            pass

    # ---------- 给插件用的能力 ----------
    @property
    def language(self) -> str:
        """当前界面语言（简体中文 / 繁體中文 / English）"""
        if self._manager.language_manager is not None:
            return getattr(self._manager.language_manager, "current_language", "简体中文")
        return "简体中文"

    @property
    def locale(self) -> str:
        """当前语言对应的插件语言文件名（zh_CN / zh_TW / en_US）"""
        return LANGUAGE_TO_LOCALE.get(self.language, "zh_CN")
    @property
    def settings_manager(self):
        """取设置管理器
        ⚠️ 优先用主窗口上那一份（那才是界面正在读写的实例），否则会表现成"开关拨了、
        功能没生效"。
        """
        window = getattr(self._manager, "main_window", None)
        live = getattr(window, "settings_manager", None) if window is not None else None
        return live if live is not None else self._manager.settings_manager

    @property
    def favorites_manager(self):
        window = getattr(self._manager, "main_window", None)
        live = getattr(window, "favorites_manager", None) if window is not None else None
        return live if live is not None else self._manager.favorites_manager

    @property
    def language_manager(self):
        return self._manager.language_manager

    def get_resources(self) -> list:
        """拿到整个资源库"""
        return self._manager.get_resources()

    @property
    def ai_agent(self):
        """GCP-AI Agent 的运行时（是属性不是方法，插件写 context.ai_agent）
        ⚠️ 主窗口还没建好时返回 None，插件必须判空，别在这里抛异常把加载带崩。"""
        window = getattr(self._manager, "main_window", None)
        if window is None:
            return None
        try:
            from .ai.agent_runtime import get_bridge
            return get_bridge(window)
        except Exception:
            return None

    def register_ai_tool(self, name, description, handler, parameters: str = "",
                         danger: bool = False) -> bool:
        """给 GCP-AI 加一只"手"（本插件专属，停用时会被一起卸掉）
        description 可给 {"zh_CN":..., "zh_TW":..., "en_US":...}。
        ⚠️ 主窗口 / Agent 没准备好时返回 False，插件要判返回值，别当异常用。
        """
        bridge = self.ai_agent
        if bridge is None or not callable(handler):
            return False
        try:
            return bridge.register_tool(name, description, handler,
                                        parameters=parameters,
                                        source=self.id, danger=danger)
        except Exception:
            return False

    def register_chat_hint(self, hint_id: str, label, insert: str = "",
                           prompt="", priority: int = 0) -> bool:
        """在聊天输入框上面登记一条圆角悬浮提示（也可以是一条命令）
        label / prompt 都能给三种语言；用户点一下把 insert 填进输入框，真发了以 insert
        开头的消息时把 prompt 追加到 system —— "要输命令才真正启用"。
        """
        try:
            from .ai.chat_hints import get_hint_registry
            return get_hint_registry().register(hint_id, label, insert, prompt,
                                                priority, source=self.id)
        except Exception:
            return False

    def unregister_chat_hint(self, hint_id: str) -> bool:
        """卸掉一条提示（插件停用时调；不调也行，主界面会按注册表过滤）"""
        try:
            from .ai.chat_hints import get_hint_registry
            return get_hint_registry().unregister(hint_id)
        except Exception:
            return False

    def style_scroll_area(self, area) -> bool:
        """把插件里的滚动区域弄成"主程序同款"的滚动条 + 平滑滚动
        ⚠️ 插件拿不到 pymodels.ui 里的东西（不同包、不同 sys.path），所以由 context 代劳；
        返回 True 表示装好了，插件侧要判返回值。
        """
        if area is None:
            return False
        ok = False
        # 1) 细圆角滚动条（照抄插件中心那份 QSS）
        try:
            from qfluentwidgets import isDarkTheme
            handle = "#555555" if isDarkTheme() else "#CCCCCC"
            area.setStyleSheet(f"""
                QScrollArea {{ border: none; background-color: transparent; }}
                QScrollBar:vertical {{ background-color: transparent; width: 8px;
                    margin: 0px; border-radius: 4px; }}
                QScrollBar::handle:vertical {{ background-color: {handle};
                    min-height: 30px; border-radius: 4px; }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                    height: 0px; background: none; }}
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                    background: none; }}
            """)
            ok = True
        except Exception:
            pass
        # 2) 平滑滚动（带惯性）
        try:
            from ..utils.smooth_scroll import install_smooth_scroll
            install_smooth_scroll(area)
            ok = True
        except Exception:
            pass
        return ok

    # ---------- 插件文件系统的能力（插件制作辅助这类插件要用） ----------
    # 注：这里原来还有一份 `_ensure_plugins_dir()`，与 PluginManager 里那个同名同实现、
    # 且**全仓没有任何调用点**（含只读存档的 py 版），所以删掉；本类要目录就直接用
    # 下面的 `plugins_dir` 属性。同名方法在一个文件里出现两次，读代码的人会以为
    # 它们分别属于不同分支，实际只会引起"该改哪一个"的困惑。
    @property
    def plugins_dir(self) -> str:
        """plugins/ 目录的绝对路径（新建插件的落点）
        ⚠️ 不要再给 app_dir 加同名 property：__init__ 里已把它设成实例属性，
        再加会让构造抛 "property has no setter"，所有插件都加载不了。
        """
        return self._manager.plugins_dir

    def reload_plugins(self) -> int:
        """重新扫描并加载 plugins/ 下的全部插件，返回加载成功的数量（不重启即生效）"""
        try:
            self._manager.load_all()
            window = getattr(self._manager, "main_window", None)
            if window is not None:
                page = getattr(window, "pluginInterface", None)
                if page is not None:
                    page.refresh_list()
                home = getattr(window, "homeInterface", None)
                if home is not None:
                    home.refresh_plugins()
            return len([p for p in self._manager.plugins if p.ok])
        except Exception as exc:
            self._log("reload_plugins 失败: %s" % exc, "err")
            return 0

    def open_plugin_config(self, plugin_id: str) -> bool:
        """跳到某个插件的配置界面（插件之间互相跳转用）"""
        window = getattr(self._manager, "main_window", None)
        if window is None:
            return False
        page = getattr(window, "pluginInterface", None)
        if page is None:
            return False
        try:
            if hasattr(window, "switchTo"):
                window.switchTo(page)
            info = None
            for item in self._manager.plugins:
                if item.id == plugin_id:
                    info = item
                    break
            if info is None:
                page.flash_plugin(plugin_id)
                return False
            page.open_config(info)
            return True
        except Exception as exc:
            self._log("打开插件配置界面失败: %s" % exc, "err")
            return False

    def _log(self, message: str, level: str = "info"):
        try:
            self._manager.plugin_log(self.name, str(message), level)
        except Exception:
            pass

    def log(self, message, level: str = "info"):
        """写日志（同时进日志文件和终端）"""
        self._manager.plugin_log(self.name, str(message), level)


class PluginManager:
    """扫描 / 加载 / 启停插件；manifest 写 default_disabled 的插件只在第一次见到时
    自动进 disabled 集合（之后听用户的）。"""

    def __init__(self, app_dir: str, config_dir: str,
                 settings_manager=None, favorites_manager=None, language_manager=None,
                 resource_loader=None):
        """config_dir 传的是**程序配置目录**（.ToolsGCP/config），不是 .ToolsGCP
        插件状态文件 plugins.json 和插件可写目录 plugin_data/ 都落在它下面。
        """
        self.app_dir = app_dir
        # ⚠️ 插件目录在 .ToolsGCP/plugins 下（不是和 .ToolsGCP 并列）。老位置里的
        #    东西由 _migrate_legacy_plugins_dir() 搬过来，老用户升级后插件不会消失。
        self.plugins_dir = os.path.join(app_dir, CONFIG_DIR_NAME, PLUGINS_DIR_NAME)
        self._migrate_legacy_plugins_dir()
        self.data_root = os.path.join(config_dir, DATA_SUBDIR)
        self.state_path = os.path.join(config_dir, STATE_FILE)
        self.notes_path = os.path.join(config_dir, NOTES_FILE)
        self.settings_manager = settings_manager
        self.favorites_manager = favorites_manager
        self.language_manager = language_manager
        # 主窗口引用：由 MainWindow 建好之后回填（插件要用它拿 AgentBridge 等能力）
        self.main_window = None
        self._resource_loader = resource_loader
        self.plugins: list[PluginInfo] = []
        state = self._load_state()
        self.disabled = state["disabled"]
        # 已经播过"默认关闭"种子的插件 id（只播种一次，之后听用户的）
        self._defaults_applied = state["defaults_applied"]
        # 备注 {插件id: 文字} 和启停状态分开存：备注弄丢不该影响插件能不能加载
        self.notes = self._load_notes()

    # ---------- 状态文件 ----------
    def _load_state(self) -> dict:
        """读 plugins.json（坏文件 / 老格式都兜住，永远返回可用结构）"""
        data = {}
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        disabled = data.get("disabled") or []
        applied = data.get("defaults_applied") or []
        return {
            "disabled": {str(x) for x in disabled} if isinstance(disabled, list) else set(),
            "defaults_applied": ({str(x) for x in applied}
                                 if isinstance(applied, list) else set()),
        }

    def _migrate_legacy_plugins_dir(self):
        """把老位置（<程序目录>/plugins）里的插件搬进 .ToolsGCP/plugins
        ⚠️ 三条安全约定：目标已存在的条目一律不动（新位置可能是更新的版本）；
        单条搬失败就跳过它、其它继续搬；整件事永不抛异常。
        搬完若老目录空了就删掉，免得留个空壳继续误导人。
        """
        legacy = os.path.join(self.app_dir, PLUGINS_DIR_NAME)
        if os.path.realpath(legacy) == os.path.realpath(self.plugins_dir):
            return
        if not os.path.isdir(legacy):
            return
        try:
            names = os.listdir(legacy)
        except Exception:
            return
        if not names:
            try:
                os.rmdir(legacy)
            except Exception:
                pass
            return
        try:
            os.makedirs(self.plugins_dir, exist_ok=True)
        except Exception:
            return
        moved, skipped = [], []
        for name in names:
            src = os.path.join(legacy, name)
            dst = os.path.join(self.plugins_dir, name)
            if os.path.exists(dst):
                skipped.append(name)
                continue
            try:
                shutil.move(src, dst)
                moved.append(name)
            except Exception:
                skipped.append(name)
        try:
            from ..utils.logger import log
            log.op("插件", "migrate_dir", 搬家=len(moved), 跳过=len(skipped),
                   到=self.plugins_dir)
        except Exception:
            pass
        # 全搬走了就把老壳删掉；还剩东西（被跳过/搬不动）就留着，绝不删
        try:
            if not os.listdir(legacy):
                os.rmdir(legacy)
        except Exception:
            pass

    def _ensure_plugins_dir(self) -> str:
        """保证插件目录存在并返回它（"打开插件目录"和模板复制都用它）"""
        try:
            os.makedirs(self.plugins_dir, exist_ok=True)
        except Exception:
            pass
        return self.plugins_dir

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump({"disabled": sorted(self.disabled),
                           "defaults_applied": sorted(self._defaults_applied)}, f,
                          ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _seed_default_disabled(self, info: PluginInfo):
        """给 manifest 里声明了 default_disabled 的插件播一次"默认关闭"的种子
        只在第一次见到它时加进 disabled；用户之后手动打开就不会再被改回去。
        """
        try:
            wanted = bool(info.manifest.get("default_disabled"))
        except Exception:
            return
        if not wanted or info.id in self._defaults_applied:
            return
        self._defaults_applied.add(info.id)
        self.disabled.add(info.id)
        self._save_state()

    # ---------- 备注文件 ----------
    def _load_notes(self) -> dict:
        """读插件备注；文件不存在/坏了都当成"没有备注"，不拦启动"""
        try:
            with open(self.notes_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            notes = data.get("notes") if isinstance(data, dict) else None
            if not isinstance(notes, dict):
                return {}
            # 只保留非空字符串，顺手限一下长度（界面上限 20 字，这里放宽一点兜旧数据）
            return {str(k): str(v)[:64] for k, v in notes.items() if str(v or "").strip()}
        except Exception:
            return {}

    def set_note(self, plugin_id: str, note: str):
        """保存一个插件的备注（空字符串 = 删除这条备注）"""
        plugin_id = str(plugin_id or "").strip()
        if not plugin_id:
            return
        note = str(note or "").strip()[:20]
        if note:
            self.notes[plugin_id] = note
        else:
            self.notes.pop(plugin_id, None)
        self._save_notes()
        # 顺手同步到内存里的插件对象，界面刷新时能直接读到
        for info in self.plugins:
            if info.id == plugin_id:
                info.note = note
                break
        try:
            from ..utils.logger import log
            log.op("插件", "note", id=plugin_id, note=note)
        except Exception:
            pass

    def note_of(self, plugin_id: str) -> str:
        return self.notes.get(str(plugin_id or ""), "")

    def _save_notes(self):
        try:
            os.makedirs(os.path.dirname(self.notes_path), exist_ok=True)
            with open(self.notes_path, "w", encoding="utf-8") as f:
                json.dump({"notes": self.notes}, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            try:
                from ..utils.logger import log
                log.err("插件", "note", f"保存备注失败: {exc}")
            except Exception:
                pass

    # ---------- 扫描 ----------
    def _localized(self, value) -> str:
        """取插件 manifest 里某个字段的**当前语言**文案（name / description 允许写成
        {"简体中文": ..., "English": ...}；普通插件继续写字符串，行为不变）"""
        if isinstance(value, dict):
            language = "简体中文"
            if self.language_manager is not None:
                language = getattr(self.language_manager, "current_language", language)
            for key in (language, "简体中文", "zh_CN", "en_US"):
                if value.get(key):
                    return str(value[key])
            return ""
        return str(value or "")

    @staticmethod
    def is_reserved_folder(name: str) -> bool:
        """这个文件夹名要不要当成插件？
        规则（顺序很重要）：下划线 / 点开头的一律跳过（_template、__pycache__、.git）；
        再显式排掉 RESERVED_DIR_NAMES，防止有人把模板改名成不以 _ 开头的名字。
        """
        name = str(name or "")
        if not name or name.startswith(("_", ".")):
            return True
        return name.lower() in {n.lower() for n in RESERVED_DIR_NAMES}

    def discover(self) -> list:
        """扫描 plugins/ 目录，返回插件列表（不加载）
        ⚠️ 绝不递归扫描子目录：只有第一层是插件，插件内部的 core/ ui/ lang/ 是它自己的模块。
        """
        self.plugins = []
        if not os.path.isdir(self.plugins_dir):
            return self.plugins

        for name in sorted(os.listdir(self.plugins_dir)):
            folder = os.path.join(self.plugins_dir, name)
            if not os.path.isdir(folder) or self.is_reserved_folder(name):
                # _template 之类的开发目录：不是插件，连数据目录都不给它建
                continue
            info = PluginInfo(name)
            info.dir = folder
            manifest_path = os.path.join(folder, MANIFEST_NAME)
            if not os.path.exists(manifest_path):
                # 兼容旧插件：找 plugin.json
                legacy = os.path.join(folder, LEGACY_MANIFEST_NAME)
                if os.path.exists(legacy):
                    manifest_path = legacy
                else:
                    info.status = STATUS_MISSING
                    info.error = f"缺少 {MANIFEST_NAME}"
                    info.id = name
                    info.name = name
                    self.plugins.append(info)
                    continue
            try:
                # utf-8-sig：记事本另存的 JSON 常带 BOM，这样也能读
                with open(manifest_path, "r", encoding="utf-8-sig") as f:
                    info.manifest = json.load(f)
            except Exception as e:
                info.status = STATUS_ERROR
                info.error = f"{MANIFEST_NAME} 解析失败: {e}"
                info.id = name
                info.name = name
                self.plugins.append(info)
                continue

            m = info.manifest
            info.id = str(m.get("id") or name)
            # name / description 支持多语言字典（见 _localized）
            info.name = self._localized(m.get("name")) or info.id
            info.version = str(m.get("version") or "")
            info.author = self._localized(m.get("author"))
            info.description = self._localized(m.get("description"))
            info.icon = str(m.get("icon") or "APPLICATION")
            info.protected = bool(m.get("builtin") or m.get("protected"))
            info.entry = str(m.get("entry") or DEFAULT_ENTRY)
            # 默认关闭的内置插件：第一次见到时播种一次（见 _seed_default_disabled）
            self._seed_default_disabled(info)

            entry_path = os.path.join(folder, info.entry)
            if not os.path.exists(entry_path):
                info.status = STATUS_ERROR
                info.error = f"入口文件不存在: {info.entry}"
            elif info.id in self.disabled:
                info.status = STATUS_DISABLED
            else:
                info.status = STATUS_OK
            self.plugins.append(info)

        return self.plugins

    # ---------- 加载 ----------
    def load_all(self) -> list:
        """扫描并加载所有插件
        ⚠️ 停用的插件也会把页面建出来，否则"默认关闭"的插件在插件中心里⚙ 配置界面
        永远是灰的，而它的开关就在那个界面里；停用靠工具/命令的来源过滤不生效。
        """
        self.discover()
        for info in self.plugins:
            # 把备注填进插件对象，界面直接读 info.note 就行
            info.note = self.notes.get(info.id, "")
            if info.status in (STATUS_OK, STATUS_DISABLED):
                self._load_one(info)
                # _load_one 成功会把状态标成 ok，这里按"停用"改回来
                if info.id in self.disabled and info.status == STATUS_OK:
                    info.status = STATUS_DISABLED
        return self.plugins

    def reload_plugin(self, info: PluginInfo):
        """重新加载一个插件
        ⚠️ 停用的插件不销毁页面：以前无条件删掉 info.page，停用后⚙ 配置界面就灰了，
        用户没法"关着进去改配置再打开"。
        """
        if info.id in self.disabled:
            info.status = STATUS_DISABLED
            # 页面保留；只有"以前遗留下来的、此时已经失效的"才清掉
            if info.page is None:
                try:
                    self._load_one(info)
                except Exception:
                    pass
                # 上面可能把它又标成 ok，这里按停用状态改回来
                if info.page is not None:
                    info.status = STATUS_DISABLED
            return info
        # 启用：先卸掉旧页面再重新加载（让插件重新走一遍 create_page）
        if info.page is not None:
            try:
                info.page.setParent(None)
                info.page.deleteLater()
            except Exception:
                pass
            info.page = None
        self._load_one(info)
        return info

    def _load_one(self, info: PluginInfo):
        entry_path = os.path.join(info.dir, info.entry)
        # 每个插件当成独立命名空间的"包"加载：插件内部可以用相对导入，
        # 不同插件里同名的 core/ ui/ 也不会互相覆盖。
        pkg_name = f"toolsgcp_plugin_{info.id.replace('-', '_').replace('.', '_')}"
        stem = os.path.splitext(os.path.basename(info.entry))[0]
        module_name = f"{pkg_name}.{stem}"
        try:
            package = sys.modules.get(pkg_name)
            if package is None:
                package = types.ModuleType(pkg_name)
                sys.modules[pkg_name] = package
            package.__path__ = [info.dir]
            package.__package__ = pkg_name

            spec = importlib.util.spec_from_file_location(module_name, entry_path)
            if spec is None or spec.loader is None:
                raise RuntimeError("无法载入入口文件")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            create_page = getattr(module, "create_page", None)
            if not callable(create_page):
                raise RuntimeError("入口文件里没有 create_page(context) 函数")

            context = PluginContext(self, info)
            page = create_page(context)
            if not isinstance(page, QWidget):
                raise RuntimeError("create_page 必须返回一个 QWidget")

            page.setObjectName(f"plugin_{info.id}")
            info.module = module
            info.page = page
            info.status = STATUS_OK
            info.error = ""
            self.plugin_log(info.name, "插件加载成功")
        except Exception as e:
            info.page = None
            info.status = STATUS_ERROR
            info.error = f"{type(e).__name__}: {e}"
            self.plugin_log(info.name, f"插件加载失败: {info.error}\n"
                                       f"{traceback.format_exc()}", "err")

    # ---------- 启停 ----------
    def set_enabled(self, info: PluginInfo, enabled: bool):
        if enabled:
            self.disabled.discard(info.id)
        else:
            self.disabled.add(info.id)
            # ⚠️ 停用时要撤掉它登记的手和命令提示，否则"插件关了，输入框上面还挂着
            #    它的命令、AI 还能用它干活"。
            try:
                from .ai.agent_tools import get_registry
                get_registry().unregister_source(info.id)
            except Exception:
                pass
            try:
                from .ai.chat_hints import get_hint_registry
                get_hint_registry().unregister_prefix(info.id)
            except Exception:
                pass
            # ⚠️ 页面不销毁：以前停用会删掉 info.page，卡片上的⚙ 配置界面就灰了，
            #    而用户恰恰要"关着也能进去配置"。留着只是不生效，下次启用直接复用。
        # ⚠️ 关 Agent 要连坐停用制作器生成的插件：生成动作是一次 AI 工具往返，Agent 一关
        #    它们就是空壳，亮着会让用户以为还能用。只在这一条链上连坐。
        if not enabled and info.id in MAKER_COMPANION_IDS:
            self._disable_maker_plugins(reason=info.name)
        # ⚠️ 反过来单独关 Agent 时也要带上插件制作辅助（制作每一步都靠 Agent 的手）；
        #    反方向只开不关（开制作辅助会带上 Agent，见 _disable_related_plugin 的说明）。
        if not enabled and info.id == AI_AGENT_PLUGIN_ID:
            self._disable_related_plugin(MAKER_PLUGIN_ID, reason=info.name)
        self._save_state()

    def _disable_maker_plugins(self, reason: str = "") -> int:
        """把"制作器生成的插件"全部停用（返回停用了几个）
        靠 manifest 里的 `generated_by` 认人；生成物自己的 generated_by 不是制作器，
        所以内部递归调 set_enabled 也不会无限递归。
        """
        count = 0
        for other in list(self.plugins):
            if other.id == MAKER_PLUGIN_ID or other.status != STATUS_OK:
                continue
            try:
                generated_by = str((other.manifest or {}).get("generated_by") or "")
            except Exception:
                generated_by = ""
            if generated_by != MAKER_PLUGIN_ID:
                continue
            try:
                self.set_enabled(other, False)
                self.reload_plugin(other)
                count += 1
            except Exception:
                pass
        if count:
            try:
                self.plugin_log("管理器",
                                f"「{reason or MAKER_PLUGIN_ID}」已关闭，"
                                f"随之停用了 {count} 个由它生成的插件")
            except Exception:
                pass
        return count

    def _disable_related_plugin(self, plugin_id: str, reason: str = "") -> bool:
        """把另一个内置插件一起停用（返回是否真的停了它）
        用途：Agent 插件被关掉时把插件制作辅助一起停用。
        ⚠️ 只处理"当前确实开着"的那个；顺手把它自己声明的总开关设置也关掉，
        否则用户进配置界面会看到"插件已停用 / 总开关却开着"。
        """
        if plugin_id in self.disabled:
            return False
        for other in list(self.plugins):
            if other.id != plugin_id:
                continue
            try:
                self.set_enabled(other, False)
                self.reload_plugin(other)
                self.sync_enabled_setting(other, False)
                self.plugin_log("管理器",
                                f"随「{reason or AI_AGENT_PLUGIN_ID}」一起停用了「{other.name}」")
            except Exception:
                return False
            return True
        return False

    def sync_enabled_setting(self, info: PluginInfo, enable: bool):
        """把插件中心那个开关同步到插件自己声明的"总开关"设置项
        manifest 里写 `"enabled_setting": "..."` 的插件，被开关时那条设置也跟着改。
        ⚠️ 这是唯一的同步口；优先用主窗口上那份设置管理器（写错对象会表现成"开关拨了、
        功能没生效"）；写失败不能影响开关本身。
        """
        try:
            key = str((getattr(info, "manifest", None) or {}).get("enabled_setting") or "").strip()
        except Exception:
            return
        if not key:
            return
        settings = None
        try:
            window = getattr(self, "main_window", None)
            settings = getattr(window, "settings_manager", None) if window else None
        except Exception:
            settings = None
        if settings is None:
            settings = getattr(self, "settings_manager", None)
        if settings is None:
            return
        try:
            settings.update_setting(key, bool(enable))
        except Exception:
            pass

    # ---------- 其它 ----------
    def get_resources(self) -> list:
        if self._resource_loader is None:
            from .resource_loader import ResourceLoader
            self._resource_loader = ResourceLoader()
            self._resource_loader.load_from_local()
        return self._resource_loader.get_all()

    def plugin_log(self, plugin_name: str, message: str, level: str = "info"):
        from ..utils.logger import log
        if level == "err":
            log.err("插件", plugin_name, message)
        else:
            log.info("插件", plugin_name, message)

    def create_from_template(self, new_id: str):
        """从 _template 复制出一个新插件，返回 (是否成功, 提示)
        ⚠️ 这是开发动作：只有它读得到 plugins/_template，正常启动流程永远跳过该目录，
        所以模板不会进插件列表、没有数据目录、也不会被当成能打开的插件。
        """
        import re
        import shutil
        new_id = str(new_id or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9\-_]{1,40}", new_id):
            # 文案与上面那条正则一致：首字符 + 再 1~40 个 = **总长 2~41** 个字符。
            # （以前这里写"2~40 位"，和正则差一个字符，41 位的合法 id 会被说成不合法。）
            return False, "插件 id 只能用 2~41 位小写字母、数字、连字符或下划线"
        if self.is_reserved_folder(new_id):
            return False, f"{new_id} 是保留名字，换一个吧"
        template = os.path.join(self.plugins_dir, TEMPLATE_DIR_NAME)
        if not os.path.isdir(template):
            return False, "找不到 _template 模板目录"
        target = os.path.join(self.plugins_dir, new_id)
        if os.path.exists(target):
            return False, f"已经有一个叫 {new_id} 的插件了"
        try:
            # 跳过 __pycache__：那是模板自己跑出来的字节码缓存，复制过去会带着旧路径
            shutil.copytree(template, target,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            manifest_path = os.path.join(target, MANIFEST_NAME)
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            manifest["id"] = new_id
            manifest["name"] = new_id
            # ⚠️ Web 版真正读的 enabled_setting 必须跟着改：模板里写的是
            #    `plugin_my_plugin_enabled`，不改的话**所有**从模板复制出来的插件
            #    共用同一个设置键 —— 关掉 A 插件，B 插件的开关也一起变灰。
            #    键名规则与 config.html 的约定一致：plugin_ + id（- 换成 _）+ _enabled。
            if manifest.get("enabled_setting"):
                manifest["enabled_setting"] = (
                    "plugin_" + new_id.replace("-", "_").replace(".", "_") + "_enabled")
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return False, str(e)
        return True, new_id
