// Perspective engine: pure, deterministic, worker-computable layouts.
//
// The same node identities are re-arranged by four perspectives — radar
// (verification), atlas (hierarchy), districts (taxonomy), trails (relations)
// — across drill levels (galaxy → context → group → page). Every layout obeys
// the honest-encoding contract: position/label = context, active overlay =
// color/ring/symbol, shape = kind, line = relation,
// and no visual implies data that does not exist. The per-level node cap keeps
// draw calls bounded while cluster-stars carry the TRUE hidden counts, so all
// pages stay countable and one drill away.

import type { GraphEdge, GraphNode, RegionGroupPayload } from "../types";
import { aggregateOverlayMetrics } from "../data/visualEncoding";
import { pageTypeLabel, pageTypeStyle, worldGroupLabel } from "../data/presentation";
import { QUADRANT_CENTER_ANGLE, SCENE_FACETS, nodeQuadrant, sceneFacetOf, type QuadrantHomes, type SceneFacet } from "./facets";
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
import { parseRealFamilyGroupId, realFamilyGroupId } from "./worldState";

export type PerspectiveId =
  | "radar"
  | "atlas"
  | "districts"
  | "trails"
  | "focus"
  | "quadrants"
  | "sources"
  | "work";

export type GroupKind =
  | "context"
  | "attention"
  | "page_type"
  | "hub"
  | "orphan"
  | "relation"
  | "facet"
  | "quadrant"
  | "core"
  | "family"
  | "region_family"
  | "source_flow"
  | "work_queue";

export type WorldGroup = {
  key: string;
  kind: GroupKind;
  labelKey: string;
  count: number;
  shown: number;
  anchor: [number, number, number];
  drill: { context?: string; group?: string } | null;
  memberIds: string[];
  region?: RegionGroupPayload;
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
  // Active recursive quadrant/template anchor. In the quadrant map this is the
  // world center, so it must never be rendered again inside a quadrant.
  centerId?: string;
  // The active quadrant (Quadrants perspective) — sets the camera fly-to target;
  // it does NOT scope the home map (all four regions stay shown).
  quadrant?: SceneFacet;
  // The compiler's per-page classification (derived quadrant_assignments,
  // inverted). When present it OVERRIDES the static page-type map — the scene
  // must never re-classify what the interpretation layer already decided.
  quadrantHomes?: QuadrantHomes;
  // The selected/center page's own interface contract includes quadrant lenses.
  // Page drill uses this to decide whether quadrants are real child objects of
  // the center or just a parent-world scaffold that should stay hidden.
  centerHasQuadrants?: boolean;
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
  // Physical origin of the group that is now centered. This is not transient UI
  // state: it is derived from the previous in-world position of the same group
  // object, so deep links and settled drills still show where the center came
  // from.
  drillOrigin?: [number, number, number];
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
    overlay_metrics: node.overlay_metrics,
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

function familyLabelKey(family: string): string {
  if (["source", "hub", "decision", "action", "rule", "event", "person", "root"].includes(family)) return family;
  return "content";
}

export function regionDrillKey(facet: SceneFacet): string {
  return `region:${facet}`;
}

export function regionFamilyDrillKey(facet: SceneFacet, family: string): string {
  return `region:${facet}:family:${familyLabelKey(family)}`;
}

export function parseRegionDrillKey(value: string | undefined): { facet: SceneFacet; family?: string } | null {
  if (!value) return null;
  const parts = value.split(":");
  if (parts[0] !== "region" || !SCENE_FACETS.includes(parts[1] as SceneFacet)) return null;
  if (parts.length === 2) return { facet: parts[1] as SceneFacet };
  if (parts.length === 4 && parts[2] === "family" && parts[3]) return { facet: parts[1] as SceneFacet, family: parts[3] };
  return null;
}

function groupGlyph(kind: string, labelKey: string): string {
  if (kind === "quadrant") return "◈";
  if ((kind === "family" || kind === "region_family") && labelKey === "source") return "▣";
  if ((kind === "family" || kind === "region_family") && labelKey === "action") return "✓";
  if ((kind === "family" || kind === "region_family") && labelKey === "decision") return "◆";
  if ((kind === "family" || kind === "region_family") && labelKey === "person") return "◎";
  if ((kind === "family" || kind === "region_family") && labelKey === "hub") return "▦";
  if ((kind === "family" || kind === "region_family") && labelKey === "rule") return "⚙";
  if ((kind === "family" || kind === "region_family") && labelKey === "event") return "✦";
  return "▤";
}

function groupPageType(kind: string, labelKey: string): string {
  if (kind === "family" || kind === "region_family") return `visual_group_${labelKey}`;
  if (kind === "quadrant") return "visual_group_region";
  return "visual_group";
}

function makeGroupNode(
  key: string,
  kind: GroupKind,
  labelKey: string,
  title: string,
  context: string,
  members: GraphNode[],
  position: [number, number, number],
  scale: number,
  drill: { context?: string; group?: string } | null,
  options: { isRoot?: boolean; ring?: number; faint?: boolean; nodeId?: string } = {}
): LayoutNode {
  const stale = members.some((node) => node.freshness_state === "stale");
  const unknown = members.length > 0 && members.every((node) => node.freshness_state === "unknown");
  const proposal = members.some((node) => node.approved_state === "proposal");
  const risk = members.some((node) => node.risk_flags.length > 0);
  const previewTitles = members.slice(0, 2).map((node) => node.title);
  const caption = previewTitles.length > 0 ? `${members.length} · ${previewTitles.join(" · ")}` : `${members.length}`;
  const nodeId = options.nodeId ?? key;
  return {
    id: nodeId,
    path: nodeId,
    title,
    context,
    page_type: groupPageType(kind, labelKey),
    freshness_state: stale ? "stale" : unknown ? "unknown" : "fresh",
    approved_state: proposal ? "proposal" : "approved",
    risk_flags: risk ? ["group_attention"] : [],
    source_ref_count: members.reduce((sum, node) => sum + node.metrics.source_ref_count, 0),
    inbound_links: members.reduce((sum, node) => sum + node.metrics.inbound_links, 0),
    outbound_links: members.reduce((sum, node) => sum + node.metrics.outbound_links, 0),
    overlay_metrics: aggregateOverlayMetrics(members),
    ageDays: 0,
    overdueRatio: stale ? 1.2 : 0,
    isHub: true,
    isRoot: Boolean(options.isRoot),
    position: [Number(position[0].toFixed(4)), Number(position[1].toFixed(4)), Number(position[2].toFixed(4))],
    scale: Number(scale.toFixed(4)),
    ...(options.ring !== undefined ? { ring: options.ring } : {}),
    ...(options.faint ? { faint: true } : {}),
    isGroup: true,
    groupKey: key,
    groupKind: kind,
    groupLabelKey: labelKey,
    groupMemberIds: members.map((node) => node.id).sort(),
    groupDrill: drill,
    visualGlyph: groupGlyph(kind, labelKey),
    groupCaption: caption,
    groupPreviewIds: members.slice(0, 3).map((node) => node.id),
    groupComposition: groupComposition(members)
  };
}

function groupComposition(members: GraphNode[]): { family: string; count: number }[] {
  const counts = new Map<string, number>();
  members.forEach((node) => {
    const family = familyOf(node);
    counts.set(family, (counts.get(family) ?? 0) + 1);
  });
  return [...counts.entries()]
    .map(([family, count]) => ({ family, count }))
    .sort((a, b) => b.count - a.count || familyRank(a.family) - familyRank(b.family) || a.family.localeCompare(b.family))
    .slice(0, 5);
}

function shouldAggregateFamily(members: GraphNode[]): boolean {
  return members.length >= 3;
}

function previewLimitForGroup(memberCount: number): number {
  // The family shell and honest count carry the root overview. Real members
  // appear one interaction deeper; keeping preview meshes beside every shell
  // made the 107-page instructional world visually and computationally noisy.
  return 0;
}

function visibleFamilyChildLimit(memberCount: number, budget: number): number {
  const capped = memberCount >= 48 ? 16 : memberCount >= 24 ? 20 : 28;
  return Math.max(1, Math.min(budget, capped));
}

function familyGroupScale(memberCount: number, level: 0 | 1 | 2): number {
  const base = level === 0 ? 0.24 : level === 1 ? 0.3 : 0.24;
  const gain = level === 0 ? 0.026 : level === 1 ? 0.034 : 0.03;
  const cap = memberCount >= 48 ? 0.42 : level === 1 ? 0.48 : 0.38;
  return Math.min(base + Math.log2(memberCount + 1) * gain, cap);
}

export function centeredQuadrantGroupScale(memberCount: number, kind: "quadrant" | "region_family", level: 1 | 2): number {
  const base = kind === "quadrant" ? 0.46 : 0.42;
  const gain = kind === "quadrant" ? 0.04 : 0.045;
  const cap = level === 1 ? 0.72 : 0.76;
  return Number(Math.min(base + Math.log2(memberCount + 1) * gain, cap).toFixed(4));
}

function previewNodesAround(
  groupKey: string,
  members: GraphNode[],
  snapshotMs: number,
  anchor: [number, number, number],
  radius: number,
  limit = 3
): LayoutNode[] {
  const previews = members.slice(0, Math.min(limit, previewLimitForGroup(members.length)));
  const start = stableHash(groupKey) * Math.PI * 2;
  return previews.map((node, index) => {
    const angle = start + (index / Math.max(previews.length, 1)) * Math.PI * 2;
    const y = anchor[1] + 0.08 + (node.approved_state === "proposal" ? 0.18 : 0);
    return makeNode(
      node,
      snapshotMs,
      [anchor[0] + Math.cos(angle) * radius, y, anchor[2] + Math.sin(angle) * radius],
      Math.min(nodeScale(node) * 0.68, 0.18),
      { faint: true, ring: 2 }
    );
  });
}

// The quadrant home map is a 2x2 territory board, not four slices of a ring.
// This value is the diagonal distance from the origin to a territory's center;
// callers project it to the canonical quadrant signs below.
export function initialQuadrantRegionOrbit(rInner: number, rOuter: number): number {
  return Number((rInner + (rOuter - rInner) * 0.55).toFixed(4));
}

function quadrantRegionPosition(facet: SceneFacet, rInner: number, rOuter: number): [number, number, number] {
  const center = QUADRANT_CENTER_ANGLE[facet];
  const regionOrbit = initialQuadrantRegionOrbit(rInner, rOuter);
  return [
    Number((Math.cos(center) * regionOrbit).toFixed(4)),
    -0.02,
    Number((Math.sin(center) * regionOrbit).toFixed(4))
  ];
}

function quadrantFamilyTerritoryOffset(index: number, total: number): [number, number] {
  const columns = Math.max(1, Math.min(3, Math.ceil(Math.sqrt(Math.max(total, 1)))));
  const rows = Math.max(1, Math.ceil(Math.max(total, 1) / columns));
  const row = Math.floor(index / columns);
  const rowStart = row * columns;
  const itemsInRow = Math.min(columns, Math.max(total - rowStart, 1));
  const columnInRow = index - rowStart;
  const x = itemsInRow === 1 ? 0 : -1.2 + (columnInRow / (itemsInRow - 1)) * 2.4;
  const z = rows === 1 ? 0 : -1.2 + (row / (rows - 1)) * 2.4;
  return [Number(x.toFixed(4)), Number(z.toFixed(4))];
}

function quadrantFamilyTerritoryAnchor(
  facet: SceneFacet,
  list: GraphNode[],
  index: number,
  total: number,
  rInner: number,
  rOuter: number
): [number, number, number] {
  const center = quadrantRegionPosition(facet, rInner, rOuter);
  const [offsetX, offsetZ] = quadrantFamilyTerritoryOffset(index, total);
  return [
    Number((center[0] + offsetX).toFixed(4)),
    list.some((node) => node.approved_state === "proposal") ? 0.35 : 0,
    Number((center[2] + offsetZ).toFixed(4))
  ];
}

export function regionFamilyAnchorInCenteredRegion(
  list: GraphNode[],
  spanCenterAngle: number,
  index = 0,
  total = 1
): [number, number, number] {
  const densityPush = total >= 6 ? 0.48 : total >= 4 ? 0.32 : total >= 3 ? 0.18 : 0;
  const alternatingShelf = total > 2 ? (index % 2) * 0.22 : 0;
  const radius = 2.42 + densityPush + alternatingShelf + Math.min(Math.log2(list.length + 1) * 0.18, 0.74);
  return [
    Number((Math.cos(spanCenterAngle) * radius).toFixed(4)),
    Number(((list.some((node) => node.approved_state === "proposal") ? 0.35 : 0) + (total > 4 && index % 3 === 1 ? 0.12 : 0)).toFixed(4)),
    Number((Math.sin(spanCenterAngle) * radius).toFixed(4))
  ];
}

function pageNodesInTerritory(
  members: GraphNode[],
  snapshotMs: number,
  anchor: [number, number, number]
): LayoutNode[] {
  return members.map((node, index) => {
    const offset = (index - (members.length - 1) / 2) * 0.44;
    const y = node.approved_state === "proposal" ? 0.35 : 0;
    return makeNode(node, snapshotMs, [anchor[0] + offset, y, anchor[2]], nodeScale(node), {
      ring: 1
    });
  });
}

function familyDrillPageNodes(members: GraphNode[], snapshotMs: number): LayoutNode[] {
  const innerCount = Math.min(members.length, members.length > 10 ? 8 : members.length);
  const outerCount = Math.max(members.length - innerCount, 0);
  return members.map((node, index) => {
    const outer = index >= innerCount;
    const ringIndex = outer ? index - innerCount : index;
    const ringSize = outer ? outerCount : innerCount;
    const phase = outer ? -Math.PI / 2 + Math.PI / Math.max(ringSize, 2) : -Math.PI / 2;
    const angle = members.length === 1 ? -Math.PI / 2 : phase + (ringIndex / Math.max(ringSize, 1)) * Math.PI * 2;
    const radius = outer ? 2.85 : members.length <= 4 ? 2.08 : 2.32;
    const y = node.approved_state === "proposal" ? 0.35 : 0;
    return makeNode(node, snapshotMs, [Math.cos(angle) * radius, y, Math.sin(angle) * radius], Math.min(nodeScale(node), members.length > 10 ? 0.22 : 0.3), {
      ring: outer ? 2 : 1
    });
  });
}

function surroundingFamilyNodes(
  activeFamily: string,
  familyEntries: [string, GraphNode[]][],
  rootNode: GraphNode | null,
  radius: number
): LayoutNode[] {
  const siblings = familyEntries.filter(([family]) => family !== activeFamily);
  return siblings.map(([family, list], index) => {
    const angle = -Math.PI * 0.72 + (index / Math.max(siblings.length - 1, 1)) * Math.PI * 1.44;
    const key = realFamilyGroupId(family);
    return makeGroupNode(
      key,
      "family",
      family,
      pageTypeLabel(`visual_group_${family}`),
      rootNode?.context || "system",
      list,
      [Math.cos(angle) * radius, -0.06, Math.sin(angle) * radius],
      Math.min(0.28 + Math.log2(list.length + 1) * 0.035, 0.46),
      { group: key },
      { ring: 3, faint: true }
    );
  });
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

// A capped perimeter must still represent the whole perimeter. Taking only a
// sorted prefix bunches every visible item into the first arc because the
// stable positions are derived from the full list index. Keep the first/highest
// priority item, include the tail, and sample the intervening ranks evenly.
// The chosen nodes retain their full-list positions, so revealing more does not
// move objects that were already visible.
function spacedSample<T>(items: readonly T[], limit: number): T[] {
  const count = Math.max(0, Math.min(Math.floor(limit), items.length));
  if (count === 0) return [];
  if (count === items.length) return [...items];
  if (count === 1) return [items[0]!];
  return Array.from({ length: count }, (_, index) => {
    const sourceIndex = Math.round((index * (items.length - 1)) / (count - 1));
    return items[sourceIndex]!;
  });
}

// ---------------------------------------------------------------------------
// Group keys per perspective: the URL :group segment. Deterministic and
// derivable from the page record alone so search/wiki-links can auto-drill.

const SOURCE_EMITTER_TYPES = new Set([
  "source",
  "source_catalog",
  "source_config",
  "source_registry",
  "input_channel",
  "input_stage"
]);

function isSourceEmitterType(pageType: string): boolean {
  return SOURCE_EMITTER_TYPES.has(pageType);
}

export function groupKeyForPage(
  perspective: PerspectiveId,
  page: { moc_parent?: string; page_type: string; freshness_state: string; approved_state?: string; risk_flags?: string[] }
): string | undefined {
  if (perspective === "trails") return undefined;
  if (perspective === "sources") {
    return isSourceEmitterType(page.page_type) ? "source-emitters" : "unconsolidated";
  }
  if (perspective === "work") {
    const flags = page.risk_flags?.join(" ").toLowerCase() ?? "";
    if (/block|fail|error|overdue/.test(flags)) return "blocked";
    if (page.approved_state === "proposal" || page.page_type === "proposal") return "proposal-review";
    if (isSourceEmitterType(page.page_type) && page.freshness_state !== "fresh") return "source-sync";
    if (pageTypeStyle(page.page_type).family === "action") return "open-actions";
    if (page.freshness_state === "stale") return "review-needed";
    return "supporting-context";
  }
  if (perspective === "districts") return page.page_type || "content";
  if (perspective === "atlas") return page.moc_parent ? atlasKeyFromRef(page.moc_parent) : "sem-pai";
  const attention =
    page.freshness_state === "stale" || page.approved_state === "proposal" || (page.risk_flags?.length ?? 0) > 0;
  return attention ? "atencao" : page.page_type || "content";
}

function radarGroupKey(node: GraphNode): string {
  return isAttention(node) ? "atencao" : node.page_type || "content";
}

function normalizedTitle(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function isActiveCenterEquivalent(node: GraphNode, center: GraphNode | null): boolean {
  if (!center || node.id === center.id) return Boolean(center && node.id === center.id);
  const centerTitle = normalizedTitle(center.title);
  const nodeTitle = normalizedTitle(node.title);
  if (!centerTitle || centerTitle !== nodeTitle) return false;
  // A detailed person/company profile that names the active root is the same
  // subject being represented in a different page contract. It belongs to the
  // center stack, not as a child planet in one of its own quadrants.
  if (center.page_type === "root_entity" && ["person", "root_entity", "context_note"].includes(node.page_type)) return true;
  if (center.page_type === "person" && node.page_type === "root_entity") return true;
  return false;
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

function familyRank(family: string): number {
  const index = FAMILY_ORDER.indexOf(family);
  return index >= 0 ? index : FAMILY_ORDER.indexOf("content");
}

function groupByFamily(nodes: GraphNode[]): Map<string, GraphNode[]> {
  const byFamily = new Map<string, GraphNode[]>();
  nodes.forEach((node) => {
    const key = familyLabelKey(familyOf(node));
    const list = byFamily.get(key) ?? [];
    list.push(node);
    byFamily.set(key, list);
  });
  byFamily.forEach((list) => list.sort(attentionFirst));
  return byFamily;
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
  if (edge.type === "moc_parent" || edge.type === "collection_member") return "hierarquia";
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

// Sources — provenance topology. Source pages are stable emitter places, their
// real evidence/ingestion edges fan emitted artifacts out behind them, and
// everything without such a relation stays visible on an explicit outer
// unconsolidated ring. Freshness remains a tone/overlay: it never changes an
// emitter into a lifecycle state or moves a page between provenance groups.

type SemanticBucket = {
  key: string;
  kind: GroupKind;
  labelKey: string;
  members: GraphNode[];
  anchor: [number, number, number];
};

function canonicalCenter(request: WorldRequest): GraphNode | null {
  const byKey = new Map<string, GraphNode>();
  request.nodes.forEach((node) => {
    byKey.set(node.id, node);
    byKey.set(node.path, node);
  });
  const configured = request.centerId ? byKey.get(request.centerId) : null;
  if (configured) return configured;
  const rootId = rootNodeId(request.nodes);
  return rootId ? byKey.get(rootId) ?? null : null;
}

function sourceFlowEdge(edge: GraphEdge): boolean {
  return /source_ref|ingestion_chain|evidence|emitt/.test(edge.type.toLowerCase());
}

function sourcesLayout(request: WorldRequest): WorldLayout {
  const snapshotMs = snapshotClock(request.nodes, request.snapshotAt);
  const center = canonicalCenter(request);
  const centerId = center?.id ?? "";
  const byKey = new Map<string, GraphNode>();
  request.nodes.forEach((node) => {
    byKey.set(node.id, node);
    byKey.set(node.path, node);
  });

  const allEmitters = request.nodes
    .filter((node) => isSourceEmitterType(node.page_type))
    .sort((a, b) => attentionFirst(a, b));
  const emitterIds = new Set(allEmitters.map((node) => node.id));
  const emittedBy = new Map<string, string>();
  request.edges
    .filter(sourceFlowEdge)
    .sort((a, b) =>
      a.type.localeCompare(b.type) ||
      a.source.localeCompare(b.source) ||
      a.target.localeCompare(b.target)
    )
    .forEach((edge) => {
      const source = byKey.get(edge.source);
      const target = byKey.get(edge.target);
      if (!source || !target) return;
      const sourceIsEmitter = emitterIds.has(source.id);
      const targetIsEmitter = emitterIds.has(target.id);
      if (sourceIsEmitter === targetIsEmitter) return;
      const emitterId = sourceIsEmitter ? source.id : target.id;
      const artifactId = sourceIsEmitter ? target.id : source.id;
      const existing = emittedBy.get(artifactId);
      if (!existing || emitterId.localeCompare(existing) < 0) emittedBy.set(artifactId, emitterId);
    });

  const emitters = allEmitters.filter((node) => node.id !== centerId);
  const emitted = request.nodes
    .filter((node) => node.id !== centerId && !emitterIds.has(node.id) && emittedBy.has(node.id))
    .sort((a, b) =>
      (emittedBy.get(a.id) ?? "").localeCompare(emittedBy.get(b.id) ?? "") ||
      attentionFirst(a, b)
    );
  const unconsolidated = request.nodes
    .filter((node) => node.id !== centerId && !emitterIds.has(node.id) && !emittedBy.has(node.id))
    .sort(attentionFirst);

  // Preserve source places before their emissions. An emitted artifact never
  // appears without its emitter merely because the node budget is tight.
  let remaining = Math.max(request.maxNodes - (center ? 1 : 0), 0);
  const visibleByKey = new Map<string, GraphNode[]>();
  [
    ["source-emitters", emitters],
    ["emitted-evidence", emitted],
    ["unconsolidated", unconsolidated]
  ].forEach(([key, members]) => {
    const list = members as GraphNode[];
    const visible = spacedSample(list, remaining);
    visibleByKey.set(key as string, visible);
    remaining -= visible.length;
  });
  const visibleIds = new Set<string>([
    ...(center ? [center.id] : []),
    ...[...visibleByKey.values()].flatMap((members) => members.map((node) => node.id))
  ]);

  const nodes: LayoutNode[] = [];
  if (center) nodes.push(makeNode(center, snapshotMs, [0, 0, 0], 0.44, { isHub: true, isRoot: true, ring: 0 }));

  const emitterAngles = new Map<string, number>();
  emitters.forEach((node, index) => {
    const angle = -Math.PI / 2 + (index / Math.max(emitters.length, 1)) * Math.PI * 2;
    emitterAngles.set(node.id, angle);
    if (!visibleIds.has(node.id)) return;
    const radius = 2.35;
    nodes.push(
      makeNode(node, snapshotMs, [Math.cos(angle) * radius, node.approved_state === "proposal" ? 0.45 : 0.08, Math.sin(angle) * radius], Math.max(nodeScale(node), 0.24), {
        isHub: true,
        ring: 1
      })
    );
  });

  const emittedByEmitter = new Map<string, GraphNode[]>();
  emitted.forEach((node) => {
    const emitterId = emittedBy.get(node.id) ?? "";
    const list = emittedByEmitter.get(emitterId) ?? [];
    list.push(node);
    emittedByEmitter.set(emitterId, list);
  });
  emittedByEmitter.forEach((members, emitterId) => {
    members.forEach((node, index) => {
      if (!visibleIds.has(node.id)) return;
      const centeredEmitter = emitterId === centerId;
      const baseAngle = centeredEmitter ? -Math.PI / 2 : emitterAngles.get(emitterId) ?? stableHash(emitterId) * Math.PI * 2;
      const width = centeredEmitter ? Math.PI * 2 : Math.min(0.64, Math.PI / Math.max(emitters.length, 3));
      const angle = centeredEmitter
        ? baseAngle + (index / Math.max(members.length, 1)) * Math.PI * 2
        : baseAngle + ((index + 0.5) / Math.max(members.length, 1) - 0.5) * width;
      const radius = centeredEmitter ? 1.28 + (index % 2) * 0.28 : 3.45 + Math.floor(index / 8) * 0.42;
      nodes.push(
        makeNode(node, snapshotMs, [Math.cos(angle) * radius, node.approved_state === "proposal" ? 0.48 : 0, Math.sin(angle) * radius], nodeScale(node), {
          ring: centeredEmitter ? 1 : 2
        })
      );
    });
  });

  unconsolidated.forEach((node, index) => {
    if (!visibleIds.has(node.id)) return;
    const ring = index % 3;
    const slot = Math.floor(index / 3);
    const slots = Math.max(Math.ceil(unconsolidated.length / 3), 1);
    const angle = -Math.PI / 2 + (slot / slots) * Math.PI * 2 + ring * 0.035;
    const radius = 4.85 + ring * 0.42;
    nodes.push(
      makeNode(node, snapshotMs, [Math.cos(angle) * radius, node.approved_state === "proposal" ? 0.42 : -0.04, Math.sin(angle) * radius], nodeScale(node) * 0.82, {
        ring: 3,
        faint: true
      })
    );
  });

  const buckets: SemanticBucket[] = [
    {
      key: "source-emitters",
      kind: "source_flow",
      labelKey: "emitters",
      members: [...(center && emitterIds.has(center.id) ? [center] : []), ...emitters],
      anchor: [0, 0.05, -2.95]
    },
    {
      key: "emitted-evidence",
      kind: "source_flow",
      labelKey: "emitted",
      members: emitted,
      anchor: [4.45, 0.05, 0]
    },
    {
      key: "unconsolidated",
      kind: "source_flow",
      labelKey: "unconsolidated",
      members: unconsolidated,
      anchor: [0, 0.05, 5.85]
    }
  ];
  const groups: WorldGroup[] = buckets.map((bucket) => {
    const visible = bucket.members.filter((node) => visibleIds.has(node.id));
    return {
      key: bucket.key,
      kind: bucket.kind,
      labelKey: bucket.labelKey,
      count: bucket.members.length,
      shown: visible.length,
      anchor: bucket.anchor,
      drill: null,
      memberIds: visible.map((node) => node.id)
    };
  });
  const clusterStars = buckets.flatMap((bucket) => {
    const hidden = bucket.members.filter((node) => !visibleIds.has(node.id));
    return hidden.length > 0
      ? [starFor(`source-star-${bucket.key}`, bucket.kind, bucket.labelKey, hidden, bucket.anchor, null)]
      : [];
  });

  const shown = nodes.length;
  return {
    perspective: "sources",
    level: 0,
    context: request.context,
    group: request.group,
    radial: "orbit",
    nodes,
    wedges: [],
    wedgeKind: "group",
    guides: [
      { kind: "circle", radius: 1.28, color: "#57d9a0", opacity: 0.16 },
      { kind: "circle", radius: 2.35, color: "#57d9a0", opacity: 0.34 },
      { kind: "circle", radius: 3.45, color: GUIDE_COLOR, opacity: 0.28 },
      { kind: "circle", radius: 5.27, color: "#ffb454", opacity: 0.18, dashed: true }
    ],
    groups,
    clusterStars,
    beacons: [],
    rInner: 1.28,
    rOuter: 5.7,
    deadlineF: DEADLINE_F,
    unknownR: null,
    totals: { total: request.nodes.length, shown, hidden: Math.max(request.nodes.length - shown, 0) },
    truncated: Math.max(request.nodes.length - shown, 0)
  };
}

// Work — an actionable queue around the same canonical center. Five stable
// spokes encode kinds of human work; supporting pages remain a quiet perimeter
// so changing view never swaps universes. Queue geometry is driven only by
// real action/proposal/source/gate-quality signals present on the node.

type WorkBucketKey = "blocked" | "proposal-review" | "source-sync" | "open-actions" | "review-needed" | "supporting-context";

const WORK_BUCKETS: { key: WorkBucketKey; labelKey: string; angle: number }[] = [
  { key: "blocked", labelKey: "blocked", angle: -Math.PI * 0.82 },
  { key: "proposal-review", labelKey: "proposals", angle: -Math.PI * 0.48 },
  { key: "source-sync", labelKey: "source_sync", angle: -Math.PI * 0.14 },
  { key: "open-actions", labelKey: "actions", angle: Math.PI * 0.2 },
  { key: "review-needed", labelKey: "review", angle: Math.PI * 0.54 },
  { key: "supporting-context", labelKey: "context", angle: Math.PI * 0.88 }
];

function activeMetric(node: GraphNode, metric: "actions" | "quality" | "evidence"): boolean {
  const value = node.overlay_metrics?.[metric];
  if (!value) return false;
  const state = value.state.toLowerCase();
  if (metric === "actions") {
    return value.count > 0 || (value.value ?? 0) > 0 || /open|blocked|overdue|review|pending/.test(state);
  }
  if (metric === "quality") {
    return value.count > 0 || (value.value ?? 0) > 0 || /fail|error|warn|risk|missing|conflict|low/.test(state);
  }
  // Evidence counts are positive when coverage is good, so only an explicit
  // gap state makes evidence a review item.
  return /gap|missing|weak|unknown|unconsolidated|no[_ -]?source/.test(state);
}

function workBucketFor(node: GraphNode): WorkBucketKey {
  const signals = [
    ...node.risk_flags,
    node.overlay_metrics?.actions.state ?? "",
    node.overlay_metrics?.quality.state ?? ""
  ].join(" ").toLowerCase();
  if (/block|fail|error|overdue/.test(signals)) return "blocked";
  if (node.approved_state === "proposal" || node.page_type === "proposal") return "proposal-review";
  if (isSourceEmitterType(node.page_type) && node.freshness_state !== "fresh") return "source-sync";
  if (familyOf(node) === "action" || activeMetric(node, "actions")) return "open-actions";
  if (node.freshness_state === "stale" || node.risk_flags.length > 0 || activeMetric(node, "quality") || activeMetric(node, "evidence")) {
    return "review-needed";
  }
  return "supporting-context";
}

function workSort(a: GraphNode, b: GraphNode): number {
  const aMetric = a.overlay_metrics?.actions;
  const bMetric = b.overlay_metrics?.actions;
  return (
    (bMetric?.count ?? 0) - (aMetric?.count ?? 0) ||
    (bMetric?.value ?? 0) - (aMetric?.value ?? 0) ||
    attentionFirst(a, b)
  );
}

function workLayout(request: WorldRequest): WorldLayout {
  const snapshotMs = snapshotClock(request.nodes, request.snapshotAt);
  const center = canonicalCenter(request);
  const centerId = center?.id ?? "";
  const membersByKey = new Map<WorkBucketKey, GraphNode[]>(WORK_BUCKETS.map((bucket) => [bucket.key, []]));
  request.nodes.forEach((node) => {
    if (node.id === centerId) return;
    membersByKey.get(workBucketFor(node))!.push(node);
  });
  membersByKey.forEach((members) => members.sort(workSort));

  const actionableBuckets = WORK_BUCKETS.slice(0, -1);
  const budget = Math.max(request.maxNodes - (center ? 1 : 0), 0);
  const visibleByKey = new Map<WorkBucketKey, GraphNode[]>(WORK_BUCKETS.map((bucket) => [bucket.key, []]));
  let remaining = budget;
  let rank = 0;
  const actionableLaneLimit = 12;
  // Round-robin across actionable lanes keeps a small lane visible even when
  // another has hundreds of items. Supporting context only uses spare budget.
  while (remaining > 0) {
    if (rank >= actionableLaneLimit) break;
    let added = false;
    actionableBuckets.forEach((bucket) => {
      if (remaining <= 0) return;
      const node = membersByKey.get(bucket.key)?.[rank];
      if (!node) return;
      visibleByKey.get(bucket.key)!.push(node);
      remaining -= 1;
      added = true;
    });
    if (!added) break;
    rank += 1;
  }
  const supporting = membersByKey.get("supporting-context") ?? [];
  // Supporting pages keep the shared world legible, but Work is an execution
  // surface rather than a second Atlas. A bounded quiet perimeter plus an
  // honest cluster count preserves context without burying the actionable
  // spokes in dozens of low-priority objects and relation lines.
  visibleByKey.set("supporting-context", spacedSample(supporting, Math.min(remaining, 12)));

  const visibleIds = new Set<string>([
    ...(center ? [center.id] : []),
    ...[...visibleByKey.values()].flatMap((members) => members.map((node) => node.id))
  ]);
  const nodes: LayoutNode[] = [];
  if (center) nodes.push(makeNode(center, snapshotMs, [0, 0, 0], 0.44, { isHub: true, isRoot: true, ring: 0 }));

  actionableBuckets.forEach((bucket, bucketIndex) => {
    const members = membersByKey.get(bucket.key) ?? [];
    members.forEach((node, index) => {
      if (!visibleIds.has(node.id)) return;
      const column = index % 7;
      const row = Math.floor(index / 7);
      const angle = bucket.angle + ((row % 5) - 2) * 0.075;
      const radius = 1.6 + column * 0.57 + Math.floor(row / 5) * 0.24;
      const lift = node.approved_state === "proposal" ? 0.5 : bucketIndex === 0 ? 0.22 : 0;
      nodes.push(makeNode(node, snapshotMs, [Math.cos(angle) * radius, lift, Math.sin(angle) * radius], nodeScale(node), { ring: bucketIndex + 1 }));
    });
  });
  supporting.forEach((node, index) => {
    if (!visibleIds.has(node.id)) return;
    const ring = index % 3;
    const slot = Math.floor(index / 3);
    const slots = Math.max(Math.ceil(supporting.length / 3), 1);
    const angle = -Math.PI / 2 + (slot / slots) * Math.PI * 2 + ring * 0.04;
    const radius = 5.15 + ring * 0.36;
    nodes.push(makeNode(node, snapshotMs, [Math.cos(angle) * radius, -0.05, Math.sin(angle) * radius], nodeScale(node) * 0.76, { ring: 6, faint: true }));
  });

  const buckets: SemanticBucket[] = WORK_BUCKETS.map((bucket) => ({
    key: bucket.key,
    kind: "work_queue",
    labelKey: bucket.labelKey,
    members: membersByKey.get(bucket.key) ?? [],
    anchor: [Math.cos(bucket.angle) * 6.05, 0.05, Math.sin(bucket.angle) * 6.05]
  }));
  const groups: WorldGroup[] = buckets.map((bucket) => {
    const visible = bucket.members.filter((node) => visibleIds.has(node.id));
    return {
      key: bucket.key,
      kind: bucket.kind,
      labelKey: bucket.labelKey,
      count: bucket.members.length,
      shown: visible.length,
      anchor: bucket.anchor,
      drill: null,
      memberIds: visible.map((node) => node.id)
    };
  });
  const clusterStars = buckets.flatMap((bucket) => {
    const hidden = bucket.members.filter((node) => !visibleIds.has(node.id));
    return hidden.length > 0
      ? [starFor(`work-star-${bucket.key}`, bucket.kind, bucket.labelKey, hidden, bucket.anchor, null)]
      : [];
  });
  const guides: WorldGuide[] = [
    ...actionableBuckets.map((bucket) => ({
      kind: "ray" as const,
      angle: bucket.angle,
      r0: 1.15,
      r1: 5.35,
      color: bucket.key === "blocked" ? "#ff7a8a" : bucket.key === "source-sync" ? "#57d9a0" : GUIDE_COLOR,
      opacity: bucket.key === "blocked" ? 0.4 : 0.28
    })),
    { kind: "circle" as const, radius: 5.5, color: GUIDE_COLOR, opacity: 0.16, dashed: true }
  ];

  const shown = nodes.length;
  return {
    perspective: "work",
    level: 0,
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
    rInner: 1.15,
    rOuter: 5.75,
    deadlineF: DEADLINE_F,
    unknownR: null,
    totals: { total: request.nodes.length, shown, hidden: Math.max(request.nodes.length - shown, 0) },
    truncated: Math.max(request.nodes.length - shown, 0)
  };
}

// ---------------------------------------------------------------------------

export function computeWorldLayout(request: WorldRequest): WorldLayout {
  if (request.perspective === "atlas") return atlasLayout(request);
  if (request.perspective === "districts") return districtsLayout(request);
  if (request.perspective === "trails") return trailsLayout(request);
  if (request.perspective === "focus") return focusLayout(request);
  if (request.perspective === "quadrants") return quadrantsLayout(request);
  if (request.perspective === "sources") return sourcesLayout(request);
  if (request.perspective === "work") return workLayout(request);
  return radarLayout(request);
}

// Quadrants — the AQAL home map: WHERE EVERYTHING LIVES. Four deterministic
// 2x2 territories carry each page's compiled home quadrant (with page type only
// as fallback), while q0-core occupies a neutral spine. radial="shelf" means
// geometry encodes territory/family depth and freshness remains a visual tone,
// never a second positional axis. All four groups remain present even when one
// is honestly empty; core is structure, not a fifth quadrant.
function quadrantsLayout(request: WorldRequest): WorldLayout {
  const snapshotMs = snapshotClock(request.nodes, request.snapshotAt);
  const rInner = 1.1;
  const rOuter = 6.4;
  const drillROuter = 3.6;
  const centerCandidate = request.centerId && request.nodes.some((node) => node.id === request.centerId)
    ? request.centerId
    : null;
  const rootId = centerCandidate ?? rootNodeId(request.nodes);
  const rootNode = request.nodes.find((node) => node.id === rootId) ?? null;
  const regionMembers = new Map<SceneFacet, GraphNode[]>(SCENE_FACETS.map((facet) => [facet, []]));
  const coreMembers: GraphNode[] = [];
  request.nodes.forEach((node) => {
    if (isActiveCenterEquivalent(node, rootNode)) return;
    const home = nodeQuadrant(node.id, node.page_type, request.quadrantHomes);
    if (home) regionMembers.get(home)!.push(node);
    else coreMembers.push(node);
  });

  const guides: WorldGuide[] = [0, Math.PI / 2, Math.PI, (3 * Math.PI) / 2].map((angle) => ({
    kind: "ray" as const,
    angle,
    r0: 0.72,
    r1: rOuter + 0.3,
    color: GUIDE_COLOR,
    opacity: 0.3
  }));

  const nodes: LayoutNode[] = [];
  const clusterStars: ClusterStar[] = [];
  const groups: WorldGroup[] = [];
  const activeFamilyGroup = parseRealFamilyGroupId(request.group);
  const selectedQuadrant = request.quadrant;

  if (activeFamilyGroup) {
    // A quadrant selector is a lens, never a data filter. Family routes must
    // therefore resolve the same members and positions under all four lenses.
    const worldMembers = [...regionMembers.values()].flat();
    const familyMembers = worldMembers.filter((node) => familyLabelKey(familyOf(node)) === activeFamilyGroup.family).sort(attentionFirst);
    const familyEntries = [...groupByFamily(worldMembers).entries()].sort((a, b) => familyRank(a[0]) - familyRank(b[0]) || a[0].localeCompare(b[0]));
    const parentSpans = allocateWedgeSpans(familyEntries.map(([family, list]) => ({ key: family, weight: list.length })));
    const parentSpan = parentSpans.find((span) => span.key === activeFamilyGroup.family);
    const parentIndex = parentSpan ? parentSpans.findIndex((span) => span.key === activeFamilyGroup.family) : -1;
    const drillOrigin = parentSpan
      ? regionFamilyAnchorInCenteredRegion(familyMembers, parentSpan.centerAngle, parentIndex, parentSpans.length)
      : null;
    const centerKey = activeFamilyGroup.key;
    if (rootNode) {
      nodes.push(makeNode(rootNode, snapshotMs, [0, 0, 0], 0.46, { isHub: true, isRoot: true, ring: 0 }));
    }
    const visible = familyMembers.slice(0, visibleFamilyChildLimit(familyMembers.length, Math.max(request.maxNodes - 1, 8)));
    const hidden = familyMembers.slice(visible.length);
    const pageNodes = familyDrillPageNodes(visible, snapshotMs);
    nodes.push(...pageNodes);
    const siblingFamilies = surroundingFamilyNodes(activeFamilyGroup.family, familyEntries, rootNode, 2.85);
    nodes.push(...siblingFamilies);
    if (hidden.length > 0) {
      clusterStars.push(starFor(`qstar-${centerKey}`, "family", activeFamilyGroup.family, hidden, [0, 0, drillROuter], null));
    }
    groups.push({
      key: centerKey,
      kind: "family",
      labelKey: activeFamilyGroup.family,
      count: familyMembers.length,
      shown: visible.length,
      anchor: [0, 0.05, drillROuter + 0.25],
      drill: null,
      memberIds: visible.map((node) => node.id).sort()
    });
    const canonicalShown = (rootNode ? 1 : 0) + visible.length;
    const canonicalTotal = (rootNode ? 1 : 0) + familyMembers.length;
    return {
      perspective: "quadrants",
      level: 2,
      group: request.group,
      radial: "orbit",
      nodes,
      wedges: [],
      wedgeKind: "group",
      guides,
      groups,
      clusterStars,
      beacons: [],
      rInner,
      rOuter: drillROuter,
      deadlineF: DEADLINE_F,
      unknownR: null,
      totals: { total: canonicalTotal, shown: canonicalShown, hidden: hidden.length },
      truncated: hidden.length,
      ...(drillOrigin ? { drillOrigin } : {}),
      ...(selectedQuadrant ? { cameraTarget: quadrantRegionPosition(selectedQuadrant, rInner, rOuter) } : {})
    };
  }

  const renderedPageIds = new Set<string>();
  if (rootNode) {
    nodes.push(makeNode(rootNode, snapshotMs, [0, 0, 0], 0.42, { isHub: true, isRoot: true }));
    renderedPageIds.add(rootNode.id);
  }

  SCENE_FACETS.forEach((facet) => {
    const center = QUADRANT_CENTER_ANGLE[facet];
    const members = [...regionMembers.get(facet)!].sort(attentionFirst);
    const byFamily = groupByFamily(members);
    const families = [...byFamily.entries()].sort((a, b) => familyRank(a[0]) - familyRank(b[0]) || a[0].localeCompare(b[0]));
    const regionMemberIds: string[] = [];
    families.forEach(([family, list], index) => {
      const key = realFamilyGroupId(family);
      const visualNodeId = regionFamilyDrillKey(facet, family);
      const familyAnchor = quadrantFamilyTerritoryAnchor(facet, list, index, families.length, rInner, rOuter);
      if (shouldAggregateFamily(list)) {
        const familyGroupNode = makeGroupNode(
          key,
          "family",
          family,
          pageTypeLabel(`visual_group_${family}`),
          rootNode?.context || "system",
          list,
          familyAnchor,
          familyGroupScale(list.length, 0),
          { group: key },
          { ring: 1, nodeId: visualNodeId }
        );
        nodes.push(familyGroupNode);
        const previews = previewNodesAround(
          visualNodeId,
          list,
          snapshotMs,
          familyAnchor,
          0.32,
          3
        );
        previews.forEach((node) => renderedPageIds.add(node.id));
        nodes.push(...previews);
        regionMemberIds.push(...previews.map((node) => node.id));
      } else {
        const pageNodes = pageNodesInTerritory(list, snapshotMs, familyAnchor);
        pageNodes.forEach((node) => renderedPageIds.add(node.id));
        nodes.push(...pageNodes);
        regionMemberIds.push(...pageNodes.map((node) => node.id));
      }
    });
    const rimRadius = rOuter + 0.36;
    const rim: [number, number, number] = [Math.cos(center) * rimRadius, 0.05, Math.sin(center) * rimRadius];
    groups.push({
      key: facet,
      kind: "quadrant",
      labelKey: facet,
      count: members.length,
      shown: regionMemberIds.length,
      anchor: rim,
      drill: null,
      memberIds: regionMemberIds.sort()
    });
  });

  const coreOrdered = [...coreMembers].sort((a, b) => a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
  coreOrdered.slice(0, 12).forEach((node, index) => {
    // q0-core owns the neutral vertical spine between the left/right
    // territories. It stays out of every authoritative cell and never crowds
    // the active root at the origin.
    const side = index % 2 === 0 ? -1 : 1;
    const distance = 1.35 + Math.floor(index / 2) * 0.62;
    nodes.push(makeNode(node, snapshotMs, [0, -0.08, side * distance], nodeScale(node) * 0.85));
    renderedPageIds.add(node.id);
  });
  if (coreOrdered.length > 12) {
    clusterStars.push(
      starFor("qstar-core", "core", "core", coreOrdered.slice(12), [0, 0, rOuter + 0.55], null)
    );
  }
  if (coreMembers.length > 0) {
    groups.push({
      key: "__core__",
      kind: "core",
      labelKey: "core",
      count: coreMembers.length,
      shown: Math.min(coreMembers.length, 12),
      anchor: [0, 0.05, rOuter + 0.35],
      drill: null,
      memberIds: coreOrdered.slice(0, 12).map((node) => node.id).sort()
    });
  }

  const total = (rootNode ? 1 : 0) + [...regionMembers.values()].reduce((sum, list) => sum + list.length, 0) + coreMembers.length;
  const shown = renderedPageIds.size;
  const hidden = Math.max(total - shown, 0);
  const cameraTarget: [number, number, number] | undefined = selectedQuadrant
    ? quadrantRegionPosition(selectedQuadrant, rInner, rOuter)
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
    totals: { total, shown, hidden },
    truncated: hidden,
    cameraTarget
  };
}

// Focus — the page-centered multi-perspective view. Structurally trails, but
// its four sectors are the FACETS (Identity & intent / Outputs & evidence /
// Culture & relations / Systems & governance),
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
  // Focus is centered on the explicit world center. A selected/read page is
  // not allowed to steal that role. Legacy requests without centerId still
  // accept pageId; a requested ID outside this graph yields the honest empty
  // layout rather than silently re-centering on the wiki root.
  const requestedCenterId = request.centerId ?? request.pageId;
  const centerId = requestedCenterId
    ? byId.has(requestedCenterId)
      ? byId.get(requestedCenterId)!.id
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
      perspective: "focus", level: requestedCenterId ? 3 : 0, context: request.context, group: undefined,
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
