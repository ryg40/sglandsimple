import { Inbox, PlayCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { StandupIncomingTicket } from "@/lib/types";

function chips(values: string[], empty = "none") {
  if (!values.length) return <span className="text-xs text-muted-foreground">{empty}</span>;
  return <div className="flex flex-wrap gap-1">{values.slice(0, 5).map((value) => <Badge key={value} variant="outline" className="text-[10px]">{value}</Badge>)}{values.length > 5 && <Badge variant="outline" className="text-[10px]">+{values.length - 5}</Badge>}</div>;
}

function confidenceVariant(confidence: number) {
  if (confidence >= 0.7) return "success" as const;
  if (confidence >= 0.45) return "warning" as const;
  return "outline" as const;
}

function sourceVariant(status: string) {
  if (["available", "healthy"].includes(status)) return "success" as const;
  if (["degraded", "error"].includes(status)) return "destructive" as const;
  return "outline" as const;
}

export function StandupIncoming({ tickets, canSend = false, onKickoff }: { tickets: StandupIncomingTicket[]; canSend?: boolean; onKickoff?: (ticket: StandupIncomingTicket) => void }) {
  if (!tickets.length) return null;
  return (
    <Card className="border-primary/30 bg-primary/5">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base"><Inbox className="size-4 text-primary" />Incoming tickets</CardTitle>
            <CardDescription>Unassigned Jira intake with workflow match and connector-hub enrichment. Read-only until a dry-run proposal reaches approvals.</CardDescription>
          </div>
          <Badge variant="warning" className="shrink-0">{tickets.length} intake</Badge>
        </div>
      </CardHeader>
      <CardContent className="grid gap-3 pt-0">
        {tickets.map((ticket) => {
          const match = ticket.workflow_match;
          const enrichment = ticket.enrichment ?? {};
          const sourceEntries = Object.entries(enrichment).filter(([key, value]) => key !== "connector_health" && value && typeof value === "object").slice(0, 4) as Array<[string, { status?: string; summary?: string }]>;
          const identity = ticket.identity_enrichment?.directory;
          const githubRepos = ticket.identity_enrichment?.github_history?.repos ?? [];
          return (
            <div key={ticket.key} className="rounded-lg border bg-card p-3 text-sm">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <a className="font-mono text-xs font-semibold text-primary underline-offset-2 hover:underline" href={`https://enterprise.atlassian.net/browse/${encodeURIComponent(ticket.key)}`} target="_blank" rel="noreferrer">{ticket.key}</a>
                    <Badge variant="outline" className="text-[10px]">{ticket.status || "new"}</Badge>
                    <Badge variant={confidenceVariant(match.confidence)} className="text-[10px]">{Math.round((match.confidence || 0) * 100)}% match</Badge>
                  </div>
                  <div className="mt-1 font-medium">{ticket.summary}</div>
                  <div className="mt-1 text-xs text-muted-foreground">Reporter: {ticket.reporter || "unknown"} · Created: {ticket.created || "unknown"}</div>
                </div>
                <Button size="sm" variant="outline" disabled={!canSend || !match.matched} onClick={() => onKickoff?.(ticket)} title={!match.matched ? "No workflow match to kick off" : "Send dry-run kickoff context to the approvals workflow"}>
                  <PlayCircle className="size-4" /> Dry-run
                </Button>
              </div>

              {identity && (
                <div className="mt-3 rounded-md border bg-muted/20 p-2 text-xs">
                  <div className="mb-1 font-medium">Who & team context</div>
                  <div className="flex flex-wrap gap-2 text-muted-foreground">
                    <span className="font-medium text-foreground">{identity.display_name || identity.email}</span>
                    {identity.title && <span>{identity.title}</span>}
                    {identity.manager?.display_name && <span>mgr: {identity.manager.display_name}</span>}
                    {chips(identity.teams || [])}
                  </div>
                  {githubRepos.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {githubRepos.slice(0, 4).map((repo) => (
                        <Badge key={repo.repo} variant="outline" className="text-[10px]" title={repo.application_mapping?.rationale}>
                          {repo.repo} → {repo.application_mapping?.application || "unknown app"} / {repo.application_mapping?.environment || "unknown env"}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              )}

              <div className="mt-3 grid gap-3 lg:grid-cols-3">
                <div className="rounded-md border bg-muted/20 p-2">
                  <div className="mb-1 text-xs font-medium">Entities</div>
                  <div className="space-y-1.5 text-xs">
                    <div><span className="text-muted-foreground">AWS:</span> {chips([...ticket.entities.aws_accounts, ...ticket.entities.aws_regions])}</div>
                    <div><span className="text-muted-foreground">RDS:</span> {chips(ticket.entities.rds_instances)}</div>
                    <div><span className="text-muted-foreground">Team/user:</span> {chips([...ticket.entities.app_team_ids, ...ticket.entities.users, ...ticket.entities.emails])}</div>
                    <div><span className="text-muted-foreground">DL:</span> {chips(ticket.entities.distribution_lists)}</div>
                  </div>
                </div>
                <div className="rounded-md border bg-muted/20 p-2">
                  <div className="mb-1 text-xs font-medium">Workflow match</div>
                  <div className="text-xs">
                    <div className="font-medium">{match.workflow || "No match"}</div>
                    <p className="mt-1 text-muted-foreground">{match.rationale}</p>
                  </div>
                </div>
                <div className="rounded-md border bg-muted/20 p-2">
                  <div className="mb-1 text-xs font-medium">Connector hub</div>
                  <div className="flex flex-wrap gap-1">
                    {sourceEntries.map(([name, source]) => <Badge key={name} variant={sourceVariant(String(source.status || "no_data"))} className="text-[10px]">{name}: {String(source.status || "no_data")}</Badge>)}
                  </div>
                  <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">{sourceEntries.map(([, source]) => source.summary).filter(Boolean).join(" · ") || "No connector details returned."}</p>
                </div>
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
