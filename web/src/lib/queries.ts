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
  WranglerSample,
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

// Stage 12 — cross-system topology graph for the Architecture page.
export function useTopology() {
  return useQuery({
    queryKey: ["topology"] as const,
    queryFn: () => api.get<TopologyGraph>("/api/topology"),
    refetchInterval: 30_000,
  });
}

