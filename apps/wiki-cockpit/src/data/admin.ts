// Admin discovery client (god-mode plan §6.3, §12.1, §14). READ-ONLY by
// construction: this module only ever issues the GET discovery request, it
// holds no token (none exists before the session milestone) and nothing it
// returns can grant capability — the session_state it reports is the server's
// own honest answer. Opening ?dock=admin goes through here and can therefore
// never authorize anything (plan §14.1).

import {
  operatorRestartReason,
  validateOperatorHandshake
} from "../contracts/operatorSecurity.js";
import {
  demoRouteRequested,
  fetchOperatorHealth,
  operatorRequest
} from "../world/clients/operatorClient";

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

// GET /api/admin/capabilities (wiki_admin_capabilities.v1).
export type AdminCapabilities = {
  schema_version: string;
  server_version: string;
  adapter: string | null;
  session_state: AdminSessionState;
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
  return {
    schema_version: String(record.schema_version || ""),
    server_version: String(record.server_version || ""),
    adapter: typeof record.adapter === "string" && record.adapter ? record.adapter : null,
    session_state: record.session_state,
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
    const response = await operatorRequest("/admin/capabilities", {
      method: "GET",
      headers: { accept: "application/json" },
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
    return { kind: "capabilities", payload };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return { kind: "unavailable", reason: "operator_unreachable" };
  }
}
