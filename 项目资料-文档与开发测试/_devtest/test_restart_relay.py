# -*- coding: utf-8 -*-
"""重启接力 `_wait_for_restart_parent` 的离线单测（task-1 第 4 项"迁移后点重启没重启"）。

不弹窗、不起 GUI：只把 ToolsGCP.pyw 里那段函数抠出来，喂不同的 sys.argv 跑，
用**控制台子进程**（python -c sleep，无窗口）当"旧实例 PID"来验等待逻辑。

跑法：python "项目资料-文档与开发测试/_devtest/test_restart_relay.py"
"""
import io
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PYW = os.path.join(ROOT, "ToolsGCP.pyw")

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f"  <- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


# ---- 从 ToolsGCP.pyw 里抠出 _wait_for_restart_parent 的源码，单独 exec 出来测 ----
src = io.open(PYW, encoding="utf-8").read()
m = re.search(r"def _wait_for_restart_parent\(\):.*?\n(?=\n_wait_for_restart_parent\(\))",
              src, re.S)
check("ToolsGCP.pyw 里能找到 _wait_for_restart_parent", bool(m))
if not m:
    print("抠不到函数，退出")
    sys.exit(1)
func_src = m.group(0)

# 组装一个可执行沙箱：把函数里的 sys.argv 换成可控变量
sandbox_ns = {"os": os, "time": time}
exec("import sys\n" + func_src + "\n", sandbox_ns)
wait_fn = sandbox_ns["_wait_for_restart_parent"]


def run_with(argv_tail):
    real = sys.argv
    sys.argv = ["ToolsGCP.pyw"] + argv_tail
    try:
        t0 = time.monotonic()
        wait_fn()
        return time.monotonic() - t0
    finally:
        sys.argv = real


print("[1] 没有 --restart（普通启动）：立刻返回，不等待")
dt = run_with([])
check("无 --restart → 几乎 0 秒返回", dt < 0.2, f"{dt:.3f}s")

print("[2] --restart <已退出的 PID>：OpenProcess 拿不到 → 立刻放行")
dead = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.05)"])
dead.wait()
dt = run_with(["--restart", str(dead.pid)])
check("死 PID → 不傻等 10 秒", dt < 0.5, f"{dt:.3f}s")

print("[3] --restart <活着的子进程 PID>：应等它退出后才返回（证明会真的等）")
live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.2)"])
dt = run_with(["--restart", str(live.pid)])
live.wait()
check("活 PID → 等待时长接近子进程存活时间（≥0.9s，说明确实在等）",
      dt >= 0.9, f"{dt:.3f}s")
check("等待有上限保护（不会超过 ~10.5s）", dt <= 10.5, f"{dt:.3f}s")

print("[4] --restart 后面没有数字 / PID 非法：不抛、直接放行")
dt = run_with(["--restart"])
check("缺 PID → 放行不抛", dt < 0.2, f"{dt:.3f}s")
dt = run_with(["--restart", "abc"])
check("坏 PID → 放行不抛", dt < 0.2, f"{dt:.3f}s")
dt = run_with(["--restart", "0"])
check("PID=0 → 放行不抛", dt < 0.2, f"{dt:.3f}s")

print("[5] shell.restart() 确实会带上 --restart <pid>（静态接线检查）")
shell = io.open(os.path.join(ROOT, ".ToolsGCP", "desktop", "shell.py"),
                encoding="utf-8").read()
check("restart() 里拼了 --restart 和 os.getpid()",
      '"--restart"' in shell and "os.getpid()" in shell)

print()
if FAILS:
    print(f"FAILED {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("ALL OK")
