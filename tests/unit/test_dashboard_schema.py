"""Unit tests: canvas schema, patches, diff, validation."""

import pytest

from dashboard_schema import (
    Canvas,
    Patch,
    apply_patch,
    detect_conflict,
    summarize_changes,
    validate_canvas,
)


@pytest.fixture()
def base_canvas():
    return Canvas(title="GMV 看板", filters={"allowed": ["country", "date"]})


@pytest.fixture()
def sample_patch():
    return Patch.model_validate({
        "base_revision": 1,
        "operations": [
            {"op": "set_title", "value": {"title": "上周 GMV"}},
            {"op": "add_component", "value": {
                "id": "c1", "type": "metric_card", "title": "GMV",
                "source_id": "s1", "field": "gmv", "span": 3}},
            {"op": "add_component", "value": {
                "id": "c2", "type": "line_chart", "title": "趋势",
                "source_id": "s1", "x": {"field": "day"},
                "series": [{"field": "gmv", "name": "GMV"}], "span": 9}},
        ],
    })


def test_apply_patch(base_canvas, sample_patch):
    after = apply_patch(base_canvas, sample_patch)
    assert after.title == "上周 GMV"
    assert len(after.components) == 2
    assert after.layout.order == ["c1", "c2"]


def test_apply_patch_does_not_mutate_original(base_canvas, sample_patch):
    before_count = len(base_canvas.components)
    apply_patch(base_canvas, sample_patch)
    assert len(base_canvas.components) == before_count


def test_duplicate_component_id_rejected(base_canvas):
    patch = Patch.model_validate({
        "base_revision": 1,
        "operations": [
            {"op": "add_component", "value": {"id": "c1", "type": "text_block", "content": "a"}},
            {"op": "add_component", "value": {"id": "c1", "type": "text_block", "content": "b"}},
        ],
    })
    with pytest.raises(ValueError):
        apply_patch(base_canvas, patch)


def test_update_unknown_component_rejected(base_canvas):
    patch = Patch.model_validate({
        "base_revision": 1,
        "operations": [{"op": "update_component", "target": "ghost", "value": {"title": "x"}}],
    })
    with pytest.raises(ValueError):
        apply_patch(base_canvas, patch)


def test_conflict_detection(sample_patch):
    assert detect_conflict(sample_patch, current_revision=2)
    assert not detect_conflict(sample_patch, current_revision=1)


def test_diff_summary(base_canvas, sample_patch):
    after = apply_patch(base_canvas, sample_patch)
    summary = summarize_changes(base_canvas, after, sample_patch)
    assert "标题" in summary
    assert "新增" in summary


def test_validate_ok(base_canvas, sample_patch):
    after = apply_patch(base_canvas, sample_patch)
    sources = {"s1": {"workspace_id": 1, "col_schema": [{"name": "day"}, {"name": "gmv"}]}}
    assert validate_canvas(after, sources=sources, workspace_id=1) == []


def test_validate_workspace_mismatch(base_canvas, sample_patch):
    after = apply_patch(base_canvas, sample_patch)
    sources = {"s1": {"workspace_id": 2, "col_schema": [{"name": "day"}, {"name": "gmv"}]}}
    errors = validate_canvas(after, sources=sources, workspace_id=1)
    assert any(e["code"] == "source_workspace_mismatch" for e in errors)


def test_validate_unknown_field(base_canvas, sample_patch):
    after = apply_patch(base_canvas, sample_patch)
    sources = {"s1": {"workspace_id": 1, "col_schema": [{"name": "day"}]}}
    errors = validate_canvas(after, sources=sources, workspace_id=1)
    assert any(e["code"] == "unknown_field" for e in errors)


def test_validate_filter_not_allowed(base_canvas):
    canvas = Canvas.model_validate({
        "filters": {"allowed": ["country"]},
        "components": [{"id": "f1", "type": "filter", "filter_key": "date"}],
    })
    errors = validate_canvas(canvas, sources={}, workspace_id=1)
    assert any(e["code"] == "filter_not_allowed" for e in errors)


def test_json_roundtrip(base_canvas, sample_patch):
    after = apply_patch(base_canvas, sample_patch)
    assert Canvas.model_validate_json(after.model_dump_json()) == after
