// Admin discovery + session client (god-mode plan §6.3, §12.1, §13, §14).
// Discovery is read-only by construction; the session calls below go through
// the SAME operator mutation boundary as every other write (nonce +
// attempt-key), with the session token composed on top as a header — never
// in a URL, never in a body echo, never in storage (the in-memory store in
// application/adminSession.ts is the only place the token exists). Opening
// ?dock=admin goes through here and can therefore never authorize anything
// (plan §14.1): authorization is exclusively the challenge+code unlock.

import {
  operatorRestartReason,
  validateOperatorHandshake
} from "../contracts/operatorSecurity.js";
import {
  demoRouteRequested,
  fetchOperatorHealth,
  operatorPost,
  operatorRequest
} from "../world/clients/operatorClient";
import {
  clearAdminSession,
  getAdminSessionToken,
  setAdminSession
} from "../application/adminSession";
import type { AdminSessionDescription } from "../application/adminSession";

// Mirror of wiki_core/web/admin/sessions.py (ADMIN_SESSION_HEADER): the
// session header COMPOSES with the operator nonce + attempt-key headers.
export const ADMIN_SESSION_HEADER = "X-Wiki-Admin-Session";

// The §6.3 closed state vocabulary, mirrored from
// wiki_core/web/admin/capabilities.py (ADMIN_SESSION_STATES).
export const ADMIN_SESSION_STATES = [
  "unavailable",
  "locked",
  "unlocking",
  "active_readonly",
  "active_partial",
  "active_full",
  "expiring",
  "revoked"
] as const;
export type AdminSessionState = (typeof ADMIN_SESSION_STATES)[number];

export type AdminCapabilityRecord = {
  id: string;
  granted: boolean;
  reason?: string;
};

// Public, token-free session description as answered by the server.
export type AdminCapabilitySession = {
  session_id: string;
  role: string | null;
  state: AdminSessionState;
  expires_in_s: number | null;
};

// GET /api/admin/capabilities (wiki_admin_capabilities.v1).
export type AdminCapabilities = {
  schema_version: string;
  server_version: string;
  adapter: string | null;
  session_state: AdminSessionState;
  session: AdminCapabilitySession | null;
  read_only: boolean;
  capabilities: AdminCapabilityRecord[];
};

// Why the dock is showing "unavailable" without a server-side state to quote.
export type AdminUnavailableReason =
  | "demo" // sealed demo route: no operator request is even attempted
  | "operator_unreachable" // sample fallback / static bundle
  | "operator_outdated" // pre-v7 process: restart to get the admin surface
  | "malformed_response"; // reachable but not speaking the capability schema

export type AdminAccess =
  | { kind: "unavailable"; reason: AdminUnavailableReason; detail?: string }
  | { kind: "capabilities"; payload: AdminCapabilities };

function isSessionState(value: unknown): value is AdminSessionState {
  return (ADMIN_SESSION_STATES as readonly string[]).includes(String(value));
}

export function parseAdminCapabilities(payload: unknown): AdminCapabilities | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  const record = payload as Record<string, unknown>;
  if (record.ok !== true) return null;
  if (!isSessionState(record.session_state)) return null;
  const rawCapabilities = Array.isArray(record.capabilities) ? record.capabilities : null;
  if (!rawCapabilities) return null;
  const capabilities: AdminCapabilityRecord[] = [];
  for (const entry of rawCapabilities) {
    if (!entry || typeof entry !== "object") return null;
    const item = entry as Record<string, unknown>;
    if (typeof item.id !== "string" || item.id.length === 0) return null;
    capabilities.push({
      id: item.id,
      // A missing/malformed granted flag is NOT a grant.
      granted: item.granted === true,
      reason: typeof item.reason === "string" ? item.reason : undefined
    });
  }
  let session: AdminCapabilitySession | null = null;
  const rawSession = record.session;
  if (rawSession && typeof rawSession === "object" && !Array.isArray(rawSession)) {
    const item = rawSession as Record<string, unknown>;
    if (typeof item.session_id === "string" && item.session_id) {
      session = {
        session_id: item.session_id,
        role: typeof item.role === "string" && item.role ? item.role : null,
        state: isSessionState(item.state) ? item.state : record.session_state,
        expires_in_s:
          typeof item.expires_in_s === "number" && Number.isFinite(item.expires_in_s)
            ? item.expires_in_s
            : null
      };
    }
  }
  return {
    schema_version: String(record.schema_version || ""),
    server_version: String(record.server_version || ""),
    adapter: typeof record.adapter === "string" && record.adapter ? record.adapter : null,
    session_state: record.session_state,
    session,
    read_only: record.read_only !== false,
    capabilities
  };
}

/**
 * Resolve what the admin surface may honestly show right now.
 *
 * Order matters: the sealed demo never contacts the operator; an unreachable
 * or outdated operator is reported as such (never as "locked", which would
 * imply an unlock could work); only a valid v7 handshake proceeds to the
 * discovery request. Nothing here retries or stores anything.
 */
export async function loadAdminAccess(options: { signal?: AbortSignal } = {}): Promise<AdminAccess> {
  if (demoRouteRequested()) {
    return { kind: "unavailable", reason: "demo" };
  }
  const health = await fetchOperatorHealth(options);
  if (!health) {
    return { kind: "unavailable", reason: "operator_unreachable" };
  }
  const handshake = validateOperatorHandshake(health);
  if (!handshake.ok) {
    return {
      kind: "unavailable",
      reason: "operator_outdated",
      detail: operatorRestartReason(handshake)
    };
  }
  try {
    // The in-memory token (if any) rides along so the server can answer with
    // the session's real granted state. Sending it never authorizes — the
    // server validates it against its own store and answers "locked" for
    // anything stale (remote revocation reflects on the next request, §22.2).
    const token = getAdminSessionToken();
    const response = await operatorRequest("/admin/capabilities", {
      method: "GET",
      headers: {
        accept: "application/json",
        ...(token ? { [ADMIN_SESSION_HEADER]: token } : {})
      },
      cache: "no-store",
      signal: options.signal
    });
    if (!response.ok) {
      return { kind: "unavailable", reason: "malformed_response" };
    }
    const payload = parseAdminCapabilities(await response.json());
    if (!payload) {
      return { kind: "unavailable", reason: "malformed_response" };
    }
    if (token && payload.session === null) {
      // We believed we had a session; the server says otherwise (restart,
      // expiry, revocation). Never keep a falsely "active" UI (§22.2).
      clearAdminSession();
    }
    return { kind: "capabilities", payload };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return { kind: "unavailable", reason: "operator_unreachable" };
  }
}

// ---------------------------------------------------------------------------
// Session lifecycle (god-mode plan §13.1): challenge -> unlock -> renew/lock
// ---------------------------------------------------------------------------

// Closed error vocabulary mirrored from wiki_core/web/admin/sessions.py, plus
// the client-side transport failure.
export type AdminSessionErrorCode =
  | "admin_disabled"
  | "admin_rate_limited"
  | "admin_challenge_rejected"
  | "admin_unlock_code_rejected"
  | "admin_session_invalid"
  | "admin_session_expired"
  | "operator_unreachable";

// Command-bus refusal vocabulary mirrored from wiki_core/web/admin/plans.py.
export type AdminCommandErrorCode =
  | AdminSessionErrorCode
  | "admin_unknown_command"
  | "admin_invalid_params"
  | "admin_capability_denied"
  | "admin_plan_not_found"
  | "admin_plan_sha_mismatch"
  | "admin_plan_stale"
  | "admin_plan_already_executed"
  | "admin_confirmation_required"
  | "admin_confirmation_mismatch"
  | "admin_checkout_busy"
  | "admin_command_failed";

export type AdminChallengeResult =
  | { ok: true; challenge: string }
  | { ok: false; errorCode: AdminSessionErrorCode };

export type AdminSessionResult =
  | { ok: true; session: AdminSessionDescription }
  | { ok: false; errorCode: AdminSessionErrorCode };

export type AdminLockResult =
  | { ok: true }
  | { ok: false; errorCode: AdminSessionErrorCode };

function errorCodeOf(payload: unknown): AdminSessionErrorCode {
  const code =
    payload && typeof payload === "object"
      ? String((payload as Record<string, unknown>).error_code || "")
      : "";
  switch (code) {
    case "admin_disabled":
    case "admin_rate_limited":
    case "admin_challenge_rejected":
    case "admin_unlock_code_rejected":
    case "admin_session_invalid":
    case "admin_session_expired":
      return code;
    default:
      return "operator_unreachable";
  }
}

function describeSession(payload: Record<string, unknown>): AdminSessionDescription | null {
  const session = payload.session;
  if (!session || typeof session !== "object" || Array.isArray(session)) return null;
  const item = session as Record<string, unknown>;
  if (typeof item.session_id !== "string" || !item.session_id) return null;
  const expiresIn =
    typeof item.expires_in_s === "number" && Number.isFinite(item.expires_in_s)
      ? item.expires_in_s
      : 0;
  return {
    sessionId: item.session_id,
    role: typeof item.role === "string" ? item.role : "",
    state: typeof item.state === "string" ? item.state : "active_partial",
    expiresAtMs: Date.now() + expiresIn * 1000,
    ttlS: typeof item.ttl_s === "number" ? item.ttl_s : expiresIn,
    idleLockS: typeof item.idle_lock_s === "number" ? item.idle_lock_s : 0
  };
}

export async function requestAdminChallenge(): Promise<AdminChallengeResult> {
  try {
    const response = await operatorPost("/admin/session/challenge", {});
    const payload = (await response.json()) as Record<string, unknown>;
    if (response.ok && payload.ok === true && typeof payload.challenge === "string") {
      return { ok: true, challenge: payload.challenge };
    }
    return { ok: false, errorCode: errorCodeOf(payload) };
  } catch {
    return { ok: false, errorCode: "operator_unreachable" };
  }
}

/**
 * Exchange the printed startup code + a fresh challenge for a session.
 * On success the token goes STRAIGHT into the in-memory store; it is not
 * returned to the caller — components never touch it.
 */
export async function unlockAdminSession(
  challenge: string,
  code: string
): Promise<AdminSessionResult> {
  try {
    const response = await operatorPost("/admin/session/unlock", { challenge, code });
    const payload = (await response.json()) as Record<string, unknown>;
    const description = describeSession(payload);
    if (response.ok && payload.ok === true && typeof payload.token === "string" && description) {
      setAdminSession(payload.token, description);
      return { ok: true, session: description };
    }
    return { ok: false, errorCode: errorCodeOf(payload) };
  } catch {
    return { ok: false, errorCode: "operator_unreachable" };
  }
}

/** Rotate the token and extend the TTL (plan §13.2). */
export async function renewAdminSession(): Promise<AdminSessionResult> {
  const token = getAdminSessionToken();
  if (!token) return { ok: false, errorCode: "admin_session_invalid" };
  try {
    const response = await operatorPost("/admin/session/renew", {}, {
      headers: { [ADMIN_SESSION_HEADER]: token }
    });
    const payload = (await response.json()) as Record<string, unknown>;
    const description = describeSession(payload);
    if (response.ok && payload.ok === true && typeof payload.token === "string" && description) {
      setAdminSession(payload.token, description);
      return { ok: true, session: description };
    }
    // A failed renew means the session is gone server-side (expired,
    // revoked, restarted). The UI must never stay "active" on hope (§22.2).
    clearAdminSession();
    return { ok: false, errorCode: errorCodeOf(payload) };
  } catch {
    return { ok: false, errorCode: "operator_unreachable" };
  }
}

/**
 * Lock now (§5.4): ask the server to revoke, then always forget the token
 * locally — even when the request fails, the client side of the session is
 * gone, and the server's own TTL/idle lock is the backstop.
 */
// ---------------------------------------------------------------------------
// Command bus (god-mode plan §11, §12.2): catalog -> plan -> review -> execute
// ---------------------------------------------------------------------------

// GET /api/admin/commands entry (wiki_admin_commands.v1). The catalog never
// grants: `granted` mirrors the server-side session role and is revalidated
// again on plan AND on execute.
export type AdminCommandCatalogEntry = {
  id: string;
  title: string;
  capability: string[];
  riskLevel: string;
  supportsDryRun: boolean;
  undoStrategy: string | null;
  granted: boolean;
  reason?: string;
};

export type AdminPlanEffects = {
  filesRead: string[];
  filesWrite: string[];
  externalCalls: string[];
  snapshotInvalidated: boolean;
};

export type AdminPlanConfirmation = {
  kind: "none" | "simple" | "typed";
  text: string | null;
};

export type AdminPlanPrecondition = { id: string; expected: unknown };

export type AdminPlanUndo = {
  kind: string | null;
  available: boolean;
  previousRevision?: string | null;
};

// One materialized plan (wiki_admin_plan.v1). The sha covers the canonical
// content the server stored — what you reviewed is what will run (§11.3).
export type AdminPlan = {
  planId: string;
  planSha: string;
  commandId: string;
  title: string;
  riskLevel: string;
  dryRun: boolean;
  summary: string;
  preconditions: AdminPlanPrecondition[];
  effects: AdminPlanEffects;
  diff: string | null;
  validation: Record<string, unknown>;
  undo: AdminPlanUndo;
  confirmation: AdminPlanConfirmation;
};

export type AdminExecuteOutcome = {
  planId: string;
  commandId: string;
  status: string;
  dryRun: boolean;
  output: unknown;
  affectedPaths: string[];
  branch: string | null;
  snapshotInvalidated: boolean;
  undo: AdminPlanUndo;
};

export type AdminCatalogResult =
  | { ok: true; commands: AdminCommandCatalogEntry[] }
  | { ok: false; errorCode: AdminCommandErrorCode };

export type AdminPlanResult =
  | { ok: true; plan: AdminPlan }
  | { ok: false; errorCode: AdminCommandErrorCode };

export type AdminExecuteResult =
  | { ok: true; outcome: AdminExecuteOutcome }
  | {
      ok: false;
      errorCode: AdminCommandErrorCode;
      failedPreconditions?: string[];
    };

function commandErrorCodeOf(payload: unknown): AdminCommandErrorCode {
  const code =
    payload && typeof payload === "object"
      ? String((payload as Record<string, unknown>).error_code || "")
      : "";
  switch (code) {
    case "admin_disabled":
    case "admin_rate_limited":
    case "admin_session_invalid":
    case "admin_session_expired":
    case "admin_unknown_command":
    case "admin_invalid_params":
    case "admin_capability_denied":
    case "admin_plan_not_found":
    case "admin_plan_sha_mismatch":
    case "admin_plan_stale":
    case "admin_plan_already_executed":
    case "admin_confirmation_required":
    case "admin_confirmation_mismatch":
    case "admin_checkout_busy":
    case "admin_command_failed":
      return code;
    default:
      return "operator_unreachable";
  }
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

function parseUndo(value: unknown): AdminPlanUndo {
  const record =
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  return {
    kind: typeof record.kind === "string" && record.kind ? record.kind : null,
    // A missing/malformed flag is NOT an available undo.
    available: record.available === true,
    previousRevision:
      typeof record.previous_revision === "string" && record.previous_revision
        ? record.previous_revision
        : null
  };
}

export function parseAdminPlan(payload: unknown): AdminPlan | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  const record = payload as Record<string, unknown>;
  if (record.ok !== true) return null;
  if (typeof record.plan_id !== "string" || !record.plan_id) return null;
  if (typeof record.plan_sha !== "string" || !record.plan_sha) return null;
  const content = record.plan;
  if (!content || typeof content !== "object" || Array.isArray(content)) return null;
  const plan = content as Record<string, unknown>;
  if (typeof plan.command_id !== "string" || !plan.command_id) return null;
  const rawEffects =
    plan.effects && typeof plan.effects === "object" && !Array.isArray(plan.effects)
      ? (plan.effects as Record<string, unknown>)
      : null;
  if (!rawEffects) return null;
  const rawConfirmation =
    plan.confirmation &&
    typeof plan.confirmation === "object" &&
    !Array.isArray(plan.confirmation)
      ? (plan.confirmation as Record<string, unknown>)
      : null;
  const confirmationKind = String(rawConfirmation?.kind || "");
  if (!["none", "simple", "typed"].includes(confirmationKind)) return null;
  const preconditions: AdminPlanPrecondition[] = [];
  for (const entry of Array.isArray(plan.preconditions) ? plan.preconditions : []) {
    if (!entry || typeof entry !== "object") return null;
    const item = entry as Record<string, unknown>;
    if (typeof item.id !== "string" || !item.id) return null;
    preconditions.push({ id: item.id, expected: item.expected });
  }
  return {
    planId: record.plan_id,
    planSha: record.plan_sha,
    commandId: plan.command_id,
    title: String(plan.title || plan.command_id),
    riskLevel: String(plan.risk_level || "read"),
    dryRun: plan.dry_run === true,
    summary: String(plan.summary || ""),
    preconditions,
    effects: {
      filesRead: stringList(rawEffects.files_read),
      filesWrite: stringList(rawEffects.files_write),
      externalCalls: stringList(rawEffects.external_calls),
      snapshotInvalidated: rawEffects.snapshot_invalidated === true
    },
    diff: typeof plan.diff === "string" ? plan.diff : null,
    validation:
      plan.validation && typeof plan.validation === "object" && !Array.isArray(plan.validation)
        ? (plan.validation as Record<string, unknown>)
        : {},
    undo: parseUndo(plan.undo),
    confirmation: {
      kind: confirmationKind as AdminPlanConfirmation["kind"],
      text:
        typeof rawConfirmation?.text === "string" && rawConfirmation.text
          ? rawConfirmation.text
          : null
    }
  };
}

export function parseAdminExecuteOutcome(payload: unknown): AdminExecuteOutcome | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  const record = payload as Record<string, unknown>;
  if (record.ok !== true) return null;
  if (typeof record.plan_id !== "string" || !record.plan_id) return null;
  if (typeof record.command_id !== "string" || !record.command_id) return null;
  return {
    planId: record.plan_id,
    commandId: record.command_id,
    status: String(record.status || "success"),
    dryRun: record.dry_run === true,
    output: record.output ?? null,
    affectedPaths: stringList(record.affected_paths),
    branch: typeof record.branch === "string" && record.branch ? record.branch : null,
    snapshotInvalidated: record.snapshot_invalidated === true,
    undo: parseUndo(record.undo)
  };
}

/** Read the reviewable command catalog. Requires an active session header —
 * the server answers, but nothing in the catalog is executable without one. */
export async function fetchAdminCommandCatalog(): Promise<AdminCatalogResult> {
  const token = getAdminSessionToken();
  try {
    const response = await operatorRequest("/admin/commands", {
      method: "GET",
      headers: {
        accept: "application/json",
        ...(token ? { [ADMIN_SESSION_HEADER]: token } : {})
      },
      cache: "no-store"
    });
    const payload = (await response.json()) as Record<string, unknown>;
    if (!response.ok || payload.ok !== true || !Array.isArray(payload.commands)) {
      return { ok: false, errorCode: commandErrorCodeOf(payload) };
    }
    const commands: AdminCommandCatalogEntry[] = [];
    for (const entry of payload.commands) {
      if (!entry || typeof entry !== "object") continue;
      const item = entry as Record<string, unknown>;
      if (typeof item.id !== "string" || !item.id) continue;
      commands.push({
        id: item.id,
        title: String(item.title || item.id),
        capability: stringList(item.capability),
        riskLevel: String(item.risk_level || "read"),
        supportsDryRun: item.supports_dry_run === true,
        undoStrategy:
          typeof item.undo_strategy === "string" && item.undo_strategy
            ? item.undo_strategy
            : null,
        granted: item.granted === true,
        reason: typeof item.reason === "string" ? item.reason : undefined
      });
    }
    return { ok: true, commands };
  } catch {
    return { ok: false, errorCode: "operator_unreachable" };
  }
}

/** Materialize a plan for one command. The browser sends command_id + params
 * only — argv does not exist on this boundary by construction (§11.1). */
export async function planAdminCommand(
  commandId: string,
  params: Record<string, string> = {},
  options: { dryRun?: boolean } = {}
): Promise<AdminPlanResult> {
  const token = getAdminSessionToken();
  if (!token) return { ok: false, errorCode: "admin_session_invalid" };
  try {
    const response = await operatorPost(
      "/admin/commands/plan",
      { command_id: commandId, params, dry_run: options.dryRun === true },
      { headers: { [ADMIN_SESSION_HEADER]: token } }
    );
    const payload = (await response.json()) as Record<string, unknown>;
    const plan = parseAdminPlan(payload);
    if (response.ok && plan) return { ok: true, plan };
    return { ok: false, errorCode: commandErrorCodeOf(payload) };
  } catch {
    return { ok: false, errorCode: "operator_unreachable" };
  }
}

/**
 * Execute EXACTLY the reviewed plan: plan_id + plan_sha + the plan-generated
 * confirmation phrase when the risk demands one. The server revalidates every
 * precondition (§9.3) and refuses stale plans — a refusal means replan, never
 * retry-harder.
 */
export async function executeAdminPlan(
  plan: AdminPlan,
  confirmation: string | null
): Promise<AdminExecuteResult> {
  const token = getAdminSessionToken();
  if (!token) return { ok: false, errorCode: "admin_session_invalid" };
  try {
    const response = await operatorPost(
      "/admin/commands/execute",
      {
        plan_id: plan.planId,
        plan_sha: plan.planSha,
        ...(confirmation !== null ? { confirmation } : {})
      },
      { headers: { [ADMIN_SESSION_HEADER]: token } }
    );
    const payload = (await response.json()) as Record<string, unknown>;
    const outcome = parseAdminExecuteOutcome(payload);
    if (response.ok && outcome) return { ok: true, outcome };
    return {
      ok: false,
      errorCode: commandErrorCodeOf(payload),
      failedPreconditions: stringList(payload.failed_preconditions)
    };
  } catch {
    return { ok: false, errorCode: "operator_unreachable" };
  }
}

export async function lockAdminSession(): Promise<AdminLockResult> {
  const token = getAdminSessionToken();
  if (!token) return { ok: false, errorCode: "admin_session_invalid" };
  try {
    const response = await operatorPost("/admin/session/lock", {}, {
      headers: { [ADMIN_SESSION_HEADER]: token }
    });
    const payload = (await response.json()) as Record<string, unknown>;
    if (response.ok && payload.ok === true) {
      return { ok: true };
    }
    return { ok: false, errorCode: errorCodeOf(payload) };
  } catch {
    return { ok: false, errorCode: "operator_unreachable" };
  } finally {
    clearAdminSession();
  }
}
