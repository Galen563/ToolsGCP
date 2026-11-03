"""AI 服务商与模型清单，设置页"服务商 / 模型"两个下拉框的数据源。
每家给：label（显示名）、api_base（OpenAI 兼容地址）、models（第一个是默认选中项）、
hint（去哪申请 key）。
⚠️ 模型 id 比软件发版更快过期，所以设置页的模型框是可编辑下拉框，清单只是常用选项；
想用自建/中转（Ollama、vLLM、one-api 等）选自定义自己填地址。
"""

# 服务商 id（存进设置的是这个，不是显示名，以后改显示名不影响老配置）
PROVIDER_DEEPSEEK = "deepseek"
PROVIDER_OPENAI = "openai"
PROVIDER_CLAUDE = "claude"
PROVIDER_GROK = "grok"
PROVIDER_KIMI = "kimi"
PROVIDER_QWEN = "qwen"
PROVIDER_SILICONFLOW = "siliconflow"
PROVIDER_CUSTOM = "custom"

DEFAULT_PROVIDER = PROVIDER_DEEPSEEK

# 顺序即下拉框顺序：国内常用的在前，国外三家紧随其后
PROVIDERS = [
    {
        "id": PROVIDER_DEEPSEEK,
        "label": "DeepSeek（深度求索）",
        "api_base": "https://api.deepseek.com/v1",
        "models": [
            # ⚠️ 这里是**界面显示名**：deepseek-v4.1-flash（V4.1-Flash）与 deepseek-v4-pro。
            #   官方文档（api-docs.deepseek.com）：API 调用模型名必须写 deepseek-flash，
            #   它由 DeepSeek-V4.1-Flash-1017 提供服务；deepseek-v4.1-flash 不是 API 名，
            #   直接传会被服务端 400 拒绝 —— 所以发送前一律走 resolve_api_model() 转换。
            "deepseek-v4.1-flash",     # V4.1-Flash（界面显示名；API 内部名 = deepseek-flash）
            "deepseek-v4-pro",         # V4-Pro，能力最强
        ],
        "hint": "在 platform.deepseek.com 申请 API Key",
    },
    {
        "id": PROVIDER_OPENAI,
        "label": "OpenAI（ChatGPT）",
        "api_base": "https://api.openai.com/v1",
        "models": [
            "gpt-5.1",
            "gpt-5.1-mini",
            "gpt-4.1",
        ],
        "hint": "在 platform.openai.com 申请 API Key",
    },
    {
        "id": PROVIDER_CLAUDE,
        "label": "Anthropic（Claude）",
        "api_base": "https://api.anthropic.com/v1",
        "models": [
            "claude-sonnet-4-6",
            "claude-opus-4-1",
            "claude-haiku-4-5",
        ],
        "hint": "在 console.anthropic.com 申请 API Key",
    },
    {
        "id": PROVIDER_GROK,
        "label": "xAI（Grok）",
        "api_base": "https://api.x.ai/v1",
        "models": [
            "grok-4",
            "grok-4-fast",
            "grok-3",
        ],
        "hint": "在 console.x.ai 申请 API Key",
    },
    {
        "id": PROVIDER_KIMI,
        "label": "Kimi（月之暗面）",
        "api_base": "https://api.moonshot.cn/v1",
        "models": [
            "kimi-k3",
            "kimi-k2.7-code",
            "kimi-k2.6",
        ],
        "hint": "在 platform.kimi.com 申请 API Key",
    },
    {
        "id": PROVIDER_QWEN,
        "label": "通义千问（阿里云百炼）",
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": [
            "qwen3-max",
            "qwen-plus",
            "qwen-flash",
        ],
        "hint": "在阿里云百炼控制台申请 API Key（有免费额度）",
    },
    {
        "id": PROVIDER_SILICONFLOW,
        "label": "硅基流动 SiliconFlow",
        "api_base": "https://api.siliconflow.cn/v1",
        "models": [
            "deepseek-ai/DeepSeek-V3",
            "Qwen/Qwen3-8B",
            "Qwen/Qwen3-32B",
        ],
        "hint": "聚合平台，模型很多；具体 id 以控制台的模型广场为准",
    },
    {
        "id": PROVIDER_CUSTOM,
        "label": "自定义（OpenAI 兼容）",
        "api_base": "",                   # 留空：让用户自己填
        "models": [],
        "hint": "任何 OpenAI 兼容接口都行：本地 Ollama / vLLM / one-api 等，填完整地址",
    },
]

# id -> 服务商字典
PROVIDER_MAP = {p["id"]: p for p in PROVIDERS}


def get_provider(provider_id: str) -> dict:
    """取服务商信息；认不出的 id 返回 None"""
    return PROVIDER_MAP.get(str(provider_id or "").strip())


def provider_label(provider_id: str) -> str:
    provider = get_provider(provider_id)
    return provider["label"] if provider else str(provider_id or "")


# ============ 多语言 ============
# ⚠️ 显示名与提示必须跟着界面语言走，整条放在 set_language.json 的 settings 段，
#    key 为 ai_provider_<id> / ai_provider_hint_<id>；id 本身不变。
#语言文件缺失时的英文兜底（与 set_language.json 的 English 一列一致）
_PROVIDER_LABEL_EN = {
    PROVIDER_DEEPSEEK: "DeepSeek",
    PROVIDER_OPENAI: "OpenAI (ChatGPT)",
    PROVIDER_CLAUDE: "Anthropic (Claude)",
    PROVIDER_GROK: "xAI (Grok)",
    PROVIDER_KIMI: "Kimi (Moonshot)",
    PROVIDER_QWEN: "Qwen (Alibaba Cloud Bailian)",
    PROVIDER_SILICONFLOW: "SiliconFlow",
    PROVIDER_CUSTOM: "Custom (OpenAI-compatible)",
}

_PROVIDER_HINT_EN = {
    PROVIDER_DEEPSEEK: "Get an API key at platform.deepseek.com",
    PROVIDER_OPENAI: "Get an API key at platform.openai.com",
    PROVIDER_CLAUDE: "Get an API key at console.anthropic.com",
    PROVIDER_GROK: "Get an API key at console.x.ai",
    PROVIDER_KIMI: "Get an API key at platform.kimi.com",
    PROVIDER_QWEN: "Get an API key in the Alibaba Cloud Bailian console (free quota available)",
    PROVIDER_SILICONFLOW: "Aggregator with many models; check the console model list for exact ids",
    PROVIDER_CUSTOM: "Any OpenAI-compatible endpoint: local Ollama / vLLM / one-api, etc. Enter the full URL",
}


def _localized(key: str, fallback: str) -> str:
    """从 settings 段取一条文案（拿不到就用 fallback，绝不显示键名）"""
    try:
        from ...core.language_manager import get_current_manager
        manager = get_current_manager()
        if manager is not None:
            text = manager.get_text("settings", key)
            if text and text != key:
                return str(text)
    except Exception:
        pass
    return fallback


def provider_display(provider_id: str) -> str:
    """服务商在下拉框里的显示名（按当前界面语言）"""
    pid = str(provider_id or "").strip()
    provider = get_provider(pid)
    if provider is None:
        return pid
    return _localized(f"ai_provider_{pid}", _PROVIDER_LABEL_EN.get(pid, provider["label"]))


def provider_hint(provider_id: str) -> str:
    """服务商那句提示（去哪申请 key），按当前界面语言"""
    pid = str(provider_id or "").strip()
    provider = get_provider(pid)
    if provider is None:
        return ""
    return _localized(f"ai_provider_hint_{pid}",
                      _PROVIDER_HINT_EN.get(pid, str(provider.get("hint") or "")))


def provider_items() -> list:
    """下拉框用的 [(id, 显示名), ...]（顺序就是 PROVIDERS 的顺序）"""
    return [(p["id"], provider_display(p["id"])) for p in PROVIDERS]


def default_api_base(provider_id: str, fallback: str = "") -> str:
    provider = get_provider(provider_id)
    if provider and provider["api_base"]:
        return provider["api_base"]
    return fallback


def models_of(provider_id: str) -> list:
    provider = get_provider(provider_id)
    return list(provider["models"]) if provider else []


def default_model(provider_id: str) -> str:
    """该服务商的默认模型（列表第一个，界面显示名）"""
    models = models_of(provider_id)
    return models[0] if models else ""


# 界面显示名 → 官方 API 模型名的映射。
# 官方文档（api-docs.deepseek.com）：API 调用模型名必须写 deepseek-flash，
# 它由 DeepSeek-V4.1-Flash-1017 提供服务；deepseek-v4.1-flash 只是版本叫法，
# 直接传会被服务端 400 拒绝。其余名字（自定义/中转）原样透传。
API_MODEL_ALIASES = {
    "deepseek-v4.1-flash": "deepseek-flash",
}


def resolve_api_model(provider_id: str, name: str) -> str:
    """把设置页的「界面显示名」解析成真正发给 API 的 model。
    ⚠️ 只转换 API_MODEL_ALIASES 里明确映射过的名字；其它名字原样返回
       （用户手填的自定义/中转模型名不能被程序改动）。
    """
    raw = str(name or "").strip()
    if not raw:
        return raw
    pid = str(provider_id or "").strip().lower()
    if pid == PROVIDER_DEEPSEEK:
        return API_MODEL_ALIASES.get(raw, raw)
    return raw


def guess_provider(api_base: str, model: str = "") -> str:
    """根据接口地址（和模型名）反推服务商 id
    用途：老配置里只有 api_base + model_name，打开设置页时要能选中原来那一项。
    先按地址特征串匹配，再按模型名前缀猜，都不像就返回自定义。
    """
    base = str(api_base or "").strip().lower()
    if base:
        for provider in PROVIDERS:
            if provider["id"] == PROVIDER_CUSTOM or not provider["api_base"]:
                continue
            host = provider["api_base"].split("://", 1)[-1].split("/", 1)[0].lower()
            if host and host in base:
                return provider["id"]

    name = str(model or "").strip().lower()
    if name:
        if name.startswith(("deepseek", "deep-seek")):
            return PROVIDER_DEEPSEEK
        if name.startswith(("gpt", "o1", "o3", "o4", "chatgpt")):
            return PROVIDER_OPENAI
        if name.startswith(("claude", "anthropic")):
            return PROVIDER_CLAUDE
        if name.startswith(("grok", "xai")):
            return PROVIDER_GROK
        if name.startswith(("kimi", "moonshot")):
            return PROVIDER_KIMI
        if name.startswith(("qwen", "qwq", "tongyi")):
            return PROVIDER_QWEN

    return PROVIDER_CUSTOM if base else DEFAULT_PROVIDER
