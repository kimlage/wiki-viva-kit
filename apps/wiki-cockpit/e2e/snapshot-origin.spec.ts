import type { Browser, Locator, Page, TestInfo } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { expect, test } from "./fixtures";

type GenesisInputMode = "keyboard" | "pointer" | "touch";

const GENESIS_STAGE_TITLES: Record<number, RegExp> = {
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

function watchDemoNetwork(
  page: Page,
  options: { operatorBases?: string[]; operatorOrigins?: string[] } = {}
) {
  const writes: { method: string; url: string }[] = [];
  const apiRequests: string[] = [];
  const operatorRequests: string[] = [];
  const nonSyntheticJson: string[] = [];
  const syntheticJson: string[] = [];
  let operatorBoundaryMarked = false;
  const afterMark = new Map<import("@playwright/test").Request, {
    url: string;
    routeAtStart: string;
    state: "pending" | "finished" | "failed";
    failure: string;
  }>();
  const operatorBases = options.operatorBases ?? ["/api", "/operator"];
  const operatorOrigins = new Set(options.operatorOrigins ?? []);
  page.on("request", (request) => {
    const method = request.method();
    const url = new URL(request.url());
    if (!["GET", "HEAD", "OPTIONS"].includes(method)) writes.push({ method, url: request.url() });
    if (url.pathname === "/api" || url.pathname.startsWith("/api/")) apiRequests.push(request.url());
    const underOperatorBase = operatorBases.some((base) => {
      if (/^https?:\/\//.test(base)) {
        const normalized = base.replace(/\/$/, "");
        return request.url() === normalized || request.url().startsWith(`${normalized}/`);
      }
      const normalized = `/${base.replace(/^\/+|\/+$/g, "")}`;
      return url.pathname === normalized || url.pathname.startsWith(`${normalized}/`);
    });
    if (underOperatorBase || operatorOrigins.has(url.origin)) {
      operatorRequests.push(request.url());
      if (operatorBoundaryMarked) {
        afterMark.set(request, {
          url: request.url(),
          routeAtStart: page.url(),
          state: "pending",
          failure: ""
        });
      }
    }
    if (url.pathname.endsWith(".json")) {
      if (url.pathname === "/wiki-cockpit.config.json" || url.pathname.startsWith("/sample-snapshot/")) {
        syntheticJson.push(url.pathname);
      } else {
        nonSyntheticJson.push(url.pathname);
      }
    }
  });
  page.on("requestfinished", (request) => {
    const observed = afterMark.get(request);
    if (observed) observed.state = "finished";
  });
  page.on("requestfailed", (request) => {
    const observed = afterMark.get(request);
    if (!observed) return;
    observed.state = "failed";
    observed.failure = request.failure()?.errorText ?? "unknown failure";
  });
  return {
    assertClean() {
      expect(writes).toEqual([]);
      expect(apiRequests).toEqual([]);
      expect(operatorRequests).toEqual([]);
      expect(nonSyntheticJson).toEqual([]);
      expect(syntheticJson.some((path) => path.startsWith("/sample-snapshot/"))).toBe(true);
    },
    markOperatorBoundary() {
      operatorBoundaryMarked = true;
      afterMark.clear();
    },
    async assertNoOperatorAfterMark() {
      await expect.poll(
        () => [...afterMark.values()].every((request) => request.state !== "pending"),
        { timeout: 5_000 }
      ).toBe(true);
      const violations = [...afterMark.values()].filter((request) =>
        request.routeAtStart.includes("/demo") ||
        request.state === "finished" ||
        (request.state === "failed" && !/aborted/i.test(request.failure))
      );
      expect(violations).toEqual([]);
    }
  };
}

async function installDelayedOperatorRuntime(page: Page, delayMs = 150) {
  await page.route("**/wiki-cockpit.config.json", async (route) => {
    await new Promise<void>((resolve) => setTimeout(resolve, delayMs));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        api_base: "/operator",
        snapshot_base: "/operator/snapshot",
        mode: "local_operator",
        repo_label: "operator-bound fixture",
        codex: { enabled: true }
      })
    });
  });

  await page.route("**/operator/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith("/operator/snapshot/")) {
      const suffix = url.pathname.slice("/operator/snapshot".length);
      const response = await route.fetch({
        url: new URL(`/sample-snapshot${suffix}`, route.request().url()).toString()
      });
      await route.fulfill({ response });
      return;
    }
    if (url.pathname === "/operator/health") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          server_version: "wiki_web_server.v6",
          schema_capabilities: ["operator_security_v2", "cors_default_deny_v1", "action_state_transitions_v1"],
          operator_security: {
            version: "wiki_operator_security.v2",
            nonce_header: "X-Wiki-Operator-Nonce",
            nonce: "e2e-read-boundary",
            attempt_header: "X-Wiki-Attempt-Key",
            max_body_bytes: 1048576,
            mutations: "post_only",
            browser_origin_default: "deny",
            cors_opt_in: "exact_loopback_allowlist"
          },
          codex: { enabled: true, installed: true, runnable: true, authed: true, usable: true, reason: "" }
        })
      });
      return;
    }
    if (url.pathname === "/operator/codex/jobs") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          jobs: [{
            job_id: "read-boundary-job",
            brief_id: "brief-boundary",
            brief_sha: "sha",
            parent_job_id: null,
            theme: "observe crossing",
            status: "running",
            steps: [{ id: "observe", label: "Observe", status: "running" }],
            branch: "wiki/read-boundary",
            draft_pr_url: null
          }]
        })
      });
      return;
    }
    if (url.pathname === "/operator/briefs") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, briefs: [] }) });
      return;
    }
    if (url.pathname === "/operator/codex/jobs/read-boundary-job/log") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, log: "safe live tail" }) });
      return;
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ ok: false }) });
  });
}

async function prepareDemo(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
}

async function activate(page: Page, target: Locator, mode: GenesisInputMode) {
  await expect(target).toBeVisible({ timeout: 20_000 });
  await expect(target).toBeEnabled({ timeout: 5_000 });
  if (mode === "touch") {
    await target.tap({ timeout: 5_000 });
    return;
  }
  if (mode === "pointer") {
    await target.click({ timeout: 5_000 });
    return;
  }
  // Locator.press focuses and dispatches the key as one browser action. A
  // closing dock may schedule focus restoration on rAF; splitting focus and
  // keypress would create an artificial race that a real Tab+Enter turn does
  // not have.
  await target.press("Enter", { timeout: 5_000 });
}

async function enterText(page: Page, target: Locator, value: string, mode: GenesisInputMode) {
  await expect(target).toBeVisible({ timeout: 20_000 });
  if (mode === "touch") {
    await target.tap({ timeout: 5_000 });
    await target.fill(value, { timeout: 5_000 });
    return;
  }
  if (mode === "pointer") {
    await target.fill(value, { timeout: 5_000 });
    return;
  }
  await target.pressSequentially(value, { delay: 0, timeout: 5_000 });
}

async function expectGenesisStage(page: Page, stage: number) {
  if (stage > 0) await expect(page).toHaveURL(new RegExp(`[?&]stage=${stage}(?:&|$)`), { timeout: 20_000 });
  await expect(page.getByRole("dialog", { name: GENESIS_STAGE_TITLES[stage] })).toBeVisible({ timeout: 20_000 });
}

async function expectNoSurfaceOverlap(page: Page, surface: Locator) {
  const guide = page.locator(".genesisCard--actionOpen");
  await expect(guide).toBeVisible();
  await expect(surface).toBeVisible();
  await expect.poll(async () => {
    const [guideBox, surfaceBox] = await Promise.all([guide.boundingBox(), surface.boundingBox()]);
    if (!guideBox || !surfaceBox) return null;
    const overlapWidth = Math.max(
      0,
      Math.min(guideBox.x + guideBox.width, surfaceBox.x + surfaceBox.width) - Math.max(guideBox.x, surfaceBox.x)
    );
    const overlapHeight = Math.max(
      0,
      Math.min(guideBox.y + guideBox.height, surfaceBox.y + surfaceBox.height) - Math.max(guideBox.y, surfaceBox.y)
    );
    return overlapWidth * overlapHeight;
  }, { timeout: 5_000 }).toBe(0);
}

async function assertStageTwoMobileCreateLayout(
  browser: Browser,
  viewport: { width: number; height: number },
  testInfo: TestInfo
) {
  const context = await browser.newContext({
    baseURL: String(testInfo.project.use.baseURL),
    colorScheme: "dark",
    hasTouch: true,
    isMobile: true,
    locale: "pt-BR",
    screen: viewport,
    viewport
  });
  try {
    const page = await context.newPage();
    const network = watchDemoNetwork(page);
    await prepareDemo(page);
    await page.goto("/demo/genesis?stage=2&visual=1");
    await expectGenesisStage(page, 2);
    await page.getByRole("dialog", { name: GENESIS_STAGE_TITLES[2] })
      .getByRole("button", { name: /Create the first area|Criar a primeira área/i })
      .tap();

    const sheet = page.locator(".createSheet");
    const form = sheet.locator(".createForm");
    const description = form.locator(".createFormHead > div small");
    const pill = form.locator(".createHomePill");
    const title = form.locator(".createFormFields input").first();
    const cta = form.locator(".createFormFoot .btn");
    await expect(form).toBeVisible();
    await expect(cta).toBeDisabled();

    const geometry = await form.evaluate((element) => {
      const rect = (selector: string) => {
        const target = element.querySelector<HTMLElement>(selector);
        if (!target) return null;
        const box = target.getBoundingClientRect();
        return { x: box.x, y: box.y, width: box.width, height: box.height, right: box.right, bottom: box.bottom };
      };
      const root = element.getBoundingClientRect();
      const button = element.querySelector<HTMLButtonElement>(".createFormFoot .btn")!;
      const style = getComputedStyle(button);
      return {
        root: { x: root.x, width: root.width, right: root.right },
        description: rect(".createFormHead > div small"),
        pill: rect(".createHomePill"),
        title: rect(".createFormFields input"),
        cta: rect(".createFormFoot .btn"),
        ctaStyle: {
          backgroundColor: style.backgroundColor,
          cursor: style.cursor,
          opacity: style.opacity
        },
        formOverflow: element.scrollWidth - element.clientWidth,
        documentOverflow: document.documentElement.scrollWidth - window.innerWidth
      };
    });
    expect(geometry.root.x).toBeGreaterThanOrEqual(8);
    expect(geometry.root.right).toBeLessThanOrEqual(viewport.width - 8 + 1);
    expect(geometry.description?.width ?? 0).toBeGreaterThanOrEqual(220);
    expect(geometry.title?.width ?? 0).toBeGreaterThanOrEqual(viewport.width - 48);
    expect(geometry.pill?.width ?? Infinity).toBeLessThanOrEqual(geometry.root.width);
    expect(geometry.pill?.y ?? 0).toBeGreaterThanOrEqual((geometry.description?.bottom ?? 0) - 1);
    expect(geometry.cta?.width ?? 0).toBeGreaterThanOrEqual(viewport.width - 48);
    expect(geometry.cta?.height ?? 0).toBeGreaterThanOrEqual(45);
    expect(geometry.ctaStyle).toMatchObject({ cursor: "not-allowed", opacity: "1" });
    expect(geometry.ctaStyle.backgroundColor).not.toBe("rgb(107, 215, 255)");
    expect(geometry.formOverflow).toBeLessThanOrEqual(1);
    expect(geometry.documentOverflow).toBeLessThanOrEqual(1);

    const screenshot = await sheet.screenshot();
    const closureDir = resolve(process.cwd(), "../../output/playwright/rt26-closure");
    const closurePath = join(
      closureDir,
      `genesis-stage-2-create-${viewport.width}x${viewport.height}-post-fix.png`
    );
    await mkdir(closureDir, { recursive: true });
    await writeFile(closurePath, screenshot);
    await testInfo.attach(`genesis-stage-2-create-${viewport.width}x${viewport.height}.png`, {
      body: screenshot,
      contentType: "image/png"
    });
    network.assertClean();
  } finally {
    await context.close();
  }
}

async function completeGenesis(page: Page, mode: GenesisInputMode) {
  await prepareDemo(page);
  await page.goto("/demo/genesis?visual=1");
  await expectGenesisStage(page, 0);
  await activate(page, page.getByRole("button", { name: /A person|Uma pessoa/i }), mode);
  await enterText(page, page.locator(".genesisVoid input"), `${mode} root`, mode);
  await activate(page, page.getByRole("button", { name: /Found the root|Fundar a raiz/i }), mode);

  await expectGenesisStage(page, 1);
  await activate(page, page.getByRole("dialog", { name: GENESIS_STAGE_TITLES[1] }).getByRole("button", { name: /Attach the quadrant lenses|Anexar as lentes/i }), mode);
  await expectNoSurfaceOverlap(page, page.locator(".blocksDock"));
  const quadrantRow = page.locator(".attachRow").filter({ hasText: /Quadrant lenses|Lentes de quadrantes/i }).first();
  await activate(page, quadrantRow.locator(".attachButton"), mode);

  await expectGenesisStage(page, 2);
  await activate(page, page.getByRole("dialog", { name: GENESIS_STAGE_TITLES[2] }).getByRole("button", { name: /Create the first area|Criar a primeira área/i }), mode);
  await expectNoSurfaceOverlap(page, page.locator(".createSheet"));
  if (!(await page.locator(".createFormFields input").first().isVisible())) {
    await activate(page, page.locator(".createTypeRow.active"), mode);
  }
  await enterText(page, page.locator(".createFormFields input").first(), "Finance", mode);
  await activate(page, page.locator(".createFormFoot button"), mode);

  await expectGenesisStage(page, 3);
  await activate(page, page.getByRole("dialog", { name: GENESIS_STAGE_TITLES[3] }).getByRole("button", { name: /Register a person|Cadastrar uma pessoa/i }), mode);
  await expectNoSurfaceOverlap(page, page.locator(".createSheet"));
  if (!(await page.locator(".createFormFields input").first().isVisible())) {
    await activate(page, page.locator(".createTypeRow.active"), mode);
  }
  await enterText(page, page.locator(".createFormFields input").first(), "Marina", mode);
  await activate(page, page.locator(".createFormFoot button"), mode);

  await expectGenesisStage(page, 4);
  await activate(page, page.getByRole("dialog", { name: GENESIS_STAGE_TITLES[4] }).getByRole("button", { name: /Attach the gamification package|Anexar o pacote de gamificação/i }), mode);
  await expectNoSurfaceOverlap(page, page.locator(".blocksDock"));
  const gamificationRow = page.locator(".attachRow").filter({ hasText: /Honest gamification|gamificação/i }).first();
  await activate(page, gamificationRow.locator(".attachButton"), mode);

  await expectGenesisStage(page, 5);
  await activate(page, page.getByRole("dialog", { name: GENESIS_STAGE_TITLES[5] }).getByRole("button", { name: /Attach the first source|Anexar a primeira fonte/i }), mode);
  await expectNoSurfaceOverlap(page, page.locator(".createSheet"));
  if (!(await page.locator(".createFormFields input").first().isVisible())) {
    await activate(page, page.locator(".createTypeRow.active"), mode);
  }
  await enterText(page, page.locator(".createFormFields input").first(), "Bank export", mode);
  await activate(page, page.locator(".createFormFoot button"), mode);

  await expectGenesisStage(page, 6);
  await activate(page, page.getByRole("dialog", { name: GENESIS_STAGE_TITLES[6] }).getByRole("button", { name: /Fly to outputs|Voar para Prática/i }), mode);
  await expectGenesisStage(page, 7);
  await activate(page, page.getByRole("dialog", { name: GENESIS_STAGE_TITLES[7] }).getByRole("button", { name: /Finish|Concluir/i }), mode);
  await expectGenesisStage(page, 8);
}

test("non-demo cockpit blocks missing operator instead of rendering sample data", async ({ page }) => {
  await page.goto("/w/radar");
  const alert = page.getByRole("alert");
  await expect(alert).toBeVisible({ timeout: 10000 });
  await expect(alert).toContainText("Real snapshot required");
  await expect(alert).toContainText(/sample fallback is blocked outside \/demo/i);
  await expect(page.locator("canvas")).toHaveCount(0);
});

test("demo cockpit can still render the bundled sample universe", async ({ page }) => {
  test.setTimeout(45_000);
  const network = watchDemoNetwork(page, { operatorBases: ["/api", "/operator"] });
  await installDelayedOperatorRuntime(page);
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.goto("/demo/w/radar");
  await expect(page.locator(".demoBanner")).toContainText(/read-only demo with synthetic data/i, { timeout: 10000 });
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20000 });
  // Config resolution is intentionally delayed and advertises /operator. A
  // direct demo load may read that public config, but must never touch the
  // advertised operator base/origin.
  network.assertClean();

  // Prove the harder SPA crossing: Work stays open with its live-log poll
  // expanded, then the route becomes /demo without a document reload. The
  // effect cleanup aborts in-flight reads and no interval can escape later.
  await page.goto("/w?center=root-alex-rivera&view=work&dock=work&visual=1&tour=0");
  const work = page.locator(".workDockPanel");
  await expect(work).toBeVisible({ timeout: 20_000 });
  await expect(work.getByText("observe crossing")).toBeVisible();
  await work.getByRole("button", { name: /Show (?:live )?log|Mostrar log/i }).click();
  await expect(work.locator(".workLog")).toContainText("safe live tail");

  network.markOperatorBoundary();
  await page.evaluate(() => {
    window.history.pushState({}, "", "/demo/w?center=root-alex-rivera&view=work&dock=work&visual=1&tour=0");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(page).toHaveURL(/\/demo\/w/);
  await expect(work).toContainText(/demo/i, { timeout: 20_000 });
  await page.waitForTimeout(2_700);
  await network.assertNoOperatorAfterMark();
});

test("demo mutation surfaces are visibly disabled and emit zero write requests", async ({ page, browser }, testInfo) => {
  // One cell covers every demo mutation surface plus the complete compact
  // touch journey. Keep the public matrix cardinality stable while allowing
  // real mobile taps and eight synthetic snapshot swaps to finish on CI.
  test.setTimeout(45_000);
  const network = watchDemoNetwork(page);
  await prepareDemo(page);

  await page.goto("/demo/w/radar?dock=gates&visual=1&tour=0");
  await expect(page.locator(".gatesDock")).toBeVisible({ timeout: 20_000 });
  const gateButtons = page.locator(".gateRunBtn, .gateChecksActions button");
  await expect(gateButtons.first()).toBeDisabled();
  await expect(gateButtons.first()).toHaveAttribute("title", /sends nothing to the local operator/i);
  for (let index = 0; index < await gateButtons.count(); index += 1) {
    await expect(gateButtons.nth(index)).toBeDisabled();
    await gateButtons.nth(index).evaluate((button: HTMLButtonElement) => button.click());
  }

  await page.goto("/demo/w/radar?dock=intake&visual=1&tour=0");
  await expect(page.locator(".intakeDock")).toBeVisible({ timeout: 20_000 });
  await page.getByPlaceholder(/statement\.pdf|extrato\.pdf/i).fill("/tmp/demo-preview.pdf");
  const add = page.getByRole("button", { name: /Add file|Adicionar arquivo/i });
  await expect(add).toBeDisabled();
  await add.evaluate((button: HTMLButtonElement) => button.click());

  await page.goto("/demo/w/radar?dock=create&visual=1&tour=0");
  const create = page.locator(".createSheet");
  await expect(create).toBeVisible({ timeout: 20_000 });
  await create.locator(".createForm input").first().fill("Preview person");
  const preview = create.getByRole("button", { name: /Preview only|Apenas prévia/i });
  await expect(preview).toBeDisabled();
  await expect(create.locator(".createGateNote")).toContainText(/never composes a brief.*opens a PR|nunca compõe um brief.*abre um PR/i);
  await preview.evaluate((button: HTMLButtonElement) => button.click());

  await page.goto("/demo/w/radar?dock=source&visual=1&tour=0");
  await expect(page.locator(".sourceDock")).toBeVisible({ timeout: 20_000 });
  await page.locator(".sourceListItem").first().click();
  await expect(page.locator(".sourceIdentity")).toBeVisible();
  const sourceMutation = page.locator(".sourceDock .btn--run");
  if (await sourceMutation.count()) {
    await expect(sourceMutation).toBeDisabled();
    await sourceMutation.evaluate((button: HTMLButtonElement) => button.click());
  }

  await page.goto("/demo/w/radar?dock=blocks&visual=1&tour=0");
  const blocks = page.locator(".blocksDock");
  await expect(blocks).toBeVisible({ timeout: 20_000 });
  const attachButtons = blocks.locator(".attachButton");
  for (let index = 0; index < await attachButtons.count(); index += 1) {
    await expect(attachButtons.nth(index)).toBeDisabled();
    await attachButtons.nth(index).evaluate((button: HTMLButtonElement) => button.click());
  }
  await blocks.locator(".blockRowMain").first().click();
  await expect(blocks.locator(".blockInspectTitle")).toBeVisible();

  await page.goto("/demo/pages/root-alex-rivera?visual=1&tour=0");
  const reader = page.locator(".pageReader");
  await expect(reader).toBeVisible({ timeout: 20_000 });
  await expect(reader.locator(".readerBody")).toBeVisible();
  const readerMutations = reader.locator(".readerActionBar button:disabled");
  expect(await readerMutations.count()).toBeGreaterThan(0);
  for (let index = 0; index < await readerMutations.count(); index += 1) {
    await readerMutations.nth(index).evaluate((button: HTMLButtonElement) => button.click());
  }
  await reader.getByRole("button", { name: /Add to packet|Adicionar ao pacote/i }).click();
  await reader.getByRole("button", { name: /Close reader|Fechar leitor/i }).click();
  await page.getByRole("button", { name: /Packet 1|Pacote 1/i }).click();
  const packet = page.locator(".packetTray");
  await expect(packet).toBeVisible({ timeout: 20_000 });
  const packetMutations = packet.locator(".packetActions button");
  expect(await packetMutations.count()).toBeGreaterThan(0);
  for (let index = 0; index < await packetMutations.count(); index += 1) {
    await expect(packetMutations.nth(index)).toBeDisabled();
    await packetMutations.nth(index).evaluate((button: HTMLButtonElement) => button.click());
  }
  await packet.locator(".readerClose").click();

  await page.locator(".missionsButton").click();
  const missions = page.locator(".missionsPanel");
  await expect(missions).toBeVisible({ timeout: 20_000 });
  const missionMutations = missions.locator("button:disabled");
  expect(await missionMutations.count()).toBeGreaterThan(0);
  for (let index = 0; index < await missionMutations.count(); index += 1) {
    await missionMutations.nth(index).evaluate((button: HTMLButtonElement) => button.click());
  }
  network.assertClean();

  await assertStageTwoMobileCreateLayout(browser, { width: 360, height: 800 }, testInfo);
  await assertStageTwoMobileCreateLayout(browser, { width: 390, height: 844 }, testInfo);

  const touchContext = await browser.newContext({
    baseURL: String(testInfo.project.use.baseURL),
    colorScheme: "dark",
    hasTouch: true,
    isMobile: true,
    locale: "pt-BR",
    screen: { width: 390, height: 844 },
    viewport: { width: 390, height: 844 }
  });
  try {
    const touchPage = await touchContext.newPage();
    const touchNetwork = watchDemoNetwork(touchPage);
    await completeGenesis(touchPage, "touch");
    touchNetwork.assertClean();
  } finally {
    await touchContext.close();
  }
});

test("Genesis still advances locally while emitting zero write requests", async ({ page }) => {
  const network = watchDemoNetwork(page);
  // This case proves local-only state and zero writes. Native Tab/Enter is a
  // separate first-class matrix cell, so use one deterministic pointer path
  // here instead of duplicating a second keyboard journey under GPU load.
  await completeGenesis(page, "pointer");
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-empty", "false");
  network.assertClean();
});
