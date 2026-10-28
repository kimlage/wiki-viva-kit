import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import test from "node:test";

// Collect the real browser suite; no frozen matrix or certification layer.
test("the static demo collects its four admin journeys and excludes operator tests", () => {
  const report = JSON.parse(execFileSync(process.execPath,
    ["node_modules/@playwright/test/cli.js", "test", "--list", "--reporter=json"],
    { encoding: "utf8", cwd: new URL("../", import.meta.url) }));
  const specs = [];
  function visit(suite) {
    specs.push(...(suite.specs || []));
    for (const child of suite.suites || []) visit(child);
  }
  for (const suite of report.suites) visit(suite);
  assert.deepEqual(report.errors, []);
  assert.equal(specs.filter(s => s.file === "god-mode.spec.ts").length, 4);
  assert.equal(specs.some(s => /(^|[\\/])downstream[\\/]/.test(s.file)), false);
});
