r"""资源来源：云端 / 本地。
========== 这个模块解决什么 ==========
所以云端 = **GitHub Release 里的一个附件**，不是某个写死的 URL：
    1. `GET /repos/{repo}/releases?per_page=30` 拿全量 release（**包含 prerelease/beta**；
       GitHub 的 /releases 和 /releases/latest 都不带 prerelease，而本项目当前就是 beta）；
    2. 按 semver 比较选**真正最新**的那个（`v1.0.0-beta.10` > `v1.0.0-beta.2`），
       版本号解析不了的按 published_at 兜底；官方 API 被墙/被限流时按
       `constants.GITHUB_MIRRORS` 顺序回退；
    3. 在这个 release 的 assets 里找**大小写不敏感、精确同名**的 `ToolsGCP-Resources.json`
       （拿 `browser_download_url`，下载同样支持镜像前缀）；
    4. 下载 → JSON 校验 → **原子写**进用户数据根的缓存，再记一份元数据。
========== 缓存放哪（硬规则） ==========
`<数据根>/config/cloud/ToolsGCP-Resources.json` + `ToolsGCP-Resources.meta.json`
    默认 = `%USERPROFILE%\.ToolsGCP\config\cloud\…`
数据根由 `core/data_root.resolve_data_root()` 算（指针优先，否则用户主目录）。
⚠️ 绝不写程序目录旁的 `.ToolsGCP`：那是随程序发布的资源目录（可能只读、升级会被覆盖），
   而且云端缓存属于"程序自己产出的文件"，必须跟用户数据根同生共死（删数据根 = 重新拉）。
========== 为什么不阻塞首屏 ==========
网络最坏情况要 8s×重试×多个镜像。所以：
    · `resolve_resource_file()` 只做**路径判断**，绝不联网；
    · 首次读资源库时走 `ensure_background_refresh()` —— 起一条守护线程去拉，
      拉到就写缓存 + 通知上层（`set_notifier`），拉不到就继续用本地自带的那份；
    · 设置页的立即检查走 `resources.cloud_refresh()`（在 js_api 工作线程里同步跑，
      本来就不在 UI 线程上，可以阻塞；界面自己有"正在检查…"）。
⚠️ 后台线程推事件前必须自己再看一眼 `shell._teardown_started`（AGENTS 第 8 条：
   WebView2 比主窗口先销毁，退出竞态里调前端会抛 ObjectDisposedException）。
========== 错误口径 ==========
**只抛机器码**（NETWORK / BAD_RESPONSE / RATE_LIMITED / NO_RELEASE / NO_ASSET /
INVALID_JSON / NOT_CONFIGURED），文案由界面查语言包；日志里写清楚"从哪个源、哪个 tag、
哪条 asset、多少条、耗时多少 / 为什么失败"，方便事后排查。
对外的方法（fetch / refresh / status）**永不向上抛异常**，只回 dict。
"""

import json
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

from ..constants import APP_REPO, CONFIG_DIR, GITHUB_MIRRORS

# 资源索引的文件名（云端附件名 / 本地文件名都用它，大小写不敏感比较）
RESOURCE_FILE_NAME = "ToolsGCP-Resources.json"
ASSET_NAME = RESOURCE_FILE_NAME

# 本地（程序自带）资源索引目录：程序目录旁的 .ToolsGCP
DEFAULT_LOCAL_DIR = CONFIG_DIR

# GitHub release 列表接口（30 条足够：本项目的 release 节奏不可能更多）
RELEASES_API = "https://api.github.com/repos/{repo}/releases?per_page={per_page}"
RELEASES_PER_PAGE = 30

# Release 里**没有** json 附件时的回退地址 —— 直接读该 tag 的源码树。
# 为什么需要：真实仓库的 release（v1.0.0-beta.2 等）目前只附了 exe/zip，
# 没有 ToolsGCP-Resources.json；而这份文件本身是**随仓库一起发布**的
# （.ToolsGCP/ToolsGCP-Resources.json 已入库）。所以云端来源在"没上传附件"时
# 回退到 raw.githubusercontent.com 的同一个 tag，功能立即可用。
# 发布工作流（.github/workflows/release.yml）也已补上把 json 作为 release 附件上传，
# 之后的版本会优先走附件（更快、不依赖源码树路径）。
RAW_INDEX_URL = ("https://raw.githubusercontent.com/{repo}/{tag}/"
                 ".ToolsGCP/ToolsGCP-Resources.json")

# ⚠️ 兼容历史名字：旧代码/文档把云端来源描述成"一个固定 SOURCE_URL"。
#    现在它只是"release 列表接口"的别名，真正的资源地址每次从 release 里找。
SOURCE_URL = RELEASES_API.format(repo=APP_REPO, per_page=RELEASES_PER_PAGE)

# 旧的缓存常量（历史上指向程序目录 → 已迁到数据根，见模块开头）；保留名字防止外部引用炸
CLOUD_CACHE_FILE = ""            # 运行时由 default_cache_file() 算，不再写死程序目录

# 网络参数（按用户要求调整）：
#   · 单次请求 60s（启动加载允许等这么久）；
#   · 启动加载最多尝试 3 次（STARTUP_ATTEMPTS），每次都是一个完整的 60s 窗口；
#   · 整体截止 = 3 × 60s（上限，避免无限等）；
#   · 后台/日常刷新仍可以在实例上单独收紧（CloudResourceSource(timeout=8)）。
TIMEOUT_SECONDS = 60
MAX_RETRY = 2                    # 单次请求内部的网络重试（镜像之间）
STARTUP_ATTEMPTS = 3             # 启动加载总尝试次数
TOTAL_DEADLINE = float(TIMEOUT_SECONDS * STARTUP_ATTEMPTS)
RETRY_BACKOFF = 0.4

# 后台自动检查的最小间隔（秒）：避免每读一次资源库就打一次 GitHub API
BACKGROUND_MIN_INTERVAL = 600.0

USER_AGENT = "ToolsGCP-ResourceSync/1.0"

# 错误机器码（和 announcements / updater 同一个口径：只给码，不给中文）
ERR_NETWORK = "NETWORK"
ERR_BAD_RESPONSE = "BAD_RESPONSE"
ERR_RATE_LIMITED = "RATE_LIMITED"
ERR_NO_RELEASE = "NO_RELEASE"
ERR_NO_ASSET = "NO_ASSET"
ERR_INVALID_JSON = "INVALID_JSON"
ERR_NOT_CONFIGURED = "NOT_CONFIGURED"

# schema_version 只接受"数字开头"的版本串（2.1.0 / 2 / 2.1.0-beta）；
# 这条校验是拿它的主要目的：挡住被代理/镜像替换成 HTML 错误页、或只下载到半截的 JSON。
_SCHEMA_VERSION_RE = re.compile(r"^[0-9]+(\.[0-9A-Za-z._-]+)*$")


class CloudError(Exception):
    """带机器码的云端错误（对外不抛，只用来在内部传递失败原因）"""

    def __init__(self, code: str, detail: str = ""):
        self.code = str(code or ERR_NETWORK)
        self.detail = str(detail or "")
        super().__init__(self.code)

    def __str__(self):
        return self.code


def _now_text(timestamp: float = None) -> str:
    """epoch → 本地 ISO 时间串（前端 new Date() 能直接解析，显示成本地时间）"""
    try:
        moment = datetime.fromtimestamp(float(timestamp))
        return moment.astimezone().isoformat(timespec="seconds")
    except Exception:
        return ""


# ==========================================================================
# 一、路径（缓存永远在**用户数据根**，绝不写程序目录）
# ==========================================================================

_CLOUD_DIR_LOCK = threading.RLock()
_CLOUD_DIR_CACHE = [""]


def cloud_dir() -> str:
    """云端缓存目录：`<数据根>/config/cloud`（首次算出来就记住，进程内不会变）
    ⚠️ 用 `data_root.resolve_data_root()` 而不是自己拼路径：数据根可能被用户在
       设置 → 存储里改过（指针文件说了算），这里跟着走。
    ⚠️ 拿不到数据根时退回 constants.DATA_DIR（它本身就是 data_root 算出来的）。
    """
    with _CLOUD_DIR_LOCK:
        if _CLOUD_DIR_CACHE[0]:
            return _CLOUD_DIR_CACHE[0]
        base = ""
        try:
            from . import data_root
            base = os.path.join(data_root.resolve_data_root(), "config")
        except Exception:
            base = ""
        if not base:
            try:
                from ..constants import DATA_DIR
                base = DATA_DIR
            except Exception:
                base = os.path.join(DEFAULT_LOCAL_DIR, "cloud")
        _CLOUD_DIR_CACHE[0] = os.path.join(base, "cloud")
        return _CLOUD_DIR_CACHE[0]


def reset_cloud_dir_cache():
    """忘掉算好的缓存目录（数据根迁移后 / 测试里重定向用）"""
    with _CLOUD_DIR_LOCK:
        _CLOUD_DIR_CACHE[0] = ""


def default_cache_file() -> str:
    """云端缓存索引的路径（`<数据根>/config/cloud/ToolsGCP-Resources.json`）"""
    return os.path.join(cloud_dir(), RESOURCE_FILE_NAME)


def default_meta_file() -> str:
    """云端缓存元数据的路径（etag / 版本 / 拉取时间…）"""
    return os.path.join(cloud_dir(), "ToolsGCP-Resources.meta.json")


def local_dir_from_settings(settings_manager) -> str:
    """取用户设置的本地资源目录；没设过就用程序自带的 .ToolsGCP"""
    if settings_manager is None:
        return DEFAULT_LOCAL_DIR
    try:
        directory = str(settings_manager.settings.get("local_resource_dir") or "").strip()
    except Exception:
        directory = ""
    return directory or DEFAULT_LOCAL_DIR


def local_bundled_file() -> str:
    """程序自带的那份资源索引（随版本发布，永远存在，云端拿不到时用它兜底）"""
    return os.path.join(DEFAULT_LOCAL_DIR, RESOURCE_FILE_NAME)


def resolve_resource_file(settings_manager=None, trigger_refresh: bool = False) -> str:
    """按当前设置算出该读哪个资源索引文件
    这是全程序唯一的判断点，搜索页 / 资源详情 / 制作器都走它，保证行为一致。
    `trigger_refresh=True` 时（只由资源库 API 传）如果云端还没缓存，
    顺手起一条**后台**线程去拉 —— 绝不在调用方线程里联网。
    """
    source = "cloud"
    if settings_manager is not None:
        try:
            source = str(settings_manager.settings.get("resource_source") or "cloud")
        except Exception:
            source = "cloud"

    if source == "local":
        user_file = os.path.join(local_dir_from_settings(settings_manager),
                                 RESOURCE_FILE_NAME)
        # 用户选的自定义目录里没有文件时，回退程序自带的那份：
        # 否则整个资源库会"空掉"（用户会以为程序坏了，而不是自己目录没放对）。
        if os.path.isfile(user_file):
            return user_file
        bundled = local_bundled_file()
        if os.path.abspath(user_file) != os.path.abspath(bundled):
            _log("warn", f"本地资源目录里没有 {RESOURCE_FILE_NAME}（{user_file}），"
                         f"回退程序自带的一份")
        return bundled

    # 云端：有缓存用缓存；没有缓存先回退本地自带，同时后台去拉最新的
    source_obj = CloudResourceSource()
    cached = source_obj.get_index_path()
    if trigger_refresh:
        ensure_background_refresh()
    if cached:
        return cached
    bundled = local_bundled_file()
    if not os.path.isfile(bundled):
        _log("warn", f"云端还没缓存、程序自带的资源索引也不见了：{bundled}")
    return bundled


# ==========================================================================
# 二、版本比较（semver：beta.10 > beta.2、正式版 > 预发布）
# ==========================================================================

def parse_version(tag: str):
    """把 tag 解析成 (major, minor, patch, [预发布标识…])；解析不了返回 None
    支持 `v1.0.0`、`1.0.0-beta.2`、`v1.0.0-rc.1+build.5`；缺的段补 0。
    ⚠️ 解析不了**不猜**：交给 published_at 兜底（宁可晚一版，也别选错版本）。
    """
    raw = str(tag or "").strip()
    if raw[:1] in ("v", "V"):
        raw = raw[1:]
    if not raw:
        return None
    raw = raw.split("+", 1)[0]                    # 丢掉构建元数据
    core, _, pre = raw.partition("-")
    parts = core.split(".")
    if not 1 <= len(parts) <= 3:
        return None
    numbers = []
    for part in parts:
        if not part.isdigit():
            return None
        numbers.append(int(part))
    while len(numbers) < 3:
        numbers.append(0)
    pre_ids = []
    if pre:
        for piece in pre.split("."):
            if not piece or not re.fullmatch(r"[0-9A-Za-z-]+", piece):
                return None
            pre_ids.append(piece)
    return (numbers[0], numbers[1], numbers[2], pre_ids)


def version_key(tag: str):
    """可比较的排序键；解析不了返回 None
    返回 (major, minor, patch, 正式版标记, 预发布标识…)
        正式版标记：1 = 正式版、0 = 预发布 ⇒ 任何正式版都大于同号预发布（semver 第 11 条）
        预发布标识逐段比：纯数字按数值（beta.10 > beta.2），字母按字典序（rc > beta > alpha）
    """
    parsed = parse_version(tag)
    if parsed is None:
        return None
    major, minor, patch, pre_ids = parsed
    if not pre_ids:
        return (major, minor, patch, 1, ())
    keys = []
    for piece in pre_ids:
        if piece.isdigit():
            # (0, 数字, "") 与 (1, 0, 字母) 比较时先比第一位 ⇒ 数字标识 < 字母标识（semver）
            keys.append((0, int(piece), ""))
        else:
            keys.append((1, 0, piece))
    return (major, minor, patch, 0, tuple(keys))


def _published_at(release: dict) -> str:
    """release 的发布时间串（ISO，UTC）—— 用作版本号相同时的 tie-break 与兜底排序"""
    release = release or {}
    return str(release.get("published_at") or release.get("created_at") or "").strip()


def select_latest_release(releases):
    """从 release 列表里挑**真正最新**的一个（包含 prerelease，排除 draft）
    优先级：能解析的版本号 > 解析不了的；版本号相同或都解析不了时比 published_at。
    """
    usable = []
    for release in (releases or []):
        if not isinstance(release, dict):
            continue
        if release.get("draft"):
            continue                          # 草稿用户根本看不到，不能算"最新"
        if not str(release.get("tag_name") or "").strip():
            continue
        usable.append(release)
    if not usable:
        return None
    scored = []
    for release in usable:
        key = version_key(release.get("tag_name"))
        if key is None:
            continue
        scored.append((key, _published_at(release), release))
    if scored:
        return max(scored, key=lambda item: (item[0], item[1]))[2]
    # 全部解析不了（自定义 tag 命名）：退化成"发布时间最新"，至少不会选空
    return max(usable, key=_published_at)


def find_resource_asset(release):
    """在 release.assets 里找 ToolsGCP-Resources.json（大小写不敏感、精确同名）
    返回 asset dict（含 browser_download_url）；没有返回 None。
    """
    for asset in ((release or {}).get("assets") or []):
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").strip()
        if name.lower() != ASSET_NAME.lower():
            continue
        if not str(asset.get("browser_download_url") or "").strip():
            continue
        return asset
    return None


# ==========================================================================
# 三、网络（官方直连优先，镜像兜底；带超时 / 重试 / 整体截止）
# ==========================================================================

def _mirrors() -> list:
    """镜像域名列表（constants.GITHUB_MIRRORS 是唯一事实来源）"""
    try:
        return [str(m).strip() for m in (GITHUB_MIRRORS or []) if str(m or "").strip()]
    except Exception:
        return []


def build_candidate_urls(url: str, mirrors=None) -> list:
    """同一个资源的候选地址：官方直连 → 各镜像（`https://{镜像}/{原地址}`）
    GitHub 的 releases API 和 assets 下载都是这个拼法（与 announcements 的镜像顺序一致）。
    ⚠️ 镜像项**允许是完整 URL**（自建代理 / 本地测试服务器需要）：带 scheme 就原样当前缀。
    """
    direct = str(url or "").strip()
    if not direct:
        return []
    urls = [direct]
    for mirror in (mirrors if mirrors is not None else _mirrors()):
        mirror = str(mirror or "").strip().rstrip("/")
        if not mirror:
            continue
        prefix = mirror if "://" in mirror else f"https://{mirror}"
        candidate = f"{prefix}/{direct}"
        if candidate not in urls:
            urls.append(candidate)
    return urls


def _open(url: str, timeout: float, headers: dict = None):
    hdrs = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
        "Cache-Control": "no-cache, no-store, max-age=0",
        "Pragma": "no-cache",
    }
    hdrs.update(headers or {})
    return urllib.request.urlopen(urllib.request.Request(url, headers=hdrs),
                                  timeout=max(1.0, float(timeout)))


def _request_once(url: str, timeout: float, headers: dict = None):
    """发一次 GET → (状态码, 响应体 bytes, 响应头 dict)
    304 不是错误（ETag 命中），单独回状态码让调用方判断；其它非 2xx 转成机器码。
    """
    try:
        with _open(url, timeout, headers) as response:
            return (int(getattr(response, "status", 200) or 200),
                    response.read(), dict(response.headers or {}))
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return 304, b"", dict(exc.headers or {})
        if exc.code in (403, 429):
            raise CloudError(ERR_RATE_LIMITED, f"HTTP {exc.code}")
        if exc.code == 404:
            raise CloudError(ERR_BAD_RESPONSE, "HTTP 404")
        raise CloudError(ERR_BAD_RESPONSE, f"HTTP {exc.code}")
    except Exception as exc:                      # noqa: BLE001 - 超时/DNS/TLS 全算网络
        raise CloudError(ERR_NETWORK, f"{type(exc).__name__}: {exc}")


def _request_with_retry(urls, timeout: float, retries: int, headers: dict = None,
                        deadline: float = None):
    """按候选地址依次尝试 + 每个地址重试；返回 (状态码, 响应体, 响应头, 用到的地址)
    ⚠️ RATE_LIMITED 不重试同一个地址（限流重试没有意义），直接换下一个源；
       网络类错误才退避重试。整体超过 deadline 就停，别让界面等太久。
    """
    last_error = CloudError(ERR_NETWORK, "没有可用的源")
    for url in urls:
        for attempt in range(int(retries) + 1):
            if deadline and time.monotonic() > deadline:
                raise CloudError(last_error.code, f"{last_error.detail}（整体超时）")
            try:
                status, body, hdrs = _request_once(url, timeout, headers)
                return status, body, hdrs, url
            except CloudError as exc:
                last_error = CloudError(exc.code, f"{url} → {exc.detail}")
                if exc.code == ERR_RATE_LIMITED:
                    break
                if attempt < int(retries):
                    time.sleep(RETRY_BACKOFF * (attempt + 1))
    raise last_error


def _decode_json(body: bytes):
    """bytes → python 对象；解不开抛 BAD_RESPONSE（HTML 错误页/半截内容都会踩到）"""
    try:
        return json.loads(body.decode("utf-8", "ignore"))
    except Exception as exc:                      # noqa: BLE001
        raise CloudError(ERR_BAD_RESPONSE, f"JSON 解析失败: {exc}")


def fetch_releases(repo: str = APP_REPO, mirrors=None, timeout: float = TIMEOUT_SECONDS,
                   retries: int = MAX_RETRY, deadline: float = None):
    """拉 release 列表（含 prerelease）→ (release 列表, 用到的地址)
    ⚠️ 不用 `/releases/latest`：它只给正式版，而本项目当前只有 beta 版。
    """
    repo = str(repo or "").strip()
    if not repo:
        raise CloudError(ERR_NOT_CONFIGURED, "没配置仓库")
    api_url = RELEASES_API.format(repo=repo, per_page=RELEASES_PER_PAGE)
    status, body, _hdrs, used_url = _request_with_retry(
        build_candidate_urls(api_url, mirrors), timeout, retries, deadline=deadline)
    data = _decode_json(body)
    if isinstance(data, dict):                    # GitHub 的错误体：{"message": "..."}
        message = str(data.get("message") or "")
        if "rate limit" in message.lower():
            raise CloudError(ERR_RATE_LIMITED, message)
        raise CloudError(ERR_BAD_RESPONSE, message or "release 列表不是数组")
    if not isinstance(data, list):
        raise CloudError(ERR_BAD_RESPONSE, f"release 列表类型异常: {type(data).__name__}")
    return data, used_url


# ==========================================================================
# 四、校验 / 原子写
# ==========================================================================

def validate_index(data: dict) -> int:
    """校验资源索引 → 返回条目数；不合法抛 CloudError(INVALID_JSON)
    校验点（都是"踩过就知道疼"的）：
        · 顶层必须是 dict（HTML 错误页解不出来、或解出来是 list/str）；
        · resources 必须是**非空** list —— 空库写进缓存等于把用户的资源库清空；
        · schema_version 必须是数字开头的版本串（挡住被镜像替换坏的半截文件）；
        · 至少有一条 dict 且带 id/code，否则前端渲染出来全是空卡片。
    """
    if not isinstance(data, dict):
        raise CloudError(ERR_INVALID_JSON,
                         f"顶层不是对象（{type(data).__name__}）")
    resources = data.get("resources")
    if not isinstance(resources, list) or not resources:
        raise CloudError(ERR_INVALID_JSON, "resources 不是非空数组")
    schema_version = data.get("schema_version")
    if not isinstance(schema_version, (str, int, float)):
        raise CloudError(ERR_INVALID_JSON, "schema_version 缺失或类型异常")
    schema_text = str(schema_version).strip()
    if not _SCHEMA_VERSION_RE.match(schema_text):
        raise CloudError(ERR_INVALID_JSON, f"schema_version 不合理: {schema_text[:40]}")
    usable = [item for item in resources
              if isinstance(item, dict) and (item.get("id") or item.get("code"))]
    if not usable:
        raise CloudError(ERR_INVALID_JSON, "resources 里没有一条带 id/code 的记录")
    return len(usable)


def count_duplicate_codes(data: dict) -> int:
    """统计重复的 code 个数（可选校验：只记日志，不拒绝 —— 用户手工合库容易出现）"""
    seen = set()
    duplicated = 0
    for item in ((data or {}).get("resources") or []):
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        if code in seen:
            duplicated += 1
        else:
            seen.add(code)
    return duplicated


def atomic_write_json(path: str, data) -> bool:
    """原子写 JSON：同目录临时文件 + fsync + os.replace
    ⚠️ 必须同目录（os.replace 跨卷会失败），而且**先写完整再替换**：
       写到一半崩掉也不会留下半截缓存让下次启动读崩。
    """
    directory = os.path.dirname(os.path.abspath(path))
    temp_path = ""
    try:
        os.makedirs(directory, exist_ok=True)
        handle, temp_path = tempfile.mkstemp(prefix=".cloud-", suffix=".tmp", dir=directory)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except Exception:
                pass                              # 某些文件系统不支持 fsync，无妨
        os.replace(temp_path, path)
        return True
    except Exception as exc:                      # noqa: BLE001
        _log("warn", f"写缓存失败 {path}: {exc}")
        try:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass
        return False


# ==========================================================================
# 五、云端来源本体
# ==========================================================================

class CloudResourceSource:
    """GitHub Release 里的资源索引（选最新 → 找 asset → 下载 → 校验 → 原子写缓存）
    对外全部方法都不抛异常：失败只体现在 `last_error` / 返回的 dict 里。
    `cache_file` / `meta_file` / `repo` / `mirrors` 都能注入 —— 单元测试用本地
    http.server 模拟 GitHub API 时全靠这几个参数。
    """

    def __init__(self, cache_file: str = "", meta_file: str = "", repo: str = "",
                 mirrors=None, timeout: float = TIMEOUT_SECONDS,
                 retries: int = MAX_RETRY, releases_api: str = "",
                 raw_index_url: str = "", startup_attempts: int = STARTUP_ATTEMPTS):
        self.cache_file = cache_file or default_cache_file()
        self.meta_file = meta_file or default_meta_file()
        self.repo = str(repo or APP_REPO).strip()
        self.mirrors = None if mirrors is None else list(mirrors)
        self.timeout = float(timeout or TIMEOUT_SECONDS)
        self.retries = int(MAX_RETRY if retries is None else retries)
        self.releases_api = str(releases_api or "").strip()
        # Release 没带 json 附件时的回退模板（测试可注入本地地址）
        self.raw_index_url = str(raw_index_url or "").strip() or RAW_INDEX_URL
        # 启动加载的总尝试次数（默认 3 次 × timeout 60s；测试可注入小值）
        try:
            self.startup_attempts = max(1, int(startup_attempts or STARTUP_ATTEMPTS))
        except Exception:
            self.startup_attempts = STARTUP_ATTEMPTS
        self.last_error = ""
        self.last_updated = False
        self.last_used_url = ""
        self.last_version = ""

    # ---------- 状态 ----------
    def configured(self) -> bool:
        """有没有配置过云端来源（仓库地址是编译期常量，正常永远 True）"""
        return bool(self.repo)

    def is_available(self) -> bool:
        """云端缓存是否**可用**（存在、能解析、resources 非空）"""
        return bool(self.get_index_path())

    def get_index_path(self) -> str:
        """返回可以直接读的云端索引文件路径；没有/坏了返回空串（调用方回退本地）"""
        if not os.path.isfile(self.cache_file):
            return ""
        data = self.read_cache()
        if not data:
            return ""
        resources = data.get("resources")
        if not isinstance(resources, list) or not resources:
            return ""
        return self.cache_file

    def read_cache(self) -> dict:
        """读本地缓存（没有或坏了就返回空 dict）"""
        try:
            if not os.path.isfile(self.cache_file):
                return {}
            with open(self.cache_file, "r", encoding="utf-8") as stream:
                data = json.load(stream)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def read_meta(self) -> dict:
        """读缓存元数据（版本 / etag / 拉取时间 / 条数）；没有返回空 dict"""
        try:
            if not os.path.isfile(self.meta_file):
                return {}
            with open(self.meta_file, "r", encoding="utf-8") as stream:
                data = json.load(stream)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def clear_cache(self):
        """清掉云端缓存，下次会重新拉（同时清元数据，否则 etag 会让它误判 304）"""
        for path in (self.cache_file, self.meta_file):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
        self.last_updated = False
        self.last_error = ""

    def status(self) -> dict:
        """给 `resources.cloud_status()` 用的状态（不含 ok 信封，由 API 层加）
        `available` = 缓存可用；`version` = release tag（去掉 v 前缀）；`count` = 缓存条数；
        `error` = 最近一次失败的机器码（成功过就是上次失败的原因，方便排查）。
        ⚠️ 就算缓存不可用也把 `error` 带上：界面据此显示"拉取失败（原因）"，不编造成功。
        """
        meta = self.read_meta()
        cached = self.read_cache()
        resources = cached.get("resources") if isinstance(cached, dict) else None
        available = bool(self.get_index_path())
        fetched_at = meta.get("fetched_at") or 0
        updated_at = _now_text(fetched_at) if fetched_at else ""
        if not available:
            updated_at = ""
        error = "" if available else str(self.last_error or meta.get("error") or "")
        return {
            "configured": self.configured(),
            "available": available,
            "version": str(meta.get("version") or ""),
            "tag": str(meta.get("tag") or ""),
            "updated_at": updated_at,
            "count": len(resources) if isinstance(resources, list) else 0,
            "error": error,
            # 界面把它当语言键查文案（`error` 保持机器码，符合"错误只抛码"的约定）
            "error_key": f"cloud_error_{error}" if error else "",
            "path": self.cache_file,
            "repo": self.repo,
        }

    # ---------- 核心：拉取 ----------
    def _touch_meta_check(self):
        """记下"这次检查的时间"（**失败也记**）
        为什么失败也要记：没有它，用户每次启动都会撞一次 GitHub API（未鉴权限流 60 次/小时），
        重启几次就被限流了。`ensure_background_refresh` 靠这个时间戳做跨进程节流。
        """
        try:
            meta = self.read_meta()
            meta["last_check_at"] = time.time()
            meta["last_check_at_text"] = _now_text(meta["last_check_at"])
            atomic_write_json(self.meta_file, meta)
        except Exception as exc:                  # noqa: BLE001 - 记时间失败不影响拉取
            _log("warn", f"写云端检查时间失败（不影响拉取）: {exc}")

    def fetch(self, force: bool = False, attempts: int = None) -> dict:
        """**带启动重试**的拉取（用户要求"加载不出来还会重试 3 次，每次 60s"）
        · `attempts=None` → 用实例的 startup_attempts（默认 3）；设置页"立即检查"传 1。
        · 每次尝试是一个完整的 `timeout`（默认 60s）窗口；全部失败后返回最后一次的错误码。
        · **任何时候都先保留旧缓存**（失败不清缓存，用户资源库不会空）。
        · 日志写清第几次/耗时/结果，排错一眼能看出来。
        """
        total = self.startup_attempts if attempts is None else max(1, int(attempts))
        last = {"ok": False, "updated": False, "version": "", "count": 0,
                "path": self.cache_file, "error": ""}
        for index in range(1, total + 1):
            started = time.monotonic()
            last = self._fetch_once(force=force)
            if last.get("ok"):
                if index > 1:
                    _log("info", f"云端资源库第 {index} 次尝试成功"
                                 f"（共 {total} 次，耗时 {time.monotonic() - started:.1f}s）")
                return last
            if index < total:
                _log("warn", f"云端资源库第 {index}/{total} 次加载失败"
                             f"（{last.get('error') or 'UNKNOWN'}，耗时 "
                             f"{time.monotonic() - started:.1f}s），{RETRY_BACKOFF}s 后重试")
                time.sleep(RETRY_BACKOFF)
        if total > 1:
            _log("err", f"云端资源库连续 {total} 次加载失败（最后一次错误："
                        f"{last.get('error') or 'UNKNOWN'}），继续使用本地资源库")
        else:
            _log("warn", f"云端资源库拉取失败（{last.get('error') or 'UNKNOWN'}），"
                         f"继续使用本地资源库")
        return last

    def _fetch_once(self, force: bool = False) -> dict:
        """单次拉取（原 fetch 的实现；`fetch()` 负责重试循环）
        ⚠️ 本次尝试的总预算：最多 60 秒（用户要求"每次 60 秒"）。
           但**必须容得下镜像回退**：直连地址先耗掉一个 timeout 时，镜像还得有机会试。
           所以按"候选地址数 × timeout"算预算，再封顶 60 秒
           （timeout=60 时正好 60 秒；timeout=2（测试）时 2 个源 = 4 秒）。
        """
        started = time.monotonic()
        try:
            candidates = len(build_candidate_urls(
                self.releases_api or RELEASES_API.format(
                    repo=self.repo, per_page=RELEASES_PER_PAGE), self.mirrors)) or 1
        except Exception:
            candidates = 1
        budget = min(60.0, float(self.timeout) * max(1, candidates))
        deadline = started + budget
        self.last_updated = False
        self.last_error = ""
        result = {"ok": False, "updated": False, "version": "", "count": 0,
                  "path": self.cache_file, "error": ""}
        if not self.configured():
            self.last_error = ERR_NOT_CONFIGURED
            result["error"] = ERR_NOT_CONFIGURED
            _log("warn", "云端资源未配置仓库，跳过拉取")
            return result
        self._touch_meta_check()

        # ---- 1) release 列表 → 选最新 ----
        try:
            api_url = self.releases_api or RELEASES_API.format(
                repo=self.repo, per_page=RELEASES_PER_PAGE)
            status, body, _hdrs, used_url = _request_with_retry(
                build_candidate_urls(api_url, self.mirrors),
                self.timeout, self.retries, deadline=deadline)
            releases = _decode_json(body)
            if isinstance(releases, dict):
                message = str(releases.get("message") or "")
                if "rate limit" in message.lower():
                    raise CloudError(ERR_RATE_LIMITED, message)
                raise CloudError(ERR_BAD_RESPONSE, message or "release 列表不是数组")
            if not isinstance(releases, list):
                raise CloudError(ERR_BAD_RESPONSE, "release 列表类型异常")
        except CloudError as exc:
            self.last_error = exc.code
            result["error"] = exc.code
            _log("warn", f"拉 release 列表失败（{exc.detail or exc.code}），沿用现有缓存",
                 code=exc.code, elapsed=f"{time.monotonic() - started:.1f}s")
            return result

        self.last_used_url = used_url
        release = select_latest_release(releases)
        if release is None:
            self.last_error = ERR_NO_RELEASE
            result["error"] = ERR_NO_RELEASE
            _log("warn", f"仓库 {self.repo} 没有可用的 release（含 beta 都算），沿用现有缓存")
            return result
        tag = str(release.get("tag_name") or "").strip()
        version = tag[1:] if tag[:1] in ("v", "V") else tag
        self.last_version = version

        # ---- 2) 找 ToolsGCP-Resources.json 附件（找不到就回退 tag 源码树）----
        asset = find_resource_asset(release)
        asset_kind = "asset"
        if asset is None:
            names = [str(a.get("name") or "") for a in (release.get("assets") or [])
                     if isinstance(a, dict)]
            # 真实仓库这些 release 只附了 exe/zip，没有 json 附件。
            # 资源库文件本身在仓库里（.ToolsGCP/ToolsGCP-Resources.json），
            # 所以回退到该 tag 的 raw 地址；镜像同样生效（build_candidate_urls 会拼前缀）。
            raw_url = self.raw_index_url.format(repo=self.repo, tag=tag)
            asset = {"name": ASSET_NAME, "browser_download_url": raw_url}
            asset_kind = "raw"
            _log("info", f"release {tag} 没有 {ASSET_NAME} 附件，回退到该 tag 源码树里的资源库",
                 tag=tag, assets=",".join(names[:10]), fallback=raw_url,
                 source="mirror" if used_url != api_url else "direct")
        asset_url = str(asset.get("browser_download_url") or "").strip()

        # ---- 3) 下载（带 ETag / If-None-Match）----
        meta = self.read_meta()
        etag = str(meta.get("etag") or "")
        same_asset = str(meta.get("asset_url") or "") == asset_url
        headers = {}
        if etag and same_asset and not force:
            headers["If-None-Match"] = etag
        try:
            status, body, resp_headers, download_url = _request_with_retry(
                build_candidate_urls(asset_url, self.mirrors),
                self.timeout, self.retries, headers=headers, deadline=deadline)
        except CloudError as exc:
            self.last_error = exc.code
            result["error"] = exc.code
            result["version"] = version
            _log("warn", f"下载 {ASSET_NAME} 失败（{exc.detail or exc.code}），沿用现有缓存",
                 tag=tag, code=exc.code, elapsed=f"{time.monotonic() - started:.1f}s")
            return result

        if status == 304:
            # 内容没变：**不重写缓存、不算失败**（用户视角就是"已是最新"）
            cached = self.read_cache()
            count = len(cached.get("resources") or []) if isinstance(cached, dict) else 0
            _log("op", f"云端资源未变化（304），沿用缓存：{self.cache_file}", tag=tag, count=count)
            self.last_error = ""
            result.update({"ok": True, "updated": False, "version": version,
                           "count": count, "error": ""})
            return result

        # ---- 4) 校验 ----
        try:
            data = _decode_json(body)
            count = validate_index(data)
        except CloudError as exc:
            # ⚠️ 校验失败**绝不覆盖**旧缓存：坏数据一旦落盘，用户下次启动资源库就空了。
            self.last_error = exc.code
            result["error"] = exc.code
            result["version"] = version
            _log("err", f"云端资源索引校验失败（{exc.detail or exc.code}），保留旧缓存",
                 tag=tag, code=exc.code, bytes=len(body))
            return result

        # ---- 5) 原子写缓存 + 元数据 ----
        if not atomic_write_json(self.cache_file, data):
            self.last_error = ERR_BAD_RESPONSE
            result["error"] = ERR_BAD_RESPONSE
            _log("err", f"云端资源缓存写盘失败：{self.cache_file}")
            return result
        fetched_at = time.time()
        # ⚠️ 成功时整份重写元数据，必须把 `_touch_meta_check()` 记的检查时间带上，
        #    否则"拉成功之后重启"会立刻再拉一次（跨进程节流失效 → 撞 GitHub 限流）。
        previous_meta = meta if isinstance(meta, dict) else {}
        new_meta = {
            "repo": self.repo,
            "version": version,
            "tag": tag,
            "asset_name": ASSET_NAME,
            "asset_kind": asset_kind,          # asset = Release 附件 / raw = tag 源码树
            "asset_url": asset_url,
            "asset_size": len(body),
            "etag": str(resp_headers.get("ETag") or resp_headers.get("Etag") or ""),
            "last_modified": str(resp_headers.get("Last-Modified") or ""),
            "fetched_at": fetched_at,
            "fetched_at_text": _now_text(fetched_at),
            "last_check_at": float(previous_meta.get("last_check_at") or fetched_at),
            "last_check_at_text": _now_text(previous_meta.get("last_check_at") or fetched_at),
            "count": count,
            "schema_version": str(data.get("schema_version") or ""),
            "source_url": download_url,
            "api_source": "direct" if used_url == api_url else "mirror",
            "duplicate_codes": count_duplicate_codes(data),
        }
        atomic_write_json(self.meta_file, new_meta)
        self.last_updated = True
        self.last_error = ""
        result.update({"ok": True, "updated": True, "version": version,
                       "count": count, "error": ""})
        elapsed = time.monotonic() - started
        _log("op", f"云端资源已更新：{tag}（{count} 条，来自 "
                   f"{new_meta['api_source']}，"
                   f"{'Release 附件' if asset_kind == 'asset' else 'tag 源码树 raw'} → "
                   f"{self.cache_file}）",
             tag=tag, count=count, asset=ASSET_NAME, asset_kind=asset_kind,
             elapsed=f"{elapsed:.1f}s",
             source=new_meta["api_source"], duplicate_codes=new_meta["duplicate_codes"])
        return result

    def refresh(self, force: bool = False) -> dict:
        """设置页立即检查/ 重试图标用：**只拉一次**（不在内部再叠 3 次重试链）
        ⚠️ 和启动加载 `fetch()`（默认 3 次 × 60s）分开：
            · 启动加载要等够 3 次（用户要求）；
            · 设置页点一下重试，不应该一次卡 3 分钟 —— 交给用户自己再点。
        """
        return self.fetch(force=force, attempts=1)


# ==========================================================================
# 六、后台刷新 + 通知（首屏不阻塞）
# ==========================================================================

_BG_LOCK = threading.RLock()
_BG_STATE = {
    "running": False,
    "last_attempt": 0.0,
    "last_finished": 0.0,
    "last_result": None,
}
_NOTIFIER = [None]


def set_notifier(callback):
    """注册"云端缓存更新了"的通知回调（API 层注册，内部实现推前端事件）
    core 层不认识 shell，所以这里只留一个回调位；None = 不通知。
    """
    _NOTIFIER[0] = callback if callable(callback) else None


def notify_result(result: dict):
    """把刚拉到的结果交给注册方（**注册方**负责检查 `_teardown_started` 再推前端）"""
    callback = _NOTIFIER[0]
    if callback is None:
        return
    try:
        callback(dict(result or {}))
    except Exception as exc:                      # noqa: BLE001 - 通知失败不影响拉取
        _log("warn", f"云端资源更新通知失败: {exc}")


def background_state() -> dict:
    """后台刷新状态（测试 / 排查用）"""
    with _BG_LOCK:
        return dict(_BG_STATE)


def ensure_background_refresh(min_interval: float = BACKGROUND_MIN_INTERVAL,
                              force: bool = False, source=None) -> bool:
    """保证"最近检查过"；没检查过就起一条**守护线程**去拉（返回是否真的起了线程）
    ⚠️ 只在后台线程里联网：调用方（首屏加载、资源库读取）不会被网络卡住。
    ⚠️ `min_interval` 是"两次检查的最小间隔"：读资源库的频率远高于检查更新的频率，
       没有它就会每次读盘都打一次 GitHub API（触发限流是必然的）。
    """
    now = time.monotonic()
    with _BG_LOCK:
        if _BG_STATE["running"]:
            return False
        if not force and (now - float(_BG_STATE["last_attempt"] or 0)) < float(min_interval):
            return False
        # 跨进程节流：上次检查时间持久化在元数据里（重启不会绕过它）
        if not force:
            probe = source or CloudResourceSource()
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
            result = (source or CloudResourceSource()).fetch(force=force)
        except Exception as exc:                  # noqa: BLE001 - 兜底，绝不带崩线程
            result = {"ok": False, "updated": False, "error": ERR_NETWORK,
                      "detail": str(exc), "path": ""}
            _log("warn", f"后台拉取云端资源异常: {exc}")
        finally:
            with _BG_LOCK:
                _BG_STATE["running"] = False
                _BG_STATE["last_finished"] = time.monotonic()
                _BG_STATE["last_result"] = dict(result or {})
            notify_result(result)

    thread = threading.Thread(target=_work, name="ToolsGCP-cloud-resource", daemon=True)
    thread.start()
    return True


# ==========================================================================
# 七、日志（延迟导入，避免和 constants/logger 成环）
# ==========================================================================

def _log(level: str, message: str, **fields):
    try:
        from ..utils.logger import log
        getattr(log, level, log.info)("资源库", "cloud", message, **fields)
    except Exception:
        pass


__all__ = [
    "RESOURCE_FILE_NAME", "ASSET_NAME", "SOURCE_URL", "CLOUD_CACHE_FILE",
    "ERR_NETWORK", "ERR_BAD_RESPONSE", "ERR_RATE_LIMITED", "ERR_NO_RELEASE",
    "ERR_NO_ASSET", "ERR_INVALID_JSON", "ERR_NOT_CONFIGURED",
    "CloudError", "CloudResourceSource",
    "cloud_dir", "reset_cloud_dir_cache", "default_cache_file", "default_meta_file",
    "local_dir_from_settings", "local_bundled_file", "resolve_resource_file",
    "parse_version", "version_key", "select_latest_release", "find_resource_asset",
    "build_candidate_urls", "fetch_releases", "validate_index",
    "count_duplicate_codes", "atomic_write_json",
    "set_notifier", "notify_result", "background_state", "ensure_background_refresh",
]
