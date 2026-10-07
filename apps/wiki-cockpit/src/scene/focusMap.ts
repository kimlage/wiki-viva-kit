import type { GraphEdge, GraphNode } from "../types";
import { contextStyle, pageTypeLabel } from "../data/presentation";

export const DEFAULT_FOCUS_NODE_BUDGET = 24;
export const MAX_FOCUS_NODE_BUDGET = 64;

export type FocusGraph = {
  nodes: readonly GraphNode[];
  edges: readonly GraphEdge[];
};

export type FocusMapOptions = {
  selectedId: string | null;
  expandedIds?: readonly string[];
  maxNodes?: number;
};

export type FocusMapNode = {
  id: string;
  /** The source record, never rewritten by the projection. */
  node: GraphNode;
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
  depth: number;
  isSelected: boolean;
  isExpanded: boolean;
  /** Distinct adjacent pages currently outside the displayed graph. */
  hiddenNeighborCount: number;
};

export type FocusMapEdge = {
  key: string;
  /** Includes the original direction, provenance and date, when supplied. */
  edge: GraphEdge;
  path: string;
  labelX: number;
  labelY: number;
  laneIndex: number;
  laneCount: number;
  /** null means the snapshot did not explicitly declare a known direction. */
  directed: boolean | null;
};

export type FocusMapCounts = {
  totalNodes: number;
  shownNodes: number;
  hiddenNodes: number;
  candidateNodes: number;
  hiddenCandidateNodes: number;
  outsideFocusNodes: number;
  totalEdges: number;
  shownEdges: number;
  hiddenEdges: number;
  candidateEdges: number;
  hiddenCandidateEdges: number;
  outsideFocusEdges: number;
  /** Records with at least one endpoint absent from graph.nodes. */
  unresolvedEdges: number;
};

export type FocusMap = {
  selectedId: string | null;
  expandedIds: string[];
  ignoredExpansionIds: string[];
  nodeBudget: number;
  nodes: FocusMapNode[];
  edges: FocusMapEdge[];
  counts: FocusMapCounts;
  bounds: { x: number; y: number; width: number; height: number };
};

export type FocusColorMode = "topic" | "category";
export type FocusColorToken = { key: string; label: string; color: string };

const CATEGORY_COLORS = ["#327ca0", "#965a73", "#996b24", "#596ba6", "#4c7d5b", "#87639e", "#996552", "#657782"] as const;
const TYPE_COLORS: Readonly<Record<string, string>> = {
  root_entity: "#216870",
  context_hub: "#607d6c",
  source: "#327ca0",
  person: "#965a73",
  action: "#996b24",
  claim: "#596ba6",
  decision: "#4c7d5b",
  artifact: "#996552",
  ingestion_event: "#87639e"
};

const compare = (left: string, right: string): number => left < right ? -1 : left > right ? 1 : 0;
const round = (value: number): number => Math.round(value * 1000) / 1000;
const uniqueSorted = (values: readonly string[]): string[] => [...new Set(values)].sort(compare);

function stableHash(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash = Math.imul(hash ^ value.charCodeAt(index), 16777619);
  }
  return hash >>> 0;
}

/** Identity colors depend on one declared field, never array order or state. */
export function focusColorToken(node: Pick<GraphNode, "context" | "page_type">, mode: FocusColorMode): FocusColorToken {
  const value = (mode === "topic" ? node.context : node.page_type).trim();
  const key = `${mode}:${value}`;
  if (mode === "topic") {
    const style = contextStyle(value);
    return { key, label: value ? style.label : "Unknown context", color: style.accent };
  }
  return {
    key,
    label: value ? pageTypeLabel(value) : "Unknown category",
    color: TYPE_COLORS[value] || CATEGORY_COLORS[stableHash(key) % CATEGORY_COLORS.length]
  };
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => compare(left, right));
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

export type KeyedEdge = { key: string; edge: GraphEdge };

export function keyEdges(edges: readonly GraphEdge[]): KeyedEdge[] {
  const records = edges.map((edge) => {
    const signature = canonicalJson(edge);
    const hasId = typeof edge.id === "string" && edge.id.length > 0;
    return { edge, signature, hasId, base: hasId ? `id:${encodeURIComponent(edge.id!)}` : `legacy:${encodeURIComponent(signature)}` };
  }).sort((left, right) => compare(left.base, right.base) || compare(left.signature, right.signature));
  const baseCounts = new Map<string, number>();
  records.forEach(({ base }) => baseCounts.set(base, (baseCounts.get(base) ?? 0) + 1));
  const occurrences = new Map<string, number>();
  return records.map(({ edge, signature, hasId, base }) => {
    const identity = canonicalJson([base, signature]);
    const occurrence = (occurrences.get(identity) ?? 0) + 1;
    occurrences.set(identity, occurrence);
    // Explicit unique IDs survive metadata updates. Equal legacy records are
    // indistinguishable, but their stable occurrence keys preserve multiplicity.
    const key = hasId && baseCounts.get(base) === 1
      ? base
      : `${base}${hasId ? `:${encodeURIComponent(signature)}` : ""}#${occurrence}`;
    return { key, edge };
  });
}

type Point = { x: number; y: number };
type RoutedEdge = FocusMapEdge & { extent: Point[] };

function boundary(node: FocusMapNode, toward: Point): Point {
  const dx = toward.x - node.x;
  const dy = toward.y - node.y;
  const scale = Math.min(
    dx === 0 ? Infinity : (node.width / 2 + 5) / Math.abs(dx),
    dy === 0 ? Infinity : (node.height / 2 + 5) / Math.abs(dy)
  );
  return { x: round(node.x + dx * scale), y: round(node.y + dy * scale) };
}

function routeEdges(records: KeyedEdge[], nodes: FocusMapNode[]): RoutedEdge[] {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const groups = new Map<string, KeyedEdge[]>();
  records.forEach((record) => {
    const pair = [record.edge.source, record.edge.target].sort(compare);
    const groupKey = canonicalJson(pair);
    groups.set(groupKey, [...(groups.get(groupKey) ?? []), record]);
  });
  const output: RoutedEdge[] = [];
  for (const group of groups.values()) {
    group.sort((left, right) => compare(left.edge.source, right.edge.source) || compare(left.edge.target, right.edge.target) || compare(left.key, right.key));
    group.forEach(({ key, edge }, laneIndex) => {
      const source = byId.get(edge.source)!;
      const target = byId.get(edge.target)!;
      const laneCount = group.length;
      const directed = edge.direction === "directed" ? true : edge.direction === "undirected" ? false : null;
      if (source.id === target.id) {
        const top = source.y - source.height / 2 - 5;
        const rise = 58 + laneIndex * 22;
        const spread = 34 + laneIndex * 12;
        const start = { x: source.x + source.width / 2 - 18, y: top };
        const end = { x: source.x - source.width / 2 + 18, y: top };
        const first = { x: source.x + source.width / 2 + spread, y: top - rise };
        const second = { x: source.x - source.width / 2 - spread, y: top - rise };
        output.push({ key, edge, laneIndex, laneCount, directed,
          path: `M ${start.x} ${start.y} C ${first.x} ${first.y} ${second.x} ${second.y} ${end.x} ${end.y}`,
          labelX: source.x, labelY: round(top - rise * 0.75), extent: [start, first, second, end] });
        return;
      }
      const [first, second] = compare(source.id, target.id) < 0 ? [source, target] : [target, source];
      const dx = second.x - first.x;
      const dy = second.y - first.y;
      const length = Math.hypot(dx, dy);
      const spacing = laneCount <= 9 ? 44 : 352 / (laneCount - 1);
      const offset = (laneIndex - (laneCount - 1) / 2) * spacing;
      // The normal uses the canonical pair order. A reciprocal edge therefore
      // occupies its own physical lane while still ending at its actual target.
      const control = {
        x: round((first.x + second.x) / 2 - dy / length * offset),
        y: round((first.y + second.y) / 2 + dx / length * offset)
      };
      const start = boundary(source, control);
      const end = boundary(target, control);
      // Reserve a conservative text width at 12px, including the label stroke.
      const narrowHorizontalGap = laneCount === 1 && source.y === target.y
        && Math.abs(end.x - start.x) < edge.type.length * 8 + 10;
      const labelY = narrowHorizontalGap
        ? Math.min(source.y - source.height / 2, target.y - target.height / 2) - 12
        : (start.y + 2 * control.y + end.y) / 4;
      output.push({ key, edge, laneIndex, laneCount, directed,
        path: `M ${start.x} ${start.y} Q ${control.x} ${control.y} ${end.x} ${end.y}`,
        labelX: round((start.x + 2 * control.x + end.x) / 4),
        labelY: round(labelY), extent: [start, control, end] });
    });
  }
  return output.sort((left, right) => compare(left.key, right.key));
}

/**
 * Read-only induced graph of the selection and its direct neighbors. An
 * expanded page exposes one additional adjacency step only if reachable via
 * already requested expansions. Node budgets hide pages deterministically;
 * every original relation whose two endpoints are displayed remains separate.
 */
export function buildFocusMap(graph: FocusGraph, options: FocusMapOptions): FocusMap {
  const orderedNodes = [...graph.nodes].sort((left, right) => compare(left.id, right.id));
  const byId = new Map(orderedNodes.map((node) => [node.id, node]));
  const selectedId = options.selectedId && byId.has(options.selectedId) ? options.selectedId : null;
  const requestedExpansions = uniqueSorted(options.expandedIds ?? []);
  const requested = new Set(requestedExpansions);
  const suppliedBudget = options.maxNodes ?? DEFAULT_FOCUS_NODE_BUDGET;
  const nodeBudget = Number.isFinite(suppliedBudget)
    ? Math.min(MAX_FOCUS_NODE_BUDGET, Math.max(1, Math.floor(suppliedBudget)))
    : DEFAULT_FOCUS_NODE_BUDGET;
  const validEdges = graph.edges.filter((edge) => byId.has(edge.source) && byId.has(edge.target));
  const adjacency = new Map(orderedNodes.map((node) => [node.id, new Set<string>()]));
  validEdges.forEach((edge) => {
    if (edge.source !== edge.target) {
      adjacency.get(edge.source)!.add(edge.target);
      adjacency.get(edge.target)!.add(edge.source);
    }
  });
  const depths = new Map<string, number>();
  const queue: string[] = [];
  const queued = new Set<string>();
  if (selectedId) {
    depths.set(selectedId, 0);
    queue.push(selectedId);
    queued.add(selectedId);
  }
  for (let index = 0; index < queue.length; index += 1) {
    const currentId = queue[index];
    const nextDepth = depths.get(currentId)! + 1;
    for (const neighborId of uniqueSorted([...adjacency.get(currentId)!])) {
      if (!depths.has(neighborId)) depths.set(neighborId, nextDepth);
      if (requested.has(neighborId) && !queued.has(neighborId)) {
        queue.push(neighborId);
        queued.add(neighborId);
      }
    }
  }
  const candidateIds = [...depths.keys()].sort((left, right) => depths.get(left)! - depths.get(right)! || compare(left, right));
  const shownIds = candidateIds.slice(0, nodeBudget);
  const shown = new Set(shownIds);
  const expandedIds = requestedExpansions.filter((id) => id !== selectedId && shown.has(id));
  const expanded = new Set(expandedIds);
  const ringIds = candidateIds.filter((id) => depths.get(id) === 1).slice(0, 10);
  const extraIds = candidateIds.filter((id) => id !== selectedId && !ringIds.includes(id));
  const nodes: FocusMapNode[] = shownIds.map((id) => {
    const node = byId.get(id)!;
    const isSelected = id === selectedId;
    const ringIndex = ringIds.indexOf(id);
    const extraIndex = extraIds.indexOf(id);
    const angle = -Math.PI / 2 + ringIndex * Math.PI * 2 / Math.max(1, ringIds.length);
    return {
      id, node, label: node.title.replace(/\s+/g, " ").trim() || id,
      x: isSelected ? 500 : ringIndex >= 0 ? round(500 + Math.cos(angle) * 350) : 152 + (extraIndex % 4) * 232,
      y: isSelected ? 340 : ringIndex >= 0 ? round(340 + Math.sin(angle) * 224) : 730 + Math.floor(extraIndex / 4) * 112,
      width: isSelected ? 208 : 190, height: isSelected ? 84 : 76,
      depth: depths.get(id)!, isSelected, isExpanded: isSelected || expanded.has(id),
      hiddenNeighborCount: [...adjacency.get(id)!].filter((neighborId) => !shown.has(neighborId)).length
    };
  });
  const candidateEdges = validEdges.filter((edge) => depths.has(edge.source) && depths.has(edge.target));
  // Key all records before filtering: legacy duplicate occurrence keys do not
  // depend on which focus or budget happens to be active.
  const records = keyEdges(graph.edges).filter(({ edge }) => shown.has(edge.source) && shown.has(edge.target));
  const routed = routeEdges(records, nodes);
  const extent = [
    { x: 32, y: 32 }, { x: 968, y: 648 },
    ...nodes.flatMap((node) => [
      { x: node.x - node.width / 2, y: node.y - node.height / 2 },
      { x: node.x + node.width / 2, y: node.y + node.height / 2 }
    ]),
    ...routed.flatMap((edge) => edge.extent)
  ];
  const minX = Math.floor(Math.min(...extent.map((point) => point.x)) - 32);
  const minY = Math.floor(Math.min(...extent.map((point) => point.y)) - 32);
  const maxX = Math.ceil(Math.max(...extent.map((point) => point.x)) + 32);
  const maxY = Math.ceil(Math.max(...extent.map((point) => point.y)) + 32);
  const unresolvedEdges = graph.edges.length - validEdges.length;
  return {
    selectedId, expandedIds,
    ignoredExpansionIds: requestedExpansions.filter((id) => !depths.has(id)),
    nodeBudget, nodes, edges: routed.map(({ extent: _extent, ...edge }) => edge),
    counts: {
      totalNodes: byId.size, shownNodes: nodes.length, hiddenNodes: byId.size - nodes.length,
      candidateNodes: candidateIds.length, hiddenCandidateNodes: candidateIds.length - nodes.length,
      outsideFocusNodes: byId.size - candidateIds.length,
      totalEdges: graph.edges.length, shownEdges: routed.length, hiddenEdges: graph.edges.length - routed.length,
      candidateEdges: candidateEdges.length, hiddenCandidateEdges: candidateEdges.length - routed.length,
      outsideFocusEdges: graph.edges.length - candidateEdges.length - unresolvedEdges, unresolvedEdges
    },
    bounds: { x: minX, y: minY, width: maxX - minX, height: maxY - minY }
  };
}
