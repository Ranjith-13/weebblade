import Image from "next/image";
import Link from "next/link";
import { getSimilar, seasonLabel } from "@/lib/api";
import { formatLabel, NULL_MARKER, SCORE_MAX, scoreOutOfTen } from "@/lib/types";

/* "More like this", from vectors built for exactly this and nothing else.
 *
 * WHAT IT IS NEAREST BY, because the caption has to be able to say so honestly:
 * genres and synopsis, embedded without any of the title's names. The search
 * index cannot answer this - it leads with every name a title has, which is
 * what makes searching by the other name work and what made the first version
 * of this block match on words. It offered Blue Box Season 2 four other shows
 * whose titles also said "Season 2", one of them Pacific Rim. The reasoning and
 * the measurements are in ai/search/similar.py.
 *
 * NOT POPULARITY, AND NOT A RATING. Nothing here knows what is good or what
 * other people watched next; it knows what the synopses have in common. The
 * caption says that, because a block headed "more like this" otherwise reads as
 * a recommendation engine, and the honest claim is narrower and more
 * interesting: these are the titles this catalogue describes most like the one
 * you are reading.
 *
 * A title's own franchise is absent - the section above lists it in full - and
 * a title with no synopsis gets no block at all rather than a block of
 * strangers. Streams on its own and renders nothing on failure, like the
 * franchise: this is the last thing on the page and must never take it down.
 */
export async function SimilarSection({ wbId }: { wbId: string }) {
  let results;
  try {
    results = await getSimilar(wbId);
  } catch {
    return null;
  }
  if (results.length === 0) return null;

  return (
    <section aria-labelledby="similar-title" className="mt-14 border-t-2 border-ink pt-4">
      <h2 id="similar-title" className="font-display text-2xl font-bold">
        More like this
      </h2>

      <ul className="mt-5 grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 lg:grid-cols-6">
        {results.map((item) => {
          const known = item.score_100 !== null && item.score_100 !== undefined;
          return (
            <li key={item.wb_id}>
              <Link href={`/anime/${item.wb_id}`} className="group block">
                <div
                  className={`relative aspect-[3/4] overflow-hidden border border-ink ${
                    known ? "plate-known" : "plate-unknown"
                  }`}
                >
                  {item.poster_url ? (
                    <Image
                      src={item.poster_url}
                      alt=""
                      fill
                      sizes="(max-width: 640px) 45vw, (max-width: 1024px) 30vw, 15vw"
                      className="object-cover"
                    />
                  ) : (
                    /* The third state: no artwork is a different gap from no
                       score, so it gets its own treatment rather than being
                       folded into the halftone. */
                    <span className="absolute inset-0 flex items-end p-2 font-display text-sm font-bold leading-tight text-ink-soft">
                      {item.title ?? "Untitled"}
                    </span>
                  )}
                  <span
                    className={`tnum absolute right-0 top-0 flex h-7 min-w-7 items-center justify-center px-1.5 ${
                      known
                        ? "bg-flag font-display text-[0.95rem] font-bold text-paper"
                        : "border-b border-l border-ink bg-paper text-[0.8rem] text-ink-soft"
                    }`}
                  >
                    {known ? scoreOutOfTen(item.score_100) : NULL_MARKER}
                    <span className="sr-only">
                      {known ? ` out of ${SCORE_MAX}` : "no score available for this title"}
                    </span>
                  </span>
                </div>
                <h3 className="mt-2 line-clamp-2 text-[0.82rem] font-medium leading-[1.3] transition-colors group-hover:text-flag">
                  {item.title ?? "Untitled"}
                </h3>
                <p className="meta mt-0.5 truncate">
                  {[
                    item.format ? formatLabel(item.format) : null,
                    item.season && item.season_year
                      ? seasonLabel(item.season, item.season_year)
                      : null,
                  ]
                    .filter(Boolean)
                    .join(", ")}
                </p>
              </Link>
            </li>
          );
        })}
      </ul>

      <p className="meta mt-5 max-w-[60ch] !leading-[1.6]">
        Nearest by genre and synopsis, computed when the catalogue was built. Not by popularity,
        rating, or what anyone else watched next. This title&rsquo;s own franchise is listed
        separately above.
      </p>
    </section>
  );
}
