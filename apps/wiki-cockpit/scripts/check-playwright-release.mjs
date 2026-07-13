#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { chromium, firefox, webkit } from "@playwright/test";
import {
  evaluateDownstreamPreflightRecord,
  evaluateRequiredPlaywrightReport
} from "./release-matrix-lib.mjs";
import {
  TEST_RESULTS_ROOT,
  readOwnedReleaseFile,
  resolveOwnedReleaseFile,
  writeOwnedReleaseFile
} from "./release-path-safety.mjs";
import {
  assertSameReleaseBuild,
  collectReleaseBuildManifest
} from "./release-build-manifest.mjs";

function argument(name, fallback = "") {
  const index = process.argv.indexOf(name);
  return index >= 0 ? String(process.argv[index + 1] || "") : fallback;
}

function git(...args) {
  return execFileSync("git", args, { encoding: "utf8" }).trim();
}

function collectGitSubject(repoRoot, subjectScript) {
  return JSON.parse(
    execFileSync(
      process.env.PYTHON || "python3",
      [subjectScript, "--root", repoRoot],
      { encoding: "utf8", maxBuffer: 8 * 1024 * 1024 }
    )
  );
}

const SUBJECT_FIELDS = [
  "source_sha",
  "tree_hash",
  "dirty",
  "dirty_entry_count",
  "worktree_fingerprint",
  "worktree_fingerprint_version",
  "staged_patch_sha256",
  "unstaged_patch_sha256",
  "untracked_state_sha256",
  "untracked_entry_count",
  "submodule_state_sha256"
];

const scope = argument("--scope");
const reportArgument = argument("--report");
const outputArgument = argument(
  "--out",
  `${TEST_RESULTS_ROOT}/${scope}.gate.json`
);
const preflightArgument = argument("--preflight");
const subjectBeforeArgument = argument("--subject-before");
const runId = argument("--run-id");
const startedAt = argument("--started-at");
const runResultArgument = argument("--run-result");
const contractArgument = argument("--contract");
const buildManifestArgument = argument("--build-manifest");
const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.resolve(scriptsDir, "..");
const contractPath = path.resolve(
  scriptsDir,
  "release-matrix-contract.json"
);

try {
  if (!scope || !reportArgument || !subjectBeforeArgument || !runId || !startedAt || !runResultArgument) {
    throw new Error("--scope, --report, --subject-before, --run-id, --started-at and --run-result are required");
  }
  if (!/^[a-z0-9][a-z0-9._-]{7,127}$/.test(runId) || !Number.isFinite(Date.parse(startedAt))) {
    throw new Error("release run provenance is invalid");
  }
  if (contractArgument) throw new Error("custom --contract paths are not allowed");
  if (scope === "downstream_required" && !preflightArgument) {
    throw new Error("--preflight is required for downstream_required");
  }
  if (scope === "public_required" && preflightArgument) {
    throw new Error("--preflight belongs only to downstream_required");
  }
  const repoRoot = git("rev-parse", "--show-toplevel");
  const repoRelative = (absolute, label) => {
    const relative = path.relative(repoRoot, absolute).replaceAll("\\", "/");
    if (!relative || relative === ".." || relative.startsWith("../")) {
      throw new Error(`${label} must stay inside the repository`);
    }
    return relative;
  };
  resolveOwnedReleaseFile(repoRoot, outputArgument, {
    label: "gate output",
    allowedRoots: [TEST_RESULTS_ROOT]
  });
  resolveOwnedReleaseFile(repoRoot, reportArgument, {
    label: "Playwright report",
    allowedRoots: [TEST_RESULTS_ROOT]
  });
  resolveOwnedReleaseFile(repoRoot, subjectBeforeArgument, {
    label: "pre-run Git subject",
    allowedRoots: [TEST_RESULTS_ROOT]
  });
  resolveOwnedReleaseFile(repoRoot, runResultArgument, {
    label: "terminal run result",
    allowedRoots: [TEST_RESULTS_ROOT]
  });
  if (
    path.posix.dirname(outputArgument) !== path.posix.dirname(reportArgument) ||
    path.posix.dirname(outputArgument) !== path.posix.dirname(subjectBeforeArgument) ||
    path.posix.dirname(outputArgument) !== path.posix.dirname(runResultArgument) ||
    !outputArgument.split("/").includes(runId)
  ) {
    throw new Error("gate/report/subject must share one unique run_id directory");
  }
  if (preflightArgument) {
    resolveOwnedReleaseFile(repoRoot, preflightArgument, {
      label: "downstream preflight",
      allowedRoots: [TEST_RESULTS_ROOT]
    });
    if (path.posix.dirname(preflightArgument) !== path.posix.dirname(outputArgument)) {
      throw new Error("downstream preflight must share the unique run_id directory");
    }
  }
  if (buildManifestArgument) {
    resolveOwnedReleaseFile(repoRoot, buildManifestArgument, {
      label: "release build manifest",
      allowedRoots: [TEST_RESULTS_ROOT]
    });
    if (path.posix.dirname(buildManifestArgument) !== path.posix.dirname(outputArgument)) {
      throw new Error("release build manifest must share the unique run_id directory");
    }
  }
  if (scope === "public_required" && !buildManifestArgument) {
    throw new Error("--build-manifest is required for public_required");
  }
  if (scope === "downstream_required" && buildManifestArgument) {
    throw new Error("--build-manifest belongs only to public_required");
  }
  const reportFile = readOwnedReleaseFile(repoRoot, reportArgument, {
    label: "Playwright report",
    allowedRoots: [TEST_RESULTS_ROOT]
  });
  const raw = reportFile.contents;
  const report = JSON.parse(raw.toString("utf8"));
  const matrixContractRaw = fs.readFileSync(contractPath);
  const matrixContract = JSON.parse(matrixContractRaw.toString("utf8"));
  const result = evaluateRequiredPlaywrightReport(report, scope, matrixContract);
  if (!result.ok) throw new Error(result.errors.join("; "));
  const subjectBeforeFile = readOwnedReleaseFile(repoRoot, subjectBeforeArgument, {
    label: "pre-run Git subject",
    allowedRoots: [TEST_RESULTS_ROOT]
  });
  const subjectBeforeRaw = subjectBeforeFile.contents;
  const subjectBefore = JSON.parse(subjectBeforeRaw.toString("utf8"));
  const subjectScript = path.join(repoRoot, "scripts/wiki_git_subject.py");
  const subjectAfter = collectGitSubject(repoRoot, subjectScript);
  for (const field of SUBJECT_FIELDS) {
    if (subjectBefore[field] !== subjectAfter[field]) {
      throw new Error(`Git subject changed during the required matrix: ${field}`);
    }
  }
  const supportingEvidence = [];
  const addSupportingContents = (id, relative, rawFile) => {
    supportingEvidence.push({
      id,
      path: relative,
      sha256: crypto.createHash("sha256").update(rawFile).digest("hex"),
      bytes: rawFile.byteLength
    });
  };
  const addSupportingFile = (id, absolute, label) => {
    const rawFile = fs.readFileSync(absolute);
    addSupportingContents(id, repoRelative(absolute, label), rawFile);
  };
  addSupportingFile("release-matrix-contract", contractPath, "release matrix contract");
  addSupportingContents(
    "git-subject-before",
    subjectBeforeFile.relative,
    subjectBeforeRaw
  );
  if (buildManifestArgument) {
    const buildManifestFile = readOwnedReleaseFile(repoRoot, buildManifestArgument, {
      label: "release build manifest",
      allowedRoots: [TEST_RESULTS_ROOT]
    });
    const buildManifest = JSON.parse(buildManifestFile.contents.toString("utf8"));
    assertSameReleaseBuild(
      buildManifest,
      collectReleaseBuildManifest(appRoot, subjectAfter.source_sha)
    );
    addSupportingContents(
      "release-build-manifest",
      buildManifestFile.relative,
      buildManifestFile.contents
    );
  }
  const toolchainFiles = [
    [
      "playwright-config",
      path.join(
        appRoot,
        scope === "public_required" ? "playwright.config.ts" : "playwright.downstream.config.ts"
      )
    ],
    ["release-matrix-checker", fileURLToPath(import.meta.url)],
    ["release-matrix-library", path.join(scriptsDir, "release-matrix-lib.mjs")],
    ["operator-security-contract", path.join(appRoot, "src/contracts/operatorSecurity.js")],
    ["release-matrix-generator", path.join(scriptsDir, "release-matrix-contract.mjs")],
    ["release-matrix-contract", contractPath],
    ["release-build-manifest", path.join(scriptsDir, "release-build-manifest.mjs")],
    ["release-build-policy", path.join(scriptsDir, "release-build-policy.mjs")],
    ["release-build-runner", path.join(scriptsDir, "build-production.mjs")],
    ["release-build-launcher", path.join(scriptsDir, "build-production.sh")],
    ["cockpit-vite-config", path.join(appRoot, "vite.config.ts")],
    ["release-server-policy", path.join(scriptsDir, "release-server-policy.mjs")],
    ["release-path-safety", path.join(scriptsDir, "release-path-safety.mjs")],
    ["git-subject-capture", path.join(scriptsDir, "capture-git-subject.mjs")],
    ["release-runner", path.join(scriptsDir, "run-playwright-release.mjs")],
    ["upgrade-gate-evidence-adapter", path.join(scriptsDir, "export-upgrade-gate-evidence.mjs")],
    ["release-runner-launcher", path.join(scriptsDir, "run-playwright-release.sh")],
    ["downstream-preflight-runner", path.join(scriptsDir, "preflight-downstream-e2e.mjs")],
    ["git-subject-compiler", subjectScript],
    ["git-subject-helper", path.join(repoRoot, "scripts/_git_subject.py")],
    ["cockpit-package", path.join(appRoot, "package.json")],
    ["cockpit-lockfile", path.join(appRoot, "package-lock.json")]
  ].map(([id, absolute]) => {
    const contents = fs.readFileSync(absolute);
    return {
      id,
      path: repoRelative(absolute, `toolchain file ${id}`),
      sha256: crypto.createHash("sha256").update(contents).digest("hex"),
      bytes: contents.byteLength
    };
  });
  const pythonVersion = execFileSync(
    process.env.PYTHON || "python3",
    ["-c", "import platform; print(platform.python_version())"],
    { encoding: "utf8" }
  ).trim();
  const browserTypes = { chromium, firefox, webkit };
  const requiredEngines = scope === "public_required"
    ? ["chromium", "firefox", "webkit"]
    : ["chromium"];
  const browserEngines = [];
  for (const name of requiredEngines) {
    const browser = await browserTypes[name].launch({ headless: true });
    try {
      browserEngines.push({ name, version: browser.version() });
    } finally {
      await browser.close();
    }
  }
  const toolchainRelative = `${path.posix.dirname(outputArgument)}/toolchain-manifest.json`;
  writeOwnedReleaseFile(
    repoRoot,
    toolchainRelative,
    `${JSON.stringify({
      schema_version: "wiki_playwright_toolchain_manifest.v1",
      scope,
      runner_version: "wiki_playwright_release_runner.v1",
      runtime: {
        platform: process.platform,
        arch: process.arch,
        node_version: process.versions.node,
        playwright_version: matrixContract.playwright_version,
        python_version: pythonVersion,
        browser_engines: browserEngines
      },
      files: toolchainFiles
    }, null, 2)}\n`,
    { label: "release toolchain manifest", allowedRoots: [TEST_RESULTS_ROOT] }
  );
  const toolchainFile = readOwnedReleaseFile(repoRoot, toolchainRelative, {
    label: "release toolchain manifest",
    allowedRoots: [TEST_RESULTS_ROOT]
  });
  addSupportingContents(
    "release-toolchain-manifest",
    toolchainFile.relative,
    toolchainFile.contents
  );
  if (preflightArgument) {
    const preflightFile = readOwnedReleaseFile(repoRoot, preflightArgument, {
      label: "downstream preflight",
      allowedRoots: [TEST_RESULTS_ROOT]
    });
    const preflightRaw = preflightFile.contents;
    const preflight = JSON.parse(preflightRaw.toString("utf8"));
    const preflightEvaluation = evaluateDownstreamPreflightRecord(preflight, process.env, repoRoot);
    if (!preflightEvaluation.ok) throw new Error(preflightEvaluation.errors.join("; "));
    if (String(preflight.consumer_head || "").toLowerCase() !== subjectAfter.source_sha) {
      throw new Error("downstream preflight consumer HEAD does not match the tested Git subject");
    }
    addSupportingContents(
      "downstream-preflight",
      preflightFile.relative,
      preflightRaw
    );
  }
  const subjectFinal = collectGitSubject(repoRoot, subjectScript);
  for (const field of SUBJECT_FIELDS) {
    if (subjectAfter[field] !== subjectFinal[field]) {
      throw new Error(`Git subject changed while compiling gate evidence: ${field}`);
    }
  }
  const gate = {
    schema_version: "wiki_test_gate_result.v1",
    id: `playwright-${scope.replace(/_required$/, "")}`,
    scope,
    command_id: scope === "public_required"
      ? "playwright_public_release_v1"
      : "playwright_downstream_release_v1",
    run_id: runId,
    started_at: startedAt,
    finished_at: new Date().toISOString(),
    run_result_path: runResultArgument,
    status: "passed",
    passed: result.summary.passed,
    failed: result.summary.failed,
    skipped: result.summary.skipped,
    flaky: result.summary.flaky,
    retries: result.summary.retries,
    subject_sha: subjectAfter.source_sha,
    tree_hash: subjectAfter.tree_hash,
    dirty: subjectAfter.dirty,
    dirty_entry_count: subjectAfter.dirty_entry_count,
    worktree_fingerprint: subjectAfter.worktree_fingerprint,
    worktree_fingerprint_version: subjectAfter.worktree_fingerprint_version,
    staged_patch_sha256: subjectAfter.staged_patch_sha256,
    unstaged_patch_sha256: subjectAfter.unstaged_patch_sha256,
    untracked_state_sha256: subjectAfter.untracked_state_sha256,
    untracked_entry_count: subjectAfter.untracked_entry_count,
    submodule_state_sha256: subjectAfter.submodule_state_sha256,
    evidence_path: reportFile.relative,
    evidence_sha256: crypto.createHash("sha256").update(raw).digest("hex"),
    evidence_bytes: raw.byteLength,
    files: result.summary.files,
    test_cells: result.cells.map((cell) => cell.id),
    supporting_evidence: supportingEvidence
  };
  writeOwnedReleaseFile(
    repoRoot,
    outputArgument,
    `${JSON.stringify(gate, null, 2)}\n`,
    { label: "gate output", allowedRoots: [TEST_RESULTS_ROOT] }
  );
  console.log(`${scope} release matrix passed: ${gate.passed} first-attempt tests, 0 skipped, 0 retries`);
} catch (error) {
  console.error(`required Playwright matrix failed closed: ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
}
