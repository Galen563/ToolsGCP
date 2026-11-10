"""桌面外壳层（pywebview + Win32）。
分层约定（重构红线，别破坏）：
    pymodels/core|utils   —— 业务逻辑（原样复用，尽量不碰）
    desktop/native        —— Win32 原生能力：无边框窗口补丁 / 托盘 / 全局热键 / 窗口动效
    desktop/webhost       —— 本地 WSGI 服务（把 webui/ 与 .ToolsGCP 资源喂给前端）
    desktop/api           —— 暴露给 window.pywebview.api 的门面
    webui/                —— HTML5 + Vue3 + Tailwind 前端
⚠️ 这一层**不许 import PyQt5**：Qt 只允许出现在启动画面那条线程里（见 desktop/splash.py）。
"""
