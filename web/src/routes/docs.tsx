import { useState, useCallback } from "react";
import {
  BookText,
  ChevronRight,
  ChevronDown,
  Search,
  RefreshCw,
  AlertTriangle,
  Archive,
  Eye,
  Edit3,
  Save,
  X,
  Bot,
  Globe,
  Lock,
  Check,
  CircleSlash,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Markdown } from "@/components/markdown";
import {
  useDocsTree,
  useDoc,
  useDocsSearch,
  useUpsertDoc,
  useSetDocFlags,
  useDocsSync,
  useDocsAgent,
} from "@/lib/queries";
import type {
  DocStatus,
  DocVisibility,
  DocReviewItem,
  DocTreeGroup,
  DocsAgentResponse,
} from "@/lib/types";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STATUS_VARIANT: Record<DocStatus, "default" | "success" | "warning" | "destructive" | "outline"> = {
  up_to_date: "success",
  needs_attention: "warning",
  archivable: "destructive",
  archived: "outline",
};

const STATUS_LABEL: Record<DocStatus, string> = {
  up_to_date: "Up to date",
  needs_attention: "Needs attention",
  archivable: "Archivable",
  archived: "Archived",
};

const VISIBILITY_ICON: Record<DocVisibility, typeof Globe> = {
  public: Globe,
  internal: Lock,
};

const TEACHING_DOCS = [
  {
    slug: "overlap-chain",
    title: "Overlap chain",
    description: "Follow one compliance finding across Mongo, GitHub, and Confluence joins.",
  },
  {
    slug: "agentic-workflows",
    title: "Agentic workflows",
    description: "See where the server-side graphs live and which collections they touch.",
  },
  {
    slug: "mcp-in-this-stack",
    title: "MCP in this stack",
    description: "Learn the transport, tool bus, and Confluence live-enable path.",
  },
] as const;

function StatusBadge({ status }: { status: DocStatus }) {
  return (
    <Badge variant={STATUS_VARIANT[status] ?? "default"}>
      {STATUS_LABEL[status] ?? status}
    </Badge>
  );
}

function VisibilityBadge({ visibility }: { visibility: DocVisibility }) {
  const Icon = VISIBILITY_ICON[visibility] ?? Lock;
  return (
    <Badge variant={visibility === "public" ? "accent" : "outline"} className="gap-1">
      <Icon className="size-3" />
      {visibility}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Left-nav tree
// ---------------------------------------------------------------------------

interface NavTreeProps {
  groups: DocTreeGroup[];
  selected: string | null;
  onSelect: (slug: string) => void;
}

function NavTree({ groups, selected, onSelect }: NavTreeProps) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const toggle = (group: string) =>
    setCollapsed((c) => ({ ...c, [group]: !c[group] }));

  return (
    <nav className="flex-1 overflow-y-auto px-2 py-2 text-sm">
      {groups.map((grp) => {
        const isOpen = !collapsed[grp.group];
        return (
          <div key={grp.group} className="mb-2">
            <button
              onClick={() => toggle(grp.group)}
              className="flex w-full items-center gap-1 rounded px-1 py-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground"
            >
              {isOpen ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
              {grp.group}
            </button>
            {isOpen &&
              grp.docs.map((doc) => (
                <button
                  key={doc.slug}
                  onClick={() => onSelect(doc.slug)}
                  className={cn(
                    "flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left transition-colors",
                    selected === doc.slug
                      ? "bg-sidebar-accent text-sidebar-accent-foreground"
                      : "text-muted-foreground hover:bg-sidebar-accent/50 hover:text-foreground"
                  )}
                >
                  <BookText className="mt-0.5 size-3.5 shrink-0" />
                  <span className="min-w-0 truncate">{doc.title || doc.slug}</span>
                  {doc.derived_status && doc.derived_status !== "up_to_date" && doc.derived_status !== "archived" && (
                    <AlertTriangle className="ml-auto mt-0.5 size-3 shrink-0 text-[color:var(--warning)]" />
                  )}
                </button>
              ))}
          </div>
        );
      })}
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Review queue
// ---------------------------------------------------------------------------

function ReviewQueue({ items, onSelect }: { items: DocReviewItem[]; onSelect: (slug: string) => void }) {
  if (items.length === 0) return null;
  return (
    <Card className="border-warning/40 bg-warning/5">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm text-[color:var(--warning)]">
          <AlertTriangle className="size-4" />
          Review queue ({items.length})
        </CardTitle>
        <CardDescription className="text-xs">These docs need attention</CardDescription>
      </CardHeader>
      <CardContent className="space-y-1">
        {items.map((item) => (
          <button
            key={item.slug}
            onClick={() => onSelect(item.slug)}
            className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-warning/10"
          >
            {item.status === "archivable" ? (
              <Archive className="size-3.5 text-destructive" />
            ) : (
              <AlertTriangle className="size-3.5 text-[color:var(--warning)]" />
            )}
            <span className="flex-1 truncate text-left">{item.title || item.slug}</span>
            <StatusBadge status={item.status as DocStatus} />
          </button>
        ))}
      </CardContent>
    </Card>
  );
}

function TeachingDocsCard({ onSelect }: { onSelect: (slug: string) => void }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Teaching guides</CardTitle>
        <CardDescription className="text-xs">
          Draft Stage 23 docs that explain the traceability chain, workflow model, and MCP surface.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {TEACHING_DOCS.map((doc) => (
          <button
            key={doc.slug}
            onClick={() => onSelect(doc.slug)}
            className="flex w-full items-start gap-2 rounded-lg border bg-muted/30 px-3 py-2 text-left transition-colors hover:bg-muted/60"
          >
            <BookText className="mt-0.5 size-4 shrink-0 text-primary" />
            <span className="min-w-0">
              <span className="block text-sm font-medium">{doc.title}</span>
              <span className="block text-xs text-muted-foreground">{doc.description}</span>
            </span>
            <ChevronRight className="ml-auto mt-0.5 size-4 shrink-0 text-muted-foreground" />
          </button>
        ))}
        <p className="text-[11px] text-muted-foreground">
          Fresh stacks seed these guides into the wiki; `scripts/import_docs.py` can refresh them from Markdown.
        </p>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Flag / tag editor
// ---------------------------------------------------------------------------

interface FlagEditorProps {
  slug: string;
  status: DocStatus;
  visibility: DocVisibility;
  tags: string[];
}

function FlagEditor({ slug, status, visibility, tags }: FlagEditorProps) {
  const setFlags = useSetDocFlags();
  const [localStatus, setLocalStatus] = useState<string>(status);
  const [localVisibility, setLocalVisibility] = useState<string>(visibility);
  const [tagInput, setTagInput] = useState(tags.join(", "));
  const [saved, setSaved] = useState(false);

  const isDirty =
    localStatus !== status ||
    localVisibility !== visibility ||
    tagInput !== tags.join(", ");

  const save = async () => {
    const parsedTags = tagInput
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    await setFlags.mutateAsync({
      slug,
      status: localStatus,
      visibility: localVisibility,
      tags: parsedTags,
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-lg border bg-muted/30 px-4 py-3">
      <div className="flex flex-col gap-1">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Status</label>
        <select
          value={localStatus}
          onChange={(e) => setLocalStatus(e.target.value)}
          className="h-8 rounded-md border bg-background px-2 text-sm"
        >
          <option value="up_to_date">Up to date</option>
          <option value="needs_attention">Needs attention</option>
          <option value="archivable">Archivable</option>
          <option value="archived">Archived</option>
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Visibility</label>
        <select
          value={localVisibility}
          onChange={(e) => setLocalVisibility(e.target.value)}
          className="h-8 rounded-md border bg-background px-2 text-sm"
        >
          <option value="internal">Internal</option>
          <option value="public">Public (sync to Confluence)</option>
        </select>
      </div>

      <div className="flex flex-1 flex-col gap-1">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Tags (comma-separated)</label>
        <Input
          value={tagInput}
          onChange={(e) => setTagInput(e.target.value)}
          className="h-8 text-sm"
          placeholder="runbook, sox-404, onboarding"
        />
      </div>

      <Button
        size="sm"
        variant={saved ? "default" : "outline"}
        disabled={!isDirty || setFlags.isPending}
        onClick={save}
        className="h-8"
      >
        {saved ? "Saved" : setFlags.isPending ? "Saving…" : "Apply flags"}
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Article editor (textarea + live preview toggle)
// ---------------------------------------------------------------------------

interface ArticleEditorProps {
  slug: string;
  initialBody: string;
  onSaved?: () => void;
}

function ArticleEditor({ slug, initialBody, onSaved }: ArticleEditorProps) {
  const [draft, setDraft] = useState(initialBody);
  const [preview, setPreview] = useState(false);
  const [note, setNote] = useState("");
  const upsert = useUpsertDoc();

  const isDirty = draft !== initialBody;

  const save = async () => {
    await upsert.mutateAsync({ slug, body_md: draft, note: note || undefined });
    onSaved?.();
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Button
          variant={preview ? "outline" : "default"}
          size="sm"
          onClick={() => setPreview(false)}
          className="gap-1"
        >
          <Edit3 className="size-3.5" />
          Edit
        </Button>
        <Button
          variant={preview ? "default" : "outline"}
          size="sm"
          onClick={() => setPreview(true)}
          className="gap-1"
        >
          <Eye className="size-3.5" />
          Preview
        </Button>
        <div className="ml-auto flex items-center gap-2">
          <Input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Revision note (optional)"
            className="h-7 w-48 text-xs"
          />
          <Button
            size="sm"
            disabled={!isDirty || upsert.isPending}
            onClick={save}
            className="h-7 gap-1"
          >
            <Save className="size-3.5" />
            {upsert.isPending ? "Saving…" : "Save"}
          </Button>
          {upsert.isError && (
            <span className="text-xs text-destructive">
              {(upsert.error as Error)?.message ?? "Save failed"}
            </span>
          )}
        </div>
      </div>

      {preview ? (
        <div className="min-h-64 rounded-lg border bg-background p-4">
          <Markdown>{draft}</Markdown>
        </div>
      ) : (
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className="min-h-64 w-full rounded-lg border bg-background p-3 font-mono text-sm leading-relaxed focus:outline-none focus:ring-1 focus:ring-ring"
          spellCheck={false}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Agent panel
// ---------------------------------------------------------------------------

function AgentPanel() {
  const agent = useDocsAgent();
  const [result, setResult] = useState<DocsAgentResponse | null>(null);
  // Which proposal slugs the human has ticked to apply at the gate.
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const waiting = result?.status === "waiting_approval";
  // Only proposals with a body are appliable.
  const appliable = (result?.suggestions ?? []).filter((s) => s.proposed_body_md);

  const run = async () => {
    const data = await agent.mutateAsync(0);
    setResult(data);
    setSelected(new Set());
  };

  const resume = async (decision: unknown, label: string) => {
    if (!result) return;
    try {
      const data = await agent.mutateAsync({ run_id: result.run_id, resume_decision: decision });
      setResult(data);
      const n = data.applied.filter((a) => !a.error).length;
      const failed = data.applied.filter((a) => a.error).length;
      toast.success(`${label}: ${n} revision(s) applied${failed ? `, ${failed} failed` : ""}`);
    } catch (e) {
      toast.error(`Apply failed: ${(e as Error).message}`);
    }
  };

  const toggle = (slug: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(slug) ? next.delete(slug) : next.add(slug);
      return next;
    });

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Bot className="size-4" />
          Docs Agent
        </CardTitle>
        <CardDescription className="text-xs">
          Reconcile → triage → suggest → human-approved apply. Proposals are never auto-applied.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Button
          size="sm"
          variant="outline"
          disabled={agent.isPending}
          onClick={run}
          className="gap-1"
        >
          <RefreshCw className={cn("size-3.5", agent.isPending && "animate-spin")} />
          {agent.isPending && !waiting ? "Running…" : "Run agent"}
        </Button>

        {agent.isError && (
          <p className="text-sm text-destructive">{(agent.error as Error)?.message ?? "Agent error"}</p>
        )}

        {result && (
          <div className="space-y-3 text-sm">
            <div className="flex items-center gap-2">
              <Badge variant={waiting ? "warning" : "success"} className="text-[10px]">
                {waiting ? "waiting approval" : "completed"}
              </Badge>
              <span className="font-mono text-[10px] text-muted-foreground">{result.run_id}</span>
            </div>
            <div>
              <span className="font-medium">Sync:</span>{" "}
              {result.reconcile.considered} public docs considered,{" "}
              {result.reconcile.live ? "live" : "dry-run"}, space={result.reconcile.space}
            </div>
            {result.triage.length > 0 && (
              <div>
                <div className="mb-1 font-medium">Triage ({result.triage.length})</div>
                <ul className="space-y-1">
                  {result.triage.map((t) => (
                    <li key={t.slug} className="flex items-center gap-2 text-xs">
                      <StatusBadge status={t.suggested_status as DocStatus} />
                      <span className="font-medium">{t.title || t.slug}</span>
                      <span className="text-muted-foreground">{t.reason}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {result.suggestions.length > 0 && (
              <div>
                <div className="mb-1 font-medium">Proposals ({result.suggestions.length})</div>
                <ul className="space-y-2">
                  {result.suggestions.map((s) => (
                    <li key={s.slug} className="rounded border bg-muted/40 px-3 py-2 text-xs">
                      <label className="flex items-start gap-2">
                        {waiting && s.proposed_body_md && (
                          <input
                            type="checkbox"
                            className="mt-0.5"
                            checked={selected.has(s.slug)}
                            onChange={() => toggle(s.slug)}
                          />
                        )}
                        <span className="min-w-0">
                          <span className="flex items-center gap-1.5 font-medium">
                            {s.title || s.slug}
                            {s.applied && <Check className="size-3 text-success" />}
                          </span>
                          <span className="mt-0.5 block text-muted-foreground">{s.rationale}</span>
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* HIL apply gate */}
            {waiting && appliable.length > 0 && (
              <div className="flex flex-wrap gap-2 border-t pt-2">
                <Button
                  size="sm"
                  disabled={agent.isPending || selected.size === 0}
                  onClick={() => resume([...selected], "Applied selected")}
                  className="gap-1"
                >
                  <Check className="size-3.5" />
                  Apply selected ({selected.size})
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={agent.isPending}
                  onClick={() => resume("all", "Applied all")}
                  className="gap-1"
                >
                  Apply all
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={agent.isPending}
                  onClick={() => resume("reject", "Rejected")}
                  className="gap-1 text-muted-foreground"
                >
                  <CircleSlash className="size-3.5" />
                  Reject
                </Button>
              </div>
            )}

            {!waiting && result.applied.length > 0 && (
              <div className="border-t pt-2">
                <div className="mb-1 font-medium">Applied ({result.applied.length})</div>
                <ul className="space-y-1 text-xs">
                  {result.applied.map((a) => (
                    <li key={a.slug} className={cn("flex items-center gap-2", a.error && "text-destructive")}>
                      <span className="font-medium">{a.slug}</span>
                      <span className="text-muted-foreground">
                        {a.error ? a.error : `→ v${a.version} (audited)`}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {result.triage.length === 0 && result.suggestions.length === 0 && (
              <p className="text-muted-foreground">All docs are healthy — no action needed.</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main route
// ---------------------------------------------------------------------------

export default function DocsWiki() {
  // Deep-link support: `/docs?doc=<slug>` (e.g. runbook links from /architecture).
  const initialSlug =
    typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("doc")
      : null;
  const [selectedSlug, setSelectedSlug] = useState<string | null>(initialSlug);
  const [searchQuery, setSearchQuery] = useState("");
  const [editing, setEditing] = useState(false);
  const [showAgent, setShowAgent] = useState(false);

  const tree = useDocsTree();
  const doc = useDoc(selectedSlug);
  const search = useDocsSearch(searchQuery);
  const sync = useDocsSync();

  const isSearching = searchQuery.length >= 2;
  const loading = tree.isLoading && !tree.data;
  const docLoading = doc.isLoading && !doc.data;

  const handleSaved = useCallback(() => {
    setEditing(false);
    doc.refetch();
  }, [doc]);

  const selectDoc = useCallback((slug: string) => {
    setSelectedSlug(slug);
    setEditing(false);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("doc", slug);
      window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
    }
  }, []);

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left nav */}
      <aside className="flex w-64 shrink-0 flex-col border-r bg-sidebar">
        {/* Search */}
        <div className="border-b p-3">
          <div className="relative">
            <Search className="absolute left-2.5 top-2 size-3.5 text-muted-foreground" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search docs…"
              className="h-7 pl-8 text-sm"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-2 top-1.5 text-muted-foreground hover:text-foreground"
              >
                <X className="size-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* Nav tree or search results */}
        {loading ? (
          <div className="space-y-2 p-3">
            {[...Array(6)].map((_, i) => (
              <Skeleton key={i} className="h-6 w-full" />
            ))}
          </div>
        ) : tree.isError ? (
          <div className="p-3">
            <p className="text-xs text-destructive">{(tree.error as Error)?.message ?? "Failed to load"}</p>
            <Button size="sm" variant="outline" onClick={() => tree.refetch()} className="mt-2 h-6 text-xs">
              Retry
            </Button>
          </div>
        ) : isSearching ? (
          <div className="flex-1 overflow-y-auto p-2">
            {search.isLoading ? (
              <Skeleton className="h-6 w-full" />
            ) : search.isError ? (
              <p className="text-xs text-destructive">Search error</p>
            ) : (search.data?.results.length ?? 0) === 0 ? (
              <p className="px-2 py-4 text-center text-xs text-muted-foreground">No results</p>
            ) : (
              search.data?.results.map((r) => (
                <button
                  key={r.slug}
                  onClick={() => {
                    selectDoc(r.slug);
                    setSearchQuery("");
                  }}
                  className="flex w-full flex-col rounded-md px-2 py-2 text-left hover:bg-sidebar-accent/50"
                >
                  <span className="text-sm font-medium">{r.title}</span>
                  {r.snippet && (
                    <span className="mt-0.5 truncate text-xs text-muted-foreground">{r.snippet}</span>
                  )}
                </button>
              ))
            )}
          </div>
        ) : (
          <NavTree
            groups={tree.data?.tree ?? []}
            selected={selectedSlug}
            onSelect={selectDoc}
          />
        )}

        {/* Sidebar footer actions */}
        <div className="border-t p-2 space-y-1">
          <button
            onClick={() => setShowAgent((v) => !v)}
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:bg-sidebar-accent/50 hover:text-foreground"
          >
            <Bot className="size-3.5" />
            Agent run
          </button>
          <button
            onClick={() => sync.mutate(undefined)}
            disabled={sync.isPending}
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:bg-sidebar-accent/50 hover:text-foreground disabled:opacity-50"
          >
            <RefreshCw className={cn("size-3.5", sync.isPending && "animate-spin")} />
            Sync to Confluence
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex flex-1 flex-col overflow-hidden">
        {/* Content area */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Agent panel (toggleable) */}
          {showAgent && <AgentPanel />}

          {!isSearching && <TeachingDocsCard onSelect={selectDoc} />}

          {/* Review queue */}
          {!isSearching && (tree.data?.review_queue.length ?? 0) > 0 && (
            <ReviewQueue
              items={tree.data!.review_queue}
              onSelect={selectDoc}
            />
          )}

          {/* Doc display */}
          {!selectedSlug ? (
            <div className="flex h-64 flex-col items-center justify-center text-center">
              <BookText className="mb-3 size-10 text-muted-foreground/40" />
              <p className="text-sm font-medium text-muted-foreground">Select a document to view</p>
              <p className="text-xs text-muted-foreground/60">
                {(tree.data?.count ?? 0) > 0
                  ? `${tree.data!.count} docs in the wiki`
                  : "No docs yet — import the corpus to get started"}
              </p>
            </div>
          ) : docLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-8 w-64" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-5/6" />
            </div>
          ) : doc.isError ? (
            <div className="flex flex-col items-center gap-3 py-12">
              <p className="text-sm text-destructive">{(doc.error as Error)?.message ?? "Failed to load document"}</p>
              <Button size="sm" variant="outline" onClick={() => doc.refetch()}>
                Retry
              </Button>
            </div>
          ) : doc.data ? (
            <div className="space-y-4">
              {/* Doc header */}
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-xl font-semibold tracking-tight">{doc.data.title || doc.data.slug}</h1>
                  <StatusBadge status={(doc.data.derived_status ?? doc.data.status) as DocStatus} />
                  <VisibilityBadge visibility={doc.data.visibility as DocVisibility} />
                  {doc.data.tags.map((tag) => (
                    <Badge key={tag} variant="outline" className="text-xs">
                      {tag}
                    </Badge>
                  ))}
                </div>
                <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
                  <span>path: <code className="rounded bg-muted px-1">{doc.data.path}</code></span>
                  <span>v{doc.data.version}</span>
                  {doc.data.owner && <span>by {doc.data.owner}</span>}
                  {doc.data.updated_at && (
                    <span>updated {new Date(doc.data.updated_at).toLocaleDateString()}</span>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant={editing ? "default" : "outline"}
                    onClick={() => setEditing((v) => !v)}
                    className="h-7 gap-1 text-xs"
                  >
                    {editing ? <X className="size-3" /> : <Edit3 className="size-3" />}
                    {editing ? "Cancel" : "Edit"}
                  </Button>
                </div>
              </div>

              {/* Flag/tag editor */}
              <FlagEditor
                slug={doc.data.slug}
                status={(doc.data.derived_status ?? doc.data.status) as DocStatus}
                visibility={doc.data.visibility as DocVisibility}
                tags={doc.data.tags}
              />

              {/* Body — editor or rendered */}
              {editing ? (
                <ArticleEditor slug={doc.data.slug} initialBody={doc.data.body_md} onSaved={handleSaved} />
              ) : (
                <div className="rounded-lg border bg-background p-5">
                  {doc.data.body_md ? (
                    <Markdown>{doc.data.body_md}</Markdown>
                  ) : (
                    <p className="text-sm text-muted-foreground italic">This document has no content yet.</p>
                  )}
                </div>
              )}

              {/* Revision history */}
              {doc.data.revisions.length > 0 && (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">Revision history ({doc.data.revisions.length})</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-1 text-xs text-muted-foreground">
                      {doc.data.revisions.map((rev) => (
                        <li key={rev._id} className="flex gap-3">
                          <span className="font-mono">v{rev.version}</span>
                          <span>{rev.author}</span>
                          {rev.note && <span className="italic">{rev.note}</span>}
                          <span className="ml-auto">{new Date(rev.created_at).toLocaleString()}</span>
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}
            </div>
          ) : null}
        </div>
      </main>
    </div>
  );
}
