"""probe_back_top_live.py · task-25 取证：无头 Edge 真量搜索页/定制页「回顶按钮」的出现阈值与回顶动画时长。

回答两件事：
  1. 切换分段后**终态**滑块是否与选中项重合（用户报的「大小和形状不对」是终态错还是过渡态错）；
  2. 切换瞬间（60/120/300ms）滑块停在哪 —— 终态对而中间态离谱 = 「先写旧尺寸、等过渡自己追」那一类；
     终态也偏 = syncSegThumbs 的测量口径/时机问题。

Edge 侧脚本是同目录的 probe_back_top_live.js（一次一个页面：?page=search / ?page=customize），通过 serve.py 的 ?js= 注入、/audit 落盘
（与 _devtest/regression.py 同一套路，fx=keep 不冻结过渡，否则读不到中间态）。
⚠️ 本机 serve.py 偶尔并发丢一个大静态文件（vendor/vue 走 onerror 重试，比 app.js 晚到），
   页面就停在启动画面；Edge 侧改为「轮询到 app 就绪」，驱动层再整体重试 3 次，
   免得把环境抖动读成产品缺陷。
用法：python 项目资料-文档与开发测试/_devtest/probe_back_top_live.py [--port 8912] [--attempts 2] [--size 1440,900] [--only search]
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
JS_FILE = os.path.join(HERE, "probe_back_top_live.js")



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



def summarize(rep, bad):
    """打印一页的结果，返回新增失败数。"""
    for c in rep.get("checks", []):
        if c.get("pass"):
            print("PASS  %s  %s" % (c.get("name"), json.dumps(c.get("info"), ensure_ascii=False)[:130]))
        else:
            bad += 1
            print("FAIL  %s  %s" % (c.get("name"), json.dumps(c.get("info"), ensure_ascii=False)[:220]))
    for sk in rep.get("skips", []):
        print("SKIP  %s  %s" % (sk.get("name"), json.dumps(sk.get("info"), ensure_ascii=False)[:220]))
    if rep.get("geo"):
        print("  几何 -> %s" % json.dumps(rep["geo"], ensure_ascii=False)[:220])
    for k in ("LONG", "SHORT"):
        if isinstance(rep.get(k), dict):
            print("  %-5s -> %s" % (k, json.dumps(rep[k], ensure_ascii=False)[:220]))
    if rep.get("errors"):
        print("  Edge 侧错误：%s" % json.dumps(rep["errors"], ensure_ascii=False)[:300])
    return bad


def main():
    port = 8912
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    size = "1440,900"
    if "--size" in sys.argv:
        size = sys.argv[sys.argv.index("--size") + 1]
    attempts = 3
    if "--attempts" in sys.argv:
        attempts = int(sys.argv[sys.argv.index("--attempts") + 1])
    pages = ["search", "customize"]
    if "--only" in sys.argv:
        pages = [sys.argv[sys.argv.index("--only") + 1]]
    if not os.path.isfile(EDGE):
        print("SKIP: 找不到 Edge =", EDGE)
        return 0
    with open(JS_FILE, encoding="utf-8") as fh:
        probe_js = fh.read()
    proc = ensure_server(port)
    profile = os.path.join(os.environ.get("TEMP", "."), "gcp_bt_live")
    os.makedirs(profile, exist_ok=True)
    # Edge 侧固定 POST 到 ?page=bt_live，所以两页共用同一个落盘名；串行跑、每轮先删旧文件
    out = os.path.join(HERE, "audit_bt_live.json")
    errf = os.path.join(HERE, "audit_bt_live_err.json")
    bad = 0
    try:
        for pg in pages:
            url = "http://127.0.0.1:%d/?%s" % (port, urllib.parse.urlencode(
                {"page": pg, "fx": "keep", "auditfile": "bt_live", "js": probe_js}))
            rep = None
            for i in range(1, attempts + 1):
                rep, why = run_once(port, url, out, errf, profile, 75, size)
                if rep is None:
                    print("%s attempt %d: %s" % (pg, i, why))
                    continue
                # 没 ready 的报告（app 没挂载 = serve 偶发丢静态文件）不能当结论收下，
                # 否则「等不到 appReady」会被打印成一条产品缺陷，那是探针自己的环境问题。
                if rep.get("ready") or rep.get("skips"):
                    break
                print("%s attempt %d: 页面没就绪（checks=%d errors=%s）重试" % (
                    pg, i, len(rep.get("checks", [])), json.dumps(rep.get("errors", []), ensure_ascii=False)[:120]))
            if not rep or not (rep.get("checks") or rep.get("skips")):
                bad += 1
                print("FAIL  %s 页没跑出任一项检查（多为 Edge/serve 环境问题，不是产品结论）" % pg)
                continue
            print("== %s（ready=%s，检查 %d / 跳过 %d）" % (
                rep.get("label") or pg, rep.get("ready"), len(rep.get("checks", [])), len(rep.get("skips", []))))
            bad = summarize(rep, bad)
    finally:
        if proc:
            proc.kill()
    print("RESULT:", ("FAIL %d" % bad) if bad else "PASS")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
