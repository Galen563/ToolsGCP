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
const srcTxt = lines.slice(223, 233).join('\n');
try {
  Vue.compile('<div>' + srcTxt + '</div>');
  console.log('ok');
} catch (e) {
  console.log('THROW:', e.message);
  console.log(e.stack.split('\n').slice(0, 6).join('\n'));
  console.log('---- content ----');
  console.log(srcTxt);
}