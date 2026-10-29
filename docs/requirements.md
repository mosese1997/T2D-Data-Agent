# t2d 需求摘要（源自《Agentic Talk to Data 数据产品实施任务书》）

> 本文件为实施用摘要；完整任务书以委托方原文为准。验收对照见各 docs/phase-notes/。

## 目标
可运行的数据产品 Demo：①自然语言创建/修改/分享/发布 Dashboard；②展示 Agent 的语义理解、任务编排、工具调用、子 Agent 协作、沙箱分析、运行追踪与评测。参考 Rappi 内部平台信息架构，使用自有品牌（t2d）。

## 硬性原则（违反即返工）
- 不擅自创建收费云资源；缺凭据 → 代码+部署配置+初始化脚本+本地验证，界面显著标识"演示数据模式"；不把模拟执行展示为真实云调用。
- 框架接口必须实测验证，不编造 API；不满足处在适配层补齐并记录边界（boundaries.md）。
- 先端到端最小链路，再补页面；每阶段更新实施记录+验证结果+剩余事项。
- 不放置看似可用但实际无功能的入口；无占位成功提示与伪造执行记录。

## 容量边界（第一版）
5-10 演示账号/约 5 人并发；分析任务并发 2（持久化排队）；沙箱并发 1；1 业务域（订单/GMV/履约）；6-8 业务表（实际 10）/10-20 指标（实际 13）；10 万-100 万合成订单（实际 30 万，可放大）；3 预置 Dashboard；文本交互；HTTP 公网 IP（无域名/TLS）；不做生产高可用与多租户 SaaS。

## 技术栈
React+TS+Vite+ECharts｜FastAPI｜Agent 框架：JiuwenSwarm（SwarmFlow 探测 GO，toolloop 为默认实现，适配层切换）｜OpenSandbox 沙箱｜MySQL 8（SQLite 先行，迁移双方言）｜SQLAlchemy+Alembic｜DWS/CSS/OBS（适配器双实现）｜Nginx｜Docker Compose｜模型：LiteLLM OpenAI 兼容路径 `t2d/deepseek-v4.1-flash-1017`（绝不走 MaaS /anthropic 流式工具调用）｜SSE 任务进度。

## 关键机制
- **9 工具**：search_semantics / get_semantic_definition / get_authorized_schema / validate_query / execute_query / get_result_metadata / run_analysis / propose_dashboard_patch / validate_dashboard_patch。每次调用绑定服务端注入的用户/任务/权限上下文（ToolContext），Schema 无身份字段。
- **查询网关**：单语句只读、对象白名单、函数黑名单、60s 超时、行数/大小限制、修复≤2、全量审计（含拒绝）。
- **任务状态机**：queued/running/waiting_for_user/waiting_for_apply/succeeded/failed/cancelled/interrupted；租约+心跳+回收；幂等键；阶段检查点；崩溃不重复应用。
- **版本**：候选 Patch 绑 base_revision，Apply 原子生成新版本，冲突要求重新生成；版本关联画布+Source+语义版本+创建人+任务。
- **权限**：admin/analyst/viewer；草稿按用户上下文查询，发布用批准的服务身份；分享不授底层数据权限；两用户上下文固定测试无串用。
- **沙箱**：无长期凭据、仅授权结果集、禁网（opt-in 必须显式）、1vCPU/1GiB、120s 超时、清理、不复用文件。
- **口径**：自然周 vs 滚动 7 天、排除今日、业务时区、订单-明细去重、缺失汇率就近回退、零分母显示「—」、贡献分析不冒充因果。

## 测试与验收（§18）
约 40 固定用例（实际 27 NL + 12 scripted）：基础问数正确率 ≥90%（比较结果值不比较 SQL）；权限与数据隔离全过；每结论关联可核验结果；进度/Activity/Trace 来自真实事件。

## 交付物（§19）
源码+锁定依赖；镜像与部署配置；云资源清单（待凭据）；初始化脚本；评测集与结果；部署/备份/排查文档；已知限制（boundaries.md）；三套演示脚本（见 docs/deployment.md §六）。

## 待提供配置（云凭据清单）
DWS（连接/Schema/受限账号/网络）、CSS（地址/认证/向量引擎/Embedding 来源+维度）、OBS（AK/SK/桶/region）、RDS MySQL（连接/账号）；最早接入点=阶段 2 数据导入，兜底=阶段 6 部署时切换。
