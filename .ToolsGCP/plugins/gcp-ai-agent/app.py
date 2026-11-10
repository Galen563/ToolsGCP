"""GCP-AI Agent（插件入口）
ToolsGCP 加载插件时只认这一件事：create_page(context) -> 返回一个 QWidget。
内置插件：GCP-AI "长出双手"的开关面板 —— 看状态、开关 Agent、把一句想法转交给
GCP-AI。真正动手的是主程序里的 AgentBridge（ai/agent_runtime.py）：
    enabled()/set_enabled() 总开关 · tools() 有哪些手 · recent_actions()/clear_actions()
    动作流水 · stats() 调了多少次 · ask(text) 把一句话交给 AI 并发送
⚠️ context.ai_agent 可能是 None（主窗口还没建好），每次用都要判空。
"""

import traceback

from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

# 插件内的模块必须用相对导入：插件是当成独立包加载的，同名 core/ ui/ 不会互相覆盖
from .core.config import Config
from .core.i18n import I18n
from .ui.page import AgentPage


def create_page(context):
    """插件入口：返回插件页面
    context 是 ToolsGCP 给的上下文，这个插件用到的成员：
        context.id / name / version / author   插件信息
        context.plugin_dir                     插件目录（放只读资源）
        context.data_dir                       可写目录（存插件数据）
        context.locale                         当前语言，zh_CN / zh_TW / en_US
        context.ai_agent                       GCP-AI Agent 的运行时（可能是 None）
        context.log("消息")                    写日志
    ⚠️ 装配阶段（读语言文件、建配置对象）也可能出意外，那样就返回兜底页面并把
       堆栈写进日志 —— 绝不抛异常，插件卡片不该显示"加载失败"。
    """
    _log(context, f"GCP-AI Agent 插件启动，语言 {context.locale}")

    try:
        config = Config(context.data_dir)
        i18n = I18n(context.plugin_dir, context.locale)

        page = AgentPage(context, config, i18n)
        return page
    except Exception as exc:
        _log(context, f"插件装配失败: {exc}\n{traceback.format_exc()}", "err")
        return _fallback_page(context, exc)


def _fallback_page(context, error) -> QWidget:
    """兜底页面：装配失败时至少给用户一句人话；⚠️ 只用最朴素的 PyQt5 控件"""
    page = QWidget()
    try:
        page.setObjectName(f"plugin_{getattr(context, 'id', 'gcp-ai-agent')}")
    except Exception:
        pass
    try:
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(8)
        title = QLabel("GCP-AI Agent", page)
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
