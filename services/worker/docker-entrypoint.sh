#!/bin/bash
# t2d Worker entrypoint: starts the appropriate worker based on queue mode.
# queue: sqlite (1.0 default) → t2d_worker.main (SQLite queue poller)
# queue: temporal (2.0)        → t2d_worker.temporal_worker (Temporal worker)
set -e

CONFIG_PATH="${AGENT_CONFIG_PATH:-/app/config/agent/agent_config.yaml}"
QUEUE_MODE=$(python3 -c "
import yaml
try:
    with open('${CONFIG_PATH}') as f:
        print((yaml.safe_load(f) or {}).get('agent', {}).get('queue', 'sqlite'))
except Exception:
    print('sqlite')
")

echo "[worker-entrypoint] queue mode: ${QUEUE_MODE}"

if [ "${QUEUE_MODE}" = "temporal" ]; then
    echo "[worker-entrypoint] starting Temporal worker..."
    exec python3 -m t2d_worker.temporal_worker
else
    echo "[worker-entrypoint] starting SQLite queue worker..."
    exec python3 -m t2d_worker.main
fi
