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
    const url = m.location().url;
    // Image CDNs and the preload heuristic are upstream noise, not this app.
    if (/favicon|preloaded using link preload|ERR_(BLOCKED|CERT|NAME)/i.test(text)) return;
    // A POSTER THE SOURCE HAS SINCE DELETED. The catalogue stores the URL a
    // source gave for a title's artwork, and those rot: two of the schedule's
    // were gone from media.kitsu.app on 2026-10-13, 404 at the origin, which
    // the image optimiser passes through as a 404 of its own. That is the
    // catalogue being older than the CDN, not this app being broken, and there
    // is nothing a frontend can do about it - so it must not fail a suite that
    // runs on every push, or the suite gets turned off.
    //
    // Narrow deliberately: only a 404, and only through /_next/image. A
    // misconfigured remotePattern answers 400 and still fails here, as it
    // should, and so does a 404 on anything this app actually serves.
    if (/404/.test(text) && /\/_next\/image\?/.test(url)) return;
    // The URL, because "Failed to load resource" alone names nothing and the
    // first time this fired it cost a quarter of an hour to find out what.
    errors.push(url ? `${text} <- ${url}` : text);
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
