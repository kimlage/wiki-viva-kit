// The gating matrix: which instruments exist for which stacks. This is the
// contract the genesis tutorial rides on — stages differ only by data.

import { describe, expect, it } from "vitest";
import { composeInstruments, rootAnchor } from "./surfaces";
import type { AnchorRecord, SnapshotBundle } from "../types";

function bundleWith(options: {
  pages?: { id: string; page_type: string; path?: string; moc_parent?: string }[];
  anchors?: Record<string, Partial<AnchorRecord>>;
}): SnapshotBundle {
  const pages = (options.pages ?? []).map((page) => ({
    id: page.id,
    path: page.path ?? `memories/${page.id}.md`,
    title: page.id,
    page_type: page.page_type,
    context: "demo",
    visibility: "private_self",
    status: "",
    updated_at: "2026-07-01",
    stale_after_days: "30",
    freshness_state: "fresh",
    approved_state: "approved",
    risk_flags: [],
    source_refs: [],
    moc_parent: page.moc_parent ?? "",
    summary: ""
  }));
  const anchors: Record<string, AnchorRecord> = {};
  for (const [id, partial] of Object.entries(options.anchors ?? {})) {
    anchors[id] = {
      stack: partial.stack ?? [],
      interface: partial.interface ?? {
        views: { available: ["radar"], default: "radar" },
        missions: { active: false, providers: [], weather_contrib: false, quiet: false },
        create: { catalog: [], arrangement: "by_family", obligations_first: true, obligations: [], disabled_reason: "" },
        intake: { forms: [] },
        score: { loops: [], no_leaderboard: true },
        has_quadrants: false,
        has_relations: false
      },
      identity: partial.identity ?? { landmark: "", motif: "none", ambient: "none", horizon_label: "title", horizon_text: "", context: "demo" },
      derived: partial.derived ?? { missions: [], warnings: [] }
    };
  }
  return {
    pages: { pages },
    blockStacks: { schema_version: "wiki_web_block_stacks.v1", anchors },
    blocks: { schema_version: "wiki_web_blocks.v1", blocks: {} }
  } as unknown as SnapshotBundle;
}

const stackOf = (...ids: string[]) => ids.map((id) => ({ id, origin: "page", scope: "descendants", kind: "", config: {}, known: true }));

describe("composeInstruments", () => {
  it("an empty world has NO instruments at all (genesis stage 0)", () => {
    const instruments = composeInstruments(bundleWith({}));
    expect(instruments.worldEmpty).toBe(true);
    expect(instruments.destinations).toEqual([]);
    expect(instruments.searchEnabled).toBe(false);
    expect(instruments.missionsEnabled).toBe(false);
    expect(instruments.conditionEnabled).toBe(false);
  });

  it("chooses the top root_entity as the world root, not a nested company root", () => {
    const bundle = bundleWith({
      pages: [
        { id: "company-clearpath", page_type: "root_entity", path: "memories/empresas/clearpath.md", moc_parent: "memories/index.md" },
        { id: "root-alex", page_type: "root_entity", path: "memories/index.md", moc_parent: "" }
      ],
      anchors: {
        "company-clearpath": {},
        "root-alex": {}
      }
    });

    expect(rootAnchor(bundle)?.id).toBe("root-alex");
  });

  it("a bare root brings the laws + create/intake, radar home, NO missions, NO quadrant map", () => {
    const instruments = composeInstruments(
      bundleWith({
        pages: [{ id: "root-x", page_type: "root_entity" }],
        anchors: {
          "root-x": {
            stack: stackOf("wiki.block.privacy_boundary.v1", "wiki.block.git_human_gate.v1", "wiki.block.ui_views.v1", "wiki.block.ui_create.v1", "wiki.block.ui_intake.v1"),
            interface: {
              views: { available: ["atlas", "districts", "focus", "radar", "trails"], default: "radar" },
              missions: { active: false, providers: [], weather_contrib: false, quiet: false },
              create: { catalog: ["person"], arrangement: "by_family", obligations_first: true, obligations: [], disabled_reason: "" },
              intake: { forms: ["copy_file"] },
              score: { loops: [], no_leaderboard: true },
              has_quadrants: false,
              has_relations: false
            }
          }
        }
      })
    );
    expect(instruments.worldEmpty).toBe(false);
    expect(instruments.destinations).toEqual(["approve", "intake", "create", "blocks", "gates"]);
    expect(instruments.missionsEnabled).toBe(false);
    expect(instruments.defaultPerspective).toBe("radar");
    expect(instruments.perspectives).not.toContain("quadrants");
  });

  it("the quadrants block turns the map on and makes it home", () => {
    const instruments = composeInstruments(
      bundleWith({
        pages: [{ id: "root-x", page_type: "root_entity" }],
        anchors: {
          "root-x": {
            stack: stackOf("wiki.block.quadrants.v1", "wiki.block.ui_views.v1"),
            interface: {
              views: { available: ["atlas", "districts", "focus", "quadrants", "radar", "trails"], default: "quadrants" },
              missions: { active: false, providers: [], weather_contrib: false, quiet: false },
              create: { catalog: [], arrangement: "by_quadrant", obligations_first: true, obligations: [], disabled_reason: "" },
              intake: { forms: [] },
              score: { loops: [], no_leaderboard: true },
              has_quadrants: true,
              has_relations: false
            }
          }
        }
      })
    );
    expect(instruments.hasQuadrants).toBe(true);
    expect(instruments.defaultPerspective).toBe("quadrants");
    expect(instruments.perspectives).toContain("quadrants");
  });

  it("the gamification package turns missions + condition on (stage 4→5 payoff)", () => {
    const quiet = bundleWith({
      pages: [{ id: "root-x", page_type: "root_entity" }],
      anchors: { "root-x": { stack: stackOf("wiki.block.relations.v1") } }
    });
    expect(composeInstruments(quiet).missionsEnabled).toBe(false);

    const loud = bundleWith({
      pages: [{ id: "root-x", page_type: "root_entity" }],
      anchors: {
        "root-x": {
          stack: stackOf("wiki.block.relations.v1", "wiki.block.ui_missions.v1", "wiki.block.gamification.v1"),
          interface: {
            views: { available: ["radar"], default: "radar" },
            missions: { active: true, providers: ["stale", "relation_cadence_overdue"], weather_contrib: true, quiet: false },
            create: { catalog: [], arrangement: "by_family", obligations_first: true, obligations: [], disabled_reason: "" },
            intake: { forms: [] },
            score: { loops: ["mission_health"], no_leaderboard: true },
            has_quadrants: false,
            has_relations: true
          }
        }
      }
    });
    const instruments = composeInstruments(loud);
    expect(instruments.missionsEnabled).toBe(true);
    expect(instruments.conditionEnabled).toBe(true);
    expect(instruments.missionProviders).toContain("relation_cadence_overdue");
  });

  it("the Sources destination appears with the first source page", () => {
    const instruments = composeInstruments(
      bundleWith({
        pages: [
          { id: "root-x", page_type: "root_entity" },
          { id: "src-1", page_type: "source" }
        ],
        anchors: { "root-x": { stack: stackOf("wiki.block.ui_create.v1") } }
      })
    );
    expect(instruments.destinations).toContain("source");
  });
});
