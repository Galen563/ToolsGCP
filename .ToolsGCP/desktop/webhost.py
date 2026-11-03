"""本地 WSGI 服务：把 `webui/` 与 `.ToolsGCP` 里的资源喂给 WebView2。
========== 为什么不用 `file://` ==========
1. `fetch()` 在 `file://` 下被浏览器直接拒绝（跨域），前端连自己的 JSON 都读不到；
2. `<script type="module">` 在 `file://` 下同样受限；
3. 图标/海报是中文文件名（`微信Galen563的ToolsGCP项目赞助.jpg`），`file://` 的编码规则
   在 Edge 上不稳定。
pywebview 支持直接把 WSGI 应用当 `url` 传（`create_window(url=app)`），它自带随机端口 +
`/js_api/<uid>` 路由，这条通道同时负责 `window.pywebview.api` —— 用同一台服务器最省事。
========== 路由 ==========
    /                    → webui/index.html
    /static/<path>       → webui/<path>              （js/css/vendor）
    /res/icon/<name>     → .ToolsGCP/images/icon/<name>   （兼容别名，规范 URL 见下）
    /res/image/<path>    → .ToolsGCP/images/<path>        （图标规范 URL = /res/image/icon/<name>）
    /res/image/<path>    → .ToolsGCP/images/<path>
    /res/<name>          → .ToolsGCP/<name>          （logo.png 等）
    /api/health          → {"ok": true, ...}         （自检脚本用）
⚠️ 所有返回都带 `Cache-Control: no-store`：开发期改前端文件必须立刻生效，
   否则 WebView2 会缓存旧 JS，改完看不到效果（这是最容易踩的坑）。
⚠️ 路径必须做越界校验：`/static/../../secret` 之类不能读到 webui 外面去。
"""

import json
import mimetypes
import os
import posixpath
import threading

import bottle

from pymodels.constants import CONFIG_DIR, APP_NAME, APP_VERSION

# 目录（前端所在位置）
# ⚠️⚠️ 不能按 `__file__` 的上级目录推导：源码运行时 webhost.py 在 `.ToolsGCP/desktop/`，
#    上级是 `.ToolsGCP/`，拼 `webui` 正好对；但 **PyInstaller 打包后布局变了**：
#      · onedir：`.ToolsGCP/desktop/webhost.py` → `_internal/desktop/webhost.py`，
#        而前端被 `--add-data ".ToolsGCP;.ToolsGCP"` 放到 `_internal/.ToolsGCP/webui/`。
#        按上级推导会得到 `_internal/webui` → **不存在** → 前端全部 404。
#      · onefile：资源在 `sys._MEIPASS/.ToolsGCP/webui/`。
#    所以统一走 `pymodels.constants.resource_path()`：它已经处理了这两种 frozen 布局
#    （先找程序目录旁的 .ToolsGCP，再找 sys._MEIPASS/.ToolsGCP），源码运行同样适用。
#    这个 bug 之前一直没暴露，是因为一直用 onefile + `_MEIPASS` 兜底；
#    换 onedir 后路径算错，前端直接打不开。
from pymodels.constants import resource_path

WEBUI_DIR = os.path.dirname(resource_path("webui", "index.html"))
# 资源目录：图标统一放在 .ToolsGCP/images/icon 下（原 .ToolsGCP/Icon，web 版已重构）
IMAGES_DIR = os.path.join(CONFIG_DIR, "images")
ICON_DIR = os.path.join(IMAGES_DIR, "icon")

# 常见类型补齐（Windows 注册表里 .webp/.mjs 有时没有）
_EXTRA_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".ico": "image/x-icon",
    ".gif": "image/gif",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".bmp": "image/bmp",
    ".map": "application/json",
    ".wasm": "application/wasm",
}

_no_store_lock = threading.Lock()


def _no_store():
    """开发期一律禁缓存：改完前端文件刷新即生效"""
    bottle.response.set_header("Cache-Control", "no-cache, no-store, must-revalidate")
    bottle.response.set_header("Pragma", "no-cache")
    bottle.response.set_header("Expires", "0")


def _safe_join(root: str, rel: str) -> str:
    """把相对路径拼到 root 下，并保证结果仍在 root 内（防目录穿越）"""
    rel = str(rel or "").replace("\\", "/").lstrip("/")
    rel = posixpath.normpath(rel)
    if rel in ("", "."):
        return root
    if rel.startswith("../") or rel == ".." or os.path.isabs(rel):
        return ""
    full = os.path.abspath(os.path.join(root, rel.replace("/", os.sep)))
    root_abs = os.path.abspath(root)
    if full != root_abs and not full.startswith(root_abs + os.sep):
        return ""
    return full


def _send_file(full_path: str, *, download: bool = False):
    if not full_path or not os.path.isfile(full_path):
        bottle.response.status = 404
        return "not found"
    ext = os.path.splitext(full_path)[1].lower()
    bottle.response.content_type = _EXTRA_TYPES.get(ext) or (
        mimetypes.guess_type(full_path)[0] or "application/octet-stream")
    _no_store()
    try:
        with open(full_path, "rb") as handle:
            return handle.read()
    except Exception:
        bottle.response.status = 500
        return "read error"


def create_app():
    """构造 WSGI 应用（pywebview 直接把它当 url 传）"""
    app = bottle.Bottle()

    # ---------- 首页 ----------
    @app.get("/")
    def index():
        full = os.path.join(WEBUI_DIR, "index.html")
        if not os.path.isfile(full):
            bottle.response.content_type = "text/html; charset=utf-8"
            _no_store()
            return (
                "<!doctype html><meta charset='utf-8'>"
                "<body style='font:14px Consolas;background:#16181d;color:#e6e6e6;padding:32px'>"
                f"<h2>{APP_NAME} {APP_VERSION}</h2>"
                "<p>前端入口还没生成：<code>webui/index.html</code> 不存在。</p>"
                "<p>这是第一步（外壳）阶段的正常状态，第三步会把页面补上。</p>"
                "</body>")
        return _send_file(full)

    # ---------- 前端静态文件 ----------
    @app.get("/static/<rel:path>")
    def static_file(rel):
        return _send_file(_safe_join(WEBUI_DIR, rel))

    # ---------- 资源（图标 / 图片 / logo） ----------
    # ⚠️ 图标目录重构（web 版）：`.ToolsGCP/Icon/` → `.ToolsGCP/images/icon/`。
    #    规范 URL 现在是 `/res/image/icon/<name>`（走下面的 res_image 就够了）。
    #    这里保留 `/res/icon/<name>` 作为**兼容别名**，指向同一个新目录 ——
    #    这样旧版本前端缓存/旧资源库 JSON 里的写法也不会 404。
    @app.get("/res/icon/<rel:path>")
    def res_icon(rel):
        return _send_file(_safe_join(ICON_DIR, rel))

    @app.get("/res/image/<rel:path>")
    def res_image(rel):
        return _send_file(_safe_join(IMAGES_DIR, rel))

    # ⚠️ 插件页要靠这条路由读 manifest.json / icon / 配置页 HTML。
    #    之前**漏了这条路由** → 前端 fetch('/res/plugins/xx/manifest.json') 全部 404
    #    → 插件列表永远是空的（"插件界面不显示插件示例"就是这个）。
    # ⚠️⚠️ 插件现在有**两个根目录**（内置 `<程序目录>\.ToolsGCP\plugins` + 用户可写
    #    `<数据根>\plugins`，见 desktop/api/plugins.py 的 plugins_dirs()），
    #    所以这里必须按同样的优先级顺序去找，**不能只服务内置那一份** ——
    #    否则 exe 版里用户放进数据根的插件"列表里看得到、点进去 config.html 404"。
    #    顺序与后端一致：用户目录在前（同名插件覆盖内置），内置目录在后。
    @app.get("/res/plugins/<rel:path>")
    def res_plugins(rel):
        from pymodels.constants import CONFIG_DIR as _CFG
        # rel 的第一段是插件目录名：按它在两个根里定位"这个插件到底在哪"
        head = str(rel or "").split("/", 1)[0]
        tail = str(rel or "")[len(head):].lstrip("/")
        bases = []
        try:
            from .api.plugins import plugins_dirs
            bases = [os.path.join(r, head) for r in plugins_dirs()]
        except Exception:
            bases = []
        if not bases:
            bases = [os.path.join(os.path.join(_CFG, "plugins"), head)]
        for base in bases:
            full = _safe_join(base, tail)
            if full and os.path.isfile(full):
                return _send_file(full)
        # 一个都没命中：回落到第一个候选，让 _send_file 正常报 404
        # （保持"路径不合法 → 空串 → 404"的原有语义，不额外抛错）
        return _send_file(_safe_join(bases[0], tail))

    @app.get("/res/<rel:path>")
    def res_root(rel):
        return _send_file(_safe_join(CONFIG_DIR, rel))

    # ---------- 自检 ----------
    @app.get("/api/health")
    def health():
        bottle.response.content_type = "application/json; charset=utf-8"
        _no_store()
        return json.dumps({
            "ok": True,
            "app": APP_NAME,
            "version": APP_VERSION,
            "webui": os.path.isdir(WEBUI_DIR),
            "has_index": os.path.isfile(os.path.join(WEBUI_DIR, "index.html")),
            "config_dir": CONFIG_DIR,
        }, ensure_ascii=False)

    return app
