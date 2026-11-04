# WeebBlade — Design

**Direction: Halftone Almanac, colour as certainty.**

A seasonal anime almanac whose real subject is *what the pipeline knows this week*. The design's
one idea and the data's one problem are the same thing, and that is deliberate.

---

## 1. What the data actually is

Measured against the live API, not assumed. Everything below drove a design decision.

| Field | Coverage (142 titles) | Consequence |
|---|---|---|
| `popularity` | **142 / 142** | The only dense ranking signal |
| `genres` | 142 / 142 | Reliable, but **98 distinct values** — long tail |
| `poster_url` | 105 (74%) | 37 titles need a typographic fallback |
| `episodes` | ~113 | Usually present |
| **`score_100`** | **39 (27%)** | **Ranking on score alone ignores 73% of the season** |
| `studios` | **0** | Do not render |
| `source_material` | **0** | Do not render |
| `mal_id` | **0** | Do not render |
| `favourites` | 142, range 0–25 | Noise dressed as a metric. Do not render |

This table is from when the warehouse held one season. It now holds twenty-two (Fall 2021 to
Winter 2027, 6,359 titles from Kitsu, MAL and AniList on 2026-10-14), reached from the season
index in the header; see frontend/ARCHITECTURE.md, "Getting to a season". The coverage figures below
were measured on 2026-09-14 over the 6,136 the warehouse held then, and are kept at that date
rather than refreshed, because what they are evidence for is the shape of the gaps: score
58% (88% of a season's TV), poster 99.9%, popularity 98.6%, studios 57%, trailer 48%, a streaming
link 46%, cover art 30%. A season runs 233 to 370 titles, 57 to 88 of them TV.

### Three upstream behaviours the UI must work around

1. **Pagination is unstable under the default sort.** `score_desc` is
   `ORDER BY score_100 DESC NULLS LAST` over 103 NULLs, so the tie block has no deterministic
   order and `LIMIT/OFFSET` slices a differently shuffled result each call. Three identical
   two-page fetches returned **126, 116 and 122** distinct titles. `sort=title` is stable (142
   rows, 142 distinct ids, identical across runs) and is pinned in `lib/api.ts`.
2. **`popularity` is a rank — lower is more popular.** The API's only popularity sort is
   `popularity_desc`, which therefore returns the *least* popular first. Sorted locally instead.
3. **Genre tags must be derived, not hardcoded.** The previous filter row offered `Sci-Fi`, which
   matched nothing; the real tag is `Science Fiction`.

---

## 2. The idea

> **Colour is the reward for known data.**

- A title the pipeline has a score for prints in **full colour** with a flag-pink score tab.
- A title it does not drains to **greyscale and screens back to visible halftone**, with an
  em-dash where the number would be.
- A title with **no artwork** gets a diagonal rule fill and its name set large — a *separate*
  state, because a missing poster is a different gap from a missing score. A title can be scored
  and have no artwork, and the design says both things at once.

When this was drawn, 73% of the season was in the screened-back state: not an edge case being
styled but the majority condition, so the page had to look composed when most of it was unknown.
With MAL and AniList it is far less, but it never goes away, and the reason is structural:
the default view is the newest season that has STARTED, which is always the one whose titles
have had the least time to be scored. Measured across five seasons on 2026-10-14:

| Season | TV screened back | All formats |
|---|---|---|
| Fall 2025 | 25% | 45% |
| Winter 2026 | 12% | 40% |
| Spring 2026 | 12% | 44% |
| Summer 2026 | 10% | 54% |
| **Fall 2026** (the default today) | **27%** | **56%** |

A season settles to about 10-12% once it has run; the one on screen by default sits at a
quarter, and more than half of it is screened back a format chip away. The page has to look
composed either way, and the design has not run out of work to do.

**The screened-back state is a stage, not a category, and `/scores` is where that is shown.**
Fall 2026 sat in the catalogue through four runs with no scored title at all, then went 1 to 19
to 55 to 59 of 81 in fifteen days (2026-10-12). Every plate in a new season starts unknown and
most of them stop being unknown; the halftone is the first few weeks of a title's life, drawn.
Once a score exists it keeps moving while the show is on air and then stops moving where the
page can print it, without ever stopping being revised. That page is the one place here that
reads the warehouse down its dates rather than across its titles, and it states its method
before it states a number, because the first version of the measurement counted snapshots and
measured the pipeline's refetch schedule instead.

This lives in two utilities in `globals.css` (`.plate-known` / `.plate-unknown`) and is applied
from `isKnown(anime)` — a real predicate over real data. **It must never be applied
decoratively.** The moment the halftone stops meaning "no score upstream", the design becomes
ornament and the honesty is gone.

**There is exactly one dot screen on this site, and that is the rule this paragraph was failing
to enforce.** A "paper tooth" shipped on 2026-09-09: ink dots at 4px pitch, opacity 0.38, over
every pixel of every page, to stop flat `#E9E7E0` reading as a grey div. It was a second
halftone, and a reader who sees dots everywhere has no reason to read dots on a plate as a fact.
It also rendered unpredictably — a 0.5px dot is sub-pixel, so it nearly vanished on the 1x display
it was tuned on and printed as a screen door over body text on a high-DPI one, which is why it
went five weeks unnoticed. Removed 2026-10-15, after comparing 0.38, 0.15 and none at both pixel
ratios: the paper colour, the hairlines and the didone already do the work it was added for.

The corollary is `.plate-fine`: a 36×49px thumbnail gets a 2px pitch, because 4px leaves nine dots
across the image and a screen nobody can read as a screen is decoration by another route.

---

## 3. Palette

Newsprint, not cream. Deliberately not the `#F4F1EA` + `#D97757` pairing.

| Token | Value | Contrast on paper | Role |
|---|---|---|---|
| `--color-paper` | `#E9E7E0` | — | Ground |
| `--color-plate` | `#DFDCD2` | — | Raised: fallback tiles, hover |
| `--color-rule` | `#C6C2B6` | — | Hairlines. Separation is rules, never shadow |
| `--color-ink` | `#15151A` | **14.71** | Body and display |
| `--color-ink-soft` | `#5E5E66` | **5.19** | Secondary text |
| `--color-flag` | `#C2005E` | **4.91** | "This value is known" |
| `--color-data` | `#1B3FBF` | **6.76** | Quantitative rails, links |

**Contrast is computed, not eyeballed.** The first draft used `#FF2E88` (**2.83** — fails even
large-text AA) and `#6E6E75` for muted text (**4.09** — fails body). Both were replaced with
measured values before a line of component code was written. Every pair above clears 4.5:1 against
its intended background, so there is no "accessible variant" to remember. If you change a colour,
re-measure.

Two signal colours only. A third is drift.

### Dark

The same ink on a darker stock, not an inverted page. Both signal hues are preserved **exactly**
and only their lightness moves, because a brand desaturated into dark mode stops being the brand.
`--color-ink` in dark is the light palette's own paper: what was the sheet becomes the ink.

| Pair | Light | Dark |
|---|---|---|
| ink on paper | 14.71 | 14.43 |
| ink-soft on paper | 5.19 | 5.51 |
| flag on paper | 4.91 | 5.24 |
| data on paper | 6.76 | 6.07 |
| **paper on flag** (the score tab, both ways) | 4.91 | 5.24 |
| rule on paper (hairline, non-text) | 1.44 | 1.43 |
| plate on paper (raised, non-text) | 1.11 | 1.14 |

The dark values are matched to the light palette's own *relationships* rather than merely
clearing AA, which is why the page reads as the same object rather than as a second design.

**Nothing in any component knows which mode it is in.** Every utility reads a variable, so this
was a palette change and not a rewrite. The halftone needs no dark variant either: its dots are
`--color-paper`, so on dark stock they become dark dots and the screen still reads as paper
showing through. Artwork loses a little brightness in dark, because a poster lit for a white page
glares against a dark ground.

**The social card does not follow.** `opengraph-image.tsx` reads these tokens out of `globals.css`
by regular expression and takes the first match, which is the light `@theme` block, so a shared
link unfurls in the product's primary identity. The dark block must stay below it.

`e2e/smoke.spec.ts` measures the rendered colours in both modes and does the arithmetic, so a
token edited to taste cannot quietly drop a pair below AA. Verified by setting dark `--color-ink`
to `#3a3a42`: the dark test failed at 1.59 and the light one still passed.

**There are two controls, and the difference between them is the point.** The footer sets a
*preference* - System / Light / Dark, with System a real answer rather than the absence of one.
The masthead corrects what is *on the screen right now*, so it is one button flipping two ways and
offers no System: that is a thing you set once, not a thing you reach for because the page is too
bright at this moment. Picking System in the footer hands the page back to the OS.

The toggle names the action, never the state - a button reading "Dark" beside a dark page cannot
say whether it describes or proposes - and it resolves System against the media query so it always
offers the mode the reader is *not* in. It wears the same hairline chip as the footer's three and
every facet on `/browse`, because that is already this site's word for "pressable": no radius, no
shadow, no icon. Set in plain `.meta` next to the wordmark it read "WeebBlade  Dark", the name of
an edition rather than a control.

Shipping the palette without either control was the real failure here, and it was reported as
"dark mode" for a week. A design that answers only `prefers-color-scheme` is a design with no
dark mode for every reader whose OS is light and whose room is not.

---

## 4. Typography

- **Bodoni Moda** — display. A didone: the historical face of printed almanacs and broadsheet
  mastheads, and its extreme thick/thin stroke contrast is the typographic echo of the halftone
  screen the design runs on, dense ink beside bare paper. Display sizes only; a didone's hairlines
  break up at body size.
- **Archivo** — text. A grotesque that survives 10px metadata without turning to mush.

**This is the second serif.** The first pass used Fraunces, reasoning that it avoided the
Instrument-Serif-plus-Inter pairing every editorial template ships. That reasoning was wrong:
Fraunces and Instrument Serif are *both* the display serifs generated sites reach for, so swapping
one for the other was a lateral move dressed up as a decision. If this ever changes again, pick a
face you can justify against **this** product, not against the last cliche.

**Do not add variable-font axes you do not vary.** Fraunces was first loaded with
`axes: ["SOFT", "WONK", "opsz"]`, none of which any rule ever set. Removing them took the home
page's font payload from **152 KB to 70 KB** with no visual change at all.

Tabular numerals (`.tnum`) on every figure — scores, counts, distances, ranks. Figures are the
substance here.

**Two levels of quiet text, and the split is load-bearing:**

- `.stamp` — uppercase, tracked. **Structural data labels only**: definition-list terms, a filter
  row's name. Five usages in the whole app.
- `.meta` — sentence case, no tracking. Everything merely small and secondary: provenance lines,
  plate metadata, pagination, back links, helper text.

This split exists because the first pass got it wrong twice over. The audit criticised the previous
build for using its equivalent 23+ times so every label shouted equally; the rewrite then shipped
**35** while claiming in this very document that it was "rationed". A label treatment applied to
everything communicates nothing. If `.stamp` creeps past single digits again, it has stopped being
a label and become a texture.

**It crept, and this paragraph did not stop it.** A title page rendered **14** of them on 2026-10-15:
three section heads and eleven rows of the facts table, each `<dt>` taking the stamp because a
definition-list term is on the sanctioned list. The predicted cost arrived exactly as written -
"Score", the number a reader opened the page for, was set identically to "Episode length". The
table's terms are `.meta` now and the page renders three. The lesson is that the budget is about
what the *page* shows, not how many places in the source apply it: one `<dt>` in a map is eleven
labels on screen.

---

## 5. Shape

Zero border-radius everywhere. No shadows — separation is hairline rules and negative space.

---

## 6. Motion

GSAP + ScrollTrigger, and **GSAP only**. Two animation libraries on the same elements compete for
the same frames and the resulting jank is very hard to attribute. GSAP earns the slot because it is
the only one that does real pinning and scrub-linked scroll.

Cost: **~49 KB gzipped**, in its own chunk. That is a real price on a site otherwise built to ship
almost no JS, and it is the reason each effect below has to justify itself.

| Effect | Where | Why it earns its place |
|---|---|---|
| Line-mask entrance | Masthead | The one moment the page announces itself. Above the fold, so a scroll trigger would never fire. |
| Parallax + scrub fade | Masthead | 12% speed difference makes the catalogue slide *over* the cover rather than with it. Scrub-linked, so dragging backwards plays it back. |
| **Coming into register** | **Plate grids** | **Offset printing's signature artifact is misregistration: plates landing a hair off true and being pulled in. The grid arrives as a sheet off a press rather than as a web page scrolling.** |
| Stagger reveal | Stat rail, digest archive, listings | A wall of near-identical rows landing at once gives the eye no order. A stagger turns a wall into a sequence. |
| **Pin** | "How to read this" key | Functional, not decorative: the key decodes the plates, so it stays put while plates scroll past it. Desktop only. |
| Parallax | Detail page key art | Stops one image plus one text column reading as a flat slab. Applied to the image *inside* a fixed frame, so nothing reflows. |
| Halftone lift | Unscored plate hover | CSS, not JS. The plate is screened because there is no score; leaning in reveals what *is* there. |

### Component motion, which is CSS and not GSAP

GSAP is for the page's set pieces and costs 49 KB. None of the following is worth a byte of it, and
all of it is transform and opacity only, so CLS stays 0.

| Effect | Where | Why it earns its place |
|---|---|---|
| Plate breath | Every loading skeleton | A static skeleton is indistinguishable from content that arrived holding nothing - and here the skeleton's resting tone *is* `--color-plate`, which is what an empty plate looks like. The whole shape breathes; nothing sweeps across it. |
| Press | Every `button` | Hover does not exist on a phone. A reader tapping a filter chip had no acknowledgement at all until the page changed, which on a cold request is a second of wondering whether the tap landed. One pixel down, the way a key presses into paper. |
| Indeterminate rule | `/search`, while waiting | A cold container answers in ~32s, and that was a line of static text. Never a percentage: nothing in the client knows how far along the request is, and a bar that invents one is lying to fill a gap. |
| Theme cross-fade | The toggle | The one moment where every colour on the page changes at once, so a hard cut between two frames reads as a glitch rather than a choice. A View Transition, so it costs no JavaScript and no library. |

**No shimmer, and the skeleton must never borrow the halftone.** A highlight sweeping across a
loading block is a material this design does not have. More importantly, animating the screen would
give it a second meaning - "not arrived yet" beside the only one it is allowed, "no score upstream" -
which is the same objection that keeps the halftone out of the entrance animations above.

**These are CSS, so the `gsap.matchMedia` guard does not cover them.** Each lives inside its own
`@media (prefers-reduced-motion: no-preference)` block, except the theme cross-fade, where the check
is in the component: suppressing a view transition's animation in a stylesheet still takes the
snapshot and still runs the machinery. The smoke suite asserts all four twice, once under each
preference, because a no-preference block is the entire mechanism and deleting it leaves everything
running for a reader who asked it not to. Motion is removed under `reduce`; the features are not -
the theme still applies, the press still presses, the search still searches.

**Deliberately not built:**

- **Horizontal scroll hijack.** `/browse` has filters, pagination and a season of 233 to 370 titles behind real URLs.
  Converting it to a horizontal pan breaks keyboard navigation, scroll restoration on back-nav, and
  the shareable-URL model that the whole filter design rests on.
- **Three.js.** There is no 3D content. It would be several hundred KB rendering nothing.
- **Lenis / smooth-scroll.** It overrides native scrolling, which fights fast scanning on a
  catalogue and is a known accessibility irritant. The scroll here should feel like the browser's.

**Reduced motion is not a "faster animation" path — it is no animation.** Every effect lives inside
`gsap.matchMedia("(prefers-reduced-motion: no-preference)")`. If that does not match, the callback
never runs, no inline styles are written, and elements render at their resting CSS state.

This was verified rather than assumed: the full-motion branch was temporarily disabled and the page
re-checked. All 12 plates and both masthead lines rendered fully visible, nothing stranded at
opacity 0.

**Everything animates transform and opacity only**, so no effect can trigger layout and CLS stays
at 0. Every animation uses `gsap.from()`, meaning the DOM's resting state is the *final* state: if
JS never runs, the page is complete and unstyled-back, not invisible.

**No entrance starts from invisible.** `autoAlpha: 0` made that promise false in practice: a
scroll trigger that has not fired holds its targets at opacity 0, so a full-page capture of the
home page showed the entire catalogue as blank paper, and a fast scroller saw the same thing.
Opacity now bottoms out at 0.35 on the plate grids. Measured after the change: all twelve plates
below the home page's fold sit at 0.35 rather than 0, and CLS is still 0 at 1440 and 390.

**The halftone is not an entrance and must never become one.** Animating the screen was the
obvious way to make a plate "develop", and it would give the screen a second meaning: "not
arrived yet" beside "no score upstream". Registration moves the artwork; the screen stays exactly
as honest as section 2 requires.

---

## 7. Layout decisions worth keeping

- **The digest lead is one paragraph, not the whole essay.** The full digest is ~700 words; the
  previous build printed all of it above the catalogue, which on a 390px phone was roughly four
  screens of unbroken prose before a single poster. Posters now appear at ~1270px instead of
  ~2400px. The rest is one click away at `/digest/[run_date]`.
- **The legend is load-bearing.** "How to read this" on the home page is the key to every plate on
  the site, not decoration.
- **Counts are stated honestly.** The old rail claimed "Sources 3" when two of the three are down
  upstream, and a title count that changed between refreshes.
- **The digest's own figures are flagged as point-in-time**, because the week this was written it
  said 140 where the season held 142. Two numbers disagreeing on one page needs a sentence, not
  silence.
- **Filters stay links, not client state** — no JS for filtering, and every view has a real
  shareable, back-button-able URL.

---

## 8. Data-layer architecture

`lib/api.ts` fetches the **whole season once** (a request per 100 titles, cached for hours) and
derives every filter, sort, facet and page locally. It never fetches the whole catalogue: the
season list comes from `GET /catalogue`, a studio's titles from `/anime?studio=`. This is not a
performance flourish:

- The upstream API rate-limits per client IP and every visitor shares this app's egress addresses,
  so caching is a **correctness boundary**, not a tweak.
- It is *fewer* upstream requests than passing filters through, not more.
- It is the only way to fix the unstable pagination, the inverted popularity sort and the drifted
  genre list, none of which can be fixed downstream.

`/search` is the deliberate exception: it runs **client-side** so each visitor spends their own
20/min budget on their own unique queries. Each result arrives from the API with its poster, score
and format, so it renders as a real plate with the correct certainty treatment. (This used to be a
lookup of the whole catalogue handed to the client, 514 KB of HTML at 2,755 titles, to decorate
twenty results.)

`lib/types.ts` is client-safe; `lib/api.ts` imports `server-only`. Importing `API_BASE` from
`api.ts` into a client component drags `cacheLife` into the browser bundle and fails the build —
the split makes that mistake fail loudly, naming the right file.

---

## 9. Explicitly avoid

Generic AI-dashboard aesthetics: rounded card grids on slate, purple-to-blue gradients, glowing
borders, emoji as iconography, a centred hero with a gradient headline, three-column feature cards
with circular icons. Also banned here specifically: **Inter, Geist, Roboto, Open Sans, Poppins**
and system-font defaults; ALL-CAPS tracked eyebrows used indiscriminately; `·`-joined metadata and
`→` appended to link text; one uniform grid where every item carries equal weight regardless of
what is known about it.

**No em-dashes in visible copy.** The em-dash is the single most reliable tell of generated prose,
and the first pass shipped 13 of them, including in the page title. The one carve-out is the `—`
used as a *null marker* on an unscored plate: that is standard typographic convention for "no
value" in tabular data, not a stylistic flourish.

**This is now a lint rule, because saying it here was not enough.** It was broken three more times
after being written down: twice in prose, and once as `&mdash;` on `/search`, which no search for
the character would ever have found. `eslint.config.mjs` rejects an em-dash in any JSX text, string
or template under `app/`, `components/` and `lib/`; the carve-out is exported as `NULL_MARKER` from
`lib/types.ts`, so the four places entitled to print one need no allowlist and declare themselves.
Comments are not matched, which is why this paragraph can exist.

**The digest is repunctuated, and it is the only text here that is.** It is written by an LLM, and
the run of 2026-10-12 carried five em-dashes, one of them in the lead paragraph the home page
prints, plus 26 non-breaking hyphens and 13 narrow no-break spaces. `plainPunctuation()` rewrites
them on the way out of the data layer: two em-dashes in a sentence become brackets, one becomes a
colon, and one straight after a figure becomes a comma. Punctuation only, never words, which is
what keeps the caption on `/digest` honest, and that caption was corrected in the same change
because it used to say the digests were kept unedited.

**No decorative markers.** No coloured dot or square before a label, no `01 / 02` numbering on a
list the reader can count, no `·` joining metadata.

**The test:** if this design would fit three other products, it is wrong. The halftone-as-certainty
system only makes sense for a product whose defining property is uneven data.
