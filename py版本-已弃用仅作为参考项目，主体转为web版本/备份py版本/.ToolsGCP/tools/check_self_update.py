r"""自更新机制自检（%TEMP% 临时更新器方案） —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/check_self_update.py

盯这几件事：
  1. 路径与参数：GetTempPath、%TEMP%\ToolsGCP_new.exe、%TEMP%\ToolsGCP.bak、
     `--update --pid --target` 的形状；
  2. 能不能换（replacement_blockers）；
  3. **进程句柄**等待旧 PID 退出（真起一个子进程）；
  4. 更新器干跑：备份 → 覆盖 → 启动新版（工作目录=程序目录）→ 返回 0；
  5. 失败**回滚**，且程序目录里**始终只有 ToolsGCP.exe**（没有 .cmd/.new/.bak 残留）；
  6. 提权路径（复制失败 → 请求管理员权限重来）；
  7. 启动后清理（含"临时文件还被占着"时后台重试）；
  8. 主程序入口把 --update 放在单实例检测**之前**。

⚠️ 全程在 tools/_out 下的沙箱里对假 exe 做，绝不碰真正的程序目录和 %TEMP% 里的真文件。
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"
OUT_DIR = TOOLS_DIR / "_out"

os.environ.setdefault("TOOLSGCP_NO_SETTINGS_WRITE", "1")
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")
sys.path.insert(0, str(PKG_DIR))

FAILURES = []


def check(label, condition, detail=""):
    mark = "PASS" if condition else "FAIL"
    if not condition:
        FAILURES.append(f"{label} {detail}".strip())
    print(f"[{mark}] {label}" + (f"  {detail}" if detail and not condition else ""))
    return bool(condition)


def _sandbox(name: str) -> Path:
    path = OUT_DIR / "_check_self_update" / name
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


# ==========================================================================
# 一、路径与参数
# ==========================================================================

def check_paths_and_args():
    from pymodels.core import self_update as su

    tmp = su.temp_dir()
    check("temp_dir() 拿到的是一个真实存在的目录", os.path.isdir(tmp), tmp)
    if sys.platform == "win32":
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        ctypes.windll.kernel32.GetTempPathW(32768, buf)
        check("Windows 下就是 GetTempPathW 的返回值（需求指定）",
              os.path.normcase(os.path.abspath(tmp)).rstrip("\\")
              == os.path.normcase(os.path.abspath(buf.value)).rstrip("\\"),
              f"{tmp!r} vs {buf.value!r}")

    check("临时新版叫 ToolsGCP_new.exe 且在 %TEMP% 下",
          os.path.basename(su.staging_exe_path()) == "ToolsGCP_new.exe"
          and os.path.dirname(os.path.abspath(su.staging_exe_path()))
          == os.path.abspath(tmp),
          su.staging_exe_path())
    check("备份叫 ToolsGCP.bak 且在 %TEMP% 下（程序目录不留 .bak）",
          os.path.basename(su.backup_exe_path()) == "ToolsGCP.bak"
          and os.path.dirname(os.path.abspath(su.backup_exe_path()))
          == os.path.abspath(tmp),
          su.backup_exe_path())

    args = su.build_updater_args(su.staging_exe_path(), r"C:\app\ToolsGCP.exe", 4321)
    check("启动参数形状 = <新版> --update --pid <PID> --target <原路径>",
          args[0] == su.staging_exe_path()
          and args[1:3] == ["--update", "--pid"] and args[3] == "4321"
          and args[4] == "--target" and args[5] == r"C:\app\ToolsGCP.exe",
          f"{args}")

    parsed = su.parse_update_args(["x.exe", "--update", "--pid", "99",
                                   "--target", r"C:\a\b.exe",
                                   "--cleanup", r"C:\t\ToolsGCP_new.exe"])
    check("参数解析：pid / target / cleanup 都对",
          parsed["pid"] == 99 and parsed["target"] == r"C:\a\b.exe"
          and parsed["cleanup"] == r"C:\t\ToolsGCP_new.exe", f"{parsed}")
    check("is_update_mode 认得 --update",
          su.is_update_mode(["x", "--update"])
          and not su.is_update_mode(["x", "--cleanup", "p"]))


# ==========================================================================
# 二、能不能换
# ==========================================================================

def check_blockers():
    from pymodels.core import self_update as su

    real = su.replacement_blockers()
    check("开发目录（源码运行 + 没有 exe）报 SOURCE_RUN + NO_EXE",
          su.BLOCK_SOURCE_RUN in real and su.BLOCK_NO_EXE in real, f"{real}")

    sandbox = _sandbox("blockers")
    target = sandbox / "ToolsGCP.exe"
    target.write_text("OLD", encoding="utf-8")

    original = su.current_executable
    try:
        su.current_executable = lambda: str(target)
        check("目录里有 ToolsGCP.exe → 没有任何阻塞",
              su.replacement_blockers(directory=str(sandbox)) == [],
              f"{su.replacement_blockers(directory=str(sandbox))}")

        su.current_executable = lambda: ""
        check("源码运行但目录里有 exe → 也不拦（要能换掉它）",
              su.replacement_blockers(directory=str(sandbox)) == [])

        plain = _sandbox("blockers_renamed")
        (plain / "我的程序.exe").write_text("OLD", encoding="utf-8")
        su.current_executable = lambda: str(plain / "我的程序.exe")
        check("目录里没有 ToolsGCP.exe 且跑的文件名带非 ASCII → RENAMED",
              su.BLOCK_RENAMED in su.replacement_blockers(directory=str(plain)),
              f"{su.replacement_blockers(directory=str(plain))}")
    finally:
        su.current_executable = original


# ==========================================================================
# 三、进程句柄等待
# ==========================================================================

def check_wait_handle():
    from pymodels.core import self_update as su

    if sys.platform != "win32":
        print("[SKIP] 非 Windows，跳过进程句柄等待")
        return

    check("不存在的 PID → 直接算「已退出」", su.wait_for_process_exit(999999, 500))

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.2)"])
    try:
        started = time.perf_counter()
        ok = su.wait_for_process_exit(child.pid, 8000)
        elapsed = time.perf_counter() - started
        check("进程句柄等待：子进程退出后立刻返回 True", ok, f"{ok}")
        check("等待时间接近子进程真实存活时间（不是死等超时）",
              0.8 <= elapsed <= 3.0, f"{elapsed:.2f}s")
    finally:
        try:
            child.kill()
        except Exception:
            pass

    child2 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])
    try:
        started = time.perf_counter()
        ok2 = su.wait_for_process_exit(child2.pid, 600)
        elapsed2 = time.perf_counter() - started
        check("超时时间到了还没退出 → 返回 False（不能无限等）",
              (not ok2) and elapsed2 < 2.5, f"{ok2} {elapsed2:.2f}s")
    finally:
        try:
            child2.kill()
        except Exception:
            pass


# ==========================================================================
# 四 / 五 / 六、更新器主流程（沙箱干跑）
# ==========================================================================

def _run_updater(sandbox: Path, *, fail_copy=False, elevate=False,
                 launch_ok=True):
    """在沙箱里跑一遍 run_update_mode，返回 (code, 记录下来的 Popen 调用, 目标, 临时文件)"""
    from pymodels.core import self_update as su

    staging = sandbox / "ToolsGCP_new.exe"
    target = sandbox / "app" / "ToolsGCP.exe"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("OLD", encoding="utf-8")
    staging.write_text("NEW", encoding="utf-8")

    calls = []
    originals = {
        "temp_dir": su.temp_dir,
        "Popen": su.subprocess.Popen,
        "_copy_with_retry": su._copy_with_retry,
        "relaunch_elevated": su.relaunch_elevated,
        "current_executable": su.current_executable,
    }

    class FakePopen:
        def __init__(self, args, **kwargs):
            if not launch_ok:
                raise OSError("模拟启动失败")
            calls.append({"args": list(args), "cwd": kwargs.get("cwd"),
                          "creationflags": kwargs.get("creationflags", 0)})

    def fake_copy(src, dst, retries=su.COPY_RETRIES):
        if fail_copy:
            return False
        return originals["_copy_with_retry"](src, dst, retries)

    su.temp_dir = lambda: str(sandbox)          # 备份/临时文件都落在沙箱里
    su.subprocess.Popen = FakePopen
    su._copy_with_retry = fake_copy
    su.relaunch_elevated = lambda argv=None: elevate
    su.current_executable = lambda: str(staging)
    try:
        argv = [str(staging), "--update", "--pid", "0", "--target", str(target)]
        code = su.run_update_mode(argv)
    finally:
        su.temp_dir = originals["temp_dir"]
        su.subprocess.Popen = originals["Popen"]
        su._copy_with_retry = originals["_copy_with_retry"]
        su.relaunch_elevated = originals["relaunch_elevated"]
        su.current_executable = originals["current_executable"]
    return code, calls, target, staging


def check_updater_run():
    sandbox = _sandbox("updater_ok")
    code, calls, target, staging = _run_updater(sandbox)
    check("更新器跑完返回 0", code == 0, f"{code}")
    check("原路径已经被覆盖成新版", target.read_text(encoding="utf-8") == "NEW",
          target.read_text(encoding="utf-8"))
    backup = sandbox / "ToolsGCP.bak"
    check("原 exe 被备份成 %TEMP%\\ToolsGCP.bak（内容是旧的）",
          backup.exists() and backup.read_text(encoding="utf-8") == "OLD",
          backup.read_text(encoding="utf-8") if backup.exists() else "（没有备份）")

    # ★ 需求："我只允许原有目录存在 ToolsGCP.exe"
    program_dir = target.parent
    leftovers = sorted(p.name for p in program_dir.iterdir())
    check("★ 程序目录里**只有** ToolsGCP.exe（没有 .cmd / .new / .bak 残留）",
          leftovers == ["ToolsGCP.exe"], f"{leftovers}")

    check("启动了原路径的新版（并带上了 --cleanup 让新版自己清理临时文件）",
          bool(calls) and calls[-1]["args"][0] == str(target)
          and calls[-1]["args"][1:3] == ["--cleanup", str(staging)],
          f"{calls}")
    check("启动新版时工作目录 = 程序目录",
          bool(calls) and os.path.normcase(str(calls[-1]["cwd"]))
          == os.path.normcase(str(program_dir)),
          f"{calls[-1]['cwd'] if calls else None}")


def check_updater_rollback():
    sandbox = _sandbox("updater_rollback")
    code, calls, target, staging = _run_updater(sandbox, fail_copy=True)
    check("覆盖失败 → 返回非 0（明确失败，不假装成功）", code != 0, f"{code}")
    check("★ 覆盖失败 → 原 exe 被**回滚**成旧内容",
          target.read_text(encoding="utf-8") == "OLD",
          target.read_text(encoding="utf-8"))
    check("回滚之后又把旧版启动起来了", bool(calls), f"{calls}")
    leftovers = sorted(p.name for p in target.parent.iterdir())
    check("失败时程序目录里也只有 ToolsGCP.exe", leftovers == ["ToolsGCP.exe"],
          f"{leftovers}")


def check_updater_elevate():
    from pymodels.core import self_update as su
    sandbox = _sandbox("updater_elevate")
    code, calls, target, staging = _run_updater(sandbox, fail_copy=True,
                                                elevate=True)
    check("普通权限覆盖失败 → 请求提权（返回 0，交给管理员那次继续）",
          code == 0, f"{code}")
    check("提权那次不去回滚（文件还没动，管理员那次会做完）",
          target.read_text(encoding="utf-8") == "OLD")
    elev_args = su.build_updater_args(staging, target, 123)
    check("提权用的是同一套启动参数（--update --pid --target 不变）",
          "--update" in elev_args and "--pid" in elev_args
          and "--target" in elev_args, f"{elev_args}")


# ==========================================================================
# 七、启动后清理
# ==========================================================================

# 子进程独占式占用一个文件（模拟"更新器进程还没退出、文件删不掉"）
_HOLDER = r"""
import ctypes, sys, time
from ctypes import wintypes
k = ctypes.WinDLL("kernel32", use_last_error=True)
k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                          wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                          wintypes.HANDLE]
k.CreateFileW.restype = wintypes.HANDLE
GENERIC_READ, GENERIC_WRITE, OPEN_EXISTING = 0x80000000, 0x40000000, 3
handle = k.CreateFileW(sys.argv[1], GENERIC_READ | GENERIC_WRITE, 0, None,
                       OPEN_EXISTING, 0, None)
if not handle:
    raise SystemExit("open failed %d" % ctypes.get_last_error())
open(sys.argv[2], "w").write("ready")
time.sleep(float(sys.argv[3]))
k.CloseHandle(handle)
"""


def check_cleanup():
    from pymodels.core import self_update as su
    sandbox = _sandbox("cleanup")
    staging = sandbox / "ToolsGCP_new.exe"
    backup = sandbox / "ToolsGCP.bak"
    staging.write_text("NEW", encoding="utf-8")
    backup.write_text("OLD", encoding="utf-8")

    original_temp = su.temp_dir
    su.temp_dir = lambda: str(sandbox)
    try:
        su.cleanup_after_update(["x.exe", "--cleanup", str(staging)])
    finally:
        su.temp_dir = original_temp
    check("新版启动后清理了 %TEMP%\\ToolsGCP_new.exe", not staging.exists())
    check("新版启动后清理了 %TEMP%\\ToolsGCP.bak", not backup.exists())

    # 没带 --cleanup 时不许动备份（那是回滚用的）
    staging.write_text("NEW", encoding="utf-8")
    backup.write_text("OLD", encoding="utf-8")
    su.temp_dir = lambda: str(sandbox)
    try:
        su.cleanup_after_update(["x.exe"])
    finally:
        su.temp_dir = original_temp
    check("不是更新后的启动就不会去删备份（免得毁掉回滚点）", backup.exists())


def check_cleanup_locked():
    """临时文件还被那个更新器进程占着时，也要（后台）删掉"""
    from pymodels.core import self_update as su

    if sys.platform != "win32":
        print("[SKIP] 非 Windows，跳过被占用文件的清理")
        return

    sandbox = _sandbox("cleanup_locked")
    staging = sandbox / "ToolsGCP_new.exe"
    backup = sandbox / "ToolsGCP.bak"
    ready = sandbox / "_ready.flag"
    staging.write_text("NEW", encoding="utf-8")
    backup.write_text("OLD", encoding="utf-8")

    holder = subprocess.Popen([sys.executable, "-c", _HOLDER,
                               str(staging), str(ready), "4"])
    deadline = time.time() + 10
    while not ready.exists() and holder.poll() is None and time.time() < deadline:
        time.sleep(0.05)

    original_temp = su.temp_dir
    su.temp_dir = lambda: str(sandbox)
    try:
        started = time.perf_counter()
        su.cleanup_after_update(["x.exe", "--cleanup", str(staging)])
        elapsed = time.perf_counter() - started
    finally:
        su.temp_dir = original_temp
        holder.wait()

    check("被占用时清理不会卡住启动（同步部分很快返回）",
          elapsed < 3.0, f"{elapsed:.2f}s")
    check("备份照样删掉了", not backup.exists())

    deadline = time.time() + 15
    while time.time() < deadline and staging.exists():
        time.sleep(0.2)
    check("★ 占用解除后，后台线程把 %TEMP%\\ToolsGCP_new.exe 删掉了",
          not staging.exists())


# ==========================================================================
# 八、入口顺序
# ==========================================================================

def check_entry_order():
    source = (PROJECT_ROOT / "ToolsGCP.pyw").read_text(encoding="utf-8")
    call_at = source.find("if _run_update_mode_if_needed():")
    mutex_at = source.find("SingleInstanceChecker()")
    check("更新模式的处理排在单实例检测**之前**（否则更新器会被互斥锁挡掉）",
          0 <= call_at < mutex_at, f"update@{call_at} mutex@{mutex_at}")
    check("更新模式的处理里不创建 QApplication（整段在 QApplication 之前）",
          source.find("QApplication(sys.argv)") > call_at >= 0)
    check("更新模式之后用 sys.exit 收口（绝不继续启动）",
          "if _run_update_mode_if_needed():" in source
          and "sys.exit(0)" in source[call_at:call_at + 400])


def main():
    print("=" * 66)
    print("一、路径与启动参数（%TEMP% + --update --pid --target）")
    print("=" * 66)
    check_paths_and_args()

    print()
    print("=" * 66)
    print("二、能不能换（replacement_blockers）")
    print("=" * 66)
    check_blockers()

    print()
    print("=" * 66)
    print("三、进程句柄等待（真起子进程）")
    print("=" * 66)
    check_wait_handle()

    print()
    print("=" * 66)
    print("四、更新器主流程（沙箱干跑）")
    print("=" * 66)
    check_updater_run()

    print()
    print("=" * 66)
    print("五、失败回滚 + 六、提权")
    print("=" * 66)
    check_updater_rollback()
    check_updater_elevate()

    print()
    print("=" * 66)
    print("七、启动后清理 + 八、入口顺序")
    print("=" * 66)
    check_cleanup()
    check_cleanup_locked()
    check_entry_order()

    print()
    if FAILURES:
        print(f"[FAIL] {len(FAILURES)} 项没通过：")
        for item in FAILURES:
            print(f"   - {item}")
        return 1
    print("[OK] 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
