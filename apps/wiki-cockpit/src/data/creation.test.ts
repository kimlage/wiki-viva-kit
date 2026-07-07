// The palette honesty contract: create surfaces offer ONLY what can actually
// be born (creatable types), the scope's catalog first, never the root.

import { describe, expect, it } from "vitest";
import { curatedPalette, isCreatable } from "./creation";
import type { TemplateSpec } from "../types";

function spec(creatable?: boolean): TemplateSpec {
  return {
    page_type: "x",
    extends: null,
    body_template: "",
    pinned_fields: [],
    facets: {},
    view: {},
    controls: [],
    scene: {},
    ...(creatable === undefined ? {} : { creatable })
  };
}

describe("creation curation", () => {
  it("creatable defaults true (old snapshots) and false is respected", () => {
    expect(isCreatable("person", spec())).toBe(true);
    expect(isCreatable("system_log", spec(false))).toBe(false);
    expect(isCreatable("ghost", undefined)).toBe(false);
  });

  it("the root is rite-owned: never creatable from a palette, whatever the flag says", () => {
    expect(isCreatable("root_entity", spec(true))).toBe(false);
  });

  it("primary follows the catalog order and drops uncreatable entries; rest holds the tail", () => {
    const types: Record<string, TemplateSpec> = {
      person: spec(),
      decision: spec(),
      source: spec(),
      system_log: spec(false),
      root_entity: spec(),
      meeting: spec()
    };
    const palette = curatedPalette(types, ["source", "person", "system_log", "root_entity"]);
    expect(palette.primary).toEqual(["source", "person"]);
    expect(palette.rest.sort()).toEqual(["decision", "meeting"]);
    expect([...palette.primary, ...palette.rest]).not.toContain("system_log");
    expect([...palette.primary, ...palette.rest]).not.toContain("root_entity");
  });

  it("an empty catalog leaves everything creatable in rest (surfaces then expand by default)", () => {
    const palette = curatedPalette({ person: spec(), claim: spec() }, []);
    expect(palette.primary).toEqual([]);
    expect(palette.rest.length).toBe(2);
  });
});
