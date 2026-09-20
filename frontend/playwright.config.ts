import { defineConfig, devices } from "@playwright/test";

/* Smoke tests against a production build, because that is the thing that ships.
 *
 * Until now CI typechecked, linted and built the frontend and nothing checked
 * that a page rendered anything: a component deleted from a commit still built
 * (fe28245) and every behaviour check was done by hand. These assert what a
 * reader would notice - the page arrives, it has content, the console is clean,
 * and the streamed pages do not shift as they fill in.
 *
 * Deliberately data-agnostic: they run against the live API, whose catalogue
 * changes weekly, so nothing here asserts a title, a count or a season.
 */
const PORT = Number(process.env.PLAYWRIGHT_PORT ?? 3100);

export default defineConfig({
  testDir: "./e2e",
  // One worker: the API rate-limits per IP (60/min), and a production build
  // serving several pages at once is how to hit it from a single runner.
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  timeout: 60_000,
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } },
    { name: "phone", use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 } } },
  ],
  webServer: {
    command: `npm run start -- -p ${PORT}`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
