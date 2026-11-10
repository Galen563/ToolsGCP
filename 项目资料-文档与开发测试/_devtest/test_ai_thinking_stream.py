# -*- coding: utf-8 -*-
"""GCP-AI 本轮改造的回归测试（Lead 亲自跑的验收口径）。

覆盖三件事：
  ① 思考与正文**彻底分家**（client.chat / chat_stream / _parse_success / _sse_delta）：
     - 正文为空、只有 reasoning_content → 不再把思考当回答吐出去；
     - thinking=False → 请求体带 thinking.disabled，reasoning 一律不回传；
     - thinking=None → 请求体**不带** thinking 参数（老网关兼容）；
     - thinking=True  → 请求体带 thinking.enabled，reasoning 单独带回。
  ② 逐字输出根因：chat_stream 必须用 read1/readline 这类**增量读**，
     绝不能在 read(1024) 上阻塞到服务端发完才返回（那就是"一次性整段出现"）。
  ③ 版本树 variant_reasoning 表：按版本存思考、翻页镜像、老文件不凭空补键。

跑法：python "项目资料-文档与开发测试/_devtest/test_ai_thinking_stream.py"
⚠️ 全程不联网、不碰用户配置。
"""
import io
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.argv = [os.path.join(ROOT, "ToolsGCP.pyw")]
sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]

from pymodels.core.ai import client as ai_client        # noqa: E402
from pymodels.core.ai import providers as ai_providers  # noqa: E402
from pymodels.core.ai import versions as ai_versions    # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f"  <- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


class _FakeResponse:
    """假 HTTP 响应：read() 照旧"攒够才返回"，read1() 一次一块（模拟真实 socket 节奏）"""

    def __init__(self, chunks, content_type="text/event-stream", no_read1=False):
        self._chunks = list(chunks)
        self._buf = b""
        self.headers = {"Content-Type": content_type}
        self.status = 200
        if no_read1:
            # 老内核形态：没有 read1 / readline，只能退回 read()
            self.read1 = None                            # noqa: 显式遮蔽方法
            self.readline = None                         # noqa

    def read(self, size=-1):
        if size is None or size < 0:
            data = self._buf + b"".join(self._chunks)
            self._buf, self._chunks = b"", []
            return data
        while len(self._buf) < size and self._chunks:
            self._buf += self._chunks.pop(0)
        out, self._buf = self._buf[:size], self._buf[size:]
        return out

    def read1(self, size=-1):
        """一次底层读：有多少给多少（真实 SSE 每帧就是一个小块）"""
        if self._buf:
            out, self._buf = self._buf, b""
            return out
        if self._chunks:
            return self._chunks.pop(0)
        return b""

    def readline(self, size=-1):
        return self.read1(size)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _run(response, body):
    original = urllib.request.urlopen
    urllib.request.urlopen = lambda request, *a, **kw: response
    try:
        return body()
    finally:
        urllib.request.urlopen = original


def _delta_frame(content=None, reasoning=None, finish=None):
    delta = {}
    if content is not None:
        delta["content"] = content
    if reasoning is not None:
        delta["reasoning_content"] = reasoning
    frame = {"choices": [{"delta": delta, "finish_reason": finish}]}
    return ("data: " + json.dumps(frame, ensure_ascii=False) + "\n\n").encode("utf-8")


# ======================================================================
print("[1] 思考与正文分家（流式）")

# 1.1 只有 reasoning、没有正文：绝不能把思考当回答
frames = [_delta_frame(reasoning="用户问了几点。我应该…"),
          _delta_frame(reasoning="先查库再回答。"),
          _delta_frame(finish="stop")]
body_seen = []
res = _run(_FakeResponse(frames),
           lambda: ai_client.chat_stream([{"role": "user", "content": "hi"}],
                                         "sk", "m", "https://api.test",
                                         on_chunk=lambda t: body_seen.append(t),
                                         on_reasoning=lambda t: None,
                                         thinking=True))
check("只有思考、没有正文 → 不再把思考顶成回答（失败而不是假成功）",
      (not res.ok) and "思考" in (res.message or ""),
      f"ok={res.ok} kind={res.kind} msg={res.message}")
check("正文回调一个字都没收到（思考没有混进 on_chunk）", body_seen == [],
      json.dumps(body_seen, ensure_ascii=False))

# 1.2 思考 + 正文混流：正文只有正文，思考单独走 on_reasoning
think_got, body_got = [], []
frames = [_delta_frame(reasoning="想一下…"),
          _delta_frame(content="答案是"),
          _delta_frame(reasoning="确认无误。"),
          _delta_frame(content=" TG-000001。"),
          _delta_frame(finish="stop")]
res = _run(_FakeResponse(frames),
           lambda: ai_client.chat_stream([{"role": "user", "content": "hi"}],
                                         "sk", "m", "https://api.test",
                                         on_chunk=lambda t: body_got.append(t),
                                         on_reasoning=lambda t: think_got.append(t),
                                         thinking=True))
check("正文 = 只有正文（思考一个字符都没混进来）",
      res.ok and res.content == "答案是 TG-000001。",
      f"content={res.content!r}")
check("reasoning 单独带回", res.reasoning == "想一下…确认无误。",
      f"reasoning={res.reasoning!r}")
check("on_reasoning 只收到思考累计、on_chunk 只收到正文累计",
      think_got and all("想" in t or "确认" in t for t in think_got)
      and all("答案" in t or "TG" in t for t in body_got),
      json.dumps([think_got, body_got], ensure_ascii=False))

# 1.3 thinking=False：思考流**不推**、结果里也不带 reasoning
think_got2, body_got2 = [], []
frames = [_delta_frame(reasoning="自言自语"), _delta_frame(content="正文"),
          _delta_frame(finish="stop")]
res = _run(_FakeResponse(frames),
           lambda: ai_client.chat_stream([{"role": "user", "content": "hi"}],
                                         "sk", "m", "https://api.test",
                                         on_chunk=lambda t: body_got2.append(t),
                                         on_reasoning=lambda t: think_got2.append(t),
                                         thinking=False))
check("thinking=False → 界面上一个字思考都看不到",
      res.ok and res.content == "正文" and think_got2 == [] and res.reasoning == "",
      f"content={res.content!r} reasoning={res.reasoning!r} think={think_got2}")

# ======================================================================
print("[2] 逐字输出：增量读（read1）而不是攒满 1024 字节")

# 2.1 用"read 攒够才给、read1 一次一块"的响应：read1 路径必须多次回调
long_text = "逐" * 400                      # 1200 字节 > 1024，read(1024) 会攒两下
frames = [_delta_frame(content=long_text[i:i + 20]) for i in range(0, len(long_text), 20)]
frames.append(b"data: [DONE]\n\n")
ticks = []
res = _run(_FakeResponse(frames),
           lambda: ai_client.chat_stream([{"role": "user", "content": "hi"}],
                                         "sk", "m", "https://api.test",
                                         on_chunk=lambda t: ticks.append(len(t))))
check("read1 路径：正文分多帧到达时回调次数 > 1（真的在往外蹦字）",
      res.ok and len(ticks) >= 2, f"ticks={ticks[:8]}…共{len(ticks)}")

# 2.2 老内核（没有 read1/readline）退回 read()：功能不坏（一次到位也要能拼完整）
res = _run(_FakeResponse(frames, no_read1=True),
           lambda: ai_client.chat_stream([{"role": "user", "content": "hi"}],
                                         "sk", "m", "https://api.test",
                                         on_chunk=lambda t: ticks.append(len(t))))
check("没有 read1 的老响应对象也能拿到完整正文（退回 read 不丢字）",
      res.ok and res.content == long_text, f"len={len(res.content or '')}")

# 2.3 readline 路径（没有可用的 read1，但有 readline）
class _LineOnly(_FakeResponse):
    """read1 抛异常（模拟"属性存在但不可用"的内核），readline 正常按帧给"""

    def read1(self, size=-1):
        raise AttributeError("no read1")

    def readline(self, size=-1):
        if self._chunks:
            return self._chunks.pop(0)
        return b""

res = _run(_LineOnly(frames),
           lambda: ai_client.chat_stream([{"role": "user", "content": "hi"}],
                                         "sk", "m", "https://api.test",
                                         on_chunk=lambda t: ticks.append(len(t))))
check("read1 不可用时退回 readline 仍流式", res.ok and res.content == long_text,
      f"ok={res.ok} kind={res.kind} msg={res.message}")

# ======================================================================
print("[3] 请求体里的 thinking 参数（三态）")

captured = {}


def _capture_urlopen(request, *a, **kw):
    captured["body"] = json.loads(request.data.decode("utf-8"))
    return _FakeResponse([b"data: [DONE]\n\n"])


def _run_capture(thinking):
    original = urllib.request.urlopen
    urllib.request.urlopen = _capture_urlopen
    try:
        ai_client.chat_stream([{"role": "user", "content": "hi"}], "sk", "m",
                              "https://api.test", thinking=thinking)
    finally:
        urllib.request.urlopen = original
    return captured.get("body", {})


body = _run_capture(None)
check("thinking=None → 请求体**不带** thinking 参数（老网关兼容）",
      "thinking" not in body, json.dumps(body, ensure_ascii=False))
body = _run_capture(False)
check("thinking=False → thinking.disabled（推理模型服务端默认开着，必须显式关）",
      body.get("thinking") == {"type": "disabled"}, json.dumps(body, ensure_ascii=False))
body = _run_capture(True)
check("thinking=True → thinking.enabled",
      body.get("thinking") == {"type": "enabled"}, json.dumps(body, ensure_ascii=False))

# 非流式同样三态
def _capture_json(request, *a, **kw):
    captured["body"] = json.loads(request.data.decode("utf-8"))
    payload = json.dumps({"choices": [{"message": {"content": "好", "reasoning_content": "想"}}]})
    return _FakeResponse([payload.encode("utf-8")], content_type="application/json")


original = urllib.request.urlopen
urllib.request.urlopen = _capture_json
try:
    r_off = ai_client.chat([{"role": "user", "content": "x"}], "sk", "m",
                           "https://api.test", thinking=False)
    r_on = ai_client.chat([{"role": "user", "content": "x"}], "sk", "m",
                          "https://api.test", thinking=True)
finally:
    urllib.request.urlopen = original
check("非流式 thinking=False：正文正常、reasoning 不回传",
      r_off.ok and r_off.content == "好" and r_off.reasoning == "",
      f"content={r_off.content!r} reasoning={r_off.reasoning!r}")
check("非流式 thinking=True：reasoning 单独带回（不并进正文）",
      r_on.ok and r_on.content == "好" and r_on.reasoning == "想",
      f"reasoning={r_on.reasoning!r}")

# 网关不认 stream、整段 JSON 一次回来（老 bug 的另一条触发路径）
payload = json.dumps({"choices": [{"message": {"content": "整段", "reasoning_content": "呓语"}}]})
res = _run(_FakeResponse([payload.encode("utf-8")], content_type="application/json"),
           lambda: ai_client.chat_stream([{"role": "user", "content": "hi"}], "sk", "m",
                                         "https://api.test", thinking=False))
check("非 SSE 网关 + 思考关：正文干净、不带思考",
      res.ok and res.content == "整段" and res.reasoning == "",
      f"content={res.content!r} reasoning={res.reasoning!r}")

# ======================================================================
print("[4] 模型能力表 / 默认值")
check("deepseek-v4.1-flash 支持思考",
      ai_providers.model_supports_thinking("deepseek", "deepseek-v4.1-flash"))
check("deepseek-chat（老名字）不支持 → 不发 thinking 参数",
      not ai_providers.model_supports_thinking("deepseek", "deepseek-chat"))
check("带路由前缀的中转名也能认（deepseek/deepseek-v4-pro）",
      ai_providers.model_supports_thinking("custom", "deepseek/deepseek-v4-pro"))
check("任何模型默认思考档位都是 off（需求：默认思考都为关闭）",
      ai_providers.thinking_default("deepseek", "deepseek-v4.1-flash") == "off")
catalog = ai_providers.model_catalog("deepseek")
check("model_catalog 给出显示名 + API 名 + 思考能力 + 档位表",
      catalog and catalog[0]["name"] == "deepseek-v4.1-flash"
      and catalog[0]["api_model"] == "deepseek-flash"
      and catalog[0]["thinking"] is True
      # ⚠️ 断言更新（需求 4「档位跟随各家官方 API」）：全局统一表 [off,low,medium,high]
      #    已经废掉了 —— deepseek 官方 reasoning_effort 只有 none/low/high/max
      #    （medium 官方只是兼容别名，会被映射到 high，所以程序**不再发** medium）。
      #    这里改成校验「档位表由官方表驱动」：恒以 off 开头、含官方专有的 max、
      #    且不出现官方不存在的 medium；具体档名以 providers.thinking_levels 为准。
      and [x["value"] for x in catalog[0]["thinking_levels"]][0] == "off"
      and "max" in [x["value"] for x in catalog[0]["thinking_levels"]]
      and "medium" not in [x["value"] for x in catalog[0]["thinking_levels"]],
      json.dumps(catalog, ensure_ascii=False))

print("[4.5] 思考多档强度（本轮需求：像 Codex 一样有档位，而不是只有开关）")
# 档位 → 请求体
def _body(thinking):
    _url, raw = ai_client._build_request([{"role": "user", "content": "x"}],
                                        "m", "https://api.test", 0, 0.7, True,
                                        thinking=thinking)
    return json.loads(raw.decode("utf-8"))
check("off → 只发 thinking.disabled（推理模型服务端默认开着，必须显式关）",
      _body("off").get("thinking") == {"type": "disabled"}
      and "reasoning_effort" not in _body("off"), json.dumps(_body("off")))
for lvl in ("low", "medium", "high"):
    b = _body(lvl)
    check(f"{lvl} → reasoning_effort={lvl} + thinking.enabled",
          b.get("reasoning_effort") == lvl and b.get("thinking") == {"type": "enabled"},
          json.dumps(b))
check("None（模型不支持）→ 两个参数都不发（老网关会 400）",
      "reasoning_effort" not in _body(None) and "thinking" not in _body(None),
      json.dumps(_body(None)))
# _thinking_on：档位是否"开着"
check("_thinking_on: off/None → False；low/medium/high → True",
      not ai_client._thinking_on("off") and not ai_client._thinking_on(None)
      and ai_client._thinking_on("low") and ai_client._thinking_on("high"))
# 旧配置兼容（关键：用户配置里现在存的是布尔 False）
check("normalize_thinking 兼容旧布尔：False→off、True→medium",
      ai_providers.normalize_thinking(False) == "off"
      and ai_providers.normalize_thinking(True) == "medium")
check("normalize_thinking 兼容字符串写法（关/开/低/中/高/坏值）",
      ai_providers.normalize_thinking("关闭") == "off"
      and ai_providers.normalize_thinking("开启") == "medium"
      and ai_providers.normalize_thinking("低") == "low"
      and ai_providers.normalize_thinking("HIGH") == "high"
      and ai_providers.normalize_thinking("乱值") == "off")
check("不支持思考的模型只给 off 一档（前端据此不画滑块）",
      [x["value"] for x in ai_providers.thinking_levels("deepseek", "deepseek-chat")] == ["off"])
# 旧布尔档位仍然能用（向后兼容：True/False 直接传给 _build_request）
check("旧调用方传 True → medium 档、传 False → off（不炸）",
      _body(True).get("reasoning_effort") == "medium"
      and _body(False).get("thinking") == {"type": "disabled"})

# ======================================================================
print("[5] 版本树 variant_reasoning：按版本存 / 翻页镜像 / 老文件不补键")

# 5.1 老会话（没有思考表）normalize 不凭空补键
old = {"role": "assistant", "content": "老回答", "ts": "x"}
ai_versions.normalize_messages([old])
check("老会话消息 normalize 后**没有** variant_reasoning 键",
      "variant_reasoning" not in old, json.dumps(sorted(old.keys())))

# 5.2 带思考落盘
m = {"role": "assistant", "content": "回答1", "ts": "x"}
ai_versions.append_variant(m, "回答1", reasoning="思考1")
check("append_variant 把思考存进表并镜像",
      m["variants"] == ["回答1"] and m["variant_reasoning"] == ["思考1"]
      and m["reasoning"] == "思考1",
      json.dumps(m, ensure_ascii=False))
msgs = [m]
ai_versions.regenerate_variant(msgs, 0, "回答2", reasoning="思考2")
check("重新生成：两版正文两版思考各归各格",
      m["variants"] == ["回答1", "回答2"] and m["variant_reasoning"] == ["思考1", "思考2"]
      and m["reasoning"] == "思考2", json.dumps(m, ensure_ascii=False))
ok = ai_versions.set_ai_variant(msgs, 0, 0)      # 翻回第 1 版
check("翻页：正文与思考一起镜像回第 1 版",
      ok and m["content"] == "回答1" and m["reasoning"] == "思考1",
      json.dumps(m, ensure_ascii=False))
ok = ai_versions.set_ai_variant(msgs, 0, 1)      # 再翻回第 2 版
check("再翻回来：思考也跟着回来", ok and m["reasoning"] == "思考2")

# 5.3 这次没思考 → 新版本格子是空串（前端据此不画折叠块）
ai_versions.regenerate_variant(msgs, 0, "回答3")
check("不带思考的新版本：该格是空串（不是 None、不是上一版的思考）",
      m["variant_reasoning"][-1] == "" and m["reasoning"] == "",
      json.dumps(m["variant_reasoning"], ensure_ascii=False))

# 5.4 去重路径不能把旧思考抹掉
m2 = {"role": "assistant", "content": "甲", "ts": "x",
      "variants": ["甲"], "variant_index": 0, "branch_suffixes": [None],
      "variant_reasoning": ["甲的思考"]}
ai_versions.regenerate_variant([m2], 0, "甲")     # 正文与已有版本相同
check("正文重复去重时不抹掉已存的思考",
      m2["variant_reasoning"] == ["甲的思考"],
      json.dumps(m2["variant_reasoning"], ensure_ascii=False))

print()
if FAILS:
    print(f"FAILED {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("ALL OK")
