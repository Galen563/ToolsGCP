# -*- coding: utf-8 -*-
"""AI 运行时元信息 + 回复语言 + 思考档位 + 资源全量 自检脚本（无头，不进主链路）。

打印**真实构建**的系统提示词，逐项验证：
  ① 模型身份（服务商 / 显示名 / api_model）
  ② 当前时间
  ③ 回复语言强制指令
  ④ 思考档位（各家官方档位表 + client 请求体）
  ⑤ 全量资源条数（应与 ToolsGCP-Resources.json 真实条数一致 = 52）
  ⑥ 能力清单（可用模型 / 已启用功能 / 已启用插件）
用法：在项目根目录运行
    python "项目资料-文档与开发测试/_devtest/check_ai_meta_runtime_prompt.py"
"""

import io
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path[:0] = [os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]


def hr(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main():
    from pymodels.core.ai import prompt as ai_prompt
    from pymodels.core.ai import providers as ai_providers
    from pymodels.core.ai import client as ai_client
    from pymodels.core.ai import capabilities as ai_caps

    # ---------- 资源库（真实 JSON） ----------
    hr("⑤ 资源库全量条数")
    res_path = os.path.join(ROOT, ".ToolsGCP", "ToolsGCP-Resources.json")
    with open(res_path, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    resources = data.get("resources") if isinstance(data, dict) else data
    resources = [r for r in resources if isinstance(r, dict)]
    print(f"资源库 JSON 真实条数: {len(resources)}")

    want_all_catalog = ai_prompt.build_resource_catalog(
        resources, "简体中文", keyword="", want_all=True)
    # 数一下带编号的行（全量模式每行以 "N｜" 开头）
    import re
    numbered = re.findall(r"(?m)^(\d+)｜", want_all_catalog)
    print(f"全量清单编号行数: {len(numbered)}（应为 {len(resources)}，"
          f"{'PASS' if len(numbered) == len(resources) else 'FAIL'}）")
    print(f"标题包含总数: {'PASS' if str(len(resources)) in want_all_catalog.splitlines()[0] + want_all_catalog[:200] else 'FAIL'}")
    print("清单前 5 行示例:")
    for line in want_all_catalog.splitlines()[:5]:
        print("   ", line)

    hr("⑤ want_all 意图判定（三语关键词）")
    probes = ["资源库里有哪些软件", "列出所有资源", "一共有多少个资源",
              "全部资源清单", "how many resources are there", "list all resources",
              "幫我看下全部的資源", "帮我找一个局域网传文件的工具"]
    for p in probes:
        print(f"   wants_all={ai_prompt.wants_all_resources(p)!s:>5}  <- {p}")
    # 52 条 ≤ FULL_CATALOG_LIMIT(400) → **任何**提问都给全量（根治"只知道一部分"）
    normal = ai_prompt.build_resource_catalog(resources, "简体中文", "局域网传文件")
    print(f"   普通提问是否也给全量: {'【资源库清单 · 完整版】' in normal}"
          f"（编号行数={len(re.findall(r'(?m)^[0-9]+｜', normal))}）")

    hr("④ 各家官方思考档位表 providers.thinking_levels()")
    cases = [
        ("deepseek", "deepseek-v4.1-flash"),
        ("deepseek", "deepseek-v4-pro"),
        ("openai", "gpt-5.1"),
        ("claude", "claude-sonnet-4-6"),
        ("grok", "grok-4"),
        ("kimi", "kimi-k3"),
        ("qwen", "qwen3-max"),
        ("custom", "gemini-2.5-pro"),
        ("siliconflow", "deepseek-ai/DeepSeek-V3"),
        ("openai", "gpt-4.1"),          # 不支持思考 → 只有 off
    ]
    for pid, name in cases:
        levels = ai_providers.thinking_levels(pid, name)
        print(f"   {pid:>11} / {name:<28} -> "
              + ", ".join(f"{r['value']}({r['label']},effort={r['effort']},"
                          f"style={r.get('style')})" for r in levels))
        # ⚠️ 断言更新（官方档位那一轮）：第一档**不再恒为 off** ——
        #    kimi-k3 / k3.1-pro 官方 thinking 恒开、只有 low/high/max（没有关这一档），
        #    kimi-k2.7-code 更是只有单档 on。所以这里改成校验"第一档必须是表内合法值、
        #    且档位名全部是官方英文名（不含中文）"，比死盯 off 更贴近真实契约。
        assert levels, f"{pid}/{name} 档位表不能为空"
        for row in levels:
            assert row["value"] and row["label"], f"{pid}/{name} 档位缺 value/label"
            assert all(ord(ch) < 128 for ch in str(row["label"])), \
                f"{pid}/{name} 档位名必须是官方英文，实际={row['label']!r}"
        # 支持关思考的模型（表内有 off）第一档仍应为 off（保持旧可读性）
        if any(r["value"] == "off" for r in levels):
            assert levels[0]["value"] == "off", f"{pid}/{name} 有 off 却不是第一档"

    hr("④ client._thinking_params() 各家请求体")
    for pid, name in cases[:8]:
        for row in ai_providers.thinking_levels(pid, name)[:3]:
            params = ai_client._thinking_params(row, pid, name)
            print(f"   {pid:<11} {name:<24} value={row['value']:<8} -> {json.dumps(params, ensure_ascii=False)}")
    # 向后兼容：旧字符串档位 + 无 provider 信息
    for legacy in [None, "", "off", "low", "medium", "high", True, False]:
        print(f"   [兼容旧调用] thinking={legacy!r} -> "
              f"{json.dumps(ai_client._thinking_params(legacy), ensure_ascii=False)}")

    hr("①+②+③+⑥ 真实构建的运行时元信息段 + 完整 system 头部")
    meta = ai_prompt.build_runtime_meta(
        provider_label=ai_providers.provider_display("deepseek"),
        display_model="deepseek-v4.1-flash",
        api_model=ai_providers.resolve_api_model("deepseek", "deepseek-v4.1-flash"),
        reply_language="zh_CN",
        thinking_text=ai_providers.thinking_levels("deepseek", "deepseek-v4.1-flash")[1]["value"]
        + "（low，DeepSeek 官方档位）",
        features_text=ai_caps.enabled_features_text(
            {"gcp_ai_agent_enabled": False, "ai_polish_enabled": True},
            resource_count=len(resources)),
        models_text="（devtest 无 Key 槽位，模拟）DeepSeek（深度求索）: deepseek-v4.1-flash, deepseek-v4-pro",
        plugins_text=ai_caps.enabled_plugins_text("zh_CN"),
    )
    print(meta)

    # 走 desktop/api/ai.py 的真实 _runtime_meta：用一个最小假 shell
    hr("desktop/api/ai.py AiDomain._runtime_meta（真桥接层）")
    from desktop.api.ai import AiDomain

    class FakeSettings:
        def __init__(self):
            self.settings = {
                "ai_provider": "deepseek",
                "model_name": "deepseek-v4.1-flash",
                "ai_reply_language": "zh_CN",
                "ai_thinking": "low",
                "language": "简体中文",
            }
        def get_api_key(self, provider=""):
            return "sk-dummy" if provider in ("deepseek", "") else ""
        def key_tail(self, provider=""):
            return "mmy"

    class FakeShell:
        settings_manager = FakeSettings()
        api = None
        current_language = lambda self: "简体中文"

    domain = AiDomain(FakeShell())
    row = domain._thinking_state("deepseek", "deepseek-v4.1-flash")
    meta2 = domain._runtime_meta("deepseek", "deepseek-v4.1-flash",
                                 "deepseek-flash", row)
    print(meta2)

    # ---------- 完整 system 消息 ----------
    hr("完整 system（build_messages 真实输出，检查必含要素）")
    msgs = ai_prompt.build_messages(
        [{"role": "user", "content": "资源库里有哪些软件？全部列一下"}],
        resources, "简体中文", keyword="",
        mode="standard", meta=meta2, want_all=True, reply_language="zh_CN")
    system = msgs[0]["content"]
    checks = {
        "模型身份（服务商行）": "当前服务商" in system,
        "显示名": "deepseek-v4.1-flash" in system,
        "api_model（与显示名不同的说明）": "deepseek-flash" in system,
        "当前时间": "当前时间：" in system,
        "星期": "星期" in system,
        "回复语言强制指令": "【输出语言】" in system and "一律使用简体中文" in system,
        "思考档位": "当前思考档位" in system,
        "全量资源标题+总数": "【资源库清单 · 完整版】" in system,
        "全部编号行数=52": len(re.findall(r"(?m)^(\d+)｜", system)) == len(resources),
        "能力清单-可用模型": "可用（已配 API Key）的服务商与模型" in system,
        "能力清单-已启用功能": "已启用的功能" in system or "已开启：" in system,
        "能力清单-已启用插件": "已启用插件" in system,
    }
    for k, v in checks.items():
        print(f"   [{'PASS' if v else 'FAIL'}] {k}")
    print(f"\nsystem 总长度: {len(system)} 字符")
    print("system 前 30 行:")
    for line in system.splitlines()[:30]:
        print("   ", line[:110])

    # list_all_resources 工具
    hr("agent 工具 list_all_resources")
    from pymodels.core.ai import agent_tools
    reg = agent_tools.get_registry()
    tool = reg.get("list_all_resources")
    print("   注册:", bool(tool), "| spec:", tool.spec("zh_CN")[:80] if tool else "-")

    class FakeDomain:
        def _resources(self):
            return resources
    outcome = reg.execute("list_all_resources", {"offset": 0}, agent=FakeDomain())
    print(f"   执行 ok={outcome.get('ok')} total="
          f"{(outcome.get('data') or {}).get('total')} returned="
          f"{(outcome.get('data') or {}).get('returned')} complete="
          f"{(outcome.get('data') or {}).get('complete')}")
    fmt = agent_tools.format_result("list_all_resources", outcome)
    print(f"   format_result 长度={len(fmt)}（预算 1200，是否截断: "
          f"{'已截断!' if len(fmt) >= 1200 else '未截断 PASS'}）")

    print("\n全部检查完成。")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    main()
