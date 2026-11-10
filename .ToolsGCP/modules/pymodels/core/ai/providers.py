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
        # ⚠️ 本轮需求（用户原话）：「服务商的自定义不应该有一个"（OPENAI兼容）"的text」。
        #    "OpenAI 兼容"是**接口协议**的说明，不是厂商名，出现在下拉/卡片里很吵
        #    （协议说明已经挪到接口地址那一行的提示文案里了）。
        "label": "自定义",
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
    PROVIDER_CUSTOM: "Custom",
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


# ==========================================================================
# 模型「思考」能力表（本轮需求：输入框右下角的模型切换 UI + 思考开关）
# ==========================================================================
# 需求原话：「选择不同模型下面的思考也会默认跟随对应模型变化，默认思考都为关闭，
#             未填写 APIkey 的模型不显示」。
# 拆开就是三件事：
#   ① 每个模型**能不能**思考（能力，按模型名判定，认不出来就当不支持）；
#   ② 默认状态永远是关（不管能不能思考，新选一个模型都先关着）；
#   ③ 没配 Key 的服务商整组模型都不出现在候选里（由调用方按 key 状态过滤，
#      这里只负责给出"有哪些模型 + 支不支持思考"）。
# ⚠️ 为什么按**名字前缀**判能力而不是写死一张全表：模型清单会随服务商发版变，
#    写死的全表一定会过期；前缀规则认不出来时退回"不支持思考"，
#    最坏只是用户少一个开关，绝不会把不支持的模型硬塞一个 thinking 参数过去（那会 400）。
_THINKING_PREFIXES = (
    "deepseek-v4",          # V4 系列（flash / pro）在服务端默认就会思考
    "deepseek-reasoner",    # R1 老名字
    "deepseek-flash",       # resolve_api_model 之后的 API 名
    "o1", "o3", "o4",       # OpenAI 推理系列
    "gpt-5",                # GPT-5 起支持
    "claude-sonnet-4", "claude-opus", "claude-haiku-4",  # Anthropic extended thinking
    "grok-3", "grok-4",     # xAI 推理线（grok-3 起有 reasoning_effort）
    "kimi-k2", "kimi-k3",   # Moonshot 推理线
    "qwq", "qwen3",         # 通义推理线
    "gemini-2",             # Gemini 2.x 动态思考（2.5 起 thinking_level）
)


def model_supports_thinking(provider_id: str, name: str) -> bool:
    """这个模型**能不能**思考（界面据此决定要不要画思考开关）

    ⚠️ 只看模型名，不看服务商：自定义/中转地址跑的常常就是这些模型，
       按名字认比按服务商认更准（用户填的中转 `deepseek-r1` 也该有开关）。
    """
    raw = str(name or "").strip().lower()
    if not raw:
        return False
    # 先去掉服务商前缀（"deepseek/deepseek-v4.1-flash" 这种带路由写法的中转模型名）
    tail = raw.rsplit("/", 1)[-1]
    for prefix in _THINKING_PREFIXES:
        if tail.startswith(prefix):
            return True
    return False


def thinking_default(provider_id: str = "", name: str = "") -> str:
    """新选一个模型时思考的默认档位 —— 需求「默认思考都为关闭」→ 能关的模型恒 "off"。

    ⚠️ 本轮修订（官方核实 kimi-k3 系思考**恒开不可关**后）：
       表里没有 off 的模型（k3/k3.1-pro 只有 low/high/max；k2.7-code 只有 on）
       不可能"默认关"，默认取**表内最低档**（官方允许的最小强度）。
       契约变化：`thinking_levels()` 的第一档**不再恒为 off**，前端滑块按数组长度
       动态分段、并且当档位集合不含 off 时不能强写 off（见 ai-frontend 同步改动）。
       单独留一个函数而不是让前端各自写 "off"：以后要改默认值只改这一处。
    """
    values = [row.get("value") for row in thinking_levels(provider_id, name)]
    if THINKING_OFF in values or not values:
        return THINKING_OFF
    return str(values[0])


# 思考档位（本轮需求：「把思考开关改为对接官方API的多档位滑动强度而不是只有开和关（类似Codex）」）
#   · 顺序 = 滑块从左到右的顺序，第一个必须是 off（默认关，需求原话）；
#   · value 是**存进设置的规范值**；effort 是**发给 API 的 reasoning_effort 值**（None = 不发）；
#   · label 只给人看，不进请求体。
#   · style 决定请求体长什么样（各家官方 API 字段不同，见 client._thinking_params）。
# ⚠️ THINKING_LEVELS 是"认不出家族时的通用表"（OpenAI 风格三档，保守口径）。
THINKING_OFF = "off"
THINKING_STYLE_EFFORT = "effort"            # OpenAI / xAI 风格：只发 reasoning_effort
THINKING_STYLE_DEEPSEEK = "deepseek"        # DeepSeek 风格：thinking{type} + reasoning_effort
THINKING_STYLE_TOGGLE = "toggle"            # Kimi / 通用 OpenAI 兼容：thinking{type}，无强度
THINKING_STYLE_ALWAYS = "always"            # 思考恒开且无档位（kimi-k2.7-code）：不发任何参数
THINKING_STYLE_QWEN = "qwen"                # DashScope 风格：enable_thinking 布尔
THINKING_STYLE_ANTHROPIC = "anthropic"      # Anthropic 风格：thinking{budget_tokens}
THINKING_STYLE_GEMINI = "gemini"            # Gemini 风格：thinking_config{thinking_level}


def _lvl(value: str, label: str, effort, style: str, **extra) -> dict:
    """档位条目：前端只吃 value/label/effort（契约固定），style 等其余字段供
    client._thinking_params 决定请求体；前端原样存回即可，不解释这些字段。"""
    row = {"value": value, "label": label, "effort": effort, "style": style}
    row.update(extra)
    return row


# 通用回退表（官方未公开档位或认不出的模型用它，行为与旧版一致）
THINKING_LEVELS = (
    {"value": "off", "effort": None, "style": THINKING_STYLE_DEEPSEEK,
     "label": "off"},
    {"value": "low", "effort": "low", "style": THINKING_STYLE_DEEPSEEK,
     "label": "low"},
    {"value": "medium", "effort": "medium", "style": THINKING_STYLE_DEEPSEEK,
     "label": "medium"},
    {"value": "high", "effort": "high", "style": THINKING_STYLE_DEEPSEEK,
     "label": "high"},
)

# ---- 各家官方档位表（查证情况见每条注释；查证时间 2026-11-08：
#      · DeepSeek 已联网核实官方 api-docs.deepseek.com/api/create-chat-completion 原文；
#      · 其余各家为公开文档口径，本次无法逐条在线核实（搜索端点鉴权失败），
#        拿不准的保守退回通用 off/low/medium/high 并在注释写明）。
# ⚠️ label 用各家**官方档位名**（需求原话），前端只显示 label；value 是存设置的规范值，
#    effort 是发给 API 的值，三者大多同名但含义分开（如 OpenAI 的 minimal）。
_LEVELS_DEEPSEEK = (
    # 官方文档（已核实）：reasoning_effort ∈ none/low/high/max，默认 high；
    # thinking{type: enabled/disabled} 独立控制开关。minimal 官方映射 low、
    # medium/xhigh 官方映射 high —— 所以真实档位就是 low/high/max 三档，max 官方确有。
    _lvl("off", "off", None, THINKING_STYLE_DEEPSEEK),
    _lvl("low", "low", "low", THINKING_STYLE_DEEPSEEK),
    _lvl("high", "high", "high", THINKING_STYLE_DEEPSEEK),
    _lvl("max", "max", "max", THINKING_STYLE_DEEPSEEK),
)
_LEVELS_OPENAI = (
    # 官方文档口径（未联网核实）：reasoning_effort ∈ minimal/low/medium/high；
    # gpt-5 系列 Responses API 另有 "none" 表示完全关思考（Chat Completions 老版本
    # 不认 none，中转不认时上层有"400 去参重试"兜底）。
    _lvl("off", "off", None, THINKING_STYLE_EFFORT),
    _lvl("minimal", "minimal", "minimal", THINKING_STYLE_EFFORT),
    _lvl("low", "low", "low", THINKING_STYLE_EFFORT),
    _lvl("medium", "medium", "medium", THINKING_STYLE_EFFORT),
    _lvl("high", "high", "high", THINKING_STYLE_EFFORT),
)
_LEVELS_CLAUDE = (
    # 官方无语义档位名，只有 budget_tokens（1024 ≤ N < max_tokens）。
    # 低/中/高 = 4096/8192/16384 预算是本程序约定的映射（注释即依据，非官方名称）。
    _lvl("off", "off", None, THINKING_STYLE_ANTHROPIC),
    _lvl("low", "low", "low", THINKING_STYLE_ANTHROPIC, budget=4096),
    _lvl("medium", "medium", "medium", THINKING_STYLE_ANTHROPIC, budget=8192),
    _lvl("high", "high", "high", THINKING_STYLE_ANTHROPIC, budget=16384),
)
_LEVELS_GEMINI = (
    # 官方文档口径（未联网核实）：2.5 系列 thinkingConfig 用 thinking_budget
    # （-1 动态 / 0 关），新命名档位 thinking_level ∈ low/high（部分模型）。
    # 这里发 thinking_level；预算制旧模型收到未知字段一般忽略，不会 400。
    _lvl("off", "off", None, THINKING_STYLE_GEMINI),
    _lvl("low", "low", "low", THINKING_STYLE_GEMINI),
    _lvl("high", "high", "high", THINKING_STYLE_GEMINI),
)
_LEVELS_KIMI_EFFORT = (
    # ⚠️⚠️ 已联网核实（2026-11-08，https://platform.kimi.ai/docs/guide/use-reasoning-effort
    #    与 …/use-thinking-models 官方原文）：
    #    kimi-k3.1-pro / kimi-k3 思考**恒开、不支持关**，顶层 `reasoning_effort`
    #    ∈ "low"/"high"/"max"（默认 max）。**官方没有 off 这一档** ——
    #    所以这张表的第一档是 low，不是 off（前端滑块必须按数组长度动态分段，
    #    不能假设第一档=关；见 ai-frontend 侧同步改动）。
    #    旧表把 Kimi 统一画成 off/on 是错的：k3 收到 thinking{type:disabled} 会直接报错。
    _lvl("low", "low", "low", THINKING_STYLE_EFFORT),
    _lvl("high", "high", "high", THINKING_STYLE_EFFORT),
    _lvl("max", "max", "max", THINKING_STYLE_EFFORT),
)
_LEVELS_KIMI_ALWAYS_ON = (
    # kimi-k2.7-code（含 highspeed 变体）：官方原文「thinking is always on」且
    # **不支持 reasoning_effort**，传 thinking{type:"disabled"} 官方明确报错。
    # → 只有一档、不可调：滑块画成禁用态显示 "on"；请求体**什么都不发**
    #   （effort=None + style=always：见 client._thinking_params 的 always 分支，
    #    多发一个被官方拒绝的参数 = 整条请求 400，宁可不表态）。
    _lvl("on", "on", None, THINKING_STYLE_ALWAYS, effort_supported=False),
)
_LEVELS_KIMI_TOGGLE = (
    # kimi-k2.6：官方 `thinking:{type:"enabled"/"disabled"}`（默认 enabled），
    # 无强度参数 → off/on 两档。label 用官方语义（on/off），规范值沿用 "medium"
    # （旧配置里布尔 True 归一成 medium，保持兼容）。
    _lvl("off", "off", None, THINKING_STYLE_TOGGLE),
    _lvl("medium", "on", "medium", THINKING_STYLE_TOGGLE),
)
_LEVELS_TOGGLE = (
    # Kimi（Moonshot）官方口径（未联网核实）：thinking:{type: enabled/disabled}
    # **只有开关没有强度档位**（文档未公开 effort 参数）。label 用官方叫法 on，
    # 规范值取 medium —— 与旧配置（布尔 True 归一成 medium）和旧调用完全兼容，
    # 前端下拉选中存的也是这个 value。
    _lvl("off", "off", None, THINKING_STYLE_TOGGLE),
    _lvl("medium", "on", "medium", THINKING_STYLE_TOGGLE),
)
_LEVELS_QWEN = (
    # 阿里云百炼官方口径（未联网核实）：enable_thinking 布尔 + thinking_budget
    # （token 数），**无档位名**。同样 label 用 on、规范值 medium（理由同上）。
    _lvl("off", "off", None, THINKING_STYLE_QWEN),
    _lvl("medium", "on", "medium", THINKING_STYLE_QWEN),
)
_LEVELS_GROK = (
    # xAI 官方口径（未联网核实）：grok-3/4 系列 reasoning_effort ∈ low/medium/high
    #（无 minimal）。off 也按 effort 风格发 reasoning_effort:"none" —— 端点不认时
    # 上层 ai.py 有"400 去参重试"兜底（最差这档没表态，等价于关）。
    _lvl("off", "off", None, THINKING_STYLE_EFFORT),
    _lvl("low", "low", "low", THINKING_STYLE_EFFORT),
    _lvl("medium", "medium", "medium", THINKING_STYLE_EFFORT),
    _lvl("high", "high", "high", THINKING_STYLE_EFFORT),
)

# 模型名前缀 → 档位表。⚠️ 顺序敏感（先匹配更长更专门的键）；
# 命中规则与 _THINKING_PREFIXES 同源：只按**模型名尾段**（去掉 "厂商/" 路由前缀）匹配。
_THINKING_TABLES = (
    ("deepseek-v4", _LEVELS_DEEPSEEK),
    ("deepseek-flash", _LEVELS_DEEPSEEK),
    ("deepseek-reasoner", _LEVELS_DEEPSEEK),
    ("gpt-5", _LEVELS_OPENAI),
    ("o1", _LEVELS_OPENAI), ("o3", _LEVELS_OPENAI), ("o4", _LEVELS_OPENAI),
    ("claude-sonnet-4", _LEVELS_CLAUDE), ("claude-opus", _LEVELS_CLAUDE),
    ("claude-haiku-4", _LEVELS_CLAUDE),
    ("gemini-2", _LEVELS_GEMINI),
    ("grok-3", _LEVELS_GROK), ("grok-4", _LEVELS_GROK),
    # ⚠️ Kimi 按**模型**细分（官方核实 2026-11-08，见 _LEVELS_KIMI_* 三张表的注释）：
    #    顺序敏感 —— k3.1-pro / k3 / k2.7-code 都要比通用前缀先匹配。
    ("kimi-k3.1-pro", _LEVELS_KIMI_EFFORT),
    ("kimi-k3", _LEVELS_KIMI_EFFORT),
    ("kimi-k2.7-code", _LEVELS_KIMI_ALWAYS_ON),
    ("kimi-k2.6", _LEVELS_KIMI_TOGGLE),
    ("kimi-k2", _LEVELS_KIMI_TOGGLE), ("moonshot", _LEVELS_KIMI_TOGGLE),
    ("qwen3", _LEVELS_QWEN), ("qwq", _LEVELS_QWEN),
)


def thinking_style_of(provider_id: str, name: str) -> str:
    """这个模型走哪种请求体风格（认不出 → 通用 deepseek 风格：
    reasoning_effort 是 OpenAI 兼容网关的事实标准，thinking{type} 兜显式关闭）"""
    table = thinking_table(provider_id, name)
    if table:
        return table[0]["style"]
    return THINKING_STYLE_DEEPSEEK


def thinking_table(provider_id: str, name: str):
    """按「服务商 + 模型名前缀」取官方档位表；认不出返回 None（调用方退回通用表）"""
    pid = str(provider_id or "").strip().lower()
    raw = str(name or "").strip().lower()
    tail = raw.rsplit("/", 1)[-1]
    # 服务商兜底（模型名认不出时按服务商给最接近的一张）
    if not tail:
        return None
    for prefix, table in _THINKING_TABLES:
        if tail.startswith(prefix):
            return table
    if pid == "siliconflow" and tail.startswith("deepseek"):
        return _LEVELS_DEEPSEEK
    return None



def normalize_thinking(value) -> str:
    """把任意来源的思考设置归一成档位字符串（off/low/medium/high）

    ⚠️ 必须兼容**旧配置**：上一轮的 `ai_thinking` 存的是布尔 True/False，
       用户配置里现在就是 False。布尔直接当档位用会掉进"认不出来 → 不表态"，
       思考关不掉（推理模型服务端默认开着，就会又开始吐思考内容）。
       · False → "off"；True → "medium"（老版本"开"没有强度概念，取中间档）；
       · "1"/"true"/"开"/"开启" → medium；"0"/"false"/"关"/"关闭" → off；
       · 认不出来 → "off"（宁可关着，也不能把思考混进回答）。
    """
    if value is True:
        return "medium"
    if value is False or value is None:
        return THINKING_OFF
    text = str(value).strip().lower()
    if text in ("", "none", "off", "false", "0", "关", "关闭", "不开启"):
        return THINKING_OFF
    if text in ("1", "true", "on", "开", "开启", "enabled"):
        return "medium"
    if text in ("minimal",):
        # ⚠️ 本轮：OpenAI 官方有独立的 minimal 档，不能再被折成 low
        #    （老版本把它归 low 是因为当时全局表没有 minimal 这一档）。
        return "minimal"
    if text in ("low", "低", "低强度"):
        return "low"
    if text in ("medium", "mid", "中", "中强度"):
        return "medium"
    if text in ("high", "高", "高强度"):
        return "high"
    if text in ("max", "极限", "最高"):
        # ⚠️ 本轮：DeepSeek 官方档位里 max 是**独立一档**（reasoning_effort=max），
        #    不再兼容映射成 high；老配置里被写成 "max" 的落到这里也是同一语义。
        return "max"
    return THINKING_OFF


# 用户存的档位不在当前模型档位表里时的映射（切模型后档位取"最接近的一档"，
# 需求："选择不同模型下面的思考也会默认跟随对应模型变化"——但用户手动选过档位时
# 不该直接丢掉，所以按语义就近取，取不到才回落 off）。
_LEVEL_FALLBACKS = {
    "minimal": "low",
    "low": "medium",        # 没有 low 的表多半有 medium
    "medium": "high",       # DeepSeek 风格没有 medium：官方就把 medium 兼容映射到 high
    "high": "medium",       # Gemini 风格只有 low/high：high 缺时退 medium 也缺 → off
    "max": "high",
    "on": "medium",
}


def resolve_thinking_level(provider_id: str = "", name: str = "", value=None) -> str:
    """把设置里的档位**修正成当前模型档位表里真实存在的 value**

    ⚠️ 为什么需要：档位表现在是各家专属（DeepSeek 有 max 没 medium、OpenAI 有
       minimal、Kimi/Qwen 只有 on…）。用户从 deepseek-v4 的 "max" 切到 gemini，
       请求里就会出现该模型没有的档位；这里统一就近映射，界面上的选中值也随之修正。

    ⚠️⚠️ 本轮新增（官方核实 kimi-k3 后）：**有的表根本没有 off 这一档**
       （k3 系思考恒开只有 low/high/max；k2.7-code 恒开无档）。
       旧写法 `level==off → 直接返回 off` 会让 off 落到表外，
       上层再照 off 去查行 → 查不到 → 发错参数。现在：
       表里没有 off 时，off 就近落**表内第一档**（k3 → low，最小强度；
       这是官方允许的最小值，也是"用户想少花思考 token"最接近的语义）。
    """
    level = normalize_thinking(value)
    table = thinking_levels(provider_id, name)
    values = [row.get("value") for row in table]
    if level == THINKING_OFF:
        # 表里有 off（绝大多数模型）：就按关处理。
        if THINKING_OFF in values or not values:
            return THINKING_OFF
        # 表里没有 off = 官方"思考恒开"：退回表内最低档，绝不返回表外值。
        return str(values[0])
    if level in values:
        return level
    seen = set()
    current = level
    while current and current not in seen:
        seen.add(current)
        current = _LEVEL_FALLBACKS.get(current)
        if current and current in values:
            return current
    # 就近映射也找不到的表（只有 off 一档 = 模型不支持思考）：
    # 发送路径本来就该"不表态"，这里返回 off 由上层按不支持处理。
    return THINKING_OFF


def thinking_levels(provider_id: str = "", name: str = "") -> list:
    """这个模型能选哪些思考档位（界面滑块的档位表 + client 发请求的映射）

    · 不支持思考的模型 → 只有 off 一档（前端据此**不画滑块**，画了也没用）；
    · 支持 → **按各家官方 API 的真实档位名和档数**（见 _THINKING_TABLES 与
      thinking_table 的注释）；认不出家族时保守退回通用 off/low/medium/high。
    ⚠️ 每项恒带 value/label/effort 三个键（前端契约），另带 style（client 用来
       决定请求体字段），前端原样回传即可。
    ⚠️ 返回的是**新列表**（每项是新 dict），调用方改了不会污染常量表。
    """
    if not model_supports_thinking(provider_id, name):
        return [dict(THINKING_LEVELS[0])]
    table = thinking_table(provider_id, name) or THINKING_LEVELS
    return [dict(level) for level in table]



def model_catalog(provider_id: str) -> list:
    """该服务商的模型清单（带思考能力），给输入框右下角的模型切换 UI 用

    返回 `[{"name": 显示名, "api_model": 发给 API 的名字, "thinking": 能不能思考,
            "thinking_levels": [档位表]}, ...]`。
    ⚠️ 顺序照 PROVIDERS 里的原顺序（第一个是默认项），**不要**在这里排序：
       设置页/切换 UI 都按这个顺序显示，排了序会和设置页对不上。
    ⚠️ `thinking_levels` 本轮新增：思考从布尔开关改成多档强度后，前端要按这张表画滑块，
       不支持思考的模型只给 off 一档（前端据此不画滑块）。
    """
    pid = str(provider_id or "").strip()
    out = []
    for name in models_of(pid):
        out.append({
            "name": name,
            "api_model": resolve_api_model(pid, name),
            "thinking": model_supports_thinking(pid, name),
            "thinking_levels": thinking_levels(pid, name),
        })
    return out


def model_catalog_all() -> list:
    """全部服务商的模型清单（分组），给模型切换 UI 一次取全

    返回 `[{"provider": id, "label": 显示名, "api_base": ..., "models": [...]}, ...]`。
    ⚠️ 这里**不**按 Key 过滤（Key 状态只有 desktop/api 那层拿得到）：
       "未填 Key 的服务商不显示"由 `desktop/api/ai.py` 的 `model_choices()` 负责，
       免得业务层去猜加密槽位怎么读。
    """
    groups = []
    for provider in PROVIDERS:
        pid = provider["id"]
        models = model_catalog(pid)
        if not models and pid != PROVIDER_CUSTOM:
            # 自定义服务商没有内置模型清单（用户自己填名字），单独一组也没东西可选
            continue
        groups.append({
            "provider": pid,
            "label": provider_display(pid),
            "api_base": provider.get("api_base") or "",
            "models": models,
        })
    return groups
