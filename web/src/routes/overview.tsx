import { useMemo, lazy, Suspense } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, FileWarning, Layers, ListChecks, GitPullRequest, Plug } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { StatCard } from "@/components/stat-card";
import { MiniTable } from "@/components/mini-table";
import { AttentionPanel } from "@/components/attention-panel";
import { ActivityTable } from "@/components/activity-table";
import { useOverview, useRecentAudit } from "@/lib/queries";

const OverviewTrendChart = lazy(() => import("@/components/overview-trend-chart"));

const STATUS_DOT: Record<string, string> = {
  healthy: "bg-success",
  ok: "bg-success",
  degraded: "bg-[color:var(--warning)]",
  disabled: "bg-muted-foreground/40",
  error: "bg-destructive",
};

export default function Overview() {
  const overview = useOverview();
  const audit = useRecentAudit(40);

  const kpis = overview.data?.kpis;
  const connectors = overview.data?.connectors ?? [];
  const tables = overview.data?.tables;
  const ovError = overview.isError ? ((overview.error as Error)?.message ?? "MCP unreachable.") : undefined;

  const trend = useMemo(() => {
    const byDay = new Map<string, number>();
    for (const r of audit.data?.rows ?? []) {
      const day = (r.ts ?? "").slice(0, 10) || "—";
      byDay.set(day, (byDay.get(day) ?? 0) + 1);
    }
    const points = [...byDay.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    return points.map(([day, count]) => ({ day: day.slice(5), count }));
  }, [audit.data]);

  const loading = overview.isLoading && !overview.data;

  return (
    <div className="mx-auto max-w-7xl space-y-5 p-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Compliance command center</h1>
        <p className="text-sm text-muted-foreground">
          Live roll-up across every connected system — what needs attention first.
        </p>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
        <StatCard
          label="Open findings"
          value={kpis?.open_findings ?? ""}
          icon={FileWarning}
          loading={loading}
        />
        <StatCard label="Active epics" value={kpis?.active_epics ?? ""} icon={Layers} loading={loading} />
        <StatCard
          label="In-flight work"
          value={kpis?.inflight_work_items ?? ""}
          icon={ListChecks}
          loading={loading}
        />
        <StatCard label="Open PRs" value={kpis?.open_prs ?? ""} icon={GitPullRequest} loading={loading} />
        <StatCard
          label="Connectors"
          value={kpis ? `${kpis.connectors_healthy}/${kpis.connectors_total}` : ""}
          delta="healthy"
          icon={Plug}
          loading={loading}
        />
        <StatCard
          label="Needs attention"
          value={kpis?.attention ?? ""}
          delta={kpis?.attention ? "review now" : undefined}
          icon={AlertTriangle}
          loading={loading}
        />
      </div>

      {/* Attention panel — the headline region, full-width directly under the KPIs */}
      <AttentionPanel
        items={overview.data?.attention ?? []}
        loading={loading}
        error={ovError}
        onRetry={() => overview.refetch()}
      />

      {/* Connector health strip */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Connector health</CardTitle>
          <CardDescription>Status of every connected system — click to open in the Hub</CardDescription>
        </CardHeader>
        <CardContent>
          {ovError ? (
            <p className="text-sm text-destructive">{ovError}</p>
          ) : loading ? (
            <p className="text-sm text-muted-foreground">Loading connectors…</p>
          ) : connectors.length === 0 ? (
            <p className="text-sm text-muted-foreground">No connectors registered.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {connectors.map((c) => (
                <Link
                  key={c.name}
                  to={c.link}
                  className="flex items-center gap-2 rounded-full border bg-card px-3 py-1.5 text-sm transition-colors hover:bg-muted/60"
                  title={c.summary}
                >
                  <span className={`size-2 rounded-full ${STATUS_DOT[c.status] ?? "bg-muted-foreground/40"}`} />
                  <span className="font-medium capitalize">{c.name}</span>
                  {c.summary && (
                    <span className="hidden max-w-[14rem] truncate text-xs text-muted-foreground sm:inline">
                      {c.summary}
                    </span>
                  )}
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Multi-table region */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <MiniTable
          title="Recent findings"
          description="Latest audit findings"
          columns={[
            { key: "requirement", label: "Requirement" },
            { key: "severity", label: "Severity" },
            { key: "status", label: "Status" },
          ]}
          rows={tables?.findings ?? []}
          rowLink={(r) => `/hub?kind=finding&id=${r._id}`}
          viewAllHref="/hub"
          loading={loading}
          error={ovError}
          onRetry={() => overview.refetch()}
        />
        <MiniTable
          title="Recent epics"
          description="Active compliance epics"
          columns={[
            { key: "title", label: "Title" },
            { key: "priority", label: "Priority" },
            { key: "status", label: "Status" },
          ]}
          rows={tables?.epics ?? []}
          rowLink={(r) => `/hub?kind=epic&id=${r._id}`}
          viewAllHref="/hub"
          loading={loading}
          error={ovError}
          onRetry={() => overview.refetch()}
        />
        <MiniTable
          title="Work items"
          description="Implementation tasks in flight"
          columns={[
            { key: "title", label: "Title" },
            { key: "status", label: "Status" },
            { key: "priority", label: "Priority" },
          ]}
          rows={tables?.work_items ?? []}
          rowLink={(r) => `/hub?kind=work_item&id=${r._id}`}
          viewAllHref="/hub"
          loading={loading}
          error={ovError}
          onRetry={() => overview.refetch()}
        />
        <MiniTable
          title="Pull requests"
          description="Open and recent PRs"
          columns={[
            { key: "title", label: "Title" },
            { key: "state", label: "State" },
            { key: "pr_number", label: "#", align: "right" },
          ]}
          rows={tables?.pr_records ?? []}
          rowLink={(r) => `/hub?kind=pr&id=${r._id}`}
          viewAllHref="/hub"
          loading={loading}
          error={ovError}
          onRetry={() => overview.refetch()}
        />
      </div>

      {/* Activity trend — retained, demoted below the compliance regions */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">Activity trend</CardTitle>
            <CardDescription>Write events per day (from the audit log)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-56 w-full">
              {trend.length === 0 ? (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                  No activity to chart yet.
                </div>
              ) : (
                <Suspense fallback={<div className="h-full w-full animate-pulse rounded-md bg-muted/40" />}>
                  <OverviewTrendChart trend={trend} />
                </Suspense>
              )}
            </div>
          </CardContent>
        </Card>

        <Card className="overflow-hidden lg:col-span-1">
          <CardHeader>
            <CardTitle className="text-base">Recent activity</CardTitle>
            <CardDescription>Latest writes across the estate</CardDescription>
          </CardHeader>
          <ActivityTable
            rows={audit.data?.rows ?? []}
            loading={audit.isLoading}
            error={audit.isError ? (audit.error as Error)?.message : undefined}
            onRetry={() => audit.refetch()}
          />
        </Card>
      </div>
    </div>
  );
}
