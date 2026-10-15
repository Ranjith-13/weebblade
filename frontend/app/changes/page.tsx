import Image from "next/image";
import Link from "next/link";
import { Suspense } from "react";
import { ScrollReveal } from "@/components/motion/ScrollReveal";
import { getChanges } from "@/lib/api";
import {
  calendarDate,
  changeSentence,
  CHANGE_SECTIONS,
  joinSources,
  type ChangedTitle,
} from "@/lib/types";

export const metadata = {
  title: "What changed",
  description:
    "What the sources said differently this week: shows that finished or started, dates that moved, scores, new listings.",
};

/* The week's changes, which until now only showed one title at a time.
 *
 * A listing like /schedule rather than a grid like /browse: the subject is an
 * event, not a title, and the same show can appear twice under different
 * headings. Grouped by what kind of news it is, because "seven episode counts"
 * and "ten shows finished" are read differently; within a group, the API's
 * order - newest fetch first, then by title.
 *
 * Every line names the sources that said it. Two sources disagree about a score
 * and move it separately, so an unattributed "7.5 to 7.4" beside a title page
 * showing 7.2 would read as a contradiction rather than as provenance.
 */

function ChangeRow({ c }: { c: ChangedTitle }) {
  return (
    <li className="border-t border-rule py-2.5">
      <Link href={`/anime/${c.wb_id}`} className="group flex items-center gap-3 focus:outline-none">
        <span className="relative block h-[3.2rem] w-[2.4rem] shrink-0 overflow-hidden border border-ink plate-known">
          {c.poster_url && <Image src={c.poster_url} alt="" fill sizes="40px" className="object-cover" />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[0.9rem] font-medium leading-tight transition-colors duration-150 group-hover:text-flag group-focus-visible:text-flag">
            {c.title ?? "Untitled"}
          </span>
          <span className="block text-[0.8rem] leading-tight text-ink-soft">{changeSentence(c)}</span>
          <span className="meta mt-0.5 block truncate">per {joinSources(c.sources)}</span>
        </span>
      </Link>
    </li>
  );
}

async function Week() {
  const { since, until, changes } = await getChanges();

  if (changes.length === 0) {
    return (
      <p className="mt-8 max-w-[52ch] leading-relaxed text-ink-soft">
        Nothing recorded yet. Each source is compared with its own previous fetch, so the first
        comparison lands with the next weekly run.
      </p>
    );
  }

  const sections = CHANGE_SECTIONS.map((s) => ({
    ...s,
    rows: changes.filter(
      (c) => s.fields.includes(c.field) && (s.where ? s.where(c) : true),
    ),
  })).filter((s) => s.rows.length > 0);

  return (
    <>
      <p className="mt-4 max-w-[60ch] leading-[1.7] text-ink-soft">
        {changes.length} changes in the week to {until ? calendarDate(until) : "the last fetch"},
        from {since ? calendarDate(since) : "the fetch before"}. Each source is compared with its
        own previous fetch of the same season, so this is what the sources changed, not what the
        pipeline did.
      </p>
      <p className="meta mt-2 max-w-[60ch] !leading-[1.6]">
        Recorded weekly, and only for the season being fetched. A title&apos;s own history, however
        far back it goes, is on its page, and what a score does over a whole life is on{" "}
        <Link
          href="/scores"
          className="underline decoration-rule underline-offset-4 transition-colors hover:text-flag"
        >
          how a score settles
        </Link>
        .
      </p>

      {/* WHAT IS ON THIS PAGE, which it never said. The sections run as
          newspaper columns and the page is 11,603px tall at 1440 and 28,284px
          on a phone - thirty-three viewports - so a reader who wanted "Newly
          listed" had to scroll past three hundred other entries to find out it
          existed. At 1440 the columns make it worse than a long page: you reach
          the bottom of column one and go back to the top for column two.

          One .meta line of anchors, built from the same sections the page
          renders, so it cannot drift from them. The device is the one the home
          page already uses to name this page's contents in a sentence. No
          numbering, no bullets, no rule - this is a line of prose that happens
          to be clickable. */}
      <p className="meta mt-3 max-w-[72ch] !leading-[1.8]">
        On this page:{" "}
        {sections.map((s, i) => (
          <span key={s.key}>
            {i > 0 && ", "}
            <a
              href={`#${s.key}`}
              className="underline decoration-rule underline-offset-4 transition-colors hover:text-flag"
            >
              {s.title.toLowerCase()}
            </a>{" "}
            <span className="tnum">{s.rows.length}</span>
          </span>
        ))}
      </p>

      {/* Columns for the same reason as the schedule: the sections are uneven,
          and a grid would leave dead space under the short ones. */}
      <ScrollReveal
        className="mt-9 gap-x-10 sm:columns-2 xl:columns-3"
        selector=":scope > section"
        y={10}
        start="top 94%"
      >
        {sections.map((s) => (
          <section key={s.key} id={s.key} className="mb-9 break-inside-avoid scroll-mt-6">
            <h2 className="flex flex-wrap items-baseline justify-between gap-x-3 border-b-2 border-ink pb-1.5">
              <span className="font-display text-[1.35rem] font-black leading-none">{s.title}</span>
              <span className="meta tnum">{s.rows.length}</span>
            </h2>
            <ul>
              {s.rows.map((c, i) => (
                <ChangeRow key={`${c.wb_id}-${c.field}-${c.new}-${i}`} c={c} />
              ))}
            </ul>
          </section>
        ))}
      </ScrollReveal>
    </>
  );
}

/* Same shape as the schedule's fallback, and it carries data-footer-waits for
   the same reason: the page streams, and a footer that paints before the week
   arrives is pushed down when it does. */
function WeekSkeleton() {
  return (
    <div data-footer-waits className="mt-9 gap-x-10 sm:columns-2 xl:columns-3">
      {[0, 1, 2].map((i) => (
        <div key={i} className="mb-9 break-inside-avoid">
          <div className="h-7 border-b-2 border-ink" />
          {[0, 1, 2].map((r) => (
            <div key={r} className="flex items-center gap-3 border-t border-rule py-2.5">
              <div className="h-[3.2rem] w-[2.4rem] shrink-0 border border-rule bg-plate" />
              <div className="flex-1 space-y-1.5">
                <div className="h-3 w-2/3 bg-plate" />
                <div className="h-2.5 w-1/2 bg-plate" />
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

export default function ChangesPage() {
  return (
    <div className="mx-auto max-w-[1340px] px-5 py-9 sm:px-7">
      <h1 className="font-display text-[clamp(2.1rem,6vw,3.4rem)] font-black leading-[0.95]">
        What changed
      </h1>
      <Suspense fallback={<WeekSkeleton />}>
        <Week />
      </Suspense>
    </div>
  );
}
