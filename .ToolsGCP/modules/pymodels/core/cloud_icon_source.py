r"""云端图标包：GitHub Release 里的 icon.zip → 解到 <数据根>/config/cloud/icons。

========== 这个模块解决什么 ==========
云端模式以前只有 `ToolsGCP-Resources.json` 来自 GitHub Release，图标还是**程序自带**的
（`.ToolsGCP/images/icon`，跟着 exe 发布，永远只有打包时那 50 个）。
现在作者把图标文件夹压成 `icon.zip` 传到**同一个 Release** 里
（附件名 `icon.zip`，解压后的目录结构 = `icon/一堆图片`），
→ 图标也要**完完全全走云端**：和 JSON 同一套「选最新 release → 找附件 → 下载（镜像回退）
   → 校验 → 落地」的流程，只是多一步**解压**。

========== 为什么用 zip 而不是 7z ==========
· zip 是 Python **标准库**（`zipfile`）能直接读的格式 ⇒ 打包成 exe 后**零新增依赖**、
  任何机器开箱即用；
· 7z 需要 py7zr / 7-Zip.exe：要么加依赖（违反 AGENTS 第 7 条"不引入新依赖"），
  要么赌用户机器上装了 7-Zip（测试者机器上没有 → 图标全灰）。
⚠️ 若以后再换回 7z：只改本文件的 `_extract_*`，其它调用点不用动。

========== 落地在哪（硬规则） ==========
`<数据根>/config/cloud/icons/<文件名>`（默认 `%USERPROFILE%\.ToolsGCP\config\cloud\icons\`）
· 和 JSON 缓存同根（AGENTS 第 9 条：程序产出的文件跟数据根同生共死）；
· ⚠️ 绝不写程序目录旁的 `.ToolsGCP\images\icon`：那是随 exe 发布的资源目录
  （onedir 下可能被覆盖、onefile 下在临时目录里每次重启都会丢），
  而且数据根迁移时 `<数据根>` 会整体搬走，云端图标跟着搬才正确。

========== 取用顺序 ==========
`icon_file(name)` 给 webhost 用：
    ① 云端目录有 → 用云端；
    ② 否则退回程序自带的 `.ToolsGCP\images\icon`（首次同步完成前的兜底，
       也是本地模式用户一直在用的那份）。
本地模式（resource_source=local）→ 直接 ②，绝不联网。

========== 不阻塞首屏 ==========
和 JSON 一样：下载/解压全部在**后台线程**里跑（`ensure_background_sync`），
拉完推事件让前端 `resetIconRetries()` 重画。同步接口 `sync()` 只由
设置页/启动后台线程调用，允许在工作线程里阻塞。

========== 错误口径 ==========
沿用 cloud_resource_source 的机器码（NETWORK / BAD_RESPONSE / RATE_LIMITED /
NO_RELEASE / NO_ASSET / INVALID_ZIP），文案由界面查语言包。
**失败绝不清空已有图标目录**：解包失败宁可继续用旧的一批。
"""

import os
import re
import shutil
import threading
import time
import zipfile

from ..constants import APP_REPO, CONFIG_DIR, RESOURCES_REPO_CHAIN
from .cloud_resource_source import (
    ERR_BAD_RESPONSE,
    ERR_NETWORK,
    ERR_NO_ASSET,
    ERR_NO_RELEASE,
    CloudResourceSource,
    MAX_RETRY,
    TIMEOUT_SECONDS,
    build_candidate_urls,
    cloud_dir,
    fetch_releases,
    http_get,
    select_latest_release,
)

# Release 附件名（大小写不敏感匹配，和 JSON 那条一致）
ICON_ASSET_NAME = "icon.zip"
# 解压后的子目录名（zip 内部结构是 icon/*.png，解出来我们只取文件名那一段，
# 但目录名和它保持一致，方便对着看）
ICLOUD_SUBDIR = "icons"
# 图标同步的状态文件（记 tag/大小/文件数/时间，跨进程节流用）
ICON_META_NAME = "icons.meta.json"
# 两个合法后缀之外的东西**一律不落盘**（zip 里混进 exe/脚本也不写）
_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".bmp"}
# 单个图标解压后的大小上限（16MB 足够任何启动器图标；防 zip bomb）
_MAX_MEMBER_BYTES = 16 * 1024 * 1024
# 整包解压后的大小上限（500MB；现在的 icon.zip 才 4MB，这是量级上的保险丝）
_MAX_TOTAL_BYTES = 500 * 1024 * 1024
# 后台自动同步的最小间隔（秒）：图标不常变，和 JSON 检查频率同量级即可
BACKGROUND_MIN_INTERVAL = 600.0


# ==========================================================================
# 路径
# ==========================================================================

def cloud_root() -> str:
    """云端缓存根（`<数据根>/config/cloud`）；不存在就创建
    ⚠️ 不能假设它已经存在：JSON 缓存目录是 cloud_resource_source 在**它自己的**
       写入路径里才建的，图标同步可能先跑（比如后台线程先完成），
       直接 mkdtemp(dir=cloud_dir()) 会 FileNotFoundError。
    """
    path = cloud_dir()
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def _make_staging() -> str:
    """建一个**普通权限**的临时解包目录（`<云端根>/icons-staging`）
    ⚠️ 为什么不用 `tempfile.mkdtemp`：它建目录时传 mode=0o700，
       Windows 上这会生成"只有属主可访问"的 ACL —— 实测在受限账户/沙箱环境里
       紧接着往这个目录写文件会 PermissionError（图标云端在测试者机器上必炸）。
       用默认权限的 `os.makedirs` 就没有这个问题；目录名固定、每次先清空，
       也不需要 mkdtemp 的随机名。
    """
    path = os.path.join(cloud_root(), "icons-staging")
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def icons_dir() -> str:
    """云端图标目录：`<数据根>/config/cloud/icons`（不存在就创建）"""
    path = os.path.join(cloud_root(), ICLOUD_SUBDIR)
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def bundled_icons_dir() -> str:
    """程序自带的那批图标（`.ToolsGCP/images/icon`，本地模式与云端兜底都用它）"""
    return os.path.join(CONFIG_DIR, "images", "icon")


def icon_meta_file() -> str:
    return os.path.join(cloud_dir(), ICON_META_NAME)


def icon_file(name: str) -> str:
    """按文件名找图标：**云端优先**，没有再退回程序自带的那份
    找不到返回空串。调用方（webhost 路由）拿到空串就 404。
    ⚠️ `name` 只取 basename —— 路由层已经把路径安全处理过了，
       这里再掐一次是双保险（防目录穿越）。
    """
    base = os.path.basename(str(name or "").replace("\\", "/"))
    if not base:
        return ""
    for directory in (icons_dir(), bundled_icons_dir()):
        try:
            candidate = os.path.join(directory, base)
            if os.path.isfile(candidate):
                return candidate
        except Exception:
            continue
    return ""


# ==========================================================================
# zip 安全解压
# ==========================================================================

def _safe_names(zf: zipfile.ZipFile):
    """过滤出**可以**落盘的成员：普通文件、图片后缀、路径安全
    · 目录条目（以 / 结尾）跳过；
    · `..` / 绝对路径 / 盘符 → 剥成纯文件名（zip 里理论上不该有，防恶意包）；
    · 非图片后缀跳过。
    """
    result = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        raw = str(info.filename or "").replace("\\", "/")
        if not raw:
            continue
        base = os.path.basename(raw)
        if not base or base in (".", ".."):
            continue
        ext = os.path.splitext(base)[1].lower()
        if ext not in _ALLOWED_EXT:
            continue
        if re.match(r"^[A-Za-z]:", raw) or raw.startswith("/"):
            # 绝对路径成员：只保留文件名，绝不按原路径写
            pass
        result.append((info, base))
    return result


def _extract_zip(data: bytes, staging: str) -> dict:
    """把 icon.zip 的字节解到 staging → {files: {名字: 路径}, bytes, skipped}
    ⚠️ **先解到临时目录、全部成功后再由调用方整批替换**：
       写到一半崩（磁盘满/杀软拦）不会留下"半批图标"，旧的一批继续可用。
    ⚠️ 只落图片后缀、只取 basename：zip 里混进别的文件（或恶意路径）也写不出去。
    """
    import io
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            members = _safe_names(zf)
            skipped = max(0, len(zf.infolist()) - len(members))
            total = 0
            written = {}
            for info, base in members:
                size = int(info.file_size or 0)
                total += size
                if size > _MAX_MEMBER_BYTES:
                    skipped += 1
                    continue
                if total > _MAX_TOTAL_BYTES:
                    raise zipfile.BadZipFile("整包解压后超出大小上限")
                target = os.path.join(staging, base)
                # 双保险：base 已经是纯文件名，不可能越界
                if not os.path.abspath(target).startswith(os.path.abspath(staging) + os.sep):
                    skipped += 1
                    continue
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, 256 * 1024)
                written[base] = target
            return {"files": written, "bytes": total, "skipped": skipped}
    except zipfile.BadZipFile as exc:
        raise CloudIconBadZip(str(exc))
    except Exception as exc:                        # noqa: BLE001
        raise CloudIconBadZip(f"{type(exc).__name__}: {exc}")


class CloudIconBadZip(Exception):
    """zip 坏了/不是 zip（对内传递，对外只出机器码 BAD_RESPONSE）"""


def _publish(staging: str, written: dict, target_dir: str) -> int:
    """把临时目录里解好的文件**逐个替换**进正式目录（同名覆盖），返回成功数"""
    import errno
    count = 0
    os.makedirs(target_dir, exist_ok=True)
    for base, path in written.items():
        destination = os.path.join(target_dir, base)
        try:
            try:
                os.replace(path, destination)
            except OSError as exc:
                # 极少数情况：目标正被占用（图标正在显示）
                # → 先删旧的再挪；再失败就跳过这个文件，不阻塞整体
                if exc.errno not in (errno.EACCES, errno.EBUSY, 32):
                    raise
                try:
                    os.remove(destination)
                    os.replace(path, destination)
                except Exception:
                    continue
            count += 1
        except Exception:
            continue
    return count


# ==========================================================================
# 同步本体
# ==========================================================================

class CloudIconSource:
    """和 CloudResourceSource 同构：选最新 release → 找 icon.zip → 下载（镜像）→ 解压落地
    ⚠️ 对外方法（sync / status）**永不向上抛异常**，失败只体现在返回 dict 里。
    参数可注入（repo / mirrors / releases_api）是留给测试里用本地 http.server 模拟的。
    """

    def __init__(self, repo: str = "", mirrors=None, timeout: float = TIMEOUT_SECONDS,
                 retries: int = MAX_RETRY, releases_api: str = ""):
        self.repo = str(repo or APP_REPO).strip()
        # ⚠️ 调用方**显式**指定过 repo / releases_api（测试注入本地 http.server）：
        #    候选链就只用这一个仓库。必须在这里记下来 —— 因为 `sync()` 成功后
        #    会把 self.repo 改写成"真正生效的那个仓库"（给 status()/meta 显示用），
        #    之后再靠比较 self.repo != APP_REPO 判"是不是注入的"就永远不成立了。
        self._repo_explicit = bool(str(repo or "").strip())
        self.mirrors = None if mirrors is None else list(mirrors)
        self.timeout = float(timeout or TIMEOUT_SECONDS)
        self.retries = int(MAX_RETRY if retries is None else retries)
        self.releases_api = str(releases_api or "").strip()
        self.last_error = ""
        self.last_used_url = ""

    # ---------- 仓库候选链 ----------
    def _repo_chain(self) -> list:
        """要依次试的仓库：新资源仓库 → 旧主仓库兜底（与 JSON 那条完全一致）。

        ⚠️ 显式注入过 repo / releases_api（测试用本地 http.server 模拟）时**只用一个**：
           否则测试会被"第二个仓库意外通过"骗过去，本地服务还被打两遍。
        """
        if self._repo_explicit or self.releases_api:
            return [self.repo]
        out = []
        for repo in RESOURCES_REPO_CHAIN:
            repo = str(repo or "").strip()
            if repo and repo not in out:
                out.append(repo)
        return out or [self.repo]

    def _pick_release(self, repo: str):
        """拉某仓库的 release 列表并挑最新的一个；任何失败都只返回 None
        （不抛、不打一堆 warn：换仓库重试是**正常路径**，刷屏才是问题）"""
        import json
        try:
            from .cloud_resource_source import RELEASES_API, RELEASES_PER_PAGE
            api_url = self.releases_api or RELEASES_API.format(
                repo=repo, per_page=RELEASES_PER_PAGE)
            _st, body, _hd, used_url = http_get(
                build_candidate_urls(api_url, self.mirrors),
                self.timeout, self.retries,
                deadline=time.monotonic() + self.timeout * 3)
            releases = json.loads(body.decode("utf-8", "ignore"))
            if not isinstance(releases, list):
                return None
            self.last_used_url = used_url
            release = select_latest_release(releases)
            if release is None:
                _log("info", f"图标云端：仓库 {repo} 没有可用 release")
            return release
        except Exception as exc:                    # noqa: BLE001
            self.last_error = "NETWORK"
            _log("info", f"图标云端：拉 {repo} 的 release 列表失败（{exc}）")
            return None

    # ---------- 状态 ----------
    def read_meta(self) -> dict:
        import json
        try:
            path = icon_meta_file()
            if not os.path.isfile(path):
                return {}
            with open(path, "r", encoding="utf-8") as stream:
                data = json.load(stream)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_meta(self, meta: dict):
        import json
        try:
            from .cloud_resource_source import atomic_write_json
            atomic_write_json(icon_meta_file(), meta)
        except Exception as exc:                    # noqa: BLE001
            _log("warn", f"写图标元数据失败（不影响使用）: {exc}")

    def status(self) -> dict:
        """纯读状态（不联网）：给设置页那行"云端图标"状态用"""
        meta = self.read_meta()
        directory = icons_dir()
        files = 0
        bytes_total = 0
        try:
            for name in os.listdir(directory):
                full = os.path.join(directory, name)
                if os.path.isfile(full):
                    files += 1
                    bytes_total += os.path.getsize(full)
        except Exception:
            pass
        fetched_at = meta.get("fetched_at") or 0
        from .cloud_resource_source import _now_text
        return {
            "configured": bool(self.repo),
            "available": files > 0,
            "version": str(meta.get("version") or ""),
            "tag": str(meta.get("tag") or ""),
            "updated_at": _now_text(fetched_at) if fetched_at else "",
            "count": files,
            "bytes": bytes_total,
            "error": str(meta.get("error") or ""),
            "error_key": "cloud_error_" + str(meta.get("error") or "") if meta.get("error") else "",
            "path": directory,
            "repo": self.repo,
        }

    # ---------- 找附件 ----------
    def find_icon_asset(self, release):
        """在 release.assets 里找 icon.zip（大小写不敏感、精确同名）"""
        for asset in ((release or {}).get("assets") or []):
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "").strip()
            if name.lower() != ICON_ASSET_NAME.lower():
                continue
            if not str(asset.get("browser_download_url") or "").strip():
                continue
            return asset
        return None

    # ---------- 同步 ----------
    def sync(self, force: bool = False) -> dict:
        """完整跑一遍：拉 release → 找 icon.zip → 下载 → 解压 → 落地
        返回 {ok, updated, tag, version, count, bytes, error}
        · 已有同步记录且 tag 没变且非 force → `updated=False, ok=True`（"已是最新"），
          这是省流量的关键：图标包 4MB，不能每次启动都重下。
        """
        result = {"ok": False, "updated": False, "version": "", "count": 0,
                  "bytes": 0, "error": ""}
        meta = self.read_meta()
        if not meta:
            # 目录里已经有图标（上次同步残留）但元数据丢了 → 先补一份，
            # 避免每次启动都为"有没有变"再打一次 API
            status = self.status()
            if status["available"]:
                meta = {"count": status["count"]}
        if (not force) and str(meta.get("asset_url") or "") and int(meta.get("count") or 0) > 0:
            pass   # 有上次成功记录：下面对完 tag 才决定要不要重新下载
        self.last_error = ""
        # ---- 1) release 列表 → 选最新（**按仓库候选链依次试**）----
        # ⚠️ 本轮需求（用户原话）：icon.zip 的地址改到
        #    https://github.com/Galen563/ToolsGCP-Resources/releases 。
        #    和 JSON 那条完全同一套做法：新仓库优先、拿不到退回旧仓库 ——
        #    新仓库此刻还没有 release（已用 GitHub API 核过），
        #    裸替换会让所有用户的云端图标当场失效（只能退回程序自带图标）。
        picked = None
        saw_release = False            # 至少有一个仓库给了 release（只是没附件）
        for repo in self._repo_chain():
            release = self._pick_release(repo)
            if release is not None:
                saw_release = True
                asset = self.find_icon_asset(release)
                if asset is not None:
                    picked = (repo, release, asset)
                    break
                _log("info", f"图标云端：仓库 {repo} 的 release 里没有 {ICON_ASSET_NAME}，"
                             f"改用下一个候选仓库")
        if picked is None:
            # ⚠️ 错误码必须**如实区分**：有 release 但没附件 = NO_ASSET，
            #    一个 release 都没有 = NO_RELEASE。全兜底成 NO_RELEASE 的话，
            #    设置页那行状态会告诉用户"仓库没发布版本"，而真正的原因
            #    是"发布了但没带 icon.zip"——排查方向直接被带偏。
            self.last_error = self.last_error or (ERR_NO_ASSET if saw_release
                                                  else ERR_NO_RELEASE)
            result["error"] = self.last_error
            _touch(self, meta)
            return result
        self.repo, release, asset = picked      # status() / meta 里显示真正生效的那个
        tag = str(release.get("tag_name") or "").strip()
        version = tag[1:] if tag[:1] in ("v", "V") else tag
        result["version"] = version
        # ⚠️ 这里**不再**需要"没有 icon.zip 附件"的分支：上面选仓库那一步已经
        #    把"有附件"作为命中条件了（没附件的仓库直接换下一个）。
        asset_url = str(asset.get("browser_download_url") or "").strip()

        # ---- 3) 已是最新？（同 tag + 同大小 + 目录里非空 + 非 force）----
        if not force:
            same_tag = str(meta.get("tag") or "") == tag
            same_size = int(meta.get("asset_size") or 0) == int(asset.get("size") or 0)
            if same_tag and same_size and int(meta.get("count") or 0) > 0:
                result.update({"ok": True, "updated": False, "count": int(meta.get("count") or 0)})
                _touch(self, meta)
                return result

        # ---- 4) 下载 ----
        try:
            _st, blob, _hd, download_url = http_get(
                build_candidate_urls(asset_url, self.mirrors),
                self.timeout, self.retries,
                deadline=time.monotonic() + self.timeout * 3)
        except Exception as exc:                    # noqa: BLE001
            self.last_error = ERR_NETWORK
            result["error"] = self.last_error
            _log("warn", f"图标云端：下载 {ICON_ASSET_NAME} 失败（{exc}），沿用现有图标",
                 code=str(getattr(exc, "code", "") or "NETWORK"))
            _touch(self, meta)
            return result

        # ---- 5) 解压（先临时目录，成功后再整批替换）----
        staging = _make_staging()
        try:
            extracted = _extract_zip(blob, staging)
        except Exception as exc:                    # noqa: BLE001
            shutil.rmtree(staging, ignore_errors=True)
            self.last_error = ERR_BAD_RESPONSE
            result["error"] = ERR_BAD_RESPONSE
            _log("err", f"图标云端：{ICON_ASSET_NAME} 解压失败（{exc}），保留旧图标")
            _touch(self, meta)
            return result
        if not extracted["files"]:
            shutil.rmtree(staging, ignore_errors=True)
            self.last_error = ERR_BAD_RESPONSE
            result["error"] = ERR_BAD_RESPONSE
            _log("err", f"图标云端：{ICON_ASSET_NAME} 里没有可落盘的图标文件，保留旧图标")
            _touch(self, meta)
            return result

        # ---- 6) 发布到正式目录 ----
        target = icons_dir()
        try:
            count = _publish(staging, extracted["files"], target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        if count <= 0:
            self.last_error = ERR_BAD_RESPONSE
            result["error"] = ERR_BAD_RESPONSE
            _log("err", "图标云端：解压成功但一个文件都没写进去（占用/权限），保留旧图标")
            _touch(self, meta)
            return result

        import json as _json
        now = time.time()
        new_meta = {
            "repo": self.repo,
            "version": version,
            "tag": tag,
            "asset_name": ICON_ASSET_NAME,
            "asset_url": asset_url,
            "asset_size": int(asset.get("size") or len(blob)),
            "fetched_at": now,
            "fetched_at_text": _now_text_s(now),
            "last_check_at": now,
            "count": count,
            "bytes": extracted["bytes"],
            "skipped": extracted["skipped"],
            "source_url": download_url,
            "error": "",
        }
        self._write_meta(new_meta)
        result.update({"ok": True, "updated": True, "count": count,
                       "bytes": extracted["bytes"], "error": ""})
        _log("op", f"云端图标已更新：{tag}（{count} 个，"
                   f"{extracted['bytes'] / 1024 / 1024:.1f}MB → {target}）",
             tag=tag, count=count, asset=ICON_ASSET_NAME)
        return result


# ==========================================================================
# 内部辅助（与 cloud_resource_source 同一套日志口径）
# ==========================================================================

def _touch(instance, meta: dict):
    """把"这次检查过"写进元数据（失败也记）—— 跨进程节流，重启不会绕过它"""
    try:
        merged = dict(meta or {})
        merged["last_check_at"] = time.time()
        instance._write_meta(merged)
    except Exception:
        pass


def _now_text_s(timestamp: float) -> str:
    from .cloud_resource_source import _now_text
    return _now_text(timestamp)


def _log(level: str, message: str, **fields):
    try:
        from ..utils.logger import log
        getattr(log, level, log.info)("图标", "cloud", message, **fields)
    except Exception:
        pass


# ==========================================================================
# 后台同步（首屏不阻塞）
# ==========================================================================

_BG_LOCK = threading.RLock()
_BG_STATE = {"running": False, "last_attempt": 0.0, "last_finished": 0.0,
             "last_result": None}
_NOTIFIER = [None]


def set_notifier(callback):
    """注册"图标同步完成"的通知（API 层负责推事件；core 层不认识 shell）"""
    _NOTIFIER[0] = callback if callable(callback) else None


def background_state() -> dict:
    with _BG_LOCK:
        return dict(_BG_STATE)


def ensure_background_sync(min_interval: float = BACKGROUND_MIN_INTERVAL,
                           force: bool = False, source: CloudIconSource = None) -> bool:
    """没同步过就起一条守护线程去同步 → 返回是否真的起了线程
    ⚠️ 只在后台线程里联网：首屏（webhost 的图标路由）永远不会被它卡住。
       路由是"云端目录有就用、没有就用自带的"——所以同步完成前显示自带图标，
       完成后推事件让前端 resetIconRetries() 刷新，观感上是平滑升级。
    """
    now = time.monotonic()
    with _BG_LOCK:
        if _BG_STATE["running"]:
            return False
        if not force and (now - float(_BG_STATE["last_attempt"] or 0)) < float(min_interval):
            return False
        if not force:
            probe = source or CloudIconSource()
            try:
                last_check = float(probe.read_meta().get("last_check_at") or 0)
            except Exception:
                last_check = 0.0
            if last_check and (time.time() - last_check) < float(min_interval):
                return False
        _BG_STATE["running"] = True
        _BG_STATE["last_attempt"] = now

    def _work():
        result = {}
        try:
            result = (source or CloudIconSource()).sync(force=force)
        except Exception as exc:                    # noqa: BLE001 - 兜底，绝不带崩线程
            result = {"ok": False, "updated": False, "error": ERR_NETWORK,
                      "detail": str(exc)}
            _log("warn", f"后台同步云端图标异常: {exc}")
        finally:
            with _BG_LOCK:
                _BG_STATE["running"] = False
                _BG_STATE["last_finished"] = time.monotonic()
                _BG_STATE["last_result"] = dict(result or {})
        callback = _NOTIFIER[0]
        if callback is not None:
            try:
                callback(dict(result or {}))
            except Exception as exc:                # noqa: BLE001
                _log("warn", f"图标同步通知失败: {exc}")

    threading.Thread(target=_work, name="ToolsGCP-cloud-icons", daemon=True).start()
    return True


__all__ = [
    "ICON_ASSET_NAME",
    "CloudIconSource",
    "icons_dir", "bundled_icons_dir", "icon_file", "icon_meta_file",
    "ensure_background_sync", "set_notifier", "background_state",
]
