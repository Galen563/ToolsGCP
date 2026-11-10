# -*- coding: utf-8 -*-
"""`_log("op", …)` 静默失效的复现 + 修复验证（task-1 第 5 项"日志部分操作不记录"的根因）。

现象：api 层到处写 `_log("op", 分类, 动作, 文本)`，但 logger.op 的签名是
      `op(cat_zh, action, **fields)` —— 第 3 个**位置参数**（那段文本）会 TypeError，
      又被 `_log` 里的 `except Exception: pass` 吞掉 → 这条 op 日志**从来没写进文件**。
      这就是用户说的"日志部分操作不进行记录"的真正来源（不是"忘了加日志"，是加了也没用）。

跑法：python "项目资料-文档与开发测试/_devtest/test_op_log_path.py"
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.argv = [os.path.join(ROOT, "ToolsGCP.pyw")]
sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]

import pymodels.utils.logger as L                            # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f"  <- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


# 抓住所有真正落地的日志（不写盘，只拦 log 方法）
cap = []
orig = L.Logger.log


def spy(self, level, cat_zh, cat_en, msg, *a, **k):
    cap.append((level, cat_zh, cat_en, msg))


L.Logger.log = spy

print("[1] 直接调 logger.op 的正确姿势（2 个位置参数）")
cap.clear()
L.log.op("设置", "api_key", key="x", new="y")
check("op(cat, action, **fields) 正常落地", len(cap) == 1 and cap[0][0] == "OP",
      str(cap))

print("[2] 防回归：op 现在必须接受第 3 个位置参数（旧签名会 TypeError → 被 _log 吞掉）")
cap.clear()
try:
    L.log.op("设置", "api_key", "保存 API Key：服务商=deepseek")
    raised = False
except TypeError:
    raised = True
check("op(分类, 动作, 文本) 不再抛 TypeError（40 处 api 层 _log('op') 的通路已打通）",
      not raised and len(cap) == 1, f"raised={raised} cap={cap}")
if cap:
    check("第 3 个位置参数作为操作文本被保留（不是当字段吞掉）",
          "保存 API Key" in cap[0][3], cap[0][3][:120])

print("[3] _log('op', …) 走一遍：修复后必须真的记下来")
# 用 resources 的 _log（它内部 getattr(log,'op')(...)）
from desktop.api import resources as R                      # noqa: E402
cap.clear()
R._log("op", "设置", "api_key", "保存 API Key：服务商=deepseek 已配置（24 位）")
check("_log('op',分类,动作,文本) 修复后落地 1 条", len(cap) == 1, str(cap))
if cap:
    check("级别是 OP", cap[0][0] == "OP", str(cap[0]))
    check("文本没丢（出现在最终 msg 里）",
          "保存 API Key" in cap[0][3], cap[0][3][:120])

print("[4] _log 其它级别（info/warn/err/dbg）不受影响")
cap.clear()
R._log("info", "资源库", "cloud", "一条普通 info")
R._log("warn", "资源库", "cloud", "一条普通 warn")
check("info/warn 照常落地", len(cap) == 2 and cap[0][0] == "INFO" and cap[1][0] == "WARN",
      str([(c[0]) for c in cap]))

print("[5] 明文 Key 绝不进日志（这条改动配套的安全线）")
cap.clear()
R._log("op", "设置", "api_key", "保存 API Key：服务商=deepseek 已配置（24 位）")
blob = " ".join(str(c) for c in cap)
check("日志文本里只有长度、没有 Key 本体", "sk-" not in blob and "24 位" in blob, blob[:120])

L.Logger.log = orig
print()
if FAILS:
    print(f"FAILED {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("ALL OK")
