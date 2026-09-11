import { getCatalogueSummary } from "@/lib/api";
import { SearchClient } from "./SearchClient";

export const metadata = {
  title: "Semantic search",
  description:
    "Search the season by meaning rather than keyword. Queries are embedded and matched against title, genre and synopsis vectors.",
};

export default async function SearchPage() {
  /* Results arrive from /search carrying their own poster, score and format, so
   * they render as real plates with the right certainty treatment and nothing
   * to look up. This page used to hand the client a lookup of the WHOLE
   * catalogue to decorate at most twenty results - every title's name, poster
   * and score in the HTML, 2,755 of them after the backfill - because the index
   * spans every season and a season-sized lookup rendered older hits as
   * unscored. The API does that join now, and all this page needs is the
   * catalogue's size. */
  const { total } = await getCatalogueSummary();

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

      <SearchClient total={total} />
    </div>
  );
}
