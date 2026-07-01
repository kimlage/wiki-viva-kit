import type { FreshnessState, GraphNode } from "../types";
import { pageTypeStyle } from "../data/presentation";

export type SceneQuality = "compact" | "balanced" | "rich";

export type ScenePerformanceProfile = {
  quality: SceneQuality;
  maxNodes: number;
  maxEdges: number;
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
  inbound_links: number;
  outbound_links: number;
  ageDays: number;
  overdueRatio: number;
  isHub: boolean;
  isRoot: boolean;
  position: [number, number, number];
  scale: number;
};

export type LayoutWedge = {
  context: string;
  startAngle: number;
  endAngle: number;
  centerAngle: number;
  count: number;
  freshCount: number;
  staleCount: number;
  unknownCount: number;
  proposalCount: number;
  riskCount: number;
  rimPosition: [number, number, number];
};

export type GalaxyLayout = {
  nodes: LayoutNode[];
  wedges: LayoutWedge[];
  rInner: number;
  rOuter: number;
  deadlineF: number;
  truncated: number;
};

// Radar constants: radius encodes time-to-stale, the deadline arc sits at
// DEADLINE_F of the band — content beyond it is past its freshness window.
const R_INNER = 2.1;
const WEDGE_GAP = 0.06;
const MIN_WEDGE = 0.35;
const SLOT_DEPTH = 0.34;
const ANGLE_PAD = 0.04;
export const DEADLINE_F = 0.7;

// The tier reflects DEVICE capability only. Repo size never downgrades the
// visual tier (a big wiki on a strong machine keeps particles and curves);
// it is absorbed by the per-tier maxNodes/maxEdges caps instead.
export function scenePerformanceProfile(
  nodeCount: number,
  options: { width?: number; pixelRatio?: number; hardwareConcurrency?: number; reducedMotion?: boolean } = {}
): ScenePerformanceProfile {
  const width = options.width ?? 1200;
  const cores = options.hardwareConcurrency ?? 4;
  const pixelRatio = options.pixelRatio ?? 1;
  const reduced = Boolean(options.reducedMotion);
  const dense = nodeCount > 110;
  if (reduced || width < 640 || cores <= 4) {
    return {
      quality: "compact",
      maxNodes: 64,
      maxEdges: 80,
      dpr: [1, Math.min(1.15, pixelRatio)],
      geometrySegments: 12,
      enableIntro: false,
      label: "compact"
    };
  }
  if (width < 1100 || cores <= 6) {
    return {
      quality: "balanced",
      maxNodes: 110,
      maxEdges: 200,
      dpr: [1, Math.min(1.35, pixelRatio)],
      geometrySegments: dense ? 14 : 18,
      enableIntro: true,
      label: "balanced"
    };
  }
  return {
    quality: "rich",
    maxNodes: 160,
    maxEdges: 320,
    dpr: [1, Math.min(1.6, pixelRatio)],
    geometrySegments: dense ? 18 : 24,
    enableIntro: true,
    label: dense ? "rich·dense" : "rich"
  };
}

function nodeWeight(node: GraphNode): number {
  const root = node.page_type === "root_index" ? 10000 : 0;
  const hub = node.page_type === "context_hub" ? 5000 : 0;
  const attention = node.risk_flags.length > 0 || node.freshness_state === "stale" || node.approved_state === "proposal" ? 1000 : 0;
  const source = node.metrics.source_ref_count * 12;
  const links = node.metrics.inbound_links * 2 + node.metrics.outbound_links;
  return root + hub + attention + source + links;
}

function parseDateMs(value: string): number | null {
  if (!value) return null;
  const parsed = Date.parse(value.length === 10 ? `${value}T00:00:00Z` : value);
  return Number.isNaN(parsed) ? null : parsed;
}

function staleBudgetDays(node: GraphNode & { stale_after_days?: string }): number {
  const raw = Number.parseFloat(String((node as { stale_after_days?: string }).stale_after_days ?? ""));
  return Number.isFinite(raw) && raw > 0 ? raw : 90;
}

// Freshness fraction: 0 = just verified, DEADLINE_F = at the freshness window,
// 1 = long past it. Radius is a direct read of "how overdue is this page".
function freshnessFraction(node: GraphNode, ageDays: number | null): number {
  const budget = staleBudgetDays(node);
  if (node.freshness_state === "stale") {
    if (ageDays === null) return DEADLINE_F + 0.12;
    const overshoot = Math.min(Math.max((ageDays - budget) / budget, 0), 1);
    return DEADLINE_F + 0.05 + overshoot * (1 - DEADLINE_F - 0.05);
  }
  if (node.freshness_state === "fresh") {
    if (ageDays === null) return 0.24;
    return 0.1 + Math.min(Math.max(ageDays / budget, 0), 1) * (DEADLINE_F - 0.25);
  }
  return DEADLINE_F - 0.08;
}

// The radar core: an explicit root page when typed, else the top-level index.
function rootNodeId(nodes: GraphNode[]): string | null {
  const byType = (type: string) =>
    nodes
      .filter((node) => node.page_type === type)
      .sort((a, b) => a.path.length - b.path.length || a.id.localeCompare(b.id))[0];
  const typed = byType("root_index") ?? byType("root_entity");
  if (typed) return typed.id;
  const indexPage = nodes
    .filter((node) => /^[^/]+\/index\.md$/.test(node.path))
    .sort((a, b) => b.metrics.inbound_links - a.metrics.inbound_links || a.id.localeCompare(b.id))[0];
  return indexPage ? indexPage.id : null;
}

export function computeGalaxyLayout(nodes: GraphNode[], maxNodes: number, snapshotAt?: string): GalaxyLayout {
  // Deterministic clock: prefer the snapshot timestamp, fall back to the
  // newest updated_at in the data. Never the wall clock.
  const snapshotMs =
    (snapshotAt ? parseDateMs(snapshotAt) : null) ??
    Math.max(0, ...nodes.map((node) => parseDateMs(node.updated_at ?? "") ?? 0));

  const rootId = rootNodeId(nodes);
  const visible = [...nodes]
    .sort(
      (a, b) =>
        Number(b.id === rootId) - Number(a.id === rootId) ||
        nodeWeight(b) - nodeWeight(a) ||
        a.context.localeCompare(b.context) ||
        a.title.localeCompare(b.title) ||
        a.id.localeCompare(b.id)
    )
    .slice(0, maxNodes);

  const contexts = [...new Set(visible.filter((node) => node.id !== rootId).map((node) => node.context || "system"))].sort();
  const byContext = new Map(
    contexts.map((context) => [context, visible.filter((node) => node.id !== rootId && (node.context || "system") === context)])
  );

  const rOuter = Math.min(4.2 + Math.sqrt(Math.max(visible.length - 24, 0)) * 0.12, 6.5);
  const band = rOuter - R_INNER;

  // Wedge allocation: sqrt-weighted width with a floor so tiny contexts stay
  // clickable. The largest wedge is placed first, centered toward the open
  // right side of the canvas (the hero card docks on the left).
  const placement = [...contexts].sort(
    (a, b) => (byContext.get(b)?.length ?? 0) - (byContext.get(a)?.length ?? 0) || a.localeCompare(b)
  );
  const weights = placement.map((context) => Math.sqrt(Math.max(byContext.get(context)?.length ?? 0, 1)));
  const totalGap = WEDGE_GAP * placement.length;
  const available = Math.PI * 2 - totalGap;
  const weightSum = weights.reduce((total, weight) => total + weight, 0) || 1;
  let spans = weights.map((weight) => (available * weight) / weightSum);
  if (placement.length > 1) {
    const clamped = spans.map((span) => Math.max(span, MIN_WEDGE));
    const clampedSum = clamped.reduce((total, span) => total + span, 0);
    spans = clamped.map((span) => (span / clampedSum) * available);
  }

  const wedges: LayoutWedge[] = [];
  let cursor = 0.35 + (spans[0] ?? 0) / 2;
  placement.forEach((context, index) => {
    const span = spans[index];
    const startAngle = cursor - span;
    const endAngle = cursor;
    const centerAngle = cursor - span / 2;
    const group = byContext.get(context) ?? [];
    wedges.push({
      context,
      startAngle,
      endAngle,
      centerAngle,
      count: group.length,
      freshCount: group.filter((node) => node.freshness_state === "fresh").length,
      staleCount: group.filter((node) => node.freshness_state === "stale").length,
      unknownCount: group.filter((node) => node.freshness_state === "unknown").length,
      proposalCount: group.filter((node) => node.approved_state === "proposal").length,
      riskCount: group.filter((node) => node.risk_flags.length > 0).length,
      rimPosition: [Math.cos(centerAngle) * (rOuter + 0.45), 0.05, Math.sin(centerAngle) * (rOuter + 0.45)]
    });
    cursor = startAngle - WEDGE_GAP;
  });
  wedges.sort((a, b) => a.context.localeCompare(b.context));
  const wedgeByContext = new Map(wedges.map((wedge) => [wedge.context, wedge]));

  const layoutNodes: LayoutNode[] = [];

  const pushNode = (node: GraphNode, position: [number, number, number], scale: number, extras: { ageDays: number; overdueRatio: number; isHub: boolean }) => {
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
      inbound_links: node.metrics.inbound_links,
      outbound_links: node.metrics.outbound_links,
      ageDays: Number(extras.ageDays.toFixed(2)),
      overdueRatio: Number(extras.overdueRatio.toFixed(4)),
      isHub: extras.isHub,
      isRoot: node.id === rootId,
      position: [Number(position[0].toFixed(4)), Number(position[1].toFixed(4)), Number(position[2].toFixed(4))],
      scale: Number(scale.toFixed(4))
    });
  };

  const nodeMetrics = (node: GraphNode) => {
    const updatedMs = parseDateMs(node.updated_at ?? "");
    const ageDays = updatedMs === null ? -1 : Math.max(0, (snapshotMs - updatedMs) / 86400000);
    const overdueRatio = ageDays < 0 ? 0 : ageDays / staleBudgetDays(node);
    return { ageDays: ageDays < 0 ? 0 : ageDays, overdueRatio, hasDate: updatedMs !== null };
  };

  for (const node of visible) {
    if (node.id === rootId) {
      const metrics = nodeMetrics(node);
      pushNode(node, [0, 0, 0], 0.5, { ageDays: metrics.ageDays, overdueRatio: metrics.overdueRatio, isHub: true });
    }
  }

  for (const context of contexts) {
    const wedge = wedgeByContext.get(context);
    if (!wedge) continue;
    const group = byContext.get(context) ?? [];
    // One pinned hub per context at the wedge mouth; everything else is
    // positioned by (angle within wedge, radius = freshness fraction).
    const hub = group
      .filter((node) => node.page_type === "context_hub")
      .sort((a, b) => a.title.localeCompare(b.title) || a.id.localeCompare(b.id))[0];
    const rest = group.filter((node) => node !== hub);

    if (hub) {
      const metrics = nodeMetrics(hub);
      pushNode(
        hub,
        [Math.cos(wedge.centerAngle) * (R_INNER - 0.25), 0, Math.sin(wedge.centerAngle) * (R_INNER - 0.25)],
        0.26,
        { ageDays: metrics.ageDays, overdueRatio: metrics.overdueRatio, isHub: true }
      );
    }

    // Deterministic slot binning: radius from freshness, angle spread within
    // the (wedge, slot) bin sorted by family/title so output is stable.
    const bins = new Map<number, { node: GraphNode; r: number; metrics: ReturnType<typeof nodeMetrics> }[]>();
    for (const node of rest) {
      const metrics = nodeMetrics(node);
      const f = freshnessFraction(node, metrics.hasDate ? metrics.ageDays : null);
      const r = R_INNER + f * band;
      const slot = Math.floor((r - R_INNER) / SLOT_DEPTH);
      const bin = bins.get(slot) ?? [];
      bin.push({ node, r, metrics });
      bins.set(slot, bin);
    }
    for (const [slot, bin] of [...bins.entries()].sort(([a], [b]) => a - b)) {
      bin.sort(
        (a, b) =>
          pageTypeStyle(a.node.page_type).family.localeCompare(pageTypeStyle(b.node.page_type).family) ||
          a.node.title.localeCompare(b.node.title) ||
          a.node.id.localeCompare(b.node.id)
      );
      const span = wedge.endAngle - wedge.startAngle;
      const usable = Math.max(span - ANGLE_PAD * 2, 0.05);
      bin.forEach((entry, index) => {
        const stagger = slot % 2 === 1 ? 0.5 : 0;
        const t = (index + 0.5 + stagger) / (bin.length + (stagger ? 0.5 : 0));
        const angle = wedge.startAngle + ANGLE_PAD + t * usable;
        const y = entry.node.approved_state === "proposal" ? 0.5 : 0;
        const scale = Math.min(0.11 + 0.05 * Math.sqrt(Math.min(entry.node.metrics.inbound_links, 16)), 0.31);
        pushNode(entry.node, [Math.cos(angle) * entry.r, y, Math.sin(angle) * entry.r], scale, {
          ageDays: entry.metrics.ageDays,
          overdueRatio: entry.metrics.overdueRatio,
          isHub: false
        });
      });
    }
  }

  return {
    nodes: layoutNodes,
    wedges,
    rInner: R_INNER,
    rOuter,
    deadlineF: DEADLINE_F,
    truncated: Math.max(0, nodes.length - visible.length)
  };
}
