# t2d — Agentic Talk to Data

**English TL;DR** — t2d is a fully working demo of an agentic "talk-to-data" product: ask questions in natural language (Chinese or English), and a multi-agent system understands your intent, generates and executes governed SQL against a semantic layer, builds/edits dashboards through reviewable patches, runs sandboxed contribution analyses, and explains its own failures. **2.0 architecture**: data access via MCP protocol, orchestration via Temporal durable workflows, metadata via OpenMetadata, agent framework via OpenJiuwen SwarmFlow. React + FastAPI + ECharts, SQLite-first with zero-change MySQL migration, Docker Compose one-command boot, 38-case eval suite, 50-step user-journey regression, bilingual UI. [详细中文介绍见下 ↓](#t2d--agentic-talk-to-data-数据产品)

---

# t2d — Agentic Talk to Data 数据产品

一个**可完整运行**的对话式数据产品 Demo：用自然语言（中/英）向 Agent 提问，它会理解意图、生成并执行受控 SQL、把结果做成看板、做贡献分解分析，甚至能解释"上一次为什么失败"。

> **这不是一个概念演示**。每个功能都经过自动化验收：38 个固定评测用例（基础问数正确率 **100%**）、50 步用户旅程回归测试全绿、六阶段验收脚本全部通过。所有 Agent 行为可追溯到真实的工具调用记录（Trace 页可核验每次输入/输出/耗时）。

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

- **语义层**：13 个指标（GMV/订单量/客单价/退款率/履约时长…）带权威口径——表达式、排除条件、币种规则、可用维度、合法关联全部结构化定义，YAML 是唯一事实源
- **口径规则结构化**：汇率缺失日就近回退做进数据库视图（`v_orders_fx`，30 万订单 0 个 NULL）；自然周 vs 滚动 7 天、排除今日、明细扇出去重——规则是结构，不是提示词约定
- **查询网关**：单语句只读、对象白名单、函数黑名单、LIMIT 钳制、60s 超时、修复≤2 次、全量审计（含被拒绝的查询）
- **权限**：工作空间数据集授权白名单是根；viewer 不能驱动 Agent；跨空间不可见；分享只授视图不授数据权限；两个空间的授权差异可现场演示

### 版本化看板

- 画布 JSON（schema_version）→ Agent 生成候选 Patch（绑定 base_revision）→ 预览 diff → **你点击应用**才生效 → 原子生成新版本
- 并发修改冲突返回 409 要求重新生成（绝不自动合并）
- 发布 = 审批流（目标空间 admin 批准）→ 不可变副本（含数据快照）落入目标空间
- 历史版本可恢复（明确提示"恢复定义不恢复数据"）

### 平台能力

- **管理台**：Agent 配置（运行时可切换）、运行列表、**Trace 详情**（agent 树 + 每次工具调用的输入/输出/耗时）、知识索引状态、评测结果
- **评测体系**：38 个固定用例，判定器比较**结果值**（与独立 reference SQL 对账）而非 SQL 字符串；基础问数门禁 90%（实测 100%）
- **中英双语**：272 条界面文案 + **Agent 回复跟随界面语言**（英文界面下发问，回答/看板标题/口径说明全英文）
- **崩溃安全**：任务检查点 + 租约回收，SIGKILL worker 后任务断点续跑，Apply 绝不重复执行（实测验证）

## 🚀 快速开始

```bash
git clone <repo> && cd t2d
cp .env.example .env          # 填 MODEL_API_KEY（任意 OpenAI 兼容端点）
cd apps/web && npm install && npm run build && cd ../..
docker compose -f infra/compose/docker-compose.yml up -d
# 首次启动自动：迁移 → 演示账号 → 语义 → 3 个预置看板（30 万合成订单已含）
```

打开 `http://<host>:8080`，用演示账号登录（见 `.env.example` 或 `scripts/seed_demo_users.py`，密码均为 `*-demo-2026`，仅演示用）。

> **演示数据模式**：未配置华为云 DWS/CSS/OBS 凭据时自动使用本地适配器（Postgres 模拟 DWS、本地混合检索模拟 CSS、本地卷模拟 OBS），界面显著标识。适配器双实现——凭据到位后改 `.env` 即切换，代码零改动。

## 🏗️ 架构（2.0）

```
浏览器 ──▶ Nginx(:8080) ──▶ FastAPI(:8001) ──SSE──▶ 任务进度
                                  │
         ┌────────────────────────┼────────────────────────┐
         │                        │                        │
    Temporal(:7233)         MCP Server(:9100)       OpenMetadata(:8585)
    工作流编排               数据访问（治理内置）      元数据中心
         │                        │                        │
    Temporal Worker          查询网关 + 语义层         Glossary + 血缘
    (SwarmFlow runtime)    (白名单/限流/审计)         + 表结构 + enrichment
         │                        │                        │
         └──────────┬─────────────┘                        │
                    │                                      │
              业务 Postgres(:5434)                   OM MySQL + ES
              (模拟 DWS, 10 表)                      (元数据存储)
                    │
              OpenSandbox(:8003)
              (沙箱分析, 1vCPU/1GiB/禁网)
```

**2.0 关键变更**：

| 层 | 1.0 | 2.0 |
|---|---|---|
| 数据访问 | 进程内 Python 函数 | **MCP 协议**（:9100）——治理随协议走，任何 MCP 客户端受同样白名单/限流/审计 |
| 任务编排 | 自研 SQLite 队列（~400 行租约/心跳/检查点） | **Temporal 工作流**——崩溃恢复/重试/取消平台原生（实测：SIGKILL 后 Activity 恰好执行一次） |
| Agent 框架 | toolloop（自建） | **SwarmFlow**（OpenJiuwen，任务书指定框架）——适配器集成验证 6/6，toolloop 保留为回退 |
| 元数据 | YAML + 状态库 | YAML（Agent 事实源）+ **OpenMetadata**（企业元数据中心：术语/血缘/表结构/enrichment） |
| 身份传播 | ToolContext 进程内注入 | **MCP 请求头**（X-T2D-*）→ 服务端对照 DB 验证 → ToolContext——模型无法伪造（跨协议边界存活） |

**关键设计决策**（详见 [docs/architecture.md](docs/architecture.md)）：

1. **确定性编排 + 模型决策点**——runner 控制状态机/检查点/取消，模型只做意图解析、SQL 生成、组件设计。子 Agent 返回结构化结果，不靠聊天转述
2. **口径规则结构化**——评测抓到模型两次"不守规矩"（汇率回退、维度中英映射），修法都是把规则做进视图/语义层，而不是加提示词
3. **诚实性机制**——演示模式黄条、未接入的能力如实 409、空结果如实说明、用户前提错误时用数据纠正、贡献分析明确"非因果"、无伪造记录
4. **治理随协议走**（2.0 新增）——MCP Server 内置查询网关全部治理，第三方 MCP 客户端也受同样约束
5. **演进不重写**——每层双轨可切换（tools: inline|mcp、queue: sqlite|temporal、runtime: toolloop|swarmflow），评测门禁守每一步

## 📁 目录结构

```
apps/web/                  React18+TS+Vite+ECharts（浅橙主题，中英双语，手写 i18n 零依赖）
services/api/              FastAPI（REST+SSE，权限域结果缓存，自初始化 entrypoint）
services/worker/           Agent Worker（三 Agent、9 工具、刷新调度、崩溃恢复）
packages/agent_adapter/    运行时抽象（toolloop 默认 + SwarmFlow 适配器，能力边界记录）
packages/semantic/         语义层（指标/术语/关联/口径规则/混合检索）
packages/query_gateway/    查询网关（sqlglot 校验/修复/限流/审计）
packages/dashboard_schema/ 画布 JSON Schema/Patch/diff/校验
packages/cloud_adapters/   DWS/CSS/OBS 适配器（演示/真实双实现）
packages/db/               26 表状态库（SQLite 先行，迁移按 MySQL 方言，双方言验证）
config/semantics/          语义配置 YAML（唯一事实源）
infra/                     Compose 全栈 + Nginx（SSE 专用配置）+ 沙箱配置
scripts/                   数据生成/导入/种子/六阶段验收/用户旅程测试
tests/                     59 个单元测试（队列/网关/画布/缓存隔离）
evals/                     38 个固定评测用例 + 判定器
docs/                      架构/部署/交付/需求/阶段实施记录（含全部验收数字）
```

## 🧪 测试与质量

```bash
python3 -m pytest tests/unit/ -q              # 59 个单元测试
python3 evals/runner.py --case-set smoke      # 评测冒烟（4 用例）
python3 evals/runner.py --case-set full       # 全量 38 用例（基础问数门禁 90%）
python3 scripts/test_user_journey.py          # 50 步用户旅程回归（~154s）
bash scripts/verify_phase6.sh --full          # 部署验收（compose 构建+公网入口+SSE）
```

**评测方法论**：判定器把 Agent 的结果与**独立执行的 reference SQL** 对账（容差内命中），从不比较 SQL 字符串——这意味着 Agent 换任何写法只要数字对就算过，而数字错一定抓得出来。评测曾抓出过 reference SQL 自身的窗口错误、模型的汇率回退缺失、维度值中英映射缺失——每次都是判定器先发现的。

## 🌐 双语

界面 272 条文案中英全覆盖（顶栏「中 / EN」即时切换，按浏览器语言自动初始）。**Agent 回复跟随界面语言**：英文界面下发消息，回答、看板标题、口径说明、变更摘要全部英文；数据内容（已有看板标题、指标名）保持创建时的语言（数据不可变原则）。

## ⚠️ 已知限制（诚实声明）

- **云服务未接**：DWS/CSS/OBS/RDS 凭据未提供时走演示适配器；Embedding 用词法+字符 n-gram 混合检索（无 ML 模型）
- **SwarmFlow 运行时**：适配器已实现并通过真实引擎集成验证（6/6），但默认环境未装 workswarm（依赖较重）——切换接口如实 409 并说明，toolloop 为默认且全验收
- **HTTP 无 TLS**：演示环境明文（任务书边界）；沙箱为容器级隔离，非虚拟机级
- 完整清单见 [docs/delivery.md](docs/delivery.md) §七

## 📚 文档

| 文档 | 内容 |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 架构总览、建板全路径、安全模型、诚实性边界 |
| [docs/deployment.md](docs/deployment.md) | 部署拓扑、云接入清单、备份恢复、故障处置、演示彩排脚本 |
| [docs/delivery.md](docs/delivery.md) | 交付物对照、验收数字汇总、已知限制 |
| [docs/requirements.md](docs/requirements.md) | 需求摘要（容量边界/硬性原则/关键机制） |
| [docs/phase-notes/](docs/phase-notes/) | 六阶段实施记录——每阶段的验收数字、踩过的坑、修复过程 |
| [packages/agent_adapter/agent_adapter/boundaries.md](packages/agent_adapter/agent_adapter/boundaries.md) | 运行时/沙箱能力矩阵、回退触发条件 |

## 🛠️ 技术栈

React 18 · TypeScript · Vite · ECharts ｜ FastAPI · SQLAlchemy · Alembic ｜ SQLite（可零改动切 MySQL 8）· PostgreSQL ｜ OpenSandbox（沙箱）｜ Docker Compose · Nginx ｜ 手写 i18n（零依赖）｜ scrypt + itsdangerous（认证）

## License

[Apache-2.0](LICENSE)
