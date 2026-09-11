import Link from "next/link";
import { SEASON_INDEX_ID } from "@/lib/types";

/* This used to say "Not in this season" and that WeebBlade only holds the
 * season most recently ingested. That stopped being true with the first
 * backfill, and a 404 is exactly where someone following an old link to an
 * older title reads it. What is true now: every season on file is one click
 * away, and a title that has an address keeps it - a merge or a change of
 * source redirects, it does not break. */
export default function NotFound() {
  return (
    <div className="mx-auto max-w-[1340px] px-5 py-20 sm:px-7">
      <p className="stamp">404</p>
      <h1 className="mt-3 font-display text-[clamp(2.2rem,7vw,4rem)] font-black leading-none">
        Nothing at this address
      </h1>
      <p className="mt-5 max-w-[52ch] leading-[1.7] text-ink-soft">
        No title, season or digest lives here. A title keeps its address once it has one, so a
        link that led here was mistyped or points to something the pipeline has not ingested.
      </p>
      <div className="mt-8 flex flex-wrap gap-x-7 gap-y-3">
        <Link href="/" className="meta inline-block border-b-2 border-flag py-1.5 transition-colors hover:text-flag">
          The front page
        </Link>
        <button
          type="button"
          popoverTarget={SEASON_INDEX_ID}
          className="meta inline-block border-b-2 border-rule py-1.5 transition-colors hover:border-flag hover:text-flag"
        >
          Every season on file
        </button>
        <Link href="/search" className="meta inline-block border-b-2 border-rule py-1.5 transition-colors hover:border-flag hover:text-flag">
          Search by meaning
        </Link>
      </div>
    </div>
  );
}
