import type { Page, TestInfo } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { test as evidenceTest, expect } from "../e2e/fixtures";
import { configureLanguage, t } from "../src/data/i18n";
import { registerContextPalette } from "../src/data/presentation";
import { localizedEncodingText, visualEncodingResolver } from "../src/data/visualEncoding";
import { focusColorToken } from "../src/scene/focusMap";
import type { GraphEdge, GraphNode, PageContent, PageRecord, SnapshotBundle } from "../src/types";
import type { OverlayId } from "../src/world/contracts";

const SCENARIO = "/sample-snapshot/scenarios/walking_skeleton";
const SOURCE_ID = "source-banco-export";
const EVENT_ID = "event-ingest-banco-2026-05";
const SOURCE_SIDECAR = "content/source-banco-export.21d8fe1f.json";
const SOURCE_URL = `${SCENARIO}/${SOURCE_SIDECAR}`;
const DEEP_LINK = `/demo/w?demo_scenario=walking_skeleton&projection=2d&page=${SOURCE_ID}&map_focus=${SOURCE_ID}&reader=1&tour=0`;
const SNAPSHOT_DIR = new URL("../public/sample-snapshot/scenarios/walking_skeleton/", import.meta.url);
const OUTPUT_DIR = fileURLToPath(new URL("../../../output/playwright/connected-map/", import.meta.url));
const OVERLAYS: OverlayId[] = ["attention", "freshness", "actions", "ownership", "evidence", "quality"];

async function fixtureJson<T>(name: string): Promise<T> {
  return JSON.parse(await readFile(new URL(name, SNAPSHOT_DIR), "utf8")) as T;
}
const manifest = await fixtureJson<SnapshotBundle["manifest"]>("manifest.json");
const graph = await fixtureJson<{ nodes: GraphNode[]; edges: GraphEdge[] }>("graph.json");
const overviewGraph = JSON.parse(await readFile(new URL("../public/sample-snapshot/graph.json", import.meta.url), "utf8")) as typeof graph;
const pages = (await fixtureJson<{ pages: PageRecord[] }>("pages.json")).pages;
const sourceContent = await fixtureJson<PageContent>(SOURCE_SIDECAR);
const byId = new Map(pages.map(page => [page.id, page]));
// The committed public fixture remains English. Override only the browser's
// runtime UI language, using the same supported configuration precedence.
configureLanguage("pt");
registerContextPalette(graph.nodes.map(node => node.context || "system"));

const test = evidenceTest.extend<{ readOnlyBoundary: void }>({
  readOnlyBoundary: [async ({ page, baseURL }, use, testInfo) => {
    const origin = new URL(baseURL!).origin;
    const requests: { method: string; path: string }[] = [];
    const violations: string[] = [], pageErrors: string[] = [];
    page.on("request", request => {
      const url = new URL(request.url());
      requests.push({ method: request.method(), path: `${url.pathname}${url.search}` });
      if (request.method() !== "GET" || url.origin !== origin || /^\/(?:api|operator)(?:\/|$)/.test(url.pathname)) {
        violations.push(`${request.method()} ${url.origin}${url.pathname}`);
      }
    });
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.route("**/*", route => {
      const request = route.request(), url = new URL(request.url());
      if (request.method() !== "GET" || url.origin !== origin || /^\/(?:api|operator)(?:\/|$)/.test(url.pathname)) return route.abort();
      return route.continue();
    });
    await page.route("**/wiki-cockpit.config.json", async route => {
      const response = await route.fetch();
      await route.fulfill({ json: { ...await response.json(), language: "pt" } });
    });
    await page.addInitScript(() => {
      localStorage.clear();
      localStorage.setItem("wikiCockpitTourDone.v1", "1");
      localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    });
    await use();
    await testInfo.attach("connected-map-read-only-requests.json", {
      body: Buffer.from(JSON.stringify({ requests, violations, pageErrors }, null, 2)), contentType: "application/json"
    });
    expect(requests.length).toBeGreaterThan(0);
    expect(violations, "snapshot journeys must stay within local GET reads").toEqual([]);
    expect(pageErrors, "journeys must finish without browser exceptions").toEqual([]);
  }, { auto: true }]
});

const params = (page: Page) => new URL(page.url()).searchParams;
const normalize = (value: string) => value.replace(/\s+/g, " ").trim();

async function settled(page: Page) {
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-layout-motion", "settled");
  await page.waitForTimeout(450); // Camera is a separate, bounded 320ms transition.
}
async function openSource(page: Page, extra = "") {
  await page.goto(`${DEEP_LINK}${extra}`);
  await expect(page.getByTestId("focus-map")).toBeVisible();
  await expect(page.locator("#page-reader-title")).toHaveText(byId.get(SOURCE_ID)!.title);
  await expect(page.locator(".readerBody")).toContainText("A live Banco source.");
  await expect(page.locator("canvas")).toHaveCount(0);
  await settled(page);
}
async function expectSelection(page: Page, id: string, focus = SOURCE_ID) {
  await expect.poll(() => params(page).get("page")).toBe(id);
  expect(params(page).get("projection")).toBe("2d");
  expect(params(page).get("map_focus")).toBe(focus);
  expect(params(page).get("demo_scenario")).toBe("walking_skeleton");
  if (params(page).get("reader") === "1" && !params(page).get("map_edge")) {
    await expect(page.locator("#page-reader-title")).toHaveText(byId.get(id)!.title);
    await expect(page.getByTestId("focus-reader").locator(".focusMapReaderLabel code")).toHaveText(byId.get(id)!.path);
  } else if (!params(page).get("map_edge")) {
    await expect(page.locator(".focusMapInspectorHeader h2")).toHaveText(byId.get(id)!.title);
  }
}
async function visibleNodeIds(page: Page) {
  return page.locator(".focusMapNode").evaluateAll(nodes => nodes.map(node => node.getAttribute("data-testid")!.slice("focus-node-".length)).sort());
}
async function edgeIds(page: Page) {
  return page.locator(".focusMapEdgeHit").evaluateAll(edges => edges.map(edge => edge.getAttribute("data-edge-id")).sort());
}
async function layoutRecords(page: Page) {
  return page.getByTestId("focus-svg").evaluate((svg,records) => {
    const centers=new Map([...svg.querySelectorAll("foreignObject")].map(node=>[node.querySelector("button")!.getAttribute("data-testid")!.slice("focus-node-".length),{x:Number(node.getAttribute("x"))+Number(node.getAttribute("width"))/2,y:Number(node.getAttribute("y"))+Number(node.getAttribute("height"))/2}]));
    const scale=Math.hypot(svg.querySelector<SVGGElement>(":scope > g")!.getScreenCTM()!.a,svg.querySelector<SVGGElement>(":scope > g")!.getScreenCTM()!.b);
    return {
      nodes:[...centers].map(([id,point])=>[point.x.toFixed(3),point.y.toFixed(3),`focus-node-${id}`]),
      // Resizing a legend changes fit scale. Compare fixed page centers and
      // the lane's screen-space offset, as implemented for screen-sized hits.
      edges:[...svg.querySelectorAll(".focusMapEdgeHit")].map(edge=>{
        const id=edge.getAttribute("data-edge-id"),record=records.find(record=>record.id===id)!,source=centers.get(record.source)!,target=centers.get(record.target)!,control=edge.getAttribute("d")!.match(/Q (-?[\d.]+) (-?[\d.]+)/)!.slice(1).map(Number);
        return [id,[(control[0]-(source.x+target.x)/2)*Math.min(1,scale),(control[1]-(source.y+target.y)/2)*Math.min(1,scale)].map(value=>Number(value.toFixed(2))||0)];
      })
    };
  },graph.edges);
}
function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(",")}}`;
  return JSON.stringify(value);
}
async function capture(page: Page, testInfo: TestInfo, name: string) {
  await mkdir(OUTPUT_DIR, { recursive: true });
  const filename = `${testInfo.project.name}-${name}.png`;
  const bytes = await page.screenshot({ path: `${OUTPUT_DIR}/${filename}`, animations: "disabled", fullPage: false });
  await testInfo.attach(filename, { body: bytes, contentType: "image/png" });
}
async function curvePoint(page: Page, edgeId: string) {
  const edge = page.locator(`.focusMapEdgeHit[data-edge-id="${edgeId}"]`);
  const point = await edge.evaluate((element: SVGPathElement) => {
    for (const fraction of [.5, .4, .6, .3, .7, .2, .8, .1, .9]) {
      const point = element.getPointAtLength(element.getTotalLength() * fraction).matrixTransform(element.getScreenCTM()!);
      const hit=document.elementFromPoint(point.x, point.y);
      if (hit === element || hit?.getAttribute("data-edge-owner")===element.getAttribute("data-edge-key")) return { x: point.x, y: point.y };
    }
    return null;
  });
  expect(point, `${edgeId} must expose a real pointer hit on its curve`).not.toBeNull();
  return point!;
}
async function clickCurve(page: Page, edgeId: string) {
  const point=await curvePoint(page,edgeId);
  await page.mouse.click(point.x,point.y);
}

async function backgroundPoint(page:Page) {
  return page.getByTestId("focus-svg").evaluate(svg=>{
    const box=svg.getBoundingClientRect();
    for(const [dx,dy] of [[8,8],[box.width-8,8],[8,box.height-60],[box.width-8,box.height-60]]) {
      const x=box.x+dx,y=box.y+dy,hit=document.elementFromPoint(x,y);
      if(hit===svg)return {x,y};
    }
    throw new Error("No clear background point available");
  });
}

test("@shared explores neighbors and actionable human previews without navigating, then pins an exact edge across perspectives",async({page},testInfo)=>{
  await openSource(page);
  const before=page.url(),body=await page.locator(".readerBody").innerText(),ids=new Set(await visibleNodeIds(page));
  const shownEdges=new Set(await edgeIds(page)),hoverId="claim-custos-sobem";
  const neighbors=new Set([hoverId]);
  graph.edges.filter(edge=>shownEdges.has(edge.id!)).forEach(edge=>{if(edge.source===hoverId)neighbors.add(edge.target);if(edge.target===hoverId)neighbors.add(edge.source);});
  await page.getByTestId(`focus-node-${hoverId}`).hover();
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-active-id",hoverId);
  expect(await page.locator(".focusMapNodeGroup.highlighted").evaluateAll(nodes=>nodes.map(node=>node.getAttribute("data-node-id")).sort())).toEqual([...neighbors].sort());
  for(const id of ids)await expect(page.getByTestId(`focus-node-${id}`).locator("../..")).toHaveClass(neighbors.has(id)?/highlighted/:/muted/);
  await expect(page.getByTestId("map-tooltip")).toContainText(byId.get(hoverId)!.title);
  expect(page.url()).toBe(before);expect(await page.locator(".readerBody").innerText()).toBe(body);
  await page.mouse.move(2,2);await expect(page.getByTestId("map-tooltip")).toHaveCount(0);
  // The old selected source is deliberately not one of this edge's endpoints.
  const record=graph.edges.find(edge=>shownEdges.has(edge.id!)&&edge.type==="impact"&&edge.source!==SOURCE_ID&&edge.target!==SOURCE_ID&&edge.target==="artifact-relatorio-recon")!;
  const point=await curvePoint(page,record.id!);await page.mouse.move(point.x,point.y);
  await expect(page.getByTestId("map-tooltip")).toContainText(t(`map.rel.${record.type}`));
  await expect(page.getByTestId("map-tooltip")).toContainText(byId.get(record.source)!.title);
  await expect(page.getByTestId("map-tooltip")).toContainText(byId.get(record.target)!.title);
  expect(await page.locator(".focusMapNodeGroup.highlighted").evaluateAll(nodes=>nodes.map(node=>node.getAttribute("data-node-id")).sort())).toEqual([record.source,record.target].sort());
  await expect(page.getByTestId(`focus-node-${SOURCE_ID}`).locator("../..")).toHaveClass(/muted/);
  expect(page.url()).toBe(before);expect(await page.locator(".readerBody").innerText()).toBe(body);
  // A real move from the curve into its action cancels the delayed exit.
  const action=page.getByTestId("map-tooltip-inspect"),box=await action.boundingBox();
  await page.mouse.move(box!.x+box!.width/2,box!.y+box!.height/2,{steps:8});
  await page.waitForTimeout(650);await expect(action).toBeVisible();
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-active-id",`id:${encodeURIComponent(record.id!)}`);
  await expect(page.getByTestId("map-tooltip")).toContainText(byId.get(record.source)!.title);
  await expect(page.getByTestId("map-tooltip")).toContainText(byId.get(record.target)!.title);
  await capture(page,testInfo,"hover-connection");await action.click();
  const key=`id:${encodeURIComponent(record.id!)}`;
  await expect.poll(()=>params(page).get("map_edge")).toBe(key);
  await expect(page.getByTestId("map-canvas")).toBeFocused();
  // The action was removed: Escape must work without artificially moving focus.
  await page.keyboard.press("Escape");await expect.poll(()=>params(page).get("map_edge")).toBeNull();
  expect(params(page).get("page")).toBeNull();
  await clickCurve(page,record.id!);await expect.poll(()=>params(page).get("map_edge")).toBe(key);
  await page.mouse.move(2,2);await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-active-id",key);
  await page.getByTestId("focus-edge-details").locator(".focusMapOriginalRecord summary").click();
  expect(JSON.parse(await page.getByTestId("map-original-record").innerText())).toEqual(record);
  const other=graph.edges.find(edge=>shownEdges.has(edge.id!)&&edge.type==="source_ref"&&edge.source==="claim-custos-sobem")!;
  const otherPoint=await curvePoint(page,other.id!);await page.mouse.move(otherPoint.x,otherPoint.y);
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-active-id",`id:${encodeURIComponent(other.id!)}`);
  await expect(page.locator(`.focusMapEdgeHit[data-edge-id="${record.id}"]`).locator("..")).toHaveClass(/muted/);
  expect(params(page).get("map_edge")).toBe(key);
  await page.mouse.move(2,2);await expect(page.getByTestId("map-tooltip")).toHaveCount(0);
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-active-id",key);
  for(const perspective of ["areas","evidence","work","network"]) {
    await page.getByTestId(`map-perspective-${perspective}`).click();await settled(page);
    expect(params(page).get("map_edge")).toBe(key);expect(params(page).get("map_focus")).toBe(SOURCE_ID);
    expect(await page.locator(".focusMapNodeGroup.highlighted").evaluateAll(nodes=>nodes.map(node=>node.getAttribute("data-node-id")).sort())).toEqual([record.source,record.target].sort());
  }
  const background=await backgroundPoint(page);
  await page.mouse.move(background.x,background.y);await page.mouse.down();await page.mouse.move(background.x+20,background.y+20,{steps:4});await page.mouse.up();
  expect(params(page).get("map_edge")).toBe(key); // A pan is not a clear action.
  const blank=await backgroundPoint(page);await page.mouse.click(blank.x,blank.y);
  await expect.poll(()=>params(page).get("map_edge")).toBeNull();
  expect(params(page).get("page")).toBeNull();expect(params(page).get("map_focus")).toBe(SOURCE_ID);
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-active-kind","");
});

test("@shared reaches connections and their preview action by keyboard, pins with Enter and clears with Escape",async({page})=>{
  await openSource(page);const before=page.url();
  await page.getByTestId(`focus-node-${SOURCE_ID}`).focus();await page.keyboard.press("e");
  const focusedKey=await page.evaluate(()=>document.activeElement?.getAttribute("data-edge-key"));expect(focusedKey).toBeTruthy();
  await expect(page.locator('.focusMapEdgeHit[tabindex="0"]')).toHaveCount(1);
  await expect(page.getByTestId("map-tooltip")).toHaveAttribute("role","dialog");
  expect(page.url()).toBe(before);
  await page.keyboard.press("Tab");await expect(page.getByTestId("map-tooltip").getByRole("button",{name:t("map.clearHighlight")})).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  expect(await page.evaluate(()=>document.activeElement?.getAttribute("data-edge-key"))).toBe(focusedKey);
  await page.keyboard.press("ArrowRight");
  const nextKey=await page.evaluate(()=>document.activeElement?.getAttribute("data-edge-key"));expect(nextKey).not.toBe(focusedKey);
  expect(page.url()).toBe(before);
  await page.keyboard.press("Enter");await expect.poll(()=>params(page).get("map_edge")).toBe(nextKey);
  await page.keyboard.press("Escape");
  await expect.poll(()=>params(page).get("map_edge")).toBeNull();expect(params(page).get("page")).toBeNull();
  await expect(page.getByTestId("map-tooltip")).toHaveCount(0);await expect(page.getByTestId("map-canvas")).toBeFocused();
  expect(params(page).get("map_focus")).toBe(SOURCE_ID);
  await page.getByTestId(`focus-node-${SOURCE_ID}`).focus();await page.keyboard.press("e");
  const actionKey=await page.evaluate(()=>document.activeElement?.getAttribute("data-edge-key"));
  await page.keyboard.press("Tab");await page.keyboard.press("Tab");
  await expect(page.getByTestId("map-tooltip-inspect")).toBeFocused();
  await page.keyboard.press("Enter");await expect.poll(()=>params(page).get("map_edge")).toBe(actionKey);
  await expect(page.getByTestId("map-canvas")).toBeFocused();
  await page.keyboard.press("Escape");await expect.poll(()=>params(page).get("map_edge")).toBeNull();
  await expect(page.getByTestId("map-canvas")).toBeFocused();
});

test("@shared keeps relation colors and strokes consistent with the legend and recorded direction",async({page})=>{
  await openSource(page);
  const rows=await page.locator(".focusMapEdge").evaluateAll(edges=>edges.map(edge=>{const line=edge.querySelector(".focusMapEdgeLine")!,css=getComputedStyle(line);return {type:edge.getAttribute("data-relation-type"),id:edge.querySelector(".focusMapEdgeHit")!.getAttribute("data-edge-id"),color:css.stroke,dash:css.strokeDasharray,arrow:line.hasAttribute("marker-end")};}));
  for(const row of rows) {
    const swatch=page.locator(`.focusMapRelationLegend [data-relation-type="${row.type}"] path`);
    expect(await swatch.evaluate(path=>({color:getComputedStyle(path).stroke,dash:getComputedStyle(path).strokeDasharray}))).toEqual({color:row.color,dash:row.dash});
    expect(row.arrow).toBe(graph.edges.find(edge=>edge.id===row.id)!.direction==="directed");
  }
  const distinct=new Map(rows.map(row=>[row.type,`${row.color}/${row.dash}`]));
  expect(new Set(distinct.values()).size).toBe(distinct.size);
});

test("@desktop @mobile preserves a real screen-sized edge hit band at overview and zoom-out scales",async({page},testInfo)=>{
  await openSource(page);await page.getByLabel(t("map.motion"),{exact:true}).uncheck();
  const measurements=[];
  for(let level=0;level<4;level++) {
    if(level)await page.getByRole("button",{name:t("map.zoomOut"),exact:true}).click();
    const band=await page.getByTestId("focus-svg").evaluate(svg=>{
      const box=svg.getBoundingClientRect();
      for(const edge of svg.querySelectorAll<SVGPathElement>(".focusMapEdgeHit"))for(const fraction of [.5,.4,.6,.3,.7,.2,.8]) {
        const length=edge.getTotalLength(),matrix=edge.getScreenCTM()!,point=edge.getPointAtLength(length*fraction).matrixTransform(matrix),a=edge.getPointAtLength(length*fraction-1).matrixTransform(matrix),b=edge.getPointAtLength(length*fraction+1).matrixTransform(matrix),distance=Math.hypot(b.x-a.x,b.y-a.y),nx=-(b.y-a.y)/distance,ny=(b.x-a.x)/distance;
        if(point.x<box.x+12||point.x>box.right-12||point.y<box.y+12||point.y>box.bottom-60)continue;
        if([-8,0,8].every(offset=>{const hit=document.elementFromPoint(point.x+nx*offset,point.y+ny*offset);return hit===edge||hit?.getAttribute("data-edge-owner")===edge.dataset.edgeKey;}))return {id:edge.dataset.edgeId,offsets:[-8,0,8]};
      }
      return null;
    });
    const declared=await page.locator(".focusMapEdgeHit").evaluateAll(edges=>edges.map(edge=>({width:getComputedStyle(edge).strokeWidth,effect:getComputedStyle(edge).vectorEffect})));
    expect(declared.every(edge=>edge.width==="18px"&&edge.effect==="non-scaling-stroke")).toBe(true);
    if(!band) {
      // At the last compact mobile zoom the fixed-size nodes cover the curves.
      // Record this obstruction explicitly; no pointer reachability is claimed.
      expect(level).toBe(3);expect(page.viewportSize()!.width).toBe(390);
    }
    measurements.push({scale:await page.getByTestId("map-canvas").getAttribute("data-camera-scale"),band,obstructed:!band});
  }
  expect(measurements.filter(row=>row.band).length).toBeGreaterThanOrEqual(3);
  await testInfo.attach("real-edge-hit-band.json",{body:Buffer.from(JSON.stringify(measurements)),contentType:"application/json"});
});

test("@desktop snaps an interrupted camera to its pending destination through real controls and reduced motion",async({page})=>{
  await openSource(page);await page.clock.install();await page.clock.pauseAt(new Date(Date.now()+1000));
  const group=page.getByTestId("focus-svg").locator(":scope > g"),fitted=await group.getAttribute("transform");
  for(const reason of ["pause","reduced"] as const) {
    await page.getByRole("button",{name:t("map.zoomOut"),exact:true}).evaluate((button:HTMLButtonElement)=>button.click());
    await page.getByRole("button",{name:t("map.fit"),exact:true}).evaluate((button:HTMLButtonElement)=>button.click());
    await page.clock.runFor(80);expect(await group.getAttribute("transform")).not.toBe(fitted);
    await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-camera-motion","moving");
    if(reason==="pause")await page.getByLabel(t("map.motion"),{exact:true}).evaluate((input:HTMLInputElement)=>input.click());
    else await page.emulateMedia({reducedMotion:"reduce"});
    await page.clock.runFor(16);await expect(group).toHaveAttribute("transform",fitted!);
    await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-camera-motion","settled");
    if(reason==="pause")await page.getByLabel(t("map.motion"),{exact:true}).evaluate((input:HTMLInputElement)=>input.click());
    else await page.emulateMedia({reducedMotion:"no-preference"});
    await page.clock.runFor(16);
  }
});

test("@mobile pins an exact connection by touch and clears it by a background tap",async({page})=>{
  await openSource(page);const record=graph.edges.find(edge=>edge.source===SOURCE_ID&&edge.type==="source_emission")!;
  const point=await curvePoint(page,record.id!);await page.touchscreen.tap(point.x,point.y);
  await expect.poll(()=>params(page).get("map_edge")).toBe(`id:${encodeURIComponent(record.id!)}`);
  await expect(page.getByTestId("focus-edge-details").locator("h2")).toHaveText(t(`map.rel.${record.type}`));
  await page.getByTestId("map-perspective-evidence").tap();await settled(page);
  expect(params(page).get("map_edge")).toBe(`id:${encodeURIComponent(record.id!)}`);
  const blank=await backgroundPoint(page);await page.touchscreen.tap(blank.x,blank.y);
  await expect.poll(()=>params(page).get("map_edge")).toBeNull();expect(params(page).get("page")).toBeNull();
});

test("@shared preserves canonical revision, selection and context through perspectives, reload and Back/Forward", async ({ page }) => {
  const responsePromise = page.waitForResponse(response => new URL(response.url()).pathname === SOURCE_URL);
  await openSource(page, "&center=root-alex-rivera&map_color=category");
  const payload = await (await responsePromise).json() as PageContent;
  expect(payload).toEqual(sourceContent);
  expect(createHash("sha256").update(canonicalJson(payload)).digest("hex")).toBe(manifest.integrity![SOURCE_SIDECAR].sha256);
  await page.locator(".focusMapSnapshot summary").click();
  await expect(page.locator(".focusMapSnapshot")).toContainText(manifest.snapshot_id!);
  const originalIds = await visibleNodeIds(page), originalEdges = await edgeIds(page);
  await page.getByTestId("focus-node-claim-custos-sobem").click();
  await expectSelection(page, "claim-custos-sobem");
  for (const perspective of ["areas", "evidence", "work"]) {
    await page.getByTestId(`map-perspective-${perspective}`).click();
    await settled(page);
    await expectSelection(page, "claim-custos-sobem");
    expect(await visibleNodeIds(page)).toEqual(originalIds);
    expect(await edgeIds(page)).toEqual(originalEdges);
    expect(params(page).get("center")).toBe("root-alex-rivera");
  }
  await page.goBack();
  await expect(page.getByTestId("map-perspective-evidence")).toHaveAttribute("aria-pressed", "true");
  await page.goForward();
  await expect(page.getByTestId("map-perspective-work")).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await expectSelection(page, "claim-custos-sobem");
  await expect(page.getByTestId("map-perspective-work")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel(t("map.color"))).toHaveValue("category");
});

test("@shared searches the whole index without recentering and reads source references in the same map", async ({ page }) => {
  await openSource(page);
  const ids = await visibleNodeIds(page);
  await page.getByTestId("map-list-mode").click();
  const list = page.locator(".focusMapItemList");
  expect((await list.locator("strong").allTextContents()).sort()).toEqual(ids.map(id => byId.get(id)!.title).sort());
  const input = page.getByTestId("focus-search");
  await input.fill("Custos de nuvem");
  await expect(page.locator(".focusMapSearchResults button")).toHaveCount(1);
  await input.press("ArrowDown");
  await expect(page.locator(".focusMapSearchResults button")).toBeFocused();
  await page.keyboard.press("Enter");
  await expectSelection(page, "claim-custos-sobem");
  expect(await list.locator("strong").allTextContents()).toHaveLength(ids.length);
  await page.locator(".focusMapPanelTabs").getByRole("button", { name: /^Fontes/ }).click();
  await expect(page.locator(".focusMapSources")).toContainText("Extrato do Banco");
  await page.locator(".focusMapSources").getByRole("button", { name: /Extrato do Banco/ }).click();
  await expectSelection(page, SOURCE_ID);
  await expect(page.locator(".readerBody")).toContainText("A live Banco source.");
  await expect(page.getByTestId("focus-reader").locator(".readerProvenance code")).toHaveText(byId.get(SOURCE_ID)!.path);
});

test("@shared starts with the whole connected overview, then focuses and expands only recorded adjacency", async ({ page }) => {
  await page.goto("/demo/w?demo_scenario=walking_skeleton&projection=2d&tour=0");
  await expect(page.getByTestId("focus-map")).toBeVisible();
  await settled(page);
  expect(params(page).get("map_scope")).toBe("all");
  expect(params(page).get("map_focus")).toBe("root-alex-rivera");
  expect(await visibleNodeIds(page)).toEqual(graph.nodes.map(node => node.id).sort());
  expect(await edgeIds(page)).toEqual(graph.edges.map(edge => edge.id).sort());
  await page.getByTestId(`focus-node-${SOURCE_ID}`).click();
  await expectSelection(page, SOURCE_ID, "root-alex-rivera");
  await expect(page.getByTestId("focus-reader")).toHaveCount(0);
  await page.getByTestId("center-current").click();
  await settled(page);
  const original = await visibleNodeIds(page);
  const actualNeighbors = [...new Set(graph.edges.filter(edge => edge.source === SOURCE_ID || edge.target === SOURCE_ID).flatMap(edge => [edge.source, edge.target]))].sort();
  expect(original).toEqual(actualNeighbors);
  await page.getByTestId("focus-node-hub-financeiro").click();
  await page.getByTestId("expand-current").click();
  await settled(page);
  const hubNeighbors = graph.edges.filter(edge => edge.source === "hub-financeiro" || edge.target === "hub-financeiro").flatMap(edge => [edge.source, edge.target]);
  expect(await visibleNodeIds(page)).toEqual([...new Set([...actualNeighbors, ...hubNeighbors])].sort());
  expect(params(page).get("map_focus")).toBe(SOURCE_ID);
  await page.getByTestId("focus-node-root-alex-rivera").click();
  await page.getByTestId("expand-current").click();
  await settled(page);
  expect(await visibleNodeIds(page)).toHaveLength(7);
  await page.getByTestId("reset-expansion").click();
  await settled(page);
  expect(await visibleNodeIds(page)).toEqual(original);
  await expect(page.locator(".focusMapSelection")).toContainText(t("map.selectionOutside"));
  await page.getByTestId("map-overview").click();
  await settled(page);
  expect(await visibleNodeIds(page)).toHaveLength(8);
  await expectSelection(page, "root-alex-rivera");
  await page.getByTestId("map-clear-selection").click();
  await expect(page.getByTestId("focus-map")).toHaveAttribute("data-inspector", "closed");
  expect(params(page).get("map_scope")).toBe("all");
});

test("@shared offers distinct pointer curves and exact provenance for parallel and reciprocal records", async ({ page }) => {
  await openSource(page);
  const parallel = graph.edges.filter(edge => [SOURCE_ID, EVENT_ID].includes(edge.source) && [SOURCE_ID, EVENT_ID].includes(edge.target));
  expect(parallel.map(edge => edge.type).sort()).toEqual(["moc_parent", "source_emission", "source_ref"]);
  const paths = await page.locator(".focusMapEdgeHit").evaluateAll((edges, ids) => edges.filter(edge => ids.includes(edge.getAttribute("data-edge-id")!)).map(edge => edge.getAttribute("d")), parallel.map(edge => edge.id!));
  expect(new Set(paths).size).toBe(3);
  for (const edge of parallel) {
    await clickCurve(page, edge.id!);
    const details = page.getByTestId("focus-edge-details");
    await expect(details.locator("h2")).toHaveText(t(`map.rel.${edge.type}`));
    await expect(details.locator(".focusMapEdgeEndpoints button").nth(0)).toHaveText(byId.get(edge.source)!.title);
    await expect(details.locator(".focusMapEdgeEndpoints button").nth(1)).toHaveText(byId.get(edge.target)!.title);
    await expect(details.locator(".focusMapEdgeEndpoints > span")).toHaveText("→");
    await details.locator(".focusMapOriginalRecord summary").click();
    expect(JSON.parse(await page.getByTestId("map-original-record").innerText())).toEqual(edge);
    expect(params(page).get("page")).toBe(SOURCE_ID);
    expect(params(page).get("map_edge")).toBe(`id:${encodeURIComponent(edge.id!)}`);
    await expect(page.locator(`.focusMapEdgeHit[data-edge-id="${edge.id}"]`).locator("..").locator(".focusMapEdgeLine")).toHaveAttribute("marker-end", /^url\(#map-arrow-/);
    await details.getByRole("button", { name: t("map.close"), exact: true }).click();
    await settled(page);
  }
  const emission = parallel.find(edge => edge.type === "source_emission")!;
  await page.locator(".focusMapPanelTabs").getByRole("button", { name: t("map.summary"), exact: true }).click();
  await page.locator(`.focusMapRelations button[data-edge-id="${emission.id}"]`).click();
  const origin = page.getByTestId("focus-edge-details").getByRole("link", { name: t("map.openOrigin") });
  const href = new URL(await origin.getAttribute("href") || "", page.url());
  expect(href.searchParams.get("page")).toBe(EVENT_ID);
  expect(href.searchParams.get("map_focus")).toBe(SOURCE_ID);
  await origin.click();
  await expectSelection(page, EVENT_ID);
  await expect(page.locator(".readerBody")).toBeVisible();
});

test("@shared changes declared color/state meanings and relation emphasis without changing geometry or coverage", async ({ page }) => {
  await openSource(page);
  const ids = new Set(await visibleNodeIds(page));
  const shownNodes = graph.nodes.filter(node => ids.has(node.id));
  const layout = await layoutRecords(page);
  for (const mode of ["topic", "category"] as const) {
    await page.getByLabel(t("map.color")).selectOption(mode);
    const counts = new Map<string, { label: string; color: string; count: number }>();
    for (const node of shownNodes) {
      const token = focusColorToken(node, mode);
      counts.set(token.key, { ...token, count: (counts.get(token.key)?.count || 0) + 1 });
      expect(await page.getByTestId(`focus-node-${node.id}`).evaluate(element => (element as HTMLElement).style.getPropertyValue("--focus-map-data-color").trim())).toBe(token.color);
    }
    expect((await page.locator(".focusMapLegend > span").allTextContents()).map(normalize).sort()).toEqual([...counts.values()].map(entry => `${entry.label}${entry.count}`).sort());
    expect(await layoutRecords(page)).toEqual(layout);
  }
  await page.getByLabel(t("map.color")).selectOption("state");
  for (const overlay of OVERLAYS) {
    await page.getByLabel(t("map.metric")).selectOption(overlay);
    for (const node of shownNodes) {
      const resolved = visualEncodingResolver.resolve(node, overlay), button = page.getByTestId(`focus-node-${node.id}`);
      expect(await button.evaluate(element => (element as HTMLElement).style.getPropertyValue("--focus-map-data-color").trim())).toBe(resolved.color);
      await expect(button).toHaveAttribute("data-ring", resolved.ring);
      await expect(button).toHaveAttribute("data-encoding-label", `${resolved.symbol} ${localizedEncodingText(resolved)}`.trim());
    }
    const expected = visualEncodingResolver.legend(overlay, shownNodes).filter(entry => entry.visibleCount > 0).map(entry => normalize(`${entry.symbol} ${localizedEncodingText(entry)}${entry.visibleCount}`)).sort();
    expect((await page.locator(".focusMapLegend > span").allTextContents()).map(normalize).sort()).toEqual(expected);
    expect(await layoutRecords(page)).toEqual(layout);
  }
  await page.locator(".focusMapRelationLegend").getByRole("button", { name: /^usa como fonte/ }).click();
  expect(params(page).get("map_relation")).toBe("source_ref");
  expect(await layoutRecords(page)).toEqual(layout);
  expect(await visibleNodeIds(page)).toHaveLength(ids.size);
});

test("@shared supports pan, zoom, fit and keyboard navigation with screen-sized node targets", async ({ page }) => {
  await openSource(page);
  const canvas = page.getByTestId("map-canvas");
  const originalScale = Number(await canvas.getAttribute("data-camera-scale"));
  await page.getByRole("button", { name: t("map.zoomIn"), exact: true }).click();
  expect(Number(await canvas.getAttribute("data-camera-scale"))).toBeGreaterThan(originalScale);
  const before = await page.getByTestId("focus-svg").locator(":scope > g").getAttribute("transform");
  const bounds = await canvas.boundingBox();
  await page.mouse.move(bounds!.x + 10, bounds!.y + 10);
  await page.mouse.down();
  await page.mouse.move(bounds!.x + 60, bounds!.y + 60, { steps: 5 });
  await page.mouse.up();
  expect(await page.getByTestId("focus-svg").locator(":scope > g").getAttribute("transform")).not.toBe(before);
  const pan = await page.getByTestId("focus-svg").locator(":scope > g").getAttribute("transform");
  await page.getByLabel(t("map.motion"), { exact: true }).uncheck();
  expect(await page.getByTestId("focus-svg").locator(":scope > g").getAttribute("transform")).toBe(pan);
  await page.getByRole("button", { name: t("map.fit"), exact: true }).click();
  await settled(page);
  const node = page.getByTestId(`focus-node-${SOURCE_ID}`);
  const box = await node.boundingBox();
  expect(box!.width).toBeGreaterThanOrEqual(43.9); expect(box!.height).toBeGreaterThanOrEqual(43.9);
  await node.focus();
  await node.press("ArrowRight");
  expect(await page.evaluate(() => document.activeElement?.getAttribute("data-testid"))).not.toBe(`focus-node-${SOURCE_ID}`);
  await page.keyboard.press("Enter");
  expect(params(page).get("page")).not.toBe(SOURCE_ID);
});

test("@shared lets keyboard search and the embedded reader own focus, then restores map controls", async ({ page }) => {
  await openSource(page);
  await page.getByTestId("map-list-mode").focus();
  await page.keyboard.press("/");
  await expect(page.getByTestId("focus-search")).toBeFocused();
  await page.getByTestId("focus-search").fill("Extrato do Banco");
  await page.getByTestId("focus-search").press("ArrowDown");
  await page.keyboard.press("Enter");
  const reader = page.getByTestId("focus-reader").locator(".pageReader");
  await reader.locator(".readerTypeChip").focus();
  // Allow the pending mobile navigation frame to run; it must not steal
  // explicit focus from an already-chosen reader control.
  await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>resolve())));
  await expect(reader.locator(".readerTypeChip")).toBeFocused();
  await page.keyboard.press("f");
  await expect(reader).toHaveClass(/expanded/);
  await expect(reader).toHaveAttribute("aria-modal", "true");
  await page.keyboard.press("/");
  await expect(page.getByTestId("focus-search")).not.toBeFocused();
  await page.keyboard.press("f");
  await expect(reader).not.toHaveClass(/expanded/);
  await expect(reader.locator(".readerTypeChip")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("focus-reader")).toHaveCount(0);
  expect(params(page).get("page")).toBe(SOURCE_ID);
  await expect(page.getByTestId("focus-search")).toBeFocused();
});

for (const invalid of ["revision", "integrity"] as const) {
  test(`@shared rejects ${invalid} failures in the canonical source body`, async ({ page }) => {
    const forged = structuredClone(sourceContent);
    forged.body = "# THIS_BODY_MUST_NEVER_RENDER";
    if (invalid === "revision") forged.snapshot_id = "synthetic-other-snapshot";
    await page.route(`**${SOURCE_URL}`, route => route.fulfill({ json: forged }));
    await page.goto(DEEP_LINK);
    await expectSelection(page, SOURCE_ID);
    await expect(page.locator(".readerFallback")).toContainText(byId.get(SOURCE_ID)!.summary);
    await expect(page.locator(".readerFallback .readerNotice")).toBeVisible();
    await expect(page.locator(".readerBody")).toHaveCount(0);
    await expect(page.getByTestId("focus-reader")).not.toContainText("THIS_BODY_MUST_NEVER_RENDER");
    await expect(page.locator("canvas")).toHaveCount(0);
  });
}

test("@shared strips crafted operator surfaces and returns selection to the original cockpit", async ({ page }) => {
  test.setTimeout(45_000);
  for (const dock of ["source", "admin", "intake"]) {
    await page.goto(`${DEEP_LINK}&dock=${dock}&tray=packet&pack_view=synthetic.read-only-probe`);
    await expect(page.getByTestId("focus-map")).toBeVisible();
    await expect.poll(() => params(page).get("dock")).toBeNull();
    expect(params(page).get("tray")).toBeNull(); expect(params(page).get("pack_view")).toBeNull();
    await expect(page.locator(".sourceDock, .adminDock, .intakeDock, .packetTray, .workDockPanel, .sourceWorkspace")).toHaveCount(0);
    // The router's existing dock > reader precedence remains authoritative.
    // Once the crafted dock is stripped, reading is an explicit next step.
    await page.getByTestId("map-open-reader").click();
    await expect(page.locator(".readerBody")).toContainText("A live Banco source.");
    await settled(page);
  }
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByRole("button", { name: t("map.original"), exact: true }).click();
  await expect(page.getByTestId("focus-map")).toHaveCount(0);
  await expect(page.locator(".worldWorkspace")).toBeVisible({ timeout: 20_000 });
  await expect(page.locator("#page-reader-title")).toHaveText(byId.get(SOURCE_ID)!.title);
  expect(params(page).get("projection")).toBeNull();
  expect(params(page).get("page")).toBe(SOURCE_ID);
  expect(params(page).get("reader")).toBe("1");
  await page.getByTestId("open-connected-map").click();
  await expectSelection(page, SOURCE_ID, manifest.root_page_id!);
  expect(params(page).get("map_scope")).toBe("all");
});

test("@desktop @mobile captures all real perspectives and the selected source with no horizontal overflow", async ({ page }, testInfo) => {
  await page.goto("/demo/w?projection=2d&tour=0");
  await expect(page.getByTestId("focus-map")).toBeVisible();
  for (const perspective of ["network", "areas", "evidence", "work"]) {
    await page.getByTestId(`map-perspective-${perspective}`).click();
    await settled(page);
    await expect(page.getByTestId("focus-counts")).toHaveText("107 de 107 páginas · 148 de 148 conexões");
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    await capture(page, testInfo, perspective);
  }
  await page.getByTestId("focus-search").fill("Custos de nuvem");
  await page.locator(".focusMapSearchResults button").first().click();
  await page.getByTestId("center-current").click();
  await settled(page);
  const box = await page.getByTestId("map-canvas").boundingBox();
  expect(box!.height).toBeGreaterThanOrEqual(219);
  await capture(page, testInfo, "focused-claim");
  await page.getByTestId("map-open-reader").click();
  await page.locator(".readerBody").scrollIntoViewIfNeeded();
  await expect(page.locator(".readerBody")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  await capture(page, testInfo, "canonical-reader");
});

test("@reduced removes direction animations and finite layout motion without altering records", async ({ page }) => {
  await openSource(page);
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-motion", "off");
  await expect(page.locator(".focusMapFlow")).toHaveCount(0);
  const ids = await edgeIds(page);
  for (const perspective of ["areas", "evidence", "work"]) {
    await page.getByTestId(`map-perspective-${perspective}`).click();
    await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-layout-motion", "settled");
    expect(await edgeIds(page)).toEqual(ids);
    await expect(page.locator(".focusMapFlow")).toHaveCount(0);
  }
});

test("@desktop runs finite RAF transitions and bounds direction signals instead of an idle force simulation", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    const request = window.requestAnimationFrame.bind(window);
    let count = 0;
    Object.defineProperty(window, "connectedMapRafCount", { get: () => count });
    window.requestAnimationFrame = callback => { count++; return request(callback); };
  });
  await openSource(page);
  await page.getByTestId("map-perspective-areas").click();
  await settled(page);
  const count = () => page.evaluate(() => (window as unknown as { connectedMapRafCount: number }).connectedMapRafCount);
  const first = await count();
  await page.waitForTimeout(220);
  const second = await count();
  expect(first).toBeGreaterThan(0); expect(second).toBe(first);
  expect(await page.locator(".focusMapFlow").count()).toBeLessThanOrEqual(8);
  await testInfo.attach("finite-map-motion.json", { body: Buffer.from(JSON.stringify({ first, second, idleWindowMs: 220, directedSignals: await page.locator(".focusMapFlow").count() })), contentType: "application/json" });
});

test("@shared pins a selected connection beyond the edge budget even in a small graph", async ({ page }) => {
  const original = graph.edges.find(edge => edge.source === SOURCE_ID && edge.target === EVENT_ID)!;
  const added = Array.from({ length: 1000 }, (_, i) => ({ ...original, id: `dense-${String(i).padStart(4, "0")}` }));
  const dense = { ...graph, edges: [...graph.edges, ...added] };
  const canonical = canonicalJson(dense);
  const denseManifest = structuredClone(manifest);
  denseManifest.integrity!["graph.json"] = { sha256: createHash("sha256").update(canonical).digest("hex"), bytes: Buffer.byteLength(canonical) };
  await page.route(`**${SCENARIO}/graph.json`, route => route.fulfill({ json: dense }));
  await page.route(`**${SCENARIO}/manifest.json`, route => route.fulfill({ json: denseManifest }));
  await page.goto(`/demo/w?demo_scenario=walking_skeleton&projection=2d&map_scope=all&page=${SOURCE_ID}&tour=0`);
  await expect(page.getByTestId("focus-map")).toBeVisible();
  await settled(page);
  await expect(page.locator(".focusMapEdgeHit")).toHaveCount(900);
  expect(await edgeIds(page)).not.toContain("dense-0999");
  const connections = page.locator(".focusMapRelations");
  while (await connections.getByRole("button", { name: /\+100/ }).count()) {
    await connections.getByRole("button", { name: /\+100/ }).click();
  }
  await connections.locator('button[data-edge-id="dense-0999"]').click();
  await expect(page.getByTestId("focus-edge-details")).toBeVisible();
  await expect(page.locator('.focusMapEdgeHit[data-edge-id="dense-0999"]')).toHaveCount(1);
  await page.getByTestId("focus-edge-details").locator(".focusMapOriginalRecord summary").click();
  expect(JSON.parse(await page.getByTestId("map-original-record").innerText())).toEqual(added[999]);
});

test("@mobile fits all small-focus node hit targets above controls and keeps short-view controls reachable", async ({ page }, testInfo) => {
  for (const height of [844, 660]) {
    await page.setViewportSize({ width: 390, height });
    await page.goto("/demo/w?projection=2d&map_scope=focus&map_focus=claim-custos-sobem&page=claim-custos-sobem&tour=0");
    await expect(page.getByTestId("focus-map")).toBeVisible();
    await settled(page);
    const canvas = page.getByTestId("map-canvas");
    await canvas.scrollIntoViewIfNeeded();
    await page.getByRole("button", { name: t("map.fit"), exact: true }).click();
    await settled(page);
    const targets = await page.locator(".focusMapNode").evaluateAll(nodes => nodes.map(node => {
      const box = node.getBoundingClientRect();
      return { id: node.getAttribute("data-testid"), hit: node.contains(document.elementFromPoint(box.x+box.width/2, box.y+box.height/2)) };
    }));
    expect(targets).toHaveLength(4);
    expect(targets.filter(target => !target.hit)).toEqual([]);
    await page.locator(".focusMapRelationLegend").scrollIntoViewIfNeeded();
    await expect(page.locator(".focusMapRelationLegend").getByRole("button").first()).toBeInViewport();
    await page.getByLabel(t("map.motion"), { exact: true }).scrollIntoViewIfNeeded();
    await expect(page.getByLabel(t("map.motion"), { exact: true })).toBeInViewport();
    await capture(page, testInfo, `short-${height}`);
  }
});

test("@mobile keeps directed arrow tangents pointing toward their recorded target at overview scale", async ({ page }, testInfo) => {
  await page.goto("/demo/w?projection=2d&tour=0");
  await expect(page.getByTestId("focus-map")).toBeVisible();
  await settled(page);
  const directions = await page.getByTestId("focus-svg").evaluate((svg, edges) => {
    const byId = new Map(edges.map(edge => [edge.id, edge]));
    const centers = new Map([...svg.querySelectorAll(".focusMapNodeGroup")].map(group => {
      const box = group.querySelector("foreignObject")!;
      return [group.getAttribute("data-node-id"), { x: Number(box.getAttribute("x"))+Number(box.getAttribute("width"))/2, y: Number(box.getAttribute("y"))+Number(box.getAttribute("height"))/2 }];
    }));
    return [...svg.querySelectorAll<SVGPathElement>(".focusMapEdgeHit")].filter(path => path.parentElement!.querySelector(".focusMapEdgeLine")?.hasAttribute("marker-end")).map(path => {
      const values = path.getAttribute("d")!.match(/-?\d+(?:\.\d+)?/g)!.map(Number);
      const record = byId.get(path.getAttribute("data-edge-id")!)!;
      const source = centers.get(record.source)!;
      const end = { x: values[4], y: values[5] }, control = { x: values[2], y: values[3] };
      const target = centers.get(record.target)!;
      return { id: record.id, source: record.source, target: record.target, dot: (end.x-control.x)*(target.x-source.x)+(end.y-control.y)*(target.y-source.y) };
    });
  }, overviewGraph.edges);
  expect(directions.length).toBeGreaterThan(0);
  expect(directions.filter(item => item.source !== item.target && item.dot <= 0)).toEqual([]);
  await testInfo.attach("mobile-directed-tangents.json", { body: Buffer.from(JSON.stringify(directions)), contentType: "application/json" });
});

test("@mobile explains Sources/Work grouping with readable screen-size group names", async ({ page }) => {
  await page.goto("/demo/w?projection=2d&tour=0");
  await expect(page.getByTestId("focus-map")).toBeVisible();
  for (const perspective of ["evidence", "work"]) {
    await page.getByTestId(`map-perspective-${perspective}`).click();
    await settled(page);
    await expect(page.locator(".focusMapPerspectiveHint")).toBeVisible();
    await expect(page.locator(".focusMapPerspectiveHint")).toContainText(perspective === "work" ? "não ordena prioridade" : "não força da evidência");
    const labels = await page.locator(".focusMapCluster").evaluateAll(elements => elements.map(element => {
      const text=element as SVGTextElement, matrix=text.getScreenCTM()!;
      const bounds=text.getBoundingClientRect();
      return {label:text.textContent,px:Number(text.getAttribute("font-size"))*Math.hypot(matrix.a,matrix.b),x:bounds.x,y:bounds.y,width:bounds.width,height:bounds.height};
    }));
    expect(labels).toHaveLength(4);
    expect(labels.every(label=>label.px>=11.9)).toBe(true);
    for(let i=0;i<labels.length;i++) for(let j=i+1;j<labels.length;j++) {
      const a=labels[i],b=labels[j];
      expect(a.x<b.x+b.width&&a.x+a.width>b.x&&a.y<b.y+b.height&&a.y+a.height>b.y).toBe(false);
    }
  }
});
