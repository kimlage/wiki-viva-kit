// Scene labels: the budgeted label set (root, selection, risks, overdue,
// drafts, review, hubs — in that priority), the tiered node label renderer,
// and the diegetic group rim pills with honest shown/total counts.

import { Html } from "@react-three/drei";
import { useMemo } from "react";
import type { CSSProperties, RefObject } from "react";
import { t } from "../../../data/i18n";
import { contextStyle, edgeStyle, pageTypeStyle, trustColor, worldGroupLabel } from "../../../data/presentation";
import { primitiveSlotClass, resolvePrimitiveForSlot } from "../../../data/visualPrimitives";
import { localizedEncodingAria, localizedEncodingText, visualEncodingResolver } from "../../../data/visualEncoding";
import type { LayoutNode } from "../../../scene/layout";
import { parseRegionDrillKey } from "../../../scene/perspectives";
import type { WorldGroup, WorldLayout } from "../../../scene/perspectives";
import type { SceneFacet } from "../../../scene/facets";
import type { OverlayId } from "../../../world/contracts";
import { MorphingNodeGroup } from "./nodes";
import type { MorphState } from "./nodes";

export type SceneLabel = {
  node: LayoutNode;
  annotation: string | null;
  annotationColor: string | null;
  compact?: boolean;
  mode?: "full" | "glyph" | "metric";
};

export function labelTitleForNode(node: LayoutNode): string {
  return node.isGroup ? worldGroupLabel(node.groupKind ?? "", node.groupLabelKey ?? node.title) : node.title;
}

export function compactGroupMetric(node: LayoutNode): string | null {
  if (!node.isGroup) return null;
  if (node.groupKind === "quadrant" && !node.isRoot) return null;
  const count = node.groupMemberIds?.length ?? 0;
  if (count <= 0) return null;
  const top = node.groupComposition?.[0];
  if (!top || node.isRoot) return String(count);
  return top.count === count ? String(count) : `${count} · ${top.count}`;
}

export type GroupCompositionChip = {
  family: string;
  count: number;
  color: string;
  share: number;
};

export type GroupStateChip = {
  kind: "action" | "risk" | "stale" | "proposal" | "evidence" | "gap";
  count: number;
  color: string;
  label: string;
  intensity: number;
};

export function groupCompositionChipsForLabel(node: LayoutNode, limit = 4): GroupCompositionChip[] {
  if (!node.isGroup || !node.groupComposition?.length) return [];
  const total = node.groupComposition.reduce((sum, entry) => sum + Math.max(entry.count, 0), 0);
  if (total <= 0) return [];
  return [...node.groupComposition]
    .filter((entry) => entry.count > 0)
    .sort((a, b) => b.count - a.count || a.family.localeCompare(b.family))
    .slice(0, limit)
    .map((entry) => ({
      family: entry.family,
      count: entry.count,
      color: pageTypeStyle(`visual_group_${entry.family}`).accent || pageTypeStyle("visual_group_content").accent,
      share: Number((entry.count / total).toFixed(4))
    }));
}

export function groupStateChipsForLabel(node: LayoutNode, group?: WorldGroup, limit = 4): GroupStateChip[] {
  if (!node.isGroup) return [];
  const region = group?.region;
  const summary = region?.summary;
  const action = region?.action_hints?.[0];
  const memberCount = Math.max(node.groupMemberIds?.length ?? group?.count ?? 1, 1);
  const chips: GroupStateChip[] = [];
  const push = (kind: GroupStateChip["kind"], count: number, color: string, label: string, priority: number) => {
    if (count <= 0) return;
    chips.push({
      kind,
      count,
      color,
      label,
      intensity: Number(Math.min(1, Math.max(0.18, count / memberCount + priority * 0.08)).toFixed(4))
    });
  };

  push("action", action?.count ?? summary?.open_actions ?? 0, "#ffd27a", action ? t(action.label_key, { n: action.count }) : "open actions", 5);
  push("risk", summary?.risk ?? (node.risk_flags.length > 0 ? 1 : 0), trustColor("risk"), "risk", 4);
  push("stale", summary?.stale ?? (node.freshness_state === "stale" ? 1 : 0), trustColor("stale"), "stale", 3);
  push("proposal", summary?.proposal ?? (node.approved_state === "proposal" ? 1 : 0), trustColor("proposal"), "review", 2);
  push(
    "evidence",
    summary?.source_backed ?? (node.source_ref_count > 0 ? Math.max(1, Math.min(node.source_ref_count, memberCount)) : node.groupLabelKey === "source" ? memberCount : 0),
    edgeStyle("source_ref").color,
    "source backed",
    1
  );
  push("gap", summary?.unsourced ?? 0, "#9aa3ff", "unsourced", 0);

  return chips
    .sort((a, b) => {
      const order = ["action", "risk", "stale", "proposal", "gap", "evidence"];
      return order.indexOf(a.kind) - order.indexOf(b.kind) || b.count - a.count || a.kind.localeCompare(b.kind);
    })
    .slice(0, limit);
}

export function groupHandleForLabel(node: LayoutNode, groups: WorldGroup[]): WorldGroup | undefined {
  if (!node.isGroup) return undefined;
  const existing = groups.find(
    (group) =>
      group.key === node.groupKey ||
      group.key === node.groupDrill?.group ||
      group.key === node.id ||
      (group.kind === node.groupKind && group.labelKey === node.groupLabelKey)
  );
  if (existing) return existing;
  if (!node.groupDrill || !node.groupKind || !node.groupLabelKey) return undefined;
  const count = node.groupMemberIds?.length ?? 0;
  return {
    key: node.groupKey ?? node.id,
    kind: node.groupKind as WorldGroup["kind"],
    labelKey: node.groupLabelKey,
    count,
    shown: Math.min(count, node.groupPreviewIds?.length ?? count),
    anchor: node.position,
    drill: node.groupDrill,
    memberIds: node.groupMemberIds ?? []
  };
}

export function labelLiftForNode(node: LayoutNode, tier = 0): number {
  if (node.isGroup) {
    const groupLift = node.isRoot ? node.scale * 2.35 + 0.24 : node.scale * 3 + 0.28;
    return groupLift + tier * 0.36;
  }
  return node.scale * 1.7 + 0.14 + tier * 0.3;
}

export function buildLabelSet(
  layout: WorldLayout,
  highlightedIds: Set<string>,
  selectedId: string,
  budget: number,
  activeQuadrant?: SceneFacet
): SceneLabel[] {
  const seen = new Set<string>();
  const labels: SceneLabel[] = [];
  const scopedQuadrantDrill = layout.perspective === "quadrants" && layout.level >= 1;
  const quadrantRoot = layout.perspective === "quadrants" && layout.level === 0;
  const push = (node: LayoutNode | undefined, annotation: string | null, annotationColor: string | null, compact = false, mode: SceneLabel["mode"] = "full") => {
    if (!node || seen.has(node.id)) return;
    seen.add(node.id);
    labels.push({ node, annotation, annotationColor, compact, mode });
  };
  const byOverdue = [...layout.nodes].sort((a, b) => b.overdueRatio - a.overdueRatio || a.title.localeCompare(b.title));

  push(layout.nodes.find((node) => node.isRoot), null, null);
  if (selectedId) push(layout.nodes.find((node) => node.id === selectedId || node.path === selectedId), null, null);

  const candidates: SceneLabel[] = [];
  for (const node of byOverdue) {
    if (node.isGroup) continue;
    if (scopedQuadrantDrill) continue;
    if (node.risk_flags.length > 0) {
      candidates.push({ node, annotation: node.risk_flags[0].replaceAll("_", " "), annotationColor: trustColor("risk") });
    }
  }
  let staleLabels = 0;
  for (const node of byOverdue) {
    if (node.isGroup) continue;
    if (scopedQuadrantDrill) continue;
    if (quadrantRoot && staleLabels >= 2) continue;
    if (node.freshness_state === "stale") {
      const overdueDays = Math.max(0, Math.round(node.ageDays - node.ageDays / Math.max(node.overdueRatio, 0.01)));
      candidates.push({
        node,
        annotation: node.overdueRatio > 1 ? `${overdueDays}d overdue` : "needs refresh",
        annotationColor: trustColor("stale")
      });
      staleLabels += 1;
    }
  }
  for (const node of byOverdue) {
    if (node.isGroup) continue;
    if (scopedQuadrantDrill) continue;
    if (node.approved_state === "proposal") {
      candidates.push({ node, annotation: "draft change", annotationColor: trustColor("proposal") });
    }
  }
  let highlightLabels = 0;
  for (const node of layout.nodes) {
    if (highlightLabels >= 4) break;
    if (highlightedIds.has(node.id) || highlightedIds.has(node.path)) {
      candidates.push({ node, annotation: "in review", annotationColor: "#8fd0e8" });
      highlightLabels += 1;
    }
  }
  if (scopedQuadrantDrill) {
    for (const node of layout.nodes) {
      if (!node.isRoot && !node.isGroup) candidates.push({ node, annotation: null, annotationColor: null });
    }
  } else if (quadrantRoot) {
    const previewIds = new Set(
      layout.nodes
        .filter((node) => node.isGroup && (!activeQuadrant || parseRegionDrillKey(node.id)?.facet === activeQuadrant))
        .flatMap((node) => node.groupPreviewIds ?? [])
    );
    for (const node of layout.nodes) {
      if (previewIds.has(node.id)) candidates.push({ node, annotation: null, annotationColor: null, compact: true });
      else if (activeQuadrant && !node.isGroup && node.quadrant === activeQuadrant) {
        candidates.push({ node, annotation: null, annotationColor: null, compact: true });
      }
    }
  }
  const groupLabelCandidates = layout.nodes
    .filter((node) => node.isGroup)
    .sort((a, b) => {
      const rootRank = Number(b.isRoot) - Number(a.isRoot);
      if (rootRank !== 0) return rootRank;
      const familyRank = scopedQuadrantDrill ? Number(b.groupKind === "region_family") - Number(a.groupKind === "region_family") : 0;
      if (familyRank !== 0) return familyRank;
      const quadrantRank = scopedQuadrantDrill
        ? Number(a.groupKind === "quadrant") - Number(b.groupKind === "quadrant")
        : Number(b.groupKind === "quadrant") - Number(a.groupKind === "quadrant");
      if (quadrantRank !== 0) return quadrantRank;
      return (b.groupMemberIds?.length ?? 0) - (a.groupMemberIds?.length ?? 0) || a.title.localeCompare(b.title);
  });
  let scopedFamilyLabels = 0;
  for (const node of groupLabelCandidates) {
    if (scopedQuadrantDrill) {
      const isFamily = node.groupKind === "region_family";
      const familyTextLimit = layout.level >= 2 ? 3 : 5;
      const deepDrill = layout.level >= 2;
      const mode: SceneLabel["mode"] = node.isRoot
        ? "full"
        : deepDrill && isFamily && scopedFamilyLabels < familyTextLimit
          ? "metric"
          : !deepDrill && isFamily && scopedFamilyLabels < familyTextLimit
            ? "full"
            : "glyph";
      if (isFamily && !node.isRoot) scopedFamilyLabels += 1;
      candidates.push({ node, annotation: mode === "glyph" ? null : node.isRoot ? null : compactGroupMetric(node), annotationColor: "#9fdff4", compact: !node.isRoot, mode });
      continue;
    }
    if (quadrantRoot && !node.isRoot) {
      const region = parseRegionDrillKey(node.id);
      if (node.groupKind !== "family" || (activeQuadrant && region?.facet !== activeQuadrant)) continue;
      candidates.push({ node, annotation: compactGroupMetric(node), annotationColor: "#9fdff4", compact: true, mode: "full" });
      continue;
    }
    candidates.push({ node, annotation: quadrantRoot && !node.isRoot ? null : compactGroupMetric(node), annotationColor: "#9fdff4", compact: quadrantRoot && !node.isRoot });
  }
  for (const node of layout.nodes) {
    if (quadrantRoot && node.isGroup) continue;
    if (node.isHub && !node.isRoot) candidates.push({ node, annotation: null, annotationColor: null });
  }
  for (const candidate of candidates) {
    if (labels.length >= budget + 2) break;
    const compact = candidate.compact || (scopedQuadrantDrill && !candidate.node.isRoot && !candidate.node.isGroup);
    push(candidate.node, candidate.annotation, candidate.annotationColor, compact, candidate.mode);
  }
  return labels;
}

export function labelsForActivePlate(labels: SceneLabel[], plateNode: LayoutNode | null | undefined): SceneLabel[] {
  if (!plateNode) return labels;
  return labels.filter((label) => label.node.id !== plateNode.id && label.node.path !== plateNode.path);
}

export function NodeLabels({
  labels,
  overlay,
  selectedId,
  morph,
  groups = [],
  onGroupSelect,
  onNodeSelect
}: {
  labels: SceneLabel[];
  overlay: OverlayId;
  selectedId: string;
  morph: RefObject<MorphState>;
  groups?: WorldGroup[];
  onGroupSelect?: (group: WorldGroup) => void;
  onNodeSelect?: (node: LayoutNode) => void;
}) {
  const tiers = useMemo(() => {
    const buckets = new Map<number, SceneLabel[]>();
    for (const label of labels) {
      const angle = Math.atan2(label.node.position[2], label.node.position[0]);
      const bucket = Math.round(angle / 0.42);
      const list = buckets.get(bucket) ?? [];
      list.push(label);
      buckets.set(bucket, list);
    }
    const tierById = new Map<string, number>();
    for (const list of buckets.values()) {
      list
        .sort(
          (a, b) =>
            Math.hypot(a.node.position[0], a.node.position[2]) - Math.hypot(b.node.position[0], b.node.position[2]) ||
            a.node.id.localeCompare(b.node.id)
        )
        .forEach((label, index) => tierById.set(label.node.id, index));
    }
    return tierById;
  }, [labels]);
  return (
    <group>
      {labels.map(({ node, annotation, annotationColor, compact, mode = "full" }) => {
        const selected = node.id === selectedId || node.path === selectedId;
        const labelTitle = labelTitleForNode(node);
        const lift = labelLiftForNode(node, tiers.get(node.id) ?? 0);
        const labelClass = [
          node.isGroup ? "nodeGroupLabel" : "",
          node.isGroup && node.isRoot ? "nodeGroupLabelRoot" : "",
          node.isGroup && !node.isRoot ? "nodeGroupLabelSatellite" : "",
          compact ? "nodeCompactLabel" : "",
          mode === "metric" ? "nodeMetricLabel" : "",
          mode === "glyph" ? "nodeGlyphOnlyLabel" : ""
        ].filter(Boolean).join(" ");
        const distanceFactor = compact || (node.isGroup && !node.isRoot) ? undefined : node.isGroup ? 3.8 : 4;
        const groupHandle = groupHandleForLabel(node, groups);
        const interactiveGroup = Boolean(groupHandle?.drill && onGroupSelect);
        const bodyClass = ["nodeLabelBody", labelClass].filter(Boolean).join(" ");
        const showTitle = mode === "full";
        const showMetric = mode === "full" || mode === "metric";
        const compositionChips = mode !== "glyph" ? groupCompositionChipsForLabel(node) : [];
        const compositionLabel = compositionChips.map((chip) => `${chip.family} ${chip.count}`).join(", ");
        const stateChips = mode !== "glyph" ? groupStateChipsForLabel(node, groupHandle) : [];
        const stateLabel = stateChips.map((chip) => `${chip.label} ${chip.count}`).join(", ");
        const composition = compositionChips.length > 0 && (
          <span className="nodeGroupComposition" aria-label={`composition: ${compositionLabel}`} title={compositionLabel}>
            {compositionChips.map((chip) => (
              <i
                key={`${node.id}-${chip.family}`}
                style={{ "--chip-color": chip.color, "--chip-share": `${Math.max(chip.share * 100, 8)}%` } as CSSProperties}
              >
                <b>{chip.count}</b>
              </i>
            ))}
          </span>
        );
        const stateRail = stateChips.length > 0 && (
          <span className="nodeGroupStateRail" aria-label={`state: ${stateLabel}`} title={stateLabel}>
            {stateChips.map((chip) => (
              <i
                key={`${node.id}-${chip.kind}`}
                className={`state-${chip.kind}`}
                style={{ "--state-color": chip.color, "--state-intensity": chip.intensity } as CSSProperties}
              >
                <b>{Math.min(chip.count, 99)}</b>
              </i>
            ))}
          </span>
        );
        const overlayEncoding = visualEncodingResolver.resolve(node, overlay);
        const overlayText = localizedEncodingText(overlayEncoding);
        const overlayAria = localizedEncodingAria(overlayEncoding);
        const overlaySignal = (
          <span
            className={`nodeOverlaySignal ring-${overlayEncoding.ring}`}
            data-overlay={overlay}
            data-overlay-state={overlayEncoding.state}
            data-overlay-token-version={overlayEncoding.version}
            aria-label={overlayAria}
            title={overlayAria}
            style={{ "--overlay-color": overlayEncoding.color } as CSSProperties}
          >
            <b aria-hidden>{overlayEncoding.symbol}</b>
            <small>{overlayText}</small>
          </span>
        );
        const interactivePage = !node.isGroup && Boolean(onNodeSelect);
        const targetKind = node.isGroup ? "group" : "page";
        const body = interactiveGroup && groupHandle ? (
          <button
            aria-label={labelTitle}
            className={bodyClass}
            data-world-target-id={node.groupDrill?.group ?? node.groupKey ?? node.id}
            data-world-target-kind={targetKind}
            onClick={(event) => {
              event.stopPropagation();
              onGroupSelect?.(groupHandle);
            }}
            title={labelTitle}
            type="button"
          >
            {node.visualGlyph && <i className="nodeVisualGlyph" aria-hidden>{node.visualGlyph}</i>}
            {showTitle && <strong>{labelTitle}</strong>}
            {showMetric && annotation && <em style={{ color: annotationColor ?? undefined }}>{annotation}</em>}
            {overlaySignal}
            {stateRail}
            {composition}
          </button>
        ) : interactivePage ? (
          <button
            aria-label={labelTitle}
            className={bodyClass}
            data-world-target-id={node.id}
            data-world-target-kind="page"
            onClick={(event) => {
              event.stopPropagation();
              onNodeSelect?.(node);
            }}
            title={labelTitle}
            type="button"
          >
            {showTitle && <strong>{labelTitle}</strong>}
            {showMetric && annotation && <em style={{ color: annotationColor ?? undefined }}>{annotation}</em>}
            {overlaySignal}
          </button>
        ) : (
          <span aria-hidden="true" className={bodyClass || undefined} data-world-decorative="true" title={labelTitle}>
            {node.visualGlyph && <i className="nodeVisualGlyph" aria-hidden>{node.visualGlyph}</i>}
            {showTitle && <strong>{labelTitle}</strong>}
            {showMetric && annotation && <em style={{ color: annotationColor ?? undefined }}>{annotation}</em>}
            {overlaySignal}
            {stateRail}
            {composition}
          </span>
        );
        return (
          <MorphingNodeGroup key={`label-${node.id}`} node={node} morph={morph}>
            <Html
              position={[0, lift, 0]}
              center
              distanceFactor={distanceFactor}
              className={selected ? "radarLabel selected" : "radarLabel"}
              wrapperClass={interactiveGroup || interactivePage ? "sceneHtmlLabel sceneHtmlControl" : "sceneHtmlLabel"}
              zIndexRange={[30, 0]}
            >
              {body}
            </Html>
          </MorphingNodeGroup>
        );
      })}
    </group>
  );
}

// Rim pills: the diegetic group handles. Only destinations with a real drill
// are controls; terminal map captions stay visibly static and mouse-inert.
export function GroupRimPills({
  groups,
  focusedGroupKey,
  onGroupSelect
}: {
  groups: WorldGroup[];
  focusedGroupKey: string;
  onGroupSelect: (group: WorldGroup) => void;
}) {
  return (
    <group>
      {groups.map((group) => {
        const accent = group.kind === "context" ? contextStyle(group.labelKey).accent : "#4f8fb5";
        const region = group.region;
        const primitive = resolvePrimitiveForSlot(null, region, "region.card");
        const topType = region?.type_mix?.[0];
        const attention = region?.attention_hints?.slice(0, 3) ?? [];
        const action = region?.action_hints?.[0];
        // An empty facet lens is an honest absence — a dimmed, non-interactive
        // "no X lens registered" wedge rather than a clickable pill over nothing.
        const emptyFacet = group.kind === "facet" && group.count === 0;
        const interactive = !emptyFacet && Boolean(group.drill || group.kind === "quadrant");
        const label = emptyFacet
          ? t("focus.emptyFacet", { facet: worldGroupLabel(group.kind, group.labelKey) })
          : worldGroupLabel(group.kind, group.labelKey);
        const header = (
          <span className="rimHeader">
            <strong>{label}</strong>
            {!emptyFacet && <small>{group.shown < group.count ? `${group.shown}/${group.count}` : group.count}</small>}
          </span>
        );
        return (
          <Html key={`rim-${group.key}`} position={group.anchor} center distanceFactor={5.2} wrapperClass={interactive ? "sceneHtmlLabel sceneHtmlControl" : "sceneHtmlLabel"} className="radarRimPill" zIndexRange={[40, 0]}>
            {interactive ? <button
              aria-label={label}
              data-world-target-id={group.drill?.group ?? group.key}
              data-world-target-kind="group"
              style={{ borderColor: emptyFacet ? "#3a4652" : accent, pointerEvents: emptyFacet ? "none" : "auto" }}
              className={[
                emptyFacet ? "emptyFacet" : "",
                focusedGroupKey === group.key ? "focused" : "",
                region ? "regionRimCard" : "",
                primitiveSlotClass(region, "region.card")
              ].filter(Boolean).join(" ")}
              onClick={(event) => {
                event.stopPropagation();
                if (!emptyFacet) onGroupSelect(group);
              }}
              disabled={emptyFacet}
              title={region ? primitive.purpose : undefined}
              type="button"
            >
              {header}
              {region && (
                <>
                  <span className="rimTypeMix">
                    {topType ? `${topType.family} ${topType.count}` : region.summary.total === 0 ? t("region.empty") : t("region.mixed")}
                  </span>
                  {attention.length > 0 ? (
                    <span className="rimAttentionRail">
                      {attention.map((hint) => (
                        <i key={hint.kind} className={`attention-${hint.kind}`}>{t(`region.attention.${hint.kind}`, { n: hint.count })}</i>
                      ))}
                    </span>
                  ) : (
                    <span className="rimAttentionRail calm">{t("region.healthy")}</span>
                  )}
                  {action && <em className="rimAction">{t(action.label_key, { n: action.count })}</em>}
                </>
              )}
            </button> : (
              <span className="rimStaticLabel" data-world-decorative="true" aria-hidden="true">
                {header}
              </span>
            )}
          </Html>
        );
      })}
    </group>
  );
}
