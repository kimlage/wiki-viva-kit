import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e/downstream",
  outputDir: process.env.WIKI_PLAYWRIGHT_OUTPUT_DIR || "./test-results/downstream",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: [
    [process.env.CI ? "line" : "list"],
    ["html", { open: "never", outputFolder: process.env.WIKI_PLAYWRIGHT_HTML_REPORT || "../../output/playwright/wiki-cockpit-downstream-report" }],
    ["json", { outputFile: process.env.WIKI_PLAYWRIGHT_JSON_REPORT || "./test-results/downstream-results.json" }]
  ],
  use: {
    baseURL: process.env.WIKI_COCKPIT_REAL_BASE_URL,
    colorScheme: "dark",
    locale: "pt-BR",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure"
  },
  projects: [
    {
      name: "chromium-downstream-required",
      use: {
        ...devices["Desktop Chrome"],
        browserName: "chromium",
        deviceScaleFactor: 1,
        viewport: { width: 1280, height: 900 }
      }
    }
  ]
});
