import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import net from "node:net";
import path from "node:path";
import { execFileSync, spawnSync } from "node:child_process";
import nodeTest from "node:test";
import { fileURLToPath } from "node:url";

// RETIRED_RELEASE_MACHINE: exact release matrices and lane receipts are no
// longer project gates. Preserve these tests as historical documentation only.
const test = Object.assign(
  (...args) => nodeTest.skip(...args),
  { after: nodeTest.after }
);
import {
  buildReleaseMatrixContract,
  evaluateDownstreamPreflightRecord as evaluateDownstreamPreflightRecordCore,
  evaluateRequiredPlaywrightReport,
  matrixCellsFromReport,
  runDownstreamPreflight as runDownstreamPreflightCore,
  sha256CanonicalJson,
  validateDownstreamEnvironment,
  verifyDownstreamAdapterManifest
} from "./release-matrix-lib.mjs";
import { collectCurrentReleaseMatrix } from "./release-matrix-contract.mjs";
import { assertReleasePortAvailable } from "./release-server-policy.mjs";
import {
  assertSameReleaseBuild,
  collectReleaseBuildManifest
} from "./release-build-manifest.mjs";
import {
  assertGenericReleaseBuildEnvironment,
  assertInternalReleaseBuildEnvironment,
  effectiveReleaseBuildInputs,
  sanitizedReleaseBuildEnvironment
} from "./release-build-policy.mjs";
import {
  materializePublicReleaseRuntimeConfig,
  PUBLIC_RELEASE_RUNTIME_CONFIG_PATH,
  verifyPublicReleaseRuntimeConfig
} from "./public-release-runtime-config.mjs";
import {
  assertReleaseEvidencePlatform,
  RELEASE_DERIVED_ROOT,
  TEST_RESULTS_ROOT,
  resolveOwnedReleaseFile,
  writeOwnedReleaseFile,
  writeOwnedReleaseFileAtomic
} from "./release-path-safety.mjs";

test("release evidence mutations fail closed on Windows", () => {
  assert.throws(
    () => assertReleaseEvidencePlatform("win32"),
    /unsupported on Windows/
  );
  assert.doesNotThrow(() => assertReleaseEvidencePlatform("darwin"));
});

const SCRIPTS_ROOT = path.dirname(fileURLToPath(import.meta.url));
const APP_ROOT = path.dirname(SCRIPTS_ROOT);
const REPO_ROOT = path.resolve(APP_ROOT, "../..");

test("release build policy rejects env files and every build-affecting variable", () => {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "wiki-build-policy-"));
  try {
    assert.deepEqual(
      assertGenericReleaseBuildEnvironment(fixture, {}),
      effectiveReleaseBuildInputs()
    );
    for (const environment of [
      { BABEL_ENV: "production" },
      { ESBUILD_BINARY_PATH: "/tmp/alternate-esbuild" },
      { NODE_ENV: "development" },
      { NODE_OPTIONS: "--require=/tmp/hook.cjs" },
      { NODE_PATH: "/tmp/node-modules" },
      { WIKI_COCKPIT_PROXY_API: "1" },
      { VITE_WIKI_API_BASE: "https://example.invalid" },
      { VITE_UNRELATED_BUT_EXPOSED: "different-dist" },
      { WIKI_COCKPIT_RELEASE_BUILD_INTERNAL: "1" }
    ]) {
      assert.throws(
        () => assertGenericReleaseBuildEnvironment(fixture, environment),
        /environment is not reproducible/
      );
    }
    for (const name of [".env", ".env.local", ".env.production", ".env.production.local"]) {
      const target = path.join(fixture, name);
      fs.writeFileSync(target, "VITE_WIKI_REPO_LABEL=hidden\n");
      assert.throws(
        () => assertGenericReleaseBuildEnvironment(fixture, {}),
        /remove app-local \.env files/
      );
      fs.unlinkSync(target);
    }
  } finally {
    fs.rmSync(fixture, { recursive: true, force: true });
  }
});

test("release build runner sanitizes to one exact internal environment", () => {
  const sanitized = sanitizedReleaseBuildEnvironment();
  assert.equal(
    sanitized.PATH,
    [path.dirname(process.execPath), "/usr/bin", "/bin"].join(path.delimiter)
  );
  assert.equal(sanitized.NODE_ENV, "production");
  assert.equal(sanitized.WIKI_COCKPIT_RELEASE_BUILD_INTERNAL, "1");
  assert.deepEqual(Object.keys(sanitized).sort(), [
    "LANG",
    "LC_ALL",
    "NODE_ENV",
    "PATH",
    "SOURCE_DATE_EPOCH",
    "TZ",
    "WIKI_COCKPIT_RELEASE_BUILD_INTERNAL"
  ]);
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "wiki-build-internal-"));
  try {
    assert.doesNotThrow(() => assertInternalReleaseBuildEnvironment(fixture, sanitized));
    assert.throws(
      () => assertInternalReleaseBuildEnvironment(fixture, { NODE_ENV: "production" }),
      /must run through the release build runner/
    );
  } finally {
    fs.rmSync(fixture, { recursive: true, force: true });
  }
});

test("POSIX build launcher refuses a PATH-injected fake Node executable", () => {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "wiki-build-launcher-"));
  try {
    const fakeNode = path.join(fixture, "node");
    fs.writeFileSync(fakeNode, "#!/bin/sh\nenv | sort\n");
    fs.chmodSync(fakeNode, 0o755);
    const result = spawnSync(
      "sh",
      [path.join(SCRIPTS_ROOT, "build-production.sh")],
      {
        encoding: "utf8",
        env: {
          ...process.env,
          PATH: `${fixture}:${process.env.PATH || ""}`,
          NODE_OPTIONS: "--require=/tmp/hostile-hook.cjs",
          NODE_PATH: "/tmp/hostile-modules",
          BABEL_ENV: "hostile",
          ESBUILD_BINARY_PATH: "/tmp/hostile-esbuild",
          VITE_WIKI_REPO_LABEL: "hostile"
        }
      }
    );
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /requires a native Node executable/);
  } finally {
    fs.rmSync(fixture, { recursive: true, force: true });
  }
});

test("release build manifest records exact safe inputs and rejects input tampering", () => {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "wiki-build-manifest-"));
  try {
    fs.mkdirSync(path.join(fixture, "scripts"));
    fs.mkdirSync(path.join(fixture, "dist"));
    const publicConfig = fs.readFileSync(path.join(APP_ROOT, ...PUBLIC_RELEASE_RUNTIME_CONFIG_PATH.split("/")));
    fs.writeFileSync(path.join(fixture, ...PUBLIC_RELEASE_RUNTIME_CONFIG_PATH.split("/")), publicConfig);
    fs.writeFileSync(path.join(fixture, "dist", "wiki-cockpit.config.json"), publicConfig);
    fs.writeFileSync(path.join(fixture, "dist", "index.html"), "<!doctype html>\n");
    const manifest = collectReleaseBuildManifest(fixture, "a".repeat(40), {});
    assert.equal(manifest.schema_version, "wiki_release_build_manifest.v2");
    assert.deepEqual(manifest.build_inputs, effectiveReleaseBuildInputs());
    assert.equal(manifest.builder_runtime.node_version, process.versions.node);
    assert.match(manifest.builder_runtime.node_executable_sha256, /^[0-9a-f]{64}$/);
    assert.ok(manifest.builder_runtime.node_executable_bytes > 0);
    const tampered = structuredClone(manifest);
    tampered.build_inputs.node_env = "development";
    assert.throws(
      () => assertSameReleaseBuild(manifest, tampered),
      /served release dist changed/
    );
  } finally {
    fs.rmSync(fixture, { recursive: true, force: true });
  }
});

test("release build replaces a consumer config only inside dist with the package-owned static demo", () => {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "wiki-public-config-"));
  try {
    fs.mkdirSync(path.join(fixture, "scripts"));
    fs.mkdirSync(path.join(fixture, "public"));
    fs.mkdirSync(path.join(fixture, "dist"));
    const source = fs.readFileSync(path.join(APP_ROOT, ...PUBLIC_RELEASE_RUNTIME_CONFIG_PATH.split("/")));
    const consumer = Buffer.from('{"mode":"local_operator","api_base":"/api/private"}\n');
    fs.writeFileSync(path.join(fixture, ...PUBLIC_RELEASE_RUNTIME_CONFIG_PATH.split("/")), source);
    fs.writeFileSync(path.join(fixture, "public", "wiki-cockpit.config.json"), consumer);
    fs.writeFileSync(path.join(fixture, "dist", "wiki-cockpit.config.json"), consumer);
    fs.writeFileSync(path.join(fixture, ".gitignore"), "dist/\n");
    execFileSync("git", ["init", "-q"], { cwd: fixture });
    execFileSync("git", ["config", "user.email", "release-config@example.test"], { cwd: fixture });
    execFileSync("git", ["config", "user.name", "Release Config Test"], { cwd: fixture });
    execFileSync("git", ["add", ".gitignore", "public", "scripts"], { cwd: fixture });
    execFileSync("git", ["commit", "-qm", "config fixture"], { cwd: fixture });
    const subjectBefore = {
      head: execFileSync("git", ["rev-parse", "HEAD"], { cwd: fixture, encoding: "utf8" }).trim(),
      tree: execFileSync("git", ["rev-parse", "HEAD^{tree}"], { cwd: fixture, encoding: "utf8" }).trim(),
      status: execFileSync("git", ["status", "--porcelain=v1"], { cwd: fixture, encoding: "utf8" })
    };

    const evidence = materializePublicReleaseRuntimeConfig(fixture);

    assert.deepEqual(fs.readFileSync(path.join(fixture, "public", "wiki-cockpit.config.json")), consumer);
    assert.deepEqual(fs.readFileSync(path.join(fixture, "dist", "wiki-cockpit.config.json")), source);
    assert.equal(evidence.source_path, PUBLIC_RELEASE_RUNTIME_CONFIG_PATH);
    assert.equal(evidence.output_path, "dist/wiki-cockpit.config.json");
    assert.doesNotThrow(() => verifyPublicReleaseRuntimeConfig(fixture));
    assert.deepEqual({
      head: execFileSync("git", ["rev-parse", "HEAD"], { cwd: fixture, encoding: "utf8" }).trim(),
      tree: execFileSync("git", ["rev-parse", "HEAD^{tree}"], { cwd: fixture, encoding: "utf8" }).trim(),
      status: execFileSync("git", ["status", "--porcelain=v1"], { cwd: fixture, encoding: "utf8" })
    }, subjectBefore);

    fs.writeFileSync(path.join(fixture, ...PUBLIC_RELEASE_RUNTIME_CONFIG_PATH.split("/")), '{"mode":"local_operator"}\n');
    assert.throws(
      () => materializePublicReleaseRuntimeConfig(fixture),
      /exact public synthetic static-demo contract/
    );

    const sourcePath = path.join(fixture, ...PUBLIC_RELEASE_RUNTIME_CONFIG_PATH.split("/"));
    const linkedSource = path.join(fixture, "scripts", "linked-public-config.json");
    fs.rmSync(sourcePath);
    fs.writeFileSync(linkedSource, source);
    fs.linkSync(linkedSource, sourcePath);
    assert.throws(
      () => materializePublicReleaseRuntimeConfig(fixture),
      /regular non-hard-linked file/
    );

    fs.rmSync(sourcePath);
    fs.rmSync(linkedSource);
    fs.writeFileSync(sourcePath, source);
    const outputPath = path.join(fixture, "dist", "wiki-cockpit.config.json");
    fs.rmSync(outputPath);
    fs.symlinkSync(path.join(fixture, "public", "wiki-cockpit.config.json"), outputPath);
    assert.throws(
      () => materializePublicReleaseRuntimeConfig(fixture),
      /output must be a regular non-hard-linked file/
    );

    fs.rmSync(outputPath);
    fs.linkSync(path.join(fixture, "public", "wiki-cockpit.config.json"), outputPath);
    assert.throws(
      () => materializePublicReleaseRuntimeConfig(fixture),
      /output must be a regular non-hard-linked file/
    );
  } finally {
    fs.rmSync(fixture, { recursive: true, force: true });
  }
});

function runNodeScript(script, args, env = {}) {
  return spawnSync(process.execPath, [path.join("scripts", script), ...args], {
    cwd: APP_ROOT,
    env: { ...process.env, ...env },
    encoding: "utf8"
  });
}

function checkerProvenance(nonce) {
  return [
    "--run-id", `fixture-${nonce}`,
    "--started-at", "2026-07-11T12:00:00Z",
    "--run-result", `${TEST_RESULTS_ROOT}/fixture-${nonce}/run-result.json`
  ];
}

const HASH = "a".repeat(64);
const CONSUMER_HEAD = "b".repeat(40);
const PUBLIC_RELEASE_SHA = "c".repeat(40);

function adapterFixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "wiki-adapter-node-"));
  fs.mkdirSync(path.join(root, "adapters"));
  const filePath = "adapters/local.mjs";
  const raw = Buffer.from("export const localAdapter = 'v1';\n", "utf8");
  fs.writeFileSync(path.join(root, filePath), raw);
  const files = [{
    path: filePath,
    sha256: crypto.createHash("sha256").update(raw).digest("hex"),
    bytes: raw.byteLength
  }];
  const adapterHash = sha256CanonicalJson({
    schema_version: "wiki_downstream_adapter_manifest.v1",
    files
  });
  fs.writeFileSync(path.join(root, "wiki.adapter-manifest.json"), `${JSON.stringify({
    schema_version: "wiki_downstream_adapter_manifest.v1",
    files,
    adapter_sha256: adapterHash
  }, null, 2)}\n`);
  execFileSync("git", ["init", "-q"], { cwd: root });
  execFileSync("git", ["config", "user.email", "adapter@example.test"], { cwd: root });
  execFileSync("git", ["config", "user.name", "Adapter Test"], { cwd: root });
  execFileSync("git", ["add", "."], { cwd: root });
  execFileSync("git", ["commit", "-qm", "adapter fixture"], { cwd: root });
  return { root, adapterHash, filePath };
}

const ADAPTER_FIXTURE = adapterFixture();
const ADAPTER_HASH = ADAPTER_FIXTURE.adapterHash;
test.after(() => fs.rmSync(ADAPTER_FIXTURE.root, { recursive: true, force: true }));

function runDownstreamPreflight(env, fetchImpl, fetchOptions = {}) {
  return runDownstreamPreflightCore(env, fetchImpl, fetchOptions, ADAPTER_FIXTURE.root);
}

function evaluateDownstreamPreflightRecord(record, env) {
  return evaluateDownstreamPreflightRecordCore(record, env, ADAPTER_FIXTURE.root);
}
const EMPTY_SLOTS = Object.freeze({ views: [], commands: [], operations: [], timelines: [] });

function fixturePresentation(packs, slots) {
  const identifiers = [...new Set([
    ...packs.map((pack) => pack.id),
    ...Object.values(slots).flat()
      .filter((row) => row && typeof row === "object" && typeof row.contribution === "string")
      .map((row) => row.contribution)
  ])].sort();
  const labels = Object.fromEntries(identifiers.map((identifier) => [identifier, identifier]));
  return { default_locale: "en", locales: { en: labels, "pt-BR": { ...labels } } };
}

function compositionFixture({ packs = [], blockPackages = [], slots = EMPTY_SLOTS, presentation = fixturePresentation(packs, slots) } = {}) {
  const semantic = { packs, block_packages: blockPackages, slots, presentation };
  return {
    schema_version: "wiki_experience_pack_composition.v1",
    core_version: "8.0.0",
    ...semantic,
    composition_sha256: sha256CanonicalJson(semantic)
  };
}

function temporalEventFixture(overrides = {}) {
  return {
    schema_version: "wiki_temporal_event.v1",
    event_id: "evt_snapshot_recorded_0123456789abcdef01234567",
    kind: "snapshot_recorded",
    subject_refs: ["system:wiki-viva"],
    context_refs: ["context:system"],
    occurred_at: null,
    recorded_at: "2026-07-11T12:00:00Z",
    valid_from: null,
    valid_to: null,
    created_at: null,
    due_at: null,
    completed_at: null,
    verified_at: null,
    ingested_at: null,
    superseded_at: null,
    precision: { recorded_at: "instant" },
    actor: null,
    source_refs: [],
    evidence_refs: [],
    caused_by: [],
    supersedes: [],
    before: {},
    after: {},
    confidence: "confirmed",
    visibility: "private",
    origin: { adapter: "release_fixture.v1" },
    temporal_conflicts: [],
    anchor: { field: "recorded_at", value: "2026-07-11T12:00:00Z", precision: "instant" },
    ...overrides
  };
}

function temporalFixture(overrides = {}) {
  const { events = [temporalEventFixture()], ...envelopeOverrides } = overrides;
  const fingerprint = sha256CanonicalJson(events);
  const anchors = events.map((event) => event?.anchor).filter(Boolean);
  const byKind = {};
  const byContext = {};
  for (const event of events) {
    const kind = String(event?.kind || "");
    byKind[kind] = (byKind[kind] ?? 0) + 1;
    for (const context of event?.context_refs ?? []) byContext[context] = (byContext[context] ?? 0) + 1;
  }
  const range = {
    from: anchors[0]?.value ?? null,
    to: anchors.at(-1)?.value ?? null,
    from_precision: anchors[0]?.precision ?? null,
    to_precision: anchors.at(-1)?.precision ?? null,
    event_count: events.length,
    dated_count: anchors.length,
    undated_count: events.length - anchors.length,
    basis: "full_result"
  };
  return {
    schema_version: "wiki_temporal_graph.v1",
    event_schema_version: "wiki_temporal_event.v1",
    repo_id: "private-pilot",
    revision: `sha256:${fingerprint}`,
    generated_at: "2026-07-11T12:00:00Z",
    event_count: events.length,
    total_count: events.length,
    returned_count: events.length,
    truncated: false,
    next_cursor: null,
    page: { offset: 0, limit: events.length, remaining_count: 0, fingerprint },
    range,
    returned_range: { ...range, basis: "returned_page" },
    summary: {
      scope: "full_result",
      event_count: events.length,
      by_kind: byKind,
      by_context: byContext,
      conflict_count: events.filter((event) => event?.temporal_conflicts?.length).length,
      imprecise_count: events.filter((event) => Object.values(event?.precision ?? {}).some((value) => value === "year" || value === "month")).length,
      diagnostic_count: 0
    },
    diagnostics: [],
    events,
    ...envelopeOverrides
  };
}

const EMPTY_COMPOSITION = compositionFixture();
const TEMPORAL_GRAPH = temporalFixture();
const VALID_ENV = {
  WIKI_COCKPIT_SNAPSHOT_URL: "http://127.0.0.1:5173/api/snapshot/pages.json",
  WIKI_COCKPIT_REAL_BASE_URL: "http://127.0.0.1:5173",
  WIKI_COCKPIT_EXPECT_REPO_ID: "private-pilot",
  WIKI_COCKPIT_EXPECT_SNAPSHOT_REVISION: "private-pilot-aaaaaaaaaaaaaaaa",
  WIKI_COCKPIT_EXPECT_SNAPSHOT_HASH: HASH,
  WIKI_COCKPIT_EXPECT_CONSUMER_HEAD: CONSUMER_HEAD,
  WIKI_COCKPIT_EXPECT_PUBLIC_RELEASE_SHA: PUBLIC_RELEASE_SHA,
  WIKI_COCKPIT_EXPECT_ADAPTER_HASH: ADAPTER_HASH,
  WIKI_COCKPIT_EXPECT_SNAPSHOT_VERSION: "wiki_web_snapshot.v2",
  WIKI_COCKPIT_EXPECT_RUNTIME_VERSION: "wiki_world_runtime.v8",
  WIKI_COCKPIT_EXPECT_SERVER_VERSION: "wiki_web_server.v6",
  WIKI_COCKPIT_EXPECT_TEMPORAL_GRAPH_VERSION: "wiki_temporal_graph.v1",
  WIKI_COCKPIT_EXPECT_TEMPORAL_EVENT_VERSION: "wiki_temporal_event.v1",
  WIKI_COCKPIT_EXPECT_EXPERIENCE_PACK_COMPOSITION_VERSION: "wiki_experience_pack_composition.v1",
  WIKI_COCKPIT_EXPECT_COMPOSITION_SHA256: EMPTY_COMPOSITION.composition_sha256,
  WIKI_COCKPIT_EXPECT_ACTIVE_PACKS: "[]",
  WIKI_COCKPIT_EXPECT_CAPABILITIES: "operator_security_v2,cors_default_deny_v1,action_state_transitions_v1",
  WIKI_COCKPIT_MIN_PAGES: "42"
};

function response(body) {
  const text = JSON.stringify(body);
  return {
    ok: true,
    status: 200,
    headers: {
      get: (name) => {
        if (name.toLowerCase() === "content-type") return "application/json";
        if (name.toLowerCase() === "content-length") return String(Buffer.byteLength(text));
        return null;
      }
    },
    text: async () => text
  };
}

function validManifest(overrides = {}) {
  return {
    repo: { repo_id: "private-pilot" },
    snapshot_id: "private-pilot-aaaaaaaaaaaaaaaa",
    bundle_hash: HASH,
    source_commit: CONSUMER_HEAD,
    source_sha: CONSUMER_HEAD,
    versions: {
      snapshot: "wiki_web_snapshot.v2",
      runtime_contract: "wiki_world_runtime.v8",
      temporal_graph: "wiki_temporal_graph.v1",
      temporal_event: "wiki_temporal_event.v1",
      experience_pack_composition: "wiki_experience_pack_composition.v1"
    },
    capabilities: ["temporal_graph", "experience_packs"],
    integrity: {
      "pages.json": {
        sha256: sha256CanonicalJson(validPages()),
        bytes: Buffer.byteLength(JSON.stringify(validPages()))
      },
      "temporal_graph.json": {
        sha256: sha256CanonicalJson(TEMPORAL_GRAPH),
        bytes: Buffer.byteLength(JSON.stringify(TEMPORAL_GRAPH))
      },
      "experience_packs.json": {
        sha256: sha256CanonicalJson(EMPTY_COMPOSITION),
        bytes: Buffer.byteLength(JSON.stringify(EMPTY_COMPOSITION))
      }
    },
    contract_errors: [],
    ...overrides
  };
}

function manifestForPayloads(temporalGraph, experiencePacks, overrides = {}) {
  return validManifest({
    integrity: {
      ...validManifest().integrity,
      "temporal_graph.json": {
        sha256: sha256CanonicalJson(temporalGraph),
        bytes: Buffer.byteLength(JSON.stringify(temporalGraph))
      },
      "experience_packs.json": {
        sha256: sha256CanonicalJson(experiencePacks),
        bytes: Buffer.byteLength(JSON.stringify(experiencePacks))
      }
    },
    ...overrides
  });
}

function validPages() {
  return {
    repo_id: "private-pilot",
    pages: Array.from({ length: 42 }, () => ({}))
  };
}

function validHealth(overrides = {}) {
  return {
    ok: true,
    repo: "private-pilot",
    server_version: "wiki_web_server.v6",
    schema_capabilities: [
      "operator_security_v2",
      "cors_default_deny_v1",
      "action_state_transitions_v1"
    ],
    operator_security: {
      version: "wiki_operator_security.v2",
      nonce_header: "X-Wiki-Operator-Nonce",
      nonce: "release-preflight-nonce",
      attempt_header: "X-Wiki-Attempt-Key",
      max_body_bytes: 1_048_576,
      mutations: "post_only",
      browser_origin_default: "deny",
      cors_opt_in: "exact_loopback_allowlist"
    },
    ...overrides
  };
}

function validRuntimeConfig(overrides = {}) {
  return {
    mode: "local_operator",
    adoption: {
      public_release_sha: PUBLIC_RELEASE_SHA,
      adapter_hash: ADAPTER_HASH,
      adapter_manifest: "wiki.adapter-manifest.json"
    },
    ...overrides
  };
}

function fixtureFetch({
  pages = validPages(),
  manifest = validManifest(),
  temporalGraph = TEMPORAL_GRAPH,
  experiencePacks = EMPTY_COMPOSITION,
  health = validHealth(),
  runtimeConfig = validRuntimeConfig()
} = {}) {
  return async (url) => {
    if (url.endsWith("pages.json")) return response(pages);
    if (url.endsWith("manifest.json")) return response(manifest);
    if (url.endsWith("temporal_graph.json")) return response(temporalGraph);
    if (url.endsWith("experience_packs.json")) return response(experiencePacks);
    if (url.endsWith("wiki-cockpit.config.json")) return response(runtimeConfig);
    return response(health);
  };
}

test("downstream preflight requires every exact attestation with no defaults", () => {
  const result = validateDownstreamEnvironment({});
  assert.equal(result.ok, false);
  for (const key of Object.keys(VALID_ENV)) assert.ok(result.errors.some((message) => message.includes(key)));
});

test("downstream adapter manifest is independently compiled from tracked clean files", (t) => {
  const fixture = adapterFixture();
  t.after(() => fs.rmSync(fixture.root, { recursive: true, force: true }));
  const evidence = verifyDownstreamAdapterManifest(
    fixture.root,
    "wiki.adapter-manifest.json",
    fixture.adapterHash
  );
  assert.equal(evidence.schema_version, "wiki_downstream_adapter_manifest.v1");
  assert.equal(evidence.adapter_sha256, fixture.adapterHash);
  assert.equal(evidence.file_count, 1);

  fs.appendFileSync(path.join(fixture.root, fixture.filePath), "// dirty\n");
  assert.throws(
    () => verifyDownstreamAdapterManifest(fixture.root, "wiki.adapter-manifest.json", fixture.adapterHash),
    /clean consumer HEAD/
  );
});

test("downstream adapter manifest rejects cycles, traversal and private or sensitive paths", (t) => {
  for (const unsafePath of [
    "../adapter.mjs",
    "apps/wiki-cockpit/public/wiki-cockpit.config.json",
    "wiki.adapter-manifest.json",
    "memories/private.md",
    "data/raw/export.csv",
    "adapters/.env.local",
    "adapters/my-secrets.json"
  ]) {
    const fixture = adapterFixture();
    t.after(() => fs.rmSync(fixture.root, { recursive: true, force: true }));
    const files = [{ path: unsafePath, sha256: "0".repeat(64), bytes: 0 }];
    const adapterHash = sha256CanonicalJson({
      schema_version: "wiki_downstream_adapter_manifest.v1",
      files
    });
    fs.writeFileSync(path.join(fixture.root, "wiki.adapter-manifest.json"), JSON.stringify({
      schema_version: "wiki_downstream_adapter_manifest.v1",
      files,
      adapter_sha256: adapterHash
    }));
    execFileSync("git", ["add", "wiki.adapter-manifest.json"], { cwd: fixture.root });
    execFileSync("git", ["commit", "-qm", `unsafe ${crypto.randomUUID()}`], { cwd: fixture.root });
    assert.throws(
      () => verifyDownstreamAdapterManifest(fixture.root, "wiki.adapter-manifest.json", adapterHash),
      /canonical repo-relative|hash cycle|include itself|private\/raw\/derived|sensitive name/,
      unsafePath
    );
  }
});

test("downstream adapter manifest rejects untracked, symlinked, hard-linked and stale bytes", (t) => {
  const untracked = adapterFixture();
  t.after(() => fs.rmSync(untracked.root, { recursive: true, force: true }));
  fs.writeFileSync(path.join(untracked.root, "untracked.mjs"), "export default 1;\n");
  const untrackedRaw = fs.readFileSync(path.join(untracked.root, "untracked.mjs"));
  const untrackedFiles = [{
    path: "untracked.mjs",
    sha256: crypto.createHash("sha256").update(untrackedRaw).digest("hex"),
    bytes: untrackedRaw.byteLength
  }];
  const untrackedHash = sha256CanonicalJson({ schema_version: "wiki_downstream_adapter_manifest.v1", files: untrackedFiles });
  fs.writeFileSync(path.join(untracked.root, "wiki.adapter-manifest.json"), JSON.stringify({
    schema_version: "wiki_downstream_adapter_manifest.v1",
    files: untrackedFiles,
    adapter_sha256: untrackedHash
  }));
  execFileSync("git", ["add", "wiki.adapter-manifest.json"], { cwd: untracked.root });
  execFileSync("git", ["commit", "-qm", "point at untracked"], { cwd: untracked.root });
  assert.throws(
    () => verifyDownstreamAdapterManifest(untracked.root, "wiki.adapter-manifest.json", untrackedHash),
    /not tracked/
  );

  const symlinked = adapterFixture();
  t.after(() => fs.rmSync(symlinked.root, { recursive: true, force: true }));
  fs.symlinkSync("local.mjs", path.join(symlinked.root, "adapters/link.mjs"));
  execFileSync("git", ["add", "adapters/link.mjs"], { cwd: symlinked.root });
  execFileSync("git", ["commit", "-qm", "track symlink"], { cwd: symlinked.root });
  const symlinkManifest = JSON.parse(fs.readFileSync(path.join(symlinked.root, "wiki.adapter-manifest.json"), "utf8"));
  symlinkManifest.files[0].path = "adapters/link.mjs";
  symlinkManifest.adapter_sha256 = sha256CanonicalJson({
    schema_version: symlinkManifest.schema_version,
    files: symlinkManifest.files
  });
  fs.writeFileSync(path.join(symlinked.root, "wiki.adapter-manifest.json"), JSON.stringify(symlinkManifest));
  execFileSync("git", ["add", "wiki.adapter-manifest.json"], { cwd: symlinked.root });
  execFileSync("git", ["commit", "-qm", "manifest symlink"], { cwd: symlinked.root });
  assert.throws(
    () => verifyDownstreamAdapterManifest(symlinked.root, "wiki.adapter-manifest.json", symlinkManifest.adapter_sha256),
    /symlink/
  );

  const linked = adapterFixture();
  t.after(() => fs.rmSync(linked.root, { recursive: true, force: true }));
  fs.linkSync(path.join(linked.root, linked.filePath), path.join(linked.root, "adapters/hard.mjs"));
  execFileSync("git", ["add", "adapters/hard.mjs"], { cwd: linked.root });
  execFileSync("git", ["commit", "-qm", "track hardlink"], { cwd: linked.root });
  const linkedManifest = JSON.parse(fs.readFileSync(path.join(linked.root, "wiki.adapter-manifest.json"), "utf8"));
  linkedManifest.files[0].path = "adapters/hard.mjs";
  linkedManifest.adapter_sha256 = sha256CanonicalJson({
    schema_version: linkedManifest.schema_version,
    files: linkedManifest.files
  });
  fs.writeFileSync(path.join(linked.root, "wiki.adapter-manifest.json"), JSON.stringify(linkedManifest));
  execFileSync("git", ["add", "wiki.adapter-manifest.json"], { cwd: linked.root });
  execFileSync("git", ["commit", "-qm", "manifest hardlink"], { cwd: linked.root });
  assert.throws(
    () => verifyDownstreamAdapterManifest(linked.root, "wiki.adapter-manifest.json", linkedManifest.adapter_sha256),
    /hard-linked/
  );
});

test("downstream preflight rejects remote endpoints and weak security capabilities", () => {
  const result = validateDownstreamEnvironment({
    ...VALID_ENV,
    WIKI_COCKPIT_REAL_BASE_URL: "https://example.test",
    WIKI_COCKPIT_EXPECT_CAPABILITIES: "operator_security_v2"
  });
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((message) => message.includes("loopback")));
  assert.ok(result.errors.some((message) => message.includes("cors_default_deny_v1")));
  assert.ok(result.errors.some((message) => message.includes("action_state_transitions_v1")));
});

test("downstream environment cannot bless an obsolete version by declaring it expected", () => {
  const result = validateDownstreamEnvironment({
    ...VALID_ENV,
    WIKI_COCKPIT_EXPECT_SERVER_VERSION: "wiki_web_server.v5"
  });
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((message) => message.includes("release-required wiki_web_server.v6")));
});

test("downstream preflight validates the complete shared operator security handshake", async () => {
  const invalidSecurity = [
    [undefined, /operator security object is missing/],
    [{ ...validHealth().operator_security, version: "wiki_operator_security.v1" }, /security version/],
    [{ ...validHealth().operator_security, nonce: "" }, /security nonce is missing/],
    [{ ...validHealth().operator_security, nonce_header: "X-Other" }, /nonce header/],
    [{ ...validHealth().operator_security, attempt_header: "X-Other" }, /attempt header/],
    [{ ...validHealth().operator_security, max_body_bytes: 0 }, /max body bytes/],
    [{ ...validHealth().operator_security, mutations: "get_or_post" }, /mutations contract/],
    [{ ...validHealth().operator_security, browser_origin_default: "allow" }, /origin default/],
    [{ ...validHealth().operator_security, cors_opt_in: "wildcard" }, /CORS opt-in/]
  ];
  for (const [operator_security, expected] of invalidSecurity) {
    await assert.rejects(
      () => runDownstreamPreflight(VALID_ENV, fixtureFetch({
        health: validHealth({ operator_security })
      })),
      expected
    );
  }

  await assert.rejects(
    () => runDownstreamPreflight(VALID_ENV, fixtureFetch({
      health: validHealth({
        schema_capabilities: ["operator_security_v2", "cors_default_deny_v1"]
      })
    })),
    /action_state_transitions_v1/
  );
});

test("downstream environment requires a canonical explicit active-pack JSON contract", () => {
  for (const activePacks of [
    "",
    "personal-finance",
    '[{"id":"personal-finance","version":"0.1.0","secret":"x"}]',
    '[{"id":"study-research","version":"0.1.0"},{"id":"personal-finance","version":"0.1.0"}]',
    '[{"id":"personal-finance","version":"0.1.0"},{"id":"personal-finance","version":"0.1.0"}]'
  ]) {
    const result = validateDownstreamEnvironment({
      ...VALID_ENV,
      WIKI_COCKPIT_EXPECT_ACTIVE_PACKS: activePacks
    });
    assert.equal(result.ok, false, activePacks);
    assert.ok(result.errors.some((message) => message.includes("ACTIVE_PACKS")), activePacks);
  }
  assert.equal(validateDownstreamEnvironment(VALID_ENV).ok, true, "[] is an explicit valid empty state");
});

test("downstream preflight binds snapshot and UI to the same origin", () => {
  const result = validateDownstreamEnvironment({
    ...VALID_ENV,
    WIKI_COCKPIT_SNAPSHOT_URL: "http://127.0.0.1:8765/api/snapshot/pages.json"
  });
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((message) => message.includes("same-origin UI boundary")));
});

test("downstream preflight verifies repo, revision, hash, temporal graph, empty pack composition and minimum pages", async () => {
  const evidence = await runDownstreamPreflight(VALID_ENV, fixtureFetch());
  assert.equal(evidence.status, "passed");
  assert.equal(evidence.page_count, 42);
  assert.equal(evidence.snapshot_hash, HASH);
  assert.equal(evidence.snapshot_source_commit, CONSUMER_HEAD);
  assert.equal(evidence.public_release_sha, PUBLIC_RELEASE_SHA);
  assert.equal(evidence.adapter_hash, ADAPTER_HASH);
  assert.equal(evidence.adapter_manifest, "wiki.adapter-manifest.json");
  assert.equal(evidence.adapter_manifest_schema_version, "wiki_downstream_adapter_manifest.v1");
  assert.equal(evidence.adapter_file_count, 1);
  assert.equal(evidence.snapshot_version, "wiki_web_snapshot.v2");
  assert.equal(evidence.temporal_event_count, 1);
  assert.equal(evidence.composition_sha256, EMPTY_COMPOSITION.composition_sha256);
  assert.deepEqual(evidence.active_packs, []);
  assert.ok(evidence.snapshot_capabilities.includes("temporal_graph"));
  assert.ok(evidence.snapshot_capabilities.includes("experience_packs"));
  assert.deepEqual(evidence.contract_errors, []);
  assert.equal(evaluateDownstreamPreflightRecord(evidence, VALID_ENV).ok, true);

  // These core-owned kinds are emitted only when a downstream has historical
  // action migrations, so the public demo alone cannot exercise them. Keep
  // the independent release validator aligned with the runtime/UI contract.
  for (const kind of ["action_state_canonicalized", "action_contract_updated"]) {
    const temporalGraph = temporalFixture({ events: [temporalEventFixture({ kind })] });
    await assert.doesNotReject(
      () => runDownstreamPreflight(VALID_ENV, fixtureFetch({
        manifest: manifestForPayloads(temporalGraph, EMPTY_COMPOSITION),
        temporalGraph
      }))
    );
  }
});

test("downstream preflight accepts one explicitly attested active pack and records it exactly", async () => {
  const slots = {
    ...EMPTY_SLOTS,
    views: [{ pack: "personal-finance", slot: "view.cashflow", contribution: "personal-finance.cashflow", mode: "append" }]
  };
  const composition = compositionFixture({
    packs: [{ id: "personal-finance", version: "0.1.0" }],
    slots
  });
  const env = {
    ...VALID_ENV,
    WIKI_COCKPIT_EXPECT_COMPOSITION_SHA256: composition.composition_sha256,
    WIKI_COCKPIT_EXPECT_ACTIVE_PACKS: '[{"id":"personal-finance","version":"0.1.0"}]'
  };
  const evidence = await runDownstreamPreflight(env, fixtureFetch({
    manifest: manifestForPayloads(TEMPORAL_GRAPH, composition),
    experiencePacks: composition
  }));
  assert.deepEqual(evidence.active_packs, [{ id: "personal-finance", version: "0.1.0" }]);
  assert.equal(evaluateDownstreamPreflightRecord(evidence, env).ok, true);
});

test("downstream preflight accepts a closed namespaced pack event with an explicit lane", async () => {
  const temporalGraph = temporalFixture({
    events: [temporalEventFixture({
      kind: "study-research.learning-captured",
      lane: "source"
    })]
  });
  const evidence = await runDownstreamPreflight(VALID_ENV, fixtureFetch({
    manifest: manifestForPayloads(temporalGraph, EMPTY_COMPOSITION),
    temporalGraph
  }));
  assert.equal(evidence.temporal_event_count, 1);
});

test("downstream preflight rejects missing capabilities and drifted temporal or composition versions", async () => {
  const manifest = validManifest({
    capabilities: ["experience_packs"],
    versions: {
      snapshot: "wiki_web_snapshot.v2",
      runtime_contract: "wiki_world_runtime.v8",
      temporal_graph: "wiki_temporal_graph.v0",
      temporal_event: "wiki_temporal_event.v0",
      experience_pack_composition: "wiki_experience_pack_composition.v0"
    }
  });
  const badTemporal = temporalFixture({
    schema_version: "wiki_temporal_graph.v0",
    event_schema_version: "wiki_temporal_event.v0",
    events: [{ event_id: "evt-1", schema_version: "wiki_temporal_event.v0" }]
  });
  await assert.rejects(
    () => runDownstreamPreflight(VALID_ENV, fixtureFetch({ manifest, temporalGraph: badTemporal })),
    /temporal graph manifest version.*temporal event manifest version.*experience pack composition manifest version.*snapshot capability temporal_graph.*payload schema_version/
  );
});

test("downstream preflight recomputes manifest integrity and the semantic composition hash", async () => {
  const tampered = {
    ...EMPTY_COMPOSITION,
    block_packages: ["unattested-after-hash"]
  };
  await assert.rejects(
    () => runDownstreamPreflight(VALID_ENV, fixtureFetch({
      manifest: manifestForPayloads(TEMPORAL_GRAPH, tampered),
      experiencePacks: tampered
    })),
    /composition_sha256 does not match/
  );

  const wrongIntegrity = validManifest({
    integrity: {
      ...validManifest().integrity,
      "experience_packs.json": { sha256: "0".repeat(64), bytes: 1 }
    }
  });
  await assert.rejects(
    () => runDownstreamPreflight(VALID_ENV, fixtureFetch({ manifest: wrongIntegrity })),
    /experience_packs.json does not match its manifest integrity/
  );

  const malformed = compositionFixture({ slots: { views: [], commands: [], operations: [], timelines: null } });
  const malformedEnv = {
    ...VALID_ENV,
    WIKI_COCKPIT_EXPECT_COMPOSITION_SHA256: malformed.composition_sha256
  };
  await assert.rejects(
    () => runDownstreamPreflight(malformedEnv, fixtureFetch({
      manifest: manifestForPayloads(TEMPORAL_GRAPH, malformed),
      experiencePacks: malformed
    })),
    /timelines slots must be an array/
  );
});

test("downstream preflight refuses an undeclared active pack and an empty temporal history", async () => {
  const composition = compositionFixture({ packs: [{ id: "personal-finance", version: "0.1.0" }] });
  await assert.rejects(
    () => runDownstreamPreflight(VALID_ENV, fixtureFetch({
      manifest: manifestForPayloads(TEMPORAL_GRAPH, composition),
      experiencePacks: composition
    })),
    /active packs do not exactly match/
  );

  const activeWithoutViewEnv = {
    ...VALID_ENV,
    WIKI_COCKPIT_EXPECT_COMPOSITION_SHA256: composition.composition_sha256,
    WIKI_COCKPIT_EXPECT_ACTIVE_PACKS: '[{"id":"personal-finance","version":"0.1.0"}]'
  };
  await assert.rejects(
    () => runDownstreamPreflight(activeWithoutViewEnv, fixtureFetch({
      manifest: manifestForPayloads(TEMPORAL_GRAPH, composition),
      experiencePacks: composition
    })),
    /has no composed view/
  );

  const emptyTemporal = temporalFixture({ event_count: 0, total_count: 0, returned_count: 0, events: [] });
  await assert.rejects(
    () => runDownstreamPreflight(VALID_ENV, fixtureFetch({
      manifest: manifestForPayloads(emptyTemporal, EMPTY_COMPOSITION),
      temporalGraph: emptyTemporal
    })),
    /complete, non-truncated, count-consistent/
  );
});

test("downstream preflight refuses a paginated or truncated static temporal payload", async () => {
  const truncatedTemporal = temporalFixture({
    event_count: 2,
    total_count: 2,
    returned_count: 1,
    truncated: true,
    next_cursor: "cursor-1",
    page: { offset: 0, remaining_count: 1 }
  });
  await assert.rejects(
    () => runDownstreamPreflight(VALID_ENV, fixtureFetch({
      manifest: manifestForPayloads(truncatedTemporal, EMPTY_COMPOSITION),
      temporalGraph: truncatedTemporal
    })),
    /complete, non-truncated, count-consistent/
  );
});

test("downstream temporal range preserves distinct microseconds inside one millisecond", async () => {
  const earlier = temporalEventFixture({
    event_id: "evt_snapshot_recorded_earlier",
    recorded_at: "2026-07-11T12:00:00.123456Z",
    anchor: { field: "recorded_at", value: "2026-07-11T12:00:00.123456Z", precision: "instant" }
  });
  const later = temporalEventFixture({
    event_id: "evt_snapshot_recorded_later",
    recorded_at: "2026-07-11T12:00:00.123457Z",
    anchor: { field: "recorded_at", value: "2026-07-11T12:00:00.123457Z", precision: "instant" }
  });
  const temporal = temporalFixture({ events: [later, earlier] });
  for (const range of [temporal.range, temporal.returned_range]) {
    range.from = earlier.recorded_at;
    range.to = later.recorded_at;
  }

  await assert.doesNotReject(
    () => runDownstreamPreflight(VALID_ENV, fixtureFetch({
      manifest: manifestForPayloads(temporal, EMPTY_COMPOSITION),
      temporalGraph: temporal
    }))
  );
});

test("downstream preflight rejects schema-valid-looking temporal contract mutations", async () => {
  const cases = [
    {
      label: "extra envelope key",
      mutate: (payload) => { payload.uncontracted = true; },
      error: /exact v1 envelope keys/
    },
    {
      label: "page fingerprint drift",
      mutate: (payload) => { payload.page.fingerprint = "f".repeat(64); },
      error: /fingerprint\/revision does not match canonical events/
    },
    {
      label: "range count drift",
      mutate: (payload) => { payload.range.dated_count = 0; },
      error: /range.*does not match the returned event set/
    },
    {
      label: "returned range basis drift",
      mutate: (payload) => { payload.returned_range.basis = "full_result"; },
      error: /returned_range\.basis must equal returned_page/
    },
    {
      label: "empty summary",
      mutate: (payload) => { payload.summary = {}; },
      error: /summary must expose the exact v1 keys/
    },
    {
      label: "summary kind drift",
      mutate: (payload) => { payload.summary.by_kind.snapshot_recorded = 2; },
      error: /summary\.by_kind does not match events/
    },
    {
      label: "malformed diagnostic",
      mutate: (payload) => {
        payload.diagnostics = [{ code: "temporal_adapter_rejected" }];
        payload.summary.diagnostic_count = 1;
      },
      error: /diagnostic.*exact temporal diagnostic v1 keys/
    },
    {
      label: "unknown event kind",
      mutate: (payload) => { payload.events[0].kind = "invented_event"; },
      error: /kind is unsupported/
    },
    {
      label: "unknown event lane",
      mutate: (payload) => { payload.events[0].lane = "invented"; },
      error: /lane is unsupported/
    },
    {
      label: "invalid typed ref",
      mutate: (payload) => { payload.events[0].subject_refs = ["not a typed ref"]; },
      error: /invalid or duplicate typed reference/
    },
    {
      label: "invalid calendar date",
      mutate: (payload) => {
        payload.events[0].recorded_at = "2026-02-30";
        payload.events[0].precision = { recorded_at: "day" };
        payload.events[0].anchor = { field: "recorded_at", value: "2026-02-30", precision: "day" };
      },
      error: /honest ISO temporal value/
    },
    {
      label: "precision mismatch",
      mutate: (payload) => { payload.events[0].precision.recorded_at = "day"; },
      error: /precision does not match its value/
    },
    {
      label: "anchor mismatch",
      mutate: (payload) => { payload.events[0].anchor.field = "occurred_at"; },
      error: /anchor does not match the canonical event clock/
    },
    {
      label: "extra event key",
      mutate: (payload) => { payload.events[0].invented = true; },
      error: /only the temporal event v1 keys/
    }
  ];
  for (const fixture of cases) {
    const temporalGraph = structuredClone(TEMPORAL_GRAPH);
    fixture.mutate(temporalGraph);
    await assert.rejects(
      () => runDownstreamPreflight(VALID_ENV, fixtureFetch({
        manifest: manifestForPayloads(temporalGraph, EMPTY_COMPOSITION),
        temporalGraph
      })),
      fixture.error,
      fixture.label
    );
  }
});

test("downstream preflight independently rejects noncanonical or conflicting pack composition", async () => {
  const pack = { id: "personal-finance", version: "0.1.0" };
  const validView = {
    pack: pack.id,
    slot: "view.analysis",
    contribution: "personal-finance.analysis",
    mode: "append"
  };
  const validSlots = { ...EMPTY_SLOTS, views: [validView] };
  const validPresentation = fixturePresentation([pack], validSlots);
  const cases = [
    {
      label: "prerelease version outside exact v1 semver",
      composition: compositionFixture({
        packs: [{ id: "personal-finance", version: "0.1.0-rc.1" }],
        slots: { ...EMPTY_SLOTS, views: [validView] }
      }),
      error: /invalid pack record/
    },
    {
      label: "duplicate packs",
      composition: compositionFixture({ packs: [pack, pack], slots: { ...EMPTY_SLOTS, views: [validView] } }),
      error: /packs must be unique and canonical/
    },
    {
      label: "missing required presentation locale",
      composition: compositionFixture({
        packs: [pack],
        slots: validSlots,
        presentation: {
          default_locale: "en",
          locales: { en: validPresentation.locales.en }
        }
      }),
      error: /locales must include canonical en and pt-BR/
    },
    {
      label: "missing contribution presentation label",
      composition: compositionFixture({
        packs: [pack],
        slots: validSlots,
        presentation: {
          default_locale: "en",
          locales: {
            en: { "personal-finance": "Personal finance" },
            "pt-BR": { "personal-finance": "Finanças pessoais" }
          }
        }
      }),
      error: /labels for en are incomplete/
    },
    {
      label: "unowned presentation identifier",
      composition: compositionFixture({
        packs: [pack],
        slots: validSlots,
        presentation: {
          default_locale: "en",
          locales: {
            en: { ...validPresentation.locales.en, "other-pack.label": "Other" },
            "pt-BR": { ...validPresentation.locales["pt-BR"], "other-pack.label": "Outro" }
          }
        }
      }),
      error: /invalid or unowned/
    },
    {
      label: "unknown pack reference",
      composition: compositionFixture({
        packs: [pack],
        slots: { ...EMPTY_SLOTS, views: [{ ...validView, pack: "ghost-pack", contribution: "ghost-pack.analysis" }] }
      }),
      error: /invalid or unnamespaced slot record/
    },
    {
      label: "unnamespaced contribution",
      composition: compositionFixture({
        packs: [pack],
        slots: { ...EMPTY_SLOTS, views: [{ ...validView, contribution: "other.analysis" }] }
      }),
      error: /invalid or unnamespaced slot record/
    },
    {
      label: "duplicate contribution",
      composition: compositionFixture({
        packs: [pack],
        slots: { ...EMPTY_SLOTS, views: [validView, { ...validView }] }
      }),
      error: /identities must be unique/
    },
    {
      label: "noncanonical rows",
      composition: compositionFixture({
        packs: [pack],
        slots: {
          ...EMPTY_SLOTS,
          views: [
            { ...validView, slot: "view.zeta", contribution: "personal-finance.zeta" },
            { ...validView, slot: "view.alpha", contribution: "personal-finance.alpha" }
          ]
        }
      }),
      error: /slots must be canonical/
    },
    {
      label: "exclusive collision",
      composition: compositionFixture({
        packs: [pack],
        slots: {
          ...EMPTY_SLOTS,
          views: [
            { ...validView, contribution: "personal-finance.alpha", mode: "exclusive" },
            { ...validView, contribution: "personal-finance.beta", mode: "append" }
          ]
        }
      }),
      error: /exclusive slot .* conflicts/
    },
    {
      label: "duplicate block package",
      composition: compositionFixture({
        packs: [pack],
        blockPackages: ["gamification", "gamification"],
        slots: { ...EMPTY_SLOTS, views: [validView] }
      }),
      error: /block_packages must be unique and canonical/
    }
  ];
  for (const fixture of cases) {
    const env = {
      ...VALID_ENV,
      WIKI_COCKPIT_EXPECT_COMPOSITION_SHA256: fixture.composition.composition_sha256,
      WIKI_COCKPIT_EXPECT_ACTIVE_PACKS: '[{"id":"personal-finance","version":"0.1.0"}]'
    };
    await assert.rejects(
      () => runDownstreamPreflight(env, fixtureFetch({
        manifest: manifestForPayloads(TEMPORAL_GRAPH, fixture.composition),
        experiencePacks: fixture.composition
      })),
      fixture.error,
      fixture.label
    );
  }
});

test("downstream preflight blocks when the served runtime has no adoption identity", async () => {
  await assert.rejects(
    () => runDownstreamPreflight(VALID_ENV, fixtureFetch({ runtimeConfig: { mode: "local_operator" } })),
    /adoption_identity_unavailable/
  );
});

test("downstream preflight refuses an adapter hash echoed only by config and environment", async () => {
  const selfAsserted = "f".repeat(64);
  const env = { ...VALID_ENV, WIKI_COCKPIT_EXPECT_ADAPTER_HASH: selfAsserted };
  await assert.rejects(
    () => runDownstreamPreflight(env, fixtureFetch({
      runtimeConfig: validRuntimeConfig({
        adoption: {
          public_release_sha: PUBLIC_RELEASE_SHA,
          adapter_hash: selfAsserted,
          adapter_manifest: "wiki.adapter-manifest.json"
        }
      })
    })),
    /adapter_manifest_invalid.*canonical file inventory and expectation/
  );
});

test("downstream preflight fails closed on an actual revision mismatch", async () => {
  await assert.rejects(
    () => runDownstreamPreflight(VALID_ENV, fixtureFetch({ manifest: validManifest({ snapshot_id: "different-revision" }) })),
    /snapshot revision/
  );
});

test("downstream preflight rejects dirty source identity, version drift and contract errors", async () => {
  const manifest = validManifest({
      source_commit: null,
      source_sha: `uncommitted:${HASH}`,
      versions: { snapshot: "wiki_web_snapshot.v1", runtime_contract: "wiki_world_runtime.v7" },
      contract_errors: ["torn snapshot"]
    });
  await assert.rejects(
    () => runDownstreamPreflight(VALID_ENV, fixtureFetch({
      manifest,
      health: validHealth({ server_version: "wiki_web_server.v5" })
    })),
    /source_commit.*missing\/dirty.*schema version.*runtime version.*server version.*contract_errors/
  );
});

test("downstream preflight times out and bounds response bytes", async () => {
  const hangingFetch = async (_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
  });
  await assert.rejects(
    () => runDownstreamPreflight(VALID_ENV, hangingFetch, { timeoutMs: 5 }),
    /timed out after 5ms/
  );

  await assert.rejects(
    () => runDownstreamPreflight(VALID_ENV, fixtureFetch(), { maxBytes: 16 }),
    /response limit/
  );
});

test("hashed downstream preflight record is revalidated against the current attestation", async () => {
  const evidence = await runDownstreamPreflight(VALID_ENV, fixtureFetch());
  const tampered = { ...evidence, snapshot_revision: "private-pilot-different" };
  const result = evaluateDownstreamPreflightRecord(tampered, VALID_ENV);
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((message) => message.includes("revision")));

  const compositionTamper = evaluateDownstreamPreflightRecord({
    ...evidence,
    composition_sha256: "0".repeat(64),
    active_packs: [{ id: "undeclared", version: "1.0.0" }],
    snapshot_capabilities: ["experience_packs"]
  }, VALID_ENV);
  assert.equal(compositionTamper.ok, false);
  for (const fragment of ["composition hash", "active packs", "snapshot capability temporal_graph"]) {
    assert.ok(compositionTamper.errors.some((message) => message.includes(fragment)), fragment);
  }

  const adapterTamper = evaluateDownstreamPreflightRecord({
    ...evidence,
    adapter_manifest: "data/derived/wiki/adapter.json",
    adapter_manifest_schema_version: "wiki_downstream_adapter_manifest.v0",
    adapter_file_count: 0
  }, VALID_ENV);
  assert.equal(adapterTamper.ok, false);
  for (const fragment of ["manifest path", "manifest schema", "file count", "cannot be reverified"]) {
    assert.ok(adapterTamper.errors.some((message) => message.includes(fragment)), fragment);
  }

  const securityTamper = evaluateDownstreamPreflightRecord({
    ...evidence,
    operator_security: { ...evidence.operator_security, nonce_present: false }
  }, VALID_ENV);
  assert.equal(securityTamper.ok, false);
  assert.ok(
    securityTamper.errors.some((message) => message.includes("security nonce"))
  );
});

function report({
  file = "e2e/navigation.spec.ts",
  projectName = "chromium-desktop",
  status = "expected",
  results = [{ status: "passed", retry: 0 }],
  config = {}
} = {}) {
  const stats = {
    expected: status === "expected" && results.at(-1)?.status === "passed" && results.length === 1 ? 1 : 0,
    unexpected: status === "unexpected" ? 1 : 0,
    skipped: status === "skipped" ? 1 : 0,
    flaky: status === "flaky" ? 1 : 0
  };
  return {
    config: {
      configFile: "/repo/apps/wiki-cockpit/playwright.config.ts",
      rootDir: "/repo/apps/wiki-cockpit/e2e",
      forbidOnly: true,
      fullyParallel: false,
      workers: 1,
      version: "1.61.1",
      projects: [{ name: projectName, retries: 0, repeatEach: 1 }],
      ...config
    },
    suites: [{ title: file.split("/").at(-1), specs: [{ file, title: "test title", tests: [{ projectName, status, expectedStatus: "passed", results }] }] }],
    errors: [],
    stats
  };
}

test("public release matrix accepts only first-attempt public passes", () => {
  const result = evaluateRequiredPlaywrightReport(report(), "public_required");
  assert.equal(result.ok, true);
  assert.deepEqual(result.summary, {
    passed: 1,
    failed: 0,
    skipped: 0,
    flaky: 0,
    retries: 0,
    total: 1,
    files: ["e2e/navigation.spec.ts"],
    projects: ["chromium-desktop"]
  });
});

test("required matrix rejects skips, retries and scope leakage", () => {
  const skipped = evaluateRequiredPlaywrightReport(
    report({ status: "skipped", results: [{ status: "skipped", retry: 0 }] }),
    "public_required"
  );
  assert.equal(skipped.ok, false);
  assert.ok(skipped.errors.some((message) => message.includes("skipped")));

  const retried = evaluateRequiredPlaywrightReport(
    report({ status: "flaky", results: [{ status: "failed", retry: 0 }, { status: "passed", retry: 1 }] }),
    "public_required"
  );
  assert.equal(retried.ok, false);
  assert.ok(retried.errors.some((message) => message.includes("retry")));

  const leaked = evaluateRequiredPlaywrightReport(
    report({ file: "e2e/downstream/operator-origin.spec.ts" }),
    "public_required"
  );
  assert.equal(leaked.ok, false);
  assert.ok(leaked.errors.some((message) => message.includes("downstream spec")));
});

test("downstream required matrix refuses public specs", () => {
  const result = evaluateRequiredPlaywrightReport(report(), "downstream_required");
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((message) => message.includes("public spec")));
});

test("required matrix contract rejects partial collection and missing projects", () => {
  const raw = report();
  const cells = matrixCellsFromReport(raw, "public_required");
  const contract = {
    schema_version: "wiki_playwright_release_matrix.v1",
    contract_version: 2,
    playwright_version: "1.61.1",
    public_required: {
      config_file: "playwright.config.ts",
      test_dir: "e2e",
      expected_tests: 2,
      required_specs: ["e2e/navigation.spec.ts", "e2e/visual.spec.ts"],
      required_projects: ["chromium-desktop", "webkit-mobile"],
      cells
    }
  };
  const result = evaluateRequiredPlaywrightReport(raw, "public_required", contract);
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((message) => message.includes("expected_tests")));
  assert.ok(result.errors.some((message) => message.includes("exact specs")));
  assert.ok(result.errors.some((message) => message.includes("configured projects")));
});

test("contract generation refuses unsafe configs and scope-crossing cells", () => {
  const downstream = report({
    file: "operator-origin.spec.ts",
    projectName: "chromium-downstream-required",
    config: {
      configFile: "/repo/apps/wiki-cockpit/playwright.downstream.config.ts",
      rootDir: "/repo/apps/wiki-cockpit/e2e/downstream"
    }
  });
  const valid = buildReleaseMatrixContract(report(), downstream);
  assert.equal(valid.public_required.expected_tests, 1);
  assert.equal(valid.downstream_required.expected_tests, 1);

  const unsafe = report({
    config: { projects: [{ name: "chromium-desktop", retries: 1, repeatEach: 1 }] }
  });
  assert.throws(() => buildReleaseMatrixContract(unsafe, downstream), /unsafe or unexpected/);
  assert.throws(
    () => buildReleaseMatrixContract(
      report({ file: "e2e/downstream/leaked.spec.ts" }),
      downstream
    ),
    /crosses the public\/downstream boundary/
  );
});

test("release configurations pin zero retries and keep downstream specs out of public collection", () => {
  const publicConfig = fs.readFileSync(new URL("../playwright.config.ts", import.meta.url), "utf8");
  const downstreamConfig = fs.readFileSync(new URL("../playwright.downstream.config.ts", import.meta.url), "utf8");
  const downstreamSpec = fs.readFileSync(new URL("../e2e/downstream/operator-origin.spec.ts", import.meta.url), "utf8");
  const snapshotOriginSpec = fs.readFileSync(new URL("../e2e/snapshot-origin.spec.ts", import.meta.url), "utf8");
  const genesisJourneySpec = fs.readFileSync(new URL("../e2e/keyboard-genesis-journey.spec.ts", import.meta.url), "utf8");
  const checker = fs.readFileSync(new URL("./check-playwright-release.mjs", import.meta.url), "utf8");
  const packageJson = JSON.parse(fs.readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  assert.match(publicConfig, /testIgnore:\s*\[downstreamSpecs, matrixOnlySpecs\]/);
  assert.match(publicConfig, /forbidOnly:\s*true/);
  assert.match(publicConfig, /retries:\s*0/);
  assert.doesNotMatch(publicConfig, /process\.env\.CI\s*\?\s*1/);
  assert.match(publicConfig, /releaseRun \? false : !process\.env\.CI/);
  assert.match(publicConfig, /WIKI_RELEASE_PORT/);
  assert.match(publicConfig, /--strictPort/);
  assert.match(publicConfig, /\.\/test-results\/playwright-dev-artifacts/);
  assert.doesNotMatch(publicConfig, /\|\|\s*"\.\/test-results"/);
  const defaultOutput = publicConfig.match(/outputDir:\s*process\.env\.WIKI_PLAYWRIGHT_OUTPUT_DIR\s*\|\|\s*"([^"]+)"/);
  assert.ok(defaultOutput);
  const disposableOutputRoot = path.resolve(APP_ROOT, defaultOutput[1]);
  const immutableReleaseRoot = path.resolve(REPO_ROOT, TEST_RESULTS_ROOT);
  assert.equal(
    immutableReleaseRoot.startsWith(`${disposableOutputRoot}${path.sep}`),
    false,
    "an ad-hoc Playwright cleanup must not contain immutable release evidence"
  );
  assert.doesNotMatch(snapshotOriginSpec, /http:\/\/127\.0\.0\.1:4173/);
  assert.doesNotMatch(genesisJourneySpec, /http:\/\/127\.0\.0\.1:4173/);
  assert.match(downstreamConfig, /testDir:\s*"\.\/e2e\/downstream"/);
  assert.match(downstreamConfig, /forbidOnly:\s*true/);
  assert.match(downstreamConfig, /retries:\s*0/);
  assert.doesNotMatch(downstreamSpec, /test\.skip/);
  assert.equal(
    packageJson.scripts["test:e2e:release"],
    "sh scripts/run-playwright-release.sh --scope public_required"
  );
  assert.equal(
    packageJson.scripts["test:e2e:operator"],
    "node scripts/run-playwright-release.mjs --scope downstream_required"
  );
  assert.match(checker, /playwright_public_release_v1/);
  assert.match(checker, /playwright_downstream_release_v1/);
  assert.doesNotMatch(checker, /\bcommand:\s/);
  for (const supportId of [
    "playwright-config",
    "runtime-performance-spec",
    "webgl-renderer-attestation",
    "release-matrix-checker",
    "release-matrix-library",
    "operator-security-contract",
    "release-matrix-contract",
    "release-build-manifest",
    "release-build-policy",
    "public-release-runtime-config-policy",
    "public-release-runtime-config",
    "release-build-runner",
    "release-build-launcher",
    "cockpit-vite-config",
    "release-path-safety",
    "release-runner",
    "upgrade-gate-evidence-adapter",
    "release-runner-launcher",
    "downstream-preflight-runner",
    "git-subject-helper"
  ]) {
    assert.ok(checker.includes(`"${supportId}"`));
  }
});

test("performance release evidence binds one hardware WebGL renderer attestation", () => {
  const publicConfig = fs.readFileSync(new URL("../playwright.config.ts", import.meta.url), "utf8");
  const performanceSpec = fs.readFileSync(new URL("../e2e/runtime-performance.spec.ts", import.meta.url), "utf8");
  const attestation = fs.readFileSync(new URL("../e2e/webgl-renderer-attestation.ts", import.meta.url), "utf8");
  const checker = fs.readFileSync(new URL("./check-playwright-release.mjs", import.meta.url), "utf8");
  const performanceStart = publicConfig.indexOf('name: "chromium-performance"');
  const nextProject = publicConfig.indexOf('name: "chromium-desktop"', performanceStart);
  assert.ok(performanceStart >= 0 && nextProject > performanceStart);
  const performanceProject = publicConfig.slice(performanceStart, nextProject);
  assert.match(performanceProject, /launchOptions:\s*\{\s*args:\s*\["--enable-gpu"\]\s*\}/);
  assert.equal(publicConfig.match(/--enable-gpu/g)?.length, 1);
  assert.doesNotMatch(publicConfig.slice(nextProject), /--enable-gpu/);

  assert.match(performanceSpec, /captureWebglRendererAttestation/);
  assert.match(performanceSpec, /assertHardwareWebglRendererAttestation/);
  assert.match(performanceSpec, /webgl-renderer-attestation\.json/);
  assert.match(attestation, /wiki_webgl_renderer_attestation\.v1/);
  assert.match(attestation, /WEBGL_debug_renderer_info/);
  assert.match(attestation, /swiftshader\|llvmpipe/);
  assert.match(attestation, /WebGL renderer attestation blocked/);
  assert.ok(checker.includes('["runtime-performance-spec",'));
  assert.ok(checker.includes('["webgl-renderer-attestation",'));
});

test("WebGL renderer attestation rejects missing, software and contradictory identities", async () => {
  const {
    assertHardwareWebglRendererAttestation,
    webglRendererAttestationBlocker
  } = await import("../e2e/webgl-renderer-attestation.ts");
  const hardware = {
    schema_version: "wiki_webgl_renderer_attestation.v1",
    requested_gpu: true,
    classification: "hardware",
    blocker: null,
    context: {
      drawing_buffer_width: 1280,
      drawing_buffer_height: 900,
      lost: false,
      version: "WebGL 2.0",
      shading_language_version: "WebGL GLSL ES 3.00"
    },
    renderer: {
      masked_vendor: "WebKit",
      masked_renderer: "WebKit WebGL",
      unmasked_vendor: "Example GPU Vendor",
      unmasked_renderer: "ANGLE (Example Hardware GPU)",
      debug_renderer_info: true
    }
  };
  assert.equal(webglRendererAttestationBlocker(hardware), null);
  assert.doesNotThrow(() => assertHardwareWebglRendererAttestation(hardware));

  const software = {
    ...structuredClone(hardware),
    classification: "software",
    blocker: "webgl_software_renderer:swiftshader",
    renderer: {
      ...hardware.renderer,
      unmasked_renderer: "ANGLE (Google SwiftShader)"
    }
  };
  assert.throws(
    () => assertHardwareWebglRendererAttestation(software),
    /blocked: webgl_software_renderer:swiftshader/
  );
  assert.throws(
    () => assertHardwareWebglRendererAttestation({
      ...structuredClone(hardware),
      classification: "unknown",
      blocker: "webgl_debug_renderer_info_unavailable",
      renderer: { ...hardware.renderer, debug_renderer_info: false }
    }),
    /blocked: webgl_debug_renderer_info_unavailable/
  );
  assert.throws(
    () => assertHardwareWebglRendererAttestation({
      ...structuredClone(hardware),
      classification: "unknown",
      blocker: "webgl_context_identity_missing",
      context: { ...hardware.context, version: "" }
    }),
    /blocked: webgl_context_identity_missing/
  );
  assert.throws(
    () => assertHardwareWebglRendererAttestation({
      ...software,
      classification: "hardware",
      blocker: null
    }),
    /fields contradict/
  );
});

test("release Playwright refuses a stale sentinel server instead of reusing it", async () => {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    await assert.rejects(
      () => assertReleasePortAvailable(address.port),
      /already occupied; stale server refused/
    );
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test("release CLIs reject README outputs and immutable clear requests", () => {
  const readmePath = path.join(REPO_ROOT, "README.md");
  const before = fs.readFileSync(readmePath);
  const nonce = crypto.randomUUID();
  const validOutput = `${RELEASE_DERIVED_ROOT}/output-safety-${nonce}.json`;

  const outputAttempt = runNodeScript("capture-git-subject.mjs", [
    "--out",
    "README.md"
  ]);
  assert.notEqual(outputAttempt.status, 0);
  assert.match(outputAttempt.stderr, /outside the owned release-evidence roots/);

  const clearAttempt = runNodeScript("capture-git-subject.mjs", [
    "--out",
    validOutput,
    "--clear",
    "README.md"
  ]);
  assert.notEqual(clearAttempt.status, 0);
  assert.match(clearAttempt.stderr, /--clear is unsupported/);
  assert.equal(fs.existsSync(path.join(REPO_ROOT, validOutput)), false);

  const checkerAttempt = runNodeScript("check-playwright-release.mjs", [
    "--scope",
    "public_required",
    "--report",
    `${TEST_RESULTS_ROOT}/missing-${nonce}.json`,
    "--subject-before",
    `${RELEASE_DERIVED_ROOT}/missing-${nonce}.json`,
    "--out",
    "README.md",
    ...checkerProvenance(nonce)
  ]);
  assert.notEqual(checkerAttempt.status, 0);
  assert.match(checkerAttempt.stderr, /outside the owned release-evidence roots/);
  assert.deepEqual(fs.readFileSync(readmePath), before);
});

test("release evidence writes are create-once and never clobber", () => {
  const nonce = crypto.randomUUID();
  const plain = `${RELEASE_DERIVED_ROOT}/create-once-${nonce}.json`;
  const atomic = `${RELEASE_DERIVED_ROOT}/create-once-atomic-${nonce}.json`;
  const plainPath = path.join(REPO_ROOT, plain);
  const atomicPath = path.join(REPO_ROOT, atomic);
  try {
    writeOwnedReleaseFile(REPO_ROOT, plain, "first\n");
    assert.throws(
      () => writeOwnedReleaseFile(REPO_ROOT, plain, "clobber\n"),
      /EEXIST|exist/i
    );
    assert.equal(fs.readFileSync(plainPath, "utf8"), "first\n");

    writeOwnedReleaseFileAtomic(REPO_ROOT, atomic, "first atomic\n");
    assert.throws(
      () => writeOwnedReleaseFileAtomic(REPO_ROOT, atomic, "clobber atomic\n"),
      /EEXIST|exist/i
    );
    assert.equal(fs.readFileSync(atomicPath, "utf8"), "first atomic\n");
  } finally {
    fs.rmSync(plainPath, { force: true });
    fs.rmSync(atomicPath, { force: true });
  }
});

test("release checker constrains every caller-controlled input to its expected root", () => {
  const nonce = crypto.randomUUID();
  const runRoot = `${TEST_RESULTS_ROOT}/fixture-${nonce}`;
  const output = `${runRoot}/gate.json`;
  const report = `${runRoot}/report.json`;
  const subject = `${runRoot}/subject.json`;

  const wrongReport = runNodeScript("check-playwright-release.mjs", [
    "--scope",
    "public_required",
    "--report",
    `${RELEASE_DERIVED_ROOT}/wrong-report-${nonce}.json`,
    "--subject-before",
    subject,
    "--out",
    output,
    ...checkerProvenance(nonce)
  ]);
  assert.notEqual(wrongReport.status, 0);
  assert.match(wrongReport.stderr, /Playwright report is outside/);

  const wrongSubject = runNodeScript("check-playwright-release.mjs", [
    "--scope",
    "public_required",
    "--report",
    report,
    "--subject-before",
    `${RELEASE_DERIVED_ROOT}/wrong-subject-${nonce}.json`,
    "--out",
    output,
    ...checkerProvenance(nonce)
  ]);
  assert.notEqual(wrongSubject.status, 0);
  assert.match(wrongSubject.stderr, /pre-run Git subject is outside/);

  const wrongPreflight = runNodeScript("check-playwright-release.mjs", [
    "--scope",
    "downstream_required",
    "--report",
    report,
    "--preflight",
    `${RELEASE_DERIVED_ROOT}/wrong-preflight-${nonce}.json`,
    "--subject-before",
    subject,
    "--out",
    output,
    ...checkerProvenance(nonce)
  ]);
  assert.notEqual(wrongPreflight.status, 0);
  assert.match(wrongPreflight.stderr, /downstream preflight is outside/);
  assert.equal(fs.existsSync(path.join(REPO_ROOT, output)), false);
});

test("release evidence paths reject traversal, absolute paths and backslashes", () => {
  for (const unsafe of [
    `${TEST_RESULTS_ROOT}/../README.md`,
    path.join(REPO_ROOT, TEST_RESULTS_ROOT, "absolute.json"),
    "apps\\wiki-cockpit\\test-results\\windows.json"
  ]) {
    assert.throws(
      () => resolveOwnedReleaseFile(REPO_ROOT, unsafe),
      /canonical repo-relative POSIX path/
    );
  }
});

test("release evidence rejects symlink targets without touching their referent", () => {
  const nonce = crypto.randomUUID();
  const readmePath = path.join(REPO_ROOT, "README.md");
  const before = fs.readFileSync(readmePath);
  const targetRelative = `${TEST_RESULTS_ROOT}/target-link-${nonce}.json`;
  const targetPath = path.join(REPO_ROOT, targetRelative);
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  fs.symlinkSync(readmePath, targetPath);

  try {
    assert.throws(
      () => resolveOwnedReleaseFile(REPO_ROOT, targetRelative),
      /target must not be a symlink/
    );
    const attempt = runNodeScript("check-playwright-release.mjs", [
      "--scope",
      "public_required",
      "--report",
      `${TEST_RESULTS_ROOT}/missing-${nonce}.json`,
      "--subject-before",
      `${RELEASE_DERIVED_ROOT}/missing-${nonce}.json`,
      "--out",
      targetRelative,
      ...checkerProvenance(nonce)
    ]);
    assert.notEqual(attempt.status, 0);
    assert.match(attempt.stderr, /target must not be a symlink/);
    assert.equal(fs.lstatSync(targetPath).isSymbolicLink(), true);
    assert.deepEqual(fs.readFileSync(readmePath), before);
  } finally {
    fs.unlinkSync(targetPath);
  }
});

test("release evidence rejects hard-linked targets without truncating their referent", () => {
  const nonce = crypto.randomUUID();
  const readmePath = path.join(REPO_ROOT, "README.md");
  const before = fs.readFileSync(readmePath);
  const targetRelative = `${TEST_RESULTS_ROOT}/hard-link-${nonce}.json`;
  const targetPath = path.join(REPO_ROOT, targetRelative);
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  fs.linkSync(readmePath, targetPath);

  try {
    assert.throws(
      () => resolveOwnedReleaseFile(REPO_ROOT, targetRelative),
      /target must not be hard-linked/
    );
    const attempt = runNodeScript("check-playwright-release.mjs", [
      "--scope",
      "public_required",
      "--report",
      `${TEST_RESULTS_ROOT}/missing-${nonce}.json`,
      "--subject-before",
      `${RELEASE_DERIVED_ROOT}/missing-${nonce}.json`,
      "--out",
      targetRelative,
      ...checkerProvenance(nonce)
    ]);
    assert.notEqual(attempt.status, 0);
    assert.match(attempt.stderr, /target must not be hard-linked/);
    assert.deepEqual(fs.readFileSync(readmePath), before);
  } finally {
    fs.unlinkSync(targetPath);
  }
});

test("release evidence rejects symlinks in its ancestor chain", () => {
  const nonce = crypto.randomUUID();
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), "wiki-release-safety-"));
  const ancestorRelative = `${TEST_RESULTS_ROOT}/ancestor-link-${nonce}`;
  const ancestorPath = path.join(REPO_ROOT, ancestorRelative);
  fs.mkdirSync(path.dirname(ancestorPath), { recursive: true });
  fs.symlinkSync(outside, ancestorPath, "dir");

  try {
    const nestedRelative = `${ancestorRelative}/gate.json`;
    assert.throws(
      () => resolveOwnedReleaseFile(REPO_ROOT, nestedRelative),
      /must not traverse a symlink/
    );
    const attempt = runNodeScript("check-playwright-release.mjs", [
      "--scope",
      "public_required",
      "--report",
      `${TEST_RESULTS_ROOT}/missing-${nonce}.json`,
      "--subject-before",
      `${RELEASE_DERIVED_ROOT}/missing-${nonce}.json`,
      "--out",
      nestedRelative,
      ...checkerProvenance(nonce)
    ]);
    assert.notEqual(attempt.status, 0);
    assert.match(attempt.stderr, /must not traverse a symlink/);
    assert.equal(fs.readdirSync(outside).length, 0);
  } finally {
    fs.unlinkSync(ancestorPath);
    fs.rmSync(outside, { recursive: true, force: true });
  }
});

test("release evidence never targets a tracked file even below an ignored root", () => {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "wiki-release-git-"));
  const trackedRelative = `${TEST_RESULTS_ROOT}/tracked.json`;
  const trackedPath = path.join(fixture, trackedRelative);
  try {
    execFileSync("git", ["init", "-q"], { cwd: fixture });
    fs.mkdirSync(path.dirname(trackedPath), { recursive: true });
    fs.writeFileSync(
      path.join(fixture, ".gitignore"),
      `${TEST_RESULTS_ROOT}/\n${RELEASE_DERIVED_ROOT}/\n`
    );
    fs.writeFileSync(trackedPath, "tracked\n");
    execFileSync("git", ["add", "-f", "--", trackedRelative], { cwd: fixture });
    assert.throws(
      () => resolveOwnedReleaseFile(fixture, trackedRelative),
      /must never target a tracked file/
    );
    assert.equal(fs.readFileSync(trackedPath, "utf8"), "tracked\n");
  } finally {
    fs.rmSync(fixture, { recursive: true, force: true });
  }
});

test("release runner writes a unique atomic blocked terminal record on pre-checker Playwright failure", () => {
  const nonce = crypto.randomUUID();
  const staleRelative = `${TEST_RESULTS_ROOT}/stale-${nonce}.gate.json`;
  const stalePath = path.join(REPO_ROOT, staleRelative);
  fs.mkdirSync(path.dirname(stalePath), { recursive: true });
  fs.writeFileSync(stalePath, '{"status":"passed","stale":true}\n');
  try {
    const attempt = runNodeScript(
      "run-playwright-release.mjs",
      ["--scope", "public_required"],
      { WIKI_RELEASE_TEST_FAIL_STAGE: "playwright" }
    );
    assert.notEqual(attempt.status, 0);
    const match = attempt.stdout.match(/release run result: (.+) \(blocked\)/);
    assert.ok(match, attempt.stdout || attempt.stderr);
    const resultRelative = match[1];
    const resultPath = path.join(REPO_ROOT, ...resultRelative.split("/"));
    const result = JSON.parse(fs.readFileSync(resultPath, "utf8"));
    assert.equal(result.schema_version, "wiki_playwright_release_run.v1");
    assert.equal(result.status, "blocked");
    assert.equal(result.failure_stage, "playwright");
    assert.equal(result.exit_code, 97);
    assert.equal(result.paths.gate_result, null);
    assert.deepEqual(result.subject_before, result.subject_after);
    assert.equal(fs.existsSync(path.join(path.dirname(resultPath), "gate-result.json")), false);
    assert.deepEqual(
      fs.readFileSync(stalePath, "utf8"),
      '{"status":"passed","stale":true}\n'
    );
    assert.equal(
      fs.readdirSync(path.dirname(resultPath)).some((name) => name.includes(".tmp-")),
      false
    );
    fs.rmSync(path.dirname(resultPath), { recursive: true, force: true });
  } finally {
    fs.rmSync(stalePath, { force: true });
  }
});

test("public release runner fails before matrix/build when host build inputs are unsafe", () => {
  const attempt = runNodeScript(
    "run-playwright-release.mjs",
    ["--scope", "public_required"],
    { VITE_WIKI_REPO_LABEL: "must-not-enter-dist" }
  );
  assert.notEqual(attempt.status, 0);
  const match = attempt.stdout.match(/release run result: (.+) \(blocked\)/);
  assert.ok(match, attempt.stdout || attempt.stderr);
  const resultPath = path.join(REPO_ROOT, ...match[1].split("/"));
  try {
    const result = JSON.parse(fs.readFileSync(resultPath, "utf8"));
    assert.equal(result.status, "blocked");
    assert.equal(result.failure_stage, "build_environment");
    assert.equal(result.paths.build_manifest, match[1].replace(/run-result\.json$/, "release-build-manifest.json"));
    assert.equal(fs.existsSync(path.join(REPO_ROOT, result.paths.build_manifest)), false);
  } finally {
    fs.rmSync(path.dirname(resultPath), { recursive: true, force: true });
  }
});

test("raw report rejects contradictory stats and unsafe runner configuration", () => {
  const contradictory = report({
    config: {
      forbidOnly: false,
      workers: 4,
      projects: [{ name: "chromium-desktop", retries: 9, repeatEach: 2 }]
    }
  });
  contradictory.stats = { expected: 0, unexpected: 1, skipped: 0, flaky: 0 };
  const result = evaluateRequiredPlaywrightReport(contradictory, "public_required");
  assert.equal(result.ok, false);
  for (const fragment of ["stats.expected", "stats.unexpected", "forbidOnly", "worker", "retries", "repeatEach"]) {
    assert.ok(result.errors.some((message) => message.includes(fragment)), fragment);
  }
});

test("real playwright --list collection exactly matches the versioned cell contract", () => {
  const contract = JSON.parse(fs.readFileSync(new URL("./release-matrix-contract.json", import.meta.url), "utf8"));
  const current = collectCurrentReleaseMatrix();
  assert.deepEqual(current, contract);
  assert.equal(current.public_required.expected_tests, 102);
  assert.equal(current.downstream_required.expected_tests, 2);
  assert.equal(
    current.public_required.cells.some((cell) => cell.file.includes("/downstream/")),
    false
  );
  assert.equal(
    current.downstream_required.cells.every((cell) => cell.file.includes("/downstream/")),
    true
  );
});
