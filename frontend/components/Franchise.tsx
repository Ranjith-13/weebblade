import { getFranchise } from "@/lib/api";
import { FranchiseList } from "./FranchiseList";

/* The rest of a title's story: its franchise from MAL's related titles, oldest
 * first. See processing/franchise.py for what joins a franchise and what does
 * not - shared characters and MAL's "other" links do not.
 *
 * Entries the catalogue does not hold are still listed, from MAL's own
 * description, because the prequel from before the catalogue's first season is
 * exactly what someone reading the sequel wants to know exists. They link to
 * MyAnimeList and say so.
 *
 * Streams on its own, below everything else on the page, and a failure renders
 * nothing: a title page must never be taken down by its franchise. A title in
 * no franchise - most one-offs, every music video - gets no section at all. */
export async function FranchiseSection({ wbId }: { wbId: string }) {
  let entries;
  try {
    entries = (await getFranchise(wbId)).entries;
  } catch {
    return null;
  }
  if (entries.length < 2) return null;
  const held = entries.filter((e) => e.wb_id).length;

  return (
    <section aria-labelledby="franchise-title" className="mt-14 border-t-2 border-ink pt-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h2 id="franchise-title" className="font-display text-2xl font-bold">
          In this franchise
        </h2>
        <p className="meta">
          <span className="tnum">{entries.length}</span> entries,{" "}
          <span className="tnum">{held}</span> in the catalogue
        </p>
      </div>
      <FranchiseList entries={entries} />
      {held < entries.length && (
        <p className="meta mt-4 max-w-[60ch] !leading-[1.6]">
          Entries the catalogue does not hold are listed as MyAnimeList describes them, and link
          there.
        </p>
      )}
    </section>
  );
}
