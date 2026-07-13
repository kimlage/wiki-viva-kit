#!/usr/bin/env node

import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  assertInternalReleaseBuildEnvironment,
  sanitizedReleaseBuildEnvironment
} from "./release-build-policy.mjs";
import { materializePublicReleaseRuntimeConfig } from "./public-release-runtime-config.mjs";

const scriptsRoot = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.dirname(scriptsRoot);

function runLocalTool(label, relativeEntry, args, env) {
  const result = spawnSync(process.execPath, [path.join(appRoot, relativeEntry), ...args], {
    cwd: appRoot,
    env,
    stdio: "inherit"
  });
  if (result.error) throw new Error(`${label} could not start: ${result.error.message}`);
  if (result.status !== 0) process.exit(result.status ?? 1);
}

try {
  assertInternalReleaseBuildEnvironment(appRoot, process.env);
  const env = sanitizedReleaseBuildEnvironment();
  runLocalTool("TypeScript build", "node_modules/typescript/bin/tsc", ["-b"], env);
  runLocalTool(
    "Vite production build",
    "node_modules/vite/bin/vite.js",
    ["build", "--mode", "production", "--manifest"],
    env
  );
  materializePublicReleaseRuntimeConfig(appRoot);
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}
