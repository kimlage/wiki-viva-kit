import { DOCK_IDS } from "../contracts";
import type { DockId, LensId, OperatorCommand, OverlayId, RuntimeEvent, ViewId, WorldState } from "../contracts";
import { Registry } from "./Registry";

export type InteractionDefinition = {
  id: RuntimeEvent["type"];
  semanticEffect: string;
  visualEffect: string;
  desktop: string;
  mobile: string;
  fallback: string;
  testId: string;
  shareable: boolean;
  changesCenter: boolean;
};
export type ViewDefinition = { id: ViewId; defaultLens: LensId; defaultOverlay: OverlayId; allowedOverlays: OverlayId[]; compatibility?: boolean };
export type OverlayDefinition = { id: OverlayId; metric: string; fallbackText: string };
export type SurfaceDefinition = { id: Exclude<DockId, "">; modal: boolean; restoresFocus: boolean };
export type SceneSystemDefinition = { id: string; inputs: string[]; fallback: string };
export type VisualPrimitiveDefinition = { id: string; dataField: string; purpose: string; accessibilityText: string };
export type RelationTypeDefinition = { id: string; directed: boolean; inverse?: string; evidenceRequired: boolean };
export type OperatorCommandDefinition = OperatorCommand & { id: string };
export type EffectDefinition = { id: string; abortable: boolean; idempotent: boolean; capability?: string };

export class RegistryKernel {
  readonly interactions = new Registry<InteractionDefinition>("interaction");
  readonly views = new Registry<ViewDefinition>("view");
  readonly overlays = new Registry<OverlayDefinition>("overlay");
  readonly surfaces = new Registry<SurfaceDefinition>("surface");
  readonly sceneSystems = new Registry<SceneSystemDefinition>("scene system");
  readonly visualPrimitives = new Registry<VisualPrimitiveDefinition>("visual primitive");
  readonly relationTypes = new Registry<RelationTypeDefinition>("relation type");
  readonly operatorCommands = new Registry<OperatorCommandDefinition>("operator command");
  readonly effects = new Registry<EffectDefinition>("effect");

  validateState(state: WorldState): string[] {
    const errors: string[] = [];
    const view = this.views.get(state.view);
    if (!view) errors.push(`unknown view: ${state.view}`);
    if (!this.overlays.has(state.overlay)) errors.push(`unknown overlay: ${state.overlay}`);
    if (view && !view.allowedOverlays.includes(state.overlay)) errors.push(`overlay ${state.overlay} is not allowed by ${state.view}`);
    if (state.dock && !this.surfaces.has(state.dock)) errors.push(`unknown surface: ${state.dock}`);
    return errors;
  }
}

export function createDefaultKernel(): RegistryKernel {
  const kernel = new RegistryKernel();
  const overlays: OverlayDefinition[] = [
    { id: "attention", metric: "attention_score", fallbackText: "Attention" },
    { id: "freshness", metric: "freshness_state", fallbackText: "Freshness" },
    { id: "actions", metric: "open_action_count", fallbackText: "Open actions" },
    { id: "ownership", metric: "owner_state", fallbackText: "Ownership" },
    { id: "evidence", metric: "evidence_state", fallbackText: "Evidence" },
    { id: "quality", metric: "quality_score", fallbackText: "Quality" }
  ];
  overlays.forEach((entry) => kernel.overlays.register(entry));
  const all = overlays.map((entry) => entry.id);
  [
    { id: "quadrants", defaultLens: "all", defaultOverlay: "actions", allowedOverlays: all },
    { id: "radar", defaultLens: "all", defaultOverlay: "freshness", allowedOverlays: all },
    { id: "sources", defaultLens: "all", defaultOverlay: "evidence", allowedOverlays: ["attention", "freshness", "actions", "ownership", "evidence", "quality"] },
    { id: "work", defaultLens: "all", defaultOverlay: "actions", allowedOverlays: all },
    { id: "atlas", defaultLens: "type", defaultOverlay: "actions", allowedOverlays: all, compatibility: true },
    { id: "focus", defaultLens: "relations", defaultOverlay: "evidence", allowedOverlays: all, compatibility: true },
    { id: "districts", defaultLens: "type", defaultOverlay: "actions", allowedOverlays: all, compatibility: true },
    { id: "trails", defaultLens: "relations", defaultOverlay: "evidence", allowedOverlays: all, compatibility: true }
  ].forEach((entry) => kernel.views.register(entry as ViewDefinition));
  const interaction = (
    id: RuntimeEvent["type"],
    semanticEffect: string,
    visualEffect: string,
    options: { shareable?: boolean; changesCenter?: boolean } = {}
  ): InteractionDefinition => ({
    id,
    semanticEffect,
    visualEffect,
    desktop: "pointer and keyboard dispatch the same registered event",
    mobile: "tap target is at least 44px and dispatches the same registered event",
    fallback: "2D control dispatches the same registered event",
    testId: `runtime-${id}`,
    shareable: options.shareable ?? true,
    changesCenter: options.changesCenter ?? false
  });
  [
    interaction("hydrateRoute", "hydrate validated shareable state", "restore the addressed world", { shareable: false }),
    interaction("inspectHover", "set ephemeral hover only", "highlight and explain without travel", { shareable: false }),
    interaction("inspectEntity", "set ephemeral inspection only", "show anchored explanation", { shareable: false }),
    interaction("selectEntity", "select a real page", "show summary plate"),
    interaction("readEntity", "read a selected real page", "open reader"),
    interaction("openReader", "read a selected real page", "open reader"),
    interaction("selectCenter", "recenter on a real page", "morph or frame the local world", { changesCenter: true }),
    interaction("setView", "change geometry only", "morph keyed nodes"),
    interaction("setLens", "change semantic projection only", "filter/orient around the same center"),
    interaction("setOverlay", "change metric encoding only", "recolor or remark without relayout"),
    interaction("selectGroup", "focus a real family grouping", "emphasize members without recentering"),
    interaction("openSurface", "open one registered surface", "show dock and restore focus on close"),
    interaction("openDock", "open one registered surface", "show dock and restore focus on close"),
    interaction("openSource", "select a canonical source page", "open source surface"),
    interaction("openPerson", "select and read a canonical person page", "open reader"),
    interaction("openAction", "select and read a canonical action page", "open work detail"),
    interaction("focusRegion", "inspect derived region state", "focus region without changing center", { shareable: false }),
    interaction("seedPage", "prepare a typed-page draft", "open registered create surface"),
    interaction("executeOperatorCommand", "request a capability-guarded effect", "open preview or receipt", { shareable: false }),
    interaction("refreshSnapshot", "request an abortable snapshot refresh", "show bounded progress", { shareable: false }),
    interaction("closeSurface", "close the primary surface", "restore prior focus"),
    interaction("setFallback", "choose equivalent 2D rendering", "preserve semantic world state"),
    interaction("setCameraIntent", "set ephemeral camera intent", "frame without semantic mutation", { shareable: false }),
    interaction("setSafeArea", "record measured viewport occupancy", "keep controls and labels unobscured", { shareable: false })
  ].forEach((entry) => kernel.interactions.register(entry));
  DOCK_IDS.forEach((id) =>
    kernel.surfaces.register({ id: id as Exclude<DockId, "">, modal: true, restoresFocus: true })
  );
  [
    { id: "camera", inputs: ["center", "view", "selection"], fallback: "static framing" },
    { id: "layout", inputs: ["pages", "relations", "view", "lens"], fallback: "deterministic list" },
    { id: "labels", inputs: ["pages", "density", "safeArea"], fallback: "text list" },
    { id: "particles", inputs: ["source_lifecycle", "flow"], fallback: "status text" },
    { id: "relationships", inputs: ["typed_edges", "overlay"], fallback: "relation list" },
    { id: "visual-regions", inputs: ["region_groups", "view"], fallback: "region cards" },
    { id: "collision", inputs: ["layout", "labels", "safeArea"], fallback: "stacked cards" },
    { id: "responsiveness", inputs: ["viewport", "safeArea", "inputMode"], fallback: "2d world" }
  ].forEach((entry) => kernel.sceneSystems.register(entry));
  [
    { id: "hierarchy", directed: true, inverse: "contains", evidenceRequired: false },
    { id: "contains", directed: true, inverse: "hierarchy", evidenceRequired: false },
    { id: "evidence", directed: true, evidenceRequired: true },
    { id: "emission", directed: true, evidenceRequired: true },
    { id: "dependency", directed: true, evidenceRequired: false },
    { id: "ownership", directed: true, evidenceRequired: true },
    { id: "participation", directed: true, evidenceRequired: true },
    { id: "citation", directed: true, evidenceRequired: true },
    { id: "impact", directed: true, evidenceRequired: true },
    { id: "temporal", directed: true, evidenceRequired: true }
  ].forEach((entry) => kernel.relationTypes.register(entry));
  [
    { id: "snapshot.read", abortable: true, idempotent: true },
    { id: "content.read", abortable: true, idempotent: true },
    { id: "operator.execute", abortable: true, idempotent: true, capability: "operator" }
  ].forEach((entry) => kernel.effects.register(entry));
  return kernel;
}
