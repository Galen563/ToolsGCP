
# -*- coding: utf-8 -*-
import io
p = r"C:\Users\Administrator\Desktop\ToolsGCP开发\v1.1.4 - 12\.ToolsGCP\desktop\api\maker.py"
lines = io.open(p, encoding="utf-8").read().split("\n")
out = []
for i in range(84, 92):
    out.append("%d: %r" % (i+1, lines[i]))
out.append("---")
for i in range(229, 262):
    out.append("%d: %r" % (i+1, lines[i]))
io.open(r"C:\Users\Administrator\Desktop\ToolsGCP开发\v1.1.4 - 12\项目资料-文档与开发测试\_devtest\_t24_anchors.txt", "w", encoding="utf-8").write("\n".join(out))
print("ok")
