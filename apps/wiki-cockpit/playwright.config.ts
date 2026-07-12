import { defineConfig, devices } from "@playwright/test";

const performanceSpec = /runtime-performance\.spec\.ts/;
const matrixOnlySpecs = /(?:runtime-performance|mobile-parity|fallback-parity|firefox-smoke)\.spec\.ts/;
const downstreamSpecs = /(?:^|[\\/])downstream[\\/]/;
const releaseRun = process.env.WIKI_RELEASE_RUN === "1";
const previewPort = releaseRun ? Number(process.env.WIKI_RELEASE_PORT) : 4173;
if (releaseRun && (!Number.isInteger(previewPort) || previewPort < 1024 || previewPort > 65535)) {
  throw new Error("WIKI_RELEASE_PORT must be a valid dedicated release port");
}
const previewOrigin = `http://127.0.0.1:${previewPort}`;

export default defineConfig({
  testDir: "./e2e",
  // Real-repository/operator tests are a separate fail-closed downstream
  // matrix. The public suite must not collect them as environment-optional
  // skips and accidentally report a green release.
  testIgnore: downstreamSpecs,
  // Local ad-hoc Playwright runs clear their output directory on startup.
  // Keep that disposable tree below its own child so it can never erase the
  // immutable per-run release evidence stored under test-results/release-runs.
  outputDir: process.env.WIKI_PLAYWRIGHT_OUTPUT_DIR || "./test-results/playwright-dev-artifacts",
  // Pixel output is renderer- and font-stack-dependent. Keep reviewed
  // references per OS and browser project instead of weakening the visual
  // contract until a macOS image happens to pass on Linux (or vice versa).
  snapshotPathTemplate: "{testDir}/__screenshots__/{platform}/{projectName}/{arg}{ext}",
  fullyParallel: false,
  forbidOnly: true,
  preserveOutput: "always",
  // A release result is first-attempt evidence. CI must never turn a flaky
  // first attempt green by retrying it.
  retries: 0,
  // WebGL, video and visual baselines share one preview server. One worker
  // keeps local evidence equivalent to CI and avoids cross-context GPU noise.
  workers: 1,
  reporter: [
    [process.env.CI ? "line" : "list"],
    ["html", { open: "never", outputFolder: process.env.WIKI_PLAYWRIGHT_HTML_REPORT || "../../output/playwright/wiki-cockpit-report" }],
    ["json", { outputFile: process.env.WIKI_PLAYWRIGHT_JSON_REPORT || "./test-results/playwright-dev-results.json" }]
  ],
  expect: {
    toHaveScreenshot: {
      // Platform-specific references plus the real reduced-motion branch are
      // now byte-stable across consecutive runs. Keep a small raster margin,
      // but no longer allow a materially different world to hide in 3.5% of
      // a mostly dark frame.
      maxDiffPixelRatio: 0.01
    }
  },
  use: {
    baseURL: previewOrigin,
    colorScheme: "dark",
    locale: "pt-BR",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure"
  },
  webServer: {
    command: `npm run preview -- --host 127.0.0.1 --port ${previewPort} --strictPort`,
    url: `${previewOrigin}/demo?visual=1`,
    reuseExistingServer: releaseRun ? false : !process.env.CI,
    timeout: 120000
  },
  projects: [
    {
      // Wall-clock frame evidence must not inherit GPU readback stalls from
      // visual-baseline tests in the shared Chromium process. A dedicated
      // first project keeps the same strict budget in a clean browser.
      name: "chromium-performance",
      testMatch: performanceSpec,
      use: {
        ...devices["Desktop Chrome"],
        browserName: "chromium",
        deviceScaleFactor: 1,
        screen: { width: 1280, height: 900 },
        viewport: { width: 1280, height: 900 }
      }
    },
    {
      name: "chromium-desktop",
      // Project options replace, rather than merge with, top-level options.
      // Keep the downstream exclusion here as well as the matrix-only filter.
      testIgnore: [downstreamSpecs, matrixOnlySpecs],
      use: {
        ...devices["Desktop Chrome"],
        browserName: "chromium",
        deviceScaleFactor: 1,
        screen: { width: 1280, height: 900 },
        viewport: { width: 1280, height: 900 }
      }
    },
    {
      name: "webkit-keyboard",
      testMatch: /keyboard-genesis(?:-journey)?\.spec\.ts/,
      use: {
        ...devices["Desktop Safari"],
        browserName: "webkit",
        deviceScaleFactor: 1,
        screen: { width: 1280, height: 900 },
        viewport: { width: 1280, height: 900 }
      }
    },
    {
      name: "webkit-mobile",
      testMatch: /mobile-parity\.spec\.ts/,
      use: {
        ...devices["iPhone 13"],
        browserName: "webkit",
        contextOptions: { hasTouch: true, isMobile: true },
        deviceScaleFactor: 3,
        screen: { width: 390, height: 844 },
        viewport: { width: 390, height: 844 }
      }
    },
    {
      name: "chromium-fallback",
      testMatch: /fallback-parity\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        browserName: "chromium",
        contextOptions: { reducedMotion: "reduce" },
        deviceScaleFactor: 1,
        screen: { width: 1280, height: 900 },
        viewport: { width: 1280, height: 900 }
      }
    },
    {
      name: "firefox-smoke",
      testMatch: /(?:firefox-smoke|keyboard-genesis)\.spec\.ts/,
      use: {
        ...devices["Desktop Firefox"],
        browserName: "firefox",
        deviceScaleFactor: 1,
        screen: { width: 1280, height: 900 },
        viewport: { width: 1280, height: 900 }
      }
    }
  ]
});
