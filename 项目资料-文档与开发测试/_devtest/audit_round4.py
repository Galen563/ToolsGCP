import io, os, re, json, itertools

# 本脚本位于 <仓库根>/项目资料-文档与开发测试/_devtest/ → 上溯三级才是仓库根
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def rd(*parts):
    return io.open(os.path.join(ROOT, *parts), encoding='utf-8').read()


def strip_js(s):
    s = re.sub(r'/\*[\s\S]*?\*/', '', s)
    s = re.sub(r'(?m)^\s*//.*$', '', s)
    return s


def strip_css(s):
    return re.sub(r'/\*[\s\S]*?\*/', '', s)


app_full = rd('.ToolsGCP', 'webui', 'js', 'app.js')
html_full = rd('.ToolsGCP', 'webui', 'index.html')
app = strip_js(app_full)
html = re.sub(r'<!--.*?-->', '', html_full, flags=re.S)
sfx = strip_css(rd('.ToolsGCP', 'webui', 'css', 'settings-fixes.css'))
aifix = strip_css(rd('.ToolsGCP', 'webui', 'css', 'ai-fixes.css'))
ai = rd('.ToolsGCP', 'desktop', 'api', 'ai.py')
pf = rd('.ToolsGCP', 'modules', 'pymodels', 'core', 'ai', 'profiles.py')
sm = rd('.ToolsGCP', 'modules', 'pymodels', 'core', 'settings_manager.py')
wh = rd('.ToolsGCP', 'desktop', 'webhost.py')
const = rd('.ToolsGCP', 'modules', 'pymodels', 'constants.py')

# 只取服务商卡片那一段 HTML
seg_start = html.index('provider-profiles')
seg = html[seg_start:seg_start + 5200]

checks = [
    ("启动黑底 · 服务端烘 data-theme 到 <html>", '_fix_html_tag' in wh and 'data-theme' in wh),
    ("启动黑底 · 保留 meta 兜底", 'tg-boot-theme' in wh),
    ("OpenAI 默认模型名称 = ChatGPT", '"openai": "ChatGPT"' in pf),
    ("弹窗化（内联编辑器已删）", '.ai-prof-editor' not in sfx and 'ai-prof-modal' in html),
    ("删掉按钮左侧介绍文本", 'ai_prof_bar_tip' not in seg),
    ("删掉「当前使用」徽标", 'ai_prof_active' not in seg),
    ("删掉「接口地址：」「token 限制输出：」标签", "t('ai_api_base', '接口地址') }}：" not in seg and "token 限制输出') }}：" not in seg),
    ("模型列表无选中态", 'is-current' not in seg and 'is-current' not in sfx),
    ("token 不勾选整块不出现", 'v-if="aiProfileEditing.limit_token"' in html),
    ("token 输入在下一行+缩进", 'margin-left: 18px' in sfx),
    ("custom 支持模型不塌陷", 'min-height: 56px' in sfx and 'ai_prof_models_manual' in html),
    ("弹窗无负边距（不再更贴边）", '-2px' not in sfx[sfx.index('.ai-prof-grid'):sfx.index('.ai-prof-grid') + 400]),
    ("弹窗底部有分隔+留白", 'border-top: 1px solid var(--card-border)' in sfx),
    ("卡片留白加大", 'padding: 13px 14px 13px 17px' in sfx),
    ("添加服务商在最右", 'class="grow"></span>' in seg and 'ai-prof-add' in seg),
    ("按钮顺序 取消|测试|保存", html.index('aiCancelProfile') < html.index('aiTestProfileDraft') < html.index('aiSaveProfile')),
    ("默认厂商不跳家（取清单第一条）", 'pid = catalog[0][0]' in ai and 'free = [item[0]' not in ai),
    ("档案有 id", 'def new_id' in pf and '"id": _text(raw.get("id"))' in pf),
    ("去重按 id 不按 provider", 'profile["id"] in seen' in pf and 'profile["provider"] in seen' not in pf),
    ("save 按 id 定位", 'item["id"] == incoming["id"]' in ai),
    ("delete 收 profile_id", 'def delete_profile(self, profile_id' in ai),
    ("Key 按档案分槽", 'def get_profile_api_key' in sm and 'def set_profile_api_key' in sm),
    ("读档案 Key 不再复制厂商槽", 'def get_profile_api_key' in sm and sm.split('def get_profile_api_key')[1].split('def ')[0].count('_key_slot(') == 0),
    ("迁移一次性标记", '"ai_profiles_migrated": False' in const and 'ai_profiles_migrated' in ai),
    ("迁移落盘一次（id 稳定）", 'self._persist_profiles(items)' in ai.split('def _profiles_raw')[1].split('def _has_legacy')[0]),
    ("聊天读档案 Key", 'get_profile_api_key(prof_id' in ai),
    ("model_choices 按档案出组+id", '"id": profile.get("id", "")' in ai),
    ("前端卡片 key 用 id", ':key="prof.id || prof.provider"' in html),
    ("前端 active 用 id", 'aiProfilesActiveId' in app and 'aiProfilesActiveId' in html),
    ("删除传 profile_id", "bridge.tryCall('ai.delete_profile', prof.id" in app),
    ("切换模型不弹提示", 'ai_model_switched' not in app),
    ("打字机限速已删", 'aiTyperStep' not in app and 'AI_TYPE_MAX_CPS' not in app),
    ("直通函数存在", 'function aiApplyStreamText' in app),
    ("done 不攒收尾包", 'aiTyperPendingDone' not in app),
    ("后端取消 120ms 节流", 'STREAM_POLL_INTERVAL = 0.008' in ai and 'STREAM_PUSH_INTERVAL = 0.12' not in ai),
    ("同步路径不假逐字", 'typewriterTail' not in app),
    ("思考状态按正文是否开始判定", 'streaming: !answered' in app),
    ("编辑未修改仍发送", '没改就不重发' not in app_full),
    ("编辑框宽度下限 240", 'MIN_EDIT_W = 240' in app),
    ("编辑框上限夹容器 88%", 'avail * 0.88' in app),
    ("滑块几何 at/(n-1)", 'aiThinkSegHeadStyle' in app and 'aiThinkFillStyle' in app),
    ("粒子随档位变量", '--think-spark-speed' in aifix and 'aiThinkSparkStyle' in app),
    ("粒子平铺无断层", 'repeat-x' in aifix and '180% 100%' not in aifix),
    ("润色图标不再转圈", 'ai-polish-pulse' in aifix),
    ("润色锁定保留", 'aiInputLocked' in app),
    ("滚动贴底/回底按钮保留", 'aiStickBottom' in app and 'ai-back-bottom' in html),
    ("每框独立撤销栈保留", '_fieldHistories' in app),
    ("右键复制分区保留", 'aiCtx.zone' in app),
    ("浅色框选加深保留", 'data-theme="light"] ::selection' in aifix),
    ("删除走自绘弹窗", 'await confirmDialog' in app and 'window.confirm(' not in app),
    ("gotoSettingsAi 锚点跟到弹窗", '.ai-prof-modal .secret-input' in app),
    ("combo 用 @change", '@update:model-value="aiProfile' not in html),
]

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  OK   " if ok else "  MISS ") + n)
print()
print("=== %d/%d 通过 ===" % (len(checks) - len(bad), len(checks)))
if bad:
    print("未通过:", bad)

# HTML 配平
src = re.sub(r'<script.*?</script>', '', html, flags=re.S)
src = re.sub(r'<style.*?</style>', '', src, flags=re.S)
void = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
stack, bad2 = [], []
for m in re.finditer(r'<(/?)([a-zA-Z][a-zA-Z0-9-]*)([^>]*?)(/?)>', src):
    c, t, _, sf = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
    if t in void or sf:
        continue
    if c:
        if stack and stack[-1][0] == t:
            stack.pop()
        else:
            bad2.append((t, src[:m.start()].count('\n') + 1))
    else:
        stack.append((t, src[:m.start()].count('\n') + 1))
print('HTML 配平:', 'OK' if not stack and not bad2 else (stack[:4], bad2[:4]))

# 三语
base = os.path.join(ROOT, '.ToolsGCP', 'modules', 'languages')
dirs = sorted(os.listdir(base))
sets = {}
for loc in dirs:
    k = set()
    for fn in os.listdir(os.path.join(base, loc)):
        k |= set(json.load(open(os.path.join(base, loc, fn), encoding='utf-8')))
    sets[loc] = k
diff = [(a, c) for a, c in itertools.combinations(dirs, 2) if sets[a] != sets[c]]
print('三语 key:', {k: len(v) for k, v in sets.items()}, '| 差异:', diff if diff else '无')
