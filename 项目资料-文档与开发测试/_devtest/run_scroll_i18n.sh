#!/usr/bin/env bash
# 版本树滚动锚点 + 英文界面中文残留扫描
set -u
cd "C:/Users/Administrator/Desktop/ToolsGCP开发/v1.1.4 - 12" || exit 1
R="项目资料-文档与开发测试/_devtest/reports"
P=8851
python "项目资料-文档与开发测试/_devtest/serve.py" $P >/dev/null 2>&1 &
SRV=$!
trap 'kill '"$SRV"' 2>/dev/null' EXIT
for i in $(seq 1 40); do
  python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:$P/static/css/base.css',timeout=1).read(16)" 2>/dev/null && break
  sleep 0.3
done
GCP_PORT=$P timeout 400 node "项目资料-文档与开发测试/_devtest/test_ai_version_scroll.mjs" > "$R/version_scroll.txt" 2>&1
echo "exit=$?" >> "$R/version_scroll.txt"
GCP_PORT=$P I18N_LANG=English timeout 500 node "项目资料-文档与开发测试/_devtest/test_i18n_english_leak.mjs" > "$R/i18n_leak_en.txt" 2>&1
echo "exit=$?" >> "$R/i18n_leak_en.txt"
