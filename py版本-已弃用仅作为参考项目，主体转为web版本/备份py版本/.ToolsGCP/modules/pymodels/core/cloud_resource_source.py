"""资源来源：云端 / 本地。

云端 = 从作者的服务器 / GitHub 拉最新资源索引（用户不用更新程序就能看到新收录）；
本地 = 直接读磁盘上的 ToolsGCP-Resources.json（用户自己改过，或开发者调试）。
默认云端。

⚠️ CloudResourceSource 目前是空骨架（所有方法都拿不到数据，等同于读本地缓存）。
接云端时要补：SOURCE_URL、fetch() 里放开注释的 requests 代码（带 304 判断、下载到
临时文件 + json 校验 + os.replace 原子替换、超时重试、schema_version 校验）、
is_available() 的 HEAD 探活。上层界面一行都不用改。
"""

import json
import os

from ..constants import CONFIG_DIR

# 本地资源索引的默认位置：程序目录下的 .ToolsGCP/ToolsGCP-Resources.json
RESOURCE_FILE_NAME = "ToolsGCP-Resources.json"
DEFAULT_LOCAL_DIR = CONFIG_DIR

# 云端资源索引地址（占位，等确定后替换）
SOURCE_URL = ""

# 下载到本地的缓存文件（云端拉下来的会先存这里）
CLOUD_CACHE_FILE = os.path.join(CONFIG_DIR, "ToolsGCP-Resources.cloud.json")

# 网络超时（秒）与重试次数
TIMEOUT_SECONDS = 8
MAX_RETRY = 2


def local_dir_from_settings(settings_manager) -> str:
    """取用户设置的本地资源目录；没设过就用程序自带的 .ToolsGCP"""
    if settings_manager is None:
        return DEFAULT_LOCAL_DIR
    directory = str(settings_manager.settings.get("local_resource_dir") or "").strip()
    return directory or DEFAULT_LOCAL_DIR


def resolve_resource_file(settings_manager=None) -> str:
    """按当前设置算出「该读哪个资源索引文件」

    这是全程序唯一的判断点，搜索页 / 资源详情都走它，保证行为一致。
    """
    source = "cloud"
    if settings_manager is not None:
        source = str(settings_manager.settings.get("resource_source") or "cloud")

    if source == "local":
        return os.path.join(local_dir_from_settings(settings_manager), RESOURCE_FILE_NAME)

    # 云端：优先用云端缓存，没有缓存就退回本地自带的
    if os.path.exists(CLOUD_CACHE_FILE):
        return CLOUD_CACHE_FILE
    return os.path.join(settings_manager and CONFIG_DIR or DEFAULT_LOCAL_DIR,
                        RESOURCE_FILE_NAME)


class CloudResourceSource:
    """云端资源索引（目前是空实现，只保证接口存在）"""

    def __init__(self, url: str = SOURCE_URL, cache_file: str = CLOUD_CACHE_FILE):
        self.url = url
        self.cache_file = cache_file
        self.last_error = ""

    # ---------- 状态 ----------
    def is_available(self) -> bool:
        """云端是否可用（还没接网络，先当作不可用）"""
        return False

    def configured(self) -> bool:
        """有没有配置过云端地址"""
        return bool(self.url)

    # ---------- 取数据 ----------
    def get_index_path(self) -> str:
        """返回可以直接读的云端索引文件路径；拿不到返回空串（接上网络后：拉取→校验→写缓存）"""
        return ""

    def fetch(self, force: bool = False) -> bool:
        """从云端拉取最新索引，成功返回 True（**还没实现**）"""
        self.last_error = "云端资源源还没实现"
        return False

    def clear_cache(self):
        """清掉云端缓存，下次会重新拉"""
        try:
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
        except Exception:
            pass

    # ---------- 辅助 ----------
    def read_cache(self) -> dict:
        """读本地缓存（没有或坏了就返回空 dict）"""
        if not os.path.exists(self.cache_file):
            return {}
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
