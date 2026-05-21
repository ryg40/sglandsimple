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

// OpenAI-shaped chat completion (only the bits we read).
export interface ChatMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
}
export interface ChatCompletion {
  choices?: { message?: { content?: string } }[];
  error?: unknown;
}
