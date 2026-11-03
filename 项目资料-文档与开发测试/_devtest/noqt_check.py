# -*- coding: utf-8 -*-
"""无 Qt 自检：确认 **Web 版主链路完全不依赖 PyQt5 / qfluentwidgets**。

========== 为什么需要它 ==========
本项目已经从 `requirements.txt` 里移除了 PyQt5 + PyQt-Fluent-Widgets（原来占 exe 体积几十 MB）：

  · 启动动画 `desktop/splash.py` 改成纯 Win32 分层窗口（ctypes + Pillow）；
  · `pymodels/core/announcements.py` 删掉了只被旧 Qt 界面使用的 QThread 类；
  · `pymodels/utils/system_utils.py` 的 Qt 改成惰性 import；
  · 其余 `pymodels/utils|core` 里的 Qt 模块（fonts / i18n_widgets / theme_utils /
    smooth_scroll / plugin_manager / updater …）Web 版从未引用。

**但没有自动化检查的话，"某天有人又在主链路加了一句 `import PyQt5`"是查不出来的** ——
开发机往往装着 PyQt5，`import xxx` 照样成功，打包后才在用户机器上炸。
所以这里用 import 钩子**假装没装 Qt**，把整条主链路 import 一遍：

  · 被拦截的 Qt import 次数必须 = 0
  · 失败的模块必须为空

========== 用法 ==========
    python "项目资料-文档与开发测试/_devtest/noqt_check.py"
退出码 0 = 通过；非 0 = 有模块仍依赖 Qt（会列出名字与拦截次数）。
⚠️ 跑之前必须已经执行过 `pip install -r requirements.txt`（不需要装 PyQt5）。
"""

import builtins
import importlib
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 项目根 = 本文件的上上级（_devtest → 项目资料… → 根）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# ⚠️⚠️ pymodels.constants.SCRIPT_DIR 取自 `sys.argv[0]`；不修正的话 CONFIG_DIR 会
#    算成"本脚本所在目录"，内置插件目录/资源路径全错。这里指向真实入口。
sys.argv[0] = os.path.join(ROOT, 'ToolsGCP.pyw')
sys.path[:0] = [os.path.join(ROOT, '.ToolsGCP'),
                os.path.join(ROOT, '.ToolsGCP', 'modules')]

BLOCKED = ('PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'qfluentwidgets')
hits = []
_real_import = builtins.__import__


def _guard(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split('.')[0] in BLOCKED:
        hits.append(name)
        raise ImportError('自检环境：模拟未安装 ' + name.split('.')[0])
    return _real_import(name, globals, locals, fromlist, level)


# 主链路：入口 → 外壳 → 各业务域 → 原生层 → pymodels 核心 → AI
TARGETS = [
    'desktop.shell', 'desktop.api', 'desktop.webhost', 'desktop.splash',
    'desktop.native.frame', 'desktop.native.tray', 'desktop.native.traymenu',
    'desktop.native.hotkey', 'desktop.native.appicon', 'desktop.native.autostart',
    'desktop.native.clipboard', 'desktop.native.privacy_state',
    'pymodels.constants', 'pymodels.core.data_root', 'pymodels.core.data_dir',
    'pymodels.core.settings_manager', 'pymodels.core.language_manager',
    'pymodels.core.en_fallback', 'pymodels.core.announcements',
    'pymodels.core.self_update', 'pymodels.utils.logger', 'pymodels.utils.crash_guard',
    'pymodels.utils.secret_store', 'pymodels.core.ai.client',
    # AI 工具链会**惰性**引用这两个；它们内部也不能顶层碰 Qt
    'pymodels.core.ai.agent_tools', 'pymodels.core.ai.agent_runtime',
    'pymodels.utils.system_utils',
]


def main() -> int:
    builtins.__import__ = _guard
    failed = []
    try:
        for name in TARGETS:
            try:
                importlib.import_module(name)
                print('OK   ', name)
            except Exception as exc:                    # noqa: BLE001
                failed.append(name)
                print('FAIL ', name, '->', type(exc).__name__, str(exc)[:120])
    finally:
        builtins.__import__ = _real_import

    print()
    print('=' * 74)
    print('被拦截的 Qt import 次数:', len(hits))
    if hits:
        for h in sorted(set(hits)):
            print('   ', h)
        print('   ⚠️ 还有模块在 import Qt —— 主链路没清干净')
    else:
        print('   ✅ 主链路全程没有尝试 import 任何 Qt 模块')
    print('失败模块:', failed if failed else '无')

    return 0 if (not failed and not hits) else 1


if __name__ == '__main__':
    sys.exit(main())
