"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { SEASON_INDEX_ID } from "@/lib/types";

/* The site's five sections. "Seasons" is a button, not a link: it opens the
 * season index (components/SeasonIndex.tsx), because the answer to "which
 * season?" has to come before the catalogue can mean anything. The warehouse
 * holds years of them, and the old "The season" link pointed at one without ever
 * saying there were others. */
type Section = "seasons" | "schedule" | "changes" | "search" | "digest";

const LINKS = [
  { key: "schedule", href: "/schedule", label: "Schedule" },
  { key: "changes", href: "/changes", label: "Changes" },
  { key: "search", href: "/search", label: "Search" },
  { key: "digest", href: "/digest", label: "Digest" },
] as const;

function sectionOf(pathname: string): Section | null {
  if (pathname === "/browse") return "seasons";
  if (pathname.startsWith("/schedule")) return "schedule";
  if (pathname.startsWith("/changes")) return "changes";
  if (pathname.startsWith("/search")) return "search";
  if (pathname.startsWith("/digest")) return "digest";
  return null;
}

/* The current section's marker is a flag bar laid over the header's ink rule
 * rather than an underline floating under the word: -mb-[2px] pulls each item's
 * 2px border down onto the rule, so the active one reads as a tab cut into the
 * masthead. Hover only changes the text, so hovering never looks like arriving. */
const item =
  "-mb-[2px] inline-flex items-center gap-1.5 border-b-2 pt-3 pb-[0.7rem] text-[0.875rem] transition-colors duration-150 hover:text-flag";

function itemState(active: boolean) {
  return active ? "border-flag font-semibold text-ink" : "border-transparent text-ink-soft";
}

/** Presentational. Rendered with `active={null}` as the Suspense fallback on
 *  routes whose pathname is unknown at prerender (a title, a dated digest). */
export function NavList({ active }: { active: Section | null }) {
  return (
    <nav aria-label="Primary" className="self-end">
      {/* THE GAP IS A BUDGET, not a preference. Five items at 0.875rem measure
          334-340px with these gaps; the container offers 350 at 390px wide
          (max-w minus the px-5 gutters). At the previous gap-x-5 the row
          measured 366-372 and had been overflowing its container on every
          route, spilling past the viewport on /schedule (392) and /search
          (391) with /changes exactly on the line at 390. It read as fitting
          because it does sit on one line - it simply did so by hanging off the
          edge, and nothing measured the document's scroll width until the
          smoke suite started to.

          The width also moves with the route, which is why this surfaced on
          one page and not another: the active item is semibold, and "Schedule"
          in semibold is 6px wider than no marker at all. The budget absorbs
          that now rather than depending on which word is longest.

          20px fits again from 412px up, so the step back to it is at 420. */}
      <ul className="flex gap-x-3 min-[420px]:gap-x-5 sm:gap-x-7">
        <li>
          <button
            type="button"
            popoverTarget={SEASON_INDEX_ID}
            aria-current={active === "seasons" ? "page" : undefined}
            className={`season-index-toggle ${item} ${itemState(active === "seasons")}`}
          >
            Seasons
            <svg
              aria-hidden
              viewBox="0 0 10 10"
              className="h-2.5 w-2.5 transition-transform duration-150"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            >
              <path d="M1.5 3.5 5 7l3.5-3.5" />
            </svg>
          </button>
        </li>
        {LINKS.map((link) => (
          <li key={link.key}>
            <Link
              href={link.href}
              data-pressable
              aria-current={active === link.key ? "page" : undefined}
              className={`${item} ${itemState(active === link.key)}`}
            >
              {link.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function PrimaryNav() {
  return <NavList active={sectionOf(usePathname())} />;
}
