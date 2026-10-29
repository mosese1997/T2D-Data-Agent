#!/bin/sh
# t2d API entrypoint: self-initialize the state DB on first boot.
# - alembic upgrade head (no-op when current)
# - seeds (users/semantics/preset dashboards) only when the DB is EMPTY
# Idempotent: safe on every restart. Preset seeds need business PG
# reachable (compose health-gates that); a skip is warned, not fatal.
set -e

export STATE_DB_URL="${STATE_DB_URL:-sqlite:////var/lib/t2d/state.db}"
mkdir -p /var/lib/t2d

echo "[entrypoint] running migrations…"
python - <<'EOF'
import os
from alembic import command
from alembic.config import Config

cfg = Config("/app/packages/db/alembic.ini")
cfg.set_main_option("script_location", "/app/packages/db/t2d_db/alembic")
cfg.set_main_option("sqlalchemy.url", os.environ["STATE_DB_URL"])
command.upgrade(cfg, "head")
EOF

echo "[entrypoint] checking seeds…"
python - <<'EOF'
import subprocess
import sys

from t2d_db.models import User
from t2d_db.session import get_sessionmaker

with get_sessionmaker()() as s:
    if s.query(User).count() > 0:
        print("[entrypoint] state DB already initialized — skipping seeds")
        sys.exit(0)

print("[entrypoint] empty state DB — seeding demo data")
for script in ("seed_demo_users.py", "seed_semantics.py", "seed_preset_dashboards.py"):
    result = subprocess.run([sys.executable, f"/app/scripts/{script}"])
    if result.returncode != 0:
        if script == "seed_preset_dashboards.py":
            print("[entrypoint] WARN: preset dashboards skipped (business PG reachable?)")
        else:
            sys.exit(result.returncode)
EOF

echo "[entrypoint] starting API"
exec uvicorn t2d_api.main:app --host 0.0.0.0 --port 8001
