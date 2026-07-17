// "admin" is the god-mode surface (plan §14.1): registered here like every
// dock so ?dock=admin can open it, but it never joins the default navigation —
// discoverability comes from the ui_admin block, authorization from the server.
export const DOCK_IDS = ["approve", "intake", "gates", "codex", "work", "source", "create", "blocks", "admin"] as const;
export type DockId = "" | (typeof DOCK_IDS)[number];

export const NATIVE_VIEWS = ["quadrants", "radar", "sources", "work", "timeline"] as const;
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

// --- Spatial/camera profiles (source foundation plane) ---------------------
// A view renders either the historical upper knowledge hemisphere or the
// vertical source-foundation profile. The profile id is registry data, never a
// URL parameter (ADR-002/§7.6: no `stratum`, `camera` or `floor` route state).
export const VIEW_SPATIAL_PROFILE_IDS = ["knowledge-upper", "source-foundation"] as const;
export type ViewSpatialProfileId = (typeof VIEW_SPATIAL_PROFILE_IDS)[number];

// The four vertical bands of the source-foundation profile. Y between bands is
// structural role (ADR-003); Y inside a band is bounded visual adjustment only.
export const WORLD_PLANE_IDS = ["core", "knowledge", "provenance", "foundation"] as const;
export type WorldPlaneId = (typeof WORLD_PLANE_IDS)[number];

// Band levels are named tokens, not repeated literals (§6.1).
export const SOURCE_FOUNDATION_LEVELS = {
  core: 2.4,
  knowledge: 0,
  provenance: -1.6,
  foundation: -3.2
} as const satisfies Record<WorldPlaneId, number>;

// Any state-driven Y offset inside the foundation profile (proposal float,
// marker lifts) is re-expressed within the node's own band and never exceeds
// this amplitude (§10.12) — a provenance proposal can never float into the
// knowledge band.
export const SOURCE_FOUNDATION_WITHIN_BAND_LIFT = 0.25;

// Structural role of a node inside the source-foundation profile (§7.3).
export type SourceFoundationRole =
  | "core-anchor"
  | "knowledge-page"
  | "provenance-page"
  | "source-station"
  | "channel-station"
  | "governance-control";

export type ViewCameraProfile = {
  hemisphere: "upper" | "lower";
  transitionPath: "direct" | "outer_arc";
  minPolarAngle: number;
  maxPolarAngle: number;
  defaultPhi: number;
  targetLevel: WorldPlaneId;
  allowUserHemisphereCrossing: boolean;
};

// Polar limits per hemisphere (§11.2). The lower profile mirrors the upper
// one across the horizon; the user orbits inside the view's hemisphere and
// only a registered view change crosses it.
export const UPPER_MIN_POLAR_ANGLE = 0.3;
export const UPPER_MAX_POLAR_ANGLE = 1.25;
export const LOWER_MIN_POLAR_ANGLE = Math.PI - UPPER_MAX_POLAR_ANGLE;
export const LOWER_MAX_POLAR_ANGLE = Math.PI - UPPER_MIN_POLAR_ANGLE;

// Recommended initial lower pose (§6.4), registered here so the numbers exist
// exactly once. R-SCENE framing: the resting distance frames the CONTENT — the
// station ring as foreground with the core visible up-frame — instead of the
// full retreat fit (which read as a tiny distant ring). 0.7 of the layout fit
// keeps the whole band span inside the 40° vertical FOV at the registered phi
// while staying far above the orbit minimum (0.18 × fit), so nothing clips.
export const SOURCE_FOUNDATION_CAMERA = {
  hemisphere: "lower",
  phi: Math.PI - 0.72,
  distanceMultiplier: 0.7,
  targetY: SOURCE_FOUNDATION_LEVELS.foundation + 0.25,
  transitionPath: "outer_arc",
  labels: "billboard"
} as const;

export const KNOWLEDGE_UPPER_CAMERA_PROFILE: ViewCameraProfile = {
  hemisphere: "upper",
  transitionPath: "direct",
  minPolarAngle: UPPER_MIN_POLAR_ANGLE,
  maxPolarAngle: UPPER_MAX_POLAR_ANGLE,
  // The settled upper development pose used by the scene camera today.
  defaultPhi: 0.72,
  targetLevel: "knowledge",
  allowUserHemisphereCrossing: false
};

export const SOURCE_FOUNDATION_CAMERA_PROFILE: ViewCameraProfile = {
  hemisphere: "lower",
  transitionPath: "outer_arc",
  minPolarAngle: LOWER_MIN_POLAR_ANGLE,
  maxPolarAngle: LOWER_MAX_POLAR_ANGLE,
  defaultPhi: SOURCE_FOUNDATION_CAMERA.phi,
  targetLevel: "foundation",
  allowUserHemisphereCrossing: false
};

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
  // Genesis 0 is a declared pre-world state, not a page with a fabricated id.
  // Every regular world still owns a real page center.
  centerId: string | null;
  emptyWorld: boolean;
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
