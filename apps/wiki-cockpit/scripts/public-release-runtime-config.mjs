import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

export const PUBLIC_RELEASE_RUNTIME_CONFIG_PATH = "scripts/public-release-runtime-config.json";
export const PUBLIC_RELEASE_RUNTIME_CONFIG_OUTPUT = "wiki-cockpit.config.json";
export const PUBLIC_RELEASE_RUNTIME_CONFIG_DELIVERY = "package_owned_static_demo_override.v1";

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

function parsePublicSyntheticConfig(raw, label) {
  let parsed;
  try {
    parsed = JSON.parse(raw.toString("utf8"));
  } catch {
    throw new Error(`${label} must be valid JSON`);
  }
  const expectedKeys = ["api_base", "codex", "mode", "repo_label", "snapshot_base"];
  if (
    !parsed ||
    typeof parsed !== "object" ||
    Array.isArray(parsed) ||
    Object.keys(parsed).sort().join(",") !== expectedKeys.join(",") ||
    parsed.api_base !== "" ||
    parsed.snapshot_base !== "/sample-snapshot" ||
    parsed.repo_label !== "Wiki Viva Kit demo" ||
    parsed.mode !== "static_demo" ||
    !parsed.codex ||
    typeof parsed.codex !== "object" ||
    Array.isArray(parsed.codex) ||
    Object.keys(parsed.codex).join(",") !== "enabled" ||
    parsed.codex.enabled !== false
  ) {
    throw new Error(`${label} must be the exact public synthetic static-demo contract`);
  }
  return parsed;
}

function requireRealDirectory(directory, label) {
  const state = fs.lstatSync(directory);
  if (!state.isDirectory() || state.isSymbolicLink()) {
    throw new Error(`${label} must be a real directory`);
  }
}

export function readPublicReleaseRuntimeConfig(appRoot) {
  const source = path.join(path.resolve(appRoot), ...PUBLIC_RELEASE_RUNTIME_CONFIG_PATH.split("/"));
  const raw = readStableRegularFile(source, "public release runtime config");
  parsePublicSyntheticConfig(raw, "public release runtime config");
  return {
    path: PUBLIC_RELEASE_RUNTIME_CONFIG_PATH,
    raw,
    sha256: crypto.createHash("sha256").update(raw).digest("hex")
  };
}

export function materializePublicReleaseRuntimeConfig(appRoot) {
  const root = path.resolve(appRoot);
  const source = readPublicReleaseRuntimeConfig(root);
  const distRoot = path.join(root, "dist");
  requireRealDirectory(distRoot, "release dist root");
  const output = path.join(distRoot, PUBLIC_RELEASE_RUNTIME_CONFIG_OUTPUT);
  if (fs.existsSync(output)) {
    const state = fs.lstatSync(output);
    if (!state.isFile() || state.isSymbolicLink() || state.nlink !== 1) {
      throw new Error("release runtime config output must be a regular non-hard-linked file");
    }
  }
  const temporary = path.join(
    distRoot,
    `.${PUBLIC_RELEASE_RUNTIME_CONFIG_OUTPUT}.${process.pid}.${crypto.randomUUID()}.tmp`
  );
  const descriptor = fs.openSync(temporary, fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_WRONLY, 0o644);
  try {
    fs.writeFileSync(descriptor, source.raw);
    fs.fsyncSync(descriptor);
  } finally {
    fs.closeSync(descriptor);
  }
  try {
    fs.renameSync(temporary, output);
  } catch (error) {
    fs.rmSync(temporary, { force: true });
    throw error;
  }
  return verifyPublicReleaseRuntimeConfig(appRoot);
}

export function verifyPublicReleaseRuntimeConfig(appRoot) {
  const root = path.resolve(appRoot);
  const source = readPublicReleaseRuntimeConfig(root);
  const output = path.join(root, "dist", PUBLIC_RELEASE_RUNTIME_CONFIG_OUTPUT);
  const served = readStableRegularFile(output, "served public release runtime config");
  parsePublicSyntheticConfig(served, "served public release runtime config");
  if (!served.equals(source.raw)) {
    throw new Error("served public release runtime config is not byte-equal to the package-owned synthetic source");
  }
  return {
    source_path: source.path,
    output_path: `dist/${PUBLIC_RELEASE_RUNTIME_CONFIG_OUTPUT}`,
    sha256: source.sha256,
    bytes: source.raw.byteLength
  };
}
