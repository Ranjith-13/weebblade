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

  /* AWAITED, NOT READ ONCE. The theme now applies inside a View Transition, so
     the attribute lands a frame after the click rather than during it - the API
     snapshots the old state first, which is the whole mechanism. Reading
     immediately raced it: this passed on desktop and failed on phone, which is
     the worst shape a test can have. The retrying assertion describes the real
     behaviour, which is "shortly", not "synchronously". */
  await page.getByRole("button", { name: "dark", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const chosen = await state();
  expect(chosen.bg).not.toBe(fresh.bg);

  await page.reload({ waitUntil: "domcontentloaded" });
  const reloaded = await state();
  expect(reloaded.attr, "applied before hydration, not after").toBe("dark");
  expect(reloaded.bg, "no flash of the system theme").toBe(chosen.bg);

  // And System is a real choice, not the absence of one.
  await page.getByRole("button", { name: "system", exact: true }).click();
  await expect(page.locator("html")).not.toHaveAttribute("data-theme", /.*/);

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

    // Same wait as above: the flip happens inside a View Transition.
    await expect(page.locator("html")).toHaveAttribute("data-theme", opposite);
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

/* A POSTER THAT 404s MUST STILL BE A PLATE. Six of the catalogue's poster URLs
   are dead at Kitsu's origin - the title keeps a poster_url, so an <Image> was
   rendered, and because alt="" a failed one draws nothing at all: the reader
   got an empty bordered box rather than the design's own no-artwork treatment.
   The name is rendered underneath every poster so a dead one reveals it.

   Asserted as a property of every plate rather than against a named title: the
   dead six change as Kitsu repairs or breaks things, and a test naming one of
   them goes red on a week nobody touched this. */
test("every plate carries its name beneath the artwork", async ({ page }) => {
  await page.goto("/browse");
  await page.waitForLoadState("networkidle");

  const plates = await page.evaluate(() => {
    const holders = [...document.querySelectorAll("a .relative")].filter((d) =>
      d.querySelector("img"),
    );
    return holders.map((d) => {
      const img = d.querySelector("img")!;
      const name = d.querySelector("span.absolute");
      return {
        named: !!name?.textContent?.trim(),
        loaded: (img as HTMLImageElement).naturalWidth > 0,
        covers: getComputedStyle(img).objectFit === "cover",
      };
    });
  });

  expect(plates.length, "there are plates to check").toBeGreaterThan(5);
  expect(plates.every((p) => p.named), "each has a name under its artwork").toBe(true);
  // And a poster that did load hides it completely, so nothing shows through.
  expect(plates.filter((p) => p.loaded).every((p) => p.covers)).toBe(true);
});

/* COMPONENT FEEL, and the half of it that is easy to ship broken.
 *
 * Section 6 of DESIGN.md is explicit that reduced motion means NO animation
 * rather than a faster one, and every one of these is CSS rather than GSAP, so
 * none of them is covered by the matchMedia guard the GSAP effects live inside.
 * A no-preference block is the whole mechanism; delete it and all three keep
 * running for a reader who asked them not to. So each is asserted twice. */
for (const motion of ["no-preference", "reduce"] as const) {
  const moving = motion === "no-preference";

  test(`component motion is ${moving ? "on" : "off"} under prefers-reduced-motion: ${motion}`, async ({
    browser,
  }) => {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      reducedMotion: motion === "reduce" ? "reduce" : "no-preference",
    });
    const page = await context.newPage();
    await page.goto("/browse");

    // The loading shapes and the search sweep, probed as rules rather than by
    // racing a real fallback: the question is whether the stylesheet matches.
    const anims = await page.evaluate(() => {
      const nameFor = (attr: string) => {
        const d = document.createElement("div");
        d.setAttribute(attr, "");
        document.body.append(d);
        const n = getComputedStyle(d).animationName;
        d.remove();
        return n;
      };
      return { skeleton: nameFor("data-skeleton"), sweep: nameFor("data-sweep") };
    });
    expect(anims.skeleton).toBe(moving ? "plate-breath" : "none");
    expect(anims.sweep).toBe(moving ? "rule-sweep" : "none");

    // Press feedback. Hover does not exist on a phone, so this is the only
    // acknowledgement a tap gets before the page changes.
    const button = page.locator(".season-index-toggle");
    const box = (await button.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    const pressed = await button.evaluate((e) => getComputedStyle(e).translate);
    await page.mouse.up();
    expect(pressed, "a press moves the control, or does not").toBe(moving ? "0px 1px" : "none");
    await page.keyboard.press("Escape");

    /* And the controls that are links rather than buttons - the nav sections,
       the filter chips, the pager. These opt in by attribute rather than a
       blanket a:active, because "Clear the filters" sits inside a sentence and
       a line of prose that twitches under the thumb is worse than one that does
       nothing. So the prose link is asserted to stay still in both modes. */
    const navLink = page.locator("header nav a[data-pressable]").first();
    await navLink.hover();
    await page.mouse.down();
    const linkPressed = await navLink.evaluate((e) => getComputedStyle(e).translate);
    await page.mouse.up();
    expect(linkPressed, "a control-shaped link presses").toBe(moving ? "0px 1px" : "none");

    const prose = page.locator("main p a:not([data-pressable])").first();
    if (await prose.count()) {
      await prose.scrollIntoViewIfNeeded();
      await prose.hover();
      await page.mouse.down();
      const prosePressed = await prose.evaluate((e) => getComputedStyle(e).translate);
      await page.mouse.up();
      expect(prosePressed, "running text never presses").toBe("none");
    }

    /* The theme flip. Reduced motion is checked in the component rather than in
       CSS, because suppressing the animation in a stylesheet still takes the
       snapshot - so the assertion is that the API was not CALLED, and that the
       theme applied regardless. Motion is removed; the feature is not. */
    const flip = await page.evaluate(async () => {
      let called = false;
      const real = document.startViewTransition;
      const supported = typeof real === "function";
      if (supported) {
        document.startViewTransition = function (cb: () => void) {
          called = true;
          return real.call(this, cb);
        };
      }
      document.querySelector<HTMLButtonElement>('header button[aria-label^="Switch"]')!.click();
      await new Promise((r) => setTimeout(r, 500));
      return { supported, called, theme: document.documentElement.getAttribute("data-theme") };
    });
    if (flip.supported) expect(flip.called, "cross-faded, or cut").toBe(moving);
    expect(flip.theme, "the theme applies either way").toBeTruthy();

    await context.close();
  });
}

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

/* THE SCORE SAYS WHETHER IT HAS STOPPED MOVING, and says who moved it.
 *
 * The number itself is a commodity - three other sites print it. What this one
 * can say is that its sources revised it twice last week, measured against
 * 30.9% of re-asked readings of an airing season changing against 0.8% of a
 * finished one.
 *
 * ATTRIBUTION IS THE ASSERTION. The figure in this line is one source's while
 * the score above it is the merged winner, and the two legitimately differ -
 * Dragon Ball Super shows 8.3 beside a newest change of 8.0 to 8.1. Unattributed
 * that is the site contradicting itself on one screen, so a line without a
 * source name is a bug rather than a cosmetic miss.
 *
 * Asserted as an invariant over whatever titles the season holds, never against
 * a named one: which shows are airing changes every week. */
test("a score that moved says so, and names who moved it", async ({ page }) => {
  await page.goto("/browse");
  const hrefs = await page.evaluate(() =>
    [...document.querySelectorAll('a[href^="/anime/"]')]
      .map((a) => a.getAttribute("href")!)
      .slice(0, 6),
  );
  expect(hrefs.length, "titles to open").toBeGreaterThan(0);

  const SOURCES = ["Kitsu", "MyAnimeList", "AniList"];
  let seen = 0;
  for (const href of hrefs) {
    await page.goto(href);
    await page.waitForLoadState("networkidle");
    const line = await page.evaluate(() => {
      const el = [...document.querySelectorAll("p")].find((e) =>
        (e.textContent ?? "").trim().startsWith("Revised "),
      );
      return el?.textContent?.trim() ?? null;
    });
    if (!line) continue; // nothing re-asked yet, which is a real state
    seen += 1;
    expect(line, `"${line}" names the source that revised it`).toMatch(
      new RegExp(SOURCES.join("|")),
    );
    expect(line, `"${line}" says when`).toMatch(/since \d/);
  }
  test.skip(seen === 0, "no title in this season has a recorded score revision");
});

/* A FINISHED SEASON SAYS ITS NUMBERS ARE FROZEN. The weekly run refetches the
   current season and the next one; everything older holds whatever its sources
   said the day it was captured, and a 2017 score will not move again. True
   since the first backfill and stated nowhere until now.

   The seasons are read off the page rather than named, because naming one is a
   test that goes red the week Summer becomes Fall - the same rule the rest of
   this suite follows. The oldest season in the index must carry the line; the
   default view, which is the current season, must not. */
test("an old season says it is no longer refetched", async ({ page }) => {
  const frozen = () =>
    page.evaluate(() =>
      [...document.querySelectorAll("p")].some((e) =>
        (e.textContent ?? "").includes("no longer refetched"),
      ),
    );

  await page.goto("/browse");
  expect(await frozen(), "the current season is still being refetched").toBe(false);

  /* From the season index specifically, not any link carrying season=. Every
     genre chip and format chip carries one too, and the first attempt read the
     last of those: it picked an UPCOMING season, which is refetched, and failed
     saying "2027-WINTER is older than the current season". */
  const keys = await page.evaluate(() =>
    [...document.querySelectorAll('.season-index a[href*="season="]')]
      .map((a) => new URL((a as HTMLAnchorElement).href).searchParams.get("season"))
      .filter((k): k is string => !!k),
  );
  const oldest = keys.at(-1);
  test.skip(!oldest, "no season links on the page to read");

  await page.goto(`/browse?season=${oldest}`);
  expect(await frozen(), `${oldest} is older than the current season`).toBe(true);
});

/* THE NAV IS THE SAME WIDTH ON EVERY ROUTE, and that is the property that was
   missing rather than a tidiness. The current section is semibold, so the row
   measured 366px with nothing marked and 372px with "Schedule" marked - it
   reflowed under the cursor on every navigation, and worse, it fitted a 390px
   viewport on some routes and not others. That variance is exactly why the
   overflow bug survived: looking at one page confirmed the row was fine.

   Each label now reserves its marked width, so this asserts the invariant that
   makes the budget meaningful. It also checks the row fits its COLUMN, not just
   the viewport - a row can clear the window while hanging into the gutter, which
   is how the first version of the fix passed and still looked wrong. */
for (const width of [390, 1440]) {
  test(`the nav keeps one width across routes at ${width}`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width, height: 800 } });
    const page = await context.newPage();
    const widths = new Map<string, number>();

    for (const path of ["/", "/browse", "/schedule", "/changes", "/search", "/digest"]) {
      await page.goto(path);
      const seen = await page.evaluate(() => {
        const nav = document.querySelector("header nav")!.getBoundingClientRect();
        const holder = document.querySelector("header > div")!;
        const inner =
          holder.getBoundingClientRect().right -
          parseFloat(getComputedStyle(holder).paddingRight);
        return { width: Math.round(nav.width), fitsColumn: nav.right <= inner + 0.5 };
      });
      widths.set(path, seen.width);
      expect(seen.fitsColumn, `${path} at ${width}: the nav stays inside its column`).toBe(true);
    }

    expect(
      new Set(widths.values()).size,
      `the nav is one width everywhere, got ${JSON.stringify([...widths])}`,
    ).toBe(1);
    await context.close();
  });
}

/* NOTHING MAY PUSH THE PAGE SIDEWAYS. The nav's five sections already take
   352px of a 390px line, which ARCHITECTURE.md records as a measurement and which,
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
