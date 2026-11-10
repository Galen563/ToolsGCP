# -*- coding: utf-8 -*-
r"""插件双目录自检：确认"两个插件根目录都加载、用户目录优先、内置受保护"。

========== 为什么需要它 ==========
exe 打包后 `<程序目录>\\.ToolsGCP\\plugins` 被塞进 exe 本体（多半只读），
所以插件支持**两个**根目录：
    ① 内置：`<程序目录>\\.ToolsGCP\\plugins\`（随程序发布）
    ② 用户：`<数据根>\plugins\`（默认 `%USERPROFILE%\\.ToolsGCP\\plugins\`，启动自动创建）
优先级 ② > ①，同名插件用户那份生效、内置那份被遮住但**不可删**。

这套规则一旦被破坏，用户会看到"插件列表里没有 / 装了不生效 / 想删删不掉"，
而且**在开发机上很难复现**（开发机的程序目录本身就是可写的）。
所以这里做一组自检，用临时目录造插件，跑完自动清理：

  1. 两个根目录都存在，且顺序 = [用户, 内置]
  2. 用户目录里新建的插件能被 list() 扫到，且 source == 'user'
  3. find_plugin_dir 能找到它；带 `..` 的路径被拒绝
  4. 与内置插件同名的用户插件：只出一条、source=user、带 shadowed
  5. 内置那份删不掉（受保护），但用户覆盖版可以删
  6. `webhost` 的 `/res/plugins/<id>/<file>` 能服务**用户目录**里的文件

========== 用法 ==========
    python "项目资料-文档与开发测试/_devtest/plugins_dualroot_check.py"
退出码 0 = 通过。⚠️ 会在用户插件目录里临时建 `__selftest_*` 文件夹，结束自动删除。
"""

import io
import json
import os
import shutil
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# ⚠️ 必须修正 argv[0]，否则 CONFIG_DIR/SCRIPT_DIR 会解析到本脚本所在目录
sys.argv[0] = os.path.join(ROOT, 'ToolsGCP.pyw')
sys.path[:0] = [os.path.join(ROOT, '.ToolsGCP'),
                os.path.join(ROOT, '.ToolsGCP', 'modules')]

from desktop.api import plugins as P                    # noqa: E402

checks = []


def check(name, cond, detail=''):
    checks.append((name, bool(cond), detail))
    print(('  ✅ ' if cond else '  ❌ ') + name + (f'  [{detail}]' if detail else ''))


def wsgi_get(app, path):
    """直接调 WSGI 应用取一个路径，返回 (status, body)"""
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured['status'] = status

    environ = {
        'REQUEST_METHOD': 'GET', 'SCRIPT_NAME': '', 'PATH_INFO': path,
        'QUERY_STRING': '', 'SERVER_NAME': '127.0.0.1', 'SERVER_PORT': '0',
        'SERVER_PROTOCOL': 'HTTP/1.1', 'wsgi.version': (1, 0),
        'wsgi.url_scheme': 'http', 'wsgi.input': io.BytesIO(b''),
        'wsgi.errors': sys.stderr, 'wsgi.multithread': False,
        'wsgi.multiprocess': False, 'wsgi.run_once': False,
    }
    body = b''
    for chunk in app(environ, start_response):
        body += chunk
    return captured.get('status', '(none)'), body


def make_plugin(base, folder, manifest_extra=None):
    """在 base 下造一个最小插件目录"""
    dest = os.path.join(base, folder)
    os.makedirs(dest, exist_ok=True)
    manifest = {'id': folder, 'name': '自检插件', 'config_page': 'config.html'}
    if manifest_extra:
        manifest.update(manifest_extra)
    with open(os.path.join(dest, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False)
    with open(os.path.join(dest, 'config.html'), 'w', encoding='utf-8') as f:
        f.write('<!doctype html><title>selftest</title>')
    return dest


def main() -> int:
    roots = P.plugins_dirs()
    user_root = roots[0] if roots else ''
    builtin_root = P.plugins_dir()

    print('插件根目录（按优先级）:')
    for i, r in enumerate(roots):
        print(f'   [{i}] {r}')
    print()

    print('=== 1) 目录与顺序 ===')
    check('至少有两个根目录', len(roots) == 2, f'{len(roots)} 个')
    check('第一个是用户目录', os.path.normcase(user_root) != os.path.normcase(builtin_root),
          user_root)
    check('用户目录已存在（自动创建）', os.path.isdir(user_root))
    check('内置目录存在', os.path.isdir(builtin_root))

    print()
    print('=== 2) 列表 / 查找 / 路径穿越 ===')
    created = []
    try:
        pid = 'zz-selftest-user-plugin'
        created.append(make_plugin(user_root, pid))

        dom = P.PluginsDomain.__new__(P.PluginsDomain)
        dom._shell = None
        dom._language = lambda: '简体中文'
        dom._locale_safe = lambda: 'zh_CN'

        res = dom.list()
        row = [r for r in res.get('plugins', []) if r.get('folder') == pid]
        check('list() 扫到用户插件', bool(row))
        check('  source == user', row[0].get('source') == 'user' if row else False,
              row[0].get('source') if row else '')
        check('find_plugin_dir 命中用户目录',
              os.path.normcase(P.find_plugin_dir(pid)) ==
              os.path.normcase(os.path.join(user_root, pid)))
        check('拒绝路径穿越', P.find_plugin_dir('../../config') == '')

        print()
        print('=== 3) 同名覆盖：用户版生效、内置版受保护 ===')
        shadow = os.path.join(user_root, 'gcp-plugin-maker')
        if not os.path.isdir(shadow):
            created.append(make_plugin(user_root, 'gcp-plugin-maker',
                                       {'name': '覆盖版', 'version': '9.9.9'}))
            res2 = dom.list()
            rows2 = [r for r in res2.get('plugins', []) if r.get('folder') == 'gcp-plugin-maker']
            check('同名插件只出一条', len(rows2) == 1, f'{len(rows2)} 条')
            if rows2:
                check('  生效的是用户那份', rows2[0].get('source') == 'user')
                check('  带 shadowed（记录被遮住的内置版）', bool(rows2[0].get('shadowed')))
            d = dom.delete('gcp-plugin-maker')
            check('用户覆盖版可以删除', bool(d.get('ok')), str(d.get('error', '')))
            check('内置版仍然存在', os.path.isdir(os.path.join(builtin_root, 'gcp-plugin-maker')))
            created.remove(shadow)
        else:
            print('  （用户目录已有同名 gcp-plugin-maker，跳过该子项以免影响用户环境）')

        print()
        print('=== 4) 静态路由能服务用户目录里的插件 ===')
        from desktop.webhost import create_app
        app = create_app()
        st, body = wsgi_get(app, '/res/plugins/%s/config.html' % pid)
        check('用户插件 config.html 可取', '200' in st and b'selftest' in body, st)
        st2, _ = wsgi_get(app, '/res/plugins/gcp-plugin-maker/manifest.json')
        check('内置插件 manifest 可取', '200' in st2, st2)
        st3, _ = wsgi_get(app, '/res/plugins/__nonexistent__/manifest.json')
        check('不存在的插件返回 404', '404' in st3, st3)

        print()
        print('=== 5) 清理 ===')
        d2 = dom.delete(pid)
        check('自检插件已删除', bool(d2.get('ok')), str(d2.get('error', '')))
    finally:
        for p in created:
            shutil.rmtree(p, ignore_errors=True)
        print('  清理完成')

    print()
    npass = sum(1 for _, ok, _ in checks if ok)
    print('=' * 70)
    print(f'总计 {len(checks)} 项：通过 {npass} / 失败 {len(checks) - npass}')
    if npass != len(checks):
        for name, ok, detail in checks:
            if not ok:
                print('  -', name, detail)
    return 0 if npass == len(checks) else 1


if __name__ == '__main__':
    sys.exit(main())
