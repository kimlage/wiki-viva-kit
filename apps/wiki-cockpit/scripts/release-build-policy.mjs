import fs from "node:fs";
import path from "node:path";

export const RELEASE_BUILD_INPUTS_SCHEMA_VERSION = "wiki_release_build_inputs.v1";
export const RELEASE_BUILD_MANIFEST_SCHEMA_VERSION = "wiki_release_build_manifest.v2";
export const RELEASE_BUILD_INTERNAL_SENTINEL = "WIKI_COCKPIT_RELEASE_BUILD_INTERNAL";

const FORBIDDEN_ENVIRONMENT_NAMES = Object.freeze([
  "BABEL_ENV",
  "ESBUILD_BINARY_PATH",
  "NODE_ENV",
  "NODE_OPTIONS",
  "NODE_PATH",
  "WIKI_COCKPIT_PROXY_API",
  RELEASE_BUILD_INTERNAL_SENTINEL
]);
const FORBIDDEN_ENVIRONMENT_PREFIXES = Object.freeze(["VITE_"]);
const FIXED_RELEASE_ENVIRONMENT = Object.freeze({
  LANG: "C",
  LC_ALL: "C",
  TZ: "UTC",
  SOURCE_DATE_EPOCH: "0",
  NODE_ENV: "production",
  [RELEASE_BUILD_INTERNAL_SENTINEL]: "1"
});

function fixedReleasePath(nodeExecutable = process.execPath) {
  return [path.dirname(path.resolve(nodeExecutable)), "/usr/bin", "/bin"].join(
    path.delimiter
  );
}

function releaseEnvFiles(appRoot) {
  return fs.readdirSync(appRoot, { withFileTypes: true })
    .map((entry) => entry.name)
    .filter((name) => name === ".env" || name.startsWith(".env."))
    .sort((left, right) => left.localeCompare(right, "en"));
}

function forbiddenEnvironmentNames(env) {
  return Object.keys(env)
    .filter((name) => (
      FORBIDDEN_ENVIRONMENT_NAMES.includes(name) ||
      FORBIDDEN_ENVIRONMENT_PREFIXES.some((prefix) => name.startsWith(prefix))
    ))
    .sort((left, right) => left.localeCompare(right, "en"));
}

export function effectiveReleaseBuildInputs() {
  return {
    schema_version: RELEASE_BUILD_INPUTS_SCHEMA_VERSION,
    command_id: "wiki_cockpit_release_build.v1",
    vite_mode: "production",
    node_env: "production",
    vite_env_loading: "disabled",
    runtime_config_path: "public/wiki-cockpit.config.json",
    runtime_config_delivery: "runtime_fetch_no_store.v1",
    environment_policy: {
      env_files: "forbidden",
      parent_launcher: "posix_env_i.v1",
      inherited_names: [],
      path_policy: "node_binary_dir_plus_usr_bin_bin.v1",
      fixed_variables: { ...FIXED_RELEASE_ENVIRONMENT },
      forbidden_names: [...FORBIDDEN_ENVIRONMENT_NAMES],
      forbidden_prefixes: [...FORBIDDEN_ENVIRONMENT_PREFIXES]
    }
  };
}

export function assertGenericReleaseBuildEnvironment(appRoot, env = process.env) {
  const root = path.resolve(appRoot);
  const envFiles = releaseEnvFiles(root);
  if (envFiles.length > 0) {
    throw new Error(
      `release build environment is not reproducible: remove app-local .env files (${envFiles.join(", ")})`
    );
  }
  const forbidden = forbiddenEnvironmentNames(env);
  if (forbidden.length > 0) {
    throw new Error(
      `release build environment is not reproducible: forbidden variables are present (${forbidden.join(", ")})`
    );
  }
  return effectiveReleaseBuildInputs();
}

export function assertInternalReleaseBuildEnvironment(appRoot, env = process.env) {
  const envFiles = releaseEnvFiles(path.resolve(appRoot));
  if (envFiles.length > 0) {
    throw new Error(
      `release build environment is not reproducible: remove app-local .env files (${envFiles.join(", ")})`
    );
  }
  const unexpected = Object.keys(env)
    .filter((name) => (
      name.startsWith("VITE_") ||
      [
        "BABEL_ENV",
        "ESBUILD_BINARY_PATH",
        "NODE_OPTIONS",
        "NODE_PATH",
        "WIKI_COCKPIT_PROXY_API"
      ].includes(name)
    ))
    .sort((left, right) => left.localeCompare(right, "en"));
  const fixedEnvironmentMatches = Object.entries(FIXED_RELEASE_ENVIRONMENT)
    .every(([name, expected]) => env[name] === expected);
  if (
    !fixedEnvironmentMatches ||
    env.PATH !== fixedReleasePath() ||
    unexpected.length > 0
  ) {
    const detail = unexpected.length > 0 ? `; forbidden variables: ${unexpected.join(", ")}` : "";
    throw new Error(`vite production build must run through the release build runner${detail}`);
  }
  return effectiveReleaseBuildInputs();
}

export function assertReleaseBuildEnvironment(appRoot, env = process.env) {
  return env[RELEASE_BUILD_INTERNAL_SENTINEL] === "1"
    ? assertInternalReleaseBuildEnvironment(appRoot, env)
    : assertGenericReleaseBuildEnvironment(appRoot, env);
}

export function sanitizedReleaseBuildEnvironment() {
  return {
    PATH: fixedReleasePath(),
    ...FIXED_RELEASE_ENVIRONMENT
  };
}
