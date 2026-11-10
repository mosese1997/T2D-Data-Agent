# t2d — Agentic Talk to Data

**English TL;DR** — t2d is a fully working demo of an agentic "talk-to-data" product: ask questions in natural language (Chinese or English), and a multi-agent system understands your intent, generates and executes governed SQL against a semantic layer, builds/edits dashboards through reviewable patches, runs sandboxed contribution analyses, and explains its own failures. [详细中文介绍见下 ↓](#t2d--agentic-talk-to-data-数据产品)

---

# t2d — Agentic Talk to Data 数据产品

一个**可完整运行**的对话式数据产品 Demo：用自然语言（中/英）向 Agent 提问，它会理解意图、生成并执行受控 SQL、把结果做成看板、做贡献分解分析，甚至能解释"上一次为什么失败"。

> **这不是一个概念演示**。每个功能都经过自动化验收：38 个固定评测用例（基础问数正确率 **100%**）、50 步用户旅程回归测试全绿、六阶段验收脚本全部通过。所有 Agent 行为可追溯到真实的工具调用记录（Trace 页可核验每次输入/输出/耗时）。

## 🏗️ 整体架构（2.0）

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  UI  │  React / TypeScript / ECharts                                    │
│  统一工作台：ChatBI · 看板画布 · 数据目录 · 任务进度 · Agent 管理台         │
│  中英双语 · SSE 实时进度 · Trace 详情 · 权限域隔离                          │
└─────────────────────────────────────────────────────────────────────────────┘
         │ HTTP JSON / SSE
         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  API  │  Python · FastAPI                                              │
│  身份/租户/角色/业务空间验证 · 权限域缓存 · OpenAPI 契约                    │
└────────┬──────────────────────────────┬────────────────────────────────┘
         │                              │
         ▼                              ▼
┌──────────────────────┐    ┌───────────────────────────────────────────┐
│  AGENT                │    │  TEMPORAL  │  Temporal + Python Worker      │
│  openJiuwen SwarmFlow │    │  持久化工作流：任务调度 · 崩溃恢复 · 幂等    │
│  意图解析 → 计划生成    │    │  Signal 等待 · 取消 · 事件溯源              │
│  → 受控执行            │    └───────────────────────────────────────────┘
└────┬────────┬─────────┘         │
     │        │                   │
     ▼        ▼                   ▼
┌─────────┐ ┌─────────────────────────────────────────────────────────────┐
│  MODEL  │ │  MCP  │  MCP Server · FastMCP                            │
│  可配置  │ │  权限再校验 · 计划验证 · 参数化 SQL                        │
│  Huawei │ │  治理内置：白名单/黑名单/限流/审计                          │
│  MaaS   │ │  X-T2D-* 身份头 → 服务端验证 → ToolContext                │
│  GLM/DS │ └──────┬──────────────────┬──────────────────────────────┘
└─────────┘         │                  │
                      │                  │
                      ▼                  ▼
┌────────────────────────────┐  ┌────────────────────────────────────────┐
│  DWS  │  Huawei Cloud DWS   │  │  SQLITE  │  本地合成数据替代（只读）      │
│  内网 · 只读 · psycopg2      │  │  SQLite · 演示模式                    │
└────────────────────────────┘  └────────────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  META  │  OpenMetadata 统一元数据                                       │
│  Catalog · Fields · Lineage · Glossary · Schema Enrichment             │
│  术语/血缘/表结构/enrichment · 语义层 YAML 同步                         │
└──────────────────────────────────────────────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  OUTPUT  │  OpenSandbox 沙箱分析                                         │
│  1vCPU/1GiB/禁网 · 贡献分解 · destroy 清理 · 无凭据注入                  │
└──────────────────────────────────────────────────────────────────────────┘
```

**组件间连接**：UI ↔ API（HTTP JSON / SSE）；API → AGENT（启动任务）；AGENT ↔ MODEL（HTTPS · OpenAI 兼容）；AGENT ↔ MCP（MCP · streamable-http）；MCP → DWS（psycopg2 · SQL / TLS）；MCP → SQLITE（sqlite3 · 只读）；API ↔ META（Python 模块）；API ↔ TEMPORAL（gRPC）；TEMPORAL → META（血缘注册）；TEMPORAL → OUTPUT（沙箱分析）。

**配置开关**（config/agent/agent_config.yaml）：

```yaml
agent:
  runtime: toolloop    # toolloop | swarmflow（Agent 运行时）
  tools: mcp          # inline | mcp（数据访问方式）
  queue: sqlite       # sqlite | temporal（任务编排方式）
```

## ✨ 核心能力

### 对话式 Agent（五种意图自动路由）

| 你说 | Agent 做什么 |
|---|---|
| "上周GMV总量是多少？" | **问答直答**——对话里直接回答数字+口径，不建看板（~10 秒） |
| "最近7天各国家GMV趋势，做成看板" | **建板**——查询→设计组件→候选变更→你确认应用 |
| "分析上周相比上上周GMV变化，各国家贡献" | **沙箱分析**——贡献分解，明确声明"不构成因果解释" |
| "把看板标题改为「GMV 周报」" | **简单修改**——跳过查询直改样式 |
| "卖得好不好" | **澄清**——主动追问指标/时间/维度，不瞎猜 |

### 数据治理（不是"能查"而是"查得对"）

- **语义层**：13 个指标带权威口径——表达式、排除条件、币种规则、可用维度、合法关联全部结构化定义，YAML 是唯一事实源
- **口径规则结构化**：汇率缺失日就近回退做进数据库视图（`v_orders_fx`，30 万订单 0 个 NULL）；自然周 vs 滚动 7 天、排除今日、明细扇出去重——规则是结构，不是提示词约定
- **查询网关**：单语句只读、对象白名单、函数黑名单、LIMIT 钳制、60s 超时、修复≤2 次、全量审计（含被拒绝的查询）
- **权限**：工作空间数据集授权白名单是根；viewer 不能驱动 Agent；跨空间不可见；分享只授视图不授数据权限；两个空间的授权差异可现场演示

### 版本化看板

- 画布 JSON（schema_version）→ Agent 生成候选 Patch（绑定 base_revision）→ 预览 diff → **你点击应用**才生效 → 原子生成新版本
- 并发修改冲突返回 409 要求重新生成（绝不自动合并）
- 发布 = 审批流（目标空间 admin 批准）→ 不可变副本（含数据快照）
- 历史版本可恢复（明确提示"恢复定义不恢复数据"）

### 平台能力

- **管理台**：Agent 配置、运行列表、**Trace 详情**（agent 树 + 每次工具调用的输入/输出/耗时）、知识索引状态、评测结果
- **评测体系**：38 个固定用例，判定器比较**结果值**（与独立 reference SQL 对账）而非 SQL 字符串；基础问数门禁 90%（实测 100%）
- **中英双语**：272 条界面文案 + **Agent 回复跟随界面语言**
- **崩溃安全**：任务检查点 + 租约回收，SIGKILL worker 后任务断点续跑，Apply 绝不重复执行（实测验证）

## 🚀 快速开始

```bash
git clone <repo> && cd rappi_t2d
cp .env.example .env          # 填 MODEL_API_KEY（任意 OpenAI 兼容端点）
cd apps/web && npm install && npm run build && cd ../..
docker compose -f infra/compose/docker-compose.yml up -d
# 首次启动自动：迁移 → 演示账号 → 语义 → 3 个预置看板（30 万合成订单已含）
```

打开 `http://<host>:8080`，用演示账号登录（见 `.env.example` 或 `scripts/seed_demo_users.py`，密码均为 `*-demo-2026`，仅演示用）。

> **演示数据模式**：未配置华为云 DWS/CSS/OBS 凭据时自动使用本地适配器（Postgres 模拟 DWS、本地混合检索模拟 CSS、本地卷模拟 OBS），界面显著标识。适配器双实现——凭据到位后改 `.env` 即切换，代码零改动。

## 📊 评测结果

| 路径 | 评测 | 基础问数 | 状态 |
|---|---|---|---|
| toolloop + inline（基线） | 38/38 | 10/10 (100%) | ✅ 生产就绪 |
| toolloop + MCP 工具 | 37/38 | 9/10 (90%) | ✅ 达标 |
| SwarmFlow + MCP（冒烟） | 4/4 | 1/1 | ✅ 适配器可用 |
| Temporal + MCP（冒烟） | 4/4 | 1/1 | ✅ 核心已通 |

## 🧪 测试

```bash
python3 -m pytest tests/unit/ -q              # 59 个单元测试
python3 evals/runner.py --case-set smoke      # 评测冒烟（4 用例）
python3 evals/runner.py --case-set full       # 全量 38 用例
python3 scripts/test_user_journey.py          # 50 步用户旅程回归（~154s）
bash scripts/verify_phase6.sh --full          # 部署验收
```

## 📁 目录结构

```
apps/web/                  React18+TS+Vite+ECharts（浅橙主题，中英双语）
services/api/              FastAPI（REST+SSE，权限域缓存，自初始化 entrypoint）
services/worker/           Agent Worker（三 Agent、9 工具、崩溃恢复、Temporal Worker）
services/dws-mcp-server/  MCP Server（数据访问协议化，治理内置）
packages/agent_adapter/   运行时抽象（toolloop + SwarmFlow + MCP 客户端）
packages/semantic/         语义层（指标/术语/关联/口径规则/混合检索）
packages/query_gateway/    查询网关（sqlglot 校验/修复/限流/审计）
packages/dashboard_schema/ 画布 JSON Schema/Patch/diff/校验
packages/cloud_adapters/  DWS/CSS/OBS 适配器（演示/真实双实现）+ OM 血缘/enrichment
packages/db/              26 表状态库（SQLite 先行，迁移按 MySQL 方言）
config/semantics/          语义配置 YAML（唯一事实源）
infra/                    Compose 全栈 + Nginx + Temporal + OpenMetadata + 沙箱
scripts/                  数据生成/导入/种子/六阶段验收/旅程测试/OM 同步/摄取
tests/                     59 个单元测试
evals/                     38 个固定评测用例 + 判定器
docs/                      架构/部署/交付/需求/阶段实施记录/演进计划
```

## 📚 文档

| 文档 | 内容 |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 1.0 架构详解 |
| [docs/deployment.md](docs/deployment.md) | 2.0 部署拓扑/云接入/备份/故障处置/演示彩排 |
| [docs/evolution-plan.md](docs/evolution-plan.md) | 2.0 演进计划与进度 |
| [docs/delivery.md](docs/delivery.md) | 交付物对照、验收数字汇总、已知限制 |
| [docs/requirements.md](docs/requirements.md) | 需求摘要 |
| [docs/phase-notes/](docs/phase-notes/) | 六阶段实施记录 + E0 四项探测报告 |
| [boundaries.md](packages/agent_adapter/agent_adapter/boundaries.md) | 2.0 能力矩阵/已知限制/事件映射/回退条件 |

## ⚠️ 已知限制

- **云服务未接**：DWS/CSS/OBS/RDS 凭据未提供，走演示适配器
- **SwarmFlow 全管线集成**：适配器独立可用（6/6），但工作流返回格式与 runner 期望不匹配——toolloop 保持为默认
- **HTTP 无 TLS**：演示环境明文（任务书边界）
- **沙箱**：容器级隔离，非虚拟机级；禁网是 opt-in（适配层强制传 deny）
- 完整清单见 [boundaries.md](packages/agent_adapter/agent_editor/boundaries.md)

## License

[Apache-2.0](LICENSE)
