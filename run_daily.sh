#!/usr/bin/env bash
# ============================================================
# A股每日复盘 · 自动任务主流程
#
# 由 cron 每交易日 20:30 调用：
#   30 20 * * 1-5  /path/to/run_daily.sh >> /path/to/logs/cron.log 2>&1
#
# 流程：交易日判断 → 采集 → 构建 → 发布 GitHub → 飞书推送
# 非交易日自动跳过；任一步失败即中止并推送失败告警。
# ============================================================
set -uo pipefail
cd "$(dirname "$0")"

DATE="${1:-$(TZ=Asia/Shanghai date +%F)}"
LOGDIR="logs"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/${DATE}-auto.log"
LOCK="$LOGDIR/.run_daily.lock"

# ---------- 日志 ----------
log() { printf '[%s] %s\n' "$(TZ=Asia/Shanghai date '+%F %T')" "$*" | tee -a "$LOG"; }

# ---------- 防重入 ----------
if [ -e "$LOCK" ]; then
  LOCK_AGE=$(( $(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || echo 0) ))
  if [ "$LOCK_AGE" -lt 3600 ]; then
    log "已有任务在运行（锁文件 ${LOCK_AGE}s 前创建），本次跳过"
    exit 0
  fi
  log "发现过期锁文件（${LOCK_AGE}s），清理后继续"
  rm -f "$LOCK"
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

log "==================== 开始 $DATE ===================="

# ---------- 1. 交易日判断 ----------
if ! python3 scripts/trading_calendar.py "$DATE" >>"$LOG" 2>&1; then
  log "非交易日，跳过本次任务"
  exit 0
fi
log "✓ 交易日确认"

# ---------- 2. 采集 ----------
log "── 采集数据 ──"
if ! python3 scripts/collect.py "$DATE" >>"$LOG" 2>&1; then
  log "✗ 采集失败（collect.py 返回非 0）"
  python3 scripts/notify_feishu.py --date "$DATE" \
    --url "任务失败：数据采集异常" 2>/dev/null || true
  exit 1
fi

# 板块数据（东财数据中心，全自动）
if ! python3 scripts/collect_em_sector.py "$DATE" \
     --merge "data/${DATE}.json" >>"$LOG" 2>&1; then
  log "⚠ 板块采集失败，页面第 6/7 章将缺数据"
fi
log "✓ 采集完成"

# ---------- 3. 构建 ----------
log "── 构建页面 ──"
if ! python3 scripts/build.py --all >>"$LOG" 2>&1; then
  log "✗ 构建失败"
  exit 1
fi
[ -f "reviews/${DATE}.html" ] || { log "✗ 未生成 reviews/${DATE}.html"; exit 1; }
log "✓ 页面生成: reviews/${DATE}.html ($(stat -c%s "reviews/${DATE}.html") bytes)"

# ---------- 4. 发布 GitHub ----------
log "── 发布 GitHub ──"
# 读凭据
# shellcheck disable=SC1090
[ -f "$HOME/.ashare-review.env" ] && . "$HOME/.ashare-review.env"

if [ -z "${GH_TOKEN:-}" ]; then
  log "✗ 未找到 GH_TOKEN（应在 ~/.ashare-review.env）"
  python3 scripts/notify_feishu.py --date "$DATE" \
    --url "发布失败：缺少 GH_TOKEN" 2>/dev/null || true
  exit 1
fi

# 优先 git push（如已配置 SSH），否则走 API
PUBLISHED=0
if git remote get-url origin >/dev/null 2>&1; then
  if git add -A >>"$LOG" 2>&1 \
     && git commit -q -m "复盘 $DATE" >>"$LOG" 2>&1 \
     && timeout 120 git push -q origin main >>"$LOG" 2>&1; then
    log "✓ 已通过 git push 发布"
    PUBLISHED=1
  else
    log "· git push 不可用，改用 API 方式"
  fi
fi

if [ "$PUBLISHED" -eq 0 ]; then
  # 用 Git Data API 做单次原子提交：只产生 1 次 commit、1 次 Pages 构建。
  # 原因：逐文件提交会产生 N 次 commit，每次触发一次 Pages 构建，
  # 直接击穿 legacy 构建配额（10 次/小时），导致 "Page build failed."。
  GH_TOKEN="$GH_TOKEN" python3 scripts/git_push.py "$GH_OWNER" "$GH_REPO"     --message "复盘 $DATE" >>"$LOG" 2>&1
  API_RC=$?
  # api_push 在「核心文件已上传、个别文件被跳过」时可能仍返回非 0，
  # 故以远端实际状态做二次确认，避免误报失败。
  if GH_TOKEN="$GH_TOKEN" GH_OWNER="$GH_OWNER" GH_REPO="$GH_REPO" \
       python3 scripts/verify_published.py "$DATE" >>"$LOG" 2>&1; then
    log "✓ 已通过 GitHub API 发布（远端已确认）"
    PUBLISHED=1
  elif [ "$API_RC" -eq 0 ]; then
    log "✓ 已通过 GitHub API 发布（api_push 返回 0）"
    PUBLISHED=1
  else
    log "✗ 发布失败（git 与 API 均不可用，且远端未确认）"
    python3 scripts/notify_feishu.py --date "$DATE" \
      --url "发布失败，请检查日志" 2>/dev/null || true
    exit 1
  fi
fi

# ---------- 5. 飞书推送 ----------
log "── 飞书推送 ──"
if python3 scripts/notify_feishu.py --date "$DATE" >>"$LOG" 2>&1; then
  log "✓ 飞书推送成功"
else
  log "⚠ 飞书推送失败（但站点已发布，可稍后手动补推）"
fi

log "==================== 完成 $DATE ===================="
exit 0
