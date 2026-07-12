import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

export const RELEASE_MATRIX_SCHEMA = "wiki_playwright_release_matrix.v1";
export const RELEASE_MATRIX_CONTRACT_VERSION = 2;
export const PREFLIGHT_TIMEOUT_MS = 15_000;
export const PREFLIGHT_MAX_RESPONSE_BYTES = 64 * 1024 * 1024;
export const REQUIRED_DOWNSTREAM_VERSIONS = Object.freeze({
  snapshot: "wiki_web_snapshot.v2",
  runtime: "wiki_world_runtime.v8",
  server: "wiki_web_server.v6",
  temporalGraph: "wiki_temporal_graph.v1",
  temporalEvent: "wiki_temporal_event.v1",
  experiencePackComposition: "wiki_experience_pack_composition.v1",
  experiencePackCore: "8.0.0"
});

export const DOWNSTREAM_ENV_KEYS = Object.freeze([
  "WIKI_COCKPIT_SNAPSHOT_URL",
  "WIKI_COCKPIT_REAL_BASE_URL",
  "WIKI_COCKPIT_EXPECT_REPO_ID",
  "WIKI_COCKPIT_EXPECT_SNAPSHOT_REVISION",
  "WIKI_COCKPIT_EXPECT_SNAPSHOT_HASH",
  "WIKI_COCKPIT_EXPECT_CONSUMER_HEAD",
  "WIKI_COCKPIT_EXPECT_PUBLIC_RELEASE_SHA",
  "WIKI_COCKPIT_EXPECT_ADAPTER_HASH",
  "WIKI_COCKPIT_EXPECT_SNAPSHOT_VERSION",
  "WIKI_COCKPIT_EXPECT_RUNTIME_VERSION",
  "WIKI_COCKPIT_EXPECT_SERVER_VERSION",
  "WIKI_COCKPIT_EXPECT_TEMPORAL_GRAPH_VERSION",
  "WIKI_COCKPIT_EXPECT_TEMPORAL_EVENT_VERSION",
  "WIKI_COCKPIT_EXPECT_EXPERIENCE_PACK_COMPOSITION_VERSION",
  "WIKI_COCKPIT_EXPECT_COMPOSITION_SHA256",
  "WIKI_COCKPIT_EXPECT_ACTIVE_PACKS",
  "WIKI_COCKPIT_EXPECT_CAPABILITIES",
  "WIKI_COCKPIT_MIN_PAGES"
]);

export const REQUIRED_OPERATOR_CAPABILITIES = Object.freeze([
  "operator_security_v2",
  "cors_default_deny_v1"
]);

export const REQUIRED_SNAPSHOT_CAPABILITIES = Object.freeze([
  "temporal_graph",
  "experience_packs"
]);
export const DOWNSTREAM_ADAPTER_MANIFEST_SCHEMA = "wiki_downstream_adapter_manifest.v1";
export const DOWNSTREAM_ADAPTER_MANIFEST_PATH = "wiki.adapter-manifest.json";
const MAX_ADAPTER_FILES = 256;
const MAX_ADAPTER_FILE_BYTES = 16 * 1024 * 1024;
const MAX_ADAPTER_TOTAL_BYTES = 64 * 1024 * 1024;
const BLOCKED_ADAPTER_ROOTS = new Set([
  ".git",
  ".wiki-viva",
  "data/raw",
  "data/derived",
  "memories",
  "memorias",
  "output",
  "private",
  "test-results"
]);
const BLOCKED_ADAPTER_SEGMENTS = new Set([
  "__pycache__",
  ".playwright-cli",
  "coverage",
  "dist",
  "node_modules",
  "playwright-report",
  "test-results"
]);
const SENSITIVE_ADAPTER_STEMS = new Set([
  "authorization", "client_secret", "cookie", "credential", "credentials",
  "id_dsa", "id_ecdsa", "id_ed25519", "id_rsa", "password", "private_key",
  "secret", "secrets", "session", "token"
]);

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value)
      .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
      .map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

export function sha256CanonicalJson(value) {
  return crypto.createHash("sha256").update(canonicalJson(value), "utf8").digest("hex");
}

function canonicalRepoRelative(raw, label) {
  if (
    typeof raw !== "string" ||
    !raw ||
    raw !== raw.trim() ||
    raw.includes("\0") ||
    raw.includes("\\") ||
    raw.startsWith("/") ||
    raw.startsWith("./") ||
    raw.startsWith("~") ||
    /^[A-Za-z]:/.test(raw)
  ) {
    throw new Error(`${label} must be one canonical repo-relative POSIX path`);
  }
  const parts = raw.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) {
    throw new Error(`${label} must be one canonical repo-relative POSIX path`);
  }
  return parts.join("/");
}

function validateAdapterFilePath(raw) {
  const relative = canonicalRepoRelative(raw, "adapter file");
  if (relative === DOWNSTREAM_ADAPTER_MANIFEST_PATH) {
    throw new Error("adapter manifest must not include itself");
  }
  const parts = relative.split("/").map((part) => part.toLowerCase());
  if (parts.at(-1) === "wiki-cockpit.config.json") {
    throw new Error("adapter manifest must not include wiki-cockpit.config.json (hash cycle)");
  }
  const rootOne = parts[0];
  const rootTwo = parts.slice(0, 2).join("/");
  if (
    BLOCKED_ADAPTER_ROOTS.has(rootOne) ||
    BLOCKED_ADAPTER_ROOTS.has(rootTwo) ||
    parts.some((part) => BLOCKED_ADAPTER_SEGMENTS.has(part))
  ) {
    throw new Error(`adapter file ${relative} crosses a private/raw/derived/generated boundary`);
  }
  for (const part of parts) {
    if (part === ".env" || part.startsWith(".env.")) {
      throw new Error(`adapter file ${relative} has a sensitive name`);
    }
    const stem = part.replace(/^\.+/, "").split(".", 1)[0];
    if (
      SENSITIVE_ADAPTER_STEMS.has(stem) ||
      /(?:^|[._-])(?:secret|secrets|token|tokens|password|credentials?|cookie|session|private[-_]?key)(?:[._-]|$)/.test(part)
    ) {
      throw new Error(`adapter file ${relative} has a sensitive name`);
    }
  }
  return relative;
}

function gitCheck(repoRoot, args, label) {
  const result = spawnSync("git", args, {
    cwd: repoRoot,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (result.error || result.status !== 0) {
    throw new Error(`${label} is not tracked by the consumer repository`);
  }
  return result.stdout;
}

function requireTrackedClean(repoRoot, relative, label) {
  gitCheck(repoRoot, ["ls-files", "--error-unmatch", "--", relative], label);
  const status = spawnSync("git", ["status", "--porcelain=v1", "--", relative], {
    cwd: repoRoot,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (status.error || status.status !== 0 || status.stdout.trim()) {
    throw new Error(`${label} must match the clean consumer HEAD`);
  }
}

function readSafeAdapterFile(repoRoot, relative, label) {
  const root = fs.realpathSync(repoRoot);
  let current = root;
  for (const part of relative.split("/")) {
    current = path.join(current, part);
    const state = fs.lstatSync(current);
    if (state.isSymbolicLink()) throw new Error(`${label} must not traverse a symlink`);
    if (current !== path.join(root, ...relative.split("/")) && !state.isDirectory()) {
      throw new Error(`${label} has a non-directory ancestor`);
    }
  }
  const resolved = fs.realpathSync(current);
  if (resolved !== root && !resolved.startsWith(`${root}${path.sep}`)) {
    throw new Error(`${label} escapes the consumer repository`);
  }
  const descriptor = fs.openSync(current, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
  try {
    const state = fs.fstatSync(descriptor);
    if (!state.isFile()) throw new Error(`${label} must be a regular file`);
    if (state.nlink !== 1) throw new Error(`${label} must not be hard-linked`);
    if (state.size > MAX_ADAPTER_FILE_BYTES) throw new Error(`${label} exceeds the adapter file size limit`);
    const raw = fs.readFileSync(descriptor);
    if (raw.byteLength > MAX_ADAPTER_FILE_BYTES) throw new Error(`${label} exceeds the adapter file size limit`);
    return raw;
  } finally {
    fs.closeSync(descriptor);
  }
}

export function verifyDownstreamAdapterManifest(
  repoRoot,
  manifestPath = DOWNSTREAM_ADAPTER_MANIFEST_PATH,
  expectedHash = ""
) {
  const root = fs.realpathSync(repoRoot);
  const gitRoot = gitCheck(root, ["rev-parse", "--show-toplevel"], "consumer repository").trim();
  if (fs.realpathSync(gitRoot) !== root) throw new Error("adapter manifest root is not the exact consumer Git root");
  const relative = canonicalRepoRelative(manifestPath, "adoption.adapter_manifest");
  if (relative !== DOWNSTREAM_ADAPTER_MANIFEST_PATH) {
    throw new Error(`adoption.adapter_manifest must equal ${DOWNSTREAM_ADAPTER_MANIFEST_PATH}`);
  }
  requireTrackedClean(root, relative, "adapter manifest");
  const manifestRaw = readSafeAdapterFile(root, relative, "adapter manifest");
  if (manifestRaw.byteLength > 1024 * 1024) throw new Error("adapter manifest exceeds the 1MiB limit");
  let manifest;
  try {
    manifest = JSON.parse(manifestRaw.toString("utf8"));
  } catch {
    throw new Error("adapter manifest is not valid JSON");
  }
  if (
    !manifest ||
    Array.isArray(manifest) ||
    typeof manifest !== "object" ||
    Object.keys(manifest).sort().join(",") !== "adapter_sha256,files,schema_version" ||
    manifest.schema_version !== DOWNSTREAM_ADAPTER_MANIFEST_SCHEMA ||
    !Array.isArray(manifest.files) ||
    manifest.files.length < 1 ||
    manifest.files.length > MAX_ADAPTER_FILES
  ) {
    throw new Error("adapter manifest shape/schema is invalid");
  }
  const records = [];
  let totalBytes = 0;
  for (const [index, record] of manifest.files.entries()) {
    if (
      !record ||
      Array.isArray(record) ||
      typeof record !== "object" ||
      Object.keys(record).sort().join(",") !== "bytes,path,sha256"
    ) {
      throw new Error(`adapter manifest file ${index} shape is invalid`);
    }
    const file = validateAdapterFilePath(record.path);
    if (!/^[0-9a-f]{64}$/.test(String(record.sha256 || ""))) {
      throw new Error(`adapter manifest file ${index} hash is invalid`);
    }
    if (!Number.isSafeInteger(record.bytes) || record.bytes < 0 || record.bytes > MAX_ADAPTER_FILE_BYTES) {
      throw new Error(`adapter manifest file ${index} byte count is invalid`);
    }
    requireTrackedClean(root, file, `adapter file ${index}`);
    const raw = readSafeAdapterFile(root, file, `adapter file ${index}`);
    const digest = crypto.createHash("sha256").update(raw).digest("hex");
    if (digest !== record.sha256 || raw.byteLength !== record.bytes) {
      throw new Error(`adapter manifest file ${index} hash/size is stale`);
    }
    totalBytes += raw.byteLength;
    records.push({ path: file, sha256: digest, bytes: raw.byteLength });
  }
  if (totalBytes > MAX_ADAPTER_TOTAL_BYTES) throw new Error("adapter manifest exceeds the aggregate size limit");
  const ordered = [...records].sort((left, right) => left.path < right.path ? -1 : left.path > right.path ? 1 : 0);
  if (JSON.stringify(records) !== JSON.stringify(ordered)) throw new Error("adapter manifest files are not canonical");
  if (new Set(records.map((record) => record.path)).size !== records.length) {
    throw new Error("adapter manifest files are not unique");
  }
  const actualHash = sha256CanonicalJson({
    schema_version: DOWNSTREAM_ADAPTER_MANIFEST_SCHEMA,
    files: records
  });
  const declaredHash = String(manifest.adapter_sha256 || "").toLowerCase();
  if (
    !/^[0-9a-f]{64}$/.test(declaredHash) ||
    declaredHash !== actualHash ||
    (expectedHash && declaredHash !== String(expectedHash).toLowerCase())
  ) {
    throw new Error("adapter manifest hash does not match its canonical file inventory and expectation");
  }
  return {
    schema_version: DOWNSTREAM_ADAPTER_MANIFEST_SCHEMA,
    manifest: relative,
    adapter_sha256: actualHash,
    file_count: records.length
  };
}

function parseExpectedActivePacks(raw, errors) {
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    errors.push("WIKI_COCKPIT_EXPECT_ACTIVE_PACKS must be an explicit JSON array; [] is the valid empty state");
    return [];
  }
  if (!Array.isArray(parsed)) {
    errors.push("WIKI_COCKPIT_EXPECT_ACTIVE_PACKS must be an explicit JSON array; [] is the valid empty state");
    return [];
  }
  const packs = [];
  const seen = new Set();
  for (const [index, pack] of parsed.entries()) {
    if (
      !pack ||
      Array.isArray(pack) ||
      typeof pack !== "object" ||
      Object.keys(pack).sort().join(",") !== "id,version" ||
      !/^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/.test(String(pack.id || "")) ||
      !/^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$/.test(String(pack.version || ""))
    ) {
      errors.push(`WIKI_COCKPIT_EXPECT_ACTIVE_PACKS[${index}] must contain only a valid id and exact semantic version`);
      continue;
    }
    if (seen.has(pack.id)) {
      errors.push(`WIKI_COCKPIT_EXPECT_ACTIVE_PACKS contains duplicate pack ${pack.id}`);
      continue;
    }
    seen.add(pack.id);
    packs.push({ id: pack.id, version: pack.version });
  }
  const canonicalOrder = [...packs].sort((left, right) => left.id < right.id ? -1 : left.id > right.id ? 1 : 0);
  if (JSON.stringify(packs) !== JSON.stringify(canonicalOrder)) {
    errors.push("WIKI_COCKPIT_EXPECT_ACTIVE_PACKS must be ordered canonically by pack id");
  }
  return packs;
}

const TEMPORAL_DATE_FIELDS = Object.freeze([
  "occurred_at", "recorded_at", "valid_from", "valid_to", "created_at",
  "due_at", "completed_at", "verified_at", "ingested_at", "superseded_at"
]);
const TEMPORAL_ANCHOR_ORDER = Object.freeze([
  "occurred_at", "completed_at", "recorded_at", "created_at", "due_at",
  "verified_at", "ingested_at", "valid_from", "superseded_at", "valid_to"
]);
const TEMPORAL_PRECISIONS = new Set(["year", "month", "day", "instant"]);
const TEMPORAL_EVENT_KINDS = new Set([
  "activity_recorded", "snapshot_recorded", "git_commit_recorded", "page_updated",
  "source_configured", "source_ingested", "source_refreshed", "source_refresh_due",
  "source_pipeline_advanced", "ingestion_recorded", "action_created", "action_due",
  "action_completed", "action_cancelled", "action_state_changed",
  "action_state_canonicalized", "action_contract_updated", "decision_recorded",
  "decision_made", "receipt_recorded"
]);
const TEMPORAL_NAMESPACED_KIND_PATTERN = /^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*){1,5}$/;
const TEMPORAL_LANES = new Set(["source", "action", "decision", "receipt", "page", "system", "other"]);
const TEMPORAL_CONFLICTS = Object.freeze([
  "valid_to_before_valid_from", "due_at_before_created_at",
  "completed_at_before_created_at", "superseded_at_before_valid_from"
]);
const TEMPORAL_EVENT_KEYS = Object.freeze([
  "schema_version", "event_id", "kind", "subject_refs", "context_refs",
  ...TEMPORAL_DATE_FIELDS, "precision", "actor", "source_refs", "evidence_refs",
  "caused_by", "supersedes", "before", "after", "confidence", "visibility",
  "origin", "temporal_conflicts", "anchor"
]);
const TEMPORAL_GRAPH_KEYS = Object.freeze([
  "schema_version", "event_schema_version", "repo_id", "revision", "generated_at",
  "event_count", "total_count", "returned_count", "truncated", "next_cursor", "page",
  "range", "returned_range", "summary", "diagnostics", "events"
]);
const TEMPORAL_REF_PATTERN = /^[a-z][a-z0-9_-]{0,31}:[A-Za-z0-9][A-Za-z0-9._/:-]{0,255}$/;
const TEMPORAL_EVENT_ID_PATTERN = /^[a-z][a-z0-9._-]{2,159}$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;

function temporalRecord(value) {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function temporalExactKeys(value, keys) {
  return temporalRecord(value) && Object.keys(value).sort().join(",") === [...keys].sort().join(",");
}

function temporalEventKeys(value) {
  return temporalExactKeys(value, TEMPORAL_EVENT_KEYS) || temporalExactKeys(value, [...TEMPORAL_EVENT_KEYS, "lane"]);
}

function temporalNonNegativeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function temporalStringArray(value) {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function temporalLeapYear(year) {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function temporalDaysInMonth(year, month) {
  return [31, temporalLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1] ?? 0;
}

function temporalUtcMillis(year, month, day) {
  const value = new Date(0);
  value.setUTCHours(0, 0, 0, 0);
  value.setUTCFullYear(year, month - 1, day);
  return value.getTime();
}

function temporalUtcMicros(year, month, day) {
  return BigInt(temporalUtcMillis(year, month, day)) * 1000n;
}

function parseTemporalPoint(value) {
  if (typeof value !== "string" || value !== value.trim()) return null;
  const yearMatch = /^(\d{4})$/.exec(value);
  if (yearMatch) {
    const year = Number(yearMatch[1]);
    if (year < 1) return null;
    return { precision: "year", lower: temporalUtcMicros(year, 1, 1), upper: temporalUtcMicros(year + 1, 1, 1) - 1n };
  }
  const monthMatch = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(value);
  if (monthMatch) {
    const year = Number(monthMatch[1]);
    const month = Number(monthMatch[2]);
    if (year < 1) return null;
    const nextYear = month === 12 ? year + 1 : year;
    const nextMonth = month === 12 ? 1 : month + 1;
    return {
      precision: "month",
      lower: temporalUtcMicros(year, month, 1),
      upper: temporalUtcMicros(nextYear, nextMonth, 1) - 1n
    };
  }
  const dayMatch = /^(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/.exec(value);
  if (dayMatch) {
    const year = Number(dayMatch[1]);
    const month = Number(dayMatch[2]);
    const day = Number(dayMatch[3]);
    if (year < 1 || day > temporalDaysInMonth(year, month)) return null;
    const lower = temporalUtcMicros(year, month, day);
    return { precision: "day", lower, upper: lower + 86_400_000_000n - 1n };
  }
  const instantMatch = /^(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])T([01]\d|2[0-3]):([0-5]\d):([0-5]\d)(?:\.(\d{1,6}))?(Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.exec(value);
  if (!instantMatch) return null;
  const year = Number(instantMatch[1]);
  const month = Number(instantMatch[2]);
  const day = Number(instantMatch[3]);
  if (year < 1 || day > temporalDaysInMonth(year, month)) return null;
  const fraction = instantMatch[7] || "";
  const zone = instantMatch[8];
  const base = `${instantMatch[1]}-${instantMatch[2]}-${instantMatch[3]}T${instantMatch[4]}:${instantMatch[5]}:${instantMatch[6]}${zone}`;
  const instantMillis = Date.parse(base);
  if (!Number.isFinite(instantMillis)) return null;
  const instant = BigInt(instantMillis) * 1000n + BigInt(fraction.padEnd(6, "0") || "0");
  return { precision: "instant", lower: instant, upper: instant };
}

function temporalRefArrayErrors(value, label, required = false) {
  if (!temporalStringArray(value)) return [`${label} must be a string array`];
  const errors = [];
  if ((required && value.length === 0) || value.length > 128) errors.push(`${label} has an invalid item count`);
  if (new Set(value).size !== value.length || value.some((item) => !TEMPORAL_REF_PATTERN.test(item))) {
    errors.push(`${label} contains an invalid or duplicate typed reference`);
  }
  return errors;
}

function temporalEventContractErrors(value, index, expectedVersion) {
  const label = `temporal graph events[${index}]`;
  if (!temporalRecord(value)) return [`${label} must be an object`];
  const errors = [];
  if (!temporalEventKeys(value)) errors.push(`${label} must expose only the temporal event v1 keys`);
  if (value.schema_version !== expectedVersion) errors.push(`${label}.schema_version is unsupported`);
  if (typeof value.event_id !== "string" || !TEMPORAL_EVENT_ID_PATTERN.test(value.event_id)) errors.push(`${label}.event_id is invalid`);
  if (
    typeof value.kind !== "string" ||
    value.kind.length > 80 ||
    (!TEMPORAL_EVENT_KINDS.has(value.kind) && !TEMPORAL_NAMESPACED_KIND_PATTERN.test(value.kind))
  ) errors.push(`${label}.kind is unsupported`);
  if (Object.prototype.hasOwnProperty.call(value, "lane") && (typeof value.lane !== "string" || !TEMPORAL_LANES.has(value.lane))) {
    errors.push(`${label}.lane is unsupported`);
  }
  for (const field of ["subject_refs", "context_refs"]) errors.push(...temporalRefArrayErrors(value[field], `${label}.${field}`, true));
  for (const field of ["source_refs", "evidence_refs", "caused_by", "supersedes"]) errors.push(...temporalRefArrayErrors(value[field], `${label}.${field}`));

  const precision = temporalRecord(value.precision) ? value.precision : null;
  if (!precision) errors.push(`${label}.precision must be an object`);
  else if (
    Object.keys(precision).some((field) => !TEMPORAL_DATE_FIELDS.includes(field)) ||
    Object.values(precision).some((item) => typeof item !== "string" || !TEMPORAL_PRECISIONS.has(item))
  ) errors.push(`${label}.precision contains an unsupported field or value`);
  const points = new Map();
  for (const field of TEMPORAL_DATE_FIELDS) {
    const raw = value[field];
    if (raw === null) {
      if (precision && Object.prototype.hasOwnProperty.call(precision, field)) errors.push(`${label}.${field} is null but declares precision`);
      continue;
    }
    const point = parseTemporalPoint(raw);
    if (!point) errors.push(`${label}.${field} is not an honest ISO temporal value`);
    else {
      points.set(field, point);
      if (!precision || precision[field] !== point.precision) errors.push(`${label}.${field} precision does not match its value`);
    }
  }
  for (const field of ["before", "after"]) {
    if (!temporalRecord(value[field]) || Object.keys(value[field]).length > 128) errors.push(`${label}.${field} must be an object with at most 128 fields`);
  }
  if (
    !temporalRecord(value.origin) ||
    Object.keys(value.origin).some((key) => key !== "adapter" && key !== "legacy_kind") ||
    typeof value.origin.adapter !== "string" ||
    value.origin.adapter.length < 1 ||
    value.origin.adapter.length > 120 ||
    (Object.prototype.hasOwnProperty.call(value.origin, "legacy_kind") && (
      typeof value.origin.legacy_kind !== "string" || value.origin.legacy_kind.length < 1 || value.origin.legacy_kind.length > 120
    ))
  ) errors.push(`${label}.origin is invalid`);
  if (value.actor !== null && (
    !temporalExactKeys(value.actor, ["kind", "ref"]) ||
    !["human", "agent", "system", "unknown"].includes(String(value.actor?.kind)) ||
    typeof value.actor?.ref !== "string" ||
    !TEMPORAL_REF_PATTERN.test(value.actor.ref)
  )) errors.push(`${label}.actor is invalid`);
  if (!["confirmed", "inferred", "uncertain", "conflicting"].includes(String(value.confidence))) errors.push(`${label}.confidence is invalid`);
  if (!['public', 'private'].includes(value.visibility)) errors.push(`${label}.visibility is invalid`);

  const declaredConflicts = temporalStringArray(value.temporal_conflicts) ? value.temporal_conflicts : null;
  if (
    !declaredConflicts ||
    new Set(declaredConflicts).size !== declaredConflicts.length ||
    declaredConflicts.some((conflict) => !TEMPORAL_CONFLICTS.includes(conflict))
  ) errors.push(`${label}.temporal_conflicts is invalid`);
  const expectedConflicts = [
    ["valid_to", "valid_from", "valid_to_before_valid_from"],
    ["due_at", "created_at", "due_at_before_created_at"],
    ["completed_at", "created_at", "completed_at_before_created_at"],
    ["superseded_at", "valid_from", "superseded_at_before_valid_from"]
  ].filter(([left, right]) => points.has(left) && points.has(right) && points.get(left).upper < points.get(right).lower)
    .map(([, , conflict]) => conflict);
  if (declaredConflicts && JSON.stringify(declaredConflicts) !== JSON.stringify(expectedConflicts)) {
    errors.push(`${label}.temporal_conflicts does not match the declared clocks`);
  }
  if (expectedConflicts.length > 0 && value.confidence !== "conflicting") errors.push(`${label}.confidence must expose temporal conflicts`);

  const expectedAnchorField = TEMPORAL_ANCHOR_ORDER.find((field) => points.has(field));
  if (!expectedAnchorField) {
    if (value.anchor !== null) errors.push(`${label}.anchor must be null when the event is undated`);
  } else if (
    !temporalExactKeys(value.anchor, ["field", "value", "precision"]) ||
    value.anchor.field !== expectedAnchorField ||
    value.anchor.value !== value[expectedAnchorField] ||
    value.anchor.precision !== precision?.[expectedAnchorField]
  ) errors.push(`${label}.anchor does not match the canonical event clock`);
  return errors;
}

function temporalExpectedRange(events, basis) {
  const anchored = events.flatMap((event) => {
    if (!temporalRecord(event) || !temporalRecord(event.anchor)) return [];
    const point = parseTemporalPoint(event.anchor.value);
    return point ? [{ anchor: event.anchor, point }] : [];
  });
  let from = null;
  let to = null;
  for (const item of anchored) {
    if (!from || item.point.lower < from.point.lower) from = item;
    if (!to || item.point.upper > to.point.upper) to = item;
  }
  return {
    from: from?.anchor.value ?? null,
    to: to?.anchor.value ?? null,
    from_precision: from?.anchor.precision ?? null,
    to_precision: to?.anchor.precision ?? null,
    event_count: events.length,
    dated_count: anchored.length,
    undated_count: events.length - anchored.length,
    basis
  };
}

function temporalRangeErrors(value, label, basis, events) {
  const keys = ["from", "to", "from_precision", "to_precision", "event_count", "dated_count", "undated_count", "basis"];
  if (!temporalExactKeys(value, keys)) return [`${label} must expose the exact temporal range v1 keys`];
  const errors = [];
  for (const field of ["event_count", "dated_count", "undated_count"]) {
    if (!temporalNonNegativeInteger(value[field])) errors.push(`${label}.${field} is invalid`);
  }
  for (const side of ["from", "to"]) {
    const precisionField = `${side}_precision`;
    if (value[side] === null) {
      if (value[precisionField] !== null) errors.push(`${label}.${precisionField} must be null with ${side}`);
    } else {
      const point = parseTemporalPoint(value[side]);
      if (!point || value[precisionField] !== point.precision) errors.push(`${label}.${side} and precision are invalid`);
    }
  }
  if (value.basis !== basis) errors.push(`${label}.basis must equal ${basis}`);
  if (
    temporalNonNegativeInteger(value.event_count) &&
    temporalNonNegativeInteger(value.dated_count) &&
    temporalNonNegativeInteger(value.undated_count) &&
    value.dated_count + value.undated_count !== value.event_count
  ) errors.push(`${label} dated and undated counts do not reconcile`);
  if (canonicalJson(value) !== canonicalJson(temporalExpectedRange(events, basis))) errors.push(`${label} does not match the returned event set`);
  return errors;
}

function temporalCountMap(value) {
  return temporalRecord(value) && Object.values(value).every(temporalNonNegativeInteger);
}

function temporalExpectedCounts(events) {
  const byKind = {};
  const byContext = {};
  let conflictCount = 0;
  let impreciseCount = 0;
  for (const event of events) {
    if (!temporalRecord(event)) continue;
    const kind = String(event.kind ?? "");
    byKind[kind] = (byKind[kind] ?? 0) + 1;
    if (temporalStringArray(event.context_refs)) {
      for (const context of event.context_refs) byContext[context] = (byContext[context] ?? 0) + 1;
    }
    if (Array.isArray(event.temporal_conflicts) && event.temporal_conflicts.length > 0) conflictCount += 1;
    if (temporalRecord(event.precision) && Object.values(event.precision).some((item) => item === "year" || item === "month")) impreciseCount += 1;
  }
  return { byKind, byContext, conflictCount, impreciseCount };
}

function temporalDiagnosticErrors(value, index) {
  const label = `temporal graph diagnostics[${index}]`;
  if (!temporalExactKeys(value, ["code", "adapter", "subject_ref", "error_codes"])) {
    return [`${label} must expose the exact temporal diagnostic v1 keys`];
  }
  const errors = [];
  if (!['temporal_adapter_rejected', 'temporal_event_id_collision'].includes(value.code)) errors.push(`${label}.code is unsupported`);
  if (typeof value.adapter !== "string" || value.adapter.length < 1 || value.adapter.length > 120) errors.push(`${label}.adapter is invalid`);
  if (typeof value.subject_ref !== "string" || !TEMPORAL_REF_PATTERN.test(value.subject_ref)) errors.push(`${label}.subject_ref is invalid`);
  if (
    !temporalStringArray(value.error_codes) ||
    value.error_codes.length < 1 ||
    new Set(value.error_codes).size !== value.error_codes.length ||
    value.error_codes.some((code) => code.length < 1 || code.length > 160)
  ) errors.push(`${label}.error_codes is invalid`);
  return errors;
}

function staticTemporalGraphErrors(temporalGraph, expected) {
  const errors = [];
  if (!temporalRecord(temporalGraph)) return ["temporal graph payload must be an object"];
  if (!temporalExactKeys(temporalGraph, TEMPORAL_GRAPH_KEYS)) errors.push("temporal graph must expose the exact v1 envelope keys");
  if (temporalGraph.schema_version !== expected.expectedTemporalGraphVersion) {
    errors.push("temporal graph payload schema_version does not match its exact manifest version");
  }
  if (temporalGraph.event_schema_version !== expected.expectedTemporalEventVersion) {
    errors.push("temporal graph event_schema_version does not match its exact manifest version");
  }
  if (typeof temporalGraph.repo_id !== "string" || temporalGraph.repo_id.length < 1 || temporalGraph.repo_id.length > 160) errors.push("temporal graph repo_id is invalid");
  if (typeof temporalGraph.revision !== "string" || !/^sha256:[0-9a-f]{64}$/.test(temporalGraph.revision)) errors.push("temporal graph revision is invalid");
  if (parseTemporalPoint(temporalGraph.generated_at)?.precision !== "instant") errors.push("temporal graph generated_at is invalid");
  for (const field of ["event_count", "total_count", "returned_count"]) {
    if (!temporalNonNegativeInteger(temporalGraph[field])) errors.push(`temporal graph ${field} is invalid`);
  }
  const events = Array.isArray(temporalGraph.events) ? temporalGraph.events : [];
  if (!Array.isArray(temporalGraph.events)) errors.push("temporal graph events must be an array");
  else {
    for (const [index, event] of events.entries()) errors.push(...temporalEventContractErrors(event, index, expected.expectedTemporalEventVersion));
    const ids = events.filter(temporalRecord).map((event) => event.event_id).filter((id) => typeof id === "string");
    if (new Set(ids).size !== ids.length) errors.push("temporal graph event ids must be unique");
  }
  const diagnostics = Array.isArray(temporalGraph.diagnostics) ? temporalGraph.diagnostics : [];
  if (!Array.isArray(temporalGraph.diagnostics)) errors.push("temporal graph diagnostics must be an array");
  else for (const [index, diagnostic] of diagnostics.entries()) errors.push(...temporalDiagnosticErrors(diagnostic, index));

  const page = temporalGraph.page;
  if (
    !temporalExactKeys(page, ["offset", "limit", "remaining_count", "fingerprint"]) ||
    !temporalNonNegativeInteger(page?.offset) ||
    !temporalNonNegativeInteger(page?.limit) ||
    !temporalNonNegativeInteger(page?.remaining_count) ||
    typeof page?.fingerprint !== "string" ||
    !SHA256_PATTERN.test(page.fingerprint)
  ) errors.push("temporal graph page contract is invalid");
  else {
    const actualFingerprint = sha256CanonicalJson(events);
    if (page.fingerprint !== actualFingerprint || temporalGraph.revision !== `sha256:${actualFingerprint}`) {
      errors.push("temporal graph page fingerprint/revision does not match canonical events");
    }
  }
  errors.push(...temporalRangeErrors(temporalGraph.range, "temporal graph range", "full_result", events));
  errors.push(...temporalRangeErrors(temporalGraph.returned_range, "temporal graph returned_range", "returned_page", events));

  const summary = temporalGraph.summary;
  if (!temporalExactKeys(summary, ["scope", "event_count", "by_kind", "by_context", "conflict_count", "imprecise_count", "diagnostic_count"])) {
    errors.push("temporal graph summary must expose the exact v1 keys");
  } else {
    const counts = temporalExpectedCounts(events);
    if (summary.scope !== "full_result" || summary.event_count !== temporalGraph.total_count) errors.push("temporal graph summary does not cover the full result");
    if (!temporalCountMap(summary.by_kind) || canonicalJson(summary.by_kind) !== canonicalJson(counts.byKind)) errors.push("temporal graph summary.by_kind does not match events");
    if (!temporalCountMap(summary.by_context) || canonicalJson(summary.by_context) !== canonicalJson(counts.byContext)) errors.push("temporal graph summary.by_context does not match events");
    if (summary.conflict_count !== counts.conflictCount) errors.push("temporal graph summary.conflict_count does not match events");
    if (summary.imprecise_count !== counts.impreciseCount) errors.push("temporal graph summary.imprecise_count does not match events");
    if (summary.diagnostic_count !== diagnostics.length) errors.push("temporal graph summary.diagnostic_count does not match diagnostics");
  }
  if (
    events.length === 0 ||
    temporalGraph.returned_count !== events.length ||
    temporalGraph.event_count !== events.length ||
    temporalGraph.total_count !== events.length ||
    temporalGraph.truncated !== false ||
    temporalGraph.next_cursor !== null ||
    page?.offset !== 0 ||
    page?.limit !== events.length ||
    page?.remaining_count !== 0
  ) {
    errors.push(
      "static temporal graph must contain one complete, non-truncated, count-consistent exact-version event set"
    );
  }
  return errors;
}

function experiencePackCompositionErrors(composition) {
  const errors = [];
  if (
    !composition ||
    Array.isArray(composition) ||
    typeof composition !== "object" ||
    Object.keys(composition).sort().join(",") !== [
      "block_packages",
      "composition_sha256",
      "core_version",
      "packs",
      "presentation",
      "schema_version",
      "slots"
    ].sort().join(",")
  ) errors.push("experience pack composition must expose the exact v1 fields");
  const packIdPattern = /^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/;
  const semverPattern = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/;
  const capabilityPattern = /^[a-z][a-z0-9_.-]*$/;
  const packs = Array.isArray(composition.packs) ? composition.packs : null;
  const normalizedPacks = [];
  if (!packs) {
    errors.push("experience pack composition packs must be an array");
  } else {
    for (const pack of packs) {
      if (
        !pack ||
        Array.isArray(pack) ||
        typeof pack !== "object" ||
        Object.keys(pack).sort().join(",") !== "id,version" ||
        !packIdPattern.test(String(pack.id || "")) ||
        !semverPattern.test(String(pack.version || ""))
      ) {
        errors.push("experience pack composition contains an invalid pack record");
        continue;
      }
      normalizedPacks.push({ id: pack.id, version: pack.version });
    }
    const canonicalPacks = [...normalizedPacks].sort((left, right) => left.id < right.id ? -1 : left.id > right.id ? 1 : 0);
    if (
      normalizedPacks.length !== packs.length ||
      new Set(normalizedPacks.map((pack) => pack.id)).size !== normalizedPacks.length ||
      JSON.stringify(normalizedPacks) !== JSON.stringify(canonicalPacks)
    ) {
      errors.push("experience pack composition packs must be unique and canonical by id");
    }
  }
  if (
    !Array.isArray(composition.block_packages) ||
    composition.block_packages.some((value) => typeof value !== "string" || !capabilityPattern.test(value)) ||
    JSON.stringify(composition.block_packages) !== JSON.stringify([...new Set(composition.block_packages ?? [])].sort())
  ) {
    errors.push("experience pack composition block_packages must be unique and canonical");
  }
  const slotKinds = ["views", "commands", "operations", "timelines"];
  if (
    !composition.slots ||
    Array.isArray(composition.slots) ||
    typeof composition.slots !== "object" ||
    Object.keys(composition.slots).sort().join(",") !== [...slotKinds].sort().join(",")
  ) {
    errors.push("experience pack composition must expose the exact v1 slot kinds");
    return errors;
  }
  const knownPacks = new Set(normalizedPacks.map((pack) => pack.id));
  const seenContributions = new Set();
  for (const kind of slotKinds) {
    const rows = composition.slots[kind];
    if (!Array.isArray(rows)) {
      errors.push(`experience pack ${kind} slots must be an array`);
      continue;
    }
    const identities = [];
    const seenIdentities = new Set();
    const bySlot = new Map();
    for (const row of rows) {
      if (
        !row ||
        Array.isArray(row) ||
        typeof row !== "object" ||
        Object.keys(row).sort().join(",") !== "contribution,mode,pack,slot" ||
        !knownPacks.has(row.pack) ||
        typeof row.slot !== "string" ||
        !row.slot.startsWith(`${kind.slice(0, -1)}.`) ||
        !capabilityPattern.test(row.slot) ||
        typeof row.contribution !== "string" ||
        !row.contribution.startsWith(`${row.pack}.`) ||
        !capabilityPattern.test(row.contribution) ||
        !["append", "exclusive"].includes(row.mode)
      ) {
        errors.push(`experience pack ${kind} contains an invalid or unnamespaced slot record`);
        continue;
      }
      const identity = [row.pack, row.slot, row.contribution, row.mode];
      const identityKey = JSON.stringify(identity);
      const contributionKey = `${kind}:${row.contribution}`;
      if (seenIdentities.has(identityKey) || seenContributions.has(contributionKey)) {
        errors.push(`experience pack ${kind} slot/contribution identities must be unique`);
      }
      seenIdentities.add(identityKey);
      seenContributions.add(contributionKey);
      identities.push(identity);
      const slotRows = bySlot.get(row.slot) ?? [];
      slotRows.push(row);
      bySlot.set(row.slot, slotRows);
    }
    const canonical = [...identities].sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
    if (JSON.stringify(identities) !== JSON.stringify(canonical)) {
      errors.push(`experience pack ${kind} slots must be canonical`);
    }
    for (const [slot, slotRows] of bySlot) {
      if (slotRows.length > 1 && slotRows.some((row) => row.mode === "exclusive")) {
        errors.push(`experience pack ${kind} exclusive slot ${slot} conflicts with another contribution`);
      }
    }
  }
  const presentation = composition.presentation;
  const localePattern = /^[a-z]{2}(?:-[A-Z]{2})?$/;
  const localeLabels = new Map();
  if (
    !presentation ||
    Array.isArray(presentation) ||
    typeof presentation !== "object" ||
    Object.keys(presentation).sort().join(",") !== "default_locale,locales" ||
    presentation.default_locale !== "en" ||
    !presentation.locales ||
    Array.isArray(presentation.locales) ||
    typeof presentation.locales !== "object"
  ) {
    errors.push("experience pack presentation contract is invalid");
  } else {
    const localeIds = Object.keys(presentation.locales);
    if (
      !localeIds.includes("en") ||
      !localeIds.includes("pt-BR") ||
      JSON.stringify(localeIds) !== JSON.stringify([...localeIds].sort())
    ) errors.push("experience pack presentation locales must include canonical en and pt-BR");
    for (const [locale, labels] of Object.entries(presentation.locales)) {
      if (!localePattern.test(locale) || !labels || Array.isArray(labels) || typeof labels !== "object") {
        errors.push(`experience pack presentation locale ${locale} is invalid`);
        continue;
      }
      const identifiers = Object.keys(labels);
      if (JSON.stringify(identifiers) !== JSON.stringify([...identifiers].sort())) {
        errors.push(`experience pack presentation labels for ${locale} must be canonical`);
      }
      for (const [identifier, label] of Object.entries(labels)) {
        const owners = normalizedPacks.filter((pack) => (
          identifier === pack.id ||
          identifier.startsWith(`${pack.id}.`) ||
          identifier.startsWith(`${pack.id.replaceAll("-", "_")}_`)
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
    const referenceKeys = Object.keys(localeLabels.get("en") ?? {});
    for (const [locale, labels] of localeLabels) {
      if (JSON.stringify(Object.keys(labels)) !== JSON.stringify(referenceKeys)) {
        errors.push(`experience pack presentation locale ${locale} lacks exact key parity`);
      }
    }
    const requiredLabels = new Set(normalizedPacks.map((pack) => pack.id));
    for (const kind of slotKinds) {
      for (const row of composition.slots[kind] ?? []) {
        if (row && typeof row.contribution === "string") requiredLabels.add(row.contribution);
      }
    }
    for (const [locale, labels] of localeLabels) {
      if ([...requiredLabels].some((identifier) => !(identifier in labels))) {
        errors.push(`experience pack presentation labels for ${locale} are incomplete`);
      }
    }
  }
  return errors;
}

function parseLoopbackUrl(raw, name, { base = false } = {}) {
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`${name} must be an absolute http(s) URL`);
  }
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error(`${name} must use http or https`);
  }
  if (url.username || url.password) {
    throw new Error(`${name} must not contain URL credentials`);
  }
  const loopback = url.hostname === "localhost" || url.hostname === "127.0.0.1" || url.hostname === "[::1]";
  if (!loopback) throw new Error(`${name} must target the exact loopback operator/UI`);
  if (url.search || url.hash) throw new Error(`${name} must not contain a query or fragment`);
  if (base && !["", "/"].includes(url.pathname)) {
    throw new Error(`${name} must be an origin/base URL without a path`);
  }
  return url;
}

export function deriveSnapshotManifestUrl(snapshotUrl) {
  const url = new URL(snapshotUrl);
  if (!url.pathname.endsWith("/pages.json")) {
    throw new Error("WIKI_COCKPIT_SNAPSHOT_URL must end with /pages.json");
  }
  return new URL("./manifest.json", url).toString();
}

export function validateDownstreamEnvironment(env = process.env) {
  const errors = [];
  const values = {};
  for (const key of DOWNSTREAM_ENV_KEYS) {
    const value = String(env[key] ?? "").trim();
    if (!value) errors.push(`${key} is required`);
    values[key] = value;
  }
  if (errors.length) return { ok: false, errors, values: null };

  try {
    values.snapshotUrl = parseLoopbackUrl(values.WIKI_COCKPIT_SNAPSHOT_URL, "WIKI_COCKPIT_SNAPSHOT_URL").toString();
    values.manifestUrl = deriveSnapshotManifestUrl(values.snapshotUrl);
  } catch (error) {
    errors.push(error.message);
  }
  try {
    const baseUrl = parseLoopbackUrl(values.WIKI_COCKPIT_REAL_BASE_URL, "WIKI_COCKPIT_REAL_BASE_URL", { base: true });
    values.baseUrl = baseUrl.toString().replace(/\/$/, "");
    values.healthUrl = new URL("/api/health", baseUrl).toString();
  } catch (error) {
    errors.push(error.message);
  }
  if (
    values.snapshotUrl &&
    values.baseUrl &&
    new URL(values.snapshotUrl).origin !== new URL(values.baseUrl).origin
  ) {
    errors.push(
      "WIKI_COCKPIT_SNAPSHOT_URL and WIKI_COCKPIT_REAL_BASE_URL must share one exact same-origin UI boundary"
    );
  }

  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(values.WIKI_COCKPIT_EXPECT_REPO_ID)) {
    errors.push("WIKI_COCKPIT_EXPECT_REPO_ID must be a non-secret repository id");
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{7,199}$/.test(values.WIKI_COCKPIT_EXPECT_SNAPSHOT_REVISION)) {
    errors.push("WIKI_COCKPIT_EXPECT_SNAPSHOT_REVISION must be an exact non-empty revision id");
  }
  if (!/^[0-9a-fA-F]{64}$/.test(values.WIKI_COCKPIT_EXPECT_SNAPSHOT_HASH)) {
    errors.push("WIKI_COCKPIT_EXPECT_SNAPSHOT_HASH must be a 64-character SHA-256");
  }
  if (
    /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(values.WIKI_COCKPIT_EXPECT_REPO_ID) &&
    /^[0-9a-fA-F]{64}$/.test(values.WIKI_COCKPIT_EXPECT_SNAPSHOT_HASH) &&
    values.WIKI_COCKPIT_EXPECT_SNAPSHOT_REVISION !==
      `${values.WIKI_COCKPIT_EXPECT_REPO_ID}-${values.WIKI_COCKPIT_EXPECT_SNAPSHOT_HASH.slice(0, 16).toLowerCase()}`
  ) {
    errors.push("WIKI_COCKPIT_EXPECT_SNAPSHOT_REVISION must be canonical for the expected repo/hash");
  }
  if (!/^[0-9a-fA-F]{40}$/.test(values.WIKI_COCKPIT_EXPECT_CONSUMER_HEAD)) {
    errors.push("WIKI_COCKPIT_EXPECT_CONSUMER_HEAD must be the exact clean 40-character consumer HEAD");
  }
  if (!/^[0-9a-fA-F]{40}$/.test(values.WIKI_COCKPIT_EXPECT_PUBLIC_RELEASE_SHA)) {
    errors.push("WIKI_COCKPIT_EXPECT_PUBLIC_RELEASE_SHA must be the exact 40-character adopted public release SHA");
  }
  if (!/^[0-9a-fA-F]{64}$/.test(values.WIKI_COCKPIT_EXPECT_ADAPTER_HASH)) {
    errors.push("WIKI_COCKPIT_EXPECT_ADAPTER_HASH must be the exact 64-character downstream adapter SHA-256");
  }
  for (const key of [
    "WIKI_COCKPIT_EXPECT_SNAPSHOT_VERSION",
    "WIKI_COCKPIT_EXPECT_RUNTIME_VERSION",
    "WIKI_COCKPIT_EXPECT_SERVER_VERSION",
    "WIKI_COCKPIT_EXPECT_TEMPORAL_GRAPH_VERSION",
    "WIKI_COCKPIT_EXPECT_TEMPORAL_EVENT_VERSION",
    "WIKI_COCKPIT_EXPECT_EXPERIENCE_PACK_COMPOSITION_VERSION"
  ]) {
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(values[key])) {
      errors.push(`${key} must be an exact non-secret version identifier`);
    }
  }
  const requiredVersions = {
    WIKI_COCKPIT_EXPECT_SNAPSHOT_VERSION: REQUIRED_DOWNSTREAM_VERSIONS.snapshot,
    WIKI_COCKPIT_EXPECT_RUNTIME_VERSION: REQUIRED_DOWNSTREAM_VERSIONS.runtime,
    WIKI_COCKPIT_EXPECT_SERVER_VERSION: REQUIRED_DOWNSTREAM_VERSIONS.server,
    WIKI_COCKPIT_EXPECT_TEMPORAL_GRAPH_VERSION: REQUIRED_DOWNSTREAM_VERSIONS.temporalGraph,
    WIKI_COCKPIT_EXPECT_TEMPORAL_EVENT_VERSION: REQUIRED_DOWNSTREAM_VERSIONS.temporalEvent,
    WIKI_COCKPIT_EXPECT_EXPERIENCE_PACK_COMPOSITION_VERSION:
      REQUIRED_DOWNSTREAM_VERSIONS.experiencePackComposition
  };
  for (const [key, required] of Object.entries(requiredVersions)) {
    if (values[key] !== required) errors.push(`${key} must equal the release-required ${required}`);
  }

  const capabilities = values.WIKI_COCKPIT_EXPECT_CAPABILITIES
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  if (!capabilities.length || new Set(capabilities).size !== capabilities.length) {
    errors.push("WIKI_COCKPIT_EXPECT_CAPABILITIES must be a non-empty, duplicate-free comma list");
  }
  for (const capability of REQUIRED_OPERATOR_CAPABILITIES) {
    if (!capabilities.includes(capability)) {
      errors.push(`WIKI_COCKPIT_EXPECT_CAPABILITIES must include ${capability}`);
    }
  }

  if (!/^[0-9a-fA-F]{64}$/.test(values.WIKI_COCKPIT_EXPECT_COMPOSITION_SHA256)) {
    errors.push("WIKI_COCKPIT_EXPECT_COMPOSITION_SHA256 must be the exact 64-character semantic composition SHA-256");
  }
  const expectedActivePacks = parseExpectedActivePacks(values.WIKI_COCKPIT_EXPECT_ACTIVE_PACKS, errors);

  if (!/^[1-9][0-9]*$/.test(values.WIKI_COCKPIT_MIN_PAGES)) {
    errors.push("WIKI_COCKPIT_MIN_PAGES must be a positive integer supplied explicitly");
  }
  if (errors.length) return { ok: false, errors, values: null };

  return {
    ok: true,
    errors: [],
    values: {
      snapshotUrl: values.snapshotUrl,
      manifestUrl: values.manifestUrl,
      baseUrl: values.baseUrl,
      healthUrl: values.healthUrl,
      runtimeConfigUrl: new URL("/wiki-cockpit.config.json", values.baseUrl).toString(),
      expectedRepo: values.WIKI_COCKPIT_EXPECT_REPO_ID,
      expectedRevision: values.WIKI_COCKPIT_EXPECT_SNAPSHOT_REVISION,
      expectedHash: values.WIKI_COCKPIT_EXPECT_SNAPSHOT_HASH.toLowerCase(),
      expectedConsumerHead: values.WIKI_COCKPIT_EXPECT_CONSUMER_HEAD.toLowerCase(),
      expectedPublicReleaseSha: values.WIKI_COCKPIT_EXPECT_PUBLIC_RELEASE_SHA.toLowerCase(),
      expectedAdapterHash: values.WIKI_COCKPIT_EXPECT_ADAPTER_HASH.toLowerCase(),
      expectedSnapshotVersion: values.WIKI_COCKPIT_EXPECT_SNAPSHOT_VERSION,
      expectedRuntimeVersion: values.WIKI_COCKPIT_EXPECT_RUNTIME_VERSION,
      expectedServerVersion: values.WIKI_COCKPIT_EXPECT_SERVER_VERSION,
      expectedTemporalGraphVersion: values.WIKI_COCKPIT_EXPECT_TEMPORAL_GRAPH_VERSION,
      expectedTemporalEventVersion: values.WIKI_COCKPIT_EXPECT_TEMPORAL_EVENT_VERSION,
      expectedExperiencePackCompositionVersion:
        values.WIKI_COCKPIT_EXPECT_EXPERIENCE_PACK_COMPOSITION_VERSION,
      expectedCompositionSha256: values.WIKI_COCKPIT_EXPECT_COMPOSITION_SHA256.toLowerCase(),
      expectedActivePacks,
      expectedCapabilities: capabilities,
      minPages: Number(values.WIKI_COCKPIT_MIN_PAGES)
    }
  };
}

async function responseTextWithinLimit(response, label, maxBytes) {
  const declaredRaw = response.headers?.get?.("content-length") ?? "";
  if (declaredRaw) {
    const declared = Number(declaredRaw);
    if (!Number.isSafeInteger(declared) || declared < 0 || declared > maxBytes) {
      throw new Error(`${label} exceeds the ${maxBytes}-byte response limit`);
    }
  }
  if (response.body?.getReader) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let total = 0;
    let text = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        total += value.byteLength;
        if (total > maxBytes) {
          await reader.cancel("response limit exceeded");
          throw new Error(`${label} exceeds the ${maxBytes}-byte response limit`);
        }
        text += decoder.decode(value, { stream: true });
      }
      return text + decoder.decode();
    } finally {
      reader.releaseLock();
    }
  }
  if (typeof response.text === "function") {
    const text = await response.text();
    if (Buffer.byteLength(text, "utf8") > maxBytes) {
      throw new Error(`${label} exceeds the ${maxBytes}-byte response limit`);
    }
    return text;
  }
  if (typeof response.json === "function") {
    const text = JSON.stringify(await response.json());
    if (Buffer.byteLength(text, "utf8") > maxBytes) {
      throw new Error(`${label} exceeds the ${maxBytes}-byte response limit`);
    }
    return text;
  }
  throw new Error(`${label} response body cannot be read`);
}

async function fetchJson(
  fetchImpl,
  url,
  label,
  { timeoutMs = PREFLIGHT_TIMEOUT_MS, maxBytes = PREFLIGHT_MAX_RESPONSE_BYTES } = {}
) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetchImpl(url, {
      headers: { accept: "application/json" },
      signal: controller.signal
    });
  } catch (error) {
    clearTimeout(timeout);
    const detail = controller.signal.aborted
      ? `timed out after ${timeoutMs}ms`
      : error instanceof Error ? error.message : String(error);
    throw new Error(`${label} is unreachable: ${detail}`);
  }
  try {
    const contentType = response.headers?.get?.("content-type") ?? "";
    if (!String(contentType).toLowerCase().includes("application/json")) {
      throw new Error(`${label} returned ${contentType || "unknown content type"}, not JSON`);
    }
    if (!response.ok) throw new Error(`${label} returned HTTP ${response.status}`);
    return JSON.parse(await responseTextWithinLimit(response, label, maxBytes));
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error(`${label} is unreachable: timed out after ${timeoutMs}ms`);
    }
    if (
      error instanceof Error &&
      (error.message.includes("response limit") ||
        error.message.startsWith(`${label} returned`))
    ) {
      throw error;
    }
    throw new Error(`${label} returned invalid JSON: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    clearTimeout(timeout);
  }
}

export async function runDownstreamPreflight(
  env = process.env,
  fetchImpl = globalThis.fetch,
  fetchOptions = {},
  repositoryRoot
) {
  const validated = validateDownstreamEnvironment(env);
  if (!validated.ok) throw new Error(validated.errors.join("; "));
  const expected = validated.values;
  const temporalGraphUrl = new URL("./temporal_graph.json", expected.snapshotUrl).toString();
  const experiencePacksUrl = new URL("./experience_packs.json", expected.snapshotUrl).toString();
  const [pages, manifest, temporalGraph, experiencePacks, health, runtimeConfig] = await Promise.all([
    fetchJson(fetchImpl, expected.snapshotUrl, "snapshot pages endpoint", fetchOptions),
    fetchJson(fetchImpl, expected.manifestUrl, "snapshot manifest endpoint", fetchOptions),
    fetchJson(fetchImpl, temporalGraphUrl, "snapshot temporal graph endpoint", fetchOptions),
    fetchJson(fetchImpl, experiencePacksUrl, "snapshot experience packs endpoint", fetchOptions),
    fetchJson(fetchImpl, expected.healthUrl, "operator health endpoint", fetchOptions),
    fetchJson(fetchImpl, expected.runtimeConfigUrl, "cockpit runtime config", fetchOptions)
  ]);

  const pageCount = Array.isArray(pages.pages) ? pages.pages.length : 0;
  const pagesRepo = String(pages.repo_id || pages.repo?.repo_id || "");
  const manifestRepo = String(manifest.repo?.repo_id || "");
  const healthRepo = String(health.repo || "");
  const revision = String(manifest.snapshot_id || "");
  const bundleHash = String(manifest.bundle_hash || "").toLowerCase();
  const sourceCommit = String(manifest.source_commit || "").toLowerCase();
  const sourceSha = String(manifest.source_sha || "").toLowerCase();
  const snapshotVersion = String(manifest.versions?.snapshot || "");
  const runtimeVersion = String(manifest.versions?.runtime_contract || "");
  const temporalGraphVersion = String(manifest.versions?.temporal_graph || "");
  const temporalEventVersion = String(manifest.versions?.temporal_event || "");
  const experiencePackCompositionVersion = String(
    manifest.versions?.experience_pack_composition || ""
  );
  const serverVersion = String(health.server_version || "");
  const contractErrors = manifest.contract_errors;
  const adoptedPublicReleaseSha = String(
    runtimeConfig.adoption?.public_release_sha || ""
  ).toLowerCase();
  const adapterHash = String(runtimeConfig.adoption?.adapter_hash || "").toLowerCase();
  const adapterManifestPath = String(runtimeConfig.adoption?.adapter_manifest || "");
  const capabilities = Array.isArray(health.schema_capabilities)
    ? health.schema_capabilities.map(String)
    : [];
  const snapshotCapabilities = Array.isArray(manifest.capabilities)
    ? manifest.capabilities.map(String)
    : [];
  const activePacks = Array.isArray(experiencePacks.packs)
    ? experiencePacks.packs.map((pack) => ({
      id: String(pack?.id || ""),
      version: String(pack?.version || "")
    }))
    : null;
  const temporalEvents = Array.isArray(temporalGraph.events) ? temporalGraph.events : null;
  const failures = [];
  let adapterManifestEvidence = null;
  const resolvedRepositoryRoot = repositoryRoot || gitCheck(
    process.cwd(),
    ["rev-parse", "--show-toplevel"],
    "consumer repository"
  ).trim();

  try {
    adapterManifestEvidence = verifyDownstreamAdapterManifest(
      resolvedRepositoryRoot,
      adapterManifestPath,
      expected.expectedAdapterHash
    );
  } catch (error) {
    failures.push(`adapter_manifest_invalid: ${error instanceof Error ? error.message : String(error)}`);
  }

  for (const [surface, repo] of [["pages", pagesRepo], ["manifest", manifestRepo], ["health", healthRepo]]) {
    if (repo !== expected.expectedRepo) failures.push(`${surface} repo_id ${repo || "(missing)"} != ${expected.expectedRepo}`);
  }
  if (revision !== expected.expectedRevision) {
    failures.push(`snapshot revision ${revision || "(missing)"} != ${expected.expectedRevision}`);
  }
  if (bundleHash !== expected.expectedHash) {
    failures.push(`snapshot hash ${bundleHash || "(missing)"} != ${expected.expectedHash}`);
  }
  const canonicalRevision = manifestRepo && /^[0-9a-f]{64}$/.test(bundleHash)
    ? `${manifestRepo}-${bundleHash.slice(0, 16)}`
    : "";
  if (revision !== canonicalRevision) {
    failures.push(`snapshot revision ${revision || "(missing)"} is not canonical for its repo/hash`);
  }
  if (sourceCommit !== expected.expectedConsumerHead) {
    failures.push(`snapshot source_commit ${sourceCommit || "(missing/dirty)"} != consumer HEAD ${expected.expectedConsumerHead}`);
  }
  if (sourceSha !== expected.expectedConsumerHead) {
    failures.push(`snapshot source_sha ${sourceSha || "(missing/dirty)"} != consumer HEAD ${expected.expectedConsumerHead}`);
  }
  if (snapshotVersion !== expected.expectedSnapshotVersion) {
    failures.push(`snapshot schema version ${snapshotVersion || "(missing)"} != ${expected.expectedSnapshotVersion}`);
  }
  if (runtimeVersion !== expected.expectedRuntimeVersion) {
    failures.push(`snapshot runtime version ${runtimeVersion || "(missing)"} != ${expected.expectedRuntimeVersion}`);
  }
  if (temporalGraphVersion !== expected.expectedTemporalGraphVersion) {
    failures.push(`temporal graph manifest version ${temporalGraphVersion || "(missing)"} != ${expected.expectedTemporalGraphVersion}`);
  }
  if (temporalEventVersion !== expected.expectedTemporalEventVersion) {
    failures.push(`temporal event manifest version ${temporalEventVersion || "(missing)"} != ${expected.expectedTemporalEventVersion}`);
  }
  if (experiencePackCompositionVersion !== expected.expectedExperiencePackCompositionVersion) {
    failures.push(
      `experience pack composition manifest version ${experiencePackCompositionVersion || "(missing)"} != ${expected.expectedExperiencePackCompositionVersion}`
    );
  }
  for (const capability of REQUIRED_SNAPSHOT_CAPABILITIES) {
    if (!snapshotCapabilities.includes(capability)) {
      failures.push(`snapshot capability ${capability} is missing`);
    }
  }
  failures.push(...staticTemporalGraphErrors(temporalGraph, expected));
  if (experiencePacks.schema_version !== expected.expectedExperiencePackCompositionVersion) {
    failures.push("experience pack payload schema_version does not match its exact manifest version");
  }
  if (experiencePacks.core_version !== REQUIRED_DOWNSTREAM_VERSIONS.experiencePackCore) {
    failures.push(`experience pack core_version must equal ${REQUIRED_DOWNSTREAM_VERSIONS.experiencePackCore}`);
  }
  const packErrors = experiencePackCompositionErrors(experiencePacks);
  failures.push(...packErrors);
  if (!packErrors.length) {
    for (const pack of expected.expectedActivePacks) {
      if (!experiencePacks.slots.views.some((row) => row.pack === pack.id && row.contribution)) {
        failures.push(`active experience pack ${pack.id} has no composed view for the downstream workbench`);
      }
    }
  }
  const compositionSha256 = String(experiencePacks.composition_sha256 || "").toLowerCase();
  const semanticCompositionSha256 = sha256CanonicalJson({
    packs: experiencePacks.packs,
    block_packages: experiencePacks.block_packages,
    slots: experiencePacks.slots,
    presentation: experiencePacks.presentation
  });
  if (
    compositionSha256 !== expected.expectedCompositionSha256 ||
    compositionSha256 !== semanticCompositionSha256
  ) {
    failures.push("experience pack composition_sha256 does not match both the explicit expectation and semantic payload");
  }
  if (!activePacks || JSON.stringify(activePacks) !== JSON.stringify(expected.expectedActivePacks)) {
    failures.push("experience pack active packs do not exactly match WIKI_COCKPIT_EXPECT_ACTIVE_PACKS");
  }
  for (const [file, payload] of [
    ["pages.json", pages],
    ["temporal_graph.json", temporalGraph],
    ["experience_packs.json", experiencePacks]
  ]) {
    const integrity = manifest.integrity?.[file];
    const canonical = canonicalJson(payload);
    const actualHash = crypto.createHash("sha256").update(canonical, "utf8").digest("hex");
    const actualBytes = Buffer.byteLength(canonical, "utf8");
    if (
      !integrity ||
      String(integrity.sha256 || "").toLowerCase() !== actualHash ||
      integrity.bytes !== actualBytes
    ) {
      failures.push(`${file} does not match its manifest integrity hash and canonical byte count`);
    }
  }
  if (health.ok !== true) failures.push("operator health did not report ok=true");
  if (serverVersion !== expected.expectedServerVersion) {
    failures.push(`operator server version ${serverVersion || "(missing)"} != ${expected.expectedServerVersion}`);
  }
  if (!Array.isArray(contractErrors) || contractErrors.length !== 0) {
    failures.push("snapshot contract_errors must be an explicit empty array");
  }
  if (!adoptedPublicReleaseSha || !adapterHash || !adapterManifestPath) {
    failures.push(
      "adoption_identity_unavailable: cockpit runtime config must serve adoption.public_release_sha, adoption.adapter_hash and adoption.adapter_manifest"
    );
  } else {
    if (adoptedPublicReleaseSha !== expected.expectedPublicReleaseSha) {
      failures.push(`adopted public release SHA ${adoptedPublicReleaseSha} != ${expected.expectedPublicReleaseSha}`);
    }
    if (adapterHash !== expected.expectedAdapterHash) {
      failures.push(`downstream adapter hash ${adapterHash} != ${expected.expectedAdapterHash}`);
    }
    if (adapterManifestPath !== DOWNSTREAM_ADAPTER_MANIFEST_PATH) {
      failures.push(`downstream adapter manifest ${adapterManifestPath} != ${DOWNSTREAM_ADAPTER_MANIFEST_PATH}`);
    }
    if (adapterManifestEvidence?.adapter_sha256 !== adapterHash) {
      failures.push("downstream adapter hash is not compiled from the tracked adapter manifest");
    }
  }
  if (pageCount < expected.minPages) failures.push(`page count ${pageCount} < ${expected.minPages}`);
  for (const capability of expected.expectedCapabilities) {
    if (!capabilities.includes(capability)) failures.push(`operator capability ${capability} is missing`);
  }
  if (failures.length) throw new Error(failures.join("; "));

  return {
    schema_version: "wiki_downstream_preflight.v2",
    scope: "downstream_required",
    status: "passed",
    repository: expected.expectedRepo,
    snapshot_revision: revision,
    snapshot_hash: bundleHash,
    consumer_head: expected.expectedConsumerHead,
    public_release_sha: adoptedPublicReleaseSha,
    adapter_hash: adapterHash,
    adapter_manifest: adapterManifestEvidence.manifest,
    adapter_manifest_schema_version: adapterManifestEvidence.schema_version,
    adapter_file_count: adapterManifestEvidence.file_count,
    snapshot_source_commit: sourceCommit,
    snapshot_source_sha: sourceSha,
    snapshot_version: snapshotVersion,
    runtime_version: runtimeVersion,
    operator_server_version: serverVersion,
    temporal_graph_version: temporalGraphVersion,
    temporal_event_version: temporalEventVersion,
    temporal_event_count: temporalEvents?.length ?? 0,
    experience_pack_composition_version: experiencePackCompositionVersion,
    composition_sha256: compositionSha256,
    active_packs: activePacks,
    contract_errors: [],
    page_count: pageCount,
    minimum_pages: expected.minPages,
    capabilities: expected.expectedCapabilities,
    snapshot_capabilities: snapshotCapabilities,
    endpoint_origins: {
      snapshot: new URL(expected.snapshotUrl).origin,
      ui: new URL(expected.baseUrl).origin
    }
  };
}

export function evaluateDownstreamPreflightRecord(record, env = process.env, repositoryRoot) {
  const validated = validateDownstreamEnvironment(env);
  const errors = [...validated.errors];
  if (!validated.ok) return { ok: false, errors };
  const expected = validated.values;
  if (
    record?.schema_version !== "wiki_downstream_preflight.v2" ||
    record?.scope !== "downstream_required" ||
    record?.status !== "passed"
  ) {
    errors.push("downstream preflight evidence is not a passed wiki_downstream_preflight.v2 record");
    return { ok: false, errors };
  }
  if (record.repository !== expected.expectedRepo) errors.push("downstream preflight repo does not match");
  if (record.snapshot_revision !== expected.expectedRevision) errors.push("downstream preflight revision does not match");
  if (String(record.snapshot_hash || "").toLowerCase() !== expected.expectedHash) {
    errors.push("downstream preflight hash does not match");
  }
  if (String(record.consumer_head || "").toLowerCase() !== expected.expectedConsumerHead) {
    errors.push("downstream preflight consumer HEAD does not match");
  }
  if (String(record.public_release_sha || "").toLowerCase() !== expected.expectedPublicReleaseSha) {
    errors.push("downstream preflight adopted public release SHA does not match");
  }
  if (String(record.adapter_hash || "").toLowerCase() !== expected.expectedAdapterHash) {
    errors.push("downstream preflight adapter hash does not match");
  }
  if (record.adapter_manifest !== DOWNSTREAM_ADAPTER_MANIFEST_PATH) {
    errors.push("downstream preflight adapter manifest path does not match");
  }
  if (record.adapter_manifest_schema_version !== DOWNSTREAM_ADAPTER_MANIFEST_SCHEMA) {
    errors.push("downstream preflight adapter manifest schema does not match");
  }
  if (!Number.isInteger(record.adapter_file_count) || record.adapter_file_count < 1) {
    errors.push("downstream preflight adapter file count is invalid");
  }
  if (repositoryRoot) {
    try {
      const currentAdapter = verifyDownstreamAdapterManifest(
        repositoryRoot,
        record.adapter_manifest,
        expected.expectedAdapterHash
      );
      if (
        currentAdapter.adapter_sha256 !== String(record.adapter_hash || "").toLowerCase() ||
        currentAdapter.file_count !== record.adapter_file_count
      ) {
        errors.push("downstream preflight adapter manifest no longer matches its record");
      }
    } catch (error) {
      errors.push(`downstream preflight adapter manifest cannot be reverified: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  if (
    String(record.snapshot_source_commit || "").toLowerCase() !== expected.expectedConsumerHead ||
    String(record.snapshot_source_sha || "").toLowerCase() !== expected.expectedConsumerHead
  ) {
    errors.push("downstream preflight snapshot source identity does not match the clean consumer HEAD");
  }
  if (record.snapshot_version !== expected.expectedSnapshotVersion) {
    errors.push("downstream preflight snapshot version does not match");
  }
  if (record.runtime_version !== expected.expectedRuntimeVersion) {
    errors.push("downstream preflight runtime version does not match");
  }
  if (record.operator_server_version !== expected.expectedServerVersion) {
    errors.push("downstream preflight operator server version does not match");
  }
  if (record.temporal_graph_version !== expected.expectedTemporalGraphVersion) {
    errors.push("downstream preflight temporal graph version does not match");
  }
  if (record.temporal_event_version !== expected.expectedTemporalEventVersion) {
    errors.push("downstream preflight temporal event version does not match");
  }
  if (!Number.isInteger(record.temporal_event_count) || record.temporal_event_count < 1) {
    errors.push("downstream preflight temporal event count must prove a non-empty real timeline");
  }
  if (
    record.experience_pack_composition_version !==
    expected.expectedExperiencePackCompositionVersion
  ) {
    errors.push("downstream preflight experience pack composition version does not match");
  }
  if (String(record.composition_sha256 || "").toLowerCase() !== expected.expectedCompositionSha256) {
    errors.push("downstream preflight experience pack composition hash does not match");
  }
  if (JSON.stringify(record.active_packs) !== JSON.stringify(expected.expectedActivePacks)) {
    errors.push("downstream preflight active packs do not match");
  }
  if (!Array.isArray(record.contract_errors) || record.contract_errors.length !== 0) {
    errors.push("downstream preflight contract_errors must be an explicit empty array");
  }
  if (!Number.isInteger(record.page_count) || record.page_count < expected.minPages) {
    errors.push("downstream preflight page count is below the required minimum");
  }
  if (record.minimum_pages !== expected.minPages) {
    errors.push("downstream preflight declared minimum page count does not match");
  }
  if (!Array.isArray(record.capabilities)) {
    errors.push("downstream preflight capabilities are missing");
  } else {
    for (const capability of expected.expectedCapabilities) {
      if (!record.capabilities.includes(capability)) {
        errors.push(`downstream preflight capability ${capability} does not match`);
      }
    }
  }
  if (!Array.isArray(record.snapshot_capabilities)) {
    errors.push("downstream preflight snapshot capabilities are missing");
  } else {
    for (const capability of REQUIRED_SNAPSHOT_CAPABILITIES) {
      if (!record.snapshot_capabilities.includes(capability)) {
        errors.push(`downstream preflight snapshot capability ${capability} does not match`);
      }
    }
  }
  const expectedOrigin = new URL(expected.baseUrl).origin;
  if (
    record.endpoint_origins?.snapshot !== expectedOrigin ||
    record.endpoint_origins?.ui !== expectedOrigin
  ) {
    errors.push("downstream preflight endpoint origins do not match the same-origin UI boundary");
  }
  return { ok: errors.length === 0, errors };
}

function portableSpecPath(raw, rootDir, scope) {
  let normalized = String(raw || "").replaceAll("\\", "/");
  if (rootDir && normalized && !path.isAbsolute(normalized)) {
    normalized = path.resolve(rootDir, normalized).replaceAll("\\", "/");
  }
  const marker = normalized.lastIndexOf("/e2e/");
  if (marker >= 0) return normalized.slice(marker + 1);
  normalized = normalized.replace(/^\.\//, "");
  if (normalized.startsWith("e2e/")) return normalized;
  const prefix = scope === "downstream_required" ? "e2e/downstream/" : "e2e/";
  return `${prefix}${normalized}`;
}

function collectReportCells(report, scope) {
  const output = [];
  const rootDir = typeof report?.config?.rootDir === "string" ? report.config.rootDir : "";
  const visit = (suite, ancestors = []) => {
    const titles = suite?.title ? [...ancestors, String(suite.title)] : ancestors;
    for (const spec of suite?.specs ?? []) {
      const file = portableSpecPath(spec.file, rootDir, scope);
      const title = [...titles, String(spec.title || "")].filter(Boolean).join(" › ");
      for (const test of spec.tests ?? []) {
        const project = String(test.projectName || test.projectId || "").trim();
        output.push({
          id: `${project}::${file}::${title}`,
          file,
          project,
          title,
          test
        });
      }
    }
    for (const child of suite?.suites ?? []) visit(child, titles);
  };
  for (const suite of report?.suites ?? []) visit(suite);
  return output;
}

export function matrixCellsFromReport(report, scope) {
  return collectReportCells(report, scope)
    .map(({ id, file, project, title }) => ({ id, file, project, title }))
    .sort((left, right) => left.id < right.id ? -1 : left.id > right.id ? 1 : 0);
}

function sortedUnique(values) {
  return [...new Set(values)].sort();
}

export function summarizePlaywrightReport(report, scope = "public_required") {
  const summary = {
    passed: 0,
    failed: 0,
    skipped: 0,
    flaky: 0,
    retries: 0,
    total: 0,
    files: [],
    projects: []
  };
  const parserErrors = [];
  const topLevelErrors = Array.isArray(report?.errors) ? report.errors.length : 0;
  let testFailures = 0;
  summary.failed += topLevelErrors;
  for (const cell of collectReportCells(report, scope)) {
    const { file, project, test } = cell;
    if (file && !summary.files.includes(file)) summary.files.push(file);
    if (project && !summary.projects.includes(project)) summary.projects.push(project);
    summary.total += 1;
    const results = Array.isArray(test.results) ? test.results : [];
    const retryValues = results.map((result) => Number(result.retry));
    if (retryValues.some((value) => !Number.isInteger(value) || value < 0)) {
      parserErrors.push(`test ${cell.id} has an invalid retry value`);
    }
    const retryCount = retryValues.length ? Math.max(...retryValues.filter(Number.isInteger), 0) : 0;
    summary.retries += retryCount;
    const status = String(test.status || "");
    const finalStatus = String(results.at(-1)?.status || "");
    const expectedStatus = String(test.expectedStatus || "passed");
    const isSkipped = status === "skipped" || finalStatus === "skipped" || expectedStatus === "skipped";
    const isFlaky = status === "flaky" || retryCount > 0 || results.length > 1;
    const isPassed = expectedStatus === "passed" && finalStatus === "passed" && status === "expected";
    if (isSkipped) summary.skipped += 1;
    else if (isFlaky) summary.flaky += 1;
    else if (isPassed) summary.passed += 1;
    else {
      summary.failed += 1;
      testFailures += 1;
    }
  }
  summary.files.sort();
  summary.projects.sort();
  return { summary, parserErrors, testFailures, topLevelErrors };
}

export function evaluateRequiredPlaywrightReport(report, scope, matrixContract = null) {
  if (!["public_required", "downstream_required"].includes(scope)) {
    throw new Error(`unknown required scope: ${scope}`);
  }
  const parsed = summarizePlaywrightReport(report, scope);
  const { summary } = parsed;
  const cells = matrixCellsFromReport(report, scope);
  const errors = [...parsed.parserErrors];
  const stats = report?.stats;
  if (!stats || !["expected", "unexpected", "skipped", "flaky"].every((key) => Number.isInteger(stats[key]) && stats[key] >= 0)) {
    errors.push("Playwright report stats are missing or invalid");
  } else {
    const expectedStats = {
      expected: summary.passed,
      unexpected: parsed.testFailures,
      skipped: summary.skipped,
      flaky: summary.flaky
    };
    for (const [key, value] of Object.entries(expectedStats)) {
      if (stats[key] !== value) errors.push(`Playwright stats.${key} contradicts parsed tests`);
    }
    if (stats.expected + stats.unexpected + stats.skipped + stats.flaky !== summary.total) {
      errors.push("Playwright stats total contradicts collected tests");
    }
  }
  const config = report?.config;
  if (!config || typeof config !== "object") {
    errors.push("Playwright report config is missing");
  } else {
    if (config.forbidOnly !== true) errors.push("Playwright config must set forbidOnly=true");
    if (config.fullyParallel !== false) errors.push("Playwright config must set fullyParallel=false");
    if (config.workers !== 1) errors.push("Playwright config must use exactly one worker");
    if (!Array.isArray(config.projects) || config.projects.length === 0) {
      errors.push("Playwright config projects are missing");
    } else {
      for (const project of config.projects) {
        if (project.retries !== 0) errors.push(`Playwright project ${project.name || "(unnamed)"} must set retries=0`);
        if (project.repeatEach !== 1) errors.push(`Playwright project ${project.name || "(unnamed)"} must set repeatEach=1`);
      }
    }
  }
  if (summary.total === 0) errors.push("required matrix collected zero tests");
  if (summary.failed) errors.push(`${summary.failed} required test(s) failed`);
  if (summary.skipped) errors.push(`${summary.skipped} required test(s) skipped`);
  if (summary.flaky) errors.push(`${summary.flaky} required test(s) were flaky`);
  if (summary.retries) errors.push(`${summary.retries} retry attempt(s) were used`);
  const downstreamFiles = summary.files.filter((file) => /(^|\/)downstream\//.test(file));
  if (scope === "public_required" && downstreamFiles.length) {
    errors.push(`public matrix collected downstream spec(s): ${downstreamFiles.join(", ")}`);
  }
  if (scope === "downstream_required" && summary.files.some((file) => !/(^|\/)downstream\//.test(file))) {
    errors.push("downstream matrix collected a public spec");
  }
  if (matrixContract !== null) {
    if (
      matrixContract.schema_version !== RELEASE_MATRIX_SCHEMA ||
      matrixContract.contract_version !== RELEASE_MATRIX_CONTRACT_VERSION
    ) {
      errors.push("release matrix contract schema is invalid");
    }
    const required = matrixContract[scope];
    if (
      !required ||
      typeof required.test_dir !== "string" ||
      !Array.isArray(required.required_specs) ||
      !Array.isArray(required.required_projects) ||
      !Array.isArray(required.cells)
    ) {
      errors.push(`${scope} release matrix contract is incomplete`);
    } else {
      if (!Number.isInteger(required.expected_tests) || required.expected_tests !== required.cells.length) {
        errors.push(`${scope} expected_tests must equal the exact contract cell count`);
      }
      if (summary.total !== required.expected_tests) {
        errors.push(`${scope} collected ${summary.total} tests, expected exactly ${required.expected_tests}`);
      }
      const exactComparisons = [
        ["specs", summary.files, [...required.required_specs].sort()],
        ["projects", summary.projects, [...required.required_projects].sort()],
        [
          "cells",
          cells.map((cell) => cell.id),
          required.cells.map((cell) => cell.id).sort()
        ]
      ];
      for (const [label, actual, expected] of exactComparisons) {
        if (JSON.stringify(actual) !== JSON.stringify(expected)) {
          errors.push(`${scope} exact ${label} do not match the release matrix contract`);
        }
      }
      const contractCells = [...required.cells].sort((left, right) =>
        left.id < right.id ? -1 : left.id > right.id ? 1 : 0
      );
      if (JSON.stringify(cells) !== JSON.stringify(contractCells)) {
        errors.push(`${scope} cell metadata contradicts the release matrix contract`);
      }
      const configuredProjects = sortedUnique((config?.projects ?? []).map((project) => String(project.name || "")));
      if (JSON.stringify(configuredProjects) !== JSON.stringify([...required.required_projects].sort())) {
        errors.push(`${scope} configured projects do not match the release matrix contract`);
      }
      if (path.basename(String(config?.configFile || "")) !== required.config_file) {
        errors.push(`${scope} Playwright config file does not match the release matrix contract`);
      }
      const rootDir = String(config?.rootDir || "").replaceAll("\\", "/").replace(/\/$/, "");
      if (!rootDir.endsWith(`/${required.test_dir}`)) {
        errors.push(`${scope} Playwright testDir does not match the release matrix contract`);
      }
      if (String(config?.version || "") !== matrixContract.playwright_version) {
        errors.push("Playwright runner version does not match the release matrix contract");
      }
    }
  }
  return { ok: errors.length === 0, errors, summary, cells };
}

function scopeContract(report, scope, configFile) {
  const cells = matrixCellsFromReport(report, scope);
  if (!cells.length || new Set(cells.map((cell) => cell.id)).size !== cells.length) {
    throw new Error(`${scope} list report must contain non-empty, unique cells`);
  }
  const config = report?.config;
  if (
    !config ||
    config.forbidOnly !== true ||
    config.fullyParallel !== false ||
    config.workers !== 1 ||
    path.basename(String(config.configFile || "")) !== configFile ||
    !Array.isArray(config.projects) ||
    config.projects.some((project) => project.retries !== 0 || project.repeatEach !== 1)
  ) {
    throw new Error(`${scope} list report uses an unsafe or unexpected Playwright config`);
  }
  const files = sortedUnique(cells.map((cell) => cell.file));
  const projects = sortedUnique(cells.map((cell) => cell.project));
  const configuredProjects = sortedUnique(config.projects.map((project) => String(project.name || "")));
  if (JSON.stringify(projects) !== JSON.stringify(configuredProjects)) {
    throw new Error(`${scope} configured projects and collected cells differ`);
  }
  if (
    (scope === "public_required" && files.some((file) => /(^|\/)downstream\//.test(file))) ||
    (scope === "downstream_required" && files.some((file) => !/(^|\/)downstream\//.test(file)))
  ) {
    throw new Error(`${scope} list report crosses the public/downstream boundary`);
  }
  if ((report.errors ?? []).length) {
    throw new Error(`${scope} list report contains top-level collection errors`);
  }
  return {
    config_file: configFile,
    test_dir: scope === "downstream_required" ? "e2e/downstream" : "e2e",
    expected_tests: cells.length,
    required_specs: files,
    required_projects: projects,
    cells
  };
}

export function buildReleaseMatrixContract(publicReport, downstreamReport) {
  const publicVersion = String(publicReport?.config?.version || "");
  const downstreamVersion = String(downstreamReport?.config?.version || "");
  if (!publicVersion || publicVersion !== downstreamVersion) {
    throw new Error("public and downstream list reports must use one exact Playwright version");
  }
  return {
    schema_version: RELEASE_MATRIX_SCHEMA,
    contract_version: RELEASE_MATRIX_CONTRACT_VERSION,
    playwright_version: publicVersion,
    public_required: scopeContract(publicReport, "public_required", "playwright.config.ts"),
    downstream_required: scopeContract(
      downstreamReport,
      "downstream_required",
      "playwright.downstream.config.ts"
    )
  };
}

export function sha256Bytes(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}
