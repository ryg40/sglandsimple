import { useEffect, useMemo, useRef, useState } from "react";
import { Copy, Play, Plus, Save, FolderOpen, Sparkles, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useCollections,
  usePipelines,
  useRunPrefix,
  useSavePipeline,
  useSuggest,
  useWranglerSample,
} from "@/lib/queries";
import {
  compileStage,
  decompile,
  inferStageOutputFields,
  newStage,
  selectedInputFields,
  STAGE_META,
  type EditableStage,
  type StageKind,
} from "@/lib/pipeline";
import type { FieldSummary, Row } from "@/lib/types";
import { cn } from "@/lib/utils";

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

interface PreviewState {
  loading: boolean;
  input: number;
  output: number;
  rows: Row[];
  error?: string;
}

interface SuccessfulPipelineState {
  collection: string;
  pipeline: Record<string, unknown>[];
  upto: number;
  source: "preview" | "save" | "load";
}

function stableJson(v: unknown): string {
  return JSON.stringify(v);
}

function formatStageJs(stage: Record<string, unknown>): string {
  return JSON.stringify(stage, null, 2);
}

function collectionRef(collection: string): string {
  return /^[A-Za-z_$][\w$]*$/.test(collection) ? `db.${collection}` : `db.getCollection(${JSON.stringify(collection)})`;
}

function formatPipelineJs(collection: string, pipeline: Record<string, unknown>[]): string {
  const body = pipeline.length
    ? pipeline.map((stage) => `  ${formatStageJs(stage).replace(/\n/g, "\n  ")}`).join(",\n")
    : "  // Add and run stages to build this aggregation pipeline.";
  return `${collectionRef(collection)}.aggregate([\n${body}\n])`;
}

async function copyText(label: string, text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`Copied ${label}`);
  } catch (e) {
    toast.error(`Copy failed: ${e instanceof Error ? e.message : String(e)}`);
  }
}

function uniqFields(fields: string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of fields) {
    const field = raw.trim();
    if (!field || seen.has(field)) continue;
    seen.add(field);
    out.push(field);
  }
  return out;
}

function fieldNamesFromRows(rows: Row[]): string[] {
  const fields: string[] = [];
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (!fields.includes(key)) fields.push(key);
    }
  }
  return fields;
}

export default function WranglerPanel() {
  const cols = useCollections();
  const [active, setActive] = useState<string | null>(null);
  const [stages, setStages] = useState<EditableStage[]>([]);
  const [previews, setPreviews] = useState<Record<number, PreviewState>>({});
  const [showSuggest, setShowSuggest] = useState(false);
  const [showLoad, setShowLoad] = useState(false);
  const [lastSuccessfulPipeline, setLastSuccessfulPipeline] = useState<SuccessfulPipelineState | null>(null);
  const stagesRef = useRef<EditableStage[]>([]);

  const sample = useWranglerSample(active);
  const runPrefix = useRunPrefix();
  const savePipeline = useSavePipeline();
  const suggest = useSuggest();
  const pipelines = usePipelines(showLoad ? active : null);

  useEffect(() => {
    if (!active && cols.data?.collections.length) setActive(cols.data.collections[0].name);
  }, [cols.data, active]);

  useEffect(() => {
    stagesRef.current = stages;
  }, [stages]);

  const fieldNames = useMemo(() => (sample.data?.field_summary ?? []).map((f) => f.field), [sample.data]);

  function clearPreviewsForIds(stageIds: number[]) {
    if (!stageIds.length) return;
    setPreviews((prev) => {
      const next = { ...prev };
      for (const id of stageIds) delete next[id];
      return next;
    });
  }

  function setStage(id: number, patch: Partial<EditableStage>) {
    const idx = stages.findIndex((st) => st.id === id);
    if (idx >= 0) clearPreviewsForIds(stages.slice(idx).map((st) => st.id));
    setStages((s) => s.map((st) => (st.id === id ? { ...st, ...patch } : st)));
  }

  function addStage(kind: StageKind, seedField?: string) {
    const st = newStage(kind, seedField);
    setStages((s) => [...s, st]);
  }

  function buildPipeline(uptoIdx: number, source = stagesRef.current) {
    return source.slice(0, uptoIdx + 1).map(compileStage);
  }

  const availableFieldsByStage = useMemo(() => {
    const byStage: string[][] = [];
    let available = uniqFields(fieldNames);
    for (const st of stages) {
      byStage.push(available);
      const preview = previews[st.id];
      if (preview && !preview.loading && !preview.error) {
        const previewFields = fieldNamesFromRows(preview.rows);
        available = previewFields.length ? uniqFields(previewFields) : inferStageOutputFields(available, st);
      } else {
        available = inferStageOutputFields(available, st);
      }
    }
    return byStage;
  }, [fieldNames, previews, stages]);

  const currentPipeline = useMemo(() => stages.map(compileStage), [stages]);
  const lastSuccessfulCode = useMemo(
    () => lastSuccessfulPipeline ? formatPipelineJs(lastSuccessfulPipeline.collection, lastSuccessfulPipeline.pipeline) : "",
    [lastSuccessfulPipeline],
  );
  const currentFingerprint = stableJson(currentPipeline);
  const successFingerprint = lastSuccessfulPipeline ? stableJson(lastSuccessfulPipeline.pipeline) : "";
  const pipelineIsCurrent = !!lastSuccessfulPipeline && lastSuccessfulPipeline.collection === active && successFingerprint === currentFingerprint;

  async function runUpTo(idx: number) {
    const currentStages = stagesRef.current;
    const st = currentStages[idx];
    if (!st || !active) return;
    setPreviews((p) => ({ ...p, [st.id]: { ...(p[st.id] ?? { input: 0, output: 0, rows: [] }), loading: true } }));
    try {
      const pipeline = buildPipeline(idx, currentStages);
      const data = await runPrefix.mutateAsync({ collection: active, pipeline, upto: idx });
      setPreviews((p) => ({ ...p, [st.id]: { loading: false, input: data.input_count, output: data.output_count, rows: data.rows } }));
      setLastSuccessfulPipeline({ collection: active, pipeline, upto: idx, source: "preview" });
    } catch (e) {
      setPreviews((p) => ({ ...p, [st.id]: { loading: false, input: 0, output: 0, rows: [], error: (e as Error).message } }));
      toast.error(`Stage ${idx}: ${(e as Error).message}`);
    }
  }

  // live re-run: debounce edits per stage
  const timers = useRef<Record<number, ReturnType<typeof setTimeout>>>({});
  function liveRerun(idx: number) {
    const st = stagesRef.current[idx];
    if (!st?.live) return;
    clearTimeout(timers.current[st.id]);
    timers.current[st.id] = setTimeout(() => {
      const currentStages = stagesRef.current;
      for (let i = idx; i < currentStages.length; i++) if (currentStages[i].live) runUpTo(i);
    }, 300);
  }

  function hydrate(raw: { name: string; stages: Record<string, unknown>[]; collection?: string }) {
    const loaded = decompile(raw.stages);
    setStages(loaded);
    setPreviews({});
    setLastSuccessfulPipeline({ collection: raw.collection ?? active ?? "collection", pipeline: raw.stages, upto: raw.stages.length - 1, source: "load" });
    setShowSuggest(false);
    setShowLoad(false);
    toast.success(`Loaded “${raw.name}”`);
  }

  async function doSave() {
    if (!stages.length || !active) return toast.message("Nothing to save");
    const name = prompt("Pipeline name:");
    if (!name) return;
    try {
      const pipeline = stages.map(compileStage);
      const r = await savePipeline.mutateAsync({ name, collection: active, stages: pipeline });
      setLastSuccessfulPipeline({ collection: active, pipeline, upto: stages.length - 1, source: "save" });
      toast.success(`Saved “${name}” (${r._id})`);
    } catch (e) {
      toast.error(`Save failed: ${(e as Error).message}`);
    }
  }

  async function doSuggest() {
    if (!active) return;
    setShowSuggest(true);
    try {
      await suggest.mutateAsync({ collection: active });
    } catch (e) {
      toast.error(`Suggest failed: ${(e as Error).message}`);
    }
  }

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col p-5">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <Tabs value={active ?? ""} onValueChange={(v) => { setActive(v); setStages([]); setPreviews({}); setLastSuccessfulPipeline(null); }}>
            <TabsList>
              {cols.data?.collections.map((c) => (
                <TabsTrigger key={c.name} value={c.name}>{c.name}</TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          <div className="ml-auto flex gap-2">
            <Button size="sm" variant="outline" onClick={() => setShowLoad(true)} disabled={!active}>
              <FolderOpen className="size-4" /> Load
            </Button>
            <Button size="sm" variant="outline" onClick={doSave} disabled={!stages.length}>
              <Save className="size-4" /> Save
            </Button>
            <Button size="sm" onClick={doSuggest} disabled={!active}>
              <Sparkles className="size-4" /> Ask agent
            </Button>
          </div>
        </div>

        {/* field chips */}
        <Card className="mb-4 p-3">
          {sample.isLoading ? (
            <div className="flex gap-2">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-7 w-24" />)}</div>
          ) : (
            <>
              <div className="flex flex-wrap gap-2">
                {(sample.data?.field_summary ?? []).map((f: FieldSummary) => (
                  <button
                    key={f.field}
                    title="click = filter · alt-click = project · right-click = group by"
                    onClick={(e) => (e.altKey ? addStage("project", f.field) : addStage("match", f.field))}
                    onContextMenu={(e) => { e.preventDefault(); addStage("group", f.field); }}
                    className="inline-flex items-center gap-1.5 rounded-full border border-border bg-secondary px-2.5 py-1 text-xs hover:bg-accent"
                  >
                    <span className="font-medium">{f.field}</span>
                    <span className="text-muted-foreground">{f.types.join("|")}</span>
                    {f.cardinality != null && <span className="text-[var(--chart-1)]">{f.cardinality}</span>}
                  </button>
                ))}
              </div>
              <p className="mt-2 text-[11px] text-muted-foreground">
                click = filter · alt-click = project · right-click = group by
              </p>
            </>
          )}
        </Card>

        {/* stage cards */}
        <div className="flex-1 space-y-3 overflow-y-auto">
          {stages.map((st, idx) => (
            <StageCard
              key={st.id}
              st={st}
              fieldNames={availableFieldsByStage[idx] ?? fieldNames}
              preview={previews[st.id]}
              onChange={(patch) => { setStage(st.id, patch); liveRerun(idx); }}
              onRun={() => runUpTo(idx)}
              onRemove={() => {
                clearPreviewsForIds(stages.slice(idx).map((x) => x.id));
                setStages((s) => s.filter((x) => x.id !== st.id));
              }}
              onDuplicate={() => {
                clearPreviewsForIds(stages.slice(idx + 1).map((x) => x.id));
                setStages((s) => {
                  const copy = { ...st, id: newStage(st.kind).id };
                  const i = s.findIndex((x) => x.id === st.id);
                  return [...s.slice(0, i + 1), copy, ...s.slice(i + 1)];
                });
              }}
            />
          ))}

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <span className="text-sm text-muted-foreground">Add stage:</span>
            {(["match", "group", "project", "sort", "limit"] as StageKind[]).map((k) => (
              <Button key={k} size="sm" variant="outline" onClick={() => addStage(k)}>
                <Plus className="size-3.5" /> {STAGE_META[k].title.split(" ")[0]}
              </Button>
            ))}
            {stages.length > 0 && (
              <Button size="sm" variant="ghost" className="ml-auto" onClick={() => runUpTo(stages.length - 1)}>
                <Play className="size-3.5" /> Run all
              </Button>
            )}
          </div>
        </div>
      </div>

      <PipelineCodePanel
        active={active}
        currentPipeline={currentPipeline}
        lastSuccessfulPipeline={lastSuccessfulPipeline}
        code={lastSuccessfulCode}
        isCurrent={pipelineIsCurrent}
      />

      {showSuggest && (
        <SidePanel title="Suggested pipelines" onClose={() => setShowSuggest(false)}>
          {suggest.isPending ? (
            <p className="text-sm text-muted-foreground">Asking the agent…</p>
          ) : !suggest.data?.pipelines.length ? (
            <p className="text-sm text-muted-foreground">No valid suggestions returned.</p>
          ) : (
            suggest.data.pipelines.map((p, i) => (
              <Card key={i} className="p-3">
                <h4 className="text-sm font-semibold">{p.name}</h4>
                <p className="mb-2 text-xs text-muted-foreground">{p.rationale}</p>
                <pre className="max-h-40 overflow-auto rounded bg-muted p-2 text-[11px]">{JSON.stringify(p.stages, null, 2)}</pre>
                <Button size="sm" className="mt-2" onClick={() => hydrate(p)}>Load into builder</Button>
              </Card>
            ))
          )}
        </SidePanel>
      )}

      {showLoad && (
        <SidePanel title="Saved pipelines" onClose={() => setShowLoad(false)}>
          {pipelines.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : !pipelines.data?.pipelines.length ? (
            <p className="text-sm text-muted-foreground">No saved pipelines.</p>
          ) : (
            pipelines.data.pipelines.map((p) => (
              <Card key={p._id} className="p-3">
                <h4 className="text-sm font-semibold">{p.name}</h4>
                <p className="mb-2 text-xs text-muted-foreground">{p.stages.length} stages · {p.collection}</p>
                <Button size="sm" onClick={() => hydrate(p)}>Load</Button>
              </Card>
            ))
          )}
        </SidePanel>
      )}
    </div>
  );
}

function PipelineCodePanel({
  active,
  currentPipeline,
  lastSuccessfulPipeline,
  code,
  isCurrent,
}: {
  active: string | null;
  currentPipeline: Record<string, unknown>[];
  lastSuccessfulPipeline: SuccessfulPipelineState | null;
  code: string;
  isCurrent: boolean;
}) {
  const visiblePipeline = lastSuccessfulPipeline?.pipeline ?? currentPipeline;
  const visibleCollection = lastSuccessfulPipeline?.collection ?? active ?? "collection";
  const visibleCode = code || formatPipelineJs(visibleCollection, visiblePipeline);
  const status = !lastSuccessfulPipeline
    ? "draft"
    : isCurrent
      ? `current · ${lastSuccessfulPipeline.source}`
      : `last successful · ${lastSuccessfulPipeline.source}`;

  return (
    <aside className="hidden w-[28rem] shrink-0 flex-col border-l border-border bg-card/70 xl:flex">
      <div className="border-b border-border px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold">MongoDB aggregation JS</h3>
            <p className="text-[11px] text-muted-foreground">
              {status} {lastSuccessfulPipeline ? `· ${lastSuccessfulPipeline.pipeline.length} stage(s)` : "· run a stage to lock in valid code"}
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => copyText("full pipeline", visibleCode)}
            disabled={!visiblePipeline.length}
          >
            <Copy className="size-3.5" /> Copy all
          </Button>
        </div>
        {!isCurrent && lastSuccessfulPipeline && (
          <p className="mt-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-700 dark:text-amber-300">
            Current visual edits have not run successfully yet; showing the last successful pipeline.
          </p>
        )}
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        <pre className="overflow-auto rounded-lg border border-border bg-slate-950 p-3 text-[11px] leading-relaxed text-slate-100 shadow-inner">
          <code>{visibleCode}</code>
        </pre>

        <div className="space-y-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Stage snippets</div>
          {visiblePipeline.length === 0 ? (
            <p className="rounded-md border border-dashed border-border p-3 text-xs text-muted-foreground">
              Add stages and run a preview to generate copyable snippets.
            </p>
          ) : (
            visiblePipeline.map((stage, idx) => {
              const stageCode = formatStageJs(stage);
              const op = Object.keys(stage)[0] ?? `stage ${idx + 1}`;
              return (
                <Card key={`${idx}-${op}`} className="space-y-2 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold">{idx + 1}. {op}</span>
                    <Button size="sm" variant="ghost" onClick={() => copyText(`${op} stage`, stageCode)}>
                      <Copy className="size-3.5" /> Copy stage
                    </Button>
                  </div>
                  <pre className="max-h-36 overflow-auto rounded-md bg-muted p-2 text-[11px] leading-relaxed">
                    <code>{stageCode}</code>
                  </pre>
                </Card>
              );
            })
          )}
        </div>
      </div>
    </aside>
  );
}

function SidePanel({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="flex w-96 max-w-[90vw] flex-col border-l border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <strong className="text-sm">{title}</strong>
        <button onClick={onClose} aria-label="Close panel" className="text-muted-foreground hover:text-foreground">
          <X className="size-4" />
        </button>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-4">{children}</div>
    </div>
  );
}

function FieldSelect({ value, fields, onChange }: { value: string; fields: string[]; onChange: (v: string) => void }) {
  const stale = !!value && !fields.includes(value);
  const options = stale ? [value, ...fields.filter((field) => field !== value)] : fields;

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        "rounded-md border border-input bg-card px-2 py-1 text-xs",
        stale && "border-destructive text-destructive"
      )}
    >
      <option value="">—</option>
      {options.map((f) => <option key={f} value={f}>{stale && f === value ? `${f} (stale)` : f}</option>)}
    </select>
  );
}

function addAllProjectFields(existing: EditableStage["projects"], fieldNames: string[]): EditableStage["projects"] {
  const fields: string[] = [];
  const seen = new Set<string>();
  for (const row of existing ?? []) {
    const field = row.field.trim();
    if (field && !seen.has(field)) {
      seen.add(field);
      fields.push(field);
    }
  }
  for (const field of fieldNames) {
    if (field && !seen.has(field)) {
      seen.add(field);
      fields.push(field);
    }
  }
  return fields.map((field) => ({ field, include: true }));
}

function excludeAllProjectFields(fieldNames: string[]): EditableStage["projects"] {
  return fieldNames.filter(Boolean).map((field) => ({ field, include: false }));
}

function StageCard({
  st, fieldNames, preview, onChange, onRun, onRemove, onDuplicate,
}: {
  st: EditableStage;
  fieldNames: string[];
  preview?: PreviewState;
  onChange: (patch: Partial<EditableStage>) => void;
  onRun: () => void;
  onRemove: () => void;
  onDuplicate: () => void;
}) {
  const meta = STAGE_META[st.kind];
  const staleFields = useMemo(
    () => selectedInputFields(st).filter((field, idx, all) => !!field && !fieldNames.includes(field) && all.indexOf(field) === idx),
    [fieldNames, st]
  );
  const cols = useMemo(() => {
    const seen: string[] = [];
    for (const r of preview?.rows ?? []) for (const k of Object.keys(r)) if (!seen.includes(k)) seen.push(k);
    return seen;
  }, [preview]);

  return (
    <Card className="overflow-hidden p-0">
      <div className="flex items-center gap-2 border-b border-border bg-muted/60 px-3 py-2">
        <span className="font-bold">{meta.icon}</span>
        <span className="text-sm font-medium">{meta.title}</span>
        {preview && !preview.loading && !preview.error && (
          <span className="ml-auto tnum text-xs text-success">{preview.input} → {preview.output} rows</span>
        )}
        {preview?.loading && <span className="ml-auto text-xs text-muted-foreground">running…</span>}
        <label className={cn("flex items-center gap-1 text-[11px] text-muted-foreground", !preview && "ml-auto")}>
          <input type="checkbox" checked={st.live} onChange={(e) => onChange({ live: e.target.checked })} /> live
        </label>
        <button onClick={onDuplicate} aria-label="Duplicate stage" className="text-muted-foreground hover:text-foreground"><Copy className="size-3.5" /></button>
        <button onClick={onRemove} aria-label="Remove stage" className="text-muted-foreground hover:text-destructive"><Trash2 className="size-3.5" /></button>
      </div>

      <div className="space-y-2 p-3">
        {staleFields.length > 0 && (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            Upstream fields changed. Review stale selections: {staleFields.join(", ")}.
          </div>
        )}
        {st.kind === "match" && (st.clauses ?? []).map((c, ci) => (
          <div key={ci} className="flex flex-wrap items-center gap-2">
            <FieldSelect value={c.field} fields={fieldNames} onChange={(v) => onChange({ clauses: st.clauses!.map((x, i) => i === ci ? { ...x, field: v } : x) })} />
            <select value={c.op} onChange={(e) => onChange({ clauses: st.clauses!.map((x, i) => i === ci ? { ...x, op: e.target.value } : x) })} className="rounded-md border border-input bg-card px-2 py-1 text-xs">
              {["=", "!=", ">", ">=", "<", "<=", "contains", "regex", "in", "exists"].map((o) => <option key={o}>{o}</option>)}
            </select>
            <input value={c.value} placeholder="value" onChange={(e) => onChange({ clauses: st.clauses!.map((x, i) => i === ci ? { ...x, value: e.target.value } : x) })} className="rounded-md border border-input bg-card px-2 py-1 text-xs" />
            <button className="text-destructive" onClick={() => onChange({ clauses: st.clauses!.filter((_, i) => i !== ci) })}>−</button>
          </div>
        ))}
        {st.kind === "match" && <button className="text-xs text-primary" onClick={() => onChange({ clauses: [...(st.clauses ?? []), { field: "", op: "=", value: "" }] })}>+ condition</button>}

        {st.kind === "group" && (
          <>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">group by</span>
              <FieldSelect value={st.groupKeys?.[0] ?? ""} fields={fieldNames} onChange={(v) => onChange({ groupKeys: v ? [v] : [] })} />
            </div>
            {(st.accs ?? []).map((a, ai) => (
              <div key={ai} className="flex flex-wrap items-center gap-2">
                <input value={a.name} placeholder="out name" onChange={(e) => onChange({ accs: st.accs!.map((x, i) => i === ai ? { ...x, name: e.target.value } : x) })} className="w-24 rounded-md border border-input bg-card px-2 py-1 text-xs" />
                <select value={a.fn} onChange={(e) => onChange({ accs: st.accs!.map((x, i) => i === ai ? { ...x, fn: e.target.value } : x) })} className="rounded-md border border-input bg-card px-2 py-1 text-xs">
                  {["count", "sum", "avg", "min", "max", "addToSet", "first", "last"].map((o) => <option key={o}>{o}</option>)}
                </select>
                <FieldSelect value={a.field} fields={fieldNames} onChange={(v) => onChange({ accs: st.accs!.map((x, i) => i === ai ? { ...x, field: v } : x) })} />
                <button className="text-destructive" onClick={() => onChange({ accs: st.accs!.filter((_, i) => i !== ai) })}>−</button>
              </div>
            ))}
            <button className="text-xs text-primary" onClick={() => onChange({ accs: [...(st.accs ?? []), { name: "", fn: "sum", field: "" }] })}>+ accumulator</button>
          </>
        )}

        {st.kind === "project" && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => onChange({ projects: addAllProjectFields(st.projects, fieldNames) })}
                disabled={fieldNames.length === 0}
              >
                Add all fields
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => onChange({ projects: excludeAllProjectFields(fieldNames) })}
                disabled={fieldNames.length === 0}
              >
                Exclude all (*:0)
              </Button>
              <Button size="sm" variant="ghost" onClick={() => onChange({ projects: [] })} disabled={(st.projects ?? []).length === 0}>
                Clear fields
              </Button>
              {fieldNames.length === 0 && <span className="text-[11px] text-muted-foreground">Sample fields are still loading or unavailable.</span>}
            </div>
            {(st.projects ?? []).map((c, ci) => (
              <div key={ci} className="flex flex-wrap items-center gap-2">
                <FieldSelect value={c.field} fields={fieldNames} onChange={(v) => onChange({ projects: st.projects!.map((x, i) => i === ci ? { ...x, field: v } : x) })} />
                <select value={c.include ? "1" : "0"} onChange={(e) => onChange({ projects: st.projects!.map((x, i) => i === ci ? { ...x, include: e.target.value === "1" } : x) })} className="rounded-md border border-input bg-card px-2 py-1 text-xs">
                  <option value="1">include</option><option value="0">exclude</option>
                </select>
                <input
                  value={c.alias ?? ""}
                  placeholder="alias (optional)"
                  onChange={(e) => onChange({ projects: st.projects!.map((x, i) => i === ci ? { ...x, alias: e.target.value } : x) })}
                  disabled={!c.include}
                  className="w-32 rounded-md border border-input bg-card px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-50"
                />
                <button className="text-destructive" onClick={() => onChange({ projects: st.projects!.filter((_, i) => i !== ci) })}>−</button>
              </div>
            ))}
            <button className="text-xs text-primary" onClick={() => onChange({ projects: [...(st.projects ?? []), { field: "", include: true }] })}>+ field</button>
          </>
        )}

        {st.kind === "sort" && (st.sorts ?? []).map((c, ci) => (
          <div key={ci} className="flex items-center gap-2">
            <FieldSelect value={c.field} fields={fieldNames} onChange={(v) => onChange({ sorts: st.sorts!.map((x, i) => i === ci ? { ...x, field: v } : x) })} />
            <select value={String(c.dir)} onChange={(e) => onChange({ sorts: st.sorts!.map((x, i) => i === ci ? { ...x, dir: Number(e.target.value) } : x) })} className="rounded-md border border-input bg-card px-2 py-1 text-xs">
              <option value="-1">desc</option><option value="1">asc</option>
            </select>
            <button className="text-destructive" onClick={() => onChange({ sorts: st.sorts!.filter((_, i) => i !== ci) })}>−</button>
          </div>
        ))}
        {st.kind === "sort" && <button className="text-xs text-primary" onClick={() => onChange({ sorts: [...(st.sorts ?? []), { field: "", dir: -1 }] })}>+ sort key</button>}

        {st.kind === "limit" && (
          <input type="number" min={1} value={st.limit ?? 10} onChange={(e) => onChange({ limit: Number(e.target.value) })} className="w-24 rounded-md border border-input bg-card px-2 py-1 text-xs" />
        )}

        <div className="pt-1">
          <Button size="sm" variant="outline" onClick={onRun}><Play className="size-3.5" /> Run up to here</Button>
        </div>

        {preview?.error && <p className="text-xs text-destructive">{preview.error}</p>}
        {preview && !preview.error && preview.rows.length > 0 && (
          <div className="mt-2 max-h-64 overflow-auto rounded-md border border-border">
            <table className="w-max min-w-full text-xs">
              <thead>
                <tr>{cols.map((c) => <th key={c} className="sticky top-0 border-b border-border bg-muted px-2 py-1 text-left">{c}</th>)}</tr>
              </thead>
              <tbody>
                {preview.rows.map((r, ri) => (
                  <tr key={ri} className="odd:bg-muted/30">
                    {cols.map((c) => <td key={c} className="border-b border-border/50 px-2 py-1 max-w-64 truncate whitespace-nowrap">{fmt(r[c])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Card>
  );
}
