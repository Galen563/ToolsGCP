"""打包辅助：给 constants.py 的 get_script_dir() 临时打上 frozen 资源路径补丁。

========== 为什么单独成文件，而不是写在 build.bat 里 ==========
build.bat 以前用 `python -c "……"` 内联一大段含三引号的 Python。
在 cmd 里这非常脆弱：
  · 批处理对引号、括号、`^`、`%` 的转义规则和 Python 完全不同；
  · 在 GBK 代码页下长命令行还会被截断；
  · 结果是 Python 收到半截字符串 → `SyntaxError: unterminated triple-quoted
    string literal`，补丁从来没打上过，打包出的 exe 找不到语言文件/图标/插件。
所以把这段逻辑挪到独立 .py 文件，bat 只负责调用它。源码里不再有任何内联 Python。

========== 补丁做了什么 ==========
frozen（PyInstaller）后 `sys.executable` 指向 exe 自身，而资源被解压到
`sys._MEIPASS`。原来的 get_script_dir() 只认 exe 目录，于是：
  · CONFIG_DIR = <exe 目录>\\.ToolsGCP   ← 这个目录**不存在**
  · 语言文件、logo.png、内置插件全部找不到
补丁让它优先返回 `sys._MEIPASS`（该目录下确实有 .ToolsGCP 时），
onefile / onedir 两种布局都正确；源码运行不受影响（走 else 分支）。

========== 安全约束 ==========
  · 只替换**恰好一处**，替换前断言原文存在、替换后断言只改了一处；
  · 幂等：已经是打过补丁的状态就直接跳过（避免重复打包报错）；
  · 只写回该文件，不碰其它任何文件。
用法（由 build.bat 调用，也可手动）：
    python "项目资料-文档与开发测试/tools/_patch_frozen.py"
退出码 0 = 成功（或已是补丁状态），非 0 = 失败。
"""

import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 项目根 = 本文件的上上级（tools → 项目资料… → 根）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGET = os.path.join(ROOT, '.ToolsGCP', 'modules', 'pymodels', 'constants.py')

OLD = '''def get_script_dir():
    """获取脚本所在目录"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        return os.path.dirname(os.path.abspath(sys.argv[0]))'''

NEW = '''def get_script_dir():
    """获取脚本所在目录"""
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass and os.path.isdir(os.path.join(meipass, '.ToolsGCP')):
            return meipass
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        return os.path.dirname(os.path.abspath(sys.argv[0]))'''


def main() -> int:
    if not os.path.isfile(TARGET):
        print(f'[错误] 找不到 {TARGET}')
        return 1

    with open(TARGET, 'r', encoding='utf-8') as f:
        src = f.read()

    # ---- 已经是补丁状态：直接成功返回（幂等，允许重复调用） ----
    if NEW in src:
        print('已经是补丁状态，跳过（幂等）')
        return 0

    # ---- 原文必须恰好出现一次 ----
    count = src.count(OLD)
    if count != 1:
        print(f'[错误] get_script_dir() 原文出现 {count} 次（应恰好 1 次），'
              f'constants.py 可能已被改动，请人工检查后再打包')
        return 1

    patched = src.replace(OLD, NEW, 1)

    # ---- 替换后自检：只多了一段、且仍能编译 ----
    if patched.count(NEW) != 1:
        print('[错误] 替换结果异常（补丁段不是恰好 1 处）')
        return 1
    try:
        compile(patched, TARGET, 'exec')
    except SyntaxError as exc:
        print(f'[错误] 补丁后语法错误：{exc}')
        return 1
    if not patched.startswith(src[:200]):
        print('[错误] 补丁后文件头部被破坏')
        return 1

    with open(TARGET, 'w', encoding='utf-8', newline='') as f:
        f.write(patched)

    print('patch ok')
    return 0


if __name__ == '__main__':
    sys.exit(main())
