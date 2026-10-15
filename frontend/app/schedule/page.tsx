import Image from "next/image";
import Link from "next/link";
import { Suspense } from "react";
import { Countdown, LocalTime, TodayMarker } from "@/components/Airing";
import { ScrollReveal } from "@/components/motion/ScrollReveal";
import { getSchedule } from "@/lib/api";
import { calendarDate, dayKeyLabel, formatLabel, jstClock, type ScheduledEpisode } from "@/lib/types";

export const metadata = {
  title: "Schedule",
  description:
    "Every episode airing this week, by the day it airs in Japan, with a countdown in your own time.",
};

/* A listing, not a grid.
 *
 * /browse is already a grid of plates, and a schedule answers a different
 * question: not "what exists" but "when". So it is set as broadsheet listings —
 * a time column you can run your eye down, days as rules across the page. The
 * artwork is present but subordinate, because the time is the thing being
 * looked up.
 */

function EpisodeRow({ e }: { e: ScheduledEpisode }) {
  // The certainty treatment, meaning what it means everywhere: in colour when
  // the catalogue has a score. A show it does not hold has none here.
  const known = e.score_100 !== null;
  const content = (
    <>
      <span
        className={[
          "relative block h-[3.2rem] w-[2.4rem] shrink-0 overflow-hidden border border-ink",
          // plate-fine, because 36x49 is too small for the catalogue's 4px dot
          // pitch to read as a screen at all - see globals.css. The plate is
          // the only certainty signal on this row; it has to be legible.
          known ? "plate-known" : "plate-unknown plate-fine",
          e.poster_url ? "" : "plate-empty bg-plate",
        ].join(" ")}
      >
        {e.poster_url && <Image src={e.poster_url} alt="" fill sizes="40px" className="object-cover" />}
      </span>

      <span className="min-w-0 flex-1">
        {/* Two lines rather than one, because one was truncating 44 of the
            week's 123 titles at 390px - "The Prince of Tennis II U-17 WORLD CUP
            Final Member Selection Match" needs 465px in a 216px column. A
            reader opens this page to find out what is on tonight and was being
            shown the first two thirds of the answer. line-clamp leaves a title
            that fits on one line, so nothing changes at 1440 where most do. */}
        <span className="line-clamp-2 text-[0.9rem] font-medium leading-tight transition-colors duration-150 group-hover:text-flag group-focus-visible:text-flag">
          {e.title ?? "Untitled"}
        </span>
        {/* One line, held for the reader's own time, which arrives after
            mount. Nowrap so its arrival cannot wrap the line and shift every
            row below. A show the catalogue does not hold says where the link
            goes in place of its format: at 390px there is room for four
            items, not five. */}
        <span className="meta mt-0.5 flex min-h-[1.5em] items-baseline gap-x-3 overflow-hidden whitespace-nowrap">
          {e.episode !== null && <span className="tnum">Ep {e.episode}</span>}
          <span>{e.wb_id ? formatLabel(e.format) : "On AniList"}</span>
          <LocalTime at={e.airing_at} />
        </span>
      </span>
    </>
  );

  const box = "group flex min-w-0 flex-1 items-center gap-3 focus:outline-none";
  return (
    <li className="flex items-center gap-4 border-t border-rule py-2.5">
      {/* When, in one column: the time in Japan, and under it how long until
          then. The countdown is the one thing on the row that must not be
          clipped, so it is not left at the end of a line that can be. */}
      <span className="w-[4.2rem] shrink-0">
        <span className="tnum block text-[0.95rem] font-semibold leading-tight">{jstClock(e.airing_at)}</span>
        <span className="meta tnum block min-h-[1.5em]">
          <Countdown at={e.airing_at} />
        </span>
      </span>
      {e.wb_id ? (
        <Link href={`/anime/${e.wb_id}`} className={box}>
          {content}
        </Link>
      ) : (
        <a href={`https://anilist.co/anime/${e.anilist_id}`} target="_blank" rel="noreferrer" className={box}>
          {content}
        </a>
      )}
    </li>
  );
}

async function Week() {
  const { days, episodes, shows, fetchedOn } = await getSchedule();

  if (episodes === 0) {
    return (
      <p className="mt-8 max-w-[52ch] leading-relaxed text-ink-soft">
        No airing schedule has been fetched yet. It comes from AniList, checked daily; until the
        first check lands, this page has nothing to show.
      </p>
    );
  }

  return (
    <>
      <p className="mt-4 max-w-[60ch] leading-[1.7] text-ink-soft">
        {episodes} episodes of {shows} shows in the next seven days, by the day they air in Japan.
        Many air late at night there, so the day and time beside each one, in your own time, is
        often a day earlier. Shows the catalogue does not hold, like the long-runners older than
        it, are listed as AniList has them and link there.
      </p>
      {fetchedOn && (
        <p className="meta mt-2 max-w-[60ch] !leading-[1.6]">
          From AniList&apos;s airing schedule, checked {calendarDate(fetchedOn)}. A broadcast that
          slips is picked up at the next daily check.
        </p>
      )}

      {/* THE WEEK, IN ORDER, BEFORE THE COLUMNS SCRAMBLE IT. The days flow as
          newspaper columns, so the three headings in the first viewport at 1440
          read Thursday 15 Oct, Sunday 18 Oct, Tuesday 20 Oct - the tops of
          three columns, not the next three days. Friday, Saturday, Monday and
          Wednesday are below the fold of columns one to three and nothing says
          the columns continue.

          Columns are still right for the board itself (see below), so the fix
          is to say the week in reading order once, with each day a link to its
          own heading and its count beside it. Same device as /changes, and for
          the same reason: the page was navigable only by scrolling it. */}
      <p className="meta mt-5 max-w-[72ch] !leading-[1.8]">
        This week:{" "}
        {days.map((d, i) => {
          const { weekday, date } = dayKeyLabel(d.key);
          return (
            <span key={d.key}>
              {i > 0 && ", "}
              <a
                href={`#${d.key}`}
                className="underline decoration-rule underline-offset-4 transition-colors hover:text-flag"
              >
                {weekday} {date}
              </a>{" "}
              <span className="tnum">{d.items.length}</span>
            </span>
          );
        })}
      </p>

      {/* Columns, not a grid. The days are uneven, and in a grid every row is
          as tall as its tallest cell, leaving short days above dead space.
          Multi-column flow lets each day start where the last one ended;
          break-inside stops a day being torn across the fold of two columns.

          One reveal around the whole board, staggering the seven days, rather
          than one per day staggering a single element. */}
      <ScrollReveal
        className="mt-9 gap-x-10 sm:columns-2 xl:columns-3"
        selector=":scope > section"
        y={10}
        start="top 94%"
      >
        {days.map((d) => {
          const { weekday, date } = dayKeyLabel(d.key);
          return (
            <section key={d.key} id={d.key} className="mb-9 break-inside-avoid scroll-mt-6">
              {/* The heading parks at the top while its own section scrolls under
                it, on a phone only. This page is thirty-three viewports there,
                and the section you are inside is the one thing the screen never
                tells you once the heading has gone past - every row below it is
                a title and a date, which reads the same under any heading.

                Phone only because above sm this flows in newspaper columns, and
                position: sticky inside a multicol fragment is undefined. The
                heading already carries the ink rule, so nothing new is drawn;
                it simply stops leaving. */}
            <h2 className="flex flex-wrap items-baseline justify-between gap-x-3 border-b-2 border-ink pb-1.5 max-sm:sticky max-sm:top-0 max-sm:z-10 max-sm:bg-paper max-sm:pt-2">
                <span className="flex items-baseline gap-x-2.5">
                  <span className="font-display text-[1.5rem] font-black leading-none">{weekday}</span>
                  <span className="meta tnum">{date}</span>
                </span>
                <span className="meta flex items-baseline gap-x-3">
                  <TodayMarker dayKey={d.key} />
                  <span className="tnum">{d.items.length}</span>
                </span>
              </h2>

              {d.items.length > 0 ? (
                <ul>
                  {d.items.map((e) => (
                    <EpisodeRow key={`${e.anilist_id}:${e.episode}:${e.airing_at}`} e={e} />
                  ))}
                </ul>
              ) : (
                <p className="meta mt-3">Nothing scheduled</p>
              )}
            </section>
          );
        })}
      </ScrollReveal>
    </>
  );
}

/* The week streams in behind this, even from a prerendered page: the HTML
   carries the fallback first and the week further down, swapped in by script.
   With the footer in view below it, the swap pushed the footer off: a layout
   shift of 0.09 on every load at 1440x1000. data-footer-waits keeps the footer
   out until the week arrives - see the rule in globals.css. It used to be a
   fallback a screen tall, which worked for a full week and would have shifted
   an empty one the other way. */
function WeekSkeleton() {
  return (
    <div data-footer-waits className="mt-9 gap-x-10 sm:columns-2 xl:columns-3" aria-hidden>
      {Array.from({ length: 7 }, (_, i) => (
        <section key={i} className="mb-9 break-inside-avoid">
          <div className="h-[2.1rem] border-b-2 border-ink" />
          <div className="mt-2 h-[3.2rem] border-t border-rule bg-plate" />
        </section>
      ))}
    </div>
  );
}

export default function SchedulePage() {
  return (
    <div className="mx-auto max-w-[1340px] px-5 py-9 sm:px-7">
      <div className="max-w-[62ch]">
        <h1 className="font-display text-[clamp(2.2rem,6vw,3.4rem)] font-black leading-none">
          Schedule
        </h1>
      </div>

      <Suspense fallback={<WeekSkeleton />}>
        <Week />
      </Suspense>
    </div>
  );
}
