"""「我当前真实有哪些能力」清单（需求 6）：喂给系统提示词的运行时能力段。

为什么单独一个模块而不是塞进 prompt.py：这些清单要读 Key 槽位（settings_manager）、
读插件目录与启停状态（plugins.json），属于"拿数据"而不是"写提示词"；prompt.py 只
负责把拿到的文本拼进元信息段。任何一项拿不到（异常）都降级为"未知/未开启"并写日志，
**绝不让发送主链路抛错**（用户报过 AI 答非所问的根因之一就是提示词构建半途炸了）。

⚠️ 插件清单必须**动态枚举**（走 desktop/api/plugins.py 的 plugins_dirs() /
PluginManager 的启停状态文件），绝不硬编码内置插件名单 —— 以后第三方开发者新增
插件要自动出现在能力清单里，这是需求原话。
"""

import json
import os


def _log(message: str):
    try:
        from ...utils.logger import log
        log.warn("AI", "capabilities", message)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# ① 可用（已配 API Key）的服务商与模型
# ---------------------------------------------------------------------------
def available_models_text(settings_manager) -> str:
    """与 desktop/api/ai.py 的 model_choices() 同一套 has_key 过滤逻辑：
    逐服务商读分槽 Key（get_api_key(provider)），有 Key 的才列，一行一个。

    ⚠️ 必须动态：写死清单会在用户换服务商/换 Key 后继续让 AI 吹自己有某个模型
       （用户报的"我说没配 Key 它还说能用 GPT"）。拿不到返回"未知"。
    """
    if settings_manager is None:
        return "未知（设置不可读）"
    try:
        from . import providers as p
        rows = []
        for provider in p.PROVIDERS:
            pid = provider["id"]
            try:
                if not settings_manager.get_api_key(pid):
                    continue
            except Exception as exc:                      # noqa: BLE001
                _log(f"读取 {pid} 的 Key 状态失败: {exc}")
                continue
            models = p.models_of(pid)
            if not models:
                rows.append(p.provider_display(pid))
                continue
            rows.append(f"{p.provider_display(pid)}: {', '.join(models)}")
        if not rows:
            return "无（当前没有任何服务商配置了 API Key）"
        return "；".join(rows)
    except Exception as exc:                              # noqa: BLE001
        _log(f"生成可用模型清单失败: {exc}")
        return "未知"


# ---------------------------------------------------------------------------
# ② 已启用的功能（来自 settings）
# ---------------------------------------------------------------------------
def enabled_features_text(settings, resource_count: int = 0,
                          network: str = "") -> str:
    """把设置里"用户能开关的功能"翻译成一串短语。

    ⚠️ 资源库/收藏夹是程序本体功能（永远具备），插件系统/AI/思考/Agent 看开关，
       联网搜索本程序**不具备**（network 传空 = 不具备；由调用方按联网插件状态传）——
       明确写出来，否则模型会顺着训练记忆声称自己能上网。
    """
    on = []
    off = []
    # 固定本体功能：不受开关控制，永远"有"
    lib = f"（当前 {resource_count} 条）" if resource_count else ""
    on.append(f"资源库检索{lib}")
    on.append("收藏夹")
    on.append("插件系统")
    try:
        get = settings.get if isinstance(settings, dict) else (lambda k, d=None: d)
        if bool(get("gcp_ai_agent_enabled", False)):
            on.append("GCP-AI Agent（可实际操作本程序）")
        else:
            off.append("GCP-AI Agent（当前关闭）")
        if bool(get("gcp_plugin_maker_enabled", False)):
            on.append("插件制作辅助 /plugin")
        if bool(get("ai_polish_enabled", True)):
            on.append("输入框润色")
        # 思考：档位开没开由调用方在元信息段的"当前思考档位"一行里单独说，
        # 这里只说"支不支持"，避免两处口径打架。
        on.append("AI 思考（强度档位见上）")
    except Exception as exc:                              # noqa: BLE001
        _log(f"读取功能开关失败: {exc}")
    # 明确不具备的：别让模型顺着"ChatGPT 人设"吹自己能联网/画图
    off.append(network if network else
               "联网搜索（本程序未开启任何联网能力）")
    parts = []
    if on:
        parts.append("已开启：" + "、".join(on))
    if off:
        parts.append("未开启/不具备：" + "、".join(off))
    return "；".join(parts) if parts else "未知"


# ---------------------------------------------------------------------------
# ③ 已启用插件（动态枚举）
# ---------------------------------------------------------------------------
def _plugins_state_path() -> str:
    """插件启停状态文件：<数据根>/config/plugins.json 的 disabled 集合。
    ⚠️ 与 pymodels.core.plugin_manager 的 STATE_FILE 同一路径口径（DATA_DIR），
       不 import plugin_manager 本体：它的 __init__ 会做目录迁移，读一个状态
       文件不该带那种副作用。
    """
    try:
        from ... import constants
        return os.path.join(str(constants.DATA_DIR), "plugins.json")
    except Exception as exc:                              # noqa: BLE001
        _log(f"定位 plugins.json 失败: {exc}")
        return ""


def _settings_snapshot() -> dict:
    """读当前设置（优先走桌面外壳那份内存实例，拿不到再 new 一个）

    ⚠️ 为什么先摸 shell：`SettingsManager()` 会重新读盘，而外壳手上那份才是
       "用户刚改完、还没落盘/正在落盘"的最新值 —— 提示词里报旧状态就是这么来的。
    ⚠️ 为什么允许退回 new 一个：capabilities 也可能在无外壳的脚本里被调用
       （自检/回归），那时没有 shell，只能读盘。两步都失败就给空字典。
    """
    # ⚠️ 这里只读盘（不去摸各种外壳上的全局引用）：core 层不认识桌面层，
    #    顶层/深层摸 shell 会把 core→desktop 的导入方向反过来（自检要求
    #    "屏蔽 PyQt5 后仍能完整 import" 就是被这类反向依赖搞脆的）。
    #    设置管理器本身有"读一次缓存进内存"的语义，调用点（拼提示词）一次一批，
    #    代价可以忽略；真正需要"最新内存值"的调用方（desktop/api/ai.py）
    #    会把 set 之后的 settings 直接传进来（见 _disabled_ids(settings=...)）。
    try:
        from ..settings_manager import SettingsManager
        return dict(SettingsManager().settings or {})
    except Exception as exc:                              # noqa: BLE001
        _log(f"读取设置失败: {exc}")
        return {}


def _disabled_ids(settings: dict = None) -> set:
    """哪些插件 id 现在是"停用"状态 —— **优先读 settings 里的 enabled_setting**

    为什么改（契约 2.5「状态双源修掉」）：
      以前只读 `<数据根>/config/plugins.json` 的 `disabled` 集合（那是 **py 版**
      PluginManager 的状态文件），而 **Web 版真正的开关是每个插件的
      `enabled_setting`**（插件中心写的就是它）。于是两个真相源各说各话：
      用户在插件中心关掉插件、AI 的提示词里却还写着"启用"（反之亦然）。
    现在的顺序：
      ① 逐插件读 manifest 的 `enabled_setting`，设置里有值就以它为准（True=启用）；
      ② 没声明该字段的插件，才回退 `plugins.json` 的 disabled 集合；
      ③ 强制开启（locked）的插件**永远算启用**（用户要求"无法关闭"）。
    """
    if settings is None:
        settings = _settings_snapshot()
    disabled = set()
    try:
        # ① settings 优先（Web 版真实开关）
        for folder, info in _enumerate_manifests():
            key = str(info.get("enabled_setting") or "").strip()
            if not key or key not in settings:
                continue
            if not _truthy(settings.get(key)):
                disabled.add(info.get("id") or folder)
                disabled.add(folder)
    except Exception as exc:                              # noqa: BLE001
        _log(f"按 settings 判定插件停用状态失败（回退 plugins.json）: {exc}")
    # ② 回退：py 版那份 plugins.json（只补"没有任何 enabled_setting 值"的条目）
    declared = set()
    try:
        for folder, info in _enumerate_manifests():
            declared.add(str(info.get("id") or folder))
            declared.add(folder)
    except Exception:
        pass
    for pid in _state_file_disabled_ids():
        if pid in declared:
            # 已经按 settings 判过了：settings 才是 Web 版的真相，别被老文件推翻
            continue
        disabled.add(pid)
    # ③ 强制开启的插件永远算"启用"（就算老配置里写着 disabled）
    for pid in _locked_ids():
        disabled.discard(pid)
    return disabled


def _truthy(value) -> bool:
    """设置值的严格布尔（和 desktop/api/plugins.py 的 _strict_on 同口径）

    ⚠️ 不能直接 bool(value)：老配置里可能存成字符串 "false"，bool("false") 是 True。
    """
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return False


def _plugin_roots() -> list:
    """全部插件根目录（用户目录在前、内置目录在后）

    优先走桌面桥接层的 `plugins_dirs()`（两个根 + 优先级规则只有那一份）；
    没有桌面层（脚本/自检）时退回 constants 自己拼，并补一个按本模块位置反推的
    内置根 —— 因为 `constants.CONFIG_DIR` 按 sys.argv[0] 推导，从 _devtest/
    跑脚本时会指到脚本目录旁，扫不到真实的 .ToolsGCP/plugins。
    """
    roots = []
    try:
        from desktop.api.plugins import plugins_dirs
        roots = [r for r in plugins_dirs() if r]
    except Exception:
        roots = []
    if not roots:
        try:
            from ... import constants
            roots = [os.path.join(str(constants.USER_DATA_ROOT), "plugins"),
                     os.path.join(str(constants.CONFIG_DIR), "plugins")]
        except Exception:
            roots = []
    derived = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "..", "..", "..", "..", "plugins"))
    if os.path.isdir(derived) and all(
            os.path.normcase(str(r)) != os.path.normcase(derived) for r in roots):
        roots = list(roots) + [derived]
    return roots


def _is_reserved(name: str) -> bool:
    """这个目录名要不要当成插件（`_` / `.` 开头 + 保留名一律跳过）

    ⚠️ 必须复用 `desktop.api.plugins.is_reserved_folder`（契约 2.5）：
       这里以前是 `name.startswith(("_", "."))`，只挡了"下划线/点"开头，
       **没挡 `plugin-showcase`** —— 于是"插件示例"被当成真插件混进 AI 的能力清单，
       模型就会说"你有个插件叫插件示例、状态启用"。两处规则必须同一份。
    ⚠️ lazy import + try：core 层不能顶层 import 桌面层（会拖进 plugins.py 的依赖），
       拿不到就退回本地的最小判定（至少 `_`/`.` 开头还是要挡）。
    """
    text = str(name or "")
    if not text:
        return True
    try:
        from desktop.api.plugins import is_reserved_folder
        return bool(is_reserved_folder(text))
    except Exception:
        return text.startswith(("_", "."))


def _enumerate_manifests(roots=None) -> list:
    """扫描插件根，返回 `[(目录名, manifest dict)]`（同名只留高优先级那一份）

    只读 manifest.json，**绝不 import 插件代码**（app.py 会拉 PyQt5 崩主线程）。
    """
    out = []
    seen = set()
    for root in (roots if roots is not None else _plugin_roots()):
        if not root or not os.path.isdir(root):
            continue
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for name in names:
            folder = os.path.join(root, name)
            if not os.path.isdir(folder) or _is_reserved(name):
                continue
            if name in seen:
                continue
            seen.add(name)
            manifest = {}
            for fname in ("manifest.json", "plugin.json"):
                path = os.path.join(folder, fname)
                if not os.path.isfile(path):
                    continue
                try:
                    with open(path, "r", encoding="utf-8-sig") as handle:
                        loaded = json.load(handle)
                    manifest = loaded if isinstance(loaded, dict) else {}
                except Exception as exc:                  # noqa: BLE001
                    _log(f"读取插件 manifest 失败 {path}: {exc}")
                    manifest = {}
                break
            if not manifest:
                continue
            manifest = dict(manifest)
            manifest.setdefault("id", name)
            out.append((name, manifest))
    return out


def _locked_ids() -> set:
    """强制开启（不可关闭）的插件 id 集合（口径只有 `is_locked_plugin` 那一份）"""
    locked = set()
    try:
        from desktop.api.plugins import is_locked_plugin
    except Exception:
        return {"gcp-ai-agent"}      # 拿不到桌面层时的兜底（常量在契约里写死）
    for folder, manifest in _enumerate_manifests():
        try:
            if is_locked_plugin(folder, manifest):
                locked.add(str(manifest.get("id") or folder))
                locked.add(folder)
        except Exception:
            continue
    return locked


def _state_file_disabled_ids() -> set:
    """`plugins.json` 里的 disabled 集合（py 版状态文件；读不到就是空集）"""
    path = _plugins_state_path()
    if not path or not os.path.isfile(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and isinstance(data.get("disabled"), list):
            return {str(x) for x in data["disabled"]}
    except Exception as exc:                              # noqa: BLE001
        _log(f"读取插件启停状态失败: {exc}")
    return set()


def enabled_plugins_text(locale: str = "zh_CN", roots=None) -> str:
    """动态枚举**两个插件根目录**（程序目录 .ToolsGCP/plugins 与数据根 plugins），
    按真实开关（settings 里的 enabled_setting，见 `_disabled_ids`）分成启用/停用，
    输出「名称 — 一句话能力（状态）」。

    ⚠️ 只走目录扫描，绝不硬编码内置插件名单：第三方开发者以后新增的插件目录
       会自动出现在这里。同名插件用户目录那份生效（优先级与 plugins_dirs() 一致）。
    ⚠️ 只读 manifest.json，绝不 import 插件代码（app.py 会拉 PyQt5 崩主线程）。
    ⚠️ 保留目录（`_template` / `plugin-showcase` 等）必须由 `is_reserved_folder` 挡掉，
       否则"插件示例"会被当成真插件写进 AI 的能力清单（模型会照着瞎说）。
    roots：测试注入用（devtest 脚本不在程序入口跑，constants.CONFIG_DIR 会按
           主脚本目录推导到 _devtest/ 下，扫不到真实插件目录）；正常留 None。
    """
    langs = {"zh_CN": "简体中文", "zh_TW": "繁體中文", "en_US": "English"}
    language = langs.get(str(locale or ""), "简体中文")
    try:
        # 根目录规则统一走 _plugin_roots()（两个根 + 优先级 + 反推兜底，只有那一份）
        root_list = list(roots) if roots else _plugin_roots()
        # ⚠️ 真的按"设置里的开关"判：这是用户点了插件中心那个开关之后**唯一**
        #    会被 AI 看到的状态，两份源各说各话就是"关了它还说自己开着"。
        disabled = _disabled_ids()
        rows = []
        for folder, manifest in _enumerate_manifests(root_list):
            # _enumerate_manifests 已经读过 manifest：直接复用，别二次读盘
            pid = str(manifest.get("id") or folder)
            name = _pick_i18n(manifest.get("name"), language) or pid
            desc = _pick_i18n(manifest.get("description"), language)[:60]
            state = "停用" if (pid in disabled or folder in disabled) else "启用"
            rows.append(f"{name}（{desc}，{state}）" if desc else f"{name}（{state}）")
        if not rows:
            return "无（未安装任何插件）"
        return "；".join(rows)
    except Exception as exc:                              # noqa: BLE001
        _log(f"枚举插件失败: {exc}")
        return "未知"


def _folder_path(roots: list, name: str) -> str:
    """在已有根里找到某个插件目录的绝对路径（只用于兜底描述，找不到给空串）"""
    for root in roots or []:
        candidate = os.path.join(str(root or ""), name)
        if root and os.path.isdir(candidate):
            return candidate
    return ""


def _pick_i18n(value, language: str) -> str:
    """多语言字段取值（语言名 → locale 名 → 简体中文 → English 顺序回退）"""
    if isinstance(value, dict):
        for key in (language, "简体中文", "zh_CN", "繁體中文", "zh_TW", "English", "en_US"):
            if value.get(key):
                return str(value[key])
        for item in value.values():
            if item:
                return str(item)
        return ""
    return str(value or "")

