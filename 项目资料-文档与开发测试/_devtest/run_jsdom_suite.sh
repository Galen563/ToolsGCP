#!/usr/bin/env bash
# 前端 jsdom 回归套件：一条命令跑完所有无浏览器探针（AGENTS.md 第 6 节的补充）。
#
# 为什么要这个脚本：这些 .mjs 探针各自要 serve.py 的 mock 后端 + GCP_PORT 环境变量，
# 手工一个个敲容易漏跑（本轮就发生过"只跑了改过的那一个，没跑同模块的另一个"）。
# 注意 1：必须由 Bash 执行 —— ops_bash 的 script_path 一律交给 Bash，同名 .ps1 会
#        直接报 `line 1: =: command not found`。
# 注意 2：serve.py 偶发并发丢一个大静态文件 ⇒ 探针里的 Vue 没挂上，看起来像产品回归。
#        判定 FAIL 之前先单独复跑那一个（复跑绿了就是环境抖动，不是缺陷）。
# 用法：先起预览 `python 项目资料-文档与开发测试/_devtest/serve.py 8912`，
#      再在本目录执行 `GCP_PORT=8912 bash run_jsdom_suite.sh`。
set -u
cd "$(dirname "$0")"
PORT="${GCP_PORT:-8912}"
PROBES="probe_back_top_ball probe_category_extras probe_detail_sel_ui probe_detail_ui probe_maker_i18n probe_maker_pool_sync probe_ping_busy_ui probe_tag_fold probe_task13_maker_ui probe_task19_preview probe_scroll_memory probe_repos_multi"
fail=0
for f in $PROBES; do
  if [ ! -f "$f.mjs" ]; then printf '%-26s MISSING\n' "$f"; fail=1; continue; fi
  out=$(GCP_PORT=$PORT node "$f.mjs" 2>&1); rc=$?
  last=$(printf '%s\n' "$out" | grep -v '^[[:space:]]*$' | tail -1)
  printf '%-26s EXIT=%s  %s\n' "$f" "$rc" "${last:0:70}"
  if [ "$rc" -ne 0 ]; then fail=1; printf '%s\n' "$out" | tail -20; fi
done
[ "$fail" -eq 0 ] && echo "RESULT: PASS" || echo "RESULT: FAIL"
exit $fail
