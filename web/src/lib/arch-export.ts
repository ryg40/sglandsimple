// arch-export.ts — pure utility module for architecture diagram export.
// No React imports; no new npm packages; browser-native APIs only.

import type { ArchitectureGraph, ArchFlow, ArchEdge } from "@/lib/types";

export type ArchExportMode = "topology" | "dataflow" | "both";
export type ArchExportPersona = "stakeholder" | "engineer";

// ---- lane config (local copy — do not import from route) -------------------

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

// ---- colour palette (standalone / non-CSS-var) -----------------------------

const C_NODE_FILL = "#1A1446";
const C_NODE_TEXT = "#ffffff";
const C_ACCENT = "#FFD000";
const C_EDGE_CURRENT = "#06748C";
const C_EDGE_PLANNED = "#8b5cf6";
const C_CONCERN = "#ef4444";
const C_LANE_BG = "#0f0c2e";
const C_LANE_BORDER = "#2d2460";
const C_BG = "#0a0820";

// ---- helpers ----------------------------------------------------------------

/** Sanitise a node id for Mermaid (replace non-alphanumerics with _). */
function safeMermaidId(id: string): string {
  return id.replace(/[^a-zA-Z0-9]/g, "_");
}

/** Resolve the active flow from a graph the same way buildFlow does. */
function resolveActiveFlow(graph: ArchitectureGraph): ArchFlow | null {
  return graph.flows.find((f) => f.id === "risk_to_artifact") ?? graph.flows[0] ?? null;
}

/** Return true if the edge should be rendered as "planned/agentic" (dashed). */
function isPlannedEdge(e: ArchEdge): boolean {
  return (
    e.planned ||
    (!!e.integration.agentic_status && e.integration.agentic_status !== "current")
  );
}

// ---- toMermaid --------------------------------------------------------------

/**
 * Build a Mermaid flowchart string for the graph.
 *
 * - Nodes grouped by lane into subgraphs.
 * - Edges: solid (-->) for current, dashed (-.->) for planned/agentic.
 * - Edge labels = protocol (engineer) or human label (stakeholder).
 * - Concern nodes tagged with ⚠.
 * - Header comment with title, timestamp, and mode.
 * - Legend comment block appended.
 */
export function toMermaid(
  graph: ArchitectureGraph,
  opts: {
    mode: ArchExportMode;
    persona: ArchExportPersona;
    activeFlow?: ArchFlow | null;
  },
): string {
  const { mode, persona } = opts;
  const activeFlow = opts.activeFlow !== undefined ? opts.activeFlow : resolveActiveFlow(graph);

  const ts = new Date().toISOString();
  const lines: string[] = [];

  // Header comment
  lines.push(`%% Architecture Export`);
  lines.push(`%% title: System Architecture`);
  lines.push(`%% timestamp: ${ts}`);
  lines.push(`%% mode: ${mode} · view: ${persona}`);
  lines.push("");
  lines.push("flowchart LR");

  // Concern node ids
  const concernNodeIds = new Set(
    graph.concerns.map((c) => c.node_id).filter(Boolean) as string[],
  );

  // Group nodes by lane
  const byLane = new Map<string, typeof graph.nodes>();
  for (const lane of LANE_ORDER) {
    byLane.set(lane, []);
  }
  for (const n of graph.nodes) {
    const bucket = byLane.get(n.lane);
    if (bucket) bucket.push(n);
    else {
      // unknown lane — create bucket
      const b: typeof graph.nodes = [];
      byLane.set(n.lane, b);
      b.push(n);
    }
  }

  // Emit subgraphs
  for (const lane of LANE_ORDER) {
    const nodes = byLane.get(lane);
    if (!nodes || nodes.length === 0) continue;
    const laneLabel = LANE_LABELS[lane] ?? lane;
    lines.push(`  subgraph ${safeMermaidId(lane)}["${laneLabel}"]`);
    for (const n of nodes) {
      const mid = safeMermaidId(n.id);
      const hasConcern = concernNodeIds.has(n.id);
      const nodeLabel = hasConcern ? `⚠ ${n.label}` : n.label;
      // Use rounded rectangle for all nodes
      lines.push(`    ${mid}["${nodeLabel}"]`);
    }
    lines.push("  end");
  }

  // Determine which edges to render
  let edgesToRender = graph.edges;

  if (mode === "dataflow" && activeFlow) {
    const flowEdgeSet = new Set<string>();
    for (let i = 0; i < activeFlow.steps.length - 1; i++) {
      flowEdgeSet.add(`${activeFlow.steps[i]}->${activeFlow.steps[i + 1]}`);
    }
    edgesToRender = graph.edges.filter((e) =>
      flowEdgeSet.has(`${e.from}->${e.to}`),
    );
  }

  // Emit edges
  lines.push("");
  for (const e of edgesToRender) {
    const fromId = safeMermaidId(e.from);
    const toId = safeMermaidId(e.to);
    const planned = isPlannedEdge(e);
    const edgeLabel =
      persona === "engineer"
        ? `${e.protocol}${e.label ? ` · ${e.label}` : ""}`
        : e.label || e.protocol;

    if (planned) {
      lines.push(`  ${fromId} -. "${edgeLabel}" .-> ${toId}`);
    } else {
      lines.push(`  ${fromId} -- "${edgeLabel}" --> ${toId}`);
    }
  }

  // Concern node styling
  if (concernNodeIds.size > 0) {
    lines.push("");
    lines.push("  %% concern nodes");
    for (const nodeId of concernNodeIds) {
      lines.push(`  style ${safeMermaidId(nodeId)} stroke:#ef4444,stroke-width:2px`);
    }
  }

  // Legend comment
  lines.push("");
  lines.push("%% Legend:");
  lines.push("%%   --> solid arrow  = current / live integration");
  lines.push("%%   -.-> dashed arrow = planned or agentic (not yet live)");
  lines.push("%%   ⚠ node label     = has active concerns / risks");
  lines.push(`%%   Generated: ${ts}`);

  return lines.join("\n");
}

// ---- copyToClipboard --------------------------------------------------------

/**
 * Copy text to clipboard via navigator.clipboard.writeText.
 * Returns Promise<boolean> — false on failure, never throws.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

// ---- downloadString ---------------------------------------------------------

/**
 * Trigger a browser download of a string as a file (Blob + object URL + <a download>).
 */
export function downloadString(
  content: string,
  filename: string,
  mime: string,
): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ---- exportNodeToPng --------------------------------------------------------

/**
 * Export a DOM element to PNG via SVG foreignObject → canvas → data URL → download.
 * Falls back gracefully and returns false on taint/security errors.
 */
export async function exportNodeToPng(
  el: HTMLElement,
  filename: string,
): Promise<boolean> {
  try {
    const rect = el.getBoundingClientRect();
    const w = Math.round(rect.width) || 1200;
    const h = Math.round(rect.height) || 800;

    const clone = el.cloneNode(true) as HTMLElement;
    clone.style.transform = "none";

    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("xmlns", svgNS);
    svg.setAttribute("width", String(w));
    svg.setAttribute("height", String(h));

    const fo = document.createElementNS(svgNS, "foreignObject");
    fo.setAttribute("width", String(w));
    fo.setAttribute("height", String(h));
    fo.appendChild(clone);
    svg.appendChild(fo);

    const svgStr = new XMLSerializer().serializeToString(svg);
    const dataUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgStr)}`;

    const img = new Image();
    img.src = dataUrl;
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = reject;
    });

    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return false;
    ctx.drawImage(img, 0, 0);

    const pngUrl = canvas.toDataURL("image/png");
    const a = document.createElement("a");
    a.href = pngUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    return true;
  } catch {
    return false;
  }
}

// ---- toStandaloneSvg --------------------------------------------------------

// SVG layout constants
const SVG_LANE_W = 220;
const SVG_NODE_H = 52;
const SVG_NODE_W = 190;
const SVG_NODE_GAP = 18;
const SVG_LANE_PAD_X = 15;
const SVG_LANE_PAD_Y = 52;
const SVG_TITLE_H = 56;
const SVG_LEGEND_H = 110;
const SVG_LEGEND_W = 270;
const SVG_RADIUS = 8;
const SVG_MARKER_SIZE = 8;

/**
 * Build a standalone SVG string of the diagram from graph data.
 * Deterministic layout: 6 lanes left→right, nodes stacked vertically within each lane.
 * Includes title bar (title + timestamp + mode), lane columns, node boxes, edges, and legend.
 */
export function toStandaloneSvg(
  graph: ArchitectureGraph,
  opts: {
    mode: ArchExportMode;
    persona: ArchExportPersona;
    activeFlow?: ArchFlow | null;
  },
): string {
  const { mode, persona } = opts;
  const activeFlow = opts.activeFlow !== undefined ? opts.activeFlow : resolveActiveFlow(graph);
  const ts = new Date().toISOString();

  // Group nodes by lane
  const byLane = new Map<string, typeof graph.nodes>();
  for (const lane of LANE_ORDER) {
    byLane.set(lane, []);
  }
  for (const n of graph.nodes) {
    const bucket = byLane.get(n.lane);
    if (bucket) {
      bucket.push(n);
    } else {
      byLane.set(n.lane, [n]);
    }
  }

  const laneCount = LANE_ORDER.length;
  const maxNodesInLane = Math.max(
    ...LANE_ORDER.map((l) => byLane.get(l)?.length ?? 0),
  );

  const canvasW = laneCount * SVG_LANE_W + 40;
  const canvasH =
    SVG_TITLE_H +
    SVG_LANE_PAD_Y +
    maxNodesInLane * (SVG_NODE_H + SVG_NODE_GAP) +
    SVG_NODE_GAP +
    SVG_LEGEND_H +
    20;

  // Node centre positions (for edge routing)
  const nodeCX = new Map<string, number>(); // node id → centre x
  const nodeCY = new Map<string, number>(); // node id → centre y

  for (let li = 0; li < LANE_ORDER.length; li++) {
    const lane = LANE_ORDER[li];
    const nodes = byLane.get(lane) ?? [];
    const laneX = 20 + li * SVG_LANE_W;
    for (let ni = 0; ni < nodes.length; ni++) {
      const n = nodes[ni];
      const cx = laneX + SVG_LANE_PAD_X + SVG_NODE_W / 2;
      const cy =
        SVG_TITLE_H +
        SVG_LANE_PAD_Y +
        ni * (SVG_NODE_H + SVG_NODE_GAP) +
        SVG_NODE_H / 2;
      nodeCX.set(n.id, cx);
      nodeCY.set(n.id, cy);
    }
  }

  // Concern node ids
  const concernNodeIds = new Set(
    graph.concerns.map((c) => c.node_id).filter(Boolean) as string[],
  );

  // Active flow steps
  let flowEdgeSet: Set<string> | null = null;
  if (activeFlow && (mode === "dataflow" || mode === "both")) {
    flowEdgeSet = new Set<string>();
    for (let i = 0; i < activeFlow.steps.length - 1; i++) {
      flowEdgeSet.add(`${activeFlow.steps[i]}->${activeFlow.steps[i + 1]}`);
    }
  }

  // Which edges to render
  let edgesToRender = graph.edges;
  if (mode === "dataflow" && flowEdgeSet) {
    edgesToRender = graph.edges.filter((e) =>
      flowEdgeSet!.has(`${e.from}->${e.to}`),
    );
  }

  // ---- build SVG parts -------------------------------------------------------

  const parts: string[] = [];

  // SVG header
  parts.push(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${canvasW}" height="${canvasH}" viewBox="0 0 ${canvasW} ${canvasH}" style="background:${C_BG};font-family:system-ui,sans-serif;">`,
  );

  // Defs: arrowhead markers
  parts.push(`<defs>`);
  // current edge marker (teal)
  parts.push(
    `<marker id="arr-current" markerWidth="${SVG_MARKER_SIZE}" markerHeight="${SVG_MARKER_SIZE}" refX="${SVG_MARKER_SIZE - 1}" refY="${SVG_MARKER_SIZE / 2}" orient="auto">` +
    `<path d="M0,0 L0,${SVG_MARKER_SIZE} L${SVG_MARKER_SIZE},${SVG_MARKER_SIZE / 2} Z" fill="${C_EDGE_CURRENT}"/>` +
    `</marker>`,
  );
  // planned edge marker (purple)
  parts.push(
    `<marker id="arr-planned" markerWidth="${SVG_MARKER_SIZE}" markerHeight="${SVG_MARKER_SIZE}" refX="${SVG_MARKER_SIZE - 1}" refY="${SVG_MARKER_SIZE / 2}" orient="auto">` +
    `<path d="M0,0 L0,${SVG_MARKER_SIZE} L${SVG_MARKER_SIZE},${SVG_MARKER_SIZE / 2} Z" fill="${C_EDGE_PLANNED}"/>` +
    `</marker>`,
  );
  // concern edge marker (red)
  parts.push(
    `<marker id="arr-concern" markerWidth="${SVG_MARKER_SIZE}" markerHeight="${SVG_MARKER_SIZE}" refX="${SVG_MARKER_SIZE - 1}" refY="${SVG_MARKER_SIZE / 2}" orient="auto">` +
    `<path d="M0,0 L0,${SVG_MARKER_SIZE} L${SVG_MARKER_SIZE},${SVG_MARKER_SIZE / 2} Z" fill="${C_CONCERN}"/>` +
    `</marker>`,
  );
  parts.push(`</defs>`);

  // Title bar
  parts.push(
    `<rect x="0" y="0" width="${canvasW}" height="${SVG_TITLE_H}" fill="${C_ACCENT}" rx="0"/>`,
  );
  parts.push(
    `<text x="20" y="30" font-size="18" font-weight="bold" fill="${C_NODE_FILL}">System Architecture</text>`,
  );
  parts.push(
    `<text x="20" y="48" font-size="10" fill="${C_NODE_FILL}" opacity="0.75">` +
    `mode: ${mode} · view: ${persona} · ${ts}` +
    `</text>`,
  );

  // Lane columns
  for (let li = 0; li < LANE_ORDER.length; li++) {
    const lane = LANE_ORDER[li];
    const laneLabel = LANE_LABELS[lane] ?? lane;
    const laneX = 20 + li * SVG_LANE_W;
    const laneH = canvasH - SVG_TITLE_H - SVG_LEGEND_H - 20;

    parts.push(
      `<rect x="${laneX}" y="${SVG_TITLE_H + 8}" width="${SVG_LANE_W - 8}" height="${laneH}" fill="${C_LANE_BG}" rx="${SVG_RADIUS}" stroke="${C_LANE_BORDER}" stroke-width="1"/>`,
    );
    // Lane label
    parts.push(
      `<text x="${laneX + (SVG_LANE_W - 8) / 2}" y="${SVG_TITLE_H + 28}" text-anchor="middle" font-size="10" font-weight="600" fill="${C_ACCENT}" letter-spacing="0.05em">${esc(laneLabel.toUpperCase())}</text>`,
    );
  }

  // Edges (drawn before nodes so nodes appear on top)
  for (const e of edgesToRender) {
    const x1 = nodeCX.get(e.from);
    const y1 = nodeCY.get(e.from);
    const x2 = nodeCX.get(e.to);
    const y2 = nodeCY.get(e.to);
    if (x1 === undefined || y1 === undefined || x2 === undefined || y2 === undefined)
      continue;

    const hasConcern =
      concernNodeIds.has(e.from) || concernNodeIds.has(e.to);
    const planned = isPlannedEdge(e);

    let stroke: string;
    let markerId: string;
    let dashArray: string;

    if (hasConcern) {
      stroke = C_CONCERN;
      markerId = "arr-concern";
      dashArray = "";
    } else if (planned) {
      stroke = C_EDGE_PLANNED;
      markerId = "arr-planned";
      dashArray = `stroke-dasharray="6 4"`;
    } else {
      stroke = C_EDGE_CURRENT;
      markerId = "arr-current";
      dashArray = "";
    }

    const edgeLabel =
      persona === "engineer"
        ? `${e.protocol}${e.label ? ` · ${e.label}` : ""}`
        : e.label || e.protocol;

    // Compute a slight curve via quadratic bezier
    const mx = (x1 + x2) / 2;
    const my = (y1 + y2) / 2 - 20;

    parts.push(
      `<path d="M${x1},${y1} Q${mx},${my} ${x2},${y2}" fill="none" stroke="${stroke}" stroke-width="1.5" ${dashArray} marker-end="url(#${markerId})" opacity="0.85"/>`,
    );

    // Edge label (mid-point)
    if (edgeLabel) {
      const lx = mx;
      const ly = my - 4;
      parts.push(
        `<rect x="${lx - 30}" y="${ly - 10}" width="60" height="13" rx="3" fill="${C_BG}" opacity="0.85"/>`,
      );
      parts.push(
        `<text x="${lx}" y="${ly}" text-anchor="middle" font-size="7" fill="#aaaacc">${esc(edgeLabel)}</text>`,
      );
    }
  }

  // Nodes
  for (let li = 0; li < LANE_ORDER.length; li++) {
    const lane = LANE_ORDER[li];
    const nodes = byLane.get(lane) ?? [];
    const laneX = 20 + li * SVG_LANE_W;

    for (let ni = 0; ni < nodes.length; ni++) {
      const n = nodes[ni];
      const nx = laneX + SVG_LANE_PAD_X;
      const ny =
        SVG_TITLE_H +
        SVG_LANE_PAD_Y +
        ni * (SVG_NODE_H + SVG_NODE_GAP);
      const hasConcern = concernNodeIds.has(n.id);
      const stroke = hasConcern ? C_CONCERN : C_LANE_BORDER;
      const strokeW = hasConcern ? 2 : 1;

      parts.push(
        `<rect x="${nx}" y="${ny}" width="${SVG_NODE_W}" height="${SVG_NODE_H}" rx="${SVG_RADIUS}" fill="${C_NODE_FILL}" stroke="${stroke}" stroke-width="${strokeW}"/>`,
      );
      // Node label (possibly with concern marker)
      const labelPrefix = hasConcern ? "⚠ " : "";
      parts.push(
        `<text x="${nx + SVG_NODE_W / 2}" y="${ny + 20}" text-anchor="middle" font-size="11" font-weight="600" fill="${C_NODE_TEXT}">${esc(labelPrefix + n.label)}</text>`,
      );
      // Node kind sub-label
      parts.push(
        `<text x="${nx + SVG_NODE_W / 2}" y="${ny + 35}" text-anchor="middle" font-size="9" fill="#8888bb">${esc(n.kind)}</text>`,
      );
      // Status dot
      const statusColor = n.status === "active" ? "#22c55e" : n.status === "planned" ? C_EDGE_PLANNED : "#888";
      parts.push(
        `<circle cx="${nx + SVG_NODE_W - 12}" cy="${ny + 12}" r="4" fill="${statusColor}"/>`,
      );
    }
  }

  // Legend box (bottom-left)
  const legY = canvasH - SVG_LEGEND_H - 10;
  const legX = 20;
  parts.push(
    `<rect x="${legX}" y="${legY}" width="${SVG_LEGEND_W}" height="${SVG_LEGEND_H}" rx="${SVG_RADIUS}" fill="${C_LANE_BG}" stroke="${C_LANE_BORDER}" stroke-width="1" opacity="0.97"/>`,
  );
  parts.push(
    `<text x="${legX + 10}" y="${legY + 18}" font-size="10" font-weight="700" fill="${C_ACCENT}">LEGEND</text>`,
  );
  // Current edge
  parts.push(`<line x1="${legX + 10}" y1="${legY + 32}" x2="${legX + 50}" y2="${legY + 32}" stroke="${C_EDGE_CURRENT}" stroke-width="2" marker-end="url(#arr-current)"/>`);
  parts.push(`<text x="${legX + 58}" y="${legY + 36}" font-size="9" fill="${C_NODE_TEXT}">Current / live integration</text>`);
  // Planned edge
  parts.push(`<line x1="${legX + 10}" y1="${legY + 50}" x2="${legX + 50}" y2="${legY + 50}" stroke="${C_EDGE_PLANNED}" stroke-width="2" stroke-dasharray="6 4" marker-end="url(#arr-planned)"/>`);
  parts.push(`<text x="${legX + 58}" y="${legY + 54}" font-size="9" fill="${C_NODE_TEXT}">Planned / agentic (not yet live)</text>`);
  // Concern edge
  parts.push(`<line x1="${legX + 10}" y1="${legY + 68}" x2="${legX + 50}" y2="${legY + 68}" stroke="${C_CONCERN}" stroke-width="2" marker-end="url(#arr-concern)"/>`);
  parts.push(`<text x="${legX + 58}" y="${legY + 72}" font-size="9" fill="${C_NODE_TEXT}">Integration with active concerns</text>`);
  // Concern node
  parts.push(`<rect x="${legX + 10}" y="${legY + 80}" width="34" height="16" rx="3" fill="${C_NODE_FILL}" stroke="${C_CONCERN}" stroke-width="2"/>`);
  parts.push(`<text x="${legX + 27}" y="${legY + 92}" text-anchor="middle" font-size="9" fill="${C_NODE_TEXT}">⚠ node</text>`);
  parts.push(`<text x="${legX + 58}" y="${legY + 92}" font-size="9" fill="${C_NODE_TEXT}">Node has active concerns</text>`);
  // Status dots
  parts.push(`<circle cx="${legX + 20}" cy="${legY + 106}" r="4" fill="#22c55e"/>`);
  parts.push(`<text x="${legX + 30}" y="${legY + 109}" font-size="9" fill="${C_NODE_TEXT}">active</text>`);
  parts.push(`<circle cx="${legX + 80}" cy="${legY + 106}" r="4" fill="${C_EDGE_PLANNED}"/>`);
  parts.push(`<text x="${legX + 90}" y="${legY + 109}" font-size="9" fill="${C_NODE_TEXT}">planned</text>`);

  parts.push(`</svg>`);

  return parts.join("\n");
}

// ---- downloadSvgAsPng -------------------------------------------------------

/**
 * Convert an SVG string to a PNG data URL via Image+canvas; triggers download.
 * Returns Promise<boolean> — false on failure.
 */
export async function downloadSvgAsPng(
  svg: string,
  filename: string,
): Promise<boolean> {
  try {
    // Parse width/height from the SVG root element
    const parser = new DOMParser();
    const doc = parser.parseFromString(svg, "image/svg+xml");
    const root = doc.documentElement;
    const w = parseInt(root.getAttribute("width") ?? "1400", 10);
    const h = parseInt(root.getAttribute("height") ?? "800", 10);

    const dataUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;

    const img = new Image();
    img.src = dataUrl;
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error("SVG image load failed"));
    });

    const canvas = document.createElement("canvas");
    // 2× for retina sharpness
    canvas.width = w * 2;
    canvas.height = h * 2;
    const ctx = canvas.getContext("2d");
    if (!ctx) return false;
    ctx.scale(2, 2);
    ctx.drawImage(img, 0, 0, w, h);

    const pngUrl = canvas.toDataURL("image/png");
    const a = document.createElement("a");
    a.href = pngUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    return true;
  } catch {
    return false;
  }
}

// ---- XML escape helper ------------------------------------------------------

function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
