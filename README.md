# t2d — Agentic Talk to Data Demo

自然语言创建、修改、分享和发布 Dashboard 的数据产品 Demo，展示 Agent 的语义理解、任务编排、工具调用、子 Agent 协作、沙箱分析、运行追踪与评测能力。业务域：订单、GMV、履约。

> **产品工作名 t2d**（品牌名在 `apps/web/src/config.ts` 与 `APP_BRAND` 环境变量中，可全局替换）。

## 架构

```
浏览器 ──HTTP──▶ Nginx(:8080)
                 ├── /      静态前端 (React+TS+Vite+ECharts)
                 └── /api/  FastAPI(:8001) ──SSE──▶ 任务进度
                                │
        Agent Worker(:8002 healthz) ── 持久化任务队列(SQLite/MySQL)
                                │
        ┌───────────┬───────────┼───────────────┬─────────────┐
   agent_adapter   semantic   query_gateway   cloud_adapters  OpenSandbox
   (toolloop /     (指标/术语/ (SQL 校验/修复/  (DWS/CSS/OBS    (:8003, Docker
    SwarmFlow)      关联规则)   限流/审计)       演示/真实双实现)  Runtime 沙箱)
                                │
                     业务 Postgres(:5434, 模拟 DWS)
```

- **模型**：经 LiteLLM 代理 OpenAI 兼容端点，别名 `t2d/deepseek-v4.1-flash-1017`。
- **演示数据模式**：无华为云 DWS/CSS/OBS 凭据时自动使用本地适配器（Postgres 模拟 DWS、本地向量检索模拟 CSS、本地卷模拟 OBS），界面显著标识，不把模拟执行展示为真实云调用。

## 快速开始

```bash
cp .env.example .env          # 填入本地配置（无需任何云凭据即可跑演示模式）
make bootstrap                # 安装依赖 + 迁移 + 合成数据 + 种子
make up                       # 启动全栈 (Nginx/API/Worker/业务PG/OpenSandbox)
# 浏览器打开 http://<host>:8080  演示账号见 scripts/seed_demo_users.py
```

## 目录

| 路径 | 职责 |
|---|---|
| `apps/web/` | React+TS+Vite+ECharts 前端 |
| `services/api/` | FastAPI 主服务（REST + SSE） |
| `services/worker/` | Agent Worker（任务队列消费、三 Agent、工具执行） |
| `packages/agent_adapter/` | Agent 运行时抽象（toolloop 基线 / SwarmFlow 适配） |
| `packages/semantic/` | 语义层（指标/术语/关联规则/口径规则/检索） |
| `packages/query_gateway/` | 查询网关（校验/修复/限流/审计） |
| `packages/dashboard_schema/` | 画布 JSON Schema、Patch、diff、校验 |
| `packages/cloud_adapters/` | DWS/CSS/OBS 适配器（演示/真实双实现） |
| `packages/db/` | 状态库 ORM 模型、迁移、队列原语 |
| `config/` | 语义配置 YAML、Agent 配置 |
| `infra/` | Docker Compose、Nginx |
| `scripts/` | 引导/数据生成导入/种子/每阶段验收脚本 |
| `tests/` `evals/` | 单测/集成/端到端；40 固定评测用例 |
| `docs/` | 架构、契约、部署、运行手册、阶段实施记录 |

## 阶段验收

```bash
python scripts/verify_phase1.py   # 框架验证与契约
python scripts/verify_phase2.py   # 底座与数据
python scripts/verify_phase3.py   # 端到端建板
python scripts/verify_phase4.py   # 修改/分享/发布
python evals/runner.py --case-set full   # 分析与评测
bash scripts/verify_phase6.sh     # 云部署复现
```

详细计划见 `docs/architecture.md` 与各阶段 `docs/phase-notes/`。
