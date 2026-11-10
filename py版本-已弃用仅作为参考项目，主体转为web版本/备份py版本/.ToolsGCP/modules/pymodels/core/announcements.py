"""公告：直接从仓库的 GitHub Issue 拉取（打了「公告」标签的 Issue 就是一条公告）。

⚠️ 必须过滤成只看作者本人发的（user.login == Galen563 或 author_association == OWNER）：
Issue 是公开的，谁都能开一条带「公告」标签的 Issue，不过滤就等于把"向全体用户推消息"
的能力送给任何人。

已读状态和内容缓存在 .ToolsGCP/config/announcements.json，和设置互不相干；
删掉这一个 json 就能全部变未读、重新弹窗。错误只抛机器码（ERR_*），文案由界面查语言。
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from PyQt5.QtCore import QThread, pyqtSignal

from ..constants import (ANNOUNCEMENTS_API, ANNOUNCEMENTS_LABEL,
                         ANNOUNCEMENTS_OWNER, ANNOUNCEMENTS_OWNER_ASSOCIATION,
                         APP_REPO, DATA_DIR, GITHUB_MIRRORS)

USER_AGENT = "ToolsGCP-Announcements/1.0"
API_TIMEOUT = 15.0
# 先试官方直连，靠前那几个源用短超时，免得官方被墙时每次都要干等满 15 秒
EARLY_TIMEOUT = 6.0
PER_PAGE = 100                 # GitHub 单页上限；公告不会有几百条，一页足够
# 已读 id 最多留多少条（防止这个状态文件无上限地长大）
MAX_READ_IDS = 800

# 错误"机器码"（和 updater 一个口径：只抛码，不抛中文）
ERR_NETWORK = "NETWORK"
ERR_BAD_RESPONSE = "BAD_RESPONSE"
ERR_RATE_LIMITED = "RATE_LIMITED"
ERR_REPO_NOT_FOUND = "REPO_NOT_FOUND"


# ==========================================================================
# 一、网络
# ==========================================================================

def _open(url, timeout=API_TIMEOUT, accept="application/vnd.github+json"):
    """发一个 GET 请求（关掉缓存，保证每次真回源）"""
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Cache-Control": "no-cache, no-store, max-age=0",
        "Pragma": "no-cache",
    })
    return urllib.request.urlopen(request, timeout=timeout)


def _mirror_of(source):
    """设置里的「搜索源」→ 镜像域名；不是白名单里的（含 "Github"/空）返回 "" """
    source = str(source or "").strip()
    return source if source in GITHUB_MIRRORS else ""


def build_announcement_urls(repo=APP_REPO, label=ANNOUNCEMENTS_LABEL,
                            search_source=""):
    """候选 API 地址：官方直连优先，镜像兜底（镜像有缓存，会让人看到旧公告）"""
    direct = ANNOUNCEMENTS_API.format(repo=repo)
    urls = [direct]
    mirror = _mirror_of(search_source)
    if mirror:
        urls.append(f"https://{mirror}/{direct}")
    return urls


def _fetch_one(url, timeout, label, per_page=PER_PAGE):
    """拉一页 Issue 并原样返回 list；失败抛 RuntimeError(错误码)"""
    params = [
        f"labels={urllib.parse.quote(str(label))}",
        "state=open",
        "sort=created",
        "direction=desc",
        f"per_page={int(per_page)}",
        f"_={int(time.time() * 1000)}",        # 破缓存：镜像站按整个 URL 做缓存键
    ]
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


# ==========================================================================
# 二、过滤 / 归一化
# ==========================================================================
def issue_author(raw):
    """Issue 作者的登录名（拿不到返回 ""）"""
    return str(((raw or {}).get("user") or {}).get("login") or "").strip()


def is_owner_issue(raw, owner=ANNOUNCEMENTS_OWNER):
    """这条 Issue 是不是"作者本人发的"（user.login == owner 或 author_association == OWNER）
    ⚠️ 顺带排掉 Pull Request：issues 接口会把 PR 混在列表里。"""
    raw = raw or {}
    if raw.get("pull_request"):
        return False
    association = str(raw.get("author_association") or "").strip().upper()
    if association == str(ANNOUNCEMENTS_OWNER_ASSOCIATION or "OWNER").upper():
        return True
    return issue_author(raw).lower() == str(owner or "").strip().lower()


def _to_local_text(value):
    """ISO 时间（GitHub 给的是 UTC）→ "YYYY-MM-DD HH:MM"（本地时区）

    解析不了就原样返回（不猜、不丢）。
    """
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
        parsed = parsed.replace(tzinfo=timezone.utc).astimezone()
        return parsed.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return parsed.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return text


# ---- markdown → 人能直接读的纯文本（不引入 markdown 渲染库）----

_CODE_FENCE_RE = re.compile(r"^\s*```.*$", re.M)
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_QUOTE_RE = re.compile(r"^\s{0,3}>\s?", re.M)
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+", re.M)
_RULE_RE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$", re.M)
_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")


def markdown_to_text(text):
    """把 Issue 正文（markdown）擦成人能直接读的纯文本

    去标题井号 / 粗体星号、`[文字](链接)` → `文字 (链接)`、列表符号换圆点、
    代码块围栏删掉但保留内容、HTML 标签去掉。
    """
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return ""
    text = _CODE_FENCE_RE.sub("", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = _IMAGE_RE.sub(lambda m: (m.group(1) or "").strip(), text)
    text = _LINK_RE.sub(r"\1 (\2)", text)
    text = _HEADING_RE.sub("", text)
    text = _QUOTE_RE.sub("", text)
    text = _BULLET_RE.sub(r"\1• ", text)
    text = _RULE_RE.sub("──────────", text)
    text = _HTML_TAG_RE.sub("", text)
    text = text.replace("**", "").replace("__", "")
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_issue(raw):
    """把 GitHub 的 Issue 压成界面要用的形状（缺字段一律给安全默认值）"""
    raw = raw or {}
    try:
        number = int(raw.get("number") or 0)
    except Exception:
        number = 0
    try:
        issue_id = int(raw.get("id") or 0)
    except Exception:
        issue_id = 0
    created = str(raw.get("created_at") or "")
    return {
        "id": issue_id or number,          # id 拿不到就退化成 number，够唯一了
        "number": number,
        "title": str(raw.get("title") or "").strip(),
        "body": markdown_to_text(raw.get("body")),
        "author": issue_author(raw),
        "url": str(raw.get("html_url") or ""),
        "created_at": created,
        "updated_at": str(raw.get("updated_at") or ""),
        "date": _to_local_text(created) or _to_local_text(raw.get("updated_at")),
    }


def extract_announcements(raw_list, owner=ANNOUNCEMENTS_OWNER):
    """过滤 + 归一化 + 去重 + 按时间新→旧排序"""
    items = []
    seen = set()
    for raw in (raw_list or []):
        if not isinstance(raw, dict):
            continue
        if not is_owner_issue(raw, owner):
            continue
        item = normalize_issue(raw)
        # ⚠️ 标题是公告的必备项：没标题的 Issue 渲染出来是张不知在说什么的卡片，跳过
        if not item["title"]:
            continue
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        items.append(item)
    items.sort(key=lambda it: (str(it.get("created_at") or ""), it.get("number") or 0),
               reverse=True)
    return items


def fetch_announcements(repo=APP_REPO, label=ANNOUNCEMENTS_LABEL, sources=None,
                        timeout=API_TIMEOUT, owner=ANNOUNCEMENTS_OWNER,
                        per_page=PER_PAGE):
    """拉取公告：候选地址依次尝试，返回已过滤的公告列表

    失败抛 RuntimeError(错误码)。"仓库不存在""被限流"换源也一样，所以直接抛；
    只有网络类失败才换下一个源重试。
    """
    urls = list(sources) if sources else [ANNOUNCEMENTS_API.format(repo=repo)]
    last_error = ERR_NETWORK
    for index, url in enumerate(urls):
        is_last = (index == len(urls) - 1)
        attempt_timeout = timeout if is_last else min(EARLY_TIMEOUT, timeout)
        try:
            raw_list = _fetch_one(url, attempt_timeout, label, per_page)
        except RuntimeError as exc:
            last_error = str(exc)
            if last_error in (ERR_REPO_NOT_FOUND, ERR_RATE_LIMITED):
                raise
            continue
        return extract_announcements(raw_list, owner)
    raise RuntimeError(last_error)


# ==========================================================================
# 三、本地状态：已读 id + 内容缓存
# ==========================================================================

STORE_FILENAME = "announcements.json"
# 状态文件的格式版本：以后改结构时可以据此迁移（现在只写不读，够用）
STATE_VERSION = 1
# 写给"打开这个文件的人"看的一句话（放在 json 里，用户一眼就知道能不能删）
STORE_NOTE = ("ToolsGCP 公告的本地状态：read_ids=已读的公告 id、"
              "items=上次拉到的公告缓存。删掉本文件 = 所有公告重新变未读"
              "（下次启动会重新弹窗），不影响任何设置。")


class AnnouncementStore:
    """公告的本地状态（.ToolsGCP/config/announcements.json）；和 toolsgcp_config.json
    完全无关，要重置公告状态删这一个 json 就够。"""

    def __init__(self, data_dir=None, filename=STORE_FILENAME):
        self.path = os.path.join(data_dir or DATA_DIR, filename)
        self.items = []
        self.read_ids = []
        self.updated_at = 0
        self.load()

    # ---------- 读写 ----------

    def load(self):
        """读状态文件；文件坏了 / 不存在都只是"没有状态"，绝不抛异常"""
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            return
        if not isinstance(data, dict):
            return
        items = []
        for item in (data.get("items") or []):
            if isinstance(item, dict) and (item.get("title") or item.get("body")):
                items.append(item)
        self.items = items
        ids = []
        for value in (data.get("read_ids") or []):
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
        self.read_ids = ids[-MAX_READ_IDS:]
        try:
            self.updated_at = int(data.get("updated_at") or 0)
        except (TypeError, ValueError):
            self.updated_at = 0

    def save(self):
        """原子落盘（先写 .tmp 再替换，中途断电不会留半截文件）"""
        payload = {
            "version": STATE_VERSION,
            "note": STORE_NOTE,
            "read_ids": self.read_ids[-MAX_READ_IDS:],
            "items": self.items,
            "updated_at": self.updated_at or int(time.time()),
        }
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            # ⚠️ 自检脚本不该改用户真实状态（和 settings_manager 一个约定）
            if os.environ.get("TOOLSGCP_NO_SETTINGS_WRITE"):
                return
            temp = self.path + ".tmp"
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(temp, self.path)
        except Exception as exc:
            _log_warn(f"保存公告状态失败: {exc}")

    # ---------- 内容 ----------

    def update_items(self, items):
        """把刚拉到的公告换成新的缓存并落盘"""
        self.items = [item for item in (items or []) if isinstance(item, dict)]
        self.updated_at = int(time.time())
        self.save()

    # ---------- 已读 ----------

    def is_read(self, item_id):
        try:
            return int(item_id) in self.read_ids
        except (TypeError, ValueError):
            return False

    def unread_items(self):
        """还没读过的公告（新→旧，和 items 同序）"""
        return [item for item in self.items if not self.is_read(item.get("id"))]

    def unread_count(self):
        return len(self.unread_items())

    def mark_all_read(self, items=None):
        """把（当前这批）公告全标成已读；返回这一次新增了几条

    只往 read_ids 追加、不删除：记住"读过什么"才不会因为公告暂时不在列表里又变未读。
    """
        targets = self.items if items is None else list(items)
        known = set(self.read_ids)
        added = 0
        for item in targets:
            try:
                item_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            if item_id in known:
                continue
            known.add(item_id)
            self.read_ids.append(item_id)
            added += 1
        if len(self.read_ids) > MAX_READ_IDS:
            self.read_ids = self.read_ids[-MAX_READ_IDS:]
        if added:
            self.save()
        return added

    def reset(self):
        """把公告状态清空（全部重新变未读、缓存也丢掉）；界面没挂按钮，给自检脚本用"""
        self.items = []
        self.read_ids = []
        self.updated_at = 0
        self.save()


# ==========================================================================
# 四、弹窗判定（纯函数，界面和自检脚本共用同一份逻辑）
# ==========================================================================

def popup_pending(unread_items, popped_ids):
    """从"未读公告"里挑出这个会话还没弹过的那几个（保持新→旧顺序）

    ⚠️ 这是"要不要弹公告窗"的唯一判定处（ui/main_window.py 直接调它）。
    按 id 挑：刷新拉到的新公告照样弹，同一条在同一会话里不重复弹，popped_ids 只在内存里。
    """
    popped = set()
    for value in (popped_ids or ()):
        try:
            popped.add(int(value))
        except (TypeError, ValueError):
            continue
    pending = []
    for item in (unread_items or []):
        if not isinstance(item, dict):
            continue
        try:
            item_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if item_id in popped:
            continue
        pending.append(item)
    return pending


# ==========================================================================
# 五、后台拉取线程
# ==========================================================================

class AnnouncementFetchWorker(QThread):
    """后台拉公告（网络绝不能跑在 UI 线程上，否则界面直接假死）"""

    fetched = pyqtSignal(list)     # 已过滤的公告列表
    failed = pyqtSignal(str)       # 错误码，见 ERR_*

    def __init__(self, search_source="", repo=APP_REPO,
                 label=ANNOUNCEMENTS_LABEL, owner=ANNOUNCEMENTS_OWNER, parent=None):
        super().__init__(parent)
        self.search_source = str(search_source or "")
        self.repo = repo
        self.label = label
        self.owner = owner

    def run(self):
        try:
            items = fetch_announcements(
                repo=self.repo, label=self.label, owner=self.owner,
                sources=build_announcement_urls(self.repo, self.label,
                                                self.search_source))
        except RuntimeError as exc:
            self.failed.emit(str(exc))
            return
        except Exception:
            self.failed.emit(ERR_NETWORK)
            return
        self.fetched.emit(items)


# ---------- 日志（延迟导入，避免成环） ----------

def _log_warn(message):
    try:
        from ..utils.logger import log
        log.warn("公告", "announcement", message)
    except Exception:
        pass


def log_announcements(count, unread):
    """拉取结果记一条 OP 日志，方便事后排查"为什么没弹窗" """
    try:
        from ..utils.logger import log
        log.op("公告", "fetch", count=count, unread=unread)
    except Exception:
        pass
