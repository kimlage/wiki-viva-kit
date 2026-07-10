export const DOCK_IDS = ["approve", "intake", "gates", "codex", "work", "source", "create", "blocks"] as const;
export type DockId = "" | (typeof DOCK_IDS)[number];

export const NATIVE_VIEWS = ["quadrants", "radar", "sources", "work"] as const;
export const COMPAT_VIEWS = ["atlas", "focus", "districts", "trails"] as const;
export const VIEW_IDS = [...NATIVE_VIEWS, ...COMPAT_VIEWS] as const;
export type ViewId = (typeof VIEW_IDS)[number];

export const LENS_IDS = [
  "all",
  "q1_intencao",
  "q2_pratica",
  "q3_relacoes",
  "q4_sistemas",
  "type",
  "relations",
  "source_state"
] as const;
export type LensId = (typeof LENS_IDS)[number];

export const OVERLAY_IDS = ["attention", "freshness", "actions", "ownership", "evidence", "quality"] as const;
export type OverlayId = (typeof OVERLAY_IDS)[number];

export type FamilyKind = "source" | "person" | "event" | "action" | "rule" | "decision" | "hub" | "content" | "root";
export type FamilyGroupId = `family:${FamilyKind}`;

export type RuntimeMode = "legacy" | "compat" | "v8";
export type PageEntityRef = { id: string; pageType: string; title?: string };
export type PageEntityIndex = ReadonlyMap<string, PageEntityRef>;

export type RouteWarningCode =
  | "invalid_center"
  | "invalid_page"
  | "invalid_view"
  | "invalid_lens"
  | "invalid_overlay"
  | "legacy_route"
  | "legacy_quadrant"
  | "legacy_region_group"
  | "invalid_runtime"
  | "unsupported_overlay";

export type RouteWarning = { code: RouteWarningCode; value?: string; normalizedTo?: string };

export type WorldState = {
  mode: RuntimeMode;
  centerId: string;
  view: ViewId;
  lens: LensId;
  overlay: OverlayId;
  group?: FamilyGroupId;
  selectedId?: string;
  hoveredId?: string;
  readerId?: string;
  dock?: DockId;
  fallback: boolean;
  focusedRegion?: string;
  cameraIntent: { kind: "preserve" | "frame-center" | "frame-selection" | "reset"; entityId?: string };
  safeArea: { top: number; right: number; bottom: number; left: number; width: number; height: number };
  warnings: RouteWarning[];
};

export type RuntimeEvent =
  | { type: "hydrateRoute"; state: WorldState }
  | { type: "inspectHover"; entityId?: string }
  | { type: "inspectEntity"; entityId?: string }
  | { type: "selectEntity"; entityId: string }
  | { type: "readEntity"; entityId?: string }
  | { type: "openReader"; entityId?: string }
  | { type: "selectCenter"; entityId: string }
  | { type: "setView"; view: ViewId }
  | { type: "setLens"; lens: LensId }
  | { type: "setOverlay"; overlay: OverlayId }
  | { type: "selectGroup"; group?: FamilyGroupId }
  | { type: "openSurface"; dock: DockId }
  | { type: "openDock"; dock: DockId }
  | { type: "openSource"; entityId: string }
  | { type: "openPerson"; entityId: string }
  | { type: "openAction"; entityId: string }
  | { type: "focusRegion"; regionId?: string }
  | { type: "seedPage"; pageType?: string }
  | { type: "executeOperatorCommand"; commandId: string }
  | { type: "refreshSnapshot" }
  | { type: "closeSurface" }
  | { type: "setFallback"; fallback: boolean }
  | { type: "setCameraIntent"; intent: WorldState["cameraIntent"] }
  | { type: "setSafeArea"; safeArea: WorldState["safeArea"] };

export const WORLD_STATE_OWNERSHIP = {
  shareable: ["centerId", "view", "lens", "overlay", "group", "selectedId", "readerId", "dock", "fallback"],
  ephemeral: ["hoveredId", "focusedRegion", "cameraIntent"],
  derived: ["safeArea"],
  resource: ["snapshot", "content", "operator"],
  diagnostic: ["warnings", "runtimeEvents", "performance"]
} as const;

export function historyModeForEvent(event: RuntimeEvent): "push" | "replace" | "none" {
  if (["inspectHover", "inspectEntity", "setCameraIntent", "setSafeArea", "focusRegion"].includes(event.type)) return "none";
  if (["selectEntity", "setFallback"].includes(event.type)) return "replace";
  if (["executeOperatorCommand", "refreshSnapshot"].includes(event.type)) return "none";
  return "push";
}

export type OperatorCommand = {
  id: string;
  capability: string;
  risk: "read" | "write" | "publish";
  preview: string;
  idempotencyKey?: string;
};

export type CommandReceipt = {
  commandId: string;
  status: "previewed" | "succeeded" | "failed" | "cancelled";
  startedAt: string;
  finishedAt?: string;
  redactedSummary: string;
};

export function isPageEntity(index: PageEntityIndex, value: string | undefined): value is string {
  return Boolean(value && index.has(value));
}
