// Read model over the declarative template registry (templates.json). The page
// TYPE drives view + interaction; this is the frontend accessor the reader,
// controls and (Phase 4) facet view read from. Degrades to a safe default when
// a snapshot has no registry (old wikis).

import type { PageContent, SnapshotBundle, TemplateSpec } from "../types";

const DEFAULT_SPEC: TemplateSpec = {
  page_type: "",
  extends: null,
  body_template: "",
  pinned_fields: [],
  facets: {},
  view: { center: "document", panels: [], badges: ["freshness"] },
  controls: [],
  scene: { shape: "sphere", emphasis: "none" }
};

export function templateSpec(bundle: SnapshotBundle, pageType: string): TemplateSpec {
  const spec = bundle.templates?.types?.[pageType];
  return spec ? { ...DEFAULT_SPEC, ...spec } : { ...DEFAULT_SPEC, page_type: pageType };
}

export function facetsOrder(bundle: SnapshotBundle): string[] {
  return bundle.templates?.facets_order ?? ["intencao", "pratica", "relacoes", "sistemas"];
}

export type PinnedFieldStatus = { field: string; present: boolean };

// Which of a type's pinned fields are actually filled on THIS page. A pinned
// field is "present" when its frontmatter value is non-empty. Drives the
// conformity read ("página fora do molde") without a server round-trip.
export function pinnedFieldStatus(spec: TemplateSpec, content: PageContent | null): PinnedFieldStatus[] {
  const fm = (content?.frontmatter ?? {}) as Record<string, unknown>;
  return spec.pinned_fields.map((field) => {
    const value = fm[field];
    const present =
      value !== undefined &&
      value !== null &&
      value !== "" &&
      !(Array.isArray(value) && value.length === 0);
    return { field, present };
  });
}

export function conforms(status: PinnedFieldStatus[]): boolean {
  return status.every((s) => s.present);
}
