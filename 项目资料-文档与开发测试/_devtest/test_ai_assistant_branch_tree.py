"""AI 版本树**行为**测试（task-5）：assistant 消息的「按版本存后继」——真 AiDomain + 真 ChatStore。

用户原话（这轮要修的就是它）：
「我点击中间的AI的重新生成，但是下面的内容是上一版AI的对话，bug 性的下面所有内容属于所有版了，
  全都不消失，存在着；用户的编辑也一样。」
→ `session.messages` 必须永远只是**当前显示的那一条线**。AI 重新生成（或翻 AI 版本）时，
  它下面那串下游对话属于**旧版本的分支**：先从当前线消失、按版本存进
  `assistant.branch_suffixes[旧页码]`（深拷贝，含那串消息各自的多版本），
  翻回旧版时原样回来；翻到从未存过后继的版本 = **空后继**（绝不把当前后继复制给所有版本）。

覆盖 task-5 验收里的 5 条（本文件全部跑真逻辑，只 mock 掉**模型请求**那一步、落临时目录）：
  ① 中间那条 AI 重新生成 → 下游从当前线消失，翻回旧版原样回来（条数/正文/各自多版本一致）
  ② 翻 AI 版本 = 整段换后继（新版本空、旧版本有）
  ③ 老会话（assistant 没有 branch_suffixes）不崩，翻版本**不把后继复制到所有版本**
  ④ 用户编辑重发那条路行为不变（回归）
  ⑤ 磁盘落盘与内存一致（重新 load 再断言一遍）
另加边界：深拷贝独立性、模型吐回同样正文时不清空当前后继、`_message_view` 的 has_branch 契约。

⚠️ 测试目录写在 `项目资料-文档与开发测试/_tmp-ai-test/`（被 .gitignore 覆盖、跑完即删）：
   沙箱里系统 %TEMP% 可能不可写，而 `<数据根>/config/chats` 是**用户真实数据，绝不碰**。
跑法：python "项目资料-文档与开发测试/_devtest/test_ai_assistant_branch_tree.py"
"""
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
for _ in range(6):
    ROOT = os.path.dirname(ROOT)
    if os.path.isdir(os.path.join(ROOT, ".ToolsGCP")):
        break
sys.argv = [os.path.join(ROOT, "ToolsGCP.pyw")]
sys.path[:0] = [os.path.join(ROOT, ".ToolsGCP"), os.path.join(ROOT, ".ToolsGCP", "modules")]
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                     # noqa: BLE001
        pass

from pymodels.core.ai import chat_store as cs             # noqa: E402
from pymodels.core.ai import versions as V                # noqa: E402
from desktop.api.ai import AiDomain                       # noqa: E402

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print(f"  {'OK  ' if condition else 'FAIL'} {name}"
          + ("" if condition else f"   <<< {detail}"))


def section(title):
    print(f"\n== {title} ==")


def _tmp_dir(prefix: str) -> str:
    base = os.path.join(ROOT, "项目资料-文档与开发测试", "_tmp-ai-test", prefix)
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base, exist_ok=True)
    return base


class _Result:
    """冒充 client.chat 的返回值（ok/kind/message/content）"""

    ok = True
    kind = ""
    message = ""

    def __init__(self, content):
        self.content = content


class _Shell:
    settings_manager = None


def make_domain(chats_dir, replies):
    """真 AiDomain + 真 ChatStore；只把「网络那一步」换成固定回复。

    落盘 / 版本树 / 下标漂移这些**被测逻辑一律走原样**，否则测的就不是用户的 bug 了。
    """
    store = cs.ChatStore(chats_dir=chats_dir)

    class _TestDomain(AiDomain):
        """store 是 property，只能靠子类覆盖，不能往实例上赋值（会 AttributeError）"""

        @property
        def store(self):
            return store

    dom = _TestDomain(_Shell())
    state = {"i": 0}
    seen = []                       # 每次请求发给模型的上下文（验"当前线"不变式）

    dom._credentials = lambda: {"api_key": "k", "model": "m", "api_model": "m",
                                "api_base": "", "missing": [], "key_tail": ""}
    dom._context_messages = lambda session, content, reply_mode, upto: (
        [dict(m) for m in session.messages[:max(0, upto if upto is not None
                                                else len(session.messages))]],
        False, "zh_CN")
    dom._resources = lambda: []
    dom._clean_reply = lambda text: text

    def fake_chat(ctx, *_a, **_kw):
        seen.append(ctx)
        text = replies[min(state["i"], len(replies) - 1)]
        state["i"] += 1
        return _Result(text), 0, []

    dom._chat_with_tools = fake_chat
    return dom, store, seen


def shape(msgs):
    """一条线的"可观察形状"：逐条 role / 正文 / 当前页 / 版本表 / 报错表。

    用于断言"翻回来**原样**回来"——数量、内容、每条自己的多版本都要一致。
    """
    return [{"role": m.get("role"), "content": m.get("content"),
             "vi": m.get("variant_index"), "vars": list(m.get("variants") or []),
             "err": m.get("variant_error")} for m in msgs]


def brief(msgs):
    return json.dumps(shape(msgs), ensure_ascii=False)


def line_key(msgs):
    """前端 view 与磁盘原文**都有**的最小可观察列（view 不带单版本 variants/报错表）。

    凡是断言"界面上看到的那条线"就用它；要断言"多版本/报错表原样"就读磁盘用 shape()。
    """
    return [(m.get("role"), m.get("content"), m.get("variant_index")) for m in msgs]


def slots(message):
    return message.get("branch_suffixes")


# ---------------------------------------------------------------------------
# ① 中间那条 AI 重新生成：下游整段让位（+ ⑤ 磁盘一致）
# ---------------------------------------------------------------------------
def test_middle_answer_regen_detaches_downstream():
    section("① 中间那条 AI 重新生成 → 下面那串下游整段让位，翻回旧版原样回来")
    tmp = _tmp_dir("assistant-regen")
    try:
        dom, store, seen = make_domain(tmp, ["回答1-新版"])
        s = store.new_session()
        s.messages = [
            {"role": "user", "content": "问题甲", "ts": "t0"},
            {"role": "assistant", "content": "回答1", "ts": "t1"},
            {"role": "user", "content": "追问一句", "ts": "t2"},
            {"role": "assistant", "content": "回答2", "ts": "t3"},
        ]
        V.normalize_messages(s.messages)
        V.append_variant(s.messages[3], "回答2-第二版")     # 下游那条自己也带多版本
        V.normalize_messages(s.messages)
        V.sync_branches(s.messages)
        store.save(s)
        before = shape(s.messages)
        before_tail = shape(s.messages[2:])          # 要"原样回来"的是**下游那串**

        res = dom.send(s.id, "问题甲", "", True, "", 1)      # assistant_index = 1（中间那条）
        check("重新生成返回 ok", res.get("ok") is True, str(res)[:200])
        line = res["session"]["messages"]
        print("   重新生成后:", brief(line))

        check("当前线只剩 2 条：下游「追问一句 / 回答2」整段让位（这就是用户报的 bug）",
              len(line) == 2, f"实际 {len(line)} 条")
        check("被重生那条有 2 个版本、停在新版、正文镜像新版",
              line[1].get("variant_index") == 1
              and (line[1].get("variants") or []) == ["回答1", "回答1-新版"]
              and line[1]["content"] == "回答1-新版",
              json.dumps(line[1], ensure_ascii=False)[:250])
        check("★ 下游不在当前线上（几个版本的后继没有混着显示）",
              not any(m["content"] in ("追问一句", "回答2", "回答2-第二版") for m in line[1:]),
              brief(line))
        check("前端契约：assistant 也带 has_branch（旧版挂下游=True / 新版空=False）",
              line[1].get("has_branch") == [True, False],
              json.dumps(line[1].get("has_branch")))
        check("上下文只有这条提问（旧回答/旧下游都不进上下文）",
              [(m.get("role"), m.get("content")) for m in seen[-1]] == [("user", "问题甲")],
              json.dumps(seen[-1], ensure_ascii=False)[:200])

        # 数据绝不能丢：下游整串（含它自己的多版本）存在**旧版本那一格**
        disk = store.load(s.id)
        a1 = disk.messages[1]
        suffix = (slots(a1) or [None, None])[0]
        check("★ 下游整串存进 assistant.branch_suffixes[0]（2 条：追问 + 回答2）",
              isinstance(suffix, list) and len(suffix) == 2,
              json.dumps(suffix, ensure_ascii=False)[:250])
        check("★ 存进去的那串**逐条原样**（正文/页码/各自版本表全一致）",
              isinstance(suffix, list) and shape(suffix) == before[2:],
              f"存={brief(suffix) if isinstance(suffix, list) else suffix} 原={brief(s.messages[2:])}")
        check("新版那一格是空的（新版本的后继从空开始）",
              not (slots(a1) or [None, None])[1],
              json.dumps(slots(a1), ensure_ascii=False)[:200])
        check("⑤ 磁盘上当前线确实只有 2 条（done 里 session 重建不会冒出旧内容）",
              len(disk.messages) == 2, brief(disk.messages))

        # 翻回旧版 → 下游原样回来；再翻新版 → 再次让位
        back = dom.switch_variant(s.id, 1, 0)
        after = back["session"]["messages"]
        print("   翻回旧版:", brief(after))
        check("翻回旧版：当前线恢复 4 条", len(after) == 4, brief(after))
        check("★ 翻回旧版：界面视图原样回来（逐条 role/正文/页码一致）",
              line_key(after) == line_key(s.messages),
              f"现在={line_key(after)}\n        原来={line_key(s.messages)}")
        check("★ 翻回旧版：下游那串在磁盘上**原样**回来（数量/正文/各自多版本/报错表全一致）",
              shape(store.load(s.id).messages[2:]) == before_tail
              and shape(store.load(s.id).messages[:1]) == before[:1],
              f"现在={brief(store.load(s.id).messages)}\n        原来={json.dumps(before, ensure_ascii=False)}")
        check("被重生那条自己仍带着新版本（翻回旧版本正文，但版本表不缩水）",
              (store.load(s.id).messages[1].get("variants") or [])
              == ["回答1", "回答1-新版"],
              json.dumps(store.load(s.id).messages[1], ensure_ascii=False)[:250])
        fwd = dom.switch_variant(s.id, 1, 1)
        check("再翻到新版：下游又整段让位（2 条）",
              len(fwd["session"]["messages"]) == 2, brief(fwd["session"]["messages"]))

        # ⑤ 磁盘与内存一致（dom.switch_variant 每次都从磁盘 load，等于"重开程序"）
        reopened = store.load(s.id)
        check("⑤ 磁盘停在新版 = 下面没有旧下游",
              len(reopened.messages) == 2
              and reopened.messages[1]["content"] == "回答1-新版",
              brief(reopened.messages))
        check("⑤ 磁盘上旧版本那一格仍完整（随时能翻回）",
              len((slots(reopened.messages[1]) or [None, None])[0] or []) == 2,
              json.dumps(slots(reopened.messages[1]), ensure_ascii=False)[:300])
        back2 = dom.switch_variant(s.id, 1, 0)
        check("⑤ 从磁盘重新 load 后翻回旧版，下游与界面仍原样一致",
              shape(store.load(s.id).messages[2:]) == before_tail
              and line_key(back2["session"]["messages"]) == line_key(s.messages),
              f"现在={brief(store.load(s.id).messages)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# ② 翻 AI 版本 = 整段换后继（新版本空、旧版本有）
# ---------------------------------------------------------------------------
def test_switch_ai_variant_swaps_suffix():
    section("② AI 气泡翻版本：整段换后继（旧版本有、新版本空）")
    messages = [
        {"role": "user", "content": "1", "ts": "t0"},
        {"role": "assistant", "content": "11", "ts": "t1"},
    ]
    V.normalize_messages(messages)
    V.append_variant(messages[1], "22")                       # 回答有 11 / 22 两版，停在 22
    messages.append({"role": "user", "content": "2", "ts": "t2"})
    V.normalize_messages(messages)
    messages.append({"role": "assistant", "content": "33", "ts": "t3"})
    V.normalize_messages(messages)
    V.sync_branches(messages)                                 # 当前线 = 1 / 22 / 2 / 33

    a1 = messages[1]
    check("同步后：当前版本(22)那一格挂着下游 2/33",
          isinstance(slots(a1), list) and shape(slots(a1)[1]) == shape(messages[2:]),
          json.dumps(slots(a1), ensure_ascii=False)[:300])

    changed = V.set_ai_variant(messages, 1, 0)                # 翻到 11
    check("翻页返回 True（真的换了）", changed is True)
    check("①② 整段换后继：当前线只剩 1 / 11（2、33 让位）",
          len(messages) == 2 and messages[1]["content"] == "11", brief(messages))
    check("①② 旧版本(22)那一格仍挂着 2/33",
          shape(slots(a1)[1]) == [{"role": "user", "content": "2", "vi": 0,
                                   "vars": ["2"], "err": [False]},
                                  {"role": "assistant", "content": "33", "vi": 0,
                                   "vars": ["33"], "err": [False]}],
          json.dumps(slots(a1), ensure_ascii=False)[:300])
    check("★★ 新版本(11)那一格是**空**的（没把当前后继复制过去）",
          not slots(a1)[0], json.dumps(slots(a1), ensure_ascii=False)[:200])
    check("翻到从未存过后继的版本：当前线只剩这一条（空后继）", len(messages) == 2)

    V.set_ai_variant(messages, 1, 1)
    check("再翻回 22：下游 2/33 原样回来",
          len(messages) == 4 and [m["content"] for m in messages[2:]] == ["2", "33"],
          brief(messages))
    check("翻到同一版不做无谓改动（返回 False）", V.set_ai_variant(messages, 1, 1) is False)
    check("越界页码被拒绝、不改数据", V.set_ai_variant(messages, 1, 9) is False
          and len(messages) == 4)
    check("给用户消息走 set_ai_variant 被拒绝", V.set_ai_variant(messages, 0, 0) is False)


# ---------------------------------------------------------------------------
# ③ 老会话向后兼容：不崩、且不把当前后继复制给所有版本
# ---------------------------------------------------------------------------
def test_legacy_session_no_branch_field():
    section("③ 老会话（assistant 没有 branch_suffixes）不崩，翻版本不复制后继")
    tmp = _tmp_dir("legacy-assistant")
    try:
        store = cs.ChatStore(chats_dir=tmp)
        # 老格式：assistant 有 variants 但**完全没有** branch_suffixes 字段
        old = {
            "schema_version": "1.0.0", "id": "legacy-ai-1", "title": "老对话",
            "created_at": "2026-01-01 10:00:00", "updated_at": "2026-01-01 10:00:05",
            "messages": [
                {"role": "user", "content": "1", "ts": "t0"},
                {"role": "assistant", "content": "22", "ts": "t1",
                 "variants": ["11", "22"], "variant_index": 1},
                {"role": "user", "content": "2", "ts": "t2"},
                {"role": "assistant", "content": "33", "ts": "t3"},
            ],
        }
        with open(store.path_of("legacy-ai-1"), "w", encoding="utf-8") as f:
            json.dump(old, f, ensure_ascii=False)

        dom, _store, _seen = make_domain(tmp, ["x"])
        got = dom.session("legacy-ai-1")
        check("老会话能打开（不崩）", got.get("ok") is True, str(got)[:200])
        view = got["session"]["messages"]
        disk = store.load("legacy-ai-1")
        check("文件载入后 assistant 也补出 branch_suffixes（与版本表等长、全 None）",
              slots(disk.messages[1]) == [None, None],
              json.dumps(slots(disk.messages[1])))
        check("全 None = 「这两版都没存过后继」（不是伪造一份后继）",
              all(s is None for s in (slots(disk.messages[1]) or [])))

        sw = dom.switch_variant("legacy-ai-1", 1, 0)          # 翻到从未存过后继的第 1 版
        line = sw["session"]["messages"]
        print("   翻到旧版:", brief(line))
        check("★ 翻版本：当前线只剩 1 / 11（下游 2/33 让位）",
              len(line) == 2 and line[1]["content"] == "11", brief(line))
        disk = store.load("legacy-ai-1")
        after_slots = slots(disk.messages[1])
        # ⚠️ 这条老会话当前显示的是**第 2 版（22）**，所以下游 2/33 属于那一格；
        #    翻到第 1 版（11，从没存过后继）→ 2/33 被存进 slot[1]，slot[0] 是空的。
        check("★ 离开的那一版(22)现在存着让位的 2/33",
              isinstance(after_slots[1], list) and len(after_slots[1]) == 2,
              json.dumps(after_slots, ensure_ascii=False)[:300])
        check("★★ 目标版本(11)那一格没有被复制一份（否则又是「所有版本混在一起」）",
              not after_slots[0], json.dumps(after_slots, ensure_ascii=False)[:300])

        back = dom.switch_variant("legacy-ai-1", 1, 1)
        check("再翻回 22：下游 2/33 原样回来",
              [m["content"] for m in back["session"]["messages"]] == ["1", "22", "2", "33"],
              brief(back["session"]["messages"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# ④ 用户编辑重发：行为不变（回归）
# ---------------------------------------------------------------------------
def test_user_edit_branch_regression():
    section("④ 用户编辑重发：旧回复整串留在旧分支，新版本从空开始（回归）")
    tmp = _tmp_dir("user-edit")
    try:
        dom, store, _seen = make_domain(tmp, ["新回答"])
        s = store.new_session()
        s.messages = [
            {"role": "user", "content": "问题甲", "ts": "t0"},
            {"role": "assistant", "content": "回答1", "ts": "t1"},
        ]
        V.normalize_messages(s.messages)
        V.append_variant(s.messages[1], "回答1-第二版")       # 旧回复自己带多版本
        V.sync_branches(s.messages)
        store.save(s)

        r = dom.send(s.id, "问题甲（编辑过）", "", True, 0, "")
        line = r["session"]["messages"]
        check("编辑后：用户消息 2 个版本、停在新版、正文是编辑后的那句",
              (line[0].get("variants") or []) == ["问题甲", "问题甲（编辑过）"]
              and line[0].get("variant_index") == 1
              and line[0]["content"] == "问题甲（编辑过）",
              json.dumps(line[0], ensure_ascii=False)[:250])
        check("编辑后：新版本下面挂的是**这次的新回答**（旧回复整串让位）",
              len(line) == 2 and line[1]["content"] == "新回答", brief(line))
        check("前端契约：用户消息的 has_branch 形状不变（版本1 有旧回复 / 版本2 有这次的新回答）",
              line[0].get("has_branch") == [True, True],
              json.dumps(line[0].get("has_branch")))

        disk = store.load(s.id)
        old = (slots(disk.messages[0]) or [None, None])[0]
        check("旧分支里那条回复的两个版本都还在（没被压成一条）",
              isinstance(old, list) and len(old) == 1
              and (old[0].get("variants") or []) == ["回答1", "回答1-第二版"],
              json.dumps(old, ensure_ascii=False)[:250])

        back = dom.switch_variant(s.id, 0, 0)
        check("切回用户版本 1：旧回复（停在第二版）原样回来",
              [m["content"] for m in back["session"]["messages"]]
              == ["问题甲", "回答1-第二版"],
              brief(back["session"]["messages"]))
        check("切回用户版本 1：那条回复的版本表仍是 2 版",
              (back["session"]["messages"][1].get("variants") or [])
              == ["回答1", "回答1-第二版"],
              json.dumps(back["session"]["messages"][1], ensure_ascii=False)[:250])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 边界：深拷贝独立性 / 模型吐回同样正文 / has_branch 契约
# ---------------------------------------------------------------------------
def test_deepcopy_and_identical_reply_edges():
    section("边界：模型吐回同样正文时不清空当前后继 + 深拷贝独立性")
    tmp = _tmp_dir("edges")
    try:
        dom, store, _seen = make_domain(tmp, ["回答1", "回答1-新版"])
        s = store.new_session()
        s.messages = [
            {"role": "user", "content": "问题甲", "ts": "t0"},
            {"role": "assistant", "content": "回答1", "ts": "t1"},
            {"role": "user", "content": "追问", "ts": "t2"},
            {"role": "assistant", "content": "回答2", "ts": "t3"},
        ]
        V.normalize_messages(s.messages)
        V.sync_branches(s.messages)
        store.save(s)

        # 第一次重新生成：模型吐回**一模一样**的正文 → 这条线什么都没变，后继必须留着
        same = dom.send(s.id, "问题甲", "", True, "", 1)
        check("模型吐回同样正文：当前线保持 4 条（没有因为'翻页'清掉后继）",
              len(same["session"]["messages"]) == 4, brief(same["session"]["messages"]))
        check("模型吐回同样正文：版本表不新增重复版本",
              len((store.load(s.id).messages[1].get("variants") or [])) == 1,
              json.dumps(store.load(s.id).messages[1], ensure_ascii=False)[:200])

        # 第二次重新生成：新正文 → 下游让位
        res = dom.send(s.id, "问题甲", "", True, "", 1)
        check("新正文：下游让位（当前线 2 条）", len(res["session"]["messages"]) == 2,
              brief(res["session"]["messages"]))
        disk = store.load(s.id)
        check("让位后：旧版本那一格 2 条、新版那一格空",
              len(slots(disk.messages[1])[0] or []) == 2
              and not slots(disk.messages[1])[1],
              json.dumps(slots(disk.messages[1]), ensure_ascii=False)[:300])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 深拷贝：恢复出来的那条线与"被存起来的那份"必须是两批独立对象，
    # 否则在一条分支上翻页/编辑会把另一条分支一起改掉。
    messages = [
        {"role": "user", "content": "q", "ts": "t0"},
        {"role": "assistant", "content": "a1", "ts": "t1"},
        {"role": "user", "content": "u2", "ts": "t2"},
        {"role": "assistant", "content": "a2", "ts": "t3"},
    ]
    V.normalize_messages(messages)
    V.sync_branches(messages)
    V.append_variant(messages[1], "a1b")                  # 两条回答版本
    messages[1]["variant_index"] = 0                      # 故意停回第 1 版
    messages[1]["content"] = "a1"
    V.set_ai_variant(messages, 1, 1)                      # 存下当前支 → 换成第 2 版（空后继）
    V.set_ai_variant(messages, 1, 0)                      # 存下第 2 版 → 放回第 1 版的下游
    stored = messages[1]["branch_suffixes"][0]
    check("深拷贝：恢复出来的下游与那一格里存的不是同一批 dict",
          isinstance(stored, list) and len(messages) == 4
          and messages[2] is not stored[0],
          f"len={len(messages)} stored={json.dumps(stored, ensure_ascii=False)[:120]}")
    messages[2]["content"] = "被就地改过"
    check("在当前线上就地改一条，不会污染那一格里存下来的内容",
          stored[0]["content"] == "u2", json.dumps(stored, ensure_ascii=False)[:150])
    messages[3]["content"] = "被就地改过2"
    check("下游整串都各存一份（不只第一条）", stored[1]["content"] == "a2",
          json.dumps(stored, ensure_ascii=False)[:150])


def test_message_view_contract():
    section("边界：_message_view 的字段形状（user 原样、assistant 新增 has_branch）")
    user_view = AiDomain._message_view({
        "role": "user", "content": "2", "ts": "t",
        "variants": ["1", "2"], "variant_index": 1,
        "branch_suffixes": [[{"role": "assistant", "content": "x"}], None]})
    ai_view = AiDomain._message_view({
        "role": "assistant", "content": "22", "ts": "t", "error": False,
        "variants": ["11", "22"], "variant_index": 1,
        "variant_error": [True, False],
        "branch_suffixes": [[{"role": "user", "content": "q"}], []]})
    check("user 的字段形状没变（role/content/ts/error/kind/variants/variant_index/has_branch）",
          set(user_view.keys()) == {"role", "content", "ts", "error", "kind",
                                    "variants", "variant_index", "has_branch"},
          sorted(user_view.keys()))
    check("user.has_branch 仍是「这一版有没有挂下游」的布尔表",
          user_view["has_branch"] == [True, False], str(user_view.get("has_branch")))
    check("assistant 也带 has_branch 布尔表", ai_view.get("has_branch") == [True, False],
          str(ai_view.get("has_branch")))
    check("view 不带 branch_suffixes 正文（payload 不膨胀）",
          "branch_suffixes" not in ai_view and "branch_suffixes" not in user_view)
    check("view 带 variant_error（翻回当初失败那一版要画红色气泡）",
          ai_view.get("variant_error") == [True, False], str(ai_view.get("variant_error")))


def main():
    test_middle_answer_regen_detaches_downstream()
    test_switch_ai_variant_swaps_suffix()
    test_legacy_session_no_branch_field()
    test_user_edit_branch_regression()
    test_deepcopy_and_identical_reply_edges()
    test_message_view_contract()
    print("\n" + "=" * 72)
    if FAIL:
        print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
        for name in FAIL:
            print("   -", name)
        return 1
    print(f"通过 {len(PASS)} 项，失败 0 项")
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
