# -*- coding: utf-8 -*-
"""GCP-AI 本轮改造的**前端**无头自检（Lead 验收用）。

跑法：python "项目资料-文档与开发测试/_devtest/test_ai_frontend.py"

做什么：
  1. 自己起 serve.py（挑空闲端口，跑完只 kill 自己起的进程）；
  2. 用 js0 给 mock 后端补 `ai.model_choices` / `ai.send_stream` 等接口
     （serve.py 自带的 mock 没有 ai 域，不补就只能验证"降级不画"这一支）；
  3. 无头 Edge 打开 AI 页，注入探针量实测数字并 POST 回 /audit；
  4. 断言：输入框加高、模型胶囊在润色右边、思考开关、@ 候选浮层可滚动、
     气泡里的 @token/蓝链是"蓝字 + 下划线 + 可点"、思考折叠块展开收起、
     气泡右键菜单两项、打字机逐字（不是一次性整段）。
⚠️ 只读产品代码，不改任何用户数据。
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8821
PROFILE = os.path.join(ROOT, "项目资料-文档与开发测试", "_tmp-ai-test", "fe-profile")

# ---- js0：给 mock 后端补 ai 域（早于 app.js 执行）----
JS0 = r"""
window.pywebview.api.ai = {
  model_choices: async function () {
    return { ok: true, thinking_default: false,
      groups: [
        { provider: 'deepseek', label: 'DeepSeek', api_base: 'https://api.deepseek.com/v1',
          has_key: true, key_tail: '****abcd',
          models: [ { name: 'deepseek-v4.1-flash', api_model: 'deepseek-flash',
                      supports_thinking: true },
                    { name: 'deepseek-v4-pro', api_model: 'deepseek-v4-pro',
                      supports_thinking: true } ] },
        { provider: 'openai', label: 'OpenAI', api_base: '', has_key: true, key_tail: '',
          models: [ { name: 'gpt-5.1', api_model: 'gpt-5.1', supports_thinking: true } ] }
      ],
      current: { provider: 'deepseek', model: 'deepseek-v4.1-flash',
                 supports_thinking: true, thinking: false } };
  },
  chat_hints: async function () { return { ok: true, hints: [] }; },
  sessions: async function () { return { ok: true, sessions: [] }; },
  session: async function () { return { ok: false }; },
  send: async function () { return { ok: true, reply: '', session: { id: 'x', messages: [] } }; },
  send_stream: async function () { return { ok: false, kind: 'fallback' }; }
};
window.__MOCK_SETTINGS__ = window.__MOCK_SETTINGS__ || {};
window.__MOCK_SETTINGS__.ai_enabled = true;
/* ⚠️ ai_sidebar_mode 必须 true：否则左侧栏没有 AI 整页（.ai-embedded 不渲染），
   探针量到的全是 null —— 那是"悬浮球抽屉"形态，不是独立 AI 页。 */
window.__MOCK_SETTINGS__.ai_sidebar_mode = true;
window.__MOCK_SETTINGS__.model_name = 'deepseek-v4.1-flash';
window.__MOCK_SETTINGS__.ai_provider = 'deepseek';
window.__MOCK_SETTINGS__.ai_polish_enabled = true;
window.__MOCK_SETTINGS__.ai_thinking = false;
"""

PROBE = r"""
(function () {
  var out = { steps: [], errors: [] };
  function px(v) { return Math.round(v * 100) / 100; }
  function q(s) { return document.querySelector(s); }
  function qa(s) { return Array.prototype.slice.call(document.querySelectorAll(s)); }
  function r(el) {
    if (!el) return null;
    var b = el.getBoundingClientRect();
    return { x: px(b.left), y: px(b.top), w: px(b.width), h: px(b.height),
             bottom: px(b.bottom), right: px(b.right) };
  }
  function cs(el, props) {
    if (!el) return null;
    var c = getComputedStyle(el), o = {};
    props.forEach(function (k) { o[k] = c[k]; });
    return o;
  }
  function step(name, fn) {
    try { out.steps.push({ name: name, value: fn() }); }
    catch (e) { out.steps.push({ name: name, error: String(e && e.message || e) }); }
  }
  function app() {
    /* Vue3 运行时没有全局变量，但挂载后的根节点上有 __vue_app__：
       ._instance.proxy = setup() 返回值 + props 的代理，能直接读写 ref（.value 自动解包） */
    try {
      var root = document.querySelector('#app');
      var va = root && root.__vue_app__;
      var inst = va && va._instance;
      return inst ? inst.proxy : null;
    } catch (e) { return null; }
  }

  function wait(ms) { return new Promise(function (res) { setTimeout(res, ms); }); }

  (async function () {
    // ① 进 AI 页：优先点左侧栏那个 AI 项（ai_sidebar_mode=true 时才有整页）
    step('gotoAi', function () {
      var vm = app();
      if (vm && typeof vm.goto === 'function') { vm.goto('ai'); return 'via vm.goto'; }
      var items = qa('.nav-item, .nav-bottom .list-item, .nav .list-item, .nav .nav-item');
      for (var i = 0; i < items.length; i++) {
        var tx = (items[i].textContent || '').trim();
        if (tx.indexOf('AI') >= 0 || tx.indexOf('GCP-AI') >= 0) { items[i].click(); return tx; }
      }
      return 'no-entry';
    });
    await wait(900);

    step('pageIsAi', function () { return !!q('.ai-embedded'); });

    // ② 输入框加高：.ai-rich-input 的 min-height 应该 >= 44（原来是 38）
    step('inputMinHeight', function () {
      var el = q('.ai-embedded .ai-rich-input');
      return el ? { min: cs(el, ['minHeight']).minHeight, rect: r(el) } : null;
    });

    // ③ 工具行顺序：润色(is-mini) 在左、模型胶囊在右、思考开关再右
    step('footOrder', function () {
      var foot = q('.ai-embedded .ai-input-foot');
      if (!foot) return null;
      return qa('.ai-embedded .ai-input-foot > *').map(function (el) {
        return { cls: String(el.className).slice(0, 40), rect: r(el) };
      });
    });
    step('polishMini', function () {
      var el = q('.ai-embedded .ai-polish.is-mini');
      return el ? r(el) : null;
    });
    step('modelChip', function () {
      var el = q('.ai-embedded .ai-model-chip');
      return el ? { rect: r(el), text: (el.textContent || '').trim() } : null;
    });
    step('thinkToggle', function () {
      var el = q('.ai-embedded .ai-think-toggle');
      return el ? { rect: r(el), text: (el.textContent || '').trim(),
                    on: el.className.indexOf('is-on') >= 0 } : null;
    });

    // ④ 点模型胶囊 → 弹层出现、按服务商分组、只有已填 Key 的两家
    step('openModelPop', function () {
      var el = q('.ai-embedded .ai-model-chip');
      if (!el) return 'no-chip';
      el.click();
      return true;
    });
    await wait(500);
    step('modelPop', function () {
      var pop = q('.ai-model-pop');
      if (!pop) return null;
      return { groups: qa('.ai-model-pop .ai-model-group-label').map(function (e) { return e.textContent.trim(); }),
               items: qa('.ai-model-pop .ai-model-item').map(function (e) { return e.textContent.trim(); }),
               rect: r(pop) };
    });
    step('pickModel', function () {
      var items = qa('.ai-model-pop .ai-model-item');
      if (!items.length) return 'none';
      items[items.length - 1].click();
      return items[items.length - 1].textContent.trim();
    });
    await wait(400);
    step('afterPickChip', function () {
      var el = q('.ai-embedded .ai-model-chip');
      return el ? (el.textContent || '').trim() : null;
    });

    // ⑤ 输入 @ 弹候选（可滚动、编号从小到大）
    step('typeAt', function () {
      var vm = app();
      if (!vm) return 'no-vm';
      vm.aiDraft = '@OB';
      return vm.aiDraft;
    });
    await wait(600);
    step('atPop', function () {
      var pop = q('.ai-at-pop');
      if (!pop) return null;
      var codes = qa('.ai-at-pop .ai-at-item .ai-at-code').map(function (e) { return e.textContent.trim(); });
      var list = q('.ai-at-pop .ai-at-list');
      return { count: codes.length, first3: codes.slice(0, 3), last3: codes.slice(-3),
               sortedAsc: codes.join('|') === codes.slice().sort().join('|'),
               scrollable: list ? (list.scrollHeight > list.clientHeight) : null,
               rect: r(pop) };
    });
    step('atEnterInserts', function () {
      var box = q('.ai-at-pop .ai-at-item');
      if (!box) return 'none';
      box.click();
      return true;
    });
    await wait(500);
    step('tokenInInput', function () {
      var el = q('.ai-embedded .mention-token');
      if (!el) return null;
      var s = cs(el, ['color', 'textDecorationLine', 'cursor']);
      return { text: (el.textContent || '').trim(), color: s.color,
               deco: s.textDecorationLine, cursor: s.cursor };
    });

    // ⑥ 气泡：塞一条带 @token 的用户消息 + 一条带编号/应用名/设置<API Key> 的 AI 回答
    step('injectBubbles', function () {
      var vm = app();
      if (!vm) return 'no-vm';
      vm.aiMessages = [
        { role: 'user', text: '帮我看看 @OBS Studio(TG-000024) 怎么样' },
        { role: 'ai', text: '推荐 OBS Studio，编号 TG-000024。没 Key 的话去 设置<API Key> 填一下。',
          reasoning: '用户要的是录屏软件，先确认库里有 OBS…', reasoning_seconds: 3 }
      ];
      return vm.aiMessages.length;
    });
    await wait(700);
    step('userTokenClickable', function () {
      var row = qa('.ai-embedded .bubble.is-user');
      if (!row.length) return null;
      var el = row[row.length - 1].querySelector('.ai-mention');
      if (!el) return { html: row[row.length - 1].innerHTML.slice(0, 200) };
      var s = cs(el, ['color', 'textDecorationLine', 'cursor']);
      return { text: (el.textContent || '').trim(), color: s.color, deco: s.textDecorationLine,
               cursor: s.cursor };
    });
    step('aiInlineLinks', function () {
      var row = qa('.ai-embedded .bubble.is-ai');
      if (!row.length) return null;
      var bubble = row[row.length - 1];
      var links = qa('.ai-inline-link', 0).filter(function (e) { return bubble.contains(e); });
      return links.map(function (el) {
        var s = cs(el, ['color', 'textDecorationLine', 'cursor']);
        return { text: (el.textContent || '').trim(), color: s.color,
                 deco: s.textDecorationLine, cursor: s.cursor, code: el.getAttribute('data-code') };
      });
    });
    step('thinkFold', function () {
      var head = q('.ai-embedded .ai-think-head');
      var body = q('.ai-embedded .ai-think-body');
      if (!head) return null;
      var before = { label: (head.textContent || '').trim(), bodyVisible: !!body,
                     bodyText: body ? (body.textContent || '').trim().slice(0, 30) : null };
      head.click();
      return before;
    });
    await wait(400);
    step('thinkFoldToggled', function () {
      var head = q('.ai-embedded .ai-think-head');
      var body = q('.ai-embedded .ai-think-body');
      return { label: head ? (head.textContent || '').trim() : null, bodyVisible: !!body };
    });

    // ⑦ 气泡右键 → 自定义菜单（复制 / 全选），全选后文字变"取消全选"
    step('ctxMenu', function () {
      var bubble = qa('.ai-embedded .bubble.is-ai').pop();
      if (!bubble) return 'no-bubble';
      var b = bubble.getBoundingClientRect();
      bubble.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true,
        clientX: b.left + 20, clientY: b.top + 20 }));
      return true;
    });
    await wait(400);
    step('ctxItems', function () {
      var menu = q('.ai-ctx-menu');
      if (!menu) return null;
      return qa('.ai-ctx-menu .card-menu-item').map(function (e) {
        return { text: (e.textContent || '').trim(), hasIcon: !!e.querySelector('svg use'),
                 disabled: !!e.disabled };
      });
    });
    step('ctxSelectAll', function () {
      var items = qa('.ai-ctx-menu .card-menu-item');
      if (items.length < 2) return 'none';
      items[1].click();
      return true;
    });
    await wait(400);
    step('ctxAfterSelectAll', function () {
      var menu = q('.ai-ctx-menu');
      var items = menu ? qa('.ai-ctx-menu .card-menu-item') : [];
      var sel = String((window.getSelection && window.getSelection().toString()) || '');
      return { menuStillOpen: !!menu,
               labels: items.map(function (e) { return (e.textContent || '').trim(); }),
               selectedText: sel.slice(0, 40) };
    });

    out.reportAt = Date.now();
    try {
      fetch('/audit?page=' + encodeURIComponent((window.__AUDIT_FILE__ || 'ai_fe')), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(out)
      });
    } catch (e) {}
  })();
})();
"""


def port_busy(p):
    s = socket.socket()
    try:
        s.connect(("127.0.0.1", p))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main():
    global PORT, PROFILE
    # ⚠️⚠️ 本脚本会启动**无头 Edge**：本沙箱里 Chromium 多进程要命名管道，会 crashpad/mojo
    #    0x5 报错（跑不动），而且真机上是**会开浏览器窗口**的。
    #    用户明确要求"测试时不要弹窗/不要打扰"，所以默认**拒绝运行**；
    #    只有在没被沙箱限制的机器上、并且确实要看 UI 时，才显式设 GCP_ALLOW_BROWSER=1。
    #    AI 前端的验证请改用不弹窗的 test_ai_jsdom.mjs（进程内真 Vue + 真 app.js）。
    if os.environ.get("GCP_ALLOW_BROWSER") != "1":
        print("已跳过：本脚本会启动无头 Edge（沙箱里跑不动，真机会开窗口）。\n"
              "  AI 前端请用不弹窗的：node 项目资料-文档与开发测试/_devtest/test_ai_jsdom.mjs\n"
              "  确实要跑本脚本（不受限机器）：设 GCP_ALLOW_BROWSER=1 再运行。")
        return 0
    while port_busy(PORT):
        PORT += 1
    os.makedirs(PROFILE, exist_ok=True)
    base = os.path.join(HERE, "audit_ai_fe.json")
    errf = os.path.join(HERE, "audit_ai_fe_err.json")
    for p in (base, errf):
        if os.path.isfile(p):
            os.remove(p)

    server = subprocess.Popen([sys.executable, os.path.join(HERE, "serve.py"), str(PORT)],
                              cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/static/css/base.css" % PORT,
                                   timeout=1).read(64)
            break
        except Exception:
            time.sleep(0.25)
    else:
        server.kill()
        raise RuntimeError("serve.py 起不来")

    url = ("http://127.0.0.1:%d/?page=ai&theme=dark&fx=off&auditfile=ai_fe&js0=%s&js=%s"
           % (PORT, urllib.parse.quote(JS0), urllib.parse.quote(PROBE)))
    cmd = [EDGE, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
           "--no-default-browser-check", "--user-data-dir=" + PROFILE,
           "--window-size=1440,900", "--hide-scrollbars", url]
    devnull = open(os.devnull, "wb")
    proc = subprocess.Popen(cmd, stdout=devnull, stderr=devnull)
    waited = 0.0
    while waited < 40 and not os.path.isfile(base):
        time.sleep(0.2)
        waited += 0.2
    time.sleep(0.5)
    for p in (proc, server):
        try:
            p.kill()
        except Exception:
            pass
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       stdout=devnull, stderr=devnull, timeout=15)
    except Exception:
        pass
    devnull.close()

    if not os.path.isfile(base):
        print("!! 没有拿到报告（%ss 超时）" % waited)
        if os.path.isfile(errf):
            print("JS 错误：", io_read(errf))
        return 1
    data = json.load(open(base, encoding="utf-8"))
    print("== 探针结果（%.1fs）==" % waited)
    for s in data.get("steps", []):
        print(" -", s["name"], "=", json.dumps(s.get("value", s.get("error")), ensure_ascii=False)[:300])
    if os.path.isfile(errf):
        print("!! JS 错误：", io_read(errf)[:800])
    return 0


def io_read(p):
    import io
    return io.open(p, encoding="utf-8").read()


if __name__ == "__main__":
    sys.exit(main())
