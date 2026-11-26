const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = process.cwd();
// NO document/navigator stubs: force Vue's pure-JS entity decoder path
vm.runInThisContext(fs.readFileSync(path.join(root, '.ToolsGCP/webui/js/vendor/vue.global.prod.js'), 'utf8'));
const Vue = global.Vue || global.window.Vue;
if (!Vue) { console.log('no vue'); process.exit(1); }
console.log('Vue', Vue.version);
try { Vue.compile('<div :title="t(\'a\', \'x&y\')">{{ b }}</div>'); console.log('probe ok'); }
catch (e) { console.log('probe THROW', e.message); }
const html = fs.readFileSync(path.join(root, '.ToolsGCP/webui/index.html'), 'utf8');
const lines = html.split(/\r?\n/);
const regions = { winResize:[224,233], header:[258,300], statsPage:[2144,2262],
                  liveRowPage:[2360,2400], statsDrawer:[3164,3285], drawerLive:[3330,3372] };
for (const [name, [a, b]] of Object.entries(regions)) {
  const srcTxt = lines.slice(a - 1, b).join('\n');
  const errs = [];
  try { Vue.compile('<div>' + srcTxt + '</div>', { onError: (e) => errs.push(String(e && e.message || e)) }); }
  catch (e) { errs.push('THROW: ' + e.message); }
  console.log(name, 'errors:', errs.length, errs.length ? String(errs[0]).slice(0, 160) : '');
}