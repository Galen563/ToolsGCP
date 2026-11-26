# -*- coding: utf-8 -*-
import json, sys, os
sys.path[:0] = [os.path.abspath(".ToolsGCP"), os.path.abspath(".ToolsGCP/modules")]
data = json.load(open(".ToolsGCP/ToolsGCP-Resources.json", encoding="utf-8"))
items = data["resources"] if isinstance(data, dict) else data
lines = []
lines.append("schema_version=%s count=%d" % (data.get("schema_version") if isinstance(data,dict) else "?", len(items)))
from pymodels.core import language_manager as lm
mgr = lm.LanguageManager()
rev = lm._term_reverse(mgr)
lines.append("reverse table size=%d" % len(rev))
for it in items:
    code = it.get("code") or it.get("id")
    for f in ("category","tags"):
        v = it.get(f)
        if v is None: continue
        kind = type(v).__name__
        hits = []
        if isinstance(v, dict):
            for lang, lst in v.items():
                for t in (lst if isinstance(lst,list) else [lst]):
                    c = lm.canonical_term(t, mgr)
                    if c != t: hits.append("%s:%r->%r" % (lang, t, c))
        elif isinstance(v, list):
            for t in v:
                c = lm.canonical_term(t, mgr)
                if c != t: hits.append("flat:%r->%r" % (t, c))
        lines.append("%s %s (%s) %s%s" % (code, f, kind, json.dumps(v, ensure_ascii=False), ("   <<< HITS: " + " | ".join(hits)) if hits else ""))
open("项目资料-文档与开发测试/_devtest/_t24_dump_cat.txt","w",encoding="utf-8").write("\n".join(lines))
print("written", len(lines))
