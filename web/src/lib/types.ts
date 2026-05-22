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

// Stage 11 — Compliance command-center overview
export type AttentionReason =
  | "overdue"
  | "due_soon"
  | "prioritized"
  | "high_severity"
  | "blocked_pr"
  | "stalled";

export interface AttentionItem {
  id: string;
  kind: "finding" | "epic" | "work_item" | "pr";
  title: string;
  reason: AttentionReason;
  severity?: string | null;
  priority?: string | null;
  due_date?: string | null;
  days_until_due?: number | null;
  link: string;
}

export interface OverviewConnector {
  name: string;
  status: string;
  enabled: boolean;
  summary: string;
  link: string;
}

export interface OverviewKpis {
  open_findings: number;
  active_epics: number;
  inflight_work_items: number;
  open_prs: number;
  connectors_healthy: number;
  connectors_total: number;
  attention: number;
}

export interface OverviewResponse {
  kpis: OverviewKpis;
  attention: AttentionItem[];
  connectors: OverviewConnector[];
  tables: {
    findings: Row[];
    epics: Row[];
    work_items: Row[];
    pr_records: Row[];
  };
  generated_at: string;
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

// ---- Stage 14 — Docs Wiki ------------------------------------------------

export type DocStatus = "up_to_date" | "needs_attention" | "archivable" | "archived";
export type DocVisibility = "internal" | "public";

/** Lightweight doc record returned in the nav tree (no body). */
export interface DocSummary {
  _id: string;
  slug: string;
  path: string;
  title: string;
  tags: string[];
  status: DocStatus;
  visibility: DocVisibility;
  version: number;
  owner?: string | null;
  last_reviewed_at?: string | null;
  updated_at?: string | null;
  created_at?: string | null;
  confluence_page_id?: string | null;
  /** Computed lifecycle status (may differ from stored status). */
  derived_status?: DocStatus;
}

/** One group in the nav tree. */
export interface DocTreeGroup {
  group: string;
  docs: DocSummary[];
}

/** Review-queue entry (needs_attention / archivable). */
export interface DocReviewItem {
  slug: string;
  title: string | null;
  status: DocStatus;
  path: string | null;
}

/** Full response from GET /api/docs/tree. */
export interface DocsTreeResponse {
  tree: DocTreeGroup[];
  docs: DocSummary[];
  review_queue: DocReviewItem[];
  count: number;
  review_days: number;
  generated_at: string;
}

/** Revision history entry. */
export interface DocRevision {
  _id: string;
  doc_id: string;
  version: number;
  body_md: string;
  author: string;
  created_at: string;
  note?: string | null;
}

/** Confluence sync-log entry. */
export interface DocSyncLogEntry {
  _id: string;
  doc_id: string;
  direction: "push" | "pull";
  confluence_page_id?: string | null;
  action: "create" | "update" | "skip" | "conflict";
  at?: string | null;
  detail?: string | null;
}

/** Full doc record returned by GET /api/docs/{slug}. */
export interface Doc extends DocSummary {
  body_md: string;
  revisions: DocRevision[];
  sync_log: DocSyncLogEntry[];
}

/** Result from docs_upsert. */
export interface DocUpsertResult {
  doc: DocSummary;
  created: boolean;
  revision_id: string;
}

/** Result from docs_set_flags. */
export interface DocFlagsResult {
  doc: DocSummary;
}

/** Single search hit. */
export interface DocSearchHit {
  slug: string;
  path: string;
  title: string;
  snippet: string;
  tags: string[];
  status: DocStatus;
  visibility: DocVisibility;
}

/** Full response from GET /api/docs/search. */
export interface DocsSearchResponse {
  query: string;
  results: DocSearchHit[];
}

/** One action in the sync plan. */
export interface DocSyncAction {
  slug: string;
  path: string;
  planned_action: "create" | "update" | "skip";
  action: string;
  live: boolean;
  detail: string;
  confluence_page_id?: string | null;
  labels: string[];
}

/** Full response from POST /api/docs/sync. */
export interface DocsSyncResponse {
  live: boolean;
  space: string;
  considered: number;
  ancestors: Record<string, string>;
  actions: DocSyncAction[];
}

/** Triage entry (stale / unreferenced doc). */
export interface DocTriageEntry {
  slug: string;
  title: string | null;
  current_status: DocStatus | null;
  suggested_status: DocStatus;
  reason: string;
}

/** Suggested improvement (proposal only, never auto-applied). */
export interface DocSuggestion {
  slug: string;
  title: string | null;
  rationale: string;
  proposed_body_md: string;
  /** True only after a HIL-approved apply; proposals start false. */
  applied: boolean;
}

/** One applied (HIL-approved) suggestion result. */
export interface DocAgentApplied {
  slug: string;
  version?: number;
  error?: string;
}

/** Full response from POST /api/docs/agent. */
export interface DocsAgentResponse {
  run_id: string;
  /** "waiting_approval" = paused at the HIL apply gate; "completed" = resumed/applied. */
  status: "waiting_approval" | "completed";
  reconcile: DocsSyncResponse;
  triage: DocTriageEntry[];
  suggestions: DocSuggestion[];
  applied: DocAgentApplied[];
  applied_any: boolean;
  approval_preview?: {
    message: string;
    proposals: { slug: string; title: string | null; rationale: string }[];
  } | null;
}
