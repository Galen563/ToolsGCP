"""内置插件三项策略自检 —— 不参与程序运行

用法（项目根目录）：
    python .ToolsGCP/tools/check_builtin_plugins.py

检查项：首页推荐不显示两个内置插件（但插件仍在）、关 Agent 时制作辅助跟着停用、改名不改 id/目录名。
"""

import json
import os
import re
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parents[1]
PKG_DIR = PROJECT_ROOT / ".ToolsGCP" / "modules"
PLUGIN_DIR = PROJECT_ROOT / ".ToolsGCP" / "plugins" / "gcp-plugin-maker"

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
# ⚠️ 让 update_setting 只改内存不落盘，否则会把用户真实的 toolsgcp_config.json 改掉。
os.environ.setdefault("TOOLSGCP_NO_SETTINGS_WRITE", "1")
sys.argv[0] = str(PROJECT_ROOT / "ToolsGCP.pyw")
sys.path.insert(0, str(PKG_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = []

# 英文旧名字：单独一个 "Plugin Maker"（后面没跟 Helper）才算残留
_STALE_EN = re.compile(r"Plugin Maker(?! Helper)")


def check(ok, label, detail=""):
    print(f"[{'OK  ' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def pump(app, rounds=6, ms=40):
    from PyQt5.QtCore import QTimer
    for _ in range(rounds):
        QTimer.singleShot(ms, app.quit)
        app.exec_()


def check_rename():
    """C：改名改到位（显示名），但没有改 id / 目录名"""
    manifest = json.loads((PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8"))
    names = manifest.get("name") or {}
    check(manifest.get("id") == "gcp-plugin-maker",
          "插件 id 仍然是 gcp-plugin-maker（改名不是改 id）", str(manifest.get("id")))
    check(names.get("简体中文") == "插件制作辅助",
          "manifest 的简体中文显示名是「插件制作辅助」", str(names.get("简体中文")))
    check(names.get("繁體中文") == "外掛製作輔助",
          "manifest 的繁體中文显示名是「外掛製作輔助」", str(names.get("繁體中文")))
    check(bool(names.get("English")) and "Helper" in names.get("English", ""),
          "manifest 的英文显示名跟着改（Plugin Maker Helper）", str(names.get("English")))

    locales = {"zh_CN.json": names.get("简体中文"),
               "zh_TW.json": names.get("繁體中文"),
               "en_US.json": names.get("English")}
    key_sets = []
    for filename, display in locales.items():
        data = json.loads((PLUGIN_DIR / "lang" / filename).read_text(encoding="utf-8"))
        key_sets.append(tuple(sorted(data)))
        check(data.get("title") == display,
              f"{filename} 的标题和 manifest 显示名一致",
              f"{data.get('title')!r} vs {display!r}")
        # ⚠️ 英文旧名要用"后面没跟 Helper"判断：新名 Plugin Maker Helper 本身就含这几个词。
        stale = [k for k, v in data.items()
                 if isinstance(v, str) and ("插件制作器" in v or "外掛製作器" in v
                                            or _STALE_EN.search(v))]
        check(not stale, f"{filename} 里不该残留旧名字", str(stale))
    check(len(set(key_sets)) == 1, "三套语言文件的键必须完全一致",
          str([len(k) for k in key_sets]))

    for path in (PLUGIN_DIR / "app.py", PLUGIN_DIR / "ui" / "page.py",
                 PLUGIN_DIR / "core" / "maker.py", PLUGIN_DIR / "core" / "skill.py"):
        text = path.read_text(encoding="utf-8")
        check("插件制作器" not in text and "外掛製作器" not in text,
              f"{path.relative_to(PROJECT_ROOT)} 里不该残留旧名字")


def build_manager(tmp_config):
    from pymodels.core.plugin_manager import PluginManager
    from pymodels.core.settings_manager import SettingsManager
    from pymodels.core.language_manager import LanguageManager

    settings = SettingsManager(config_dir=tmp_config)
    manager = PluginManager(str(PROJECT_ROOT), tmp_config,
                            settings_manager=settings,
                            language_manager=LanguageManager())
    return manager, settings


def check_agent_cascade():
    from pymodels.core.plugin_manager import (AI_AGENT_PLUGIN_ID, MAKER_PLUGIN_ID,
                                              PluginInfo, STATUS_DISABLED, STATUS_OK)
    tmp_config = tempfile.mkdtemp(prefix="toolsgcp-check-")
    manager, settings = build_manager(tmp_config)
    manager.load_all()

    by_id = {info.id: info for info in manager.plugins}
    check(AI_AGENT_PLUGIN_ID in by_id and MAKER_PLUGIN_ID in by_id,
          "两个内置插件都被扫到了（隐藏 ≠ 不加载）", str(sorted(by_id)))
    if AI_AGENT_PLUGIN_ID not in by_id or MAKER_PLUGIN_ID not in by_id:
        return
    agent, maker = by_id[AI_AGENT_PLUGIN_ID], by_id[MAKER_PLUGIN_ID]

    # 先把两个都打开（全新配置里默认停用），再模拟"关 Agent"
    for info in (agent, maker):
        manager.set_enabled(info, True)
        manager.reload_plugin(info)
    check(agent.status == STATUS_OK and maker.status == STATUS_OK,
          "自检前置：两个插件先都开着", f"agent={agent.status} maker={maker.status}")

    # 塞一个"生成物"插件，验证连坐停用生成物的老行为没坏
    fake = PluginInfo("zz-check-generated")
    fake.id = "zz-check-generated"
    fake.name = "自检生成物"
    fake.dir = str(tmp_config)
    fake.manifest = {"generated_by": MAKER_PLUGIN_ID}
    fake.status = STATUS_OK
    manager.plugins.append(fake)
    manager.set_enabled(fake, True)

    manager.set_enabled(agent, False)
    manager.reload_plugin(agent)

    check(agent.status == STATUS_DISABLED and agent.id in manager.disabled,
          "关掉 Agent 之后它自己是停用的", f"status={agent.status}")
    check(maker.id in manager.disabled and maker.status == STATUS_DISABLED,
          "关掉 Agent 之后「插件制作辅助」跟着停用",
          f"disabled={sorted(manager.disabled)} status={maker.status}")
    check(fake.id in manager.disabled,
          "由制作辅助生成的插件照样跟着停用（老行为没坏）",
          f"disabled={sorted(manager.disabled)}")
    check(settings.settings.get("gcp_plugin_maker_enabled") is False,
          "「插件制作辅助」的总开关设置一起关掉（不留自相矛盾的状态）",
          str(settings.settings.get("gcp_plugin_maker_enabled")))
    check(settings.settings.get("gcp_ai_agent_enabled") is False,
          "Agent 自己的总开关设置也是关的",
          str(settings.settings.get("gcp_ai_agent_enabled")))

    # 反方向：单独把制作辅助打开，不该把 Agent 也关了（放开的动作只"开"不"关"）
    manager.set_enabled(maker, True)
    manager.reload_plugin(maker)
    check(agent.status == STATUS_DISABLED and agent.id in manager.disabled,
          "单独打开制作辅助，不会反过来动 Agent 的状态",
          f"agent={agent.status}")


def check_home_hides_builtins(app):
    from pymodels.core.language_manager import LanguageManager
    from pymodels.core.plugin_manager import (AI_AGENT_PLUGIN_ID, MAKER_PLUGIN_ID,
                                              PluginInfo, STATUS_OK)
    from pymodels.interfaces.home_interface import HomeInterface

    lang = LanguageManager()
    tmp_config = tempfile.mkdtemp(prefix="toolsgcp-check-home-")
    manager, _settings = build_manager(tmp_config)
    manager.load_all()

    page = HomeInterface(lang, manager)
    page.resize(1180, 800)
    page.show()
    pump(app, 8)

    shown = [card.info.id for card in page._minicards]
    check(AI_AGENT_PLUGIN_ID not in shown and MAKER_PLUGIN_ID not in shown,
          "首页推荐里没有这两个内置插件", str(shown))
    check(page.empty_label.isVisible(),
          "只有内置插件时，首页给一句「暂无可推荐」的说明（不是「还没装插件」）",
          f"text={page.empty_label.text()!r}")
    check(page.empty_label.text() == lang.get_text("home", "no_recommend_plugins"),
          "那句说明用的是新文案 no_recommend_plugins",
          page.empty_label.text())
    check(page.empty_label.text() != lang.get_text("home", "no_plugins"),
          "不该说「还没有安装插件」（用户明明装了两个）", page.empty_label.text())
    check(not page.count_label.text(),
          "没有可推荐插件时不显示计数", repr(page.count_label.text()))

    ids = {info.id for info in manager.plugins}
    check({AI_AGENT_PLUGIN_ID, MAKER_PLUGIN_ID} <= ids,
          "两个内置插件仍然在插件列表里（没被删、也没被卸载）", str(sorted(ids)))
    for plugin_id in (AI_AGENT_PLUGIN_ID, MAKER_PLUGIN_ID):
        folder = PROJECT_ROOT / ".ToolsGCP" / "plugins" / plugin_id
        check(folder.is_dir() and (folder / "manifest.json").is_file(),
              f"插件目录/文件原封不动：{plugin_id}", str(folder))

    other = PluginInfo("zz-check-third-party")
    other.id = "zz-check-third-party"
    other.name = "自检第三方插件"
    other.version = "1.0.0"
    other.author = "self-check"
    other.description = "占位说明"
    other.dir = str(tmp_config)
    other.status = STATUS_OK
    manager.plugins.append(other)
    page.refresh_plugins()
    pump(app, 4)
    shown = [card.info.id for card in page._minicards]
    check(shown == ["zz-check-third-party"],
          "第三方插件照常出现在首页推荐里", str(shown))
    check(not page.empty_label.isVisible(), "有可推荐插件时空状态隐藏")
    check(page.count_label.text() == "（1）", "计数跟着第三方插件走",
          repr(page.count_label.text()))
    page.close()


def check_plugin_page_cascade(app):
    """真主窗口：在插件中心把 Agent 关掉 → 「插件制作辅助」卡片跟着变停用

    ⚠️ 绝不落盘：靠 TOOLSGCP_NO_SETTINGS_WRITE=1，以及把 manager._save_state 临时换成空函数。
    """
    from pymodels.core.plugin_manager import (AI_AGENT_PLUGIN_ID, MAKER_PLUGIN_ID,
                                              STATUS_DISABLED, STATUS_OK)
    from pymodels.ui.main_window import MainWindow

    window = MainWindow()
    window.resize(1280, 880)
    window.show()
    pump(app, 14, 90)
    page = window.pluginInterface
    window.switchTo(page)
    pump(app, 8, 60)

    manager = page.manager
    manager._save_state = lambda: None          # 见上面说明：只改内存，不写盘

    agent = next((i for i in manager.plugins if i.id == AI_AGENT_PLUGIN_ID), None)
    maker = next((i for i in manager.plugins if i.id == MAKER_PLUGIN_ID), None)
    check(agent is not None and maker is not None,
          "插件页里应当有 GCP-AI Agent 和 插件制作辅助 这两个内置插件")
    if agent is None or maker is None:
        window.close()
        return

    # 起点统一成"两个都开着"（用户真实配置里可能是关的）
    for info in (agent, maker):
        if info.status != STATUS_OK:
            manager.set_enabled(info, True)
            manager.reload_plugin(info)
    page.refresh_list()
    pump(app, 8, 60)

    def card_of(info):
        for holder in list(getattr(page, "_cards", [])) + list(getattr(page, "_rows", [])):
            if getattr(holder, "info", None) is info:
                return holder
        return None

    start_card = card_of(agent)
    check(start_card is not None and bool(start_card.toggle_switch.isChecked()),
          "起点：Agent 那张卡片的开关是开着的",
          f"card={start_card is not None}")

    page._on_card_toggle(agent)
    pump(app, 12, 70)                           # 等它那个 240ms 的列表刷新

    check(maker.id in manager.disabled and maker.status == STATUS_DISABLED,
          "插件页关掉 Agent 之后，制作辅助在管理器里真的被停用了",
          f"disabled={sorted(manager.disabled)} status={maker.status}")
    maker_card = card_of(maker)
    check(maker_card is not None and not maker_card.toggle_switch.isChecked(),
          "制作辅助那张卡片的开关跟着变成关闭（界面没停留在旧状态）",
          f"card={maker_card is not None} "
          f"checked={maker_card.toggle_switch.isChecked() if maker_card else None}")
    window.close()


def main():
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])
    from qfluentwidgets import setTheme, Theme
    from pymodels.utils.theme_utils import apply_app_palette
    setTheme(Theme.LIGHT, lazy=False)
    apply_app_palette(False)

    check_rename()
    check_agent_cascade()
    check_home_hides_builtins(app)
    check_plugin_page_cascade(app)

    if FAILURES:
        print(f"\n[!!] {len(FAILURES)} 项失败")
        return 1
    print("\n[OK] 三项策略全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
