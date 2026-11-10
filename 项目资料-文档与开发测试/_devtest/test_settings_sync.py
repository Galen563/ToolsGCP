# -*- coding: utf-8 -*-
"""桌面端 ↔ 浏览器端「配置类改动」同步的单测（task-1 第 3 项）。

用户原话：「桌面端和浏览器端同时开启时他们更改是同步更改的而不是一个端更改了另一个端的
ui 还是原来之前的样子……需要改动的是有配置存储的需要同步」。

根因（已定位）：后端 `settings.set(key, value, notify)` 只在 `notify=True` 时才广播
`settings-changed`，而**前端所有 saveSetting 都传 false** → 这条事件实际上从来没为
用户改动发过，另一端自然收不到。修法：值真的变了就广播（notify 参数保留兼容）。

本脚本验三件事（全程不起窗口、不碰用户配置）：
  ① 值变了 → 广播；值没变 → 不广播（省掉无谓推送）。
  ② 敏感项（api_key* / license_key / dev_mode_key）**一律不广播**：
     push_event 会经 HTTP 长轮询投给浏览器端，推明文 Key = 泄密；
     也不能"广播但抹空值"（另一端会把空串写回自己正在填的输入框）。
  ③ 收藏写操作仍然广播（回归：这条本来就是对的，别被我改坏）。

跑法：python "项目资料-文档与开发测试/_devtest/test_settings_sync.py"
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.argv = [os.path.join(ROOT, "ToolsGCP.pyw")]
sys.path[:0] = [ROOT, os.path.join(ROOT, ".ToolsGCP"),
                os.path.join(ROOT, ".ToolsGCP", "modules")]

import pymodels.constants as constants_mod                    # noqa: E402
from pymodels.core.settings_manager import SettingsManager    # noqa: E402
from pymodels.core.favorites_manager import FavoritesManager  # noqa: E402
from desktop.api.resources import SettingsDomain, FavoritesDomain  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}" + (f"  <- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


class _Shell:
    """只收事件，不碰任何窗口；两个域都从 shell 上取 manager（property 不可赋值）"""

    def __init__(self):
        self.events = []
        self.settings_manager = None
        self.favorites_manager = None

    def current_language(self):
        return "简体中文"

    def push_event(self, name, payload):
        self.events.append((name, payload))

    def settings_changed(self):
        return [p for n, p in self.events if n == "settings-changed"]

    def fav_changed(self):
        return [p for n, p in self.events if n == "favorites-changed"]


def make(tmp, name):
    cfg = os.path.join(tmp, name)
    shutil.rmtree(cfg, ignore_errors=True)
    os.makedirs(cfg, exist_ok=True)
    shell = _Shell()
    manager = SettingsManager(config_dir=cfg)
    shell.settings_manager = manager
    shell.favorites_manager = FavoritesManager(config_dir=cfg)
    # 迁移/测试期间绝不把用户真实配置写回去（update_setting 只改内存）
    os.environ["TOOLSGCP_NO_SETTINGS_WRITE"] = "1"
    return shell, manager, cfg


TMP = os.path.join(ROOT, "项目资料-文档与开发测试", "_tmp-ai-test", "settings-sync")
os.makedirs(TMP, exist_ok=True)

print("[1] 值真的变了 → 广播 settings-changed（前端传 notify=false 也要发）")
shell, manager, cfg = make(TMP, "a")
domain = SettingsDomain(shell)
res = domain.set("theme", "浅色主题", False)        # 前端就是这么调的（notify=False）
check("set 返回 ok", res.get("ok") is True, str(res)[:120])
check("广播了一条", len(shell.settings_changed()) == 1,
      str(shell.settings_changed()))
got = shell.settings_changed()[0]
check("载荷形状 {key,old,new}",
      set(got.keys()) >= {"key", "old", "new"} and got["key"] == "theme"
      and got["new"] == "浅色主题", str(got))

print("[2] 值没变 → 不广播（不刷屏、不无谓起线程）")
before = len(shell.settings_changed())
domain.set("theme", "浅色主题", False)
check("重复写同一个值不产生新事件",
      len(shell.settings_changed()) == before,
      f"{before} -> {len(shell.settings_changed())}")

print("[3] notify=True 仍然广播（老调用方语义不变）")
before = len(shell.settings_changed())
domain.set("accent_color", "purple", True)
check("notify=True 广播", len(shell.settings_changed()) == before + 1)

print("[4] 敏感项一律不广播（明文 Key 绝不能经 HTTP 桥投给另一端）")
shell2, manager2, _ = make(TMP, "b")
domain2 = SettingsDomain(shell2)
for key in ["api_key", "api_key_enc", "api_key_enc_deepseek",
            "license_key", "dev_mode_key"]:
    n0 = len(shell2.settings_changed())
    domain2.set(key, "sk-SECRET-DO-NOT-LEAK", False)
    n1 = len(shell2.settings_changed())
    check(f"{key} 变更**不**广播", n1 == n0, f"{n0} -> {n1}")
    check(f"{key} 仍然真的写进内存了（只是不广播）",
          manager2.settings.get(key) == "sk-SECRET-DO-NOT-LEAK")
# 非敏感项对照：证明"不广播"不是因为整条链路坏了
domain2.set("model_name", "deepseek-v4.1-flash", False)
check("对照：非敏感项照常广播", len(shell2.settings_changed()) == 1,
      str(shell2.settings_changed()))

print("[5] 收藏写操作照常广播 favorites-changed（回归，别改坏）")
shell3, manager3, cfg3 = make(TMP, "c")
fdomain = FavoritesDomain(shell3)
n0 = len(shell3.fav_changed())
added = fdomain.add("TG-000001", "Default")
n1 = len(shell3.fav_changed())
check("favorites.add 返回 ok", bool(added.get("ok")), str(added)[:150])
check("favorites.add 广播了 favorites-changed", n1 > n0, f"{n0} -> {n1}")

print("[6] 前端 listener 幂等（静态契约：收到事件只赋值、不会再调 settings.set）")
io_ = open(os.path.join(ROOT, ".ToolsGCP", "webui", "js", "app.js"), encoding="utf-8")
src = io_.read()
io_.close()
seg = src[src.find("onEvent('settings-changed'"):]
seg = seg[:seg.find("\n      });") + 8]
check("settings-changed 监听里没有再调 settings.set（无回声死循环）",
      "settings.set" not in seg, seg.replace("\n", " ")[:200])

print("[7] 日志打码：按服务商分槽的 api_key_enc_<pid> 不能把明文写进日志")
# 这条是本轮实测发现的**真漏洞**：logger 的 REDACT_KEYS 是精确匹配，
# update_setting 记的 `key=api_key_enc_deepseek new=<明文>` 原样落进了 system_log.log。
from pymodels.utils.logger import _format_fields, is_secret_key   # noqa: E402

SECRET = "sk-SECRET-DO-NOT-LEAK"
line = _format_fields({"key": "api_key_enc_deepseek", "old": "", "new": SECRET})
check("api_key_enc_deepseek 的 new 被打码", SECRET not in line and "***" in line, line)
line2 = _format_fields({"key": "license_key", "new": SECRET})
check("license_key 同样打码", SECRET not in line2, line2)
line3 = _format_fields({"key": "theme", "old": "跟随系统", "new": "浅色主题"})
check("普通设置**不**被打码（别把有用信息也抹了）",
      "浅色主题" in line3 and "***" not in line3, line3)
check("max_token / min_token 不该被当成敏感项（前缀判定的反例）",
      not is_secret_key("max_token") and not is_secret_key("min_token")
      and not is_secret_key("limit_token_output"))
check("api_key_enc_kimi / api_key 都算敏感项",
      is_secret_key("api_key_enc_kimi") and is_secret_key("api_key"))

print("[8] settings.get 整份快照：分槽 Key 也不能下发前端")
shell4, manager4, _ = make(TMP, "d")
manager4.settings["api_key_enc_deepseek"] = "dpapi:CIPHERTEXT"
domain4 = SettingsDomain(shell4)
snap = domain4.get()
check("快照里 api_key_enc_deepseek 被清空",
      snap.get("ok") and snap["settings"].get("api_key_enc_deepseek") == "",
      str(snap.get("settings", {}).get("api_key_enc_deepseek")))
check("快照里普通项照常下发（theme 还在）",
      "theme" in snap.get("settings", {}))

print()
if FAILS:
    print(f"FAILED {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("ALL OK")
