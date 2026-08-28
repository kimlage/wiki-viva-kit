#!/usr/bin/env node

import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  analyzeBundle,
  evaluateBundle,
  formatBytes,
  inspectBundleGateArguments,
  inspectBundleBuildConfiguration
} from "./bundle-gate-lib.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.resolve(scriptDir, "..");
let buildOutput = "";
const invocationViolations = inspectBundleGateArguments(process.argv.slice(2));
if (invocationViolations.length > 0) {
  for (const violation of invocationViolations) {
    console.error(`BUNDLE INVOCATION VIOLATION [${violation.id}]: ${violation.detail}`);
  }
  process.exit(1);
}

console.log("Building the production cockpit with a Vite manifest before measuring bundle budgets...");
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const build = spawnSync(npmCommand, ["run", "build"], {
  cwd: appRoot,
  encoding: "utf8",
  env: process.env,
  maxBuffer: 32 * 1024 * 1024
});
if (build.stdout) process.stdout.write(build.stdout);
if (build.stderr) process.stderr.write(build.stderr);
buildOutput = `${build.stdout ?? ""}\n${build.stderr ?? ""}`;
if (build.error) {
  console.error(`Bundle gate could not execute the production build: ${build.error.message}`);
  process.exit(1);
}
if (build.status !== 0) {
  console.error(`Bundle gate stopped because the production build exited with status ${build.status}.`);
  process.exit(1);
}

let report;
try {
  report = analyzeBundle(path.join(appRoot, "dist"));
} catch (error) {
  console.error(`Bundle gate could not inspect the production artifacts: ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
}

const result = evaluateBundle(report, {
  buildOutput,
  configurationViolations: inspectBundleBuildConfiguration(appRoot)
});
const largestLazy = report.lazyJs[0];

console.log("Wiki Viva cockpit production bundle gate");
console.log(`  initial JS gzip: ${formatBytes(report.totals.initialJsGzipBytes)} / ${formatBytes(result.budgets.initialJsGzipBytes)}`);
console.log(`  initial CSS min: ${formatBytes(report.totals.initialCssBytes)} / ${formatBytes(result.budgets.initialCssBytes)}`);
console.log(`  initial CSS gzip: ${formatBytes(report.totals.initialCssGzipBytes)} / ${formatBytes(result.budgets.initialCssGzipBytes)}`);
console.log(`  initial HTML gzip: ${formatBytes(report.totals.initialHtmlGzipBytes)} / ${formatBytes(result.budgets.initialHtmlGzipBytes)}`);
console.log(
  largestLazy
    ? `  largest lazy/worker JS gzip: ${formatBytes(largestLazy.gzipBytes)} (${largestLazy.file}) / ${formatBytes(result.budgets.lazyChunkGzipBytes)}`
    : "  largest lazy/worker JS gzip: none"
);
console.log(`  measured artifacts: ${report.initialJs.length} initial JS, ${report.initialCss.length} initial CSS, ${report.lazyJs.length} lazy/worker JS`);
console.log("  required lazy capabilities: RuntimeWorldView, SystemScene, PageReader");

for (const item of result.violations) {
  const measurement = typeof item.actual === "number"
    ? ` actual=${formatBytes(item.actual)} budget=${formatBytes(item.budget)}`
    : "";
  const file = item.file ? ` file=${item.file}` : "";
  console.error(`BUNDLE VIOLATION [${item.id}]${file}${measurement}: ${item.detail}`);
}

if (!result.ok) {
  console.error(`Bundle gate failed with ${result.violations.length} blocking violation(s). Budgets are fixed by the v8 contract; warnings are not silenced or converted to an allowed baseline.`);
  process.exit(1);
}

console.log("Bundle gate passed: production artifacts and build warnings satisfy the explicit v8 budgets.");
