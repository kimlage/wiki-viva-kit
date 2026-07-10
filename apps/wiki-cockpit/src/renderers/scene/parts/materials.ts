// Scene materials + edge selection: the shared visual vocabulary of the world.
// Trust/state annotations, overlay-body helpers, shape mapping, the WebGL /
// reduced-motion fallback gates, and the edge emphasis/selection pipeline.
// Pure functions and constants — no React, no three.js objects.

import { t } from "../../../data/i18n";
import { isMetaPage, pageTypeStyle, trustColor } from "../../../data/presentation";
import { visualEncodingResolver } from "../../../data/visualEncoding";
import type { GitState, GraphEdge } from "../../../types";
import type { LayoutNode, ScenePerformanceProfile } from "../../../scene/layout";
import type { OverlayId } from "../../../world/contracts";
import type { WorldLayout } from "../../../scene/perspectives";
import type { RelationIsolation } from "../../../components/SystemScene";

export function canUseWebGL(): boolean {
  if (typeof document === "undefined") return false;
  const canvas = document.createElement("canvas");
  try {
    return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function isVisualTestMode(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("visual") === "1";
}

export type SceneFallbackReason = "visual_test" | "reduced_motion" | "webgl_unavailable" | "performance_budget";

export function sceneFallbackReason(): SceneFallbackReason | null {
  if (isVisualTestMode()) return "visual_test";
  if (prefersReducedMotion()) return "reduced_motion";
  if (!canUseWebGL()) return "webgl_unavailable";
  return null;
}

export function shouldUseFallback(): boolean {
  return sceneFallbackReason() !== null;
}

// Exposed so the shell can route surfaces: the SPATIAL creation/founding flows
// live in the canvas; in fallback mode their 2D twins (sheet, DOM cards) are
// the declared alternative.
export function sceneFallbackPreferred(): boolean {
  return shouldUseFallback();
}

export function allowAmbientMotion(): boolean {
  if (isVisualTestMode() || prefersReducedMotion()) return false;
  if (typeof document !== "undefined" && document.visibilityState === "hidden") return false;
  return true;
}

export function freshnessLabel(state: string): string {
  if (state === "fresh") return t("trust.ok");
  if (state === "stale") return t("trust.needsRefresh");
  return t("trust.notChecked");
}

export function workspaceLabel(git: GitState): string {
  if (git.proposal.is_proposal_branch) return git.proposal.theme ? `review: ${git.proposal.theme}` : "review workspace";
  if (git.current_branch === git.default_branch) return "approved workspace";
  return "current workspace";
}

export type TrustKey = "fresh" | "stale" | "unknown" | "proposal";

export function nodeTrustKey(node: Pick<LayoutNode, "approved_state" | "freshness_state">): TrustKey {
  if (node.approved_state === "proposal") return "proposal";
  if (node.freshness_state === "fresh") return "fresh";
  if (node.freshness_state === "stale") return "stale";
  return "unknown";
}

// State → material treatment. Since the re-encoding, the node BODY hue is the
// context identity (per-instance colors, see InstancedNodeMesh); this table
// keeps what per-instance attributes cannot express: per-state emissive
// (attention glows — amber heat for stale, purple for drafts), opacity (the
// unknown veil) and the glow-sprite gate. Salience inversion survives: fresh
// bodies sit in a calm lightness band with no emissive; problems radiate.
export const TRUST_MATERIALS: Record<TrustKey | "root", { emissiveIntensity: number; opacity: number; glows: boolean }> = {
  fresh: { emissiveIntensity: 0.05, opacity: 1, glows: false },
  stale: { emissiveIntensity: 1.1, opacity: 1, glows: true },
  proposal: { emissiveIntensity: 1.0, opacity: 1, glows: true },
  unknown: { emissiveIntensity: 0, opacity: 0.6, glows: false },
  root: { emissiveIntensity: 0.9, opacity: 1, glows: true }
};

export function trustMaterial(node: LayoutNode) {
  if (node.isRoot) return TRUST_MATERIALS.root;
  return TRUST_MATERIALS[nodeTrustKey(node)];
}

// The same active-overlay token paints WebGL bodies and their 2D twins.
// Context is deliberately not an input: it remains position/label/keyline.
export function nodeDisplayColor(node: LayoutNode, overlay: OverlayId): string {
  return visualEncodingResolver.resolve(node, overlay).color;
}

// State ANNOTATION color (glow sprites, chips, guides): the trust palette
// survives as the state accent language even though it no longer paints
// node bodies.
export function trustDisplayColor(node: LayoutNode): string {
  if (node.isRoot) return trustColor("root");
  return trustColor(nodeTrustKey(node));
}

export type SuperShape = "sphere" | "crystal" | "hub" | "frame" | "source" | "comet" | "slab" | "spark" | "totem";

export function superShape(pageType: string): SuperShape {
  // META pages (molds: template_block/skill/perspective) render as BLUEPRINTS —
  // a wireframe partition of their own. The plant vs the building, literally.
  if (isMetaPage(pageType)) return "frame";
  const style = pageTypeStyle(pageType);
  if (style.family === "source") return "source";
  if (style.family === "person" || style.shape === "totem") return "totem";
  if (style.shape === "crystal" || style.shape === "diamond") return "crystal";
  if (style.shape === "comet") return "comet";
  if (style.shape === "slab") return "slab";
  if (style.shape === "spark") return "spark";
  if (style.shape === "hub") return "hub";
  if (style.family === "hub" || style.family === "root") return "hub";
  return "sphere";
}

export function layoutNodeIndex(layout: WorldLayout): Map<string, LayoutNode> {
  const index = new Map<string, LayoutNode>();
  layout.nodes.forEach((node) => {
    index.set(node.id, node);
    index.set(node.path, node);
  });
  return index;
}

// ---------------------------------------------------------------------------
// Edges

const EDGE_PRIORITY: Record<string, number> = {
  pr_impact: 5,
  ingestion_chain: 4,
  source_ref: 3,
  collection_member: 2,
  moc_parent: 2,
  markdown_link: 1
};

const EDGE_REST_OPACITY: Record<string, number> = {
  pr_impact: 0.9,
  ingestion_chain: 0.8,
  source_ref: 0.42,
  collection_member: 0.2,
  moc_parent: 0.18,
  markdown_link: 0
};

export type SceneEdge = {
  from: LayoutNode;
  to: LayoutNode;
  type: string;
  emphasis: number;
};

export type RelationLane = {
  type: string;
  count: number;
  share: number;
  rank: number;
};

export type GroupRelationBundle = {
  key: string;
  type: string;
  count: number;
  incoming: number;
  outgoing: number;
  flow: "in" | "out" | "mixed";
  share: number;
  rank: number;
  targetId: string;
  targetLabel: string;
  from: [number, number, number];
  to: [number, number, number];
};

function isPageDrillLayout(layout: WorldLayout): boolean {
  const root = layout.nodes.find((node) => node.isRoot);
  return layout.perspective === "quadrants" && layout.level >= 3 && Boolean(root && !root.isGroup);
}

export function relationLanesForLayout(edges: GraphEdge[], layout: WorldLayout, maxLanes = 4): RelationLane[] {
  if (layout.perspective !== "quadrants" || layout.level < 1) return [];
  if (isPageDrillLayout(layout)) return [];
  const index = layoutNodeIndex(layout);
  const counts = new Map<string, number>();
  for (const edge of edges) {
    if (edge.type === "markdown_link") continue;
    const from = index.get(edge.source);
    const to = index.get(edge.target);
    if (!from || !to || from.id === to.id) continue;
    counts.set(edge.type, (counts.get(edge.type) ?? 0) + 1);
  }
  const total = [...counts.values()].reduce((sum, count) => sum + count, 0);
  if (total <= 0) return [];
  return [...counts.entries()]
    .map(([type, count]) => ({
      type,
      count,
      share: count / total,
      rank: EDGE_PRIORITY[type] ?? 0
    }))
    .sort((a, b) => b.count - a.count || b.rank - a.rank || a.type.localeCompare(b.type))
    .slice(0, maxLanes);
}

function groupMemberSet(node: LayoutNode): Set<string> {
  return new Set(node.groupMemberIds ?? []);
}

function dominantRelation(counts: Map<string, number>): { type: string; count: number; rank: number } | null {
  const ranked = [...counts.entries()]
    .map(([type, count]) => ({ type, count, rank: EDGE_PRIORITY[type] ?? 0 }))
    .sort((a, b) => b.count - a.count || b.rank - a.rank || a.type.localeCompare(b.type));
  return ranked[0] ?? null;
}

function rootOverviewGroupRelationBundles(edges: GraphEdge[], layout: WorldLayout, maxBundles: number): GroupRelationBundle[] {
  const groups = layout.nodes
    .filter((node) => node.isGroup && node.groupKind === "region_family" && (node.groupMemberIds?.length ?? 0) > 0)
    .sort((a, b) => (b.groupMemberIds?.length ?? 0) - (a.groupMemberIds?.length ?? 0) || a.id.localeCompare(b.id));
  if (groups.length < 2) return [];
  const memberToGroup = new Map<string, LayoutNode>();
  groups.forEach((group) => {
    group.groupMemberIds?.forEach((memberId) => memberToGroup.set(memberId, group));
  });
  const pairMap = new Map<
    string,
    {
      a: LayoutNode;
      b: LayoutNode;
      counts: Map<string, number>;
      aToB: number;
      bToA: number;
      total: number;
      crossFacet: boolean;
    }
  >();

  for (const edge of edges) {
    if (edge.type === "markdown_link") continue;
    const sourceGroup = memberToGroup.get(edge.source);
    const targetGroup = memberToGroup.get(edge.target);
    if (!sourceGroup || !targetGroup || sourceGroup.id === targetGroup.id) continue;
    const [a, b] = sourceGroup.id.localeCompare(targetGroup.id) <= 0 ? [sourceGroup, targetGroup] : [targetGroup, sourceGroup];
    const key = `${a.id}<->${b.id}`;
    const aFacet = parseRegionFacet(a.id);
    const bFacet = parseRegionFacet(b.id);
    const entry =
      pairMap.get(key) ??
      {
        a,
        b,
        counts: new Map<string, number>(),
        aToB: 0,
        bToA: 0,
        total: 0,
        crossFacet: Boolean(aFacet && bFacet && aFacet !== bFacet)
      };
    entry.counts.set(edge.type, (entry.counts.get(edge.type) ?? 0) + 1);
    entry.total += 1;
    if (sourceGroup.id === a.id) entry.aToB += 1;
    else entry.bToA += 1;
    pairMap.set(key, entry);
  }

  const total = [...pairMap.values()].reduce((sum, entry) => sum + entry.total, 0);
  if (total <= 0) return [];
  return [...pairMap.values()]
    .map((entry): GroupRelationBundle | null => {
      const dominant = dominantRelation(entry.counts);
      if (!dominant) return null;
      const from = entry.bToA > entry.aToB ? entry.b : entry.a;
      const to = from.id === entry.a.id ? entry.b : entry.a;
      const forward = from.id === entry.a.id ? entry.aToB : entry.bToA;
      const backward = from.id === entry.a.id ? entry.bToA : entry.aToB;
      const flow: GroupRelationBundle["flow"] = forward > 0 && backward > 0 ? "mixed" : "out";
      return {
        key: `${from.id}->${to.id}:${dominant.type}`,
        type: dominant.type,
        count: entry.total,
        incoming: backward,
        outgoing: forward,
        flow,
        share: entry.total / total,
        rank: dominant.rank + (entry.crossFacet ? 2 : 0),
        targetId: to.id,
        targetLabel: to.title,
        from: from.position,
        to: to.position
      } satisfies GroupRelationBundle;
    })
    .filter((bundle): bundle is GroupRelationBundle => Boolean(bundle))
    .sort((a, b) => b.count - a.count || b.rank - a.rank || a.key.localeCompare(b.key))
    .slice(0, maxBundles);
}

function parseRegionFacet(key: string): string | null {
  const parts = key.split(":");
  return parts[0] === "region" && parts[1] ? parts[1] : null;
}

export function groupRelationBundlesForLayout(edges: GraphEdge[], layout: WorldLayout, maxBundles = layout.level >= 2 ? 4 : 6): GroupRelationBundle[] {
  if (layout.perspective !== "quadrants") return [];
  if (layout.level === 0) return rootOverviewGroupRelationBundles(edges, layout, maxBundles);
  if (layout.level < 1) return [];
  if (isPageDrillLayout(layout)) return [];
  const center = layout.nodes.find((node) => node.isRoot && node.isGroup);
  if (!center?.groupMemberIds?.length) return [];
  const centerMembers = groupMemberSet(center);
  const candidates = layout.nodes
    .filter((node) => node.isGroup && node.id !== center.id && node.groupKind === "region_family" && (node.groupMemberIds?.length ?? 0) > 0)
    .sort((a, b) => (b.groupMemberIds?.length ?? 0) - (a.groupMemberIds?.length ?? 0) || a.id.localeCompare(b.id));
  const totalByCandidate = new Map<string, { node: LayoutNode; counts: Map<string, number>; total: number }>();
  const directionByCandidate = new Map<string, { incoming: number; outgoing: number }>();
  candidates.forEach((node) => {
    totalByCandidate.set(node.id, { node, counts: new Map(), total: 0 });
    directionByCandidate.set(node.id, { incoming: 0, outgoing: 0 });
  });

  for (const edge of edges) {
    if (edge.type === "markdown_link") continue;
    const sourceInCenter = centerMembers.has(edge.source);
    const targetInCenter = centerMembers.has(edge.target);
    if (!sourceInCenter && !targetInCenter) continue;
    for (const candidate of candidates) {
      const members = groupMemberSet(candidate);
      const sourceInGroup = members.has(edge.source);
      const targetInGroup = members.has(edge.target);
      if (!sourceInGroup && !targetInGroup) continue;
      // Internal child-family links are already encoded by the child object.
      // The bundle answers "what connects this group to the open center/world?".
      if (sourceInGroup && targetInGroup) continue;
      const entry = totalByCandidate.get(candidate.id);
      const direction = directionByCandidate.get(candidate.id);
      if (!entry) continue;
      entry.counts.set(edge.type, (entry.counts.get(edge.type) ?? 0) + 1);
      entry.total += 1;
      if (direction) {
        if (sourceInCenter && targetInGroup) direction.outgoing += 1;
        if (sourceInGroup && targetInCenter) direction.incoming += 1;
      }
    }
  }

  const total = [...totalByCandidate.values()].reduce((sum, entry) => sum + entry.total, 0);
  if (total <= 0) return [];
  return [...totalByCandidate.values()]
    .map((entry) => {
      const dominant = dominantRelation(entry.counts);
      if (!dominant) return null;
      const direction = directionByCandidate.get(entry.node.id) ?? { incoming: 0, outgoing: 0 };
      const flow =
        direction.incoming > 0 && direction.outgoing > 0
          ? "mixed"
          : direction.incoming > direction.outgoing
            ? "in"
            : "out";
      return {
        key: `${center.id}->${entry.node.id}:${dominant.type}`,
        type: dominant.type,
        count: entry.total,
        incoming: direction.incoming,
        outgoing: direction.outgoing,
        flow,
        share: entry.total / total,
        rank: dominant.rank,
        targetId: entry.node.id,
        targetLabel: entry.node.title,
        from: center.position,
        to: entry.node.position
      } satisfies GroupRelationBundle;
    })
    .filter((bundle): bundle is GroupRelationBundle => Boolean(bundle))
    .sort((a, b) => b.count - a.count || b.rank - a.rank || a.targetId.localeCompare(b.targetId))
    .slice(0, maxBundles);
}

function edgeEmphasis(
  edge: { from: LayoutNode; to: LayoutNode; type: string },
  focusIds: Set<string>,
  highlightedIds: Set<string>,
  quality: string,
  mocEmphasis: boolean,
  rootOverview: boolean,
  familyOverview: boolean,
  quadrantDrillOverview: boolean
): number {
  const touchesFocus =
    focusIds.size > 0 && [edge.from.id, edge.from.path, edge.to.id, edge.to.path].some((key) => focusIds.has(key));
  const insideHighlight =
    highlightedIds.size > 0 &&
    (highlightedIds.has(edge.from.id) || highlightedIds.has(edge.from.path)) &&
    (highlightedIds.has(edge.to.id) || highlightedIds.has(edge.to.path));
  if (touchesFocus) return edge.type === "markdown_link" ? 0.65 : 1;
  if (insideHighlight && edge.type === "pr_impact") return 1;
  let rest = EDGE_REST_OPACITY[edge.type] ?? 0.3;
  // Atlas raises the solid hierarchy web — it IS the perspective.
  if (mocEmphasis && (edge.type === "moc_parent" || edge.type === "collection_member")) rest = 0.55;
  if (rootOverview) {
    const rootScale: Record<string, number> = {
      pr_impact: 0.75,
      ingestion_chain: 0.52,
      source_ref: 0.36,
      collection_member: 0.34,
      moc_parent: 0.34,
      markdown_link: 0
    };
    rest *= rootScale[edge.type] ?? 0.35;
  }
  if (familyOverview) {
    const familyScale: Record<string, number> = {
      pr_impact: 0.62,
      ingestion_chain: 0.42,
      source_ref: 0.28,
      collection_member: 0.3,
      moc_parent: 0.3,
      markdown_link: 0
    };
    rest *= familyScale[edge.type] ?? 0.24;
  } else if (quadrantDrillOverview) {
    const drillScale: Record<string, number> = {
      pr_impact: 0.58,
      ingestion_chain: 0.36,
      source_ref: 0.24,
      collection_member: 0.26,
      moc_parent: 0.26,
      markdown_link: 0
    };
    rest *= drillScale[edge.type] ?? 0.22;
  }
  const ambient = edge.type === "markdown_link" ? (quality === "rich" ? 0.08 : 0) : rest;
  return focusIds.size > 0 ? ambient * 0.25 : ambient;
}

function relationEdgeMatch(relation: RelationIsolation, edge: GraphEdge, selectedKeys: Set<string>): boolean {
  const fromSelected = selectedKeys.has(edge.source);
  const toSelected = selectedKeys.has(edge.target);
  if (!fromSelected && !toSelected) return false;
  if (relation === "hierarquia") return edge.type === "moc_parent" || edge.type === "collection_member";
  if (relation === "evidencia") return edge.type === "source_ref" || edge.type === "ingestion_chain";
  if (relation === "links") return edge.type === "markdown_link" && fromSelected;
  return edge.type === "markdown_link" && toSelected;
}

export function selectSceneEdges(
  edges: GraphEdge[],
  layout: WorldLayout,
  focusIds: Set<string>,
  highlightedIds: Set<string>,
  profile: ScenePerformanceProfile,
  isolateRelation: RelationIsolation | null,
  selectedKeys: Set<string>
): SceneEdge[] {
  const index = layoutNodeIndex(layout);
  const mapped: (SceneEdge & { sortKey: string })[] = [];
  const rootOverview =
    layout.perspective === "quadrants" &&
    layout.level === 0 &&
    !isolateRelation &&
    focusIds.size === 0 &&
    highlightedIds.size === 0;
  const pageDrillOverview =
    isPageDrillLayout(layout) &&
    !isolateRelation &&
    focusIds.size === 0 &&
    highlightedIds.size === 0;
  const familyOverview =
    layout.perspective === "quadrants" &&
    layout.level >= 2 &&
    !pageDrillOverview &&
    !isolateRelation &&
    focusIds.size === 0 &&
    highlightedIds.size === 0;
  const quadrantDrillOverview =
    layout.perspective === "quadrants" &&
    layout.level >= 1 &&
    !pageDrillOverview &&
    !isolateRelation &&
    focusIds.size === 0 &&
    highlightedIds.size === 0;
  for (const edge of edges) {
    const from = index.get(edge.source);
    const to = index.get(edge.target);
    if (!from || !to || from.id === to.id) continue;
    if (isolateRelation && selectedKeys.size > 0) {
      if (!relationEdgeMatch(isolateRelation, edge, selectedKeys)) continue;
      mapped.push({ from, to, type: edge.type, emphasis: 1, sortKey: `${edge.source}->${edge.target}:${edge.type}` });
      continue;
    }
    const emphasis = edgeEmphasis(
      { from, to, type: edge.type },
      focusIds,
      highlightedIds,
      profile.quality,
      layout.perspective === "atlas",
      rootOverview,
      familyOverview,
      quadrantDrillOverview
    );
    if (emphasis <= 0.01) continue;
    mapped.push({ from, to, type: edge.type, emphasis, sortKey: `${edge.source}->${edge.target}:${edge.type}` });
  }
  const sorted = mapped.sort(
    (a, b) =>
      Number(b.emphasis >= 1) - Number(a.emphasis >= 1) ||
      (EDGE_PRIORITY[b.type] ?? 0) - (EDGE_PRIORITY[a.type] ?? 0) ||
      b.from.inbound_links + b.to.inbound_links - (a.from.inbound_links + a.to.inbound_links) ||
      a.sortKey.localeCompare(b.sortKey)
  );
  return applyEdgeBudget(sorted, profile, rootOverview, familyOverview, quadrantDrillOverview, pageDrillOverview);
}

function evidenceFlowBudget(layout: WorldLayout, quality: string): number {
  const rich = quality === "rich";
  const balanced = quality === "balanced";
  if (layout.perspective === "quadrants" && layout.level === 0) return rich ? 10 : balanced ? 7 : 4;
  if (layout.perspective === "quadrants" && layout.level >= 3) return rich ? 5 : balanced ? 3 : 2;
  if (layout.perspective === "quadrants" && layout.level >= 2) return rich ? 6 : balanced ? 4 : 2;
  if (layout.perspective === "quadrants" && layout.level >= 1) return rich ? 8 : balanced ? 5 : 3;
  return rich ? 12 : balanced ? 8 : 4;
}

function evidenceFlowTypeCap(type: string, maxTotal: number): number {
  if (type === "ingestion_chain") return Math.max(1, Math.ceil(maxTotal * 0.45));
  if (type === "source_ref") return Math.max(1, Math.ceil(maxTotal * 0.65));
  return 0;
}

function evidenceFlowScore(edge: SceneEdge): number {
  const attention = (node: LayoutNode) =>
    (node.freshness_state === "stale" ? 14 : 0) +
    (node.approved_state === "proposal" ? 12 : 0) +
    node.risk_flags.length * 10 +
    (node.source_ref_count > 0 ? Math.min(12, node.source_ref_count * 2) : 0);
  const relation = EDGE_PRIORITY[edge.type] ?? 0;
  const connectivity = edge.from.inbound_links + edge.to.inbound_links + (edge.from.outbound_links + edge.to.outbound_links) * 0.35;
  return relation * 100 + edge.emphasis * 40 + attention(edge.from) + attention(edge.to) + connectivity;
}

export function selectEvidenceFlowEdges(sceneEdges: SceneEdge[], layout: WorldLayout, quality: string): SceneEdge[] {
  const maxTotal = evidenceFlowBudget(layout, quality);
  if (maxTotal <= 0) return [];
  const byType = new Map<string, number>();
  const picked: SceneEdge[] = [];
  const candidates = sceneEdges
    .filter((edge) => edge.type === "source_ref" || edge.type === "ingestion_chain")
    .map((edge) => ({
      edge,
      score: evidenceFlowScore(edge),
      key: `${edge.from.id}->${edge.to.id}:${edge.type}`
    }))
    .sort((a, b) => b.score - a.score || a.key.localeCompare(b.key));

  for (const candidate of candidates) {
    if (picked.length >= maxTotal) break;
    const nextCount = (byType.get(candidate.edge.type) ?? 0) + 1;
    if (nextCount > evidenceFlowTypeCap(candidate.edge.type, maxTotal)) continue;
    byType.set(candidate.edge.type, nextCount);
    picked.push(candidate.edge);
  }
  return picked;
}

function rootOverviewTypeCap(type: string, quality: string): number {
  const rich = quality === "rich";
  const balanced = quality === "balanced";
  const caps: Record<string, number> = {
    pr_impact: rich ? 2 : balanced ? 1 : 1,
    ingestion_chain: rich ? 3 : balanced ? 2 : 1,
    source_ref: rich ? 2 : balanced ? 1 : 1,
    collection_member: rich ? 2 : balanced ? 1 : 1,
    moc_parent: rich ? 2 : balanced ? 1 : 1,
    markdown_link: 0
  };
  return caps[type] ?? (rich ? 4 : 2);
}

function rootOverviewEdgeBudget(quality: string): number {
  if (quality === "rich") return 8;
  if (quality === "balanced") return 5;
  return 3;
}

function rootOverviewCenterTouchBudget(_quality: string): number {
  return 1;
}

function familyOverviewTypeCap(type: string, quality: string): number {
  const rich = quality === "rich";
  const balanced = quality === "balanced";
  const caps: Record<string, number> = {
    pr_impact: rich ? 3 : 2,
    ingestion_chain: rich ? 3 : balanced ? 2 : 1,
    source_ref: rich ? 4 : balanced ? 3 : 2,
    collection_member: rich ? 3 : balanced ? 2 : 1,
    moc_parent: rich ? 3 : balanced ? 2 : 1,
    markdown_link: 0
  };
  return caps[type] ?? (rich ? 2 : 1);
}

function familyOverviewEdgeBudget(quality: string): number {
  if (quality === "rich") return 10;
  if (quality === "balanced") return 7;
  return 4;
}

function quadrantDrillTypeCap(type: string, quality: string): number {
  const rich = quality === "rich";
  const balanced = quality === "balanced";
  const caps: Record<string, number> = {
    pr_impact: rich ? 3 : balanced ? 2 : 1,
    ingestion_chain: rich ? 4 : balanced ? 3 : 1,
    source_ref: rich ? 5 : balanced ? 3 : 2,
    collection_member: rich ? 3 : balanced ? 2 : 1,
    moc_parent: rich ? 3 : balanced ? 2 : 1,
    markdown_link: 0
  };
  return caps[type] ?? (rich ? 2 : 1);
}

function quadrantDrillEdgeBudget(quality: string): number {
  if (quality === "rich") return 12;
  if (quality === "balanced") return 8;
  return 5;
}

function pageDrillTypeCap(type: string, quality: string): number {
  const rich = quality === "rich";
  const balanced = quality === "balanced";
  const caps: Record<string, number> = {
    pr_impact: rich ? 2 : 1,
    ingestion_chain: rich ? 2 : balanced ? 1 : 1,
    source_ref: rich ? 3 : balanced ? 2 : 1,
    collection_member: rich ? 2 : 1,
    moc_parent: rich ? 2 : 1,
    markdown_link: 0
  };
  return caps[type] ?? 1;
}

function pageDrillEdgeBudget(quality: string): number {
  if (quality === "rich") return 6;
  if (quality === "balanced") return 4;
  return 3;
}

function applyEdgeBudget<T extends SceneEdge & { sortKey: string }>(
  edges: T[],
  profile: ScenePerformanceProfile,
  rootOverview: boolean,
  familyOverview: boolean,
  quadrantDrillOverview: boolean,
  pageDrillOverview: boolean
): SceneEdge[] {
  if (!rootOverview && !familyOverview && !quadrantDrillOverview && !pageDrillOverview) return edges.slice(0, profile.maxEdges);
  const byType = new Map<string, number>();
  const picked: SceneEdge[] = [];
  let centerTouchCount = 0;
  const maxTotal = Math.min(
    profile.maxEdges,
    rootOverview
      ? rootOverviewEdgeBudget(profile.quality)
      : familyOverview
        ? familyOverviewEdgeBudget(profile.quality)
        : pageDrillOverview
          ? pageDrillEdgeBudget(profile.quality)
          : quadrantDrillEdgeBudget(profile.quality)
  );
  for (const edge of edges) {
    if (picked.length >= maxTotal) break;
    const touchesCenter = rootOverview && (edge.from.isRoot || edge.to.isRoot);
    if (touchesCenter) {
      if (centerTouchCount >= rootOverviewCenterTouchBudget(profile.quality)) continue;
    }
    const nextCount = (byType.get(edge.type) ?? 0) + 1;
    const cap = rootOverview
      ? rootOverviewTypeCap(edge.type, profile.quality)
      : familyOverview
        ? familyOverviewTypeCap(edge.type, profile.quality)
        : pageDrillOverview
          ? pageDrillTypeCap(edge.type, profile.quality)
          : quadrantDrillTypeCap(edge.type, profile.quality);
    if (nextCount > cap) continue;
    byType.set(edge.type, nextCount);
    if (touchesCenter) centerTouchCount += 1;
    picked.push(edge);
  }
  return picked;
}

export function edgeControlPoint(fromPos: [number, number, number], toPos: [number, number, number], type: string): [number, number, number] {
  const midX = (fromPos[0] + toPos[0]) / 2;
  const midY = (fromPos[1] + toPos[1]) / 2;
  const midZ = (fromPos[2] + toPos[2]) / 2;
  if (type === "markdown_link") {
    return [midX, Math.min(fromPos[1], toPos[1]) - 0.35, midZ];
  }
  const distance = Math.hypot(fromPos[0] - toPos[0], fromPos[1] - toPos[1], fromPos[2] - toPos[2]);
  return [midX, midY + 0.12 + distance * 0.05, midZ];
}

export function edgeControlPointForLayout(edge: { from: LayoutNode; to: LayoutNode; type: string }, layout: WorldLayout): [number, number, number] {
  const rootQuadrantOverview = layout.perspective === "quadrants" && layout.level === 0;
  if (!rootQuadrantOverview) return edgeControlPoint(edge.from.position, edge.to.position, edge.type);

  const [fromX, fromY, fromZ] = edge.from.position;
  const [toX, toY, toZ] = edge.to.position;
  const midX = (fromX + toX) / 2;
  const midY = (fromY + toY) / 2;
  const midZ = (fromZ + toZ) / 2;
  const distance = Math.hypot(fromX - toX, fromY - toY, fromZ - toZ);
  if (distance <= 0.7) return edgeControlPoint(edge.from.position, edge.to.position, edge.type);

  let dirX = midX;
  let dirZ = midZ;
  let dirLength = Math.hypot(dirX, dirZ);
  if (dirLength < 0.2) {
    const chordX = toX - fromX;
    const chordZ = toZ - fromZ;
    const side = fromX * toZ - fromZ * toX >= 0 ? 1 : -1;
    dirX = -chordZ * side;
    dirZ = chordX * side;
    dirLength = Math.hypot(dirX, dirZ);
  }
  if (dirLength < 0.01) return edgeControlPoint(edge.from.position, edge.to.position, edge.type);

  const minClearance = Math.max(layout.rInner * 1.35, layout.rOuter * 0.42);
  const maxClearance = Math.max(minClearance, layout.rOuter * 0.82);
  const clearance = Math.min(maxClearance, Math.max(minClearance, Math.hypot(midX, midZ) + 1.35));
  const lift = Math.min(1.85, 0.52 + distance * 0.13);
  return [
    Number(((dirX / dirLength) * clearance).toFixed(4)),
    Number((midY + lift).toFixed(4)),
    Number(((dirZ / dirLength) * clearance).toFixed(4))
  ];
}
