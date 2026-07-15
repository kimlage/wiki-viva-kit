import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { chromium } from "@playwright/test";
import {
  runDownstreamPreflight,
  validateDownstreamEnvironment
} from "./release-matrix-lib.mjs";
import {
  TEST_RESULTS_ROOT,
  readOwnedReleaseFile
} from "./release-path-safety.mjs";

const SUBJECT_FIELDS = Object.freeze([
  "source_sha",
  "tree_hash",
  "dirty",
  "dirty_entry_count",
  "worktree_fingerprint_version",
  "worktree_fingerprint",
  "staged_patch_sha256",
  "unstaged_patch_sha256",
  "untracked_state_sha256",
  "untracked_entry_count",
  "submodule_state_sha256"
]);
const PROFILE_SPECS = Object.freeze([
  {
    profile: "desktop",
    artifact: "desktop.png",
    route: "/w?view=quadrants&tour=0",
    view: "quadrants",
    viewport: { width: 1440, height: 1000 },
    mode: "desktop",
    runtime_mode: "v8"
  },
  {
    profile: "mobile",
    artifact: "mobile.png",
    route: "/w?view=timeline&tour=0",
    view: "timeline",
    viewport: { width: 390, height: 844 },
    mode: "mobile",
    runtime_mode: "v8"
  },
  {
    profile: "fallback",
    artifact: "fallback.png",
    route: "/w?view=quadrants&visual=1&tour=0",
    view: "quadrants",
    viewport: { width: 1440, height: 1000 },
    mode: "fallback",
    runtime_mode: "v8"
  },
  {
    profile: "quadrant_collection_two_step",
    artifact: "quadrant_collection_two_step.png",
    route: "/w?view=quadrants&lens=q2_pratica&overlay=actions&tour=0",
    view: "quadrants",
    viewport: { width: 1440, height: 1000 },
    mode: "quadrant_collection_two_step",
    runtime_mode: "v8"
  }
]);
const ALLOWED_ROUTE_PARAMETERS = new Set([
  "group",
  "lens",
  "overlay",
  "tour",
  "view",
  "visual"
]);
const SECRET_ROUTE_PARAMETER = /(?:authorization|cookie|credential|password|secret|session|signature|token|api[-_]?key)/i;
const GATE_ID = /^[a-z][a-z0-9_.-]{1,127}$/;
const RUN_ID = /^[a-z0-9][a-z0-9._-]{7,127}$/;
const SHA40 = /^[0-9a-f]{40}$/;

function fail(message) {
  throw new Error(`upgrade gate evidence rejected: ${message}`);
}

function sha256(raw) {
  return crypto.createHash("sha256").update(raw).digest("hex");
}

function jsonBytes(payload) {
  return Buffer.from(`${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function collectSubject(repoRoot, env = process.env) {
  const script = path.join(repoRoot, "scripts/wiki_git_subject.py");
  return JSON.parse(execFileSync(
    env.PYTHON || "python3",
    [script, "--root", repoRoot],
    { encoding: "utf8", maxBuffer: 8 * 1024 * 1024 }
  ));
}

function sameSubject(left, right) {
  return SUBJECT_FIELDS.every((field) => left?.[field] === right?.[field]);
}

function sameGateSubject(subject, gateResult) {
  return (
    subject?.source_sha === gateResult?.subject_sha &&
    SUBJECT_FIELDS.filter((field) => field !== "source_sha")
      .every((field) => subject?.[field] === gateResult?.[field])
  );
}

function parseTimestamp(value, label) {
  if (typeof value !== "string" || !value || !Number.isFinite(Date.parse(value))) {
    fail(`${label} is not an ISO-8601 timestamp`);
  }
  return Date.parse(value);
}

export function validateEvidenceBindings({
  runId,
  startedAt,
  gateResult,
  subjectBefore,
  currentSubject,
  expectedConsumerHead,
  now = Date.now()
}) {
  if (!RUN_ID.test(runId)) fail("run_id is invalid");
  const started = parseTimestamp(startedAt, "started_at");
  if (started > now + 5 * 60_000 || now - started > 24 * 60 * 60_000) {
    fail("release run is stale or future-dated");
  }
  if (!SHA40.test(expectedConsumerHead)) fail("expected consumer HEAD is not exact");
  if (
    !gateResult ||
    gateResult.schema_version !== "wiki_test_gate_result.v1" ||
    gateResult.scope !== "downstream_required" ||
    gateResult.command_id !== "playwright_downstream_release_v1" ||
    gateResult.run_id !== runId ||
    gateResult.started_at !== startedAt ||
    gateResult.status !== "passed" ||
    gateResult.failed !== 0 ||
    gateResult.skipped !== 0 ||
    gateResult.flaky !== 0 ||
    gateResult.retries !== 0 ||
    !Number.isInteger(gateResult.passed) ||
    gateResult.passed <= 0
  ) {
    fail("gate result is not one current, first-attempt downstream pass");
  }
  const finished = parseTimestamp(gateResult.finished_at, "gate finished_at");
  if (finished < started || finished > now + 5 * 60_000) {
    fail("gate result timestamps do not bind the current run");
  }
  if (
    !subjectBefore ||
    !currentSubject ||
    subjectBefore.dirty !== false ||
    currentSubject.dirty !== false ||
    subjectBefore.dirty_entry_count !== 0 ||
    currentSubject.dirty_entry_count !== 0 ||
    gateResult.dirty !== false ||
    gateResult.dirty_entry_count !== 0 ||
    !sameSubject(subjectBefore, currentSubject) ||
    !sameGateSubject(subjectBefore, gateResult) ||
    subjectBefore.source_sha !== expectedConsumerHead ||
    currentSubject.source_sha !== expectedConsumerHead ||
    gateResult.subject_sha !== expectedConsumerHead
  ) {
    fail("Git, gate and operator consumer subjects differ");
  }
  return { source_sha: expectedConsumerHead, started_at: startedAt };
}

export function resolveGateArtifactDirectory(env = process.env) {
  const rawRun = String(env.WIKI_UPGRADE_RUN_DIR || "");
  const rawArtifact = String(env.WIKI_UPGRADE_GATE_ARTIFACT_DIR || "");
  const gateId = String(env.WIKI_UPGRADE_GATE_ID || "");
  if (!rawRun || !rawArtifact || !GATE_ID.test(gateId)) {
    fail("runner-owned artifact directory identity is incomplete");
  }
  if (
    !path.isAbsolute(rawRun) ||
    !path.isAbsolute(rawArtifact) ||
    path.resolve(rawRun) !== rawRun ||
    path.resolve(rawArtifact) !== rawArtifact
  ) {
    fail("runner-owned artifact paths must be canonical absolute paths");
  }
  const runState = fs.lstatSync(rawRun);
  const artifactState = fs.lstatSync(rawArtifact);
  if (
    runState.isSymbolicLink() ||
    artifactState.isSymbolicLink() ||
    !runState.isDirectory() ||
    !artifactState.isDirectory()
  ) {
    fail("runner-owned artifact path must be a real directory");
  }
  const runRoot = fs.realpathSync(rawRun);
  const artifactDir = fs.realpathSync(rawArtifact);
  if (runRoot !== rawRun || artifactDir !== rawArtifact) {
    fail("runner-owned artifact path must not traverse aliases or symlinks");
  }
  const expected = path.join(runRoot, "gate-artifacts", gateId);
  if (artifactDir !== expected) {
    fail("artifact directory does not belong to the active gate/run pair");
  }
  if (fs.readdirSync(artifactDir).length !== 0) {
    fail("artifact directory must be empty at the start of this run");
  }
  return { artifactDir, gateId, runRoot };
}

export function sanitizeObservedRoute(raw, baseUrl) {
  let observed;
  let base;
  try {
    base = new URL(baseUrl);
    observed = new URL(raw, base);
  } catch {
    fail("captured route is not a valid URL");
  }
  if (observed.origin !== base.origin) fail("captured route escaped the operator origin");
  if (!observed.pathname.startsWith("/") || /^\/(?:private|consumer|real)(?:\/|$)/i.test(observed.pathname)) {
    fail("captured route exposes a private route namespace");
  }
  const sanitized = new URL(observed.pathname, "http://wiki-viva.invalid");
  for (const [key, value] of observed.searchParams.entries()) {
    if (SECRET_ROUTE_PARAMETER.test(key) || !ALLOWED_ROUTE_PARAMETERS.has(key)) continue;
    if (!/^[A-Za-z0-9_.:-]{1,128}$/.test(value)) {
      fail(`captured route parameter ${key} is not public-safe`);
    }
    sanitized.searchParams.append(key, value);
  }
  return `${sanitized.pathname}${sanitized.search}`;
}

function requireNativeProfileRoute(route, spec) {
  if (typeof route !== "string" || !route.startsWith("/")) {
    fail(`visual profile ${spec.profile} route is not canonical`);
  }
  let actual;
  let expected;
  try {
    actual = new URL(route, "http://wiki-viva.invalid");
    expected = new URL(spec.route, "http://wiki-viva.invalid");
  } catch {
    fail(`visual profile ${spec.profile} route is not canonical`);
  }
  const actualEntries = [...actual.searchParams.entries()];
  const actualKeys = actualEntries.map(([key]) => key);
  const expectedEntries = [...expected.searchParams.entries()];
  const expectedQuery = new Map(expectedEntries);
  const allowedDynamic = spec.profile === "quadrant_collection_two_step"
    ? new Set(["group"])
    : new Set();
  if (
    actual.origin !== "http://wiki-viva.invalid" ||
    actual.pathname !== expected.pathname ||
    actual.hash ||
    actualKeys.length !== new Set(actualKeys).size ||
    actualEntries.some(([key, value]) =>
      (!expectedQuery.has(key) && !allowedDynamic.has(key)) ||
      !/^[A-Za-z0-9_.:-]{1,128}$/.test(value)
    ) ||
    expectedEntries.some(([key, value]) => actual.searchParams.get(key) !== value)
  ) {
    fail(`visual profile ${spec.profile} route differs from its native contract`);
  }
}

export function validateProfileObservation(observation, spec) {
  if (
    !observation ||
    !spec ||
    observation.view !== spec.view ||
    observation.runtime_mode !== spec.runtime_mode
  ) {
    fail(`visual profile ${spec?.profile || "unknown"} view/runtime differs from its native contract`);
  }
  requireNativeProfileRoute(observation.route, spec);
  return observation;
}

function pngDimensions(raw) {
  if (
    !Buffer.isBuffer(raw) ||
    raw.length < 33 ||
    !raw.subarray(0, 8).equals(Buffer.from("89504e470d0a1a0a", "hex")) ||
    raw.subarray(12, 16).toString("ascii") !== "IHDR" ||
    !raw.subarray(-8, -4).equals(Buffer.from("49454e44", "hex"))
  ) {
    fail("captured visual artifact is not a complete PNG");
  }
  return { width: raw.readUInt32BE(16), height: raw.readUInt32BE(20) };
}

function writeExclusive(target, raw) {
  if (path.basename(target) !== path.basename(target).replaceAll("/", "")) {
    fail("artifact filename is unsafe");
  }
  let descriptor;
  try {
    descriptor = fs.openSync(
      target,
      fs.constants.O_WRONLY |
        fs.constants.O_CREAT |
        fs.constants.O_EXCL |
        (fs.constants.O_NOFOLLOW || 0),
      0o600
    );
    const state = fs.fstatSync(descriptor);
    if (!state.isFile() || state.nlink !== 1) fail("artifact target is not an exclusive regular file");
    fs.writeFileSync(descriptor, raw);
    fs.fsyncSync(descriptor);
  } finally {
    if (descriptor !== undefined) fs.closeSync(descriptor);
  }
}

export function writeEvidenceBundle({ artifactDir, captures, requestCount, networkErrorCount, consoleErrorCount, consoleWarningCount }) {
  const expectedProfiles = PROFILE_SPECS.map((item) => item.profile);
  if (
    !Array.isArray(captures) ||
    captures.length !== expectedProfiles.length ||
    captures.map((item) => item?.profile).join("\0") !== expectedProfiles.join("\0") ||
    !Number.isInteger(requestCount) ||
    requestCount <= 0 ||
    !Number.isInteger(networkErrorCount) ||
    networkErrorCount !== 0 ||
    !Number.isInteger(consoleErrorCount) ||
    consoleErrorCount !== 0 ||
    !Number.isInteger(consoleWarningCount) ||
    consoleWarningCount < 0
  ) {
    fail("current-run capture is incomplete or observed console/network errors");
  }
  if (fs.readdirSync(artifactDir).length !== 0) fail("artifact directory is no longer empty");
  const visualEntries = [];
  const files = [];
  for (const [index, capture] of captures.entries()) {
    const expected = PROFILE_SPECS[index];
    if (
      capture.artifact !== expected.artifact ||
      !capture.viewport ||
      capture.viewport.width !== expected.viewport.width ||
      capture.viewport.height !== expected.viewport.height ||
      capture.view !== expected.view ||
      capture.runtime_mode !== expected.runtime_mode ||
      typeof capture.route !== "string" ||
      !capture.route.startsWith("/")
    ) {
      fail(`visual profile ${expected.profile} is not bound to its exact artifact/view/runtime/viewport`);
    }
    validateProfileObservation(capture, expected);
    const dimensions = pngDimensions(capture.png);
    if (
      dimensions.width !== expected.viewport.width ||
      dimensions.height !== expected.viewport.height
    ) {
      fail(`visual profile ${expected.profile} dimensions differ from its viewport`);
    }
    visualEntries.push({
      profile: expected.profile,
      artifact: expected.artifact,
      route: capture.route,
      view: capture.view,
      runtime_mode: capture.runtime_mode,
      viewport: expected.viewport
    });
  }
  const payloads = [
    ...captures.map((capture) => [capture.artifact, capture.png]),
    [
      "network-summary.json",
      jsonBytes({
        schema_version: "wiki_viva_network_capture_summary.v1",
        capture_method: "playwright_current_run_loopback_operator",
        request_count: requestCount,
        error_count: networkErrorCount,
        payloads_redacted: true
      })
    ],
    [
      "browser-console-summary.json",
      jsonBytes({
        schema_version: "wiki_viva_browser_console_summary.v1",
        error_count: consoleErrorCount,
        warning_count: consoleWarningCount,
        payloads_redacted: true
      })
    ],
    [
      "visual-evidence-summary.json",
      jsonBytes({
        schema_version: "wiki_viva_canary_visual_summary.v2",
        entries: visualEntries
      })
    ]
  ];
  for (const [name, raw] of payloads) {
    const target = path.join(artifactDir, name);
    writeExclusive(target, raw);
    files.push({ name, sha256: sha256(raw), bytes: raw.length });
  }
  const observed = fs.readdirSync(artifactDir).sort();
  const expected = payloads.map(([name]) => name).sort();
  if (JSON.stringify(observed) !== JSON.stringify(expected)) {
    fail("artifact directory contains an unowned or missing file");
  }
  return { files: files.sort((left, right) => left.name.localeCompare(right.name)) };
}

function attachTelemetry(page, counters) {
  page.on("request", () => {
    counters.requestCount += 1;
  });
  page.on("requestfailed", () => {
    counters.networkErrorCount += 1;
  });
  page.on("response", (response) => {
    if (response.status() >= 400) counters.networkErrorCount += 1;
  });
  page.on("console", (message) => {
    if (message.type() === "error") counters.consoleErrorCount += 1;
    if (message.type() === "warning") counters.consoleWarningCount += 1;
  });
  page.on("pageerror", () => {
    counters.consoleErrorCount += 1;
  });
}

async function requireWorldReady(page, expectedRepo) {
  const response = await page.waitForLoadState("domcontentloaded").then(() => null).catch(() => null);
  void response;
  await page.locator(".worldWorkspace").waitFor({ state: "visible", timeout: 30_000 });
  await page.locator(".sceneShell").waitFor({ state: "visible", timeout: 30_000 });
  if (await page.locator(".demoBanner").count()) fail("operator capture fell back to the public demo");
  const topBar = await page.locator(".topBar").textContent();
  if (!String(topBar || "").includes(expectedRepo)) fail("operator UI does not expose the expected repo");
  if (await page.getByRole("alert").count()) fail("operator UI exposes a blocking alert");
}

async function requireProfileState(page, spec, baseUrl) {
  const workspace = page.locator(".worldWorkspace");
  const state = await workspace.evaluate((element) => ({
    view: element.getAttribute("data-world-view") || "",
    runtime_mode: element.getAttribute("data-runtime-mode") || ""
  }));
  const route = sanitizeObservedRoute(page.url(), baseUrl);
  validateProfileObservation({ ...state, route }, spec);
  return { ...state, route };
}

export async function captureProfile(browser, spec, expected, counters) {
  const context = await browser.newContext({
    baseURL: expected.baseUrl,
    viewport: spec.viewport,
    screen: spec.viewport,
    deviceScaleFactor: 1,
    colorScheme: "dark",
    locale: "pt-BR",
    hasTouch: spec.mode === "mobile",
    isMobile: spec.mode === "mobile",
    reducedMotion: spec.mode === "fallback" ? "reduce" : "no-preference"
  });
  const page = await context.newPage();
  attachTelemetry(page, counters);
  try {
    await page.addInitScript(() => {
      window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
      window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
      window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
    });
    const navigation = await page.goto(spec.route, {
      waitUntil: "domcontentloaded",
      timeout: 60_000
    });
    if (!navigation || !navigation.ok()) fail(`profile ${spec.profile} navigation failed`);
    await requireWorldReady(page, expected.expectedRepo);
    if (spec.mode === "desktop") {
      await page.locator(".sceneShell canvas").waitFor({ state: "attached", timeout: 30_000 });
      if (await page.locator(".sceneShell.fallbackMode").count()) fail("desktop profile used fallback rendering");
    }
    if (spec.mode === "fallback") {
      await page.locator(".sceneShell.fallbackMode").waitFor({ state: "visible", timeout: 30_000 });
    }
    if (spec.mode === "quadrant_collection_two_step") {
      const workspace = page.locator(".worldWorkspace");
      await workspace.waitFor({ state: "visible" });
      await page.locator(".sceneShell canvas").waitFor({ state: "attached", timeout: 30_000 });
      await workspace.evaluate((element) => {
        const scope = window;
        scope.__wikiUpgradeEvidenceCanvas = document.querySelector(".sceneShell canvas");
        scope.__wikiUpgradeEvidenceCenter = element.dataset.worldCenter || "";
      });
      const group = page.locator('[data-world-target-kind="group"]:visible').first();
      await group.waitFor({ state: "visible", timeout: 30_000 });
      await group.click();
      const summary = page.locator("[data-world-group-summary]:visible").first();
      await summary.waitFor({ state: "visible", timeout: 30_000 });
      const members = summary.locator("[data-world-member-id]:visible");
      if (await members.count() < 1) fail("quadrant collection exposes no real member");
      const capturedState = await requireProfileState(page, spec, expected.baseUrl);
      const png = await page.screenshot({ animations: "disabled", fullPage: false });
      await members.first().click();
      await page.waitForFunction(() => {
        const workspaceElement = document.querySelector(".worldWorkspace");
        return Boolean(
          workspaceElement &&
          workspaceElement.dataset.worldCenter &&
          workspaceElement.dataset.worldCenter !== window.__wikiUpgradeEvidenceCenter
        );
      }, null, { timeout: 30_000 });
      const preserved = await page.evaluate(() =>
        document.querySelector(".sceneShell canvas") === window.__wikiUpgradeEvidenceCanvas
      );
      if (!preserved) fail("quadrant collection journey remounted the world canvas");
      await requireProfileState(page, spec, expected.baseUrl);
      return {
        profile: spec.profile,
        artifact: spec.artifact,
        route: capturedState.route,
        view: capturedState.view,
        runtime_mode: capturedState.runtime_mode,
        viewport: spec.viewport,
        png
      };
    }
    const capturedState = await requireProfileState(page, spec, expected.baseUrl);
    const png = await page.screenshot({ animations: "disabled", fullPage: false });
    return {
      profile: spec.profile,
      artifact: spec.artifact,
      route: capturedState.route,
      view: capturedState.view,
      runtime_mode: capturedState.runtime_mode,
      viewport: spec.viewport,
      png
    };
  } finally {
    page.removeAllListeners();
    await context.close();
  }
}

export async function exportUpgradeGateEvidence({
  repoRoot,
  runId,
  startedAt,
  gateResultPath,
  subjectBeforePath,
  env = process.env
}) {
  const validatedEnvironment = validateDownstreamEnvironment(env);
  if (!validatedEnvironment.ok) fail(validatedEnvironment.errors.join("; "));
  const expected = validatedEnvironment.values;
  const { artifactDir } = resolveGateArtifactDirectory(env);
  const gateFile = readOwnedReleaseFile(repoRoot, gateResultPath, {
    label: "current downstream gate result",
    allowedRoots: [TEST_RESULTS_ROOT]
  });
  const subjectFile = readOwnedReleaseFile(repoRoot, subjectBeforePath, {
    label: "current downstream subject before",
    allowedRoots: [TEST_RESULTS_ROOT]
  });
  if (
    path.posix.dirname(gateFile.relative) !== path.posix.dirname(subjectFile.relative) ||
    !gateFile.relative.split("/").includes(runId)
  ) {
    fail("gate result and subject do not belong to one current release run");
  }
  const gateResult = JSON.parse(gateFile.contents.toString("utf8"));
  const subjectBefore = JSON.parse(subjectFile.contents.toString("utf8"));
  const currentSubject = collectSubject(repoRoot, env);
  validateEvidenceBindings({
    runId,
    startedAt,
    gateResult,
    subjectBefore,
    currentSubject,
    expectedConsumerHead: expected.expectedConsumerHead
  });
  const reportFile = readOwnedReleaseFile(repoRoot, gateResult.evidence_path, {
    label: "current downstream Playwright report",
    allowedRoots: [TEST_RESULTS_ROOT]
  });
  if (
    reportFile.contents.length !== gateResult.evidence_bytes ||
    sha256(reportFile.contents) !== gateResult.evidence_sha256
  ) {
    fail("gate result no longer binds its executed Playwright report");
  }
  await runDownstreamPreflight(env, globalThis.fetch, {}, repoRoot);

  const counters = {
    requestCount: 0,
    networkErrorCount: 0,
    consoleErrorCount: 0,
    consoleWarningCount: 0
  };
  const captures = [];
  const browser = await chromium.launch({ headless: true });
  try {
    for (const spec of PROFILE_SPECS) {
      captures.push(await captureProfile(browser, spec, expected, counters));
    }
  } finally {
    await browser.close();
  }
  const finalSubject = collectSubject(repoRoot, env);
  validateEvidenceBindings({
    runId,
    startedAt,
    gateResult,
    subjectBefore,
    currentSubject: finalSubject,
    expectedConsumerHead: expected.expectedConsumerHead
  });
  return writeEvidenceBundle({ artifactDir, captures, ...counters });
}

export const UPGRADE_GATE_EVIDENCE_PROFILES = PROFILE_SPECS;
