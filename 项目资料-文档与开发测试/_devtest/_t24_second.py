
# -*- coding: utf-8 -*-
import io, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEV = os.path.dirname(os.path.abspath(__file__))
sys.argv[0] = os.path.join(ROOT, "ToolsGCP.pyw")
sys.path[:0] = [os.path.join(ROOT, ".ToolsGCP"), os.path.join(ROOT, ".ToolsGCP", "modules")]
sys.stdout.reconfigure(errors="replace")
sys.path.insert(0, DEV)
import migrate_task24_category_tags as M
data = json.load(io.open(M.LIB, encoding="utf-8"))
ch, un = M.build(data)
out = []
for c in ch:
    out.append("%s.%s kind=%s before=%s after=%s" % (c["code"], c["field"], c["kind"],
               json.dumps(c["before"], ensure_ascii=False), json.dumps(c["after"], ensure_ascii=False)))
io.open(os.path.join(DEV, "_t24_second.txt"), "w", encoding="utf-8").write("\n".join(out) + "\n")
print("second pass changes:", len(ch), "undecided:", len(un))
