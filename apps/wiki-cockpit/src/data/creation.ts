// Creation curation — the one answer to "what can be born HERE, and in what
// order?". Every create surface (the spatial seeder, the fallback sheet) reads
// this instead of dumping the registry: only creatable types are offered
// (creatable=false marks generated/system/rite-owned types), the scope's
// catalog is the small first level, and everything else waits behind an
// explicit expansion. Never a flat alphabetical dump of the database.

import { pageTypeLabel } from "./presentation";
import { SCENE_FACETS } from "../scene/facets";
import type { SceneFacet } from "../scene/facets";
import type { BriefSpec, SnapshotBundle, TemplateSpec } from "../types";

export type CuratedPalette = {
  // The scope's catalog (ui_create.catalog), creatable-filtered, catalog order.
  primary: string[];
  // Every other creatable type — shown only behind "more types…".
  rest: string[];
};

// Can a human seed this type from a create surface? Old snapshots without the
// flag stay fully creatable (back-compat); the root is rite-owned either way.
export function isCreatable(pageType: string, spec: TemplateSpec | undefined): boolean {
  if (!spec) return false;
  if (pageType === "root_entity") return false;
  return spec.creatable !== false;
}

export function creatableTypes(types: Record<string, TemplateSpec>): string[] {
  return Object.keys(types).filter((pageType) => isCreatable(pageType, types[pageType]));
}

export function curatedPalette(types: Record<string, TemplateSpec>, catalog: string[]): CuratedPalette {
  const creatable = new Set(creatableTypes(types));
  const primary = catalog.filter((pageType) => creatable.has(pageType));
  const primarySet = new Set(primary);
  const rest = [...creatable]
    .filter((pageType) => !primarySet.has(pageType))
    .sort((a, b) => pageTypeLabel(a).localeCompare(pageTypeLabel(b)));
  return { primary, rest };
}

// The wiki's areas, straight from the compiled freshness rollup — the one list
// every create/intake surface offers as a destination. Sorted for stable UI.
export function contextsOf(bundle: SnapshotBundle): string[] {
  return Object.keys(bundle.freshness?.by_context ?? {}).sort();
}

// Per-type `home_quadrant:` overrides from the template registry (a wiki can
// pin a custom type into a specific quadrant). Only valid facets are kept.
// The ONE home for this map — the sheet and the spatial seeder both read it.
export function registryHomeOverrides(types: Record<string, TemplateSpec>): Record<string, SceneFacet | null> {
  const out: Record<string, SceneFacet | null> = {};
  for (const [pageType, spec] of Object.entries(types)) {
    const raw = (spec as { home_quadrant?: string | null }).home_quadrant;
    if (raw && (SCENE_FACETS as readonly string[]).includes(raw)) out[pageType] = raw as SceneFacet;
  }
  return out;
}

// Fields the SYSTEM fills — never asked of a human at creation time.
export const AUTO_FIELDS = new Set([
  "updated_at",
  "stale_after_days",
  "page_id",
  "page_type",
  "context",
  "template_ref",
  "template_overlay"
]);

// The one shape every create surface hands to the brief composer.
export function createBriefSpec(options: {
  pageType: string;
  title: string;
  context: string;
  home: SceneFacet | null;
  pinned?: { key: string; label?: string; value?: string; required?: boolean }[];
}): BriefSpec {
  return {
    mission_kind: "create",
    theme: `new-${options.pageType}`,
    grounding: {
      attach_context_package: true,
      create: {
        page_type: options.pageType,
        title: options.title,
        context: options.context,
        home_facet: options.home,
        pinned: options.pinned ?? []
      }
    }
  };
}
