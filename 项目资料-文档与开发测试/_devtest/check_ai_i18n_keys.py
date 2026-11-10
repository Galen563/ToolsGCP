# -*- coding: utf-8 -*-
"""检查前端用到的 i18n key 在三语 set_language.json（以及全部语言模块）里是否齐全。

只针对**本轮 GCP-AI 改造新增**的 key（脚本里显式列出），避免把历史遗留问题也算进来。
跑法：python "项目资料-文档与开发测试/_devtest/check_ai_i18n_keys.py"
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 本轮新增（与 add_ai_i18n_keys.py 同一份清单 + 模板里额外用到的）
KEYS = [
    "ai_think_streaming", "ai_thought_seconds", "ai_thought_done",
    "ai_think_collapse", "ai_think_expand", "ai_think_label",
    "ai_think_on_tip", "ai_think_off_tip", "ai_think_on_toast", "ai_think_off_toast",
    "ai_on", "ai_off",
    "ai_model_tip", "ai_model_pick", "ai_model_no_key", "ai_model_no_key_body",
    "ai_model_go_settings", "ai_model_thinking", "ai_model_switched",
    "ai_at_tip", "ai_ctx_copy_all", "ai_ctx_copy_sel", "ai_ctx_select_all",
    "ai_ctx_deselect", "ai_polish_undo",
]

fail = []
for locale in ("zh_CN", "zh_TW", "en_US"):
    path = os.path.join(ROOT, ".ToolsGCP", "modules", "languages", locale,
                        "set_language.json")
    data = json.load(io.open(path, encoding="utf-8"))
    missing = [k for k in KEYS if k not in data]
    print(f"{locale}: {'OK 全部齐全' if not missing else 'MISSING ' + str(missing)}")
    if missing:
        fail.append(locale)

# 顺带确认 app.js 里本轮新增代码用到的 key 都在清单内（防漏写）
app = io.open(os.path.join(ROOT, ".ToolsGCP", "webui", "js", "app.js"),
              encoding="utf-8").read()
html = io.open(os.path.join(ROOT, ".ToolsGCP", "webui", "index.html"),
               encoding="utf-8").read()
used = set(re.findall(r"t\('(ai_[a-z_]+)'", app)) | set(re.findall(r"t\('(ai_[a-z_]+)'", html))
new_used = {k for k in used if k in KEYS or k.startswith(("ai_think", "ai_model", "ai_at",
                                                           "ai_ctx", "ai_thought",
                                                           "ai_polish_undo"))}
not_in_list = sorted(new_used - set(KEYS))
print("本轮用到但清单里没有的 key：", not_in_list or "无")
for locale in ("zh_CN", "zh_TW", "en_US"):
    path = os.path.join(ROOT, ".ToolsGCP", "modules", "languages", locale,
                        "set_language.json")
    data = json.load(io.open(path, encoding="utf-8"))
    miss = [k for k in not_in_list if k not in data]
    if miss:
        print(f"  !! {locale} 也缺这些：{miss}")
        fail.append(locale + "-extra")

if fail:
    print("FAILED", fail)
    sys.exit(1)
print("ALL OK")
