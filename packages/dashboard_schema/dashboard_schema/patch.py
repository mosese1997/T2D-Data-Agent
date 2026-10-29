"""Candidate patches: operations against a base revision.

Flow: the agent proposes a patch bound to base_revision → validation →
user previews the diff → Apply atomically creates revision+1. If the
dashboard's current revision moved past base_revision, the patch is marked
conflict and must be regenerated (never auto-merged).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .canvas import Canvas, Component


class PatchOperation(BaseModel):
    op: Literal[
        "add_component",
        "update_component",
        "remove_component",
        "set_layout",
        "set_title",
        "set_filters",
    ]
    target: str | None = None  # component id for component ops
    value: dict[str, Any] = Field(default_factory=dict)


class Patch(BaseModel):
    base_revision: int
    operations: list[PatchOperation]
    change_summary: str = ""
    # component_id -> source_id bindings introduced by this patch
    source_bindings: dict[str, str] = Field(default_factory=dict)


class PatchConflict(Exception):
    """base_revision no longer matches the dashboard's current revision."""

    def __init__(self, base_revision: int, current_revision: int):
        super().__init__(
            f"patch base_revision={base_revision} but dashboard is at "
            f"revision={current_revision}; regenerate the candidate patch"
        )
        self.base_revision = base_revision
        self.current_revision = current_revision


def detect_conflict(patch: Patch, current_revision: int) -> bool:
    return patch.base_revision != current_revision


def apply_patch(canvas: Canvas, patch: Patch) -> Canvas:
    """Pure function: apply operations to a canvas, returning a new Canvas.

    Raises ValueError on structurally invalid operations (unknown target,
    duplicate id, etc.). Callers wrap this in the Apply transaction.
    """
    result = canvas.model_copy(deep=True)
    for operation in patch.operations:
        result = _apply_one(result, operation)
    return result


def _apply_one(canvas: Canvas, op: PatchOperation) -> Canvas:
    if op.op == "set_title":
        canvas.title = str(op.value.get("title", canvas.title))
        return canvas

    if op.op == "set_layout":
        if "grid_cols" in op.value:
            canvas.layout.grid_cols = int(op.value["grid_cols"])
        if "order" in op.value:
            canvas.layout.order = list(op.value["order"])
        return canvas

    if op.op == "set_filters":
        if "allowed" in op.value:
            canvas.filters.allowed = list(op.value["allowed"])
        if "defaults" in op.value:
            canvas.filters.defaults = dict(op.value["defaults"])
        return canvas

    if op.op == "add_component":
        component = Component.model_validate(op.value)
        if canvas.component_by_id(component.id) is not None:
            raise ValueError(f"component id already exists: {component.id}")
        canvas.components.append(component)
        if component.id not in canvas.layout.order:
            canvas.layout.order.append(component.id)
        return canvas

    if op.op == "update_component":
        target = canvas.component_by_id(op.target or "")
        if target is None:
            raise ValueError(f"unknown component: {op.target}")
        updates = {k: v for k, v in op.value.items() if k != "id"}
        updated = target.model_copy(update=updates)
        canvas.components = [
            updated if c.id == updated.id else c for c in canvas.components
        ]
        return canvas

    if op.op == "remove_component":
        target_id = op.target or ""
        if canvas.component_by_id(target_id) is None:
            raise ValueError(f"unknown component: {target_id}")
        canvas.components = [c for c in canvas.components if c.id != target_id]
        canvas.layout.order = [cid for cid in canvas.layout.order if cid != target_id]
        return canvas

    raise ValueError(f"unknown operation: {op.op}")
