import type { SourceEntity } from "../types";
import type { ExecutorRoute } from "./sourceAccess";

export function savedSourceRoute(source: SourceEntity, routes: ExecutorRoute[]): ExecutorRoute | undefined {
  const saved = source.access_policy?.connection || source.access_policy?.execution;
  if (saved) return routes.find(route => route.connectionId === saved.connection_id && route.profile === saved.profile && route.targetProfile === saved.target_profile);
  return routes.length === 1 ? routes[0] : undefined;
}

export type SourceConnectionState = "loading" | "testing" | "queued" | "needs_context" | "not_configured" | "unverified" | "verified" | "revoked" | "expired" | "no_access" | "executor_unavailable" | "approval" | "busy" | "paused" | "identity_needed" | "indeterminate" | "authorization_hold";

// A saved pointer or a native catalogue is not observed access. Only an exact,
// dated source observation may claim identity, permissions, revocation or expiry.
export function sourceConnectionState(source: SourceEntity, { loading = false, error = "", available = false, accountFound = false, bindingMatches = false, accountsAvailable = false, unresolved = false, needsContext = false, pending = false, queued = false, now = Date.now(), bindingSha }: {
  loading?: boolean; error?: string; available?: boolean; accountFound?: boolean; bindingMatches?: boolean; accountsAvailable?: boolean; unresolved?: boolean; needsContext?: boolean; pending?: boolean; queued?: boolean; now?: number; bindingSha?: string;
}): SourceConnectionState {
  if (loading) return "loading";
  if (needsContext && !error) return "needs_context";
  if (queued && !error) return "queued";
  if (pending && !error) return "testing";
  if (["source_authorization_unavailable", "source_authorization_denied", "authority_account_enforcement_required"].includes(error)) return "authorization_hold";
  if (unresolved || error === "source_read_result_unknown") return "indeterminate";
  if (error === "profile_stopped") return "paused";
  if (error === "source_identity_ambiguous") return "identity_needed";
  if (error === "native_operation_approval_pending") return "approval";
  if (["native_session_busy", "native_context_waiting"].includes(error)) return "busy";
  if (["authority_blocked", "wrong_account"].includes(error)) return "no_access";
  if (error) return ["executor_unavailable", "source_host_standalone", "source_host_not_allowed", "authorization_missing", "executor_profile_mismatch"].includes(error) ? "executor_unavailable" : "indeterminate";
  const access = source.access, policy = source.access_policy;
  const evidence = access && Boolean(bindingSha) && access.binding_sha256 === bindingSha && Boolean(access.evidence_ref) &&
    Number.isFinite(Date.parse(access.checked_at)) && Date.parse(access.checked_at) <= now && Date.parse(access.valid_until) > now;
  if (evidence) {
    if (access.status === "revoked") return "revoked";
    if (access.status === "session_expired") return "expired";
    if (["authority_blocked", "wrong_account", "identity_mismatch"].includes(access.status)) return "no_access";
    if (access.status === "executor_unavailable") return "executor_unavailable";
    if (access.status === "awaiting_approval") return "approval";
    if (access.status === "execution_unknown") return "indeterminate";
    if (available && accountFound && bindingMatches && accountsAvailable && access.status === "verified" && access.verified && policy?.expected_identity && access.confirmed_identity === policy.expected_identity &&
      policy.requested_scopes.every(scope => access.granted_scopes.includes(scope))) return "verified";
  }
  if (!available) return "executor_unavailable";
  return accountFound || Boolean(policy?.connection || policy?.execution) ? "unverified" : "not_configured";
}
