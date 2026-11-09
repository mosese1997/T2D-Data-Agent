"""E3: Temporal worker — runs the workflow definitions.

Replaces the SQLite queue poller: Temporal's task queue replaces our
lease/heartbeat/reaper. The worker polls Temporal (not SQLite), executes
Activities that call the same runner logic, and the API starts workflows
instead of enqueuing task rows (task rows still exist for SSE/snapshot).

Run: python -m t2d_worker.temporal_worker
"""

from __future__ import annotations

import asyncio
import os
import sys

from concurrent.futures import ThreadPoolExecutor
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from .temporal_workflows import (
    BuildDashboardWorkflow,
    RefreshWorkflow,
    run_intent_phase,
    run_query_phase,
    run_design_phase,
    run_analysis_phase,
    run_answer_phase,
    finalize_task,
)

TASK_QUEUE = "t2d-tasks"
TEMPORAL_HOST = os.environ.get("TEMPORAL_HOST", "127.0.0.1:7233")


async def main() -> None:
    client = await Client.connect(TEMPORAL_HOST)
    print(f"[temporal-worker] connecting to {TEMPORAL_HOST}, queue: {TASK_QUEUE}",
          flush=True)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[BuildDashboardWorkflow, RefreshWorkflow],
        activities=[run_intent_phase, run_query_phase, run_design_phase,
                    run_analysis_phase, run_answer_phase, finalize_task],
        activity_executor=ThreadPoolExecutor(4),
        workflow_runner=UnsandboxedWorkflowRunner(),
    )
    print("[temporal-worker] started — waiting for workflows", flush=True)
    await worker.run()


async def start_task_workflow(
    *,
    task_id: int,
    task_type: str,
    payload: dict,
) -> str:
    """Called by the API to start a workflow (replaces queue.enqueue).

    Workflow ID = t2d-{task_type}-{task_id} (idempotent).
    """
    client = await Client.connect(TEMPORAL_HOST)
    workflow_id = f"t2d-{task_type}-{task_id}"
    payload["task_id"] = task_id

    if task_type == "refresh":
        handle = await client.start_workflow(
            RefreshWorkflow.run, payload,
            id=workflow_id, task_queue=TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE)
    else:
        handle = await client.start_workflow(
            BuildDashboardWorkflow.run, payload,
            id=workflow_id, task_queue=TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE)
    return workflow_id


if __name__ == "__main__":
    asyncio.run(main())
