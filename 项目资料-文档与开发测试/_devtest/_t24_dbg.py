# -*- coding: utf-8 -*-
import json, sys, os
sys.path[:0] = [os.path.abspath(".ToolsGCP"), os.path.abspath(".ToolsGCP/modules")]
from pymodels import constants
out = []
out.append("CONFIG_DIR=%r" % constants.CONFIG_DIR)
out.append("USER_DATA_ROOT=%r" % getattr(constants,"USER_DATA_ROOT",None))
out.append("LANGUAGES_DIR=%r exists=%s" % (constants.LANGUAGES_DIR, os.path.isdir(constants.LANGUAGES_DIR)))
from pymodels.core import language_manager as lm
mgr = lm.LanguageManager()
out.append("languages_dir=%r isdir=%s" % (mgr.languages_dir, os.path.isdir(mgr.languages_dir)))
for loc, mods in mgr.translations.items():
    out.append("locale %s modules=%d common_keys=%d" % (loc, len(mods), len((mods.get("common") or {}))))
    for m, kv in mods.items():
        if not kv: out.append("   EMPTY module %s" % m)
rev = lm._term_reverse(mgr)
out.append("rev size=%d" % len(rev))
out.append("canonical('Clipboard')=%r" % lm.canonical_term("Clipboard", mgr))
out.append("canonical('粘贴板')=%r" % lm.canonical_term("粘贴板", mgr))
open("项目资料-文档与开发测试/_devtest/_t24_dbg.txt","w",encoding="utf-8").write("\n".join(out))
print("done")
