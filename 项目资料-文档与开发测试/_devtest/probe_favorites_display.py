# -*- coding: utf-8 -*-
"""收藏夹显示名探针（第五轮需求②）。

需求原话：「修复收藏夹页面默认的收藏夹实际文件夹是英文名的，
在界面上显示的语言应该是设置中选择的语言而不是一直是简体中文。」

口径（已与用户确认）：**内部真名恒为 "Default"**（存储、迁移、筛选都按它走），
只有显示层跟着界面语言变。

覆盖三层：
  ① favorites_manager 三语表 + 未知语言退回英文 + 历史中文名归一（真跑）；
  ② 后端出口 resources.py favorites.list 必须把 label 交出去；
  ③ 前端显示走 label、真名只做身份、**切语言必须重拉收藏夹**。
"""
import json
import os
import shutil
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (os.path.join(ROOT, ".ToolsGCP"), os.path.join(ROOT, ".ToolsGCP", "modules")):
    if p not in sys.path:
        sys.path.insert(0, p)

results = []

TMP_ROOT = os.path.join(ROOT, ".tmp-favprobe")


def _local_tmp(tag):
    """沙箱里 tempfile.mkdtemp() 落到的系统 TEMP 不可写（PermissionError），
    改用仓库内的 .tmp-favprobe/（.gitignore 的 /.tmp-* 已覆盖），跑完整体删除。"""
    d = os.path.join(TMP_ROOT, tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    return d


def check(name, cond, detail=""):
    results.append((bool(cond), name, detail))


# ---------- ① 后端纯函数：三语显示名 ----------
from pymodels.core import favorites_manager as fm  # noqa: E402
from pymodels.core.favorites_manager import FavoritesManager, display_folder_name  # noqa: E402

check("内部真名仍是 Default（不是改成中文名存盘）", fm.DEFAULT_FOLDER == "Default", str(fm.DEFAULT_FOLDER))
check("简体中文显示默认收藏夹", display_folder_name("Default", "简体中文") == "默认收藏夹",
      display_folder_name("Default", "简体中文"))
check("繁體中文显示預設收藏夾", display_folder_name("Default", "繁體中文") == "預設收藏夾",
      display_folder_name("Default", "繁體中文"))
check("English 显示 Default", display_folder_name("Default", "English") == "Default",
      display_folder_name("Default", "English"))
check("未知语言退回英文（不是简体中文）", display_folder_name("Default", "Deutsch") == "Default",
      display_folder_name("Default", "Deutsch"))
check("空语言也退回英文", display_folder_name("Default", "") == "Default", display_folder_name("Default", ""))
check("用户自建夹原样显示（不许被翻译）", display_folder_name("我的开发工具", "English") == "我的开发工具")
mgr_tmp = _local_tmp("favlabel")
check("default_folder_label 随语言", FavoritesManager(mgr_tmp).default_folder_label("繁體中文") == "預設收藏夾")

# ---------- ② 历史中文名归一：老数据不能变成两个默认夹 ----------
# ⚠️ favorites.json 的真实形态是 folders: [{"name":..,"items":[..]}] 的**数组**（见
#    用户目录里的实际文件），写成字典会被 load() 整段忽略 ⇒ 测不到归一逻辑。
#    另外 FavoritesManager 在构造时就 load() 了，必须先落盘再构造，否则读的是空文件。
def load_from(name_lists):
    d = _local_tmp("favlegacy")
    with open(os.path.join(d, fm.FAVORITES_FILE), "w", encoding="utf-8") as f:
        json.dump({"schema_version": fm.SCHEMA_VERSION,
                   "folders": [{"name": n, "items": list(v)} for n, v in name_lists]}, f, ensure_ascii=False)
    return FavoritesManager(d)

try:
    mgr = load_from([("默认收藏夹", ["TG-000001"]), ("Work", ["TG-000002"])])
    names = mgr.folders()
    check("旧版中文默认夹被归一为 Default", names.count("Default") == 1 and "默认收藏夹" not in names, str(names))
    check("归一后条目没丢", mgr.folder_items("Default") == ["TG-000001"], str(mgr.folder_items("Default")))
    check("自建夹不受影响", "Work" in names and mgr.folder_items("Work") == ["TG-000002"], str(names))
    check("默认夹永远排在最前", names and names[0] == "Default", str(names))
    # 边界：用户自建夹恰好叫 "Default"，老文件里同时还有中文名的默认夹。归一发生在
    # 判重**之后**的话，folders() 里会出现两条 "Default"，_folder() 只认第一条 ⇒
    # 第二条里的收藏在界面上永远看不见（看不见的收藏就是丢数据）。
    mgr2 = load_from([("Default", ["TG-000001"]), ("默认收藏夹", ["TG-000002", "TG-000001"]), ("Work", ["TG-000003"])])
    check("两条默认夹归一后不重复", mgr2.folders().count("Default") == 1, str(mgr2.folders()))
    check("重复归一的条目被合并而不是丢弃",
          sorted(mgr2.folder_items("Default")) == ["TG-000001", "TG-000002"], str(mgr2.folder_items("Default")))
    check("合并后每条收藏都能定位到夹",
          sorted(mgr2.all_codes()) == ["TG-000001", "TG-000002", "TG-000003"] and mgr2.folder_of("TG-000002") == "Default",
          str(mgr2.all_codes()))
except Exception as exc:  # noqa: BLE001
    check("历史数据归一（异常）", False, repr(exc))

# ---------- ③ 后端出口 ----------
src_api = open(os.path.join(ROOT, ".ToolsGCP", "desktop", "api", "resources.py"), encoding="utf-8").read()
check("favorites.list 接受 language 形参", 'def list(self, language: str = "")' in src_api)
check("列表出口逐夹算显示名 label", '"label": display_folder_name(name, lang)' in src_api)
check("label 语言 = 传入参数或 shell.current_language()", "lang = language or self._shell.current_language()" in src_api)
check("顶层还送出 default_label", "default_label=manager.default_folder_label(lang)" in src_api)
check("移动完成事件用显示名", "folder=display_folder_name(to_folder, self._shell.current_language())" in src_api)

# ---------- ④ 前端 ----------
app = open(os.path.join(ROOT, ".ToolsGCP", "webui", "js", "app.js"), encoding="utf-8").read()
html = open(os.path.join(ROOT, ".ToolsGCP", "webui", "index.html"), encoding="utf-8").read()
seg = app[app.index("async function loadFavorites"):][:600]
check("loadFavorites 显式带界面语言（切语言那一刻不能靠后端兜底）",
      "bridge.tryCall('favorites.list', uiLanguage())" in seg)
check("folders 落库时保留 label 兜底", "label: f.label || f.name" in seg)
check("收藏夹列表渲染用 f.label（显示名）", "{{ f.label }}" in html)
check("选中态用真名 f.name（显示名不能当身份）", "favFolder === f.name" in html)
check("默认夹判定仍按真名", "const isDefaultFolder = computed(() => favFolder.value === 'Default');" in app)
# 导入流程只会把 codes 放进**用户选定的已有夹**（move_many / add 两条出口），
# 不会新建夹 ⇒ 老文件里的中文夹名不可能变成第二个默认夹；导出写的是内部真名。
check("导出用的是内部真名（不是随语言变的显示名）",
      "name: f.name" in app and "value: f.name" in app)
_imp = app[app.index("async function applyImportedFavorites"):app.index("/* 选「文件 → 解析")]
check("导入不会新建收藏夹（只移动进已有夹）",
      "favorites.move_many" in _imp and "favorites.add" in _imp and "create_folder" not in _imp)

bad = [r for r in results if not r[0]]
for ok, name, detail in results:
    print(("PASS  " if ok else "FAIL  ") + name + (("  | " + detail) if detail else ""))
print("---- 汇总 %d/%d ----" % (len(results) - len(bad), len(results)))
sys.exit(1 if bad else 0)
