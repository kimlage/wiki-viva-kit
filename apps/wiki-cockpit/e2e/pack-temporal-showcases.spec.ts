import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

const SHOWCASES = [
  {
    id: "personal_finance_showcase",
    center: "finance-transaction-income",
    prefix: "personal-finance.",
    labels: {
      "personal-finance.monthly-closed": { label: "Month closed", lane: "page" },
      "personal-finance.monthly-period": { label: "Monthly period", lane: "page" },
      "personal-finance.obligation-due": { label: "Obligation due", lane: "page" },
      "personal-finance.reconciliation-recorded": { label: "Reconciliation recorded", lane: "page" },
      "personal-finance.transaction-occurred": { label: "Transaction occurred", lane: "page" }
    }
  },
  {
    id: "study_research_showcase",
    center: "claim-review-cadence",
    prefix: "study-research.",
    labels: {
      "study-research.claim-recorded": { label: "Claim recorded", lane: "page" },
      "study-research.claim-verified": { label: "Claim verified", lane: "page" },
      "study-research.learning-captured": { label: "Learning captured", lane: "source" },
      "study-research.spaced-review-due": { label: "Spaced review due", lane: "page" }
    }
  }
] as const;

async function prepareDemo(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
}

for (const showcase of SHOWCASES) {
  test(`${showcase.id} Chronoscope renders every declared pack event on its explicit lane`, async ({ page }) => {
    await prepareDemo(page);
    const runtimeErrors: string[] = [];
    page.on("pageerror", (error) => runtimeErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") runtimeErrors.push(message.text());
    });

    const temporalResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === `/sample-snapshot/scenarios/${showcase.id}/temporal_graph.json`;
    });
    await page.goto(
      `/demo/w?demo_scenario=${showcase.id}&center=${showcase.center}&view=timeline&time_mode=event&tour=0`
    );
    const temporal = await (await temporalResponse).json() as {
      diagnostics: unknown[];
      events: Array<{ kind: string; lane?: string }>;
    };

    const namespaced = temporal.events
      .filter((event) => event.kind.startsWith(showcase.prefix))
      .map((event) => event.kind)
      .filter((kind, index, values) => values.indexOf(kind) === index)
      .sort();
    expect(namespaced).toEqual(Object.keys(showcase.labels).sort());
    expect(temporal.diagnostics).toEqual([]);
    expect(
      temporal.events
        .filter((event) => event.kind.startsWith(showcase.prefix))
        .every((event) => event.lane === showcase.labels[event.kind as keyof typeof showcase.labels].lane)
    ).toBe(true);

    const workspace = page.locator(".worldWorkspace");
    await expect(page.locator(".worldRouteLoading, .sceneLoading")).toHaveCount(0, {
      timeout: 20_000
    });
    await expect(workspace).toHaveAttribute("data-world-center", showcase.center);
    await expect(workspace).toHaveAttribute("data-world-view", "timeline");
    await expect(page.getByRole("heading", { name: "Chronoscope" })).toBeVisible();
    await expect(page.locator(".timelineEventList")).toBeVisible();
    for (const [kind, { label, lane }] of Object.entries(showcase.labels)) {
      const expectedCount = temporal.events.filter((event) => event.kind === kind).length;
      await expect(
        page.locator(`.timelineEventList li[data-temporal-lane="${lane}"]`).filter({ hasText: label })
      ).toHaveCount(expectedCount);
    }
    expect(new URL(page.url()).searchParams.has("time_lanes")).toBe(false);
    expect(runtimeErrors).toEqual([]);
  });
}
