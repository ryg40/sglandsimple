import { Link } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { AttentionItem, AttentionReason } from "@/lib/types";

const REASON_LABEL: Record<AttentionReason, string> = {
  overdue: "Overdue",
  due_soon: "Due soon",
  prioritized: "Prioritized",
  high_severity: "High severity",
  blocked_pr: "Blocked PR",
  stalled: "Stalled",
};

// Map a reason to a Badge variant (theme tokens only).
const REASON_VARIANT: Record<AttentionReason, "destructive" | "warning" | "default"> = {
  overdue: "destructive",
  blocked_pr: "destructive",
  high_severity: "destructive",
  due_soon: "warning",
  prioritized: "warning",
  stalled: "default",
};

const KIND_LABEL: Record<AttentionItem["kind"], string> = {
  finding: "Finding",
  epic: "Epic",
  work_item: "Work item",
  pr: "PR",
};

function dueBadge(item: AttentionItem) {
  const d = item.days_until_due;
  if (d == null) return null;
  if (d < 0) return `${Math.abs(Math.round(d))}d overdue`;
  if (d === 0) return "due today";
  return `${Math.round(d)}d to due`;
}

export function AttentionPanel({
  items,
  loading,
  error,
  onRetry,
}: {
  items: AttentionItem[];
  loading?: boolean;
  error?: string;
  onRetry?: () => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <AlertTriangle className="size-4 text-[color:var(--warning)]" />
          Points of concern
        </CardTitle>
        <CardDescription>Prioritized, due-soon, overdue, and stalled items across the estate</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        {error ? (
          <div className="flex flex-col items-center gap-2 p-6 text-center text-sm text-destructive">
            <span>{error}</span>
            {onRetry && (
              <button className="text-xs text-primary hover:underline" onClick={onRetry}>
                Retry
              </button>
            )}
          </div>
        ) : loading ? (
          <div className="space-y-2 p-4">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="p-8 text-center text-sm text-muted-foreground">
            Nothing needs attention — all clear. ✅
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="px-4 py-2 font-medium">Item</th>
                  <th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 font-medium">Reason</th>
                  <th className="px-4 py-2 font-medium">Severity / Priority</th>
                  <th className="px-4 py-2 text-right font-medium">Due</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => {
                  const badge = dueBadge(it);
                  const overdue = (it.days_until_due ?? 0) < 0;
                  return (
                    <tr key={`${it.kind}-${it.id}`} className="border-b last:border-0 hover:bg-muted/40">
                      <td className="max-w-xs truncate px-4 py-2" title={it.title}>
                        <Link to={it.link} className="font-medium text-foreground hover:text-primary hover:underline">
                          {it.title}
                        </Link>
                      </td>
                      <td className="px-4 py-2 text-muted-foreground">{KIND_LABEL[it.kind]}</td>
                      <td className="px-4 py-2">
                        <Badge variant={REASON_VARIANT[it.reason]} className="font-medium">
                          {REASON_LABEL[it.reason]}
                        </Badge>
                      </td>
                      <td className="px-4 py-2 capitalize text-muted-foreground">
                        {it.severity ?? it.priority ?? "—"}
                      </td>
                      <td className={`px-4 py-2 text-right tnum ${overdue ? "text-destructive" : "text-muted-foreground"}`}>
                        {badge ?? "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
