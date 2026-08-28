import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const appSource = fs.readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const workspaceSource = fs.readFileSync(
  new URL("../src/components/SourceWorkspace.tsx", import.meta.url),
  "utf8"
);

test("the standalone source workspace owns its visual stylesheet", () => {
  assert.match(
    workspaceSource,
    /import\s+["']\.\.\/styles\.css["'];?/,
    "SourceWorkspace must load the shared visual stylesheet because this route bypasses RuntimeWorldView"
  );
});

test("the source workspace remains a lazy standalone application surface", () => {
  assert.match(
    appSource,
    /const SourceWorkspace = lazy\(\(\) => import\(["']\.\/components\/SourceWorkspace["']\)/,
    "SourceWorkspace must stay lazy so the 2D manager does not preload the 3D runtime"
  );
});
