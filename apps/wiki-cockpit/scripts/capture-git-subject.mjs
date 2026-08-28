#!/usr/bin/env node

import path from "node:path";
import { execFileSync } from "node:child_process";
import {
  RELEASE_DERIVED_ROOT,
  resolveOwnedReleaseFile,
  writeOwnedReleaseFile
} from "./release-path-safety.mjs";

function argument(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? String(process.argv[index + 1] || "") : "";
}

function argumentsFor(name) {
  return process.argv.flatMap((value, index) =>
    value === name && process.argv[index + 1] ? [String(process.argv[index + 1])] : []
  );
}

try {
  const outputArgument = argument("--out");
  if (!outputArgument) throw new Error("--out is required");
  const repoRoot = execFileSync("git", ["rev-parse", "--show-toplevel"], {
    encoding: "utf8"
  }).trim();
  const clearArguments = argumentsFor("--clear");
  if (clearArguments.length) {
    throw new Error("--clear is unsupported because release evidence is immutable");
  }
  resolveOwnedReleaseFile(repoRoot, outputArgument, {
    label: "--out",
    allowedRoots: [RELEASE_DERIVED_ROOT]
  });
  const subjectScript = path.join(repoRoot, "scripts/wiki_git_subject.py");
  const raw = execFileSync(
    process.env.PYTHON || "python3",
    [subjectScript, "--root", repoRoot],
    { encoding: "utf8", maxBuffer: 8 * 1024 * 1024 }
  );
  const subject = JSON.parse(raw);
  if (
    !/^[0-9a-f]{40}$/.test(String(subject.source_sha || "")) ||
    !/^[0-9a-f]{40}$/.test(String(subject.tree_hash || "")) ||
    !/^[0-9a-f]{64}$/.test(String(subject.worktree_fingerprint || ""))
  ) {
    throw new Error("wiki_git_subject.py returned an invalid subject");
  }
  writeOwnedReleaseFile(
    repoRoot,
    outputArgument,
    `${JSON.stringify(subject, null, 2)}\n`,
    { label: "--out", allowedRoots: [RELEASE_DERIVED_ROOT] }
  );
  console.log(`git subject captured: ${subject.source_sha} ${subject.worktree_fingerprint}`);
} catch (error) {
  console.error(`git subject capture failed closed: ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
}
