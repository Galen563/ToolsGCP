"""GCP-AI 的系统提示词与资源库上下文。
AI 没法访问本地文件、也没联网，唯一能"知道我们库里有 LocalSend"的办法是把资源清单
放进上下文：系统提示词 + 资源清单（按需压缩）+ 最近的对话历史。
    messages = build_messages(session, resources, language,
                              context_rounds=0, keyword="局域网传文件")
本轮新增（需求 1/2/3/6）：`meta` 运行时元信息段 —— 模型身份、当前时间、回复语言、
思考档位、可用能力清单。模型的自我认知和时间感知**不可靠**（训练语料里的说法会过期、
它也没有时钟），唯一正确的做法是每次构建请求时把真实值写进 system，并明确告诉它
"被问到就按这段答"。
"""

import re
from datetime import datetime

from ..resource_loader import resolve_i18n
from .. import resource_schema

# 清单里每条资源的简介截断长度（太长的话 48 条就能把上下文吃满）
DESC_MAX = 60
# 全量模式（want_all）下的简介截断：52 条量级很小，放宽到能看清"它能干什么"即可
FULL_DESC_MAX = 120
# 没有关键词时，最多塞多少条进上下文
CATALOG_MAX = 120
# 有关键词时，最多给多少条（命中通常很少，给多点也不怕）
CATALOG_MAX_FILTERED = 40
# 全量模式的条目数阈值：超过它才退回关键词挑选（token 预算是限制原因时保底）
FULL_CATALOG_LIMIT = 400

# ---------- 回复模式（设置里的回复模式三选一） ----------
# 模型默认爱写小作文（大标题、分点、表格、附代码），所以把"写多长"抽成可切换的模式。
MODE_STANDARD = "standard"
MODE_CONCISE = "concise"
MODE_PROFESSIONAL = "professional"

DEFAULT_REPLY_MODE = MODE_STANDARD

# 每种模式的额外要求，会拼在 BASE_PROMPT 后面（越靠后模型越容易遵守）
MODE_PROMPTS = {
    MODE_CONCISE: """
【回答长度要求：简洁】
· 最多 4 行，能一句话说完就一句话。
· 只给结论：资源名称 + 它干什么 + 一个链接。不要分类、标签、优缺点、对比、总结。
· 不要标题、不要编号列表、不要表格、不要分隔线。
· 最多推荐 2 个。用户追问了再展开。
""",
    MODE_STANDARD: """
【回答长度要求：标准】
· 控制在 6 行以内，重点在前两行。
· 找到资源就按这个格式写（不要加多余的话）：
    推荐：名称 —— 一句话它能干什么
    官网：完整链接（没有就写 GitHub 链接）
    备选：再给一个同类的名称 —— 一句话（没有就省略这行）
· 不要标题、不要编号列表、不要表格、不要总结段落。
· 最多推荐 2~3 个，多了等于没推荐。
""",
    MODE_PROFESSIONAL: """
【回答长度要求：专业】
· 可以写 10 行左右，但必须**先给结论**，再给依据；能用一句话说清的就不要展开。
· 结构固定为：推荐（名称 + 一句话定位）→ 官网 / GitHub 链接 → 关键差异（2~3 条，每条一行）
  → 备选（1~2 个）。
· 只说对"选哪个"有用的信息：适用场景、体积/性能、是否开源、有无中文界面这类维度。
  不要写安装步骤、不要写使用教程、不要复述简介。
· 每条一行，不要长段落。
""",
}

# 所有模式都必须遵守的硬要求
# ⚠️⚠️ 「列举全部资源」的例外段（本轮修复用户反馈「列举所有资源bug还存在，还是会遗漏
#    一大部分」的真根因）：
#    模式段里那三句"最多 4 行 / 6 行 / 10 行、最多推荐 2~3 个"是给**推荐类**问题
#    （"我要一个能传文件的工具"）写的。用户问"列举所有资源 / 资源库有哪些"时，
#    模型严格照模式段执行 → 就算上下文里给了完整的 52 条清单，它也只挑 2~3 条输出，
#    看起来就是"遗漏一大部分/随机给我一两条"。清单再全也救不了，这是**输出指令**
#    与用户意图直接冲突。
#    所以在硬要求里显式声明优先级：**列举类请求不受长度模式约束**。
EXHAUSTIVE_RULE = """
【列举类请求的例外（优先级高于上面的长度模式）】
· 用户要你"列举/列出所有/全部/有哪些/多少个"资源时：**上面的行数与条数上限一律不生效**。
· 必须把【资源库清单】里的条目**逐条、按编号完整列完**（编号 1 到 N 一条不落），
  每条格式：`编号. 名称 —— 一句话简介（编码）`。
· 结尾另起一行写 `共 N 条`，N 必须等于清单里给出的总数；对不上就是漏了，回去补全。
· 绝不允许"以下是一些示例""等等""仅列举部分"这类偷懒说法，也不允许只列你觉得好的几条。
· 清单里没有的资源不要补；清单被截断时按提示说明"共 N 条，这里先列前 M 条"。
"""

HARD_RULES = """
【硬性要求（任何模式下都适用）】
· **绝对不要输出代码**，包括代码块、命令、脚本、配置片段、JSON、正则。用户看的是
  "该用哪个软件"，不是来读代码的。
· 不要用 Markdown 表格、不要用 | 画表、不要用 ### 标题、不要用分隔线。
· 不要复述用户的问题，不要写"好的""希望这对你有帮助"这类客套话。
· 不确定的就说不确定；资源库里没有的就直说没有，不要编造名称、编码或链接。
· 给出链接时必须是完整的 http(s) 地址，不要写成"官网"两个字让用户自己找。
· 回答语言一律按下面【输出语言】那一条执行（默认跟随用户提问的语言）。
"""

# 模型角色定位 + 内置知识（写得克制一点：多一段它回答时就多想展开一点）
BASE_PROMPT = """你是 GCP-AI，内嵌在 Windows 工具箱软件 ToolsGCP 里的助手。

ToolsGCP 维护着一份"程序 / 网站索引"（资源库），每条都直达官网或官方 GitHub，
主要功能有：搜索与筛选资源、收藏夹、把常用软件整理成部署清单、插件扩展、资源制作器。

【你的首要任务】
用户描述"想要一个能做某事的软件 / 网站"时，先在下面给你的【资源库清单】里找匹配的条目
（按名称、分类、标签、简介判断，不要只认字面完全一致的词）。找到就告诉他叫什么、
一句话能干什么、去哪下载。清单里没有就直说"资源库暂未收录"，再简单给个建议。

【@ 提到某条资源】
用户在界面上可以点资源卡片的「@给AI」，输入框里就会出现这种文本：

    @LocalSend(TG-000001)

含义是"我说的就是资源库里的这一条"（括号里是它的资源编码，可能没有）。
遇到 @ 时：
· 直接按**那一条**回答，不要另找别的资源；
· 编码能对上清单里的某一行 → 就用那一行的信息；对不上就按名称找；
· 用户追问（比如"它支持哪些系统""和另一个比怎么样"）时，仍然以这条资源为中心。
· 如果清单里根本没有这个名字，就说"资源库里没有这条"，不要编。

【你可以让回答里的某些文字变成"可点击的链接"】
界面上有四种写法会被渲染成蓝色下划线、用户点下去有真实动作。**要不要用、用在哪，
完全由你自己判断**（用户说"这里点一下能跳过去会更方便"时才用），不是所有提到
资源的地方都该加链接：

    @名称(TG-000024)     ← 点它 → 打开这条资源的详情页（最常用）
    TG-000024            ← 只写编码，同样可点、同样跳详情
    设置<API Key>        ← 点它 → 跳到 设置 → GCP-AI 那一栏

规则：
· 只有**资源库里真的存在**的名字/编码才能这么写；对不上就写普通文字，别硬凑。
· 一次回答里最多给 1~2 个链接，给多了就没有重点了；纯聊天、讲概念、
  说模型名/参数名时**不要**加链接（"我用的是 deepseek-v4.1-flash 模型"
  这种就正常写文字，不要写成链接）。
· 用户没配 API Key / Key 报错这类情况，可以在需要他去做设置的地方写一次
  设置<API Key>，让他点一下就能过去填。
· 不要把上面这三种写法用在**不是资源**的东西上（网站 URL、文件名、按钮名都不是）。
"""

# 资源清单段落的标题
CATALOG_HEADER = "\n【资源库清单】（每行一条，用 ｜ 分隔字段；这是你唯一能看到的资源信息）\n"

# 全量清单标题的固定前缀（build_system_message 用它判断"清单已自带标题，别再叠一层"）
# ⚠️ 开头保持【资源库清单】字样：BASE_PROMPT 里让模型"在下面给你的【资源库清单】里找"，
#    两处标题对不上会让它以为这不是它该用的那份清单。
FULL_TITLE_PREFIX = "【资源库清单"

# 全量模式的标题（带总数 + 硬性要求"逐条列完"，需求 5）
FULL_CATALOG_HEADER = ("\n【资源库清单 · 完整版】共 {total} 条，按分类分组、全局连续编号；"
                       "这是你唯一能看到的资源信息。\n"
                       "⚠️ 被要求列举全部资源时必须逐条列完 {total} 条，不能只给示例、"
                       "不能只说一两条、不能随机挑。\n")

# 资源清单为空时的说明
EMPTY_CATALOG_HINT = "（当前资源库清单为空：可能是资源文件缺失或还没加载成功。）"

# ==========================================================================
# 回复语言（需求 3：新增设置项 ai_reply_language）
# ==========================================================================
# 用户明确要求"提示词简短有力"，所以每种语言就一句、用【】打头放在 system 靠后位置
# （越靠后模型越容易遵守，同 MODE_PROMPTS 的理由）。
REPLY_LANG_AUTO = "auto"
REPLY_LANG_RULES = {
    "auto": "\n【输出语言】一律使用与用户最新消息相同的语言，包括思考过程(reasoning)与最终回答；不得夹杂其它语言。\n",
    "zh_CN": "\n【输出语言】一律使用简体中文，包括思考过程(reasoning)与最终回答；不得夹杂其它语言。\n",
    "zh_TW": "\n【输出语言】一律使用繁體中文，包括思考過程(reasoning)與最終回答；不得夾雜其它語言。\n",
    "en": "\n【输出语言】ALWAYS reply in English, including your reasoning and the final answer. Never mix other languages.\n",
}
# 语言显示名（设置页下拉与元信息段共用；三语文案 key 同值兜底）
REPLY_LANG_LABELS = {
    "auto": "跟随输入语言",
    "zh_CN": "简体中文",
    "zh_TW": "繁體中文",
    "en": "English",
}


def language_rule(reply_language: str) -> str:
    """强制输出语言的那一句话（认不出的值按 auto 处理）"""
    key = str(reply_language or "").strip()
    return REPLY_LANG_RULES.get(key, REPLY_LANG_RULES[REPLY_LANG_AUTO])


def language_label(reply_language: str) -> str:
    key = str(reply_language or "").strip()
    if key not in REPLY_LANG_RULES:
        key = REPLY_LANG_AUTO
    return REPLY_LANG_LABELS[key]


def reply_language_choices() -> list:
    """设置页「回复语言」下拉的数据源：[{"value","label"}...]（前端要画下拉，需求 3）。
    ⚠️ label 优先取当前界面语言的语言包（settings 分组 ai_reply_lang_* 三语 key），
       拿不到用内置中文兜底；value 永远是存进设置的规范值，不随界面语言变。
    """
    out = []
    for value in ("auto", "zh_CN", "zh_TW", "en"):
        out.append({"value": value,
                    "label": _localized(f"ai_reply_lang_{value}",
                                        REPLY_LANG_LABELS[value])})
    return out


def _localized(key: str, fallback: str) -> str:
    """从语言包 settings 分组取一条文案（与 providers._localized 同口径；拿不到用兜底）"""
    try:
        from ..language_manager import get_current_manager
        manager = get_current_manager()
        if manager is not None:
            text = manager.get_text("settings", key)
            if text and text != key:
                return str(text)
    except Exception:                                     # noqa: BLE001
        pass
    return fallback


# ==========================================================================
# 「列举所有资源」意图判定（需求 5）
# ==========================================================================
# 三语关键词表：命中任何一条 → 全量清单进上下文（而不是关键词挑选的一小截）。
# ⚠️ 为什么宁可误判成全量也不漏判：52 条的清单全量给也只多花几百 token，
#    而"AI 只知道一部分"是用户点名要修的行为缺陷（漏一条比多给 50 条严重得多）。
_WANT_ALL_WORDS = (
    # 简体中文
    "所有", "全部", "每一个", "每个", "列举", "列出所有", "清单", "多少个",
    "都有什么", "有哪些", "多少种", "全量", "挨个", "逐条", "资源库有",
    # 繁體中文
    "每一條", "每條", "羅列", "清單", "多少個", "都有哪些", "有多少", "全量",
    # English（小写匹配）
    "how many", "list all", "all resources", "every resource", "enumerate",
    "full list", "what resources", "show me all", "all of the",
)


def wants_all_resources(text: str) -> bool:
    """这句话是不是在要求"列举/全部资源"（三语，大小写不敏感）"""
    raw = str(text or "").strip().lower()
    if not raw:
        return False
    return any(word in raw for word in _WANT_ALL_WORDS)


# ==========================================================================
# 运行时元信息（需求 1 / 2 / 6：模型身份、当前时间、能力清单）
# ==========================================================================
_WEEKDAY_ZH = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")

META_HEADER = "\n【运行时元信息（本段由程序在构建上下文时实时生成，以本段为准）】\n"

META_RULES = (
    "· 被问到「你是什么模型 / 什么服务商 / 思考开没开 / 现在几点 / 你能做什么」时，\n"
    "  直接按上面这段如实回答，不要说不确定，也不要凭训练记忆回答 ——\n"
    "  你对自身型号和当前时间的内置知识**不可靠**，只有这段是现场算出来的。\n"
    "· 显示名与实际调用名不同时（服务商中转/路由），两个都说清楚。\n"
    "· 上面的能力清单是当前真实开启的：清单外的能力不要编，没有就说没有。\n"
)


def current_time_text(now=None) -> str:
    """「当前时间」一行：每次构建请求时实时计算（系统本地时区）。
    ⚠️ 模型没有时钟，被问"今天几号/现在几点"必然瞎编；唯一解法是每次拼真实值。
    用 datetime.now().astimezone() 而不是 naive now：能同时拿到时区名和 UTC 偏移。
    """
    try:
        dt = now if now is not None else datetime.now().astimezone()
        offset = dt.utcoffset()
        if offset is not None:
            total = int(offset.total_seconds())
            sign = "+" if total >= 0 else "-"
            hh, mm = divmod(abs(total), 3600)
            offset_text = f"UTC{sign}{hh:02d}:{mm // 60:02d}"
        else:
            offset_text = "UTC?"
        try:
            # dt.tzname() 是系统本地时区名（Windows 中文系统上是"中国标准时间"这类）；
            # 拿不到就只用 UTC 偏移顶上，不强求 IANA 名（本机时区反查不可靠）。
            tz_name = dt.tzname() or ""
        except Exception:                                 # noqa: BLE001
            tz_name = ""
        tz_text = f"{tz_name} / {offset_text}" if tz_name else offset_text
        weekday = _WEEKDAY_ZH[dt.weekday()]
        return (f"当前时间：{dt.strftime('%Y-%m-%d %H:%M:%S')}"
                f"（{weekday}，时区 {tz_text}，本地时间）")
    except Exception:                                     # noqa: BLE001
        # 极端兜底：时间算不出来也不能把整条元信息段搞崩（主链路优先）
        return "当前时间：未知（系统时间读取失败）"


def build_runtime_meta(provider_label: str = "", display_model: str = "",
                       api_model: str = "", reply_language: str = "auto",
                       thinking_text: str = "", features_text: str = "",
                       models_text: str = "", plugins_text: str = "",
                       now=None) -> str:
    """拼「运行时元信息」段（需求 1+2+6 共用的一段，缺哪项就不写哪项，绝不抛）。

    参数都由调用方（desktop/api/ai.py）现算现传：
      provider_label/display_model/api_model —— 模型身份（需求 1）
      reply_language —— 回复语言设置（需求 3，详细强指令在 language_rule）
      thinking_text —— 当前思考档位（含各家官方档位名，需求 4）
      features_text/models_text/plugins_text —— 能力清单（需求 6）
    """
    lines = [META_HEADER.rstrip("\n")]
    if provider_label:
        lines.append(f"· 当前服务商：{provider_label}")
    if display_model:
        lines.append(f"· 用户所选模型（显示名）：{display_model}")
    if api_model:
        if display_model and api_model != display_model:
            lines.append(f"· 实际发给 API 的模型名：{api_model}"
                         f"（与显示名不同：由服务商中转/路由所致，回答时以两个名字说明）")
        else:
            lines.append(f"· 实际发给 API 的模型名：{api_model}")
    lines.append(f"· 回复语言：{language_label(reply_language)}"
                 f"（用户设定，见下方【输出语言】指令）")
    if thinking_text:
        lines.append(f"· 当前思考档位：{thinking_text}")
    lines.append(current_time_text(now))
    lines.append("  （该时间是**本次会话构建上下文时**的实时值；被问到时间以此为准，"
                 "不要说不确定。用户要更精确的当前时间时，说明以系统时间为准即可。）")
    if models_text:
        lines.append(f"· 可用（已配 API Key）的服务商与模型：{models_text}")
    if features_text:
        lines.append(f"· 已启用的功能：{features_text}")
    if plugins_text:
        lines.append(f"· 已启用插件：{plugins_text}")
    lines.append(META_RULES.rstrip("\n"))
    return "\n".join(lines) + "\n"


# ==========================================================================
# 产品边界：用户协议 / 隐私政策（正文在 .ToolsGCP/legal/*.txt，不写进代码）
# ==========================================================================
# ⚠️⚠️ 本轮改动（用户原话）：「我之前写了每次对话开始都给AI植入2份我这个程序的用户协议
#   和隐私政策等，导致大量文本消耗太多token问题。现在我决定 AI 可以主动找到这个协议
#   不是必须发送的文本提示词，但是要让 AI 知道这个的存在，提示词限制下不要让 AI 阅读
#   这个文本，只是告诉他有这个东西，如果必要时允许查阅的」
#   → 以前每次请求把两份全文（约 5200 字）塞进 system，现在只塞**条号目录**（约 370 字），
#     每条消息净省 ~4800 字符 ≈ 3000+ token。
#   → 为什么留目录而不是干脆不提：目录里的条标题（"第三方软件的风险承担与责任切割"
#     "禁止性行为"这类）本身就够模型判断"这个请求触边界、需要查原文"，
#     同时它也知道去哪查、怎么引 —— 去掉全文没有去掉判断力，只去掉了 token。
LEGAL_HEADER = "\n【ToolsGCP 用户协议与隐私政策 · 条款目录】（只有条号和标题，正文未加载）\n"

LEGAL_RULES = """
【产品边界（重要）】
ToolsGCP 有两份现行文件：《ToolsGCP 用户协议》和《ToolsGCP 隐私政策及免责声明》。
它们的**全文不在这里**（为了不把上下文撑爆），下面只给你条号目录。按以下规则使用：

1. 用户的要求如果明显越过 ToolsGCP 的边界（例如：要求你协助传播恶意软件、侵犯知识产权、
   实施网络攻击、未经授权访问他人系统、规避技术保护措施、要求你为第三方软件的安全性
   或合法性作保证、要求你承诺第三方软件不含病毒、要求你对第三方产品承担责任等），
   不要照做。先用一句话明确说明"这个请求触及了协议边界，我不能按这个方式做"。
2. 引用依据时**只引用目录里真实存在的条号**（例如「《ToolsGCP 用户协议》第三条」），
   可以说出那条的标题。**绝对不要编造条款原文、编造更细的款号（如 3.2）或臆造内容** ——
   你手里只有目录，没有正文。
3. 需要引用具体条文内容才能说清楚时，**不要凭印象复述**，按下面两种情况处理：
   · 如果你这次能用文件读取类工具（例如 read_file）：直接读
     `.ToolsGCP/legal/` 下对应的那份 txt（用户协议 = `ToolsGCP_User Agreement.txt`，
     隐私政策 = `ToolsGCP_Privacy Policy and Disclaimer.txt`），**只读相关条款**、
     读完据原文引用 —— 这就是"必要时允许查阅"的正解；
   · 如果这次没有文件读取能力（GCP-AI Agent 没开）：如实告诉用户
     「这两份文件在程序目录的 `.ToolsGCP/legal/` 下，可以打开查看具体条款」，
     或者请他把相关条款内容贴给你，你再据原文回答。
   两种情况都**不许**假装读过、不许编造原文。
4. 说明"触发了什么"：用户这句话里哪个动作/目的触发了该条款（一句话，别展开说教）。
5. 最后给出**合规的替代做法**：在协议允许的范围内，你能帮他做什么（例如把需求改成
   检索合法资源、解释原理、建议使用安全软件检测、提示备份数据等）。
6. 语气克制、就事论事，不要道德说教、不要长篇大论（3~5 行为宜）。
7. 协议里没有涉及的事情，不要拿它来限制用户；你也不是律师，不要给出法律意见。
"""

# 两份协议都没读到时，只在 system 里保留一句兜底说明（提示词仍然要有边界意识）
LEGAL_MISSING_HINT = """
【产品边界】
本次没有加载到《用户协议》《隐私政策及免责声明》的全文（文件缺失或被移动）。
如果用户的要求明显涉及违法、侵权、恶意软件、攻击他人系统或侵犯隐私，仍然要拒绝，
并说明这属于 ToolsGCP 不允许的用途；不要编造具体条款号。
"""


def mode_prompt(mode: str) -> str:
    """取某个模式对应的提示词段落（认不出的值用默认模式）"""
    return MODE_PROMPTS.get(str(mode or ""), MODE_PROMPTS[DEFAULT_REPLY_MODE])



def _pick(value, language: str) -> str:
    """取多语言字段的当前语言值（资源库里的 name/description 允许写成多语言字典）"""
    resolved = resolve_i18n(value, language)
    return str(resolved or "").strip()


def _pick_list(value, language: str) -> str:
    """取"列表字段"的展示文本（如 category 是列表）
    ⚠️ 不能直接 `_pick(list)`：`str(["工具"])` 是 `"['工具']"`，模型会照着它去搜带方括号的分类。
    """
    return "/".join(resource_schema.as_text_list(value, language))


def _resource_line(item: dict, language: str, desc_max: int = DESC_MAX,
                   index=None) -> str:
    """把一条资源压成一行清单文本（用 ｜ 分隔而不是换行，省 token）
    desc_max：全量模式放宽截断（需求 5），挑选模式沿用旧 60。
    index：全量模式下的全局编号（配合分组输出，AI 数得清"一共多少条"）。"""
    name = _pick(item.get("name"), language) or str(item.get("id") or "")
    parts = [f"{index}｜{name}" if index is not None else name]

    code = str(item.get("code") or "").strip()
    if code:
        parts.append(code)

    category = _pick_list(item.get("category"), language)
    if category:
        parts.append(f"分类：{category}")

    tags = item.get("tags") or []
    tag_text = "/".join(_pick(t, language) for t in tags if _pick(t, language))
    if tag_text:
        parts.append(f"标签：{tag_text}")

    desc = _pick(item.get("description"), language)
    if desc:
        if len(desc) > desc_max:
            desc = desc[:desc_max] + "…"
        parts.append(desc)

    # ⚠️ 编码和标识排在名称/分类之后的旧顺序保持不变会让模型对不上 @ 的写法，
    #    标识（id）也要写出来：没有 code 的资源，卡片上的 @ 塞进输入框的就是 id
    #    （见 AppCard.resource_code），不写它模型就对不上"@ 的这一条是哪条"。
    rid = str(item.get("id") or "").strip()
    if rid and rid != code:
        parts.append(f"标识：{rid}")

    for label, field in (("官网", "url"), ("GitHub", "github")):
        url = str(item.get(field) or "").strip()
        if url:
            parts.append(f"{label}：{url}")

    return "｜".join(parts)


def _find_by_code_or_id(items: list, keyword: str):
    """关键词就是资源编码 / id 时，把那条精确找出来并排在最前面
    ⚠️ 这是"@ 给 AI 却说这条不存在"的根因之一：extract_keyword() 返回的是编码，而编码
    不在 haystack 里，筛选会退回全量清单，一旦被截断那条就不在里面。
    """
    needle = str(keyword or "").strip().upper()
    if not needle:
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("code") or "").strip().upper() == needle:
            return item
        if str(item.get("id") or "").strip().upper() == needle:
            return item
    return None


def build_resource_catalog(resources, language: str = "简体中文",
                           keyword: str = "", want_all: bool = False) -> str:
    """把资源库压成一段可供模型阅读的清单。

    ⚠️⚠️ 需求 5 的核心修复："列举所有只给一两条 / 随机"的根因是按关键词挑资源，
       命中就只把挑出来的塞进上下文 → AI 只知道一部分。策略改为**优先给全量**：
         ① 条目数 ≤ FULL_CATALOG_LIMIT（400）→ **一律完整清单**（按分类分组、全局
            连续编号、简介截断放宽、带"必须逐条列完 N 条"的硬要求）。52 条量级每条
            一行成本很低，全量给才是正确取舍；@ 提到的条目本来也在这份完整清单里，
            不存在"挑丢某条"的问题。
         ② 条目数 > 阈值（token 预算真的是限制）→ 退回关键词挑选，但 want_all 时
            给满预算并明确告诉模型"必须调 list_all_resources 补齐"，不许凭半截清单
            编造或只给示例。
    keyword 可以是空格分隔的多个关键词（一次 @ 好几条时就是一串编码），命中即算。
    ⚠️ 筛选是"宽进"：命中率低也宁可多给几条，但绝不能一条不给。
    """
    items = [r for r in (resources or []) if isinstance(r, dict)]
    if not items:
        return EMPTY_CATALOG_HINT

    # ---------- ① 优先全量（需求 5） ----------
    if len(items) <= FULL_CATALOG_LIMIT:
        return _full_catalog(items, language)

    # ---------- ② 超大库：才退回关键词挑选 ----------
    keyword = str(keyword or "").strip().lower()
    if keyword:
        parts = [p for p in keyword.split() if p]
        # ① 先看有没有**精确命中编码 / id** 的（一次 @ 多条时就是几个编码）
        pinned = []
        for part in parts:
            found = _find_by_code_or_id(items, part)
            if found is not None and found not in pinned:
                pinned.append(found)
        if pinned:
            # ② 精确命中的排最前，"整串包含"的相关条目补在后面
            #    ⚠️ 只做整串包含、不做"拆词滑动窗口"：窗口里的 "00" 会命中 TG-000099 之类的无关条目。
            related = [r for r in items
                       if any(part in _haystack(r, language) for part in parts)]
            items = pinned + [r for r in related if r not in pinned]
            limit = CATALOG_MAX_FILTERED
        else:
            # 没有编码/id：整体走宽松匹配（名称 / 分类 / 标签 / 简介）
            matched = _match_by_keyword(items, keyword, language)
            if matched:
                items = matched
                limit = CATALOG_MAX_FILTERED
            else:
                # 一个都没命中：退回尽量多给，让模型自己判断（它比字符串匹配聪明）
                limit = CATALOG_MAX
    else:
        limit = CATALOG_MAX

    lines = [_resource_line(item, language) for item in items[:limit]]
    total = len(items)
    if total > limit:
        if want_all:
            # ⚠️ 用户明确要"全部"但清单装不下：明说只给了前 M 条 + 必须调工具补齐，
            #    否则模型会拿这半截清单当全集，"列举所有"就永远少一条。
            lines.append(f"（资源库共 {total} 条，受上下文长度限制这里只列了前 {limit} 条。"
                         f"用户要的是**全部**：必须调用 list_all_resources 用 offset 翻页"
                         f"取满 {total} 条后再作答，绝不能只列这几条或凭这半截编造。）")
        else:
            lines.append(f"（清单过长，这里只列了前 {limit} 条，共 {total} 条。）")
    return "\n".join(lines)


def _full_catalog(items: list, language: str) -> str:
    """全量清单：按分类分组、全局连续编号、每条一行 `编号｜名称｜编码｜简介｜分类`。
    （需求 5：被要求列举全部时必须能逐条数完 N 条。）"""
    # 分组：一条资源可能有多个类别，归入**第一个**类别（避免重复计数导致
    # "总数对不上"——用户拿编号核过：AI 报 52 条却列出 60 行就是重复归类造成的）
    groups = {}
    order = []
    for item in items:
        cats = _pick_list(item.get("category"), language) or "未分类"
        first = cats.split("/")[0]
        if first not in groups:
            groups[first] = []
            order.append(first)
        groups[first].append(item)

    out = []
    index = 0
    for cat in order:
        members = groups[cat]
        out.append(f"— {cat}（{len(members)} 条）")
        for item in members:
            index += 1
            out.append(_resource_line(item, language,
                                      desc_max=FULL_DESC_MAX, index=index))
    header = FULL_CATALOG_HEADER.replace("{total}", str(index))
    return header + "\n".join(out)



def _haystack(item: dict, language: str) -> str:
    """一条资源可用于匹配的文本（名称/关键词/简介 + 编码/id，转小写）
    关键词 = 类别 ∪ 标签（resource_schema.keywords_of），tags 去重后必须显式带类别。
    ⚠️ 编码和 id 也要进去：extract_keyword() 对 `@名称(TG-000001)` 返回的就是编码，
    不算进来的话"拆词匹配"也匹配不上，表现为"@ 了某条资源，AI 说库里没有"。
    """
    return " ".join((
        _pick(item.get("name"), language),
        " ".join(resource_schema.keywords_of(item, language)),
        _pick(item.get("description"), language),
        str(item.get("code") or ""),
        str(item.get("id") or ""),
    )).lower()


# 参与匹配的"词"最少要有几个字符
# ⚠️ extract_keyword 提出的中文串是连着的（"局域网传文件"），要拆成片段才能匹配；
# 但单字片段会让一个"传"字命中 OBS 简介里的"直播推流"，所以中文/英文/数字片段都至少 2 个。
MIN_TOKEN_LEN = 2


def _keyword_tokens(phrase: str) -> set:
    """把关键词拆成可匹配的片段：整串 + 按空白切 + 长片段的"2 字滑动窗口"
    （中文没词间空格，滑动窗口是不用分词库也能凑出子词的办法）"""
    tokens = set()
    for chunk in str(phrase or "").split():
        if len(chunk) >= MIN_TOKEN_LEN:
            tokens.add(chunk)
        if len(chunk) > 4:
            tokens.update(chunk[i:i + 2] for i in range(len(chunk) - 1))
    return {t for t in tokens if len(t) >= MIN_TOKEN_LEN}


def _match_by_keyword(items: list, keyword: str, language: str) -> list:
    """按关键词挑相关资源：整串命中 → 拆片段命中 → 都没有则返回空，由调用方退回全量清单"""
    phrase = str(keyword or "").strip().lower()
    if not phrase:
        return []

    exact = [item for item in items if phrase in _haystack(item, language)]
    if exact:
        return exact

    tokens = _keyword_tokens(phrase)
    if not tokens:
        return []

    return [item for item in items
            if any(token in _haystack(item, language) for token in tokens)]


def build_legal_section() -> str:
    """产品边界那一节 = 规则 + **条号目录**（本轮起不再注入正文）。

    ⚠️ 正文**绝不写进代码**（用户要求协议文本只存在于 .ToolsGCP/legal/*.txt，
       改条款只改文本、不用改代码）；
    ⚠️ 也**绝不注入正文**（本轮需求：每次对话塞两份全文太费 token）——
       这里只做"读目录 + 包一层规则"，全文留在磁盘上由用户自行查阅。
    ⚠️ 目录读不到（文件缺失/格式不认）时的兜底**不能提条号**：
       一个条号都没见过还去引用，必然是编造，所以退回 LEGAL_MISSING_HINT
       那段"仍然要拒绝，但不要编造具体条款号"。
    """
    try:
        from . import legal
        index = legal.build_legal_index()
    except Exception:                                     # noqa: BLE001
        index = ""
    if not index:
        return LEGAL_MISSING_HINT
    return LEGAL_RULES + LEGAL_HEADER + index + "\n"


def build_system_message(resources, language: str = "简体中文",
                         keyword: str = "", mode: str = DEFAULT_REPLY_MODE,
                         meta: str = "", want_all: bool = False,
                         reply_language: str = "auto") -> str:
    """拼出完整的 system 消息
    顺序：运行时元信息 → 角色定位 → 资源清单 → 产品边界（协议全文）→ 输出语言
          → 硬性要求 → 模式要求
    （模型对靠近末尾的指令遵守得最好，所以"怎么回答"放最后；元信息放最前是身份锚点，
      输出语言紧贴硬性要求，保证它压过模型"跟着用户语言走"的默认倾向。）
    meta：build_runtime_meta() 的结果（需求 1/2/6），空串 = 不放这一段。
    want_all：需求 5，见 build_resource_catalog。
    reply_language：需求 3 设置项 ai_reply_language（auto/zh_CN/zh_TW/en）。
    """
    catalog = build_resource_catalog(resources, language, keyword, want_all)
    # 全量模式生成的文本自带 FULL_CATALOG_HEADER（含总数与逐条要求），不再叠 CATALOG_HEADER
    if catalog.lstrip("\n").startswith(FULL_TITLE_PREFIX):
        body = catalog
    else:
        body = CATALOG_HEADER + catalog
    prefix = meta if meta else ""
    return (prefix + BASE_PROMPT + body
            + "\n" + build_legal_section()
            + language_rule(reply_language)
            + "\n" + HARD_RULES
            # ⚠️ 列举类例外**紧贴模式段之前**：模型对越靠后的指令遵守越好，而模式段
            #    （"最多 4/6/10 行、最多推荐 2~3 个"）正是"列举只给一两条"的直接来源，
            #    例外必须压在它上面、且在它之后出现，才能稳定翻掉那条限制。
            + (EXHAUSTIVE_RULE if want_all else "")
            + mode_prompt(mode))


def build_messages(session_messages, resources, language: str = "简体中文",
                   context_rounds: int = 0, keyword: str = "",
                   mode: str = DEFAULT_REPLY_MODE, meta: str = "",
                   want_all: bool = False,
                   reply_language: str = "auto") -> list:
    """组装最终发给 API 的 messages
    context_rounds：0 = 整个会话全发；10/20/30 = 只发最近 N 轮。
    meta / want_all / reply_language：需求 1/2/3/5/6，见 build_system_message。
    ⚠️ system 永远第一条且只有一条；裁剪后要把开头多余的 assistant 丢掉，保证第一条是 user。
    """
    history = [m for m in (session_messages or [])
               if isinstance(m, dict) and m.get("role") in ("user", "assistant")
               and not m.get("error")          # 报错气泡只留在历史里，不进上下文
               and str(m.get("content") or "").strip()]

    rounds = int(context_rounds or 0)
    if rounds > 0:
        # 从后往前数 rounds 个 user 消息，从它开始截
        user_indexes = [i for i, m in enumerate(history) if m["role"] == "user"]
        if len(user_indexes) > rounds:
            history = history[user_indexes[-rounds]:]

    # 保证第一条是 user（见上面第 2 个坑）
    while history and history[0]["role"] != "user":
        history.pop(0)

    messages = [{"role": "system",
                 "content": build_system_message(resources, language, keyword, mode,
                                                 meta=meta, want_all=want_all,
                                                 reply_language=reply_language)}]
    messages.extend({"role": m["role"], "content": str(m["content"])} for m in history)
    return messages


def extract_keyword(text: str) -> str:
    """从用户这句话里抠出可用于筛资源的关键词
    去掉"我想要/帮我找/有没有"这类意图词，剩下最长的中文/英文片段就是候选。
    ⚠️ @ 提到的资源优先当关键词，且一次可以 @ 多条：必须把所有提及的编码/id 都收集起来
    （以前只取第一个，@ 了 7 条时其余全被答"不在资源库清单里"）。
    """
    raw = str(text or "").strip()
    if not raw:
        return ""

    codes = []
    names = []
    for mention in re.finditer(r"@([^()\s@]{1,60})(?:\(([^)]{1,60})\))?", raw):
        # 名称里可能带空格（"OBS Studio"），@OBS Studio 这种写法取不到，所以只取到
        # 第一个空格为止；编码（TG-000001）命中率更高，优先用它。
        code = (mention.group(2) or "").strip()
        name = (mention.group(1) or "").strip()
        key = code or name
        if key and key not in codes:
            codes.append(key)
        if name and name not in names:
            names.append(name)
    if codes:
        # 编码排前面（精确），名称兜底（没写编码时用名字匹配）
        return " ".join(codes + names)

    stop_words = (
        "我想要", "我要", "我想", "帮我", "找个", "找一个", "找一款", "推荐", "有没有",
        "求推荐", "介绍", "一下", "一个", "什么", "软件", "工具", "网站", "程序",
        "能", "可以", "用来", "做", "干啥", "功能", "的",
    )
    cleaned = raw
    for word in stop_words:
        cleaned = cleaned.replace(word, " ")
    # 只留下中文、字母、数字（标点和语气词对匹配没帮助）
    kept = []
    for ch in cleaned:
        if ch.isalnum() or ch == " ":
            kept.append(ch)
        else:
            kept.append(" ")
    words = [w for w in "".join(kept).split() if len(w) >= 2]
    words.sort(key=len, reverse=True)
    return " ".join(words[:3])
