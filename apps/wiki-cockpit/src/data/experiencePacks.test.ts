import { afterEach, describe, expect, it } from "vitest";
import type { ExperiencePackComposition, PageRecord } from "../types";
import {
  experiencePackLabel,
  experiencePackView,
  humanizePackIdentifier,
  pageBelongsToExperiencePack,
  pagesForExperiencePack,
  slotsForExperiencePack
} from "./experiencePacks";
import { configureLanguage } from "./i18n";

afterEach(() => configureLanguage("en"));

const composition: ExperiencePackComposition = {
  schema_version: "wiki_experience_pack_composition.v1",
  core_version: "8.0.0",
  packs: [{ id: "example-pack", version: "1.2.3" }],
  block_packages: ["quadrant_lenses"],
  slots: {
    views: [{ pack: "example-pack", slot: "view.map", contribution: "example-pack.reference-map", mode: "append" }],
    commands: [{ pack: "example-pack", slot: "command.capture", contribution: "example-pack.capture", mode: "append" }],
    operations: [],
    timelines: [{ pack: "example-pack", slot: "timeline.history", contribution: "example-pack.history", mode: "append" }]
  },
  presentation: {
    default_locale: "en",
    locales: {
      en: {
        "example-pack": "Example Pack",
        "example-pack.capture": "Capture",
        "example-pack.history": "History",
        "example-pack.reference-map": "Reference Map"
      },
      es: {
        "example-pack": "Paquete de ejemplo",
        "example-pack.capture": "Capturar",
        "example-pack.history": "Historial",
        "example-pack.reference-map": "Mapa de referencias"
      },
      "pt-BR": {
        "example-pack": "Pack de Exemplo",
        "example-pack.capture": "Capturar",
        "example-pack.history": "Histórico",
        "example-pack.reference-map": "Mapa de Referências"
      }
    }
  },
  composition_sha256: "0".repeat(64)
};

function page(id: string, pageType: string, title = id): PageRecord {
  return {
    id,
    path: `memories/${id}.md`,
    title,
    page_type: pageType,
    context: "demo",
    visibility: "public",
    status: "active",
    updated_at: "2026-07-11",
    stale_after_days: "90",
    freshness_state: "fresh",
    approved_state: "approved",
    risk_flags: [],
    source_refs: [],
    moc_parent: "",
    summary: "Synthetic evidence."
  };
}

describe("experience pack presentation", () => {
  it("resolves namespaced views and groups slots without knowing a vertical", () => {
    expect(experiencePackView(composition, "example-pack.reference-map")?.slot).toBe("view.map");
    expect(experiencePackView(composition, "other.reference-map")).toBeUndefined();
    expect(slotsForExperiencePack(composition, "example-pack").commands).toHaveLength(1);
    expect(slotsForExperiencePack(composition, "other").views).toEqual([]);
  });

  it("derives canonical pack pages from the portable page-type namespace", () => {
    const pages = [
      page("two", "example_pack_claim", "Beta"),
      page("one", "example_pack_source", "Alpha"),
      page("core", "decision")
    ];
    expect(pageBelongsToExperiencePack(pages[0], "example-pack")).toBe(true);
    expect(pageBelongsToExperiencePack(pages[2], "example-pack")).toBe(false);
    expect(pagesForExperiencePack(pages, "example-pack").map((item) => item.id)).toEqual(["one", "two"]);
  });

  it("humanizes identifiers without shipping pack-specific copy", () => {
    expect(humanizePackIdentifier("example-pack.reference-map", "example-pack")).toBe("Reference Map");
    expect(humanizePackIdentifier("example_pack_research_source", "example-pack")).toBe("Research Source");
    expect(humanizePackIdentifier("monthly_closing-tape")).toBe("Monthly Closing Tape");
  });

  it("projects the verified pack catalog in the active language with a safe fallback", () => {
    expect(experiencePackLabel(composition, "example-pack.reference-map", "example-pack")).toBe("Reference Map");
    configureLanguage("pt-BR");
    expect(experiencePackLabel(composition, "example-pack.reference-map", "example-pack")).toBe("Mapa de Referências");
    configureLanguage("es");
    expect(experiencePackLabel(composition, "example-pack.reference-map", "example-pack")).toBe("Mapa de referencias");
    expect(experiencePackLabel(composition, "example_pack_unknown", "example-pack")).toBe("Unknown");
  });
});
