"""隐私同意的**落盘状态**（不依赖 PyQt5 的纯 Python 版）。
========== 这个文件到底在哪（用户最常问的问题）==========
    `<当前数据根>/config/privacy_policy.json`
    默认 = `<用户主目录>\\.ToolsGCP\\config\\privacy_policy.json`
（"当前数据根"由 core/data_root.py 按 `%USERPROFILE%\\ToolsGCP.json` 指针解析；
  用户在设置里改过存储位置，它就跟着**新位置**走，旧目录里不会再留一份。）
所以："删掉这个数据根（设置 → 存储里显示的那个 .ToolsGCP）" = 同意记录一起没了
      = 下次启动**必须重新同意**（`load()` 找不到文件就返回 consent_given=False）。
⚠️ 程序目录旁的 `.ToolsGCP` 是**资源目录**，里面的 `config/privacy_policy.json`
   即使还是旧备份，也**不会**被反向迁移带回用户数据根（data_root._REVERSE_SKIP_FILES）——
   这条是修过的真实 bug：以前反向迁移会把"已同意"从程序目录复制回来，导致删了数据根
   也不重新弹窗。
========== 为什么单独写一份 ==========
原版 `ui/privacy_consent.py` 的 `PrivacyManager` 带着一堆 PyQt5 / qfluentwidgets
import（它同时管对话框）。而桌面外壳有一条**硬约束**（见 desktop/splash.py 的长注释）：
    ⚠️ 只要主线程 import 过 PyQt5（哪怕只是 import 而不建对象），
       进程退出时就会 100% 以 0xC0000005（访问违例）崩掉（8/8 复现）。
所以 Web 版外壳**绝不**在主线程 import 那个模块。但"同意记录"必须落盘、且要带
哈希校验（否则用户改个 json 就能绕过），于是这里把状态那部分原样搬成纯 Python：
    · 文件位置：`<数据根>/config/privacy_policy.json`（和原版同一个文件）
    · 字段：consent_given / consent_version / consent_timestamp / consent_hash
    · 哈希算法、盐值、版本号全部与原版逐字一致（`_PRIVACY_HASH_SALT`、V1.0）
    · 三语说明注释也照抄，用户打开这个 json 看得懂
这样原版 Qt 程序与 Web 版外壳写的是**同一份文件**：在原版里同意过，Web 版直接认。
⚠️ **只认当前数据根上的文件，不做任何进程内缓存**：每次启动都重新读盘
   （AppShell 用 `PrivacyState(DATA_DIR)` 新建实例）。删了文件就一定是"没同意"。
"""

import hashlib
import json
import os
import threading
from datetime import datetime

# 内置防篡改校验密钥（⚠️ 与原版 privacy_consent.py 完全一致，改了旧记录就失效）
_PRIVACY_HASH_SALT = "ToolsGCP_PrivacyConsent_Salt_v1.0"
CONSENT_VERSION = "V1.0"


class PrivacyState:
    """隐私政策同意状态（线程安全；只读写 json，不碰任何 GUI 库）"""

    def __init__(self, config_dir=None):
        self._lock = threading.RLock()
        if config_dir is None:
            try:
                from pymodels.constants import DATA_DIR
                config_dir = DATA_DIR
            except Exception:
                config_dir = os.path.join(os.getcwd(), ".ToolsGCP", "config")
        self.dir = os.path.join(str(config_dir), "")
        self.path = os.path.join(self.dir, "privacy_policy.json")

    # ---------- 诊断 ----------
    @property
    def data_root(self) -> str:
        """当前数据根（self.dir 的上一级，通常是 `<主目录>/.ToolsGCP`）"""
        return os.path.dirname(os.path.normpath(self.dir))

    def exists(self) -> bool:
        """同意记录文件现在是否在盘上（**只查，不创建**）
        用于诊断/日志：api.privacy_state 在 load() 之前调它，就能区分
        "从来没有同意过" 和 "同意过但文件被删了（比如删了数据根）"。
        """
        try:
            return os.path.isfile(self.path)
        except Exception:
            return False

    def describe(self) -> dict:
        """给日志/自检用的一行信息（不含同意内容，只有位置与存在性）"""
        return {"data_root": self.data_root, "path": self.path, "exists": self.exists()}

    # ---------- 默认内容 ----------
    @staticmethod
    def _default():
        return {
            "_comment_zh-CN": "【重要说明】consent_given 为 false 表示您尚未同意用户协议与隐私政策，将无法使用本软件；consent_given 为 true 表示您已同意，可正常使用全部功能。",
            "_comment_zh-TW": "【重要說明】consent_given 為 false 表示您尚未同意用戶協議與隱私政策，將無法使用本軟體；consent_given 為 true 表示您已同意，可正常使用全部功能。",
            "_comment_en": "【Important Notice】If consent_given is false, you have not agreed to the User Agreement and Privacy Policy and will not be able to use this software. If consent_given is true, you have agreed and may use all features normally.",
            "consent_given": False,
            "consent_version": CONSENT_VERSION,
            "consent_timestamp": "",
            "consent_hash": "",
        }

    # ---------- 读写 ----------
    def _ensure_dir(self):
        try:
            os.makedirs(self.dir, exist_ok=True)
        except Exception:
            pass

    def load(self) -> dict:
        """读状态；文件不存在/损坏都只是"没有同意过"，绝不抛异常"""
        with self._lock:
            self._ensure_dir()
            if not os.path.exists(self.path):
                data = self._default()
                self._save(data)
                return data
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except Exception:
                data = self._default()
                self._save(data)
                return data
            if not isinstance(data, dict):
                data = self._default()
                self._save(data)
                return data
            # 补齐缺失字段
            default = self._default()
            for key, value in default.items():
                if key not in data:
                    data[key] = value
            return data

    def _save(self, data: dict) -> bool:
        self._ensure_dir()
        try:
            temp = self.path + ".tmp"
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            os.replace(temp, self.path)
            return True
        except Exception:
            return False

    # ---------- 校验 ----------
    @staticmethod
    def _hash(consent_given, consent_version, consent_timestamp) -> str:
        raw = f"{_PRIVACY_HASH_SALT}|{consent_given}|{consent_version}|{consent_timestamp}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def is_valid(self, data: dict = None) -> bool:
        """同意状态是否有效（true 且哈希匹配；防止手改 json 绕过）"""
        data = self.load() if data is None else data
        if not data.get("consent_given"):
            return False
        expected = self._hash(data.get("consent_given", False),
                              data.get("consent_version", ""),
                              data.get("consent_timestamp", ""))
        return str(data.get("consent_hash", "")) == expected

    # ---------- 记录 ----------
    def record_consent(self) -> bool:
        """记录用户同意（写 json + 哈希）；返回是否写盘成功"""
        with self._lock:
            data = self.load()
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data["consent_given"] = True
            data["consent_version"] = CONSENT_VERSION
            data["consent_timestamp"] = stamp
            data["consent_hash"] = self._hash(True, CONSENT_VERSION, stamp)
            return self._save(data)

    def reset(self) -> bool:
        """清掉同意记录（给自检/卸载用；界面没有这个按钮）"""
        with self._lock:
            return self._save(self._default())
