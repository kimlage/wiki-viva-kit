import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../data/runtimeConfig", () => ({
  apiUrl: vi.fn(async (path: string) => `http://127.0.0.1:8765/api${path}`)
}));

import { operatorPost, resetOperatorSecurityForTests } from "./operatorClient";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" }
  });
}

function health(nonce: string) {
  return {
    ok: true,
    schema_capabilities: ["operator_security_v1"],
    operator_security: {
      version: "wiki_operator_security.v1",
      nonce_header: "X-Wiki-Operator-Nonce",
      nonce,
      attempt_header: "X-Wiki-Attempt-Key",
      max_body_bytes: 1_048_576,
      mutations: "post_only"
    }
  };
}

beforeEach(() => {
  resetOperatorSecurityForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("operatorPost", () => {
  it("caches the handshake and gives each logical mutation a unique attempt key", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (url.endsWith("/health")) return jsonResponse(health("nonce-a"));
      return jsonResponse({ ok: true });
    }));

    await operatorPost("/gates/run", { gate_id: "audit" });
    await operatorPost("/gates/run", { gate_id: "coverage" });

    expect(calls.filter((call) => call.url.endsWith("/health"))).toHaveLength(1);
    const posts = calls.filter((call) => call.init?.method === "POST");
    expect(posts).toHaveLength(2);
    const first = new Headers(posts[0].init?.headers).get("X-Wiki-Attempt-Key");
    const second = new Headers(posts[1].init?.headers).get("X-Wiki-Attempt-Key");
    expect(first).toMatch(/^wiki-/);
    expect(second).toMatch(/^wiki-/);
    expect(first).not.toBe(second);
    expect(new Headers(posts[0].init?.headers).get("X-Wiki-Operator-Nonce")).toBe("nonce-a");
  });

  it("re-handshakes after nonce rotation and retries with the same attempt key", async () => {
    const posts: RequestInit[] = [];
    let healthCount = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/health")) {
        healthCount += 1;
        return jsonResponse(health(healthCount === 1 ? "nonce-old" : "nonce-new"));
      }
      posts.push(init ?? {});
      return posts.length === 1 ? jsonResponse({ ok: false }, 403) : jsonResponse({ ok: true });
    }));

    const response = await operatorPost("/git/workflow", { operation: "status" });
    expect(response.ok).toBe(true);
    expect(healthCount).toBe(2);
    expect(posts).toHaveLength(2);
    expect(new Headers(posts[0].headers).get("X-Wiki-Attempt-Key")).toBe(
      new Headers(posts[1].headers).get("X-Wiki-Attempt-Key")
    );
    expect(new Headers(posts[1].headers).get("X-Wiki-Operator-Nonce")).toBe("nonce-new");
  });

  it("fails closed when the operator does not advertise the security contract", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ok: true, schema_capabilities: [] }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(operatorPost("/briefs", {})).rejects.toThrow("operator_security.v1");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rejects a body larger than the operator-advertised bound before POST", async () => {
    const fetchMock = vi.fn(async (url: string) =>
      jsonResponse({
        ...health("nonce-small"),
        operator_security: { ...health("nonce-small").operator_security, max_body_bytes: 8 }
      })
    );
    vi.stubGlobal("fetch", fetchMock);
    await expect(operatorPost("/briefs", { payload: "too large" })).rejects.toThrow("advertised 8 byte limit");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
