const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = process.cwd();
// Entity-decoding DOM stub good enough for compiler syntax checks:
// Vue in-browser decoder does: el=document.createElement('div'); el.innerHTML=raw; el.textContent
function decodeEntities(s) {
  return String(s)
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&#(\d+);/g, (m, d) => String.fromCharCode(parseInt(d, 10)))
    .replace(/&x([0-9a-fA-F]+);/g, (m, h) => String.fromCharCode(parseInt(h, 16)));
}
global.document = {
  createElement: () => {
    // Vue 3.5 的浏览器解码器：decoder.innerHTML = '<div foo="...">' 然后读
    // decoder.children[0].getAttribute('foo')。stub 必须同时提供 textContent 与
    // children[0].getAttribute 两条路，否则编译整个模板时 decodeEntities 崩。
    const el = { _raw: '', textContent: '', style: {}, className: '' };
    const child = { getAttribute: () => el._decodedAttr };
    el.children = [child];
    Object.defineProperty(el, 'innerHTML', {
      set(v) {
        el._raw = String(v);
        el.textContent = decodeEntities(String(v));
        const m = String(v).match(/^<div foo="([\s\S]*)">$/);
        el._decodedAttr = m ? decodeEntities(m[1]) : null;
      },
      get() { return el._raw; },
    });
    el.setAttribute = () => {}; el.appendChild = () => {}; el.querySelector = () => null;
    return el;
  },
  querySelector: () => null, addEventListener() {},
  documentElement: { style: {}, setAttribute() {} },
  head: { appendChild() {} }, createTextNode: () => ({}),
};
global.window = global; global.self = global; global.navigator = { userAgent: 'node' };
vm.runInThisContext(fs.readFileSync(path.join(root, '.ToolsGCP/webui/js/vendor/vue.global.prod.js'), 'utf8'));
const Vue = global.Vue;
const html = fs.readFileSync(path.join(root, '.ToolsGCP/webui/index.html'), 'utf8');
const start = html.indexOf('<div id="app"');
const tail = html.indexOf('<script src="/static/js/app.js"');
let seg = html.slice(start, tail);
seg = seg.slice(0, seg.lastIndexOf('</div>') + 6);
const errs = [];
let res;
try {
  res = Vue.compile(seg, { onError: (e) => errs.push(String(e && e.message || e)),
                           onWarn: (w) => errs.push('WARN ' + String(w && w.message || w)) });
} catch (e) {
  errs.push('THROW: ' + e.message + ' | ' + String(e.stack).split('\n').slice(1, 3).join(' / '));
}
console.log('template bytes:', seg.length);
console.log('errors:', errs.length);
errs.slice(0, 20).forEach(e => console.log(' -', String(e).slice(0, 260)));
if (!errs.length && res) console.log('COMPILED OK, ast type:', res && typeof res);