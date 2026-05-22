import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ArchitectureGraph } from "@/lib/types";

export interface ArchFilters {
  search: string;
  layerId: string;
  kind: string;
  owner: string;
  dataClassification: string;
  agenticStatus: string;
}

export const EMPTY_FILTERS: ArchFilters = {
  search: "",
  layerId: "",
  kind: "",
  owner: "",
  dataClassification: "",
  agenticStatus: "",
};

interface ArchFiltersBarProps {
  filters: ArchFilters;
  onChange: (f: ArchFilters) => void;
  graph: ArchitectureGraph;
}

function unique(arr: (string | number | null)[]): string[] {
  return Array.from(new Set(arr.filter((x): x is string => typeof x === "string" && x !== "" && x !== "TBD")));
}

export function ArchFiltersBar({ filters, onChange, graph }: ArchFiltersBarProps) {
  const layers = graph.layers.map((l) => ({ id: l.id, label: l.label }));
  const kinds = unique(graph.nodes.map((n) => n.kind));
  const owners = unique(graph.nodes.map((n) => n.meta.owner ?? null));
  const classifications = unique(graph.nodes.map((n) => n.meta.data_classification ?? null));
  const agenticStatuses = unique(
    graph.edges.flatMap((e) =>
      e.integration.agentic_status ? [e.integration.agentic_status] : []
    )
  );

  const set = (key: keyof ArchFilters, value: string) =>
    onChange({ ...filters, [key]: value });

  const activeCount = Object.values(filters).filter(Boolean).length;

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border bg-card/50 px-4 py-2">
      {/* Search */}
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          className="h-7 w-48 pl-8 text-xs"
          placeholder="Search nodes…"
          value={filters.search}
          onChange={(e) => set("search", e.target.value)}
        />
      </div>

      {/* Environment */}
      <select
        className="h-7 rounded-md border border-input bg-card px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
        value={filters.layerId}
        onChange={(e) => set("layerId", e.target.value)}
      >
        <option value="">All environments</option>
        {layers.map((l) => (
          <option key={l.id} value={l.id}>{l.label}</option>
        ))}
      </select>

      {/* Kind */}
      <select
        className="h-7 rounded-md border border-input bg-card px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
        value={filters.kind}
        onChange={(e) => set("kind", e.target.value)}
      >
        <option value="">All kinds</option>
        {kinds.map((k) => (
          <option key={k} value={k}>{k}</option>
        ))}
      </select>

      {/* Owner */}
      {owners.length > 0 && (
        <select
          className="h-7 rounded-md border border-input bg-card px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          value={filters.owner}
          onChange={(e) => set("owner", e.target.value)}
        >
          <option value="">All owners</option>
          {owners.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
      )}

      {/* Data classification */}
      {classifications.length > 0 && (
        <select
          className="h-7 rounded-md border border-input bg-card px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          value={filters.dataClassification}
          onChange={(e) => set("dataClassification", e.target.value)}
        >
          <option value="">All classifications</option>
          {classifications.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      )}

      {/* Agentic status */}
      {agenticStatuses.length > 0 && (
        <select
          className="h-7 rounded-md border border-input bg-card px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          value={filters.agenticStatus}
          onChange={(e) => set("agenticStatus", e.target.value)}
        >
          <option value="">All integration status</option>
          {agenticStatuses.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      )}

      {/* Clear */}
      {activeCount > 0 && (
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs text-muted-foreground"
          onClick={() => onChange(EMPTY_FILTERS)}
        >
          <X className="mr-1 h-3 w-3" />
          Clear ({activeCount})
        </Button>
      )}
    </div>
  );
}

// ---- Known-unknowns panel ---------------------------------------------------

const META_KEYS = [
  "account_id", "vpc_id", "cidr", "hostname", "private_ip",
  "instance_type", "storage_gb", "retention_days", "owner",
  "data_classification", "criticality", "runbook_slug",
];

interface KnownUnknownsProps {
  graph: ArchitectureGraph;
  focusNode: (id: string) => void;
}

interface TbdEntry {
  nodeId: string;
  nodeLabel: string;
  fields: string[];
  owner: string | null;
  layerLabel: string;
}

export function KnownUnknownsPanel({ graph, focusNode }: KnownUnknownsProps) {
  const layerById = new Map(graph.layers.map((l) => [l.id, l]));

  const entries: TbdEntry[] = graph.nodes
    .map((n) => {
      const fields = META_KEYS.filter((k) => n.meta[k] === "TBD");
      const layer = layerById.get(n.layer_id);
      return {
        nodeId: n.id,
        nodeLabel: n.label,
        fields,
        owner: typeof n.meta.owner === "string" && n.meta.owner !== "TBD" ? n.meta.owner : null,
        layerLabel: layer?.label ?? n.layer_id,
      };
    })
    .filter((e) => e.fields.length > 0);

  const totalTbd = entries.reduce((s, e) => s + e.fields.length, 0);

  return (
    <div>
      <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold">
        Known unknowns
        <Badge variant="outline" className="ml-auto font-mono">{totalTbd}</Badge>
      </h3>
      <p className="mb-2 text-[11px] text-muted-foreground">
        Meta fields still marked TBD — these need to be populated.
      </p>
      <a
        href="/docs?doc=docs/architecture-inventory-template"
        className="mb-3 inline-flex items-center gap-1 text-[11px] font-medium text-[var(--chart-2)] hover:underline"
      >
        Architecture inventory capture form →
      </a>

      {entries.length === 0 ? (
        <p className="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
          All meta fields populated — nothing pending.
        </p>
      ) : (
        <ul className="space-y-2">
          {entries.map((e) => (
            <li key={e.nodeId}>
              <button
                onClick={() => focusNode(e.nodeId)}
                className="w-full rounded-lg border border-border px-3 py-2 text-left text-xs hover:bg-muted/60 transition-colors"
              >
                <div className="flex items-center gap-1.5">
                  <span className="font-semibold text-foreground truncate">{e.nodeLabel}</span>
                  <Badge variant="outline" className="ml-auto font-mono text-[9px] shrink-0">{e.fields.length}</Badge>
                </div>
                <div className="mt-0.5 text-[10px] text-muted-foreground">{e.layerLabel}</div>
                <div className="mt-1 flex flex-wrap gap-1">
                  {e.fields.map((f) => (
                    <span key={f} className="inline-flex items-center rounded border border-dashed border-muted-foreground/40 bg-muted px-1.5 py-0.5 text-[9px] text-muted-foreground">
                      {f.replace(/_/g, " ")}
                    </span>
                  ))}
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
