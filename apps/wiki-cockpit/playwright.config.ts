import { defineConfig, devices } from "@playwright/test";

const performanceSpec = /runtime-performance\.spec\.ts/;
const matrixOnlySpecs = /(?:runtime-performance|mobile-parity|fallback-parity|firefox-smoke)\.spec\.ts/;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  // Pixel output is renderer- and font-stack-dependent. Keep reviewed
  // references per OS and browser project instead of weakening the visual
  // contract until a macOS image happens to pass on Linux (or vice versa).
  snapshotPathTemplate: "{testDir}/__screenshots__/{platform}/{projectName}/{arg}{ext}",
  fullyParallel: false,
  preserveOutput: "always",
  retries: process.env.CI ? 1 : 0,
  // WebGL, video and visual baselines share one preview server. One worker
  // keeps local evidence equivalent to CI and avoids cross-context GPU noise.
  workers: 1,
  reporter: [
    [process.env.CI ? "line" : "list"],
    ["html", { open: "never", outputFolder: "../../output/playwright/wiki-cockpit-report" }],
    ["json", { outputFile: "./test-results/results.json" }]
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
    baseURL: "http://127.0.0.1:4173",
    colorScheme: "dark",
    locale: "pt-BR",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure"
  },
  webServer: {
    command: "npm run preview -- --host 127.0.0.1 --port 4173",
    url: "http://127.0.0.1:4173/demo?visual=1",
    reuseExistingServer: !process.env.CI,
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
      testIgnore: matrixOnlySpecs,
      use: {
        ...devices["Desktop Chrome"],
        browserName: "chromium",
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
      testMatch: /firefox-smoke\.spec\.ts/,
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
