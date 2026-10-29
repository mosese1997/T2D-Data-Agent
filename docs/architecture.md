# t2d 架构说明

## 一、总览

```
┌─ 浏览器 ────────────────────────────────────────────────┐
│  React+TS+Vite+ECharts（apps/web）                      │
│  Studio：画布 + Agent 面板（SSE 实时进度）              │
└──────────────┬──────────────────────────────────────────┘
               │ HTTP /api（Nginx :8080 唯一入口）
┌──────────────▼──────────────────────────────────────────┐
│ FastAPI（services/api :8001）                           │
│  auth / workspaces / dashboards / versions / patches    │
│  conversations / tasks(SSE) / sources / files           │
│  publish+approvals / shares / refresh / admin(trace)    │
└──────┬──────────────────────────────┬───────────────────┘
       │ 持久化任务队列（SQLite/MySQL）│
┌──────▼──────────────┐   ┌───────────▼─────────────────┐
│ Agent Worker(:8002) │   │ 状态库（26 表）             │
│  runner 三段编排     │   │  tasks/run_events/          │
│  ├ 主 Agent 意图     │   │  tool_calls/agent_runs      │
│  ├ 查询 Sub-agent    │   │  dashboards/versions/       │
│  └ 分析 Sub-agent    │   │  patches/sources/metrics …  │
│  9 工具（服务端注入  │   └─────────────────────────────┘
│  ToolContext）       │
└──┬─────────┬────────┘
   │         │
┌──▼──────┐ ┌─▼──────────────┐   ┌──────────────────────┐
│ 查询网关 │ │ OpenSandbox    │   │ 业务 Postgres(:5434) │
│ sqlglot  │ │ (:8003)        │   │ （模拟 DWS）         │
│ 校验/限流│ │ 1vCPU/1GiB     │   │ 10 表 30 万订单      │
│ 修复≤2   │ │ 禁网/无凭据    │   └──────────────────────┘
│ 审计     │ │ destroy 清理   │
└──┬──────┘ └────────────────┘
   │
┌──▼───────────────────┐    ┌───────────────────────────┐
│ LiteLLM(:4000)        │    │ 语义层（YAML 权威）       │
│ OpenAI 兼容路径       │    │ 13 指标/11 术语/9 关联    │
│ t2d/deepseek-v4.1-    │    │ 口径规则（自然周/排除今日  │
│ flash-1017            │    │ /汇率回退/零分母/去重）   │
└───────────────────────┘    └───────────────────────────┘
```

## 二、一次建板的完整路径（阶段 3 验收路径）

1. 用户消息 → `conversations/{id}/messages`：消息落库 + 任务入队（幂等键）。
2. Worker 原子领取（乐观 UPDATE，租约 30s/心跳 10s）→ runner。
3. **意图段**（主 Agent）：search_semantics → 结构化意图；歧义 → waiting_for_user（/answer 回答后重排队）。
4. **查询段**（查询 Sub-agent）：get_semantic_definition → get_authorized_schema → validate_query →（修复≤2）→ execute_query：网关校验（单 SELECT/白名单/函数黑名单/LIMIT 钳制/60s 超时/只读）→ 业务库 → 结果落 FileStore（sha256）→ Source 行。
5. **设计段**（主 Agent）：propose_dashboard_patch（结构/字段/权限/base_revision 校验）→ waiting_for_apply。
6. 用户 Apply：单事务重验 base_revision → 新 DashboardVersion(revision+1) → 冲突则 409+conflict。
7. 前端按 canvas 的 source_id 拉数据渲染。

**崩溃安全**：每段完成写 checkpoint；SIGKILL 后租约过期 → 重排队 → 跳过已完成段；Apply 是单事务，绝不重复应用（verify_phase3 实测）。

## 三、安全模型

- **身份**：登录（scrypt+itsdangerous token）→ 每次工具调用绑定服务端从任务行构造的 ToolContext（user/workspace/role/授权数据集）——工具 Schema 无任何身份字段，模型无法伪造。
- **数据权限**：workspace_datasets 白名单是根；网关三层约束（validator → 连接级 read_only → DB 授权）；发布副本隔离（不可变快照）；分享只授视图。
- **沙箱**（任务书 §15 全项）：无凭据注入、仅授权结果集输入、deny-all 出网（**opt-in，适配层强制显式传参**）、1vCPU/1GiB、120s 超时、TTL 兜底、finally destroy、零宿主挂载（全部实测，见 boundaries.md）。
- **审计**：成功与拒绝的查询都落 audit_logs；工具明细落 tool_calls（Trace 页可核验，无伪造记录）。

## 四、诚实性边界（演示模式）

- 无 DWS/CSS/OBS 凭据 → 本地适配器 + 界面黄条"演示数据模式"；不把模拟执行展示为真实云调用。
- swarmflow 运行时：探测 GO 但适配器未接入主链路——管理台切换接口返回 409 并说明（无假开关）。
- 贡献分析明确声明"不构成因果解释"；空结果如实说明；模型前提错误时纠正（实测）。

## 五、已知限制

见 `packages/agent_adapter/agent_adapter/boundaries.md`（运行时/沙箱能力矩阵与回退条件）与各 phase-notes 的"遗留"节。
