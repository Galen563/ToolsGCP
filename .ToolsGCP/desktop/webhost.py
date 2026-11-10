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
import re                                       # _inject_boot_theme 改写 <html> 标签用
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


def _send_icon(rel: str):
    """图标专用：云端目录优先、程序自带兜底
    ⚠️ 与 `_safe_join` 分开是因为它的查找要跨**两个根**（cloud icons / images），
       而 `_safe_join` 只能限定在一个根里；这里只取 basename，天然没有穿越风险。
    """
    base = os.path.basename(str(rel or "").replace("\\", "/"))
    if not base:
        return _send_file("")
    path = ""
    try:
        from pymodels.core.cloud_icon_source import icon_file
        path = icon_file(base)
    except Exception:
        # 云端模块不可用（打包裁剪/异常）→ 退回老逻辑，绝不因为图标 500
        path = _safe_join(ICON_DIR, base)
    return _send_file(path)


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


# ==========================================================================
# 首帧主题（本轮修复"浅色主题下启动加载画面仍是深色"的**根治点**）
# ==========================================================================
# 用户报的现象是"程序窗口**中的**启动加载画面"—— 那是 webui 的 `.boot-screen`
# （不是 desktop/splash.py 那个 180px 原生浮窗，那个已经离屏取证证明底色算对了）。
# 真因（三条叠加，前两条由这里治）：
#   A. index.html 的首帧脚本只能问 localStorage 或系统 prefers-color-scheme。
#      而 pywebview 默认 `private_mode=True`（winforms 会把 WebView2 设成
#      IsInPrivateModeEnabled + 每次换一个**临时** profile 目录）→
#      `toolsgcp.theme` 每次启动都是空的，**永远读不到用户存的浅色**；
#      退到 matchMedia 后，本机 Windows 应用模式是深色
#      （HKCU\...\Themes\Personalize\AppsUseLightTheme = 0）→ 首帧必黑。
#      （实测 %APPDATA%\pywebview / %LOCALAPPDATA%\pywebview 都不存在，印证了这点。）
#   B. shell.py 建窗时 background_color 写死 #1C1C1C，页面合成前露的就是那层黑底。
# 解法：`/` 这条路由是**服务端**渲染的，后端本来就知道用户存的是什么主题
#   （settings 文件就在数据根里）→ 直接把真实主题烘进返回的 HTML，
#   首帧脚本优先用它，不再依赖 localStorage / 系统色。
#   ⚠️ 桌面端（webhost）与浏览器模式（Ctrl+Shift+O）共用**同一个 bottle app**
#      （browsermode.create_bridge_app 把这个 app 当 base_app），所以这一处改完
#      两端同时生效，不用改两遍。
def _boot_theme(cfg_path: str = "") -> dict:
    """读用户设置里的主题，给首帧用。绝不抛异常，拿不到就返回深色兜底。

    深浅的判定**复用** splash 那边已经调好的 `_theme_is_light()`
    （兼容 浅色主题 / 浅色 / 淺色主題 / Light Theme / dark / 短形式 等全部写法），
    不在这里再写一份字符串表 —— 两处各判一次早晚又会不一致（上一轮就是这么坏的）。
    """
    out = {"dark": True, "accent": "blue", "source": "fallback"}
    try:
        import json as _json
        from pymodels.constants import DATA_DIR
        # ⚠️ 用 DATA_DIR（= 用户数据根下的 config/，和 splash / SettingsManager
        #    同一个文件），**不是** CONFIG_DIR —— 后者是随程序发布的资源目录
        #    （modules/images/资源库），里面没有用户配置（AGENTS.md 第 9 条）。
        # ⚠️ cfg_path 是给测试用的"依赖注入"口子（免得到处改 module 属性 + reload）；
        #    生产路径一律留空、自己算 DATA_DIR。
        cfg = str(cfg_path or "") or os.path.join(DATA_DIR, "toolsgcp_config.json")
        if not os.path.isfile(cfg):
            return out
        with open(cfg, "r", encoding="utf-8") as handle:
            data = _json.load(handle)
        theme = data.get("theme")
        accent = str(data.get("accent_color") or "blue").strip() or "blue"
        # 延迟 import：splash 模块属于窗口层，正常情况下这里能拿到；拿不到就退回本地判定
        try:
            from .splash import _theme_is_light
            verdict = _theme_is_light(theme)
        except Exception:                             # noqa: BLE001
            verdict = None
        if verdict is None:
            text = str(theme or "").strip().lower()
            if ("浅色" in text or "淺色" in text or "light" in text):
                verdict = True
            elif ("深色" in text or "dark" in text):
                verdict = False
        if verdict is None:
            # "跟随系统"/认不出 → 跟 splash 同一口径问注册表
            follows = ("跟随" in str(theme or "") or "跟隨" in str(theme or "")
                       or "follow" in text or "system" in text or "auto" in text)
            if follows:
                try:
                    from pymodels.utils.system_utils import detect_system_theme
                    verdict = (detect_system_theme() != "深色主题")
                    out["source"] = "system"
                except Exception:                     # noqa: BLE001
                    verdict = None
        if verdict is not None:
            out["dark"] = not verdict
            out["accent"] = accent
            out["source"] = out["source"] if out["source"] != "fallback" else "settings"
        elif accent:
            out["accent"] = accent
    except Exception:                                 # noqa: BLE001
        return {"dark": True, "accent": "blue", "source": "fallback"}
    return out


def _inject_boot_theme(html: str, cfg_path: str = "") -> bytes:
    """把真实主题烘进 index.html，返回改过的字节。

    ⚠️⚠️ 本轮修复「程序启动时窗口出现的一瞬间是深色主题」（用户要求彻底解决）。
    以前只往 <head> 里插一个 <meta>，靠 head 里那段脚本再 `setAttribute('data-theme')`。
    这条路**治不好**，原因是时序而不是判断错：
        ① HTML 自上而下解析 —— `<html lang="zh-CN" data-theme="dark">` 这个**硬编码的
           深色属性在脚本运行之前就已经生效**；
        ② WebView2 拿到第一个字节就可以开始首帧合成，客户区按 `--page` 的深色值刷；
        ③ 脚本随后才把 data-theme 改成 light → 用户看到"一小块深色（= 客户区，比窗口
           小一圈，所以像 350×250 套在 400×300 里）闪一下再变浅色"。
    所以正确的做法是**让第一个解析到的字节就是对的**：直接在服务端改写 `<html>` 标签上的
    `data-theme` / `data-accent`，不再依赖任何 JS 执行时机。
    head 里那段脚本与 <meta> 都**保留**：
        · meta：给脚本当数据源（浏览器模式直接开文件、注入失败时仍可用）；
        · 脚本：兜底路径，正常注入时它算出来的值和标签一致，setAttribute 是幂等的。
    """
    boot = _boot_theme(cfg_path)
    theme = "dark" if boot["dark"] else "light"
    accent = str(boot["accent"] or "blue").replace('"', "")
    tag = ('<meta id="tg-boot-theme" data-dark="%s" data-accent="%s" data-source="%s">'
           % ("1" if boot["dark"] else "0", accent, boot["source"]))

    # ① 改写 <html ...> 上的 data-theme / data-accent（首帧即正确）
    def _fix_html_tag(m):
        head = m.group(0)
        for attr, value in (("data-theme", theme), ("data-accent", accent)):
            if re.search(attr + r'\s*=\s*"[^"]*"', head):
                head = re.sub(r'(' + attr + r'\s*=\s*")[^"]*(")', r'\g<1>' + value + r'\g<2>',
                              head, count=1)
            else:
                head = head[:head.rindex(">")] + ' %s="%s">' % (attr, value)
        return head

    html = re.sub(r"<html\b[^>]*>", _fix_html_tag, html, count=1)

    # ② ★ 本轮重点：把 `<meta name="color-scheme">` 也改成**只有当前这一种**。
    #    ⚠️⚠️ 这是「启动时黑屏闪一下」的真根因，而且**和主题无关**（用户原话：
    #       「不局限于浅色主题所以我推测与主题无关」）—— 完全正确，原因在
    #       Chromium 的 **canvas（画布）底色**：
    #         · 原文是 `content="dark light"`，意思是"本页面深浅都支持"；
    #         · 于是浏览器按**系统的** prefers-color-scheme 选一种来画 canvas，
    #           本机 Windows 应用模式是深色（AppsUseLightTheme=0）→ canvas = 近黑；
    #         · 这层 canvas 在 `<html>` 的 CSS/内联底色**生效之前**就已经画上去了，
    #           而且它由浏览器进程决定，不受我们那段首帧脚本控制；
    #         · 近黑 canvas vs 深色页面的 #1C1C1C / 浅色页面的 #F3F4F7
    #           **两种主题下都明显更黑** → 所以"浅色会闪、深色也会闪"。
    #       为什么"开着录屏反而不出现"：录屏占用高 → 前端 `app.ready` 上报得晚 →
    #       窗口显示时页面早就合成完了，那一帧根本没被看见；空闲时窗口出得早，
    #       正好赶上 canvas 还在裸奔。**这恰恰证明它发生在"第一帧之前"**，
    #       和 ①（改写 data-theme）治的"脚本执行时机"不是同一层问题。
    #       → 声明成单一方案（light 就只写 light），Chromium 便不再跟着系统走，
    #         canvas 直接是我们想要的那个颜色，闪黑从源头消失。
    def _fix_color_scheme(*_ignored):
        return ('<meta name="color-scheme" content="%s">'
                % ("dark" if theme == "dark" else "light"))

    if re.search(r'<meta\s+name="color-scheme"[^>]*>', html):
        html = re.sub(r'<meta\s+name="color-scheme"[^>]*>', _fix_color_scheme, html, count=1)
    else:
        # 万一将来有人把这条 meta 删了：主动补在 <head> 最前，别退回"跟着系统走"
        at = html.find("<head>")
        inject = _fix_color_scheme(None) + "\n"
        html = (html[:at + len("<head>")] + "\n" + inject + html[at + len("<head>"):]
                if at >= 0 else inject + html)

    # 插在 <head> 之后（早于那段首帧脚本执行），找不到就前置
    anchor = "<head>"
    at = html.find(anchor)
    if at >= 0:
        i = at + len(anchor)
        html = html[:i] + "\n" + tag + html[i:]
    else:
        html = tag + html
    return html.encode("utf-8")


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
        # ⚠️ 首页**不走** _send_file：那会把文件原样吐出去，就没有机会把
        #    服务端已知的真实主题烘进首帧 HTML（用户"浅色主题启动仍深色"的根治点，
        #    见 _boot_theme 的注释）。这里自己读、自己注入、自己发同样的头。
        try:
            with open(full, "r", encoding="utf-8") as handle:
                html = handle.read()
        except Exception:                             # noqa: BLE001
            return _send_file(full)                   # 读不动就退回原样发送，别把界面搞黑屏
        bottle.response.content_type = "text/html; charset=utf-8"
        _no_store()
        return _inject_boot_theme(html)

    # ---------- 前端静态文件 ----------
    @app.get("/static/<rel:path>")
    def static_file(rel):
        return _send_file(_safe_join(WEBUI_DIR, rel))

    # ---------- 资源（图标 / 图片 / logo） ----------
    # ⚠️ 图标目录重构（web 版）：`.ToolsGCP/Icon/` → `.ToolsGCP/images/icon/`。
    #    规范 URL 现在是 `/res/image/icon/<name>`（走下面的 res_image 就够了）。
    #    这里保留 `/res/icon/<name>` 作为**兼容别名**，指向同一个新目录 ——
    #    这样旧版本前端缓存/旧资源库 JSON 里的写法也不会 404。
    # ⚠️⚠️ 云端图标：作者把 icon.zip 传到 GitHub Release 后，图标优先从
    #    `<数据根>/config/cloud/icons` 取，取不到再退回程序自带的 images/icon
    #    （见 cloud_icon_source.icon_file）。同步在后台线程跑，路由本身**永不联网**。
    @app.get("/res/icon/<rel:path>")
    def res_icon(rel):
        return _send_icon(rel)

    @app.get("/res/image/icon/<rel:path>")
    def res_image_icon(rel):
        return _send_icon(rel)

    @app.get("/res/image/<rel:path>")
    def res_image(rel):
        # 图标子路径单独走"云端优先"（/res/image/icon/xx.png 是规范 URL）
        head = str(rel or "").replace("\\", "/")
        if head.startswith("icon/"):
            return _send_icon(head[len("icon/"):])
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
