#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { execFileSync, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  TEST_RESULTS_ROOT,
  readOwnedReleaseFile,
  writeOwnedReleaseFile,
  writeOwnedReleaseFileAtomic
} from "./release-path-safety.mjs";
import {
  assertSameReleaseBuild,
  collectReleaseBuildManifest
} from "./release-build-manifest.mjs";
import {
  assertReleaseBuildEnvironment,
  sanitizedReleaseBuildEnvironment
} from "./release-build-policy.mjs";
import { assertReleasePortAvailable } from "./release-server-policy.mjs";

const RUNNER_VERSION = "wiki_playwright_release_runner.v1";
const SCOPE_COMMAND = Object.freeze({
  public_required: "playwright_public_release_v1",
  downstream_required: "playwright_downstream_release_v1"
});

function argument(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? String(process.argv[index + 1] || "") : "";
}

function timestamp() {
  return new Date().toISOString();
}

function collectSubject(repoRoot) {
  const script = path.join(repoRoot, "scripts/wiki_git_subject.py");
  return JSON.parse(execFileSync(
    process.env.PYTHON || "python3",
    [script, "--root", repoRoot],
    { encoding: "utf8", maxBuffer: 8 * 1024 * 1024 }
  ));
}

function sameSubject(left, right) {
  const fields = [
    "source_sha", "tree_hash", "dirty", "dirty_entry_count",
    "worktree_fingerprint_version", "worktree_fingerprint",
    "staged_patch_sha256", "unstaged_patch_sha256",
    "untracked_state_sha256", "untracked_entry_count",
    "submodule_state_sha256"
  ];
  return fields.every((field) => left?.[field] === right?.[field]);
}

class StageFailure extends Error {
  constructor(stage, exitCode) {
    super(`release stage failed: ${stage}`);
    this.stage = stage;
    this.exitCode = Number.isInteger(exitCode) ? exitCode : 1;
  }
}

const scope = argument("--scope");
if (!Object.hasOwn(SCOPE_COMMAND, scope)) {
  console.error("release runner failed closed: --scope must be public_required or downstream_required");
  process.exit(1);
}

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = execFileSync("git", ["rev-parse", "--show-toplevel"], {
  cwd: appRoot,
  encoding: "utf8"
}).trim();
const runId = `${scope.replace(/_required$/, "")}-${Date.now().toString(36)}-${crypto.randomUUID()}`;
const runRoot = `${TEST_RESULTS_ROOT}/release-runs/${scope}/${runId}`;
const paths = Object.freeze({
  result: `${runRoot}/run-result.json`,
  subjectBefore: `${runRoot}/git-subject-before.json`,
  report: `${runRoot}/playwright-report.json`,
  artifacts: `${runRoot}/playwright-artifacts`,
  html: `${runRoot}/playwright-html`,
  gate: `${runRoot}/gate-result.json`,
  preflight: `${runRoot}/downstream-preflight.json`,
  buildManifest: `${runRoot}/release-build-manifest.json`
});
const startedAt = timestamp();
const releasePort = String(42000 + crypto.randomInt(20000));
let finishedAt = startedAt;
let stage = "subject_before";
let subjectBefore = null;
let subjectAfter = null;
let exitCode = 0;
let status = "blocked";
let releaseBuildManifest = null;

function runStage(name, command, args, extraEnv = {}) {
  stage = name;
  if (process.env.WIKI_RELEASE_TEST_FAIL_STAGE === name) {
    throw new StageFailure(name, 97);
  }
  const result = spawnSync(command, args, {
    cwd: appRoot,
    env: {
      ...(scope === "public_required"
        ? sanitizedReleaseBuildEnvironment()
        : process.env),
      ...extraEnv
    },
    stdio: "inherit"
  });
  if (result.error || result.status !== 0) {
    throw new StageFailure(name, result.status ?? 1);
  }
}

try {
  subjectBefore = collectSubject(repoRoot);
  writeOwnedReleaseFile(
    repoRoot,
    paths.subjectBefore,
    `${JSON.stringify(subjectBefore, null, 2)}\n`,
    { label: "release run subject before", allowedRoots: [TEST_RESULTS_ROOT] }
  );
  const npm = process.platform === "win32" ? "npm.cmd" : "npm";
  if (scope === "public_required") {
    stage = "build_environment";
    assertReleaseBuildEnvironment(appRoot, process.env);
  }
  runStage("matrix_contract", npm, ["run", "check:release-matrix"]);
  if (scope === "public_required") {
    runStage("build", npm, ["run", "build"]);
    releaseBuildManifest = collectReleaseBuildManifest(appRoot, subjectBefore.source_sha);
    writeOwnedReleaseFile(
      repoRoot,
      paths.buildManifest,
      `${JSON.stringify(releaseBuildManifest, null, 2)}\n`,
      { label: "release build manifest", allowedRoots: [TEST_RESULTS_ROOT] }
    );
    await assertReleasePortAvailable(Number(releasePort));
  }
  if (scope === "downstream_required") {
    runStage(
      "downstream_preflight",
      process.execPath,
      ["scripts/preflight-downstream-e2e.mjs", "--out", paths.preflight]
    );
  }
  runStage(
    "playwright",
    process.execPath,
    [
      "node_modules/@playwright/test/cli.js",
      "test",
      `--config=${scope === "public_required" ? "playwright.config.ts" : "playwright.downstream.config.ts"}`,
      "--retries=0"
    ],
    {
      WIKI_RELEASE_RUN: "1",
      WIKI_RELEASE_PORT: releasePort,
      WIKI_PLAYWRIGHT_JSON_REPORT: path.join(repoRoot, ...paths.report.split("/")),
      WIKI_PLAYWRIGHT_OUTPUT_DIR: path.join(repoRoot, ...paths.artifacts.split("/")),
      WIKI_PLAYWRIGHT_HTML_REPORT: path.join(repoRoot, ...paths.html.split("/"))
    }
  );
  if (scope === "public_required") {
    assertSameReleaseBuild(
      releaseBuildManifest,
      collectReleaseBuildManifest(appRoot, subjectBefore.source_sha)
    );
  }
  const checkerArgs = [
    "scripts/check-playwright-release.mjs",
    "--scope", scope,
    "--report", paths.report,
    "--subject-before", paths.subjectBefore,
    "--out", paths.gate,
    "--run-id", runId,
    "--started-at", startedAt,
    "--run-result", paths.result
  ];
  if (scope === "downstream_required") {
    checkerArgs.push("--preflight", paths.preflight);
  }
  if (scope === "public_required") {
    checkerArgs.push("--build-manifest", paths.buildManifest);
  }
  runStage("gate_compile", process.execPath, checkerArgs);
  if (scope === "public_required") {
    assertSameReleaseBuild(
      releaseBuildManifest,
      collectReleaseBuildManifest(appRoot, subjectBefore.source_sha)
    );
  }
  stage = "subject_after";
  subjectAfter = collectSubject(repoRoot);
  if (!sameSubject(subjectBefore, subjectAfter)) throw new StageFailure(stage, 1);
  status = "passed";
} catch (error) {
  exitCode = error instanceof StageFailure ? error.exitCode : 1;
  if (!(error instanceof StageFailure)) stage = stage || "internal";
  try {
    subjectAfter = collectSubject(repoRoot);
  } catch {
    subjectAfter = null;
  }
} finally {
  finishedAt = timestamp();
  let gateResult = null;
  if (status === "passed") {
    try {
      const gate = readOwnedReleaseFile(repoRoot, paths.gate, {
        label: "release run gate result",
        allowedRoots: [TEST_RESULTS_ROOT]
      });
      gateResult = {
        path: gate.relative,
        sha256: crypto.createHash("sha256").update(gate.contents).digest("hex"),
        bytes: gate.contents.byteLength
      };
    } catch {
      status = "blocked";
      stage = "terminal_gate_read";
      exitCode = 1;
    }
  }
  const result = {
    schema_version: "wiki_playwright_release_run.v1",
    runner_version: RUNNER_VERSION,
    run_id: runId,
    scope,
    command_id: SCOPE_COMMAND[scope],
    status,
    failure_stage: status === "blocked" ? stage : null,
    exit_code: status === "blocked" ? exitCode || 1 : 0,
    started_at: startedAt,
    finished_at: finishedAt,
    subject_before: subjectBefore,
    subject_after: subjectAfter,
    paths: {
      report: paths.report,
      preflight: scope === "downstream_required" ? paths.preflight : null,
      build_manifest: scope === "public_required" ? paths.buildManifest : null,
      gate_result: gateResult
    }
  };
  writeOwnedReleaseFileAtomic(
    repoRoot,
    paths.result,
    `${JSON.stringify(result, null, 2)}\n`,
    { label: "release run final result", allowedRoots: [TEST_RESULTS_ROOT] }
  );
  console.log(`release run result: ${paths.result} (${status})`);
}

if (status !== "passed") process.exitCode = exitCode || 1;
