const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = process.cwd();
global.window = global; global.self = global;
global.navigator = { userAgent: 'node' };
global.document = { createElement: () => ({ setAttribute(){}, style:{}, appendChild(){} }),
                   querySelector: () => null, addEventListener(){},
                   documentElement: { style:{}, setAttribute(){} },
                   head: { appendChild(){} }, createTextNode: () => ({}) };
vm.runInThisContext(fs.readFileSync(path.join(root, '.ToolsGCP/webui/js/vendor/vue.global.prod.js'), 'utf8'));
const Vue = global.Vue;
const html = fs.readFileSync(path.join(root, '.ToolsGCP/webui/index.html'), 'utf8');
const lines = html.split(/\r?\n/);
function grab(a, b) { return lines.slice(a - 1, b).join('\n'); }
const regions = {
  winResize: [224, 233],
  header: [258, 300],
  statsPage: [2144, 2262],
  liveRowPage: [2360, 2400],
  statsDrawer: [3164, 3285],
};
for (const [name, [a, b]] of Object.entries(regions)) {
  let srcTxt = grab(a, b);
  const errs = [];
  // wrap in template root to tolerate fragment top-level
  try { Vue.compile('<div>' + srcTxt + '</div>', { onError: (e) => errs.push(String(e && e.message || e)) }); }
  catch (e) { errs.push('THROW: ' + e.message); }
  console.log(name, 'lines', a + '-' + b, 'errors:', errs.length);
  errs.slice(0, 6).forEach((e) => console.log('   -', String(e).slice(0, 200)));
}