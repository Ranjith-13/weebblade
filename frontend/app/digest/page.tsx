import Link from "next/link";
import { Suspense } from "react";
import { ScrollReveal } from "@/components/motion/ScrollReveal";
import { getDigestDates } from "@/lib/api";

export const metadata = {
  title: "Digest archive",
  description:
    "Every weekly trend digest, written by an LLM from that week's freshly ingested season data.",
};

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

export default function DigestIndexPage() {
  return (
    <div className="mx-auto max-w-[1340px] px-5 py-9 sm:px-7">
      <div className="max-w-[62ch]">
        <h1 className="font-display text-[clamp(2.2rem,6vw,3.4rem)] font-black leading-none">
          Digest archive
        </h1>
        {/* "They are kept unedited" was true until the digest started being
            repunctuated on its way to the page (plainPunctuation in lib/types.ts),
            and then it was the kind of sentence this site keeps catching itself
            in: copy that was accurate when it was written and quietly was not
            any more. The claim worth making is the narrow one, so it can stay
            true. */}
        <p className="mt-4 leading-[1.7] text-ink-soft">
          Each week the pipeline hands that run&rsquo;s aggregates to an LLM and asks for a
          written read on the season. The words are kept as it wrote them, including where a
          week&rsquo;s figures differ from today&rsquo;s; only the punctuation is normalised to
          the house style on the way to this page. Each one is a record of what the pipeline
          knew at the time.
        </p>
      </div>
      <Suspense fallback={<div className="mt-11 h-40 border-t border-rule" />}>
        <DigestList />
      </Suspense>
    </div>
  );
}

async function DigestList() {
  const dates = await getDigestDates();

  if (dates.length === 0) {
    return (
      <p className="mt-11 max-w-[52ch] text-ink-soft">
        No digests have been written yet. The first appears after the pipeline&rsquo;s next
        weekly run.
      </p>
    );
  }

  return (
    <ScrollReveal selector=":scope > ol > li" y={14} stagger={0.06}>
      <ol className="mt-11 border-t-2 border-ink">
      {dates.map((date, i) => (
        <li key={date}>
          <Link
            href={`/digest/${date}`}
            className="group flex flex-wrap items-baseline gap-x-5 gap-y-1 border-b border-rule py-5 transition-colors hover:bg-plate"
          >
            <span className="font-display text-[1.6rem] font-bold leading-tight transition-colors group-hover:text-flag">
              {dateline(date)}
            </span>
            {i === 0 && (
              <span className="border border-flag px-1.5 py-0.5 text-[0.62rem] uppercase tracking-[0.12em] text-flag">
                Latest
              </span>
            )}
          </Link>
        </li>
        ))}
      </ol>
    </ScrollReveal>
  );
}
