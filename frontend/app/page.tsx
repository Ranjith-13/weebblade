import Link from "next/link";
import { Suspense } from "react";
import Markdown from "react-markdown";
import { PlateGrid, PlateGridSkeleton } from "@/components/Plate";
import { ProvenanceLines } from "@/components/Provenance";
import { getLatestDigest, getSeason, getSeasons } from "@/lib/api";
import { MastheadScroll } from "@/components/motion/MastheadScroll";
import { PinnedAside } from "@/components/motion/PinnedAside";
import { ScrollReveal } from "@/components/motion/ScrollReveal";
import { halftone } from "@/lib/design-tokens";
import { byScoreThenPopularity, isTv, SEASON_INDEX_ID } from "@/lib/types";

function dateline(runDate: string): string {
  const parsed = new Date(`${runDate}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return runDate;
  return parsed.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

export default function HomePage() {
  return (
    <div className="mx-auto max-w-[1340px] px-5 sm:px-7">
      <Suspense fallback={<HomeSkeleton />}>
        <Home />
      </Suspense>
    </div>
  );
}

function HomeSkeleton() {
  return (
    <div className="py-10">
      <div className="h-24 w-2/3 bg-plate" />
      <div className="mt-8 h-20 border-y border-rule" />
      <div className="mt-10">
        <PlateGridSkeleton />
      </div>
    </div>
  );
}

async function Home() {
  const [digest, season, seasons] = await Promise.all([
    getLatestDigest(),
    getSeason(),
    getSeasons(),
  ]);

  /* TV only, matching what /browse defaults to. Ranking the whole season put
     music videos and shorts in a list headed "rated highest", which they can
     never be: 0% of music videos carry a score. */
  const featured = season.items.filter(isTv).sort(byScoreThenPopularity).slice(0, 12);

  /* The digest runs ~700 words. The previous build printed all of it above the
     catalogue, which on a phone was roughly four screens of unbroken prose
     before a single poster. Here the lead paragraph carries the page and the
     rest is one click away, so the season itself is reachable immediately. */
  const paragraphs = digest?.content.split(/\n{2,}/).filter((p) => p.trim()) ?? [];
  const lead = paragraphs[0] ?? "";
  const hasMore = paragraphs.length > 1;

  return (
    <>
      <section className="border-b-2 border-ink pt-9 pb-5 sm:pt-12">
        <MastheadScroll>
          <div className="flex flex-wrap items-end justify-between gap-x-10 gap-y-4">
            {/* Each line sits in its own overflow-hidden strip so the entrance
                reads as type rising off the press rather than a block fading
                in. pb clearance stops the didone's fine terminals clipping
                against the mask edge. */}
            <h1 className="font-display text-[clamp(2.9rem,10vw,5.6rem)] font-black leading-[0.86] tracking-[-0.025em]">
              {season.label ? (
                <>
                  <span className="block overflow-hidden pb-[0.04em]">
                    <span data-mast-line className="block">
                      {season.label.split(" ")[0]}
                    </span>
                  </span>
                  <span className="block overflow-hidden pb-[0.04em]">
                    <span data-mast-line className="block text-flag">
                      {season.label.split(" ")[1]}
                    </span>
                  </span>
                </>
              ) : (
                "This season"
              )}
            </h1>
            <p data-mast-meta className="meta text-right leading-[1.8]">
              {digest ? `Week of ${dateline(digest.run_date)}` : "Awaiting first digest"}
              <br />
              <Suspense fallback={null}>
                <ProvenanceLines />
              </Suspense>
              {/* The masthead names one season in the largest type on the site,
                  which read as though it were the only one. */}
              {seasons.length > 1 && (
                <>
                  <br />
                  <button
                    type="button"
                    popoverTarget={SEASON_INDEX_ID}
                    className="inline-block py-1 underline decoration-rule underline-offset-4 transition-colors hover:text-flag"
                  >
                    All {seasons.length} seasons
                  </button>
                </>
              )}
            </p>
          </div>
        </MastheadScroll>
      </section>

      {/* Counts stated as they actually are, and derived from the full season
          rather than from one unstably-paginated page. The old rail claimed
          "Sources 3" when two of the three are down upstream, and reported a
          title count that changed between refreshes. */}
      {/* Leads with TV because that is what the site shows by default, and states
          the rest of the ingest beside it rather than folding a season's music
          videos into a single headline number - 27 of 142 titles then, 59 of 237
          in Summer 2026. The rail used to say "142 titles, 39 rated" - true, but
          it described the ingest, not the anime. */}
      <ScrollReveal selector=":scope > dl > div" y={12} stagger={0.07} start="top 92%">
        <dl className="grid grid-cols-2 border-b border-rule sm:grid-cols-4">
          <Stat term="TV series" value={season.tvTotal} />
          <Stat term="Rated" value={season.tvScored} of={season.tvTotal} />
          <Stat term="Airing now" value={season.tvAiring} />
          <Stat term="Beyond TV" value={season.nonTvTotal} />
        </dl>
      </ScrollReveal>

      <section className="border-b border-rule py-9">
        <div>
          {digest ? (
            <>
              <p className="meta mb-4">
                Written by an LLM from this week&rsquo;s ingested data
              </p>
              <div className="digest-prose text-[1.02rem]">
                <Markdown>{lead}</Markdown>
              </div>
              {hasMore && (
                <Link
                  href={`/digest/${digest.run_date}`}
                  className="mt-6 inline-block border-b-2 border-flag pb-0.5 text-[0.85rem] font-medium transition-colors hover:text-flag"
                >
                  Read the full digest ({paragraphs.length - 1} more{" "}
                  {paragraphs.length === 2 ? "paragraph" : "paragraphs"})
                </Link>
              )}
              {/* The digest quotes the figures from its own run, which will not
                  always match today's rail - when this was written, 140 where
                  the season held 142. Saying so is cheaper and more honest
                  than quietly letting two numbers disagree on one page. */}
              <p className="meta mt-3 max-w-[54ch] !leading-[1.6]">
                Figures inside the digest are as written at that run and may differ from
                the counts above
              </p>
            </>
          ) : (
            <div className="digest-prose">
              <p className="meta">No digest yet</p>
              <p className="mt-4 leading-relaxed text-ink-soft">
                The pipeline writes one each week from the freshly ingested season. The
                catalogue below is live in the meantime.
              </p>
            </div>
          )}
        </div>

      </section>

      <section className="py-9">
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <h2 className="font-display text-2xl font-bold">Rated highest this season</h2>
          <Link
            href="/browse"
            className="meta inline-block border-b border-rule py-1.5 transition-colors hover:border-flag hover:text-flag"
          >
            All <span className="tnum">{season.tvTotal}</span> TV series
          </Link>
        </div>

        {/* The key now sits beside the plates it explains and is pinned while
            they scroll past. It moved here from the digest block for exactly
            that reason: a legend is only useful next to the thing it decodes. */}
        <p className="meta mt-2">
          <Link
            href="/browse?format=all"
            className="inline-block py-1.5 underline decoration-rule underline-offset-4 transition-colors hover:text-flag"
          >
            Films, ONAs, specials and music videos are here too
          </Link>
        </p>

        <div className="mt-6 grid gap-x-10 gap-y-8 lg:grid-cols-[15rem_minmax(0,1fr)]">
          <PinnedAside>
            <h2 className="meta mb-3">How to read this</h2>
            <ul className="space-y-3 text-[0.82rem] leading-[1.55]">
              <li className="flex gap-3">
                <span className="mt-0.5 h-4 w-4 shrink-0 border border-ink bg-flag" />
                <span>
                  <b className="font-semibold">In colour.</b> The pipeline has a score for
                  this title.
                </span>
              </li>
              <li className="flex gap-3">
                <span className="mt-0.5 h-4 w-4 shrink-0 border border-ink" style={halftone} />
                <span>
                  <b className="font-semibold">Screened back.</b> No score upstream.{" "}
                  {Math.round(((season.tvTotal - season.tvScored) / season.tvTotal) * 100)}% of
                  TV series. Hover one to lift the screen.
                </span>
              </li>
            </ul>
          </PinnedAside>

          <ScrollReveal selector=":scope > div > a" stagger={0.05}>
            <PlateGrid items={featured} columns="lg:grid-cols-3 xl:grid-cols-4" />
          </ScrollReveal>
        </div>
      </section>
    </>
  );
}

function Stat({ term, value, of }: { term: string; value: number; of?: number }) {
  return (
    <div className="border-r border-rule py-4 pr-4 last:border-r-0">
      <dt className="stamp mb-1.5">{term}</dt>
      <dd className="font-display text-[1.7rem] font-bold leading-none tnum">
        {value.toLocaleString()}
        {of !== undefined && (
          <span className="ml-1 font-sans text-[0.72rem] font-medium text-ink-soft">
            / {of.toLocaleString()}
          </span>
        )}
      </dd>
    </div>
  );
}
