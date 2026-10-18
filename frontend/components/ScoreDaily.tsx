import { getDailyScores } from "@/lib/api";
import {
  calendarDate,
  compactCount,
  realMoves,
  scoreOutOfTen,
  sourceLabel,
  VOTES_WORTH_CALLING_A_MOVE,
} from "@/lib/types";

/* Whose readings these are. The daily check asks AniList and only AniList
 * (ingestion/anilist/fetch_status.py), so this is a fact about the pipeline
 * rather than a column to carry through the API. */
const ASKED = "anilist";

/* What a week did to this title's score, asked every morning.
 *
 * THE DENSE HALF OF /scores, AND THE ONE THING HERE NOBODY ELSE PRINTS. Three
 * other sites show a rating. None of them shows what it was yesterday, because
 * that needs somebody to have asked every morning and kept the answers - which
 * the daily AniList status check has been doing for exactly the titles the
 * catalogue calls airing. The readings were being written and nothing read them.
 *
 * It is NOT a second score history. score_history in the rail above is weekly
 * and runs the length of the catalogue; a score that moves on Tuesday and back
 * on Friday is invisible there and is two readings here.
 *
 * THE UNIT IS A RE-ASK, not a day. The check writes a row every morning whether
 * or not anything moved, so a pair of readings counts only where the vote count
 * moved - the same rule as /scores, for the reason set out above
 * backend/app/routers/scores._REASKS. "Asked five times" would be a statement
 * about the pipeline's schedule.
 *
 * AND A PRINTED MOVE IS MOSTLY ARITHMETIC, which is the trap this block had to
 * be designed around. A score stored out of 100 and shown out of 10 flips on
 * the single vote that crosses .05: of the nine printed moves in the first day
 * of readings, one rode 521 new votes and one rode two. Printing those the same
 * way would report rounding as news, which is precisely what /scores exists to
 * avoid doing with snapshots. So a move is only called a move above
 * VOTES_WORTH_CALLING_A_MOVE new votes, and the weight is printed beside it.
 *
 * NOTHING IS SHOWN WHERE THERE IS NOTHING TO SAY. One reading is not an
 * observation of movement, a finished title is never asked about, and a
 * warehouse published before the score columns existed has no readings at all.
 * All three render nothing rather than a flat line - the same rule /scores
 * follows for a season nobody re-asked.
 */
export async function ScoreDailySection({ wbId }: { wbId: string }) {
  let daily;
  try {
    daily = await getDailyScores(wbId);
  } catch {
    return null;
  }
  // Under two readings there is no pair, and with no re-ask every pair was a
  // copy: either way the honest answer is silence, not a line at one point.
  if (!daily || daily.points.length < 2 || daily.reasks === 0) return null;

  const since = calendarDate(daily.points[0].fetched_on);
  const moves = realMoves(daily);
  const rounding = daily.moves.length - moves.length;
  const votes = compactCount(daily.votes_gained);

  return (
    <div className="mt-5 border-l-2 border-flag pl-4">
      <p className="text-[0.9rem] !leading-[1.5]">
        {/* NAMED, AND THAT IS CORRECTNESS RATHER THAN COURTESY - the same rule
            the revisions line in the rail follows. The score above this block
            is the merged winner of three sources and these readings are one
            source's, so they legitimately differ: on the title this was built
            against the rail printed 7.5 from MyAnimeList while these said 6.9.
            Unattributed, that is the site contradicting itself on one screen. */}
        <span className="font-semibold">{sourceLabel(ASKED)}</span>, asked every morning
        since {since}
        {votes ? (
          <>
            : <span className="tnum font-semibold">{votes}</span> more votes
          </>
        ) : null}
        {moves.length > 0 ? (
          <>
            , and the score moved{" "}
            <span className="tnum font-semibold">
              {scoreOutOfTen(moves[0].was)} to {scoreOutOfTen(moves[moves.length - 1].now)}
            </span>
          </>
        ) : (
          <>, and its score has not moved</>
        )}
      </p>

      {moves.length > 0 && (
        <ol className="mt-2">
          {moves.map((m) => (
            <li key={m.on} className="flex gap-3 border-t border-rule py-1 text-[0.8rem]">
              <span className="tnum w-[7.5rem] shrink-0 text-ink-soft">{calendarDate(m.on)}</span>
              <span className="tnum font-semibold">
                {scoreOutOfTen(m.was)} to {scoreOutOfTen(m.now)}
              </span>
              {/* The weight behind the move, never the move alone. */}
              <span className="meta ml-auto self-center">
                on {compactCount(m.votes_gained)} new votes
              </span>
            </li>
          ))}
        </ol>
      )}

      <p className="meta mt-1 max-w-[46ch] !leading-[1.6]">
        {/* Says what the figure counts, in the page rather than in a tooltip:
            a reader who cannot see why five mornings produced three readings
            will read the difference as an error. */}
        {/* Mornings rather than pairs. "1 of 1 readings" is what counting the
            comparisons printed, which is both awkward and wrong-sounding: a
            reading is a point and a re-ask is the gap between two, and the
            first morning has nothing behind it to have moved from. */}
        Of {daily.points.length} mornings, {daily.reasks} brought new votes.
        {rounding > 0 ? (
          <>
            {" "}
            {rounding} further change{rounding === 1 ? "" : "s"} of the printed score rode
            under {VOTES_WORTH_CALLING_A_MOVE} votes, which is a rounding boundary being
            crossed rather than an opinion moving.
          </>
        ) : null}{" "}
        A score is stored out of 100 and shown out of 10, so only a change this site
        would print counts as a move. These readings are daily and the score above is
        the weekly published figure, so this can run a few days ahead of it.
      </p>
    </div>
  );
}

/* The last reading's own score is deliberately not printed here. The rail above
 * carries the title's score and it is the merged winner of three sources, while
 * these readings are AniList's alone: the two legitimately differ, and two
 * numbers for one thing on one screen is the bug the digest's scale fix was
 * about. What this block adds is the movement, which is its own fact. */
