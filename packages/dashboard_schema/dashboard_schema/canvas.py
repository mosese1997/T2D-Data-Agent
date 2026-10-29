"""Canvas JSON models (schema_version 1.0, task book §12).

Component types: metric_card, line_chart, bar_chart, data_table, text_block,
filter. Data components bind a Source ID + fields; validation checks the
bound fields against the source's col_schema (validate.py).
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ComponentType(str, Enum):
    METRIC_CARD = "metric_card"
    LINE_CHART = "line_chart"
    BAR_CHART = "bar_chart"
    DATA_TABLE = "data_table"
    TEXT_BLOCK = "text_block"
    FILTER = "filter"


class DateRange(BaseModel):
    type: str = "last_n_days"  # last_n_days | natural_week | custom
    n: int | None = None
    anchor: str = "today"


class Filters(BaseModel):
    allowed: list[str] = Field(default_factory=list)  # e.g. country/date/channel
    defaults: dict[str, Any] = Field(default_factory=dict)


class Layout(BaseModel):
    grid_cols: int = 12
    order: list[str] = Field(default_factory=list)  # component ids


class SeriesSpec(BaseModel):
    field: str
    name: str | None = None
    split_by: str | None = None  # dimension column to split series on


class DisplaySpec(BaseModel):
    unit: str | None = None  # currency | percent | number | duration
    precision: int | None = None
    comparison: str | None = None  # wow | dod | None — zero denominators render "—"
    legend: bool = True
    stacked: bool = False
    page_size: int = 20


class Component(BaseModel):
    id: str
    type: ComponentType
    title: str = ""
    span: int = 4  # of layout.grid_cols
    # Data components: which source and which fields.
    source_id: str | None = None
    field: str | None = None  # metric_card value field
    x: dict[str, Any] | None = None  # {"field": "day"}
    series: list[SeriesSpec] = Field(default_factory=list)
    columns: list[str] | None = None  # data_table
    content: str | None = None  # text_block (caliber notes etc.)
    filter_key: str | None = None  # filter component: which allowed key
    display: DisplaySpec = Field(default_factory=DisplaySpec)


class Canvas(BaseModel):
    schema_version: str = "1.0"
    title: str = ""
    filters: Filters = Field(default_factory=Filters)
    layout: Layout = Field(default_factory=Layout)
    components: list[Component] = Field(default_factory=list)

    def component_by_id(self, component_id: str) -> Component | None:
        return next((c for c in self.components if c.id == component_id), None)
