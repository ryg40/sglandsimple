import { X, ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ArchNode, ArchLayer, ArchConcern } from "@/lib/types";

const META_KEYS = [
  "account_id", "vpc_id", "cidr", "hostname", "private_ip",
  "instance_type", "storage_gb", "retention_days", "owner",
  "data_classification", "criticality", "runbook_slug",
];

const INT_KEYS = ["protocol", "auth_mode", "endpoint_ref", "frequency", "sla", "agentic_status"];

interface ArchDrawerProps {
  node: ArchNode | null;
  layer: ArchLayer | null;
  concerns: ArchConcern[];
  isEngineer: boolean;
  onClose: () => void;
}

function TbdPill() {
  return (
    <span className="inline-flex items-center rounded-full border border-dashed border-muted-foreground/40 bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
      TBD — pending
    </span>
  );
}

function MetaRow({ label, value }: { label: string; value: string | number | null }) {
  if (value === null) return null;
  const isTbd = value === "TBD";
  return (
    <div className="flex items-start justify-between gap-2 py-1 text-xs border-b border-border/50 last:border-0">
      <span className="text-muted-foreground shrink-0">{label}</span>
      {isTbd ? <TbdPill /> : (
        <span className="font-mono text-foreground break-all text-right">{String(value)}</span>
      )}
    </div>
  );
}

export function ArchDrawer({ node, layer, concerns, isEngineer, onClose }: ArchDrawerProps) {
  if (!node) return null;

  const nodeConcerns = concerns.filter((c) => c.node_id === node.id);
  const runbookSlug = node.meta.runbook_slug;
  const hasRunbook = runbookSlug && runbookSlug !== "TBD";

  return (
    <aside className="flex w-80 shrink-0 flex-col border-l border-border bg-card/60 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{node.label}</div>
          {layer && (
            <div className="text-[10px] text-muted-foreground truncate">
              {layer.label} · {layer.kind.replace(/_/g, " ")}
            </div>
          )}
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} className="h-6 w-6 p-0 shrink-0">
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Status & kind */}
        <div className="flex items-center gap-2 flex-wrap">
          <Badge variant="outline" className="text-xs">{node.kind}</Badge>
          <Badge variant="outline" className="text-xs">{node.lane}</Badge>
          <Badge
            variant="outline"
            className={`text-xs ${node.status === "healthy" || node.status === "ok" || node.status === "active"
              ? "border-[var(--success)] text-[var(--success)]"
              : node.status === "error"
              ? "border-[var(--destructive)] text-[var(--destructive)]"
              : "border-[var(--warning)] text-[var(--warning)]"
            }`}
          >
            {node.status}
          </Badge>
        </div>

        {/* Runbook link */}
        {hasRunbook && (
          <a
            href={`/docs?doc=${encodeURIComponent(String(runbookSlug))}`}
            className="flex items-center gap-1.5 text-xs font-medium text-[var(--chart-2)] hover:underline"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Open runbook →
          </a>
        )}

        {/* Concerns */}
        {nodeConcerns.length > 0 && (
          <div>
            <h4 className="mb-1.5 text-xs font-semibold text-[var(--destructive)]">
              Concerns ({nodeConcerns.length})
            </h4>
            <ul className="space-y-1.5">
              {nodeConcerns.map((c) => (
                <li key={c.id} className="rounded-lg border border-[var(--destructive)]/30 bg-[var(--destructive)]/5 px-2.5 py-1.5 text-xs">
                  <div className="flex items-center gap-1.5 font-semibold text-[var(--destructive)]">
                    <span className="uppercase text-[9px]">{c.severity}</span>
                    <span className="font-normal text-muted-foreground">· {c.kind}</span>
                  </div>
                  <div className="mt-0.5 text-foreground">{c.title}</div>
                  {c.link && (
                    <a href={c.link} className="mt-0.5 text-[10px] text-[var(--chart-2)] hover:underline">
                      Open →
                    </a>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Stakeholder: plain description */}
        {!isEngineer && (
          <div>
            <h4 className="mb-1 text-xs font-semibold">Role</h4>
            <p className="text-xs text-muted-foreground">
              {node.kind.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())} in the{" "}
              {node.lane.replace(/_/g, " ")} lane of the architecture.
            </p>
            {node.meta.owner && node.meta.owner !== "TBD" && (
              <p className="mt-1 text-xs text-muted-foreground">
                Owner: <span className="font-medium text-foreground">{String(node.meta.owner)}</span>
              </p>
            )}
            {node.meta.data_classification && node.meta.data_classification !== "TBD" && (
              <p className="mt-0.5 text-xs text-muted-foreground">
                Classification: <span className="font-medium text-foreground">{String(node.meta.data_classification)}</span>
              </p>
            )}
          </div>
        )}

        {/* Engineer: all meta fields */}
        {isEngineer && (
          <div>
            <h4 className="mb-1.5 text-xs font-semibold">Infrastructure metadata</h4>
            <div className="rounded-lg border border-border bg-muted/30 px-3 py-1">
              {META_KEYS.map((k) => {
                const val = node.meta[k];
                if (val === undefined) return null;
                return <MetaRow key={k} label={k.replace(/_/g, " ")} value={val} />;
              })}
            </div>
          </div>
        )}

        {/* Integration keys (engineer only, shown if meta has them) */}
        {isEngineer && Object.keys(node.meta).some((k) => INT_KEYS.includes(k)) && (
          <div>
            <h4 className="mb-1.5 text-xs font-semibold">Integration</h4>
            <div className="rounded-lg border border-border bg-muted/30 px-3 py-1">
              {INT_KEYS.map((k) => {
                const val = node.meta[k];
                if (val === undefined) return null;
                return <MetaRow key={k} label={k.replace(/_/g, " ")} value={val} />;
              })}
            </div>
          </div>
        )}

        {/* Raw JSON (engineer) */}
        {isEngineer && (
          <div>
            <h4 className="mb-1 text-xs font-semibold">Raw JSON</h4>
            <pre className="max-h-48 overflow-auto rounded-lg bg-muted/50 p-2 text-[9px] font-mono text-muted-foreground">
              {JSON.stringify(node, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </aside>
  );
}
