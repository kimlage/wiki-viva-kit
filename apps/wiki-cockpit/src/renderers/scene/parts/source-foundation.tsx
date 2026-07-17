// Source-foundation renderer (plan §10, §16.4–16.7): the visual layer of the
// vertical foundation profile. Everything here derives from the RESOLVED
// layout — stations/pages are ordinary LayoutNodes rendered by NodeInstances;
// this part renders the DERIVED primitives (instanced stream ports, pipeline
// lanes, vertical provenance conduits, emission flow bundles, typed gap
// markers, governance plates) plus the per-band plane guides that replace the
// upper profile's ground guides (§10.12).
//
// Contracts honored here:
// - §10.9 labels are drei Html → always billboard/camera-facing, never
//   mirrored in the lower hemisphere; the safe area/label CSS stays sovereign.
// - §10.10 occlusion: band opacity policy via FOUNDATION_BAND_OPACITY; depth
//   test stays TRUE for geometry (only depthWrite is disabled on additive
//   transparents, the repo-wide convention); selection raises contrast, never
//   position.
// - §10.11 encoding reuses the existing overlay token vocabulary through the
//   visual encoding resolver: stream breach = freshness `stale` token, recipe
//   validity = `quality` tokens + ARIA text, closure = evidence/actions
//   tokens. No new ring/dash/pulse semantics are introduced.
// - §16.5 picking: ports are derived controls with an accessible DOM twin and
//   never enter PageEntityIndex (a port activation patches the SourceDock,
//   not the page selection); lanes are inspection-only; conduits and flow
//   bundles carry no pointer handlers so they never capture the pointer.
// - §16.7 particles: this part adds NO particle system. Flow direction is
//   carried by static arrowheads derived from the real emission direction
//   (reduced-motion safe) plus the textual member count; the existing
//   SceneParticles layer keeps serving real graph edges under its own budget,
//   so nothing here can suggest a running sync for historical status.
// - Frameloop demand-safe: no useFrame loop invalidates by itself; the only
//   per-frame work is the shared morph fade (same pattern as EdgeArcs), which
//   runs while the morph transaction is already invalidating.

import { Html } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from "react";
import type { RefObject } from "react";
import * as THREE from "three";
import { t } from "../../../data/i18n";
import { edgeStyle, trustColor } from "../../../data/presentation";
import { SEMANTIC_VISUAL_TOKENS } from "../../../data/visualEncoding";
import type { SemanticVisualToken } from "../../../data/visualEncoding";
import type { LayoutNode } from "../../../scene/layout";
import type {
  SourceFlowBundle,
  SourceFoundationPrimitive,
  SourceGapMarker,
  SourceGovernancePlate,
  SourcePipelineLane,
  SourceStreamPort,
  WorldLayout
} from "../../../scene/perspectives";
import { SOURCE_FOUNDATION_WITHIN_BAND_LIFT } from "../../../world/contracts";
import type { WorldPlaneId } from "../../../world/contracts";
import type { SourceTraceMode } from "../../../world/sourceSignals";
import { morphAttachmentOpacity } from "./nodes";
import type { MorphState } from "./nodes";

// ---------------------------------------------------------------------------
// Pure specs (unit-tested; no three.js state)

/** True only for the resolved foundation profile — every renderer below and
 * the SystemScene composition key off this, so other views mount ZERO meshes. */
export function isFoundationProfile(layout: WorldLayout): boolean {
  return layout.planeProfile?.active === "foundation";
}

// §20 density counters over the DERIVED foundation scene. Stations are the
// mounted source-station page nodes; every other counter measures derived
// primitives directly (plan §20 rule 10 — telemetry must not stop at source
// GraphNodes). The aggregated "+N" overflow port counts as ONE port while its
// hiddenCount stays visible in-scene, and grouped emissions already arrive as
// one flow bundle carrying its count — aggregation never inflates these
// counters and port pressure never hides a station (ports/conduits are
// budgeted separately from stations in FOUNDATION_DENSITY_BUDGETS).
export function foundationDensityCounters(layout: WorldLayout): {
  sourceStations: number;
  sourceStreamPorts: number;
  sourcePipelineLanes: number;
  sourceFlowSegments: number;
  sourceGapMarkers: number;
} {
  if (!isFoundationProfile(layout)) {
    return { sourceStations: 0, sourceStreamPorts: 0, sourcePipelineLanes: 0, sourceFlowSegments: 0, sourceGapMarkers: 0 };
  }
  const primitives = layout.foundationPrimitives ?? [];
  const byKind = (kind: SourceFoundationPrimitive["kind"]): number =>
    primitives.filter((primitive) => primitive.kind === kind).length;
  return {
    sourceStations: layout.nodes.filter((node) => node.foundationRole === "source-station").length,
    sourceStreamPorts: byKind("stream-port"),
    sourcePipelineLanes: byKind("pipeline-lane"),
    sourceFlowSegments: byKind("flow-bundle"),
    sourceGapMarkers: byKind("gap-marker")
  };
}

// §10.10 opacity policy per band. Foundation stays fully present, provenance
// reads at 0.75–0.9, knowledge recedes to 0.35–0.65 until selected, the core
// stays legible without covering stations.
export const FOUNDATION_BAND_OPACITY: Record<WorldPlaneId, { base: number; selected: number }> = {
  foundation: { base: 1, selected: 1 },
  provenance: { base: 0.82, selected: 0.9 },
  knowledge: { base: 0.5, selected: 0.9 },
  core: { base: 0.88, selected: 1 }
};

export function foundationBandOpacity(plane: WorldPlaneId | undefined, selected = false): number {
  const policy = FOUNDATION_BAND_OPACITY[plane ?? "knowledge"];
  return selected ? policy.selected : policy.base;
}

export type FoundationBandGuide = {
  plane: WorldPlaneId;
  y: number;
  radius: number;
  labelKey: string;
  opacity: number;
  /** Honest band aggregate ("305 páginas alimentadas" style): the TRUE total
   * of the band's population from the layout census — never the visible
   * slice. Null when the band has no countable population (core) or the
   * census group is absent (stations-only drill without groups). */
  countText: string | null;
};

const BAND_CENSUS_GROUP: Partial<Record<WorldPlaneId, string>> = {
  foundation: "source-emitters",
  provenance: "provenance",
  knowledge: "emitted"
};

const BAND_COUNT_KEY: Partial<Record<WorldPlaneId, string>> = {
  foundation: "source_foundation.band.count.foundation",
  provenance: "source_foundation.band.count.provenance",
  knowledge: "source_foundation.band.count.knowledge"
};

const BAND_ROLE: Partial<Record<WorldPlaneId, string>> = {
  foundation: "source-station",
  provenance: "provenance-page",
  knowledge: "knowledge-page"
};

/** TRUE band population, by order of authority: the payload census the layout
 * carries (foundationCensus — counts members that are hidden, aggregated at
 * rest, or entirely outside an anchor-scoped graph slice), then the census
 * group's full count, then the mounted role nodes (bare layouts carrying
 * neither). The pill must never read the visible slice: layout groups count
 * only the pages that survived graph scoping, which is exactly how a
 * 50-source world once claimed "0 fontes". */
export function foundationBandCount(layout: WorldLayout, plane: WorldPlaneId): number | null {
  if (plane === "core") return null;
  const census = layout.foundationCensus;
  if (census) return census[plane];
  const groupKey = BAND_CENSUS_GROUP[plane];
  if (!groupKey) return null;
  const group = layout.groups.find((candidate) => candidate.key === groupKey);
  if (group) return group.count;
  const role = BAND_ROLE[plane];
  const mounted = layout.nodes.filter((node) => node.foundationRole === role).length;
  return mounted > 0 ? mounted : null;
}

// One quiet ring per band at the band's EXACT structural level (§10.12: the
// profile owns its plane guides; radii follow the layout so the visual
// spacing control flows through). R1: every band carries a STRONG name plus
// its honest aggregate count — the 5-second read of the world.
export function foundationPlaneGuides(layout: WorldLayout): FoundationBandGuide[] {
  if (!isFoundationProfile(layout) || !layout.planeProfile) return [];
  const levels = layout.planeProfile.levels;
  const countText = (plane: WorldPlaneId): string | null => {
    const key = BAND_COUNT_KEY[plane];
    const count = foundationBandCount(layout, plane);
    return key && count !== null ? t(key, { n: count }) : null;
  };
  return [
    { plane: "foundation", y: levels.foundation, radius: layout.rOuter * 0.66, labelKey: "source_foundation.band.foundation", opacity: 0.3, countText: countText("foundation") },
    { plane: "provenance", y: levels.provenance, radius: layout.rOuter * 0.82, labelKey: "source_foundation.band.provenance", opacity: 0.22, countText: countText("provenance") },
    { plane: "knowledge", y: levels.knowledge, radius: layout.rOuter * 0.9, labelKey: "source_foundation.band.knowledge", opacity: 0.16, countText: countText("knowledge") },
    { plane: "core", y: levels.core, radius: Math.max(layout.rInner * 1.1, 1.1), labelKey: "source_foundation.band.core", opacity: 0.2, countText: null }
  ];
}

// --- R1 progressive disclosure ----------------------------------------------
// The calm entry contract: at rest the world is core anchor + labeled bands +
// stations. Stream ports and pipeline lanes mount ONLY for a focused station
// (selected, hovered or the active trace subject); knowledge/provenance pages
// rest as heavily dimmed aggregates and individualize on focus.

export function foundationFocusStationIds(
  layout: WorldLayout,
  selectedId: string,
  hoveredId = "",
  trace: TraceHighlight | null = null
): Set<string> {
  const ids = new Set<string>();
  if (!isFoundationProfile(layout)) return ids;
  const stations = new Set(
    layout.nodes.filter((node) => node.foundationRole === "source-station").flatMap((node) => [node.id, node.path])
  );
  [selectedId, hoveredId, trace?.subjectId ?? ""].forEach((id) => {
    if (id && stations.has(id)) ids.add(id);
  });
  return ids;
}

/** True when the node rests as part of a dimmed aggregate: knowledge and
 * provenance pages recede until selection/hover/trace (or their owning
 * station's focus) individualizes them. Never hides — presence only. */
export function foundationRestDim(
  node: Pick<LayoutNode, "id" | "path" | "foundationRole" | "sourceIds">,
  context: { selectedId?: string; hoveredId?: string; highlightedIds?: ReadonlySet<string> }
): boolean {
  if (node.foundationRole !== "knowledge-page" && node.foundationRole !== "provenance-page") return false;
  const selectedId = context.selectedId ?? "";
  const hoveredId = context.hoveredId ?? "";
  const highlighted = context.highlightedIds;
  if (selectedId && (node.id === selectedId || node.path === selectedId)) return false;
  if (hoveredId && (node.id === hoveredId || node.path === hoveredId)) return false;
  if (highlighted && (highlighted.has(node.id) || highlighted.has(node.path))) return false;
  const owners = node.sourceIds ?? [];
  if (selectedId && owners.includes(selectedId)) return false;
  if (hoveredId && owners.includes(hoveredId)) return false;
  return true;
}

export type PortRenderGroups = {
  solid: SourceStreamPort[];
  outline: SourceStreamPort[];
  overflow: SourceStreamPort[];
  breached: SourceStreamPort[];
};

// §10.4: selected streams solid, unselected outline, the aggregated "+N" port
// carries the TRUE hidden count, breach is an overlay symbol (never position).
// R1: when a focus set is given, only ports of focused stations mount — the
// resting world shows stations, not their port crowns.
export function portRenderGroups(layout: WorldLayout, focus?: ReadonlySet<string> | null): PortRenderGroups {
  const allPorts = (layout.foundationPrimitives ?? []).filter(
    (primitive): primitive is SourceStreamPort => primitive.kind === "stream-port"
  );
  const ports = focus ? allPorts.filter((port) => port.sourceIds.some((id) => focus.has(id))) : allPorts;
  return {
    solid: ports.filter((port) => port.streamId !== null && port.selected),
    outline: ports.filter((port) => port.streamId !== null && !port.selected),
    overflow: ports.filter((port) => port.streamId === null),
    breached: ports.filter((port) => port.breached)
  };
}

// A port is a derived control (§16.5): activating it focuses the source's
// stream table in the SourceDock. It NEVER patches pageId — derived ids must
// not enter the page selection/PageEntityIndex.
export function portFocusPatch(port: SourceStreamPort): { dock: "source"; src: string | null } {
  return { dock: "source", src: port.sourceIds[0] ?? null };
}

// Breach reuses the existing freshness `stale` overlay token (§10.11) — same
// color, same symbol the rest of the world already uses for "past deadline".
export function portBreachToken(): SemanticVisualToken {
  return SEMANTIC_VISUAL_TOKENS.freshness.states.stale;
}

export function portAriaText(port: SourceStreamPort): string {
  if (port.streamId === null) return t("source_foundation.port.hiddenAria", { n: port.hiddenCount });
  const parts = [t(port.labelKey)];
  parts.push(t(port.selected ? "source_foundation.port.selectedState" : "source_foundation.port.unselectedState"));
  if (port.breached) parts.push(t("source_foundation.port.breachedState"));
  return parts.join(" — ");
}

// §12.2: activating a source station dispatches the EXISTING openSource
// grammar (dock=source&src=<id>) plus a normal page selection for visual focus
// and trace emphasis. It never touches `center`, so no recenter can happen
// implicitly. Every other foundation role returns null and keeps the normal
// selection contract (§12.4/§12.5: provenance/knowledge pages are ordinary
// selections; recenter stays an explicit action).
export function stationSelectPatch(
  node: Pick<LayoutNode, "id" | "foundationRole">
): { pageId: string; dock: "source"; src: string } | null {
  return node.foundationRole === "source-station" ? { pageId: node.id, dock: "source", src: node.id } : null;
}

export type TraceHighlight = { mode: SourceTraceMode; subjectId: string };

// §12.6 trace modes as SELECTION-DRIVEN highlights over relations the layout
// already resolved — never a new view, never movement:
// - upstream: page → its emission bundles → owning source stations;
// - downstream: source → its provenance/knowledge pages via bundles + node
//   ownership (LayoutNode.sourceIds keeps many-to-many countable);
// - closure: source → targets whose every emission is accepted (bundle
//   severity "none" is the layout's closed-closure encoding).
export function traceHighlightIds(layout: WorldLayout, trace: TraceHighlight | null): Set<string> {
  const ids = new Set<string>();
  if (!trace || !trace.subjectId || !isFoundationProfile(layout)) return ids;
  const bundles = (layout.foundationPrimitives ?? []).filter(
    (primitive): primitive is SourceFlowBundle => primitive.kind === "flow-bundle"
  );
  const addBundle = (bundle: SourceFlowBundle) => {
    ids.add(bundle.id);
    bundle.sourceIds.forEach((id) => ids.add(id));
    bundle.pageIds.forEach((id) => ids.add(id));
  };
  if (trace.mode === "upstream") {
    bundles.filter((bundle) => bundle.pageIds.includes(trace.subjectId)).forEach(addBundle);
    const subject = layout.nodes.find((node) => node.id === trace.subjectId);
    (subject?.sourceIds ?? []).forEach((id) => ids.add(id));
    if (ids.size > 0) ids.add(trace.subjectId);
    return ids;
  }
  const closureOnly = trace.mode === "closure";
  bundles
    .filter((bundle) => bundle.sourceIds.includes(trace.subjectId) && (!closureOnly || bundle.severity === "none"))
    .forEach(addBundle);
  if (!closureOnly) {
    layout.nodes
      .filter(
        (node) =>
          (node.foundationRole === "provenance-page" || node.foundationRole === "knowledge-page") &&
          (node.sourceIds ?? []).includes(trace.subjectId)
      )
      .forEach((node) => ids.add(node.id));
  }
  ids.add(trace.subjectId);
  return ids;
}

export type SourceStateEmphasis = {
  /** Stations (and real pages named by diagnostics) needing operator attention. */
  attentionIds: Set<string>;
  /** Derived primitives that recede while the lens is active. */
  dimmedPrimitiveIds: Set<string>;
};

const LENS_DIM_FACTOR = 0.3;

function primitiveNeedsAttention(primitive: SourceFoundationPrimitive): boolean {
  if (primitive.kind === "stream-port") return primitive.breached;
  if (primitive.kind === "pipeline-lane") return primitive.severity === "error";
  if (primitive.kind === "gap-marker") return primitive.severity === "warning" || primitive.severity === "error";
  if (primitive.kind === "governance-plate") return primitive.severity !== "none";
  return primitive.severity === "warning" || primitive.severity === "error";
}

// §12.7: lens=source_state filters/emphasizes state WITHOUT moving anything.
// Geometry is untouched — attention states (breached/pending streams, failed
// lanes, invalid recipes, warning/error gaps, blocked flows) come forward and
// nominal primitives recede in presence only. No object ever changes band.
export function sourceStateEmphasis(layout: WorldLayout, lens: string | undefined): SourceStateEmphasis | null {
  if (lens !== "source_state" || !isFoundationProfile(layout)) return null;
  const primitives = layout.foundationPrimitives ?? [];
  const attentionIds = new Set<string>();
  primitives.forEach((primitive) => {
    if (!primitiveNeedsAttention(primitive)) return;
    primitive.sourceIds.forEach((id) => attentionIds.add(id));
    if (primitive.canonicalEntityId) attentionIds.add(primitive.canonicalEntityId);
  });
  const dimmedPrimitiveIds = new Set<string>();
  primitives.forEach((primitive) => {
    const related =
      primitive.sourceIds.some((id) => attentionIds.has(id)) ||
      (primitive.canonicalEntityId ? attentionIds.has(primitive.canonicalEntityId) : false);
    if (!primitiveNeedsAttention(primitive) && !related) dimmedPrimitiveIds.add(primitive.id);
  });
  return { attentionIds, dimmedPrimitiveIds };
}

export function foundationDimFactor(id: string, emphasis: SourceStateEmphasis | null): number {
  return emphasis?.dimmedPrimitiveIds.has(id) ? LENS_DIM_FACTOR : 1;
}

// Deterministic ingestion stage order (wiki_source_lifecycle.v2 vocabulary):
// the stage marker sits at this fraction of the lane arc. Unknown stages hide
// the marker instead of faking progress.
export const PIPELINE_STAGE_ORDER = [
  "configured",
  "manifested",
  "extracted",
  "indexed",
  "deep_read",
  "proposal_ready",
  "integrating",
  "gate_pending",
  "complete"
] as const;

export function pipelineStageFraction(stage: string): number | null {
  const index = (PIPELINE_STAGE_ORDER as readonly string[]).indexOf(stage);
  return index < 0 ? null : index / (PIPELINE_STAGE_ORDER.length - 1);
}

// Structural kind → symbol (§10.11 "Tipo estrutural → forma/símbolo"); the
// ARIA text keeps content and deep_read verbally distinguishable (§10.5).
export const PIPELINE_KIND_SYMBOLS: Record<string, string> = {
  content: "≣",
  deep_read: "◎"
};

export type LaneRenderSpec = {
  id: string;
  laneKind: string;
  stage: string;
  center: [number, number, number];
  radius: number;
  tickCount: number;
  stageFraction: number | null;
  symbol: string;
  color: string;
  severity: SourcePipelineLane["severity"];
  label: string;
  aria: string;
  sourceIds: string[];
};

// R1: lanes follow the same focus contract as ports — no focus set means the
// unfiltered census (tests/telemetry), a set means only focused stations mount.
export function laneRenderSpecs(layout: WorldLayout, focus?: ReadonlySet<string> | null): LaneRenderSpec[] {
  const allLanes = (layout.foundationPrimitives ?? []).filter(
    (primitive): primitive is SourcePipelineLane => primitive.kind === "pipeline-lane"
  );
  const lanes = focus ? allLanes.filter((lane) => lane.sourceIds.some((id) => focus.has(id))) : allLanes;
  return lanes.map((lane) => {
    const label = t(lane.labelKey);
    return {
      id: lane.id,
      laneKind: lane.laneKind,
      stage: lane.stage,
      center: lane.position,
      radius: lane.radius,
      tickCount: lane.tickCount,
      stageFraction: pipelineStageFraction(lane.stage),
      symbol: PIPELINE_KIND_SYMBOLS[lane.laneKind] ?? "•",
      color:
        lane.severity === "error"
          ? SEMANTIC_VISUAL_TOKENS.quality.states.flagged.color
          : edgeStyle("ingestion_chain").color,
      severity: lane.severity,
      label,
      aria: `${label} — ${t("source_foundation.lane.stage", { stage: lane.stage || "?", ticks: lane.tickCount })}`,
      sourceIds: lane.sourceIds
    };
  });
}

export type ConduitSpec = {
  id: string;
  stationId: string;
  base: [number, number, number];
  top: [number, number, number];
  members: { id: string; position: [number, number, number] }[];
  bundledCount: number;
  memberCount: number;
};

export const CONDUIT_SPLIT_BUDGET = 8;

// §10.6 provenance towers: a thin vertical trunk per source station up to the
// provenance band, splitting only where relations really diverge. A page with
// several owning sources appears under EVERY owner (many-to-many stays
// renderable and countable, §10.7); beyond the split budget the remaining
// members are bundled with their honest count. Orphan provenance pages have
// no trunk — a conduit is never invented.
export function conduitSpecs(layout: WorldLayout): ConduitSpec[] {
  if (!isFoundationProfile(layout) || !layout.planeProfile) return [];
  const provenanceY = layout.planeProfile.levels.provenance;
  const stations = layout.nodes.filter((node) => node.foundationRole === "source-station");
  const provenance = layout.nodes.filter((node) => node.foundationRole === "provenance-page");
  return stations
    .map((station) => {
      const members = provenance
        .filter((node) => (node.sourceIds ?? []).includes(station.id))
        .map((node) => ({ id: node.id, position: node.position }))
        .sort((a, b) => a.id.localeCompare(b.id));
      const split = members.slice(0, CONDUIT_SPLIT_BUDGET);
      return {
        id: `conduit:${station.id}`,
        stationId: station.id,
        base: station.position,
        top: [station.position[0], provenanceY - 0.15, station.position[2]] as [number, number, number],
        members: split,
        bundledCount: members.length - split.length,
        memberCount: members.length
      };
    })
    .filter((conduit) => conduit.memberCount > 0);
}

// Closure severity → existing token colors (§10.11: evidence/closure stays in
// the evidence/actions overlay vocabulary; nothing new is minted here).
export function flowSeverityColor(severity: SourceFlowBundle["severity"]): string {
  if (severity === "warning" || severity === "error") return SEMANTIC_VISUAL_TOKENS.actions.states.blocked.color;
  if (severity === "info") return SEMANTIC_VISUAL_TOKENS.evidence.states.unknown.color;
  return SEMANTIC_VISUAL_TOKENS.evidence.states.linked.color;
}

export type FlowBundleSpec = {
  id: string;
  from: [number, number, number];
  to: [number, number, number];
  control: [number, number, number];
  color: string;
  opacity: number;
  traceCount: number;
  arrowAt: [number, number, number];
  arrowToward: [number, number, number];
  countLabelAt: [number, number, number] | null;
  pageIds: string[];
  sourceIds: string[];
};

function bezierPoint(
  from: [number, number, number],
  control: [number, number, number],
  to: [number, number, number],
  s: number
): [number, number, number] {
  const u = 1 - s;
  return [
    u * u * from[0] + 2 * u * s * control[0] + s * s * to[0],
    u * u * from[1] + 2 * u * s * control[1] + s * s * to[1],
    u * u * from[2] + 2 * u * s * control[2] + s * s * to[2]
  ];
}

// §10.6/§10.7: one bundle per real (source, target) relation — a two-source
// page keeps two tethers. The control point pushes the midpoint radially
// OUTWARD from the world axis so the curve clears the dense station core, and
// the arrowhead is placed near the target end: direction is derived from the
// real emission direction, never from animation. Trace highlights (§12.6) and
// the source_state lens (§12.7) only modulate presence — from/to/control stay
// byte-identical, nothing moves.
export function flowBundleSpecs(
  layout: WorldLayout,
  selectedId = "",
  emphasis: { traceIds?: Set<string>; dimmedIds?: Set<string> } = {}
): FlowBundleSpec[] {
  const bundles = (layout.foundationPrimitives ?? []).filter(
    (primitive): primitive is SourceFlowBundle => primitive.kind === "flow-bundle"
  );
  return bundles.map((bundle) => {
    const mid: [number, number, number] = [
      (bundle.from[0] + bundle.to[0]) / 2,
      (bundle.from[1] + bundle.to[1]) / 2,
      (bundle.from[2] + bundle.to[2]) / 2
    ];
    const radial = Math.hypot(mid[0], mid[2]);
    const push = 0.5 + Math.min(bundle.traceCount * 0.06, 0.4);
    const scale = radial < 0.001 ? 0 : (radial + push) / radial;
    const control: [number, number, number] =
      radial < 0.001 ? [push, mid[1], 0] : [mid[0] * scale, mid[1], mid[2] * scale];
    const selected =
      (Boolean(selectedId) && (bundle.pageIds.includes(selectedId) || bundle.sourceIds.includes(selectedId))) ||
      Boolean(emphasis.traceIds?.has(bundle.id));
    const dim = !selected && emphasis.dimmedIds?.has(bundle.id) ? LENS_DIM_FACTOR : 1;
    return {
      id: bundle.id,
      from: bundle.from,
      to: bundle.to,
      control,
      color: flowSeverityColor(bundle.severity),
      opacity:
        (selected
          ? foundationBandOpacity("knowledge", true) * 0.62
          : foundationBandOpacity("knowledge") * 0.62) * dim,
      traceCount: bundle.traceCount,
      arrowAt: bezierPoint(bundle.from, control, bundle.to, 0.82),
      arrowToward: bezierPoint(bundle.from, control, bundle.to, 0.94),
      countLabelAt: bundle.traceCount > 1 ? bezierPoint(bundle.from, control, bundle.to, 0.5) : null,
      pageIds: bundle.pageIds,
      sourceIds: bundle.sourceIds
    };
  });
}

// R1 calm entry: individual emission curves mount only when something focuses
// them — the selected/hovered page or station, an active trace, or the
// source_state lens (which keeps its attention subjects). At rest the
// knowledge band's honest aggregate label carries the count instead of a
// serrated tangle of unlabeled curves. Presence only: specs are filtered,
// never moved.
export function visibleFlowBundleSpecs(
  specs: FlowBundleSpec[],
  context: {
    selectedId?: string;
    hoveredId?: string;
    traceIds?: ReadonlySet<string>;
    emphasis?: SourceStateEmphasis | null;
  }
): FlowBundleSpec[] {
  const selectedId = context.selectedId ?? "";
  const hoveredId = context.hoveredId ?? "";
  return specs.filter((spec) => {
    if (context.traceIds?.has(spec.id)) return true;
    const focuses = (id: string) => Boolean(id) && (spec.pageIds.includes(id) || spec.sourceIds.includes(id));
    if (focuses(selectedId) || focuses(hoveredId)) return true;
    if (context.emphasis) return !context.emphasis.dimmedPrimitiveIds.has(spec.id);
    return false;
  });
}

// Typed gap severity reuses the quality overlay tokens; informational entries
// use the quiet attention token (gray, honest "no alarm" mark).
export function gapSeverityToken(severity: SourceGapMarker["severity"]): SemanticVisualToken {
  if (severity === "error") return SEMANTIC_VISUAL_TOKENS.quality.states.flagged;
  if (severity === "warning") return SEMANTIC_VISUAL_TOKENS.quality.states.warning;
  return SEMANTIC_VISUAL_TOKENS.attention.states.quiet;
}

export type GapMarkerSpec = {
  id: string;
  code: string;
  position: [number, number, number];
  color: string;
  symbol: string;
  count: number;
  text: string;
  aria: string;
  canonicalEntityId?: string;
  sourceId: string | null;
};

export function gapMarkerSpecs(layout: WorldLayout): GapMarkerSpec[] {
  const markers = (layout.foundationPrimitives ?? []).filter(
    (primitive): primitive is SourceGapMarker => primitive.kind === "gap-marker"
  );
  const stationIds = new Set(
    layout.nodes.filter((node) => node.foundationRole === "source-station").map((node) => node.id)
  );
  return markers.map((marker) => {
    const token = gapSeverityToken(marker.severity);
    const text = t(marker.labelKey);
    return {
      id: marker.id,
      code: marker.code,
      position: marker.position,
      color: token.color,
      symbol: token.symbol,
      count: marker.count,
      text,
      aria: `${text} — ${t("source_foundation.gap.count", { n: marker.count })}`,
      ...(marker.canonicalEntityId ? { canonicalEntityId: marker.canonicalEntityId } : {}),
      sourceId:
        marker.canonicalEntityId && stationIds.has(marker.canonicalEntityId)
          ? marker.canonicalEntityId
          : marker.sourceIds.find((id) => stationIds.has(id)) ?? null
    };
  });
}

// --- R2: gap markers → per-station badges + bounded world markers + panel ---
// The flood of one marker per diagnostic is replaced by (a) one severity badge
// per affected station carrying the TRUE per-station occurrence total, (b) at
// most WORLD_GAP_MARKER_BUDGET world markers — the single worst diagnostic of
// the worst stations — and (c) the complete aggregated census exposed to the
// HUD via sourceGapSummary. Nothing is dropped silently: every diagnostic is
// counted in a badge, a summary group, or both.

export const WORLD_GAP_MARKER_BUDGET = 12;

const GAP_SEVERITY_RANK: Record<SourceGapMarker["severity"], number> = {
  error: 3,
  warning: 2,
  info: 1,
  none: 0
};

function gapSeverityRank(severity: SourceGapMarker["severity"]): number {
  return GAP_SEVERITY_RANK[severity] ?? 0;
}

type SeveritySpec = GapMarkerSpec & { severity: SourceGapMarker["severity"] };

function compareGapSpecs(a: SeveritySpec, b: SeveritySpec): number {
  return (
    gapSeverityRank(b.severity) - gapSeverityRank(a.severity) ||
    b.count - a.count ||
    a.id.localeCompare(b.id)
  );
}

export type StationGapBadge = {
  stationId: string;
  stationTitle: string;
  position: [number, number, number];
  severity: SourceGapMarker["severity"];
  /** TRUE sum of occurrence counts across every diagnostic on this station. */
  total: number;
  markerCount: number;
  aria: string;
  /** The station's single worst diagnostic — the badge's activation subject
   * and the candidate for the bounded world-marker budget. */
  topMarker: SeveritySpec;
};

function gapSpecsWithSeverity(layout: WorldLayout): SeveritySpec[] {
  const markers = (layout.foundationPrimitives ?? []).filter(
    (primitive): primitive is SourceGapMarker => primitive.kind === "gap-marker"
  );
  const severityById = new Map(markers.map((marker) => [marker.id, marker.severity]));
  return gapMarkerSpecs(layout).map((spec) => ({ ...spec, severity: severityById.get(spec.id) ?? "info" }));
}

export function stationGapBadges(layout: WorldLayout): StationGapBadge[] {
  if (!isFoundationProfile(layout)) return [];
  const stations = new Map(
    layout.nodes.filter((node) => node.foundationRole === "source-station").map((node) => [node.id, node])
  );
  const byStation = new Map<string, SeveritySpec[]>();
  gapSpecsWithSeverity(layout).forEach((spec) => {
    if (!spec.sourceId || !stations.has(spec.sourceId)) return;
    byStation.set(spec.sourceId, [...(byStation.get(spec.sourceId) ?? []), spec]);
  });
  return [...byStation.entries()]
    .map(([stationId, specs]) => {
      const sorted = [...specs].sort(compareGapSpecs);
      const top = sorted[0];
      const station = stations.get(stationId)!;
      const total = specs.reduce((sum, spec) => sum + spec.count, 0);
      return {
        stationId,
        stationTitle: station.title,
        position: [
          station.position[0],
          Number((station.position[1] + Math.max(station.scale, 0.2) + 0.18).toFixed(4)),
          station.position[2]
        ] as [number, number, number],
        severity: top.severity,
        total,
        markerCount: specs.length,
        aria: t("source_foundation.gaps.stationBadge", { label: station.title, n: total }),
        topMarker: top
      };
    })
    .sort(
      (a, b) =>
        gapSeverityRank(b.severity) - gapSeverityRank(a.severity) ||
        b.total - a.total ||
        a.stationId.localeCompare(b.stationId)
    );
}

/** The bounded in-world marker set: the single worst diagnostic of the worst
 * stations, repositioned above their station. Everything else stays counted
 * in badges and the HUD summary. */
export function worldGapMarkers(layout: WorldLayout): GapMarkerSpec[] {
  return stationGapBadges(layout)
    .slice(0, WORLD_GAP_MARKER_BUDGET)
    .map((badge) => ({
      ...badge.topMarker,
      position: [badge.position[0], Number((badge.position[1] + 0.18).toFixed(4)), badge.position[2]] as [
        number,
        number,
        number
      ]
    }));
}

export type SourceGapGroup = {
  code: string;
  severity: SourceGapMarker["severity"];
  label: string;
  /** Number of diagnostics carrying this code. */
  markerCount: number;
  /** TRUE sum of occurrence counts across those diagnostics. */
  occurrenceCount: number;
  markers: SeveritySpec[];
};

export type SourceGapSummary = {
  /** TRUE total of occurrences across every diagnostic — the HUD chip number. */
  total: number;
  markerTotal: number;
  worldMarkerCount: number;
  stationCount: number;
  groups: SourceGapGroup[];
};

// The complete aggregated census for the HUD panel: grouped by diagnostic
// code, sorted by severity then occurrence count. Sum of group occurrence
// counts always equals `total` — the honesty invariant the tests enforce.
export function sourceGapSummary(layout: WorldLayout): SourceGapSummary {
  const specs = gapSpecsWithSeverity(layout);
  const byCode = new Map<string, SeveritySpec[]>();
  specs.forEach((spec) => byCode.set(spec.code, [...(byCode.get(spec.code) ?? []), spec]));
  const groups: SourceGapGroup[] = [...byCode.entries()]
    .map(([code, members]) => {
      const sorted = [...members].sort(compareGapSpecs);
      return {
        code,
        severity: sorted[0].severity,
        label: sorted[0].text,
        markerCount: members.length,
        occurrenceCount: members.reduce((sum, spec) => sum + spec.count, 0),
        markers: sorted
      };
    })
    .sort(
      (a, b) =>
        gapSeverityRank(b.severity) - gapSeverityRank(a.severity) ||
        b.occurrenceCount - a.occurrenceCount ||
        a.code.localeCompare(b.code)
    );
  const badges = stationGapBadges(layout);
  return {
    total: specs.reduce((sum, spec) => sum + spec.count, 0),
    markerTotal: specs.length,
    worldMarkerCount: Math.min(badges.length, WORLD_GAP_MARKER_BUDGET),
    stationCount: badges.length,
    groups
  };
}

export type GovernancePlateSpec = {
  id: string;
  position: [number, number, number];
  color: string;
  symbol: string;
  aria: string;
  canonicalEntityId: string | null;
  severity: SourceGovernancePlate["severity"];
};

// Recipe validity goes through the `quality` overlay tokens + ARIA text
// (§10.11) — never a new ring/rim channel.
export function governancePlateSpecs(layout: WorldLayout): GovernancePlateSpec[] {
  const plates = (layout.foundationPrimitives ?? []).filter(
    (primitive): primitive is SourceGovernancePlate => primitive.kind === "governance-plate"
  );
  return plates.map((plate) => {
    const token =
      plate.severity === "none"
        ? SEMANTIC_VISUAL_TOKENS.quality.states.clear
        : SEMANTIC_VISUAL_TOKENS.quality.states.warning;
    return {
      id: plate.id,
      position: plate.position,
      color: token.color,
      symbol: token.symbol,
      aria: `${t(plate.labelKey)} — ${t(`overlay.state.quality.${plate.severity === "none" ? "clear" : "warning"}`)}`,
      canonicalEntityId: plate.canonicalEntityId ?? null,
      severity: plate.severity
    };
  });
}

export type FoundationProposalStem = {
  id: string;
  from: [number, number, number];
  to: [number, number, number];
};

// §10.12: the proposal float is re-expressed WITHIN the node's band; the stem
// anchors at the band level (never the world ground), so no decorative line
// can cross two bands.
export function foundationProposalStems(layout: WorldLayout): FoundationProposalStem[] {
  if (!isFoundationProfile(layout) || !layout.planeProfile) return [];
  const levels = layout.planeProfile.levels;
  return layout.nodes
    .filter((node) => node.approved_state === "proposal" && node.plane && node.plane !== "core")
    .map((node) => {
      const bandY = levels[node.plane!];
      const boundedY =
        bandY +
        Math.max(
          Math.min(node.position[1] - bandY, SOURCE_FOUNDATION_WITHIN_BAND_LIFT),
          -SOURCE_FOUNDATION_WITHIN_BAND_LIFT
        );
      return {
        id: node.id,
        from: [node.position[0], bandY, node.position[2]] as [number, number, number],
        to: [node.position[0], boundedY, node.position[2]] as [number, number, number]
      };
    })
    .filter((stem) => Math.abs(stem.to[1] - stem.from[1]) > 0.01);
}

// ---------------------------------------------------------------------------
// Render helpers (three.js state; every layer follows the EdgeArcs morph-fade
// pattern so primitives enter/exit by opacity, §16.6)

const CONDUIT_COLOR = edgeStyle("ingestion_chain").color;
const PORT_COLOR = edgeStyle("source_ref").color;

// R3: every interactive scene object flips the canvas cursor on hover so
// pickable things read as pickable. The canvas element is shared, so the
// helpers are idempotent.
function useSceneCursor(): { over: () => void; out: () => void } {
  const { gl } = useThree();
  return useMemo(
    () => ({
      over: () => {
        gl.domElement.style.cursor = "pointer";
      },
      out: () => {
        gl.domElement.style.cursor = "";
      }
    }),
    [gl]
  );
}

function FadingLineSegments({
  segments,
  colors,
  color,
  baseOpacity,
  morph,
  renderOrder
}: {
  segments: number[];
  colors?: number[];
  color?: string;
  baseOpacity: number;
  morph: RefObject<MorphState>;
  renderOrder: number;
}) {
  const { invalidate } = useThree();
  const object = useMemo(() => {
    if (segments.length === 0) return null;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(segments), 3));
    if (colors) geometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(colors), 3));
    const material = new THREE.LineBasicMaterial({
      ...(colors ? { vertexColors: true } : { color }),
      transparent: true,
      opacity: morph.current?.active ? 0 : baseOpacity,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      toneMapped: false
    });
    const lines = new THREE.LineSegments(geometry, material);
    lines.renderOrder = renderOrder;
    return { lines, geometry, material };
  }, [baseOpacity, color, colors, morph, renderOrder, segments]);
  useFrame((state) => {
    if (!object) return;
    object.material.opacity = morphAttachmentOpacity(morph.current, state.clock.elapsedTime, baseOpacity);
  });
  useEffect(() => {
    invalidate();
    return () => {
      object?.geometry.dispose();
      object?.material.dispose();
    };
  }, [invalidate, object]);
  return object ? <primitive object={object.lines} /> : null;
}

function circleSegments(center: [number, number, number], radius: number, out: number[], segments = 48): void {
  for (let index = 0; index < segments; index += 1) {
    const a0 = (index / segments) * Math.PI * 2;
    const a1 = ((index + 1) / segments) * Math.PI * 2;
    out.push(
      center[0] + Math.cos(a0) * radius,
      center[1],
      center[2] + Math.sin(a0) * radius,
      center[0] + Math.cos(a1) * radius,
      center[1],
      center[2] + Math.sin(a1) * radius
    );
  }
}

function FoundationBandGuides({
  layout,
  morph,
  framedBand = null,
  onBandFrame
}: {
  layout: WorldLayout;
  morph: RefObject<MorphState>;
  // R4: the currently framed band (aria-pressed) and the frame dispatch.
  framedBand?: WorldPlaneId | null;
  onBandFrame?: (plane: WorldPlaneId) => void;
}) {
  const guides = useMemo(() => foundationPlaneGuides(layout), [layout]);
  const segments = useMemo(() => {
    const out: number[] = [];
    guides.forEach((guide) => circleSegments([0, guide.y, 0], guide.radius, out, 72));
    return out;
  }, [guides]);
  if (guides.length === 0) return null;
  return (
    <group>
      <FadingLineSegments segments={segments} color="#22303a" baseOpacity={0.55} morph={morph} renderOrder={1} />
      {/* R1: STRONG band names + honest aggregate counts — the 5-second read.
          R4: the pill is first-class navigation — activating it frames that
          band with the registered camera pose (never free flight). */}
      {guides.map((guide) => (
        <Html
          key={guide.plane}
          position={[guide.radius * 0.72, guide.y + 0.06, guide.radius * 0.6]}
          center
          distanceFactor={6.4}
          wrapperClass="sceneHtmlLabel"
          className="foundationBandLabel"
          zIndexRange={[18, 0]}
        >
          <button
            type="button"
            data-band-pill={guide.plane}
            aria-pressed={framedBand === guide.plane}
            aria-label={t("source_foundation.band.frameAria", { label: t(guide.labelKey) })}
            title={t("source_foundation.band.frameAria", { label: t(guide.labelKey) })}
            onClick={() => onBandFrame?.(guide.plane)}
          >
            <strong>{t(guide.labelKey)}</strong>
            {guide.countText && <small>{guide.countText}</small>}
          </button>
        </Html>
      ))}
    </group>
  );
}

function FoundationConduits({
  layout,
  morph,
  focusIds
}: {
  layout: WorldLayout;
  morph: RefObject<MorphState>;
  focusIds: ReadonlySet<string>;
}) {
  const conduits = useMemo(() => conduitSpecs(layout), [layout]);
  const buildSegments = useCallback((members: ConduitSpec[]): number[] => {
    const out: number[] = [];
    members.forEach((conduit) => {
      out.push(...conduit.base, ...conduit.top);
      conduit.members.forEach((member) => {
        // One-bend split from the trunk top toward the member: relations
        // diverge above the trunk, and the elbow stays clear of neighbor
        // stations because it starts on the station's own vertical.
        const elbow: [number, number, number] = [
          conduit.top[0] + (member.position[0] - conduit.top[0]) * 0.35,
          member.position[1] - 0.08,
          conduit.top[2] + (member.position[2] - conduit.top[2]) * 0.35
        ];
        out.push(...conduit.top, ...elbow, ...elbow, ...member.position);
      });
    });
    return out;
  }, []);
  // R1: at rest the towers read as a quiet aggregate; a focused station's
  // trunk comes forward with its member splits at full presence.
  const focusedSegments = useMemo(
    () => buildSegments(conduits.filter((conduit) => focusIds.has(conduit.stationId))),
    [buildSegments, conduits, focusIds]
  );
  const restSegments = useMemo(
    () => buildSegments(conduits.filter((conduit) => !focusIds.has(conduit.stationId))),
    [buildSegments, conduits, focusIds]
  );
  const bundleBadges = useMemo(
    () => conduits.filter((conduit) => conduit.bundledCount > 0 && focusIds.has(conduit.stationId)),
    [conduits, focusIds]
  );
  if (conduits.length === 0) return null;
  const restOpacity = foundationBandOpacity("provenance") * 0.16;
  const focusOpacity = foundationBandOpacity("provenance", true) * 0.6;
  return (
    <group>
      <FadingLineSegments segments={restSegments} color={CONDUIT_COLOR} baseOpacity={restOpacity} morph={morph} renderOrder={2} />
      {focusedSegments.length > 0 && (
        <FadingLineSegments segments={focusedSegments} color={CONDUIT_COLOR} baseOpacity={focusOpacity} morph={morph} renderOrder={2} />
      )}
      {bundleBadges.map((conduit) => (
        <Html
          key={conduit.id}
          position={[conduit.top[0], conduit.top[1] + 0.14, conduit.top[2]]}
          center
          distanceFactor={5.2}
          wrapperClass="sceneHtmlLabel"
          className="clusterStarLabel"
          zIndexRange={[22, 0]}
        >
          <span title={t("source_foundation.conduit.bundle", { n: conduit.bundledCount })}>+{conduit.bundledCount}</span>
        </Html>
      ))}
    </group>
  );
}

const FLOW_ARROW_BUDGET: Record<string, number> = { rich: 160, balanced: 110, compact: 60 };
const FLOW_COUNT_LABEL_BUDGET = 24;

function FoundationFlowBundles({
  layout,
  selectedId,
  hoveredId,
  quality,
  morph,
  traceIds,
  emphasis
}: {
  layout: WorldLayout;
  selectedId: string;
  hoveredId: string;
  quality: string;
  morph: RefObject<MorphState>;
  traceIds: Set<string>;
  emphasis: SourceStateEmphasis | null;
}) {
  // R1: only focused/traced/attention bundles mount — the resting knowledge
  // band speaks through its labeled aggregate count instead.
  const specs = useMemo(
    () =>
      visibleFlowBundleSpecs(
        flowBundleSpecs(layout, selectedId, { traceIds, dimmedIds: emphasis?.dimmedPrimitiveIds }),
        { selectedId, hoveredId, traceIds, emphasis }
      ),
    [emphasis, hoveredId, layout, selectedId, traceIds]
  );
  const { segments, colors } = useMemo(() => {
    const positions: number[] = [];
    const vertexColors: number[] = [];
    const color = new THREE.Color();
    const steps = quality === "compact" ? 6 : 12;
    specs.forEach((spec) => {
      color.set(spec.color).multiplyScalar(Math.min(spec.opacity / 0.62, 1));
      for (let index = 0; index < steps; index += 1) {
        const a = bezierPoint(spec.from, spec.control, spec.to, index / steps);
        const b = bezierPoint(spec.from, spec.control, spec.to, (index + 1) / steps);
        positions.push(...a, ...b);
        vertexColors.push(color.r, color.g, color.b, color.r, color.g, color.b);
      }
    });
    return { segments: positions, colors: vertexColors };
  }, [quality, specs]);
  const arrowBudget = FLOW_ARROW_BUDGET[quality] ?? FLOW_ARROW_BUDGET.balanced;
  const arrows = useMemo(() => specs.slice(0, arrowBudget), [arrowBudget, specs]);
  const countLabels = useMemo(
    () =>
      specs
        .filter((spec) => spec.countLabelAt !== null)
        .sort((a, b) => b.traceCount - a.traceCount || a.id.localeCompare(b.id))
        .slice(0, FLOW_COUNT_LABEL_BUDGET),
    [specs]
  );
  if (specs.length === 0) return null;
  return (
    <group>
      <FadingLineSegments segments={segments} colors={colors} baseOpacity={0.9} morph={morph} renderOrder={3} />
      {arrows.map((spec) => (
        <FlowArrow key={spec.id} spec={spec} morph={morph} />
      ))}
      {countLabels.map((spec) => (
        <Html
          key={`count-${spec.id}`}
          position={spec.countLabelAt!}
          center
          distanceFactor={5.6}
          wrapperClass="sceneHtmlLabel"
          className="clusterStarLabel"
          zIndexRange={[20, 0]}
        >
          <span title={t("source_foundation.flow.count", { n: spec.traceCount })}>×{spec.traceCount}</span>
        </Html>
      ))}
    </group>
  );
}

function FlowArrow({ spec, morph }: { spec: FlowBundleSpec; morph: RefObject<MorphState> }) {
  const materialRef = useRef<THREE.MeshBasicMaterial | null>(null);
  const quaternion = useMemo(() => {
    const direction = new THREE.Vector3(
      spec.arrowToward[0] - spec.arrowAt[0],
      spec.arrowToward[1] - spec.arrowAt[1],
      spec.arrowToward[2] - spec.arrowAt[2]
    );
    if (direction.lengthSq() < 1e-8) direction.set(0, 1, 0);
    direction.normalize();
    return new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction);
  }, [spec.arrowAt, spec.arrowToward]);
  useFrame((state) => {
    if (!materialRef.current) return;
    materialRef.current.opacity = morphAttachmentOpacity(morph.current, state.clock.elapsedTime, spec.opacity);
  });
  return (
    <mesh position={spec.arrowAt} quaternion={quaternion} renderOrder={3}>
      <coneGeometry args={[0.045, 0.13, 6]} />
      <meshBasicMaterial
        ref={materialRef}
        color={spec.color}
        transparent
        opacity={spec.opacity}
        blending={THREE.AdditiveBlending}
        depthWrite={false}
        toneMapped={false}
      />
    </mesh>
  );
}

function FoundationProposalStemsLayer({ layout, morph }: { layout: WorldLayout; morph: RefObject<MorphState> }) {
  const stems = useMemo(() => foundationProposalStems(layout), [layout]);
  const segments = useMemo(() => stems.flatMap((stem) => [...stem.from, ...stem.to]), [stems]);
  if (stems.length === 0) return null;
  return (
    <FadingLineSegments
      segments={segments}
      color={trustColor("proposal")}
      baseOpacity={0.5}
      morph={morph}
      renderOrder={2}
    />
  );
}

type PortInstancedLayerProps = {
  ports: SourceStreamPort[];
  wireframe: boolean;
  morph: RefObject<MorphState>;
  // §12.7 lens dim — presence only; instance matrices (positions) are shared
  // with the bright layer and never change.
  opacityScale?: number;
};

function PortInstancedLayer({ ports, wireframe, morph, opacityScale = 1 }: PortInstancedLayerProps) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const materialRef = useRef<THREE.MeshStandardMaterial | null>(null);
  const { invalidate } = useThree();
  const matrix = useMemo(() => new THREE.Matrix4(), []);
  const quaternionIdentity = useMemo(() => new THREE.Quaternion(), []);
  const position = useMemo(() => new THREE.Vector3(), []);
  const scale = useMemo(() => new THREE.Vector3(), []);
  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    ports.forEach((port, index) => {
      position.set(...port.position);
      const radius = port.bounds.radius;
      matrix.compose(position, quaternionIdentity, scale.set(radius, radius, radius));
      mesh.setMatrixAt(index, matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    invalidate();
  }, [invalidate, matrix, ports, position, quaternionIdentity, scale]);
  const baseOpacity = (wireframe ? 0.85 : 1) * opacityScale;
  useFrame((state) => {
    if (!materialRef.current) return;
    materialRef.current.opacity = morphAttachmentOpacity(morph.current, state.clock.elapsedTime, baseOpacity);
  });
  if (ports.length === 0) return null;
  return (
    <instancedMesh ref={ref} args={[undefined, undefined, ports.length]} frustumCulled={false} renderOrder={5}>
      <cylinderGeometry args={[1, 1, 0.55, 10]} />
      <meshStandardMaterial
        ref={materialRef}
        color={PORT_COLOR}
        emissive={PORT_COLOR}
        emissiveIntensity={wireframe ? 0.12 : 0.34}
        transparent
        opacity={baseOpacity}
        wireframe={wireframe}
        flatShading
        toneMapped={false}
      />
    </instancedMesh>
  );
}

function FoundationStreamPorts({
  layout,
  morph,
  emphasis,
  focusIds,
  onPortFocus
}: {
  layout: WorldLayout;
  morph: RefObject<MorphState>;
  emphasis: SourceStateEmphasis | null;
  // R1: ports mount only for focused stations.
  focusIds: ReadonlySet<string>;
  onPortFocus: (port: SourceStreamPort) => void;
}) {
  const cursor = useSceneCursor();
  const groups = useMemo(() => portRenderGroups(layout, focusIds), [focusIds, layout]);
  // §12.7 lens: nominal ports recede by presence only — their instance
  // transforms are identical to the bright layers, so nothing moves.
  const splitByDim = useCallback(
    (ports: SourceStreamPort[]): { bright: SourceStreamPort[]; dim: SourceStreamPort[] } => {
      if (!emphasis) return { bright: ports, dim: [] };
      return {
        bright: ports.filter((port) => !emphasis.dimmedPrimitiveIds.has(port.id)),
        dim: ports.filter((port) => emphasis.dimmedPrimitiveIds.has(port.id))
      };
    },
    [emphasis]
  );
  const solidSplit = useMemo(() => splitByDim(groups.solid), [groups.solid, splitByDim]);
  const outlineSplit = useMemo(() => splitByDim(groups.outline), [groups.outline, splitByDim]);
  const allPorts = useMemo(
    () => [...groups.solid, ...groups.outline, ...groups.overflow],
    [groups.outline, groups.overflow, groups.solid]
  );
  const hitRef = useRef<THREE.InstancedMesh>(null);
  const { invalidate } = useThree();
  const matrix = useMemo(() => new THREE.Matrix4(), []);
  const quaternionIdentity = useMemo(() => new THREE.Quaternion(), []);
  const position = useMemo(() => new THREE.Vector3(), []);
  const scale = useMemo(() => new THREE.Vector3(), []);
  useLayoutEffect(() => {
    const mesh = hitRef.current;
    if (!mesh) return;
    allPorts.forEach((port, index) => {
      position.set(...port.position);
      const hit = Math.max(port.bounds.radius * 2.1, 0.2);
      matrix.compose(position, quaternionIdentity, scale.set(hit, hit, hit));
      mesh.setMatrixAt(index, matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    invalidate();
  }, [allPorts, invalidate, matrix, position, quaternionIdentity, scale]);
  const breachToken = portBreachToken();
  if (allPorts.length === 0) return null;
  return (
    <group>
      <PortInstancedLayer ports={solidSplit.bright} wireframe={false} morph={morph} />
      <PortInstancedLayer ports={outlineSplit.bright} wireframe morph={morph} />
      {solidSplit.dim.length > 0 && (
        <PortInstancedLayer ports={solidSplit.dim} wireframe={false} morph={morph} opacityScale={0.3} />
      )}
      {outlineSplit.dim.length > 0 && (
        <PortInstancedLayer ports={outlineSplit.dim} wireframe morph={morph} opacityScale={0.3} />
      )}
      {/* Breach = overlay symbol from the existing freshness token, never a
          different position (§10.4). aria-hidden: the accessible twin speaks. */}
      {groups.breached.map((port) => (
        <Html
          key={`breach-${port.id}`}
          position={[port.position[0], port.position[1] + 0.14, port.position[2]]}
          center
          distanceFactor={4.6}
          wrapperClass="sceneHtmlLabel"
          className="radarDeadlineCaption"
          zIndexRange={[24, 0]}
        >
          <span aria-hidden style={{ color: breachToken.color }}>{breachToken.symbol}</span>
        </Html>
      ))}
      {/* The aggregated "+N" port shows its TRUE hidden count. */}
      {groups.overflow.map((port) => (
        <Html
          key={`overflow-${port.id}`}
          position={[port.position[0], port.position[1] + 0.16, port.position[2]]}
          center
          distanceFactor={4.8}
          wrapperClass="sceneHtmlLabel"
          className="clusterStarLabel"
          zIndexRange={[24, 0]}
        >
          <button type="button" onClick={() => onPortFocus(port)} title={t("source_foundation.port.hiddenAria", { n: port.hiddenCount })}>
            <strong>+{port.hiddenCount}</strong>
          </button>
        </Html>
      ))}
      <instancedMesh
        ref={hitRef}
        args={[undefined, undefined, allPorts.length]}
        frustumCulled={false}
        onClick={(event) => {
          event.stopPropagation();
          if (typeof event.instanceId === "number" && allPorts[event.instanceId]) {
            onPortFocus(allPorts[event.instanceId]);
          }
        }}
        onPointerOver={cursor.over}
        onPointerOut={cursor.out}
      >
        <sphereGeometry args={[1, 8, 8]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} colorWrite={false} />
      </instancedMesh>
    </group>
  );
}

function FoundationPipelineLanes({
  layout,
  morph,
  emphasis,
  focusIds,
  onLaneInspect
}: {
  layout: WorldLayout;
  morph: RefObject<MorphState>;
  emphasis: SourceStateEmphasis | null;
  // R1: lanes mount only for focused stations.
  focusIds: ReadonlySet<string>;
  onLaneInspect: (lane: LaneRenderSpec) => void;
}) {
  const cursor = useSceneCursor();
  const specs = useMemo(() => laneRenderSpecs(layout, focusIds), [focusIds, layout]);
  const { segments, colors } = useMemo(() => {
    const positions: number[] = [];
    const vertexColors: number[] = [];
    const color = new THREE.Color();
    specs.forEach((spec) => {
      color.set(spec.color).multiplyScalar(foundationDimFactor(spec.id, emphasis));
      const before = positions.length;
      circleSegments(spec.center, spec.radius, positions, 40);
      // Discrete cadence ticks (§10.5): short radial marks, never a temporal
      // radius.
      for (let tick = 0; tick < spec.tickCount; tick += 1) {
        const angle = -Math.PI / 2 + (tick / Math.max(spec.tickCount, 1)) * Math.PI * 2;
        positions.push(
          spec.center[0] + Math.cos(angle) * (spec.radius - 0.03),
          spec.center[1],
          spec.center[2] + Math.sin(angle) * (spec.radius - 0.03),
          spec.center[0] + Math.cos(angle) * (spec.radius + 0.03),
          spec.center[1],
          spec.center[2] + Math.sin(angle) * (spec.radius + 0.03)
        );
      }
      const vertices = (positions.length - before) / 3;
      for (let index = 0; index < vertices; index += 1) vertexColors.push(color.r, color.g, color.b);
    });
    return { segments: positions, colors: vertexColors };
  }, [emphasis, specs]);
  if (specs.length === 0) return null;
  return (
    <group>
      <FadingLineSegments segments={segments} colors={colors} baseOpacity={0.5} morph={morph} renderOrder={4} />
      {specs.map((spec) => (
        <group key={spec.id}>
          {spec.stageFraction !== null && (
            <mesh
              position={[
                spec.center[0] + Math.cos(-Math.PI / 2 + spec.stageFraction * Math.PI * 2) * spec.radius,
                spec.center[1] + 0.02,
                spec.center[2] + Math.sin(-Math.PI / 2 + spec.stageFraction * Math.PI * 2) * spec.radius
              ]}
              renderOrder={4}
            >
              <octahedronGeometry args={[0.05, 0]} />
              <meshBasicMaterial
                color={spec.color}
                transparent
                opacity={0.9 * foundationDimFactor(spec.id, emphasis)}
                depthWrite={false}
                toneMapped={false}
              />
            </mesh>
          )}
          {/* Kind symbol keeps content/deep_read visually distinguishable; the
              full ARIA text lives on the accessible twin and this title. */}
          <Html
            position={[spec.center[0] + spec.radius + 0.14, spec.center[1] + 0.04, spec.center[2]]}
            center
            distanceFactor={4.8}
            wrapperClass="sceneHtmlLabel"
            className="radarDeadlineCaption"
            zIndexRange={[21, 0]}
          >
            <span
              aria-hidden
              title={spec.aria}
              style={{ color: spec.color, opacity: foundationDimFactor(spec.id, emphasis) }}
            >
              {spec.symbol}
            </span>
          </Html>
          {/* Inspection-only hit ring (§16.5): click announces, never navigates. */}
          <mesh
            position={spec.center}
            rotation={[Math.PI / 2, 0, 0]}
            renderOrder={4}
            onClick={(event) => {
              event.stopPropagation();
              onLaneInspect(spec);
            }}
            onPointerOver={cursor.over}
            onPointerOut={cursor.out}
          >
            <torusGeometry args={[spec.radius, 0.06, 6, 40]} />
            <meshBasicMaterial transparent opacity={0} depthWrite={false} colorWrite={false} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

// R2: the world mounts (a) one severity badge per affected station with its
// TRUE occurrence total and (b) at most WORLD_GAP_MARKER_BUDGET markers for
// the worst stations' single worst diagnostic. The full census lives in
// sourceGapSummary for the HUD — nothing is silently dropped.
function FoundationGapMarkers({
  layout,
  morph,
  emphasis,
  onGapInspect
}: {
  layout: WorldLayout;
  morph: RefObject<MorphState>;
  emphasis: SourceStateEmphasis | null;
  onGapInspect: (marker: GapMarkerSpec) => void;
}) {
  const specs = useMemo(() => worldGapMarkers(layout), [layout]);
  const badges = useMemo(() => stationGapBadges(layout), [layout]);
  if (specs.length === 0 && badges.length === 0) return null;
  return (
    <group>
      {specs.map((spec) => (
        <GapMarkerMesh
          key={spec.id}
          spec={spec}
          morph={morph}
          dim={foundationDimFactor(spec.id, emphasis)}
          onGapInspect={onGapInspect}
        />
      ))}
      {badges.map((badge) => {
        const token = gapSeverityToken(badge.severity);
        return (
          <Html
            key={`gap-badge-${badge.stationId}`}
            position={badge.position}
            center
            distanceFactor={5}
            wrapperClass="sceneHtmlLabel"
            className="clusterStarLabel"
            zIndexRange={[25, 0]}
          >
            <button type="button" aria-label={badge.aria} title={badge.aria} onClick={() => onGapInspect(badge.topMarker)}>
              <span aria-hidden style={{ color: token.color }}>{token.symbol}</span>
              <strong>{badge.total}</strong>
            </button>
          </Html>
        );
      })}
    </group>
  );
}

function GapMarkerMesh({
  spec,
  morph,
  dim,
  onGapInspect
}: {
  spec: GapMarkerSpec;
  morph: RefObject<MorphState>;
  dim: number;
  onGapInspect: (marker: GapMarkerSpec) => void;
}) {
  const materialRef = useRef<THREE.MeshStandardMaterial | null>(null);
  const cursor = useSceneCursor();
  useFrame((state) => {
    if (!materialRef.current) return;
    materialRef.current.opacity = morphAttachmentOpacity(morph.current, state.clock.elapsedTime, 0.96 * dim);
  });
  return (
    <group position={spec.position}>
      <mesh
        renderOrder={6}
        onClick={(event) => {
          event.stopPropagation();
          onGapInspect(spec);
        }}
        onPointerOver={cursor.over}
        onPointerOut={cursor.out}
      >
        <octahedronGeometry args={[0.09, 0]} />
        <meshStandardMaterial
          ref={materialRef}
          color={spec.color}
          emissive={spec.color}
          emissiveIntensity={0.45 * dim}
          transparent
          opacity={0.96 * dim}
          flatShading
          toneMapped={false}
        />
      </mesh>
      <Html position={[0, 0.16, 0]} center distanceFactor={5} wrapperClass="sceneHtmlLabel" className="clusterStarLabel" zIndexRange={[26, 0]}>
        <button type="button" onClick={() => onGapInspect(spec)} title={spec.aria}>
          <span aria-hidden style={{ color: spec.color }}>{spec.symbol}</span>
          {spec.count > 1 && <strong>×{spec.count}</strong>}
        </button>
      </Html>
    </group>
  );
}

function FoundationGovernancePlates({
  layout,
  morph,
  emphasis,
  onPlateOpen
}: {
  layout: WorldLayout;
  morph: RefObject<MorphState>;
  emphasis: SourceStateEmphasis | null;
  onPlateOpen: (plate: GovernancePlateSpec) => void;
}) {
  const specs = useMemo(() => governancePlateSpecs(layout), [layout]);
  if (specs.length === 0) return null;
  return (
    <group>
      {specs.map((spec) => (
        <GovernancePlateMesh
          key={spec.id}
          spec={spec}
          morph={morph}
          dim={foundationDimFactor(spec.id, emphasis)}
          onPlateOpen={onPlateOpen}
        />
      ))}
    </group>
  );
}

function GovernancePlateMesh({
  spec,
  morph,
  dim,
  onPlateOpen
}: {
  spec: GovernancePlateSpec;
  morph: RefObject<MorphState>;
  dim: number;
  onPlateOpen: (plate: GovernancePlateSpec) => void;
}) {
  const materialRef = useRef<THREE.MeshStandardMaterial | null>(null);
  const cursor = useSceneCursor();
  useFrame((state) => {
    if (!materialRef.current) return;
    materialRef.current.opacity = morphAttachmentOpacity(morph.current, state.clock.elapsedTime, 0.92 * dim);
  });
  return (
    <group position={spec.position}>
      <mesh
        renderOrder={5}
        onClick={(event) => {
          event.stopPropagation();
          onPlateOpen(spec);
        }}
        onPointerOver={cursor.over}
        onPointerOut={cursor.out}
      >
        <boxGeometry args={[0.24, 0.05, 0.16]} />
        <meshStandardMaterial
          ref={materialRef}
          color={spec.color}
          emissive={spec.color}
          emissiveIntensity={(spec.severity === "none" ? 0.16 : 0.4) * dim}
          transparent
          opacity={0.92 * dim}
          flatShading
          toneMapped={false}
        />
      </mesh>
      {spec.severity !== "none" && (
        <Html position={[0, 0.12, 0]} center distanceFactor={4.6} wrapperClass="sceneHtmlLabel" className="radarDeadlineCaption" zIndexRange={[23, 0]}>
          <span aria-hidden title={spec.aria} style={{ color: spec.color }}>{spec.symbol}</span>
        </Html>
      )}
    </group>
  );
}

// The accessible twin (§16.5): one visually-hidden DOM list mirrors every
// MOUNTED derived control so keyboard and screen-reader users reach the exact
// same actions the pointer reaches — focused ports focus the SourceDock,
// focused lanes announce, station gap badges open the worst diagnostic with
// TRUE totals, stationless diagnostics stay reachable as aggregated groups,
// plates open the real config page. R2: the twin never floods with one button
// per diagnostic occurrence — aggregates carry the honest counts instead.
function FoundationAccessTwin({
  layout,
  focusIds,
  onPortFocus,
  onLaneInspect,
  onGapInspect,
  onPlateOpen
}: {
  layout: WorldLayout;
  focusIds: ReadonlySet<string>;
  onPortFocus: (port: SourceStreamPort) => void;
  onLaneInspect: (lane: LaneRenderSpec) => void;
  onGapInspect: (marker: GapMarkerSpec) => void;
  onPlateOpen: (plate: GovernancePlateSpec) => void;
}) {
  const groups = useMemo(() => portRenderGroups(layout, focusIds), [focusIds, layout]);
  const ports = useMemo(
    () => [...groups.solid, ...groups.outline, ...groups.overflow],
    [groups.outline, groups.overflow, groups.solid]
  );
  const lanes = useMemo(() => laneRenderSpecs(layout, focusIds), [focusIds, layout]);
  const gapBadges = useMemo(() => stationGapBadges(layout), [layout]);
  const stationlessGapGroups = useMemo(() => {
    const stationIds = new Set(gapBadges.map((badge) => badge.stationId));
    const summary = sourceGapSummary(layout);
    return summary.groups
      .map((group) => ({
        ...group,
        markers: group.markers.filter((marker) => !marker.sourceId || !stationIds.has(marker.sourceId))
      }))
      .map((group) => ({
        ...group,
        occurrenceCount: group.markers.reduce((sum, marker) => sum + marker.count, 0)
      }))
      .filter((group) => group.markers.length > 0);
  }, [gapBadges, layout]);
  const plates = useMemo(() => governancePlateSpecs(layout), [layout]);
  if (ports.length + lanes.length + gapBadges.length + stationlessGapGroups.length + plates.length === 0) return null;
  return (
    <Html position={[0, 0, 0]} wrapperClass="sceneHtmlLabel" className="visuallyHidden" zIndexRange={[10, 0]}>
      <nav aria-label={t("source_foundation.twin.title")}>
        <ul>
          {ports.map((port) => (
            <li key={`twin-${port.id}`}>
              <button type="button" onClick={() => onPortFocus(port)}>
                {portAriaText(port)}
              </button>
            </li>
          ))}
          {lanes.map((lane) => (
            <li key={`twin-${lane.id}`}>
              <button type="button" onClick={() => onLaneInspect(lane)}>
                {lane.aria}
              </button>
            </li>
          ))}
          {gapBadges.map((badge) => (
            <li key={`twin-gap-station-${badge.stationId}`}>
              <button type="button" onClick={() => onGapInspect(badge.topMarker)}>
                {badge.aria}
              </button>
            </li>
          ))}
          {stationlessGapGroups.map((group) => (
            <li key={`twin-gap-code-${group.code}`}>
              <button type="button" onClick={() => onGapInspect(group.markers[0])}>
                {t("source_foundation.gaps.aggregate", { label: group.label, n: group.occurrenceCount })}
              </button>
            </li>
          ))}
          {plates.map((plate) => (
            <li key={`twin-${plate.id}`}>
              <button type="button" onClick={() => onPlateOpen(plate)}>
                {plate.aria}
              </button>
            </li>
          ))}
        </ul>
      </nav>
    </Html>
  );
}

// ---------------------------------------------------------------------------
// Composition — mounted by SystemScene ONLY when the resolved layout runs the
// foundation profile; any other view renders zero meshes from this module.

export function SourceFoundationPart({
  layout,
  quality,
  selectedId,
  hoveredId = "",
  lens = "",
  trace = null,
  framedBand = null,
  morph,
  onPortFocus,
  onLaneInspect,
  onGapInspect,
  onPlateOpen,
  onBandFrame
}: {
  layout: WorldLayout;
  quality: string;
  selectedId: string;
  // R1: hover shares the focus contract with selection for progressive
  // disclosure (ports/lanes of the hovered station mount).
  hoveredId?: string;
  // §12.7: the source_state lens emphasizes/dims presence only.
  lens?: string;
  // §12.6: selection-driven trace highlight — ephemeral, never route state.
  trace?: TraceHighlight | null;
  // R4: ephemeral band framing state (never route state).
  framedBand?: WorldPlaneId | null;
  morph: RefObject<MorphState>;
  onPortFocus: (port: SourceStreamPort) => void;
  onLaneInspect: (lane: LaneRenderSpec) => void;
  onGapInspect: (marker: GapMarkerSpec) => void;
  onPlateOpen: (plate: GovernancePlateSpec) => void;
  onBandFrame?: (plane: WorldPlaneId) => void;
}) {
  const handlePortFocus = useCallback((port: SourceStreamPort) => onPortFocus(port), [onPortFocus]);
  const emphasis = useMemo(() => sourceStateEmphasis(layout, lens), [layout, lens]);
  const traceIds = useMemo(() => traceHighlightIds(layout, trace), [layout, trace]);
  const focusIds = useMemo(
    () => foundationFocusStationIds(layout, selectedId, hoveredId, trace),
    [hoveredId, layout, selectedId, trace]
  );
  if (!isFoundationProfile(layout)) return null;
  return (
    <group>
      <FoundationBandGuides layout={layout} morph={morph} framedBand={framedBand} onBandFrame={onBandFrame} />
      <FoundationProposalStemsLayer layout={layout} morph={morph} />
      <FoundationConduits layout={layout} morph={morph} focusIds={focusIds} />
      <FoundationFlowBundles
        layout={layout}
        selectedId={selectedId}
        hoveredId={hoveredId}
        quality={quality}
        morph={morph}
        traceIds={traceIds}
        emphasis={emphasis}
      />
      <FoundationStreamPorts layout={layout} morph={morph} emphasis={emphasis} focusIds={focusIds} onPortFocus={handlePortFocus} />
      <FoundationPipelineLanes layout={layout} morph={morph} emphasis={emphasis} focusIds={focusIds} onLaneInspect={onLaneInspect} />
      <FoundationGapMarkers layout={layout} morph={morph} emphasis={emphasis} onGapInspect={onGapInspect} />
      <FoundationGovernancePlates layout={layout} morph={morph} emphasis={emphasis} onPlateOpen={onPlateOpen} />
      <FoundationAccessTwin
        layout={layout}
        focusIds={focusIds}
        onPortFocus={handlePortFocus}
        onLaneInspect={onLaneInspect}
        onGapInspect={onGapInspect}
        onPlateOpen={onPlateOpen}
      />
    </group>
  );
}
