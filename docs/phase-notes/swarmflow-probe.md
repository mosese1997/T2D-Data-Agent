# SwarmFlow 编排引擎探测报告（JiuwenSwarm / workswarm 0.2.7）

- 日期：2026-10-30
- 探测人：框架验证（Claude Code agent）
- 目的：实测 SwarmFlow 能否被 t2d 以无 UI、编程方式使用，作为 `runtime: toolloop|swarmflow` 可切换实现的 go/no-go 依据。
- 探测 venv：`/root/rappi_t2d/var/probe-venv`（workswarm 0.2.7，openjiuwen 0.1.19，pydantic 2.14.2，mcp 1.30.0，fastmcp 3.4.0）
- 模型：本机 LiteLLM `http://localhost:4000/v1`（OpenAI 兼容），`t2d/deepseek-v4.1-flash-1017`。API key 来自 `/root/litellm/.env` 的 `LITELLM_MASTER_KEY`，仅经环境变量传入脚本，未打印、未落盘。
- 探测脚本：`/root/rappi_t2d/var/probe-scripts/swarmflow_probe.py`（引擎无 UI 驱动/取消/预算）、`swarmflow_probe_harness.py`（真实后端+自定义工具）、`swarmflow_probe_resume_mcp.py`（持久化续跑+MCP）、`mcp_echo_server.py`（最小 stdio MCP server）、workflow 样例 `wf_min.py`/`wf_cancel.py`/`wf_budget.py`/`wf_tool.py`/`wf_mcp.py`。

## 0. 结论摘要

**GO** —— SwarmFlow 引擎可以完全脱离其 TUI/Web/飞书渠道进程，以纯库方式编程驱动。t2d 要求的全部能力（无 UI 运行、子 Agent 委派、结构化返回、自定义 Python 工具注入、事件流、协作式取消、预算、持久化续跑）均有实测通过证据；MCP 工具注入亦实测通过。建议作为 `agent_config.yaml` 的 `runtime: swarmflow` 可切换实现落地，注意事项见 §5。

## 1. 源码勘察

安装位置：`/root/rappi_t2d/var/probe-venv/lib/python3.12/site-packages/openjiuwen/agent_teams/workflow/`

```
workflow/
├── engine/                 # 业务无关的编排引擎（不 import agent_teams 业务层）
│   ├── facade.py           # `swarmflow` 公共原语（sys.modules 别名注册）
│   ├── primitives.py       # agent/parallel/pipeline/verify/AgentSession 实现
│   ├── runner.py           # run_workflow() —— 顶层编程入口
│   ├── runtime.py          # Runtime / AbortSignal
│   ├── budget.py           # BudgetLedger
│   ├── errors.py           # EngineError/BudgetExhausted/WorkflowAborted/...
│   ├── progress.py         # WorkflowProgressEvent / ProgressKind / progress_sink
│   ├── loader.py           # META + async def run(args) 脚本加载（ast 提取 META）
│   ├── journal.py          # 内容寻址缓存日志（resume/WAL）
│   └── backends/           # AgentBackend 抽象 + MockBackend
├── backends/
│   ├── team_worker_backend.py  # 生产后端：每个 agent() → 一次性 DeepAgent worker
│   ├── avatar_session_backend.py # agent_session()/human_session() 的有状态会话
│   └── budget_rail.py          # 把 token 记账挂进 worker 的模型调用回路
├── runner.py               # run_swarmflow()（团队集成入口，供 swarmflow() 工具调用）
├── observer.py             # WorkflowObserver：事件流 → 4 层 WorkflowRun
└── tool_swarmflow.py       # 团队 leader 的 swarmflow() 工具封装（TUI 走这条）
```

### 1.1 关键真实签名（引自源码）

引擎入口 `engine/runner.py`：

```python
async def run_workflow(
    path: str, *, args: Any = None,
    backend: AgentBackend | None = None,      # 可插拔；默认 MockBackend
    resume: str | None = None, journal_path: str | None = None,
    wal_path: str | None = None, strict: bool = False,
    log_sink: Callable[[str], None] | None = None,
    progress_sink: ProgressSink | None = None, # 事件订阅接口
    cap: int | None = None, agent_gate: AgentAdmission | None = None,
    budget: BudgetLedger | None = None,        # 会话级 token 上限
    workflow_budget: BudgetLedger | None = None, # 单次运行上限（默认取 META.workflow_token_limit）
    abort_event: AbortSignal | None = None,    # 协作式暂停/停止信号
    run_id: str | None = None,
) -> Any
```

脚本原语 `engine/facade.py`（`from swarmflow import ...`，模块在 import 时以 `sys.modules["swarmflow"]` 别名注册，无需安装包）：

```python
async def agent(prompt, *, label=None, phase=None, schema=None, options=None)
    # schema=PydanticModel -> MyModel|None；schema=JSONSchema dict -> dict|None；None -> str|None
    # options 白名单键：label/phase/schema/model/timeout/isolation/agent_type
    #   ∪ backend.KNOWN_OPTIONS，未知键 raise EngineError
async def parallel(thunks) -> list      # fork-join 屏障，失败分支归 None，不抛
async def pipeline(items, *stages)      # 无屏障流式
async def map_parallel(items, fn)       # 防 late-binding 的 fan-out（别名 pmap）
def phase(title) / def log(message)
async def workflow(name_or_path, args)  # 内联子工作流（深度限 1）
def agent_session(*, label, phase, instructions, options) -> AgentSession  # 多轮有状态
async def human(prompt, *, schema, label, phase, options)  # 一次性人类回合（需团队 messager）
budget  # 单例：budget.total / budget.spent() / budget.remaining() —— 读的是"本次运行"账本
```

后端抽象 `engine/backends/base.py`：

```python
class AgentBackend(abc.ABC):
    KNOWN_OPTIONS: frozenset[str]
    def bind_budget(self, budget: BudgetLedger) -> None      # 后端是账本唯一写入者
    def bind_workflow_budget(self, workflow_budget) -> None
    @abc.abstractmethod
    async def run(self, prompt, opts, schema_json, *, call_key=None) -> AgentResult
    # 可选四件套 open_session/send_turn/close_session/aclose 支撑 agent_session()
```

取消 `engine/runtime.py`：

```python
@dataclass
class AbortSignal:
    event: asyncio.Event = field(default_factory=asyncio.Event)
    reason: str = "pause"          # "pause"（可续跑）| "stop"（终态）
    def set(self, reason: str = "pause") -> None
```

预算 `engine/budget.py`：`BudgetLedger(total=None, spent=0)`，`add/add_phase/remaining/exhausted`；超限抛 `BudgetExhausted(message, scope="session"|"workflow", spent, total, workflow_spent, workflow_total, top_phases)`（`BaseException`，不会被编排层 `except Exception` 吞掉）。

### 1.2 全局状态 / 配置依赖

- **引擎层零配置**：`engine/` 不 import agent_teams 业务层，无 config.yaml、无单例、无渠道进程依赖。运行态经 `contextvars`（`_rt/_path/_seq`）绑定，同进程并发多个 run 互相隔离（`primitives.py` 模块 docstring 明示）。
- **状态落盘位置**：`openjiuwen.agent_teams.paths.get_openjiuwen_home()` = `OPENJIUWEN_HOME` 环境变量，缺省 `~/.openjiuwen`。可用该变量把 worker 工作区/日志钉到 t2d 自己的目录。实测（§2 探测 2）未产生任何持久化工作区目录（worker 用 in-memory checkpoint，`storage_type: inmemory`）。
- **TUI/Web/飞书渠道**：只是引擎的"嵌入方"之一——TUI 走 `tool_swarmflow.py` → `run_swarmflow()` → `run_workflow()`；我们直接调 `run_workflow()` 即可，完全绕开渠道进程。

## 2. 实测记录

### 探测 A：无 UI 驱动（`swarmflow_probe.py`）—— ✅ PASS

自写 60 行 `LitellmBackend(AgentBackend)`（httpx 直连 LiteLLM `/chat/completions`，把 usage tokens 记入绑定账本），`run_workflow()` 驱动 `wf_min.py`（META + `async def run(args)`，含 pydantic schema agent、纯文本 agent、`parallel()` 两个分支、`phase()`/`log()`/`budget.*`）。无 config.yaml、无 UI、无渠道进程。

实测输出（节选）：

```
A. run_workflow returned:
{"structured": {"answer": "4", "confidence": 1.0}, "plain": "ok",
 "parallel": ["p1", "p2"], "budget_total": 20000, "budget_spent": 327, "budget_remaining": 19673}
A. event kinds: ['workflow_started','phase','log','agent_started','agent_completed',
 'phase','agent_started','agent_completed','agent_started','agent_started',
 'agent_completed','agent_completed','workflow_completed']
A. PASS
```

### 探测 B：协作式取消（AbortSignal）—— ✅ PASS

6 步顺序 agent 工作流，6 秒后 `abort.set("stop")`：

```
[probe] abort_event.set('stop') fired
B. PASS: WorkflowAborted reason='stop'
```

语义（源码 `primitives.py::_check_abort` + `runner.py`）：abort 在每个 `agent()` 的入口门与"pre-journal 门"检查——**在飞的 LLM 调用会自然完成但不落 journal**（续跑会重跑该节点）；`CancelledError` 路径（直接 `task.cancel()`）也被 `runner.py` 显式处理（stop 时写 seal 记录）。对 t2d SSE 取消：`abort_event.set("stop")` + 视需要 `task.cancel()` 即可，双保险。

### 探测 C：预算控制 —— ✅ PASS

`BudgetLedger(total=30)` 传入 `run_workflow(budget=...)`，首个 agent 实耗 38 tokens：

```
C. PASS: BudgetExhausted scope='session' spent=38 total=30 top_phases=[('B', 38)]
C. message: session token budget exhausted: 38/30
```

事件流同时给出终态事件 `workflow_stopped`（session 超限）并附 `budget_exhausted_scope:"session"`；workflow 级（`META.workflow_token_limit`）超限则发 `workflow_failed`（可通过改脚本续跑）。注意语义细节：**脚本内 `budget.*` 读的是 per-run 账本**（`META.workflow_token_limit`），会话级账本只在宿主侧可见/可设——t2d 服务端应同时设两层。

### 探测 2：生产后端 + 自定义 Python 工具注入（`swarmflow_probe_harness.py`）—— ✅ PASS

不写自定义 backend，直接用生产链路 `TeamWorkerBackend`（每个 `agent()` → 一次性 DeepAgent worker，走 `TeamHarness.run_once`）：

- 模型：`TeamModelConfig(model_client_config=ModelClientConfig(client_provider="OpenAI", api_key=..., api_base="http://localhost:4000/v1"), model_request_config=ModelRequestConfig(model="t2d/deepseek-v4.1-flash-1017"))` —— OpenAI 兼容代理一等支持。
- 工具：两个 `@tool` 装饰的普通 async Python 函数（`get_order_total`/`count_orders_by_status`，schema 自动从签名提取）。**注入方式**：`DeepAgentSpec.tools` 的 pydantic 校验只收 `ToolCard|BuiltinToolSpec`，Tool 实例须经 `spec.model_copy(update={"tools": [...]})` 注入——这正是框架自身给 worker 注入 `StructuredOutputTool` 的同一模式（`team_worker_backend.py` → `derive_member_spec()`，`model_copy` 不复检）。
- 结构化输出：`agent(schema=OrderReport)` → 引擎自动加 `structured_output` 工具 + `StructuredOutputFinishRail`，worker 必须以工具调用提交结果。

实测结果（模型真实调用了两个自定义工具，再以 structured_output 提交）：

```
run_workflow returned:
{"query_text": "Order O-1001 totals 12,500 cents, and there are 42 paid orders.",
 "report": {"order_id": "O-1001", "total_cents": 12500, "currency": "COP", "paid_order_count": 42}}
agent_completed label=query tokens=1461
agent_completed label=report tokens=2272
=== probe result: PASS (tools + schema through real harness) ===
```

全程无 config.yaml、无团队进程、无 UI；`enable_sys_operation=False` 后 worker 无文件系统/shell 工具，纯数据工具型 agent 可行。未产生持久化工作区目录（checkpoint 为 inmemory）。

### 探测 D：持久化与断点续跑（`swarmflow_probe_resume_mcp.py`）—— ✅ PASS

`run_workflow(journal_path=..., run_id="probe-run-1")` 首跑 4 次 LLM 调用；同 `run_id` + `resume=journal` 重跑：

```
D. first run: llm_calls=4 spent1_ok=True
D. resume run: llm_calls=0 (expect 0)
D. results identical on resume: True
D. PASS
```

journal 为内容寻址缓存（调用路径 key + prompt/opts/schema 签名 + run_id 隔离），WAL 为崩溃恢复边车；`run_id` 不同则永不命中旧缓存。对 t2d：任务重试/幂等可直接复用该机制。

### 探测 E：MCP 工具注入 —— ✅ PASS

`DeepAgentSpec.mcps=[McpServerConfig(server_name="echo", client_type="stdio", params={"command": venv_python, "args": ["mcp_echo_server.py"]})]`（fastmcp 3.4.0 写的 1 工具 stdio server）。worker 经 harness 的 MCP rail 挂载远端工具并真实调用：

```
E. run_workflow returned: 'echo: hello-mcp'
E. PASS
```

限制：stdio 客户端断开时有一个 anyio cancel-scope 噪音异常（`RuntimeError: Attempted to exit cancel scope in a different task`），不影响工具调用结果，但日志需过滤。client_type 另支持 `sse`/`streamable-http`（`core/foundation/tool/mcp/client/`）。

## 3. 事件流对接 SSE（源码证据 + 实测）

- 订阅接口就是 `run_workflow(progress_sink=...)`：每个 `WorkflowProgressEvent`（frozen dataclass，`progress.py`）同步回调一次。kind 集合：`workflow_started/phase/log/agent_started/agent_completed/agent_failed/human_prompt/human_replied/workflow_completed/workflow_failed/workflow_paused/workflow_stopped`。字段含 `phase/label/prompt/model/outcome/message/tokens/budget/workflow_budget/agent_id/node_type/correlation_id` 等，`dataclasses.asdict` 即可 JSON 化（探测 A 已验证）。
- TUI 复用的 `WorkflowObserver`（`workflow/observer.py`）本身就是纯 Python 类：`emit()` 累积事件 + 可选 `on_event` 回调扇出，`observer.run` 随时折叠成 4 层 `WorkflowRun`（Phase ▸ agents ▸ prompt/activity/outcome），`to_frontend()` 输出 JSON。t2d 的 SSE 桥可直接：`WorkflowObserver(on_event=lambda ev: sse_publish(seq++, asdict(ev)))`，满足"只展示真实阶段与工具摘要、带递增 seq"的要求——事件里没有隐藏推理，只有 prompt 摘要/结果预览/token 数。
- 注意：事件刻意无时间戳（引擎禁时钟保证确定性续跑），SSE 侧自行打时间戳。

## 4. 能力矩阵

| 能力 | 结论 | 证据 |
|---|---|---|
| 无 UI 编程运行 | ✅ 实测通过 | 探测 A/2：`run_workflow()` 纯库调用，无 config.yaml/渠道进程；引擎层零全局状态（contextvars） |
| 子 Agent 委派（主→查询/分析） | ✅ 实测通过 | `agent(prompt, label=, phase=)` 每调用一个 worker；`parallel()` 实测两分支并发；生产后端实测（探测 2） |
| 结构化返回 `schema=` | ✅ 实测通过 | pydantic 模型与 JSON Schema dict 双支持；探测 A（`Answer`）与探测 2（`OrderReport` 经 structured_output 工具）均返回强类型对象 |
| 自定义工具注入（9 个 Python 函数） | ✅ 实测通过 | `@tool` 装饰器（`core/foundation/tool/tool.py`，签名自动提 schema）+ `spec.model_copy(update={"tools": [...]})` 注入；探测 2 模型真实调用两个工具并取回正确值 |
| MCP 工具 | ✅ 实测通过 | `DeepAgentSpec.mcps` + stdio server 实测（探测 E）；另支持 sse/streamable-http；断开时有噪音异常（不影响结果） |
| 事件订阅（→SSE） | ✅ 实测通过 | `progress_sink` 收全量结构化事件（探测 A 13 事件全 dump）；`WorkflowObserver.on_event` 可直接桥接 SSE |
| 取消 | ✅ 实测通过（协作式） | `AbortSignal.set("stop")` → `WorkflowAborted(reason='stop')`（探测 B）；在飞调用不落 journal；可叠加 `task.cancel()`（runner 有 seal 处理）。限制：非抢占式，在飞 LLM 调用会跑完 |
| 预算 | ✅ 实测通过 | 双层账本：会话级 `run_workflow(budget=BudgetLedger(total=N))` + per-run `META.workflow_token_limit`；超限抛 `BudgetExhausted(scope, spent, total, top_phases)`（探测 C）；后端按真实 usage 记账、可在 agent 循环中途截断（budget_rail） |
| 持久化/续跑 | ✅ 实测通过 | journal+WAL 内容寻址缓存；同 run_id 续跑 0 次 LLM 调用、结果一致（探测 D）；`run_id` 隔离并发运行 |
| 多轮有状态会话 `agent_session()` | ⚠️ 源码验证、未实测 | `AgentSession.send()/fork()/aclose()` + `AvatarSessionManager` 完整实现；t2d 主 Agent 对话可用，但本次未跑通端到端（单次 `agent()` 已覆盖 t2d 子 Agent 场景） |
| `human()/human_session()` | ❌ 不适用于 t2d | 需团队 messager/回复主题（飞书等渠道）；t2d 无此需求，忽略 |

## 5. 集成注意事项（GO 的附带条件）

1. **工具注入用 `model_copy` 模式**：`DeepAgentSpec.tools` 校验只收 `ToolCard`；Tool 实例（`@tool` 产物）经 `spec.model_copy(update={"tools": [...]})` 注入。这是框架自身注入 `StructuredOutputTool` 的同款内部用法，0.2.x 未文档化——升级时需回归测试。
2. **每个 worker 有一次多模odal 探测调用**：harness 会对模型发一张 1x1 图片问颜色（探测 2 日志可见，~319 tokens + 一次往返）。`DeepAgentSpec.enable_read_image_multimodal=False` 可跳过该探测，t2d 应设置。
3. **worker 系统提示带硬编码中文安全段**（`swarmflow_worker` locale + 安全原则），与 `language="en"` 并存。对 t2d 无害，但演示时若展示 prompt 需知晓。
4. **取消是协作式**：abort 在 agent() 边界生效；SSE 取消建议 `abort_event.set("stop")` + `task.cancel()` 组合并容忍在飞调用完成（结果不落 journal）。
5. **预算两层语义**：脚本内 `budget.*` 只读 per-run 账本；会话级上限由宿主设置。t2d 服务端应同时设 `budget=`（任务级）与 `META.workflow_token_limit`（工作流级），且后者不得超过前者（`MetaError` 校验）。
6. **并发上限**：默认 `min(16, cpu_count-2)`（`cap.py`），可用 `run_workflow(cap=N)` 或 `agent_gate` 覆盖；`parallel()` 单次 fan-out 上限 4096。
7. **状态目录**：设 `OPENJIUWEN_HOME` 环境变量把框架状态（如启用 sys_operation 时的 worker 工作区）钉进 t2d 管理的目录；本次探测未产生持久化目录。
8. **重试语义**：后端/校验失败默认重试 2 次（`Runtime.retries=2`）；`parallel()` 分支失败归 `None` 不抛——工作流脚本需用 `compact()`/判空处理，或依赖 `agent_failed` 事件在 SSE 侧呈现。
9. **版本**：workswarm 0.2.7 / openjiuwen 0.1.19 为早期版本，API 可能变动；建议在 `packages/agent_adapter` 边界层（见 `boundaries.md`）隔离这些接口，便于升级。

## 6. go/no-go

**GO**：SwarmFlow 作为 t2d 的 `runtime: swarmflow` 可切换实现。推荐形态：

- 引擎入口 `openjiuwen.agent_teams.workflow.engine.run_workflow()`（或薄封装 `run_swarmflow()`）；
- 后端用生产 `TeamWorkerBackend` + 程序化 `DeepAgentSpec`（litellm OpenAI 兼容模型 + `@tool` 注入 9 个工具 + `enable_sys_operation=False` + `enable_read_image_multimodal=False`）；
- SSE 桥用 `progress_sink`/`WorkflowObserver.on_event`；取消用 `AbortSignal`+`task.cancel()`；预算用双层 `BudgetLedger`；任务幂等/重试复用 journal `run_id` 机制。
- 自建 toolloop 保留为默认实现，SwarmFlow 以配置切换——两实现边界记录进 `packages/agent_adapter/boundaries.md`。

未实测项（`agent_session()` 有状态多轮、`verify()` 评审、`isolation="worktree"`）不阻塞 go；如主 Agent 需要多轮对话上下文，落地时先补一次 `agent_session()` 端到端验证。
