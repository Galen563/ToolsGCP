
# -*- coding: utf-8 -*-
"""task-24 探针：category / tags「显示文本 → 规范中文」写侧兜底（可反复跑，不落盘）。

覆盖 lead 的口径：
  ① 简体中文 / 繁體中文 / English 三种写法都能反查回规范值，且**与当前界面语言无关**
  ② 反查不到的一律原样保留（用户自定义值：绝不猜、绝不丢）
  ③ 幂等：同一份数据连跑两遍零 diff（函数层 + MakerDomain._normalize 全链路 × 真实 57 条）
  ④ 语言池字典形态与扁平 list[str] 形态都覆盖（含逗号串这种历史形态）
  ⑤ 只动 category / tags：links 与其它 i18n 字段的既有行为不变
  ⑥ 反查表不可用 / 元素类型不对时不抛异常（兜底逻辑本身不能把落盘搞挂）

术语对照取自 languages/{zh_CN,zh_TW,en_US}/common_language.json 的 term_* 键（_t24_terms.txt 有全表），
其中两条容易被想当然：抠图 的 English 是 "Image matting"（不是 Photo Tool）；
"Photo Tool" 自己也是某个 term_ 键名 ⇒ 反查按"键→键"自等，返回 "Photo Tool" 本身。

跑法：python "项目资料-文档与开发测试/_devtest/probe_task24_canonical.py"
结尾打印 RESULT: PASS / RESULT: FAIL（退出码 0 / 1）。
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEV = os.path.dirname(os.path.abspath(__file__))
# constants.get_script_dir() = dirname(abspath(sys.argv[0]))。不改 argv[0]，语言表目录会被
# 算成 _devtest\.ToolsGCP\modules\languages（不存在）⇒ 反查表空、canonical_term 原样返回，
# 探针会"绿得毫无意义"（第一次跑就是这么被骗过去的）。
sys.argv[0] = os.path.join(ROOT, "ToolsGCP.pyw")
sys.path[:0] = [os.path.join(ROOT, ".ToolsGCP"), os.path.join(ROOT, ".ToolsGCP", "modules")]

try:                                    # 控制台是 GBK：中文打印必须先降级，别 UnicodeEncodeError 把探针搞挂
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

from desktop.api import maker
from desktop.api.maker import MakerDomain, canonicalize_lang_list, canonicalize_term
from pymodels.core import language_manager as lm
from pymodels.core import resource_schema

N = MakerDomain._normalize
FAILS = []
LOG = []


def check(title, got, want):
    """一条断言：不等记 FAIL，并把双方 JSON 打全（ensure_ascii=False 才看得懂中文）"""
    ok = got == want
    LOG.append("%s %s\n     got =%s\n     want=%s"
               % ("[PASS]" if ok else "[FAIL]", title,
                  json.dumps(got, ensure_ascii=False), json.dumps(want, ensure_ascii=False)))
    if not ok:
        FAILS.append(title)


# ── ① 三语显示文本 → 规范值 ──────────────────────────────────────────
LOG.append("── ① 三语显示文本 → 规范值（zh_CN / zh_TW / en_US 都认）──")
TRIPLES = [
    (("粘贴板", "粘貼板", "Clipboard"), "粘贴板"),
    (("游戏平台", "遊戲平台", "Game platform"), "游戏平台"),
    (("文件转换", "文件轉換", "FileConverter"), "文件转换"),
    (("轻量", "輕量", "Lightweight"), "轻量"),
    (("教学辅助", "教學輔助", "Teaching aid"), "教学辅助"),
    (("社交", "社交", "Social"), "社交"),
    (("管理器", "管理器", "Manager"), "管理器"),
    (("服务器部署", "伺服器部署", "Server deployment"), "服务器部署"),
    (("图标生成", "圖標生成", "Icon Maker"), "图标生成"),
    (("多平台", "多平台", "Multi-Platform"), "多平台"),
    (("版本控制", "版本控制", "Version Control"), "版本控制"),
    (("AI原生浏览器", "AI原生瀏覽器", "AI-native browser"), "AI原生浏览器"),
    (("抠图", "摳圖", "Image matting"), "抠图"),
    (("去背景", "去背", "Background Removal"), "去背景"),
    (("AI图像", "AI圖像", "AI Cutout"), "AI图像"),
    (("工具", "工具", "Tools"), "工具"),
    (("编程", "程式設計", "Programming"), "编程"),
    (("实用", "實用", "Utility"), "实用"),
    (("系统", "系統", "System"), "系统"),
]
for texts, want in TRIPLES:
    for text in texts:
        check("canonical_term(%r) → %r" % (text, want), canonicalize_term(text), want)
# 已知边界：term_ 键名本身也在反查表里自等（库里没用过 图片处理，所以不受影响）
check("'Photo Tool' 作为键名自等（不猜成 图片处理）", canonicalize_term("Photo Tool"), "Photo Tool")

# ── ② 用户自定义值原样保留 ──────────────────────────────────────────
LOG.append("── ② 用户自定义值原样保留（不猜、不丢）──")
for custom in ["MC启动器", "知名", "自造标签X", "GCP-AI", "xxx-插件", "图片处理-自用"]:
    check("自定义值 %r 原样" % custom, canonicalize_term(custom), custom)
check("自定义值与术语混排也不丢", canonicalize_lang_list(["MC启动器", "知名", "遊戲平台"]),
      ["MC启动器", "知名", "游戏平台"])
check("反查后同值必须去重（粘贴板/粘貼板/Clipboard 并成一份）",
      canonicalize_lang_list(["粘贴板", "粘貼板", "Clipboard"]), ["粘贴板"])

# ── ③ 幂等 ─────────────────────────────────────────────────────────
LOG.append("── ③ 幂等：跑两遍零 diff ──")
SAMPLES = [
    ["粘贴板", "粘貼板", "Clipboard"],
    {"简体中文": ["工具"], "繁體中文": ["工具"], "English": ["Tools"]},
    {"简体中文": ["AI图像", "去背景", "抠图"], "繁體中文": ["AI圖像", "去背", "摳圖"],
     "English": ["Background Removal", "AI Cutout", "Photo Tool"]},
    {"English": ["Game platform"]},
    ["MC启动器", "知名"],
    {"简体中文": [], "繁體中文": ["实用"], "English": []},
    {"简体中文": ["编程"], "繁體中文": ["工具"], "English": ["工具"]},
    "工具,粘贴板",
    None,
    123,
]
for s in SAMPLES:
    once = canonicalize_lang_list(s)
    check("幂等（函数层）%s" % json.dumps(s, ensure_ascii=False)[:56],
          canonicalize_lang_list(once), once)
# 同一条数据连着过两遍写侧链路（_normalize）也必须零 diff
LIB = os.path.join(ROOT, ".ToolsGCP", "ToolsGCP-Resources.json")
data = json.load(io.open(LIB, encoding="utf-8"))
items = data.get("resources") or data.get("items") or []
diffs = []
for e in items:
    p1 = N(e)
    p2 = N(p1)
    for k in set(list(p1.keys()) + list(p2.keys())):
        if p1.get(k) != p2.get(k):
            diffs.append((e.get("code"), k, p1.get(k), p2.get(k)))
check("幂等（真实库 %d 条走 _normalize 两遍零 diff）" % len(items), diffs, [])
# 落盘值再过一遍反查应当不变（这就是迁移做完后的稳态）
resid = []
for e in items:
    for f in ("category", "tags"):
        v = e.get(f)
        if not isinstance(v, (list, dict)):
            continue
        pool = v if isinstance(v, list) else [x for p in v.values() for x in p]
        for x in pool:
            c = canonicalize_term(x)
            if isinstance(x, str) and c != x:
                resid.append((e.get("code"), f, x, c))
LOG.append("     库里仍残留的显示文本（=「三池不一致」未自动改的那几条）%d 处：%s"
           % (len(resid), json.dumps(resid, ensure_ascii=False)))

# ── ④ 两种形态 × 真实写侧链路 ────────────────────────────────────────
LOG.append("── ④ 形态覆盖（走 MakerDomain._normalize 落盘链路）──")
check("dict 形态·三池同内容 → 塌缩扁平 list[str]",
      N({"name": "T", "tags": {"简体中文": ["粘贴板"], "繁體中文": ["粘貼板"], "English": ["Clipboard"]}}).get("tags"),
      ["粘贴板"])
check("dict 形态·只送 English → 规范值扁平",
      N({"name": "T", "category": {"English": ["Game platform"]}}).get("category"), ["游戏平台"])
check("扁平 list 形态", N({"name": "T", "category": ["遊戲平台", "Game platform"]}).get("category"),
      ["游戏平台"])
check("逗号串历史形态", N({"name": "T", "tags": "粘貼板,Clipboard"}).get("tags"), ["粘贴板"])
check("三池内容不一致 → 保持字典形态（不合并内容），但值已规范化",
      N({"name": "T", "tags": {"简体中文": ["MC启动器", "知名"], "繁體中文": ["MC 啟動器"],
                               "English": ["MC launcher"]}}).get("tags"),
      {"简体中文": ["MC启动器", "知名"], "繁體中文": ["MC启动器"], "English": ["MC启动器"]})
check("全语言皆空 → 不写回字段（与 normalize_lang_list 的丢弃口径一致）",
      N({"name": "T", "category": {"简体中文": [], "繁體中文": [], "English": []}}).get("category"), None)
check("未知语言键不静默丢",
      canonicalize_lang_list({"English": ["Clipboard"], "日本語": ["貼上"]}),
      {"English": ["粘贴板"], "日本語": ["貼上"]})

# ── ⑤ 与当前界面语言无关 ───────────────────────────────────────────
LOG.append("── ⑤ 与当前界面语言无关（English 界面下同样还原）──")
mgr = lm.get_current_manager() or lm.LanguageManager()
switched = None
for code in ("English", "en_US", "en"):
    try:
        mgr.set_language(code)
        switched = code
        break
    except Exception:
        continue
LOG.append("     set_language(%r) 后 locale=%r" % (switched, mgr.locale()))
check("English 界面下 dict 反查 → 规范中文扁平",
      canonicalize_lang_list({"English": ["Clipboard"], "简体中文": ["粘贴板"], "繁體中文": ["粘貼板"]}, mgr),
      ["粘贴板"])
check("English 界面下读侧 translate_term('工具') 仍给显示译名（不变）",
      lm.translate_term("工具", mgr), "Tools")
check("English 界面下反查仍回规范中文", canonicalize_term("Tools", mgr), "工具")

# ── ⑥ 只动 category / tags ────────────────────────────────────────
LOG.append("── ⑥ links / name / description 的既有行为不变 ──")
raw = {"name": {"简体中文": "小工具", "繁體中文": "小工具", "English": "Widget"},
       "description": {"简体中文": "描述", "繁體中文": "描述", "English": "Desc"},
       "links": [{"label": {"简体中文": "官网", "繁體中文": "官網", "English": "Site"},
                  "url": "https://example.com"},
                 {"label": "Clipboard", "url": "https://example.org"}],
       "category": {"English": ["Game platform"]}}
got = N(raw)
check("links 未被值反查改写（与 normalize_links 结果完全一致）",
      got.get("links"), resource_schema.normalize_links(raw["links"]))
check("links 里那条 label='Clipboard' 仍是 'Clipboard'（证明兜底没越界动 links）",
      got["links"][1]["label"], "Clipboard")
# name / description 是 I18N_FIELDS（"一句话按语言翻"）：三语**不同**就保留字典，
# 这是既有口径；本次兜底只碰 LANG_LIST_FIELDS，所以这两个字段的形态不能受影响。
check("name 三语不同 → 仍保留字典（未被兜底动过）", got.get("name"), raw["name"])
check("description 三语不同 → 仍保留字典", got.get("description"), raw["description"])
check("category 已反查成规范值", got.get("category"), ["游戏平台"])
# 三语同值才塌缩成字符串（I18N_FIELDS 的既有约定，兜底后依然成立）
same = N({"name": {"简体中文": "小工具", "繁體中文": "小工具", "English": "小工具"},
          "description": {"简体中文": "描述", "繁體中文": "描述", "English": "描述"},
          "tags": {"简体中文": ["粘贴板"], "繁體中文": ["粘貼板"], "English": ["Clipboard"]}})
check("name 三语同值 → 仍塌缩成字符串", same.get("name"), "小工具")
check("description 三语同值 → 仍塌缩成字符串", same.get("description"), "描述")
check("同一条里 tags 塌缩、name 塌缩互不干扰", same.get("tags"), ["粘贴板"])
# 兜底绝不能伸进 name / description 的值里（那是要按语言显示的正文，不是枚举值）
nt = N({"name": {"简体中文": "Clipboard 粘贴板", "繁體中文": "Clipboard 粘贴板",
                 "English": "Clipboard 粘贴板"}, "tags": ["Clipboard"]})
check("name 里的 'Clipboard' 不被反查（只动 category/tags）", nt.get("name"), "Clipboard 粘贴板")
check("tags 里的 'Clipboard' 被反查", nt.get("tags"), ["粘贴板"])
LOG.append("     LANG_LIST_FIELDS=%s（兜底只碰这些字段）"
           % json.dumps(list(getattr(resource_schema, "LANG_LIST_FIELDS", ())), ensure_ascii=False))

# ── ⑦ 健壮性 ──────────────────────────────────────────────────────
LOG.append("── ⑦ 脏元素 / 拿不到管理器时不抛 ──")
check("非字符串元素原样保留", canonicalize_lang_list([{"坏": 1}, 2, "遊戲平台"]), [{"坏": 1}, 2, "游戏平台"])
check("None 原样", canonicalize_lang_list(None), None)
check("字符串原样（形状交给 normalize 压平）", canonicalize_lang_list("工具"), "工具")
check("空 dict 原样", canonicalize_lang_list({}), {})
check("manager=None 时仍返回字符串（内部会兜底建管理器）",
      isinstance(canonicalize_term("Clipboard", None), str), True)
check("坏条目整条不抛（links 传非 list）", isinstance(N({"name": "T", "links": "x", "tags": "遊戲平台"}), dict), True)

text = "\n".join(LOG) + "\n"
io.open(os.path.join(DEV, "probe_task24_canonical.out.txt"), "w", encoding="utf-8").write(text)
print(text)
print("失败 %d 项" % len(FAILS))
for f in FAILS:
    print("  FAIL:", f)
print("RESULT: " + ("PASS" if not FAILS else "FAIL"))
sys.exit(0 if not FAILS else 1)
