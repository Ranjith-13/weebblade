import Link from "next/link";
import { Suspense } from "react";
import { getScoreSettling, seasonKey, seasonLabel } from "@/lib/api";
import {
  calendarDate,
  PHASE_LABEL,
  shareOf,
  sourceLabel,
  type ArrivalPoint,
  type SeasonPhase,
  type ScoreSettling,
  type SeasonSettling,
  type SettlingBand,
} from "@/lib/types";

export const metadata = {
  title: "How a score settles",
  description:
    "What happens to an anime score over its life, read from every dated copy of the catalogue the pipeline has kept: when a season acquires its numbers, how long they keep moving, and what they do afterwards.",
};

/* THE ONE PAGE HERE THAT READS THE WAREHOUSE DOWN THE DATES.
 *
 * Every other view answers "what is true now" from anime_media_latest, which is
 * the top slice of anime_media's 66,098 dated rows. The pipeline has been
 * accumulating a longitudinal dataset since June and rendering it as a
 * catalogue; this is the half that makes it a data project rather than a front
 * end over an API, and until now nothing on the site said any of it.
 *
 * It exists as a page rather than a sentence because the finding is a shape,
 * not a figure: a score arrives weeks after its season is listed, moves while
 * the show is on air, and then stops moving where anyone can see it without
 * ever stopping being revised. Three facts, each of which needs its own
 * evidence next to it.
 *
 * WHY THE METHOD COMES BEFORE THE NUMBERS, high on the page and not in a
 * footnote: the first version of this measurement counted snapshots and
 * reported that no score older than two seasons ever moves. That was a fact
 * about which seasons the pipeline refetches, not about anime - most rows in
 * most runs are copies - and it was wrong in the most flattering possible
 * direction. Anything that reads this page should meet that caveat before it
 * meets a percentage. The arithmetic is in backend/app/routers/scores.py.
 *
 * No numbers are written into this file. Every figure below is read from the
 * response, because the window grows by a run a week and a number in the copy
 * is wrong by the next one.
 */

const PHASES: SeasonPhase[] = ["airing", "over", "upcoming"];

/** Whole days between two run dates. Both are plain YYYY-MM-DD in UTC, so this
 *  needs no timezone reasoning and must not acquire any. */
function daysBetween(from: string, to: string): number {
  return Math.round(
    (Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000,
  );
}

/* A share as a bar, in the colour reserved for quantitative rails. Under the
   figure rather than instead of it: the counts behind these rates are small
   enough that a bar alone would overstate what is known. */
function Rail({ part, whole }: { part: number; whole: number }) {
  const share = whole === 0 ? 0 : part / whole;
  return (
    <span className="mt-1 block h-[3px] bg-rule" aria-hidden>
      <span className="block h-full bg-data" style={{ width: `${share * 100}%` }} />
    </span>
  );
}

/* Column headings in .meta, not .stamp. The uppercase tracked label is for
   structural labels and is rationed to single digits sitewide (globals.css);
   two tables' worth of headings would be a dozen of them on one page, which is
   the texture that rule exists to prevent. */
const HEAD = "meta pb-1.5 text-left font-normal align-bottom";
const NUM = "tnum py-2 text-right tabular-nums";

function Figures({ row }: { row: SeasonSettling | SettlingBand }) {
  return (
    <>
      <td className={NUM}>{row.reasks}</td>
      <td className={NUM}>{row.revised}</td>
      <td className={NUM}>
        <span className="whitespace-nowrap">
          {row.visible} <span className="meta">{shareOf(row.visible, row.reasks)}</span>
        </span>
        <Rail part={row.visible} whole={row.reasks} />
      </td>
      <td className={NUM}>{row.median_change.toFixed(2)}</td>
    </>
  );
}

function SettlingTable({ data }: { data: ScoreSettling }) {
  return (
    /* Held to a reading measure rather than the 1340px container. Five columns
       stretched across a wide screen put a season's name and its figures a foot
       apart, and the row rule between them is the only thing carrying the eye. */
    <table className="mt-5 w-full max-w-[46rem] table-fixed border-collapse text-[0.85rem]">
      <colgroup>
        <col className="w-[32%]" />
        <col className="w-[16%]" />
        <col className="w-[18%]" />
        <col className="w-[19%]" />
        <col className="w-[15%]" />
      </colgroup>
      <caption className="sr-only">
        Re-asked readings of a score by season, grouped by whether the season was on air while
        the pipeline was watching
      </caption>
      <thead>
        <tr className="border-b-2 border-ink">
          <th scope="col" className={HEAD}>
            Season
          </th>
          <th scope="col" className={`${HEAD} !text-right`}>
            Asked again
          </th>
          <th scope="col" className={`${HEAD} !text-right`}>
            Answer differed
          </th>
          <th scope="col" className={`${HEAD} !text-right`}>
            Enough to print
          </th>
          <th scope="col" className={`${HEAD} !text-right`}>
            Median change
          </th>
        </tr>
      </thead>
      {PHASES.map((phase) => {
        const band = data.bands.find((b) => b.phase === phase);
        const seasons = data.seasons.filter((s) => s.phase === phase);
        const only = seasons.length === 1 ? seasons[0] : null;
        if (!band) return null;
        return (
          <tbody key={phase}>
            {/* The phase's own totals sit in its heading row, so the comparison
                the page is about is one glance down a single column rather than
                a second table repeating the same five measures. */}
            <tr className="border-b border-ink">
              <th scope="rowgroup" className="py-2 text-left font-semibold">
                {PHASE_LABEL[phase]}{" "}
                {/* A band of one season printed its totals and then the same
                    figures again on the season beneath. Its name goes up here
                    instead. */}
                <span className="meta tnum">
                  {only ? seasonLabel(only.season, only.season_year) : `${band.seasons} seasons`}
                </span>
              </th>
              <Figures row={band} />
            </tr>
            {(only ? [] : seasons).map((season) => (
              <tr key={`${season.season}-${season.season_year}`} className="border-b border-rule">
                <td className="py-2 pl-3 text-ink-soft">
                  <Link
                    href={`/browse?season=${seasonKey(season.season, season.season_year)}`}
                    className="underline decoration-rule underline-offset-4 transition-colors hover:text-flag"
                  >
                    {seasonLabel(season.season, season.season_year)}
                  </Link>
                </td>
                <Figures row={season} />
              </tr>
            ))}
          </tbody>
        );
      })}
    </table>
  );
}

function ArrivalTable({ points }: { points: ArrivalPoint[] }) {
  return (
    <table className="mt-5 w-full max-w-[30rem] table-fixed border-collapse text-[0.85rem]">
      <colgroup>
        <col className="w-[38%]" />
        <col className="w-[24%]" />
        <col className="w-[38%]" />
      </colgroup>
      <caption className="sr-only">
        How many of the season&rsquo;s titles the catalogue listed, and how many it had a score
        for, on each run date
      </caption>
      <thead>
        <tr className="border-b-2 border-ink">
          <th scope="col" className={HEAD}>
            Run
          </th>
          <th scope="col" className={`${HEAD} !text-right`}>
            Listed
          </th>
          <th scope="col" className={`${HEAD} !text-right`}>
            Scored
          </th>
        </tr>
      </thead>
      <tbody>
        {points.map((p) => (
          <tr key={p.run_date} className="border-b border-rule">
            <td className="py-2">{calendarDate(p.run_date)}</td>
            <td className={NUM}>{p.listed}</td>
            <td className={NUM}>
              <span className="whitespace-nowrap">
                {p.scored} <span className="meta">{shareOf(p.scored, p.listed)}</span>
              </span>
              <Rail part={p.scored} whole={p.listed} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Nothing({ reason }: { reason: string }) {
  return (
    <p className="mt-6 max-w-[58ch] leading-[1.7] text-ink-soft">
      {reason} The warehouse keeps a dated copy of the catalogue on every run, so this fills in by
      itself as the runs accumulate.
    </p>
  );
}

async function Settling() {
  const data = await getScoreSettling();

  /* The API has not answered for this: either it holds no warehouse yet, or it
     is running a commit older than this page. Both are states, not errors. */
  if (!data) {
    return (
      <Nothing reason="The API has no answer for this yet, which happens while it is still coming up on a new release." />
    );
  }

  const { first_run: first, last_run: last, reasks, snapshots } = data;

  if (!first || !last || reasks === 0) {
    return (
      <Nothing
        reason={
          snapshots > 1
            ? `${snapshots} copies of the catalogue are on file and no source has yet been asked about the same title twice.`
            : "There is one copy of the catalogue on file, so there is nothing to compare it with."
        }
      />
    );
  }

  const airing = data.bands.find((b) => b.phase === "airing");
  const over = data.bands.find((b) => b.phase === "over");
  const unasked = data.seasons_held - data.seasons.length;
  const days = daysBetween(first, last);
  const leader = data.sources[0];
  const arrival = data.arrival;
  const blind = arrival?.points.filter((p) => p.listed > 0 && p.scored === 0) ?? [];
  const firstScored = arrival?.points.find((p) => p.scored > 0);
  const settled = arrival?.points[arrival.points.length - 1];

  return (
    <>
      <p className="mt-4 max-w-[62ch] leading-[1.7] text-ink-soft">
        Every other page here prints what the sources say now. The warehouse also kept what they
        said before: {snapshots} dated copies of the catalogue between {calendarDate(first)}
        {first.slice(0, 4) !== last.slice(0, 4) && ` ${first.slice(0, 4)}`} and{" "}
        {calendarDate(last)} {last.slice(0, 4)}. This page reads them down the dates instead of
        across the titles.
      </p>

      <section className="mt-10 border-t-2 border-ink pt-5">
        <h2 className="font-display text-[1.5rem] font-black leading-none">
          A row written again is not a question asked again
        </h2>
        <p className="mt-4 max-w-[62ch] leading-[1.7] text-ink-soft">
          The weekly run refetches the season it is covering and copies every other title&rsquo;s
          row forward unchanged. So a score that never moves may simply never have been looked up,
          and the first pass at this measurement made exactly that mistake: it counted snapshots,
          and reported as a fact about anime what was really a fact about the pipeline&rsquo;s own
          schedule.
          {unasked > 0 && (
            <>
              {" "}
              {unasked} of the {data.seasons_held} seasons on file were not asked about at all in
              this window. They are missing from the table below rather than listed as settled.
            </>
          )}
        </p>
        <p className="mt-3 max-w-[62ch] leading-[1.7] text-ink-soft">
          What is counted instead is a reading where the source&rsquo;s own vote count had moved
          too, which no copy can fake. There are <span className="tnum">{reasks}</span> of those.
          The test is deliberately the vote count and not the score: a test that looks at the
          answer discards every reading that came back the same, and would find movement
          everywhere.
        </p>
      </section>

      <section className="mt-10">
        <h2 className="font-display text-[1.5rem] font-black leading-none">
          What a re-asked score did
        </h2>
        {/* DELIBERATELY NOT ANIMATED, unlike every other listing here. A
            stagger holds its targets at opacity 0 until a scroll trigger fires,
            and on this page the targets are the argument: scrolling fast landed
            on a table of five column headings and nine empty rules. A plate
            grid can afford that and a table of evidence cannot. Leaving it out
            also means this route loads no GSAP chunk at all, which is the right
            trade for a page whose only interaction is reading. */}
        <SettlingTable data={data} />
        <p className="meta mt-3 max-w-[62ch] !leading-[1.6]">
          A score is stored out of 100 and printed out of 10 to one decimal, so one whole point is
          the smallest change this site can show. The median column is in stored points; the column
          beside it counts the readings that crossed a printable step.
        </p>

        {airing && over && (
          <>
            <p className="mt-6 max-w-[62ch] leading-[1.7]">
              A number moves while its show is on air and then stops moving where anyone can see
              it. It does not stop being revised. Of the{" "}
              <span className="tnum">{over.reasks}</span> readings of a season already over,{" "}
              <span className="tnum">{over.revised}</span> came back different and{" "}
              <span className="tnum">{over.visible}</span> differed by enough to print. The average
              is still being refined years after the last episode, two decimal places below
              anything this site would ever show.
            </p>
            <p className="mt-3 max-w-[62ch] leading-[1.7] text-ink-soft">
              It is not a drift in either direction. Among readings of a season on air,{" "}
              <span className="tnum">{airing.up}</span> rose and{" "}
              <span className="tnum">{airing.down}</span> fell; among readings of one already over,{" "}
              <span className="tnum">{over.up}</span> and <span className="tnum">{over.down}</span>
              . Scores here do not sag once the audience moves on. They just stop wobbling.
            </p>
          </>
        )}
      </section>

      {arrival && settled && (
        <section className="mt-10 border-t-2 border-ink pt-5">
          <h2 className="font-display text-[1.5rem] font-black leading-none">
            Before any of that, a score has to arrive
          </h2>
          <p className="mt-4 max-w-[62ch] leading-[1.7] text-ink-soft">
            The sources list a season as soon as it is announced, months before it airs, so its
            first appearances in the catalogue carry titles and no numbers.{" "}
            {seasonLabel(arrival.season, arrival.season_year)} sat in the catalogue through{" "}
            <span className="tnum">{blind.length}</span> {blind.length === 1 ? "run" : "runs"}{" "}
            without a single scored title.
            {firstScored && (
              <>
                {" "}
                It went from the first one on {calendarDate(firstScored.run_date)} to{" "}
                <span className="tnum">{settled.scored}</span> of{" "}
                <span className="tnum">{settled.listed}</span> in{" "}
                <span className="tnum">{daysBetween(firstScored.run_date, settled.run_date)}</span>{" "}
                days.
              </>
            )}
          </p>
          <ArrivalTable points={arrival.points} />
          <p className="meta mt-3 max-w-[62ch] !leading-[1.6]">
            The same titles throughout, counted on every run the catalogue holds them. Copied rows
            are included here on purpose: the question is what the catalogue held on that date, and
            a copy of yesterday&rsquo;s row is still what it held.
          </p>
          <p className="mt-5 max-w-[62ch] leading-[1.7] text-ink-soft">
            This is the halftone on every plate in the catalogue, drawn in time. A title with no
            score upstream prints screened back to a visible dot screen, and that is not a styling
            choice about new titles: it is the top of that column.
          </p>
        </section>
      )}

      <section className="mt-10 border-t border-rule pt-5">
        <h2 className="meta">What this cannot tell you</h2>
        <ul className="mt-3 max-w-[62ch] space-y-2.5 text-[0.85rem] leading-[1.6] text-ink-soft">
          {leader && data.sources.length > 1 && (
            <li>
              <span className="tnum">{leader.reasks}</span> of the{" "}
              <span className="tnum">{reasks}</span> re-asked readings are{" "}
              {sourceLabel(leader.source)}&rsquo;s. The other
              sources&rsquo; rows are refetched far less often, so most of this is one
              source&rsquo;s revisions rather than a consensus.
            </li>
          )}
          <li>
            The window is <span className="tnum">{days}</span> days long and grows by one run a
            week. Nothing here can see further back than {calendarDate(first)}, which is why the
            seasons are sorted by where they sat during the window and not by age.
          </li>
          <li>
            TV titles only, as the catalogue&rsquo;s own default view is. Measured across every
            format the shape is the same to within a point or two, but most of a season&rsquo;s
            music videos and shorts have no score to revise.
          </li>
        </ul>
      </section>

      <p className="mt-10 border-t border-rule pt-5 text-[0.9rem]">
        <Link
          href="/changes"
          className="border-b-2 border-flag pb-0.5 font-medium transition-colors hover:text-flag"
        >
          The same history, one week at a time
        </Link>
      </p>
    </>
  );
}

/* Streams, so the shell is sent before the API answers. It carries
   data-footer-waits for the reason every streamed route here does: a footer
   painted above the content is pushed down when the content arrives, which is
   the only layout shift this site has ever measured. */
function SettlingSkeleton() {
  return (
    <div data-footer-waits data-skeleton className="mt-6">
      <div className="h-4 w-2/3 max-w-[40rem] bg-plate" />
      <div className="mt-2 h-4 w-1/2 max-w-[32rem] bg-plate" />
      <div className="mt-10 h-7 w-1/3 max-w-[24rem] bg-plate" />
      <div className="mt-5 border-b-2 border-ink" />
      {Array.from({ length: 10 }, (_, i) => (
        <div key={i} className="flex items-center justify-between gap-6 border-b border-rule py-3">
          <div className="h-3 w-24 bg-plate" />
          <div className="h-3 w-40 bg-plate" />
        </div>
      ))}
    </div>
  );
}

export default function ScoresPage() {
  return (
    <div className="mx-auto max-w-[1340px] px-5 py-9 sm:px-7">
      <h1 className="font-display text-[clamp(2.1rem,6vw,3.4rem)] font-black leading-[0.95]">
        How a score settles
      </h1>
      <Suspense fallback={<SettlingSkeleton />}>
        <Settling />
      </Suspense>
    </div>
  );
}
