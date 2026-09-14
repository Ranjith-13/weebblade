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

This table is from when the warehouse held one season. It now holds twenty (Fall 2021 to Summer
2026, 6,148 titles from Kitsu, MAL and AniList), reached from the season index in the header; see
frontend/CLAUDE.md, "Getting to a season".

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

73% of the season is in the screened-back state. That is not an edge case being styled; it is the
majority condition, and the page has to look composed when most of it is unknown.

This lives in two utilities in `globals.css` (`.plate-known` / `.plate-unknown`) and is applied
from `isKnown(anime)` — a real predicate over real data. **It must never be applied
decoratively.** The moment the halftone stops meaning "no score upstream", the design becomes
ornament and the honesty is gone.

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
| Stagger reveal | Plate grids, stat rail, digest archive | 142 near-identical 3:4 plates landing at once give the eye no order. A stagger turns a wall into a sequence. |
| **Pin** | "How to read this" key | Functional, not decorative: the key decodes the plates, so it stays put while plates scroll past it. Desktop only. |
| Parallax | Detail page key art | Stops one image plus one text column reading as a flat slab. Applied to the image *inside* a fixed frame, so nothing reflows. |
| Halftone lift | Unscored plate hover | CSS, not JS. The plate is screened because there is no score; leaning in reveals what *is* there. |

**Deliberately not built:**

- **Horizontal scroll hijack.** `/browse` has filters, pagination and 142 titles behind real URLs.
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
- **The digest's own figures are flagged as point-in-time**, because this week it says 140 where
  the season holds 142. Two numbers disagreeing on one page needs a sentence, not silence.
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

**No decorative markers.** No coloured dot or square before a label, no `01 / 02` numbering on a
list the reader can count, no `·` joining metadata.

**The test:** if this design would fit three other products, it is wrong. The halftone-as-certainty
system only makes sense for a product whose defining property is uneven data.
