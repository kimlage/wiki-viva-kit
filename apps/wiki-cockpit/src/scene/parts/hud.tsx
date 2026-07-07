// DOM HUD twins of the scene encodings: the honest census over visible nodes,
// the collapsible StatusStrip filter chips + Key popover, and the hover
// tooltip (page facts + the anchor "city tooltip" architecture line).

import { useState } from "react";
import { t } from "../../data/i18n";
import { contextStyle, edgeStyle, isRawData, landmarkGlyph, pageTypeLabel, trustColor } from "../../data/presentation";
import type { GraphEdge, GraphNode } from "../../types";
import type { LayoutNode } from "../layout";
import type { WorldLayout } from "../perspectives";
import { freshnessLabel, nodeTrustKey } from "./materials";
import type { TrustKey } from "./materials";
import { isEvidenceGap } from "./particles-layer";

export type SceneCensus = {
  trust: { key: TrustKey; label: string; color: string; count: number }[];
  riskCount: number;
  evidenceCount: number;
  unsourcedCount: number;
  rawCount: number;
  contexts: { key: string; label: string; color: string; count: number }[];
  edgeCounts: { key: string; label: string; color: string; count: number }[];
  hidden: number;
  total: number;
};

export function sceneCensus(nodes: GraphNode[], edges: GraphEdge[], layout: WorldLayout): SceneCensus {
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
    // Hue = area: the live color legend (Key popover) lists what is on screen.
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
        <div className="radarKeyPopover" role="dialog" aria-label="Map key">
          <div>
            <span>{t("scene.keyColorLabel")}</span>
            <p>{t("scene.keyColor")}</p>
            <ul>
              {census.contexts.map((entry) => (
                <li key={entry.key}>
                  <i style={{ background: entry.color }} />
                  {entry.label} · {entry.count}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <span>{t("scene.keyPositionLabel")}</span>
            <p>{t("scene.keyPosition")}</p>
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

export function HoverTooltip({
  hover,
  anchorInfo
}: {
  hover: { node: LayoutNode; x: number; y: number } | null;
  anchorInfo?: Record<string, AnchorHoverInfo>;
}) {
  if (!hover) return null;
  const { node } = hover;
  const anchor = anchorInfo?.[node.id];
  return (
    <div className="radarTooltip" style={{ left: hover.x + 14, top: hover.y + 12 }}>
      <strong>{node.title}</strong>
      <span>
        {pageTypeLabel(node.page_type)} · {contextStyle(node.context).label}
        {isRawData(node.page_type) ? ` · ◆ ${t("world.raw")}` : ""}
      </span>
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
    </div>
  );
}
