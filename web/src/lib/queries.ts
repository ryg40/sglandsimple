import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { api, qs } from "./api";
import type {
  AuditRecentResponse,
  ChatCompletion,
  ChatMessage,
  CollectionsResponse,
  DeleteResult,
  InsertResult,
  PipelinesResponse,
  RunPrefixResult,
  SaveResult,
  SheetApplyResult,
  SheetRowsResponse,
  Stage,
  SuggestResult,
  TopologyGraph,
  ArchitectureGraph,
  OverviewResponse,
  WranglerSample,
  JiraIssuesResponse,
  JiraStageEdit,
  JiraStageResult,
  JiraValidateResult,
  JiraRevertResult,
  JiraApplyResult,
  DocsTreeResponse,
  Doc,
  DocUpsertResult,
  DocFlagsResult,
  DocsSearchResponse,
  DocsSyncResponse,
  DocsAgentResponse,
  MeResponse,
} from "./types";

export const keys = {
  collections: ["collections"] as const,
  sheetRows: (c: string, skip: number, limit: number) => ["sheet-rows", c, skip, limit] as const,
  sample: (c: string) => ["wrangler-sample", c] as const,
  pipelines: (c?: string) => ["wrangler-pipelines", c ?? "all"] as const,
  audit: (limit: number) => ["audit-recent", limit] as const,
};

// ---- reads -----------------------------------------------------------------

export function useCollections() {
  return useQuery({
    queryKey: keys.collections,
    queryFn: () => api.get<CollectionsResponse>("/api/sheet/collections"),
  });
}

export function useSheetRows(collection: string | null, skip: number, limit: number) {
  return useQuery({
    queryKey: keys.sheetRows(collection ?? "", skip, limit),
    queryFn: () =>
      api.get<SheetRowsResponse>(`/api/sheet/rows${qs({ collection: collection!, skip, limit })}`),
    enabled: !!collection,
  });
}

export function useWranglerSample(collection: string | null) {
  return useQuery({
    queryKey: keys.sample(collection ?? ""),
    queryFn: () => api.get<WranglerSample>(`/api/wrangler/sample${qs({ collection: collection! })}`),
    enabled: !!collection,
  });
}

export function usePipelines(collection: string | null) {
  return useQuery({
    queryKey: keys.pipelines(collection ?? undefined),
    queryFn: () =>
      api.get<PipelinesResponse>(`/api/wrangler/pipelines${qs({ collection: collection ?? undefined })}`),
    enabled: !!collection,
  });
}

export function useRecentAudit(limit = 25) {
  return useQuery({
    queryKey: keys.audit(limit),
    queryFn: () => api.get<AuditRecentResponse>(`/api/audit/recent${qs({ limit })}`),
    refetchInterval: 15_000,
  });
}

// ---- sheet mutations (optimistic) ------------------------------------------

function invalidateSheet(qc: QueryClient, collection: string) {
  qc.invalidateQueries({ queryKey: ["sheet-rows", collection] });
  qc.invalidateQueries({ queryKey: keys.collections });
  qc.invalidateQueries({ queryKey: ["audit-recent"] });
}

interface CellArgs {
  collection: string;
  _id: string;
  field: string;
  value: unknown;
  skip: number;
  limit: number;
}

export function useUpdateCell() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (a: CellArgs) =>
      api.post("/api/sheet/cell", { collection: a.collection, _id: a._id, field: a.field, value: a.value }),
    onMutate: async (a: CellArgs) => {
      const key = keys.sheetRows(a.collection, a.skip, a.limit);
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<SheetRowsResponse>(key);
      if (prev) {
        qc.setQueryData<SheetRowsResponse>(key, {
          ...prev,
          rows: prev.rows.map((r) => (r._id === a._id ? { ...r, [a.field]: a.value } : r)),
        });
      }
      return { key, prev };
    },
    onError: (_e, _a, ctx) => {
      if (ctx?.prev) qc.setQueryData(ctx.key, ctx.prev);
    },
    onSettled: (_d, _e, a) => invalidateSheet(qc, a.collection),
  });
}

export function useInsertRow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (a: { collection: string; doc: Record<string, unknown> }) =>
      api.post<InsertResult>("/api/sheet/row", a),
    onSettled: (_d, _e, a) => invalidateSheet(qc, a.collection),
  });
}

export function useDeleteRow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (a: { collection: string; _id: string; skip: number; limit: number }) =>
      api.del<DeleteResult>(`/api/sheet/row${qs({ collection: a.collection, _id: a._id })}`),
    onMutate: async (a) => {
      const key = keys.sheetRows(a.collection, a.skip, a.limit);
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<SheetRowsResponse>(key);
      if (prev) {
        qc.setQueryData<SheetRowsResponse>(key, {
          ...prev,
          rows: prev.rows.filter((r) => r._id !== a._id),
          total: Math.max(0, prev.total - 1),
        });
      }
      return { key, prev };
    },
    onError: (_e, _a, ctx) => {
      if (ctx?.prev) qc.setQueryData(ctx.key, ctx.prev);
    },
    onSettled: (_d, _e, a) => invalidateSheet(qc, a.collection),
  });
}

export function useApplyNl() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (a: { collection: string; instruction: string }) =>
      api.post<SheetApplyResult>("/api/sheet/nl", a),
    onSettled: (_d, _e, a) => invalidateSheet(qc, a.collection),
  });
}

// ---- wrangler mutations -----------------------------------------------------

export function useRunPrefix() {
  return useMutation({
    mutationFn: (a: { collection: string; pipeline: Stage[]; upto: number }) =>
      api.post<RunPrefixResult>("/api/wrangler/run", a),
  });
}

export function useSavePipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (a: { name: string; collection: string; stages: Stage[]; _id?: string }) =>
      api.post<SaveResult>("/api/wrangler/save", a),
    onSettled: () => qc.invalidateQueries({ queryKey: ["wrangler-pipelines"] }),
  });
}

export function useSuggest() {
  return useMutation({
    mutationFn: (a: { collection: string }) => api.post<SuggestResult>("/api/wrangler/suggest", a),
  });
}

// ---- chat -------------------------------------------------------------------

export function useChat() {
  return useMutation({
    mutationFn: (messages: ChatMessage[]) =>
      api.post<ChatCompletion>("/api/chat", { messages }),
  });
}

export function useAskData() {
  return useMutation({
    mutationFn: (question: string) => api.post<ChatCompletion>("/api/ask_data", { question }),
  });
}

// ---- Stage 9 — Compliance Hub React Query Hooks ---------------------------

export const keys_stage9 = {
  connectors: ["connectors-bubbles"] as const,
  connector: (name: string) => ["connector-detail", name] as const,
};

export function useConnectors() {
  return useQuery({
    queryKey: keys_stage9.connectors,
    queryFn: () => api.get<{ connectors: any[] }>("/api/connectors"),
    refetchInterval: 30_000, // Poll every 30 seconds
  });
}

export function useConnectorDetail(name: string | null) {
  return useQuery({
    queryKey: keys_stage9.connector(name ?? ""),
    queryFn: () => api.get<any>(`/api/connectors/${name}`),
    enabled: !!name,
  });
}

export function useWorkflowRun() {
  return useMutation({
    mutationFn: (a: { finding_id: string; resume_decision?: string; checkpoint_id?: string }) =>
      api.post<any>("/api/workflow/run", a),
  });
}

// Stage 11 — compliance command-center overview (one polled call, SWR).
export function useOverview() {
  return useQuery({
    queryKey: ["overview"] as const,
    queryFn: () => api.get<OverviewResponse>("/api/overview"),
    refetchInterval: 30_000,
    placeholderData: (prev) => prev, // stale-while-revalidate: never blank on refetch
  });
}

// Stage 12 — cross-system topology graph for the Architecture page.
export function useTopology() {
  return useQuery({
    queryKey: ["topology"] as const,
    queryFn: () => api.get<TopologyGraph>("/api/topology"),
    refetchInterval: 30_000,
  });
}

// Stage 18 — architecture graph v2 for the Architecture page.
export function useArchitecture() {
  return useQuery({
    queryKey: ["architecture"] as const,
    queryFn: () => api.get<ArchitectureGraph>("/api/architecture"),
    refetchInterval: 30_000,
  });
}


// ---- Stage 16 — HIL-gated Jira bulk editing -------------------------------

export const jiraKeys = { issues: ["jira-issues"] as const };

export function useJiraIssues() {
  return useQuery({
    queryKey: jiraKeys.issues,
    queryFn: () => api.get<JiraIssuesResponse>("/api/jira/issues"),
  });
}

export function useStageJiraEdits() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (edits: JiraStageEdit[]) => api.post<JiraStageResult>("/api/jira/stage", { edits }),
    onSuccess: () => qc.invalidateQueries({ queryKey: jiraKeys.issues }),
  });
}

export function useValidateJira() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (issue_keys?: string[]) => api.post<JiraValidateResult>("/api/jira/validate", { issue_keys }),
    onSuccess: () => qc.invalidateQueries({ queryKey: jiraKeys.issues }),
  });
}

export function useRevertJira() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (issue_keys?: string[]) => api.post<JiraRevertResult>("/api/jira/revert", { issue_keys }),
    onSuccess: () => qc.invalidateQueries({ queryKey: jiraKeys.issues }),
  });
}

export function useApplyJira() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (issue_keys?: string[]) => api.post<JiraApplyResult>("/api/jira/apply", { issue_keys }),
    onSuccess: () => qc.invalidateQueries({ queryKey: jiraKeys.issues }),
  });
}

// ---- Stage 14 — Docs Wiki -------------------------------------------------

export const docsKeys = {
  tree: (tag?: string, status?: string, visibility?: string) =>
    ["docs-tree", tag ?? "", status ?? "", visibility ?? ""] as const,
  doc: (slug: string) => ["docs-doc", slug] as const,
  search: (q: string) => ["docs-search", q] as const,
};

export function useDocsTree(opts?: { tag?: string; status?: string; visibility?: string }) {
  const { tag, status, visibility } = opts ?? {};
  return useQuery({
    queryKey: docsKeys.tree(tag, status, visibility),
    queryFn: () => {
      const params = new URLSearchParams();
      if (tag) params.set("tag", tag);
      if (status) params.set("status", status);
      if (visibility) params.set("visibility", visibility);
      const qs = params.toString();
      return api.get<DocsTreeResponse>(`/api/docs/tree${qs ? `?${qs}` : ""}`);
    },
    refetchInterval: 60_000,
    placeholderData: (prev) => prev,
  });
}

export function useDoc(slug: string | null) {
  return useQuery({
    queryKey: docsKeys.doc(slug ?? ""),
    queryFn: () => api.get<Doc>(`/api/docs/${slug}`),
    enabled: !!slug,
  });
}

export function useDocsSearch(q: string) {
  return useQuery({
    queryKey: docsKeys.search(q),
    queryFn: () => api.get<DocsSearchResponse>(`/api/docs/search?q=${encodeURIComponent(q)}`),
    enabled: q.length >= 2,
  });
}

export function useUpsertDoc() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (doc: {
      slug: string;
      path?: string;
      title?: string;
      body_md?: string;
      tags?: string[];
      status?: string;
      visibility?: string;
      owner?: string;
      note?: string;
    }) => api.post<DocUpsertResult>("/api/docs", doc),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["docs-tree"] });
      qc.invalidateQueries({ queryKey: docsKeys.doc(vars.slug) });
    },
  });
}

export function useSetDocFlags() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (a: { slug: string; status?: string; visibility?: string; tags?: string[] }) =>
      api.post<DocFlagsResult>(`/api/docs/${a.slug}/flags`, {
        status: a.status,
        visibility: a.visibility,
        tags: a.tags,
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["docs-tree"] });
      qc.invalidateQueries({ queryKey: docsKeys.doc(vars.slug) });
    },
  });
}

export function useDocsSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (slug?: string) => api.post<DocsSyncResponse>("/api/docs/sync", slug ? { slug } : {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["docs-tree"] }),
  });
}

export function useDocsAgent() {
  const qc = useQueryClient();
  return useMutation({
    // A fresh run passes { limit_suggestions } and pauses at the HIL apply gate;
    // resume by passing { run_id, resume_decision } to apply approved proposals.
    mutationFn: (
      arg?: number | { limit_suggestions?: number; run_id?: string; resume_decision?: unknown },
    ) => {
      const body =
        typeof arg === "number" ? { limit_suggestions: arg } : (arg ?? {});
      return api.post<DocsAgentResponse>("/api/docs/agent", body);
    },
    onSuccess: (data) => {
      // Applying suggestions writes revisions; refresh the tree/docs.
      if (data.applied_any) qc.invalidateQueries({ queryKey: ["docs-tree"] });
    },
  });
}

// ---- Stage 19 — current-user identity + capabilities ----------------------

/** Fetch the caller's identity and capability set from /api/me.
 *
 * Always returns HTTP 200 (authenticated: false when unauthenticated), so
 * this query never errors on missing credentials — the SPA uses the result
 * to decide whether to render a login prompt or the full UI.
 *
 * staleTime: 60 s  — identity rarely changes mid-session; avoid chatty re-fetches.
 */
export function useMe() {
  return useQuery({
    queryKey: ["me"] as const,
    queryFn: () => api.get<MeResponse>("/api/me"),
    staleTime: 60_000,
  });
}
