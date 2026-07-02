import { describe, expect, it } from "vitest";
import { blockingRung, codexLadder } from "./codexLadder";
import { CODEX_UNAVAILABLE } from "../types";
import type { CodexCapability } from "../types";

const cap = (over: Partial<CodexCapability>): CodexCapability => ({ ...CODEX_UNAVAILABLE, ...over });

describe("codexLadder", () => {
  it("marks operator restart as the blocker when the operator is outdated", () => {
    const rungs = codexLadder(cap({ operator_outdated: true, enabled: true }));
    expect(rungs[0]).toEqual({ id: "operator", state: "blocked" });
    // Everything after the blocker is pending (can't be judged yet).
    expect(rungs.slice(1).every((r) => r.state === "pending")).toBe(true);
    expect(blockingRung(cap({ operator_outdated: true }))).toBe("operator");
  });

  it("blocks on install when enabled but not installed", () => {
    const rungs = codexLadder(cap({ enabled: true, installed: false }));
    expect(rungs.find((r) => r.id === "operator")?.state).toBe("ok");
    expect(rungs.find((r) => r.id === "enabled")?.state).toBe("ok");
    expect(rungs.find((r) => r.id === "installed")?.state).toBe("blocked");
    expect(blockingRung(cap({ enabled: true, installed: false }))).toBe("installed");
  });

  it("blocks on runnable (the real broken-binary case)", () => {
    const rungs = codexLadder(cap({ enabled: true, installed: true, runnable: false, authed: true }));
    expect(rungs.find((r) => r.id === "runnable")?.state).toBe("blocked");
  });

  it("blocks on login when installed+runnable but not authed", () => {
    expect(blockingRung(cap({ enabled: true, installed: true, runnable: true, authed: false }))).toBe("authed");
  });

  it("has no blocker and a green ready rung when usable", () => {
    const rungs = codexLadder(
      cap({ enabled: true, installed: true, runnable: true, authed: true, usable: true })
    );
    expect(rungs.every((r) => r.state === "ok")).toBe(true);
    expect(blockingRung(cap({ enabled: true, installed: true, runnable: true, authed: true, usable: true }))).toBeNull();
  });

  it("blocks on enabled first when the wiki turned codex off", () => {
    expect(blockingRung(cap({ enabled: false }))).toBe("enabled");
  });
});
