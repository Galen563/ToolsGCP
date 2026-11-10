"""启动"界面缩放显示闸门"验证

用户要求：彻底解决启动时"先出现一小块界面、然后自动适配调整界面和 ui 大小"的跳变。
修法：把 ZoomFactor 有结论变成窗口显示的第三道前置条件（带超时兜底）。

A. frame 侧通知器语义（幂等、异常不外溢、无窗口环境也能验）
B. shell 侧三条放行路径 + "绝不自锁 / 绝不永不显示"的静态不变量
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, '.ToolsGCP'), os.path.join(ROOT, '.ToolsGCP', 'modules')]

fails = []


def check(name, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + name + (("  <- " + detail) if (detail and not ok) else ""))
    if not ok:
        fails.append(name)


# ============ A. 通知器语义 ============
from desktop.native import frame as F

print("A) frame._make_zoom_notifier")
calls = []
fire = F._make_zoom_notifier(lambda: calls.append(1))
fire()
fire()
fire()
check("回调只触发一次（幂等）", len(calls) == 1, str(len(calls)))

boom = []


def bad():
    boom.append(1)
    raise RuntimeError("回调炸了")


raised = False
try:
    F._make_zoom_notifier(bad)()
except Exception:
    raised = True
check("回调异常不外溢（不崩启动线程）", not raised)
check("异常后不再重试（仍是一次）", len(boom) == 1, str(len(boom)))

try:
    F._make_zoom_notifier(None)()
    ok = True
except Exception:
    ok = False
check("on_ready=None 时调用不抛", ok)

ha, hb = [], []
fa, fb = F._make_zoom_notifier(lambda: ha.append(1)), F._make_zoom_notifier(lambda: hb.append(1))
fa()
fa()
fb()
check("不同调用的通知器互不影响（显示器变化可再次调用）", ha == [1] and hb == [1], str((ha, hb)))

fired = []
F.apply_page_zoom(None, 1.5, on_ready=lambda: fired.append(1))
check("window=None 也立刻放行（闸门不空等）", fired == [1], str(fired))
fired2 = []
F.apply_page_zoom(object(), 0, on_ready=lambda: fired2.append(1))
check("zoom<=0 也立刻放行", fired2 == [1], str(fired2))

# ============ B. shell 侧静态不变量 ============
print()
print("B) shell 显示闸门")
shell = io.open(os.path.join(ROOT, '.ToolsGCP', 'desktop', 'shell.py'), encoding='utf-8').read()
frame_src = io.open(os.path.join(ROOT, '.ToolsGCP', 'desktop', 'native', 'frame.py'),
                    encoding='utf-8').read()

check("有 ZOOM_GATE_TIMEOUT 兜底常量", 'ZOOM_GATE_TIMEOUT = ' in shell)
check("闸门默认放行（r=1.0 不会永不显示）", 'self._zoom_ready = True' in shell)
check("算出 r 的当场就关闸门（早于 ready 事件）",
      shell.index('self._ui_scale = frame.ui_scale_factor()')
      < shell.index('self._zoom_ready = False'))
check("_try_show 检查第三条件", 'if not self._zoom_ready:' in shell)
check("超时兜底强制放行", 'def _on_zoom_gate_timeout' in shell)
check("apply_page_zoom 挂上结论回调", 'on_ready=self.mark_zoom_ready' in shell)

# mark_zoom_ready 的函数体
m = re.search(r"def mark_zoom_ready\(self\):(.*?)\n    def ", shell, re.S)
body = m.group(1) if m else ""
check("mark_zoom_ready 函数体取到了", bool(body))
check("不直接调 _try_show（避免 GUI 线程自锁）", 'self._try_show()' not in body)
check("用另起线程的方式补显示", 'threading.Thread(target=self._try_show' in body)
check("放行时取消兜底定时器", 'gate.cancel()' in body)
check("退出竞态下不置位（teardown 闸门）", '_teardown_started' in body)

# frame 侧三条路径都要 notify
check("frame 成功路径 notify", 'notify()' in frame_src)
check("frame 被拒路径也 notify（否则闸门只能等超时）",
      frame_src.count('notify()') >= 4, str(frame_src.count('notify()')))
check("frame 编组失败/异常路径 notify",
      'if not ok:' in frame_src and frame_src.count('notify()') >= 5)

print()
print("=== %s ===" % ("全部通过" if not fails else "未通过: " + str(fails)))
sys.exit(1 if fails else 0)
