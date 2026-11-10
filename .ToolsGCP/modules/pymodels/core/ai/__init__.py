"""GCP-AI 的核心逻辑，不依赖 Qt，可单独测试。
providers/chat_store/prompt/client 各自独立，worker.py 负责放进 QThread 交给界面。
"""

from .chat_store import ChatSession, ChatStore
from .prompt import (MODE_CONCISE, MODE_PROFESSIONAL, MODE_STANDARD, build_messages,
                     build_resource_catalog, extract_keyword)
from .client import ChatResult, chat, normalize_api_base, is_valid_api_base
from .providers import (DEFAULT_PROVIDER, PROVIDERS, default_model, get_provider,
                        guess_provider, models_of)

__all__ = [
    "ChatSession", "ChatStore",
    "build_messages", "build_resource_catalog", "extract_keyword",
    "MODE_STANDARD", "MODE_CONCISE", "MODE_PROFESSIONAL",
    "ChatResult", "chat", "normalize_api_base", "is_valid_api_base",
    "PROVIDERS", "DEFAULT_PROVIDER", "get_provider", "models_of",
    "default_model", "guess_provider",
]
