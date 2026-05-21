import { useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Users, Ticket, FileText, Database } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { StatCard } from "@/components/stat-card";
import { ActivityTable } from "@/components/activity-table";
import { useCollections, useRecentAudit } from "@/lib/queries";

const ICONS: Record<string, typeof Users> = {
  employees: Users,
  tickets: Ticket,
  documents: FileText,
};

export default function Overview() {
  const cols = useCollections();
  const audit = useRecentAudit(40);

  const trend = useMemo(() => {
    // Aggregate audit rows into a per-day activity count for the trend chart.
    const byDay = new Map<string, number>();
    for (const r of audit.data?.rows ?? []) {
      const day = (r.ts ?? "").slice(0, 10) || "—";
      byDay.set(day, (byDay.get(day) ?? 0) + 1);
    }
    const points = [...byDay.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    return points.map(([day, count]) => ({ day: day.slice(5), count }));
  }, [audit.data]);

  return (
    <div className="mx-auto max-w-7xl space-y-5 p-5">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {(cols.data?.collections ?? (cols.isLoading ? [null, null, null] : [])).map((c, i) =>
          c ? (
            <StatCard
              key={c.name}
              label={c.name}
              value={c.count.toLocaleString()}
              icon={ICONS[c.name] ?? Database}
            />
          ) : (
            <StatCard key={i} label="…" value="" loading icon={Database} />
          )
        )}
        <StatCard
          label="Write events"
          value={(audit.data?.rows.length ?? 0).toLocaleString()}
          delta="audit log"
          icon={Database}
          loading={audit.isLoading}
        />
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Activity trend</CardTitle>
            <CardDescription>Write events per day (from the audit log)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-56 w-full">
              {trend.length === 0 ? (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                  No activity to chart yet.
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={trend} margin={{ left: -20, right: 8, top: 8 }}>
                    <defs>
                      <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.35} />
                        <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="day" stroke="var(--muted-foreground)" fontSize={11} tickLine={false} axisLine={false} />
                    <YAxis stroke="var(--muted-foreground)" fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} />
                    <Tooltip
                      contentStyle={{
                        background: "var(--popover)",
                        border: "1px solid var(--border)",
                        borderRadius: 8,
                        fontSize: 12,
                        color: "var(--popover-foreground)",
                      }}
                    />
                    <Area type="monotone" dataKey="count" stroke="var(--chart-1)" strokeWidth={2} fill="url(#fill)" />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Collections</CardTitle>
            <CardDescription>Document counts</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {(cols.data?.collections ?? []).map((c) => {
              const max = Math.max(1, ...(cols.data?.collections ?? []).map((x) => x.count));
              return (
                <div key={c.name}>
                  <div className="mb-1 flex justify-between text-sm">
                    <span className="capitalize">{c.name}</span>
                    <span className="tnum text-muted-foreground">{c.count}</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div className="h-full rounded-full bg-[var(--chart-1)]" style={{ width: `${(c.count / max) * 100}%` }} />
                  </div>
                </div>
              );
            })}
            {cols.isError && <p className="text-sm text-destructive">MCP unreachable.</p>}
          </CardContent>
        </Card>
      </div>

      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle>Recent activity</CardTitle>
          <CardDescription>Latest writes across Sheet and Wrangler</CardDescription>
        </CardHeader>
        <ActivityTable
          rows={audit.data?.rows ?? []}
          loading={audit.isLoading}
          error={audit.isError ? (audit.error as Error)?.message : undefined}
          onRetry={() => audit.refetch()}
        />
      </Card>
    </div>
  );
}
