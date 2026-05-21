import { useMemo, useState } from "react";
import { toast } from "sonner";
import {
  useJiraIssues,
  useStageJiraEdits,
  useValidateJira,
  useRevertJira,
  useApplyJira,
} from "../lib/queries";
import type { JiraApplyResult, JiraIssueRow } from "../lib/types";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { Skeleton } from "./ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import { AlertCircle, Save, CheckCircle2, Undo2, Rocket, AlertTriangle } from "lucide-react";

// Stage 16 — editable Jira grid with HIL-gated bulk apply.
// Edits are local until Save (stages them), Validate runs server rules, and
// Apply pushes only validated rows (dry-run unless JIRA_WRITES_ENABLED).

const EDITABLE = ["status", "assignee", "priority", "story_points", "summary", "duedate"] as const;
type EditableField = (typeof EDITABLE)[number];

const STATUS_OPTS = ["To Do", "In Progress", "Blocked", "In Review", "Done", "Deferred"];
const PRIORITY_OPTS = ["Lowest", "Low", "Medium", "High", "Highest", "Critical"];

type LocalEdits = Record<string, Partial<Record<EditableField, string>>>; // key -> field -> value

function stageBadge(row: JiraIssueRow) {
  const s = row._stage_status;
  if (!s) return null;
  if (s === "validated") return <Badge variant="success" className="text-[9px]">validated</Badge>;
  if (s === "invalid") return <Badge variant="destructive" className="text-[9px]">invalid</Badge>;
  if (s === "applied") return <Badge variant="accent" className="text-[9px]">applied</Badge>;
  return <Badge variant="warning" className="text-[9px]">staged</Badge>;
}

export function JiraEditableGrid() {
  const { data, isLoading, isError, error, refetch } = useJiraIssues();
  const stage = useStageJiraEdits();
  const validate = useValidateJira();
  const revert = useRevertJira();
  const apply = useApplyJira();

  const [edits, setEdits] = useState<LocalEdits>({});
  const [applyOpen, setApplyOpen] = useState(false);
  const [applyResult, setApplyResult] = useState<JiraApplyResult | null>(null);

  const rows = data?.issues ?? [];
  const dirtyCount = Object.values(edits).reduce((n, f) => n + Object.keys(f).length, 0);

  // current displayed value: local edit > staged proposal > live value
  const shown = (row: JiraIssueRow, field: EditableField): string => {
    const local = edits[row.key]?.[field];
    if (local !== undefined) return local;
    const staged = row._staged?.[field];
    if (staged !== undefined && staged !== null) return String(staged);
    const v = (row as Record<string, unknown>)[field];
    return v === undefined || v === null ? "" : String(v);
  };

  const isDirty = (key: string, field: EditableField) => edits[key]?.[field] !== undefined;

  const setCell = (key: string, field: EditableField, value: string) => {
    setEdits((prev) => ({ ...prev, [key]: { ...prev[key], [field]: value } }));
  };

  const buildStagePayload = () =>
    Object.entries(edits).map(([issue_key, fields]) => ({
      issue_key,
      changes: Object.fromEntries(
        Object.entries(fields).map(([f, v]) => [
          f,
          f === "story_points" ? (v === "" ? null : Number(v)) : v,
        ]),
      ),
    }));

  const onSave = async () => {
    if (dirtyCount === 0) {
      toast.info("No edits to stage");
      return;
    }
    try {
      const res = await stage.mutateAsync(buildStagePayload());
      setEdits({});
      toast.success(`Staged ${res.staged.length} issue(s) (HIL draft — not sent to Jira)`);
      if (res.rejected.length) toast.warning(`${res.rejected.length} rejected: ${res.rejected.map((r) => r.reason).join("; ")}`);
    } catch (e) {
      toast.error(`Stage failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const onValidate = async () => {
    try {
      const res = await validate.mutateAsync(undefined);
      const bad = res.results.filter((r) => r.status === "invalid");
      if (bad.length) {
        toast.error(`${bad.length} invalid: ${bad.map((b) => `${b.issue_key} (${b.validation.errors.map((e) => e.message).join(", ")})`).join("; ")}`);
      } else {
        toast.success(`Validated ${res.validated} staged issue(s)`);
      }
    } catch (e) {
      toast.error(`Validate failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const onRevert = async () => {
    try {
      const res = await revert.mutateAsync(undefined);
      setEdits({});
      toast.success(`Reverted ${res.reverted.length} staged issue(s)`);
    } catch (e) {
      toast.error(`Revert failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const onApplyConfirm = async () => {
    try {
      const res = await apply.mutateAsync(undefined);
      setApplyResult(res);
      if (res.apply_mode === "dry_run") {
        toast.success(`Dry-run: ${res.plan.length} change(s) planned, nothing sent to Jira`);
      } else {
        toast.success(`Applied ${res.applied.length} change(s) to live Jira`);
      }
      if (res.skipped.length) toast.warning(`${res.skipped.length} skipped (not validated)`);
      refetch();
    } catch (e) {
      toast.error(`Apply failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const stagedRows = useMemo(() => rows.filter((r) => r._stage_status && r._stage_status !== "applied"), [rows]);
  const validatedCount = stagedRows.filter((r) => r._stage_status === "validated").length;

  if (isLoading) return <Skeleton className="h-64 w-full rounded-lg" />;
  if (isError)
    return (
      <div className="rounded-lg border border-destructive/20 bg-destructive/5 p-6 text-center">
        <AlertCircle className="mx-auto mb-2 h-8 w-8 text-destructive" />
        <p className="text-sm font-semibold text-destructive">Failed to load Jira issues</p>
        <p className="mt-1 text-xs text-muted-foreground">{error instanceof Error ? error.message : String(error)}</p>
        <Button variant="outline" size="sm" className="mt-3" onClick={() => refetch()}>Retry</Button>
      </div>
    );

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/30 p-2">
        <span className="text-xs text-muted-foreground">
          {dirtyCount > 0 ? `${dirtyCount} unsaved edit(s)` : `${stagedRows.length} staged`}
        </span>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button size="sm" variant="default" onClick={onSave} disabled={dirtyCount === 0 || stage.isPending}>
            <Save className="mr-1.5 h-3.5 w-3.5" /> Save
          </Button>
          <Button size="sm" variant="outline" onClick={onValidate} disabled={stagedRows.length === 0 || validate.isPending}>
            <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" /> Validate
          </Button>
          <Button size="sm" variant="outline" onClick={onRevert} disabled={stagedRows.length === 0 || revert.isPending}>
            <Undo2 className="mr-1.5 h-3.5 w-3.5" /> Revert
          </Button>
          <Button
            size="sm"
            variant="default"
            onClick={() => { setApplyResult(null); setApplyOpen(true); }}
            disabled={validatedCount === 0}
            title={validatedCount === 0 ? "Validate staged edits first" : undefined}
          >
            <Rocket className="mr-1.5 h-3.5 w-3.5" /> Apply ({validatedCount})
          </Button>
        </div>
      </div>

      <div className="overflow-x-auto rounded border">
        <table className="w-full border-collapse text-left text-xs">
          <thead>
            <tr className="border-b bg-muted/50 font-semibold">
              <th className="p-2">Key</th>
              <th className="p-2">Summary</th>
              <th className="p-2">Status</th>
              <th className="p-2">Assignee</th>
              <th className="p-2">Priority</th>
              <th className="p-2 text-right">Pts</th>
              <th className="p-2">Due</th>
              <th className="p-2">Stage</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((row) => {
              const errs = row._validation?.errors ?? [];
              const errFor = (f: string) => errs.find((e) => e.field === f)?.message;
              const cellCls = (f: EditableField) =>
                `w-full bg-transparent rounded px-1 py-0.5 outline-none focus:ring-1 focus:ring-primary ${
                  isDirty(row.key, f) ? "ring-1 ring-amber-400 bg-amber-50 dark:bg-amber-950/30" : ""
                } ${errFor(f) ? "ring-1 ring-destructive" : ""}`;
              return (
                <tr key={row.key} className="align-top hover:bg-muted/30">
                  <td className="p-2 font-mono font-bold text-primary">{row.key}</td>
                  <td className="p-2 min-w-[200px]">
                    <input className={cellCls("summary")} value={shown(row, "summary")} onChange={(e) => setCell(row.key, "summary", e.target.value)} />
                    {errFor("summary") && <p className="text-[10px] text-destructive">{errFor("summary")}</p>}
                  </td>
                  <td className="p-2">
                    <select className={cellCls("status")} value={shown(row, "status")} onChange={(e) => setCell(row.key, "status", e.target.value)}>
                      {STATUS_OPTS.map((o) => <option key={o} value={o}>{o}</option>)}
                      {!STATUS_OPTS.includes(shown(row, "status")) && <option value={shown(row, "status")}>{shown(row, "status")}</option>}
                    </select>
                  </td>
                  <td className="p-2 min-w-[120px]">
                    <input className={cellCls("assignee")} value={shown(row, "assignee")} onChange={(e) => setCell(row.key, "assignee", e.target.value)} />
                    {errFor("assignee") && <p className="text-[10px] text-destructive">{errFor("assignee")}</p>}
                  </td>
                  <td className="p-2">
                    <select className={cellCls("priority")} value={shown(row, "priority")} onChange={(e) => setCell(row.key, "priority", e.target.value)}>
                      {PRIORITY_OPTS.map((o) => <option key={o} value={o}>{o}</option>)}
                      {!PRIORITY_OPTS.includes(shown(row, "priority")) && <option value={shown(row, "priority")}>{shown(row, "priority")}</option>}
                    </select>
                  </td>
                  <td className="p-2 text-right">
                    <input type="number" min={0} className={`${cellCls("story_points")} text-right`} value={shown(row, "story_points")} onChange={(e) => setCell(row.key, "story_points", e.target.value)} />
                    {errFor("story_points") && <p className="text-[10px] text-destructive">{errFor("story_points")}</p>}
                  </td>
                  <td className="p-2">
                    <input type="date" className={cellCls("duedate")} value={(shown(row, "duedate") || "").slice(0, 10)} onChange={(e) => setCell(row.key, "duedate", e.target.value)} />
                    {errFor("duedate") && <p className="text-[10px] text-destructive">{errFor("duedate")}</p>}
                  </td>
                  <td className="p-2">{stageBadge(row)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Apply confirm dialog — HIL review of staged diff */}
      <Dialog open={applyOpen} onOpenChange={setApplyOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-warning" />
              Review staged changes before applying
            </DialogTitle>
            <DialogDescription>
              {applyResult
                ? applyResult.note
                : "These validated changes will be applied. Review the diff below; nothing is sent until you confirm."}
            </DialogDescription>
          </DialogHeader>

          <div className="max-h-[40vh] overflow-y-auto rounded border bg-muted/30 p-3 text-xs">
            {(applyResult?.plan ?? stagedRows.filter((r) => r._stage_status === "validated").map((r) => ({
              tool: "jira_update_issue",
              issue_key: r.key,
              fields: r._staged ?? {},
            }))).map((p) => (
              <div key={p.issue_key} className="mb-2 border-b pb-2 last:border-0">
                <span className="font-mono font-bold text-primary">{p.issue_key}</span>
                <div className="mt-1 flex flex-wrap gap-1">
                  {Object.entries(p.fields).map(([f, v]) => (
                    <Badge key={f} variant="outline" className="font-mono text-[10px]">{f} → {String(v)}</Badge>
                  ))}
                </div>
              </div>
            ))}
            {applyResult && applyResult.skipped.length > 0 && (
              <p className="mt-2 text-destructive">Skipped: {applyResult.skipped.map((s) => `${s.issue_key} (${s.reason})`).join("; ")}</p>
            )}
          </div>

          <DialogFooter>
            {applyResult ? (
              <Button variant="outline" onClick={() => setApplyOpen(false)}>Close</Button>
            ) : (
              <>
                <Button variant="outline" onClick={() => setApplyOpen(false)}>Cancel</Button>
                <Button variant="default" onClick={onApplyConfirm} disabled={apply.isPending}>
                  <Rocket className="mr-1.5 h-3.5 w-3.5" />
                  Confirm Apply
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
