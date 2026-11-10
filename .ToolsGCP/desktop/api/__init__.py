"""暴露给前端的门面（`window.pywebview.api`）。
========== 两条必须遵守的规则 ==========
1. pywebview 的 js_api 回调跑在**工作线程**（`webview/util.py:247` 明写 "executed in a
   separate thread"）。所以这里的每个方法都不能假设自己在 UI 线程上：
     · 窗口操作一律走 pywebview 自己的 `Window.show/hide/maximize/...`（内部 `Invoke` 到
       WinForms 线程，是线程安全的），或走我们自己的原生封装（Win32 的 SetWindowPos 等
       对跨线程调用是安全的）；
     · **绝对不要**在这层里直接操作 WebView 控件。
2. 返回值必须是 JSON 可序列化的普通 dict；异常必须自己接住并转成 `{"ok": False, "error": ...}`。
   一旦抛出去，前端拿到的会是 `Error` 对象，页面上只会看到一句 e.message —— 排查很痛苦。
========== 命名约定 ==========
前端统一 `await api.<域>.<方法>(...)`（pywebview 支持点号路径，见 util.py 的
`get_nested_attribute`）。基础域是 window / app / i18n / log / shell，
其余按 resources / favorites / downloader / plugins / ai 等域逐步挂上来。
"""

import json
import os
import sys
import threading
import time
import traceback

from pymodels.constants import (APP_NAME, APP_VERSION, APP_AUTHOR, CONFIG_DIR,
                                DATA_DIR, LANGUAGES_DIR, DEFAULT_SETTINGS)
# 语言名 → 语言目录名的**唯一**映射放在 pymodels 层（language_manager）：
# 这一层直接 import，别在这里再维护一份，两份写歪了前端就和后端取不到同一套文案。
from pymodels.core.language_manager import (DEFAULT_LOCALE, locale_for,
                                            normalize_language)

from ..native import frame, win32


def _ok(**kwargs):
    payload = {"ok": True}
    payload.update(kwargs)
    return payload


def _fail(message, **kwargs):
    payload = {"ok": False, "error": str(message or "unknown error")}
    payload.update(kwargs)
    return payload


def _log(level: str, category_zh: str, category_en: str, message: str):
    """所有输出都走原版日志器（格式不变：可 grep、带分类、OP 级记操作）"""
    try:
        from pymodels.utils.logger import log
        getattr(log, level, log.info)(category_zh, category_en, message)
    except Exception:
        pass


class AppDomain:
    """程序级信息 / 前端就绪上报"""

    def __init__(self, shell):
        self._shell = shell

    def info(self):
        """前端启动时拉一次：版本、是否首次启动、窗口初始尺寸等"""
        try:
            settings = self._shell.settings_manager
            theme = str(settings.settings.get("theme", "跟随系统")) if settings else "跟随系统"
            return _ok(app=APP_NAME, version=APP_VERSION, author=APP_AUTHOR,
                       theme=theme,
                       accent=str(settings.settings.get("accent_color", "blue"))
                       if settings else "blue",
                       language=str(settings.settings.get("language", "跟随系统"))
                       if settings else "跟随系统",
                       data_dir=DATA_DIR,
                       config_dir=CONFIG_DIR,
                       args=sys.argv[1:],
                       platform=sys.platform,
                       python=sys.version.split()[0],
                       startup_ts=self._shell.started_at)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def ready(self):
        """⚠️ 前端**首屏真的画完了**才调这个（Vue 的 mounted + nextTick 之后）
        这是原版 `ui_ready` 的等价物：启动流程要等"启动画面播完"和"前端就绪"两件事都完成，
        才把主窗口 show 出来（`ToolsGCP.pyw:189-213` 的 state/on_ui_ready 逻辑）。
        重复调用无副作用。
        """
        try:
            self._shell.mark_frontend_ready()
            return _ok()
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def heartbeat(self):
        """前端 60s 一次心跳：用来判断"界面还活着"，也顺带把运行时长记进日志"""
        try:
            return _ok(uptime=round(time.time() - self._shell.started_at, 1))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    # ---------- 隐私同意（落盘走 PrivacyState：json + 哈希，不是前端 localStorage） ----------
    def privacy_state(self):
        r"""读隐私同意状态
        ⚠️ 同意记录写在 `<当前数据根>/config/privacy_policy.json`（带哈希校验，和原版同一个
            文件、同一套算法）。默认数据根是 `<用户主目录>\.ToolsGCP`。
            早期 Web 版只写前端 localStorage，表现为"每次启动都要重新同意一次"，所以这里
            把落盘那套接回来：agreed 为 True 时前端不再弹窗。
        ⚠️ 用户删掉整个数据根后，这里必须返回 agreed=False（文件没了 = 没同意过）。
            path / exists 是**诊断字段**（只读，不改变 {ok, agreed, version, timestamp} 契约）：
            exists 是 load() 之前查的，所以 exists=False + agreed=False 就代表"从来没同意过
            或同意记录跟着数据根被删了"，排查日志一眼能看出来。
        """
        try:
            state = self._shell.privacy_manager
            if state is None:
                return _ok(agreed=False, reason="privacy state 未就绪",
                           path="", exists=False, root="")
            path = str(getattr(state, "path", "") or "")
            root = str(getattr(state, "data_root", "") or "")
            exists = bool(state.exists()) if hasattr(state, "exists") else (
                os.path.isfile(path) if path else False)
            data = state.load()
            agreed = bool(state.is_valid(data))
            _log("info", "隐私", "privacy",
                 f"同意状态检查 path={path} exists={exists} agreed={agreed}")
            if not agreed:
                _log("info", "隐私", "privacy",
                     "当前数据根没有有效的隐私同意记录，前端将重新弹出隐私政策"
                     "（删除数据根 / 首次启动 / consent 过期都属于这种情况）")
            return _ok(agreed=agreed,
                       version=str(data.get("consent_version") or ""),
                       timestamp=str(data.get("consent_timestamp") or ""),
                       path=path, exists=exists, root=root)
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "隐私", "privacy", f"读取同意状态失败: {exc}")
            return _fail(exc)

    def accept_privacy(self, version: str = "V1.0"):
        """记录用户同意（写 json + 哈希）"""
        try:
            state = self._shell.privacy_manager
            if state is None:
                return _fail("privacy state 未就绪")
            ok = state.record_consent()
            path = str(getattr(state, "path", "") or "")
            if ok:
                _log("op", "隐私", "privacy",
                     f"用户同意隐私政策（版本 {version}）path={path}")
            else:
                _log("warn", "隐私", "privacy", f"同意记录写盘失败 path={path}")
            return _ok(saved=bool(ok), path=path)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    # ⚠️ 原来的 privacy_text()（取用户协议/隐私政策**全文**）已删除：
    #    用户要求本地不再存长文，前端直接 openLink 跳官网
    #    （https://toolsgcp.pages.dev/user-agreement 与 https://toolsgcp.pages.dev/privacy）。
    #    同意状态检测仍走上面的 privacy_state()/accept_privacy()，不要一起删。

    def settings(self):
        """当前设置快照（前端只读；写请走 set_setting）"""
        try:
            manager = self._shell.settings_manager
            data = dict(manager.settings) if manager else dict(DEFAULT_SETTINGS)
            # 敏感项不下发前端
            # ⚠️ 走 logger.is_secret_key()（精确名 + 前缀族），别再写死那四个名字：
            #    API Key 早就按服务商分槽存成 api_key_enc_<pid>，精确清单会把它们
            #    **原样下发**（DPAPI 密文对同一用户可解，等于把 Key 交给前端）。
            from pymodels.utils.logger import is_secret_key
            for key in list(data.keys()):
                if is_secret_key(key):
                    data[key] = ""
            return _ok(settings=data)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def splash_remaining(self):
        """启动画面还剩多少毫秒（前端据此决定自己的 loading 遮罩什么时候撤）
        ⚠️ 返回 0 = 没有启动画面或已经播完。前端拿到 >0 的值时要**等够这么久**
            再显示主界面，否则"设了 5 秒却提前出现"。
        """
        try:
            return _ok(remaining=int(getattr(self._shell, "splash_remaining_ms", lambda: 0)()),
                       enabled=bool(getattr(self._shell, "_splash_enabled", False)))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def splash_wait(self, timeout: float = 30.0):
        """阻塞等启动画面播完（前端 ready 之前调；超时也返回，不会卡死启动）"""
        try:
            done = self._shell.wait_splash_done(float(timeout or 0))
            return _ok(done=bool(done))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)


class WindowDomain:
    """窗口控制（无边框窗口的标题栏按钮全走这里）"""

    def __init__(self, shell):
        self._shell = shell

    def _hwnd(self) -> int:
        return self._shell.hwnd()

    def state(self):
        try:
            data = dict(frame.window_state(self._hwnd()))
            # 全屏状态以 shell 那份为准：非 frameless 模式（系统标题栏）下
            # pywebview 的原生 toggle_fullscreen 不会回写 frame._state.fullscreen，
            # 而 F11 现在还有一条"原生 AcceleratorKeyPressed"的到达路径，
            # 只有 shell._fullscreen_state 是三条路径共同维护的唯一事实来源。
            data["fullscreen"] = bool(getattr(self._shell, "_fullscreen_state", False))
            return _ok(**data)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def start_drag(self, token=None):
        """自定义标题栏按下 → 交给系统拖动
        ⚠️ 必须把 `window` 一起交给 frame 层：只有它能让这条调用编组到 GUI 线程，
           否则 ReleaseCapture/SendMessage 都发在错误线程上，表现为"窗口拖不动"。
           见 frame.start_drag / frame.on_gui_thread 的说明。
        ⚠️ `token` 现在**必须收下**：前端每次按下都会传一个自增号。
           之前签名是 `start_drag(self)`，而前端已经改成
           `bridge.call('window.start_drag', token)` —— 参数对不上时 pywebview
           直接抛 TypeError，Promise 走 reject，前端那条 `.catch()` 会以为
           "原生通道不可用"，于是**每一次拖动都掉进兜底通道**（等于主路径永久失效，
           还顺手把用户报的抖动换了一种形态）。
           token 的作用是**让上一次还没送达的排队消息作废**（见 frame.start_drag）。
        """
        try:
            started = frame.start_drag(self._hwnd(), self._shell.window, token)
            return _ok(started=bool(started))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def drag_delta(self, dx: int = 0, dy: int = 0):
        """【已废弃，保留兼容】按增量移动窗口。
        ⚠️ 增量式**不能用于拖动**：js_api 异步 + 基线漂移 = 窗口乱跳
           （用户报的"往几个方向卡顿移动"就是这么来的）。
           拖动请走 `window.drag_start` / `drag_move` / `drag_end`。
        """
        try:
            return _ok(moved=frame.move_by(self._shell.window, int(dx or 0), int(dy or 0)))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def drag_start(self):
        """兜底拖动：记录起始窗口矩形 + 起始光标（都在后端取，物理像素）。
        ⚠️ 只在**原生拖动通道明确不可用时**才走这一套（见 WindowDomain.start_drag
           与前端 startDragFallback）。前端一个坐标都不传 ——
           `screenX/screenY` 是 CSS 像素，受 DPI 和页面 ZoomFactor 影响，
           拿它算窗口位置就是"越拖越偏"的来源。
        """
        try:
            return _ok(**frame.drag_start(self._shell.window))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def drag_move(self):
        """兜底拖动一帧：目标位置 = 起始矩形 + (当前光标 − 起始光标)。

        ⚠️ **幂等**是本方法存在的意义：同一次拖动里第 N 帧重复送达、
           或者第 3 帧比第 2 帧先到，落点都一样 —— 不会叠加、不会回跳。
           旧的 `drag_delta` 是"在当前值上累加"，一旦有两条在飞就必然错位。
        """
        try:
            return _ok(**frame.drag_step(self._shell.window))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def drag_end(self):
        """兜底拖动结束（前端 mouseup）：清掉会话基准"""
        try:
            return _ok(**frame.drag_end())
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def minimize(self):
        try:
            hwnd = self._hwnd()
            if hwnd:
                frame.minimize(hwnd)
            else:
                win = self._shell.window
                if win is not None:
                    win.minimize()
            return _ok()
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def toggle_maximize(self):
        try:
            maximized = frame.toggle_maximize(self._hwnd())
            return _ok(maximized=maximized)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def start_resize(self, direction: str = ""):
        """从前端窗口边缘热区启动系统原生缩放
        `direction` ∈ left/right/top/bottom/topleft/topright/bottomleft/bottomright。
        返回值只表示"请求已投递"；真正的缩放由系统模态循环完成（松手才结束）。
        ⚠️ 不阻塞：frame.start_resize 会另起线程编组到 GUI 线程，
           这里立刻返回，避免 js_api 工作线程被模态循环挂住。
        """
        try:
            ok = frame.start_resize(self._hwnd(), getattr(self._shell, "window", None),
                                   direction)
            if not ok:
                return _fail("无效的缩放方向: %s" % direction)
            return _ok(direction=str(direction))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def toggle_fullscreen(self):
        """F11 / 全屏按钮：进/出全屏（隐藏自绘标题栏由前端根据事件/返回值切）
        契约（前端 Lead 按这个改 app.js）：
            返回值 `{ok:true, fullscreen:bool, via:"framepos"|"pywebview"|"pywebview-fallback"}`
                  `{ok:false, error:"…", fullscreen:bool}`  ← 请求到了后端但没生效，**必须提示**
            事件   `window.fullscreen` payload `{fullscreen: bool, via: str}`
                   （成功时由 shell 推；前端若用返回值切状态，事件是双保险）
        ⚠️ 实现全部收在 `shell.toggle_fullscreen()`：F11 有三条到达路径
           （页面 keydown / 原生 AcceleratorKeyPressed / 按钮点击），只留一个实现才不会
           出现"某条路径行为不一样"。这里只做 JSON 信封 + 失败可读化。
        ⚠️ 必须校验 `frame.toggle_fullscreen(...)` 的返回值：不校验时窗口没动
           也照样返回 `{ok:true}`、日志只剩一条 op 级的"进入全屏"——
           现象就是"点了没反应、日志也没有"。失败要带上原因。
        """
        try:
            result = self._shell.toggle_fullscreen() or {}
            if result.get("ok"):
                return _ok(fullscreen=bool(result.get("fullscreen")),
                           via=str(result.get("via") or ""),
                           state=result.get("state") or {})
            return _fail(result.get("error") or "全屏切换失败",
                         fullscreen=bool(result.get("fullscreen")),
                         via=str(result.get("via") or ""),
                         state=result.get("state") or {})
        except Exception as exc:                          # noqa: BLE001
            _log("err", "窗口", "fullscreen", f"全屏切换异常: {exc}")
            return _fail(exc)

    def close(self, force: bool = False):
        """标题栏 × → 走和系统关闭完全相同的路径（closeEvent 里那套 close_mode 逻辑）
        ⚠️⚠️ **必须异步**（WebView2 ObjectDisposedException 最常见触发点）：
            pywebview 的 `js_bridge_call` 在 js_api 回调**返回之后**还要
            `window.evaluate_js(...)` 把结果送还 JS（webview/util.py:264）。
            若在这里同步 `request_close()`（发 WM_CLOSE → 窗口立刻销毁）再 `return _ok()`，
            那句 evaluate_js 就必然打在已释放的 WebView2 上 → 用户每点一次 × 都可能刷一段
            `System.ObjectDisposedException: 无法访问已释放的对象。"WebView2"`。
            所以：本方法立即返回，真正的关闭延迟到 `request_close_async` 里做。
        ⚠️ `force=True` = 前端已经弹过确认框并得到用户同意 —— 后端别再弹原生框。
        """
        try:
            self._shell.request_close_async(force=bool(force))
            return _ok(deferred=True)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def hide_to_tray(self):
        try:
            self._shell.hide_to_tray()
            return _ok()
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def show(self):
        """把主窗口呼出并置前
        ⚠️⚠️ 本轮修复用户报的「浏览器端打开 ToolsGCP 后，桌面端 ToolsGCP 又突然
           回到了所有窗口页面最顶端」：
           浏览器模式 = 桌面窗口**隐藏到托盘**、内容由浏览器页签提供。而前端
           `goto('home'/'search'/'ai')` 里带着 `bridge.tryCall('window.show')`
           （见 app.js 8607-8609），浏览器端那页一加载/一导航就调它 → 桌面窗口
           被"呼出 + 置前"，就是用户看到的"自己蹦到最上面"。
           → **浏览器模式隐藏期间，前端这一路不再掀窗口**（返回 skipped）。
           ⚠️ 用户**主动**呼出仍然有效：托盘双击、托盘右键「显示主窗口」、
              全局热键、单实例激活 —— 那些走 shell.show_window()/on_tray_*，
              不经过这里，且会清掉 _browser_mode_hidden 标记（见 shell.py）。
              这是用户本轮在选项里明确要的：「浏览器模式期间不要跳，
              但热键/托盘呼出时当然要跳到最前」。
        """
        try:
            if getattr(self._shell, "_browser_mode_hidden", False):
                return _ok(skipped=True, reason="browser_mode_hidden")
            self._shell.show_window()
            return _ok()
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def center(self):
        """把窗口摆回工作区居中（⚠️ 必须让 frame 层编组到 GUI 线程，见其注释）
        ⚠️「启动时最小化到托盘」生效时**必须跳过**：center 里的 resize/move 自带
           SWP_SHOWWINDOW，前端 ready 后那句 window.center 会把本应隐藏的窗口
           直接掀出来（= 开关又"不生效"了）。用户从托盘呼出走 shell.show_window()，
           那条路自己会居中。
        ⚠️⚠️ 线程：这是 **js_api 工作线程**调的（前端 bridge.tryCall('window.center')），
           不是 GUI 线程。而旧的 `frame.center_on_screen()` 内部调 pywebview 的
           `window.resize()/move()` —— 那两个方法**没有** Invoke 到 GUI 线程
           （platforms/winforms.py:600-643），会跨线程读写 WinForms 的托管属性
           （Form.Size / Form.Location），和真实矩形失配 → 窗口位置/尺寸"自己跑掉"。
           → 改用 `frame.force_center_on_screen()`：它走**原生** SetWindowPos
              且**自带** GUI 线程编组（on_gui_thread）。
        """
        try:
            if getattr(self._shell, "_startup_hidden", False):
                # ⚠️ center 内部带 SWP_SHOWWINDOW：静默启动时前端 boot 里那句
                #    window.center 会把窗口在 OFFSCREEN 重新显示出来 →
                #    **任务栏出现按钮、屏幕上看不见**（本轮 ②/③ 的根因之一）。
                #    ⚠️ 只挡「开机自启静默启动」这一个场景：
                #       静默启动期间 _shown 已置 True，前端不会自己呼出窗口，
                #       挡掉无副作用；用户从托盘呼出走 shell.show_window()，不经过这里。
                #    ⚠️ **不能**在这里读 _browser_mode_hidden（那是 lead 本轮刚定的闸门，
                #       由 _startup_hidden 复位与 toggle 清理，别碰）。
                return _ok(skipped=True, reason="startup_hidden")
            # ⚠️ 本轮同 window.show 那条：center 里的 resize/move 自带 SWP_SHOWWINDOW
            #    （见 frame.force_center_on_screen），浏览器模式隐藏期间前端启动时那句
            #    window.center 会把本应藏在托盘的窗口直接掀出来并置前 → 用户看到的
            #    "桌面端突然跳到所有窗口最顶端"。所以这里也要挡住。
            if getattr(self._shell, "_browser_mode_hidden", False):
                return _ok(skipped=True, reason="browser_mode_hidden")
            frame.force_center_on_screen(self._hwnd(), self._shell.window)
            return _ok()
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def set_theme(self, dark: bool = False):
        """把窗口的 DWM 装饰（圆角/边框/深色标题栏）跟主题对齐
        ⚠️ 系统标题栏模式（frameless=False）下，Windows 自己画的标题栏也要跟着换色，
           否则深色程序顶上会突然冒出一条白条（见 shell._apply_caption_theme）。
        """
        try:
            frame.apply_dark(bool(dark))
            try:
                self._shell._apply_caption_theme()
            except Exception:
                pass
            return _ok()
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def tray_menu(self, x=None, y=None):
        """弹出**原生**托盘右键菜单（自绘圆角菜单）
        ⚠️ 前端不要自己画 HTML 菜单：Windows 托盘菜单会超出窗口边界、且要在
           窗口失焦时保持最上层 —— 只有原生分层窗口能做到（见 shell.show_tray_menu）。
        x/y 为可选的屏幕坐标；不传就按托盘图标位置自动定位。
        """
        try:
            shown = self._shell.show_tray_menu(x, y)
            return _ok(shown=bool(shown))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)


class I18nDomain:
    """文案（15 个语言模块 × 三套语言目录）
    v1.1.4 起语言文件按语言分目录：
        .ToolsGCP/modules/languages/{zh_CN,zh_TW,en_US}/<module>_language.json
    每个 json 只有一种语言，值是**扁平字符串字典**（不再是 {key: {简体中文, English}}）。
    取值优先级和 LanguageManager 一致：请求语言目录 → zh_CN 目录 → key 本身。
    """

    MODULES = ("common", "nav", "search", "notice", "tools_gcp", "deploy",
               "github", "settings", "log", "feedback", "privacy", "plugin",
               "maker", "customize")

    FILES = {
        "search": "search_language.json",
        "notice": "notice_language.json", "tools_gcp": "ToolsGCPcenter_language.json",
        "deploy": "deploy_language.json", "github": "github_language.json",
        "settings": "set_language.json", "log": "log_language.json",
        "feedback": "feedback_language.json", "nav": "nav_language.json",
        "privacy": "privacy_language.json", "plugin": "plugin_language.json",
        "maker": "maker_language.json", "customize": "customize_language.json",
        "common": "common_language.json",
    }

    def __init__(self, shell):
        self._shell = shell

    def language(self):
        try:
            return _ok(language=self._shell.current_language())
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    @classmethod
    def _read_locale(cls, locale: str) -> dict:
        """读一个语言目录下的全部模块：{module: {key: 文案}}
        缺文件 / 结构不对 / 读失败 → 该模块给空 dict（交给上一层的 zh_CN 回退），
        绝不抛异常：前端拿不到文案只会显示 key，不该因此整页白屏。
        """
        data = {}
        locale_dir = os.path.join(LANGUAGES_DIR, locale)
        for module, filename in cls.FILES.items():
            entry = {}
            path = os.path.join(locale_dir, filename)
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as handle:
                        raw = json.load(handle)
                    if isinstance(raw, dict):
                        # 新结构是扁平字符串字典；只收非空字符串（空值等于没有）
                        entry = {str(key): str(value) for key, value in raw.items()
                                 if isinstance(value, str) and value}
                    else:
                        _log("warn", "语言", "language",
                             f"语言文件结构不是扁平字典: {path}")
                except Exception as exc:                  # noqa: BLE001
                    _log("warn", "语言", "language", f"加载语言文件失败 {path}: {exc}")
            data[module] = entry
        return data

    def bundle(self, language: str = ""):
        """一次把当前语言的**全部模块**下发：避免每渲染一段文案就跨一次进程边界
        ⚠️ 取值优先级与 `LanguageManager.get_text` 一致：`请求语言目录 → zh_CN 目录`；
            值已经是字符串（新结构一个文件只有一种语言），不用再按 dict 取语言。
            再缺就由前端自己的 t(key, 默认文案) 兜底，最后才显示 key 本身。
        """
        try:
            lang = str(language or self._shell.current_language() or "简体中文")
            locale = locale_for(lang)
            primary = self._read_locale(locale)
            # 只有非中文语言才需要再读一遍 zh_CN 做补词
            fallback = (primary if locale == DEFAULT_LOCALE
                        else self._read_locale(DEFAULT_LOCALE))
            data = {}
            for module in self.FILES:
                entry = dict(fallback.get(module, {}))
                entry.update(primary.get(module, {}))    # 该语言有的词覆盖中文
                data[module] = entry
            return _ok(language=normalize_language(lang), locale=locale, modules=data)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def text(self, module: str, key: str, language: str = ""):
        """单条取词（给"临时补一个词"用；批量请走 bundle）
        优先级同 bundle：请求语言目录 → zh_CN 目录 → key 本身（取不到就回 key，方便排查）。
        """
        try:
            lang = str(language or self._shell.current_language() or "简体中文")
            filename = self.FILES.get(module, "")
            if not filename:
                return _ok(text=key)
            locale = locale_for(lang)
            candidates = (locale,) if locale == DEFAULT_LOCALE else (locale, DEFAULT_LOCALE)
            for candidate in candidates:
                path = os.path.join(LANGUAGES_DIR, candidate, filename)
                if not os.path.isfile(path):
                    continue
                with open(path, "r", encoding="utf-8") as handle:
                    raw = json.load(handle)
                value = raw.get(key) if isinstance(raw, dict) else None
                if isinstance(value, str) and value:
                    return _ok(text=value)
            return _ok(text=key)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)


class LogDomain:
    """前端日志（统一进 system_log.log，方便和原版日志一起 grep）
    ⚠️ 这个域之前**只有 client()**，而前端日志页调的是 `log.files` / `log.read_current` /
    `log.export` / `log.clear_history` —— 全都不存在，tryCall 拿到 null 就静默降级，
    所以日志页永远空着、按钮永远禁用。这里把原版日志页需要的能力补齐。
    """

    def __init__(self, shell):
        self._shell = shell

    @staticmethod
    def _paths():
        """返回 (日志目录, 当前日志文件名)——直接复用原版常量，不另建目录"""
        from pymodels.constants import LOGS_DIR, LOG_CURRENT_FILE
        return LOGS_DIR, LOG_CURRENT_FILE

    def files(self, refresh: bool = False):
        """列出**全部**日志文件（新→旧）：[{name, rel, path, size, mtime, current}]
        ⚠️ 必须递归扫：历史日志在 `logs/history/ToolsGCP-<时间戳>.log`，
        当前日志在 `logs/system_log.log`。之前用单层 os.listdir，
        所以列表里只剩当前那一份 —— 正是"为什么只有当前页面、之前的都不显示"。
        """
        try:
            import os
            log_dir, current_name = self._paths()
            if not os.path.isdir(log_dir):
                return _ok(files=[], dir=log_dir)
            rows = []
            for root, _dirs, names in os.walk(log_dir):
                for name in names:
                    if not name.lower().endswith((".log", ".txt")):
                        continue
                    full = os.path.join(root, name)
                    try:
                        stat = os.stat(full)
                    except OSError:
                        continue
                    rel = os.path.relpath(full, log_dir).replace("\\", "/")
                    rows.append({
                        "name": name,
                        "rel": rel,
                        "path": full,
                        "size": int(stat.st_size),
                        "mtime": int(stat.st_mtime),
                        "current": rel == current_name,
                    })
            rows.sort(key=lambda r: (not r["current"], -r["mtime"]))
            return _ok(files=rows, dir=log_dir, count=len(rows))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def read(self, path: str = "", tail: int = 200000):
        """读一份日志的尾部内容（默认当前日志）；path 必须落在日志目录内"""
        try:
            import os
            log_dir, current_name = self._paths()
            target = str(path or "").strip()
            if not target:
                target = os.path.join(log_dir, current_name)
            target = os.path.abspath(target)
            root = os.path.abspath(log_dir)
            if target != root and not target.startswith(root + os.sep):
                return _fail("拒绝读取日志目录以外的文件")
            if not os.path.isfile(target):
                return _fail("日志文件不存在: " + target)
            limit = max(2000, min(int(tail or 200000), 2000000))
            with open(target, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - limit))
                raw = handle.read()
            text = raw.decode("utf-8", errors="replace")
            return _ok(path=target, text=text, size=int(size),
                       name=os.path.basename(target))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def read_current(self, tail: int = 200000):
        """当前日志（system_log.log）的尾部内容
        ⚠️ 必须带 `tail`：前端 `bridge.tryCall('log.read_current', 200000)` 会把它
           当**位置参数**传进来（pywebview 直接把 js 参数映射成实参）。原来签名是
           `read_current(self)`，于是每次进日志页都在控制台刷：
               TypeError: LogDomain.read_current() takes 1 positional argument but 2 were given
        """
        return self.read("", tail)

    # ---------- 导出（和 py 版同款：选位置 + zip + 固定命名） ----------
    @staticmethod
    def _default_zip_name(all_logs: bool) -> str:
        """默认文件名 —— 完全照抄 py 版（interfaces/log_interface.py:760/789）
            ToolsGCP_Log_<YYYYmmdd_HHMMSS>.zip       导出当前日志
            ToolsGCP_AllLogs_<YYYYmmdd_HHMMSS>.zip   导出全部日志
        """
        import time
        stamp = time.strftime("%Y%m%d_%H%M%S")
        return f"{APP_NAME}_{'AllLogs' if all_logs else 'Log'}_{stamp}.zip"

    def _collect(self, all_logs: bool):
        """要打包的文件：当前日志 +（all 时）递归所有历史日志"""
        import os
        log_dir, current_name = self._paths()
        current = os.path.abspath(os.path.join(log_dir, current_name))
        files = []
        if os.path.isfile(current):
            files.append(current)
        if all_logs and os.path.isdir(log_dir):
            for root, _dirs, names in os.walk(log_dir):
                for name in names:
                    if not name.lower().endswith((".log", ".txt")):
                        continue
                    full = os.path.abspath(os.path.join(root, name))
                    if full == current:
                        continue
                    files.append(full)
        return files

    @staticmethod
    def _zip(target: str, files):
        """优先复用原版 `logger.export_zip`（压缩包结构 = logs/xxx.log，和 py 版一致）"""
        try:
            from pymodels.utils.logger import log as py_log
            py_log.export_zip(target, files)
            return
        except Exception:
            pass
        import zipfile
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as handle:
            for path in files:
                import os
                handle.write(path, os.path.join("logs", os.path.basename(path)))

    def export(self, all: bool = False, path: str = "", pick: bool = True):
        """导出日志 → **zip 压缩包**，默认让用户自己选保存位置
        对照 py 版 `LogInterface.on_export_current / on_export_all`：
          · 先弹系统另存为（QFileDialog.getSaveFileName）；
          · 默认文件名是按时间戳生成的（见 `_default_zip_name`）；
          · 用户没写扩展名就补 `.zip`；
          · 用 `log.export_zip` 打包，包内固定 `logs/<文件名>`。
        `pick=False`（或显式传 path）时不弹框，落到桌面 —— 给自检脚本用。
        """
        try:
            import os
            all_logs = bool(all)
            files = self._collect(all_logs)
            if not files:
                return _fail("还没有可导出的日志")
            target = str(path or "").strip()
            if not target and pick:
                picked = self._shell.pick_save_path(
                    self._default_zip_name(all_logs), "ZIP 压缩包 (*.zip)")
                if not picked:
                    return _ok(canceled=True, path="", count=0)
                target = picked
            if not target:
                home = os.path.expanduser("~")
                desktop = os.path.join(home, "Desktop")
                out_dir = desktop if os.path.isdir(desktop) else os.getcwd()
                target = os.path.join(out_dir, self._default_zip_name(all_logs))
            if not target.lower().endswith(".zip"):
                target += ".zip"
            target = os.path.abspath(target)
            parent = os.path.dirname(target)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
            self._zip(target, files)
            _log("op", "日志", "log", f"已导出 {len(files)} 个日志: {target}")
            return _ok(path=target, name=os.path.basename(target),
                       count=len(files), canceled=False)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def export_current(self, path: str = ""):
        return self.export(False, path)

    def export_all(self, path: str = ""):
        """兼容前端 `log.export_all` 的调用名"""
        return self.export(True, path)

    def clear_history(self):
        """清理历史日志（保留当前日志）"""
        try:
            import os
            log_dir, current_name = self._paths()
            removed = 0
            if os.path.isdir(log_dir):
                # 递归清理（含 history/ 子目录），只保留当前日志
                for root, _dirs, names in os.walk(log_dir):
                    for name in names:
                        if not name.lower().endswith((".log", ".txt")):
                            continue
                        full = os.path.join(root, name)
                        if os.path.abspath(full) == os.path.abspath(os.path.join(log_dir, current_name)):
                            continue
                        try:
                            os.remove(full)
                            removed += 1
                        except OSError:
                            pass
            _log("op", "日志", "log", f"清理历史日志 {removed} 个")
            return _ok(removed=removed)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def client(self, level: str = "info", category: str = "界面",
               message: str = "", **fields):
        try:
            level = str(level or "info").lower()
            if level not in ("dbg", "info", "warn", "err", "op", "fatal"):
                level = "info"
            text = str(message or "")
            if fields:
                extra = " ".join(f"{k}={v}" for k, v in sorted(fields.items()))
                text = f"{text} {extra}".strip()
            _log(level if level != "dbg" else "dbg", category or "界面", "web", text)
            return _ok()
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)


class ClipboardDomain:
    """系统剪贴板（前端复制按钮统一走这里）
    ⚠️ 为什么不能只用 `navigator.clipboard`：WebView2 里它经常 reject（权限/上下文），
       前端就把"复制失败"当成"复制成功"提示给用户 —— 这就是"提示复制成功但剪贴板是空的"。
       这里直接打 Win32 剪贴板，和原版 PyQt 的 QApplication.clipboard() 等价。
    """

    def __init__(self, shell):
        self._shell = shell

    def write(self, text: str = ""):
        try:
            from ..native import clipboard
            value = str(text if text is not None else "")
            if not clipboard.set_text(value):
                return _fail("写入剪贴板失败（剪贴板被其它程序占用？）")
            return _ok(length=len(value))
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def read(self):
        try:
            from ..native import clipboard
            return _ok(text=clipboard.get_text())
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    # 兼容前端可能的调用名
    def copy(self, text: str = ""):
        return self.write(text)

    def set_text(self, text: str = ""):
        return self.write(text)


class ShellDomain:
    """外部程序相关（打开链接 / 打开目录 / 重启）"""

    def __init__(self, shell):
        self._shell = shell

    def open_url(self, url: str, label: str = "", background: bool = False):
        """用系统默认浏览器打开链接（原版 `utils/url_open.open_url` 的等价语义）
        ⚠️ 这里**不是** `webbrowser.open()` 那条"跳出应用"的路径：它是"用户点了外链"，
           原版也同样是交给系统浏览器。
        ⚠️ 应用**自身**的页面永远在 pywebview 窗口里，不经过这里。
        ⚠️⚠️ `background` 决定**要不要把本窗口抢回前台**。
           原版（py 的 url_open.open_url）只在**后台打开**（按着 Ctrl）时才抢回前台：
               background=True  → 浏览器在后台开，窗口保持在前台（需要抢回）
               background=False → 浏览器在前台开，**不要**抢回
           若普通点击也**无条件**抢回（`_reclaim()` 三拍 150/400/800ms）：
           用户点了链接 → 浏览器跳出来 → 150ms 后 ToolsGCP 又闪回前台 →
           浏览器被顶到后面（现象："点链接后突然又闪回 ToolsGCP 窗口"、
           "关掉标签页时先切到浏览器、又瞬间切回 ToolsGCP"）。
           所以：普通点击（background=False）**不抢**；只有显式后台打开才抢。
        """
        try:
            url = str(url or "").strip()
            if not url.lower().startswith(("http://", "https://", "mailto:")):
                return _fail(f"拒绝打开非 http(s) 链接: {url}")
            if background:
                # 后台打开：SW_SHOWNOACTIVATE（=3）不激活浏览器，之后要把窗口抢回前台
                win32.shell32.ShellExecuteW(None, "open", url, None, None, 3)
                threading.Thread(target=self._reclaim, name="ToolsGCP-foreground",
                                 daemon=True).start()
            else:
                # 前台打开：SW_SHOWNORMAL（=1）让浏览器正常获得焦点，
                # **不抢回** —— 否则浏览器刚跳出来就被 ToolsGCP 顶掉（用户投诉的"闪回"）。
                win32.shell32.ShellExecuteW(None, "open", url, None, None, 1)
            _log("info", "外壳", "url",
                 f"打开外部链接: {label or url}".strip()
                 + ("（后台打开，已排队抢回前台）" if background else "（前台打开，不抢回焦点）"))
            return _ok()
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def _reclaim(self):
        """多拍把窗口抢回前台（原版 url_open 的 150/400/800ms 三拍）
        ⚠️ 每拍之前都查一次退出闸门：这个线程要睡将近 1.4 秒，期间用户完全可能已经关掉
           程序 —— 那时再去 ShowWindow/SetForegroundWindow 会去碰已销毁的 hwnd。
           （它不调 evaluate_js，所以不会产生 WebView2 那条异常，但同样不该在退出时动窗口。）
        """
        for delay in (0.15, 0.40, 0.80):
            time.sleep(delay)
            if getattr(self._shell, "_teardown_started", False):
                return
            try:
                frame.bring_to_front(self._shell.hwnd())
            except Exception:
                pass

    def ping(self, url: str = ""):
        """**真实**测 Ping：DNS 解析 → TCP 握手 →（https 再算 TLS），返回各段毫秒数
        背景：前端卡片右键的测 Ping之前是拿本地图标文件 fetch 一下，等于假测
        （本机文件永远几毫秒）。这里对资源真实地址做一次网络测量：
          · dns_ms  —— getaddrinfo 耗时
          · tcp_ms  —— TCP 三次握手（这才是通常说的"网络延迟"）
          · tls_ms  —— https 的 TLS 握手（http 为 None）
          · total_ms= 三者之和
        全部用标准库，5 秒超时，失败返回明确原因（不假装成功）。
        """
        import socket
        import ssl
        import time
        from urllib.parse import urlparse

        def _fail_ping(message: str):
            return {"ok": False, "error": message}

        try:
            raw = str(url or "").strip()
            if not raw:
                return _fail_ping("没有可测的地址")
            if "://" not in raw:
                raw = "https://" + raw
            parsed = urlparse(raw)
            host = parsed.hostname
            if not host:
                return _fail_ping("地址里没有主机名: " + raw)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)

            started = time.perf_counter()
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            dns_ms = (time.perf_counter() - started) * 1000
            if not infos:
                return _fail_ping("DNS 没有返回可用地址: " + host)

            family, socktype, proto, _canon, addr = infos[0]
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(5.0)
            try:
                tcp_started = time.perf_counter()
                sock.connect(addr)
                tcp_ms = (time.perf_counter() - tcp_started) * 1000
                tls_ms = None
                if parsed.scheme == "https":
                    ctx = ssl.create_default_context()
                    tls_started = time.perf_counter()
                    sock = ctx.wrap_socket(sock, server_hostname=host)
                    tls_ms = (time.perf_counter() - tls_started) * 1000
            finally:
                try:
                    sock.close()
                except Exception:
                    pass

            total_ms = dns_ms + tcp_ms + (tls_ms or 0.0)
            return _ok(host=host, port=port,
                       dns_ms=round(dns_ms, 1), tcp_ms=round(tcp_ms, 1),
                       tls_ms=(None if tls_ms is None else round(tls_ms, 1)),
                       total_ms=round(total_ms, 1))
        except Exception as exc:                          # noqa: BLE001
            return _fail_ping(f"{type(exc).__name__}: {exc}")

    def open_path(self, path: str):
        """打开目录/文件（插件目录、日志目录这类入口用）"""
        try:
            path = os.path.abspath(str(path or ""))
            if not os.path.exists(path):
                return _fail(f"路径不存在: {path}")
            os.startfile(path)                            # noqa: S606 - Windows 专用
            return _ok()
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def pick_folder(self, title: str = "", initial: str = ""):
        """系统选择文件夹对话框（存储位置迁移等用）"""
        try:
            picked = self._shell.pick_folder(title=title, initial=initial)
            if not picked:
                return _ok(canceled=True, path="")
            return _ok(path=picked, canceled=False)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def pick_save_file(self, default_name: str = "", file_type: str = ""):
        """系统另存为对话框"""
        try:
            picked = self._shell.pick_save_path(default_name=default_name,
                                                file_type=file_type)
            if not picked:
                return _ok(canceled=True, path="")
            return _ok(path=picked, canceled=False)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def restart(self, open_settings: bool = False):
        """重启程序（原版 `utils/system_utils.restart_program`）
        ⚠️ 先 Popen、再**异步**退出（同 close/quit 的道理：同步 destroy 会让 pywebview
           在回调返回时对已释放的 WebView2 调 evaluate_js）。
        """
        try:
            self._shell.restart(open_settings=bool(open_settings))
            return _ok(deferred=True)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def quit(self, force: bool = False):
        """彻底退出（托盘菜单的"退出" / 前端退出按钮）
        ⚠️ 同样必须异步：立即把 `{ok:true}` 交回前端，延迟 0.25s 再真正销毁窗口。
        ⚠️ `force=True` = 用户已经确认过了（前端弹过框），别再弹原生确认框。
        """
        try:
            self._shell.quit_app_async(force=bool(force))
            return _ok(deferred=True)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def confirm_exit(self):
        """前端已经弹过确认框并得到用户同意 —— 告诉后端别再弹原生框
        ⚠️ 为什么要这个接口：退出确认有两条路（前端 HTML 弹窗 / 后端原生 MessageBox），
           前端那条走完必须告诉后端一声，否则点关闭会**弹两次**确认框。
        """
        try:
            self._shell.set_exit_confirmed()
            return _ok()
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def save_text_file(self, default_name: str = "", content: str = "",
                       file_type: str = ""):
        """**系统另存为对话框 + 写文本文件**（导出清单/收藏/任意 JSON 都走这里）
        背景：前端导出原来是 `Blob + a.download`，而 pywebview 的 WebView2 默认
        `ALLOW_DOWNLOADS` 关闭、`DownloadStarting` 里直接 `args.Cancel = True`
        （webview/platforms/edgechromium.py 的 on_download_starting）——
        所以用户点导出得到的是**空文件/根本没落盘**。桌面程序必须走系统对话框 + 后端写盘。
        参数：
            default_name  默认文件名（如 `ToolsGCP-Deploy-20261025.json`）
            content       要写入的**文本**（前端负责生成 JSON 字符串，后端只管落盘）
            file_type     筛选器，字符串即可：`'JSON 文件 (*.json)'`。
                          也兼容 `'*.json'` / `'JSON 文件|*.json'` / 多条 `;;` 分隔
                          （由 shell.normalize_file_types 兜底，见那里的注释）。
        返回：
            用户取消 → `{ok:true, canceled:true, path:""}`
            写成功   → `{ok:true, canceled:false, saved:true, path, name, bytes}`
            失败     → `{ok:false, error:"…"}`
        ⚠️ 编码固定 **UTF-8（无 BOM）**、换行不转换（`newline=""`），内容末尾没有换行时补一个，
           这样 Windows 记事本/VS Code 打开都正常，也和前端生成的 JSON 文本一致。
        """
        try:
            text = "" if content is None else str(content)
            picked = self._shell.pick_save_path(default_name=default_name,
                                                file_type=file_type)
            if not picked:
                _log("info", "外壳", "dialog", "用户取消了另存为")
                return _ok(canceled=True, path="", saved=False, bytes=0)
            path = os.path.abspath(str(picked))
            # 用户没写扩展名就按 default_name 的扩展名补一个（.NET 一般会补，
            # 但它补的是"筛选器第一条"；这里以调用方给的默认名为准更可控）
            root, ext = os.path.splitext(path)
            if not ext:
                want = os.path.splitext(str(default_name or ""))[1]
                if want:
                    path += want
            parent = os.path.dirname(path)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
            if text and not text.endswith(("\n", "\r")):
                text += "\n"
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
            size = os.path.getsize(path)
            _log("op", "外壳", "dialog",
                 f"已导出文件: {path}（{size} 字节，{len(text)} 字符）")
            return _ok(canceled=False, saved=True, path=path,
                       name=os.path.basename(path), bytes=int(size))
        except Exception as exc:                          # noqa: BLE001
            _log("err", "外壳", "dialog", f"导出文件失败: {exc}")
            return _fail(exc)

    def environment(self):
        """自检用：把外壳层的关键状态一次性吐出来"""
        try:
            return _ok(platform=sys.platform, python=sys.version.split()[0],
                       argv=sys.argv, frozen=bool(getattr(sys, "frozen", False)),
                       config_dir=CONFIG_DIR, data_dir=DATA_DIR,
                       hwnd=self._shell.hwnd(),
                       window=frame.window_state(self._shell.hwnd()),
                       tray=bool(self._shell.tray and self._shell.tray.available),
                       hotkeys=self._shell.hotkey_status())
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)


class AnnouncementDomain:
    """公告（原版 core/announcements.py + AnnouncementStore：已读状态落盘）
    ⚠️ 早期 Web 版把已读写在前端 localStorage，且每次都重新拉 GitHub，
       表现为"每次启动都要重新点一次已读"（公告已读状态没存住）。
       这里把原版那套搬回来：内容与已读 id 都在 `.ToolsGCP/config/announcements.json`。
    """

    def __init__(self, shell):
        self._shell = shell

    @property
    def store(self):
        manager = getattr(self._shell, "announcement_store", None)
        return manager

    def list(self, refresh: bool = False):
        """当前公告列表（默认用本地缓存；refresh=True 时去 GitHub 拉一次）"""
        try:
            store = self.store
            if store is None:
                return _fail("公告状态未就绪")
            if refresh:
                self._fetch(store)
            items = [dict(item) for item in (store.items or [])]
            return _ok(items=items, read_ids=list(store.read_ids),
                       unread=store.unread_count(), updated_at=store.updated_at)
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def mark_read(self, item_id):
        """把一条标成已读
        ⚠️ `item_id` 传的是 GitHub issue 的**编号**（#1 / #2 那种），
           不是数据库 id —— 状态文件里记的也是编号。
        ⚠️ 已读状态可能保存不下来的处理：
           后端 store 里**可能没有**这条公告（前端走的是 GitHub 直连那条路，
           没把内容同步给 store）→ 那 mark_all_read(target) 找不到人，
           什么都不会写盘。
           → 所以：target 为空时，用前端传来的**编号**直接记进 read_ids。
        """
        try:
            store = self.store
            if store is None:
                return _fail("公告状态未就绪")
            target = [item for item in list(store.items or []) + list(store.known or [])
                      if str(item.get("id")) == str(item_id)
                      or str(item.get("number")) == str(item_id)]
            if target:
                added = store.mark_all_read(target)
            else:
                # store 里没有这条 → 直接按编号记（前端已经知道编号了）
                try:
                    key = int(item_id)
                except (TypeError, ValueError):
                    key = 0
                if key and key not in set(store.read_ids):
                    store.read_ids.append(key)
                    store.read_ids = store.read_ids[-MAX_READ_IDS:]
                    store.save()
                    added = 1
                else:
                    added = 0
            # 补 op 日志（用户反馈"部分操作不记录"）：已读状态是会落盘的持久改动，
            # 以前一条都不写，"公告怎么又未读了/已读没存上"根本无从查起。
            _log("op", "公告", "mark_read",
                 f"标已读 编号={item_id} 新增={added} 剩余未读={store.unread_count()}")
            return _ok(added=added, unread=store.unread_count())
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def sync_items(self, items=None):
        """把前端拿到的公告内容**同步**给后端 store（配合 mark_read 的兜底）
        ⚠️ 为什么需要：前端有两条取公告的路：
           ① 后端 store（announcements.list）—— 有缓存时走这条；
           ② 直接 fetch GitHub API —— store 里没缓存时走这条。
           走 ② 时 store 是空的 → 后面 mark_read 找不到对应的公告 → **已读状态存不下来**。
           → 走 ② 之后调这个接口把内容补进 store，之后 mark_read 才能对上。
           ⚠️ 只**补内容**（items），不碰 read_ids（已读状态由 mark_read 管）。
        """
        try:
            store = self.store
            if store is None:
                return _fail("公告状态未就绪")
            clean = [dict(item) for item in (items or []) if isinstance(item, dict)]
            if clean:
                # ⚠️ 保留已有的 read_ids：update_items 只换 items，不动已读状态
                store.update_items(clean)
            return _ok(count=len(store.items), unread=store.unread_count())
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def mark_all_read(self):
        """全部标成已读"""
        try:
            store = self.store
            if store is None:
                return _fail("公告状态未就绪")
            added = store.mark_all_read()
            return _ok(added=added, unread=store.unread_count())
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def pending(self):
        """还没弹过的未读公告（前端弹新公告用；判定逻辑与原版同源）"""
        try:
            store = self.store
            if store is None:
                return _ok(items=[])
            return _ok(items=[dict(i) for i in store.unread_items()])
        except Exception as exc:                          # noqa: BLE001
            return _fail(exc)

    def _fetch(self, store):
        """去 GitHub 拉一次（复用原版 fetch_announcements + 镜像顺序）"""
        try:
            from pymodels.core import announcements as core
            settings = self._shell.settings_manager
            source = str(settings.settings.get("search_source", "")) if settings else ""
            items = core.fetch_announcements(
                sources=core.build_announcement_urls(search_source=source))
            store.update_items(items)
            core.log_announcements(len(items), store.unread_count())
        except Exception as exc:                          # noqa: BLE001
            _log("warn", "公告", "announcement", f"拉取公告失败: {exc}")


def _module_placeholder_unused():
    return None


class HotkeyDomain:
    """`api.hotkey.*` —— 快捷键的注册/重注册与浏览器模式
    ⚠️⚠️ 这个域以前**根本不存在**：前端设置页改完快捷键一直在调
       `bridge.tryCall('hotkey.apply_settings')`，后端没有这个域 → tryCall 返回 null
       → 前端只能提示"注册接口未就绪，重启后生效"。也就是说**改完快捷键必须重启**
       才起作用（用户会以为"设置没生效"）。现在补上，改完立刻重注册。
    """

    def __init__(self, shell):
        self._shell = shell

    def apply_settings(self):
        """按当前设置重注册全部快捷键，返回 `{ok, error, status}`
        `status` = shell.hotkey_status()：name → {ok, text}，前端据此显示每条的状态。
        ⚠️ 这条会碰原生层（RegisterHotKey / 键盘钩子），但都在托盘那条原生线程或
           钩子自己的线程上编组（见 shell.apply_hotkey_settings），js_api 工作线程
           调用是安全的。
        """
        try:
            ok, error = self._shell.apply_hotkey_settings(notify=True)
            return _ok(applied=bool(ok), error=error or "",
                       status=self._shell.hotkey_status())
        except Exception as exc:                        # noqa: BLE001
            return _fail(exc, status={})

    def status(self):
        try:
            return _ok(status=self._shell.hotkey_status())
        except Exception as exc:                        # noqa: BLE001
            return _fail(exc, status={})

    def set_caps_led(self, on):
        """把**大写锁定灯**设成指定状态（快捷键录制完还原用）
        ⚠️ 为什么需要：Caps Lock 是切换键。用户在录制框里按 Ctrl+Caps+O 时，
           按下 Caps 那一刻系统就把灯翻了 → 绑完快捷键打字全是大写
           （"设个快捷键把键盘弄坏了"级别的糟糕体验）。
           浏览器 / WebView2 里没有任何 API 能**设置**灯的状态
           （只有 `getModifierState('CapsLock')` 能读），所以只能由原生层注入一次
           VK_CAPITAL 把它翻回去。
        ⚠️ 注入"按下 + 抬起"一对（scan code 0x45 = Caps）：VK 事件走完整条输入链，
           系统按正常逻辑切换状态。
        ⚠️ **幂等**：先读当前灯的状态，和期望一致就什么都不做 —— 前端重复调、
           或者用户在别处已经翻回去了，都不会被这里再翻一次。
        """
        try:
            if not win32.IS_WINDOWS:
                return _ok(set=False, reason="not_windows")
            current = bool(win32.user32.GetKeyState(0x14) & 1)   # GK_TOGGLE = 0x01
            want = bool(on)
            if current == want:
                return _ok(set=True, unchanged=True, caps_led=want)
            KEYEVENTF_KEYUP = 0x0002
            win32.user32.keybd_event(0x14, 0x45, 0, 0)
            win32.user32.keybd_event(0x14, 0x45, KEYEVENTF_KEYUP, 0)
            after = bool(win32.user32.GetKeyState(0x14) & 1)
            if after != want:
                # ⚠️ 实测：受限会话/被拦的输入注入下 keybd_event **可能整条不起作用**
                #   （本机试过：注入完灯的状态一点没变）。那种情况必须**如实报失败**，
                #   不能回 ok=True —— 前端要靠这个值决定要不要提示用户"灯还亮着，
                #   自己按一下 Caps Lock 关掉"。谎报成功等于让用户莫名其妙。
                _log("warn", f"还原大写锁定灯失败：注入按键后仍是 {after}（期望 {want}）")
                return _ok(set=False, unchanged=False, caps_led=after,
                           reason="input_blocked")
            _log("info", f"快捷键录完还原大写锁定灯：{current} → {after}")
            return _ok(set=True, unchanged=False, caps_led=after)
        except Exception as exc:                        # noqa: BLE001
            # 还原失败只是灯还亮着，绝不能让"绑定快捷键"这一步失败
            return _fail(exc, set=False)

    # ---------- 浏览器模式（Ctrl+Caps+O） ----------
    def browser_status(self):
        """服务是否在跑、URL、有几个页签在轮询事件"""
        try:
            return _ok(**self._shell.browser_mode_status())
        except Exception as exc:                        # noqa: BLE001
            return _fail(exc, running=False, url="", port=0)

    def browser_open(self):
        """立刻打开浏览器模式（设置页的按钮；和快捷键同一个入口）"""
        try:
            return _ok(**self._shell.open_browser_mode())
        except Exception as exc:                        # noqa: BLE001
            return _fail(exc)

    def browser_close(self):
        """停掉浏览器模式的服务（用户不想让它一直占端口时用）"""
        try:
            from .. import browsermode
            browsermode.SERVER.stop()
            return _ok(running=False)
        except Exception as exc:                        # noqa: BLE001
            return _fail(exc)


class Api:
    """`window.pywebview.api` 的根对象
    ⚠️ 新增域只要在这里挂一个属性（`self.xxx = XxxDomain(shell)`），
       pywebview 会自动把公有方法展开成 `api.xxx.method`（util.py 的 get_functions）。
    """

    def __init__(self, shell):
        self._shell = shell
        self.app = AppDomain(shell)
        self.window = WindowDomain(shell)
        self.i18n = I18nDomain(shell)
        self.log = LogDomain(shell)
        self.shell = ShellDomain(shell)
        self.clipboard = ClipboardDomain(shell)
        self.announcements = AnnouncementDomain(shell)
        # 资源库 / 收藏 / 配置
        from .resources import FavoritesDomain, ResourcesDomain, SettingsDomain
        self.settings = SettingsDomain(shell)
        self.favorites = FavoritesDomain(shell)
        self.resources = ResourcesDomain(shell)
        # GCP-AI：会话 / 历史对话 / 发送（对齐原版 core/ai + ui/ai_chat_panel.py 的会话模型）
        from .ai import AiDomain
        self.ai = AiDomain(shell)
        # 资源制作器（提交软件 / 批量合成）的写盘：提供真正的 append_entry/append_entries
        # （缺这个域时前端只能降级成"导出 JSON 自己放回去"）。
        from .maker import MakerDomain
        self.maker = MakerDomain(shell)
        # 检查更新：下载更新包 + 重启替换。契约见 desktop/api/update.py 的模块 docstring。
        from .update import UpdateDomain
        self.update = UpdateDomain(shell)
        # 插件：插件中心列真实目录（缺这个域时前端只能退回写死的三个 id，
        # 用户自己生成的插件永远不出现）。同文件里还有插件制作辅助的纯 Python 桥：
        # `/plugin` 悬浮提示 + create_plugin 工具（**不** import 插件的 app.py/ui，
        # 它们会 import PyQt5 到主线程）。
        from .plugins import PluginsDomain
        self.plugins = PluginsDomain(shell)
        # GitHub Releases 下载域（前端 `downloader.releases / resolve_asset / start /
        # cancel / list / open_file / open_folder / clear_finished / retry`）。
        # 部署页与更新页都依赖 `downloader.start`，没有这个域就只能降级去开浏览器。
        from .downloader import DownloadDomain
        self.downloader = DownloadDomain(shell)
        # 快捷键：改完设置**立刻**重注册（以前没有这个域，前端 tryCall 拿到 null
        # 只能提示"重启后生效"）+ 浏览器模式开关。见 HotkeyDomain。
        self.hotkey = HotkeyDomain(shell)

    # ---------- 兜底 ----------
    def ping(self):
        """最小连通性探针（前端启动脚本第一件事）"""
        return _ok(pong=True, ts=time.time())
