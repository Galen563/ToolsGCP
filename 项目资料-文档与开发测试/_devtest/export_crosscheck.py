# -*- coding: utf-8 -*-
import io, re
js = io.open(r'.ToolsGCP/webui/js/app.js', encoding='utf-8').read()
i = js.rindex('return {')
# take until we balance braces
depth = 0; j = i
while j < len(js):
    ch = js[j]
    if ch == '{': depth += 1
    elif ch == '}':
        depth -= 1
        if depth == 0: break
    j += 1
ret = js[i:j]
names = ['aiStatsOpen','aiStatsHover','aiCacheStats','aiTokenStats','aiContextStats',
'aiNumberFmt','copyAiStats','aiRunCardIndex','aiLiveSteps','aiAgentStepsDone',
'aiAgentStepsOpen','aiAgentStepsSummary','toggleAgentSteps','aiAgentPlanning',
'aiBubbleSteps','aiBubbleStepsOpen','aiToggleBubbleSteps','aiBubbleStepsDone',
'aiBubbleStepsSummary','aiUsageLast','aiUsageTotal','aiLastHit']
missing = [n for n in names if not re.search(r'\\b' + n + r'\\b', ret)]
print('return block lines:', ret.count(chr(10)))
print('missing exports:', missing if missing else 'NONE')