// Admin discovery + session client (plan §12.1, §13, §22.2): the parser
// refuses to invent state, the loader never contacts the operator from the
// sealed demo, an old operator is reported as OUTDATED — never as "locked",
// which would imply an unlock could succeed against a process with no admin
// surface — and the session lifecycle keeps the token exclusively in memory.

import { afterEach, describe, expect, it, vi } from "vitest";

const { demoRouteRequested, fetchOperatorHealth, operatorPost, operatorRequest } = vi.hoisted(() => ({
  demoRouteRequested: vi.fn(() => false),
  fetchOperatorHealth: vi.fn(async (): Promise<unknown> => null),
  operatorPost: vi.fn(async (): Promise<unknown> => ({ ok: false, json: async () => ({}) })),
  operatorRequest: vi.fn(async (): Promise<unknown> => ({ ok: false }))
}));

vi.mock("../world/clients/operatorClient", () => ({
  demoRouteRequested,
  fetchOperatorHealth,
  operatorPost,
  operatorRequest
}));

import {
  ADMIN_SESSION_HEADER,
  loadAdminAccess,
  lockAdminSession,
  parseAdminCapabilities,
  renewAdminSession,
  requestAdminChallenge,
  unlockAdminSession
} from "./admin";
import {
  adminSessionActive,
  clearAdminSession,
  getAdminSessionToken
} from "../application/adminSession";

function v7Health() {
  return {
    ok: true,
    server_version: "wiki_web_server.v7",
    schema_capabilities: [
      "operator_security_v2",
      "cors_default_deny_v1",
      "action_state_transitions_v1",
      "admin_capabilities_v1",
      "admin_session_v1"
    ],
    operator_security: {
      version: "wiki_operator_security.v2",
      nonce_header: "X-Wiki-Operator-Nonce",
      nonce: "test-nonce",
      attempt_header: "X-Wiki-Attempt-Key",
      max_body_bytes: 1_048_576,
      mutations: "post_only",
      browser_origin_default: "deny",
      cors_opt_in: "exact_loopback_allowlist"
    }
  };
}

function lockedPayload() {
  return {
    ok: true,
    schema_version: "wiki_admin_capabilities.v1",
    server_version: "wiki_admin.v1",
    adapter: "local_startup_code",
    session_state: "locked",
    session: null,
    read_only: true,
    capabilities: [
      { id: "system.inspect", granted: false, reason: "session_not_authorized" },
      { id: "break_glass.local", granted: false, reason: "disabled_by_config" }
    ]
  };
}

afterEach(() => {
  vi.clearAllMocks();
  demoRouteRequested.mockReturnValue(false);
  clearAdminSession();
});

function jsonResponse(status: number, payload: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => payload };
}

function unlockedResponse(token: string) {
  return jsonResponse(200, {
    ok: true,
    token,
    session: {
      session_id: "session_1234",
      role: "admin",
      state: "active_full",
      expires_in_s: 900,
      idle_remaining_s: 300,
      ttl_s: 900,
      idle_lock_s: 300
    }
  });
}

describe("parseAdminCapabilities", () => {
  it("parses the locked discovery payload without inventing grants", () => {
    const parsed = parseAdminCapabilities(lockedPayload());
    expect(parsed).not.toBeNull();
    expect(parsed?.session_state).toBe("locked");
    expect(parsed?.read_only).toBe(true);
    expect(parsed?.capabilities.every((entry) => entry.granted === false)).toBe(true);
  });

  it("rejects payloads that are not an honest capability schema", () => {
    expect(parseAdminCapabilities(null)).toBeNull();
    expect(parseAdminCapabilities({ ...lockedPayload(), ok: false })).toBeNull();
    expect(parseAdminCapabilities({ ...lockedPayload(), session_state: "root" })).toBeNull();
    expect(parseAdminCapabilities({ ...lockedPayload(), capabilities: "all" })).toBeNull();
    expect(parseAdminCapabilities({ ...lockedPayload(), capabilities: [{ granted: true }] })).toBeNull();
  });

  it("treats a malformed granted flag as NOT granted", () => {
    const parsed = parseAdminCapabilities({
      ...lockedPayload(),
      capabilities: [{ id: "system.inspect", granted: "yes" }]
    });
    expect(parsed?.capabilities[0].granted).toBe(false);
  });
});

describe("loadAdminAccess", () => {
  it("never contacts the operator from the sealed demo route", async () => {
    demoRouteRequested.mockReturnValue(true);
    const access = await loadAdminAccess();
    expect(access).toEqual({ kind: "unavailable", reason: "demo" });
    expect(fetchOperatorHealth).not.toHaveBeenCalled();
    expect(operatorRequest).not.toHaveBeenCalled();
  });

  it("reports an unreachable operator (sample fallback) honestly", async () => {
    fetchOperatorHealth.mockResolvedValue(null);
    const access = await loadAdminAccess();
    expect(access).toEqual({ kind: "unavailable", reason: "operator_unreachable" });
    expect(operatorRequest).not.toHaveBeenCalled();
  });

  it("detects an old pre-admin operator and asks for a restart (§22.2)", async () => {
    fetchOperatorHealth.mockResolvedValue({ ...v7Health(), server_version: "wiki_web_server.v6" });
    const access = await loadAdminAccess();
    expect(access.kind).toBe("unavailable");
    if (access.kind === "unavailable") {
      expect(access.reason).toBe("operator_outdated");
      expect(access.detail).toMatch(/outdated.*restart/);
    }
    expect(operatorRequest).not.toHaveBeenCalled();
  });

  it("returns the server's own locked state after a valid v7 handshake", async () => {
    fetchOperatorHealth.mockResolvedValue(v7Health());
    operatorRequest.mockResolvedValue({ ok: true, json: async () => lockedPayload() });
    const access = await loadAdminAccess();
    expect(access.kind).toBe("capabilities");
    if (access.kind === "capabilities") {
      expect(access.payload.session_state).toBe("locked");
      expect(access.payload.adapter).toBe("local_startup_code");
    }
    expect(operatorRequest).toHaveBeenCalledWith(
      "/admin/capabilities",
      expect.objectContaining({ method: "GET" })
    );
  });

  it("refuses to shape a non-schema answer into a session state", async () => {
    fetchOperatorHealth.mockResolvedValue(v7Health());
    operatorRequest.mockResolvedValue({ ok: true, json: async () => ({ hello: "world" }) });
    const access = await loadAdminAccess();
    expect(access).toEqual({ kind: "unavailable", reason: "malformed_response" });
  });

  it("clears a stale in-memory session when the server answers locked (§22.2 remote revocation)", async () => {
    operatorPost.mockResolvedValue(unlockedResponse("tok-a"));
    await unlockAdminSession("challenge-1", "AAAA-2222");
    expect(adminSessionActive()).toBe(true);
    fetchOperatorHealth.mockResolvedValue(v7Health());
    operatorRequest.mockResolvedValue({ ok: true, json: async () => lockedPayload() });
    const access = await loadAdminAccess();
    expect(access.kind).toBe("capabilities");
    expect(adminSessionActive()).toBe(false);
    expect(getAdminSessionToken()).toBeNull();
  });
});

describe("admin session lifecycle (§13, §22.2)", () => {
  it("stores the unlock token in memory only — no browser storage is touched", async () => {
    operatorPost.mockResolvedValueOnce(jsonResponse(200, { ok: true, challenge: "ch-1", expires_in_s: 120 }));
    const challenge = await requestAdminChallenge();
    expect(challenge).toEqual({ ok: true, challenge: "ch-1" });
    operatorPost.mockResolvedValueOnce(unlockedResponse("tok-memory-only"));
    const result = await unlockAdminSession("ch-1", "AAAA-2222");
    expect(result.ok).toBe(true);
    expect(adminSessionActive()).toBe(true);
    expect(getAdminSessionToken()).toBe("tok-memory-only");
    // §22.2/§13.2: nothing persisted — a reload starts from a locked page.
    expect(globalThis.localStorage?.length ?? 0).toBe(0);
    expect(globalThis.sessionStorage?.length ?? 0).toBe(0);
  });

  it("keeps the UI locked after a rejected code (§22.2 no falsely-active state)", async () => {
    operatorPost.mockResolvedValueOnce(
      jsonResponse(403, { ok: false, error_code: "admin_unlock_code_rejected" })
    );
    const result = await unlockAdminSession("ch-1", "WRNG-CODE");
    expect(result).toEqual({ ok: false, errorCode: "admin_unlock_code_rejected" });
    expect(adminSessionActive()).toBe(false);
    expect(getAdminSessionToken()).toBeNull();
  });

  it("renew sends the session header and adopts the rotated token", async () => {
    operatorPost.mockResolvedValueOnce(unlockedResponse("tok-old"));
    await unlockAdminSession("ch-1", "AAAA-2222");
    operatorPost.mockResolvedValueOnce(unlockedResponse("tok-new"));
    const result = await renewAdminSession();
    expect(result.ok).toBe(true);
    expect(operatorPost).toHaveBeenLastCalledWith(
      "/admin/session/renew",
      {},
      expect.objectContaining({ headers: { [ADMIN_SESSION_HEADER]: "tok-old" } })
    );
    expect(getAdminSessionToken()).toBe("tok-new");
  });

  it("a failed renew locks the client side immediately", async () => {
    operatorPost.mockResolvedValueOnce(unlockedResponse("tok-old"));
    await unlockAdminSession("ch-1", "AAAA-2222");
    operatorPost.mockResolvedValueOnce(
      jsonResponse(403, { ok: false, error_code: "admin_session_expired" })
    );
    const result = await renewAdminSession();
    expect(result).toEqual({ ok: false, errorCode: "admin_session_expired" });
    expect(adminSessionActive()).toBe(false);
  });

  it("lock forgets the token even when the transport fails (§5.4)", async () => {
    operatorPost.mockResolvedValueOnce(unlockedResponse("tok-old"));
    await unlockAdminSession("ch-1", "AAAA-2222");
    operatorPost.mockRejectedValueOnce(new Error("network down"));
    const result = await lockAdminSession();
    expect(result).toEqual({ ok: false, errorCode: "operator_unreachable" });
    expect(adminSessionActive()).toBe(false);
    expect(getAdminSessionToken()).toBeNull();
  });

  it("maps rate limiting to its typed error", async () => {
    operatorPost.mockResolvedValueOnce(
      jsonResponse(429, { ok: false, error_code: "admin_rate_limited" })
    );
    const result = await unlockAdminSession("ch-1", "AAAA-2222");
    expect(result).toEqual({ ok: false, errorCode: "admin_rate_limited" });
  });
});
