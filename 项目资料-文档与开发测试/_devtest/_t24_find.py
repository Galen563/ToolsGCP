
# -*- coding: utf-8 -*-
import io, os
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEV = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(ROOT, ".ToolsGCP", "desktop", "api", "maker.py")
lines = io.open(p, encoding="utf-8", newline="").read().split("\n")
out = []
for i, l in enumerate(lines):
    if "schema" in l and l.lstrip().startswith("#"):
        out.append("%d: %r" % (i + 1, l))
    elif set(l.strip()) <= set("-") and l.strip():
        out.append("%d: DASHRULE %r" % (i + 1, l[:20]))
head = [l for l in lines if l.startswith("# --")]
out.append("--- lines startswith '# --' : %d" % len(head))
out += [repr(h[:60]) for h in head[:12]]
io.open(os.path.join(DEV, "_t24_headers.txt"), "w", encoding="utf-8").write("\n".join(out) + "\n")
print("wrote", len(out), "lines")
