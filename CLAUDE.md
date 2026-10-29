# CLAUDE.md — t2d 仓库工作说明

本文件为 Claude Code 在本仓库内工作的指引。

## 项目背景

t2d 是 Agentic Talk to Data 数据产品 Demo（任务书见 docs/requirements.md）。完整实施计划：`/root/.claude/plans/merry-sauteeing-rain.md`。业务域：订单、GMV、履约。

## 硬性规则（违反即返工）

1. **模型调用**：一律走 LiteLLM `:4000` 的 OpenAI 兼容路径（`/v1/chat/completions`），model=`t2d/deepseek-v4.1-flash-1017`。**绝不**调用 MaaS `/anthropic` 端点做流式工具调用（有 53-60% 截断缺陷，见 /root/bug-reports/）。
2. **工具上下文注入**：每次工具调用的用户/任务/权限上下文由服务端从任务行构造（`packages/agent_adapter` ToolContext），工具的 JSON Schema 中不得出现任何身份字段——模型无法伪造身份。
3. **演示模式诚实性**：无云凭据时界面必须显示"演示数据模式"横幅；不得把模拟执行展示为真实云调用；不得放置无功能的假入口；不得伪造执行记录/占位成功提示。
4. **状态库双方言**：迁移按 MySQL 8.0 方言写并保持 SQLite 兼容——主键 `BigInteger().with_variant(Integer(), "sqlite")`、不用 ENUM、不用 `ON UPDATE CURRENT_TIMESTAMP`、String 必带长度、时间存 naive UTC。见 `packages/db/t2d_db/session.py` 注释。
5. **不创建收费云资源**；云凭据只进 `.env`（已 gitignore），绝不进代码、日志或前端。
6. **SSE 事件**只展示真实阶段与工具摘要，不推送模型隐藏推理；事件带递增 seq 支持 Last-Event-ID 补读。
7. 每阶段完成必须更新 `docs/phase-notes/` 实施记录并跑对应 `scripts/verify_phaseN.*`。

## 常用命令

```bash
make bootstrap        # 依赖安装+迁移+数据生成导入+种子
make up / make down   # 启停全栈
make test             # pytest (tests/)
python scripts/verify_phase1.py   # 当前阶段验收
```

## 代码结构要点

- 三 Agent：`services/worker/t2d_worker/agents/`（main/query/analysis）。子 Agent 返回结构化结果，不靠聊天转述。
- 9 个工具：`services/worker/t2d_worker/tools/`，注册表在 registry.py。
- Agent 运行时切换：`config/agent/agent_config.yaml` 的 `runtime: toolloop|swarmflow`，两实现都在 `packages/agent_adapter/`，边界记录在 `packages/agent_adapter/agent_adapter/boundaries.md`。
- 查询网关：单语句/只读/对象白名单/函数黑名单/60s 超时/修复≤2次，入口 `packages/query_gateway/query_gateway/gateway.py`。
- 任务队列：`packages/db/t2d_db/queue.py`，单语句原子领取，租约+心跳+取消+幂等。

## 端口约定（本机已占用 3000/3001/4000/4010/8000/9090/5433/6379，不得使用）

Nginx 8080｜API 8001｜Worker 健康检查 8002｜OpenSandbox Server 8003｜业务 PG 5434｜Vite dev 5173

## 已知边界

- JiuwenSwarm SwarmFlow：0.2.x 早期项目，工具注册/取消/无 UI 运行 API 未公开文档化，验证结论与限制见 boundaries.md。
- OpenSandbox 资源限制配置：README 未覆盖，实测结论记录在 boundaries.md。
- 本机磁盘有限：构建用多阶段+slim 基础镜像；默认 30 万订单（百万级只在云上跑）。
