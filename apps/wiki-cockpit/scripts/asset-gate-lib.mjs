import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

export const ASSET_MANIFEST_SCHEMA = "wiki_cockpit_asset_manifest.v1";

const REQUIRED_ASSET_ROOTS = ["public", "src/assets"];
const APPROVED_LICENSES = new Set([
  "Apache-2.0",
  "BSD-3-Clause",
  "CC-BY-4.0",
  "CC0-1.0",
  "ISC",
  "MIT",
  "OFL-1.1"
]);
const LICENSE_MARKERS = Object.freeze({
  "Apache-2.0": ["Apache License", "Version 2.0"],
  "BSD-3-Clause": ["Redistribution and use in source and binary forms"],
  "CC-BY-4.0": ["Creative Commons Attribution 4.0"],
  "CC0-1.0": ["CC0 1.0 Universal"],
  ISC: ["ISC License", "Permission to use, copy, modify"],
  MIT: ["MIT License", "Permission is hereby granted"],
  "OFL-1.1": ["SIL OPEN FONT LICENSE", "Version 1.1"]
});
const POLICY_CEILINGS = {
  max_asset_count: 128,
  max_total_bytes: 5 * 1024 * 1024,
  max_single_asset_bytes: 1024 * 1024
};
const ASSET_EXTENSIONS = new Set([
  ".avif", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp",
  ".eot", ".otf", ".ttf", ".woff", ".woff2",
  ".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav",
  ".mp4", ".m4v", ".mov", ".webm",
  ".glb", ".gltf", ".hdr"
]);
const KIND_EXTENSIONS = {
  image: new Set([".avif", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp", ".hdr"]),
  font: new Set([".eot", ".otf", ".ttf", ".woff", ".woff2"]),
  audio: new Set([".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav"]),
  video: new Set([".mp4", ".m4v", ".mov", ".webm"]),
  model: new Set([".glb", ".gltf"])
};
const SOURCE_EXTENSIONS = new Set([".css", ".html", ".js", ".jsx", ".mjs", ".ts", ".tsx"]);
const ICON_PACKAGE_PATTERNS = [
  /^react-icons(?:\/|$)/,
  /^@heroicons(?:\/|$)/,
  /^@fortawesome(?:\/|$)/,
  /^@phosphor-icons(?:\/|$)/,
  /^phosphor-react(?:\/|$)/,
  /^@tabler\/icons(?:\/|$)/,
  /^iconoir-react(?:\/|$)/
];

function toPosix(value) {
  return value.split(path.sep).join("/");
}

function exactKeys(value, expected) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const actual = Object.keys(value).sort();
  return actual.length === expected.length && actual.every((key, index) => key === [...expected].sort()[index]);
}

function isSafeRelative(value) {
  if (typeof value !== "string" || !value || path.isAbsolute(value) || value.includes("\\")) return false;
  const normalized = path.posix.normalize(value);
  return normalized === value && normalized !== ".." && !normalized.startsWith("../");
}

function isWithin(root, target) {
  const relative = path.relative(root, target);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
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
      else if (entry.isFile() || entry.isSymbolicLink()) files.push(absolute);
    }
  }
  return files.sort();
}

function sha256(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function assetExtension(value) {
  const withoutSuffix = value.split(/[?#]/, 1)[0].toLowerCase();
  const extension = path.posix.extname(withoutSuffix);
  return ASSET_EXTENSIONS.has(extension) ? extension : null;
}

function sourceFiles(appRoot) {
  const files = walkFiles(path.join(appRoot, "src"))
    .filter((file) => SOURCE_EXTENSIONS.has(path.extname(file)))
    .filter((file) => !/\.(?:test|spec|stories)\.[cm]?[jt]sx?$/.test(file));
  const index = path.join(appRoot, "index.html");
  if (fs.existsSync(index)) files.push(index);
  return files.sort();
}

function classifyReference(raw, sourceFile, appRoot, forceLocal = false) {
  const reference = String(raw || "").trim().replace(/^['"]|['"]$/g, "");
  if (!reference || reference.startsWith("#")) return null;
  if (/^(?:https?:)?\/\//i.test(reference)) return { kind: "hotlink", reference };
  if (/^(?:data|blob):/i.test(reference)) return { kind: "inline", reference: reference.slice(0, 64) };
  if (!forceLocal && !assetExtension(reference)) return null;
  const clean = reference.split(/[?#]/, 1)[0];
  const absolute = clean.startsWith("/")
    ? path.join(appRoot, "public", clean.slice(1))
    : path.resolve(path.dirname(sourceFile), clean);
  if (!isWithin(appRoot, absolute)) return { kind: "unsafe", reference };
  return { kind: "local", reference, path: toPosix(path.relative(appRoot, absolute)) };
}

function pushReference(target, raw, file, line, appRoot, forceLocal = false) {
  const classified = classifyReference(raw, file, appRoot, forceLocal);
  if (classified) target.push({ ...classified, file: toPosix(path.relative(appRoot, file)), line });
}

function lineNumber(text, index) {
  return text.slice(0, index).split("\n").length;
}

function collectReferences(appRoot) {
  const references = [];
  const iconImports = [];
  const assetSuffix = "(?:avif|gif|jpe?g|png|svg|webp|eot|otf|ttf|woff2?|aac|flac|m4a|mp3|ogg|wav|mp4|m4v|mov|webm|glb|gltf|hdr)";
  for (const file of sourceFiles(appRoot)) {
    const text = fs.readFileSync(file, "utf8");
    const extension = path.extname(file);

    if (extension === ".css") {
      for (const match of text.matchAll(/\burl\(\s*([^)]+?)\s*\)/gi)) {
        pushReference(references, match[1], file, lineNumber(text, match.index), appRoot, true);
      }
      for (const match of text.matchAll(/@import\s+["']([^"']+)["']/gi)) {
        const value = match[1];
        if (/^(?:https?:)?\/\//i.test(value) || /^(?:data|blob):/i.test(value)) {
          pushReference(references, value, file, lineNumber(text, match.index), appRoot);
        }
      }
    }

    if (extension === ".html") {
      for (const match of text.matchAll(/<(img|source|audio|video|script|link)\b([^>]*)>/gi)) {
        const tag = match[1].toLowerCase();
        const attributes = match[2];
        const rel = attributes.match(/\brel\s*=\s*["']([^"']+)["']/i)?.[1] || "";
        const attributeNames = tag === "link" && /(?:icon|stylesheet|preload|prefetch)/i.test(rel)
          ? ["href"]
          : tag === "video"
            ? ["src", "poster"]
            : tag === "link"
              ? []
              : ["src", "srcset"];
        for (const name of attributeNames) {
          const value = attributes.match(new RegExp(`\\b${name}\\s*=\\s*["']([^"']+)["']`, "i"))?.[1];
          if (!value) continue;
          for (const candidate of name === "srcset" ? value.split(",").map((item) => item.trim().split(/\s+/, 1)[0]) : [value]) {
            pushReference(references, candidate, file, lineNumber(text, match.index), appRoot, ["img", "source", "audio", "video"].includes(tag));
          }
        }
      }
      for (const match of text.matchAll(/\bstyle\s*=\s*["']([^"']+)["']/gi)) {
        const style = match[1];
        for (const urlMatch of style.matchAll(/\burl\(\s*([^)]+?)\s*\)/gi)) {
          pushReference(references, urlMatch[1], file, lineNumber(text, match.index), appRoot, true);
        }
        for (const importMatch of style.matchAll(/@import\s+["']([^"']+)["']/gi)) {
          pushReference(references, importMatch[1], file, lineNumber(text, match.index), appRoot);
        }
      }
    }

    if ([".js", ".jsx", ".mjs", ".ts", ".tsx"].includes(extension)) {
      for (const match of text.matchAll(/(?:import|export)\s+(?:[^"']*?\s+from\s+)?["']([^"']+)["']/g)) {
        const specifier = match[1];
        if (specifier === "lucide-react" || ICON_PACKAGE_PATTERNS.some((pattern) => pattern.test(specifier))) {
          iconImports.push({ package: specifier, file: toPosix(path.relative(appRoot, file)), line: lineNumber(text, match.index) });
        }
        if (assetExtension(specifier)) pushReference(references, specifier, file, lineNumber(text, match.index), appRoot);
      }
      const literalAsset = new RegExp(`["'\\x60]([^"'\\x60\\n]*?\\.${assetSuffix}(?:[?#][^"'\\x60\\n]*)?)["'\\x60]`, "gi");
      for (const match of text.matchAll(literalAsset)) {
        pushReference(references, match[1], file, lineNumber(text, match.index), appRoot);
      }
      const externalAsset = new RegExp(`(?:https?:)?//[^\\s"'\\x60)]+?\\.${assetSuffix}(?:[?#][^\\s"'\\x60)]*)?`, "gi");
      for (const match of text.matchAll(externalAsset)) {
        pushReference(references, match[0], file, lineNumber(text, match.index), appRoot);
      }
      for (const match of text.matchAll(/(?:data|blob):(image|font|audio|video)\/[a-z0-9.+-]+/gi)) {
        pushReference(references, match[0], file, lineNumber(text, match.index), appRoot);
      }
      for (const match of text.matchAll(/\b(?:src|poster|srcSet)\s*=\s*(?:["']([^"']+)["']|\{\s*["'`]([^"'`]+)["'`]\s*\})/g)) {
        pushReference(references, match[1] || match[2], file, lineNumber(text, match.index), appRoot, true);
      }
      for (const match of text.matchAll(/\burl\(\s*([^)]+?)\s*\)/g)) {
        pushReference(references, match[1], file, lineNumber(text, match.index), appRoot, true);
      }
    }
  }
  const uniqueReferences = [...new Map(references.map((item) => [`${item.file}:${item.line}:${item.kind}:${item.reference}`, item])).values()];
  const uniqueImports = [...new Map(iconImports.map((item) => [`${item.file}:${item.line}:${item.package}`, item])).values()];
  return { references: uniqueReferences, iconImports: uniqueImports };
}

function push(errors, code, detail) {
  errors.push({ code, detail });
}

function readJson(file, errors, label) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    push(errors, `${label}_unreadable`, error instanceof Error ? error.message : String(error));
    return null;
  }
}

function svgSafetyErrors(file) {
  let text;
  try {
    text = fs.readFileSync(file, "utf8");
  } catch {
    return ["invalid_svg"];
  }
  const errors = [];
  if (!/<svg\b/i.test(text) || /<!DOCTYPE|<!ENTITY/i.test(text)) errors.push("invalid_svg");
  if (/<\s*(?:script|foreignObject|iframe|object|embed)\b/i.test(text)) errors.push("active_svg");
  // Backslashes and XML character/entity references introduce pre-render
  // decoding grammars (CSS escapes and XML entities). This gate does not try
  // to emulate both parsers: manifested SVG containing either is rejected.
  if (/[\\&]/.test(text)) errors.push("active_svg");
  // Manifested SVG is deliberately presentation-only. CSS is not parsed here,
  // so accepting <style> or style= would make every CSS escape/entity form a
  // second URL grammar that a regex denylist cannot normalize safely. SMIL and
  // other timed/control elements are excluded for the same fail-closed reason.
  if (/<\s*style\b|\sstyle\s*=|<\s*(?:animate(?:Motion|Transform)?|set|discard)\b/i.test(text)) {
    errors.push("active_svg");
  }
  if (/\son[a-z0-9_-]+\s*=/i.test(text)) errors.push("active_svg");
  const withoutStandardNamespaces = text.replace(
    /\sxmlns(?::xlink)?\s*=\s*["']http:\/\/www\.w3\.org\/(?:2000\/svg|1999\/xlink)["']/gi,
    ""
  );
  if (
    /<\s*\/?\s*[A-Za-z_][A-Za-z0-9_.-]*:/i.test(withoutStandardNamespaces) ||
    /\s[A-Za-z_][A-Za-z0-9_.-]*:[A-Za-z_][A-Za-z0-9_.-]*\s*=/i.test(withoutStandardNamespaces)
  ) {
    errors.push("active_svg");
  }
  if (/(?:javascript\s*:|data\s*:|https?\s*:|(?<!:)\/\/|@import|url\s*\()/i.test(withoutStandardNamespaces)) {
    errors.push("active_svg");
  }
  for (const match of text.matchAll(/(?:\b|:)\b(?:href|src)\s*=\s*["']([^"']+)["']/gi)) {
    // Only a literal local fragment is safe. Numeric/named entities are not
    // accepted because an XML consumer resolves them before fetching.
    if (match[1] && !/^#[A-Za-z_][A-Za-z0-9_.:-]*$/.test(match[1])) {
      errors.push("remote_svg_reference");
    }
  }
  return [...new Set(errors)];
}

export function evaluateAssetManifest({ appRoot, manifestPath, schemaPath } = {}) {
  const errors = [];
  const resolvedAppRoot = path.resolve(appRoot || process.cwd());
  const resolvedManifest = path.resolve(manifestPath || path.join(resolvedAppRoot, "assets/manifest.v1.json"));
  const resolvedSchema = path.resolve(schemaPath || path.join(resolvedAppRoot, "assets/manifest.v1.schema.json"));
  const repoRoot = path.resolve(resolvedAppRoot, "../..");
  const appRootReal = fs.realpathSync(resolvedAppRoot);
  const repoRootReal = fs.realpathSync(repoRoot);
  const manifest = readJson(resolvedManifest, errors, "manifest");
  const schema = readJson(resolvedSchema, errors, "schema");
  if (!manifest || !schema) return { ok: false, errors, summary: null };

  if (schema?.properties?.schema_version?.const !== ASSET_MANIFEST_SCHEMA) {
    push(errors, "schema_contract_mismatch", "schema must pin the same v1 schema_version as the gate");
  }
  if (!exactKeys(manifest, ["schema_version", "policy", "external_assets", "icon_dependencies", "assets"])) {
    push(errors, "manifest_shape", "manifest has missing or unknown top-level fields");
  }
  if (manifest.schema_version !== ASSET_MANIFEST_SCHEMA) {
    push(errors, "schema_version", `expected ${ASSET_MANIFEST_SCHEMA}`);
  }

  const policy = manifest.policy;
  if (!exactKeys(policy, ["allowed_asset_roots", "allowed_spdx", "hotlinks", "inline_data_assets", "budgets"])) {
    push(errors, "policy_shape", "policy has missing or unknown fields");
  }
  const roots = Array.isArray(policy?.allowed_asset_roots) ? policy.allowed_asset_roots : [];
  if (JSON.stringify(roots) !== JSON.stringify(REQUIRED_ASSET_ROOTS)) {
    push(errors, "asset_roots", `allowed_asset_roots must be exactly ${REQUIRED_ASSET_ROOTS.join(", ")}`);
  }
  const allowedSpdx = Array.isArray(policy?.allowed_spdx) ? policy.allowed_spdx : [];
  if (!allowedSpdx.length || new Set(allowedSpdx).size !== allowedSpdx.length || allowedSpdx.some((item) => !APPROVED_LICENSES.has(item))) {
    push(errors, "license_allowlist", "allowed_spdx must be unique and limited to the gate-approved SPDX set");
  }
  if (policy?.hotlinks !== "forbidden") push(errors, "hotlink_policy", "hotlinks must be forbidden");
  if (policy?.inline_data_assets !== "forbidden") push(errors, "inline_policy", "inline data/blob assets must be forbidden");

  const budgets = policy?.budgets;
  if (!exactKeys(budgets, ["max_asset_count", "max_total_bytes", "max_single_asset_bytes"])) {
    push(errors, "budget_shape", "global budgets have missing or unknown fields");
  }
  for (const [name, ceiling] of Object.entries(POLICY_CEILINGS)) {
    const value = budgets?.[name];
    if (!Number.isInteger(value) || value < 0 || value > ceiling) {
      push(errors, "budget_policy", `${name} must be an integer between 0 and ${ceiling}`);
    }
  }

  const external = manifest.external_assets;
  if (!exactKeys(external, ["state", "declared_count"])) push(errors, "external_shape", "external_assets has missing or unknown fields");
  if (!Number.isInteger(external?.declared_count) || external.declared_count < 0) push(errors, "external_count", "declared_count must be a non-negative integer");
  if (!["none", "present"].includes(external?.state)) push(errors, "external_state", "state must be none or present");

  const iconDependencies = Array.isArray(manifest.icon_dependencies) ? manifest.icon_dependencies : [];
  const iconDependency = iconDependencies[0];
  if (iconDependencies.length !== 1 || !exactKeys(iconDependency, ["package", "version", "classification", "vendored", "lock_integrity", "license"])) {
    push(errors, "icon_dependencies", "icon_dependencies must declare exactly the Lucide runtime dependency");
  } else if (
    iconDependency.package !== "lucide-react" ||
    iconDependency.classification !== "runtime_component_dependency" ||
    iconDependency.vendored !== false ||
    typeof iconDependency.version !== "string" ||
    !/^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/.test(iconDependency.version) ||
    typeof iconDependency.lock_integrity !== "string" ||
    !/^sha512-[A-Za-z0-9+/]+={0,2}$/.test(iconDependency.lock_integrity) ||
    !exactKeys(iconDependency.license, ["spdx", "file", "sha256"]) ||
    iconDependency.license.spdx !== "ISC" ||
    !/^[a-f0-9]{64}$/.test(iconDependency.license.sha256 || "")
  ) {
    push(errors, "icon_dependency_contract", "Lucide must be a version-, integrity- and ISC-license-bound non-vendored runtime dependency");
  }
  const packageJson = readJson(path.join(resolvedAppRoot, "package.json"), errors, "package_json");
  const packageLock = readJson(path.join(resolvedAppRoot, "package-lock.json"), errors, "package_lock");
  const rootLockDependency = packageLock?.packages?.[""]?.dependencies?.["lucide-react"];
  const installedLockDependency = packageLock?.packages?.["node_modules/lucide-react"];
  if (
    !iconDependency ||
    packageJson?.dependencies?.["lucide-react"] !== iconDependency.version ||
    rootLockDependency !== iconDependency.version
  ) {
    push(errors, "lucide_dependency", "package.json and the lock root must pin the exact manifested lucide-react version");
  }
  if (
    !iconDependency ||
    installedLockDependency?.version !== iconDependency.version ||
    installedLockDependency?.integrity !== iconDependency.lock_integrity ||
    installedLockDependency?.license !== iconDependency.license?.spdx
  ) {
    push(errors, "lucide_lock_identity", "package-lock must bind Lucide version, tarball integrity and SPDX license to the manifest");
  }
  if (iconDependency?.license) {
    const noticeRelative = iconDependency.license.file;
    const noticePath = isSafeRelative(noticeRelative) ? path.resolve(resolvedAppRoot, noticeRelative) : "";
    const noticeExists = Boolean(noticePath && isWithin(resolvedAppRoot, noticePath) && fs.existsSync(noticePath));
    if (
      !noticeExists ||
      fs.lstatSync(noticePath).isSymbolicLink() ||
      !fs.statSync(noticePath).isFile() ||
      sha256(noticePath) !== iconDependency.license.sha256
    ) {
      push(errors, "lucide_license_notice", "Lucide must point to the exact regular in-repo third-party notice bytes");
    } else {
      const notice = fs.readFileSync(noticePath, "utf8");
      if (!notice.includes("Lucide") || !notice.includes("ISC License") || !notice.includes("Permission to use, copy, modify")) {
        push(errors, "lucide_license_notice", "Lucide notice must contain the applicable ISC attribution and grant");
      }
    }
  }

  const assets = Array.isArray(manifest.assets) ? manifest.assets : [];
  if (!Array.isArray(manifest.assets)) push(errors, "assets_shape", "assets must be an array; [] is valid");
  const ids = new Set();
  const paths = new Set();
  let totalBytes = 0;
  let thirdPartyCount = 0;

  for (const [index, asset] of assets.entries()) {
    const label = `assets[${index}]`;
    if (!exactKeys(asset, ["id", "path", "kind", "origin", "license", "integrity", "budget", "provenance"])) {
      push(errors, "asset_shape", `${label} has missing or unknown fields`);
      continue;
    }
    if (typeof asset.id !== "string" || !/^[a-z0-9][a-z0-9-]*$/.test(asset.id) || ids.has(asset.id)) {
      push(errors, "asset_id", `${label}.id is invalid or duplicated`);
    }
    ids.add(asset.id);
    if (!isSafeRelative(asset.path) || !roots.some((root) => asset.path.startsWith(`${root}/`)) || paths.has(asset.path)) {
      push(errors, "asset_path", `${label}.path is unsafe, outside allowed roots or duplicated`);
    }
    paths.add(asset.path);
    const extension = assetExtension(asset.path);
    if (!extension || !KIND_EXTENSIONS[asset.kind]?.has(extension)) push(errors, "asset_kind", `${label}.kind does not match its file extension`);
    if (!["first_party", "third_party"].includes(asset.origin)) push(errors, "asset_origin", `${label}.origin is invalid`);
    if (asset.origin === "third_party") thirdPartyCount += 1;

    if (!exactKeys(asset.license, ["spdx", "file", "sha256"]) || !allowedSpdx.includes(asset.license?.spdx) || !/^[a-f0-9]{64}$/.test(asset.license?.sha256 || "")) {
      push(errors, "asset_license", `${label} needs an allowlisted SPDX license and exact license shape`);
    }
    const licenseFile = typeof asset.license?.file === "string" ? path.resolve(resolvedAppRoot, asset.license.file) : "";
    const licenseRealPath = licenseFile && fs.existsSync(licenseFile) ? fs.realpathSync(licenseFile) : "";
    if (
      !licenseFile ||
      !isWithin(repoRoot, licenseFile) ||
      !licenseRealPath ||
      !isWithin(repoRootReal, licenseRealPath) ||
      fs.lstatSync(licenseFile).isSymbolicLink() ||
      !fs.statSync(licenseFile).isFile() ||
      !/(?:license|copying|notice)/i.test(path.basename(licenseFile))
    ) {
      push(errors, "asset_license_file", `${label}.license.file must name an existing file inside the repository`);
    } else {
      const licenseText = fs.readFileSync(licenseFile, "utf8");
      const markers = LICENSE_MARKERS[asset.license.spdx] || [];
      if (sha256(licenseFile) !== asset.license.sha256) {
        push(errors, "asset_license_hash", `${label}.license.sha256 does not match the license bytes`);
      }
      if (!markers.every((marker) => licenseText.includes(marker))) {
        push(errors, "asset_license_content", `${label}.license.file does not match declared SPDX ${asset.license.spdx}`);
      }
    }

    if (!exactKeys(asset.integrity, ["algorithm", "value", "bytes"]) || asset.integrity?.algorithm !== "sha256" || !/^[a-f0-9]{64}$/.test(asset.integrity?.value || "") || !Number.isInteger(asset.integrity?.bytes) || asset.integrity.bytes < 0) {
      push(errors, "asset_integrity", `${label} needs sha256, lowercase digest and exact byte count`);
    }
    if (!exactKeys(asset.budget, ["max_bytes"]) || !Number.isInteger(asset.budget?.max_bytes) || asset.budget.max_bytes < 0) {
      push(errors, "asset_budget", `${label} needs one non-negative max_bytes budget`);
    }
    if (!exactKeys(asset.provenance, ["source", "upstream_url", "attribution"]) || typeof asset.provenance?.attribution !== "string" || !asset.provenance.attribution.trim()) {
      push(errors, "asset_provenance", `${label} needs exact source, upstream_url and attribution fields`);
    }
    if (asset.origin === "first_party" && (asset.provenance?.source !== "repository" || asset.provenance?.upstream_url !== null)) {
      push(errors, "first_party_provenance", `${label} first-party provenance must be repository + null upstream_url`);
    }
    if (asset.origin === "third_party" && (asset.provenance?.source !== "vendored" || !/^https:\/\//.test(asset.provenance?.upstream_url || ""))) {
      push(errors, "third_party_provenance", `${label} third-party provenance must be vendored with an HTTPS upstream_url`);
    }

    const absolute = path.resolve(resolvedAppRoot, asset.path || "");
    if (!isWithin(resolvedAppRoot, absolute) || !fs.existsSync(absolute)) {
      push(errors, "asset_missing", `${label} file is missing`);
      continue;
    }
    const lstat = fs.lstatSync(absolute);
    const realPath = fs.realpathSync(absolute);
    if (lstat.isSymbolicLink() || !lstat.isFile() || !isWithin(appRootReal, realPath)) {
      push(errors, "asset_file_type", `${label} must be a regular, non-symlink file`);
      continue;
    }
    const bytes = lstat.size;
    totalBytes += bytes;
    if (asset.integrity?.bytes !== bytes) push(errors, "asset_bytes", `${label} declares ${asset.integrity?.bytes}, actual ${bytes}`);
    if (asset.integrity?.value !== sha256(absolute)) push(errors, "asset_hash", `${label} sha256 does not match the file`);
    if (Number.isInteger(asset.budget?.max_bytes) && bytes > asset.budget.max_bytes) push(errors, "asset_item_budget", `${label} exceeds its max_bytes budget`);
    if (Number.isInteger(budgets?.max_single_asset_bytes) && asset.budget?.max_bytes > budgets.max_single_asset_bytes) push(errors, "asset_budget_escalation", `${label} max_bytes exceeds the global single-asset budget`);
    if (extension === ".svg") {
      for (const svgError of svgSafetyErrors(absolute)) {
        push(errors, svgError, `${label} SVG contains active, remote or invalid content`);
      }
    }
  }

  if (Number.isInteger(budgets?.max_asset_count) && assets.length > budgets.max_asset_count) push(errors, "asset_count_budget", `asset count ${assets.length} exceeds ${budgets.max_asset_count}`);
  if (Number.isInteger(budgets?.max_total_bytes) && totalBytes > budgets.max_total_bytes) push(errors, "asset_total_budget", `asset bytes ${totalBytes} exceeds ${budgets.max_total_bytes}`);
  if (external?.declared_count !== thirdPartyCount || external?.state !== (thirdPartyCount === 0 ? "none" : "present")) {
    push(errors, "external_state_mismatch", `external state/count must equal the ${thirdPartyCount} third-party manifest asset(s)`);
  }

  const inventory = new Set();
  for (const root of roots) {
    const absoluteRoot = path.join(resolvedAppRoot, root);
    if (fs.existsSync(absoluteRoot) && fs.lstatSync(absoluteRoot).isSymbolicLink()) {
      push(errors, "asset_root_symlink", `${root} must be a real directory, not a symlink`);
      continue;
    }
    for (const file of walkFiles(absoluteRoot)) {
      if (fs.lstatSync(file).isSymbolicLink()) {
        push(errors, "asset_root_symlink", `${toPosix(path.relative(resolvedAppRoot, file))} is a symlink under an asset root`);
        continue;
      }
      if (assetExtension(file)) inventory.add(toPosix(path.relative(resolvedAppRoot, file)));
    }
  }
  for (const file of inventory) if (!paths.has(file)) push(errors, "unmanifested_asset", `${file} exists under an asset root but is not manifested`);
  for (const file of paths) if (!inventory.has(file)) push(errors, "manifest_inventory_mismatch", `${file} is manifested but absent from the asset inventory`);

  const { references, iconImports } = collectReferences(resolvedAppRoot);
  for (const reference of references) {
    if (reference.kind === "hotlink") push(errors, "hotlink", `${reference.file}:${reference.line} references ${reference.reference}`);
    else if (reference.kind === "inline") push(errors, "inline_asset", `${reference.file}:${reference.line} embeds ${reference.reference}`);
    else if (reference.kind === "unsafe") push(errors, "unsafe_asset_reference", `${reference.file}:${reference.line} escapes the app root: ${reference.reference}`);
    else if (reference.kind === "local" && !paths.has(reference.path)) push(errors, "unmanifested_reference", `${reference.file}:${reference.line} references unmanifested ${reference.path}`);
  }
  for (const iconImport of iconImports) {
    if (iconImport.package !== "lucide-react") push(errors, "icon_package", `${iconImport.file}:${iconImport.line} imports unsupported ${iconImport.package}`);
  }

  return {
    ok: errors.length === 0,
    errors,
    summary: {
      schema_version: manifest.schema_version,
      asset_count: assets.length,
      first_party_asset_count: assets.length - thirdPartyCount,
      external_asset_count: thirdPartyCount,
      total_bytes: totalBytes,
      max_asset_count: budgets?.max_asset_count ?? null,
      max_total_bytes: budgets?.max_total_bytes ?? null,
      max_single_asset_bytes: budgets?.max_single_asset_bytes ?? null,
      local_reference_count: references.filter((item) => item.kind === "local").length,
      icon_dependency: iconDependency?.package || null,
      icon_dependency_version: iconDependency?.version || null,
      icon_dependency_license: iconDependency?.license?.spdx || null
    }
  };
}
