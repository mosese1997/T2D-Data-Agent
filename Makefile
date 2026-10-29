.PHONY: bootstrap install migrate data seed up down restart logs test verify clean

PY := python3
PIP := $(PY) -m pip
PACKAGES := packages/db packages/agent_adapter packages/semantic packages/query_gateway packages/dashboard_schema packages/cloud_adapters
SERVICES := services/api services/worker

bootstrap: install migrate data seed
	@echo "✅ bootstrap 完成。运行 make up 启动全栈。"

install:
	@for p in $(PACKAGES) $(SERVICES); do $(PIP) install -e $$p -q || exit 1; done
	@cd apps/web && npm install --silent

migrate:
	@cd packages/db && alembic upgrade head

data: gen-data import-data

gen-data:
	@$(PY) scripts/gen_synthetic_data.py --seed 42 --orders 300000 --out data/synthetic

import-data:
	@$(PY) scripts/import_synthetic_data.py --dir data/synthetic

seed:
	@$(PY) scripts/seed_demo_users.py
	@$(PY) scripts/seed_semantics.py
	@$(PY) scripts/seed_preset_dashboards.py

up:
	@cd infra/compose && docker compose up -d

down:
	@cd infra/compose && docker compose down

restart:
	@cd infra/compose && docker compose restart

logs:
	@cd infra/compose && docker compose logs -f --tail=100

test:
	@$(PY) -m pytest tests/ -v

verify:
	@$(PY) scripts/verify_phase1.py

clean:
	@rm -rf data/synthetic var/*.db* var/files logs
	@echo "✅ 已清理生成数据与运行时产物（保留代码与配置）"
