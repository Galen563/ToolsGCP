/* 浏览器模式桥接的**竞态**回归（Node 直接跑，无依赖）。
 *
 * 为什么要有这个文件：用户报「浏览器模式下功能和配置文件之类的全部不生效，
 * 图片 资源 配置全部加载不上来」。根因不在后端路由（静态/资源实测全 200），
 * 而在前端：`bridge.init()` 与「浏览器模式探测」是两条**互不相干**的异步链，
 * init 先以 api=null 落定并把 null **缓存**进 _initPromise，
 * 探测随后才把传输换成 HTTP —— 所有调用方拿到的还是那份已 resolve 的 null，
 * 于是 has() 恒 false、每个 tryCall 都走 needApi 降级 = 全线失效。
 *
 * 这个测试把 app.js 里 bridge / httpBridge / installHttpBridge 那一段**原样抽出来**
 * 在 Node 里跑，用假的 fetch 模拟「capabilities 比 pywebview 晚到」和反过来两种时序，
 * 断言两种时序下都必须能用 HTTP 调到后端方法。
 *
 * 跑法： node "项目资料-文档与开发测试/_devtest/test_bridge_race.js"
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..', '..');
const APP_JS = path.join(ROOT, '.ToolsGCP', 'webui', 'js', 'app.js');

let fails = 0;
function check(label, cond, extra) {
  if (cond) console.log('  OK   ' + label);
  else { console.log('  FAIL ' + label + (extra ? '  ' + extra : '')); fails += 1; }
}

/* 从 app.js 里截出要测的那一段（不复制源码，避免和真文件脱钩）*/
function extract() {
  const src = fs.readFileSync(APP_JS, 'utf8');
  const start = src.indexOf('/* ===================== 桥（pywebview js_api） =====================');
  const end = src.indexOf('/* ===================== 后端 → 前端事件');
  if (start < 0 || end < 0) throw new Error('app.js 里找不到桥接那一段（结构变了，先更新本测试）');
  const t = src.slice(start, end);
  // 这段里用到的外部依赖：t()（i18n）
  // ⚠️ 末尾那两个赋值不能省：vm 里顶层 `const` 是**词法绑定**，不会变成全局属性，
  //    测试要从 sandbox 上取 bridge / httpBridge 就必须自己挂一次。
  return 'function t(k, f) { return f === undefined ? k : f; }\n' + t
    + '\nglobalThis.bridge = bridge; globalThis.httpBridge = httpBridge;\n';
}

/* 跑一次"浏览器模式"启动，返回 bridge 对象
   opts.capsDelayMs  ：capabilities 响应延迟（模拟比 pywebview 注入慢/快）
   opts.pywebviewReadyMs: 多久后出现 window.pywebview（Infinity = 永远不出现 = 真浏览器）
   opts.emptyCaps     ：capabilities 先返回**空清单**（后端 api 还没建好那条路） */
function runScenario(opts) {
  const listeners = {};
  const state = { calls: [], pollStarts: 0, browserMark: false };
  const sandbox = {
    console,
    setTimeout, clearTimeout, Promise, JSON, Set, Math, String, Number, Array, Object, Error,
    AbortSignal: { timeout: () => undefined },
    /* ⚠️⚠️ 必须把 location/fetch/document 同时放在 sandbox 顶层：
       vm 里 `sandbox.window = {...}` 只是**一个属性**，不是全局对象 ——
       被评测的脚本里写的是裸 `location.protocol` / `fetch(...)`（浏览器里它们
       来自 window），在 vm 里要靠 sandbox 顶层的同名属性解析。
       少一份就会抛 ReferenceError，被 installHttpBridge 的 try/catch 吞掉，
       表现是"httpBridge.active 永远 false"—— 测试自己错了，别误判成产品 bug。 */
    location: { protocol: 'http:', pathname: '/' },
    document: {
      documentElement: { classList: { add() { state.browserMark = true; } } },
      getElementById: () => null,
      querySelector: () => null,
      addEventListener() {},
    },
  };
  sandbox.window = {
    addEventListener(name, fn) { (listeners[name] = listeners[name] || []).push(fn); },
    removeEventListener() {},
    fetch: () => {},
    /* ⚠️ 本测试只截了 app.js 的**桥接那一段**，事件总线那一节
       （`window.ToolsGCP = window.ToolsGCP || {}`）不在里面，
       所以这里得先给一个桩，否则探测里 emit 会炸 —— 那是测试的锅，不是产品的。 */
    ToolsGCP: { emit() {} },
  };
  sandbox.fetch = async (url, init) => {
    /* 桌面端模拟：capabilities 这条路由在普通 webhost 上是 **404**
       ⚠️ 必须在脚本执行**之前**就装好这个 fetch —— 探测脚本一加载就发请求，
          跑完之后再覆盖等于覆盖不到（场景③一开始就栽在这儿过）。 */
    if (opts.noBridgeRoute) return { ok: false, status: 404, json: async () => ({}) };
    const method = (init && init.method) || 'GET';
    if (url === '/jsbridge/capabilities') {
      if (opts.capsDelayMs) await new Promise((r) => setTimeout(r, opts.capsDelayMs));
      state.capsHits = (state.capsHits || 0) + 1;
      /* emptyCaps：**只有第一次**返回空清单（模拟"桥已经在跑、但 shell.api 还没挂上"），
         后续返回完整清单 —— 这样才能验证 retryCaps 真的会把清单刷回来。 */
      const empty = opts.emptyCaps && state.capsHits === 1;
      return {
        ok: true, status: 200,
        json: async () => ({
          ok: true, mode: 'browser',
          methods: empty
            ? []
            : ['resources.all', 'settings.get', 'ai.send', 'ping', 'window.state'],
        }),
      };
    }
    if (url === '/jsbridge/events/poll') {
      state.pollStarts += 1;
      /* ⚠️ 必须**模拟长轮询的挂线时间**（后端 EVENT_POLL_WAIT_S = 2.5s）。
         立刻返回会让 startPolling 变成纯微任务忙循环：`await` 从不真正让出，
         setTimeout（capabilities 的延迟、pywebview 注入、retryCaps 的间隔）
         一个都跑不到 → 整个测试挂死。上一版就栽在这里，**这是测试的锅，
         不是产品的**（真浏览器里这条 fetch 本来就挂着 2.5 秒）。 */
      await new Promise((r) => setTimeout(r, opts.pollHoldMs == null ? 300 : opts.pollHoldMs));
      return { ok: true, status: 200, json: async () => ({ ok: true, events: [] }) };
    }
    if (url.startsWith('/jsbridge/call/')) {
      const dotted = url.slice('/jsbridge/call/'.length);
      state.calls.push(dotted);
      if (dotted === 'resources.all') {
        return { ok: true, status: 200, json: async () => ({ ok: true, result: { ok: true, items: [1, 2, 3] } }) };
      }
      return { ok: true, status: 200, json: async () => ({ ok: true, result: { ok: true } }) };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  };
  sandbox.window.fetch = sandbox.fetch;
  sandbox.globalThis = sandbox;

  vm.createContext(sandbox);
  vm.runInContext(extract(), sandbox);

  /* pywebview 何时出现 */
  if (Number.isFinite(opts.pywebviewReadyMs)) {
    setTimeout(() => {
      sandbox.window.pywebview = { api: { resources: { all: async () => ({ ok: true, desktop: true }) } } };
      (listeners.pywebviewready || []).forEach((f) => f());
    }, opts.pywebviewReadyMs);
  }
  return { sandbox, state };
}

async function main() {
  /* 场景①：真浏览器（pywebview 永远不出现）+ capabilities 比第一次调用**慢**
     —— 这就是线上那个竞态的时序 */
  console.log('== 场景①：浏览器里 capabilities 比首次 tryCall 晚到 ==');
  {
    const { sandbox, state } = runScenario({ capsDelayMs: 60, pywebviewReadyMs: Infinity });
    const bridge = sandbox.bridge;
    // 立刻调用（模拟 app.js 启动阶段第一批 tryCall）
    const r = await bridge.tryCall('resources.all');
    check('首次 tryCall 走通了 HTTP 桥（没有降级成 null）', !!r && r.ok === true,
      JSON.stringify(r));
    check('调用确实落到 /jsbridge/call/resources.all',
      state.calls.indexOf('resources.all') >= 0, JSON.stringify(state.calls));
    check('浏览器模式标记打在 <html> 上（顶部栏靠它隐藏）', state.browserMark === true);
    check('httpBridge.active 已置位', sandbox.httpBridge.active === true);
  }

  /* 场景②：capabilities 先到、随后才有调用（顺利时序，别改出回归）*/
  console.log('== 场景②：capabilities 先到（顺利时序）==');
  {
    const { sandbox, state } = runScenario({ capsDelayMs: 0, pywebviewReadyMs: Infinity });
    await new Promise((r) => setTimeout(r, 30));
    const r = await sandbox.bridge.tryCall('resources.all');
    check('顺利时序下也能调到后端', !!r && r.ok === true);
    check('清单里没有的方法仍返回 null（保持降级语义）',
      (await sandbox.bridge.tryCall('nope.whatever')) === null);
  }

  /* 场景③：桌面端 —— 有 pywebview，且 capabilities 这条路由 404
     （桌面端 webhost 没有桥路由，绝不能误接管）*/
  console.log('== 场景③：桌面端不能误启用 HTTP 桥 ==');
  {
    /* noBridgeRoute = capabilities 返回 404（桌面端 webhost 没有桥路由）*/
    const { sandbox, state } = runScenario({
      capsDelayMs: 0, pywebviewReadyMs: 10, noBridgeRoute: true,
    });
    await new Promise((r) => setTimeout(r, 60));
    const r = await sandbox.bridge.tryCall('resources.all');
    check('桌面端走 pywebview（返回 desktop:true）', !!r && r.desktop === true, JSON.stringify(r));
    check('桌面端没有把调用打到 /jsbridge', state.calls.length === 0, JSON.stringify(state.calls));
    check('桌面端不会给 <html> 打 is-browser-mode 标记', state.browserMark === false);
    check('桌面端 httpBridge.active 保持 false', sandbox.httpBridge.active === false);
  }

  /* 场景③b：桌面端 + 桥路由 404，但 pywebview **晚到**（3 秒后才注入）
     —— 以前 init 只等 2 秒就会缓存一份 null；现在先等探测落定（404 → 秒回），
        再去等 pywebview，注入进来就能立刻用上（不靠 2 秒兜底赌运气）。 */
  console.log('== 场景③b：桌面端 pywebview 晚到也不许缓存成 null ==');
  {
    const { sandbox } = runScenario({
      capsDelayMs: 0, pywebviewReadyMs: 120, noBridgeRoute: true,
    });
    /* 探测几乎是立刻 404；此时 pywebview 还没出现 → init 必须继续等而不是立刻定案 */
    const r = await sandbox.bridge.tryCall('resources.all');
    check('pywebview 120ms 后注入 → 这次调用仍成功（init 没有提前缓存 null）',
      !!r && r.desktop === true, JSON.stringify(r));
  }

  /* 场景③c：后端桥在跑但 capabilities 是**空清单**（shell.api 还没建好）
     → 仍然要判定为浏览器模式并接管，之后清单刷回来就能用 */
  console.log('== 场景③c：capabilities 空清单也要接管（不许退回桌面行为）==');
  {
    const { sandbox } = runScenario({ capsDelayMs: 0, pywebviewReadyMs: Infinity, emptyCaps: true });
    await new Promise((r) => setTimeout(r, 2600));   // 等 retryCaps 的 600ms 间隔刷回来
    check('空清单仍然 active', sandbox.httpBridge.active === true);
    check('清单刷回来后 has(resources.all) = true',
      sandbox.bridge.has('resources.all') === true);
  }

  /* 场景④：file:// 打开（预览脚本 / 打包异常）——完全不探测 */
  console.log('== 场景④：file:// 不探测 ==');
  {
    const src = fs.readFileSync(APP_JS, 'utf8');
    check('探测被 isHttp 挡住（file:// 直接 return）',
      /if \(!isHttp\) return;/.test(src));
  }

  /* 场景⑤：根级方法（api.ping 这种一层路径）在浏览器模式也要能用
     —— Proxy 逐段取属性对一层路径返回的是"内层 Proxy"（不是 function），
        老写法 has('ping') 恒 false */
  console.log('== 场景⑤：根级方法在浏览器模式可用 ==');
  {
    const { sandbox } = runScenario({ capsDelayMs: 0, pywebviewReadyMs: Infinity });
    await new Promise((r) => setTimeout(r, 30));
    check('has("ping")（capabilities 里有）= true', sandbox.bridge.has('ping') === true);
    check('has("resources.all") = true', sandbox.bridge.has('resources.all') === true);
    check('has("resources.nothing") = false', sandbox.bridge.has('resources.nothing') === false);
  }

  /* 场景⑥：用户后来要求**删掉**「隐藏左侧栏元素」这个设置项（含 F9 临时恢复），
     所以这里从"验证 F9 不落盘"改成"验证它确实被删干净了" —— 断言方向反过来，
     强度不降：留着半个实现（比如只剩配置键、或只剩 F9 分支）同样是 bug。 */
  console.log('== 场景⑥：「隐藏左侧栏元素」/ F9 已按要求彻底移除 ==');
  {
    const src = fs.readFileSync(APP_JS, 'utf8');
    check('navRevealAll / navHiddenKeys / navVisible 全部不再存在',
      !/const navRevealAll/.test(src) && !/const navHiddenKeys/.test(src)
        && !/function navVisible/.test(src),
      '还有残留的隐藏机制');
    check('toggleNavReveal 不再存在', !/function toggleNavReveal/.test(src));
    check('NAV_HIDEABLE 清单不再存在', !/const NAV_HIDEABLE/.test(src));
    check('onKeydown 里不再有 F9 分支', !/event\.key === 'F9'/.test(src));
    check('设置页里不再有 nav_hide_* 行',
      !/key: 'nav_hide_elements'/.test(src) && !/nav_hide_settings/.test(src));
    check('前端默认配置里不再有 nav_hide_* 键',
      !/nav_hide_elements: false/.test(src));
  }

  console.log('\n=== 结论：' + (fails === 0 ? '全部通过' : fails + ' 项失败') + ' ===');
  process.exit(fails === 0 ? 0 : 1);
}

main().catch((e) => { console.error('测试自身出错:', e); process.exit(2); });
