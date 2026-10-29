"""SwarmFlow adapter — probe verdict GO (see boundaries.md §1).

Implementation lands in phase 3, after the toolloop baseline has the
end-to-end chain green. Contract: same AgentSession/AgentRuntime interface;
upper layers never import openjiuwen directly.

Integration recipe (validated by docs/phase-notes/swarmflow-probe.md):
- entry: openjiuwen.agent_teams.workflow.engine.runner.run_workflow()
- backend: TeamWorkerBackend + programmatic DeepAgentSpec
  (OpenAI-compatible ModelClientConfig -> litellm :4000)
- tools: @tool-decorated functions injected via
  spec.model_copy(update={"tools": [...]})  # undocumented internal pattern
- events: progress_sink -> AgentEvent (map in boundaries.md §3)
- cancel: AbortSignal.set("stop") + task.cancel()
- budget: two-layer BudgetLedger (session via run_workflow(budget=),
  per-run via META.workflow_token_limit)
- resume: journal run_id == task idempotency key
"""
