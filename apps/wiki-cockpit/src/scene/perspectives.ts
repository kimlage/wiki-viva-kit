// Perspective engine: pure, deterministic, worker-computable layouts.
//
// The same node identities are re-arranged by four perspectives — radar
// (verification), atlas (hierarchy), districts (taxonomy), trails (relations)
// — across drill levels (galaxy → context → group → page). Every layout obeys
// the honest-encoding contract: hue = context, tone = state (aging), shape =
// kind, line = relation,
// and no visual implies data that does not exist. The per-level node cap keeps
// draw calls bounded while cluster-stars carry the TRUE hidden counts, so all
// pages stay countable and one drill away.

import type { GraphEdge, GraphNode } from "../types";
import { pageTypeStyle } from "../data/presentation";
import { QUADRANT_CENTER_ANGLE, SCENE_FACETS, homeQuadrant, sceneFacetOf, type SceneFacet } from "./facets";
import type { GalaxyLayout, LayoutNode, LayoutWedge } from "./layout";
import {
  DEADLINE_F,
  UNKNOWN_F,
  allocateWedgeSpans,
  computeGalaxyLayout,
  freshnessFraction,
  nodeWeight,
  parseDateMs,
  rootNodeId,
  snapshotClock,
  staleBudgetDays
} from "./layout";

export type PerspectiveId = "radar" | "atlas" | "districts" | "trails" | "focus" | "quadrants";

// The 1–5 keys cycle these five (radar stays 1 and the default); `focus` is
// page-triggered (a locked page through the four lenses), never a bare-key
// perspective. `quadrants` (key 5) is the AQAL home map — where everything lives.
export const PERSPECTIVE_ORDER: PerspectiveId[] = ["radar", "atlas", "districts", "trails", "quadrants"];

export type GroupKind = "context" | "attention" | "page_type" | "hub" | "orphan" | "relation" | "facet" | "quadrant" | "core";

export type WorldGroup = {
  key: string;
  kind: GroupKind;
  labelKey: string;
  count: number;
  shown: number;
  anchor: [number, number, number];
  drill: { context?: string; group?: string } | null;
  memberIds: string[];
};

export type ClusterStar = {
  key: string;
  kind: GroupKind;
  labelKey: string;
  count: number;
  position: [number, number, number];
  scale: number;
  histogram: { fresh: number; stale: number; unknown: number; proposal: number; risk: number };
  // null = nothing deeper to open — the star reveals in place instead.
  drill: { context?: string; group?: string } | null;
};

export type Beacon = {
  context: string;
  position: [number, number, number];
  count: number;
  attentionCount: number;
};

export type WorldGuide =
  | { kind: "circle"; radius: number; color: string; opacity: number; dashed?: boolean }
  | { kind: "arc"; radius: number; start: number; end: number; color: string; opacity: number }
  | { kind: "ray"; angle: number; r0: number; r1: number; color: string; opacity: number };

export type WorldRequest = {
  perspective: PerspectiveId;
  context?: string;
  group?: string;
  pageId?: string;
  // The active quadrant (Quadrants perspective) — sets the camera fly-to target;
  // it does NOT scope the home map (all four regions stay shown).
  quadrant?: SceneFacet;
  nodes: GraphNode[];
  edges: GraphEdge[];
  maxNodes: number;
  snapshotAt?: string;
};

export type WorldLayout = {
  perspective: PerspectiveId;
  level: number;
  context?: string;
  group?: string;
  // What radius means in this layout — the scene only draws the freshness
  // deadline and the "sem dados" band when radius really encodes freshness.
  radial: "freshness" | "shelf" | "orbit" | "ego";
  nodes: LayoutNode[];
  wedges: LayoutWedge[];
  wedgeKind: "context" | "group";
  guides: WorldGuide[];
  groups: WorldGroup[];
  clusterStars: ClusterStar[];
  beacons: Beacon[];
  rInner: number;
  rOuter: number;
  deadlineF: number;
  unknownR: number | null;
  totals: { total: number; shown: number; hidden: number };
  truncated: number;
  // Optional camera fly-to target (region centroid) for perspectives that carry
  // a sub-focus, e.g. the active quadrant.
  cameraTarget?: [number, number, number];
};

const GUIDE_COLOR = "#22303a";

// ---------------------------------------------------------------------------
// Shared helpers

function stableHash(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) / 4294967296;
}

function sanitizeSegment(segment: string): string {
  return segment
    .toLowerCase()
    .replace(/\.md$/, "")
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// Atlas group keys are hierarchical: the FULL path (or page id) is encoded,
// segments joined by "~", trailing "index" dropped. This keeps sibling
// `folder/index.md` hubs distinguishable — a basename-only slug collapsed
// every hub to "index" and made nested drills silently no-op.
export function atlasKeyFromRef(ref: string): string {
  const segments = ref.split("/").map(sanitizeSegment).filter(Boolean);
  if (segments.length > 1 && segments[segments.length - 1] === "index") segments.pop();
  return segments.join("~") || "sem-pai";
}

export function slugify(value: string): string {
  return (
    value
      .toLowerCase()
      .replace(/\.md$/, "")
      .split("/")
      .filter(Boolean)
      .pop() || value.toLowerCase()
  )
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function contextOf(node: GraphNode): string {
  return node.context || "system";
}

function isAttention(node: GraphNode): boolean {
  return node.freshness_state === "stale" || node.approved_state === "proposal" || node.risk_flags.length > 0;
}

function attentionFirst(a: GraphNode, b: GraphNode): number {
  return (
    Number(isAttention(b)) - Number(isAttention(a)) ||
    nodeWeight(b) - nodeWeight(a) ||
    a.title.localeCompare(b.title) ||
    a.id.localeCompare(b.id)
  );
}

function histogram(nodes: GraphNode[]): ClusterStar["histogram"] {
  return {
    fresh: nodes.filter((node) => node.freshness_state === "fresh").length,
    stale: nodes.filter((node) => node.freshness_state === "stale").length,
    unknown: nodes.filter((node) => node.freshness_state === "unknown").length,
    proposal: nodes.filter((node) => node.approved_state === "proposal").length,
    risk: nodes.filter((node) => node.risk_flags.length > 0).length
  };
}

function makeNode(
  node: GraphNode,
  snapshotMs: number,
  position: [number, number, number],
  scale: number,
  options: { isHub?: boolean; isRoot?: boolean; ring?: number; faint?: boolean } = {}
): LayoutNode {
  const updatedMs = parseDateMs(node.updated_at ?? "");
  const ageDays = updatedMs === null ? 0 : Math.max(0, (snapshotMs - updatedMs) / 86400000);
  const overdueRatio = updatedMs === null ? 0 : ageDays / staleBudgetDays(node);
  return {
    id: node.id,
    path: node.path,
    title: node.title,
    context: node.context,
    page_type: node.page_type,
    freshness_state: node.freshness_state,
    approved_state: node.approved_state,
    risk_flags: node.risk_flags,
    source_ref_count: node.metrics.source_ref_count,
    inbound_links: node.metrics.inbound_links,
    outbound_links: node.metrics.outbound_links,
    ageDays: Number(ageDays.toFixed(2)),
    overdueRatio: Number(overdueRatio.toFixed(4)),
    isHub: Boolean(options.isHub),
    isRoot: Boolean(options.isRoot),
    position: [Number(position[0].toFixed(4)), Number(position[1].toFixed(4)), Number(position[2].toFixed(4))],
    scale: Number(scale.toFixed(4)),
    ...(options.ring !== undefined ? { ring: options.ring } : {}),
    ...(options.faint ? { faint: true } : {})
  };
}

function nodeScale(node: GraphNode): number {
  return Math.min(0.11 + 0.05 * Math.sqrt(Math.min(node.metrics.inbound_links, 16)), 0.31);
}

function starFor(
  key: string,
  kind: GroupKind,
  labelKey: string,
  hidden: GraphNode[],
  position: [number, number, number],
  drill: ClusterStar["drill"]
): ClusterStar {
  return {
    key,
    kind,
    labelKey,
    count: hidden.length,
    position: [Number(position[0].toFixed(4)), Number(position[1].toFixed(4)), Number(position[2].toFixed(4))],
    // A cluster-star is an aggregate marker, not a planet: a log curve for
    // gentle magnitude separation, capped BELOW the largest real node (0.31)
    // so hidden-count markers never dwarf actual pages at scale.
    scale: Number(Math.min(0.16 + Math.log2(hidden.length + 1) * 0.02, 0.26).toFixed(4)),
    histogram: histogram(hidden),
    drill
  };
}

// Budget split across groups proportionally to their true size, each group
// keeping at least one visible slot so no group ever disappears.
function splitBudget(groups: { key: string; size: number }[], budget: number): Map<string, number> {
  const out = new Map<string, number>();
  if (groups.length === 0) return out;
  const total = groups.reduce((sum, group) => sum + group.size, 0) || 1;
  const ordered = [...groups].sort((a, b) => b.size - a.size || a.key.localeCompare(b.key));
  let used = 0;
  ordered.forEach((group) => {
    const share = Math.max(1, Math.floor((budget * group.size) / total));
    out.set(group.key, share);
    used += share;
  });
  // Distribute leftovers to the largest groups deterministically.
  let index = 0;
  while (used < budget && ordered.length > 0) {
    const group = ordered[index % ordered.length];
    if ((out.get(group.key) ?? 0) < group.size) {
      out.set(group.key, (out.get(group.key) ?? 0) + 1);
      used += 1;
    }
    index += 1;
    if (index > budget * 2 + ordered.length) break;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Group keys per perspective: the URL :group segment. Deterministic and
// derivable from the page record alone so search/wiki-links can auto-drill.

export function groupKeyForPage(
  perspective: PerspectiveId,
  page: { moc_parent?: string; page_type: string; freshness_state: string; approved_state?: string; risk_flags?: string[] }
): string | undefined {
  if (perspective === "trails") return undefined;
  if (perspective === "districts") return page.page_type || "content";
  if (perspective === "atlas") return page.moc_parent ? atlasKeyFromRef(page.moc_parent) : "sem-pai";
  const attention =
    page.freshness_state === "stale" || page.approved_state === "proposal" || (page.risk_flags?.length ?? 0) > 0;
  return attention ? "atencao" : page.page_type || "content";
}

function radarGroupKey(node: GraphNode): string {
  return isAttention(node) ? "atencao" : node.page_type || "content";
}

// ---------------------------------------------------------------------------
// Radar — the freshness perspective (L0 delegates to the galaxy layout).

function radarGalaxy(request: WorldRequest): WorldLayout {
  const layout: GalaxyLayout = computeGalaxyLayout(request.nodes, request.maxNodes, request.snapshotAt);
  const clusterStars: ClusterStar[] = [];
  const groups: WorldGroup[] = layout.wedges.map((wedge) => {
    const all = request.nodes.filter((node) => contextOf(node) === wedge.context);
    const shownIds = new Set(layout.nodes.filter((node) => (node.context || "system") === wedge.context).map((n) => n.id));
    const hidden = all.filter((node) => !shownIds.has(node.id));
    if (hidden.length > 0) {
      clusterStars.push(
        starFor(
          `star-${wedge.context}`,
          "context",
          wedge.context,
          hidden,
          [
            Math.cos(wedge.centerAngle) * (layout.rOuter - 0.3),
            0,
            Math.sin(wedge.centerAngle) * (layout.rOuter - 0.3)
          ],
          { context: wedge.context }
        )
      );
    }
    return {
      key: wedge.context,
      kind: "context" as const,
      labelKey: wedge.context,
      count: wedge.count,
      shown: wedge.shown,
      anchor: wedge.rimPosition,
      drill: { context: wedge.context },
      memberIds: layout.nodes
        .filter((node) => (node.context || "system") === wedge.context)
        .sort((a, b) => a.title.localeCompare(b.title) || a.id.localeCompare(b.id))
        .map((node) => node.id)
    };
  });
  return {
    perspective: "radar",
    level: 0,
    radial: "freshness",
    nodes: layout.nodes,
    wedges: layout.wedges,
    wedgeKind: "context",
    guides: [],
    groups,
    clusterStars,
    beacons: [],
    rInner: layout.rInner,
    rOuter: layout.rOuter,
    deadlineF: layout.deadlineF,
    unknownR: layout.unknownR,
    totals: layout.totals,
    truncated: layout.truncated
  };
}

function horizonBeacons(request: WorldRequest, rOuter: number, activeContext: string): Beacon[] {
  const others = [...new Set(request.nodes.map(contextOf))].filter((context) => context !== activeContext).sort();
  return others.map((context, index) => {
    const angle = 0.35 + ((index + 0.5) / others.length) * Math.PI * 2;
    const members = request.nodes.filter((node) => contextOf(node) === context);
    return {
      context,
      position: [Math.cos(angle) * (rOuter + 1.7), 0.4, Math.sin(angle) * (rOuter + 1.7)] as [number, number, number],
      count: members.length,
      attentionCount: members.filter(isAttention).length
    };
  });
}

// A generic single-circle radar over an arbitrary grouping. Radius keeps the
// freshness semantics; wedges become the grouping sectors.
function groupedRadar(
  request: WorldRequest,
  scoped: GraphNode[],
  groupOf: (node: GraphNode) => string,
  groupKind: GroupKind,
  level: number,
  drillFor: (groupKey: string) => { context?: string; group?: string } | null,
  radiusFor?: (node: GraphNode, snapshotMs: number) => number
): WorldLayout {
  const snapshotMs = snapshotClock(scoped, request.snapshotAt);
  const total = scoped.length;
  const byGroup = new Map<string, GraphNode[]>();
  scoped.forEach((node) => {
    const key = groupOf(node);
    const list = byGroup.get(key) ?? [];
    list.push(node);
    byGroup.set(key, list);
  });
  const groupKeys = [...byGroup.keys()].sort();
  const budget = splitBudget(
    groupKeys.map((key) => ({ key, size: byGroup.get(key)?.length ?? 0 })),
    Math.max(request.maxNodes - 1, 8)
  );
  const rOuter = Math.min(4.2 + Math.sqrt(Math.max(Math.min(total, request.maxNodes) - 24, 0)) * 0.12, 6.5);
  const rInner = 1.6;
  const band = rOuter - rInner;
  const spans = allocateWedgeSpans(groupKeys.map((key) => ({ key, weight: byGroup.get(key)?.length ?? 0 })));
  const spanByKey = new Map(spans.map((span) => [span.key, span]));

  const nodes: LayoutNode[] = [];
  const clusterStars: ClusterStar[] = [];
  const wedges: LayoutWedge[] = [];
  const groups: WorldGroup[] = [];

  groupKeys.forEach((key) => {
    const span = spanByKey.get(key);
    if (!span) return;
    const members = [...(byGroup.get(key) ?? [])].sort(attentionFirst);
    const visible = members.slice(0, budget.get(key) ?? members.length);
    const hidden = members.slice(visible.length);
    const usable = Math.max(span.endAngle - span.startAngle - 0.08, 0.05);
    const sorted = [...visible].sort(
      (a, b) =>
        pageTypeStyle(a.page_type).family.localeCompare(pageTypeStyle(b.page_type).family) ||
        a.title.localeCompare(b.title) ||
        a.id.localeCompare(b.id)
    );
    sorted.forEach((node, index) => {
      const updatedMs = parseDateMs(node.updated_at ?? "");
      const ageDays = updatedMs === null ? null : Math.max(0, (snapshotMs - updatedMs) / 86400000);
      const fraction = radiusFor ? radiusFor(node, snapshotMs) : freshnessFraction(node, ageDays);
      const radius = rInner + fraction * band;
      const t = (index + 0.5) / sorted.length;
      const jitter = (stableHash(node.id) - 0.5) * (usable / Math.max(sorted.length, 6)) * 0.8;
      const angle = span.startAngle + 0.04 + t * usable + jitter;
      const y = node.approved_state === "proposal" ? 0.5 : 0;
      nodes.push(makeNode(node, snapshotMs, [Math.cos(angle) * radius, y, Math.sin(angle) * radius], nodeScale(node)));
    });
    if (hidden.length > 0) {
      clusterStars.push(
        starFor(
          `star-${key}`,
          groupKind,
          key,
          hidden,
          [Math.cos(span.centerAngle) * (rOuter - 0.3), 0, Math.sin(span.centerAngle) * (rOuter - 0.3)],
          drillFor(key)
        )
      );
    }
    const rim: [number, number, number] = [
      Math.cos(span.centerAngle) * (rOuter + 0.45),
      0.05,
      Math.sin(span.centerAngle) * (rOuter + 0.45)
    ];
    wedges.push({
      context: key,
      startAngle: span.startAngle,
      endAngle: span.endAngle,
      centerAngle: span.centerAngle,
      count: members.length,
      shown: visible.length,
      freshCount: members.filter((node) => node.freshness_state === "fresh").length,
      staleCount: members.filter((node) => node.freshness_state === "stale").length,
      unknownCount: members.filter((node) => node.freshness_state === "unknown").length,
      proposalCount: members.filter((node) => node.approved_state === "proposal").length,
      riskCount: members.filter((node) => node.risk_flags.length > 0).length,
      rimPosition: rim
    });
    groups.push({
      key,
      kind: groupKind,
      labelKey: key,
      count: members.length,
      shown: visible.length,
      anchor: rim,
      drill: drillFor(key),
      memberIds: sorted.map((node) => node.id)
    });
  });

  const shown = nodes.length;
  return {
    perspective: request.perspective,
    level,
    context: request.context,
    group: request.group,
    radial: "freshness",
    nodes,
    wedges,
    wedgeKind: groupKind === "context" ? "context" : "group",
    guides: [],
    groups,
    clusterStars,
    beacons: request.context ? horizonBeacons(request, rOuter, request.context) : [],
    rInner,
    rOuter,
    deadlineF: DEADLINE_F,
    unknownR: rInner + band * UNKNOWN_F,
    totals: { total, shown, hidden: total - shown },
    truncated: total - shown
  };
}

function radarLayout(request: WorldRequest): WorldLayout {
  if (!request.context) return radarGalaxy(request);
  const scoped = request.nodes.filter((node) => contextOf(node) === request.context);
  if (request.group) {
    const members = scoped.filter((node) => radarGroupKey(node) === request.group);
    return groupedRadar(request, members, radarGroupKey, "attention", 2, () => null);
  }
  return groupedRadar(request, scoped, radarGroupKey, "attention", 1, (key) => ({
    context: request.context,
    group: key
  }));
}

// ---------------------------------------------------------------------------
// Atlas — orbit-of-orbits over the moc_parent hierarchy.

type AtlasIndex = {
  childrenOf: Map<string, GraphNode[]>;
  parentOf: Map<string, string>;
  subtreeSize: Map<string, number>;
  byId: Map<string, GraphNode>;
};

function buildAtlasIndex(nodes: GraphNode[], edges: GraphEdge[]): AtlasIndex {
  const byId = new Map<string, GraphNode>();
  nodes.forEach((node) => {
    byId.set(node.id, node);
    byId.set(node.path, node);
  });
  const parentOf = new Map<string, string>();
  edges.forEach((edge) => {
    if (edge.type !== "moc_parent") return;
    const child = byId.get(edge.source);
    const parent = byId.get(edge.target);
    if (!child || !parent || child.id === parent.id) return;
    parentOf.set(child.id, parent.id);
  });
  // Cycle guard: walk up from every node; break the edge that closes a loop.
  parentOf.forEach((_, childId) => {
    const seen = new Set<string>([childId]);
    let cursor = parentOf.get(childId);
    while (cursor) {
      if (seen.has(cursor)) {
        parentOf.delete(childId);
        break;
      }
      seen.add(cursor);
      cursor = parentOf.get(cursor);
    }
  });
  const childrenOf = new Map<string, GraphNode[]>();
  parentOf.forEach((parentId, childId) => {
    const child = byId.get(childId);
    if (!child) return;
    const list = childrenOf.get(parentId) ?? [];
    list.push(child);
    childrenOf.set(parentId, list);
  });
  childrenOf.forEach((list) => list.sort((a, b) => a.title.localeCompare(b.title) || a.id.localeCompare(b.id)));
  const subtreeSize = new Map<string, number>();
  const sizeOf = (id: string, guard: Set<string>): number => {
    if (subtreeSize.has(id)) return subtreeSize.get(id) ?? 1;
    if (guard.has(id)) return 1;
    guard.add(id);
    const children = childrenOf.get(id) ?? [];
    const size = 1 + children.reduce((sum, child) => sum + sizeOf(child.id, guard), 0);
    subtreeSize.set(id, size);
    return size;
  };
  nodes.forEach((node) => sizeOf(node.id, new Set()));
  return { childrenOf, parentOf, subtreeSize, byId };
}

function atlasRootFor(request: WorldRequest, index: AtlasIndex): GraphNode | null {
  const inContext = (node: GraphNode) => !request.context || contextOf(node) === request.context;
  if (request.group && request.context) {
    const candidates = request.nodes
      .filter(
        (node) =>
          inContext(node) &&
          (atlasKeyFromRef(node.path) === request.group || atlasKeyFromRef(node.id) === request.group)
      )
      .sort((a, b) => (index.subtreeSize.get(b.id) ?? 0) - (index.subtreeSize.get(a.id) ?? 0) || a.id.localeCompare(b.id));
    if (candidates[0]) return candidates[0];
  }
  if (request.context) {
    const hubs = request.nodes
      .filter((node) => contextOf(node) === request.context && node.page_type === "context_hub")
      .sort((a, b) => a.path.length - b.path.length || a.id.localeCompare(b.id));
    if (hubs[0]) return hubs[0];
    const biggest = request.nodes
      .filter((node) => contextOf(node) === request.context)
      .sort((a, b) => (index.subtreeSize.get(b.id) ?? 0) - (index.subtreeSize.get(a.id) ?? 0) || a.id.localeCompare(b.id));
    return biggest[0] ?? null;
  }
  const rootId = rootNodeId(request.nodes);
  if (rootId && index.byId.has(rootId)) return index.byId.get(rootId) ?? null;
  // No typed root: orbit the best-connected node instead of an empty world.
  return (
    [...request.nodes].sort(
      (a, b) =>
        (index.subtreeSize.get(b.id) ?? 0) - (index.subtreeSize.get(a.id) ?? 0) ||
        b.metrics.inbound_links - a.metrics.inbound_links ||
        a.id.localeCompare(b.id)
    )[0] ?? null
  );
}

function atlasLayout(request: WorldRequest): WorldLayout {
  const snapshotMs = snapshotClock(request.nodes, request.snapshotAt);
  const index = buildAtlasIndex(request.nodes, request.edges);
  const root = atlasRootFor(request, index);
  const level = request.group ? 2 : request.context ? 1 : 0;
  const scoped = request.context
    ? request.nodes.filter((node) => contextOf(node) === request.context)
    : request.nodes;
  const total = scoped.length;

  const nodes: LayoutNode[] = [];
  const clusterStars: ClusterStar[] = [];
  const groups: WorldGroup[] = [];
  const guides: WorldGuide[] = [];

  const r1 = 2.7;
  const r2 = 4.6;
  const rOuter = r2 + 0.6;
  guides.push({ kind: "circle", radius: r1, color: GUIDE_COLOR, opacity: 0.3 });
  guides.push({ kind: "circle", radius: r2, color: GUIDE_COLOR, opacity: 0.22 });

  if (!root) {
    return {
      perspective: "atlas",
      level,
      context: request.context,
      group: request.group,
      radial: "orbit",
      nodes,
      wedges: [],
      wedgeKind: "group",
      guides,
      groups,
      clusterStars,
      beacons: [],
      rInner: r1,
      rOuter,
      deadlineF: DEADLINE_F,
      unknownR: null,
      totals: { total, shown: 0, hidden: total },
      truncated: total
    };
  }

  nodes.push(makeNode(root, snapshotMs, [0, 0, 0], 0.42, { isHub: true, isRoot: true, ring: 0 }));

  // Ring 1: the drill root's children. At L0 the "children" of the wiki root
  // are the context hubs (or the root's moc children when typed).
  let ring1: GraphNode[];
  const orphans: GraphNode[] = [];
  if (level === 0) {
    // Every context appears on ring 1 — a context without a typed hub is
    // represented by its best-connected page, never dropped from the map.
    const contexts = [...new Set(request.nodes.map(contextOf))].sort();
    ring1 = contexts
      .map((context) => {
        const members = request.nodes.filter((node) => contextOf(node) === context && node.id !== root.id);
        const hub = members
          .filter((node) => node.page_type === "context_hub")
          .sort((a, b) => a.path.length - b.path.length || a.id.localeCompare(b.id))[0];
        if (hub) return hub;
        return [...members].sort(
          (a, b) =>
            (index.subtreeSize.get(b.id) ?? 0) - (index.subtreeSize.get(a.id) ?? 0) ||
            b.metrics.inbound_links - a.metrics.inbound_links ||
            a.id.localeCompare(b.id)
        )[0] ?? null;
      })
      .filter((node): node is GraphNode => Boolean(node));
  } else {
    ring1 = (index.childrenOf.get(root.id) ?? []).filter((node) => contextOf(node) === request.context);
    // The visible "sem pai" bucket exists at the context level and at its own
    // group level — never hidden, never leaking into other groups' L2.
    const includeOrphans = level === 1 || request.group === "sem-pai";
    if (includeOrphans) {
      // Orphans bring their whole subtree: a page whose parent chain never
      // reaches the drill root must still be browsable and counted.
      const seen = new Set<string>();
      scoped
        .filter((node) => node.id !== root.id && !index.parentOf.has(node.id))
        .forEach((orphanRoot) => {
          const queue: GraphNode[] = [orphanRoot];
          while (queue.length > 0) {
            const next = queue.shift()!;
            if (seen.has(next.id) || next.id === root.id) continue;
            seen.add(next.id);
            if (!request.context || contextOf(next) === request.context) orphans.push(next);
            queue.push(...(index.childrenOf.get(next.id) ?? []));
          }
        });
    }
  }

  const ring1Weight = (hub: GraphNode) =>
    level === 0
      ? request.nodes.filter((node) => contextOf(node) === contextOf(hub)).length
      : index.subtreeSize.get(hub.id) ?? 1;

  const entries = ring1.map((hub) => ({ key: hub.id, weight: ring1Weight(hub) }));
  if (orphans.length > 0) entries.push({ key: "__orphans__", weight: orphans.length });
  const spans = allocateWedgeSpans(entries);
  const spanByKey = new Map(spans.map((span) => [span.key, span]));

  // Budget: root + ring1 always shown; ring2 fills the rest.
  const ring2Budget = Math.max(request.maxNodes - 1 - ring1.length - Math.min(orphans.length, 24), 0);
  const ring2Sizes = ring1.map((hub) => ({
    key: hub.id,
    size:
      level === 0
        ? Math.max(request.nodes.filter((node) => contextOf(node) === contextOf(hub)).length - 1, 0)
        : (index.subtreeSize.get(hub.id) ?? 1) - 1
  }));
  const ring2Split = splitBudget(ring2Sizes.filter((entry) => entry.size > 0), ring2Budget);

  ring1.forEach((hub) => {
    const span = spanByKey.get(hub.id);
    if (!span) return;
    const hubPos: [number, number, number] = [Math.cos(span.centerAngle) * r1, 0, Math.sin(span.centerAngle) * r1];
    nodes.push(makeNode(hub, snapshotMs, hubPos, 0.3, { isHub: true, ring: 1 }));

    const descendants =
      level === 0
        ? request.nodes
            .filter((node) => contextOf(node) === contextOf(hub) && node.id !== hub.id && node.id !== root.id)
            .sort(attentionFirst)
        : ((): GraphNode[] => {
            // Full subtree, breadth-first, attention first inside each rank.
            const out: GraphNode[] = [];
            const queue = [...(index.childrenOf.get(hub.id) ?? [])];
            const seen = new Set<string>([hub.id]);
            while (queue.length > 0) {
              const next = queue.shift()!;
              if (seen.has(next.id)) continue;
              seen.add(next.id);
              out.push(next);
              queue.push(...(index.childrenOf.get(next.id) ?? []));
            }
            return out.sort(attentionFirst);
          })();

    const allowance = ring2Split.get(hub.id) ?? 0;
    const visible = descendants.slice(0, allowance);
    const hidden = descendants.slice(visible.length);
    const usable = Math.max(span.endAngle - span.startAngle - 0.1, 0.06);
    const sorted = [...visible].sort((a, b) => a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
    sorted.forEach((node, indexInGroup) => {
      const depth = index.parentOf.get(node.id) === hub.id || level === 0 ? 0 : 1;
      const radius = r2 + depth * 0.7;
      const t = (indexInGroup + 0.5) / sorted.length;
      const angle = span.startAngle + 0.05 + t * usable;
      const y = node.approved_state === "proposal" ? 0.5 : 0;
      nodes.push(
        makeNode(node, snapshotMs, [Math.cos(angle) * radius, y, Math.sin(angle) * radius], nodeScale(node), {
          ring: 2,
          faint: depth > 0
        })
      );
    });
    const hubKey = atlasKeyFromRef(hub.path);
    // Drilling to the level we are already on is not a drill — those stars
    // reveal locally instead of navigating.
    const hubDrill =
      level === 0
        ? { context: contextOf(hub) }
        : hubKey === request.group
          ? null
          : { context: request.context, group: hubKey };
    if (hidden.length > 0) {
      clusterStars.push(
        starFor(
          `star-${hub.id}`,
          "hub",
          hub.title,
          hidden,
          [Math.cos(span.centerAngle) * (r2 + 0.35), 0, Math.sin(span.centerAngle) * (r2 + 0.35)],
          hubDrill
        )
      );
    }
    const memberIds = [hub.id, ...sorted.map((node) => node.id)];
    groups.push({
      key: level === 0 ? contextOf(hub) : hubKey,
      kind: level === 0 ? "context" : "hub",
      labelKey: level === 0 ? contextOf(hub) : hub.title,
      count: descendants.length + 1,
      shown: visible.length + 1,
      anchor: [Math.cos(span.centerAngle) * (rOuter + 0.35), 0.05, Math.sin(span.centerAngle) * (rOuter + 0.35)],
      drill: hubDrill,
      memberIds
    });
    guides.push({
      kind: "arc",
      radius: r1,
      start: span.startAngle + 0.02,
      end: span.endAngle - 0.02,
      color: GUIDE_COLOR,
      opacity: 0.4
    });
  });

  if (orphans.length > 0) {
    const span = spanByKey.get("__orphans__");
    if (span) {
      const sorted = [...orphans].sort(attentionFirst);
      const orphanBudget = request.group === "sem-pai" ? Math.max(request.maxNodes - nodes.length, 24) : 24;
      const visible = sorted.slice(0, Math.min(orphanBudget, sorted.length));
      const hidden = sorted.slice(visible.length);
      const usable = Math.max(span.endAngle - span.startAngle - 0.1, 0.06);
      const stable = [...visible].sort((a, b) => a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
      stable.forEach((node, indexInGroup) => {
        const t = (indexInGroup + 0.5) / stable.length;
        const angle = span.startAngle + 0.05 + t * usable;
        const y = node.approved_state === "proposal" ? 0.5 : 0;
        nodes.push(makeNode(node, snapshotMs, [Math.cos(angle) * r2, y, Math.sin(angle) * r2], nodeScale(node), { ring: 2 }));
      });
      if (hidden.length > 0) {
        clusterStars.push(
          starFor(
            "star-sem-pai",
            "orphan",
            "sem-pai",
            hidden,
            [Math.cos(span.centerAngle) * (r2 + 0.35), 0, Math.sin(span.centerAngle) * (r2 + 0.35)],
            request.group === "sem-pai" ? null : { context: request.context, group: "sem-pai" }
          )
        );
      }
      groups.push({
        key: "sem-pai",
        kind: "orphan",
        labelKey: "sem-pai",
        count: orphans.length,
        shown: visible.length,
        anchor: [Math.cos(span.centerAngle) * (rOuter + 0.35), 0.05, Math.sin(span.centerAngle) * (rOuter + 0.35)],
        drill: request.context && request.group !== "sem-pai" ? { context: request.context, group: "sem-pai" } : null,
        memberIds: stable.map((node) => node.id)
      });
    }
  }

  const shown = nodes.length;
  return {
    perspective: "atlas",
    level,
    context: request.context,
    group: request.group,
    radial: "orbit",
    nodes,
    wedges: [],
    wedgeKind: "group",
    guides,
    groups,
    clusterStars,
    beacons: request.context ? horizonBeacons(request, rOuter, request.context) : [],
    rInner: r1,
    rOuter,
    deadlineF: DEADLINE_F,
    unknownR: null,
    totals: { total: level === 0 ? request.nodes.length : total, shown, hidden: Math.max((level === 0 ? request.nodes.length : total) - shown, 0) },
    truncated: Math.max((level === 0 ? request.nodes.length : total) - shown, 0)
  };
}

// ---------------------------------------------------------------------------
// Districts — the world sorted by shape: family shelves, context sectors.

const FAMILY_ORDER = ["root", "hub", "content", "source", "decision", "action", "rule", "event", "person"];

function familyOf(node: GraphNode): string {
  const family = pageTypeStyle(node.page_type).family;
  return FAMILY_ORDER.includes(family) ? family : "content";
}

// Shared shelf sub-layout: place `members` into concentric family shelves fanned
// across the angular span [spanStart, spanEnd]. radius = family-shelf depth (the
// honest "shelf" idiom); freshness stays on TONE. Used by BOTH districtsLayout
// (per context sector) and quadrantsLayout (per fixed quadrant region), so the
// encoding is identical in both.
function familyShelfNodes(
  members: GraphNode[],
  spanStart: number,
  spanEnd: number,
  rInner: number,
  step: number,
  snapshotMs: number
): LayoutNode[] {
  const usable = Math.max(spanEnd - spanStart - 0.08, 0.05);
  const byFamily = new Map<string, GraphNode[]>();
  members.forEach((node) => {
    const family = familyOf(node);
    const list = byFamily.get(family) ?? [];
    list.push(node);
    byFamily.set(family, list);
  });
  const out: LayoutNode[] = [];
  byFamily.forEach((list, family) => {
    const shelf = rInner + FAMILY_ORDER.indexOf(family) * step;
    const sorted = [...list].sort(
      (a, b) => a.page_type.localeCompare(b.page_type) || a.title.localeCompare(b.title) || a.id.localeCompare(b.id)
    );
    sorted.forEach((node, indexInShelf) => {
      const t = (indexInShelf + 0.5) / sorted.length;
      const angle = spanStart + 0.04 + t * usable;
      const y = node.approved_state === "proposal" ? 0.5 : 0;
      out.push(makeNode(node, snapshotMs, [Math.cos(angle) * shelf, y, Math.sin(angle) * shelf], nodeScale(node)));
    });
  });
  return out;
}

function districtsLayout(request: WorldRequest): WorldLayout {
  if (request.context && request.group) {
    const members = request.nodes.filter(
      (node) => contextOf(node) === request.context && (node.page_type || "content") === request.group
    );
    return groupedRadar(request, members, (node) => node.page_type || "content", "page_type", 2, () => null);
  }
  if (request.context) {
    const scoped = request.nodes.filter((node) => contextOf(node) === request.context);
    return groupedRadar(request, scoped, (node) => node.page_type || "content", "page_type", 1, (key) => ({
      context: request.context,
      group: key
    }));
  }

  // L0: concentric family shelves × context sectors.
  const snapshotMs = snapshotClock(request.nodes, request.snapshotAt);
  const total = request.nodes.length;
  const contexts = [...new Set(request.nodes.map(contextOf))].sort();
  const spans = allocateWedgeSpans(
    contexts.map((context) => ({
      key: context,
      weight: request.nodes.filter((node) => contextOf(node) === context).length
    }))
  );
  const spanByKey = new Map(spans.map((span) => [span.key, span]));
  const rInner = 1.7;
  const step = 0.52;
  const rOuter = rInner + FAMILY_ORDER.length * step;
  const guides: WorldGuide[] = FAMILY_ORDER.map((family, index) => ({
    kind: "circle" as const,
    radius: rInner + index * step,
    color: GUIDE_COLOR,
    opacity: index % 2 === 0 ? 0.24 : 0.14
  }));

  const nodes: LayoutNode[] = [];
  const clusterStars: ClusterStar[] = [];
  const wedges: LayoutWedge[] = [];
  const groups: WorldGroup[] = [];
  const budget = splitBudget(
    contexts.map((context) => ({
      key: context,
      size: request.nodes.filter((node) => contextOf(node) === context).length
    })),
    request.maxNodes
  );

  contexts.forEach((context) => {
    const span = spanByKey.get(context);
    if (!span) return;
    const members = request.nodes.filter((node) => contextOf(node) === context).sort(attentionFirst);
    const visible = members.slice(0, budget.get(context) ?? members.length);
    const hidden = members.slice(visible.length);
    familyShelfNodes(visible, span.startAngle, span.endAngle, rInner, step, snapshotMs).forEach((node) =>
      nodes.push(node)
    );
    if (hidden.length > 0) {
      clusterStars.push(
        starFor(
          `star-${context}`,
          "context",
          context,
          hidden,
          [Math.cos(span.centerAngle) * (rOuter - 0.2), 0, Math.sin(span.centerAngle) * (rOuter - 0.2)],
          { context }
        )
      );
    }
    const rim: [number, number, number] = [
      Math.cos(span.centerAngle) * (rOuter + 0.45),
      0.05,
      Math.sin(span.centerAngle) * (rOuter + 0.45)
    ];
    wedges.push({
      context,
      startAngle: span.startAngle,
      endAngle: span.endAngle,
      centerAngle: span.centerAngle,
      count: members.length,
      shown: visible.length,
      freshCount: members.filter((node) => node.freshness_state === "fresh").length,
      staleCount: members.filter((node) => node.freshness_state === "stale").length,
      unknownCount: members.filter((node) => node.freshness_state === "unknown").length,
      proposalCount: members.filter((node) => node.approved_state === "proposal").length,
      riskCount: members.filter((node) => node.risk_flags.length > 0).length,
      rimPosition: rim
    });
    groups.push({
      key: context,
      kind: "context",
      labelKey: context,
      count: members.length,
      shown: visible.length,
      anchor: rim,
      drill: { context },
      memberIds: visible.map((node) => node.id).sort()
    });
  });

  const shown = nodes.length;
  return {
    perspective: "districts",
    level: 0,
    radial: "shelf",
    nodes,
    wedges,
    wedgeKind: "context",
    guides,
    groups,
    clusterStars,
    beacons: [],
    rInner,
    rOuter,
    deadlineF: DEADLINE_F,
    unknownR: null,
    totals: { total, shown, hidden: total - shown },
    truncated: total - shown
  };
}

// ---------------------------------------------------------------------------
// Trails — ego-graph of the locked page in typed relation sectors.

export const TRAIL_SECTORS = ["hierarquia", "evidencia", "links", "citado-por"] as const;
export type TrailSector = (typeof TRAIL_SECTORS)[number];

function trailSectorFor(edge: GraphEdge, outbound: boolean): TrailSector {
  if (edge.type === "moc_parent") return "hierarquia";
  if (edge.type === "source_ref" || edge.type === "ingestion_chain") return "evidencia";
  return outbound ? "links" : "citado-por";
}

function trailsLayout(request: WorldRequest): WorldLayout {
  const snapshotMs = snapshotClock(request.nodes, request.snapshotAt);
  const byId = new Map<string, GraphNode>();
  request.nodes.forEach((node) => {
    byId.set(node.id, node);
    byId.set(node.path, node);
  });
  const centerId = request.pageId && byId.has(request.pageId) ? byId.get(request.pageId)!.id : rootNodeId(request.nodes);
  const center = centerId ? byId.get(centerId) ?? null : null;
  const guides: WorldGuide[] = [];
  const r1 = 2.6;
  const r2 = 4.4;
  const rOuter = r2 + 0.6;
  guides.push({ kind: "circle", radius: r1, color: GUIDE_COLOR, opacity: 0.3 });
  guides.push({ kind: "circle", radius: r2, color: GUIDE_COLOR, opacity: 0.2 });

  if (!center) {
    return {
      perspective: "trails",
      level: request.pageId ? 3 : 0,
      context: request.context,
      group: undefined,
      radial: "ego",
      nodes: [],
      wedges: [],
      wedgeKind: "group",
      guides,
      groups: [],
      clusterStars: [],
      beacons: [],
      rInner: r1,
      rOuter,
      deadlineF: DEADLINE_F,
      unknownR: null,
      totals: { total: request.nodes.length, shown: 0, hidden: request.nodes.length },
      truncated: request.nodes.length
    };
  }

  // 1-hop neighbors bucketed into typed sectors, with true counts.
  const sectorMembers = new Map<TrailSector, GraphNode[]>(TRAIL_SECTORS.map((sector) => [sector, []]));
  const seen = new Set<string>([center.id]);
  const hopOf = new Map<string, 1 | 2>();
  request.edges.forEach((edge) => {
    const sourceNode = byId.get(edge.source);
    const targetNode = byId.get(edge.target);
    if (!sourceNode || !targetNode) return;
    let neighbor: GraphNode | null = null;
    let outbound = false;
    if (sourceNode.id === center.id) {
      neighbor = targetNode;
      outbound = true;
    } else if (targetNode.id === center.id) {
      neighbor = sourceNode;
      outbound = false;
    }
    if (!neighbor || seen.has(neighbor.id)) return;
    seen.add(neighbor.id);
    hopOf.set(neighbor.id, 1);
    sectorMembers.get(trailSectorFor(edge, outbound))!.push(neighbor);
  });

  // 2-hop: fill remaining budget breadth-first from 1-hop neighbors.
  const oneHopIds = new Set([...seen].filter((id) => id !== center.id));
  const twoHop: { node: GraphNode; via: string }[] = [];
  request.edges.forEach((edge) => {
    const sourceNode = byId.get(edge.source);
    const targetNode = byId.get(edge.target);
    if (!sourceNode || !targetNode) return;
    const pairs: [GraphNode, GraphNode][] = [
      [sourceNode, targetNode],
      [targetNode, sourceNode]
    ];
    pairs.forEach(([from, to]) => {
      if (oneHopIds.has(from.id) && !seen.has(to.id)) {
        seen.add(to.id);
        hopOf.set(to.id, 2);
        twoHop.push({ node: to, via: from.id });
      }
    });
  });

  const sectorSpan = (Math.PI * 2) / TRAIL_SECTORS.length;
  const nodes: LayoutNode[] = [makeNode(center, snapshotMs, [0, 0, 0], 0.42, { isHub: true, isRoot: true, ring: 0 })];
  const clusterStars: ClusterStar[] = [];
  const groups: WorldGroup[] = [];
  const oneHopTotal = [...sectorMembers.values()].reduce((sum, list) => sum + list.length, 0);
  const budget1 = Math.min(oneHopTotal, Math.max(request.maxNodes - 1, 8));
  const split = splitBudget(
    TRAIL_SECTORS.map((sector) => ({ key: sector, size: sectorMembers.get(sector)!.length })).filter(
      (entry) => entry.size > 0
    ),
    budget1
  );

  const angleOfNeighbor = new Map<string, number>();
  TRAIL_SECTORS.forEach((sector, sectorIndex) => {
    const start = 0.35 + sectorIndex * sectorSpan;
    const members = [...(sectorMembers.get(sector) ?? [])].sort(
      (a, b) => contextOf(a).localeCompare(contextOf(b)) || a.title.localeCompare(b.title) || a.id.localeCompare(b.id)
    );
    guides.push({ kind: "ray", angle: start, r0: r1 - 0.6, r1: r2 + 0.4, color: GUIDE_COLOR, opacity: 0.35 });
    const visible = members.slice(0, split.get(sector) ?? members.length);
    const hidden = members.slice(visible.length);
    const usable = sectorSpan - 0.16;
    visible.forEach((node, indexInSector) => {
      const t = (indexInSector + 0.5) / visible.length;
      const angle = start + 0.08 + t * usable;
      angleOfNeighbor.set(node.id, angle);
      const y = node.approved_state === "proposal" ? 0.5 : 0;
      nodes.push(makeNode(node, snapshotMs, [Math.cos(angle) * r1, y, Math.sin(angle) * r1], nodeScale(node), { ring: 1 }));
    });
    if (hidden.length > 0) {
      const centerAngle = start + sectorSpan / 2;
      clusterStars.push(
        starFor(`star-${sector}`, "relation", sector, hidden, [Math.cos(centerAngle) * (r2 + 0.3), 0, Math.sin(centerAngle) * (r2 + 0.3)], null)
      );
    }
    const centerAngle = start + sectorSpan / 2;
    groups.push({
      key: sector,
      kind: "relation",
      labelKey: sector,
      count: members.length,
      shown: visible.length,
      anchor: [Math.cos(centerAngle) * (rOuter + 0.4), 0.05, Math.sin(centerAngle) * (rOuter + 0.4)],
      drill: null,
      memberIds: visible.map((node) => node.id)
    });
  });

  // 2nd hop nodes hang faintly near their 1-hop anchor.
  const shownIds = new Set(nodes.map((node) => node.id));
  const budget2 = Math.max(request.maxNodes - nodes.length, 0);
  const orderedTwoHop = [...twoHop].sort(
    (a, b) => a.node.title.localeCompare(b.node.title) || a.node.id.localeCompare(b.node.id)
  );
  orderedTwoHop.slice(0, budget2).forEach(({ node, via }) => {
    if (shownIds.has(node.id)) return;
    shownIds.add(node.id);
    const anchor = angleOfNeighbor.get(via) ?? stableHash(via) * Math.PI * 2;
    const angle = anchor + (stableHash(node.id) - 0.5) * 0.5;
    const y = node.approved_state === "proposal" ? 0.5 : 0;
    nodes.push(makeNode(node, snapshotMs, [Math.cos(angle) * r2, y, Math.sin(angle) * r2], nodeScale(node) * 0.85, { ring: 2, faint: true }));
  });
  const hiddenTwoHop = orderedTwoHop.length - Math.min(orderedTwoHop.length, budget2);
  if (hiddenTwoHop > 0) {
    clusterStars.push(
      starFor(
        "star-2-hop",
        "relation",
        "links",
        orderedTwoHop.slice(budget2).map((entry) => entry.node),
        [Math.cos(0.35 - 0.3) * (r2 + 0.3), 0, Math.sin(0.35 - 0.3) * (r2 + 0.3)],
        null
      )
    );
  }

  const reachableTotal = 1 + oneHopTotal + orderedTwoHop.length;
  const shown = nodes.length;
  return {
    perspective: "trails",
    level: 3,
    context: request.context,
    group: undefined,
    radial: "ego",
    nodes,
    wedges: [],
    wedgeKind: "group",
    guides,
    groups,
    clusterStars,
    beacons: [],
    rInner: r1,
    rOuter,
    deadlineF: DEADLINE_F,
    unknownR: null,
    totals: { total: reachableTotal, shown, hidden: Math.max(reachableTotal - shown, 0) },
    truncated: Math.max(reachableTotal - shown, 0)
  };
}

// ---------------------------------------------------------------------------

export function computeWorldLayout(request: WorldRequest): WorldLayout {
  if (request.perspective === "atlas") return atlasLayout(request);
  if (request.perspective === "districts") return districtsLayout(request);
  if (request.perspective === "trails") return trailsLayout(request);
  if (request.perspective === "focus") return focusLayout(request);
  if (request.perspective === "quadrants") return quadrantsLayout(request);
  return radarLayout(request);
}

// Quadrants — the AQAL home map: WHERE EVERYTHING LIVES. The plane is carved into
// four FIXED 90° regions by each page's home quadrant (its own page_type, not a
// neighbor edge), plus a central q0-core disc for structural pages that honestly
// have no quadrant. radial="shelf": radius is family-shelf depth (freshness stays
// on tone), never a freshness deadline — the four fixed sectors must not double-
// encode. The frame is constant: four quadrant groups + rays always emit (an
// empty quadrant shows a dimmed rim, count 0); the core group emits only when
// populated (the core is not a fifth quadrant).
function quadrantsLayout(request: WorldRequest): WorldLayout {
  const snapshotMs = snapshotClock(request.nodes, request.snapshotAt);
  const total = request.nodes.length;
  const rInner = 1.7;
  const step = 0.52;
  const rOuter = rInner + FAMILY_ORDER.length * step;
  const coreR = 1.15; // the q0-core disc lives inside rInner

  // Partition by home quadrant (structural/unknown → core).
  const regionMembers = new Map<SceneFacet, GraphNode[]>(SCENE_FACETS.map((facet) => [facet, []]));
  const coreMembers: GraphNode[] = [];
  request.nodes.forEach((node) => {
    const home = homeQuadrant(node.page_type);
    if (home) regionMembers.get(home)!.push(node);
    else coreMembers.push(node);
  });

  // Render budget split proportionally over the five true region sizes.
  const budget = splitBudget(
    [
      ...SCENE_FACETS.map((facet) => ({ key: facet, size: regionMembers.get(facet)!.length })),
      { key: "__core__", size: coreMembers.length }
    ].filter((entry) => entry.size > 0),
    request.maxNodes
  );

  // Four fixed rays at the region BOUNDARIES (the axes between quadrants).
  const guides: WorldGuide[] = [0, Math.PI / 2, Math.PI, (3 * Math.PI) / 2].map((angle) => ({
    kind: "ray" as const,
    angle,
    r0: coreR,
    r1: rOuter + 0.3,
    color: GUIDE_COLOR,
    opacity: 0.3
  }));
  FAMILY_ORDER.forEach((_family, index) => {
    guides.push({ kind: "circle", radius: rInner + index * step, color: GUIDE_COLOR, opacity: index % 2 === 0 ? 0.16 : 0.09 });
  });

  const nodes: LayoutNode[] = [];
  const clusterStars: ClusterStar[] = [];
  const groups: WorldGroup[] = [];

  SCENE_FACETS.forEach((facet) => {
    const center = QUADRANT_CENTER_ANGLE[facet];
    const spanStart = center - Math.PI / 4 + 0.06;
    const spanEnd = center + Math.PI / 4 - 0.06;
    const members = [...regionMembers.get(facet)!].sort(attentionFirst);
    const visible = members.slice(0, budget.get(facet) ?? members.length);
    const hidden = members.slice(visible.length);
    familyShelfNodes(visible, spanStart, spanEnd, rInner, step, snapshotMs).forEach((node) => nodes.push(node));
    const rim: [number, number, number] = [Math.cos(center) * (rOuter + 0.55), 0.05, Math.sin(center) * (rOuter + 0.55)];
    if (hidden.length > 0) {
      clusterStars.push(starFor(`qstar-${facet}`, "quadrant", facet, hidden, [Math.cos(center) * (rOuter - 0.2), 0, Math.sin(center) * (rOuter - 0.2)], { group: facet }));
    }
    // ALWAYS emit the four quadrant groups (even count 0 → honest dimmed rim).
    groups.push({
      key: facet,
      kind: "quadrant",
      labelKey: facet,
      count: members.length,
      shown: visible.length,
      anchor: rim,
      drill: null,
      memberIds: visible.map((node) => node.id).sort()
    });
  });

  // q0-core: structural pages on a small central disc — honest "no quadrant".
  const coreVisible = coreMembers.slice(0, budget.get("__core__") ?? coreMembers.length);
  const coreHidden = coreMembers.slice(coreVisible.length);
  const coreOrdered = [...coreVisible].sort((a, b) => a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
  coreOrdered.forEach((node, index) => {
    const angle = (index / Math.max(coreOrdered.length, 1)) * Math.PI * 2;
    const ring = coreR * (0.35 + 0.6 * ((index % 3) / 2));
    nodes.push(makeNode(node, snapshotMs, [Math.cos(angle) * ring, 0, Math.sin(angle) * ring], nodeScale(node) * 0.9));
  });
  if (coreHidden.length > 0) {
    clusterStars.push(starFor("qstar-core", "core", "core", coreHidden, [0, 0, 0], null));
  }
  // The core group emits ONLY when populated — it is not a persistent quadrant.
  if (coreMembers.length > 0) {
    groups.push({
      key: "__core__",
      kind: "core",
      labelKey: "core",
      count: coreMembers.length,
      shown: coreVisible.length,
      anchor: [0, 0.05, 0],
      drill: null,
      memberIds: coreVisible.map((node) => node.id).sort()
    });
  }

  const shown = nodes.length;
  const cameraTarget: [number, number, number] | undefined = request.quadrant
    ? [Math.cos(QUADRANT_CENTER_ANGLE[request.quadrant]) * (rInner + rOuter) * 0.5, 0, Math.sin(QUADRANT_CENTER_ANGLE[request.quadrant]) * (rInner + rOuter) * 0.5]
    : undefined;

  return {
    perspective: "quadrants",
    level: 0,
    radial: "shelf",
    nodes,
    wedges: [],
    wedgeKind: "group",
    guides,
    groups,
    clusterStars,
    beacons: [],
    rInner,
    rOuter,
    deadlineF: DEADLINE_F,
    unknownR: null,
    totals: { total, shown, hidden: total - shown },
    truncated: total - shown,
    cameraTarget
  };
}

// Focus — the page-centered multi-perspective view. Structurally trails, but
// its four sectors are the FACETS (Intention/Practice/Relations/Systems),
// bucketed from the neighbor's page_type + edge, and an empty facet renders as a
// visible "no lens registered" wedge (honest absence). Structural neighbors
// (moc_parent hierarchy) collapse into a hidden cluster so the lenses stay pure.
function focusLayout(request: WorldRequest): WorldLayout {
  const snapshotMs = snapshotClock(request.nodes, request.snapshotAt);
  const byId = new Map<string, GraphNode>();
  request.nodes.forEach((node) => {
    byId.set(node.id, node);
    byId.set(node.path, node);
  });
  // Focus is page-anchored: a pageId that is NOT in this graph yields the
  // empty/center-less layout, never a silent re-center on the wiki root (which
  // would contradict the HTML legend still keyed to the requested page).
  const centerId = request.pageId
    ? byId.has(request.pageId)
      ? byId.get(request.pageId)!.id
      : null
    : rootNodeId(request.nodes);
  const center = centerId ? byId.get(centerId) ?? null : null;
  const guides: WorldGuide[] = [];
  const r1 = 2.6;
  const r2 = 4.4;
  const rOuter = r2 + 0.6;
  guides.push({ kind: "circle", radius: r1, color: GUIDE_COLOR, opacity: 0.3 });
  guides.push({ kind: "circle", radius: r2, color: GUIDE_COLOR, opacity: 0.2 });

  const emptyTotals = { total: request.nodes.length, shown: 0, hidden: request.nodes.length };
  if (!center) {
    return {
      perspective: "focus", level: request.pageId ? 3 : 0, context: request.context, group: undefined,
      radial: "ego", nodes: [], wedges: [], wedgeKind: "group", guides, groups: [], clusterStars: [],
      beacons: [], rInner: r1, rOuter, deadlineF: DEADLINE_F, unknownR: null, totals: emptyTotals,
      truncated: request.nodes.length
    };
  }

  // 1-hop neighbors bucketed by FACET; structural (null facet) set aside.
  const facetMembers = new Map<SceneFacet, GraphNode[]>(SCENE_FACETS.map((facet) => [facet, []]));
  const structural: GraphNode[] = [];
  const seen = new Set<string>([center.id]);
  request.edges.forEach((edge) => {
    const sourceNode = byId.get(edge.source);
    const targetNode = byId.get(edge.target);
    if (!sourceNode || !targetNode) return;
    let neighbor: GraphNode | null = null;
    if (sourceNode.id === center.id) neighbor = targetNode;
    else if (targetNode.id === center.id) neighbor = sourceNode;
    if (!neighbor || seen.has(neighbor.id)) return;
    seen.add(neighbor.id);
    const facet = sceneFacetOf(neighbor.page_type, edge.type);
    if (facet) facetMembers.get(facet)!.push(neighbor);
    else structural.push(neighbor);
  });

  const sectorSpan = (Math.PI * 2) / SCENE_FACETS.length;
  const nodes: LayoutNode[] = [makeNode(center, snapshotMs, [0, 0, 0], 0.42, { isHub: true, isRoot: true, ring: 0 })];
  const clusterStars: ClusterStar[] = [];
  const groups: WorldGroup[] = [];
  const oneHopTotal = [...facetMembers.values()].reduce((sum, list) => sum + list.length, 0);
  const budget1 = Math.min(oneHopTotal, Math.max(request.maxNodes - 1, 8));
  const split = splitBudget(
    SCENE_FACETS.map((facet) => ({ key: facet, size: facetMembers.get(facet)!.length })).filter((entry) => entry.size > 0),
    budget1
  );

  SCENE_FACETS.forEach((facet, sectorIndex) => {
    const start = 0.35 + sectorIndex * sectorSpan;
    const members = [...(facetMembers.get(facet) ?? [])].sort(
      (a, b) => contextOf(a).localeCompare(contextOf(b)) || a.title.localeCompare(b.title) || a.id.localeCompare(b.id)
    );
    guides.push({ kind: "ray", angle: start, r0: r1 - 0.6, r1: r2 + 0.4, color: GUIDE_COLOR, opacity: 0.35 });
    const visible = members.slice(0, split.get(facet) ?? members.length);
    const hidden = members.slice(visible.length);
    const usable = sectorSpan - 0.16;
    visible.forEach((node, indexInSector) => {
      const tt = (indexInSector + 0.5) / visible.length;
      const angle = start + 0.08 + tt * usable;
      const y = node.approved_state === "proposal" ? 0.5 : 0;
      nodes.push(makeNode(node, snapshotMs, [Math.cos(angle) * r1, y, Math.sin(angle) * r1], nodeScale(node), { ring: 1 }));
    });
    const centerAngle = start + sectorSpan / 2;
    if (hidden.length > 0) {
      clusterStars.push(
        starFor(`facet-star-${facet}`, "facet", facet, hidden, [Math.cos(centerAngle) * (r2 + 0.3), 0, Math.sin(centerAngle) * (r2 + 0.3)], null)
      );
    }
    // Every facet emits a group — an EMPTY one renders as an honest "no lens"
    // wedge the UI can offer to fill.
    groups.push({
      key: facet,
      kind: "facet",
      labelKey: facet,
      count: members.length,
      shown: visible.length,
      anchor: [Math.cos(centerAngle) * (rOuter + 0.4), 0.05, Math.sin(centerAngle) * (rOuter + 0.4)],
      drill: null,
      memberIds: visible.map((node) => node.id)
    });
  });

  // Structural neighbors (hierarchy/links) collapse into one hidden cluster so
  // the four lenses show only what belongs in a lens.
  if (structural.length > 0) {
    clusterStars.push(
      starFor("focus-structural", "relation", "links", structural, [Math.cos(-0.3) * (r2 + 0.3), 0, Math.sin(-0.3) * (r2 + 0.3)], null)
    );
  }

  const reachableTotal = 1 + oneHopTotal + structural.length;
  const shown = nodes.length;
  return {
    perspective: "focus", level: 3, context: request.context, group: undefined, radial: "ego",
    nodes, wedges: [], wedgeKind: "group", guides, groups, clusterStars, beacons: [],
    rInner: r1, rOuter, deadlineF: DEADLINE_F, unknownR: null,
    totals: { total: reachableTotal, shown, hidden: Math.max(reachableTotal - shown, 0) },
    truncated: Math.max(reachableTotal - shown, 0)
  };
}

export function worldLevel(route: { context?: string; group?: string; pageId?: string }): number {
  if (route.pageId) return 3;
  if (route.group) return 2;
  if (route.context) return 1;
  return 0;
}
