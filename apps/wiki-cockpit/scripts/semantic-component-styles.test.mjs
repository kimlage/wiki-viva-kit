import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const APP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const COMPONENT_ROOT = path.join(APP_ROOT, "src/components");

test("standalone component styles consume the shared semantic theme contract", () => {
  const files = fs.readdirSync(COMPONENT_ROOT)
    .filter((name) => name.endsWith(".css"))
    .sort();
  assert.deepEqual(files, ["pack-workbench.css", "timeline.css"]);

  for (const name of files) {
    const source = fs.readFileSync(path.join(COMPONENT_ROOT, name), "utf8");
    assert.doesNotMatch(
      source,
      /#[0-9a-f]{3,8}\b|rgba?\s*\(/i,
      `${name} must not embed a dark-only color literal outside the theme token definitions`
    );
    assert.doesNotMatch(
      source,
      /var\(--(?:text|surface|overlay-accent)[^)]*\)/,
      `${name} must use the --wiki-* semantic token vocabulary`
    );
    assert.match(source, /var\(--wiki-text\)/);
    assert.match(source, /var\(--wiki-surface/);
    assert.match(source, /var\(--wiki-border\)/);
  }
});
