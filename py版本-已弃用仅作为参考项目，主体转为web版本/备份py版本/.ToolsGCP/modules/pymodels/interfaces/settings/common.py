"""设置页共用常量与工具。

⚠️ 颜色优先用 .theme 的 token（tokens()）；下面两个默认文字色只用于把置灰标签恢复成普通颜色。
"""

import sys

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QColor

from ...core.language_manager import LanguageManager
from ...core.settings_manager import SettingsManager
from .theme import DARK, LIGHT

from .texts import FALLBACK_TEXTS

# 联动置灰时用的灰色
DISABLED_TEXT_COLOR = QColor(LIGHT["text_disabled"])
# 恢复可用状态时用的默认文字色
DEFAULT_TEXT_LIGHT = QColor(LIGHT["text"])
DEFAULT_TEXT_DARK = QColor(DARK["text"])

# 默认启动页顺序：与左侧导航栏一致；内部键沿用旧值（"部署"），已有配置不会被重置
PAGE_ORDER = ["首页", "搜索", "定制页", "收藏", "部署", "设置"]

# 两个全局快捷键的默认值
# ⚠️ RegisterHotKey 不能拿 Caps Lock 做主键（会返回"已被占用"），故 AI 用 Ctrl+Alt+G，启动时迁移老的 Ctrl+Caps
HOTKEY_DEFAULTS = {"search": ("hotkey_search", "Ctrl+Q"),
                   "ai": ("hotkey_ai", "Ctrl+Alt+G")}


class SettingsSaveDebouncer:
    """把连续的小改动合并成一次落盘（停手 SCHEDULE_MS 之后统一写）。"""

    SCHEDULE_MS = 400

    def __init__(self, owner, settings_manager):
        self._owner = owner
        self._manager = settings_manager
        self._pending = {}
        self._timer = QTimer(owner)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.flush)

    def set(self, key, value):
        """记下待保存的值（同一个键只保留最后一次）"""
        if self._manager.settings.get(key) == value and key not in self._pending:
            return
        self._pending[key] = value
        self._timer.start(self.SCHEDULE_MS)

    def flush(self):
        """立刻把所有待保存的写下去"""
        if not self._pending:
            return
        pending, self._pending = self._pending, {}
        for key, value in pending.items():
            self._manager.update_setting(key, value)
