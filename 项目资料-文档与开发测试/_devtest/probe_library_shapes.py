# -*- coding: utf-8 -*-
"""最后一个 gap：字典形态的 category/tags 经过 loader/搜索页链路会不会露出怪东西。
task-11 收紧后的 detail 契约：category / tags 恒为当前语言的字符串数组，
磁盘原形态（可能是三语字典）只挂在同名的 *_i18n 键上给制作器灌池用，
其余接口（all/query/search/stats）必须仍是「当前语言的规范值数组」。"""
import json, os, sys, tempfile
sys.path[:0] = [os.path.join(os.getcwd(), ".ToolsGCP"),
                os.path.join(os.getcwd(), ".ToolsGCP", "modules")]
from pymodels.core import resource_loader as rl, resource_query as rq, resource_schema as rs  # noqa: E402

tmp = os.path.join(os.getcwd(), "项目资料-文档与开发测试", "_devtest", ".tmp-e2e2")
os.makedirs(tmp, exist_ok=True)
lib = os.path.join(tmp, "ToolsGCP-Resources.json")
data = {"schema_version": "2.1.0",
        "metadata": {"name": "t", "description": "t", "icon_dir": "Icon",
                     "updated_at": "2026-01-01T00:00:00", "total_count": 2},
        "resources": [
            {"id": "a", "code": "TG-900010", "name": "字典形态",
             "category": {"简体中文": ["工具"], "English": ["工具", "网络"]},
             "tags": {"简体中文": ["官方"], "English": ["官方", "知名"]},
             "url": "https://a", "description": "d"},
            {"id": "b", "code": "TG-900011", "name": "老形态",
             "category": ["工具", "网络"], "tags": ["官方"],
             "url": "https://b", "description": "d"},
        ]}
with open(lib, "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False)

res = []
def add(name, ok, detail=None):
    res.append((name, bool(ok)))
    print(("  OK    " if ok else "  FAIL  ") + name + ("" if detail is None else "   <- " + str(detail)))

# ⚠️ 构造器**不加载**数据（只设字段），必须显式 load_from_data ——
#    上一版直接 get_all() 拿到空列表，几条断言在 [] 上"全真"通过（假绿）。
loader = rl.ResourceLoader(lib, "简体中文")
assert loader.load_from_data(data), "load_from_data 失败"
items = loader.get_all()
add("资源条数 == 2（防止空列表让下面的断言假绿）", len(items) == 2, len(items))
add("loader 返回的 category 是数组（不是字典）",
    all(isinstance(x.get("category"), list) for x in items),
    [type(x.get("category")).__name__ for x in items])
add("loader 返回的 tags 是数组",
    all(isinstance(x.get("tags"), list) for x in items),
    [type(x.get("tags")).__name__ for x in items])
add("字典条目按当前语言取值正确",
    items[0].get("category") == ["工具"] and items[0].get("tags") == ["官方"],
    {"cat": items[0].get("category"), "tags": items[0].get("tags")})
add("老形态条目不受影响",
    items[1].get("category") == ["工具", "网络"], items[1].get("category"))

print("== 搜索/筛选/分组 ==")
add("by_tag('工具') 能查到两条（索引收默认语言规范值）",
    len(loader.by_tag("工具")) == 2, [x.get("code") for x in loader.by_tag("工具")])
add("by_category('网络') 命中两条（索引建在**各语言并集**上，task-6 用户定夺）",
    [x.get("code") for x in loader.by_category("网络")] == ["TG-900010", "TG-900011"],
    [x.get("code") for x in loader.by_category("网络")])
add("by_tag('知名') 命中字典那条（标签并集也可搜到）",
    [x.get("code") for x in loader.by_tag("知名")] == ["TG-900010"],
    [x.get("code") for x in loader.by_tag("知名")])
cats = []
for x in items:
    for c in rs.categories_of(x) or ["其他"]:
        cats.append(c)
add("分组键里没有 dict/对象（不会出现 [object Object] 分组）",
    all(isinstance(c, str) for c in cats), cats[:6])

print("== 英文界面语言下的 loader ==")
loader_en = rl.ResourceLoader(lib, "English")
assert loader_en.load_from_data(data), "英文 loader 加载失败"
items_en = loader_en.get_all()
add("English loader 也拿到 2 条", len(items_en) == 2, len(items_en))
add("English 界面下 loader 仍返回数组",
    all(isinstance(x.get("category"), list) for x in items_en),
    [x.get("category") for x in items_en])
print("   English 界面下字典条目的 category =", items_en[0].get("category"))

print("== 制作器那条路：原始副本 ==")
raw = loader.get_raw_i18n_by_id("a") or loader.get_raw_i18n_by_code("TG-900010")
add("原始副本里 category 仍是字典（制作器灌池靠它）",
    isinstance(raw.get("category"), dict), raw.get("category"))
add("原始副本里 tags 仍是字典",
    isinstance(raw.get("tags"), dict), raw.get("tags"))

print("== 前端 mapItem 的输入形态确认 ==")
# 前端 mapItem 走的是 resources.all 的返回（数组），detail 的字典只进制作器 poolsFromRaw
sample = items[0]
add("all 接口形态下 category 可直接 join（前端 term() 逐个映射安全）",
    isinstance(sample.get("category"), list)
    and all(isinstance(v, str) for v in sample.get("category", [])),
    sample.get("category"))

shutil_ok = True
import shutil
shutil.rmtree(tmp, ignore_errors=True)
fails = [n for n, ok in res if not ok]
print("\n==== gap 检查 %d/%d 通过 ====" % (len(res) - len(fails), len(res)))
sys.exit(1 if fails else 0)