import { describe, expect, it } from "vitest";
import { conforms, facetsOrder, pinnedFieldStatus, templateSpec } from "./templates";
import type { PageContent, SnapshotBundle, TemplateSpec } from "../types";

const spec: TemplateSpec = {
  page_type: "meeting",
  extends: "relation_base",
  body_template: "docs/references/templates/wiki/meeting.md",
  pinned_fields: ["updated_at", "participants", "decisions"],
  facets: { intencao: ["decisions"], relacoes: ["participants"] },
  view: { center: "timeline", panels: [], badges: ["freshness"] },
  controls: [{ kind: "focus" }],
  scene: { shape: "slab", emphasis: "relations" }
};

const bundle = {
  templates: { schema_version: "wiki_templates.v1", facets_order: ["intencao", "pratica", "relacoes", "sistemas"], types: { meeting: spec } }
} as unknown as SnapshotBundle;

const content = (fm: Record<string, unknown>): PageContent => ({ frontmatter: fm } as unknown as PageContent);

describe("templates read model", () => {
  it("resolves a spec, falls back to a safe default for unknown types", () => {
    expect(templateSpec(bundle, "meeting").view.center).toBe("timeline");
    const unknown = templateSpec(bundle, "nope");
    expect(unknown.view.center).toBe("document");
    expect(unknown.scene.shape).toBe("sphere");
  });

  it("flags a page in/out of its mold by pinned fields", () => {
    const full = pinnedFieldStatus(spec, content({ updated_at: "2026-07-03", participants: ["a"], decisions: ["d"] }));
    expect(conforms(full)).toBe(true);
    const partial = pinnedFieldStatus(spec, content({ updated_at: "2026-07-03", participants: [] }));
    expect(conforms(partial)).toBe(false);
    expect(partial.find((s) => s.field === "participants")?.present).toBe(false);
    expect(partial.find((s) => s.field === "decisions")?.present).toBe(false);
  });

  it("empty content = every pinned field missing (never crashes)", () => {
    const status = pinnedFieldStatus(spec, null);
    expect(status.every((s) => !s.present)).toBe(true);
  });

  it("exposes the facet order with a safe default", () => {
    expect(facetsOrder(bundle)).toEqual(["intencao", "pratica", "relacoes", "sistemas"]);
    expect(facetsOrder({} as SnapshotBundle)[0]).toBe("intencao");
  });
});
