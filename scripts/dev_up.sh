#!/usr/bin/env bash
# Dev-process launcher: API (:8001) + Worker (:8002) with proper env.
# Sources the model key from the local litellm .env (never printed/stored).
set -euo pipefail
cd "$(dirname "$0")/.."

export STATE_DB_URL="${STATE_DB_URL:-sqlite:///var/state.db}"
export MODEL_API_BASE="${MODEL_API_BASE:-http://localhost:4000/v1}"
export MODEL_NAME="${MODEL_NAME:-t2d/deepseek-v4.1-flash-1017}"

# NOTE: 本地开发便利——从宿主机 litellm 栈读取模型密钥；部署环境用 .env 的 MODEL_API_KEY，不依赖此路径。
if [ -z "${MODEL_API_KEY:-}" ]; then
  if [ -f /root/litellm/.env ]; then
    MODEL_API_KEY=$(python3 - <<'PYEOF'
line = [l for l in open('/root/litellm/.env') if l.startswith('LITELLM_MASTER_KEY=')][0]
print(line.split('=', 1)[1].strip().strip('"').strip("'"))
PYEOF
)
    export MODEL_API_KEY
  else
    echo "ERROR: MODEL_API_KEY 未设置且找不到 /root/litellm/.env" >&2
    exit 1
  fi
fi

mkdir -p var
pkill -f "uvicorn t2d_api" 2>/dev/null || true
pkill -f "t2d_worker.main" 2>/dev/null || true
sleep 1

nohup python3 -m uvicorn t2d_api.main:app --host 127.0.0.1 --port 8001 > var/api.log 2>&1 &
echo "api pid $!"
nohup python3 -m t2d_worker.main > var/worker.log 2>&1 &
echo "worker pid $!"

# OpenSandbox server (probe venv; config from the phase-1 probe)
if ! curl -sf http://127.0.0.1:8003/health >/dev/null 2>&1; then
  if [ -x var/probe-venv/bin/opensandbox-server ]; then
    # setsid + full fd detachment: a plain `nohup ... &` keeps the pipe
    # open and hangs any `dev_up.sh | tail` pipeline.
    setsid bash -c 'cd var/probe-scripts && exec ../probe-venv/bin/opensandbox-server \
      --config opensandbox-config.toml > sandbox-server.log 2>&1 < /dev/null' &
    echo "sandbox server starting…"
  else
    echo "⚠️  opensandbox-server 不可用（分析功能将无法运行）"
  fi
fi

sleep 4
curl -sf http://127.0.0.1:8001/api/healthz >/dev/null && echo "✅ API :8001"
curl -sf http://127.0.0.1:8002/healthz >/dev/null && echo "✅ Worker :8002"
curl -sf http://127.0.0.1:8003/health >/dev/null && echo "✅ Sandbox :8003"
