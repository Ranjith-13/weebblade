import { getSources } from "@/lib/api";
import { joinSources } from "@/lib/types";

/* Where the data on screen came from, stated from the data itself.
 *
 * Both places this replaces were hardcoded and both were wrong: the sitewide
 * footer said "Assembled weekly from Kitsu. AniList and Jikan are down upstream."
 * and the masthead said "1 of 3 sources live" - written when Kitsu was the only
 * live source, and left untouched when MyAnimeList joined and became the sole
 * supplier of studios, source material and broadcast slots. A project whose
 * whole point is reconciling several sources was telling every visitor it used
 * one.
 *
 * It counts three now. Jikan is not a source that is down, it is a source that
 * stopped existing: its public API was discontinued on 1 October 2026. While it
 * was still in ALL_SOURCES the masthead read "3 of 4 sources live", which is the
 * same class of wrong this component was written to end - a number that says
 * something is temporarily missing when nothing is.
 *
 * Async so it reads the catalogue, which is already cached; render it inside a
 * <Suspense> so the surrounding shell stays static under PPR. The fallback names
 * no number, because a wrong number is exactly what this exists to stop.
 */

export const PROVENANCE_FALLBACK = "Assembled weekly from the pipeline's live sources.";

export async function Provenance({ className }: { className?: string }) {
  const { live, configured } = await getSources();

  if (live.length === 0) return <p className={className}>{PROVENANCE_FALLBACK}</p>;

  return (
    <p className={className}>
      Assembled weekly from {joinSources(live)}
      {/* Parenthesised rather than joined with an em-dash, which DESIGN.md
          bans in visible copy. Not a comma either: joinSources() produces a
          comma-separated list, so ", 2 of 3 sources live" reads as one more
          source in it. */}
      {live.length < configured && ` (${live.length} of ${configured} sources live)`}.
    </p>
  );
}

/* The masthead's stacked variant: same fact, no sentence, because it sits in a
 * right-aligned column of short lines rather than in prose. */
export async function ProvenanceLines() {
  const { live, configured } = await getSources();

  if (live.length === 0) return null;

  return (
    <>
      {joinSources(live)}
      <br />
      {live.length} of {configured} sources live
    </>
  );
}
