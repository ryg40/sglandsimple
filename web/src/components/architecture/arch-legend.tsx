import { LAYER_ACCENT } from "./arch-node";

const CLOUD_KINDS: { kind: string; label: string }[] = [
  { kind: "aws_account",        label: "AWS" },
  { kind: "azure_subscription", label: "Azure" },
  { kind: "gcp_project",        label: "GCP" },
  { kind: "on_prem_zone",       label: "On-Prem" },
  { kind: "saas",               label: "SaaS" },
];

export function ArchLegend() {
  return (
    <div className="rounded-xl border border-border bg-card/80 p-3 text-xs shadow-sm backdrop-blur w-[200px]">
      <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Legend</div>

      {/* Cloud accents */}
      <div className="mb-2 space-y-1">
        {CLOUD_KINDS.map(({ kind, label }) => {
          const a = LAYER_ACCENT[kind];
          return (
            <div key={kind} className="flex items-center gap-2">
              <span className={`h-3 w-3 rounded-sm border ${a.bg} ${a.border}`} />
              <span className="text-muted-foreground">{label}</span>
            </div>
          );
        })}
      </div>

      <div className="my-1.5 border-t border-border" />

      {/* Status dots */}
      <div className="mb-2 space-y-1">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-[var(--success)]" />
          <span className="text-muted-foreground">Healthy</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-[var(--warning)]" />
          <span className="text-muted-foreground">Degraded</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-[var(--destructive)]" />
          <span className="text-muted-foreground">Error</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-muted-foreground/30" />
          <span className="text-muted-foreground">Unknown</span>
        </div>
      </div>

      <div className="my-1.5 border-t border-border" />

      {/* Edge types */}
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <svg width="28" height="8" className="shrink-0">
            <line x1="0" y1="4" x2="28" y2="4" stroke="var(--chart-2)" strokeWidth="2" />
          </svg>
          <span className="text-muted-foreground">Current</span>
        </div>
        <div className="flex items-center gap-2">
          <svg width="28" height="8" className="shrink-0">
            <line x1="0" y1="4" x2="28" y2="4" stroke="var(--chart-3,#8b5cf6)" strokeWidth="2" strokeDasharray="4 3" />
          </svg>
          <span className="text-muted-foreground">Planned / agentic</span>
        </div>
        <div className="flex items-center gap-2">
          <svg width="28" height="8" className="shrink-0">
            <line x1="0" y1="4" x2="28" y2="4" stroke="var(--destructive)" strokeWidth="2" />
          </svg>
          <span className="text-muted-foreground">Has concern</span>
        </div>
      </div>

      <div className="my-1.5 border-t border-border" />

      {/* Flow step badge */}
      <div className="flex items-center gap-2">
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--chart-2)] text-[10px] font-bold text-white">
          1
        </span>
        <span className="text-muted-foreground">Flow step</span>
      </div>
    </div>
  );
}
