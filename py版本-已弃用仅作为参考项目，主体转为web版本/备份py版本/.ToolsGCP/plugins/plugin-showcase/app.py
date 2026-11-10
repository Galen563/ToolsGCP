"""插件示例（plugin-showcase）

一个可以直接跑、也方便照着改的示例插件：放在 plugins/ 下自动被加载，出现在左侧栏
「插件」页和首页的「推荐插件」里。它演示了写插件的基本东西：

    入口约定：create_page(context) 返回一个 QWidget（本文件最后）；逻辑（Logic）与
    界面（CardPage）分开；读资源库 / 设置用 context.get_resources() /
    settings_manager.settings；数据只能写 context.data_dir（插件目录只读）、日志用
    context.log；文案读 lang/*.json；界面用 qfluentwidgets，和主程序观感一致。

改成你自己的：改 PLUGIN 的名字、把 Logic 换成你的算法、CardPage 换成你的界面。
"""

import json
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout,
                             QWidget)
from qfluentwidgets import (CaptionLabel, PushButton, SimpleCardWidget,
                            StrongBodyLabel, SubtitleLabel)

# 多语言回退顺序
I18N_FALLBACK = ("zh_CN", "en_US")


class I18n:
    """极简多语言：读插件目录下 lang/<locale>.json"""

    def __init__(self, plugin_dir: str, locale: str = "zh_CN"):
        self.dir = os.path.join(plugin_dir, "lang")
        self.locale = locale or "zh_CN"
        self._cache = {}

    def _load(self, locale: str) -> dict:
        if locale not in self._cache:
            path = os.path.join(self.dir, f"{locale}.json")
            data = {}
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8-sig") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            self._cache[locale] = data
        return self._cache[locale]

    def t(self, key: str, **kwargs) -> str:
        for locale in (self.locale,) + tuple(x for x in I18N_FALLBACK
                                            if x != self.locale):
            value = self._load(locale).get(key)
            if value:
                text = str(value)
                if kwargs:
                    try:
                        return text.format(**kwargs)
                    except Exception:
                        return text
                return text
        return key


def categories_of(item: dict) -> list:
    """取一条资源的类别列表（兼容两种形态）；⚠️ category 从 schema 2.1.0 起是列表"""
    value = (item or {}).get("category")
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [p.strip() for p in str(value or "").replace("，", ",").replace("、", ",")
            .replace("；", ",").replace(";", ",").split(",") if p.strip()]


class Logic:
    """业务逻辑（界面代码不要写算法，都放这里）"""

    def __init__(self, context):
        self.context = context

    def resources(self) -> list:
        """ToolsGCP 的资源库（list[dict]）"""
        return self.context.get_resources() or []

    def summary(self) -> dict:
        """资源库概况：总数 / 类别数 / 有官网的 / 有仓库的"""
        items = self.resources()
        return {
            "total": len(items),
            "categories": len({name for r in items for name in categories_of(r)}),
            "with_site": len([r for r in items if r.get("url")]),
            "with_repo": len([r for r in items if r.get("github")]),
        }

    def top_categories(self, limit: int = 6) -> list:
        """出现最多的几个类别，返回 [(类别, 数量), ...]"""
        counts = {}
        for item in self.resources():
            for name in categories_of(item):
                counts[name] = counts.get(name, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]

    def sample(self, limit: int = 5) -> list:
        """随便取几条，用来演示怎么把资源显示出来"""
        return self.resources()[:limit]


class KeyValueCard(SimpleCardWidget):
    """一行"标题：值"的小卡片（演示用，可删）"""

    def __init__(self, title: str, value: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addWidget(StrongBodyLabel(title, self))
        layout.addStretch()
        layout.addWidget(CaptionLabel(value, self))


class CardPage(QWidget):
    """插件主页面：把 context 能看到的东西都列出来（示例刻意做成信息展示）"""

    def __init__(self, context, i18n, logic, parent=None):
        super().__init__(parent)
        self.context = context
        self.i18n = i18n
        self.logic = logic

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(12)

        layout.addWidget(SubtitleLabel(self.i18n.t("title"), content))
        hint = CaptionLabel(self.i18n.t("hint"), content)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(6)

        # ---- 插件信息 ----
        for key, value in (
            ("info_id", context.id),
            ("info_version", context.version or "-"),
            ("info_author", context.author or "-"),
            ("info_locale", context.locale),
            ("info_data_dir", context.data_dir),
        ):
            layout.addWidget(KeyValueCard(self.i18n.t(key), str(value), content))

        # ---- 资源库概况（演示 get_resources）----
        summary = self.logic.summary()
        for key in ("res_total", "res_categories", "res_site", "res_repo"):
            layout.addWidget(KeyValueCard(self.i18n.t(key),
                                          str(summary.get(key.split("_", 1)[1], 0)),
                                          content))

        top = self.logic.top_categories()
        if top:
            text = "、".join(f"{name} {count}" for name, count in top)
            layout.addWidget(KeyValueCard(self.i18n.t("res_top"), text, content))

        # ---- 示例资源（演示怎么读一条资源的字段）----
        for item in self.logic.sample():
            name = str(item.get("name") or item.get("id") or "")
            desc = str(item.get("description") or "")
            code = str(item.get("code") or "")
            layout.addWidget(KeyValueCard(name, f"{code}  {desc}"[:60], content))

        # ---- 按钮：写一条自己的数据（演示 context.data_dir）----
        self.counter_label = CaptionLabel("", content)
        layout.addWidget(self.counter_label)

        self.click_btn = PushButton(self.i18n.t("click_me"), content)
        self.click_btn.clicked.connect(self._on_click)
        layout.addWidget(self.click_btn, 0, Qt.AlignLeft)

        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)

        self._refresh_counter()

    # ---------- 自己的数据 ----------
    def _config_path(self) -> str:
        """插件自己的数据只能写在 context.data_dir；⚠️ 插件目录是只读的、还会被覆盖"""
        return os.path.join(self.context.data_dir, "counter.json")

    def _read_counter(self) -> int:
        try:
            with open(self._config_path(), "r", encoding="utf-8") as f:
                return int(json.load(f).get("count", 0))
        except Exception:
            return 0

    def _write_counter(self, value: int):
        try:
            os.makedirs(self.context.data_dir, exist_ok=True)
            with open(self._config_path(), "w", encoding="utf-8") as f:
                json.dump({"count": int(value)}, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            self.context.log(f"写自己的数据失败: {exc}", level="err")

    def _refresh_counter(self):
        self.counter_label.setText(
            self.i18n.t("count_now", count=self._read_counter()))

    def _on_click(self):
        value = self._read_counter() + 1
        self._write_counter(value)
        self._refresh_counter()
        # 写日志：文件和终端都会输出，排查问题时很有用
        self.context.log(f"点了第 {value} 次")


def create_page(context):
    """插件入口（ToolsGCP 只认这一个函数）；必须返回一个 QWidget"""
    # 跟随 ToolsGCP 当前语言；插件只翻自己 lang/ 里的文案
    i18n = I18n(context.plugin_dir, context.locale)
    logic = Logic(context)
    context.log(f"插件示例已加载（语言 {context.locale}）")
    return CardPage(context, i18n, logic)
