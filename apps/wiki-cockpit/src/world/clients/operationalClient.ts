import { operatorRequest } from "./operatorClient";
import type { RuntimeObservations } from "../../data/runtimeObservations";

export async function loadRuntimeObservations(options?: { signal?: AbortSignal }): Promise<RuntimeObservations> {
  const response = await operatorRequest("/runtime/observations", { signal: options?.signal, cache: "no-store" });
  if (!response.ok) throw new Error("runtime_observation_unavailable");
  const value = await response.json();
  if (!validObservation(value)) throw new Error("runtime_observation_invalid");
  return value;
}

type JsonObject = Record<string, unknown>;
const record = (value: unknown): value is JsonObject => Boolean(value && typeof value === "object" && !Array.isArray(value));
const textOrNull = (value: unknown) => value === null || typeof value === "string";
const textFields = (value: JsonObject, keys: string[]) => keys.every(key => typeof value[key] === "string");

function validRetainedChain(row: JsonObject): boolean {
  const guard = row.guard_admission;
  return (row.run_id === undefined || (typeof row.run_id === "string" && row.run_id === row.effect_key)) &&
    (row.action_path === undefined || typeof row.action_path === "string") &&
    (row.result == null || (record(row.result) && typeof row.result.excerpt === "string" && Array.from(row.result.excerpt).length <= 1600 &&
      typeof row.result.text_sha256 === "string" && /^[a-f0-9]{64}$/.test(row.result.text_sha256) && typeof row.result.truncated === "boolean")) &&
    (row.authorization === undefined || (record(row.authorization) && row.authorization.status === "not_observed")) &&
    (guard === undefined || (record(guard) &&
      ["retained_chain_verified", "not_observed", "unavailable"].includes(String(guard.status)) &&
      ["model", "effort", "error_code"].every(key => textOrNull(guard[key])))) &&
    (row.review === undefined || (record(row.review) &&
      ["not_observed", "failure_resolution_reviewed"].includes(String(row.review.status)) && textOrNull(row.review.head)));
}

// Validate the read model before rendering nested fields. An old or malformed
// endpoint is unavailable, never a substitute "idle" or successful observation.
function validObservation(value: unknown): value is RuntimeObservations {
  if (!record(value) || value.ok !== true || value.schema_version !== "wiki_runtime_observations.v1" || typeof value.observed_at !== "string") return false;
  const operator = value.operator, runtime = value.openclaw;
  if (!record(operator) || !record(operator.frontend) || !textFields(operator, ["started_at", "server_version"]) ||
      !["boot_source_commit", "current_source_commit", "content_source_commit"].every(key => textOrNull(operator[key])) ||
      !["boot_code_sha256", "current_code_sha256"].every(key => operator[key] === undefined || textOrNull(operator[key])) ||
      !(operator.restart_required === null || typeof operator.restart_required === "boolean") ||
      !textOrNull(operator.frontend.entry_sha256) || operator.frontend.source_commit !== null ||
      !["not_served", "observed", "unavailable"].includes(String(operator.frontend.status))) return false;
  if (!record(runtime) || typeof runtime.configured !== "boolean" || runtime.observation_scope !== "retained_local_evidence" ||
      runtime.gateway_status !== "not_observed" || runtime.active_run !== null || runtime.pending_inputs !== null ||
      !record(runtime.usage) || runtime.usage.status !== "not_measured" || runtime.usage.tokens !== null || runtime.usage.cost !== null) return false;
  if (runtime.transport !== undefined && (!record(runtime.transport) || runtime.transport.scope !== "loopback_tcp_only" ||
      !textOrNull(runtime.transport.observed_at) || !["reachable", "unreachable", "not_configured", "unavailable"].includes(String(runtime.transport.status)))) return false;
  if (!Array.isArray(runtime.attempts) || !runtime.attempts.every(row => record(row) &&
      textFields(row, ["profile", "action_id", "effect_key", "attempted_at"]) && textOrNull(row.result_captured_at) && validRetainedChain(row) &&
      ["result_retained", "resolved_without_result", "awaiting_reconciliation"].includes(String(row.status)) &&
      (row.proposal == null || (record(row.proposal) && typeof row.proposal.status === "string" &&
        ["branch", "head", "proposal_head", "approved_base", "material_path", "material_sha256", "result_path"].every(key => {
          const proposal = row.proposal as JsonObject;
          return proposal[key] === undefined || typeof proposal[key] === "string";
        }) &&
        (row.proposal.content_incorporated_in_main === undefined || typeof row.proposal.content_incorporated_in_main === "boolean"))))) return false;
  if (!Array.isArray(runtime.rules) || !runtime.rules.every(row => record(row) &&
      textFields(row, ["rule_id", "profile", "action_id"]) && typeof row.interval_minutes === "number" &&
      textOrNull(row.next_expected_observation_at) && row.scheduler_status === "not_observed" &&
      (row.last_wake === null || (record(row.last_wake) && textFields(row.last_wake, ["observed_at", "mode"]) &&
        typeof row.last_wake.slot === "number" && textOrNull(row.last_wake.effect_key) && textOrNull(row.last_wake.error_code) &&
        ["success", "failure"].includes(String(row.last_wake.status)) &&
        (row.last_wake.new_dispatch === null || typeof row.last_wake.new_dispatch === "boolean"))))) return false;
  return Array.isArray(runtime.native_observations) && runtime.native_observations.every(row => record(row) &&
    typeof row.profile === "string" && row.status === "unavailable" && row.observed_at === null && row.has_active_run === null &&
    row.active_run_ids === null && row.session_status === null && row.error_code === "native_read_api_may_write") &&
    Array.isArray(runtime.errors) && runtime.errors.every(error => typeof error === "string");
}
