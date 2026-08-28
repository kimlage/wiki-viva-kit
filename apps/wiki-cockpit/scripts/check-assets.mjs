#!/usr/bin/env node

import path from "node:path";
import { fileURLToPath } from "node:url";
import { evaluateAssetManifest } from "./asset-gate-lib.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.resolve(scriptDir, "..");
const result = evaluateAssetManifest({ appRoot });

console.log("Wiki Viva cockpit asset provenance gate");
if (result.summary) {
  console.log(`  contract: ${result.summary.schema_version}`);
  console.log(`  assets: ${result.summary.asset_count}/${result.summary.max_asset_count} (${result.summary.first_party_asset_count} first-party, ${result.summary.external_asset_count} external)`);
  console.log(`  bytes: ${result.summary.total_bytes}/${result.summary.max_total_bytes} total; ${result.summary.max_single_asset_bytes} maximum per asset`);
  console.log(`  local runtime references: ${result.summary.local_reference_count}`);
  console.log(`  icon dependency: ${result.summary.icon_dependency}@${result.summary.icon_dependency_version} (${result.summary.icon_dependency_license}; lock-bound runtime dependency, not a vendored asset)`);
}
for (const error of result.errors) console.error(`ASSET ERROR [${error.code}]: ${error.detail}`);

if (!result.ok) {
  console.error(`Asset gate failed with ${result.errors.length} error(s).`);
  process.exit(1);
}

console.log("Asset gate passed: every local asset is licensed, hashed and budgeted; hotlinks and inline data assets are absent.");
