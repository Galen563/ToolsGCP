"""插件制作辅助（插件入口）

ToolsGCP 加载插件时只认这一件事：create_page(context) -> 返回一个 QWidget。

内置插件，且**默认不开启**（manifest 里 "default_disabled": true）。配置界面只有开关
和下拉框 —— 用户要写的东西全部在 GCP-AI 的聊天框里说。它自己只做两件事：

    1) 落盘骨架 —— core/maker.py 把插件文件写进 plugins/<id>/
    2) 登记入口 —— 往宿主的聊天提示注册表登记 /plugin 悬浮提示 + 一段指令，再登记
                    create_plugin 这个 AI 工具；组装指令的 Skill 规则在 core/skill.py

⚠️ context.ai_agent 可能是 None，老宿主上 context.register_chat_hint /
   register_ai_tool 可能压根不存在 —— 插件必须自己判空/判存在（见 ui/page.py）。
"""

import traceback

from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

# 插件内的模块必须用相对导入：插件是当成独立包加载的，同名 core/ ui/ 不会互相覆盖
from .core.config import Config
from .core.i18n import I18n
from .ui.page import PluginMakerPage


def create_page(context):
    """插件入口：返回插件页面

    context 是 ToolsGCP 给的上下文，这个插件用到的成员：
        context.id / name / version / author   插件信息
        context.plugin_dir                     插件目录（放只读资源）
        context.data_dir                       可写目录（存插件数据）
        context.locale                         当前语言，zh_CN / zh_TW / en_US
        context.settings_manager               读/写设置（总开关和 Skill 规则都在这）
        context.plugins_dir                    新插件的落点（plugins/ 绝对路径）
        context.reload_plugins()               写完文件后让新插件立刻出现
        context.open_plugin_config(id)         跳到新插件的配置界面
        context.register_chat_hint(...)        登记 /plugin 悬浮提示（老宿主可能没有）
        context.register_ai_tool(...)          登记 create_plugin 工具（老宿主可能没有）
        context.ai_agent                       GCP-AI Agent 的运行时（可能是 None）
        context.log("消息")                    写日志

    ⚠️ 装配阶段（读语言文件、建配置对象）也可能出意外，那样就返回兜底页面并把
       堆栈写进日志 —— 绝不抛异常。
    """
    _log(context, f"插件制作辅助启动，语言 {context.locale}")

    try:
        config = Config(context.data_dir)
        i18n = I18n(context.plugin_dir, context.locale)

        page = PluginMakerPage(context, config, i18n)
        return page
    except Exception as exc:
        _log(context, f"插件装配失败: {exc}\n{traceback.format_exc()}", "err")
        return _fallback_page(context, exc)


def _fallback_page(context, error) -> QWidget:
    """兜底页面：装配失败时至少给用户一句人话；⚠️ 只用最朴素的 PyQt5 控件"""
    page = QWidget()
    try:
        page.setObjectName(f"plugin_{getattr(context, 'id', 'gcp-plugin-maker')}")
    except Exception:
        pass
    try:
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(8)
        title = QLabel("Plugin Maker Helper / 插件制作辅助", page)
        detail = QLabel(f"Plugin failed to load / 插件加载失败: {error}", page)
        detail.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(detail)
        layout.addStretch(1)
    except Exception:
        pass
    return page


def _log(context, message: str, level: str = "info"):
    """写日志：日志本身出问题也不能影响插件加载"""
    try:
        context.log(str(message), level=level)
    except Exception:
        pass
