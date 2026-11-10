"""设置管理模块；设置落盘在 .ToolsGCP/config/toolsgcp_config.json（见 core/data_dir.py）"""

import json
import os
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

                    # ---------- 一次性默认值迁移 ----------
                    # ⚠️ 只改 DEFAULT_SETTINGS 没用：键在用户首次启动时就已按旧默认值落盘，
                    #    "键存在"所以合并默认值不会碰它。这里用迁移标记做一次性修正，
                    #    用户之后自己关掉就不会再被覆盖。
                    if not settings.get("_migrated_show_github_default", False):
                        settings["search_show_github"] = True
                        settings["_migrated_show_github_default"] = True
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

    # ---------- API Key（加密存储） ----------
    def get_api_key(self) -> str:
        """读取 API Key（密文在配置里，这里返回明文）

        兼容旧配置：老版本明文存在 "api_key"，直接返回；下次 set_api_key() 后迁移成密文。
        """
        encrypted = self.settings.get("api_key_enc", "")
        if encrypted:
            return unprotect(encrypted)
        return str(self.settings.get("api_key", "") or "")

    def set_api_key(self, value: str):
        """保存 API Key（DPAPI 加密后写入 api_key_enc，明文键清空）"""
        value = str(value or "")
        if not value:
            self.settings["api_key_enc"] = ""
            self.settings["api_key"] = ""
        else:
            self.settings["api_key_enc"] = protect(value)
            # 清掉可能残留的明文
            self.settings["api_key"] = ""
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

        ⚠️ 现在统一返回 "Github"：「国内源」已从界面去掉，老配置里存的"国内源"会让
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
