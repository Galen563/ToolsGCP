# -*- coding: utf-8 -*-
"""本轮 GCP-AI 改造新增的多语言键（三语各写一遍，跑完即删）。

只做一件事：在 set_language.json 的 `ai_thinking` 那一行后面插入新键。
⚠️ 幂等：已经存在同名键就跳过（不重复插、不覆盖已有译文）。
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NEW = {
    "zh_CN": {
        "ai_think_streaming": "正在思考…",
        "ai_thought_seconds": "已深度思考（用时 {n} 秒）",
        "ai_thought_done": "已思考",
        "ai_think_collapse": "{text} · 收起",
        "ai_think_expand": "{text} · 展开",
        "ai_think_label": "思考",
        "ai_think_on_tip": "思考已开启：回答会先展示模型的思考过程",
        "ai_think_off_tip": "开启后回答会带上可展开/收起的思考过程",
        "ai_think_on_toast": "已开启思考：回答会先展示模型的思考过程",
        "ai_think_off_toast": "已关闭思考",
        "ai_on": "开",
        "ai_off": "关",
        "ai_model_tip": "切换模型（只显示已填 Key 的服务商）",
        "ai_model_pick": "选择模型",
        "ai_model_no_key": "未配置 API Key",
        "ai_model_no_key_body": "还没有任何服务商填过 API Key。",
        "ai_model_go_settings": "去设置里填写",
        "ai_model_thinking": "思考",
        "ai_model_switched": "已切换到 {name}",
        "ai_at_tip": "↑↓ 选择 · Enter 插入 · Esc 关闭",
        "ai_ctx_copy_all": "复制",
        "ai_ctx_copy_sel": "复制选中内容",
        "ai_ctx_select_all": "全选",
        "ai_ctx_deselect": "取消全选",
        "ai_polish_undo": "返回上一个",
    },
    "zh_TW": {
        "ai_think_streaming": "正在思考…",
        "ai_thought_seconds": "已深度思考（用時 {n} 秒）",
        "ai_thought_done": "已思考",
        "ai_think_collapse": "{text} · 收合",
        "ai_think_expand": "{text} · 展開",
        "ai_think_label": "思考",
        "ai_think_on_tip": "思考已開啟：回答會先顯示模型的思考過程",
        "ai_think_off_tip": "開啟後回答會帶上可展開／收合的思考過程",
        "ai_think_on_toast": "已開啟思考：回答會先顯示模型的思考過程",
        "ai_think_off_toast": "已關閉思考",
        "ai_on": "開",
        "ai_off": "關",
        "ai_model_tip": "切換模型（僅顯示已填 Key 的服務商）",
        "ai_model_pick": "選擇模型",
        "ai_model_no_key": "未配置 API Key",
        "ai_model_no_key_body": "還沒有任何服務商填過 API Key。",
        "ai_model_go_settings": "到設定裡填寫",
        "ai_model_thinking": "思考",
        "ai_model_switched": "已切換到 {name}",
        "ai_at_tip": "↑↓ 選擇 · Enter 插入 · Esc 關閉",
        "ai_ctx_copy_all": "複製",
        "ai_ctx_copy_sel": "複製選取內容",
        "ai_ctx_select_all": "全選",
        "ai_ctx_deselect": "取消全選",
        "ai_polish_undo": "返回上一個",
    },
    "en_US": {
        "ai_think_streaming": "Thinking…",
        "ai_thought_seconds": "Deeply thought ({n} s)",
        "ai_thought_done": "Thought",
        "ai_think_collapse": "{text} · Collapse",
        "ai_think_expand": "{text} · Expand",
        "ai_think_label": "Thinking",
        "ai_think_on_tip": "Thinking is on: the answer shows the model's reasoning first",
        "ai_think_off_tip": "Turn on to show a collapsible reasoning block",
        "ai_think_on_toast": "Thinking enabled: answers will show the reasoning first",
        "ai_think_off_toast": "Thinking disabled",
        "ai_on": "On",
        "ai_off": "Off",
        "ai_model_tip": "Switch model (only providers with an API key are listed)",
        "ai_model_pick": "Choose model",
        "ai_model_no_key": "No API key",
        "ai_model_no_key_body": "No provider has an API key yet.",
        "ai_model_go_settings": "Set one up",
        "ai_model_thinking": "Thinking",
        "ai_model_switched": "Switched to {name}",
        "ai_at_tip": "↑↓ select · Enter insert · Esc close",
        "ai_ctx_copy_all": "Copy",
        "ai_ctx_copy_sel": "Copy selection",
        "ai_ctx_select_all": "Select all",
        "ai_ctx_deselect": "Deselect",
        "ai_polish_undo": "Undo polish",
    },
}

changed = []
for locale, table in NEW.items():
    path = os.path.join(ROOT, ".ToolsGCP", "modules", "languages", locale, "set_language.json")
    with io.open(path, encoding="utf-8") as fh:
        text = fh.read()
    data = json.loads(text)
    todo = {k: v for k, v in table.items() if k not in data}
    if not todo:
        print(f"{locale}: 全部已存在，跳过")
        continue
    # 用 json 重新序列化会打乱既有顺序/缩进 —— 改成**文本插入**：
    # 在 "ai_thinking": "...", 这一行后面追加，其余字节原样不动。
    lines = text.split("\n")
    out = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and '"ai_thinking"' in line:
            if not line.rstrip().endswith(","):
                out[-1] = line.rstrip() + ","
            block = ["  %s: %s," % (json.dumps(k, ensure_ascii=False),
                                     json.dumps(v, ensure_ascii=False))
                     for k, v in todo.items()]
            out.extend(block)
            inserted = True
    if not inserted:
        print(f"{locale}: 没找到 ai_thinking 锚点，跳过（请手工检查）")
        continue
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out))
    # 写完立刻验一遍 JSON 还能解析，坏了就报错退出
    with io.open(path, encoding="utf-8") as fh:
        json.load(fh)
    changed.append((locale, len(todo)))
    print(f"{locale}: 新增 {len(todo)} 个键，JSON 校验通过")

print("DONE", changed)
