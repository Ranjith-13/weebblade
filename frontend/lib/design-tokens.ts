/* Programmatic handles for the design tokens.
 *
 * The VALUES live in exactly one place — the `@theme` block in app/globals.css.
 * This module deliberately exports only the variable *names* and the composed
 * patterns built from them, so there is no second copy of a hex code anywhere in
 * the codebase to drift out of sync. If you need a colour in TSX, use a Tailwind
 * utility (`text-flag`, `bg-plate`); reach for this only where an inline style
 * is genuinely unavoidable, such as a generated background-image. */

export const token = {
  paper: "var(--color-paper)",
  plate: "var(--color-plate)",
  rule: "var(--color-rule)",
  ink: "var(--color-ink)",
  inkSoft: "var(--color-ink-soft)",
  flag: "var(--color-flag)",
  data: "var(--color-data)",
} as const;

/** The halftone screen, as used by `.plate-unknown` and by the legend swatch
 *  that explains it. Same geometry in both places, from one definition. */
export const halftone = {
  backgroundImage: `radial-gradient(${token.ink} 1.1px, transparent 1.2px)`,
  backgroundSize: "4px 4px",
} as const;

/** Contrast ratios measured against `--color-paper` (#E9E7E0). Kept here as a
 *  record of why these values and not the first draft's: #FF2E88 scored 2.83,
 *  which fails even large-text AA, and #6E6E75 scored 4.09, which fails body.
 *  If you change a colour, re-measure — do not eyeball it. */
export const CONTRAST_ON_PAPER = {
  ink: 14.71,
  inkSoft: 5.19,
  flag: 4.91,
  data: 6.76,
} as const;
