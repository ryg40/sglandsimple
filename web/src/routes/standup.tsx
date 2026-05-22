import { useMemo, useState } from "react";
import { Activity, Bot, Check, ChevronDown, ChevronUp, Link2, Radio, ShieldCheck, Sparkles, UsersRound, X } from "lucide-react";
import { JiraEditableGrid } from "@/components/jira-editable-grid";
import {
  StandupChat,
  type StandupAssociation,
  type StandupControls,
  type StandupProposal,
  type StandupTraceState,
} from "@/components/standup-chat";
import { Capability, DisabledWithTooltip, useAuth } from "@/components/auth-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useConnectors } from "@/lib/queries";

const GATES = [
  { label: "Proposal approval", value: "RBAC gated", variant: "success" as const, detail: "Approve/Reject in the tray require the canApproveStandupActions capability (admin); others are read-only." },
  { label: "Standup dry-run", value: "enforced", variant: "success" as const, detail: "Approving a proposal validates staged Jira edits only; STANDUP_DRY_RUN_ONLY suppresses live apply." },
  { label: "Jira live writes", value: "external gate", variant: "warning" as const, detail: "Production writes still require Stage 16 validation/apply plus JIRA_WRITES_ENABLED outside Standup." },
];

function proposalStatusVariant(status: string) {
  if (status === "approved") return "success" as const;
  if (status === "rejected") return "destructive" as const;
  return "warning" as const;
}

function validationLabel(proposal: StandupProposal): string | null {
  const vs = proposal.validation_state;
  if (!vs || typeof vs !== "object") return null;
  const state = (vs as Record<string, unknown>).state;
  return typeof state === "string" ? state : null;
}

function connectorStatus(connector: any) {
  return String(connector?.health?.status ?? connector?.summary?.status ?? connector?.status ?? "unknown");
}

function connectorBadgeVariant(status: string) {
  if (status === "healthy" || status === "enabled") return "success";
  if (status === "error" || status === "degraded") return "destructive";
  if (status === "disabled" || status === "placeholder") return "outline";
  return "warning";
}

function associationLabel(kind: StandupAssociation["kind"]) {
  return {
    jira: "Jira",
    confluence: "Confluence",
    github: "GitHub",
    servicenow: "ServiceNow",
    archer: "Archer",
    snowflake: "Snowflake",
    mongodb: "MongoDB",
    mention: "Mention",
    url: "URL",
  }[kind];
}

export default function Standup() {
  const [configOpen, setConfigOpen] = useState(false);
  const [linkCount, setLinkCount] = useState(0);
  const [associations, setAssociations] = useState<StandupAssociation[]>([]);
  const [trace, setTrace] = useState<StandupTraceState | null>(null);
  const [controls, setControls] = useState<StandupControls | null>(null);
  const { hasCapability } = useAuth();
  const canApprove = hasCapability(Capability.CAN_APPROVE_STANDUP);
  const proposals = controls?.proposals ?? [];
  const connectors = useConnectors();
  const connectorRows = connectors.data?.connectors ?? [];
  const healthyConnectors = useMemo(
    () => connectorRows.filter((connector: any) => connectorStatus(connector) === "healthy").length,
    [connectorRows],
  );

  return (
    <div className="flex min-h-full flex-col gap-4 p-5">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight">Standup Jira cockpit</h1>
            <Badge variant="success">Stage 20 live slice</Badge>
            <Badge variant="outline">Jira writes stay gated</Badge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Screen-share-first workspace with the editable Jira grid as the centerpiece, live websocket chat capture,
            dry-run proposal persistence, and configuration traces for connector/tool context.
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-lg border bg-card px-3 py-2 text-xs text-muted-foreground">
          <UsersRound className="size-4 text-primary" />
          <span>Session: daily-standup</span>
          <Badge variant={canApprove ? "success" : "outline"} className="text-[10px]">
            {canApprove ? "approver" : "read-only"}
          </Badge>
        </div>
      </div>

      <div className="grid min-h-[calc(100vh-10rem)] gap-4 xl:grid-cols-[minmax(0,1fr)_23rem]">
        <section className="min-w-0 space-y-3">
          <Card className="overflow-hidden">
            <CardHeader className="border-b bg-muted/20 pb-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <CardTitle className="text-base">Jira Explorer</CardTitle>
                  <CardDescription>
                    Reuses the Stage 16 editable grid for sprint triage, staging, and validation; apply is disabled here until Standup approval/RBAC lands.
                  </CardDescription>
                </div>
                <div className="flex flex-wrap gap-2 text-xs">
                  <Badge variant="outline">bulk edit toolbar</Badge>
                  <Badge variant="outline">stage badges</Badge>
                  <Badge variant="outline">validation state</Badge>
                </div>
              </div>
            </CardHeader>
            <CardContent className="p-3">
              <JiraEditableGrid allowApply={false} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <CardTitle className="text-sm">Jira Configuration / tool trace</CardTitle>
                  <CardDescription>Collapsed by default so the grid stays dominant during standup.</CardDescription>
                </div>
                <Button variant="outline" size="sm" onClick={() => setConfigOpen((open) => !open)}>
                  {configOpen ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
                  {configOpen ? "Hide" : "Show"}
                </Button>
              </div>
            </CardHeader>
            {configOpen && (
              <CardContent className="grid gap-3 pt-0 text-sm xl:grid-cols-[1.1fr_1fr]">
                <div className="space-y-3">
                  <div className="rounded-lg border bg-muted/20 p-3">
                    <div className="mb-2 flex items-center gap-2 font-medium">
                      <ShieldCheck className="size-4 text-success" />
                      Dry-run / live-write gates
                    </div>
                    <div className="space-y-2">
                      {GATES.map((gate) => (
                        <div key={gate.label} className="rounded-md border bg-card p-2">
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-xs font-medium">{gate.label}</span>
                            <Badge variant={gate.variant} className="text-[10px]">{gate.value}</Badge>
                          </div>
                          <p className="mt-1 text-xs text-muted-foreground">{gate.detail}</p>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="rounded-lg border bg-muted/20 p-3">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 font-medium">
                        <Activity className="size-4 text-primary" />
                        Connector health
                      </div>
                      <Badge variant={connectors.isError ? "destructive" : "outline"} className="text-[10px]">
                        {connectors.isLoading ? "loading" : `${healthyConnectors}/${connectorRows.length} healthy`}
                      </Badge>
                    </div>
                    {connectors.isError ? (
                      <p className="text-xs text-destructive">Connector health is unavailable; Standup remains dry-run.</p>
                    ) : connectorRows.length === 0 ? (
                      <p className="text-xs text-muted-foreground">No connector health rows loaded yet.</p>
                    ) : (
                      <div className="grid gap-2 sm:grid-cols-2">
                        {connectorRows.slice(0, 8).map((connector: any) => {
                          const status = connectorStatus(connector);
                          return (
                            <div key={connector.name} className="flex items-center justify-between gap-2 rounded-md border bg-card px-2 py-1.5">
                              <span className="truncate text-xs font-medium capitalize">{connector.name}</span>
                              <Badge variant={connectorBadgeVariant(status)} className="text-[10px]">{status}</Badge>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="rounded-lg border bg-muted/20 p-3">
                    <div className="mb-2 flex items-center gap-2 font-medium">
                      <Radio className="size-4 text-primary" />
                      Websocket / agent / tool trace
                    </div>
                    <div className="grid gap-2 text-xs sm:grid-cols-2">
                      <div className="rounded-md border bg-card p-2">
                        <div className="text-muted-foreground">Websocket</div>
                        <div className="mt-1 font-medium">{trace?.connection.status ?? "not connected"}</div>
                        <p className="mt-1 text-muted-foreground">{trace?.connection.detail ?? "Waiting for chat panel telemetry."}</p>
                      </div>
                      <div className="rounded-md border bg-card p-2">
                        <div className="text-muted-foreground">Presence / messages</div>
                        <div className="mt-1 font-medium">{trace?.presence.count ?? 0} present · {trace?.messageCount ?? 0} messages</div>
                        <p className="mt-1 truncate text-muted-foreground">
                          {(trace?.presence.participants ?? [])
                            .slice(0, 4)
                            .map((participant) => participant.displayName)
                            .join(", ") || "No live participant snapshot yet."}
                        </p>
                      </div>
                      <div className="rounded-md border bg-card p-2">
                        <div className="text-muted-foreground">Agent</div>
                        <div className="mt-1 font-medium">standup_summarize</div>
                        <p className="mt-1 text-muted-foreground">Available through websocket agent.summarize; all results remain dry-run proposals.</p>
                      </div>
                      <div className="rounded-md border bg-card p-2">
                        <div className="text-muted-foreground">Tool calls</div>
                        <div className="mt-1 font-medium">read-only preview</div>
                        <p className="mt-1 text-muted-foreground">Jira edit proposals are staged/validated only; Standup never calls live apply.</p>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-lg border bg-muted/20 p-3">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 font-medium">
                        <Link2 className="size-4 text-primary" />
                        Cross-service associations
                      </div>
                      <Badge variant="outline" className="text-[10px]">{linkCount} detected</Badge>
                    </div>
                    {associations.length === 0 ? (
                      <p className="text-xs text-muted-foreground">Paste Jira keys, Confluence/GitHub/ServiceNow/Archer/Snowflake/Mongo links, or @mentions in chat to preview associations.</p>
                    ) : (
                      <div className="max-h-48 space-y-2 overflow-y-auto pr-1">
                        {associations.map((association) => (
                          <div key={`${association.kind}-${association.token}`} className="rounded-md border bg-card p-2 text-xs">
                            <div className="flex items-center justify-between gap-2">
                              <Badge variant="outline" className="text-[10px]">{associationLabel(association.kind)}</Badge>
                              <span className="text-muted-foreground">from {association.sourceAuthor}</span>
                            </div>
                            <div className="mt-1 break-all font-mono text-primary">{association.token}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </CardContent>
            )}
          </Card>
        </section>

        <aside className="flex min-h-0 flex-col gap-4">
          <StandupChat
            sessionId="daily-standup"
            onAssociationCountChange={setLinkCount}
            onAssociationsChange={setAssociations}
            onTraceChange={setTrace}
            onControlsChange={setControls}
          />

          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Bot className="size-4 text-primary" />
                    Approval tray
                  </CardTitle>
                  <CardDescription>
                    {canApprove
                      ? "Approve or reject dry-run proposals; approval validates staged Jira edits only."
                      : "Read-only: approving requires the canApproveStandupActions capability."}
                  </CardDescription>
                </div>
                <DisabledWithTooltip
                  enabled={Boolean(controls?.canSend) && !controls?.summarizing}
                  message={controls?.canSend ? "Summarizing…" : "Live websocket not connected"}
                >
                  <Button size="sm" variant="outline" onClick={() => controls?.summarize()}>
                    <Sparkles className="size-4" />
                    {controls?.summarizing ? "Summarizing…" : "Summarize"}
                  </Button>
                </DisabledWithTooltip>
              </div>
            </CardHeader>
            <CardContent className="space-y-3 pt-0">
              {proposals.length === 0 ? (
                <div className="rounded-lg border border-dashed bg-muted/20 p-4 text-center text-xs text-muted-foreground">
                  No proposals yet. Capture standup notes, then run <span className="font-medium">Summarize</span> to
                  generate dry-run follow-up proposals.
                </div>
              ) : (
                proposals.map((proposal) => {
                  const status = String(proposal.status);
                  const decided = status !== "proposed";
                  const validation = validationLabel(proposal);
                  return (
                    <div key={proposal.id} className="rounded-lg border bg-muted/20 p-3 text-sm">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 font-medium">{proposal.title ?? proposal.type ?? "Proposal"}</div>
                        <Badge variant={proposalStatusVariant(status)} className="text-[10px] capitalize">{status}</Badge>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-1 text-[10px]">
                        {proposal.target_service && <Badge variant="outline" className="capitalize">{proposal.target_service}</Badge>}
                        {proposal.dry_run && <Badge variant="outline">dry-run</Badge>}
                        {validation && <Badge variant="outline">{validation}</Badge>}
                      </div>
                      {proposal.rationale && (
                        <p className="mt-2 text-xs text-muted-foreground">{proposal.rationale}</p>
                      )}
                      {proposal.approval?.actor && (
                        <p className="mt-1 text-[10px] text-muted-foreground">
                          {status} by {proposal.approval.actor}
                          {proposal.approval.applied === false ? " · dry-run only (not applied)" : ""}
                        </p>
                      )}
                      <div className="mt-2 flex gap-2">
                        <DisabledWithTooltip
                          enabled={canApprove && !decided && Boolean(controls?.canSend)}
                          message={!canApprove ? "Requires canApproveStandupActions" : !controls?.canSend ? "Live websocket not connected" : "Already decided"}
                        >
                          <Button size="sm" variant="outline" onClick={() => controls?.approve(proposal.id)}>
                            <Check className="size-3.5" />
                            Approve
                          </Button>
                        </DisabledWithTooltip>
                        <DisabledWithTooltip
                          enabled={canApprove && !decided && Boolean(controls?.canSend)}
                          message={!canApprove ? "Requires canApproveStandupActions" : !controls?.canSend ? "Live websocket not connected" : "Already decided"}
                        >
                          <Button size="sm" variant="ghost" onClick={() => controls?.reject(proposal.id)}>
                            <X className="size-3.5" />
                            Reject
                          </Button>
                        </DisabledWithTooltip>
                      </div>
                    </div>
                  );
                })
              )}
              <div className="flex items-center gap-2 rounded-lg border border-success/30 bg-success/10 p-3 text-xs text-success">
                <ShieldCheck className="size-4" />
                Approvals are dry-run only; live external writes still require Stage 16 apply + JIRA_WRITES_ENABLED.
              </div>
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}
