import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { collectCurrentReleaseMatrix } from "./release-matrix-contract.mjs";

// This is a current demo-collection regression test, not a revival of the
// retired lane/capsule/attestation release state machine.
test("the static demo collects all four sealed admin journeys exactly once", () => {
  const contract = JSON.parse(fs.readFileSync(new URL("./release-matrix-contract.json", import.meta.url), "utf8"));
  const current = collectCurrentReleaseMatrix();
  assert.deepEqual(current, contract);
  assert.equal(current.public_required.expected_tests, 106);
  assert.equal(current.downstream_required.expected_tests, 2);
  const cells = current.public_required.cells.filter((cell) => cell.file === "e2e/god-mode.spec.ts");
  assert.equal(cells.length, 4);
  assert.deepEqual(cells.map((cell) => cell.project), Array(4).fill("chromium-desktop"));
  assert.deepEqual(cells.map((cell) => cell.title).sort(), [
    "demo ritual: abrachaindabra opens the sealed 3D plate, near-misses stay search, Escape closes",
    "demo god_mode: opens the Admin Dock honestly unavailable without any admin request",
    "reduced motion › ritual degrades to the 2D twin with identical copy and flow",
    "forced fallback (visual test mode) supports the same ritual and god_mode operations"
  ].map((title) => `god-mode.spec.ts › ${title}`).sort());
  assert.equal(current.public_required.cells.some((cell) => cell.file.includes("downstream/")), false);
  assert.equal(current.downstream_required.cells.some((cell) => cell.file === "e2e/god-mode.spec.ts"), false);
});
