// Scene materials + edge selection: the shared visual vocabulary of the world.
// Trust/state material table, context-hue helpers, shape mapping, the WebGL /
// reduced-motion fallback gates, and the edge emphasis/selection pipeline.
// Pure functions and constants — no React, no three.js objects.

import { t } from "../../data/i18n";
import { agedColor, contextStyle, isMetaPage, pageTypeStyle, trustColor } from "../../data/presentation";
import type { GitState, GraphEdge } from "../../types";
import type { LayoutNode, ScenePerformanceProfile } from "../layout";
import type { WorldLayout } from "../perspectives";
import type { RelationIsolation } from "../../components/SystemScene";

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

export function shouldUseFallback(): boolean {
  return isVisualTestMode() || prefersReducedMotion() || !canUseWebGL();
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

// Hue = context (who the node is), tone = state (how it is): the aged context
// accent. Used by every 2D twin of the 3D body (minimap dots, fallback chips).
export function nodeDisplayColor(node: LayoutNode): string {
  if (node.isRoot) return trustColor("root");
  return agedColor(contextStyle(node.context).accent, nodeTrustKey(node));
}

// State ANNOTATION color (glow sprites, chips, guides): the trust palette
// survives as the state accent language even though it no longer paints
// node bodies.
export function trustDisplayColor(node: LayoutNode): string {
  if (node.isRoot) return trustColor("root");
  return trustColor(nodeTrustKey(node));
}

export type SuperShape = "sphere" | "crystal" | "hub" | "frame";

export function superShape(pageType: string): SuperShape {
  // META pages (molds: template_block/skill/perspective) render as BLUEPRINTS —
  // a wireframe partition of their own. The plant vs the building, literally.
  if (isMetaPage(pageType)) return "frame";
  const style = pageTypeStyle(pageType);
  if (style.shape === "crystal" || style.shape === "diamond") return "crystal";
  if (style.shape === "hub") return "hub";
  if (style.family === "source") return "crystal";
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
  moc_parent: 2,
  markdown_link: 1
};

const EDGE_REST_OPACITY: Record<string, number> = {
  pr_impact: 0.9,
  ingestion_chain: 0.8,
  source_ref: 0.42,
  moc_parent: 0.18,
  markdown_link: 0
};

export type SceneEdge = {
  from: LayoutNode;
  to: LayoutNode;
  type: string;
  emphasis: number;
};

function edgeEmphasis(
  edge: { from: LayoutNode; to: LayoutNode; type: string },
  focusIds: Set<string>,
  highlightedIds: Set<string>,
  quality: string,
  mocEmphasis: boolean
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
  if (mocEmphasis && edge.type === "moc_parent") rest = 0.55;
  const ambient = edge.type === "markdown_link" ? (quality === "rich" ? 0.08 : 0) : rest;
  return focusIds.size > 0 ? ambient * 0.25 : ambient;
}

function relationEdgeMatch(relation: RelationIsolation, edge: GraphEdge, selectedKeys: Set<string>): boolean {
  const fromSelected = selectedKeys.has(edge.source);
  const toSelected = selectedKeys.has(edge.target);
  if (!fromSelected && !toSelected) return false;
  if (relation === "hierarquia") return edge.type === "moc_parent";
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
      layout.perspective === "atlas"
    );
    if (emphasis <= 0.01) continue;
    mapped.push({ from, to, type: edge.type, emphasis, sortKey: `${edge.source}->${edge.target}:${edge.type}` });
  }
  return mapped
    .sort(
      (a, b) =>
        Number(b.emphasis >= 1) - Number(a.emphasis >= 1) ||
        (EDGE_PRIORITY[b.type] ?? 0) - (EDGE_PRIORITY[a.type] ?? 0) ||
        b.from.inbound_links + b.to.inbound_links - (a.from.inbound_links + a.to.inbound_links) ||
        a.sortKey.localeCompare(b.sortKey)
    )
    .slice(0, profile.maxEdges);
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
