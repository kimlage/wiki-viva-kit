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
  executeAdminPlan,
  fetchAdminCommandCatalog,
  loadAdminAccess,
  lockAdminSession,
  parseAdminCapabilities,
  parseAdminExecuteOutcome,
  parseAdminPlan,
  planAdminCommand,
  renewAdminSession,
  requestAdminChallenge,
  unlockAdminSession
} from "./admin";
import {
  adminSessionActive,
  clearAdminSession,
  getAdminSessionDescription,
  getAdminSessionToken,
  setAdminSession,
  adminLockNoticeKey
} from "../application/adminSession";

function v7Health() {
  return {
    ok: true,
    server_version: "wiki_web_server.v10",
    schema_capabilities: [
      "operator_security_v2",
      "cors_default_deny_v1",
      "action_state_transitions_v1",
      "action_page_authoring_v1",
      "admin_capabilities_v1",
      "admin_session_v1",
      "admin_commands_v1", "revocable_documentary_proposals_v1"
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
    effect_state: { inflight_effects:0, revocation_pending:false, outcome_uncertain:false },
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
    const {effect_state: _activity, ...oldOperator} = lockedPayload();
    expect(parseAdminCapabilities(oldOperator)).toBeNull();
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

  it("retains only a lock-confirmation credential while revocation drains", async () => {
    operatorPost.mockResolvedValueOnce(unlockedResponse("tok-draining"));
    await unlockAdminSession("ch-1", "AAAA-2222");
    operatorPost.mockResolvedValueOnce(jsonResponse(409, { ok: false, error_code: "admin_revocation_pending", state: "revocation_pending" }));
    operatorPost.mockResolvedValueOnce(jsonResponse(200, { ok: true, state: "locked" }));
    expect(await lockAdminSession()).toEqual({ ok: false, errorCode: "admin_revocation_pending" });
    expect(adminSessionActive()).toBe(false);
    expect(getAdminSessionToken()).toBeNull();
    expect(getAdminSessionDescription()?.revocationState).toBe("pending");
    const calls = operatorPost.mock.calls.length;
    expect((await planAdminCommand("system.inspect")).ok).toBe(false);
    expect(operatorPost.mock.calls.length).toBe(calls);
    expect(await lockAdminSession()).toEqual({ ok: true });
    expect(operatorPost).toHaveBeenLastCalledWith("/admin/session/lock", {}, {
      headers: { [ADMIN_SESSION_HEADER]: "tok-draining" }
    });
  });

  it("retains confirmation through discovery, transport failure and uncertainty", async () => {
    operatorPost.mockResolvedValueOnce(unlockedResponse("tok-reconcile"));
    await unlockAdminSession("ch-1", "AAAA-2222");
    operatorPost.mockRejectedValueOnce(new Error("controlled transport failure"));
    expect((await lockAdminSession()).ok).toBe(false);
    expect(getAdminSessionDescription()?.revocationState).toBe("unconfirmed");
    fetchOperatorHealth.mockResolvedValue(v7Health());
    operatorRequest.mockResolvedValueOnce(jsonResponse(200, { ...lockedPayload(),
      effect_state: { inflight_effects: 1, revocation_pending: true, outcome_uncertain: false } }));
    await loadAdminAccess();
    expect(getAdminSessionDescription()?.revocationState).toBe("unconfirmed");
    operatorPost.mockResolvedValueOnce(jsonResponse(409, { ok: false, error_code: "admin_effect_outcome_uncertain" }));
    expect(await lockAdminSession()).toEqual({ ok: false, errorCode: "admin_effect_outcome_uncertain" });
    expect(getAdminSessionDescription()?.revocationState).toBe("uncertain");
    expect(operatorPost).toHaveBeenLastCalledWith("/admin/session/lock", {}, { headers: { [ADMIN_SESSION_HEADER]: "tok-reconcile" } });
    const count = operatorPost.mock.calls.length;
    expect((await renewAdminSession()).ok).toBe(false);
    expect((await unlockAdminSession("new", "EXAMPLE")).ok).toBe(false);
    expect(operatorPost.mock.calls.length).toBe(count);
  });

  it("a delayed renew can only confirm revocation, never reactivate after lock", async () => {
    operatorPost.mockResolvedValueOnce(unlockedResponse("tok-racing"));
    await unlockAdminSession("ch-1", "AAAA-2222");
    let finishRenew!: (value: unknown) => void;
    operatorPost.mockImplementationOnce(() => new Promise((resolve) => { finishRenew = resolve; }));
    const renewal = renewAdminSession();
    operatorPost.mockResolvedValueOnce(jsonResponse(409, { ok: false, error_code: "admin_revocation_pending" }));
    await lockAdminSession();
    operatorPost.mockResolvedValueOnce(jsonResponse(200, { ok: true, state: "locked" }));
    finishRenew(unlockedResponse("tok-late-rotation"));
    expect((await renewal).ok).toBe(false);
    expect(getAdminSessionToken()).toBeNull();
    expect(getAdminSessionDescription()).toBeNull();
    expect(operatorPost).toHaveBeenLastCalledWith("/admin/session/lock", {}, { headers: { [ADMIN_SESSION_HEADER]: "tok-late-rotation" } });
  });

  it("a known renew rate limit does not falsely announce or erase a session", async () => {
    operatorPost.mockResolvedValueOnce(unlockedResponse("tok-limited"));
    await unlockAdminSession("ch-1", "AAAA-2222");
    operatorPost.mockResolvedValueOnce(jsonResponse(429, { ok: false, error_code: "admin_rate_limited" }));
    expect(await renewAdminSession()).toEqual({ ok: false, errorCode: "admin_rate_limited" });
    expect(adminSessionActive()).toBe(true);
    expect(getAdminSessionToken()).toBe("tok-limited");
  });

  it.each(["pending", "transport"])("an older lock %s cannot undo newer completion or emit a stale notice", async (outcome) => {
    operatorPost.mockResolvedValueOnce(unlockedResponse("tok-concurrent-lock"));
    await unlockAdminSession("ch-1", "AAAA-2222");
    let finish!: (value: unknown) => void;
    let fail!: (reason: Error) => void;
    operatorPost.mockImplementationOnce(() => new Promise((resolve, reject) => { finish = resolve; fail = reject; }));
    const first = lockAdminSession();
    operatorPost.mockResolvedValueOnce(jsonResponse(200, { ok: true, state: "locked" }));
    expect(await lockAdminSession()).toEqual({ ok: true });
    if (outcome === "pending") finish(jsonResponse(409, { ok: false, error_code: "admin_revocation_pending" }));
    else fail(new Error("controlled late transport error"));
    const old = await first;
    expect(old).toEqual({ ok: false, errorCode: "admin_response_superseded" });
    expect(adminLockNoticeKey(old)).toBeNull();
    expect(getAdminSessionDescription()).toBeNull();
    expect(getAdminSessionToken()).toBeNull();
  });

  it("an old successful lock cannot announce completion for a newer session", async () => {
    operatorPost.mockResolvedValueOnce(unlockedResponse("tok-old-session"));
    await unlockAdminSession("ch-1", "AAAA-2222");
    let finish!: (value: unknown) => void;
    operatorPost.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const pending = lockAdminSession();
    setAdminSession("tok-new-session", { sessionId: "new-session", role: "admin", state: "active_full",
      expiresAtMs: Date.now()+900000, ttlS:900, idleLockS:300 });
    finish(jsonResponse(200, { ok:true, state:"locked" }));
    const old = await pending;
    expect(adminLockNoticeKey(old)).toBeNull();
    expect(getAdminSessionToken()).toBe("tok-new-session");
  });

  it.each(["refusal", "transport"])("a late renew %s is superseded for both state and notice", async (outcome) => {
    operatorPost.mockResolvedValueOnce(unlockedResponse("tok-renew-old"));
    await unlockAdminSession("ch-1", "AAAA-2222");
    let finish!: (value: unknown) => void;
    let fail!: (reason: Error) => void;
    operatorPost.mockImplementationOnce(() => new Promise((resolve,reject) => { finish=resolve; fail=reject; }));
    const renewal=renewAdminSession();
    clearAdminSession();
    setAdminSession("tok-renew-new", {sessionId:"new-session",role:"admin",state:"active_full",
      expiresAtMs:Date.now()+900000,ttlS:900,idleLockS:300});
    if (outcome === "refusal") finish(jsonResponse(403,{ok:false,error_code:"admin_session_invalid"}));
    else fail(new Error("controlled late transport error"));
    expect(await renewal).toEqual({ok:false,errorCode:"admin_response_superseded"});
    expect(getAdminSessionToken()).toBe("tok-renew-new");
  });

  it("late discovery cannot quarantine a newer session", async () => {
    operatorPost.mockResolvedValueOnce(unlockedResponse("tok-old-discovery"));
    await unlockAdminSession("ch-1", "AAAA-2222");
    fetchOperatorHealth.mockResolvedValue(v7Health());
    let finish!: (value: unknown) => void;
    operatorRequest.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const discovery = loadAdminAccess();
    await vi.waitFor(() => expect(finish).toBeTypeOf("function"));
    setAdminSession("tok-new-discovery", { sessionId: "new-session", role: "admin", state: "active_full",
      expiresAtMs: Date.now()+900000, ttlS:900, idleLockS:300 });
    finish(jsonResponse(200, lockedPayload()));
    expect(await discovery).toEqual({ kind: "superseded" });
    expect(getAdminSessionToken()).toBe("tok-new-discovery");
    expect(getAdminSessionDescription()?.revocationState).toBeUndefined();
  });

  it("a delayed unlock after off is retained only to confirm native revocation", async () => {
    let finish!: (value: unknown) => void;
    operatorPost.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const unlocking = unlockAdminSession("ch-late", "AAAA-2222");
    expect((await lockAdminSession()).ok).toBe(false); // off invalidates the pending lifecycle
    const calls = operatorPost.mock.calls.length;
    expect((await unlockAdminSession("second", "AAAA-2222")).ok).toBe(false);
    expect(operatorPost.mock.calls.length).toBe(calls); // a second unlock cannot replace pending identity
    operatorPost.mockResolvedValueOnce(jsonResponse(200, { ok:true, state:"locked" }));
    finish(unlockedResponse("tok-late-unlock"));
    expect((await unlocking).ok).toBe(false);
    expect(getAdminSessionToken()).toBeNull();
    expect(getAdminSessionDescription()).toBeNull();
    expect(operatorPost).toHaveBeenLastCalledWith("/admin/session/lock", {}, {
      headers:{[ADMIN_SESSION_HEADER]:"tok-late-unlock"}
    });
  });

  it("maps rate limiting to its typed error", async () => {
    operatorPost.mockResolvedValueOnce(
      jsonResponse(429, { ok: false, error_code: "admin_rate_limited" })
    );
    const result = await unlockAdminSession("ch-1", "AAAA-2222");
    expect(result).toEqual({ ok: false, errorCode: "admin_rate_limited" });
  });
});

// ---------------------------------------------------------------------------
// Command bus client (plan §11, §12.2, PR4)
// ---------------------------------------------------------------------------

function planPayload(overrides: Record<string, unknown> = {}) {
  return {
    ok: true,
    plan_id: "plan_ab12cd34",
    plan_sha: `sha256:${"a".repeat(64)}`,
    expires_in_s: 600,
    plan: {
      schema_version: "wiki_admin_plan.v1",
      command_id: "snapshot.rebuild",
      title: "Rebuild the published web snapshot",
      params: {},
      dry_run: false,
      risk_level: "derive",
      capability: ["snapshot.rebuild"],
      summary: "Rebuild the derived web snapshot.",
      preconditions: [
        { id: "branch", expected: "wiki/topic" },
        { id: "worktree_fingerprint", expected: "sha256:beef" }
      ],
      effects: {
        files_read: ["memories"],
        files_write: ["data/derived/wiki/web-snapshot"],
        external_calls: [],
        snapshot_invalidated: true
      },
      diff: null,
      validation: { kind: "deterministic_rebuild" },
      undo: {
        kind: "restore_previous_snapshot_revision",
        available: false,
        previous_revision: null
      },
      confirmation: { kind: "simple", text: "RUN snapshot.rebuild" },
      ...overrides
    }
  };
}

async function unlockForBus(token: string) {
  operatorPost.mockResolvedValueOnce(unlockedResponse(token));
  await unlockAdminSession("ch-1", "AAAA-2222");
}

describe("command bus client (§11, §12.2)", () => {
  it("planAdminCommand refuses locally without a session — no request leaves", async () => {
    const result = await planAdminCommand("system.inspect");
    expect(result).toEqual({ ok: false, errorCode: "admin_session_invalid" });
    expect(operatorPost).not.toHaveBeenCalled();
  });

  it("planAdminCommand sends command_id + params only, with the session header", async () => {
    await unlockForBus("tok-bus");
    operatorPost.mockResolvedValueOnce(jsonResponse(200, planPayload()));
    const result = await planAdminCommand("snapshot.rebuild", {}, { dryRun: false });
    expect(operatorPost).toHaveBeenLastCalledWith(
      "/admin/commands/plan",
      { command_id: "snapshot.rebuild", params: {}, dry_run: false },
      expect.objectContaining({ headers: { [ADMIN_SESSION_HEADER]: "tok-bus" } })
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.plan.planSha).toBe(`sha256:${"a".repeat(64)}`);
      expect(result.plan.effects.snapshotInvalidated).toBe(true);
      expect(result.plan.confirmation).toEqual({ kind: "simple", text: "RUN snapshot.rebuild" });
    }
  });

  it("parseAdminPlan refuses malformed payloads instead of inventing a plan", () => {
    expect(parseAdminPlan(null)).toBeNull();
    expect(parseAdminPlan({ ok: false })).toBeNull();
    const noEffects = planPayload({ effects: "everything" });
    expect(parseAdminPlan(noEffects)).toBeNull();
    const weirdConfirmation = planPayload({ confirmation: { kind: "shout", text: "GO" } });
    expect(parseAdminPlan(weirdConfirmation)).toBeNull();
  });

  it("executeAdminPlan binds plan_id + plan_sha + confirmation to the request", async () => {
    await unlockForBus("tok-bus");
    const plan = parseAdminPlan(planPayload());
    expect(plan).not.toBeNull();
    operatorPost.mockResolvedValueOnce(
      jsonResponse(200, {
        ok: true,
        plan_id: plan!.planId,
        plan_sha: plan!.planSha,
        command_id: "snapshot.rebuild",
        risk_level: "derive",
        dry_run: false,
        status: "success",
        output: { files: [] },
        affected_paths: ["data/derived/wiki/web-snapshot"],
        branch: "wiki/topic",
        snapshot_invalidated: true,
        undo: { kind: "restore_previous_snapshot_revision", available: true, previous_revision: "rev-1" }
      })
    );
    const result = await executeAdminPlan(plan!, "RUN snapshot.rebuild");
    expect(operatorPost).toHaveBeenLastCalledWith(
      "/admin/commands/execute",
      {
        plan_id: plan!.planId,
        plan_sha: plan!.planSha,
        confirmation: "RUN snapshot.rebuild"
      },
      expect.objectContaining({ headers: { [ADMIN_SESSION_HEADER]: "tok-bus" } })
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.outcome.snapshotInvalidated).toBe(true);
      expect(result.outcome.undo).toEqual({
        kind: "restore_previous_snapshot_revision",
        available: true,
        previousRevision: "rev-1"
      });
    }
  });

  it("maps a stale-plan refusal with its failed preconditions (§9.3)", async () => {
    await unlockForBus("tok-bus");
    const plan = parseAdminPlan(planPayload());
    operatorPost.mockResolvedValueOnce(
      jsonResponse(409, {
        ok: false,
        error_code: "admin_plan_stale",
        failed_preconditions: ["branch", "worktree_fingerprint"]
      })
    );
    const result = await executeAdminPlan(plan!, "RUN snapshot.rebuild");
    expect(result).toEqual({
      ok: false,
      errorCode: "admin_plan_stale",
      failedPreconditions: ["branch", "worktree_fingerprint"]
    });
  });

  it("parseAdminExecuteOutcome never invents an available undo", () => {
    expect(
      parseAdminExecuteOutcome({
        ok: true,
        plan_id: "plan_1",
        command_id: "system.inspect",
        status: "success",
        undo: { kind: "restore_previous_snapshot_revision", available: "yes" }
      })!.undo.available
    ).toBe(false);
    expect(parseAdminExecuteOutcome({ ok: false })).toBeNull();
  });

  it("fetchAdminCommandCatalog carries the token and refuses malformed catalogs", async () => {
    await unlockForBus("tok-bus");
    operatorRequest.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        schema_version: "wiki_admin_commands.v1",
        commands: [
          {
            id: "system.inspect",
            title: "Inspect system state",
            capability: ["system.inspect"],
            risk_level: "read",
            supports_dry_run: false,
            parameter_schema: { reviewed_input: { required: true } },
            undo_strategy: null,
            granted: true
          }
        ]
      })
    });
    const result = await fetchAdminCommandCatalog();
    expect(operatorRequest).toHaveBeenLastCalledWith(
      "/admin/commands",
      expect.objectContaining({
        headers: expect.objectContaining({ [ADMIN_SESSION_HEADER]: "tok-bus" })
      })
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.commands).toEqual([
        {
          id: "system.inspect",
          title: "Inspect system state",
          capability: ["system.inspect"],
          riskLevel: "read",
          supportsDryRun: false,
          requiresParameters: true,
          undoStrategy: null,
          granted: true,
          reason: undefined
        }
      ]);
    }
    operatorRequest.mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true, commands: "all" }) });
    const malformed = await fetchAdminCommandCatalog();
    expect(malformed.ok).toBe(false);
  });
});
