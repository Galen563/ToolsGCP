"""设置页兜底文案（语言文件里查不到时用这里的文案）。

⚠️ 必须放在模块级常量里，不要写进函数内部 —— 之前每次调用 get_text() 都重新构造一个
100 多项的字典，而设置页构建时 get_text 会被调用上百次，白白浪费算力。
"""

FALLBACK_TEXTS = {
    # ---- 标题 ----
    "settings_title": "Settings",
    "appearance": "Appearance",
    "startup": "Startup",
    "search_settings": "Search",
    "download_settings": "Downloads",
    "resource_source": "Resource source",
    "resource_source_tip": "Cloud: use the latest resource list published by the author.\nLocal: use a ToolsGCP-Resources.json on your own disk.",
    "resource_source_mode": "Source",
    "source_cloud": "Cloud (recommended)",
    "source_local": "Local file",
    "local_dir": "Folder",
    "choose_dir": "Choose folder",
    "current_index_file": "Current index file",
    "index_file_missing": "ToolsGCP-Resources.json was not found there",
    "local_dir_temp_notice": "Note: the local/cloud resource feature is still under development.",
    "search_card_size": "Search card size",
    "search_card_size_tip": "Change the size of search page cards. Takes effect immediately.",
    "card_size_small": "Small (more per screen)",
    "card_size_medium": "Medium (default)",
    "card_size_large": "Large (3 lines of description)",
    "function_settings": "Features",
    "dev_functions": "Developer features",
    "about": "About",

    # ---- 存储 ----
    "storage_section": "Storage",
    "storage_location": "Storage location",
    "storage_location_desc": "Config, chat history and logs are stored here",
    "storage_location_tip": "Resource files (library, icons, language packs) are not here; they ship with the app",
    "storage_pointer_file": "Location file",
    "storage_pointer_file_desc": "ToolsGCP.json records where that folder is; it is rebuilt automatically if missing or broken",
    "storage_change": "Change",
    "storage_reset": "Reset",
    "storage_choose_dir": "Choose where to store .ToolsGCP",
    "storage_confirm_title": "Migrate storage",
    "storage_confirm_body": "Migrate .ToolsGCP to",
    "storage_confirm_ok": "Migrate",
    "storage_confirm_cancel": "Cancel",
    "storage_preparing": "Preparing…",
    "storage_done": "Migration complete",
    "storage_success": "Migration succeeded",
    "storage_failed": "Migration failed",
    "storage_restart_hint": "Restart the app for it to fully take effect",
    "storage_reset_done": "Restored to the default location",
    "storage_same_path": "That folder is already the current location",
    "storage_invalid_target": "That location cannot be used",
    "storage_note": "Only configuration files live here. ToolsGCP-Resources.json is a resource file and is never moved.",

    # ---- 外观 ----
    "theme_mode": "Theme Mode", "language": "Language",
    "follow_system": "Follow System", "light_theme": "Light Theme", "dark_theme": "Dark Theme",
    "splash_screen": "Splash Screen",
    "splash_screen_tip": "Show splash screen on startup when enabled",
    "splash_screen_duration": "Splash Screen Duration",
    "splash_screen_duration_tip": "The splash duration slider exists because Python needs time to load resources",
    "seconds": "s",

    # ---- 快捷键 ----
    "hotkey_section": "Hotkeys",
    "hotkey_enable": "Enable Global Hotkeys",
    "hotkey_enable_tip": "Once enabled, the shortcut is exclusive to this app and other programs will not receive it",
    "hotkey_search": "Open Search Box",
    "hotkey_search_tip": "Pressing this shortcut from any program brings ToolsGCP to the front and focuses the search box",
    "hotkey_ai": "Open GCP-AI",
    "hotkey_ai_tip": "Pressing this shortcut from any program opens the GCP-AI panel",
    "hotkey_hint": "Click the box on the right and press the key combination you want. Esc cancels, Backspace clears.",
    "hotkey_reset": "Reset",
    "hotkey_register_failed": "Hotkey registration failed",
    # ⚠️ "hotkey_registered"（绿色的"已注册"）按需求删掉了：注册成功不再显示小字，只保留注册失败的提示
    "hotkey_failed": "Not active (taken or unusable)",

    # ---- 启动 ----
    "autostart": "Launch at startup",
    "minimize_to_tray": "Minimize to Tray on Startup",
    "minimize_to_tray_tip": "When enabled, the app will hide to tray on startup without showing the main window",
    "default_page": "Default Page",

    # ---- 搜索 ----
    "auto_search": "Auto Search",
    "auto_search_tip": "When enabled, search as you type; when disabled, press Enter or click search button",
    "show_github_button": "Show GitHub button",
    "show_github_button_tip": "Show the GitHub button on search cards (on by default)",
    "search_view_mode": "Search view",
    "search_view_mode_tip": "Tile: 4 large cards per row; Grid: 6 small cards, favourite only",
    "search_view_tile": "Tile",
    "search_view_grid": "Grid",
    # 在搜索页显示"视图切换按钮"（那个磁贴/网格的小分段控件）
    "show_view_switch": "Show the view switch on the search page",
    "show_view_switch_tip": ("Hides the tile/grid switch on the search toolbar and lets sorting move right. The \"Search page view\" option below still works."),

    # ---- 下载 ----
    "search_source": "Search Source", "download_source": "Download Source",
    "domestic_source": "Domestic Source", "github_source": "Github",
    "download_speed_limit": "Download Speed Limit",
    "download_speed_limit_tip": "Cap the download speed so it does not fill your bandwidth",
    "unlimited": "Unlimited", "limit": "Limit",
    "speed_limit_setting": "Speed limit",

    # ---- 功能 ----
    "close_mode": "Close Mode", "exit_directly": "Exit completely",
    "minimize_to_tray_option": "Minimize to tray",
    "notify": "Show notifications", "license": "GCP License Key",
    "license_tip": "Enter a valid key to unlock all features",
    "input_license": "Enter your GCP License Key",
    "verify": "Verify", "license_valid": "Key is valid", "license_invalid": "Invalid key",
    "license_saved": "Key saved",
    "available_keys": "Available GCP License Keys", "available_dev_keys": "Available Developer Keys",
    "notify_enabled": "Notifications on", "notify_disabled": "Notifications off",
    "close_mode_changed": "Close behavior updated",
    "open_settings_on_restart": "Open settings after restart",
    "debug_info": "Debug Info",
    "enabled": "Enabled", "disabled": "Disabled",

    # ---- 开发者 ----
    "developer_functions": "Developer Functions",
    "developer_identity_token": "Developer Identity Token",
    "dev_mode_tip": "Enter the correct key to unlock more hidden content, debugging features, and additional permissions",
    "input_dev_key": "Enter admin verification key",
    "admin_verified": "Admin Verified", "verify_time": "Verification Time",
    "dev_verify_success": "Developer identity token verified", "dev_key_invalid": "Developer identity token invalid",
    "dev_logout": "Developer mode exited", "logout": "Leave developer mode",
    "debug_info_enabled": "Show debug info",
    "coming_soon": "Coming soon…",

    # ---- AI / API（AI 开关 / API Key / 模型调用 合成一块）----
    "ai_section": "GCP-AI", "ai_enable": "Enable GCP-AI",
    "api_key_section": "API Key",
    "api_key_tip": "Enter the API key for third-party services. It will be stored in the local config file",
    "api_key_placeholder": "Please enter API Key",
    "show": "Show", "hide": "Hide", "save": "Save", "clear": "Clear",
    "api_key_saved": "API Key saved", "api_key_cleared": "API Key cleared",
    "model_name": "Model Name",
    "model_name_tip": "Enter the AI model name to use, saved together with the API Key",
    "model_name_placeholder": "Enter model name (e.g. gpt-4, claude-3, etc.)",
    "model_name_saved": "Model name and API Key saved",
    "model_calling": "Model Calling",
    "limit_token_output": "Limit token output",
    "limit_token_tip": "Cap the number of tokens in a single reply",
    "min_token": "Min tokens", "max_token": "Max tokens",
    "token_saved": "Token settings saved",

    # ---- AI 接口地址 / 服务商 / 上下文范围 / 回复模式 ----
    "ai_provider": "Provider",
    "ai_provider_tip": "Pick a provider and the model name and base URL below are filled in automatically. Both boxes are editable — type any model id or your own endpoint.",
    "ai_api_base": "API Base URL",
    "ai_api_base_tip": "OpenAI-compatible base URL, usually ending in /v1. Filled automatically from the provider; edit freely (a local model can use http://127.0.0.1:port/v1).",
    "ai_api_base_placeholder": "https://api.deepseek.com/v1",
    "ai_api_base_invalid": "The base URL must start with http:// or https:// and include a host name",
    "model_name_required": "Please choose or type a model name first",
    "ai_reply_mode": "Reply Mode",
    "ai_reply_mode_tip": "Controls answer length and detail. Concise: max 4 lines, conclusion only. Standard: within 6 lines, a pick plus one alternative. Professional: about 10 lines with key differences. No mode outputs code.",
    "ai_mode_standard": "Standard",
    "ai_mode_concise": "Concise",
    "ai_mode_professional": "Professional",
    "ai_reply_mode_saved": "Reply mode updated",
    "ai_context_window": "Context Window",
    "ai_context_tip": "How much chat history to send with each question. The full history is always saved on disk; longer context is more coherent but costs more tokens",
    "ai_context_full": "Whole session (longest memory)",
    "ai_context_10": "Last 10 rounds",
    "ai_context_20": "Last 20 rounds",
    "ai_context_30": "Last 30 rounds",
    "ai_context_saved": "Context window updated",

    # ---- AI 聊天抽屉（右侧抽屉界面用；键名以 ai_ 开头，走的是 settings 模块）----
    "ai_no_key_reply": "No <a href=\"toolsgcp://api_key\">API Key</a> configured yet — fill it in and we're good to go.",
    "ai_welcome": "Just say what you need — e.g. \"a tool to transfer files over my LAN\" — and I'll find it in the library.",
    "ai_new_chat": "New chat",
    "ai_history": "History",
    "ai_back": "Back",
    "ai_close_drawer": "Collapse",
    "ai_history_empty": "No conversations yet",
    "ai_history_empty_card": "This conversation is empty.",
    "ai_history_load_failed": "This conversation file can't be read; it may be corrupted",
    # 历史列表加载中那行字（和搜索页同一个加载动画，只换文案）
    "ai_history_loading": "Loading conversations",
    # 聊天区载入一段对话时的遮罩文案（同样复用搜索页的加载动画）
    "ai_chat_loading": "Loading conversation",
    # 输入框 / 气泡的圆角右键菜单
    "menu_copy": "Copy",
    "menu_paste": "Paste",
    "menu_cut": "Cut",
    "menu_undo": "Undo",
    "menu_select_all": "Select all",
    # 气泡操作栏上的按钮（独立小控件，不继承 BaseDrawer，走 _panel_text 查表）
    "msg_edit": "Rewrite this message",
    "msg_copy": "Copy",
    "msg_prev": "Previous version",
    "msg_next": "Next version",
    "msg_regen": "Regenerate this reply",
    # AI 面板里的悬浮提示
    "link_tip_open": "Click to open in the browser; Ctrl+Click to open inside the app",
    "mention_tip_detail": "Open the details page for \"{name}\"",
    "ai_delete_chat": "Delete this conversation",
    # "删除对话"确认框（历史抽屉里点垃圾桶时弹的那个）
    "ai_delete_title": "Delete conversation",
    "ai_delete_btn": "Delete",
    "ai_delete_confirm": "This can't be undone. Delete this conversation?",
    "cancel": "Cancel",
    "ai_deleted": "Conversation deleted",
    "ai_thinking": "Thinking…",
    "ai_stop": "Stop",
    "ai_stopped": "Generation stopped",
    "ai_input_placeholder": "Describe an app or site you want… (Enter to send, Shift+Enter for newline)",
    "ai_send": "Send",
    "ai_error_no_key": "No API Key configured. Please fill it in at Settings → API Key",
    "ai_error_no_model": "No model name configured. Please fill it in at Settings → API Key (e.g. deepseek-v4.1-flash)",
    "ai_error_failed": "Request failed",
    "ai_reply_stopped": "(response interrupted)",
    # @ 提及（输入框打 @ 弹资源候选；候选里的资源名在气泡里是蓝色下划线可点）
    "ai_resource_not_found": "No entry {code} in the library — it may have been removed.",
    "ai_mention_hint": "Type @ to pick an entry from the library",
    "ai_mention_tip": "Mention this entry to GCP-AI",

    # ---- 关于 ----
    "check_update": "Check for Updates", "check_update_btn": "Check Now",
    "checking_update": "Checking for updates...",
    "gcp_keys_title": "GCP License Keys",

    # ---- 更新下载渠道（下载区域里的下拉框）----
    "update_channel": "Update channel",
    "update_channel_tip": "Which releases \"Check for Updates\" accepts: Stable + Beta (default), Stable only, or Beta only.",
    "update_channel_all": "Stable + Beta",
    "update_channel_stable": "Stable only",
    "update_channel_beta": "Beta only",

    # ---- 检查更新：结果反馈 ----
    "update_is_latest": "You are on the latest version",
    "update_dir_fallback": "The program folder is not writable; the update was saved to your Downloads folder",

    # ---- 检查更新：更新弹窗 ----
    "update_dialog_title": "Update available",
    "update_dialog_available": "Update available",
    "update_badge_prerelease": "Beta",
    "update_badge_stable": "Stable",
    "update_fact_current": "Current version",
    "update_fact_latest": "Latest version",
    "update_fact_file": "File",
    "update_fact_size": "Size",
    "update_fact_published": "Published",
    "update_fact_notes": "Release notes",
    "update_notes_empty": "(This release has no notes)",
    "update_btn_download": "Download",
    "update_btn_later": "Later",
    "update_btn_open_page": "Release page",
    "update_btn_cancel": "Cancel",
    "update_btn_close": "Close",
    "update_btn_open_folder": "Open folder",
    "update_btn_restart_now": "Restart & update now",
    "update_btn_see_reasons": "Why?",
    "update_btn_know": "Got it",
    "update_download_ready_replace": ("Verified. Click \"Restart & update now\" to "
                                      "replace the program and launch the new version."),
    "update_download_cannot_replace": ("Verified, but this environment cannot replace "
                                       "the program automatically. Click \"Why?\" to see "
                                       "which case applies."),

    # ---- 自替换失败的"统一提示"（原因码 → 这里的一条）----
    "update_replace_failed_title": "Cannot replace automatically",
    "update_replace_failed_intro": ("The new version has been downloaded, but the program "
                                    "could not replace itself. The usual reasons are "
                                    "listed below:"),
    "update_replace_detected": "Detected this time:",
    "update_replace_other": "Other reasons that can also break the replacement:",
    "update_replace_reason_source_run": ("Running from source code (development state) — "
                                         "there is no ToolsGCP.exe in the folder to replace"),
    "update_replace_reason_no_exe": ("ToolsGCP.exe cannot be found in the current folder "
                                     "(deleted, or this is still a development folder)"),
    "update_replace_reason_stage": ("Copying the new version into the program folder failed "
                                    "(no disk space, not enough permission, or blocked by "
                                    "security software)"),
    "update_replace_reason_renamed": ("The program was renamed — the running file is not "
                                      "called ToolsGCP.exe"),
    "update_replace_reason_not_writable": ("The program folder is not writable (installed "
                                           "under Program Files, on a read-only or network "
                                           "drive)"),
    "update_replace_reason_script": ("The helper script cannot be written to the temp "
                                     "folder (temp folder not writable, or blocked by "
                                     "security software)"),
    "update_replace_reason_not_windows": ("This system is not Windows (the auto-replace "
                                          "script only works on Windows)"),
    "update_replace_manual_tip": ("New version file: {path}\nClick \"Open folder\" and "
                                  "rename it to ToolsGCP.exe to replace the old file "
                                  "manually."),

    # ---- 更新包下载 ----
    "update_download_title": "Downloading update",
    "update_download_starting": "Connecting…",
    "update_download_done": "Update downloaded",
    "update_download_done_tip": "Verified. The file is saved at the location below.",
    "update_download_done_warn": "Downloaded (with warnings)",
    "update_warn_too_small": "File may be incomplete",
    "update_warn_not_exe": "May not be a program file",
    "update_download_failed": "Download failed",
    "update_download_cancelled": "Download cancelled",
    "update_was_cancelled": "Cancelled",

    # ---- 检查更新：错误说明（错误码 → 这里的一条）----
    "update_err_no_release": "The author hasn't published any releases yet",
    "update_err_rate_limit": "GitHub API rate limit reached, please try again later",
    "update_err_network": "Network error, please check your connection and retry",
    "update_err_bad_response": "Unexpected response from the server, please try again later",
    "update_err_no_channel_release": "No release in the selected channel — try another channel",
    "update_err_no_asset": "ToolsGCP.exe was not found in this release",
    "update_err_timeout": "Checking for updates timed out, please try again later",
    "update_err_checksum": "Checksum mismatch — the download may be incomplete, please retry",
    "update_err_too_small": "The downloaded file is incomplete (unexpected size)",
    "update_err_not_exe": "The downloaded file is not an executable",
    "update_err_disk": "Failed to write the file — check disk space and permissions",
    "update_err_http": "Server returned an error",
    "update_err_unknown": "Failed to check for updates",

    # ---- 设置页自身的导航与搜索（新版两栏布局用）----
    "settings_search_hint": "Search settings…",
    "settings_search_none": "No matching setting",
    # 新版"行内副说明"用的文案（原来只有 ⓘ 悬停提示，说明藏在鼠标后面）
    "theme_mode_desc": "Follow the Windows light / dark setting",
    # ---- 组件配色（外观）----
    "accent_color": "Accent color",
    "accent_color_desc": "Colors of switches, dropdowns and sliders (the AI ball keeps its own colors)",
    "accent_blue": "Blue",
    "accent_purple": "Violet",
    "accent_orange": "Claude orange",
    "language_desc": "Takes effect after restarting the app",
    # ---- API Key 未保存拦截 ----
    "api_unsaved_title": "Unsaved changes",
    "api_unsaved_body": ("Provider / model / API base / API key have unsaved changes.\nChoose Save and continue, Discard changes, or Stay here."),

    # ---- 通用 ----
    "success": "Success", "error": "Error", "warning": "Warning", "info": "Info",
    "search_title": "Search", "home_page_title": "Home",
    "home_title": "Custom", "tools_gcp_title": "Favorites",
    "github_title": "Github", "deploy_title": "App Deploy",
    "feedback_title": "Feedback", "log_title": "View Logs",
    # ⚠️ 原来的 customize_title / customize_hint 已删除：定制页早就不是空页了，这两个键没有任何代码在读；
    #    但 nav_language.json 里的 "customize"（左侧栏那一项的显示名）不能删 —— 删了侧边栏就没字了。
    "autostart_enabled": "Auto-start enabled",
    "autostart_disabled": "Auto-start disabled",
    "autostart_failed": "Failed to set auto-start",
}
