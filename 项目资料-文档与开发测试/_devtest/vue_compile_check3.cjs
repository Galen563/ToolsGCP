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
console.log('Vue version:', Vue && Vue.version);
try { Vue.compile('<div>{{ a }}</div>'); console.log('tiny ok'); }
catch (e) { console.log('tiny THROW', e.message); }
const html = fs.readFileSync(path.join(root, '.ToolsGCP/webui/index.html'), 'utf8');
const start = html.indexOf('<div id="app"');
const tailIdx = html.indexOf('<script src="/static/js/app.js"');
let seg = html.slice(start, tailIdx);
const lastClose = seg.lastIndexOf('</div>');
seg = seg.slice(0, lastClose + 6);
console.log('seg bytes:', seg.length);
// split into top-level lines and grow by 400 lines per step
const lines = seg.split('\n');
let lo = 0, hi = lines.length, badHi = lines.length;
function okAt(n) {
  const chunk = lines.slice(0, n).join('\n');
  try { Vue.compile(chunk); return true; } catch (e) { return false; }
}
console.log('full ok?', okAt(lines.length));
// find first line count that fails
for (let n = 200; n <= lines.length; n += 200) {
  if (!okAt(n)) { badHi = n; break; }
}
if (badHi === lines.length && okAt(lines.length)) { console.log('ALL GOOD'); process.exit(0); }
lo = Math.max(0, badHi - 200);
for (let n = lo + 1; n <= badHi; n++) {
  if (!okAt(n)) {
    console.log('first failing line count:', n);
    console.log('context:', JSON.stringify(lines.slice(n - 6, n + 1).join('\n').slice(0, 400)));
    break;
  }
}