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

let capCalls = 0;
let capResponse: () => { ok: boolean; status?: number; statusText?: string; json?: () => Promise<unknown> };

beforeEach(() => {
  capCalls = 0;
  capResponse = () => ({ ok: false, status: 500, statusText: "unset" });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const u = String(url);
      if (u.includes("wiki-cockpit.config.json")) {
        return { ok: true, json: async () => ({ api_base: "/api", mode: "local_operator", codex: { enabled: true } }) };
      }
      if (u.includes("/codex/capability")) {
        capCalls += 1;
        return capResponse();
      }
      return { ok: false, status: 404, statusText: "not found" };
    })
  );
});

afterEach(() => vi.unstubAllGlobals());

describe("loadCodexCapability", () => {
  it("never hits the operator in demo mode — reports honestly", async () => {
    const cap = await loadCodexCapability(runtime({ mode: "static_demo" }));
    expect(cap.usable).toBe(false);
    expect(cap.reason).toContain("demo");
    expect(capCalls).toBe(0);
  });

  it("never hits the operator when codex is disabled by config", async () => {
    const cap = await loadCodexCapability(runtime({ codexEnabled: false }));
    expect(cap.usable).toBe(false);
    expect(cap.enabled).toBe(false);
    expect(capCalls).toBe(0);
  });

  it("passes a usable capability straight through", async () => {
    capResponse = () => ({
      ok: true,
      json: async () => ({
        enabled: true,
        installed: true,
        runnable: true,
        authed: true,
        auth_mode: "chatgpt",
        version: "codex-cli 0.99.0",
        usable: true,
        reason: ""
      })
    });
    const cap = await loadCodexCapability(runtime());
    expect(capCalls).toBe(1);
    expect(cap.usable).toBe(true);
    expect(cap.auth_mode).toBe("chatgpt");
    expect(cap.version).toBe("codex-cli 0.99.0");
  });

  it("fails closed (never fakes availability) on a 500", async () => {
    capResponse = () => ({ ok: false, status: 500, statusText: "boom" });
    const cap = await loadCodexCapability(runtime());
    expect(cap.usable).toBe(false);
    expect(cap.reason).toContain("500");
  });

  it("fails closed when the operator returns an unusable record", async () => {
    capResponse = () => ({
      ok: true,
      json: async () => ({
        enabled: true,
        installed: true,
        runnable: false,
        authed: true,
        auth_mode: "chatgpt",
        version: null,
        usable: false,
        reason: "Codex is installed but not runnable: spawn ENOENT"
      })
    });
    const cap = await loadCodexCapability(runtime());
    expect(cap.usable).toBe(false);
    expect(cap.installed).toBe(true);
    expect(cap.runnable).toBe(false);
  });
});
