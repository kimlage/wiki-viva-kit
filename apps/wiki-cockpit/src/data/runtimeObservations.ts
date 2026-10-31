import type { RuntimeProposal } from "./actionBoard";

// This endpoint observes retained evidence. It never claims live Gateway state.
export type RuntimeAttemptObservation = {
  profile: string; action_id: string; effect_key: string; attempted_at: string;
  result_captured_at: string | null;
  status: "result_retained" | "resolved_without_result" | "awaiting_reconciliation";
  run_id?: string; action_path?: string;
  result?: { excerpt: string; text_sha256: string; truncated: boolean } | null;
  authorization?: { status: "not_observed" };
  guard_admission?: { status: "retained_chain_verified" | "not_observed" | "unavailable"; model: string | null; effort: string | null; error_code: string | null };
  review?: { status: "not_observed" | "failure_resolution_reviewed"; head: string | null };
  proposal?: (RuntimeProposal & { content_incorporated_in_main?: boolean; result_path?: string }) | null;
};
export type RuntimeObservations = {
  ok: boolean; schema_version: "wiki_runtime_observations.v1"; observed_at: string;
  operator: {
    started_at: string; boot_source_commit: string | null; current_source_commit: string | null;
    content_source_commit: string | null;
    boot_code_sha256?: string | null; current_code_sha256?: string | null;
    restart_required: boolean | null; server_version: string;
    frontend: { status: "not_served" | "observed" | "unavailable"; entry_sha256: string | null; source_commit: null };
  };
  openclaw: {
    configured: boolean; observation_scope: "retained_local_evidence"; gateway_status: "not_observed";
    active_run: null; pending_inputs: null; usage: { status: "not_measured"; tokens: null; cost: null };
    transport?: { status: "reachable" | "unreachable" | "not_configured" | "unavailable"; scope: "loopback_tcp_only"; observed_at: string | null };
    native_observations: { profile: string; observed_at: null; status: "unavailable";
      has_active_run: null; active_run_ids: null; session_status: null; error_code: "native_read_api_may_write" }[];
    attempts: RuntimeAttemptObservation[];
    rules: { rule_id: string; profile: string; action_id: string; interval_minutes: number;
      last_wake: { observed_at: string; slot: number; mode: string; effect_key: string | null;
        status: "success" | "failure"; error_code: string | null; new_dispatch: boolean | null } | null;
      next_expected_observation_at: string | null; scheduler_status: "not_observed" }[];
    errors: string[];
  };
};
export type RuntimeObservationReader = (options?: { signal?: AbortSignal }) => Promise<RuntimeObservations>;

export function latestAttempt(observation: RuntimeObservations | null, actionId?: string): RuntimeAttemptObservation | undefined {
  return observation?.openclaw.attempts.filter(row => !actionId || row.action_id === actionId)
    .sort((a, b) => b.attempted_at.localeCompare(a.attempted_at))[0];
}
