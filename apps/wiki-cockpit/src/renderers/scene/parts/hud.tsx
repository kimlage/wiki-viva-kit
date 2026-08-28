// DOM HUD twins of the scene encodings: the honest census over visible nodes,
// the collapsible StatusStrip filter chips + Key popover, and the hover
// tooltip (page facts + the anchor "city tooltip" architecture line).

import { useState } from "react";
import { t } from "../../../data/i18n";
import { contextStyle, edgeStyle, isRawData, landmarkGlyph, pageTypeLabel, pageTypeStyle, trustColor, worldGroupLabel } from "../../../data/presentation";
import { localizedEncodingText, SEMANTIC_VISUAL_TOKENS_VERSION, visualEncodingResolver } from "../../../data/visualEncoding";
import type { OverlayLegendEntry } from "../../../data/visualEncoding";
import type { GraphEdge, GraphNode } from "../../../types";
import type { LayoutNode } from "../../../scene/layout";
import type { WorldGroup, WorldLayout } from "../../../scene/perspectives";
import { freshnessLabel, nodeTrustKey } from "./materials";
import type { TrustKey } from "./materials";
import { isEvidenceGap } from "./particles-layer";
import type { OverlayId } from "../../../world/contracts";

export type SceneCensus = {
  trust: { key: TrustKey; label: string; color: string; count: number }[];
  riskCount: number;
  evidenceCount: number;
  unsourcedCount: number;
  rawCount: number;
  contexts: { key: string; label: string; color: string; count: number }[];
  overlay: OverlayId;
  overlaySignals: OverlayLegendEntry[];
  edgeCounts: { key: string; label: string; color: string; count: number }[];
  hidden: number;
  total: number;
};

export function sceneCensus(nodes: GraphNode[], edges: GraphEdge[], layout: WorldLayout, overlay: OverlayId = "freshness"): SceneCensus {
  const visibleIds = new Set(layout.nodes.map((node) => node.id));
  const visible = nodes.filter((node) => visibleIds.has(node.id));
  const counts = new Map<TrustKey, number>();
  visible.forEach((node) => {
    const key = nodeTrustKey({ approved_state: node.approved_state, freshness_state: node.freshness_state });
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  const trust = (
    [
      { key: "fresh" as const, label: t("scene.trust.fresh") },
      { key: "stale" as const, label: t("scene.trust.stale") },
      { key: "proposal" as const, label: t("scene.trust.proposal") },
      { key: "unknown" as const, label: t("scene.trust.unknown") }
    ]
  )
    .map((entry) => ({ ...entry, color: trustColor(entry.key), count: counts.get(entry.key) || 0 }))
    .filter((entry) => entry.count > 0);
  const edgeCounts = new Map<string, number>();
  edges.forEach((edge) => {
    if (visibleIds.has(edge.source) && visibleIds.has(edge.target)) {
      edgeCounts.set(edge.type, (edgeCounts.get(edge.type) || 0) + 1);
    }
  });
  return {
    trust,
    riskCount: visible.filter((node) => node.risk_flags.length > 0).length,
    evidenceCount: visible.filter((node) => node.metrics.source_ref_count > 0).length,
    unsourcedCount: visible.filter((node) => isEvidenceGap(node.page_type, node.metrics.source_ref_count)).length,
    rawCount: visible.filter((node) => isRawData(node.page_type)).length,
    overlay,
    overlaySignals: visualEncodingResolver.legend(overlay, visible),
    // Context is retained as a labelled positional census, not body hue.
    contexts: [...visible.reduce((map, node) => {
      const key = node.context || "system";
      map.set(key, (map.get(key) || 0) + 1);
      return map;
    }, new Map<string, number>()).entries()]
      .map(([key, count]) => ({ key, label: contextStyle(key).label, color: contextStyle(key).accent, count }))
      .sort((a, b) => b.count - a.count),
    edgeCounts: [...edgeCounts.entries()]
      .map(([key, count]) => ({ key, label: edgeStyle(key).label, color: edgeStyle(key).color, count }))
      .sort((a, b) => b.count - a.count),
    hidden: layout.totals.hidden,
    total: layout.totals.total
  };
}

export type SceneFilter = TrustKey | "raw" | "unsourced";

export function StatusStrip({
  census,
  filter,
  onFilter
}: {
  census: SceneCensus;
  filter: SceneFilter | null;
  onFilter: (key: SceneFilter | null) => void;
}) {
  const [keyOpen, setKeyOpen] = useState(false);
  // The strip COLLAPSES to one quiet chip unless a filter is active or the
  // owner opens it — census chips are useful, but not worth a permanent row
  // competing with the command bar.
  const [expanded, setExpanded] = useState(false);
  const open = expanded || Boolean(filter);
  if (!open) {
    return (
      <div className="radarStatusStrip collapsed" aria-label="Map status">
        <button className="stripChip stripToggle" onClick={() => setExpanded(true)} type="button">
          {t("misc.filter")} ▸
        </button>
      </div>
    );
  }
  return (
    <div className="radarStatusStrip" aria-label="Map status">
      <button className="stripChip stripToggle" onClick={() => { setExpanded(false); if (filter) onFilter(null); }} type="button">
        {t("misc.filter")} ▾
      </button>
      {census.trust.map((entry) => (
        <button
          className={filter === entry.key ? "stripChip active" : "stripChip"}
          key={entry.key}
          onClick={() => onFilter(filter === entry.key ? null : entry.key)}
          title={`Show only ${entry.label}`}
          type="button"
        >
          <i style={{ background: entry.color }} />
          {entry.label} {entry.count}
        </button>
      ))}
      {census.riskCount > 0 && (
        <span className="stripChip static">
          <i style={{ background: trustColor("risk") }} />
          {t("scene.risk")} {census.riskCount}
        </span>
      )}
      {census.evidenceCount > 0 && (
        <span className="stripChip static">
          <i style={{ background: edgeStyle("source_ref").color }} />
          {t("scene.evidence")} {census.evidenceCount}
        </span>
      )}
      {census.unsourcedCount > 0 && (
        <button
          className={filter === "unsourced" ? "stripChip active" : "stripChip"}
          onClick={() => onFilter(filter === "unsourced" ? null : ("unsourced" as SceneFilter))}
          title={t("misc.showOnly", { label: t("scene.unsourced") })}
          type="button"
        >
          <i style={{ background: "#8b93c9" }} />
          {t("scene.unsourced")} {census.unsourcedCount}
        </button>
      )}
      {census.rawCount > 0 && (
        <button
          className={filter === "raw" ? "stripChip active rawChip" : "stripChip rawChip"}
          onClick={() => onFilter(filter === "raw" ? null : ("raw" as SceneFilter))}
          title={t("misc.showOnly", { label: t("world.raw") })}
          type="button"
        >
          <i style={{ background: "#57d9a0", borderRadius: 0 }} />◆ {t("world.raw")} {census.rawCount}
        </button>
      )}
      {census.hidden > 0 && (
        <span className="stripChip static" title={t("scene.hiddenTitle")}>
          {t("scene.hiddenTotal", { hidden: census.hidden, total: census.total })}
        </span>
      )}
      <button className={keyOpen ? "stripChip active keyChip" : "stripChip keyChip"} onClick={() => setKeyOpen((open) => !open)} type="button">
        {t("scene.key")}
      </button>
      {keyOpen && (
        <div
          className="radarKeyPopover"
          role="dialog"
          aria-label={t("scene.keyAria")}
          data-testid="overlay-legend"
          data-overlay={census.overlay}
          data-overlay-token-version={SEMANTIC_VISUAL_TOKENS_VERSION}
        >
          <div className="overlayLegendScale">
            <span>{t("scene.keyColorLabel")}</span>
            <p>{t("scene.keyColor")}</p>
            <ul>
              {census.overlaySignals.map((entry) => (
                <li
                  key={entry.state}
                  data-overlay-state={entry.state}
                  style={{ "--overlay-color": entry.color } as React.CSSProperties}
                >
                  <i aria-hidden>{entry.symbol}</i>
                  {localizedEncodingText(entry)} · {entry.visibleCount}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <span>{t("scene.keyPositionLabel")}</span>
            <p>{t("scene.keyPosition")}</p>
            <ul className="contextPositionLegend">
              {census.contexts.map((entry) => (
                <li key={entry.key}>⌖ {entry.label} · {entry.count}</li>
              ))}
            </ul>
          </div>
          <div>
            <span>{t("scene.keyShapeLabel")}</span>
            <p>{t("scene.keyShape")}</p>
          </div>
          <div>
            <span>{t("scene.keyLinesLabel")}</span>
            <ul>
              {census.edgeCounts.map((entry) => (
                <li key={entry.key}>
                  <i style={{ background: entry.color }} />
                  {entry.label} · {entry.count}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <span>{t("scene.keyUseLabel")}</span>
            <p>{t("scene.keyUse")}</p>
          </div>
        </div>
      )}
    </div>
  );
}

// What hovering an ANCHOR shows beyond the page facts: its architecture — the
// RTS "city tooltip" (landmark, population under its lenses, care debt).
export type AnchorHoverInfo = {
  landmark: string;
  lensedPages: number;
  relationsDue: number;
  missions: number;
};

export function groupForHoverNode(node: LayoutNode, groups: WorldGroup[] = []): WorldGroup | undefined {
  if (!node.isGroup) return undefined;
  return groups.find(
    (group) =>
      group.key === node.groupKey ||
      group.key === node.groupDrill?.group ||
      group.key === node.id ||
      group.drill?.group === node.groupKey ||
      (group.kind === node.groupKind && group.labelKey === node.groupLabelKey)
  );
}

function groupTitle(node: LayoutNode, group: WorldGroup | undefined): string {
  if (!node.isGroup) return node.title;
  const kind = group?.kind ?? node.groupKind ?? "";
  const labelKey = group?.labelKey ?? node.groupLabelKey ?? node.title;
  return worldGroupLabel(kind, labelKey);
}

function groupCountLine(node: LayoutNode, group: WorldGroup | undefined): string {
  const region = group?.region;
  const count = region?.summary.total ?? group?.count ?? node.groupMemberIds?.length ?? 0;
  const shown = region?.summary.shown ?? group?.shown;
  const hidden = region?.summary.hidden ?? (typeof shown === "number" ? Math.max(count - shown, 0) : 0);
  const countText = count === 1 ? "1 page" : `${count} pages`;
  const shownText = typeof shown === "number" && shown < count ? ` · ${shown} visible` : "";
  const hiddenText = hidden > 0 ? ` · ${hidden} hidden` : "";
  return `${countText}${shownText}${hiddenText}`;
}

export function groupCompositionForTooltip(node: LayoutNode, group: WorldGroup | undefined): { key: string; label: string; count: number; color: string }[] {
  const fromRegion = group?.region?.type_mix?.map((entry) => ({
    key: entry.family,
    label: pageTypeLabel(`visual_group_${entry.family}`),
    count: entry.count,
    color: pageTypeStyle(`visual_group_${entry.family}`).accent
  }));
  const fromNode = node.groupComposition?.map((entry) => ({
    key: entry.family,
    label: pageTypeLabel(`visual_group_${entry.family}`),
    count: entry.count,
    color: pageTypeStyle(`visual_group_${entry.family}`).accent
  }));
  return (fromRegion && fromRegion.length > 0 ? fromRegion : fromNode ?? []).slice(0, 5);
}

export type TooltipSignalChip = {
  key: string;
  label: string;
  value: string | number;
  color: string;
};

export function orbitClusterSignalsForTooltip(node: LayoutNode): TooltipSignalChip[] {
  const inspection = node.inspection?.kind === "orbit_cluster" ? node.inspection : null;
  if (!inspection) return [];
  const familyStyle = pageTypeStyle(`visual_group_${inspection.family}`);
  const laneColor =
    inspection.laneKind === "attention"
      ? trustColor("stale")
      : inspection.laneKind === "evidence"
        ? edgeStyle("source_ref").color
        : inspection.laneKind === "gap"
          ? "#8b93c9"
          : familyStyle.accent;
  return [
    {
      key: "family",
      label: t("tooltip.cluster.family"),
      value: familyStyle.label,
      color: familyStyle.accent
    },
    {
      key: "count",
      label: t("tooltip.cluster.children"),
      value: inspection.count,
      color: familyStyle.accent
    },
    {
      key: "lane",
      label: t("tooltip.cluster.signal"),
      value: t(`tooltip.cluster.lane.${inspection.laneKind}`),
      color: laneColor
    }
  ];
}

export function pageSignalsForTooltip(node: LayoutNode): TooltipSignalChip[] {
  const style = pageTypeStyle(node.page_type);
  const family = style.family || "content";
  const familyColor = style.accent || contextStyle(node.context).accent;
  const trustKey = node.approved_state === "proposal" ? "proposal" : node.risk_flags.length > 0 ? "risk" : node.freshness_state;
  const chips: TooltipSignalChip[] = [
    {
      key: "type",
      label: pageTypeLabel(node.page_type),
      value: pageTypeLabel(`visual_group_${family}`),
      color: familyColor
    },
    {
      key: "state",
      label: freshnessLabel(node.freshness_state),
      value: node.approved_state === "proposal" ? t("scene.trust.proposal") : node.risk_flags.length > 0 ? t("scene.trust.risk") : freshnessLabel(node.freshness_state),
      color: trustColor(trustKey)
    }
  ];
  if (node.source_ref_count > 0) {
    chips.push({
      key: "evidence",
      label: t("scene.evidence"),
      value: node.source_ref_count,
      color: edgeStyle("source_ref").color
    });
  }
  const links = node.inbound_links + node.outbound_links;
  if (links > 0) {
    chips.push({
      key: "links",
      label: t("scene.links"),
      value: links,
      color: contextStyle(node.context).accent
    });
  }
  if (node.risk_flags.length > 0) {
    chips.push({
      key: "risk",
      label: t("decision.risk"),
      value: node.risk_flags.length,
      color: trustColor("risk")
    });
  }
  return chips.slice(0, 5);
}

function groupAttentionForTooltip(node: LayoutNode, group: WorldGroup | undefined): string[] {
  const region = group?.region;
  if (region) {
    const attention = region.attention_hints.slice(0, 4).map((hint) => t(`region.attention.${hint.kind}`, { n: hint.count }));
    const action = region.action_hints[0] ? [t(region.action_hints[0].label_key, { n: region.action_hints[0].count })] : [];
    return [...attention, ...action];
  }
  const attention: string[] = [];
  if (node.freshness_state === "stale") attention.push(t("trust.needsRefresh"));
  if (node.approved_state === "proposal") attention.push(t("decision.approval"));
  if (node.risk_flags.length > 0) attention.push(t("decision.risk"));
  if (node.source_ref_count > 0) attention.push(`${node.source_ref_count} ${t("scene.evidence")}`);
  return attention.slice(0, 4);
}

export function HoverTooltip({
  hover,
  anchorInfo,
  groups = []
}: {
  hover: { node: LayoutNode; x: number; y: number } | null;
  anchorInfo?: Record<string, AnchorHoverInfo>;
  groups?: WorldGroup[];
}) {
  if (!hover) return null;
  const { node } = hover;
  const anchor = anchorInfo?.[node.id];
  const group = groupForHoverNode(node, groups);
  const composition = node.isGroup ? groupCompositionForTooltip(node, group) : [];
  const attention = node.isGroup ? groupAttentionForTooltip(node, group) : [];
  const isGroup = Boolean(node.isGroup);
  const isOrbitCluster = node.inspection?.kind === "orbit_cluster";
  const orbitClusterSignals = isOrbitCluster ? orbitClusterSignalsForTooltip(node) : [];
  const pageSignals = !isGroup ? pageSignalsForTooltip(node) : [];
  return (
    <div className={isGroup ? "radarTooltip groupTooltip" : isOrbitCluster ? "radarTooltip orbitClusterTooltip" : "radarTooltip"} style={{ left: hover.x + 14, top: hover.y + 12 }}>
      <strong>{isGroup ? groupTitle(node, group) : node.title}</strong>
      {isGroup ? (
        <>
          <span>
            {pageTypeLabel(node.page_type)} · {groupCountLine(node, group)}
          </span>
          {composition.length > 0 && (
            <span className="tooltipComposition">
              {composition.map((entry) => (
                <i key={entry.key} style={{ borderColor: entry.color }}>
                  <b style={{ background: entry.color }} />
                  {entry.label} {entry.count}
                </i>
              ))}
            </span>
          )}
          {attention.length > 0 ? (
            <span className="tooltipAttention">{attention.join(" · ")}</span>
          ) : (
            <span>{t("region.healthy")}</span>
          )}
          <span>
            ← {node.inbound_links} in · → {node.outbound_links} out · {node.source_ref_count} {t("scene.evidence")}
          </span>
        </>
      ) : isOrbitCluster ? (
        <>
          <span>{t("tooltip.cluster.kind")}</span>
          {orbitClusterSignals.length > 0 && (
            <span className="tooltipSignals" aria-label={orbitClusterSignals.map((entry) => `${entry.label} ${entry.value}`).join(", ")}>
              {orbitClusterSignals.map((entry) => (
                <i key={entry.key} title={`${entry.label}: ${entry.value}`} style={{ borderColor: entry.color }}>
                  <b style={{ background: entry.color }} />
                  <span>{entry.label}</span>
                  <em>{entry.value}</em>
                </i>
              ))}
            </span>
          )}
          <span className="tooltipAttention">{t("tooltip.cluster.openRepresentative")}</span>
          <span>
            ← {node.inbound_links} {t("tooltip.cluster.realChildren")} · {node.source_ref_count} {t("scene.evidence")}
          </span>
        </>
      ) : (
        <>
          <span>
            {pageTypeLabel(node.page_type)} · {contextStyle(node.context).label}
            {isRawData(node.page_type) ? ` · ◆ ${t("world.raw")}` : ""}
          </span>
          {pageSignals.length > 0 && (
            <span className="tooltipSignals" aria-label={pageSignals.map((entry) => `${entry.label} ${entry.value}`).join(", ")}>
              {pageSignals.map((entry) => (
                <i key={entry.key} title={`${entry.label}: ${entry.value}`} style={{ borderColor: entry.color }}>
                  <b style={{ background: entry.color }} />
                  <span>{entry.label}</span>
                  <em>{entry.value}</em>
                </i>
              ))}
            </span>
          )}
          {anchor && (
            <span className="tooltipAnchor">
              {landmarkGlyph(anchor.landmark)} {anchor.landmark}
              {anchor.lensedPages > 0 ? ` · ${t("tooltip.lensed", { n: anchor.lensedPages })}` : ""}
              {anchor.relationsDue > 0 ? ` · ${t("tooltip.due", { n: anchor.relationsDue })}` : ""}
              {anchor.missions > 0 ? ` · ${t("tooltip.missions", { n: anchor.missions })}` : ""}
            </span>
          )}
          <span>
            {freshnessLabel(node.freshness_state)}
            {node.ageDays > 0 ? ` · ${Math.round(node.ageDays)}d since update` : ""}
          </span>
          <span>
            ← {node.inbound_links} in · → {node.outbound_links} out · evidence {node.source_ref_count}
          </span>
          {node.risk_flags.length > 0 && <span className="tooltipRisk">{node.risk_flags.join(", ").replaceAll("_", " ")}</span>}
        </>
      )}
    </div>
  );
}
