import type { Locator, Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { attachViewportScreenshot, expect, test } from "./fixtures";
import type { PageRecord, SourceEntity } from "../src/types";
import type { RuntimeObservations } from "../src/data/runtimeObservations";

test.describe.configure({ timeout: 60_000 });

// Public synthetic read models only. No operator, account, model or native
// runtime is started. Every /operator request is fulfilled in this browser.
// Reuse the shipped dense fixture so selection starts far below the detail.
const FIXTURE = new URL("../dist/sample-snapshot/scenarios/dense_stress/", import.meta.url);
const canonical = (value: unknown): string => Array.isArray(value) ? `[${value.map(canonical).join(",")}]`
  : value && typeof value === "object" ? `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`
  : JSON.stringify(value);
const digest = (value: string) => createHash("sha256").update(value).digest("hex");

async function syntheticOperator(page: Page) {
  const manifest = JSON.parse(await readFile(new URL("manifest.json", FIXTURE), "utf8"));
  const artifacts: Record<string, any> = Object.fromEntries(await Promise.all(Object.keys(manifest.integrity).map(async name =>
    [name, JSON.parse(await readFile(new URL(name, FIXTURE), "utf8"))])));
  const pages = artifacts["pages.json"].pages as PageRecord[];
  const front = pages.find(row => row.id === "hub-clientes")!;
  const action = pages.find(row => row.page_type === "action" && row.work?.state === "open")!;
  const source = artifacts["source_entities.json"].sources[0] as SourceEntity;
  Object.assign(source, {
    recipe_ok: true, recipe_errors: [], schedule: { mode: "event_driven", cadence_days: 0, cron_hint: "" },
    freshness_applicable: false, pending_streams: 0,
    verification: { recorded_at: "2026-10-29", evidence_refs: [action.id], live_access: "unknown" },
    streams: [{ id: "synthetic-record", label: "Synthetic historical record", selected: true, privacy: "private_self", target_pages: [action.id], skip_reason: "", cursor_age_days: 22, cadence_days: 0, breached: false }]
  });
  Object.assign(source.sync, { streams_total: 1, streams_fresh: 1, streams_without_pending: 1, last_run_at: "2026-10-09", event_closure: { gate_state: "pending", consolidated_into: [], no_change: [], reviewed_no_change: true } });
  Object.assign(source.lifecycle!, { last_ingested_at: "2026-10-09", adoption_state: "pending", pipeline_stage: "gate_pending" });
  const reviewSource = artifacts["source_entities.json"].sources[1] as SourceEntity;
  Object.assign(reviewSource, { recipe_ok: true, recipe_errors: [], schedule: source.schedule, freshness_applicable: false, pending_streams: 1,
    streams: [{ ...source.streams[0], breached: true, information_review_pending: true,
      review_requests: [{ request_id: "synthetic-review", scope: "synthetic-record", fields: ["body"], consumers: [action.path], priority: "on_demand", status: "review_pending" }] }] });
  Object.assign(reviewSource.sync, { streams_total: 1, streams_fresh: 0, streams_without_pending: 0 });
  // Same hash basis as the snapshot producer: sidecars exclude the embedded
  // snapshot ID from the bundle hash, then include it in their own integrity.
  manifest.bundle_hash = digest(Object.keys(artifacts).sort().map(name => {
    const value = name.startsWith("content/") ? Object.fromEntries(Object.entries(artifacts[name]).filter(([key]) => key !== "snapshot_id")) : artifacts[name];
    return `${name}:${digest(canonical(value))}`;
  }).join("\n"));
  manifest.snapshot_id = `${manifest.repo.repo_id}-${manifest.bundle_hash.slice(0, 16)}`;
  for (const [name, value] of Object.entries(artifacts)) {
    if (name.startsWith("content/")) value.snapshot_id = manifest.snapshot_id;
    const encoded = canonical(value);
    manifest.integrity[name] = { sha256: digest(encoded), bytes: Buffer.byteLength(encoded) };
  }
  artifacts["manifest.json"] = manifest;
  const observation: RuntimeObservations = {
    ok: true, schema_version: "wiki_runtime_observations.v1", observed_at: "2026-10-31T12:00:00Z",
    operator: { started_at: "2026-10-30T09:00:00Z", boot_source_commit: "a".repeat(40), current_source_commit: "b".repeat(40), content_source_commit: "c".repeat(40), restart_required: true, server_version: "wiki_web_server.v11", frontend: { status: "observed", entry_sha256: "d".repeat(64), source_commit: null } },
    openclaw: { configured: true, observation_scope: "retained_local_evidence", gateway_status: "not_observed", active_run: null, pending_inputs: null, usage: { status: "not_measured", tokens: null, cost: null }, attempts: [], rules: [], native_observations: [], errors: [], transport: { status: "unavailable", scope: "loopback_tcp_only", observed_at: null } }
  };
  const state = { failed: false, frontsEmpty: false, writes: [] as string[], external: [] as string[], pageErrors: [] as string[] };
  page.on("pageerror", error => state.pageErrors.push(error.message));
  await page.route(url => !["127.0.0.1", "localhost"].includes(url.hostname), async route => { state.external.push(route.request().url()); await route.abort(); });
  await page.addInitScript(() => {
    localStorage.setItem("wikiCockpitTourDone.v1", "1");
    localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.route("**/wiki-cockpit.config.json", route => route.fulfill({ json: { api_base: "/operator", snapshot_base: "/operator/snapshot", mode: "local_operator", language: "en", repo_label: "Synthetic observability browser fixture", codex: { enabled: false } } }));
  await page.route("**/operator/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() !== "GET") {
      state.writes.push(`${request.method()} ${path}`);
      await route.fulfill({ status: 403, json: { ok: false, error_code: "synthetic_read_only_boundary" } }); return;
    }
    const name = path.slice("/operator/snapshot/".length);
    if (path.startsWith("/operator/snapshot/") && artifacts[name]) { await route.fulfill({ json: artifacts[name] }); return; }
    if (path.startsWith("/operator/pages/")) {
      const id = decodeURIComponent(path.split("/")[3]);
      const content = Object.entries(artifacts).find(([name, value]) => name.startsWith("content/") && value.page?.page_id === id)?.[1];
      if (content) { await route.fulfill({ json: content }); return; }
    }
    if (path === "/operator/coordination") {
      await route.fulfill({ json: { schema_version: "wiki_coordination.v1", configured: true, snapshot_id: manifest.snapshot_id,
        profiles: [{ id: "synthetic", label: "Synthetic coordinator", scope: "Historical synthesis only. Assignment does not authorize resumption.", action_ids: [action.id] }], actions: [], front_warnings: [],
        fronts: state.frontsEmpty ? [] : [{ page_id: front.id, path: front.path, title: front.title, page_type: front.page_type, context: front.context, declared_status: "paused", recorded_at: "2026-10-29", owner_ref: "Synthetic owner", coordinators: ["synthetic"], action_ids: [action.id], active_action_ids: [action.id], evidence_refs: [action.id], source_refs: [source.source_id], next_action: "Review the recorded pause before any resumption", blocker_reason: "Paused by the operator; assignment is context only", summary: `Synthetic paused front; retained commit ${"a".repeat(64)} and artifact synthetic_record_${"b".repeat(64)}`, content_sha256: front.content_sha256, live_execution: "unknown" }] } }); return;
    }
    if (path === "/operator/runtime/observations") { await route.fulfill(state.failed ? { status: 503, json: { ok: false, error_code: "synthetic_observation_unavailable" } } : { json: observation }); return; }
    if (path === "/operator/codex/jobs") { await route.fulfill({ json: { ok: true, jobs: [] } }); return; }
    if (path === "/operator/briefs") { await route.fulfill({ json: { ok: true, briefs: [] } }); return; }
    if (path.endsWith("/receipts")) { await route.fulfill({ json: { ok: true, receipts: [] } }); return; }
    await route.fulfill({ status: 404, json: { ok: false, error_code: "synthetic_endpoint_absent" } });
  });
  return { state, source, reviewSource, action, front, observation };
}

async function noHorizontalOverflow(page: Page, surface: Locator) {
  // As in the existing fallback journey, measure the settled surface rather
  // than the intentional translated frame during its finite entry animation.
  await page.evaluate(async () => {
    const finite = document.getAnimations().filter(animation => animation.effect?.getTiming().iterations !== Infinity);
    await Promise.all(finite.map(animation => animation.finished.catch(() => undefined)));
  });
  const geometry = await surface.evaluate(element => {
    const rect = element.getBoundingClientRect();
    return { left: rect.left, right: rect.right, width: window.innerWidth, overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth };
  });
  expect(geometry.overflow, "document must not acquire a horizontal scrollport").toBeLessThanOrEqual(1);
  expect(geometry.left).toBeGreaterThanOrEqual(-1);
  expect(geometry.right).toBeLessThanOrEqual(geometry.width + 1);
}

test("world links lead to Kanban and recorded fronts; back, reload and unavailable observation retain their scope", async ({ page }, testInfo) => {
  const { state, front, action, observation: retained } = await syntheticOperator(page);
  await page.goto("/w?projection=2d&tour=0");
  const links = page.getByRole("navigation", { name: "Wiki work" });
  await expect(links.getByRole("link", { name: "Kanban", exact: true })).toBeVisible();
  await links.getByRole("link", { name: "Kanban", exact: true }).click();
  await expect(page).toHaveURL(/\/board$/);
  await expect(page.locator(".boardCard").first()).toBeVisible();
  await page.getByText("Operator observation and versions", { exact: true }).click();
  const observation = page.locator(".boardObservations .runtimeObservation");
  await expect(observation).toContainText("This does not prove inactivity");
  await expect(observation).toContainText("Not measured");
  await observation.getByText("Content, process and served frontend", { exact: true }).click();
  await expect(observation).toContainText("Frontend source commit");
  await expect(observation).toContainText("Not observed");
  await attachViewportScreenshot(page, testInfo, "desktop-recorded-observation");

  retained.openclaw.attempts.push({ profile: "synthetic", action_id: action.id, effect_key: "synthetic-run", run_id: "synthetic-run",
    attempted_at: "2026-10-31T10:00:00Z", result_captured_at: "2026-10-31T10:01:00Z", status: "result_retained",
    result: { excerpt: "Synthetic result already preserved; no native inspection.", text_sha256: "e".repeat(64), truncated: false },
    authorization: { status: "not_observed" }, guard_admission: { status: "retained_chain_verified", model: "synthetic-model", effort: "high", error_code: null },
    review: { status: "not_observed", head: null } });
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await observation.getByText("Read retained result", { exact: true }).click();
  await expect(observation).toContainText("Synthetic result already preserved; no native inspection.");
  await expect(observation).toContainText("Historical guard chain verified");
  await expect(observation.locator("dl > div").filter({ has: page.getByText("Current authorization", { exact: true }) })).toContainText("Not observed");
  await expect(observation.locator("dl > div").filter({ has: page.getByText("Independent review", { exact: true }) })).toContainText("Not observed");
  await attachViewportScreenshot(page, testInfo, "desktop-retained-result-without-inspection");

  await page.getByRole("link", { name: "Work fronts", exact: true }).click();
  await expect(page).toHaveURL(/\/board\?view=fronts$/);
  const fronts = page.getByRole("region", { name: "Work fronts" });
  await expect(fronts).toContainText("Paused by the operator");
  await expect(fronts).toContainText("Live execution and effective access: unknown");
  await fronts.getByText("Synthetic coordinator", { exact: true }).click();
  await expect(fronts).toContainText("Historical synthesis only");
  await fronts.getByRole("button", { name: "Read front page" }).click();
  const detail = page.locator(".boardDetail");
  await expect(detail).toHaveAttribute("data-read-state", "ready");
  await expect(detail).toBeFocused();
  await expect(page).toHaveURL(new RegExp(`action=${front.id}`));
  await page.reload();
  await expect(detail).toHaveAttribute("data-page-id", front.id);
  await expect(detail).toHaveAttribute("data-read-state", "ready");
  await page.goBack();
  await expect(page).toHaveURL(/\/board\?view=fronts$/);
  await expect(detail).toHaveCount(0);

  state.failed = true; state.frontsEmpty = true;
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(fronts).toContainText("No front is declared in this projection");
  await page.getByText("Operator observation and versions", { exact: true }).click();
  await expect(observation).toContainText("Observation unavailable");
  await expect(observation).not.toContainText("Executor is idle");
  await attachViewportScreenshot(page, testInfo, "desktop-empty-fronts-observation-error");
  expect(state.writes).toEqual([]); expect(state.external).toEqual([]); expect(state.pageErrors).toEqual([]);
});

test("390px selection returns from a low card to visible focused detail and keeps source review separate from no pending trigger", async ({ page }, testInfo) => {
  const { state, source, reviewSource } = await syntheticOperator(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/board");
  const cards = page.locator(".board-open .boardCard");
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBeGreaterThan(8);
  const card = cards.last(), title = await card.locator("h3").innerText();
  await card.scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(1000);
  await attachViewportScreenshot(page, testInfo, "narrow-before-low-card-selection");
  await card.click();
  const detail = page.locator(".boardDetail");
  await expect(detail).toHaveAttribute("data-read-state", "ready");
  await expect(detail).toBeFocused();
  await expect(detail.getByRole("heading", { name: title, exact: true }).first()).toBeInViewport();
  await noHorizontalOverflow(page, detail);
  await attachViewportScreenshot(page, testInfo, "narrow-after-low-card-selection");
  await page.reload();
  await expect(detail).toHaveAttribute("data-read-state", "ready");
  await expect(detail).toBeFocused();
  await expect(detail.getByRole("heading", { name: title, exact: true }).first()).toBeInViewport();
  await noHorizontalOverflow(page, detail);
  await attachViewportScreenshot(page, testInfo, "narrow-after-selected-reload");
  // Reload has no remembered DOM opener; choose the existing card again to
  // establish a fresh, real return target before checking the close path.
  await card.click();
  await expect(detail.getByRole("heading", { name: title, exact: true }).first()).toBeInViewport();
  await detail.getByRole("button", { name: "Close", exact: true }).click();
  await expect(card).toBeFocused();
  await expect(card).toBeInViewport();
  await noHorizontalOverflow(page, page.locator(".actionBoard"));

  await page.getByRole("link", { name: "Work fronts", exact: true }).click();
  const fronts = page.getByRole("region", { name: "Work fronts" });
  await expect(fronts).toContainText("a".repeat(64));
  await noHorizontalOverflow(page, fronts);
  await attachViewportScreenshot(page, testInfo, "narrow-fronts-long-retained-identifiers");

  await page.goto(`/w?dock=source&src=${source.source_id}&visual=1&tour=0`);
  const sourceDock = page.locator(".sourceDock");
  const evidence = sourceDock.getByRole("region", { name: "Source evidence" });
  await expect(evidence).toContainText("No recorded trigger pending");
  await expect(evidence).toContainText("2026-10-09");
  await expect(evidence).toContainText("2026-10-29");
  await expect(evidence).toContainText("Current access / effective identity");
  await noHorizontalOverflow(page, sourceDock);
  await sourceDock.getByRole("button", { name: "History", exact: true }).click();
  await expect(sourceDock).toContainText("review found no change");
  await expect(evidence).toContainText("pending");
  await evidence.scrollIntoViewIfNeeded();
  await attachViewportScreenshot(page, testInfo, "narrow-source-review-and-recorded-no-change");
  await page.goto(`/w?dock=source&src=${reviewSource.source_id}&visual=1&tour=0`);
  const review = sourceDock.getByText("Information awaiting review", { exact: true }).first();
  await expect(review).toBeVisible();
  await expect(evidence.locator("dl > div").first()).toHaveText("Recorded pending work1");
  await noHorizontalOverflow(page, sourceDock);
  await review.scrollIntoViewIfNeeded();
  await attachViewportScreenshot(page, testInfo, "narrow-source-information-review-pending");
  expect(state.writes).toEqual([]); expect(state.external).toEqual([]); expect(state.pageErrors).toEqual([]);
});
