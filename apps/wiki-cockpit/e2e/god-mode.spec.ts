// God-mode plan §22.9 core journeys against the sealed demo (chromium-desktop
// project). What runs HERE: demo → ritual → admin unavailable; ritual visuals
// and copy; god_mode opening the honest Admin Dock; Escape ladder; the
// reduced-motion path; the 2D fallback twin with the SAME operations. The
// local_operator unlock/lock/plan/execute journeys need a live operator
// process and are covered at vitest level (AdminUnlockDialog/AdminDock/
// adminSession tests) and pytest level (test_admin_sessions/commands/
// capabilities/audit) — the public Playwright suite must stay runnable
// against the static demo alone.

import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

test.describe.configure({ timeout: 60_000 });

const WORLD_ROUTE = "/demo/w?view=quadrants&center=root-alex-rivera";

// The demo fixture publishes language "en" — assert the exact EN copy so the
// 3D plate and the 2D fallback are proven to speak the SAME line (§15.6).
const DEMO_SPEECH = "This universe is a demonstration vision. No real change will be made here.";
const RITUAL_PHRASE = "abrachaindabra";

async function prepareDemo(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
}

// The demo is sealed (§3.2, §7): no route in these journeys may ever issue an
// administrative request. Track every attempt, assert zero at the end.
function trackAdminRequests(page: Page): string[] {
  const rows: string[] = [];
  page.on("request", (request) => {
    try {
      if (new URL(request.url()).pathname.startsWith("/api/admin")) rows.push(request.url());
    } catch {
      /* non-URL request (data:) — irrelevant */
    }
  });
  return rows;
}

function trackRuntimeErrors(page: Page): string[] {
  const rows: string[] = [];
  page.on("pageerror", (error) => rows.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") rows.push(message.text());
  });
  return rows;
}

async function castPhrase(page: Page, phrase: string) {
  const input = page.locator(".commandSearch input");
  await input.fill(phrase);
  await input.press("Enter");
}

async function expectRitualOpenWithDemoCopy(page: Page) {
  const plate = page.locator(".takezoPlate");
  await expect(plate).toBeVisible({ timeout: 15_000 });
  await expect(plate.locator(".takezoName")).toHaveText("Takezo");
  await expect(plate.locator(".takezoSpeech")).toHaveText(DEMO_SPEECH);
  await expect(plate.locator(".takezoNote")).not.toBeEmpty();
  // Sealed demo: contemplation only — no unlock CTA exists (§5.3).
  await expect(plate.locator(".plateCta")).toHaveCount(0);
  // §23: the ritual moves keyboard focus onto the dialog plate.
  await expect(plate).toBeFocused();
  // The phrase is presentation state only: never in the URL, never left in
  // the field, never recorded anywhere addressable (§5.1, §10.4).
  await expect(page).not.toHaveURL(/abrachaindabra/i);
  await expect(page.locator(".commandSearch input")).toHaveValue("");
}

async function expectRitualClosedByEscape(page: Page) {
  await page.keyboard.press("Escape");
  await expect(page.locator(".takezoPlate")).toHaveCount(0);
  // Closing hands keyboard focus back to the command bar (§23).
  await expect(page.locator(".commandSearch input")).toBeFocused();
}

async function expectAdminDockUnavailable(page: Page) {
  await expect(page).toHaveURL(/[?&]dock=admin(?:&|$)/);
  const dock = page.locator(".adminDock");
  await expect(dock).toBeVisible({ timeout: 10_000 });
  // §6.3: state is a text label, never color-only.
  await expect(dock.locator(".adminStateChip")).toHaveText("Admin unavailable");
  await expect(dock.locator(".adminStateChip")).toHaveClass(/adminState-unavailable/);
  // Honest sealed-demo body, and no unlock affordance whatsoever.
  await expect(dock).toContainText("This is the sealed demo");
  await expect(dock.locator(".primaryButton")).toHaveCount(0);
  await dock.locator(".readerClose").click();
  await expect(page.locator(".adminDock")).toHaveCount(0);
  await expect(page).not.toHaveURL(/[?&]dock=admin/);
}

test("demo ritual: abrachaindabra opens the sealed 3D plate, near-misses stay search, Escape closes", async ({ page }) => {
  await prepareDemo(page);
  const adminRequests = trackAdminRequests(page);
  const runtimeErrors = trackRuntimeErrors(page);
  await page.goto(WORLD_ROUTE);
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator("canvas")).toHaveCount(1, { timeout: 20_000 });

  // §5.2/§22.1: a suffixed phrase is NOT the ritual — it stays plain search
  // and must not crash even without results.
  await castPhrase(page, `${RITUAL_PHRASE} gato`);
  await expect(page.locator(".takezoPlate")).toHaveCount(0);
  await expect(page.locator(".sceneShell")).toHaveAttribute("data-takezo-ritual", "false");
  await page.locator(".commandSearch input").fill("");

  // The real phrase (normalization: edge whitespace + case are forgiven).
  await castPhrase(page, `  ${RITUAL_PHRASE.toUpperCase()}  `);
  await expect(page.locator(".sceneShell")).toHaveAttribute("data-takezo-ritual", "true", { timeout: 15_000 });
  await expectRitualOpenWithDemoCopy(page);

  await expectRitualClosedByEscape(page);
  await expect(page.locator(".sceneShell")).toHaveAttribute("data-takezo-ritual", "false");

  expect(adminRequests).toEqual([]);
  expect(runtimeErrors).toEqual([]);
});

test("demo god_mode: opens the Admin Dock honestly unavailable without any admin request", async ({ page }) => {
  await prepareDemo(page);
  const adminRequests = trackAdminRequests(page);
  const runtimeErrors = trackRuntimeErrors(page);
  await page.goto(WORLD_ROUTE);
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20_000 });

  await castPhrase(page, "god_mode");
  await expectAdminDockUnavailable(page);

  // A bare near-miss with an unknown argument stays search — no dock reopens.
  await castPhrase(page, "god_mode gato");
  await expect(page.locator(".adminDock")).toHaveCount(0);

  expect(adminRequests).toEqual([]);
  expect(runtimeErrors).toEqual([]);
});

test.describe("reduced motion", () => {
  // Same mechanism as the chromium-fallback project: reducedMotion is a
  // context option here, not a first-class test option.
  test.use({ contextOptions: { reducedMotion: "reduce" } });

  test("ritual degrades to the 2D twin with identical copy and flow", async ({ page }) => {
    await prepareDemo(page);
    const adminRequests = trackAdminRequests(page);
    const runtimeErrors = trackRuntimeErrors(page);
    await page.goto(WORLD_ROUTE);
    expect(await page.evaluate(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(true);
    await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/, { timeout: 20_000 });
    await expect(page.locator("canvas")).toHaveCount(0);

    await castPhrase(page, RITUAL_PHRASE);
    const fallback = page.locator(".takezoRitualFallback");
    await expect(fallback).toBeVisible({ timeout: 10_000 });
    await expect(fallback).toHaveAttribute("data-takezo-runtime", "demo");
    // §15.6: the figure keeps the full identity as accessible alt text.
    await expect(fallback.locator(".takezoFigure")).toHaveAttribute(
      "aria-label",
      "Takezo, a wizard cat with a blue robe, a blue hat and red ribbons"
    );
    await expectRitualOpenWithDemoCopy(page);
    await expectRitualClosedByEscape(page);

    expect(adminRequests).toEqual([]);
    expect(runtimeErrors).toEqual([]);
  });
});

test("forced fallback (visual test mode) supports the same ritual and god_mode operations", async ({ page }) => {
  await prepareDemo(page);
  const adminRequests = trackAdminRequests(page);
  const runtimeErrors = trackRuntimeErrors(page);
  await page.goto(`${WORLD_ROUTE}&visual=1`);
  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/, { timeout: 20_000 });
  await expect(page.locator("canvas")).toHaveCount(0);

  // §22.9 journey 10: the fallback world runs the SAME operations.
  await castPhrase(page, RITUAL_PHRASE);
  await expect(page.locator(".takezoRitualFallback")).toBeVisible({ timeout: 10_000 });
  await expectRitualOpenWithDemoCopy(page);
  await expectRitualClosedByEscape(page);

  await castPhrase(page, "god_mode");
  await expectAdminDockUnavailable(page);

  expect(adminRequests).toEqual([]);
  expect(runtimeErrors).toEqual([]);
});
