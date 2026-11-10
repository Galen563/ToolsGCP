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
