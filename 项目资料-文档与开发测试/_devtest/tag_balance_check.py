# -*- coding: utf-8 -*-
import io
from html.parser import HTMLParser

VOID = set(['br','img','input','hr','meta','link','source','area','base','col',
           'embed','param','track','wbr'])

class Checker(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=False)
        self.stack = []
        self.errors = []
    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        self.stack.append((tag, self.getpos()))
    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.errors.append('stray close %s at line %s' % (tag, self.getpos()[0]))
            return
        if self.stack[-1][0] == tag:
            self.stack.pop()
            return
        # tolerate implicit paragraph closes
        while self.stack and self.stack[-1][0] == 'p':
            self.stack.pop()
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()
        else:
            top, pos = self.stack[-1]
            self.errors.append('close %s at line %s does not match open %s from line %s'
                               % (tag, self.getpos()[0], top, pos[0]))
            self.stack.pop()

path = '.ToolsGCP/webui/index.html'
text = io.open(path, encoding='utf-8').read()
start = text.index('<div id="app"')
tail = text.index('<script src="/static/js/app.js"')
seg = text[start:tail]
seg = seg[:seg.rindex('</div>') + 6]
c = Checker()
c.feed(seg)
print('seg lines:', seg.count(chr(10)) + 1)
print('errors:', len(c.errors))
for e in c.errors[:20]:
    print(' -', e)
print('unclosed at EOF:', [(t, p[0]) for (t, p) in c.stack][:20])