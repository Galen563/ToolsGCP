
# -*- coding: utf-8 -*-
import io, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEV = os.path.dirname(os.path.abspath(__file__))
sys.argv[0] = os.path.join(ROOT, "ToolsGCP.pyw")
sys.path[:0] = [os.path.join(ROOT, ".ToolsGCP"), os.path.join(ROOT, ".ToolsGCP", "modules")]
from pymodels.core import language_manager as lm
mgr = lm.LanguageManager()
langs = mgr.translations if hasattr(mgr, "translations") else {}
keys = ["粘贴板","游戏平台","文件转换","轻量","教学辅助","社交","管理器","服务器部署","图标生成","多平台",
        "版本控制","AI原生浏览器","抠图","去背景","AI图像","工具","编程","实用","系统","学习","官方","知名","MC启动器"]
out = []
for loc in ("zh_CN","zh_TW","en_US"):
    d = langs.get(loc) or {}
    out.append("### %s  (term_* count=%d)" % (loc, sum(1 for k in d if k.startswith("term_"))))
for k in keys:
    row = []
    for loc in ("zh_CN","zh_TW","en_US"):
        d = langs.get(loc) or {}
        # 语言表按 module 分文件？先看扁平还是嵌套
        v = d.get("term_" + k)
        if v is None and isinstance(d, dict):
            for mod, sub in d.items():
                if isinstance(sub, dict) and ("term_" + k) in sub:
                    v = sub["term_" + k]; break
        row.append("%s=%r" % (loc, v))
    out.append("%-12s %s" % (k, "  ".join(row)))
out.append("top keys of translations: %s" % list(langs.keys()))
sample = langs.get("en_US")
if isinstance(sample, dict):
    out.append("en_US type=dict keys(sample)=%s" % [k for k in list(sample)[:8]])
    out.append("term_ keys in en_US=%d" % sum(1 for k in sample if str(k).startswith("term_")))
io.open(os.path.join(DEV, "_t24_terms.txt"), "w", encoding="utf-8").write("\n".join(out) + "\n")
print("ok")
