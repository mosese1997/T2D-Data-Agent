# Agent 运行时与沙箱 — 能力边界记录（2.0）

> CLAUDE.md 规则：框架不原生支持的行为在适配层补齐并记录边界；不得宣称未验证的能力已具备。
> 本文件四节：能力矩阵 / 已知限制 / 事件映射 / 回退触发条件。
> 证据来源：docs/phase-notes/ 探测报告 + 2.0 演进阶段验收记录。

## 1. 能力矩阵

### Agent 运行时（runtime: toolloop | swarmflow，config/agent/agent_config.yaml 切换）

| 能力 | toolloop（自建基线） | swarmflow（workswarm 0.2.7 / openjiuwen 0.1.19，2.0 默认） |
|---|---|---|
| 无 UI 编程运行 | ✅（即本体） | ✅ 实测：run_workflow() 纯库入口，零全局状态（contextvars），无 config.yaml/渠道进程 |
| 子 Agent 委派 | ✅ runtime.spawn() | ✅ 实测：agent(prompt, label=, phase=) 每调用一个 worker；parallel() 并发 |
| 结构化返回 | ✅ 最终回答中提取 JSON | ✅ 实测：schema= pydantic/JSONSchema，经 structured_output 工具强类型提交 |
| 自定义工具注入 | ✅ OpenAI function schema 直下 | ✅ 实测：@tool(input_params=JSON Schema, auto_extract=False) + spec.model_copy(update={"tools": [...]}) |
| MCP 工具 | ✅ McpToolSession（E1） | ✅ 实测：DeepAgentSpec.mcps + stdio server（E0 探测）；2.0 经 MCP server :9100 |
| 事件订阅→SSE | ✅ event_sink（AgentEvent） | ✅ 实测：progress_sink 收全量 WorkflowProgressEvent（13 种 kind）；WorkflowObserver.on_event 可桥 SSE |
| 取消 | ✅ 步骤边界+工具入口协作式 | ✅ 实测：AbortSignal.set("stop")→WorkflowAborted；协作式，在飞调用完成但不落 journal；建议叠加 task.cancel() |
| 预算 | ✅ Budget(max_steps/tool_calls/tokens) 本地强制 | ✅ 实测：双层 BudgetLedger（会话级+per-run），超限抛 BudgetExhausted |
| 持久化/断点续跑 | ➖ 由任务 checkpoint 承担 | ✅ 实测：journal+WAL 内容寻址，同 run_id 续跑 0 次 LLM 调用结果一致 |
| 多轮有状态会话 | ✅ messages 列表自然多轮 | ⚠️ agent_session() 源码验证完整、未端到端实测（落地时先补验证） |
| 流式 token | ❌（整段返回，SSE 只发阶段/摘要） | ❌（事件无 token 流）——t2d 不需要 |
| **系统 Python 共存** | ✅ | ✅ **2.0 实测**：workswarm + mcp 2.x + temporalio + fastapi + openjiuwen 全部共存（依赖冲突已解决） |
| **集成测试** | ✅ Journey 50/50 + 评测 37/38 | ✅ **2.0 实测**：适配器 6/6 + 冒烟 4/4 + 全量评测（进行中） |

**决策（2.0）**：SwarmFlow 已转正为默认 runtime（2026-11-10）。toolloop 保留为配置可切回的回退。

### 数据访问（E1 MCP 化）

| 能力 | 1.0 进程内 | 2.0 MCP Server (:9100) |
|---|---|---|
| 治理（白名单/黑名单/限流/审计） | ✅ 查询网关 | ✅ **同一网关原样内置**——治理随协议走，任何 MCP 客户端受同样约束 |
| 身份传播 | ✅ ToolContext 服务端注入 | ✅ X-T2D-* 请求头 → 服务端验证（用户/空间/成员/数据集从 DB 推导）→ ToolContext |
| 模型可伪造身份 | ❌ Schema 无身份字段 | ❌ 同——模型只看到类型化工具签名 |
| 越权数据集 | ✅ 网关拒绝 | ✅ 实测：mx-focus 无 refunds → object_not_authorized |
| 危险 SQL | ✅ 网关拒绝 | ✅ 实测：DELETE → not_select |
| 双轨切换 | — | ✅ tools: inline \| mcp；MCP 不可达自动回退 inline |

### 任务编排（E3 Temporal）

| 语义 | 1.0 自研队列（~400 行） | 2.0 Temporal | 验证 |
|---|---|---|---|
| 崩溃恢复 | 租约+checkpoint+回收器 | **事件溯源原生**（0 行） | ✅ SIGKILL→重启→4 Activity 恰好一次 |
| Signal 等待 | waiting_for_user 状态 | workflow.wait_condition | ✅ E0 + 工作流定义 |
| 取消 | cancel_requested 标志 | handle.cancel() | ✅ E0 |
| 幂等 | idempotency_key UNIQUE | REJECT_DUPLICATE Workflow ID | ✅ E0 |
| 任务状态 | runner._set_status | finalize_task Activity | ✅ E2E |
| 双轨切换 | — | queue: sqlite \| temporal | ✅ API + compose worker 双模式 |

### 元数据（E2 OpenMetadata 2.0.7）

| 能力 | 状态 |
|---|---|
| 语义层→Glossary 同步 | ✅ 24 术语（幂等 upsert） |
| 表元数据摄取 | ✅ 10 表（列结构 + PG 类型映射 + VARCHAR dataLength） |
| 血缘写入 | ✅ execute_query → source → tables（best-effort 不阻塞） |
| Schema enrichment | ✅ 列描述/标签/owner → get_authorized_schema（OM 挂了 schema 照常返回） |
| OM 进主 compose | ✅ mysql + ES + server 三服务 |
| Wiki 页对接 OM Catalog | ⏳ 前端改动（可后置） |

### 沙箱（OpenSandbox 1.2.0，SDK 与 Server 同版本）

| 能力 | 结论 | 证据 |
|---|---|---|
| 生命周期 create→run→write→run→read→destroy | ✅ 实测 | destroy 后 docker ps -a 零残留 |
| 资源限制 | ✅ 实测 | resource={"cpu":"1","memory":"1Gi"} → docker NanoCpus/Memory 生效；OOM kill 行为正确 |
| 命令超时与取消 | ✅ 实测 | RunCommandOpts(timeout=5) 对 sleep 60 → 6s 被杀、沙箱仍可用 |
| 网络隔离 | ⚠️ **opt-in，默认放通** | 不传 network_policy 时 pypi/宿主网关/裸 IP 全通；显式 NetworkPolicy(default_action="deny") 后全拦 |
| 文件/凭据边界 | ✅ 实测 | 沙箱间文件不互通；Mounts=[]（零宿主挂载）；零 env 注入 |
| 异常清理 | ✅ 实测 | kill -9 server 后容器存活；重启按 label 收养 |
| 鉴权 | ✅ 实测 | server.api_key + header OPEN-SANDBOX-API-KEY；无/错 key 401 |
| 冷启动延迟 | 实测数字 | 冷 5.08s / 暖 2.0–2.8s；每命令 ~1s；destroy 1.35s；TTL 最小 60s |

## 2. 已知限制（2.0）

### swarmflow
- 工具注入的 model_copy 模式是 0.2.x 未文档化内部用法，升级需回归测试
- 每个 worker 默认有一次多模态探测调用（~319 tokens）；设 enable_read_image_multimodal=False 跳过
- worker 系统提示含硬编码中文安全段
- 取消为协作式：在飞 LLM 调用会跑完（结果不落 journal，续跑重跑该节点）
- 预算两层语义：脚本内 budget.* 只读 per-run 账本；会话级由宿主设置
- parallel() 分支失败归 None 不抛：脚本需 compact()/判空
- human()/human_session() 需团队 messager 渠道——t2d 不适用
- 早期版本（0.2.x）：API 可能变动；所有接口经 agent_adapter 边界层隔离
- **系统 Python 依赖共存**：workswarm 会拉低 mcp 到 1.x——需在安装后重装 mcp>=2.3（已解决并记录）

### MCP server
- 2.x API 与大量 v1 教材不同（MCPServer 改名、2元组、headers 经 http_client 注入）
- FileRef/Source 的 task_id=0 须转 None（FK 到 tasks 表）
- ToolError 必须在 _call 层捕获返回结构化 payload（否则 SDK 包成无用的 "Error executing tool"）

### Temporal
- timeout 必须用 timedelta（int 在当前 protobuf 下抛 TypeError）
- 沙箱 runner 在本环境校验失败——用 UnsandboxedWorkflowRunner
- 同步 Activity 需显式 activity_executor=ThreadPoolExecutor(n)
- workflow 实例状态必须在 __init__ 初始化（replay 语义）
- WorkflowIDReusePolicy 在 temporalio.common（不是 client）
- 取消异常是 WorkflowFailureError 包 CancelledError（查 cause 链）

### OpenMetadata
- main 分支 compose 引用 SNAPSHOT 镜像（registry 不存在）——必须用 git tag 对应的 compose
- 不要动 auth 配置（NoopAuthorizer 会把 adminPrincipals 映射弄坏）
- 自注册用户即 admin（enableSelfSignup: true）
- glossaryTerms 创建：glossary 字段用名称字符串（不是 UUID、不是 EntityReference）
- 2.x 连接密码字段 schema 变了（服务注册先不带密码）
- column 的 description 字段在 2.x API 不被接受（列描述经 enrichment 从 OM 读回时才有）
- VARCHAR 列必须有 dataLength

### 沙箱
- **禁网是 opt-in**：默认完全放通出网。t2d 适配层每次显式传 NetworkPolicy(default_action="deny")
- 禁网沙箱内不能 pip install（依赖须预烧进镜像）
- 沙箱为容器级隔离，非虚拟机级

## 3. 事件映射（swarmflow → t2d SSE）

| swarmflow 事件 | t2d SSE | 处理 |
|---|---|---|
| workflow_started | phase.started | 直映射 |
| phase / log | phase.started / phase.completed | 直映射 |
| agent_started / agent_completed / agent_failed | tool.started / tool.completed / task.failed(子) | 直映射；tokens 记入 agent_runs |
| human_prompt / human_replied | — | **丢弃**（t2d 澄清走宿主层） |
| workflow_paused / workflow_stopped | task.cancelled / task.failed | 按 reason 区分 |
| workflow_completed / workflow_failed | task.completed / task.failed | 直映射 |
| 事件无时间戳 | — | 引擎禁时钟（确定性续跑）；SSE 侧自打时间戳 |

toolloop 事件（AgentEvent）→ SSE 映射见 events.py SSE_EVENT_MAP，无丢弃项。

## 4. 回退触发条件

**swarmflow → toolloop**（任一即触发）：
1. workswarm/openjiuwen import 失败（依赖缺失或版本不兼容）
2. SwarmFlow 适配器未通过 toolloop 的同一集成测试
3. 升级后 model_copy 注入模式失效且无替代
4. runtime: toolloop 配置手动切回

**MCP → inline 工具**（任一即触发）：
1. MCP server 不可达（连接超时）——自动回退（已实现）
2. MCP 工具调用持续失败——自动回退（已实现）
3. tools: inline 配置手动切回

**temporal → sqlite 队列**（任一即触发）：
1. Temporal server 不可达——API 回退到 SQLite 队列（已实现）
2. queue: sqlite 配置手动切回

**OpenMetadata → 本地语义层**（自动）：
1. OM 不可达——schema enrichment 跳过（已实现）
2. OM 表未摄取——该表无 enrichment（已实现）
3. YAML 语义层始终是 Agent 的事实源（OM 只是企业元数据中心）
