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

/* DARK MODE, CHECKED THE WAY THIS PROJECT CHECKS COLOUR: computed, never
 * eyeballed. globals.css claims a contrast figure for every pair in both
 * palettes; this measures the rendered values and does the arithmetic, so a
 * token edited to taste cannot quietly drop a pair below AA.
 *
 * Both modes in one test, because the point is that the SAME markup satisfies
 * both - every utility reads a variable, so nothing in any component knows
 * which mode it is in. */
function contrast(a: [number, number, number], b: [number, number, number]) {
  const lum = (c: [number, number, number]) =>
    c.map((v) => {
      const x = v / 255;
      return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
    }).reduce((acc, v, i) => acc + v * [0.2126, 0.7152, 0.0722][i], 0);
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

for (const scheme of ["light", "dark"] as const) {
  test(`the palette clears AA in ${scheme} mode`, async ({ browser }) => {
    const page = await browser.newPage({ colorScheme: scheme });
    await page.goto("/browse");
    await page.waitForTimeout(2500);

    const rgb = (value: string): [number, number, number] => {
      const m = value.match(/\d+/g)!;
      return [Number(m[0]), Number(m[1]), Number(m[2])];
    };

    const measured = await page.evaluate(() => {
      const cs = getComputedStyle(document.body);
      const h1 = getComputedStyle(document.querySelector("h1")!);
      const tab = document.querySelector('[class*="bg-flag"]');
      return {
        background: cs.backgroundColor,
        body: cs.color,
        heading: h1.color,
        tabBg: tab ? getComputedStyle(tab).backgroundColor : null,
        tabText: tab ? getComputedStyle(tab).color : null,
      };
    });

    const bg = rgb(measured.background);
    expect(contrast(rgb(measured.body), bg), `body text in ${scheme}`).toBeGreaterThanOrEqual(4.5);
    expect(contrast(rgb(measured.heading), bg), `heading in ${scheme}`).toBeGreaterThanOrEqual(4.5);

    /* The score tab is the one place the signal colour is a BACKGROUND, so it
       has to clear AA from the other side as well. It is the single most
       important pair on the site: it is what "this value is known" looks like. */
    if (measured.tabBg && measured.tabText) {
      expect(
        contrast(rgb(measured.tabText), rgb(measured.tabBg)),
        `score tab in ${scheme}`,
      ).toBeGreaterThanOrEqual(4.5);
    }

    await page.close();
  });
}

/* The theme control, and specifically the half of it that can fail silently.
 *
 * A stored choice lives in localStorage, which the server cannot read, so the
 * root layout ships a blocking inline script that applies it before first
 * paint. The first version of that script read localStorage.getItem(undefined)
 * - the key was exported from a "use client" module, so the Server Component
 * importing it got a client reference instead of the string. It compiled, it
 * ran, and it did nothing: every reload painted the system's answer and then
 * snapped to the reader's.
 *
 * So the assertion that matters is made at domcontentloaded, BEFORE hydration.
 * A test that waits for the page to settle would pass on a site that flashes. */
test("an explicit theme survives a reload without a flash", async ({ browser }) => {
  // A light OS, so only an explicit choice can make it dark.
  const context = await browser.newContext({ colorScheme: "light" });
  const page = await context.newPage();
  const state = () =>
    page.evaluate(() => ({
      attr: document.documentElement.getAttribute("data-theme"),
      bg: getComputedStyle(document.body).backgroundColor,
    }));

  await page.goto("/browse");
  const fresh = await state();
  expect(fresh.attr, "untouched follows the system").toBeNull();

  await page.getByRole("button", { name: "dark", exact: true }).click();
  const chosen = await state();
  expect(chosen.attr).toBe("dark");
  expect(chosen.bg).not.toBe(fresh.bg);

  await page.reload({ waitUntil: "domcontentloaded" });
  const reloaded = await state();
  expect(reloaded.attr, "applied before hydration, not after").toBe("dark");
  expect(reloaded.bg, "no flash of the system theme").toBe(chosen.bg);

  // And System is a real choice, not the absence of one.
  await page.getByRole("button", { name: "system", exact: true }).click();
  expect((await state()).attr).toBeNull();

  await context.close();
});

/* The masthead toggle, and the two things about it that broke in review.
 *
 * It is a second control over one piece of state, so the failure mode is the
 * two disagreeing: the footer kept rendering "System" as current after the
 * header had moved the page to dark. localStorage fires `storage` in OTHER
 * tabs only, so a local change dispatches its own event; without that the
 * footer is stale until something else re-renders it, which looks exactly like
 * a control that did nothing.
 *
 * And it flips against what the reader is LOOKING at, not what they chose, so
 * under a dark OS an untouched page offers "light". Resolving that needs the
 * media query, not just the stored value. */
test("the masthead toggle flips the page and agrees with the footer", async ({ browser }) => {
  for (const scheme of ["light", "dark"] as const) {
    const context = await browser.newContext({ colorScheme: scheme });
    const page = await context.newPage();
    await page.goto("/browse");

    const opposite = scheme === "light" ? "dark" : "light";
    const toggle = page.getByRole("button", { name: `Switch to the ${opposite} theme` });
    await expect(toggle, `under a ${scheme} OS it offers ${opposite}`).toBeVisible();

    const before = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    await toggle.click();

    expect(await page.evaluate(() => document.documentElement.getAttribute("data-theme"))).toBe(
      opposite,
    );
    expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).not.toBe(
      before,
    );

    // The footer control is the same state seen from elsewhere, so it has to
    // have moved too - this is the half that fails silently.
    await expect(
      page.getByRole("button", { name: opposite, exact: true }),
      "the footer agrees with the header",
    ).toHaveAttribute("aria-pressed", "true");

    // And it flips back, naming the other direction now.
    await expect(page.getByRole("button", { name: `Switch to the ${scheme} theme` })).toBeVisible();

    await context.close();
  }
});

/* ENTER MEANS TWO THINGS, and on a catalogue of Japanese titles the second one
   is not an edge case. While an IME is composing, Enter confirms the candidate;
   it does not submit. Unguarded, picking the kanji for a half-typed kana fired a
   search on the fragment and spent one of the reader's 20 queries a minute.

   The assertion is on the network, not the handler: a guard that calls
   preventDefault on an event nobody submits would pass a DOM-level test. */
test("an IME's Enter does not fire a search", async ({ page }) => {
  const api: string[] = [];
  page.on("request", (r) => {
    if (/onrender\.com\/search/.test(r.url())) api.push(r.url());
  });

  await page.goto("/search");
  await page.fill("#q", "ゆるキャン");

  await page.evaluate(() =>
    document
      .querySelector("#q")!
      .dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Enter",
          isComposing: true,
          bubbles: true,
          cancelable: true,
        }),
      ),
  );
  await page.waitForTimeout(1200);
  expect(api, "composing Enter sends nothing").toHaveLength(0);

  // And a real Enter, composition finished, still searches.
  await page.press("#q", "Enter");
  await expect
    .poll(() => api.length, { timeout: 40_000, message: "a finished Enter searches" })
    .toBe(1);
  expect(decodeURIComponent(api[0]), "the whole phrase, not a fragment").toContain("ゆるキャン");
});

/* The two long pages: following an anchor has to say where it put you, and the
   heading has to stay once you are there. Both pages run past thirty viewports
   on a phone, where every row below a heading reads the same under any of them. */
for (const path of ["/changes", "/schedule"]) {
  test(`${path} marks the section an anchor landed on`, async ({ page }) => {
    await page.goto(path);
    const id = await page.evaluate(() => document.querySelector("section[id]")?.id);
    const rule = () =>
      page.evaluate(
        (s) => getComputedStyle(document.querySelector(`section[id="${s}"] > h2`)!).borderBottomColor,
        id,
      );

    const unmarked = await rule();
    await page.goto(`${path}#${id}`);
    const marked = await rule();
    expect(marked, "the landed section is flagged").not.toBe(unmarked);
    expect(marked, "and flagged in the marker colour, not some new one").toBe("rgb(194, 0, 94)");
  });

  test(`${path} parks its section heading on a phone only`, async ({ browser }) => {
    for (const [width, want] of [
      [390, "sticky"],
      [1440, "static"],
    ] as const) {
      const context = await browser.newContext({ viewport: { width, height: 844 } });
      const page = await context.newPage();
      await page.goto(path);
      // Above sm the page flows in newspaper columns, and sticky inside a
      // multicol fragment is undefined - so it must NOT be sticky there.
      await expect
        .poll(
          () =>
            page.evaluate(
              () => getComputedStyle(document.querySelector("section[id] > h2")!).position,
            ),
          { message: `${path} at ${width}` },
        )
        .toBe(want);
      await context.close();
    }
  });
}

/* Scrolling to the end of the season list should stop there, not carry on into
   the catalogue standing behind it. */
test("the season index contains its own scroll", async ({ page }) => {
  await page.goto("/browse");
  await page.click(".season-index-toggle");
  await expect(page.locator(".season-index")).toBeVisible();
  expect(
    await page.evaluate(
      () => getComputedStyle(document.querySelector(".season-index")!).overscrollBehaviorY,
    ),
  ).toBe("contain");
});

/* NOTHING MAY PUSH THE PAGE SIDEWAYS. The nav's five sections already take
   352px of a 390px line, which CLAUDE.md records as a measurement and which,
   until this test, nothing enforced: adding the theme toggle beside them gave
   the site its first horizontal scrollbar and it was caught by hand, which is
   not a process. The toggle rides with the wordmark for this reason. */
for (const width of [390, 1440]) {
  test(`no horizontal overflow at ${width}`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width, height: 844 } });
    const page = await context.newPage();
    // /search and /schedule carry the longest marked nav item, which is what
    // tipped the row past the viewport; both belong in this list.
    for (const path of ["/", "/browse", "/schedule", "/changes", "/search", "/digest"]) {
      await page.goto(path);
      const doc = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth,
      }));
      expect(doc.scroll, `${path} at ${width} fits its viewport`).toBeLessThanOrEqual(doc.client);
    }
    await context.close();
  });
}

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
