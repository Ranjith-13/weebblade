import { getSeason } from "@/lib/api";
import { displayTitle } from "@/lib/types";
import { SearchClient, type PlateLite } from "./SearchClient";

export const metadata = {
  title: "Semantic search",
  description:
    "Search the season by meaning rather than keyword. Queries are embedded and matched against title, genre and synopsis vectors.",
};

export default async function SearchPage() {
  /* The /search endpoint returns only title, ids and a distance — no artwork,
   * no score, no format. The old results list was therefore plain text and raw
   * floats, which made the most visual entity in the product its least visual
   * surface. The whole season is already cached server-side, so we hand the
   * client a small lookup and join against it locally: real plates, correct
   * certainty treatment, and not one extra upstream request. */
  const season = await getSeason();
  const lookup: Record<string, PlateLite> = {};
  for (const a of season.items) {
    lookup[`${a.source}:${a.source_id}`] = {
      t: displayTitle(a),
      p: a.poster_url,
      s: a.score_100,
      f: a.format,
      c: a.status === "current",
    };
  }

  return (
    <div className="mx-auto max-w-[1340px] px-5 py-9 sm:px-7">
      <div className="max-w-[62ch]">
        <h1 className="font-display text-[clamp(2.2rem,6vw,3.4rem)] font-black leading-none">
          Search by meaning
        </h1>
        <p className="mt-4 leading-[1.7] text-ink-soft">
          Your words are turned into a vector by a sentence-transformers model and matched
          against vectors built from each title&rsquo;s name, genres and synopsis. Describe what
          you want rather than naming it &mdash; &ldquo;quiet show about cooking&rdquo; works
          here in a way it would not in a keyword search.
        </p>
      </div>

      <SearchClient lookup={lookup} total={season.total} />
    </div>
  );
}
