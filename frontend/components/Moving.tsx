import Link from "next/link";
import { getMoving } from "@/lib/api";
import {
  calendarDate,
  compactCount,
  formatLabel,
  moveDirection,
  scoreOutOfTen,
  titleHref,
  VOTES_WORTH_CALLING_A_MOVE,
  weightedMovers,
} from "@/lib/types";

/* What the season's scores have done this week, across titles.
 *
 * THE FRONT DOOR THE MEASUREMENT DID NOT HAVE. The daily series has been asking
 * every morning since 16 October and could be seen only by landing on the right
 * title's page and knowing to look: 308 re-asks over the first three days with
 * no route to any of them. /scores explains how a score behaves over its life
 * and is read once; this is the same instrument pointed at this week, and it is
 * the only thing here that answers "what is happening" with titles rather than
 * with rates.
 *
 * IT SITS ABOVE THE METHOD, not below it. The rest of this page is the argument
 * for why these numbers mean anything, and an argument is worth reading after
 * the thing it is about. A reader who stops at the first screen should still
 * leave with the one fact no other site prints.
 *
 * RANKED BY THE VOTES BEHIND THE MOVE, not by its size, and the two disagree
 * constantly: a score stored out of 100 and shown out of 10 crosses a rounding
 * boundary on a single vote, so a list sorted by size puts its least meaningful
 * row at the top. Sorted by weight the top of the list is where the most people
 * actually changed their minds - and the rest are counted off rather than
 * printed, because "moved on two votes" is a fact about arithmetic.
 *
 * MOST TITLES DO NOT MOVE, and saying so is what makes the rest worth reading.
 * 151 of the 178 re-asked in the first window were steady. A page that printed
 * only the movers would imply a season in constant motion.
 */
export async function MovingSection() {
  let data;
  try {
    data = await getMoving();
  } catch {
    return null;
  }
  const movers = weightedMovers(data);
  // Nothing to show is a real answer on a quiet week, and on a warehouse
  // published before the series existed. Both render nothing rather than an
  // empty heading, which is the rule the rest of this page follows. Either
  // list alone is worth the section: a week where no score moved but four
  // thousand people picked something up is still a week with news in it.
  if (!data || (movers.length === 0 && data.gaining.length === 0)) return null;

  const quiet = data.movers.length - movers.length;

  return (
    <section aria-labelledby="moving-title" className="mt-10 border-t-2 border-ink pt-5">
      <h2 id="moving-title" className="font-display text-[1.5rem] font-black leading-none">
        What moved this week
      </h2>
      <p className="mt-4 max-w-[62ch] leading-[1.7] text-ink-soft">
        AniList is asked about every airing title every morning, so unlike the rest of this page
        these are days rather than weeks apart.{" "}
        <span className="tnum">{data.titles_reasked}</span> titles were asked again between{" "}
        {data.first_day && calendarDate(data.first_day)} and{" "}
        {data.last_day && calendarDate(data.last_day)}, and{" "}
        <span className="tnum">{data.steady}</span> of them print the same score they printed
        before. These are the ones that do not.
      </p>

      {movers.length === 0 ? (
        <p className="mt-4 max-w-[62ch] leading-[1.7] text-ink-soft">
          None of them moved the score this site prints, which is an ordinary week: a score is an
          average over tens of thousands of votes and a few days rarely shift one.
        </p>
      ) : (
      <ol className="mt-5">
        {movers.map((m) => {
          const direction = moveDirection(m);
          return (
            <li
              key={m.wb_id}
              className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-t border-rule py-2"
            >
              <Link href={titleHref(m)} className="font-semibold hover:text-flag">
                {m.title}
              </Link>
              {m.format && <span className="meta">{formatLabel(m.format)}</span>}
              <span className="tnum ml-auto text-[0.95rem]">
                {scoreOutOfTen(m.was)}{" "}
                {/* The word, not an arrow: a glyph at this size needs a legend
                    and reads as decoration. */}
                <span className="meta">{direction === "up" ? "up to" : "down to"}</span>{" "}
                {/* WEIGHT, NOT COLOUR. The first draft printed a rise in flag
                    pink, which reads well and is wrong: on this site that
                    colour means a title HAS a score, and a second meaning for
                    it - "went up" - is the same drift DESIGN.md refuses for
                    .plate-unknown. The words either side already say which way
                    it went, and they say it to a reader who cannot see hue. */}
                <span className="font-semibold">{scoreOutOfTen(m.now)}</span>
              </span>
              {/* The weight travels with the move, always. Without it the row
                  above and a two-vote rounding flip are the same sentence. */}
              <span className="meta w-full text-right tnum sm:w-auto sm:text-left">
                {compactCount(m.votes_gained)} new votes
              </span>
            </li>
          );
        })}
      </ol>
      )}

      {/* THE OTHER QUESTION, and on this data the bigger one. A score moving is
          the rarer event: 37 of the 243 titles re-asked in the first window,
          while 78% of the week's votes landed on titles whose score held. A
          page built only on movers leaves most of the week on the floor, and
          "four thousand people picked this up" is a thing no rating says. */}
      {data.gaining.length > 0 && (
        <>
          <h3 className="mt-9 font-display text-[1.2rem] font-black leading-none">
            Who found an audience
          </h3>
          <p className="mt-3 max-w-[62ch] leading-[1.7] text-ink-soft">
            The same readings answer a second question, and mostly about different titles. A score
            is an average and moves slowly; the number of people holding a title moves every day.
            Of <span className="tnum">{compactCount(data.votes_total)}</span> new votes in this
            window, <span className="tnum">{compactCount(data.votes_on_steady)}</span> went to
            titles whose printed score did not budge, so they appear nowhere above.
          </p>
          <ol className="mt-4">
            {data.gaining.map((g) => (
              <li
                key={g.wb_id}
                className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-t border-rule py-2"
              >
                <Link href={titleHref(g)} className="font-semibold hover:text-flag">
                  {g.title}
                </Link>
                {/* Where the two lists overlap, said rather than hidden. */}
                {g.moved && <span className="meta">score moved too</span>}
                <span className="tnum ml-auto text-[0.95rem]">
                  <span className="font-semibold">+{compactCount(g.gained)}</span>{" "}
                  <span className="meta">people</span>
                </span>
                {/* The rate beside the volume: what separates a big show
                    ticking over from a small one breaking out. */}
                <span className="meta w-full text-right tnum sm:w-auto sm:text-left">
                  {g.share}% more than it had
                </span>
              </li>
            ))}
          </ol>
          <p className="meta mt-3 max-w-[62ch] !leading-[1.6]">
            Ranked by how many people rather than by the rate, with the rate beside it. Counted
            from AniList&rsquo;s own readings, never against the score above, which may be a
            different source&rsquo;s number: subtracting two sources from each other reported a
            title as having grown 892% where it had grown 10.8%.
          </p>
        </>
      )}

      {movers.length > 0 && (
      <p className="meta mt-9 max-w-[62ch] !leading-[1.6]">
        Ranked by the votes behind the move rather than its size, because a score stored out of 100
        and shown out of 10 crosses a rounding boundary on a single vote.
        {quiet > 0 && (
          <>
            {" "}
            {quiet} further title{quiet === 1 ? "" : "s"} changed the score shown on fewer than{" "}
            {VOTES_WORTH_CALLING_A_MOVE} new votes, which is that boundary being crossed rather
            than an opinion moving, and {quiet === 1 ? "is" : "are"} left out here.
          </>
        )}{" "}
        Only titles the catalogue calls airing are asked daily, so this is the current season by
        construction rather than by a filter.
      </p>
      )}
    </section>
  );
}
