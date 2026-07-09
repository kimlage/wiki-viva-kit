import { defineConfig, devices } from "@playwright/test";

const matrixOnlySpecs = /(?:mobile-parity|fallback-parity|firefox-smoke)\.spec\.ts/;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  snapshotPathTemplate: "{testDir}/__screenshots__/{arg}{ext}",
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
      maxDiffPixelRatio: 0.035
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
