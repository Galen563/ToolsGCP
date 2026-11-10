#!/usr/bin/env bash
# 视觉四项验证（含未保存弹窗真跑）+ 修正后的英文残留扫描
set -u
cd "C:/Users/Administrator/Desktop/ToolsGCP开发/v1.1.4 - 12" || exit 1
R="项目资料-文档与开发测试/_devtest/reports"
P=8857
python "项目资料-文档与开发测试/_devtest/serve.py" $P >/dev/null 2>&1 &
SRV=$!
trap 'kill '"$SRV"' 2>/dev/null' EXIT
for i in $(seq 1 40); do
  python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:$P/static/css/base.css',timeout=1).read(16)" 2>/dev/null && break
  sleep 0.3
done
GCP_PORT=$P timeout 500 python -X utf8 "项目资料-文档与开发测试/_devtest/test_r2_visual_and_dialog.py" > "$R/visual_dialog.txt" 2>&1
echo "visual_exit=$?" >> "$R/visual_dialog.txt"
GCP_PORT=$P I18N_LANG=English timeout 600 node "项目资料-文档与开发测试/_devtest/test_i18n_english_leak.mjs" > "$R/i18n_leak_en.txt" 2>&1
echo "i18n_exit=$?" >> "$R/i18n_leak_en.txt"
