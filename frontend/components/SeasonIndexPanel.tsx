"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { SEASON_INDEX_ID } from "@/lib/types";

/* Mirrors SeasonRef in lib/api.ts. Declared here because that module is
 * server-only, and a client component must not import from it. */
export type SeasonEntry = {
  key: string;
  season: string;
  year: number;
  label: string;
  count: number;
};

function byYear(seasons: SeasonEntry[]) {
  const years: { year: number; seasons: SeasonEntry[] }[] = [];
  for (const s of seasons) {
    const last = years.at(-1);
    if (last?.year === s.year) last.seasons.push(s);
    else years.push({ year: s.year, seasons: [s] });
  }
  return years;
}

function seasonName(s: SeasonEntry) {
  return `${s.season.charAt(0)}${s.season.slice(1).toLowerCase()}`;
}

/** The index itself. Presentational, so the server can render it as the
 *  Suspense fallback before the URL is known, with nothing marked current. */
export function SeasonIndexPanel({
  seasons,
  activeKey,
  panelRef,
}: {
  seasons: SeasonEntry[];
  activeKey: string | null;
  panelRef?: React.Ref<HTMLDivElement>;
}) {
  const total = seasons.reduce((n, s) => n + s.count, 0);
  const newest = seasons[0];
  const oldest = seasons.at(-1);

  return (
    <div
      id={SEASON_INDEX_ID}
      ref={panelRef}
      popover="auto"
      aria-labelledby="season-index-title"
      className="season-index"
    >
      <div className="mx-auto grid max-w-[1340px] gap-x-14 gap-y-6 px-5 pt-6 pb-8 sm:px-7 md:grid-cols-[auto_minmax(0,1fr)]">
        <div>
          <div className="flex items-baseline justify-between gap-6">
            <h2 id="season-index-title" className="text-[0.95rem] font-semibold">
              Seasons on file
            </h2>
            <button
              type="button"
              popoverTarget={SEASON_INDEX_ID}
              popoverTargetAction="hide"
              className="meta inline-block py-1.5 underline decoration-rule underline-offset-4 transition-colors hover:text-flag"
            >
              Close
            </button>
          </div>

          {/* Year columns, newest first, and within a year the newest season on
              top: the same order the rest of the site uses, so the season a bare
              URL shows is always the first entry here. */}
          <div className="mt-5 grid grid-cols-3 gap-x-5 sm:gap-x-10">
            {byYear(seasons).map(({ year, seasons: inYear }) => (
              <section key={year} aria-labelledby={`season-year-${year}`}>
                <h3
                  id={`season-year-${year}`}
                  className="tnum font-display text-[1.7rem] font-black leading-none"
                >
                  {year}
                </h3>
                <ul className="mt-3 border-t-2 border-ink sm:w-44">
                  {inYear.map((s) => {
                    const active = s.key === activeKey;
                    return (
                      <li key={s.key} className="border-b border-rule">
                        <Link
                          href={`/browse?season=${s.key}`}
                          aria-current={active ? "page" : undefined}
                          aria-label={`${s.label}, ${s.count} titles`}
                          className={[
                            "flex items-baseline justify-between gap-3 py-2 text-[0.9rem] transition-colors duration-150 hover:text-flag",
                            active ? "font-semibold text-flag" : "text-ink",
                          ].join(" ")}
                        >
                          {seasonName(s)}
                          <span className="tnum text-[0.72rem] text-ink-soft">{s.count}</span>
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
          </div>
        </div>

        {/* What a season is here, stated where the question arises. Both sources
            file a title under the season it premiered in, so a long runner that
            began in Spring is still in Spring while it airs through Summer, and
            a reader looking for it under Summer would otherwise think it missing. */}
        <div className="max-w-[44ch] self-end text-[0.85rem] leading-[1.65] text-ink-soft md:border-l md:border-rule md:pl-8">
          {newest && oldest && (
            <p className="text-ink">
              <span className="tnum font-semibold">{total.toLocaleString()}</span> titles across{" "}
              <span className="tnum">{seasons.length}</span> seasons, {oldest.label} to{" "}
              {newest.label}.
            </p>
          )}
          <p className="mt-2">
            A season is a quarter of the broadcast year. Each title is filed under the season
            it premiered in, so a show that began in Spring and is still airing stays in Spring.
          </p>
        </div>
      </div>
    </div>
  );
}

/** The live index: marks the season in view, sits under the header when it
 *  opens, and closes when the route changes. */
export function SeasonIndexLive({ seasons }: { seasons: SeasonEntry[] }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const panel = useRef<HTMLDivElement>(null);

  const requested = searchParams.get("season");
  const newest = seasons[0]?.key ?? null;
  // Mirrors getSeason(): an unknown key falls back to the newest season, and
  // the front page and the schedule are always the newest.
  const activeKey =
    pathname === "/browse"
      ? seasons.some((s) => s.key === requested)
        ? requested
        : newest
      : pathname === "/" || pathname.startsWith("/schedule")
        ? newest
        : null;

  useEffect(() => {
    const el = panel.current;
    if (!el) return;
    /* Placed on open rather than in CSS because the header's height is not a
       constant: it wraps to two rows on a phone. Fixed, and never above the top
       edge, so a trigger lower down the page still opens it in view. */
    const place = (event: Event) => {
      if ((event as ToggleEvent).newState !== "open") return;
      const header = document.getElementById("site-header");
      const bottom = header?.getBoundingClientRect().bottom ?? 0;
      el.style.setProperty("--season-index-top", `${Math.max(0, bottom)}px`);
    };
    const closeOnLink = (event: MouseEvent) => {
      if ((event.target as Element).closest("a")) el.hidePopover();
    };
    el.addEventListener("beforetoggle", place);
    el.addEventListener("click", closeOnLink);
    return () => {
      el.removeEventListener("beforetoggle", place);
      el.removeEventListener("click", closeOnLink);
    };
  }, []);

  // A client-side navigation keeps the layout mounted, so without this the
  // index would stay open over the page it just opened.
  useEffect(() => {
    const el = panel.current;
    if (el?.matches(":popover-open")) el.hidePopover();
  }, [pathname, searchParams]);

  return <SeasonIndexPanel seasons={seasons} activeKey={activeKey} panelRef={panel} />;
}
