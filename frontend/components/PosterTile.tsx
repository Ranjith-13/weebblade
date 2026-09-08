import Image from "next/image";
import Link from "next/link";
import { displayTitle, type Anime } from "@/lib/types";

/** Roughly 15% of live rows have no poster_url (measured against the real API,
 *  not assumed) - Kitsu simply doesn't have artwork for some titles. A missing
 *  poster gets a typographic tile rather than a broken-image box or a grey
 *  placeholder, so the grid stays intentional-looking rather than damaged. */
function PosterFallback({ title }: { title: string }) {
  return (
    <div className="absolute inset-0 flex items-end bg-raised p-3">
      <span className="font-display text-lg leading-tight text-muted line-clamp-4">
        {title}
      </span>
    </div>
  );
}

export function PosterTile({ anime, priority = false }: { anime: Anime; priority?: boolean }) {
  const title = displayTitle(anime);

  return (
    <Link
      href={`/anime/${anime.source}/${anime.source_id}`}
      className="group block focus:outline-none focus-visible:ring-1 focus-visible:ring-accent"
    >
      {/* Natural poster ratio - 3:4 is what all three sources serve. */}
      <div className="relative aspect-[3/4] overflow-hidden border border-rule">
        {anime.poster_url ? (
          <Image
            src={anime.poster_url}
            alt=""
            fill
            // Matches the responsive grid below (2 cols on phones up to 6 on
            // wide screens) so the browser doesn't download desktop-sized
            // posters onto a phone.
            sizes="(max-width: 640px) 45vw, (max-width: 1024px) 30vw, 16vw"
            className="object-cover"
            priority={priority}
          />
        ) : (
          <PosterFallback title={title} />
        )}
      </div>

      <div className="mt-2.5 flex items-start justify-between gap-3">
        <h3 className="text-[0.82rem] leading-snug line-clamp-2 group-hover:text-accent transition-colors">
          {title}
        </h3>
        {anime.score_100 !== null && (
          <span className="tnum text-[0.82rem] text-muted shrink-0">
            {anime.score_100.toFixed(1)}
          </span>
        )}
      </div>
    </Link>
  );
}

export function PosterGrid({ items }: { items: Anime[] }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-7 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
      {items.map((anime, i) => (
        <PosterTile
          key={`${anime.source}:${anime.source_id}`}
          anime={anime}
          // Only the first row is above the fold; priority-loading the whole
          // grid would compete with itself and slow the LCP it's meant to help.
          priority={i < 6}
        />
      ))}
    </div>
  );
}
