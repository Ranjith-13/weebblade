import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { ImageResponse } from "next/og";

import { getTitle } from "@/lib/api";
import { displayTitle, isKnown, scoreOutOfTen, SCORE_MAX, secondaryTitle } from "@/lib/types";

/* The card a shared title link unfurls into.
 *
 * Every title page used to send the site's own card - "WeebBlade: a seasonal
 * anime almanac", the same picture and the same sentence whichever title you
 * posted - so a link to a specific show said nothing about that show. This
 * renders the title instead: its artwork, its name, and whether the pipeline
 * has a score for it.
 *
 * WHY IT LOOKS LIKE THE SITE AND NOT LIKE A CARD TEMPLATE. The one idea the
 * design runs on is that colour is the reward for known data (DESIGN.md §2): a
 * scored title prints in full colour with a flag-pink score, an unscored one
 * carries the em-dash null marker instead. A card that showed every title the
 * same way would be the "uniform grid where every item carries equal weight"
 * the design explicitly rejects - in the one place strangers see it first.
 *
 * Satori renders this, not a browser, so: flexbox only, no grid, no CSS
 * variables, no stylesheet. Hence the palette being read out of globals.css
 * below rather than typed here, and every container that holds more than one
 * child carrying an explicit display: flex.
 */

export const alt = "A WeebBlade title card: the show's artwork, name and score";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const bodoni = await readFile(join(process.cwd(), "assets/BodoniModa-Black.ttf"));
const archivo = await readFile(join(process.cwd(), "assets/Archivo-Medium.ttf"));

/* DESIGN.md: "app/globals.css is the single source of truth for every colour.
 * There is no literal hex anywhere in app/, components/ or lib/; keep it that
 * way." Satori cannot read a stylesheet, so the values have to reach it as
 * strings - but they are read FROM globals.css rather than copied out of it,
 * so the rule still holds and the card cannot drift from the site. A renamed
 * or deleted token fails the build here, loudly, instead of rendering a card in
 * some colour nobody chose. */
const TOKENS = ["paper", "plate", "rule", "ink", "ink-soft", "flag"] as const;

const css = await readFile(join(process.cwd(), "app/globals.css"), "utf8");
const palette = Object.fromEntries(
  TOKENS.map((token) => {
    const found = css.match(new RegExp(`--color-${token}:\\s*(#[0-9a-fA-F]{3,8})`));
    if (!found) {
      throw new Error(
        `opengraph-image: no --color-${token} in app/globals.css. The card reads its ` +
          `palette from there so it cannot drift from the site; if the token was renamed, ` +
          `rename it here too.`,
      );
    }
    return [token, found[1]];
  }),
) as Record<(typeof TOKENS)[number], string>;

/* Satori has no line clamp, so a long title is cut here instead of overflowing
 * the card. Generous: the longest in the catalogue run past 70 characters
 * ("Life With an Ordinary Guy Who Reincarnated Into a Total Fantasy Knockout"),
 * and a card that ends mid-word is better than one that ends mid-layout. */
function clamp(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, limit - 1).trimEnd()}…`;
}

/* Fetched at request time, never bundled: a cover is 100-200 KB and the
 * ImageResponse budget is 500 KB for everything including the fonts.
 *
 * Returns null on anything going wrong, and that is not defensive padding -
 * six of the catalogue's poster URLs are already 404 at Kitsu, confirmed at the
 * origin. The card has a composed state without artwork, so a dead poster costs
 * the picture rather than the card. */
async function poster(url: string | null): Promise<string | null> {
  if (!url) return null;
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(4000) });
    if (!res.ok) return null;
    const type = res.headers.get("content-type") ?? "image/jpeg";
    const body = Buffer.from(await res.arrayBuffer());
    return `data:${type};base64,${body.toString("base64")}`;
  } catch {
    return null;
  }
}

export default async function Image({ params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  const anime = await getTitle(key);

  /* A key that resolves to nothing still has to answer with an image: the
   * alternative is a broken-image icon in somebody's timeline. */
  if (!anime) {
    return new ImageResponse(
      (
        <div
          style={{
            width: "100%",
            height: "100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: palette.paper,
            color: palette.ink,
            fontFamily: "Bodoni Moda",
            fontSize: 84,
          }}
        >
          WeebBlade
        </div>
      ),
      { ...size, fonts: [{ name: "Bodoni Moda", data: bodoni, weight: 900, style: "normal" }] },
    );
  }

  const known = isKnown(anime);
  const score = scoreOutOfTen(anime.score_100);
  const art = await poster(anime.poster_url);
  const secondary = secondaryTitle(anime);

  const facts = [
    anime.format,
    anime.season && anime.season_year
      ? `${anime.season.charAt(0)}${anime.season.slice(1).toLowerCase()} ${anime.season_year}`
      : null,
    anime.episodes ? `${anime.episodes} ${anime.episodes === 1 ? "ep" : "eps"}` : null,
    (anime.studios ?? [])[0] ?? null,
  ].filter(Boolean) as string[];

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          background: palette.paper,
          color: palette.ink,
          fontFamily: "Archivo",
        }}
      >
        {/* Artwork, where there is any. Separation is a hairline rule, never a
            shadow - the design has no shadows anywhere. */}
        {art && (
          <img
            src={art}
            alt=""
            width={394}
            height={630}
            style={{ width: 394, height: 630, objectFit: "cover", borderRight: `2px solid ${palette.ink}` }}
          />
        )}

        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            padding: "52px 56px",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div
              style={{
                display: "flex",
                fontFamily: "Bodoni Moda",
                fontSize: 30,
                letterSpacing: "0.01em",
                borderBottom: `2px solid ${palette.ink}`,
                paddingBottom: 14,
              }}
            >
              WeebBlade
            </div>

            <div
              style={{
                display: "flex",
                fontFamily: "Bodoni Moda",
                fontSize: secondary ? 62 : 70,
                lineHeight: 1.04,
                marginTop: 34,
              }}
            >
              {clamp(displayTitle(anime), 72)}
            </div>

            {secondary && (
              <div style={{ display: "flex", fontSize: 25, color: palette["ink-soft"], marginTop: 16 }}>
                {clamp(secondary, 64)}
              </div>
            )}
          </div>

          <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between" }}>
            <div style={{ display: "flex", flexDirection: "column", maxWidth: 440 }}>
              {/* Spacing, not separators. DESIGN.md bans "·-joined metadata" by
                  name, and the first version of this card did exactly that -
                  the rule exists because a dot between every fact is the
                  decoration every template reaches for, and the site itself
                  separates with a gap and nothing else. */}
              <div style={{ display: "flex", gap: 26, fontSize: 21, color: palette["ink-soft"], letterSpacing: "0.04em" }}>
                {facts.map((fact) => (
                  <span key={fact} style={{ display: "flex" }}>
                    {fact}
                  </span>
                ))}
              </div>
            </div>

            {/* The whole idea, in the corner: a score the pipeline has prints
                in the signal colour; one it does not gets the em-dash that
                means "no value" in a table, which is the single carve-out
                DESIGN.md allows for that character. Not an invented "N/A", and
                not a zero. */}
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
              <div style={{ display: "flex", fontSize: 17, color: palette["ink-soft"], letterSpacing: "0.1em" }}>
                {known ? "SCORE" : "NO SCORE UPSTREAM"}
              </div>
              <div
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  fontFamily: "Bodoni Moda",
                  fontSize: 78,
                  marginTop: 6,
                  /* ink-soft, not rule. At 78px a Bodoni em-dash is one hairline,
                     and in the rule colour it read as a rendering artefact rather
                     than as the deliberate "no value" mark it is. Screened back
                     from the flag pink, still legible as a decision. */
                  color: known ? palette.flag : palette["ink-soft"],
                }}
              >
                {known ? score : "—"}
                {known && (
                  <span style={{ fontFamily: "Archivo", fontSize: 24, color: palette["ink-soft"], marginLeft: 8 }}>
                    / {SCORE_MAX}
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    ),
    {
      ...size,
      fonts: [
        { name: "Bodoni Moda", data: bodoni, weight: 900, style: "normal" },
        { name: "Archivo", data: archivo, weight: 500, style: "normal" },
      ],
    },
  );
}
