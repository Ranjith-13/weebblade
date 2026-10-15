import Image from "next/image";
import Link from "next/link";
import {
  dayKeyLabel,
  displayTitle,
  formatLabel,
  isAiring,
  isKnown,
  jstDayKey,
  NULL_MARKER,
  SCORE_MAX,
  scoreOutOfTen,
  titleHref,
  type Anime,
} from "@/lib/types";

/* A "plate" in the printing sense. This component is where the design's one
 * idea lives, so it is worth stating plainly:
 *
 *   score present  -> full-colour artwork, flag-pink score tab   ("known")
 *   score absent   -> greyscale + halftone screen, em-dash tab   ("unknown")
 *   artwork absent -> diagonal rule fill with the title set large
 *
 * Nearly three quarters of the season has no score, so this is not an edge case being
 * styled — it is the majority state, and the page should look composed when
 * most of it is unknown. Note the third case is INDEPENDENT of the first: a
 * title can be scored and have no artwork (68.6 with a blank plate), and the
 * design says both things at once instead of collapsing them into one
 * "incomplete" look. */

export function Plate({
  anime,
  priority = false,
  week,
}: {
  anime: Anime;
  priority?: boolean;
  /** This week's episode for this title, where the schedule has one. */
  week?: { episode: number | null; airing_at: string };
}) {
  const title = displayTitle(anime);
  const known = isKnown(anime);
  const airing = isAiring(anime);
  const episode = week?.episode != null ? week : null;

  return (
    <Link
      href={titleHref(anime)}
      className="group block focus:outline-none"
    >
      <div
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
            sizes="(max-width: 640px) 46vw, (max-width: 1024px) 30vw, 15vw"
            className="object-cover"
            priority={priority}
          />
        ) : (
          <span className="absolute inset-0 flex items-end p-2.5 font-display text-[0.95rem] font-bold leading-[1.1] text-ink-soft">
            {title}
          </span>
        )}

        {/* The tab is the read-at-a-glance signal. Paper-on-flag is 4.91:1, so
            it stays legible rather than relying on the artwork behind it. */}
        <span
          className={[
            "absolute left-0 top-0 z-10 px-1.5 py-1 leading-none tnum",
            known
              ? "bg-flag font-display text-[0.95rem] font-bold text-paper"
              : "border-b border-r border-ink bg-paper text-[0.8rem] text-ink-soft",
          ].join(" ")}
        >
          {known ? scoreOutOfTen(anime.score_100) : NULL_MARKER}
          <span className="sr-only">
            {known ? ` out of ${SCORE_MAX}` : "no score available for this title"}
          </span>
        </span>
      </div>

      <div className="mt-2">
        <h3 className="line-clamp-2 text-[0.78rem] font-medium leading-[1.3] transition-colors duration-150 group-hover:text-flag group-focus-visible:text-flag">
          {title}
        </h3>
        {/* Separation by weight and colour, not by a middot.
            "Airing" is a true word that answers nothing a reader scanning a
            season actually wants. Where the week's schedule knows which episode
            lands and when, it says that instead - same slot, same line, so a
            grid of a hundred plates keeps its rhythm and nothing shifts.
            The date is Japan's, labelled, exactly as the schedule's own columns
            are: a bare weekday would be read as the reader's, and these
            broadcast late enough at night in Tokyo to be the previous evening
            across the Americas. */}
        <p className="meta mt-1 flex flex-wrap items-baseline gap-x-2">
          {episode ? (
            <>
              <span className="font-bold text-data">Ep {episode.episode}</span>
              <span>
                {dayKeyLabel(jstDayKey(episode.airing_at)).date} JST
                <span className="sr-only">
                  , episode {episode.episode} airs that day in Japan
                </span>
              </span>
            </>
          ) : (
            airing && <span className="font-bold text-data">Airing</span>
          )}
          <span>{formatLabel(anime.format)}</span>
        </p>
      </div>
    </Link>
  );
}

export function PlateGrid({
  items,
  /** Column tracks above `sm`. Overridable because the home page runs this grid
   *  alongside a 15rem pinned key, where six columns would crush each plate. */
  columns = "lg:grid-cols-5 xl:grid-cols-6",
  week,
}: {
  items: Anime[];
  columns?: string;
  /** This week's episodes by wb_id; see getWeekEpisodes. Absent is fine - the
   *  plates fall back to the word they carried before. */
  week?: Record<string, { episode: number | null; airing_at: string }>;
}) {
  return (
    <div className={`grid grid-cols-2 gap-x-4 gap-y-7 sm:grid-cols-3 ${columns}`}>
      {items.map((anime, i) => (
        <Plate
          key={`${anime.source}:${anime.source_id}`}
          anime={anime}
          // Only the first row is above the fold; priority-loading the whole
          // grid makes it compete with itself and slows the LCP it should help.
          priority={i < 6}
          week={anime.wb_id ? week?.[anime.wb_id] : undefined}
        />
      ))}
    </div>
  );
}

/** Loading shape for the grid. Matches the real plate's aspect and border so
 *  nothing shifts when content arrives. */
export function PlateGridSkeleton({ count = 12 }: { count?: number }) {
  return (
    <div
      data-skeleton
      className="grid grid-cols-2 gap-x-4 gap-y-7 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6"
    >
      {Array.from({ length: count }).map((_, i) => (
        <div key={i}>
          <div className="plate-empty aspect-[3/4] border border-rule bg-plate" />
          <div className="mt-2 h-3 w-4/5 bg-plate" />
          <div className="mt-1.5 h-2 w-2/5 bg-plate" />
        </div>
      ))}
    </div>
  );
}
