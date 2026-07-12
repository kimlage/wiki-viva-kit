import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

export const TEST_RESULTS_ROOT = "apps/wiki-cockpit/test-results";
export const RELEASE_DERIVED_ROOT = "data/derived/wiki/release";
export const RELEASE_OWNED_ROOTS = Object.freeze([
  TEST_RESULTS_ROOT,
  RELEASE_DERIVED_ROOT
]);

export function assertReleaseEvidencePlatform(platform = process.platform) {
  if (platform === "win32") {
    throw new Error(
      "release evidence operations are unsupported on Windows until handle-pinned reparse-point traversal is available"
    );
  }
}

function canonicalRepoRelative(raw, label) {
  if (
    typeof raw !== "string" ||
    !raw ||
    raw !== raw.trim() ||
    raw.includes("\0") ||
    raw.includes("\\") ||
    path.posix.isAbsolute(raw) ||
    /^[A-Za-z]:/.test(raw)
  ) {
    throw new Error(`${label} must be one canonical repo-relative POSIX path`);
  }
  const parts = raw.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) {
    throw new Error(`${label} must be one canonical repo-relative POSIX path`);
  }
  return parts.join("/");
}

function underRoot(relative, root) {
  return relative.startsWith(`${root}/`) && relative !== root;
}

function gitStatus(repoRoot, args) {
  return spawnSync("git", args, {
    cwd: repoRoot,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
}

function ensureUntrackedIgnored(repoRoot, relative, label) {
  const tracked = gitStatus(repoRoot, ["ls-files", "--error-unmatch", "--", relative]);
  if (tracked.status === 0) throw new Error(`${label} must never target a tracked file`);
  const ignored = gitStatus(repoRoot, ["check-ignore", "-q", "--", relative]);
  if (ignored.status !== 0) {
    throw new Error(`${label} must stay under an explicitly ignored release-evidence root`);
  }
}

function ensureDirectoryChain(repoRoot, relativeParent, label, create) {
  const root = fs.realpathSync(repoRoot);
  let current = root;
  for (const part of relativeParent.split("/")) {
    current = path.join(current, part);
    try {
      const state = fs.lstatSync(current);
      if (state.isSymbolicLink()) throw new Error(`${label} must not traverse a symlink`);
      if (!state.isDirectory()) throw new Error(`${label} ancestor must be a directory`);
    } catch (error) {
      if (!(error && typeof error === "object" && error.code === "ENOENT")) throw error;
      if (!create) return false;
      fs.mkdirSync(current, { mode: 0o700 });
      const created = fs.lstatSync(current);
      if (created.isSymbolicLink() || !created.isDirectory()) {
        throw new Error(`${label} parent directory could not be created safely`);
      }
    }
  }
  return true;
}

export function resolveOwnedReleaseFile(
  repoRoot,
  raw,
  {
    label = "release evidence file",
    allowedRoots = RELEASE_OWNED_ROOTS,
    mustExist = false,
    createParents = false
  } = {}
) {
  assertReleaseEvidencePlatform();
  const root = fs.realpathSync(repoRoot);
  const relative = canonicalRepoRelative(raw, label);
  if (!allowedRoots.some((allowed) => underRoot(relative, allowed))) {
    throw new Error(`${label} is outside the owned release-evidence roots`);
  }
  const parentRelative = path.posix.dirname(relative);
  const parentExists = ensureDirectoryChain(root, parentRelative, label, false);
  const absolute = path.join(root, ...relative.split("/"));
  let targetExists = false;
  if (parentExists) {
    try {
      const state = fs.lstatSync(absolute);
      targetExists = true;
      if (state.isSymbolicLink()) throw new Error(`${label} target must not be a symlink`);
      if (!state.isFile()) throw new Error(`${label} target must be a regular file`);
      if (state.nlink !== 1) throw new Error(`${label} target must not be hard-linked`);
    } catch (error) {
      if (!(error && typeof error === "object" && error.code === "ENOENT")) throw error;
    }
  }
  ensureUntrackedIgnored(root, relative, label);
  if (mustExist && !targetExists) throw new Error(`${label} is missing`);
  if (createParents && !parentExists) ensureDirectoryChain(root, parentRelative, label, true);
  return { absolute, relative };
}

export function removeOwnedReleaseFile(repoRoot, raw, options = {}) {
  resolveOwnedReleaseFile(repoRoot, raw, {
    ...options,
    mustExist: false,
    createParents: false
  });
  throw new Error("release evidence is immutable and cannot be removed or replaced");
}

export function writeOwnedReleaseFile(repoRoot, raw, contents, options = {}) {
  return writeOwnedReleaseFileAtomic(repoRoot, raw, contents, options);
}

export function writeOwnedReleaseFileAtomic(repoRoot, raw, contents, options = {}) {
  const resolved = resolveOwnedReleaseFile(repoRoot, raw, {
    ...options,
    mustExist: false,
    createParents: true
  });
  const temporary = `${resolved.relative}.tmp-${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const tempResolved = resolveOwnedReleaseFile(repoRoot, temporary, {
    ...options,
    label: `${options.label || "release evidence file"} temporary`,
    mustExist: false,
    createParents: true
  });
  let descriptor;
  try {
    descriptor = fs.openSync(
      tempResolved.absolute,
      fs.constants.O_WRONLY |
        fs.constants.O_CREAT |
        fs.constants.O_EXCL |
        (fs.constants.O_NOFOLLOW || 0),
      0o600
    );
    const state = fs.fstatSync(descriptor);
    if (!state.isFile() || state.nlink !== 1) {
      throw new Error(`${options.label || "release evidence file"} temporary is unsafe`);
    }
    fs.writeFileSync(descriptor, contents);
    fs.fsyncSync(descriptor);
    fs.closeSync(descriptor);
    descriptor = undefined;
    // A hard-link publish is atomic and, unlike rename, fails with EEXIST
    // instead of replacing a path inserted after the precheck.
    fs.linkSync(tempResolved.absolute, resolved.absolute);
    fs.unlinkSync(tempResolved.absolute);
    if (process.platform !== "win32") {
      const parent = fs.openSync(path.dirname(resolved.absolute), fs.constants.O_RDONLY);
      try {
        fs.fsyncSync(parent);
      } finally {
        fs.closeSync(parent);
      }
    }
  } finally {
    if (descriptor !== undefined) fs.closeSync(descriptor);
    try {
      fs.unlinkSync(tempResolved.absolute);
    } catch (error) {
      if (!(error && typeof error === "object" && error.code === "ENOENT")) throw error;
    }
  }
  return resolved;
}

export function readOwnedReleaseFile(repoRoot, raw, options = {}) {
  const resolved = resolveOwnedReleaseFile(repoRoot, raw, {
    ...options,
    mustExist: true,
    createParents: false
  });
  const descriptor = fs.openSync(
    resolved.absolute,
    fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0)
  );
  try {
    const state = fs.fstatSync(descriptor);
    if (!state.isFile()) throw new Error(`${options.label || "release evidence file"} is not regular`);
    if (state.nlink !== 1) throw new Error(`${options.label || "release evidence file"} must not be hard-linked`);
    return { ...resolved, contents: fs.readFileSync(descriptor) };
  } finally {
    fs.closeSync(descriptor);
  }
}
