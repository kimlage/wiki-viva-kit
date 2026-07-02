import { describe, expect, it } from "vitest";
import { deriveApproval, gateFixSpec, trimGateOutput } from "./approval";
import type { DiffFile, SnapshotBundle } from "../types";

const file = (path: string, category: string, over: Partial<DiffFile> = {}): DiffFile => ({
  path,
  status: "M",
  category,
  change_sources: ["branch"],
  additions: 1,
  deletions: 0,
  known_generated: false,
  staged: false,
  unstaged: true,
  risk_hints: [],
  preview: [],
  ...over
});

const bundle = (files: DiffFile[], git: Partial<SnapshotBundle["git"]["proposal"]> = {}, gateStatus = "not_run"): SnapshotBundle =>
  ({
    diff: { files },
    git: { proposal: { is_proposal_branch: true, theme: "x", draft_pr_url: null, human_gate_state: "", ...git } },
    gates: { status: gateStatus, gates: [] }
  } as unknown as SnapshotBundle);

describe("deriveApproval", () => {
  it("separates content pages from the code crate", () => {
    const view = deriveApproval(
      bundle([file("memories/a.md", "memory"), file("wiki_core/x.py", "core"), file("apps/wiki-cockpit/y.ts", "web_cockpit")])
    );
    expect(view.contentFiles.map((f) => f.path)).toEqual(["memories/a.md"]);
    expect(view.codeFiles.length).toBe(2);
    expect(view.fileCount).toBe(3);
  });

  it("is clean when nothing changed", () => {
    expect(deriveApproval(bundle([])).decision).toBe("clean");
  });

  it("says ready when changes exist and no PR yet", () => {
    expect(deriveApproval(bundle([file("memories/a.md", "memory")])).decision).toBe("ready");
  });

  it("says review once a draft PR is open", () => {
    const view = deriveApproval(bundle([file("memories/a.md", "memory")], { draft_pr_url: "https://x/pull/1" }));
    expect(view.decision).toBe("review");
    expect(view.prUrl).toContain("/pull/1");
  });

  it("a red gate blocks readiness even with an open PR", () => {
    const view = deriveApproval(bundle([file("memories/a.md", "memory")], { draft_pr_url: "https://x/pull/1" }, "fail"));
    expect(view.decision).toBe("checks");
  });

  it("surfaces only genuine privacy files", () => {
    const view = deriveApproval(
      bundle([file("memories/publico/a.md", "memory", { risk_hints: ["public_boundary"] }), file("memories/b.md", "memory")])
    );
    expect(view.privacyFiles.map((f) => f.path)).toEqual(["memories/publico/a.md"]);
  });
});

describe("gateFixSpec", () => {
  it("composes a verify brief that carries the failure evidence", () => {
    const spec = gateFixSpec({ id: "wiki_audit", argv: ["python3", "scripts/wiki_audit.py", "--check"] }, "E: broken link");
    expect(spec.mission_kind).toBe("verify");
    expect(spec.theme).toBe("fix-wiki-audit");
    expect(spec.grounding.state_report).toEqual({ scope: "audit" });
    expect(spec.intent).toContain("python3 scripts/wiki_audit.py --check");
    expect(spec.intent).toContain("E: broken link");
    // The contract line: never game the check.
    expect(spec.intent).toContain("never weaken or skip the check");
  });

  it("asks Codex to reproduce first when no output was captured", () => {
    const spec = gateFixSpec({ id: "pytest", argv: ["python3", "-m", "pytest", "tests/"] });
    expect(spec.intent).toContain("Run the command first");
  });
});

describe("trimGateOutput", () => {
  it("keeps the tail — verdicts print last", () => {
    const long = Array.from({ length: 500 }, (_, i) => `line ${i}`).join("\n");
    const trimmed = trimGateOutput(long, "", 200);
    expect(trimmed.startsWith("…")).toBe(true);
    expect(trimmed).toContain("line 499");
    expect(trimmed.length).toBeLessThanOrEqual(202);
  });

  it("merges stdout and stderr with a divider", () => {
    expect(trimGateOutput("out", "err")).toBe("out\n--- stderr ---\nerr");
    expect(trimGateOutput("out", "")).toBe("out");
  });
});
