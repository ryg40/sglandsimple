import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { relativeTime } from "@/lib/utils";
import type { AuditRow } from "@/lib/types";

function actionVariant(action: string): "success" | "warning" | "destructive" | "default" {
  if (action === "insertOne") return "success";
  if (action === "deleteOne") return "destructive";
  if (action === "updateOne" || action === "replaceOne") return "warning";
  return "default";
}

export function ActivityTable({
  rows,
  loading,
  error,
  onRetry,
}: {
  rows: AuditRow[];
  loading?: boolean;
  error?: string;
  onRetry?: () => void;
}) {
  if (loading) {
    return (
      <div className="space-y-2 p-5">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-9 w-full" />
        ))}
      </div>
    );
  }
  if (error) {
    return (
      <div className="p-8 text-center text-sm text-muted-foreground">
        <p className="mb-3">Couldn’t load activity: {error}</p>
        {onRetry && (
          <button className="text-primary underline-offset-4 hover:underline" onClick={onRetry}>
            Retry
          </button>
        )}
      </div>
    );
  }
  if (!rows.length) {
    return (
      <div className="p-8 text-center text-sm text-muted-foreground">
        No write activity yet. Edits in Sheet and Wrangler show up here.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th className="px-5 py-2 font-medium">Action</th>
            <th className="px-5 py-2 font-medium">Collection</th>
            <th className="px-5 py-2 font-medium">Document</th>
            <th className="px-5 py-2 font-medium">Source</th>
            <th className="px-5 py-2 text-right font-medium">When</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-border/60 last:border-0 hover:bg-accent/40">
              <td className="px-5 py-2.5">
                <Badge variant={actionVariant(r.action)}>{r.action}</Badge>
              </td>
              <td className="px-5 py-2.5">{r.collection}</td>
              <td className="px-5 py-2.5 font-mono text-xs text-muted-foreground">{r.doc_id ?? "—"}</td>
              <td className="px-5 py-2.5 text-muted-foreground">{r.source}</td>
              <td className="px-5 py-2.5 text-right text-muted-foreground">{relativeTime(r.ts)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
