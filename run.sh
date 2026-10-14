#!/usr/bin/env bash
# A股每日复盘 · 一键流水线
#
#   ./run.sh                 # 最近交易日
#   ./run.sh 2026-10-15      # 指定交易日
#
# 步骤：采集 → (板块缺失则提示走 MCP) → 构建 → 校验
set -uo pipefail
cd "$(dirname "$0")"

DATE="${1:-}"
if [ -n "$DATE" ]; then
  ARG="$DATE"
else
  ARG=""
fi

echo "=============================================="
echo " A股每日复盘 · 生成流程"
echo "=============================================="

echo
echo "[1/3] 采集数据"
python3 scripts/collect.py ${ARG:+"$ARG"} || exit 1

# 解析实际交易日
ACTUAL="$DATE"
if [ -z "$ACTUAL" ]; then
  ACTUAL=$(ls -t data/*.json 2>/dev/null | grep -E '[0-9]{4}-[0-9]{2}-[0-9]{2}\.json$' | head -1 | sed 's|data/||;s|\.json||')
fi
echo "     交易日 = $ACTUAL"

# 若板块为空，尝试本地库补齐
if python3 -c "
import json,sys
d=json.load(open('data/$ACTUAL.json'))
sys.exit(0 if d.get('industry_top') else 1)
" 2>/dev/null; then
  :
else
  echo
  echo "[2/3] 板块数据缺失 —— 尝试从东财本地库补齐"
  python3 scripts/sector_from_db.py "$ACTUAL" --merge "data/$ACTUAL.json" || {
    echo "     !! 本地库也没有该日数据。请调用 MCP 的 get_sector_list，"
    echo "        再用 scripts/import_mcp.py + merge_mcp.py 合并。"
  }
fi

# 检查分析段
if [ ! -f "data/$ACTUAL.analysis.json" ]; then
  echo
  echo "     !! 缺少 data/$ACTUAL.analysis.json"
  echo "        第 1/9/10/11 章将为空白。可先复制其他日期的文件作为模板。"
fi

echo
echo "[3/3] 构建页面"
python3 scripts/build.py "$ACTUAL" || exit 1

echo
echo "=============================================="
echo " 完成。产物："
echo "   index.html"
echo "   reviews/$ACTUAL.html"
echo
echo " 本地预览： python3 -m http.server 8099"
echo "           → http://127.0.0.1:8099"
echo "=============================================="
