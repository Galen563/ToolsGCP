"""程序基本架构（插件入口）
ToolsGCP 加载插件时只认这一件事：create_page(context) -> 返回一个 QWidget。
目录分工（拆不拆由你）：
    app.py            ← 你在这里：装配各模块，产出页面
    core/config.py      插件自己的配置读写
    core/i18n.py        多语言
    core/logic.py       功能与逻辑算法
    ui/sidebar.py       左侧栏
    ui/page.py          专属界面
    lang/*.json         三种语言的文案
    assets/             图片等资源
"""

from PyQt5.QtWidgets import (
    QHBoxLayout, QStackedWidget, QWidget,
)

# 插件内的模块必须用相对导入：插件是当成独立包加载的，同名 core/ ui/ 不会互相覆盖
from .core.config import Config
from .core.i18n import I18n
from .core.logic import Logic
from .ui.page import HomePage, StatsPage
from .ui.sidebar import Sidebar


def create_page(context):
    """插件入口：返回插件页面
    context 是 ToolsGCP 给的上下文，常用成员：
        context.name / version / author   插件信息
        context.plugin_dir                插件目录（放只读资源）
        context.data_dir                  可写目录（存插件数据）
        context.locale                    当前语言，zh_CN / zh_TW / en_US
        context.get_resources()           资源库 list[dict]
        context.log("消息")               写日志
    """
    context.log(f"插件启动，语言 {context.locale}")

    config = Config(context.data_dir)
    i18n = I18n(context.plugin_dir, context.locale)
    logic = Logic(context)

    root = PluginRoot(context, config, i18n, logic)
    return root


class PluginRoot(QWidget):
    """插件主界面：左侧栏 + 右侧内容区"""

    def __init__(self, context, config, i18n, logic):
        super().__init__()
        self.context = context
        self.config = config
        self.i18n = i18n
        self.logic = logic

        self.setObjectName(f"plugin_{context.id}")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar(i18n, self)
        layout.addWidget(self.sidebar)

        self.stack = QStackedWidget(self)
        self.pages = {
            "home": HomePage(context, config, i18n, logic, self.stack),
            "stats": StatsPage(context, config, i18n, logic, self.stack),
        }
        for page in self.pages.values():
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)

        self.sidebar.currentChanged.connect(self.switch_to)
        self.switch_to("home")

    def switch_to(self, key: str):
        page = self.pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        page.on_show()
        self.context.log(f"切换到页面 {key}")
