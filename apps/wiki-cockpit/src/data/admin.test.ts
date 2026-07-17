// Admin discovery client (plan §12.1, §22.2): the parser refuses to invent
// state, the loader never contacts the operator from the sealed demo, and an
// old (pre-v7) operator is reported as OUTDATED — never as "locked", which
// would imply an unlock could succeed against a process with no admin surface.

import { afterEach, describe, expect, it, vi } from "vitest";

const { demoRouteRequested, fetchOperatorHealth, operatorRequest } = vi.hoisted(() => ({
  demoRouteRequested: vi.fn(() => false),
  fetchOperatorHealth: vi.fn(async (): Promise<unknown> => null),
  operatorRequest: vi.fn(async (): Promise<unknown> => ({ ok: false }))
}));

vi.mock("../world/clients/operatorClient", () => ({
  demoRouteRequested,
  fetchOperatorHealth,
  operatorRequest
}));

import { loadAdminAccess, parseAdminCapabilities } from "./admin";

function v7Health() {
  return {
    ok: true,
    server_version: "wiki_web_server.v7",
    schema_capabilities: [
      "operator_security_v2",
      "cors_default_deny_v1",
      "action_state_transitions_v1",
      "admin_capabilities_v1"
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
});

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
});
