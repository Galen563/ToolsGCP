"""Win32 原生能力（全部走 ctypes，不额外依赖 pywin32）。
⚠️ 为什么不 import pywin32：`requirements.txt` 现在按需求冻结（不许动），而 pywin32 并不在
   里面。装一份本地能跑、打包时缺依赖就炸，属于"埋雷"。这里用 ctypes 直调同一批 Win32 API，
   零新增依赖，行为一致。
"""
