import { Link } from "react-router-dom";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { Row } from "@/lib/types";

/** A compact, capped table of the most-recent rows of one collection.
 *  Used by the Overview multi-table region (Stage 11). */
export function MiniTable({
  title,
  description,
  columns,
  rows,
  rowLink,
  viewAllHref,
  loading,
  error,
  onRetry,
}: {
  title: string;
  description?: string;
  columns: { key: string; label: string; align?: "left" | "right" }[];
  rows: Row[];
  rowLink?: (row: Row) => string;
  viewAllHref?: string;
  loading?: boolean;
  error?: string;
  onRetry?: () => void;
}) {
  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex-row items-center justify-between gap-2 space-y-0">
        <div>
          <CardTitle className="text-base">{title}</CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </div>
        {viewAllHref && (
          <Link to={viewAllHref} className="text-xs font-medium text-primary hover:underline">
            View all in Hub →
          </Link>
        )}
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
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-6 w-full" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <div className="p-6 text-center text-sm text-muted-foreground">No rows.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  {columns.map((c) => (
                    <th
                      key={c.key}
                      className={`px-4 py-2 font-medium ${c.align === "right" ? "text-right" : ""}`}
                    >
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const href = rowLink?.(r);
                  const cells = columns.map((c) => {
                    const v = r[c.key];
                    const text = v == null ? "—" : String(v);
                    return (
                      <td
                        key={c.key}
                        className={`px-4 py-2 ${c.align === "right" ? "text-right tnum" : ""} truncate`}
                        title={text}
                      >
                        {c.key === columns[0].key && href ? (
                          <Link to={href} className="text-foreground hover:text-primary hover:underline">
                            {text}
                          </Link>
                        ) : (
                          text
                        )}
                      </td>
                    );
                  });
                  return (
                    <tr key={(r._id as string) ?? i} className="border-b last:border-0 hover:bg-muted/40">
                      {cells}
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
