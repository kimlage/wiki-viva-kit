// Minimap + 2D fallback: the same layout, the same URLs, zero motion.
// FallbackPlanView is the SVG plan (also the minimap disc inside the 3D
// shell); SceneFallback is the full reduced-motion / no-WebGL navigation
// surface — perspectives, levels, groups and pages as nested lists.

import { t } from "../../data/i18n";
import { trustColor, worldGroupLabel } from "../../data/presentation";
import type { GitState } from "../../types";
import type { ClusterStar, WorldGroup, WorldLayout } from "../perspectives";
import type { ScenePatch } from "../../components/SystemScene";
import { nodeDisplayColor, nodeTrustKey, workspaceLabel } from "./materials";
import type { SceneCensus } from "./hud";

export function FallbackPlanView({
  layout,
  selectedPageId,
  highlightedIds,
  onNodeSelect,
  onContextSelect
}: {
  layout: WorldLayout;
  selectedPageId: string;
  highlightedIds: Set<string>;
  onNodeSelect?: (nodeId: string) => void;
  onContextSelect?: (context: string) => void;
}) {
  const size = 420;
  const scale = size / 2 / (layout.rOuter + 1.2);
  const px = (value: number) => size / 2 + value * scale;
  const band = layout.rOuter - layout.rInner;
  const deadlineR = (layout.rInner + band * layout.deadlineF) * scale;
  return (
    <svg className="fallbackPlan" viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Content map plan view">
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
          style={{ cursor: onContextSelect ? "pointer" : undefined }}
          onClick={() => group.drill?.context && onContextSelect?.(group.drill.context)}
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
            onClick={() => star.drill?.context && onContextSelect?.(star.drill.context)}
            style={{ cursor: onContextSelect && star.drill?.context ? "pointer" : undefined }}
          />
          <text x={px(star.position[0])} y={px(star.position[2]) + 3} className="planContextLabel" textAnchor="middle">
            +{star.count}
          </text>
        </g>
      ))}
      {layout.nodes.map((node) => {
        const highlighted = highlightedIds.has(node.id) || highlightedIds.has(node.path);
        const selected = node.id === selectedPageId || node.path === selectedPageId;
        // At 2-4px, STATE wins the pixel: attention dots take the state accent
        // and a size bump; calm dots carry the context hue (aged). Premixing
        // hue+tone at this size reads as murk for everyone.
        const trust = nodeTrustKey(node);
        const attention = trust === "stale" || trust === "proposal";
        const fill = node.isRoot ? trustColor("root") : attention ? trustColor(trust) : nodeDisplayColor(node);
        return (
          <circle
            key={`plan-${node.id}`}
            cx={px(node.position[0])}
            cy={px(node.position[2])}
            r={Math.max(attention ? 4 : 3, node.scale * scale * (attention ? 2 : 1.6))}
            fill={fill}
            fillOpacity={trust === "fresh" && !selected && !highlighted ? 0.55 : trust === "unknown" ? 0.7 : 0.95}
            stroke={selected ? "#dff8ff" : highlighted ? "#8fd0e8" : node.risk_flags.length > 0 ? trustColor("risk") : "none"}
            strokeWidth={selected || highlighted ? 2 : 1.4}
            onClick={() => onNodeSelect?.(node.id)}
            style={{ cursor: onNodeSelect ? "pointer" : undefined }}
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
  git,
  selectedPageId,
  highlightedIds,
  census,
  makeHref,
  onNodeSelect,
  onGroupSelect,
  onStarDrill
}: {
  layout: WorldLayout;
  git: GitState;
  selectedPageId: string;
  highlightedIds: Set<string>;
  census: SceneCensus;
  makeHref: (patch: ScenePatch) => string;
  onNodeSelect?: (nodeId: string) => void;
  onGroupSelect: (group: WorldGroup) => void;
  onStarDrill: (star: ClusterStar) => void;
}) {
  return (
    <div className="sceneFallback" aria-label="Content map">
      <div className="fallbackCore">
        <strong>{git.proposal.is_proposal_branch ? "Draft change" : "Approved content"}</strong>
        <span>{workspaceLabel(git)}</span>
      </div>
      <FallbackPlanView
        layout={layout}
        selectedPageId={selectedPageId}
        highlightedIds={highlightedIds}
        onNodeSelect={onNodeSelect}
        onContextSelect={(context) => onGroupSelect({ key: context, kind: "context", labelKey: context, count: 0, shown: 0, anchor: [0, 0, 0], drill: { context }, memberIds: [] })}
      />
      <div className="fallbackCensus" aria-label="Content map counts">
        {census.trust.map((entry) => (
          <span key={entry.key}>
            <i style={{ background: entry.color }} />
            {entry.label} {entry.count}
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
          return (
            <a
              key={group.key}
              className="fallbackGroupLink"
              href={
                group.drill
                  ? makeHref({ context: group.drill.context ?? null, group: group.drill.group ?? null, pageId: null, reader: false })
                  : makeHref({})
              }
              onClick={(event) => {
                event.preventDefault();
                onGroupSelect(group);
              }}
            >
              {worldGroupLabel(group.kind, group.labelKey)} · {group.shown < group.count ? `${group.shown}/${group.count}` : group.count}
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
        {layout.nodes.slice(0, 24).map((node) => {
          const trust = nodeTrustKey(node);
          return (
            <a
              className={`fallbackNode node-${node.freshness_state}${node.id === selectedPageId || node.path === selectedPageId ? " active" : ""}${highlightedIds.has(node.id) || highlightedIds.has(node.path) ? " highlighted" : ""}`}
              key={`${node.id}-${node.path}`}
              href={makeHref({ pageId: node.id, reader: true })}
              onClick={(event) => {
                event.preventDefault();
                onNodeSelect?.(node.id);
              }}
              // Border = context identity; the state ALSO gets a text chip so
              // the fallback never encodes meaning in color alone (WCAG 1.4.1).
              style={{ borderColor: nodeDisplayColor(node) }}
              title={node.path}
            >
              {node.title}
              {trust !== "fresh" && <small className="fallbackNodeState">{t(`scene.trust.${trust}`)}</small>}
            </a>
          );
        })}
      </div>
    </div>
  );
}
