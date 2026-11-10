@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

if not exist "ToolsGCP.pyw" (
    echo [错误] 请把本 bat 放在 ToolsGCP.pyw 同级目录再运行。
    pause
    exit /b 1
)
if not exist ".ToolsGCP\modules\pymodels\constants.py" (
    echo [错误] 找不到 .ToolsGCP\modules\pymodels\constants.py
    pause
    exit /b 1
)

echo [1/4] 备份 constants.py ...
copy /Y ".ToolsGCP\modules\pymodels\constants.py" ".ToolsGCP\modules\pymodels\constants.py.bak" >nul

echo [2/4] 临时写入 frozen 路径（打包用，结束后会还原）...
python -c "import pathlib;p=pathlib.Path(r'.ToolsGCP/modules/pymodels/constants.py');c=p.read_text(encoding='utf-8');old='''def get_script_dir():\n    \"\"\"获取脚本所在目录\"\"\"\n    if getattr(sys, 'frozen', False):\n        return os.path.dirname(os.path.abspath(sys.executable))\n    else:\n        return os.path.dirname(os.path.abspath(sys.argv[0]))''';new='''def get_script_dir():\n    \"\"\"获取脚本所在目录\"\"\"\n    if getattr(sys, 'frozen', False):\n        meipass = getattr(sys, '_MEIPASS', None)\n        if meipass and os.path.isdir(os.path.join(meipass, '.ToolsGCP')):\n            return meipass\n        return os.path.dirname(os.path.abspath(sys.executable))\n    else:\n        return os.path.dirname(os.path.abspath(sys.argv[0]))''';assert old in c, '未匹配到 get_script_dir，请检查 constants.py';p.write_text(c.replace(old,new,1),encoding='utf-8');print('patch ok')"
if errorlevel 1 (
    echo [错误] 自动改路径失败，已还原。
    copy /Y ".ToolsGCP\modules\pymodels\constants.py.bak" ".ToolsGCP\modules\pymodels\constants.py" >nul
    del /F /Q ".ToolsGCP\modules\pymodels\constants.py.bak" >nul 2>&1
    pause
    exit /b 1
)

echo [3/4] 开始 PyInstaller 打包（无 PyQt）...
pyinstaller --noconfirm --onefile --windowed --name ToolsGCP --icon=.ToolsGCP/logo.png --add-data ".ToolsGCP;.ToolsGCP" --paths=.ToolsGCP --paths=.ToolsGCP/modules --hidden-import=pymodels --hidden-import=desktop --collect-submodules=pymodels --collect-submodules=desktop --collect-all pywebview --collect-all bottle --collect-all pythonnet --collect-all PIL --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 --exclude-module PySide6 --exclude-module matplotlib --exclude-module numpy --exclude-module scipy --exclude-module pandas --exclude-module tkinter ToolsGCP.pyw
set "BUILD_ERR=%ERRORLEVEL%"

echo [4/4] 还原 constants.py ...
copy /Y ".ToolsGCP\modules\pymodels\constants.py.bak" ".ToolsGCP\modules\pymodels\constants.py" >nul
del /F /Q ".ToolsGCP\modules\pymodels\constants.py.bak" >nul 2>&1

if not "%BUILD_ERR%"=="0" (
    echo.
    echo [失败] 打包出错，错误码 %BUILD_ERR%。源码已还原。
    pause
    exit /b %BUILD_ERR%
)

echo.
echo [完成] 单文件：dist\ToolsGCP.exe
echo 已去掉 PyQt；.ToolsGCP 打进 exe；运行时用包内资源，不会在 exe 旁新建 .ToolsGCP。
echo.
pause