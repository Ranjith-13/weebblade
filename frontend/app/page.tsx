import Link from "next/link";
import Markdown from "react-markdown";
import { PosterGrid } from "@/components/PosterTile";
import { getAnimeList, getLatestDigest } from "@/lib/api";

function formatDateline(runDate: string): string {
  const parsed = new Date(`${runDate}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return runDate;
  return parsed
    .toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" })
    .toUpperCase();
}

function titleCase(value: string) {
  return value.charAt(0) + value.slice(1).toLowerCase();
}

export default async function HomePage() {
  // Independent and both cached server-side (see lib/api.ts) - fetched
  // concurrently rather than waterfalled.
  const [digest, topRated] = await Promise.all([
    getLatestDigest(),
    getAnimeList({ limit: 12, sort: "score_desc" }),
  ]);

  // The digest is prose with no heading of its own, so the season is what
  // anchors the page typographically. Taken from the data rather than the
  // clock - the pipeline decides which season is current, not the browser.
  const lead = topRated.items[0];
  const seasonLabel =
    lead?.season && lead.season_year
      ? `${titleCase(lead.season)} ${lead.season_year}`
      : "This season";

  return (
    <div className="mx-auto max-w-[1400px] px-6">
      <section className="border-b border-rule py-14 md:py-20">
        <div className="grid gap-x-16 gap-y-10 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
          {/* Left rail: the dateline and the provenance of the number. Kept as
              typography rather than stat cards - the figures are the point. */}
          <div className="lg:sticky lg:top-10 lg:self-start">
            <h1 className="font-display text-6xl leading-[0.95] md:text-7xl">
              {seasonLabel}
            </h1>
            {digest && (
              <p className="label mt-6 !leading-[1.7]">
                Week of {formatDateline(digest.run_date)}
              </p>
            )}
            <dl className="mt-8 border-t border-rule">
              {[
                ["Titles tracked", topRated.total.toLocaleString()],
                ["Sources", "3"],
                ["Refreshed", "Weekly"],
              ].map(([term, value]) => (
                <div
                  key={term}
                  className="flex items-baseline justify-between border-b border-rule py-2.5"
                >
                  <dt className="label">{term}</dt>
                  <dd className="tnum text-sm">{value}</dd>
                </div>
              ))}
            </dl>
          </div>

          {/* Right: the digest itself, the actual centrepiece. */}
          <div>
            {digest ? (
              <>
                <p className="label">
                  <span className="text-accent">●</span> Written by an LLM from the week&rsquo;s
                  ingested data
                </p>
                <div className="digest-prose mt-6 text-[1.05rem] text-ink/90">
                  <Markdown>{digest.content}</Markdown>
                </div>
                <Link
                  href="/digest"
                  className="label mt-10 inline-block border-b border-accent pb-1 !text-ink"
                >
                  Digest archive
                </Link>
              </>
            ) : (
              <div className="digest-prose">
                <p className="label">No digest yet</p>
                <p className="mt-5 text-muted leading-relaxed">
                  The pipeline writes one each week from the freshly ingested season. The
                  catalogue below is live in the meantime.
                </p>
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="py-14">
        <div className="flex items-baseline justify-between gap-6">
          <h2 className="label">Top rated this season</h2>
          <Link href="/browse" className="label hover:!text-ink transition-colors">
            All <span className="tnum">{topRated.total}</span> titles →
          </Link>
        </div>
        <div className="mt-7">
          <PosterGrid items={topRated.items} />
        </div>
      </section>
    </div>
  );
}
