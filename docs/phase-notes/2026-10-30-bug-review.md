# 系统性 Bug 排查记录 — 2026-10-30（交付后第一轮）

> 起因：用户报告"拉美 GMV 总览找不到"——预置看板被 80+ 个评测产生的空看板淹没。

## 发现与修复（按严重度）

### 1. 评测污染演示库（根因级）
- **现象**：每次评测跑批在演示状态库里留下会话/任务/空看板/Source，工作空间列表被淹没。
- **根因**：评测与演示共用同一状态库。
- **修复**：**隔离评测栈**——`evals/runner.py` 对 nl/full 默认启用：一次性状态库（var/eval-state.db）+ 独立数据目录 + 专用 API(:8011)/Worker(:8012)，跑完镜像结果回演示库（管理台评测页可见，任务链接不跨库故丢弃），atexit 退出清理。实测：隔离跑完演示库看板/会话数不变。
- **配套**：`scripts/cleanup_test_data.py`——按完整 FK 依赖序清理历史测试数据（这轮梳理出全部依赖边：approvals→publications→versions、shares.version_id、patches.applied_version_id、conversations/tasks.dashboard_id 指针、在用 file_ref 保留但断链）。演示库清至 3 预置 + 1 用户看板。

### 2. 无效 cron → 500
- 创建刷新计划时 croniter 对非法表达式抛 ValueError → 未捕获 500。修复：400 + 明确错误信息。调度器侧 `_next_fire` 返回 None 时静默停摆（API 已拦截，纵深防御可接受）。

### 3. "最近访问"死条目
- 看板被删后 localStorage 里的最近访问条目永久残留，点击进 Studio 显示错误但条目不清除。修复：Studio 加载 404 时调 `removeRecent` 自动清除。

### 4. 前端容错走查（无需修复，已确认健壮）
- Sources 页：逐 source try/catch，死引用跳过 ✓
- Trace 页：404 → 错误展示 ✓
- sessionStorage 任务恢复：补读失败 → clearSession ✓
- Studio 看板加载：错误显示不崩溃 ✓

### 5. API 边界走查（确认设计行为，无需修改）
- 同会话二连发消息 → 双 pending patch → 冲突 409 流程（verify_phase4 正是此场景）
- answer 模式 + 新建看板页：问答直答不建板（提示词已引导"可以做成看板"）
- 双管理员并发审批 → 可能双副本（demo 规模可接受，记录在案）
- SSE 任务观察权限：工作空间成员可见（符合 Activity 定位）

## 回归门禁（修复后全绿）

单测 59/59｜评测冒烟 4/4｜verify_phase2 17/17｜隔离栈实测（启动→跑→镜像→退出）✓
