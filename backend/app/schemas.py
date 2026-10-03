"""Shared contracts: the metadata wrapper, the data-request grammar, the widget
catalog and the agent's operation language."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Business metadata wrapper
# ---------------------------------------------------------------------------

ReviewStatus = Literal["draft", "needs_review", "approved", "rejected", "missing"]
SemanticType = Literal["identifier", "dimension", "measure", "time", "text", "flag"]


class ColumnMeta(BaseModel):
    name: str
    data_type: str = ""
    nullable: bool = True
    primary_key: bool = False
    description: str = ""
    unit: str | None = None
    semantic_type: SemanticType | None = None
    # Allowed values discovered from constraints, and their business meaning once known.
    allowed_values: list[str] = Field(default_factory=list)
    coded_values: dict[str, str] = Field(default_factory=dict)
    status: ReviewStatus = "draft"
    confidence: float = 0.0
    ambiguities: list[str] = Field(default_factory=list)
    restricted: bool = False
    schema_change: str | None = None  # e.g. "added", "type_changed: INTEGER -> TEXT"


class TableMeta(BaseModel):
    name: str
    description: str = ""
    row_meaning: str = ""
    status: ReviewStatus = "draft"
    confidence: float = 0.0
    ambiguities: list[str] = Field(default_factory=list)
    restricted: bool = False
    schema_change: str | None = None
    columns: list[ColumnMeta] = Field(default_factory=list)

    def column(self, name: str) -> ColumnMeta | None:
        return next((c for c in self.columns if c.name == name), None)


class RelationshipMeta(BaseModel):
    """Directional join: many rows of from_table reference one row of to_table."""

    id: str
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    cardinality: Literal["many_to_one", "one_to_one"] = "many_to_one"
    origin: Literal["declared", "inferred", "manual"] = "declared"
    description: str = ""
    status: ReviewStatus = "draft"
    confidence: float = 0.0
    ambiguities: list[str] = Field(default_factory=list)


class Expr(BaseModel):
    """Arithmetic over columns: {column} | {literal} | {op, args}."""

    model_config = ConfigDict(extra="forbid")

    column: str | None = None
    literal: float | None = None
    op: Literal["add", "sub", "mul", "div"] | None = None
    args: list[Expr] | None = None

    @model_validator(mode="after")
    def _one_form(self) -> Expr:
        forms = [self.column is not None, self.literal is not None, self.op is not None]
        if sum(forms) != 1:
            raise ValueError("expression must have exactly one of column, literal or op")
        if self.op is not None and (not self.args or len(self.args) != 2):
            raise ValueError("arithmetic expressions take exactly two args")
        return self

    def columns(self) -> list[str]:
        if self.column:
            return [self.column]
        return [c for a in self.args or [] for c in a.columns()]


Aggregation = Literal["sum", "avg", "min", "max", "count", "count_distinct"]
ValueFormat = Literal["number", "integer", "currency", "percent", "text", "date"]


class MetricMeta(BaseModel):
    name: str  # identifier used in data requests
    label: str = ""
    description: str = ""
    agg: Aggregation
    expr: Expr
    format: ValueFormat = "number"
    status: ReviewStatus = "draft"
    confidence: float = 0.0
    ambiguities: list[str] = Field(default_factory=list)


class MetadataDoc(BaseModel):
    tables: list[TableMeta] = Field(default_factory=list)
    relationships: list[RelationshipMeta] = Field(default_factory=list)
    metrics: list[MetricMeta] = Field(default_factory=list)

    def table(self, name: str) -> TableMeta | None:
        return next((t for t in self.tables if t.name == name), None)


# ---------------------------------------------------------------------------
# Data requests (structured query plan, compiled by the execution service)
# ---------------------------------------------------------------------------

TimeGrain = Literal["day", "week", "month", "quarter", "year"]
FilterOp = Literal[
    "eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in", "between",
    "contains", "is_null", "not_null", "in_last_days",
]


class Dimension(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str  # "table.column"
    alias: str | None = None
    grain: TimeGrain | None = None

    @property
    def key(self) -> str:
        if self.alias:
            return self.alias
        col = self.field.split(".")[-1]
        return f"{col}_{self.grain}" if self.grain else col


class Measure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alias: str
    metric: str | None = None  # approved metric name
    agg: Aggregation | None = None
    field: str | None = None  # shorthand for expr={"column": field}
    expr: Expr | None = None

    @model_validator(mode="after")
    def _shape(self) -> Measure:
        if self.metric:
            if self.agg or self.field or self.expr:
                raise ValueError(f"measure '{self.alias}': use either metric or agg+field/expr")
        else:
            if not self.agg:
                raise ValueError(f"measure '{self.alias}': agg is required when metric is not set")
            if (self.field is None) == (self.expr is None) and self.agg != "count":
                raise ValueError(f"measure '{self.alias}': provide exactly one of field or expr")
        return self


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    op: FilterOp
    value: Any = None


class OrderBy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str  # a dimension or measure alias
    direction: Literal["asc", "desc"] = "asc"


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimensions: list[Dimension] = Field(default_factory=list)
    measures: list[Measure] = Field(default_factory=list)
    filters: list[Filter] = Field(default_factory=list)
    order_by: list[OrderBy] = Field(default_factory=list)
    limit: int | None = None
    # Relationship ids to prefer when more than one approved join path exists.
    via: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _non_empty(self) -> QueryPlan:
        if not self.dimensions and not self.measures:
            raise ValueError("a data request needs at least one dimension or measure")
        keys = [d.key for d in self.dimensions] + [m.alias for m in self.measures]
        if len(keys) != len(set(keys)):
            raise ValueError(f"output names must be unique, got {keys}")
        return self

    def output_keys(self) -> list[str]:
        return [d.key for d in self.dimensions] + [m.alias for m in self.measures]


# ---------------------------------------------------------------------------
# UI descriptions (component catalog)
# ---------------------------------------------------------------------------

WidgetType = Literal["kpi", "table", "bar", "line", "area", "pie"]


class Presentation(BaseModel):
    model_config = ConfigDict(extra="allow")
    x: str | None = None  # category/time key
    y: list[str] = Field(default_factory=list)  # value keys
    series: str | None = None  # optional key to split into series (pivot)
    stacked: bool = False
    horizontal: bool = False
    columns: list[str] = Field(default_factory=list)  # table column order
    formats: dict[str, ValueFormat] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    w: int = 6  # width in a 12-column dashboard grid
    h: int = 4  # height in grid rows (~70px)

    @field_validator("w")
    @classmethod
    def _w(cls, v: int) -> int:
        return max(2, min(12, v))

    @field_validator("h")
    @classmethod
    def _h(cls, v: int) -> int:
        return max(2, min(12, v))


class WidgetSpec(BaseModel):
    type: WidgetType
    title: str
    query: QueryPlan
    presentation: Presentation = Field(default_factory=Presentation)


class WidgetChanges(BaseModel):
    type: WidgetType | None = None
    title: str | None = None
    query: QueryPlan | None = None
    presentation: Presentation | None = None


# ---------------------------------------------------------------------------
# Agent operations
# ---------------------------------------------------------------------------


class Position(BaseModel):
    x: float
    y: float


class RelativePlacement(BaseModel):
    dashboard_id: str
    side: Literal["right", "left", "above", "below"] = "right"


class CreateDashboardOp(BaseModel):
    op: Literal["create_dashboard"]
    ref: str | None = None  # local reference usable by later operations in the same turn
    name: str
    description: str = ""
    filters: list[Filter] = Field(default_factory=list)
    widgets: list[WidgetSpec] = Field(default_factory=list)
    position: Position | None = None
    relative_to: RelativePlacement | None = None
    width: float | None = None
    height: float | None = None


class UpdateDashboardOp(BaseModel):
    op: Literal["update_dashboard"]
    dashboard_id: str
    name: str | None = None
    description: str | None = None
    filters: list[Filter] | None = None


class MoveDashboardOp(BaseModel):
    op: Literal["move_dashboard"]
    dashboard_id: str
    position: Position | None = None
    relative_to: RelativePlacement | None = None
    width: float | None = None
    height: float | None = None


class RemoveDashboardOp(BaseModel):
    op: Literal["remove_dashboard"]
    dashboard_id: str


class AddWidgetOp(BaseModel):
    op: Literal["add_widget"]
    dashboard_id: str
    widget: WidgetSpec


class UpdateWidgetOp(BaseModel):
    op: Literal["update_widget"]
    widget_id: str
    changes: WidgetChanges


class RemoveWidgetOp(BaseModel):
    op: Literal["remove_widget"]
    widget_id: str


Operation = Annotated[
    Union[
        CreateDashboardOp, UpdateDashboardOp, MoveDashboardOp, RemoveDashboardOp,
        AddWidgetOp, UpdateWidgetOp, RemoveWidgetOp,
    ],
    Field(discriminator="op"),
]


class Clarification(BaseModel):
    question: str
    options: list[str] = Field(default_factory=list)


class AgentPlan(BaseModel):
    message: str = ""
    clarification: Clarification | None = None
    operations: list[Operation] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API payloads
# ---------------------------------------------------------------------------


class Selection(BaseModel):
    dashboard_ids: list[str] = Field(default_factory=list)
    widget_ids: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    prompt: str
    selection: Selection = Field(default_factory=Selection)
    data_source_id: str | None = None


class DataSourceCreate(BaseModel):
    name: str
    url: str
    documentation: str = ""


class DataSourceUpdate(BaseModel):
    name: str | None = None
    documentation: str | None = None


class DashboardCreate(BaseModel):
    name: str
    data_source_id: str
    x: float = 0
    y: float = 0


class DashboardPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None
    filters: list[Filter] | None = None


class WidgetPatch(BaseModel):
    """Direct (non-agent) edits: presentation, title, type and existing filter values."""

    title: str | None = None
    type: WidgetType | None = None
    presentation: Presentation | None = None
    filters: list[Filter] | None = None


class Viewport(BaseModel):
    x: float
    y: float
    zoom: float


Expr.model_rebuild()
