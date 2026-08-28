import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { ASSET_MANIFEST_SCHEMA, evaluateAssetManifest } from "./asset-gate-lib.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const canonicalAppRoot = path.resolve(scriptDir, "..");
const canonicalSchema = JSON.parse(fs.readFileSync(path.join(canonicalAppRoot, "assets/manifest.v1.schema.json"), "utf8"));
const LUCIDE_VERSION = "1.0.0";
const LUCIDE_INTEGRITY = "sha512-Zml4dHVyZS1sdWNpZGU=";
const LUCIDE_NOTICE = "# Third-party notices\n\nLucide\n\nISC License\n\nPermission to use, copy, modify, and/or distribute this software.\n";
const MIT_LICENSE = "MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a copy.\n";

function digest(content) {
  return crypto.createHash("sha256").update(content).digest("hex");
}

function baseManifest(content) {
  return {
    schema_version: ASSET_MANIFEST_SCHEMA,
    policy: {
      allowed_asset_roots: ["public", "src/assets"],
      allowed_spdx: ["Apache-2.0", "BSD-3-Clause", "CC-BY-4.0", "CC0-1.0", "ISC", "MIT", "OFL-1.1"],
      hotlinks: "forbidden",
      inline_data_assets: "forbidden",
      budgets: {
        max_asset_count: 8,
        max_total_bytes: 8192,
        max_single_asset_bytes: 4096
      }
    },
    external_assets: { state: "none", declared_count: 0 },
    icon_dependencies: [
      {
        package: "lucide-react",
        version: LUCIDE_VERSION,
        classification: "runtime_component_dependency",
        vendored: false,
        lock_integrity: LUCIDE_INTEGRITY,
        license: {
          spdx: "ISC",
          file: "assets/THIRD_PARTY_NOTICES.md",
          sha256: digest(Buffer.from(LUCIDE_NOTICE))
        }
      }
    ],
    assets: [
      {
        id: "test-image",
        path: "public/test.png",
        kind: "image",
        origin: "first_party",
        license: { spdx: "MIT", file: "assets/FIRST_PARTY_ASSET_LICENSE.md", sha256: digest(Buffer.from(MIT_LICENSE)) },
        integrity: { algorithm: "sha256", value: digest(content), bytes: content.length },
        budget: { max_bytes: 1024 },
        provenance: { source: "repository", upstream_url: null, attribution: "Fixture contributors" }
      }
    ]
  };
}

function fixture(t, { content = Buffer.from("fixture-image") } = {}) {
  const repoRoot = fs.mkdtempSync(path.join(os.tmpdir(), "wiki-cockpit-assets-"));
  const appRoot = path.join(repoRoot, "apps/wiki-cockpit");
  fs.mkdirSync(path.join(appRoot, "assets"), { recursive: true });
  fs.mkdirSync(path.join(appRoot, "public"), { recursive: true });
  fs.mkdirSync(path.join(appRoot, "src/assets"), { recursive: true });
  fs.writeFileSync(path.join(appRoot, "assets/FIRST_PARTY_ASSET_LICENSE.md"), MIT_LICENSE);
  fs.writeFileSync(path.join(appRoot, "assets/THIRD_PARTY_NOTICES.md"), LUCIDE_NOTICE);
  fs.writeFileSync(path.join(appRoot, "package.json"), JSON.stringify({ dependencies: { "lucide-react": LUCIDE_VERSION } }));
  fs.writeFileSync(path.join(appRoot, "package-lock.json"), JSON.stringify({
    packages: {
      "": { dependencies: { "lucide-react": LUCIDE_VERSION } },
      "node_modules/lucide-react": {
        version: LUCIDE_VERSION,
        integrity: LUCIDE_INTEGRITY,
        license: "ISC"
      }
    }
  }));
  fs.writeFileSync(path.join(appRoot, "index.html"), '<link rel="icon" href="/test.png">\n');
  fs.writeFileSync(path.join(appRoot, "public/test.png"), content);
  fs.writeFileSync(path.join(appRoot, "assets/manifest.v1.schema.json"), JSON.stringify(canonicalSchema));
  const manifest = baseManifest(content);
  const writeManifest = () => fs.writeFileSync(path.join(appRoot, "assets/manifest.v1.json"), JSON.stringify(manifest, null, 2));
  const evaluate = () => {
    writeManifest();
    return evaluateAssetManifest({ appRoot });
  };
  t.after(() => fs.rmSync(repoRoot, { recursive: true, force: true }));
  return { appRoot, manifest, evaluate, content };
}

function codes(result) {
  return result.errors.map((entry) => entry.code);
}

test("accepts the repository manifest and records every external asset explicitly", () => {
  const result = evaluateAssetManifest({ appRoot: canonicalAppRoot });
  assert.equal(result.ok, true, JSON.stringify(result.errors, null, 2));
  assert.equal(result.summary.schema_version, ASSET_MANIFEST_SCHEMA);
  assert.equal(result.summary.external_asset_count, 8);
  assert.equal(result.summary.icon_dependency, "lucide-react");
});

test("accepts a truly empty asset inventory as an explicit valid state", (t) => {
  const current = fixture(t);
  fs.rmSync(path.join(current.appRoot, "public/test.png"));
  fs.writeFileSync(path.join(current.appRoot, "index.html"), '<div id="root"></div>\n');
  current.manifest.assets = [];
  current.manifest.external_assets = { state: "none", declared_count: 0 };
  const result = current.evaluate();
  assert.equal(result.ok, true, JSON.stringify(result.errors, null, 2));
  assert.deepEqual(result.summary, {
    schema_version: ASSET_MANIFEST_SCHEMA,
    asset_count: 0,
    first_party_asset_count: 0,
    external_asset_count: 0,
    total_bytes: 0,
    max_asset_count: 8,
    max_total_bytes: 8192,
    max_single_asset_bytes: 4096,
    local_reference_count: 0,
    icon_dependency: "lucide-react",
    icon_dependency_version: LUCIDE_VERSION,
    icon_dependency_license: "ISC"
  });
});

test("rejects remote, protocol-relative and inline data asset references", async (t) => {
  for (const [name, reference, expected] of [
    ["https", "https://cdn.example.test/hero.png", "hotlink"],
    ["protocol-relative", "//cdn.example.test/hero.png", "hotlink"],
    ["data", "data:image/png;base64,AAAA", "inline_asset"]
  ]) {
    await t.test(name, (nested) => {
      const current = fixture(nested);
      fs.writeFileSync(path.join(current.appRoot, "src/asset.css"), `.hero{background-image:url(${reference})}`);
      const result = current.evaluate();
      assert.equal(result.ok, false);
      assert.ok(codes(result).includes(expected), JSON.stringify(result.errors, null, 2));
    });
  }
});

test("rejects active and remotely-referencing manifested SVG", async (t) => {
  for (const [name, svg, expected] of [
    ["script", '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "active_svg"],
    ["remote image", '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://cdn.example.test/a.png"/></svg>', "active_svg"],
    ["data image", '<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,AA"/></svg>', "active_svg"],
    ["event handler", '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>', "active_svg"],
    ["escaped CSS hotlink", '<svg xmlns="http://www.w3.org/2000/svg"><style>.x{background-image:u\\72l(\\68ttps\\3a \\2f \\2f cdn.example.test/a.png)}</style><rect class="x" width="10" height="10"/></svg>', "active_svg"],
    ["escaped presentation-attribute hotlink", '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="u\\72l(\\68ttp\\3a \\2f \\2f cdn.example.test/external.svg#paint)"/></svg>', "active_svg"],
    ["entity-obscured namespace style", '<svg xmlns="http://www.w3.org/2000/svg" xmlns:s="&#104;ttp://www.w3.org/2000/svg"><s:style>.x{fill:u\\72l(\\68ttp\\3a \\2f \\2f cdn.example.test/external.svg#paint)}</s:style><rect class="x"/></svg>', "active_svg"],
    ["style attribute", '<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:url(#paint)"/></svg>', "active_svg"],
    ["SMIL animation", '<svg xmlns="http://www.w3.org/2000/svg"><set attributeName="href" to="https://cdn.example.test/a.png"/></svg>', "active_svg"],
    ["entity-obscured href", '<svg xmlns="http://www.w3.org/2000/svg"><image href="&#x68;ttps://cdn.example.test/a.png"/></svg>', "remote_svg_reference"]
  ]) {
    await t.test(name, (nested) => {
      const content = Buffer.from(svg);
      const current = fixture(nested, { content });
      fs.renameSync(
        path.join(current.appRoot, "public/test.png"),
        path.join(current.appRoot, "public/test.svg")
      );
      fs.writeFileSync(path.join(current.appRoot, "index.html"), '<link rel="icon" href="/test.svg">\n');
      current.manifest.assets[0].path = "public/test.svg";
      const result = current.evaluate();
      assert.equal(result.ok, false);
      assert.ok(codes(result).includes(expected), JSON.stringify(result.errors, null, 2));
    });
  }
});

test("rejects remote and inline assets hidden in HTML style attributes", async (t) => {
  for (const [name, reference, expected] of [
    ["remote", "https://cdn.example.test/a.png", "hotlink"],
    ["inline", "data:image/png;base64,AA", "inline_asset"]
  ]) {
    await t.test(name, (nested) => {
      const current = fixture(nested);
      fs.writeFileSync(
        path.join(current.appRoot, "index.html"),
        `<div style="background-image:url(${reference})"></div>\n`
      );
      const result = current.evaluate();
      assert.equal(result.ok, false);
      assert.ok(codes(result).includes(expected), JSON.stringify(result.errors, null, 2));
    });
  }
});

test("rejects an opaque local JSX resource that cannot be matched to a manifested file", (t) => {
  const current = fixture(t);
  fs.writeFileSync(path.join(current.appRoot, "src/card.tsx"), 'export const Card = () => <img src="/media/render/42" alt="" />;\n');
  const result = current.evaluate();
  assert.equal(result.ok, false);
  assert.ok(codes(result).includes("unmanifested_reference"), JSON.stringify(result.errors, null, 2));
});

test("rejects an opaque local CSS resource instead of exempting extensionless assets", (t) => {
  const current = fixture(t);
  fs.writeFileSync(path.join(current.appRoot, "src/card.css"), '.card{background-image:url("/media/render/42")}\n');
  const result = current.evaluate();
  assert.equal(result.ok, false);
  assert.ok(codes(result).includes("unmanifested_reference"), JSON.stringify(result.errors, null, 2));
});

test("rejects an asset without license, hash or per-item budget", async (t) => {
  for (const [name, mutate, expected] of [
    ["license", (asset) => { asset.license = {}; }, "asset_license"],
    ["hash", (asset) => { asset.integrity = {}; }, "asset_integrity"],
    ["budget", (asset) => { asset.budget = {}; }, "asset_budget"]
  ]) {
    await t.test(name, (nested) => {
      const current = fixture(nested);
      mutate(current.manifest.assets[0]);
      const result = current.evaluate();
      assert.equal(result.ok, false);
      assert.ok(codes(result).includes(expected), JSON.stringify(result.errors, null, 2));
    });
  }
});

test("binds each asset to matching license bytes and SPDX content", async (t) => {
  await t.test("license hash drift", (nested) => {
    const current = fixture(nested);
    fs.appendFileSync(path.join(current.appRoot, "assets/FIRST_PARTY_ASSET_LICENSE.md"), "drift\n");
    const result = current.evaluate();
    assert.ok(codes(result).includes("asset_license_hash"), JSON.stringify(result.errors, null, 2));
  });
  await t.test("wrong SPDX content", (nested) => {
    const current = fixture(nested);
    current.manifest.assets[0].license.spdx = "OFL-1.1";
    const result = current.evaluate();
    assert.ok(codes(result).includes("asset_license_content"), JSON.stringify(result.errors, null, 2));
  });
});

test("rejects hash drift, unmanifested files and assets over budget", async (t) => {
  await t.test("hash drift", (nested) => {
    const current = fixture(nested);
    current.manifest.assets[0].integrity.value = "0".repeat(64);
    const result = current.evaluate();
    assert.ok(codes(result).includes("asset_hash"));
  });
  await t.test("unmanifested file", (nested) => {
    const current = fixture(nested);
    fs.writeFileSync(path.join(current.appRoot, "public/unlisted.webp"), "unlisted");
    const result = current.evaluate();
    assert.ok(codes(result).includes("unmanifested_asset"));
  });
  await t.test("item budget", (nested) => {
    const current = fixture(nested);
    current.manifest.assets[0].budget.max_bytes = 1;
    const result = current.evaluate();
    assert.ok(codes(result).includes("asset_item_budget"));
  });
});

test("requires honest third-party provenance and a matching external count", (t) => {
  const current = fixture(t);
  const asset = current.manifest.assets[0];
  asset.origin = "third_party";
  asset.provenance = { source: "vendored", upstream_url: "http://insecure.example.test/test.png", attribution: "Fixture author" };
  const result = current.evaluate();
  assert.equal(result.ok, false);
  assert.ok(codes(result).includes("third_party_provenance"));
  assert.ok(codes(result).includes("external_state_mismatch"));
});

test("accepts a vendored third-party asset only with HTTPS provenance and exact external state", (t) => {
  const current = fixture(t);
  const asset = current.manifest.assets[0];
  asset.origin = "third_party";
  asset.provenance = {
    source: "vendored",
    upstream_url: "https://assets.example.test/test.png",
    attribution: "Fixture author"
  };
  current.manifest.external_assets = { state: "present", declared_count: 1 };
  const result = current.evaluate();
  assert.equal(result.ok, true, JSON.stringify(result.errors, null, 2));
  assert.equal(result.summary.external_asset_count, 1);
});

test("keeps Lucide as a runtime dependency and rejects an alternate icon package", (t) => {
  const current = fixture(t);
  current.manifest.icon_dependencies = [
    { ...current.manifest.icon_dependencies[0], package: "react-icons" }
  ];
  fs.writeFileSync(path.join(current.appRoot, "src/icons.tsx"), 'import { Icon } from "react-icons/fa";\nexport { Icon };\n');
  const result = current.evaluate();
  assert.equal(result.ok, false);
  assert.ok(codes(result).includes("icon_dependency_contract"));
  assert.ok(codes(result).includes("icon_package"));
});

test("rejects Lucide version, lock integrity, license and notice drift", async (t) => {
  for (const [name, mutate, expected] of [
    ["version", (current) => { current.manifest.icon_dependencies[0].version = "1.0.1"; }, "lucide_dependency"],
    ["integrity", (current) => { current.manifest.icon_dependencies[0].lock_integrity = "sha512-ZHJpZnQ="; }, "lucide_lock_identity"],
    ["license", (current) => { current.manifest.icon_dependencies[0].license.spdx = "MIT"; }, "icon_dependency_contract"],
    ["notice", (current) => { fs.appendFileSync(path.join(current.appRoot, "assets/THIRD_PARTY_NOTICES.md"), "drift\n"); }, "lucide_license_notice"]
  ]) {
    await t.test(name, (nested) => {
      const current = fixture(nested);
      mutate(current);
      const result = current.evaluate();
      assert.equal(result.ok, false);
      assert.ok(codes(result).includes(expected), JSON.stringify(result.errors, null, 2));
    });
  }
});

test("rejects a symlink in the asset inventory", { skip: process.platform === "win32" }, (t) => {
  const current = fixture(t);
  const original = path.join(current.appRoot, "public/test.png");
  const target = path.join(current.appRoot, "public/target.bin");
  fs.renameSync(original, target);
  fs.symlinkSync("target.bin", original);
  const result = current.evaluate();
  assert.equal(result.ok, false);
  assert.ok(codes(result).includes("asset_file_type"));
});
