# t2d Data Agent 演进计划（2.0 架构）

> 状态：待评审 ｜ 前置：t2d 1.0 已交付（六阶段验收全过、38/38 评测、50 步旅程回归）
> 方法论：延续 1.0 验证有效的「验证优先 + 双轨切换 + 评测门禁」——每阶段先探测验证、新旧并行可切换、同一套评测/旅程套件守门，任何阶段可回退。

## 一、演进目标：从 1.0 到 2.0

| 维度 | 1.0 现状（已验证） | 2.0 目标 | 演进性质 |
|---|---|---|---|
| **数据访问** | cloud_adapters 进程内直连（Postgres 模拟 DWS），9 工具为 Python 函数 | **MCP Server 封装 DWS**，Agent 成为 MCP 客户端 | 协议化：治理随协议走 |
| **元数据** | YAML 语义层（唯一源）+ 状态库投影 | **OpenMetadata** 统一元数据（表结构/血缘/词汇表/数据质量） | 平台化：企业级元数据中心 |
| **数据目录** | Sources 页 + Wiki 页（自建） | **OpenMetadata Catalog**（发现/词汇/分类/血缘可视化） | ⚠️ 假设：用户所说 "OpenCatalog" 即 OpenMetadata 的目录模块（GitHub 无独立同名项目，已核实） |
| **任务编排** | 自研 SQLite 队列（租约/心跳/检查点/回收器，崩溃恢复实测） | **Temporal** 持久化工作流（重试/超时/取消/断点恢复平台原生） | 基建化：AI 上下文与任务状态由 Temporal 管理 |
| **Agent 框架** | toolloop 默认 + SwarmFlow 适配器（真实引擎验证 6/6，未转正） | **OpenJiuwen/SwarmFlow 为主要运行时**（其 MCP 原生支持已在探测中实测通过） | 转正：回到任务书指定框架 |

**核心洞察**：这五项不是孤立的——SwarmFlow 探测时已实测 `DeepAgentSpec.mcps`（MCP 客户端支持，stdio 模式 E2E 通过）。**工具 MCP 化与 OpenJiuwen 转正是天然一体的**：工具变成 MCP Server 后，SwarmFlow 用原生 MCP 挂载，toolloop 走 MCP 客户端库，两条运行时消费同一组 MCP 服务。

## 二、目标架构

```
┌────────────────────────────────────────────────────────────────────┐
│ 浏览器（React，1.0 前端基本不动）                                    │
└──────────────┬─────────────────────────────────────────────────────┘
               │ Nginx → FastAPI（REST/SSE 不变）
┌──────────────▼─────────────────────────────────────────────────────┐
│ Temporal（新增基建）                                                │
│  任务 = Workflow（意图/查询/设计/分析 = Activities）                │
│  会话上下文/检查点 = Workflow State（持久化，平台原生）              │
│  waiting_for_user/apply = Signal；取消 = Cancel；恢复 = 平台原生    │
│  Temporal UI = 免费增送的运行追踪（补充现有 Trace 页）              │
└──────────────┬─────────────────────────────────────────────────────┘
               │ Temporal Worker（原 Agent Worker 改造）
┌──────────────▼─────────────────────────────────────────────────────┐
│ Agent 运行时：OpenJiuwen/SwarmFlow（转正，默认）                     │
│  ├─ MCP 客户端（DeepAgentSpec.mcps，探测已验证）                    │
│  └─ 回退：toolloop（保留，配置切换）                                 │
└──────┬─────────────────────────────────────────────────────────────┘
       │ MCP 协议（stdio/HTTP）
┌──────▼─────────────────────────────────────────────────────────────┐
│ t2d-dws-mcp-server（新建，治理内置）                                │
│  工具：search_semantics / get_authorized_schema / validate_query   │
│        execute_query / get_result_metadata / run_analysis          │
│  内置：查询网关全部治理（白名单/黑名单/限流/审计）+ ToolContext 鉴权 │
│  后端：DWS（凭据到位）/ Postgres（演示模式）——沿用 cloud_adapters   │
└──────┬─────────────────────────────────────────────────────────────┘
       │                          ┌───────────────────────────────────┐
┌──────▼──────────────────────┐   │ OpenMetadata（新增基建）           │
│ 业务仓库（DWS/Postgres）     │   │  表结构/列注释 ← 自动摄取          │
└─────────────────────────────┘   │  词汇表 ← 语义层 YAML 同步         │
                                  │  血缘 ← Agent 写入（板→源→表）     │
                                  │  数据目录/发现/质量 ← Catalog UI    │
                                  └───────────────────────────────────┘
```

## 三、关键设计决策（需评审确认）

### D1. MCP 身份传播（最重要的安全设计）

1.0 的安全不变量是「工具 Schema 无身份字段，ToolContext 服务端注入，模型无法伪造」。MCP 协议化后这个不变量必须跨协议边界存活：

- **方案**：MCP HTTP transport 的请求头携带 `X-T2D-User / X-T2D-Workspace / X-T2D-Task`（由 Temporal Worker 从 Workflow 状态注入，模型接触不到）；MCP Server 侧校验并构造等价 ToolContext
- **禁止**：身份作为工具参数暴露给模型（等于让模型可伪造）
- 治理全部内置于 MCP Server——**任何 MCP 客户端（包括第三方）调用都受同样的白名单/限流/审计约束**

### D2. 元数据事实源：双源各司其职（推荐）

- **YAML 保持 Agent 的事实源**：代码化、可评审、可版本化、离线可用——这是 1.0 语义层被验证的工作方式
- **OpenMetadata 做企业元数据中心**：表结构自动摄取（PG/DWS connector）、血缘（Agent 自动写入）、词汇表（YAML 单向同步）、使用统计与质量
- 不把 Agent 的查询路径改成强依赖 OM（OM 挂了 Agent 不能瘫）——OM 是治理与发现层，不是查询依赖

### D3. Temporal 替换自研队列的边界

- **替换**：租约/心跳/回收/检查点/重试（平台原生，删掉我们 ~400 行队列代码）
- **保留**：runner 的状态机语义（intent→query→design 分支逻辑变成 Workflow 的 Activity 编排）；幂等键（映射为 Workflow ID）；「Apply 单事务不重复」不变（Apply 仍在 API 侧）
- **AI 上下文管理**：会话历史 + 任务状态 = Workflow State；用户澄清 = Signal 等待；跨重启的对话连续性平台保证
- 部署形态待确认：**自建 Temporal Server（+自己的 DB/UI）还是 Temporal Cloud？**（自建符合"一套 Demo 环境"边界，但多一个有状态服务）

### D4. OpenJiuwen 转正的依赖问题

探测已确认能力（无 UI 驱动/MCP 注入/事件/取消/预算/续跑全过），遗留问题是 workswarm 依赖重量（google-adk 全家桶，与 FastAPI 栈有版本冲突风险）。方案：
- Worker 镜像内独立 venv 安装 workswarm（隔离依赖冲突），或 sidecar 形态
- toolloop 保留为配置可切回的回退（boundaries.md 继续记录两者边界）

## 四、分阶段实施（每阶段有验收门禁）

### 阶段 E0：验证与选型确认（~1 周）

延续 1.0 的探测方法论，四个最小验证程序：
1. **OpenMetadata**：compose 起最小实例（注意资源：OM 较重，需 ≥4GB 内存预算）；验证 PG 摄取 connector、Glossary API、Lineage API
2. **Temporal**：起 server+UI；Python SDK 验证 Workflow/Activity/Signal/Cancel/重试语义——特别是**对照 1.0 的崩溃测试**（SIGKILL worker 后 workflow 恢复不重复执行）
3. **MCP**：Python SDK 起最小 HTTP server；验证请求头传播 + 工具调用往返
4. **确认项**：OpenCatalog=OM 目录模块（用户确认）；Temporal 自建/Cloud（用户确认）；workswarm 在 worker 镜像的安装体积实测

**验收**：四个探测报告（照 1.0 的 swarmflow-probe.md 标准），go/no-go 结论。

### 阶段 E1：数据访问 MCP 化（~2-3 周）

1. 新建 `services/dws-mcp-server/`：包装**现有** query_gateway + semantic 层（治理零改动——这是关键，治理逻辑是 1.0 验证过的资产，只换协议外壳）
2. 身份传播按 D1 实现；审计记录 MCP 请求头里的身份
3. toolloop 加 MCP 客户端工具加载（与进程内工具同一 Tool 契约）
4. **双轨**：`agent_config.yaml` 增加 `tools: inline | mcp` 开关
5. **门禁**：38 用例评测 + 50 步旅程在 **MCP 路径**上全绿（与 inline 路径同分）

### 阶段 E2：OpenMetadata 元数据统一（~2-3 周，可与 E1 后半并行）

1. compose 加 OpenMetadata；业务库摄取（PG connector；DWS 凭据到位后换）
2. 同步器：YAML 指标/术语 → OM Glossary（单向，YAML 为源）；表结构以 OM 摄取为准
3. Agent 集成：`get_authorized_schema` 增强为读 OM（列注释/标签/owner 更丰富）；`search_semantics` 可选查 OM 词汇
4. 血缘：execute_query 后自动写 OM lineage（dashboard→source→table）
5. Wiki 页改为 OM Catalog 嵌入/链接（保留本地页兜底）
6. **门禁**：评测不变绿要求（OM 挂掉时 Agent 走本地语义层降级——降级路径写进 boundaries.md）

### 阶段 E3：Temporal 编排迁移（~3-4 周，最大改动）

1. compose 加 Temporal server+UI+DB
2. Worker 改造为 Temporal Worker：runner 状态机映射为 Workflow（意图/查询/设计/分析=Activities；澄清/待应用=Signal 等待；SSE 事件从 Activity 发出，事件存储不改——run_events 表继续作为 SSE 游标）
3. 幂等键→Workflow ID；任务行保留（API 快照不变），状态由 Temporal 权威
4. **双轨**：`queue: sqlite | temporal` 开关
5. **门禁（最严）**：50 步旅程全绿 + **1.0 的崩溃测试在 Temporal 上重跑**（SIGKILL Temporal Worker → 恢复不重复 Apply）+ 取消语义验证
6. 删除自研队列代码（或归档到 attic/）

### 阶段 E4：OpenJiuwen 转正（~1-2 周）

1. worker 镜像装 workswarm（独立 venv）；SwarmFlow 设默认 runtime
2. 工具经 `DeepAgentSpec.mcps` 挂载 MCP Server（E1 产物）——探测验证过的路径
3. toolloop 保留回退；boundaries.md 更新为 2.0 边界
4. **门禁**：全部评测+旅程在 SwarmFlow 运行时全绿（与 toolloop 同分）

### 阶段 E5：交付收尾（~1 周）

部署文档 2.0、架构文档更新、boundaries.md 全量重写、演示彩排（新增：Temporal UI 看任务编排、OM Catalog 看血缘发现）、README 更新。

## 五、里程碑与工期

| 阶段 | 工期 | 依赖 | 可并行 |
|---|---|---|---|
| E0 验证 | 1 周 | — | — |
| E1 MCP 化 | 2-3 周 | E0 | E2 后半 |
| E2 OpenMetadata | 2-3 周 | E0 | 与 E1 并行 |
| E3 Temporal | 3-4 周 | E1（工具先稳定） | — |
| E4 OpenJiuwen 转正 | 1-2 周 | E1+E3 | — |
| E5 收尾 | 1 周 | 全部 | — |

**合计：约 9-12 周**（1-2 人）；E1/E2 并行可压缩到 **7-9 周**。

## 六、风险清单

| 风险 | 等级 | 缓解 |
|---|---|---|
| MCP 身份传播设计缺陷（模型可伪造身份） | **高** | D1 方案评审后才开工；E1 加"伪造身份调用被拒"的固定测试用例 |
| Temporal 重写引入 1.0 已修复的回归（双执行/丢事件） | 高 | 1.0 崩溃测试套件原样重跑作为 E3 门禁；双轨可回退 |
| OpenMetadata 资源占用压垮演示机 | 中 | E0 实测内存；必要时 OM 独立部署或降配 |
| workswarm 依赖冲突破坏 worker | 中 | 独立 venv 隔离；toolloop 回退常驻 |
| OM 成为查询强依赖（可用性下降） | 中 | D2：OM 只是治理/发现层，查询路径降级可用 |
| 基建膨胀（Temporal+OM+MCP server 三个新服务） | 中 | 与任务书"初期不引入重基建"精神的偏离需用户明确接受——本计划默认接受（用户指定） |

## 七、1.0 资产的存续（演进不重写）

| 1.0 资产 | 2.0 去向 |
|---|---|
| 查询网关（校验/限流/审计） | **原样**内置于 MCP Server（治理随协议走） |
| 语义层 YAML + 口径规则（v_orders_fx 等） | **原样**保留为 Agent 事实源；同步到 OM |
| 评测套件 38 用例 + 旅程 50 步 | **原样**作为每阶段门禁（判定器不变） |
| runner 状态机语义 | 映射为 Temporal Workflow 编排（逻辑不变，载体变） |
| toolloop 运行时 | 降为回退（配置常驻） |
| SwarmFlow 适配器 + 探测报告 | 转正依据（E4 直接复用） |
| 前端 + API 契约 | 基本不动（SSE 事件协议不变） |
| 自研队列 | E3 后退役（被 Temporal 替代） |

## 八、待用户确认的三个问题

1. **OpenCatalog** = OpenMetadata 的数据目录模块？（GitHub 无独立同名项目；若你指的是别的具体项目，给我仓库链接）
2. **Temporal 部署形态**：自建 Server（符合单环境演示边界，多一个有状态服务）还是 Temporal Cloud（免运维但引入外部依赖）？
3. **工期与启动**：按此计划开工？还是先只做 E0 验证周，拿到四个探测报告后再决定后续投入？
