# -*- coding: utf-8 -*-
"""ToolsGCP GCP-AI 三个 Bug 修复 的自测脚本（修复前基线应 FAIL，修复后应全 PASS）。

用法：
    python 项目资料-文档与开发测试/_devtest/ai_fix_selftest.py
在 DSH 沙箱里跑（进程不允许往系统临时目录写文件）时先设：
    TOOLSGCP_TEST_TMP=<工作区某目录>   （脚本会把测试文件建在它下面）

覆盖：
  A. 后端行为（临时目录 + monkeypatch，绝不碰真实 ~/.ToolsGCP）
     · DeepSeek 模型清单/默认模型
     · API Key 按服务商分槽读写 / 旧单槽迁移 / 清洗 / 尾号掩码
     · ai.send 失败也落盘错误气泡（error/kind/persisted/当前配置）
     · ai.send 成功落盘回答；no_key 引导回答落盘
     · ai.send(resend=True)：摘掉旧回答、不重复落用户消息
     · prompt.build_messages 跳过 error 消息
     · ai.test_connection 信封字段
  B. 前端/CSS/语言包静态断言
     · app.js 的 AI_PROVIDERS、sessionToMessages 重建、error 映射、
       按服务商存 Key、测试连接、resend 第 4 参、启动总是新对话
     · index.html 两处气泡 error 类绑定 + 测试连接按钮
     · components.css：bubble-wrap 限宽 / 气泡 100% / .is-error
     · 三语 set_language.json：新词条齐全、模型示例名已更新
     · 全仓 grep 不应再出现 deepseek-v4.1-flash（排除 备份/py版本 存档）
"""
import json
import os
import re
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(REPO, ".ToolsGCP"),
                os.path.join(REPO, ".ToolsGCP", "modules")]

# ---------- 测试临时目录（沙箱里要能写） ----------
_TMP_BASE = os.environ.get("TOOLSGCP_TEST_TMP") or ""
import tempfile


def _mk(name):
    """建一个可写的测试目录；沙箱里 tempfile.mkdtemp 会被拦，改用固定根+唯一名。"""
    if _TMP_BASE:
        d = os.path.join(_TMP_BASE, name + "-" + os.urandom(4).hex())
        os.makedirs(d, exist_ok=True)
        return d
    return tempfile.mkdtemp(prefix="ai-fix-" + name + "-")


_passed = 0
_failed = 0
_errors = []


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print("[PASS]", name)
    else:
        _failed += 1
        print("[FAIL]", name, (detail if detail else ""))
        _errors.append(name)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# =====================================================================
# A. 后端行为
# =====================================================================
from pymodels.core.settings_manager import SettingsManager
from pymodels.core.ai import providers as P
from pymodels.core.ai import prompt as PROMPT
from pymodels.core.ai import client as CLIENT
from pymodels.core.ai.chat_store import ChatSession
from desktop.api.ai import AiDomain

# --- A1 模型清单（界面显示名 deepseek-v4.1-flash；发送时内部转官方 API 名） ---
names = P.models_of("deepseek")
check("A1 deepseek 含 deepseek-v4.1-flash（界面显示名）",
      "deepseek-v4.1-flash" in names, names)
check("A1 deepseek 含 deepseek-v4-pro", "deepseek-v4-pro" in names, names)
check("A1 默认 = deepseek-v4.1-flash",
      P.default_model("deepseek") == "deepseek-v4.1-flash",
      P.default_model("deepseek"))

# --- A1b 官方 API 名解析（用户确认：deepseek-v4.1-flash 或 deepseek-v4-pro；
#       官方文档 API 名是 deepseek-flash，由 resolve_api_model 转换，调用不能错） ---
check("A1b v4.1-flash → API 名 deepseek-flash",
      P.resolve_api_model("deepseek", "deepseek-v4.1-flash") == "deepseek-flash",
      P.resolve_api_model("deepseek", "deepseek-v4.1-flash"))
check("A1b v4-pro 原样", P.resolve_api_model("deepseek", "deepseek-v4-pro")
      == "deepseek-v4-pro", P.resolve_api_model("deepseek", "deepseek-v4-pro"))
check("A1b 已是 API 名原样", P.resolve_api_model("deepseek", "deepseek-flash")
      == "deepseek-flash", P.resolve_api_model("deepseek", "deepseek-flash"))
check("A1b 自定义名原样", P.resolve_api_model("deepseek", "my-model-x")
      == "my-model-x", P.resolve_api_model("deepseek", "my-model-x"))
check("A1b 其它服务商不转换", P.resolve_api_model("kimi", "deepseek-v4.1-flash")
      == "deepseek-v4.1-flash", P.resolve_api_model("kimi", "deepseek-v4.1-flash"))

# --- A2 Key 按服务商分槽 / 迁移 / 清洗 / 掩码 ---
m = SettingsManager(config_dir=_mk("keys"))
m.set_api_key("  sk-test-1111  ", "deepseek")
m.set_api_key("kimi-key-2222", "kimi")
check("A2 deepseek key 读写", m.get_api_key("deepseek") == "sk-test-1111",
      m.get_api_key("deepseek"))
check("A2 kimi key 读写", m.get_api_key("kimi") == "kimi-key-2222", m.get_api_key("kimi"))
check("A2 服务商互不串 Key", m.get_api_key("kimi") != m.get_api_key("deepseek"))
check("A2 key_tail 掩码", m.key_tail("deepseek") == "****1111", m.key_tail("deepseek"))

m2 = SettingsManager(config_dir=_mk("migrate"))
m2.settings["api_key_enc"] = "plain:YWJjZDEyMzQ="  # base64("abcd1234")，unprotect 按明文返回
m2.settings["ai_provider"] = "deepseek"
v = m2.get_api_key()
check("A2 旧单槽迁移到当前服务商", v == "abcd1234", v)
check("A2 迁移后旧槽清空", m2.settings.get("api_key_enc", "") == "",
      m2.settings.get("api_key_enc"))
check("A2 迁移后槽里有值", bool(m2.settings.get("api_key_enc_deepseek", "")))

from pymodels.utils.secret_store import sanitize_api_key
check("A2 清洗 Bearer/引号/零宽",
      sanitize_api_key('\u200b"Bearer sk-abc-1234"\u200b') == "sk-abc-1234",
      sanitize_api_key('\u200b"Bearer sk-abc-1234"\u200b'))

# --- A3/A4 发送落盘 ---
class FakeShell:
    def __init__(self, manager):
        self.settings_manager = manager

    def current_language(self):
        return "简体中文"


def _make_domain():
    tmpd = _mk("chat")
    import pymodels.core.ai.chat_store as cs
    cs.CHATS_DIR = tmpd
    mgr = SettingsManager(config_dir=tmpd)
    mgr.set_api_key("sk-ok-1111", "deepseek")
    mgr.settings["ai_provider"] = "deepseek"
    mgr.settings["model_name"] = "deepseek-v4.1-flash"
    mgr.settings["api_base"] = "https://api.deepseek.com/v1"
    mgr.save_settings(mgr.settings)
    return AiDomain(FakeShell(mgr)), cs, tmpd


def run_send(chat_result, resend=False, text="你好"):
    domain, cs, _ = _make_domain()
    orig = CLIENT.chat
    CLIENT.chat = lambda messages, api_key, model, api_base, **kw: chat_result
    try:
        return domain.send("", text, resend=resend)
    finally:
        CLIENT.chat = orig


# 失败分支：错误气泡必须落盘
r = run_send(CLIENT.ChatResult(False, kind="auth", message="API Key 无效或没有权限"))
check("A3 失败 ok=false", r.get("ok") is False)
check("A3 失败 kind=auth", r.get("kind") == "auth", r.get("kind"))
check("A3 失败 persisted=True", r.get("persisted") is True, r.get("persisted"))
last = (r.get("session") or {}).get("messages", [])[-1]
check("A3 失败错误气泡已落盘(error=True)",
      last.get("role") == "assistant" and last.get("error") is True, last)
check("A3 失败气泡带 kind", last.get("kind") == "auth", last.get("kind"))
check("A3 错误文本含当前配置", "当前配置" in (last.get("content") or ""),
      (last.get("content") or "")[-60:])
import pymodels.core.ai.chat_store as csm
check("A3 会话文件真实存在",
      os.path.isfile(os.path.join(csm.CHATS_DIR, r["session_id"] + ".json")))

# 成功分支
r = run_send(CLIENT.ChatResult(True, content="推荐：Everything —— 本地文件搜索"))
check("A4 成功 ok=true", r.get("ok") is True)
last = (r.get("session") or {}).get("messages", [])[-1]
check("A4 成功回答落盘", last.get("role") == "assistant" and "推荐" in (last.get("content") or ""), last)
check("A4 成功消息 error=False", last.get("error") is False, last)

# no_key 分支（先把 Key 槽清掉，再把 client.chat 钉死，避免误发真实请求）
domain, cs, _ = _make_domain()
domain.settings_manager.settings["api_key_enc_deepseek"] = ""
domain.settings_manager.settings["model_name"] = "deepseek-v4.1-flash"
orig = CLIENT.chat
CLIENT.chat = lambda *a, **kw: CLIENT.ChatResult(False, kind="no_key", message="unused")
try:
    r = domain.send("", "你好")
finally:
    CLIENT.chat = orig
check("A4 no_key ok=true kind=no_key",
      r.get("ok") is True and r.get("kind") == "no_key", r.get("kind"))
msgs = (r.get("session") or {}).get("messages", [])
check("A4 no_key 引导回答落盘", len(msgs) == 2 and msgs[1].get("role") == "assistant", msgs)

# resend：先有旧回答，再 resend → 旧回答被摘掉、用户消息不重复、新回答在
domain, cs, _ = _make_domain()
orig = CLIENT.chat
CLIENT.chat = lambda messages, api_key, model, api_base, **kw: CLIENT.ChatResult(
    True, content="第一版回答")
try:
    r1 = domain.send("", "帮我找个工具")
finally:
    CLIENT.chat = orig
sid = r1["session_id"]
CLIENT.chat = lambda messages, api_key, model, api_base, **kw: CLIENT.ChatResult(
    True, content="重新生成后的回答")
try:
    r2 = domain.send(sid, "帮我找个工具", resend=True)
finally:
    CLIENT.chat = orig
msgs = (r2.get("session") or {}).get("messages", [])
contents = [m.get("content") for m in msgs]
check("A5 resend 摘掉旧回答", "第一版回答" not in contents, contents)
check("A5 resend 不重复用户消息", contents.count("帮我找个工具") == 1, contents)
check("A5 resend 新回答落盘", "重新生成后的回答" in contents, contents)

# prompt 跳过 error
sess = ChatSession()
sess.messages = [{"role": "user", "content": "你好"},
                 {"role": "assistant", "content": "报错啦", "error": True, "kind": "auth"},
                 {"role": "assistant", "content": "正常回答"}]
out = PROMPT.build_messages(sess.messages, [], "简体中文", context_rounds=0)
contents = [m.get("content") for m in out]
check("A6 error 消息不进上下文", "报错啦" not in contents, contents)
check("A6 正常回答仍在上下文", "正常回答" in contents, contents)

# test_connection
domain, cs, _ = _make_domain()
orig = CLIENT.chat
CLIENT.chat = lambda messages, api_key, model, api_base, **kw: CLIENT.ChatResult(True, content="pong")
try:
    r = domain.test_connection()
finally:
    CLIENT.chat = orig
check("A7 test_connection ok", r.get("ok") is True, r)
check("A7 字段齐全", r.get("kind") == "ok" and r.get("model") == "deepseek-v4.1-flash"
      and r.get("provider") == "deepseek" and r.get("key_tail") == "****1111"
      and r.get("latency_ms") is not None, r)

# =====================================================================
# B. 前端 / CSS / 语言包静态断言
# =====================================================================
APP_JS = _read(os.path.join(REPO, ".ToolsGCP", "webui", "js", "app.js"))
INDEX = _read(os.path.join(REPO, ".ToolsGCP", "webui", "index.html"))
CSS = _read(os.path.join(REPO, ".ToolsGCP", "webui", "css", "components.css"))

# 模型名：界面清单/默认 = deepseek-v4.1-flash（用户认识的名字）
check("B1 AI_PROVIDERS 含 deepseek-v4.1-flash（界面显示名）",
      "'deepseek-v4.1-flash'" in APP_JS)
check("B16 新增「模型选择」下拉（服务商与模型名称之间）",
      "label: t('model_select', '模型选择')" in APP_JS
      and "key: 'model_name', type: 'select'" in APP_JS)
check("B16 「模型选择」是纯下拉（不可输入）",
      (lambda: (
          "editable: true" not in APP_JS.split("label: t('model_select'")[1][:500]
          if "label: t('model_select'" in APP_JS else False))())
check("B16 「模型名称」输入框保留（可自定义任意名称）",
      "key: 'model_name', type: 'text', wide: true" in APP_JS
      and "datalist: provider.models" in APP_JS)
check("B16 下拉选项含自定义当前值（显示不错位）",
      "modelOptions.push(curModel)" in APP_JS)
check("B16 不再自动纠正模型名（不替用户改）",
      "saveSetting('model_name', next)" not in APP_JS)
check("B16 combo 透传 editable/placeholder",
      ":editable=\"!!row.editable\"" in INDEX
      and ":placeholder=\"row.placeholder || ''\"" in INDEX)
check("B2 aiSend 以 session.messages 重建气泡", "sessionToMessages(session)" in APP_JS)
check("B2 loadAiSession 还原 error/kind",
      "error: !!m.error" in APP_JS and "kind: String(m.kind || '')" in APP_JS)
check("B2 openAiSession 失败 toast",
      "ai_history_load_failed" in APP_JS and "return;" in APP_JS)
check("B3 保存 Key 带服务商", "settings.set_api_key', key," in APP_JS
      or "settings.set_api_key', key" in APP_JS)
check("B3 清空 Key 带服务商", "settings.set_api_key', ''," in APP_JS)
check("B3 显示 Key 带服务商", "settings.reveal_api_key'," in APP_JS)
check("B3 切换服务商拉取 Key", "loadApiKeyForProvider(value)" in APP_JS)
check("B4 测试连接调用", "ai.test_connection" in APP_JS)
check("B5 resend 第 4 参", "ai.send', aiSessionId.value || '', text," in APP_JS
      and "!!resend" in APP_JS)
check("B6 启动总是新对话",
      "loadAiOnBoot" in APP_JS and "ai.new_session" in APP_JS
      and "loadAiSession('')" not in APP_JS)
check("B7 历史仍可加载（openAiSession 用 loadAiSession）", "loadAiSession(sessionId)" in APP_JS)

# index.html
check("B8 两处气泡 error 类绑定", INDEX.count("'is-error': !!m.error") >= 2,
      INDEX.count("'is-error': !!m.error"))
check("B9 测试连接按钮", "testAiConnection" in INDEX and "ai_test_connection" in INDEX)

# CSS
check("B10 bubble-wrap 限宽 78%", ".bubble-wrap" in CSS and "max-width: 78%" in CSS)
check("B11 包裹层内气泡 100%", ".bubble-wrap > .bubble" in CSS and "max-width: 100%" in CSS)
check("B12 报错气泡样式", ".bubble.is-error" in CSS)

# 语言包
langs = {}
for loc in ("zh_CN", "zh_TW", "en_US"):
    langs[loc] = json.load(open(os.path.join(
        REPO, ".ToolsGCP", "modules", "languages", loc, "set_language.json"),
        encoding="utf-8"))
    need = ["ai_test_connection", "ai_testing", "ai_test_ok", "ai_test_failed",
            "ai_key_for_provider_missing", "ai_key_for_provider_saved",
            "model_select", "model_select_tip"]
    missing = [k for k in need if k not in langs[loc]]
    check("B13 %s 新词条齐全" % loc, not missing, missing)
    check("B14 %s 模型示例名 = deepseek-v4.1-flash（官方名）" % loc,
          "deepseek-v4.1-flash" in langs[loc].get("ai_error_no_model", ""),
          langs[loc].get("ai_error_no_model"))

# 前端只显示界面名（deepseek-v4.1-flash）；API 内部名（deepseek-flash）由后端
# resolve_api_model 转换，不出现在前端清单/语言包里。
LEGACY = re.compile(r"deepseek-flash")
hits = []
WEB = [os.path.join(REPO, ".ToolsGCP", "webui", "js", "app.js")] + [
    os.path.join(REPO, ".ToolsGCP", "modules", "languages", loc, "set_language.json")
    for loc in ("zh_CN", "zh_TW", "en_US")]
for p in WEB:
    if LEGACY.search(_read(p)):
        hits.append(os.path.relpath(p, REPO))
check("B15 前端清单/语言包不出现 API 内部名 deepseek-flash", not hits, hits[:5])

# =====================================================================
print("\n==== ai_fix_selftest: %d passed, %d failed ====" % (_passed, _failed))
if _failed:
    print("Failed:", _errors)
sys.exit(1 if _failed else 0)
