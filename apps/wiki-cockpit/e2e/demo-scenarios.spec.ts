import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";
import executionContract from "../public/sample-snapshot/demo-scenarios.json" with { type: "json" };

type ScenarioContract = (typeof executionContract.scenarios)[number];

if (
  executionContract.schema_version !== "wiki_demo_scenario_execution.v1"
  || executionContract.fixture_id !== "wiki-viva-demo-v8"
) {
  throw new Error("demo scenario execution contract is not the v8 release artifact");
}

test.describe.configure({ timeout: 60_000 });

async function prepareDemo(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
}

function executableRoute(route: string) {
  const parsed = new URL(route, "http://wiki-viva.invalid");
  parsed.searchParams.set("tour", "0");
  parsed.searchParams.set("visual", "1");
  return `${parsed.pathname}?${parsed.searchParams.toString()}`;
}

for (const scenario of executionContract.scenarios as ScenarioContract[]) {
  for (const [routeIndex, canonicalRoute] of scenario.canonical_routes.entries()) {
    test(`core demo canonical route ${scenario.id} ${routeIndex + 1}/${scenario.canonical_routes.length} executes its manifest contract`, async ({ page }) => {
    await prepareDemo(page);
    const runtimeErrors: string[] = [];
    page.on("pageerror", (error) => runtimeErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") runtimeErrors.push(message.text());
    });

    const manifestResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === `${scenario.snapshot_base}/manifest.json`;
    });
    const warningsResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === `${scenario.snapshot_base}/snapshot_warnings.json`;
    });
    const parsedRoute = new URL(canonicalRoute, "http://wiki-viva.invalid");
    await page.goto(executableRoute(canonicalRoute));
    const response = await manifestResponse;
    expect(response.status()).toBe(200);
    const manifest = await response.json() as {
      contract_errors?: unknown[];
      fixture?: { scenario_id?: string };
    };
    expect(manifest.fixture?.scenario_id).toBe(scenario.id);
    expect(manifest.contract_errors).toEqual([]);
    const warningPayload = await (await warningsResponse).json() as {
      warnings?: Array<{ code?: string }>;
    };
    const warningCodes = [...new Set(
      (warningPayload.warnings ?? []).map((row) => row.code ?? "").filter(Boolean)
    )].sort();
    expect(warningCodes).toEqual(scenario.artifact_warning_codes);

    const workspace = page.locator(".worldWorkspace");
    await expect(page.locator(".worldRouteLoading, .sceneLoading")).toHaveCount(0, {
      timeout: 20_000
    });
    await expect(workspace).toBeVisible({ timeout: 20_000 });
    await expect(workspace).toHaveAttribute("data-world-center", parsedRoute.searchParams.get("center")!);
    await expect(workspace).toHaveAttribute("data-world-view", parsedRoute.searchParams.get("view")!);
    await expect(workspace).toHaveAttribute("data-world-page-count", String(scenario.page_count));
    const overlay = parsedRoute.searchParams.get("overlay");
    if (overlay) await expect(workspace).toHaveAttribute("data-world-overlay", overlay);
    const dock = parsedRoute.searchParams.get("dock");
    if (dock === "source") await expect(page.locator(".sourceDock")).toBeVisible();
    if (dock === "work") await expect(page.locator(".workDockPanel")).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`[?&]demo_scenario=${scenario.id}(?:&|$)`));
    await expect(page.getByRole("heading", { name: "Real snapshot required" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "O cockpit quebrou ao renderizar" })).toHaveCount(0);
    expect(runtimeErrors).toEqual([]);
    });
  }
}
