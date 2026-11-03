r"""公告：直接从仓库的 GitHub Issue 拉取（打了公告标签的 Issue 就是一条公告）。
⚠️ 必须过滤成只看作者本人发的（user.login == Galen563 或 author_association == OWNER）：
Issue 是公开的，谁都能开一条带公告标签的 Issue，不过滤就等于把"向全体用户推消息"
的能力送给任何人。
已读状态和内容缓存都在**当前数据根**的 config/ 下：
    `<数据根>/config/announcements.json`
    默认 = `<用户主目录>\.ToolsGCP\config\announcements.json`
（数据根由 core/data_root.py 按 `%USERPROFILE%\ToolsGCP.json` 指针解析；改了存储位置就跟到新根。）
⚠️ 删掉整个数据根、或只删这个 json ⇒ read_ids 清空 ⇒ 所有公告**重新未读**、下次启动重新弹窗。
   程序目录旁 `.ToolsGCP` 是资源目录，里面的旧 announcements.json 备份**不会**被反向迁移
   搬回来（data_root._REVERSE_SKIP_FILES）——这条是修过的真实 bug（删了数据根仍显示已读）。
⚠️ **删什么会重置 / 删什么不会**（用户反馈"删了 .ToolsGCP 还是已读"，写清楚免得再问）
    · 删 `<用户主目录>\.ToolsGCP`（设置 → 存储里显示的那个）       ⇒ 重置 ✔
    · 只删 `<数据根>\config\announcements.json`                    ⇒ 重置 ✔
    · 运行期间删上面任意一个（程序不关）                            ⇒ 重置 ✔
      （`_reset_if_state_file_vanished`：文件没了就不许把内存里的 read_ids 写回去）
    · 删**程序目录旁**的 `.ToolsGCP`（随程序发布的那份：modules/images/资源库）
      ⇒ **不会**重置，而且那不是数据根；删了程序就跑不起来了
    · 清前端 localStorage / 换 WebView2 配置                        ⇒ 不影响 ✔
      （已读状态只认磁盘；pywebview 默认 private_mode，localStorage 本来也不跨会话）
和设置（toolsgcp_config.json）互不相干。错误只抛机器码（ERR_*），文案由界面查语言。
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ⚠️ 本文件**现在是纯标准库模块**：以前这里有一段 try-import
#    `from PyQt5.QtCore import QThread, pyqtSignal`（只为一个 Web 版从不使用的
#    QThread 后台类）。那段 import 去掉后，本模块主线程加载不再碰 Qt，
#    这也是"从 dependencies 里删掉 PyQt5"的关键一步。
#    ⚠️ 别再往本文件加 Qt import：主线程 import 过 PyQt5 会让进程退出崩 0xC0000005
#       （见 desktop/splash.py 的长注释），而本模块是 Web 外壳启动链路必经的。

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
    """设置里的搜索源→ 镜像域名；不是白名单里的（含 "Github"/空）返回 "" """
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
STORE_NOTE = ("ToolsGCP 公告的本地状态：read_ids=已读的公告 id（GitHub issue 的**编号**，"
              "即 #1 / #2 那种）、items=上次拉到的公告缓存。本文件位于 <数据根>/config/（默认 "
              "%USERPROFILE%\\.ToolsGCP\\config\\announcements.json）。"
              "删掉本文件或整个数据根 = 所有公告重新变未读（下次启动会重新弹窗），"
              "不影响任何设置。")

# ⚠️ items 里**只存 id / number / created_at / updated_at** 这几个字段
#    · title / body 是**公告正文** —— 界面上的标题和内容是前端从 GitHub 实时拉的
#      （AnnouncementDomain.sync_items → store.update_items），本地再存一份纯属浪费；
#      而且 body 可能很长，存进配置文件既臃肿又没意义。
#    · 剩下的字段够判"读没读过"了：已读判定用 _key_of()（优先 number、其次 id），
#      number 就是 GitHub issue 的编号（#1 / #2），id 是数据库主键（老文件兼容用）。
#    · 白名单式（而不是黑名单式）：以后新增字段默认**不落盘**，不会又漏进正文。
def _strip_body(item):
    """把一条公告裁成"可以安全落盘"的形状（去掉 title / body 等正文）
    ⚠️ 只保留 id / number / created_at / updated_at —— 已读判定只需要 number。
       title / body 一律丢掉（哪怕老文件里有，读进来也直接扔）。
    """
    if not isinstance(item, dict):
        return {}
    result = {}
    for key in ("id", "number", "created_at", "updated_at"):
        value = item.get(key)
        if value is None or value == "":
            continue
        result[key] = value
    return result


class AnnouncementStore:
    """公告的本地状态（`<当前数据根>/config/announcements.json`，默认
    `<用户主目录>\\.ToolsGCP\\config\\announcements.json`）；和 toolsgcp_config.json
    完全无关。删掉这个 json（或整个数据根）= 所有公告重新未读，下次启动重新弹窗。
    ⚠️ 状态只认当前数据根上的文件：反向迁移（程序目录 → 用户主目录）不会把它带回来，
       所以"删了数据根"之后一定是全新未读（data_root._REVERSE_SKIP_FILES）。
    """

    def __init__(self, data_dir=None, filename=STORE_FILENAME):
        self.path = os.path.join(data_dir or DATA_DIR, filename)
        # 内容缓存（**带标题正文**）：接口返回给前端渲染列表用。
        # ⚠️ 正文不再落盘 ⇒ 从磁盘读回来的条目只有 id/number，
        #    那种条目**不能**当内容缓存（前端会拿它渲染出空白的公告页）。
        self.items = []
        # 已知公告的 id/number 索引（**不带正文**）：落盘的就是它。
        # ⚠️ 为什么要有它：落盘不存正文后，"读过哪些"只能靠这些编号来判断；
        #    前端点全部已读时后端要靠它把编号写进 read_ids。
        self.known = []
        self.read_ids = []
        self.updated_at = 0
        # 记住"载入这一刻状态文件在不在" —— 用来发现"程序运行期间用户把数据根删了"
        #      （见 `_reset_if_state_file_vanished`，这是"删了 .ToolsGCP 还是已读"的另一条路径）。
        self._existed_at_load = os.path.isfile(self.path)
        self.load()
        # 启动时把"状态文件到底在哪、已读几条"记一条日志：
        # 用户反馈"我删了 .ToolsGCP 公告还是已读"时，这条日志能立刻说明他删错了目录。
        try:
            from ..utils.logger import log
            log.info("公告", "store",
                     f"公告已读状态文件: {self.path}"
                     f"（已读 {len(self.read_ids)} 条 / 缓存 {len(self.items)} 条）")
        except Exception:
            pass

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
        known = []
        for item in (data.get("items") or []):
            # ⚠️ 以前只认有 title 或 body的条目 —— 那是"缓存里有正文"的旧格式。
            #    现在落盘时**不再存正文**（用户要求），新文件里的条目只有 id/number，
            #    用老条件判断会把它们**全丢掉** → 读回来 items 空了 → 已读判定失灵。
            #    → 改成有 title/body（老格式）**或**有 number/id（新格式）都收。
            if not isinstance(item, dict):
                continue
            if not (item.get("title") or item.get("body")
                    or item.get("number") or item.get("id")):
                continue
            known.append(_strip_body(item))
            # ⚠️ 只有**带正文**的条目才算"内容缓存" ——
            #    前端 `loadNotices()` 是store.items 非空 → 直接用它渲染，不去拉 GitHub，
            #    把"只有编号的条目"塞进去 → 公告页标题/正文会**全空白**。
            if item.get("title") or item.get("body"):
                items.append(item)
        self.items = items
        self.known = known
        ids = []
        for value in (data.get("read_ids") or []):
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
        self.read_ids = ids[-MAX_READ_IDS:]
        # ⚠️ 老文件里 read_ids 存的是 GitHub 的**数据库 id**，
        #    新约定是**编号**（#1/#2）。这里做一次性迁移：把 items 里
        #    "数据库 id → 编号"的对应关系套上去，老用户的已读状态不会丢。
        #    ⚠️ 对应关系要从 **known**（编号索引）里取 ——
        #    老文件的 items 带正文会被收进 self.items，新格式只有编号会进 known，
        #    两个都要算进去。
        if ids:
            mapping = {}
            for item in list(self.items or []) + list(self.known or []):
                try:
                    db_id = int(item.get("id"))
                    number = int(item.get("number"))
                except (TypeError, ValueError):
                    continue
                if db_id and number:
                    mapping[db_id] = number
            if mapping:
                migrated = [mapping.get(value, value) for value in self.read_ids]
                if migrated != self.read_ids:
                    self.read_ids = migrated[-MAX_READ_IDS:]
        try:
            self.updated_at = int(data.get("updated_at") or 0)
        except (TypeError, ValueError):
            self.updated_at = 0

    def save(self):
        """原子落盘（先写 .tmp 再替换，中途断电不会留半截文件）"""
        # 兜底：写之前再确认一次"用户运行期间有没有把状态删掉"，
        # 否则会把内存里的旧 read_ids 又写回去（= 已读复活）。
        self._reset_if_state_file_vanished()
        payload = {
            "version": STATE_VERSION,
            "note": STORE_NOTE,
            "read_ids": self.read_ids[-MAX_READ_IDS:],
            # ⚠️ 落盘时**去掉 title / body**。
            #    内存里的 self.items 仍带正文 —— 那是接口要返回给前端的
            #    （announcements.list 拿它渲染列表）。
            #    落盘的是"编号索引"：self.known（已知有哪些公告）+ self.items 里新拉的。
            #    只存 id/number 足够判"读没读过"，正文每次从 GitHub 实时拉。
            "items": self._items_for_disk(),
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
            self._existed_at_load = True
        except Exception as exc:
            _log_warn(f"保存公告状态失败: {exc}")

    def _items_for_disk(self) -> list:
        """落盘用的"编号索引"（**永远不含 title / body**）
        ⚠️ config 配置中的 announcements.json 不要存储 title 和 body。
           这里把两个来源合并去重：
             · self.known  —— 启动时从磁盘读回来的编号索引（老文件迁移过来的）；
             · self.items  —— 本次运行新拉到的公告（带正文，落盘时剥掉正文）。
           两者都是 dict，最后统一过一遍 _strip_body（白名单）。
        """
        merged = []
        seen = set()
        for source in (self.known or [], self.items or []):
            for item in source:
                if not isinstance(item, dict):
                    continue
                stripped = _strip_body(item)
                if not stripped:
                    continue
                key = (str(stripped.get("number") or ""), str(stripped.get("id") or ""))
                if key in seen:
                    continue
                seen.add(key)
                merged.append(stripped)
        return merged

    def _reset_if_state_file_vanished(self) -> bool:
        """状态文件"载入时在、现在没了" → 当成用户删了数据根，就地重置已读状态
        为什么需要它：删掉数据根后，公告的已读状态必须跟着重置并重新推送。
        删数据根这条路径在启动时已经正确（read_ids 读不到 = 全部未读），
        但如果用户是在**程序运行期间**删的，内存里的 read_ids 会在下一次 `save()` 时被原样
        写回去，看起来就是"删了也没用"。这里让"文件消失"这个事实优先于内存状态。
        返回 True 表示这次发生了重置。
        """
        if not self._existed_at_load:
            return False
        try:
            if os.path.exists(self.path):
                return False
        except Exception:
            return False
        self.items = []
        self.known = []
        self.read_ids = []
        self.updated_at = 0
        self._existed_at_load = False
        _log_warn(f"公告状态文件已被删除（{self.path}）→ 已读状态重置，所有公告重新未读")
        return True

    # ---------- 内容 ----------

    def update_items(self, items):
        """把刚拉到的公告换成新的缓存并落盘"""
        # 先看"文件还在不在"：被删过就先清空已读，再写入这次新拉的内容
        self._reset_if_state_file_vanished()
        self.items = [item for item in (items or []) if isinstance(item, dict)]
        # ⚠️ 编号索引也跟着更新（落盘的 items = known + 新拉的，去重、剥正文）
        self.known = [dict(item) for item in self.items]
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
        return [item for item in self.items if not self.is_read(self._key_of(item))]

    def unread_count(self):
        return len(self.unread_items())

    @staticmethod
    def _key_of(item):
        """一条公告的**唯一标识** = GitHub 的 issue **编号**（#1 / #2 …）
        ⚠️ 之前用的是 GitHub 的**数据库 id**（一串很大的数字，issue 的内部主键）。
           → 编号（number）才是**人类可读、跨仓库唯一、不会变**的那个标识；
             数据库 id 是 GitHub 内部主键，用户在界面上根本认不出来。
           ⚠️ 兼容老文件：老 read_ids 里存的是数据库 id —— 读的时候两种都认
              （老 id 仍然能对上已读状态），新写的统一用编号。
        """
        item = item or {}
        for key in ("number", "id"):
            try:
                value = int(item.get(key))
            except (TypeError, ValueError):
                continue
            if value:
                return value
        return 0

    def mark_all_read(self, items=None):
        """把（当前这批）公告全标成已读；返回这一次新增了几条
    只往 read_ids 追加、不删除：记住"读过什么"才不会因为公告暂时不在列表里又变未读。
    """
        # ⚠️ 必须先判"状态文件是不是被用户删了"：否则会把删掉之后自动重连的旧 read_ids
        #    又写回去（= 已读复活）。
        self._reset_if_state_file_vanished()
        # ⚠️ 正文不再落盘 ⇒ self.items 只在"本次运行拉到过内容"时才有值。
        #    点全部已读时如果 self.items 是空的（内容是前端从 GitHub 拉的、
        #    后端这边只有编号索引），那就**按编号索引 known** 来标 ——
        #    否则用户点了全部已读什么都没记下来（老 bug 的另一种表现）。
        if items is not None:
            targets = list(items)
        elif self.items:
            targets = list(self.items)
        else:
            targets = list(self.known or [])
        known = set(self.read_ids)
        # ⚠️ 老 read_ids 里存的是 GitHub 的**数据库 id**，新写的统一用**编号**（#1/#2）。
        #    这里把数据库 id也算进 known —— 否则老用户升级后所有公告会**重新变成未读**。
        legacy = set()
        for item in list(self.items or []) + list(self.known or []):
            try:
                legacy.add(int(item.get("id")))
            except (TypeError, ValueError):
                continue
        added = 0
        for item in targets:
            item_id = self._key_of(item)
            if not item_id:
                continue
            if item_id in known:
                continue
            try:
                if int(item.get("id")) in known:
                    continue          # 数据库 id 已在已读列表里（老文件）
            except (TypeError, ValueError):
                pass
            known.add(item_id)
            self.read_ids.append(item_id)
            added += 1
        if len(self.read_ids) > MAX_READ_IDS:
            self.read_ids = self.read_ids[-MAX_READ_IDS:]
        if added:
            self.save()
        return added

    def state_info(self):
        """状态文件的位置与概况（API / 自检 / 用户排查"已读为什么还在"用）"""
        try:
            exists = os.path.exists(self.path)
            size = os.path.getsize(self.path) if exists else 0
        except Exception:
            exists, size = False, 0
        return {"path": self.path, "exists": exists, "size": size,
                "read_count": len(self.read_ids), "item_count": len(self.items)}

    def reset(self):
        """把公告状态清空（全部重新变未读、缓存也丢掉）；界面没挂按钮，给自检脚本用"""
        self.items = []
        self.known = []
        self.read_ids = []
        self.updated_at = 0
        self._existed_at_load = False
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
# （已删除）五、后台拉取线程 AnnouncementFetchWorker
# ==========================================================================
# 这里原来有一个 QThread 版的后台拉取类（原版 Qt 界面用），配一段 try-import
# `from PyQt5.QtCore import QThread, pyqtSignal`。
# ⚠️ 删除原因：**Web 版从不用它**（全仓搜不到任何 `AnnouncementFetchWorker(` 调用，
#    Web 版走 desktop/api/__init__.py 的 AnnouncementDomain 纯函数 + 自己的线程），
#    而那段顶层 Qt import 是"主链路唯一还会去碰 PyQt5 的地方" —— 留着它，
#    PyQt5 就没法从依赖里彻底移除（打包体积也降不下来）。
#    Qt 依赖在这里去掉后，本文件成为**纯标准库模块**，
#    `_noqt` 自检（屏蔽 PyQt5 后跑整条主链路）已确认零命中。
# ==========================================================================


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
