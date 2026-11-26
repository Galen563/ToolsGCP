
import json, sys, os
sys.stdout.reconfigure(errors="replace")
base = ".ToolsGCP/modules/languages"
out = {}
for loc in ("zh_CN","zh_TW","en_US"):
    p = os.path.join(base, loc, "common_language.json")
    d = json.load(open(p, encoding="utf-8"))
    terms = {k: v for k, v in d.items() if k.startswith("term_")}
    out[loc] = terms
    print(loc, "total", len(d), "term", len(terms))
zh = out["zh_CN"]
print("\n--- zh_CN term_ keys ---")
for k in sorted(zh): print(k[5:], "|", zh[k])
print("\n--- zh_TW term_ keys ---")
for k in sorted(out["zh_TW"]): print(k[5:], "|", out["zh_TW"][k])
print("\n--- en_US term_ keys ---")
for k in sorted(out["en_US"]): print(k[5:], "|", out["en_US"][k])
