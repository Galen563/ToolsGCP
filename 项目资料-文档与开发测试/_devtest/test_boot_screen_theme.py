# -*- coding: utf-8 -*-
"""启动加载画面"浅色主题仍是深色 / 叠加 / 不居中"——本轮根治点的回归测试。

⚠️ 关键认知（上一轮就是搞错了对象才"修过但没修好"）：
   用户原话说的是「**程序窗口中的**启动加载画面」，
   那是 webui 里的 `.boot-screen`（logo + ToolsGCP + 进度条 + bootText），
   **不是** desktop/splash.py 那个 180px 原生分层浮窗。
   splash.py 的底色计算上一轮已经改对（真机日志 `底色: 浅色 theme='浅色主题' light=True`），
   所以再怎么调 splash.py 用户都还是看到黑的。

三条真因与对应修复（本脚本逐条断言）：
  A. 首帧主题只能问 localStorage / 系统色：
     pywebview 默认 private_mode=True → WebView2 每次跑在全新临时 profile，
     `toolsgcp.theme` **每次启动必然为空**；退到 matchMedia 后，
     Windows 应用模式是深色（AppsUseLightTheme=0）→ 首帧必黑。
     → 修法：后端在 `/` 路由把真实 theme 烘进 HTML（<meta id="tg-boot-theme">），
       首帧脚本第 0 优先用它。桌面端与浏览器模式共用同一个 WSGI app ⇒ 一起生效。
  B. shell.py 建窗 background_color 写死 #1C1C1C → 页面合成前那层就是黑的。
     → 修法：按 _is_dark() 取 #F3F4F7 / #1C1C1C。
  C. _is_dark() 只认死字符串 "浅色主题"（和 splash 上一轮同一个 bug）
     → 写法稍偏（"浅色"/"Light Theme"/短形式/繁体）就掉到"读注册表"= 判成深色。
     → 修法：复用 splash._theme_is_light 那张兼容表。
  D. .boot-screen `absolute` 挂在 .content 里 → 居中于**内容盒**（被 48px 标题栏
     + 48px 导航挤成偏右下各 24px），且透明底压在已切好的搜索页骨架上 = "ui 叠加"。
     → 修法：改 `fixed;inset:0`（与窗口同心）+ 一层跟随主题的半透明底。

跑法：python "项目资料-文档与开发测试/_devtest/test_boot_screen_theme.py"
全程不起窗口、不写用户配置（配置用临时 DATA_DIR 注入）。
"""
import importlib
import io
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.request
from wsgiref.simple_server import make_server, WSGIRequestHandler

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(BASE, ".ToolsGCP"),
                os.path.join(BASE, ".ToolsGCP", "modules")]

FAILS = []


def check(name, cond, extra=""):
    print(("  OK    " if cond else "  FAIL  ") + name + (f"  <- {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


def read_repo(*parts):
    return io.open(os.path.join(BASE, *parts), encoding="utf-8").read()


# =========================================================================
print("[1] _boot_theme()：按用户配置判深浅（兼容各种 theme 写法）")
# 沙箱里系统 %TEMP% 不可写 → 固定名目录（AGENTS/项目踩坑记录）
TMP = os.path.join(BASE, "项目资料-文档与开发测试", "_tmp-ai-test", "boot-theme")
os.makedirs(TMP, exist_ok=True)

from desktop import webhost                                   # noqa: E402

CFG = os.path.join(TMP, "toolsgcp_config.json")


def theme_for(value):
    """把某个 theme 写法写进临时配置文件，让 _boot_theme 直接读它（依赖注入口子，
       不用改 module 属性 + reload —— reload 会把 WEBUI_DIR 一起重算，容易引出假失败）"""
    with io.open(CFG, "w", encoding="utf-8") as fh:
        json.dump({"theme": value, "accent_color": "purple"}, fh, ensure_ascii=False)
    return webhost._boot_theme(CFG)


# 配置文件根本不存在时不能抛
out = webhost._boot_theme(os.path.join(TMP, "no-such-file-here.json"))
check("配置文件缺失 → 不抛异常、回退深色", out["dark"] is True, str(out))

# =========================================================================
print("[2] 服务端把主题烘进 index.html（桌面端与浏览器模式共用同一条 / 路由）")
html_path = os.path.join(BASE, ".ToolsGCP", "webui", "index.html")
raw = io.open(html_path, encoding="utf-8").read()

for value, want_attr, note in [("浅色主题", "0", "规范简体"), ("深色主题", "1", "规范简体深色"),
                               ("浅色", "0", "短形式"), ("乱七八糟", "1", "认不出来→深色兜底")]:
    with io.open(CFG, "w", encoding="utf-8") as fh:
        json.dump({"theme": value}, fh, ensure_ascii=False)
    out = webhost._inject_boot_theme(raw, CFG).decode("utf-8")
    m = re.search(r'<meta id="tg-boot-theme"[^>]*>', out)
    check(f"theme={value!r}（{note}）→ HTML 里出现 data-dark=\"{want_attr}\" 的 meta",
          bool(m) and f'data-dark="{want_attr}"' in m.group(0),
          (m.group(0) if m else "NOT FOUND")[:120])
    check(f"  meta 落在 <head> 之后、首帧脚本之前（能被 getElementById 拿到）",
          bool(m) and out.find("<head>") < out.find(m.group(0))
          and out.find(m.group(0)) < out.find("getElementById('tg-boot-theme')"))
check("注入后仍是完整页面（挂载点/闭合标签都在）",
      'id="app"' in out and "</html>" in out and len(out) > len(raw))
check("原文件本身没有这个 meta（证明是服务端注入，不是前端写死）",
 'tg-boot-theme" data-dark' not in raw)

# 真起一次服务确认路由层也走这条逻辑（不 reload，用默认 DATA_DIR）
# ⚠️ pymodels.constants 的 CONFIG_DIR 是按**入口脚本所在目录**算的
#    （AGENTS.md 第 2/9 条：程序目录旁的 .ToolsGCP 是资源目录）。
#    本脚本在 _devtest/ 下，所以 webhost.WEBUI_DIR 会指到
#    `_devtest/.ToolsGCP/webui`（不存在）→ `/` 会回"前端入口还没生成"那页。
#    这不是产品 bug（真跑 `python ToolsGCP.pyw` 时入口在根目录，路径是对的），
#    是测试运行目录的产物，所以这里显式把 WEBUI_DIR 钉回真实目录再验路由。
webhost.WEBUI_DIR = os.path.join(BASE, ".ToolsGCP", "webui")
assert os.path.isfile(os.path.join(webhost.WEBUI_DIR, "index.html")), webhost.WEBUI_DIR
app = webhost.create_app()


class Quiet(WSGIRequestHandler):
    def log_message(self, *a):
        pass


httpd = make_server("127.0.0.1", 0, app, handler_class=Quiet)
port = httpd.server_address[1]
srv = threading.Thread(target=httpd.serve_forever, daemon=True)
srv.start()
time.sleep(0.5)
try:
    body = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read().decode("utf-8")
    check("`/` 路由返回的 HTML 带 boot-theme meta（证明走的是注入那条，不是 _send_file）",
          'id="tg-boot-theme"' in body, body[:90].replace("\n", " "))
    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5)
    check("`/` 仍然 no-store（改前端立刻生效那条不能退化）",
          "no-store" in (resp.headers.get("Cache-Control") or ""),
          resp.headers.get("Cache-Control"))
finally:
    httpd.shutdown()

# =========================================================================
print("[3] 首帧脚本：第 0 优先级是服务端 meta，且底色跟随主题")
head = read_repo(".ToolsGCP", "webui", "index.html")
seg = head[:head.find("<!-- 启动时不要框选第一个按钮")]
check("首帧脚本读 tg-boot-theme", "getElementById('tg-boot-theme')" in seg)
check("root.style.background 不再是写死一种颜色",
      re.search(r"root\.style\.background\s*=\s*dark\s*\?\s*'#1C1C1C'\s*:\s*'#F3F4F7'", seg)
      is not None)
check("localStorage 判定被降级为兜底（有 meta 时不再走）",
      "if (!document.getElementById('tg-boot-theme'))" in seg)
check("整段包在 try 里（拿不到 meta 也不白屏）", seg.count("try {") >= 2)

# =========================================================================
print("[4] shell.py：建窗底色跟随主题 + _is_dark 兼容各种写法")
shell = read_repo(".ToolsGCP", "desktop", "shell.py")
check("create_window 的 background_color 不再写死 #1C1C1C",
      'background_color="#1C1C1C",' not in shell)
check("background_color 按 _is_dark() 取色",
      'background_color=("#1C1C1C" if self._is_dark() else "#F3F4F7")' in shell)
check("_is_dark 复用 splash 的兼容表（不再只认死字符串）",
      "from .splash import _theme_is_light" in shell)
m = re.search(r"def _is_dark\(self\).*?\n    def ", shell, re.S)
check("_is_dark 仍然绝不抛异常（兜底深色）", m and "except Exception" in m.group(0))

# 真跑一遍 _is_dark 的判定（不建窗口，直接喂桩 settings）
from desktop.shell import AppShell                                   # noqa: E402


class StubSettings:
    def __init__(self, theme):
        self.settings = {"theme": theme}


for theme, want in [("浅色主题", False), ("浅色", False), ("Light Theme", False),
                    ("淺色主題", False), ("深色主题", True), ("深色", True)]:
    sh = AppShell.__new__(AppShell)
    sh.settings_manager = StubSettings(theme)
    check(f"_is_dark(theme={theme!r}) == {want}", sh._is_dark() is want, str(sh._is_dark()))

# =========================================================================
print("[5] .boot-screen 几何：fixed（与窗口同心）+ 一层跟随主题的底色")
ovl = read_repo(".ToolsGCP", "webui", "css", "overlays.css")
# ⚠️ 找**选择器**那一次出现（前面注释里也提到 .boot-screen，用 find 会命中注释）
m = re.search(r"^\.boot-screen\s*\{", ovl, re.M)
if not m:
    m = re.search(r"\.boot-screen\s*\{", ovl)
check("找到 .boot-screen 规则本体（不是注释里提的名字）", bool(m))
i = m.start() if m else ovl.find(".boot-screen")
block = ovl[i:ovl.find("\n}", i) + 2]
check("改成 position: fixed（不再被标题栏/导航挤偏 24px）",
      "position: fixed" in block, block[:70])
check("不再完全透明（防两层字叠字）",
      "background: transparent;" not in block)
check("底色跟随 --page 且不透明度足够压住底下页面",
      re.search(r"background:\s*color-mix\(in srgb,\s*var\(--page\)\s*(8[5-9]|9[0-9]|100)%",
                block) is not None, block[:200])
check("pointer-events 已交回（不再透明层穿下去点到底页）",
      "pointer-events: auto" in block or "pointer-events: none" not in block)

print("=" * 72)
if FAILS:
    print(f"FAILED {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("ALL OK")
