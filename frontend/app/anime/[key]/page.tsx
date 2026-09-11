import Image from "next/image";
import Link from "next/link";
import { notFound, permanentRedirect, unstable_rethrow } from "next/navigation";
import { Suspense } from "react";
import { FranchiseSection } from "@/components/Franchise";
import { ParallaxPoster } from "@/components/motion/ParallaxPoster";
import { NextAiring } from "@/components/NextAiring";
import { Trailer } from "@/components/Trailer";
import { getSeasons, getTitle, seasonKey } from "@/lib/api";
import {
  ageRatingLabel,
  displayTitle,
  FORMAT_ALL,
  formatAirDate,
  formatLabel,
  isKnown,
  isTv,
  broadcastSlotLabel,
  secondaryTitle,
  sourceMaterialLabel,
  SCORE_MAX,
  scoreOutOfTen,
  sourceLinks,
  streamingLinks,
  WB_ID,
  type Anime,
} from "@/lib/types";

/* A title page lives at /anime/{wb_id}, the title's stable identity - see
 * titleHref() in lib/types.ts. The old /anime/{source}/{source_id} addresses are
 * turned into these by proxy.ts before any page renders.
 *
 * A key that is not shaped like an identity is a 404 without asking the API:
 * nothing else lives at this depth, and a request per stray URL would spend the
 * shared rate limit on junk. */
async function load(key: string): Promise<Anime> {
  if (!WB_ID.test(key)) notFound();
  const anime = await getTitle(key);
  if (!anime) notFound();
  return anime;
}

export async function generateMetadata(props: PageProps<"/anime/[key]">) {
  const { key } = await props.params;
  try {
    const anime = await load(key);
    return {
      title: displayTitle(anime),
      description: anime.synopsis?.slice(0, 200) ?? undefined,
      // An identity that merged into another still answers here, with the
      // surviving title; the canonical address is the survivor's.
      alternates: anime.wb_id ? { canonical: `/anime/${anime.wb_id}` } : undefined,
    };
  } catch (err) {
    // A missing title is Next's own not-found signal, not a failure: let it
    // through, so the 404 carries its noindex. Swallowing it here served every
    // unknown identity as an indexable page titled "Title".
    unstable_rethrow(err);
    // Anything else must not be the thing that breaks a page — the page's own
    // load() will surface a real error on its own.
    return { title: "Title" };
  }
}

/* Shell prerenders; the params-dependent body streams inside <Suspense>.
 * Required by Cache Components — reading `params` outside a boundary makes the
 * route unprerenderable and blocks first paint on an upstream round-trip. */
export default function AnimeDetailPage(props: PageProps<"/anime/[key]">) {
  return (
    <article className="mx-auto max-w-[1340px] px-5 py-9 sm:px-7">
      <Suspense fallback={<DetailSkeleton />}>
        <AnimeDetail params={props.params} />
      </Suspense>
    </article>
  );
}

const BACK_LINK = "meta inline-block py-2 transition-colors hover:text-flag";

function DetailSkeleton() {
  return (
    <>
      {/* A working link while the title loads, the same size as the season-named
          one that replaces it. */}
      <Link href="/browse" className={BACK_LINK}>
        Back to the season
      </Link>
      <DetailBodySkeleton />
    </>
  );
}

function DetailBodySkeleton() {
  return (
    <div className="mt-7 grid gap-x-12 gap-y-8 md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)]">
      <div className="plate-empty aspect-[3/4] border border-rule bg-plate" />
      <div className="space-y-4">
        <div className="h-12 w-2/3 bg-plate" />
        <div className="h-4 w-1/3 bg-plate" />
        <div className="h-24 w-full bg-plate" />
      </div>
    </div>
  );
}

async function AnimeDetail({
  params,
}: {
  params: PageProps<"/anime/[key]">["params"];
}) {
  const { key } = await params;
  const [anime, seasons] = await Promise.all([load(key), getSeasons()]);

  /* An identity can merge into another when a later fetch shows two records to
     be one show - four did on 2026-09-11, when Kitsu's missing pages came in.
     Their addresses keep working and land on the survivor's. This redirects
     inside the streamed page, so it is a client-side redirect rather than a
     308; merges are too rare to justify an API call in the proxy on every title
     view to catch them earlier. */
  if (anime.wb_id && anime.wb_id !== key) permanentRedirect(`/anime/${anime.wb_id}`);

  const title = displayTitle(anime);
  const secondary = secondaryTitle(anime);
  const known = isKnown(anime);

  /* Every link out of this page stays in the title's own season. They used to
     drop it, and /browse without a season is the newest one - so on any title
     from an earlier season, clicking a genre opened a different season filtered
     by that genre. Iyashikei from Laid-Back Camp 3 (Spring 2024) returned zero
     results. A season /browse does not offer (fewer than ten titles) is left
     out rather than linked to the wrong one. */
  const filed = seasons.find(
    (s) => anime.season && anime.season_year && s.key === seasonKey(anime.season, anime.season_year),
  );
  /* A title that is not TV would be hidden by the browse default, so a link from
     it asks for every format, and the title can see itself in what it opens. */
  const inSeason = (filter: Record<string, string>) => {
    const qs = new URLSearchParams({
      ...(filed ? { season: filed.key } : {}),
      ...(isTv(anime) ? {} : { format: FORMAT_ALL }),
      ...filter,
    });
    return `/browse?${qs}`;
  };
  /* The padding makes a 27px target of a 15px line, and the equal negative margin
     takes it back out of the layout, so a linked row is exactly as tall as the
     plain ones around it. Each sits alone in a 40px row, so nothing overlaps.
     min-w-6 covers the short values - "TV" is 17px wide - and text-right keeps
     them flush with the column like every other value. */
  const linkClass =
    "-my-1.5 inline-block min-w-6 py-1.5 text-right underline decoration-rule underline-offset-4 transition-colors hover:text-flag";

  /* Only fields the data actually carries, which is now a different set than
     it was. Studios and Source material were removed when they were null for
     100% of rows, because Kitsu provides neither; MAL does, so they are back and
     lead, being the most concretely useful things here. Favourites stays out:
     it ranges 0-25 and is noise dressed as a metric. */
  const facts: [string, React.ReactNode][] = [
    /* The studios are links, and this is the only way into a studio filter.
       /browse has no studio chip row on purpose: 135 distinct studios across 227
       titles, only two with four or more, so a row would be either 28 chips deep
       or useless, and would leave most studios unreachable either way. "What
       else did they make" is the question people actually arrive with, and from
       here it works for all 135.

       format=all because the question is everything they made, and the browse
       default would silently hide their films and ONAs. */
    anime.studios.length > 0
      ? [
          "Studio",
          anime.studios.map((studio, i) => (
            <span key={studio}>
              {i > 0 && ", "}
              <Link
                href={`/browse?studio=${encodeURIComponent(studio)}&format=${FORMAT_ALL}`}
                className={linkClass}
              >
                {studio}
              </Link>
            </span>
          )),
        ]
      : null,
    filed
      ? [
          "Season",
          <Link key="season" href={`/browse?season=${filed.key}`} className={linkClass}>
            {filed.label}
          </Link>,
        ]
      : null,
    sourceMaterialLabel(anime.source_material)
      ? [
          "Adapted from",
          <Link
            key="material"
            href={inSeason({ material: anime.source_material! })}
            className={linkClass}
          >
            {sourceMaterialLabel(anime.source_material)}
          </Link>,
        ]
      : null,
    [
      "Format",
      anime.format ? (
        <Link
          key="format"
          href={inSeason({ format: anime.format })}
          className={linkClass}
        >
          {formatLabel(anime.format)}
        </Link>
      ) : (
        formatLabel(anime.format)
      ),
    ],
    ["Status", anime.status === "current" ? "Airing now" : "Finished"],
    anime.episodes ? ["Episodes", String(anime.episodes)] : null,
    anime.duration_minutes ? ["Episode length", `${anime.duration_minutes} min`] : null,
    formatAirDate(anime) ? ["First aired", formatAirDate(anime)!] : null,
    ageRatingLabel(anime.age_rating)
      ? ["Rating", ageRatingLabel(anime.age_rating)!]
      : null,
    // userCount is the one interest figure present for essentially the whole
    // season, so it leads. popularity and rating_rank are RANKS (lower is
    // better) and are labelled as such so nobody reads 11,491 as a score.
    anime.user_count
      ? ["Tracked by", `${anime.user_count.toLocaleString()} people`]
      : null,
    anime.popularity
      ? ["Popularity rank", `#${Math.round(anime.popularity).toLocaleString()}`]
      : null,
    anime.rating_rank ? ["Rating rank", `#${anime.rating_rank.toLocaleString()}`] : null,
  ].filter(Boolean) as [string, React.ReactNode][];

  const watch = streamingLinks(anime);
  const links = sourceLinks(anime);
  const slot = broadcastSlotLabel(anime.broadcast_day, anime.broadcast_time);

  return (
    <>
      <Link href={filed ? `/browse?season=${filed.key}` : "/browse"} className={BACK_LINK}>
        {filed ? `Back to ${filed.label}` : "Back to the season"}
      </Link>

      {/* Cover art exists for only ~17% of the season, so this is an enhancement
          and never a layout assumption: when it is absent the page simply starts
          at the poster, with nothing reserved and nothing to shift. It carries
          the same certainty treatment as the plates so a screened-back banner
          still reads as "no score" rather than as a different design. */}
      {anime.cover_url && (
        <div
          className={[
            "relative mt-7 aspect-[3/1] w-full overflow-hidden border border-ink",
            known ? "plate-known" : "plate-unknown",
          ].join(" ")}
        >
          <Image
            src={anime.cover_url}
            alt=""
            fill
            sizes="(max-width: 1340px) 100vw, 1340px"
            className="object-cover"
            priority
          />
        </div>
      )}

    <div className="mt-7 grid gap-x-12 gap-y-9 md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)]">
      <div>
        <ParallaxPoster
          className={[
            "relative aspect-[3/4] overflow-hidden border border-ink",
            known ? "plate-known" : "plate-unknown",
            anime.poster_url ? "" : "plate-empty bg-plate",
          ].join(" ")}
        >
          {anime.poster_url ? (
            <Image
              src={anime.poster_url}
              alt=""
              fill
              sizes="(max-width: 768px) 90vw, 15rem"
              className="object-cover"
              priority
            />
          ) : (
            <span className="absolute inset-0 flex items-end p-4 font-display text-xl font-bold leading-tight text-ink-soft">
              {title}
            </span>
          )}
        </ParallaxPoster>

        {/* The score, or an honest statement that there isn't one. An absent
            score is a fact about the pipeline, not a blank to skip past. */}
        <div className="mt-4 border-t-2 border-ink pt-3">
          {known ? (
            <div className="flex items-baseline justify-between gap-3">
              <span className="stamp">Score</span>
              <span className="tnum font-display text-[2.4rem] font-black leading-none text-flag">
                {scoreOutOfTen(anime.score_100)}
                <span className="text-[1.1rem] font-bold text-ink-soft"> / {SCORE_MAX}</span>
              </span>
            </div>
          ) : (
            <p className="text-[0.8rem] leading-relaxed text-ink-soft">
              <span className="meta block mb-1.5">Not scored</span>
              No source rates this title yet. Rather more than half the season is in the
              same position. It is missing upstream, not withheld here.
            </p>
          )}
        </div>
      </div>

      <div>
        <h1 className="font-display text-[clamp(1.9rem,5vw,3.1rem)] font-black leading-[0.95] text-balance">
          {title}
        </h1>
        {secondary && <p className="mt-2.5 text-ink-soft">{secondary}</p>}

        {anime.genres.length > 0 && (
          <ul className="mt-5 flex flex-wrap gap-2">
            {anime.genres.map((genre) => (
              <li key={genre}>
                <Link
                  href={inSeason({ genre })}
                  className="inline-block border border-rule px-2.5 py-1.5 text-[0.72rem] transition-colors hover:border-ink hover:text-flag"
                >
                  {genre}
                </Link>
              </li>
            ))}
          </ul>
        )}

        {/* The most actionable thing on the page, so it sits above the synopsis.
            About 59% of the season carries at least one link; the rest say so
            plainly rather than leaving a silent gap where a control should be. */}
        <div className="mt-7 border-t border-rule pt-5">
          <h2 className="stamp mb-3">Where to watch</h2>
          {watch.length > 0 ? (
            <ul className="flex flex-wrap gap-2">
              {watch.map(({ service, url }) => (
                <li key={url}>
                  <a
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-block border border-ink px-3 py-1.5 text-[0.8rem] font-medium transition-colors hover:bg-flag hover:text-paper"
                  >
                    {service}
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            /* Named Kitsu until MAL joined. Kitsu is still the only source that
               carries streaming links, but on a MAL-only title Kitsu has no
               record at all, so blaming it by name was misleading in exactly the
               case where the message shows most often. */
            <p className="text-[0.85rem] text-ink-soft">
              No source lists a streaming link for this title.
            </p>
          )}
        </div>

        {anime.synopsis ? (
          <p className="mt-7 max-w-[64ch] leading-[1.72]">{anime.synopsis}</p>
        ) : (
          <p className="mt-7 text-ink-soft">No synopsis upstream for this title.</p>
        )}

        {anime.trailer_id && (
          <div className="mt-7 max-w-[34rem]">
            <Trailer videoId={anime.trailer_id} title={title} />
          </div>
        )}

        <dl className="mt-9 border-t-2 border-ink sm:grid sm:grid-cols-2 sm:gap-x-12">
          {facts.map(([term, value]) => (
            <div
              key={term}
              className="flex items-baseline justify-between gap-6 border-b border-rule py-2.5"
            >
              <dt className="stamp">{term}</dt>
              <dd className="tnum text-[0.85rem]">{value}</dd>
            </div>
          ))}
        </dl>

        {slot && (
          <div className="mt-5 border-l-2 border-data pl-4">
            <p className="text-[0.9rem]">
              Airs <span className="font-semibold">{slot}</span>
            </p>
            {/* One line of space is reserved because NextAiring is client-only
                and renders nothing during SSR. Without the reservation the
                caveat below jumps down a line the moment it fills in, which is
                exactly the layout shift the rest of the page avoids. 1.5em is
                one .meta line: 0.75rem at line-height 1.5. */}
            <p className="meta mt-1 min-h-[1.5em]">
              <NextAiring
                broadcastDay={anime.broadcast_day}
                broadcastTime={anime.broadcast_time}
              />
            </p>
            {/* Stated plainly rather than tucked into a tooltip: MAL has no
                next-episode date, so this is the regular weekly slot projected
                forward. A broadcast that slips will not show up here. */}
            <p className="meta mt-1 max-w-[46ch] !leading-[1.6]">
              This is the regular broadcast slot, not a confirmed airdate
            </p>
          </div>
        )}

        <p className="meta mt-6 flex flex-wrap items-baseline gap-x-5 gap-y-1">
          {links.length > 0 ? (
            links.map((link) => (
              <a
                key={link.href}
                href={link.href}
                target="_blank"
                rel="noreferrer"
                className="inline-block py-1 underline decoration-rule underline-offset-4 transition-colors hover:text-flag"
              >
                {link.label}
              </a>
            ))
          ) : (
            <span>Source: {anime.source}</span>
          )}
          {anime.run_date && <span>Snapshot {anime.run_date}</span>}
        </p>
      </div>
    </div>

    {/* Streams after the title itself: the franchise is a second request, and
        the page is complete without it. */}
    {anime.wb_id && (
      <Suspense fallback={null}>
        <FranchiseSection wbId={anime.wb_id} />
      </Suspense>
    )}
    </>
  );
}
