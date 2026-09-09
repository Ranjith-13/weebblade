import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { ParallaxPoster } from "@/components/motion/ParallaxPoster";
import { getAnime } from "@/lib/api";
import {
  ApiError,
  displayTitle,
  formatAirDate,
  formatLabel,
  isKnown,
  secondaryTitle,
  type Anime,
} from "@/lib/types";

async function load(source: string, id: string): Promise<Anime> {
  try {
    return await getAnime(source, id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }
}

export async function generateMetadata(props: PageProps<"/anime/[source]/[id]">) {
  const { source, id } = await props.params;
  try {
    const anime = await load(source, id);
    return {
      title: displayTitle(anime),
      description: anime.synopsis?.slice(0, 200) ?? undefined,
    };
  } catch {
    // Metadata must never be the thing that breaks a page — the page's own
    // load() will surface a real error or 404 on its own.
    return { title: "Title" };
  }
}

/* Shell prerenders; the params-dependent body streams inside <Suspense>.
 * Required by Cache Components — reading `params` outside a boundary makes the
 * route unprerenderable and blocks first paint on an upstream round-trip. */
export default function AnimeDetailPage(props: PageProps<"/anime/[source]/[id]">) {
  return (
    <article className="mx-auto max-w-[1340px] px-5 py-9 sm:px-7">
      <Link href="/browse" className="meta inline-block py-2 transition-colors hover:text-flag">
        Back to the season
      </Link>
      <Suspense fallback={<DetailSkeleton />}>
        <AnimeDetail params={props.params} />
      </Suspense>
    </article>
  );
}

function DetailSkeleton() {
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
  params: PageProps<"/anime/[source]/[id]">["params"];
}) {
  const { source, id } = await params;
  const anime = await load(source, id);

  const title = displayTitle(anime);
  const secondary = secondaryTitle(anime);
  const known = isKnown(anime);

  /* Only fields the data actually carries. The previous build rendered
     Studios, Source material and Favourites: the first two are null for 100%
     of live rows (Kitsu provides neither), and favourites ranges 0–25, which
     is noise dressed as a metric. Popularity — present on every single row and
     never previously shown — replaces them, with its direction spelled out
     because a bare "5,909" reads like a score otherwise. */
  const facts: [string, string][] = [
    ["Format", formatLabel(anime.format)],
    ["Status", anime.status === "current" ? "Airing now" : "Finished"],
    anime.episodes ? ["Episodes", String(anime.episodes)] : null,
    anime.duration_minutes ? ["Episode length", `${anime.duration_minutes} min`] : null,
    formatAirDate(anime) ? ["First aired", formatAirDate(anime)!] : null,
    anime.popularity
      ? ["Popularity", `#${Math.round(anime.popularity).toLocaleString()} on Kitsu`]
      : null,
  ].filter(Boolean) as [string, string][];

  return (
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
                {anime.score_100!.toFixed(1)}
              </span>
            </div>
          ) : (
            <p className="text-[0.8rem] leading-relaxed text-ink-soft">
              <span className="meta block mb-1.5">Not scored</span>
              Kitsu has no rating for this title. Nearly three quarters of the season is in
              the same position. It is missing upstream, not withheld here.
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
                  href={`/browse?genre=${encodeURIComponent(genre)}`}
                  className="inline-block border border-rule px-2.5 py-1.5 text-[0.72rem] transition-colors hover:border-ink hover:text-flag"
                >
                  {genre}
                </Link>
              </li>
            ))}
          </ul>
        )}

        {anime.synopsis ? (
          <p className="mt-7 max-w-[64ch] leading-[1.72]">{anime.synopsis}</p>
        ) : (
          <p className="mt-7 text-ink-soft">No synopsis upstream for this title.</p>
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

        <p className="meta mt-6 flex flex-wrap gap-x-5">
          <span>Source: {anime.source}</span>
          {anime.run_date && <span>Snapshot {anime.run_date}</span>}
        </p>
      </div>
    </div>
  );
}
