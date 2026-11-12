import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

// Separate runners, never concurrent GPU workers on the same runner. The
// ordinary/local release configuration and its first-attempt policy stay intact.
const group = process.env.WIKI_CI_BROWSER_GROUP;
const visualSpec = /visual-regression\.spec\.ts/;
const desktop = base.projects!.find((project) => project.name === "chromium-desktop")!;
let projects = base.projects!;
let shard: { current: number; total: number } | undefined;

if (group === "desktop-1" || group === "desktop-2") {
  const ignores = desktop.testIgnore ?? [];
  projects = [{
    ...desktop,
    testIgnore: [...(Array.isArray(ignores) ? ignores : [ignores]), visualSpec],
  }];
  shard = { current: group === "desktop-1" ? 1 : 2, total: 2 };
} else if (group === "visual-mobile") {
  projects = [
    { ...desktop, testMatch: visualSpec },
    ...projects.filter((project) => project.name === "webkit-mobile"),
  ];
} else if (group === "cross-browser") {
  projects = projects.filter((project) =>
    ["webkit-keyboard", "chromium-fallback", "firefox-smoke"].includes(project.name!),
  );
} else {
  throw new Error(`Unknown WIKI_CI_BROWSER_GROUP: ${group}`);
}

export default defineConfig({ ...base, projects, shard });
