import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { getAnime } from "@/lib/api";
import {
  ApiError,
  displayTitle,
  formatAirDate,
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
    // Metadata must never be the thing that breaks a page - the page's own
    // load() will surface a real error or 404 on its own.
    return { title: "Title" };
  }
}

/* Shell prerenders; the params-dependent body streams inside <Suspense>.
 * Required by Cache Components - reading `params` outside a boundary makes the
 * route unprerenderable and blocks first paint on an upstream round-trip. */
export default function AnimeDetailPage(props: PageProps<"/anime/[source]/[id]">) {
  return (
    <article className="mx-auto max-w-[1400px] px-6 py-12">
      <Link href="/browse" className="label hover:!text-ink transition-colors">
        ← Browse
      </Link>
      <Suspense fallback={<DetailSkeleton />}>
        <AnimeDetail params={props.params} />
      </Suspense>
    </article>
  );
}

function DetailSkeleton() {
  return (
    <div className="mt-8 grid gap-x-14 gap-y-10 md:grid-cols-[minmax(0,16rem)_minmax(0,1fr)]">
      <div className="aspect-[3/4] border border-rule bg-raised" />
      <div className="space-y-4">
        <div className="h-12 w-2/3 bg-raised" />
        <div className="h-4 w-1/3 bg-raised" />
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
  const airDate = formatAirDate(anime);

  // Only facts that actually exist for this row. Kitsu - currently the only
  // live source - has no studios, mal_id or source_material at all, so these
  // are filtered rather than rendered as a wall of em-dashes.
  const facts: Array<[string, string]> = [
    anime.format ? (["Format", anime.format] as [string, string]) : null,
    anime.status ? (["Status", anime.status] as [string, string]) : null,
    anime.episodes !== null ? (["Episodes", String(anime.episodes)] as [string, string]) : null,
    anime.duration_minutes !== null
      ? (["Episode length", `${anime.duration_minutes} min`] as [string, string])
      : null,
    airDate ? (["First aired", airDate] as [string, string]) : null,
    anime.source_material ? (["Source", anime.source_material] as [string, string]) : null,
    anime.studios.length ? (["Studios", anime.studios.join(", ")] as [string, string]) : null,
    anime.favourites !== null
      ? (["Favourites", anime.favourites.toLocaleString()] as [string, string])
      : null,
  ].filter((entry): entry is [string, string] => entry !== null);

  return (
    <div className="mt-8 grid gap-x-14 gap-y-10 md:grid-cols-[minmax(0,16rem)_minmax(0,1fr)]">
        <div>
          <div className="relative aspect-[3/4] border border-rule bg-raised">
            {anime.poster_url ? (
              <Image
                src={anime.poster_url}
                alt=""
                fill
                sizes="(max-width: 768px) 60vw, 16rem"
                className="object-cover"
                priority
              />
            ) : (
              <div className="absolute inset-0 flex items-end p-4">
                <span className="font-display text-2xl leading-tight text-muted">{title}</span>
              </div>
            )}
          </div>

          {anime.score_100 !== null && (
            <div className="mt-5 flex items-baseline justify-between border-t border-rule pt-3">
              <span className="label">Score</span>
              <span className="tnum font-display text-3xl text-accent">
                {anime.score_100.toFixed(1)}
              </span>
            </div>
          )}
        </div>

        <div>
          <h1 className="font-display text-4xl leading-[1.05] md:text-5xl text-balance">{title}</h1>
          {secondary && <p className="mt-3 text-muted">{secondary}</p>}

          {anime.genres.length > 0 && (
            <ul className="mt-6 flex flex-wrap gap-x-3 gap-y-2">
              {anime.genres.map((genre) => (
                <li key={genre}>
                  <Link
                    href={`/browse?genre=${encodeURIComponent(genre)}`}
                    className="label border border-rule px-2 py-1 hover:!text-ink hover:border-muted transition-colors inline-block"
                  >
                    {genre}
                  </Link>
                </li>
              ))}
            </ul>
          )}

          {anime.synopsis && (
            <p className="mt-8 max-w-[68ch] leading-[1.75] text-ink/90">{anime.synopsis}</p>
          )}

          {facts.length > 0 && (
            <dl className="mt-10 border-t border-rule sm:grid sm:grid-cols-2 sm:gap-x-12">
              {facts.map(([term, value]) => (
                <div
                  key={term}
                  className="flex items-baseline justify-between gap-6 border-b border-rule py-2.5"
                >
                  <dt className="label">{term}</dt>
                  <dd className="tnum text-sm text-right">{value}</dd>
                </div>
              ))}
            </dl>
          )}

          <p className="label mt-8">
            Ingested from {anime.source}
            {anime.run_date ? ` · Snapshot ${anime.run_date}` : ""}
          </p>
        </div>
    </div>
  );
}
