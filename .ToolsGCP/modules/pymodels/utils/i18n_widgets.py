"""控件级的小型多语言补丁
qfluentwidgets 有一部分控件的内置文字是写死的（典型是 SwitchButton 上的 "On" / "Off"，
中文界面里也写着英文）。这里用应用级事件过滤器，在开关第一次显示时按当前语言补一次文字
—— 页面是按需懒建的，遍历一遍必然漏。
⚠️ 刻意设成空文字的开关（例如部署页那两个）不会被覆盖：只在 On/Off 还是库的默认值时才动手。
"""

from PyQt5.QtCore import QEvent, QObject

# SwitchButton 的默认文字（库写死的），用来判断"这个开关还没被我们接管"
_DEFAULT_TEXTS = (("On", "Off"), ("开", "关"), ("開", "關"))

# 语言文件缺失时的英文兜底
_FALLBACK = ("On", "Off")

_filter = None


def switch_texts() -> tuple:
    """当前语言下开关的 (开文字, 关文字)"""
    try:
        from ..core.language_manager import get_current_manager
        manager = get_current_manager()
        if manager is not None:
            on_text = manager.get_text("common", "switch_on_text")
            off_text = manager.get_text("common", "switch_off_text")
            if (on_text and off_text and on_text != "switch_on_text"
                    and off_text != "switch_off_text"):
                return str(on_text), str(off_text)
    except Exception:
        pass
    return _FALLBACK


def _on_text(switch) -> str:
    """读开关上的"开"文字
    ⚠️ `onText` 在这个版本的 qfluentwidgets 里是 **pyqtProperty**（属性）而不是方法 ——
       写成 `switch.onText()` 会抛 TypeError，被外层 try 吞掉后表现成"装了过滤器但一个
       开关都没改"。
    """
    value = getattr(switch, "onText", None)
    return str(value() if callable(value) else (value or ""))


def _off_text(switch) -> str:
    value = getattr(switch, "offText", None)
    return str(value() if callable(value) else (value or ""))


def apply_switch_text(switch):
    """把一个开关的文字换成当前语言（已经是目标文字就什么都不做）"""
    try:
        on_text, off_text = switch_texts()
        current = (_on_text(switch), _off_text(switch))
        if current == (on_text, off_text):
            return
        # 只接管"还带着默认文字"的开关：部署页那两个是故意留空的
        if current not in _DEFAULT_TEXTS:
            return
        switch.setOnText(on_text)
        switch.setOffText(off_text)
    except Exception:
        pass


class _SwitchTextFilter(QObject):
    """控件显示出来时补一次本地化文字"""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show:
            try:
                from qfluentwidgets import SwitchButton
                if isinstance(obj, SwitchButton):
                    apply_switch_text(obj)
            except Exception:
                pass
        return False


def install_switch_text_i18n(app):
    """装到 QApplication 上（重复调用无副作用）"""
    global _filter
    if app is None or _filter is not None:
        return _filter
    _filter = _SwitchTextFilter(app)
    app.installEventFilter(_filter)
    return _filter


__all__ = ["install_switch_text_i18n", "apply_switch_text", "switch_texts"]
