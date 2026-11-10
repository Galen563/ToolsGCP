#!/usr/bin/env bash
# 只复跑 sweep 里那两个 FAIL 项（matrix 需要 8811；i18n 扫描需要 mock 服务）
set -u
cd "C:/Users/Administrator/Desktop/ToolsGCP开发/v1.1.4 - 12" || exit 1
R="项目资料-文档与开发测试/_devtest/reports"
P=8868
python "项目资料-文档与开发测试/_devtest/serve.py" $P >/dev/null 2>&1 &
S1=$!
python "项目资料-文档与开发测试/_devtest/serve.py" 8811 >/dev/null 2>&1 &
S2=$!
trap 'kill '"$S1"' '"$S2"' 2>/dev/null' EXIT
for i in $(seq 1 40); do
  python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8811/static/css/base.css',timeout=1).read(16)" 2>/dev/null && break
  sleep 0.3
done
printf 'layout_matrix  '
timeout 300 node "项目资料-文档与开发测试/_devtest/test_cards_layout_matrix.js" >/dev/null 2>&1 && echo PASS || echo FAIL
printf 'i18n_leak      '
GCP_PORT=$P I18N_LANG=English timeout 600 node "项目资料-文档与开发测试/_devtest/test_i18n_english_leak.mjs" > "$R/i18n_leak_final.txt" 2>&1 && echo PASS || echo FAIL
head -4 "$R/i18n_leak_final.txt"
grep -E "^  [a-z]+: |^共 |ALL OK" "$R/i18n_leak_final.txt" | head -20
