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
  { path: "/scores", heading: /score/i },
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

  /* The per-source history is the one thing here no other anime site has, and
     it sits below the synopsis, the trailer and the facts. A reader is told at
     the top that it exists - but only where it does, since the weekly run
     refetches the current season alone and most older titles have none.
     Asserted as an implication rather than a fact about any particular title,
     because which titles have history changes every week and a test that goes
     red for that is a test that gets deleted. */
  const history = page.locator("#what-changed");
  if (await history.count()) {
    await expect(page.locator('a[href="#what-changed"]')).toBeVisible();
  }

  /* The score's arc, where it has one. Shown only when the score moved at the
     one decimal this page prints, which is about half of a current season and
     none of a year ago - so this is an implication, like the history link
     above, rather than a fact about whichever title the catalogue happens to
     lead with today. The shape is asserted because the failure mode is a
     sentence that reads "up from 8.41 since 2026-10-04": right numbers, wrong
     product. */
  const arc = page.getByText(/(up from|down from|between) \d+\.\d/);
  if (await arc.count()) {
    await expect(arc.first()).toHaveText(
      /^(up from \d\.\d|down from \d\.\d|between \d\.\d and \d\.\d) since \d{1,2} [A-Z][a-z]+$/,
    );
  }

  /* "More like this", which is the one block here that is a guess rather than a
     fact. Asserted as an implication, like the history link above: a title with
     no synopsis gets no neighbours by design, and a warehouse published before
     ai/search/similar.py existed has none at all, so its absence is a state
     rather than a failure. What must hold where it does appear is that it links
     to real title pages and never to the franchise listed right above it. */
  const similar = page.locator("#similar-title");
  if (await similar.count()) {
    const links = page.locator('section[aria-labelledby="similar-title"] a[href^="/anime/"]');
    expect(await links.count(), "similar titles").toBeGreaterThan(0);
    const franchise = await page
      .locator('section[aria-labelledby="franchise-title"] a[href^="/anime/"]')
      .evaluateAll((nodes) => nodes.map((n) => n.getAttribute("href")));
    const suggested = await links.evaluateAll((nodes) =>
      nodes.map((n) => n.getAttribute("href")),
    );
    expect(suggested.filter((href) => franchise.includes(href)), "franchise in similar").toEqual([]);
  }

  /* The card a shared link unfurls into. Rendered by Satori, which fails at
     runtime in ways neither tsc nor the build can see - an unsupported CSS
     property, a font that will not parse, a poster that 404s at the origin (six
     already do). Asserted as a real PNG of the right size rather than as a 200,
     because an error page is also a 200. */
  const card = await page.request.get(`${href}/opengraph-image`);
  expect(card.status(), "opengraph-image status").toBe(200);
  expect(card.headers()["content-type"]).toContain("image/png");
  const png = await card.body();
  expect(png.subarray(0, 8).toString("binary")).toBe("\x89PNG\r\n\x1a\n");
  expect(png.readUInt32BE(16), "card width").toBe(1200);
  expect(png.readUInt32BE(20), "card height").toBe(630);

  expect(errors, "title page console").toEqual([]);
});

/* The digest is the one block of prose here that nobody wrote, and the home page
 * prints its lead paragraph. The run of 2026-10-12 carried five em-dashes - one
 * of them in that lead - plus 26 non-breaking hyphens and 13 narrow no-break
 * spaces, against a design rule that bans the first by name. plainPunctuation()
 * in lib/types.ts repunctuates it on the way out of the data layer.
 *
 * Asserted on the rendered page rather than on the function, because what has to
 * be true is that none of it reaches a reader, and the next digest will be
 * written by a model that has never read DESIGN.md. An absence assertion, so it
 * cannot be flaky: a week whose digest is already clean passes for the right
 * reason, and a week whose digest is missing skips. */
const GENERATED = { "em-dash": "\u2014", "non-breaking hyphen": "\u2011", "narrow no-break space": "\u202f" };

test("the digest reaches the page with none of the typography a model reaches for", async ({ page }) => {
  await page.goto("/");

  const lead = page.locator(".digest-prose");
  if (!(await lead.count())) test.skip(true, "no digest on file yet");

  const dated = await page.locator('a[href^="/digest/"]').first().getAttribute("href");
  for (const path of ["/", dated].filter(Boolean)) {
    await page.goto(path!);
    const prose = await page.locator(".digest-prose").first().innerText();
    expect(prose.length, `${path} digest prose`).toBeGreaterThan(0);
    for (const [name, char] of Object.entries(GENERATED)) {
      expect(prose.includes(char), `${path} digest contains a ${name}`).toBe(false);
    }
  }
});

/* The streamed pages, which send their layout before their content: the footer
 * waits for the content (data-footer-waits in globals.css) so it cannot be
 * pushed down when it arrives. That guard is invisible until it breaks, so it
 * is measured rather than assumed. */
for (const path of ["/schedule", "/changes", "/scores"]) {
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
