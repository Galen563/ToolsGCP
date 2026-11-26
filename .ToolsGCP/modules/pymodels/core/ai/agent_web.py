# -*- coding: utf-8 -*-
"""Web 版 Agent 工具实现 —— 让那 31 个"手"在 pywebview 壳里真的能用。

========== 一、为什么需要这一层 ==========
core/ai/agent_tools.py 里的 31 个工具**全部是 PyQt5 版实现**：
    window.switchTo(...) / window.navigationInterface / window.searchInterface
    qfluentwidgets.InfoBar / QWidget.findChildren(...)
而 Web 版宿主（desktop/shell.py 的 Shell）**没有这些属性**，也没有 Qt。
所以 desktop/api/ai.py 的 _execute_tool() 以前只能放行 create_plugin / list_all_resources，
其余 29 个一律回"本轮不支持工具" —— 配置界面里那 31 个开关看着都有用，实际点了没用。

本模块用 **同一套工具名、同一套参数名** 重新实现一遍，只依赖 Shell 上真实存在的东西：
    shell.settings_manager / shell.favorites_manager / shell.language_manager
    shell.api.resources / shell.api.log / shell.api.shell / shell.api.hotkey
    shell.api.downloader / shell.api.plugins
    shell.push_event(...)   ← 要动界面时推事件给前端（协议见 app.js 的 agent.ui 监听器）
    shell.window            ← pywebview 窗口对象（minimize / toggle_maximize / …）

========== 二、两条硬约束（违反会直接搞崩主链路） ==========
1. **绝不 import PyQt5 / qfluentwidgets**（AGENTS.md 第 7 节：主线程 import 会让 WebView2 崩）。
2. **任何函数都不许抛**：公开函数一律 try/except 兜住，失败返回 {"ok": False, "error": ...}。
   工具链路上抛一次异常，模型只会看到一条干巴巴的 traceback，用户则看到"AI 不动了"。

========== 三、"要动界面"的工具怎么实现 ==========
Web 版的界面是前端 DOM，后端碰不到。约定：后端 push_event("agent.ui", {op, ...})，
前端 app.js 的 agent.ui 监听器落地（goto_page / open_resource / notify /
open_plugin_config / new_chat / set_theme / deploy_list）。需要回值的（deploy_list）
走 ai.agent_reply(reqId, payload) 回到本模块的等待表。
⚠️ 前端没实现某个 op 时**必须如实返回失败**，绝不能假装成功 ——
   AGENT_PROMPT_FOOTER 明令禁止模型"没调工具就说已经做了"，后端更不能替它撒谎。
"""

import os
import subprocess
import sys
import threading
import time
import uuid

# 这些工具都属于内置插件 gcp-ai-agent 这个"域"，开关一关就该整体下架。
# ⚠️ 必须和 agent_tools.AGENT_PLUGIN_SOURCE 保持一致（那边是权威定义）。
AGENT_SOURCE = "gcp-ai-agent"

# 等前端回值的默认超时（秒）。界面动作都是本地 DOM 操作，1.5 秒足够；
# 超时不卡死工具线程，直接如实报"界面没回应"。
REPLY_TIMEOUT = 1.5

# 一次工具结果里最多回多少字符（和 agent_tools.MAX_RESULT_CHARS 同口径）
MAX_TEXT = 20000


def _allowed_roots():
    """写盘/读文件允许的根目录：程序目录 + 主目录 + 桌面/下载/文档

    为什么要有白名单：AI 能自己决定路径，不设边界的话一次 write_file 就能覆盖
    用户任意位置的任意文件。宁可让它报"不在允许目录内"，也不能让它乱写。
    """
    roots = []
    try:
        from pymodels.constants import CONFIG_DIR
        roots.append(str(CONFIG_DIR))
    except Exception:
        pass
    try:
        home = os.path.expanduser("~")
        if home:
            roots.append(home)
            for name in ("Desktop", "Downloads", "Documents"):
                roots.append(os.path.join(home, name))
    except Exception:
        pass
    out = []
    for item in roots:
        try:
            real = os.path.realpath(item)
            if real and real not in out:
                out.append(real)
        except Exception:
            continue
    return out


def _within_allowed(path):
    """这个路径在允许根之内吗（用 realpath 比较，符号链接/junction 也算）"""
    try:
        real = os.path.realpath(str(path or ""))
    except Exception:
        return False
    if not real:
        return False
    for root in _allowed_roots():
        try:
            if os.path.normcase(real) == os.path.normcase(root):
                return True
            if os.path.normcase(real).startswith(os.path.normcase(root + os.sep)):
                return True
        except Exception:
            continue
    return False


# ======================================================================
# 运行上下文
# ======================================================================
class WebAgentContext:
    """把 Shell 上那些域对象包成一个"工具能用"的上下文

    为什么不让工具直接摸 shell：工具代码要到处 getattr 兜空，很容易漏；
    集中在这里之后，缺哪个域只会在一个地方退化（并且有默认值），工具本身干净。
    """

    def __init__(self, shell=None):
        self.shell = shell
        # 前端回值表：{req_id: payload}。工具线程 wait、js_api 线程 submit，
        # 所以**必须**用锁保护（跨线程唤醒最容易出的 bug 就是"等的人没被叫醒"）。
        self._replies = {}
        self._reply_lock = threading.Lock()

    # ---------- 拿域对象 ----------
    def _api(self, name):
        try:
            api = getattr(self.shell, "api", None)
            return getattr(api, name, None) if api is not None else None
        except Exception:
            return None

    def window(self):
        """pywebview 的窗口对象（最小化/最大化等走它）"""
        try:
            return getattr(self.shell, "window", None)
        except Exception:
            return None

    def settings(self):
        try:
            return getattr(self.shell, "settings_manager", None)
        except Exception:
            return None

    def favorites(self):
        try:
            return getattr(self.shell, "favorites_manager", None)
        except Exception:
            return None

    def language(self):
        try:
            return str(self.shell.current_language() or "")
        except Exception:
            return "简体中文"

    def locale(self):
        language = self.language()
        try:
            from .agent_tools import locale_of
            return locale_of(language)
        except Exception:
            return "zh_CN"

    def resources(self):
        """资源库清单（复用 ResourcesDomain 已经加载好的那份，不另 new loader）"""
        domain = self._api("resources")
        if domain is None:
            return []
        try:
            items = domain._all_items()
            return list(items) if items else []
        except Exception:
            return []

    def push_event(self, name, payload):
        try:
            self.shell.push_event(str(name), payload if isinstance(payload, dict) else {})
            return True
        except Exception:
            return False

    def log(self, level, message):
        try:
            from ...utils.logger import log
            method = level if level in ("info", "warn", "err", "op") else "info"
            getattr(log, method)("AI-Agent", "agent_web", str(message or "")[:400])
        except Exception:
            pass

    # ---------- 前端回值 ----------
    def new_request(self):
        return "u-" + uuid.uuid4().hex[:12]

    def submit_reply(self, req_id, payload):
        """前端调 ai.agent_reply 时进到这里（可能在另一个线程）"""
        key = str(req_id or "")
        if not key:
            return False
        with self._reply_lock:
            self._replies[key] = payload
        return True

    def wait_reply(self, req_id, timeout=REPLY_TIMEOUT):
        """等前端回值；超时返回 None（调用方据此如实报失败，不卡死）。

        ⚠️ 用轮询而不是 threading.Event：后端 agent_reply 可能在**任意** js_api 工作线程
           进来，而工具在另一个线程等；用 Event 要额外维护一张 id→Event 的表并处理
           "Event 先到、工具后等"的竞态。20ms 轮询在这个量级（≤3s）完全够，且不可能死锁。
        """
        key = str(req_id or "")
        if not key:
            return None
        deadline = time.time() + max(0.1, float(timeout or REPLY_TIMEOUT))
        while time.time() < deadline:
            with self._reply_lock:
                if key in self._replies:
                    return self._replies.pop(key)
            time.sleep(0.02)
        with self._reply_lock:
            return self._replies.pop(key, None)


# ======================================================================
# 小工具
# ======================================================================
def _ok(data=None, **kwargs):
    out = {"ok": True}
    if data is not None:
        out["data"] = data
    out.update(kwargs)
    return out


def _fail(message):
    return {"ok": False, "error": str(message or "未知错误")}


def _text(value, limit=MAX_TEXT):
    text = str(value if value is not None else "")
    return text[:limit]


def _categories_of(item):
    """取一条资源的类别列表（字段可能是 categories 也可能是 category，值可能是串或表）"""
    raw = item.get("categories")
    if raw is None:
        raw = item.get("category")
    if isinstance(raw, str):
        return [part.strip() for part in raw.replace("/", ",").split(",") if part.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


def _find_resource(ctx, key):
    """按编码 / id / 名称找一条资源（**多级匹配**，越靠前越精确）

    ⚠️⚠️ 修「资源库里没有 XXX」——用户实测的高频失败（Q5 确认是这条）。
    旧实现只有两级：编码完全相等、名称**完全相等**。而模型拿到的往往是用户的口语
    （"抠图"），资源名却是"抠图精灵" —— 完全相等永远匹配不上，于是每次收藏都
    回一句"资源库里没有 抠图"，用户看到的就是"AI 说了要干活但干不成"。

    现在按「精确 → 包含 → 关键词」三级匹配：
      ① 编码 / id 完全相等（大小写不敏感）—— 最高优先，不会误判；
      ② 名称完全相等；
      ③ 名称**包含**查询词（"抠图" ⊂ "抠图精灵"）；
      ④ 查询词包含名称（用户说得比资源名长："帮我找抠图精灵那个软件"）；
      ⑤ 关键词/标签命中（资源自带的 keywords 里可能有"抠图"）。
    命中多条时**取名称最短的**（通常是最贴近用户说的那个），避免"抠图"命中一堆。
    """
    needle = str(key or "").strip()
    if not needle:
        return None
    upper = needle.upper()
    lowered = needle.lower()
    items = [x for x in ctx.resources() if isinstance(x, dict)]
    if not items:
        return None

    # ① 编码 / id 精确
    for item in items:
        code = str(item.get("code") or item.get("id") or "").strip()
        if code.upper() == upper:
            return item

    # ② 名称精确
    for item in items:
        if str(item.get("name") or "").strip().lower() == lowered:
            return item

    # ③④⑤ 模糊匹配：收集候选，取名称最短的（最贴近用户说的那个）
    candidates = []
    for item in items:
        name = str(item.get("name") or "").strip()
        lname = name.lower()
        if not lname:
            continue
        hit = False
        if lowered in lname:            # ③ "抠图" ⊂ "抠图精灵"
            hit = True
        elif lname in lowered:          # ④ 用户说得更长
            hit = True
        else:
            # ⑤ 关键词/标签命中
            kws = item.get("keywords")
            if isinstance(kws, (list, tuple)):
                for kw in kws:
                    k = str(kw or "").strip().lower()
                    if k and (k in lowered or lowered in k):
                        hit = True
                        break
        if hit:
            candidates.append((len(name), name, item))
    if candidates:
        candidates.sort(key=lambda x: (x[0], x[1]))
        return candidates[0][2]
    return None


def find_resource_candidates(ctx, key, limit=5):
    """找**多个**候选（给"找不到"时的提示用：告诉模型/用户"你是想说这些吗"）"""
    needle = str(key or "").strip().lower()
    if not needle:
        return []
    out = []
    for item in ctx.resources():
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        # 只要有一个字相同就算候选（足够给提示用了，不必严格）
        if any(ch in name.lower() for ch in needle if ch.strip()):
            out.append(name)
        if len(out) >= limit:
            break
    return out

def _brief(item):
    """一条资源的紧凑描述（省 token：只给模型真用得上的字段）"""
    if not isinstance(item, dict):
        return {}
    return {
        "code": str(item.get("code") or item.get("id") or ""),
        "name": str(item.get("name") or ""),
        "category": "/".join(_categories_of(item)),
        "desc": _text(item.get("description") or item.get("summary") or "", 120),
        "url": _text(item.get("url") or item.get("download") or "", 200),
    }


def _full(item):
    """完整字段（去掉体积大又没用的，避免工具结果被 format_result 拦腰截断）"""
    out = dict(item) if isinstance(item, dict) else {}
    for key in ("icon", "icon_data", "raw", "html"):
        out.pop(key, None)
    for key in list(out.keys()):
        if isinstance(out[key], (list, dict)) and len(str(out[key])) > 400:
            out[key] = _text(str(out[key]), 400)
    return out


def _set_setting(ctx, key, value):
    """写设置（走 SettingsDomain.set，这样会广播 settings-changed + 触发插件资源同步）

    ⚠️⚠️ 本轮修复（用户原话：「我让 agent 改字体…结果我去查看它选中的还是原本的，
       效果却是其他字体」）：旧版这里取的是 `ctx._api("resources")` ——
       `set()` 挂在 **SettingsDomain**（api.settings，见 desktop/api/__init__.py 挂载表），
       ResourcesDomain 上没有这个方法，`domain.set(...)` 抛 AttributeError 被
       except 吞掉 → 每次都掉进兜底的 `manager.update_setting()`（只写盘、
       **不广播 settings-changed**）。于是 agent 改完：
         · 效果层：apply_appearance 事件把 settings 快照带回来 → 界面真的变了；
         · 数据层：设置页下拉框绑的是 draft[key]，只有 settings-changed 才回填 →
           下拉框永远显示旧值。正是"效果变了、选中项没变"的完整成因。
       改回正确域名后一切走正门：值变了就广播，前端 listener 同时回填
       settings 与 draft（app.js 14443 起），两端一致。
    """
    domain = ctx._api("settings")
    if domain is not None:
        try:
            result = domain.set(str(key), value)
            return bool(isinstance(result, dict) and result.get("ok"))
        except Exception:
            pass
    manager = ctx.settings()
    if manager is None:
        return False
    try:
        # 兜底（api.settings 不可用时才会到这里）：直写管理器，不广播。
        ctx.log("warn", "agent 写设置走了兜底路径（api.settings 不可用）: %s" % key)
        manager.update_setting(str(key), value)
        return True
    except Exception:
        return False


def _ui(ctx, op, **payload):
    """推一个界面动作给前端"""
    body = {"op": str(op)}
    body.update(payload)
    return {"ok": bool(ctx.push_event("agent.ui", body)), "op": op, "body": body}



# ======================================================================
# 工具实现（纯数据类）
# ======================================================================
def _tool_search(ctx, args):
    query = str(args.get("query") or args.get("q") or "").strip().lower()
    category = str(args.get("category") or "").strip().lower()
    try:
        limit = max(1, min(20, int(args.get("limit") or 8)))
    except (TypeError, ValueError):
        limit = 8
    hits = []
    for item in ctx.resources():
        if not isinstance(item, dict):
            continue
        if category and not any(category in c.lower() for c in _categories_of(item)):
            continue
        keywords = item.get("keywords")
        if isinstance(keywords, (list, tuple)):
            keyword_text = " ".join(str(x) for x in keywords)
        else:
            keyword_text = str(keywords or "")
        haystack = " ".join((
            str(item.get("name") or ""),
            keyword_text,
            str(item.get("description") or ""),
            str(item.get("code") or item.get("id") or ""),
        )).lower()
        if query and query not in haystack:
            continue
        hits.append(_brief(item))
        if len(hits) >= limit:
            break
    return _ok(count=len(hits), items=hits)


def _tool_get(ctx, args):
    raw = args.get("code") or args.get("id") or args.get("name") or ""
    item = _find_resource(ctx, raw)
    if item is None:
        near = find_resource_candidates(ctx, raw)
        hint = ("。你是想找：" + "、".join(near)) if near else ""
        return _fail("资源库里没有「%s」%s（可以先用 search_resources 查准确名称）"
                     % (raw, hint))
    return _ok(_full(item))


def _tool_open(ctx, args):
    code = str(args.get("code") or args.get("id") or "").strip()
    item = _find_resource(ctx, code)
    if item is None:
        return _fail("资源库里没有 %s" % code)
    real_code = str(item.get("code") or item.get("id") or code)
    result = _ui(ctx, "open_resource", code=real_code)
    if not result.get("ok"):
        return _fail("界面没能打开详情页（前端没连上）")
    return _ok("已在界面上打开「%s」的详情页" % (item.get("name") or real_code))


def _tool_stats(ctx, args):
    items = [x for x in ctx.resources() if isinstance(x, dict)]
    counter = {}
    for item in items:
        for name in _categories_of(item):
            counter[name] = counter.get(name, 0) + 1
    top = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    return _ok(total=len(items), categories=len(counter),
               top=["%s:%s" % (k, v) for k, v in top])


def _tool_list_all(ctx, args):
    items = [x for x in ctx.resources() if isinstance(x, dict)]
    try:
        offset = max(0, int(args.get("offset") or 0))
    except (TypeError, ValueError):
        offset = 0
    try:
        page_size = int(args.get("page_size") or 0)
    except (TypeError, ValueError):
        page_size = 0
    limit = page_size if page_size > 0 else 10
    page = []
    for index, item in enumerate(items[offset:offset + limit], start=offset + 1):
        brief = _brief(item)
        page.append({
            "no": index,
            "name": brief.get("name"),
            "code": brief.get("code"),
            "category": brief.get("category"),
            "desc": _text(brief.get("desc"), 24),
        })
    return _ok(total=len(items), offset=offset, returned=len(page),
               complete=offset + len(page) >= len(items), items=page)


# ======================================================================
# 工具实现（收藏）
# ======================================================================
def _refresh_favorites(ctx, action: str = "", **fields):
    """收藏变更后广播 `favorites-changed` —— **必须**调，否则界面不刷新

    ⚠️⚠️ 这是一个真实踩过的 bug（用户原话）：「我也不知道是什么我先去看了看收藏夹
       啥都没有 没任何变化」。而磁盘上 favorites.json 里 GCP 文件夹和 4 条资源
       **明明都在**。
       根因：`FavoritesDomain` 的所有写方法（add/remove/create_folder…）末尾都会
       `push_event("favorites-changed")`，前端靠它刷新收藏页与搜索结果
       （app.js 的 onEvent('favorites-changed') → loadFavorites + runQuery）。
       而 agent_web 是**直接调 manager.add()**（FavoritesManager 本身不发事件），
       等于绕过了那一层广播 —— 数据真的写进去了，界面却一直停在旧状态，
       用户看起来就是"什么都没发生"。
       所以：AI 动完收藏，必须走这里补发通知，和手动操作完全同一条链路。
    """
    try:
        payload = {"action": str(action or "ai")}
        payload.update(fields)
        ctx.push_event("favorites-changed", payload)
    except Exception:                                     # noqa: BLE001
        pass



def _tool_favorites(ctx, args):
    manager = ctx.favorites()
    if manager is None:
        return _fail("收藏功能不可用")
    try:
        folders = []
        for name in list(manager.folders())[:12]:
            codes = list(manager.folder_items(name))[:20]
            names = []
            for code in codes:
                item = _find_resource(ctx, code)
                names.append(str(item.get("name")) if item else str(code))
            folders.append({"folder": str(name), "count": manager.count(name), "items": names})
        return _ok(total=len(manager.all_codes()), folders=folders)
    except Exception as exc:
        return _fail("读取收藏夹失败: %s" % exc)


def _tool_favorite_set(ctx, args):
    manager = ctx.favorites()
    if manager is None:
        return _fail("收藏功能不可用")
    raw = args.get("code") or args.get("name") or args.get("id")
    item = _find_resource(ctx, raw)
    if item is None and str(raw or "").strip():
        # ⚠️ 找不到时**给出候选**，别只回一句"资源库里没有 X"：
        #    模型看到候选就能自己纠正并重试，用户不用手动查编码。
        near = find_resource_candidates(ctx, raw)
        hint = ("。你是想找：" + "、".join(near)) if near else ""
        return _fail("资源库里没有「%s」%s（可以先用 search_resources 查准确名称）"
                     % (raw, hint))
    code = str((item or {}).get("code") or (item or {}).get("id") or raw or "").strip()
    if not code:
        return _fail("缺少 code / name 参数（要哪条资源？给名称或编码都行）")
    on = args.get("on")
    on = True if on is None else bool(on)
    folder = str(args.get("folder") or "").strip()
    try:
        if on:
            if folder and folder not in manager.folders():
                manager.create_folder(folder)
            manager.add(code, folder or None)
            where = ("收藏夹「%s」" % folder) if folder else "收藏夹"
            text = "已把 %s 放进%s" % (code, where)
        else:
            manager.remove(code)
            text = "已把 %s 移出收藏" % code
        # ⚠️ 必须广播：否则收藏页/搜索结果不刷新，用户以为"没任何变化"
        _refresh_favorites(ctx, "set", code=code, folder=folder, on=on)
        return _ok({"result": text, "code": code, "folders": list(manager.folders())[:12]})
    except Exception as exc:
        return _fail("收藏操作失败: %s" % exc)


def _tool_favorite_folder(ctx, args):
    manager = ctx.favorites()
    if manager is None:
        return _fail("收藏功能不可用")
    name = str(args.get("name") or args.get("folder") or "").strip()
    if not name:
        return _fail("缺少 name 参数（收藏夹名称）")
    try:
        result = manager.create_folder(name)
        ok = result[0] if isinstance(result, tuple) else bool(result)
        if not ok:
            return _fail(str(result[1]) if isinstance(result, tuple) else "新建失败")
        moved = ""
        raw = args.get("code") or args.get("name_or_code")
        if raw:
            item = _find_resource(ctx, raw)
            code = str((item or {}).get("code") or (item or {}).get("id") or raw).strip()
            manager.add(code, name)
            moved = "，并把 %s 放了进去" % code
        # ⚠️ 必须广播：否则界面不会出现新建的收藏夹
        _refresh_favorites(ctx, "create_folder", folder=name)
        return _ok({"folder": name, "result": "已新建收藏夹「%s」%s" % (name, moved)})
    except Exception as exc:
        return _fail("新建收藏夹失败: %s" % exc)


def _tool_favorite_move(ctx, args):
    manager = ctx.favorites()
    if manager is None:
        return _fail("收藏功能不可用")
    raw = args.get("code") or args.get("name")
    item = _find_resource(ctx, raw)
    code = str((item or {}).get("code") or (item or {}).get("id") or raw or "").strip()
    folder = str(args.get("folder") or args.get("to") or "").strip()
    if not code:
        return _fail("缺少 code 参数")
    if not folder:
        return _fail("缺少 folder 参数（目标收藏夹名称）")
    try:
        if folder not in manager.folders():
            manager.create_folder(folder)
        current = manager.folder_of(code)
        if current == folder:
            return _ok("%s 本来就在「%s」里" % (code, folder))
        if current:
            manager.move(code, current, folder)
        else:
            manager.add(code, folder)
        _refresh_favorites(ctx, "move", code=code, to=folder)
        return _ok({"result": "已把 %s 从「%s」移到「%s」" % (code, current or "未收藏", folder),
                    "folders": list(manager.folders())[:12]})
    except Exception as exc:
        return _fail("移动收藏失败: %s" % exc)



# ======================================================================
# 工具实现（界面与导航 —— 全部走 agent.ui 事件）
# ======================================================================
def _tool_goto(ctx, args):
    page = str(args.get("page") or "").strip()
    if not page:
        return _fail("缺少 page 参数")
    if not _ui(ctx, "goto_page", page=page).get("ok"):
        return _fail("界面没能切换页面（前端没连上）")
    return _ok("已切换到「%s」页面" % page)


def _tool_notify(ctx, args):
    text = str(args.get("text") or "").strip()
    if not text:
        return _fail("缺少 text 参数")
    if not _ui(ctx, "notify", text=text, level=str(args.get("level") or "info")).get("ok"):
        return _fail("当前界面无法弹提示")
    return _ok("提示已显示给用户")


def _tool_search_view(ctx, args):
    applied = []
    card = str(args.get("card_size") or "").strip()
    if card:
        if card not in ("small", "medium", "large"):
            return _fail("card_size 只能是 small / medium / large")
        if _set_setting(ctx, "card_size", card):
            applied.append("card_size=%s" % card)
    view = str(args.get("view") or "").strip()
    if view:
        if view not in ("tile", "grid"):
            return _fail("view 只能是 tile / grid")
        if _set_setting(ctx, "view_mode", view):
            applied.append("view=%s" % view)
    if not applied:
        return _fail("没有给出要改的项（card_size / view）")
    return _ok("已调整搜索页外观：" + "、".join(applied))


def _tool_deploy_list(ctx, args):
    """需要前端回值：把当前部署清单变成 {items:[...]} 回给模型

    ⚠️ 前端没回值（老版本 / 界面在别的页）时**如实报失败**，不假装"清单是空的"——
       后者会让模型回答"部署清单里什么都没有"，用户看到的就是一句假话。
    """
    req_id = ctx.new_request()
    if not ctx.push_event("agent.ui", {"op": "deploy_list", "reqId": req_id}):
        return _fail("界面没有连接，拿不到部署清单")
    payload = ctx.wait_reply(req_id, REPLY_TIMEOUT * 2)
    if payload is None:
        return _fail("界面没有及时回应，读不到部署清单")
    if isinstance(payload, dict) and payload.get("ok") is False:
        return _fail(payload.get("error") or "界面拒绝了这次请求")
    items = payload.get("items") if isinstance(payload, dict) else None
    items = items if isinstance(items, list) else []
    return _ok(count=len(items), items=items[:20])


def _tool_set_window_state(ctx, args):
    action = str(args.get("action") or "").strip().lower()
    window = ctx.window()
    if window is None:
        return _fail("窗口还没准备好")
    mapping = {
        "minimize": "minimize", "min": "minimize", "最小化": "minimize",
        "maximize": "toggle_maximize", "最大化": "toggle_maximize",
        "toggle_maximize": "toggle_maximize",
        "fullscreen": "toggle_fullscreen", "全屏": "toggle_fullscreen",
        "toggle_fullscreen": "toggle_fullscreen",
        "hide": "hide_to_tray", "hide_to_tray": "hide_to_tray", "托盘": "hide_to_tray",
        "show": "show", "显示": "show",
    }
    method = mapping.get(action)
    if not method:
        return _fail("action 只能是 minimize / maximize / fullscreen / hide / show")
    try:
        getattr(window, method)()
        return _ok("窗口已执行：%s" % action)
    except Exception as exc:
        return _fail("窗口操作失败: %s" % exc)


def _tool_new_chat(ctx, args):
    if not _ui(ctx, "new_chat").get("ok"):
        return _fail("界面没能新建会话")
    return _ok("已开始一段新的 AI 对话")


# ======================================================================
# 工具实现（设置与外观）
# ======================================================================
# 键名的常见别名：模型经常把 key 写成 name / setting / item（不是用户在乱填，
# 而是对工具契约的合理误读）。入口统一归一，比让模型自己再试一轮更省 token。
_SETTING_KEY_ALIASES = ("key", "name", "setting", "setting_key", "key_name", "item")
_SETTING_META_KEYS = set(_SETTING_KEY_ALIASES) | {
    "value", "on", "off", "settings", "args", "arguments", "input",
    "parameters", "label", "tool", "tool_name",
}


def _setting_args(args):
    """把 set_setting / get_setting 的参数归一成 (key, value, batch)。

    用户报：「agent 执行恢复时，字体/配色 set_setting 报缺少 key 参数」。
    根因：模型常把 set_setting 当 update_settings 用（写成
    {"settings": {"字体": "..."}}），或把键名写成 name / setting / item，
    而旧实现只认 args["key"] —— 参数一到就判空、直接失败，
    组件本身其实完全能改（list_settings 里键名和可选值都在）。
    这里在工具入口兜住这些写法：
      · batch   —— 批量 {"键": 值}，调用方整批交给 update_settings；
      · key     —— 单个键名（可能是中文标签，交给调用方解析）；
      · value   —— 对应的值（value 缺失时退回 on，界面上"开关"类常用）。
    只在**认不出任何键名**时才返回空 key，让调用方报那句明确的错误。
    """
    if not isinstance(args, dict):
        return "", None, {}
    # ⚠️⚠️ 模型有时把**上一次工具结果的信封**当参数回灌（实测日志：
    #    「agent_tool 工具 set_setting ok=False args=[ok,data]」—— 参数键名成了 ok/data）。
    #    这种参数既没有 key 也没有 settings，下面两条规则都会落到"缺少 key 参数"，
    #    白白再失败一轮（用户报的"恢复时 2 步失败"就有它）。
    #    信封的形状 = {"ok": bool, "data"/"error": ...}；data 里往往**装着真正的参数**
    #    （上一次 list_settings 的结果、或上一次 set_setting 的 {"key":..,"value":..}）。
    #    这里把信封拆开看：data 是 dict 就当参数继续解析，data 里找得到设置键就用它。
    if "ok" in args and isinstance(args.get("data"), dict) and not any(
            k in args for k in _SETTING_KEY_ALIASES) and ("settings" not in args) and (
            "parameters" not in args):
        inner = args.get("data") or {}
        # 内层若是 {"key":..,"value":..} 这种单键形状 → 直接用
        inner_key = ""
        for name in _SETTING_KEY_ALIASES:
            raw = inner.get(name)
            if isinstance(raw, str) and raw.strip():
                inner_key = raw.strip()
                break
        if inner_key:
            return inner_key, inner.get("value"), {}
        # 内层若是 {"设置键": 值} 的批量形状 → 当批量。
        # ⚠️ 必须要求**值都是标量**：list_settings 的结果长这样
        #    {"settings": {...}, "groups": [...]}（值是嵌套 dict / 列表），
        #    那不是批量设置 —— 误当批量会把一堆分组名写进设置里。
        inner_keys = [k for k in inner.keys() if str(k) not in _SETTING_META_KEYS]
        if inner_keys and all(isinstance(inner.get(k), (str, int, float, bool))
                              for k in inner_keys):
            return "", None, {k: inner.get(k) for k in inner_keys}
    for name in ("settings", "parameters"):
        batch = args.get(name)
        if isinstance(batch, dict) and batch:
            return "", None, dict(batch)
    key = ""
    for name in _SETTING_KEY_ALIASES:
        raw = args.get(name)
        if isinstance(raw, str) and raw.strip():
            key = raw.strip()
            break
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            key = str(raw).strip()
            break
    value = args.get("value")
    if value is None and "on" in args:
        value = args.get("on")
    if key:
        return key, value, {}
    # 兜底：参数里只有一个"不像参数名"的键 → 把它当成设置键
    # （模型常直接写 {"主题": "深色主题"}，这是最省事也最常见的写法）
    candidates = [k for k in args.keys() if str(k) not in _SETTING_META_KEYS]
    if len(candidates) == 1:
        only = candidates[0]
        return str(only), args.get(only), {}
    return "", value, {}


def _tool_get_setting(ctx, args):
    """读一项设置（**只读项可以读、但不给敏感值**）

    ⚠️⚠️ 修「6 个失败」里那 4 个 get_setting：
    模型拿到 list_settings 的输出后，会去 get_setting 复查某个键。
    而旧实现只要"键不在 settings 里"就直接失败 —— 但模型常常是从
    list_settings 里**看到过**这个键（比如 readonly 分组里的），或拼错一个字母。
    现在：① 键不存在时给"你是想找这些吗"的候选；
          ② 敏感项**允许查询但回掩码值**（让模型知道"这项存在、但你看不到值"），
             而不是直接报错 —— 直接报错会让模型以为整个设置系统坏了，反复重试。
    """
    from . import setting_spec

    key, _value, _batch = _setting_args(args)
    if not key:
        return _fail("缺少 key 参数（要读哪一项？可以用 list_settings 看键名）")
    manager = ctx.settings()
    if manager is None:
        return _fail("设置不可用")
    # ⚠️ 先尝试把"人话"解析成键名（用户说"通知位置"，模型可能原样传进来）：
    #    这一行让 "通知位置" → toast_position，而不是去查一个不存在的键然后报错。
    #    这正是 AI 回"设置里根本没有通知位置这一项"的直接修复。
    # ⚠️ 先尝试把"人话"解析成键名（用户说"通知位置"，模型可能原样传进来）：
    #    这一行让 "通知位置" → toast_position，而不是去查一个不存在的键然后报错。
    #    这正是 AI 回"设置里根本没有通知位置这一项"的直接修复。
    if key not in manager.settings:
        _resolved = setting_spec.label_to_key(key)
        if _resolved and _resolved in manager.settings:
            key = _resolved
    try:
        if key not in manager.settings:
            needle = key.lower()
            near = [k for k in sorted(manager.settings)
                    if needle and needle in str(k).lower()][:8]
            # 再给一次"人话 -> 键"的提示（模型看到就能自己纠正）
            _by_label = setting_spec.label_to_key(key)
            if _by_label and _by_label not in near:
                near.insert(0, _by_label)
            hint = ("。你是想找：" + " / ".join(near)) if near else ""
            return _fail("没有名为 %s 的设置项%s（先用 list_settings 看有哪些键）"
                         % (key, hint))
        # 敏感项：能查到"存在"，但值必须掩码（日志/对话都不该出现明文 Key）
        try:
            from ...utils.logger import is_secret_key
            if is_secret_key(key):
                return _ok({key: "（已隐藏，这是敏感设置）"}, readonly=True)
        except Exception:                                 # noqa: BLE001
            pass
        if setting_spec.is_readonly(key):
            return _ok({key: manager.settings.get(key),
                        "label": setting_spec.key_label(key)}, readonly=True)
        item = {key: manager.settings.get(key)}
        _label = setting_spec.key_label(key)
        if _label:
            item["label"] = _label
        return _ok(item)
    except Exception as exc:
        return _fail("读取设置失败: %s" % exc)


def _tool_set_setting(ctx, args):
    """改一项设置（先查 setting_spec 再写，写完按 apply 提示让界面即时生效）

    用户原话（三个 bug 指向同一处）：
      「我希望是设置中的所有内容agent都可以动的了」
      「例如我让他切换主体它切换成功了但是并没有立即生效的bug必须重启一下」
      「我跟他说我喜欢毛玻璃让他切换她说没有直接执行失败」

    修复要点：
      ① 值域校验 + 中文别名：毛玻璃 → glass、深色 → 深色主题；
      ② 只读/敏感项挡住（api_key 改了用户就登不上服务商）；
      ③ 写完整合 apply 提示，让前端立刻重画（否则"要重启才看到"）。
    """
    from . import setting_spec

    key, value, batch = _setting_args(args)
    if batch:
        # 模型把 set_setting 当 update_settings 用了：整批转交，
        # 别让它因为一个参数名错误就白失败一轮（用户报的"2 步失败"就是这种）
        return _tool_update_settings(ctx, {"settings": batch})
    if not key:
        # ⚠️ 工具结果信封回灌（{"ok":..,"data":..}）单独给一句人话错误：
        #    上面的 _setting_args 已经把能救的救了（data 里带着真参数），
        #    到这里说明 data 里也没有可用的设置键 —— 明确告诉模型"别把结果当参数回灌"。
        if isinstance(args, dict) and "ok" in args:
            return _fail("参数看起来是**上一次工具结果的信封**（里面有 ok/data），"
                         "而不是设置项。请重新调用并给出 key 与 value 两个参数")
        return _fail("缺少 key 参数（要改哪一项？先用 list_settings 看键名）")
    if value is None:
        # 缺值时报清楚，绝不把 str(None)="None" 写进设置（那会把字体名写坏）
        return _fail("缺少 value 参数（%s 要改成什么值？）" % key)
    manager = ctx.settings()
    if manager is None:
        return _fail("设置不可用")
    # ⚠️ 人话键名先解析（"通知位置" → toast_position）。
    #    这就是 AI 说"设置里根本没有通知位置这一项"的修复点。
    if key not in manager.settings:
        _resolved = setting_spec.label_to_key(key)
        if _resolved and _resolved in manager.settings:
            key = _resolved
    if key not in manager.settings:
        needle = key.lower()
        near = [k for k in manager.settings if needle and needle in str(k).lower()][:6]
        _by_label = setting_spec.label_to_key(key)
        if _by_label and _by_label not in near:
            near.insert(0, _by_label)
        hint = ("，你是想找：" + " / ".join(near)) if near else ""
        return _fail("没有名为 %s 的设置项%s" % (key, hint))

    if setting_spec.is_readonly(key):
        return _fail("%s 是敏感/只读设置（API Key、内部状态一类），不允许 AI 修改" % key)

    # value 已由 _setting_args 归一（含 on 兜底），不再从原始 args 取
    old = manager.settings.get(key)

    # ① 枚举项：走别名解析（"毛玻璃"能不能识别的关键）
    if setting_spec.is_enum(key):
        ok, resolved, hint = setting_spec.resolve_value(key, value)
        if not ok:
            return _fail(hint)
        value = resolved
    else:
        # ② 非枚举项：按旧值类型转换（布尔要认中文"开/关"）
        try:
            if isinstance(old, bool):
                if isinstance(value, bool):
                    pass
                else:
                    words = str(value).strip().lower()
                    if words in setting_spec.BOOL_TRUE_WORDS:
                        value = True
                    elif words in setting_spec.BOOL_FALSE_WORDS:
                        value = False
                    else:
                        return _fail("%s 是开关，值只能是开/关（收到 %r）" % (key, value))
            elif isinstance(old, int) and not isinstance(old, bool):
                value = int(value)
            elif isinstance(old, float):
                value = float(value)
            else:
                value = str(value)
        except (TypeError, ValueError):
            return _fail("值 %r 不适合设置项 %s" % (value, key))

    if not _set_setting(ctx, key, value):
        return _fail("写入设置失败: %s" % key)

    # ③ 写完让界面立刻生效（不然就是"要重启"那个 bug）
    apply = setting_spec.apply_hint(key)
    if apply == "appearance":
        _ui(ctx, "apply_appearance", theme=_read_setting(ctx, "theme"),
            theme_effect=_read_setting(ctx, "theme_effect"),
            accent_color=_read_setting(ctx, "accent_color"),
            ui_font_family=_read_setting(ctx, "ui_font_family"),
            ui_animation=_read_setting(ctx, "ui_animation"))
    elif apply == "language":
        _ui(ctx, "apply_language", language=value)
    elif apply == "reload":
        _ui(ctx, "reload_data", key=key)

    label = setting_spec.key_label(key)
    shown = ("%s（%s）" % (key, label)) if label else key
    return _ok("%s: %s → %s" % (shown, old, value))


def _read_setting(ctx, key: str, fallback=""):
    """读一项设置的当前值（读不到给 fallback）"""
    manager = ctx.settings()
    if manager is None:
        return fallback
    try:
        return manager.settings.get(key, fallback)
    except Exception:                                     # noqa: BLE001
        return fallback


def _tool_list_settings(ctx, args):
    """列出全部设置项 + 当前值（枚举项连可选值、每项带界面中文名）

    用户要求（Q1b）：「设置中的所有内容 agent 都可以动」
    → 要能改，模型得先知道：有哪些键、现在什么值、能填什么、界面上叫什么。
    ⚠️ label 尤其关键：用户说「通知位置」，模型要能对应到 toast_position。
    """
    from . import setting_spec

    manager = ctx.settings()
    if manager is None:
        return _fail("设置不可用")
    keyword = str(args.get("keyword") or "").strip().lower()
    try:
        items = {}
        readonly = []
        for key, value in sorted(manager.settings.items()):
            label = setting_spec.key_label(key)
            if keyword:
                hay = (str(key) + " " + label).lower()
                if keyword not in hay:
                    continue
            try:
                from ...utils.logger import is_secret_key
                if is_secret_key(key):
                    items[str(key)] = "（已隐藏）"
                    continue
            except Exception:
                pass
            if setting_spec.is_readonly(key):
                readonly.append(str(key))
                continue
            entry = {"value": _text(str(value), 100)}
            if label:
                entry["label"] = label
            if setting_spec.is_enum(key):
                spec = setting_spec.SETTING_VALUES.get(str(key)) or {}
                entry["values"] = list(spec.get("values") or [])
                apply = setting_spec.apply_hint(key)
                if apply:
                    entry["applies"] = apply
            items[str(key)] = entry
        result = {"count": len(items), "settings": items}
        if readonly:
            result["readonly"] = readonly[:20]
        # ⚠️ 必须包在 data 里：工具结果回给模型前会过 agent_tools.format_result，
        #   它只序列化 result["data"]（见 format_result）。旧写法 _ok(**result) 把
        #   count/settings 摊在顶层、没有 data → 模型收到 {"data":""}，于是断言
        #   "设置接口返回空内容，读不到键名和可选值"（用户实测，就是这条）。
        return _ok(result)
    except Exception as exc:
        return _fail("读取设置列表失败: %s" % exc)


def _tool_update_settings(ctx, args):
    """一次改多项设置（逐项走 _tool_set_setting，规则只有一份）"""
    raw = args.get("settings")
    if not isinstance(raw, dict) or not raw:
        return _fail("缺少 settings 参数（对象，如 {\"theme\":\"深色主题\"}）")
    applied = []
    changes = []          # ★ 保留每项的「旧值 → 新值」（见下面注释）
    failed = []
    for key, value in raw.items():
        result = _tool_set_setting(ctx, {"key": key, "value": value})
        if result.get("ok"):
            applied.append(str(key))
            # ★ 本轮（用户："agent 不知道原有的选择"）：批量改设置时旧实现只留键名，
            #   步骤详情就只剩"完成"，模型下一轮再也想不起来自己把什么从什么改成了什么。
            #   _tool_set_setting 返回的 data 正是"键（界面名）: 旧 → 新"，原样带出去。
            detail = result.get("data")
            if isinstance(detail, str) and detail.strip():
                changes.append(detail.strip())
        else:
            failed.append("%s: %s" % (key, result.get("error")))
    if not applied:
        return _fail("一项都没改成功 — %s" % "；".join(failed[:4]))
    data = {"applied": applied}
    if changes:
        data["result"] = "；".join(changes[:8])
    if failed:
        data["failed"] = failed[:4]
    return _ok(data)


def _tool_ui_switch(ctx, args):
    """界面开关（布尔类）—— 统一委派给 _tool_set_setting

    ⚠️ 不另写一套写盘逻辑：值域/别名/只读/即时生效只该有一份。
       旧实现里 bool(args.get("on")) 把 "关闭"/"false" 全判成 True（bool("false") 是真）。
    """
    key = str(args.get("key") or args.get("name") or "").strip()
    if not key:
        return _fail("缺少 key 参数（要开/关哪一项）")
    return _tool_set_setting(ctx, {"key": key, "value": args.get("on")})


def _tool_set_theme(ctx, args):
    """切主题（走 set_setting，保证值域校验 + 即时生效）"""
    return _tool_set_setting(ctx, {"key": "theme", "value": args.get("theme")})


def _tool_set_language(ctx, args):
    """切语言（**必须让前端走完整 changeLanguage 链路**）

    ⚠️ 修用户报的：「让 agent 切换语言为英文，小部分成功切换、大部分还是老样子」。
    根因：旧实现只写设置，前端不重读。语言牵动语言包重拉、资源库重取、筛选候选、
    收藏夹、投稿表单分段、document.lang、所有 t() 重渲染 —— 只有 changeLanguage() 做得全。
    所以：写盘 + 推 apply_language，让前端跑 changeLanguage()（= 模仿人类操作）。
    """
    language = str(args.get("language") or "").strip()
    # ★ 本轮（用户："我说恢复，它会问是不是语言；我说是，它说不知道你之前是什么语言"）：
    #   旧值必须在**写之前**读出来，并且跟着结果一起回给模型 —— 否则模型这一轮结束就
    #   再也无法回答"刚才是什么语言"，下一轮只能反问用户。
    old_language = _read_setting(ctx, "language", "")
    result = _tool_set_setting(ctx, {"key": "language", "value": language})
    if not result.get("ok"):
        return result
    from . import setting_spec
    ok, resolved, _hint = setting_spec.resolve_value("language", language)
    if ok and resolved:
        _ui(ctx, "apply_language", language=resolved)
        return _ok("已把界面语言从 %s 切换为 %s（正在重新加载界面文案）"
                   % (old_language or "未知", resolved),
                   previous=old_language, current=resolved)
    return result


def _tool_set_autostart(ctx, args):
    """开机自启（走 settings.set，那里会联动写/删注册表 Run 项）"""
    on = bool(args.get("on"))
    if not _set_setting(ctx, "startup_with_windows", on):
        return _fail("写入开机自启设置失败")
    return _ok("开机自启已%s" % ("开启" if on else "关闭"))


def _tool_set_hotkeys(ctx, args):
    """全局热键开关与键位"""
    applied = []
    on = args.get("on")
    if on is not None:
        if _set_setting(ctx, "hotkey_enabled", bool(on)):
            applied.append("全局热键已%s" % ("开启" if on else "关闭"))
    for slot in ("hotkey_search", "hotkey_ai"):
        value = str(args.get(slot) or "").strip()
        if value and _set_setting(ctx, slot, value):
            applied.append("%s=%s" % (slot, value))
    domain = ctx._api("hotkey")
    if domain is not None and applied:
        try:
            if hasattr(domain, "apply"):
                domain.apply()
        except Exception:
            pass
    if not applied:
        return _fail("没有给出要改的项（on / hotkey_search / hotkey_ai）")
    return _ok("；".join(applied))


def _tool_plugins(ctx, args):
    """列出已安装插件及状态"""
    domain = ctx._api("plugins")
    if domain is None:
        return _fail("插件系统不可用")
    try:
        result = domain.list()
        if not isinstance(result, dict) or not result.get("ok"):
            return _fail("读取插件列表失败")
        rows = []
        for row in (result.get("plugins") or []):
            rows.append({
                "id": row.get("id"), "name": row.get("name"),
                "enabled": bool(row.get("enabled")), "locked": bool(row.get("locked")),
                "builtin": bool(row.get("builtin")), "version": row.get("version"),
            })
        return _ok(count=len(rows), plugins=rows)
    except Exception as exc:
        return _fail("读取插件列表失败: %s" % exc)


def _tool_set_plugin_enabled(ctx, args):
    """启停插件：走 PluginsDomain.set_enabled（它会同步释放/加载资源）

    ⚠️ 这是"插件开关 = 资源生命周期"的唯一入口。绕过它直接写设置，
       就会出现「卡片关了，插件资源还在内存里」。
    """
    ident = str(args.get("id") or args.get("name") or "").strip()
    if not ident:
        return _fail("缺少 id 或 name 参数")
    on = bool(args.get("on", args.get("enabled", True)))
    domain = ctx._api("plugins")
    if domain is not None and hasattr(domain, "set_enabled"):
        try:
            result = domain.set_enabled(ident, on)
            if isinstance(result, dict) and result.get("ok"):
                return _ok("已%s插件 %s" % ("启用" if on else "停用", ident))
            reason = result.get("error") if isinstance(result, dict) else ""
            return _fail(reason or ("无法%s插件 %s" % ("启用" if on else "停用", ident)))
        except Exception as exc:
            return _fail("启停插件失败: %s" % exc)
    # 退化：只写 enabled_setting
    manifest_path = ""
    try:
        from desktop.api.plugins import find_plugin_dir
        folder = find_plugin_dir(ident)
        if folder:
            manifest_path = os.path.join(folder, "manifest.json")
    except Exception:
        manifest_path = ""
    if not manifest_path or not os.path.isfile(manifest_path):
        return _fail("没有找到插件 %s" % ident)
    try:
        import json
        with open(manifest_path, "r", encoding="utf-8-sig") as handle:
            manifest = json.load(handle)
        key = str(manifest.get("enabled_setting") or "").strip()
        if not key:
            return _fail("插件 %s 没有提供开关配置" % ident)
        if not _set_setting(ctx, key, on):
            return _fail("写入插件开关失败")
        return _ok("已%s插件 %s" % ("启用" if on else "停用", ident))
    except Exception as exc:
        return _fail("启停插件失败: %s" % exc)


def _tool_open_plugin_config(ctx, args):
    """打开某插件的配置页（界面动作）"""
    ident = str(args.get("id") or args.get("name") or "").strip()
    if not ident:
        return _fail("缺少 id 或 name 参数")
    if not _ui(ctx, "open_plugin_config", id=ident).get("ok"):
        return _fail("界面没能打开插件配置页")
    return _ok("已打开插件 %s 的配置界面" % ident)


def _tool_manage_plugins(ctx, args):
    """插件管理：list / enable / disable / delete"""
    action = str(args.get("action") or "").strip().lower()
    domain = ctx._api("plugins")
    if domain is None:
        return _fail("插件系统不可用")
    ident = str(args.get("id") or args.get("name") or "").strip()
    try:
        if action in ("list", "列出", ""):
            return _tool_plugins(ctx, args)
        if action in ("enable", "disable", "启用", "停用"):
            return _tool_set_plugin_enabled(ctx, {"id": ident, "on": action in ("enable", "启用")})
        if action in ("delete", "remove", "删除"):
            if not ident:
                return _fail("缺少 id 参数")
            result = domain.delete(ident)
            if isinstance(result, dict) and result.get("ok"):
                return _ok("已删除插件 %s" % ident)
            return _fail((result or {}).get("error") or "删除插件失败")
        return _fail("action 只能是 list / enable / disable / delete")
    except Exception as exc:
        return _fail("插件操作失败: %s" % exc)


# ======================================================================
# 工具实现（文件与系统）
# ======================================================================
def _safe_path(path, need_exists=True):
    """解析并校验路径；越界/不存在返回 (空串, 原因)"""
    raw = str(path or "").strip()
    if not raw:
        return "", "缺少 path 参数"
    full = os.path.abspath(os.path.expanduser(raw))
    if not _within_allowed(full):
        return "", ("不在允许的目录内（只能读写程序目录、主目录、桌面/下载/文档）：%s" % full)
    if need_exists and not os.path.exists(full):
        return "", "路径不存在：%s" % full
    return full, ""


def _tool_list_dir(ctx, args):
    raw = str(args.get("path") or "").strip() or os.path.expanduser("~")
    full, error = _safe_path(raw, need_exists=True)
    if error:
        return _fail(error)
    if not os.path.isdir(full):
        return _fail("不是一个目录：%s" % full)
    try:
        entries = []
        for name in sorted(os.listdir(full))[:200]:
            child = os.path.join(full, name)
            try:
                size = os.path.getsize(child) if os.path.isfile(child) else 0
            except OSError:
                size = 0
            entries.append({"name": name, "dir": os.path.isdir(child), "size": size})
        return _ok(path=full, count=len(entries), entries=entries)
    except Exception as exc:
        return _fail("列目录失败: %s" % exc)


def _tool_read_file(ctx, args):
    full, error = _safe_path(args.get("path"), need_exists=True)
    if error:
        return _fail(error)
    if os.path.isdir(full):
        return _fail("这是一个目录，用 list_dir 看内容")
    try:
        if os.path.getsize(full) > 8 * 1024 * 1024:
            return _fail("文件太大（超过 8MB），请换一个小文件")
        with open(full, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.read(MAX_TEXT)
        return _ok(path=full, chars=len(content), content=content)
    except Exception as exc:
        return _fail("读取文件失败: %s" % exc)


def _tool_write_file(ctx, args):
    full, error = _safe_path(args.get("path"), need_exists=False)
    if error:
        return _fail(error)
    content = str(args.get("content") if args.get("content") is not None else "")
    append = bool(args.get("append"))
    try:
        parent = os.path.dirname(full)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(full, "a" if append else "w", encoding="utf-8") as handle:
            handle.write(content)
        return _ok("已%s %s（%d 字符）" % ("追加到" if append else "写入", full, len(content)))
    except Exception as exc:
        return _fail("写文件失败: %s" % exc)


def _tool_run_python(ctx, args):
    code = str(args.get("code") or "").strip()
    if not code:
        return _fail("缺少 code 参数")
    try:
        timeout = float(args.get("timeout") or 60)
    except (TypeError, ValueError):
        timeout = 60.0
    timeout = max(1.0, min(60.0, timeout))
    try:
        completed = subprocess.run(
            [sys.executable or "python", "-c", code],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
        return _ok(returncode=completed.returncode,
                   stdout=_text(completed.stdout, 6000),
                   stderr=_text(completed.stderr, 3000))
    except subprocess.TimeoutExpired:
        return _fail("代码运行超时（%g 秒）" % timeout)
    except Exception as exc:
        return _fail("运行 Python 失败: %s" % exc)


def _tool_open_url(ctx, args):
    url = str(args.get("url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return _fail("只支持 http/https 链接")
    domain = ctx._api("shell")
    if domain is None:
        return _fail("打开链接能力不可用")
    try:
        result = domain.open_url(url)
        if isinstance(result, dict) and not result.get("ok"):
            return _fail(result.get("error") or "打开链接失败")
        return _ok("已在系统浏览器中打开：%s" % url)
    except Exception as exc:
        return _fail("打开链接失败: %s" % exc)


def _tool_download_resource(ctx, args):
    code = str(args.get("code") or args.get("id") or "").strip()
    item = _find_resource(ctx, code)
    if item is None:
        near = find_resource_candidates(ctx, code)
        hint = ("。你是想找：" + "、".join(near)) if near else ""
        return _fail("资源库里没有「%s」%s" % (code, hint))
    url = str(item.get("url") or item.get("download") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return _fail("这条资源没有可直接下载的链接")
    domain = ctx._api("downloader")
    if domain is None or not hasattr(domain, "start"):
        return _fail("下载功能不可用")
    try:
        result = domain.start(url)
        if isinstance(result, dict) and not result.get("ok"):
            return _fail(result.get("error") or "下载没有开始")
        return _ok("已开始下载：%s" % (item.get("name") or code))
    except Exception as exc:
        return _fail("开始下载失败: %s" % exc)



# ======================================================================
# 工具实现（诊断与自检）
# ======================================================================
def _tool_read_logs(ctx, args):
    domain = ctx._api("log")
    if domain is None:
        return _fail("日志功能不可用")
    try:
        limit = max(1, min(200, int(args.get("limit") or 30)))
    except (TypeError, ValueError):
        limit = 30
    try:
        result = domain.read_current()
        if not isinstance(result, dict) or not result.get("ok"):
            return _fail("读取日志失败")
        content = str(result.get("content") or result.get("text") or "")
        lines = [line for line in content.splitlines() if line.strip()][-limit:]
        return _ok(lines=len(lines), content="\n".join(lines)[-MAX_TEXT:])
    except Exception as exc:
        return _fail("读取日志失败: %s" % exc)


def _tool_export_logs(ctx, args):
    domain = ctx._api("log")
    if domain is None:
        return _fail("日志功能不可用")
    try:
        result = domain.export(all=bool(args.get("all")))
        if not isinstance(result, dict) or not result.get("ok"):
            return _fail((result or {}).get("error") or "导出日志失败")
        return _ok("日志已导出：%s" % (result.get("path") or ""))
    except Exception as exc:
        return _fail("导出日志失败: %s" % exc)


def _tool_app_diagnostics(ctx, args):
    """诊断快照：排查最常用的几项一次给全"""
    report = {}
    try:
        resources = ctx._api("resources")
        report["paths"] = resources.paths() if resources is not None else {}
    except Exception:
        report["paths"] = {}
    try:
        from .chat_store import ChatStore
        report["sessions"] = len(ChatStore().list_sessions())
    except Exception as exc:
        report["sessions"] = "不可用: %s" % exc
    try:
        report["resources"] = len(ctx.resources())
    except Exception:
        report["resources"] = 0
    try:
        manager = ctx.settings()
        if manager is not None:
            report["provider"] = manager.settings.get("ai_provider")
            report["model"] = manager.settings.get("model_name")
    except Exception:
        pass
    try:
        from .agent_tools import get_registry
        registry = get_registry()
        report["tools"] = registry.count()
        report["recent_tools"] = registry.recent_actions(5)
    except Exception:
        pass
    return _ok(report)


def _tool_self_check(ctx, args):
    report = {}
    try:
        manager = ctx.favorites()
        report["favorites"] = {"folders": len(manager.folders())} if manager is not None \
            else {"error": "不可用"}
    except Exception:
        report["favorites"] = {"error": "不可用"}
    try:
        report["resources"] = {"count": len(ctx.resources())}
    except Exception:
        report["resources"] = {"error": "不可用"}
    try:
        manager = ctx.settings()
        sample = {}
        if manager is not None:
            for key in ("ai_enabled", "gcp_ai_agent_enabled", "theme", "language"):
                sample[key] = manager.settings.get(key)
        report["settings_sample"] = sample
    except Exception:
        report["settings_sample"] = {"error": "不可用"}
    try:
        from .agent_tools import get_registry
        registry = get_registry()
        report["tools"] = {"count": registry.count(),
                           "recent": registry.recent_actions(5)}
    except Exception:
        report["tools"] = {"error": "不可用"}
    return _ok(report)


# ======================================================================
# 注册表：名字 -> (参数串, 实现, 是否危险)
# ======================================================================
# ⚠️ 参数串必须和 agent_tools 里注册的**完全一致**（模型看到的清单来自那边）。
_WEB_TOOLS = {
    # ---------- 资源库 ----------
    "search_resources": ("query,category,limit", _tool_search, False),
    "get_resource": ("code", _tool_get, False),
    "open_resource": ("code", _tool_open, False),
    "resource_stats": ("", _tool_stats, False),
    "list_all_resources": ("offset,page_size", _tool_list_all, False),
    # ---------- 收藏 ----------
    "list_favorites": ("", _tool_favorites, False),
    "set_favorite": ("code,folder,on", _tool_favorite_set, False),
    "create_favorite_folder": ("name,code", _tool_favorite_folder, False),
    "move_favorite": ("code,folder", _tool_favorite_move, False),
    # ---------- 界面与导航 ----------
    "goto_page": ("page", _tool_goto, False),
    "notify_user": ("text", _tool_notify, False),
    "search_view": ("card_size,view", _tool_search_view, False),
    "deploy_list": ("", _tool_deploy_list, False),
    "set_window_state": ("action", _tool_set_window_state, False),
    # ---------- 设置与外观 ----------
    "get_setting": ("key", _tool_get_setting, False),
    "set_setting": ("key,value", _tool_set_setting, False),
    "list_settings": ("keyword", _tool_list_settings, False),
    "update_settings": ("settings", _tool_update_settings, False),
    "ui_switch": ("key,on", _tool_ui_switch, False),
    "set_theme": ("theme", _tool_set_theme, False),
    "set_language": ("language", _tool_set_language, False),
    "set_autostart": ("on", _tool_set_autostart, False),
    "set_hotkeys": ("on,hotkey_search,hotkey_ai", _tool_set_hotkeys, False),
    # ---------- 插件 ----------
    "list_plugins": ("", _tool_plugins, False),
    "set_plugin_enabled": ("id,on", _tool_set_plugin_enabled, False),
    "open_plugin_config": ("id", _tool_open_plugin_config, False),
    "manage_plugins": ("action,id", _tool_manage_plugins, False),
    # ---------- 文件与系统 ----------
    "list_dir": ("path", _tool_list_dir, False),
    "read_file": ("path", _tool_read_file, False),
    "write_file": ("path,content,append", _tool_write_file, True),
    "run_python": ("code,timeout", _tool_run_python, True),
    "open_url": ("url", _tool_open_url, False),
    "download_resource": ("code", _tool_download_resource, False),
    # ---------- 诊断 ----------
    "read_logs": ("limit", _tool_read_logs, False),
    "export_logs": ("all", _tool_export_logs, False),
    "app_diagnostics": ("", _tool_app_diagnostics, False),
    "new_chat": ("", _tool_new_chat, False),
    "self_check": ("", _tool_self_check, False),
}

# 本模块实现的全部工具名
WEB_TOOL_NAMES = sorted(_WEB_TOOLS.keys())

# 中文描述（登记给模型看）
_DESCRIPTIONS = {
    "search_resources": "在 ToolsGCP 资源库里搜索程序/网站（返回编码、名称、简介、链接）",
    "get_resource": "按编码或名称取一笔资源的完整信息（支持模糊匹配，如「抠图」可命中「抠图精灵」）",
    "open_resource": "在界面上打开某笔资源的详细页",
    "resource_stats": "资源库统计：总数、类别数、各类别笔数",
    "list_all_resources": "返回资源库全部条目（分页取，必须列完）",
    "list_favorites": "列出收藏夹（含每个夹里的资源）",
    "set_favorite": "收藏/取消收藏一笔资源；folder 可指定放进哪个收藏夹",
    "create_favorite_folder": "新建一个收藏夹；带上 code 可以顺便把资源放进去",
    "move_favorite": "把一笔资源移动到另一个收藏夹",
    "goto_page": "切换到主界面的某个页面",
    "notify_user": "在界面上弹一则提示",
    "search_view": "调整搜索页外观：card_size / view",
    "deploy_list": "查看部署/导出清单里的资源编码",
    "set_window_state": "窗口最小化/最大化/全屏/隐藏到托盘/显示",
    "get_setting": ("读取一项设置。key 可以是设置键名，也可以是界面中文名"
                    "（如「通知位置」会自动对应到 toast_position）"),
    "set_setting": ("修改一项设置（立即生效并保存）。key 接受键名或界面中文名，"
                    "value 接受中文说法（如 theme_effect 传「毛玻璃」=glass）；"
                    "先用 list_settings 查看有哪些键、能填什么值"),
    "list_settings": "列出全部设置项：键名、界面中文名(label)、当前值、枚举项的可选值(values)",
    "update_settings": "一次修改多项设置，settings 是对象如 {\"theme\":\"深色主题\"}",
    "ui_switch": "打开/关闭某一项布尔开关（key 同样接受中文名）",
    "set_theme": "切换主题（深色/浅色/跟随系统，也认 dark/light/auto）",
    "set_language": "切换界面语言（简体中文/繁體中文/English，会自动重载全部界面文案）",
    "set_autostart": "开启/关闭开机自启",
    "set_hotkeys": "设置全局热键开关与键位",
    "list_plugins": "列出已安装的插件及启用状态",
    "set_plugin_enabled": "启用或停用某个插件（会同步加载/释放它的资源）",
    "open_plugin_config": "打开某个插件的配置界面",
    "manage_plugins": "插件管理：list / enable / disable / delete",
    "list_dir": "列出一个目录里的文件",
    "read_file": "读一个文本文件的内容（最多 2 万字）",
    "write_file": "写一个文本文件（append=true 追加）",
    "run_python": "在独立子进程里跑一小段 Python 代码（最多 60 秒）",
    "open_url": "用系统默认浏览器打开一个网址（http/https）",
    "download_resource": "把某条资源交给下载器下载",
    "read_logs": "读最近的执行日志",
    "export_logs": "把日志打包导出成 zip",
    "app_diagnostics": "诊断快照：配置路径/会话数/服务商/资源数/工具数",
    "new_chat": "开始一段新的 AI 对话",
    "self_check": "自检：汇总收藏夹/插件开关/资源库/关键设置/最近调用",
}

def _describe_all(name: str) -> dict:
    """把工具描述展开成三语字典（登记给 AITool.description）

    用户原话：「插件配置和 ai 的这个输出也要支持三语言」。
    ⚠️ 旧实现 {"zh_CN": 中文, "zh_TW": 同一句中文, "en_US": 同一句中文} ——
       界面切英文后，模型看到的工具清单仍然是整片中文。
    ⚠️ 英文/繁中没写全时**回退中文**，保证不会出现空描述（空描述模型更容易乱调）。
    """
    zh = _DESCRIPTIONS.get(name, name)
    tw = _DESCRIPTIONS_TW.get(name, "")
    en = _DESCRIPTIONS_EN.get(name, "")
    return {"zh_CN": zh, "zh_TW": tw or zh, "en_US": en or zh}


# 英文描述（没写的自动回退中文，见 _describe_all）
_DESCRIPTIONS_EN = {
    "search_resources": "Search the ToolsGCP library for apps/websites (code, name, summary, link)",
    "get_resource": "Get one resource by code or fuzzy name (e.g. 'cutout' matches 'Cutout Wizard')",
    "open_resource": "Open a resource's detail page in the UI",
    "resource_stats": "Library stats: total, category count, per-category counts",
    "list_all_resources": "Return every library entry (paged; must list them all)",
    "list_favorites": "List favorite folders and the resources inside them",
    "set_favorite": "Save/unsave a resource; folder picks which favorite folder",
    "create_favorite_folder": "Create a favorite folder; pass code to also put a resource in it",
    "move_favorite": "Move a resource into another favorite folder",
    "goto_page": "Switch the main window to a page",
    "notify_user": "Show a short toast in the UI",
    "search_view": "Adjust the search page: card_size / view",
    "deploy_list": "List resource codes currently in the deploy/export list",
    "set_window_state": "Minimize / maximize / fullscreen / hide to tray / show the window",
    "get_setting": ("Read one setting. 'key' accepts either the setting key or the UI label "
                    "(e.g. 'toast position' maps to toast_position)"),
    "set_setting": ("Change one setting (applies and saves immediately). 'key' accepts the key or "
                    "the UI label; 'value' accepts natural language (e.g. theme_effect='glass'). "
                    "Use list_settings first to see keys and allowed values"),
    "list_settings": "List all settings: key, UI label, current value, and allowed values for enums",
    "update_settings": "Change several settings at once; settings is an object like {\"theme\":\"dark\"}",
    "ui_switch": "Turn a boolean switch on/off (key also accepts the UI label)",
    "set_theme": "Switch theme (dark / light / system)",
    "set_language": "Switch UI language (reloads all UI copy automatically)",
    "set_autostart": "Enable/disable launch at Windows startup",
    "set_hotkeys": "Set global hotkey switch and key bindings",
    "list_plugins": "List installed plugins and whether they are enabled",
    "set_plugin_enabled": "Enable or disable a plugin (syncs its resources)",
    "open_plugin_config": "Open a plugin's configuration screen",
    "manage_plugins": "Plugin management: list / enable / disable / delete",
    "list_dir": "List files in a directory",
    "read_file": "Read a text file (up to 20k characters)",
    "write_file": "Write a text file (append=true to append)",
    "run_python": "Run a short Python snippet in a separate process (60s max)",
    "open_url": "Open a URL in the system browser (http/https)",
    "download_resource": "Hand a resource to the downloader",
    "read_logs": "Read the most recent log lines",
    "export_logs": "Export logs as a zip",
    "app_diagnostics": "Diagnostics snapshot: paths / sessions / provider / resources / tools",
    "new_chat": "Start a new AI conversation",
    "self_check": "Self-check: favorites / plugins / library / key settings / recent calls",
}

# 繁中描述（没写的自动回退中文）
_DESCRIPTIONS_TW = {
    "search_resources": "在 ToolsGCP 資源庫裡搜尋程式/網站（回傳編碼、名稱、簡介、連結）",
    "get_resource": "依編碼或名稱取一筆資源（支援模糊比對）",
    "open_resource": "在介面上開啟某筆資源的詳細頁",
    "resource_stats": "資源庫統計：總數、類別數、各類別筆數",
    "list_all_resources": "回傳資源庫全部條目（分頁取，必須列完）",
    "list_favorites": "列出收藏夾（含每個夾裡的資源）",
    "set_favorite": "收藏/取消收藏一筆資源；folder 可指定放進哪個收藏夾",
    "create_favorite_folder": "新增一個收藏夾；帶上 code 可以順便把資源放進去",
    "move_favorite": "把一筆資源移動到另一個收藏夾",
    "goto_page": "切換到主介面的某個頁面",
    "notify_user": "在介面上彈一則提示",
    "search_view": "調整搜尋頁外觀：card_size / view",
    "deploy_list": "看部署/匯出清單裡現在有哪些資源編碼",
    "set_window_state": "視窗最小化/最大化/全螢幕/隱藏到系統匣/顯示",
    "get_setting": "讀取一項設定。key 也接受介面中文名（如「通知位置」對應 toast_position）",
    "set_setting": ("修改一項設定（立即生效並儲存）。key 接受鍵名或介面中文名，"
                    "value 接受中文說法；先用 list_settings 查看有哪些鍵與可選值"),
    "list_settings": "列出全部設定項：鍵名、介面中文名、目前值、列舉項的可選值",
    "update_settings": "一次修改多項設定，settings 是物件如 {\"theme\":\"深色主題\"}",
    "ui_switch": "開啟/關閉某一項布林開關（key 同樣接受中文名）",
    "set_theme": "切換主題（深色/淺色/跟隨系統）",
    "set_language": "切換介面語言（會自動重新載入全部介面文案）",
    "set_autostart": "開啟/關閉開機自啟",
    "set_hotkeys": "設定全域熱鍵開關與鍵位",
    "list_plugins": "列出已安裝的外掛及啟用狀態",
    "set_plugin_enabled": "啟用或停用某個外掛（會同步載入/釋放它的資源）",
    "open_plugin_config": "開啟某個外掛的設定介面",
    "manage_plugins": "外掛管理：list / enable / disable / delete",
    "list_dir": "列出一個目錄裡的檔案",
    "read_file": "讀一個文字檔的內容（最多 2 萬字）",
    "write_file": "寫一個文字檔（append=true 附加）",
    "run_python": "在獨立子程序裡跑一小段 Python 程式碼（最多 60 秒）",
    "open_url": "用系統預設瀏覽器開啟一個網址（http/https）",
    "download_resource": "把某條資源交給下載器下載",
    "read_logs": "讀最近的執行日誌",
    "export_logs": "把日誌打包匯出成 zip",
    "app_diagnostics": "診斷快照：設定路徑/工作階段數/服務商/資源數/工具數",
    "new_chat": "開始一段新的 AI 對話",
    "self_check": "自檢：彙總收藏夾/外掛開關/資源庫/關鍵設定/最近呼叫",
}


# ======================================================================
# 工具的「界面显示名」（三语）—— 配置页模块列表的标题
# ======================================================================
# ⚠️⚠️ 用户原话：「插件界面有些东西只有英文的没用其他2个语言的了，我要的是三语言
#    而且和设置中的语言同切换」。
# 根因：配置页把 tool.name（search_resources 这种英文标识符）当成**唯一标题**显示，
#   description 只在下面当灰色小字。所以界面切到中文/繁中，标题仍然全是英文。
# 修法：给每个工具一套三语短名（LABELS），配置页优先用它当标题，
#   英文标识符降级成副标签（mono 小字，开发者还需要它来对照）。
TOOL_LABELS = {
    "search_resources": ("搜索资源", "搜尋資源", "Search"),
    "get_resource": ("查看资源", "查看資源", "Get resource"),
    "open_resource": ("打开资源", "開啟資源", "Open resource"),
    "resource_stats": ("资源统计", "資源統計", "Stats"),
    "list_all_resources": ("列出全部资源", "列出全部資源", "List all"),
    "list_favorites": ("查看收藏夹", "查看收藏夾", "Favorites"),
    "set_favorite": ("收藏资源", "收藏資源", "Save favorite"),
    "create_favorite_folder": ("新建收藏夹", "新增收藏夾", "New folder"),
    "move_favorite": ("移动收藏", "移動收藏", "Move favorite"),
    "goto_page": ("切换页面", "切換頁面", "Go to page"),
    "notify_user": ("弹出提示", "彈出提示", "Notify"),
    "search_view": ("搜索页外观", "搜尋頁外觀", "Search view"),
    "deploy_list": ("部署清单", "部署清單", "Deploy list"),
    "set_window_state": ("窗口状态", "視窗狀態", "Window state"),
    "get_setting": ("读取设置", "讀取設定", "Read setting"),
    "set_setting": ("修改设置", "修改設定", "Change setting"),
    "list_settings": ("列出设置", "列出設定", "List settings"),
    "update_settings": ("批量改设置", "批次改設定", "Update settings"),
    "ui_switch": ("界面开关", "介面開關", "UI switch"),
    "set_theme": ("切换主题", "切換主題", "Theme"),
    "set_language": ("切换语言", "切換語言", "Language"),
    "set_autostart": ("开机自启", "開機自啟", "Autostart"),
    "set_hotkeys": ("全局热键", "全域熱鍵", "Hotkeys"),
    "list_plugins": ("列出插件", "列出外掛", "List plugins"),
    "set_plugin_enabled": ("启停插件", "啟停外掛", "Toggle plugin"),
    "open_plugin_config": ("打开插件配置", "開啟外掛設定", "Plugin config"),
    "manage_plugins": ("管理插件", "管理外掛", "Manage plugins"),
    "list_dir": ("列出目录", "列出目錄", "List folder"),
    "read_file": ("读取文件", "讀取檔案", "Read file"),
    "write_file": ("写入文件", "寫入檔案", "Write file"),
    "run_python": ("运行代码", "執行程式碼", "Run code"),
    "open_url": ("打开网页", "開啟網頁", "Open URL"),
    "download_resource": ("下载资源", "下載資源", "Download"),
    "read_logs": ("查看日志", "查看日誌", "Read logs"),
    "export_logs": ("导出日志", "匯出日誌", "Export logs"),
    "app_diagnostics": ("诊断信息", "診斷資訊", "Diagnostics"),
    "new_chat": ("新建对话", "新增對話", "New chat"),
    "self_check": ("自检", "自檢", "Self check"),
}


def tool_label(name: str, locale: str = "zh_CN") -> str:
    """工具的三语显示名（认不出的回退成工具名本身，绝不返回空串）"""
    labels = TOOL_LABELS.get(str(name or ""))
    if not labels:
        return str(name or "")
    index = {"zh_CN": 0, "zh_TW": 1, "en_US": 2}.get(str(locale or "zh_CN"), 0)
    return labels[index] or labels[0] or str(name or "")


_FALLBACK_CTX = None
_FALLBACK_CTX = None


def _fallback_ctx(agent=None):
    """给没有显式 ctx 的调用方凑一个上下文（探针/自检/预览）"""
    global _FALLBACK_CTX
    shell = None
    for attr in ("_shell", "shell", "main_window", "window"):
        try:
            candidate = getattr(agent, attr, None)
        except Exception:
            candidate = None
        if candidate is not None and not callable(candidate):
            shell = candidate
            break
    if shell is None:
        if _FALLBACK_CTX is None:
            _FALLBACK_CTX = WebAgentContext(None)
        return _FALLBACK_CTX
    return WebAgentContext(shell)


def _make_handler(name):
    """生成某个工具的处理函数（闭包捕获名字）"""
    def handler(agent, args):
        ctx = None
        try:
            ctx = getattr(agent, "_agent_web_ctx", None)
        except Exception:
            ctx = None
        if ctx is None:
            ctx = _fallback_ctx(agent)
        return execute(name, args, ctx)
    return handler


def register_web_tools(registry=None, ctx=None):
    """把 Web 版实现注册进注册表（覆盖同名 Qt 版实现），返回成功注册数量

    ⚠️ 幂等：同名 register_tool 就是覆盖，重复调用不会重复计数。
    ⚠️ 本函数不抛：单个工具注册失败只记日志。
    """
    count = 0
    if registry is None:
        try:
            from .agent_tools import get_registry
            registry = get_registry()
        except Exception as exc:
            _log("warn", "拿不到工具注册表: %s" % exc)
            return 0
    for name in WEB_TOOL_NAMES:
        params, _handler, danger = _WEB_TOOLS[name]
        try:
            ok = registry.register_tool(
                name,
                _describe_all(name),
                _make_handler(name),
                parameters=params,
                source=AGENT_SOURCE,
                danger=danger,
            )
            if ok:
                count += 1
        except Exception as exc:
            _log("warn", "注册工具 %s 失败: %s" % (name, exc))
    _log("info", "Web 版工具已注册 %d 个（共 %d 个）" % (count, len(WEB_TOOL_NAMES)))
    return count


def execute(name, args, ctx=None):
    """执行一个工具，返回 {"ok": bool, ...} 信封；永不抛"""
    tool = str(name or "").strip()
    spec = _WEB_TOOLS.get(tool)
    if spec is None:
        return _fail("Web 版没有实现工具 %s" % tool)
    if ctx is None:
        ctx = _fallback_ctx(None)
    try:
        return spec[1](ctx, args if isinstance(args, dict) else {})
    except Exception as exc:
        _log("err", "工具 %s 执行异常: %s: %s" % (tool, type(exc).__name__, exc))
        return _fail("%s: %s" % (type(exc).__name__, exc))


def submit_reply(req_id, payload):
    """前端 ai.agent_reply 的落点（模块级，供 AiDomain 调用）"""
    try:
        ctx = _FALLBACK_CTX
        if ctx is None:
            return False
        return ctx.submit_reply(req_id, payload)
    except Exception:
        return False


def _log(level, message):
    """本模块自己的日志（拿不到日志器时静默）"""
    try:
        from ...utils.logger import log
        method = level if level in ("info", "warn", "err", "op") else "info"
        getattr(log, method)("AI-Agent", "agent_web", str(message or "")[:400])
    except Exception:
        pass


__all__ = [
    "AGENT_SOURCE", "REPLY_TIMEOUT", "WEB_TOOL_NAMES",
    "WebAgentContext", "register_web_tools", "execute", "submit_reply",
    "TOOL_LABELS", "tool_label",
]
