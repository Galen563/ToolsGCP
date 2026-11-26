
# -*- coding: utf-8 -*-
"""把 task-24 的写侧兜底拼进 desktop/api/maker.py（锚点唯一性断言，失败就不落盘）"""
import io, os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEV = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(ROOT, ".ToolsGCP", "desktop", "api", "maker.py")

text = io.open(TARGET, encoding="utf-8", newline="").read()
block1 = io.open(os.path.join(DEV, "_t24_block_funcs.txt"), encoding="utf-8").read().rstrip("\n") + "\n\n\n"
block2 = io.open(os.path.join(DEV, "_t24_block_call.txt"), encoding="utf-8").read().rstrip("\n") + "\n"

assert "canonicalize_lang_list" not in text, "maker.py 已经打过补丁了，中止"
log = []

# --- 1) 模块级函数块：插到 class MakerDomain 之前 ---
KEY1 = "class MakerDomain:"
assert text.count(KEY1) == 1, "锚点1 出现 %d 次" % text.count(KEY1)
i = text.index(KEY1)
ls = text.rfind("\n", 0, i) + 1
text = text[:ls] + block1 + text[ls:]
log.append("[ok] 模块级反查函数 %d 行插在 class MakerDomain 之前（新行号 %d）"
           % (block1.count("\n"), text[:ls].count("\n") + 1))

# --- 2) 修正 _merge_i18n 里"后端不翻译"的旧注释 ---
OLD3 = ("        #   · 每个语言各自 split_multi 拆成 list、各自去重（值一律规范中文口径，\n"
        "        #     canonicalTerm 是前端职责，后端不翻译）；\n")
NEW3 = ("        #   · 每个语言各自 split_multi 拆成 list、各自去重（值的口径 = 规范简体中文；\n"
        "        #     显示文本 → 规范值的反查见下面的 task-24 兜底段 ——\n"
        "        #     原先这里写的是「canonicalTerm 是前端职责，后端不翻译」，而实测前端会送\n"
        "        #     当前界面语言那份显示值（English 界面 → \"Clipboard\"），原样落盘就是脏值通道）；\n")
assert text.count(OLD3) == 1, "锚点2 出现 %d 次" % text.count(OLD3)
text = text.replace(OLD3, NEW3)
log.append("[ok] _merge_i18n 旧注释（后端不翻译）改为指向 task-24 兜底")

# --- 3) 值兜底调用：接在 out[field] = merged 那行之后（links 段之前）---
KEY2 = "                out[field] = merged"
assert text.count(KEY2) == 1, "锚点3 出现 %d 次" % text.count(KEY2)
j = text.index(KEY2)
le = text.index("\n", j) + 1
text = text[:le] + block2 + text[le:]
log.append("[ok] _merge_i18n 值兜底循环接在 merged 赋值之后（新行号 %d）" % (text[:le].count("\n") + 1))

io.open(TARGET, "w", encoding="utf-8", newline="").write(text)
io.open(os.path.join(DEV, "_t24_patch.log"), "w", encoding="utf-8").write("\n".join(log) + "\n")
print("patched")
