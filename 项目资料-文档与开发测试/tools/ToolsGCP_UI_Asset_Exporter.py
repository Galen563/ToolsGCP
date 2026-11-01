#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 ToolsGCP UI 素材导出器（宣传片用）· 单文件 · 零第三方依赖 · 不修改原程序
================================================================================
做什么
把 ToolsGCP（web 版）界面里的**单个 UI 组件**（卡片 / 按钮 / 气泡 / 设置行 / 分段
控制器 / 弹层 / 侧栏 …）从**真实 DOM** 直接导出成高质量 PNG（**1x 原生无损**），
而不是"整页截图再裁切"。输出带清单（组件名 / 尺寸 / 原始坐标 / 主题 / 文件），
方便在剪映里按层摆放做动效。
另外每个页面 × 每个切换分页都会额外导出一张**整程序整图**（screens/ 目录），
用来快速对位置、做转场底板。
怎么做（为什么可行）
原程序前端是 `pywebview + Vue3 runtime CDN + 纯 CSS`，没有构建步骤、没有 canvas
绘制界面 —— 所以"从程序内部提取"最忠实的办法就是：
  ① 起一个 **headless Edge**（绝不弹可见窗口、不抢焦点），
  ② 用 DevTools 协议（CDP，纯标准库 WebSocket）连上去，
  ③ 本工具自带一个只读静态服务器，把 `.ToolsGCP/webui` 喂给浏览器，并注入
     mock 的 `window.pywebview.api`（真实后端是 Python，这里用 JS 假数据代替，
     这样工具能独立运行、不 import 原程序、也不碰用户数据），
  ④ 逐页导航 → 给要导出的元素打临时标记 → 滚动到可见 → 量 rect / 阴影 / 是否
     被祖先裁切 → `Page.captureScreenshot(clip, scale)` 精确截取那一个元素。
透明背景、圆角、文字、图标、边框、阴影、抗锯齿都由 Chromium 真实渲染给出。
输出结构
    <输出目录>/
      manifest.json              ← 全局清单（所有组件 + 主题 + 尺寸 + 坐标 + 说明）
      assets.csv                 ← 同一份清单的表格版（Excel / 剪映对照用）
      README-使用说明.md          ← 怎么用 + 哪些东西提取不了、为什么、怎么替代
      dark/<page>/<组件>__<w>x<h>.png
      dark/<page>/page.json
      screens/<theme>/<page>/<state>__full.png   ← 每个分页一张整程序整图
      light/...                   ← 主题=both 时第二套
用法
    python ToolsGCP_UI_Asset_Exporter.py                 # 交互式：问输出目录/主题/效果/强调色/页面
    python ToolsGCP_UI_Asset_Exporter.py --yes           # 全部默认值（输出到 ./ToolsGCP-UI-Assets）
    python ToolsGCP_UI_Asset_Exporter.py --yes --themes both --out D:/素材
    python ToolsGCP_UI_Asset_Exporter.py --list          # 只列出会导出的页面/组件（不启动浏览器）
    python ToolsGCP_UI_Asset_Exporter.py --yes --pages search,maker-form
限制（工具会如实写进 manifest 的 skipped / note，不伪造）
  · 整页背景（渐变/海报模糊）不是"组件"，提取出来会带上背景色 → 记 skipped 并给替代方案；
  · `backdrop-filter`（云母/玻璃/亚克力）组件单独抠图会失去材质 → 同时给
    `__opaque` 版本（含页面背景）+ 在 manifest 标 `transparent: false`；
  · 远程图片 / 视频 / 轮播过渡帧、iframe 插件页、系统原生窗口边框与托盘菜单、
    原生右键菜单（那部分是 Python 画的）都无法作为 DOM 组件导出 → skipped 说明；
  · 动画进行中的中间态不导出（等页面静止后统一量），需要中间帧请改用录屏。
依赖：Windows + Edge（系统自带）+ Python 3.8+。不需要 playwright / selenium / PIL。
================================================================================
"""

from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOL_NAME = "ToolsGCP UI 素材导出器"
TOOL_VERSION = "1.0.0"
SCHEMA_VERSION = 1

DEFAULT_VIEWPORT = (1440, 900)
DEFAULT_SCALE = 2
EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

# 语言模块文件名（和 desktop/api/__init__.py 的 FILES 保持一致）
I18N_FILES = {
    "search": "search_language.json", "home": "home_language.json",
    "notice": "notice_language.json", "tools_gcp": "ToolsGCPcenter_language.json",
    "deploy": "deploy_language.json", "github": "github_language.json",
    "settings": "set_language.json", "log": "log_language.json",
    "feedback": "feedback_language.json", "nav": "nav_language.json",
    "privacy": "privacy_language.json", "plugin": "plugin_language.json",
    "maker": "maker_language.json", "customize": "customize_language.json",
    "common": "common_language.json",
}

# 前端 `default_page`（中文标题）→ 前端内部页面键（app.js 的 map）
PAGE_TITLE = {
    "home": "首页", "search": "搜索", "customize": "定制页", "favorites": "收藏",
    "deploy": "部署", "settings": "设置", "github": "Github", "log": "查看日志",
    "notice": "公告", "feedback": "反馈", "workshop": "GCP工坊", "plugins": "插件",
    "maker": "提交软件",
}

THEME_LABEL = {"dark": "深色主题", "light": "浅色主题"}


# =============================================================================
# 一、小工具：路径 / 终端输出 / PNG
# =============================================================================

def eprint(*args):
    """进度一律走 stderr，stdout 只留最终摘要（方便脚本管道）。"""
    print(*args, file=sys.stderr, flush=True)


def find_project_root(start: str) -> str:
    """从脚本位置往上找含 .ToolsGCP/webui/index.html 的目录。
    ⚠️ 不用 __file__ 硬编码层级：tools/ 可能被整体拷到别处，用户也可能把本脚本
       放到项目外再 `--project` 指过来。找不到就明确报错，不猜。
    """
    here = os.path.abspath(start)
    for _ in range(8):
        if os.path.isfile(os.path.join(here, ".ToolsGCP", "webui", "index.html")):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return ""


def find_edge() -> str:
    for path in EDGE_CANDIDATES:
        if os.path.isfile(path):
            return path
    # 最后摸一下 PATH（有些机器是裸 msedge.exe）
    found = shutil.which("msedge.exe") or shutil.which("msedge")
    return found or ""


def free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def sanitize_name(text: str, fallback: str = "asset") -> str:
    """文件名安全化：保留中文/字母/数字/-/_，其余变 -。"""
    value = re.sub(r"[^\w\u4e00-\u9fff\-]+", "-", str(text or "")).strip("-")
    return value or fallback


def now_iso() -> str:
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def human_size(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return "%.1f%s" % (num, unit) if unit != "B" else "%d%s" % (num, unit)
        num /= 1024.0
    return "%d B" % num


def png_size_and_alpha(data: bytes, sample_alpha: bool = False) -> dict:
    """读 PNG：尺寸（只解析 IHDR，极快）；可选解出像素采样 alpha。
    ⚠️ 为什么自己解 PNG 而不是用 PIL：本工具**禁止新增依赖**。Chrome 导出的是
       8bit RGBA/RGB、非隔行，手写解码器 60 行就够；只有需要验证"圆角外是否真的
       透明"时才解像素（解像素是纯 Python，慢，所以默认只抽查少量图）。
    """
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("不是 PNG")
    pos, width, height, bit_depth, color_type = 8, 0, 0, 8, 6
    idat = bytearray()
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", chunk[:10])
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
    info = {"w": width, "h": height, "bit_depth": bit_depth,
            "color_type": color_type,
            "has_alpha": color_type in (4, 6), "alpha_ratio": None, "corners": None}
    if not sample_alpha or not idat:
        return info
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if color_type not in (4, 6):
        # 没有 alpha 通道：明确当作"完全不透明"，别拿蓝通道冒充 alpha（曾经踩过）
        info["alpha_ratio"] = 1.0
        info["corners"] = [255, 255, 255, 255]
        return info
    if bit_depth != 8 or channels is None:
        return info
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    prev = bytearray(stride)
    p = 0
    transparent_px = 0
    total_px = 0
    corners = []
    corner_idx = {(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)}
    alpha_idx = channels - 1
    for y in range(height):
        if p >= len(raw):
            break
        ftype = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if ftype == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        total_px += width
        if y % 3 == 0:                                  # 每 3 行采一次，够判断"有没有透明"
            for x in range(0, width, 3):
                if line[x * channels + alpha_idx] < 8:
                    transparent_px += 1
        for (cx, cy) in list(corner_idx):
            if cy == y:
                corners.append(line[cx * channels + alpha_idx])
                corner_idx.discard((cx, cy))
        prev = line
    info["corners"] = corners
    sampled = max(1, (height // 3 + 1) * (len(range(0, width, 3))))
    info["alpha_ratio"] = round(transparent_px / float(max(1, sampled)), 4)
    return info


# =============================================================================
# 二、mock 后端（JS）：原程序的后端是 Python，这里用等价假数据，让页面能独立渲染
# =============================================================================

MOCK_TEMPLATE = r"""
/* ---------- ToolsGCP UI 素材导出器注入的 mock 后端（只读、无副作用） ---------- */
window.__MOCK_RESOURCES__ = __RESOURCES__;
window.__MOCK_SETTINGS__ = __SETTINGS__;
window.__MOCK_NOTICES__ = __NOTICES__;
window.__MOCK_PLUGINS__ = __PLUGINS__;
window.__MOCK_I18N__ = __I18N__;
(function () {
  var R = window.__MOCK_RESOURCES__ || [];
  var S = window.__MOCK_SETTINGS__ || {};
  var latest = R.slice(0, 10).map(function (r) { return r.code; });
  function ok(o) { var d = Object.assign({ ok: true }, o || {}); return d; }
  function find(code) {
    for (var i = 0; i < R.length; i += 1) { if (R[i].code === code) return R[i]; }
    return null;
  }
  window.pywebview = { api: {
    resources: {
      all: async function () { return ok({ items: R }); },
      status: async function () { return ok({ source: 'mock', count: R.length }); },
      refresh_latest: async function () { return ok({ codes: latest }); },
      detail: async function (code) { var hit = find(code); return { ok: !!hit, item: hit }; },
      filter_options: async function () {
        var cats = {}, tags = {}, systems = {}, archs = {};
        R.forEach(function (r) {
          (r.category || []).forEach(function (c) { cats[c] = (cats[c] || 0) + 1; });
          (r.tags || []).forEach(function (t) { tags[t] = (tags[t] || 0) + 1; });
          (r.systems || []).forEach(function (s) { systems[s] = (systems[s] || 0) + 1; });
          (r.architectures || []).forEach(function (a) { archs[a] = (archs[a] || 0) + 1; });
        });
        function toList(m) {
          return Object.keys(m).map(function (k) { return { value: k, count: m[k] }; })
            .sort(function (a, b) { return b.count - a.count; });
        }
        return ok({ categories: toList(cats), tags: toList(tags),
                    systems: toList(systems), architectures: toList(archs) });
      },
    },
    settings: {
      get: async function () { return ok({ settings: S }); },
      set: async function () { return ok({}); },
      api_key_state: async function () { return ok({ configured: false }); },
      reveal_api_key: async function () { return ok({ value: '' }); },
      paths: async function () { return ok({ config: 'C:/mock/.ToolsGCP', data: 'C:/mock' }); },
    },
    favorites: {
      list: async function () { return ok({ folders: [] }); },
      toggle: async function () { return ok({ favorite: true }); },
      add: async function () { return ok({}); },
      remove: async function () { return ok({}); },
    },
    app: {
      info: async function () { return ok({ app: 'ToolsGCP', version: '1.1.4',
        configDir: 'C:/mock/.ToolsGCP', args: [] }); },
      privacy_state: async function () { return ok({ agreed: true }); },
      splash_remaining: async function () { return ok({ remaining: 0 }); },
      ready: async function () { return ok({}); },
    },
    window: {
      state: async function () { return ok({ maximized: false, fullscreen: false }); },
      center: async function () { return ok({}); },
      minimize: async function () { return ok({}); },
    },
    plugins: { list: async function () { return ok({ plugins: window.__MOCK_PLUGINS__ || [] }); } },
    announcements: { list: async function () { return ok({ notices: window.__MOCK_NOTICES__ || [],
      unread: 0 }); } },
    log: { client: async function () { return ok({}); } },
    i18n: { bundle: async function () { return ok(window.__MOCK_I18N__ || { modules: {} }); } },
    shell: { open_path: async function () { return ok({}); } },
    deploy: { list: async function () { return ok({ items: [] }); } },
    ai: {
      session: async function () { return ok({ session: null }); },
      history: async function () { return ok({ items: [] }); },
      send: async function () { return ok({}); },
    },
  } };
  /* 首帧就定好主题/效果/强调色，避免导出时闪一下默认值 */
  try {
    var root = document.documentElement;
    if (S.theme === '浅色主题') { root.setAttribute('data-theme', 'light'); }
    else { root.setAttribute('data-theme', 'dark'); }
    root.setAttribute('data-fx', S.theme_effect || 'mica');
    root.setAttribute('data-accent', S.accent_color || 'blue');
  } catch (e) {}
})();
"""


class AssetServer:
    """只读静态服务器：把 .ToolsGCP/webui + .ToolsGCP 资源喂给 headless Edge。
    ⚠️ 完全只读：不写任何文件，不改原程序；`index.html` 只在**内存里**注入 mock。
    """

    MIME = {
        ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
        ".ico": "image/x-icon", ".woff2": "font/woff2", ".woff": "font/woff",
        ".ttf": "font/ttf", ".map": "application/json",
    }

    def __init__(self, root: str, mock_payload: dict):
        self.root = root
        self.webui = os.path.join(root, ".ToolsGCP", "webui")
        self.data = os.path.join(root, ".ToolsGCP")
        self.mock = mock_payload
        self.httpd = None
        self.thread = None
        self.port = 0
        with open(os.path.join(self.webui, "index.html"), "r", encoding="utf-8") as fh:
            self.index_html = fh.read()

    # ---------- 注入 ----------
    def _mock_js(self, query: dict) -> str:
        def one(name, default=""):
            value = query.get(name)
            return value[0] if value else default

        settings = dict(self.mock["settings"])
        theme = one("theme", "dark")
        settings["theme"] = THEME_LABEL.get(theme, "深色主题")
        settings["theme_effect"] = one("fx", settings.get("theme_effect", "mica"))
        settings["accent_color"] = one("accent", settings.get("accent_color", "blue"))
        settings["language"] = one("lang", "简体中文")
        settings["default_page"] = one("dp", PAGE_TITLE["search"])
        if one("ai", "") == "1":
            settings["ai_enabled"] = True
        if one("aiside", "") == "1":
            settings["ai_enabled"] = True
            settings["ai_sidebar_mode"] = True
        elif one("aiside", "") == "0":
            settings["ai_sidebar_mode"] = False
        settings = dict(settings)
        js = (MOCK_TEMPLATE
              .replace("__RESOURCES__", json.dumps(self.mock["resources"], ensure_ascii=False))
              .replace("__SETTINGS__", json.dumps(settings, ensure_ascii=False))
              .replace("__NOTICES__", json.dumps(self.mock["notices"], ensure_ascii=False))
              .replace("__PLUGINS__", json.dumps(self.mock["plugins"], ensure_ascii=False))
              .replace("__I18N__", json.dumps({"ok": True, "language": "简体中文",
                                               "locale": "zh_CN",
                                               "modules": self.mock["i18n"]},
                                              ensure_ascii=False)))
        # 主题要在 Vue 挂载前就定好，避免首帧用默认主题渲染（否则截图里会闪）
        js += ("\ntry{document.documentElement.setAttribute('data-theme',%r);"
               "document.documentElement.setAttribute('data-fx',%r);"
               "document.documentElement.setAttribute('data-accent',%r);}catch(e){}\n"
               % (("light" if theme == "light" else "dark"),
                  settings.get("theme_effect", "mica"),
                  settings.get("accent_color", "blue")))
        return js

    # ---------- 路由 ----------
    @staticmethod
    def _safe_join(base: str, rel: str) -> str:
        rel = str(rel or "").replace("\\", "/").lstrip("/")
        rel = os.path.normpath(rel).replace("\\", "/")
        if rel in ("", "."):
            return base
        if rel.startswith("../") or rel == ".." or os.path.isabs(rel):
            return ""
        full = os.path.abspath(os.path.join(base, rel.replace("/", os.sep)))
        if full != os.path.abspath(base) and not full.startswith(os.path.abspath(base) + os.sep):
            return ""
        return full

    def _send(self, handler, full: str):
        if not full or not os.path.isfile(full):
            handler.send_error(404, "not found")
            return
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as fh:
            body = fh.read()
        handler.send_response(200)
        handler.send_header("Content-Type", self.MIME.get(ext, "application/octet-stream"))
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)

    def _handle(self, handler, server_self):
        parsed = urllib.parse.urlparse(handler.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if path == "/":
            html = server_self.index_html
            mock_js = server_self._mock_js(query)
            # 注入点：icons.js 之前（和 _devtest/serve.py 同一处，保证 app.js 之前执行）
            needle = '<script src="/static/js/icons.js"></script>'
            if needle in html:
                html = html.replace(needle, "<script>%s</script>\n%s" % (mock_js, needle))
            else:
                html = html.replace("</head>", "<script>%s</script></head>" % mock_js)
            body = html.encode("utf-8")
            handler.send_response(200)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.send_header("Content-Length", str(len(body)))
            handler.send_header("Cache-Control", "no-store")
            handler.end_headers()
            handler.wfile.write(body)
            return
        if path.startswith("/static/"):
            server_self._send(handler, AssetServer._safe_join(
                server_self.webui, path[len("/static/"):]))
            return
        if path.startswith("/res/image/"):
            server_self._send(handler, AssetServer._safe_join(
                os.path.join(server_self.data, "images"), path[len("/res/image/"):]))
            return
        if path.startswith("/res/icon/"):
            server_self._send(handler, AssetServer._safe_join(
                os.path.join(server_self.data, "images", "icon"), path[len("/res/icon/"):]))
            return
        if path.startswith("/res/"):
            server_self._send(handler, AssetServer._safe_join(
                server_self.data, path[len("/res/"):]))
            return
        handler.send_error(404, "not found")

    def start(self):
        server_ref = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                try:
                    server_ref._handle(self, server_ref)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.port = free_port()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    @property
    def url(self) -> str:
        return "http://127.0.0.1:%d/" % self.port

    def stop(self):
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


# =============================================================================
# 三、CDP 客户端（纯标准库 WebSocket）
# =============================================================================

class WSClient:
    """最小 WebSocket 客户端：只支持本工具需要的文本帧 + 分片 + ping。"""

    def __init__(self, url: str, timeout: float = 30.0):
        rest = url.split("://", 1)[1]
        host_port, _, path = rest.partition("/")
        host, _, port = host_port.partition(":")
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        request = ("GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\n"
                   "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
                   "Sec-WebSocket-Version: 13\r\n\r\n" % (path, host_port, key))
        self.sock.sendall(request.encode())
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("WebSocket 握手被关闭")
            data += chunk
        head = data.split(b"\r\n\r\n")[0]
        if b"101" not in head.split(b"\r\n")[0]:
            raise RuntimeError("WebSocket 握手失败：%r" % head[:200])
        self.msg_id = 0

    def _send_frame(self, payload: bytes, opcode: int = 0x1):
        mask = os.urandom(4)
        head = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126)
            head += struct.pack(">H", n)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", n)
        head += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(head) + masked)

    def _read_exact(self, n: int) -> bytes:
        out = b""
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise RuntimeError("WebSocket 连接已断开")
            out += chunk
        return out

    def recv(self) -> str:
        payload = b""
        while True:
            b1, b2 = self._read_exact(2)
            fin = b1 & 0x80
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else None
            data = self._read_exact(length) if length else b""
            if mask:
                data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
            if opcode == 0x8:
                raise RuntimeError("WebSocket 收到 close 帧")
            if opcode == 0x9:
                self._send_frame(data, opcode=0xA)
                continue
            if opcode == 0xA:
                continue
            payload += data
            if fin:
                return payload.decode("utf-8", "replace")

    def call(self, method: str, params: dict = None, timeout: float = 60.0):
        self.msg_id += 1
        mid = self.msg_id
        self._send_frame(json.dumps({"id": mid, "method": method,
                                     "params": params or {}}).encode("utf-8"))
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("%s → %s" % (method, msg["error"]))
                return msg.get("result", {})
        raise TimeoutError("CDP 超时：%s" % method)

    def close(self):
        try:
            self._send_frame(b"", opcode=0x8)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


class Browser:
    """headless Edge + CDP 会话。全程无可见窗口。"""

    def __init__(self, edge: str, viewport=DEFAULT_VIEWPORT, verbose: bool = False,
                 keep_temp: bool = False, extra_args=None):
        self.edge = edge
        self.viewport = viewport
        self.verbose = verbose
        self.keep_temp = keep_temp
        self.extra_args = list(extra_args or [])
        self.port = free_port()
        self.profile = tempfile.mkdtemp(prefix="gcp_ui_assets_")
        self.proc = None
        self.ws = None

    def start(self):
        args = [
            self.edge, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--no-first-run", "--no-default-browser-check",
            "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
            "--disable-features=Translate,MediaRouter,OptimizationHints",
            "--force-device-scale-factor=1",
            "--window-size=%d,%d" % self.viewport,
            "--remote-debugging-port=%d" % self.port,
            "--user-data-dir=%s" % self.profile,
        ] + self.extra_args + ["about:blank"]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % self.port,
                                            timeout=1) as resp:
                    json.loads(resp.read().decode("utf-8"))
                    break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("headless Edge 没起来（CDP 端口无响应）")
        request = urllib.request.Request(
            "http://127.0.0.1:%d/json/new?about:blank" % self.port, method="PUT")
        with urllib.request.urlopen(request, timeout=15) as resp:
            target = json.loads(resp.read().decode("utf-8"))
        self.ws = WSClient(target["webSocketDebuggerUrl"])
        self.ws.call("Page.enable")
        self.ws.call("Runtime.enable")
        self.ws.call("Emulation.setDeviceMetricsOverride", {
            "width": self.viewport[0], "height": self.viewport[1],
            "deviceScaleFactor": 1, "mobile": False})
        return self

    # ---------- 基础动作 ----------
    def goto(self, url: str):
        self.ws.call("Page.navigate", {"url": url})

    def eval(self, expression: str, timeout: float = 60.0):
        res = self.ws.call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True,
            "awaitPromise": True, "userGesture": True}, timeout=timeout)
        if res.get("exceptionDetails"):
            raise RuntimeError("JS 异常：%s" % json.dumps(
                res["exceptionDetails"], ensure_ascii=False)[:600])
        return res.get("result", {}).get("value")

    def wait_js(self, expression: str, timeout: float = 20.0, interval: float = 0.15) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.eval(expression):
                    return True
            except Exception:
                pass
            time.sleep(interval)
        return False

    def set_transparent_background(self, transparent: bool):
        if transparent:
            self.ws.call("Emulation.setDefaultBackgroundColorOverride",
                         {"color": {"r": 0, "g": 0, "b": 0, "a": 0}})
        else:
            self.ws.call("Emulation.setDefaultBackgroundColorOverride", {})

    def screenshot(self, clip: dict, scale: float, transparent: bool) -> bytes:
        params = {
            "format": "png",
            "captureBeyondViewport": True,
            "fromSurface": True,
            "omitBackground": bool(transparent),
            "clip": {"x": clip["x"], "y": clip["y"], "width": clip["width"],
                     "height": clip["height"], "scale": scale},
        }
        res = self.ws.call("Page.captureScreenshot", params, timeout=120)
        return base64.b64decode(res["data"])

    def close(self):
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        self.ws = None
        if self.proc:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=15)
            except Exception:
                pass
            try:
                self.proc.kill()
            except Exception:
                pass
            self.proc = None
        if self.keep_temp:
            eprint("· 已保留临时 profile：%s" % self.profile)
        else:
            shutil.rmtree(self.profile, ignore_errors=True)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()


# =============================================================================
# 四、注入到页面的 JS：收集候选组件 / 准备截图 / 还原
# =============================================================================

JS_HELPERS = r"""
window.__gcpAsset = (function () {
  var ATTR = 'data-gcp-export-id';
  var saved = [];
  var hidden = [];
  function rect(el) { var b = el.getBoundingClientRect();
    return { x: b.left, y: b.top, w: b.width, h: b.height }; }
  function alphaOf(color) {
    if (!color) return 0;
    var m = String(color).match(/rgba?\(([^)]+)\)/);
    if (!m) return 1;
    var parts = m[1].split(',').map(function (s) { return parseFloat(s); });
    return parts.length >= 4 ? parts[3] : 1;
  }
  /* 阴影要一起截进来：按 box-shadow 的 blur/offset/spread 算外扩像素 */
  function shadowPad(el) {
    var s = getComputedStyle(el).boxShadow, pad = 2;
    if (!s || s === 'none') return pad;
    var cleaned = s.replace(/rgba?\([^)]*\)/g, '').replace(/color\([^)]*\)/g, '');
    cleaned.split(',').forEach(function (part) {
      var nums = (part.match(/-?[0-9.]+px/g) || []).map(parseFloat);
      if (nums.length >= 3) {
        var ox = nums[0] || 0, oy = nums[1] || 0, blur = nums[2] || 0, spread = nums[3] || 0;
        pad = Math.max(pad, Math.max(Math.abs(ox), Math.abs(oy)) + blur + Math.max(0, spread) + 2);
      }
    });
    return Math.min(80, Math.ceil(pad));
  }
  function backdropOf(el) {
    var node = el;
    while (node && node !== document.documentElement) {
      var v = getComputedStyle(node).backdropFilter;
      if (v && v !== 'none') return v;
      node = node.parentElement;
    }
    return 'none';
  }
  function clipsOf(el, pad) {
    var r = rect(el), out = [], node = el.parentElement;
    while (node && node !== document.documentElement) {
      var c = getComputedStyle(node);
      if (c.overflowX !== 'visible' || c.overflowY !== 'visible') {
        var pr = rect(node);
        if (pr.w > 0) {
          var cut = (r.x - pad) < pr.x - 0.5 || (r.y - pad) < pr.y - 0.5 ||
                    (r.x + r.w + pad) > (pr.x + pr.w) + 0.5 ||
                    (r.y + r.h + pad) > (pr.y + pr.h) + 0.5;
          if (cut) out.push({ cls: String(node.className || node.tagName).slice(0, 60),
                              overflowX: c.overflowX, overflowY: c.overflowY });
        }
      }
      node = node.parentElement;
    }
    return out;
  }
  function describe(el) {
    var parts = [], node = el;
    while (node && node !== document.body && parts.length < 4) {
      var tag = node.tagName.toLowerCase();
      var cls = String(node.className || '').trim().split(/\s+/).slice(0, 2).join('.');
      parts.unshift(cls ? tag + '.' + cls : tag);
      node = node.parentElement;
    }
    return parts.join(' > ');
  }
  function collect(opts) {
    var results = [], skipped = [], used = [], ids = 0;
    function accept(el, name, note) {
      if (!el || used.indexOf(el) >= 0) return false;
      var r = rect(el), cs = getComputedStyle(el);
      if (!r.w || !r.h || r.w < opts.minW || r.h < opts.minH) {
        skipped.push({ name: name, reason: '尺寸过小（' + Math.round(r.w) + 'x' +
          Math.round(r.h) + '），单独成图没有意义' });
        return false;
      }
      if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) {
        skipped.push({ name: name, reason: '当前不可见（display/visibility/opacity）' });
        return false;
      }
      used.push(el);
      var pad = shadowPad(el);
      var info = {
        id: ids, name: name, selector: describe(el), tag: el.tagName.toLowerCase(),
        cls: String(el.className || '').slice(0, 120),
        /* locator：截图时用它重新定位元素。
           ⚠️ 为什么不能只靠 data 属性：搜索页是虚拟列表，滚动会触发重渲染，
              打过标记的节点可能被 Vue 换成新节点（实测 "元素已不在 DOM"）。
              所以同时存「选择器 + 该选择器下的序号 + 文字前缀」，重渲染后还能找回来。 */
        locator: { id: ids, sel: sel_used || ('.' + String(el.className || '').trim().split(/\s+/)[0]),
                   index: index_used || 0,
                   text: (el.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 40) },
        rect: { x: r.x, y: r.y, w: r.w, h: r.h },
        pad: pad, clips: clipsOf(el, pad),
        backdrop: backdropOf(el), position: cs.position,
        radius: cs.borderRadius, shadow: String(cs.boxShadow || '').slice(0, 120),
        text: (el.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 80),
        note: note || ''
      };
      el.setAttribute(ATTR, String(ids));
      ids += 1;
      results.push(info);
      return true;
    }
    var sel_used = '', index_used = 0;
    (opts.curated || []).forEach(function (spec) {
      var nodes = [];
      try { nodes = Array.prototype.slice.call(document.querySelectorAll(spec.sel)); }
      catch (e) { skipped.push({ name: spec.name, reason: '选择器写法错误：' + spec.sel }); return; }
      if (!nodes.length) {
        skipped.push({ name: spec.name, reason: '本页没有匹配到元素（选择器 ' + spec.sel +
          '），可能该页结构变了' });
        return;
      }
      var limit = spec.limit || 1;
      var taken = 0;
      for (var i = 0; i < nodes.length && taken < limit; i += 1) {
        var name = limit > 1 ? spec.name + '-' + (taken + 1) : spec.name;
        sel_used = spec.sel; index_used = i;
        if (accept(nodes[i], name, spec.note)) taken += 1;
      }
    });
    if (opts.auto && opts.auto.tokens && opts.auto.tokens.length) {
      var vw = window.innerWidth, vh = window.innerHeight;
      var pageArea = vw * vh;
      opts.auto.tokens.forEach(function (token) {
        if (results.length >= opts.maxTotal) return;
        var nodes = [];
        try { nodes = Array.prototype.slice.call(document.querySelectorAll('.' + token)); }
        catch (e) { return; }
        var taken = 0;
        for (var i = 0; i < nodes.length && taken < (opts.auto.limit || 2); i += 1) {
          if (results.length >= opts.maxTotal) break;
          var el = nodes[i], r = rect(el);
          if (!r.w || !r.h) continue;
          if (r.w * r.h > pageArea * 0.7) continue;            /* 整页容器不要 */
          if (el === document.querySelector('.page')) continue;
          sel_used = '.' + token; index_used = i;
          if (accept(el, token + '-' + (taken + 1), '自动发现')) taken += 1;
        }
      });
    }
    return { assets: results, skipped: skipped,
             scroll: { x: window.scrollX, y: window.scrollY },
             doc: { w: document.documentElement.scrollWidth,
                    h: document.documentElement.scrollHeight } };
  }
  function locate(locator) {
    var el = document.querySelector('[' + ATTR + '="' + locator.id + '"]');
    if (el) return el;
    if (!locator.sel) return null;
    var nodes = [];
    try { nodes = Array.prototype.slice.call(document.querySelectorAll(locator.sel)); }
    catch (e) { return null; }
    if (locator.text) {
      for (var i = 0; i < nodes.length; i += 1) {
        if ((nodes[i].innerText || '').trim().replace(/\s+/g, ' ').indexOf(locator.text) === 0) {
          nodes[i].setAttribute(ATTR, String(locator.id));
          return nodes[i];
        }
      }
    }
    var fallback = nodes[locator.index || 0];
    if (fallback) fallback.setAttribute(ATTR, String(locator.id));
    return fallback || null;
  }
  function needsScroll(el) {
    var r = el.getBoundingClientRect();
    return r.top < 4 || r.left < 4 || r.bottom > (window.innerHeight - 4) ||
           r.right > (window.innerWidth - 4);
  }
  async function prepare(locator, transparent) {
    var el = locate(locator);
    if (!el) return { error: '元素已不在 DOM（页面重渲染了），跳过' };
    var cs = getComputedStyle(el);
    if (cs.position === 'fixed' || cs.position === 'sticky') {
      window.scrollTo(0, 0);
    } else if (needsScroll(el)) {
      /* 只在真的露不全时才滚动：搜索页是虚拟列表，滚动会触发重渲染，
         已经完整可见的元素就别动它，能少一次"节点被换掉"的机会。 */
      try { el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' }); }
      catch (e) { el.scrollIntoView(); }
    }
    await new Promise(function (r) { requestAnimationFrame(function () { requestAnimationFrame(r); }); });
    await new Promise(function (r) { setTimeout(r, 90); });
    /* 滚动可能让 Vue 重建节点：重新定位一次（locator 里存了选择器+序号+文字） */
    el = locate(locator);
    if (!el) return { error: '滚动后元素被重新渲染掉了，跳过' };
    restore();
    var isolated = 0;
    if (transparent) {
      /* 先把祖先链上的兄弟节点藏起来：否则外扩的截图范围里会出现邻居卡片 */
      isolated = isolate(el);
      /* 只清"大面积祖先背景"：整页渐变 / 页面底色不该出现在组件图里。
         组件自己的底色、边框、阴影一律不动（那才是素材本体）。 */
      var node = el.parentElement;
      while (node && node !== document.documentElement) {
        var c = getComputedStyle(node);
        var b = node.getBoundingClientRect();
        var big = (b.width * b.height) > (window.innerWidth * window.innerHeight * 0.05);
        var hasPaint = c.backgroundImage !== 'none' || alphaOf(c.backgroundColor) > 0.02;
        if (big && hasPaint) {
          saved.push({ node: node, bg: node.style.background,
                       bgImage: node.style.backgroundImage });
          node.style.background = 'transparent';
          node.style.backgroundImage = 'none';
        }
        node = node.parentElement;
      }
      await new Promise(function (r) { setTimeout(r, 30); });
    }
    var r2 = el.getBoundingClientRect();
    var docW = Math.max(document.documentElement.scrollWidth, window.innerWidth);
    var docH = Math.max(document.documentElement.scrollHeight, window.innerHeight);
    /* 轮播/位移动画里的元素可能被 transform 挪到文档可视范围之外，scrollIntoView 也拉不回来。
       这种不是"截图参数有问题"，直接跳过并说明原因，别硬截图变成一张废图。 */
    if (r2.width <= 0 || r2.height <= 0 ||
        r2.right <= 0 || r2.bottom <= 0 ||
        r2.left >= docW || r2.top >= docH) {
      return { error: '元素被动画/位移挪到文档可视范围外（轮播或过渡中），跳过' };
    }
    return {
      ok: true,
      rect: { x: r2.left, y: r2.top, w: r2.width, h: r2.height },
      pad: shadowPad(el),
      clips: clipsOf(el, shadowPad(el)),
      scroll: { x: window.scrollX, y: window.scrollY },
      doc: { w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight },
      clearedAncestors: saved.length
    };
  }
  /* ---- 隔离目标元素：把祖先链上的兄弟节点全部 visibility:hidden ----
     ⚠️ 为什么必须隔离：截图范围要外扩以装下阴影（pad），而这个范围内经常压着
        兄弟卡片/相邻控件 —— 不隔离的话"一个卡片的素材"里会有半张邻居卡片（实测过）。
        用 visibility 而不是 display：不改变布局，元素坐标保持不变。 */
  function isolate(el) {
    var node = el;
    while (node && node.parentElement && node !== document.body) {
      var parent = node.parentElement;
      var kids = Array.prototype.slice.call(parent.children);
      for (var i = 0; i < kids.length; i += 1) {
        var child = kids[i];
        if (child === node) continue;
        if (child === el) continue;
        var cs = getComputedStyle(child);
        if (cs.display === 'none' || cs.visibility === 'hidden') continue;
        hidden.push({ el: child, visibility: child.style.visibility });
        child.style.visibility = 'hidden';
      }
      node = parent;
    }
    /* 固定定位的覆盖层（标题栏 / 悬浮球 / 遮罩）不在这条链上，单独按相交判断 */
    var r = el.getBoundingClientRect(), pad = shadowPad(el);
    var box = { x: r.left - pad, y: r.top - pad, w: r.width + pad * 2, h: r.height + pad * 2 };
    Array.prototype.slice.call(document.querySelectorAll('body > *, body > * > *')).forEach(function (n) {
      var cs = getComputedStyle(n);
      if (cs.position !== 'fixed' && cs.position !== 'sticky') return;
      if (n === el || n.contains(el)) return;
      var b = n.getBoundingClientRect();
      if (b.width < 2 || b.height < 2) return;
      var hit = !(b.right < box.x || b.left > box.x + box.w ||
                  b.bottom < box.y || b.top > box.y + box.h);
      if (!hit) return;
      hidden.push({ el: n, visibility: n.style.visibility });
      n.style.visibility = 'hidden';
    });
    return hidden.length;
  }
  function unisolate() {
    for (var i = hidden.length - 1; i >= 0; i -= 1) {
      try { hidden[i].el.style.visibility = hidden[i].visibility; } catch (e) {}
    }
    hidden = [];
  }
  function restore() {
    unisolate();
    for (var i = saved.length - 1; i >= 0; i -= 1) {
      var item = saved[i];
      try { item.node.style.background = item.bg; item.node.style.backgroundImage = item.bgImage; }
      catch (e) {}
    }
    saved = [];
  }
  /* 第二版（backdrop-filter 组件专用）：保留页面背景（材质需要它），但同样把邻居藏掉，
     这样导出的 __opaque 图是"卡片 + 它身后的页面底色"，而不是"卡片 + 半张邻居卡片"。 */
  async function prepareOpaque(locator) {
    restore();
    var el = locate(locator);
    if (!el) return { error: '元素已不在 DOM' };
    isolate(el);
    await new Promise(function (r) { requestAnimationFrame(function () { requestAnimationFrame(r); }); });
    await new Promise(function (r) { setTimeout(r, 60); });
    var r2 = el.getBoundingClientRect();
    return { ok: true, rect: { x: r2.left, y: r2.top, w: r2.width, h: r2.height },
             pad: shadowPad(el), scroll: { x: window.scrollX, y: window.scrollY } };
  }
  function cleanup() {
    restore();
    var marked = document.querySelectorAll('[' + ATTR + ']');
    for (var i = 0; i < marked.length; i += 1) marked[i].removeAttribute(ATTR);
  }
  return { collect: collect, prepare: prepare, prepareOpaque: prepareOpaque,
           restore: restore, cleanup: cleanup, shadowPad: shadowPad };
})();
"""

JS_DISMISS = r"""
(function () {
  var hit = 0;
  var want = /稍后|关闭|取消|全部已读|知道了|同意|不再提示|OK|Close|Later|Cancel|Got it/i;
  document.querySelectorAll('.modal-backdrop, .pop-backdrop').forEach(function (back) {
    var btn = null;
    back.querySelectorAll('.btn, .icon-btn').forEach(function (b) {
      if (!btn && want.test((b.textContent || '').trim())) btn = b;
    });
    if (btn) { btn.click(); hit += 1; }
    else if (back.classList.contains('modal-backdrop')) { back.click(); hit += 1; }
  });
  return hit;
})()
"""

# 按选择器 + 文案点击的通用助手：注入一次，后面所有 actions 都能用。
# targets = [[selector, 期望文案或 '', 第几个], ...]；空文案表示不按文案过滤。
JS_CLICK_HELPER = r"""
window.__clickText__ = function (targets) {
  for (var t = 0; t < targets.length; t += 1) {
    var sel = String(targets[t][0] || ''), text = String(targets[t][1] || '');
    var idx = targets[t][2] || 0;
    var nodes = [];
    try { nodes = Array.prototype.slice.call(document.querySelectorAll(sel)); }
    catch (e) { continue; }
    if (text) nodes = nodes.filter(function (n) {
      return ((n.getAttribute('title') || '') + ' ' + (n.textContent || '')).indexOf(text) >= 0;
    });
    var hit = nodes[idx];
    if (hit) {
      hit.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      hit.click();
      return { clicked: true, cls: String(hit.className || '').slice(0, 60) };
    }
  }
  return { clicked: false };
};
"""

JS_SCROLL_TOP = r"""
(function () {
  document.querySelectorAll('[data-scroll-key], .page-scroll, .content, .maker-form-scroll, .settings-main')
    .forEach(function (el) { try { el.scrollTop = 0; } catch (e) {} });
  window.scrollTo(0, 0);
  return true;
})()
"""

# 透明背景：为什么要在页面里用 canvas 算 alpha
# 实测（本机 Edge 133 / headless=new）：`Page.captureScreenshot` 无论
# omitBackground / fromSurface / captureBeyondViewport 怎么组合、就算页面是
# `background: transparent`，返回的 PNG **永远是 RGB（无 alpha 通道）**——
# 这是该内核在 headless 下的限制，不是参数写法问题。
# 于是改用"双背景抠像"：
#   ① 把页面（html/body）强制刷成纯黑 #000 截一张；
#   ② 再刷成纯白 #FFF 截一张；
#   同一个像素的合成公式：观测 = 前景×a + 背景×(1-a)
#   ⇒ a = 1 - (白底观测 - 黑底观测) / 255，前景色 = 黑底观测 / a。
#   这是标准的反预乘做法，**保留了抗锯齿与半透明材质**，比"色键抠图"干净得多。
# 计算放在页面里用 canvas 做（浏览器原生速度），Python 只收发 base64，
# 不引第三方库也不需要慢速逐像素 Python 循环。
JS_ALPHA_EXTRACT = r"""
window.__gcpAlpha = (function () {
  var canvas = null, ctx = null;
  function load(url) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () { resolve(img); };
      img.onerror = function () { reject(new Error('图片解码失败')); };
      img.src = url;
    });
  }
  async function extract(blackUrl, whiteUrl) {
    var a = await load(blackUrl);
    var b = await load(whiteUrl);
    var w = a.naturalWidth, h = a.naturalHeight;
    if (!w || !h) throw new Error('截图为空');
    if (!canvas) canvas = document.createElement('canvas');
    canvas.width = w; canvas.height = h;
    ctx = canvas.getContext('2d', { willReadFrequently: true });
    ctx.clearRect(0, 0, w, h);
    ctx.drawImage(a, 0, 0);
    var da = ctx.getImageData(0, 0, w, h).data;
    ctx.clearRect(0, 0, w, h);
    ctx.drawImage(b, 0, 0);
    var db = ctx.getImageData(0, 0, w, h).data;
    var out = ctx.createImageData(w, h);
    var o = out.data;
    for (var i = 0; i < da.length; i += 4) {
      var rb = da[i], gb = da[i + 1], bb = da[i + 2];
      var rw = db[i], gw = db[i + 1], bw = db[i + 2];
      var delta = ((rw - rb) + (gw - gb) + (bw - bb)) / 3;
      var alpha = 1 - delta / 255;
      if (alpha <= 0.006) { o[i] = 0; o[i + 1] = 0; o[i + 2] = 0; o[i + 3] = 0; continue; }
      if (alpha >= 0.994) alpha = 1;
      var inv = 1 / alpha;
      var r = Math.round(rb * inv), g = Math.round(gb * inv), bl = Math.round(bb * inv);
      o[i] = r < 0 ? 0 : (r > 255 ? 255 : r);
      o[i + 1] = g < 0 ? 0 : (g > 255 ? 255 : g);
      o[i + 2] = bl < 0 ? 0 : (bl > 255 ? 255 : bl);
      o[i + 3] = Math.round(alpha * 255);
    }
    ctx.putImageData(out, 0, 0);
    return canvas.toDataURL('image/png');
  }
  return { extract: extract };
})();
"""

# 把整页刷成纯色（双背景抠像用）。只动 html/body 的底色，组件自己的颜色一律不动。
JS_ALPHA_PROBE_ON = r"""
(function () {
  var id = '__gcp_probe_bg__';
  var style = document.getElementById(id);
  if (!style) { style = document.createElement('style'); style.id = id;
                document.head.appendChild(style); }
  style.textContent = 'html,body{background:__COLOR__ !important;' +
                      'background-image:none !important}';
  return true;
})()
"""

JS_ALPHA_PROBE_OFF = r"""
(function () {
  var style = document.getElementById('__gcp_probe_bg__');
  if (style) style.remove();
  return true;
})()
"""


# =============================================================================
# 五、页面与组件目录（选择器全部来自对真实 DOM 的清点，见下方清单注释）
# =============================================================================

# auto.tokens：自动发现时允许的 class 名（都是真实存在的组件类，不会瞎猜）
AUTO_TOKENS = [
    "card", "card-icon", "card-title", "card-desc", "card-btn", "card-tint",
    "btn", "btn-primary", "btn-sm", "btn-block", "btn-half", "btn-danger-ghost",
    "icon-btn", "chip", "tag", "tag-more", "switch", "switch-knob",
    "combo-trigger", "segmented", "seg-item", "input", "badge",
    "bubble", "bubble-actions", "bubble-btn", "ai-input-row", "ai-send", "ai-polish",
    "float-ball", "notice-card", "notice-title", "notice-body", "gh-card", "gh-title",
    "log-item", "log-list", "deploy-toolbar", "deploy-mode-row", "table-head", "table-row",
    "plugin-card", "plugin-icon", "plugin-names", "maker-card", "maker-toolbar", "maker-seg",
    "form-grid", "field", "field-label", "setting-row", "setting-label", "setting-control",
    "settings-card", "settings-side", "list-item", "list-widget", "search-box", "search-lead",
    "filter-btn", "filter-panel", "filter-row", "titlebar", "tb-btn", "nav-item", "nav-badge",
    "nav-indicator", "interest-chip", "onboard-card", "pip", "slide", "carousel",
    "detail-hero", "detail-icon", "detail-grid", "detail-key", "detail-val", "detail-link",
    "preview-card", "preview-icon", "preview-name", "preview-tags", "maker-output-card",
    "browser-row", "browser-head", "batch-row", "batch-file", "qq-row", "qq-image",
    "fb-title", "feedback-card", "section-title", "hairline", "more-item", "combo-item",
    "modal", "modal-title", "modal-actions", "toast", "selection-bar", "sel-count",
    "card-menu", "card-menu-item", "heatmap",
]

PAGES = [
    # ---------------- 常规页面 ----------------
    dict(key="home", title="首页", query="home", selectors=[
        ("carousel", ".carousel", 1, "首页轮播容器（含海报）"),
        ("carousel-slide", ".slide", 2, ""),
        ("carousel-pip", ".pip", 3, ""),
        ("home-plugin-card", ".plugin-card", 2, "首页精选插件卡"),
        ("home-card", ".card", 2, ""),
    ]),
    dict(key="search", title="搜索页", query="search", selectors=[
        ("search-box", ".search-box", 1, ""),
        ("search-toolbar", ".toolbar-row", 1, ""),
        ("filter-btn", ".filter-btn", 1, ""),
        ("view-seg", ".view-seg", 1, "视图切换分段"),
        ("sort-combo", ".combo-trigger", 1, ""),
        ("search-card", ".card", 3, ""),
        ("card-icon", ".card-icon", 2, ""),
        ("card-btn", ".card-btn", 3, ""),
        ("search-chip", ".chip", 4, ""),
        ("search-tag", ".tag", 3, ""),
    ]),
    dict(key="search-filter", title="搜索页-筛选面板", query="search",
         actions=["filter"], selectors=[
             ("filter-panel", ".filter-panel", 1, "展开后的筛选面板"),
             ("filter-row", ".filter-row", 2, ""),
             ("filter-chip-on", ".chip.is-on", 3, "选中态胶囊"),
         ]),
    dict(key="detail", title="详情页", query="search", actions=["open-detail"], selectors=[
        ("detail-wrap", ".detail-wrap", 1, "详情整块（含滚动内容）"),
        ("detail-topbar", ".detail-topbar", 1, ""),
        ("detail-hero", ".detail-hero", 1, ""),
        ("detail-icon", ".detail-icon", 1, ""),
        ("detail-link", ".detail-link", 3, ""),
        ("detail-grid", ".detail-grid", 1, ""),
        ("detail-key", ".detail-key", 3, ""),
        ("detail-val", ".detail-val", 3, ""),
        ("detail-block", ".detail-block", 2, ""),
    ]),
    dict(key="customize", title="定制页", query="customize", selectors=[
        ("onboard-card", ".onboard-card", 1, ""),
        ("interest-chip", ".interest-chip", 4, ""),
        ("customize-btn", ".btn", 2, ""),
    ]),
    dict(key="favorites", title="收藏页", query="favorites", selectors=[
        ("fav-side", ".fav-side", 1, ""),
        ("fav-list-item", ".list-item", 2, ""),
        ("fav-btn", ".btn", 4, ""),
    ]),
    dict(key="notice", title="公告页", query="notice", selectors=[
        ("notice-card", ".notice-card", 2, ""),
        ("notice-title", ".notice-title", 2, ""),
        ("notice-body", ".notice-body", 1, ""),
    ]),
    dict(key="github", title="Github 页", query="github", selectors=[
        ("gh-wrap", ".gh-wrap", 1, ""),
        ("gh-card", ".gh-card", 2, ""),
        ("gh-title", ".gh-title", 2, ""),
    ]),
    dict(key="feedback", title="反馈页", query="feedback", selectors=[
        ("feedback-card", ".feedback-card", 1, ""),
        ("qq-row", ".qq-row", 1, ""),
        ("fb-btn", ".btn-primary", 1, ""),
    ]),
    dict(key="log", title="查看日志", query="log", selectors=[
        ("log-list", ".log-list", 1, ""),
        ("log-item", ".log-item", 3, ""),
        ("log-btn", ".btn", 3, ""),
    ]),
    dict(key="deploy", title="应用部署", query="deploy", selectors=[
        ("deploy-wrap", ".deploy-wrap", 1, ""),
        ("deploy-toolbar", ".deploy-toolbar", 1, ""),
        ("deploy-mode-row", ".deploy-mode-row", 1, ""),
        ("deploy-table-head", ".table-head", 1, ""),
        ("deploy-table-row", ".table-row", 3, ""),
        ("deploy-switch", ".switch", 1, ""),
    ]),
    dict(key="plugins", title="插件页", query="plugins", selectors=[
        ("plugin-wrap", ".plugin-wrap", 1, ""),
        ("plugin-page-head", ".plugin-page-head", 1, ""),
        ("plugin-search", ".plugin-search", 1, ""),
        ("plugin-card", ".plugin-card", 3, ""),
        ("plugin-icon", ".plugin-icon", 2, ""),
    ]),
    dict(key="maker-form", title="提交软件-投稿表单", query="maker", selectors=[
        ("maker-header", ".maker-header", 1, ""),
        ("maker-toolbar", ".maker-toolbar", 1, ""),
        ("maker-seg", ".maker-seg", 1, ""),
        ("maker-card", ".maker-card", 3, ""),
        ("maker-field", ".field", 3, ""),
        ("maker-input", ".input", 3, ""),
        ("maker-category-combo", ".combo-trigger", 1, ""),
        ("maker-chip", ".chip", 3, ""),
        ("maker-step", ".maker-card-step", 3, ""),
        ("preview-card", ".preview-card", 1, "实时预览卡"),
        ("output-card", ".maker-output-card", 1, "产出卡"),
        ("output-btn", ".btn-block", 4, ""),
    ]),
    dict(key="maker-browser", title="提交软件-资源浏览", query="maker",
         actions=["maker-tab:browser"], selectors=[
             ("browser-bar", ".maker-browser-bar", 1, ""),
             ("browser-panel", ".browser-panel", 1, ""),
             ("browser-head", ".browser-head", 1, ""),
             ("browser-row", ".browser-row", 4, ""),
             ("browser-foot", ".browser-foot", 1, ""),
         ]),
    dict(key="maker-batch", title="提交软件-批量合成", query="maker",
         actions=["maker-tab:batch"], selectors=[
             ("batch-card", ".maker-card", 3, ""),
             ("batch-row", ".batch-row", 2, ""),
             ("batch-file-list", ".batch-file-list", 1, ""),
             ("batch-combo", ".combo-trigger", 2, ""),
         ]),
    dict(key="settings", title="设置页", query="settings", selectors=[
        ("settings-side", ".settings-side", 1, ""),
        ("settings-side-item", ".list-item", 3, ""),
        ("settings-card", ".settings-card", 2, ""),
        ("setting-row", ".setting-row", 4, ""),
        ("setting-label", ".setting-label", 3, ""),
        ("setting-combo", ".combo-trigger", 2, ""),
        ("setting-switch", ".switch", 2, ""),
        ("setting-btn", ".btn-sm", 2, ""),
        ("settings-search", ".search-box", 1, ""),
        ("section-title", ".section-title", 3, ""),
    ]),
    # ---------------- 浮层 / 侧栏 / AI ----------------
    dict(key="ai-page", title="GCP-AI 整页", query="search",
         settings={"ai": "1", "aiside": "1"},
         actions=["goto-ai"], selectors=[
             ("ai-embedded", ".ai-embedded", 1, ""),
             ("ai-head", ".ai-head", 1, ""),
             ("ai-brand", ".ai-brand", 1, ""),
             ("ai-messages", ".ai-messages", 1, ""),
             ("ai-bubble", ".bubble.is-ai", 1, "AI 气泡"),
             ("ai-input-row", ".ai-input-row", 1, ""),
             ("ai-send", ".ai-send", 1, ""),
             ("ai-polish", ".ai-polish", 1, ""),
         ]),
    dict(key="ai-drawer", title="GCP-AI 悬浮抽屉", query="search",
         settings={"ai": "1", "aiside": "0"}, actions=["open-ai-drawer"], selectors=[
             ("ai-drawer", ".ai-drawer", 1, ""),
             ("ai-drawer-head", ".ai-head", 1, ""),
             ("ai-drawer-bubble", ".bubble.is-ai", 1, ""),
             ("ai-drawer-input", ".ai-input-row", 1, ""),
             ("ai-drawer-send", ".ai-send", 1, ""),
         ]),
    dict(key="chrome", title="窗口框架（标题栏 / 悬浮球 / 侧栏）", query="home", selectors=[
        ("titlebar", ".titlebar", 1, "自绘标题栏"),
        ("titlebar-btn", ".tb-btn", 3, ""),
        ("float-ball", ".float-ball", 1, "AI 悬浮球"),
        ("nav-item", ".nav-item", 4, ""),
        ("nav-burger", ".nav-burger", 1, ""),
    ]),
    dict(key="nav-expanded", title="侧栏展开态", query="home", actions=["nav-expand"], selectors=[
        ("nav-expanded", ".nav", 1, ""),
        ("nav-label", ".nav-label", 3, ""),
        ("nav-indicator", ".nav-indicator", 1, ""),
    ]),
    dict(key="more-menu", title="更多菜单", query="home", actions=["more-menu"], selectors=[
        ("more-pop", ".more-pop", 1, ""),
        ("more-item", ".more-item", 4, ""),
    ]),
    dict(key="combo-pop", title="下拉弹层", query="search", actions=["open-combo"], selectors=[
        ("combo-pop", ".combo-pop", 1, ""),
        ("combo-item", ".combo-item", 3, ""),
    ]),
    dict(key="card-menu", title="卡片右键菜单", query="search", actions=["card-menu"], selectors=[
        ("card-menu", ".card-menu", 1, ""),
        ("card-menu-item", ".card-menu-item", 3, ""),
    ]),
    dict(key="modal", title="公告弹层", query="notice", keep_dialogs=True, selectors=[
        ("modal", ".modal", 1, "带遮罩的弹窗本体"),
        ("modal-title", ".modal-title", 1, ""),
        ("modal-body", ".modal-body", 1, ""),
        ("modal-btn", ".modal-actions .btn", 2, ""),
    ]),
]

# 每个页面导航后要做的额外动作（JS 片段，全部来自真实 DOM）
# ---------------------------------------------------------------- 分页整图状态
# 每个页面可以挂 states：按顺序切换页面内的分页/视图，每个状态导一张**整程序整图**。
SETTINGS_TABS = ["外观", "动画", "启动", "搜索", "快捷键", "下载", "通知",
                 "功能", "存储", "GCP-AI", "开发者功能", "关于"]


def _settings_tab_js(index: int) -> str:
    return ("(function(){var n=document.querySelectorAll('.settings-side .list-item');"
            "if(n[%d]) n[%d].click(); return !!n[%d];})()" % (index, index, index))


PAGE_STATES = {
    "home": [("default", "首页", "")],
    "search": [
        ("tile", "磁贴视图", ""),
        ("grid", "网格视图", "(function(){var b=document.querySelectorAll('.view-seg .seg-item');"
                            "if(b[1]) b[1].click(); return !!b[1];})()"),
        ("filter", "筛选面板", "(function(){var b=document.querySelector('.filter-btn');"
                                 "if(b) b.click(); return !!b;})()"),
    ],
    "customize": [("default", "推荐", "")],
    "favorites": [
        ("default", "默认收藏夹", ""),
        ("folder", "其它收藏夹", "(function(){var n=document.querySelectorAll('.fav-side .list-item');"
                               "if(n[1]) n[1].click(); return !!n[1];})()"),
    ],
    "notice": [("default", "公告", "")],
    "github": [("default", "Github", "")],
    "feedback": [("default", "反馈", "")],
    "log": [("default", "日志", "")],
    "deploy": [
        ("export", "导出模式", ""),
        ("deploy", "部署模式", "(function(){var b=document.querySelector('.deploy-mode-row .switch');"
                             "if(b) b.click(); return !!b;})()"),
    ],
    "plugins": [("grid", "插件网格", "")],
    "maker-form": [("form", "投稿表单", "")],
    "maker-browser": [("browser", "资源浏览", "")],
    "maker-batch": [("batch", "批量合成", "")],
    "maker-help": [("help", "使用说明", "")],
    "settings": [("tab%d" % i, SETTINGS_TABS[i], _settings_tab_js(i))
                 for i in range(len(SETTINGS_TABS))],
    "ai-page": [("chat", "AI 对话", "")],
    "ai-drawer": [("drawer", "AI 抽屉", "")],
    "chrome": [("default", "窗口框架", "")],
}


ACTION_JS = {
    "filter": "(function(){var b=document.querySelector('.filter-btn'); if(b) b.click(); return !!b;})()",
    "open-detail": "(function(){var c=document.querySelector('.card'); if(c) c.click(); return !!c;})()",
    "goto-ai": "window.__clickText__([['.nav-item','AI']])",
    "open-ai-drawer": "(function(){var b=document.querySelector('.float-ball'); if(b) b.click(); return !!b;})()",
    "nav-expand": "(function(){var b=document.querySelector('.nav-burger'); if(b) b.click(); return !!b;})()",
    "more-menu": "window.__clickText__([['.nav-item','更多'],['.nav-burger',''],['.more-btn','']])",
    "open-combo": "(function(){var t=document.querySelector('.combo-trigger'); if(t) t.click(); return !!t;})()",
    "card-menu": ("(function(){var c=document.querySelector('.card'); if(!c) return false;"
                  "var r=c.getBoundingClientRect();"
                  "c.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,"
                  "clientX:Math.round(r.left+r.width/2),clientY:Math.round(r.top+r.height/2)}));"
                  "return true;})()"),
    "maker-tab:browser": "(function(){var t=document.querySelectorAll('.maker-seg .seg-item'); if(t[1]) t[1].click(); return t.length;})()",
    "maker-tab:batch": "(function(){var t=document.querySelectorAll('.maker-seg .seg-item'); if(t[2]) t[2].click(); return t.length;})()",
}


class PageError(RuntimeError):
    pass


def is_connection_lost(exc: Exception) -> bool:
    """判断异常是不是"浏览器/CDP 连接断了"（长任务里 Edge 偶发崩渲染进程）。"""
    text = "%s %s" % (type(exc).__name__, exc)
    for token in ("10054", "10053", "WebSocket", "ws ", "CDP", "ConnectionAborted",
                  "ConnectionReset", "连接已断开", "强迫关闭"):
        if token in text:
            return True
    return False


# =============================================================================
# 六、导出器
# =============================================================================

class Exporter:
    def __init__(self, args, root: str, edge: str):
        self.args = args
        self.root = root
        self.edge = edge
        self.mock = {}
        self.server = None
        self.browser = None
        self._last_clip = None
        self.fx_list = list(getattr(args, "fx_list", None) or [args.fx])
        self.accent_list = list(getattr(args, "accent_list", None) or [args.accent])
        self.combos = [(fx, ac) for fx in self.fx_list for ac in self.accent_list]
        self.multi_combo = len(self.combos) > 1
        self.cur_fx, self.cur_accent = self.combos[0]
        self.manifest = {
            "screens": [],
            "tool": {"name": TOOL_NAME, "version": TOOL_VERSION,
                     "schema": SCHEMA_VERSION, "generated_at": now_iso()},
            "source": {"project": root, "webui": os.path.join(root, ".ToolsGCP", "webui"),
                       "mode": "headless Edge + CDP，从真实 DOM 逐组件截图"},
            "config": {"viewport": list(args.viewport), "scale": args.scale,
                       "themes": args.themes, "fx": args.fx, "accent": args.accent,
                       "fx_list": self.fx_list, "accent_list": self.accent_list,
                       "combos": ["%s-%s" % (fx, ac) for fx, ac in self.combos],
                       "pages": "all" if not args.pages else args.pages},
            "themes": {},
            "assets": [],
            "skipped": [],
            "summary": {},
        }

    # ---------- mock 数据 ----------
    def load_mock_data(self):
        data_dir = os.path.join(self.root, ".ToolsGCP")
        with open(os.path.join(data_dir, "ToolsGCP-Resources.json"), "r",
                  encoding="utf-8") as fh:
            lib = json.load(fh)
        resources = lib.get("resources", []) if isinstance(lib, dict) else lib
        lang_dir = os.path.join(self.root, ".ToolsGCP", "modules", "languages", "zh_CN")
        i18n = {}
        for module, filename in I18N_FILES.items():
            path = os.path.join(lang_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    i18n[module] = json.load(fh)
            except Exception:
                i18n[module] = {}
        plugins = []
        plugin_dir = os.path.join(data_dir, "plugins")
        if os.path.isdir(plugin_dir):
            for name in sorted(os.listdir(plugin_dir)):
                manifest_path = os.path.join(plugin_dir, name, "manifest.json")
                if not os.path.isfile(manifest_path):
                    continue
                try:
                    with open(manifest_path, "r", encoding="utf-8") as fh:
                        m = json.load(fh)
                except Exception:
                    continue
                icon = m.get("icon") or ""
                plugins.append({
                    "id": m.get("id") or name, "name": m.get("name") or name,
                    "version": m.get("version") or "1.0.0",
                    "author": m.get("author") or "—",
                    "description": m.get("description") or "",
                    "enabled": bool(m.get("builtin", False)),
                    "status": "ok", "hasConfig": bool(m.get("config_page")),
                    "note": "", "protected": bool(m.get("builtin", False)),
                    "icon": ("/res/plugins/%s/%s" % (name, icon)) if icon else "",
                })
        notices = [
            {"id": "n1", "title": "欢迎使用 ToolsGCP",
             "body": "ToolsGCP 是一个致力于收录全网好用资源的工具箱聚合平台。\n"
                     "当前版本 1.1.4，支持资源检索、部署、插件与 AI 辅助。",
             "date": "2026-01-01", "author": "Galen563", "number": 1},
            {"id": "n2", "title": "v1.1.4 更新说明",
             "body": "修复了下拉框无法切换、收藏状态不同步等问题；\n"
                     "新增提交软件页与 AI 润色按钮。",
             "date": "2026-01-02", "author": "Galen563", "number": 2},
        ]
        self.mock = {"resources": resources, "settings": {
            "theme": "深色主题", "accent_color": self.args.accent, "language": "简体中文",
            "theme_effect": self.args.fx, "default_page": "搜索",
            "ai_enabled": False, "ai_sidebar_mode": False, "ai_polish_enabled": True,
            "search_view": "tile", "search_card_size": "medium",
            "search_show_github": True, "search_show_view_switch": True,
            "plugin_view": "grid", "deploy_mode": False, "notify_enabled": True,
            "resource_source": "cloud", "ui_font_family": "微软雅黑",
            "ui_animation": "on", "nav_hover_expand": False,
            "customize_interests": [], "customize_onboarded": False,
        }, "notices": notices, "plugins": plugins, "i18n": i18n}

    # ---------- 运行 ----------
    def run(self) -> int:
        self.load_mock_data()
        eprint("· 项目：%s" % self.root)
        eprint("· 资源库：%d 条；语言模块：%d 个；插件：%d 个"
               % (len(self.mock["resources"]), len(self.mock["i18n"]),
                  len(self.mock["plugins"])))
        self.server = AssetServer(self.root, self.mock).start()
        eprint("· 本地只读服务器：%s" % self.server.url)
        started = time.time()
        try:
            self.browser = Browser(self.edge, tuple(self.args.viewport), self.args.verbose,
                                   keep_temp=self.args.keep_temp).start()
            eprint("· headless Edge 已连接（CDP 端口 %d，无可见窗口）" % self.browser.port)
            pages = self.selected_pages()
            for theme in self.args.themes:
                for fx, accent in self.combos:
                    self.cur_fx, self.cur_accent = fx, accent
                    self.mock["settings"]["theme_effect"] = fx
                    self.mock["settings"]["accent_color"] = accent
                    self.run_theme(theme, pages)
        finally:
            if self.browser:
                self.browser.close()
            if self.server:
                self.server.stop()
        self.finish(started)
        return 0 if self.manifest["summary"].get("assets") else 2

    def page_states(self, page):
        """这个页面要导出哪些分页整图（默认一张 default）"""
        states = PAGE_STATES.get(page["key"])
        if states:
            return [{"key": k, "label": label, "js": js} for k, label, js in states]
        return [{"key": "default", "label": page.get("title") or page["key"], "js": ""}]

    def selected_pages(self):
        if not self.args.pages:
            return list(PAGES)
        wanted = [p.strip() for p in self.args.pages.split(",") if p.strip()]
        known = {p["key"]: p for p in PAGES}
        out, missing = [], []
        for key in wanted:
            if key in known:
                out.append(known[key])
            else:
                missing.append(key)
        if missing:
            eprint("⚠ 未知页面键（已忽略）：%s" % ", ".join(missing))
            eprint("  可用：%s" % ", ".join(known.keys()))
        return out

    def combo_suffix(self) -> str:
        """多组合时给每个「效果 + 强调色」一套独立目录，避免互相覆盖。"""
        return "%s-%s" % (self.cur_fx, self.cur_accent) if self.multi_combo else ""

    def theme_rel(self, theme: str) -> str:
        """该主题在输出目录下的相对路径（单组合时就是主题名，与旧版一致）。"""
        suffix = self.combo_suffix()
        return "%s/%s" % (suffix, theme) if suffix else theme

    def theme_key(self, theme: str) -> str:
        suffix = self.combo_suffix()
        return "%s/%s" % (suffix, theme) if suffix else theme

    def page_url(self, page: dict, theme: str) -> str:
        params = {
            "dp": PAGE_TITLE.get(page["query"], "搜索"),
            "theme": theme,
            "fx": self.cur_fx,
            "accent": self.cur_accent,
            "lang": "简体中文",
        }
        params.update(page.get("settings") or {})
        return self.server.url + "?" + urllib.parse.urlencode(params)

    # ---------- 单个主题 ----------
    def run_theme(self, theme: str, pages):
        key = self.theme_key(theme)
        rel = self.theme_rel(theme)
        out_dir = os.path.join(self.args.out, *rel.split("/"))
        os.makedirs(out_dir, exist_ok=True)
        self.manifest["themes"][key] = {"dir": rel, "pages": [], "theme": theme,
                                        "fx": self.cur_fx, "accent": self.cur_accent}
        eprint("\n=== 主题：%s（%s）  效果：%s  强调色：%s ===" % (theme, "深色" if theme == "dark" else "浅色", self.cur_fx, self.cur_accent))
        for index, page in enumerate(pages, 1):
            attempt = 0
            while True:
                attempt += 1
                try:
                    stat = self.export_page(theme, page, index, len(pages))
                    break
                except Exception as exc:                   # 单页失败不拖垮整套
                    lost = is_connection_lost(exc)
                    if lost and attempt <= 2:
                        eprint("  ⚠ 浏览器连接中断（%s），重启 headless 后重试第 %d 次…"
                               % (exc, attempt))
                        self.restart_browser()
                        continue
                    eprint("  ✗ 页面 %s 失败：%s" % (page["key"], exc))
                    self.manifest["skipped"].append({
                        "theme": theme, "page": page["key"], "selector": "(整页)",
                        "reason": "页面导出失败：%s" % exc})
                    stat = None
                    break
            if stat:
                self.manifest["themes"][key]["pages"].append(stat)

    def restart_browser(self):
        """长任务里 Edge 偶发断开（渲染进程崩/内存），重启一次继续跑，别让整套白跑。"""
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        self.browser = Browser(self.edge, tuple(self.args.viewport), self.args.verbose,
                               keep_temp=self.args.keep_temp).start()

    def capture_screens(self, theme: str, page: dict):
        """导出该页面每个分页状态的整程序整图（screens/<theme>/<page>/<state>__full.png）
        ⚠️ 整图**不透明**（含页面背景），是给剪映当底板/对位用的；
           组件透明 PNG 仍在 <theme>/<page>/ 下。
        """
        browser = self.browser
        assert browser is not None
        states = self.page_states(page)
        if not states:
            return
        suffix = self.combo_suffix()
        out_dir = os.path.join(self.args.out, "screens",
                               *([suffix, theme] if suffix else [theme]),
                               sanitize_name(page["key"]))
        os.makedirs(out_dir, exist_ok=True)
        viewport = [int(self.args.viewport[0]), int(self.args.viewport[1])]
        for state in states:
            try:
                if state["js"]:
                    browser.eval(state["js"])
                    time.sleep(max(0.25, float(self.args.settle) * 0.6))
                clip = {"x": 0, "y": 0, "width": viewport[0], "height": viewport[1]}
                data = browser.screenshot(clip, 1, transparent=False)
                name = "%s__full.png" % sanitize_name(state["key"])
                path = os.path.join(out_dir, name)
                with open(path, "wb") as fh:
                    fh.write(data)
                meta = png_size_and_alpha(data, sample_alpha=False)
                self.manifest["screens"].append({
                    "page": page["key"], "page_title": page["title"], "theme": theme,
                    "state": state["key"], "label": state["label"],
                    "fx": self.cur_fx, "accent": self.cur_accent,
                    "file": os.path.relpath(path, self.args.out),
                    "px_size": {"w": meta["w"], "h": meta["h"]},
                    "timestamp": now_iso(),
                })
                eprint("    ▣ 整图 %-12s %s" % (state["key"], os.path.basename(path)))
            except Exception as exc:                     # noqa: BLE001
                self.manifest["skipped"].append({
                    "theme": theme, "page": page["key"],
                    "selector": "(整图:%s)" % state["key"],
                    "reason": "整图导出失败：%s" % exc})
                eprint("    ✗ 整图 %s 失败：%s" % (state["key"], exc))
        # 回到默认视图，避免影响组件抓取
        try:
            browser.eval("(function(){var b=document.querySelector('.page .seg-item');"
                         "if(b) b.click();})()")
        except Exception:
            pass

    def export_page(self, theme: str, page: dict, index: int, total: int) -> dict:
        browser = self.browser
        assert browser is not None
        label = "[%d/%d] %s · %s" % (index, total, theme, page["title"])
        browser.goto(self.page_url(page, theme))
        ok = browser.wait_js(
            "!!document.querySelector('.app-root') && !document.querySelector('.boot-screen')", 25)
        if not ok:
            raise PageError("前端没能挂载（.app-root 缺失或仍在启动画面）")
        time.sleep(float(self.args.settle))
        if not page.get("keep_dialogs"):
            for _ in range(4):
                if not browser.eval("document.querySelectorAll('.modal-backdrop').length"):
                    break
                browser.eval(JS_DISMISS)
                time.sleep(0.35)
        browser.eval(JS_HELPERS)
        browser.eval(JS_CLICK_HELPER)
        browser.eval(JS_ALPHA_EXTRACT)
        browser.eval(JS_SCROLL_TOP)
        for action in page.get("actions") or []:
            js = ACTION_JS.get(action)
            if not js:
                self.manifest["skipped"].append({
                    "theme": theme, "page": page["key"], "selector": "(action:%s)" % action,
                    "reason": "动作未定义"})
                continue
            try:
                browser.eval(js)
            except Exception as exc:
                eprint("    ⚠ 动作 %s 执行失败：%s" % (action, exc))
            time.sleep(0.7)
        # ---- 先导这个页面每个分页的"整程序整图"（1x，含页面背景）----
        self.capture_screens(theme, page)

        # 收集候选（组件仍在默认视图下抓；分页整图见 screens/）
        curated = []
        for item in page.get("selectors") or []:
            name, sel = item[0], item[1]
            limit = item[2] if len(item) > 2 else 1
            note = item[3] if len(item) > 3 else ""
            curated.append({"name": name, "sel": sel, "limit": limit, "note": note})
        collect_js = ("window.__gcpAsset.collect(%s)" % json.dumps({
            "curated": curated,
            "auto": None if self.args.no_auto else {"tokens": AUTO_TOKENS,
                                                     "limit": self.args.auto_limit},
            "maxTotal": self.args.max_per_page,
            "minW": 24, "minH": 12,
        }, ensure_ascii=False))
        found = browser.eval(collect_js)
        assets = found.get("assets", [])
        for skipped in found.get("skipped", []):
            self.manifest["skipped"].append({
                "theme": theme, "page": page["key"], "selector": skipped.get("name"),
                "reason": skipped.get("reason")})
        eprint("%s  发现 %d 个候选组件" % (label, len(assets)))

        page_dir = os.path.join(self.args.out, *self.theme_rel(theme).split("/"),
                                sanitize_name(page["key"]))
        os.makedirs(page_dir, exist_ok=True)
        page_assets = []
        for order, info in enumerate(assets):
            try:
                record = self.capture(theme, page, info, page_dir)
            except Exception as exc:
                eprint("    ✗ %s：%s" % (info["name"], exc))
                self.manifest["skipped"].append({
                    "theme": theme, "page": page["key"], "selector": info["name"],
                    "reason": "截图失败：%s" % exc})
                continue
            if record:
                page_assets.append(record)
                self.manifest["assets"].append(record)
                eprint("    ✓ %-28s %sx%s → %s" % (record["name"],
                       record["px_size"]["w"], record["px_size"]["h"],
                       os.path.basename(record["file"])))
        browser.eval("window.__gcpAsset && window.__gcpAsset.cleanup()")
        page_payload = {
            "page": page["key"], "title": page["title"], "theme": theme,
            "url": self.page_url(page, theme),
            "generated_at": now_iso(),
            "assets": page_assets,
        }
        with open(os.path.join(page_dir, "page.json"), "w", encoding="utf-8") as fh:
            json.dump(page_payload, fh, ensure_ascii=False, indent=1)
        return {"key": page["key"], "title": page["title"], "dir": page_dir,
                "assets": len(page_assets)}

    def capture(self, theme: str, page: dict, info: dict, page_dir: str):
        browser = self.browser
        assert browser is not None
        transparent = True
        prepared = {}
        for attempt in range(2):
            prepared = browser.eval("window.__gcpAsset.prepare(%s, %s)"
                                    % (json.dumps(info.get("locator") or {"id": info["id"]},
                                                  ensure_ascii=False),
                                       "true" if transparent else "false"))
            if not prepared.get("error"):
                break
            time.sleep(0.25)
        if prepared.get("error"):
            raise RuntimeError(prepared["error"])
        rect = prepared["rect"]
        pad = int(prepared.get("pad") or 2)
        scroll = prepared.get("scroll") or {"x": 0, "y": 0}
        doc = prepared.get("doc") or {"w": 0, "h": 0}
        note = info.get("note") or ""
        clips = prepared.get("clips") or info.get("clips") or []
        if info.get("position") in ("fixed", "sticky"):
            # 固定元素：滚动到顶后按视口坐标截（此时 scroll=0，视口=文档）
            clip_x = rect["x"] - pad
            clip_y = rect["y"] - pad
        else:
            clip_x = rect["x"] + scroll["x"] - pad
            clip_y = rect["y"] + scroll["y"] - pad
        width = rect["w"] + pad * 2
        height = rect["h"] + pad * 2
        clamped = False
        if clip_x < 0:
            width += clip_x
            clip_x = 0
            clamped = True
        if clip_y < 0:
            height += clip_y
            clip_y = 0
            clamped = True
        if doc["w"] and clip_x + width > doc["w"]:
            width = doc["w"] - clip_x
            clamped = True
        if doc["h"] and clip_y + height > doc["h"]:
            height = doc["h"] - clip_y
            clamped = True
        if width < 8 or height < 8:
            raise RuntimeError("可截取区域太小（被祖先容器裁切干净了）")
        if clamped:
            note = (note + " " if note else "") + "阴影/外发光部分被页面边界裁剪"
        if clips:
            cls = ", ".join(sorted({c["cls"] for c in clips if c.get("cls")}))[:70]
            note = (note + " " if note else "") + "部分阴影被祖先容器裁切（%s）" % cls
        backdrop = info.get("backdrop") or "none"
        needs_opaque = backdrop not in ("none", "")
        if needs_opaque:
            note = (note + " " if note else "") + (
                "该组件带 backdrop-filter（%s）：透明版会失去材质，另附 __opaque 版（含页面背景）"
                % backdrop)

        stem = "%s__%dx%d" % (sanitize_name(info["name"]), int(round(rect["w"])),
                              int(round(rect["h"])))
        filename = stem + ".png"
        path = os.path.join(page_dir, filename)
        clip = {"x": clip_x, "y": clip_y, "width": width, "height": height}
        self._last_clip = clip

        # ---- 双背景抠像（黑底 + 白底各截一张 → canvas 反预乘出真 alpha）----
        data = self.capture_alpha(clip)
        with open(path, "wb") as fh:
            fh.write(data)
        meta = png_size_and_alpha(data, sample_alpha=True)
        expected_w = int(round(width * self.args.scale))
        expected_h = int(round(height * self.args.scale))
        if abs(meta["w"] - expected_w) > 2 or abs(meta["h"] - expected_h) > 2:
            # 尺寸对不上说明捕获有问题：不假装成功
            os.remove(path)
            raise RuntimeError("PNG 尺寸异常：期望约 %dx%d，实际 %dx%d"
                               % (expected_w, expected_h, meta["w"], meta["h"]))
        if not meta["has_alpha"]:
            os.remove(path)
            raise RuntimeError("抠像结果没有 alpha 通道（应为 RGBA）")
        transparent_ok = (meta["alpha_ratio"] or 0) >= 0.002
        if not transparent_ok:
            note = (note + " " if note else "") + (
                "该区域四角基本不透明（组件自身铺满整块），叠放时按普通图片用即可")
        record = {
            "name": info["name"], "page": page["key"], "page_title": page["title"],
            "theme": theme, "selector": info["selector"],
            "fx": self.cur_fx, "accent": self.cur_accent,
            "bbox": {"x": round(rect["x"], 1), "y": round(rect["y"], 1),
                     "w": round(rect["w"], 1), "h": round(rect["h"], 1)},
            "doc_bbox": {"x": round(clip_x, 1), "y": round(clip_y, 1),
                         "w": round(width, 1), "h": round(height, 1)},
            "css_size": {"w": int(round(rect["w"])), "h": int(round(rect["h"]))},
            "px_size": {"w": meta["w"], "h": meta["h"]},
            "scale": self.args.scale, "file": os.path.relpath(path, self.args.out),
            "transparent": transparent_ok,
            "alpha_sample": {"corners": meta.get("corners"), "ratio": meta.get("alpha_ratio")},
            "backdrop_filter": backdrop, "timestamp": now_iso(), "note": note.strip(),
        }
        if needs_opaque:
            # backdrop-filter 组件：再给一张"页面原样（含背景材质）"的版本。
            # 注意也要隔离邻居，否则边缘会混进相邻卡片。
            ob = browser.eval("window.__gcpAsset.prepareOpaque(%s)"
                              % json.dumps(info.get("locator") or {"id": info["id"]},
                                           ensure_ascii=False))
            if ob.get("error"):
                note = (note + " " if note else "") + "__opaque 版生成失败：" + str(ob["error"])
            else:
                pad2 = int(ob.get("pad") or pad)
                sc = ob.get("scroll") or {"x": 0, "y": 0}
                orr = ob["rect"]
                if info.get("position") in ("fixed", "sticky"):
                    ox, oy = orr["x"] - pad2, orr["y"] - pad2
                else:
                    ox, oy = orr["x"] + sc["x"] - pad2, orr["y"] + sc["y"] - pad2
                ow, oh = orr["w"] + pad2 * 2, orr["h"] + pad2 * 2
                if ox < 0:
                    ow += ox; ox = 0
                if oy < 0:
                    oh += oy; oy = 0
                if doc["w"] and ox + ow > doc["w"]:
                    ow = doc["w"] - ox
                if doc["h"] and oy + oh > doc["h"]:
                    oh = doc["h"] - oy
                opaque_clip = {"x": ox, "y": oy, "width": max(8, ow), "height": max(8, oh)}
                opaque_name = stem + "__opaque.png"
                opaque_path = os.path.join(page_dir, opaque_name)
                opaque = browser.screenshot(opaque_clip, self.args.scale, transparent=False)
                with open(opaque_path, "wb") as fh:
                    fh.write(opaque)
                record["opaque_file"] = os.path.relpath(opaque_path, self.args.out)
                record["opaque_note"] = "含页面背景材质（backdrop-filter 需要底色才好看）"
            browser.eval("window.__gcpAsset.restore()")
        browser.eval(JS_ALPHA_PROBE_OFF)
        browser.eval("window.__gcpAsset.restore()")
        return record

    # ---------- 透明抠像 ----------
    def capture_alpha(self, clip: dict) -> bytes:
        """双背景截两张 + 页面内 canvas 反预乘，返回 RGBA PNG 字节。"""
        browser = self.browser
        assert browser is not None
        black = self.capture_on("#000000")
        white = self.capture_on("#ffffff")
        # ⚠️ 探针色只是临时用的：不摘掉的话，后面 __opaque 版会把整页刷成白色（实测踩过）
        browser.eval(JS_ALPHA_PROBE_OFF)
        black_url = "data:image/png;base64," + base64.b64encode(black).decode()
        white_url = "data:image/png;base64," + base64.b64encode(white).decode()
        result = browser.eval(
            "window.__gcpAlpha.extract(%s, %s)"
            % (json.dumps(black_url), json.dumps(white_url)), timeout=180)
        if not isinstance(result, str) or not result.startswith("data:image/png;base64,"):
            raise RuntimeError("页面内抠像失败（没有拿到 PNG dataURL）")
        return base64.b64decode(result.split(",", 1)[1])

    def capture_on(self, color: str) -> bytes:
        """把页面刷成纯色后截取同一块区域（用于反预乘）。"""
        browser = self.browser
        assert browser is not None
        rgb = color.lstrip("#")
        r, g, b = int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16)
        browser.ws.call("Emulation.setDefaultBackgroundColorOverride",
                        {"color": {"r": r, "g": g, "b": b, "a": 255}})
        browser.eval(JS_ALPHA_PROBE_ON.replace("__COLOR__", color))
        time.sleep(0.06)
        data = browser.screenshot(self._last_clip, self.args.scale, transparent=False)
        browser.ws.call("Emulation.setDefaultBackgroundColorOverride", {})
        return data

    # ---------- 收尾：manifest / csv / README ----------
    def finish(self, started: float):
        summary = {
            "screens": len(self.manifest.get("screens") or []),
            "themes": len(self.manifest["themes"]),
            "pages": sum(len(t["pages"]) for t in self.manifest["themes"].values()),
            "assets": len(self.manifest["assets"]),
            "skipped": len(self.manifest["skipped"]),
            "bytes": 0,
            "seconds": round(time.time() - started, 1),
        }
        for record in self.manifest["assets"]:
            path = os.path.join(self.args.out, record["file"])
            try:
                summary["bytes"] += os.path.getsize(path)
            except OSError:
                pass
        self.manifest["summary"] = summary
        os.makedirs(self.args.out, exist_ok=True)
        with open(os.path.join(self.args.out, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(self.manifest, fh, ensure_ascii=False, indent=1)
        self.write_csv()
        self.write_readme()
        # 控制台摘要
        print("")
        print("=" * 68)
        print(" %s v%s —— 导出完成" % (TOOL_NAME, TOOL_VERSION))
        print("=" * 68)
        print(" 输出目录 : %s" % os.path.abspath(self.args.out))
        print(" 主题     : %s" % ", ".join(self.args.themes))
        print(" 组合     : %d 套（效果 %s × 强调色 %s）"
              % (len(self.combos), "/".join(self.fx_list), "/".join(self.accent_list)))
        print(" 页面     : %d 个" % summary["pages"])
        print(" 素材     : %d 张（%s）" % (summary["assets"], human_size(summary["bytes"])))
        print(" 跳过     : %d 条（原因见 manifest.json 的 skipped 字段）" % summary["skipped"])
        print(" 耗时     : %.1f 秒" % summary["seconds"])
        print(" 清单     : manifest.json / assets.csv / README-使用说明.md")
        print("=" * 68)

    def write_csv(self):
        import csv
        path = os.path.join(self.args.out, "assets.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["theme", "page", "name", "css_w", "css_h", "px_w", "px_h",
                             "scale", "x", "y", "transparent", "backdrop_filter",
                             "file", "opaque_file", "note"])
            for r in self.manifest["assets"]:
                writer.writerow([r["theme"], r["page"], r["name"],
                                 r["css_size"]["w"], r["css_size"]["h"],
                                 r["px_size"]["w"], r["px_size"]["h"], r["scale"],
                                 r["bbox"]["x"], r["bbox"]["y"],
                                 "yes" if r["transparent"] else "no",
                                 r["backdrop_filter"], r["file"],
                                 r.get("opaque_file", ""), r["note"]])

    def write_readme(self):
        lines = [
            "# ToolsGCP UI 素材包（宣传片用）",
            "",
            "由 `ToolsGCP_UI_Asset_Exporter.py` 从程序**真实 DOM** 逐组件导出。",
            "",
            "- 生成时间：%s" % self.manifest["tool"]["generated_at"],
            "- 视口：%dx%d，倍率：1x 原生无损（PNG 像素 = CSS 像素）"
            % (self.manifest["config"]["viewport"][0], self.manifest["config"]["viewport"][1]),
            "- 主题效果：%s，强调色：%s"
            % (", ".join(self.fx_list), ", ".join(self.accent_list)),
            "",
            "## 目录结构",
            "",
            "```",
            "<输出目录>/",
            "  manifest.json         全局清单（每张图的名字/尺寸/坐标/主题/说明）",
            "  assets.csv            同一份清单的表格版（Excel 可直接打开）",
            "  dark/<页面key>/*.png  深色主题",
            "  screens/<主题>/<页面key>/<状态>__full.png  整程序整图（每个分页一张）",
            "  light/<页面key>/*.png 浅色主题（--themes both 时才有）",
            "  <效果>-<强调色>/…       指定 all 时才有的组合层"
            "（如 mica-blue/dark/…，screens 同理）",
            "  <页面key>/page.json   该页的清单",
            "```",
            "",
            "## 在剪映里用（分层动效排版）",
            "",
            "1. **同一屏的素材放在同一时间点**：所有图都是 1440×900 视口下按真实布局截的，",
            "   PNG 中心点 = 元素中心点。把图按 `bbox`（视口坐标 x/y）摆回去，就能 1:1 还原界面。",
            "2. 导入 1440×900 的黑色/透明画布 → 逐张拖入（1x 原生尺寸，不用缩放），"
            "用 `bbox.x/bbox.y` 设置位置",
            "   （剪映的位置是中心点：left = bbox.x + css_w/2，top = bbox.y + css_h/2）。",
            "3. `px_size` 是 PNG 实际像素，`css_size` 是界面里的逻辑尺寸；**两者相等（1x 无损）**。",
            "4. 分组动画：`page` 相同的一组属于同一屏（比如 search 页的卡片 + 按钮 + 标签），",
            "   可以对它们做同一组关键帧（整体上浮/缩放），因为坐标同源。",
            "5. 透明 PNG 可直接叠加发光/模糊特效；`transparent: false` 的图自带底色，",
            "   建议铺在最底层或直接覆盖画面。",
            "",
            "## 已知限制（不伪造成功，每个都在 manifest.skipped 里有说明）",
            "",
            "- **整页背景**（渐变 + 海报模糊）不是组件，导出会带底色，故不作为素材；",
            "  需要背景请用同目录 `chrome` 页的 `.titlebar` 等素材自行拼，或整屏截图另存。",
            "- **backdrop-filter（云母/玻璃/亚克力）**：单独抠图会失去材质。这类组件同时给了",
            "  `*__opaque.png`（含页面背景），叠加时优先用 opaque 版。",
            "- **远程图片 / 视频 / 轮播过渡帧**：素材来自网络与动画中间态，静态导出只有首帧或占位。",
            "- **iframe 插件配置页**：跨文档无法裁剪，需打开插件后整屏截。",
            "- **系统原生部分**（窗口圆角/边框、托盘菜单、原生右键菜单）由 Python 绘制，不是 DOM，",
            "  不在本工具范围；如需这部分请用录屏 + 蒙版。",
            "- 动画中间态没有导出（等页面静止后才量）；需要中间帧请录屏。",
            "",
            "## 复现命令",
            "",
            "```bat",
            "python ToolsGCP_UI_Asset_Exporter.py --yes --themes both --scale %s --out \"%s\""
            % (self.args.scale, os.path.abspath(self.args.out)),
            "```",
            "",
            "工具单文件、零第三方依赖，只读原程序文件，不修改程序与用户数据。",
        ]
        with open(os.path.join(self.args.out, "README-使用说明.md"), "w",
                  encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


# =============================================================================
# 七、交互式提问 + 命令行
# =============================================================================

def ask(prompt: str, default: str) -> str:
    try:
        value = input("%s [默认 %s]：" % (prompt, default)).strip()
    except EOFError:
        value = ""
    return value or default


FX_CHOICES = ["mica", "glass", "acrylic"]
ACCENT_CHOICES = ["blue", "purple", "orange"]
FX_LABEL = {"mica": "云母", "glass": "毛玻璃", "acrylic": "亚克力"}
ACCENT_LABEL = {"blue": "蓝", "purple": "紫", "orange": "橙"}


def expand_multi(value, choices):
    """把取值展开成列表：all / 全部 → 全部选项；逗号分隔也可以；非法值忽略。

    单选值时返回只含一个元素的列表 —— 这样输出目录结构与旧版完全一致。
    """
    items = [v.strip().lower() for v in str(value or "").replace("，", ",").split(",")
             if v.strip()]
    if not items or "all" in items or "全部" in items or "all".upper() in items:
        return list(choices)
    out = []
    for item in items:
        if item in choices and item not in out:
            out.append(item)
    return out or list(choices)


def interactive_config(args):
    print("=" * 68)
    print(" %s v%s" % (TOOL_NAME, TOOL_VERSION))
    print(" 从程序内部直接导出独立 UI 组件 PNG（透明背景 / 1x 原生无损）")
    print("=" * 68)
    args.out = ask("输出目录", args.out)
    theme = ask("主题（dark / light / both）", "both").lower()
    args.themes = ["dark", "light"] if theme == "both" else (
        ["light"] if theme == "light" else ["dark"])
    print(" ")
    print(" 主题效果（决定卡片/标题栏的材质与高光）：")
    print("   1) mica    云母（默认，几乎不糊）")
    print("   2) glass   毛玻璃（强模糊高透明）")
    print("   3) acrylic 亚克力（中模糊 + 高光边）")
    print("   4) all     全部（每种效果各导一套）")
    fx = ask("主题效果编号或名称", args.fx).lower()
    fx_map = {"1": "mica", "2": "glass", "3": "acrylic", "4": "all",
              "mica": "mica", "glass": "glass", "acrylic": "acrylic",
              "all": "all", "全部": "all"}
    args.fx = fx_map.get(fx, args.fx)
    print(" ")
    print(" 强调色：")
    print("   1) blue    蓝（默认）")
    print("   2) purple  紫")
    print("   3) orange  橙")
    print("   4) all     全部（每种强调色各导一套）")
    accent = ask("强调色编号或名称", args.accent).lower()
    accent_map = {"1": "blue", "2": "purple", "3": "orange", "4": "all",
                  "blue": "blue", "purple": "purple", "orange": "orange",
                  "all": "all", "全部": "all"}
    args.accent = accent_map.get(accent, args.accent)
    pages = ask("页面（all / 逗号分隔的页面 key，可用 --list 查看）", "all")
    args.pages = "" if pages.lower() == "all" else pages
    print("")
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ToolsGCP_UI_Asset_Exporter.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="从 ToolsGCP（web 版）真实 DOM 逐组件导出宣传片用素材（透明 PNG + 清单）。",
        epilog="""示例：
  python ToolsGCP_UI_Asset_Exporter.py
  python ToolsGCP_UI_Asset_Exporter.py --yes
  python ToolsGCP_UI_Asset_Exporter.py --yes --themes both --out "D:/宣传片素材"
  python ToolsGCP_UI_Asset_Exporter.py --list
  python ToolsGCP_UI_Asset_Exporter.py --yes --pages search,maker-form,settings --no-auto

输出：
  <输出目录>/manifest.json / assets.csv / README-使用说明.md
  <输出目录>/<主题>/<页面>/<组件>__<宽>x<高>.png
""")
    parser.add_argument("--out", default="", help="输出目录（默认 ./ToolsGCP-UI-Assets）")
    parser.add_argument("--themes", default="", help="dark / light / both（默认 both）")
    parser.add_argument("--scale", type=int, default=0,
                        help="已取消（保留参数兼容旧命令；固定 1x 原生无损）")
    parser.add_argument("--pages", default="", help="只导出指定页面，逗号分隔（默认全部）")
    parser.add_argument("--fx", default="mica", choices=FX_CHOICES + ["all"],
                        help="主题效果：mica / glass / acrylic / all（全部各导一套；默认 mica）")
    parser.add_argument("--accent", default="blue", choices=ACCENT_CHOICES + ["all"],
                        help="强调色：blue / purple / orange / all（全部各导一套；默认 blue）")
    parser.add_argument("--project", default="", help="ToolsGCP 项目根目录（默认自动向上查找）")
    parser.add_argument("--edge", default="", help="msedge.exe 路径（默认自动查找）")
    parser.add_argument("--yes", "-y", action="store_true", help="不提问，全部用默认值")
    parser.add_argument("--list", action="store_true", help="只打印页面/组件计划，不启动浏览器")
    parser.add_argument("--no-auto", action="store_true", help="关闭自动发现，只导出手工挑选的组件")
    parser.add_argument("--auto-limit", type=int, default=3, help="每类自动发现最多几个（默认 3）")
    parser.add_argument("--max-per-page", type=int, default=30, help="每页素材上限（默认 30）")
    parser.add_argument("--settle", type=float, default=0.6, help="页面稳定等待秒数（默认 0.6）")
    parser.add_argument("--viewport", default="%dx%d" % DEFAULT_VIEWPORT,
                        help="视口尺寸（默认 1440x900）")
    parser.add_argument("--keep-temp", action="store_true", help="保留 Edge 临时 profile（排错用）")
    parser.add_argument("--verbose", action="store_true", help="打印更多过程信息")
    parser.add_argument("--version", action="version",
                        version="%s %s" % (TOOL_NAME, TOOL_VERSION))
    return parser


def print_plan():
    print("可导出页面 / 组件计划（选择器来自对真实 DOM 的清点）：")
    curated_total = 0
    for page in PAGES:
        count = 0
        detail = []
        for item in page["selectors"]:
            limit = item[2] if len(item) > 2 else 1
            count += limit
            detail.append("%s×%s" % (item[0], limit))
        curated_total += count
        print("  %-14s %-26s 手工 %2d 张  %s" % (
            page["key"], page["title"], count,
            "  ".join(detail[:4]) + (" …" if len(detail) > 4 else "")))
    print("")
    print("合计：%d 个页面，手工挑选 %d 张；另有自动发现（%d 个组件类 × 每类默认 2 个），"
          "每页上限由 --max-per-page 控制（默认 18）。"
          % (len(PAGES), curated_total, len(AUTO_TOKENS)))


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.list:
        print_plan()
        return 0
    # 补齐交互默认值
    args.out = args.out or os.path.join(os.getcwd(), "ToolsGCP-UI-Assets")
    themes = (args.themes or "").lower()
    if not themes:
        themes = "both"
    if themes in ("both", "all"):
        args.themes = ["dark", "light"]
    elif themes == "light":
        args.themes = ["light"]
    elif themes == "dark":
        args.themes = ["dark"]
    else:
        eprint("⚠ --themes 只能是 dark / light / both，已按 both 处理")
        args.themes = ["dark", "light"]
    # 那个什么缩放去除吧直接要原本无损的就行→ 固定 1x（原生像素）。
    if args.scale and args.scale != 1:
        print("⚠ --scale 已取消：现在固定 1x 原生无损输出（本次忽略 --scale %s）" % args.scale)
    args.scale = 1
    args.fx_list = expand_multi(args.fx, FX_CHOICES)
    args.accent_list = expand_multi(args.accent, ACCENT_CHOICES)
    try:
        vw, vh = [int(x) for x in str(args.viewport).lower().split("x")]
    except Exception:
        eprint("⚠ --viewport 写法应为 1440x900，已用默认值")
        vw, vh = DEFAULT_VIEWPORT
    args.viewport = (max(800, vw), max(600, vh))

    root = find_project_root(args.project or os.path.dirname(os.path.abspath(__file__)))
    if not root:
        eprint("✗ 找不到 ToolsGCP 项目根目录（应包含 .ToolsGCP/webui/index.html）。")
        eprint("  请用 --project 指定，例如：--project \"D:\\ToolsGCP\"")
        return 3
    edge = args.edge or find_edge()
    if not edge or not os.path.isfile(edge):
        eprint("✗ 找不到 msedge.exe（Microsoft Edge）。请用 --edge 指定完整路径。")
        return 3

    if not args.yes:
        args = interactive_config(args)
    os.makedirs(args.out, exist_ok=True)

    eprint("")
    eprint("输出：%s" % os.path.abspath(args.out))
    eprint("主题：%s   倍率：%sx 原生无损   视口：%dx%d"
           % (", ".join(args.themes), args.scale, args.viewport[0], args.viewport[1]))
    eprint("效果：%s   强调色：%s   组合数：%d"
           % (", ".join(args.fx_list), ", ".join(args.accent_list),
              len(args.fx_list) * len(args.accent_list)))
    eprint("提示：全程 headless（无可见窗口），可以继续用电脑。")
    eprint("")

    exporter = Exporter(args, root, edge)
    try:
        return exporter.run()
    except KeyboardInterrupt:
        eprint("\n已中断（已清理 Edge 与临时目录）")
        return 130
    except Exception as exc:
        eprint("\n✗ 导出失败：%s" % exc)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
