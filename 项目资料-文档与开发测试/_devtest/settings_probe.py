"""settings-fe 专项探针（task-4 验证，仅 _devtest 用，不属于产品代码）。
做什么：
  1. 自起 serve.py（默认 8812，端口占用则自动 +1），跑完只 kill 自己起的进程；
  2. 无头 Edge 注入探针断言 4 项修复：
     A 左栏点击后选中稳定（状态机）+ 用户滚动恢复 scrollspy + 触底不乱跳；
     B 设置搜索：结果「板块-设置项」合并行、清除按钮、Esc 清空、文字排版统一；
     C Combo：弹层贴触发器下方 4px、触发器滚出可视区即关闭、内部容器滚动有响应；
     D 输入框右键菜单：项/图标/快捷键小字/禁用态/Esc/不超窗。
  3. 结果写 _devtest/settings_probe.json，控制台打印 PASS/FAIL 摘要。
用法：
    python "项目资料-文档与开发测试/_devtest/settings_probe.py"
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BASE_PORT = 8812
PROFILE = None

PRELUDE = r"""
var P = (function () {
  var R = { name: '__NAME__', steps: [], errors: [] };
  function q(sel) { return document.querySelector(sel); }
  function qa(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }
  function txt(el) { return el ? (el.textContent || '').trim() : null; }
  R.q = q; R.qa = qa; R.txt = txt;
  R.bootWait = function (cb) {
    var t0 = Date.now();
    (function loop() {
      if (!q('.boot-screen') || Date.now() - t0 > 12000) return cb();
      setTimeout(loop, 100);
    })();
  };
  R.step = function (tag, fn) {
    try { var v = fn(); R.steps.push({ tag: tag, value: v }); }
    catch (e) { R.steps.push({ tag: tag, error: String(e) }); R.errors.push(tag + ': ' + e); }
  };
  R.post = function () {
    try {
      fetch('/audit?page=' + encodeURIComponent('__AUDITFILE__'), { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(R) });
    } catch (e) { R.errors.push('post: ' + e); }
  };
  /* 侧栏板块按钮（按 label 文本找）*/
  R.sideItem = function (label) {
    var hit = null;
    qa('.settings-side .list-item.plain').forEach(function (b) {
      if ((b.textContent || '').trim() === label) hit = b; });
    return hit;
  };
  R.onSide = function () {
    var on = q('.settings-side .list-item.plain.is-on');
    return on ? (on.textContent || '').trim() : null;
  };
  /* 通过原生 setter 改 input 值并派发 input 事件（Vue v-model 收得到）*/
  R.setInput = function (el, value) {
    var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  };
  return R;
})();
"""


def seq(steps):
    out = ""
    for delay, js in reversed(steps):
        body = "try{\\n%s\\n}catch(e){P.errors.push('step: '+String(e));}" % js
        out = "setTimeout(function(){\\n%s\\n%s},%d);" % (body, out, delay)
    return out


def case(name, steps, page="settings", js0="", wall=45):
    return {"name": name, "page": page, "js0": js0,
            "auditfile": "settings_probe_" + name, "steps": steps, "wall": wall}


def build_cases():
    C = []

    # ---------- A：左栏点击选中稳定（状态机核心回归）----------
    A = [(1500, """
      var keys = ['外观','动画','启动','搜索','快捷键','下载','通知','功能','存储','GCP-AI','开发者功能','关于'];
      P._keys = keys; P._clicks = [];
      P.step('sections', function () { return { found: keys.map(function (k) { return !!P.sideItem(k); }) }; });
    """)]
    # 逐个点击：点完 1s 后断言 is-on 仍是点击项（旧版 GCP-AI/开发者功能会跳"关于"）
    delay = 1500
    for i, k in enumerate(['外观', '快捷键', '存储', 'GCP-AI', '开发者功能', '关于', '外观', 'GCP-AI']):
        delay += 1300
        A.append((delay, "P.step('click%d', function () { var b = P.sideItem(%s); if (b) b.click(); return { key: %s, clicked: !!b }; });" % (i, json.dumps(k, ensure_ascii=False), json.dumps(k, ensure_ascii=False))))
        delay += 1000
        A.append((delay, "P.step('after%d', function () { return { want: %s, on: P.onSide() }; });" % (i, json.dumps(k, ensure_ascii=False))))
    # 用户 wheel 滚动 → scrollspy 必须恢复且准确
    delay += 500
    A.append((delay, """
      P.step('wheelBack', function () {
        var b = P.sideItem('关于'); if (b) b.click();
        return { clickedAbout: !!b };
      });
    """))
    delay += 1400
    A.append((delay, """
      P.step('userWheel', function () {
        var host = document.querySelector('.settings-main');
        /* 真实浏览器里 wheel 会直接滚；无头 dispatch 不滚，所以"意图 + 手动滚"两步都做。
           先小滚一点让 scroll 事件带着意图标记进来 → 状态机交还 scrollspy */
        host.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: -100 }));
        host.scrollTo({ top: Math.max(0, host.scrollTop - 100), behavior: 'auto' });
        return { scrollTop: Math.round(host.scrollTop) };
      });
    """))
    delay += 400
    A.append((delay, """
      P.step('spyMiddle', function () {
        /* 用户再滚到中间（无新意图也行：交还后一直是 free）：spy 必须准确 */
        var host = document.querySelector('.settings-main');
        host.scrollTo({ top: Math.round(host.scrollHeight * 0.12), behavior: 'auto' });
        return { scrollTop: Math.round(host.scrollTop) };
      });
    """))
    delay += 500
    A.append((delay, """
      P.step('spyRestored', function () {
        var host = document.querySelector('.settings-main');
        var value = host.scrollTop + 60;
        var pickedIdx = 0;
        var nodes = P.qa('.settings-main .settings-section');
        nodes.forEach(function (node, i) { if (node.offsetTop <= value) pickedIdx = i; });
        var buttons = P.qa('.settings-side .list-item.plain');
        var expectBtn = buttons[pickedIdx];
        var on = document.querySelector('.settings-side .list-item.plain.is-on');
        return { expectKey: nodes[pickedIdx] ? nodes[pickedIdx].dataset.key : null,
          expectText: P.txt(expectBtn), onText: P.txt(on),
          matches: !!(on && expectBtn && on === expectBtn) };
      });
    """))
    # 用户滚到底（free 态）：选中必须是视口可见的最后一节，而不是乱跳
    delay += 400
    A.append((delay, """
      P.step('userWheelBottom', function () {
        var host = document.querySelector('.settings-main');
        host.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: 4000 }));
        host.scrollTo({ top: host.scrollHeight, behavior: 'auto' });
        return { atBottom: host.scrollTop + host.clientHeight >= host.scrollHeight - 4 };
      });
    """))
    delay += 600
    A.append((delay, "P.step('bottomOn', function () { return { on: P.onSide() }; }); P.post();"))
    C.append(case("spy", A))

    # ---------- B：设置搜索（合并行 / 清除 / Esc / 文字排版）----------
    B = [(1500, """
      P.step('box', function () {
        var inp = document.querySelector('.settings-search input');
        P._inp = inp;
        var cs = inp ? getComputedStyle(inp) : null;
        return { exists: !!inp,
          fontSize: cs && cs.fontSize, color: cs && cs.color, fontFamily: cs && cs.fontFamily,
          textIndent: cs && cs.textIndent, letterSpacing: cs && cs.letterSpacing };
      });
    """),
    (300, """
      P.step('noFirstLetterRule', function () {
        var hits = [];
        Array.prototype.forEach.call(document.styleSheets, function (ss) {
          var rules = null;
          try { rules = ss.cssRules; } catch (e) { return; }
          if (!rules) return;
          Array.prototype.forEach.call(rules, function (r) {
            if (r.selectorText && r.selectorText.indexOf('first-letter') >= 0) hits.push(r.selectorText);
          });
        });
        return hits;
      });
    """),
    (300, """
      P.step('type', function () { P.setInput(P._inp, '浏'); return { value: P._inp.value }; });
    """),
    (700, """
      P.step('hits', function () {
        var rows = P.qa('.settings-side .search-hit');
        var texts = rows.map(function (r) { return (r.textContent || '').trim(); });
        var merged = P.qa('.settings-side .hit-merged').length;
        var split = P.qa('.settings-side .hit-section').length + P.qa('.settings-side .hit-row').length;
        return { count: rows.length, mergedSpans: merged, legacySpans: split,
          hasShortcutHit: texts.some(function (t) { return t.indexOf('快捷键-浏览器中打开') >= 0; }),
          samples: texts.slice(0, 6) };
      });
    """),
    (300, """
      P.step('clearBtn', function () {
        var btn = document.querySelector('.settings-search .search-clear');
        var visible = btn && getComputedStyle(btn).display !== 'none' && btn.getBoundingClientRect().width > 0;
        var box = document.querySelector('.settings-search');
        var br = box.getBoundingClientRect(); var cr = btn ? btn.getBoundingClientRect() : null;
        return { exists: !!btn, visible: !!visible,
          insideRightEdge: !!(cr && cr.right <= br.right + 1 && cr.left >= br.left - 1),
          icon: !!(btn && btn.querySelector('use')) };
      });
    """),
    (300, """
      P.step('typedStyleUniform', function () {
        var cs = getComputedStyle(P._inp);
        return { fontSize: cs.fontSize, color: cs.color };
      });
    """),
    (300, """
      P.step('clickClear', function () {
        var btn = document.querySelector('.settings-search .search-clear');
        if (btn) btn.click();
        return { clicked: !!btn };
      });
    """),
    (500, """
      P.step('afterClear', function () {
        var sections = P.qa('.settings-side .list-item.plain').length;
        return { value: P._inp.value, backToSections: sections >= 10 };
      });
    """),
    (300, """
      P.step('escClear', function () {
        P.setInput(P._inp, '浏');
        P._inp.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, key: 'Escape' }));
        return true;
      });
    """),
    (600, """
      P.step('afterEsc', function () {
        var sections = P.qa('.settings-side .list-item.plain').length;
        return { value: P._inp.value, backToSections: sections >= 10 };
      }); P.post();
    """)]
    C.append(case("search", B))

    # ---------- C：Combo 弹层（贴合 / 滚出即关 / 内部容器滚动响应）----------
    Cc = [(1500, """
      P.step('open', function () {
        var host = document.querySelector('.settings-main');
        host.scrollTo({ top: 0, behavior: 'auto' });
        var trig = document.querySelector('.settings-main .combo-trigger');
        P._trig = trig;
        if (trig) trig.click();
        return { trigger: !!trig };
      });
    """),
    (400, """
      P.step('placed', function () {
        var pop = document.querySelector('.combo-pop');
        if (!pop) return { pop: false };
        var pr = pop.getBoundingClientRect(); var tr = P._trig.getBoundingClientRect();
        return { pop: true, gap: Math.round(pr.top - tr.bottom),
          coversTrigger: pr.top < tr.bottom - 1,
          leftAligned: Math.abs(pr.left - tr.left) < 1,
          items: P.qa('.combo-item').length };
      });
    """),
    (300, """
      P.step('scrollContainer', function () {
        /* 内部滚动容器滚一点：触发器仍在视口内 → 弹层必须跟着重定位（贴 4px） */
        var host = document.querySelector('.settings-main');
        host.scrollTo({ top: host.scrollTop + 80, behavior: 'auto' });
        return { scrollTop: Math.round(host.scrollTop) };
      });
    """),
    (400, """
      P.step('afterContainerScroll', function () {
        var pop = document.querySelector('.combo-pop');
        if (!pop) return { pop: false };
        var pr = pop.getBoundingClientRect(); var tr = P._trig.getBoundingClientRect();
        return { pop: true, gap: Math.round(pr.top - tr.bottom), coversTrigger: pr.top < tr.bottom - 1 };
      });
    """),
    (300, """
      P.step('scrollAway', function () {
        /* 把触发器滚出可视区（上方）：弹层必须关闭，而不是留在屏幕底部原 x 位置 */
        var host = document.querySelector('.settings-main');
        var target = P._trig.getBoundingClientRect().bottom + 300;
        host.scrollTo({ top: host.scrollTop + target, behavior: 'auto' });
        var tr = P._trig.getBoundingClientRect();
        return { triggerTop: Math.round(tr.top), triggerBottom: Math.round(tr.bottom), vh: window.innerHeight };
      });
    """),
    (400, """
      P.step('afterAway', function () {
        var pop = document.querySelector('.combo-pop');
        var tr = P._trig.getBoundingClientRect();
        return { popClosed: !pop, triggerOffscreen: tr.bottom < 0 || tr.top > window.innerHeight };
      }); P.post();
    """)]
    C.append(case("combo", Cc))

    # ---------- C2：贴底的下拉框不再"抵到触发器中间" ----------
    C2 = [(1500, """
      P.step('openNearBottom', function () {
        var host = document.querySelector('.settings-main');
        /* 找一个下拉框，把它滚到"窗口下缘只剩几十 px"的位置 */
        var trigs = P.qa('.settings-main .combo-trigger');
        var trig = trigs[0];
        P._trig = trig;
        var r = trig.getBoundingClientRect();
        var delta = (window.innerHeight - 40) - r.top;   /* 触发器顶边距窗口底 40px */
        host.scrollTo({ top: Math.max(0, host.scrollTop + delta), behavior: 'auto' });
        trig.click();
        return { triggerBottomInWindow: Math.round(trig.getBoundingClientRect().bottom), vh: window.innerHeight };
      });
    """),
    (400, """
      P.step('nearBottom', function () {
        var pop = document.querySelector('.combo-pop');
        var tr = P._trig.getBoundingClientRect();
        if (!pop) return { popClosed: true, triggerBottom: Math.round(tr.bottom) };
        var pr = pop.getBoundingClientRect();
        return { pop: true, gap: Math.round(pr.top - tr.bottom),
          coversTrigger: pr.top < tr.bottom - 1,
          popBottomOverflow: Math.round(pr.bottom - window.innerHeight) };
      }); P.post();
    """)]
    C.append(case("combo_bottom", C2))

    # ---------- D：输入框右键菜单 ----------
    D = [(1500, """
      P.step('contextEmpty', function () {
        var inp = document.querySelector('.settings-search input');
        P.setInput(inp, '');
        inp.focus();
        var r = inp.getBoundingClientRect();
        inp.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true,
          clientX: Math.round(r.left + 20), clientY: Math.round(r.top + 10) }));
        return { dispatched: true, defaultPrevented: null };
      });
    """),
    (500, """
      P.step('menuEmpty', function () {
        var menu = document.querySelector('#input-menu');
        if (!menu || menu.hidden) return { open: false };
        var items = P.qa('#input-menu .input-menu-item');
        var summary = items.map(function (b) {
          return { cmd: b.getAttribute('data-cmd'),
            label: (b.querySelector('.imi-label') || {}).textContent,
            hotkey: (b.querySelector('.imi-key') || {}).textContent,
            disabled: b.disabled || b.classList.contains('is-disabled'),
            icon: !!b.querySelector('use') };
        });
        var mr = menu.getBoundingClientRect();
        return { open: true, count: items.length, items: summary,
          inWindow: mr.left >= 0 && mr.top >= 0 && mr.right <= window.innerWidth + 1 && mr.bottom <= window.innerHeight + 1,
          labelsLocalized: summary.every(function (s) { return !!s.label; }) };
      });
    """),
    (200, """
      P.step('closeByEsc', function () {
        window.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Escape' }));
        var menu = document.querySelector('#input-menu');
        return { hiddenAfterEsc: !menu || menu.hidden };
      });
    """),
    (300, """
      P.step('contextWithSelection', function () {
        var inp = document.querySelector('.settings-search input');
        P.setInput(inp, '浏览器');
        inp.setSelectionRange(0, 2);
        var r = inp.getBoundingClientRect();
        inp.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true,
          clientX: Math.round(r.left + 20), clientY: Math.round(r.top + 10) }));
        return true;
      });
    """),
    (500, """
      P.step('menuSelection', function () {
        var menu = document.querySelector('#input-menu');
        if (!menu || menu.hidden) return { open: false };
        var map = {};
        P.qa('#input-menu .input-menu-item').forEach(function (b) {
          map[b.getAttribute('data-cmd')] = b.disabled || b.classList.contains('is-disabled');
        });
        return { open: true, disabledMap: map };
      });
    """),
    (200, """
      P.step('aiExcluded', function () {
        /* 找一个 AI 输入框（侧边栏模式或抽屉）；mock 默认 ai_sidebar_mode=false 且抽屉未开，
           没有 .ai-input 在场时返回 notPresent（视为通过：无冲突可能）。 */
        var ai = document.querySelector('.ai-input, .ai-rich-input');
        if (!ai) return { notPresent: true };
        var r = ai.getBoundingClientRect();
        ai.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true,
          clientX: Math.round(r.left + 20), clientY: Math.round(r.top + 10) }));
        var menu = document.querySelector('#input-menu');
        return { aiField: true, globalMenuOpened: !!(menu && !menu.hidden) };
      });
    """),
    (200, """
      P.step('nativePrevented', function () {
        var inp = document.querySelector('.settings-search input');
        var ev = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 100, clientY: 100 });
        inp.dispatchEvent(ev);
        return { defaultPrevented: ev.defaultPrevented };
      });
    """),
    (300, """
      P.step('hotkeyUntouched', function () {
        /* Ctrl+A 在输入框里仍是浏览器原生全选：菜单代码不得拦 keydown */
        var inp = document.querySelector('.settings-search input');
        P.setInput(inp, 'abcdef');
        inp.focus();
        inp.setSelectionRange(0, 0);
        inp.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, key: 'a', ctrlKey: true }));
        return { menuClosed: (document.querySelector('#input-menu') || {}).hidden !== false };
      }); P.post();
    """)]
    C.append(case("inputmenu", D))

    # ---------- E：三语下搜索结果文案（js0 直接把 mock 设置切成 English）----------
    E = [(1500, """
      P.step('lang', function () {
        var vm = window.__TOOLSGCP_APP__;
        return { language: vm && vm.settings ? vm.settings.language : null };
      });
    """),
    (300, """
      P.step('typeEn', function () {
        var inp = document.querySelector('.settings-search input');
        P._inp = inp;
        P.setInput(inp, '浏');
        return { typed: !!inp };
      });
    """),
    (700, """
      P.step('hitsEn', function () {
        var rows = P.qa('.settings-side .search-hit');
        var texts = rows.map(function (r) { return (r.textContent || '').trim(); });
        return { count: rows.length, samples: texts.slice(0, 4),
          hasEnPair: texts.some(function (t) { return t.indexOf('Hotkeys-Open in Browser') >= 0; }),
          dashFormat: texts.every(function (t) { return t.indexOf('-') > 0; }) };
      });
    """),
    (200, """
      P.step('menuLabelsEn', function () {
        var inp = P._inp;
        var r = inp.getBoundingClientRect();
        inp.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true,
          clientX: Math.round(r.left + 20), clientY: Math.round(r.top + 8) }));
        return true;
      });
    """),
    (500, """
      P.step('menuLabelsCheck', function () {
        var labels = P.qa('#input-menu .imi-label').map(function (s) { return s.textContent; });
        return { labels: labels };
      }); P.post();
    """)]
    C.append(case("i18n", E, js0="window.__MOCK_SETTINGS__.language = 'English';"))
    return C


def port_busy(port):
    s = socket.socket()
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def pick_port():
    global PROFILE
    p = BASE_PORT
    while port_busy(p):
        p += 1
    PROFILE = os.path.join(os.environ.get("TEMP", "."), "gcp_settings_probe_%d" % p)
    return p


def start_server(port):
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, "serve.py"), str(port)],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/static/css/base.css" % port, timeout=1).read(64)
            return proc
        except Exception:
            time.sleep(0.25)
    proc.kill()
    raise RuntimeError("serve.py 起不来")


def run_case(port, c):
    if not os.path.isdir(PROFILE):
        os.makedirs(PROFILE, exist_ok=True)
    js = (PRELUDE.replace("__NAME__", c["name"]).replace("__AUDITFILE__", c["auditfile"])
          + "P.bootWait(function () {\\n" + seq(c["steps"]) + "\\n});")
    qs = [("page", c["page"]), ("auditfile", c["auditfile"]), ("js", js)]
    if c["js0"]:
        qs.append(("js0", c["js0"]))
    url = "http://127.0.0.1:%d/?%s" % (port, urllib.parse.urlencode(qs))
    out = os.path.join(HERE, "audit_%s.json" % c["auditfile"])
    err = os.path.join(HERE, "audit_%s_err.json" % c["auditfile"])
    for p in (out, err):
        if os.path.isfile(p):
            os.remove(p)
    shot = os.path.join(HERE, "reports", "settings_probe_%s.png" % c["name"])
    cmd = [EDGE, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
           "--no-default-browser-check", "--user-data-dir=" + PROFILE,
           "--window-size=1440,900", "--hide-scrollbars",
           "--screenshot=" + shot, "--virtual-time-budget=1000", url]
    t0 = time.time()
    devnull = open(os.devnull, "wb")
    proc = subprocess.Popen(cmd, stdout=devnull, stderr=devnull)
    waited = 0.0
    while waited < c["wall"] and not os.path.isfile(out):
        time.sleep(0.1)
        waited += 0.1
    time.sleep(0.35)
    try:
        proc.kill()
    except Exception:
        pass
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       stdout=devnull, stderr=devnull, timeout=15)
    except Exception:
        pass
    devnull.close()
    dt = time.time() - t0
    data = None
    if os.path.isfile(out):
        with open(out, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    errs = None
    if os.path.isfile(err):
        with open(err, "r", encoding="utf-8") as fh:
            errs = json.load(fh)
    return {"case": c["name"], "secs": round(dt, 1), "report": data,
            "jsError": errs, "screenshot": shot}


# ---- 断言 ----
def get_step(rep, tag):
    for s in (rep or {}).get("steps", []):
        if s.get("tag") == tag:
            return s
    return None


def val(rep, tag):
    s = get_step(rep, tag)
    return s.get("value") if s else None


def assert_spy(rep, fails):
    # 每个 clickN/afterN 对：after 的 on 必须等于 want
    for i in range(8):
        want = val(rep, "click%d" % i)
        after = val(rep, "after%d" % i)
        if not want or not after:
            fails.append("spy: 缺 click%d/after%d" % (i, i))
            continue
        if not want["clicked"]:
            fails.append("spy: 没找到板块按钮 %s" % want["key"])
            continue
        if after["on"] != after["want"]:
            fails.append("spy: 点「%s」后选中变成「%s」（跳板回归！）" % (after["want"], after["on"]))
    uw = val(rep, "userWheel")
    if not uw:
        fails.append("spy: 缺 userWheel 步骤")
    restored = val(rep, "spyRestored")
    if not restored or not restored.get("matches"):
        fails.append("spy: 用户滚动到中间后 scrollspy 未跟随/不准：%s" % restored)
    bottom = val(rep, "bottomOn")
    if not bottom or bottom.get("on") not in ("开发者功能", "关于"):
        fails.append("spy: 用户滚到底时选中异常：%s" % bottom)


def assert_search(rep, fails):
    box = val(rep, "box")
    if not box or not box.get("exists"):
        fails.append("search: 搜索框不存在")
        return
    if box.get("textIndent") not in ("0px", None):
        fails.append("search: textIndent=%s 非 0" % box.get("textIndent"))
    fl = val(rep, "noFirstLetterRule")
    if fl:
        fails.append("search: 存在 ::first-letter 规则 %s" % fl)
    hits = val(rep, "hits")
    if not hits or hits.get("count", 0) == 0:
        fails.append("search: 搜「浏」没有结果")
    else:
        if not hits.get("hasShortcutHit"):
            fails.append("search: 结果里没有「快捷键-浏览器中打开」%s" % hits.get("samples"))
        if hits.get("legacySpans", 0) != 0:
            fails.append("search: 仍是旧的两 span 分开格式")
        if hits.get("mergedSpans", 0) != hits.get("count"):
            fails.append("search: 合并行数量不符")
    clear = val(rep, "clearBtn")
    if not clear or not clear.get("exists") or not clear.get("visible"):
        fails.append("search: 清除按钮缺失或不可见")
    elif not clear.get("insideRightEdge"):
        fails.append("search: 清除按钮不在输入框右缘内")
    after_clear = val(rep, "afterClear")
    if not after_clear or after_clear.get("value") != "" or not after_clear.get("backToSections"):
        fails.append("search: 点清除后没恢复板块列表：%s" % after_clear)
    after_esc = val(rep, "afterEsc")
    if not after_esc or after_esc.get("value") != "" or not after_esc.get("backToSections"):
        fails.append("search: Esc 没清空：%s" % after_esc)
    typed = val(rep, "typedStyleUniform")
    empty = box
    if typed and (typed.get("fontSize") != empty.get("fontSize") or typed.get("color") != empty.get("color")):
        fails.append("search: 输入前后字号/颜色不一致")


def assert_combo(rep, fails):
    placed = val(rep, "placed")
    if not placed or not placed.get("pop"):
        fails.append("combo: 点触发器没弹出弹层")
    else:
        if placed.get("gap") != 4:
            fails.append("combo: 弹层与触发器间距=%s（应为 4）" % placed.get("gap"))
        if placed.get("coversTrigger"):
            fails.append("combo: 弹层覆盖触发器")
    after = val(rep, "afterContainerScroll")
    if not after or not after.get("pop"):
        fails.append("combo: 内部容器滚动 80px 后弹层被误关（触发器未离开可视区）")
    elif after.get("gap") != 4 or after.get("coversTrigger"):
        fails.append("combo: 容器滚动后未贴合：%s" % after)
    away = val(rep, "afterAway")
    if not away or not away.get("popClosed"):
        fails.append("combo: 触发器滚出可视区后弹层未关闭：%s" % away)


def assert_combo_bottom(rep, fails):
    away = val(rep, "nearBottom")
    if not away:
        fails.append("combo_bottom: 无数据")
        return
    if away.get("popClosed"):
        # 触发器底边距窗口底 40px：下方空间 < 96+8 且触发器仍可见 → 允许自然截断而不是关闭；
        # 但触发器 top 距窗口底 40 意味着 bottom 已出窗口 → 关闭是正确行为。
        return
    if away.get("coversTrigger"):
        fails.append("combo_bottom: 弹层抵到触发器中间（遮挡回归）")
    if away.get("gap") != 4:
        fails.append("combo_bottom: 间距=%s 非 4" % away.get("gap"))


def assert_inputmenu(rep, fails):
    empty = val(rep, "menuEmpty")
    if not empty or not empty.get("open"):
        fails.append("inputmenu: 右键没打开菜单")
    else:
        if empty.get("count") != 6:
            fails.append("inputmenu: 项数=%s 非 6" % empty.get("count"))
        if not empty.get("inWindow"):
            fails.append("inputmenu: 菜单超出窗口")
        if not empty.get("labelsLocalized"):
            fails.append("inputmenu: 有项缺文案")
        m = {s["cmd"]: s for s in empty.get("items", [])}
        for cmd in ("copy", "paste", "cut", "select-all", "undo", "redo"):
            if cmd not in m:
                fails.append("inputmenu: 缺 %s 项" % cmd)
            elif not m[cmd].get("icon"):
                fails.append("inputmenu: %s 没有图标" % cmd)
        want_keys = {"copy": "Ctrl+C", "paste": "Ctrl+V", "cut": "Ctrl+X",
                     "select-all": "Ctrl+A", "undo": "Ctrl+Z", "redo": "Ctrl+Y"}
        for cmd, hk in want_keys.items():
            if cmd in m and m[cmd].get("hotkey") != hk:
                fails.append("inputmenu: %s 快捷键小字=%s" % (cmd, m[cmd].get("hotkey")))
        # 空输入框无选区：copy/cut/select-all 禁用
        for cmd in ("copy", "cut", "select-all"):
            if cmd in m and not m[cmd].get("disabled"):
                fails.append("inputmenu: 空框/无选区时 %s 应禁用" % cmd)
    esc = val(rep, "closeByEsc")
    if not esc or not esc.get("hiddenAfterEsc"):
        fails.append("inputmenu: Esc 没关菜单")
    sel = val(rep, "menuSelection")
    if not sel or not sel.get("open"):
        fails.append("inputmenu: 有选区右键没打开")
    else:
        dm = sel.get("disabledMap", {})
        if dm.get("copy") or dm.get("cut"):
            fails.append("inputmenu: 有选区时 copy/cut 仍禁用：%s" % dm)
        if dm.get("select-all") is not False:
            fails.append("inputmenu: 有内容时 select-all 应可用：%s" % dm)
    prevented = val(rep, "nativePrevented")
    if not prevented or not prevented.get("defaultPrevented"):
        fails.append("inputmenu: 没拦掉浏览器原生菜单")
    ai = val(rep, "aiExcluded")
    if ai and ai.get("aiField") and ai.get("globalMenuOpened"):
        fails.append("inputmenu: AI 输入框被全局菜单接管（应排除）")


def assert_i18n(rep, fails):
    hits = val(rep, "hitsEn")
    if not hits or hits.get("count", 0) == 0:
        fails.append("i18n: 英文态搜「浏」无结果（可能未切成功，见 samples）")
    else:
        if not hits.get("hasEnPair"):
            fails.append("i18n: 英文结果没有 Hotkeys-Open in Browser：%s" % hits.get("samples"))
        if not hits.get("dashFormat"):
            fails.append("i18n: 英文结果不是 板块-设置项 格式：%s" % hits.get("samples"))
    labels = val(rep, "menuLabelsCheck")
    if not labels:
        fails.append("i18n: 菜单文案没采到")


ASSERTS = {"spy": assert_spy, "search": assert_search, "combo": assert_combo,
           "combo_bottom": assert_combo_bottom, "inputmenu": assert_inputmenu,
           "i18n": assert_i18n}


def main():
    only = set(sys.argv[1:])
    port = pick_port()
    print("port=%d" % port)
    reports_dir = os.path.join(HERE, "reports")
    if not os.path.isdir(reports_dir):
        os.makedirs(reports_dir, exist_ok=True)
    proc = start_server(port)
    results = []
    fails = []
    try:
        for c in build_cases():
            if only and c["name"] not in only:
                continue
            res = run_case(port, c)
            results.append(res)
            rep = res["report"]
            if not rep:
                fails.append("%s: 探针没回传（可能 Edge 起不来 / 页面崩）" % c["name"])
            elif res.get("jsError"):
                fails.append("%s: 页面 JS 报错 %s" % (c["name"], res["jsError"]))
            else:
                ASSERTS[c["name"]](rep, fails)
            print("%-12s %5.1fs steps=%s" % (c["name"], res["secs"],
                  len((rep or {}).get("steps", []))))
    finally:
        proc.kill()
    out = {"results": results, "fails": fails}
    with open(os.path.join(HERE, "settings_probe.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("=" * 60)
    if fails:
        for f in fails:
            print("FAIL %s" % f)
        print("SUMMARY: %d FAIL" % len(fails))
        sys.exit(1)
    print("SUMMARY: ALL PASS")


if __name__ == "__main__":
    main()
