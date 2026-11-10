"""GCP-AI 的「消息版本树」（用户编辑版本 + AI 重新生成版本 + 各自的下游分支）。

===========================================================================
为什么是这个结构（而不是每条消息挂一棵 children 树）
===========================================================================
`session.messages` **永远就是当前显示的那一条线**（扁平列表，下标即顺序），
版本信息作为**可选字段**挂在消息本身上，跟着会话一起落盘：

    用户消息  {role:"user", content, ts,
               variants: ["1", "2"],        # 每个编辑版本的文本
               variant_index: 1,            # 当前显示第几版（默认 = 最后一版）
               branch_suffixes: [ [AI回复...], [AI回复...] ] }
                                          # 第 k 项 = 第 k 个编辑版本**后面挂着的那串消息**
    AI 消息   {role:"assistant", content, ts,
               variants: ["11", "22"], variant_index: 1,
               branch_suffixes: [ None, [用户下一条, AI下一条, ...] ] }
                                          # 第 k 项 = 第 k 个回答版本**后面挂着的那串消息**

两类消息的 branch_suffixes 语义**完全对称**，都是「第 k 版后面挂着的那串下游消息」：
  · 用户把 "1" 编辑成 "2" → 11/22 整串存进 user.branch_suffixes[0]（属于版本 "1"），
    版本 "2" 的后继从空开始；切回版本 "1" 时把那一格放回来即可。
  · AI 把中间的 "11" 重新生成成 "11b" → **它下面那串对话**（用户接下来问的、AI 答的、
    再往下的一切，含各自的多版本）整串存进 assistant.branch_suffixes[0]（属于版本 "11"），
    新版 "11b" 的后继从空开始；翻回旧版时把那一格放回来。
⚠️⚠️ 缺了 AI 这一半，就是用户报的「点击中间的 AI 重新生成，下面所有内容属于所有版了、
   全都不消失」：旧版本的下游没有让位，几个版本的后继同时显示在同一条线上。

⚠️⚠️ 上下文绝不能混兄弟版本：因为切分支时 `messages[index+1:]` 会**整段**换成目标版本
   的后继，`session.messages` 本身就等于「当前选中的那一版 + 该版本下当前选中的下游」
   这一条线，所以 `prompt.build_messages(session.messages, ...)` 拿到的天然就是干净的一条线，
   不需要（也**不许**）在那里再猜版本。这是本模块存在的唯一理由，改这里前先想清楚。

===========================================================================
向后兼容（老会话文件没有这些字段）
===========================================================================
`normalize_messages()` 把缺字段的老实消息当成「只有 v1」：
`variants=[content]`、`variant_index=0`、两类消息都补 `branch_suffixes=[None]`。
`content` 永远**镜像**当前选中那一版的正文，所以任何旧代码（只读 content 的历史面板、
预览摘要、PyQt 版共用的读写路径）都不会因为多了这几个字段而读坏。
老文件里如果 `content` 和 `variants` 对不上（旧版"编辑后发送"只改 content 没同步 variants 的
坏数据），`normalize_messages()` 会把正文补成版本表的最后一版并指过去，避免一翻页跳回旧内容。
⚠️ 老会话里 AI 消息的 `branch_suffixes` 补出来**全是 None**（= "这一版从没存过后继"）。
   翻到这种版本时后继就是**空**，`restore_branch_suffix` 只认那一格的值 —— 绝不能
   "目标没有就沿用当前的后继"，那正是让所有版本的后继混在一起、用户报的那个 bug。
"""

import copy

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"

VARIANTS_KEY = "variants"
INDEX_KEY = "variant_index"
BRANCH_KEY = "branch_suffixes"
# 与 variants **等长**的错误标记表：第 k 项 = 第 k 版是不是报错气泡。
# 为什么要单独一张表而不是一条消息上的一个 error：重新生成时"上一次失败、这次成功"会落在
# 同一条消息的不同版本上，只用消息级的 error 就没法表达"这一版是红的、那一版不红"
# （用户翻回旧版看到的应该是当初那条红色报错）。老会话文件没这个字段 → 视为全 False，
# 消息级 error 仍照旧生效（向后兼容）。
ERRORS_KEY = "variant_error"
# 与 variants **等长**的思考文本表：第 k 项 = 第 k 版回答的推理过程（reasoning_content）。
# ⚠️ 为什么要单独一张表，而不是把思考拼进 content：
#   用户报「我也没有思考按钮，但是为什么 AI 会输出带有思考内容的句子」——
#   根因就是老代码在 content 为空时拿 reasoning_content 顶成正文，自言自语的
#   「用户问…我应该…」直接进了气泡、还跟着落盘（历史会话文件里能翻到实例）。
#   现在思考与正文**两条数据**：正文永远只有 content，思考只活在这张表里，
#   界面上是 DeepSeek 网页版那种可展开/收起的折叠块，且只有开了「思考」才有内容。
# 老会话文件没有这张表 → 视为"全都没有思考"（不新增键，避免把用户历史文件写胖）。
REASONINGS_KEY = "variant_reasoning"


def _log(action: str, **fields):
    try:
        from ...utils.logger import log
        log.op("AI", action, **fields)
    except Exception:
        pass


# ---------------------------------------------------------------- 归一化 / 读取
def _clean_variants(message: dict) -> list:
    """把 message["variants"] 收成字符串表（丢弃非字符串项，保证顺序）"""
    stored = message.get(VARIANTS_KEY)
    if not isinstance(stored, list):
        return []
    return [str(v or "") for v in stored]


def _clean_errors(message: dict, count: int) -> list:
    """取"每一版是不是报错"的布尔表（与 variants 等长；缺位补 False）"""
    stored = message.get(ERRORS_KEY)
    errors = [bool(v) for v in stored] if isinstance(stored, list) else []
    if not errors:
        errors = [bool(message.get("error"))]
    errors = errors[:count]
    while len(errors) < count:
        errors.append(False)
    return errors


def _has_reasonings(message: dict) -> bool:
    """这条消息**有没有**思考表（老会话文件没有 →  False，绝不凭空补键）"""
    return isinstance(message.get(REASONINGS_KEY), list)


def _clean_reasonings(message: dict, count: int) -> list:
    """取"每一版的思考文本"表（与 variants 等长；缺位补空串）

    ⚠️ 只在调用方**已经确认**这条消息有思考表时才用（见 _has_reasonings）：
       没有这张表的老消息补出来全是空串，写回去只会把用户历史文件平白写胖。
    """
    stored = message.get(REASONINGS_KEY)
    think = [str(v or "") for v in stored] if isinstance(stored, list) else []
    think = think[:count]
    while len(think) < count:
        think.append("")
    return think


def normalize_messages(messages: list, repair: bool = True) -> int:
    """就地补齐整棵版本树的字段（幂等），返回**修过几条**（>0 时调用方应当落盘）。

    为什么要主动扫一遍而不是读的时候惰性修：刚从磁盘载入历史时，界面要立刻知道
    「这条消息有几个版本」才能决定要不要画 `◀ 2/3 ▶`；惰性修会让首屏少画导航。

    `repair=False` 用于只读预览（比如历史列表算摘要）：不去动用户的数据。
    """
    if not isinstance(messages, list):
        return 0
    fixed = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        before = _snapshot(message)
        _normalize_one(message, repair)
        if _snapshot(message) != before:
            fixed += 1
    return fixed


def _snapshot(message: dict) -> tuple:
    """用于比较"这条有没有被改过"：只关心版本三件套和正文镜像"""
    return (
        str(message.get("content") or ""),
        tuple(_clean_variants(message)),
        message.get(INDEX_KEY),
        len(message[BRANCH_KEY]) if isinstance(message.get(BRANCH_KEY), list) else None,
    )


def _normalize_one(message: dict, repair: bool) -> None:
    variants = _clean_variants(message)
    current = str(message.get("content") or "")
    role = str(message.get("role") or "")

    appended_current = False
    if not variants:
        variants = [current]
    elif repair and current and current not in variants:
        # 老版坏数据：正文不在版本表里（旧版"编辑后发送"只改 content、没同步 variants）。
        # ⚠️ 必须把正文**追加成最新那一版**并把页码指过去，绝不能反过来用 variants[0]
        #    覆盖 content —— 那样用户上一次编辑的内容就等于被程序悄悄丢掉了。
        variants.append(current)
        appended_current = True

    if message.get(INDEX_KEY) is None and variants:
        # 默认显示**最后一版**（新生成的、刚编辑完的那一条必须在最前），
        # 且 variant_index 缺失时按"最后一版"补，而不是老实地当 0。
        index = len(variants) - 1
    elif appended_current:
        index = len(variants) - 1
    else:
        index = _clamp_index(message.get(INDEX_KEY), len(variants))
    if repair:
        message[INDEX_KEY] = index
        message["content"] = variants[index] if variants else ""
    message[VARIANTS_KEY] = variants

    # 报错表：与版本表等长；老消息没有这张表 → 用消息级的 error 当"唯一那一版"的标记，
    # 于是老会话读进来仍然是"这条是报错气泡"。
    errors = message.get(ERRORS_KEY)
    errors = [bool(v) for v in errors] if isinstance(errors, list) else []
    if not errors:
        errors = [bool(message.get("error"))]
    errors = errors[:len(variants)]
    while len(errors) < len(variants):
        errors.append(False)
    message[ERRORS_KEY] = errors
    if repair and role == ROLE_ASSISTANT:
        # 消息级 error 永远镜像"当前选中那一版"（老代码 + 上下文组装只认消息级那个字段）；
        # 用户消息没有报错气泡的概念，不给它凭空加键。
        message["error"] = bool(errors[index]) if errors else False

    # 思考表：**只对已经有这张表的消息**做对齐/镜像（老会话文件绝不凭空补键，见上面注释）。
    # 表里每一格 = 对应那一版回答的思考文本；消息级 reasoning 镜像当前选中那一版。
    if role == ROLE_ASSISTANT and _has_reasonings(message):
        think = _clean_reasonings(message, len(variants))
        if repair:
            message[REASONINGS_KEY] = think
            message["reasoning"] = think[index] if index < len(think) else ""
        else:
            message.setdefault(REASONINGS_KEY, think)

    if _is_branchable(role):
        # 分支表 = 「每一版后面挂着的那串下游消息」，user / assistant **两类消息都要有**
        # （只给 user 是上一轮的缺口：AI 重新生成时旧版本的下游无处可存，只能混着显示）。
        branches = message.get(BRANCH_KEY)
        branches = list(branches) if isinstance(branches, list) else []
        # 分支表必须和版本表**等长**：多的截掉（版本被删过），少的补 None（新版本还没有后继）
        branches = branches[:len(variants)]
        while len(branches) < len(variants):
            branches.append(None)
        if repair:
            message[BRANCH_KEY] = branches
        else:
            message.setdefault(BRANCH_KEY, branches)


def _clamp_index(value, count: int) -> int:
    """把存储的页码钳进 [0, count-1]：坏数据（超范围/非整数）都退回最后一版"""
    try:
        index = int(value)
    except (TypeError, ValueError):
        return max(0, count - 1)
    if count <= 0:
        return 0
    if index < 0:
        return 0
    if index >= count:
        return count - 1
    return index


# ---------------------------------------------------------------- 只读查询
def variant_count(message) -> int:
    if not isinstance(message, dict):
        return 1
    return max(1, len(_clean_variants(message)))


def active_variant(message) -> int:
    if not isinstance(message, dict):
        return 0
    return _clamp_index(message.get(INDEX_KEY), variant_count(message))


def has_navigation(message) -> bool:
    """要不要画 `◀ n/m ▶`：只有一版时不显示导航（用户明确要求）"""
    return variant_count(message) > 1


# ---------------------------------------------------------------- AI 重新生成
def append_variant(message: dict, content: str, error: bool = False,
                   reasoning: str = "", allow_duplicate: bool = False) -> int:
    """给一条消息追加新版本（重新生成的结果 / 用户编辑确认），返回新版本的页码。

    ⚠️ 这里**只补齐、不重置**版本表：无条件写 `variants=[当前正文]` 会把已有版本
       整个冲掉（用户翻不到之前那几版，py 版踩过这个坑）。
    ⚠️ 正文与已有版本重复时不新增条目，只把页码指过去（避免"看起来多了个一模一样的版本"）。
       ⚠️⚠️ 例外 = `allow_duplicate=True`（用户原话本轮报的：「点击编辑内容不编辑内容
          直接点对勾按钮结果版本树ui不增加」）：
          **用户主动点确认**是一次明确的"重新问一遍"动作，语义上就该多一个版本 ——
          即使原文没改。旧的去重把这条路径也吞掉了，界面上看就是"点了没反应"。
          而且这不浪费：重问会拿到**一条新的回答**（那条才是真正的新内容）。
          AI 回答那一路（line ~340/346、desktop/api/ai.py 的 _persist_assistant）
          **不传**这个参数，保持原有去重 —— 那边"同一版正文重复落盘"确实不该长版本。
    ⚠️ `error`：这一版是不是**报错气泡**（请求失败落的盘）。必须按版本记 ——
       "上一次失败、这次重新生成成功"落在同一条消息的两个版本上，只用消息级 error
       就表达不了"这版红、那版不红"（翻回旧版应该还是红色报错）。
    ⚠️ `reasoning`：这一版的**思考文本**（与正文分开存进 REASONINGS_KEY 表）。
       空串 = 这一版没有思考（用户没开思考按钮时就是空串，界面上不画折叠块）。
       ⚠️ 只有非空、或这条消息**本来就有**思考表时才建表 —— 老会话文件不会因为
       "这次没思考"被平白加一个空表键。
    ⚠️ 只在**内存里**给这一条追加版本，不会碰它下面的消息：真正的"旧下游让位"由
       `regenerate_variant()` 负责（先存 branch_suffixes 再删尾部）。
    """
    normalize_messages([message])
    variants = _clean_variants(message)
    errors = _clean_errors(message, len(variants))
    text = str(content or "")
    think = str(reasoning or "")
    had_table = _has_reasonings(message)
    if text in variants and not allow_duplicate:
        index = variants.index(text)
    else:
        variants.append(text)
        errors.append(False)
        index = len(variants) - 1
    errors[index] = bool(error)
    message[VARIANTS_KEY] = variants
    message[ERRORS_KEY] = errors
    message[INDEX_KEY] = index
    message["content"] = text
    # 思考表：有东西可存（这次的思考非空）或这条消息已经有表 → 对齐并写这一格
    if think or had_table:
        thinks = _clean_reasonings(message, len(variants))
        # ⚠️ 这次的思考为空时**不覆盖已有值**：去重路径（正文和某一版一模一样）会走到这里，
        #    把用户曾经存下的思考清空等于丢历史 —— 宁可留着旧思考，也不要写坏。
        if think or not thinks[index]:
            thinks[index] = think
        message[REASONINGS_KEY] = thinks
        message["reasoning"] = thinks[index]
    role = str(message.get("role") or "")
    # ⚠️ error 只给 assistant 消息写：用户消息根本没有"报错气泡"这一说，
    #    给它塞 error:False 只是往会话文件里添噪声（老文件里也没有这个键）。
    if role == ROLE_ASSISTANT:
        message["error"] = bool(error)
    if _is_branchable(role):
        # 版本表变长后分支表跟着对齐：新版本的那一格补 None（= "还没有后继"）。
        # ⚠️ 只补 None，**绝不复制上一格** —— 复制就等于把旧版本的下游错挂到新版本上，
        #    又变成"所有版本混在一起"。
        _align_branches(message)
    return index


# ---------------------------------------------------------------- 切版本 / 切分支
def regenerate_variant(messages: list, index: int, content: str,
                       error: bool = False, reasoning: str = "") -> int:
    """AI 重新生成：给第 index 条回答**追加一个新版本**，并让它下面的旧下游整段让位。

    ⚠️⚠️ 顺序不能换（和 apply_user_edit 同一条教训）：
      ① **先存后取**：把当前这一版的下游（`messages[index+1:]`）深拷贝存进
         `branch_suffixes[当前页码]`。旧的那串后续对话不能删，用户翻回旧版还得看见它
         （含那串消息各自的多版本）。
      ② 再给这条回答追加新版本（正文 / 版本表 / 报错表 / 思考表 / 页码），新版本的分支格子是 None。
      ③ 最后 `del messages[index+1:]`：新版本的后继从空开始。
    反过来的话第 ① 步存到的就是"已经被删空的尾巴"，旧下游整段丢失。

    ⚠️ 模型这次吐的正文如果和**已有的某一版**一模一样（append_variant 会去重，不新增条目）：
      · 与当前版相同 → 这条线什么都没变，刚存好的后继**原样留着**（绝不能清空，
        否则用户点一次重新生成、界面上的后续对话就凭空消失）；
      · 与更早的某一版相同 → 等价于翻到那一版：目标版本存过后继就放出来，
        没存过（None）就是**空后继**（绝不复制当前的，否则又是"所有版本混在一起"）。
    """
    message = _at(messages, index)
    if message is None or str(message.get("role") or "") != ROLE_ASSISTANT:
        return -1
    normalize_messages([message])
    variants = _clean_variants(message)
    text = str(content or "")
    current = active_variant(message)

    save_branch_suffix(messages, index, current)          # ① 旧下游先存好（深拷贝）
    if text in variants:
        target = variants.index(text)
        # 去重：只更新这一版的正文镜像/报错/思考（这次带思考就覆盖那一格的思考，不带就保留旧的）
        append_variant(message, content, error=error, reasoning=reasoning)
        if target == current:
            return current                                # 这条线没变，后继保持原样
        restore_branch_suffix(messages, index, target)    # ③ 目标版本的后继（None = 空）
        return target

    new_index = append_variant(message, content, error=error,
                               reasoning=reasoning)       # ② 新版本 + 页码 + 正文
    branches = message.get(BRANCH_KEY)
    if isinstance(branches, list) and 0 <= new_index < len(branches):
        branches[new_index] = None                        #    新版本格子显式置空
        message[BRANCH_KEY] = branches
    del messages[index + 1:]                              # ③ 新版本的后继从空开始
    return new_index


def set_ai_variant(messages: list, index: int, target: int) -> bool:
    """AI 气泡翻页 = 换一条回答的版本，**连同它下面那串下游消息整段一起换**。

    ⚠️ 和用户气泡的 switch_user_branch 是同一套语义、同样"先存后取"三步：
       ① 先把当前这一版的下游存进 branch_suffixes[当前版]；
       ② 换正文 + 页码（报错标记跟着镜像）；
       ③ 再放出目标版本那一格（None / 没存过 = 空后继，绝不沿用当前的后继）。
    只换这一条、不动后继，就是用户报的"重新生成后下面的内容属于所有版、全都不消失"。
    返回 False 表示无事可做（页码相同 / 越界 / 不是 AI 消息），调用方不该重绘。
    """
    message = _at(messages, index)
    if message is None or str(message.get("role") or "") != ROLE_ASSISTANT:
        return False
    normalize_messages([message])
    variants = _clean_variants(message)
    if not (0 <= int(target) < len(variants)):
        return False
    current = active_variant(message)
    if target == current:
        return False

    save_branch_suffix(messages, index, current)          # ① 先把当前这支存好
    message[INDEX_KEY] = int(target)                      # ② 换页码 + 正文
    message["content"] = variants[int(target)]
    # 报错标记也要跟着翻页镜像：翻回"当初失败那一版"就画红色，翻到成功那版就不画
    message["error"] = bool(_clean_errors(message, len(variants))[int(target)])
    # 思考同样按版本镜像（翻到哪一版就显示那一版的思考；那一版没思考就清空，
    # 绝不能把上一版的思考跟着翻过去 —— 和"所有版本混在一起"是同一类错误）
    if _has_reasonings(message):
        thinks = _clean_reasonings(message, len(variants))
        message[REASONINGS_KEY] = thinks
        message["reasoning"] = thinks[int(target)]
    restore_branch_suffix(messages, index, int(target))   # ③ 再放出目标那支（None = 空）
    return True


def switch_user_branch(messages: list, index: int, target: int) -> bool:
    """用户气泡翻页 = 换一个「我说的话」，**连同它下面那串 AI 回复整段一起换**。

    ⚠️⚠️ 顺序很关键：**先存后取**。反过来的话当前这一支的后继会在"取目标分支"那一步被
        整个丢掉 —— 用户切过去再切回来，就发现原来的 AI 回复不见了。
    返回 False 表示无事可做（页码相同 / 越界 / 不是用户消息），调用方不该重绘。
    """
    message = _at(messages, index)
    if message is None or str(message.get("role") or "") != ROLE_USER:
        return False
    normalize_messages([message])
    variants = _clean_variants(message)
    if not (0 <= int(target) < len(variants)):
        return False
    current = active_variant(message)
    if target == current:
        return False

    save_branch_suffix(messages, index, current)          # ① 先把当前这支存好
    message["content"] = variants[int(target)]            # ② 换正文 + 页码
    message[INDEX_KEY] = int(target)
    restore_branch_suffix(messages, index, int(target))   # ③ 再放出目标那支
    return True


def switch_variant(messages: list, index: int, target: int) -> bool:
    """操作栏上翻页的总入口（按角色分派）。

    ⚠️ 两类消息都是"整段换后继"：用户翻页换的是"这一句提问下面那串对话"，
       AI 翻页换的是"这一版回答下面那串对话"。同款先存后取，只是落点不同。
    """
    message = _at(messages, index)
    if message is None:
        return False
    role = str(message.get("role") or "")
    if role == ROLE_USER:
        return switch_user_branch(messages, index, target)
    if role == ROLE_ASSISTANT:
        return set_ai_variant(messages, index, target)
    return False


# ---------------------------------------------------------------- 编辑后重发
def apply_user_edit(messages: list, index: int, new_text: str = "") -> bool:
    """把「编辑过的用户消息」变成它的一个新版本，并从这一版重新问。

    ⚠️ 三件事顺序不能换：
      1. 先把当前这一支的后继**原样存进** branch_suffixes[当前版本]（旧回复不能删，
         用户翻回版本 1 还得看见 11/22）；
      2. 新文本追加成这条用户消息的一个新版本，页码指过去；
      3. 新版本的后继从空开始（清空 messages[index+1:]），由调用方紧接着发一次请求。
    正文 / 版本表 / 页码 / 分支表必须四样一起改：只改内存不改消息本身，
    落盘后 `_normalize_one` 会用旧表反过来覆盖正文，翻页器也不出现。
    """
    text = str(new_text or "")
    message = _at(messages, index)
    if message is None or str(message.get("role") or "") != ROLE_USER:
        return False
    normalize_messages([message])
    current = active_variant(message)
    save_branch_suffix(messages, index, current)          # ① 旧的那串回复先存好
    # ② 新版本 + 页码 + 正文
    # ⚠️ allow_duplicate=True：用户**主动点了确认**就该多一个版本，哪怕原文没改
    #    （本轮需求原话：「点击编辑内容不编辑内容直接点对勾按钮结果版本树ui不增加」）。
    #    旧写法走默认去重 → 文本相同就只把页码指回原来那一版，第 ③ 步又把下游删了，
    #    结果 = "看起来什么都没发生，但下面那串回答没了" —— 比不加版本更糟。
    append_variant(message, text, allow_duplicate=True)
    _align_branches(message)                              #    分支表跟着版本表变长
    del messages[index + 1:]                              # ③ 新分支从空开始
    return True


# ---------------------------------------------------------------- 分支存取
def save_branch_suffix(messages: list, index: int, branch_index: int) -> None:
    """把「当前这条线」在 index 之后的消息存进第 branch_index 个分支（深拷贝）。

    user / assistant 两类消息通用（分支落点都是"这一版后面的那串下游"）。
    ⚠️ 必须是深拷贝：浅拷贝的话切分支后两个分支**共享同一批 dict**，
       在一支里翻页（改 content）会把另一支的那条一起改掉 —— 用户说的"上下文混乱"。
    """
    message = _at(messages, index)
    if message is None or not _is_branchable(message.get("role")):
        return
    variants, branches = _ensure_branches(message)
    if branches is None or not (0 <= int(branch_index) < len(branches)):
        return
    branches[int(branch_index)] = copy.deepcopy(messages[index + 1:])
    message[BRANCH_KEY] = branches


def restore_branch_suffix(messages: list, index: int, branch_index: int) -> None:
    """把第 branch_index 个分支的后继放出来（替换 index 之后的全部消息）。

    ⚠️ 那一格是 None / 越界（这一版从没存过后继）时放出的是**空后继** ——
       绝不能拿当前显示的后继顶替，否则所有版本的下游又混在一起了。
    """
    message = _at(messages, index)
    if message is None or not _is_branchable(message.get("role")):
        return
    _variants, branches = _ensure_branches(message)
    suffix = None
    if branches is not None and 0 <= int(branch_index) < len(branches):
        suffix = branches[int(branch_index)]
    del messages[index + 1:]
    if isinstance(suffix, list):
        # ⚠️ 同样要深拷贝：放出来的这批消息之后会被就地翻页 / 追加分支，
        #    不能和分支表里那份共用对象。
        messages.extend(copy.deepcopy(suffix))


def sync_branches(messages: list) -> bool:
    """落盘前把每条消息「当前版本」那一格的后继刷成实时内容（user + assistant 都要）。

    为什么需要：`branch_suffixes[current]` 只在"离开这一支"时才写（见
    switch_user_branch / set_ai_variant 的先存后取），如果用户切到版本 2 后又在这支里
    重新生成出一批新回答、或在这支下面继续聊，直接落盘的话版本 2 那一格里存的还是
    **旧**后继 —— 重开程序翻回版本 2，看到的回答和当时屏幕上不一样。
    写盘前统一 sync 一次，磁盘就永远自洽。
    ⚠️ 两类消息都要刷：只刷 user 的话，AI 重新生成后"新版本这一格"永远是 None，
       重开程序翻回新版会看到空后继，而屏幕上当时明明有一串对话。
    返回是否真的改动过（调用方可据此决定要不要多存一次）。
    """
    changed = False
    if not isinstance(messages, list):
        return False
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        if not _is_branchable(message.get("role")):
            continue
        normalize_messages([message])
        target = copy.deepcopy(messages[index + 1:])
        slots = message.get(BRANCH_KEY)
        slot = active_variant(message)
        if not isinstance(slots, list) or not (0 <= slot < len(slots)):
            changed = True
            continue
        if slots[slot] != target:
            slots[slot] = target
            changed = True
    return changed


# ---------------------------------------------------------------- 内部工具
def _is_branchable(role) -> bool:
    """这条消息能不能挂「按版本存的后继」：user 与 assistant 都可以。

    ⚠️ 判据必须是"角色"而不是"有没有 branch_suffixes 这个键"：老会话里两类消息都没有
       这个键，但语义上它们**都能**挂后继（补齐后即可用）。system 之类不参与版本树。
    """
    return str(role or "") in (ROLE_USER, ROLE_ASSISTANT)


def _at(messages, index: int):
    if not isinstance(messages, list) or index is None:
        return None
    if not (0 <= int(index) < len(messages)):
        return None
    return messages[int(index)]


def _ensure_branches(message: dict):
    """取出/补齐「版本表」与「分支表」等长这一不变式，返回 (variants, branches)"""
    variants = _clean_variants(message)
    if not variants:
        variants = [str(message.get("content") or "")]
        message[VARIANTS_KEY] = variants
    branches = message.get(BRANCH_KEY)
    branches = list(branches) if isinstance(branches, list) else []
    branches = branches[:len(variants)]
    while len(branches) < len(variants):
        branches.append(None)
    message[BRANCH_KEY] = branches
    return variants, branches


def _align_branches(message: dict) -> None:
    """版本表变长 / 变短后把分支表对齐（并保证页码合法）"""
    variants, _branches = _ensure_branches(message)
    message[INDEX_KEY] = _clamp_index(message.get(INDEX_KEY), len(variants))
