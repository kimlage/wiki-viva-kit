import type {
  ExperiencePackComposition,
  ExperiencePackSlot,
  PageRecord
} from "../types";
import { uiLanguage } from "./i18n";

export function humanizePackIdentifier(value: string, packId?: string): string {
  const pageTypePrefix = packId ? `${packId.replace(/[^a-z0-9]+/gi, "_")}_` : "";
  const prefix = packId && value.startsWith(`${packId}.`)
    ? value.slice(packId.length + 1)
    : pageTypePrefix && value.startsWith(pageTypePrefix)
      ? value.slice(pageTypePrefix.length)
      : value;
  return prefix
    .replace(/[._-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .trim();
}

export function experiencePackLabel(
  composition: ExperiencePackComposition | undefined,
  identifier: string,
  packId?: string
): string {
  const locale = uiLanguage() === "pt" ? "pt-BR" : "en";
  const presentation = composition?.presentation;
  return presentation?.locales[locale]?.[identifier]
    ?? presentation?.locales[presentation.default_locale]?.[identifier]
    ?? humanizePackIdentifier(identifier, packId);
}

export function experiencePackView(
  composition: ExperiencePackComposition | undefined,
  contribution: string
): ExperiencePackSlot | undefined {
  if (!composition || !contribution) return undefined;
  return composition.slots.views.find((slot) => slot.contribution === contribution);
}

export function experiencePackVersion(
  composition: ExperiencePackComposition,
  packId: string
): string | undefined {
  return composition.packs.find((pack) => pack.id === packId)?.version;
}

/**
 * Pack page types are namespaced by the portable pack id. The workbench uses
 * that public contract instead of knowing any vertical (finance, study, etc.).
 */
export function pageBelongsToExperiencePack(page: PageRecord, packId: string): boolean {
  const namespace = packId.replace(/[^a-z0-9]+/gi, "_").replace(/^_+|_+$/g, "").toLowerCase();
  const pageType = page.page_type.toLowerCase();
  return Boolean(namespace && (pageType === namespace || pageType.startsWith(`${namespace}_`)));
}

export function pagesForExperiencePack(pages: PageRecord[], packId: string): PageRecord[] {
  return pages
    .filter((page) => pageBelongsToExperiencePack(page, packId))
    .sort((left, right) => left.title.localeCompare(right.title) || left.id.localeCompare(right.id));
}

export function slotsForExperiencePack(
  composition: ExperiencePackComposition,
  packId: string
): ExperiencePackComposition["slots"] {
  return {
    views: composition.slots.views.filter((slot) => slot.pack === packId),
    commands: composition.slots.commands.filter((slot) => slot.pack === packId),
    operations: composition.slots.operations.filter((slot) => slot.pack === packId),
    timelines: composition.slots.timelines.filter((slot) => slot.pack === packId)
  };
}
