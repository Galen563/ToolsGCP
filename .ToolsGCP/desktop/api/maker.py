"""资源制作器（提交软件）的写盘域 —— `window.pywebview.api.maker`。
========== 为什么需要它 ==========
提交软件页（`.ToolsGCP/webui/index.html` 的 maker 段）本来只是一个**表单**：
它把用户填的内容组装成一条资源，然后调 `maker.append_entry` 写进
`.ToolsGCP/ToolsGCP-Resources.json`。但后端一直**没有这个域**，前端只能降级成
"导出一个合并后的 JSON 让用户自己放回去" —— 页面上看起来能填，实际写不进资源库。
这里补上最小可用的写盘能力（不依赖 PyQt，也不 import 原版 `interfaces/`）：
    maker.info()                    正在用的资源库路径 / 条目数 / schema
    maker.append_entry(entry, opts) 新增或按 id 覆盖一条（写盘前自动备份）
    maker.append_entries(items, opts) 批量合并（追加模式 / 新建模式，重复条目策略）
约定：
  · 条目先过 `pymodels.core.resource_schema.normalize()`，保证和原版写得一样；
  · 写盘用临时文件 + os.replace原子替换，写之前把旧文件复制成
    `ToolsGCP-Resources.backup-<时间戳>.json`（和原版一致，最多留 20 份）；
  · 任何异常都转成 `{ok: False, error}`，绝不把半截 JSON 留在盘上。
"""

import base64
import json
import os
import re
import shutil
import time
from urllib.parse import quote

from pymodels.constants import CONFIG_DIR, IMAGES_DIR


def _ok(**kwargs):
    payload = {"ok": True}
    payload.update(kwargs)
    return payload


def _fail(message, **kwargs):
    payload = {"ok": False, "error": str(message or "unknown error")}
    payload.update(kwargs)
    return payload


def _log(level: str, category_zh: str, category_en: str, message: str):
    try:
        from pymodels.utils.logger import log
        getattr(log, level, log.info)(category_zh, category_en, message)
    except Exception:
        pass


DEFAULT_FILE = os.path.join(CONFIG_DIR, "ToolsGCP-Resources.json")
BACKUP_KEEP = 20
# 图标目录（web 版重构后的位置）：/res/image/icon/<name> 就是这里的文件。
# ⚠️ 不要再用旧的 `.ToolsGCP/Icon/`：webhost 的路由只认 images/icon。
ICON_DIR = os.path.join(IMAGES_DIR, "icon")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".webp", ".svg")
MAX_ICON_BYTES = 16 * 1024 * 1024


class MakerDomain:
    """资源库写盘（提交软件 / 批量合成共用）"""

    def __init__(self, shell):
        self._shell = shell

    # ---------- 路径 ----------
    def library_path(self) -> str:
        """当前资源库文件（跟着设置里的"资源来源"走；拿不到就用默认路径）"""
        try:
            from pymodels.core.cloud_resource_source import resolve_resource_file
            manager = getattr(self._shell, "settings_manager", None)
            path = resolve_resource_file(manager)
            if path:
                return str(path)
        except Exception:
            pass
        return DEFAULT_FILE

    # ---------- 读 ----------
    @staticmethod
    def _read(path: str):
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, list):
            return {"schema_version": "2.1.0", "resources": data}, data
        if not isinstance(data, dict):
            raise ValueError("资源库不是 JSON 对象或数组")
        items = data.get("resources")
        if not isinstance(items, list):
            items = []
            data["resources"] = items
        return data, items

    # ---------- 写（原子 + 备份） ----------
    @staticmethod
    def _write(path: str, data: dict):
        # ① 先把旧文件备份成 ToolsGCP-Resources.backup-<时间戳>.json
        #    ⚠️ 备份失败就**中止写入**（对齐 py 的 backup_library 失败即 abort）：
        #       宁可这次不写，也不能把用户唯一的一份资源库覆盖掉。
        try:
            if os.path.isfile(path):
                stamp = time.strftime("%Y%m%d-%H%M%S")
                backup = os.path.join(os.path.dirname(path),
                                      f"ToolsGCP-Resources.backup-{stamp}.json")
                shutil.copy2(path, backup)
                MakerDomain._prune_backups(os.path.dirname(path))
        except Exception as exc:                          # noqa: BLE001
            _log("err", "资源库", "maker", f"备份资源库失败，已中止写入: {exc}")
            raise RuntimeError(f"资源库备份失败，已中止写入（原文件没有改动）：{exc}") from exc
        # ② 临时文件 + os.replace（写到一半崩溃也不会毁掉原文件）
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp, path)

    @staticmethod
    def _prune_backups(folder: str):
        try:
            names = [n for n in os.listdir(folder)
                     if n.startswith("ToolsGCP-Resources.backup-") and n.endswith(".json")]
            names.sort(reverse=True)
            for name in names[BACKUP_KEEP:]:
                try:
                    os.remove(os.path.join(folder, name))
                except OSError:
                    pass
        except Exception:
            pass

    # ---------- 归一化 ----------
    @staticmethod
    def _normalize(entry: dict) -> dict:
        """把前端传来的条目规范化（字段顺序 / 空值过滤 / tags 去重 / 类别转 list）
        ⚠️ **多语言字段必须在 normalize 之后合并**。
           `resource_schema.normalize()` 会把 kind="i18n" 的字段按**当前语言**压成一句话
           （first_text），所以前端送来的 `{简体中文, 繁體中文, English}` 字典
           会在这一步被压扁成**一种语言** —— 写回资源库时繁中/英文就没了。
           对齐 py 版 `resource_maker_pages.py:1579-1582` 的做法：
               normalized = resource_schema.normalize(entry)
               return self.apply_i18n_to_entry(normalized)
           ⚠️ 这也是 py 版注释里写的提交不了三语言的根因之一。
           （之前 web 版只做了第一步，所以用户从制作器写回一次就丢一次多语言。）
        """
        try:
            from pymodels.core import resource_schema
            normalized = resource_schema.normalize(dict(entry or {}))
            return MakerDomain._merge_i18n(entry or {}, normalized)
        except Exception:
            return dict(entry or {})

    @staticmethod
    def _merge_i18n(raw: dict, normalized: dict) -> dict:
        """把**多语言字典**合并回规范化后的条目（normalize 之后做）
        ⚠️ 规则（对齐 py 版 apply_i18n_to_entry）：
          · 字段是"多语言字典"且至少一种语言有内容 → 保留字典形态写盘；
          · 三种语言内容**完全相同** → 不写字典，写成纯字符串（和前端
            applyI18nToEntry 的行为一致，避免资源库里出现无意义的同内容字典）；
          · 字典里只有一种语言有内容 → 也写成纯字符串（更紧凑，语义等价）。
        ⚠️ 只处理 kind=="i18n" 的字段（name/description/intro/supplement），
           其余字段照常走 normalize 的规范化。
        """
        try:
            from pymodels.core import resource_schema
        except Exception:
            return normalized
        fields = getattr(resource_schema, "I18N_FIELDS", ())
        if not fields:
            return normalized
        out = dict(normalized or {})
        for field in fields:
            value = (raw or {}).get(field)
            if not isinstance(value, dict) or not value:
                continue
            texts = {}
            for lang, text in value.items():
                clean = str(text or "").strip()
                if clean:
                    texts[str(lang)] = clean
            if not texts:
                continue
            # 三种（或 N 种）语言内容全一样 → 写成纯字符串
            if len(set(texts.values())) == 1:
                out[field] = next(iter(texts.values()))
            else:
                out[field] = texts
        return out

    @staticmethod
    def _key_of(item: dict) -> str:
        return str(item.get("id") or "").strip() or str(item.get("code") or "").strip()

    # ---------- 图标 ----------
    def icon_dir(self) -> str:
        """制作器写图标的目录（web 版：`.ToolsGCP/images/icon/`，`/res/image/icon/<name>` 就是它）"""
        return ICON_DIR

    @staticmethod
    def _safe_icon_name(name, ext_hint: str = "") -> str:
        """把任意文件名洗成"图标目录里能用的文件名"。
        ⚠️ 规则和 py 的 copy_into_icon_dir 不同：那边**保留中文**（Windows 允许），
           所以这里也只去掉 Windows 非法字符 + 目录部分，不做 ASCII 化 ——
           否则用户导入微信.png会被改名叫 icon.png，在资源库里对不上。
        """
        raw = str(name or "").replace("\\", "/")
        base = os.path.basename(raw)
        base = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", base).strip()
        stem, ext = os.path.splitext(base)
        ext = (ext or ext_hint or ".png").lower()
        if ext not in IMAGE_EXTS:
            ext = ".png"
        stem = stem.strip() or "icon"
        return stem + ext

    def icon_path(self, name: str) -> str:
        return os.path.join(self.icon_dir(), self._safe_icon_name(name))

    def _icon_name_if_exists(self, name) -> str:
        """资源库里的 icon 字段 -> 真实存在的文件名；不存在返回空串（绝不写悬空引用）"""
        base = self._safe_icon_name(name) if name else ""
        if not base:
            return ""
        return base if os.path.isfile(os.path.join(self.icon_dir(), base)) else ""

    def _copy_icon_to(self, name, dest_dir: str, stem: str) -> str:
        """把图标目录里的某个文件复制到 dest_dir，返回最终文件名（失败/不存在 → 空串）。
        命名优先用 <stem><ext>（stem 已按 py copy_icon 的规则 ASCII 化）；
        同名且内容相同 → 复用；冲突 → 加时间戳，绝不覆盖别人的图片。
        """
        source_name = self._icon_name_if_exists(name)
        if not source_name:
            return ""
        source = os.path.join(self.icon_dir(), source_name)
        os.makedirs(dest_dir, exist_ok=True)
        _, ext = os.path.splitext(source_name)
        safe_stem = re.sub(r"[^A-Za-z0-9_\-]+", "", str(stem or "")) or \
            re.sub(r"[^A-Za-z0-9_\-]+", "", os.path.splitext(source_name)[0]) or "icon"
        for candidate in (f"{safe_stem}{ext}", source_name):
            dest = os.path.join(dest_dir, candidate)
            if not os.path.isfile(dest):
                shutil.copyfile(source, dest)
                return candidate
            try:
                with open(dest, "rb") as a, open(source, "rb") as b:
                    if a.read() == b.read():
                        return candidate
            except Exception:
                pass
        candidate = f"{safe_stem}-{time.strftime('%H%M%S')}{ext}"
        shutil.copyfile(source, os.path.join(dest_dir, candidate))
        return candidate

    def save_icon(self, name="", data=""):
        """把前端导入的图片**真正落盘**到图标目录。
        ⚠️ 为什么必须有这一步：前端 `pickIcon` 只把文件读成 dataURL 放在内存里，
           以前"追加到本机资源库"直接写 `icon: <文件名>` —— 那个文件在磁盘上根本不存在，
           资源库/搜索页的图标永远是坏的（= 假装成功）。这里补上真正的写文件。
        参数：
            name  期望文件名（前端用 code 命名，如 TG-000053.png；非图标扩展名会兜底成 .png）
            data  data URL（`data:image/png;base64,...`）或裸 base64
        返回：`{ok, name, path, url, bytes}`
        """
        try:
            payload = str(data or "")
            if payload.startswith("data:"):
                _head, _sep, payload = payload.partition(",")
            if not payload:
                return _fail("图片内容是空的")
            raw = base64.b64decode(payload, validate=False)
            if not raw:
                return _fail("图片内容是空的")
            if len(raw) > MAX_ICON_BYTES:
                return _fail(f"图片太大（{len(raw) // 1024} KB > "
                             f"{MAX_ICON_BYTES // 1024} KB），请换一张小一点的")
            want = self._safe_icon_name(name)
            folder = self.icon_dir()
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, want)
            tmp = path + ".tmp"
            with open(tmp, "wb") as handle:
                handle.write(raw)
            os.replace(tmp, path)
            _log("op", "资源库", "maker", f"已导入图标 {want}（{len(raw)} 字节）")
            return _ok(name=want, path=path, bytes=len(raw),
                       url="/res/image/icon/" + quote(want))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    # ---------- 对外接口 ----------
    def info(self):
        """让页面知道"正在写到哪个文件、现在有多少条" """
        try:
            path = self.library_path()
            data, items = self._read(path)
            return _ok(path=path, count=len(items),
                       schema_version=data.get("schema_version", ""))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def append_entry(self, entry=None, options=None):
        """新增一条；同 id（或同 code）已存在时**覆盖**
        options.confirm：前端已经弹过"覆盖确认"时为 True（保留字段，后端不做二段确认）
        对齐 py `append_to_library` 的几件"必须真做"的事：
          · 每次从**磁盘**重读资源库（不拿前端的旧副本覆盖别人的改动）；
          · 覆盖时保留原条目的 listed_at（改内容不算重新上架）；
          · icon 字段必须指向图标目录里**真实存在**的文件，否则删掉这个字段
            （绝不写悬空引用 —— 那会让搜索页显示坏图标）；
          · 写完更新 metadata.updated_at / total_count。
        """
        try:
            path = self.library_path()
            data, items = self._read(path)
            item = self._normalize(entry or {})
            key = self._key_of(item)
            if not key:
                return _fail("这条资源没有 id 或 code，无法写入")
            if not item.get("name"):
                return _fail("资源名称不能为空")

            # 图标：只认图标目录里真实存在的文件名
            icon_name = self._icon_name_if_exists(item.get("icon"))
            if icon_name:
                item["icon"] = icon_name
            else:
                item.pop("icon", None)

            action = "add"
            for index, existing in enumerate(items):
                if self._key_of(existing) == key:
                    # 覆盖：保留原上架时间（前端没显式给就沿用旧的）
                    if not item.get("listed_at"):
                        item["listed_at"] = existing.get("listed_at", "")
                    items[index] = item
                    action = "update"
                    break
            else:
                items.append(item)
            if not item.get("listed_at"):
                item["listed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

            data["resources"] = items
            metadata = data.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
                data["metadata"] = metadata
            metadata["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            metadata["total_count"] = len(items)
            self._write(path, data)
            _log("op", "资源库", "maker",
                 f"{'覆盖' if action == 'update' else '新增'}资源 {key}（{item.get('name')}）")
            return _ok(action=action, id=key, code=item.get("code", ""),
                       name=item.get("name", ""), total=len(items), path=path,
                       entry=item)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def save_standalone(self, entry=None, options=None):
        """另存为**独立资源库**：系统另存为对话框 + 写一个合法的资源库 JSON。
        对齐 py `save_standalone`：
          · 用户在系统对话框里点取消 → `{ok:true, canceled:true}`（静默，不报错）；
          · 图标如果真实存在，复制到 `目标目录/Icon/<名字>` 并改写 entry.icon，
            metadata.icon_dir 写 "Icon"（这样把这个 JSON 发给别人也能直接用）；
          · 图标不存在就删掉 icon 字段，绝不引一个不存在的文件；
          · 先写 `.tmp` 再 os.replace（半截写成不会留下坏 JSON）。
        """
        try:
            opts = options or {}
            item = self._normalize(entry or {})
            key = self._key_of(item)
            if not key:
                return _fail("这条资源没有 id 或 code，无法另存")
            if not item.get("name"):
                return _fail("资源名称不能为空")

            default_name = str(opts.get("default_name") or "ToolsGCP-Resources.json")
            picked = self._shell.pick_save_path(default_name=default_name,
                                                file_type="JSON 文件 (*.json)")
            if not picked:
                _log("info", "资源库", "maker", "用户取消了另存为独立资源库")
                return _ok(canceled=True, saved=False, path="")

            path = os.path.abspath(str(picked))
            if not os.path.splitext(path)[1]:
                path += ".json"
            parent = os.path.dirname(path) or os.getcwd()
            os.makedirs(parent, exist_ok=True)

            icon_dir = os.path.join(parent, "Icon")
            icon_name = self._copy_icon_to(item.get("icon"), icon_dir, key)
            if icon_name:
                item["icon"] = icon_name
            else:
                item.pop("icon", None)

            payload = {
                "schema_version": "2.1.0",
                "metadata": {
                    "name": "ToolsGCP Resources",
                    "description": "ToolsGCP 资源索引文件",
                    "icon_dir": "Icon",
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "total_count": 1,
                },
                "resources": [item],
            }
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(tmp, path)
            size = os.path.getsize(path)
            _log("op", "资源库", "maker",
                 f"另存为独立资源库: {path}（{size} 字节，图标 {item.get('icon') or '无'}）")
            return _ok(canceled=False, saved=True, path=path,
                       name=os.path.basename(path), bytes=int(size),
                       count=1, icon=item.get("icon", ""))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def append_entries(self, entries=None, options=None):
        """批量合并
        options.mode = "append"（追加进现有资源库，默认）/ "new"（合并成一个新文件）
        options.duplicate = "skip"（默认）/ "overwrite"
        options.output = new 模式下的输出文件名（写到资源库同目录）
        """
        try:
            opts = options or {}
            mode = str(opts.get("mode") or "append").lower()
            dup = str(opts.get("duplicate") or "skip").lower()
            source = [self._normalize(e) for e in (entries or []) if isinstance(e, dict)]
            if not source:
                return _fail("没有可合并的条目")

            if mode == "new":
                base_path = os.path.join(os.path.dirname(self.library_path()),
                                         str(opts.get("output") or "ToolsGCP-Resources-merged.json"))
                data = {"schema_version": "2.1.0",
                        "metadata": {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                        "resources": []}
                items = data["resources"]
            else:
                base_path = self.library_path()
                data, items = self._read(base_path)

            existing_keys = {}
            for index, item in enumerate(items):
                existing_keys[self._key_of(item)] = index

            added = updated = skipped = 0
            for item in source:
                key = self._key_of(item)
                if not key:
                    skipped += 1
                    continue
                if key in existing_keys:
                    if dup == "overwrite":
                        items[existing_keys[key]] = item
                        updated += 1
                    else:
                        skipped += 1
                    continue
                existing_keys[key] = len(items)
                items.append(item)
                added += 1

            data["resources"] = items
            self._write(base_path, data)
            _log("op", "资源库", "maker",
                 f"批量合成（{mode}/{dup}）：新增 {added}，覆盖 {updated}，跳过 {skipped}")
            return _ok(path=base_path, added=added, updated=updated, skipped=skipped,
                       total=len(items), mode=mode)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)
