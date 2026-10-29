#!/usr/bin/env bash
# Phase 6 acceptance: deployment reproducibility (task book §17 阶段6).
# Stages:
#   1. compose 配置有效性 + nginx 配置语法
#   2. .env.example 完整性（无真实密钥）
#   3. 文档交付物存在（deployment/runbook/architecture/requirements/boundaries）
#   4. --full：实际构建并起全栈，公网入口 :8080 healthz 200 + 演示冒烟
# 用法: bash scripts/verify_phase6.sh [--full]
set -uo pipefail
cd "$(dirname "$0")/.."

FULL=0
[ "${1:-}" = "--full" ] && FULL=1

PASS=0; FAIL=0
ok()   { echo "  ✅ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ❌ $1"; FAIL=$((FAIL+1)); }

echo "═══ 阶段 6 验收 verify_phase6 ═══"

echo "[1] Compose 与 Nginx 配置"
if docker compose -f infra/compose/docker-compose.yml config >/dev/null 2>&1; then
  ok "docker compose config 有效"
else
  bad "docker compose config 无效"
fi
if [ -f apps/web/dist/index.html ]; then
  ok "前端构建产物存在（apps/web/dist）"
else
  bad "前端未构建（先 cd apps/web && npm run build）"
fi

echo "[2] 环境配置模板"
if grep -q "MODEL_API_KEY=change-me" .env.example && ! grep -qE "sk-[A-Za-z0-9]{20}" .env.example; then
  ok ".env.example 无真实密钥"
else
  bad ".env.example 含疑似真实密钥"
fi
for key in APP_SECRET_KEY MODEL_API_BASE DWS_HOST CSS_HOST OBS_ACCESS_KEY MYSQL_URL SANDBOX_API_KEY TASK_ANALYSIS_CONCURRENCY; do
  grep -q "$key" .env.example || bad ".env.example 缺 $key"
done
ok "环境键名齐全（APP/MODEL/DWS/CSS/OBS/MYSQL/SANDBOX/TASK_LIMITS）"

echo "[3] 文档交付物"
for doc in docs/deployment.md docs/architecture.md docs/requirements.md \
           packages/agent_adapter/agent_adapter/boundaries.md; do
  [ -f "$doc" ] && ok "$doc" || bad "缺 $doc"
done
# runbook 摘要在 deployment.md §五
grep -q "故障处置" docs/deployment.md && ok "runbook（deployment.md §五）" || bad "缺 runbook"

echo "[4] 每阶段验收脚本与实施记录"
for f in scripts/verify_phase1.py scripts/verify_phase2.py scripts/verify_phase3.py \
         scripts/verify_phase4.py scripts/verify_phase5.py; do
  [ -f "$f" ] && ok "$f" || bad "缺 $f"
done
ls docs/phase-notes/*.md >/dev/null 2>&1 && ok "phase-notes 实施记录" || bad "缺实施记录"

if [ "$FULL" -eq 1 ]; then
  echo "[5] 全栈构建与公网入口（--full）"
  if docker compose -f infra/compose/docker-compose.yml up -d --build > var/compose-up.log 2>&1; then
    ok "docker compose up -d --build"
  else
    bad "compose 构建失败（见 var/compose-up.log）"
  fi
  for i in $(seq 1 60); do
    curl -sf http://127.0.0.1:8080/api/healthz >/dev/null 2>&1 && break
    sleep 2
  done
  if curl -sf http://127.0.0.1:8080/api/healthz >/dev/null; then
    ok "公网入口 :8080/api/healthz 200"
    curl -s http://127.0.0.1:8080/api/healthz | python3 -c "import sys,json; d=json.load(sys.stdin); print('    demo_mode:', d['demo_mode'], '| checks:', d['checks'])"
  else
    bad ":8080 healthz 不可达"
  fi
  if curl -sf http://127.0.0.1:8080/ >/dev/null; then
    ok "前端经 Nginx 可访问"
  else
    bad "前端经 Nginx 不可达"
  fi
  # SSE 经 Nginx（缓冲关闭验证）：取一个历史任务的事件流头部
  TOKEN=$(curl -s -X POST http://127.0.0.1:8080/api/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"admin-demo-2026"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])" 2>/dev/null)
  TASK_ID=$(curl -s "http://127.0.0.1:8080/api/admin/runs?limit=1" -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['task_id'])" 2>/dev/null)
  if [ -n "${TASK_ID:-}" ] && timeout 5 curl -s -N "http://127.0.0.1:8080/api/tasks/$TASK_ID/events" -H "Authorization: Bearer $TOKEN" | head -c 20 | grep -q "id:"; then
    ok "SSE 经 Nginx 无缓冲"
  else
    bad "SSE 经 Nginx 无输出（检查 events location）"
  fi
else
  echo "[5] 跳过全栈构建（--full 启用）"
fi

echo ""
echo "═══ 结果：$PASS 通过 / $FAIL 失败 ═══"
[ "$FAIL" -eq 0 ] && echo "✅ 阶段 6 验收通过" || { echo "❌ 阶段 6 验收未通过"; exit 1; }
