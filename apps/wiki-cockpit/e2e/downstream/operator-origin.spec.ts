import { createHash } from "node:crypto";
import { expect, test } from "../fixtures";
import { validateOperatorHandshake } from "../../src/contracts/operatorSecurity.js";

test.describe.configure({ timeout: 90_000 });

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required by the downstream release matrix`);
  return value;
}

function manifestUrl(snapshotUrl: string): string {
  return new URL("./manifest.json", snapshotUrl).toString();
}

function payloadUrl(snapshotUrl: string, file: "temporal_graph.json" | "experience_packs.json"): string {
  return new URL(`./${file}`, snapshotUrl).toString();
}

type ExpectedPack = { id: string; version: string };

function expectedPacks(): ExpectedPack[] {
  const raw = required("WIKI_COCKPIT_EXPECT_ACTIVE_PACKS");
  const value = JSON.parse(raw) as unknown;
  if (!Array.isArray(value)) throw new Error("WIKI_COCKPIT_EXPECT_ACTIVE_PACKS must be a JSON array");
  return value as ExpectedPack[];
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
      .map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function canonicalEvidence(value: unknown) {
  const encoded = canonicalJson(value);
  return {
    sha256: createHash("sha256").update(encoded, "utf8").digest("hex"),
    bytes: Buffer.byteLength(encoded, "utf8")
  };
}

function expectations() {
  return {
    snapshotUrl: required("WIKI_COCKPIT_SNAPSHOT_URL"),
    expectedRepo: required("WIKI_COCKPIT_EXPECT_REPO_ID"),
    expectedRevision: required("WIKI_COCKPIT_EXPECT_SNAPSHOT_REVISION"),
    expectedHash: required("WIKI_COCKPIT_EXPECT_SNAPSHOT_HASH").toLowerCase(),
    expectedConsumerHead: required("WIKI_COCKPIT_EXPECT_CONSUMER_HEAD").toLowerCase(),
    expectedPublicReleaseSha: required("WIKI_COCKPIT_EXPECT_PUBLIC_RELEASE_SHA").toLowerCase(),
    expectedAdapterHash: required("WIKI_COCKPIT_EXPECT_ADAPTER_HASH").toLowerCase(),
    expectedSnapshotVersion: required("WIKI_COCKPIT_EXPECT_SNAPSHOT_VERSION"),
    expectedRuntimeVersion: required("WIKI_COCKPIT_EXPECT_RUNTIME_VERSION"),
    expectedServerVersion: required("WIKI_COCKPIT_EXPECT_SERVER_VERSION"),
    expectedTemporalGraphVersion: required("WIKI_COCKPIT_EXPECT_TEMPORAL_GRAPH_VERSION"),
    expectedTemporalEventVersion: required("WIKI_COCKPIT_EXPECT_TEMPORAL_EVENT_VERSION"),
    expectedExperiencePackCompositionVersion: required("WIKI_COCKPIT_EXPECT_EXPERIENCE_PACK_COMPOSITION_VERSION"),
    expectedCompositionSha256: required("WIKI_COCKPIT_EXPECT_COMPOSITION_SHA256").toLowerCase(),
    expectedActivePacks: expectedPacks(),
    expectedCapabilities: required("WIKI_COCKPIT_EXPECT_CAPABILITIES")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean),
    minPages: Number(required("WIKI_COCKPIT_MIN_PAGES"))
  };
}

test("exact downstream operator serves the attested repo, revision, hash and capabilities", async ({ request }) => {
  const {
    snapshotUrl,
    expectedRepo,
    expectedRevision,
    expectedHash,
    expectedConsumerHead,
    expectedPublicReleaseSha,
    expectedAdapterHash,
    expectedSnapshotVersion,
    expectedRuntimeVersion,
    expectedServerVersion,
    expectedTemporalGraphVersion,
    expectedTemporalEventVersion,
    expectedExperiencePackCompositionVersion,
    expectedCompositionSha256,
    expectedActivePacks,
    expectedCapabilities,
    minPages
  } = expectations();
  const [
    pagesResponse,
    manifestResponse,
    temporalResponse,
    experiencePacksResponse,
    healthResponse,
    runtimeConfigResponse
  ] = await Promise.all([
    request.get(snapshotUrl, { headers: { accept: "application/json" } }),
    request.get(manifestUrl(snapshotUrl), { headers: { accept: "application/json" } }),
    request.get(payloadUrl(snapshotUrl, "temporal_graph.json"), { headers: { accept: "application/json" } }),
    request.get(payloadUrl(snapshotUrl, "experience_packs.json"), { headers: { accept: "application/json" } }),
    request.get("/api/health", { headers: { accept: "application/json" } }),
    request.get("/wiki-cockpit.config.json", { headers: { accept: "application/json" } })
  ]);

  for (const response of [
    pagesResponse,
    manifestResponse,
    temporalResponse,
    experiencePacksResponse,
    healthResponse,
    runtimeConfigResponse
  ]) {
    expect(response.headers()["content-type"] || "").toContain("application/json");
    expect(response.ok()).toBe(true);
  }

  const pages = await pagesResponse.json();
  const manifest = await manifestResponse.json();
  const temporal = await temporalResponse.json();
  const experiencePacks = await experiencePacksResponse.json();
  const health = await healthResponse.json();
  const runtimeConfig = await runtimeConfigResponse.json();

  expect(pages.repo_id || pages.repo?.repo_id).toBe(expectedRepo);
  expect(Array.isArray(pages.pages) ? pages.pages.length : 0).toBeGreaterThanOrEqual(minPages);
  expect(manifest.repo?.repo_id).toBe(expectedRepo);
  expect(manifest.snapshot_id).toBe(expectedRevision);
  expect(String(manifest.bundle_hash || "").toLowerCase()).toBe(expectedHash);
  expect(String(manifest.source_commit || "").toLowerCase()).toBe(expectedConsumerHead);
  expect(String(manifest.source_sha || "").toLowerCase()).toBe(expectedConsumerHead);
  expect(manifest.versions?.snapshot).toBe(expectedSnapshotVersion);
  expect(manifest.versions?.runtime_contract).toBe(expectedRuntimeVersion);
  expect(manifest.capabilities).toEqual(expect.arrayContaining(["temporal_graph", "experience_packs"]));
  expect(manifest.versions?.temporal_graph).toBe(expectedTemporalGraphVersion);
  expect(manifest.versions?.temporal_event).toBe(expectedTemporalEventVersion);
  expect(manifest.versions?.experience_pack_composition).toBe(expectedExperiencePackCompositionVersion);
  expect(temporal.schema_version).toBe(expectedTemporalGraphVersion);
  expect(temporal.event_schema_version).toBe(expectedTemporalEventVersion);
  expect(temporal.returned_count).toBeGreaterThan(0);
  expect(temporal.returned_count).toBe(temporal.events.length);
  expect(temporal.returned_count).toBe(temporal.total_count);
  expect(temporal.event_count).toBe(temporal.total_count);
  expect(temporal.truncated).toBe(false);
  expect(temporal.next_cursor).toBeNull();
  expect(temporal.page?.remaining_count).toBe(0);
  expect(temporal.events.every((event: { schema_version?: string }) => event.schema_version === expectedTemporalEventVersion)).toBe(true);
  expect(experiencePacks.schema_version).toBe(expectedExperiencePackCompositionVersion);
  expect(experiencePacks.core_version).toBe("8.0.0");
  expect(experiencePacks.packs).toEqual(expectedActivePacks);
  expect(String(experiencePacks.composition_sha256 || "").toLowerCase()).toBe(expectedCompositionSha256);
  expect(canonicalEvidence({
    packs: experiencePacks.packs,
    block_packages: experiencePacks.block_packages,
    slots: experiencePacks.slots,
    presentation: experiencePacks.presentation
  }).sha256).toBe(expectedCompositionSha256);
  expect(canonicalEvidence(pages)).toEqual(manifest.integrity?.["pages.json"]);
  expect(canonicalEvidence(temporal)).toEqual(manifest.integrity?.["temporal_graph.json"]);
  expect(canonicalEvidence(experiencePacks)).toEqual(manifest.integrity?.["experience_packs.json"]);
  expect(manifest.contract_errors).toEqual([]);
  expect(health.repo).toBe(expectedRepo);
  expect(health.ok).toBe(true);
  expect(health.server_version).toBe(expectedServerVersion);
  const operatorHandshake = validateOperatorHandshake(health);
  expect(operatorHandshake.errors).toEqual([]);
  expect(operatorHandshake.ok).toBe(true);
  expect(String(runtimeConfig.adoption?.public_release_sha || "").toLowerCase()).toBe(expectedPublicReleaseSha);
  expect(String(runtimeConfig.adoption?.adapter_hash || "").toLowerCase()).toBe(expectedAdapterHash);
  expect(runtimeConfig.adoption?.adapter_manifest).toBe("wiki.adapter-manifest.json");
  for (const capability of expectedCapabilities) {
    expect(health.schema_capabilities).toContain(capability);
  }
});

test("exact downstream UI renders the attested repo instead of a sample fallback", async ({ page }) => {
  const {
    snapshotUrl,
    expectedRepo,
    expectedRevision,
    expectedHash,
    expectedConsumerHead,
    expectedPublicReleaseSha,
    expectedAdapterHash,
    expectedSnapshotVersion,
    expectedRuntimeVersion,
    expectedTemporalGraphVersion,
    expectedTemporalEventVersion,
    expectedExperiencePackCompositionVersion,
    expectedCompositionSha256,
    expectedActivePacks,
    minPages
  } = expectations();
  const expectedBootUrl = new URL("/api/snapshot/boot", snapshotUrl).toString();
  const expectedTemporalUrl = payloadUrl(snapshotUrl, "temporal_graph.json");
  const expectedRuntimeConfigUrl = new URL("/wiki-cockpit.config.json", snapshotUrl).toString();
  const runtimeConfigResponse = page.waitForResponse(
    (response) => response.request().method() === "GET" && response.url() === expectedRuntimeConfigUrl,
    { timeout: 20000 }
  );
  const uiBootResponse = page.waitForResponse(
    (response) => response.request().method() === "GET" && response.url() === expectedBootUrl,
    { timeout: 20000 }
  );
  await page.addInitScript(() => {
    window.localStorage.setItem("wikiCockpitTourDone.v1", "1");
    window.localStorage.setItem("wikiCockpitMissionCard.v1", "closed");
    window.localStorage.setItem("wiki-cockpit.missionCard", "closed");
  });
  await page.goto("/w/quadrants");
  const [bootResponse, configResponse] = await Promise.all([
    uiBootResponse,
    runtimeConfigResponse
  ]);
  expect(bootResponse.ok()).toBe(true);
  expect(configResponse.ok()).toBe(true);
  const uiBoot = await bootResponse.json();
  const uiManifest = uiBoot["manifest.json"];
  const uiPages = uiBoot["pages.json"];
  const uiExperiencePacks = uiBoot["experience_packs.json"];
  const uiRuntimeConfig = await configResponse.json();
  expect(uiManifest).toBeTruthy();
  expect(uiPages).toBeTruthy();
  expect(uiExperiencePacks).toBeTruthy();
  expect(uiManifest.repo?.repo_id).toBe(expectedRepo);
  expect(uiManifest.snapshot_id).toBe(expectedRevision);
  expect(String(uiManifest.bundle_hash || "").toLowerCase()).toBe(expectedHash);
  expect(String(uiManifest.source_commit || "").toLowerCase()).toBe(expectedConsumerHead);
  expect(String(uiManifest.source_sha || "").toLowerCase()).toBe(expectedConsumerHead);
  expect(uiManifest.versions?.snapshot).toBe(expectedSnapshotVersion);
  expect(uiManifest.versions?.runtime_contract).toBe(expectedRuntimeVersion);
  expect(uiManifest.capabilities).toEqual(expect.arrayContaining(["temporal_graph", "experience_packs"]));
  expect(uiManifest.versions?.temporal_graph).toBe(expectedTemporalGraphVersion);
  expect(uiManifest.versions?.temporal_event).toBe(expectedTemporalEventVersion);
  expect(uiManifest.versions?.experience_pack_composition).toBe(expectedExperiencePackCompositionVersion);
  expect(uiExperiencePacks.schema_version).toBe(expectedExperiencePackCompositionVersion);
  expect(uiExperiencePacks.packs).toEqual(expectedActivePacks);
  expect(uiExperiencePacks.composition_sha256).toBe(expectedCompositionSha256);
  expect(uiManifest.contract_errors).toEqual([]);
  expect(uiPages.repo_id || uiPages.repo?.repo_id).toBe(expectedRepo);
  expect(Array.isArray(uiPages.pages) ? uiPages.pages.length : 0).toBeGreaterThanOrEqual(minPages);
  expect(canonicalEvidence(uiPages)).toEqual(uiManifest.integrity?.["pages.json"]);
  expect(canonicalEvidence(uiExperiencePacks)).toEqual(uiManifest.integrity?.["experience_packs.json"]);
  expect(String(uiRuntimeConfig.adoption?.public_release_sha || "").toLowerCase()).toBe(expectedPublicReleaseSha);
  expect(String(uiRuntimeConfig.adoption?.adapter_hash || "").toLowerCase()).toBe(expectedAdapterHash);
  expect(uiRuntimeConfig.adoption?.adapter_manifest).toBe("wiki.adapter-manifest.json");
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.locator(".topBar")).toContainText(expectedRepo, { timeout: 20000 });
  await expect(page.locator(".topBar")).toContainText("local operator");
  await expect(page.locator(".demoBanner")).toHaveCount(0);
  await expect(page.locator(".sceneShell")).not.toHaveClass(/fallbackMode/, { timeout: 20000 });
  await expect(page.locator("canvas")).toHaveCount(1, { timeout: 20000 });
  const worldMeta = page.locator(".worldMeta");
  await expect(worldMeta).toContainText(/pages|páginas/i);
  const displayedCount = (await worldMeta.textContent())?.match(/([0-9][0-9.,]*)\s+(?:pages|páginas)/i);
  expect(displayedCount, "world metadata must expose its real page count").not.toBeNull();
  expect(Number(displayedCount?.[1].replace(/[.,]/g, ""))).toBeGreaterThanOrEqual(minPages);
  await expect(page.locator(".worldNavigatorPackBadge")).toHaveAttribute(
    "data-active-pack-count",
    String(expectedActivePacks.length)
  );

  const temporalResponsePromise = page.waitForResponse(
    (response) => response.request().method() === "GET" && response.url() === expectedTemporalUrl,
    { timeout: 20000 }
  );
  await page.locator('[data-view-option="timeline"]').click();
  const temporalResponse = await temporalResponsePromise;
  expect(temporalResponse.ok()).toBe(true);
  const renderedTemporal = await temporalResponse.json();
  expect(renderedTemporal.schema_version).toBe(expectedTemporalGraphVersion);
  expect(renderedTemporal.event_schema_version).toBe(expectedTemporalEventVersion);
  expect(renderedTemporal.returned_count).toBeGreaterThan(0);
  expect(renderedTemporal.returned_count).toBe(renderedTemporal.total_count);
  expect(renderedTemporal.truncated).toBe(false);
  expect(renderedTemporal.next_cursor).toBeNull();
  expect(renderedTemporal.page?.remaining_count).toBe(0);
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-view", "timeline");
  await expect(page.getByRole("heading", { name: /Chronoscope|Cronoscópio/ })).toBeVisible({ timeout: 20000 });
  await expect(page.locator(".timelineEvent").first()).toBeVisible({ timeout: 20000 });
  await expect(page.locator(".timelineContractWarning")).toHaveCount(0);
  await expect(page.locator(".sceneShell")).toHaveAttribute("data-scene-suspended", "true");

  // One bounded appearance combination proves that theme and density remain
  // state-preserving controls in the real downstream world. The public matrix
  // owns the exhaustive cross-product; this exact-repo journey does not imply it.
  await page.locator(".appearanceControl > summary").click();
  await page.getByRole("button", { name: /Luminous Observatory|Observatório Luminoso/i }).click();
  await page.getByRole("button", { name: /Use Command density|Usar densidade Comando/i }).click();
  await expect(page.locator("html")).toHaveAttribute("data-wiki-theme", "luminous-observatory");
  await expect(page.locator("html")).toHaveAttribute("data-wiki-density", "command");
  await expect(page.locator(".worldWorkspace")).toHaveAttribute("data-world-view", "timeline");

  // Likewise, this is a single explicit mobile+forced-fallback integration
  // point, not a claim that the downstream matrix repeats every public cell.
  await page.setViewportSize({ width: 390, height: 844 });
  const mobileTimelineUrl = new URL(page.url());
  mobileTimelineUrl.searchParams.set("visual", "1");
  await page.goto(`${mobileTimelineUrl.pathname}${mobileTimelineUrl.search}`);
  const timeline = page.locator(".timelineSurface");
  await expect(timeline).toBeVisible({ timeout: 20000 });
  await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/, { timeout: 20000 });
  await expect(page.locator(".timelineEvent").first()).toBeVisible({ timeout: 20000 });
  await expect(page.locator("html")).toHaveAttribute("data-wiki-theme", "luminous-observatory");
  await expect(page.locator("html")).toHaveAttribute("data-wiki-density", "command");
  const timelineGeometry = await timeline.evaluate((surface) => {
    const controls = [...surface.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled)")]
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      });
    const rect = surface.getBoundingClientRect();
    return {
      left: rect.left,
      right: rect.right,
      viewportWidth: window.innerWidth,
      controlCount: controls.length,
      minimumControlHeight: Math.min(...controls.map((element) => element.getBoundingClientRect().height)),
      horizontalOverflow: Math.max(
        document.documentElement.scrollWidth - document.documentElement.clientWidth,
        document.body.scrollWidth - document.documentElement.clientWidth
      )
    };
  });
  expect.soft(timelineGeometry.left).toBeGreaterThanOrEqual(0);
  expect.soft(timelineGeometry.right).toBeLessThanOrEqual(timelineGeometry.viewportWidth + 1);
  expect.soft(timelineGeometry.controlCount).toBeGreaterThan(0);
  expect.soft(timelineGeometry.minimumControlHeight).toBeGreaterThanOrEqual(44);
  expect.soft(timelineGeometry.horizontalOverflow).toBeLessThanOrEqual(1);

  const mutationRequests: string[] = [];
  page.on("request", (request) => {
    if (["POST", "PUT", "PATCH", "DELETE"].includes(request.method()) && new URL(request.url()).pathname.startsWith("/api/")) {
      mutationRequests.push(`${request.method()} ${new URL(request.url()).pathname}`);
    }
  });
  const packUrl = new URL(page.url());
  packUrl.searchParams.set("view", "quadrants");
  packUrl.searchParams.delete("time_cursor");
  packUrl.searchParams.delete("time_mode");
  packUrl.searchParams.delete("time_lanes");
  if (expectedActivePacks.length) {
    for (const activePack of expectedActivePacks) {
      const firstView = uiExperiencePacks.slots?.views?.find(
        (row: { pack?: string; contribution?: string }) => row.pack === activePack.id && row.contribution
      );
      if (!firstView?.contribution) {
        throw new Error(`active pack ${activePack.id} must contribute at least one workbench view`);
      }
      packUrl.searchParams.set("pack_view", firstView.contribution);
      await page.goto(`${packUrl.pathname}${packUrl.search}`);
      const workbench = page.locator(`.packWorkbenchSurface[data-pack-id="${activePack.id}"]`);
      await expect(workbench).toBeVisible({ timeout: 20000 });
      await expect(workbench).toHaveAttribute("data-pack-view", firstView.contribution);
      await expect(workbench.locator(".packWorkbenchAdapterNotice")).toBeVisible();
      const nonExecutable = workbench.locator(".packWorkbenchInventoryGroup button");
      const declaredNonExecutable = [
        ...(uiExperiencePacks.slots?.commands ?? []),
        ...(uiExperiencePacks.slots?.operations ?? [])
      ].filter((row: { pack?: string }) => row.pack === activePack.id).length;
      await expect(nonExecutable).toHaveCount(declaredNonExecutable);
      if (declaredNonExecutable) {
        expect(await nonExecutable.evaluateAll((buttons) => buttons.every((button) => (button as HTMLButtonElement).disabled))).toBe(true);
      }
      await expect(page.locator(".sceneShell")).toHaveClass(/fallbackMode/);
      const workbenchGeometry = await workbench.evaluate((surface) => {
        const rect = surface.getBoundingClientRect();
        const enabledControls = [...surface.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled)")]
          .filter((element) => {
            const box = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return box.width > 0 && box.height > 0 && style.display !== "none" && style.visibility !== "hidden";
          });
        return {
          left: rect.left,
          right: rect.right,
          viewportWidth: window.innerWidth,
          controlCount: enabledControls.length,
          minimumControlHeight: Math.min(...enabledControls.map((element) => element.getBoundingClientRect().height)),
          horizontalOverflow: Math.max(
            document.documentElement.scrollWidth - document.documentElement.clientWidth,
            document.body.scrollWidth - document.documentElement.clientWidth
          )
        };
      });
      expect.soft(workbenchGeometry.left).toBeGreaterThanOrEqual(0);
      expect.soft(workbenchGeometry.right).toBeLessThanOrEqual(workbenchGeometry.viewportWidth + 1);
      expect.soft(workbenchGeometry.controlCount).toBeGreaterThan(0);
      expect.soft(workbenchGeometry.minimumControlHeight).toBeGreaterThanOrEqual(44);
      expect.soft(workbenchGeometry.horizontalOverflow).toBeLessThanOrEqual(1);
    }
  } else {
    packUrl.searchParams.delete("pack_view");
    await page.goto(`${packUrl.pathname}${packUrl.search}`);
    await expect(page.locator('.worldNavigatorPackBadge[data-active-pack-count="0"]')).toBeVisible({ timeout: 20000 });
    await expect(page.locator(".packWorkbenchSurface")).toHaveCount(0);
  }
  expect(mutationRequests, "the downstream read journey must not execute pack or operator mutations").toEqual([]);
});
