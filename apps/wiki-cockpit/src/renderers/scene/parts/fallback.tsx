// Minimap + 2D fallback: the same layout, the same URLs, zero motion.
// FallbackPlanView is the SVG plan (also the minimap disc inside the 3D
// shell); SceneFallback is the full reduced-motion / no-WebGL navigation
// surface — perspectives, levels, groups and pages as nested lists.

import { t } from "../../../data/i18n";
import { trustColor, worldGroupLabel } from "../../../data/presentation";
import { resolvePrimitiveForSlot } from "../../../data/visualPrimitives";
import { localizedEncodingAria, localizedEncodingText, SEMANTIC_VISUAL_TOKENS_VERSION, strongAttentionNodeIds, visualEncodingResolver } from "../../../data/visualEncoding";
import type { GitState } from "../../../types";
import type { ClusterStar, WorldGroup, WorldLayout } from "../../../scene/perspectives";
import { layoutNodeInstanceKeys } from "../../../scene/layout";
import type { ScenePatch } from "../../../components/SystemScene";
import { nodeDisplayColor, workspaceLabel } from "./materials";
import type { SceneFallbackReason } from "./materials";
import type { SceneCensus } from "./hud";
import type { OverlayId } from "../../../world/contracts";

export function FallbackPlanView({
  layout,
  overlay,
  selectedPageId,
  highlightedIds
}: {
  layout: WorldLayout;
  overlay: OverlayId;
  selectedPageId: string;
  highlightedIds: Set<string>;
}) {
  const size = 420;
  const scale = size / 2 / (layout.rOuter + 1.2);
  const px = (value: number) => size / 2 + value * scale;
  const band = layout.rOuter - layout.rInner;
  const deadlineR = (layout.rInner + band * layout.deadlineF) * scale;
  const strongAttention = strongAttentionNodeIds(layout.nodes);
  const instanceKeys = layoutNodeInstanceKeys(layout.nodes);
  return (
    <svg className="fallbackPlan" viewBox={`0 0 ${size} ${size}`} aria-hidden="true" focusable="false">
      {layout.guides
        .filter((guide): guide is Extract<typeof guide, { kind: "circle" }> => guide.kind === "circle")
        .map((guide, index) => (
          <circle key={`g-${index}`} cx={size / 2} cy={size / 2} r={guide.radius * scale} fill="none" stroke="#22303a" strokeOpacity="0.5" />
        ))}
      {layout.radial === "freshness" && (
        <>
          <circle cx={size / 2} cy={size / 2} r={layout.rInner * scale} fill="none" stroke="#22303a" strokeOpacity="0.5" />
          <circle cx={size / 2} cy={size / 2} r={layout.rOuter * scale} fill="none" stroke="#22303a" strokeOpacity="0.5" />
          <circle cx={size / 2} cy={size / 2} r={deadlineR} fill="none" stroke={trustColor("stale")} strokeOpacity="0.45" strokeDasharray="4 4" />
        </>
      )}
      {layout.wedges.map((wedge) => (
        <line
          key={`ray-${wedge.context}`}
          x1={px(Math.cos(wedge.startAngle) * layout.rInner)}
          y1={px(Math.sin(wedge.startAngle) * layout.rInner)}
          x2={px(Math.cos(wedge.startAngle) * layout.rOuter)}
          y2={px(Math.sin(wedge.startAngle) * layout.rOuter)}
          stroke="#22303a"
          strokeOpacity="0.4"
        />
      ))}
      {layout.groups.map((group) => (
        <text
          key={`plan-label-${group.key}`}
          x={px(group.anchor[0])}
          y={px(group.anchor[2])}
          className="planContextLabel"
          textAnchor="middle"
        >
          {worldGroupLabel(group.kind, group.labelKey)} · {group.shown < group.count ? `${group.shown}/${group.count}` : group.count}
        </text>
      ))}
      {layout.clusterStars.map((star) => (
        <g key={`plan-star-${star.key}`}>
          <circle
            cx={px(star.position[0])}
            cy={px(star.position[2])}
            r={Math.max(5, star.scale * scale * 1.6)}
            fill="#334a5c"
            stroke="#6bd7ff"
            strokeWidth={1.4}
          />
          <text x={px(star.position[0])} y={px(star.position[2]) + 3} className="planContextLabel" textAnchor="middle">
            +{star.count}
          </text>
        </g>
      ))}
      {layout.nodes.map((node, index) => {
        const highlighted = highlightedIds.has(node.id) || highlightedIds.has(node.path);
        const selected = node.id === selectedPageId || node.path === selectedPageId;
        const encoding = visualEncodingResolver.resolve(node, overlay);
        const attention = encoding.emissive >= 0.4;
        const strong = overlay !== "attention" || strongAttention.has(node.id);
        return (
          <circle
            key={`plan-${instanceKeys[index]}`}
            cx={px(node.position[0])}
            cy={px(node.position[2])}
            r={Math.max(node.isGroup ? 7 : attention ? 4 : 3, node.scale * scale * (node.isGroup ? 2.4 : attention ? 2 : 1.6))}
            fill={encoding.color}
            fillOpacity={node.isGroup ? 0.45 : encoding.opacity * (!selected && !highlighted ? 0.8 : 1)}
            stroke={selected ? "#dff8ff" : highlighted ? "#8fd0e8" : !strong || encoding.ring === "none" ? "none" : encoding.color}
            strokeWidth={selected || highlighted ? 2 : 1.4}
            strokeDasharray={encoding.ring === "dashed" ? "2 2" : undefined}
            data-overlay={overlay}
            data-overlay-state={encoding.state}
            data-overlay-strong={strong ? "true" : "false"}
          />
        );
      })}
    </svg>
  );
}

// The reduced-motion / no-WebGL fallback navigates the exact same topology at
// the same URLs: perspectives, levels, groups and pages as nested lists.
export function SceneFallback({
  layout,
  overlay,
  git,
  fallbackReason,
  selectedPageId,
  highlightedIds,
  census,
  makeHref,
  centerableIds,
  onNodeSelect,
  onGroupSelect,
  onStarDrill
}: {
  layout: WorldLayout;
  overlay: OverlayId;
  git: GitState;
  fallbackReason: SceneFallbackReason;
  selectedPageId: string;
  highlightedIds: Set<string>;
  census: SceneCensus;
  makeHref: (patch: ScenePatch) => string;
  centerableIds?: ReadonlySet<string>;
  onNodeSelect?: (nodeId: string) => void;
  onGroupSelect: (group: WorldGroup) => void;
  onStarDrill: (star: ClusterStar) => void;
}) {
  const strongAttention = strongAttentionNodeIds(layout.nodes);
  const fallbackNodes = layout.nodes.slice(0, 24);
  const fallbackNodeKeys = layoutNodeInstanceKeys(fallbackNodes);
  const currentCenterId = layout.nodes.find((node) => node.isRoot)?.id;
  return (
    <div className="sceneFallback" aria-label="Content map" data-fallback-reason={fallbackReason}>
      <div className="fallbackCore">
        <strong>{git.proposal.is_proposal_branch ? "Draft change" : "Approved content"}</strong>
        <span>{workspaceLabel(git)}</span>
      </div>
      {fallbackReason === "performance_budget" && (
        <aside className="performanceFallbackNotice" role="status">
          <strong>{t("scene.fallback.performance.title")}</strong>
          <span>{t("scene.fallback.performance.body")}</span>
        </aside>
      )}
      <FallbackPlanView
        layout={layout}
        overlay={overlay}
        selectedPageId={selectedPageId}
        highlightedIds={highlightedIds}
      />
      <div
        className="fallbackCensus overlayFallbackLegend"
        aria-label={t("scene.activeOverlayKeyAria")}
        data-testid="overlay-legend"
        data-overlay={overlay}
        data-overlay-token-version={SEMANTIC_VISUAL_TOKENS_VERSION}
      >
        {census.overlaySignals.map((entry) => (
          <span key={entry.state} data-overlay-state={entry.state} style={{ "--overlay-color": entry.color } as React.CSSProperties}>
            <i aria-hidden>{entry.symbol}</i>
            {localizedEncodingText(entry)} {entry.visibleCount}
          </span>
        ))}
        {census.hidden > 0 && <span>{t("scene.hiddenTotal", { hidden: census.hidden, total: census.total })}</span>}
      </div>
      <nav className="fallbackGroups" aria-label="Grupos deste nível">
        {layout.groups.map((group) => {
          // An empty facet lens is an honest absence, not a clickable group —
          // mirror the 3D rim pill ("no <facet> lens registered", non-interactive).
          if (group.kind === "facet" && group.count === 0) {
            return (
              <span key={group.key} className="fallbackGroupLink emptyFacet">
                {t("focus.emptyFacet", { facet: worldGroupLabel(group.kind, group.labelKey) })}
              </span>
            );
          }
          if (!group.drill && group.kind !== "quadrant") {
            return (
              <span
                key={group.key}
                className="fallbackGroupLink currentGroup"
                data-world-decorative="true"
                aria-hidden="true"
              >
                {worldGroupLabel(group.kind, group.labelKey)} · {group.count}
              </span>
            );
          }
          return (
            <a
              key={group.key}
              className={group.region ? "fallbackGroupLink fallbackRegionCard" : "fallbackGroupLink"}
              data-world-target-id={group.key}
              data-world-target-kind="group"
              href={
                group.drill
                  ? makeHref({ context: group.drill.context ?? null, group: group.drill.group ?? null, lens: group.drill.lens ?? null, pageId: null, reader: false })
                  : makeHref({})
              }
              onClick={(event) => {
                event.preventDefault();
                onGroupSelect(group);
              }}
              title={group.region ? resolvePrimitiveForSlot(null, group.region, "fallback.card").purpose : undefined}
            >
              {group.region ? (
                <>
                  <strong>{worldGroupLabel(group.kind, group.labelKey)}</strong>
                  <span>{group.shown < group.count ? `${group.shown}/${group.count}` : group.count}</span>
                  <small>
                    {(group.region.type_mix?.[0]?.family ?? t("region.mixed"))} · {group.region.summary.open_actions > 0 ? t("region.actions", { n: group.region.summary.open_actions }) : t("region.healthy")}
                  </small>
                  {group.region.attention_hints.length > 0 && (
                    <em>
                      {group.region.attention_hints.slice(0, 2).map((hint) => t(`region.attention.${hint.kind}`, { n: hint.count })).join(" · ")}
                    </em>
                  )}
                </>
              ) : (
                `${worldGroupLabel(group.kind, group.labelKey)} · ${group.shown < group.count ? `${group.shown}/${group.count}` : group.count}`
              )}
            </a>
          );
        })}
        {layout.clusterStars.map((star) =>
          star.drill ? (
            <a
              key={star.key}
              className="fallbackGroupLink starLink"
              href={makeHref({ context: star.drill.context ?? null, group: star.drill.group ?? null, pageId: null, reader: false })}
              onClick={(event) => {
                event.preventDefault();
                onStarDrill(star);
              }}
            >
              +{star.count} {t("scene.hidden")}
            </a>
          ) : (
            <button key={star.key} className="fallbackGroupLink starLink" onClick={() => onStarDrill(star)} type="button">
              +{star.count} {t("scene.hidden")} · {t("scene.showMore")}
            </button>
          )
        )}
      </nav>
      <div className="fallbackNodeGrid">
        {fallbackNodes.map((node, index) => {
          const encoding = visualEncodingResolver.resolve(node, overlay);
          const encodingText = localizedEncodingText(encoding);
          const encodingAria = localizedEncodingAria(encoding);
          const strong = overlay !== "attention" || strongAttention.has(node.id);
          // Region-scoped family nodes use an internal layout id so multiple
          // quadrants can own the same semantic family. The interactive 3D
          // label exposes the canonical drill id; the adaptive 2D surface must
          // expose that same id or a performance fallback silently breaks
          // keyboard/touch automation and deep-navigation semantics.
          const targetId = node.isGroup
            ? node.groupDrill?.group ?? node.groupKey ?? node.id
            : node.id;
          const recenters = !node.isGroup && node.id !== currentCenterId && Boolean(centerableIds?.has(node.id));
          const href = node.isGroup
            ? makeHref({ context: node.groupDrill?.context ?? null, group: node.groupDrill?.group ?? null, lens: node.groupDrill?.lens ?? null, pageId: null, reader: false })
            : recenters
              ? makeHref({ center: node.id, lens: "all", group: null, worldGroup: null, pageId: null, reader: false })
              : makeHref({ pageId: node.id, reader: true });
          return (
            <a
              className={`fallbackNode node-${node.freshness_state}${node.isGroup ? " groupNode" : ""}${node.id === selectedPageId || node.path === selectedPageId ? " active" : ""}${highlightedIds.has(node.id) || highlightedIds.has(node.path) ? " highlighted" : ""}`}
              key={`fallback-node-${fallbackNodeKeys[index]}`}
              data-world-target-id={targetId}
              data-world-target-kind={node.isGroup ? "group" : "page"}
              href={href}
              onClick={(event) => {
                event.preventDefault();
                onNodeSelect?.(node.id);
              }}
              style={{ borderColor: nodeDisplayColor(node, overlay), "--overlay-color": encoding.color } as React.CSSProperties}
              title={node.path}
              data-overlay={overlay}
              data-overlay-state={encoding.state}
              data-overlay-strong={strong ? "true" : "false"}
            >
              {node.visualGlyph && <span className="fallbackNodeGlyph" aria-hidden>{node.visualGlyph}</span>}
              <span className="fallbackNodeTitle">{node.title}</span>
              <small className={`fallbackNodeState ring-${strong ? encoding.ring : "none"}`} aria-label={encodingAria}>
                <b aria-hidden>{encoding.symbol}</b> {encodingText}
              </small>
            </a>
          );
        })}
      </div>
    </div>
  );
}
