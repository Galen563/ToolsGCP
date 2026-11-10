"""插件制作辅助 —— 真正干活的那个模块
职责只有一件：把插件文件写进 `plugins/<id>/`（界面负责问参数、弹确认框）。一次生成
会写出 manifest.json / app.py / core/ / ui/ / lang/*.json / README*.md /
assets/icon.png，具体哪几项由 skill.py 的开关决定。
⚠️ 四条安全底线：
1) **只在这个插件自己的文件夹里写**：所有写操作都要经过 `_join()`，越界直接拒绝。
2) **id 先验证再落盘**：正则 + 保留名黑名单（见 validate_id）。
3) **已存在的文件夹不许悄悄覆盖**：返回 `exists=True`，界面确认后才传 `overwrite=True`；
   覆盖时只补自己那几项文件，不删用户加的。
4) **异常不逃逸**：公开函数只返回 Result / 元组，绝不抛给调用方。
⚠️ 生成的代码是**文本模板**，用 `{{token}}` 占位再替换（不用 str.format）：目标文件里
   有大量 `{}`（JSON、f-string、dict），format 会把它们当占位符。
"""

import json
import os
import re
import shutil

from . import skill

# 插件 id 的合法格式（和宿主 plugin_manager 的算法一致）
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-_]{1,40}$")

RESERVED_IDS = {
    "_template", "plugin-showcase",       # 官方模板 / 示例
    "plugins", "gcp-plugin-maker",        # 目录名 / 自己（不许自己覆盖自己）
}

MANIFEST_NAME = "manifest.json"

TOKEN_PLUGIN_ID = "{{plugin_id}}"
TOKEN_PLUGIN_NAME = "{{plugin_name}}"
TOKEN_PLUGIN_SLUG = "{{plugin_slug}}"
TOKEN_IDEA = "{{idea}}"
TOKEN_LANGUAGE = "{{language}}"
# ⚠️ manifest 里的来源标记：主程序靠它认出"制作器做出来的插件"，在 Agent 被关掉时
#    一起停用（见 core/plugin_manager.py 里 AGENT_PLUGIN_ID 附近那段）。
TOKEN_MAKER_ID = "{{maker_id}}"
MAKER_PLUGIN_ID = "gcp-plugin-maker"


class Result:
    """一次生成的结果（界面只读它，不读异常）"""

    def __init__(self):
        self.ok = False           # 最终是否成功（至少 manifest + app.py 写成功）
        self.exists = False       # 目标目录已存在，且这次**没有**被允许覆盖
        self.error = ""           # 失败的说明（已经是给用户看的一句话）
        self.folder = ""          # 目标插件目录（绝对路径）
        self.written = []         # 这次真正写/复制的文件（相对路径，正斜杠）
        self.skipped = []         # 因为已存在而跳过的文件（覆盖模式下）

    def summary(self) -> str:
        """一行摘要：成功写了几项、跳过了几项"""
        if self.error and not self.ok:
            return self.error
        text = f"written={len(self.written)} skipped={len(self.skipped)}"
        if self.error:
            text += f" warn={self.error}"
        return text


# ---------- 校验 ----------
def validate_id(plugin_id: str):
    """校验插件 id，返回 (是否合法, 给用户看的原因)；⚠️ 必须小写字母 + 数字开头"""
    value = str(plugin_id or "").strip()
    if not value:
        return False, "插件 id 不能为空"
    if not ID_PATTERN.match(value):
        return False, "插件 id 要用 2~41 位小写字母、数字、连字符或下划线，且以字母或数字开头"
    if value.lower() in RESERVED_IDS or value.startswith(("_", ".")):
        return False, f"{value} 是保留名字，换一个吧"
    return True, ""


def package_name(plugin_id: str) -> str:
    """插件文件夹名 → 宿主给它的 Python 包名（和 plugin_manager 的算法一致）"""
    return "toolsgcp_plugin_" + str(plugin_id or "").replace("-", "_").replace(".", "_")


def target_dir(plugins_dir: str, plugin_id: str) -> str:
    """目标插件目录（绝对路径）"""
    return os.path.join(str(plugins_dir or ""), str(plugin_id or ""))


# ---------- 路径安全 ----------
def _join(folder: str, *parts) -> str:
    """在插件目录里拼路径，并确认它没跑出插件目录；⚠️ 这是本模块的唯一出口"""
    root = os.path.abspath(folder)
    target = os.path.abspath(os.path.join(root, *[str(p) for p in parts]))
    if target != root and not target.startswith(root + os.sep):
        raise ValueError(f"路径越界，已拒绝：{target}")
    return target


def _write_text(folder: str, rel_path: str, text: str, result: Result,
                overwrite: bool) -> bool:
    """写一个文本文件（UTF-8）。已存在且不允许覆盖时记 skipped 并返回 False"""
    path = _join(folder, rel_path)
    if os.path.exists(path) and not overwrite:
        result.skipped.append(rel_path)
        return False
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    result.written.append(rel_path)
    return True


def _copy_icon(folder: str, template_dir: str, result: Result,
               overwrite: bool) -> bool:
    """把 _template 的图标复制成新插件的图标；⚠️ 找不到模板图标不算失败"""
    if not template_dir:
        return False
    source = os.path.join(str(template_dir), "assets", "icon.png")
    if not os.path.exists(source):
        return False
    path = _join(folder, "assets", "icon.png")
    if os.path.exists(path) and not overwrite:
        result.skipped.append("assets/icon.png")
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copyfile(source, path)
        result.written.append("assets/icon.png")
        return True
    except Exception:
        return False


# ---------- 生成模板（全部是纯文本，用 TOKEN_* 占位） ----------
# ⚠️ manifest 里的 config_page / enabled_setting / default_disabled 是 **Web 版真正读的字段**
#    （缺了前两个，插件在 Web 版里就是"列表里有、⚙ 是灰的、开关拨不动"的空壳）。
#    键名规则必须和 _template/config.html 一致：plugin_<id 里 - 换成 _>_enabled。
MANIFEST_TEMPLATE = """{
  "id": "{{plugin_id}}",
  "name": "{{plugin_name}}",
  "version": "1.0.0",
  "author": "ToolsGCP",
  "description": "{{idea}}",
  "entry": "app.py",
  "icon": "assets/icon.png",
  "config_page": "config.html",
  "enabled_setting": "plugin_{{plugin_slug}}_enabled",
  "default_disabled": true,
  "generated_by": "{{maker_id}}"
}
"""

APP_PY_TEMPLATE = '''"""
{{plugin_name}}（插件入口）
=========================

ToolsGCP 加载插件时只认这一件事：

    create_page(context)  ->  返回一个 QWidget

这个插件是「插件制作辅助」生成的骨架：**现在就能加载、能跑**，
你要做的是把 ui/page.py 里的内容换成真正的功能。

目录分工：
    app.py            你在这里：装配各模块，产出页面
    core/config.py    插件自己的配置读写（写在 context.data_dir 里）
    core/i18n.py      多语言
    ui/page.py        专属界面
    lang/*.json       三种语言的文案（键必须完全一致）
    assets/icon.png   插件图标（给插件卡片用）
"""

import traceback

from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

# 插件自己的模块一律用「相对导入」（插件是当成一个独立包加载的，
# 这样两个插件里同名的 core/ ui/ 不会互相覆盖）
from .core.config import Config
from .core.i18n import I18n
from .ui.page import MainPage


def create_page(context):
    """插件入口：返回插件页面

    context 是 ToolsGCP 给的上下文，常用成员：
        context.id / name / version / author   插件信息
        context.plugin_dir                     插件目录（放只读资源）
        context.data_dir                       可写目录（存插件数据）
        context.locale                         当前语言，zh_CN / zh_TW / en_US
        context.log("消息")                    写日志
    """
    _log(context, f"{context.name} 插件启动，语言 {context.locale}")

    try:
        # 1) 初始化基础模块：配置 / 多语言
        config = Config(context.data_dir)
        i18n = I18n(context.plugin_dir, context.locale)

        # 2) 组页面
        return MainPage(context, config, i18n)
    except Exception as exc:
        _log(context, f"插件装配失败: {exc}\\n{traceback.format_exc()}", "err")
        return _fallback_page(context, exc)


def _fallback_page(context, error) -> QWidget:
    """兜底页面：装配失败时至少给用户一句人话

    ⚠️ 只用最朴素的 PyQt5 控件（不碰 qfluentwidgets）：能走到这里说明
       环境可能已经有问题了，兜底页自己再失败就真没救了。
    """
    page = QWidget()
    try:
        page.setObjectName(f"plugin_{getattr(context, 'id', 'plugin')}")
    except Exception:
        pass
    try:
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(8)
        layout.addWidget(QLabel("{{plugin_name}}", page))
        detail = QLabel(f"Plugin failed to load / 插件加载失败: {error}", page)
        detail.setWordWrap(True)
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
'''

UI_PAGE_TEMPLATE = '''"""
{{plugin_name}} 的专属界面
=========================

这是**起始页面**：四张卡片，每一张都在演示一件"插件该怎么做"的事 ——

    1. 标题      —— 文案全部走 i18n（lang/*.json），界面里没有写死的句子
    2. 计数器    —— 用户操作写进插件自己的配置（context.data_dir，不是插件目录）
    3. 运行信息  —— 插件版本 / 当前语言 / 数据目录，排查问题时最有用
    4. 下一步    —— 把这里换成真正的功能；README.md 里写了怎么做

三条硬规矩（改代码时别破坏）：

    ⚠️ 一切用户可见的文字都走 i18n：i18n.t("key")。写死的中文/英文会让
       另外两种语言的用户看到乱码一样的界面。
    ⚠️ 异常不许逃出去：按钮回调 / refresh() / on_show() 里每一段都要 try 包住，
       插件把主程序带崩是不可接受的。
    ⚠️ 插件自己的数据只写 context.data_dir（可写目录）；插件目录是只读的，
       往那里写东西在别人的机器上会直接失败。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, FluentIcon as FIF, PrimaryPushButton,
    SimpleCardWidget, StrongBodyLabel, SubtitleLabel,
)


class MainPage(QWidget):
    """插件主页面：一页到底，内容不多，滚动看就行"""

    def __init__(self, context, config, i18n, parent=None):
        super().__init__(parent)
        self.context = context
        self.config = config
        self.i18n = i18n

        # 界面上的控件引用先给 None：万一某张卡片没建起来，
        # refresh() 里也要能判空跳过，而不是 AttributeError。
        self.counter_label = None
        self.info_label = None

        try:
            # 和模板一致：objectName 带上插件 id，主题刷新时主程序靠它认页面
            self.setObjectName(f"plugin_{context.id}")
        except Exception:
            pass

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # 横向不滚动：文字一律按宽度换行（插件页里出现横向滚动条非常难看）
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)

        # 一张卡片建失败只丢它自己 —— 少一张卡片也比整个插件加载失败强
        for builder in (self._build_header, self._build_counter_card,
                        self._build_info_card, self._build_next_card):
            self._build_safely(builder, content, layout)

        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        # 第一次进来先把状态读一遍；宿主打开插件时还会再调 refresh() / on_show()
        self.refresh()

    # ==================================================================
    # 通用小工具
    # ==================================================================
    def _log(self, message: str, level: str = "info"):
        """写日志：日志本身出问题也不能影响界面"""
        try:
            self.context.log(str(message), level=level)
        except Exception:
            pass

    def _build_safely(self, builder, parent, layout):
        """建一张卡片：出错就记日志跳过，绝不让异常逃出去"""
        try:
            widget = builder(parent)
            if widget is not None:
                layout.addWidget(widget)
        except Exception as exc:
            self._log(f"构建卡片 {getattr(builder, '__name__', builder)} 失败: {exc}", "err")

    def _new_card(self, parent, title_key: str, desc_key: str = ""):
        """统一风格的卡片：标题 + 一句说明 + 由调用方往 layout 里塞内容"""
        card = SimpleCardWidget(parent)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(8)
        layout.addWidget(StrongBodyLabel(self.i18n.t(title_key), card))
        if desc_key:
            desc = CaptionLabel(self.i18n.t(desc_key), card)
            desc.setWordWrap(True)
            layout.addWidget(desc)
        return card, layout

    @staticmethod
    def _body(parent, text: str):
        """一段可换行、可选中复制的正文"""
        label = BodyLabel(str(text or ""), parent)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    # ==================================================================
    # 卡片
    # ==================================================================
    def _build_header(self, parent):
        box = QWidget(parent)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(SubtitleLabel(self.i18n.t("title"), box))
        intro = BodyLabel(self.i18n.t("intro"), box)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        return box

    def _build_counter_card(self, parent):
        card, layout = self._new_card(parent, "sec_counter", "sec_counter_desc")

        row = QHBoxLayout()
        row.setSpacing(8)
        button = PrimaryPushButton(self.i18n.t("btn_count"), card, FIF.ADD)
        button.clicked.connect(self._on_count)
        row.addWidget(button)

        self.counter_label = CaptionLabel("", card)
        self.counter_label.setWordWrap(True)
        row.addWidget(self.counter_label, 1)
        layout.addLayout(row)
        return card

    def _build_info_card(self, parent):
        card, layout = self._new_card(parent, "sec_info")
        self.info_label = CaptionLabel("", card)
        self.info_label.setWordWrap(True)
        # 允许选中复制：用户反馈问题时要能把这行直接贴出来
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.info_label)
        return card

    def _build_next_card(self, parent):
        card, layout = self._new_card(parent, "sec_next", "sec_next_desc")
        layout.addWidget(self._body(card, self.i18n.t("next_body")))
        return card

    # ==================================================================
    # 行为
    # ==================================================================
    def _on_count(self):
        """点一下计数 +1，并写进插件自己的配置里（关掉程序也还在）"""
        try:
            times = self.config.bump("clicks")
        except Exception as exc:
            # ⚠️ 配置文件可能被手改坏了（存了"三"而不是 3）：int() 会抛。
            #    这种小事绝不能让界面崩，记日志 + 给一句提示就够了。
            self._log(f"计数失败: {exc}", "err")
            return
        self._refresh_counter(times)

    def _refresh_counter(self, times=None):
        if self.counter_label is None:
            return
        try:
            if times is None:
                times = int(self.config.get("clicks", 0) or 0)
            self.counter_label.setText(self.i18n.t("count_line", n=int(times)))
        except Exception as exc:
            self._log(f"更新计数失败: {exc}", "err")

    def _refresh_info(self):
        if self.info_label is None:
            return
        try:
            self.info_label.setText(self.i18n.t(
                "info_line",
                version=str(getattr(self.context, "version", "") or ""),
                locale=str(getattr(self.context, "locale", "") or ""),
                data_dir=str(getattr(self.context, "data_dir", "") or "")))
        except Exception as exc:
            self._log(f"更新运行信息失败: {exc}", "err")

    # ==================================================================
    # 对外钩子
    # ==================================================================
    def refresh(self):
        """重新读一遍页面上的数据

        宿主打开插件时会按 on_show → refresh 的顺序找钩子并调用，所以这里就是
        "页面被切过来时"要做的全部事情。

        ⚠️ 逐个 try：某一块读失败只让那一块空着，异常绝不能逃给宿主。
        """
        for name, fn in (("counter", self._refresh_counter),
                         ("info", self._refresh_info)):
            try:
                fn()
            except Exception as exc:
                self._log(f"刷新 {name} 失败: {exc}", "err")

    # 宿主是按 ("on_show", "refresh", "refresh_theme") 的顺序找**第一个**能调的钩子，
    # 所以直接把 refresh 注册成 on_show：两种叫法都指向同一次刷新。
    on_show = refresh
'''

# ---------- 生成出来的 config.html（Web 版唯一真正会加载的部分） ----------
# ⚠️ 为什么 py 版骨架之外还要多这一个文件：Web 版主线程**不许** import PyQt5
#    （AGENTS.md 第 8 节），插件的 app.py / ui/page.py 在 Web 版里永远不会被执行。
#    Web 版只认 manifest 的 `config_page`（iframe 打开）+ `enabled_setting`（开关写哪个设置键）。
#    以前生成的骨架缺这两样，"用 AI 做的插件"和"抄 _template 做的插件"一样是空壳。
# ⚠️ 占位符只有那六个 TOKEN_*（plugin_id / plugin_name / plugin_slug / idea /
#    language / maker_id），替换走字符串 replace 而不是 str.format —— 所以 JS 里
#    普通的 `{}`（对象字面量等）不受影响，但若将来有人改成 format，那些花括号会炸。
#    因此新增占位符时，务必同时改 _render() 和这里，并且别在 JS 里造新的 `{{…}}`。
CONFIG_HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{plugin_name}} · 配置</title>
<!--  {{plugin_name}}（{{plugin_id}}）的配置界面 —— Web 版真正加载的就是这一页。
      ⚠️ 三条规矩：不依赖主程序 CSS/JS、不联网、无构建；数据只走宿主
         window.pywebview.api.settings.get/set；主题由宿主 postMessage 推。-->
<script>
  /* 首帧主题：优先跟父文档已解析好的 data-theme（主程序 applyAppearance 写的）。
     ⚠️ 不能只信本页 matchMedia：主程序强制深色而系统浅色时两者相反，首帧会白一下。 */
  (function () {
    var theme = '';
    try {
      var host = window.parent && window.parent !== window ? window.parent : null;
      if (host && host.document && host.document.documentElement) {
        var attr = host.document.documentElement.getAttribute('data-theme');
        if (attr === 'dark' || attr === 'light') theme = attr;
      }
    } catch (e) { /* 跨源：忽略 */ }
    if (!theme) {
      var dark = true;
      try {
        if (window.matchMedia) dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      } catch (e) { dark = true; }
      theme = dark ? 'dark' : 'light';
    }
    document.documentElement.setAttribute('data-theme', theme);
  })();
</script>
<style>
  :root { color-scheme: dark; }
  html[data-theme="light"] { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 22px 24px 28px; font-size: 13px; line-height: 1.7;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", system-ui, sans-serif;
    background: var(--page); color: var(--text);
  }
  html[data-theme="dark"] {
    --page: #1c1c1c; --card: #26262a; --border: #35353b;
    --text: #eaeaea; --text2: #a8a8b0; --accent: #4cc46a;
  }
  html[data-theme="light"] {
    --page: #f3f4f7; --card: #ffffff; --border: #e6e9f0;
    --text: #1f2329; --text2: #6b7280; --accent: #2fa36b;
  }
  h1 { margin: 0 0 4px; font-size: 16px; }
  .sub { margin: 0 0 18px; color: var(--text2); font-size: 12px; }
  .card { background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: 14px 16px; margin-bottom: 12px; }
  .row { display: flex; align-items: center; gap: 12px; }
  .label { flex: 1 1 auto; }
  .tip { color: var(--text2); font-size: 11.5px; margin-top: 2px; }
  .kv { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 4px 14px; }
  .kv dt { color: var(--text2); }
  .kv dd { margin: 0; word-break: break-all; }
  .switch { flex: 0 0 auto; width: 44px; height: 22px; padding: 0; border-radius: 11px;
    border: 1px solid var(--border); background: var(--page); position: relative;
    cursor: pointer; transition: background 140ms ease, border-color 140ms ease; }
  .switch.is-on { background: var(--accent); border-color: var(--accent); }
  .switch-knob { position: absolute; top: 2px; left: 2px; width: 16px; height: 16px;
    border-radius: 50%; background: #fff; transition: transform 160ms cubic-bezier(.22,.8,.2,1); }
  .switch.is-on .switch-knob { transform: translateX(22px); }
  .btn { height: 30px; padding: 0 14px; border-radius: 6px; font-size: 12.5px;
    cursor: pointer; border: 1px solid var(--border); background: var(--card); color: var(--text); }
  .btn:hover { border-color: var(--accent); }
  .foot { display: flex; gap: 10px; margin-top: 16px; }
  .notice { display: none; margin-bottom: 14px; padding: 8px 12px; border-radius: 8px;
    background: rgba(224, 163, 58, .14); border: 1px solid rgba(224, 163, 58, .4); font-size: 12px; }
  .is-preview .notice { display: block; }
</style>
</head>
<body>
<div class="notice" data-i18n="cfg_preview_tip">预览模式：这一页被浏览器直接打开，拿不到桌面端接口，设置只读。</div>

<h1>{{plugin_name}}</h1>
<p class="sub">{{idea}}</p>

<div class="card">
  <div class="row">
    <div class="label">
      <div data-i18n="cfg_enable">启用本插件</div>
      <div class="tip" data-i18n="cfg_enable_tip">开关写进主程序设置（enabled_setting），关掉程序也保留</div>
    </div>
    <button class="switch" id="swOn" type="button" aria-checked="false"><span class="switch-knob"></span></button>
  </div>
</div>

<!--  把你的配置项加在这一块下面：每行一个 .card + .row，
      读写都走 save()（同一个 settings 域）；文案给个 data-i18n 键就能跟语言走。 -->
<div class="card">
  <dl class="kv">
    <dt data-i18n="cfg_meta_id">插件 id</dt><dd id="infoId">—</dd>
    <dt data-i18n="cfg_meta_version">版本</dt><dd id="infoVersion">—</dd>
    <dt data-i18n="cfg_meta_key">设置键</dt><dd id="infoKey">—</dd>
  </dl>
</div>

<div class="foot">
  <button class="btn" id="btnClose" type="button" data-i18n="cfg_back">返回插件列表</button>
</div>

<script>
  var PLUGIN_ID = '{{plugin_id}}';
  /* 必须和 manifest.enabled_setting 一致（那边是 plugin_{{plugin_slug}}_enabled） */
  var ENABLED_KEY = 'plugin_{{plugin_slug}}_enabled';
  var state = { api: null, manifest: {}, busy: false, locale: '简体中文', strings: {} };

  function $(id) { return document.getElementById(id); }

  /* ---------- 文案走 lang/*.json（缺 lang/ 时自动退回 HTML 里写的原话） ----------
     ⚠️ lang/ 目录是**可选项**（技能里的 three_languages 关掉就不生成），所以这里
        先抓一遍 DOM 里的兜底文案，再尝试拉语言文件：拉不到就一条都不改，
        界面仍然正常，绝不会显示成键名。 */
  var LOCALE_TO_FILE = { '简体中文': 'zh_CN', '繁體中文': 'zh_TW', 'English': 'en_US' };
  var i18nDefaults = {};

  function captureDefaults() {
    var nodes = document.querySelectorAll('[data-i18n]');
    for (var i = 0; i < nodes.length; i += 1) {
      var k = nodes[i].getAttribute('data-i18n');
      if (!(k in i18nDefaults)) i18nDefaults[k] = nodes[i].textContent;
    }
  }

  function loadStrings() {
    var file = LOCALE_TO_FILE[state.locale] || 'zh_CN';
    return fetch('lang/' + file + '.json', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .catch(function () { return {}; })
      .then(function (d) { state.strings = d || {}; });
  }

  function applyI18n() {
    var nodes = document.querySelectorAll('[data-i18n]');
    for (var i = 0; i < nodes.length; i += 1) {
      var k = nodes[i].getAttribute('data-i18n');
      var text = state.strings[k];
      if (text === undefined) text = i18nDefaults[k];
      if (text !== undefined) nodes[i].textContent = text;
    }
  }

  /* iframe 里没有 window.pywebview（pywebview 只往主框架注入）→ 回退 parent */
  function findApi() {
    try { if (window.pywebview && window.pywebview.api) return window.pywebview.api; } catch (e) {}
    try {
      var host = window.parent;
      if (host && host !== window && host.pywebview && host.pywebview.api) return host.pywebview.api;
    } catch (e) {}
    return null;
  }

  function waitForApi(timeoutMs) {
    var found = findApi();
    if (found) return Promise.resolve(found);
    return new Promise(function (resolve) {
      var done = false, timer = 0, timeout = 0;
      function cleanup() {
        try { window.removeEventListener('pywebviewready', check); } catch (e) {}
        if (timer) window.clearInterval(timer);
        if (timeout) window.clearTimeout(timeout);
      }
      function finish(v) { if (done) return; done = true; cleanup(); resolve(v || null); }
      function check() { var api = findApi(); if (api) finish(api); }
      try { window.addEventListener('pywebviewready', check); } catch (e) {}
      timer = window.setInterval(check, 120);
      timeout = window.setTimeout(function () { finish(findApi()); }, timeoutMs || 2500);
    });
  }

  /* 旧配置里可能是字符串 "false"，`!!` 会把它当"开" —— 必须这样归一化 */
  function settingOn(value) {
    if (value === true) return true;
    if (value === false || value === null || value === undefined) return false;
    if (typeof value === 'number') return value !== 0;
    if (typeof value === 'string') {
      return ['true', '1', 'yes', 'on'].indexOf(value.trim().toLowerCase()) >= 0;
    }
    return false;
  }

  function renderSwitch(on) {
    var el = $('swOn');
    if (on) el.classList.add('is-on'); else el.classList.remove('is-on');
    el.setAttribute('aria-checked', on ? 'true' : 'false');
  }

  async function loadAll() {
    try {
      var res = await fetch('manifest.json', { cache: 'no-store' });
      if (res.ok) state.manifest = await res.json();
    } catch (e) { /* 读不到就用默认值，不许整页空白 */ }
    $('infoId').textContent = state.manifest.id || PLUGIN_ID;
    $('infoVersion').textContent = state.manifest.version || '—';
    $('infoKey').textContent = state.manifest.enabled_setting || ENABLED_KEY;

    var key = state.manifest.enabled_setting || ENABLED_KEY;
    if (!state.api) { renderSwitch(!state.manifest.default_disabled); return; }
    try {
      var got = await state.api.settings.get(key);
      var value = (got && got.ok) ? got.value : undefined;
      if (value === undefined || value === null) value = !state.manifest.default_disabled;
      renderSwitch(settingOn(value));
    } catch (e) { renderSwitch(!state.manifest.default_disabled); }
  }

  async function save(next) {
    if (state.busy || !state.api) return;
    state.busy = true;
    renderSwitch(next);
    try {
      var key = state.manifest.enabled_setting || ENABLED_KEY;
      var res = await state.api.settings.set(key, next);
      if (!res || res.ok === false) throw new Error((res && res.error) || 'unknown');
    } catch (e) {
      renderSwitch(!next);   /* 写失败弹回去，别显示成"已生效"的假象 */
    } finally {
      state.busy = false;
    }
  }

  /* 宿主 → 插件页的主题同步协议（app.js 的 pluginThemePayload） */
  window.addEventListener('message', function (event) {
    var data = event && event.data;
    if (!data || data.type !== 'toolsgcp-theme') return;
    if (data.theme) document.documentElement.setAttribute('data-theme', data.theme);
    if (data.fx) document.documentElement.setAttribute('data-fx', data.fx);
    if (data.accent) document.documentElement.setAttribute('data-accent', data.accent);
    if (data.language && data.language !== state.locale) {
      state.locale = data.language;
      loadStrings().then(applyI18n);
    }
  });

  $('swOn').addEventListener('click', function () {
    save(!this.classList.contains('is-on'));
  });
  $('btnClose').addEventListener('click', function () {
    try {
      window.parent.postMessage({ type: 'toolsgcp-close-plugin', id: PLUGIN_ID }, '*');
    } catch (e) {}
  });

  waitForApi().then(function (api) {
    state.api = api;
    if (!api) document.documentElement.classList.add('is-preview');
    /* ⚠️ 顺序：先抓 HTML 里的兜底文案，再拉语言文件，最后才 loadAll 刷 DOM。
       反了的话兜底文案会被语言文件的内容覆盖掉，缺键时就显示成空白。 */
    captureDefaults();
    return loadStrings().then(applyI18n).then(loadAll);
  });
</script>
</body>
</html>
'''

# 生成出来的 lang/*.json（内容是 JSON 文本；{{plugin_name}} / {{idea}} 会被替换）
# ⚠️ 三个文件的键**必须完全一致** —— 改一个记得改三个。
LANG_BLUEPRINTS = {
    "zh_CN": """{
  "title": "{{plugin_name}}",
  "intro": "{{idea}}",

  "sec_counter": "试一试",
  "sec_counter_desc": "点一下按钮，计数会写进插件自己的配置里（存在 context.data_dir，关掉程序也还在）。",
  "btn_count": "点我 +1",
  "count_line": "你已经点了 {n} 次",

  "sec_info": "运行信息",
  "info_line": "版本 {version} · 当前语言 {locale} · 数据目录 {data_dir}",

  "sec_next": "下一步该改哪里",
  "sec_next_desc": "这个页面是骨架，真正的功能要你自己填。",
  "next_body": "打开 ui/page.py 把卡片换成你的功能；要写逻辑就新建 core/logic.py；文案改了记得三个语言文件一起改。",

  "cfg_enable": "启用本插件",
  "cfg_enable_tip": "开关写进主程序设置（enabled_setting），关掉程序也保留",
  "cfg_preview_tip": "预览模式：这一页被浏览器直接打开，拿不到桌面端接口，设置只读。",
  "cfg_back": "返回插件列表",
  "cfg_meta_id": "插件 id",
  "cfg_meta_version": "版本",
  "cfg_meta_key": "设置键"
}
""",
    "zh_TW": """{
  "title": "{{plugin_name}}",
  "intro": "{{idea}}",

  "sec_counter": "試一試",
  "sec_counter_desc": "按一下按鈕，計數會寫進外掛自己的設定裡（存在 context.data_dir，關掉程式也還在）。",
  "btn_count": "按我 +1",
  "count_line": "你已經按了 {n} 次",

  "sec_info": "執行資訊",
  "info_line": "版本 {version} · 目前語言 {locale} · 資料目錄 {data_dir}",

  "sec_next": "下一步該改哪裡",
  "sec_next_desc": "這個頁面是骨架，真正的功能要你自己填。",
  "next_body": "打開 ui/page.py 把卡片換成你的功能；要寫邏輯就新建 core/logic.py；文案改了記得三個語言檔一起改。",

  "cfg_enable": "啟用本外掛",
  "cfg_enable_tip": "開關寫進主程式設定（enabled_setting），關掉程式也保留",
  "cfg_preview_tip": "預覽模式：這頁被瀏覽器直接開啟，拿不到桌面端介面，設定唯讀。",
  "cfg_back": "返回外掛清單",
  "cfg_meta_id": "外掛 id",
  "cfg_meta_version": "版本",
  "cfg_meta_key": "設定鍵"
}
""",
    "en_US": """{
  "title": "{{plugin_name}}",
  "intro": "{{idea}}",

  "sec_counter": "Try it",
  "sec_counter_desc": "Press the button — the count is stored in this plugin's own config (context.data_dir), so it survives a restart.",
  "btn_count": "Click me +1",
  "count_line": "You have clicked {n} time(s)",

  "sec_info": "Runtime info",
  "info_line": "Version {version} · Language {locale} · Data folder {data_dir}",

  "sec_next": "What to change next",
  "sec_next_desc": "This page is a skeleton — the real feature is yours to write.",
  "next_body": "Open ui/page.py and replace the cards with your feature; put logic in a new core/logic.py; when you change a string, change all three language files.",

  "cfg_enable": "Enable this plugin",
  "cfg_enable_tip": "The switch writes into ToolsGCP settings (enabled_setting) and survives a restart",
  "cfg_preview_tip": "Preview mode: this page was opened directly in a browser, so the desktop API is unavailable and settings are read-only.",
  "cfg_back": "Back to plugin list",
  "cfg_meta_id": "Plugin id",
  "cfg_meta_version": "Version",
  "cfg_meta_key": "Settings key"
}
""",
}

# README 主文档
README_TEMPLATE = """# {{plugin_name}}

> ToolsGCP 插件 · id `{{plugin_id}}`

{{idea}}

## 核心功能

> ⚠️ 这一节是「插件制作辅助」生成的**占位说明**，请按真实功能改写：
> 用一段话讲清楚"这个插件解决什么问题"，再列几条用户能直接看到的能力。

- 在 ToolsGCP 的插件中心打开「{{plugin_name}}」即可使用。
- 目前是一个可运行的起始页面：点按钮计数（演示"插件自己的配置怎么存"）。
- 支持 <LANGUAGES> 三套界面语言，跟随 ToolsGCP 的界面语言自动切换。

## 安装与使用

这是**内置目录式插件**，不需要安装包，放到 `plugins/` 下就生效：

1. 确认插件目录存在：`<ToolsGCP>/plugins/{{plugin_id}}/`
2. 启动 ToolsGCP → 打开左侧「插件」（插件中心）。
3. 找到「{{plugin_name}}」这张卡片 → 点进去即是配置/功能界面。
4. 想关掉：插件卡片上的开关，或右键菜单里的启用/停用。

本插件由「插件制作辅助」直接写入本机 `plugins/` 目录，因此**首次出现在列表里
不需要重启**；如果你手动拷贝进来，重启一次程序即可。

## 目录结构

```
plugins/{{plugin_id}}/
├── manifest.json       插件元信息（id / name / description / version / author / entry / icon）
├── app.py              入口：create_page(context) → QWidget
├── core/
│   ├── __init__.py
│   ├── config.py       插件自己的配置读写（JSON，落在 context.data_dir）
│   └── i18n.py         多语言（lang/*.json，回退顺序 zh_CN → en_US）
├── ui/
│   ├── __init__.py
│   └── page.py         界面：一页到底，四张卡片
├── lang/
<LANG_TREE>
├── assets/
│   └── icon.png        插件图标（插件卡片用）
└── README.md           本文件
```

## 配置项

放在 ToolsGCP 的设置里（`.ToolsGCP/config/toolsgcp_config.json`），键名都以本插件 id 开头：

| 配置 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `{{plugin_slug}}_clicks` | int | 0 | 起始页的点击计数，用来演示"插件自己的数据存哪" |

插件自己的运行数据存在 `.ToolsGCP/config/plugin_data/{{plugin_id}}/config.json`
（即宿主给的 `context.data_dir`）——
⚠️ 插件目录本身可能不可写，**任何运行时数据都不要往插件目录里写**。

## 常见坑

- **界面文案写死在代码里**：三种语言的用户里会有人看到一半中文一半英文。
  所有用户可见的字都必须走 `i18n.t("key")`。
- **三个语言文件的 key 对不上**：少翻译一句没关系（会回退到 zh_CN），
  但 key 拼错、缺失就会直接显示成 key 本身。
- **异常逃出按钮回调**：一个没包住的异常就能把主程序面板带崩。
  按钮回调 / `refresh()` / `on_show()` 里一律 try 住。
- **往插件目录写文件**：在别人机器上（只读安装目录）会直接失败，
  运行时数据请写 `context.data_dir`。
- **模块导入用绝对路径**：插件是被当成独立包加载的，插件内部必须用相对导入
  （`from .core.config import Config`），否则会互相串味。
- **`context.ai_agent` 可能是 `None`**（主窗口还没建好）：每次用之前都要判空。

## 二次开发指引

1. **改界面**：编辑 `ui/page.py`。想要多页/侧边栏，可以参考
   `plugins/_template/ui/sidebar.py` 用 `QStackedWidget` 切换。
2. **加逻辑**：新建 `core/logic.py`，把计算和数据处理放进函数，
   界面只负责显示和收集输入（`ui/page.py` 里的注释就是这么分工的）。
3. **加文案**：三个 `lang/*.json` 一起加同样的 key，`zh_CN` 是兜底语言。
4. **加配置**：`core/config.py` 是极简 JSON 读写，
   `config.get(key, default)` / `config.set(key, value)` / `config.bump(key)` 够用了。
5. **用宿主能力**：`context` 上还有
   `get_resources()`（资源库）、`register_ai_tool()`（给 GCP-AI 加一只手）、
   `log()`（写日志）、`open_plugin_config(id)`（跳到别的插件配置页）等。
6. **调试**：改完 `app.py` 后回插件中心停用再启用即可重载；
   日志在 ToolsGCP 的日志页里，`context.log()` 写的内容会带上插件名。

## 许可

随 ToolsGCP 本体一起分发；二次开发请保留本文件与出处说明。
"""

# 额外语言的 README（默认不生成，开关在 Skill 技能里）
README_ZH_TW_TEMPLATE = """# {{plugin_name}}

> ToolsGCP 外掛 · id `{{plugin_id}}`

{{idea}}

## 核心功能

> ⚠️ 這一節是「外掛製作輔助」產生的**佔位說明**，請依真實功能改寫。

- 在 ToolsGCP 的外掛中心打開「{{plugin_name}}」即可使用。
- 目前是可執行的起始頁面：按鈕計數（示範外掛自己的設定怎麼存）。
- 支援 <LANGUAGES> 三套介面語言，跟隨 ToolsGCP 的介面語言自動切換。

## 安裝與使用

1. 確認外掛目錄存在：`<ToolsGCP>/plugins/{{plugin_id}}/`
2. 啟動 ToolsGCP → 左側「外掛」。
3. 找到「{{plugin_name}}」卡片 → 點進去就是設定／功能介面。
4. 想關掉：卡片上的開關，或右鍵選單的啟用／停用。

## 目錄結構

```
plugins/{{plugin_id}}/
├── manifest.json       外掛資訊
├── app.py              入口：create_page(context) → QWidget
├── core/               設定（config.py）與多語言（i18n.py）
├── ui/                 介面（page.py）
├── lang/               簡體中文 / 繁體中文 / English 文案
├── assets/icon.png     圖示
└── README.md           簡體中文說明（本檔為繁體中文版）
```

## 設定項

| 設定 | 型別 | 預設 | 說明 |
| --- | --- | --- | --- |
| `{{plugin_slug}}_clicks` | int | 0 | 起始頁的點擊計數 |

執行資料存在 `.ToolsGCP/config/plugin_data/{{plugin_id}}/config.json`（`context.data_dir`），
⚠️ 不要往外掛目錄寫執行資料。

## 常見坑

- 介面文字寫死在程式碼裡 → 其他語言的教學會缺字；一律走 `i18n.t("key")`。
- 三個語言檔的 key 對不上 → 顯示成 key 本身；少翻譯可以，key 不能缺。
- 例外逃出按鈕回呼 → 會把主面板帶崩；一律 try 住。
- 外掛內部匯入要用相對匯入（`from .core.config import Config`）。

## 二次開發指引

1. 改介面：`ui/page.py`。
2. 加邏輯：新建 `core/logic.py`，介面只負責顯示與收集輸入。
3. 加文案：三個 `lang/*.json` 一起加同樣的 key。
4. 用宿主能力：`context.get_resources()` / `register_ai_tool()` / `log()`。

## 授權

隨 ToolsGCP 本體一起散布；二次開發請保留本檔與出處說明。
"""

README_EN_TEMPLATE = """# {{plugin_name}}

> A ToolsGCP plugin · id `{{plugin_id}}`

{{idea}}

## What it does

> ⚠️ This section is a **placeholder** written by the Plugin Maker Helper — replace it with
> a description of the real feature.

- Open “{{plugin_name}}” from the ToolsGCP plugin center.
- Right now it is a runnable starter page: a button that counts (it demonstrates
  where a plugin keeps its own data).
- Ships with <LANGUAGES> UI languages and follows the ToolsGCP interface language.

## Install & use

1. Make sure the folder exists: `<ToolsGCP>/plugins/{{plugin_id}}/`
2. Start ToolsGCP and open “Plugins” in the left sidebar.
3. Find the “{{plugin_name}}” card and open it — that page *is* the plugin UI.
4. To turn it off, use the switch on the card (or the context menu).

## Layout

```
plugins/{{plugin_id}}/
├── manifest.json       plugin metadata
├── app.py              entry point: create_page(context) -> QWidget
├── core/               config.py (settings) and i18n.py (languages)
├── ui/                 page.py (the interface)
├── lang/               Simplified Chinese / Traditional Chinese / English strings
├── assets/icon.png     plugin icon
└── README.md           Simplified-Chinese documentation (this file is the English one)
```

## Settings

| Setting | Type | Default | Meaning |
| --- | --- | --- | --- |
| `{{plugin_slug}}_clicks` | int | 0 | Click counter used by the starter page |

Runtime data lives in `.ToolsGCP/config/plugin_data/{{plugin_id}}/config.json`
(the host-provided `context.data_dir`). ⚠️ Never write runtime data into the
plugin folder itself — it may be read-only.

## Pitfalls

- Hard-coded UI strings → other languages see a half-translated page. Always use `i18n.t("key")`.
- The three `lang/*.json` files must share the exact same key set (a missing
  translation falls back to zh_CN; a missing *key* shows the key itself).
- An exception escaping a button callback can take the host panel down — wrap everything.
- Inside a plugin, always import with relative paths (`from .core.config import Config`).

## Hacking on it

1. Edit the UI in `ui/page.py`.
2. Put logic in a new `core/logic.py`; the page only displays and collects input.
3. Add strings to all three `lang/*.json` files at once.
4. Host capabilities: `context.get_resources()`, `register_ai_tool()`, `log()`.

## License

Distributed with ToolsGCP itself; keep this file and its attribution when you fork it.
"""

# 写文件的目标名字 → README 模板
README_FILES = {
    "README.md": README_TEMPLATE,
    "README.zh_TW.md": README_ZH_TW_TEMPLATE,
    "README.en_US.md": README_EN_TEMPLATE,
}


# ---------- 组装 ----------
def _clean_idea(idea: str) -> str:
    """把用户输入的想法压成一行，给 manifest / README 的简介用
    ⚠️ 换行会在 JSON 里变成 \\n、在 Markdown 引用里会把后面几行顶出引用块，
       所以这里统一压成一行并限长。
    """
    text = " ".join(str(idea or "").split())
    if not text:
        return "由「插件制作辅助」生成的 ToolsGCP 插件。"
    return text[:200]


def _render(template: str, plugin_id: str, plugin_name: str, idea: str,
            language: str) -> str:
    """把模板里的 token 换成真实值（顺序无所谓，token 之间不会互相包含）"""
    return (template
            .replace(TOKEN_PLUGIN_ID, plugin_id)
            .replace(TOKEN_PLUGIN_SLUG, plugin_id.replace("-", "_"))
            .replace(TOKEN_PLUGIN_NAME, plugin_name)
            .replace(TOKEN_IDEA, idea)
            .replace(TOKEN_LANGUAGE, language)
            .replace(TOKEN_MAKER_ID, MAKER_PLUGIN_ID))


def _lang_languages_text(options: dict) -> str:
    """README 里那句"支持哪三种语言"（开关关掉时给一句兼容说法）"""
    if skill.normalize(options)["three_languages"]:
        return "简体中文 / 繁體中文 / English"
    return "简体中文"


def _lang_tree_text(options: dict) -> str:
    """README 目录结构里的 lang/ 子树"""
    if skill.normalize(options)["three_languages"]:
        return ("│   ├── zh_CN.json      简体中文（兜底语言）\n"
                "│   ├── zh_TW.json      繁體中文\n"
                "│   └── en_US.json      English")
    return "│   └── zh_CN.json      简体中文"


def plan_files(options: dict) -> list:
    """这次会写出哪些文件（界面上的"将生成"预览用它）；⚠️ 必须和 generate() 写的一致"""
    options = skill.normalize(options)
    files = [
        "manifest.json",
        "app.py",
        # ⚠️ Web 版唯一真正加载的就是这个文件（manifest 的 config_page 指向它），
        #    所以它和 app.py 一样是**必出项**，不受 any 开关影响。
        "config.html",
        "core/__init__.py",
        "core/config.py",
        "core/i18n.py",
        "ui/__init__.py",
        "ui/page.py",
        "assets/icon.png",
    ]
    if options["three_languages"]:
        files += [f"lang/{locale}.json" for locale in skill.ALL_LOCALES]
    if options["require_readme"]:
        files.append("README.md")
        files += skill.readme_extra_files(options)
    return files


def generate(context, plugin_id: str, plugin_name: str, idea: str, language: str,
             options: dict, overwrite: bool = False,
             plugins_dir: str = None, template_dir: str = None) -> Result:
    """把插件骨架写进 `plugins/<plugin_id>/`
    context 只用来读默认目录 / 写日志（判空也行）；plugin_id 会先过 validate_id；
    plugin_name 为空就用 id 顶上；options 见 core/skill.py；overwrite=True 表示目标目录
    已存在也照写（只覆盖自己的那几项文件）；plugins_dir / template_dir 是显式指定目录
    （测试用，不传就从 context / 自己身上找）。
    返回 Result —— **绝不抛异常**。
    """
    result = Result()
    try:
        options = skill.normalize(options)
        plugin_id = str(plugin_id or "").strip()
        plugin_name = str(plugin_name or "").strip() or plugin_id
        language = str(language or "").strip() or "Python"
        idea = _clean_idea(idea)

        # 1) 校验 id：不合法就到此为止，一个字节都不写
        valid, reason = validate_id(plugin_id)
        if not valid:
            result.error = reason
            return result

        root = plugins_dir or _default_plugins_dir(context)
        if not root:
            result.error = "拿不到 plugins 目录，无法生成插件"
            return result
        folder = target_dir(root, plugin_id)
        result.folder = folder

        # 3) 已存在且没被允许覆盖：原样返回，由界面去问用户
        if os.path.exists(folder) and not overwrite:
            result.exists = True
            result.error = f"plugins/{plugin_id}/ 已经存在了"
            return result

        os.makedirs(folder, exist_ok=True)

        # 覆盖模式下只补写自己那几项，**不删**用户后来加的文件
        _write_text(folder, MANIFEST_NAME,
                    _render(MANIFEST_TEMPLATE, plugin_id, plugin_name, idea, language),
                    result, overwrite)
        _write_text(folder, "app.py",
                    _render(APP_PY_TEMPLATE, plugin_id, plugin_name, idea, language),
                    result, overwrite)
        # ⚠️ config.html 必须和 plan_files 里那条一一对应（界面上的"将生成"预览用的就是它）
        _write_text(folder, "config.html",
                    _render(CONFIG_HTML_TEMPLATE, plugin_id, plugin_name, idea, language),
                    result, overwrite)
        _write_text(folder, "core/__init__.py", '"""插件的 Python 模块包"""\n',
                    result, overwrite)
        _write_text(folder, "core/config.py", CORE_CONFIG_TEMPLATE,
                    result, overwrite)
        _write_text(folder, "core/i18n.py", CORE_I18N_TEMPLATE,
                    result, overwrite)
        _write_text(folder, "ui/__init__.py", '"""插件的界面模块包"""\n',
                    result, overwrite)
        _write_text(folder, "ui/page.py",
                    _render(UI_PAGE_TEMPLATE, plugin_id, plugin_name, idea, language),
                    result, overwrite)

        # 语言文件：只有开了 three_languages 才写
        if options["three_languages"]:
            for locale in skill.ALL_LOCALES:
                blueprint = LANG_BLUEPRINTS.get(locale)
                if not blueprint:
                    continue
                _write_text(folder, f"lang/{locale}.json",
                            _render(blueprint, plugin_id, plugin_name, idea, language),
                            result, overwrite)

        # README：主文档 + 按开关决定的额外语言版本
        if options["require_readme"]:
            readme_files = ["README.md"] + skill.readme_extra_files(options)
            for filename in readme_files:
                template = README_FILES.get(filename)
                if not template:
                    continue
                text = _render(template, plugin_id, plugin_name, idea, language)
                text = text.replace("<LANGUAGES>", _lang_languages_text(options))
                text = text.replace("<LANG_TREE>", _lang_tree_text(options))
                _write_text(folder, filename, text, result, overwrite)

        _copy_icon(folder, template_dir or _default_template_dir(context), result,
                   overwrite)

        # 5) 判定成败
        # "能加载"的最低要求：manifest.json + app.py 都真的写出去了
        wrote = set(result.written)
        if MANIFEST_NAME in wrote and "app.py" in wrote:
            result.ok = True
        elif os.path.exists(_join(folder, MANIFEST_NAME)) and \
                os.path.exists(_join(folder, "app.py")):
            # 覆盖模式下两样都已存在（都进了 skipped）：也算成立
            result.ok = True
        else:
            result.error = result.error or "关键文件没写成功"
        return result
    except Exception as exc:
        # ⚠️ 兜底：写盘过程中的任何意外（权限、磁盘满、路径被占）都在这里收口，
        #    绝不抛给界面 —— 界面上只要一句"失败：xxx"就够了。
        result.ok = False
        result.error = f"{type(exc).__name__}: {exc}"
        return result


# ---------- 目录位置（都判空：context 可能少属性，也可能整个是 None） ----------
def _default_plugins_dir(context) -> str:
    """优先用宿主给的 plugins_dir；拿不到就猜自己上一层的 plugins/"""
    try:
        root = getattr(context, "plugins_dir", None)
        if root:
            return str(root)
    except Exception:
        pass
    # 本文件在 <plugins>/gcp-plugin-maker/core/maker.py → 上溯三层就是 plugins/
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.dirname(os.path.dirname(here))
    except Exception:
        return ""


def _default_template_dir(context) -> str:
    """模板目录：plugins/_template（图标从它的 assets/ 里拿）"""
    try:
        root = getattr(context, "plugin_dir", None)
        if root:
            return os.path.join(os.path.dirname(os.path.abspath(str(root))), "_template")
    except Exception:
        pass
    root = _default_plugins_dir(context)
    return os.path.join(root, "_template") if root else ""


# ---------- 生成出来的 core/config.py 与 core/i18n.py（和 _template 保持一致） ----------
# ⚠️ 这两段是**目标插件**要用的代码，只有被写进新插件目录、再被那个插件 import 时
#    才起作用，所以里面刻意不引用本插件的任何东西。
CORE_CONFIG_TEMPLATE = '''"""
插件自己的配置读写
==================

存到 ToolsGCP 给的 data_dir（可写目录）里，不要往插件目录写东西。

用法：
    cfg = Config(context.data_dir)
    cfg.get("times", 0)
    cfg.set("times", 5)
"""

import json
import os


class Config:
    """极简 JSON 配置"""

    def __init__(self, data_dir: str, filename: str = "config.json"):
        self.path = os.path.join(data_dir, filename)
        self.data = {}
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8-sig") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}
        return self.data

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value):
        self.data[key] = value
        self.save()

    def bump(self, key: str, step: int = 1) -> int:
        """计数 +1，返回新值（示例：统计插件被打开过几次）

        ⚠️ 老配置文件被手改坏（存了"三"而不是 3）时 int() 会抛异常，
           调用方要自己 try —— 插件里绝不能让这种小事把界面刷崩。
        """
        value = int(self.get(key, 0)) + step
        self.set(key, value)
        return value
'''

CORE_I18N_TEMPLATE = '''"""
多语言系统
==========

跟着 ToolsGCP 的界面语言自动切换，插件不用自己判断。

文案放在 lang/ 下，一个语言一个文件：
    lang/zh_CN.json     简体中文
    lang/zh_TW.json     繁體中文
    lang/en_US.json     English

文件格式（平铺的键值对，简单好维护）：
    {
      "title": "我的插件",
      "hello": "你好，{name}！"
    }

用法：
    i18n = I18n(context.plugin_dir, context.locale)
    i18n.t("title")                  → 我的插件
    i18n.t("hello", name="小明")      → 你好，小明！

找不到当前语言的键时，会依次回退到 zh_CN → en_US → 键名本身，
所以少翻译几句也不会显示成空白。

⚠️ 三种语言的键**必须完全一致**：zh_CN 是兜底语言，
   某个键只在 zh_CN 里有的话，英文用户看到的就是中文。
"""

import json
import os

# 回退顺序：当前语言找不到就往这里面的语言找
FALLBACK_ORDER = ["zh_CN", "en_US"]


class I18n:
    """插件文案翻译器"""

    def __init__(self, plugin_dir: str, locale: str = "zh_CN", lang_dir: str = "lang"):
        self.lang_dir = os.path.join(plugin_dir, lang_dir)
        self.locale = locale or "zh_CN"
        self._cache = {}

    # ---------- 读取 ----------
    def _load(self, locale: str) -> dict:
        if locale in self._cache:
            return self._cache[locale]
        path = os.path.join(self.lang_dir, f"{locale}.json")
        data = {}
        if os.path.exists(path):
            try:
                # utf-8-sig：兼容记事本另存出来的带 BOM 文件
                with open(path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        self._cache[locale] = data
        return data

    def available_locales(self) -> list:
        """lang/ 目录里都有哪些语言"""
        if not os.path.isdir(self.lang_dir):
            return []
        return sorted(fn[:-5] for fn in os.listdir(self.lang_dir)
                      if fn.endswith(".json"))

    # ---------- 翻译 ----------
    def t(self, key: str, **kwargs) -> str:
        """取一条文案；带 {占位符} 的话用 kwargs 替换

        ⚠️ 只对**模板**做 format：填进去的值里就算带 {} 也不会再被解析一遍，
           所以工具说明、用户输入这类内容可以放心当参数传进来。
        """
        text = self._find(key)
        if kwargs and isinstance(text, str):
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text

    def _find(self, key: str) -> str:
        for locale in [self.locale] + [x for x in FALLBACK_ORDER if x != self.locale]:
            value = self._load(locale).get(key)
            if value:
                return str(value)
        return key

    def all(self) -> dict:
        """当前语言的完整文案表（想整体遍历时用）"""
        merged = {}
        for locale in reversed([self.locale] + FALLBACK_ORDER):
            merged.update(self._load(locale))
        return merged
'''
