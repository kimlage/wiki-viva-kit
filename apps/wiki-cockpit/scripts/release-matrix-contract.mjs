#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { buildReleaseMatrixContract } from "./release-matrix-lib.mjs";

const APP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PLAYWRIGHT_CLI = path.join(APP_ROOT, "node_modules/@playwright/test/cli.js");
const CONTRACT_PATH = path.join(APP_ROOT, "scripts/release-matrix-contract.json");

export function collectPlaywrightList(configFile) {
  const stdout = execFileSync(
    process.execPath,
    [PLAYWRIGHT_CLI, "test", `--config=${configFile}`, "--list", "--reporter=json"],
    { cwd: APP_ROOT, encoding: "utf8", maxBuffer: 32 * 1024 * 1024 }
  );
  return JSON.parse(stdout);
}

export function collectCurrentReleaseMatrix() {
  return buildReleaseMatrixContract(
    collectPlaywrightList("playwright.config.ts"),
    collectPlaywrightList("playwright.downstream.config.ts")
  );
}

function serialized(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

function main() {
  const write = process.argv.includes("--write");
  const check = process.argv.includes("--check") || !write;
  if (write && process.argv.includes("--check")) {
    throw new Error("choose exactly one of --write or --check");
  }
  const current = collectCurrentReleaseMatrix();
  if (write) {
    fs.writeFileSync(CONTRACT_PATH, serialized(current), "utf8");
    console.log(`release matrix contract written: ${CONTRACT_PATH}`);
    return;
  }
  if (check) {
    const expected = fs.readFileSync(CONTRACT_PATH, "utf8");
    const actual = serialized(current);
    if (expected !== actual) {
      throw new Error(
        "release matrix contract is stale; review the exact --list diff, then run node scripts/release-matrix-contract.mjs --write"
      );
    }
    console.log(
      `release matrix contract current: ${current.public_required.expected_tests} public + ${current.downstream_required.expected_tests} downstream cells`
    );
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    main();
  } catch (error) {
    console.error(`release matrix contract failed closed: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  }
}
