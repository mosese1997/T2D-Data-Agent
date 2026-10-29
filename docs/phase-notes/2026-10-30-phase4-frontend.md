# 阶段 4 实施记录 + 前端交付 — 2026-10-30

> **阶段 4 验收：✅ 20/20**（`python scripts/verify_phase4.py`）
> 任务书验收标准：「草稿到业务空间发布完整闭环」——analyst 发起发布 → 目标空间 admin 审批 → 不可变副本落地 → 目标空间 viewer 可查看、非成员被拒。

## 阶段 4 能力

- **版本恢复**：POST /dashboards/{id}/versions/{rev}/restore —— 恢复历史画布定义为新版本，响应明确"不含历史数据快照"。
- **发布审批**：发布=请求→目标空间 admin 审批→**不可变副本**（dashboard+version+sources+结果文件全量拷贝，source id 重映射保持画布绑定）落入目标空间（status=published）。副本即发布结果：目标成员可见快照，不授任何底层数据权限。每次发布都是新 Approval（SQL/受众变更需重新审批）。
- **分享**：token 公开视图（canvas+数据，无 SQL/无 source 元数据/无鉴权）；viewer 仍不能驱动 Agent（403）。
- **刷新**：手动触发 + cron 计划；worker 以 publisher 身份确定性重执行绑定 Source 的 SQL，结果文件原地替换（source id 稳定，画布绑定不断）；发布副本不随刷新变化（不可变语义）。
- **简单修改快速路径**（验收暴露的缺口，任务书 §9）：改标题/图例/布局/文字 → 意图段判 mode=simple_modify → 跳过查询段直入设计段（不允许无 Source 加数据组件）。

## 验收明细（20/20）

多轮修改 2；并发冲突 4（双 pending patch、先应用者胜、后者 409+conflict 状态）；发布闭环 5（pending、admin 可见、批准、目标 viewer 可看可读数据、非成员 403/404）；分享 4（创建、公开可看、不泄 SQL、viewer 不能发消息）；刷新 4（入队、成功、文件原地替换、数据可读）+ 简单修改路径（含在多轮修改中）。

## 前端交付（apps/web，后台任务完成）

- React 18.3.1 + TS 5.6.3 + Vite 5.4.11 + ECharts 5.5.1 + zustand 5.0.2 + react-router 6.28.0，全锁定版本；`npm run build`（tsc --noEmit && vite build）零错误（产物 JS 1.24MB / gzip 411KB）。
- 页面：登录（演示账号一键填入）/ Home（最近访问+连接状态）/ Workspace 看板列表 / **Studio**（12 列 grid 画布：指标卡金额格式化与空值「—」、折线/柱状 split_by 拆系列与堆叠、表格分页、口径文字；右侧 Agent 面板：SSE 实时进度、澄清问答、patch 预览+应用/拒绝+409 冲突文案、取消）/ Sources 页（SQL/口径/预览）/ 全局演示模式黄条。
- SSE：fetch 流式解析（EventSource 不能带鉴权头）；挂载先 GET snapshot 补齐再接增量（seq 去重）；sessionStorage 保持进行中任务，刷新页面自动重挂。
- 已实测：经 Vite 代理 SSE 逐条实时到达；patch apply 实测看板升 v2（10 组件）。
- 手动验证：http://localhost:5173（Vite 绑定 [::1]，用 localhost 不用 127.0.0.1）。

## 过程修复

- refresh 端点 enqueue 传 session 未 commit（任务行没落库）→ 补 commit。
- runner 缺 DashboardVersion 导入（simple_modify 路径触发 NameError）。
