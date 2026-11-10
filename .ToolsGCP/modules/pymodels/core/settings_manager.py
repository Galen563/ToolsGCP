"""设置管理模块；设置落盘在 .ToolsGCP/config/toolsgcp_config.json（见 core/data_dir.py）"""

import json
import os
import re
from ..constants import DATA_DIR, DEFAULT_SETTINGS
from ..utils.secret_store import protect, unprotect


class SettingsManager:
    """设置管理器：整个配置读进 self.settings 放内存；写用 update_setting()（会落盘并记日志）"""

    def __init__(self, config_dir=None):
        # config_dir 可显式传其它目录（测试、便携模式）
        if config_dir is None:
            config_dir = DATA_DIR
        self.config_dir = config_dir
        self.config_file = os.path.join(config_dir, "toolsgcp_config.json")
        self.settings = self.load_settings()
    
    def load_settings(self):
        """加载设置"""
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    
                    # 合并默认设置
                    for key, default_value in DEFAULT_SETTINGS.items():
                        if key not in settings:
                            settings[key] = default_value
                        
                        # 类型修正
                        if key == "splash_screen_duration":
                            try:
                                val = int(settings[key])
                                if val < 1:
                                    val = 1
                                elif val > 5:
                                    val = 5
                                settings[key] = val
                            except (ValueError, TypeError):
                                settings[key] = 2
                        elif key in ["startup_with_windows", "minimize_to_tray", "notify_enabled", 
                                   "open_settings_on_restart", "dev_mode_enabled",
                                   "debug_info_enabled_Galen563", "debug_info_enabled_Cyric373",
                                   "download_speed_limit_enabled", "splash_screen_enabled",
                                   "deploy_mode"]:
                            settings[key] = bool(settings[key])
                        elif key == "download_speed_limit":
                            try:
                                val = int(settings[key])
                                if val < 1:
                                    val = 1
                                elif val > 300:
                                    val = 300
                                settings[key] = val
                            except (ValueError, TypeError):
                                settings[key] = 100
                        elif key == "download_threads":
                            # 多线程下载并发数（1~100）。旧配置里可能是字符串 / 浮点，
                            # 一律夹到合法区间，夹不住就用默认值 100。
                            try:
                                val = int(settings[key])
                                if val < 1:
                                    val = 1
                                elif val > 100:
                                    val = 100
                                settings[key] = val
                            except (ValueError, TypeError):
                                settings[key] = 100
                        elif key == "download_retry_count":
                            # 失败重试次数（1~20）。
                            try:
                                val = int(settings[key])
                                if val < 1:
                                    val = 1
                                elif val > 20:
                                    val = 20
                                settings[key] = val
                            except (ValueError, TypeError):
                                settings[key] = 5
                        elif key == "download_save_dir":
                            # 下载保存位置。空串 = 系统下载文件夹（由后端解析），
                            # 非空必须是绝对路径；相对路径按当前工作目录解析容易指向奇怪的地方，
                            # 这里统一转成绝对路径再用。
                            raw = str(settings[key] or "").strip()
                            if raw:
                                try:
                                    settings[key] = os.path.abspath(os.path.expanduser(raw))
                                except Exception:
                                    settings[key] = ""
                            else:
                                settings[key] = ""
                        elif key == "releases_source":
                            # Releases 弹窗下拉框（official / all）。
                            raw = str(settings[key] or "").strip().lower()
                            settings[key] = raw if raw in ("official", "all") else "official"

                    # ---------- 一次性默认值迁移 ----------
                    # ⚠️ 只改 DEFAULT_SETTINGS 没用：键在用户首次启动时就已按旧默认值落盘，
                    #    "键存在"所以合并默认值不会碰它。这里用迁移标记做一次性修正，
                    #    用户之后自己关掉就不会再被覆盖。
                    if not settings.get("_migrated_show_github_default", False):
                        settings["search_show_github"] = True
                        settings["_migrated_show_github_default"] = True
                        self.save_settings(settings)

                    # 需求：启动动画**默认关闭**（老配置里是 True，这里一次性改掉；
                    #       用户之后自己想开就自己开，不会被再次覆盖）
                    if not settings.get("_migrated_splash_default", False):
                        settings["splash_screen_enabled"] = False
                        settings["_migrated_splash_default"] = True
                        self.save_settings(settings)

                    # 需求：主题效果 / 侧栏悬停展开 / 提示框位置 三个新键给默认值
                    if not settings.get("_migrated_ui_defaults", False):
                        settings["theme_effect"] = "mica"
                        settings["nav_hover_expand"] = False
                        settings["toast_position"] = "top"
                        settings["_migrated_ui_defaults"] = True
                        self.save_settings(settings)

                    # ⚠️ 提示框位置默认改成顶端居中（以前是右上角）。
                    #    只改 DEFAULT_SETTINGS 对老用户无效（键已经按旧值落盘了），
                    #    所以这里用一次性迁移标记改掉 —— 改完打标记，用户之后自己调就不会被覆盖。
                    if not settings.get("_migrated_toast_position_top", False):
                        settings["toast_position"] = "top"
                        settings["_migrated_toast_position_top"] = True
                        self.save_settings(settings)

                    # 需求：「首页」（海报轮播页）已整体删除，老配置里 default_page
                    #       可能还是 "首页" —— 那是个已经不存在的页面，留着会让
                    #       设置页的下拉框显示一个非法值（前端虽有 || 'search' 兜底，
                    #       但配置里仍然是脏值，下次读取还是脏的）。一次性迁成「搜索」。
                    # ⚠️ 用标记位而不是"值等于首页就改"：万一以后又加回同名页面，
                    #    用户自己选的值得以保留、不会被这段老代码反复改写。
                    if not settings.get("_migrated_home_removed", False):
                        if str(settings.get("default_page") or "").strip() == "首页":
                            settings["default_page"] = "搜索"
                        settings["_migrated_home_removed"] = True
                        self.save_settings(settings)

                    # ⚠️⚠️ 浏览器模式快捷键的遗留默认值迁移，**连着两轮**：
                    #    第 1 轮 `_migrated_browser_hotkey_caps`：最早的默认值 Ctrl+D → 当时的默认值；
                    #    第 2 轮 `_migrated_browser_hotkey_shift`：第 1 轮的产物 Ctrl+Caps+O
                    #            → 现在的默认值 Ctrl+Shift+O（已经跑过第 1 轮的用户也要跟着迁）。
                    #    为什么改 DEFAULT_SETTINGS 不够：`hotkey_browser` 这个键在老版本
                    #    就以旧默认值 "Ctrl+D" **落过盘**了，"键存在" → 上面的合并默认值
                    #    永远不会碰它 → 新默认值形同虚设。
                    #    后果是真实的（日志 ToolsGCP-2026-11-06-002734027.log 实证）：
                    #      "在浏览器中打开 已注册: Ctrl+D" → 值里不含 Caps
                    #      → shell.apply_hotkey_settings 分流时 caps_rules 是**空的**
                    #      → capskeyhook 那条全局键盘钩子根本没 start()
                    #      → 用户按 Ctrl+Caps+O 完全没反应。
                    #    ⚠️ 标记键**绝不能**加进 DEFAULT_SETTINGS：上面的合并循环会先把它
                    #       补成 True，这段迁移就永远是死代码（老配置里的旧值迁不掉）。
                    #    两轮都**只认"旧默认值本身"**（大小写与空格不敏感，
                    #    "+" 是序列的一部分、不能去掉）：用户自己录的 Ctrl+Shift+B、
                    #    Win+T 等一律不动；迁完打标记，用户之后自愿改回旧值也不再翻。
                    if not settings.get("_migrated_browser_hotkey_caps", False):
                        legacy = str(settings.get("hotkey_browser") or "")
                        legacy = "".join(legacy.split()).strip().lower()
                        if legacy in ("ctrl+d", "control+d"):    # 就是那个最早的默认值
                            settings["hotkey_browser"] = DEFAULT_SETTINGS.get(
                                "hotkey_browser", "Ctrl+Shift+O")
                        settings["_migrated_browser_hotkey_caps"] = True
                        self.save_settings(settings)

                    # 第 2 轮：上一版默认值 Ctrl+Caps+O（第 1 轮迁出来的结果）→ Ctrl+Shift+O。
                    # ⚠️ 同样只认这一个遗留值：用户自己录的 Ctrl+Caps+P / Ctrl+D 都不动。
                    #    新装用户拿到的是 DEFAULT_SETTINGS 里的 Ctrl+Shift+O，判据不成立。
                    if not settings.get("_migrated_browser_hotkey_shift", False):
                        legacy = str(settings.get("hotkey_browser") or "")
                        legacy = "".join(legacy.split()).strip().lower()
                        if legacy in ("ctrl+caps+o", "control+caps+o"):
                            settings["hotkey_browser"] = DEFAULT_SETTINGS.get(
                                "hotkey_browser", "Ctrl+Shift+O")
                        settings["_migrated_browser_hotkey_shift"] = True
                        self.save_settings(settings)

                    return settings
            else:
                self.save_settings(DEFAULT_SETTINGS)
                return DEFAULT_SETTINGS.copy()
                
        except Exception as e:
            from ..utils.logger import log
            log.err("设置", "settings", f"加载设置时出错: {e}")
            return DEFAULT_SETTINGS.copy()
    
    def save_settings(self, settings):
        """保存设置"""
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            from ..utils.logger import log
            log.err("设置", "settings", f"保存设置时出错: {e}")
    
    def update_setting(self, key, value):
        """更新单个设置（每次修改都记一条 OP 日志）
        ⚠️ 自检/测试脚本请设 TOOLSGCP_NO_SETTINGS_WRITE=1，那样只改内存不落盘，
        否则脚本会把用户真实配置改掉。
        """
        old = self.settings.get(key, None)
        self.settings[key] = value
        if not os.environ.get("TOOLSGCP_NO_SETTINGS_WRITE"):
            self.save_settings(self.settings)
        from ..utils.logger import log
        log.op("设置", "update", key=key, old=old, new=value)
    
    def get_debug_info_key(self, admin_name):
        """获取指定管理员的调试信息设置键名"""
        return f"debug_info_enabled_{admin_name}"

    # ---------- API Key（按服务商分槽加密存储） ----------
    # ⚠️ 为什么按服务商分槽：API Key 是“跟着服务商走”的（DeepSeek 的 Key 打不了 Kimi），
    #    老版本只有一个 api_key_enc 槽，用户切服务商后会把上一个服务商的 Key 继续发给
    #    新服务商 → 401「API Key 无效」（日志里就有一例：测过 Kimi/Qwen 后切回 DeepSeek
    #    发送，服务端收到的是别的服务商的 Key）。现在每个服务商一个槽
    #    `api_key_enc_<pid>`，切换互不干扰；旧单槽 api_key_enc / api_key 在首次读取时
    #    一次性迁移到“当时正在用的服务商”，之后不再当作全局 Key。
    _PROVIDER_SLOT_RE = re.compile(r"^[a-z0-9_]{1,40}$")

    def _normalize_provider(self, provider=None) -> str:
        pid = str(provider or "").strip().lower()
        if not pid:
            pid = str(self.settings.get("ai_provider", "deepseek") or "deepseek").strip().lower()
        return pid if self._PROVIDER_SLOT_RE.match(pid) else "custom"

    def _key_slot(self, provider=None) -> str:
        return f"api_key_enc_{self._normalize_provider(provider)}"

    def get_api_key(self, provider=None) -> str:
        """读取某个服务商的 API Key（密文在配置里，这里返回明文）
        兼容旧配置：老版本明文存在 "api_key"、密文存在 "api_key_enc"，
        首次读取时把旧 Key 归到“当前正在用的服务商”并清掉旧槽（一次性迁移）。
        """
        from ..utils.secret_store import sanitize_api_key, unprotect
        slot = self._key_slot(provider)
        stored = self.settings.get(slot, "")
        if stored:
            return sanitize_api_key(unprotect(stored))
        # 旧单槽迁移：只把旧 Key 迁到“当前服务商”，其它服务商读不到
        legacy = self.settings.get("api_key_enc", "") or self.settings.get("api_key", "")
        if legacy:
            try:
                plain = unprotect(legacy)
                self.settings[slot] = legacy
                self.settings["api_key_enc"] = ""
                self.settings["api_key"] = ""
                if not os.environ.get("TOOLSGCP_NO_SETTINGS_WRITE"):
                    self.save_settings(self.settings)
                return sanitize_api_key(plain)
            except Exception:
                # 旧槽读不出来就当没有（不抛，界面继续可用）
                pass
        return ""

    def set_api_key(self, value, provider=None):
        """保存某个服务商的 API Key（DPAPI 加密后写该服务商槽，明文旧槽清空）

        ⚠️ 本轮修复「手动清空输入框后点保存，存储里还是旧 Key」：
           空值**必须真的落盘**，而且要连旧单槽一起清 ——
           旧写法只在本分支把 `api_key` 明文槽清掉，`api_key_enc` 旧密文槽留着不动；
           于是下次 `get_api_key()` 走进「旧单槽迁移」分支，把那条旧密文**又迁回当前
           服务商槽**，用户看到的就是"明明清了空、重开还是配置好的状态"。
           同理 `save_settings` 不能被跳过：空槽不写盘，配置文件里仍是老密文。
        """
        from ..utils.secret_store import protect, sanitize_api_key
        value = sanitize_api_key(value)
        slot = self._key_slot(provider)
        if not value:
            # 显式空值：本服务商槽删除（不是写 ""，避免 get 时 falsy 判断歧义），
            # 并把两个旧槽一并清掉，杜绝上面说的"迁移回魂"。
            self.settings.pop(slot, None)
            self.settings["api_key_enc"] = ""
            self.settings["api_key"] = ""
        else:
            self.settings[slot] = protect(value)
            # 清掉可能残留的明文旧槽，避免下次 get_api_key 又把旧值迁回来
            self.settings["api_key"] = ""
            self.settings["api_key_enc"] = ""
        self.save_settings(self.settings)

    def has_api_key(self, provider=None) -> bool:
        return bool(self.get_api_key(provider))

    # ---------- API Key（按**服务商档案**分槽；本轮档案重构新增） ----------
    # ⚠️⚠️ 为什么还要再分一层：上一轮把服务商配置改成"档案卡片列表"后，Key 仍然只按
    #    **厂商**分槽（api_key_enc_<pid>）。用户随即要求「同厂商也是要独立的」——
    #    同一家厂商存两条档案（例如两套 DeepSeek 账号 / 一个官方一个中转）时，
    #    共用一把 Key 就直接矛盾：改一条会污染另一条。
    #    所以 Key 的主键跟着档案走：`api_key_enc_<档案id>`。
    #    厂商槽**不删**，只作为迁移来源与"没有档案 id 的旧调用方"的兜底。
    _PROFILE_SLOT_RE = re.compile(r"^[a-f0-9]{4,40}$")

    def _profile_slot(self, profile_id) -> str:
        pid = str(profile_id or "").strip().lower()
        # id 是 uuid hex；不合法就退回厂商口径（老调用方传 provider 进来也不会炸）
        return f"api_key_enc_{pid}" if self._PROFILE_SLOT_RE.match(pid) else ""

    def get_profile_api_key(self, profile_id, provider=None) -> str:
        """读某条档案**自己**的 Key。

        ⚠️⚠️ 这里**不做**"厂商槽兜底复制"（上一轮我这么写过，是错的）：
           同厂商可以有多条档案，如果每条读不到自己的槽就去复制厂商槽，
           结果所有档案都变成"有 Key"，优先级判定和"未填 Key 不显示"全部失真
           （本轮自验脚本抓到的真 bug：删掉 active 后没有落到预期的下一条）。
           迁移只在 `_adopt_legacy_provider_key` 里**显式做一次**，
           并且只给指定那一条。
        """
        from ..utils.secret_store import sanitize_api_key, unprotect
        slot = self._profile_slot(profile_id)
        if not slot:
            return self.get_api_key(provider)
        stored = self.settings.get(slot, "")
        if stored:
            return sanitize_api_key(unprotect(stored))
        return ""

    def adopt_legacy_provider_key(self, profile_id, provider=None) -> bool:
        """把厂商旧槽的 Key **一次性**交给指定档案（迁移专用，调用方负责挑那唯一一条）

        返回是否真的搬了。搬完就把厂商槽清掉，避免第二条档案再复制一次
        （"复制"会变成"两家共用"，与用户要的独立相悖）。
        """
        from ..utils.secret_store import sanitize_api_key, unprotect
        slot = self._profile_slot(profile_id)
        if not slot or self.settings.get(slot):
            return False
        legacy_slot = self._key_slot(provider)
        legacy = self.settings.get(legacy_slot, "") or self.settings.get("api_key_enc", "") \
            or self.settings.get("api_key", "")
        if not legacy:
            return False
        try:
            plain = sanitize_api_key(unprotect(legacy))
        except Exception:
            return False
        if not plain:
            return False
        self.settings[slot] = legacy
        # 搬完删掉来源：厂商槽现在是"档案槽"的派生概念，不再作为独立存储
        for junk in (legacy_slot, "api_key_enc", "api_key"):
            if junk in self.settings:
                self.settings[junk] = ""
        if not os.environ.get("TOOLSGCP_NO_SETTINGS_WRITE"):
            self.save_settings(self.settings)
        return True

    def set_profile_api_key(self, value, profile_id, provider=None):
        """把 Key 写进这条档案自己的槽（空值 = 删槽，并清掉可能被复制回来的旧值来源）"""
        from ..utils.secret_store import protect, sanitize_api_key
        value = sanitize_api_key(value)
        slot = self._profile_slot(profile_id)
        if not slot:
            # 没有合法档案 id：退回厂商槽（保持老行为，绝不静默丢 Key）
            return self.set_api_key(value, provider)
        if value:
            self.settings[slot] = protect(value)
        else:
            self.settings.pop(slot, None)
        self.save_settings(self.settings)

    def has_profile_api_key(self, profile_id, provider=None) -> bool:
        return bool(self.get_profile_api_key(profile_id, provider))

    def profile_key_tail(self, profile_id, provider=None) -> str:
        """档案 Key 的尾号（绝不回传明文）"""
        value = self.get_profile_api_key(profile_id, provider) or ""
        return ("****" + value[-4:]) if len(value) >= 4 else ("*" * len(value))

    def drop_profile_key_slot(self, profile_id) -> None:
        """档案被删除时清掉它的 Key 槽（用户原话：删档案「它的 API Key 也会一起清除」）"""
        slot = self._profile_slot(profile_id)
        if slot and slot in self.settings:
            self.settings.pop(slot, None)
            self.save_settings(self.settings)

    def key_tail(self, provider=None) -> str:
        """只给尾号，绝不回传明文（错误提示里让用户核对是哪把 Key）"""
        value = self.get_api_key(provider) or ""
        return ("****" + value[-4:]) if len(value) >= 4 else ("*" * len(value))

    # ---------- 接口地址（同样按服务商分槽） ----------
    # ⚠️ 本轮修复用户报的"串台大 bug"：设置里服务商=openai（全局 api_base 存的是
    #    https://api.openai.com/v1），从输入框模型弹层选了 DeepSeek 的模型聊天，
    #    请求却打到 openai 的地址（报错文案：服务商 DeepSeek、接口 openai）。
    #    根因：api_base 是**全局单槽**，而 Key 早已按服务商分槽（api_key_enc_<pid>）、
    #    模型/服务商也会随选择变 —— 三样东西里只有地址不跟服务商走，必然串。
    #    现在地址也分槽：`api_base_<pid>`，与 Key 完全同一套规范化/迁移规则。
    def get_api_base(self, provider=None) -> str:
        """读取某个服务商**显式设置过**的接口地址（没有返回空串，由调用方决定默认值）。
        兼容旧配置：第一次读某服务商时，若分槽为空、而旧全局 api_base 的 host 正好
        属于该服务商（providers.guess_provider 判定），把旧值迁进该槽再用
        （不猜测"猜不出属于谁"的旧值 —— 那是自定义中转地址，留给 custom 兜底）。
        """
        pid = self._normalize_provider(provider)
        slot = f"api_base_{pid}"
        stored = str(self.settings.get(slot, "") or "").strip()
        if stored:
            return stored
        legacy = str(self.settings.get("api_base", "") or "").strip()
        if legacy:
            try:
                from .ai import providers as ai_providers
                if ai_providers.guess_provider(legacy) == pid and pid != "custom":
                    self.settings[slot] = legacy
                    self.save_settings(self.settings)
                    return legacy
            except Exception:                               # noqa: BLE001
                pass
        return ""

    def set_api_base(self, value, provider=None):
        """把接口地址写进对应服务商槽（空值=删槽，回退官方默认地址）"""
        pid = self._normalize_provider(provider)
        slot = f"api_base_{pid}"
        text = str(value or "").strip()
        if text:
            self.settings[slot] = text
        else:
            self.settings.pop(slot, None)
        self.save_settings(self.settings)
    
    def get_debug_info_enabled(self, admin_name):
        """获取指定管理员的调试信息开关状态"""
        key = self.get_debug_info_key(admin_name)
        return self.settings.get(key, False)
    
    def set_debug_info_enabled(self, admin_name, enabled):
        """设置指定管理员的调试信息开关状态"""
        key = self.get_debug_info_key(admin_name)
        self.update_setting(key, enabled)
    
    def get_default_source_by_language(self, language):
        """返回默认下载源
        ⚠️ 现在统一返回 "Github"：国内源已从界面去掉，老配置里存的"国内源"会让
        `SOURCE_OPTIONS.index(...)` 抛 ValueError，导致设置页整块打不开。
        """
        return "Github"
    
    def get_download_speed_limit(self):
        """获取下载限速值（MB/s），如果未启用返回0表示无限制"""
        if not self.settings.get("download_speed_limit_enabled", False):
            return 0
        return self.settings.get("download_speed_limit", 100)
    
    def is_download_speed_limited(self):
        """检查是否启用了下载限速"""
        return self.settings.get("download_speed_limit_enabled", False)
    
    def get_splash_screen_duration_ms(self):
        """获取启动动画时长（毫秒）"""
        seconds = self.settings.get("splash_screen_duration", 2)
        return seconds * 1000
