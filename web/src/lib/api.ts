// Typed, same-origin fetch wrapper. Every call throws ApiError on non-2xx
// so the Query layer can surface a consistent message + status.

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown, message?: string) {
    super(message ?? `request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function parse(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}

function describe(body: unknown): string | undefined {
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    if (typeof b.detail === "string") return b.detail;
    if (b.error) return typeof b.error === "string" ? b.error : JSON.stringify(b.error);
  }
  return undefined;
}

async function request<T>(method: string, url: string, payload?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: payload !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: payload !== undefined ? JSON.stringify(payload) : undefined,
  });
  const body = await parse(res);
  if (!res.ok) throw new ApiError(res.status, body, describe(body));
  return body as T;
}

export const api = {
  get: <T>(url: string) => request<T>("GET", url),
  post: <T>(url: string, body?: unknown) => request<T>("POST", url, body ?? {}),
  del: <T>(url: string) => request<T>("DELETE", url),
};

export const api_stage9 = {
  getConnectors: () => api.get<{ connectors: any[] }>("/api/connectors"),
  getConnector: (name: string) => api.get<any>(`/api/connectors/${name}`),
  runWorkflow: (findingId: string, decision?: string, runId?: string) =>
    api.post<any>("/api/workflow/run", { finding_id: findingId, resume_decision: decision, checkpoint_id: runId }),
};

export function qs(params: Record<string, string | number | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
}
