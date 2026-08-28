import { NATIVE_VIEWS, OVERLAY_IDS } from "./contracts";
import type { LensId, OverlayId } from "./contracts";
import type { RegistryKernel } from "./registries/RegistryKernel";

export type NativeWorldViewId = (typeof NATIVE_VIEWS)[number];

export const QUADRANT_LENS_IDS = [
  "q1_intencao",
  "q2_pratica",
  "q3_relacoes",
  "q4_sistemas"
] as const satisfies readonly LensId[];

export type QuadrantLensId = (typeof QUADRANT_LENS_IDS)[number];
export type QuadrantLensOptionId = "all" | QuadrantLensId;
export type QuadrantLensSelection = QuadrantLensOptionId;

export type ExperienceIconId =
  | "view"
  | "lens"
  | "overlay"
  | "quadrants"
  | "radar"
  | "sources"
  | "work"
  | "timeline"
  | "attention"
  | "freshness"
  | "actions"
  | "ownership"
  | "evidence"
  | "quality";

export type ExperienceAxis = {
  id: "view" | "lens" | "overlay";
  icon: ExperienceIconId;
  labelKey: string;
  descriptionKey: string;
};

export type ViewExperience = {
  id: NativeWorldViewId;
  icon: ExperienceIconId;
  labelKey: string;
  questionKey: string;
  descriptionKey: string;
};

export type OverlayExperience = {
  id: OverlayId;
  icon: ExperienceIconId;
  labelKey: string;
  questionKey: string;
  descriptionKey: string;
};

export type QuadrantLensExperience = {
  id: QuadrantLensOptionId;
  value: QuadrantLensSelection;
  labelKey: string;
  descriptionKey: string;
};

/**
 * Copy lives in the normal EN/PT dictionary. This module only names the
 * semantic slots so the navigator can be rendered by any deployment without
 * embedding one language (or one product explanation) in the component.
 */
export const WORLD_EXPERIENCE_KEYS = {
  compactAria: "world.experience.compactAria",
  viewGroupAria: "world.experience.viewGroupAria",
  compatibilityBadge: "world.experience.compatibility.badge",
  compatibilitySwitchHint: "world.experience.compatibility.switchHint",
  overlaySelectLabel: "world.overlayControl",
  learn: "world.experience.learn",
  close: "world.experience.close",
  panelTitle: "world.experience.title",
  panelIntro: "world.experience.intro",
  mentalModelTitle: "world.experience.mentalModel.title",
  viewsTitle: "world.experience.views.title",
  viewsIntro: "world.experience.views.intro",
  overlaysTitle: "world.experience.overlays.title",
  overlaysIntro: "world.experience.overlays.intro",
  lensesTitle: "world.experience.lenses.title",
  lensesIntro: "world.experience.lenses.intro"
} as const;

export const WORLD_EXPERIENCE_AXES = [
  {
    id: "view",
    icon: "view",
    labelKey: "world.experience.axis.view.label",
    descriptionKey: "world.experience.axis.view.description"
  },
  {
    id: "lens",
    icon: "lens",
    labelKey: "world.experience.axis.lens.label",
    descriptionKey: "world.experience.axis.lens.description"
  },
  {
    id: "overlay",
    icon: "overlay",
    labelKey: "world.experience.axis.overlay.label",
    descriptionKey: "world.experience.axis.overlay.description"
  }
] as const satisfies readonly ExperienceAxis[];

export const WORLD_VIEW_EXPERIENCES = [
  {
    id: "quadrants",
    icon: "quadrants",
    labelKey: "world.view.quadrants",
    questionKey: "world.experience.view.quadrants.question",
    descriptionKey: "world.experience.view.quadrants.description"
  },
  {
    id: "radar",
    icon: "radar",
    labelKey: "world.view.radar",
    questionKey: "world.experience.view.radar.question",
    descriptionKey: "world.experience.view.radar.description"
  },
  {
    id: "sources",
    icon: "sources",
    labelKey: "world.view.sources",
    questionKey: "world.experience.view.sources.question",
    descriptionKey: "world.experience.view.sources.description"
  },
  {
    id: "work",
    icon: "work",
    labelKey: "world.view.work",
    questionKey: "world.experience.view.work.question",
    descriptionKey: "world.experience.view.work.description"
  },
  {
    id: "timeline",
    icon: "timeline",
    labelKey: "world.view.timeline",
    questionKey: "world.experience.view.timeline.question",
    descriptionKey: "world.experience.view.timeline.description"
  }
] as const satisfies readonly ViewExperience[];

export const WORLD_OVERLAY_EXPERIENCES = [
  {
    id: "attention",
    icon: "attention",
    labelKey: "world.overlay.attention",
    questionKey: "world.experience.overlay.attention.question",
    descriptionKey: "world.experience.overlay.attention.description"
  },
  {
    id: "freshness",
    icon: "freshness",
    labelKey: "world.overlay.freshness",
    questionKey: "world.experience.overlay.freshness.question",
    descriptionKey: "world.experience.overlay.freshness.description"
  },
  {
    id: "actions",
    icon: "actions",
    labelKey: "world.overlay.actions",
    questionKey: "world.experience.overlay.actions.question",
    descriptionKey: "world.experience.overlay.actions.description"
  },
  {
    id: "ownership",
    icon: "ownership",
    labelKey: "world.overlay.ownership",
    questionKey: "world.experience.overlay.ownership.question",
    descriptionKey: "world.experience.overlay.ownership.description"
  },
  {
    id: "evidence",
    icon: "evidence",
    labelKey: "world.overlay.evidence",
    questionKey: "world.experience.overlay.evidence.question",
    descriptionKey: "world.experience.overlay.evidence.description"
  },
  {
    id: "quality",
    icon: "quality",
    labelKey: "world.overlay.quality",
    questionKey: "world.experience.overlay.quality.question",
    descriptionKey: "world.experience.overlay.quality.description"
  }
] as const satisfies readonly OverlayExperience[];

/**
 * Runtime availability comes from the operational registry. Presentation
 * metadata remains typed and localized here, but a view/overlay that was not
 * installed in the active kernel cannot leak into the navigator.
 */
export function registeredWorldViewExperiences(
  kernel: Pick<RegistryKernel, "views">
): readonly ViewExperience[] {
  const registered = new Set(kernel.views.values().map((entry) => entry.id));
  return WORLD_VIEW_EXPERIENCES.filter((entry) => registered.has(entry.id));
}

export function registeredWorldOverlayExperiences(
  kernel: Pick<RegistryKernel, "overlays">
): readonly OverlayExperience[] {
  const registered = new Set(kernel.overlays.values().map((entry) => entry.id));
  return WORLD_OVERLAY_EXPERIENCES.filter((entry) => registered.has(entry.id));
}

export const WORLD_QUADRANT_LENS_EXPERIENCES = [
  {
    id: "all",
    value: "all",
    labelKey: "world.experience.lens.all.label",
    descriptionKey: "world.experience.lens.all.description"
  },
  {
    id: "q1_intencao",
    value: "q1_intencao",
    labelKey: "world.experience.lens.q1.label",
    descriptionKey: "world.experience.lens.q1.description"
  },
  {
    id: "q2_pratica",
    value: "q2_pratica",
    labelKey: "world.experience.lens.q2.label",
    descriptionKey: "world.experience.lens.q2.description"
  },
  {
    id: "q3_relacoes",
    value: "q3_relacoes",
    labelKey: "world.experience.lens.q3.label",
    descriptionKey: "world.experience.lens.q3.description"
  },
  {
    id: "q4_sistemas",
    value: "q4_sistemas",
    labelKey: "world.experience.lens.q4.label",
    descriptionKey: "world.experience.lens.q4.description"
  }
] as const satisfies readonly QuadrantLensExperience[];

const nativeViews = new Set<string>(NATIVE_VIEWS);
const overlays = new Set<string>(OVERLAY_IDS);
const quadrantLenses = new Set<string>(QUADRANT_LENS_IDS);

export function isNativeWorldViewId(value: string): value is NativeWorldViewId {
  return nativeViews.has(value);
}

export function isWorldOverlayId(value: string): value is OverlayId {
  return overlays.has(value);
}

export function isQuadrantLensId(value: string | null | undefined): value is QuadrantLensId {
  return Boolean(value && quadrantLenses.has(value));
}

export function activeQuadrantLensOption(value: LensId | null | undefined): QuadrantLensOptionId {
  return isQuadrantLensId(value) ? value : "all";
}
