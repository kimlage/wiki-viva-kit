import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  analyzeBundle,
  evaluateBundle,
  findBlockingBuildWarnings,
  inspectBundleGateArguments,
  inspectBundleBuildConfiguration
} from "./bundle-gate-lib.mjs";

function fixture({ manifest, files }) {
  const dist = fs.mkdtempSync(path.join(os.tmpdir(), "wiki-bundle-gate-"));
  fs.mkdirSync(path.join(dist, ".vite"), { recursive: true });
  fs.writeFileSync(path.join(dist, ".vite", "manifest.json"), JSON.stringify(manifest));
  if (!("index.html" in files)) fs.writeFileSync(path.join(dist, "index.html"), "<!doctype html><div id=\"root\"></div>");
  for (const [relative, content] of Object.entries(files)) {
    const target = path.join(dist, relative);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, content);
  }
  return dist;
}

test("measures the real entry import graph, CSS and lazy chunks from a Vite manifest", (t) => {
  const dist = fixture({
    manifest: {
      "src/main.tsx": {
        file: "assets/main.js",
        isEntry: true,
        imports: ["_vendor.js"],
        dynamicImports: ["src/reader.tsx"],
        css: ["assets/main.css"]
      },
      "_vendor.js": { file: "assets/vendor.js" },
      "src/reader.tsx": { file: "assets/reader.js", isDynamicEntry: true }
    },
    files: {
      "assets/main.js": "export const main = true;",
      "assets/vendor.js": "export const vendor = true;",
      "assets/reader.js": "export const reader = true;",
      "assets/main.css": ".shell{display:block}"
    }
  });
  t.after(() => fs.rmSync(dist, { recursive: true, force: true }));

  const report = analyzeBundle(dist);
  assert.deepEqual(report.initialJs.map((entry) => entry.file).sort(), ["assets/main.js", "assets/vendor.js"]);
  assert.deepEqual(report.initialCss.map((entry) => entry.file), ["assets/main.css"]);
  assert.deepEqual(report.lazyJs.map((entry) => entry.file), ["assets/reader.js"]);
  assert.equal(evaluateBundle(report, { requiredLazyCapabilities: [] }).ok, true);
});

test("fails every explicit size budget independently", (t) => {
  const dist = fixture({
    manifest: {
      "src/main.tsx": { file: "assets/main.js", isEntry: true, css: ["assets/main.css"] },
      "src/lazy.ts": { file: "assets/lazy.js", isDynamicEntry: true }
    },
    files: {
      "assets/main.js": "main-shell-payload",
      "assets/lazy.js": "lazy-capability-payload",
      "assets/main.css": ".shell{color:rebeccapurple}"
    }
  });
  t.after(() => fs.rmSync(dist, { recursive: true, force: true }));

  const report = analyzeBundle(dist);
  const result = evaluateBundle(report, {
    requiredLazyCapabilities: [],
    budgets: {
      initialJsGzipBytes: 1,
      lazyChunkGzipBytes: 1,
      initialCssBytes: 1,
      initialCssGzipBytes: 1
    }
  });
  assert.equal(result.ok, false);
  assert.deepEqual(
    result.violations.map((entry) => entry.id).sort(),
    ["initial-css-gzip", "initial-css-minified", "initial-js-gzip", "lazy-js-gzip"]
  );
});

test("charges inline script/style and transitively imported CSS to initial budgets", (t) => {
  const dist = fixture({
    manifest: {
      "src/main.tsx": { file: "assets/main.js", isEntry: true, imports: ["_vendor.js"], css: ["assets/main.css"] },
      "_vendor.js": { file: "assets/vendor.js", css: ["assets/vendor.css"] }
    },
    files: {
      "index.html": '<!doctype html><style>.inline{color:red}</style><script>window.__boot=true</script><script type="module" src="/assets/main.js"></script>',
      "assets/main.js": "export const main = true;",
      "assets/vendor.js": "export const vendor = true;",
      "assets/main.css": ".shell{display:block}",
      "assets/vendor.css": ".vendor{display:block}"
    }
  });
  t.after(() => fs.rmSync(dist, { recursive: true, force: true }));
  const report = analyzeBundle(dist);
  assert.deepEqual(
    report.initialCss.map((entry) => entry.file).sort(),
    ["assets/main.css", "assets/vendor.css", "index.html#inline-style-1"]
  );
  assert.ok(report.initialJs.some((entry) => entry.file === "index.html#inline-script-1"));
  assert.ok(report.totals.initialHtmlGzipBytes > 0);
  const result = evaluateBundle(report, {
    requiredLazyCapabilities: [],
    budgets: { initialCssBytes: 1 }
  });
  assert.ok(result.violations.some((entry) => entry.id === "initial-css-minified"));
});

test("requires world, scene and reader capabilities to be exclusive reachable dynamic entries", (t) => {
  const dist = fixture({
    manifest: {
      "src/main.tsx": {
        file: "assets/main.js",
        isEntry: true,
        dynamicImports: ["src/components/RuntimeWorldView.tsx"]
      },
      "src/components/RuntimeWorldView.tsx": {
        file: "assets/world.js",
        isDynamicEntry: true,
        dynamicImports: ["src/components/SystemScene.tsx", "src/components/PageReader.tsx"]
      },
      "src/components/SystemScene.tsx": { file: "assets/scene.js", isDynamicEntry: true },
      "src/components/PageReader.tsx": { file: "assets/reader.js", isDynamicEntry: true }
    },
    files: {
      "assets/main.js": "main",
      "assets/world.js": "world",
      "assets/scene.js": "scene",
      "assets/reader.js": "reader"
    }
  });
  t.after(() => fs.rmSync(dist, { recursive: true, force: true }));
  assert.equal(evaluateBundle(analyzeBundle(dist)).ok, true);
});

test("blocks missing, eager and unreachable mandatory capability chunks", (t) => {
  const dist = fixture({
    manifest: {
      "src/main.tsx": {
        file: "assets/main.js",
        isEntry: true,
        imports: ["src/components/SystemScene.tsx"],
        dynamicImports: ["src/components/RuntimeWorldView.tsx"]
      },
      "src/components/RuntimeWorldView.tsx": { file: "assets/world.js", isDynamicEntry: true },
      "src/components/SystemScene.tsx": { file: "assets/scene.js", isDynamicEntry: true },
      "src/components/PageReader.tsx": { file: "assets/reader.js", isDynamicEntry: true }
    },
    files: {
      "assets/main.js": "main",
      "assets/world.js": "world",
      "assets/scene.js": "scene",
      "assets/reader.js": "reader"
    }
  });
  t.after(() => fs.rmSync(dist, { recursive: true, force: true }));
  const result = evaluateBundle(analyzeBundle(dist), {
    requiredLazyCapabilities: [
      { id: "missing", source: "src/components/Missing.tsx" },
      { id: "three-scene", source: "src/components/SystemScene.tsx" },
      { id: "page-reader", source: "src/components/PageReader.tsx" }
    ]
  });
  assert.deepEqual(
    result.violations.filter((entry) => entry.id.startsWith("lazy-capability:")).map((entry) => entry.id).sort(),
    [
      "lazy-capability:missing:missing",
      "lazy-capability:page-reader:unreachable",
      "lazy-capability:three-scene:eager",
      "lazy-capability:three-scene:unreachable"
    ]
  );
});

test("forbids skip-build because dist may be stale", () => {
  assert.deepEqual(inspectBundleGateArguments([]), []);
  assert.deepEqual(inspectBundleGateArguments(["--skip-build"]).map((entry) => entry.id), ["skip-build-forbidden"]);
});

test("treats ineffective imports and Vite oversized-chunk warnings as blockers", () => {
  const output = [
    "[INEFFECTIVE_DYNAMIC_IMPORT] src/data/snapshot.ts is dynamically imported",
    "(!) Some chunks are larger than 500 kB after minification."
  ].join("\n");
  assert.deepEqual(
    findBlockingBuildWarnings(output).map((entry) => entry.id),
    ["ineffective-dynamic-import", "vite-large-chunk"]
  );
});

test("refuses to infer budgets from an unmanifested dist directory", (t) => {
  const dist = fs.mkdtempSync(path.join(os.tmpdir(), "wiki-bundle-gate-no-manifest-"));
  t.after(() => fs.rmSync(dist, { recursive: true, force: true }));
  assert.throws(() => analyzeBundle(dist), /production build must run with Vite --manifest/);
});

test("rejects attempts to hide Vite chunk warnings by configuration", (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "wiki-bundle-config-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.writeFileSync(
    path.join(root, "vite.config.ts"),
    "export default { build: { chunkSizeWarningLimit: 2500 }, logLevel: 'silent' };"
  );
  assert.deepEqual(
    inspectBundleBuildConfiguration(root).map((entry) => entry.id),
    ["raised-chunk-warning-limit", "silenced-build-log"]
  );
});
