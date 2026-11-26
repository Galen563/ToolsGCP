
# -*- coding: utf-8 -*-
"""maker.py 补丁后的冒烟测：走真实 _normalize 链路"""
import io, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEV = os.path.dirname(os.path.abspath(__file__))
sys.argv[0] = os.path.join(ROOT, "ToolsGCP.pyw")          # 关键：constants 按 argv[0] 定位资源根
sys.path[:0] = [os.path.join(ROOT, ".ToolsGCP"), os.path.join(ROOT, ".ToolsGCP", "modules")]

from desktop.api.maker import MakerDomain, canonicalize_term, canonicalize_lang_list

N = MakerDomain._normalize


def case(title, raw):
    got = N(raw)
    again = N(got) if isinstance(got, dict) else got
    return title, {"category": got.get("category"), "tags": got.get("tags")}, again


rows = []
rows.append(case("英文界面送来 Clipboard（三池同内容）",
                 {"name": "T1", "tags": {"简体中文": ["粘贴板"], "繁體中文": ["粘貼板"], "English": ["Clipboard"]}}))
rows.append(case("只有 English 池",
                 {"name": "T2", "category": {"English": ["Game platform"]}}))
rows.append(case("扁平 list 形态",
                 {"name": "T3", "category": ["遊戲平台", "Game platform"]}))
rows.append(case("逗号串形态",
                 {"name": "T4", "tags": "粘貼板,Clipboard"}))
rows.append(case("自定义值（认不出→原样）",
                 {"name": "T5", "tags": {"简体中文": ["MC启动器", "知名"], "繁體中文": ["MC启动器"], "English": ["MC启动器"]}}))
rows.append(case("三池内容不一致（不自动改）",
                 {"name": "T6", "tags": {"简体中文": ["AI图像", "去背景", "抠图"], "繁體中文": ["AI圖像", "去背", "摳圖"], "English": ["Background Removal", "AI Cutout", "Photo Tool"]}}))
rows.append(case("幂等（规范值再进一次）",
                 {"name": "T7", "category": ["工具"], "tags": ["粘贴板", "系统"]}))
rows.append(case("links 不受影响",
                 {"name": "T8", "links": [{"label": {"简体中文": "官网"}, "url": "https://x"}], "category": "遊戲平台"}))

out = []
for title, got, again in rows:
    same = json.dumps(got, ensure_ascii=False, sort_keys=True) == json.dumps({"category": again.get("category"), "tags": again.get("tags")}, ensure_ascii=False, sort_keys=True)
    out.append("■ %s\n  -> category=%s\n  -> tags   =%s\n  幂等=%s" % (title, json.dumps(got["category"], ensure_ascii=False), json.dumps(got["tags"], ensure_ascii=False), same))
out.append("canonicalize_term('FileConverter')=%r  ('档案转换')=%r  ('自定义词')=%r" % (canonicalize_term("FileConverter"), canonicalize_term("档案转换"), canonicalize_term("自定义词")))
io.open(os.path.join(DEV, "_t24_smoke.txt"), "w", encoding="utf-8").write("\n".join(out) + "\n")
print("done")
