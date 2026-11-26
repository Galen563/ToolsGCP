# -*- coding: utf-8 -*-
"""task-26 探针：repos（多组开源仓库）的 normalize / validate / github 互填不变量。

覆盖 lead 定的契约：
  ① 只有 github 的老数据 → normalize 反推出一行 repos，github 保持不变
  ② repos 里的坏行（url 非 http(s) / platform=none / 行不是对象）整行丢弃，
     github 取**第一行有效** url
  ③ repos 有值而 github 空 → github 补齐为首行 url
  ④ platform 由 url 反推（github/gitcode/gitee/gitlab 官方站点），认不出归 custom
  ⑤ 幂等：normalize(normalize(x)) == normalize(x)（含键序，用 json 串比）
  ⑥ validate 对坏行给人话问题、不抛异常；行数超 20 报截断提示
  ⑦ 真实资源库 57 条：normalize 前后 github **一字不变**（老读取方零改动的保证）
     + 每条都得到合法 repos + 二次幂等
  ⑧ detail 出口 _detail_repos 恒为 list[dict] 且 platform/url 都是纯字符串（脏输入不炸）
  ⑨ loader 摘要接口带 repos（卡片/列表那一路能拿到多组信息）

⚠️ 两个 Windows 坑（照抄 _devtest 里其它脚本的做法）：
  · sys.argv[0] 必须钉到 ROOT/ToolsGCP.pyw：constants.get_script_dir() 取的是
    dirname(abspath(sys.argv[0]))，指错 ⇒ LANGUAGES_DIR 指错 ⇒ 读到空表 ⇒ 假绿。
  · sys.stdout.reconfigure(errors="replace")：控制台是 GBK，中文断言名会 UnicodeEncodeError。

跑法：python "项目资料-文档与开发测试/_devtest/probe_repos_schema.py"
结尾打印 RESULT: PASS / RESULT: FAIL（退出码 0 / 1）。
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.argv[0] = os.path.join(ROOT, "ToolsGCP.pyw")
sys.path[:0] = [os.path.join(ROOT, ".ToolsGCP"), os.path.join(ROOT, ".ToolsGCP", "modules")]

try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

from pymodels.core import resource_schema as rs          # noqa: E402
from pymodels.core.resource_loader import ResourceLoader, SUMMARY_FIELDS  # noqa: E402

FAILS = []


def check(title, got, want):
    ok = got == want
    print(("%s " % ("ok  " if ok else "FAIL")) + title
          + ("" if ok else "   got=%s want=%s" % (json.dumps(got, ensure_ascii=False),
                                                  json.dumps(want, ensure_ascii=False))))
    if not ok:
        FAILS.append(title)


def dump(d):
    """按 json 串比较：既比值也比键序（lead 要求'字典序一致'）"""
    return json.dumps(d, ensure_ascii=False, sort_keys=False)


print("== 1) 老数据：只有 github -> 反推一行 repos ==")
one = rs.normalize({"id": "x", "code": "TG-1", "name": {"简体中文": "n"},
                    "github": "https://github.com/a/b"})
check("1.1 repos 自动补一行",
      one.get("repos"), [{"platform": "github", "url": "https://github.com/a/b"}])
check("1.2 github 保持不变", one.get("github"), "https://github.com/a/b")
check("1.3 幂等（二次 normalize 零 diff）", dump(rs.normalize(dict(one))), dump(one))

print("== 2) repos 多行 + 坏行丢弃 + github 取首行有效 ==")
mixed = rs.normalize({"id": "y", "code": "TG-2", "name": "N",
                      "repos": [
                          {"platform": "github", "url": "https://github.com/a/b"},
                          {"platform": "gitee", "url": "javascript:alert(1)"},
                          {"platform": "gitcode", "url": "https://gitcode.com/a/b"},
                      ]})
check("2.1 坏协议行被丢", [r["platform"] for r in mixed["repos"]], ["github", "gitcode"])
check("2.2 github == 第一行有效 url", mixed["github"], "https://github.com/a/b")
check("2.3 幂等", dump(rs.normalize(dict(mixed))), dump(mixed))

print("== 3) repos 有值而 github 空 -> github 补齐 ==")
gap = rs.normalize({"id": "z", "code": "TG-3", "name": "Z",
                    "repos": [{"platform": "custom", "url": "https://x.y/z"}]})
check("3.1 github 反填", gap.get("github"), "https://x.y/z")
check("3.2 repos 保留", gap.get("repos"), [{"platform": "custom", "url": "https://x.y/z"}])
check("3.3 幂等", dump(rs.normalize(dict(gap))), dump(gap))

print("== 4) 平台反推口径 ==")
cases = [("https://github.com/a/b", "github"), ("http://github.com/a/b", "github"),
         ("https://www.GitHub.com/a/b", "github"), ("https://gitee.com/a/b", "gitee"),
         ("https://gitcode.com/a/b", "gitcode"), ("https://gitlab.com/a/b", "gitlab"),
         ("https://gitlab.example.org/a/b", "custom"),
         ("https://code.mycompany.cn/a/b", "custom")]
for url, want in cases:
    check("4 %s -> %s" % (url, want), rs._repo_platform_of(url), want)

print("== 5) platform=none / 非闭集 / 脏行一律丢弃 ==")
drop = rs.normalize({"id": "w", "code": "TG-4", "name": "W",
                     "repos": [{"platform": "none", "url": "https://github.com/a/b"},
                               {"platform": "bitbucket", "url": "https://bitbucket.org/a/b"},
                               "字符串行", None, {"platform": "gitee"}]})
check("5.1 全坏行 -> repos 不落盘", "repos" in drop, False)
check("5.2 github 也没被瞎补", drop.get("github", ""), "")
check("5.3 幂等", dump(rs.normalize(dict(drop))), dump(drop))
none_only = rs.normalize({"id": "w2", "code": "TG-5", "name": "W2",
                          "github": "https://github.com/a/b",
                          "repos": [{"platform": "none", "url": "https://github.com/a/b"}]})
# none 行本身被丢（5.1~5.3 已验），但 github 是个有效网址 —— 契约第 2 条要求
# 「repos 清洗后为空而 github 有值」时**由 github 反补一行**，所以这里有一行是对的。
check("5.4 none 行被丢，repos 由 github 反补（契约第 2 条）",
      none_only.get("repos"), [{"platform": "github", "url": "https://github.com/a/b"}])
check("5.5 反补后 github 未被改写", none_only.get("github"), "https://github.com/a/b")
# 「明确声明不开源」的形态：platform=none 且 github 为空 —— 两个字段都不该落盘
silent = rs.normalize({"id": "w3", "code": "TG-5b", "name": "W3",
                       "repos": [{"platform": "none", "url": ""}]})
check("5.6 none + 无 github -> 两个字段都不写", ("repos" in silent) or ("github" in silent), False)

print("== 6) validate：坏行给人话问题、不抛异常 ==")
probs = rs.validate({"id": "v", "code": "TG-6", "name": "V",
                     "repos": [{"platform": "github", "url": "ftp://a/b"},
                               {"platform": "none", "url": "https://github.com/c/d"},
                               {"platform": "gitee", "url": "https://gitee.com/e/f"}]})
check("6.1 报出坏协议行", any("repos[0]" in p and "http/https" in p for p in probs), True)
check("6.2 报出 none 行", any("repos[1]" in p and "none" in p for p in probs), True)
check("6.3 有效行不报", any("repos[2]" in p for p in probs), False)
over = rs.validate({"id": "v2", "code": "TG-7", "name": "V2",
                    "repos": [{"platform": "custom", "url": "https://a%d/x" % i}
                              for i in range(rs.REPOS_MAX_ROWS + 3)]})
check("6.4 超上限报截断提示", any("超过上限" in p for p in over), True)
check("6.5 超上限 normalize 截断到 20",
      len(rs.normalize({"id": "v2", "code": "TG-7", "name": "V2",
                        "repos": [{"platform": "custom", "url": "https://a%d/x" % i}
                                  for i in range(rs.REPOS_MAX_ROWS + 3)]})["repos"]),
      rs.REPOS_MAX_ROWS)
check("6.6 形态离谱不抛（repos 是字符串）",
      isinstance(rs.validate({"id": "v3", "code": "TG-8", "name": "V3", "repos": "x"}), list), True)
check("6.7 同平台同 url（含尾斜杠差异）去重",
      rs.normalize({"id": "v4", "code": "TG-9", "name": "V4",
                    "repos": [{"platform": "github", "url": "https://github.com/a/b"},
                              {"platform": "github", "url": "https://github.com/a/b/"}]})["repos"],
      [{"platform": "github", "url": "https://github.com/a/b"}])
check("6.8 不同平台同 url 不去重（两条镜像都要留）",
      len(rs.normalize({"id": "v5", "code": "TG-10", "name": "V5",
                        "repos": [{"platform": "github", "url": "https://x/a.git"},
                                  {"platform": "gitee", "url": "https://x/a.git"}]})["repos"]), 2)

print("== 7) 真实资源库 57 条：github 一字不变 + 合法 repos + 幂等 ==")
lib = json.load(io.open(os.path.join(ROOT, ".ToolsGCP", "ToolsGCP-Resources.json"),
                        encoding="utf-8"))["resources"]
bad_github = []
bad_repos = []
not_idem = []
with_repos = 0
for item in lib:
    n = rs.normalize(dict(item))
    if n.get("github", "") != item.get("github", ""):
        bad_github.append(item.get("code"))
    rows = n.get("repos")
    if rows:
        with_repos += 1
        for row in rows:
            if row.get("platform") not in rs.REPOS_PLATFORMS or not rs.is_http_url(row.get("url")):
                bad_repos.append(item.get("code"))
    if dump(rs.normalize(dict(n))) != dump(n):
        not_idem.append(item.get("code"))
check("7.1 github 逐条一字不变", bad_github, [])
check("7.2 repos 行全部合法", bad_repos, [])
check("7.3 二次 normalize 幂等", not_idem, [])
print("     （%d/%d 条带 repos）" % (with_repos, len(lib)))
check("7.4 老数据也至少有一行 repos（有 github 的）",
      sum(1 for i in lib if i.get("github")) == with_repos, True)

print("== 8) detail 出口 _detail_repos：恒 list[dict]、脏输入不炸 ==")
from desktop.api.resources import _detail_repos                        # noqa: E402
check("8.1 干净形态原样", _detail_repos({"repos": [{"platform": "gitee", "url": "https://gitee.com/a/b"}]}),
      [{"platform": "gitee", "url": "https://gitee.com/a/b"}])
check("8.2 只有 github 时补一行", _detail_repos({"github": "https://github.com/a/b"}),
      [{"platform": "github", "url": "https://github.com/a/b"}])
dirty = _detail_repos({"repos": [{"platform": {"简体中文": "github"}, "url": {"简体中文": "https://gitee.com/a/b"}},
                                 "字符串", {"platform": "gitee", "url": "ftp://x"}]})
check("8.3 脏行（字典/字符串/坏协议）全部过滤，不露 dict",
      all(isinstance(r, dict) and isinstance(r["platform"], str) and isinstance(r["url"], str)
          for r in dirty), True)
check("8.4 非 http 的 url 不出去", any("ftp://" in json.dumps(r) for r in dirty), False)
check("8.5 无仓库返回空列表", _detail_repos({"id": "n"}), [])

print("== 9) loader 摘要接口带 repos ==")
check("9.1 SUMMARY_FIELDS 含 repos", "repos" in SUMMARY_FIELDS, True)
loader = ResourceLoader(language="简体中文")
assert loader.load_from_data({"schema_version": "2.1.0", "resources": [
    {"id": "l1", "code": "TG-L1", "name": "L1", "github": "https://github.com/a/b"},
    {"id": "l2", "code": "TG-L2", "name": "L2",
     "repos": [{"platform": "gitee", "url": "https://gitee.com/c/d"},
               {"platform": "github", "url": "https://github.com/c/d"}]}]}), "loader 载入失败"
summaries = {s["id"]: s for s in loader.get_summaries()}
check("9.2 摘要里 l1 有一行 repos", summaries["l1"].get("repos"),
      [{"platform": "github", "url": "https://github.com/a/b"}])
check("9.3 摘要里 l2 有两行 + github 取首行",
      [len(summaries["l2"]["repos"]), summaries["l2"]["github"]],
      [2, "https://gitee.com/c/d"])
check("9.4 全库校验零新增问题（repos 相关的坏数据才报）",
      [c for c, p in rs.validate_all([rs.normalize(dict(i)) for i in lib]).items()
       if any("repos" in x for x in p)], [])

print("")
if FAILS:
    print("FAILED %d 项 -> %s" % (len(FAILS), FAILS))
    print("RESULT: FAIL")
    sys.exit(1)
print("RESULT: PASS")
sys.exit(0)
