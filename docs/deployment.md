# t2d 部署手册

> 演示环境：HTTP（无 TLS）、公网 IP 直连、单区域。生产高可用/多租户不在首版范围（任务书 §2）。

## 一、拓扑

### 单机演示形态（当前默认，一台 ECS）

```
浏览器 ──HTTP:8080──▶ Nginx ─┬─ /            前端静态（apps/web/dist）
                            ├─ /api/        api:8001（FastAPI）
                            └─ /api/tasks/*/events  SSE（proxy_buffering off）
api/worker ──▶ business-pg:5434（Postgres，模拟 DWS）
worker ──▶ sandbox-server:8003（OpenSandbox，docker.sock 创建沙箱）
api/worker ──▶ host:4000（LiteLLM 代理 → 华为云 MaaS）
状态库：SQLite（卷 t2d_appdata:/var/lib/t2d/state.db，WAL）
文件：本地卷（OBS 演示模式）
```

### 两台 ECS 形态（任务书 §4/§5 目标）

- **ECS-A（应用机，4C8G）**：Nginx、前端、api、worker、sandbox-server。
- **ECS-B（数据机，2C4G）**：业务 Postgres（或真实 DWS）、状态库 MySQL 8（RDS 或容器）、备份卷。
- 通过 VPC 内网互访；安全组：应用组放行 8080 入站（公网）+ 22（运维源 IP）；数据组/沙箱组仅允许应用组内网。

## 二、首次部署（单机）

前置：Docker 26+ / Compose v2；磁盘 ≥ 10G 可用；LiteLLM 代理可达。

```bash
# 1. 代码与配置
git clone <repo> && cd rappi_t2d
cp .env.example .env
#   必填：APP_SECRET_KEY（随机串）、MODEL_API_KEY（LiteLLM Virtual Key）、
#         SANDBOX_API_KEY（与 infra/sandbox/opensandbox-config.toml 一致）

# 2. 前端构建（宿主机构建，产物进 nginx 镜像）
cd apps/web && npm install && npm run build && cd ../..

# 3. 合成数据（可重复：--seed 42 --anchor-date）
python3 scripts/gen_synthetic_data.py --seed 42 --orders 300000 --out data/synthetic

# 4. 启动全栈
cd infra/compose && docker compose up -d --build && cd ../..

# 5. 初始化（迁移已在启动时对空库自动执行；种子需手动）
export STATE_DB_URL=sqlite:///var/state.db   # 开发机直跑时；容器内路径不同，见下
# 容器内初始化（推荐）：
docker exec t2d_api python - <<'EOF'
import os
os.environ['STATE_DB_URL'] = 'sqlite:////var/lib/t2d/state.db'
from alembic import command
from alembic.config import Config
cfg = Config('/app/packages/db/alembic.ini')  # 若镜像未含 packages，见"已知限制"
EOF
```

> **当前已知限制（诚实声明）**：api/worker 镜像内未打包 Alembic 迁移目录与种子脚本；
> 首版部署采用"宿主机跑一次初始化、挂载 state.db 卷"的方式：
> ```bash
> # 宿主机（开发机）先初始化好 var/state.db 与 var/files，再挂载进容器：
> #   volumes: t2d_appdata 已挂 /var/lib/t2d —— 把 var/state.db 与 var/files 放入该卷
> bash scripts/dev_up.sh && python3 scripts/seed_demo_users.py \
>   && python3 scripts/seed_semantics.py && python3 scripts/seed_preset_dashboards.py
> docker compose -f infra/compose/docker-compose.yml up -d
> ```
> 阶段 6 收尾时把迁移+种子并入镜像 entrypoint（见 docs/phase-notes 待办）。

```bash
# 6. 验证
curl http://127.0.0.1:8080/api/healthz       # status ok + demo_mode
浏览器打开 http://<公网IP>:8080               # 演示账号见 scripts/seed_demo_users.py
```

## 三、云资源接入清单（凭据到位后）

| 服务 | 环境变量 | 切换动作 |
|---|---|---|
| DWS | DWS_HOST/PORT/DATABASE/SCHEMA/USER/PASSWORD | 补齐 dws_dw.py 实测后接入 factory；重导数据 |
| CSS | CSS_HOST/PORT/USER/PASSWORD + EMBEDDING_* | 补齐 css.py；重建索引（semantic_version 变更必须新索引） |
| OBS | OBS_ACCESS_KEY/SECRET_KEY/SERVER/BUCKET | 补齐 obs.py；文件迁移 |
| RDS MySQL | MYSQL_URL | 零改动切换（迁移按 MySQL 方言写，已双验证）；`alembic upgrade head` |
| 模型 | MODEL_API_BASE/KEY | 已接 LiteLLM（OpenAI 兼容路径） |

## 四、备份与恢复

- **状态库**：`sqlite3 var/state.db ".backup backup/state-$(date +%F).db"`（WAL 下安全）；上云后用 RDS 自动备份。
- **业务库**：演示数据可随时重灌（`import_synthetic_data.py --recreate`）；真实 DWS 用快照。
- **文件卷**：tar 打包 var/files；OBS 接入后用桶版本化。
- **恢复**：新机拉代码 → 恢复 state.db 与 var/files → compose up → healthz 绿。

## 五、故障处置（runbook 摘要）

| 症状 | 处置 |
|---|---|
| healthz 里 litellm=false | 检查 LiteLLM 栈（docker ps / :4000/health/liveliness）；worker 日志看 401/403（审查误杀会自动重试 4 次） |
| 任务一直 queued | worker 存活？（:8002/healthz）；`SELECT status, count(*) FROM tasks GROUP BY 1`；租约回收每 15s 由 worker 主循环执行 |
| 任务卡 running | kill worker → 租约 30s 过期 → 自动重排队续跑（checkpoint） |
| 沙箱任务失败 | sandbox-server 日志；孤儿容器清理：`docker rm -f $(docker ps -aq --filter "label=opensandbox.io/id")` |
| SSE 无输出 | Nginx：确认命中 events location（proxy_buffering off）；直连 :8001 排除代理因素 |
| 磁盘告警 | `docker builder prune`；evals/reports 归档；data/synthetic 可重生成 |

## 六、演示彩排清单（任务书 §19 三套脚本）

1. **订单/GMV 对话建板**：登录 analyst_a → Studio 新建 → "上周各国家GMV趋势，再给我一个GMV总量" → 看 SSE 进度 → Apply → 改标题（简单修改路径）→ 发布到墨西哥专项 → admin 审批。
2. **履约多 Source 看板**：打开预置"履约监控" → "最近7天各国履约时长对比" → 局部 Patch 应用 → 刷新一次。
3. **下降贡献分析**：问"分析上周相比上上周GMV变化，各国家贡献如何" → 结论（非因果表述）→ Activity/管理台 Trace 查看分析执行详情（agent_runs 三段 + run_analysis 输入输出）。
