"""AI 版本树**行为**回归：复现用户报的两件事（跑真实 AiDomain + 真实 ChatStore 落盘）。

用户原话拆解：
A)「点击回答1重新生成会在回答3的空白位置上出现一个正在xxx聊天气泡然后突然消失，
    这个回答1的内容重新生成」→ 重新生成时"正在生成"的气泡要出现在**被重生那条的正下方**
    （原位），而不是列表末尾；结束后原位收敛成那条的新版本。（前端渲染另测，见本文件末尾）
B)「我点击中间的AI的重新生成，但是下面的内容是上一版AI的对话，bug 性的下面所有内容
    属于所有版了，**全都不消失，存在着**；用户的编辑也一样。」
   → 重新生成 messages[1]（回答1）时，它**下面**的回答2 属于**旧版本的分支**：
   必须从当前显示的那条线上消失（存进 assistant.branch_suffixes[旧版本]，深拷贝、
   内容与它自己的多版本都要原样保留），翻回答1的版本时整段换后继 ——
   翻回旧版原样回来、翻到新版是空的。**不能让几个版本的后继同时显示**。
   （本文件 2026-11-06 按用户这轮澄清改写：上一轮"回答2 原位不动、一直显示"的断言
     正是用户点名的 bug，已按新语义换成"消失 + 可翻回"的等价断言。）

跑法： python "项目资料-文档与开发测试/_devtest/test_ai_regen_behavior.py"
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

from pymodels.core.ai import chat_store as cs            # noqa: E402
from pymodels.core.ai import versions as V               # noqa: E402
from desktop.api.ai import AiDomain                      # noqa: E402

FAIL = []


def _tmp_dir(prefix: str) -> str:
    """测试用的临时会话目录（和 test_ai_versions.py 同一套约定）。

    ⚠️ 不用系统 %TEMP%：沙箱环境里它**不可写**（Errno 13），"落盘 / 重开"的用例
       会全变成假失败（现象：res["session"]["messages"] 只剩 1 条 → IndexError）。
       写进 `项目资料-文档与开发测试/_tmp-ai-test/`（被 .gitignore 的 `_tmp*/` 覆盖、
       随时可删），既跑得动也**绝不污染 .ToolsGCP/chats —— 那是用户数据，一律不碰**。
    """
    base = os.path.join(ROOT, "项目资料-文档与开发测试", "_tmp-ai-test", prefix)
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base, exist_ok=True)
    return base


def check(label, cond, extra=""):
    if cond:
        print(f"  OK   {label}")
    else:
        print(f"  FAIL {label}  {extra}")
        FAIL.append(label)


class _Result:
    """冒充 client.chat 的返回值（ok/kind/message/content）"""

    ok = True
    kind = ""
    message = ""

    def __init__(self, content):
        self.content = content


def make_domain(chats_dir, replies):
    """造一个"只换掉网络那一层"的 AiDomain：
    落盘 / 版本树 / 下标这些**真逻辑一律走原样**，否则测的就不是用户的 bug 了。"""
    store = cs.ChatStore(chats_dir=chats_dir)

    class _TestDomain(AiDomain):
        """store 是 property，只能靠子类覆盖，不能往实例上赋值（会 AttributeError）"""

        @property
        def store(self):
            return store

    dom = _TestDomain(shell=types_Shell())
    state = {"i": 0}

    dom._credentials = lambda: {"api_key": "k", "model": "m", "api_model": "m",
                                "api_base": "", "missing": [], "key_tail": ""}
    dom._context_messages = lambda session, content, reply_mode, upto: (
        [dict(m) for m in session.messages[:max(0, upto if upto is not None
                                                else len(session.messages))]],
        False, "zh_CN")
    dom._resources = lambda: []
    dom._clean_reply = lambda text: text

    def fake_chat(_ctx, *_a, **_kw):
        text = replies[min(state["i"], len(replies) - 1)]
        state["i"] += 1
        return _Result(text), 0, []

    dom._chat_with_tools = fake_chat
    return dom, store


def types_Shell():
    class _Shell:
        settings_manager = None
    return _Shell()


def brief(msgs):
    return json.dumps([{"role": m["role"], "c": m["content"],
                        "v": m.get("variant_index"),
                        "vars": m.get("variants"),
                        "br": (None if not isinstance(m.get("branch_suffixes"), list)
                               else [None if s is None else len(s)
                                     for s in m["branch_suffixes"]])}
                       for m in msgs], ensure_ascii=False)


def scenario_a_regen_detaches_old_suffix():
    print("== 场景①：对「回答1」重新生成，下面的「回答2」必须整段让位（存进旧版本分支）==")
    dom, store = make_domain(_tmp_dir("regen"),
                             ["回答1-新版"])
    session = store.new_session()
    session.messages = [
        {"role": "user", "content": "问题甲", "ts": "t0"},
        {"role": "assistant", "content": "回答1", "ts": "t1"},
        {"role": "assistant", "content": "回答2", "ts": "t2"},
    ]
    V.normalize_messages(session.messages)
    # 回答2 自身也带多版本：让位/翻回来时"每条自己的多版本"也必须原样
    V.append_variant(session.messages[2], "回答2-第二版")
    V.sync_branches(session.messages)
    store.save(session)

    res = dom.send(session.id, "问题甲", "", True, "", 1)      # assistant_index = 1
    msgs = res["session"]["messages"]
    print("   重新生成后:", brief(msgs))

    check("重新生成只给「回答1」追加版本（没多出一条 assistant）", len(msgs) == 2,
          f"实际 {len(msgs)} 条")
    check("「回答1」现在有两个版本", len(msgs[1].get("variants") or []) == 2,
          json.dumps(msgs[1].get("variants"), ensure_ascii=False))
    check("页码停在最后一版（新版本）", msgs[1].get("variant_index") == 1)
    check("正文镜像到新版", msgs[1]["content"] == "回答1-新版", msgs[1]["content"])
    check("★「回答2」不再挂在当前线上（旧下游整段让位，不是所有版本混着显示）",
          not any(m["content"].startswith("回答2") for m in msgs[1:]),
          brief(msgs))
    check("★ 前端契约：assistant 也带 has_branch（旧版挂着下游 / 新版是空的）",
          msgs[1].get("has_branch") == [True, False],
          json.dumps(msgs[1].get("has_branch")))

    # 数据绝不能丢：回答2 完整存在**旧版本那一格**里（读磁盘，view 不回正文）
    disk = store.load(session.id)
    a1 = disk.messages[1]
    suffix = (a1.get("branch_suffixes") or [None, None])[0]
    check("★ 回答2 被存进 assistant.branch_suffixes[旧版本 0]（没有丢数据）",
          isinstance(suffix, list) and len(suffix) == 1
          and suffix[0]["content"] == "回答2-第二版",
          json.dumps(suffix, ensure_ascii=False)[:200])
    check("★ 让位的那条回答**自己的多版本也原样保留**",
          isinstance(suffix, list) and len(suffix) == 1
          and (suffix[0].get("variants") or []) == ["回答2", "回答2-第二版"],
          json.dumps(suffix, ensure_ascii=False)[:200])
    check("新版那一格是空的（branch_suffixes[1] 没有内容）",
          not (a1.get("branch_suffixes") or [None, None])[1], 
          json.dumps(a1.get("branch_suffixes"), ensure_ascii=False)[:200])
    check("落盘的当前线上确实只有 2 条（前端用 done 里的 session 重建不会冒出旧内容）",
          len(disk.messages) == 2, brief(disk.messages))

    sw = dom.switch_variant(session.id, 1, 0)                   # 翻回回答1的旧版
    m2 = sw["session"]["messages"]
    print("   翻回旧版:", brief(m2))
    check("翻回旧版：回答1 正文回到『回答1』", m2[1]["content"] == "回答1",
          m2[1]["content"])
    check("★ 翻回旧版：回答2 原样回来（条数一致）", len(m2) == 3, brief(m2))
    check("★ 翻回旧版：回答2 内容一致", m2[2]["content"] == "回答2-第二版",
          m2[2]["content"] if len(m2) > 2 else "没有第三条")
    check("★ 翻回旧版：回答2 自己的两个版本都在（多版本没被压掉）",
          (m2[2].get("variants") or []) == ["回答2", "回答2-第二版"],
          json.dumps(m2[2].get("variants"), ensure_ascii=False))

    fwd = dom.switch_variant(session.id, 1, 1)                  # 再翻到新版
    m3 = fwd["session"]["messages"]
    check("再翻到新版：回答2 又整段让位（当前线只剩 2 条）", len(m3) == 2, brief(m3))

    # 磁盘上也要一致（重开程序看到的一样：停在新版 = 下面没有旧内容）
    reloaded = store.load(session.id)
    check("落盘一致：磁盘上停在新版、下面没有旧下游",
          len(reloaded.messages) == 2 and reloaded.messages[1]["content"] == "回答1-新版",
          brief(reloaded.messages))
    check("落盘一致：旧版本那一格里的回答2 仍在磁盘上（可再翻回）",
          len((reloaded.messages[1].get("branch_suffixes") or [None, None])[0] or []) == 1,
          json.dumps(reloaded.messages[1].get("branch_suffixes"), ensure_ascii=False)[:300])


def scenario_b_edit_branch_keeps_old_versions():
    print("== 场景②：编辑重发后，旧那串回复（含它的多版本）必须整串留在旧分支 ==")
    dom, store = make_domain(_tmp_dir("edit"),
                             ["新回答"])
    s = store.new_session()
    s.messages = [
        {"role": "user", "content": "问题甲", "ts": "t0"},
        {"role": "assistant", "content": "回答1", "ts": "t1"},
    ]
    V.normalize_messages(s.messages)
    V.append_variant(s.messages[1], "回答1-第二版")     # 回答1 已有两版
    V.sync_branches(s.messages)
    store.save(s)

    r = dom.send(s.id, "问题甲（编辑过）", "", True, 0, "")   # user_index = 0
    msgs = r["session"]["messages"]
    print("   编辑后:", brief(msgs))
    # ⚠️ branch_suffixes 的**正文**不会出现在给前端的 view 里（_message_view 只回
    #    has_branch 布尔表，省 payload），所以这里必须读**磁盘上的会话**来验归属。
    disk = store.load(s.id)
    u = disk.messages[0]
    check("用户消息有 2 个版本", len(u.get("variants") or []) == 2,
          json.dumps(u.get("variants"), ensure_ascii=False))
    check("前端 view 告诉界面「版本1 挂着回复」（has_branch）",
          bool((msgs[0].get("has_branch") or [False])[0]),
          json.dumps(msgs[0].get("has_branch")))
    old = (u.get("branch_suffixes") or [None, None])[0]
    check("旧分支里存着那串回复", isinstance(old, list) and len(old) == 1,
          json.dumps(old, ensure_ascii=False)[:200])
    check("★ 旧分支里那条回复的**两个版本都还在**（没被压成一条）",
          isinstance(old, list) and len(old) == 1
          and len(old[0].get("variants") or []) == 2,
          json.dumps(old, ensure_ascii=False)[:200])

    back = dom.switch_variant(s.id, 0, 0)
    bm = back["session"]["messages"]
    print("   切回用户版本1:", brief(bm))
    check("切回版本1 → 旧那串回复回来了（正文=回答1-第二版）",
          len(bm) == 2 and bm[1]["content"] == "回答1-第二版", brief(bm))
    check("切回版本1 → 那条回复仍是 2 个版本",
          len(bm) == 2 and len(bm[1].get("variants") or []) == 2, brief(bm))


def scenario_c_stream_regen_same_semantics():
    """流式那条路必须和同步那条**完全同一套版本语义**（用户默认开着逐字输出）。
    只验证 _prepare_send 算出来的 plan 一致，不真的起线程。"""
    print("== 场景③：流式与同步的版本语义一致（同一个 _prepare_send） ==")
    dom, store = make_domain(_tmp_dir("stream"), ["x"])
    s = store.new_session()
    s.messages = [
        {"role": "user", "content": "问题甲", "ts": "t0"},
        {"role": "assistant", "content": "回答1", "ts": "t1"},
        {"role": "assistant", "content": "回答2", "ts": "t2"},
    ]
    V.normalize_messages(s.messages)
    store.save(s)
    plan = dom._prepare_send(store, s, "问题甲", True, "", 1)
    check("regen 语义：mode=regen", plan.get("mode") == "regen", json.dumps(plan))
    check("regen 语义：assistant_index=1（就地翻版，不是新增）",
          plan.get("assistant_index") == 1, str(plan.get("assistant_index")))
    check("★ regen 语义：上下文截到回答1**之前**（upto=1，回答2 不进上下文）",
          plan.get("upto") == 1, f"upto={plan.get('upto')}")


def main():
    scenario_a_regen_detaches_old_suffix()
    scenario_b_edit_branch_keeps_old_versions()
    scenario_c_stream_regen_same_semantics()
    print("\n=== 结论：%s ===" % ("全部通过" if not FAIL else f"{len(FAIL)} 项失败"))
    for f in FAIL:
        print("   -", f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
