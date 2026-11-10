"""浏览器模式**端到端**验收：起真桥服务 + 真 Edge（CDP），等 boot 跑完再断言。

为什么不用 --dump-dom：那个 flag 在 **load 事件**那一刻就 dump，
而本项目的 boot() 是一条 await 链（bridge.init → app.info → settings → i18n →
法律闸门 → continueBoot → resources.all），load 时还停在 `启动中[appinfo]`。
拿那份 DOM 断言"资源加载成功"必然是假失败（踩过一次），
反过来"刚好看到卡片"也不能证明什么。
→ 用 CDP 连上活页面，**轮询等到 boot 链走完**再查，才是用户那句
  「浏览器模式下功能和配置文件之类的全部不生效，图片 资源 配置全部加载不上来」
  的真正反证。

依赖：仓库外面那份 CDP 小工具（C:/tmp/cdp.js + ws 模块）。找不到就跳过并说明原因，
     不把它当失败（本机没装就没法跑真浏览器，不是产品问题）。

跑法： python "项目资料-文档与开发测试/_devtest/test_browser_mode_live_cdp.py"
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
for _ in range(6):
    ROOT = os.path.dirname(ROOT)
    if os.path.isdir(os.path.join(ROOT, ".ToolsGCP")):
        break
sys.argv = [os.path.join(ROOT, "ToolsGCP.pyw")]
sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                               # noqa: BLE001
        pass

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
CDP_JS = r"C:\tmp\cdp.js"
WS_MODULES = r"C:\tmp\node_modules"

FAILS = []


def check(label, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + label + ("" if cond else "  ← " + str(extra)))
    if not cond:
        FAILS.append(label)


def cdp(port, mode, arg=None):
    cmd = ["node", CDP_JS, str(port), mode] + ([arg] if arg is not None else [])
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=60, cwd=os.path.dirname(WS_MODULES))
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    return (p.stdout or b"").decode("utf-8", "replace")


"""⚠️ 表达式必须**直接返回对象**，不要自己 JSON.stringify 一遍：
   cdp.js 走的是 Runtime.evaluate + returnByValue，它拿到 value 之后**自己**会
   JSON.stringify(value, null, 2) 打印。返回字符串 → 打印出来是一整段带 \" 转义的
   字符串字面量，再 json.loads 必然失败（第一版就栽在这里，白判了一次"CDP 没返回"）。"""
EVAL_BOOT_DONE = r"""(() => {
  const app = document.querySelector('#app');
  const txt = app && app.innerText ? app.innerText : '';
  return {
    browserMode: document.documentElement.classList.contains('is-browser-mode'),
    bootText: (txt.match(/启动中\[[^\]]*\]/) || [''])[0],
    failed: (txt.match(/启动失败[^|]{0,120}/) || [''])[0],
    cards: document.querySelectorAll('.card').length,
    iconImgs: [...document.querySelectorAll('.card img')].map(i => i.getAttribute('src')).slice(0,3),
    brokenImgs: [...document.querySelectorAll('img')].filter(i => i.complete && i.naturalWidth === 0)
                  .map(i => i.getAttribute('src')).slice(0,5),
    navItems: [...document.querySelectorAll('.nav-item')].length,
    titlebarHidden: (() => { const t = document.querySelector('.titlebar');
        return t ? getComputedStyle(t).display === 'none' : 'no-titlebar'; })(),
    titlebarInDom: !!document.querySelector('.titlebar'),
    winResizeHidden: (() => { const w = document.querySelector('.win-resize');
        return w ? getComputedStyle(w).display === 'none' : 'absent'; })(),
    workshopIcon: !!document.querySelector('#i-workshop'),
    /* 本轮：GCP工坊图标已按要求恢复原样（用 developer 扳手），
       所以 i-workshop 应当**不存在**、而侧栏那个条目引用 #i-developer。 */
    workshopUsesDeveloper: (() => {
      const b = [...document.querySelectorAll('.nav-item')]
        .find(n => (n.getAttribute('title') || '') === 'GCP工坊');
      if (!b) return 'no-item';
      const u = b.querySelector('use');
      return u ? (u.getAttribute('href') || u.getAttribute('xlink:href') || '') : 'no-use';
    })(),
    keyboardIcon: !!document.querySelector('#i-keyboard'),
    searchBox: !!document.querySelector('.search-box input'),
  };
})()"""


def main() -> int:
    edge = next((p for p in EDGE_CANDIDATES if os.path.isfile(p)), None)
    if not edge or not os.path.isfile(CDP_JS) or not os.path.isdir(WS_MODULES):
        print("跳过：本机缺 msedge.exe 或 CDP 工具（C:/tmp/cdp.js + ws），"
              "这条端到端验收需要真浏览器内核。")
        return 0

    tmp = tempfile.mkdtemp(prefix="tgcp-live-")
    os.environ["TOOLSGCP_NO_SETTINGS_WRITE"] = "1"

    from desktop import browsermode as bm
    from desktop.api import Api
    from desktop.shell import AppShell
    from desktop.native.privacy_state import PrivacyState
    from pymodels.core.settings_manager import SettingsManager

    """用**真的 AppShell**（不是手搓替身）：AppShell.__init__ 只建管理器、不建窗口，
       所以可以安全拿来当"后端已就绪"的壳，前端调到的全是真实代码路径。
       ⚠️ settings / privacy 都指到临时目录：privacy_manager 默认写用户真实 config，
          直接 record_consent() 会改到用户机器上的同意记录 —— 绝对不行。"""
    shell = AppShell(SettingsManager(config_dir=tmp), splash_enabled=False)
    shell.privacy_manager = PrivacyState(tmp)
    shell.push_event = lambda *a, **k: False
    shell._teardown_started = True
    shell.api = Api(shell)
    shell.privacy_manager.record_consent()

    srv = bm.BrowserServer()
    started = srv.ensure_started(shell, port=0)
    if not started.get("ok"):
        print("FAIL 桥服务起不来:", started)
        return 1
    url = started["url"]
    port = 9333
    profile = tempfile.mkdtemp(prefix="tgcp-live-prof-")
    proc = None
    try:
        print("桥服务:", url)
        proc = subprocess.Popen(
            [edge, "--headless=new", "--disable-gpu", "--no-first-run",
             "--no-default-browser-check", f"--user-data-dir={profile}",
             f"--remote-debugging-port={port}", url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 等 CDP 起来
        for _ in range(40):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
                    targets = json.loads(r.read().decode("utf-8"))
                if any(t.get("type") == "page" for t in targets):
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            check("Edge 的 CDP 端口可用", False, "9333 一直没起来")
            return 1

        # 轮询等 boot 链跑完（最多 40 秒）：判据 = 不再出现"启动中[…]"
        data = None
        deadline = time.time() + 40
        while time.time() < deadline:
            raw = cdp(port, "eval", EVAL_BOOT_DONE)
            m = re.search(r"\{[\s\S]*\}", raw)
            if m:
                try:
                    data = json.loads(m.group(0))
                except Exception:
                    pass
            if data and not data.get("bootText") and not data.get("failed"):
                break
            time.sleep(1.0)

        if not data:
            check("拿到 CDP 的页面状态", False, "eval 没有返回 JSON")
            return 1
        print("   最终状态:", json.dumps(data, ensure_ascii=False)[:400])

        check("boot 链跑完（没有停在 启动中[…]）", not data.get("bootText"),
              data.get("bootText"))
        check("boot 没有抛异常（无「启动失败」）", not data.get("failed"), data.get("failed"))
        check("★ 资源库真的加载出来了（渲染出卡片）", data.get("cards", 0) > 0,
              f"卡片数={data.get('cards')}")
        check("★ 卡片图标 URL 走 /res/image/icon/",
              any("/res/image/icon/" in s for s in data.get("iconImgs", [])),
              data.get("iconImgs"))
        check("★ 没有加载失败的图片（broken img = 0）",
              not data.get("brokenImgs"), data.get("brokenImgs"))
        check("侧栏渲染出来（nav-item ≥ 6）", data.get("navItems", 0) >= 6,
              data.get("navItems"))
        check("浏览器模式标记在 <html> 上", data.get("browserMode") is True)
        check("★ 顶部栏被**计算样式**隐藏（display:none，不是被拆掉）",
              data.get("titlebarHidden") is True and data.get("titlebarInDom") is True,
              f"hidden={data.get('titlebarHidden')} inDom={data.get('titlebarInDom')}")
        check("窗口缩放热区在浏览器模式不显示",
              data.get("winResizeHidden") in (True, "absent"), data.get("winResizeHidden"))
        # 本轮用户要求「GCP工坊图标恢复原样」：自定义 i-workshop 已删除，
        # 侧栏该条目改回引用 developer（扳手）。keyboard 图标保留。
        check("★ GCP工坊已恢复原样（i-workshop 不存在、引用 #i-developer）",
              data.get("workshopIcon") is False
                and str(data.get("workshopUsesDeveloper", "")).endswith("#i-developer"),
              f"workshopIcon={data.get('workshopIcon')} uses={data.get('workshopUsesDeveloper')}")
        check("快捷键分区用的 keyboard 图标仍在精灵里",
              data.get("keyboardIcon") is True)
        check("搜索框可用（界面不是空白/错误页）", data.get("searchBox") is True)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        srv.stop()
        shutil.rmtree(profile, ignore_errors=True)

    print("\n=== 结论：%s ===" % ("全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}"))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
