// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadCodexCapability } from "./snapshot";
import type { RuntimeConfig } from "./runtimeConfig";
import { operatorPost, resetOperatorSecurityForTests } from "../world/clients/operatorClient";

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
  resetOperatorSecurityForTests();
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

const health = (codex: Record<string, unknown> | null, nonce = "capability-current-nonce") => ({
  ok: true,
  json: async () => ({
    ok: true,
    repo: "t",
    server_version: "wiki_web_server.v6",
    schema_capabilities: [
      "operator_security_v2",
      "cors_default_deny_v1",
      "action_state_transitions_v1",
      "codex",
      "briefs"
    ],
    operator_security: {
      version: "wiki_operator_security.v2",
      nonce_header: "X-Wiki-Operator-Nonce",
      nonce,
      attempt_header: "X-Wiki-Attempt-Key",
      max_body_bytes: 1_048_576,
      mutations: "post_only",
      browser_origin_default: "deny",
      cors_opt_in: "exact_loopback_allowlist"
    },
    codex
  })
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

  it("keeps a v4/v1 process read-only, then re-verifies v6/v2 and emits one idempotent mutation", async () => {
    const usableCodex = {
      enabled: true,
      installed: true,
      runnable: true,
      authed: true,
      auth_mode: "chatgpt",
      version: "codex-cli current",
      usable: true,
      reason: ""
    };
    let restarted = false;
    const requests: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      requests.push({ url: String(url), init });
      if (String(url).includes("wiki-cockpit.config.json")) {
        return new Response(JSON.stringify({
          api_base: "/api",
          mode: "local_operator",
          codex: { enabled: true }
        }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (String(url).endsWith("/health")) {
        const payload = restarted
          ? await health(usableCodex, "nonce-after-restart").json()
          : {
              ok: true,
              server_version: "wiki_web_server.v4",
              schema_capabilities: ["operator_security_v1", "codex"],
              operator_security: {
                version: "wiki_operator_security.v1",
                nonce_header: "X-Wiki-Operator-Nonce",
                nonce: "nonce-before-restart",
                attempt_header: "X-Wiki-Attempt-Key",
                max_body_bytes: 1_048_576,
                mutations: "post_only"
              },
              codex: usableCodex
            };
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "content-type": "application/json" }
        });
      }
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" }
      });
    }));

    const stale = await loadCodexCapability(runtime());
    expect(stale.operator_outdated).toBe(true);
    expect(stale.reason).toContain("restart");
    await expect(operatorPost("/briefs", { mission: "blocked-before-restart" })).rejects.toThrow(/restart/);
    expect(requests.filter((request) => request.init?.method === "POST")).toHaveLength(0);

    restarted = true;
    const current = await loadCodexCapability(runtime());
    expect(current.operator_outdated).toBe(false);
    expect(current.usable).toBe(true);
    const response = await operatorPost("/briefs", { mission: "after-restart" });
    expect(response.ok).toBe(true);

    const posts = requests.filter((request) => request.init?.method === "POST");
    expect(posts).toHaveLength(1);
    const headers = new Headers(posts[0].init?.headers);
    expect(headers.get("X-Wiki-Operator-Nonce")).toBe("nonce-after-restart");
    expect(headers.get("X-Wiki-Attempt-Key")).toMatch(/^wiki-/);
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
