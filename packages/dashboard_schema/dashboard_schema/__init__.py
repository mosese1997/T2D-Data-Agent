"""dashboard_schema — canvas JSON contract, patches, diff, validation."""

from .canvas import Canvas, Component, ComponentType, Layout, Filters
from .patch import Patch, PatchOperation, apply_patch, detect_conflict
from .diff import summarize_changes
from .validate import validate_canvas, ValidationError

__all__ = [
    "Canvas", "Component", "ComponentType", "Layout", "Filters",
    "Patch", "PatchOperation", "apply_patch", "detect_conflict",
    "summarize_changes", "validate_canvas", "ValidationError",
]
