# Fonts for the social cards

`ImageResponse` renders with Satori, which has no stylesheet and no `next/font`:
every glyph it draws has to be handed to it as font data. It accepts `ttf`,
`otf` and `woff` only - the `woff2` that `next/font` caches is no use here - so
these two static instances of the site's own faces live in the repository.

| File | Face | Size |
|---|---|---|
| `BodoniModa-Black.ttf` | Bodoni Moda 900, the display face | 43.8 KB |
| `Archivo-Medium.ttf` | Archivo 500, the text face | 109.5 KB |

153 KB of the 500 KB `ImageResponse` bundle, which also counts the JSX, the CSS
and any bundled image. Measured before any of this was written, because whether
Bodoni fits at all decided whether the cards were possible.

Both are SIL Open Font License 1.1, which permits redistribution:
<https://fonts.google.com/specimen/Bodoni+Moda> · <https://fonts.google.com/specimen/Archivo>

Posters are fetched at request time instead of bundled, which is what keeps the
bundle at 153 KB however large a cover image happens to be.
