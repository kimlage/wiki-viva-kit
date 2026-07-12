import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../data/runtimeConfig", () => ({
  apiUrl: vi.fn(async (path: string) => `http://127.0.0.1:8765/api${path}`)
}));

import { apiUrl } from "../../data/runtimeConfig";
import { fetchOperatorHealth, operatorPost, operatorRequest, resetOperatorSecurityForTests } from "./operatorClient";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" }
  });
}

function health(nonce: string) {
  return {
    ok: true,
    server_version: "wiki_web_server.v6",
    schema_capabilities: [
      "operator_security_v2",
      "cors_default_deny_v1",
      "action_state_transitions_v1"
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
    }
  };
}

beforeEach(() => {
  resetOperatorSecurityForTests();
  vi.mocked(apiUrl).mockReset();
  vi.mocked(apiUrl).mockImplementation(async (path: string) => `http://127.0.0.1:8765/api${path}`);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("operatorPost", () => {
  it("blocks every demo read before config resolution or transport", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("location", { pathname: "/demo/world" });
    vi.stubGlobal("fetch", fetchMock);

    await expect(operatorRequest("/briefs", { method: "GET" })).rejects.toThrow(/read-only demo/);
    expect(apiUrl).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps the legacy ?demo=1 synthetic switch behind the same operator boundary", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("location", { pathname: "/w/radar", search: "?demo=1" });
    vi.stubGlobal("fetch", fetchMock);

    await expect(operatorRequest("/health", { method: "GET" })).rejects.toThrow(/read-only demo/);
    await expect(operatorPost("/briefs", {})).rejects.toThrow(/read-only demo/);
    expect(apiUrl).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("revalidates a read after delayed apiUrl resolution and before GET", async () => {
    const liveLocation = { pathname: "/w/radar" };
    const fetchMock = vi.fn();
    vi.stubGlobal("location", liveLocation);
    vi.stubGlobal("fetch", fetchMock);
    vi.mocked(apiUrl).mockImplementationOnce(async (path: string) => {
      liveLocation.pathname = "/demo/world";
      return `http://127.0.0.1:8765/operator${path}`;
    });

    await expect(operatorRequest("/codex/jobs", { method: "GET" })).rejects.toThrow(/read-only demo/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("blocks every demo mutation before a handshake or POST", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("location", { pathname: "/demo/world" });
    vi.stubGlobal("fetch", fetchMock);

    await expect(operatorPost("/briefs", { mission: "preview" })).rejects.toThrow(/read-only demo/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("revalidates live-to-demo navigation after the async handshake and before POST", async () => {
    const liveLocation = { pathname: "/w/radar" };
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal("location", liveLocation);
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (url.endsWith("/health")) {
        liveLocation.pathname = "/demo/world";
        return jsonResponse(health("nonce-crossed"));
      }
      return jsonResponse({ ok: true });
    }));

    await expect(operatorPost("/briefs", { mission: "crossing" })).rejects.toThrow(/read-only demo/);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toMatch(/\/health$/);
    expect(calls.some((call) => call.init?.method === "POST")).toBe(false);
  });

  it("never re-handshakes or retries a 403 after the route crosses into demo", async () => {
    const liveLocation = { pathname: "/w/radar" };
    let healthCount = 0;
    let postCount = 0;
    vi.stubGlobal("location", liveLocation);
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/health")) {
        healthCount += 1;
        return jsonResponse(health("nonce-before-crossing"));
      }
      if (init?.method === "POST") {
        postCount += 1;
        liveLocation.pathname = "/demo/world";
        return jsonResponse({ ok: false }, 403);
      }
      return jsonResponse({ ok: true });
    }));

    await expect(operatorPost("/gates/run", { gate_id: "audit" })).rejects.toThrow(/read-only demo/);
    expect(healthCount).toBe(1);
    expect(postCount).toBe(1);
  });

  it("propagates AbortSignal through the health handshake", async () => {
    const controller = new AbortController();
    const calls: RequestInit[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      calls.push(init ?? {});
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
      });
    }));

    const pending = operatorPost("/briefs", { mission: "cancelled" }, { signal: controller.signal });
    await vi.waitFor(() => expect(calls).toHaveLength(1));
    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(calls[0].signal).toBe(controller.signal);
    expect(calls.some((init) => init.method === "POST")).toBe(false);
  });

  it("fails a health read closed when delayed resolution crosses into demo", async () => {
    const liveLocation = { pathname: "/w/radar" };
    const fetchMock = vi.fn();
    vi.stubGlobal("location", liveLocation);
    vi.stubGlobal("fetch", fetchMock);
    vi.mocked(apiUrl).mockImplementationOnce(async (path: string) => {
      liveLocation.pathname = "/demo/world";
      return `http://127.0.0.1:8765/operator${path}`;
    });

    await expect(fetchOperatorHealth()).resolves.toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

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
    const handshakes: RequestInit[] = [];
    const controller = new AbortController();
    let healthCount = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/health")) {
        healthCount += 1;
        handshakes.push(init ?? {});
        return jsonResponse(health(healthCount === 1 ? "nonce-old" : "nonce-new"));
      }
      posts.push(init ?? {});
      return posts.length === 1 ? jsonResponse({ ok: false }, 403) : jsonResponse({ ok: true });
    }));

    const response = await operatorPost("/git/workflow", { operation: "status" }, { signal: controller.signal });
    expect(response.ok).toBe(true);
    expect(healthCount).toBe(2);
    expect(posts).toHaveLength(2);
    expect(handshakes.every((init) => init.signal === controller.signal)).toBe(true);
    expect(posts.every((init) => init.signal === controller.signal)).toBe(true);
    expect(new Headers(posts[0].headers).get("X-Wiki-Attempt-Key")).toBe(
      new Headers(posts[1].headers).get("X-Wiki-Attempt-Key")
    );
    expect(new Headers(posts[1].headers).get("X-Wiki-Operator-Nonce")).toBe("nonce-new");
  });

  it("fails closed when the operator does not advertise the security contract", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ok: true, schema_capabilities: [] }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(operatorPost("/briefs", {})).rejects.toThrow(/outdated.*restart.*wiki_operator_security\.v2/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rejects a running v1 operator and asks for a restart before any mutation", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        ok: true,
        server_version: "wiki_web_server.v4",
        schema_capabilities: ["operator_security_v1"],
        operator_security: {
          version: "wiki_operator_security.v1",
          nonce_header: "X-Wiki-Operator-Nonce",
          nonce: "legacy-nonce",
          attempt_header: "X-Wiki-Attempt-Key",
          max_body_bytes: 1_048_576,
          mutations: "post_only"
        }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(operatorPost("/gates/run", { gate_id: "audit" })).rejects.toThrow(
      /wiki_operator_security\.v1.*restart.*wiki_operator_security\.v2/
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rejects a handshake that omits the explicit default-deny CORS capability", async () => {
    const incomplete = health("nonce-without-cors-capability");
    incomplete.schema_capabilities = ["operator_security_v2", "action_state_transitions_v1"];
    const fetchMock = vi.fn(async () => jsonResponse(incomplete));
    vi.stubGlobal("fetch", fetchMock);

    await expect(operatorPost("/briefs", {})).rejects.toThrow(/outdated.*restart/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rejects a v4 server even if it claims the new security capabilities", async () => {
    const stale = health("nonce-from-v4");
    stale.server_version = "wiki_web_server.v4";
    const fetchMock = vi.fn(async () => jsonResponse(stale));
    vi.stubGlobal("fetch", fetchMock);

    await expect(operatorPost("/briefs", {})).rejects.toThrow(/outdated.*restart/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rejects a handshake without the domain-action transition boundary", async () => {
    const incomplete = health("nonce-without-action-transition");
    incomplete.schema_capabilities = ["operator_security_v2", "cors_default_deny_v1"];
    const fetchMock = vi.fn(async () => jsonResponse(incomplete));
    vi.stubGlobal("fetch", fetchMock);

    await expect(operatorPost("/briefs", {})).rejects.toThrow(/outdated.*restart/);
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
