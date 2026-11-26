
# -*- coding: utf-8 -*-
import io, os
DEV = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(DEV, "migrate_task24_category_tags.py")
src = io.open(P, encoding="utf-8").read()
head = src.split("def write_report(")[0]
tail = io.open(os.path.join(DEV, "_t24_tail.py"), encoding="utf-8").read()
assert "逐池反查（内容仍不一致⇒不塌缩）" in head, "plan_for 里 lead 的改动丢了"
assert "if value == MANUAL_OVERRIDE[(code, field)]:" in head, "plan_for 里 no-op 保护丢了"
if "\nimport time\n" not in head:
    head = head.replace("import shutil\nimport sys\n", "import shutil\nimport sys\nimport time\n")
assert "import time" in head
io.open(P, "w", encoding="utf-8", newline="\n").write(head + tail)
print("head=%d tail=%d" % (len(head), len(tail)))
