# -*- coding: utf-8 -*-
"""临时勘察：constants.SCRIPT_DIR 取的是 sys.argv[0] 所在目录，
探针放在 _devtest 下会把 .ToolsGCP 算到 _devtest 里 —— 先把 argv[0] 顶成仓库根的入口。"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.argv[0] = os.path.join(ROOT, "ToolsGCP.pyw")
sys.path[:0] = [os.path.join(ROOT, ".ToolsGCP"), os.path.join(ROOT, ".ToolsGCP", "modules")]
from pymodels import constants
from pymodels.core import language_manager as lm
lines = ["LANGUAGES_DIR=%s exists=%s" % (constants.LANGUAGES_DIR, os.path.isdir(constants.LANGUAGES_DIR))]
mgr = lm.LanguageManager()
rev = lm._term_reverse(mgr)
lines.append("rev size=%d" % len(rev))
data = json.load(open(os.path.join(ROOT, ".ToolsGCP/ToolsGCP-Resources.json"), encoding="utf-8"))
items = data["resources"] if isinstance(data, dict) else data
hits = 0
for it in items:
    code = it.get("code") or it.get("id")
    for f in ("category", "tags"):
        v = it.get(f)
        if isinstance(v, dict):
            for lang, lst in v.items():
                for t in (lst if isinstance(lst, list) else [lst]):
                    c = lm.canonical_term(t, mgr)
                    if c != t:
                        hits += 1
                        lines.append("HIT %s.%s[%s] %r -> %r" % (code, f, lang, t, c))
        elif isinstance(v, list):
            for t in v:
                c = lm.canonical_term(t, mgr)
                if c != t:
                    hits += 1
                    lines.append("HIT %s.%s(flat) %r -> %r" % (code, f, t, c))
lines.append("TOTAL HITS = %d" % hits)
open(os.path.join(ROOT, "项目资料-文档与开发测试/_devtest/_t24_hits.txt"), "w", encoding="utf-8").write("\n".join(lines))
print("ok")
