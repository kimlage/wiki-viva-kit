import type { FreshnessState, GraphNode } from "../types";

export type SceneQuality = "compact" | "balanced" | "rich";

export type ScenePerformanceProfile = {
  quality: SceneQuality;
  maxNodes: number;
  dpr: [number, number];
  geometrySegments: number;
  enableIntro: boolean;
  label: string;
};

export type LayoutNode = {
  id: string;
  path: string;
  title: string;
  context: string;
  page_type: string;
  freshness_state: FreshnessState;
  approved_state: string;
  risk_flags: string[];
  source_ref_count: number;
  outbound_links: number;
  position: [number, number, number];
  scale: number;
  color: string;
};

export type GalaxyLayout = {
  nodes: LayoutNode[];
  contextAnchors: { context: string; position: [number, number, number]; count: number }[];
  truncated: number;
};

const COLORS: Record<FreshnessState | "proposal" | "root", string> = {
  fresh: "#5ee6a8",
  stale: "#ffb454",
  unknown: "#9aa3b2",
  proposal: "#c57cff",
  root: "#6bd7ff"
};

export function scenePerformanceProfile(
  nodeCount: number,
  options: { width?: number; pixelRatio?: number; hardwareConcurrency?: number; reducedMotion?: boolean } = {}
): ScenePerformanceProfile {
  const width = options.width ?? 1200;
  const cores = options.hardwareConcurrency ?? 4;
  const pixelRatio = options.pixelRatio ?? 1;
  const reduced = Boolean(options.reducedMotion);
  if (reduced || width < 640 || cores <= 4 || nodeCount > 140) {
    return {
      quality: "compact",
      maxNodes: 36,
      dpr: [1, Math.min(1.15, pixelRatio)],
      geometrySegments: 12,
      enableIntro: false,
      label: "compact"
    };
  }
  if (width < 1100 || cores <= 6 || nodeCount > 84) {
    return {
      quality: "balanced",
      maxNodes: 64,
      dpr: [1, Math.min(1.35, pixelRatio)],
      geometrySegments: 18,
      enableIntro: true,
      label: "balanced"
    };
  }
  return {
    quality: "rich",
    maxNodes: 96,
    dpr: [1, Math.min(1.6, pixelRatio)],
    geometrySegments: 24,
    enableIntro: true,
    label: "rich"
  };
}

function nodeWeight(node: GraphNode): number {
  const root = node.page_type === "root_index" ? 1000 : 0;
  const stale = node.freshness_state === "stale" ? 80 : 0;
  const source = node.metrics.source_ref_count * 12;
  const links = node.metrics.inbound_links + node.metrics.outbound_links;
  return root + stale + source + links;
}

function nodeColor(node: GraphNode): string {
  if (node.approved_state === "proposal") return COLORS.proposal;
  if (node.page_type === "root_index") return COLORS.root;
  return COLORS[node.freshness_state] ?? COLORS.unknown;
}

export function computeGalaxyLayout(nodes: GraphNode[], maxNodes: number): GalaxyLayout {
  const visible = [...nodes]
    .sort((a, b) => nodeWeight(b) - nodeWeight(a) || a.context.localeCompare(b.context) || a.title.localeCompare(b.title))
    .slice(0, maxNodes);
  const contexts = [...new Set(visible.map((node) => node.context || "system"))].sort();
  const byContext = new Map(contexts.map((context) => [context, visible.filter((node) => (node.context || "system") === context)]));
  const contextAnchors = contexts.map((context, index) => {
    const angle = (index / Math.max(contexts.length, 1)) * Math.PI * 2 - Math.PI / 2;
    const radius = contexts.length === 1 ? 1.7 : 2.15 + Math.min(contexts.length, 7) * 0.08;
    return {
      context,
      count: byContext.get(context)?.length ?? 0,
      position: [Math.cos(angle) * radius, 0, Math.sin(angle) * radius] as [number, number, number]
    };
  });
  const anchorByContext = new Map(contextAnchors.map((anchor) => [anchor.context, anchor]));
  const layoutNodes: LayoutNode[] = [];
  for (const [context, group] of byContext.entries()) {
    const anchor = anchorByContext.get(context);
    if (!anchor) continue;
    group.forEach((node, index) => {
      const localAngle = (index / Math.max(group.length, 1)) * Math.PI * 2 + group.length * 0.17;
      const localRing = 0.38 + Math.sqrt(index + 1) * 0.21;
      const drift = node.freshness_state === "stale" ? 0.38 : 0;
      const root = node.page_type === "root_index";
      const x = root ? 0 : anchor.position[0] + Math.cos(localAngle) * (localRing + drift);
      const z = root ? 0 : anchor.position[2] + Math.sin(localAngle) * (localRing + drift);
      const y = root ? 0 : ((index % 5) - 2) * 0.13 + (node.approved_state === "proposal" ? 0.34 : 0);
      layoutNodes.push({
        id: node.id,
        path: node.path,
        title: node.title,
        context: node.context,
        page_type: node.page_type,
        freshness_state: node.freshness_state,
        approved_state: node.approved_state,
        risk_flags: node.risk_flags,
        source_ref_count: node.metrics.source_ref_count,
        outbound_links: node.metrics.outbound_links,
        position: [Number(x.toFixed(4)), Number(y.toFixed(4)), Number(z.toFixed(4))],
        scale: Number((root ? 0.42 : 0.16 + Math.min(node.metrics.outbound_links, 6) * 0.025).toFixed(4)),
        color: nodeColor(node)
      });
    });
  }
  return {
    nodes: layoutNodes,
    contextAnchors,
    truncated: Math.max(0, nodes.length - visible.length)
  };
}
