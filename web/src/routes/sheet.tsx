import { useEffect, useMemo, useState } from "react";
import { Loader2, Plus, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  useApplyNl,
  useCollections,
  useDeleteRow,
  useInsertRow,
  useSheetRows,
  useUpdateCell,
} from "@/lib/queries";
import type { Row } from "@/lib/types";
import { cn } from "@/lib/utils";

const PAGE = 50;

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export default function SheetPanel() {
  const cols = useCollections();
  const [active, setActive] = useState<string | null>(null);
  const [skip, setSkip] = useState(0);
  const [nl, setNl] = useState("");

  useEffect(() => {
    if (!active && cols.data?.collections.length) setActive(cols.data.collections[0].name);
  }, [cols.data, active]);

  const rows = useSheetRows(active, skip, PAGE);
  const updateCell = useUpdateCell();
  const insertRow = useInsertRow();
  const deleteRow = useDeleteRow();
  const applyNl = useApplyNl();

  const columns = useMemo(() => {
    const seen: string[] = [];
    for (const r of rows.data?.rows ?? []) for (const k of Object.keys(r)) if (!seen.includes(k)) seen.push(k);
    return seen.sort((a, b) => (a === "_id" ? -1 : b === "_id" ? 1 : 0));
  }, [rows.data]);

  const [edit, setEdit] = useState<{ id: string; field: string } | null>(null);
  const [draft, setDraft] = useState("");

  function beginEdit(r: Row, field: string) {
    if (field === "_id") return;
    setEdit({ id: String(r._id), field });
    setDraft(fmt(r[field]));
  }

  async function commit(r: Row, field: string) {
    setEdit(null);
    const current = fmt(r[field]);
    if (draft === current) return;
    let value: unknown = draft;
    const t = draft.trim();
    if (t === "true") value = true;
    else if (t === "false") value = false;
    else if (/^-?\d+(\.\d+)?$/.test(t)) value = Number(t);
    else if (t.startsWith("{") || t.startsWith("[")) {
      try {
        value = JSON.parse(t);
      } catch {
        /* keep string */
      }
    }
    try {
      await updateCell.mutateAsync({ collection: active!, _id: String(r._id), field, value, skip, limit: PAGE });
      toast.success(`Updated ${field}`);
    } catch (e) {
      toast.error(`Save failed: ${(e as Error).message}`);
    }
  }

  async function addRow() {
    const id = prompt(`New ${active} row — _id (blank = auto):`);
    if (id === null) return;
    const doc: Record<string, unknown> = {};
    if (id.trim()) doc._id = id.trim();
    try {
      await insertRow.mutateAsync({ collection: active!, doc });
      toast.success("Row inserted");
    } catch (e) {
      toast.error(`Insert failed: ${(e as Error).message}`);
    }
  }

  async function removeRow(r: Row) {
    if (!confirm(`Delete ${active} ${r._id}? Recorded in the audit log.`)) return;
    try {
      await deleteRow.mutateAsync({ collection: active!, _id: String(r._id), skip, limit: PAGE });
      toast.success(`Deleted ${r._id}`);
    } catch (e) {
      toast.error(`Delete failed: ${(e as Error).message}`);
    }
  }

  async function runNl(e: React.FormEvent) {
    e.preventDefault();
    const instruction = nl.trim();
    if (!instruction || !active) return;
    const id = toast.loading(`Applying to ${active}…`);
    try {
      const res = await applyNl.mutateAsync({ collection: active, instruction });
      if (res.isError || res.error) toast.error(res.error || res.summary || "failed", { id });
      else toast.success(`${(res.applied ?? []).length} op(s) applied`, { id });
      setNl("");
    } catch (err) {
      toast.error(`NL failed: ${(err as Error).message}`, { id });
    }
  }

  const total = rows.data?.total ?? 0;
  const from = rows.data?.rows.length ? skip + 1 : 0;
  const to = skip + (rows.data?.rows.length ?? 0);

  return (
    <div className="flex h-full flex-col p-5">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs value={active ?? ""} onValueChange={(v) => { setActive(v); setSkip(0); }}>
          <TabsList>
            {cols.data?.collections.map((c) => (
              <TabsTrigger key={c.name} value={c.name}>
                {c.name}
                <span className="ml-1.5 text-xs text-muted-foreground">{c.count}</span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <Button size="sm" variant="outline" onClick={addRow} disabled={!active}>
          <Plus className="size-4" /> Add row
        </Button>
        <div className="ml-auto flex items-center gap-2 text-sm text-muted-foreground">
          <span className="tnum">{from}–{to} of {total}</span>
          <Button size="sm" variant="outline" disabled={skip <= 0} onClick={() => setSkip(Math.max(0, skip - PAGE))}>
            ‹
          </Button>
          <Button size="sm" variant="outline" disabled={to >= total} onClick={() => setSkip(skip + PAGE)}>
            ›
          </Button>
        </div>
      </div>

      <form onSubmit={runNl} className="mb-4 flex items-center gap-2">
        <Sparkles className="size-4 text-muted-foreground" />
        <Input
          value={nl}
          onChange={(e) => setNl(e.target.value)}
          placeholder="Describe an edit — e.g. change Bob Carter's dept to Platform"
          aria-label="Natural-language edit"
        />
        <Button type="submit" disabled={applyNl.isPending || !active}>
          {applyNl.isPending ? <Loader2 className="size-4 animate-spin" /> : "Apply"}
        </Button>
      </form>

      <Card className="flex-1 overflow-auto p-0">
        {rows.isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 10 }).map((_, i) => <Skeleton key={i} className="h-8 w-full" />)}
          </div>
        ) : rows.isError ? (
          <div className="p-8 text-center text-sm text-muted-foreground">
            Couldn’t load rows: {(rows.error as Error)?.message}
            <div className="mt-3"><Button size="sm" variant="outline" onClick={() => rows.refetch()}>Retry</Button></div>
          </div>
        ) : !rows.data?.rows.length ? (
          <div className="p-8 text-center text-sm text-muted-foreground">No rows.</div>
        ) : (
          <table className="w-max min-w-full border-separate border-spacing-0 text-sm">
            <thead>
              <tr>
                {columns.map((c) => (
                  <th
                    key={c}
                    className={cn(
                      "sticky top-0 z-10 border-b border-border bg-muted px-3 py-2 text-left font-medium whitespace-nowrap",
                      c === "_id" && "sticky left-0 z-20"
                    )}
                  >
                    {c}
                  </th>
                ))}
                <th className="sticky top-0 z-10 border-b border-border bg-muted px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {rows.data.rows.map((r) => (
                <tr key={String(r._id)} className="group hover:bg-accent/40">
                  {columns.map((c) => {
                    const editing = edit?.id === String(r._id) && edit?.field === c;
                    return (
                      <td
                        key={c}
                        onClick={() => beginEdit(r, c)}
                        className={cn(
                          "border-b border-border/60 px-3 py-1.5 whitespace-nowrap",
                          c === "_id"
                            ? "sticky left-0 bg-card font-mono text-xs text-muted-foreground group-hover:bg-accent/40"
                            : "cursor-cell"
                        )}
                      >
                        {editing ? (
                          <input
                            autoFocus
                            value={draft}
                            onChange={(e) => setDraft(e.target.value)}
                            onBlur={() => commit(r, c)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") { e.preventDefault(); commit(r, c); }
                              if (e.key === "Escape") { e.preventDefault(); setEdit(null); }
                            }}
                            className="w-full min-w-32 rounded border border-ring bg-card px-1.5 py-0.5 text-sm focus-visible:outline-none"
                          />
                        ) : (
                          <span className="block max-w-80 truncate">{fmt(r[c])}</span>
                        )}
                      </td>
                    );
                  })}
                  <td className="border-b border-border/60 px-2 py-1.5">
                    <button
                      aria-label={`Delete row ${r._id}`}
                      onClick={() => removeRow(r)}
                      className="text-muted-foreground opacity-0 transition hover:text-destructive group-hover:opacity-100"
                    >
                      <Trash2 className="size-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
