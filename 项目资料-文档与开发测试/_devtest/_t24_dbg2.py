
# -*- coding: utf-8 -*-
import io, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEV = os.path.dirname(os.path.abspath(__file__))
sys.argv[0] = os.path.join(ROOT, "ToolsGCP.pyw")
sys.path[:0] = [os.path.join(ROOT, ".ToolsGCP"), os.path.join(ROOT, ".ToolsGCP", "modules")]
out = []
try:
    sys.stdout.reconfigure(errors="replace")
except Exception as e:
    out.append("reconfigure failed: %r" % e)
from pymodels import constants
out.append("LANGUAGES_DIR=%r exists=%s" % (constants.LANGUAGES_DIR, os.path.isdir(constants.LANGUAGES_DIR)))
from pymodels.core import language_manager as lm
from desktop.api import maker
m1 = lm.get_current_manager()
out.append("get_current_manager() -> %r" % (m1,))
m2 = maker._term_manager()
out.append("maker._term_manager() -> %r" % (m2,))
out.append("m2 is m1: %s" % (m2 is m1))
if m2 is not None:
    out.append("m2.translations locales=%s" % list((m2.translations or {}).keys()))
    for loc, d in (m2.translations or {}).items():
        out.append("  %s type=%s len=%s term_nest=%s" % (loc, type(d).__name__, len(d) if d else 0,
                   sum(1 for k, v in (d.items() if isinstance(d, dict) else []) if isinstance(v, dict))))
    rev = lm._term_reverse(m2)
    out.append("rev size=%d  Clipboard->%r" % (len(rev), rev.get("Clipboard")))
out.append("canonicalize_term('Clipboard') = %r" % (maker.canonicalize_term("Clipboard"),))
out.append("lm.canonical_term('Clipboard') = %r" % (lm.canonical_term("Clipboard"),))
out.append("lm.canonical_term('Clipboard', m2) = %r" % (lm.canonical_term("Clipboard", m2),))
io.open(os.path.join(DEV, "_t24_dbg2.txt"), "w", encoding="utf-8").write("\n".join(str(x) for x in out) + "\n")
print("ok")
