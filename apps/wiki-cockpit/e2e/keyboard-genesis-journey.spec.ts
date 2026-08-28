import type { Locator, Page } from "@playwright/test";
import { expect, test } from "./fixtures";

test.use({ trace: "retain-on-failure", video: "off" });
test.describe.configure({ timeout: 90_000 });

const STAGE_TITLES: Record<number, RegExp> = {
  0: /Every world begins empty|Todo mundo começa vazio/i,
  1: /The root brought the laws|A raiz trouxe as leis/i,
  2: /Four lenses opened around the root|Quatro lentes abriram ao redor da raiz/i,
  3: /The first area has its own face|A primeira área tem cara própria/i,
  4: /The world knows\. Nothing asks|O mundo sabe\. Nada pede/i,
  5: /Data became missions|Dados viraram missões/i,
  6: /Evidence has a quadrant|Evidência tem quadrante/i,
  7: /The system sees itself|O sistema se vê/i,
  8: /This world is yours now|Este mundo agora é seu/i
};

async function prepare(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  // Force the route/config await that previously leaked an operator read.
  await page.route("**/wiki-cockpit.config.json", async (route) => {
    await new Promise<void>((resolve) => setTimeout(resolve, 100));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ api_base: "/operator", snapshot_base: "/operator/snapshot", mode: "local_operator" })
    });
  });
}

function watchBoundary(page: Page) {
  const operator: string[] = [];
  const writes: string[] = [];
  const synthetic: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api" || url.pathname.startsWith("/api/") ||
        url.pathname === "/operator" || url.pathname.startsWith("/operator/")) {
      operator.push(`${request.method()} ${request.url()}`);
    }
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) {
      writes.push(`${request.method()} ${request.url()}`);
    }
    if (url.pathname.startsWith("/sample-snapshot/") && url.pathname.endsWith(".json")) synthetic.push(url.pathname);
  });
  return () => {
    expect(operator).toEqual([]);
    expect(writes).toEqual([]);
    expect(synthetic.length).toBeGreaterThan(0);
  };
}

async function expectStage(page: Page, stage: number) {
  if (stage > 0) await expect(page).toHaveURL(new RegExp(`[?&]stage=${stage}(?:&|$)`), { timeout: 20_000 });
  await expect(page.getByRole("dialog", { name: STAGE_TITLES[stage] })).toBeVisible({ timeout: 20_000 });
}

async function activeSignature(page: Page): Promise<string> {
  return page.evaluate(() => {
    const active = document.activeElement as HTMLElement | null;
    if (!active || active === document.body) return "BODY";
    return [active.tagName.toLowerCase(), active.id, active.className, active.getAttribute("aria-label"), active.textContent?.trim().slice(0, 48)]
      .filter(Boolean)
      .join("|");
  });
}

async function isFocused(target: Locator): Promise<boolean> {
  return target.evaluate((element) => document.activeElement === element);
}

async function assertVisibleKeyboardFocus(target: Locator) {
  const focus = await target.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      active: document.activeElement === element,
      focusVisible: element.matches(":focus-visible"),
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth
    };
  });
  expect(focus.active).toBe(true);
  expect(focus.focusVisible).toBe(true);
  expect(focus.outlineStyle).not.toBe("none");
  expect(Number.parseFloat(focus.outlineWidth)).toBeGreaterThanOrEqual(2);
}

// No locator.focus/click/press is allowed here. The only focus movement is the
// browser's native sequential navigation, matching a keyboard or switch user.
async function tabTo(page: Page, target: Locator, options: { reverseRoundTrip?: boolean } = {}) {
  await expect(target).toBeVisible({ timeout: 20_000 });
  await expect(target).toBeEnabled({ timeout: 10_000 });
  const trace: string[] = [];
  if (!(await isFocused(target))) {
    for (let step = 0; step < 120; step += 1) {
      await page.keyboard.press("Tab");
      const active = await activeSignature(page);
      trace.push(active);
      if (await isFocused(target)) break;
    }
  }
  expect(await isFocused(target), `focus traversal never reached target: ${trace.join(" -> ")}`).toBe(true);
  await assertVisibleKeyboardFocus(target);

  if (options.reverseRoundTrip !== false) {
    await page.keyboard.press("Shift+Tab");
    const reverse = await activeSignature(page);
    expect(await isFocused(target)).toBe(false);
    await page.keyboard.press("Tab");
    expect(await isFocused(target), `Tab did not return after Shift+Tab from ${reverse}`).toBe(true);
    await assertVisibleKeyboardFocus(target);
  }
}

async function keyboardActivate(page: Page, target: Locator) {
  await tabTo(page, target);
  await page.keyboard.press("Enter");
}

async function keyboardFill(page: Page, target: Locator, value: string) {
  await tabTo(page, target);
  await page.keyboard.type(value, { delay: 4 });
  await expect(target).toHaveValue(value);
}

async function runGenesis(page: Page) {
  await page.goto("/demo/genesis?visual=1");
  await expectStage(page, 0);
  await keyboardActivate(page, page.getByRole("button", { name: /A person|Uma pessoa/i }));
  await keyboardFill(page, page.locator(".genesisVoid input"), "Keyboard root");
  await keyboardActivate(page, page.getByRole("button", { name: /Found the root|Fundar a raiz/i }));

  await expectStage(page, 1);
  await keyboardActivate(page, page.getByRole("dialog", { name: STAGE_TITLES[1] }).getByRole("button", { name: /Attach the quadrant lenses|Anexar as lentes/i }));
  await keyboardActivate(page, page.locator(".attachRow").filter({ hasText: /Quadrant lenses|Lentes de quadrantes/i }).first().locator(".attachButton"));

  await expectStage(page, 2);
  await keyboardActivate(page, page.getByRole("dialog", { name: STAGE_TITLES[2] }).getByRole("button", { name: /Create the first area|Criar a primeira área/i }));
  await keyboardFill(page, page.locator(".createFormFields input").first(), "Finance");
  await keyboardActivate(page, page.locator(".createFormFoot button"));

  await expectStage(page, 3);
  await keyboardActivate(page, page.getByRole("dialog", { name: STAGE_TITLES[3] }).getByRole("button", { name: /Register a person|Cadastrar uma pessoa/i }));
  await keyboardFill(page, page.locator(".createFormFields input").first(), "Marina");
  await keyboardActivate(page, page.locator(".createFormFoot button"));

  await expectStage(page, 4);
  await keyboardActivate(page, page.getByRole("dialog", { name: STAGE_TITLES[4] }).getByRole("button", { name: /Attach the gamification package|Anexar o pacote de gamificação/i }));
  await keyboardActivate(page, page.locator(".attachRow").filter({ hasText: /Honest gamification|gamificação/i }).first().locator(".attachButton"));

  await expectStage(page, 5);
  await keyboardActivate(page, page.getByRole("dialog", { name: STAGE_TITLES[5] }).getByRole("button", { name: /Attach the first source|Anexar a primeira fonte/i }));
  await keyboardFill(page, page.locator(".createFormFields input").first(), "Bank export");
  await keyboardActivate(page, page.locator(".createFormFoot button"));

  await expectStage(page, 6);
  await keyboardActivate(page, page.getByRole("dialog", { name: STAGE_TITLES[6] }).getByRole("button", { name: /Fly to outputs|Voar para Prática/i }));
  await expectStage(page, 7);
  await keyboardActivate(page, page.getByRole("dialog", { name: STAGE_TITLES[7] }).getByRole("button", { name: /Finish|Concluir/i }));
  await expectStage(page, 8);

  const explore = page.getByRole("dialog", { name: STAGE_TITLES[8] }).getByRole("link", { name: /Explore|Explorar/i });
  await tabTo(page, explore);
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-empty", "false");
}

async function runMobileSwitchControl(page: Page) {
  await page.goto("/demo/genesis?stage=2&visual=1");
  await expectStage(page, 2);
  await keyboardActivate(page, page.getByRole("dialog", { name: STAGE_TITLES[2] }).getByRole("button", { name: /Create the first area|Criar a primeira área/i }));
  const input = page.locator(".createFormFields input").first();
  await keyboardFill(page, input, "Switch area");
  const submit = page.locator(".createFormFoot button");
  await tabTo(page, submit);
  await expect(submit).toBeEnabled();
}

test("Genesis 0→8 is operable by native Tab and Shift+Tab without focus traps or operator traffic", async ({ page, browser }, testInfo) => {
  await prepare(page);
  const assertBoundary = watchBoundary(page);
  await runGenesis(page);
  assertBoundary();

  // Chromium supplies the compact switch-control companion. The same release
  // already runs the full touch journey at 390×844; this proves that its
  // controls also participate in sequential keyboard/switch navigation.
  if (testInfo.project.name === "chromium-desktop") {
    const context = await browser.newContext({
      baseURL: String(testInfo.project.use.baseURL),
      colorScheme: "dark",
      hasTouch: true,
      isMobile: true,
      locale: "pt-BR",
      screen: { width: 390, height: 844 },
      viewport: { width: 390, height: 844 }
    });
    try {
      const mobile = await context.newPage();
      await prepare(mobile);
      const assertMobileBoundary = watchBoundary(mobile);
      await runMobileSwitchControl(mobile);
      assertMobileBoundary();
    } finally {
      await context.close();
    }
  }
});
