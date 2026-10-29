// ---- auth ----
export interface User {
  id: number;
  username: string;
  display_name: string | null;
}

export interface LoginResponse {
  token: string;
  user: User;
}

// ---- health ----
export interface HealthChecks {
  litellm: boolean;
  business_pg: boolean;
  state_db: boolean;
}

export interface HealthInfo {
  status: string;
  brand: string;
  env: string;
  demo_mode: boolean;
  model?: string | null;
  checks: HealthChecks;
}

// ---- workspaces ----
export interface Workspace {
  id: number;
  slug: string;
  name: string;
  type: string;
  role: string;
}

export interface WorkspaceDetail extends Workspace {
  datasets: string[];
  dashboard_count: number;
}

// ---- dashboards ----
export interface DashboardSummary {
  id: number;
  title: string;
  status: string;
  current_version_id: number;
  updated_at: string;
}

export interface CanvasDisplay {
  unit?: string | null;
  precision?: number | null;
  comparison?: unknown;
  legend?: boolean | null;
  stacked?: boolean | null;
  page_size?: number | null;
}

export interface CanvasSeries {
  field: string;
  name?: string | null;
  split_by?: string | null;
}

export interface CanvasComponent {
  id: string;
  type: string;
  title?: string | null;
  span?: number | null;
  source_id?: string | null;
  field?: string | null;
  x?: { field: string } | null;
  series?: CanvasSeries[] | null;
  columns?: string[] | null;
  content?: string | null;
  display?: CanvasDisplay | null;
}

export interface Canvas {
  schema_version: string;
  title?: string | null;
  filters?: { allowed?: string[] | null; defaults?: Record<string, unknown> | null } | null;
  layout?: { grid_cols?: number | null; order?: string[] | null } | null;
  components?: CanvasComponent[] | null;
}

export interface Dashboard {
  id: number;
  workspace_id: number;
  title: string;
  status: string;
  current_version_id: number;
  canvas: Canvas;
  revision: number;
  updated_at: string;
}

// ---- conversations / messages ----
export interface ConversationCreateResponse {
  id: number;
  dashboard_id?: number | null;
}

export interface ChatMessage {
  seq: number;
  role: string;
  content: string;
  task_id?: number | null;
  created_at?: string | null;
}

export interface SendMessageResponse {
  task_id: number;
  message_seq: number;
}

// ---- tasks ----
export type TaskStatus =
  | 'queued'
  | 'running'
  | 'waiting_for_user'
  | 'waiting_for_apply'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'interrupted';

export interface TaskEvent {
  seq: number;
  event: string;
  phase?: string | null;
  data: Record<string, unknown>;
}

export interface Task {
  id: number;
  type?: string | null;
  status: TaskStatus;
  result?: unknown;
  error?: string | null;
  events?: TaskEvent[] | null;
}

// ---- patches ----
export interface PatchSummary {
  id: number;
  base_revision: number;
  status: string;
  diff_summary: string;
  task_id: number;
  created_at: string;
}

export interface ApplyPatchResponse {
  version_id: number;
  revision: number;
  dashboard_id: number;
}

// ---- sources ----
export interface SourceColumn {
  name: string;
  type: number;
}

export interface Source {
  id: number;
  title: string;
  sql: string;
  params?: Record<string, unknown> | null;
  col_schema: SourceColumn[];
  row_count: number;
  status: string;
  caliber_notes?: { notes?: string[] | null } | null;
  created_at?: string | null;
}

export interface RowsResponse {
  columns: SourceColumn[];
  rows: unknown[][];
  row_count: number;
  truncated?: boolean;
  page: number;
  size: number;
}
