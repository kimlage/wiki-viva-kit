// Contract parity test for SourceEntity vs the JSON emitted by
// wiki_core/web/sources.py (`wiki_web_source_entities.v1`). The backend grew
// `sync.event_closure` and `lifecycle` additively (no version bump); the TS
// type declares both as OPTIONAL so older snapshots stay valid. This test
// pins that contract from both sides: the shipped sample snapshot must
// validate WITH the fields present, and a record WITHOUT them must still
// validate.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { SourceEntitiesPayload, SourceEntity } from "../types";

const SOURCE_ENTITIES_VERSION = "wiki_web_source_entities.v1";

const EVENT_CLOSURE_KEYS = ["consolidated_into", "reviewed_no_change", "no_change", "gate_state"] as const;

const LIFECYCLE_STRING_KEYS = [
  "state",
  "freshness_state",
  "last_attempt_state",
  "pipeline_stage",
  "adoption_state",
  "last_sync_success_at",
  "last_ingested_at",
  "last_attempt_at",
  "reviewed_no_change_receipt",
  "accepted_ref",
  "blocked_reason"
] as const;

const LIFECYCLE_STRING_ARRAY_KEYS = [
  "emitted_page_ids",
  "emitted_action_ids",
  "proposal_ids",
  "secret_safe_log_refs",
  "authoring_error_codes"
] as const;

const LIFECYCLE_KEYS = [
  ...LIFECYCLE_STRING_KEYS,
  ...LIFECYCLE_STRING_ARRAY_KEYS,
  "pipeline_stage_timestamps",
  "raw_artifact_count"
] as const;

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).sort().join(",") === [...keys].sort().join(",");
}

function eventClosureErrors(value: unknown, label: string): string[] {
  if (value === undefined) return [];
  if (!record(value)) return [`${label} must be an object when present`];
  const errors: string[] = [];
  if (!exactKeys(value, EVENT_CLOSURE_KEYS)) errors.push(`${label} must expose the exact event closure keys`);
  for (const key of ["consolidated_into", "no_change"] as const) {
    if (!stringArray(value[key])) errors.push(`${label}.${key} must be a string array`);
  }
  if (typeof value.reviewed_no_change !== "boolean") errors.push(`${label}.reviewed_no_change must be a boolean`);
  if (typeof value.gate_state !== "string") errors.push(`${label}.gate_state must be a string`);
  return errors;
}

function lifecycleErrors(value: unknown, label: string): string[] {
  if (value === undefined) return [];
  if (!record(value)) return [`${label} must be an object when present`];
  const errors: string[] = [];
  if (!exactKeys(value, LIFECYCLE_KEYS)) errors.push(`${label} must expose the exact lifecycle projection keys`);
  for (const key of LIFECYCLE_STRING_KEYS) {
    if (typeof value[key] !== "string") errors.push(`${label}.${key} must be a string`);
  }
  for (const key of LIFECYCLE_STRING_ARRAY_KEYS) {
    if (!stringArray(value[key])) errors.push(`${label}.${key} must be a string array`);
  }
  const timestamps = value.pipeline_stage_timestamps;
  if (!record(timestamps) || Object.values(timestamps).some((item) => typeof item !== "string")) {
    errors.push(`${label}.pipeline_stage_timestamps must map stage to string timestamp`);
  }
  const count = value.raw_artifact_count;
  if (typeof count !== "number" || !Number.isInteger(count) || count < 0) {
    errors.push(`${label}.raw_artifact_count must be a non-negative integer`);
  }
  return errors;
}

function sourceEntityErrors(value: unknown, label: string): string[] {
  if (!record(value)) return [`${label} must be an object`];
  const errors: string[] = [];
  if (!record(value.sync)) errors.push(`${label}.sync must be an object`);
  else errors.push(...eventClosureErrors(value.sync.event_closure, `${label}.sync.event_closure`));
  errors.push(...lifecycleErrors(value.lifecycle, `${label}.lifecycle`));
  return errors;
}

function loadPayload(relative: string): SourceEntitiesPayload {
  const raw = readFileSync(resolve(process.cwd(), "public/sample-snapshot", relative), "utf8");
  return JSON.parse(raw) as SourceEntitiesPayload;
}

describe("source entities contract parity", () => {
  it("validates the sample snapshot sources with lifecycle and event closure present", () => {
    const payload = loadPayload("source_entities.json");
    expect(payload.schema_version).toBe(SOURCE_ENTITIES_VERSION);
    expect(payload.sources.length).toBeGreaterThan(0);
    for (const [index, source] of payload.sources.entries()) {
      const label = `sources[${index}]`;
      // The current backend always emits both additive fields.
      expect(source.sync.event_closure, `${label}.sync.event_closure`).toBeDefined();
      expect(source.lifecycle, `${label}.lifecycle`).toBeDefined();
      expect(sourceEntityErrors(source, label)).toEqual([]);
    }
  });

  it("validates the source_lifecycle scenario snapshot", () => {
    const payload = loadPayload("scenarios/source_lifecycle/source_entities.json");
    expect(payload.schema_version).toBe(SOURCE_ENTITIES_VERSION);
    expect(payload.sources.length).toBeGreaterThan(0);
    for (const [index, source] of payload.sources.entries()) {
      expect(sourceEntityErrors(source, `sources[${index}]`)).toEqual([]);
    }
  });

  it("accepts a source entity with lifecycle and event closure absent (older snapshots)", () => {
    const payload = loadPayload("source_entities.json");
    const stripped = structuredClone(payload.sources[0]) as Record<string, unknown>;
    delete stripped.lifecycle;
    delete (stripped.sync as Record<string, unknown>).event_closure;
    expect(sourceEntityErrors(stripped, "stripped")).toEqual([]);
    // Compile-time parity: both fields are optional on the TS type.
    const typed: SourceEntity = stripped as unknown as SourceEntity;
    expect(typed.lifecycle).toBeUndefined();
    expect(typed.sync.event_closure).toBeUndefined();
  });

  it("rejects malformed lifecycle and event closure shapes", () => {
    const payload = loadPayload("source_entities.json");
    const broken = structuredClone(payload.sources[0]) as Record<string, unknown>;
    (broken.lifecycle as Record<string, unknown>).raw_artifact_count = "3";
    (broken.lifecycle as Record<string, unknown>).emitted_page_ids = [7];
    ((broken.sync as Record<string, unknown>).event_closure as Record<string, unknown>).reviewed_no_change = "yes";
    expect(sourceEntityErrors(broken, "broken")).toEqual([
      "broken.sync.event_closure.reviewed_no_change must be a boolean",
      "broken.lifecycle.emitted_page_ids must be a string array",
      "broken.lifecycle.raw_artifact_count must be a non-negative integer"
    ]);
  });
});
