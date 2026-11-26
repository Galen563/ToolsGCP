#!/usr/bin/env bash
# 跑本轮相关 jsdom 探针（maker i18n + detail ui）
set -u
cd "C:/Users/Administrator/Desktop/ToolsGCP开发/v1.1.4 - 12" || exit 1
R="项目资料-文档与开发测试/_devtest/reports"
mkdir -p "$R"
PORT=8899
python "项目资料-文档与开发测试/_devtest/serve.py" $PORT >/dev/null 2>&1 &
SRV=$!
trap 'kill '"$SRV"' 2>/dev/null' EXIT
for i in $(seq 1 60); do
  python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:$PORT/static/css/base.css',timeout=1).read(16)" 2>/dev/null && break
  sleep 0.3
done
for p in probe_maker_i18n probe_detail_ui probe_category_extras; do
  GCP_PORT=$PORT timeout 600 node "项目资料-文档与开发测试/_devtest/$p.mjs" > "$R/$p.txt" 2>&1
  echo "${p}_exit=$?" >> "$R/$p.txt"
done
echo DONE
