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


def _disabled_ids() -> set:
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
    按 plugins.json 的 disabled 集合分成启用/停用，输出「名称 — 一句话能力（状态）」。

    ⚠️ 只走目录扫描，绝不硬编码内置插件名单：第三方开发者以后新增的插件目录
       会自动出现在这里。同名插件用户目录那份生效（优先级与 plugins_dirs() 一致）。
    ⚠️ 只读 manifest.json，绝不 import 插件代码（app.py 会拉 PyQt5 崩主线程）。
    roots：测试注入用（devtest 脚本不在程序入口跑，constants.CONFIG_DIR 会按
           主脚本目录推导到 _devtest/ 下，扫不到真实插件目录）；正常留 None。
    """
    langs = {"zh_CN": "简体中文", "zh_TW": "繁體中文", "en_US": "English"}
    language = langs.get(str(locale or ""), "简体中文")
    try:
        # 桌面桥接层提供 plugins_dirs()（两个根 + 优先级）；core 层单独运行时
        # （测试/预览）退回 constants 自己拼，两边规则一致。
        # ⚠️ `desktop` 是顶层包，不能用相对导入跨出 pymodels；导入失败=没有桥接层。
        if not roots:
            try:
                from desktop.api.plugins import plugins_dirs
                roots = list(plugins_dirs())
            except Exception as exc:                      # noqa: BLE001
                _log(f"plugins_dirs() 不可用，退回 constants 拼路径: {exc}")
                roots = []
        if not roots:
            from ... import constants
            roots = [os.path.join(str(constants.USER_DATA_ROOT), "plugins"),
                     os.path.join(str(constants.CONFIG_DIR), "plugins")]
        # ⚠️ 兜底：constants.CONFIG_DIR 按"主脚本所在目录"推导 —— 从 _devtest /
        #    其它非程序入口跑时它会指到脚本目录旁，扫不到真实内置插件根。
        #    本模块自己的 __file__ 一定在 `<root>/.ToolsGCP/modules/pymodels/core/ai`
        #    下，反推上去就是真正的 .ToolsGCP/plugins：只在"现有根里没有任何一个
        #    存在的目录名恰好是插件根"之外的场景**追加**一个候选（生产环境两处
        #    路径相同，normcase 判重后什么都不加，行为不变）。
        derived = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                "..", "..", "..", "..", "plugins"))
        if os.path.isdir(derived) and all(
                os.path.normcase(str(r)) != os.path.normcase(derived) for r in roots):
            roots = list(roots) + [derived]
        disabled = _disabled_ids()
        rows = []
        seen = set()
        for root in roots:
            if not root or not os.path.isdir(root):
                continue
            for name in sorted(os.listdir(root)):
                folder = os.path.join(root, name)
                # 规则与 PluginManager.is_reserved_folder 一致：_/. 开头不是插件
                if not os.path.isdir(folder) or name.startswith(("_", ".")):
                    continue
                if name in seen:
                    continue            # 高优先级根已收过：同名被遮住的内置份不重复列
                seen.add(name)
                info = _manifest_brief(folder, name, language)
                state = "停用" if (info["id"] in disabled or name in disabled) else "启用"
                desc = info["description"]
                rows.append(f"{info['name']}（{desc}，{state}）"
                            if desc else f"{info['name']}（{state}）")
        if not rows:
            return "无（未安装任何插件）"
        return "；".join(rows)
    except Exception as exc:                              # noqa: BLE001
        _log(f"枚举插件失败: {exc}")
        return "未知"


def _manifest_brief(folder: str, fallback_name: str, language: str) -> dict:
    """读一个插件目录的 manifest.json，取「名称 + 一句话能力」；坏了给目录名兜底"""
    out = {"id": fallback_name, "name": fallback_name, "description": ""}
    for fname in ("manifest.json", "plugin.json"):
        path = os.path.join(folder, fname)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                m = json.load(handle)
            if not isinstance(m, dict):
                break
            out["id"] = str(m.get("id") or fallback_name)

            def _pick(value):
                if isinstance(value, dict):
                    for key in (language, "简体中文", "zh_CN", "English", "en_US"):
                        if value.get(key):
                            return str(value[key])
                    return ""
                return str(value or "")

            out["name"] = _pick(m.get("name")) or out["id"]
            out["description"] = _pick(m.get("description"))[:60]
        except Exception as exc:                          # noqa: BLE001
            _log(f"读取插件 manifest 失败 {folder}: {exc}")
        break
    return out
