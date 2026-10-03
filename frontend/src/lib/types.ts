export type Role = "admin" | "analyst" | "viewer";
export type WidgetType = "kpi" | "table" | "bar" | "line" | "area" | "pie";
export type ValueFormat = "number" | "integer" | "currency" | "percent" | "text" | "date";
export type ReviewStatus = "draft" | "needs_review" | "approved" | "rejected" | "missing";

export interface Filter {
  field: string;
  op: string;
  value?: unknown;
}

export interface QueryPlan {
  dimensions?: { field: string; alias?: string; grain?: string }[];
  measures?: { alias: string; metric?: string; agg?: string; field?: string }[];
  filters?: Filter[];
  order_by?: { key: string; direction: "asc" | "desc" }[];
  limit?: number;
  via?: string[];
}

export interface Presentation {
  x?: string | null;
  y?: string[];
  series?: string | null;
  stacked?: boolean;
  horizontal?: boolean;
  columns?: string[];
  formats?: Record<string, ValueFormat>;
  labels?: Record<string, string>;
  w?: number;
  h?: number;
}

export interface Widget {
  id: string;
  dashboard_id: string;
  type: WidgetType;
  title: string;
  position: number;
  query: QueryPlan;
  presentation: Presentation;
  effective_query_hash: string | null;
  skipped_filters: { field: string; reason: string }[];
  dependency_issues: string[];
  updated_at: string | null;
}

export interface Dashboard {
  id: string;
  name: string;
  description: string;
  data_source_id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  filters: Filter[];
  widgets: Widget[];
  updated_at: string | null;
}

export interface Viewport {
  x: number;
  y: number;
  zoom: number;
}

export interface ResultColumn {
  key: string;
  kind: "dimension" | "measure";
  field: string | null;
  metric: string | null;
  grain: string | null;
  format: ValueFormat | null;
}

export interface QueryResult {
  query_hash: string;
  columns: ResultColumn[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  limit: number;
  executed_at: string;
  duration_ms: number;
  cached: boolean;
  skipped_filters: { field: string; reason: string }[];
}

export type RunStatus = "idle" | "queued" | "loading" | "success" | "empty" | "error";

export interface WidgetRuntime {
  status: RunStatus;
  hash: string | null;
  error?: string;
  startedAt?: number;
}

export interface Clarification {
  question: string;
  options: string[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "ok" | "error" | "clarification";
  clarification: Clarification | null;
  change_set_id: string | null;
  selection: { dashboard_ids?: string[]; widget_ids?: string[] };
  created_at: string;
  pending?: boolean;
}

export interface DataSourceSummary {
  id: string;
  name: string;
  url: string;
  is_demo: boolean;
  documentation: string;
  discovered_at: string | null;
  drafted_at: string | null;
  table_count: number;
  status_counts: Record<string, number>;
}

export interface ColumnMeta {
  name: string;
  data_type: string;
  nullable: boolean;
  primary_key: boolean;
  description: string;
  unit: string | null;
  semantic_type: string | null;
  allowed_values: string[];
  coded_values: Record<string, string>;
  status: ReviewStatus;
  confidence: number;
  ambiguities: string[];
  restricted: boolean;
  schema_change: string | null;
}

export interface TableMeta {
  name: string;
  description: string;
  row_meaning: string;
  status: ReviewStatus;
  confidence: number;
  ambiguities: string[];
  restricted: boolean;
  schema_change: string | null;
  columns: ColumnMeta[];
}

export interface RelationshipMeta {
  id: string;
  from_table: string;
  from_column: string;
  to_table: string;
  to_column: string;
  cardinality: "many_to_one" | "one_to_one";
  origin: "declared" | "inferred" | "manual";
  description: string;
  status: ReviewStatus;
  confidence: number;
  ambiguities: string[];
}

export interface MetricMeta {
  name: string;
  label: string;
  description: string;
  agg: string;
  expr: unknown;
  format: ValueFormat;
  status: ReviewStatus;
  confidence: number;
  ambiguities: string[];
}

export interface MetadataDoc {
  tables: TableMeta[];
  relationships: RelationshipMeta[];
  metrics: MetricMeta[];
}

export interface ImpactItem {
  dashboard_id: string;
  dashboard: string;
  widget_id: string;
  widget: string;
  issues: string[];
}

export interface HistoryItem {
  id: string;
  source: string;
  summary: string;
  undone: boolean;
  created_at: string;
  dashboards: string[];
}

export interface AppConfig {
  llm_configured: boolean;
  model: string;
  gateway: string;
  roles: Role[];
  limits: { default_rows: number; max_rows: number; timeout_seconds: number };
}
