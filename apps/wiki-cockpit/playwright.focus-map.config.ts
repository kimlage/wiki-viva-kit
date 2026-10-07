import { defineConfig, devices } from "@playwright/test";

// Integrated-map journeys against an already-running synthetic preview.
// Normal project CI remains unchanged; no historical release ceremony.
export default defineConfig({
  testDir: "./e2e-prototypes",
  testMatch: /focus-map\.spec\.ts/,
  outputDir: "./test-results/focus-2d",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  preserveOutput: "always",
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "../../output/playwright/focus-2d-report" }],
    ["json", { outputFile: "../../output/playwright/focus-2d-results.json" }]
  ],
  use: {
    baseURL: process.env.WIKI_MAP_QA_BASE_URL || "http://127.0.0.1:4297",
    headless: true,
    colorScheme: "light",
    locale: "pt-BR",
    serviceWorkers: "block",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "off"
  },
  projects: [
    {
      name: "focus-chromium-desktop",
      grep: /@shared|@desktop/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 }
    },
    {
      name: "focus-chromium-mobile",
      grep: /@shared|@mobile/,
      use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 }
    },
    {
      name: "focus-chromium-reduced",
      grep: /@shared|@reduced/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1, contextOptions: { reducedMotion: "reduce" } }
    },
    {
      name: "focus-firefox-desktop",
      grep: /@shared/,
      use: { ...devices["Desktop Firefox"], viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 }
    }
  ]
});
