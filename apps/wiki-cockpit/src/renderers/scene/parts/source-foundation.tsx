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
import type {
  SourceFlowBundle,
  SourceGapMarker,
  SourceGovernancePlate,
  SourcePipelineLane,
  SourceStreamPort,
  WorldLayout
} from "../../../scene/perspectives";
import { SOURCE_FOUNDATION_WITHIN_BAND_LIFT } from "../../../world/contracts";
import type { WorldPlaneId } from "../../../world/contracts";
import { morphAttachmentOpacity } from "./nodes";
import type { MorphState } from "./nodes";

// ---------------------------------------------------------------------------
// Pure specs (unit-tested; no three.js state)

/** True only for the resolved foundation profile — every renderer below and
 * the SystemScene composition key off this, so other views mount ZERO meshes. */
export function isFoundationProfile(layout: WorldLayout): boolean {
  return layout.planeProfile?.active === "foundation";
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
};

// One quiet ring per band at the band's EXACT structural level (§10.12: the
// profile owns its plane guides; radii follow the layout so the visual
// spacing control flows through).
export function foundationPlaneGuides(layout: WorldLayout): FoundationBandGuide[] {
  if (!isFoundationProfile(layout) || !layout.planeProfile) return [];
  const levels = layout.planeProfile.levels;
  return [
    { plane: "foundation", y: levels.foundation, radius: layout.rOuter * 0.66, labelKey: "source_foundation.band.foundation", opacity: 0.3 },
    { plane: "provenance", y: levels.provenance, radius: layout.rOuter * 0.82, labelKey: "source_foundation.band.provenance", opacity: 0.22 },
    { plane: "knowledge", y: levels.knowledge, radius: layout.rOuter * 0.9, labelKey: "source_foundation.band.knowledge", opacity: 0.16 },
    { plane: "core", y: levels.core, radius: Math.max(layout.rInner * 1.1, 1.1), labelKey: "source_foundation.band.core", opacity: 0.2 }
  ];
}

export type PortRenderGroups = {
  solid: SourceStreamPort[];
  outline: SourceStreamPort[];
  overflow: SourceStreamPort[];
  breached: SourceStreamPort[];
};

// §10.4: selected streams solid, unselected outline, the aggregated "+N" port
// carries the TRUE hidden count, breach is an overlay symbol (never position).
export function portRenderGroups(layout: WorldLayout): PortRenderGroups {
  const ports = (layout.foundationPrimitives ?? []).filter(
    (primitive): primitive is SourceStreamPort => primitive.kind === "stream-port"
  );
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

export function laneRenderSpecs(layout: WorldLayout): LaneRenderSpec[] {
  const lanes = (layout.foundationPrimitives ?? []).filter(
    (primitive): primitive is SourcePipelineLane => primitive.kind === "pipeline-lane"
  );
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
// real emission direction, never from animation.
export function flowBundleSpecs(layout: WorldLayout, selectedId = ""): FlowBundleSpec[] {
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
      Boolean(selectedId) && (bundle.pageIds.includes(selectedId) || bundle.sourceIds.includes(selectedId));
    return {
      id: bundle.id,
      from: bundle.from,
      to: bundle.to,
      control,
      color: flowSeverityColor(bundle.severity),
      opacity: selected
        ? foundationBandOpacity("knowledge", true) * 0.62
        : foundationBandOpacity("knowledge") * 0.62,
      traceCount: bundle.traceCount,
      arrowAt: bezierPoint(bundle.from, control, bundle.to, 0.82),
      arrowToward: bezierPoint(bundle.from, control, bundle.to, 0.94),
      countLabelAt: bundle.traceCount > 1 ? bezierPoint(bundle.from, control, bundle.to, 0.5) : null,
      pageIds: bundle.pageIds,
      sourceIds: bundle.sourceIds
    };
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

function FoundationBandGuides({ layout, morph }: { layout: WorldLayout; morph: RefObject<MorphState> }) {
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
      {guides.map((guide) => (
        <Html
          key={guide.plane}
          position={[guide.radius * 0.72, guide.y + 0.06, guide.radius * 0.6]}
          center
          distanceFactor={6.4}
          wrapperClass="sceneHtmlLabel"
          className="radarDeadlineCaption"
          zIndexRange={[18, 0]}
        >
          <span style={{ opacity: Math.min(guide.opacity * 3, 1) }}>{t(guide.labelKey)}</span>
        </Html>
      ))}
    </group>
  );
}

function FoundationConduits({ layout, morph }: { layout: WorldLayout; morph: RefObject<MorphState> }) {
  const conduits = useMemo(() => conduitSpecs(layout), [layout]);
  const segments = useMemo(() => {
    const out: number[] = [];
    conduits.forEach((conduit) => {
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
  }, [conduits]);
  const bundleBadges = useMemo(
    () => conduits.filter((conduit) => conduit.bundledCount > 0),
    [conduits]
  );
  if (conduits.length === 0) return null;
  const opacity = foundationBandOpacity("provenance") * 0.42;
  return (
    <group>
      <FadingLineSegments segments={segments} color={CONDUIT_COLOR} baseOpacity={opacity} morph={morph} renderOrder={2} />
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
  quality,
  morph
}: {
  layout: WorldLayout;
  selectedId: string;
  quality: string;
  morph: RefObject<MorphState>;
}) {
  const specs = useMemo(() => flowBundleSpecs(layout, selectedId), [layout, selectedId]);
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
};

function PortInstancedLayer({ ports, wireframe, morph }: PortInstancedLayerProps) {
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
  const baseOpacity = wireframe ? 0.85 : 1;
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
  onPortFocus
}: {
  layout: WorldLayout;
  morph: RefObject<MorphState>;
  onPortFocus: (port: SourceStreamPort) => void;
}) {
  const groups = useMemo(() => portRenderGroups(layout), [layout]);
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
      <PortInstancedLayer ports={groups.solid} wireframe={false} morph={morph} />
      <PortInstancedLayer ports={groups.outline} wireframe morph={morph} />
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
  onLaneInspect
}: {
  layout: WorldLayout;
  morph: RefObject<MorphState>;
  onLaneInspect: (lane: LaneRenderSpec) => void;
}) {
  const specs = useMemo(() => laneRenderSpecs(layout), [layout]);
  const { segments, colors } = useMemo(() => {
    const positions: number[] = [];
    const vertexColors: number[] = [];
    const color = new THREE.Color();
    specs.forEach((spec) => {
      color.set(spec.color);
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
  }, [specs]);
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
              <meshBasicMaterial color={spec.color} transparent opacity={0.9} depthWrite={false} toneMapped={false} />
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
            <span aria-hidden title={spec.aria} style={{ color: spec.color }}>{spec.symbol}</span>
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
          >
            <torusGeometry args={[spec.radius, 0.06, 6, 40]} />
            <meshBasicMaterial transparent opacity={0} depthWrite={false} colorWrite={false} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

function FoundationGapMarkers({
  layout,
  morph,
  onGapInspect
}: {
  layout: WorldLayout;
  morph: RefObject<MorphState>;
  onGapInspect: (marker: GapMarkerSpec) => void;
}) {
  const specs = useMemo(() => gapMarkerSpecs(layout), [layout]);
  if (specs.length === 0) return null;
  return (
    <group>
      {specs.map((spec) => (
        <GapMarkerMesh key={spec.id} spec={spec} morph={morph} onGapInspect={onGapInspect} />
      ))}
    </group>
  );
}

function GapMarkerMesh({
  spec,
  morph,
  onGapInspect
}: {
  spec: GapMarkerSpec;
  morph: RefObject<MorphState>;
  onGapInspect: (marker: GapMarkerSpec) => void;
}) {
  const materialRef = useRef<THREE.MeshStandardMaterial | null>(null);
  useFrame((state) => {
    if (!materialRef.current) return;
    materialRef.current.opacity = morphAttachmentOpacity(morph.current, state.clock.elapsedTime, 0.96);
  });
  return (
    <group position={spec.position}>
      <mesh
        renderOrder={6}
        onClick={(event) => {
          event.stopPropagation();
          onGapInspect(spec);
        }}
      >
        <octahedronGeometry args={[0.09, 0]} />
        <meshStandardMaterial
          ref={materialRef}
          color={spec.color}
          emissive={spec.color}
          emissiveIntensity={0.45}
          transparent
          opacity={0.96}
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
  onPlateOpen
}: {
  layout: WorldLayout;
  morph: RefObject<MorphState>;
  onPlateOpen: (plate: GovernancePlateSpec) => void;
}) {
  const specs = useMemo(() => governancePlateSpecs(layout), [layout]);
  if (specs.length === 0) return null;
  return (
    <group>
      {specs.map((spec) => (
        <GovernancePlateMesh key={spec.id} spec={spec} morph={morph} onPlateOpen={onPlateOpen} />
      ))}
    </group>
  );
}

function GovernancePlateMesh({
  spec,
  morph,
  onPlateOpen
}: {
  spec: GovernancePlateSpec;
  morph: RefObject<MorphState>;
  onPlateOpen: (plate: GovernancePlateSpec) => void;
}) {
  const materialRef = useRef<THREE.MeshStandardMaterial | null>(null);
  useFrame((state) => {
    if (!materialRef.current) return;
    materialRef.current.opacity = morphAttachmentOpacity(morph.current, state.clock.elapsedTime, 0.92);
  });
  return (
    <group position={spec.position}>
      <mesh
        renderOrder={5}
        onClick={(event) => {
          event.stopPropagation();
          onPlateOpen(spec);
        }}
      >
        <boxGeometry args={[0.24, 0.05, 0.16]} />
        <meshStandardMaterial
          ref={materialRef}
          color={spec.color}
          emissive={spec.color}
          emissiveIntensity={spec.severity === "none" ? 0.16 : 0.4}
          transparent
          opacity={0.92}
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
// derived control so keyboard and screen-reader users reach the exact same
// actions the pointer reaches — ports focus the SourceDock, lanes announce,
// gap markers open their diagnostic, plates open the real config page.
function FoundationAccessTwin({
  layout,
  onPortFocus,
  onLaneInspect,
  onGapInspect,
  onPlateOpen
}: {
  layout: WorldLayout;
  onPortFocus: (port: SourceStreamPort) => void;
  onLaneInspect: (lane: LaneRenderSpec) => void;
  onGapInspect: (marker: GapMarkerSpec) => void;
  onPlateOpen: (plate: GovernancePlateSpec) => void;
}) {
  const groups = useMemo(() => portRenderGroups(layout), [layout]);
  const ports = useMemo(
    () => [...groups.solid, ...groups.outline, ...groups.overflow],
    [groups.outline, groups.overflow, groups.solid]
  );
  const lanes = useMemo(() => laneRenderSpecs(layout), [layout]);
  const gaps = useMemo(() => gapMarkerSpecs(layout), [layout]);
  const plates = useMemo(() => governancePlateSpecs(layout), [layout]);
  if (ports.length + lanes.length + gaps.length + plates.length === 0) return null;
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
          {gaps.map((gap) => (
            <li key={`twin-${gap.id}`}>
              <button type="button" onClick={() => onGapInspect(gap)}>
                {gap.aria}
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
  morph,
  onPortFocus,
  onLaneInspect,
  onGapInspect,
  onPlateOpen
}: {
  layout: WorldLayout;
  quality: string;
  selectedId: string;
  morph: RefObject<MorphState>;
  onPortFocus: (port: SourceStreamPort) => void;
  onLaneInspect: (lane: LaneRenderSpec) => void;
  onGapInspect: (marker: GapMarkerSpec) => void;
  onPlateOpen: (plate: GovernancePlateSpec) => void;
}) {
  const handlePortFocus = useCallback((port: SourceStreamPort) => onPortFocus(port), [onPortFocus]);
  if (!isFoundationProfile(layout)) return null;
  return (
    <group>
      <FoundationBandGuides layout={layout} morph={morph} />
      <FoundationProposalStemsLayer layout={layout} morph={morph} />
      <FoundationConduits layout={layout} morph={morph} />
      <FoundationFlowBundles layout={layout} selectedId={selectedId} quality={quality} morph={morph} />
      <FoundationStreamPorts layout={layout} morph={morph} onPortFocus={handlePortFocus} />
      <FoundationPipelineLanes layout={layout} morph={morph} onLaneInspect={onLaneInspect} />
      <FoundationGapMarkers layout={layout} morph={morph} onGapInspect={onGapInspect} />
      <FoundationGovernancePlates layout={layout} morph={morph} onPlateOpen={onPlateOpen} />
      <FoundationAccessTwin
        layout={layout}
        onPortFocus={handlePortFocus}
        onLaneInspect={onLaneInspect}
        onGapInspect={onGapInspect}
        onPlateOpen={onPlateOpen}
      />
    </group>
  );
}
