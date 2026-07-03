import { describe, expect, it } from "vitest";
import { computeCondition } from "./condition";
import type { SnapshotBundle } from "../types";

function bundle(over: Record<string, unknown>): SnapshotBundle {
  return {
    freshness: { summary: { fresh: 10, stale: 0, unknown: 0 } },
    gates: { status: "pass", gates: [] },
    diff: { files: [] },
    sourceEntities: { summary: { pending: 0 } },
    ...over
  } as unknown as SnapshotBundle;
}

describe("computeCondition — one honest selector", () => {
  it("clear when everything is fresh, no gates failing, nothing pending", () => {
    const c = computeCondition(bundle({}));
    expect(c.weather).toBe("clear");
    expect(c.freshRatio).toBe(1);
    expect(c.pendingApproval).toBe(0);
  });

  it("a failing gate DOMINATES → blocked, regardless of freshness", () => {
    const c = computeCondition(
      bundle({ gates: { status: "fail", gates: [{ id: "links", status: "fail" }, { id: "secrets", status: "pass" }] } })
    );
    expect(c.weather).toBe("blocked");
    expect(c.gatesFailing).toEqual(["links"]);
  });

  it("many unknown → unverified; much stale → aging (on fractions)", () => {
    expect(computeCondition(bundle({ freshness: { summary: { fresh: 5, stale: 0, unknown: 5 } } })).weather).toBe("unverified");
    expect(computeCondition(bundle({ freshness: { summary: { fresh: 7, stale: 3, unknown: 0 } } })).weather).toBe("aging");
  });

  it("pendingApproval counts ONLY local uncommitted memory edits, never the whole branch diff", () => {
    const c = computeCondition(
      bundle({
        diff: {
          files: [
            { category: "memory", change_sources: ["working_tree"] }, // counts
            { category: "memory", change_sources: ["staged"] }, // counts
            { category: "memory", change_sources: ["branch"] }, // committed on branch — does NOT count
            { category: "code", change_sources: ["working_tree"] } // not memory — does NOT count
          ]
        }
      })
    );
    expect(c.pendingApproval).toBe(2);
  });

  it("no field can be non-zero without a real count (agentsActive is an explicit input)", () => {
    const c = computeCondition(bundle({ sourceEntities: { summary: { pending: 3 } } }), 2);
    expect(c.pendingSourceIntake).toBe(3);
    expect(c.agentsActive).toBe(2);
  });
});
