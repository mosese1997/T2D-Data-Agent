# t2d Data Agent 演进计划（2.0 架构）

> 状态：**E1 完成、E2 大半完成、E3 核心已通** ｜ 更新：2026-11-10
> 方法论：延续 1.0 验证有效的「验证优先 + 双轨切换 + 评测门禁」

## 进度总览

| 阶段 | 状态 | 关键验证 |
|---|---|---|
| **E0** 验证周 | ✅ 完成 | 四项探测全 GO（MCP/Temporal/workswarm/OM） |
| **E1** MCP 化 | ✅ 完成 | 37/38 评测 + Journey 50/50 + 双轨开关 |
| **E2** OpenMetadata | ✅ 大半完成 | 24 术语 + 10 表 + 血缘 + enrichment + compose |
| **E3** Temporal | 🔄 核心已通 | E2E ✅ + 崩溃测试 ✅ + API 双轨 ✅ + 冒烟 4/4 |
| **E4** OpenJiuwen | ⏳ 待启动 | 依赖 E1+E3 |
| **E5** 交付 | ⏳ | 依赖全部 |

## 已完成详情

### E1: 数据访问 MCP 化 ✅
- `services/dws-mcp-server/`：1.0 查询工具经 MCP streamable-http (:9100)
- 治理零改动（网关白名单/限流/审计原样内置）
- D1 身份传播：X-T2D-* 头 → 服务端验证 → ToolContext（模型无法伪造）
- `agent_adapter.mcp_client.McpToolSession`：远程工具包装为本地 Tool 对象
- 双轨：`tools: inline | mcp` 配置切换，MCP 不可达自动回退
- 评测：MCP 全量 37/38（基础问数 10/10），Journey 50/50

### E2: OpenMetadata ✅（大半完成）
- `scripts/sync_semantics_to_om.py`：24 术语 → Glossary 't2d-business'（幂等）
- `scripts/ingest_tables_to_om.py`：10 表摄取（列结构 + PG 类型映射）
- `packages/cloud_adapters/om_lineage.py`：血缘写入（execute_query → source → tables）
- `packages/cloud_adapters/om_enrich.py`：schema enrichment（列描述/标签/owner）
- OM 三服务（mysql/es/server）进主 compose
- 待做：Wiki 页对接 OM Catalog（前端改动）

### E3: Temporal 编排迁移 🔄（核心已通）
- Temporal server 进主 compose（:7233 gRPC + :8082 UI）
- `temporal_workflows.py`：BuildDashboardWorkflow（intent→[clarify signal]→query→design/analysis→[apply signal]）+ RefreshWorkflow
- `temporal_worker.py`：Temporal worker（替代 SQLite 队列轮询）
- Runner phase 提取：5 个独立方法（inline 和 Temporal Activity 共用）
- `finalize_task` Activity：工作流结束时更新任务行状态
- API 双轨：`queue: sqlite | temporal` 配置切换
- **崩溃测试**：SIGKILL → 重启 → 4 Activity 恰好一次（事件溯源原生）
- **E2E**：POST message → workflow → succeeded → 答案正确
- **冒烟**：4/4（基础问数精确命中）
- 待做：全量评测、compose worker 支持 Temporal 模式

## 待完成

### E3 收尾
- [ ] Temporal 全量 38 用例评测
- [ ] compose worker 支持 queue: temporal（Dockerfile/entrypoint）
- [ ] 自研队列归档（attic/）

### E4: OpenJiuwen 转正（~1-2 周）
- [ ] workswarm 进 worker 镜像（独立 venv，~1.9GB）
- [ ] SwarmFlow 设默认 runtime
- [ ] MCP 工具经 DeepAgentSpec.mcps 挂载（E0 探测已验证）
- [ ] 全部评测在 SwarmFlow 运行时全绿

### E5: 交付收尾（~1 周）
- [ ] 部署文档 2.0（Temporal + OM + MCP server）
- [ ] boundaries.md 全量重写
- [ ] 演示彩排（新增：Temporal UI 看编排、OM Catalog 看血缘）
- [ ] README 更新

## 技术栈变更（2.0 vs 1.0）

| 组件 | 1.0 | 2.0 |
|---|---|---|
| 数据访问 | 进程内 Python 函数 | MCP Server（:9100）+ MCP 客户端 |
| 元数据 | YAML + 状态库 | YAML（源）+ OpenMetadata（企业中心） |
| 任务编排 | 自研 SQLite 队列（~400 行） | Temporal 工作流（平台原生） |
| Agent 框架 | toolloop | toolloop（默认）+ SwarmFlow（待转正） |
| 部署 | 5 容器 compose | 9 容器 compose（+temporal +OM 三服务） |
