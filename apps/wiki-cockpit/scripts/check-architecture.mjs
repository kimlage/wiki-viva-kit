#!/usr/bin/env node

import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  collectArchitectureViolations,
  evaluateArchitectureBaseline,
  readArchitectureBaseline,
  summarizeByRule
} from "./architecture-gate-lib.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.resolve(scriptDir, "..");
const baselinePath = path.join(scriptDir, "architecture-debt.json");
const violations = collectArchitectureViolations(appRoot);

if (process.argv.includes("--print-current-json")) {
  process.stdout.write(`${JSON.stringify(violations, null, 2)}\n`);
  process.exit(0);
}

let baseline;
try {
  baseline = readArchitectureBaseline(baselinePath);
} catch (error) {
  console.error(`Architecture gate could not read ${baselinePath}: ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
}

const result = evaluateArchitectureBaseline(violations, baseline);

console.log("Wiki Viva cockpit architecture boundary gate");
console.log(`Scanned production source; found ${violations.length} tracked boundary violation(s).`);
for (const [rule, count] of summarizeByRule(violations)) console.log(`  ${rule}: ${count}`);

for (const message of result.baselineErrors) console.error(`BASELINE ERROR: ${message}`);
for (const entry of result.regressions) {
  console.error(`NEW VIOLATION: ${entry.file}:${entry.line} [${entry.ruleId}] ${entry.detail}`);
  console.error(`  fingerprint: ${entry.fingerprint}`);
}
for (const entry of result.staleDebt) {
  console.error(`STALE DEBT: ${entry.fingerprint}`);
  console.error("  Remove the resolved entry from scripts/architecture-debt.json in the same change.");
}

if (!result.ok) {
  console.error(
    `Architecture gate failed: ${result.regressions.length} regression(s), ${result.staleDebt.length} stale debt entr${result.staleDebt.length === 1 ? "y" : "ies"}, ${result.baselineErrors.length} baseline error(s).`
  );
  process.exit(1);
}

console.log(`Architecture gate passed with ${result.acceptedDebt.length} exact legacy debt entr${result.acceptedDebt.length === 1 ? "y" : "ies"}; any added or silently resolved violation fails the gate.`);
