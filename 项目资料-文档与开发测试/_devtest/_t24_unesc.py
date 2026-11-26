
# -*- coding: utf-8 -*-
import io, os
DEV = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(DEV, "migrate_task24_category_tags.py")
src = io.open(P, encoding="utf-8").read()
n = src.count("%%")
src2 = src.replace("%%", "%")
io.open(P, "w", encoding="utf-8", newline="\n").write(src2)
print("replaced %d occurrences of %%%% -> %%" % n)
