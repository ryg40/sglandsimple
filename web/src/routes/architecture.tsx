import { useMemo, useCallback, useState, useEffect } from "react";
import { Link } from "react-router-dom";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  MarkerType,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  AlertTriangle, RefreshCw, Network, ServerCrash, Download, Copy, Check, ChevronDown, BookText,
} from "lucide-react";
import { useArchitecture } from "@/lib/queries";
import type { ArchitectureGraph, ArchNode, ArchEdge, ArchLayer, ArchConcern } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { ArchSystemNode, type ArchNodeData } from "@/components/architecture/arch-node";
import { ArchDrawer } from "@/components/architecture/arch-drawer";
import { ArchLegend } from "@/components/architecture/arch-legend";
import { ArchFiltersBar, KnownUnknownsPanel, EMPTY_FILTERS, type ArchFilters } from "@/components/architecture/arch-filters";
import {
  toMermaid,
  toStandaloneSvg,
  copyToClipboard,
  downloadString,
  downloadSvgAsPng,
  type ArchExportMode,
  type ArchExportPersona,
} from "@/lib/arch-export";

// ---- lane config ------------------------------------------------------------

const LANE_ORDER = [
  "sources",
  "risk_itsm",
  "atlassian",
  "implementation",
  "warehouse_observability",
  "artifacts",
] as const;

const LANE_LABELS: Record<string, string> = {
  sources: "Sources",
  risk_itsm: "Risk & ITSM",
  atlassian: "Atlassian",
  implementation: "Implementation",
  warehouse_observability: "Warehouse & Observability",
  artifacts: "Artifacts",
};

const COL_W = 240;
const ROW_H = 135;
const Y_OFFSET = 80;

const TEACHING_DOCS = [
  { slug: "overlap-chain", label: "Overlap chain" },
  { slug: "agentic-workflows", label: "Agentic workflows" },
  { slug: "mcp-in-this-stack", label: "MCP in this stack" },
] as const;

// ---- layout -----------------------------------------------------------------

function applyFilters(
  graph: ArchitectureGraph,
  filters: ArchFilters,
): { visibleNodeIds: Set<string> } {
  const visibleNodeIds = new Set<string>();
  for (const n of graph.nodes) {
    if (filters.search) {
      const q = filters.search.toLowerCase();
      if (!n.label.toLowerCase().includes(q) && !n.id.toLowerCase().includes(q)) continue;
    }
    if (filters.layerId && n.layer_id !== filters.layerId) continue;
    if (filters.kind && n.kind !== filters.kind) continue;
    if (filters.owner) {
      if (!n.meta.owner || n.meta.owner !== filters.owner) continue;
    }
    if (filters.dataClassification) {
      if (!n.meta.data_classification || n.meta.data_classification !== filters.dataClassification) continue;
    }
    if (filters.agenticStatus) {
      // node must have at least one edge with this agentic_status
      const hasMatch = graph.edges.some(
        (e) =>
          (e.from === n.id || e.to === n.id) &&
          e.integration.agentic_status === filters.agenticStatus
      );
      if (!hasMatch) continue;
    }
    visibleNodeIds.add(n.id);
  }
  return { visibleNodeIds };
}

type ViewMode = "topology" | "dataflow" | "both";
type PersonaMode = "stakeholder" | "engineer";

function buildFlow(
  graph: ArchitectureGraph,
  viewMode: ViewMode,
  isEngineer: boolean,
  filters: ArchFilters,
  selectedNodeId: string | null,
): { nodes: Node[]; edges: Edge[] } {
  const layerById = new Map<string, ArchLayer>(graph.layers.map((l) => [l.id, l]));

  // Active flow (default to risk_to_artifact)
  const activeFlow = graph.flows.find((f) => f.id === "risk_to_artifact") ?? graph.flows[0] ?? null;
  const flowStepMap = new Map<string, number>();
  if (activeFlow && (viewMode === "dataflow" || viewMode === "both")) {
    activeFlow.steps.forEach((nodeId, i) => flowStepMap.set(nodeId, i + 1));
  }

  const { visibleNodeIds } = applyFilters(graph, filters);
  const hasFilters = Object.values(filters).some(Boolean);

  // Build nodes
  const laneColMap = new Map<string, number>(LANE_ORDER.map((l, i) => [l, i]));
  const perLaneCount = new Map<string, number>();

  const nodes: Node[] = graph.nodes.map((n) => {
    const col = laneColMap.get(n.lane) ?? 0;
    const row = perLaneCount.get(n.lane) ?? 0;
    perLaneCount.set(n.lane, row + 1);

    const layer = layerById.get(n.layer_id);
    const flowStep = flowStepMap.get(n.id) ?? null;
    const isFlowHighlight = flowStep !== null;
    const isVisible = !hasFilters || visibleNodeIds.has(n.id);

    const nodeData: ArchNodeData = {
      node: n,
      layerKind: layer?.kind ?? "saas",
      layerLabel: layer?.label ?? n.layer_id,
      isEngineer,
      isFlowHighlight,
      flowStep,
    };

    return {
      id: n.id,
      type: "archSystem",
      position: { x: col * COL_W + 40, y: row * ROW_H + Y_OFFSET },
      data: nodeData as unknown as Record<string, unknown>,
      selected: n.id === selectedNodeId,
      style: hasFilters && !isVisible ? { opacity: 0.15, pointerEvents: "none" } : undefined,
    };
  });

  // Determine edge concerns: node IDs with concerns
  const concernNodeIds = new Set(graph.concerns.map((c) => c.node_id).filter(Boolean) as string[]);

  // Edge color helper
  function edgeStyle(e: ArchEdge): { stroke: string; strokeDasharray?: string; animated?: boolean } {
    const hasConcern = concernNodeIds.has(e.from) || concernNodeIds.has(e.to);
    if (hasConcern) return { stroke: "var(--destructive)" };
    const isPlanned =
      e.planned ||
      (e.integration.agentic_status && e.integration.agentic_status !== "current");
    if (isPlanned) {
      return {
        stroke: "var(--chart-3,#8b5cf6)",
        strokeDasharray: "6 3",
        animated: true,
      };
    }
    return { stroke: "var(--chart-2)" };
  }

  // In dataflow-only mode show only edges that are part of the active flow
  const flowEdgeSet = new Set<string>();
  if (activeFlow && viewMode === "dataflow") {
    for (let i = 0; i < activeFlow.steps.length - 1; i++) {
      flowEdgeSet.add(`${activeFlow.steps[i]}->${activeFlow.steps[i + 1]}`);
    }
  }

  const edges: Edge[] = graph.edges
    .filter((e) => {
      if (viewMode === "dataflow" && activeFlow) {
        return flowEdgeSet.has(`${e.from}->${e.to}`);
      }
      return true;
    })
    .map((e) => {
      const s = edgeStyle(e);
      const label = isEngineer ? `${e.protocol}${e.label ? ` · ${e.label}` : ""}` : e.label || undefined;

      // dim if either endpoint is filtered out
      const bothVisible = !hasFilters || (visibleNodeIds.has(e.from) && visibleNodeIds.has(e.to));

      return {
        id: `${e.from}->${e.to}`,
        source: e.from,
        target: e.to,
        label,
        animated: s.animated,
        markerEnd: { type: MarkerType.ArrowClosed, color: s.stroke },
        style: {
          stroke: s.stroke,
          strokeWidth: 1.8,
          strokeDasharray: s.strokeDasharray,
          opacity: !bothVisible ? 0.1 : undefined,
        },
        labelStyle: { fontSize: 9, fill: "var(--muted-foreground)" },
        labelBgStyle: { fill: "var(--card)", fillOpacity: 0.9 },
      };
    });

  return { nodes, edges };
}

// ---- severity helpers -------------------------------------------------------

const SEV_CLS: Record<string, string> = {
  critical: "border-[var(--destructive)] bg-[var(--destructive)]/10 text-[var(--destructive)]",
  high: "border-[var(--warning)] bg-[var(--warning)]/10 text-[var(--warning)]",
  medium: "border-border bg-muted text-muted-foreground",
  low: "border-border bg-muted text-muted-foreground",
};

// ---- sidebar tab type -------------------------------------------------------
type SidebarTab = "concerns" | "unknowns";

// ---- main page --------------------------------------------------------------

export default function Architecture() {
  const { data, isLoading, isError, error, refetch, isRefetching } = useArchitecture();

  const [viewMode, setViewMode] = useState<ViewMode>("topology");
  const [personaMode, setPersonaMode] = useState<PersonaMode>("stakeholder");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [filters, setFilters] = useState<ArchFilters>(EMPTY_FILTERS);
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>("concerns");

  // Export state
  const [exportStatus, setExportStatus] = useState<"idle" | "copied" | "failed" | "png-failed">("idle");
  useEffect(() => {
    if (exportStatus !== "idle") {
      const t = setTimeout(() => setExportStatus("idle"), 2000);
      return () => clearTimeout(t);
    }
  }, [exportStatus]);

  const nodeTypes = useMemo(() => ({ archSystem: ArchSystemNode }), []);

  const isEngineer = personaMode === "engineer";

  const flow = useMemo(
    () =>
      data
        ? buildFlow(data, viewMode, isEngineer, filters, selectedNodeId)
        : { nodes: [], edges: [] },
    [data, viewMode, isEngineer, filters, selectedNodeId],
  );

  // Active flow for export (mirrors buildFlow's logic)
  const activeFlow = useMemo(
    () => data?.flows.find((f) => f.id === "risk_to_artifact") ?? data?.flows[0] ?? null,
    [data],
  );

  // Export helpers
  const exportDateSlug = new Date().toISOString().slice(0, 10);
  const exportMode = viewMode as ArchExportMode;
  const exportPersona = personaMode as ArchExportPersona;

  const handleCopyMermaid = useCallback(async () => {
    if (!data) return;
    const mmd = toMermaid(data, { mode: exportMode, persona: exportPersona, activeFlow });
    const ok = await copyToClipboard(mmd);
    setExportStatus(ok ? "copied" : "failed");
  }, [data, exportMode, exportPersona, activeFlow]);

  const handleDownloadSvg = useCallback(() => {
    if (!data) return;
    const svg = toStandaloneSvg(data, { mode: exportMode, persona: exportPersona, activeFlow });
    downloadString(svg, `architecture-${exportMode}-${exportDateSlug}.svg`, "image/svg+xml");
  }, [data, exportMode, exportPersona, activeFlow, exportDateSlug]);

  const handleDownloadPng = useCallback(async () => {
    if (!data) return;
    const svg = toStandaloneSvg(data, { mode: exportMode, persona: exportPersona, activeFlow });
    const ok = await downloadSvgAsPng(svg, `architecture-${exportMode}-${exportDateSlug}.png`);
    if (!ok) setExportStatus("png-failed");
  }, [data, exportMode, exportPersona, activeFlow, exportDateSlug]);

  // Selected node + its layer
  const selectedNode = useMemo<ArchNode | null>(
    () => data?.nodes.find((n) => n.id === selectedNodeId) ?? null,
    [data, selectedNodeId],
  );
  const selectedLayer = useMemo<ArchLayer | null>(
    () =>
      selectedNode
        ? (data?.layers.find((l) => l.id === selectedNode.layer_id) ?? null)
        : null,
    [data, selectedNode],
  );

  const onConcernClick = useCallback((c: ArchConcern) => {
    if (c.node_id) setSelectedNodeId(c.node_id);
  }, []);

  const focusNode = useCallback((id: string) => setSelectedNodeId(id), []);

  // Lane header positions for the canvas overlay
  const laneHeaders = useMemo(
    () =>
      LANE_ORDER.map((lane, i) => ({
        lane,
        label: LANE_LABELS[lane] ?? lane,
        x: i * COL_W + 40,
      })),
    [],
  );

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* ---- Top header ---- */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-6 py-4">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <Network className="h-6 w-6 text-primary" />
            System Architecture
          </h2>
          <p className="text-sm text-muted-foreground">
            Enterprise topology, data flows, and integration status across all environments.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">Teaching docs:</span>
            {TEACHING_DOCS.map((doc) => (
              <Link
                key={doc.slug}
                to={`/docs?doc=${doc.slug}`}
                className="inline-flex items-center gap-1 rounded-full border bg-muted/40 px-2.5 py-1 font-medium text-foreground transition-colors hover:bg-accent"
              >
                <BookText className="size-3.5 text-primary" />
                {doc.label}
              </Link>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {/* Persona toggle */}
          <div className="flex rounded-lg border border-border bg-muted p-0.5 text-xs">
            {(["stakeholder", "engineer"] as PersonaMode[]).map((m) => (
              <button
                key={m}
                onClick={() => setPersonaMode(m)}
                className={`rounded-md px-3 py-1 font-medium capitalize transition-colors ${
                  personaMode === m
                    ? "bg-card text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {m}
              </button>
            ))}
          </div>

          {/* View mode toggle */}
          <div className="flex rounded-lg border border-border bg-muted p-0.5 text-xs">
            {(["topology", "dataflow", "both"] as ViewMode[]).map((m) => (
              <button
                key={m}
                onClick={() => setViewMode(m)}
                className={`rounded-md px-3 py-1 font-medium capitalize transition-colors ${
                  viewMode === m
                    ? "bg-card text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {m === "dataflow" ? "Data flow" : m.charAt(0).toUpperCase() + m.slice(1)}
              </button>
            ))}
          </div>

          <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isLoading || isRefetching}>
            <RefreshCw className={`mr-2 h-4 w-4 ${isRefetching ? "animate-spin" : ""}`} />
            Refresh
          </Button>

          {/* Export dropdown */}
          {data && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" className="gap-1">
                  <Download className="h-4 w-4" />
                  Export
                  <ChevronDown className="h-3 w-3 opacity-60" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>Export diagram</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={handleCopyMermaid}>
                  {exportStatus === "copied" ? (
                    <Check className="h-4 w-4 text-green-500" />
                  ) : (
                    <Copy className="h-4 w-4" />
                  )}
                  {exportStatus === "copied"
                    ? "Copied!"
                    : exportStatus === "failed"
                    ? "Copy failed"
                    : "Copy Mermaid"}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={handleDownloadSvg}>
                  <Download className="h-4 w-4" />
                  Download SVG
                </DropdownMenuItem>
                <DropdownMenuItem onClick={handleDownloadPng}>
                  <Download className="h-4 w-4" />
                  {exportStatus === "png-failed"
                    ? "PNG failed — try SVG"
                    : "Download PNG"}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>

      {/* ---- Filter bar ---- */}
      {data && (
        <ArchFiltersBar filters={filters} onChange={setFilters} graph={data} />
      )}

      {/* ---- Body ---- */}
      {isLoading ? (
        <div className="flex-1 p-6">
          <Skeleton className="h-full w-full rounded-xl" />
        </div>
      ) : isError ? (
        <div className="m-auto flex max-w-md flex-col items-center rounded-xl border border-destructive/20 bg-destructive/5 p-8 text-center">
          <ServerCrash className="mb-3 h-10 w-10 text-destructive" />
          <h4 className="text-lg font-semibold text-destructive">Architecture unavailable</h4>
          <p className="mt-1 text-sm text-muted-foreground">
            {error instanceof Error ? error.message : "Could not reach the MCP architecture service."}
          </p>
          <Button variant="outline" size="sm" className="mt-4" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      ) : !data || data.nodes.length === 0 ? (
        <div className="m-auto flex flex-col items-center text-center text-muted-foreground">
          <Network className="mb-2 h-8 w-8" />
          <p className="text-sm font-semibold">No architecture data found</p>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 overflow-hidden">
          {/* ---- Canvas ---- */}
          <div className="relative min-w-0 flex-1">
            <ReactFlow
              nodes={flow.nodes}
              edges={flow.edges}
              nodeTypes={nodeTypes}
              onNodeClick={(_evt, n) => setSelectedNodeId(n.id)}
              fitView
              proOptions={{ hideAttribution: true }}
              minZoom={0.2}
              maxZoom={2}
            >
              <Background color="var(--border)" gap={20} />
              <Controls className="!shadow-md" />
              <MiniMap
                pannable
                zoomable
                nodeColor={(n) => {
                  const d = n.data as unknown as ArchNodeData;
                  if (d.node?.concerns?.length > 0) return "var(--destructive)";
                  return "var(--chart-2)";
                }}
                maskColor="color-mix(in oklch, var(--background) 80%, transparent)"
              />

              {/* Lane header overlay */}
              <div className="pointer-events-none absolute left-0 top-2 flex pl-10 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {laneHeaders.map((lh) => (
                  <span
                    key={lh.lane}
                    className="text-center"
                    style={{ width: COL_W, marginLeft: lh.x === laneHeaders[0].x ? 0 : undefined }}
                  >
                    {lh.label}
                  </span>
                ))}
              </div>

              {/* Legend (bottom-left corner, inside canvas) */}
              <div className="pointer-events-none absolute bottom-14 left-3">
                <ArchLegend />
              </div>
            </ReactFlow>
          </div>

          {/* ---- Right sidebar ---- */}
          <aside className="flex w-80 shrink-0 flex-col border-l border-border bg-card/40 overflow-hidden">
            {/* Tabs */}
            <div className="flex border-b border-border">
              {([
                ["concerns", `Concerns (${data.concerns.length})`],
                ["unknowns", "Known unknowns"],
              ] as [SidebarTab, string][]).map(([tab, label]) => (
                <button
                  key={tab}
                  onClick={() => setSidebarTab(tab)}
                  className={`flex-1 py-2 text-xs font-medium transition-colors ${
                    sidebarTab === tab
                      ? "border-b-2 border-primary text-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            <div className="flex-1 overflow-y-auto p-4">
              {sidebarTab === "concerns" && (
                <>
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
                              selectedNodeId === c.node_id ? "ring-2 ring-primary" : ""
                            } ${SEV_CLS[c.severity] ?? SEV_CLS.low}`}
                          >
                            <div className="flex items-center gap-2">
                              <AlertTriangle className="h-3 w-3 shrink-0" />
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
                </>
              )}

              {sidebarTab === "unknowns" && (
                <KnownUnknownsPanel graph={data} focusNode={focusNode} />
              )}
            </div>
          </aside>

          {/* ---- Details drawer (slides in beside sidebar) ---- */}
          {selectedNode && (
            <ArchDrawer
              node={selectedNode}
              layer={selectedLayer}
              concerns={data.concerns}
              isEngineer={isEngineer}
              onClose={() => setSelectedNodeId(null)}
            />
          )}
        </div>
      )}
    </div>
  );
}
