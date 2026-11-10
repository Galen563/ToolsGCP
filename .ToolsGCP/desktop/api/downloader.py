"""GitHub Releases 下载后端 —— `api.downloader.*`
========== 一、这个域负责什么 ==========
部署页/更新页/资源详情都调 `downloader.start(...)`，本域提供
选最新版本 → 自动找到对应系统/架构的安装包 → 直接下的完整闭环。
========== 二、接口契约（前端按这个联调，名字/参数/返回值不要改）==========
`downloader.releases(github_url="", page=1, per_page=30, source="")`
    github_url 支持 `https://github.com/owner/repo`、带 `.git`/尾斜杠/`/releases`、
    `owner/repo`、`git@github.com:owner/repo.git`。
    → `{ok, repo, releases:[{tag, name, prerelease, draft, published_at, body,
                             html_url, zipball_url, tarball_url,
                             assets:[{name, size, download_url, content_type}]}],
        page, per_page, count, cached, source, error}`
    ⚠️ **包含 prerelease、不包含 draft**（本项目当前只有 beta 版，忽略预发布就永远没东西）。
    ⚠️ `source` 参数（`official` 官方 / `all` 全部），空 = 用用户设置里的
       `releases_source`（默认 official）。官方 = 已筛选的列表（只留有正式发布产物的
       release）；全部 = 再给每个 release 追加 GitHub 自动生成的 zip / tar.gz 源码包。
       过滤在返回前做，两种来源**共用同一份 GitHub 缓存**，切下拉框不用重新请求。
    失败 → `{ok:false, error:"<机器码>", repo}`，机器码见本文件末尾 ERR_*。
`downloader.resolve_asset(github_url, platform="", arch="")`
    智能关键词匹配：按文件名里的平台/架构关键词 + 扩展名强信号打分，
    源码包 / 校验文件 / 签名 / 调试符号一律排除；安装包优先于压缩包。
    platform: `windows`(默认) / `linux` / `macos`；arch: `x64`(默认) / `arm64` / `x86`。
    → `{ok, repo, platform, arch, asset:{name, size, download_url, score, content_type},
        candidates:[{name, size, score, content_type}], release:{tag, name, prerelease, published_at},
        error}`
    找不到 → `{ok:false, error:"NO_MATCH", candidates:[...]}`（candidates 仍然给，方便排查）
`downloader.start(url, filename="", dir="", expected_size=0, source="")`
    · **立即返回**（下载在后台线程里流式跑，绝不阻塞 js_api）：
        `{ok:true, started:true, id, name, path, dir, total, url}`
    · 后台事件（`shell.push_event`，前端监听 `window.ToolsGCP.on('download.progress', …)`）：
        `download.progress` `{id, status:'downloading'|'done'|'failed'|'canceled',
                              received, total, percent, speed, eta, name, path, error}`
        · percent = 0~100 的 float（total 未知时 0，前端可当不确定态）
        · speed = 字节/秒（float），eta = 剩余秒数（未知时 null）
        · 节流 ≥200ms；**退出闸门**：`shell._teardown_started` 之后不再推
    · 默认下载目录 = **系统下载文件夹**（`<用户主目录>/Downloads`），
      可传 dir 覆盖，也可以用用户设置里的下载保存位置
      （不自动套 `Downloads/ToolsGCP` 子目录）；
    · 多线程分段下载（HTTP Range，线程数来自设置 `download_threads`，
      默认 100；服务器不支持分段时自动退回单线程）、
      失败重试（次数来自设置 `download_retry_count`，默认 5，每次间隔 30s，
      **连接成功后重试计数重置回上限**）。
`downloader.start_wait(url, filename="", dir="", expected_size=0, source="", timeout=0)`
    同上的**同步版本**：等下载结束再返回 `{ok, id, status, path, size, error}`。
    部署页老流程（`await downloader.start(...)` 后用 `result.ok` 判断成功）想保持
    原语义时改调这个即可（`timeout>0` 时超时返回 TIMEOUT，下载线程会继续跑）。
`downloader.cancel(id="")` → `{ok, canceled:bool, status, running:bool}`（id 为空 = 取消全部）
`downloader.list()` → `{ok, items:[{id, url, name, dir, path, status, received, total,
                          percent, speed, eta, error, source, created_at, started_at,
                          finished_at}], active, finished, dir}`
`downloader.open_file(id)` → `{ok, path}` / `{ok:false, error:"NOT_FOUND"}`
`downloader.open_folder(id="")` → `{ok, path}`（id 为空就打开默认下载目录）
`downloader.clear_finished()` → `{ok, removed}`（只清列表，不删文件）
`downloader.retry(id)` → 用同一 id 重新下（重置进度，返回同 start）
`downloader.choose_dir()` → `{ok, path, canceled}`（系统"选择文件夹"，初始位置=当前生效的下载目录）
`downloader.default_dir()` → `{ok, path}`（当前生效的下载目录）
`downloader.settings_info()` → `{ok, dir, default_dir, threads, retry_count, retry_interval}`
    （把当前生效的下载设置回给前端设置 → 下载那几行显示）
========== 三、为什么这些实现细节是这样 ==========
· **镜像前缀**：GitHub 的 `releases/download` 在国内经常直连不通，候选地址 = 官方直连 +
  `constants.GITHUB_MIRRORS` 逐个前缀（顺序按设置里的下载源优先）；一个源失败自动换下一个。
· **文件名清洗 + 同名加 (1)**：asset.name 当不可信输入处理（只取 basename、过滤
  `\\/:*?"<>|`），否则 `../../config/settings.json` 这个名字能把文件写到下载目录之外。
· **退出闸门**：下载线程是 daemon，但 `evaluate_js` 在 WebView2 销毁后会抛
  ObjectDisposedException（AGENTS 第 8 条），所以推送前自己再看一眼 `_teardown_started`。
· **进度节流 200ms**：`push_event` 每次都起一条线程去 evaluate_js，不节流会把 UI 线程打满。
· **保留半成品？不保留**：失败/取消/大小不符都删掉临时文件，避免用户拿到一个坏安装包。
"""

import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from pymodels.constants import GITHUB_MIRRORS

from . import _fail, _log, _ok

# ==========================================================================
# 常量
# ==========================================================================
API_BASE = "https://api.github.com"
GITHUB_WEB = "https://github.com"

USER_AGENT = "ToolsGCP-Downloader/1.0"
TIMEOUT_S = 20.0                 # 单次 HTTP 操作超时（下载是流式的，只算"连上/等下一个块"）
DL_CONNECT_TIMEOUT_S = 3.0       # **下载连接**的短超时（连不上就换源，别让"取消"等 20 秒）
MAX_RETRY = 1                    # 每个候选地址重试次数（网络抖动够用了）
CHUNK_SIZE = 256 * 1024          # 流式下载分块（保留：兼容旧引用）
# ⚠️ socket 每次**实际读**的块大小从 256KB 缩到 32KB。
#    暂停/取消的检查点在"每块读完之后"，多线程分段下载默认 100 个线程，
#    点暂停时每个线程手里还攥着**一个未读完的块** →
#    旧值 100×256KB ≈ 25MB 的"过冲"，进度条肉眼可见继续爬一段
#    （"已经暂停了，进度条还在跑一段才停"的现象）。
#    32KB → 过冲上限 ≈ 3MB，配合前端冻结百分比，基本无感。
READ_CHUNK_SIZE = 32 * 1024
READ_TIMEOUT_S = 1.0             # socket 读超时（让取消1 秒内生效；见 _set_read_timeout）
PROGRESS_INTERVAL_S = 0.2        # 进度推送节流（≥200ms，见模块 docstring）
RELEASES_CACHE_TTL = 600.0       # releases 内存缓存 10 分钟（避免翻来覆去刷 GitHub）
MAX_BODY_CHARS = 20000           # release 正文截断（JSON 太大前端也渲染不动）
MAX_CANDIDATES = 20              # resolve_asset 回传的候选数量

# 错误机器码（只给码，中文文案在语言包/前端）
ERR_BAD_URL = "BAD_URL"
ERR_NETWORK = "NETWORK"
ERR_BAD_RESPONSE = "BAD_RESPONSE"
ERR_RATE_LIMITED = "RATE_LIMITED"
ERR_REPO_NOT_FOUND = "REPO_NOT_FOUND"
ERR_NO_RELEASE = "NO_RELEASE"
ERR_NO_MATCH = "NO_MATCH"
ERR_CANCELED = "CANCELED"
ERR_DISK_ERROR = "DISK_ERROR"
ERR_SIZE_MISMATCH = "SIZE_MISMATCH"
ERR_TOO_MANY = "TOO_MANY"
ERR_NOT_FOUND = "NOT_FOUND"
ERR_UNSUPPORTED = "UNSUPPORTED"
ERR_TIMEOUT = "TIMEOUT"
ERR_EXISTS = "EXISTS"

# ---------- 下载设置（多线程 / 失败重试）----------
# ⚠️ 这些是**兜底常量**：真值一律来自用户设置（settings_manager），
#    这里只给"设置读不到 / 越界"时的安全下限。
DEFAULT_DOWNLOAD_THREADS = 100      # 多线程下载并发数（1~100）
DEFAULT_DOWNLOAD_RETRY = 5          # 失败重试次数（1~20）
MAX_DOWNLOAD_THREADS = 100
MAX_DOWNLOAD_RETRY = 20
RETRY_INTERVAL_S = 30.0             # 每次重试间隔 30 秒

# ---------- Releases 来源（官方 / 全部）----------
RELEASES_SOURCE_OFFICIAL = "official"   # 官方 = 已筛选（只留真正的发布产物）
RELEASES_SOURCE_ALL = "all"             # 全部 = 连 GitHub 自动生成的源码包都列出来

# GitHub 自动为每个 tag 生成的源码包（全部模式要连 zip 和 tar.gz 一起列出）。
# 它们不是 release asset，而是 `zipball_url` /
# `tarball_url` 这两个字段，所以全部模式要把它们**合成**成可下载的条目。
_SOURCE_ARCHIVE_EXT = {"zip": "Source code (zip)", "tar.gz": "Source code (tar.gz)"}

# 默认平台/架构（程序按本机自动判断）
DEFAULT_PLATFORM = "windows"
DEFAULT_ARCH = "x64"

_PLATFORM_ALIASES = {
    "windows": "windows", "win": "windows", "win32": "windows", "win64": "windows",
    "linux": "linux", "ubuntu": "linux", "debian": "linux",
    "macos": "macos", "mac": "macos", "osx": "macos", "darwin": "macos",
    "mac os x": "macos",
}
_ARCH_ALIASES = {
    "x64": "x64", "x86_64": "x64", "x86-64": "x64", "amd64": "x64", "64": "x64",
    "arm64": "arm64", "aarch64": "arm64", "armv8": "arm64",
    "x86": "x86", "i386": "x86", "i686": "x86", "32": "x86", "win32": "x86",
}


# ==========================================================================
# 一、错误 / 小工具
# ==========================================================================
class DownloadError(Exception):
    """带机器码的下载/接口错误（对外不抛，只回 dict）"""

    def __init__(self, code: str, detail: str = ""):
        self.code = str(code or ERR_NETWORK)
        self.detail = str(detail or "")
        super().__init__(self.code)

    def __str__(self):
        return self.code


def _friendly(exc) -> str:
    """把异常翻成一句人话（只进日志，不进返回值）"""
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}：{exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        return f"网络错误：{getattr(exc, 'reason', exc)}"
    if isinstance(exc, (TimeoutError, OSError)) and "timed out" in str(exc).lower():
        return "连接超时"
    return f"{type(exc).__name__}: {exc}"


def _now() -> float:
    return time.time()


# ==========================================================================
# 二、仓库地址解析 / 镜像地址
# ==========================================================================
_REPO_RE = re.compile(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?$")


def parse_repo(github_url: str) -> str:
    """把各种写法的仓库地址解析成 `owner/repo`；解析不了返回空串
    支持：`owner/repo`、`https://github.com/owner/repo`（可带 `.git`、尾斜杠、
    `/releases`、`/tree/main` 之类多余路径、`?tab=` 查询串）、
    `git@github.com:owner/repo.git`、以及镜像前缀（`https://ghfast.top/https://github.com/o/r`）。
    """
    raw = str(github_url or "").strip()
    if not raw:
        return ""
    # 镜像前缀：整串里出现 github.com 之后的部分才是正主
    lowered = raw.lower()
    index = lowered.find("github.com/")
    if index >= 0:
        raw = raw[index + len("github.com/"):]
    elif lowered.startswith("git@github.com:"):
        raw = raw[len("git@github.com:"):]
    raw = raw.split("?", 1)[0].split("#", 1)[0]
    raw = raw.split("://", 1)[-1] if "://" in raw else raw
    # 允许残留 host 前缀（例如镜像站把 github.com 放在路径里）
    raw = raw.strip("/")
    parts = [piece for piece in raw.split("/") if piece]
    if len(parts) >= 2 and parts[0].lower() in ("github.com", "www.github.com"):
        parts = parts[1:]
    if not parts:
        return ""
    if len(parts) == 1:
        return ""
    match = _REPO_RE.match(f"{parts[0]}/{parts[1]}")
    if not match:
        return ""
    owner, repo = match.group(1), match.group(2)
    if repo.lower() in ("releases", "tags", "issues", "pulls"):
        return ""
    return f"{owner}/{repo}"


def _mirror_order(settings_manager=None) -> list:
    """镜像顺序：设置里的下载源优先，其余按 constants.GITHUB_MIRRORS 原序
    ⚠️ GITHUB_MIRRORS 是唯一事实来源（不要在别处再抄一份域名列表）。
    """
    preferred = ""
    try:
        if settings_manager is not None:
            settings = getattr(settings_manager, "settings", {}) or {}
            preferred = str(settings.get("download_source")
                            or settings.get("search_source") or "").strip()
    except Exception:
        preferred = ""
    mirrors = [str(m).strip() for m in (GITHUB_MIRRORS or []) if str(m or "").strip()]
    if preferred and preferred in mirrors:
        mirrors = [preferred] + [m for m in mirrors if m != preferred]
    return mirrors


def build_candidate_urls(url: str, mirrors=None) -> list:
    """候选地址：官方直连 → 各镜像前缀（`https://{镜像}/{原地址}`）
    镜像项允许是完整 URL（自建代理/本地测试服务器）；和云端资源那边同一口径。
    """
    direct = str(url or "").strip()
    if not direct:
        return []
    urls = [direct]
    for mirror in (mirrors or []):
        mirror = str(mirror or "").strip().rstrip("/")
        if not mirror:
            continue
        prefix = mirror if "://" in mirror else f"https://{mirror}"
        candidate = f"{prefix}/{direct}"
        if candidate not in urls:
            urls.append(candidate)
    return urls


# ==========================================================================
# 三、HTTP：拉 GitHub API（带缓存 + 镜像回退）
# ==========================================================================
_RELEASES_CACHE = {}
_CACHE_LOCK = threading.RLock()


def clear_releases_cache():
    """清掉 releases 内存缓存（测试 / 用户手动刷新用）"""
    with _CACHE_LOCK:
        _RELEASES_CACHE.clear()


def _set_read_timeout(response, seconds: float):
    """把 HTTP 响应的 socket **读超时**调小（让取消能立刻生效）
    ⚠️ urllib 的 `timeout` 参数既管连接超时也管 socket 读超时，但**建立连接后**
       读超时就是 20 秒（TIMEOUT_S）—— 一个 chunk 卡住时，用户点取消要等 20 秒。
       这里把底层 socket 的超时单独调小（1 秒），连接超时不变。
    ⚠️ 读超时不是错误：读循环里 catch 之后会回头看取消/暂停标记，没有就继续读。
    """
    try:
        sock = getattr(response, "fp", None)
        # urllib 的 response.fp 是 BufferedReader，raw 才是 socket
        raw = getattr(sock, "raw", None)
        if raw is not None and hasattr(raw, "sock"):
            raw.sock.settimeout(float(seconds))
            return True
        if sock is not None and hasattr(sock, "settimeout"):
            sock.settimeout(float(seconds))
            return True
    except Exception:
        pass
    return False


def _open(url: str, timeout: float = TIMEOUT_S, headers: dict = None):
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    hdrs.update(headers or {})
    return urllib.request.urlopen(urllib.request.Request(url, headers=hdrs),
                                  timeout=max(1.0, float(timeout)))


def _request_json(urls, timeout: float = TIMEOUT_S, retries: int = MAX_RETRY):
    """按候选地址依次 GET + JSON 解析；返回 (data, 用到的地址)；失败抛 DownloadError"""
    last = DownloadError(ERR_NETWORK, "没有候选地址")
    for url in urls:
        for attempt in range(int(retries) + 1):
            try:
                with _open(url, timeout) as response:
                    body = response.read()
                try:
                    return __import__("json").loads(body.decode("utf-8", "ignore")), url
                except Exception as exc:          # noqa: BLE001
                    raise DownloadError(ERR_BAD_RESPONSE, f"JSON 解析失败: {exc}")
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise DownloadError(ERR_REPO_NOT_FOUND, f"HTTP 404 @ {url}")
                if exc.code in (403, 429):
                    # 限流：换源还有可能成功（镜像出口 IP 不同），但同一地址不重试
                    last = DownloadError(ERR_RATE_LIMITED, f"HTTP {exc.code} @ {url}")
                    break
                last = DownloadError(ERR_BAD_RESPONSE, f"HTTP {exc.code} @ {url}")
            except DownloadError as exc:
                last = exc
            except Exception as exc:              # noqa: BLE001
                last = DownloadError(ERR_NETWORK, f"{_friendly(exc)} @ {url}")
            if attempt < int(retries) and last.code != ERR_RATE_LIMITED:
                time.sleep(0.3 * (attempt + 1))
    raise last


# ==========================================================================
# 四、Release / Asset 归一化 + 智能匹配
# ==========================================================================
def _normalize_asset(raw: dict) -> dict:
    raw = raw or {}
    try:
        size = int(raw.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    return {
        "name": str(raw.get("name") or ""),
        "size": size,
        "download_url": str(raw.get("browser_download_url")
                            or raw.get("download_url") or ""),
        "content_type": str(raw.get("content_type") or ""),
    }


def normalize_release(raw: dict) -> dict:
    """GitHub release → 前端要好用的形状（draft 也保留字段，由调用方过滤）"""
    raw = raw or {}
    body = str(raw.get("body") or "")
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + "\n…（内容过长已截断）"
    assets = [_normalize_asset(item) for item in (raw.get("assets") or [])
              if isinstance(item, dict)]
    assets = [item for item in assets if item["name"] and item["download_url"]]
    return {
        "tag": str(raw.get("tag_name") or raw.get("tag") or "").strip(),
        "name": str(raw.get("name") or "").strip(),
        "prerelease": bool(raw.get("prerelease")),
        "draft": bool(raw.get("draft")),
        "published_at": str(raw.get("published_at") or raw.get("created_at") or ""),
        "body": body,
        "html_url": str(raw.get("html_url") or ""),
        "assets": assets,
        # GitHub 自动生成的源码包（**不在** assets 里）
        "zipball_url": str(raw.get("zipball_url") or ""),
        "tarball_url": str(raw.get("tarball_url") or ""),
    }


def source_archive_assets(release: dict) -> list:
    """把 GitHub 自动生成的源码包（zipball / tarball）合成成可下载条目
    ⚠️ 这两个包**不是** release asset：没有 size、没有 content_type，下载下来的大小
       也不固定（GitHub 每次重新打包）。所以 size 给 0（前端显示"—"），
       下载时后端按 expected_size=0 处理（不校验大小）。
    ⚠️ 文件名用 `<tag>.zip` / `<tag>.tar.gz` —— URL 形如 /zipball/<ref>，猜不到文件名。
    """
    release = release or {}
    tag = str(release.get("tag") or "source").strip() or "source"
    out = []
    for key, ext in (("zipball_url", "zip"), ("tarball_url", "tar.gz")):
        url = str(release.get(key) or "").strip()
        if not url:
            continue
        out.append({
            "name": f"{tag}.{ext}",
            "size": 0,
            "download_url": url,
            "content_type": "application/octet-stream",
            "is_source_archive": True,
        })
    return out


# 官方模式下要排除的"噪声"附件：校验文件 / 签名 / 调试符号（它们不是可用的发布产物）
# ⚠️ 判据是**文件名本身**（去扩展名后）等于这些词，或扩展名是其中之一：
#    · "SHA256SUMS" / "sha256sums.txt" / "checksums.txt" / "app.sha256" → 校验文件
#    · "app.sig" / "app.asc" / "gpg.asc"                          → 签名
#    · "app.pdb" / "app.symbols"                                  → 调试符号
#    这样才能覆盖 GitHub 上五花八门的命名（"SHA256SUMS" 没有点号，靠 \.sha256 匹配不到）。
_NOISE_TOKEN_RE = re.compile(
    r"^(sha\d*(sums?)?|md5sum?s?|sums?|checksums?|shasums?|sig|sign|signature|"
    r"asc|gpg|pgp|sbom|debug|symbols?|pdb|dsym)$", re.IGNORECASE)


def _is_noise_asset(name: str) -> bool:
    """这个附件是不是"校验文件 / 签名 / 调试符号"（不算正式发布产物）
    同时看**去扩展名的主体**和**扩展名**：
    · "SHA256SUMS"   → 主体 "sha256sums" 命中
    · "checksums.txt" → 主体 "checksums" 命中
    · "app.sha256"   → 扩展名 "sha256" 命中
    · "app.exe" / "app.zip" → 都不命中（是正常发布产物）
    """
    raw = str(name or "").strip()
    if not raw:
        return False
    stem, ext = os.path.splitext(raw)
    ext = ext.lower().lstrip(".")
    for token in (stem.strip().lower(), ext):
        if token and _NOISE_TOKEN_RE.match(token):
            return True
    return False


def filter_releases_for_source(releases, source: str = RELEASES_SOURCE_OFFICIAL) -> list:
    """按官方 / 全部过滤 release 列表（前端顶部下拉框，默认官方）
    ⚠️⚠️ 两种来源的**语义**（容易搞混，写清楚）：
       · official（官方，**默认**）：**经过筛选**的列表 —— 只保留**有正式发布产物**的
         release（assets 里至少有一个不是校验文件 / 签名 / 调试符号的东西），
         并且**不**追加 GitHub 自动生成的源码包。
       · all（全部）：**完全不做筛选** —— 把 GitHub 返回的 release **原样列出**
         （含预发布、含只有源码包的、含各种奇怪附件的），**只**额外把 GitHub 自动生成的
         zip / tar.gz 源码包补成可下载条目（因为它们不在 assets 里，不补就点不到）。
       ⚠️ 所以：全部= 不筛选 + 补源码包；官方= 筛选过 + 不补源码包。
          官方列表 + 只有源码包的 release那种实现**不是**全部—— 它其实还是筛过。
    """
    source = str(source or RELEASES_SOURCE_OFFICIAL).strip().lower()
    out = []
    for release in (releases or []):
        if not isinstance(release, dict):
            continue
        item = dict(release)
        if source == RELEASES_SOURCE_ALL:
            # 全部：**不筛选**，原样列出；只补源码包（它们不在 assets 里）
            archives = source_archive_assets(release)
            if archives:
                item["assets"] = list(release.get("assets") or []) + archives
            out.append(item)
            continue
        # 官方：只留有正式发布产物的 release
        assets = [a for a in (release.get("assets") or []) if isinstance(a, dict)]
        has_real_asset = any(not _is_noise_asset(a.get("name") or "") for a in assets)
        if not has_real_asset:
            continue
        out.append(item)
    return out


def normalize_platform(value: str = "") -> str:
    """平台名归一化（空 → 按运行环境猜，猜不出用 windows）"""
    text = str(value or "").strip().lower()
    if not text:
        if sys.platform.startswith("win"):
            text = "windows"
        elif sys.platform == "darwin":
            text = "macos"
        elif sys.platform.startswith("linux"):
            text = "linux"
        else:
            text = DEFAULT_PLATFORM
    return _PLATFORM_ALIASES.get(text, text if text in _PLATFORM_ALIASES.values()
                                 else DEFAULT_PLATFORM)


def normalize_arch(value: str = "") -> str:
    """架构名归一化（空 → 按 machine() 猜，猜不出用 x64）"""
    text = str(value or "").strip().lower()
    if not text:
        try:
            import platform as _platform
            machine = str(_platform.machine() or "").lower()
        except Exception:
            machine = ""
        text = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64",
                "aarch64": "arm64", "i386": "x86", "i686": "x86"}.get(machine, "")
    return _ARCH_ALIASES.get(text, text if text in _ARCH_ALIASES.values() else DEFAULT_ARCH)


# ---- 关键词表（全是小写，对 asset.name.lower() 做 search）----
_PLATFORM_KEYWORDS = {
    "windows": (r"(?:^|[^a-z])win(?:dows|32|64)?(?:[^a-z]|$)", r"\.exe$", r"\.msi$"),
    # 注意 "darwin" 里含 "win"，所以上面必须用"前后不能是字母"的边界写法
    "linux": (r"linux", r"ubuntu", r"debian", r"fedora", r"centos", r"appimage",
              r"\.deb$", r"\.rpm$", r"\.flatpak$"),
    "macos": (r"macos", r"mac[ _-]?os[ _-]?x?", r"osx", r"darwin", r"apple",
              r"\.dmg$", r"\.pkg$"),
}
_ARCH_KEYWORDS = {
    "x64": (r"x64", r"x86[_-]64", r"amd64", r"win64", r"64[ _-]?bit"),
    "arm64": (r"arm64", r"aarch64", r"armv8", r"arm[ _-]?64"),
    # ⚠️ x86 必须排除 x86_64：`x86(?![-_]?64)` 保证 "x86_64" 不算 32 位
    "x86": (r"(?:^|[^a-z0-9])x86(?![-_]?64)(?:[^a-z0-9]|$)", r"i[3-6]86", r"win32",
            r"32[ _-]?bit"),
}
# 扩展名：强信号（安装包）
_INSTALLER_EXTS = (".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".appimage", ".msix")
# 扩展名：压缩包（可用但不是最优）
_ARCHIVE_EXTS = (".zip", ".7z", ".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".rar")
# 不同平台的"专有"扩展名：请求 A 平台时出现 B 平台的专有包 → 强烈扣分
_PLATFORM_EXTS = {
    "windows": (".exe", ".msi", ".msix"),
    "linux": (".deb", ".rpm", ".appimage", ".flatpak"),
    "macos": (".dmg", ".pkg"),
}
# 一律排除：源码包 / 校验 / 签名 / 调试符号 / SBOM / 元数据
_REJECT_PATTERNS = (
    r"source[ _-]?code", r"(?:^|[^a-z])sources?(?:[^a-z]|$)", r"\.src\.", r"\.tar\.(?:gz|bz2|xz)$.*src",
    r"sha(?:1|256|512)?sums?", r"checksums?", r"(?:^|[^a-z])md5(?:[^a-z]|$)",
    r"\.(?:sha1|sha256|sha512|md5|asc|sig|minisig|pem|sbom|spdx|json|txt|ya?ml)$",
    r"symbols?", r"\.pdb$", r"\.debug$", r"\.dsym$", r"\.blockmap$", r"\.torrent$",
)


def _match_any(name: str, patterns) -> bool:
    return any(re.search(pattern, name) for pattern in patterns)


def score_asset(asset_name: str, platform: str = DEFAULT_PLATFORM,
                arch: str = DEFAULT_ARCH) -> int:
    """给一个 asset 文件名打分（分越高越"就是它"）；被排除的返回 -999
    加分项（智能关键词匹配）：
        · 平台关键词命中 +40；明确是别的平台 -60
        · 架构命中 +15；架构明确不符 -10（x86 请求遇到 x64 包时尤其重要）
        · 平台专有安装包扩展名 +25（通用压缩包 +6）
    扣分/排除项：源码包、sha/asc/sig/symbols/debug/sbom、元数据文件 → -999
    """
    name = str(asset_name or "").strip().lower()
    if not name:
        return -999
    for pattern in _REJECT_PATTERNS:
        if re.search(pattern, name):
            return -999

    score = 0
    # ---- 平台 ----
    matched_platform = ""
    for candidate in ("windows", "linux", "macos"):
        if _match_any(name, _PLATFORM_KEYWORDS[candidate]):
            matched_platform = candidate
            break
    if matched_platform == platform:
        score += 40
    elif matched_platform:
        score -= 60
    # ---- 架构 ----
    matched_arch = ""
    for candidate in ("arm64", "x64", "x86"):
        if _match_any(name, _ARCH_KEYWORDS[candidate]):
            matched_arch = candidate
            break
    if matched_arch == arch:
        score += 15
    elif matched_arch:
        score -= 10
    # ---- 扩展名 ----
    if name.endswith(_INSTALLER_EXTS):
        platform_exts = _PLATFORM_EXTS.get(platform, ())
        if name.endswith(platform_exts):
            score += 25
        else:
            score -= 50                     # 别的平台的安装包
    elif name.endswith(_ARCHIVE_EXTS):
        score += 6                          # 压缩包能用但不是首选
    elif name.endswith((".exe.json", ".sig", ".asc")):
        score -= 80
    # 名字里带 "portable"/"setup" 的微调：安装包优先（setup/installer > portable）
    if re.search(r"(?:^|[^a-z])(setup|installer|install|full)(?:[^a-z]|$)", name):
        score += 6
    return score


def rank_assets(assets, platform: str = DEFAULT_PLATFORM,
                arch: str = DEFAULT_ARCH) -> list:
    """给一组 asset 打分并排序（同分：大的优先，再按名字保证稳定）"""
    scored = []
    for asset in (assets or []):
        if not isinstance(asset, dict):
            continue
        score = score_asset(asset.get("name"), platform, arch)
        if score <= 0:
            continue
        item = dict(asset)
        item["score"] = score
        scored.append(item)
    scored.sort(key=lambda item: (-int(item.get("score") or 0),
                                  -int(item.get("size") or 0),
                                  str(item.get("name") or "")))
    return scored


# ==========================================================================
# 五、下载管理器
# ==========================================================================
def system_download_dir() -> str:
    """系统下载文件夹：`<用户主目录>/Downloads`（Windows 上是下载）
    ⚠️ 默认目录**直接**落在系统下载文件夹下，不再自动套一层 `Downloads/ToolsGCP`
       子目录（历史上套过，后来明确去掉，别加回来）。
    """
    try:
        home = os.path.expanduser("~")
    except Exception:
        home = ""
    if not home or home == "~":
        home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or os.getcwd()
    return os.path.join(home, "Downloads")


def default_download_dir() -> str:
    """默认下载目录 = 系统下载文件夹（不套自动生成的 ToolsGCP 子目录）"""
    return system_download_dir()


_BAD_FILENAME_RE = re.compile(r'[<>:"|?*\x00-\x1f]')


def safe_filename(name: str, fallback: str = "download.bin") -> str:
    """把外部给的文件名洗成安全的**单层文件名**（不允许路径穿越/非法字符）"""
    raw = str(name or "").strip().replace("\\", "/")
    raw = raw.split("?", 1)[0].split("#", 1)[0]
    raw = os.path.basename(raw)
    raw = _BAD_FILENAME_RE.sub("_", raw)
    raw = raw.strip(" .")
    if not raw or raw in (".", ".."):
        raw = fallback
    if len(raw) > 150:
        root, ext = os.path.splitext(raw)
        raw = root[:150 - len(ext)] + ext
    return raw


def filename_from_url(url: str, fallback: str = "download.bin") -> str:
    """从下载地址里猜文件名（GitHub 的 `/releases/download/<tag>/<file>` 就是最后一个片段）"""
    try:
        path = urllib.parse.urlsplit(str(url or "")).path
    except Exception:
        path = str(url or "")
    candidate = urllib.parse.unquote(os.path.basename(path.rstrip("/")))
    return safe_filename(candidate, fallback)


def unique_path(directory: str, filename: str) -> str:
    """同名文件已存在时加 ` (1)`、` (2)`…（需求：同名加 (1)，绝不覆盖用户已有文件）"""
    path = os.path.join(directory, filename)
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(filename)
    index = 1
    while index < 10000:
        candidate = os.path.join(directory, f"{root} ({index}){ext}")
        if not os.path.exists(candidate):
            return candidate
        index += 1
    return os.path.join(directory, f"{root} ({int(_now())}){ext}")


def _open_path(path: str) -> bool:
    """用系统默认程序打开一个文件（测试里会被替换掉，避免真弹窗口）"""
    try:
        if sys.platform == "win32":
            os.startfile(path)                       # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


def open_folder(path: str, select_file: str = "") -> bool:
    """打开一个目录（Windows 上带 select_file 时在资源管理器里选中它）"""
    try:
        if sys.platform == "win32":
            if select_file and os.path.isfile(select_file):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(select_file)])
            else:
                os.startfile(path)                   # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


class _Canceled(Exception):
    """用户取消（内部信号，不外抛）"""


class DownloadDomain:
    """`api.downloader.*`：Releases 浏览 / 智能选包 / 下载管理器"""

    def __init__(self, shell):
        self._shell = shell
        self._lock = threading.RLock()
        self._items = {}                 # id -> 记录 dict（保持插入顺序，list() 按它出）
        self._seq = 0

    # ---------- 内部小工具 ----------
    @property
    def _settings(self):
        return getattr(self._shell, "settings_manager", None)

    def _mirrors(self) -> list:
        return _mirror_order(self._settings)

    # ---------- 用户设置（多线程 / 重试 / 保存位置 / Releases 来源）----------
    def _setting(self, key: str, default=""):
        """从 settings_manager 读一个设置值（读不到就返回默认值）"""
        manager = self._settings
        if manager is None:
            return default
        try:
            data = getattr(manager, "settings", None)
            if not isinstance(data, dict):
                return default
            value = data.get(key, default)
            return default if value is None else value
        except Exception:
            return default

    def _int_setting(self, key: str, default: int, low: int, high: int) -> int:
        """读一个 int 设置并夹到 [low, high]（配置被手工改坏时不会把下载搞崩）"""
        try:
            value = int(self._setting(key, default))
        except (TypeError, ValueError):
            value = default
        return max(low, min(high, value))

    def download_threads(self) -> int:
        """多线程下载并发数（用户设置，默认 100）"""
        return self._int_setting("download_threads", DEFAULT_DOWNLOAD_THREADS,
                                 1, MAX_DOWNLOAD_THREADS)

    def download_retry_count(self) -> int:
        """失败重试次数（用户设置，默认 5）"""
        return self._int_setting("download_retry_count", DEFAULT_DOWNLOAD_RETRY,
                                 1, MAX_DOWNLOAD_RETRY)

    def save_dir(self) -> str:
        """下载保存位置（用户设置；空 = 系统下载文件夹）"""
        raw = str(self._setting("download_save_dir", "") or "").strip()
        if not raw:
            return default_download_dir()
        try:
            return os.path.abspath(os.path.expanduser(raw))
        except Exception:
            return default_download_dir()

    def _releases_source(self, source: str = "") -> str:
        """Releases 来源：显式参数优先，否则用用户设置（默认 official）"""
        text = str(source or "").strip().lower()
        if text in (RELEASES_SOURCE_OFFICIAL, RELEASES_SOURCE_ALL):
            return text
        setting = str(self._setting("releases_source", RELEASES_SOURCE_OFFICIAL) or "").strip().lower()
        return setting if setting in (RELEASES_SOURCE_OFFICIAL, RELEASES_SOURCE_ALL) \
            else RELEASES_SOURCE_OFFICIAL

    def _can_push(self) -> bool:
        """退出闸门：WebView2 比主窗口先销毁，退出后调前端必崩（AGENTS 第 8 条）"""
        return not bool(getattr(self._shell, "_teardown_started", False))

    def _push(self, item: dict, status: str):
        """推一条 download.progress（含节流；调用方负责"要不要推"）"""
        if not self._can_push():
            return
        # ⚠️ 幽灵防护：记录已经被 remove()/clear_finished() 从 _items 里删掉了，
        #    但下载线程要到下一个检查点才发现 cancel —— 这 ≤1 秒的窗口里它还会推
        #    几条进度。前端 mergeDownloadItem 找不到该 id 会**凭空新建一条**，
        #    表现为"点✕删除后任务消失一瞬又回来，再点弹 NOT_FOUND，循环往复"。
        #    self._lock 是 RLock（同线程可重入），持锁调用方也安全。
        with self._lock:
            if self._items.get(str(item.get("id") or "")) is not item:
                # 记录都不在了，这条线程没有继续跑的意义：顺手让它停
                item.setdefault("cancel", threading.Event()).set()
                return
        payload = {
            "id": item["id"], "status": status,
            "received": int(item.get("received") or 0),
            "total": int(item.get("total") or 0),
            "percent": round(float(item.get("percent") or 0.0), 2),
            "speed": round(float(item.get("speed") or 0.0), 1),
            "eta": (round(float(item["eta"]), 1)
                    if isinstance(item.get("eta"), (int, float)) else None),
            "name": item.get("name") or "",
            "path": item.get("path") or "",
            # ⚠️ url / dir 也要推给前端 —— 前端要靠它们显示/复制下载链接
            "url": item.get("url") or "",
            "dir": item.get("dir") or "",
            # ⚠️ 完成/取消/失败的时刻也要推给前端 ——
            #    前端要显示文件名后面的下载时间（2026/10/30），
            #    而进度事件是**唯一**能通知前端"这条任务结束了"的时机
            #    （list() 虽然也带 finished_at，但轮询有 1.2s 延迟）。
            "finished_at": float(item.get("finished_at") or 0.0),
            "error": item.get("error") or "",
            "source": item.get("source") or "",
        }
        try:
            self._shell.push_event("download.progress", payload)
        except Exception as exc:                     # noqa: BLE001
            _log("warn", "下载", "download", f"推送下载进度失败: {exc}")

    def _new_id(self) -> str:
        with self._lock:
            self._seq += 1
            return f"dl{self._seq}"

    def _snapshot(self, item: dict) -> dict:
        """给 list()/start() 用的 JSON 安全副本（不带 Event / 线程对象）"""
        keys = ("id", "url", "name", "dir", "path", "status", "received", "total",
                "percent", "speed", "eta", "error", "source", "expected_size",
                "created_at", "started_at", "finished_at", "used_url")
        data = {key: item.get(key) for key in keys}
        for key in ("percent", "speed"):
            data[key] = round(float(data.get(key) or 0.0), 2)
        if isinstance(data.get("eta"), (int, float)):
            data["eta"] = round(float(data["eta"]), 1)
        return data

    def _running(self) -> int:
        with self._lock:
            return sum(1 for item in self._items.values()
                       if item.get("status") == "downloading")

    # ==================================================================
    # Releases
    # ==================================================================
    def releases(self, github_url: str = "", page: int = 1, per_page: int = 30,
                 source: str = ""):
        """拉某个仓库的 release 列表（含 prerelease、不含 draft；10 分钟内存缓存）
        ⚠️ `source` 参数（`official` 官方 / `all` 全部）。
           `source` 为空时用**用户设置**里的 `releases_source`（默认 official）。
           缓存只缓存 GitHub 的**原始**列表（两种 source 共用同一份缓存），
           过滤在返回前做 —— 切下拉框不用重新请求 GitHub。
        ⚠️ 返回值带 `raw_count`（筛选**前**的原始条数）和 `has_more`
           （还有没有下一页）。
           ⚠️ 为什么必须有：如果前端用这一页返回几条 >= perPage判断还有没有下一页，
              **筛选之后**条数会变少（官方模式过滤掉了没产物的 release）
              → hasMore 误判成 false →加载更多按钮直接消失、用户看不到后面的版本。
              后端知道原始条数，所以由它来判。
        """
        try:
            repo = parse_repo(github_url)
            if not repo:
                return _fail(ERR_BAD_URL, repo="", releases=[], page=1, per_page=30,
                             count=0, cached=False, source=self._releases_source(source),
                             raw_count=0, has_more=False)
            try:
                page = max(1, int(page or 1))
                per_page = min(100, max(1, int(per_page or 30)))
            except (TypeError, ValueError):
                page, per_page = 1, 30

            want_source = self._releases_source(source)
            cache_key = (repo.lower(), page, per_page)
            with _CACHE_LOCK:
                cached = _RELEASES_CACHE.get(cache_key)
            if cached and cached[0] > _now():
                raw_releases = cached[1]
                shown = filter_releases_for_source(raw_releases, want_source)
                return _ok(repo=repo, releases=shown, page=page, per_page=per_page,
                           count=len(shown), cached=True, source=want_source,
                           raw_count=len(raw_releases),
                           has_more=len(raw_releases) >= per_page)

            api_url = (f"{API_BASE}/repos/{repo}/releases"
                       f"?per_page={per_page}&page={page}")
            urls = build_candidate_urls(api_url, self._mirrors())
            data, used_url = _request_json(urls)
            if isinstance(data, dict):
                message = str(data.get("message") or "")
                code = (ERR_RATE_LIMITED if "rate limit" in message.lower()
                        else ERR_BAD_RESPONSE)
                raise DownloadError(code, message or "返回不是数组")
            if not isinstance(data, list):
                raise DownloadError(ERR_BAD_RESPONSE,
                                    f"返回类型异常: {type(data).__name__}")

            raw_releases = []
            for raw in data:
                if not isinstance(raw, dict) or raw.get("draft"):
                    continue                      # 草稿用户看不到，别列出来
                item = normalize_release(raw)
                if item["tag"]:
                    raw_releases.append(item)
            shown = filter_releases_for_source(raw_releases, want_source)
            _log("op", "下载", "releases",
                 f"拉取 {repo} 的 release 列表成功：{len(shown)} 条"
                 f"（原始 {len(raw_releases)} 条 / 来源 {want_source}，{used_url}）")
            with _CACHE_LOCK:
                _RELEASES_CACHE[cache_key] = (_now() + RELEASES_CACHE_TTL, raw_releases)
            return _ok(repo=repo, releases=shown, page=page, per_page=per_page,
                       count=len(shown), cached=False, source=want_source,
                       raw_count=len(raw_releases),
                       has_more=len(raw_releases) >= per_page)
        except DownloadError as exc:
            _log("warn", "下载", "releases",
                 f"拉取 release 列表失败（{exc.code}: {exc.detail}）")
            return _fail(exc.code, repo=parse_repo(github_url), releases=[],
                         page=page, per_page=per_page, count=0, cached=False,
                         source=self._releases_source(source))
        except Exception as exc:                      # noqa: BLE001
            _log("err", "下载", "releases", f"拉取 release 列表异常: {exc}")
            return _fail(ERR_BAD_RESPONSE, repo="", releases=[], page=page,
                         per_page=per_page, count=0, cached=False)

    # ==================================================================
    # 智能选包
    # ==================================================================
    def resolve_asset(self, github_url: str = "", platform: str = "", arch: str = ""):
        """在最新 release 里挑最匹配当前系统/架构的安装包（找不到 → NO_MATCH）"""
        try:
            platform = normalize_platform(platform)
            arch = normalize_arch(arch)
            listing = self.releases(github_url)
            if not listing.get("ok"):
                return _fail(listing.get("error") or ERR_BAD_RESPONSE,
                             repo=listing.get("repo") or "",
                             platform=platform, arch=arch,
                             asset=None, candidates=[], release=None)
            releases = listing.get("releases") or []
            if not releases:
                return _fail(ERR_NO_RELEASE, repo=listing.get("repo") or "",
                             platform=platform, arch=arch,
                             asset=None, candidates=[], release=None)
            # 正式版优先、同类型里新的优先；正式版没有可用的再退到预发布
            ordered = sorted(releases, key=lambda rel: (bool(rel.get("prerelease")),
                                                        _negative_time(rel)))
            all_candidates = []
            for release in ordered:
                ranked = rank_assets(release.get("assets"), platform, arch)
                all_candidates.extend(ranked)
                if not ranked:
                    continue
                best = ranked[0]
                _log("op", "下载", "resolve",
                     f"{listing.get('repo')} 选中 {best.get('name')}"
                     f"（score={best.get('score')}, 平台={platform}, 架构={arch}）")
                return _ok(repo=listing.get("repo") or "", platform=platform, arch=arch,
                           asset={"name": best.get("name"),
                                  "size": best.get("size") or 0,
                                  "download_url": best.get("download_url"),
                                  "score": best.get("score"),
                                  "content_type": best.get("content_type") or ""},
                           candidates=[{"name": item.get("name"),
                                        "size": item.get("size") or 0,
                                        "score": item.get("score"),
                                        "content_type": item.get("content_type") or ""}
                                       for item in all_candidates[:MAX_CANDIDATES]],
                           release={"tag": release.get("tag"),
                                    "name": release.get("name"),
                                    "prerelease": release.get("prerelease"),
                                    "published_at": release.get("published_at")})
            _log("warn", "下载", "resolve",
                 f"{listing.get('repo')} 没有匹配 {platform}/{arch} 的安装包（候选 {len(all_candidates)} 个）")
            return _fail(ERR_NO_MATCH, repo=listing.get("repo") or "",
                         platform=platform, arch=arch, asset=None,
                         candidates=[{"name": item.get("name"),
                                      "size": item.get("size") or 0,
                                      "score": item.get("score"),
                                      "content_type": item.get("content_type") or ""}
                                     for item in all_candidates[:MAX_CANDIDATES]],
                         release=None)
        except Exception as exc:                      # noqa: BLE001
            _log("err", "下载", "resolve", f"智能选包异常: {exc}")
            return _fail(ERR_BAD_RESPONSE, repo="", platform=platform, arch=arch,
                         asset=None, candidates=[], release=None)

    # ==================================================================
    # 下载管理器
    # ==================================================================
    def _prepare_item(self, url, filename, dir, expected_size, source) -> dict:
        """校验参数、定目录、定文件名（同名加 (1)）、建记录；失败抛 DownloadError"""
        target_url = str(url or "").strip()
        if not target_url:
            raise DownloadError(ERR_BAD_URL, "url 为空")
        scheme = urllib.parse.urlsplit(target_url).scheme.lower()
        if scheme not in ("http", "https"):
            raise DownloadError(ERR_BAD_URL, f"不是 http(s) 地址: {scheme or '(空)'}")

        # 目录优先级 = 显式传入 > 用户设置下载保存位置> 系统下载文件夹。
        # ⚠️ 兜底 default 就是系统下载文件夹本身
        #    （不套自动生成的 ToolsGCP 子目录）。
        directory = str(dir or "").strip() or self.save_dir()
        directory = os.path.abspath(os.path.expanduser(directory))
        try:
            os.makedirs(directory, exist_ok=True)
        except Exception as exc:                      # noqa: BLE001
            raise DownloadError(ERR_DISK_ERROR, f"创建下载目录失败: {exc}")

        name = safe_filename(filename) if str(filename or "").strip() else \
            filename_from_url(target_url)
        with self._lock:
            path = unique_path(directory, name)
            name = os.path.basename(path)
            item = {
                "id": self._new_id(),
                "url": target_url,
                "used_url": "",
                "name": name,
                "dir": directory,
                "path": path,
                "status": "downloading",
                "received": 0,
                "total": 0,
                "percent": 0.0,
                "speed": 0.0,
                "eta": None,
                "error": "",
                "source": str(source or ""),
                "expected_size": int(expected_size or 0),
                "created_at": _now(),
                "started_at": 0.0,
                "finished_at": 0.0,
                # 分段续传状态（seg_offsets = 每段写到哪；contiguous = 从开头
                # 连续写完的前缀长度，单线程换源续传用它）。不进 _snapshot。
                "seg_offsets": {},
                "contiguous": 0,
                "cancel": threading.Event(),
                "thread": None,
            }
            self._items[item["id"]] = item
        return item

    def _start_thread(self, item: dict) -> dict:
        thread = threading.Thread(target=self._run, args=(item,),
                                  name=f"ToolsGCP-download-{item['id']}", daemon=True)
        item["thread"] = thread
        thread.start()
        return _ok(started=True, id=item["id"], name=item["name"], path=item["path"],
                   dir=item["dir"], url=item["url"], total=0)

    def start(self, url: str = "", filename: str = "", dir: str = "",
              expected_size: int = 0, source: str = ""):
        """开始下载（**立即返回**，进度走 download.progress 事件）"""
        try:
            item = self._prepare_item(url, filename, dir, expected_size, source)
        except DownloadError as exc:
            _log("warn", "下载", "start", f"下载参数无效（{exc.code}: {exc.detail}）")
            return _fail(exc.code, started=False)
        except Exception as exc:                      # noqa: BLE001
            _log("err", "下载", "start", f"启动下载异常: {exc}")
            return _fail(ERR_BAD_RESPONSE, started=False)
        _log("op", "下载", "start",
             f"开始下载 {item['name']} → {item['path']}（源: {item['source'] or url}）")
        return self._start_thread(item)

    def start_wait(self, url: str = "", filename: str = "", dir: str = "",
                   expected_size: int = 0, source: str = "", timeout: float = 0):
        """同步下载（部署页老流程 `await start()` 保持"下完再返回"语义时用）
        `timeout>0` 时最多等这么久，超时返回 `{ok:false, error:"TIMEOUT"}`，
        但**下载线程继续跑**（用户还能在下载页看到进度）。
        """
        try:
            item = self._prepare_item(url, filename, dir, expected_size, source)
        except DownloadError as exc:
            return _fail(exc.code, started=False)
        except Exception as exc:                      # noqa: BLE001
            return _fail(ERR_BAD_RESPONSE, started=False)
        self._start_thread(item)
        thread = item.get("thread")
        try:
            if thread is not None:
                thread.join(timeout if float(timeout or 0) > 0 else None)
        except Exception:
            pass
        if item.get("status") == "downloading":
            return _fail(ERR_TIMEOUT, id=item["id"], status=item["status"],
                         path=item["path"], size=int(item.get("received") or 0))
        ok = item.get("status") == "done"
        payload = dict(id=item["id"], status=item["status"], path=item["path"],
                       size=int(item.get("received") or 0), name=item["name"],
                       error=item.get("error") or "")
        return _ok(**payload) if ok else _fail(item.get("error") or ERR_CANCELED, **payload)

    def _open_download(self, item: dict, url: str, headers: dict = None):
        """**可取消**的下载连接：连之前先看取消标记，连接超时用短超时 + 有限重试
        为什么不让 `_download_from` 直接 urlopen：
            · urlopen 的 timeout 原本是 TIMEOUT_S(20s) —— 服务器连不上时，
              用户点了取消也得干等 20 秒才报错（"取消点好几次、过好一会才停"的现象）。
              下载连接用 DL_CONNECT_TIMEOUT_S(3s)，连不上就换下一个镜像源。
            · 更要紧的是：**连接中**是没法用 socket 读超时兜底的
              （那时 socket 还没建好），所以每发起一次连接前必须先看取消标记。
        ⚠️ HTTPError 原样抛出：404/403 是"这个源不行，换源"的信号，
           被吞掉的话调用方会以为只是网络抖动，换源逻辑就废了。
        """
        hdrs = {"User-Agent": USER_AGENT}
        hdrs.update(headers or {})
        last_exc = None
        for attempt in range(3):
            # ⚠️ 每次尝试连接**前**都看一次取消标记：用户点取消后不该再发起新连接
            if item["cancel"].is_set():
                raise _Canceled()
            try:
                request = urllib.request.Request(url, headers=hdrs)
                return urllib.request.urlopen(request, timeout=DL_CONNECT_TIMEOUT_S)
            except (socket.timeout, TimeoutError) as exc:
                # 超时：先看是不是被取消了（是就立刻停，别再重试）
                if item["cancel"].is_set():
                    raise _Canceled()
                last_exc = exc
                continue
        if last_exc is not None:
            raise last_exc
        raise DownloadError(ERR_NETWORK, f"无法连接下载源：{url}")

    def _probe_range(self, item: dict, url: str):
        """探测服务器是否支持 Range 分段下载（多线程下载的前提）
        返回 `(支持, 文件总大小)`：
        · 发一个 `Range: bytes=0-0` 的 GET，服务器回 **206** 就说明支持分段；
        · `Content-Range: bytes 0-0/12345` 里的总长度就是文件大小。
        ⚠️ 探测失败**不抛异常** —— 返回 (False, 0)，调用方退回单线程下载。
        ⚠️ 探测会真的下载 1 个字节（Range 的语义就是这样），代价可忽略。
        ⚠️ 探测也走 `_open_download` —— 探测阶段也要能立刻响应取消，
           不然用户点取消后还要等本次连接的超时跑完。
        """
        try:
            response = self._open_download(item, url, headers={"Range": "bytes=0-0"})
            try:
                status = getattr(response, "status", None) or response.getcode()
                content_range = str(response.headers.get("Content-Range") or "")
                total = 0
                if "/" in content_range:
                    tail = content_range.rsplit("/", 1)[-1].strip()
                    if tail.isdigit():
                        total = int(tail)
                return (int(status) == 206, total)
            finally:
                try:
                    response.close()
                except Exception:
                    pass
        except _Canceled:
            raise
        except Exception:
            return (False, 0)

    def _download_from_multithreaded(self, item: dict, url: str, total: int, threads: int):
        """多线程分段下载（HTTP Range，线程数默认 100）
        · 把文件切成 `threads` 段，每段一个线程，各自从自己那一段读；
        · 全部线程**写同一个文件**的**不同字节区间**（互不重叠），所以不��要锁住写操作；
          只有"累计进度"用锁保护（`item["received"]`）。
        · 任何一段失败 → 整个下载失败（调用方按重试策略重来），
          宁可重下也不能留一个"缺段"的坏文件给用户。
        · ⚠️ 服务器不支持 Range（206）→ 调用方已经退回单线程，这里不会走到。
        """
        threads = max(1, min(int(threads or 1), MAX_DOWNLOAD_THREADS))
        if total <= 0 or threads <= 1:
            return self._download_from(item, url)

        # ---- 切段 ----
        seg_size = max(1, total // threads)
        segments = []
        start = 0
        while start < total and len(segments) < threads:
            end = total - 1 if len(segments) == threads - 1 else min(total - 1, start + seg_size - 1)
            if end < start:
                break
            segments.append((start, end))
            start = end + 1

        item["total"] = total
        item["used_url"] = url
        item["started_at"] = item["started_at"] or _now()
        item["threads"] = len(segments)

        # ⚠️ 分段续传：预分配**只在文件不存在/尺寸不对时做**。
        #    换源重试时文件已经下了一部分 —— truncate 会把已下的字节全清了再从零下，
        #    进度条直接跳回 0%（"跑一半突然回到 0"的现象）。
        #    尺寸对不上（比如新源的 total 和旧的不一样）才重开文件并清空段偏移。
        offsets = item.setdefault("seg_offsets", {})
        try:
            size = os.path.getsize(item["path"]) if os.path.isfile(item["path"]) else -1
        except OSError:
            size = -1
        if size != total:
            # ⚠️ 文件不存在 / 尺寸不对才重建，且**尽量保住开头连续写完的前缀**。
            #    "wb" 会把文件清成 0 —— 此前单线程已经下好的前缀会白白丢掉，bug 就这么来。
            #    前缀有效 = 文件大小恰好等于连续前缀（单线程顺序写的半成品）。
            prefix = int(item.get("contiguous") or 0)
            keep = prefix if (0 < prefix < total and size == prefix) else 0
            if keep:
                with open(item["path"], "r+b") as stream:
                    stream.truncate(total)          # 撑到全尺寸，前 keep 字节原样保留
            else:
                with open(item["path"], "wb") as stream:
                    stream.truncate(total)          # 没有可信前缀：全新空文件
                offsets.clear()
            # 按"前缀盖到哪个段"重建各段偏移（段边界由同一个 total/threads 决定，稳定）
            if keep:
                for seg_start, seg_end in segments:
                    if seg_start < keep:
                        offsets[seg_start] = min(keep, seg_end + 1)
        # 续传起点 = 各段已经写进去的量之和（received 从真实进度起步，不回 0）
        # ⚠️ contiguous = 从文件开头**连续**写完的前缀长度。
        #    多线程文件是预分配的空洞文件（大小=total），单线程续传不能拿
        #    received 当文件大小校验 —— 只有"前 contiguous 字节确实写完"
        #    才能安全地 Range: bytes={contiguous}- 续传。
        already = 0
        contiguous = 0
        for seg_start, seg_end in segments:
            done = int(offsets.get(seg_start) or seg_start)
            if done > seg_start:
                already += min(done, seg_end + 1) - seg_start
            # 段是按顺序排的：只有"从 contiguous 开始的段"写完了，前缀才能往前推
            if seg_start == contiguous and done >= seg_end + 1:
                contiguous = done
        item["contiguous"] = contiguous
        item["received"] = already
        item["percent"] = (already * 100.0 / total) if total else 0.0

        progress_lock = threading.Lock()
        errors = []
        last_push = [0.0]
        # ⚠️ 取消是**正常控制流**（用户点了取消），不是错误。
        #    如果 worker 里 `except _Canceled: raise` 把异常抛到线程顶层，
        #    threading 就会给每个分段线程打印一屏 traceback
        #    （Exception in thread ToolsGCP-dl-dl1-...: _Canceled）。
        #    多线程分段下载有几十上百个线程 → 一次取消刷几十屏。
        #    所以：worker 自己吞掉 _Canceled，只置一个标记；
        #    取消的事实由 item["cancel"] 表达，外层统一判断（见下面 join 之后）。
        canceled = [False]

        def worker(seg_start: int, seg_end: int):
            # ⚠️ 线程里的异常**不会**自动冒泡到主线程，必须自己收进 errors，
            #    否则分段失败会被静默吞掉，最后只看到"下载不完整"这种含糊的错。
            try:
                self._download_segment(item, url, seg_start, seg_end, total,
                                       progress_lock, last_push)
            except _Canceled:
                # 正常控制流：不重抛（重抛会被 threading 打印成异常刷屏）
                canceled[0] = True
            except Exception as exc:              # noqa: BLE001
                errors.append(exc if isinstance(exc, DownloadError)
                              else DownloadError(ERR_NETWORK, _friendly(exc)))

        workers = []
        for seg_start, seg_end in segments:
            thread = threading.Thread(target=worker, args=(seg_start, seg_end),
                                      name=f"ToolsGCP-dl-{item['id']}-{seg_start}",
                                      daemon=True)
            workers.append(thread)
            thread.start()
        # 等所有分段线程结束
        for thread in workers:
            thread.join()
        # ⚠️ 取消优先于错误：用户点了取消时，"下载不完整"这种次生错误不该盖掉取消语义
        if canceled[0] or item["cancel"].is_set():
            raise _Canceled()
        if errors:
            raise errors[0]
        received = int(item.get("received") or 0)
        if received < total:
            raise DownloadError(ERR_SIZE_MISMATCH,
                                f"分段下载不完整：收到 {received}，应为 {total}")
        return received

    def _download_segment(self, item: dict, url: str, seg_start: int, seg_end: int,
                          total: int, progress_lock, last_push):
        """下载文件的一个字节区间（写进最终文件的对应位置）
        ⚠️ 分段续传：每段的"已写到哪"记在 item["seg_offsets"][seg_start]。
           换源/重试时从该偏移继续（请求头带 Range: bytes={resume}-{seg_end}），
           进度条不再"跑一半突然回 0%"。服务器不支持 Range（回 200）时退回本段起点。
        """
        offsets = item.setdefault("seg_offsets", {})
        with progress_lock:
            resume_from = int(offsets.get(seg_start) or seg_start)
        if resume_from > seg_end:
            return                                   # 这一段早就下完了，跳过
        # ⚠️ 走 _open_download —— 连接阶段也能立刻响应取消，且连接超时只有 3 秒
        response = self._open_download(
            item, url, headers={"Range": f"bytes={resume_from}-{seg_end}"})
        # ⚠️ 分段请求必须拿到 206。服务器回 200 = 无视 Range 给了**整个文件**，
        #    从任何偏移往文件里写都会错位（把别人的段写进这一段的位置）。
        #    探测（_probe_range）已经确认过这个 URL 支持 Range，走到这里还回 200
        #    属于异常源 —— 直接报错让 _run 换下一个源，绝不硬写坏文件。
        try:
            status_code = int(getattr(response, "status", None) or response.getcode())
        except Exception:
            status_code = 200
        if status_code != 206:
            try:
                response.close()
            except Exception:
                pass
            raise DownloadError(ERR_NETWORK, "服务器不支持分段下载（Range 被忽略）")
        # ⚠️ 同 _download_from —— 读超时调小，取消能立刻生效
        try:
            _set_read_timeout(response, READ_TIMEOUT_S)
        except Exception:
            pass
        try:
            with open(item["path"], "r+b") as stream:
                stream.seek(resume_from)
                while True:
                    if item["cancel"].is_set():
                        raise _Canceled()
                    if not self._can_push():
                        item["cancel"].set()
                        raise _Canceled()
                    # ⚠️ 检查**暂停**标记（暂停时挂起，恢复后继续）。
                    self._wait_if_paused(item)
                    try:
                        # ⚠️ 小块读（32KB）—— 暂停/取消的检查粒度提高 8 倍，
                        #    点暂停后的"过冲"从 ~25MB 降到 ~3MB。
                        chunk = response.read(READ_CHUNK_SIZE)
                    except socket.timeout:
                        if item["cancel"].is_set():
                            raise _Canceled()
                        continue
                    if not chunk:
                        break
                    stream.write(chunk)
                    with progress_lock:
                        # 记下这一段写到哪了（续传点），换源后从这里接着下
                        offsets[seg_start] = stream.tell()
                        item["received"] = int(item.get("received") or 0) + len(chunk)
                        now = _now()
                        elapsed = max(0.001, now - item["started_at"])
                        item["speed"] = item["received"] / elapsed
                        item["percent"] = (item["received"] * 100.0 / total)
                        item["eta"] = ((total - item["received"]) / item["speed"]
                                       if item["speed"] > 0 else None)
                        if now - last_push[0] >= PROGRESS_INTERVAL_S:
                            last_push[0] = now
                            # ⚠️ 推**当前真实状态**，不要写死 "downloading"。
                            #    若写死，暂停/取消之后下载线程还会推最后几条
                            #    "downloading" 进度 → 前端 mergeDownloadItem 直接
                            #    Object.assign 覆盖 → 界面在下载中和已暂停之间
                            #    **来回跳**，按钮跟着闪，看起来就是"点了没反应"
                            #    （"暂停/继续/取消点击无效"的真正根因）。
                            #    item["status"] 初始就是 "downloading"（_prepare_item），
                            #    正常下载时行为不变；暂停/取消时它已被改成 paused/canceled。
                            self._push(item, item.get("status") or "downloading")
        finally:
            try:
                response.close()
            except Exception:
                pass

    def _download_from(self, item: dict, url: str):
        """从**一个**候选地址流式下载到 item['path']；失败抛异常（由调用方换源）
        ⚠️ 单线程续传：优先按 item["contiguous"]（多线程分段记下的"从开头
           **连续**写完的前缀"）；没有它（纯单线程）时按 received，但要求
           磁盘文件大小**恰好等于** received（多线程的预分配空洞文件不满足，
           不会误把空洞当前缀）。对不上就退回从头覆盖下。换源不再白白从 0 开始。
        """
        resume_from = 0
        try:
            have = int(item.get("received") or 0)
            size = os.path.getsize(item["path"]) if os.path.isfile(item["path"]) else -1
            contiguous = int(item.get("contiguous") or 0)
            if contiguous > 0 and size >= contiguous:
                resume_from = contiguous
            elif have > 0 and size == have:
                resume_from = have
        except OSError:
            resume_from = 0
        # ⚠️ 走 _open_download —— 连接超时 3 秒、连接前先看取消标记
        response = self._open_download(
            item, url,
            headers={"Range": "bytes=%d-" % resume_from} if resume_from else None)
        # ⚠️ 连接成功**立刻**再确认一次取消：别白下一个文件
        #   （连接成功到进入读循环之间有一小段空窗，用户可能正好在这时点取消）
        if item["cancel"].is_set():
            try:
                response.close()
            except Exception:
                pass
            raise _Canceled()
        # ⚠️ 请求了续传但服务器回 200（无视 Range，给整个文件）→ 只能从头下
        if resume_from:
            try:
                code = int(getattr(response, "status", None) or response.getcode())
            except Exception:
                code = 200
            if code != 206:
                try:
                    response.close()
                except Exception:
                    pass
                resume_from = 0
                response = self._open_download(item, url)
        # ⚠️ 把 socket 的**读超时**调到 1 秒 —— urlopen 的 timeout 同时也是
        #   socket 超时，原来 20 秒意味着一个 chunk 卡住时，点取消最多要等 20 秒
        #   才生效（现象："取消按钮点好几次、得过好一会才停"）。
        #   1 秒后：读超时 → 回头检查 cancel/pause → 立刻响应；正常下载不受影响
        #   （socket 超时是"多久没收到数据"，收到就重置）。
        try:
            _set_read_timeout(response, READ_TIMEOUT_S)
        except Exception:
            pass
        try:
            total = item.get("expected_size") or 0
            header_size = response.headers.get("Content-Length")
            if header_size:
                try:
                    body = int(header_size)
                    # ⚠️ 206 的 Content-Length 是**剩余**部分，总量 = 已续 + 剩余
                    if resume_from and not total:
                        total = resume_from + body
                    elif not total:
                        total = body
                except (TypeError, ValueError):
                    pass
            item["total"] = total
            item["used_url"] = url
            item["started_at"] = item["started_at"] or _now()
            received = resume_from
            last_push = 0.0
            if resume_from:
                stream = open(item["path"], "r+b")
                stream.seek(resume_from)
            else:
                stream = open(item["path"], "wb")
            with stream:
                while True:
                    if item["cancel"].is_set():
                        raise _Canceled()
                    if not self._can_push():
                        # 程序正在退出：别再下载了，当作取消（也不推事件）
                        item["cancel"].set()
                        raise _Canceled()
                    # ⚠️ 暂停时挂起（恢复后接着下）
                    self._wait_if_paused(item)
                    # ⚠️ 读超时改成**短超时**（1 秒）——
                    #   之前用 TIMEOUT_S(20s) 读，一个 chunk 卡住时用户点取消
                    #   要等最多 20 秒才生效（现象："取消按钮点好几次、得过好一会才停"）。
                    #   改成 1 秒后：读超时 → 回头看 cancel/pause 标记 → 立刻响应。
                    #   ⚠️ 正常的慢速下载也不会误伤：socket 超时是"多久没收到数据"，
                    #      收到数据就重置，连续 1 秒没数据才算超时。
                    try:
                        # ⚠️ 小块读（32KB）—— 暂停/取消响应粒度提高 8 倍
                        chunk = response.read(READ_CHUNK_SIZE)
                    except socket.timeout:
                        # 没数据：看看是不是被取消了 / 暂停了
                        if item["cancel"].is_set():
                            raise _Canceled()
                        continue
                    if not chunk:
                        break
                    stream.write(chunk)
                    received += len(chunk)
                    now = _now()
                    elapsed = max(0.001, now - item["started_at"])
                    item["received"] = received
                    # 单线程是**顺序写**的 → 连续前缀就是 received
                    item["contiguous"] = received
                    item["speed"] = received / elapsed
                    item["percent"] = (received * 100.0 / total) if total else 0.0
                    item["eta"] = ((total - received) / item["speed"]
                                   if total and item["speed"] > 0 else None)
                    if now - last_push >= PROGRESS_INTERVAL_S:
                        last_push = now
                        # ⚠️ 同 _download_from —— 推真实状态，别写死 "downloading"
                        #    （暂停/取消后写死会把状态覆盖回去，界面来回跳）
                        self._push(item, item.get("status") or "downloading")
            # ⚠️ **提前断流要当错误抛**，不能静默返回短读。
            #    若静默返回：服务器中途掐线 → read 拿到 b'' → 正常 return →
            #    _run 把它当"这个源成功了"跳出换源循环 → 末尾大小校验才炸成 failed。
            #    表现就是"下载失败、重试又回 0"。
            #    短读 = 这个源失败 → _run 的 for 循环换下一个源 →
            #    配合续传（Range），已下的部分原样保留，进度不回 0。
            if total and received != total:
                raise DownloadError(
                    ERR_SIZE_MISMATCH,
                    f"响应提前结束：收到 {received}，应为 {total}")
            return received
        finally:
            try:
                response.close()
            except Exception:
                pass

    def _run(self, item: dict):
        """后台线程主体：候选地址逐个试 → 失败按设置重试 → 校验大小 → 收尾
        ⚠️ 失败重试（次数默认 5、每次间隔 30s、连上则计数回归上限）：
           · 重试次数取用户设置（默认 5），**每次重试间隔 30 秒**；
           · 连上则回归上限= 一旦**连上并收到过数据**，重试计数**重置回上限**
             （长文件下载中途网络抖动能重新获得完整的一轮重试机会，而不是把配额耗光）；
           · 等待用 `cancel.wait(30)` 而不是 `time.sleep(30)` —— 用户点取消能立刻跳出，
             不用干等 30 秒；
           · 用户设置的**配置值不改**（"回归上限"只是这一次下载任务内部的计数）。
        """
        error = ""
        status = "downloading"
        try:
            max_retries = self.download_retry_count()
            retries_left = max_retries
            while True:
                urls = build_candidate_urls(item["url"], self._mirrors())
                last_error = DownloadError(ERR_NETWORK, "没有候选地址")
                connected = False
                for url in urls:
                    if item["cancel"].is_set():
                        raise _Canceled()
                    # ⚠️ **不清零 received/percent**。
                    #    若每次换源都把进度抹回 0，用户会看到"跑一半突然回到 0%"。
                    #    换源 = 续传（多线程按 seg_offsets、单线程按 Range），
                    #    已下到的字节保留，进度单调不回退。
                    try:
                        # 多线程分段下载。
                        # ⚠️ 先探测服务器是否支持 Range（206）；不支持就**自动退回单线程**
                        #    （很多 CDN / 镜像站不支持分段，硬上会拿到错误的内容）。
                        threads = self.download_threads()
                        if threads > 1:
                            supported, probe_total = self._probe_range(item, url)
                            if supported and probe_total > 1:
                                received = self._download_from_multithreaded(
                                    item, url, probe_total, threads)
                                connected = received > 0
                                break
                            _log("info", "下载", "range",
                                 f"{item['name']} 的源不支持分段下载，退回单线程：{url}")
                        received = self._download_from(item, url)
                        connected = received > 0
                        break
                    except _Canceled:
                        raise
                    except DownloadError as exc:
                        last_error = exc
                        # ⚠️ 换下一个源**前不删半成品** —— 删了就等于前功尽弃、
                        #    下一个源只能从 0 开始（就是"进度回 0"的现象）。
                        #    半成品的清理由最终失败收尾时统一做（见下面的 except 分支）。
                    except Exception as exc:              # noqa: BLE001
                        last_error = DownloadError(ERR_NETWORK, f"{_friendly(exc)} @ {url}")
                        _log("warn", "下载", "download",
                             f"{item['name']} 从 {url} 下载失败，换下一个源: {_friendly(exc)}")
                else:
                    # 所有候选地址都失败 → 看还剩几次重试机会
                    if retries_left <= 0:
                        raise last_error
                    retries_left -= 1
                    _log("warn", "下载", "retry",
                         f"{item['name']} 下载失败，{RETRY_INTERVAL_S:.0f}s 后重试"
                         f"（还剩 {retries_left}/{max_retries} 次）：{last_error.code}")
                    # cancel.wait 返回 True = 期间被取消 → 直接退出
                    if item["cancel"].wait(RETRY_INTERVAL_S):
                        raise _Canceled()
                    continue

                # 下载成功：连上过就把重试配额**重置回上限**
                if connected:
                    retries_left = max_retries
                break

            expected = int(item.get("expected_size") or 0)
            total = int(item.get("total") or 0)
            if expected and received != expected:
                self._remove_partial(item)
                raise DownloadError(ERR_SIZE_MISMATCH,
                                    f"大小不符：收到 {received}，应为 {expected}")
            if total and received != total:
                self._remove_partial(item)
                raise DownloadError(ERR_SIZE_MISMATCH,
                                    f"大小不符：收到 {received}，应为 {total}")
            if received <= 0:
                self._remove_partial(item)
                raise DownloadError(ERR_BAD_RESPONSE, "下载到 0 字节")

            item["received"] = received
            item["percent"] = 100.0
            item["status"] = status = "done"
            item["finished_at"] = _now()
            item["error"] = ""
            _log("op", "下载", "done",
                 f"下载完成 {item['name']}（{received} 字节，耗时 "
                 f"{item['finished_at'] - (item['started_at'] or item['finished_at']):.1f}s）→ {item['path']}")
        except _Canceled:
            item["status"] = status = "canceled"
            item["finished_at"] = _now()
            item["error"] = ""
            self._remove_partial(item)
            _log("info", "下载", "cancel", f"下载已取消：{item['name']}")
        except DownloadError as exc:
            item["status"] = status = "failed"
            item["finished_at"] = _now()
            item["error"] = error = exc.code
            # ⚠️ 换源途中保留半成品（续传用），但**彻底失败**时删掉 ——
            #    别在用户的下载目录里留一个永远下不完的坏文件。
            self._remove_partial(item)
            item["seg_offsets"] = {}
            item["contiguous"] = 0
            _log("warn", "下载", "failed",
                 f"下载失败 {item['name']}（{exc.code}: {exc.detail}）")
        except Exception as exc:                      # noqa: BLE001
            item["status"] = status = "failed"
            item["finished_at"] = _now()
            item["error"] = error = ERR_NETWORK
            self._remove_partial(item)
            item["seg_offsets"] = {}
            item["contiguous"] = 0
            _log("err", "下载", "failed", f"下载异常 {item['name']}: {exc}")
        finally:
            item["speed"] = 0.0 if status != "downloading" else item.get("speed", 0.0)
            item["eta"] = None
            self._push(item, status)

    @staticmethod
    def _remove_partial(item: dict):
        """删掉半成品（失败/取消/大小不符时都删，别让用户下到一个坏安装包）"""
        path = str(item.get("path") or "")
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass

    # ---------- 控制 ----------
    def cancel(self, id: str = ""):
        """取消下载（id 为空 = 取消所有进行中的）
        ⚠️ **立刻**把状态改成 "canceled" 并推事件。
           若只置取消标记，要等下载线程自己发现（最多再等一个读超时）才改状态，
           前端这段时间看着还是下载中—— 用户就以为没点生效，连点好几次。
           所以：置标记 + 改状态 + 推事件都在返回前做完，界面马上变已取消。
        ⚠️ 这里**不删文件**：半成品由下载线程的 `_Canceled` 分支 `_remove_partial` 删
           （这里删会和写文件的线程打架）。
        """
        try:
            targets = []
            with self._lock:
                if id:
                    item = self._items.get(str(id))
                    if item is None:
                        return _fail(ERR_NOT_FOUND, canceled=False, status="",
                                     running=False)
                    targets.append(item)
                else:
                    targets = [item for item in self._items.values()
                               if item.get("status") in ("downloading", "paused")]
            canceled = False
            for item in targets:
                was_active = item.get("status") in ("downloading", "paused")
                # ① 先置取消标记：让下载线程尽快停下来
                item.setdefault("cancel", threading.Event()).set()
                # ② 再立刻改状态并推事件：前端不用等线程醒过来
                #    ⚠️ 置标记和改状态之间，下载线程可能刚好**成功**收尾（status="done"）。
                #    这时不能再覆盖成 "canceled"（文件已经下完了，覆盖会让用户以为失败）。
                if was_active and item.get("status") in ("downloading", "paused"):
                    item["status"] = "canceled"
                    item["speed"] = 0.0
                    item["eta"] = None
                    # ⚠️ 记下取消时刻 —— 前端要显示文件名后面的时间
                    #    （见 _push 的 finished_at 说明）。
                    item["finished_at"] = _now()
                    self._push(item, "canceled")
                canceled = canceled or was_active
            return _ok(canceled=canceled,
                       status=(targets[0].get("status") if len(targets) == 1 else
                               ("canceled" if canceled else "")),
                       running=self._running() > 0)
        except Exception as exc:                      # noqa: BLE001
            return _fail(ERR_BAD_RESPONSE, canceled=False, status="", running=False)

    def active_count(self):
        """正在执行的任务数（downloading + paused）—— 退出确认框要用
        ⚠️ 不抛异常：退出流程正在跑，这里挂了会把退出卡住。
        """
        try:
            with self._lock:
                count = sum(1 for it in self._items.values()
                            if it.get("status") in ("downloading", "paused"))
                running = sum(1 for it in self._items.values()
                              if it.get("status") == "downloading")
            return _ok(count=count, running=running)
        except Exception:
            return _ok(count=0, running=0)

    def list(self):
        """所有下载任务（含进度/速度/路径；按创建顺序）"""
        try:
            with self._lock:
                items = [self._snapshot(item) for item in self._items.values()]
            # ⚠️ paused（暂停）也算"进行中" —— 它还没下完，红点要留着
            active = sum(1 for item in items
                         if item.get("status") in ("downloading", "paused"))
            finished = sum(1 for item in items
                           if item.get("status") in ("done", "failed", "canceled"))
            return _ok(items=items, active=active, finished=finished,
                       dir=self.save_dir())
        except Exception as exc:                      # noqa: BLE001
            return _fail(ERR_BAD_RESPONSE, items=[], active=0, finished=0,
                         dir=self.save_dir())

    def open_file(self, id: str = ""):
        """用系统默认程序打开下好的文件"""
        item = self._find(id)
        if item is None:
            return _fail(ERR_NOT_FOUND, path="")
        path = str(item.get("path") or "")
        if not path or not os.path.isfile(path):
            return _fail(ERR_NOT_FOUND, path=path)
        return _ok(path=path) if _open_path(path) else _fail(ERR_UNSUPPORTED, path=path)

    def open_folder(self, id: str = ""):
        """打开下载目录（带 id 时在资源管理器里选中该文件）"""
        item = self._find(id) if id else None
        if item is not None:
            path = str(item.get("path") or "")
            directory = str(item.get("dir") or os.path.dirname(path))
            ok = open_folder(directory, path)
            return _ok(path=directory) if ok else _fail(ERR_UNSUPPORTED, path=directory)
        directory = default_download_dir()
        try:
            os.makedirs(directory, exist_ok=True)
        except Exception:
            pass
        return _ok(path=directory) if open_folder(directory) else \
            _fail(ERR_UNSUPPORTED, path=directory)

    def clear_finished(self, scope: str = "finished"):
        """按范围清理下载任务记录（**不删文件**）
        ⚠️ 前端清空下拉框有三项：
             · 清除全部    → scope='all'
             · 清除已完成  → scope='finished'（done + failed + canceled）
             · 清除未完成  → scope='unfinished'（downloading + paused）
        ⚠️ 正在下载/暂停的任务**不会被**误删（除非 scope='all'）。
        ⚠️ 删掉正在跑的记录前**先置取消标记** —— 否则后台线程还在往一个
           已经被删掉的记录里写进度，下次 list() 它又冒出来（"删了又回来"）。
        """
        scope = str(scope or "finished").strip().lower()
        finished_states = ("done", "failed", "canceled")
        unfinished_states = ("downloading", "paused")
        try:
            with self._lock:
                stale = []
                for key, item in self._items.items():
                    status = str(item.get("status") or "")
                    if scope == "all":
                        stale.append(key)
                    elif scope == "unfinished":
                        if status in unfinished_states:
                            stale.append(key)
                    else:                       # finished
                        if status in finished_states:
                            stale.append(key)
                # ⚠️ 先让后台线程停下来，再把记录删掉
                for key in stale:
                    item = self._items.get(key)
                    if item is None:
                        continue
                    if item.get("status") in unfinished_states:
                        item.setdefault("cancel", threading.Event()).set()
                        # 状态也就地改掉 —— 记录即将消失，线程醒来后
                        # 的收尾推送会被幽灵防护丢弃，这里不留"downloading"残影
                        item["status"] = "canceled"
                for key in stale:
                    self._items.pop(key, None)
            _log("op", "下载", "clear", f"清理下载任务记录 {len(stale)} 条（范围 {scope}）")
            return _ok(removed=len(stale), scope=scope)
        except Exception as exc:                      # noqa: BLE001
            return _fail(ERR_BAD_RESPONSE, removed=0, scope=scope)

    def retry(self, id: str = ""):
        """重试一个失败的下载（复用同一个 id，重置进度）"""
        item = self._find(id)
        if item is None:
            return _fail(ERR_NOT_FOUND, started=False)
        with self._lock:
            if item.get("status") == "downloading":
                return _fail(ERR_TOO_MANY, started=False, id=id)
            item.update({"status": "downloading", "received": 0, "total": 0,
                         "percent": 0.0, "speed": 0.0, "eta": None, "error": "",
                         "started_at": 0.0, "finished_at": 0.0, "used_url": ""})
            # 重试 = 用户明确"从头再下"，续传偏移一起清掉
            #（失败收尾时半成品文件本来也已被 _remove_partial 删除）
            item["seg_offsets"] = {}
            item["contiguous"] = 0
            item["cancel"] = threading.Event()
            # ⚠️ **还要清掉暂停标记** —— 暂停过的任务重试时，
            #    老的 pause 事件还是 set 状态，新线程一进去 _wait_if_paused 就又挂起了，
            #    表现为"点了重试一点反应都没有"。
            item["pause"] = threading.Event()
        _log("op", "下载", "retry", f"重试下载 {item['name']}（{item['url']}）")
        return self._start_thread(item)

    # ---------- 目录 ----------
    def choose_dir(self):
        """系统选择文件夹（部署页第一次下载前问一次）"""
        try:
            initial = self.save_dir()
            picker = getattr(self._shell, "pick_folder", None)
            if picker is None:
                return _ok(path=initial, canceled=True)
            picked = picker(title="选择下载目录", initial=initial)
            if not picked:
                return _ok(path=initial, canceled=True)
            return _ok(path=str(picked), canceled=False)
        except Exception as exc:                      # noqa: BLE001
            return _fail(ERR_BAD_RESPONSE, path=self.save_dir(), canceled=True)

    def default_dir(self):
        """默认下载目录（用户设置的保存位置，空 = 系统下载文件夹）"""
        return _ok(path=self.save_dir())

    def settings_info(self):
        """把当前生效的下载设置回给前端（保存位置 / 线程数 / 重试次数）
        前端设置 → 下载那几行要显示真值（而不是自己猜默认）。
        """
        return _ok(dir=self.save_dir(),
                   default_dir=default_download_dir(),
                   threads=self.download_threads(),
                   retry_count=self.download_retry_count(),
                   retry_interval=RETRY_INTERVAL_S)

    # ---------- 内部 ----------
    def _find(self, id) -> dict:
        with self._lock:
            return self._items.get(str(id or ""))

    @staticmethod
    def _wait_if_paused(item: dict):
        """暂停时挂起当前线程；恢复后继续
        ⚠️ 用 Event.wait 而不是 sleep：取消时能**立刻**跳出，不用干等。
        ⚠️ 暂停标记挂在 item 上（所有分段线程都看同一个），所以多线程分段下载
           会被**整体**暂停 —— 这才是用户预期的"暂停"。
        """
        paused = item.get("pause")
        if paused is None:
            return
        while paused.is_set():
            # 暂停中：被取消也要能退出
            if item.get("cancel") is not None and item["cancel"].is_set():
                raise _Canceled()
            # 等 200ms 再看一次（既能被恢复唤醒，也能及时发现取消）
            paused.wait(0.2)

    # ---------- 暂停 / 恢复 / 删除任务 / 分类清理 ----------
    def pause(self, id: str = ""):
        """暂停一个下载任务（可恢复）
        ⚠️ 暂停只是**挂起**下载线程，任务记录还在、进度保留，恢复后接着下。
        """
        try:
            item = self._find(id)
            if item is None:
                return _fail(ERR_NOT_FOUND, paused=False, status="")
            if item.get("status") != "downloading":
                return _fail(ERR_BAD_RESPONSE, paused=False,
                              status=str(item.get("status") or ""))
            item.setdefault("pause", threading.Event()).set()
            item["status"] = "paused"
            self._push(item, "paused")
            _log("op", "下载", "pause", f"暂停下载：{item.get('name')}")
            return _ok(paused=True, status="paused", id=item.get("id"))
        except Exception as exc:                      # noqa: BLE001
            return _fail(exc, paused=False, status="")

    def resume(self, id: str = ""):
        """恢复一个被暂停的下载任务"""
        try:
            item = self._find(id)
            if item is None:
                return _fail(ERR_NOT_FOUND, resumed=False, status="")
            paused = item.get("pause")
            if paused is None or not paused.is_set():
                return _ok(resumed=False, status=str(item.get("status") or ""))
            paused.clear()
            item["status"] = "downloading"
            self._push(item, "downloading")
            _log("op", "下载", "resume", f"恢复下载：{item.get('name')}")
            return _ok(resumed=True, status="downloading", id=item.get("id"))
        except Exception as exc:                      # noqa: BLE001
            return _fail(exc, resumed=False, status="")

    def remove(self, id: str = ""):
        """把一个任务记录从列表里删掉（**不删文件**）
        ⚠️ 只删记录 —— 文件留在磁盘上（用户可能还要）。
        ⚠️ **幂等** —— 记录本来就不在（重复点击 / 前端和后端状态短暂不一致）
           也返回 ok，删除目标已达成。若回 NOT_FOUND，前端弹NOT_FOUND报错，
           配合线程复活（见 _push 的幽灵防护）就成了"删了又回来、再点就报错"的死循环。
        """
        try:
            with self._lock:
                item = self._items.get(str(id or ""))
                if item is None:
                    return _ok(removed=False, id=str(id or ""))
                # 还在下载的：先停掉，免得后台线程还在写这个条目
                if item.get("status") in ("downloading", "paused"):
                    item.setdefault("cancel", threading.Event()).set()
                self._items.pop(str(id or ""), None)
            _log("op", "下载", "remove", f"删除下载任务记录：{item.get('name')}")
            return _ok(removed=True, id=str(id or ""))
        except Exception as exc:                      # noqa: BLE001
            return _fail(exc, removed=False)


def _negative_time(release: dict) -> float:
    """把 published_at 变成"越大越新"的排序键（解析不了当 0）"""
    text = str((release or {}).get("published_at") or "")
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            import datetime
            moment = datetime.datetime.strptime(text, fmt)
            return moment.timestamp()
        except Exception:
            continue
    return 0.0


__all__ = [
    "DownloadDomain", "DownloadError", "parse_repo", "build_candidate_urls",
    "normalize_release", "normalize_platform", "normalize_arch", "score_asset",
    "rank_assets", "safe_filename", "filename_from_url", "unique_path",
    "default_download_dir", "system_download_dir", "clear_releases_cache",
    "filter_releases_for_source", "source_archive_assets",
    "RELEASES_SOURCE_OFFICIAL", "RELEASES_SOURCE_ALL",
    "DEFAULT_DOWNLOAD_THREADS", "DEFAULT_DOWNLOAD_RETRY",
    "MAX_DOWNLOAD_THREADS", "MAX_DOWNLOAD_RETRY", "RETRY_INTERVAL_S",
    "ERR_BAD_URL", "ERR_NETWORK", "ERR_BAD_RESPONSE", "ERR_RATE_LIMITED",
    "ERR_REPO_NOT_FOUND", "ERR_NO_RELEASE", "ERR_NO_MATCH", "ERR_CANCELED",
    "ERR_DISK_ERROR", "ERR_SIZE_MISMATCH", "ERR_TOO_MANY", "ERR_NOT_FOUND",
    "ERR_UNSUPPORTED", "ERR_TIMEOUT",
]
