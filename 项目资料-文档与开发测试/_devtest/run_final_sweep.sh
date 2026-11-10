#!/usr/bin/env bash
# 最终全量验证：14 个 Python 套件 + 5 个 Node 探针 + 语法/导入/JSON 校验
set -u
cd "C:/Users/Administrator/Desktop/ToolsGCP开发/v1.1.4 - 12" || exit 1
R="项目资料-文档与开发测试/_devtest/reports"
OUT="$R/final_sweep.txt"
: > "$OUT"

echo "=== 语法 / 导入 ===" >> "$OUT"
python -m compileall -q .ToolsGCP/desktop .ToolsGCP/modules ToolsGCP.pyw 2>&1 | tail -2 >> "$OUT" && echo "PY_COMPILE OK" >> "$OUT"
python -c "import sys;sys.path[:0]=['.ToolsGCP','.ToolsGCP/modules'];import desktop.shell;print('IMPORT OK')" 2>&1 | tail -1 >> "$OUT"
for f in app.js icons.js rich-input.js; do node --check ".ToolsGCP/webui/js/$f" 2>&1 | head -2 >> "$OUT" && echo "JS OK $f" >> "$OUT"; done
python -X utf8 -c "
import io,json,os
bad=0
for L in os.listdir('.ToolsGCP/modules/languages'):
    for f in os.listdir(os.path.join('.ToolsGCP/modules/languages',L)):
        try: json.load(io.open(os.path.join('.ToolsGCP/modules/languages',L,f),encoding='utf-8'))
        except Exception as e: print('JSON BAD',L,f,e); bad+=1
print('JSON OK' if bad==0 else f'JSON {bad} BAD')
" >> "$OUT" 2>&1

echo "" >> "$OUT"
echo "=== Python 套件 ===" >> "$OUT"
for t in test_ai_thinking_stream test_ai_versions test_ai_regen_behavior test_ai_assistant_branch_tree \
         test_ai_error_i18n test_boot_screen_theme test_browser_mode_tray test_browser_tab_icon \
         test_settings_sync test_op_log_path test_splash_theme test_traymenu_hover test_restart_relay \
         test_autostart_toggle; do
  printf '%-34s ' "$t" >> "$OUT"
  timeout 150 python -X utf8 "项目资料-文档与开发测试/_devtest/$t.py" >/dev/null 2>&1 \
    && echo "PASS" >> "$OUT" || echo "FAIL" >> "$OUT"
done

echo "" >> "$OUT"
echo "=== Node（不需要 mock 服务）===" >> "$OUT"
for t in test_ai_pure_logic test_cards_contracts; do
  printf '%-34s ' "$t" >> "$OUT"
  timeout 200 node "项目资料-文档与开发测试/_devtest/$t.js" >/dev/null 2>&1 \
    && echo "PASS" >> "$OUT" || echo "FAIL" >> "$OUT"
done
printf '%-34s ' "test_r2_visual_css" >> "$OUT"
timeout 200 node "项目资料-文档与开发测试/_devtest/test_r2_visual_css.mjs" >/dev/null 2>&1 \
  && echo "PASS" >> "$OUT" || echo "FAIL" >> "$OUT"

echo "" >> "$OUT"
echo "=== Node（需要 mock 服务）===" >> "$OUT"
P=8866
python "项目资料-文档与开发测试/_devtest/serve.py" $P >/dev/null 2>&1 &
SRV=$!
# ⚠️ test_cards_layout_matrix.js 里写死了 8811（它自己不起服务），
#   所以这里也要在 8811 起一份，否则会 ECONNREFUSED 假 FAIL。
python "项目资料-文档与开发测试/_devtest/serve.py" 8811 >/dev/null 2>&1 &
SRV2=$!
trap 'kill '"$SRV"' '"$SRV2"' 2>/dev/null' EXIT
for i in $(seq 1 40); do
  python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:$P/static/css/base.css',timeout=1).read(16)" 2>/dev/null && break
  sleep 0.3
done
# 8811 也要等到能连（matrix 写死了这个端口）
for i in $(seq 1 40); do
  python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8811/static/css/base.css',timeout=1).read(16)" 2>/dev/null && break
  sleep 0.3
done
printf '%-34s ' "test_cards_layout_matrix" >> "$OUT"
timeout 300 node "项目资料-文档与开发测试/_devtest/test_cards_layout_matrix.js" >/dev/null 2>&1 \
  && echo "PASS" >> "$OUT" || echo "FAIL" >> "$OUT"
for t in settings_probe_jsdom test_input_menu_click test_unsaved_dialog_removed; do
  printf '%-34s ' "$t" >> "$OUT"
  GCP_PORT=$P timeout 400 node "项目资料-文档与开发测试/_devtest/$t.mjs" >/dev/null 2>&1 \
    && echo "PASS" >> "$OUT" || echo "FAIL(见对应报告)" >> "$OUT"
done
printf '%-34s ' "test_ai_jsdom(11 用例)" >> "$OUT"
GCP_PORT=$P timeout 900 node "项目资料-文档与开发测试/_devtest/test_ai_jsdom.mjs" > "$R/ai_jsdom_final.txt" 2>&1 \
  && echo "PASS" >> "$OUT" || echo "FAIL" >> "$OUT"
printf '%-34s ' "test_ai_version_scroll" >> "$OUT"
GCP_PORT=$P timeout 400 node "项目资料-文档与开发测试/_devtest/test_ai_version_scroll.mjs" > "$R/version_scroll_final.txt" 2>&1 \
  && echo "PASS" >> "$OUT" || echo "FAIL" >> "$OUT"
printf '%-34s ' "test_i18n_english_leak" >> "$OUT"
GCP_PORT=$P I18N_LANG=English timeout 600 node "项目资料-文档与开发测试/_devtest/test_i18n_english_leak.mjs" > "$R/i18n_leak_final.txt" 2>&1 \
  && echo "PASS(见报告)" >> "$OUT" || echo "FAIL/ABORT" >> "$OUT"

echo "" >> "$OUT"
echo "SWEEP_DONE" >> "$OUT"
