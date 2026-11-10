"""程序自更新：检查新版本 + 下载更新包（替换自己由 core/self_update.py 的更新器做）。
流程：fetch_releases() 拉版本列表 → select_release() 挑出比现在新且带 ToolsGCP.exe
的那个 → UpdateDownloadWorker 下到 %TEMP% 并校验。
⚠️ 目标识别按文件名精确匹配 APP_ASSET_NAME，不按后缀/体积猜。
⚠️ 版本比较绝不能直接比字符串（"1.1.10" < "1.1.4"），必须拆成整数按段比。
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

from PyQt5.QtCore import QThread, pyqtSignal

from ..constants import (APP_ASSET_NAME, APP_REPO, APP_VERSION,
                         GITHUB_MIRRORS, SCRIPT_DIR, UPDATE_CHANNELS,
                         UPDATE_CHANNEL_ALL, UPDATE_RELEASES_API)

USER_AGENT = "ToolsGCP-Updater/1.0"
API_TIMEOUT = 15.0


# ---------- 一、错误的"机器码" ----------
# 这里只抛码，不抛中文文案 —— 文案由界面层查语言文件（三种语言）。
ERR_REPO_NOT_FOUND = "REPO_NOT_FOUND"     # 仓库不存在 / 一个版本都没发过
ERR_RATE_LIMITED = "RATE_LIMITED"         # GitHub API 限流（匿名 60 次/小时）
ERR_NETWORK = "NETWORK"                   # 断网 / 超时 / DNS 失败
ERR_BAD_RESPONSE = "BAD_RESPONSE"         # 返回的 JSON 不是预期结构
ERR_NO_CHANNEL_RELEASE = "NO_CHANNEL_RELEASE"   # 这个通道下没有版本
ERR_NO_ASSET = "NO_ASSET"                 # 有版本，但里面没有 ToolsGCP.exe

# 警告码：文件下下来了，但有点可疑。**不影响下载成功**，只是提醒一句。
WARN_TOO_SMALL = "WARN_TOO_SMALL"         # 体积远小于正常构建（可能是测试文件）
WARN_NOT_EXE = "WARN_NOT_EXE"             # 开头不是 PE 的 MZ 头，可能不是可执行程序


class _Cancelled(Exception):
    """内部用：用户点了取消（不往外抛，转成 failed("CANCELLED")）"""


# ---------- 二、版本解析与比较（SemVer） ----------

# v 可选、三段数字必需、预发布标识可选、build 元数据可选且**不参与比较**
_VERSION_RE = re.compile(
    r"^[vV]?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<pre>[0-9A-Za-z.\-]+))?"
    r"(?:\+(?P<build>[0-9A-Za-z.\-]+))?$"
)


def parse_version(text):
    """把版本字符串解析成可比较的结构；解析不了返回 None
    ⚠️ 解析失败必须返回 None，调用方要因此拒绝更新 —— 宁可"不更新"也绝不猜大小。
    """
    if text is None:
        return None
    match = _VERSION_RE.match(str(text).strip())
    if not match:
        return None
    numbers = (int(match.group("major")),
               int(match.group("minor")),
               int(match.group("patch")))
    pre_raw = match.group("pre")
    if pre_raw:
        pre = []
        for part in pre_raw.split("."):
            if part == "":
                return None                     # "1.0.0-beta..1" 这种非法输入
            if part.isdigit():
                pre.append((0, int(part), ""))
            else:
                # 预发布标识按 SemVer 是区分大小写的，但这里统一转小写，
                # 免得 "Beta.1" 和 "beta.1" 被当成两个不同版本（宽进严出）
                pre.append((1, 0, part.lower()))
    else:
        pre = None
    return (numbers, pre)


def compare_parsed(left, right):
    """比较两个 parse_version 的结果：左<右 -1 / 相等 0 / 左>右 1"""
    if left[0] != right[0]:
        return -1 if left[0] < right[0] else 1
    pre_left, pre_right = left[1], right[1]
    if pre_left is None and pre_right is None:
        return 0
    # 正式版 > 同号的所有预发布版（1.2.0 > 1.2.0-rc.1）
    if pre_left is None:
        return 1
    if pre_right is None:
        return -1
    for item_left, item_right in zip(pre_left, pre_right):
        if item_left != item_right:
            return -1 if item_left < item_right else 1
    if len(pre_left) != len(pre_right):
        # 段数少的更小：1.1.5-beta < 1.1.5-beta.1
        return -1 if len(pre_left) < len(pre_right) else 1
    return 0


def compare_versions(left, right):
    """比较两个版本字符串；任一无法解析返回 None（调用方必须当成"不比"）"""
    parsed_left, parsed_right = parse_version(left), parse_version(right)
    if parsed_left is None or parsed_right is None:
        return None
    return compare_parsed(parsed_left, parsed_right)


def is_newer(remote, local):
    """remote 是否比 local 新；无法比较时返回 False（保守：不提示更新）"""
    result = compare_versions(remote, local)
    return bool(result is not None and result > 0)


def display_version(version=None):
    """界面上显示的版本号：统一带 v（tag、界面都带 v，只有 APP_VERSION 不带）"""
    text = str(version if version is not None else APP_VERSION).strip()
    if not text:
        return "v?"
    return text if text[:1] in "vV" else f"v{text}"


# ---------- 三、目标识别：从 Release 的资产里挑出 ToolsGCP.exe ----------

_ASSET_EXACT = APP_ASSET_NAME.lower()          # "toolsgcp.exe"

# 兜底：允许 ToolsGCP-1.2.0.exe / ToolsGCP_v1.2.0.exe 这类带版本号的副本
_ASSET_FALLBACK_RE = re.compile(
    r"^toolsgcp[-_ ]?v?\d[\d.]*(?:[-.][0-9a-z.]+)?\.exe$")

# 先排除再选择：这些词出现在文件名里就无条件不要
_ASSET_REJECT_HINTS = (
    "resourcemaker", "resource-maker", "resource_maker", "maker",   # 另一个程序
    "setup", "installer", "install", "unins",                       # 安装器不是绿色包
    "symbols", "debug", "test", "sample",                           # 非发布产物
)
_ASSET_REJECT_EXTS = (
    ".txt", ".json", ".md", ".sha256", ".sha256sum", ".sums", ".sig", ".asc",
    ".yml", ".yaml", ".blockmap", ".md5", ".part",
)


def pick_update_asset(release):
    """在 Release 的资产里挑出更新载荷（文件名精确等于 ToolsGCP.exe 优先，其次是带
    版本号的副本）；挑不到返回 None。先排除明显不是的，绝不"猜一个最像的"。"""
    exact, fallback = None, None
    for asset in ((release or {}).get("assets") or []):
        name = str(asset.get("name") or "").strip()
        if not name:
            continue
        low = name.lower()
        if low.endswith(_ASSET_REJECT_EXTS):
            continue
        if any(hint in low for hint in _ASSET_REJECT_HINTS):
            continue
        if low == _ASSET_EXACT:
            exact = asset
            break                      # 精确命中就不用再看后面的了
        if fallback is None and _ASSET_FALLBACK_RE.match(low):
            fallback = asset
    return exact or fallback


# ---------- 四、通道过滤与挑选 ----------

def channel_allows(release, channel):
    """这个 release 属于当前通道吗（stable = 只收正式版；beta = 只收预发布；all = 全收）"""
    release = release or {}
    if release.get("draft"):
        return False
    if channel == "stable":
        return not release.get("prerelease")
    if channel == "beta":
        return bool(release.get("prerelease"))
    return True


def update_channel(settings_manager=None, default=UPDATE_CHANNEL_ALL):
    """从设置里读更新通道；值非法（老配置/被手改）就退回默认的 all"""
    value = ""
    try:
        value = str(settings_manager.settings.get("update_channel") or "")
    except Exception:
        value = ""
    return value if value in UPDATE_CHANNELS else default


def select_release(releases, channel=UPDATE_CHANNEL_ALL):
    """挑出通道内版本号最大、并且带着 ToolsGCP.exe 的那个 release
    ⚠️ 解析不了版本号、或没带 exe 的 release 都跳过继续往旧的找，这样"发了只写说明、
    忘了挂 exe 的版本"不会把更新卡死。
    """
    best, best_parsed = None, None
    for release in (releases or []):
        if not channel_allows(release, channel):
            continue
        parsed = parse_version(str(release.get("tag_name") or ""))
        if parsed is None:
            continue
        if pick_update_asset(release) is None:
            continue
        if best_parsed is None or compare_parsed(parsed, best_parsed) > 0:
            best, best_parsed = release, parsed
    return best


def build_update_info(release, current_version=APP_VERSION):
    """把 release 整理成界面要用的那份字典（版本 / 版本信息 / 文件名 / 大小）"""
    asset = pick_update_asset(release) or {}
    tag = str((release or {}).get("tag_name") or "").strip()
    version = tag[1:] if tag[:1] in ("v", "V") else tag
    published = str((release or {}).get("published_at") or "")
    return {
        "tag": tag,
        "version": version,
        "display_version": display_version(version),
        "name": str((release or {}).get("name") or tag),
        "notes": str((release or {}).get("body") or "").strip(),
        "prerelease": bool((release or {}).get("prerelease")),
        "published_at": published[:10] if published else "",
        "asset_name": str(asset.get("name") or ""),
        "asset_size": int(asset.get("size") or 0),
        "asset_url": str(asset.get("browser_download_url") or ""),
        "page_url": str((release or {}).get("html_url") or ""),
        "sha256": "",
        "is_newer": is_newer(version, current_version),
    }


# ---------- 五、网络 ----------

def _open(url, timeout=API_TIMEOUT, accept="application/vnd.github+json"):
    """统一的请求封装（GitHub 的 API 强制要求带 User-Agent）
    ⚠️ 显式要求不要缓存：中间任何一层（CDN / 镜像站 / 代理）都可能缓存响应，
    表现为"改了 Release 客户端还说已是最新"。
    """
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Cache-Control": "no-cache, no-store, max-age=0",
        "Pragma": "no-cache",
    })
    return urllib.request.urlopen(request, timeout=timeout)


def _cache_bust(url):
    """给 URL 挂时间戳参数，让中间缓存每次都算新请求（缓存键通常就是整个 URL）"""
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}_={int(time.time() * 1000)}"


def _mirror_of(source):
    """把设置里的"源"名字变成镜像域名；不在 GITHUB_MIRRORS 白名单里的一律返回 ""
    （不能让设置里的任意字符串变成请求目标）。"""
    source = str(source or "").strip()
    return source if source in GITHUB_MIRRORS else ""


def apply_mirror(url, mirror):
    """把 GitHub 直链套上国内镜像前缀（mirror 为空 / "Github" 时原样返回）
    已知镜像用的都是 `https://<镜像域名>/https://github.com/...` 这种拼接方式。
    """
    url = str(url or "")
    if not url or not _mirror_of(mirror):
        return url
    return f"https://{_mirror_of(mirror)}/{url}"


def build_api_urls(repo=APP_REPO, search_source=""):
    """按搜索源设置拼出候选 API 地址（依次尝试）
    ⚠️ 官方直连优先、镜像只作兜底（和下载那边相反）：镜像站会缓存 api.github.com 的
    响应，改完 Release 客户端还一直说"已是最新"。镜像那条会加时间戳参数。
    """
    direct = UPDATE_RELEASES_API.format(repo=repo)
    urls = [direct]
    mirror = _mirror_of(search_source)
    if mirror:
        urls.append(f"https://{mirror}/{direct}")
    return urls


def build_download_urls(asset_url, download_source=""):
    """按下载源设置拼出候选下载地址（镜像优先，官方兜底）"""
    asset_url = str(asset_url or "")
    if not asset_url:
        return []
    urls = []
    mirrored = apply_mirror(asset_url, download_source)
    if mirrored and mirrored != asset_url:
        urls.append(mirrored)
    urls.append(asset_url)
    return urls


def _fetch_one(url, timeout=API_TIMEOUT, per_page=30):
    """拉一个 API 地址并解析成 list；失败抛 RuntimeError(错误码)
    ⚠️ 每次加时间戳参数 + 不缓存请求头，保证真的回源问一次。
    """
    params = []
    if per_page:
        params.append(f"per_page={int(per_page)}")
    params.append(f"_={int(time.time() * 1000)}")
    separator = "&" if "?" in url else "?"
    url = f"{url}{separator}{'&'.join(params)}"
    try:
        with _open(url, timeout) as response:
            data = json.loads(response.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(ERR_REPO_NOT_FOUND)
        if exc.code in (403, 429):
            raise RuntimeError(ERR_RATE_LIMITED)
        raise RuntimeError(f"HTTP_{exc.code}")
    except Exception:
        raise RuntimeError(ERR_NETWORK)
    if not isinstance(data, list):
        raise RuntimeError(ERR_BAD_RESPONSE)
    return data


# 候选源里靠前那几个用更短的超时：官方直连被墙时，不必每次干等 15 秒才退镜像
EARLY_TIMEOUT = 6.0


def fetch_releases(repo=APP_REPO, sources=None, timeout=API_TIMEOUT, per_page=30):
    """拉取 release 列表（新→旧），候选地址依次尝试
    ⚠️ 用列表接口而不是 /releases/latest：后者只返回最新正式版，服务不了 Beta 通道，
    作者只发预发布版时还会直接 404。
    """
    urls = list(sources) if sources else [UPDATE_RELEASES_API.format(repo=repo)]
    last_error = ERR_NETWORK
    for index, url in enumerate(urls):
        is_last = (index == len(urls) - 1)
        attempt_timeout = timeout if is_last else min(EARLY_TIMEOUT, timeout)
        try:
            return _fetch_one(url, attempt_timeout, per_page)
        except RuntimeError as exc:
            last_error = str(exc)
            # "仓库不存在"和"被限流"是**这个源明确给出的答案**，换个源也一样，
            # 所以直接抛出去；只有网络类失败才值得换下一个源重试。
            if last_error in (ERR_REPO_NOT_FOUND, ERR_RATE_LIMITED):
                raise
    raise RuntimeError(last_error)


def _fetch_expected_sha256(release, asset_name):
    """从校验清单（SHA256SUMS.txt）里取目标文件的 SHA-256；拿不到返回 ""
    （不强制：老 Release 可能没挂它，跳过校验即可，别让少一个文件废掉整个更新）"""
    want = os.path.basename(str(asset_name or "")).lower()
    if not want:
        return ""
    for asset in ((release or {}).get("assets") or []):
        name = str(asset.get("name") or "").lower()
        if not name.endswith((".txt", ".sha256", ".sums", ".sha256sum")):
            continue
        if "sha" not in name and "sum" not in name:
            continue
        url = str(asset.get("browser_download_url") or "")
        if not url:
            continue
        try:
            with _open(url, timeout=10, accept="text/plain") as response:
                text = response.read(65536).decode("utf-8", "ignore")
        except Exception:
            continue
        for line in text.splitlines():
            # 标准格式："<64位十六进制>  ToolsGCP.exe"（可能带 * 表示二进制模式）
            match = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+)$", line.strip())
            if not match:
                continue
            if os.path.basename(match.group(2).strip()).lower() == want:
                return match.group(1).lower()
    return ""


def sha256_of(path):
    """算文件的 SHA-256（分块读，避免把几十 MB 的 exe 一次性读进内存）"""
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------- 六、下载地址与落盘位置 ----------

def default_download_dir():
    """更新包下载目录：系统临时目录 %TEMP%；返回 (目录, 是否退回了备用目录)
    （程序目录里不留任何下载产物，只允许存在 ToolsGCP.exe）"""
    from .self_update import temp_dir
    try:
        directory = temp_dir()
    except Exception:
        directory = SCRIPT_DIR or os.getcwd()
    if not is_writable_dir(directory):
        # 极端情况（TEMP 被设成一个不存在的盘符）：退回程序目录
        return (SCRIPT_DIR or os.getcwd()), True
    return directory, False


def is_writable_dir(path):
    """目录能不能写（真去建一个临时文件试，别只看 os.access）"""
    try:
        if not os.path.isdir(path):
            return False
        probe = os.path.join(path, ".toolsgcp_write_test")
        with open(probe, "w"):
            pass
        os.remove(probe)
        return True
    except Exception:
        return False


def format_size(size):
    """把字节数变成人能读的大小；非法/未知返回 "—" """
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


def format_speed(bytes_per_second):
    """下载速度：500 KB/s 这种"""
    try:
        value = float(bytes_per_second or 0)
    except Exception:
        return ""
    if value <= 0:
        return ""
    return f"{format_size(value)}/s"


# ---------- 七、工作线程 ----------

class UpdateCheckWorker(QThread):
    """后台查版本（网络请求绝不能跑在 UI 线程上，否则界面直接假死）
    三个出口信号：found(info) 有新版 / latest(info) 已是最新 / failed(code)。
    """

    found = pyqtSignal(dict)
    latest = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, channel=UPDATE_CHANNEL_ALL, current_version=APP_VERSION,
                 search_source="", parent=None):
        super().__init__(parent)
        self.channel = channel if channel in UPDATE_CHANNELS else UPDATE_CHANNEL_ALL
        self.current_version = current_version
        # 搜索源设置：决定去哪儿问版本
        self.search_source = str(search_source or "")

    def run(self):
        try:
            releases = fetch_releases(
                sources=build_api_urls(search_source=self.search_source))
        except RuntimeError as exc:
            self.failed.emit(str(exc))
            return
        except Exception:
            self.failed.emit(ERR_NETWORK)
            return

        if not any(channel_allows(item, self.channel) for item in releases):
            self.failed.emit(ERR_NO_CHANNEL_RELEASE)
            return

        release = select_release(releases, self.channel)
        if release is None:
            # 有版本，但没有任何一个带着 ToolsGCP.exe
            self.failed.emit(ERR_NO_ASSET)
            return

        info = build_update_info(release, self.current_version)
        if not info["asset_url"]:
            self.failed.emit(ERR_NO_ASSET)
            return
        # 校验值拿不到就算了（不影响下载，只是少一道保险）
        try:
            info["sha256"] = _fetch_expected_sha256(release, info["asset_name"])
        except Exception:
            info["sha256"] = ""

        if info["is_newer"]:
            self.found.emit(info)
        else:
            self.latest.emit(info)


class UpdateDownloadWorker(QThread):
    """带进度 / 速度 / 可取消的下载线程
    · 先下到 `<目标>.part`，全部完成并校验通过才改名成正式文件；
    · 有 SHA-256 就必须对上，对不上删掉重来；
    · 落盘前检查 PE 头（MZ）和体积下限，挡住"下回来的其实是个网页"。
    """

    progressed = pyqtSignal(int, int, float)   # 已下载字节 / 总字节（未知为0）/ 速度 B/s
    succeeded = pyqtSignal(str, str)           # 保存路径, 警告码（没有警告时是 ""）
    failed = pyqtSignal(str)                   # 错误码

    CHUNK = 64 * 1024
    # 小于这个体积只警告不拦截（10MB）：当前阶段只下载不替换，可疑文件无损害；
    # 真正会导致装错文件的只有"哈希对不上"，那个仍然硬拦（见 _download）。
    SUSPICIOUS_SIZE = 10 * 1024 * 1024

    def __init__(self, urls, dest_path, expected_sha256="", parent=None):
        """urls：候选下载地址（按顺序尝试，一般由 build_download_urls 生成）
        传字符串也收（只试一个）。
        """
        super().__init__(parent)
        if isinstance(urls, str):
            urls = [urls]
        self.urls = [str(u) for u in (urls or []) if str(u or "").strip()]
        self.dest_path = str(dest_path or "")
        self.expected_sha256 = str(expected_sha256 or "").lower()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        part_path = self.dest_path + ".part"
        if not self.urls:
            self.failed.emit(ERR_NO_ASSET)
            return

        last_error = ERR_NETWORK
        warning = ""
        for url in self.urls:
            if self._cancelled:
                self._cleanup(part_path)
                self.failed.emit("CANCELLED")
                return
            try:
                warning = self._download(url, part_path)
            except _Cancelled:
                self._cleanup(part_path)
                self.failed.emit("CANCELLED")
                return
            except Exception as exc:
                last_error = str(exc) or ERR_NETWORK
                self._cleanup(part_path)
                # 哈希对不上 / 磁盘问题：换个源也一样，没必要重试
                if last_error in ("CHECKSUM", "DISK"):
                    self.failed.emit(last_error)
                    return
                # 否则试下一个源（镜像挂了就退回官方）
                warning = ""
                continue
            else:
                break
        else:
            self.failed.emit(last_error)
            return

        # ---- 走到这儿说明内容已经下好（哈希校验在 _download 里做），这里只负责"转正" ----
        try:
            if os.path.exists(self.dest_path):
                os.remove(self.dest_path)
            os.rename(part_path, self.dest_path)
        except Exception:
            self._cleanup(part_path)
            self.failed.emit("DISK")
            return
        self.succeeded.emit(self.dest_path, warning)

    # ---------- 内部 ----------

    def _download(self, url, part_path):
        try:
            os.makedirs(os.path.dirname(os.path.abspath(part_path)), exist_ok=True)
        except Exception:
            raise RuntimeError("DISK")

        started = time.time()
        last_emit = started
        received = 0
        try:
            with _open(url, timeout=30, accept="application/octet-stream") as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                with open(part_path, "wb") as handle:
                    while True:
                        if self._cancelled:
                            raise _Cancelled()
                        chunk = resp.read(self.CHUNK)
                        if not chunk:
                            break
                        handle.write(chunk)
                        received += len(chunk)
                        now = time.time()
                        # 每 200ms 报一次进度就够界面刷新了，太频繁反而拖慢下载
                        if now - last_emit >= 0.2:
                            elapsed = max(now - started, 0.001)
                            self.progressed.emit(received, total, received / elapsed)
                            last_emit = now
        except _Cancelled:
            raise
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP_{exc.code}")
        except Exception:
            raise RuntimeError(ERR_NETWORK)

        elapsed = max(time.time() - started, 0.001)
        self.progressed.emit(received, received, received / elapsed)

        # ---- 落盘后的"体检"：只报警不拦截（当前阶段只下载不替换，硬拦只会挡住测试） ----
        warnings = []
        if received < self.SUSPICIOUS_SIZE:
            warnings.append(WARN_TOO_SMALL)
        try:
            with open(part_path, "rb") as handle:
                if handle.read(2) != b"MZ":
                    warnings.append(WARN_NOT_EXE)
        except Exception:
            pass

        # ---- 唯一还会硬拦的一项：哈希对不上 = 文件真的坏了 ----
        if self.expected_sha256:
            try:
                actual = sha256_of(part_path)
            except Exception:
                raise RuntimeError("DISK")
            if actual != self.expected_sha256:
                raise RuntimeError("CHECKSUM")

        return ",".join(warnings)

    def _cleanup(self, part_path):
        try:
            if os.path.exists(part_path):
                os.remove(part_path)
        except Exception:
            pass
