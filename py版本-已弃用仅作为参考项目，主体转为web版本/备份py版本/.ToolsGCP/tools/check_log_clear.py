"""日志清理自检 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/check_log_clear.py

盯两件事：clear_history() 只删 history/ 下的归档、不动当前日志；重启归档照旧。

⚠️ 全程在沙箱目录里跑，绝不碰用户真实的 .ToolsGCP/logs/。
"""

import os
import shutil
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"
# ⚠️ 沙箱放在 tools/_out 下，别用 tempfile（有的环境写不了系统临时目录）。
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


def main():
    sandbox = OUT_DIR / "_check_log_clear"
    if sandbox.exists():
        shutil.rmtree(sandbox, ignore_errors=True)
    logs_dir = sandbox / "logs"
    history_dir = logs_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    # 先摆一份上次的日志和假归档，再让 logger 进来（它会归档当前那份）
    (logs_dir / "system_log.log").write_text("OLD-SESSION-LINE\n", encoding="utf-8")
    (history_dir / "ToolsGCP-2020-01-01-000000000.log").write_text(
        "very old\n", encoding="utf-8")

    # ⚠️ 必须在 import logger 之前改 constants（logger 是 `from ..constants import …`）
    from pymodels import constants
    constants.LOGS_DIR = str(logs_dir)
    constants.LOG_HISTORY_DIR = str(history_dir)
    constants.LOG_CURRENT_FILE = "system_log.log"

    from pymodels.utils import logger as logger_mod
    log = logger_mod.Logger()

    current = Path(log.current_path)
    check("沙箱里的当前日志路径就是沙箱那一份",
          current == logs_dir / "system_log.log", f"{current}")

    archived = sorted(p.name for p in history_dir.glob("*.log"))
    # ⚠️ 不断言"正好几份"：每次构造 Logger 都会归档上一份，份数不稳定，只断言归档发生了。
    check("启动归档照旧工作：上一份日志被搬进了 history/",
          len(archived) >= 2, f"{archived}")
    check("归档里能找到刚才那份日志的内容",
          any("OLD-SESSION-LINE" in (history_dir / name).read_text(encoding="utf-8")
              for name in archived), f"{archived}")

    # 这次会话写点东西
    log.info("启动", "startup", "本次会话的第一行")
    log.op("设置", "update", key="theme", value="深色主题")
    before = current.read_text(encoding="utf-8")
    check("当前日志里有本次会话的内容", "本次会话的第一行" in before and before.strip() != "")

    # 再摆两个假历史再清理（名字不可与上面重名，重名会被覆盖）
    for i in (5, 6):
        (history_dir / f"ToolsGCP-2020-01-0{i}-000000000.log").write_text(
            "junk\n", encoding="utf-8")
    history_before = len(list(history_dir.glob("*.log")))
    check("清理前 history/ 里有归档（>= 4 份）", history_before >= 4,
          f"{history_before}")

    removed = log.clear_history()

    check("clear_history() 删掉的份数 == 清理前实际份数",
          removed == history_before, f"{removed} != {history_before}")
    check("history/ 被清空了", not list(history_dir.glob("*.log")),
          f"{list(history_dir.glob('*.log'))}")

    after = current.read_text(encoding="utf-8")
    check("★ 当前日志**内容没被清掉**（需求原话的那一条）", after == before,
          f"before={before!r} after={after!r}")
    check("当前日志里还能查到清理前写的操作记录",
          "本次会话的第一行" in after and "key=theme" in after, f"{after!r}")

    # 清理之后再写一条：句柄没被关掉，还能继续追加
    log.info("日志", "log", "清理之后还能继续写")
    tail = current.read_text(encoding="utf-8")
    check("清理之后日志句柄仍然可用（还能继续追加）",
          "清理之后还能继续写" in tail and "本次会话的第一行" in tail, f"{tail!r}")

    # 非 .log 的文件不该被顺手删掉
    (history_dir / "keepme.txt").write_text("not a log\n", encoding="utf-8")
    log.clear_history()
    check("history/ 里的非 .log 文件不会被删",
          (history_dir / "keepme.txt").exists())

    log.close()
    try:
        shutil.rmtree(sandbox, ignore_errors=True)
    except Exception:
        pass

    print()
    if FAILURES:
        print(f"❌ {len(FAILURES)} 项没通过：")
        for item in FAILURES:
            print(f"   - {item}")
        return 1
    print("✅ 全部通过：清理历史不会动当前日志")
    return 0


if __name__ == "__main__":
    sys.exit(main())
