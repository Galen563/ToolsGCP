"""GCP-AI 的模型调用客户端（OpenAI 兼容格式，只用标准库 urllib + json）。
    POST {api_base}/chat/completions，Authorization: Bearer {api_key}
    result = chat(messages, api_key, model, api_base, timeout=60)
    result.ok / result.kind / result.message   # kind 用来给界面挑文案和颜色
"""

import codecs
import json
import socket
import time
import urllib.error
import urllib.request

# 默认接口地址（DeepSeek 的 OpenAI 兼容端点）
DEFAULT_API_BASE = "https://api.deepseek.com/v1"

# 超时：非流式要等整段回答生成完，给宽一点
DEFAULT_TIMEOUT = 90

# 结果类型（界面按 kind 显示不同文案，避免把网络错误显示成"密钥错误"）
KIND_OK = "ok"
KIND_NO_KEY = "no_key"          # 没配 key
KIND_NO_MODEL = "no_model"      # 没配模型名
KIND_AUTH = "auth"              # 401 / 403：key 不对或没权限
KIND_RATE = "rate"              # 429：额度/频率限制
KIND_TIMEOUT = "timeout"        # 超时
KIND_NETWORK = "network"        # DNS / 连不上 / TLS
KIND_BAD_REQUEST = "bad_request"  # 400：参数或模型名不被接受
KIND_SERVER = "server"          # 5xx：服务端问题
KIND_BAD_JSON = "bad_json"      # 返回的不是预期的 JSON 结构
KIND_CONFIG = "config"          # 地址非法等配置问题
# finish_reason=length（回答被 token 上限截断）单独一个 kind：
# ⚠️ 为什么不用 bad_request —— 「测试连接」以前 max_tokens=1，推理模型思考也要吃 token，
#    于是**永远**收到这条"回答被长度上限截断了，请调大最大token量"，
#    用户填没填 Key、地址对不对都看到同一句话，等于测试功能形同虚设（用户原话）。
#    截断恰恰说明 HTTP 通路是好的（网关已经正常生成回答），所以 kind 要能被上层
#    单独判成"连通正常"，而聊天路径仍然把它当错误提示用户调大上限。
KIND_LENGTH = "length"
KIND_UNKNOWN = "unknown"


class ChatResult:
    """一次调用的结果（不抛异常，调用方只看 ok / kind / message）

    ⚠️ `reasoning`（推理模型返回的**思考过程**）与 `content`（给用户的**正文**）是两条
       完全分开的数据：以前 content 为空时会拿 reasoning 顶上去，结果用户没开思考按钮
       也在气泡里看到「用户问调用的什么模型。我应该诚实说…」这类自言自语
       （用户报的 bug，历史会话文件里能翻到实例）。现在**绝不混**：
       reasoning 只作为独立字段带出去，落盘/显示都由上层按“思考开关”决定。
    """

    def __init__(self, ok: bool, content: str = "", kind: str = KIND_OK,
                 message: str = "", status: int = 0, raw: str = "",
                 reasoning: str = ""):
        self.ok = ok
        self.content = content
        self.kind = kind
        self.message = message      # 给用户看的中文说明
        self.status = status        # HTTP 状态码（0 = 没走到 HTTP 层）
        self.raw = raw              # 原始响应片段（排查用，只取前若干字符）
        self.reasoning = reasoning  # 思考过程（与正文分开，绝不并进 content）

    def __repr__(self):
        return f"<ChatResult ok={self.ok} kind={self.kind} status={self.status}>"


def normalize_api_base(api_base: str) -> str:
    """把用户填的接口地址规整成可以直接拼 /chat/completions 的形式
    ⚠️ 必须允许用户直接粘完整 endpoint：否则会再拼一次路径变成 404，报错还看不出原因。
    """
    base = str(api_base or "").strip()
    if not base:
        return DEFAULT_API_BASE
    if "://" not in base:
        base = "https://" + base
    base = base.rstrip("/")
    for suffix in ("/chat/completions", "/completions"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return base.rstrip("/") or DEFAULT_API_BASE


def is_valid_api_base(api_base: str) -> bool:
    """设置页保存前用它校验（只做基本判断，不联网）"""
    base = str(api_base or "").strip()
    if not base:
        return True                     # 留空 = 用默认地址
    if not base.startswith(("http://", "https://")):
        return False
    # 至少要有个主机名，"https://" 本身不算
    rest = base.split("://", 1)[1]
    host = rest.split("/", 1)[0]
    return bool(host.strip())


def _thinking_row(thinking, provider_id: str = "", model: str = ""):
    """把上层传来的"档位"归一成一张 {value,effort,style,...} 行（拿不到返回 None）

    兼容三种来源（向后兼容的根）：
      ① dict：providers.thinking_levels() 的某一行（本轮推荐用法，含各家 style/budget）；
      ② str：旧式档位字符串（"off"/"low"/"medium"/"high"/"minimal"/"max"…），
         有 provider/model 信息时按各家表查行，查不到退回通用表；
      ③ bool：旧配置 True/False → 等价 medium / off。
    """
    if isinstance(thinking, dict):
        return thinking
    if thinking is None or thinking == "":
        return None
    if provider_id or model:
        # 有服务商/模型信息：到各家官方表里找同 value 的那一行
        try:
            from . import providers as _p
            key = str(thinking).strip().lower() if not isinstance(thinking, bool) \
                else ("medium" if thinking else "off")
            levels = _p.thinking_levels(provider_id, model)
            for row in levels:
                if str(row.get("value")) == key:
                    return row
            # ⚠️⚠️ 没命中要分两种情况，绝不能一律"就近映射"：
            #   ① 该模型**支持思考但官方表里没有这一档**（kimi-k3 只有 low/high/max，
            #      没有 off；k2.7-code 只有单档 on）→ 就近落到表内合法档位。
            #      绝不返回 None 回退 deepseek 风格：那会给 k3 发 `thinking.disabled`，
            #      官方明确报错。
            #   ② 该模型**根本不支持思考**（表里只有 off 一档，例如模型名认不出来）→
            #      绝对不能把用户想要的 medium/high 映射成 off 再"发关闭"，
            #      那是把用户的"开思考"悄悄变成"关思考"。这种情况返回 None
            #      = 不表态（上层也不会画思考块），保持与旧版一致的行为。
            #   ③ 表里只有**一个非 off 档**（恒思考模型，如 kimi-k2.7-code 的 "on"）→
            #      只能落那一档；它的 style=always 会让 _thinking_params 什么都不发
            #      （官方不接受 disabled），恰好是"关不掉、也无需设"的正确表达。
            if len(levels) > 1:
                try:
                    fixed = _p.resolve_thinking_level(provider_id, model, key)
                    for row in levels:
                        if str(row.get("value")) == fixed:
                            return row
                except Exception:                  # noqa: BLE001
                    pass
            elif levels and str(levels[0].get("value")) != "off":
                return levels[0]
        except Exception:                          # noqa: BLE001
            pass
    return None


# ---------- 各家思考参数的请求体拼装 ----------
# 每个 style 对应一组 (off 载荷, 非 off 载荷构造函数)。style 认不出 = deepseek 风格：
# `reasoning_effort` 是 OpenAI 兼容网关的事实标准，`thinking{type}` 负责显式关闭。
# ⚠️ 官方字段口径（查证时间 2026-11-08，DeepSeek 已在线核实原文，其余为各家公开文档）：
#   · deepseek：`thinking:{type:enabled/disabled}` + `reasoning_effort:low/high/max`
#     （none 表示关；medium/minimal/xhigh 官方兼容映射，我们直接发官方值）
#   · effort（OpenAI o/gpt-5、xAI Grok）：只有 `reasoning_effort`；
#     off 发 `reasoning_effort:"none"`（OpenAI Responses 起支持；中转不认时
#     上层 ai.py 有"400 去参重试"兜底，最差这档没表态）
#   · toggle（Kimi）：`thinking:{type:enabled/disabled}`，官方无强度参数
#   · qwen（DashScope）：`enable_thinking:true/false`（可选 thinking_budget 未用）
#   · anthropic：`thinking:{type:enabled,budget_tokens:N}`（官方无语义档位名，
#     低/中/高 = 4096/8192/16384 预算，映射为本程序约定；走 Messages API 原生端点
#     时生效，走 OpenAI 兼容中转多半被忽略 → 上层 400/无效均有兜底）
#   · gemini：`thinking_config:{thinking_level:"low"/"high"}`，off = thinking_budget:0
def _thinking_params(thinking, provider_id: str = "", model: str = "") -> dict:
    """把"思考档位"翻译成请求体里要加的字段（返回 {} = 什么都不加）

    ⚠️ 本轮需求：档位改成「按各家官方 API 的真实档位与名称」后，请求体字段各家不同，
       所以上层（desktop/api/ai.py）现在传的是 providers.thinking_levels() 里的**一行
       dict**（含 value/effort/style/budget）。同时**保持向后兼容**：
       旧调用方仍传字符串档位（"off"/"low"/"medium"/"high"）或旧布尔 True/False 也能
       工作 —— 传了 provider_id/model 就按各家表解析，没传就退回 deepseek 风格
       （= 旧行为：thinking{type} + reasoning_effort）。

    规则（顺序固定）：
      · None / "" → 不表态：**不加任何参数**（老网关/中转对未知参数会 400，默认不传才安全）
      · off → 按 style 显式关闭 —— 推理模型（deepseek-v4 等）在服务端**默认就是开着的**，
        不显式关就会一直吐 reasoning_content（用户报的"没开思考按钮却有思考内容"根因）。
      · 非 off → 按 style 发各家的"开 + 强度"字段。
    ⚠️ 万一某个网关不认这些参数：上层（ai.py）收到 400 会**自动去掉思考参数重试一次**，
       用户最差只是"这一档没生效"，不会发不出去。
    """
    if thinking is None or thinking == "":
        return {}
    row = _thinking_row(thinking, provider_id, model)
    if row is None:
        # ② / ③：纯字符串或布尔 → 完全走旧口径（deepseek 风格）
        if thinking is True:
            level = "medium"
        elif thinking is False:
            level = "off"
        else:
            level = str(thinking).strip().lower()
        if level in ("", "none", "off", "disable", "disabled", "关", "关闭"):
            return {"thinking": {"type": "disabled"}}
        if level in ("low", "medium", "high", "minimal", "max"):
            return {"thinking": {"type": "enabled"}, "reasoning_effort": level}
        return {}       # 认不出来的档位 = 不表态，别把请求体写坏

    style = str(row.get("style") or "deepseek")
    value = str(row.get("value") or "").lower()
    effort = row.get("effort")

    # 「恒开无档」（kimi-k2.7-code 官方：thinking 永远开、传 disabled 直接报错、
    # 也没有 reasoning_effort）：**什么都不发**。多发任何一个字段都是 400，
    # 不表态才是官方唯一正确的调法。
    if style == "always":
        return {}

    if value == "off" or effort is None:
        if style == "effort":
            return {"reasoning_effort": "none"}
        if style == "toggle" or style == "deepseek":
            return {"thinking": {"type": "disabled"}}
        if style == "qwen":
            return {"enable_thinking": False}
        if style == "gemini":
            return {"thinking_config": {"thinking_budget": 0}}
        return {}       # anthropic：不发 thinking 块本来就不思考

    if style == "effort":
        return {"reasoning_effort": str(effort)}
    if style == "deepseek":
        return {"thinking": {"type": "enabled"}, "reasoning_effort": str(effort)}
    if style == "toggle":
        return {"thinking": {"type": "enabled"}}
    if style == "qwen":
        return {"enable_thinking": True}
    if style == "gemini":
        return {"thinking_config": {"thinking_level": str(effort)}}
    if style == "anthropic":
        budget = int(row.get("budget") or 8192)
        return {"thinking": {"type": "enabled", "budget_tokens": budget}}
    return {}


def _thinking_on(thinking, provider_id: str = "", model: str = "") -> bool:
    """这一档**要不要把思考带出去**（True = 界面上该有折叠块）

    与 _thinking_params 同一套解析：None/"" /off/认不出 → False（界面一个字都不出现）。
    dict 行按 value/effort 判；字符串/布尔沿用旧判定（reasoning_effort 有没有值）。
    """
    if thinking is None or thinking == "":
        return False
    row = _thinking_row(thinking, provider_id, model)
    if row is not None:
        # 「恒开无档」（style=always）：模型永远吐 reasoning_content，界面就该永远
        # 有折叠块 —— 这里若按 effort is None 判 False，k2.7-code 的思考会被**静默丢弃**
        # （用户明明看见官方网页有思考，我们的气泡却没有）。
        if str(row.get("style") or "") == "always":
            return True
        return str(row.get("value") or "").lower() != "off" and row.get("effort") is not None
    if isinstance(thinking, bool):
        return thinking
    level = str(thinking).strip().lower()
    return level in ("low", "medium", "high", "minimal", "max", "on")


def _build_request(messages: list, model: str, api_base: str,
                   max_tokens: int, temperature: float, stream: bool,
                   thinking=None, provider_id: str = ""):
    url = f"{normalize_api_base(api_base)}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": bool(stream),
    }
    if max_tokens and max_tokens > 0:
        payload["max_tokens"] = int(max_tokens)
    payload.update(_thinking_params(thinking, provider_id, model))
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return url, body



def chat(messages: list, api_key: str, model: str, api_base: str = "",
         max_tokens: int = 0, temperature: float = 0.7,
         timeout: int = DEFAULT_TIMEOUT, thinking=None,
         provider_id: str = "") -> ChatResult:
    """发一次非流式请求，返回 ChatResult（永不抛异常）
    max_tokens 传 0 = 不限制；不用流式是因为要自己解析 SSE、处理半路断流，出错分支多得多。
    ⚠️ Key 在这里再防御性清洗一遍（去不可见字符/空白/引号/Bearer 前缀）：
       设置页已清洗，但其它调用方（测试、旧配置直读）不一定走设置。
    ⚠️ `thinking`：本轮起推荐传 providers.thinking_levels() 里的**档位行 dict**
       （含各家 style/effort/budget）；仍兼容旧调用方传字符串档位
       （None / "off" / "low" / "medium" / "high"，也兼容旧 True/False）—— 见 _thinking_params。
       `provider_id`（可省）只在 thinking 是字符串/布尔时用来选各家官方档位表。
    """
    from ...utils.secret_store import sanitize_api_key
    api_key = sanitize_api_key(api_key)
    model = str(model or "").strip()

    if not api_key:
        return ChatResult(False, kind=KIND_NO_KEY, message="还没有配置 API Key")
    if not model:
        return ChatResult(False, kind=KIND_NO_MODEL, message="还没有配置模型名称")
    if not is_valid_api_base(api_base):
        return ChatResult(False, kind=KIND_CONFIG, message="接口地址不是有效的网址")

    url, body = _build_request(messages, model, api_base, max_tokens, temperature,
                              stream=False, thinking=thinking, provider_id=provider_id)
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            # 有些网关会挡没有 UA 的请求
            "User-Agent": "ToolsGCP-GCP-AI/1.0",
        })

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", "replace")
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        # HTTP 层有响应但状态码非 2xx：响应体里的服务端说明比状态码有用
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        return _from_http_error(exc.code, detail)
    except (socket.timeout, TimeoutError):
        return ChatResult(False, kind=KIND_TIMEOUT,
                          message=f"请求超时（{timeout} 秒），可能是网络慢或服务端繁忙")
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return ChatResult(False, kind=KIND_TIMEOUT, message=f"请求超时（{timeout} 秒）")
        return ChatResult(False, kind=KIND_NETWORK, message=f"连不上服务器：{reason}")
    except Exception as exc:
        return ChatResult(False, kind=KIND_UNKNOWN, message=f"请求失败：{exc}")

    result = _parse_success(text, status)
    # 思考档位为 off / 没表态（润色、测试连接那些路径）→ 连 reasoning 字段都不带回：
    # 上层按"有没有思考块"决定要不要渲染折叠 UI，留空 = 界面上什么都没有。
    if not _thinking_on(thinking, provider_id, model):
        result.reasoning = ""
    return result


# ==========================================================================
# 流式（SSE）请求：逐段回调，界面能一个字一个字地往外蹦
# ==========================================================================
# 为什么要单独写一份而不是给 chat() 加个 stream 参数：
#   · chat() 的调用方（润色、测试连接、工具循环）都要"整段结果"，改成流式反而要多一层拼装；
#   · 流式的错误分支和阻塞点完全不同（读到一半断流、半行 JSON、[DONE] 收尾），
#     混在一起最容易出的事故是"半路崩了但上层以为成功"。
# 契约：
#   · `on_chunk(accumulated_text)` 每次拿到的是**累计全文**（不是增量），前端直接整段替换
#     气泡文本就行，不用自己拼接 —— 少一处会错的地方；
#   · 回调里抛异常只会被吞掉并记进 aborted，**绝不打断读流**（前端事件推送失败很常见）；
#   · 永不抛异常，返回 ChatResult（ok=True 时 content 就是全文），语义与 chat() 一致；
#   · 任何失败（连不上 / 401 / 半路断 / 网关不认 stream）都返回 ok=False + kind，
#     调用方据此退回非流式的 chat()，界面最差也只是"没有逐字效果"，不会卡死或空屏。
STREAM_CHUNK_MIN_INTERVAL = 0.09      # 秒：约 90ms 回调一次（约 11 fps），足够像打字


def _sse_data_lines(buffer: str):
    """从 SSE 文本块里切出完整的 `data:` 载荷，返回 (载荷列表, 剩余未完整的尾巴)

    ⚠️ 必须只消费**完整行**：urllib 读到的是任意切分的字节块，一条 JSON 经常在中间被截断，
       半行去 json.loads 会抛，看起来像"服务端返回的不是 JSON"。留着的尾巴等下一块补全。
    """
    payloads = []
    while True:
        newline = buffer.find("\n")
        if newline < 0:
            break
        line = buffer[:newline].strip()
        buffer = buffer[newline + 1:]
        if not line or line.startswith(":"):     # 心跳 / 注释行
            continue
        if line.startswith("data:"):
            payloads.append(line[5:].strip())
    return payloads, buffer


def _sse_delta(payload: str) -> tuple:
    """一条 data: 载荷 → (正文增量, 思考增量, 是否结束)

    ⚠️⚠️ 正文与思考**各回各的**，绝不互相顶替（用户报的"没开思考按钮却输出思考内容"）：
      · `choices[0].delta.content`          → 正文增量
      · `choices[0].delta.reasoning_content` → 思考增量（推理模型才有）
    以前这里在 content 为空时拿 reasoning_content 顶上，思考期的包就全变成"正文"了。
    少数网关不返 delta 而是把整段塞在 message.content 里 —— 那才是正文兜底，
    **不**兜底 reasoning（没有正文就让它走"模型没有返回内容"的分支，别把思考当回答）。
    """
    if payload == "[DONE]":
        return "", "", True
    try:
        data = json.loads(payload)
    except Exception:
        return "", "", False
    if not isinstance(data, dict):
        return "", "", False
    error = data.get("error")
    if isinstance(error, (dict, str)):
        detail = error.get("message") if isinstance(error, dict) else error
        raise _StreamError(str(detail or "服务端返回错误"))
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return "", "", False
    first = choices[0] if isinstance(choices[0], dict) else {}
    delta = first.get("delta") if isinstance(first.get("delta"), dict) else {}
    text = str(delta.get("content") or "")
    reasoning = str(delta.get("reasoning_content") or "")
    if not text and not reasoning:
        # 少数网关不返 delta 而是把整段塞在 message.content 里
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        text = str(message.get("content") or "")
    finished = str(first.get("finish_reason") or "") in ("stop", "length", "content_filter")
    return text, reasoning, finished


class _StreamError(Exception):
    """流式响应体里带回来的服务端错误（由 _sse_delta 抛出、chat_stream 接住翻译）"""


def chat_stream(messages: list, api_key: str, model: str, api_base: str = "",
                max_tokens: int = 0, temperature: float = 0.7,
                timeout: int = DEFAULT_TIMEOUT, on_chunk=None,
                should_stop=None, on_reasoning=None, thinking=None,
                provider_id: str = "") -> ChatResult:
    """流式发一次 chat/completions，边收边回调 `on_chunk(累计全文)`。

    `should_stop()` 返回 True 时**立刻中断读取**并返回 ok=False / kind="cancelled"
    （前端点了"停止"，别再往已经作废的气泡上写字）。

    ⚠️ `on_reasoning(累计思考文本)`：推理模型的思考流**只走这个回调**，绝不混进
       `on_chunk`（用户报的"没开思考按钮却看到思考内容"的另一半根因）。
       `thinking`：本轮起推荐传 providers.thinking_levels() 里的档位行 dict；
       兼容旧式字符串档位（None/"off"/"low"/"medium"/"high"）与旧布尔。见 _thinking_params。
       `provider_id`（可省）只在 thinking 是字符串/布尔时用来选各家官方档位表。
    """
    from ...utils.secret_store import sanitize_api_key
    api_key = sanitize_api_key(api_key)
    model = str(model or "").strip()

    if not api_key:
        return ChatResult(False, kind=KIND_NO_KEY, message="还没有配置 API Key")
    if not model:
        return ChatResult(False, kind=KIND_NO_MODEL, message="还没有配置模型名称")
    if not is_valid_api_base(api_base):
        return ChatResult(False, kind=KIND_CONFIG, message="接口地址不是有效的网址")

    url, body = _build_request(messages, model, api_base, max_tokens, temperature,
                              stream=True, thinking=thinking, provider_id=provider_id)
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "ToolsGCP-GCP-AI/1.0",
            # 有些网关会自作主张压缩 SSE，压了就读不到及时的分块
            "Accept-Encoding": "identity",
        })

    parts = []                     # 收到的**正文**增量（最后 join 成全文）
    think_parts = []               # 收到的**思考**增量（与正文完全分开，绝不互替）
    emitted_len = -1               # 上次回调时的长度：没变就不重复回调
    last_emit = 0.0
    think_len = -1
    think_last = 0.0
    # ⚠️⚠️ 本轮修复用户报的「思考没输出完毕 AI 就开始回复生成文本」（严格顺序）：
    #    `think_pending` = 思考又长了、但因为节流**没推出去**。
    #    正文第一次要推之前必须先把它补推完（见 _flush 里那段），
    #    否则界面会出现"正文已经开始逐字、思考块还停在半截、过一会儿思考又突然
    #    蹦出一大段" —— 就是这个顺序错乱，不是模型的问题。
    think_pending = False
    t_started = time.monotonic()   # 取证：首字/首思考到达各用了多久（见下面两条日志）
    t_first_think = None
    t_first_body = None
    saw_any_delta = False          # 一条 delta 都没收到 → 多半是网关不认 stream

    def _flush(force: bool) -> None:
        """按节流把累计全文推给回调；force=True 用于收尾（最后一段必须必达）"""
        # ⚠️ t_first_body 也要 nonlocal：它是**取证计数器**，本函数里要赋值。
        #    漏了 nonlocal 会让它变成本函数的局部名，于是上面那句读它直接
        #    UnboundLocalError —— 而这个异常会被外层 try 吞掉，表现是
        #    "思考回调正常、正文一次都不推"，极难看出是这里少写了一个词。
        nonlocal emitted_len, last_emit, think_pending, t_first_body
        if on_chunk is None:
            return
        text = "".join(parts)
        if text == "":
            return          # 一个字都还没有（多半整条流只有思考）：空串不推，
                            # 否则前端会收到一条 text="" 的 delta，白闪一下
        if not force:
            now = time.monotonic()
            if len(text) == emitted_len or (now - last_emit) < STREAM_CHUNK_MIN_INTERVAL:
                return
        # ① 严格顺序：正文出门前，先把**欠着的**思考补推干净
        if think_pending:
            _flush_reasoning(True)
        if t_first_body is None:
            t_first_body = time.monotonic() - t_started
        emitted_len = len(text)
        last_emit = time.monotonic()
        try:
            on_chunk(text)
        except Exception:                          # noqa: BLE001
            # 推前端失败（窗口正在销毁等）绝不能让读流线程崩；继续读完整段再说
            pass

    def _flush_reasoning(force: bool) -> None:
        """思考流的节流回调（与 _flush 同一口径，推的是 reasoning）

        ⚠️ 档位是 off / 没表态时**一个字都不推**：
           思考增量照样收进 think_parts（收尾时按档位决定要不要带出去），
           但绝不让它出现在界面上 —— 这就是"没开思考却看到思考内容"的根治点。
        """
        nonlocal think_len, think_last, think_pending, t_first_think
        if on_reasoning is None or not _thinking_on(thinking, provider_id, model):
            return
        text = "".join(think_parts)
        if not force:
            now = time.monotonic()
            if len(text) == think_len:
                return
            if (now - think_last) < STREAM_CHUNK_MIN_INTERVAL:
                # 节流跳过 = 欠了一次推送，**必须记下来**（正文推之前要补），
                # 否则这个信息就永久丢了 —— 以前就是这个丢失导致"思考落后于正文"。
                think_pending = True
                return
        if text == "" and not force:
            return
        if t_first_think is None and text:
            t_first_think = time.monotonic() - t_started
        think_len = len(text)
        think_last = time.monotonic()
        think_pending = False
        try:
            on_reasoning(text)
        except Exception:                          # noqa: BLE001
            pass

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            content_type = str(response.headers.get("Content-Type") or "")
            if "text/event-stream" not in content_type.lower():
                # 网关把 stream 当普通请求处理了：整段 JSON 一次回来
                raw = response.read().decode("utf-8", "replace")
                parsed = _parse_success(raw, status)
                if parsed.ok:
                    parts[:] = [parsed.content]
                    think_parts[:] = [parsed.reasoning or ""]
                    _flush(True)
                    _flush_reasoning(True)
                # 档位为 off / 没表态 → 不把 reasoning 带回上层（界面上不该出现思考块）
                if not _thinking_on(thinking, provider_id, model):
                    parsed.reasoning = ""
                return parsed
            buffer = ""
            # ⚠️ 必须用**增量解码器**：response.read(1024) 切的是字节，一个中文字（UTF-8 3 字节）
            #    经常被切成两块，直接 chunk.decode("utf-8","replace") 会把半个字变成 \ufffd，
            #    表现就是"流式输出里冒出乱码方块"。增量解码器会把残缺的尾字节留到下一块。
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            # ⚠️️ 必须用 **read1**（有则用）而不是 read(1024) —— 这是"回答不是逐字输出、
            #    而是一次性整段蹦出来"的**真正根因**：
            #      · `HTTPResponse.read(n)` 会**内部循环直到攒够 n 字节**才返回；
            #      · 一个中文回答 340 字 ≈ 1024 字节，绝大多数回答根本凑不满 1024，
            #        于是 read(1024) 一直阻塞到**服务端发完并关闭连接**才返回 ——
            #        整段文字一次性到手，前端只收到一条 delta，看起来就是"啪"地全出来；
            #      · `read1(n)` 只做**一次**底层 socket 读，有多少返回多少（可能只有几十字节），
            #        SSE 的分块节奏因此能原样透到界面上，逐字效果就回来了。
            #    老内核/别的响应对象没有 read1 时退回 readline()（按行读同样是增量的），
            #    两者都没有才退回 read()（最差 = 整段一次，但功能不坏）。
            read1 = getattr(response, "read1", None)
            readline = getattr(response, "readline", None)
            while True:
                if should_stop is not None and should_stop():
                    return ChatResult(False, kind="cancelled", message="已停止", status=status)
                chunk = b""
                if callable(read1):
                    try:
                        chunk = read1(4096)
                    except Exception:                     # noqa: BLE001
                        chunk = b""
                if not chunk and callable(readline):
                    try:
                        chunk = readline(4096)
                    except Exception:                     # noqa: BLE001
                        chunk = b""
                if not chunk:
                    if not callable(read1) and not callable(readline):
                        chunk = response.read(1024)
                    if not chunk:
                        break
                buffer += decoder.decode(chunk)
                payloads, buffer = _sse_data_lines(buffer)
                for payload in payloads:
                    try:
                        delta, think_delta, finished = _sse_delta(payload)
                    except _StreamError as exc:
                        return ChatResult(False, kind=KIND_UNKNOWN,
                                          message=f"服务端返回错误：{exc}", status=status)
                    except Exception:              # noqa: BLE001
                        continue                   # 单条载荷解析不了不掐整条流
                    if think_delta:
                        think_parts.append(think_delta)
                        _flush_reasoning(False)
                    if finished:
                        _flush(True)
                        _flush_reasoning(True)
                        return _stream_result(parts, status, think_parts, thinking, provider_id, model)
                    if delta:
                        saw_any_delta = True
                        parts.append(delta)
                        _flush(False)
            # 循环结束 = 连接自己关了的（正常也这样收尾：[DONE] 之后服务端就断了）
            _flush(True)
            _flush_reasoning(True)
            if parts:
                return _stream_result(parts, status, think_parts, thinking, provider_id, model)
            if not saw_any_delta and not think_parts:
                return ChatResult(False, kind=KIND_BAD_JSON, status=status,
                                  message="服务端没有按流式格式返回内容")
            return ChatResult(False, kind=KIND_BAD_JSON, status=status,
                              message="模型没有返回内容", raw="")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        return _from_http_error(exc.code, detail)
    except (socket.timeout, TimeoutError):
        if parts:
            # 已经有半段：别当失败丢掉，照实用
            return _stream_result(parts, 200, think_parts, thinking, provider_id, model)
        return ChatResult(False, kind=KIND_TIMEOUT,
                          message=f"请求超时（{timeout} 秒），可能是网络慢或服务端繁忙")
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return ChatResult(False, kind=KIND_TIMEOUT, message=f"请求超时（{timeout} 秒）")
        return ChatResult(False, kind=KIND_NETWORK, message=f"连不上服务器：{reason}")
    except Exception as exc:                       # noqa: BLE001
        if parts:
            return _stream_result(parts, 200, think_parts, thinking, provider_id, model)
        return ChatResult(False, kind=KIND_UNKNOWN, message=f"请求失败：{exc}")


def _stream_result(parts: list, status: int, think_parts: list = None,
                   thinking=None, provider_id: str = "", model: str = "") -> ChatResult:
    """把收到的分块拼成成功结果（与 _parse_success 一样的 strip 口径）

    ⚠️ 思考文本只有在档位**开着**（非 off 的档位行 / 旧的 low/medium/high/max）时才带出去；
       而且**永远**放在 `reasoning` 字段里，绝不塞进 content。
    """
    content = "".join(parts).strip()
    reasoning = ("".join(think_parts or []).strip()) \
        if _thinking_on(thinking, provider_id, model) else ""
    if not content:
        if reasoning:
            # 只有思考、没有正文：给明确原因（和 _parse_success 同口径），
            # 而不是"模型没有返回内容"那种看不出方向的文案。
            return ChatResult(False, kind=KIND_BAD_JSON, status=status,
                              message="模型只返回了思考过程、没有给出回答，"
                                      "可以关掉「思考」再试一次",
                              reasoning=reasoning)
        return ChatResult(False, kind=KIND_BAD_JSON, status=status,
                          message="模型没有返回内容，换个说法再试一次")
    return ChatResult(True, content=content, status=status, reasoning=reasoning)


def _from_http_error(status: int, detail: str) -> ChatResult:
    """把 HTTP 错误码翻译成"用户能看懂 + 知道下一步做什么"的说明"""
    # 从响应体里挖服务端给的原因（OpenAI 格式是 {"error": {"message": "..."}}）
    server_message = ""
    try:
        data = json.loads(detail) if detail else {}
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict):
            server_message = str(error.get("message") or "")
        elif isinstance(error, str):
            server_message = error
        if not server_message and isinstance(data, dict):
            server_message = str(data.get("message") or "")
    except Exception:
        server_message = detail.strip()[:200]

    suffix = f"（服务端说明：{server_message}）" if server_message else ""

    if status in (401, 403):
        # ⚠️ 提示里点一句"可能属于别的服务商 / 已过期"：切换服务商后沿用旧 Key 是
        #    最常见的 401 来源（Kimi 的 Key 发给 DeepSeek），别让用户以为软件坏了。
        # ⚠️ 本轮需求：用户原话「当未填写API Key时**或者填写有误**会固定回复
        #    其中包括"请填写<API Key>" 这个是下滑线字体 点击跳转页面到设置中的GCP-AI 位置」。
        #    → "填写有误"（401/403）这条也要带上 `请填写<API Key>` 这个**固定字面量**，
        #      前端 aiSplitLinks 认它 → 渲染成蓝色下划线，点了跳 设置 → GCP-AI。
        #      （以前写的是"请到 设置 → API Key 检查"，那是普通文字，看得到点不动。）
        return ChatResult(False, kind=KIND_AUTH, status=status,
                          message=f"API Key 无效或没有权限（可能已过期/被撤销，或这把 Key "
                                  f"不属于当前服务商），请重新填写<API Key> 后再试{suffix}")
    if status == 429:
        return ChatResult(False, kind=KIND_RATE, status=status,
                          message=f"请求过于频繁或额度不足，稍后再试{suffix}")
    if status == 400:
        return ChatResult(False, kind=KIND_BAD_REQUEST, status=status,
                          message=f"请求被拒绝，通常是模型名称或参数不对{suffix}")
    if status == 404:
        return ChatResult(False, kind=KIND_CONFIG, status=status,
                          message=f"接口地址不存在（404），请检查 设置 → 接口地址{suffix}")
    if 500 <= status < 600:
        return ChatResult(False, kind=KIND_SERVER, status=status,
                          message=f"服务端出错（{status}），过一会儿再试{suffix}")
    return ChatResult(False, kind=KIND_UNKNOWN, status=status,
                      message=f"请求失败（HTTP {status}）{suffix}")


def _parse_success(text: str, status: int) -> ChatResult:
    """解析成功响应，取 choices[0].message.content"""
    try:
        data = json.loads(text)
    except Exception:
        return ChatResult(False, kind=KIND_BAD_JSON, status=status,
                          message="服务端返回的不是 JSON，可能是接口地址指向了网页",
                          raw=text[:200])

    if not isinstance(data, dict):
        return ChatResult(False, kind=KIND_BAD_JSON, status=status,
                          message="服务端返回结构异常", raw=text[:200])

    # 有些兼容网关把错误塞在 200 里
    if isinstance(data.get("error"), (dict, str)) and not data.get("choices"):
        error = data["error"]
        detail = error.get("message") if isinstance(error, dict) else error
        return ChatResult(False, kind=KIND_UNKNOWN, status=status,
                          message=f"服务端返回错误：{detail}", raw=text[:200])

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ChatResult(False, kind=KIND_BAD_JSON, status=status,
                          message="服务端没有返回任何回答", raw=text[:200])

    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = str(message.get("content") or "").strip()
    # ⚠️ 思考与正文**分开**（用户报的"没开思考按钮却看到思考内容"的同步路径根因）：
    #    以前 content 为空时拿 reasoning_content 顶成回答，自言自语的"用户问…我应该…"
    #    就是这么混进正文的。现在 reasoning 只进 ChatResult.reasoning，绝不进 content。
    reasoning = str(message.get("reasoning_content") or "").strip()

    if not content:
        finish = str(first.get("finish_reason") or "")
        if finish == "length":
            # kind 用独立的 KIND_LENGTH（见上面注释）：聊天路径照样报错引导用户调大上限，
            # 但「测试连接」能认出"这是截断、不是连不上"。
            return ChatResult(False, kind=KIND_LENGTH, status=status,
                              message="回答被长度上限截断了，请调大「最大 token 量」",
                              reasoning=reasoning)
        if reasoning:
            # 只有思考、没有正文：给明确错误，而不是把思考当回答吐出去
            return ChatResult(False, kind=KIND_BAD_JSON, status=status,
                              message="模型只返回了思考过程、没有给出回答，"
                                      "可以关掉「思考」再试一次",
                              reasoning=reasoning, raw=text[:200])
        return ChatResult(False, kind=KIND_BAD_JSON, status=status,
                          message=f"模型没有返回内容（finish_reason={finish or '未知'}）",
                          raw=text[:200])

    return ChatResult(True, content=content, status=status, reasoning=reasoning)
