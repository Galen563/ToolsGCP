"""档案按 id 独立 + Key 按档案分槽 + 旧数据迁移（临时验证脚本，跑完删）"""
import sys, os, shutil, json

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, '.ToolsGCP'), os.path.join(ROOT, '.ToolsGCP', 'modules')]
tmp = os.path.join(ROOT, '_dt_profiles_v3')
shutil.rmtree(tmp, ignore_errors=True)
os.makedirs(tmp)

from pymodels.core.settings_manager import SettingsManager
from pymodels.core.ai import profiles as P
from desktop.api.ai import AiDomain

m = SettingsManager(config_dir=tmp)


class Shell:
    _teardown_started = False
    _quitting = False
    api = None

    def __init__(self, mgr):
        self.settings_manager = mgr

    def push_event(self, *a, **k):
        pass

    def current_language(self):
        return '简体中文'


d = AiDomain.__new__(AiDomain)
d._shell = Shell(m)

print('1) 同厂商两条档案不被吞')
m.set_api_key('sk-ds-1', 'deepseek')
# 先落一次盘：让"老配置合成"那条正式成为档案并置上 migrated 标记，
# 之后新增几条就是干净的净增量。
d.save_profile({'provider': 'deepseek', 'label': 'DeepSeek', 'models': ['deepseek-v4.1-flash']})
base_n = len(d.profiles()['profiles'])
d.save_profile({'provider': 'deepseek', 'label': 'DeepSeek 工作',
                'api_base': 'https://api.deepseek.com/v1',
                'models': ['deepseek-v4.1-flash']})
r2 = d.save_profile({'provider': 'deepseek', 'label': 'DeepSeek 个人',
                     'api_base': 'https://中转.example.com/v1',
                     'models': ['deepseek-v4-pro']})
lst = r2['profiles']
labels = [p['label'] for p in lst]
print('   基线 =', base_n, '现在 =', len(lst), labels)
assert len(lst) == base_n + 2, '同厂商第二条被吞了！'
assert 'DeepSeek 工作' in labels and 'DeepSeek 个人' in labels, labels
assert len({p['id'] for p in lst}) == len(lst), '档案 id 有重复'
print('   PASS')

print('\n2) Key 按档案独立（改一条不影响另一条）')
by_label = {p['label']: p for p in lst}
id1, id2 = by_label['DeepSeek 工作']['id'], by_label['DeepSeek 个人']['id']
m.set_profile_api_key('sk-AAA-1111', id1, 'deepseek')
m.set_profile_api_key('sk-BBB-2222', id2, 'deepseek')
print('   档案1 =', m.get_profile_api_key(id1, 'deepseek'))
print('   档案2 =', m.get_profile_api_key(id2, 'deepseek'))
assert m.get_profile_api_key(id1, 'deepseek') == 'sk-AAA-1111'
assert m.get_profile_api_key(id2, 'deepseek') == 'sk-BBB-2222'
print('   PASS: 两条互不覆盖')

print('\n3) 优先级：删掉 active 才落到下一条有 Key 的')
first_id = next(p['id'] for p in lst if p['has_key'])
rd = d.delete_profile(first_id)
rest = rd['profiles']
print('   删除 active', first_id, '→ 剩余', len(rest))
# 其余档案都没配 Key（新建就是空的），所以此时没有可用档案
assert len(rest) == len(lst) - 1
# 给 id2 之外的另一条也配上 Key，验证"更靠上的优先"
second = rest[0]['id']
m.set_profile_api_key('sk-SECOND-3333', second, rest[0]['provider'])
p2 = d.profiles()
print('   active 应为最上且有 Key 的 =', p2['active_id'], '期望', second)
assert p2['active_id'] == second
# 再逐个删掉有 Key 的，验证最终落到 id2（下一条有 Key 的档案）
cur = d.delete_profile(second)
guard = 0
while cur['active_id'] != id2 and guard < 10:
    guard += 1
    cur = d.delete_profile(cur['active_id'])
print('   最终 active =', cur['active_id'], '期望', id2)
assert cur['active_id'] == id2, '没有自动落到下一条有 Key 的档案'
assert m.get_profile_api_key(id2, 'deepseek') == 'sk-BBB-2222', '删别条时误伤了本条 Key'
c = d._credentials()
print('   聊天实际用 =', c['provider'], c['model'], c['api_base'], c['key_tail'])
assert c['api_base'] == 'https://中转.example.com/v1'
assert c['key_tail'].endswith('2222')
print('   PASS')

print('\n3b) 删掉**最后一条**后不会又"复活"出幽灵档案')
tmpg = os.path.join(ROOT, '_dt_ghost')
shutil.rmtree(tmpg, ignore_errors=True)
os.makedirs(tmpg)
mg = SettingsManager(config_dir=tmpg)
dg = AiDomain.__new__(AiDomain)
dg._shell = Shell(mg)
mg.set_api_key('sk-x', 'deepseek')
one = dg.save_profile({'provider': 'deepseek', 'label': '唯一', 'models': ['m1']})
n_before = len(one['profiles'])
gone = dg.delete_profile(one['profiles'][-1]['id'])
again = dg.profiles()
print('   存过 =', n_before, '删后 =', len(gone['profiles']), '再读 =', len(again['profiles']))
assert len(gone['profiles']) == n_before - 1
assert len(again['profiles']) == n_before - 1, '删光后又复活出幽灵档案'
print('   PASS')

print('\n4) 旧配置迁移（只有厂商槽、档案无 id）')
tmp2 = os.path.join(ROOT, '_dt_legacy')
shutil.rmtree(tmp2, ignore_errors=True)
os.makedirs(tmp2)
m2 = SettingsManager(config_dir=tmp2)
m2.update_setting('ai_provider', 'openai')
m2.update_setting('model_name', 'gpt-5.1')
m2.set_api_key('sk-legacy-9999', 'openai')
d2 = AiDomain.__new__(AiDomain)
d2._shell = Shell(m2)
p = d2.profiles()
print('   档案 =', [(x['label'], x['has_key'], x['key_tail']) for x in p['profiles']])
assert p['profiles'][0]['has_key'], '旧厂商槽的 Key 没迁移过来'
first_id = p['profiles'][0]['id']
# 迁移的 Key 此时只在内存里（_legacy_key），**要等用户第一次保存档案才落槽**——
# 这是设计决定（读操作绝不写盘）。所以这里验的是"能用"，不是"槽里有"。
c_leg = d2._credentials()
print('   升级后直接聊天用的 Key 尾号 =', c_leg['key_tail'])
assert c_leg['api_key'] == 'sk-legacy-9999', '迁移的 Key 没生效'
# 真正保存一次之后，Key 才落到这条档案自己的槽
d2.save_profile(dict(p['profiles'][0]))
assert m2.get_profile_api_key(first_id, 'openai') == 'sk-legacy-9999', '落盘后 Key 没进档案槽'
print('   落盘后档案槽读到 =', m2.get_profile_api_key(first_id, 'openai'))
# 再新增一条同厂商的，**不该**也拿到这把 Key
add2 = d2.save_profile({'provider': 'openai', 'label': '另一条', 'models': ['gpt-4.1']})
other = [x for x in add2['profiles'] if x['label'] == '另一条'][0]
assert not other['has_key'], '新档案不该自动继承别条的 Key'
print('   新档案 has_key =', other['has_key'], '(正确：独立，不继承)')
# 再调用一次不该重复迁移/不该多出幽灵档案
p2 = d2.profiles()
assert len(p2['profiles']) == 2 and p2['profiles'][0]['id'] == first_id
print('   PASS: 迁移一次性、幂等，label 默认 =', p['profiles'][0]['label'])
assert p['profiles'][0]['label'] == 'ChatGPT', 'OpenAI 默认名应为 ChatGPT'

print('\n5) add_profile 默认仍是第一条厂商（DeepSeek）')
r = d.add_profile()
print('   draft.provider =', r['draft']['provider'], '| is_new =', r.get('is_new'))
assert r['draft']['provider'] == 'deepseek'
assert r.get('is_new') is True

print('\n6) model_choices 同厂商出两组、current 按 id')
tmp3 = os.path.join(ROOT, '_dt_two')
shutil.rmtree(tmp3, ignore_errors=True)
os.makedirs(tmp3)
m3 = SettingsManager(config_dir=tmp3)
d3 = AiDomain.__new__(AiDomain)
d3._shell = Shell(m3)
a = d3.save_profile({'provider': 'deepseek', 'label': 'A', 'models': ['deepseek-v4.1-flash']})
id_a = [p for p in a['profiles'] if p['label'] == 'A'][0]['id']
m3.set_profile_api_key('sk-A-0001', id_a, 'deepseek')
b = d3.save_profile({'provider': 'deepseek', 'label': 'B', 'models': ['deepseek-v4-pro']})
id_b = [p for p in b['profiles'] if p['label'] == 'B'][0]['id']
m3.set_profile_api_key('sk-B-0002', id_b, 'deepseek')
mc = d3.model_choices()
got = [(g.get('id'), g['profile_label'], [x['name'] for x in g['models']])
       for g in mc['groups']]
print('   groups =', got)
assert id_a in {g.get('id') for g in mc['groups']}, 'A 档案没出现在弹层里'
assert id_b in {g.get('id') for g in mc['groups']}, 'B 档案没出现在弹层里'
print('   current.id =', mc['current']['id'])
assert mc['current']['id'] == id_a, 'current 必须是最靠上那条（A）'
print('   PASS')

for x in (tmp, tmp2, tmp3, tmpg):
    shutil.rmtree(x, ignore_errors=True)
# 兜底清扫：本脚本历史上漏过 tmpg（仓库根会多出 _dt_ghost/），
# 所以把**仓库根**里任何 _dt_*/_devtmp_*/_dbg* 临时目录都清掉，避免污染工作区。
# ⚠️ 只扫 ROOT（仓库根），绝不扫它的父目录 —— 父目录里还有别的项目副本。
for _name in os.listdir(ROOT):
    if _name.startswith(('_dt_', '_devtmp_', '_dbg')):
        shutil.rmtree(os.path.join(ROOT, _name), ignore_errors=True)
print('\nALL PASS')
