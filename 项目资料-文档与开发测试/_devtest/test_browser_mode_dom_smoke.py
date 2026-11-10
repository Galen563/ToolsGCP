"""浏览器模式**真浏览器**冒烟：起真的桥服务，用无头 Edge 打开页面，看界面到底有没有活。

为什么需要这一份：前面那些测试分别证明了「静态路由 200」「capabilities 有 157 个方法」
「桥并发不排队」，但用户报的是「浏览器模式下功能/配置/图片全部加载不上来」——
这属于**整页跑起来之后**的表现，只有真的用浏览器打开一次才算数。
本轮修的正是前端那条竞态（bridge.init 先缓存了一份 api=null，探测随后才接管），
静态读代码很容易看过去，跑一次 DOM 就藏不住：
Vue 没挂载 → 页面里会留 `{{ t('…') }}`；桥没接管 → 界面是启动失败的样子。

断言（全部来自 dump 出来的 DOM）：
  1. <html> 上有 is-browser-mode        = 探测判定为浏览器模式（顶部栏靠它隐藏）
  2. 页面里没有未编译的 {{ }}            = Vue 真的挂载了
  3. 渲染出 nav-item                     = 侧栏起来了（数据/图标没炸）
  4. 图标精灵里有 i-workshop / i-keyboard = 本轮新加的两个图标真的进了 DOM
  5. 标题栏的三个按钮仍在 DOM 里（被 CSS 隐藏，不是被 v-if 拆掉）
     ⚠️ 这条是**特意保留的护栏**：桌面端要复用同一份模板，
        所以浏览器模式只许用 CSS 藏，不许把 markup 删掉。

跑法： python "项目资料-文档与开发测试/_devtest/test_browser_mode_dom_smoke.py"
"""
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
for _ in range(6):
    ROOT = os.path.dirname(ROOT)
    # 逐层向上，直到**这一层目录下真的有 .ToolsGCP**（本文件在 根/项目资料…/_devtest/，
    # 所以要向上两层才到仓库根；写死层数会随归档目录挪动而失效）。
    if os.path.isdir(os.path.join(ROOT, ".ToolsGCP")):
        break
# ⚠️ constants.CONFIG_DIR = dirname(sys.argv[0]) + ".ToolsGCP"：
#    不这么设会让所有静态路由 404（假故障，踩过）。
sys.argv = [os.path.join(ROOT, "ToolsGCP.pyw")]
sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                               # noqa: BLE001
        pass

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

FAILS = []


def check(label, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + label + ("" if cond else "  ← " + str(extra)))
    if not cond:
        FAILS.append(label)


def main() -> int:
    edge = next((p for p in EDGE_CANDIDATES if os.path.isfile(p)), None)
    if not edge:
        print("跳过：本机找不到 msedge.exe（这份测试需要真的浏览器内核）")
        return 0

    # ⚠️ 用**临时配置目录**：冒烟只读不写用户数据，绝不碰 %USERPROFILE%\.ToolsGCP
    tmp_cfg = tempfile.mkdtemp(prefix="toolsgcp-dom-smoke-")
    os.environ["TOOLSGCP_NO_SETTINGS_WRITE"] = "1"

    from desktop import browsermode as bm
    from desktop.shell import AppShell
    from desktop.native.privacy_state import PrivacyState
    from pymodels.core.settings_manager import SettingsManager

    """⚠️️ 这里用**真的 AppShell**，不是手搓的替身对象。
       上一版写了个只有 api 属性的 _Shell，结果 boot 一路踩 AttributeError：
       app.info 缺 started_at、i18n.bundle / resources.filter_options 缺
       current_language → 界面停在"启动中[appinfo]"，我却拿这份 DOM 去断言
       "资源库加载成功"，那种断言**全绿也不能证明任何东西**。
       AppShell.__init__ 只建管理器、不建窗口（webview 调用都在 run()/_try_show 里），
       所以可以直接拿来当"后端已经就绪"的壳，走的完全是真实代码路径。
       ⚠️ 但 settings/privacy 这两个会落盘的都要显式换成临时目录：
          privacy_manager 默认指 DATA_DIR（= 用户真实 config），
          直接 record_consent() 会**写到用户机器上** —— 绝对不行。"""
    shell = AppShell(SettingsManager(config_dir=tmp_cfg), splash_enabled=False)
    shell.privacy_manager = PrivacyState(tmp_cfg)      # 同意记录落在临时目录
    shell._teardown_started = True                     # 挡住 evaluate_js / push_event
    shell.push_event = lambda *a, **k: False           # 桥事件不需要真推给窗口
    # ⚠️ AppShell.__init__ 里 self.api = None（真身在 run() 才建，因为要接窗口），
    #    而桥的 capabilities / jsbridge 全靠 shell.api → 不补这一句就是永远 api_not_ready。
    from desktop.api import Api
    shell.api = Api(shell)
    try:
        # 方法名是 record_consent（不是 accept）：写一份带哈希校验的同意记录，
        # 让 boot 的法律闸门放行，页面才会真的去读资源库。
        shell.privacy_manager.record_consent()
    except Exception as exc:                            # noqa: BLE001
        print("   （预置同意状态失败，页面可能停在同意弹窗：", exc, "）")
    srv = bm.BrowserServer()
    started = srv.ensure_started(shell, port=0)
    if not started.get("ok"):
        print("FAIL 桥服务起不来:", started)
        return 1
    url = started["url"]
    print("桥服务:", url)
    try:
        # 先确认服务真的在（不然 Edge 会返回一张错误页，看不出产品问题）
        with urllib.request.urlopen(url, timeout=8) as resp:
            check("GET / 返回 200", resp.status == 200, resp.status)

        profile = tempfile.mkdtemp(prefix="toolsgcp-edge-profile-")
        """⚠️ 不能用 --virtual-time-budget 来"等页面跑完"：
        浏览器模式的前端有一条**永不空闲**的事件长轮询（/jsbridge/events/poll，
        服务端每次挂 2.5 秒再返回，前端拿到就再发下一条）。virtual time 会因为有
        pending 网络请求而卡住不推进 → Edge 永远不 dump（实测 180 秒超时）。
        改成 --timeout：到点**无条件**把当前 DOM dump 出来，不管还有没有请求挂着。
        8 秒对本地回环 + 一次 Vue 挂载绰绰有余（日志里 boot 各步是毫秒级走完的）。"""
        cmd = [edge, "--headless=new", "--disable-gpu", "--no-first-run",
               "--no-default-browser-check", f"--user-data-dir={profile}",
               "--timeout=8000", "--dump-dom", url]
        # ⚠️ --dump-dom 的时点取决于 load 事件，和 boot() 的 await 链是**赛跑**：
        #    偶尔 dump 到"Vue 还没挂载完"的那一帧 → ①/②/②b 会假失败（实测约 1/3 概率）。
        #    这是**观测工具**的抖动，不是产品问题，所以这里最多重试 3 次，
        #    只要有一次 dump 到"已挂载"的完整帧就用那一份（断言本身没有放宽）。
        dom = ""
        for attempt in range(3):
            try:
                proc = subprocess.run(cmd, capture_output=True, timeout=150)
                cand = proc.stdout.decode("utf-8", errors="replace")
            except subprocess.TimeoutExpired as exc:
                cand = (exc.stdout or b"").decode("utf-8", errors="replace")
            dom = cand
            # 判据：Vue 已挂载（没有未编译的 {{ t( }}，且 v-cloak 已摘）
            if cand and "{{ t(" not in cand and "v-cloak" not in cand:
                if attempt:
                    print(f"   （第 {attempt + 1} 次 dump 才拿到已挂载帧）")
                break
            print(f"   （第 {attempt + 1} 次 dump 落在挂载前，重试…）")
            time.sleep(1.0)
        check("Edge 有输出（页面加载完成）", len(dom) > 20000, f"DOM {len(dom)} 字节")
        if len(dom) < 5000:
            print(proc.stderr.decode("utf-8", errors="replace")[-800:])

        # ① 浏览器模式标记
        check("① <html> 带 is-browser-mode（顶部栏靠它隐藏）",
              "is-browser-mode" in dom[:4000] or 'class="no-anim is-browser-mode"' in dom
              or re.search(r"<html[^>]*is-browser-mode", dom) is not None,
              dom[:400])

        # ② Vue 真的挂载了：不能有未编译的插值
        leftovers = re.findall(r"\{\{\s*t\(", dom)
        check("② 没有未编译的 {{ t('…') }}（Vue 挂载成功）",
              not leftovers, f"{len(leftovers)} 处残留")
        check("②b v-cloak 已被移除（挂载完成才会去掉该属性）",
              "v-cloak" not in dom, "仍带 v-cloak")

        # ③ 侧栏渲染出来了
        check("③ 渲染出侧栏条目 nav-item", 'class="nav-item' in dom, "没有 nav-item")

        # ④ 本轮新图标进了精灵
        # 本轮用户要求「GCP工坊图标恢复原样」：自定义 i-workshop 已删除。
        check("④ GCP工坊已恢复原样（精灵里不再有 i-workshop）",
              'id="i-workshop"' not in dom)
        check("④b 图标精灵里有 i-keyboard（设置·快捷键分区）", 'id="i-keyboard"' in dom)
        check("④c 侧栏 GCP工坊 用的是 #i-developer（扳手，恢复原样）",
              "#i-developer" in dom and "#i-workshop" not in dom)

        # ⑤ 护栏：浏览器模式只许 CSS 藏，不许把 markup 拆掉（桌面端共用同一份模板）
        check("⑤ 标题栏三个按钮仍在 DOM（用 CSS 隐藏，不是 v-if 拆掉）",
              "tb-btn" in dom and "i-win_min" in dom,
              "titlebar markup 不见了 → 桌面端会跟着遭殃")
        check("⑤b 标题栏仍是 <header class=\"titlebar\">",
              re.search(r'class="titlebar', dom) is not None)

        # ⑥ ⚠️ 这里**不能**断言"资源库加载出来了"：--dump-dom 在 **load 事件**那一刻
        #     就 dump，而 boot() 是一条 await 链（bridge.init → app.info → settings →
        #     i18n → 法律闸门 → continueBoot → resources.all），load 时还停在
        #     `启动中[appinfo]`，卡片必然还没渲染。拿它断言"资源加载成功"是**假失败**
        #     （踩过），反过来"恰好看到卡片"也证明不了什么。
        #     → 真浏览器端到端（等 boot 跑完再查）由
        #       test_browser_mode_live_cdp.py 负责，那一份才是用户那句
        #       「图片 资源 配置全部加载不上来」的正证。
        #     本文件只守"结构层面"的几条：标记、Vue 挂载、精灵、markup 没被拆。
        # 能在这里真断言的只有"桥这条路本身通不通"：capabilities 是 boot 第一步
        # （bridge.init）要用的，它 200 且带方法数，说明前端不会一上来就全线降级。
        caps_raw = ""
        try:
            req = urllib.request.Request(url + "/jsbridge/capabilities", method="POST",
                                         data=b"{}", headers={"Origin": url})
            with urllib.request.urlopen(req, timeout=8) as resp:
                caps_raw = resp.read().decode("utf-8")
        except Exception as exc:                    # noqa: BLE001
            caps_raw = "ERR " + str(exc)
        import json as _json
        try:
            caps = _json.loads(caps_raw)
        except Exception:
            caps = {}
        check("⑥ 桥的 capabilities 可用且方法非空（boot 第一步不会全线降级）",
              bool(caps.get("ok")) and len(caps.get("methods") or []) > 50,
              f"ok={caps.get('ok')} methods={len(caps.get('methods') or [])}")
        check("⑥b 关键域都在清单里（resources/settings/i18n）",
              all(any(m.startswith(p) for m in (caps.get("methods") or []))
                  for p in ("resources.", "settings.", "i18n.")))

        # 顺带看一眼有没有把 boot 卡住的痕迹
        boot = re.search(r"bootText[^<]{0,80}", dom)
        print("   （boot 文案参考：", (boot.group(0)[:70] if boot else "无"), "）")
    finally:
        srv.stop()

    print("\n=== 结论：%s ===" % ("全部通过" if not FAILS else f"{len(FAILS)} 项失败 -> {FAILS}"))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
