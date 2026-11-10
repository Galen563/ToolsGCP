#!/usr/bin/env bash
# 复跑：设置页探针（下拉框跟随新断言）+ 输入框右键菜单"点了真有效果"专项
set -u
cd "C:/Users/Administrator/Desktop/ToolsGCP开发/v1.1.4 - 12" || exit 1
R="项目资料-文档与开发测试/_devtest/reports"
P=8846
python "项目资料-文档与开发测试/_devtest/serve.py" $P >/dev/null 2>&1 &
SRV=$!
trap 'kill '"$SRV"' 2>/dev/null' EXIT
for i in $(seq 1 40); do
  python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:$P/static/css/base.css',timeout=1).read(16)" 2>/dev/null && break
  sleep 0.3
done
GCP_PORT=$P timeout 500 node "项目资料-文档与开发测试/_devtest/settings_probe_jsdom.mjs" > "$R/settings_jsdom_r2.txt" 2>&1
echo "settings_exit=$?" >> "$R/settings_jsdom_r2.txt"
GCP_PORT=$P timeout 400 node "项目资料-文档与开发测试/_devtest/test_input_menu_click.mjs" > "$R/input_menu_click.txt" 2>&1
echo "menu_exit=$?" >> "$R/input_menu_click.txt"
