# WeebBlade — Design Intent

A seasonal anime **trend tracker** built on a real data pipeline (multi-source ingestion → PySpark
→ DuckDB → LLM digest + embedding search). The product story is data journalism, not a streaming
catalogue. Design accordingly.

## Voice

Editorial and analytical — closer to a well-designed sports-statistics site or a music review
publication than to a streaming service. Confident typography carries the page; posters punctuate
it rather than wallpaper it.

## Palette

- Dark-first. Near-black ground `#0B0B0F` — not slate-grey, not navy.
- Foreground `#F2F2F0`, muted `#8A8A92`, hairline rules `#22222A`.
- A single vivid accent `#E23E57`, used sparingly for emphasis and data highlights only. Never as
  large fills, never as a gradient wash.

## Typography

- Strong hierarchy with real scale contrast: oversized editorial headlines set against small,
  tight, uppercase metadata labels with wide letter-spacing. Not three barely-different sizes.
- Tabular/aligned numerals for all figures — scores, episode counts, similarity distances.
- Measured line length (~65–75ch) for any prose, especially the digest.

## Shape and surface

- Sharp corners throughout. No rounded cards, no pill buttons.
- No soft drop shadows, no glassmorphism, no glowing or gradient borders.
- Separation comes from hairline rules and negative space, not from elevated cards.

## Data is content

Scores, episode counts, genre tags and search similarity distances are the substance of this
product, not incidental metadata. Typeset them deliberately and legibly — never bury them in muted
grey small print.

## Layout

- **Poster grid**: dense, tight gutters, posters at their natural 3:4 ratio, title and score set
  beneath in small caps. No hover-scale animations.
- **Weekly AI digest** is the hero of the home page and should read like a magazine column: a clear
  dateline, real paragraph typography, generous measure.
- **Semantic search** results must visibly show similarity ranking — this is embedding-based
  search, and the design should make that legible rather than mimicking a plain keyword search box.
- Generous negative space and clear vertical rhythm. Let sections breathe rather than filling every
  region with a card.

## Explicitly avoid

Generic AI-dashboard aesthetics: rounded-corner card grids on a slate background, purple-to-blue
gradients, glowing borders, emoji used as iconography, a centered hero with a gradient headline,
three-column feature cards with circular icons. If it looks like a default admin template or a
generic SaaS landing page, it is wrong.
