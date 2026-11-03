"""收藏夹管理：一定有一个默认收藏夹（不可删/改名、永远排最前），其余可增删改。
收藏项用资源编码（TG-0001）记录，展示时再回资源库取数据；
存储文件：.ToolsGCP/config/favorites.json
"""

import json
import os

from ..constants import DATA_DIR

FAVORITES_FILE = "favorites.json"
SCHEMA_VERSION = "1.0.0"

DEFAULT_FOLDER = "Default"
MAX_FOLDER_NAME = 24
MAX_FOLDERS = 50

# 默认收藏夹在数据里统一存成 "Default"，界面上按当前语言显示：这样切语言时
# 收藏夹不会变成两个，老版本存的中文名也能迁移过来。
DEFAULT_FOLDER_NAMES = {
    "简体中文": "默认收藏夹",
    "繁體中文": "預設收藏夾",
    "English": "Default",
}
# 历史版本可能存过的默认收藏夹名字（读到就统一改写成 "Default"）
LEGACY_DEFAULT_NAMES = {"默认收藏夹", "默認收藏夾", "預設收藏夾", "Default", "default",
                        "既定のフォルダ", "기본 폴더"}


def display_folder_name(name: str, language: str = "简体中文") -> str:
    """把内部文件夹名翻译成界面显示用的名字（只有默认收藏夹需要翻译）"""
    if name == DEFAULT_FOLDER:
        # ⚠️ 语言不认识时退回英文而不是简体中文：语言文件缺失时界面应统一英文
        return DEFAULT_FOLDER_NAMES.get(language, DEFAULT_FOLDER_NAMES["English"])
    return name


def _log_op(action: str, **fields):
    """收藏相关的操作统一记日志（失败也不影响功能）"""
    try:
        from ..utils.logger import log
        log.op("收藏", action, **fields)
    except Exception:
        pass


class FavoritesManager:
    """收藏夹管理器"""

    def __init__(self, config_dir=None):
        self.config_dir = config_dir or DATA_DIR
        self.path = os.path.join(self.config_dir, FAVORITES_FILE)
        self.data = {"schema_version": SCHEMA_VERSION, "folders": []}
        self.load()

    # ---------- 读写 ----------
    def load(self):
        raw = None
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except Exception:
                raw = None

        folders = []
        if isinstance(raw, dict) and isinstance(raw.get("folders"), list):
            for folder in raw["folders"]:
                if not isinstance(folder, dict):
                    continue
                name = str(folder.get("name") or "").strip()
                if not name or any(f["name"] == name for f in folders):
                    continue
                # 老数据里默认收藏夹存的是中文名，统一迁移成英文键
                if name in LEGACY_DEFAULT_NAMES:
                    name = DEFAULT_FOLDER
                items = folder.get("items")
                items = [str(i) for i in items if str(i).strip()] if isinstance(items, list) else []
                # 去重且保序
                seen = set()
                items = [i for i in items if not (i in seen or seen.add(i))]
                folders.append({"name": name, "items": items})

        if not any(f["name"] == DEFAULT_FOLDER for f in folders):
            folders.insert(0, {"name": DEFAULT_FOLDER, "items": []})
        else:
            # 默认收藏夹永远排第一
            folders.sort(key=lambda f: 0 if f["name"] == DEFAULT_FOLDER else 1)

        self.data = {"schema_version": SCHEMA_VERSION, "folders": folders}
        if raw is None:
            self.save()

    def save(self):
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    # ---------- 查询 ----------
    def folders(self) -> list:
        return [f["name"] for f in self.data["folders"]]

    def _folder(self, name):
        for folder in self.data["folders"]:
            if folder["name"] == name:
                return folder
        return None

    def folder_items(self, name) -> list:
        folder = self._folder(name)
        return list(folder["items"]) if folder else []

    def count(self, name) -> int:
        folder = self._folder(name)
        return len(folder["items"]) if folder else 0

    def all_codes(self) -> set:
        codes = set()
        for folder in self.data["folders"]:
            codes.update(folder["items"])
        return codes

    def is_favorite(self, code) -> bool:
        code = str(code or "")
        return bool(code) and code in self.all_codes()

    def folder_of(self, code) -> str:
        """返回该项目所在的收藏夹名（没收藏返回空串）"""
        code = str(code or "")
        for folder in self.data["folders"]:
            if code in folder["items"]:
                return folder["name"]
        return ""

    # ---------- 增删 ----------
    def _ensure_folder(self, name):
        """取一个收藏夹，没有就建出来（绝不允许返回 None）
        ⚠️ 必需的兜底：文件被改坏或默认夹名对不上时 _folder() 返回 None，而调用方
        下一行就是 `folder["items"].append(...)`，直接 TypeError，表现为"AI 说已经
        收藏了，收藏夹其实一条没变"。
        """
        folder = self._folder(name)
        if folder is not None:
            return folder
        folder = self._folder(DEFAULT_FOLDER)
        if folder is not None:
            return folder
        # 真的一个都没有：把默认收藏夹补回来（数据坏了也要能用）
        folder = {"name": str(name or DEFAULT_FOLDER), "items": []}
        try:
            self.data.setdefault("folders", []).append(folder)
        except Exception:
            self.data = {"schema_version": SCHEMA_VERSION, "folders": [folder]}
        return folder

    def add(self, code, folder_name: str = None) -> bool:
        code = str(code or "").strip()
        if not code:
            return False
        name = folder_name or DEFAULT_FOLDER
        folder = self._ensure_folder(name)
        if code in folder["items"]:
            return False
        folder["items"].append(code)
        self.save()
        _log_op("add", code=code, folder=folder["name"], total=len(folder["items"]))
        return True

    def remove(self, code, folder_name: str = None) -> bool:
        """从指定收藏夹（默认全部收藏夹）里移除"""
        code = str(code or "").strip()
        if not code:
            return False
        changed = False
        targets = [self._folder(folder_name)] if folder_name else self.data["folders"]
        for folder in targets:
            if folder and code in folder["items"]:
                folder["items"].remove(code)
                changed = True
        if changed:
            self.save()
            _log_op("remove", code=code, folder=folder_name or "全部")
        return changed

    def toggle(self, code, folder_name: str = None) -> bool:
        """切换收藏状态，返回切换后的状态（True = 已收藏）"""
        code = str(code or "").strip()
        if not code:
            return False
        if self.is_favorite(code):
            self.remove(code)
            _log_op("toggle", code=code, state="取消收藏")
            return False
        self.add(code, folder_name)
        _log_op("toggle", code=code, state="已收藏", folder=folder_name or DEFAULT_FOLDER)
        return True

    def move(self, code, from_folder: str, to_folder: str) -> bool:
        if from_folder == to_folder:
            return False
        self.remove(code, from_folder)
        return self.add(code, to_folder)

    # ---------- 收藏夹增删改 ----------
    def create_folder(self, name):
        """新建收藏夹，返回 (是否成功, 提示)"""
        name = str(name or "").strip()
        error = self._validate_name(name)
        if error:
            return False, error
        if self._folder(name):
            return False, f"已经有一个叫「{name}」的收藏夹了"
        if len(self.data["folders"]) >= MAX_FOLDERS:
            return False, f"最多只能建 {MAX_FOLDERS} 个收藏夹"
        self.data["folders"].append({"name": name, "items": []})
        self.save()
        _log_op("create_folder", name=name)
        return True, name

    def default_folder_label(self, language: str = "简体中文") -> str:
        """默认收藏夹在当前语言下的名字（给提示信息用）"""
        return display_folder_name(DEFAULT_FOLDER, language)

    def rename_folder(self, old_name, new_name):
        """重命名收藏夹，返回 (是否成功, 提示)"""
        folder = self._folder(old_name)
        if folder is None:
            return False, "收藏夹不存在"
        if old_name == DEFAULT_FOLDER:
            return False, "default_folder_reserved"

        new_name = str(new_name or "").strip()
        error = self._validate_name(new_name)
        if error:
            return False, error
        if new_name == old_name:
            return False, "名称没有变化"
        if self._folder(new_name):
            return False, f"已经有一个叫「{new_name}」的收藏夹了"

        folder["name"] = new_name
        self.save()
        _log_op("rename_folder", old=old_name, new=new_name)
        return True, new_name

    def delete_folder(self, name):
        """删除收藏夹（里面的收藏会一起删除），返回 (是否成功, 提示)"""
        if name == DEFAULT_FOLDER:
            return False, "default_folder_reserved"
        folder = self._folder(name)
        if folder is None:
            return False, "收藏夹不存在"
        self.data["folders"].remove(folder)
        self.save()
        _log_op("delete_folder", name=name, items=len(folder["items"]))
        return True, name

    def _validate_name(self, name) -> str:
        """返回错误信息，通过则返回空串"""
        if not name:
            return "名称不能为空"
        if len(name) > MAX_FOLDER_NAME:
            return f"名称不能超过 {MAX_FOLDER_NAME} 个字"
        if name == DEFAULT_FOLDER:
            return "default_folder_reserved"
        if any(c in name for c in "\\/:*?\"<>|"):
            return "名称里不能包含 \\ / : * ? \" < > |"
        return ""
