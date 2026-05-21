// Shared types for every /api/* payload. The web service proxies MCP
// tools and unwraps the JSON content block, so these mirror the tool
// return shapes (see mcp/server.py, mcp/wrangler.py, mcp/db.py).

export type CollectionName = "employees" | "tickets" | "documents";

export interface Collection {
  name: CollectionName;
  count: number;
}
export interface CollectionsResponse {
  collections: Collection[];
}

export type Row = Record<string, unknown> & { _id?: string };

export interface SheetRowsResponse {
  collection: string;
  skip: number;
  limit: number;
  total: number;
  rows: Row[];
}

export interface CellUpdateResult {
  _id: string;
  matched: number;
  modified: number;
  before: Row | null;
  after: Row | null;
}

export interface InsertResult {
  _id: string;
  after: Row | null;
}

export interface DeleteResult {
  _id: string;
  deleted: number;
  before: Row | null;
}

export interface AppliedOp {
  op: string;
  _id?: string;
  field?: string;
  before?: unknown;
  after?: unknown;
}
export interface SheetApplyResult {
  collection: string;
  instruction: string;
  rationale?: string;
  applied: AppliedOp[];
  failed: { op: string; _id?: string; field?: string; error: string }[];
  summary: string;
  error?: string | null;
  isError?: boolean;
  markdown?: string;
}

export interface FieldSummary {
  field: string;
  types: string[];
  cardinality: number | null;
  coverage: number;
  examples: unknown[];
}
export interface WranglerSample {
  collection: string;
  sort_field: string;
  sort_dir: number;
  row_count: number;
  rows: Row[];
  field_summary: FieldSummary[];
}

export type Stage = Record<string, unknown>;

export interface RunPrefixResult {
  collection: string;
  stage_index: number;
  input_count: number;
  output_count: number;
  rows: Row[];
}

export interface SavedPipeline {
  _id: string;
  name: string;
  collection: string;
  stages: Stage[];
  created_at?: string;
  updated_at?: string;
}
export interface PipelinesResponse {
  pipelines: SavedPipeline[];
}
export interface SaveResult {
  _id: string;
  name: string;
  collection: string;
  saved: boolean;
}

export interface SuggestedPipeline {
  name: string;
  rationale: string;
  stages: Stage[];
}
export interface SuggestResult {
  collection: string;
  pipelines: SuggestedPipeline[];
  dropped?: { name: string; reason: string }[];
  isError?: boolean;
}

export interface AuditRow {
  doc_id: string | null;
  action: string;
  collection: string;
  source: string;
  ts?: string;
  before?: unknown;
  after?: unknown;
}
export interface AuditRecentResponse {
  collection: string;
  rows: AuditRow[];
}

// Stage 9 — Compliance Connector & Workflow types
export interface ConnectorBubble {
  name: string;
  health: {
    status: "healthy" | "disabled" | "degraded" | "error" | "placeholder";
    detail?: string;
  };
  summary: {
    status: string;
    collections?: Array<{ name: string; count: number }>;
    pages_count?: number;
    open_issues_count?: number;
    prs_count?: number;
    rds_instances_count?: number;
    open_incidents?: number;
    change_requests?: number;
    audit_log_rows_count?: number;
    findings_tracked?: number;
    detail?: string;
  };
}

export interface WorkflowRunMetadata {
  run_id: string;
  status: "running" | "waiting_approval" | "completed" | "failed";
  step_index: number;
  artifacts: {
    finding?: Record<string, any>;
    epic?: Record<string, any>;
    ticket_payload?: Record<string, any>;
    ticket_key?: string;
    branch_name?: string;
    pr_spec?: Record<string, any>;
    pr_url?: string;
    pr_number?: number;
    confluence_doc_text?: string;
    confluence_url?: string;
  };
  next_action_preview?: {
    message?: string;
    preview?: string;
  } | null;
}

// OpenAI-shaped chat completion (only the bits we read).
export interface ChatMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
}
export interface ChatCompletion {
  choices?: { message?: { content?: string } }[];
  error?: unknown;
}

// Stage 12 — cross-system topology graph (see mcp/topology.py).
export interface TopologyNode {
  id: string;
  label: string;
  kind: string;
  zone: string;
  status: string;
  endpoint: string;
  metrics: Record<string, number>;
  concerns: string[];
}
export interface TopologyEdge {
  from: string;
  to: string;
  label: string;
  kind: string;
  concern?: boolean;
}
export interface TopologyConcern {
  id: string;
  severity: "critical" | "high" | "medium" | "low";
  kind: string;
  title: string;
  node_id?: string;
  edge?: { from: string; to: string };
  link?: string;
}
export interface TopologyZone {
  id: string;
  label: string;
  order: number;
}
export interface TopologyGraph {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  concerns: TopologyConcern[];
  zones: TopologyZone[];
}

// ---- Stage 16 — HIL-gated Jira bulk editing ------------------------------
export interface JiraIssueRow {
  key: string;
  summary?: string;
  status?: string;
  assignee?: string;
  priority?: string;
  story_points?: number | null;
  duedate?: string | null;
  epic_key?: string;
  epic_name?: string;
  updated?: string;
  flagged?: boolean;
  // staging overlay (added by jira_list_issues)
  _staged?: Record<string, unknown>;
  _stage_status?: "staged" | "validated" | "invalid" | "applied" | "reverted" | null;
  _validation?: { ok: boolean; errors: { field: string; message: string }[] } | null;
  [k: string]: unknown;
}
export interface JiraIssuesResponse {
  issues: JiraIssueRow[];
  staged_count: number;
}
export interface JiraStageEdit {
  issue_key: string;
  changes: Record<string, unknown>;
}
export interface JiraStageResult {
  staged: string[];
  rejected: { issue_key: string; reason: string }[];
  writes_enabled: boolean;
}
export interface JiraValidateResult {
  results: { issue_key: string; status: string; validation: { ok: boolean; errors: { field: string; message: string }[] } }[];
  validated: number;
}
export interface JiraRevertResult {
  reverted: string[];
}
export interface JiraApplyPlanItem {
  tool: string;
  issue_key: string;
  fields: Record<string, unknown>;
}
export interface JiraApplyResult {
  apply_mode: "dry_run" | "live";
  writes_enabled: boolean;
  applied: string[];
  skipped: { issue_key: string; reason: string }[];
  plan: JiraApplyPlanItem[];
  note: string;
}
