#!/usr/bin/env bash
# 发布到 GitHub（创建仓库 + 推送 + 开启 Pages）
#
# 用法:
#   GH_TOKEN=ghp_xxx ./publish.sh <github用户名> [仓库名]
#
# 说明:
#   - 仓库名默认 ashare-daily-review
#   - 推送后自动开启 GitHub Pages（走 GitHub Actions 或 main 分支根目录）
#   - 站点为纯静态，Pages 直接从仓库根目录提供服务
set -euo pipefail
cd "$(dirname "$0")"

OWNER="${1:-}"
REPO="${2:-ashare-daily-review}"
TOKEN="${GH_TOKEN:-}"

if [ -z "$OWNER" ]; then
  echo "用法: GH_TOKEN=ghp_xxx ./publish.sh <github用户名> [仓库名]"
  exit 1
fi
if [ -z "$TOKEN" ]; then
  echo "错误: 未提供 GH_TOKEN 环境变量"
  echo "  请到 https://github.com/settings/tokens 创建 Classic token，勾选 repo 权限"
  exit 1
fi

API="https://api.github.com"
AUTH=(-H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json")

echo "=============================================="
echo " 发布到 GitHub: $OWNER/$REPO"
echo "=============================================="

# 1) 校验 token 与账号
echo
echo "[1/5] 校验 token"
ME=$(curl -s "${AUTH[@]}" "$API/user" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('login',''))" 2>/dev/null || true)
if [ -z "$ME" ]; then
  echo "  ✗ token 无效或无权限"
  exit 1
fi
echo "  ✓ 已认证为: $ME"

# 2) 创建仓库（已存在则跳过）
echo
echo "[2/5] 创建仓库"
CODE=$(curl -s -o /tmp/gh_create.json -w "%{http_code}" "${AUTH[@]}" -X POST "$API/user/repos" \
  -d "{\"name\":\"$REPO\",\"description\":\"A股每日复盘 · 静态归档站\",\"private\":false,\"auto_init\":false}")
if [ "$CODE" = "201" ]; then
  echo "  ✓ 仓库已创建"
elif [ "$CODE" = "422" ]; then
  echo "  · 仓库已存在，继续使用"
else
  echo "  ! 创建返回 HTTP $CODE"
  head -c 300 /tmp/gh_create.json; echo
fi

# 3) 推送
echo
echo "[3/5] 推送代码"
git remote remove origin 2>/dev/null || true
git remote add origin "https://${OWNER}:${TOKEN}@github.com/${OWNER}/${REPO}.git"
git push -u origin main --force
echo "  ✓ 已推送"

# 4) 开启 Pages（用 Actions 工作流部署）
echo
echo "[4/5] 开启 GitHub Pages"
CODE=$(curl -s -o /tmp/gh_pages.json -w "%{http_code}" "${AUTH[@]}" -X POST "$API/repos/$OWNER/$REPO/pages" \
  -d '{"build_type":"workflow"}' 2>/dev/null || echo "000")
if [ "$CODE" = "201" ] || [ "$CODE" = "409" ]; then
  echo "  ✓ Pages 已启用（build_type=workflow）"
else
  echo "  · Pages 返回 HTTP $CODE —— 可能需要在仓库 Settings → Pages 手动选择 Source: GitHub Actions"
  head -c 300 /tmp/gh_pages.json 2>/dev/null; echo
fi

# 5) 触发工作流（若未自动触发）
echo
echo "[5/5] 触发部署工作流"
curl -s -o /dev/null "${AUTH[@]}" -X POST "$API/repos/$OWNER/$REPO/actions/workflows/deploy-pages.yml/dispatches" \
  -d '{"ref":"main"}' || true
echo "  ✓ 已触发（若失败，push 本身也会触发）"

echo
echo "=============================================="
echo " 完成！"
echo
echo " 仓库:  https://github.com/$OWNER/$REPO"
echo " 站点:  https://$OWNER.github.io/$REPO/"
echo
echo " 首次部署约需 1-2 分钟，可在 Actions 页查看进度："
echo " https://github.com/$OWNER/$REPO/actions"
echo "=============================================="
