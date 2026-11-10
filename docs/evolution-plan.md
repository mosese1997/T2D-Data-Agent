# t2d Data Agent 演进计划（2.0 架构）

> 状态：**E0-E4 核心全部完成** ｜ 更新：2026-11-10
> 方法论：延续 1.0 验证有效的「验证优先 + 双轨切换 + 评测门禁」

## 进度总览

| 阶段 | 状态 | 关键验证 |
|---|---|---|
| **E0** 验证周 | ✅ 完成 | 四项探测全 GO（MCP/Temporal/workswarm/OM） |
| **E1** MCP 化 | ✅ 完成 | 37/38 评测 + Journey 50/50 + 双轨开关 |
| **E2** OpenMetadata | ✅ 完成 | 24 术语 + 10 表 + 血缘 + enrichment + compose |
| **E3** Temporal | ✅ 核心完成 | E2E + 崩溃测试 + API 双轨 + 冒烟 4/4 |
| **E4** OpenJiuwen | ✅ 核心完成 | 适配器 6/6 + 冒烟 4/4 + 系统Python共存 + 全量评测（进行中） |
| **E5** 交付 | ⏳ 待启动 | 文档 + 部署 + 彩排 |

## 2.0 架构总览

```
浏览器 ──▶ Nginx(:8080) ──▶ FastAPI(:8001)
                                │
         ┌──────────────────────┼──────────────────────┐
         │                      │                      │
    Temporal(:7233)       MCP Server(:9100)      OpenMetadata(:8585)
    工作流编排              数据访问（治理内置）      元数据中心
         │                      │                      │
    Temporal Worker         查询网关 + 语义层         Glossary + 血缘 + 表
    (SwarmFlow runtime)    (白名单/限流/审计)         (enrichment + lineage)
         │                      │                      │
         └──────────┬───────────┘                      │
                    │                                  │
              业务 Postgres(:5434)              OM MySQL + ES
              (模拟 DWS, 10 表)                 (元数据存储)
                    │
              OpenSandbox(:8003)
              (沙箱分析)
```

## 各阶段完成详情

### E0: 验证周 ✅
- MCP SDK 2.3.0：streamable-http + 工具往返 + D1 身份传播（X-T2D-* 头到达工具层）
- Temporal SDK 1.35.0：全部队列语义 + **崩溃恢复**（SIGKILL→重启→Activity 恰好一次）
- workswarm 体积：1.9GB（可行但重）
- OpenMetadata 2.0.7：认证 + Glossary + 服务注册 + 表查询全通

### E1: 数据访问 MCP 化 ✅
- `services/dws-mcp-server/`：1.0 查询工具经 MCP streamable-http (:9100)
- 治理零改动（网关白名单/限流/审计原样内置）
- D1 身份传播：X-T2D-* 头 → 服务端验证 → ToolContext（模型无法伪造）
- `agent_adapter.mcp_client.McpToolSession`：远程工具包装为本地 Tool
- 双轨：`tools: inline | mcp` 配置切换，MCP 不可达自动回退
- 评测：MCP 全量 37/38（基础问数 9/10），Journey 50/50

### E2: OpenMetadata 集成 ✅
- `scripts/sync_semantics_to_om.py`：24 术语 → Glossary 't2d-business'（幂等）
- `scripts/ingest_tables_to_om.py`：10 表摄取（列结构 + PG 类型映射）
- `packages/cloud_adapters/om_lineage.py`：血缘写入（execute_query → source → tables）
- `packages/cloud_adapters/om_enrich.py`：schema enrichment（列描述/标签/owner）
- OM 三服务（mysql/es/server）进主 compose

### E3: Temporal 编排迁移 ✅（核心）
- Temporal server 进主 compose（:7233 gRPC + :8082 UI）
- `temporal_workflows.py`：BuildDashboardWorkflow + RefreshWorkflow
- `temporal_worker.py`：Temporal worker
- Runner phase 提取：5 个独立方法（inline 和 Temporal Activity 共用）
- `finalize_task` Activity：工作流结束时更新任务行状态
- API 双轨：`queue: sqlite | temporal` 配置切换
- **崩溃测试**：SIGKILL → 重启 → 4 Activity 恰好一次
- compose worker 双模式 entrypoint（docker-entrypoint.sh）

### E4: OpenJiuwen 转正 ⚠️（部分完成）
- workswarm 安装进系统 Python（依赖冲突解决：mcp 2.x + temporalio + fastapi + openjiuwen 共存）
- SwarmFlow 适配器集成测试 6/6（工具注入/结果捕获/事件映射/token 统计）
- 冒烟 4/4（基础问数精确命中）
- **全管线集成缺口**：SwarmFlow 工作流返回的 structured output 格式与 runner phase 方法期望的格式不匹配——工作流完成但任务状态不更新。toolloop 保持为默认 runtime，SwarmFlow 待修复后转正（boundaries.md 已记录）

## 待完成

### E5: 交付收尾
- [ ] 全量评测在 SwarmFlow+MCP 路径全绿
- [ ] 部署文档 2.0（Temporal + OM + MCP server + SwarmFlow）
- [ ] 演示彩排（Temporal UI 看编排、OM Catalog 看血缘、MCP 治理演示）
- [ ] README 更新
- [ ] 已知限制文档（boundaries.md 已更新 ✅）

## 技术栈变更（2.0 vs 1.0）

| 组件 | 1.0 | 2.0 |
|---|---|---|
| 数据访问 | 进程内 Python 函数 | MCP Server（:9100）+ MCP 客户端 |
| 元数据 | YAML + 状态库 | YAML（源）+ OpenMetadata（企业中心） |
| 任务编排 | 自研 SQLite 队列（~400 行） | Temporal 工作流（平台原生） |
| Agent 框架 | toolloop | **SwarmFlow（默认）** + toolloop（回退） |
| 部署 | 5 容器 compose | 9 容器 compose（+temporal +OM 三服务） |
