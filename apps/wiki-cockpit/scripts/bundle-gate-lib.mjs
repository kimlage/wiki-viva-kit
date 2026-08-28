import fs from "node:fs";
import path from "node:path";
import { gzipSync } from "node:zlib";

export const BUNDLE_BUDGETS = Object.freeze({
  initialJsGzipBytes: 300_000,
  lazyChunkGzipBytes: 300_000,
  initialCssBytes: 90_000,
  initialCssGzipBytes: 25_000,
  initialHtmlGzipBytes: 20_000
});

export const REQUIRED_LAZY_CAPABILITIES = Object.freeze([
  { id: "world-runtime", source: "src/components/RuntimeWorldView.tsx" },
  { id: "three-scene", source: "src/components/SystemScene.tsx" },
  { id: "page-reader", source: "src/components/PageReader.tsx" }
]);

export const BLOCKING_BUILD_WARNINGS = Object.freeze([
  {
    id: "ineffective-dynamic-import",
    pattern: /\[INEFFECTIVE_DYNAMIC_IMPORT\]|dynamically imported by[\s\S]*also statically imported by/i,
    remediation: "Make the optional capability exclusively dynamic or exclusively eager; a fake lazy boundary is release-blocking."
  },
  {
    id: "vite-large-chunk",
    pattern: /Some chunks are larger than \d+ kB after minification/i,
    remediation: "Split the capability/route; do not raise chunkSizeWarningLimit."
  }
]);

function toPosix(value) {
  return value.split(path.sep).join("/");
}

function walkFiles(root) {
  if (!fs.existsSync(root)) return [];
  const files = [];
  const pending = [root];
  while (pending.length) {
    const current = pending.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const absolute = path.join(current, entry.name);
      if (entry.isDirectory()) pending.push(absolute);
      else if (entry.isFile()) files.push(absolute);
    }
  }
  return files.sort();
}

function unique(values) {
  return [...new Set(values)];
}

function readArtifact(distRoot, relative) {
  const normalized = relative.replace(/^\/+/, "");
  const absolute = path.resolve(distRoot, normalized);
  const relativeToDist = path.relative(distRoot, absolute);
  if (relativeToDist.startsWith("..") || path.isAbsolute(relativeToDist)) {
    throw new Error(`Bundle manifest artifact escapes dist/: ${relative}`);
  }
  if (!fs.existsSync(absolute) || !fs.statSync(absolute).isFile()) {
    throw new Error(`Bundle manifest references missing artifact: ${relative}`);
  }
  const content = fs.readFileSync(absolute);
  return {
    file: toPosix(normalized),
    bytes: content.byteLength,
    gzipBytes: gzipSync(content, { level: 9 }).byteLength
  };
}

function inlineArtifact(file, content) {
  const bytes = Buffer.from(content, "utf8");
  return {
    file,
    bytes: bytes.byteLength,
    gzipBytes: gzipSync(bytes, { level: 9 }).byteLength
  };
}

function localAsset(value) {
  if (!value || /^(?:[a-z]+:)?\/\//i.test(value) || value.startsWith("data:")) return null;
  return value.replace(/^\/+/, "").split(/[?#]/, 1)[0];
}

function htmlInitialAssets(distRoot) {
  const htmlPath = path.join(distRoot, "index.html");
  if (!fs.existsSync(htmlPath)) throw new Error("Missing dist/index.html from the production build.");
  const html = fs.readFileSync(htmlPath, "utf8");
  const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)];
  const styles = [...html.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)];
  const links = [...html.matchAll(/<link\b([^>]*)>/gi)];
  const externalJs = scripts.flatMap((match) => {
    const src = match[1].match(/\bsrc\s*=\s*["']([^"']+)["']/i)?.[1];
    const asset = localAsset(src);
    return asset?.endsWith(".js") ? [asset] : [];
  });
  const externalCss = links.flatMap((match) => {
    const attrs = match[1];
    const rel = attrs.match(/\brel\s*=\s*["']([^"']+)["']/i)?.[1] ?? "";
    const href = attrs.match(/\bhref\s*=\s*["']([^"']+)["']/i)?.[1];
    const asset = localAsset(href);
    return /(?:^|\s)stylesheet(?:\s|$)/i.test(rel) && asset?.endsWith(".css") ? [asset] : [];
  });
  const inlineJs = scripts
    .filter((match) => !/\bsrc\s*=/i.test(match[1]))
    .map((match, index) => inlineArtifact(`index.html#inline-script-${index + 1}`, match[2]));
  const inlineCss = styles.map((match, index) => inlineArtifact(`index.html#inline-style-${index + 1}`, match[1]));
  return {
    html: inlineArtifact("index.html", html),
    externalJs,
    externalCss,
    inlineJs,
    inlineCss
  };
}

function initialManifestKeys(manifest, entryKeys) {
  const visited = new Set();
  const pending = [...entryKeys];
  while (pending.length) {
    const key = pending.pop();
    if (visited.has(key)) continue;
    const record = manifest[key];
    if (!record) throw new Error(`Bundle manifest imports missing record: ${key}`);
    visited.add(key);
    for (const imported of record.imports ?? []) pending.push(imported);
  }
  return visited;
}

function sum(records, field) {
  return records.reduce((total, record) => total + record[field], 0);
}

function dynamicReachableKeys(manifest, initialKeys) {
  const visited = new Set();
  const dynamic = new Set();
  const pending = [...initialKeys];
  while (pending.length) {
    const key = pending.pop();
    if (visited.has(key)) continue;
    visited.add(key);
    const record = manifest[key];
    if (!record) continue;
    for (const imported of record.imports ?? []) pending.push(imported);
    for (const imported of record.dynamicImports ?? []) {
      dynamic.add(imported);
      pending.push(imported);
    }
  }
  return dynamic;
}

export function analyzeBundle(distRoot) {
  const manifestPath = path.join(distRoot, ".vite", "manifest.json");
  if (!fs.existsSync(manifestPath)) {
    throw new Error("Missing dist/.vite/manifest.json. The production build must run with Vite --manifest.");
  }

  let manifest;
  try {
    manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  } catch (error) {
    throw new Error(`Invalid Vite manifest JSON: ${error instanceof Error ? error.message : String(error)}`);
  }
  if (!manifest || Array.isArray(manifest) || typeof manifest !== "object") {
    throw new Error("Vite manifest must be an object keyed by source/chunk ID.");
  }

  const entryKeys = Object.entries(manifest)
    .filter(([, record]) => record && record.isEntry === true)
    .map(([key]) => key);
  if (entryKeys.length === 0) throw new Error("Vite manifest has no production entry chunk.");

  const initialKeys = initialManifestKeys(manifest, entryKeys);
  const htmlAssets = htmlInitialAssets(distRoot);
  const initialJsFiles = unique([
    [...initialKeys]
      .map((key) => manifest[key]?.file)
      .filter((file) => typeof file === "string" && file.endsWith(".js")),
    htmlAssets.externalJs
  ].flat());
  const initialCssFiles = unique([
    [...initialKeys].flatMap((key) =>
      Array.isArray(manifest[key]?.css) ? manifest[key].css.filter((file) => typeof file === "string") : []
    ),
    htmlAssets.externalCss
  ].flat());

  if (initialJsFiles.length === 0) throw new Error("Vite manifest entry graph has no JavaScript artifact.");

  const allJsFiles = unique([
    ...Object.values(manifest)
      .map((record) => record?.file)
      .filter((file) => typeof file === "string" && file.endsWith(".js")),
    ...walkFiles(distRoot)
      .map((absolute) => toPosix(path.relative(distRoot, absolute)))
      .filter((file) => file.endsWith(".js"))
  ]);

  const initialJs = [...initialJsFiles.map((file) => readArtifact(distRoot, file)), ...htmlAssets.inlineJs];
  const initialCss = [...initialCssFiles.map((file) => readArtifact(distRoot, file)), ...htmlAssets.inlineCss];
  const initialSet = new Set(initialJsFiles);
  const lazyJs = allJsFiles
    .filter((file) => !initialSet.has(file))
    .map((file) => readArtifact(distRoot, file))
    .sort((left, right) => right.gzipBytes - left.gzipBytes || left.file.localeCompare(right.file));

  return {
    manifestPath: toPosix(path.relative(distRoot, manifestPath)),
    manifest,
    entries: entryKeys,
    initialKeys: [...initialKeys],
    dynamicKeys: [...dynamicReachableKeys(manifest, initialKeys)],
    html: htmlAssets.html,
    initialJs,
    initialCss,
    lazyJs,
    totals: {
      initialJsBytes: sum(initialJs, "bytes"),
      initialJsGzipBytes: sum(initialJs, "gzipBytes"),
      initialCssBytes: sum(initialCss, "bytes"),
      initialCssGzipBytes: sum(initialCss, "gzipBytes"),
      initialHtmlBytes: htmlAssets.html.bytes,
      initialHtmlGzipBytes: htmlAssets.html.gzipBytes
    }
  };
}

export function inspectBundleGateArguments(args) {
  return args.includes("--skip-build")
    ? [{
        id: "skip-build-forbidden",
        detail: "--skip-build is forbidden: a bundle verdict must follow a build from the current source, never a potentially stale dist directory."
      }]
    : [];
}

export function findBlockingBuildWarnings(buildOutput) {
  return BLOCKING_BUILD_WARNINGS
    .filter((warning) => warning.pattern.test(buildOutput))
    .map(({ id, remediation }) => ({ id, remediation }));
}

export function inspectBundleBuildConfiguration(appRoot) {
  const configCandidates = ["vite.config.ts", "vite.config.js", "vite.config.mjs", "vite.config.cjs"];
  const configFile = configCandidates.map((candidate) => path.join(appRoot, candidate)).find((candidate) => fs.existsSync(candidate));
  if (!configFile) return [];
  const source = fs.readFileSync(configFile, "utf8");
  const violations = [];
  const threshold = source.match(/chunkSizeWarningLimit\s*:\s*([\d.]+)/);
  if (threshold && Number(threshold[1]) > 500) {
    violations.push({
      id: "raised-chunk-warning-limit",
      detail: `Vite chunkSizeWarningLimit is ${threshold[1]} kB; v8 forbids hiding oversized chunks by raising the default 500 kB warning.`
    });
  } else if (/chunkSizeWarningLimit\s*:/.test(source) && !threshold) {
    violations.push({
      id: "dynamic-chunk-warning-limit",
      detail: "Vite chunkSizeWarningLimit is not a numeric literal, so the gate cannot prove that oversized-chunk warnings remain active."
    });
  }
  if (/logLevel\s*:\s*["']silent["']/.test(source)) {
    violations.push({
      id: "silenced-build-log",
      detail: "Vite logLevel is silent; build warnings must remain visible and blocking."
    });
  }
  return violations;
}

export function evaluateBundle(report, options = {}) {
  const budgets = { ...BUNDLE_BUDGETS, ...(options.budgets ?? {}) };
  const warnings = findBlockingBuildWarnings(options.buildOutput ?? "");
  const violations = [];

  if (report.totals.initialJsGzipBytes > budgets.initialJsGzipBytes) {
    violations.push({
      id: "initial-js-gzip",
      actual: report.totals.initialJsGzipBytes,
      budget: budgets.initialJsGzipBytes,
      detail: "Initial world-shell JavaScript exceeds the transfer budget."
    });
  }
  if (report.totals.initialCssBytes > budgets.initialCssBytes) {
    violations.push({
      id: "initial-css-minified",
      actual: report.totals.initialCssBytes,
      budget: budgets.initialCssBytes,
      detail: "Initial shell CSS exceeds the minified budget."
    });
  }
  if (report.totals.initialCssGzipBytes > budgets.initialCssGzipBytes) {
    violations.push({
      id: "initial-css-gzip",
      actual: report.totals.initialCssGzipBytes,
      budget: budgets.initialCssGzipBytes,
      detail: "Initial shell CSS exceeds the transfer budget."
    });
  }
  if (report.totals.initialHtmlGzipBytes > budgets.initialHtmlGzipBytes) {
    violations.push({
      id: "initial-html-gzip",
      actual: report.totals.initialHtmlGzipBytes,
      budget: budgets.initialHtmlGzipBytes,
      detail: "Initial HTML exceeds the transfer budget; inline script/style bytes are also charged to their JS/CSS budgets."
    });
  }
  for (const chunk of report.lazyJs) {
    if (chunk.gzipBytes > budgets.lazyChunkGzipBytes) {
      violations.push({
        id: "lazy-js-gzip",
        file: chunk.file,
        actual: chunk.gzipBytes,
        budget: budgets.lazyChunkGzipBytes,
        detail: "A single lazy/worker JavaScript chunk exceeds the transfer budget."
      });
    }
  }
  for (const warning of warnings) {
    violations.push({
      id: `build-warning:${warning.id}`,
      detail: warning.remediation
    });
  }
  for (const configuration of options.configurationViolations ?? []) {
    violations.push({ id: `build-config:${configuration.id}`, detail: configuration.detail });
  }
  const initialKeys = new Set(report.initialKeys ?? []);
  const dynamicKeys = new Set(report.dynamicKeys ?? []);
  const initialFiles = new Set((report.initialJs ?? []).map((entry) => entry.file));
  for (const capability of options.requiredLazyCapabilities ?? REQUIRED_LAZY_CAPABILITIES) {
    const record = report.manifest?.[capability.source];
    if (!record) {
      violations.push({
        id: `lazy-capability:${capability.id}:missing`,
        detail: `Required lazy capability '${capability.source}' is absent from the production manifest.`
      });
      continue;
    }
    if (initialKeys.has(capability.source) || initialFiles.has(record.file) || record.isDynamicEntry !== true) {
      violations.push({
        id: `lazy-capability:${capability.id}:eager`,
        file: record.file,
        detail: `Required capability '${capability.source}' is not an exclusive dynamic entry.`
      });
    }
    if (!dynamicKeys.has(capability.source)) {
      violations.push({
        id: `lazy-capability:${capability.id}:unreachable`,
        file: record.file,
        detail: `Required capability '${capability.source}' is not reachable through a dynamic import from the production entry.`
      });
    }
  }

  return { ok: violations.length === 0, budgets, violations, warnings };
}

export function formatBytes(bytes) {
  return `${(bytes / 1000).toFixed(2)} kB`;
}
