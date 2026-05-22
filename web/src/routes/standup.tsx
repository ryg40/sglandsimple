import { useState } from "react";
import { Bot, ChevronDown, ChevronUp, ShieldCheck, UsersRound } from "lucide-react";
import { JiraEditableGrid } from "@/components/jira-editable-grid";
import { StandupChat } from "@/components/standup-chat";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const PROPOSAL_PREVIEWS = [
  {
    title: "Capture blocker follow-up",
    target: "Jira proposal",
    status: "dry-run preview",
    detail: "Turn selected standup notes into a task or bug after the Standup agent/backend lands.",
  },
  {
    title: "Associate service context",
    target: "Link proposal",
    status: "pending agent",
    detail: "Parse Jira, Confluence, GitHub, ServiceNow, Archer, and Snowflake links from chat messages.",
  },
];

export default function Standup() {
  const [configOpen, setConfigOpen] = useState(false);
  const [linkCount, setLinkCount] = useState(0);

  return (
    <div className="flex min-h-full flex-col gap-4 p-5">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight">Standup Jira cockpit</h1>
            <Badge variant="warning">Stage 20 shell</Badge>
            <Badge variant="outline">Jira writes stay gated</Badge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Screen-share-first workspace with the editable Jira grid as the centerpiece, live-or-local chat capture,
            proposal previews, and configuration traces while the backend websocket/agent slices mature.
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-lg border bg-card px-3 py-2 text-xs text-muted-foreground">
          <UsersRound className="size-4 text-primary" />
          <span>Session: daily-standup</span>
          <Badge variant="success" className="text-[10px]">admin preview</Badge>
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
              <CardContent className="grid gap-3 pt-0 text-sm sm:grid-cols-3">
                <div className="rounded-lg border bg-muted/20 p-3">
                  <div className="font-medium">Write guard</div>
                  <p className="mt-1 text-xs text-muted-foreground">Apply is disabled on this page until Standup approval/RBAC lands; Hub retains the Stage 16 path.</p>
                </div>
                <div className="rounded-lg border bg-muted/20 p-3">
                  <div className="font-medium">Tool calls</div>
                  <p className="mt-1 text-xs text-muted-foreground">Future websocket events can stream agent/tool trace summaries here.</p>
                </div>
                <div className="rounded-lg border bg-muted/20 p-3">
                  <div className="font-medium">Associations</div>
                  <p className="mt-1 text-xs text-muted-foreground">{linkCount} local link/key candidate(s) captured in standup notes.</p>
                </div>
              </CardContent>
            )}
          </Card>
        </section>

        <aside className="flex min-h-0 flex-col gap-4">
          <StandupChat sessionId="daily-standup" onAssociationCountChange={setLinkCount} />

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Bot className="size-4 text-primary" />
                Agent suggestions
              </CardTitle>
              <CardDescription>Read-only preview tray for future dry-run proposals.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 pt-0">
              {PROPOSAL_PREVIEWS.map((proposal) => (
                <div key={proposal.title} className="rounded-lg border bg-muted/20 p-3 text-sm">
                  <div className="flex items-start justify-between gap-2">
                    <div className="font-medium">{proposal.title}</div>
                    <Badge variant="warning" className="text-[10px]">{proposal.status}</Badge>
                  </div>
                  <div className="mt-1 text-xs font-medium text-primary">{proposal.target}</div>
                  <p className="mt-1 text-xs text-muted-foreground">{proposal.detail}</p>
                </div>
              ))}
              <div className="flex items-center gap-2 rounded-lg border border-success/30 bg-success/10 p-3 text-xs text-success">
                <ShieldCheck className="size-4" />
                External writes require existing Jira gates and future approval policy.
              </div>
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}
