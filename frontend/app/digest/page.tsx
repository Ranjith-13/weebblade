import Link from "next/link";
import { getDigestDates } from "@/lib/api";

export const metadata = { title: "Digest archive" };

function formatDate(runDate: string): string {
  const parsed = new Date(`${runDate}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return runDate;
  return parsed.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

export default async function DigestArchivePage() {
  const dates = await getDigestDates();

  return (
    <div className="mx-auto max-w-[1400px] px-6 py-12">
      <div className="max-w-[68ch]">
        <h1 className="font-display text-5xl leading-none md:text-6xl">Digest archive</h1>
        <p className="mt-5 leading-relaxed text-muted">
          Each week the pipeline summarises the freshly ingested season with an LLM, using the
          real aggregates it just computed &mdash; scores, genre counts, format mix &mdash; rather
          than free-associating from a title list.
        </p>
      </div>

      {dates.length === 0 ? (
        <p className="mt-12 text-muted">No digests have been generated yet.</p>
      ) : (
        <ol className="mt-12 border-t border-rule">
          {dates.map((date, i) => (
            <li key={date}>
              <Link
                href={`/digest/${date}`}
                className="group flex items-baseline gap-5 border-b border-rule py-5 hover:bg-raised transition-colors"
              >
                <span className="label tnum w-7 shrink-0">
                  {String(dates.length - i).padStart(2, "0")}
                </span>
                <span className="font-display text-2xl group-hover:text-accent transition-colors">
                  {formatDate(date)}
                </span>
                {i === 0 && <span className="label !text-accent">Latest</span>}
              </Link>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
