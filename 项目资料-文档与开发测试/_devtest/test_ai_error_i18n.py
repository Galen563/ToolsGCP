# -*- coding: utf-8 -*-
"""后端错误/固定回复的多语言验证（本轮"切了语言还有简体中文"的后端那一半）。

⚠️ 为什么后端也要测：用户报「语言切换为其他语言部分地方还是只有简体中文文本内容，
   包括各种地方」—— 报错气泡和"没配 Key"的固定回复都是**后端生成、直接落盘进气泡**
   的文本，前端只负责显示、翻不了。以前前端 grep 永远查不出这一类。

覆盖：
  [1] 三条语言包文案在三种语言下都取得到，且**英文界面不出现简体中文**
  [2] 可点击 token 的字面量按语言各一份，且前端 AI_SETTINGS_TOKENS 全认得
  [3] _localized_error 按 kind 本地化 + 保留"（服务端说明：…）"尾巴
  [4] 占位符必须被填掉（我第一版漏了 {status}/{reason}，会显示字面量）
  [5] 认不出 kind / 语言包缺键 → 原样返回，绝不吞掉报错信息

跑法：python "项目资料-文档与开发测试/_devtest/test_ai_error_i18n.py"
全程离线：语言包直接读文件，不写用户配置、不起窗口。
"""
import io
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(BASE, ".ToolsGCP"), os.path.join(BASE, ".ToolsGCP", "modules")]

FAILS = []
CJK = re.compile(r"[\u4e00-\u9fff]")


def check(name, cond, extra=""):
    print(("  OK    " if cond else "  FAIL  ") + name + (f"  <- {extra}" if extra else ""))
    if not cond:
        FAILS.append(name)


PACK = {
    "zh_CN": os.path.join(BASE, ".ToolsGCP", "modules", "languages", "zh_CN", "set_language.json"),
    "zh_TW": os.path.join(BASE, ".ToolsGCP", "modules", "languages", "zh_TW", "set_language.json"),
    "en_US": os.path.join(BASE, ".ToolsGCP", "modules", "languages", "en_US", "set_language.json"),
}
DATA = {k: json.load(io.open(v, encoding="utf-8")) for k, v in PACK.items()}

KEYS = ["ai_err_no_key", "ai_err_no_model", "ai_err_auth", "ai_err_rate", "ai_err_timeout",
        "ai_err_network", "ai_err_bad_request", "ai_err_server", "ai_err_bad_json",
        "ai_err_config", "ai_err_unknown", "ai_err_failed", "ai_err_current_config",
        "ai_no_key_chat", "ai_no_key_polish", "ai_no_key_test"]

print("[1] 语言包：三语齐全 + 英文界面不含简体中文")
for k in KEYS:
    missing = [L for L in PACK if k not in DATA[L]]
    check(f"{k} 三语齐全", not missing, "缺:" + ",".join(missing))
en_bad = [(k, DATA["en_US"][k]) for k in KEYS if k in DATA["en_US"] and CJK.search(DATA["en_US"][k])]
check("en_US 的 16 条错误/固定回复里没有简体中文", not en_bad,
      "; ".join(f"{k}={v[:40]}" for k, v in en_bad[:3]))
# ⚠️ 差异字表要挑**真的只在简体出现**的字：
#    「於」是繁体的"于"（屬於/過於 都对）、「查」繁简同形（檢查）——
#    把它们当简体字会误报（我第一版就假 FAIL 了 3 条）。
TW_SIMPLIFIED = r"设|单|关|内|达|远|级|统|润|历|储|为|与|从|众|医|厅|装|负|质|顾"
tw_bad = [(k, DATA["zh_TW"][k]) for k in KEYS
          if k in DATA["zh_TW"] and re.search(TW_SIMPLIFIED, DATA["zh_TW"][k])]
check("zh_TW 没有混入简体字（抽查常见简繁差异字）", not tw_bad,
      "; ".join(f"{k}={v[:40]}" for k, v in tw_bad[:3]))

print("[2] 可点击 token 的字面量：后端有、前端认")
appjs = io.open(os.path.join(BASE, ".ToolsGCP", "webui", "js", "app.js"), encoding="utf-8").read()
m = re.search(r"const AI_SETTINGS_TOKENS = \[([^\]]+)\]", appjs, re.S)
check("前端有 AI_SETTINGS_TOKENS 表", bool(m))
tokens = re.findall(r"'([^']+)'", m.group(1)) if m else []
check("前端认中文 token（请填写/设置/填写）",
      "请填写<API Key>" in tokens and "设置<API Key>" in tokens, ",".join(tokens))
check("前端认英文 token", "fill in <API Key>" in tokens and "<API Key>" in tokens)
# 后端每条文案里的 <API Key> 字面量必须能被前端匹配到
for L in PACK:
    for k in ("ai_no_key_chat", "ai_no_key_polish", "ai_no_key_test", "ai_err_auth"):
        v = DATA[L].get(k, "")
        if "<API Key>" not in v:
            continue
        hit = any(tok in v for tok in tokens)
        check(f"{L}/{k} 里的 <API Key> 能被前端识别", hit, v[:60])
# ⚠️ 顺序 = 匹配优先级：长的必须在短的前面，否则 "请填写<API Key>" 会被 "<API Key>" 吃掉一截
if tokens:
    idx_bare = tokens.index("<API Key>")
    longer_before = all(tokens.index(t) < idx_bare for t in tokens if len(t) > len("<API Key>"))
    check("token 表按长度优先排列（长在前，避免被裸 <API Key> 截断）", longer_before,
          ",".join(tokens))

print("[3] _localized_error 按 kind 本地化")
from desktop.api.ai import AiDomain                                     # noqa: E402


class Stub(AiDomain):
    """只桩 _locale / _text 的取数来源，**逻辑跑真实代码**"""

    def __init__(self, locale):
        self._locale_value = locale
        self._shell = None

    def _locale(self):
        return self._locale_value

    def _text(self, key, fallback, module="set", **fmt):
        text = DATA.get(self._locale_value, {}).get(key, "") or fallback
        for name, value in fmt.items():
            text = text.replace("{" + name + "}", str(value))
        return text


zh = Stub("zh_CN")
en = Stub("en_US")
tw = Stub("zh_TW")

msg_auth = ("API Key 无效或没有权限（可能已过期/被撤销，或这把 Key 不属于当前服务商），"
            "请重新填写<API Key> 后再试（服务端说明：invalid api key）")
out_en = en._localized_error("auth", msg_auth)
check("英文界面下 401 错误变成英文", "API key is invalid" in out_en, out_en[:70])
check("英文错误里仍带可点的 <API Key>", "<API Key>" in out_en)
check("保留了 client 拼的「（服务端说明：…）」尾巴（排查信息不能被翻译吞掉）",
      "服务端说明：invalid api key" in out_en, out_en[-60:])
out_zh = zh._localized_error("auth", msg_auth)
check("中文界面保持中文", "API Key 无效或没有权限" in out_zh, out_zh[:40])
out_tw = tw._localized_error("auth", msg_auth)
check("繁体界面是繁体", "無效或沒有權限" in out_tw, out_tw[:40])

print("[4] 占位符必须被填掉（不能把 {status} 显示给用户）")
out = en._localized_error("server", "服务器出错（503）（服务端说明：x）", status=503)
check("{status} 被真实状态码替换", "503" in out and "{status}" not in out, out[:80])
out = en._localized_error("network", "连不上服务器：timed out")
check("{reason} 被原始原因替换", "timed out" in out and "{reason}" not in out, out[:80])
out = en._localized_error("unknown", "收到非预期的响应（HTTP 418）", status=0)
check("status=0 时不硬填占位符 → 整条退回原文（宁可不翻译也不显示坏文案）",
      "{status}" not in out, out[:80])

print("[5] 兜底：认不出就原样返回")
out = zh._localized_error("totally_unknown_kind", "某种没见过的错误")
check("未知 kind → 原样返回 message", out == "某种没见过的错误", out)
empty = Stub("en_US")
empty._text = lambda key, fallback, module="set", **fmt: ""
out = empty._localized_error("auth", msg_auth)
check("语言包缺键 → 退回 client 原文（绝不因为翻译失败丢报错）", out == msg_auth, out[:60])

print("[6] 固定回复：send 路径按语言出文案")
d = Stub("en_US")
hint = d._text("ai_no_key_chat", "还没有配置{missing}。请填写<API Key> 后再聊。",
               missing="API Key")
check("英文固定回复整句英文", hint.startswith("No API Key configured"), hint[:70])
check("英文固定回复里的 token 前端可点", any(tok in hint for tok in tokens), hint[:80])
d2 = Stub("zh_CN")
hint2 = d2._text("ai_no_key_chat", "还没有配置{missing}。请填写<API Key> 后再聊。", missing="API Key")
check("中文固定回复保留中文 token", "请填写<API Key>" in hint2, hint2[:60])

print("[7] 端到端：真实 LanguageManager（不桩 _text）—— 抓『模块名写错』这类静默失败")
# ⚠️ 为什么必须有这一段：[3]/[6] 里的 Stub 直接桩掉了 _text 的取数逻辑，
#    所以『模块名写错（set vs settings）导致永远查不到、静默退回中文』这种 bug
#    它们**全都测不出来**。只有走真实 manager 才能验到。
from pymodels.core import language_manager as lm                      # noqa: E402


class RealStub(AiDomain):
    """只桩 _locale()，**取文案走真实 LanguageManager**（读真实语言包）"""

    def __init__(self, locale):
        self._locale_value = locale
        self._shell = None

    def _locale(self):
        return self._locale_value


try:
    # ⚠️ LanguageManager 默认按 **CONFIG_DIR**（= 入口脚本旁的 .ToolsGCP）找语言包，
    #    本脚本在 _devtest/ 下 → 会指到 `_devtest/.ToolsGCP/modules/languages`（不存在），
    #    于是三语全空、只能走 en_fallback（表现成"键名被当成文案显示出来"）。
    #    真跑 ToolsGCP.pyw 时入口在根目录、路径是对的 —— 这是测试运行目录的产物，
    #    所以这里显式传真实的 languages 目录。
    manager = lm.LanguageManager(config_dir=os.path.join(BASE, ".ToolsGCP"))
    manager.load_all_languages()
    lm.set_current_manager(manager)
    MODULES = sorted((manager.translations.get("en_US", {}) or {}).keys())
    check("真实 manager 加载成功（en_US 模块数 >= 10）", len(MODULES) >= 10, str(len(MODULES)))
    check("set_language.json 对应的模块键是 settings（不是 set）",
          "settings" in MODULES and "set" not in MODULES, ",".join(MODULES[:6]))

    en = RealStub("en_US")
    zh = RealStub("zh_CN")
    tw = RealStub("zh_TW")
    check("英文：401 错误整句英文（真实取数，非桩）",
          en._localized_error("auth", "API Key 无效或没有权限（x），请重新填写<API Key> 后再试")
          .startswith("API key is invalid"),
          en._localized_error("auth", "API Key 无效或没有权限（x），请重新填写<API Key> 后再试")[:50])
    hint_en = en._text("ai_no_key_chat", "还没有配置{missing}。请填写<API Key> 后再聊。",
                       missing="API Key")
    check("英文：固定回复整句英文", hint_en.startswith("No API Key configured"), hint_en[:60])
    check("英文固定回复里不含简体汉字", not CJK.search(hint_en.replace("<API Key>", "")), hint_en[:70])
    hint_zh = zh._text("ai_no_key_chat", "ENGLISH-LEAK", missing="API Key")
    check("中文：同一条键取到中文（证明不是永远 fallback）",
          hint_zh.startswith("还没有配置"), hint_zh[:50])
    hint_tw = tw._text("ai_no_key_chat", "FALLBACK", missing="API Key")
    check("繁体：取到繁体（還沒有配置）", hint_tw.startswith("還沒有"), hint_tw[:50])
    # 反向：故意用错模块名，必须取不到（说明这条断言真的在查模块名，而不是恒真）
    wrong = en._text("ai_no_key_chat", "FALLBACK", module="set", missing="API Key")
    check("模块名写错时确实退回 fallback（证明本测试对模块名敏感、不是恒真）",
          wrong == "FALLBACK", wrong[:40])
except Exception as exc:
    check("真实 manager 端到端可跑", False, type(exc).__name__ + " " + str(exc)[:120])

print("=" * 72)
if FAILS:
    print(f"FAILED {len(FAILS)}:")
    for f in FAILS:
        print("   -", f)
    sys.exit(1)
print("ALL OK")
