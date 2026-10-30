# Agent 运行时与沙箱 — 能力边界记录

> CLAUDE.md 规则：框架不原生支持的行为在适配层补齐并记录边界；不得宣称未验证的能力已具备。
> 本文件四节：能力矩阵 / 已知限制 / 事件映射 / 回退触发条件。
> 证据来源：docs/phase-notes/swarmflow-probe.md、docs/phase-notes/opensandbox-probe.md（探测脚本在 var/probe-scripts/）。

## 1. 能力矩阵

### Agent 运行时（runtime: toolloop | swarmflow，config/agent/agent_config.yaml 切换）

| 能力 | toolloop（自建基线，默认） | swarmflow（workswarm 0.2.7 / openjiuwen 0.1.19） |
|---|---|---|
| 无 UI 编程运行 | ✅（即本体） | ✅ 实测：run_workflow() 纯库入口，零全局状态（contextvars），无 config.yaml/渠道进程 |
| 子 Agent 委派 | ✅ runtime.spawn() | ✅ 实测：agent(prompt, label=, phase=) 每调用一个 worker；parallel() 并发 |
| 结构化返回 | ✅ 最终回答中提取 JSON | ✅ 实测：schema= pydantic/JSONSchema，经 structured_output 工具强类型提交 |
| 自定义工具注入（9 工具） | ✅ OpenAI function schema 直下 | ✅ 实测：@tool 装饰器 + spec.model_copy(update={"tools": [...]})（未文档化内部模式） |
| MCP 工具 | ➖ 不需要 | ✅ 实测：DeepAgentSpec.mcps + stdio server（断开有 anyio 噪音异常，不影响结果） |
| 事件订阅→SSE | ✅ event_sink（AgentEvent） | ✅ 实测：progress_sink 收全量 WorkflowProgressEvent（13 种 kind）；WorkflowObserver.on_event 可桥 SSE |
| 取消 | ✅ 步骤边界+工具入口协作式 | ✅ 实测：AbortSignal.set("stop")→WorkflowAborted；协作式，在飞调用完成但不落 journal；建议叠加 task.cancel() |
| 预算 | ✅ Budget(max_steps/tool_calls/tokens) 本地强制 | ✅ 实测：双层 BudgetLedger（会话级+per-run），超限抛 BudgetExhausted |
| 持久化/断点续跑 | ➖ 由任务 checkpoint 承担 | ✅ 实测：journal+WAL 内容寻址，同 run_id 续跑 0 次 LLM 调用结果一致 |
| 多轮有状态会话 | ✅ messages 列表自然多轮 | ⚠️ agent_session() 源码验证完整、未端到端实测（落地时先补验证） |
| 流式 token | ❌（整段返回，SSE 只发阶段/摘要） | ❌（事件无 token 流）——t2d 不需要 |

**决策（阶段 1 决策门）**：SwarmFlow 探测 **GO**。**适配器已实现并通过集成验证**（`swarmflow/runtime.py`；`scripts/test_swarmflow_adapter.py` 在 var/probe-venv 下对真实引擎 6/6：工具 JSON Schema 直注、结果捕获、事件映射、token 统计）。toolloop 保持默认；`agent_config.yaml runtime: swarmflow` 可切换——**仅当 worker 环境可 import openjiuwen**（懒加载；不可用时 worker 打警告回退 toolloop，管理台切换返回 409 并说明）。系统 Python 与 worker 镜像默认不装 workswarm（依赖 google-adk 全家桶，与 FastAPI 栈有版本冲突风险）——这是部署环境决策，不是能力缺口。

### 沙箱（OpenSandbox 1.2.0，SDK 与 Server 同版本）

| 能力 | 结论 | 证据 |
|---|---|---|
| 生命周期 create→run→write→run→read→destroy | ✅ 实测 | destroy 后 docker ps -a 零残留（label opensandbox.io/id） |
| 资源限制 | ✅ 实测 | create 参数 resource={"cpu":"1","memory":"1Gi"} → docker NanoCpus=1e9/Memory=1GiB；2GiB 分配 1.17s 被 OOM kill（沙箱存活）；2 线程烧 4s 墙钟 process_time=3.99s（严格 1 vCPU） |
| 命令超时与取消 | ✅ 实测 | RunCommandOpts(timeout=5) 对 sleep 60 → 6s 被杀、沙箱仍可用；commands.interrupt() 2.06s 终止后台命令 |
| 网络隔离 | ⚠️ **opt-in，默认放通** | 不传 network_policy 时 pypi/宿主网关/裸 IP 全通；显式 NetworkPolicy(default_action="deny") 后全拦（egress sidecar 同 netns） |
| 文件/凭据边界 | ✅ 实测 | 沙箱间文件不互通；所有沙箱 Mounts=[]（零宿主挂载）；默认零 env 注入 |
| 异常清理 | ✅ 实测 | kill -9 server 后容器存活；重启按 label 收养并重建 TTL 定时器；孤儿 sidecar 有清理路径 |
| 鉴权 | ✅ 实测 | server.api_key + header OPEN-SANDBOX-API-KEY；无/错 key 401 |
| 冷启动延迟 | 实测数字 | 冷 5.08s / 暖 2.0–2.8s；每命令固定 ~1s 开销；destroy 1.35s；TTL 最小 60s（server 强制） |

## 2. 已知限制

### toolloop
- 无 token 级流式：SSE 只推送阶段与工具摘要（符合任务书"不展示隐藏推理"）。
- nudge 重试上限 MODEL_MAX_RETRIES=2：模型连续空响应时任务失败并解释原因，不静默降级。

### swarmflow
- 工具注入的 model_copy 模式是 0.2.x 未文档化内部用法，升级需回归测试。
- 每个 worker 默认有一次多模态探测调用（~319 tokens）；必须设 enable_read_image_multimodal=False 跳过。
- worker 系统提示含硬编码中文安全段；演示展示 prompt 时需知晓。
- 取消为协作式：在飞 LLM 调用会跑完（结果不落 journal，续跑重跑该节点）。
- 预算两层语义：脚本内 budget.* 只读 per-run 账本；会话级由宿主设置，两层都要设。
- parallel() 分支失败归 None 不抛：脚本需 compact()/判空，SSE 侧依赖 agent_failed 事件呈现。
- human()/human_session() 需团队 messager 渠道——t2d 不适用，澄清走 toolloop 的 clarification 事件或宿主层实现。
- 早期版本（0.2.x）：所有接口经 agent_adapter 边界层隔离，禁止上层直接 import openjiuwen。

### 沙箱（OpenSandbox）
- **禁网是 opt-in**：默认完全放通出网。t2d 适配层（run_isolated）必须每次显式传 NetworkPolicy(default_action="deny")——漏传即裸奔。
- 禁网沙箱内不能 pip install：pandas/numpy 等依赖必须预烧进 t2d 专用沙箱镜像（基于 python:3.12-slim）。
- 沙箱 TTL 最小 60s（server 422 强制）；t2d 设 TTL 10 分钟兜底 + finally destroy。
- 每命令 ~1s 固定开销：批量小命令应合并为单脚本执行。
- egress.mode 可升级 dns+nft（首版不需要）。

## 3. 事件映射（丢弃项记录）

| swarmflow 事件 | t2d SSE | 处理 |
|---|---|---|
| workflow_started | phase.started | 直映射 |
| phase / log | phase.started / phase.completed | 直映射 |
| agent_started / agent_completed / agent_failed | tool.started / tool.completed / task.failed(子) | 直映射；tokens 记入 agent_runs |
| human_prompt / human_replied | — | **丢弃**（t2d 澄清走宿主层，不适用） |
| workflow_paused / workflow_stopped | task.cancelled / task.failed | 按 reason 区分 |
| workflow_completed / workflow_failed | task.completed / task.failed | 直映射 |
| 事件无时间戳 | — | 引擎禁时钟（确定性续跑）；SSE 侧自打时间戳 |

toolloop 事件（AgentEvent）→ SSE 映射见 events.py SSE_EVENT_MAP，无丢弃项。

## 4. 回退触发条件

**swarmflow → toolloop**（任一即触发，当前均未触发）：
1. run_workflow() 无法脱离渠道进程运行 —— 已排除（实测通过）。
2. 9 工具注入不可行（直注与 MCP 双路径皆受阻）—— 已排除（双路径实测通过）。
3. 事件无法对接 SSE（无订阅接口）—— 已排除（progress_sink 实测）。
4. 升级后 model_copy 注入模式失效且无替代 —— 持续观察项。
5. swarmflow 适配器未通过 toolloop 的同一集成测试 —— 阶段 3 验证项。

**OpenSandbox → docker 直跑适配层**（任一即触发，当前均未触发）：
1. 资源限制不可配或无效 —— 已排除（实测 NanoCpus/Memory 生效 + OOM 行为正确）。
2. 禁网策略不可用或不生效 —— 已排除（deny 实测全拦；但注意 opt-in 语义，适配层强制显式传参）。
3. destroy 后容器残留 / 崩溃后清理不可靠 —— 已排除（零残留 + server 重启收养机制实测）。
4. 升级后 SDK 接口变动 —— 持续观察项（1.2.0 锁定版本）。
