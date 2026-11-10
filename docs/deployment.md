# t2d 部署手册（2.0 架构）

> 演示环境：HTTP（无 TLS）、公网 IP 直连、单区域。生产高可用/多租户不在首版范围（任务书 §2）。
> 2.0 新增：Temporal 工作流编排、OpenMetadata 元数据中心、MCP 数据访问协议、SwarmFlow Agent 运行时。

## 一、拓扑（2.0）

### 单机演示形态（当前默认，一台 ECS）

```
浏览器 ──HTTP:8080──▶ Nginx ─┬─ /            前端静态（apps/web/dist）
                            ├─ /api/        api:8001（FastAPI）
                            └─ /api/tasks/*/events  SSE

api ──▶ temporal:7233（工作流编排，UI :8082）
     ──▶ mcp-server:9100（数据访问，治理内置）
     ──▶ openmetadata:8585（元数据中心，UI :8585）

temporal-worker ──▶ temporal:7233（执行工作流 Activities）
                  ──▶ mcp-server:9100（MCP 工具调用）
                  ──▶ business-pg:5434（业务数据）
                  ──▶ sandbox:8003（沙箱分析）

openmetadata ──▶ om-mysql:3306 + om-es:9200（元数据存储）
api/worker ──▶ host:4000（LiteLLM 代理 → 华为云 MaaS）
状态库：SQLite（卷 t2d_appdata:/var/lib/t2d/state.db，WAL）
文件：本地卷（OBS 演示模式）
```

### 配置开关（config/agent/agent_config.yaml）

```yaml
agent:
  runtime: swarmflow    # toolloop | swarmflow（Agent 运行时）
  tools: mcp            # inline | mcp（数据访问方式）
  queue: sqlite          # sqlite | temporal（任务编排方式）
```

### 两台 ECS 形态（任务书 §4/§5 目标）

- **ECS-A（应用机，4C8G）**：Nginx、前端、api、temporal-worker、mcp-server、sandbox-server。
- **ECS-B（数据机，4C8G）**：业务 Postgres（或真实 DWS）、状态库 MySQL 8、Temporal server、OpenMetadata（mysql + ES + server）。
- 通过 VPC 内网互访；安全组：应用组放行 8080 入站（公网）+ 22（运维源 IP）；数据组/沙箱组仅允许应用组内网。

## 二、首次部署（单机）

前置：Docker 26+ / Compose v2；磁盘 ≥ 15G 可用（2.0 新增 Temporal + OM 约 3G）；LiteLLM 代理可达。

```bash
# 1. 代码与配置
git clone <repo> && cd rappi_t2d
cp .env.example .env
#   必填：APP_SECRET_KEY、MODEL_API_KEY、SANDBOX_API_KEY、OM_PASSWORD

# 2. 前端构建
cd apps/web && npm install && npm run build && cd ../..

# 3. 合成数据
python3 scripts/gen_synthetic_data.py --seed 42 --orders 300000 --out data/synthetic

# 4. 启动全栈（9 容器）
docker compose -f infra/compose/docker-compose.yml up -d
# 首次启动自动：迁移 → 演示账号 → 语义 → 3 个预置看板

# 5. OpenMetadata 初始化（首次）
python3 scripts/sync_semantics_to_om.py      # 语义层→Glossary（24 术语）
python3 scripts/ingest_tables_to_om.py     # 业务表→OM（10 表）

# 6. 验证
curl http://<host>:8080/api/healthz       # API
curl http://<host>:8082/                    # Temporal UI
curl http://<host>:8585/                     # OpenMetadata UI
```

## 三、云资源接入清单（凭据到位后）

| 服务 | 环境变量 | 切换动作 |
|---|---|---|
| DWS | DWS_HOST/PORT/DATABASE/SCHEMA/USER/PASSWORD | 补齐 dws_dw.py 实测后接入 factory；重导数据 |
| CSS | CSS_HOST/PORT/USER/PASSWORD + EMBEDDING_* | 补齐 css.py；重建索引 |
| OBS | OBS_ACCESS_KEY/SECRET_KEY/SERVER/BUCKET | 补齐 obs.py；文件迁移 |
| RDS MySQL | MYSQL_URL | 零改动切换；`alembic upgrade head` |
| 模型 | MODEL_API_BASE/KEY | 已接 LiteLLM（OpenAI 兼容路径） |

## 四、备份与恢复

- **状态库**：`sqlite3 var/state.db ".backup backup/state-$(date +%F).db"`
- **业务库**：演示数据可重灌（`import_synthetic_data.py --recreate`）
- **文件卷**：tar 打包 var/files
- **OM 元数据**：MySQL dump（openmetadata_db）
- **恢复**：新机拉代码 → 恢复 state.db + var/files → compose up → healthz 绿

## 五、故障处置（runbook）

| 症状 | 处置 |
|---|---|
| healthz 里 litellm=false | 检查 LiteLLM 栈（:4000）；401/403 = 审查误杀（自动重试 4 次） |
| 任务一直 queued | worker 存活？（:8002）；queue 模式对吗？temporal 模式检查 :7233 |
| 任务卡 running | kill worker → SQLite 模式靠租约回收；temporal 模式靠事件溯源续跑 |
| MCP server 不可达 | 检查 :9100；worker 自动回退 inline 工具 |
| Temporal 不可达 | 检查 :7233；API 自动回退 SQLite 队列 |
| OM 不可达 | 检查 :8585；schema enrichment 自动跳过 |
| 沙箱任务失败 | :8003 日志；孤儿容器：`docker rm -f $(docker ps -aq --filter "label=opensandbox.io/id")` |
| SSE 无输出 | Nginx events location（proxy_buffering off）；直连 :8001 排除代理 |
| 磁盘告警 | `docker builder prune`；evals/reports 归档；data/synthetic 可重生成 |

## 六、演示彩排清单

1. **订单/GMV 对话建板**：登录 analyst_a → Studio 新建 → "最近7天各国家GMV趋势" → SSE 进度 → Apply → 改标题 → 发布到墨西哥专项 → admin 审批
2. **履约多 Source 看板**：打开预置"履约监控" → "最近7天各国履约时长对比" → 局部 Patch → 刷新
3. **下降贡献分析**：问"分析上周相比上上周GMV变化，各国家贡献" → 非因果结论 → **Temporal UI 看工作流** → **OM Catalog 看血缘** → Trace 看执行详情
