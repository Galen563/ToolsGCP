# -*- coding: utf-8 -*-
"""端到端（真实落盘 + 真实读回）：制作器保存三语不同的类别/标签，会不会丢。

用临时资源库文件（monkeypatch library_path），**绝不碰**真实
.ToolsGCP/ToolsGCP-Resources.json。链路是产品真链路：
  MakerDomain.append_entry（写盘，含 _normalize/_merge_i18n）
    → 磁盘 JSON
    → ResourceDomain.detail（读，含 _merge_raw_i18n）
    → 原始三语字典回到前端形态
"""
import json, os, shutil, sys, tempfile
sys.path[:0] = [os.path.join(os.getcwd(), ".ToolsGCP"),
                os.path.join(os.getcwd(), ".ToolsGCP", "modules")]

# ⚠️ 沙箱不允许写系统临时目录 / 用户数据根 —— 整个测试的落盘都关进工作区里一个
#    自建的 .tmp-e2e 目录（跑完删掉）：资源库、滚动备份都指到这里，
#    真实资源库与用户数据目录一个字节都不动。
tmp = os.path.join(os.getcwd(), "项目资料-文档与开发测试", "_devtest", ".tmp-e2e")
shutil.rmtree(tmp, ignore_errors=True)
os.makedirs(tmp, exist_ok=True)
lib = os.path.join(tmp, "ToolsGCP-Resources.json")
with open(lib, "w", encoding="utf-8") as fh:
    json.dump({"schema_version": "2.1.0",
               "metadata": {"name": "t", "description": "t", "icon_dir": "Icon",
                            "updated_at": "2026-01-01T00:00:00", "total_count": 0},
               "resources": []}, fh, ensure_ascii=False)

from desktop.api.maker import MakerDomain            # noqa: E402
from desktop.api import resources as res_mod         # noqa: E402
from pymodels.core import resource_schema as rs      # noqa: E402

res = []
def add(name, ok, detail=None):
    res.append((name, bool(ok)))
    print(("  OK    " if ok else "  FAIL  ") + name + ("" if detail is None else "   <- " + str(detail)))

# 让两条链路都指向临时库：资源库路径 + 滚动备份路径（_write 里会 copy2 到备份，
# 不重定向就会去写用户数据根 → 沙箱 PermissionError，而且会污染真实备份）
mk = MakerDomain.__new__(MakerDomain)
mk._shell = None
MakerDomain.library_path = staticmethod(lambda *a, **k: lib)
import desktop.api.maker as maker_mod                # noqa: E402
maker_mod.rolling_backup_file = lambda: os.path.join(tmp, "ToolsGCP-Resources.prev.json")

CAT = {"简体中文": ["工具"], "繁體中文": ["工具"], "English": ["工具", "网络"]}
TAGS = {"简体中文": ["官方"], "English": ["官方", "知名"]}
entry = {"id": "e2e", "code": "TG-900001", "name": "E2E",
         "category": CAT, "tags": TAGS, "url": "https://example.com",
         "description": "只有简中一句话"}

print("== 1) 写盘 ==")
r = mk.append_entry(entry, {"confirm": True})
add("append_entry 成功", r.get("ok") is True, r.get("error") or r.get("action"))

print("== 2) 磁盘上的真实形态 ==")
disk = json.load(open(lib, encoding="utf-8"))["resources"][0]
add("磁盘 category 是三语字典", disk.get("category") == CAT, disk.get("category"))
add("磁盘 tags 是三语字典", disk.get("tags") == TAGS, disk.get("tags"))

print("== 3) 读侧按语言取值 ==")
add("categories_of(English) == [工具, 网络]",
    rs.categories_of(disk, "English") == ["工具", "网络"], rs.categories_of(disk, "English"))
add("categories_of(简体) == [工具]",
    rs.categories_of(disk, "简体中文") == ["工具"], rs.categories_of(disk, "简体中文"))

print("== 4) resources.detail 是否把原始字典回传（前端灌池靠它） ==")
raw = rs.raw_i18n_of(disk)
add("raw_i18n_of 含 category 原始字典",
    raw.get("category") == CAT, raw.get("category"))
add("raw_i18n_of 含 tags 原始字典",
    raw.get("tags") == TAGS, raw.get("tags"))
# 需求3 收紧后的契约：正身字段恒为 list[str]（前端卡片直接 v-for），
# 磁盘原始字典改由 category_i18n / tags_i18n 携带（制作器灌池靠它们）
merged = res_mod._merge_raw_i18n(rs.normalize(dict(disk), "English"), raw, "English")
add("_merge_raw_i18n 后 category / tags 是纯字符串数组（绝不含字典）",
    merged.get("category") == ["工具", "网络"] and merged.get("tags") == ["官方", "知名"],
    {"cat": merged.get("category"), "tags": merged.get("tags")})
add("_merge_raw_i18n 后 category_i18n / tags_i18n 原样带回磁盘字典",
    merged.get("category_i18n") == CAT and merged.get("tags_i18n") == TAGS,
    {"cat_i18n": merged.get("category_i18n"), "tags_i18n": merged.get("tags_i18n")})

print("== 5) 前端 poolsFromRaw 等价逻辑（数组/字典两种形态都要灌对） ==")
def pools_from_raw(value, langs=("简体中文", "繁體中文", "English")):
    out = {}
    if isinstance(value, dict):
        for lang in langs:
            one = value.get(lang, value.get("简体中文"))
            out[lang] = one if isinstance(one, list) else [one]
        return out
    base = value if isinstance(value, list) else [value]
    return {lang: list(base) for lang in langs}
p1 = pools_from_raw(merged.get("category_i18n"))
add("字典形态 → 三个池各取自己那份",
    p1["English"] == ["工具", "网络"] and p1["简体中文"] == ["工具"], p1)
p2 = pools_from_raw(["工具", "网络"])
add("数组形态 → 三个池同值（老数据零迁移）",
    p2["English"] == p2["繁體中文"] == ["工具", "网络"], p2)

print("== 6) 再保存一次（往返稳定，不会越存越丢） ==")
# 模拟制作器把「读到的原始形态」原样送回：必须幂等（越存越丢就是这里出错）
r2 = mk.append_entry({"id": "e2e", "code": "TG-900001", "name": "E2E",
                      "category": merged.get("category_i18n"), "tags": merged.get("tags_i18n"),
                      "url": "https://example.com", "description": "只有简中一句话"},
                     {"confirm": True})
disk2 = json.load(open(lib, encoding="utf-8"))["resources"][0]
add("二次写盘形态不变",
    disk2.get("category") == CAT and disk2.get("tags") == TAGS,
    {"category": disk2.get("category"), "tags": disk2.get("tags")})

print("== 7) 真实资源库未被污染 ==")
real = json.load(open(".ToolsGCP/ToolsGCP-Resources.json", encoding="utf-8"))["resources"]
add("真实资源库没有 e2e 条目", not any(x.get("id") == "e2e" for x in real), len(real))
# 真实库现在 54 条：detail 出口必须没有任何"字典形态的 category/tags"漏到前端
disk_real = json.load(open(".ToolsGCP/ToolsGCP-Resources.json", encoding="utf-8"))["resources"]
leak = []
for it in disk_real:
    m = res_mod._merge_raw_i18n(rs.normalize(dict(it), "简体中文"), rs.raw_i18n_of(it), "简体中文")
    for k in ("category", "tags"):
        v = m.get(k)
        if isinstance(v, (dict, str)) or (isinstance(v, list) and any(not isinstance(x, str) for x in v)):
            leak.append((it.get("code"), k, v))
add("全库 detail 出口 category/tags 无字典、无 JSON 残迹", not leak, leak[:3])

shutil.rmtree(tmp, ignore_errors=True)
fails = [n for n, ok in res if not ok]
print("\n==== 端到端 %d/%d 通过 ====" % (len(res) - len(fails), len(res)))
sys.exit(1 if fails else 0)