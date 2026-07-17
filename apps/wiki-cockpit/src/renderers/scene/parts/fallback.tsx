// Minimap + 2D fallback: the same layout, the same URLs, zero motion.
// FallbackPlanView is the SVG plan (also the minimap disc inside the 3D
// shell); SceneFallback is the full reduced-motion / no-WebGL navigation
// surface — perspectives, levels, groups and pages as nested lists.

import { t } from "../../../data/i18n";
import { edgeStyle, trustColor, worldGroupLabel } from "../../../data/presentation";
import { resolvePrimitiveForSlot } from "../../../data/visualPrimitives";
import { localizedEncodingAria, localizedEncodingText, SEMANTIC_VISUAL_TOKENS_VERSION, strongAttentionNodeIds, visualEncodingResolver } from "../../../data/visualEncoding";
import type { GitState, SourceFoundationPayload, SourceFoundationStream } from "../../../types";
import type { ClusterStar, SourceFlowBundle, SourceStreamPort, WorldGroup, WorldLayout } from "../../../scene/perspectives";
import type { LayoutNode } from "../../../scene/layout";
import { layoutNodeInstanceKeys } from "../../../scene/layout";
import type { ScenePatch } from "../../../components/SystemScene";
import { flowSeverityColor, gapMarkerSpecs, portAriaText, portBreachToken } from "./source-foundation";
import type { GapMarkerSpec } from "./source-foundation";
import { nodeDisplayColor, workspaceLabel } from "./materials";
import type { SceneFallbackReason } from "./materials";
import type { SceneCensus } from "./hud";
import type { OverlayId, WorldPlaneId } from "../../../world/contracts";

// ---------------------------------------------------------------------------
// Source-foundation fallback (plan §14): the 2D surface does not imitate the
// lower-hemisphere camera — it represents the SAME chain (source → provenance
// → knowledge → core) as four horizontal bands with connecting lines, and the
// list below carries the semantics (the SVG stays decorative/aria-hidden).

/** Top-to-bottom reading order of §14.1: the core is fed by knowledge targets,
 * which trace back through provenance to the sources at the foundation. */
export const FOUNDATION_PLAN_BAND_ORDER: WorldPlaneId[] = ["core", "knowledge", "provenance", "foundation"];

export type FoundationPlanBand = {
  plane: WorldPlaneId;
  labelKey: string;
  top: number;
  bottom: number;
  /** Honest node count of the band — visible nodes only; hidden counts travel
   * on the cluster stars, exactly like the 3D scene. */
  count: number;
};

export type FoundationPlanLink = {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  color: string;
  opacity: number;
};

export type FoundationPlanModel = {
  size: number;
  margin: number;
  bands: FoundationPlanBand[];
  points: Map<string, { x: number; y: number }>;
  links: FoundationPlanLink[];
  /** Deterministic band projection — world angle spreads horizontally, world
   * radius nudges vertically WITHIN the band, Y picks the band by structural
   * level. State never moves a node across bands here either (§10.12). */
  project: (position: [number, number, number]) => { x: number; y: number };
};

// Pure, deterministic view model for the band fallback. Null outside the
// foundation profile — the circular plan stays byte-identical for v8 layouts.
export function foundationPlanModel(layout: WorldLayout, size = 420): FoundationPlanModel | null {
  if (layout.planeProfile?.active !== "foundation") return null;
  const levels = layout.planeProfile.levels;
  const margin = 26;
  const innerWidth = size - margin * 2;
  const bandHeight = (size - margin * 2) / FOUNDATION_PLAN_BAND_ORDER.length;
  const bands: FoundationPlanBand[] = FOUNDATION_PLAN_BAND_ORDER.map((plane, index) => ({
    plane,
    labelKey: `source_foundation.band.${plane}`,
    top: margin + index * bandHeight,
    bottom: margin + (index + 1) * bandHeight,
    count: 0
  }));
  const bandIndexOf = (y: number): number => {
    let best = 0;
    FOUNDATION_PLAN_BAND_ORDER.forEach((plane, index) => {
      if (Math.abs(levels[plane] - y) < Math.abs(levels[FOUNDATION_PLAN_BAND_ORDER[best]] - y)) best = index;
    });
    return best;
  };
  const project = (position: [number, number, number]): { x: number; y: number } => {
    const band = bands[bandIndexOf(position[1])];
    const radius = Math.hypot(position[0], position[2]);
    const radiusNorm = Math.min(radius / Math.max(layout.rOuter, 1), 1);
    const angle = radius < 0.001 ? 0 : Math.atan2(position[2], position[0]);
    return {
      x: margin + ((angle + Math.PI) / (Math.PI * 2)) * innerWidth,
      y: band.top + bandHeight * (0.3 + radiusNorm * 0.55)
    };
  };
  const points = new Map<string, { x: number; y: number }>();
  const stationPoints = new Map<string, { x: number; y: number }>();
  layout.nodes.forEach((node) => {
    const point = project(node.position);
    points.set(node.id, point);
    const bandIndex = node.plane ? FOUNDATION_PLAN_BAND_ORDER.indexOf(node.plane) : bandIndexOf(node.position[1]);
    if (bandIndex >= 0) bands[bandIndex].count += 1;
    if (node.foundationRole === "source-station") stationPoints.set(node.id, point);
  });
  const links: FoundationPlanLink[] = [];
  // source → provenance: real ownership relations only (§14.2) — a page with
  // several owning sources keeps one line per owner, orphans get no line.
  const provenanceColor = edgeStyle("ingestion_chain").color;
  layout.nodes
    .filter((node) => node.foundationRole === "provenance-page")
    .forEach((node) => {
      const point = points.get(node.id);
      if (!point) return;
      (node.sourceIds ?? []).forEach((sourceId) => {
        const stationPoint = stationPoints.get(sourceId);
        if (stationPoint) {
          links.push({ x1: stationPoint.x, y1: stationPoint.y, x2: point.x, y2: point.y, color: provenanceColor, opacity: 0.3 });
        }
      });
    });
  // source → knowledge: one line per real emission bundle, keeping the same
  // closure-severity colors the 3D flow bundles use (§10.11).
  const bundleTargetIds = new Set<string>();
  (layout.foundationPrimitives ?? [])
    .filter((primitive): primitive is SourceFlowBundle => primitive.kind === "flow-bundle")
    .forEach((bundle) => {
      const from = bundle.sourceIds[0] ? stationPoints.get(bundle.sourceIds[0]) : undefined;
      const to = bundle.pageIds[0] ? points.get(bundle.pageIds[0]) : undefined;
      if (!from || !to) return;
      bundleTargetIds.add(bundle.pageIds[0]);
      links.push({ x1: from.x, y1: from.y, x2: to.x, y2: to.y, color: flowSeverityColor(bundle.severity), opacity: 0.45 });
    });
  // knowledge → core: the consolidation step of the §14.1 chain — only for
  // targets with at least one real emission, into the REAL center page.
  const coreNode = layout.nodes.find((node) => node.foundationRole === "core-anchor");
  const corePoint = coreNode ? points.get(coreNode.id) : undefined;
  if (corePoint) {
    bundleTargetIds.forEach((targetId) => {
      const point = points.get(targetId);
      if (point) links.push({ x1: point.x, y1: point.y, x2: corePoint.x, y2: corePoint.y, color: "#33505f", opacity: 0.3 });
    });
  }
  return { size, margin, bands, points, links, project };
}

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
  const model = foundationPlanModel(layout, size);
  const scale = size / 2 / (layout.rOuter + 1.2);
  const px = (value: number) => size / 2 + value * scale;
  const band = layout.rOuter - layout.rInner;
  const deadlineR = (layout.rInner + band * layout.deadlineF) * scale;
  const strongAttention = strongAttentionNodeIds(layout.nodes);
  const instanceKeys = layoutNodeInstanceKeys(layout.nodes);
  // One projection for every mark: band model in the foundation profile,
  // the classic top-down circular plan everywhere else.
  const pointOf = (position: [number, number, number]): { x: number; y: number } =>
    model ? model.project(position) : { x: px(position[0]), y: px(position[2]) };
  return (
    <svg
      className="fallbackPlan"
      viewBox={`0 0 ${size} ${size}`}
      aria-hidden="true"
      focusable="false"
      data-plane-profile={model ? "foundation" : "knowledge"}
    >
      {model ? (
        <>
          {/* §14.2: four horizontal bands replace the single circular map. */}
          {model.bands.map((bandRow) => (
            <g key={`band-${bandRow.plane}`}>
              <line
                x1={model.margin}
                y1={bandRow.bottom}
                x2={size - model.margin}
                y2={bandRow.bottom}
                stroke="#22303a"
                strokeOpacity="0.5"
              />
              <text x={model.margin} y={bandRow.top + 13} className="planContextLabel" textAnchor="start">
                {t(bandRow.labelKey)} · {bandRow.count}
              </text>
            </g>
          ))}
          {model.links.map((link, index) => (
            <line
              key={`chain-${index}`}
              x1={link.x1}
              y1={link.y1}
              x2={link.x2}
              y2={link.y2}
              stroke={link.color}
              strokeOpacity={link.opacity}
            />
          ))}
        </>
      ) : (
        <>
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
        </>
      )}
      {layout.clusterStars.map((star) => {
        const point = pointOf(star.position);
        return (
          <g key={`plan-star-${star.key}`}>
            <circle cx={point.x} cy={point.y} r={Math.max(5, star.scale * scale * 1.6)} fill="#334a5c" stroke="#6bd7ff" strokeWidth={1.4} />
            <text x={point.x} y={point.y + 3} className="planContextLabel" textAnchor="middle">
              +{star.count}
            </text>
          </g>
        );
      })}
      {layout.nodes.map((node, index) => {
        const highlighted = highlightedIds.has(node.id) || highlightedIds.has(node.path);
        const selected = node.id === selectedPageId || node.path === selectedPageId;
        const encoding = visualEncodingResolver.resolve(node, overlay);
        const attention = encoding.emissive >= 0.4;
        const strong = overlay !== "attention" || strongAttention.has(node.id);
        const point = pointOf(node.position);
        return (
          <circle
            key={`plan-${instanceKeys[index]}`}
            cx={point.x}
            cy={point.y}
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

// ---------------------------------------------------------------------------
// §14.3 navigable sections of the foundation fallback. Every control fires the
// SAME semantic event as its 3D counterpart: a source opens the SourceDock via
// the ordinary node-select path (§12.2), a stream fires the port-focus event
// (dock scope + ephemeral stream focus, §16.5), provenance/knowledge pages are
// ordinary selections, and a gap fires the gap-inspect event.

export const FOUNDATION_FALLBACK_SECTION_BUDGET = 16;

export type FoundationSection<T> = { items: T[]; hidden: number };

export type FoundationFallbackSections = {
  stations: FoundationSection<{ node: LayoutNode; aria: string }>;
  streams: FoundationSection<{ port: SourceStreamPort; aria: string }>;
  provenance: FoundationSection<{ node: LayoutNode; aria: string }>;
  targets: FoundationSection<{ node: LayoutNode; aria: string }>;
  gaps: FoundationSection<GapMarkerSpec>;
};

// A breached stream whose port fell over the per-station port budget (or whose
// station is over the node budget) still belongs in "streams needing
// attention": this stand-in carries the same identity the port-focus event
// needs (source + recipe stream id); position/bounds are inert in the 2D list.
function foundationStandInPort(stream: SourceFoundationStream): SourceStreamPort {
  return {
    kind: "stream-port",
    id: stream.stream_id,
    streamId: stream.stream_id,
    sourceIds: [stream.source_id],
    pageIds: [...stream.target_page_ids].sort(),
    position: [0, 0, 0],
    bounds: { radius: 0 },
    labelKey: "source_foundation.port.stream",
    severity: "warning",
    selected: stream.selected,
    breached: true,
    hiddenCount: 0
  };
}

// §14.5 screen-reader name of a stream: label; state; cadence; privacy;
// target pages. Falls back to the generic port ARIA when the payload is
// absent (older snapshots) — never invented facts.
export function foundationStreamAria(port: SourceStreamPort, stream?: SourceFoundationStream): string {
  if (!stream) return portAriaText(port);
  const parts = [t("source_foundation.fallback.stream.name", { label: stream.label })];
  if (stream.breached) {
    const overdueDays =
      stream.cursor_age_days !== null && stream.cursor_age_days > stream.cadence_days
        ? stream.cursor_age_days - stream.cadence_days
        : null;
    parts.push(
      overdueDays !== null
        ? t("source_foundation.fallback.stream.overdue", { n: overdueDays })
        : t("source_foundation.fallback.stream.breached")
    );
  } else if (stream.freshness_state === "never") {
    parts.push(t("source_foundation.fallback.stream.never"));
  } else {
    parts.push(t("source_foundation.fallback.stream.onTime"));
  }
  if (stream.cadence_days > 0) parts.push(t("source_foundation.fallback.stream.cadence", { n: stream.cadence_days }));
  if (stream.privacy) parts.push(t("source_foundation.fallback.stream.privacy", { privacy: stream.privacy }));
  parts.push(t("source_foundation.fallback.stream.targets", { n: stream.target_page_ids.length }));
  return parts.join("; ");
}

// Pure section model (unit-tested). Null outside the foundation profile.
// Facts come from the payload the layout itself was built from; when the
// payload is absent every claim that needs it is omitted, never guessed.
export function foundationFallbackSections(
  layout: WorldLayout,
  payload?: SourceFoundationPayload
): FoundationFallbackSections | null {
  if (layout.planeProfile?.active !== "foundation") return null;
  const stationByPage = new Map(
    (payload?.stations ?? [])
      .filter((station) => station.kind === "source")
      .map((station) => [station.canonical_page_id, station])
  );
  const streamsBySource = new Map<string, SourceFoundationStream[]>();
  (payload?.streams ?? []).forEach((stream) => {
    streamsBySource.set(stream.source_id, [...(streamsBySource.get(stream.source_id) ?? []), stream]);
  });
  const targetByPage = new Map((payload?.targets ?? []).map((target) => [target.page_id, target]));
  // Open provenance = event/proposal pages of emissions that are not closed
  // (closure accepted/reviewed_no_change is the closed vocabulary, §8/§9).
  const openProvenanceIds = new Set<string>();
  (payload?.emissions ?? []).forEach((emission) => {
    if (emission.closure_state === "accepted" || emission.closure_state === "reviewed_no_change") return;
    if (emission.event_page_id) openProvenanceIds.add(emission.event_page_id);
    emission.proposal_page_ids.forEach((proposalId) => openProvenanceIds.add(proposalId));
  });

  const cap = <T,>(items: T[], extraHidden = 0): FoundationSection<T> => ({
    items: items.slice(0, FOUNDATION_FALLBACK_SECTION_BUDGET),
    hidden: Math.max(items.length - FOUNDATION_FALLBACK_SECTION_BUDGET, 0) + extraHidden
  });

  // §14.5 station name: source; streams on time/overdue; recipe; pipeline
  // stage; emitted pages. Payload-absent snapshots keep the bare name.
  const stationAria = (node: LayoutNode): string => {
    const parts = [t("source_foundation.fallback.station.name", { label: node.title })];
    const station = stationByPage.get(node.id);
    if (station) {
      const streams = streamsBySource.get(node.id) ?? [];
      const breached = streams.filter((stream) => stream.breached).length;
      if (streams.length > 0) {
        parts.push(t("source_foundation.fallback.station.streams", { onTime: streams.length - breached, total: streams.length }));
        if (breached > 0) parts.push(t("source_foundation.fallback.station.breached", { n: breached }));
      }
      parts.push(t(`source_foundation.fallback.recipe.${station.recipe_state}`));
      if (station.pipeline_stage) parts.push(t("source_foundation.fallback.station.stage", { stage: station.pipeline_stage }));
      parts.push(t("source_foundation.fallback.station.emitted", { n: station.target_page_ids.length }));
    }
    return parts.join("; ");
  };

  const stationNodes = layout.nodes.filter((node) => node.foundationRole === "source-station");
  // Honest hidden count: the emitters cluster star carries stations over the
  // node budget (station priority is a layout invariant, §19.4).
  const hiddenStations = layout.clusterStars
    .filter((star) => star.key === "foundation-star-emitters")
    .reduce((sum, star) => sum + star.count, 0);

  const ports = (layout.foundationPrimitives ?? []).filter(
    (primitive): primitive is SourceStreamPort => primitive.kind === "stream-port"
  );
  const portByStreamId = new Map(
    ports.filter((port) => port.streamId !== null).map((port) => [port.streamId as string, port])
  );
  const attentionStreams = payload
    ? payload.streams
        .filter((stream) => stream.breached)
        .sort((a, b) => a.label.localeCompare(b.label) || a.stream_id.localeCompare(b.stream_id))
        .map((stream) => {
          const port = portByStreamId.get(stream.stream_id) ?? foundationStandInPort(stream);
          return { port, aria: foundationStreamAria(port, stream) };
        })
    : ports.filter((port) => port.breached).map((port) => ({ port, aria: portAriaText(port) }));

  const openProvenance = layout.nodes
    .filter((node) => node.foundationRole === "provenance-page" && openProvenanceIds.has(node.id))
    .map((node) => ({
      node,
      aria: [
        node.title,
        t("source_foundation.fallback.provenance.open"),
        ...(node.sourceIds && node.sourceIds.length > 0
          ? [t("source_foundation.fallback.provenance.sources", { n: node.sourceIds.length })]
          : [])
      ].join("; ")
    }));

  const targetNodes = layout.nodes.filter((node) => node.foundationRole === "knowledge-page");
  const targets = (payload ? targetNodes.filter((node) => targetByPage.has(node.id)) : targetNodes.filter((node) => !node.faint)).map(
    (node) => {
      const target = targetByPage.get(node.id);
      return {
        node,
        aria: target
          ? [
              t("source_foundation.fallback.target.name", { label: node.title }),
              t("source_foundation.fallback.target.sources", { n: target.source_ids.length }),
              t(`source_foundation.fallback.closure.${target.closure_state}`)
            ].join("; ")
          : t("source_foundation.fallback.target.name", { label: node.title })
      };
    }
  );

  return {
    stations: cap(stationNodes.map((node) => ({ node, aria: stationAria(node) })), hiddenStations),
    streams: cap(attentionStreams),
    provenance: cap(openProvenance),
    targets: cap(targets),
    gaps: cap(gapMarkerSpecs(layout))
  };
}

function FoundationSectionHeading({ labelKey, section }: { labelKey: string; section: FoundationSection<unknown> }) {
  return (
    <h3>
      {t(labelKey)} · {section.items.length}
      {section.hidden > 0 && <span className="fallbackFoundationMore"> {t("source_foundation.fallback.more", { n: section.hidden })}</span>}
    </h3>
  );
}

// §14.7: no state is color-only here — every entry carries symbol AND text
// AND count, and the full sentence lives in the accessible name.
function FoundationFallbackNav({
  layout,
  sourceFoundation,
  makeHref,
  onNodeSelect,
  onPortFocus,
  onGapInspect
}: {
  layout: WorldLayout;
  sourceFoundation?: SourceFoundationPayload;
  makeHref: (patch: ScenePatch) => string;
  onNodeSelect?: (nodeId: string) => void;
  onPortFocus?: (port: SourceStreamPort) => void;
  onGapInspect?: (marker: GapMarkerSpec) => void;
}) {
  const sections = foundationFallbackSections(layout, sourceFoundation);
  if (!sections) return null;
  const breachToken = portBreachToken();
  const pageEntry = (
    entry: { node: LayoutNode; aria: string },
    href: string,
    extra?: React.ReactNode
  ) => (
    <li key={`foundation-${entry.node.id}`}>
      <a
        className="fallbackFoundationLink"
        data-world-target-id={entry.node.id}
        data-world-target-kind="page"
        href={href}
        aria-label={entry.aria}
        onClick={(event) => {
          event.preventDefault();
          onNodeSelect?.(entry.node.id);
        }}
      >
        <span aria-hidden="true" className="fallbackFoundationTitle">{entry.node.title}</span>
        {extra}
      </a>
    </li>
  );
  return (
    <nav className="fallbackFoundation" aria-label={t("source_foundation.fallback.sections")} data-plane-profile="foundation">
      <section className="fallbackFoundationSection" data-section="sources">
        <FoundationSectionHeading labelKey="source_foundation.fallback.sources" section={sections.stations} />
        {sections.stations.items.length === 0 ? (
          <span className="fallbackFoundationEmpty">{t("source_foundation.fallback.none")}</span>
        ) : (
          <ul>
            {sections.stations.items.map((entry) =>
              pageEntry(
                entry,
                makeHref({ pageId: entry.node.id, dock: "source", src: entry.node.id }),
                <small aria-hidden="true">{entry.aria.slice(entry.aria.indexOf(";") + 1).trim()}</small>
              )
            )}
          </ul>
        )}
      </section>
      <section className="fallbackFoundationSection" data-section="streams">
        <FoundationSectionHeading labelKey="source_foundation.fallback.streamsAttention" section={sections.streams} />
        {sections.streams.items.length === 0 ? (
          <span className="fallbackFoundationEmpty">{t("source_foundation.fallback.none")}</span>
        ) : (
          <ul>
            {sections.streams.items.map((entry) => (
              <li key={`foundation-stream-${entry.port.id}`}>
                <button
                  type="button"
                  className="fallbackFoundationLink"
                  aria-label={entry.aria}
                  onClick={() => onPortFocus?.(entry.port)}
                >
                  <b aria-hidden="true" className="fallbackFoundationSymbol" style={{ color: breachToken.color }}>
                    {breachToken.symbol}
                  </b>
                  <span aria-hidden="true">{entry.aria}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="fallbackFoundationSection" data-section="provenance">
        <FoundationSectionHeading labelKey="source_foundation.fallback.openProvenance" section={sections.provenance} />
        {sections.provenance.items.length === 0 ? (
          <span className="fallbackFoundationEmpty">{t("source_foundation.fallback.none")}</span>
        ) : (
          <ul>
            {sections.provenance.items.map((entry) =>
              pageEntry(
                entry,
                makeHref({ pageId: entry.node.id, reader: true }),
                <small aria-hidden="true">{t("source_foundation.fallback.provenance.open")}</small>
              )
            )}
          </ul>
        )}
      </section>
      <section className="fallbackFoundationSection" data-section="targets">
        <FoundationSectionHeading labelKey="source_foundation.fallback.knowledgeTargets" section={sections.targets} />
        {sections.targets.items.length === 0 ? (
          <span className="fallbackFoundationEmpty">{t("source_foundation.fallback.none")}</span>
        ) : (
          <ul>
            {sections.targets.items.map((entry) =>
              pageEntry(
                entry,
                makeHref({ pageId: entry.node.id, reader: true }),
                <small aria-hidden="true">{entry.aria.slice(entry.aria.indexOf(";") + 1).trim()}</small>
              )
            )}
          </ul>
        )}
      </section>
      <section className="fallbackFoundationSection" data-section="gaps">
        <FoundationSectionHeading labelKey="source_foundation.fallback.gaps" section={sections.gaps} />
        {sections.gaps.items.length === 0 ? (
          <span className="fallbackFoundationEmpty">{t("source_foundation.fallback.none")}</span>
        ) : (
          <ul>
            {sections.gaps.items.map((gap) => (
              <li key={`foundation-gap-${gap.id}`}>
                <button
                  type="button"
                  className="fallbackFoundationLink"
                  aria-label={gap.aria}
                  onClick={() => onGapInspect?.(gap)}
                >
                  <b aria-hidden="true" className="fallbackFoundationSymbol" style={{ color: gap.color }}>
                    {gap.symbol}
                  </b>
                  <span aria-hidden="true">{gap.text}</span>
                  {gap.count > 1 && <small aria-hidden="true">×{gap.count}</small>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </nav>
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
  sourceFoundation,
  onNodeSelect,
  onGroupSelect,
  onStarDrill,
  onPortFocus,
  onGapInspect
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
  // §14.3: the payload the foundation layout was built from — the navigable
  // sections read stream/recipe/closure facts from it (absent = old snapshot,
  // the sections degrade to layout-only facts).
  sourceFoundation?: SourceFoundationPayload;
  onNodeSelect?: (nodeId: string) => void;
  onGroupSelect: (group: WorldGroup) => void;
  onStarDrill: (star: ClusterStar) => void;
  // §14.3: the same semantic events the 3D scene fires for derived controls.
  onPortFocus?: (port: SourceStreamPort) => void;
  onGapInspect?: (marker: GapMarkerSpec) => void;
}) {
  const strongAttention = strongAttentionNodeIds(layout.nodes);
  const fallbackNodes = layout.nodes.slice(0, 24);
  const fallbackNodeKeys = layoutNodeInstanceKeys(fallbackNodes);
  const currentCenterId = layout.nodes.find((node) => node.isRoot)?.id;
  return (
    <div className="sceneFallback" aria-label={t("scene.fallback.aria")} data-fallback-reason={fallbackReason}>
      <div className="fallbackCore">
        <strong>{git.proposal.is_proposal_branch ? t("scene.fallback.draft") : t("scene.fallback.approved")}</strong>
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
      <FoundationFallbackNav
        layout={layout}
        sourceFoundation={sourceFoundation}
        makeHref={makeHref}
        onNodeSelect={onNodeSelect}
        onPortFocus={onPortFocus}
        onGapInspect={onGapInspect}
      />
      <nav className="fallbackGroups" aria-label={t("scene.fallback.groups")}>
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
