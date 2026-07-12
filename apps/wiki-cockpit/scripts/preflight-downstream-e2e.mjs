#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { runDownstreamPreflight } from "./release-matrix-lib.mjs";
import {
  TEST_RESULTS_ROOT,
  writeOwnedReleaseFile
} from "./release-path-safety.mjs";

function argument(name, fallback = "") {
  const index = process.argv.indexOf(name);
  return index >= 0 ? String(process.argv[index + 1] || "") : fallback;
}

const repoRoot = execFileSync("git", ["rev-parse", "--show-toplevel"], {
  encoding: "utf8"
}).trim();
const output = argument("--out", `${TEST_RESULTS_ROOT}/downstream-preflight.json`);
try {
  const evidence = await runDownstreamPreflight(process.env, globalThis.fetch, {}, repoRoot);
  writeOwnedReleaseFile(repoRoot, output, `${JSON.stringify(evidence, null, 2)}\n`, {
    label: "downstream preflight output",
    allowedRoots: [TEST_RESULTS_ROOT]
  });
  console.log(
    `downstream preflight passed: ${evidence.repository} ${evidence.snapshot_revision} ` +
    `(${evidence.page_count} pages, ${evidence.temporal_event_count} temporal events, ` +
    `${evidence.active_packs.length} active packs, ${evidence.adapter_file_count} adapter files, ` +
    `composition ${evidence.composition_sha256.slice(0, 12)})`
  );
} catch (error) {
  console.error(`downstream preflight failed closed: ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
}
