"""GCP-AI 版本树 / 流式 / 润色 的可跑测试（无第三方依赖，直接 python 跑）。

    python "项目资料-文档与开发测试/_devtest/test_ai_versions.py"

覆盖（用户明确要求的验收项）：
  1. 老格式会话文件（没有版本字段）能读进来，且当成"只有 v1"；
  2. 用户发 "1" → AI 回 "11"、"22"（重新生成产生第二条版本）；
     之后用户**编辑**这条消息成 "2" → 11/22 仍属于版本 "1"，与版本 "2" 的回复互不混；
  3. 上下文（发给模型的 messages）严格按"当前选中的用户版本 + 该版本下选中的 AI 回复"组装；
  4. 润色撤销的正确性（后端返回 original / 前端撤销状态机的契约）；
  5. 所有版本持久化（写盘 → 重新 load 还在）；
  6. 流式：chat_stream 的 SSE 解析（半行 JSON / 半个中文字 / [DONE] / 收尾必达 / 中断 / 401）；
  7. 后端 send / switch_variant 的版本语义端到端（不联网：只 mock 模型请求那一步）。

⚠️ 这个脚本**只写仓库内的临时目录**（`项目资料-文档与开发测试/_tmp-ai-test/`，已 gitignore），
   绝不碰 `.ToolsGCP/chats` —— 那是用户数据。
"""

import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
for entry in (ROOT, os.path.join(ROOT, ".ToolsGCP"), os.path.join(ROOT, ".ToolsGCP", "modules")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

# ⚠️ Windows 控制台默认 GBK，中文 + ✓/✗ 一打印就 UnicodeEncodeError 把整个测试打断。
#    这里强制 stdout/stderr 走 UTF-8（Python 3.7+），让脚本在任何终端都能跑完。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                     # noqa: BLE001
        pass


def _tmp_dir(prefix: str) -> str:
    """测试用的临时会话目录。

    ⚠️ 不用系统 %TEMP%：沙箱环境里它**不可写**（Errno 13），会让"落盘 / 重开"的用例
       全变成假失败。写进 `项目资料-文档与开发测试/_tmp-ai-test/`（被 .gitignore 的
       `项目资料-文档与开发测试/_tmp*/` 覆盖、随时可删），
       既跑得动也**绝不污染 .ToolsGCP/chats —— 那是用户数据，一律不碰**。
    """
    base = os.path.join(ROOT, "项目资料-文档与开发测试", "_tmp-ai-test", prefix)
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base, exist_ok=True)
    return base


from pymodels.core.ai import client as ai_client                  # noqa: E402
from pymodels.core.ai import versions as V                        # noqa: E402
from pymodels.core.ai.chat_store import ChatStore                 # noqa: E402

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    mark = "✓" if condition else "✗"
    print(f"  {mark} {name}{('  ← ' + str(detail)) if (detail and not condition) else ''}")


def section(title):
    print(f"\n── {title} ──")


def read_repo_file(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# ===========================================================================
# 1) 老格式会话（无版本字段）能读
# ===========================================================================
def test_legacy_read():
    section("1. 老格式会话文件能读（向后兼容）")
    legacy = [
        {"role": "user", "content": "帮我找个局域网传文件的工具", "ts": "2026-01-01 10:00:00"},
        {"role": "assistant", "content": "推荐 LocalSend", "ts": "2026-01-01 10:00:05"},
        {"role": "assistant", "content": "请求失败：超时", "ts": "2026-01-01 10:01:00",
         "error": True, "kind": "timeout"},
    ]
    messages = [dict(m) for m in legacy]
    changed = V.normalize_messages(messages)

    check("老实消息补齐后仍只有 1 个版本",
          all(V.variant_count(m) == 1 for m in messages),
          str([V.variant_count(m) for m in messages]))
    check("补齐后页码都是第 1 版（索引 0）",
          all(V.active_variant(m) == 0 for m in messages))
    check("正文没被改坏", [m["content"] for m in messages] == [m["content"] for m in legacy])
    check("报错气泡的 error/kind 标记原样保留",
          messages[2]["error"] is True and messages[2]["kind"] == "timeout")
    check("normalize 报告『改过几条』（首屏就能拿到版本数）", changed == 3, str(changed))
    check("只有一版时不显示导航", all(V.has_navigation(m) is False for m in messages))
    check("用户消息补出 branch_suffixes（长度 = 版本数）",
          messages[0]["branch_suffixes"] == [None], str(messages[0].get("branch_suffixes")))
    check("normalize 幂等（再跑一遍不再报改动）",
          V.normalize_messages(messages) == 0)

    # 坏数据：content 不在 variants 里（旧版"编辑后发送"只改 content 没同步 variants）
    broken = [{"role": "user", "content": "编辑后的正文", "ts": "x",
               "variants": ["编辑前的正文"], "variant_index": 0}]
    V.normalize_messages(broken)
    check("正文不在版本表里时会被补成新的一版",
          broken[0]["variants"] == ["编辑前的正文", "编辑后的正文"],
          str(broken[0]["variants"]))
    check("补进去后停在正文那一版（绝不把用户编辑的正文回退掉）",
          broken[0]["variant_index"] == 1 and broken[0]["content"] == "编辑后的正文")

    # 越界页码：坏数据退回最后一版，不能崩
    weird = [{"role": "assistant", "content": "B", "variants": ["A", "B"], "variant_index": 99}]
    V.normalize_messages(weird)
    check("页码越界被钳到最后一版", weird[0]["variant_index"] == 1
          and weird[0]["content"] == "B", str(weird[0]))

    # 磁盘级：老文件（完全没有版本字段）能 load + save 后再读
    tmp = _tmp_dir("legacy")
    try:
        store = ChatStore(chats_dir=tmp)
        old_on_disk = {"schema_version": "1.0.0", "id": "legacy-1", "title": "老对话",
                       "created_at": "2026-01-01 10:00:00",
                       "updated_at": "2026-01-01 10:00:05",
                       "messages": [dict(m) for m in legacy]}
        with open(store.path_of("legacy-1"), "w", encoding="utf-8") as f:
            json.dump(old_on_disk, f, ensure_ascii=False)

        loaded = store.load("legacy-1")
        check("老文件能 load", loaded is not None and len(loaded.messages) == 3)
        V.normalize_messages(loaded.messages)
        store.save(loaded)
        again = ChatStore(chats_dir=tmp).load("legacy-1")
        check("老文件升级后内容仍一致",
              [m["content"] for m in again.messages] == [m["content"] for m in legacy])
        check("原始老字段（title / 时间）没丢",
              again.title == "老对话" and again.created_at == "2026-01-01 10:00:00")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# 2) 用户消息的版本 + 各自挂的 AI 回复（用户原话的例子）
# ===========================================================================
def test_user_versions_and_branches():
    section("2. 用户编辑 → 新版本；旧回复归属不变（版本 1 与版本 2 各挂各的）")
    # 用户发 "1"，AI 回了 "11"，重新生成出 "22"（同一条回答的第 2 版）
    messages = [
        {"role": "user", "content": "1", "ts": "t0"},
        {"role": "assistant", "content": "11", "ts": "t1"},
    ]
    V.normalize_messages(messages)
    V.append_variant(messages[1], "22")
    check("重新生成 = 同一条回答多一个版本（不是新增一条气泡）",
          len(messages) == 2 and V.variant_count(messages[1]) == 2, str(len(messages)))
    check("默认显示最后一版", messages[1]["variant_index"] == 1)
    check("content 镜像当前版", messages[1]["content"] == "22")
    check("两条版本都在版本表里", messages[1]["variants"] == ["11", "22"])

    # 用户把这条消息**编辑**成 "2"
    ok = V.apply_user_edit(messages, 0, "2")
    check("编辑成功产生新版本", ok and V.variant_count(messages[0]) == 2,
          str(messages[0].get("variants")))
    check("编辑后停在最后一版（正文是 2）",
          messages[0]["content"] == "2" and messages[0]["variant_index"] == 1)
    check("新版本下面还没有回复（旧回复整段挪进旧分支）", len(messages) == 1,
          str([m.get("content") for m in messages]))

    suffixes = messages[0]["branch_suffixes"]
    check("11/22 属于版本 1：存进 branch_suffixes[0]",
          isinstance(suffixes[0], list) and len(suffixes[0]) == 1
          and suffixes[0][0]["role"] == "assistant"
          and suffixes[0][0]["variants"] == ["11", "22"],
          json.dumps(suffixes[0], ensure_ascii=False))
    check("版本 2 的后继是空的（branch_suffixes[1] is None）", suffixes[1] is None)

    # 版本 2 下新问一次：AI 回 "33"
    messages.append({"role": "assistant", "content": "33", "ts": "t2"})
    V.normalize_messages(messages)
    V.sync_branches(messages)
    check("版本 2 的回复不会写进版本 1 那一格",
          suffixes[0][0]["variants"] == ["11", "22"] and suffixes[0][0]["content"] != "33",
          json.dumps(messages[0]["branch_suffixes"][0], ensure_ascii=False))
    check("版本 2 那一格拿到 33", messages[0]["branch_suffixes"][1][0]["content"] == "33")

    # 翻回版本 1 → 看到的必须是 11/22 那一支，而不是 33
    ok = V.switch_user_branch(messages, 0, 0)
    check("翻回版本 1 成功", ok)
    check("版本 1 的正文回来了", messages[0]["content"] == "1")
    check("版本 1 下面挂的是那条回答（停在最后一版 22）",
          len(messages) == 2 and messages[1]["content"] == "22",
          json.dumps([m.get("content") for m in messages], ensure_ascii=False))
    check("切回来时导航仍在（2 版都还在）",
          V.variant_count(messages[1]) == 2 and messages[1]["variants"] == ["11", "22"])

    # 再切回版本 2 → 33 必须回来（"先存后取"不能把任何一支弄丢）
    V.switch_user_branch(messages, 0, 1)
    check("再切回版本 2：正文 2 + 回复 33",
          messages[0]["content"] == "2" and [m.get("content") for m in messages[1:]] == ["33"],
          json.dumps([m.get("content") for m in messages], ensure_ascii=False))

    # 兄弟分支互不污染（深拷贝）：在版本 1 这一支里把回答翻到第 1 版（11）
    V.switch_user_branch(messages, 0, 0)
    V.set_ai_variant(messages, 1, 0)
    V.sync_branches(messages)
    check("在一支里翻页不会改掉另一支的那条回答",
          messages[0]["branch_suffixes"][1][0]["content"] == "33",
          json.dumps(messages[0]["branch_suffixes"][1], ensure_ascii=False))
    V.switch_user_branch(messages, 0, 1)
    check("切到版本 2 看到的仍是 33（没被版本 1 的翻页带跑）",
          messages[1]["content"] == "33")
    V.switch_user_branch(messages, 0, 0)
    check("版本 1 那一支的翻页结果也回来了（11）",
          messages[1]["content"] == "11" and messages[1]["variant_index"] == 0)

    # AI 气泡翻页走的是另一条路：不能顺手把下面的消息换掉
    before = len(messages)
    V.append_variant(messages[1], "44")            # 现在有 11 / 22 / 44 三版，停在 44
    check("AI 追加版本只动这一条回答，不新增/删除消息",
          len(messages) == before and V.variant_count(messages[1]) == 3,
          f"{len(messages)} / {messages[1].get('variants')}")
    V.set_ai_variant(messages, 1, 1)
    check("AI 翻页只换正文镜像（翻到第 2 版 = 22）",
          messages[1]["content"] == "22" and messages[1]["variant_index"] == 1
          and len(messages) == before,
          json.dumps(messages[1], ensure_ascii=False)[:200])

    # 重复内容不产生"看起来一模一样的两个版本"
    count = V.variant_count(messages[1])
    V.append_variant(messages[1], "44")
    check("同样的正文重复落盘不会多出重复版本",
          V.variant_count(messages[1]) == count)

    # 越界 / 非用户消息：一律拒绝，不乱改数据
    check("给 AI 消息走『切分支』会被拒绝", V.switch_user_branch(messages, 1, 0) is False)
    check("越界页码被拒绝", V.switch_user_branch(messages, 0, 77) is False)


# ===========================================================================
# 3) 上下文按选中版本组装，绝不混兄弟版本
# ===========================================================================
def _context_window(messages, upto):
    """复刻 desktop/api/ai.py 的 _context_messages 里"取哪几条消息"的那一步。

    真正的组装走 pymodels.core.ai.prompt.build_messages（它只读 role/content），
    所以只要**窗口本身**是按当前选中版本切的，上下文就不可能混 —— 这里测的就是窗口。
    """
    return messages[:upto]


def test_context_isolation():
    section("3. 上下文按「当前选中的版本」组装（兄弟版本不混）")
    messages = [{"role": "user", "content": "1", "ts": "t0"}]
    V.normalize_messages(messages)
    messages.append({"role": "assistant", "content": "11", "ts": "t1"})
    V.normalize_messages(messages)
    V.append_variant(messages[1], "22")
    V.sync_branches(messages)

    V.apply_user_edit(messages, 0, "2")
    messages.append({"role": "assistant", "content": "33", "ts": "t2"})
    V.normalize_messages(messages)
    V.sync_branches(messages)

    def role_content(pairs):
        return [(p["role"], p["content"]) for p in pairs]

    # 当前在版本 2：上下文里只应出现 "2" 和 "33"
    window = _context_window(messages, len(messages))
    check("版本 2 的上下文只有 2 / 33（不含 1、11、22）",
          role_content(window) == [("user", "2"), ("assistant", "33")],
          json.dumps(role_content(window), ensure_ascii=False))

    # 切回版本 1：上下文只应出现 "1" 和那条回答（当前显示第 2 版 = 22）
    V.switch_user_branch(messages, 0, 0)
    window = _context_window(messages, len(messages))
    check("切回版本 1 的上下文是 1 / 22（不含 2、33）",
          role_content(window) == [("user", "1"), ("assistant", "22")],
          json.dumps(role_content(window), ensure_ascii=False))

    # 在版本 1 这一支里把回答翻到第 1 版（11）→ 上下文跟着换，且不带 22
    V.set_ai_variant(messages, 1, 0)
    window = _context_window(messages, len(messages))
    check("AI 翻页后上下文用选中那一版（1 / 11）",
          role_content(window) == [("user", "1"), ("assistant", "11")],
          json.dumps(role_content(window), ensure_ascii=False))

    # 重新生成时：旧回答**不进**上下文（upto = 旧回答的下标）
    window = _context_window(messages, 1)
    check("重新生成的上下文截到旧回答之前（只有提问）",
          role_content(window) == [("user", "1")],
          json.dumps(role_content(window), ensure_ascii=False))

    # 用真实的 build_messages 走一遍：确认版本字段不会泄漏进给模型的文本
    from pymodels.core.ai import prompt as ai_prompt

    full = ai_prompt.build_messages(messages, [], "简体中文", context_rounds=0, keyword="")
    body = "\n".join(str(m.get("content") or "") for m in full[1:])
    check("发给模型的 messages 里没有 variants / branch_suffixes 字段文本",
          "variants" not in body and "branch_suffixes" not in body, body[:200])
    check("发给模型的尾部两条正好是界面上那两条",
          [(m["role"], m["content"]) for m in full[1:]] == [("user", "1"), ("assistant", "11")],
          json.dumps(full[1:], ensure_ascii=False))
    check("system 永远第一条且只有一条",
          full[0]["role"] == "system" and sum(1 for m in full if m["role"] == "system") == 1)


# ===========================================================================
# 4) 润色撤销
# ===========================================================================
def test_polish_undo():
    section("4. 润色 ↔ 撤销润色")
    from desktop.api.ai import AiDomain

    ai_py = read_repo_file(".ToolsGCP", "desktop", "api", "ai.py")
    check("polish 成功信封带 original 字段（前端撤销就有准）",
          "return _ok(text=polished, original=content)" in ai_py)

    clean = AiDomain._clean_polished
    check("剥掉「润色后：」前缀", clean("润色后：帮我找个工具") == "帮我找个工具",
          clean("润色后：帮我找个工具"))
    check("剥掉代码块包裹", clean("```\n帮我找个工具\n```") == "帮我找个工具",
          clean("```\n帮我找个工具\n```"))
    check("剥掉成对中文引号（只剥一层）", clean("“帮我找个工具”") == "帮我找个工具")
    check("正文里的引号不会被误剥", clean("他说「你好」之后走了") == "他说「你好」之后走了")
    check("空输入返回空串", clean("") == "")

    # 润色提示词（用户原话："润色提示词"要优化）—— 关键约束必须都在
    prompt = AiDomain.POLISH_SYSTEM_PROMPT
    for keyword, label in (("不要**回答**", "不回答问题"),
                           ("不要改变语言", "不改变语言"),
                           ("代码片段、命令、文件路径、URL", "保留代码"),
                           ("专有名词", "保留专有名词"),
                           ("只输出润色后的正文本身", "只给润色后的正文"),
                           ("不要增删信息", "保持原意（不增删信息）"),
                           ("最小改动", "原句通顺时最小改动")):
        check(f"润色提示词含「{label}」约束", keyword in prompt, keyword)

    # 前端撤销状态机：三条硬规则都在（丢了任何一条就会"撤销吃掉用户的修改"）
    app_js = read_repo_file(".ToolsGCP", "webui", "js", "app.js")
    check("前端存了润色前的原文（aiPolishOriginal）", "aiPolishOriginal" in app_js)
    check("有 clearPolishUndo（撤销态的清理入口）", "function clearPolishUndo" in app_js)
    check("程序改草稿走标记（setAiDraftProgrammatically）",
          "function setAiDraftProgrammatically" in app_js)
    check("watch(aiDraft) 用 flush:'sync'（否则程序赋值会被误判成用户编辑）",
          "watch(aiDraft, () => {" in app_js and "flush: 'sync'" in app_js)
    check("用户在润色后又手动编辑 → 清掉可撤销态",
          app_js.count("clearPolishUndo()") >= 3)
    check("润色按钮第二态画「返回上一个」图标", "#i-undo" in read_repo_file(
        ".ToolsGCP", "webui", "index.html"))
    check("模型没改（正文一样）时不画假的可撤销按钮",
          "if (aiPolishOriginal.value.trim() === polished.trim())" in app_js)


# ===========================================================================
# 5) 全部版本都持久化（重开程序还在）
# ===========================================================================
def test_persistence():
    section("5. 所有版本持久化（写盘 → 重新 load 还在）")
    tmp = _tmp_dir("persistence")
    try:
        store = ChatStore(chats_dir=tmp)
        session = store.new_session()
        session.messages = [{"role": "user", "content": "1", "ts": "t0"}]
        V.normalize_messages(session.messages)
        session.messages.append({"role": "assistant", "content": "11", "ts": "t1"})
        V.normalize_messages(session.messages)
        V.append_variant(session.messages[1], "22")
        V.sync_branches(session.messages)
        store.save(session)

        V.apply_user_edit(session.messages, 0, "2")
        session.messages.append({"role": "assistant", "content": "33", "ts": "t2"})
        V.normalize_messages(session.messages)
        V.sync_branches(session.messages)
        store.save(session)

        raw = json.load(open(store.path_of(session.id), encoding="utf-8"))
        check("版本字段真的写进了会话文件",
              raw["messages"][0].get("variants") == ["1", "2"]
              and isinstance(raw["messages"][0].get("branch_suffixes"), list),
              json.dumps(raw["messages"][0], ensure_ascii=False)[:300])

        reopened = ChatStore(chats_dir=tmp).load(session.id)
        check("重开后用户消息仍有 2 个版本", V.variant_count(reopened.messages[0]) == 2)
        check("重开后仍停在最后一版（默认显示最后一版）", reopened.messages[0]["content"] == "2")
        V.normalize_messages(reopened.messages)
        check("重开后版本 1 的 11/22 还在（没混进版本 2）",
              reopened.messages[0]["branch_suffixes"][0][0]["variants"] == ["11", "22"],
              json.dumps(reopened.messages[0]["branch_suffixes"], ensure_ascii=False)[:400])
        V.switch_user_branch(reopened.messages, 0, 0)
        check("重开后还能翻回版本 1 并看到 22",
              reopened.messages[0]["content"] == "1"
              and reopened.messages[1]["content"] == "22",
              json.dumps([m.get("content") for m in reopened.messages], ensure_ascii=False))
        check("切分支后 messages 条数变了（前端必须重新取下标）", len(reopened.messages) == 2)
        check("等待提示不会被当成消息存进会话",
              all("查看问题" not in str(m.get("content") or "")
                  for m in reopened.messages))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# 6) 流式：SSE 解析 + 节流收尾必达 + 中断
# ===========================================================================
class _FakeResponse:
    """假 HTTP 响应：按固定字节块吐出 SSE，模拟真实的任意切分"""

    def __init__(self, chunks, content_type="text/event-stream"):
        self._chunks = list(chunks)
        self._buf = b""
        self.headers = {"Content-Type": content_type}
        self.status = 200

    def read(self, size=-1):
        if size is None or size < 0:
            data = self._buf + b"".join(self._chunks)
            self._buf = b""
            self._chunks = []
            return data
        while len(self._buf) < size and self._chunks:
            self._buf += self._chunks.pop(0)
        out, self._buf = self._buf[:size], self._buf[size:]
        return out

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _delta_frame(text, finish=None):
    """造一帧 OpenAI 格式的 SSE（用 json.dumps 保证引号/大括号一定配平）"""
    frame = {"choices": [{"delta": {"content": text}, "finish_reason": finish}]}
    return ("data: " + json.dumps(frame, ensure_ascii=False) + "\n\n").encode("utf-8")


def _with_urlopen(response_or_raiser, body):
    """临时替换 urlopen 跑一段，跑完**必须**还原（不然污染同进程后面的用例）"""
    original = urllib.request.urlopen
    urllib.request.urlopen = response_or_raiser
    try:
        return body()
    finally:
        urllib.request.urlopen = original


def test_stream_sse_parsing():
    section("6. 流式 SSE 解析 / 收尾必达 / 中断")
    # 6.1 一帧被切成 5 个字节块 + **半个中文字**（UTF-8 3 字节被劈开）
    frame = _delta_frame("你好世界")
    pieces = [frame[:20], frame[20:41], frame[41:60], frame[60:], b"data: [DONE]\n\n"]
    received = []
    result = _with_urlopen(
        lambda request, *a, **kw: _FakeResponse(pieces),
        lambda: ai_client.chat_stream([{"role": "user", "content": "hi"}],
                                      "sk-test", "test-model", "https://api.test",
                                      on_chunk=lambda text: received.append(text)))
    check("半行 JSON + 半个中文字都能拼出完整正文（无乱码）",
          result.ok and result.content == "你好世界",
          f"ok={result.ok} kind={result.kind} msg={result.message} content={result.content!r}")
    check("没有把替换字符 \\ufffd 吐进正文", "\ufffd" not in result.content)
    check("on_chunk 收到的是**累计全文**（前端整段替换即可）",
          bool(received) and received[-1] == "你好世界", json.dumps(received, ensure_ascii=False))
    check("回调序列是单调变长的前缀（不会越回调越短）",
          all(received[i] in received[i + 1] for i in range(len(received) - 1))
          if len(received) > 1 else True,
          json.dumps(received, ensure_ascii=False))
    check("收尾强制推一次全文（最后一次回调 == 最终 content，节流不吞最后一段）",
          bool(received) and received[-1] == result.content)

    # 6.2 多帧累积（真实回答有很多帧）
    frames = [_delta_frame("A"), _delta_frame("B"), _delta_frame("C"), b"data: [DONE]\n\n"]
    seen = []
    result2 = _with_urlopen(
        lambda request, *a, **kw: _FakeResponse(frames),
        lambda: ai_client.chat_stream([{"role": "user", "content": "hi"}],
                                      "sk", "m", "https://api.test",
                                      on_chunk=lambda text: seen.append(text)))
    check("多帧累积成完整回答", result2.ok and result2.content == "ABC",
          f"content={result2.content!r}")

    # 6.3 网关不认 stream：Content-Type 是 json，整段返回也要能用
    body = json.dumps({"choices": [{"message": {"content": "整段回答"}}]}).encode("utf-8")
    result3 = _with_urlopen(
        lambda request, *a, **kw: _FakeResponse([body], content_type="application/json"),
        lambda: ai_client.chat_stream([{"role": "user", "content": "hi"}],
                                      "sk", "m", "https://api.test"))
    check("网关不支持流式时整段解析仍成功（前端只丢逐字效果）",
          result3.ok and result3.content == "整段回答",
          f"kind={result3.kind} msg={result3.message}")

    # 6.4 中断：should_stop 生效 → kind=cancelled
    state = {"stop": False}
    many = [_delta_frame("aaaa") for _ in range(60)] + [b"data: [DONE]\n\n"]
    result4 = _with_urlopen(
        lambda request, *a, **kw: _FakeResponse(many),
        lambda: ai_client.chat_stream([{"role": "user", "content": "hi"}],
                                      "sk", "m", "https://api.test",
                                      on_chunk=lambda text: state.update(stop=True),
                                      should_stop=lambda: state["stop"]))
    check("点了停止 → 不再继续（kind=cancelled）",
          (not result4.ok) and result4.kind == "cancelled",
          f"ok={result4.ok} kind={result4.kind}")

    # 6.5 服务端 401 要翻译成 auth，不能当成成功
    def raise401(request, *a, **kw):
        raise urllib.error.HTTPError("https://api.test", 401, "Unauthorized", {}, None)

    result5 = _with_urlopen(raise401,
                           lambda: ai_client.chat_stream([{"role": "user", "content": "hi"}],
                                                         "sk", "m", "https://api.test"))
    check("流式遇到 401 → kind=auth", (not result5.ok) and result5.kind == "auth",
          f"kind={result5.kind} msg={result5.message}")

    # 6.6 响应体里带 error 字段（200 + error）也要报失败
    bad = b'data: {"error": {"message": "\xe4BD\x99\xe9\xa2\x9d\xe4\xb8\x8d\xe8\xb6\xb3"}}\n\n'
    result6 = _with_urlopen(
        lambda request, *a, **kw: _FakeResponse([bad]),
        lambda: ai_client.chat_stream([{"role": "user", "content": "hi"}],
                                      "sk", "m", "https://api.test"))
    check("流式里的服务端 error 载荷 → 失败而不是空回答", not result6.ok,
          f"ok={result6.ok} kind={result6.kind} msg={result6.message}")

    # 6.7 没配 Key / 没模型：不联网就给可读原因
    r_nokey = ai_client.chat_stream([{"role": "user", "content": "x"}], "", "m")
    r_nomodel = ai_client.chat_stream([{"role": "user", "content": "x"}], "sk", "")
    check("没 Key / 没模型时不发起请求就给原因",
          r_nokey.kind == "no_key" and r_nomodel.kind == "no_model",
          f"{r_nokey.kind}/{r_nomodel.kind}")

    # 6.8 非流式的 chat() 没被改坏（回归）
    json_body = json.dumps({"choices": [{"message": {"content": "老路径"}}]}).encode("utf-8")
    r_old = _with_urlopen(
        lambda request, *a, **kw: _FakeResponse([json_body], content_type="application/json"),
        lambda: ai_client.chat([{"role": "user", "content": "x"}], "sk", "m", "https://api.test"))
    check("原 chat() 仍然正常（润色/测试连接/工具循环都靠它）",
          r_old.ok and r_old.content == "老路径", f"kind={r_old.kind}")

    # 6.9 推事件不能"每个字起一个线程"。
    from desktop.api.ai import AiDomain

    # ⚠️ 断言更新（本轮需求：「ai 输出多快逐字就有多快」，已确认「完全跟随到达速度」）：
    #    旧断言要求节流 ≥100ms，而 120ms 节流正是"整段突然出现"的成因之一，
    #    现在已经**取消节流**（改成 8ms 短轮询：有新增立刻推、没有就睡）。
    #    原来那条"防线程爆炸"的真实约束并没有丢 —— 它靠的是
    #    **单一 pump 线程顺序调用 push_event**，而不是靠时间窗口。
    #    所以这里改成校验真正的不变量：存在轮询间隔（>0，不能空转烧 CPU）
    #    且推送只在 pump 线程里发生（不再有 per-delta 起线程的写法）。
    check("推字轮询间隔存在（>0，不空转烧 CPU）",
          0 < AiDomain.STREAM_POLL_INTERVAL <= 0.02,
          str(AiDomain.STREAM_POLL_INTERVAL))
    check("逐字不再被 120ms 节流拖慢",
          AiDomain.STREAM_PUSH_INTERVAL <= 0.02,
          str(AiDomain.STREAM_PUSH_INTERVAL))
    _src = open(os.path.join(ROOT, ".ToolsGCP", "desktop", "api", "ai.py"),
                encoding="utf-8").read()
    check("每个 delta 不起新线程（_push 只在 pump/reader 里顺序调用）",
          "threading.Thread(target=self._push" not in _src)
    check("SSE 解析器认 [DONE]",
          ai_client._sse_data_lines("data: [DONE]\n\n")[0] == ["[DONE]"])


# ===========================================================================
# 7) 后端 AiDomain：版本化 send（假外壳 + mock 模型请求，不联网）
# ===========================================================================
class _FakeSettings:
    def __init__(self, values=None, api_key="sk-fake"):
        # model_name 必须有：`_credentials()` 认的是"设置里的模型名"，
        # 空 → 后端直接走 no_key 引导回答，那还测什么版本语义。
        base = {"model_name": "test-model"}
        base.update(values or {})
        self.settings = base
        self._api_key = api_key

    def get_api_key(self, provider=""):
        return self._api_key

    def key_tail(self, provider=""):
        return "fake"


class _FakeShell:
    """只够 AiDomain 用的假外壳：能读设置、能收事件（不真起 WebView2）"""

    def __init__(self, values=None, api_key="sk-fake"):
        self.settings_manager = _FakeSettings(values, api_key)
        self.events = []
        self.api = None
        self._teardown_started = False
        self._quitting = False

    def current_language(self):
        return "简体中文"

    def push_event(self, name, payload):
        self.events.append((name, payload))


def _make_domain(tmp, api_key="sk-fake"):
    """造一个指向临时目录的 AiDomain，并把"请求模型"那一步换成可控假回答。

    ⚠️ 这里只 mock `_chat_with_tools`（网络那一步），版本树 / 落盘 / 上下文截取
       全都跑真代码 —— 否则测不到我们真正改的东西。
    """
    from desktop.api.ai import AiDomain

    shell = _FakeShell(api_key=api_key)
    domain = AiDomain(shell)
    store = ChatStore(chats_dir=tmp)
    type(domain).store = property(lambda self: store)
    replies = []

    def fake_chat(messages, api_key, model, api_base, locale="zh_CN", allow_tools=False,
                  thinking=None, max_tokens=0):
        # 每问一次给一条**不同**的回答，方便验证"重新生成 = 多一个版本"
        # ⚠️ 返回形状要和真 _chat_with_tools 一致：(result, rounds, created_plugins)
        # ⚠️ `thinking` 是本轮新增的三态思考开关形参，mock 必须收下（否则 TypeError）
        # ⚠️ `max_tokens` 是「列举全部资源」垫高输出预算那轮新增的形参
        #    （_chat_with_tools 会显式传 0 = 不表态），mock 同样必须收下。
        text = "回答-" + str(len(replies) + 1)
        replies.append({"text": text, "messages": list(messages)})
        return ai_client.ChatResult(True, content=text), 0, []

    domain._chat_with_tools = fake_chat
    return domain, shell, store, replies


def _fake_chat_returns(result):
    """把单个 ChatResult 包成 _chat_with_tools 的返回三元组（result, rounds, created）
    ⚠️ `max_tokens` 形参是「列举全部资源垫高输出预算」那轮 _chat_with_tools 新增的
       （恒传，0=不表态）；mock 不收就会 TypeError，让"请求失败"用例变成"签名错了"。"""
    def wrapper(messages, api_key, model, api_base, locale="zh_CN", allow_tools=False,
                thinking=None, max_tokens=0):
        return result, 0, []
    return wrapper


def test_send_versions_end_to_end():
    section("7. 后端 send / switch_variant：版本语义端到端（mock 模型请求）")
    tmp = _tmp_dir("sendver")
    try:
        domain, shell, store, replies = _make_domain(tmp)

        first = domain.send("", "帮我找个局域网传文件的工具", "standard")
        check("普通发送成功（ok=true）", first.get("ok") is True, str(first)[:250])
        sid = first["session_id"]
        msgs = first["session"]["messages"]
        check("用户消息 + 回答都进了历史", len(msgs) == 2, json.dumps(msgs)[:300])
        check("新回答带上了版本字段（前端才画得出导航）",
              msgs[1].get("variant_index") == 0 and msgs[0].get("variants") is not None
              or V.variant_count(msgs[1]) >= 1)
        check("第一条用户消息 = 会话标题", first["session"]["title"] == "帮我找个局域网传文件的工具",
              first["session"]["title"])

        # 重新生成：同一条回答多一个版本，**不摘掉**旧回答
        second = domain.send(sid, "帮我找个局域网传文件的工具", "standard",
                             resend=True, assistant_index=1)
        check("重新生成不新增气泡（条数仍是 2）",
              len(second["session"]["messages"]) == 2,
              json.dumps(second["session"]["messages"], ensure_ascii=False)[:400])
        regenerated = second["session"]["messages"][1]
        check("重新生成 → 那条回答有 2 个版本且停在最后一版",
              regenerated.get("variant_index") == 1
              and len(regenerated.get("variants") or []) == 2
              and regenerated["content"].startswith("回答-2"),
              json.dumps(regenerated, ensure_ascii=False)[:300])
        check("旧回答（回答-1）还在版本表里、没被删",
              (regenerated.get("variants") or [])[0].startswith("回答-1"),
              json.dumps(regenerated.get("variants"), ensure_ascii=False))
        check("重问没在历史里留下第二条一样的提问",
              len([m for m in second["session"]["messages"] if m["role"] == "user"]) == 1)

        # 关键：重新生成时**旧回答不进上下文**
        asked = replies[-1]["messages"]
        tail = [(m["role"], m["content"]) for m in asked[1:]]
        check("重新生成的上下文里没有那条旧回答（只有提问）",
              tail == [("user", "帮我找个局域网传文件的工具")],
              json.dumps(tail, ensure_ascii=False)[:300])

        # 编辑后重发：用户消息变新版本，旧回复整段进旧分支
        third = domain.send(sid, "改成找一个离线也能用的工具", "standard",
                            resend=True, user_index=0)
        after_edit = third["session"]["messages"]
        user0 = after_edit[0]
        check("编辑后用户消息有 2 个版本（原句 + 编辑后的那句）",
              len(user0.get("variants") or []) == 2
              and user0["content"] == "改成找一个离线也能用的工具",
              json.dumps(user0.get("variants"), ensure_ascii=False))
        check("新版本下面挂的是**这一次的新回答**（不是旧分支那条）",
              len(after_edit) == 2 and after_edit[1]["content"].startswith("回答-3"),
              json.dumps([m.get("content") for m in after_edit], ensure_ascii=False))
        check("编辑后发给模型的上下文是编辑后的那句",
              [(m["role"], m["content"]) for m in replies[-1]["messages"][1:]][-1]
              == ("user", "改成找一个离线也能用的工具"),
              json.dumps(replies[-1]["messages"][-2:], ensure_ascii=False)[:300])

        # 翻回第一个版本 → 11/22 那一支（这里 = 回答-1/回答-2）必须整段回来
        back = domain.switch_variant(sid, 0, 0)
        back_msgs = back["session"]["messages"]
        check("switch_variant 返回整个会话", back.get("ok") and len(back_msgs) >= 2,
              json.dumps(back_msgs, ensure_ascii=False)[:300])
        check("翻回版本 1 后正文是当初那句提问",
              back_msgs[0]["content"] == "帮我找个局域网传文件的工具",
              back_msgs[0]["content"])
        check("翻回版本 1 后那条回答的两个版本都在（回答-1 / 回答-2）",
              len(back_msgs[1].get("variants") or []) == 2,
              json.dumps(back_msgs[1], ensure_ascii=False)[:300])
        check("切到版本 1 后**没有**把版本 3 的新回答带进来",
              not any("回答-3" in str(m.get("content") or "") for m in back_msgs),
              json.dumps([m.get("content") for m in back_msgs], ensure_ascii=False))

        # 越界下标：明确失败，绝不改数据
        bad = domain.switch_variant(sid, 999, 0)
        check("越界下标返回 ok=false + stale_index",
              bad.get("ok") is False and bad.get("kind") == "stale_index", str(bad)[:200])

        # 磁盘检查：全部版本都在磁盘上
        reopened = store.load(sid)
        user_msgs = [m for m in reopened.messages if m["role"] == "user"]
        check("磁盘上的会话也带完整版本树",
              len(user_msgs[0].get("variants") or []) == 2
              and user_msgs[0].get("variant_index") == 0
              and len(user_msgs[0].get("branch_suffixes") or []) == 2,
              json.dumps(user_msgs[0], ensure_ascii=False)[:300])
        check("两个版本各自的后继都还在磁盘上（兄弟分支没丢）",
              all(isinstance(slot, list) and slot for
                  slot in (user_msgs[0].get("branch_suffixes") or [])),
              json.dumps(user_msgs[0].get("branch_suffixes"), ensure_ascii=False)[:400])
        check("会话文件里没有任何『正在查看问题 / 正在思考』之类的占位消息",
              all("查看问题" not in str(m.get("content") or "")
                  and "正在思考" not in str(m.get("content") or "")
                  for m in reopened.messages),
              json.dumps([m.get("content") for m in reopened.messages], ensure_ascii=False))
        check("会话文件里没有 variants 之外的临时流式字段（streaming 不落盘）",
              all("streaming" not in m for m in reopened.messages))

        # 空消息 / 不存在的会话：可读失败，不崩
        check("空消息返回 ok=false", domain.send(sid, "", "standard").get("ok") is False)
        check("读不存在的会话返回 ok=false",
              domain.session("no-such-session").get("ok") is False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_no_key_and_errors():
    section("7b. 没配 Key / 请求失败时的落盘与版本")
    tmp = _tmp_dir("nokey")
    try:
        # 没 Key → 先落盘用户消息 + 固定引导回答（PyQt 版同款行为）
        domain, _shell, store, _replies = _make_domain(tmp, api_key="")
        first = domain.send("", "随便问一句", "standard")
        check("没 Key 时 ok=true + kind=no_key（引导回答也是正常一条消息）",
              first.get("ok") is True and first.get("kind") == "no_key", str(first)[:200])
        check("没 Key 时用户消息仍然落盘", len(store.load(first["session_id"]).messages) == 2)

        # 请求失败 → 报错气泡带 error/kind 落盘，重新生成成功后不该还是红的
        domain2, _shell2, store2, _r2 = _make_domain(_tmp_dir("fail"))
        domain2._chat_with_tools = _fake_chat_returns(
            ai_client.ChatResult(False, kind="network", message="连不上服务器：boom"))
        failed = domain2.send("", "问一句", "standard")
        check("请求失败返回 ok=false 且错误已落盘",
              failed.get("ok") is False and failed.get("persisted") is True, str(failed)[:200])
        fmsg = store2.load(failed["session_id"]).messages[1]
        check("报错气泡带 error 标记（历史里能还原成报错样式）",
              fmsg.get("error") is True and fmsg.get("kind") == "network", str(fmsg)[:200])

        domain2._chat_with_tools = _fake_chat_returns(
            ai_client.ChatResult(True, content="这次成功了"))
        retried = domain2.send(failed["session_id"], "问一句", "standard",
                              resend=True, assistant_index=1)
        rmsg = store2.load(retried["session_id"]).messages[1]
        check("失败后重新生成成功 → 新版本不再被标成报错",
              rmsg.get("error") is False and rmsg["content"] == "这次成功了", str(rmsg)[:250])
        check("重新生成后那条有 2 个版本（旧的报错也留着可翻）",
              len(rmsg.get("variants") or []) == 2, json.dumps(rmsg, ensure_ascii=False)[:300])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def store_load_answer(store, sid):
    """读会话里**最后一条 assistant** 的正文（流式落盘校验用）"""
    loaded = store.load(sid)
    for message in reversed(loaded.messages or []):
        if str(message.get("role") or "") == "assistant":
            return str(message.get("content") or "")
    return ""


def test_stream_fallback_contract():
    section("8. 流式的降级契约（推不动就别流式）")
    from desktop.api.ai import AiDomain

    # ⚠️ 测试**绝不联网**：把 chat_stream 换成"立刻返回一帧"的假流。
    #    不然 send_stream 起的后台线程会真的去打 api.deepseek.com（CI 上慢且不稳定，
    #    还会在日志里留下 auth 报错，看着像代码有问题）。
    real_stream = ai_client.chat_stream

    def fake_stream(messages, api_key, model, api_base, max_tokens=0, temperature=0.7,
                    timeout=None, on_chunk=None, should_stop=None,
                    on_reasoning=None, thinking=None):
        # ⚠️ `on_reasoning` / `thinking` 是本轮新增的（思考与正文分家），mock 必须收下
        if on_chunk:
            on_chunk("假的")
            on_chunk("假的流式回答")
        return ai_client.ChatResult(True, content="假的流式回答")

    ai_client.chat_stream = fake_stream
    tmp = _tmp_dir("streamfb")
    try:
        domain, shell, _store, _replies = _make_domain(tmp)

        # 正常：能起流，返回 stream_id
        result = domain.send_stream("", "随便问一句", "standard")
        check("能推事件时 send_stream 返回 stream_id",
              result.get("ok") is True and bool(result.get("stream_id")), str(result)[:200])
        check("send_stream 把刚落盘的用户消息带回来（气泡立刻出现；回答到得快也会一起带上）",
              bool(result.get("session"))
              and result["session"]["messages"][0]["role"] == "user"
              and len(result["session"]["messages"]) >= 1,
              json.dumps(result.get("session") or {}, ensure_ascii=False)[:250])

        # 等后台线程收尾（最多 3s），确认 done 事件必达 + 回答落盘
        sid = result["session_id"]
        types = []
        deadline = time.time() + 3.0
        while time.time() < deadline:
            types = [p.get("type") for n, p in shell.events if n == "ai.stream"]
            if any(t in ("done", "error", "cancelled") for t in types):
                break
            time.sleep(0.05)
        check("流式跑完会推 done（收尾事件必达）", "done" in types, str(types))
        check("done 事件带整会话 + 累计正文",
              any(p.get("type") == "done" and p.get("text") == "假的流式回答"
                  for _n, p in shell.events),
              json.dumps([p for _n, p in shell.events], ensure_ascii=False)[:300])
        check("流式的回答真的落盘了（带版本字段）",
              store_load_answer(ChatStore(chats_dir=tmp), sid) == "假的流式回答")
        check("等待提示那句**没有**被当成消息写进会话",
              not any("查看问题" in str(m.get("content") or "")
                      for m in ChatStore(chats_dir=tmp).load(sid).messages))

        # 外壳正在退出 → 不许走流式（done 永远到不了，界面会卡住）
        shell._teardown_started = True
        result2 = domain.send_stream("", "随便问一句", "standard")
        check("正在退出时 send_stream 直接 kind=fallback",
              result2.get("ok") is False and result2.get("kind") == "fallback",
              str(result2)[:200])
        shell._teardown_started = False

        # 没有 push_event 的外壳（预览模式 mock）→ 同样 fallback
        class _NoPushShell(_FakeShell):
            push_event = None

        domain3 = AiDomain(_NoPushShell())
        store3 = ChatStore(chats_dir=_tmp_dir("streamfb3"))
        type(domain3).store = property(lambda self: store3)
        result3 = domain3.send_stream("", "随便问一句", "standard")
        check("外壳推不了事件时 send_stream 立刻 fallback（不空等）",
              result3.get("ok") is False and result3.get("reason") == "no_event_channel",
              str(result3)[:200])

        # 空消息 / 未知 id 的中断都不能崩
        check("空消息流式返回 ok=false", domain.send_stream("", "", "standard").get("ok") is False)
        check("cancel_stream 对未知 id 也安全", domain.cancel_stream("does-not-exist").get("ok") is True)

        # 推事件前必须检查退出闸门（AGENTS 第 8 条）
        source = read_repo_file(".ToolsGCP", "desktop", "api", "ai.py")
        check("推事件前有统一的 _can_push() 闸门", "def _can_push" in source)
        check("闸门同时看 _teardown_started 与 _quitting",
              "_teardown_started" in source and "_quitting" in source)
        check("读流线程回调里不直接推事件（只记累计文本，交给 pump）",
              "只在**记**最新的累计全文" in source or "只**记**最新的累计全文" in source)
    finally:
        ai_client.chat_stream = real_stream
        shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# 9) 界面改动的静态契约（跑不了 GUI，就钉住关键实现点）
# ===========================================================================
def test_ui_contracts():
    section("9. 界面 5 项改动的静态契约")
    html = read_repo_file(".ToolsGCP", "webui", "index.html")
    icons = read_repo_file(".ToolsGCP", "webui", "js", "icons.js")
    css = read_repo_file(".ToolsGCP", "webui", "css", "ai-fixes.css")
    app_js = read_repo_file(".ToolsGCP", "webui", "js", "app.js")

    # ① 发送按钮
    check("发送按钮用纸飞机图标（两处：独立页 + 抽屉）", html.count("#i-send") >= 2,
          str(html.count("#i-send")))
    check("icons.js 里有 send（纸飞机）", "\n  send:" in icons)
    check("icons.js 里有 stop（忙态）", "\n  stop:" in icons)
    check("发送按钮圆角方形（radius 10，不是 999 圆）",
          ".ai-send {" in css and "border-radius: 10px" in css
          and "border-radius: 999px" not in css.split(".ai-send {")[1][:400])
    check("禁用态 cursor: not-allowed", re_search(css, r"\.ai-send:disabled\s*{[^}]*not-allowed"))
    check("hover 效果排除 disabled（禁用时不变亮）",
          re_search(css, r"\.ai-send:not\(:disabled\):hover"))
    check("玻璃档下禁用态也被钉住（不被渐变底色盖回去）",
          re_search(css, r"data-fx=\"glass\"\] \.ai-send:disabled"))
    check("模板上 disabled 属性是真禁用", ':disabled="aiBusy ? false : !aiDraft.trim()"' in html)

    # ② 历史行手型
    check("历史对话行 cursor: pointer",
          re_search(css, r"\.history-item[,\s][^}]*cursor: pointer")
          or re_search(css, r"\.history-item\s*,[^}]*cursor: pointer"))
    check("行内按钮也各自有手型", re_search(css, r"\.history-item \.icon-btn[^}]*cursor: pointer")
          or ".history-item .icon-btn" in css)
    check("行内按钮禁用态退回 not-allowed", "button:disabled" in css and "not-allowed" in css)

    # ③ 润色
    check("润色按钮两态切图标", "#i-undo" in html and "#i-robot" in html)
    check("润色按钮可撤销态有 .is-undo 样式", ".ai-polish.is-undo" in css)

    # ④ 版本导航 + 原地编辑
    check("版本导航 ◀ ▶（两处都画）", html.count('class="variant-nav"') >= 2)
    check("只有一版时不渲染导航", html.count("aiVariantCount(m) > 1") >= 2)
    check("导航默认停在最后一版（后端 variant_index）",
          "active_variant" in app_js or "aiVariantPage" in app_js)
    check("用户气泡有编辑入口", "aiStartEdit(i)" in html)
    check("编辑态按钮换成 ✕ / ✓", "aiAcceptEdit(i)" in html and "aiCancelEdit" in html)
    check("编辑框复用同一个 .bubble 类（尺寸保持）",
          'class="bubble ai-bubble-edit is-user"' in html)
    check("编辑框宽度按实测尺寸起步（不跳位）", "aiEditBoxStyle" in html and "aiEditBox" in app_js)
    check("翻版本走后端并整体重建", "ai.switch_variant" in app_js and
          "sessionToMessages(result.session)" in app_js)
    check("切会话时丢弃旧流（防迟到 delta 写字）",
          "clearStreamBubble()" in app_js and "if (id !== aiStreamId) return;" in app_js)

    # ⑤ 等待提示 + 流式
    check("等待提示独立于消息列表（.ai-pending）", html.count('class="ai-pending"') >= 2)
    check("省略号是三个 dot（CSS 动画）",
          html.count("dot-1") >= 2 and "@keyframes ai-dot2" in css and "@keyframes ai-dot3" in css)
    # 等待提示现在**有两个落点**（本轮需求：重新生成时它在**原位置取代**那颗气泡本体）：
    #   · 普通提问（下面还没有 AI 气泡可落位）：列表末尾那一行
    #     `v-if="aiBusy && aiPending && aiPendingAfter < 0"`
    #   · 重新生成 / 编辑重发：`v-else-if="aiRegenPlaceholder(i)"` 直接画在那颗气泡的位置上
    #     （用户要求"原本的聊天气泡消失、用正在xxx代替"，所以不再是"挂在下面一颗"）。
    # 两处都仍由 aiBusy && aiPending 驱动（"它不是一条消息"这个约束不变）。
    check("等待提示由 aiBusy && aiPending 驱动（不是消息）",
          'v-if="aiBusy && aiPending && aiPendingAfter' in html)
    check("等待提示会**原地取代**被重生的那条回答（不是挂在末尾、也不是多挂一颗）",
          "aiRegenPlaceholder(i)" in html and "function aiRegenPlaceholder" in app_js)
    check("重新生成期间会把下面的旧分支内容先藏起来（用户报的『全都不消失』）",
          "aiRowShown(i)" in html and "function aiRowShown" in app_js and "aiCutAfter" in app_js)
    check("前端收 ai.stream 事件", "onEvent('ai.stream'" in app_js)
    check("第一段 delta 到达就关掉等待提示",
          re_search(app_js, r"type === 'delta'[\s\S]{0,400}aiPending\.value = false"))
    check("流式光标（看得出还在吐字）", ".ai-stream-cursor" in css and "ai-stream-cursor" in html)
    check("流式有看门狗兜底（收尾包丢了也不会永久卡住）", "armAiStreamWatchdog" in app_js)
    # ⚠️ 断言更新（本轮需求：「删除设置中的回答逐字输出选项 我本来设计的就是逐字输出
    #    不需要这个选项控制」）：那一行 UI 已删除，但**设置键 ai_stream_enabled 保留**
    #    （旧配置兼容），发送路径恒走流式。所以校验点从"有这一行"改成
    #    "键还在（兼容）但设置页不再渲染它、发送恒走流式"。
    check("逐字输出开关已从设置页移除，但设置键保留（旧配置兼容）",
          "ai_stream_enabled: true" in app_js                  # 默认值表里还有这个键（无引号对象字面量）
          and "{ key: 'ai_stream_enabled'" not in app_js)      # 但不再有这一行设置项
    check("发送路径恒走流式（不再读 ai_stream_enabled）",
          "const wantStream = true;" in app_js
          and "settingOn(settings.ai_stream_enabled)" not in app_js)
    check("constants.py 没被这次改动加键（避开 Lead 的改动）",
          "ai_stream_enabled" not in read_repo_file(".ToolsGCP", "modules", "pymodels",
                                                    "constants.py"))
    check("ai-fixes.css 已在 index.html 末尾引入",
          "/static/css/ai-fixes.css" in html and html.index("ai-fixes.css") > html.index("download-ui.css"))

    # 三语同步
    keys = ["ai_pending", "ai_undo_polish_tip", "ai_polish_undone", "ai_stream_enable",
            "ai_stream_enable_tip", "ai_stream_lost", "ai_version_prev", "ai_version_next",
            "ai_variant_stale", "ai_edit", "ai_edit_send", "ai_edit_empty"]
    markers = {"zh_CN": "AI正在查看问题", "zh_TW": "AI正在檢視問題",
               "en_US": "AI is reading your question"}
    for locale, marker in markers.items():
        text = read_repo_file(".ToolsGCP", "modules", "languages", locale, "set_language.json")
        check(f"{locale} 有等待提示文案「{marker}」", marker in text, marker)
        missing = [k for k in keys if f'"{k}"' not in text]
        check(f"{locale} 12 个新 key 齐全", not missing, "缺: " + ",".join(missing))

    # 禁区没被碰（自查：只报告、不判失败 —— Lead 自己也在改这些文件，
    # git status 里出现它们是正常的；要确认的是**我这次的改动没写进它们**）
    touched = _git_touched(FORBIDDEN_FILES)
    if touched:
        print("     ℹ️ 禁区文件在工作区有改动（Lead 的改动，不是我的）：", "; ".join(touched))
    check("禁区文件里没有我这次的改动痕迹", not _forbidden_contains_my_markers(),
          "见 _forbidden_contains_my_markers 的输出")


def re_search(text, pattern):
    import re
    return bool(re.search(pattern, text))


FORBIDDEN_FILES = [
    ".ToolsGCP/desktop/api/update.py",
    ".ToolsGCP/desktop/api/downloader.py",
    ".ToolsGCP/desktop/api/resources.py",
    ".ToolsGCP/desktop/webhost.py",
    ".ToolsGCP/desktop/shell.py",
    ".ToolsGCP/desktop/native/frame.py",
    ".ToolsGCP/modules/pymodels/constants.py",
    ".ToolsGCP/native/hotkey.py",
    ".ToolsGCP/modules/pymodels/core/cloud_resources.py",
]
# 我这次改动里的"签名"字符串：只要它们出现在禁区文件里，就说明我越界写了代码
MY_MARKERS = ("send_stream", "ai_versions", "variant_index", "branch_suffixes",
              "POLISH_SYSTEM_PROMPT", "ai_pending", "stream_id")


def _git_touched(paths):
    """git 里这些文件是否有改动（信息用：Lead 也在改同一批文件）"""
    import subprocess
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--"] + paths,
                             cwd=ROOT, capture_output=True, text=True, timeout=20)
    except Exception:                                     # noqa: BLE001
        return []
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def _forbidden_contains_my_markers():
    """禁区文件的**当前内容**里有没有我这次改动的签名串（有 = 我越界了）"""
    hits = []
    for rel in FORBIDDEN_FILES:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except Exception:                                 # noqa: BLE001
            continue
        for marker in MY_MARKERS:
            if marker in text:
                hits.append(f"{rel}:{marker}")
    if hits:
        print("     ⚠️ 禁区文件里发现我的改动痕迹：", "; ".join(hits))
    return hits


def main():
    print("=" * 72)
    print("GCP-AI 版本树 / 流式 / 润色 测试")
    print("=" * 72)
    tests = [test_legacy_read, test_user_versions_and_branches, test_context_isolation,
             test_polish_undo, test_persistence, test_stream_sse_parsing,
             test_send_versions_end_to_end, test_no_key_and_errors,
             test_stream_fallback_contract, test_ui_contracts]
    started = time.time()
    for test in tests:
        try:
            test()
        except Exception as exc:                          # noqa: BLE001
            import traceback
            FAIL.append(f"{test.__name__} 抛异常")
            print(f"  ✗ {test.__name__} 抛异常：{type(exc).__name__}: {exc}")
            traceback.print_exc()

    print("\n" + "=" * 72)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项（{time.time() - started:.2f}s）")
    if FAIL:
        print("失败清单：")
        for name in FAIL:
            print(f"  - {name}")
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
