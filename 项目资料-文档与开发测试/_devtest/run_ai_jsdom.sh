#!/usr/bin/env bash
# 跑完整 11 个 AI jsdom 用例（前台 300 秒会被截断，所以放后台）
set -u
cd "C:/Users/Administrator/Desktop/ToolsGCP开发/v1.1.4 - 12" || exit 1
PORT=8835
OUT="项目资料-文档与开发测试/_devtest/reports/ai_jsdom_r2.txt"

python "项目资料-文档与开发测试/_devtest/serve.py" "$PORT" >/dev/null 2>&1 &
SRV=$!
trap 'kill '"$SRV"' 2>/dev/null' EXIT

for i in $(seq 1 40); do
  python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:$PORT/static/css/base.css',timeout=1).read(16)" 2>/dev/null && break
  sleep 0.3
done

GCP_PORT=$PORT timeout 900 node "项目资料-文档与开发测试/_devtest/test_ai_jsdom.mjs" > "$OUT" 2>&1
echo "exit=$?" >> "$OUT"
