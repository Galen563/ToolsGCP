"""
ToolsGCP Python Models Package
"""

# ⚠️ 版本号**不要在这里写第二份**。唯一事实来源是 constants.APP_VERSION
#    （以前这里是 "1.0.0"，和 constants 里的号对不上，改版本时极容易改错文件）。
from .constants import APP_VERSION as __version__   # noqa: F401
from .constants import APP_AUTHOR as __author__     # noqa: F401

__all__ = ["__version__", "__author__"]
