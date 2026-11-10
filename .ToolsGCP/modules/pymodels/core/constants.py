"""[已废弃] 仅为兼容 `from ..core.constants import XXX`，常量统一由 pymodels/constants.py 提供。"""

from ..constants import *          # noqa: F401,F403
from ..constants import (          # 显式再导出一次，方便 IDE 跳转
    APP_NAME, APP_VERSION, APP_AUTHOR,
    IS_AUTOSTART, OPEN_SETTINGS,
    SCRIPT_DIR, CONFIG_DIR, DATA_DIR, CHATS_DIR, PLUGIN_DATA_DIR,
    LANGUAGES_DIR, IMAGES_DIR,
    LOGS_DIR, LOG_HISTORY_DIR, LOG_CURRENT_FILE, LOG_FILE_PREFIX, LOG_MAX_HISTORY,
    VALID_GCP_KEYS, DEV_KEYS, SPECIAL_KEYS, SOURCE_OPTIONS,
    DEFAULT_SETTINGS,
)
