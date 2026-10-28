import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { assertReleaseBuildEnvironment, sanitizedReleaseBuildEnvironment } from "./release-build-policy.mjs";
import { materializePublicReleaseRuntimeConfig } from "./public-release-runtime-config.mjs";

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "wiki-build-safety-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

test("production build rejects app env files and inherited endpoint overrides", t => {
  const root = fixture(t);
  assert.doesNotThrow(() => assertReleaseBuildEnvironment(root, {}));
  for (const name of ["VITE_API_BASE", "NODE_OPTIONS", "WIKI_COCKPIT_PROXY_API"])
    assert.throws(() => assertReleaseBuildEnvironment(root, { [name]: "untrusted" }));
  fs.writeFileSync(path.join(root, ".env.local"), "VITE_API_BASE=untrusted\n");
  assert.throws(() => assertReleaseBuildEnvironment(root, {}), /app-local/);
});

test("build launcher passes only its fixed environment", t => {
  const root = fixture(t);
  const clean = sanitizedReleaseBuildEnvironment();
  assert.doesNotThrow(() => assertReleaseBuildEnvironment(root, clean));
  assert.throws(() => assertReleaseBuildEnvironment(root, { ...clean, VITE_API_BASE: "untrusted" }));
  assert.throws(() => assertReleaseBuildEnvironment(root, { ...clean, PATH: "/untrusted" }));
});

test("static output cannot publish a consumer endpoint or operator configuration", t => {
  const root = fixture(t);
  fs.mkdirSync(path.join(root, "scripts")); fs.mkdirSync(path.join(root, "dist"));
  const source = path.join(root, "scripts/public-release-runtime-config.json");
  const config = JSON.parse(fs.readFileSync(new URL("./public-release-runtime-config.json", import.meta.url)));
  fs.writeFileSync(source, JSON.stringify({ ...config, mode: "operator", api_base: "https://private.invalid" }));
  assert.throws(() => materializePublicReleaseRuntimeConfig(root), /public synthetic/);
  assert.equal(fs.existsSync(path.join(root, "dist/wiki-cockpit.config.json")), false);
  fs.writeFileSync(source, JSON.stringify(config));
  materializePublicReleaseRuntimeConfig(root);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(root, "dist/wiki-cockpit.config.json"))), config);
});
