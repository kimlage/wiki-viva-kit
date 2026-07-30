import { describe, expect, it } from "vitest";
import {
  INITIAL_PROTOTYPE_SESSION,
  prototypeReducer,
  type PrototypeAction
} from "../../../labs/anatta-worlds/model";

function run(actions: PrototypeAction[]) {
  return actions.reduce(prototypeReducer, INITIAL_PROTOTYPE_SESSION);
}

describe("Anatta Worlds comparable prototype state", () => {
  it("does not commit a localized mutation before a receipt", () => {
    const beforeGate = run([
      { type: "show_diff" },
      { type: "focus_tension" },
      { type: "open_mission" },
      { type: "choose_mission", choice: "do" },
      { type: "return_evidence" },
      { type: "review_agent_proposal" },
      { type: "open_gate" },
      { type: "commit_mutation" }
    ]);

    expect(beforeGate.phase).toBe("human_gate");
    expect(beforeGate.receipt).toBeNull();
    expect(beforeGate.mutationCommitted).toBe(false);
  });

  it("emits the canonical partial receipt before changing only the East bed", () => {
    const receipt = run([
      { type: "show_diff" },
      { type: "focus_tension" },
      { type: "set_lens", lens: "hydrology" },
      { type: "set_lens", lens: "climate" },
      { type: "set_lens", lens: "compare" },
      { type: "open_mission" },
      { type: "choose_mission", choice: "do" },
      { type: "return_evidence" },
      { type: "review_agent_proposal" },
      { type: "open_gate" },
      { type: "decide_claim", claimId: "east_watered", decision: "accept" },
      { type: "decide_claim", claimId: "east_recovering", decision: "correct" },
      { type: "decide_claim", claimId: "whole_garden_resolved", decision: "reject" },
      { type: "emit_receipt" }
    ]);

    expect(receipt.phase).toBe("receipt_issued");
    expect(receipt.mutationCommitted).toBe(false);
    expect(receipt.receipt).toMatchObject({
      receiptId: "receipt.aurora-001",
      decision: "partial_accept",
      mutation: {
        entityId: "entity.bed-east",
        dataRef: "snapshot.return"
      }
    });

    const committed = prototypeReducer(receipt, { type: "commit_mutation" });
    expect(committed.phase).toBe("mutation_committed");
    expect(committed.mutationCommitted).toBe(true);
    expect(committed.selectedId).toBe("entity.bed-east");
  });

  it.each([
    ["ask_evidence", "pending_evidence"],
    ["compost", "composted"]
  ] as const)("%s produces an honest no-mutation receipt", (choice, decision) => {
    const session = run([
      { type: "show_diff" },
      { type: "focus_tension" },
      { type: "open_mission" },
      { type: "choose_mission", choice }
    ]);

    expect(session.receipt?.decision).toBe(decision);
    expect(session.receipt?.mutation).toBeNull();
    expect(prototypeReducer(session, { type: "commit_mutation" }).mutationCommitted).toBe(false);
  });

  it("blocks agent delegation under proposal-only grant", () => {
    const session = run([
      { type: "show_diff" },
      { type: "focus_tension" },
      { type: "open_mission" },
      { type: "choose_mission", choice: "delegate" }
    ]);

    expect(session.phase).toBe("mission_selected");
    expect(session.notice).toContain("Bloqueado pelo grant");
    expect(session.receipt).toBeNull();
  });

  it("resets without persistence", () => {
    const changed = prototypeReducer(INITIAL_PROTOTYPE_SESSION, { type: "show_diff" });
    expect(prototypeReducer(changed, { type: "reset" })).toEqual(INITIAL_PROTOTYPE_SESSION);
  });
});
