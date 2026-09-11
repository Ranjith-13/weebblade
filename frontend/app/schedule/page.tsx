import Image from "next/image";
import Link from "next/link";
import { Suspense } from "react";
import { LocalSlot, TodayMarker } from "@/components/LocalSlot";
import { ScrollReveal } from "@/components/motion/ScrollReveal";
import { getSchedule } from "@/lib/api";
import {
  displayTitle,
  formatLabel,
  isKnown,
  SCHEDULE_DAYS,
  titleHref,
  weekdayLabel,
  type Anime,
} from "@/lib/types";

export const metadata = {
  title: "Schedule",
  description:
    "What is airing this week, by broadcast day in Japan, with each slot converted to your own time.",
};

/* A listing, not a grid.
 *
 * /browse is already a grid of plates, and a schedule answers a different
 * question: not "what exists" but "when". So it is set as broadsheet listings —
 * a time column you can run your eye down, days as rules across the page. The
 * artwork is present but subordinate, because the time is the thing being
 * looked up.
 */

function Slot({ anime }: { anime: Anime }) {
  const title = displayTitle(anime);
  const known = isKnown(anime);

  return (
    <li className="flex items-center gap-4 border-t border-rule py-2.5">
      <span className="tnum w-[3.6rem] shrink-0 text-[0.95rem] font-semibold">
        {anime.broadcast_time}
      </span>

      <Link
        href={titleHref(anime)}
        className="group flex min-w-0 flex-1 items-center gap-3 focus:outline-none"
      >
        <span
          className={[
            "relative block h-[3.2rem] w-[2.4rem] shrink-0 overflow-hidden border border-ink",
            known ? "plate-known" : "plate-unknown",
            anime.poster_url ? "" : "plate-empty bg-plate",
          ].join(" ")}
        >
          {anime.poster_url && (
            <Image src={anime.poster_url} alt="" fill sizes="40px" className="object-cover" />
          )}
        </span>

        <span className="min-w-0 flex-1">
          <span className="block truncate text-[0.9rem] font-medium leading-tight transition-colors duration-150 group-hover:text-flag group-focus-visible:text-flag">
            {title}
          </span>
          {/* One line of space held for the viewer's own time, which arrives
              after mount. Without it every row shifts as the column fills. */}
          <span className="meta mt-0.5 flex min-h-[1.5em] items-baseline gap-x-3">
            <span>{formatLabel(anime.format)}</span>
            <LocalSlot
              broadcastDay={anime.broadcast_day}
              broadcastTime={anime.broadcast_time}
            />
          </span>
        </span>
      </Link>
    </li>
  );
}

async function Week() {
  const { days, slotted, airingWithoutSlot } = await getSchedule();

  if (slotted === 0) {
    return (
      <p className="mt-8 max-w-[52ch] leading-relaxed text-ink-soft">
        No broadcast slots are recorded for anything airing right now. Slots come from
        MyAnimeList; if that source has not landed a run yet, this page has nothing to show.
      </p>
    );
  }

  return (
    <>
      <p className="mt-4 max-w-[58ch] leading-[1.7] text-ink-soft">
        {slotted} titles with a known slot, by the day they broadcast in Japan. Most air after
        midnight there, so the day beside each one is often not the day where you are.
        {airingWithoutSlot > 0 && (
          <> {airingWithoutSlot} more are airing with no slot recorded, and are not listed here.</>
        )}
      </p>

      {/* Columns, not a grid. The days are wildly uneven — 16 on Sunday against 4
          on Tuesday — and in a grid every row is as tall as its tallest cell, so
          Monday's 13 rows left Tuesday and Wednesday sitting above a column of
          dead space. Multi-column flow lets each day start where the last one
          ended. break-inside is what stops a day being torn in half across the
          fold of two columns.

          One reveal around the whole board, staggering the seven days, rather
          than one per day staggering a single element. */}
      <ScrollReveal
        className="mt-9 gap-x-10 sm:columns-2 xl:columns-3"
        selector=":scope > section"
        y={10}
        start="top 94%"
      >
        {days.map((d) => (
          <section key={d.day} className="mb-9 break-inside-avoid">
            <h2 className="flex flex-wrap items-baseline justify-between gap-x-3 border-b-2 border-ink pb-1.5">
              <span className="font-display text-[1.5rem] font-black leading-none">
                {weekdayLabel(d.day)}
              </span>
              <span className="meta flex items-baseline gap-x-3">
                <TodayMarker day={d.day} />
                <span>{d.items.length}</span>
              </span>
            </h2>

            {d.items.length > 0 ? (
              <ul>
                {d.items.map((a) => (
                  <Slot key={`${a.source}:${a.source_id}`} anime={a} />
                ))}
              </ul>
            ) : (
              <p className="meta mt-3">Nothing scheduled</p>
            )}
          </section>
        ))}
      </ScrollReveal>
    </>
  );
}

function WeekSkeleton() {
  return (
    <div className="mt-9 gap-x-10 sm:columns-2 xl:columns-3" aria-hidden>
      {SCHEDULE_DAYS.map((day) => (
        <section key={day} className="mb-9 break-inside-avoid">
          <div className="border-b-2 border-ink pb-1.5">
            <span className="font-display text-[1.5rem] font-black leading-none text-rule">
              {weekdayLabel(day)}
            </span>
          </div>
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
