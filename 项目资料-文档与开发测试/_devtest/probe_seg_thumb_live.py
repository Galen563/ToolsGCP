"""probe_seg_thumb_live.py · task-20 取证：用无头 Edge 真量「多语言字段」分段滑块 .seg-thumb 的几何。

回答两件事：
  1. 切换分段后**终态**滑块是否与选中项重合（用户报的「大小和形状不对」是终态错还是过渡态错）；
  2. 切换瞬间（60/120/300ms）滑块停在哪 —— 终态对而中间态离谱 = 「先写旧尺寸、等过渡自己追」那一类；
     终态也偏 = syncSegThumbs 的测量口径/时机问题。

Edge 侧脚本是同目录的 probe_seg_thumb_live.js，通过 serve.py 的 ?js= 注入、/audit 落盘
（与 _devtest/regression.py 同一套路，fx=keep 不冻结过渡，否则读不到中间态）。
⚠️ 本机 serve.py 偶尔并发丢一个大静态文件（vendor/vue 走 onerror 重试，比 app.js 晚到），
   页面就停在启动画面；Edge 侧改为「轮询到 app 就绪」，驱动层再整体重试 3 次，
   免得把环境抖动读成产品缺陷。
用法：python 项目资料-文档与开发测试/_devtest/probe_seg_thumb_live.py [--port 8912] [--attempts 3]
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
JS_FILE = os.path.join(HERE, "probe_seg_thumb_live.js")

# 判定用：哪些 snap 属于「应该已经稳定」的终态
SETTLED = ("A_", "D_", "E_", "G_", "H_", "I_")
TOL = 1.5


def port_busy(p):
    s = socket.socket()
    try:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", p)) == 0
    finally:
        s.close()


def ensure_server(port):
    """已在跑就复用（重复起会抢端口）。"""
    if port_busy(port):
        return None
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, "serve.py"), str(port)],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/static/css/base.css" % port, timeout=1).read(64)
            return proc
        except Exception:
            time.sleep(0.25)
    proc.kill()
    raise RuntimeError("serve.py 起不来")


def run_once(port, url, out, errf, profile, wait_s, size="1440,900"):
    """开一次无头 Edge，等报告落盘。返回 (report|None, 说明)。"""
    for f in (out, errf):
        if os.path.isfile(f):
            try:
                os.remove(f)
            except OSError:
                pass
    devnull = open(os.devnull, "wb")
    cmd = [EDGE, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
           "--no-default-browser-check", "--user-data-dir=" + profile,
           "--window-size=" + size, "--hide-scrollbars", url]
    p = subprocess.Popen(cmd, stdout=devnull, stderr=devnull)
    waited = 0.0
    while waited < wait_s and not os.path.isfile(out):
        time.sleep(0.2)
        waited += 0.2
    time.sleep(0.4)
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                   stdout=devnull, stderr=devnull, timeout=20)
    devnull.close()
    if not os.path.isfile(out):
        tail = ""
        if os.path.isfile(errf):
            with open(errf, encoding="utf-8") as fh:
                tail = fh.read()[:600]
        return None, "没拿到报告（%.1fs）Edge 侧错误：%s" % (waited, tail or "无")
    with open(out, encoding="utf-8") as fh:
        return json.load(fh), "ok"


def main():
    port = 8912
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    size = "1440,900"
    if "--size" in sys.argv:
        # 用户机器上窗口比测试机窄时会走 layout.css 的 1128px 断点，
        # 单/双栏与滚动条口径都不同，必须能量尺寸才谈得上复现。
        size = sys.argv[sys.argv.index("--size") + 1]
    attempts = 3
    if "--attempts" in sys.argv:
        attempts = int(sys.argv[sys.argv.index("--attempts") + 1])
    if not os.path.isfile(EDGE):
        print("SKIP: 找不到 Edge =", EDGE)
        return 0
    # ⚠️ --js 的值在标志的**下一位**（原来写成 index("--js") 本身，把标志名当文件名打开）
    js_path = sys.argv[sys.argv.index("--js") + 1] if "--js" in sys.argv else JS_FILE
    with open(js_path, encoding="utf-8") as fh:
        probe_js = fh.read()
    proc = ensure_server(port)
    profile = os.path.join(os.environ.get("TEMP", "."), "gcp_seg_live")
    os.makedirs(profile, exist_ok=True)
    out = os.path.join(HERE, "audit_seg_live.json")
    errf = os.path.join(HERE, "audit_seg_live_err.json")
    url = "http://127.0.0.1:%d/?%s" % (port, urllib.parse.urlencode(
        {"page": "search", "fx": "keep", "auditfile": "seg_live", "js": probe_js}))
    rep = None
    try:
        for i in range(1, attempts + 1):
            rep, why = run_once(port, url, out, errf, profile, 70, size)
            if rep is None:
                print("attempt %d: %s" % (i, why))
                continue
            if not rep.get("ready"):
                print("attempt %d: 页面没就绪 boot=%s navMore=%s openedMaker=%s errors=%s"
                      % (i, rep.get("boot"), rep.get("navMore"), rep.get("openedMaker"), rep.get("errors")))
                continue
            print("attempt %d: 就绪（第 %d 次）" % (i, i))
            break
        else:
            print("FAIL: 重试 %d 次仍拿不到就绪报告（多为环境/并发加载问题，不是产品结论）" % attempts)
            return 1
    finally:
        if proc:
            proc.kill()
    print("boot=%s navMore=%s openedMaker=%s errors=%s" % (
        rep.get("boot"), rep.get("navMore"), rep.get("openedMaker"), rep.get("errors")))
    bad = 0
    for s in rep.get("steps", []):
        print("%-22s on=%-6s thumb=%s on=%s dx=%s dw=%s dh=%s itemW=%s docW=%s" % (
            s["tag"], s.get("onText"), s.get("thumb"), s.get("on"),
            s.get("dx"), s.get("dw"), s.get("dh"), s.get("itemWidths"), s.get("docW")))
        if s.get("thumb") is None or s.get("on") is None:
            print("   !! 缺滑块或选中项 segFound=%s thumbFound=%s" % (s.get("segFound"), s.get("thumbFound")))
            bad += 1
            continue
        if any(s["tag"].startswith(x) for x in SETTLED) and max(s["dx"], s["dw"], s["dh"]) > TOL:
            print("   !! 终态不重合 dx=%s dw=%s dh=%s inline=%s decl=%s segRect=%s" % (
                s["dx"], s["dw"], s["dh"], s.get("inline"), s.get("thumbDecl"), s.get("segRect")))
            bad += 1
    print("完整报告 ->", out)
    print("RESULT:", ("FAIL %d" % bad) if bad else "PASS")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
