"""临时开发用静态服务器（仅用于本地 UI 自检，不属于产品代码）。
- /                -> webui/index.html（可注入 mock pywebview.bridge）
- /static/<path>   -> webui/<path>
- /res/<path>      -> .ToolsGCP/<path>
用法：
    python _devtest/serve.py [port]
浏览器打开 http://127.0.0.1:<port>/
"""
import json
import mimetypes
import os
import posixpath
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # 已下沉到 项目资料-文档与开发测试/_devtest/
WEBUI = os.path.join(ROOT, ".ToolsGCP", "webui")   # webui 已搬进 .ToolsGCP
DATA = os.path.join(ROOT, ".ToolsGCP")

EXTRA_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def safe_join(root, rel):
    rel = str(rel or "").replace("\\", "/").lstrip("/")
    rel = posixpath.normpath(rel)
    if rel in ("", "."):
        return root
    if rel.startswith("../") or rel == ".." or os.path.isabs(rel):
        return ""
    full = os.path.abspath(os.path.join(root, rel.replace("/", os.sep)))
    ra = os.path.abspath(root)
    if full != ra and not full.startswith(ra + os.sep):
        return ""
    return full


def load_resources():
    path = os.path.join(DATA, "ToolsGCP-Resources.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("resources", [])
    except Exception:
        return []


RESOURCES = load_resources()
LATEST = [r.get("code") for r in RESOURCES[:10] if r.get("code")]


# mock 版 i18n —— 直接读真实语言包，让预览能验证三语文案（以前 mock 没有
# i18n.bundle，界面全靠代码里的中文 fallback，测不出语言包缺词/错词）。
LANG_DIRS = {
    "简体中文": "zh_CN", "繁體中文": "zh_TW", "English": "en_US",
    "zh_CN": "zh_CN", "zh_TW": "zh_TW", "en_US": "en_US",
}


def mock_i18n_bundle(language):
    lang = str(language or "").strip() or "简体中文"
    folder = LANG_DIRS.get(lang, "zh_CN")
    base = os.path.join(DATA, "modules", "languages", folder)
    modules = {}
    try:
        for name in sorted(os.listdir(base)):
            if not name.endswith(".json"):
                continue
            module = name[:-5]
            if module.endswith("_language"):
                module = module[: -len("_language")]
            try:
                with open(os.path.join(base, name), "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                continue
            if isinstance(data, dict):
                modules[module] = data
    except Exception:
        pass
    return {"ok": True, "language": lang, "modules": modules}


MOCK_API = """
window.__MOCK_RESOURCES__ = %s;
window.pywebview = { api: {
  resources: {
    all: async function () { return { ok: true, items: window.__MOCK_RESOURCES__ }; },
    status: async function () { return { ok: true, source: 'mock-resources.json' }; },
    refresh_latest: async function () { return { ok: true, codes: %s }; },
    detail: async function (code) {
      var hit = (window.__MOCK_RESOURCES__ || []).filter(function (r) { return r.code === code; })[0];
      return { ok: !!hit, item: hit || null };
    },
    /* R19：云端资源库状态（默认成功；用 ?js0=window.__MOCK_CLOUD_STATUS__={...} 造错误态，
       用 ?js0=delete window.pywebview.api.resources.cloud_status 验证"接口不存在 → 整行不渲染"） */
    cloud_status: async function () {
      if (window.__MOCK_CLOUD_STATUS__) return window.__MOCK_CLOUD_STATUS__;
      return { ok: true, configured: true, available: true, version: '1.2.3', tag: 'v1.2.3',
        updated_at: '2026-10-28T21:30:00', count: 52, error: '', error_key: '',
        path: 'C:/mock/.ToolsGCP/cloud/ToolsGCP-Resources.json', repo: 'Galen563/ToolsGCP' };
    },
    cloud_refresh: async function (force) {
      /* 记录调用次数/参数，CDP 侧据此验证"切到云端会触发一次、不阻塞 UI" */
      window.__MOCK_CLOUD_REFRESH_CALLS__ = (window.__MOCK_CLOUD_REFRESH_CALLS__ || 0) + 1;
      window.__MOCK_CLOUD_REFRESH_ARGS__ = { force: !!force };
      /* ?js0=window.__MOCK_CLOUD_REFRESH_DELAY__=2000 → 模拟慢网络，验证界面不被 await 卡住 */
      if (window.__MOCK_CLOUD_REFRESH_DELAY__) {
        await new Promise(function (res) { setTimeout(res, window.__MOCK_CLOUD_REFRESH_DELAY__); });
      }
      if (window.__MOCK_CLOUD_REFRESH_RESULT__) return window.__MOCK_CLOUD_REFRESH_RESULT__;
      return { ok: true, updated: false, version: '1.2.3', count: 52,
        path: 'C:/mock/.ToolsGCP/cloud/ToolsGCP-Resources.json', error: '', error_key: '' };
    },
  },
  settings: {
    get: async function () { return { ok: true, settings: window.__MOCK_SETTINGS__ || {} }; },
    api_key_state: async function () { return { ok: true, configured: false }; },
    set: async function () { return { ok: true }; },
    paths: async function () { return { ok: true, config: 'C:/mock/.ToolsGCP', data: 'C:/mock' }; },
  },
  /* R19：mock 版 i18n —— 由 /mock/i18n 读真实语言包，预览/QA 能验证三语文案 */
  i18n: {
    bundle: async function (language) {
      var lang = String(language || (window.__MOCK_SETTINGS__ && window.__MOCK_SETTINGS__.language) || '简体中文');
      try {
        var r = await fetch('/mock/i18n?lang=' + encodeURIComponent(lang));
        if (!r.ok) return { ok: false, error: 'mock i18n HTTP ' + r.status };
        return await r.json();
      } catch (e) { return { ok: false, error: String(e) }; }
    },
  },
  favorites: (function () {
    /* R19：收藏接口的最小内存实现 —— 让收藏页的导入 / 导出 / 星标能真正点通
       （以前这里只有 list 返回空数组，UI 只能看不能测）。
       ⚠️ 仅开发测试用；真实实现在 .ToolsGCP/desktop/api/resources.py。 */
    var DEFAULT_LABEL = '默认收藏夹';
    var state = [
      { name: 'Default', label: DEFAULT_LABEL, items: [] },
      { name: '常用工具', label: '常用工具', items: ['TG-000001', 'TG-000002', 'TG-000003'] }
    ];
    window.__MOCK_FAV_STATE__ = state;
    function folder(name) {
      for (var i = 0; i < state.length; i++) { if (state[i].name === name) return state[i]; }
      return null;
    }
    function folderOf(code) {
      for (var i = 0; i < state.length; i++) {
        if (state[i].items.indexOf(code) >= 0) return state[i].name;
      }
      return '';
    }
    function drop(code) {
      state.forEach(function (f) {
        f.items = f.items.filter(function (c) { return c !== code; });
      });
    }
    return {
      list: async function () {
        return { ok: true, folders: state.map(function (f) {
            return { name: f.name, label: f.label, count: f.items.length,
                     items: f.items.slice(), is_default: f.name === 'Default' };
          }),
          total: state.reduce(function (n, f) { return n + f.items.length; }, 0),
          default: 'Default', default_label: DEFAULT_LABEL };
      },
      toggle: async function (code, folderName) {
        var current = folderOf(code);
        if (current) { drop(code); return { ok: true, code: code, favorite: false, folder: '' }; }
        var target = folder(folderName || 'Default') || state[0];
        target.items.push(code);
        return { ok: true, code: code, favorite: true, folder: target.name };
      },
      add: async function (code, folderName) {
        var current = folderOf(code);
        if (current) return { ok: true, code: code, added: false, folder: current };
        var target = folder(folderName || 'Default') || state[0];
        target.items.push(code);
        return { ok: true, code: code, added: true, folder: target.name };
      },
      remove: async function (code) {
        drop(code);
        return { ok: true, code: code, removed: true };
      },
      move_many: async function (codes, from, to) {
        var src = folder(from), dst = folder(to), moved = 0;
        (codes || []).forEach(function (code) {
          if (src && dst && src.items.indexOf(code) >= 0) {
            src.items = src.items.filter(function (c) { return c !== code; });
            dst.items.push(code);
            moved += 1;
          }
        });
        return { ok: true, moved: moved, total: (codes || []).length, folder: to };
      },
      create_folder: async function (name) {
        var text = String(name || '').trim();
        if (!text) return { ok: true, created: false, name: '', message: '请输入收藏夹名称' };
        if (folder(text)) return { ok: true, created: false, name: '',
          message: '已经有一个叫「' + text + '」的收藏夹了' };
        state.push({ name: text, label: text, items: [] });
        return { ok: true, created: true, name: text, message: '' };
      },
      rename_folder: async function (old, name) {
        var hit = folder(old), text = String(name || '').trim();
        if (!hit) return { ok: true, renamed: false, name: '', message: '收藏夹不存在' };
        hit.name = text; hit.label = text;
        return { ok: true, renamed: true, name: text, message: '' };
      },
      delete_folder: async function (name) {
        state = state.filter(function (f) { return f.name !== name; });
        return { ok: true, deleted: true, name: name, message: '' };
      }
    };
  })(),
  shell: {
    save_text_file: async function (name, content) {
      /* 让"导出收藏/导出清单"在无头浏览器里也能验证：把内容留在 window 上供 CDP 读取 */
      window.__MOCK_SAVED_FILE__ = { name: name, content: content };
      return { ok: true, canceled: false, path: 'C:/mock/' + name };
    },
  },
  app: {
    info: async function () { return { ok: true, app: 'ToolsGCP', version: '1.1.4',
      configDir: 'C:/mock/.ToolsGCP', args: [] }; },
    privacy_state: async function () { return { ok: true, agreed: true }; },
    ready: async function () { return { ok: true }; },
  },
  window: {
    state: async function () { return { ok: true, maximized: false, fullscreen: false }; },
    center: async function () { return { ok: true }; },
  },
  plugins: { list: async function () { return { ok: true, plugins: window.__MOCK_PLUGINS__ || [] }; } },
  /* R20：downloads 的 mock —— 预览/QA 里能看 Releases 弹窗与下载页
     （真实实现在 desktop/api/downloader.py；这里只给内存假数据，绝不假装写盘）。 */
  downloader: (function () {
    var state = { items: [] };
    window.__MOCK_DOWNLOADS__ = state;
    function fakeReleases(repo) {
      var names = ['ToolsGCP-windows-x64.exe', 'ToolsGCP-windows-arm64.zip',
                   'ToolsGCP-linux-amd64.AppImage', 'ToolsGCP-macos-arm64.dmg',
                   'SHA256SUMS.txt', 'Source code.zip'];
      return {
        ok: true, repo: repo || 'Galen563/ToolsGCP', page: 1, per_page: 30,
        releases: [
          { tag: 'v1.1.0', name: 'v1.1.0', prerelease: false, draft: false,
            published_at: '2026-10-20T12:00:00Z', body: '正式版',
            assets: names.slice(0, 4).map(function (n, i) {
              return { name: n, size: 24000000 - i * 3000000,
                download_url: 'https://example.com/' + n, content_type: 'application/octet-stream' };
            }) },
          { tag: 'v1.2.0-beta.1', name: 'v1.2.0-beta.1', prerelease: true, draft: false,
            published_at: '2026-10-28T09:00:00Z', body: '测试版',
            assets: names.map(function (n) {
              return { name: n, size: 1200000, download_url: 'https://example.com/' + n,
                content_type: 'application/octet-stream' };
            }) },
        ],
      };
    }
    return {
      releases: async function (url, page, perPage) { return fakeReleases(url); },
      resolve_asset: async function (url, platform, arch) {
        return { ok: true, repo: url, platform: platform || 'windows', arch: arch || 'x64',
          asset: { name: 'ToolsGCP-windows-x64.exe', size: 24000000, score: 80,
            download_url: 'https://example.com/ToolsGCP-windows-x64.exe' }, candidates: [] };
      },
      start: async function (url, filename, dir, size, source) {
        var id = 'dl' + (state.items.length + 1);
        var item = { id: id, url: url, name: filename || ('file' + state.items.length),
          status: 'downloading', received: 0, total: Number(size) || 1000000,
          percent: 0, speed: 0, eta: null, path: (dir || 'C:/mock/Downloads') + '/' + (filename || 'file'),
          dir: dir || 'C:/mock/Downloads', error: '', source: source || '' };
        state.items.push(item);
        var timer = setInterval(function () {
          if (item.status !== 'downloading') { clearInterval(timer); return; }
          item.received += Math.round(item.total / 8);
          item.percent = Math.min(100, Math.round(item.received / item.total * 100));
          item.speed = 640000;
          item.eta = 8;
          if (item.percent >= 100) { item.status = 'done'; item.percent = 100; item.speed = 0; item.eta = null; }
          try {
            window.ToolsGCP && window.ToolsGCP.emit && window.ToolsGCP.emit('download.progress', item);
          } catch (e) {}
        }, 400);
        return { ok: true, started: true, id: id, name: item.name, path: item.path, dir: item.dir,
          total: item.total, url: url };
      },
      cancel: async function (id) {
        state.items.forEach(function (it) { if (it.id === id) { it.status = 'canceled'; } });
        return { ok: true, canceled: true };
      },
      list: async function () {
        return { ok: true, items: state.items.slice(), dir: 'C:/mock/Downloads',
          active: state.items.filter(function (i) { return i.status === 'downloading'; }).length,
          finished: state.items.length };
      },
      retry: async function (id) {
        state.items.forEach(function (it) { if (it.id === id) { it.status = 'downloading'; it.percent = 0; } });
        return { ok: true, started: true };
      },
      open_file: async function () { return { ok: true }; },
      open_folder: async function () { return { ok: true }; },
      clear_finished: async function () {
        state.items = state.items.filter(function (it) { return it.status === 'downloading'; });
        return { ok: true, removed: 1 };
      },
    };
  })(),

  /* R19（maker-ui）：提交软件「产出」的真实接口 —— mock 版只把结果记在内存里，
     用来在纯浏览器预览下验证 UI 流程（真写盘只有桌面端 maker.py 做）。
     ⚠️ 缺任意一个，前端都会走 needApi 的明确降级（绝不假装成功）。 */
  maker: {
    info: async function () {
      var list = window.__MOCK_RESOURCES__ || [];
      return { ok: true, path: 'C:/mock/.ToolsGCP/ToolsGCP-Resources.json', count: list.length };
    },
    append_entry: async function (entry, options) {
      var list = window.__MOCK_RESOURCES__ || [];
      var key = (entry && (entry.id || entry.code)) || '';
      var hit = -1;
      for (var i = 0; i < list.length; i += 1) {
        if (((list[i] || {}).id || (list[i] || {}).code) === key) { hit = i; break; }
      }
      var action = hit >= 0 ? 'update' : 'add';
      if (hit >= 0) list[hit] = entry; else list.push(entry);
      window.__MOCK_RESOURCES__ = list;
      return { ok: true, action: action, id: key, total: list.length,
               code: (entry || {}).code || '', name: (entry || {}).name || '',
               path: 'C:/mock/.ToolsGCP/ToolsGCP-Resources.json', entry: entry };
    },
    save_icon: async function (name, data) {
      window.__MOCK_ICONS__ = window.__MOCK_ICONS__ || {};
      var text = String(data || '');
      window.__MOCK_ICONS__[name] = text.length;
      return { ok: true, name: name, path: 'C:/mock/.ToolsGCP/images/icon/' + name,
               bytes: text.length, url: '/res/image/icon/' + encodeURIComponent(name) };
    },
    save_standalone: async function (entry, options) {
      window.__MOCK_STANDALONE__ = { entry: entry, options: options || {} };
      return { ok: true, canceled: false, saved: true,
               path: 'C:/mock/out/ToolsGCP-Resources.json', name: 'ToolsGCP-Resources.json',
               count: 1, icon: (entry || {}).icon || '' };
    },
  },
  announcements: { list: async function () { return { ok: true, notices: window.__MOCK_NOTICES__ || [],
      unread: 0 }; } },
  log: { client: async function () { return { ok: true }; } },
} };
""" % (json.dumps(RESOURCES, ensure_ascii=False), json.dumps(LATEST))


# ============================================================================
# 无头冻结（?fx=）—— 固化自检台最大的一个坑
# ⚠️ 坑：无头 Edge + --virtual-time-budget 下，CSS transition / animation 的时钟
#    **不推进**（渲染帧被虚拟时间策略跳过），于是测量拿到的是起始帧而不是稳定态。
#    已实测到的假数字（2026-10）：
#      · .more-pop 停在 popIn 的 scale(.96) → 子元素量到 14.4px（真值 15px）
#      · 侧栏展开后 .nav 仍量到 48px（真值 240px）
#      · .combo-pop 的 popTopGap 量到 -3（稳定态应为 4，看着像"弹层翻转/压住触发框"的假 bug）
#    所以**量之前必须把动画推到终点**。三种模式：
#      ?fx=off    （硬冻结）注入 *{transition:none!important;animation:none!important}
#                 再把已在跑的动画 finish()，布局/尺寸/坐标直接落在终态 —— 量数字用这个。
#      ?fx=finish （软冻结）只 document.getAnimations().forEach(a=>a.finish())，不动样式表；
#                 并在 0/300/700/1200/1800/2400ms 反复补刀（切页等新动画会不断产生）。
#      ?fx=keep   （不冻结）什么都不做 —— 用来读"过渡声明本身"（例如验证 .seg-thumb 的
#                 transitionProperty 是否含 left/width、时长是否 220ms），不要用它量坐标。
#    ?audit=1 默认按 fx=off 跑（审计数字必须是稳定态）；需要保留过渡请显式 ?fx=keep。
#    副作用已实测：fx=off 下 Vue <transition> 仍正常收尾（见 regression_report.md
#    冻结副作用一节：mustaches=0、.page 非空、无 enter-from 残留、无卡在 opacity:0）。
# ============================================================================
FX_FINISH_JS = (
    "(function(){try{document.getAnimations().forEach(function(a){try{a.finish();}catch(e){}});}"
    "catch(e){}})();"
)
FX_OFF_JS = (
    "(function(){try{var s=document.createElement('style');s.id='__fx_off__';"
    "s.textContent='*{transition:none !important;animation:none !important}';"
    "document.head.appendChild(s);}catch(e){}"
    "try{document.getAnimations().forEach(function(a){try{a.finish();}catch(e){}});}catch(e){}})();"
)


AUDIT_JS = r"""
(function () {
  /* 见本文件顶部 fx 说明：审计数字必须是稳定态，先把在跑的动画推到终点 */
  try { document.getAnimations().forEach(function (a) { try { a.finish(); } catch (e) {} }); } catch (e) {}
  function rect(el) {
    var r = el.getBoundingClientRect();
    return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) };
  }
  function cs(el, props) {
    var c = getComputedStyle(el), o = {};
    props.forEach(function (p) { o[p] = c[p]; });
    return o;
  }
  function describe(sel, sample, props) {
    var els = Array.prototype.slice.call(document.querySelectorAll(sel)).slice(0, sample || 4);
    return els.map(function (el) {
      var r = el.getBoundingClientRect();
      var out = { sel: sel, cls: el.className && String(el.className).slice(0, 90),
                  rect: { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) },
                  scrollW: el.scrollWidth, clientW: el.clientWidth,
                  scrollH: el.scrollHeight, clientH: el.clientHeight, text: (el.textContent || '').trim().slice(0, 40) };
      if (props) out.cs = cs(el, props);
      return out;
    });
  }
  function childrenReport(sel) {
    var host = document.querySelector(sel);
    if (!host) return null;
    var out = { host: describe(sel, 1, ['display', 'alignItems', 'gap', 'padding', 'justifyContent'])[0], children: [] };
    Array.prototype.forEach.call(host.children, function (ch) {
      var r = ch.getBoundingClientRect();
      out.children.push({ tag: ch.tagName.toLowerCase(), cls: String(ch.className).slice(0, 60),
        rect: { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) },
        text: (ch.textContent || '').trim().slice(0, 30) });
    });
    return out;
  }
  function collapsed() {
    var hits = [];
    Array.prototype.forEach.call(document.querySelectorAll('.page *'), function (el) {
      var c = getComputedStyle(el);
      if (c.display === 'none' || c.visibility === 'hidden' || c.position === 'fixed') return;
      var r = el.getBoundingClientRect();
      if (r.width < 1 && r.height < 1 && el.children.length === 0 && el.textContent.trim()) {
        hits.push({ cls: String(el.className).slice(0, 60), tag: el.tagName.toLowerCase(), text: el.textContent.trim().slice(0, 30) });
      }
    });
    return hits.slice(0, 20);
  }
  function clipped() {
    var hits = [];
    Array.prototype.forEach.call(document.querySelectorAll('.page *'), function (el) {
      var c = getComputedStyle(el);
      if (c.overflowX === 'visible' && c.overflowY === 'visible') return;
      var dx = el.scrollWidth - el.clientWidth, dy = el.scrollHeight - el.clientHeight;
      var hiddenX = c.overflowX === 'hidden' || c.overflowX === 'clip';
      var hiddenY = c.overflowY === 'hidden' || c.overflowY === 'clip';
      if ((hiddenX && dx > 2) || (hiddenY && dy > 2)) {
        hits.push({ cls: String(el.className).slice(0, 60), tag: el.tagName.toLowerCase(),
          dx: dx, dy: dy, rect: { w: Math.round(el.getBoundingClientRect().width), h: Math.round(el.getBoundingClientRect().height) } });
      }
    });
    return hits.slice(0, 40);
  }
  function comboReport() {
    var out = [];
    Array.prototype.forEach.call(document.querySelectorAll('.combo'), function (c, i) {
      var t = c.querySelector('.combo-trigger'), a = c.querySelector('.combo-arrow'), l = c.querySelector('.combo-label');
      if (!t) return;
      var tr = t.getBoundingClientRect();
      out.push({ i: i, trigger: { x: Math.round(tr.left), y: Math.round(tr.top), w: Math.round(tr.width), h: Math.round(tr.height) },
        triggerPadding: getComputedStyle(t).padding,
        label: l ? (function () { var r = l.getBoundingClientRect(); return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) }; })() : null,
        arrow: a ? (function () { var r = a.getBoundingClientRect(); return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height),
          rightGap: Math.round(tr.right - r.right), centerOffsetY: Math.round((r.top + r.height / 2) - (tr.top + tr.height / 2)) }; })() : null,
        labelText: (c.textContent || '').trim().slice(0, 30) });
    });
    return out;
  }
  function overlaps() {
    var hits = [];
    var sel = '.toolbar-row, .plugin-head-text, .ai-head, .ai-input-row, .row, .filter-row, .card-head, .setting-row';
    Array.prototype.forEach.call(document.querySelectorAll(sel), function (host) {
      var kids = Array.prototype.filter.call(host.children, function (k) { return getComputedStyle(k).display !== 'none'; });
      for (var i = 0; i < kids.length; i++) {
        for (var j = i + 1; j < kids.length; j++) {
          var a = kids[i].getBoundingClientRect(), b = kids[j].getBoundingClientRect();
          if (a.width === 0 || b.width === 0) continue;
          var ox = Math.min(a.right, b.right) - Math.max(a.left, b.left);
          var oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
          if (ox > 2 && oy > 2) {
            var s = getComputedStyle(host);
            if (s.position === 'relative' || s.position === 'absolute') continue;
            hits.push({ host: String(host.className).slice(0, 50), a: String(kids[i].className).slice(0, 40),
              b: String(kids[j].className).slice(0, 40), ox: Math.round(ox), oy: Math.round(oy) });
          }
        }
      }
    });
    return hits.slice(0, 30);
  }
  var report = {
    url: location.href, page: (location.search.match(/page=([^&]*)/) || [])[1] || '',
    view: { w: innerWidth, h: innerHeight },
    sanity: { vueLoaded: (typeof Vue !== 'undefined'), pageCount: document.querySelectorAll('.page').length,
              appRoot: !!document.querySelector('.app-root'),
              titlebarText: (document.querySelector('.titlebar') || {}).textContent || '',
              mustaches: (document.body.innerHTML.match(/\{\{/g) || []).length },
    combos: comboReport(),
    clipped: clipped(),
    collapsed: collapsed(),
    overlaps: overlaps(),
    body: describe('body', 1),
    page_: describe('.page', 1),
    toolbar: describe('.toolbar-row', 1, ['display', 'alignItems', 'gap', 'height']),
    toolbarChildren: childrenReport('.toolbar-row'),
    searchBox: describe('.search-box', 1),
    filterBtn: describe('.filter-btn', 1),
    cards: describe('.card', 2),
    settings: { side: describe('.settings-side', 1), main: describe('.settings-main', 1),
                row: describe('.setting-row', 3), control: describe('.setting-control', 3) },
    switches: describe('.switch', 3, ['position', 'width', 'height', 'borderRadius']),
    switchKnobs: describe('.switch .switch-knob', 3),
    segmented: describe('.segmented', 2),
    chips: describe('.chip', 3),
    nav: describe('.nav', 1), navItems: describe('.nav-item', 3),
    layers: (function () {
      function z(sel) { var e = document.querySelector(sel); return e ? getComputedStyle(e).zIndex : null; }
      var nav = document.querySelector('.nav');
      var cont = document.querySelector('.content');
      var hit = null;
      if (nav && nav.getBoundingClientRect().width > 60) {
        var r = nav.getBoundingClientRect();
        var el = document.elementFromPoint(Math.round(r.left + r.width - 6), Math.round(r.top + 200));
        hit = el ? (el.closest('.nav') ? 'nav' : (el.className || el.tagName)) : null;
      }
      return { titlebar: z('.titlebar'), content: z('.content'),
               nav: z('.nav'), morePop: z('.more-pop'), backdrop: z('.pop-backdrop'),
               navExpanded: !!(nav && nav.classList.contains('is-expanded')),
               navWidth: nav ? Math.round(nav.getBoundingClientRect().width) : null,
               pointHitsNav: hit };
    })(),
    titlebar: describe('.titlebar', 1), tbBtns: describe('.tb-btn', 6),
    aiDrawer: describe('.ai-drawer', 1), floatBall: describe('.float-ball', 1),
    triLang: describe('.tri-lang', 1), langCol: describe('.lang-col', 1),
    formThree: describe('.form-grid.three', 1),
    carousel: (function () {
      var c = document.querySelector('.carousel');
      if (!c) return null;
      var r = c.getBoundingClientRect();
      var imgs = Array.prototype.slice.call(document.querySelectorAll('.slide img')).map(function (im) {
        var ir = im.getBoundingClientRect();
        return { src: (im.getAttribute('src') || '').split('/').pop(), nw: im.naturalWidth, nh: im.naturalHeight,
                 w: Math.round(ir.width), h: Math.round(ir.height),
                 fit: getComputedStyle(im).objectFit, loaded: im.complete && im.naturalWidth > 0 };
      });
      return { rect: { w: Math.round(r.width), h: Math.round(r.height) },
               inlineHeight: c.style.height || '', scrollH: c.scrollHeight,
               slideCount: document.querySelectorAll('.slide').length,
               pips: document.querySelectorAll('.pip').length, imgs: imgs };
    })(),
  };
  function send() {
    try {
      /* 落盘文件名：?auditfile=<name> 可覆盖（缺省 = ?page 的值，行为与老版本完全一致） */
      var file = (typeof window.__AUDIT_FILE__ === 'string' && window.__AUDIT_FILE__) || report.page;
      report.auditFile = file;
      fetch('/audit?page=' + encodeURIComponent(file), { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(report) });
    } catch (e) { /* ignore */ }
  }
  /* ---- 功能自检：真正点开第一个下拉框 → 点第 2 项 → 验证标签变化 + 弹层关闭 ---- */
  var trig = document.querySelector('.combo-trigger');
  if (!trig) { send(); return; }
  var before = trig.querySelector('.combo-label').textContent;
  trig.click();
  setTimeout(function () {
    var pop = document.querySelector('.combo-pop');
    var test = { opened: !!pop, before: before,
      itemCount: pop ? pop.querySelectorAll('.combo-item').length : 0 };
    if (pop) {
      var pr = pop.getBoundingClientRect();
      test.popTopGap = Math.round(pr.top - trig.getBoundingClientRect().bottom);
      test.popTransform = getComputedStyle(pop).transform;
      test.popMaxH = getComputedStyle(pop).maxHeight;
    }
    if (!pop || !pop.querySelectorAll('.combo-item').length) { report.comboTest = test; send(); return; }
    var items = pop.querySelectorAll('.combo-item');
    var want = items[1].textContent.trim();
    test.want = want;
    items[1].click();
    setTimeout(function () {
      test.after = trig.querySelector('.combo-label').textContent;
      test.picked = test.after === want;
      test.closedAfterPick = !document.querySelector('.combo-pop');
      test.arrowRightGap = (function () {
        var a = trig.querySelector('.combo-arrow');
        if (!a) return null;
        return Math.round(trig.getBoundingClientRect().right - a.getBoundingClientRect().right);
      })();
      report.comboTest = test;
      send();
    }, 250);
  }, 250);
})();
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "ToolsGCPDevTest"

    def log_message(self, *args):
        pass

    def _send(self, full, ctype=None):
        if not full or not os.path.isfile(full):
            self.send_error(404, "not found")
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = ctype or EXTRA_TYPES.get(ext) or mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        url = urlparse(self.path)
        if url.path != "/audit":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        page = (parse_qs(url.query).get("page") or ["index"])[0] or "index"
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit_%s.json" % page)
        try:
            data = json.loads(body.decode("utf-8"))
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
        except Exception:
            with open(out, "wb") as fh:
                fh.write(body)
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        qs = parse_qs(url.query)

        if path == "/":
            with open(os.path.join(WEBUI, "index.html"), "r", encoding="utf-8") as fh:
                html = fh.read()
            page = (qs.get("page") or [""])[0]
            theme = (qs.get("theme") or ["dark"])[0]
            accent = (qs.get("accent") or ["blue"])[0]
            settings = {
                "theme": "深色主题" if theme == "dark" else "浅色主题",
                "accent_color": accent,
                "ai_enabled": True,
                "ai_sidebar_mode": False,
                "default_page": {"home": "首页", "search": "搜索", "settings": "设置",
                                 "favorites": "收藏", "deploy": "部署", "plugins": "插件",
                                 "maker": "提交软件", "log": "查看日志", "notice": "公告",
                                 "feedback": "反馈", "github": "Github",
                                 "customize": "定制页"}.get(page, "搜索"),
            }
            mock = MOCK_API + "\nwindow.__MOCK_SETTINGS__ = %s;\n" % json.dumps(settings, ensure_ascii=False)
            # 报告/错误上报的落盘文件名：?auditfile=<name> 缺省 = ?page 的值。
            # 老用法（只看 ?page）行为完全不变：audit_<page>.json / audit_<page>_err.json。
            audit_file = (qs.get("auditfile") or [page or "x"])[0] or "x"
            mock += "\nwindow.__AUDIT_FILE__ = %s;\n" % json.dumps(audit_file, ensure_ascii=False)
            # 冻结（?fx=off|finish）必须尽早注入：样式表要在 Vue 首次渲染前就位
            fx = (qs.get("fx") or [""])[0]
            if not fx and (qs.get("audit") or [""])[0]:
                fx = "off"
            if fx == "off":
                mock += "\n/* fx=off：硬冻结（见 serve.py 顶部注释） */\n" + FX_OFF_JS + "\n"
            elif fx == "finish":
                mock += ("\n/* fx=finish：软冻结，反复把动画推到终点 */\n"
                         "(function(){var f=function(){%s};"
                         "[0,300,700,1200,1800,2400].forEach(function(t){setTimeout(f,t);});})();\n"
                         % FX_FINISH_JS)
            # ?js0=<code>：立即执行（早于 icons.js / app.js），用来给 app 装测试夹具；
            # 注意是"裸执行"，里面的引号/换行请自己保证合法（与 ?js= 一样不做转义）。
            mock += ("\nwindow.__MOCK_PLUGINS__ = ["
                     "{id:'demo1',name:'演示插件 A',version:'1.0.0',author:'Galen563',description:'用于自检排版与开关位置。',enabled:true,status:'ok',hasConfig:true,note:'',icon:''},"
                     "{id:'demo2',name:'演示插件 B',version:'0.9.2',author:'Cyric373',description:'第二个插件，列表视图下检查对齐。',enabled:false,status:'ok',hasConfig:false,note:'备注',icon:''}"
                     "];\n")
            mock += ("\nwindow.__MOCK_NOTICES__ = ["
                     "{id:'n1',title:'欢迎使用 ToolsGCP',body:'这是一条用于自检公告页排版的示例公告。',date:'2026-01-01',author:'Galen563',number:1},"
                     "{id:'n2',title:'v1.1.4 更新说明',body:'修复了下拉框无法切换的问题。',date:'2026-01-02',author:'Galen563',number:2}"
                     "];\n")
            # 页面级错误上报：某些页面渲染/脚本报错时也能在 audit_<auditfile>_err.json 里看到
            mock += ("\n(function(){function rp(kind,msg,stack){try{fetch('/audit?page='+"
                     "encodeURIComponent((window.__AUDIT_FILE__||'x')+'_err'),"
                     "{method:'POST',headers:{'Content-Type':'application/json'},"
                     "body:JSON.stringify({kind:kind,msg:String(msg),stack:String(stack||'').slice(0,800)})});}catch(e){}}"
                     "window.addEventListener('error',function(e){rp('error',e.message,e.error&&e.error.stack);});"
                     "window.addEventListener('unhandledrejection',function(e){rp('reject',e.reason&&e.reason.message,e.reason&&e.reason.stack);});"
                     "})();\n")
            # ?js0=<code>：立即执行（早于 icons.js / app.js），用来给 app 装测试夹具；
            # 注意是"裸执行"，里面的引号/换行请自己保证合法（与 ?js= 一样不做转义）。
            inject_js0 = (qs.get("js0") or [""])[0]
            if inject_js0:
                mock += "\n/* js0：早注入（早于 app.js），装夹具用 */\ntry { %s } catch (e) { console.error(e); }\n" % inject_js0
            inject_js = (qs.get("js") or [""])[0]
            if inject_js:
                mock += "\nsetTimeout(function(){ try { %s } catch (e) { console.error(e); } }, 600);\n" % inject_js
            if (qs.get("audit") or [""])[0]:
                mock += "\nsetTimeout(function(){ %s }, 2500);\n" % AUDIT_JS
            which = (qs.get("open") or [""])[0]
            if which == "ai":
                mock += ("\nsetTimeout(function(){var b=document.querySelector('.float-ball');"
                         "if(b)b.click();},900);\n")
            elif which == "nav":
                mock += ("\nsetTimeout(function(){var b=document.querySelector('.nav-burger');"
                         "if(b)b.click();},900);\n")
            elif which == "ai_drawer":
                mock += ("\nsetTimeout(function(){var b=document.querySelector('.float-ball');"
                         "if(b)b.click();},900);"
                         "setTimeout(function(){var h=document.querySelector('.ai-head .icon-btn');"
                         "var bs=document.querySelectorAll('.ai-head .icon-btn');"
                         "if(bs&&bs[1])bs[1].click();},1500);\n")
            # 强制首帧主题
            mock += ("\ntry { document.documentElement.setAttribute('data-theme', %r);"
                     " document.documentElement.setAttribute('data-accent', %r);"
                     " localStorage.setItem('toolsgcp.theme', %r);"
                     " localStorage.setItem('toolsgcp.accent', %r); } catch (e) {}\n"
                     % (theme, accent, theme, accent))
            html = html.replace('<script src="/static/js/icons.js"></script>',
                                '<script>%s</script>\n<script src="/static/js/icons.js"></script>' % mock)
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/mock/i18n":
            lang = (qs.get("lang") or [""])[0]
            body = json.dumps(mock_i18n_bundle(lang), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if path.startswith("/static/"):
            self._send(safe_join(WEBUI, path[len("/static/"):]))
            return
        # ⚠️ 必须和 desktop/webhost.py 的路由一致（图标目录已重构到 images/icon）：
        #    /res/icon/<rel>  -> .ToolsGCP/images/icon/<rel>   （兼容别名）
        #    /res/image/<rel> -> .ToolsGCP/images/<rel>        （规范：/res/image/icon/<name>）
        #    /res/<rel>       -> .ToolsGCP/<rel>
        if path.startswith("/res/icon/"):
            self._send(safe_join(os.path.join(DATA, "images", "icon"), path[len("/res/icon/"):]))
            return
        if path.startswith("/res/image/"):
            self._send(safe_join(os.path.join(DATA, "images"), path[len("/res/image/"):]))
            return
        if path.startswith("/res/"):
            self._send(safe_join(DATA, path[len("/res/"):]))
            return
        self.send_error(404)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8791
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("serving on http://127.0.0.1:%d/  (resources=%d)" % (port, len(RESOURCES)))
    srv.serve_forever()