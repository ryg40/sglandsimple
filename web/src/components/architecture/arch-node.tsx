import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  Database, Server, Cloud, Shield, Ticket, Kanban, GitBranch, BookOpen,
  Snowflake, Activity, FileText, AlertTriangle, HardDrive, Box,
} from "lucide-react";
import type { ArchNode } from "@/lib/types";

// ---- icon mapping -----------------------------------------------------------
const KIND_ICON: Record<string, typeof Database> = {
  ec2_mongodb: Database,
  ec2: Server,
  rds: Database,
  s3: HardDrive,
  saas: Cloud,
  shield: Shield,
  ticket: Ticket,
  kanban: Kanban,
  git: GitBranch,
  book: BookOpen,
  cloud: Cloud,
  database: Database,
  snowflake: Snowflake,
  observability: Activity,
  artifact: FileText,
  box: Box,
};

// ---- cloud kind → color accent -----------------------------------------------
export const LAYER_ACCENT: Record<string, { bg: string; text: string; border: string }> = {
  aws_account:          { bg: "bg-amber-500/10",  text: "text-amber-600 dark:text-amber-400",  border: "border-amber-400/40" },
  azure_subscription:   { bg: "bg-blue-500/10",   text: "text-blue-600 dark:text-blue-400",    border: "border-blue-400/40" },
  gcp_project:          { bg: "bg-red-500/10",    text: "text-red-600 dark:text-red-400",      border: "border-red-400/40" },
  on_prem_zone:         { bg: "bg-slate-500/10",  text: "text-slate-600 dark:text-slate-400",  border: "border-slate-400/40" },
  saas:                 { bg: "bg-violet-500/10", text: "text-violet-600 dark:text-violet-400", border: "border-violet-400/40" },
};

export const LAYER_ACCENT_DEFAULT = { bg: "bg-muted", text: "text-muted-foreground", border: "border-border" };

const STATUS_DOT: Record<string, string> = {
  healthy: "bg-[var(--success)]",
  ok: "bg-[var(--success)]",
  active: "bg-[var(--success)]",
  disabled: "bg-muted-foreground/50",
  placeholder: "bg-[var(--warning)]",
  degraded: "bg-[var(--warning)]",
  error: "bg-[var(--destructive)]",
  unknown: "bg-muted-foreground/30",
};

// Data passed through ReactFlow node.data
export interface ArchNodeData extends Record<string, unknown> {
  node: ArchNode;
  layerKind: string;
  layerLabel: string;
  isEngineer: boolean;
  isFlowHighlight: boolean;
  flowStep: number | null;
}

export function ArchSystemNode({ data }: NodeProps) {
  const d = data as unknown as ArchNodeData;
  const n = d.node;
  const accent = LAYER_ACCENT[d.layerKind] ?? LAYER_ACCENT_DEFAULT;
  const Icon = KIND_ICON[n.kind] ?? Box;
  const hasConcern = n.concerns.length > 0;
  const dot = STATUS_DOT[n.status] ?? "bg-muted-foreground/30";

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`${n.label}, status ${n.status}${hasConcern ? `, ${n.concerns.length} concern(s)` : ""}`}
      className={[
        "w-[200px] rounded-xl border bg-card px-3 py-2.5 shadow-sm transition-shadow hover:shadow-md cursor-pointer",
        hasConcern
          ? "border-[var(--destructive)] ring-2 ring-[var(--destructive)]/30"
          : `border-border ${d.isFlowHighlight ? "ring-2 ring-[var(--chart-2)]" : ""}`,
      ].join(" ")}
    >
      <Handle type="target" position={Position.Left} className="!bg-[var(--chart-2)]" />

      {/* Layer badge header */}
      <div className={`-mx-3 -mt-2.5 mb-2 rounded-t-xl px-3 py-1 text-[9px] font-semibold uppercase tracking-wider ${accent.bg} ${accent.text} truncate`}>
        {d.layerLabel}
      </div>

      <div className="flex items-center gap-1.5">
        <Icon className="h-4 w-4 shrink-0 text-primary" />
        <span className="flex-1 truncate text-sm font-semibold">{n.label}</span>
        <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${dot}`} title={`Status: ${n.status}`} />
        {hasConcern && <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-[var(--destructive)]" />}
        {d.flowStep !== null && (
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[var(--chart-2)] text-[10px] font-bold text-white">
            {d.flowStep}
          </span>
        )}
      </div>

      {d.isEngineer && (
        <div className="mt-1 space-y-0.5">
          {n.meta.hostname && n.meta.hostname !== "TBD" && (
            <div className="truncate text-[9px] font-mono text-muted-foreground">{String(n.meta.hostname)}</div>
          )}
          {n.meta.instance_type && n.meta.instance_type !== "TBD" && (
            <div className="text-[9px] text-muted-foreground">{String(n.meta.instance_type)}</div>
          )}
        </div>
      )}

      <Handle type="source" position={Position.Right} className="!bg-[var(--chart-2)]" />
    </div>
  );
}
