import { expect, test as base, type Page, type TestInfo } from "@playwright/test";

type ConsoleEvidence = {
  kind: "console" | "pageerror";
  level: string;
  text: string;
};

type NetworkEvidence = {
  error?: string;
  method: string;
  status?: number;
  url: string;
};

export type RuntimePerformanceEvidence = {
  schema_version: "wiki_runtime_performance.v1";
  activeDevice: "desktop" | "mobile";
  samplePolicy: { capacity: number; warmupFrames: number; minimumSamples: number; publishEvery: number };
  sampleCount: number;
  counters: {
    sourceNodes: number;
    interactiveNodes: number;
    relationLines: number;
    labels: number;
    particles: number;
    fallbackReason: string | null;
    frameTimeMedianMs: number | null;
    frameTimeP95Ms: number | null;
    routeUsabilityMs: number | null;
    interactionFeedbackMs: number | null;
  };
  evaluations: Partial<Record<"desktop" | "mobile", Record<"normal" | "stress", {
    status: "within_budget" | "compact" | "fallback" | "blocked";
    violations: string[];
    degradationReasons: string[];
  }>>>;
};

function performanceEvidenceInPage(): RuntimePerformanceEvidence | null {
  const output = document.querySelector<HTMLOutputElement>('[data-testid="runtime-performance"]');
  const raw = output?.value || output?.textContent || "";
  if (!raw) return null;
  try {
    return JSON.parse(raw) as RuntimePerformanceEvidence;
  } catch {
    return null;
  }
}

const MAX_EVIDENCE_ROWS = 200;
const MAX_EVIDENCE_TEXT = 600;
const SECRET_KEY = /(authorization|cookie|credential|password|secret|session|signature|token|api[-_]?key)/i;

function redactText(value: string): string {
  return value
    .replace(/\bBearer\s+[^\s,;]+/gi, "Bearer [REDACTED]")
    .replace(/([?&](?:authorization|credential|password|secret|session|signature|token|api[-_]?key)=)[^&#\s]*/gi, "$1[REDACTED]")
    .replace(/((?:authorization|credential|password|secret|session|signature|token|api[-_]?key)\s*[:=]\s*)[^\s,;]+/gi, "$1[REDACTED]")
    .slice(0, MAX_EVIDENCE_TEXT);
}

function redactUrl(value: string): string {
  try {
    const url = new URL(value);
    for (const key of [...url.searchParams.keys()]) {
      if (SECRET_KEY.test(key)) url.searchParams.set(key, "[REDACTED]");
    }
    url.username = "";
    url.password = "";
    return redactText(url.toString());
  } catch {
    return redactText(value);
  }
}

async function readPageEvidence(page: Page) {
  if (page.isClosed()) return { closed: true };
  return page.evaluate(() => {
    const workspace = document.querySelector<HTMLElement>(".worldWorkspace");
    const scene = document.querySelector<HTMLElement>(".sceneShell");
    const active = document.activeElement as HTMLElement | null;
    const performanceOutput = document.querySelector<HTMLOutputElement>('[data-testid="runtime-performance"]');
    let runtimePerformance: RuntimePerformanceEvidence | null = null;
    try {
      const raw = performanceOutput?.value || performanceOutput?.textContent || "";
      runtimePerformance = raw ? JSON.parse(raw) as RuntimePerformanceEvidence : null;
    } catch {
      runtimePerformance = null;
    }
    return {
      closed: false,
      route: `${window.location.pathname}${window.location.search}${window.location.hash}`,
      viewport: {
        width: window.innerWidth,
        height: window.innerHeight,
        dpr: window.devicePixelRatio,
        touchPoints: navigator.maxTouchPoints
      },
      document: {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        clientHeight: document.documentElement.clientHeight,
        scrollHeight: document.documentElement.scrollHeight
      },
      runtime: workspace
        ? {
            mode: workspace.dataset.runtimeMode ?? "",
            center: workspace.dataset.worldCenter ?? "",
            view: workspace.dataset.worldView ?? "",
            lens: workspace.dataset.worldLens ?? "",
            overlay: workspace.dataset.worldOverlay ?? "",
            warnings: workspace.dataset.runtimeWarnings ?? ""
          }
        : null,
      scene: scene
        ? {
            fallback: scene.classList.contains("fallbackMode"),
            center: scene.dataset.sceneCenter ?? "",
            group: scene.dataset.sceneGroup ?? "",
            lens: scene.dataset.sceneLens ?? "",
            perspective: scene.dataset.scenePerspective ?? ""
          }
        : null,
      performance: runtimePerformance,
      visibleSurface:
        document.querySelector<HTMLElement>(
          ".pageReader, .sourceDock, .gateDock, .gatesDock, .blocksDock, .intakeDock, .workDockPanel"
        )?.className ?? null,
      activeElement: active
        ? {
            tag: active.tagName.toLowerCase(),
            label: active.getAttribute("aria-label") ?? active.getAttribute("title") ?? active.textContent?.trim().slice(0, 120) ?? ""
          }
        : null
    };
  }).catch((error: unknown) => ({ closed: false, collectionError: redactText(String(error)) }));
}

async function attachJson(testInfo: TestInfo, name: string, value: unknown) {
  await testInfo.attach(name, {
    body: Buffer.from(`${JSON.stringify(value, null, 2)}\n`, "utf8"),
    contentType: "application/json"
  });
}

export const test = base.extend<{ evidenceCapture: void }>({
  evidenceCapture: [
    async ({ browserName, page }, use, testInfo) => {
      const consoleRows: ConsoleEvidence[] = [];
      const networkRows: NetworkEvidence[] = [];
      const pushConsole = (row: ConsoleEvidence) => {
        if (consoleRows.length < MAX_EVIDENCE_ROWS) consoleRows.push(row);
      };
      const pushNetwork = (row: NetworkEvidence) => {
        if (networkRows.length < MAX_EVIDENCE_ROWS) networkRows.push(row);
      };

      page.on("console", (message) => {
        if (!["warning", "error"].includes(message.type())) return;
        pushConsole({ kind: "console", level: message.type(), text: redactText(message.text()) });
      });
      page.on("pageerror", (error) => {
        pushConsole({ kind: "pageerror", level: "error", text: redactText(error.stack ?? error.message) });
      });
      page.on("requestfailed", (request) => {
        pushNetwork({
          error: redactText(request.failure()?.errorText ?? "request failed"),
          method: request.method(),
          url: redactUrl(request.url())
        });
      });
      page.on("response", (response) => {
        if (response.status() < 400) return;
        pushNetwork({
          method: response.request().method(),
          status: response.status(),
          url: redactUrl(response.url())
        });
      });

      await use();

      const pageEvidence = await readPageEvidence(page);
      const consoleNetworkSummary = {
        schema: "wiki-viva.browser-console-network.v1",
        project: testInfo.project.name,
        browser: browserName,
        console: consoleRows,
        network: networkRows,
        counts: {
          console: consoleRows.length,
          network: networkRows.length
        }
      };
      await attachJson(testInfo, "console-network-summary.json", consoleNetworkSummary);
      await attachJson(testInfo, "qa-evidence.json", {
        schema: "wiki-viva.browser-evidence.v1",
        capturedAt: new Date().toISOString(),
        project: testInfo.project.name,
        browser: browserName,
        test: testInfo.title,
        file: testInfo.file,
        retry: testInfo.retry,
        status: testInfo.status,
        expectedStatus: testInfo.expectedStatus,
        page: pageEvidence,
        consoleNetwork: consoleNetworkSummary.counts
      });
    },
    { auto: true }
  ]
});

export { expect };

export async function attachViewportScreenshot(page: Page, testInfo: TestInfo, name: string) {
  await testInfo.attach(`${name}.png`, {
    body: await page.screenshot({ animations: "disabled", fullPage: false }),
    contentType: "image/png"
  });
}

export async function waitForRuntimePerformance(
  page: Page,
  options: { minimumSamples?: number; timeout?: number } = {}
): Promise<RuntimePerformanceEvidence> {
  const minimumSamples = options.minimumSamples ?? 30;
  const timeout = options.timeout ?? 20_000;
  await page.waitForFunction(
    ({ samples }) => {
      const output = document.querySelector<HTMLOutputElement>('[data-testid="runtime-performance"]');
      if (!output || output.dataset.performanceReady !== "true") return false;
      const raw = output.value || output.textContent || "";
      try {
        const evidence = JSON.parse(raw) as RuntimePerformanceEvidence;
        return evidence.sampleCount >= samples;
      } catch {
        return false;
      }
    },
    { samples: minimumSamples },
    { timeout }
  );
  const evidence = await page.evaluate(performanceEvidenceInPage);
  if (!evidence) throw new Error("runtime performance output was ready but not parseable");
  return evidence;
}

export async function resetRuntimePerformanceWindow(page: Page): Promise<void> {
  const reset = await page.evaluate((eventName) => {
    window.dispatchEvent(new Event(eventName));
    const output = document.querySelector<HTMLOutputElement>('[data-testid="runtime-performance"]');
    return output?.dataset.performanceReady === "false" && output.dataset.performanceSamples === "0";
  }, "wiki-viva:runtime-performance-reset");
  if (!reset) throw new Error("runtime performance measurement window did not reset synchronously");
}
