
# -*- coding: utf-8 -*-
import io, json, os
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
p = os.path.join(ROOT, ".ToolsGCP", "ToolsGCP-Resources.json")
d = json.load(io.open(p, encoding="utf-8"))
out = ["top type=%s" % type(d).__name__]
if isinstance(d, dict):
    out.append("keys=%s" % list(d.keys()))
    for k, v in d.items():
        out.append("  %s -> %s %s" % (k, type(v).__name__, len(v) if isinstance(v, (list, dict)) else repr(v)[:60]))
    for k, v in d.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            out.append("  list key %r first item keys=%s" % (k, list(v[0].keys())))
            out.append("  codes sample=%s" % [e.get("code") for e in v[:5]])
            break
io.open(os.path.join(ROOT, "项目资料-文档与开发测试", "_devtest", "_t24_shape.txt"), "w", encoding="utf-8").write("\n".join(out) + "\n")
print("ok")
