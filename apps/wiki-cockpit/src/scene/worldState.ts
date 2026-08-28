import { SCENE_FACETS, type SceneFacet } from "./facets";

export type LensId = SceneFacet;

export type RealFamilyKind =
  | "source"
  | "person"
  | "event"
  | "action"
  | "rule"
  | "decision"
  | "hub"
  | "content"
  | "root";

export type RealFamilyGroupId = `family:${RealFamilyKind}`;

export type InteractionIntent =
  | "inspect-only"
  | "orient-lens"
  | "open-real-group"
  | "open-real-page"
  | "open-dock"
  | "disabled-empty";

const REAL_FAMILY_KINDS = new Set<RealFamilyKind>([
  "source",
  "person",
  "event",
  "action",
  "rule",
  "decision",
  "hub",
  "content",
  "root"
]);

export function isLensId(value: string | null | undefined): value is LensId {
  return SCENE_FACETS.includes(value as SceneFacet);
}

export function normalizeLensId(value: string | null | undefined): LensId | undefined {
  return isLensId(value) ? value : undefined;
}

export function normalizeRealFamilyKind(value: string | null | undefined): RealFamilyKind {
  return value && REAL_FAMILY_KINDS.has(value as RealFamilyKind) ? (value as RealFamilyKind) : "content";
}

export function realFamilyGroupId(family: string): RealFamilyGroupId {
  return `family:${normalizeRealFamilyKind(family)}`;
}

export function parseRealFamilyGroupId(value: string | null | undefined): { family: RealFamilyKind; key: RealFamilyGroupId } | null {
  if (!value || value.startsWith("region:")) return null;
  const [prefix, family, ...rest] = value.split(":");
  if (prefix !== "family" || rest.length > 0) return null;
  const normalized = normalizeRealFamilyKind(family);
  if (family !== normalized) return null;
  return { family: normalized, key: `family:${normalized}` };
}

export function isLegacyRegionGroup(value: string | null | undefined): boolean {
  return Boolean(value && value.startsWith("region:"));
}

export type WorldNavigationState = {
  centerId: string;
  lens?: LensId;
  group?: RealFamilyGroupId;
  pageId?: string;
  dock?: string;
  reader: boolean;
  legacyRegion: boolean;
};

export function worldNavigationState(input: {
  centerId?: string | null;
  lens?: string | null;
  group?: string | null;
  pageId?: string | null;
  dock?: string | null;
  reader?: boolean;
}): WorldNavigationState {
  const family = parseRealFamilyGroupId(input.group);
  return {
    centerId: input.centerId || "",
    lens: normalizeLensId(input.lens),
    group: family?.key,
    pageId: input.pageId || undefined,
    dock: input.dock || undefined,
    reader: Boolean(input.reader),
    legacyRegion: isLegacyRegionGroup(input.group)
  };
}
