"""密钥安全存储
Windows 上用 DPAPI（CryptProtectData）加密：密文只能被"同一台电脑 + 同一个 Windows 用户"
解出来，程序不需要自己管理主密钥。非 Windows 平台降级为 base64 混淆（标记 plain:，不假装安全）。
存储格式："dpapi:<base64密文>" / "plain:<base64明文>" / ""（空）。用法：protect / unprotect。
"""

import base64
import ctypes
import sys

PREFIX_DPAPI = "dpapi:"
PREFIX_PLAIN = "plain:"
_ENTROPY = b"ToolsGCP.SecretStore.v1"

# 用户在网页/文档里复制 Key 时常带进来的不可见字符（零宽、BOM、不换行空格等）
_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00a0"), None)
# 包裹 Key 的常见引号/反引号（成对剥一层）
_QUOTE_PAIRS = (('"', '"'), ("'", "'"), ("`", "`"), ("“", "”"), ("「", "」"))


def sanitize_api_key(value) -> str:
    """把用户粘贴的 API Key 规整成真正要发给服务商的样子。

    ⚠️ 为什么要做这层清洗：多数「API Key 无效」是粘贴/输入带入的隐藏字符或前缀
    （零宽字符、BOM、`Bearer `、整段带引号的 JSON/文档示例），服务商拿到的是
    一个“看起来一样但完全不是同一个”的字符串。规则：
      1) 去掉不可见字符（零宽空格/BOM/NBSP 等）与首尾空白；
      2) 剥一层成对包裹的引号/反引号/中文引号（只剥最外一层）；
      3) 去掉开头多余的 `Bearer ` / `bearer ` 前缀；
      4) Key 内部不应有空白（整行粘贴会带入换行），统一去掉。
    返回空串表示“没填有效内容”。
    """
    text = str(value or "").translate(_INVISIBLE).strip()
    for left, right in _QUOTE_PAIRS:
        if len(text) >= 2 and text.startswith(left) and text.endswith(right):
            text = text[len(left):len(text) - len(right)].strip()
            break
    lowered = text.lower()
    if lowered.startswith("bearer "):
        text = text[7:].strip()
    return "".join(text.split())


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _to_blob(data: bytes) -> _DataBlob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _from_blob(blob: _DataBlob) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _free_blob(blob: _DataBlob):
    if blob.pbData:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def available() -> bool:
    """当前环境是否能用系统级加密"""
    return sys.platform == "win32"


def is_encrypted(value: str) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX_DPAPI)


def protect(text: str) -> str:
    """加密字符串；空串原样返回"""
    if not text:
        return ""
    raw = text.encode("utf-8")
    if not available():
        return PREFIX_PLAIN + base64.b64encode(raw).decode("ascii")
    try:
        in_blob = _to_blob(raw)
        entropy = _to_blob(_ENTROPY)
        out_blob = _DataBlob()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(in_blob), "ToolsGCP", ctypes.byref(entropy),
            None, None, 0, ctypes.byref(out_blob))
        if not ok:
            raise OSError("CryptProtectData 失败")
        try:
            return PREFIX_DPAPI + base64.b64encode(_from_blob(out_blob)).decode("ascii")
        finally:
            _free_blob(out_blob)
    except Exception:
        # 加密不可用时宁可用明文标记，也不要静默丢数据
        return PREFIX_PLAIN + base64.b64encode(raw).decode("ascii")


def unprotect(stored: str) -> str:
    """解密字符串；不是本模块产出的格式就当成明文返回"""
    if not stored:
        return ""
    if stored.startswith(PREFIX_PLAIN):
        try:
            return base64.b64decode(stored[len(PREFIX_PLAIN):]).decode("utf-8")
        except Exception:
            return ""
    if not stored.startswith(PREFIX_DPAPI):
        return stored   # 旧版本存的明文，直接返回
    if not available():
        return ""
    try:
        data = base64.b64decode(stored[len(PREFIX_DPAPI):])
        in_blob = _to_blob(data)
        entropy = _to_blob(_ENTROPY)
        out_blob = _DataBlob()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, ctypes.byref(entropy),
            None, None, 0, ctypes.byref(out_blob))
        if not ok:
            return ""
        try:
            return _from_blob(out_blob).decode("utf-8", "ignore")
        finally:
            _free_blob(out_blob)
    except Exception:
        return ""
