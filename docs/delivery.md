# t2d 交付清单（2.0 架构）

> 交付日期：2026-11-10 ｜ 版本：2.0 ｜ 仓库：/root/rappi_t2d（git，main 分支）
> 1.0 交付见 git 历史（tag: v1.0）；2.0 演进计划见 docs/evolution-plan.md

## 一、可运行源码与锁定依赖 ✅

- 单仓库 14 个包/服务（新增 services/dws-mcp-server、temporal_workflows/worker、om_lineage/enrich）
- Python 依赖锁定（pyproject 精确版本区间）；前端锁定（react 18.3.1 / vite 5.4.11 / echarts 5.5.1 / ts 5.6.3）
- workswarm + mcp 2.x + temporalio + fastapi + openjiuwen 系统Python 共存（依赖冲突已解决并记录）

## 二、容器镜像构建与部署配置 ✅

- services/{api,worker,dws-mcp-server}/Dockerfile（多阶段 slim）
- infra/sandbox/Dockerfile（OpenSandbox server）
- infra/nginx/Dockerfile + nginx.conf（SSE 专用 location，动态 DNS 解析，三入口 80/8080/8443）
- infra/compose/docker-compose.yml：9 服务（business-pg / api / worker / sandbox-server / nginx / temporal / openmetadata-mysql / openmetadata-es / openmetadata-server）
- worker docker-entrypoint.sh：按 queue 模式自动启动 SQLite 队列 worker 或 Temporal worker
- api docker-entrypoint.sh：首次启动自动迁移+种子

## 三、云资源实际清单及规格

- **当前**：无（演示模式——本地适配器，界面黄条显著标识）
- **待提供凭据**：DWS / CSS / OBS / RDS MySQL 8.0（清单见 deployment.md §三）
- 适配器双实现就绪：凭据到位 → 改 .env → 实测验证 → 切换（代码零改动）

## 四、数据、语义、Agent 配置初始化脚本 ✅

- scripts/gen_synthetic_data.py（seed=42 可复现；币种定价按汇率放大）
- scripts/import_synthetic_data.py（psycopg3 流式 COPY）
- scripts/seed_demo_users.py / seed_semantics.py / seed_preset_dashboards.py
- **scripts/sync_semantics_to_om.py**（2.0 新增：语义层→OM Glossary 同步，24 术语）
- **scripts/ingest_tables_to_om.py**（2.0 新增：业务表→OM 摄取，10 表）
- config/semantics（13 指标/11 术语/10 关联规则/11 数据集，semantic_version=2）
- config/agent/agent_config.yaml（runtime/tools/queue 三开关）

## 五、评测集及结果 ✅

| 路径 | 评测 | 基础问数 |
|---|---|---|
| 1.0（inline + sqlite） | 38/38 | 10/10 (100%) |
| E1（MCP 工具 + sqlite） | 37/38 | 9/10 (90%) |
| E3（MCP + temporal） | 冒烟 4/4 | 1/1 |
| E4（SwarmFlow + MCP） | 冒烟 4/4 + 全量（进行中） | 1/1 |

- 评测方法论：判定器比较**结果值**（与独立 reference SQL 对账），从不比较 SQL 字符串
- 50 步用户旅程回归（E1 MCP 路径 50/50）

## 六、文档 ✅

- docs/architecture.md（1.0 架构详解）
- docs/deployment.md（部署拓扑/云接入/备份/故障处置/演示彩排）
- docs/evolution-plan.md（2.0 演进计划与进度）
- docs/requirements.md（需求摘要）
- docs/delivery.md（本文档）
- docs/phase-notes/（1.0 六阶段 + E0 四项探测报告）
- packages/agent_adapter/agent_adapter/boundaries.md（2.0 能力矩阵/已知限制/事件映射/回退条件）

## 七、已知限制与未实现项（诚实声明）

1. **云服务未接**：DWS/CSS/OBS/RDS 凭据未提供，走演示适配器
2. **SwarmFlow**：已转正默认 runtime，但 workswarm 0.2.x 是早期版本，API 可能变动（boundaries.md 记录）
3. **HTTP 无 TLS**：演示环境明文（任务书边界）
4. **沙箱**：容器级隔离，非虚拟机级；禁网是 opt-in（适配层强制传 deny）
5. **OM Wiki 页对接**：前端改动待完成（OM API 已就绪）
6. **Temporal 生产形态**：当前用 dev server（内存库）；生产需 auto-setup + PG
7. **评测 runner Temporal 模式**：eval runner 已支持 temporal queue，但全量评测尚未在 temporal 路径完成

## 八、三套可复现演示脚本

1. **订单/GMV 对话建板**："最近7天各国家GMV趋势，做成看板" → Agent 查询→设计→预览→Apply→发布
2. **履约多 Source 看板**：预置"履约监控"看板 → 局部修改 → 刷新
3. **下降贡献分析**："分析上周相比上上周GMV变化，各国家贡献" → 沙箱分解 → 非因果结论 → Trace 查看

## 九、2.0 新增交付物

| 组件 | 位置 | 说明 |
|---|---|---|
| **MCP Server** | services/dws-mcp-server/ | 数据访问协议化（治理内置，D1 身份传播） |
| **MCP 客户端** | packages/agent_adapter/mcp_client.py | 远程工具包装为本地 Tool 对象 |
| **Temporal 工作流** | services/worker/temporal_workflows.py | runner 状态机→Workflow/Activities |
| **Temporal Worker** | services/worker/temporal_worker.py | 替代 SQLite 队列轮询 |
| **OM 血缘** | packages/cloud_adapters/om_lineage.py | execute_query→source→tables |
| **OM Enrichment** | packages/cloud_adapters/om_enrich.py | 列描述/标签/owner→get_authorized_schema |
| **OM 同步脚本** | scripts/sync_semantics_to_om.py | YAML→Glossary（幂等） |
| **OM 摄取脚本** | scripts/ingest_tables_to_om.py | 业务表→OM（列结构） |
| **Runner Phase 提取** | services/worker/runner.py | 5 个独立方法（inline 和 Temporal 共用） |
| **双模式 Worker 入口** | services/worker/docker-entrypoint.sh | 按 queue 模式自动启动 |
