import { useMemo, useState } from "react";
import { Bot, CheckCircle2, Loader2, PauseCircle, Play, Square, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  useAgentArtifacts,
  useAgentProfiles,
  useAgentRun,
  useCancelAgentRun,
  useResumeAgentRun,
  useStartAgentRun,
} from "@/lib/queries";
import { cn } from "@/lib/utils";

function StatusIcon({ status }: { status?: string }) {
  if (status === "running") return <Loader2 className="size-4 animate-spin text-amber-500" />;
  if (status === "waiting_approval") return <PauseCircle className="size-4 text-amber-500" />;
  if (status === "completed") return <CheckCircle2 className="size-4 text-emerald-500" />;
  if (status === "error" || status === "rejected" || status === "cancelled") return <XCircle className="size-4 text-destructive" />;
  return <Bot className="size-4 text-muted-foreground" />;
}

export default function Agents() {
  const profiles = useAgentProfiles();
  const [agent, setAgent] = useState<string>("");
  const [goal, setGoal] = useState("Summarize what this agent can do and use only read-only/dry-run paths.");
  const [runId, setRunId] = useState<string | null>(null);
  const start = useStartAgentRun();
  const run = useAgentRun(runId);
  const artifacts = useAgentArtifacts(runId);
  const resume = useResumeAgentRun();
  const cancel = useCancelAgentRun();

  const roster = profiles.data?.profiles ?? [];
  const selected = useMemo(() => roster.find((p) => p.name === agent), [roster, agent]);

  async function startRun() {
    const rec = await start.mutateAsync({ goal, agent: agent || null, mode: "dry_run" });
    setRunId(rec.run_id);
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 p-6">
      <div className="rounded-3xl border bg-gradient-to-r from-slate-950 via-slate-900 to-teal-950 p-6 text-white shadow-lg">
        <div className="flex items-center gap-3">
          <div className="rounded-2xl bg-amber-400/20 p-3 text-amber-200"><Bot className="size-6" /></div>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Deep Agent Operations</h1>
            <p className="text-sm text-slate-300">Stage 21 runtime: profile roster, pollable runs, HITL approval preview, and cancellation.</p>
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
        <Card>
          <CardHeader><CardTitle>Agent roster</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {profiles.isLoading && <p className="text-sm text-muted-foreground">Loading profiles…</p>}
            {profiles.isError && <p className="text-sm text-destructive">Unable to load profiles.</p>}
            {roster.map((p) => (
              <button
                key={p.name}
                onClick={() => setAgent(p.name)}
                className={cn(
                  "w-full rounded-xl border p-3 text-left text-sm transition hover:bg-muted",
                  agent === p.name && "border-amber-500 bg-amber-500/10"
                )}
              >
                <div className="font-medium">{p.name}</div>
                <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">{p.description}</div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {p.graph && <span className="rounded-full bg-teal-500/10 px-2 py-0.5 text-xs text-teal-700">graph:{p.graph}</span>}
                  {p.write_tools.length > 0 && <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-xs text-amber-700">HITL writes</span>}
                  <span className="rounded-full bg-muted px-2 py-0.5 text-xs">{p.allowed_tools.length} tools</span>
                </div>
              </button>
            ))}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Start dry-run</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <Input value={agent} onChange={(e) => setAgent(e.target.value)} placeholder="agent name, or blank for orchestrator routing" />
              {selected && <p className="text-xs text-muted-foreground">Selected: {selected.description}</p>}
              <textarea
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                rows={4}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <Button onClick={startRun} disabled={!goal.trim() || start.isPending}>
                {start.isPending ? <Loader2 className="mr-2 size-4 animate-spin" /> : <Play className="mr-2 size-4" />} Start run
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Run status</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center gap-2 text-sm">
                <StatusIcon status={run.data?.status} />
                <span className="font-mono">{runId ?? "No run selected"}</span>
                {run.data?.status && <span className="rounded-full bg-muted px-2 py-0.5 text-xs">{run.data.status}</span>}
              </div>
              {run.data?.error && <pre className="whitespace-pre-wrap rounded-lg bg-destructive/10 p-3 text-xs text-destructive">{run.data.error}</pre>}
              {run.data?.result_text && <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-muted p-3 text-sm">{run.data.result_text}</pre>}
              {run.data?.approval && (
                <div className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
                  <div className="font-medium">Approval requested: {run.data.approval.tool || "tool"}</div>
                  <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(run.data.approval.payload ?? run.data.approval, null, 2)}</pre>
                  <div className="mt-3 flex gap-2">
                    <Button size="sm" onClick={() => resume.mutate({ run_id: run.data!.run_id, decision: "approve" })}>Approve</Button>
                    <Button size="sm" variant="outline" onClick={() => resume.mutate({ run_id: run.data!.run_id, decision: "reject" })}>Reject</Button>
                  </div>
                </div>
              )}
              {runId && run.data?.status === "running" && (
                <Button variant="outline" onClick={() => cancel.mutate(runId)}><Square className="mr-2 size-4" />Cancel</Button>
              )}
              {artifacts.data?.artifacts && artifacts.data.artifacts.length > 0 && (
                <div>
                  <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">Artifacts</div>
                  <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-muted p-3 text-xs">
                    {JSON.stringify(artifacts.data.artifacts, null, 2)}
                  </pre>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
