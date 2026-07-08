// Scene labels: the budgeted label set (root, selection, risks, overdue,
// drafts, review, hubs — in that priority), the tiered node label renderer,
// and the diegetic group rim pills with honest shown/total counts.

import { Html } from "@react-three/drei";
import { useMemo } from "react";
import { t } from "../../data/i18n";
import { contextStyle, trustColor, worldGroupLabel } from "../../data/presentation";
import { primitiveSlotClass, resolvePrimitiveForSlot } from "../../data/visualPrimitives";
import type { LayoutNode } from "../layout";
import type { WorldGroup, WorldLayout } from "../perspectives";

export type SceneLabel = {
  node: LayoutNode;
  annotation: string | null;
  annotationColor: string | null;
};

export function buildLabelSet(layout: WorldLayout, highlightedIds: Set<string>, selectedId: string, budget: number): SceneLabel[] {
  const seen = new Set<string>();
  const labels: SceneLabel[] = [];
  const push = (node: LayoutNode | undefined, annotation: string | null, annotationColor: string | null) => {
    if (!node || seen.has(node.id)) return;
    seen.add(node.id);
    labels.push({ node, annotation, annotationColor });
  };
  const byOverdue = [...layout.nodes].sort((a, b) => b.overdueRatio - a.overdueRatio || a.title.localeCompare(b.title));

  push(layout.nodes.find((node) => node.isRoot), null, null);
  if (selectedId) push(layout.nodes.find((node) => node.id === selectedId || node.path === selectedId), null, null);

  const candidates: SceneLabel[] = [];
  for (const node of byOverdue) {
    if (node.risk_flags.length > 0) {
      candidates.push({ node, annotation: node.risk_flags[0].replaceAll("_", " "), annotationColor: trustColor("risk") });
    }
  }
  for (const node of byOverdue) {
    if (node.freshness_state === "stale") {
      const overdueDays = Math.max(0, Math.round(node.ageDays - node.ageDays / Math.max(node.overdueRatio, 0.01)));
      candidates.push({
        node,
        annotation: node.overdueRatio > 1 ? `${overdueDays}d overdue` : "needs refresh",
        annotationColor: trustColor("stale")
      });
    }
  }
  for (const node of byOverdue) {
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
  for (const node of layout.nodes) {
    if (node.isHub && !node.isRoot) candidates.push({ node, annotation: null, annotationColor: null });
  }
  for (const candidate of candidates) {
    if (labels.length >= budget + 2) break;
    push(candidate.node, candidate.annotation, candidate.annotationColor);
  }
  return labels;
}

export function NodeLabels({ labels, selectedId }: { labels: SceneLabel[]; selectedId: string }) {
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
      {labels.map(({ node, annotation, annotationColor }) => {
        const selected = node.id === selectedId || node.path === selectedId;
        const lift = node.scale * 1.7 + 0.14 + (tiers.get(node.id) ?? 0) * 0.3;
        return (
          <Html
            key={`label-${node.id}`}
            position={[node.position[0], node.position[1] + lift, node.position[2]]}
            center
            distanceFactor={4}
            className={selected ? "radarLabel selected" : "radarLabel"}
            wrapperClass="sceneHtmlLabel"
            zIndexRange={[30, 0]}
          >
            <span>
              <strong>{node.title}</strong>
              {annotation && <em style={{ color: annotationColor ?? undefined }}>{annotation}</em>}
            </span>
          </Html>
        );
      })}
    </group>
  );
}

// Rim pills: the diegetic group handles. Honest shown/total counts; click
// drills (or cycles focus when the group has no deeper level).
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
        const label = emptyFacet
          ? t("focus.emptyFacet", { facet: worldGroupLabel(group.kind, group.labelKey) })
          : worldGroupLabel(group.kind, group.labelKey);
        return (
          <Html key={`rim-${group.key}`} position={group.anchor} center distanceFactor={5.2} wrapperClass="sceneHtmlLabel" className="radarRimPill" zIndexRange={[40, 0]}>
            <button
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
              <span className="rimHeader">
                <strong>{label}</strong>
                {!emptyFacet && <small>{group.shown < group.count ? `${group.shown}/${group.count}` : group.count}</small>}
              </span>
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
            </button>
          </Html>
        );
      })}
    </group>
  );
}
