"""GCP-AI 域（`window.pywebview.api.ai`）—— 把原版 `ui/ai_chat_panel.py` 的**会话模型**搬到 Web 端。
========== 为什么要有这个后端域（而不是前端自己 fetch） ==========
Web 版早期是前端直接 `fetch(api_base + '/chat/completions')`，历史对话也写在前端
localStorage 里。结果是：
  1. **历史对话的粒度完全错了**：localStorage 里存的是"消息数组"，历史面板列出的是
     **每一条消息**；而原版（`core/ai/chat_store.py`）是 **一个会话 = 一个 json 文件**，
     历史面板列出的是**一个个对话页**（标题 = 第一句话、时间是会话的创建/更新时间）。
  2. 清除历史后前端只清了自己的 localStorage，列表要"重新进一次"才刷新。
  3. API Key 要送到前端才能发请求（前端 fetch 必须带 Authorization）。
所以这里把原版那套原封不动接回来：
  · 会话文件 `.ToolsGCP/config/chats/<id>.json`（**和 PyQt 版共用同一份数据**，
    在一边聊过的对话，另一边打开就能看到）；
  · 组装 messages 走 `pymodels.core.ai.prompt`（system 提示词 / 资源清单 / 上下文轮数）；
  · 发请求走 `pymodels.core.ai.client.chat`（永不抛异常，返回可读的错误说明）；
  · API Key 只在后端使用，不经过前端。
========== 历史对话不存储的成因与写入顺序约定 ==========
日志里 0 条 `[AI|chat]`、`<用户数据根>/config/chats/` 为空，不是存储坏了，而是
**根本就没走到存储**：
  · 用户设置里 `api_key` 与 `model_name` 都是空 → 前端 `aiSend()` 里有一道
    "先查 `settings.api_key_state`，没配 Key 就只往界面推两条气泡并 return"的早退，
    **压根没调 `ai.send`**（所以后端日志也不可能有记录）；
  · 后端 `send()` 若把 "没 Key/没模型" 放在**写盘之前**、且失败**不打日志**，
    就算某个调用方真的走到了这里，也同样是"什么都不留痕"。
本层的写入顺序（对齐 PyQt 版 `ai_chat_panel.send_message()`）：
  1. **用户消息先落盘**（不管后面发不发得出去，说过的话不能丢）；
  2. 没有 API Key / 模型名 → 落一条固定的引导回答再返回 `{ok:true, kind:"no_key", reply:…}`，
     和原版"给固定回答 + 都写进历史"完全一致；
  3. 每条失败路径都写日志（`no_key` / `no_model` / 请求失败 / 落盘失败），
     "历史不存储"这类问题能在日志里一句话定位；
  4. 落盘结果真的检查（`ChatStore.append()` 内部把 `save()` 的返回值丢了，
     这里补 `path_of()` 存在性校验 + 再 save 一次），失败会带 `persisted:false` 回前端。
⚠️ 前端那道早退（`aiSend` 里 no-key 直接 return）与后端策略要一致：
   要么删掉那道早退让后端来兜（推荐，历史就能存下来），
   要么接受"没配 Key 的提问不落历史"。
"""

import json
import os
import re
import threading
import time
import uuid

from pymodels.constants import APP_NAME, APP_VERSION


def _now() -> str:
    """消息时间戳（和 pymodels.core.ai.chat_store 同格式，历史面板/排序口径一致）"""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ok(**kwargs):
    payload = {"ok": True}
    payload.update(kwargs)
    return payload


def _fail(message, **kwargs):
    payload = {"ok": False, "error": str(message or "unknown error")}
    payload.update(kwargs)
    return payload


def _log(level: str, category_zh: str, category_en: str, message: str):
    try:
        from pymodels.utils.logger import log
        getattr(log, level, log.info)(category_zh, category_en, message)
    except Exception:
        pass


def _reasoning_of(extra) -> str:
    """从 extra 里取「这一版的思考文本」（没有就当空串）

    ⚠️ 思考与正文彻底分家（用户报的"没开思考按钮却输出思考内容"）：
       正文永远只走 content，思考只走这个字段 → versions 的 variant_reasoning 表。
    """
    if not isinstance(extra, dict):
        return ""
    return str(extra.get("reasoning") or "")


class AiDomain:
    """GCP-AI 会话 / 历史 / 发送"""

    def __init__(self, shell):
        self._shell = shell
        # 正在跑的流式请求：stream_id → 状态 dict（stop/latest/done…）。
        # 只放内存：这些是"一次输出过程"的临时状态，**绝不能进会话文件**
        # （用户要求：等待提示和半截的流式内容不能当成一条历史消息）。
        self._streams = {}
        self._streams_lock = threading.Lock()

    # ---------- 基础 ----------
    @property
    def store(self):
        from pymodels.core.ai.chat_store import ChatStore
        return ChatStore()

    @property
    def settings_manager(self):
        return getattr(self._shell, "settings_manager", None)

    def _setting(self, key: str, fallback=None):
        manager = self.settings_manager
        if manager is None:
            return fallback
        value = manager.settings.get(key)
        return fallback if value in (None, "") else value

    # ================= 服务商配置档案（本轮设置页重构） =================
    # 需求原话见 core/ai/profiles.py 的模块 docstring（那里是唯一设计说明）。
    # 这里只是桥接：读/写 `ai_provider_profiles` 这一个设置键，并把"当前生效那条"
    # 派生回旧的平铺键（ai_provider / model_name / api_base / max_token），
    # 让既有聊天/润色/能力清单代码一行都不用改。

    def _selected_profile_id(self) -> str:
        """用户在聊天框模型弹层里显式选中的档案 id（`ai_profile_id`）。

        ⚠️ 本轮新增（修「同厂商两条档案的模型切换 UI 会同时变」）：
           以前"当前用哪条"完全由**数组顺序**推导，同厂商两条档案在界面上
           是两组独立模型、后端却永远只认靠前那条 → 点第二条那组里的模型，
           看着切了、实际没切，思考档位也跟着另一条走。
           现在前端点选时写这个键，读档案时优先认它（命不中/那条没 Key 时
           由 `profiles.active_profile` 自动落回顺序推导，不会卡死）。
        """
        return str(self._setting("ai_profile_id", "") or "").strip().lower()

    def _thinking_level_for(self, provider: str, model: str, profile_id: str = "") -> str:
        """该**模型**单独记住的思考档位。

        需求原话（本轮）：「切换不同模型他们的思考强度**默认都是关闭的**，
        每个思考强度都有**单独的存储**等级几的强度」—— 两句话是有冲突的，
        取这个解释（也是唯一自洽的解释）：
          · 这台模型**设过** → 用它自己那份记忆（切回来还在，不互相污染）；
          · 这台模型**从没设过** → **关**（"默认关闭"）。

        ⚠️⚠️ 唯一例外：整张表**全空**（= 这个用户还在用旧版，从没在新 UI 上
           拨过档位）。这时必须退回旧的全局 `ai_thinking`，否则老用户一升级
           就被静默改成"思考关闭"，他原来调好的 high 凭空没了。
           表现上也很自然：他**当前这台**模型继续沿用旧值，
           而从这一刻起遇到的**其它**模型才享受"默认关"。
           （不这么处理会踩另一个坑：全局值每次切模型都被刷新成"上一个模型的档位"，
             于是新模型的默认档 = 上一个模型的档位 = high，永远不关 —— 自测抓到的。）
        ⚠️⚠️ 本轮新增 `profile_id`（用户原话：「同一个服务商的模型思考强度 ui 他们是
           相通的，可是我需要每个模型都是独立存储的，删除厂商也跟随删除」）：
           键里必须带上**档案 id**，否则同一家厂商的两条档案列了同一个模型名时
           共用一条记录 → 在 A 上拨到 high，B 也跟着变 high。
        """
        try:
            from pymodels.core.ai import profiles as ai_profiles
            store = self._setting("ai_thinking_level", {}) or {}
            if not isinstance(store, dict):
                store = {}
            hit = str(store.get(
                ai_profiles.thinking_key(provider, model, profile_id)) or "").strip()
            if not hit and profile_id:
                # 老配置兜底：这条档案还没写过新键时，认一次旧的 provider|model
                hit = str(store.get(ai_profiles.thinking_key(provider, model)) or "").strip()
            if hit:
                return hit
            legacy = str(self._setting("ai_thinking", "off") or "off")
            return legacy if not store else "off"
        except Exception:                                 # noqa: BLE001
            return str(self._setting("ai_thinking", "off") or "off")

    def _remember_thinking_level(self, provider: str, model: str, level: str,
                                 profile_id: str = "") -> None:
        """把档位写进"按模型"那张表（同时仍写全局 `ai_thinking` = 当前档，
        这样老读取方 / 浏览器端不用改也能拿到当前值）。"""
        manager = self.settings_manager
        if manager is None:
            return
        try:
            store = dict(manager.settings.get("ai_thinking_level") or {})
            if not isinstance(store, dict):
                store = {}
        except Exception:                                 # noqa: BLE001
            store = {}
        try:
            from pymodels.core.ai import profiles as ai_profiles
            # ⚠️ 用**带档案 id 的键**写入（见 _thinking_level_for 里的需求说明）。
            #    没有 id（旧前端 / 兜底路径）时退回旧格式，行为不比改之前差。
            store[ai_profiles.thinking_key(provider, model, profile_id)] = str(level or "off")
            manager.update_setting("ai_thinking_level", store)
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "AI", "thinking", f"记住思考档位失败（不影响本次请求）: {exc}")

    def _profiles_raw(self) -> list:
        """读档案数组（空时用旧配置合成一条，见 profiles.migrate_from_legacy）

        ⚠️⚠️ "空"要分两种，别一律当老配置迁移（这个坑删档案时会立刻现形）：
          · 键**根本不存在**（`ai_provider_profiles` 从没写过）→ 真·老用户，走迁移合成；
          · 键存在但值是**空数组** → 用户把最后一条档案删了，就是**没有服务商**，
            绝不能又凭平铺键把刚删掉的那家"复活"成一个幽灵档案。
        """
        from pymodels.core.ai import profiles as ai_profiles
        manager = self.settings_manager
        settings = dict(getattr(manager, "settings", {}) or {}) if manager is not None else {}
        raw = self._setting("ai_provider_profiles", []) or []
        items = ai_profiles.normalize_profiles(raw)
        if items:
            # ⚠️ 本轮：这条"有档案就直接返回"的近路**也要**过一遍旧 Key 归集。
            #    否则老数据（档案早就建好、Key 还躺在厂商槽里）永远走不到归集，
            #    model_choices 依旧把每条档案都判成"未填 Key"（自验抓到的：
            #    加了 _adopt_provider_slot_keys 但 groups 仍然是空）。
            return self._fill_profile_defaults(self._adopt_provider_slot_keys(items))
        # ⚠️ "是不是老用户"不能用 `"ai_provider_profiles" in settings` 判 ——
        #    SettingsManager 加载时会把 DEFAULT_SETTINGS 合并进内存**并落盘**，
        #    于是这个键在磁盘上也永远存在（值是默认空数组），迁移分支永不触发
        #    （本轮自验脚本抓到的真 bug：老用户升级后服务商列表一片空白）。
        #    可靠的信号是**用户真的配过东西**：档案为空、但旧口径里
        #    有厂商 Key / 有模型名 / 有接口地址 → 按老配置合成一条。
        #    全新安装（一个 Key 都没填、模型名也空）仍然得到空数组，符合预期。
        if self._has_legacy_ai_config(settings):
            items = ai_profiles.migrate_from_legacy(settings)
            items = self._fill_profile_defaults(items)
            # ⚠️⚠️ 合成出来必须**当场落盘一次**，不能每次读都现合成：
            #    `normalize_profile()` 在没有 id 时会生成新的随机 id，
            #    于是"读两次拿到两个不同 id"—— 前端按 id 编辑/删除永远找不到，
            #    Key 槽也会一次一个名字地疯长（本轮自验抓到的真 bug，比被吞更隐蔽）。
            #    落盘后 `ai_profiles_migrated` 置真，下次读直接用磁盘上那份稳定 id。
            #    （读操作写盘是例外，仅"一次性迁移"这一处，且写完就不再触发。）
            if items:
                only = items[0]
                # 旧厂商槽的 Key 只搬给**这一条**档案：
                # ⚠️ 绝不能在 `get_profile_api_key()` 里做"读不到就复制厂商槽"——
                #    那样同厂商每一条档案都会复制一份、全被判成"有 Key"，
                #    优先级和"未填 Key 不显示"双双失真（本轮自验抓到的另一个真 bug）。
                legacy_key = self._read_legacy_provider_key(only.get("provider"))
                try:
                    self._persist_profiles(items)
                except Exception as exc:                   # noqa: BLE001
                    _log("warn", "AI", "profiles", f"老配置迁移落盘失败（本次仅内存）: {exc}")
                if legacy_key:
                    try:
                        manager.set_profile_api_key(legacy_key, only.get("id"),
                                                    only.get("provider"))
                    except Exception:                      # noqa: BLE001
                        pass
                    # 厂商旧槽清空：Key 已搬进档案槽，留着会被"读旧键"的老路径误用
                    try:
                        manager.set_api_key("", only.get("provider"))
                    except Exception:                      # noqa: BLE001
                        pass
                _log("info", "AI", "profiles",
                     f"老配置已迁移为服务商档案：{only.get('provider')}/{only.get('id')}")
        return self._fill_profile_defaults(self._adopt_provider_slot_keys(items))

    def _adopt_provider_slot_keys(self, items: list) -> list:
        """把**厂商旧槽**里残留的 Key 交给"该厂商唯一的那条档案"（一次性、无歧义才做）

        ⚠️⚠️ 本轮修复用户报的「至少有一个服务商在列表中了，可是对话框里的模型选择
           还是没有任何服务商、不显示任何模型」：
           Key 从"按厂商分槽"改成"按档案分槽"之前存的 Key，落在
           `api_key_enc_deepseek` 这类**厂商槽**里；而 `model_choices()` /
           `_credentials()` 判断"这条档案能不能用"只看 `api_key_enc_<档案id>`。
           读不到 ⇒ 这条档案被当成"未填 Key"整组过滤掉 ⇒ 模型下拉一片空白。
           （上一轮迁移只在"档案数组整个为空、从平铺键合成"时搬 Key，
             已经建过档案的用户根本没走到那条路。）

        ⚠️ 为什么必须限定"该厂商只有一条档案"才搬：同厂商两条档案共用一把厂商槽
           时，搬到哪一条都是猜（另一条会凭空"未填 Key"，或两条都判成有 Key，
           优先级和过滤双双失真 —— 这是 AGENTS 里点过名的坑）。
           有歧义就**什么都不动**，让用户在新 UI 里重填一次，明确且可预期。
        """
        if not items:
            return items
        manager = self.settings_manager
        if manager is None:
            return items
        try:
            # ⚠️⚠️ **先做零成本的字符串预检**，别每次读档案都去 DPAPI 解密。
            #    这个函数挂在 `_profiles_raw()` 上，而后者**每条消息至少被调 3 次**
            #    （_credentials / model_choices / _profile_max_token）。
            #    直接进循环的话，每次都要对每个厂商做一遍 `get_api_key()`
            #    （= ctypes CryptUnprotectData + 正则 + 明文清洗），
            #    用户本轮正好报了「AI 回复比我之前要等的更久」——
            #    读路径上任何一点固定开销都会直接加在"第一个字出现之前"的等待里。
            #    归集只需要回答"厂商槽里还有没有东西"，看**密文键在不在**就够了；
            #    而归集成功后那几个槽会被清空 → 预检恒为假 → 之后每次读都是 O(1) 早退。
            settings_map = getattr(manager, "settings", {}) or {}
            if not any(str(k).startswith("api_key_enc_") and settings_map.get(k)
                       for k in settings_map):
                return items
            by_provider = {}
            for item in items:
                by_provider.setdefault(item.get("provider", ""), []).append(item)
            for pid, group in by_provider.items():
                if not pid or len(group) != 1:
                    continue
                if str(settings_map.get("api_key_enc_" + pid) or "") == "":
                    continue                     # 这家厂商槽没东西（含"已归集过"）
                prof = group[0]
                if manager.get_profile_api_key(prof.get("id"), pid):
                    continue                     # 档案槽已经有了，以它为准
                if not manager.get_api_key(pid):
                    continue                     # 解不出明文（损坏等）→ 别乱动
                if manager.adopt_legacy_provider_key(prof.get("id"), pid):
                    _log("info", "AI", "profiles",
                         f"厂商旧槽的 API Key 已交给档案：{pid}/{prof.get('id')}")
        except Exception as exc:                 # noqa: BLE001
            _log("warn", "AI", "profiles", f"归集旧 API Key 槽失败（不影响启动）: {exc}")
        return items

    def _fill_profile_defaults(self, items: list) -> list:
        """给缺字段的档案补上厂商默认地址 / 官方模型清单 / 默认名称标签

        单独抽出来是因为迁移路径要"补完再落盘"，而普通读路径也要"补完再给前端画"，
        两处各写一遍迟早对不上。
        """
        if not items:
            return items or []
        from pymodels.core.ai import profiles as ai_profiles
        from pymodels.core.ai import providers as ai_providers
        for only in items:
            if not only.get("api_base"):
                only["api_base"] = ai_providers.default_api_base(only.get("provider", ""))
            if not only.get("models"):
                models = ai_providers.models_of(only.get("provider", ""))
                if models:
                    only["models"] = list(models)
            if not only.get("model") and only.get("models"):
                only["model"] = only["models"][0]
            if not only.get("label"):
                only["label"] = ai_profiles.default_label_for(only.get("provider", ""))
        return items

    def _read_legacy_provider_key(self, provider) -> str:
        """读厂商旧槽里的 Key 明文（只为一次性迁移服务）"""
        manager = self.settings_manager
        if manager is None or not provider:
            return ""
        try:
            return manager.get_api_key(provider) or ""
        except Exception:                                  # noqa: BLE001
            return ""

    def _has_key(self, provider_id: str) -> bool:
        """厂商槽有没有 Key（老口径；档案改造后主要给兼容路径用）"""
        manager = self.settings_manager
        if manager is None:
            return False
        try:
            return bool(manager.get_api_key(provider_id))
        except Exception:                                  # noqa: BLE001
            return False

    def _has_legacy_ai_config(self, settings: dict) -> bool:
        """老配置信号：**厂商槽里真的有 Key** 才认为这个用户配过东西

        ⚠️⚠️ 判据只能用 Key，不能再用 model_name / api_base ——
           这两个在 DEFAULT_SETTINGS 里**本来就有默认值**
           （api_base 默认就是 `https://api.deepseek.com/v1`），
           全新安装也"有值"，于是每个新用户一进来就被合成一条空档案、
           服务商列表里凭空多出一条"DeepSeek（未填 Key）"
           （本轮自验脚本抓到的真 bug）。
           Key 不可能有默认值：**有 Key == 用户真的配过**。

        ⚠️ 仍要先排除"已经迁移过一次"：`ai_profiles_migrated` 为真就不再合成，
           否则用户删掉最后一条档案后、旧厂商槽里如果还留着 Key，
           下次读列表又会"复活"出一条幽灵档案。
           标记由 `_persist_profiles()` 写入（任何一次真正的档案写盘都算"用户已接管"）。
        """
        try:
            if bool(settings.get("ai_profiles_migrated", False)):
                return False
        except Exception:                     # noqa: BLE001
            pass
        try:
            manager = self.settings_manager
            if manager is None:
                return False
            pid = str(settings.get("ai_provider") or "").strip().lower()
            return bool(pid and manager.get_api_key(pid))
        except Exception:                     # noqa: BLE001
            return False

    def _has_key(self, provider_id: str) -> bool:
        manager = self.settings_manager
        if manager is None:
            return False
        try:
            return bool(manager.get_api_key(provider_id))
        except Exception:                                  # noqa: BLE001
            return False

    def _has_profile_key(self, profile) -> bool:
        """这条档案**自己**有没有 Key（本轮：Key 按档案 id 分槽，不再按厂商）"""
        manager = self.settings_manager
        if not isinstance(profile, dict):
            return False
        if manager is None:
            return False
        try:
            return bool(manager.get_profile_api_key(profile.get("id"),
                                                     profile.get("provider")))
        except Exception:                                  # noqa: BLE001
            return False

    def _profile_key_tail(self, profile) -> str:
        manager = self.settings_manager
        if manager is None or not isinstance(profile, dict):
            return ""
        try:
            return manager.profile_key_tail(profile.get("id"), profile.get("provider")) or ""
        except Exception:                                  # noqa: BLE001
            return ""

    def _profiles_payload(self) -> list:
        """档案数组 + 前端需要的派生字段（长条卡片直接照着画）"""
        from pymodels.core.ai import profiles as ai_profiles
        from pymodels.core.ai import providers as ai_providers
        out = []
        for item in self._profiles_raw():
            summary = ai_profiles.profile_summary(item, ai_providers)
            # Key 状态由**后端**读（DPAPI 分槽，前端拿不到明文），只回"有没有 + 尾号"
            has_key = self._has_profile_key(item)
            summary["has_key"] = has_key
            summary["key_tail"] = self._profile_key_tail(item) if has_key else ""
            out.append(summary)
        return out

    def profiles(self):
        """给设置页的档案列表（含派生字段与 Key 状态）

        返回 `{ok, profiles:[...], active_id, active_provider, active_model}`。
        ⚠️ 本轮新增 `active_id`：同厂商可能有多条档案，**只有 id 能唯一确定生效那条**，
           前端高亮/编辑回填都必须用 id，不能再拿 provider 比。
        """
        try:
            from pymodels.core.ai import profiles as ai_profiles
            items = self._profiles_payload()
            current = ai_profiles.active_profile(items, self._has_profile_key,
                                       self._selected_profile_id())
            return _ok(profiles=items,
                       active_id=current.get("id", ""),
                       active_provider=current.get("provider", ""),
                       active_model=current.get("model", ""))
        except Exception as exc:                           # noqa: BLE001
            _log("err", "AI", "profiles", f"读取服务商档案失败: {exc}")
            return _fail(exc)

    def save_profile(self, profile=None):
        """新增/更新一条服务商档案（**按档案 id 定位**，保持数组顺序）

        ⚠️⚠️ 本轮修复用户报的「如果列表中有同厂商的又增加一个新的同厂商的，
           保存后会被直接吞了」：旧实现按 **provider** 查找替换，
           第二条 DeepSeek 直接覆盖第一条。现在：
             · 入参带 id 且能在数组里找到 → **原地更新那一条**；
             · id 为空 / 找不到 → **追加一条新档案**（同厂商也允许并存）。
           档案 id 由 profiles.normalize_profile 在缺失时自动生成。

        需求：卡片里的「测试连接」和「保存」，**没有清除按钮**
        （清除 Key 仍走设置页原有的那个入口；这里不要自造第二套删除语义）。
        入参是完整档案 dict（前端编辑器收集好的）。返回保存后的完整列表，
        前端直接用它重画列表，不用再拉一次。
        """
        try:
            from pymodels.core.ai import profiles as ai_profiles
            from pymodels.core.ai import providers as ai_providers
            incoming = ai_profiles.normalize_profile(profile or {})
            if not incoming:
                return _fail("服务商档案缺少厂商 id，无法保存")
            pid = incoming["provider"]
            # 补默认值（前端没填全时也能落一条完整档案）
            if not incoming["api_base"]:
                incoming["api_base"] = ai_providers.default_api_base(pid)
            if not incoming["models"]:
                models = ai_providers.models_of(pid)
                if models:
                    incoming["models"] = list(models)
            incoming["model"] = (incoming["models"][0] if incoming["models"] else "")
            if not incoming["label"]:
                incoming["label"] = ai_profiles.default_label_for(pid)
            manager = self.settings_manager
            if manager is None:
                return _fail("设置未就绪，无法保存服务商档案")
            items = self._profiles_raw()
            replaced = False
            for index, item in enumerate(items):
                if item["id"] == incoming["id"]:          # ← 按档案 id，不按 provider
                    items[index] = incoming
                    replaced = True
                    break
            if not replaced:
                items.append(incoming)          # 新加的排到最后（优先级最低，符合直觉）
            items = ai_profiles.normalize_profiles(items)
            self._persist_profiles(items)
            _log("op", "AI", "profiles",
                 f"{'更新' if replaced else '新增'}服务商档案：{pid}/{incoming['id']} "
                 f"（模型 {incoming['model']}，支持 {len(incoming['models'])} 个，"
                 f"上限 {incoming['max_token']} tokens）")
            # ⚠️ `active_*` 必须是**真正生效**的那条（数组顺序 + 该档案自己有 Key），
            #    不是"刚保存的这条"。刚保存新厂商时它往往**不是** active ——
            #    因为新加的排到数组末尾、优先级最低（用户实测 bug 的正解就是
            #    "保存新厂商不该改掉我已选的模型"）。
            current = ai_profiles.active_profile(items, self._has_profile_key,
                                       self._selected_profile_id())
            return _ok(profiles=self._profiles_payload(),
                       saved=incoming["id"], saved_provider=pid,
                       replaced=replaced,
                       active_id=current.get("id", ""),
                       active_provider=current.get("provider", ""),
                       active_model=current.get("model", ""))
        except Exception as exc:                           # noqa: BLE001
            _log("err", "AI", "profiles", f"保存服务商档案失败: {exc}")
            return _fail(exc)

    def delete_profile(self, profile_id: str = "", provider: str = ""):
        """删除一条服务商档案（长条卡片最右边那个红色按钮）

        ⚠️ 本轮参数从 provider 换成 **profile_id**：同厂商可能有多条，
           只给 provider 无法指定删哪一条。为兼容旧前端仍接受 provider
           （此时删该厂商的**第一条**并写日志说明）。

        需求：「如果期间我删除了原本选择模型厂商的apikey则选择一个更靠上的厂商的第一个模型」
        —— 删除后 `_persist_profiles` 会重算"当前生效那条"并写回平铺键，
        所以聊天用的服务商/模型自动落到**下一条还有 Key 的、且更靠上**的档案。
        """
        try:
            from pymodels.core.ai import profiles as ai_profiles
            manager = self.settings_manager
            if manager is None:
                return _fail("设置未就绪，无法删除")
            items_all = self._profiles_raw()
            target_id = str(profile_id or "").strip().lower()
            removed = None
            if target_id:
                keep = []
                for item in items_all:
                    if item["id"] == target_id and removed is None:
                        removed = item
                        continue
                    keep.append(item)
            else:
                # 兼容旧调用：只给了 provider → 删该厂商第一条
                pid = str(provider or "").strip().lower()
                if not pid:
                    return _fail("没有指定要删除的服务商档案")
                keep = []
                for item in items_all:
                    if item["provider"] == pid and removed is None:
                        removed = item
                        continue
                    keep.append(item)
            if removed is None:
                return _fail("没有找到要删除的服务商档案")
            self._persist_profiles(keep)
            # ⚠️ 清掉**这条档案自己的** Key 槽：档案都删了还留着密文，
            #    会让"未填 Key 的档案不显示"那套逻辑以为它还在用。
            #    ⚠️ 只删这一条的槽，**不动厂商槽**（同厂商可能还有别的档案在用它）。
            try:
                manager.drop_profile_key_slot(removed["id"])
            except Exception:                              # noqa: BLE001
                pass
            # ⚠️⚠️ 本轮需求（用户原话）：「某个配置删除后也要连着把**模型思考状态存储**
            #    一并删除」。以前只删了档案和 Key 槽，`ai_thinking_level` 那张表里的
            #    条目**永远留着** —— 于是①配置里积累一堆指向已删档案的死条目；
            #    ②更糟的是新建一条档案如果**复用了同一个 id**（几乎不可能但 id 撞车时），
            #    或者旧格式键 `provider|model` 残留，都会让"新档案"莫名其妙带着旧档位。
            #    ⚠️ 按 `profile_id|` **前缀**删，只清这一条，同厂商另一条档案的记忆
            #       完全不受影响（正是用户要的"而不是同厂商的就允许相同"）。
            try:
                store = manager.settings.get("ai_thinking_level")
                cleaned = ai_profiles.strip_thinking_store(store, removed["id"])
                if cleaned != (store if isinstance(store, dict) else {}):
                    manager.update_setting("ai_thinking_level", cleaned)
                    _log("op", "AI", "profiles",
                         f"同步清除该档案的思考档位记忆：{removed['id']}"
                         f"（{len(store or {}) - len(cleaned)} 条）")
            except Exception as exc:                       # noqa: BLE001
                _log("warn", "AI", "profiles",
                     f"清除思考档位记忆失败（不影响删除本身）: {exc}")
            current = ai_profiles.active_profile(keep, self._has_profile_key,
                                       self._selected_profile_id())
            _log("op", "AI", "profiles",
                 f"删除服务商档案：{removed['provider']}/{removed['id']} → 当前改用 "
                 f"{current.get('provider') or '(无)'} / {current.get('model') or '(无)'}")
            return _ok(profiles=self._profiles_payload(),
                       deleted=removed["id"], deleted_provider=removed["provider"],
                       active_id=current.get("id", ""),
                       active_provider=current.get("provider", ""),
                       active_model=current.get("model", ""))
        except Exception as exc:                           # noqa: BLE001
            _log("err", "AI", "profiles", f"删除服务商档案失败: {exc}")
            return _fail(exc)

    def add_profile(self, provider: str = "", model: str = ""):
        """弹窗打开时给一份**已经填好默认值**的草稿

        ⚠️⚠️ 本轮修复（用户实测：「当点击添加服务商后弹出的这个里面的支持模型里面为空」）：
           旧写法是 `add_profile()` 不带参数 → 返回 `need_pick=True` 且**没有 draft**，
           前端就退回一个 `provider:'' / models:[]` 的空草稿 → 弹窗里支持模型一片空白、
           接口地址也是空的。
           现在：不传 provider 时**默认取厂商清单第一条**（= DeepSeek，和
           DEFAULT_SETTINGS 的 ai_provider 一致），并把该厂商的官方模型清单、
           官方接口地址、默认模型名称标签全部预填。
           同时排除已经配过的厂商（重复配一家没意义），全配过就退回第一家。
        """
        try:
            from pymodels.core.ai import profiles as ai_profiles
            from pymodels.core.ai import providers as ai_providers
            catalog = ai_providers.provider_items()          # [(id, 显示名), ...]
            if not catalog:
                return _fail("厂商清单为空，无法新建服务商")
            pid = str(provider or "").strip().lower()
            if not pid:
                # ⚠️ 本轮改动（用户原话：「当列表中有例如deepseek了点击添加服务商
                #    他会默认选择下一个厂商给丢弃不要了 还是默认选择deepseek」）：
                #    以前这里会"排除已经配过的厂商"、把默认值挪到下一家。
                #    现在同厂商允许多条档案，默认**永远是清单第一条**（DeepSeek），
                #    用户想再加一条 DeepSeek 就直接是 DeepSeek，不用手动切回去。
                pid = catalog[0][0]
            models = list(ai_providers.models_of(pid))
            draft = {
                "provider": pid,
                # 模型名称默认 = 品牌名（用户："模型名称是有默认的模型名称的"）
                "label": ai_profiles.default_label_for(pid),
                # 接口地址默认填满官方地址（用户："接口地址默认为填写满的状态而不是空着的"）
                "api_base": ai_providers.default_api_base(pid),
                "models": models,
                "model": (str(model or "").strip() or (models[0] if models else "")),
                # token 限制默认关闭（用户："token限制输出默认是关闭的"）
                "limit_token": False,
                "min_token": ai_profiles.DEFAULT_MIN_TOKEN,
                "max_token": ai_profiles.DEFAULT_MAX_TOKEN,
            }
            return _ok(draft=draft, providers=self._provider_items_view(),
                       is_new=True)      # 前端据此知道这是"新建"（切厂商要清空 Key 草稿）
        except Exception as exc:                           # noqa: BLE001
            return _fail(exc)

    def _provider_items_view(self) -> list:
        """厂商清单的 dict 视图（前端要 `{provider,label}`，别把元组透出去）

        ⚠️ `providers.provider_items()` 返回的是 `[(id, 显示名), ...]` 元组列表
           （那是给老下拉框用的形状）。前端一律吃 dict，这里统一转一次，
           免得每个调用点各转一遍、早晚漏一个。
        """
        out = []
        try:
            from pymodels.core.ai import providers as ai_providers
            for item in ai_providers.provider_items():
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    out.append({"provider": item[0], "label": item[1]})
                elif isinstance(item, dict):
                    out.append({"provider": item.get("provider") or item.get("id") or "",
                                "label": item.get("label") or ""})
        except Exception:                                  # noqa: BLE001
            return []
        return out

    def set_model_choice(self, profile_id: str = "", provider: str = "",
                         model: str = "", thinking: str = ""):
        """聊天框模型弹层点选一条模型 → 落盘"选了哪条档案的哪个模型 + 它的思考档位"

        需求原话（本轮）：
          「假如服务商添加了相同的服务商，在输入框内的模型切换ui有2个同服务商
           分别的模型切换，可是他有2个同时切换而且同时改变切换状态的bug，
           应该他们都是独立的！」
          「还有切换不同模型他们的思考强度默认都是关闭的，
           每个思考强度都有单独的存储等级几的强度」

        ⚠️⚠️ 为什么要**一个后端方法**而不是前端连发两次 settings.set：
           `ai_thinking_level` 是 { "<provider>|<model>": 档位 } 这张**表**，
           前端读-改-写整张表会在另一端（浏览器模式 / 桌面端同时在线）改它时
           丢对方的条目。合并必须在服务端一处做，和 Key 分槽同一套纪律。

        参数：
          profile_id  档案 id（同厂商两条档案靠它区分；空 = 不按档案定位）
          provider    厂商 id
          model       该档案 models 里的显示名
          thinking    可选：顺手把这条模型的记忆档位写成它（省略则不动已存的档位）

        返回 `{ok, profile_id, provider, model, thinking}`；找不到档案/model 时
        `ok=False`（前端据此提示，绝不假装成功）。
        """
        try:
            from pymodels.core.ai import profiles as ai_profiles
            from pymodels.core.ai import providers as ai_providers
            manager = self.settings_manager
            if manager is None:
                return _fail("设置未就绪")
            pid = str(profile_id or "").strip().lower()
            want_model = str(model or "").strip()
            items = self._profiles_raw()
            target = None
            for item in items:
                if pid and item.get("id") == pid:
                    target = item
                    break
            if target is None and pid:
                return _fail("没有找到这条服务商档案（可能已被删除）")
            if target is None:
                return _fail("缺少服务商档案 id")
            provider = str(target.get("provider") or provider or "").strip().lower()
            allowed = [str(x) for x in (target.get("models") or [])]
            if want_model and want_model not in allowed:
                # 手输/清单变了：仍然允许（custom 本来就没清单），但要留痕
                _log("warn", "AI", "model_choices",
                     f"选中的模型不在这条档案的支持清单里：{provider}/{want_model} "
                     f"（清单={allowed}）")
            if not want_model:
                want_model = str(target.get("model") or (allowed[0] if allowed else ""))
            # ① 记住"当前用哪条档案 + 哪个模型"（平铺键仍是派生快照，供老读取方用）
            changed = []
            for key, value in (("ai_profile_id", str(target.get("id") or "")),
                               ("ai_provider", provider),
                               ("model_name", want_model)):
                if str(manager.settings.get(key, "") or "") != str(value):
                    manager.update_setting(key, value)
                    changed.append((key, value))
            # ⚠️ 本轮新增（**不是**顺手加的，是修一个必然会出现的错位）：
            #    这三个键走的是 `manager.update_setting`，**不会**发 settings-changed
            #    广播（那条在 resources.py 的 settings.set 里）—— 而前端的
            #    `aiThinkingLevel` / `aiModelIsOn` 全部是 computed，读的是前端
            #    `settings` 对象。桌面端和浏览器模式**共用同一个后端**：
            #      浏览器里换了模型 → 磁盘变了 → 桌面端那份 settings 还是旧的 →
            #      思考滑块显示 A 模型的档位、实际发请求用 B 模型（后端读磁盘）。
            #    界面与请求各说各话，正是用户最反感的那类"看着没反应/串台"。
            #    所以这里显式广播；Key 之类的敏感值一概不碰（本方法不涉密）。
            for key, value in changed:
                try:
                    self._shell.push_event("settings-changed",
                                           {"key": key, "old": None, "new": value})
                except Exception:                          # noqa: BLE001
                    pass                                   # 外壳没这个方法（预览 mock）：不影响落盘
            # ② 思考档位：给了就按**这条档案 + 这个模型**记；没给就查它自己存过的档位。
            #    需求"切换不同模型，思考强度默认都是关闭的"落在：**从没单独设过档位的
            #    模型**查表查不到 → 退回 `ai_thinking` 的默认 "off"（全新安装就是 off）。
            #    ⚠️ 本轮把 profile_id 一起带进键里（同厂商两条档案不再串档）。
            level = str(thinking or "").strip()
            target_id = str(target.get("id") or "")
            if level:
                levels = ai_providers.thinking_levels(provider, want_model) or []
                legal = [str(r.get("value")) for r in levels if isinstance(r, dict)]
                level = ai_providers.resolve_thinking_level(
                    provider, want_model, level if (not legal or level in legal) else "off")
                self._remember_thinking_level(provider, want_model, level, target_id)
            else:
                level = ai_providers.resolve_thinking_level(
                    provider, want_model,
                    self._thinking_level_for(provider, want_model, target_id))
            manager.update_setting("ai_thinking", level)
            _log("op", "AI", "model_choices",
                 f"切换模型：{provider}/{want_model} 档案={target.get('id')} 思考={level}")
            return _ok(profile_id=str(target.get("id") or ""), provider=provider,
                       model=want_model, thinking=level,
                       thinking_levels=ai_providers.thinking_levels(provider, want_model))
        except Exception as exc:                           # noqa: BLE001
            return _fail(exc)

    def provider_catalog(self):
        """设置页「添加服务商」下拉要用的厂商清单 + 每个厂商的官方模型候选

        前端据此画：厂商下拉 → 勾选官方模型（可手输补充）。
        """
        try:
            from pymodels.core.ai import providers as ai_providers
            groups = []
            # ⚠️ provider_items() 返回的是 **[(id, 显示名), ...] 元组列表**，
            #    不是 dict（这里踩过一次：写 item.get() 直接 AttributeError）。
            for item in ai_providers.provider_items():
                pid, label = (item[0], item[1]) if isinstance(item, (list, tuple)) \
                    else (str(item or ""), "")
                groups.append({
                    "provider": pid,
                    "label": label,
                    "api_base": ai_providers.default_api_base(pid),
                    "models": list(ai_providers.models_of(pid)),
                    "hint": ai_providers.provider_hint(pid),
                })
            return _ok(providers=groups)
        except Exception as exc:                           # noqa: BLE001
            return _fail(exc)

    def _find_profile(self, profile_id: str = "", provider: str = "") -> dict:
        """按 id 找一条档案（id 找不到时退回"该厂商第一条"，兼容旧前端只给 provider）"""
        pid = str(profile_id or "").strip().lower()
        items = self._profiles_raw()
        if pid:
            for item in items:
                if item.get("id") == pid:
                    return item
        want = str(provider or "").strip().lower()
        if want:
            for item in items:
                if item.get("provider") == want:
                    return item
        return {}

    def profile_key_state(self, profile_id: str = "", provider: str = ""):
        """某条**档案**的 Key 配置状态（不回传明文，只回有没有 + 尾号）

        ⚠️⚠️ 本轮新增，修用户报的「至少有一个服务商在列表中了，可是对话框里的
           模型选择还是没有任何服务商、不显示任何模型」：
           设置页弹窗读/写 Key 走的是 `settings.api_key_state` /
           `settings.set_api_key`，那两个是**厂商槽**（`api_key_enc_deepseek`）；
           而模型候选 `model_choices` 与聊天 `_credentials` 判定"这条档案有没有 Key"
           用的是 `get_profile_api_key(档案id)` = **档案槽**。
           写 A 读 B ⇒ 用户明明填了 Key，后端认为这条档案没 Key ⇒ 整组模型被过滤掉。
           这里给前端一套和后端判定**完全同口径**的档案槽入口。
        """
        try:
            manager = self.settings_manager
            if manager is None:
                return _fail("设置未就绪")
            prof = self._find_profile(profile_id, provider)
            pid = str(profile_id or "").strip().lower() or str(prof.get("id") or "")
            if not pid:
                return _fail("没有这条服务商档案")
            value = manager.get_profile_api_key(pid, provider) or ""
            return _ok(configured=bool(value), length=len(value), profile_id=pid)
        except Exception as exc:                           # noqa: BLE001
            return _fail(exc)

    def reveal_profile_key(self, profile_id: str = "", provider: str = ""):
        """显式取某条**档案**的明文 Key（弹窗"显示"按钮 / 回填输入框用）"""
        try:
            manager = self.settings_manager
            if manager is None:
                return _fail("设置未就绪")
            prof = self._find_profile(profile_id, provider)
            pid = str(profile_id or "").strip().lower() or str(prof.get("id") or "")
            if not pid:
                return _fail("没有这条服务商档案")
            return _ok(value=manager.get_profile_api_key(pid, provider) or "",
                       profile_id=pid)
        except Exception as exc:                           # noqa: BLE001
            return _fail(exc)

    def set_profile_key(self, profile_id: str = "", value: str = "", provider: str = ""):
        """把 Key 写进这条**档案**自己的槽（空值 = 清除）

        ⚠️ 与 `settings.set_api_key` 的区别只有一个，但很关键：那一个写厂商槽，
           这一个写档案槽，而"档案有没有 Key"只认档案槽（见 profile_key_state 的说明）。
        """
        try:
            manager = self.settings_manager
            if manager is None:
                return _fail("设置未就绪")
            pid = str(profile_id or "").strip().lower()
            if not pid:
                return _fail("缺少服务商档案 id")
            prof = self._find_profile(pid)
            manager.set_profile_api_key(str(value or ""), pid,
                                        provider or prof.get("provider", ""))
            saved = manager.get_profile_api_key(pid, provider or prof.get("provider", "")) or ""
            # ⚠️ 不记 Key 本身、也不记尾号（日志页可以被导出给别人看）
            _log("op", "AI", "profiles",
                 f"保存 API Key：档案={pid} "
                 + (f"已配置（{len(saved)} 位）" if saved else "已清空"))
            # 档案有 Key / 没 Key 都会改变"当前生效那条"，顺手重算一次派生键
            items = self._profiles_raw()
            current = None
            try:
                from pymodels.core.ai import profiles as ai_profiles
                current = ai_profiles.active_profile(items, self._has_profile_key,
                                       self._selected_profile_id())
            except Exception:                              # noqa: BLE001
                current = None
            if current:
                self._persist_profiles(items)
            return _ok(configured=bool(saved), length=len(saved), profile_id=pid,
                       profiles=self._profiles_payload(),
                       active_id=(current or {}).get("id", ""),
                       active_provider=(current or {}).get("provider", ""))
        except Exception as exc:                           # noqa: BLE001
            return _fail(exc)

    def _persist_profiles(self, items: list) -> None:
        """写档案数组，并把"当前生效那条"派生回旧的平铺键（单点写盘）

        ⚠️ 顺序很重要：先写 profiles（单一事实源），再按它重算平铺键。
           反了的话中途异常会留下"平铺键说 A、档案说 B"的不一致状态。
        """
        from pymodels.core.ai import profiles as ai_profiles
        manager = self.settings_manager
        if manager is None:
            return
        cleaned = ai_profiles.normalize_profiles(items)
        manager.update_setting("ai_provider_profiles", cleaned)
        # ⚠️ 打上"用户已接管档案列表"的标记：此后即使旧的平铺键还留在配置里，
        #    `_profiles_raw()` 也不会再合成出一条幽灵档案
        #    （否则用户删掉最后一条 → 列表空 → 下次读又"复活"，就是本轮自验抓到的坑）。
        manager.update_setting("ai_profiles_migrated", True)
        view = ai_profiles.build_settings_view(cleaned)
        for key, value in view.items():
            manager.update_setting(key, value)
        _log("dbg", "AI", "profiles",
             f"档案已落盘：{len(cleaned)} 条，当前 → "
             f"{view.get('ai_provider') or '(无)'} / {view.get('model_name') or '(无)'}")

    def _language(self) -> str:
        try:
            value = self._setting("language", "简体中文")
            if value and value != "跟随系统":
                return str(value)
        except Exception:
            pass
        return "简体中文"

    def _locale(self) -> str:
        """当前界面语言 → locale（zh_CN / zh_TW / en_US）
        ⚠️ 优先问 shell：设置里存跟随系统时只有 `shell.current_language()` 才知道
           用户到底是什么语言（`_language()` 那条路会硬退回简体中文）。
           `/plugin` 的悬浮提示和注入指令都按它取文案，否则英文系统下会冒出中文提示。
        """
        language = ""
        try:
            language = str(self._shell.current_language() or "")
        except Exception:
            language = ""
        if not language:
            language = self._language()
        try:
            from pymodels.core.language_manager import locale_for
            return locale_for(language)
        except Exception:
            return "zh_CN"

    def _text(self, key: str, fallback: str, module: str = "settings", **fmt) -> str:
        """按**当前界面语言**取一段后端文案（本轮多语言修复）

        ⚠️ 为什么后端也要走语言包：这几条"固定回复"（没配 Key / Key 无效 / 缺模型名）
           是**后端生成、直接落盘进气泡**的文本，前端只负责显示、翻不了。
           以前它们是硬编码中文 → 用户切到 English 后界面上仍出现
           「还没有配置 API Key。请填写<API Key> 后再聊。」
           正是用户本轮报的「语言切换为其他语言部分地方还是只有简体中文文本内容，
           包括各种地方」里**后端那一类**（前端 grep 根本查不出来，只能英文界面实扫）。

        ⚠️ 为什么不用 `manager.get_text(..., language=None)`：那条会落到
           `self.current_language`（manager 自己的状态），而"跟随系统"时只有
           `shell.current_language()` → `self._locale()` 才知道用户到底什么语言。
           所以这里**按 locale 直查** translations 表，取不到再退回 get_text，
           再取不到退回中文 fallback —— 绝不抛异常（发送是主路径，不能为文案挂掉）。
        ⚠️ 占位符用 str.replace 不用 format：文案里可能带别的 `{}`，format 会直接抛。
        ⚠️⚠️ **module 名必须是 language_manager 的 MODULES 键，不是文件名**：
           set_language.json 对应的模块键是 `"settings"`（见 language_manager.py:92），
           写成 `"set"` 会**静默查不到 → 永远退回中文 fallback**，
           整个后端本地化等于没做，而且不报错、极难发现
           （我第一版就踩了这个，是端到端测试 test_ai_error_i18n.py 的 [7] 段抓出来的）。
        """
        text = ""
        try:
            from pymodels.core import language_manager
            manager = language_manager.get_current_manager()
            if manager is not None:
                locale = self._locale()
                got = (getattr(manager, "translations", {}) or {}).get(locale, {}) \
                    .get(module, {}).get(key)
                if not (isinstance(got, str) and got.strip()):
                    try:
                        got = manager.get_text(module, key)
                    except Exception:                     # noqa: BLE001
                        got = None
                # ⚠️ LanguageManager.get_text 找不到键时**返回键名本身**（见其 docstring
                #    "找不到就返回 key"）。那不是文案，是会把 `ai_no_key_chat` 这种
                #    字符串直接显示到用户气泡里的 bug —— 必须当成"没取到"处理。
                #    （[7] 端到端测试拿错模块名跑时抓到的就是这条。）
                if isinstance(got, str) and got.strip() and got.strip() != key:
                    text = got
        except Exception:                                 # noqa: BLE001
            text = ""
        if not text:
            text = fallback
        for name, value in fmt.items():
            text = text.replace("{" + name + "}", str(value))
        return text

    # 后端网络层（client.py）的错误 kind → 语言包键
    # ⚠️ client.py 是**纯网络层**，拿不到界面语言、也不该拿（它被润色/测试连接/
    #    工具循环共用，塞语言依赖会让它难测）。所以本地化放在这一层做：
    #    按 kind 查表出**当前语言的文案**，而不是把中文原文再翻一遍。
    _ERR_KEYS = {
        "no_key": "ai_err_no_key", "no_model": "ai_err_no_model",
        "auth": "ai_err_auth", "rate": "ai_err_rate", "timeout": "ai_err_timeout",
        "network": "ai_err_network", "bad_request": "ai_err_bad_request",
        "server": "ai_err_server", "bad_json": "ai_err_bad_json",
        "config": "ai_err_config", "unknown": "ai_err_unknown",
    }

    def _localized_error(self, kind: str, message: str, status: int = 0) -> str:
        """把 client 返回的错误按界面语言重写成一句话

        ⚠️ 为什么必须做：用户本轮报「语言切换为其他语言部分地方还是只有简体中文文本内容，
           包括各种地方」—— 报错气泡也是**后端文本**，英文界面下整条 401 提示是中文，
           而且里面那句「请重新填写<API Key>」还点不动（前端只认自己语言的字面量）。
        ⚠️ 保留 client 拼的「（服务端说明：…）」尾巴：那是排查时最有用的原始信息，
           本地化只能换**我们自己写的那句话**，不能吞掉服务端回的内容。
        ⚠️ 认不出 kind / 语言包缺键 → 原样返回 client 的 message（绝不因为翻译失败
           而把报错信息弄丢）。
        """
        key = self._ERR_KEYS.get(str(kind or ""))
        if not key:
            return message
        tail = ""
        base = str(message or "")
        marker = "（服务端说明："
        at = base.find(marker)
        if at >= 0:
            tail = base[at:]
        text = self._text(key, "")
        if not text:
            return message
        # ⚠️ 占位符必须填上，否则用户会看到字面量 "{status}" / "{reason}"
        #    （我第一版就漏了这三条：network / server / unknown 的模板带占位符）。
        #    · {status}：client 的 ChatResult.status 本来就有，调用方传进来；
        #    · {reason}：client 那句中文是固定前缀「连不上服务器：」，从原文里抠出
        #      后半段即可（抠不到就整条退回原文，宁可不翻译也不能显示坏文案）。
        status = int(status or 0)
        if "{status}" in text:
            if not status:
                return message
            text = text.replace("{status}", str(status))
        if "{reason}" in text:
            prefix = "连不上服务器："
            if not base.startswith(prefix):
                return message
            text = text.replace("{reason}", base[len(prefix):].strip() or "-")
        return text + tail

    # ---------- 输入框 "/" 悬浮提示（插件制作辅助） ----------
    def chat_hints(self):
        """前端输入框上方的悬浮提示：**只在插件制作辅助开启时**才有条目
        契约（`app.js` 的 `loadAiHints()`）：
            `{ok:true, hints:[{id,label,insert,prompt,priority}], locale}`
            `{ok:false, error}` → 前端会退回它内置的兜底提示（所以失败也要回 ok=false，
            不要用"空 hints 的 ok=true"把前端兜底也一起堵死）。
        行为约定：/plugin 悬浮提示只在 GCP-AI 的**任意界面**输入 `/` 时跳出，
        且只有"插件制作辅助"**开启**时才有反应 —— 所以关着的时候必须**一条都不给**。
        """
        try:
            from .plugins import hint_payload, maker_enabled
            manager = self.settings_manager
            if not maker_enabled(manager):
                return _ok(hints=[], locale=self._locale(), enabled=False)
            locale = self._locale()
            hint = hint_payload(manager, locale)
            if not hint:
                return _fail("插件制作辅助的提示文案不可用（插件可能缺失或 lang/*.json 损坏）",
                             hints=[], locale=locale, enabled=True)
            return _ok(hints=[hint], locale=locale, enabled=True)
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "AI", "hint", f"组装 /plugin 悬浮提示失败: {exc}")
            return _fail(exc, hints=[])

    def _plugin_prompt(self, content: str):
        """这条消息是不是 `/plugin` 命令；是且插件制作辅助开着 → (是否命令, 注入指令)
        返回 `(is_plugin_command, prompt)`：
            · 插件制作辅助关着 → `(False, "")`：按**普通消息**处理
              （只有开启后输入 `/` 才会有反应）；
            · 开着但插件缺失/文案坏了 → `(False, "")`：宁可当普通消息，也不给它一个
              半截指令让模型瞎调工具。
        """
        text = str(content or "").lstrip()
        if not text.lower().startswith("/plugin"):
            return False, ""
        try:
            from .plugins import hint_payload, maker_enabled
            manager = self.settings_manager
            if not maker_enabled(manager):
                return False, ""
            hint = hint_payload(manager, self._locale())
            prompt = str((hint or {}).get("prompt") or "")
            if not prompt:
                return False, ""
            return True, prompt
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "AI", "hint", f"读取 /plugin 指令失败（按普通消息处理）: {exc}")
            return False, ""

    # ---------- 会话列表（历史面板） ----------
    @staticmethod
    def _preview(session) -> str:
        """历史卡片的一行摘要（原版 HistoryCard._preview_text 的同款语义）"""
        for message in reversed(session.messages or []):
            text = " ".join(str(message.get("content") or "").split())
            if text:
                return text[:60] + ("…" if len(text) > 60 else "")
        return ""

    def sessions(self, limit: int = 100):
        """历史对话列表：**一条 = 一个对话页**（不是一条消息）"""
        try:
            store = self.store
            rows = []
            for session in store.list_sessions()[:max(1, int(limit or 100))]:
                rows.append({
                    "id": session.id,
                    "title": session.title or "新对话",
                    "created_at": session.created_at,
                    "updated_at": session.updated_at,
                    "count": len(session.messages or []),
                    "preview": self._preview(session),
                })
            return _ok(sessions=rows, count=len(rows))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def session(self, session_id: str = ""):
        """读一个会话的全部内容；session_id 为空则返回最近一个（没有就新建）
        ⚠️ 这里也要 normalize：前端的气泡导航 ◀ n/m ▶ 靠 variants 判断，
           老会话文件没这个字段 → 不在这里补齐的话，第一次打开连"有几版"都看不出来
           （send() 只在发消息时补，只翻版本不发消息就漏了）。
        """
        try:
            from pymodels.core.ai import versions as ai_versions

            store = self.store
            target = str(session_id or "").strip()
            loaded = store.load(target) if target else None
            if loaded is None:
                if target:
                    return _fail("这个对话已经不存在了")
                loaded = store.latest_session()
            repaired = ai_versions.normalize_messages(loaded.messages)
            if repaired:
                # 补齐过的版本树顺手落盘：磁盘和界面从此一致，
                # 别让前端每次打开都要重新"修一遍"（也方便老文件自然升级成新格式）
                try:
                    store.save(loaded)
                except Exception:                         # noqa: BLE001
                    pass
            return _ok(session={"id": loaded.id, "title": loaded.title,
                                "created_at": loaded.created_at,
                                "updated_at": loaded.updated_at,
                                "messages": [self._message_view(m)
                                             for m in (loaded.messages or [])]})
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def new_session(self):
        """新建一个空会话（不落盘，直到发出第一条消息）"""
        try:
            session = self.store.new_session()
            return _ok(session={"id": session.id, "title": "", "messages": []})
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def delete_session(self, session_id: str = ""):
        """删掉一个对话页"""
        try:
            target = str(session_id or "").strip()
            if not target:
                return _fail("没有指定要删除的对话")
            ok = self.store.delete(target)
            _log("op", "AI", "session", f"删除历史对话 {target} ok={ok}")
            return _ok(deleted=bool(ok), id=target)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def clear(self):
        """清空全部历史对话（返回删掉的**对话页**数量），前端立即重新拉列表"""
        try:
            count = self.store.clear()
            _log("op", "AI", "session", f"清空历史对话 {count} 个")
            return _ok(cleared=count)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    # ---------- 发送 ----------
    def _resources(self):
        """资源清单（system 提示词里要用的；拿不到就给空列表，不影响聊天）
        ⚠️ 复用 ResourcesDomain 那份**已经加载好**的 loader（它按设置里的资源来源算路径、
           还带缓存）。不要在这里另 new 一个 ResourceLoader —— 那会再读一遍 JSON。
        """
        try:
            api = getattr(self._shell, "api", None)
            domain = getattr(api, "resources", None)
            if domain is not None:
                items = domain._all_items()
                if items:
                    return list(items)
        except Exception:
            pass
        return []

    # ---------- 工具循环（create_plugin） ----------
    def _execute_tool(self, name: str, args: dict, locale: str) -> dict:
        """执行一个 [TOOL] 调用，返回工具结果信封（**绝不抛**）
        ⚠️ 只执行 `create_plugin` 和 `list_all_resources`：内置 Agent 工具（search_resources / open_page…）
           全都依赖 py 版 Qt 主窗口对象，Web 版既没有也不该在乱动界面 ——
           模型要是凭记忆硬写一个名字过来，就明确告诉它"不支持"，让它直接回答用户。
           `list_all_resources`（需求 5）例外：纯读资源库（Web 版自己那份 loader），
           不碰任何界面，正好治"列举所有只给一两条"。
        """
        tool = str(name or "").strip()
        if tool == "create_plugin":
            try:
                from .plugins import execute_create_plugin
                return execute_create_plugin(self.settings_manager, args, locale=locale)
            except Exception as exc:                      # noqa: BLE001
                _log("err", "AI", "agent_tool", f"create_plugin 执行异常: {exc}")
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if tool == "list_all_resources":
            try:
                from pymodels.core.ai import agent_tools
                registry = agent_tools.get_registry()
                return registry.execute("list_all_resources",
                                        args if isinstance(args, dict) else {},
                                        agent=self)
            except Exception as exc:                      # noqa: BLE001
                _log("err", "AI", "agent_tool", f"list_all_resources 执行异常: {exc}")
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"ok": False,
                "error": f"本轮不支持工具 {tool}（只支持 create_plugin / "
                         f"list_all_resources）；请直接用文字回答用户。"}

    def _call_context_messages(self, session, content: str, reply_mode: str, upto: int,
                               provider_id: str, display_model: str,
                               api_model: str, thinking_row):
        """调用 _context_messages（元信息入参**只在方法支持时才传**）

        ⚠️⚠️ 为什么要探测签名而不是直接传：既有回归脚本
        （_devtest/test_ai_regen_behavior.py:93）用
        `dom._context_messages = lambda session, content, reply_mode, upto: (...)`
        把整个上下文组装换掉了 —— 多传一个新关键字参数会 TypeError，
        而 send() 的兜底 except 会把它伪装成"发送异常：TypeError ..."落盘，
        测试全红、真机没坏，排查起来极其费劲。方法本身可被子类/实例覆盖，
        所以按**当前绑定的那个**的签名判断：支持就传（走完整元信息路径），
        不支持就退回 4 参旧调用（元信息段自然缺，功能不坏）。
        """
        try:
            import inspect
            names = set(inspect.signature(self._context_messages).parameters)
        except Exception:                                 # noqa: BLE001
            names = set()
        if "provider_id" in names:
            return self._context_messages(
                session, content, reply_mode, upto,
                provider_id=provider_id, display_model=display_model,
                api_model=api_model, thinking_row=thinking_row)
        return self._context_messages(session, content, reply_mode, upto)

    def _chat_with_tools(self, messages: list, api_key: str, model: str, api_base: str,
                         locale: str = "zh_CN", allow_tools: bool = False,
                         thinking=None, max_tokens: int = 0):
        """请求模型；回答里带 [TOOL] 就执行、把结果塞回去再问一轮
        返回 `(result, rounds, created_plugins)`：
            result —— 最后一次 `ChatResult`（ok=False 表示失败，调用方照原样转成 error）；
            rounds —— 实际跑了几个工具轮（0 = 一次就答完）；
            created_plugins —— 这轮生成的插件 id（给前端决定要不要刷新插件列表）。
        ⚠️ `thinking`：本轮起上层传的是 providers.thinking_levels() 里的**档位行 dict**
            （自带 style/effort/budget，client 无需再知道服务商）。
            ⚠️⚠️ 不要给 client.chat 多传 `provider_id=`：既有回归脚本
            （_devtest/test_ai_versions.py / test_ai_regen_behavior.py）用**固定签名
            闭包 mock 掉了 client.chat**，多传一个新关键字参数会让它们 TypeError →
            整条发送被判"发送异常"，测试全红但真机没坏，极难定位。档位行 dict 路径
            本来就不需要 provider 信息（_thinking_row 直接吃 dict），字符串档位的
            兜底解析退回上一版 deepseek 风格 —— 与旧行为一致，兼容安全。
        ⚠️⚠️ `allow_tools=False`（普通聊天）时**一次就返回**：不解析、不执行任何工具。
            py 版是靠 `AgentBridge.enabled()`（GCP-AI Agent 开关）决定要不要跑工具；
            Web 版的内置 Agent 工具全都依赖 Qt 主窗口对象，只有 `/plugin` 指令
            才允许调 `create_plugin`。普通聊天里模型就算写了 `[TOOL]`，也当普通文本。
        协议与 py 版 `ui/ai_chat_panel.py：_agent_try_continue` 完全一致：
            模型 → 程序  `[TOOL] {"name": "create_plugin", "args": {...}}`
            程序 → 模型  `[TOOL_RESULT] {"tool": "...", "ok": true, "data": "..."}`
        轮数上限 `agent_tools.MAX_ROUNDS`（6）、单轮调用上限 `MAX_CALLS_PER_ROUND`（2）
        都由 `parse_tool_calls()` 负责，这里只守 MAX_ROUNDS。
        ⚠️⚠️ `scratch`（工具调用 + 结果的往返消息）**只活在这次请求里**，绝不写进
            chat_store：历史里只留"用户问 → 最终回答"，否则历史面板会被一堆 JSON 淹掉。
        ⚠️ 这是 js_api 的工作线程，同步阻塞是预期行为（前端显示"正在思考…"），
        但最多 6 轮，不会无限转。
        """
        from pymodels.core.ai import agent_tools
        from pymodels.core.ai import client as ai_client

        created = []
        scratch = []
        rounds = 0
        result = ai_client.chat(messages, api_key, model, api_base,
                                # ⚠️ 只有 wants_all 那类请求才带 max_tokens（上层算好传进来，
                                #    0 = 不发，保持旧请求体形状不变，回归脚本的 mock 签名不受影响）
                                max_tokens=int(max_tokens or 0), thinking=thinking)
        if not allow_tools:
            return result, rounds, created
        while True:
            if not getattr(result, "ok", False):
                return result, rounds, created
            content = str(getattr(result, "content", "") or "")
            if rounds >= int(getattr(agent_tools, "MAX_ROUNDS", 6)):
                _log("warn", "AI", "agent",
                     f"工具轮数到达上限 {getattr(agent_tools, 'MAX_ROUNDS', 6)}，按普通回答收尾")
                return result, rounds, created
            try:
                calls, _cleaned = agent_tools.parse_tool_calls(content)
            except Exception as exc:                      # noqa: BLE001
                _log("warn", "AI", "agent", f"解析工具调用失败（按普通回答处理）: {exc}")
                return result, rounds, created
            if not calls:
                return result, rounds, created

            results = []
            for call in calls:
                name = str(call.get("name") or "")
                args = call.get("args") if isinstance(call.get("args"), dict) else {}
                try:
                    outcome = self._execute_tool(name, args, locale)
                except Exception as exc:                  # noqa: BLE001
                    outcome = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                if name == "create_plugin" and outcome.get("ok"):
                    created_id = str((outcome.get("data") or {}).get("id") or "")
                    if created_id:
                        created.append(created_id)
                _log("op", "AI", "agent_tool",
                     f"工具 {name} ok={bool(outcome.get('ok'))} "
                     f"args={list(args.keys())[:6]}")
                try:
                    results.append(agent_tools.format_result(name, outcome))
                except Exception:                         # noqa: BLE001
                    results.append(f"{getattr(agent_tools, 'RESULT_TAG', '[TOOL_RESULT]')} "
                                   f'{{"tool":"{name}","ok":false}}')
            scratch.append({"role": "assistant", "content": content})
            scratch.append({"role": "user", "content": "\n".join(results)})
            rounds += 1
            result = ai_client.chat(messages + scratch, api_key, model, api_base,
                                    thinking=thinking)

    @staticmethod
    def _clean_reply(text: str) -> str:
        """最终回答里如果还残留 [TOOL] 标记就抠掉（工具轮数到上限时会这样）
        ⚠️ 不能写 `cleaned or raw`：模型整条回答只有一个 `[TOOL] {...}` 时，
           `parse_tool_calls` 抠出来的 cleaned 恰恰是**空串**，那样又会把原始标记fallback 回来。
           这里改成"认出了调用就用 cleaned（哪怕为空）"。
        """
        raw = str(text or "")
        if "[TOOL]" not in raw:
            return raw.strip()
        try:
            from pymodels.core.ai import agent_tools
            calls, cleaned = agent_tools.parse_tool_calls(raw)
            if calls:
                return str(cleaned or "").strip()
            return raw.strip()
        except Exception:
            return raw.strip()

    def _persist_message(self, store, session, role: str, content: str,
                         extra: dict = None) -> bool:
        """追加一条消息并**确认真的写到磁盘**，返回是否成功
        ⚠️ 为什么要多此一举：`ChatStore.append()` 内部有 `self.save(session)` 但**丢掉了
           返回值**（它永远 return True）。于是"目录不可写 / 磁盘满 / 权限不够"这类失败
           在调用方完全看不出来 —— 用户以为聊过的话丢了，日志里也是干净的。
           这里补两层确认：① append 之后检查会话文件是否真的存在；② 不存在就再
           `store.save()` 一次；③ 仍然没有 → 记 err 日志并让上层把 persisted:false 告诉前端。
        ⚠️ `extra`：报错气泡要带 `{"error": True, "kind": ...}`，历史面板才能原样还原。
        """
        try:
            accepted = store.append(session, role, content, persist=True, extra=extra)
        except Exception as exc:                          # noqa: BLE001
            _log("err", "AI", "chat", f"追加 {role} 消息异常: {type(exc).__name__}: {exc}")
            return False
        if not accepted:
            _log("warn", "AI", "chat", f"追加 {role} 消息被拒绝（内容为空或角色非法）")
            return False
        try:
            path = store.path_of(session.id)
        except Exception as exc:                          # noqa: BLE001
            _log("err", "AI", "chat", f"取会话文件路径失败: {exc}")
            return False
        try:
            if not os.path.isfile(path):
                store.save(session)                    # 兜底再写一次（原子写，幂等）
            if os.path.isfile(path):
                return True
        except Exception as exc:                          # noqa: BLE001
            _log("err", "AI", "chat", f"保存会话失败: {type(exc).__name__}: {exc}")
            return False
        _log("err", "AI", "chat",
             f"保存会话失败：{path} 不存在（会话目录可能不可写）")
        return False

    def _describe_config(self, api_base: str = "", model: str = "",
                         key_tail: str = "") -> str:
        """失败提示里附一行“当时用的是哪套配置”，用户一眼能看出 Key/模型/地址对不对。
        只显示 Key 尾号，绝不回传明文。
        """
        parts = []
        try:
            from pymodels.core.ai import providers as ai_providers
            pid = str(self._setting("ai_provider", "deepseek") or "deepseek").strip().lower()
            parts.append("服务商："
                         + (ai_providers.provider_label(pid)
                            if ai_providers.get_provider(pid) else pid))
        except Exception:                                # noqa: BLE001
            parts.append("服务商：?")
        if model:
            parts.append(f"模型：{model}")
        if api_base:
            parts.append(f"接口：{api_base}")
        if key_tail:
            parts.append(f"Key 尾号：{key_tail}")
        return "，".join(parts)

    # ================= 版本树 / 流式的公共底座 =================
    def _prepare_send(self, store, session, content: str, resend: bool,
                      user_index, assistant_index):
        """按「重新生成 / 编辑后重发 / 普通发送」三种语义把**用户那一侧**的版本改动做完并落盘。

        返回 `{mode, upto, assistant_index}`；出错时返回 `{failed: <_fail 信封>}`。
        send() 与 send_stream() 都必须走这里 —— 版本语义只写一遍，
        两条链路各写一份迟早会歪（歪的表现就是"兄弟版本混进上下文"，很难查）。

        `upto` = 参与上下文的最后一条消息的下标 + 1（见 _context_messages）。
        """
        from pymodels.core.ai import versions as ai_versions

        # 载入后先把版本树补齐（老会话文件没有这些字段 → 全当"只有 v1"）；
        # 真的补过东西就顺手落盘，省得每次读都要再修一遍。
        if ai_versions.normalize_messages(session.messages):
            self._persist_session(store, session)

        messages = session.messages
        ui = self._to_index(user_index)
        ai_idx = self._to_index(assistant_index)
        edit = bool(resend) and ui is not None and \
            0 <= ui < len(messages) and str(messages[ui].get("role") or "") == "user"
        regen = bool(resend) and not edit

        # 重新生成时"旧回答"落在哪一条：前端给的下标优先，没给就退到最后一条 assistant
        if regen and ai_idx is None:
            for probe in range(len(messages) - 1, -1, -1):
                if str(messages[probe].get("role") or "") == "assistant":
                    ai_idx = probe
                    break
        # 下标越界 / 那条已经不是 assistant（切过分支、或会话被别的窗口改过）：
        # 一律当"没有可就地翻版的老回答"→ 走新增回答，绝不拿坏下标去改数据。
        if regen and ai_idx is not None and \
                not (0 <= ai_idx < len(messages)
                     and str(messages[ai_idx].get("role") or "") == "assistant"):
            ai_idx = None

        # ① 用户消息**先落盘**（说过的话不能丢；即使后面发不出去也要留在历史里）
        if edit:
            # 编辑后重发：这条用户消息**多一个新版本**，它下面的 AI 回复整段换成新分支
            # （旧的那串先存进 branch_suffixes[旧版本]，翻回旧版本还看得见）
            if not ai_versions.apply_user_edit(messages, ui, content):
                return {"failed": _fail(
                    "这条消息已经不在当前对话里了（可能刚翻过版本），请重试",
                    kind="stale_index", session_id=session.id,
                    session=self._dump(session))}
            user_saved = self._persist_session(store, session)
            upto = ui + 1
        elif regen:
            # 重新生成：提问已经在磁盘上，**不重复落**用户消息（否则历史里两条一样的提问）
            user_saved = os.path.isfile(store.path_of(session.id))
            if not user_saved:
                user_saved = self._persist_message(store, session, "user", content)
            # 上下文只到"这条提问"为止：旧回答不进上下文（它只是另一个版本）
            upto = ai_idx if ai_idx is not None else len(messages)
        else:
            user_saved = self._persist_user_message(store, session, content)
            upto = len(messages)
        if not user_saved:
            return {"failed": _fail(
                "对话没能保存到磁盘（检查会话目录是否可写）",
                kind="storage", session_id=session.id,
                session=self._dump(session), persisted=False)}
        return {"mode": "edit" if edit else ("regen" if regen else "new"),
                "upto": upto, "assistant_index": ai_idx}

    @staticmethod
    def _to_index(value):
        """把前端传来的下标归一成 int 或 None（pywebview 可能给字符串/浮点/None）"""
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _ensure_title(self, session, content: str) -> None:
        """第一条用户消息顺便当标题（自己往 messages 里塞消息时要补上 store.append 的这一步）"""
        if str(session.title or ""):
            return
        try:
            session.title = self.store._make_title(content)
        except Exception:                                 # noqa: BLE001
            session.title = "新对话"

    def _request_max_tokens(self, content: str = "") -> int:
        """这次请求要发的 max_tokens（0 = 不表态，沿旧行为）。

        ⚠️ 本轮新增：用户实测「列举所有资源」仍然**只列出一半就停**。
        清单本身已经全量进上下文（prompt.build_resource_catalog 那条修好了），
        剩下的截断发生在**输出侧**：不少网关不给 max_tokens 时有自己的默认上限
        （DeepSeek 思考模型默认输出预算也不大），52 条 × 每条一行 + 简介很容易撞线。
        所以判定 wants_all 时主动把输出预算垫高到"装得下 N 条"：
            N×60 token，夹在 [2048, 8192]（再高很多网关直接 400，反而全毁）。
        其它情况一律返回 0（保持"不表态"，别改变现有请求体形状）。
        ⚠️ 判定/条数**函数内部自己取**（调用点只传用户那句话）：send/send_stream
           两条路径的局部变量不一样，把 want_all 传来传去迟早出现"一条改了另一条没改"。
        """
        try:
            from pymodels.core.ai import prompt as ai_prompt
            if not ai_prompt.wants_all_resources(str(content or "")):
                return 0
        except Exception:                                 # noqa: BLE001
            return 0
        total = 0
        try:
            total = len(self._resources())
        except Exception:                                 # noqa: BLE001
            total = 0
        need = max(2048, min(8192, int(max(1, total)) * 60))
        try:
            cap = self._profile_max_token()
            if cap > 0:
                need = min(8192, max(need, cap))
        except Exception:                                 # noqa: BLE001
            pass
        return need

    def _profile_max_token(self) -> int:
        """当前生效服务商档案的「token 限制输出」上限（0 = 不限）

        ⚠️ 本轮设置页重构：token 限制从**全局**一个值改成**每个服务商独立**，
           而且**默认关闭**（用户原话：「token限制输出默认是关闭的」）。
           所以只有该档案 `limit_token=True` 才返回它的 max_token，
           关着就返回 0 = 不表态（发给网关的请求体里根本不带 max_tokens）。
           老配置兼容：没有档案时退回旧的 `limit_token_output` + `max_token` 两键。
        """
        try:
            from pymodels.core.ai import profiles as ai_profiles
            items = self._profiles_raw()
            current = ai_profiles.active_profile(items, self._has_profile_key,
                                       self._selected_profile_id())
            if current:
                if not current.get("limit_token"):
                    return 0
                return int(current.get("max_token") or 0)
        except Exception:                                 # noqa: BLE001
            pass
        try:
            if bool(self._setting("limit_token_output", False)):
                return int(str(self._setting("max_token", "") or 0) or 0)
        except Exception:                                 # noqa: BLE001
            pass
        return 0

    def _effective_base(self, provider: str = "") -> str:
        """某个服务商**当前实际生效**的接口地址（全站唯一口径）。

        读取顺序（和 _credentials 完全一致，谁都不许自己拼）：
          ① `api_base_<pid>` 分槽值（用户在设置页为该服务商显式存过的地址）；
          ② custom（自定义/中转）没有槽值 → 退回旧全局 `api_base`（老配置就一个框）；
          ③ 内置服务商 → 官方默认地址 `providers.default_api_base(pid)`。

        ⚠️ 本轮新增这个函数就是为了根治"串台"：以前 4 个调用点（聊天 / 润色 /
        测试连接 / 诊断快照）各读各的全局 `api_base`，切了服务商/模型后
        地址还停在上一家（用户实测：选 DeepSeek 模型却打到 openai 端点）。
        所有读取现在只走这里。
        """
        manager = self.settings_manager
        pid = str(provider or self._setting("ai_provider", "deepseek")
                  or "deepseek").strip().lower()
        base = ""
        if manager is not None:
            try:
                base = manager.get_api_base(pid) or ""
            except Exception:                             # noqa: BLE001
                base = ""
        if not base and pid == "custom":
            base = str(self._setting("api_base", "") or "").strip()
        if not base:
            try:
                from pymodels.core.ai import providers as ai_providers
                base = ai_providers.default_api_base(pid) or base
            except Exception:                             # noqa: BLE001
                pass
        return base

    def _credentials(self):
        """读设置里的 Key / 模型 / 接口地址（send 与 send_stream 共用，口径完全一致）
        返回 `{api_key, model(显示名), api_model(发给 API 的名字), api_base, missing}`。
        ⚠️ 模型名以用户设置/下拉为准，程序不替用户改"值"；但发送前必须把界面显示名解析成
           官方 API 模型名，否则服务端 400。
        ⚠️⚠️ 本轮修复「服务商串台」大 bug（用户实测：设置服务商=openai，输入框选了
           DeepSeek 的模型聊天，报错却是「服务商 DeepSeek，接口 https://api.openai.com/v1」）：
           旧写法 Key 用 `get_api_key()`（不带 provider，靠 ai_provider 兜底恰好是对的），
           但 **api_base 读的是全局单槽** `api_base` —— 那是"上一次在设置页保存时所属
           服务商"的地址。模型弹层选 DeepSeek 会把 ai_provider/model_name 都改掉，
           可**没人改 api_base**，于是 DeepSeek 的请求打到 openai 端点。
           现在三件套（Key / 地址 / 尾号）**全部显式带 provider**，地址走
           `settings_manager.get_api_base(pid)` 的分槽口径：
             分槽 api_base_<pid>（用户为该服务商显式设过）
             → custom：退回旧全局 api_base（中转地址本来就只有一个框）
             → 内置服务商：providers.default_api_base(pid) 官方地址。
        """
        manager = self.settings_manager
        # ⚠️⚠️ 本轮（设置页服务商卡片重构）核心修复：
        #   用户实测「我去设置搞了一个新厂商的apikey保存后，他会给我直接默认选择模型为
        #   刚刚厂商的第一个模型」——
        #   根因：以前 model_name / ai_provider 是**全局平铺键**，设置页一保存新厂商
        #   就把它们覆盖掉，聊天随即"偷偷换了模型"。
        #   现在：**聊天优先用当前档案**（有序数组里第一条有 Key 的），
        #   平铺键只是它派生出来的快照。只有完全没有档案（老配置）才退回平铺键。
        #   —— 这正是"设置里改配置不该改掉我已选模型"的正解。
        profile = {}
        try:
            from pymodels.core.ai import profiles as ai_profiles
            profile = ai_profiles.active_profile(
                self._profiles_raw(), self._has_profile_key,
                self._selected_profile_id()) or {}
        except Exception:                                 # noqa: BLE001
            profile = {}
        # ⚠️ 本轮（档案按 id 独立后）Key 必须读**这条档案自己的槽**：
        #    同厂商两条档案各有各的 Key，按厂商读会拿错（改一条影响另一条）。
        prof_id = profile.get("id") or ""
        provider = str(profile.get("provider")
                       or self._setting("ai_provider", "deepseek")
                       or "deepseek").strip().lower()
        # 模型名：档案的 model（真实调用那个）优先；没有才退回平铺 model_name
        # ⚠️ 本轮补充：档案里 `model` 恒等于 models[0]（normalize_profile 保证），
        #    但用户可以在弹层里选这条档案的**第二个**模型 —— 那时必须用他选的那个，
        #    否则"选了 Pro 实际还在调 Flash"。判定口径：平铺 model_name **在这条档案的
        #    models 清单里** 才算数（不在 = 属于别的档案/已被删，不能拿过来用）。
        display_model = str(profile.get("model")
                            or self._setting("model_name", "") or "").strip()
        try:
            picked = str(self._setting("model_name", "") or "").strip()
            allowed = [str(x) for x in (profile.get("models") or [])]
            if picked and allowed and picked in allowed:
                display_model = picked
        except Exception:                                 # noqa: BLE001
            pass
        api_model = display_model
        try:
            from pymodels.core.ai import providers as ai_providers
            # ⚠️ 用「支持模型」清单里的名字去解析官方 API 名 —— 档案的 label 只是备注，
            #    **绝不参与调用**（用户原话：模型名称只是标签，不影响真实调用）。
            api_model = ai_providers.resolve_api_model(provider, display_model)
        except Exception:                                 # noqa: BLE001
            pass
        api_key = ""
        if manager is not None:
            try:
                if prof_id:
                    api_key = manager.get_profile_api_key(prof_id, provider) or ""
                else:
                    # 没有档案（老配置直接跑）→ 退回厂商槽
                    api_key = manager.get_api_key(provider) or ""
            except Exception as exc:                      # noqa: BLE001
                _log("warn", "AI", "chat", f"读取 API Key 失败: {exc}")
                api_key = ""
        # 地址：档案里存的那份优先（每条档案独立），否则走分槽/官方默认
        api_base = str(profile.get("api_base") or "").strip() or self._effective_base(provider)
        missing = []
        if not str(api_key).strip():
            missing.append("API Key")
        if not api_model:
            missing.append("模型名称")
        key_tail = ""
        if manager is not None:
            try:
                key_tail = (manager.profile_key_tail(prof_id, provider) if prof_id
                            else manager.key_tail(provider)) or ""
            except Exception:                             # noqa: BLE001
                key_tail = ""
        return {"api_key": api_key, "model": display_model, "api_model": api_model,
                "provider": provider, "profile_id": prof_id,
                "api_base": api_base, "missing": missing,
                "key_tail": key_tail}

    def _thinking_state(self, provider_id: str = "", display_model: str = "",
                        profile_id: str = ""):
        """这次请求的思考**档位行** —— 返回 providers.thinking_levels() 里的一行 dict，
        或 None（模型不支持思考）

        需求原话（本轮）：「把思考开关改为对接官方API的多档位滑动强度而不是只有开和关
        （类似Codex）」+ 上一轮的「默认思考都为关闭」。
        落成的规则（顺序固定）：
          ① 模型**不支持**思考 → 返回 None：连各家思考参数都不发。
             老网关/中转对不认识的参数会 400，"不支持就别发"是唯一安全的做法；
             界面上也因此不画滑块（见 model_choices 的 thinking_levels 只有 off 一档）。
          ② 支持思考 → 读设置里的 `ai_thinking` 并**归一成档位**（providers.normalize_thinking
             兼容旧的布尔配置：False→"off"、True→"medium"），默认 off；
             再用 resolve_thinking_level 修正成**当前模型官方表里真实存在的 value**
             （各家档位不同：从 DeepSeek 的 max 切到 Gemini 会就近取档）。
          ③ ⚠️ 本轮起返回的是**档位行 dict**（{value,label,effort,style,...}）：
             各家请求体字段不同（reasoning_effort / thinking{type} / enable_thinking /
             thinking_config / budget），client._thinking_params 按 style 分发。
             旧调用方拿字符串也兼容（client 会按 provider_id/model 现查表）。
          ④ 任何异常 → None（宁可不思考，也不能把思考混进正文，也不能发坏请求体）。
        """
        try:
            from pymodels.core.ai import providers as ai_providers
            pid = str(provider_id or self._setting("ai_provider", "deepseek")
                      or "deepseek").strip().lower()
            name = str(display_model or self._setting("model_name", "") or "")
            if not ai_providers.model_supports_thinking(pid, name):
                return None
            level = ai_providers.resolve_thinking_level(
                pid, name, self._thinking_level_for(pid, name, profile_id))
            for row in ai_providers.thinking_levels(pid, name):
                if row.get("value") == level:
                    return row
            return dict(ai_providers.THINKING_LEVELS[0])
        except Exception:                                 # noqa: BLE001
            return None

    @staticmethod
    def _thinking_level_of(thinking_row) -> str:
        """档位行 → 规范值字符串（给落盘/日志/提示词用；None → ""）"""
        if isinstance(thinking_row, dict):
            return str(thinking_row.get("value") or "off")
        if thinking_row is None:
            return ""
        return str(thinking_row)

    def _thinking_display(self, thinking_row, provider_id: str = "",
                          model_name: str = "") -> str:
        """「当前思考档位」的中文说明（需求 1：元信息段要写清档位，含各家官方名）。
        认不出/不支持就老实说"该模型不支持思考"，别让 AI 瞎答。"""
        try:
            if thinking_row is None:
                return "该模型不支持思考（未发送任何思考参数）"
            if isinstance(thinking_row, dict):
                value = str(thinking_row.get("value") or "off")
                label = str(thinking_row.get("label") or "")
            else:
                value = str(thinking_row)
                label = ""
            if value == "off":
                return "关闭（off）—— 未开启深度思考，也不会输出思考内容"
            return (f"{label or value}（发给 API 的值：{value}"
                    f"，模型族 {provider_id or '未知'} / {model_name or '未知'} 的官方档位）")
        except Exception:                                 # noqa: BLE001
            return "未知"

    @staticmethod
    def _thinking_open(thinking) -> bool:
        """档位是否"开着"（有思考就该显示折叠块 / 落盘 reasoning）

        ⚠️ 以前到处写 `thinking is True`，改成档位字符串后 `is True` 会**永远为假**，
           思考开着也看不见 —— 统一走这里（None/off = 关，low/medium/high = 开）。
           本轮起 thinking 可能是**档位行 dict**（各家 style 不同），由 client 统一判定。
        """
        try:
            from pymodels.core.ai import client as ai_client
            return bool(ai_client._thinking_on(thinking))
        except Exception:                                 # noqa: BLE001
            return False

    def model_choices(self):
        """输入框右下角「模型切换 UI」的数据源（只列**已填 API Key** 的服务商）

        需求原话：「未填写 APIkey 的模型不显示」。
        ⚠️ 为什么在后端过滤而不是前端猜：Key 是按服务商分槽 DPAPI 加密存的
           （settings_manager.get_api_key(provider)），前端**拿不到也不该拿到**明文，
           只能由后端读、只回"有没有 + 尾号"。前端自己猜必然出错。

        返回：`{ok, groups:[{provider,label,api_base,has_key,key_tail,
                             models:[{name,api_model,supports_thinking}]}],
                current:{provider,model,supports_thinking,thinking},
                thinking_default:false, no_key_hint:...}`
        · `groups` 已按 Key 过滤（没 Key 的服务商整组不出现）；
        · `current` 是当前生效的选择（万一用户设置里的模型所属服务商没 Key，
          也照样带出来，否则下拉框会显示成"空白/第一项"，用户以为设置被改了）；
        · `thinking_default` 恒为 False（需求"默认思考都为关闭"），给前端做
          "换了模型就把思考拨回关闭"的依据。
        """
        try:
            from pymodels.core.ai import providers as ai_providers
            from pymodels.core.ai import profiles as ai_profiles
            manager = self.settings_manager
            # ⚠️⚠️ 本轮（设置页服务商卡片重构）：模型弹层的数据源改成**档案**，
            #    不再用"内置厂商清单 × 有没有 Key"现推。
            #    为什么必须改：用户现在可以自定义「支持模型」（官方清单勾选 + 手输补充），
            #    弹层里当然只能列出**他勾过的那几个**；继续按 providers.model_catalog_all()
            #    推会列出该厂商全部型号，选到没勾的那个 = 保存的配置形同虚设。
            #    同时 `_credentials()` 也读档案，两边从此是**同一份事实源**。
            groups = []
            profiles_all = self._profiles_raw()
            for profile in profiles_all:
                pid = profile["provider"]
                # ⚠️ Key 按**档案**判定（同厂商两条各有各的 Key，一条没填不影响另一条）
                if not self._has_profile_key(profile):
                    continue                              # 未填 Key 的档案整组不显示
                models = []
                for name in (profile.get("models") or []):
                    models.append({
                        "name": name,
                        "api_model": ai_providers.resolve_api_model(pid, name),
                        "supports_thinking": bool(
                            ai_providers.model_supports_thinking(pid, name)),
                        "thinking_levels": ai_providers.thinking_levels(pid, name),
                    })
                if not models and pid != ai_providers.PROVIDER_CUSTOM:
                    continue
                groups.append({
                    # ⚠️ 本轮新增 id：同厂商两条档案要靠它区分（前端 v-for 的 key
                    #    也必须用它，用 provider 会撞 key、Vue 会复用错节点）。
                    "id": profile.get("id", ""),
                    "provider": pid,
                    # 分组标题用**厂商显示名**（不是档案 label —— 那是"模型名称"标签，
                    # 两者语义不同：label 是这条档案的备注名，分组标题是厂商）。
                    "label": ai_providers.provider_display(pid) or pid,
                    "api_base": profile.get("api_base") or "",
                    "has_key": True, "key_tail": self._profile_key_tail(profile),
                    # 档案的"模型名称"标签：前端弹层可以拿它当分组副标题/当前项显示
                    "profile_label": profile.get("label") or "",
                    "models": models,
                })
            # 当前生效那条（和 _credentials 完全同口径：数组顺序 + 档案 Key 可用性）
            current_profile = ai_profiles.active_profile(
                profiles_all, self._has_profile_key, self._selected_profile_id()) or {}
            cur_provider = str(current_profile.get("provider")
                               or self._setting("ai_provider", "deepseek")
                               or "deepseek").strip().lower()
            cur_model = str(current_profile.get("model")
                            or self._setting("model_name", "") or "").strip()
            # ⚠️ 本轮修正（与 _credentials 里同一处口径对齐）：档案的 `model` 恒等于
            #    models[0]（normalize_profile 保证），但用户可以在弹层里选这条档案的
            #    **第二个**模型。旧写法这里直接拿 models[0] 去查档位，于是
            #    "选了 Pro 却显示/使用 Flash 的思考档位" —— 也是用户报的
            #    "同厂商两个模型设置相通"的一种表现。
            #    判定：平铺 model_name **在这条档案的 models 清单里**才算数。
            try:
                picked = str(self._setting("model_name", "") or "").strip()
                allowed = [str(x) for x in (current_profile.get("models") or [])]
                if picked and allowed and picked in allowed:
                    cur_model = picked
            except Exception:                             # noqa: BLE001
                pass
            # 思考档位：修正成当前模型官方表里真实存在的 value（各家档位不同）
            # ⚠️⚠️ 本轮必须带上**档案 id**（用户原话：「同厂商两个模型的思考强度 ui
            #    是相通的，可是我需要每个模型都独立存储」）：不带 id 时读的是
            #    `provider|model` 这条旧键，同厂商两条档案列同名模型就共用档位。
            cur_level = ai_providers.resolve_thinking_level(
                cur_provider, cur_model,
                self._thinking_level_for(cur_provider, cur_model,
                                         str(current_profile.get("id") or "")))
            current = {
                "id": current_profile.get("id", ""),
                "provider": cur_provider,
                "model": cur_model,
                "supports_thinking": bool(
                    ai_providers.model_supports_thinking(cur_provider, cur_model)),
                # ⚠️ `thinking` 是**档位规范值**（各家官方表里的 value：off/low/medium/
                #    high/minimal/max/on…），不再是布尔。旧配置里的 True/False 由
                #    normalize_thinking + resolve_thinking_level 兜掉并修正到当前模型
                #    真实存在的档位，前端拿到的值一定能在 thinking_levels 表里找到。
                "thinking": cur_level,
                "thinking_levels": ai_providers.thinking_levels(cur_provider, cur_model),
            }
            # 需求 3：回复语言下拉数据源 —— 前端（ai-frontend）据此画
            # 「设置 → GCP-AI → 回复语言」下拉；[{value,label}...]，value 存进
            # 设置项 ai_reply_language，label 跟随界面语言（三语 key ai_reply_lang_*）。
            from pymodels.core.ai import prompt as ai_prompt
            cur_reply_lang = str(self._setting("ai_reply_language", "auto") or "auto")
            return _ok(groups=groups, current=current, thinking_default="off",
                       thinking_levels=ai_providers.THINKING_LEVELS,
                       reply_languages=ai_prompt.reply_language_choices(),
                       reply_language=cur_reply_lang)
        except Exception as exc:                          # noqa: BLE001
            _log("err", "AI", "model_choices", f"取模型清单失败: {exc}")
            return _fail(exc)

    def _runtime_meta(self, provider_id: str = "", display_model: str = "",
                      api_model: str = "", thinking_row=None) -> str:
        """「运行时元信息」段（需求 1/2/6）：模型身份 + 当前时间 + 回复语言 +
        思考档位 + 能力清单（可用模型/已启用功能/已启用插件）。

        ⚠️ 每一项都独立 try：某项拿不到（异常）降级为"未知/未开启"并写日志，
           绝不让发送主链路抛错 —— 这一段只是"告知"，缺一段提示词不致命，
           抛异常整条消息发不出去才是事故。
        """
        try:
            from pymodels.core.ai import prompt as ai_prompt
            from pymodels.core.ai import providers as ai_providers
            from pymodels.core.ai import capabilities as ai_caps

            manager = self.settings_manager
            provider_label = ""
            try:
                provider_label = ai_providers.provider_display(provider_id)
                if provider_id == "custom" or not provider_label:
                    # custom 没有显示名：拿**实际生效地址**给用户认（串台修复：
                    # 以前这里读全局 api_base，快照里显示的可能是上一家的端点）
                    base = self._effective_base(provider_id)
                    if base:
                        provider_label = f"自定义接口（{base}）"
            except Exception:                             # noqa: BLE001
                provider_label = provider_id or ""

            # ② 已启用功能（含联网判定：本程序当前没有联网工具/联网插件开启）
            try:
                settings_dict = dict(getattr(manager, "settings", {}) or {}) \
                    if manager is not None else {}
            except Exception:                             # noqa: BLE001
                settings_dict = {}
            features = ai_caps.enabled_features_text(
                settings_dict, resource_count=len(self._resources()))

            # ③ 已启用插件：动态枚举（core 不认识 desktop 层，优先走 plugins_dirs 桥）
            plugins_text = ai_caps.enabled_plugins_text(self._locale())

            # 联网能力：扫描"启用中且带联网工具"的插件目前不可判定，
            # 保守口径：只要 Agent 或联网类插件没开就明确说"不具备"。
            network = ""
            try:
                if bool(settings_dict.get("gcp_ai_agent_enabled", False)):
                    # Agent 开着时也不虚构联网：本程序内置工具没有联网项
                    network = ""
            except Exception:                             # noqa: BLE001
                pass

            # ① 可用（已配 Key）的服务商与模型 —— 与 model_choices 同一 has_key 口径
            models_text = ai_caps.available_models_text(manager)

            thinking_text = self._thinking_display(thinking_row, provider_id,
                                                   display_model)
            reply_language = str(self._setting("ai_reply_language", "auto"))
            return ai_prompt.build_runtime_meta(
                provider_label=provider_label,
                display_model=display_model,
                api_model=api_model,
                reply_language=reply_language,
                thinking_text=thinking_text,
                features_text=features,
                models_text=models_text,
                plugins_text=plugins_text,
            )
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "AI", "meta", f"构建运行时元信息失败（本次不带该段）: {exc}")
            return ""

    def _context_messages(self, session, content: str, reply_mode: str, upto: int,
                          provider_id: str = "", display_model: str = "",
                          api_model: str = "", thinking_row=None):
        """按「当前选中的版本」组装发给模型的上下文
        ⚠️⚠️ 关键约定：`session.messages` **永远就是当前显示的那一条线**
           （core/ai/versions.py 的扁平镜像结构：切用户版本时整段替换 messages[index+1:]，
           AI 翻页只换 content 镜像）。所以这里只要"截到 upto"就天然不会把兄弟版本混进来，
           绝不要在这里再去猜 variants。
        `upto` = 参与上下文的最后一条消息的**下标 + 1**（重新生成时 = 那条旧回答的位置，
        也就是"旧回答不进上下文"）。
        provider_id/display_model/api_model/thinking_row：需求 1/2/6 的元信息入参
        （可选，不传元信息段就缺 —— 兼容旧调用方与测试 mock）。
        """
        from pymodels.core.ai import prompt as ai_prompt

        rounds = 0
        try:
            rounds = int(self._setting("ai_context_rounds", 0) or 0)
        except Exception:
            rounds = 0
        mode = str(reply_mode or self._setting("ai_reply_mode", "standard") or "standard")
        window = session.messages[:max(0, upto)] if upto is not None else list(session.messages)
        try:
            keyword = ai_prompt.extract_keyword(content)
        except Exception:
            keyword = ""
        # 需求 5：意图是"列举/全部/有哪些/多少个"→ 完整清单进上下文（不截断）
        try:
            want_all = ai_prompt.wants_all_resources(content)
        except Exception:                                 # noqa: BLE001
            want_all = False
        # 需求 3：回复语言（后端拼强制指令，前端只管存设置值）
        try:
            reply_language = str(self._setting("ai_reply_language", "auto") or "auto")
        except Exception:                                 # noqa: BLE001
            reply_language = "auto"
        # 需求 1/2/6：运行时元信息（构建失败返回空串，主链路照常）
        meta = ""
        if display_model or provider_id:
            meta = self._runtime_meta(provider_id, display_model, api_model,
                                      thinking_row)
        messages = ai_prompt.build_messages(
            window, self._resources(), self._language(),
            context_rounds=rounds, keyword=keyword, mode=mode,
            meta=meta, want_all=want_all, reply_language=reply_language)

        # `/plugin`：把插件制作辅助的 Skill 指令追加到 system 末尾
        # ⚠️ 只改**第一条 system**（build_messages 保证 system 永远第一条且只有一条）：
        #    有些网关/模型对多 system 的处理不一致，py 版也是"追加到同一条 system"。
        locale = self._locale()
        plugin_command, plugin_prompt = self._plugin_prompt(content)
        if plugin_prompt:
            if messages and str(messages[0].get("role")) == "system":
                messages[0]["content"] = (str(messages[0].get("content") or "")
                                          + "\n\n" + plugin_prompt)
            else:
                messages.insert(0, {"role": "system", "content": plugin_prompt})
            _log("info", "AI", "hint",
                 f"用户输入 /plugin：已注入插件制作辅助指令（{len(plugin_prompt)} 字）")
        return messages, plugin_command, locale

    def _persist_assistant(self, store, session, content: str, regenerate_at=None,
                           extra: dict = None) -> bool:
        """把这一轮的回答写进会话：重新生成 = 给那条回答**追加一个版本**（并把它的旧下游
        整段让位、按版本存起来），正常回答 = 新增一条（自带 v1 的版本字段，前端才能一上来就
        显示导航）。

        ⚠️ `regenerate_at` 必须是**当前** messages 的绝对下标（切分支会让下标漂移）。
        ⚠️⚠️ 重新生成必须走 `versions.regenerate_variant`（先存旧下游 → 追加新版本 →
           新版本格子置 None → `del messages[i+1:]`）。**先存后取**的顺序不能反：
           反了的话旧版本的下游整段丢失（用户翻回旧版什么都看不到）。
           这就是用户报的「重新生成后下面的内容属于所有版、全都不消失」的另一半修复 ——
           落盘后的会话里，被重生那条下面**本来就该是空的**（旧下游按版本挂在
           branch_suffixes 里），前端拿 done 里的 session 重建才不会让旧内容又冒出来。
        ⚠️ 落盘前先 sync_branches：每条消息（user 与 assistant 都要）那一格的后继要在
           "这一轮又多了一条回答/版本"之后刷新，否则重开程序翻回该版本，
           看到的回答和当时屏幕上不一致。
        """
        from pymodels.core.ai import versions as ai_versions

        messages = session.messages
        index = self._to_index(regenerate_at)
        is_error = bool(isinstance(extra, dict) and extra.get("error"))
        kind = str((extra or {}).get("kind") or "") if isinstance(extra, dict) else ""
        if index is not None and 0 <= index < len(messages) \
                and str(messages[index].get("role") or "") == "assistant":
            message = messages[index]
            # ⚠️ error 按**版本**记（variants 旁边那张 variant_error 表）：
            #    "上一版请求失败、这次重新生成成功"落在同一条消息的两个版本上，
            #    只有消息级 error 就没法表达"翻回旧版还是红色报错、新版不红"。
            # ⚠️ 这一步内部会把 messages[index+1:] 先深拷贝存进旧版本的分支格子，
            #    再删掉它们（新版本的后继从空开始）——顺序见函数自己的注释。
            ai_versions.regenerate_variant(messages, index, content, error=is_error,
                                           reasoning=_reasoning_of(extra))
            message["kind"] = kind if is_error else ""
            message["ts"] = _now()
        else:
            if index is not None:
                _log("warn", "AI", "chat",
                     f"重新生成下标 {index} 已失效（会话被改过？），按新增回答处理")
            message = {"role": "assistant", "content": str(content or ""),
                       "ts": _now()}
            if isinstance(extra, dict):
                for key, value in extra.items():
                    if key not in ("role", "content", "ts", "error", "kind"):
                        message[key] = value
            ai_versions.append_variant(message, content, error=is_error,
                                        reasoning=_reasoning_of(extra))
            message["kind"] = kind if is_error else ""
            messages.append(message)
        ai_versions.normalize_messages(messages)
        ai_versions.sync_branches(messages)
        session.updated_at = _now()
        return self._persist_session(store, session)

    def _persist_user_message(self, store, session, content: str) -> bool:
        """新增一条用户消息（带 v1 版本字段）并落盘；标题也在这里顺便定下来"""
        from pymodels.core.ai import versions as ai_versions

        message = {"role": "user", "content": str(content or ""), "ts": _now()}
        ai_versions.append_variant(message, str(content or ""))
        message[ai_versions.BRANCH_KEY] = [None]
        session.messages.append(message)
        self._ensure_title(session, content)
        ai_versions.normalize_messages(session.messages)
        session.updated_at = _now()
        return self._persist_session(store, session)

    def _persist_session(self, store, session) -> bool:
        """**确认真的写到磁盘**（ChatStore.save 会返回 False，但 append 的返回值被它丢了）
        ⚠️ 为什么要多此一举：目录不可写 / 磁盘满 / 权限不够这类失败，在调用方完全看不出来
           —— 用户以为聊过的话丢了，日志里也是干净的。这里补两层确认：
           ① 会话文件不存在就先 save 一次；② 仍然没有 → 记 err 日志并让上层 persisted:false。
        """
        try:
            path = store.path_of(session.id)
        except Exception as exc:                          # noqa: BLE001
            _log("err", "AI", "chat", f"取会话文件路径失败: {exc}")
            return False
        try:
            if not store.save(session):
                _log("err", "AI", "chat", f"保存会话失败（原子写返回 False）: {path}")
                return False
            return os.path.isfile(path)
        except Exception as exc:                          # noqa: BLE001
            _log("err", "AI", "chat", f"保存会话失败: {type(exc).__name__}: {exc}")
            return False

    def send(self, session_id: str = "", text: str = "", reply_mode: str = "",
             resend: bool = False, user_index=None, assistant_index=None):
        """发一条消息：落盘用户消息 → 组装上下文 → 请求 → 回答落盘（全部走版本树）

        返回 `{ok, reply, session_id, session, variant_count, variant_index}`；
        失败时 `error` 是可读说明。额外：
            `tool_rounds` / `created_plugins` / `plugin_command`（见 _chat_with_tools）
            `persisted`   —— 这次的消息有没有真的写进磁盘（false = 历史里看不到，前端可提示）
            `kind`        —— "no_key" / "no_model" / 请求失败的分类

        ============ 三种"发送"（版本语义全在这里，别处不要再猜） ============
        ① 普通发送（resend=False、不带 user_index）：
           追加一条**新用户消息**（v1）+ 一条**新 AI 回答**（v1）。
        ② 重新生成（`resend=True` + `assistant_index`=要重写的那条 AI 回答的下标）：
           **不再摘掉旧回答**（那是老实现，会把历史版本弄丢）；旧回答留在原位，
           新回答作为它的**一个新版本**追加进 `variants`，页码翻到最新。
           它**下面那串下游对话整段让位**：先深拷贝存进这条回答**旧版本**的
           `branch_suffixes[旧页码]`，追加新版本后新版本的格子是空的、并把
           `messages[assistant_index+1:]` 删掉（所以落盘后这条下面本来就该没有内容）。
           翻回旧版本时那一格原样放回来，几个版本的后继永远不会混着显示。
           上下文截到那条旧回答**之前**（`upto=assistant_index`），旧回答不进上下文。
           没给 `assistant_index` 时退回"最后一条 assistant 的位置"（兼容旧前端）。
        ③ 编辑后重发（`resend=True` + `user_index`=被编辑那条用户消息的下标）：
           该用户消息多出一个新版本（文本换成编辑后的），**它下面那串 AI 回复整段换掉**：
           旧的那串先存进 `branch_suffixes[旧版本]`（翻回旧版本还看得见），新版本从空开始。
           上下文 = `messages[:user_index+1]`（新版本的那一句就是最后一句）。

        ⚠️⚠️ 下标会漂移：切分支会整段替换 `messages[index+1:]`，所以 `user_index` /
           `assistant_index` **必须是前端当前这份 messages 的绝对下标**，前端在发请求前
           刚从后端拿到这份列表时才算数；每次返回都带整个 session，让前端重建下标。
        ⚠️⚠️ **顺序和 PyQt 版 `ai_chat_panel.send_message()` 一致：先落盘、再判断能不能发。**
           以前是"先查 Key/模型 → 不满足就直接 return"：既没落盘、也没打日志，
           用户看到的就是"历史对话不存储 + 日志里什么都没有"的根因之一。现在：
             ① 用户消息先写进 chats/<id>.json；
             ② 没配 Key / 模型名 → 落一条固定的引导回答，返回 `{ok:true, kind:"no_key"}`；
             ③ 每条失败路径都写日志（no_key / no_model / 请求失败 / 落盘失败）；
             ④ 落盘失败会在返回值里带 `persisted:false`，前端能提示"对话没保存"。
        ⚠️ 这是**同步阻塞**调用（js_api 在工作线程里跑，不会卡界面）；界面要逐字输出请用
           `send_stream`（前端按设置 `ai_stream_enabled` 二选一，失败自动退回这里）。
        """
        session = None
        store = None
        try:
            from pymodels.core.ai import client as ai_client      # noqa: F401

            content = str(text or "").strip()
            if not content:
                _log("warn", "AI", "chat", "空消息，已忽略")
                return _fail("消息是空的")

            store = self.store
            target = str(session_id or "").strip()
            session = store.load(target) if target else None
            if session is None:
                session = store.new_session()
                _log("info", "AI", "chat", f"新建会话 {session.id}")
            else:
                _log("dbg", "AI", "chat", f"续聊会话 {session.id}")

            plan = self._prepare_send(store, session, content, resend, user_index,
                                      assistant_index)
            if plan.get("failed"):
                return plan["failed"]
            edit_regen = plan["mode"] == "edit"
            regen = plan["mode"] == "regen"
            ai_idx = plan["assistant_index"]
            upto = plan["upto"]

            # ② 能不能发？不能发就给一条固定引导回答（同样落盘）—— 对齐 PyQt 版行为
            creds = self._credentials()
            api_key = creds["api_key"]
            display_model = creds["model"]
            model = creds["api_model"]
            api_base = creds["api_base"]
            if creds["missing"]:
                # ⚠️ 本轮需求（用户原话）：「当未填写API Key时或者填写有误会固定回复
                #    其中包括"请填写<API Key>" 这个是下滑线字体 点击跳转页面到设置中的
                #    GCP-AI 位置（现在的那个是不可点击状态 无下划线 不是蓝色字体的普通字体
                #    是不对的 还有"<>"不是变量而是就是可点击文本的一部分）」。
                #    → 文案里嵌 `设置<API Key>` 这个**固定字面量**（尖括号就是文本本身，
                #      不是变量占位符）；前端 aiSplitLinks 认它 → 渲染成蓝色下划线，
                #      点了走 gotoSettingsAi() 跳 设置 → GCP-AI。
                # ⚠️ 本轮多语言：这条"固定回复"是**后端生成、直接落盘进气泡**的文本，
                #    前端只负责显示、翻不了 → 以前英文界面下它也整句中文
                #    （用户报的「语言切换为其他语言部分地方还是只有简体中文文本内容」）。
                #    现在按界面语言从语言包取（`_text` 走 `_locale()`，"跟随系统"也对）。
                hint = self._text("ai_no_key_chat",
                                  "还没有配置{missing}。请填写<API Key> 后再聊。\n"
                                  "（这条对话已经保存到历史里，配置好之后可以接着聊）",
                                  missing=" 和 ".join(creds["missing"]))
                saved = self._persist_assistant(store, session, hint,
                                                None if edit_regen else ai_idx)
                _log("op", "AI", "chat_no_key",
                     f"会话 {session.id} 缺 {'/'.join(creds['missing'])}，"
                     f"已保存对话并给出引导回答")
                return _ok(reply=hint, kind="no_key",
                           session_id=session.id, session=self._dump(session),
                           missing=creds["missing"], persisted=bool(saved),
                           **self._variant_of(session, ai_idx if regen else None))

            # ③ 组装上下文（system 提示词 / 资源清单 / 上下文轮数 / 元信息 / /plugin 全走原版实现）
            #    ⚠️ 思考档位先算：元信息段里"当前思考档位"一行要用它（需求 1/4）
            thinking = self._thinking_state(creds.get("provider"), display_model,
                                           creds.get("profile_id") or "")
            ctx_messages, plugin_command, locale = self._call_context_messages(
                session, content, reply_mode, upto,
                creds.get("provider") or "", display_model, model, thinking)

            # ③.5（thinking 已在 ③ 前算好，见上）

            # ④ 请求（含工具循环；client.chat 永不抛异常）
            #    ⚠️ 只有 `/plugin` 指令才允许跑工具（见 _chat_with_tools 的说明）
            #    ⚠️ 本轮：「列举所有资源」这类请求主动垫高输出预算（_request_max_tokens），
            #    否则 52 条列到一半就被网关默认上限掐掉（用户实测"还是漏一大部分"的另一半）。
            req_max_tokens = self._request_max_tokens(content)
            result, tool_rounds, created = self._chat_with_tools(
                ctx_messages, api_key, model, api_base, locale=locale,
                allow_tools=plugin_command, thinking=thinking,
                max_tokens=req_max_tokens)

            # ④.5 ⚠️ 本轮新增：**网关不认思考参数就自动降级重试一次**。
            #    多档强度靠 `reasoning_effort` / `thinking` 两个字段，官方 DeepSeek/OpenAI
            #    都支持，但用户填的**中转/自建网关**（one-api、vLLM、各种镜像）很可能
            #    把未知参数判成 400 —— 那样用户只是"想开个思考"，结果整条消息发不出去，
            #    比没有思考严重得多。所以：带档位失败且是 400/bad_request →
            #    去掉思考参数（thinking=None）原样重试一次，并在日志里说清楚。
            if (not getattr(result, "ok", False)) and thinking is not None \
                    and getattr(result, "kind", "") == "bad_request":
                _log("warn", "AI", "chat",
                     f"网关拒绝了思考档位 {thinking!r}（{getattr(result, 'message', '')}），"
                     f"已去掉思考参数重试一次")
                result, tool_rounds, created = self._chat_with_tools(
                    ctx_messages, api_key, model, api_base, locale=locale,
                    allow_tools=plugin_command, thinking=None)
                thinking = None       # 这次确实没思考：落盘/界面都不该出现思考块

            if not getattr(result, "ok", False):
                kind = getattr(result, "kind", "") or ""
                # ⚠️ 本轮：按界面语言重写错误文案（详见 _localized_error），
                #    "当前配置：" 这一行也跟着本地化 —— 它以前是硬编码中文。
                message = self._localized_error(
                    kind, getattr(result, "message", "") or self._text("ai_err_failed", "请求失败"),
                    status=getattr(result, "status", 0) or 0)
                config = self._describe_config(api_base, display_model, creds["key_tail"])
                error_text = (message + "\n"
                              + self._text("ai_err_current_config", "当前配置：") + config) if config else message
                # ⚠️ 报错也要落盘（带 error 标记）：这就是"从历史点进来对话没了"的根因修复，
                #   以前失败分支只 return，前端只在内存里推一个气泡。
                #   重新生成时同样"就地成一个版本"，报错气泡也带版本字段才能翻页。
                saved = self._persist_assistant(
                    store, session, error_text,
                    None if edit_regen else ai_idx,
                    {"error": True, "kind": kind})
                _log("err", "AI", "chat",
                     f"请求失败 kind={kind} {message}"
                     f"（错误已落盘={saved}，会话 {session.id}）")
                return _fail(error_text, kind=kind,
                             session_id=session.id, session=self._dump(session),
                             tool_rounds=tool_rounds, created_plugins=created,
                             persisted=bool(saved))

            reply = self._clean_reply(str(getattr(result, "content", "") or ""))
            if not reply:
                reply = ("AI 反复调用工具但没有给出最终回答，请把你的需求说得更具体一点，"
                         "或者直接告诉它插件的 id。" if tool_rounds
                         else "模型没有返回内容，换个说法再试一次。")
            # ⚠️ 思考文本**单独落盘**（variant_reasoning 表），绝不拼进 reply：
            #    拼进正文就是用户报的"没开思考按钮却看到思考内容"。
            #    档位关着（off）/ 模型不支持（None）/ 网关拒绝后降级 → 一律空串，磁盘上不留思考。
            reasoning = (str(getattr(result, "reasoning", "") or "")
                         if self._thinking_open(thinking) else "")
            reply_saved = self._persist_assistant(store, session, reply,
                                                  None if edit_regen else ai_idx,
                                                  {"reasoning": reasoning}
                                                  if reasoning else None)
            if not reply_saved:
                _log("err", "AI", "chat",
                     f"回答写盘失败（会话 {session.id}）：本次回答只显示在界面上")
            _log("op", "AI", "chat",
                 f"会话 {session.id} 收到回答 {len(reply)} 字"
                 + (f"（思考 {len(reasoning)} 字）" if reasoning else "")
                 + (f"（工具轮 {tool_rounds}，生成插件 {', '.join(created)}）"
                    if tool_rounds else "")
                 + ("（重新生成 → 新版本）" if regen else "")
                 + ("（编辑后重发 → 新分支）" if edit_regen else "")
                 + ("" if reply_saved else "（写盘失败）"))
            return _ok(reply=reply, session_id=session.id, session=self._dump(session),
                       tool_rounds=tool_rounds, created_plugins=created,
                       plugin_command=bool(plugin_command),
                       reasoning=reasoning, thinking=self._thinking_open(thinking),
                       persisted=bool(reply_saved),
                       **self._variant_of(session, ai_idx if regen else None))
        except Exception as exc:                          # noqa: BLE001
            _log("err", "AI", "chat", f"发送异常: {type(exc).__name__}: {exc}")
            extra = {}
            try:
                if session is not None:
                    extra = {"session_id": session.id, "session": self._dump(session)}
                    # 兜底：异常路径也尽量把报错落盘（用户消息已写过盘的话，对话就完整了）
                    try:
                        if store is not None and session.messages:
                            error_text = (f"发送异常：{type(exc).__name__}: {exc}")
                            self._persist_message(store, session, "assistant",
                                                  error_text, {"error": True})
                            extra = {"session_id": session.id,
                                     "session": self._dump(session)}
                    except Exception:
                        pass
            except Exception:
                extra = {}
            return _fail(exc, **extra)

    def _variant_of(self, session, index):
        """把"刚写好那条回答"的版本信息带给前端（前端据此决定要不要画 ◀ n/m ▶）"""
        try:
            from pymodels.core.ai import versions as ai_versions
            message = None
            if index is not None and 0 <= int(index) < len(session.messages):
                message = session.messages[int(index)]
            elif session.messages:
                message = session.messages[-1]
            if not isinstance(message, dict):
                return {}
            return {"variant_count": ai_versions.variant_count(message),
                    "variant_index": ai_versions.active_variant(message)}
        except Exception:                                 # noqa: BLE001
            return {}

    # ---------- 切换版本（气泡上的 ◀ n ▶） ----------
    def switch_variant(self, session_id: str = "", index=None, variant_index=None):
        """把某条消息翻到第 variant_index 版，返回**整个 session**（不是增量）

        ⚠️⚠️ 为什么要返回整个会话：翻页 = 换**整条分支**。用户消息翻页换的是"这句提问下面
           挂的那串 AI 回复"；AI 消息翻页换的是"这一版回答下面挂的那串对话"—— 两者都会
           整段替换 `messages[index+1:]`，后面的消息下标全跟着漂。
           前端只拿增量拼必然画歪 —— 一律用返回的 messages 重建气泡。
        ⚠️ 下标必须来自前端**当前**这份 messages；越界直接 ok:false + kind=stale_index，
           前端重新拉一次会话即可，绝不"猜最近的一条"改数据。
        """
        session = None
        try:
            from pymodels.core.ai import versions as ai_versions

            target = str(session_id or "").strip()
            store = self.store
            session = store.load(target) if target else None
            if session is None:
                return _fail("这个对话已经不存在了", session_id=target)
            ai_versions.normalize_messages(session.messages)

            index_value = self._to_index(index)
            variant_value = self._to_index(variant_index)
            if index_value is None or variant_value is None:
                return _fail("没有指定要翻哪一条消息的哪一版")
            if not (0 <= index_value < len(session.messages)):
                return _fail("这条消息已经不在当前对话里了（可能刚翻过版本），请重新打开对话",
                             kind="stale_index", session_id=session.id,
                             session=self._dump(session))

            changed = ai_versions.switch_variant(session.messages, index_value, variant_value)
            if changed:
                ai_versions.sync_branches(session.messages)
                session.updated_at = _now()
                saved = self._persist_session(store, session)
                _log("op", "AI", "switch_variant",
                     f"会话 {session.id} 第 {index_value} 条翻到第 {variant_value} 版"
                     f"（落盘={saved}）")
            return _ok(changed=bool(changed), session_id=session.id,
                       session=self._dump(session), persisted=True)
        except Exception as exc:                          # noqa: BLE001
            _log("err", "AI", "switch_variant", f"切换版本失败: {exc}")
            return _fail(exc, session=self._dump(session) if session else None)

    # ================= 流式（逐字）输出 =================
    # 为什么用「后端线程 + shell.push_event」而不是前端自己 fetch：
    #   · API Key 只在后端（前端拿不到，也不该拿到）；
    #   · pywebview 的 js_api 是"一次调用一个返回值"，没法在同一个调用里往外推。
    #   所以 send_stream **立刻返回** stream_id，回答的文字靠 `ai.stream` 事件推给前端。
    # 事件载荷（统一 name = "ai.stream"）：
    #   {stream_id, session_id, type: "delta"|"done"|"error"|"cancelled",
    #    text: 累计全文(delta/done) / 错误说明(error), session: 落盘后的整会话(done/error/cancelled)}
    # ⚠️⚠️ 后台线程推前端**前必须检查 `_teardown_started`**（AGENTS 第 8 条）：
    #    WebView2 比主窗口先销毁，`shell.push_event` 里虽然有三道闸，但那是在**新线程里**查的；
    #    我们每个 delta 都新建线程去推，退出瞬间会堆出一串注定失败还带异常的调用。
    #    所以这里 `_push()` 自己先查一次（`_can_push()`），闸门关掉就**整个流直接收尾不再推**。
    # ⚠️⚠️ 本轮（用户确认「完全跟随到达速度」）：**取消 120ms 节流**，
    #    改成"有新增立刻推、没有就短睡 8ms"的轮询（见 _stream_pump）。
    #    旧节流把网关的到达节奏主动放慢了 120ms/包，快模型被攒成大包 →
    #    用户看到的"一坨一坨 / 整段突然出现"，一半成因就在这里。
    #    为什么不会把线程堆爆：推送始终由**这一条 pump 线程顺序调用** push_event，
    #    而且同一轮里 reader 写了几次也只推一份最新累计值（dirty + 长度比对）。
    #    done / error / cancelled **必须必达**，收尾那一条永远推。
    STREAM_POLL_INTERVAL = 0.008
    # 兼容旧引用（回归脚本 / 注释里提到过这个名字）：保留但不再作为节流窗口使用。
    STREAM_PUSH_INTERVAL = STREAM_POLL_INTERVAL

    def _stream_slot(self, stream_id: str) -> dict:
        with self._streams_lock:
            return self._streams.get(stream_id)

    def _can_push(self) -> bool:
        """外壳还能不能往前端推事件（退出竞态里宁可丢事件，也不能崩）"""
        shell = self._shell
        if shell is None:
            return False
        if getattr(shell, "_teardown_started", False) or getattr(shell, "_quitting", False):
            return False
        # ⚠️ 必须判 callable：本地预览的 mock 外壳 / 老外壳上 push_event 可能压根没有
        #    或者被显式置成 None —— `hasattr` 对 None 也返回 True，会让我们起一个
        #    永远推不出 done 的流，界面就卡在"正在查看问题"里出不来。
        return callable(getattr(shell, "push_event", None))

    def _push(self, payload: dict) -> bool:
        """推一条 ai.stream 事件；外壳不可用/正在退出 → 静默丢掉并返回 False"""
        if not self._can_push():
            return False
        try:
            self._shell.push_event("ai.stream", payload)
            return True
        except Exception as exc:                          # noqa: BLE001
            # 老后端没有 push_event / 窗口刚好销毁：都不该让流式线程跟着崩
            _log("dbg", "AI", "stream", f"推送流式事件失败（本次已跳过）: {exc}")
            return False

    def send_stream(self, session_id: str = "", text: str = "", reply_mode: str = "",
                    resend: bool = False, user_index=None, assistant_index=None):
        """流式版 send()：**立刻**返回 `{ok, stream_id, session_id, session}`，回答靠事件推。

        返回 ok=False + `kind:"fallback"` 表示"这条别走流式"（外壳推不了事件 / 缺 Key /
        `/plugin` 工具循环 / 会话目录写不进），前端应当**原样改调 send()**，
        行为退回整段返回，用户最差只是"没有逐字效果"，绝不会卡住没结果。

        ⚠️⚠️ **所有 fallback 判断必须在 `_prepare_send()` 之前做完**：
           `_prepare_send` 会把用户消息**落盘**。如果先落盘再说"这条别走流式"，
           前端退回 `send()` 时会**再落一次**同一条提问 —— 历史里凭空多出一模一样的两条
           （这个坑很隐蔽：界面只看得到"多发了一次"，磁盘上才是证据）。
        """
        content = str(text or "").strip()
        if not content:
            return _fail("消息是空的")
        # ① 推不动事件就别流式（预览模式的 mock 外壳 / 老后端 / 正在退出）：
        #    流式的价值就是"往外推字"，推不动 = done 事件永远不到，界面会卡在等待提示里。
        shell = self._shell
        if not self._can_push():
            return _fail("需要回退到整段返回", kind="fallback", reason="no_event_channel")
        try:
            from pymodels.core.ai import client as ai_client

            # ② 缺 Key / 缺模型：引导回答是固定文本，用不着流式 → 交给 send() 全程处理
            creds = self._credentials()
            if creds["missing"]:
                return _fail("需要回退到整段返回", kind="fallback", reason="no_credentials")
            # ③ `/plugin` 要跑工具循环（多轮往返、同步整段的老路径），不流式
            plugin_command, _plugin_prompt = self._plugin_prompt(content)
            if plugin_command:
                return _fail("需要回退到整段返回", kind="fallback", reason="plugin_command")
            # ④ 后端客户端没有流式实现（被裁掉的旧版本）
            if not hasattr(ai_client, "chat_stream"):
                return _fail("需要回退到整段返回", kind="fallback", reason="no_stream_client")

            session = None
            try:
                store = self.store
                target = str(session_id or "").strip()
                session = store.load(target) if target else None
                if session is None:
                    session = store.new_session()

                # ⑤ 到这里才真的动会话：用户那一侧的版本改动 + 落盘
                #    （和 send() 完全同一条代码路径，版本语义只写一遍）
                plan = self._prepare_send(store, session, content, resend, user_index,
                                          assistant_index)
                if plan.get("failed"):
                    return plan["failed"]

                # 思考档位先算：元信息段里"当前思考档位"一行要用它（与 send() 同一口径）
                thinking_row = self._thinking_state(creds.get("provider"),
                                                    creds.get("model"),
                                                    creds.get("profile_id") or "")
                ctx_messages, still_plugin, locale = self._call_context_messages(
                    session, content, reply_mode, plan["upto"],
                    creds.get("provider") or "", creds.get("model") or "",
                    creds.get("api_model") or "", thinking_row)
                if still_plugin:
                    # 兜底（理论上到不了：③ 已经拦过）：绝不在工具循环里冒充流式
                    return _fail("需要回退到整段返回", kind="fallback",
                                 reason="plugin_command", session_id=session.id,
                                 session=self._dump(session))

                # ⑥ 建流 + 起线程
                stream_id = uuid.uuid4().hex[:12]
                # 思考档位行（None = 模型不支持）：开着才会把 reasoning 推给前端 + 落盘
                thinking = thinking_row
                state = {
                    "stop": False,
                    "latest": "",            # 最新累计全文（ticker 只推这个）
                    "dirty": False,          # 有没有新内容没推
                    "done": False,           # 是否已结束（ticker 靠它退出）
                    "pushed_len": -1,
                    # ⚠️ 思考流走**自己的一套** latest/dirty/pushed_len：
                    #    以前 reasoning 被塞进 latest，正文和思考混在一格里一次性蹦出来，
                    #    既造成"不是逐字输出"，也让没开思考的用户看见了思考内容。
                    "reasoning": "",
                    "reasoning_dirty": False,
                    "reasoning_pushed_len": -1,
                    # ⚠️ 本轮新增（逐字输出仍"整段突然出现"的第二半修复）：
                    #    `deltas` = 真的推出去过几条 delta。done 里带 streamed 标记，
                    #    前端据此区分"该走打字机"还是"整段本来就到不了几个包"。
                    "deltas": 0,
                    "first_pending": True,   # 第一个有内容的包要**立刻**推（不等 120ms）
                }
                with self._streams_lock:
                    self._streams[stream_id] = state
                context = {
                    "store": store, "session": session, "plan": plan, "creds": creds,
                    "messages": ctx_messages, "locale": locale, "content": content,
                    "thinking": thinking,
                }
                threading.Thread(target=self._stream_reader, args=(stream_id, context),
                                 name=f"ToolsGCP-ai-stream-{stream_id}", daemon=True).start()
                threading.Thread(target=self._stream_pump, args=(stream_id,),
                                 name=f"ToolsGCP-ai-pump-{stream_id}", daemon=True).start()
                _log("op", "AI", "stream",
                     f"开始流式输出 {stream_id}（会话 {session.id}，模式 {plan['mode']}）")
                # 把刚落盘的用户消息先还给前端：气泡立刻出现，不用等回答
                return _ok(stream_id=stream_id, session_id=session.id,
                           session=self._dump(session))
            except Exception as inner:                      # noqa: BLE001
                _log("err", "AI", "stream", f"启动流式失败（前端请退回 send）: {inner}")
                return _fail(inner, kind="fallback", reason="start_failed",
                             session=self._dump(session) if session else None)
        except Exception as exc:                          # noqa: BLE001
            _log("err", "AI", "stream", f"启动流式失败（前端请退回 send）: {exc}")
            return _fail(exc, kind="fallback", reason="start_failed")

    def _stream_reader(self, stream_id: str, context: dict) -> None:
        """后台线程：读 SSE → 更新 state.latest；结束后落盘 + 推收尾事件"""
        from pymodels.core.ai import client as ai_client

        state = self._stream_slot(stream_id) or {}
        session = context["session"]
        store = context["store"]
        plan = context["plan"]
        creds = context["creds"]
        thinking = context.get("thinking")
        reply_saved = False
        try:
            def on_chunk(accumulated: str) -> None:
                # ⚠️ 只**记**最新的累计全文，不在这里推事件：读流线程一次回答会回调几十上百次，
                #    每次起一个 push 线程 = 线程爆炸。真正推的是 _stream_pump（固定 120ms 一条）。
                state["latest"] = str(accumulated or "")
                state["dirty"] = True

            def on_reasoning(accumulated: str) -> None:
                # ⚠️ 思考流**只进 reasoning 格**，绝不写进 latest（那是正文）：
                #    两者混在一格 = 用户看到的"思考内容混在回答里 + 一次性整段出现"。
                state["reasoning"] = str(accumulated or "")
                state["reasoning_dirty"] = True

            def should_stop() -> bool:
                return bool(state.get("stop")) or not self._can_push()

            result = ai_client.chat_stream(
                context["messages"], creds["api_key"], creds["api_model"],
                # ⚠️ wants_all 的列举类回答同样垫高输出预算（和 send() 一个口径）：
                #    流式路径以前恒 max_tokens=0，网关默认上限照样把 52 条掐一半。
                creds["api_base"],
                max_tokens=self._request_max_tokens(context.get("content") or ""),
                temperature=0.7,
                on_chunk=on_chunk, should_stop=should_stop,
                on_reasoning=on_reasoning if self._thinking_open(thinking) else None,
                thinking=thinking)

            # ⚠️ 与 send() 同一套降级：网关把思考档位判成 400 → 去掉参数重试一次。
            #    流式这里要**先清掉已经收到的思考**再重试，否则旧档位的半截思考会
            #    跟着降级后的回答一起显示（档位已经关了却还有思考块）。
            if (not getattr(result, "ok", False)) and thinking is not None \
                    and getattr(result, "kind", "") == "bad_request" \
                    and not state.get("stop"):
                _log("warn", "AI", "stream",
                     f"网关拒绝了思考档位 {thinking!r}（{getattr(result, 'message', '')}），"
                     f"已去掉思考参数重试一次")
                state["reasoning"] = ""
                state["reasoning_dirty"] = False
                state["reasoning_pushed_len"] = -1
                thinking = None
                context["thinking"] = None
                state["latest"] = ""
                state["dirty"] = False
                state["pushed_len"] = -1
                result = ai_client.chat_stream(
                    context["messages"], creds["api_key"], creds["api_model"],
                    creds["api_base"],
                    max_tokens=self._request_max_tokens(context.get("content") or ""),
                    temperature=0.7,
                    on_chunk=on_chunk, should_stop=should_stop,
                    on_reasoning=None, thinking=None)
            cancelled = bool(state.get("stop")) or getattr(result, "kind", "") == "cancelled"
            ok = bool(getattr(result, "ok", False))
            text = state.get("latest") or ""
            think_text = (state.get("reasoning") or "") if self._thinking_open(thinking) else ""

            if cancelled:
                # 中断：已经把打出来的部分落盘（别丢用户看到的字），并标注被中断
                partial = str(text or "").strip()
                payload = None
                if partial:
                    partial = f"{partial}\n\n（本次回答被中断）"
                    reply_saved = self._persist_assistant(
                        store, session, partial,
                        None if plan["mode"] == "edit" else plan["assistant_index"],
                        {"reasoning": think_text} if think_text else None)
                    payload = self._dump(session)
                self._push({"stream_id": stream_id, "session_id": session.id,
                            "type": "cancelled", "text": partial,
                            "reasoning": think_text,
                            "session": payload})
                _log("op", "AI", "stream", f"流式已中断 {stream_id}（已落盘={reply_saved}）")
                return

            if not ok:
                kind = getattr(result, "kind", "") or ""
                message = self._localized_error(
                    kind, getattr(result, "message", "") or self._text("ai_err_failed", "请求失败"),
                    status=getattr(result, "status", 0) or 0)
                config = self._describe_config(creds["api_base"], creds["model"],
                                               creds["key_tail"])
                error_text = (message + "\n"
                              + self._text("ai_err_current_config", "当前配置：") + config) if config else message
                saved = self._persist_assistant(
                    store, session, error_text,
                    None if plan["mode"] == "edit" else plan["assistant_index"],
                    {"error": True, "kind": kind})
                _log("err", "AI", "stream",
                     f"流式请求失败 kind={kind} {message}（错误已落盘={saved}）")
                self._push({"stream_id": stream_id, "session_id": session.id,
                            "type": "error", "kind": kind, "error": error_text,
                            "text": error_text, "session": self._dump(session),
                            "persisted": bool(saved),
                            # 同 done：前端据此区分"字已经逐字打过了"还是"整段直接出现"
                            "streamed": int(state.get("deltas") or 0) >= 2,
                            "delta_count": int(state.get("deltas") or 0)})
                return

            reply = self._clean_reply(str(getattr(result, "content", "") or text or ""))
            if not reply:
                reply = "模型没有返回内容，换个说法再试一次。"
            # 思考文本：档位关着 / 模型不支持 / 网关拒绝后降级 → 一律清空（不该出现思考块）
            think_final = (str(getattr(result, "reasoning", "") or "") or think_text) \
                if self._thinking_open(thinking) else ""
            reply_saved = self._persist_assistant(
                store, session, reply,
                None if plan["mode"] == "edit" else plan["assistant_index"],
                {"reasoning": think_final} if think_final else None)
            _log("op", "AI", "stream",
                 f"流式回答完成 {stream_id}：{len(reply)} 字（写盘={reply_saved}）"
                 + (f"（思考 {len(think_final)} 字）" if think_final else "")
                 + ("（新版本）" if plan["mode"] == "regen" else "")
                 + ("（新分支）" if plan["mode"] == "edit" else ""))
            # 收尾：done 必达，带上**整会话**让前端用磁盘为准重建（下标从此也重新对齐）
            # ⚠️ 本轮新增 `streamed` / `reason`（前端打字机的判据，用户需求"整段突然出现"）：
            #    streamed=false 意味着**这条回答根本没有经过逐字通道**
            #    （网关一次性吐完 / 思考被拒后降级重跑 / 短回答只攒到一个包），
            #    前端就知道不该把 done 的整段再"贴"一次，而是把已经打出来的字平滑收尾。
            #    老前端忽略这两个字段也不会坏（契约向后兼容）。
            deltas = int(state.get("deltas") or 0)
            self._push({"stream_id": stream_id, "session_id": session.id,
                        "type": "done", "text": reply,
                        "reasoning": think_final,
                        "session": self._dump(session),
                        "persisted": bool(reply_saved),
                        "streamed": deltas >= 2,
                        "delta_count": deltas})
        except Exception as exc:                          # noqa: BLE001
            _log("err", "AI", "stream", f"流式线程异常 {stream_id}: {exc}")
            try:
                self._push({"stream_id": stream_id, "session_id": session.id,
                            "type": "error", "kind": "stream_exception",
                            "error": f"{type(exc).__name__}: {exc}",
                            "text": "", "session": self._dump(session)})
            except Exception:
                pass
        finally:
            state["done"] = True
            with self._streams_lock:
                self._streams.pop(stream_id, None)

    def _stream_pump(self, stream_id: str) -> None:
        """推字：只推"最新累计全文"（不做增量拼接，前端整段替换即可）

        ⚠️⚠️ 本轮改动（用户原话：「我的原意是 ai 输出多快软件这个逐字功能输出就有多快」，
           并已确认「完全跟随到达速度」）：**取消 120ms 节流**。
           以前每 120ms 才醒一次，等于后端主动把网关的到达节奏**放慢了**，
           快模型/短回答会被攒成"几个大包"，观感就是"一坨一坨"甚至"整段突然出现"。
           现在改成轮询间隔 = STREAM_POLL_INTERVAL（8ms）：
             · 有新增就立刻推 → 到达速度 ≈ 推送速度；
             · 没新增就短睡，CPU 占用可忽略（一次回答最多几百次空转）；
             · 仍然是**这一条 pump 线程自己推**，不会"每个字起一个线程"把线程堆爆
               （push_event 由这条线程顺序调用，天然串行）。
           ⚠️ 同一帧内 reader 写了多次也只推一份最新累计值（dirty 标志 + 长度比对），
              所以"跟随到达速度"不等于"每个 SSE 分片都发一条事件"。

        ⚠️ 正文与思考**各自记账、同一条 delta 里都带上**：
           `text` = 累计正文，`reasoning` = 累计思考（只有开了思考才有值）。
           分开是因为它们渲染在气泡的两个位置（思考在上、正文在下），
           混在一格里 = 用户看到的"思考内容混进回答"。
        ⚠️ 顺序（用户报的「思考未完成就直接输出回答文本」）：
           reader 侧 SSE 本来就是"先 reasoning_content 后 content"，
           这里保证**每条 delta 都带上当时的完整累计思考**，前端因此永远不可能
           看到"正文比思考先跑"——思考缺一段就是后端没读到，而不是前端贴错。
        """
        state = self._stream_slot(stream_id)
        if state is None:
            return
        try:
            while not state.get("done"):
                # 有内容就推、没有就短睡：节流窗口从 120ms 降到 8ms，
                # 观感上就是"AI 出多快我们显示多快"。
                if not (state.get("dirty") or state.get("reasoning_dirty")):
                    time.sleep(self.STREAM_POLL_INTERVAL)
                    if state.get("done"):
                        break
                    continue
                if state.get("done"):
                    break
                text = state.get("latest") or ""
                think = state.get("reasoning") or ""
                dirty_body = bool(state.get("dirty"))
                dirty_think = bool(state.get("reasoning_dirty"))
                changed = False
                if dirty_body:
                    state["dirty"] = False
                    if len(text) != state.get("pushed_len"):
                        state["pushed_len"] = len(text)
                        changed = True
                if dirty_think:
                    state["reasoning_dirty"] = False
                    if len(think) != state.get("reasoning_pushed_len"):
                        state["reasoning_pushed_len"] = len(think)
                        changed = True
                if not changed:
                    continue
                state["first_pending"] = False
                state["deltas"] = int(state.get("deltas") or 0) + 1
                if not self._push({"stream_id": stream_id, "type": "delta",
                                   "text": text, "reasoning": think}):
                    # 推不动 = 窗口正在销毁：让读流线程也别白跑（它靠 should_stop 收尾）
                    state["stop"] = True
                    break
        except Exception as exc:                          # noqa: BLE001
            _log("dbg", "AI", "stream", f"推字线程退出 {stream_id}: {exc}")

    def cancel_stream(self, stream_id: str = ""):
        """前端点「停止」：让读流线程尽快收尾（已打出的字会落盘并标注被中断）
        ⚠️ urllib 的阻塞 read 没法真中断，这里只是置标志；线程会在下一次读循环或超时后退出。
        """
        state = self._stream_slot(str(stream_id or ""))
        if state is None:
            return _ok(cancelled=False)
        state["stop"] = True
        _log("op", "AI", "stream", f"请求中断流式 {stream_id}")
        return _ok(cancelled=True, stream_id=str(stream_id))

    # ---------- 输入框润色按钮 ----------
    # 需求：GCP-AI 输入框最右侧、发送键左边放一个 AI 图标按钮，对当前输入做润色；
    #   设置 → GCP-AI 里可关，关掉后按钮消失。
    # 设计取舍：
    #   · **不走 ai.send**、不落盘到历史对话：用户只是想把这句话说顺，不是一次提问；
    #   · 只改措辞，不回答、不推荐资源、不新增事实（避免模型"抢答"）；
    #   · 失败返回 ok:false + error，前端 toast 提示，绝不假装成功；
    #   · 用同步非流式请求（js_api 在工作线程里跑，不会卡界面）。
    # ⚠️ 这条提示词是"只润色不抢答"的唯一防线：以前写得笼统（"改得更有条理更具体"），
    #    模型经常顺着用户那句问题**直接回答**（"帮我找个传文件的工具" → 它真给推荐了），
    #    输入框就被换成了一段答案，用户写的话等于丢了（前端虽然有撤销，但体验很糟）。
    #    现在把"绝不回答"提到最前面，并给出可判定的硬规则 + 反例，让它没有发挥空间。
    POLISH_SYSTEM_PROMPT = """你只有一个任务：把用户给你的这段文字**改写得更通顺**（润色 / 纠错 / 提升表达）。

【绝对不要做的事】
· 不要**回答**这段话里的问题，不要执行它的请求，不要推荐任何软件或网站，不要给出结论或建议。
  这段话是用户**准备发给另一个 AI 的提问**，不是给你的任务；你改的是它的措辞。
  反例：输入「帮我找个局域网传文件的工具」→ 输出里出现了具体软件名或链接 = 严重错误。
· 不要改变语言：中文输入就中文输出，英文就英文，不要翻译、不要中英混排。
· 不要增删信息：不添加新的事实、名称、链接、数字、结论；不删掉原有的限定条件和细节。
· 不要解释你做了什么，不要前言后语（"好的""以下是润色结果"这类一个字都不要）。

【必须原样保留】
· 代码片段、命令、文件路径、URL、接口地址：一个字都不要改（包括大小写和空格）。
· 专有名词：软件名、产品名、人名、组织名、资源编码（如 TG-000001）、@提到的对象
  （形如 @LocalSend(TG-000001)）—— 保持原拼写原样出现。
· @ 提及、换行分段、列表项的**数量与顺序**。

【输出要求】
· **只输出润色后的正文本身**：不要引号、不要代码块、不要 Markdown 标记、
  不要「润色后：」之类的前缀、不要同时给出多个版本或对照说明。
· 只做文字层面的优化：用词更准确、句子更通顺、错别字与标点修正、语序更合理、
  口语啰嗦处收紧；保持用户原本的语气和第一人称视角。
· 原句已经通顺时做**最小改动**（哪怕输出和输入完全一样，也是正确结果）。
· 长度与原句相当，不要为了"显得有在干活"而扩写。"""

    @staticmethod
    def _clean_polished(text: str) -> str:
        """清掉模型偶尔带出来的包装（代码块/引号/前缀），只留润色后的正文"""
        value = str(text or "").strip()
        if not value:
            return ""
        # ```...``` 代码块
        if value.startswith("```"):
            value = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", value)
            value = re.sub(r"\s*```$", "", value).strip()
        # 常见前缀（模型很喜欢加）
        value = re.sub(r"^(润色(后|结果|版本)?\s*[：:]\s*)", "", value)
        value = re.sub(r"^(polished(\s+text)?\s*[：:]\s*)", "", value, flags=re.I)
        # 成对包裹的引号/书名号（只剥一层）
        pairs = (('"', '"'), ("'", "'"), ("“", "”"), ("「", "」"), ("『", "』"))
        for left, right in pairs:
            if len(value) >= 2 and value.startswith(left) and value.endswith(right):
                inner = value[len(left):len(value) - len(right)].strip()
                if inner:
                    value = inner
                break
        return value.strip()

    def polish(self, text: str = ""):
        """润色输入框文本：返回 `{ok:true, text, original}` / `{ok:false, error}`
        ⚠️ 不落盘、不创建会话；没有配置 Key/模型时直接给出可读原因（前端 toast）。
        """
        content = str(text or "").strip()
        if not content:
            return _fail("输入框是空的，没有可润色的内容")
        if len(content) > 6000:
            return _fail("这段话太长了（超过 6000 字），先缩短一点再润色")
        try:
            from pymodels.core.ai import client as ai_client
            manager = self.settings_manager
            # ⚠️⚠️ 本轮修复（用户原话）：「点击润色按钮可说我未填写 API Key 可是我填写了」。
            #    根因是**润色自己另写了一套读 Key 的代码**，读的是**厂商槽**
            #    `manager.get_api_key(pid)`；而自"档案按 id 独立"之后，Key 实际存在
            #    **档案槽** `api_key_enc_<profile_id>` 里 —— 厂商槽往往是空的。
            #    于是聊天（走 `_credentials()`，读档案槽）正常，润色（读厂商槽）
            #    一口咬定"没填 Key"。这类"同一个判断写两遍、两遍口径不同"的 bug
            #    在这一块代码里已经是第三次了（串台那次同理）。
            #    ⇒ 正解：润色**不再自己拼**Key/模型/地址，直接复用 send 用的
            #      `_credentials()`，让两条路径永远同口径。
            cred = self._credentials()
            provider = str(cred.get("provider") or "").strip().lower()
            api_key = str(cred.get("api_key") or "")
            model = str(cred.get("api_model") or cred.get("model") or "").strip()
            api_base = str(cred.get("api_base") or "").strip()
            missing = []
            if not api_key:
                missing.append("API Key")
            if not model:
                missing.append("模型名称")
            if missing:
                return _fail(self._text("ai_no_key_polish",
                                        "还没有配置{missing}，请填写<API Key> 后再润色",
                                        missing=" 和 ".join(missing)),
                             kind="no_key", missing=missing)
            max_tokens = 0
            if bool(self._setting("limit_token_output", False)):
                try:
                    max_tokens = int(str(self._setting("max_token", "") or 0) or 0)
                except Exception:
                    max_tokens = 0
            messages = [
                {"role": "system", "content": self.POLISH_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ]
            result = ai_client.chat(messages, api_key, model, api_base,
                                    max_tokens=max_tokens, temperature=0.3)
            if not getattr(result, "ok", False):
                message = getattr(result, "message", "") or "润色请求失败"
                _log("warn", "AI", "polish",
                     f"润色失败 kind={getattr(result, 'kind', '')} {message}")
                return _fail(message, kind=getattr(result, "kind", ""))
            polished = self._clean_polished(str(getattr(result, "content", "") or ""))
            if not polished:
                return _fail("模型没有返回可用的润色结果，请再试一次")
            _log("op", "AI", "polish",
                 f"润色完成：{len(content)} 字 → {len(polished)} 字")
            return _ok(text=polished, original=content)
        except Exception as exc:                          # noqa: BLE001
            _log("err", "AI", "polish", f"润色异常: {type(exc).__name__}: {exc}")
            return _fail(exc)

    # ---------- 测试连接（设置页「测试连接」按钮） ----------
    def test_connection(self, provider: str = "", model: str = "",
                        api_base: str = "", api_key: str = "",
                        profile_id: str = ""):
        """用当前（或设置页草稿里的）配置发一次最小请求，验证 Key/模型/地址能不能用。
        参数为空时回退到已保存的设置；前端在「测试连接」前会先把草稿传进来，
        这样测的就是“用户马上要保存的”那套配置，而不是落盘后再测。
        返回：`{ok, kind, message, status, model, api_base, provider, key_tail, latency_ms}`
        只回 Key 尾号，绝不回传明文。
        """
        try:
            from pymodels.core.ai import client as ai_client
            manager = self.settings_manager
            pid = str(provider or "").strip().lower() \
                or str(self._setting("ai_provider", "deepseek") or "deepseek").strip().lower()
            model = str(model or "").strip() or str(self._setting("model_name", "") or "").strip()
            display_model = model          # 界面显示名（返回给前端用，不发给 API）
            # ⚠️ 同 send：测试连接发送前把界面显示名解析成官方 API 模型名
            try:
                from pymodels.core.ai import providers as ai_providers
                model = ai_providers.resolve_api_model(pid, model)
            except Exception:                              # noqa: BLE001
                pass
            # ⚠️ 地址口径和 _credentials() 完全一致（统一走 _effective_base）：
            #    分槽 api_base_<pid> → custom 兜旧全局值 → 内置服务商官方默认地址。
            #    （测试和真实聊天必须用同一个地址，否则"测试通过、聊天 401"这种
            #      自相矛盾会直接烧掉用户的信任 —— 就是本轮串台 bug 的同族问题。）
            base = str(api_base or "").strip()
            # ⚠️ 本轮：长条卡片上的「测试连接」会带 profile_id。
            #    ① 地址：草稿没给地址时用**这条档案自己的**地址，不要落到厂商/全局槽
            #       （同厂商两条档案各有各的地址，按厂商取必然测错一台）；
            #    ② Key：同理先读**档案槽**。以前这里只读厂商槽 `api_key_enc_<pid>`，
            #       而新 UI 把 Key 存进 `api_key_enc_<档案id>` ⇒ 明明配过却说
            #       "还没有配置 API Key"（和"模型下拉不显示"是同一个读写不同口径的病）。
            prof = self._find_profile(profile_id, pid) if str(profile_id or "").strip() else {}
            if not base and prof:
                base = str(prof.get("api_base") or "").strip()
            if not base:
                base = self._effective_base(pid)
            key = str(api_key or "").strip()
            if not key and prof and manager is not None:
                try:
                    key = manager.get_profile_api_key(prof.get("id"),
                                                      prof.get("provider")) or ""
                except Exception:                          # noqa: BLE001
                    key = ""
            if not key and manager is not None:
                key = manager.get_api_key(pid) or ""
            missing = []
            if not key:
                missing.append("API Key")
            if not model:
                missing.append("模型名称")
            if missing:
                return _fail(self._text("ai_no_key_test",
                                        "还没有配置{missing}，请填写<API Key> 后再测",
                                        missing=" 和 ".join(missing)),
                             kind="no_key", provider=pid, model=display_model,
                             api_base=base or ai_client.DEFAULT_API_BASE,
                             key_tail="", latency_ms=0)
            start = time.time()
            # ⚠️ 本轮修复（用户原话：「点击设置中的测试链接他说“错误 连接失败：回答被长度
            #    上限截断了，请调大最大token量”，不管我又没有填写APIKey」）：
            #    旧写法 `max_tokens=1` 且不关思考 —— 推理模型光是思考就要吃掉好几个 token，
            #    正文永远是空 + finish_reason=length，于是**任何人**点测试都看到同一句
            #    "被长度上限截断"，Key 对错、地址通不通全被这句话盖住。
            #    现在：① 显式关思考（"off" 行 = 各家 disabled/none 参数，见 _thinking_params；
            #    恒思考的模型发了也只是被忽略）；② max_tokens 给到 16，够吐几个字；
            #    ③ finish_reason=length（KIND_LENGTH）判成**连通正常**——能收到 200 就说明
            #    Key/地址/模型三样都通了，只是回答短被截断，不影响"测试连接"的结论。
            result = ai_client.chat(
                [{"role": "user", "content": "ping"}], key, model, base,
                max_tokens=16, temperature=0, timeout=30,
                thinking="off",              # 字符串档位 + provider_id：由 client 查各家官方表
                provider_id=pid)
            latency_ms = int((time.time() - start) * 1000)
            tail = ("****" + key[-4:]) if len(key) >= 4 else ("*" * len(key))
            base_used = ai_client.normalize_api_base(base)
            if not getattr(result, "ok", False):
                if getattr(result, "kind", "") == ai_client.KIND_LENGTH:
                    _log("op", "AI", "test",
                         f"测试连接 {pid}/{model}：连通正常（回答被长度上限截断，"
                         f"{latency_ms}ms）")
                    return _ok(kind="ok",
                               message=self._text("ai_test_ok_truncated",
                                                  "连接正常（测试回答较短，被长度上限截断，"
                                                  "不影响连通性结论）"),
                               status=getattr(result, "status", 200),
                               model=display_model, api_base=base_used, provider=pid,
                               key_tail=tail, latency_ms=latency_ms)
                return _fail(getattr(result, "message", "") or "请求失败",
                             kind=getattr(result, "kind", "") or "",
                             status=getattr(result, "status", 0),
                             model=display_model, api_base=base_used, provider=pid,
                             key_tail=tail, latency_ms=latency_ms)
            return _ok(kind="ok", message="连接正常",
                       status=getattr(result, "status", 200),
                       model=display_model, api_base=base_used, provider=pid,
                       key_tail=tail, latency_ms=latency_ms)
        except Exception as exc:                          # noqa: BLE001
            _log("err", "AI", "test", f"测试连接异常: {type(exc).__name__}: {exc}")
            return _fail(exc, latency_ms=0)

    @staticmethod
    def _message_view(m) -> dict:
        """给前端的一条消息（历史还原 + 版本导航用）：
        ⚠️ 报错气泡必须带 error/kind，前端才能把它画成"报错样式"，
           并且 prompt 组装上下文时后端靠 error 字段跳过它。
        ⚠️ 版本三件套（variants / variant_index / branch_suffixes）要**原样带回去**：
           前端的气泡导航 ◀ 2/3 ▶ 和用户消息翻页全靠它们；缺一样就画不出导航，
           翻过的版本在界面上"消失"（磁盘里其实还在）。
           `variants` 里存的是**每一版正文**，前端按 variant_index 取当前那一条显示，
           而 `content` 已经是那一版的镜像（后端保证），所以老代码只读 content 也不会错。
        """
        view = {"role": m.get("role"), "content": m.get("content"),
                "ts": m.get("ts", ""),
                "error": bool(m.get("error")), "kind": m.get("kind", "")}
        variants = m.get("variants")
        if isinstance(variants, list) and len(variants) > 1:
            view["variants"] = [str(v or "") for v in variants]
            # 每一版是不是报错：翻回"当初失败那一版"时前端要画成红色气泡
            errors = m.get("variant_error")
            if isinstance(errors, list) and any(bool(e) for e in errors):
                view["variant_error"] = [bool(e) for e in errors]
        if isinstance(m.get("variant_index"), int):
            view["variant_index"] = int(m.get("variant_index"))
        # 思考文本（variant_reasoning 表）：只带**非空**的那些格，且只在消息本身有这张表时带。
        # ⚠️ 老会话文件没这张表 → view 里连 reasoning 键都没有（前端按"没有就不画折叠块"处理），
        #    既不会把没思考的回答画出一个空折叠块，也不会让 payload 变大。
        if str(m.get("role") or "") == "assistant" \
                and isinstance(m.get("variant_reasoning"), list):
            thinks = [str(v or "") for v in (m.get("variant_reasoning") or [])]
            if any(thinks):
                view["variant_reasoning"] = thinks
                # 当前选中那一版的思考单独镜像一份：前端渲染气泡只用它，不用自己再按页码取
                idx = view.get("variant_index")
                current = thinks[idx] if isinstance(idx, int) and 0 <= idx < len(thinks) else ""
                if not current and thinks:
                    current = thinks[-1]
                view["reasoning"] = current
        # branch_suffixes 的**正文**不给前端（切分支/翻版本问后端就行）：
        # 带过去只是让前端知道"这一版有没有挂着下游"，不传整串消息，省得 payload 变大。
        # ⚠️ user 与 assistant **两类消息都要带**：AI 重新生成/翻版本时前端也要知道
        #    "这一版下面原来有没有内容"（旧版本挂着下游、新版本是空的）。
        #    形状保持稳定：与 variants 等长的布尔表，user 那边一个字都不改。
        if str(m.get("role") or "") in ("user", "assistant") \
                and isinstance(m.get("branch_suffixes"), list):
            view["has_branch"] = [bool(b) for b in (m.get("branch_suffixes") or [])]
        return view

    @staticmethod
    def _dump(session) -> dict:
        return {"id": session.id, "title": session.title,
                "created_at": session.created_at, "updated_at": session.updated_at,
                "messages": [AiDomain._message_view(m) for m in (session.messages or [])]}

    def provider_models(self, provider: str = ""):
        """某个服务商的模型候选（设置页"刷新模型列表"用；纯本地表，不联网）"""
        try:
            from pymodels.core.ai import providers as ai_providers
            pid = str(provider or "").strip() or self._setting("ai_provider", "deepseek")
            return _ok(provider=pid, models=ai_providers.models_of(pid),
                       api_base=ai_providers.default_api_base(pid),
                       model=ai_providers.default_model(pid))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def info(self):
        """自检用：会话目录、会话数、是否配了 key（不回传明文）
        ⚠️ `chats_dir` 用 **store 自己算出来的目录**（而不是直接甩模块常量）：
           排查"历史不存储"时这两个值必须对得上；store 被指到别处（迁移 / 改数据根 /
           测试）也要如实反映。取不到才退回常量。
        """
        try:
            from pymodels.constants import CHATS_DIR
            store = self.store
            chats_dir = str(getattr(store, "chats_dir", "") or CHATS_DIR)
            manager = self.settings_manager
            provider = str(self._setting("ai_provider", "deepseek") or "deepseek").strip().lower()
            configured = bool(manager and manager.get_api_key(provider))
            key_tail = manager.key_tail(provider) if manager is not None else ""
            return _ok(app=APP_NAME, version=APP_VERSION, chats_dir=chats_dir,
                       dir_exists=bool(os.path.isdir(chats_dir)),
                       sessions=len(store.list_sessions()),
                       provider=provider, model_name=self._setting("model_name", ""),
                       # 串台修复：诊断快照报**当前服务商实际生效**的地址
                       api_base=self._effective_base(provider),
                       configured=configured, key_tail=key_tail,
                       ts=time.time())
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    # ---------- 插件配置界面用的 Agent 状态（：把 py 版配置页搬到 Web） ----------
    # 背景：GCP-AI Agent 的配置页里有更多模块最近动作统计三大块，
    # 数据源是 pymodels.core.ai.agent_runtime.AgentBridge。Web 版之前没有把这层
    # 暴露给前端，插件 config.html 只能显示一个总开关（用户说的"空壳 UI"）。
    # 这里把 AgentBridge 的只读/开关能力按 JSON 信封暴露出去；AgentBridge 本身
    # 只依赖 window 上的 settings_manager / language_manager / plugin_manager，
    # 缺失的（plugin_manager）它会自己按"插件没被停用"处理，不会抛。
    def _agent_bridge(self):
        from pymodels.core.ai.agent_runtime import get_bridge
        return get_bridge(self._shell)

    def agent_state(self):
        """Agent 配置页一次拉全：开关 / 全部模块 / 统计 / 最近动作"""
        try:
            bridge = self._agent_bridge()
            return _ok(enabled=bool(bridge.enabled()),
                       setting_on=bool(bridge.setting_on()),
                       tools=bridge.tools(),
                       stats=bridge.stats(),
                       actions=bridge.recent_actions(20),
                       language=self._language())
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def set_agent_enabled(self, on: bool = False):
        """Agent 总开关（和设置里的 gcp_ai_agent_enabled 是同一个键）
        联动（和前端 saveSetting / togglePlugin 同一口径）：关闭 AI Agent 时
        **一并关闭插件制作辅助**；启用制作辅助 → Agent 由前端 manifest.companion 带开。
        """
        try:
            bridge = self._agent_bridge()
            on = bool(on)
            bridge.set_enabled(on)
            if not on:
                manager = self.settings_manager
                if manager is not None:
                    try:
                        if bool(manager.settings.get("gcp_plugin_maker_enabled", False)):
                            manager.update_setting("gcp_plugin_maker_enabled", False)
                            try:
                                self._shell.push_event("settings-changed",
                                    {"key": "gcp_plugin_maker_enabled", "new": False})
                            except Exception:
                                pass
                    except Exception as exc:                  # noqa: BLE001
                        _log("warn", "AI", "agent",
                             f"关闭 Agent 时同步关闭插件制作辅助失败: {exc}")
            return _ok(enabled=bool(bridge.setting_on()))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def set_agent_tool(self, name: str = "", on: bool = False):
        """打开/关掉某一项手；关掉的会写进 gcp_ai_agent_tools_off"""
        try:
            bridge = self._agent_bridge()
            bridge.set_tool_on(str(name or ""), bool(on))
            return _ok(tools=bridge.tools())
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def set_all_agent_tools(self, on: bool = False):
        """一键全开 / 全关（配置页更多模块的总控）"""
        try:
            bridge = self._agent_bridge()
            bridge.set_all_tools_on(bool(on))
            return _ok(tools=bridge.tools())
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def clear_agent_actions(self):
        """清空最近动作"""
        try:
            bridge = self._agent_bridge()
            bridge.clear_actions()
            return _ok(actions=bridge.recent_actions(20))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)
