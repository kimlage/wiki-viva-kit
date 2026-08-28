import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  ARCHITECTURE_POLICY_VERSION,
  collectArchitectureViolations,
  evaluateArchitectureBaseline
} from "./architecture-gate-lib.mjs";

function fixture(files) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "wiki-architecture-gate-"));
  for (const [relative, content] of Object.entries(files)) {
    const target = path.join(root, relative);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, content);
  }
  return root;
}

test("detects component, system, client and state boundary violations", (t) => {
  const root = fixture({
    "src/router.ts": "export function navigate() {}\n",
    "src/data/snapshot.ts": "export function load() {}\n",
    "src/components/Bad.tsx": [
      'import { navigate } from "../router";',
      'import { load } from "../data/snapshot";',
      "export function Bad() { fetch('/api/direct'); window.history.pushState({}, '', '/bad'); navigate(); return load(); }"
    ].join("\n"),
    "src/scene/layout.tsx": 'import React from "react"; export const layout = React;',
    "src/world/state/BadState.ts": "export const read = () => fetch('/api/state');"
  });
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));

  const rules = collectArchitectureViolations(root).map((entry) => entry.ruleId);
  assert.ok(rules.includes("components-no-router-mutation"));
  assert.ok(rules.includes("components-no-transport"));
  assert.ok(rules.filter((rule) => rule === "components-no-transport").length >= 2);
  assert.ok(rules.includes("components-no-direct-history"));
  assert.ok(rules.includes("systems-are-renderer-pure"));
  assert.ok(rules.includes("state-is-pure"));
});

test("a zero-debt baseline passes and a new violation fails", (t) => {
  const root = fixture({
    "src/components/Clean.tsx": "export const Clean = () => null;"
  });
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));

  const current = collectArchitectureViolations(root);
  const baseline = { policyVersion: ARCHITECTURE_POLICY_VERSION, debt: [] };
  assert.equal(evaluateArchitectureBaseline(current, baseline).ok, true);

  fs.mkdirSync(path.join(root, "src/data"), { recursive: true });
  fs.writeFileSync(path.join(root, "src/data/snapshot.ts"), "export function load() {}\n");
  fs.writeFileSync(
    path.join(root, "src/components/New.tsx"),
    'import { load } from "../data/snapshot"; export const New = load;'
  );
  const regression = evaluateArchitectureBaseline(collectArchitectureViolations(root), baseline);
  assert.equal(regression.ok, false);
  assert.equal(regression.regressions.length, 1);
});

test("rejects baseline growth even when a new violation is documented", (t) => {
  const root = fixture({
    "src/data/snapshot.ts": "export function load() {}\n",
    "src/components/Legacy.tsx": 'import { load } from "../data/snapshot"; export const Legacy = load;'
  });
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const current = collectArchitectureViolations(root);
  const baseline = {
    policyVersion: ARCHITECTURE_POLICY_VERSION,
    debt: current.map((entry) => ({
      fingerprint: entry.fingerprint,
      reason: "Attempted new debt.",
      removal: "Later."
    }))
  };
  const result = evaluateArchitectureBaseline(current, baseline);
  assert.equal(result.ok, false);
  assert.ok(result.baselineErrors.some((message) => message.includes("zero-debt")));
});

test("detects transport and router mutation hidden behind transitive facades", (t) => {
  const root = fixture({
    "src/router.ts": "export function navigate() {}\n",
    "src/data/snapshot.ts": "export function load() {}\n",
    "src/facades/operator.ts": 'export { load } from "../data/snapshot";',
    "src/facades/navigation.ts": 'import { navigate } from "../router"; export const go = navigate;',
    "src/components/Bad.tsx": [
      'import { load } from "../facades/operator";',
      'import { go } from "../facades/navigation";',
      "export const Bad = () => { load(); go(); return null; };"
    ].join("\n")
  });
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const violations = collectArchitectureViolations(root);
  assert.ok(violations.some((entry) => entry.ruleId === "components-no-transitive-transport"));
  assert.ok(violations.some((entry) => entry.ruleId === "components-no-transitive-router-mutation"));
});

test("type-only port dependencies do not inherit infrastructure capabilities", (t) => {
  const root = fixture({
    "src/router.ts": "export type Route = { path: string }; export function navigate() {}\n",
    "src/data/snapshot.ts": "export type Payload = { ok: boolean }; export function load() {}\n",
    "src/application/ports.ts": [
      'import type { Route } from "../router";',
      'import type { Payload } from "../data/snapshot";',
      "export type Ports = { route: Route; payload: Payload };"
    ].join("\n"),
    "src/components/Clean.tsx": 'import type { Ports } from "../application/ports"; export const Clean = (_: Ports) => null;'
  });
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  assert.deepEqual(collectArchitectureViolations(root), []);
});

test("resolved debt remains a blocking stale entry until the baseline is updated", (t) => {
  const root = fixture({ "src/components/Clean.tsx": "export const Clean = () => null;" });
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));

  const baseline = {
    policyVersion: ARCHITECTURE_POLICY_VERSION,
    debt: [{
      fingerprint: "components-no-transport|src/components/Old.tsx|import:../data/snapshot:*|1",
      reason: "Old debt.",
      removal: "Remove with the old component."
    }]
  };
  const result = evaluateArchitectureBaseline(collectArchitectureViolations(root), baseline);
  assert.equal(result.ok, false);
  assert.equal(result.staleDebt.length, 1);
});
