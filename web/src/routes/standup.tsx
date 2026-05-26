import { useMemo, useState, type ReactNode } from "react";
import { Activity, BookOpenText, Bot, Check, ChevronDown, ChevronUp, FileText, Layers3, Link2, Radio, ShieldCheck, Sparkles, UsersRound, X } from "lucide-react";
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
import { Markdown } from "@/components/markdown";
import { useConnectors, useStandupEpics, useStandupTemplates } from "@/lib/queries";
import type { StandupEpic, StandupTemplate } from "@/lib/types";

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

function payloadText(payload: Record<string, unknown> | undefined) {
  return JSON.stringify(payload ?? {}, null, 2);
}

function parsePayloadDraft(text: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(text || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null;
  } catch {
    return null;
  }
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

function chipList(values: string[], empty = "—") {
  if (!values.length) return <span className="text-xs text-muted-foreground">{empty}</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {values.slice(0, 6).map((value) => (
        <Badge key={value} variant="outline" className="text-[10px]">{value}</Badge>
      ))}
      {values.length > 6 && <Badge variant="outline" className="text-[10px]">+{values.length - 6}</Badge>}
    </div>
  );
}

function jiraUrl(key: string) {
  return `https://enterprise.atlassian.net/browse/${encodeURIComponent(key)}`;
}

function statusVariant(value: string) {
  const v = value.toLowerCase();
  if (["done", "closed", "resolved", "complete", "completed"].includes(v)) return "success" as const;
  if (["blocked", "at_risk", "critical"].includes(v)) return "destructive" as const;
  if (["in_progress", "active", "todo"].includes(v)) return "warning" as const;
  return "outline" as const;
}

function priorityVariant(value: string) {
  const v = value.toLowerCase();
  if (["critical", "highest", "p0", "high", "p1"].includes(v)) return "destructive" as const;
  if (["medium", "p2"].includes(v)) return "warning" as const;
  if (["low", "p3"].includes(v)) return "outline" as const;
  return "outline" as const;
}

function StandupEpicsCard({ selectedEpicKey, onSelectEpic }: { selectedEpicKey: string | null; onSelectEpic: (epic: StandupEpic) => void }) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const epicsQuery = useStandupEpics();
  const epics = epicsQuery.data?.epics ?? [];
  const subtitle = epicsQuery.isLoading ? "loading epics" : `${epics.length} ${epicsQuery.data?.active_only === false ? "epics" : "active epics"}`;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Layers3 className="size-4 text-primary" />
              Epics
            </CardTitle>
            <CardDescription>{selectedEpicKey ? `Selected context: ${selectedEpicKey}` : subtitle}</CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={() => setOpen((value) => !value)}>
            {open ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
            {open ? "Hide" : "Show"}
          </Button>
        </div>
      </CardHeader>
      {open && (
        <CardContent className="space-y-2 pt-0">
          {epicsQuery.isError ? (
            <p className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">Unable to load active epics.</p>
          ) : epics.length === 0 ? (
            <p className="rounded-lg border border-dashed bg-muted/20 p-3 text-xs text-muted-foreground">No active epics returned by the standup epics proxy.</p>
          ) : (
            epics.map((epic) => {
              const isExpanded = expanded === epic.epic_key;
              const selected = selectedEpicKey === epic.epic_key;
              return (
                <div key={epic.epic_key} className={`rounded-lg border p-3 text-sm ${selected ? "border-primary/60 bg-primary/5" : "bg-muted/20"}`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <a href={jiraUrl(epic.jira_key)} target="_blank" rel="noreferrer" className="font-mono text-xs font-semibold text-primary underline-offset-2 hover:underline">
                          {epic.epic_key}
                        </a>
                        {epic.program_area && <Badge variant="outline" className="text-[10px]">{epic.program_area}</Badge>}
                        <Badge variant={statusVariant(epic.status)} className="text-[10px] capitalize">{epic.status}</Badge>
                        {epic.priority && <Badge variant={priorityVariant(epic.priority)} className="text-[10px] capitalize">{epic.priority}</Badge>}
                      </div>
                      <div className="mt-1 line-clamp-2 font-medium">{epic.title}</div>
                    </div>
                    <div className="flex shrink-0 gap-1">
                      <Button size="sm" variant={selected ? "default" : "outline"} onClick={() => onSelectEpic(epic)}>
                        Select
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setExpanded(isExpanded ? null : epic.epic_key)}>
                        {isExpanded ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
                      </Button>
                    </div>
                  </div>
                  <div className="mt-2 grid gap-2 text-xs">
                    <div>
                      <span className="text-muted-foreground">Classifiers: </span>
                      {chipList([...epic.tags, ...epic.regulation_refs, ...epic.db_platform_combos])}
                    </div>
                    <div className="flex flex-wrap gap-2 text-muted-foreground">
                      <span>{epic.ticket_refs.length} ticket refs</span>
                      <span>·</span>
                      <span>{epic.finding_ids.length} finding links</span>
                    </div>
                  </div>
                  {isExpanded && (
                    <div className="mt-3 space-y-2 rounded-md border bg-card p-2 text-xs">
                      <div>
                        <div className="mb-1 font-medium">Ticket refs</div>
                        {chipList(epic.ticket_refs)}
                      </div>
                      <div>
                        <div className="mb-1 font-medium">Finding IDs</div>
                        {chipList(epic.finding_ids)}
                      </div>
                      <div>
                        <div className="mb-1 font-medium">Database/platform combos</div>
                        {chipList(epic.db_platform_combos)}
                      </div>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </CardContent>
      )}
    </Card>
  );
}

const TEMPLATE_FIELD_SPECS: Array<{ key: keyof StandupEpic; label: string; render?: (epic: StandupEpic) => ReactNode }> = [
  { key: "epic_key", label: "Epic" },
  { key: "program_area", label: "Area" },
  { key: "priority", label: "Priority" },
  { key: "status", label: "Status" },
  { key: "regulation_refs", label: "Reg refs", render: (epic) => chipList(epic.regulation_refs) },
  { key: "db_platform_combos", label: "DB/platform", render: (epic) => chipList(epic.db_platform_combos) },
  { key: "tags", label: "Labels", render: (epic) => chipList(epic.tags) },
];

function FieldCell({ epic, spec }: { epic: StandupEpic; spec: (typeof TEMPLATE_FIELD_SPECS)[number] }) {
  if (spec.render) return <>{spec.render(epic)}</>;
  const value = epic[spec.key];
  return <span>{Array.isArray(value) ? value.join(", ") : String(value ?? "—")}</span>;
}

function StandupTemplatesCard() {
  const [open, setOpen] = useState(false);
  const epicsQuery = useStandupEpics();
  const templatesQuery = useStandupTemplates();
  const templates = templatesQuery.data?.templates ?? [];
  const [selectedName, setSelectedName] = useState<string>("");
  const selectedTemplate: StandupTemplate | undefined = templates.find((template) => template.name === selectedName) ?? templates[0];
  const selectedValue = selectedTemplate?.name ?? "";
  const epics = epicsQuery.data?.epics ?? [];

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-sm">
              <BookOpenText className="size-4 text-primary" />
              Templates
            </CardTitle>
            <CardDescription>{templates.length ? `${templates.length} shared prompts · fields table read-only` : "Backend-owned prompts + epic field specs"}</CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={() => setOpen((value) => !value)}>
            {open ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
            {open ? "Hide" : "Show"}
          </Button>
        </div>
      </CardHeader>
      {open && (
        <CardContent className="space-y-4 pt-0">
          <div className="rounded-lg border bg-muted/20 p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div>
                <div className="text-xs font-medium">Per-epic customized fields</div>
                <p className="text-[11px] text-muted-foreground">Read-only projection; cells are rendered through a field spec for future inline editing.</p>
              </div>
              <Badge variant="outline" className="text-[10px]">Editing coming soon</Badge>
            </div>
            <div className="max-h-56 overflow-auto rounded-md border bg-card">
              <table className="w-full min-w-[42rem] text-left text-xs">
                <thead className="sticky top-0 bg-muted text-muted-foreground">
                  <tr>
                    {TEMPLATE_FIELD_SPECS.map((spec) => <th key={spec.key} className="px-2 py-1.5 font-medium">{spec.label}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {epics.length === 0 ? (
                    <tr><td className="px-2 py-3 text-muted-foreground" colSpan={TEMPLATE_FIELD_SPECS.length}>No active epics loaded.</td></tr>
                  ) : epics.map((epic) => (
                    <tr key={epic.epic_key} className="border-t align-top">
                      {TEMPLATE_FIELD_SPECS.map((spec) => (
                        <td key={spec.key} className="px-2 py-2"><FieldCell epic={epic} spec={spec} /></td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="rounded-lg border bg-muted/20 p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-xs font-medium">
                <FileText className="size-4 text-primary" />
                Prompt/template library
              </div>
              <Badge variant="outline" className="text-[10px]">shared source</Badge>
            </div>
            {templatesQuery.isError ? (
              <p className="text-xs text-destructive">Template library is unavailable.</p>
            ) : templates.length === 0 ? (
              <p className="text-xs text-muted-foreground">No templates returned, or `STANDUP_TEMPLATES_ENABLED=false`.</p>
            ) : (
              <div className="space-y-3">
                <select
                  className="w-full rounded-md border bg-background px-2 py-1.5 text-xs"
                  value={selectedValue}
                  onChange={(event) => setSelectedName(event.target.value)}
                >
                  {templates.map((template) => (
                    <option key={template.name} value={template.name}>{template.name} · {template.kind}</option>
                  ))}
                </select>
                {selectedTemplate?.description && <p className="text-xs text-muted-foreground">{selectedTemplate.description}</p>}
                <div className="max-h-72 overflow-auto rounded-md border bg-card p-3">
                  <Markdown>{selectedTemplate?.body_md ?? ""}</Markdown>
                </div>
              </div>
            )}
          </div>
        </CardContent>
      )}
    </Card>
  );
}

export default function Standup() {
  const [configOpen, setConfigOpen] = useState(false);
  const [chatExpanded, setChatExpanded] = useState(false);
  const [linkCount, setLinkCount] = useState(0);
  const [associations, setAssociations] = useState<StandupAssociation[]>([]);
  const [trace, setTrace] = useState<StandupTraceState | null>(null);
  const [controls, setControls] = useState<StandupControls | null>(null);
  const [selectedEpic, setSelectedEpic] = useState<StandupEpic | null>(null);
  const [payloadDrafts, setPayloadDrafts] = useState<Record<string, string>>({});
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

      <div
        className={`grid min-h-[calc(100vh-10rem)] gap-4 ${
          chatExpanded ? "grid-cols-1" : "xl:grid-cols-[minmax(0,1fr)_23rem]"
        }`}
      >
        <section className={`min-w-0 space-y-3 ${chatExpanded ? "order-2" : ""}`}>
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

          <StandupTemplatesCard />

          <div className="grid gap-4 lg:grid-cols-2">
            <StandupEpicsCard selectedEpicKey={selectedEpic?.epic_key ?? null} onSelectEpic={setSelectedEpic} />

          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Bot className="size-4 text-primary" />
                    Approvals viewport
                  </CardTitle>
                  <CardDescription>
                    {canApprove
                      ? "Edit staged proposal payloads, Save without applying, then Submit through production gates when enabled."
                      : "Read-only: Save/Submit requires the canApproveStandupActions capability or named approver grant."}
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
                  No staged changes yet. Capture standup notes, then run <span className="font-medium">Summarize</span> to
                  generate proposals for approver review.
                </div>
              ) : (
                proposals.map((proposal) => {
                  const status = String(proposal.status);
                  const decided = status !== "proposed";
                  const validation = validationLabel(proposal);
                  const draft = payloadDrafts[proposal.id] ?? payloadText(proposal.dry_run_payload);
                  const parsedDraft = parsePayloadDraft(draft);
                  return (
                    <div key={proposal.id} className="rounded-lg border bg-muted/20 p-3 text-sm">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 font-medium">{proposal.title ?? proposal.type ?? "Proposal"}</div>
                        <Badge variant={proposalStatusVariant(status)} className="text-[10px] capitalize">{status}</Badge>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-1 text-[10px]">
                        {proposal.target_service && <Badge variant="outline" className="capitalize">{proposal.target_service}</Badge>}
                        {proposal.dry_run && <Badge variant="outline">staged</Badge>}
                        {validation && <Badge variant="outline">{validation}</Badge>}
                      </div>
                      {proposal.rationale && <p className="mt-2 text-xs text-muted-foreground">{proposal.rationale}</p>}
                      <label className="mt-3 block text-[11px] font-medium text-muted-foreground">Editable staged payload</label>
                      <textarea
                        className="mt-1 min-h-32 w-full rounded-md border bg-background p-2 font-mono text-[11px]"
                        value={draft}
                        disabled={!canApprove || decided}
                        onChange={(event) => setPayloadDrafts((current) => ({ ...current, [proposal.id]: event.target.value }))}
                      />
                      {!parsedDraft && <p className="mt-1 text-[10px] text-destructive">Payload must be a valid JSON object before Save/Submit.</p>}
                      {proposal.approval?.actor && (
                        <p className="mt-1 text-[10px] text-muted-foreground">
                          {status} by {proposal.approval.actor}
                          {proposal.approval.applied === false ? " · not applied" : " · applied"}
                        </p>
                      )}
                      <div className="mt-2 flex flex-wrap gap-2">
                        <DisabledWithTooltip
                          enabled={canApprove && !decided && Boolean(controls?.canSend) && Boolean(parsedDraft)}
                          message={!canApprove ? "Requires approver rights" : !controls?.canSend ? "Live websocket not connected" : !parsedDraft ? "Fix JSON first" : "Already decided"}
                        >
                          <Button size="sm" variant="outline" onClick={() => parsedDraft && controls?.edit(proposal.id, parsedDraft)}>
                            <Check className="size-3.5" />
                            Save
                          </Button>
                        </DisabledWithTooltip>
                        <DisabledWithTooltip
                          enabled={canApprove && !decided && Boolean(controls?.canSend) && Boolean(parsedDraft)}
                          message={!canApprove ? "Requires approver rights" : !controls?.canSend ? "Live websocket not connected" : !parsedDraft ? "Fix JSON first" : "Already decided"}
                        >
                          <Button size="sm" variant="default" onClick={() => {
                            if (parsedDraft) controls?.edit(proposal.id, parsedDraft);
                            controls?.approve(proposal.id);
                          }}>
                            <ShieldCheck className="size-3.5" />
                            Submit
                          </Button>
                        </DisabledWithTooltip>
                        <DisabledWithTooltip
                          enabled={canApprove && !decided && Boolean(controls?.canSend)}
                          message={!canApprove ? "Requires approver rights" : !controls?.canSend ? "Live websocket not connected" : "Already decided"}
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
              <div className="flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/10 p-3 text-xs text-[color:var(--warning)]">
                <ShieldCheck className="size-4" />
                Submit revalidates staged Jira edits and only calls production apply when STANDUP_DRY_RUN_ONLY=false, WORKFLOW_WRITES_ENABLED=true, and JIRA_WRITES_ENABLED=true.
              </div>
            </CardContent>
          </Card>
          </div>
        </section>

        <aside className={`flex min-h-0 flex-col gap-4 ${chatExpanded ? "order-1" : ""}`}>
          <StandupChat
            sessionId="daily-standup"
            onAssociationCountChange={setLinkCount}
            onAssociationsChange={setAssociations}
            onTraceChange={setTrace}
            onControlsChange={setControls}
            expanded={chatExpanded}
            onToggleExpand={() => setChatExpanded((value) => !value)}
          />
        </aside>
      </div>
    </div>
  );
}
