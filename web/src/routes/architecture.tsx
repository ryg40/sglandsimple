import { useMemo, useCallback, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  MarkerType,
  type Node,
  type Edge,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Shield, Ticket, Kanban, GitBranch, BookOpen, Cloud, Database,
  Snowflake, AlertTriangle, RefreshCw, Network, ServerCrash,
} from "lucide-react";
import { useTopology } from "@/lib/queries";
import type { TopologyGraph, TopologyNode, TopologyConcern } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

const ICONS: Record<string, typeof Shield> = {
  shield: Shield, ticket: Ticket, kanban: Kanban, git: GitBranch,
  book: BookOpen, cloud: Cloud, database: Database, snowflake: Snowflake,
};

// Deterministic zoned layout: one column per zone (left → right), nodes
// stacked vertically within their zone. Stable across refetches.
function layout(graph: TopologyGraph): { nodes: Node[]; edges: Edge[] } {
  const zoneOrder = [...graph.zones].sort((a, b) => a.order - b.order);
  const COL_W = 260;
  const ROW_H = 130;
  const colIndex = new Map(zoneOrder.map((z, i) => [z.id, i]));
  const perZoneCount = new Map<string, number>();

  const nodes: Node[] = graph.nodes.map((n) => {
    const col = colIndex.get(n.zone) ?? 0;
    const row = perZoneCount.get(n.zone) ?? 0;
    perZoneCount.set(n.zone, row + 1);
    return {
      id: n.id,
      type: "system",
      position: { x: col * COL_W + 40, y: row * ROW_H + 60 },
      data: n as unknown as Record<string, unknown>,
    };
  });

  const edges: Edge[] = graph.edges.map((e) => ({
    id: `${e.from}->${e.to}`,
    source: e.from,
    target: e.to,
    label: e.label,
    animated: !!e.concern,
    markerEnd: { type: MarkerType.ArrowClosed, color: e.concern ? "var(--destructive)" : "var(--chart-2)" },
    style: {
      stroke: e.concern ? "var(--destructive)" : "var(--chart-2)",
      strokeWidth: e.concern ? 2.5 : 1.5,
    },
    labelStyle: { fontSize: 10, fill: "var(--muted-foreground)" },
    labelBgStyle: { fill: "var(--card)", fillOpacity: 0.85 },
  }));

  return { nodes, edges };
}

const STATUS_DOT: Record<string, string> = {
  healthy: "bg-[var(--success)]",
  ok: "bg-[var(--success)]",
  disabled: "bg-muted-foreground/50",
  placeholder: "bg-[var(--warning)]",
  degraded: "bg-[var(--warning)]",
  error: "bg-[var(--destructive)]",
};

// Custom node — a system "box" with icon, status dot, and a headline metric.
function SystemNode({ data }: NodeProps) {
  const n = data as unknown as TopologyNode;
  const Icon = ICONS[n.kind] ?? Database;
  const hasConcern = n.concerns.length > 0;
  const metricEntries = Object.entries(n.metrics ?? {});
  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`${n.label}, status ${n.status}${hasConcern ? `, ${n.concerns.length} concern(s)` : ""}`}
      className={`w-[200px] rounded-xl border bg-card px-3 py-2.5 shadow-sm transition-shadow hover:shadow-md ${
        hasConcern ? "border-[var(--destructive)] ring-2 ring-[var(--destructive)]/30" : "border-border"
      }`}
      title={`${n.label} • ${n.status} • ${n.endpoint}`}
    >
      <Handle type="target" position={Position.Left} className="!bg-[var(--chart-2)]" />
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-primary" />
        <span className="text-sm font-semibold">{n.label}</span>
        <span className={`ml-auto h-2.5 w-2.5 rounded-full ${STATUS_DOT[n.status] ?? "bg-muted-foreground/50"}`} />
        {hasConcern && <AlertTriangle className="h-3.5 w-3.5 text-[var(--destructive)]" />}
      </div>
      <div className="mt-1 truncate text-[10px] font-mono text-muted-foreground" title={n.endpoint}>
        {n.endpoint}
      </div>
      {metricEntries.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {metricEntries.slice(0, 3).map(([k, v]) => (
            <Badge key={k} variant="outline" className="text-[9px] font-mono py-0 px-1 font-normal">
              {k.replace(/_count$/, "").replace(/_/g, " ")}: {typeof v === "number" ? v.toLocaleString() : String(v)}
            </Badge>
          ))}
        </div>
      )}
      <Handle type="source" position={Position.Right} className="!bg-[var(--chart-2)]" />
    </div>
  );
}

const SEV_CLS: Record<string, string> = {
  critical: "border-[var(--destructive)] bg-[var(--destructive)]/10 text-[var(--destructive)]",
  high: "border-[var(--warning)] bg-[var(--warning)]/10 text-[var(--warning)]",
  medium: "border-border bg-muted text-muted-foreground",
  low: "border-border bg-muted text-muted-foreground",
};

export default function Architecture() {
  const { data, isLoading, isError, error, refetch, isRefetching } = useTopology();
  const [focusNode, setFocusNode] = useState<string | null>(null);

  const nodeTypes = useMemo(() => ({ system: SystemNode }), []);
  const flow = useMemo(() => (data ? layout(data) : { nodes: [], edges: [] }), [data]);

  // Highlight the focused node (from a concern click).
  const nodes = useMemo(
    () =>
      flow.nodes.map((n) => ({
        ...n,
        selected: n.id === focusNode,
      })),
    [flow.nodes, focusNode],
  );

  const onConcernClick = useCallback((c: TopologyConcern) => {
    if (c.node_id) setFocusNode(c.node_id);
  }, []);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-6 py-4">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <Network className="h-6 w-6 text-primary" />
            System Architecture
          </h2>
          <p className="text-sm text-muted-foreground">
            Live interconnectivity across every compliance system — endpoints, status, and points of concern.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isLoading || isRefetching}>
          <RefreshCw className={`mr-2 h-4 w-4 ${isRefetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {isLoading ? (
        <div className="flex-1 p-6">
          <Skeleton className="h-full w-full rounded-xl" />
        </div>
      ) : isError ? (
        <div className="m-auto flex max-w-md flex-col items-center rounded-xl border border-destructive/20 bg-destructive/5 p-8 text-center">
          <ServerCrash className="mb-3 h-10 w-10 text-destructive" />
          <h4 className="text-lg font-semibold text-destructive">Topology unavailable</h4>
          <p className="mt-1 text-sm text-muted-foreground">
            {error instanceof Error ? error.message : "Could not reach the MCP topology service."}
          </p>
          <Button variant="outline" size="sm" className="mt-4" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      ) : !data || data.nodes.length === 0 ? (
        <div className="m-auto flex flex-col items-center text-center text-muted-foreground">
          <Network className="mb-2 h-8 w-8" />
          <p className="text-sm font-semibold">No systems registered</p>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1">
          {/* Canvas */}
          <div className="relative min-w-0 flex-1">
            <ReactFlow
              nodes={nodes}
              edges={flow.edges}
              nodeTypes={nodeTypes}
              onNodeClick={(_, n) => setFocusNode(n.id)}
              fitView
              proOptions={{ hideAttribution: true }}
              minZoom={0.3}
            >
              <Background color="var(--border)" gap={20} />
              <Controls className="!shadow-md" />
              <MiniMap
                pannable
                zoomable
                nodeColor={(n) =>
                  ((n.data as unknown as TopologyNode)?.concerns?.length ?? 0) > 0
                    ? "var(--destructive)"
                    : "var(--chart-2)"
                }
                maskColor="color-mix(in oklch, var(--background) 80%, transparent)"
              />
              {/* Zone labels */}
              <div className="pointer-events-none absolute left-0 top-2 flex gap-[60px] pl-10 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                {[...data.zones].sort((a, b) => a.order - b.order).map((z) => (
                  <span key={z.id} className="w-[200px]">{z.label}</span>
                ))}
              </div>
            </ReactFlow>
          </div>

          {/* Concern list — the readable artifact, not just the canvas */}
          <aside className="w-80 shrink-0 overflow-y-auto border-l border-border bg-card/40 p-4">
            <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold">
              <AlertTriangle className="h-4 w-4 text-[var(--destructive)]" />
              Points of concern
              <Badge variant="outline" className="ml-auto font-mono">{data.concerns.length}</Badge>
            </h3>
            <p className="mb-3 text-[11px] text-muted-foreground">
              Click an item to focus its system on the diagram.
            </p>
            {data.concerns.length === 0 ? (
              <p className="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
                Nothing needs attention — all clear.
              </p>
            ) : (
              <ul className="space-y-2">
                {data.concerns.map((c) => (
                  <li key={c.id}>
                    <button
                      onClick={() => onConcernClick(c)}
                      className={`w-full rounded-lg border px-3 py-2 text-left text-xs transition-colors hover:bg-muted/60 ${
                        focusNode === c.node_id ? "ring-2 ring-primary" : ""
                      } ${SEV_CLS[c.severity] ?? SEV_CLS.low}`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-[9px] font-bold uppercase">{c.severity}</span>
                        <span className="ml-auto text-[9px] font-mono opacity-70">{c.kind}</span>
                      </div>
                      <div className="mt-1 leading-snug text-foreground">{c.title}</div>
                      {c.link && (
                        <a
                          href={c.link}
                          onClick={(e) => e.stopPropagation()}
                          className="mt-1 inline-block text-[10px] font-medium text-[var(--chart-2)] hover:underline"
                        >
                          Open in Hub →
                        </a>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
