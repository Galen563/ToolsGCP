"""服务商配置档案（设置页「GCP-AI → 服务商卡片列表」的数据层）
================================================================
本轮设置页重构的唯一数据事实源。需求原话：

  「添加服务商，点击之后下面大列表中出现一个类似卡片ui，里面的原本是模型选择改为支持模型，
    之后模型名称和接口和API Key不变，不过下面还要有一个token限制输出ui，好了之后里面有
    测试连接和保存 没有清除按钮；保存好后这个ui会变成一个长条卡片ui在里面 左侧内部显示
    模型名称（这个自定义个）接着是一个括号里面是厂商（灰色字体），后面是x个模型（这个填写
    支持的模型数量 这个是要变量的而不是固定的），最右侧是测试连接按钮 编辑按钮 删除按钮
    （删除为红色）」

  「我需要他不变 如果期间我删除了原本选择模型厂商的apikey则选择一个更靠上的厂商的第一个模型。」

  「这个模型名称不影响真实回答和厂商调用和使用模型，你可以理解为是一个备注类似的功能
    只是一个单纯的标签，默认都是根据厂商他们的默认AI名称例如选择深度求索厂商默认模型名称为
    DeepSeek，之前的模型名称不规范不应该是带有是什么模型的例如v4.1flash或pro这种，
    现在默认统称为DeepSeek这种」

============== 三条设计决定（都写在这里，避免以后各处猜） ==============
① **数组顺序即优先级**：profiles[0] 最优先，自动作为"当前使用"。
   删掉最上面那家、或它的 API Key 被清空 → 自动落到下一家（用户确认的口径）。
   不引入额外的 "active" 字段：多一个状态就多一种"两者不一致"的 bug。
② **模型名称只是标签**：`label` 只用于界面显示（长条卡片左边那个名字），
   **不参与任何真实调用**。真实调用用 `model`（∈ `models`），由
   providers.resolve_api_model() 转成官方 API 名。
   默认 label = 厂商品牌名（DeepSeek / OpenAI / Claude…），不是具体的
   "deepseek-v4.1-flash" 这种型号名 —— 那是用户明确否掉的旧写法。
③ **API Key 不进这份数据**：仍走 `api_key_enc_<pid>` 的 DPAPI 密文分槽
   （settings_manager.get/set_api_key）。这份 profile 是明文 JSON，
   绝不能出现任何密钥材料。

============== 与旧配置的兼容 ==============
老版本只存 `ai_provider` / `model_name` / `api_base` 三个平铺键。
`load()` 发现档案为空时会用它们**合成**一条（不写盘，等下次真正保存再落盘），
这样升级后用户不用重新配一遍。
"""

import uuid

from ..constants import DEFAULT_SETTINGS

# 每条档案允许出现的字段（写盘前按这张表过滤，防止前端塞进来奇怪的东西）
# ⚠️ 本轮新增 `id`（见模块 docstring 的设计决定 ①'）：档案唯一身份，
#    同厂商多条并存时只有它能区分。
_PROFILE_FIELDS = ("id", "provider", "label", "api_base", "models", "model",
                   "limit_token", "min_token", "max_token")

# 默认输出 token 上限（没有显式配置时用它；和老的 max_token 默认值保持一致）
DEFAULT_MAX_TOKEN = 4096
DEFAULT_MIN_TOKEN = 0.5
# 上限的合理范围：太小几乎不能完整回答，太大很多网关会直接 400
MIN_MAX_TOKEN = 256
MAX_MAX_TOKEN = 32768


def _text(value) -> str:
    return str(value or "").strip()


def _as_int(value, fallback: int) -> int:
    try:
        number = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return fallback
    return max(MIN_MAX_TOKEN, min(MAX_MAX_TOKEN, number))


def _as_str_list(value) -> list:
    """把任意输入归一成去重、保序、去空白的字符串列表"""
    if isinstance(value, str):
        # 允许前端图省事传逗号/分号/换行分隔的字符串
        for sep in ("\n", "，", ",", ";", "；"):
            value = value.replace(sep, "\n")
        items = value.split("\n")
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        items = []
    out, seen = [], set()
    for item in items:
        text = _text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _as_float(value, fallback: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def new_id() -> str:
    """档案唯一 id（短 uuid）

    ⚠️⚠️ 本轮新增，修用户报的「同厂商又加一条，保存后会被直接吞了」。
       旧实现把 provider 当主键：`normalize_profiles()` 按 provider 去重 +
       `save_profile()` 按 provider 查找替换 → 第二条 DeepSeek 直接覆盖第一条。
       现在主键是 id，provider 只是"这条档案连的是哪家"的属性，
       同厂商 N 条完全合法（各自不同的地址/模型/token/Key）。
    """
    return uuid.uuid4().hex[:12]


def normalize_profile(raw: dict) -> dict:
    """把一条任意来源的档案归一成规范形状（认不出就返回空 dict）

    ⚠️ 本轮新增 `limit_token`（默认 **False**，用户原话「token限制输出默认是关闭的」）
       和 `min_token`（用户原话「还有后最小的token呢！」—— 老版本有这一项，
       卡片重构时被我漏掉了，现在补回，并且同样按服务商独立）。
       `max_token` 保持有默认值，但**只有 limit_token=True 时才会真的发给网关**。
    """
    if not isinstance(raw, dict):
        return {}
    provider = _text(raw.get("provider")).lower()
    if not provider:
        return {}
    models = _as_str_list(raw.get("models") or raw.get("supported_models"))
    # ⚠️ 本轮需求（用户原话）：「当前模型这个选项去除我不需要这个ui」。
    #    所以**实际调用哪个模型不再由用户单独选**，一律 = 支持模型列表的第一个。
    #    这里仍然读一下 raw["model"]，只为兼容已经存过该字段的老配置：
    #    它若不在列表里就插到最前面（等价于"老用户继续用他原来那个模型"），
    #    在列表里则不动顺序 —— 最终 model 永远等于 models[0]，两者不会不一致。
    legacy_model = _text(raw.get("model") or raw.get("model_name"))
    if legacy_model and legacy_model not in models:
        models.insert(0, legacy_model)
    label = _text(raw.get("label") or raw.get("alias") or raw.get("display_name"))
    out = {
        # id 缺失就补一个（老配置升级、以及"新建还没落盘"的草稿都会走到这里）
        "id": _text(raw.get("id")) or new_id(),
        "provider": provider,
        "label": label,
        "api_base": _text(raw.get("api_base") or raw.get("base_url")),
        "models": models,
        "model": (models[0] if models else ""),
        # 默认关闭（用户明确要求：「token限制输出默认是关闭的」）
        "limit_token": bool(raw.get("limit_token", False)),
        # 最小 token：老版本有这一项、卡片重构时被漏了，现在补回（按档案独立）
        "min_token": _as_float(raw.get("min_token"), DEFAULT_MIN_TOKEN),
        "max_token": _as_int(raw.get("max_token"), DEFAULT_MAX_TOKEN),
    }
    return {key: out[key] for key in _PROFILE_FIELDS}


def normalize_profiles(raw) -> list:
    """把任意输入归一成"有序、按 id 唯一"的档案数组

    ⚠️⚠️ 本轮改动（修「同厂商第二条被吞」）：去重键从 **provider 换成 id**。
       同一家厂商出现多条档案是完全合法的（用户要的就是这个），
       只有 id 重复才丢（同 id = 同一条，重复出现没有意义）。
       老配置里没有 id 的条目会在 normalize_profile 里自动补 id 并保留下来。
    """
    if not isinstance(raw, (list, tuple)):
        return []
    out, seen = [], set()
    for item in raw:
        profile = normalize_profile(item)
        if not profile or profile["id"] in seen:
            continue
        seen.add(profile["id"])
        out.append(profile)
    return out


def default_label_for(provider_id: str, providers_module=None) -> str:
    """某厂商的**默认模型名称标签** —— 用户要求是品牌简称，不是型号名。

    「选择深度求索厂商默认模型名称为 DeepSeek，之前的模型名称不规范不应该是带有是什么模型的
      例如 v4.1flash 或 pro 这种，现在默认统称为 DeepSeek」

    映射刻意做成短品牌名（和厂商标识一致），而不是把 PROVIDERS 里的
    "DeepSeek（深度求索）"整个拿来用 —— 后者带括号全称，放在长条卡片左边太长。
    认不出的厂商退回 provider_id 原样（至少不会是空字符串）。
    """
    pid = _text(provider_id).lower()
    return _BRAND_LABELS.get(pid, pid or "")


# 厂商 id → 默认模型名称标签（纯显示用；新增厂商时在这里补一行即可）
# ⚠️ 本轮改动（用户原话：「OpenAI的模型名称默认应该是ChatGPT」）：
#    openai 的品牌默认标签用 **ChatGPT**（用户认知里这一家的"产品名"），
#    不是 "OpenAI"。注意这只影响"模型名称"这个标签的默认值，
#    厂商下拉里显示的 "OpenAI (ChatGPT)" 是另一套（providers 的 label），别混。
_BRAND_LABELS = {
    "deepseek": "DeepSeek",
    "openai": "ChatGPT",
    "claude": "Claude",
    "grok": "Grok",
    "kimi": "Kimi",
    "qwen": "Qwen",
    "siliconflow": "SiliconFlow",
    "custom": "自定义",
}


def migrate_from_legacy(settings: dict, providers_module=None) -> list:
    """老配置 → 一条档案（只读，不写盘）

    老版本三个键：`ai_provider`（厂商）/ `model_name`（显示名）/ `api_base`（地址）。
    合成规则：
      · provider 取 ai_provider，缺失时用 deepseek（和旧默认一致）；
      · models 就取 model_name 那一个（老版本没有"支持模型"概念）；
      · label 优先用 model_name，但**如果是型号名就换成品牌名**
        （用户明确要求"默认统称为 DeepSeek"这种）；
      · api_base 用旧值，没有就留空（调用方会填厂商默认地址）。
    """
    if not isinstance(settings, dict):
        return []
    provider = _text(settings.get("ai_provider")).lower()
    display = _text(settings.get("model_name"))
    base = _text(settings.get("api_base"))
    if not provider and not display and not base:
        return []
    provider = provider or "deepseek"
    brand = default_label_for(provider)
    label = display or brand
    # 型号名（带版本号/dash 的）不适合当标签 → 换成品牌名
    if label and ("-" in label or "." in label):
        label = brand or label
    profile = normalize_profile({
        "provider": provider,
        "label": label,
        "api_base": base,
        "models": [display] if display else [],
        "model": display,
        # 老配置有全局的 limit_token_output / min_token / max_token 三键，
        # 合成时原样搬进这条档案（保持用户升级前的行为不变）
        "limit_token": bool(settings.get("limit_token_output", False)),
        "min_token": settings.get("min_token", DEFAULT_MIN_TOKEN),
        "max_token": settings.get("max_token", DEFAULT_MAX_TOKEN),
    })
    return [profile] if profile else []


def active_profile(profiles: list, has_key=None, selected_id: str = "") -> dict:
    """从有序档案里挑出"当前真正可用的那一条"

    `has_key(profile) -> bool` 由调用方注入（Key 存在 DPAPI 分槽里，本模块不碰存储层）。
    ⚠️ **参数是整条档案 dict，不是 provider 字符串** —— 这里踩过一个静默很久的坑：
       本函数以前调的是 `has_key(profile["provider"])`，而**所有**调用方传进来的
       都是 `_has_profile_key(profile: dict)`（内部第一句
       `if not isinstance(profile, dict): return False`）。
       传字符串进去永远得到 False ⇒ "找第一条有 Key 的"这个循环**从来没命中过**，
       函数无条件落到 `return items[0]`。后果是用户明确要的那条规则
       （「如果期间我删除了原本选择模型厂商的apikey则选择一个更靠上的厂商的第一个模型」）
       其实一直是**失效**的：只要第 0 条没 Key，也照样硬用它发请求（必然 401），
       而不是落到下面那条有 Key 的。本轮连同 selected_id 一起改对。

    规则（顺序固定）：
      · **先认 selected_id**（用户在聊天框模型弹层里显式选中的那条）—— 本轮新增，
        修「同厂商两条档案界面上独立、后端却永远只认靠前那条」：
        命中且这条档案自己有 Key 才生效；命不中（档案已删）或它没 Key
        （不能用来发请求）→ 落回顺序推导。
      · 按数组顺序找第一个"配了 Key"的；
      · 一个都没 Key → 返回第一条（界面仍要显示点什么，聊天时会走 no_key 引导）；
      · 档案为空 → 返回 {}。
    """
    items = normalize_profiles(profiles)
    if not items:
        return {}
    check = callable(has_key)

    def _usable(profile):
        """这条档案能不能直接拿来发请求（调用方没给判定函数时一律当真，保持旧行为）"""
        if not check:
            return True
        try:
            return bool(has_key(profile))
        except Exception:                       # noqa: BLE001
            return False

    want = str(selected_id or "").strip().lower()
    if want:
        for profile in items:
            if profile.get("id") != want:
                continue
            if _usable(profile):
                return profile
            break                               # 选中这条没 Key：不再认它，走顺序推导
    if check:
        for profile in items:
            if _usable(profile):
                return profile
    return items[0]


def thinking_key(provider: str, model: str, profile_id: str = "") -> str:
    """按模型分别存思考档位的字典键（见 constants 里的 `ai_thinking_level`）。

    ⚠️⚠️ 本轮改动（用户原话）：「服务商的模型列表里有同一个服务商时，他的模型很多设置
       都是相通的，例如**思考强度 ui 他们就是相通的**，可是我需要的是每个模型都是
       **独立存储**的，删除厂商也跟随删除，而不是同厂商的就允许相同」
       → 旧键 `provider|model`：同一家厂商的**两条档案**（两套 Key、或一个官方一个中转）
         列了同一个模型名时，档位互相串改；删掉其中一家，另一家的记忆也一起没了 /
         或者该没的没清掉。
       → 新键 `profile_id|provider|model`：**每条档案自己一份**，
         删除档案时按 `profile_id|` 前缀精确清掉它的全部条目（见 strip_thinking_store）。
       ⚠️ `profile_id` 可选是为了**读取兼容**：老配置里存的是旧格式，
         读的时候先查新键、查不到再查旧键，不至于升级就把用户调好的档位清空。
         写入一律用新键（带 id），所以旧条目会在第一次改动后被自然取代。
    """
    pid = str(profile_id or "").strip().lower()
    body = "%s|%s" % (str(provider or "").strip().lower(), str(model or "").strip())
    return "%s|%s" % (pid, body) if pid else body


def thinking_prefix(profile_id: str) -> str:
    """某条档案全部思考档位条目的**键前缀**（删除档案时按它清表）

    ⚠️ 没有 profile_id 时返回 None 而不是空串：空串是任何键的前缀，
       `strip_thinking_store` 以前就因此"什么都不删"（用户报的「删除对应厂商
       他的思考强度存储也会一并删除」没生效的一条真因）。调用方必须判 None。
    """
    pid = str(profile_id or "").strip().lower()
    return "%s|" % pid if pid else None


def thinking_key_parts(key) -> tuple:
    """把一个档位表的键拆成 (profile_id, provider)；认不出来返回 ("", "")。

    两种历史格式（见 thinking_key）：
      · 新：`<profile_id>|<provider>|<model>` —— 档案级，可精确归属
      · 旧：`<provider>|<model>`             —— 厂商级，同厂商多条档案**共用**（bug 之源）
    模型名里出现 `|` 的概率极低；万一出现，多段的那条按"新格式"处理，
    provider 取第二段，只是让这条脏键归属看得略保守，不影响其它键。
    """
    text = str(key or "").strip()
    if "|" not in text:
        return ("", "")
    parts = text.split("|", 2)
    if len(parts) < 3:
        return ("", parts[0].strip().lower())      # 旧格式：第一段是厂商
    return (parts[0].strip().lower(), parts[1].strip().lower())


def is_scoped_thinking_key(key) -> bool:
    """这条键是不是"档案级"（新格式，带 profile_id 前缀）"""
    return bool(thinking_key_parts(key)[0])


def strip_thinking_store(store, profile_id: str, provider: str = "") -> dict:
    """从档位表里删掉**这条档案**的所有条目（需求：「删除厂商也跟随删除」）。

    ⚠️ 带 profile_id 时只删这一条档案的前缀，**不碰**同厂商其它档案 —— 这正是用户要的
       "而不是同厂商的就允许相同"：两条 DeepSeek 档案各自独立，删 A 不影响 B。
    ⚠️⚠️ 本轮补上 provider（用户原话：「删除对应厂商他的思考强度存储也会一并删除」）：
       旧格式键 `<provider>|<model>` 是**厂商级**的，光按 profile_id 前缀删永远删不掉，
       于是：①配置里积累一堆指向已删档案的死条目；
            ②更糟的是读取端（老写法）会拿这条脏键当"老配置兜底"，
              让**新建**的同厂商档案莫名其妙带着已删档案的档位 —— 看着就像"没删干净"。
       所以：只要传了 provider，就把该厂商的**旧格式（厂商级）键**一并清掉。
       这不违反"不影响同厂商另一条档案"：另一条档案的记忆在**它自己的**
       `<pid>|<provider>|<model>` 键里，一条都不会被这里删掉（而且一旦两条档案
       各自拨过档位，旧键就再也不会被读到了，留着只有坏处）。
    """
    if not isinstance(store, dict):
        return {}
    prefix = thinking_prefix(profile_id)
    provider = str(provider or "").strip().lower()
    result = {}
    for key, value in store.items():
        pid, prov = thinking_key_parts(key)
        if prefix and pid and key.startswith(prefix):
            continue                       # 这条档案自己的档案级条目
        if not provider and not prefix:
            result[key] = value
            continue
        if provider and not pid and prov == provider:
            continue                       # 已删厂商留下的厂商级脏键
        result[key] = value
    return result


def provider_profile_ids(profiles, provider: str) -> list:
    """某家厂商当前有几条档案（决定"厂商级旧键到底该归谁"）。"""
    want = str(provider or "").strip().lower()
    out = []
    for item in (profiles or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("provider") or "").strip().lower() != want:
            continue
        pid = str(item.get("id") or "").strip().lower()
        if pid:
            out.append(pid)
    return out


def migrate_thinking_store(store, profiles, active_profile_id: str = "",
                           legacy_level: str = "") -> dict:
    """把"厂商级旧键 / 全局旧值"**归位**到档案级键（返回新表；不改动入参、绝不丢数据）。

    ⚠️ 为什么要有这一步（本轮需求"每个思考 ui 都应该是关闭状态"的真根因）：
      读取端以前在表里查不到时会回退**全局** `ai_thinking`，而全局值每次切模型都被
      刷新成"上一个模型的档位" → 新加的厂商/档案一进来就继承上一家的 high/max，
      用户看到的"默认不是关闭"。正确做法不是在读的时候继续猜，而是把历史值
      **一次性落到它真正归属的那条档案上**，之后读取端以档案级键为主。

    ⚠️⚠️ 本轮自测抓到的**数据丢失**坑（写这版规则前先看明白，别再改回去）：
      第一版把"认不出归属的厂商级旧键"**直接丢掉**。实测本机配置
      （`ai_provider_profiles` = 空数组，档位表里却有 4 条厂商级记录）跑一次归位
      变成 0 条 —— 用户调好的档位凭空全没。这比原来的 bug 严重得多，所以：
      **该厂商有档案 → 归位给第一条（归属确定、从此不再相通）；
       该厂商一条档案都没有（档案体系还没建立）→ 原样保留，读取端照旧能读到。**
    规则（顺序固定）：
      1. 档案级键原样保留（包括 off：那是用户明确拨过的档位，不许当脏数据丢）；
      2. 厂商级旧键 `<provider>|<model>`：该厂商**有档案** → 归位到**第一条**
         （同厂商多条时只能这么猜，且从这一刻起它们不再相通；这条档案本来也在读
          同一个值，所以它不算丢，其余档案改为"没记录 = off"正是本轮要的修复）；
         该厂商**没有任何档案** → **原样保留**（没有"另一条档案"可串，
         拒掉就等于把用户唯一的记录判成没设过 → 静默变 off）；
      3. 当前生效档案的当前模型仍然没有任何记录时，才接住全局 `ai_thinking` 快照；
      4. 其余一律不写 = 查不到 = off（需求"默认关闭"）。
    ⚠️ 第 3 步依赖"调用时机在档案指针被改动**之前**"（全局快照属于上一个选择）：
       desktop/api/ai.py 的 set_model_choice 已显式先归位再改指针，注释有推导。
    """
    result = {}
    if isinstance(store, dict):
        for key, value in store.items():
            if is_scoped_thinking_key(key):
                result[key] = value
    items = [p for p in (profiles or []) if isinstance(p, dict)]
    if isinstance(store, dict):
        for key, value in store.items():
            if is_scoped_thinking_key(key):
                continue
            _pid, prov = thinking_key_parts(key)
            ids = provider_profile_ids(items, prov)
            if ids and "|" in str(key):
                model = str(key).split("|", 1)[1]
                result[thinking_key(prov, model, ids[0])] = value
                continue                    # 已归位给该厂商第一条档案，旧键不再保留
            result[key] = value             # 该厂商没档案 → 原样留着（见上面的丢数据坑）
    # 3) 当前生效档案 + 当前模型仍无任何记录 → 接住全局旧值，别让老用户静默变关
    # ⚠️⚠️ 这一步**只在"整张表还没有任何档案级记录"时**才允许发生（本轮自测抓到的
    #    串档：给 A 设 high 后切到 B，B 凭空变 high）。推导：
    #      全局 `ai_thinking` 每次切模型都会被刷新成"上一个模型的档位"，
    #      所以它**只在"这张表还是空的"那一刻**才等价于"老用户从来没归位过的历史值"。
    #      表里一旦出现档案级记录，说明归位已经完成、事实源已经换成这张表，
    #      此后快照只是"上一次用的是哪档"的流水值，拿它喂任何档案都是**编出来的档位**。
    if legacy_level is True:                 # 老配置的布尔 True（档位那一版之前）
        legacy_level = "medium"
    elif legacy_level is False:
        legacy_level = "off"
    has_scoped = any(is_scoped_thinking_key(k) for k in result)
    level = str(legacy_level or "").strip().lower()
    if level in ("", "off", "false", "0", "none", "关", "关闭"):
        level = ""              # 全局本来就是关 → 什么都不写（全新安装零条目、零 I/O）
    aid = str(active_profile_id or "").strip().lower()
    if level and aid and not has_scoped:
        target = None
        for item in items:
            if str(item.get("id") or "").strip().lower() == aid:
                target = item
                break
        if target is not None:
            prov = str(target.get("provider") or "").strip().lower()
            model = str(target.get("model") or "").strip()
            scoped = thinking_key(prov, model, aid)
            if prov and model and scoped not in result \
                    and thinking_key(prov, model) not in result:
                result[scoped] = level
    return result


def get_thinking_level(store, provider: str, model: str, fallback: str = "off",
                       profile_id: str = "", profile_ids=None) -> str:
    """查这条**档案 + 这个模型**记住的档位；查不到 → fallback（默认 off）。

    `store` 是 settings 里那个 dict（ai_thinking_level），容错：不是 dict 就当空。
    `profile_ids` 是**该厂商目前的档案 id 列表**（profiles.provider_profile_ids 算的）。

    读取顺序与理由：
      1. 档案级键 `<pid>|<provider>|<model>` —— 唯一事实源，用户明确为这条档案设的；
      2. 厂商级旧键 `<provider>|<model>` —— **只有归属唯一时才认**：
         · 没有档案体系（老配置直接跑，profile_id 为空）→ 没有"串档"可言，认；
         · 该厂商只有一条档案且就是当前这条 → 归属唯一，认（老用户升级不丢档位）；
         · 该厂商有两条以上档案 → **谁都不许认**：这正是用户报的
           "同厂商两条档案的思考强度 ui 是相通的"，认了就会互相串改；
      3. 都没有 → fallback（= off，需求"每个思考 ui 都应该是关闭状态"）。
    ⚠️ 绝不回退全局 `ai_thinking`：那是"上一个模型档位"的快照，
       拿它当默认值就是本轮"新厂商默认不是关闭"这个 bug 的本体。
    """
    if not isinstance(store, dict):
        return fallback
    pid = str(profile_id or "").strip().lower()
    if pid:
        text = _thinking_hit(store, thinking_key(provider, model, pid))
        if text:
            return text
    ids = [str(x).strip().lower() for x in (profile_ids or []) if str(x).strip()]
    # ⚠️ "归属唯一"只看**这家厂商目前有几条档案**，不要求 pid 落在 ids 里：
    #    · 0 条（档案体系还没建立，或 ai_profile_id 是指向已删档案的陈旧值）→
    #      根本不存在"另一条档案"可以被串，这条厂商级键是用户**唯一**的记录，
    #      拒掉它 = 把用户调好的档位判成"没设过"→ 静默变 off（本轮自测抓到的
    #      真实数据丢失就是这个分支：本机 profiles=[] + 4 条厂商级记录）；
    #    · 1 条 → 唯一归属就是它，读到即正确（哪怕 pid 是个陈旧 id，真正生效的
    #      档案按 active_profile 也会落回这唯一一条）；
    #    · ≥2 条 → **谁都不许读**：这正是用户报的"同厂商两条档案 ui 是相通的"。
    #    正常流程下 ≥2 条这个分支见不到厂商级键（migrate_thinking_store 已把它们
    #    归位成档案级），这里是给"迁移没跑成/没触发"留的最后一道防线。
    sole_owner = (not ids) or (len(ids) == 1)
    if sole_owner:
        text = _thinking_hit(store, thinking_key(provider, model))
        if text:
            return text
    return fallback


def _thinking_hit(store: dict, key: str) -> str:
    value = store.get(key)
    return str(value).strip() if value is not None else ""


def build_settings_view(profiles: list, settings: dict = None) -> dict:
    """把档案数组摊平成**旧口径**的平铺设置键（兼容所有既有读取方）

    为什么需要：聊天/润色/能力清单等一大堆既有代码读的是
    `ai_provider` / `model_name` / `api_base` / `max_token` 这几个**平铺**键。
    与其把它们全改成读 profiles（改动面巨大、回归风险高），不如在保存档案时
    顺手把"当前生效那条"写回这几个平铺键 —— 单一事实源仍是 profiles，
    平铺键只是派生出来的快照。
    """
    current = active_profile(profiles)
    view = {}
    if not current:
        return view
    view["ai_provider"] = current["provider"]
    view["model_name"] = current.get("model") or ""
    # ⚠️ label 是显示标签，别写进 model_name —— model_name 要参与 API 调用解析
    view["api_base"] = current.get("api_base") or ""
    # token 限制：只有该档案真的打开了开关才把上限传给旧键，
    #   否则写 0（= 不限），免得"默认关闭"的档案还带着 4096 的隐性上限。
    view["limit_token_output"] = bool(current.get("limit_token"))
    view["min_token"] = current.get("min_token", DEFAULT_MIN_TOKEN)
    view["max_token"] = (current.get("max_token") or DEFAULT_MAX_TOKEN) \
        if current.get("limit_token") else 0
    return view


def profile_summary(profile: dict, providers_module=None) -> dict:
    """给前端长条卡片用的摘要（**只加显示字段，不改原始数据**）

    返回原档案 + 三个派生字段：
      · `provider_label`：厂商全称（灰色字体那个括号里的内容）
      · `model_count`：支持模型数量（用户要求"x 个模型"必须变量、不能写死）
      · `key_tail`：Key 尾号（可选，由调用方补）
    """
    base = normalize_profile(profile)
    if not base:
        return {}
    out = dict(base)
    out["provider_label"] = ""
    if providers_module is not None:
        try:
            out["provider_label"] = providers_module.provider_display(base["provider"])
        except Exception:                           # noqa: BLE001
            out["provider_label"] = base["provider"]
    if not out["provider_label"]:
        out["provider_label"] = base["provider"]
    out["model_count"] = len(base["models"])
    return out
