# t2d 交付清单（任务书 §19 对照）

> 交付日期：2026-10-30｜版本：首版（演示模式）｜仓库：/root/rappi_t2d（git，main 分支）

## 一、可运行源码与锁定依赖 ✅

- 单仓库 12 个包/服务（apps/web、services/{api,worker}、packages/{db,agent_adapter,semantic,query_gateway,dashboard_schema,cloud_adapters}、infra、config、scripts、tests、evals、docs）。
- Python 依赖锁定（pyproject 精确版本区间）；前端锁定（react 18.3.1 / vite 5.4.11 / echarts 5.5.1 / ts 5.6.3 等，无 latest）。
- 6 个阶段实施记录：docs/phase-notes/（每阶段验收数字与遗留项）。

## 二、容器镜像构建与部署配置 ✅

- services/{api,worker}/Dockerfile（多阶段 slim）；infra/sandbox/Dockerfile（OpenSandbox server）；infra/nginx/Dockerfile + nginx.conf（SSE 专用 location，proxy_buffering off）。
- infra/compose/docker-compose.yml：business-pg / api / worker / sandbox-server / nginx 全栈，端口约定与健康检查。
- 开发态：scripts/dev_up.sh（API:8001 / Worker:8002 / 沙箱:8003 / Vite:5173）。

## 三、云资源实际清单及规格

- **当前**：无（演示模式——本地 Postgres 模拟 DWS、本地混合检索模拟 CSS、本地卷模拟 OBS；界面黄条显著标识）。
- **待提供凭据**（docs/deployment.md §三接入清单）：DWS（连接/独立 Schema/受限只读账号/网络放行）、CSS（地址/认证/向量引擎确认/Embedding 来源+维度）、OBS（AK/SK/私有桶/region）、RDS MySQL 8.0（连接/账号）。
- 适配器双实现就绪：cloud_adapters 真实实现占位含接入核对清单；凭据到位 → 改 .env + 实测验证后切换（代码零改动）。

## 四、数据、语义、Agent 配置初始化脚本 ✅

- scripts/gen_synthetic_data.py（seed=42 + anchor-date 完全可复现；30 万订单/72 万明细/116 万履约事件/含 2 个刻意缺失汇率日）。
- scripts/import_synthetic_data.py（psycopg3 流式 COPY，--recreate 可重灌）；schema_business.sql（10 表+索引+v_orders_fx 汇率回退视图）。
- scripts/seed_demo_users.py（6 账号/2 空间/角色矩阵/数据集授权白名单）、seed_semantics.py（YAML→状态库）、seed_preset_dashboards.py（3 预置看板，Source 经网关真实执行）。
- config/semantics（13 指标/11 术语/10 关联规则/11 数据集，semantic_version=2）+ config/agent/agent_config.yaml（runtime 唯一切换开关）。

## 五、评测集及结果 ✅

- evals/cases：39 固定用例（27 NL + 12 scripted），覆盖任务书 §18 全部类别。
- evals/runner.py + judge.py：**比较结果值不比较 SQL**；结果落 eval_runs 表 + evals/reports/*.json；管理台评测页可视化。
- 最终结果：见 docs/phase-notes/2026-10-30-phase5.md「最终评测结果」（基础问数门禁 ≥90%）。

## 六、文档 ✅

- docs/deployment.md（拓扑/首次部署/云接入清单/备份恢复/故障处置 runbook/三套演示彩排脚本）
- docs/architecture.md（总览/建板全路径/安全模型/诚实性边界）
- docs/requirements.md（任务书摘要）
- packages/agent_adapter/agent_adapter/boundaries.md（运行时+沙箱能力矩阵/已知限制/事件映射/回退触发条件）
- 各阶段 phase-notes（验收数字、过程发现的问题与修复、遗留项）

## 七、已知限制与未实现项（诚实声明）

1. **swarmflow 运行时**：探测 GO（无 UI 驱动/工具注入/事件/取消/预算/续跑全部实测），但适配器未接入主链路——管理台切换如实返回 409。toolloop 为默认且经过全部验收。
2. **云服务未接**：DWS/CSS/OBS/RDS 凭据未提供，全部走演示适配器；Embedding 用词法+字符 n-gram 混合检索（无 ML 模型，边界已记录）。
3. **镜像内未打包迁移/种子**：首版采用宿主机初始化+卷挂载（deployment.md 有说明）；待办：并入镜像 entrypoint。
4. **HTTP 无 TLS**：演示环境明文（任务书边界）；会话 Cookie 未设 Secure（不能误设，§6）。
5. **结果缓存**：服务端未实现结果缓存（任务书 §14 缓存键要求记录为待办）；当前每次渲染直读结果文件，前端有模块级缓存。
6. **刷新调度**：cron 计划表已建，调度器未实现自动触发（手动刷新可用且验收过）。
7. **多轮有状态会话**（agent_session）：SwarmFlow 侧源码验证未实测；toolloop 主链路用会话尾部消息实现多轮上下文，已验收。
8. 沙箱为容器隔离，**非虚拟机级隔离**（任务书 §15 要求如实表述）。

## 八、三套可复现演示脚本 ✅

见 docs/deployment.md §六（①订单/GMV 对话建板修改发布 ②履约多 Source 看板局部修改 ③下降贡献分析+沙箱报告+Trace）。

## 九、验收数字汇总

| 阶段 | 验收 | 结果 |
|---|---|---|
| 1 技术验证与契约 | verify_phase1 | 18/19（唯一未过为可选 MySQL 加测，已单独验证通过） |
| 2 底座与数据 | verify_phase2 | 17/17 |
| 3 端到端建板 | verify_phase3 | 12/12（含 SIGKILL 崩溃恢复不重复应用） |
| 4 修改/分享/发布 | verify_phase4 | 20/20 |
| 5 分析与平台 | verify_phase5 | （待最终评测后填写） |
| 6 云部署 | verify_phase6 | 静态 15/0；--full 待跑 |
| 评测套件 | evals full | （待填写；门禁：基础问数 ≥90%） |
