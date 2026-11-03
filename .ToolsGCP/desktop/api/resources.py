"""资源库 + 收藏 + 配置 的 API 域（`window.pywebview.api.resources / favorites / settings`）。
========== 分层约定 ==========
    pymodels/core/*   —— 业务本体（**原样复用**：ResourceLoader / resource_schema /
                        FavoritesManager / SettingsManager / cloud_resource_source）
    desktop/api/*     —— 只做三件事：① 把 JSON 化不了的对象转成 dict；
                        ② 把异常转成 `{"ok": False, "error": ...}`；
                        ③ 加一点"跨页面共用"的缓存（原版每个页面各自 new 一个
                        ResourceLoader、各读一遍 JSON，Web 版没这个必要）。
⚠️ 这一层**不许 import PyQt5**，也不许写任何界面逻辑。
⚠️ 算法一律不在这里重写：搜索/筛选/排序/分组全部委托给
   `pymodels/core/resource_query.py`（那份实现已通过与原版 Qt UI 代码的差分自检）。
"""

import os
import threading

from pymodels.constants import APP_NAME, APP_VERSION, CONFIG_DIR, DATA_DIR
from pymodels.core import cloud_resource_source, resource_query, resource_schema
from pymodels.core.cloud_resource_source import CloudResourceSource, resolve_resource_file
from pymodels.core.favorites_manager import (DEFAULT_FOLDER, display_folder_name,
                                             FavoritesManager)
from pymodels.core.resource_loader import ResourceLoader
from pymodels.core.settings_manager import SettingsManager


def _ok(**kwargs):
    payload = {"ok": True}
    payload.update(kwargs)
    return payload


def _fail(message, **kwargs):
    payload = {"ok": False, "error": str(message or "unknown error")}
    payload.update(kwargs)
    return payload


def _log(level: str, category_zh: str, category_en: str, message: str, **fields):
    try:
        from pymodels.utils.logger import log
        getattr(log, level, log.info)(category_zh, category_en, message, **fields)
    except Exception:
        pass


class _LibraryCache:
    """进程内共享的资源库缓存（原版每个页面各 new 一个 loader、各读一遍 JSON）
    ⚠️ 这是**新增的性能优化**，但必须保证"对外行为与原版一致"：
       · 原版每次 `reload_resources()` 都会重新读盘 —— 这里提供 `reload()` 做同样的事；
       · 读盘失败/文件不存在时，原版返回 False 并保留上一次的数据；这里同样保留，
         并由调用方决定怎么提示。
    ⚠️ 加锁：js_api 回调跑在工作线程（`webview/util.py:247`），可能并发进来。
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._loader = None
        self._path = ""
        self._language = ""
        self._mtime = 0.0
        self._error = ""

    def loader(self, settings_manager, language: str = "简体中文",
               force: bool = False) -> ResourceLoader:
        with self._lock:
            # trigger_refresh=True：云端还没有缓存时顺手起后台线程去拉（**不阻塞**这里）。
            # ⚠️ 只在"读资源库"这条业务路径上懒触发；设置页显示路径之类的调用不触发。
            path = resolve_resource_file(settings_manager, trigger_refresh=True)
            language = language or "简体中文"
            try:
                mtime = os.path.getmtime(path) if os.path.exists(path) else 0.0
            except Exception:
                mtime = 0.0

            need = (force or self._loader is None
                    or path != self._path or language != self._language
                    or (mtime and mtime != self._mtime))
            if not need:
                return self._loader

            loader = ResourceLoader(resource_file=path, language=language)
            loaded = False
            try:
                loaded = bool(loader.load_from_local())
            except Exception as exc:                # noqa: BLE001
                self._error = str(exc)
                _log("err", "资源库", "load", f"加载资源库异常: {exc}")
            if loaded:
                self._loader = loader
                self._path = path
                self._language = language
                self._mtime = mtime
                self._error = ""
            elif self._loader is None:
                # 从没成功过：留一个空 loader（让上层拿到空列表而不是 None）
                self._loader = loader
                self._path = path
                self._language = language
                if not self._error:
                    self._error = f"资源库加载失败: {path}"
            return self._loader

    def invalidate(self):
        with self._lock:
            self._loader = None
            self._mtime = 0.0


class SettingsDomain:
    """配置读写（原版 SettingsManager 的门面）"""

    def __init__(self, shell):
        self._shell = shell

    @property
    def manager(self) -> SettingsManager:
        return self._shell.settings_manager

    def get(self, key: str = ""):
        """读一个键；不传 key 就返回整份设置（敏感键会被清空）
        ⚠️ 原版 `SettingsManager.settings` 是内存里那份，这里读的是同一份 ——
           所以"设置改了界面没变"这类联动问题，前端只要重新拉一次就同步了。
        """
        try:
            manager = self.manager
            if key:
                return _ok(key=key, value=manager.settings.get(key))
            data = dict(manager.settings)
            for secret in ("api_key", "api_key_enc", "license_key", "dev_mode_key"):
                if secret in data:
                    data[secret] = ""
            return _ok(settings=data)
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def set(self, key: str, value, notify: bool = False):
        """改一个设置（落盘 + 记 OP 日志，与原版 `update_setting` 完全一致）
        ⚠️ 原版的 `update_setting(key, value)` 会把**全量设置**写盘并记一条
           `log.op("设置","update", key=, old=, new=)`。这里保持同一条链路，
           不另写一份写盘逻辑（否则日志格式和打码规则就不一致了）。
        ⚠️ `notify=True` 时额外向前端广播 `settings-changed`，方便其它页面联动；
           原版是用 pyqtSignal 广播的（`favorites_changed` 那类），Web 版等价物就是它。
        """
        try:
            manager = self.manager
            old = manager.settings.get(key)
            manager.update_setting(key, value)
            if notify:
                self._shell.push_event("settings-changed",
                                       {"key": key, "old": old, "new": value})
            return _ok(key=key, old=old, new=manager.settings.get(key))
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def set_api_key(self, value: str = "", provider: str = ""):
        """保存某个服务商的 API Key（DPAPI 加密后写该服务商槽，明文旧槽清空）
        ⚠️ `provider` 必须跟着前端当前选中的服务商传（ai_provider），
           否则切过服务商后会把 Key 存错槽，聊天时后端又读不到。
        """
        try:
            self.manager.set_api_key(str(value or ""), provider)
            # ⚠️ 走一遍 notify，让设置页/其它页面知道"key 变了"
            pid = self.manager._normalize_provider(provider)
            value = self.manager.get_api_key(provider) or ""
            return _ok(configured=bool(value), length=len(value), provider=pid)
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def api_key_state(self, provider: str = ""):
        """给前端看的"API Key 配置状态"（**不回传明文**，只回长度/是否已配置）
        ⚠️ 原版设置页要显示"已保存/未保存"和"显示/隐藏"，Web 端不把密钥送到前端，
           只回一个标记；需要明文时由设置页显式调 `reveal_api_key()`。
        """
        try:
            value = self.manager.get_api_key(provider) or ""
            return _ok(configured=bool(value), length=len(value),
                       provider=self.manager._normalize_provider(provider))
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def reveal_api_key(self, provider: str = ""):
        """显式取某个服务商的明文（设置页"显示"按钮用；这是唯一回传明文的入口）"""
        try:
            return _ok(value=self.manager.get_api_key(provider) or "",
                       provider=self.manager._normalize_provider(provider))
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def paths(self):
        """给前端/排查用的路径信息"""
        try:
            return _ok(app=APP_NAME, version=APP_VERSION,
                       config_dir=CONFIG_DIR, data_dir=DATA_DIR,
                       resource_file=resolve_resource_file(self.manager))
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    # ================= 存储位置（原版 interfaces/settings/cards_storage.py）=================
    # 需求原话：设置中的存储区域的存储位置是**更改位置**，而不是现在这个打开文件夹的意思。
    # 原版行为（cards_storage.py）：
    #   ① 只读地址框显示当前 .ToolsGCP 目录 + 位置记录文件ToolsGCP.json 路径；
    #   ② 更改→ QFileDialog 选目录 → 在下面建 .ToolsGCP → 校验 → **弹确认框**（路径单独一行）
    #      → 后台线程迁移 → 进度条 + 完成提示；
    #   ③ 恢复默认→ reset_to_default_root()。
    # 这里把 ②③ 的**内核**原样搬到 Web 版（选目录 = 系统对话框；迁移 = core/data_root）。
    #⚠️ 数据根语义已恢复为 py 版（见 core/data_root.py 开头）：
    #    默认数据根 = `<用户主目录>\.ToolsGCP`（python 自动创建）；
    #    指针 = `<用户主目录>\ToolsGCP.json`，固定在主目录，不随迁移改变位置；
    #    程序目录旁的 .ToolsGCP **只是资源**（modules/images/resources/plugins），
    #    既不作为默认值、也不允许被选成数据根（validate_target 会拒绝）。
    #    首次真实启动时 core/data_root 会把旧 web 版误存进程序目录的 config/logs
    #    一次性复制到用户主目录（幂等，源保留作备份），所以这里无需额外处理。
    # ⚠️ 迁移是**真剪切**（用户反馈"只是复制，旧 .ToolsGCP 还在"）：
    #   `data_root.migrate_data_root()` 会把白名单数据搬走后删掉旧根（旧根若是程序
    #    资源目录，只清空其中的 config/logs）；被 logger 占用的 `logs/system_log.log`
    #    当次搬不动，会写 `<新根>/config/.pending_migration_cleanup.json`，
    #    下次启动由 core/data_root 自动补搬并清理旧目录（前端只需提示"重启后完全生效"）。
    #    这里返回的 message 已经区分完全剪切成功 / 部分待下次启动两档。
    @property
    def _migrate_state(self) -> dict:
        state = getattr(self, "_mig_state", None)
        if state is None:
            # ⚠️ 键名不能叫 "ok"：_ok(**state) 里的 "ok" 会覆盖掉信封自带的 ok=True，
            #    前端就会把"进度查询成功"当成失败（曾经的真实 bug）。统一改叫 success。
            state = {"running": False, "done": 0, "total": 0, "text": "",
                     "percent": 0, "success": False, "message": "", "finished": False}
            self._mig_state = state
            self._mig_lock = threading.Lock()
        return state

    def data_root_info(self):
        r"""当前数据根 + 指针文件 + 默认位置（设置页存储板块用）
        `root` = 当前生效的数据根（指针优先，否则 `<用户主目录>\.ToolsGCP`）；
        `pointer` = `<用户主目录>\ToolsGCP.json`（位置记录文件，固定在主目录）；
        `default` = `<用户主目录>\.ToolsGCP`（"恢复默认"会回到这里）；
        `current` = constants.DATA_DIR（即 root/config，给排查用）；
        `pending` = 上次迁移被占用、等下次启动补搬的清单（没有就是 {}，排查用）。
        前端新版只显示"存储位置"一行，但接口字段保留，老前端也不会挂。
        """
        try:
            from pymodels.core import data_root
            return _ok(root=data_root.resolve_data_root(),
                       pointer=data_root.pointer_file_path(),
                       default=data_root.default_data_root(),
                       current=DATA_DIR,
                       pending=data_root.pending_cleanup_info())
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def pick_data_root(self):
        """弹选择文件夹并算好新的 .ToolsGCP 目录（**只选不定**，不迁移）
        返回 `{ok, path, canceled}`；同一目录 / 目标非法 / 选到当前数据目录里面
        都返回 ok=False 并带原因，前端在弹确认框之前就能拦下来（对齐原版 validate_target 那一步）。
        """
        try:
            from pymodels.core import data_root
            current = data_root.resolve_data_root()
            picked = self._shell.pick_folder(
                title="选择新的存放位置",
                initial=os.path.dirname(current) or current)
            if not picked:
                return _ok(canceled=True, path="", current=current)
            chosen = os.path.normpath(picked)
            # 用户直接选到 .ToolsGCP 本身就用它，否则在下面建一个（原版同款规则）
            new_root = chosen if os.path.basename(chosen).lower() == ".toolsgcp" \
                else os.path.join(chosen, ".ToolsGCP")
            if os.path.normcase(os.path.abspath(new_root)) == \
                    os.path.normcase(os.path.abspath(current)):
                return _fail("新位置和当前位置是同一个目录", same=True, current=current)
            # 选到当前数据根里面 → 迁移会自我嵌套（搬完删旧根把新数据删掉），提前拦住
            if data_root.is_inside_data_root(new_root):
                return _fail("不能选当前存储目录里面的文件夹", invalid=True, current=current)
            ok, reason = data_root.validate_target(new_root)
            if not ok:
                return _fail(reason, invalid=True, current=current)
            return _ok(canceled=False, path=new_root, current=current)
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def migrate_data_root(self, path: str = ""):
        """把 .ToolsGCP **剪切**到新位置（**后台线程**，立即返回；进度用 data_root_progress 轮询）
        ⚠️ 真剪切在 core/data_root.migrate_data_root：旧目录会被清掉；被 logger 占用的
           `logs/system_log.log` 会留待下次启动补搬（待清理清单），message 会说明。
        """
        target = str(path or "").strip()
        if not target:
            return _fail("没有指定新的存放位置")
        state = self._migrate_state
        with self._mig_lock:
            if state.get("running"):
                return _fail("已经在迁移中了")
        try:
            from pymodels.core import data_root
            ok, reason = data_root.validate_target(target)
            if not ok:
                return _fail(reason)
            # 新位置在当前数据目录里面 → 迁移会自我嵌套（搬完删旧根会把新数据一起删掉）。
            # 注意"和当前位置相同"不算：那会在后台线程里直接返回"无需迁移"。
            current = data_root.resolve_data_root()
            if (os.path.normcase(os.path.abspath(target))
                    != os.path.normcase(os.path.abspath(current))
                    and data_root.is_inside_data_root(target)):
                return _fail("新位置不能放在当前存储目录里面（会造成自我嵌套）")
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)
        with self._mig_lock:
            state.update({"running": True, "done": 0, "total": 0, "text": "正在准备…",
                          "percent": 0, "success": False, "message": "", "finished": False})
        _log("op", "设置", "storage", f"开始迁移 .ToolsGCP → {target}")

        def _report(done, total, text):
            total = max(1, int(total or 1))
            with self._mig_lock:
                state.update({"done": int(done or 0), "total": total,
                              "text": str(text or ""),
                              "percent": int(max(0, min(100, round((done or 0) * 100.0 / total))))})

        def _work():
            try:
                ok, message = data_root.migrate_data_root(target, progress_cb=_report)
            except Exception as exc:                # noqa: BLE001
                ok, message = False, str(exc)
            with self._mig_lock:
                state.update({"running": False, "finished": True, "success": bool(ok),
                              "message": str(message or ""),
                              "percent": 100 if ok else state.get("percent", 0)})
            _log("info" if ok else "err", "设置", "storage",
                 f"迁移 .ToolsGCP 结束 ok={ok} msg={message}")

        threading.Thread(target=_work, name="ToolsGCP-data-root", daemon=True).start()
        return _ok(started=True, path=target)

    def data_root_progress(self):
        """迁移进度（前端每 200ms 拉一次）"""
        try:
            state = self._migrate_state
            with self._mig_lock:
                return _ok(**dict(state))
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def reset_data_root(self):
        r"""恢复默认数据根 = `<用户主目录>\.ToolsGCP`（原版 cards_storage.py 的恢复默认）
        ⚠️ 默认位置由 data_root.default_data_root() 算，恢复 py 语义后它永远是用户主目录，
           不是程序目录旁的资源 .ToolsGCP。
        """
        try:
            from pymodels.core import data_root
            ok, message = data_root.reset_to_default_root()
            # ⚠️ 同样不能用 "ok" 当字段名（会覆盖信封的 ok=True），用 success。
            return _ok(success=bool(ok), message=str(message or ""),
                       root=data_root.resolve_data_root())
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)


class FavoritesDomain:
    """收藏夹（原版 FavoritesManager 的门面）
    ⚠️ 所有写操作都会通过 `push_event("favorites-changed")` 广播 —— 原版是靠
       `favorites_changed` 信号在搜索页 / 收藏页 / 定制页之间同步的，Web 版等价物。
    """

    def __init__(self, shell):
        self._shell = shell

    @property
    def manager(self) -> FavoritesManager:
        return self._shell.favorites_manager

    def _changed(self, action: str = "", **fields):
        self._shell.push_event("favorites-changed",
                               {"action": action, **fields})

    def list(self, language: str = ""):
        """全部收藏夹：名称 + 数量 +（默认夹的）显示名 + 该夹的编码列表
        ⚠️ 原版左侧列表显示的是 `display_folder_name()` 的结果（默认夹要按语言翻译），
           但**内部身份**仍是 `"Default"`（筛选、存储都按它走）。
           这里两个都给：`folders[].name` = 内部身份，`label` = 显示名。
        """
        try:
            manager = self.manager
            lang = language or self._shell.current_language()
            folders = []
            for name in manager.folders():
                folders.append({
                    "name": name,
                    "label": display_folder_name(name, lang),
                    "count": manager.count(name),
                    "items": manager.folder_items(name),
                    "is_default": name == DEFAULT_FOLDER,
                })
            return _ok(folders=folders, total=len(manager.all_codes()),
                       default=DEFAULT_FOLDER,
                       default_label=manager.default_folder_label(lang))
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def all_codes(self):
        try:
            return _ok(codes=sorted(self.manager.all_codes()))
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def is_favorite(self, code: str = ""):
        try:
            code = str(code or "")
            return _ok(code=code, favorite=self.manager.is_favorite(code),
                       folder=self.manager.folder_of(code))
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def toggle(self, code: str = "", folder: str = ""):
        """切换收藏状态，返回切换后的状态（True = 已收藏）"""
        try:
            code = str(code or "")
            if not code:
                return _fail("code 不能为空")
            state = self.manager.toggle(code, folder or None)
            self._changed("toggle", code=code, favorite=state,
                          folder=self.manager.folder_of(code))
            return _ok(code=code, favorite=state,
                       folder=self.manager.folder_of(code))
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def add(self, code: str = "", folder: str = ""):
        try:
            code = str(code or "")
            if not code:
                return _fail("code 不能为空")
            added = self.manager.add(code, folder or None)
            if added:
                self._changed("add", code=code, folder=folder or DEFAULT_FOLDER)
            return _ok(code=code, added=added,
                       folder=self.manager.folder_of(code))
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def remove(self, code: str = "", folder: str = ""):
        try:
            code = str(code or "")
            if not code:
                return _fail("code 不能为空")
            removed = self.manager.remove(code, folder or None)
            if removed:
                self._changed("remove", code=code, folder=folder or "全部")
            return _ok(code=code, removed=removed)
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def move(self, code: str = "", from_folder: str = "", to_folder: str = ""):
        """把一条收藏从 A 夹移到 B 夹（原版 move：先 remove 再 add）"""
        try:
            code = str(code or "")
            moved = self.manager.move(code, from_folder, to_folder)
            if moved:
                self._changed("move", code=code, **{"from": from_folder, "to": to_folder})
            return _ok(code=code, moved=moved)
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def move_many(self, codes=None, from_folder: str = "", to_folder: str = ""):
        """批量移动（原版收藏页"确定移动"：逐条 move + 统计成功数）
        ⚠️ 原版**没有事务**：部分失败只体现在计数上（"已把 {n} 项移动到…"）。
           这里保持同样语义，不引入回滚。
        """
        try:
            codes = [str(c) for c in (codes or []) if str(c or "").strip()]
            moved = 0
            for code in codes:
                try:
                    if self.manager.move(code, from_folder, to_folder):
                        moved += 1
                except Exception:
                    continue
            if moved:
                self._changed("move_many", count=moved,
                              **{"from": from_folder, "to": to_folder})
            return _ok(moved=moved, total=len(codes),
                       folder=display_folder_name(to_folder, self._shell.current_language())
                       if to_folder == DEFAULT_FOLDER else to_folder)
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    # ---------- 收藏夹增删改 ----------
    def create_folder(self, name: str = ""):
        """返回 (是否成功, 提示)；⚠️ 提示可能是"语言键"（如 default_folder_reserved），
        前端要按语言键翻译 —— 这与原版一致（原版把这种字符串直接交给 i18n 层）。"""
        try:
            ok, message = self.manager.create_folder(name)
            if ok:
                self._changed("create_folder", name=name)
            return _ok(created=ok, name=message if ok else "",
                       message="" if ok else message)
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def rename_folder(self, old: str = "", new: str = ""):
        try:
            ok, message = self.manager.rename_folder(old, new)
            if ok:
                self._changed("rename_folder", **{"from": old, "to": new})
            return _ok(renamed=ok, name=message if ok else "",
                       message="" if ok else message)
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def delete_folder(self, name: str = ""):
        try:
            ok, message = self.manager.delete_folder(name)
            if ok:
                self._changed("delete_folder", name=name)
            return _ok(deleted=ok, name=message if ok else "",
                       message="" if ok else message)
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)


# 提交软件（制作器）需要的三语言字段。
# ⚠️ 这四个字段在磁盘上是 {简体中文, 繁體中文, English} 字典，
#    但 normalize()（唯一读数入口）会把它们压成"当前语言"的字符串。
#    制作器要把三种语言都灌进表单，就必须拿回**原始字典** —— 见 _merge_raw_i18n。
# ⚠️ 字段清单直接取自 resource_schema.I18N_FIELDS（由 FIELDS 里 kind=="i18n" 推导），
#    别在这里再硬编码一份 —— 加字段时只改 schema 一处。
DETAIL_I18N_FIELDS = tuple(resource_schema.I18N_FIELDS)


def _merge_raw_i18n(item: dict, raw: dict) -> dict:
    """把规范形态条目里的多语言字段换回**原始三语言字典**（详情接口专用）
    ⚠️ 返回的是**新字典**（浅拷贝 + 替换几个字段），绝不改内存索引里的那份 ——
       其它消费方（get_all / get_summaries / resource_query）拿到的仍然是字符串。
    ⚠️ 磁盘上本来就写成纯字符串的字段保持字符串不动（raw 里没有它），
       前端据此回退到"只灌简体中文"的老行为。
    """
    if not isinstance(item, dict):
        return {}
    out = dict(item)
    for field in DETAIL_I18N_FIELDS:
        value = (raw or {}).get(field)
        if isinstance(value, dict) and value:
            out[field] = value
    return out


class ResourcesDomain:
    """资源库（扫描 / 查询 / 详情 / 筛选选项）
    ⚠️ 方法命名对照原版：
        reload()        ≈ SearchInterface.reload_resources()
        all()           ≈ ResourceLoader.get_summaries()（卡片用的轻量字段）
        detail(code)    ≈ 点击卡片后 `get_by_code` + 详情页需要的完整字段
        query()         ≈ `_apply_filters`（关键词 + 筛选）
        groups()        ≈ `AppsIndexFramework.set_data()` 里的分组
        filter_options()≈ `_reload_filter_options` 的选项集
    """

    def __init__(self, shell):
        self._shell = shell
        self._cache = _LibraryCache()
        # ⚠️ 最新集合在**原版里是搜索页的实例状态**（`self._latest_codes`），
        #    生命周期 = "筛选条件变化时刷新一次，之后一直用到下次筛选变化"。
        #    这里做成域级缓存，由前端显式调 `refresh_latest()` 刷新，
        #    语义与原版一致（不自动算，见 resource_query.query 的说明）。
        self._latest = set()
        self._latest_lock = threading.RLock()
        # 云端资源库：后台线程把新缓存写好后回调这里 → 丢内存索引 + 通知前端。
        # ⚠️ 注册在 core 层的"通知位"上（core 不认识 shell，见 cloud_resource_source）。
        cloud_resource_source.set_notifier(self._on_cloud_updated)
        # 启动时后台刷新（cloud_refresh_async）的状态位。
        # ⚠️ 为什么单独一个锁：后台刷新是**守护线程**，可能和 js_api 回调并发进来
        #    → 必须保证"同一时刻只有一条刷新在跑"（否则重复打 GitHub API = 限流）。
        self._cloud_bg_lock = threading.RLock()
        self._cloud_bg_running = False

    # ---------- 云端资源库 ----------
    def _on_cloud_updated(self, result: dict):
        """后台线程回调：云端缓存已更新 → 作废内存索引 + 推送事件
        ⚠️ 这里可能在**任意后台线程**里被调用：
            · 先丢索引（用锁保护，其它线程下次读会重新载入）；
            · 推前端前必须自己再查一次 `_teardown_started`（AGENTS 第 8 条：
              WebView2 比主窗口先销毁，退出竞态里调前端会抛 ObjectDisposedException）。
        """
        try:
            if not isinstance(result, dict) or not result.get("updated"):
                return
            self._cache.invalidate()
            if getattr(self._shell, "_teardown_started", False):
                return
            self._shell.push_event("cloud-resources-updated", {
                "version": str(result.get("version") or ""),
                "count": int(result.get("count") or 0),
                "path": str(result.get("path") or ""),
            })
        except Exception as exc:                    # noqa: BLE001
            _log("warn", "资源库", "cloud", f"云端资源更新回调异常: {exc}")

    def cloud_status(self):
        """云端资源库状态（设置 → 资源来源 下面那行轻量提示）
        返回 `{ok, configured, available, version, updated_at, count, error, path, tag, repo}`
            configured = 仓库地址是否配置（正常恒 True）
            available  = 本地缓存是否可用（有缓存才渲染"v{version}（{count} 条）"）
            version    = release tag（去掉 v 前缀）
            updated_at = 拉取时间（本地 ISO 时间串，前端 new Date() 可直接解析）
            count      = 缓存里的资源条数
            error      = 失败机器码（NETWORK/BAD_RESPONSE/RATE_LIMITED/NO_RELEASE/NO_ASSET/INVALID_JSON）
            error_key  = 机器码对应的语言键（cloud_error_XXX），界面查文案用；没失败就是空串
            path       = 缓存文件路径
        ⚠️ 这是**纯读**接口（不联网、不阻塞）：网络动作交给 `cloud_refresh()` 或后台线程。
        """
        try:
            return _ok(**CloudResourceSource().status())
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    # ---------- 启动时加载云端资源库（3 次 × 60s）+ 重试 ----------
    def cloud_prepare(self, force: bool = False):
        """程序启动时调用：云端模式才真正等它加载完（重试策略 3 次 × 60s）
        即：启动时检测到云端模式就等待加载，加载不出来重试 3 次（每次 60 秒超时）
        后才报错。
        返回：
            `{ok, skipped, updated, version, count, path, error, error_key, attempts}`
            · skipped=True = 当前不是云端模式（本地读取 / 已有可用缓存且不强制刷新）→ 立即返回；
            · ok=False 且 error=机器码 = 连续 attempts 次都失败（保留旧缓存）；
            · 全程只在 js_api 工作线程里跑，不阻塞 GUI（前端启动页显示"正在加载云端资源库…"）。
        ⚠️ 已有可用缓存时不阻塞启动：直接用缓存（除非 force=True）。
        """
        try:
            from pymodels.core.cloud_resource_source import (
                CloudResourceSource, resolve_resource_file, CLOUD_CACHE_FILE)
            manager = self._shell.settings_manager if self._shell else None
            source_mode = "cloud"
            if manager is not None:
                source_mode = str(manager.settings.get("resource_source") or "cloud")
            if source_mode != "cloud":
                return _ok(skipped=True, updated=False, version="", count=0,
                           path="", error="", attempts=0)
            cacher = CloudResourceSource()
            # 有可用缓存且不强制 → 直接用它（启动不该被"检查更新"拖住）
            if not force and cacher.get_index_path():
                info = cacher.status()
                return _ok(skipped=True, updated=False,
                           version=str(info.get("version") or ""),
                           count=int(info.get("count") or 0),
                           path=str(info.get("path") or ""), error="", attempts=0)
            result = cacher.fetch(force=bool(force))
            if result.get("ok"):
                if result.get("updated"):
                    self._cache.invalidate()
                return _ok(skipped=False, updated=bool(result.get("updated")),
                           version=str(result.get("version") or ""),
                           count=int(result.get("count") or 0),
                           path=str(result.get("path") or ""), error="",
                           attempts=int(getattr(cacher, "startup_attempts", 3)))
            code = str(result.get("error") or "unknown")
            return _fail(code, skipped=False, updated=False,
                         version=str(result.get("version") or ""),
                         count=int(result.get("count") or 0),
                         path=str(result.get("path") or ""),
                         error=code, error_key="cloud_error_" + code,
                         attempts=int(getattr(cacher, "startup_attempts", 3)))
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc, skipped=False, updated=False, version="", count=0,
                         path="", error=str(exc), error_key="", attempts=3)

    def cloud_retry(self):
        """设置页云端资源库右侧重试图标：强制重新拉取（一次完整重试链）"""
        try:
            from pymodels.core.cloud_resource_source import CloudResourceSource
            cacher = CloudResourceSource()
            result = cacher.fetch(force=True)
            if result.get("ok"):
                if result.get("updated"):
                    self._cache.invalidate()
                return _ok(updated=bool(result.get("updated")),
                           version=str(result.get("version") or ""),
                           count=int(result.get("count") or 0),
                           path=str(result.get("path") or ""), error="")
            code = str(result.get("error") or "unknown")
            return _fail(code, updated=False,
                         version=str(result.get("version") or ""),
                         count=int(result.get("count") or 0),
                         path=str(result.get("path") or ""),
                         error=code, error_key="cloud_error_" + code)
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc, updated=False, version="", count=0, path="",
                         error=str(exc), error_key="")

    def cloud_refresh(self, force: bool = False):
        """立刻检查云端有没有更新（设置页立即检查/ 切到云端时调）
        返回 `{ok, updated, version, count, path, error}`：
            updated=True  = 本次调用真的换了新缓存（False 且 ok=True 表示"已是最新"/304）
        失败时 `ok=False` + `error=机器码`，并且**保留旧缓存**（界面显示"拉取失败（原因）"）。
        ⚠️ 这里同步跑网络（最长 8s×重试×镜像，见 core 的 TOTAL_DEADLINE 20s）：
            js_api 回调本来就在工作线程，不会卡 UI；前端自己有"正在检查…"状态。
        ⚠️ 拉到新数据后必须让内存索引失效，否则前端读到的还是旧索引。
        """
        try:
            source = CloudResourceSource()
            result = source.refresh(force=bool(force))
            if result.get("ok"):
                if result.get("updated"):
                    self._cache.invalidate()
                return _ok(updated=bool(result.get("updated")),
                           version=str(result.get("version") or ""),
                           count=int(result.get("count") or 0),
                           path=str(result.get("path") or ""),
                           error="")
            return _fail(str(result.get("error") or "unknown"),
                         updated=False,
                         version=str(result.get("version") or ""),
                         count=int(result.get("count") or 0),
                         path=str(result.get("path") or ""),
                         error_key=("cloud_error_" + str(result.get("error") or ""))
                         if result.get("error") else "")
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc, updated=False, version="", count=0, path="", error_key="")

    # ---------- 启动时后台刷新云端资源库（**立刻返回**，不挡窗口）----------
    def cloud_refresh_async(self, force: bool = False):
        r"""**立刻返回**的后台刷新：启动时自动更新云端资源库用
        行为要求：程序启动就自动更新云端资源库（前提是设置为云端），
        但**绝不能**因为云端加载不出来而卡住窗口 —— 窗口必须先正常出现。
        ⚠️ 为什么要有这个"async 版"（`cloud_refresh` 是同步的）：
            `cloud_refresh` 会**同步跑网络**（core 的 refresh → fetch(attempts=1)，
            单次超时 60s + 镜像回退，最坏能跑一分多钟）。
            启动流程里 await 它 = **窗口被网络卡住**（这是要避免的行为）。
            所以这里改成：接口**立即返回** `{ok:true, started:true}`，
            真正的拉取丢一条**守护线程**去跑，跑完推事件 `cloud.refresh.done`。
        返回 `{ok, started, skipped}`：
            started=True  = 已经起了后台线程（正在拉）
            started=False = 没起（本地模式 / 已经在拉了 / 后端不可用）
        ⚠️ **失败不弹窗**：失败只体现在 `cloud.refresh.done` 事件的 ok/error 里，
           前端最多弹个 toast —— 绝不能挡住界面。
        """
        try:
            manager = self._shell.settings_manager if self._shell else None
            source_mode = "cloud"
            if manager is not None:
                source_mode = str(manager.settings.get("resource_source") or "cloud")
            if source_mode != "cloud":
                # 本地模式 → 不需要刷新云端（只有云端模式才刷新的前提条件）
                return _ok(started=False, skipped=True, reason="not_cloud")
            with self._cloud_bg_lock:
                if self._cloud_bg_running:
                    return _ok(started=False, skipped=True, reason="already_running")
                self._cloud_bg_running = True

            def _work():
                result = {}
                try:
                    result = CloudResourceSource().refresh(force=bool(force))
                    if result.get("ok") and result.get("updated"):
                        # 拉到新缓存 → 作废内存索引，否则前端读到的还是旧的
                        self._cache.invalidate()
                except Exception as exc:            # noqa: BLE001
                    result = {"ok": False, "updated": False, "error": str(exc),
                              "version": "", "count": 0, "path": ""}
                finally:
                    with self._cloud_bg_lock:
                        self._cloud_bg_running = False
                self._push_cloud_refresh_done(result)

            thread = threading.Thread(target=_work, name="ToolsGCP-cloud-refresh",
                                      daemon=True)
            thread.start()
            return _ok(started=True, skipped=False)
        except Exception as exc:                    # noqa: BLE001
            with self._cloud_bg_lock:
                self._cloud_bg_running = False
            return _fail(exc, started=False, skipped=False)

    def _push_cloud_refresh_done(self, result: dict):
        """后台刷新跑完 → 推 `cloud.refresh.done` 事件给前端
        ⚠️ 推事件前必须自己查一次 `_teardown_started`（AGENTS 第 8 条：
           WebView2 比主窗口先销毁，退出竞态里调前端会抛 ObjectDisposedException）。
        """
        result = result if isinstance(result, dict) else {}
        code = str(result.get("error") or "")
        payload = {
            "ok": bool(result.get("ok")),
            "updated": bool(result.get("updated")),
            "version": str(result.get("version") or ""),
            "count": int(result.get("count") or 0),
            "path": str(result.get("path") or ""),
            "error": code,
            "error_key": ("cloud_error_" + code) if code else "",
        }
        try:
            if getattr(self._shell, "_teardown_started", False):
                return
            self._shell.push_event("cloud.refresh.done", payload)
        except Exception as exc:                    # noqa: BLE001
            _log("warn", "资源库", "cloud", f"推送云端刷新结果失败: {exc}")

    # ---------- 内部 ----------
    def _loader(self, force: bool = False) -> ResourceLoader:
        return self._cache.loader(self._shell.settings_manager,
                                  self._shell.current_language(), force=force)

    def _all_items(self):
        return self._loader().get_all()

    # ---------- 加载 ----------
    def reload(self, force: bool = False):
        """重新读盘（原版 `reload_resources()`：重新读 + 重新搜索 + 记日志）
        ⚠️ 原版这个方法末尾会自动触发一次"重新搜索"；Web 版由前端在拿到结果后自己
           调 `query()` —— 因为"搜索"在现代前端是纯计算，不需要后端再跑一遍。
        """
        try:
            loader = self._loader(force=True)
            items = loader.get_all()
            latest = self.refresh_latest()
            return _ok(count=len(items),
                       schema_version=loader.schema_version,
                       icon_dir=getattr(loader, "_icon_dir", ""),
                       source=resolve_resource_file(self._shell.settings_manager),
                       latest=latest.get("codes", []) if latest.get("ok") else [],
                       error=self._cache._error)
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def status(self):
        """资源库状态（前端启动时拉一次：条目数、来源文件、schema 版本、标签数）"""
        try:
            loader = self._loader()
            items = loader.get_all()
            return _ok(loaded=bool(items) or bool(self._cache._path),
                       count=len(items),
                       schema_version=loader.schema_version,
                       source=resolve_resource_file(self._shell.settings_manager),
                       icon_dir=getattr(loader, "_icon_dir", ""),
                       error=self._cache._error)
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    # ---------- 读 ----------
    def all(self, view: str = ""):
        """整库（卡片用的轻量字段 —— 与 `get_summaries()` 同一份字段集）
        `view`（tile / grid）目前不影响数据，只保留参数位：原版是通过
        `app_card.apply_view_mode()` 改全局尺寸再重建卡片的，数据本身不变。
        """
        try:
            return _ok(items=self._loader().get_summaries(),
                       total=len(self._loader().get_all()))
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def detail(self, key: str = "", by: str = "code"):
        """资源详情（`key` 可以是 code / id；默认按 code 查）
        ⚠️ 原版详情页是"拿 id 向 loader 取全量"（`get_by_id`），但卡片右键 @ 给 AI
           用的是 code（`TG-000001`）。这里**两种都认**，避免前端还要自己判断用哪个。
        ⚠️ 这里返回的 `name` / `description` / `intro` / `supplement`
           是**原始三语言字典**（{简体中文, 繁體中文, English}），不是当前语言的字符串。
           原因：normalize()（唯一读数入口）会把多语言字典压成单语言字符串，
           提交软件页（制作器）就再也拿不到繁中/英文
           （表现为"多语言字段不加载繁体中文和英文的内容"）。
           为什么只有这一条路返回字典（而不是改 normalize()）：
             · normalize() 同时是**写盘**链路的规范器（normalize_all / maker 写盘），
               读/写两条路共用它，改它会牵连写盘语义；
             · resource_query（搜索/筛选/排序）、ai/prompt、收藏、部署、
               插件清单全都直接吃它的**字符串**形态，改成字典它们全要跟着改；
             · 而前端的 mapItem()/pickI18n() 本来就能处理字典（按当前语言取，
               取不到回退简中），所以详情页返回字典对搜索页/详情页都安全。
           其余接口（all / query / search / stats …）**仍返回字符串**，零风险。
        """
        try:
            key = str(key or "").strip()
            if not key:
                return _fail("key 不能为空")
            loader = self._loader()
            item = None
            if by == "id":
                item = loader.get_by_id(key)
            if item is None:
                item = loader.get_by_code(key)
            if item is None:
                item = loader.get_by_id(key)
            if item is None:
                _log("warn", "资源库", "detail", f"找不到资源: {key}")
                return _fail(f"找不到资源: {key}")
            # 取原始多语言字典（拿不到就保持规范形态的字符串）
            raw = loader.get_raw_i18n_by_id(item.get("id") or "")
            if not raw:
                raw = loader.get_raw_i18n_by_code(item.get("code") or "")
            detail_item = _merge_raw_i18n(item, raw)
            return _ok(item=detail_item, key=key,
                       variants=detail_item.get("variants") or [],
                       default_variant=detail_item.get("default_variant") or "")
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def variant(self, key: str = "", variant_key: str = ""):
        """取某个变体（原版 `ResourceLoader.resolve_variant`）
        变体字段会被提到顶层，前端"切版本"时应该用这个返回值替换展示字段 ——
        与原版 `_apply_variant` 的做法一致（url/github 取 variant 的值，缺则退回顶层）。
        """
        try:
            loader = self._loader()
            item = loader.get_by_code(key) or loader.get_by_id(key)
            if item is None:
                return _fail(f"找不到资源: {key}")
            chosen = ResourceLoader.resolve_variant(item, variant_key or None)
            variants = [v for v in (item.get("variants") or [])
                        if isinstance(v, dict) and v.get("key")]
            if chosen is None:
                return _ok(item=item, variant=None, variants=variants)
            merged = dict(item)
            for field in ("url", "github", "download_url", "author_url", "chat_url"):
                value = chosen.get(field)
                if value:
                    merged[field] = value
            return _ok(item=merged, variant=chosen, variants=variants)
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    # ---------- 搜索 ----------
    def refresh_latest(self, n: int = resource_query.LATEST_N):
        """重算最新这一档（原版 `_refresh_latest_codes`）
        ⚠️⚠️ 前端必须**在原版同样的时机**调它，否则行为对不上：
            原版只在"筛选条件变化"时刷新（`_on_filter_changed` → `_apply_filter_later`
            → `_refresh_latest_codes` → `_apply_filters`）；
            直接敲关键词搜索（`_do_search`）**不刷新**，用的是上次的集合。
            换句话说：搜索页初始状态下的 `_latest_codes` 是**空集合**，
            此时选最新等于不筛（这一点差分自检抓过，别"修"）。
        """
        try:
            codes = resource_query.latest_codes(self._all_items(), n)
            with self._latest_lock:
                self._latest = set(codes)
            return _ok(codes=sorted(codes), count=len(codes))
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def latest_codes(self):
        """读当前最新集合（不重算）"""
        with self._latest_lock:
            return _ok(codes=sorted(self._latest), count=len(self._latest))

    def query(self, keyword: str = "", filters=None, sort_key: str = "",
              use_latest: bool = False, grouped: bool = True):
        """搜索 + 筛选 +（可选）排序/分组，一次调用给前端可直接渲染的结构
        参数：
            keyword    = 搜索框原文
            filters    = {"category": [...], "tag": [...], "source": [...],
                         "favorite": [...], "updated": [...], "system": [...],
                         "arch": [...]}（与 FilterPanel.values() 同形）
            sort_key   = ""(默认) / all / category / az / za
            use_latest = ⚠️ **默认 False**，表示"用当前缓存的 latest 集合"，
                         与原版"直接搜索"路径一致。只有"筛选条件变化"那条路径
                         才应该先调 `refresh_latest()` 再 `query()`。
            grouped    = True 时额外返回分组结构；False 只回平铺列表
        返回：`{items, groups, total, keyword, latest_size}`
        """
        try:
            items = self._all_items()
            with self._latest_lock:
                latest = set(self._latest)
            matched, used = resource_query.query(
                items, keyword, filters or {},
                favorites=self._shell.favorites_manager,
                latest=latest)

            result = {
                "items": matched,
                "total": len(matched),
                "all_total": len(items),
                "keyword": used,
                "latest_size": len(latest),
            }
            if sort_key or grouped:
                key = sort_key or resource_query.SORT_ALL
                groups = resource_query.group_items(
                    matched, key, translate=self._translate_term)
                if grouped:
                    # ⚠️ 不要把匹配到的对象复制一遍：直接复用（前端只读不改）
                    result["groups"] = [
                        {"canonical": canonical, "title": title, "items": group,
                         "count": len(group)}
                        for canonical, title, group in groups
                    ]
                if key == resource_query.SORT_ALL and len(groups) == 1:
                    result["sorted"] = groups[0][2]
            return _ok(**result)
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def search(self, keyword: str = ""):
        """只按关键词搜（不带筛选）—— 给 AI 工具/自检脚本用的轻量入口"""
        try:
            matched, used = resource_query.query(
                self._all_items(), keyword, {},
                favorites=self._shell.favorites_manager, latest=set())
            return _ok(items=matched, total=len(matched), keyword=used)
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    # ---------- 筛选选项 ----------
    def filter_options(self, language: str = ""):
        """更多筛选那一整块需要的选项（值 + 显示名）
        与原版 `_setup_search_page` 里逐行 add_row 的内容一一对应：
            category（固定顺序）/ tag（运行时算）/ source / favorite /
            updated / system / arch
        ⚠️ 值与显示名分开：**值是规范中文**（筛选按它匹配），显示名按语言翻译。
        """
        try:
            lang = language or self._shell.current_language()
            items = self._all_items()
            translate = self._translate_term

            category_options = [
                {"value": c, "label": translate(c)} for c in resource_query.CATEGORY_ORDER
            ]
            tag_options = [
                {"value": t, "label": translate(t)}
                for t in resource_query.tag_filter_options(items)
            ]
            system_options = [
                {"value": s, "label": translate(s)}
                for s in resource_schema.SYSTEMS
            ]
            arch_options = [
                {"value": a, "label": translate(a)}
                for a in resource_schema.ARCHITECTURES
            ]
            return _ok(
                category=category_options, tag=tag_options,
                system=system_options, arch=arch_options,
                category_order=list(resource_query.CATEGORY_ORDER),
                source=[{"value": "site"}, {"value": "repo"}, {"value": "download"}],
                favorite=[{"value": "only"}],
                updated=[{"value": k} for k in ("latest", "10d", "30d", "180d")],
                latest_n=resource_query.LATEST_N,
                language=lang)
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def _translate_term(self, value: str) -> str:
        """术语显示名（类别/标签/系统/架构）—— 只改显示，不改匹配用的值"""
        try:
            from pymodels.core.language_manager import translate_term
            manager = self._shell.language_manager
            return translate_term(value, manager)
        except Exception:
            return value

    # ---------- 图标 ----------
    def icon_url(self, name: str = ""):
        """把一个 icon 字段（可能是 "localsend.png" 或 ".ToolsGCP/Icon/xx.png"）
        转成前端能直接用的 URL
        ⚠️ 原版是拿 QPixmap 直接读盘；Web 端必须走本地 HTTP 服务
           （`file://` 下 fetch/Canvas 都会被拒）。
        ⚠️ 图标目录已重构（web 版）：`.ToolsGCP/Icon/` → `.ToolsGCP/images/icon/`，
           规范 URL = `/res/image/icon/<name>`（`/res/icon/<name>` 保留为兼容别名）。
           资源库 JSON 里的 icon 字段历史上写过 ".ToolsGCP/Icon/xx.png" 这种完整路径，
           这里只取 basename 再拼新目录，两种写法都能用。
        """
        try:
            raw = str(name or "").strip().replace("\\", "/")
            if not raw:
                return _ok(url="")
            if raw.startswith("http://") or raw.startswith("https://"):
                return _ok(url=raw, remote=True)
            base = os.path.basename(raw)
            # 归一：只取文件名，目录由 webhost 的路由决定
            return _ok(url=f"/res/image/icon/{base}", name=base, remote=False)
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)

    def stats(self):
        """资源库统计（给"定制页"/"自检"/Agent 用）"""
        try:
            items = self._all_items()
            by_category = {}
            by_tag = {}
            by_system = {}
            for item in items:
                for category in resource_schema.categories_of(item):
                    by_category[category] = by_category.get(category, 0) + 1
                for tag in resource_schema.tags_of(item):
                    by_tag[tag] = by_tag.get(tag, 0) + 1
                for system in resource_schema.systems_of(item):
                    by_system[system] = by_system.get(system, 0) + 1
            return _ok(total=len(items),
                       categories=by_category, tags=by_tag, systems=by_system,
                       with_github=sum(1 for i in items if i.get("github")),
                       with_url=sum(1 for i in items if i.get("url")),
                       with_download=sum(1 for i in items if i.get("download_url")),
                       latest=len(resource_query.latest_codes(items)))
        except Exception as exc:                    # noqa: BLE001
            return _fail(exc)


__all__ = ["SettingsDomain", "FavoritesDomain", "ResourcesDomain"]
