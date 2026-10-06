import type { Page, TestInfo } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { test as evidenceTest, expect } from "../e2e/fixtures";
import { configureLanguage } from "../src/data/i18n";
import { registerContextPalette } from "../src/data/presentation";
import { localizedEncodingText, visualEncodingResolver } from "../src/data/visualEncoding";
import { focusColorToken } from "../src/scene/focusMap";
import type { GraphEdge, GraphNode, PageContent, PageRecord, SnapshotBundle } from "../src/types";
import type { OverlayId } from "../src/world/contracts";

declare global {
  interface Window { focusMapWebglCalls: number; }
}

const SCENARIO = "/sample-snapshot/scenarios/walking_skeleton";
const SOURCE_ID = "source-banco-export";
const EVENT_ID = "event-ingest-banco-2026-05";
const SOURCE_SIDECAR = "content/source-banco-export.21d8fe1f.json";
const SOURCE_URL = `${SCENARIO}/${SOURCE_SIDECAR}`;
const DEEP_LINK = `/demo/w?demo_scenario=walking_skeleton&projection=2d&page=${SOURCE_ID}&map_focus=${SOURCE_ID}&reader=1&tour=0`;
const SNAPSHOT_DIR = new URL("../public/sample-snapshot/scenarios/walking_skeleton/", import.meta.url);
const OUTPUT_DIR = fileURLToPath(new URL("../../../output/playwright/", import.meta.url));
const OVERLAYS: OverlayId[] = ["attention", "freshness", "actions", "ownership", "evidence", "quality"];

async function fixtureJson<T>(name: string): Promise<T> {
  return JSON.parse(await readFile(new URL(name, SNAPSHOT_DIR), "utf8")) as T;
}

// Read-only fixture records supply the oracle; these tests never rewrite a
// snapshot, canonical page, operator state, or the existing release gates.
const manifest = await fixtureJson<SnapshotBundle["manifest"]>("manifest.json");
const graph = await fixtureJson<{ nodes: GraphNode[]; edges: GraphEdge[] }>("graph.json");
const pages = (await fixtureJson<{ pages: PageRecord[] }>("pages.json")).pages;
const sourceContent = await fixtureJson<PageContent>(SOURCE_SIDECAR);
const byId = new Map(pages.map((page) => [page.id, page]));
configureLanguage("en"); // The committed walking_skeleton manifest declares en.
registerContextPalette(graph.nodes.map((node) => node.context || "system"));

type ReadOnlyRequest = { method: string; path: string };
const test = evidenceTest.extend<{ readOnlyBoundary: void }>({
  readOnlyBoundary: [async ({ page, baseURL }, use, testInfo) => {
    const origin = new URL(baseURL!).origin;
    const requests: ReadOnlyRequest[] = [];
    const violations: string[] = [];
    const pageErrors: string[] = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      requests.push({ method: request.method(), path: `${url.pathname}${url.search}` });
      if (request.method() !== "GET" || url.origin !== origin || /^\/(?:api|operator)(?:\/|$)/.test(url.pathname)) {
        violations.push(`${request.method()} ${url.origin}${url.pathname}`);
      }
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.route("**/*", (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (request.method() !== "GET" || url.origin !== origin || /^\/(?:api|operator)(?:\/|$)/.test(url.pathname)) return route.abort();
      return route.continue();
    });
    await page.addInitScript(() => {
      window.localStorage.clear();
      window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
      window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    });
    await use();
    await testInfo.attach("focus-2d-read-only-requests.json", {
      body: Buffer.from(JSON.stringify({ requests, violations, pageErrors }, null, 2)),
      contentType: "application/json"
    });
    expect(requests.length, "the actual browser journey must make snapshot reads").toBeGreaterThan(0);
    expect(violations, "every request must be a local GET outside the operator boundary").toEqual([]);
    expect(pageErrors, "the 2D projection must complete without browser exceptions").toEqual([]);
  }, { auto: true }]
});

function params(page: Page) { return new URL(page.url()).searchParams; }
const normalize = (value: string) => value.replace(/\s+/g, " ").trim();

async function openSource(page: Page, extra = "") {
  await page.goto(`${DEEP_LINK}${extra}`);
  await expect(page.getByTestId("focus-map")).toBeVisible();
  await expect(page.locator("#page-reader-title")).toHaveText(byId.get(SOURCE_ID)!.title);
  await expect(page.locator(".readerBody")).toContainText("A live Banco source.");
  await expect(page.locator("canvas")).toHaveCount(0);
}

async function expectSelection(page: Page, id: string, focus = SOURCE_ID) {
  await expect(page.locator("#page-reader-title")).toHaveText(byId.get(id)!.title);
  await expect(page.getByTestId("focus-reader").locator(".focusMapReaderLabel code")).toHaveText(byId.get(id)!.path);
  await expect.poll(() => params(page).get("page")).toBe(id);
  expect(params(page).get("reader")).toBe("1");
  expect(params(page).get("projection")).toBe("2d");
  expect(params(page).get("map_focus")).toBe(focus);
  expect(params(page).get("demo_scenario")).toBe("walking_skeleton");
  expect(params(page).get("tour")).toBe("0");
}

async function visibleNodeIds(page: Page) {
  return page.locator(".focusMapNode").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-testid")!.slice("focus-node-".length)).sort());
}

async function layoutRecords(page: Page) {
  return page.getByTestId("focus-svg").evaluate((svg) => ({
    nodes: [...svg.querySelectorAll("foreignObject")].map((node) => [node.getAttribute("x"), node.getAttribute("y"), node.querySelector("button")!.getAttribute("data-testid")]),
    edges: [...svg.querySelectorAll(".focusMapEdgeHit")].map((edge) => [edge.getAttribute("data-edge-id"), edge.getAttribute("d")])
  }));
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(",")}}`;
  return JSON.stringify(value);
}

async function capture(page: Page, testInfo: TestInfo, name: string) {
  await mkdir(OUTPUT_DIR, { recursive: true });
  const bytes = await page.screenshot({ path: `${OUTPUT_DIR}/${name}.png`, animations: "disabled", fullPage: false });
  await testInfo.attach(`${name}.png`, { body: bytes, contentType: "image/png" });
}

// Click a real hit-tested point on the SVG curve. Its bounding-box center can
// lie away from a quadratic path, so a rectangle click would not test the UI.
async function clickCurve(page: Page, edgeId: string) {
  const edge = page.locator(`.focusMapEdgeHit[data-edge-id="${edgeId}"]`);
  await edge.scrollIntoViewIfNeeded();
  const point = await edge.evaluate((element: SVGPathElement) => {
    const scroller = element.closest<HTMLElement>(".focusMapCanvas")!;
    const mid = element.getPointAtLength(element.getTotalLength() / 2).matrixTransform(element.getScreenCTM()!);
    const rect = scroller.getBoundingClientRect();
    scroller.scrollLeft += mid.x - (rect.left + rect.width / 2);
    scroller.scrollTop += mid.y - (rect.top + rect.height / 2);
    for (const fraction of [0.5, 0.4, 0.6, 0.3, 0.7]) {
      const candidate = element.getPointAtLength(element.getTotalLength() * fraction).matrixTransform(element.getScreenCTM()!);
      if (document.elementFromPoint(candidate.x, candidate.y) === element) return { x: candidate.x, y: candidate.y };
    }
    return null;
  });
  expect(point, `the distinct curve for ${edgeId} must expose a pointer hit target`).not.toBeNull();
  await page.mouse.click(point!.x, point!.y);
}

test("@shared restores source identity, independent map focus, and Back/Forward state", async ({ page }) => {
  const responsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === SOURCE_URL);
  await openSource(page, "&center=root-alex-rivera&map_color=category");
  const response = await responsePromise;
  const payload = await response.json() as PageContent;
  expect(payload).toEqual(sourceContent);
  expect(payload.page?.page_id).toBe(SOURCE_ID);
  expect(payload.snapshot_id).toBe(manifest.snapshot_id);
  expect(createHash("sha256").update(canonicalJson(payload)).digest("hex")).toBe(manifest.integrity![SOURCE_SIDECAR].sha256);
  await expect(page.locator(".focusMapSnapshot")).toContainText(manifest.snapshot_id!);
  await expectSelection(page, SOURCE_ID);

  await page.getByTestId("focus-node-claim-custos-sobem").click();
  await expectSelection(page, "claim-custos-sobem");
  expect(params(page).get("center")).toBe("root-alex-rivera");
  await page.getByTestId("map-list-mode").click();
  await expect(page.locator(".focusMapItemList")).toBeVisible();
  await page.goBack();
  await expect(page.getByTestId("focus-svg")).toBeVisible();
  await expectSelection(page, "claim-custos-sobem");
  await page.goBack();
  await expectSelection(page, SOURCE_ID);
  await page.goForward();
  await expectSelection(page, "claim-custos-sobem");
  await page.goForward();
  await expect(page.locator(".focusMapItemList")).toBeVisible();
  await page.reload();
  await expectSelection(page, "claim-custos-sobem");
  await expect(page.getByTestId("map-list-mode")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("Cor significa")).toHaveValue("category");
  expect(params(page).get("center")).toBe("root-alex-rivera");
});

test("@shared searches the snapshot index and follows canonical source references from list mode", async ({ page }) => {
  await openSource(page);
  const ids = await visibleNodeIds(page);
  const relationIds = await page.locator(".focusMapRelations button").evaluateAll((buttons) => buttons.map((button) => button.getAttribute("data-edge-id")).sort());
  await page.getByTestId("map-list-mode").click();
  const list = page.getByRole("list", { name: "Itens do mesmo foco" });
  expect((await list.locator("strong").allTextContents()).sort()).toEqual(ids.map((id) => byId.get(id)!.title).sort());
  expect(await page.locator(".focusMapRelations button").evaluateAll((buttons) => buttons.map((button) => button.getAttribute("data-edge-id")).sort())).toEqual(relationIds);

  const input = page.getByTestId("focus-search");
  await input.fill("Custos de nuvem");
  await expect(page.locator(".focusMapSearchResults button")).toHaveCount(1);
  await input.press("ArrowDown");
  await expect(page.locator(".focusMapSearchResults button")).toBeFocused();
  await page.keyboard.press("Enter");
  await expectSelection(page, "claim-custos-sobem", "claim-custos-sobem");
  await expect(page.locator(".readerBody")).toContainText("Content that lands in its quadrant interior.");
  await expect(page.locator(".focusMapReaderLabel")).toContainText("1 referências de fonte");
  await page.getByTestId("focus-reader").locator(".readerRelations").getByRole("button", { name: /Extrato do Banco/ }).click();
  await expectSelection(page, SOURCE_ID, "claim-custos-sobem");
  await expect(page.locator(".readerBody")).toContainText("A live Banco source.");
  await expect(page.getByTestId("focus-reader").locator(".readerProvenance code")).toHaveText(byId.get(SOURCE_ID)!.path);
});

test("@shared pins bare-entry focus and preserves selection when returning to the original cockpit", async ({ page }) => {
  test.setTimeout(45_000);
  await page.goto("/demo/w?demo_scenario=walking_skeleton&projection=2d&tour=0");
  await expect(page.getByTestId("focus-map")).toBeVisible();
  await expect.poll(() => params(page).get("map_focus")).toBe("root-alex-rivera");
  const originalIds = await visibleNodeIds(page);
  const hub = page.getByTestId("focus-node-hub-financeiro");
  await hub.click();
  await expectSelection(page, "hub-financeiro", "root-alex-rivera");
  expect(await visibleNodeIds(page)).toEqual(originalIds);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("focus-reader")).toHaveCount(0);
  expect(params(page).get("map_focus")).toBe("root-alex-rivera");
  expect(await visibleNodeIds(page)).toEqual(originalIds);
  await expect(hub).toBeFocused();
  await hub.press("Enter");
  await expectSelection(page, "hub-financeiro", "root-alex-rivera");
  await page.getByRole("button", { name: "Cockpit original ↗", exact: true }).click();
  await expect(page.getByTestId("focus-map")).toHaveCount(0);
  await expect(page.locator(".worldWorkspace")).toBeVisible({ timeout: 20_000 });
  await expect(page.locator("#page-reader-title")).toHaveText(byId.get("hub-financeiro")!.title);
  expect(params(page).get("projection")).toBeNull();
  expect(params(page).get("page")).toBe("hub-financeiro");
  expect(params(page).get("reader")).toBe("1");
  expect(params(page).get("demo_scenario")).toBe("walking_skeleton");
  expect(params(page).get("tour")).toBe("0");
  await page.goBack();
  await expectSelection(page, "hub-financeiro", "root-alex-rivera");
  expect(await visibleNodeIds(page)).toEqual(originalIds);
  await expect(page.locator("canvas")).toHaveCount(0);
});

test("@shared selects neighbors and expands only their reachable adjacency while retaining local focus", async ({ page }) => {
  await openSource(page);
  const originalIds = await visibleNodeIds(page);
  expect(originalIds).toEqual([SOURCE_ID, ...new Set(graph.edges.filter((edge) => edge.source === SOURCE_ID || edge.target === SOURCE_ID).flatMap((edge) => [edge.source, edge.target]).filter((id) => id !== SOURCE_ID))].sort());
  await page.getByTestId("focus-node-hub-financeiro").click();
  await expectSelection(page, "hub-financeiro");
  await expect(page.getByTestId("expand-current")).toBeEnabled();
  await page.getByTestId("expand-current").click();
  await expect(page.getByTestId("focus-node-root-alex-rivera")).toBeVisible();
  expect(await visibleNodeIds(page)).toEqual([...originalIds, "root-alex-rivera"].sort());
  expect(params(page).getAll("map_expand")).toEqual(["hub-financeiro"]);
  await expectSelection(page, "hub-financeiro");

  await page.getByTestId("focus-node-root-alex-rivera").click();
  await page.getByTestId("expand-current").click();
  await expect(page.getByTestId("focus-node-person-marina-costa")).toBeVisible();
  expect(await visibleNodeIds(page)).toHaveLength(7);
  await expect(page.getByTestId("focus-counts")).toContainText("7 de 8 itens");
  await expectSelection(page, "root-alex-rivera");
  await page.getByTestId("center-current").click();
  await expectSelection(page, "root-alex-rivera", "root-alex-rivera");
  expect(params(page).getAll("map_expand")).toEqual([]);
  expect(await visibleNodeIds(page)).toEqual(["hub-financeiro", "person-marina-costa", "root-alex-rivera"]);
  await page.goBack();
  await expectSelection(page, "root-alex-rivera");
  expect(await visibleNodeIds(page)).toHaveLength(7);
  await page.getByTestId("reset-expansion").click();
  expect(await visibleNodeIds(page)).toEqual(originalIds);
  await expect(page.locator(".focusMapSelection")).toContainText("Fora do foco atual.");
  await expectSelection(page, "root-alex-rivera");
});

test("@shared preserves and inspects all parallel and reciprocal source-event records", async ({ page }) => {
  await openSource(page);
  const ids = new Set(await visibleNodeIds(page));
  const expectedEdges = graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
  const paths = page.locator(".focusMapEdgeHit");
  expect(await paths.evaluateAll((edges) => edges.map((edge) => edge.getAttribute("data-edge-id")).sort())).toEqual(expectedEdges.map((edge) => edge.id).sort());
  const parallel = graph.edges.filter((edge) => [SOURCE_ID, EVENT_ID].includes(edge.source) && [SOURCE_ID, EVENT_ID].includes(edge.target));
  expect(parallel.map((edge) => edge.type).sort()).toEqual(["moc_parent", "source_emission", "source_ref"]);
  const curveRecords = await paths.evaluateAll((edges, edgeIds) => edges.filter((edge) => edgeIds.includes(edge.getAttribute("data-edge-id")!)).map((edge) => ({ key: edge.getAttribute("data-edge-key"), path: edge.getAttribute("d") })), parallel.map((edge) => edge.id!));
  expect(new Set(curveRecords.map((edge) => edge.key)).size).toBe(3);
  expect(new Set(curveRecords.map((edge) => edge.path)).size).toBe(3);

  for (const edge of parallel) {
    await clickCurve(page, edge.id!);
    const details = page.getByTestId("focus-edge-details");
    await expect(details.getByRole("heading", { level: 3 })).toHaveText(`Relação · ${edge.type}`);
    await expect(details.locator(".focusMapEdgeEndpoints button").nth(0)).toHaveText(byId.get(edge.source)!.title);
    await expect(details.locator(".focusMapEdgeEndpoints button").nth(1)).toHaveText(byId.get(edge.target)!.title);
    await expect(details.locator(".focusMapEdgeEndpoints > span")).toHaveText("→");
    for (const [key, value] of Object.entries({ "Direção": edge.direction, "Observada em": edge.observed_at, "Base": edge.basis, "Estado da relação": edge.status, ...edge.provenance })) {
      await expect(details.locator("dt").filter({ hasText: new RegExp(`^${key}$`) }).locator("+ dd")).toHaveText(value!);
    }
    await expect(details).toContainText("3 relações distintas entre estes itens");
    expect(params(page).get("map_edge")).toBe(`id:${encodeURIComponent(edge.id!)}`);
    await expectSelection(page, SOURCE_ID);
    await expect(page.locator(`.focusMapEdgeHit[data-edge-id="${edge.id}"]`).locator("..").locator(".focusMapEdgeLine")).toHaveAttribute("marker-end", "url(#focus-map-arrow)");
  }

  const emission = parallel.find((edge) => edge.type === "source_emission")!;
  await page.locator(`.focusMapRelations button[data-edge-id="${emission.id}"]`).click();
  const origin = page.getByTestId("focus-edge-details").getByRole("link", { name: /Ler página que registra esta relação/ });
  const href = new URL(await origin.getAttribute("href") || "", page.url());
  expect(href.searchParams.get("page")).toBe(EVENT_ID);
  expect(href.searchParams.get("map_focus")).toBe(SOURCE_ID);
  await origin.click();
  await expectSelection(page, EVENT_ID);
  await expect(page.locator(".readerBody")).toBeVisible();
});

test("@shared gives topic, category and every state metric their declared legend without moving the graph", async ({ page }) => {
  await openSource(page);
  const ids = new Set(await visibleNodeIds(page));
  const shownNodes = graph.nodes.filter((node) => ids.has(node.id));
  const originalLayout = await layoutRecords(page);
  const colorSelect = page.getByLabel("Cor significa");
  for (const mode of ["topic", "category"] as const) {
    await colorSelect.selectOption(mode);
    const counts = new Map<string, { label: string; color: string; count: number }>();
    for (const node of shownNodes) {
      const token = focusColorToken(node, mode);
      counts.set(token.key, { ...token, count: (counts.get(token.key)?.count || 0) + 1 });
      const button = page.getByTestId(`focus-node-${node.id}`);
      expect(await button.evaluate((element) => (element as HTMLElement).style.getPropertyValue("--focus-map-data-color").trim())).toBe(token.color);
      await expect(button.locator(":scope > span").last()).toHaveText(token.label);
    }
    expect((await page.locator(".focusMapLegend > span").allTextContents()).map(normalize).sort()).toEqual([...counts.values()].map((entry) => `${entry.label} ${entry.count}`).sort());
    await expect(page.locator(".focusMapLegend")).toHaveAttribute("aria-label", mode === "topic" ? "Legenda de tema / área" : "Legenda de categoria");
    expect(await layoutRecords(page)).toEqual(originalLayout);
  }
  await colorSelect.selectOption("state");
  for (const overlay of OVERLAYS) {
    await page.getByLabel("Métrica de estado").selectOption(overlay);
    for (const node of shownNodes) {
      const resolved = visualEncodingResolver.resolve(node, overlay);
      const button = page.getByTestId(`focus-node-${node.id}`);
      expect(resolved.dataBacked).toBe(true);
      expect(await button.evaluate((element) => (element as HTMLElement).style.getPropertyValue("--focus-map-data-color").trim())).toBe(resolved.color);
      await expect(button).toHaveAttribute("data-ring", resolved.ring);
      await expect(button.locator(":scope > span").last()).toHaveText(`${resolved.symbol} ${localizedEncodingText(resolved)}`);
    }
    const expectedLegend = visualEncodingResolver.legend(overlay, shownNodes).filter((entry) => entry.visibleCount > 0).map((entry) => normalize(`${entry.symbol} ${localizedEncodingText(entry)} ${entry.visibleCount}`)).sort();
    expect((await page.locator(".focusMapLegend > span").allTextContents()).map(normalize).sort()).toEqual(expectedLegend);
    expect(await layoutRecords(page)).toEqual(originalLayout);
    await expectSelection(page, SOURCE_ID);
  }
});

test("@shared supports keyboard search and relation selection without trapping the embedded reader", async ({ page }) => {
  await openSource(page);
  const reader = page.locator(".pageReader");
  await expect(reader).toHaveAttribute("role", "complementary");
  expect(await reader.getAttribute("aria-modal")).toBeNull();
  await page.getByTestId("map-list-mode").focus();
  await page.keyboard.press("/");
  await expect(page.getByTestId("focus-search")).toBeFocused();
  await page.getByTestId("focus-search").fill("Extrato do Banco");
  const sourceResult = page.locator(`.focusMapSearchResults button[data-page-id="${SOURCE_ID}"]`);
  await page.keyboard.press("ArrowDown");
  await expect(sourceResult).toBeFocused();
  await page.keyboard.press("Enter");
  await expectSelection(page, SOURCE_ID);
  if (page.viewportSize()!.width <= 1250) await expect(page.getByTestId("focus-reader")).toBeFocused();
  else await expect(sourceResult).toBeFocused();

  await reader.locator(".readerTypeChip").focus();
  await page.keyboard.press("Shift+Tab");
  expect(await reader.evaluate((element) => element.contains(document.activeElement))).toBe(false);
  expect(await page.getByTestId("focus-map").evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await reader.locator(".readerActionBar button:not(:disabled)").last().focus();
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("focus-reader").getByRole("button", { name: "Voltar à exploração", exact: true })).toBeFocused();
  expect(await reader.evaluate((element) => element.contains(document.activeElement))).toBe(false);

  // F belongs to the reader while it owns focus. The expanded reading dialog
  // traps Tab, then collapsing restores the same reader control.
  await page.getByTestId("map-list-mode").focus();
  await page.keyboard.press("f");
  await expect(reader).not.toHaveClass(/expanded/);
  const firstReaderControl = reader.locator(".readerTypeChip");
  const lastReaderControl = reader.locator(".readerActionBar button:not(:disabled)").last();
  await firstReaderControl.focus();
  await page.keyboard.press("f");
  await expect(reader).toHaveClass(/expanded/);
  await expect(reader).toHaveAttribute("role", "dialog");
  await expect(reader).toHaveAttribute("aria-modal", "true");
  await expect(reader).toBeFocused();
  await page.keyboard.press("/");
  await expect(page.getByTestId("focus-search")).not.toBeFocused();
  await firstReaderControl.focus();
  await page.keyboard.press("Shift+Tab");
  await expect(lastReaderControl).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(firstReaderControl).toBeFocused();
  await page.keyboard.press("f");
  await expect(reader).not.toHaveClass(/expanded/);
  await expect(firstReaderControl).toBeFocused();

  const edge = page.locator(".focusMapEdgeHit").first();
  await edge.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("focus-edge-details")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("focus-edge-details")).toHaveCount(0);
  await expect(edge).toBeFocused();
  await expectSelection(page, SOURCE_ID);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("focus-reader")).toHaveCount(0);
  await expect(sourceResult).toBeFocused();
  expect(params(page).get("reader")).toBeNull();
  expect(params(page).get("page")).toBeNull();
  expect(params(page).get("map_focus")).toBe(SOURCE_ID);
});

for (const invalid of ["revision", "integrity"] as const) {
  test(`@shared rejects ${invalid} failures in the canonical source sidecar`, async ({ page }) => {
    const forged = JSON.parse(JSON.stringify(sourceContent)) as PageContent;
    forged.body = "\n# Synthetic corruption marker\n\nTHIS_BODY_MUST_NEVER_RENDER.\n";
    if (invalid === "revision") forged.snapshot_id = "synthetic-other-snapshot";
    await page.route(`**${SOURCE_URL}`, (route) => route.fulfill({ json: forged }));
    await page.goto(DEEP_LINK);
    await expectSelection(page, SOURCE_ID);
    await expect(page.locator(".readerFallback")).toContainText(byId.get(SOURCE_ID)!.summary);
    await expect(page.locator(".readerFallback .readerNotice")).toBeVisible();
    await expect(page.locator(".readerBody")).toHaveCount(0);
    await expect(page.getByTestId("focus-reader")).not.toContainText("THIS_BODY_MUST_NEVER_RENDER");
    await expect(page.getByTestId("focus-reader").locator(".readerProvenance code")).toHaveText(byId.get(SOURCE_ID)!.path);
    await expect(page.locator("canvas")).toHaveCount(0);
  });
}

test("@shared removes crafted source, admin and intake docks before exposing any operator surface", async ({ page }) => {
  for (const dock of ["source", "admin", "intake"]) {
    await page.goto(`${DEEP_LINK}&dock=${dock}&tray=packet&pack_view=synthetic.read-only-probe`);
    await expect(page.getByTestId("focus-map")).toBeVisible();
    await expect.poll(() => params(page).get("dock")).toBeNull();
    expect(params(page).get("tray")).toBeNull();
    expect(params(page).get("pack_view")).toBeNull();
    await expect(page.locator(".sourceDock, .adminDock, .intakeDock, .packetTray, .workDockPanel, .sourceWorkspace")).toHaveCount(0);
    await expect(page.locator("canvas")).toHaveCount(0);
    await page.getByTestId(`focus-node-${SOURCE_ID}`).click();
    await expectSelection(page, SOURCE_ID);
    await expect(page.locator(".readerBody")).toContainText("A live Banco source.");
  }
});

test("@desktop records the synthetic graph, canonical reader and relation provenance", async ({ page }, testInfo) => {
  await openSource(page);
  await capture(page, testInfo, "focus-2d-desktop");
  const emission = graph.edges.find((edge) => edge.source === SOURCE_ID && edge.target === EVENT_ID && edge.type === "source_emission")!;
  await page.locator(`.focusMapRelations button[data-edge-id="${emission.id}"]`).click();
  await page.getByTestId("focus-edge-details").scrollIntoViewIfNeeded();
  await expect(page.getByTestId("focus-edge-details")).toContainText(emission.provenance!.path);
  await capture(page, testInfo, "focus-2d-desktop-provenance");
});

test("@mobile offers a practical list and canonical source reading without page overflow", async ({ page }, testInfo) => {
  await openSource(page);
  await page.getByTestId("map-list-mode").click();
  await page.getByTestId("focus-search").fill("Extrato do Banco");
  const list = page.getByRole("list", { name: "Itens do mesmo foco" });
  await list.scrollIntoViewIfNeeded();
  const geometry = await list.evaluate((element) => {
    const buttons = [...element.querySelectorAll("button")].map((button) => {
      const rect = button.getBoundingClientRect();
      return { width: rect.width, height: rect.height, left: rect.left, right: rect.right, overflow: button.scrollWidth - button.clientWidth };
    });
    const map = document.querySelector<HTMLElement>(".focusMap")!;
    return { viewport: innerWidth, documentOverflow: document.documentElement.scrollWidth - innerWidth, mapOverflow: map.scrollWidth - map.clientWidth, buttons };
  });
  expect(geometry.viewport).toBe(390);
  expect(geometry.documentOverflow).toBeLessThanOrEqual(1);
  expect(geometry.mapOverflow).toBeLessThanOrEqual(1);
  for (const button of geometry.buttons) {
    expect(button.width).toBeGreaterThanOrEqual(300);
    expect(button.height).toBeGreaterThanOrEqual(44);
    expect(button.left).toBeGreaterThanOrEqual(0);
    expect(button.right).toBeLessThanOrEqual(391);
    expect(button.overflow).toBeLessThanOrEqual(1);
  }
  await capture(page, testInfo, "focus-2d-mobile-list");
  const eventOpener = list.getByRole("button", { name: /Ingestão: extrato do banco/ });
  await eventOpener.click();
  await expectSelection(page, EVENT_ID);
  const reader = page.getByTestId("focus-reader");
  await expect(reader).toBeFocused();
  const automaticReaderPosition = await reader.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return { top: rect.top, right: rect.right, left: rect.left, bottom: rect.bottom, viewportHeight: innerHeight };
  });
  expect(automaticReaderPosition.top).toBeGreaterThanOrEqual(0);
  expect(automaticReaderPosition.top).toBeLessThan(automaticReaderPosition.viewportHeight / 2);
  expect(automaticReaderPosition.left).toBeGreaterThanOrEqual(0);
  expect(automaticReaderPosition.right).toBeLessThanOrEqual(391);
  await expect(reader.locator(".readerBody")).toBeVisible();
  await capture(page, testInfo, "focus-2d-mobile-reader");
  await reader.getByRole("button", { name: "Voltar à exploração", exact: true }).click();
  await expect(eventOpener).toBeFocused();
  await expect(eventOpener).toBeInViewport({ ratio: 0.8 });
  await expectSelection(page, EVENT_ID);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
});

test("@reduced keeps the 2D projection free of WebGL and motion", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    const getContext = HTMLCanvasElement.prototype.getContext;
    window.focusMapWebglCalls = 0;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, ...args: Parameters<typeof getContext>) {
      if (String(args[0]).toLowerCase().includes("webgl")) window.focusMapWebglCalls += 1;
      return Reflect.apply(getContext, this, args);
    } as typeof getContext;
  });
  await openSource(page);
  expect(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(true);
  const before = await layoutRecords(page);
  await page.getByTestId("focus-node-hub-financeiro").click();
  await page.getByTestId("expand-current").click();
  await page.getByLabel("Cor significa").selectOption("state");
  await expect(page.locator("canvas")).toHaveCount(0);
  const motion = await page.getByTestId("focus-map").evaluate((map) => ({
    webglCalls: window.focusMapWebglCalls,
    animations: map.getAnimations({ subtree: true }).filter((animation) => animation.playState === "running").length,
    styledMotion: [...map.querySelectorAll<HTMLElement>("*")].filter((element) => {
      const style = getComputedStyle(element);
      return style.animationName !== "none" || style.transitionDuration.split(",").some((duration) => Number.parseFloat(duration) > 0);
    }).length
  }));
  expect(motion).toEqual({ webglCalls: 0, animations: 0, styledMotion: 0 });
  await page.getByTestId("reset-expansion").click();
  expect(await layoutRecords(page)).toEqual(before);
  await capture(page, testInfo, "focus-2d-reduced-motion");
});
