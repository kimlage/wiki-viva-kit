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

// Validate the read model before rendering nested fields. An old or malformed
// endpoint is unavailable, never a substitute "idle" or successful observation.
function validObservation(value: unknown): value is RuntimeObservations {
  if (!record(value) || value.ok !== true || value.schema_version !== "wiki_runtime_observations.v1" || typeof value.observed_at !== "string") return false;
  const operator = value.operator;
  if (!record(operator) || !record(operator.frontend) || !textFields(operator, ["started_at", "server_version"]) ||
      !["boot_source_commit", "current_source_commit", "content_source_commit"].every(key => textOrNull(operator[key])) ||
      !["boot_code_sha256", "current_code_sha256"].every(key => operator[key] === undefined || textOrNull(operator[key])) ||
      !(operator.restart_required === null || typeof operator.restart_required === "boolean") ||
      !textOrNull(operator.frontend.entry_sha256) || operator.frontend.source_commit !== null ||
      !["not_served", "observed", "unavailable"].includes(String(operator.frontend.status))) return false;
  return true;
}
