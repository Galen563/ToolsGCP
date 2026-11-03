"""GCP-AI 的系统提示词与资源库上下文。
AI 没法访问本地文件、也没联网，唯一能"知道我们库里有 LocalSend"的办法是把资源清单
放进上下文：系统提示词 + 资源清单（按需压缩）+ 最近的对话历史。
    messages = build_messages(session, resources, language,
                              context_rounds=0, keyword="局域网传文件")
"""

import re

from ..resource_loader import resolve_i18n
from .. import resource_schema

# 清单里每条资源的简介截断长度（太长的话 48 条就能把上下文吃满）
DESC_MAX = 60
# 没有关键词时，最多塞多少条进上下文
CATALOG_MAX = 120
# 有关键词时，最多给多少条（命中通常很少，给多点也不怕）
CATALOG_MAX_FILTERED = 40

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
HARD_RULES = """
【硬性要求（任何模式下都适用）】
· **绝对不要输出代码**，包括代码块、命令、脚本、配置片段、JSON、正则。用户看的是
  "该用哪个软件"，不是来读代码的。
· 不要用 Markdown 表格、不要用 | 画表、不要用 ### 标题、不要用分隔线。
· 不要复述用户的问题，不要写"好的""希望这对你有帮助"这类客套话。
· 不确定的就说不确定；资源库里没有的就直说没有，不要编造名称、编码或链接。
· 给出链接时必须是完整的 http(s) 地址，不要写成"官网"两个字让用户自己找。
· 用用户提问的语言回答。
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
"""

# 资源清单段落的标题
CATALOG_HEADER = "\n【资源库清单】（每行一条，用 ｜ 分隔字段；这是你唯一能看到的资源信息）\n"

# 资源清单为空时的说明
EMPTY_CATALOG_HINT = "（当前资源库清单为空：可能是资源文件缺失或还没加载成功。）"

# ==========================================================================
# 产品边界：用户协议 / 隐私政策（正文在 .ToolsGCP/legal/*.txt，不写进代码）
# ==========================================================================
# 所以这里只放"怎么使用这两份文件"的规则；正文由 legal.build_legal_prompt() 从磁盘读取。
LEGAL_HEADER = "\n【ToolsGCP 用户协议与隐私政策全文】（解释边界时以这里的原文和条号为准）\n"

LEGAL_RULES = """
【产品边界（重要）】
下面给你的是 ToolsGCP 现行的《用户协议》和《隐私政策及免责声明》全文，它是你判断
"用户的要求能不能做"的唯一依据。按以下规则使用：

1. 用户的要求如果违反其中任何一条（例如：要求你协助传播恶意软件、侵犯知识产权、
   实施网络攻击、未经授权访问他人系统、规避技术保护措施、要求你为第三方软件的安全性
   或合法性作保证、要求你承诺第三方软件不含病毒、要求你对第三方产品承担责任等），
   不要照做。先用一句话明确说明"这个请求触及了协议边界，我不能按这个方式做"。
2. 然后**引用具体依据**：写清楚是哪份文件、第几条、条款大意（可以引用原文关键句）。
   例如「《ToolsGCP 用户协议》第 4.2 条」「《ToolsGCP 隐私政策及免责声明》第八条 8.3」。
   只引用下面文本里真实存在的条号，**不要编造条号或原文**；记不清就只说文件和大意。
3. 说明"触发了什么"：用户这句话里哪个动作/目的触发了该条款（一句话，别展开说教）。
4. 最后给出**合规的替代做法**：在协议允许的范围内，你能帮他做什么（例如把需求改成
   检索合法资源、解释原理、建议使用安全软件检测、提示备份数据等）。
5. 语气克制、就事论事，不要道德说教、不要重复引用、不要长篇大论（3~5 行为宜）。
6. 协议里没有涉及的事情，不要拿它来限制用户；你也不是律师，不要给出法律意见。
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


def _resource_line(item: dict, language: str) -> str:
    """把一条资源压成一行清单文本（用 ｜ 分隔而不是换行，省 token）"""
    name = _pick(item.get("name"), language) or str(item.get("id") or "")
    parts = [name]

    category = _pick_list(item.get("category"), language)
    if category:
        parts.append(f"分类：{category}")

    tags = item.get("tags") or []
    tag_text = "/".join(_pick(t, language) for t in tags if _pick(t, language))
    if tag_text:
        parts.append(f"标签：{tag_text}")

    desc = _pick(item.get("description"), language)
    if desc:
        if len(desc) > DESC_MAX:
            desc = desc[:DESC_MAX] + "…"
        parts.append(desc)

    code = str(item.get("code") or "").strip()
    if code:
        parts.append(f"编码：{code}")
    # ⚠️ 标识（id）也要写出来：没有 code 的资源，卡片上的 @ 塞进输入框的就是 id
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
                           keyword: str = "") -> str:
    """把资源库压成一段可供模型阅读的清单
    keyword 可以是空格分隔的多个关键词（一次 @ 好几条时就是一串编码），命中即算。
    ⚠️ 筛选是"宽进"：命中率低也宁可多给几条，但绝不能一条不给。
    """
    items = [r for r in (resources or []) if isinstance(r, dict)]
    if not items:
        return EMPTY_CATALOG_HINT

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
                # 一个都没命中：退回全量，让模型自己判断（它比字符串匹配聪明）
                limit = CATALOG_MAX
    else:
        limit = CATALOG_MAX

    lines = [_resource_line(item, language) for item in items[:limit]]
    total = len(items)
    if total > limit:
        lines.append(f"（清单过长，这里只列了前 {limit} 条，共 {total} 条。）")
    return "\n".join(lines)


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
    """从磁盘读两份协议，拼成 system 里的一节（读不到就退回一句兜底说明）
    ⚠️ 正文**绝不写进代码**：用户要求 AI 直接看到 .ToolsGCP/legal/ 下的 txt，
       改条款时只改文本。这里只做"读 + 包一层标题/规则"。
    """
    try:
        from . import legal
        body = legal.build_legal_prompt()
    except Exception:                                     # noqa: BLE001
        body = ""
    if not body:
        return LEGAL_MISSING_HINT
    return LEGAL_RULES + LEGAL_HEADER + body


def build_system_message(resources, language: str = "简体中文",
                         keyword: str = "", mode: str = DEFAULT_REPLY_MODE) -> str:
    """拼出完整的 system 消息
    顺序：角色定位 → 资源清单 → 产品边界（协议全文）→ 硬性要求 → 模式要求
    （模型对靠近末尾的指令遵守得最好，所以"怎么回答"放最后）。
    """
    catalog = build_resource_catalog(resources, language, keyword)
    return (BASE_PROMPT + CATALOG_HEADER + catalog
            + "\n" + build_legal_section()
            + "\n" + HARD_RULES + mode_prompt(mode))


def build_messages(session_messages, resources, language: str = "简体中文",
                   context_rounds: int = 0, keyword: str = "",
                   mode: str = DEFAULT_REPLY_MODE) -> list:
    """组装最终发给 API 的 messages
    context_rounds：0 = 整个会话全发；10/20/30 = 只发最近 N 轮。
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
                 "content": build_system_message(resources, language, keyword, mode)}]
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
