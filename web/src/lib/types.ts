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

// Stage 24 — Standup reference rail
export interface StandupEpic {
  _id: string;
  epic_key: string;
  jira_key: string;
  title: string;
  program_area: string;
  status: string;
  priority: string;
  tags: string[];
  regulation_refs: string[];
  db_platform_combos: string[];
  ticket_refs: string[];
  finding_ids: string[];
  due_date?: string | null;
  updated_at?: string | null;
}
export interface StandupEpicsResponse {
  epics: StandupEpic[];
  active_only: boolean;
  limit: number;
  count: number;
}
export interface StandupTemplate {
  name: string;
  kind: "jira" | "confluence";
  description?: string;
  body_md: string;
}
export interface StandupTemplatesResponse {
  enabled: boolean;
  version: string;
  templates: StandupTemplate[];
}

export interface StandupIncomingEntities {
  aws_accounts: string[];
  rds_instances: string[];
  aws_regions: string[];
  app_team_ids: string[];
  users: string[];
  emails: string[];
  distribution_lists: string[];
}
export interface IdentityEnrichment {
  identity: string;
  found: boolean;
  status: string;
  directory?: {
    display_name?: string;
    email?: string;
    uid?: string;
    title?: string;
    department?: string;
    division?: string;
    location?: string;
    manager?: { display_name?: string; email?: string; title?: string } | null;
    teams?: string[];
    groups?: string[];
  } | null;
  manager_chain?: Array<Record<string, unknown> | null>;
  recent_activity?: Record<string, { status: string; summary: string; items: unknown[] }>;
  team_context?: Record<string, Record<string, unknown>>;
  github_history?: {
    status: string;
    summary?: string;
    count: number;
    repos: Array<{
      repo: string;
      interaction_kinds?: string[];
      evidence_count?: number;
      most_recent?: string;
      project?: string;
      application_mapping?: {
        application: string;
        environment: string;
        team: string;
        confidence: number;
        rationale: string;
      };
    }>;
  };
}

export interface StandupIncomingTicket {
  key: string;
  summary: string;
  reporter: string;
  created?: string | null;
  status: string;
  assignee?: string | null;
  entities: StandupIncomingEntities;
  workflow_match: {
    matched: boolean;
    workflow: string | null;
    kind?: string;
    confidence: number;
    rationale: string;
  };
  enrichment: Record<string, { status?: string; summary?: string; items?: unknown[] } | unknown>;
  identity_enrichment?: IdentityEnrichment | null;
  proposal: { status: "proposed"; dry_run: true; target_service: string; payload: Record<string, unknown> };
}
export interface StandupIncomingResponse {
  tickets: StandupIncomingTicket[];
  count: number;
  limit: number;
  generated_at: string;
  read_only: boolean;
}
// S29.gate-toggle.1 — effective production-apply gate state for /standup.
export interface StandupGates {
  dry_run_only: boolean;
  dry_run_only_source: "override" | "env";
  workflow_writes_enabled: boolean;
  jira_writes_enabled: boolean;
  mcp_gates_independent: boolean;
  live_writes_effective: boolean;
}
export interface StandupSetGatesResult {
  gates: StandupGates;
  audit: Record<string, unknown>;
}

// Stage 35 — standup chat-session history/navigation.
export interface StandupSessionSummary {
  session_id: string;
  title: string;
  sprint: string;
  status: string;
  started_at?: string | null;
  updated_at?: string | null;
  message_count: number;
  proposal_count: number;
  active_proposal_count: number;
  implemented_proposal_count: number;
}
export interface StandupSessionsResponse {
  sessions: StandupSessionSummary[];
  count: number;
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

// Stage 21 — Deep Agent runtime.
export interface AgentProfile {
  name: string;
  description: string;
  write_policy?: string;
  required_capability?: string | null;
  allowed_tools: string[];
  write_tools: string[];
  graph?: string | null;
}

export interface AgentProfilesResponse {
  profiles: AgentProfile[];
}

export type AgentRunStatus = "running" | "waiting_approval" | "completed" | "rejected" | "cancelled" | "error";

export interface AgentApprovalRequest {
  run_id: string;
  tool?: string;
  payload?: Record<string, unknown>;
  rationale?: string;
  /** Stage-19 capability the approver must hold to approve this write (S21.hitl.1). */
  required_capability?: string;
  /** Number of pending tool actions in the interrupt. */
  action_count?: number;
}

export interface AgentRunRecord {
  run_id: string;
  goal: string;
  agent?: string | null;
  status: AgentRunStatus;
  mode: string;
  actor?: string | null;
  result_text?: string;
  approval?: AgentApprovalRequest | null;
  artifacts: Record<string, unknown>[];
  error?: string;
  created_at: number;
  updated_at: number;
}

export interface AgentArtifactsResponse {
  run_id: string;
  artifacts: Record<string, unknown>[];
}

// Stage 18 — architecture graph v2 (see mcp/architecture.py).

export interface ArchLayer {
  id: string;
  label: string;
  /** "aws_account" | "azure_subscription" | "gcp_project" | "on_prem_zone" | "saas" */
  kind: string;
  parent_id: string | null;
  meta: Record<string, string | number | null>;
}

export interface ArchNode {
  id: string;
  label: string;
  /** e.g. "ec2_mongodb" | "ec2" | "rds" | "s3" | "saas" | "shield" | "ticket" | "kanban" | "git" | "book" | "cloud" | "database" | "snowflake" | "observability" | "artifact" */
  kind: string;
  layer_id: string;
  status: string;
  /** Visual column: "sources" | "risk_itsm" | "atlassian" | "implementation" | "warehouse_observability" | "artifacts" */
  lane: string;
  meta: Record<string, string | number | null>;
  concerns: string[];
}

export interface ArchEdge {
  from: string;
  to: string;
  label: string;
  /** "REST" | "webhook" | "log shipper" | "MCP tool" | "agent workflow" | "SQL/export" */
  protocol: string;
  flow: string | null;
  planned: boolean;
  integration: Record<string, string | number | null>;
}

export interface ArchFlow {
  id: string;
  label: string;
  steps: string[];
}

export interface ArchConcern {
  id: string;
  severity: "critical" | "high" | "medium" | "low";
  kind: string;
  title: string;
  node_id?: string;
  link?: string;
}

export interface ArchitectureGraph {
  layers: ArchLayer[];
  nodes: ArchNode[];
  edges: ArchEdge[];
  flows: ArchFlow[];
  concerns: ArchConcern[];
}

// Stage 19 — /api/auth/diagnostics response (canAdminAuth only).

export interface AuthDiagnosticsCache {
  file_path: string;
  ttl_seconds: number;
  loaded: boolean;
  user_count: number;
  last_load_age_seconds: number | null;
}

export interface AuthDiagnosticsLdap {
  adapter_class: string;
  is_fixture: boolean;
  ldap_url_configured: boolean;
}

export interface AuthDiagnosticsSeededUser {
  username: string;
  display_name: string;
  groups: string[];
  roles: string[];
}

export interface AuthDiagnosticsRecentDeny {
  username: string;
  capability: string;
  reason: string;
  ts: string;
}

export interface AuthDiagnostics {
  auth_mode: string;
  sso_required: boolean;
  dev_headers_enabled: boolean;
  groups: Record<string, string>;
  role_capabilities: Record<string, string[]>;
  cache: AuthDiagnosticsCache;
  ldap: AuthDiagnosticsLdap;
  seeded_users: AuthDiagnosticsSeededUser[];
  recent_denies: AuthDiagnosticsRecentDeny[];
}

// Stage 19 — /api/me identity + capability response.
// capabilities values are the Capability constant strings from web/auth.py.
export type Capability = string;

export interface MeResponse {
  authenticated: boolean;
  /** Present only when authenticated === true. */
  user?: {
    username: string;
    display_name: string;
    email: string;
  };
  /** Present only when authenticated === true. */
  groups?: string[];
  /** Present only when authenticated === true. */
  roles?: string[];
  /** Sorted list of granted capabilities; empty array when unauthenticated. */
  capabilities: Capability[];
  auth_mode: string;
  /** Present only when authenticated === true. */
  source?: string;
}

// Stage 26 — chat runtime visibility (/api/chat/runtime). Redacted: no keys.
export interface RuntimeRole {
  role: string;
  provider: string;
  /** Host + path only; credentials/query stripped server-side. */
  endpoint: string;
  model: string;
  max_tokens: number;
  /** True when the role rides the UPSTREAM_* defaults (no role overrides). */
  inherits_default: boolean;
}

export interface RuntimeAgent {
  name: string;
  description: string;
  role: string;
  graph: string | null;
  write_policy: string;
  required_capability: string | null;
  provider: string;
  endpoint: string;
  model: string;
  inherits_default: boolean;
}

export interface RuntimeOrchestrator {
  description: string;
  role: string;
  provider: string;
  endpoint: string;
  model: string;
  inherits_default: boolean;
}

export interface ChatRuntimePlatform {
  roles: Record<string, RuntimeRole>;
  orchestrator: RuntimeOrchestrator | null;
  agents: RuntimeAgent[];
  /** Present only if the deep-agent platform failed to resolve. */
  error?: string;
}

export interface ChatRuntimeResponse {
  chat_agent: RuntimeRole;
  platform: ChatRuntimePlatform;
}
