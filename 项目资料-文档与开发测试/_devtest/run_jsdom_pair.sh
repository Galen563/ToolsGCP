#!/usr/bin/env bash
# 跑两个 jsdom 探针（AI 11 用例 + 设置页），前台容易超时，所以放后台
set -u
cd "C:/Users/Administrator/Desktop/ToolsGCP开发/v1.1.4 - 12" || exit 1
R="项目资料-文档与开发测试/_devtest/reports"
python "项目资料-文档与开发测试/_devtest/serve.py" 8841 >/dev/null 2>&1 &
SRV=$!
trap 'kill '"$SRV"' 2>/dev/null' EXIT
for i in $(seq 1 40); do
  python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8841/static/css/base.css',timeout=1).read(16)" 2>/dev/null && break
  sleep 0.3
done
GCP_PORT=8841 timeout 800 node "项目资料-文档与开发测试/_devtest/test_ai_jsdom.mjs" > "$R/ai_jsdom_r2.txt" 2>&1
echo "ai_exit=$?" >> "$R/ai_jsdom_r2.txt"
GCP_PORT=8841 timeout 500 node "项目资料-文档与开发测试/_devtest/settings_probe_jsdom.mjs" > "$R/settings_jsdom_r2.txt" 2>&1
echo "settings_exit=$?" >> "$R/settings_jsdom_r2.txt"
