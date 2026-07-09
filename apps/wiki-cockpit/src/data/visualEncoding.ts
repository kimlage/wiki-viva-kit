import type { OverlayMetric, OverlayMetrics } from "../types";
import type { OverlayId } from "../world/contracts";
import { t } from "./i18n";

export const SEMANTIC_VISUAL_TOKENS_VERSION = "wiki_semantic_visual_tokens.v1" as const;
export const STRONG_ATTENTION_MARK_BUDGET = 12;

export type OverlayRing = "none" | "solid" | "double" | "dashed";

export type SemanticVisualToken = {
  color: string;
  label: string;
  symbol: string;
  ring: OverlayRing;
  opacity: number;
  emissive: number;
  pulse: boolean;
};

type OverlayTokenScale = {
  label: string;
  metric: keyof OverlayMetrics;
  fallbackState: string;
  states: Record<string, SemanticVisualToken>;
};

const token = (
  color: string,
  label: string,
  symbol: string,
  ring: OverlayRing,
  opacity = 1,
  emissive = 0.08,
  pulse = false
): SemanticVisualToken => ({ color, label, symbol, ring, opacity, emissive, pulse });

// One versioned token table for WebGL materials, DOM labels, live legend and
// reduced-motion fallback. Context/area is intentionally absent: active
// overlay state owns color; page type owns shape and context stays in position
// and text labels.
export const SEMANTIC_VISUAL_TOKENS: Readonly<Record<OverlayId, OverlayTokenScale>> = Object.freeze({
  attention: {
    label: "Attention",
    metric: "attention",
    fallbackState: "unknown",
    states: {
      quiet: token("#71808f", "No attention signal", "·", "none", 0.72, 0.02),
      watch: token("#f2b84b", "Needs attention", "!", "solid", 1, 0.42),
      urgent: token("#ff6b62", "Urgent", "!!", "double", 1, 0.82, true),
      unknown: token("#9186a6", "Attention unknown", "?", "dashed", 0.68, 0.04)
    }
  },
  freshness: {
    label: "Freshness",
    metric: "freshness",
    fallbackState: "unknown",
    states: {
      fresh: token("#56c99c", "Fresh", "●", "solid", 0.94, 0.08),
      stale: token("#ff8b62", "Stale", "◷", "double", 1, 0.5),
      never_synced: token("#b58b7d", "Never synced", "∅", "dashed", 0.9, 0.18),
      unknown: token("#8a96a7", "Not checked", "?", "dashed", 0.64, 0.02)
    }
  },
  actions: {
    label: "Actions",
    metric: "actions",
    fallbackState: "unknown",
    states: {
      none: token("#71808f", "No linked action", "·", "none", 0.72, 0.02),
      open: token("#58b7f5", "Open action", "→", "solid", 1, 0.3),
      blocked: token("#ff6672", "Blocked action", "×", "double", 1, 0.78),
      overdue: token("#f4a742", "Overdue action", "⌛", "double", 1, 0.66),
      done: token("#65c889", "Completed action", "✓", "solid", 0.82, 0.08),
      cancelled: token("#8c8792", "Cancelled action", "—", "dashed", 0.68, 0.02),
      unknown: token("#8a96a7", "Action state unknown", "?", "dashed", 0.64, 0.02)
    }
  },
  ownership: {
    label: "Ownership",
    metric: "ownership",
    fallbackState: "unknown",
    states: {
      assigned: token("#b992f4", "Assigned", "@", "solid", 0.94, 0.18),
      shared: token("#e789ca", "Shared ownership", "@@", "double", 1, 0.3),
      unassigned: token("#efb354", "Unassigned", "∅", "dashed", 1, 0.42),
      unknown: token("#82909d", "Ownership not recorded", "?", "dashed", 0.64, 0.02)
    }
  },
  evidence: {
    label: "Evidence",
    metric: "evidence",
    fallbackState: "unknown",
    states: {
      linked: token("#55c9c3", "Evidence linked", "↗", "solid", 0.96, 0.2),
      unrecorded: token("#f07b8f", "No evidence recorded", "∅", "dashed", 1, 0.46),
      unknown: token("#82909d", "Evidence state unknown", "?", "dashed", 0.64, 0.02)
    }
  },
  quality: {
    label: "Quality",
    metric: "quality",
    fallbackState: "unknown",
    states: {
      clear: token("#70c696", "No deterministic flags", "✓", "solid", 0.88, 0.08),
      warning: token("#efb84f", "Quality warning", "△", "solid", 1, 0.4),
      flagged: token("#f06f91", "Quality issue", "×", "double", 1, 0.7),
      unknown: token("#82909d", "Quality not measured", "?", "dashed", 0.64, 0.02)
    }
  }
});

export type VisualMetricNode = {
  id?: string;
  path?: string;
  page_type: string;
  freshness_state: string;
  approved_state: string;
  risk_flags: string[];
  source_ref_count?: number;
  metrics?: { source_ref_count?: number };
  overlay_metrics?: Partial<OverlayMetrics>;
};

export type ResolvedVisualEncoding = SemanticVisualToken & {
  version: typeof SEMANTIC_VISUAL_TOKENS_VERSION;
  overlay: OverlayId;
  overlayLabel: string;
  overlayLabelKey: string;
  labelKey: string;
  state: string;
  count: number;
  value: number | null;
  valueText: string;
  accessibleText: string;
  reasons: string[];
  refs: string[];
  dataBacked: boolean;
};

export type OverlayLegendEntry = ResolvedVisualEncoding & { visibleCount: number };

const sourceRefCount = (node: VisualMetricNode): number =>
  Math.max(0, Number(node.source_ref_count ?? node.metrics?.source_ref_count ?? 0));

function compatibilityMetric(node: VisualMetricNode, overlay: OverlayId): OverlayMetric {
  const riskCount = node.risk_flags?.length ?? 0;
  const sourceCount = sourceRefCount(node);
  const basis = ["compat_derived"];
  if (overlay === "attention") {
    const urgent = riskCount > 0;
    const watch = node.freshness_state === "stale" || node.approved_state === "proposal";
    return {
      state: urgent ? "urgent" : watch ? "watch" : "quiet",
      value: urgent ? 1 : watch ? 0.5 : 0,
      count: riskCount + Number(watch),
      reasons: [...basis, ...node.risk_flags, ...(node.freshness_state === "stale" ? ["freshness:stale"] : [])],
      refs: []
    };
  }
  if (overlay === "freshness") {
    const state = ["fresh", "stale"].includes(node.freshness_state) ? node.freshness_state : "unknown";
    return { state, value: state === "fresh" ? 1 : state === "stale" ? 0 : null, count: 1, reasons: basis, refs: [] };
  }
  if (overlay === "evidence") {
    return { state: sourceCount > 0 ? "linked" : "unrecorded", value: sourceCount > 0 ? 1 : 0, count: sourceCount, reasons: basis, refs: [] };
  }
  if (overlay === "quality") {
    return { state: riskCount > 1 ? "flagged" : riskCount === 1 ? "warning" : "clear", value: riskCount, count: riskCount, reasons: [...basis, ...node.risk_flags], refs: [] };
  }
  if (overlay === "ownership") {
    return { state: "unknown", value: null, count: 0, reasons: basis, refs: [] };
  }
  return { state: node.page_type === "action" ? "open" : "none", value: node.page_type === "action" ? 1 : 0, count: node.page_type === "action" ? 1 : 0, reasons: basis, refs: [] };
}

const STATE_PRIORITY: Record<OverlayId, Record<string, number>> = {
  attention: { urgent: 4, watch: 3, unknown: 2, quiet: 1 },
  freshness: { never_synced: 5, stale: 4, unknown: 3, fresh: 1 },
  actions: { blocked: 7, overdue: 6, open: 5, unknown: 4, cancelled: 3, done: 2, none: 1 },
  ownership: { unassigned: 5, shared: 4, assigned: 3, unknown: 2 },
  evidence: { unrecorded: 4, unknown: 3, linked: 1 },
  quality: { flagged: 5, warning: 4, unknown: 3, clear: 1 }
};

const unique = (values: string[]): string[] => [...new Set(values.filter(Boolean))].sort();

export function overlayMetricForNode(node: VisualMetricNode, overlay: OverlayId): OverlayMetric {
  const metric = node.overlay_metrics?.[overlay];
  if (!metric || typeof metric.state !== "string") return compatibilityMetric(node, overlay);
  return {
    state: metric.state,
    value: typeof metric.value === "number" && Number.isFinite(metric.value) ? metric.value : null,
    count: Math.max(0, Number(metric.count ?? 0)),
    reasons: unique(Array.isArray(metric.reasons) ? metric.reasons.map(String) : []),
    refs: unique(Array.isArray(metric.refs) ? metric.refs.map(String) : [])
  };
}

export function aggregateOverlayMetrics(nodes: VisualMetricNode[]): OverlayMetrics {
  return (Object.keys(SEMANTIC_VISUAL_TOKENS) as OverlayId[]).reduce((output, overlay) => {
    const records = nodes.map((node) => overlayMetricForNode(node, overlay));
    const highest = [...records].sort(
      (a, b) => (STATE_PRIORITY[overlay][b.state] ?? 0) - (STATE_PRIORITY[overlay][a.state] ?? 0) || a.state.localeCompare(b.state)
    )[0];
    const numeric = records.map((record) => record.value).filter((value): value is number => typeof value === "number");
    output[overlay] = {
      state: highest?.state ?? SEMANTIC_VISUAL_TOKENS[overlay].fallbackState,
      value: numeric.length > 0 ? Math.max(...numeric) : null,
      count: records.reduce((sum, record) => sum + record.count, 0),
      reasons: unique(records.flatMap((record) => record.reasons)),
      refs: unique(records.flatMap((record) => record.refs))
    };
    return output;
  }, {} as OverlayMetrics);
}

function valueText(tokenValue: SemanticVisualToken, metric: OverlayMetric): string {
  if (metric.count > 0) return `${tokenValue.label} · ${metric.count}`;
  return tokenValue.label;
}

export class VisualEncodingResolver {
  readonly version = SEMANTIC_VISUAL_TOKENS_VERSION;

  resolve(node: VisualMetricNode, overlay: OverlayId): ResolvedVisualEncoding {
    const scale = SEMANTIC_VISUAL_TOKENS[overlay];
    const metric = overlayMetricForNode(node, overlay);
    const state = scale.states[metric.state] ? metric.state : scale.fallbackState;
    const tokenValue = scale.states[state];
    const text = valueText(tokenValue, metric);
    const reasons = metric.reasons.filter((reason) => reason !== "compat_derived");
    const reasonText = reasons.length > 0 ? `; ${reasons.slice(0, 3).join(", ")}` : "";
    return {
      ...tokenValue,
      version: this.version,
      overlay,
      overlayLabel: scale.label,
      overlayLabelKey: `world.overlay.${overlay}`,
      labelKey: `overlay.state.${overlay}.${state}`,
      state,
      count: metric.count,
      value: metric.value,
      valueText: text,
      accessibleText: `${scale.label}: ${text}${reasonText}`,
      reasons,
      refs: metric.refs,
      dataBacked: !metric.reasons.includes("compat_derived")
    };
  }

  legend(overlay: OverlayId, nodes: VisualMetricNode[]): OverlayLegendEntry[] {
    const scale = SEMANTIC_VISUAL_TOKENS[overlay];
    const counts = new Map<string, number>();
    nodes.forEach((node) => {
      const resolved = this.resolve(node, overlay);
      counts.set(resolved.state, (counts.get(resolved.state) ?? 0) + 1);
    });
    return Object.keys(scale.states).map((state) => ({
      ...this.resolve(
        {
          page_type: "legend",
          freshness_state: "unknown",
          approved_state: "approved",
          risk_flags: [],
          overlay_metrics: {
            [overlay]: { state, value: null, count: 0, reasons: ["legend"], refs: [] }
          }
        },
        overlay
      ),
      visibleCount: counts.get(state) ?? 0
    }));
  }
}

export const visualEncodingResolver = new VisualEncodingResolver();

export function strongAttentionNodeIds(
  nodes: VisualMetricNode[],
  budget = STRONG_ATTENTION_MARK_BUDGET
): Set<string> {
  const stateRank: Record<string, number> = { urgent: 2, watch: 1 };
  return new Set(
    nodes
      .map((node) => ({
        id: String(node.id || node.path || ""),
        encoding: visualEncodingResolver.resolve(node, "attention")
      }))
      .filter((entry) => entry.id && (stateRank[entry.encoding.state] ?? 0) > 0)
      .sort(
        (a, b) =>
          (stateRank[b.encoding.state] ?? 0) - (stateRank[a.encoding.state] ?? 0) ||
          b.encoding.count - a.encoding.count ||
          (b.encoding.value ?? -1) - (a.encoding.value ?? -1) ||
          a.id.localeCompare(b.id)
      )
      .slice(0, Math.max(0, Math.floor(budget)))
      .map((entry) => entry.id)
  );
}

export function localizedEncodingText(encoding: ResolvedVisualEncoding): string {
  const label = t(encoding.labelKey);
  return encoding.count > 0 ? t("overlay.encoding.count", { label, n: encoding.count }) : label;
}

export function localizedEncodingAria(encoding: ResolvedVisualEncoding): string {
  return t("overlay.encoding.aria", {
    overlay: t(encoding.overlayLabelKey),
    state: localizedEncodingText(encoding)
  });
}
