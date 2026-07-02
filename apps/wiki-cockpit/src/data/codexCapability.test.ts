// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadCodexCapability } from "./snapshot";
import type { RuntimeConfig } from "./runtimeConfig";

const runtime = (over: Partial<RuntimeConfig> = {}): RuntimeConfig => ({
  apiBase: "/api",
  snapshotBase: "",
  repoLabel: "",
  mode: "local_operator",
  language: "",
  strings: {},
  presentation: {},
  codexEnabled: true,
  ...over
});

let healthCalls = 0;
let healthResponse: () => { ok: boolean; status?: number; json?: () => Promise<unknown> };

beforeEach(() => {
  healthCalls = 0;
  healthResponse = () => ({ ok: false, status: 500 });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const u = String(url);
      if (u.includes("wiki-cockpit.config.json")) {
        return { ok: true, json: async () => ({ api_base: "/api", mode: "local_operator", codex: { enabled: true } }) };
      }
      if (u.includes("/health")) {
        healthCalls += 1;
        return healthResponse();
      }
      return { ok: false, status: 404 };
    })
  );
});

afterEach(() => vi.unstubAllGlobals());

const health = (codex: Record<string, unknown> | null, caps = ["codex", "briefs"]) => ({
  ok: true,
  json: async () => ({ ok: true, repo: "t", server_version: "wiki_web_server.v2", schema_capabilities: caps, codex })
});

describe("loadCodexCapability", () => {
  it("never hits the operator in demo mode — reports honestly", async () => {
    const cap = await loadCodexCapability(runtime({ mode: "static_demo" }));
    expect(cap.usable).toBe(false);
    expect(cap.reason).toContain("demo");
    expect(healthCalls).toBe(0);
  });

  it("never hits the operator when codex is disabled by config", async () => {
    const cap = await loadCodexCapability(runtime({ codexEnabled: false }));
    expect(cap.usable).toBe(false);
    expect(cap.enabled).toBe(false);
    expect(healthCalls).toBe(0);
  });

  it("passes a usable capability straight through the health payload", async () => {
    healthResponse = () =>
      health({
        enabled: true,
        installed: true,
        runnable: true,
        authed: true,
        auth_mode: "chatgpt",
        version: "codex-cli 0.142.5",
        usable: true,
        reason: ""
      });
    const cap = await loadCodexCapability(runtime());
    expect(healthCalls).toBe(1);
    expect(cap.usable).toBe(true);
    expect(cap.auth_mode).toBe("chatgpt");
    expect(cap.version).toBe("codex-cli 0.142.5");
  });

  it("reports operator_outdated when /api/health lacks the codex capability", async () => {
    // Old operator: no schema_capabilities, no codex block — the exact bug.
    healthResponse = () => ({ ok: true, json: async () => ({ ok: true, repo: "t" }) });
    const cap = await loadCodexCapability(runtime());
    expect(cap.usable).toBe(false);
    expect(cap.operator_outdated).toBe(true);
    expect(cap.reason).toContain("restart");
  });

  it("fails closed (not reachable) when health errors", async () => {
    healthResponse = () => ({ ok: false, status: 500 });
    const cap = await loadCodexCapability(runtime());
    expect(cap.usable).toBe(false);
    expect(cap.reason).toContain("not reachable");
  });

  it("fails closed when the operator reports an unusable record", async () => {
    healthResponse = () =>
      health({
        enabled: true,
        installed: true,
        runnable: false,
        authed: true,
        auth_mode: "chatgpt",
        version: null,
        usable: false,
        reason: "Codex is installed but not runnable: spawn ENOENT"
      });
    const cap = await loadCodexCapability(runtime());
    expect(cap.usable).toBe(false);
    expect(cap.installed).toBe(true);
    expect(cap.runnable).toBe(false);
    expect(cap.operator_outdated).toBe(false);
  });
});
