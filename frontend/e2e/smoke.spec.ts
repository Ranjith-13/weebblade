import { expect, test, type Page } from "@playwright/test";

/* What a reader would notice, on the pages they actually land on. Nothing here
 * asserts a title, a count or a season: the catalogue changes every week, and a
 * test that breaks when Summer becomes Fall is a test that gets deleted. */

const ROUTES = [
  { path: "/", heading: /WeebBlade|Summer|Fall|Winter|Spring/i },
  { path: "/browse", heading: /./ },
  { path: "/schedule", heading: /Schedule|This week|Airing/i },
  { path: "/changes", heading: /What changed/i },
  { path: "/search", heading: /Search/i },
  { path: "/digest", heading: /Digest/i },
];

/** Console errors, minus the ones a browser emits for reasons of its own. */
function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const text = m.text();
    // Image CDNs and the preload heuristic are upstream noise, not this app.
    if (/favicon|preloaded using link preload|ERR_(BLOCKED|CERT|NAME)/i.test(text)) return;
    errors.push(text);
  });
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  return errors;
}

for (const route of ROUTES) {
  test(`${route.path} renders with content and a clean console`, async ({ page }) => {
    const errors = watchConsole(page);
    const response = await page.goto(route.path);

    expect(response?.status(), `${route.path} status`).toBeLessThan(400);
    await expect(page.locator("h1").first()).toBeVisible();
    await expect(page.locator("h1").first()).toHaveText(route.heading);
    // Real content, not just a shell: the streamed body has arrived.
    await expect(page.locator("main")).not.toBeEmpty();
    await page.waitForTimeout(2500);
    expect(errors, `${route.path} console`).toEqual([]);
  });
}

test("a title page opens from the catalogue and carries its facts", async ({ page }) => {
  const errors = watchConsole(page);
  await page.goto("/browse");
  const first = page.locator('main a[href^="/anime/"]').first();
  await expect(first).toBeVisible();
  // Followed rather than clicked: a client-side transition keeps the old page
  // in the DOM while the new one streams, and the assertions below would race
  // it. What matters here is that the catalogue's links lead to real pages.
  const href = await first.getAttribute("href");
  expect(href).toMatch(/\/anime\/wb_[0-9a-f]+/);
  await page.goto(href!);
  await expect(page.locator("h1")).toBeVisible();
  // Every title page states a status, whatever else it lacks.
  await expect(page.getByText(/Status/i).first()).toBeVisible();
  expect(errors, "title page console").toEqual([]);
});

/* The streamed pages, which send their layout before their content: the footer
 * waits for the content (data-footer-waits in globals.css) so it cannot be
 * pushed down when it arrives. That guard is invisible until it breaks, so it
 * is measured rather than assumed. */
for (const path of ["/schedule", "/changes"]) {
  test(`${path} does not shift as it fills in`, async ({ page }) => {
    await page.addInitScript(() => {
      (window as unknown as { __cls: number }).__cls = 0;
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries() as (PerformanceEntry & { value: number; hadRecentInput: boolean })[]) {
          if (!entry.hadRecentInput) (window as unknown as { __cls: number }).__cls += entry.value;
        }
      }).observe({ type: "layout-shift", buffered: true });
    });

    await page.goto(path);
    await page.waitForTimeout(3500);

    const cls = await page.evaluate(() => (window as unknown as { __cls: number }).__cls);
    expect(cls, `${path} cumulative layout shift`).toBeLessThan(0.02);
  });
}
