"""下载与下载地址解析（只用标准库）
解析一个资源该从哪儿下载：download_url 直链 → GitHub Releases 最新安装包
（查 API）→ 退回打开官网页面。另含带进度、可限速、可取消的下载线程。
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal

USER_AGENT = "ToolsGCP-Deploy/1.0"

# 优先挑选的安装包后缀（按优先级从高到低）
PREFERRED_EXTS = (".exe", ".msi", ".zip", ".7z", ".rar", ".dmg", ".pkg", ".apk", ".deb", ".appimage")
# 明显不是 Windows 产物的关键词（命中就大幅降分）
SKIP_HINTS = ("source", "src", "debug", "symbols", "linux", "macos", "darwin", "android", "ios")

GITHUB_API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"

# 解析结果缓存：owner/repo → (直链, 文件名, 错误)
_asset_cache: dict = {}


def _open(url: str, timeout: float = 20.0):
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json, application/octet-stream",
    })
    return urllib.request.urlopen(request, timeout=timeout)


def parse_github_repo(url: str) -> Optional[str]:
    """从 GitHub 地址里取出 owner/repo"""
    if not url:
        return None
    m = re.match(r"^https?://(?:www\.)?github\.com/([^/]+)/([^/#?]+)", str(url).strip(), re.I)
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    repo = re.sub(r"\.git$", "", repo)
    if owner.lower() in ("orgs", "topics", "search", "features", "apps"):
        return None
    return f"{owner}/{repo}"


def _pick_asset(assets: list) -> Optional[dict]:
    """从 release assets 里挑一个最像安装包的"""
    scored = []
    for asset in assets or []:
        name = str(asset.get("name") or "")
        low = name.lower()
        if not low or low.endswith((".sig", ".sha256", ".txt", ".json", ".yml", ".yaml", ".asc")):
            continue
        score = 0
        for i, ext in enumerate(PREFERRED_EXTS):
            if low.endswith(ext):
                score = 100 - i * 5
                break
        if score == 0:
            continue
        if any(hint in low for hint in SKIP_HINTS):
            score -= 60
        # 这些变体不是默认首选
        if "mono" in low or "console" in low or "headless" in low:
            score -= 15
        size = int(asset.get("size") or 0)
        if size > 0:
            score += 1
        scored.append((score, size, asset))
    if not scored:
        return None
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return scored[0][2]


def resolve_github_asset(github_url: str):
    """查询 GitHub 最新 release 的安装包直链，返回 (直链, 建议文件名, 错误信息)"""
    repo = parse_github_repo(github_url)
    if not repo:
        return None, None, "不是有效的 GitHub 仓库地址"

    if repo in _asset_cache:
        return _asset_cache[repo]

    api = GITHUB_API.format(owner=repo.split("/")[0], repo=repo.split("/")[1])
    try:
        with _open(api, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            result = (None, None, "该仓库没有发布过 Release")
        elif e.code == 403:
            result = (None, None, "GitHub API 访问次数超限，稍后再试")
        else:
            result = (None, None, f"查询失败（HTTP {e.code}）")
        _asset_cache[repo] = result
        return result
    except Exception as e:
        return None, None, f"查询失败：{e}"

    asset = _pick_asset(data.get("assets"))
    if not asset:
        result = (None, None, "该 Release 里没有找到安装包")
    else:
        result = (asset.get("browser_download_url"),
                  asset.get("name") or "download.bin", None)
    _asset_cache[repo] = result
    return result


def resolve_target(resource: dict):
    """决定一个资源怎么部署，返回 {"kind", "url", "filename", "error"}
    kind：direct 直链 / github 最新 release 安装包 / page 打开官网页面 / unknown。
    """
    if not resource:
        return {"kind": "unknown", "url": "", "filename": "", "error": "资源库里没有这个编码"}

    direct = str(resource.get("download_url") or "").strip()
    if direct.startswith(("http://", "https://")):
        name = os.path.basename(urllib.parse.urlparse(direct).path) or \
            f"{resource.get('id', 'download')}.bin"
        return {"kind": "direct", "url": direct, "filename": name, "error": None}

    github = str(resource.get("github") or "").strip()
    if github:
        url, filename, err = resolve_github_asset(github)
        if url:
            return {"kind": "github", "url": url, "filename": filename, "error": None}
        page = str(resource.get("url") or github).strip()
        return {"kind": "page", "url": page, "filename": "", "error": err}

    page = str(resource.get("url") or "").strip()
    if page:
        return {"kind": "page", "url": page, "filename": "", "error": None}
    return {"kind": "unknown", "url": "", "filename": "", "error": "该资源没有可用地址"}


def safe_filename(name: str, fallback: str = "download.bin") -> str:
    """去掉文件名里的非法字符"""
    name = re.sub(r'[\\/:*?"<>|]+', "_", str(name or "").strip())
    return name or fallback


class DownloadWorker(QThread):
    """带进度 / 限速 / 可取消的下载线程"""

    progressed = pyqtSignal(int, int)     # 已下载字节, 总字节（未知时为 0）
    succeeded = pyqtSignal(str)           # 保存路径
    failed = pyqtSignal(str)

    CHUNK = 64 * 1024

    def __init__(self, url: str, dest_path: str, speed_limit_mb: float = 0, parent=None):
        super().__init__(parent)
        self.url = url
        self.dest_path = dest_path
        self.speed_limit_mb = float(speed_limit_mb or 0)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        tmp_path = self.dest_path + ".part"
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.dest_path)), exist_ok=True)
            with _open(self.url) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                received = 0
                started = time.time()
                limit_bytes = self.speed_limit_mb * 1024 * 1024 if self.speed_limit_mb > 0 else 0
                with open(tmp_path, "wb") as f:
                    while True:
                        if self._cancelled:
                            raise RuntimeError("已取消")
                        chunk = resp.read(self.CHUNK)
                        if not chunk:
                            break
                        f.write(chunk)
                        received += len(chunk)
                        self.progressed.emit(received, total)

                        # 限速：按平均速率补齐差距（分片 sleep，保证取消能及时响应）
                        if limit_bytes > 0:
                            while not self._cancelled:
                                expected = received / limit_bytes
                                remaining = expected - (time.time() - started)
                                if remaining <= 0:
                                    break
                                time.sleep(min(0.2, remaining))

            if os.path.exists(self.dest_path):
                os.remove(self.dest_path)
            os.rename(tmp_path, self.dest_path)
            self.succeeded.emit(self.dest_path)
        except Exception as e:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            if self._cancelled:
                self.failed.emit("已取消")
            else:
                self.failed.emit(str(e))
