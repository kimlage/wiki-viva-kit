import type { ExperiencePackComposition, TemporalGraphPayload } from "../types";

export const TEMPORAL_GRAPH_VERSION = "wiki_temporal_graph.v1";
export const TEMPORAL_EVENT_VERSION = "wiki_temporal_event.v1";
export const EXPERIENCE_PACK_COMPOSITION_VERSION = "wiki_experience_pack_composition.v1";

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function nonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

const TEMPORAL_DATE_FIELDS = [
  "occurred_at",
  "recorded_at",
  "valid_from",
  "valid_to",
  "created_at",
  "due_at",
  "completed_at",
  "verified_at",
  "ingested_at",
  "superseded_at"
] as const;
const TEMPORAL_ANCHOR_ORDER = [
  "occurred_at",
  "completed_at",
  "recorded_at",
  "created_at",
  "due_at",
  "verified_at",
  "ingested_at",
  "valid_from",
  "superseded_at",
  "valid_to"
] as const;
const TEMPORAL_PRECISIONS = new Set(["year", "month", "day", "instant"]);
const TEMPORAL_EVENT_KINDS = new Set([
  "activity_recorded",
  "snapshot_recorded",
  "git_commit_recorded",
  "page_updated",
  "source_configured",
  "source_ingested",
  "source_refreshed",
  "source_refresh_due",
  "source_pipeline_advanced",
  "ingestion_recorded",
  "action_created",
  "action_due",
  "action_completed",
  "action_cancelled",
  "action_state_changed",
  "action_state_canonicalized",
  "action_contract_updated",
  "decision_recorded",
  "decision_made",
  "receipt_recorded"
]);
const TEMPORAL_NAMESPACED_KIND_PATTERN = /^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*){1,5}$/;
const TEMPORAL_LANES = new Set(["source", "action", "decision", "receipt", "page", "system", "other"]);
const TEMPORAL_CONFLICTS = [
  "valid_to_before_valid_from",
  "due_at_before_created_at",
  "completed_at_before_created_at",
  "superseded_at_before_valid_from"
] as const;
const TEMPORAL_EVENT_KEYS = [
  "schema_version",
  "event_id",
  "kind",
  "subject_refs",
  "context_refs",
  ...TEMPORAL_DATE_FIELDS,
  "precision",
  "actor",
  "source_refs",
  "evidence_refs",
  "caused_by",
  "supersedes",
  "before",
  "after",
  "confidence",
  "visibility",
  "origin",
  "temporal_conflicts",
  "anchor"
] as const;
const TEMPORAL_GRAPH_KEYS = [
  "schema_version",
  "event_schema_version",
  "repo_id",
  "revision",
  "generated_at",
  "event_count",
  "total_count",
  "returned_count",
  "truncated",
  "next_cursor",
  "page",
  "range",
  "returned_range",
  "summary",
  "diagnostics",
  "events"
] as const;
const REF_PATTERN = /^[a-z][a-z0-9_-]{0,31}:[A-Za-z0-9][A-Za-z0-9._/:-]{0,255}$/;
const EVENT_ID_PATTERN = /^[a-z][a-z0-9._-]{2,159}$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;

type TemporalDateField = typeof TEMPORAL_DATE_FIELDS[number];
type TemporalPoint = { precision: "year" | "month" | "day" | "instant"; lower: bigint; upper: bigint };

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).sort().join(",") === [...keys].sort().join(",");
}

function temporalEventKeys(value: Record<string, unknown>): boolean {
  return exactKeys(value, TEMPORAL_EVENT_KEYS) || exactKeys(value, [...TEMPORAL_EVENT_KEYS, "lane"]);
}

function hasOwn(value: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function leapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function daysInMonth(year: number, month: number): number {
  return [31, leapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1] ?? 0;
}

function utcMillis(year: number, month: number, day: number): number {
  const value = new Date(0);
  value.setUTCHours(0, 0, 0, 0);
  value.setUTCFullYear(year, month - 1, day);
  return value.getTime();
}

function utcMicros(year: number, month: number, day: number): bigint {
  return BigInt(utcMillis(year, month, day)) * 1000n;
}

function temporalPoint(value: unknown): TemporalPoint | null {
  if (typeof value !== "string" || value !== value.trim()) return null;
  const yearMatch = /^(\d{4})$/.exec(value);
  if (yearMatch) {
    const year = Number(yearMatch[1]);
    if (year < 1) return null;
    return { precision: "year", lower: utcMicros(year, 1, 1), upper: utcMicros(year + 1, 1, 1) - 1n };
  }
  const monthMatch = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(value);
  if (monthMatch) {
    const year = Number(monthMatch[1]);
    const month = Number(monthMatch[2]);
    if (year < 1) return null;
    const nextYear = month === 12 ? year + 1 : year;
    const nextMonth = month === 12 ? 1 : month + 1;
    return { precision: "month", lower: utcMicros(year, month, 1), upper: utcMicros(nextYear, nextMonth, 1) - 1n };
  }
  const dayMatch = /^(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/.exec(value);
  if (dayMatch) {
    const year = Number(dayMatch[1]);
    const month = Number(dayMatch[2]);
    const day = Number(dayMatch[3]);
    if (year < 1 || day > daysInMonth(year, month)) return null;
    const lower = utcMicros(year, month, day);
    return { precision: "day", lower, upper: lower + 86_400_000_000n - 1n };
  }
  const instantMatch = /^(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])T([01]\d|2[0-3]):([0-5]\d):([0-5]\d)(?:\.(\d{1,6}))?(Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.exec(value);
  if (!instantMatch) return null;
  const year = Number(instantMatch[1]);
  const month = Number(instantMatch[2]);
  const day = Number(instantMatch[3]);
  if (year < 1 || day > daysInMonth(year, month)) return null;
  const fraction = instantMatch[7] || "";
  const zone = instantMatch[8];
  const base = `${instantMatch[1]}-${instantMatch[2]}-${instantMatch[3]}T${instantMatch[4]}:${instantMatch[5]}:${instantMatch[6]}${zone}`;
  const instantMillis = Date.parse(base);
  if (!Number.isFinite(instantMillis)) return null;
  const instant = BigInt(instantMillis) * 1000n + BigInt(fraction.padEnd(6, "0") || "0");
  return { precision: "instant", lower: instant, upper: instant };
}

function refArrayErrors(
  value: unknown,
  label: string,
  { required = false }: { required?: boolean } = {}
): string[] {
  if (!stringArray(value)) return [`${label} must be a string array`];
  const errors: string[] = [];
  if ((required && value.length === 0) || value.length > 128) errors.push(`${label} has an invalid item count`);
  if (new Set(value).size !== value.length || value.some((item) => !REF_PATTERN.test(item))) {
    errors.push(`${label} contains an invalid or duplicate typed reference`);
  }
  return errors;
}

function temporalEventErrors(value: unknown, index: number): string[] {
  if (!record(value)) return [`events[${index}] must be an object`];
  const errors: string[] = [];
  const label = `events[${index}]`;
  if (!temporalEventKeys(value)) errors.push(`${label} must expose only the temporal event v1 keys`);
  if (value.schema_version !== TEMPORAL_EVENT_VERSION) errors.push(`events[${index}].schema_version is unsupported`);
  if (typeof value.event_id !== "string" || !EVENT_ID_PATTERN.test(value.event_id)) errors.push(`${label}.event_id is invalid`);
  if (
    typeof value.kind !== "string" ||
    value.kind.length > 80 ||
    (!TEMPORAL_EVENT_KINDS.has(value.kind) && !TEMPORAL_NAMESPACED_KIND_PATTERN.test(value.kind))
  ) errors.push(`${label}.kind is unsupported`);
  if (hasOwn(value, "lane") && (typeof value.lane !== "string" || !TEMPORAL_LANES.has(value.lane))) {
    errors.push(`${label}.lane is unsupported`);
  }
  for (const field of ["subject_refs", "context_refs"] as const) {
    errors.push(...refArrayErrors(value[field], `${label}.${field}`, { required: true }));
  }
  for (const field of ["source_refs", "evidence_refs", "caused_by", "supersedes"] as const) {
    errors.push(...refArrayErrors(value[field], `${label}.${field}`));
  }
  const precision = record(value.precision) ? value.precision : null;
  if (!precision) errors.push(`${label}.precision must be an object`);
  else if (
    Object.keys(precision).some((field) => !TEMPORAL_DATE_FIELDS.includes(field as TemporalDateField)) ||
    Object.values(precision).some((item) => typeof item !== "string" || !TEMPORAL_PRECISIONS.has(item))
  ) errors.push(`${label}.precision contains an unsupported field or value`);
  const points = new Map<TemporalDateField, TemporalPoint>();
  for (const field of TEMPORAL_DATE_FIELDS) {
    const raw = value[field];
    if (raw === null) {
      if (precision && hasOwn(precision, field)) errors.push(`${label}.${field} is null but declares precision`);
      continue;
    }
    const point = temporalPoint(raw);
    if (!point) errors.push(`${label}.${field} is not an honest ISO temporal value`);
    else {
      points.set(field, point);
      if (!precision || precision[field] !== point.precision) errors.push(`${label}.${field} precision does not match its value`);
    }
  }
  for (const field of ["before", "after"] as const) {
    if (!record(value[field]) || Object.keys(value[field]).length > 128) errors.push(`${label}.${field} must be an object with at most 128 fields`);
  }
  if (
    !record(value.origin) ||
    Object.keys(value.origin).some((key) => key !== "adapter" && key !== "legacy_kind") ||
    typeof value.origin.adapter !== "string" ||
    value.origin.adapter.length < 1 ||
    value.origin.adapter.length > 120 ||
    (hasOwn(value.origin, "legacy_kind") && (
      typeof value.origin.legacy_kind !== "string" ||
      value.origin.legacy_kind.length < 1 ||
      value.origin.legacy_kind.length > 120
    ))
  ) {
    errors.push(`${label}.origin is invalid`);
  }
  if (value.actor !== null && (
    !record(value.actor) ||
    !exactKeys(value.actor, ["kind", "ref"]) ||
    !["human", "agent", "system", "unknown"].includes(String(value.actor.kind)) ||
    typeof value.actor.ref !== "string" ||
    !REF_PATTERN.test(value.actor.ref)
  )) {
    errors.push(`${label}.actor is invalid`);
  }
  if (!["confirmed", "inferred", "uncertain", "conflicting"].includes(String(value.confidence))) {
    errors.push(`${label}.confidence is invalid`);
  }
  if (value.visibility !== "public" && value.visibility !== "private") errors.push(`${label}.visibility is invalid`);
  const declaredConflicts = stringArray(value.temporal_conflicts) ? value.temporal_conflicts : null;
  if (
    !declaredConflicts ||
    new Set(declaredConflicts).size !== declaredConflicts.length ||
    declaredConflicts.some((conflict) => !TEMPORAL_CONFLICTS.includes(conflict as typeof TEMPORAL_CONFLICTS[number]))
  ) errors.push(`${label}.temporal_conflicts is invalid`);
  const expectedConflicts = [
    ["valid_to", "valid_from", "valid_to_before_valid_from"],
    ["due_at", "created_at", "due_at_before_created_at"],
    ["completed_at", "created_at", "completed_at_before_created_at"],
    ["superseded_at", "valid_from", "superseded_at_before_valid_from"]
  ].filter(([left, right]) => {
    const leftPoint = points.get(left as TemporalDateField);
    const rightPoint = points.get(right as TemporalDateField);
    return Boolean(leftPoint && rightPoint && leftPoint.upper < rightPoint.lower);
  }).map(([, , conflict]) => conflict);
  if (declaredConflicts && JSON.stringify(declaredConflicts) !== JSON.stringify(expectedConflicts)) {
    errors.push(`${label}.temporal_conflicts does not match the declared clocks`);
  }
  if (expectedConflicts.length > 0 && value.confidence !== "conflicting") {
    errors.push(`${label}.confidence must expose temporal conflicts`);
  }
  const expectedAnchorField = TEMPORAL_ANCHOR_ORDER.find((field) => points.has(field));
  if (!expectedAnchorField) {
    if (value.anchor !== null) errors.push(`${label}.anchor must be null when the event is undated`);
  } else if (
    !record(value.anchor) ||
    !exactKeys(value.anchor, ["field", "value", "precision"]) ||
    value.anchor.field !== expectedAnchorField ||
    value.anchor.value !== value[expectedAnchorField] ||
    value.anchor.precision !== precision?.[expectedAnchorField]
  ) {
    errors.push(`${label}.anchor does not match the canonical event clock`);
  }
  return errors;
}

function expectedRange(events: unknown[], basis: "full_result" | "returned_page"): Record<string, unknown> {
  const anchored = events.flatMap((event) => {
    if (!record(event) || !record(event.anchor) || typeof event.anchor.value !== "string") return [];
    const point = temporalPoint(event.anchor.value);
    if (!point || !TEMPORAL_PRECISIONS.has(String(event.anchor.precision))) return [];
    return [{ anchor: event.anchor, point }];
  });
  let from: Record<string, unknown> | null = null;
  let to: Record<string, unknown> | null = null;
  for (const item of anchored) {
    if (!from || item.point.lower < (from.point as TemporalPoint).lower) from = item;
    if (!to || item.point.upper > (to.point as TemporalPoint).upper) to = item;
  }
  return {
    from: from ? (from.anchor as Record<string, unknown>).value : null,
    to: to ? (to.anchor as Record<string, unknown>).value : null,
    from_precision: from ? (from.anchor as Record<string, unknown>).precision : null,
    to_precision: to ? (to.anchor as Record<string, unknown>).precision : null,
    event_count: events.length,
    dated_count: anchored.length,
    undated_count: events.length - anchored.length,
    basis
  };
}

function rangeErrors(
  value: unknown,
  label: string,
  basis: "full_result" | "returned_page",
  events: unknown[]
): string[] {
  const errors: string[] = [];
  const keys = ["from", "to", "from_precision", "to_precision", "event_count", "dated_count", "undated_count", "basis"];
  if (!record(value) || !exactKeys(value, keys)) return [`${label} must expose the exact temporal range v1 keys`];
  for (const field of ["event_count", "dated_count", "undated_count"] as const) {
    if (!nonNegativeInteger(value[field])) errors.push(`${label}.${field} is invalid`);
  }
  for (const side of ["from", "to"] as const) {
    const precisionField = `${side}_precision` as const;
    if (value[side] === null) {
      if (value[precisionField] !== null) errors.push(`${label}.${precisionField} must be null with ${side}`);
    } else {
      const point = temporalPoint(value[side]);
      if (!point || value[precisionField] !== point.precision) errors.push(`${label}.${side} and precision are invalid`);
    }
  }
  if (value.basis !== basis) errors.push(`${label}.basis must equal ${basis}`);
  if (
    nonNegativeInteger(value.event_count) &&
    nonNegativeInteger(value.dated_count) &&
    nonNegativeInteger(value.undated_count) &&
    value.dated_count + value.undated_count !== value.event_count
  ) errors.push(`${label} dated and undated counts do not reconcile`);
  const expected = expectedRange(events, basis);
  if (keys.some((key) => value[key] !== expected[key])) errors.push(`${label} does not match the returned event set`);
  return errors;
}

function countMap(value: unknown): value is Record<string, number> {
  return record(value) && Object.values(value).every(nonNegativeInteger);
}

function canonicalEntries(value: Record<string, number>): [string, number][] {
  return Object.entries(value).sort(([left], [right]) => left.localeCompare(right));
}

function expectedCountMaps(events: unknown[]): {
  byKind: Record<string, number>;
  byContext: Record<string, number>;
  conflictCount: number;
  impreciseCount: number;
} {
  const byKind: Record<string, number> = {};
  const byContext: Record<string, number> = {};
  let conflictCount = 0;
  let impreciseCount = 0;
  for (const event of events) {
    if (!record(event)) continue;
    const kind = String(event.kind ?? "");
    byKind[kind] = (byKind[kind] ?? 0) + 1;
    if (stringArray(event.context_refs)) {
      for (const context of event.context_refs) byContext[context] = (byContext[context] ?? 0) + 1;
    }
    if (Array.isArray(event.temporal_conflicts) && event.temporal_conflicts.length > 0) conflictCount += 1;
    if (record(event.precision) && Object.values(event.precision).some((item) => item === "year" || item === "month")) {
      impreciseCount += 1;
    }
  }
  return { byKind, byContext, conflictCount, impreciseCount };
}

function diagnosticErrors(value: unknown, index: number): string[] {
  const label = `diagnostics[${index}]`;
  if (!record(value) || !exactKeys(value, ["code", "adapter", "subject_ref", "error_codes"])) {
    return [`${label} must expose the exact temporal diagnostic v1 keys`];
  }
  const errors: string[] = [];
  if (value.code !== "temporal_adapter_rejected" && value.code !== "temporal_event_id_collision") {
    errors.push(`${label}.code is unsupported`);
  }
  if (typeof value.adapter !== "string" || value.adapter.length < 1 || value.adapter.length > 120) {
    errors.push(`${label}.adapter is invalid`);
  }
  if (typeof value.subject_ref !== "string" || !REF_PATTERN.test(value.subject_ref)) {
    errors.push(`${label}.subject_ref is invalid`);
  }
  if (
    !stringArray(value.error_codes) ||
    value.error_codes.length < 1 ||
    new Set(value.error_codes).size !== value.error_codes.length ||
    value.error_codes.some((code) => code.length < 1 || code.length > 160)
  ) errors.push(`${label}.error_codes is invalid`);
  return errors;
}

export function temporalGraphContractErrors(
  value: unknown,
  versions: Record<string, string> | undefined
): string[] {
  const errors: string[] = [];
  if (versions?.temporal_graph !== TEMPORAL_GRAPH_VERSION || versions?.temporal_event !== TEMPORAL_EVENT_VERSION) {
    errors.push("manifest temporal graph/event version is unsupported");
  }
  if (!record(value)) return [...errors, "temporal graph must be an object"];
  if (!exactKeys(value, TEMPORAL_GRAPH_KEYS)) errors.push("temporal graph must expose the exact v1 envelope keys");
  if (value.schema_version !== TEMPORAL_GRAPH_VERSION) errors.push("temporal graph schema_version is unsupported");
  if (value.event_schema_version !== TEMPORAL_EVENT_VERSION) errors.push("temporal event schema_version is unsupported");
  if (typeof value.repo_id !== "string" || value.repo_id.length < 1 || value.repo_id.length > 160) {
    errors.push("temporal graph repo_id is invalid");
  }
  if (typeof value.revision !== "string" || !/^sha256:[0-9a-f]{64}$/.test(value.revision)) {
    errors.push("temporal graph revision is invalid");
  }
  if (temporalPoint(value.generated_at)?.precision !== "instant") errors.push("temporal graph generated_at is invalid");
  for (const field of ["event_count", "total_count", "returned_count"] as const) {
    if (!nonNegativeInteger(value[field])) errors.push(`temporal graph ${field} is invalid`);
  }
  if (typeof value.truncated !== "boolean") errors.push("temporal graph truncated flag is invalid");
  if (
    !record(value.page) ||
    !exactKeys(value.page, ["offset", "limit", "remaining_count", "fingerprint"]) ||
    !nonNegativeInteger(value.page.offset) ||
    !nonNegativeInteger(value.page.limit) ||
    !nonNegativeInteger(value.page.remaining_count) ||
    typeof value.page.fingerprint !== "string" ||
    !SHA256_PATTERN.test(value.page.fingerprint)
  ) {
    errors.push("temporal graph page contract is invalid");
  } else if (value.revision !== `sha256:${value.page.fingerprint}`) {
    errors.push("temporal graph page fingerprint does not match revision");
  }
  const diagnostics = Array.isArray(value.diagnostics) ? value.diagnostics : [];
  if (!Array.isArray(value.diagnostics)) errors.push("temporal graph diagnostics must be an array");
  else value.diagnostics.forEach((diagnostic, index) => errors.push(...diagnosticErrors(diagnostic, index)));
  const events = Array.isArray(value.events) ? value.events : [];
  if (!Array.isArray(value.events)) errors.push("temporal graph events must be an array");
  else {
    events.forEach((event, index) => errors.push(...temporalEventErrors(event, index)));
    const ids = events.filter(record).map((event) => event.event_id).filter((id): id is string => typeof id === "string");
    if (new Set(ids).size !== ids.length) errors.push("temporal graph contains duplicate event ids");
    const eventIds = new Set(ids);
    for (const event of events) {
      if (!record(event)) continue;
      for (const field of ["caused_by", "supersedes"] as const) {
        if (!stringArray(event[field])) continue;
        for (const reference of event[field]) {
          if (!reference.startsWith("event:") || !eventIds.has(reference.slice("event:".length))) {
            errors.push(`temporal graph ${field} target is unresolved`);
          }
        }
      }
    }
    if (nonNegativeInteger(value.returned_count) && value.returned_count !== events.length) {
      errors.push("temporal graph returned_count does not match events length");
    }
  }
  errors.push(...rangeErrors(value.range, "temporal graph range", "full_result", events));
  errors.push(...rangeErrors(value.returned_range, "temporal graph returned_range", "returned_page", events));
  if (!record(value.summary) || !exactKeys(value.summary, [
    "scope", "event_count", "by_kind", "by_context", "conflict_count", "imprecise_count", "diagnostic_count"
  ])) {
    errors.push("temporal graph summary must expose the exact v1 keys");
  } else {
    const expected = expectedCountMaps(events);
    if (value.summary.scope !== "full_result" || value.summary.event_count !== value.total_count) {
      errors.push("temporal graph summary does not cover the full result");
    }
    if (!countMap(value.summary.by_kind) || JSON.stringify(canonicalEntries(value.summary.by_kind)) !== JSON.stringify(canonicalEntries(expected.byKind))) {
      errors.push("temporal graph summary.by_kind does not match events");
    }
    if (!countMap(value.summary.by_context) || JSON.stringify(canonicalEntries(value.summary.by_context)) !== JSON.stringify(canonicalEntries(expected.byContext))) {
      errors.push("temporal graph summary.by_context does not match events");
    }
    if (value.summary.conflict_count !== expected.conflictCount) errors.push("temporal graph summary.conflict_count does not match events");
    if (value.summary.imprecise_count !== expected.impreciseCount) errors.push("temporal graph summary.imprecise_count does not match events");
    if (value.summary.diagnostic_count !== diagnostics.length) errors.push("temporal graph summary.diagnostic_count does not match diagnostics");
  }
  if (
    nonNegativeInteger(value.event_count) &&
    nonNegativeInteger(value.total_count) &&
    nonNegativeInteger(value.returned_count) &&
    (
      value.event_count !== value.total_count ||
      value.returned_count !== value.total_count ||
      value.truncated !== false ||
      value.next_cursor !== null ||
      !record(value.page) ||
      value.page.offset !== 0 ||
      value.page.limit !== value.returned_count ||
      value.page.remaining_count !== 0
    )
  ) {
    errors.push("static temporal graph must be complete and non-truncated");
  }
  return errors;
}

export function experiencePackContractErrors(
  value: unknown,
  versions: Record<string, string> | undefined
): string[] {
  const errors: string[] = [];
  if (versions?.experience_pack_composition !== EXPERIENCE_PACK_COMPOSITION_VERSION) {
    errors.push("manifest experience pack composition version is unsupported");
  }
  if (!record(value)) return [...errors, "experience pack composition must be an object"];
  if (Object.keys(value).sort().join(",") !== [
    "block_packages",
    "composition_sha256",
    "core_version",
    "packs",
    "presentation",
    "schema_version",
    "slots"
  ].sort().join(",")) errors.push("experience pack composition must expose the exact v1 fields");
  if (value.schema_version !== EXPERIENCE_PACK_COMPOSITION_VERSION) errors.push("experience pack schema_version is unsupported");
  if (value.core_version !== "8.0.0") errors.push("experience pack core_version is unsupported");
  const packPattern = /^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/;
  const semverPattern = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/;
  const capabilityPattern = /^[a-z][a-z0-9_.-]*$/;
  const packs = Array.isArray(value.packs) ? value.packs : [];
  if (!Array.isArray(value.packs) || packs.some((pack) => (
    !record(pack) ||
    Object.keys(pack).sort().join(",") !== "id,version" ||
    typeof pack.id !== "string" ||
    !packPattern.test(pack.id) ||
    typeof pack.version !== "string" ||
    !semverPattern.test(pack.version)
  ))) {
    errors.push("experience pack list is invalid");
  }
  const packIds = packs.filter(record).map((pack) => String(pack.id));
  if (
    new Set(packIds).size !== packIds.length ||
    JSON.stringify(packIds) !== JSON.stringify([...packIds].sort())
  ) {
    errors.push("experience pack list must be unique and canonical");
  }
  if (
    !stringArray(value.block_packages) ||
    value.block_packages.some((item) => !capabilityPattern.test(item)) ||
    JSON.stringify(value.block_packages) !== JSON.stringify([...new Set(value.block_packages)].sort())
  ) errors.push("experience pack block_packages must be a unique canonical string array");
  const slotKinds = ["views", "commands", "operations", "timelines"] as const;
  if (
    !record(value.slots) ||
    Object.keys(value.slots).sort().join(",") !== [...slotKinds].sort().join(",")
  ) errors.push("experience pack slots must expose the exact v1 kinds");
  else {
    const installed = new Set(packIds);
    const seenContributions = new Set<string>();
    for (const kind of slotKinds) {
      const rows = value.slots[kind];
      if (!Array.isArray(rows)) errors.push(`experience pack slots.${kind} must be an array`);
      else {
        const identities: string[][] = [];
        const seenIdentities = new Set<string>();
        const rowsBySlot = new Map<string, Record<string, unknown>[]>();
        rows.forEach((row, index) => {
          if (
            !record(row) ||
            Object.keys(row).sort().join(",") !== "contribution,mode,pack,slot" ||
            typeof row.pack !== "string" ||
            !installed.has(row.pack) ||
            typeof row.slot !== "string" ||
            !row.slot.startsWith(`${kind.slice(0, -1)}.`) ||
            !capabilityPattern.test(row.slot) ||
            typeof row.contribution !== "string" ||
            !row.contribution.startsWith(`${row.pack}.`) ||
            !capabilityPattern.test(row.contribution) ||
            (row.mode !== "append" && row.mode !== "exclusive")
          ) {
            errors.push(`pack slot ${kind}[${index}] is invalid or unnamespaced`);
            return;
          }
          const identity = [row.pack, row.slot, row.contribution, row.mode];
          const identityKey = JSON.stringify(identity);
          const contributionKey = `${kind}:${row.contribution}`;
          if (seenIdentities.has(identityKey) || seenContributions.has(contributionKey)) {
            errors.push(`pack slot ${kind}[${index}] identity/contribution is duplicated`);
          }
          seenIdentities.add(identityKey);
          seenContributions.add(contributionKey);
          identities.push(identity);
          rowsBySlot.set(row.slot, [...(rowsBySlot.get(row.slot) ?? []), row]);
        });
        const canonical = [...identities].sort((left, right) => {
          const leftKey = JSON.stringify(left);
          const rightKey = JSON.stringify(right);
          return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0;
        });
        if (JSON.stringify(identities) !== JSON.stringify(canonical)) {
          errors.push(`experience pack slots.${kind} must be canonical`);
        }
        for (const [slot, slotRows] of rowsBySlot) {
          if (slotRows.length > 1 && slotRows.some((row) => row.mode === "exclusive")) {
            errors.push(`experience pack slots.${kind} exclusive slot ${slot} conflicts`);
          }
        }
      }
    }
  }
  const presentation = value.presentation;
  const localePattern = /^[a-z]{2}(?:-[A-Z]{2})?$/;
  const localeLabels = new Map<string, Record<string, unknown>>();
  if (
    !record(presentation) ||
    Object.keys(presentation).sort().join(",") !== "default_locale,locales" ||
    presentation.default_locale !== "en" ||
    !record(presentation.locales)
  ) {
    errors.push("experience pack presentation contract is invalid");
  } else {
    const locales = presentation.locales;
    const localeIds = Object.keys(locales);
    if (
      !localeIds.includes("en") ||
      !localeIds.includes("es") ||
      !localeIds.includes("pt-BR") ||
      JSON.stringify(localeIds) !== JSON.stringify([...localeIds].sort())
    ) errors.push("experience pack presentation locales must include canonical en, es and pt-BR");
    for (const [locale, labels] of Object.entries(locales)) {
      if (!localePattern.test(locale) || !record(labels)) {
        errors.push(`experience pack presentation locale ${locale} is invalid`);
        continue;
      }
      const identifiers = Object.keys(labels);
      if (JSON.stringify(identifiers) !== JSON.stringify([...identifiers].sort())) {
        errors.push(`experience pack presentation labels for ${locale} must be canonical`);
      }
      for (const [identifier, label] of Object.entries(labels)) {
        const owners = packIds.filter((packId) => (
          identifier === packId ||
          identifier.startsWith(`${packId}.`) ||
          identifier.startsWith(`${packId.replaceAll("-", "_")}_`)
        ));
        if (
          !capabilityPattern.test(identifier) ||
          typeof label !== "string" ||
          label !== label.trim() ||
          label.length < 1 ||
          label.length > 96 ||
          /[\u0000-\u001f\u007f]/.test(label) ||
          owners.length !== 1
        ) errors.push(`experience pack presentation label ${locale}:${identifier} is invalid or unowned`);
      }
      localeLabels.set(locale, labels);
    }
    const referenceKeys = [...(localeLabels.get("en") ? Object.keys(localeLabels.get("en")!) : [])];
    for (const [locale, labels] of localeLabels) {
      if (JSON.stringify(Object.keys(labels)) !== JSON.stringify(referenceKeys)) {
        errors.push(`experience pack presentation locale ${locale} lacks exact key parity`);
      }
    }
    const requiredLabels = new Set(packIds);
    if (record(value.slots)) {
      for (const kind of slotKinds) {
        const rows = value.slots[kind];
        if (Array.isArray(rows)) rows.forEach((row) => {
          if (record(row) && typeof row.contribution === "string") requiredLabels.add(row.contribution);
        });
      }
    }
    for (const [locale, labels] of localeLabels) {
      if ([...requiredLabels].some((identifier) => !(identifier in labels))) {
        errors.push(`experience pack presentation labels for ${locale} are incomplete`);
      }
    }
  }
  if (typeof value.composition_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(value.composition_sha256)) {
    errors.push("experience pack composition_sha256 is invalid");
  }
  return errors;
}

export function asTemporalGraphPayload(value: unknown): TemporalGraphPayload {
  return value as TemporalGraphPayload;
}

export function asExperiencePackComposition(value: unknown): ExperiencePackComposition {
  return value as ExperiencePackComposition;
}
