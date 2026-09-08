import { SearchClient } from "./SearchClient";

export const metadata = {
  title: "Semantic search",
  description:
    "Search the season by meaning rather than keyword - queries are embedded and matched against title, genre and synopsis vectors.",
};

export default function SearchPage() {
  return (
    <div className="mx-auto max-w-[1400px] px-6 py-12">
      <div className="max-w-[68ch]">
        <h1 className="font-display text-5xl leading-none md:text-6xl">Semantic search</h1>
        <p className="mt-5 leading-relaxed text-muted">
          Queries are embedded with a sentence-transformers model and matched against vectors
          built from each title&rsquo;s name, genres and synopsis. Describe what you want rather
          than naming it &mdash; &ldquo;quiet show about cooking&rdquo; works better here than it
          would in a keyword search.
        </p>
      </div>

      <SearchClient />
    </div>
  );
}
