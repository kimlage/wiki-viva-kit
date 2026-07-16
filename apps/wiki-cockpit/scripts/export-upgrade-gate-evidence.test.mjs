import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import nodeTest from "node:test";
import zlib from "node:zlib";
import { chromium } from "@playwright/test";
import {
  UPGRADE_GATE_EVIDENCE_PROFILES,
  captureProfile,
  resolveGateArtifactDirectory,
  sanitizeObservedRoute,
  validateEvidenceBindings,
  validateProfileObservation,
  writeEvidenceBundle
} from "./export-upgrade-gate-evidence.mjs";

// RETIRED_RELEASE_MACHINE: upgrade evidence/capsule certification is historical.
// Keep the tests as executable documentation without running them in normal CI.
const test = nodeTest.skip;

function pngChunk(type, payload) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(payload.length);
  const crc = Buffer.alloc(4);
  // The evidence adapter verifies the PNG envelope/dimensions; Playwright owns
  // production encoding. CRC is still deterministic for the public fixture.
  const crc32 = (() => {
    let value = 0xffffffff;
    for (const byte of Buffer.concat([type, payload])) {
      value ^= byte;
      for (let index = 0; index < 8; index += 1) {
        value = (value >>> 1) ^ (0xedb88320 & -(value & 1));
      }
    }
    return (value ^ 0xffffffff) >>> 0;
  })();
  crc.writeUInt32BE(crc32);
  return Buffer.concat([length, type, payload, crc]);
}

function png(width, height) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header.set([8, 2, 0, 0, 0], 8);
  const row = Buffer.alloc(1 + width * 3);
  const pixels = Buffer.concat(Array.from({ length: height }, () => row));
  return Buffer.concat([
    Buffer.from("89504e470d0a1a0a", "hex"),
    pngChunk(Buffer.from("IHDR"), header),
    pngChunk(Buffer.from("IDAT"), zlib.deflateSync(pixels)),
    pngChunk(Buffer.from("IEND"), Buffer.alloc(0))
  ]);
}

function syntheticCanaryHtml({ view, runtimeMode, flipAfterMember = false }) {
  return `<!doctype html>
<html><body>
  <div class="topBar">synthetic-consumer</div>
  <main class="worldWorkspace" data-world-view="${view}" data-runtime-mode="${runtimeMode}" data-world-center="root">
    <section class="sceneShell">
      <canvas width="32" height="24"></canvas>
      <button data-world-target-kind="group">Group</button>
      <div data-world-group-summary hidden>
        <button data-world-member-id="member">Member</button>
      </div>
    </section>
  </main>
  <script>
    const workspace = document.querySelector('.worldWorkspace');
    const summary = document.querySelector('[data-world-group-summary]');
    document.querySelector('[data-world-target-kind="group"]').addEventListener('click', () => {
      summary.hidden = false;
    });
    document.querySelector('[data-world-member-id]').addEventListener('click', () => {
      workspace.dataset.worldCenter = 'member';
      if (${JSON.stringify(flipAfterMember)}) workspace.dataset.runtimeMode = 'compat';
    });
  </script>
</body></html>`;
}

async function runSyntheticProfileCapture(spec, options) {
  const html = syntheticCanaryHtml(options);
  const server = http.createServer((_request, response) => {
    response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    response.end(html);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  const baseUrl = `http://127.0.0.1:${address.port}`;
  const browser = await chromium.launch({ headless: true });
  try {
    return await captureProfile(
      browser,
      spec,
      { baseUrl, expectedRepo: "synthetic-consumer" },
      { requestCount: 0, networkErrorCount: 0, consoleErrorCount: 0, consoleWarningCount: 0 }
    );
  } finally {
    await browser.close();
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
}

function subject(sha = "a".repeat(40)) {
  return {
    source_sha: sha,
    tree_hash: "b".repeat(40),
    dirty: false,
    dirty_entry_count: 0,
    worktree_fingerprint_version: "wiki_git_subject.v2",
    worktree_fingerprint: "c".repeat(64),
    staged_patch_sha256: "d".repeat(64),
    unstaged_patch_sha256: "e".repeat(64),
    untracked_state_sha256: "f".repeat(64),
    untracked_entry_count: 0,
    submodule_state_sha256: "1".repeat(64)
  };
}

function gateResult(currentSubject, startedAt, runId = "downstream-current-run") {
  const { source_sha, ...fields } = currentSubject;
  return {
    schema_version: "wiki_test_gate_result.v1",
    scope: "downstream_required",
    command_id: "playwright_downstream_release_v1",
    run_id: runId,
    started_at: startedAt,
    finished_at: new Date(Date.parse(startedAt) + 1_000).toISOString(),
    status: "passed",
    passed: 2,
    failed: 0,
    skipped: 0,
    flaky: 0,
    retries: 0,
    subject_sha: source_sha,
    ...fields
  };
}

test("current-run binding rejects stale, fabricated and mismatched subjects", () => {
  const startedAt = new Date().toISOString();
  const current = subject();
  const gate = gateResult(current, startedAt);
  assert.deepEqual(
    validateEvidenceBindings({
      runId: gate.run_id,
      startedAt,
      gateResult: gate,
      subjectBefore: current,
      currentSubject: current,
      expectedConsumerHead: current.source_sha
    }),
    { source_sha: current.source_sha, started_at: startedAt }
  );
  assert.throws(
    () => validateEvidenceBindings({
      runId: gate.run_id,
      startedAt,
      gateResult: { ...gate, subject_sha: "9".repeat(40) },
      subjectBefore: current,
      currentSubject: current,
      expectedConsumerHead: current.source_sha
    }),
    /subjects differ/
  );
  const stale = new Date(Date.now() - 25 * 60 * 60_000).toISOString();
  assert.throws(
    () => validateEvidenceBindings({
      runId: gate.run_id,
      startedAt: stale,
      gateResult: gateResult(current, stale),
      subjectBefore: current,
      currentSubject: current,
      expectedConsumerHead: current.source_sha
    }),
    /stale or future-dated/
  );
  assert.throws(
    () => validateEvidenceBindings({
      runId: gate.run_id,
      startedAt,
      gateResult: { ...gate, status: "passed", skipped: 1 },
      subjectBefore: current,
      currentSubject: current,
      expectedConsumerHead: current.source_sha
    }),
    /first-attempt downstream pass/
  );
});

test("runner-owned gate artifact directory rejects aliases and preseeded evidence", () => {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "wiki-upgrade-artifacts-"));
  fs.mkdirSync(path.join(fixture, "run"));
  const runRoot = fs.realpathSync(path.join(fixture, "run"));
  const artifactDir = path.join(runRoot, "gate-artifacts", "real_canary");
  fs.mkdirSync(artifactDir, { recursive: true });
  const env = {
    WIKI_UPGRADE_RUN_DIR: runRoot,
    WIKI_UPGRADE_GATE_ID: "real_canary",
    WIKI_UPGRADE_GATE_ARTIFACT_DIR: artifactDir
  };
  try {
    assert.deepEqual(resolveGateArtifactDirectory(env), {
      artifactDir,
      gateId: "real_canary",
      runRoot
    });
    fs.writeFileSync(path.join(artifactDir, "manual.json"), "{}\n");
    assert.throws(() => resolveGateArtifactDirectory(env), /must be empty/);
    fs.unlinkSync(path.join(artifactDir, "manual.json"));
    assert.throws(
      () => resolveGateArtifactDirectory({
        ...env,
        WIKI_UPGRADE_GATE_ARTIFACT_DIR: path.join(runRoot, "gate-artifacts", "other")
      }),
      /ENOENT|does not belong/
    );
  } finally {
    fs.rmSync(fixture, { recursive: true, force: true });
  }
});

test("route projection removes consumer identity and rejects secret or private namespaces", () => {
  assert.equal(
    sanitizeObservedRoute(
      "http://127.0.0.1:43123/w?center=private-person&view=quadrants&lens=q2_pratica&group=family%3Ahub&token=secret",
      "http://127.0.0.1:43123"
    ),
    "/w?view=quadrants&lens=q2_pratica&group=family%3Ahub"
  );
  assert.throws(
    () => sanitizeObservedRoute("/private/account", "http://127.0.0.1:43123"),
    /private route namespace/
  );
  assert.throws(
    () => sanitizeObservedRoute("http://example.invalid/w", "http://127.0.0.1:43123"),
    /escaped the operator origin/
  );
});

test("all canary profiles enter native query routes and require v8 runtime", () => {
  assert.deepEqual(
    UPGRADE_GATE_EVIDENCE_PROFILES.map((profile) => ({
      profile: profile.profile,
      route: profile.route,
      view: profile.view,
      runtime_mode: profile.runtime_mode
    })),
    [
      { profile: "desktop", route: "/w?view=quadrants&tour=0", view: "quadrants", runtime_mode: "v8" },
      { profile: "mobile", route: "/w?view=timeline&tour=0", view: "timeline", runtime_mode: "v8" },
      { profile: "fallback", route: "/w?view=quadrants&visual=1&tour=0", view: "quadrants", runtime_mode: "v8" },
      {
        profile: "quadrant_collection_two_step",
        route: "/w?view=quadrants&lens=q2_pratica&overlay=actions&tour=0",
        view: "quadrants",
        runtime_mode: "v8"
      }
    ]
  );
});

test("profile observation rejects safe-looking wrong routes, views and runtimes", () => {
  const desktop = UPGRADE_GATE_EVIDENCE_PROFILES[0];
  assert.doesNotThrow(() => validateProfileObservation({
    route: desktop.route,
    view: desktop.view,
    runtime_mode: desktop.runtime_mode
  }, desktop));
  for (const mutation of [
    { route: "/totally-wrong-but-safe", view: "quadrants", runtime_mode: "v8" },
    { route: "/w/quadrants", view: "quadrants", runtime_mode: "v8" },
    { route: desktop.route, view: "timeline", runtime_mode: "v8" },
    { route: desktop.route, view: "quadrants", runtime_mode: "compat" }
  ]) {
    assert.throws(
      () => validateProfileObservation(mutation, desktop),
      /native contract/
    );
  }
});

test("real browser canary rejects a canonical mobile route rendering the wrong view", async () => {
  const mobile = UPGRADE_GATE_EVIDENCE_PROFILES.find((profile) => profile.profile === "mobile");
  await assert.rejects(
    runSyntheticProfileCapture(mobile, { view: "quadrants", runtimeMode: "v8" }),
    /view\/runtime differs from its native contract/
  );
});

test("real two-step canary rechecks runtime after the member transition", async () => {
  const twoStep = UPGRADE_GATE_EVIDENCE_PROFILES.find(
    (profile) => profile.profile === "quadrant_collection_two_step"
  );
  await assert.rejects(
    runSyntheticProfileCapture(twoStep, {
      view: "quadrants",
      runtimeMode: "v8",
      flipAfterMember: true
    }),
    /view\/runtime differs from its native contract/
  );
});

test("writer emits exactly four current-run profiles and three sanitized summaries", () => {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "wiki-upgrade-bundle-"));
  try {
    const captures = UPGRADE_GATE_EVIDENCE_PROFILES.map((profile) => ({
      profile: profile.profile,
      artifact: profile.artifact,
      route: profile.route,
      view: profile.view,
      runtime_mode: profile.runtime_mode,
      viewport: profile.viewport,
      png: png(profile.viewport.width, profile.viewport.height)
    }));
    const receipt = writeEvidenceBundle({
      artifactDir: fixture,
      captures,
      requestCount: 12,
      networkErrorCount: 0,
      consoleErrorCount: 0,
      consoleWarningCount: 1
    });
    assert.equal(receipt.files.length, 7);
    assert.deepEqual(fs.readdirSync(fixture).sort(), [
      "browser-console-summary.json",
      "desktop.png",
      "fallback.png",
      "mobile.png",
      "network-summary.json",
      "quadrant_collection_two_step.png",
      "visual-evidence-summary.json"
    ]);
    assert.deepEqual(
      Object.keys(JSON.parse(fs.readFileSync(path.join(fixture, "network-summary.json"), "utf8"))).sort(),
      ["capture_method", "error_count", "payloads_redacted", "request_count", "schema_version"]
    );
    const visual = JSON.parse(fs.readFileSync(path.join(fixture, "visual-evidence-summary.json"), "utf8"));
    assert.equal(visual.schema_version, "wiki_viva_canary_visual_summary.v2");
    assert.deepEqual(visual.entries.map((entry) => entry.profile), [
      "desktop",
      "mobile",
      "fallback",
      "quadrant_collection_two_step"
    ]);
    assert.deepEqual(visual.entries.map((entry) => entry.view), ["quadrants", "timeline", "quadrants", "quadrants"]);
    assert.deepEqual(visual.entries.map((entry) => entry.runtime_mode), ["v8", "v8", "v8", "v8"]);
    assert.throws(
      () => writeEvidenceBundle({
        artifactDir: fixture,
        captures,
        requestCount: 12,
        networkErrorCount: 0,
        consoleErrorCount: 0,
        consoleWarningCount: 0
      }),
      /no longer empty/
    );
  } finally {
    fs.rmSync(fixture, { recursive: true, force: true });
  }
});

test("writer rejects missing or non-v8 runtime before creating artifacts", async (t) => {
  for (const runtimeMode of [undefined, "compat", "legacy"]) {
    await t.test(String(runtimeMode), () => {
      const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "wiki-upgrade-runtime-"));
      try {
        const captures = UPGRADE_GATE_EVIDENCE_PROFILES.map((profile) => ({
          profile: profile.profile,
          artifact: profile.artifact,
          route: profile.route,
          view: profile.view,
          runtime_mode: profile.runtime_mode,
          viewport: profile.viewport,
          png: png(profile.viewport.width, profile.viewport.height)
        }));
        captures[0].runtime_mode = runtimeMode;
        assert.throws(
          () => writeEvidenceBundle({
            artifactDir: fixture,
            captures,
            requestCount: 12,
            networkErrorCount: 0,
            consoleErrorCount: 0,
            consoleWarningCount: 0
          }),
          /artifact\/view\/runtime\/viewport/
        );
        assert.deepEqual(fs.readdirSync(fixture), []);
      } finally {
        fs.rmSync(fixture, { recursive: true, force: true });
      }
    });
  }
});

test("writer refuses console/network failures before publishing any artifact", () => {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "wiki-upgrade-failed-bundle-"));
  const captures = UPGRADE_GATE_EVIDENCE_PROFILES.map((profile) => ({
    profile: profile.profile,
    artifact: profile.artifact,
    route: profile.route,
    view: profile.view,
    runtime_mode: profile.runtime_mode,
    viewport: profile.viewport,
    png: png(profile.viewport.width, profile.viewport.height)
  }));
  try {
    assert.throws(
      () => writeEvidenceBundle({
        artifactDir: fixture,
        captures,
        requestCount: 4,
        networkErrorCount: 1,
        consoleErrorCount: 0,
        consoleWarningCount: 0
      }),
      /observed console\/network errors/
    );
    assert.deepEqual(fs.readdirSync(fixture), []);
  } finally {
    fs.rmSync(fixture, { recursive: true, force: true });
  }
});
