import type { LucideIcon } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export function StatCard({
  label,
  value,
  delta,
  icon: Icon,
  loading,
}: {
  label: string;
  value: string | number;
  delta?: string;
  icon?: LucideIcon;
  loading?: boolean;
}) {
  const positive = delta?.trim().startsWith("+");
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <span className="text-sm text-muted-foreground">{label}</span>
        {Icon && (
          <span className="flex size-8 items-center justify-center rounded-lg bg-accent text-accent-foreground">
            <Icon className="size-4" />
          </span>
        )}
      </div>
      {loading ? (
        <Skeleton className="mt-3 h-8 w-24" />
      ) : (
        <div className="tnum mt-2 text-3xl font-semibold tracking-tight">{value}</div>
      )}
      {delta && !loading && (
        <div className={cn("mt-1 text-xs font-medium", positive ? "text-success" : "text-muted-foreground")}>
          {delta}
        </div>
      )}
    </Card>
  );
}
