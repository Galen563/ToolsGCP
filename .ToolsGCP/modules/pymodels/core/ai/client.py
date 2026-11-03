"""GCP-AI 的模型调用客户端（OpenAI 兼容格式，只用标准库 urllib + json）。
    POST {api_base}/chat/completions，Authorization: Bearer {api_key}
    result = chat(messages, api_key, model, api_base, timeout=60)
    result.ok / result.kind / result.message   # kind 用来给界面挑文案和颜色
"""

import json
import socket
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
KIND_UNKNOWN = "unknown"


class ChatResult:
    """一次调用的结果（不抛异常，调用方只看 ok / kind / message）"""

    def __init__(self, ok: bool, content: str = "", kind: str = KIND_OK,
                 message: str = "", status: int = 0, raw: str = ""):
        self.ok = ok
        self.content = content
        self.kind = kind
        self.message = message      # 给用户看的中文说明
        self.status = status        # HTTP 状态码（0 = 没走到 HTTP 层）
        self.raw = raw              # 原始响应片段（排查用，只取前若干字符）

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


def _build_request(messages: list, model: str, api_base: str,
                   max_tokens: int, temperature: float, stream: bool):
    url = f"{normalize_api_base(api_base)}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": bool(stream),
    }
    if max_tokens and max_tokens > 0:
        payload["max_tokens"] = int(max_tokens)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return url, body


def chat(messages: list, api_key: str, model: str, api_base: str = "",
         max_tokens: int = 0, temperature: float = 0.7,
         timeout: int = DEFAULT_TIMEOUT) -> ChatResult:
    """发一次非流式请求，返回 ChatResult（永不抛异常）
    max_tokens 传 0 = 不限制；不用流式是因为要自己解析 SSE、处理半路断流，出错分支多得多。
    ⚠️ Key 在这里再防御性清洗一遍（去不可见字符/空白/引号/Bearer 前缀）：
       设置页已清洗，但其它调用方（测试、旧配置直读）不一定走设置。
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
                              stream=False)
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

    return _parse_success(text, status)


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
        return ChatResult(False, kind=KIND_AUTH, status=status,
                          message=f"API Key 无效或没有权限（可能已过期/被撤销，或这把 Key "
                                  f"不属于当前服务商），请到 设置 → API Key 检查{suffix}")
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

    if not content:
        # 推理类模型偶尔把内容放在 reasoning_content 里（或者被内容过滤拦了）
        reasoning = str(message.get("reasoning_content") or "").strip()
        finish = str(first.get("finish_reason") or "")
        if reasoning:
            content = reasoning
        elif finish == "length":
            return ChatResult(False, kind=KIND_BAD_REQUEST, status=status,
                              message="回答被长度上限截断了，请调大「最大 token 量」")
        else:
            return ChatResult(False, kind=KIND_BAD_JSON, status=status,
                              message=f"模型没有返回内容（finish_reason={finish or '未知'}）",
                              raw=text[:200])

    return ChatResult(True, content=content, status=status)
