import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import {
  assertReleaseBuildEnvironment,
  RELEASE_BUILD_MANIFEST_SCHEMA_VERSION
} from "./release-build-policy.mjs";
import { verifyPublicReleaseRuntimeConfig } from "./public-release-runtime-config.mjs";

function canonicalFiles(files) {
  return JSON.stringify(files);
}

function readStableRegularFile(file, label) {
  const descriptor = fs.openSync(
    file,
    fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0)
  );
  try {
    const before = fs.fstatSync(descriptor);
    if (!before.isFile() || before.nlink !== 1) {
      throw new Error(`${label} must be a regular non-hard-linked file`);
    }
    const contents = fs.readFileSync(descriptor);
    const after = fs.fstatSync(descriptor);
    for (const field of ["dev", "ino", "size", "mtimeMs", "nlink"]) {
      if (before[field] !== after[field]) throw new Error(`${label} changed while read`);
    }
    return contents;
  } finally {
    fs.closeSync(descriptor);
  }
}

export function collectReleaseBuildManifest(appRoot, subjectSha, env = process.env) {
  if (process.platform === "win32") {
    throw new Error("release build evidence is unsupported on Windows");
  }
  if (!/^[0-9a-f]{40}$/.test(String(subjectSha || ""))) {
    throw new Error("release build manifest requires an exact Git subject");
  }
  const buildInputs = assertReleaseBuildEnvironment(appRoot, env);
  const nodeExecutable = fs.realpathSync(process.execPath);
  const nodeContents = readStableRegularFile(
    nodeExecutable,
    "release builder Node executable"
  );
  const builderRuntime = {
    node_version: process.versions.node,
    node_executable_sha256: crypto
      .createHash("sha256")
      .update(nodeContents)
      .digest("hex"),
    node_executable_bytes: nodeContents.byteLength
  };
  const distRoot = path.join(appRoot, "dist");
  const rootState = fs.lstatSync(distRoot);
  if (!rootState.isDirectory() || rootState.isSymbolicLink()) {
    throw new Error("release dist root must be a real directory");
  }
  const files = [];
  const visit = (directory, relativeDirectory = "") => {
    const entries = fs.readdirSync(directory, { withFileTypes: true })
      .sort((left, right) => left.name.localeCompare(right.name, "en"));
    for (const entry of entries) {
      const absolute = path.join(directory, entry.name);
      const relative = path.posix.join(relativeDirectory, entry.name);
      const state = fs.lstatSync(absolute);
      if (state.isSymbolicLink()) throw new Error("release dist must not contain symlinks");
      if (state.isDirectory()) {
        visit(absolute, relative);
        continue;
      }
      if (!state.isFile() || state.nlink !== 1) {
        throw new Error("release dist must contain only regular non-hard-linked files");
      }
      const contents = readStableRegularFile(absolute, `release dist file ${relative}`);
      files.push({
        path: `dist/${relative}`,
        sha256: crypto.createHash("sha256").update(contents).digest("hex"),
        bytes: contents.byteLength
      });
    }
  };
  visit(distRoot);
  if (files.length === 0) throw new Error("release dist inventory is empty");
  // The consumer-owned runtime config is intentionally excluded from C1.
  // A public release build therefore proves that the served byte came from
  // the package-owned synthetic source before its dist inventory is sealed.
  verifyPublicReleaseRuntimeConfig(appRoot);
  files.sort((left, right) => left.path.localeCompare(right.path, "en"));
  return {
    schema_version: RELEASE_BUILD_MANIFEST_SCHEMA_VERSION,
    scope: "public_required",
    subject_sha: subjectSha,
    dist_root: "apps/wiki-cockpit/dist",
    build_inputs: buildInputs,
    builder_runtime: builderRuntime,
    file_count: files.length,
    aggregate_sha256: crypto.createHash("sha256").update(canonicalFiles(files)).digest("hex"),
    files
  };
}

export function assertSameReleaseBuild(expected, current) {
  if (JSON.stringify(expected) !== JSON.stringify(current)) {
    throw new Error("served release dist changed during the required matrix");
  }
}
