import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import Markdown from "react-markdown";
import { getDigest } from "@/lib/api";

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

export async function generateMetadata(props: PageProps<"/digest/[run_date]">) {
  const { run_date } = await props.params;
  return { title: `Digest — ${formatDate(run_date)}` };
}

/* Shell prerenders; the params-dependent body streams. Cache Components makes
 * reading `params` outside a <Suspense> boundary a prerender error. */
export default function DigestPage(props: PageProps<"/digest/[run_date]">) {
  return (
    <article className="mx-auto max-w-[1400px] px-6 py-12">
      <Link href="/digest" className="label hover:!text-ink transition-colors">
        ← Archive
      </Link>
      <Suspense
        fallback={
          <div className="mt-8 space-y-4">
            <div className="h-14 w-1/2 bg-raised" />
            <div className="h-4 w-full max-w-[68ch] bg-raised" />
          </div>
        }
      >
        <DigestBody params={props.params} />
      </Suspense>
    </article>
  );
}

async function DigestBody({
  params,
}: {
  params: PageProps<"/digest/[run_date]">["params"];
}) {
  const { run_date } = await params;
  const digest = await getDigest(run_date);

  if (!digest) notFound();

  return (
    <>
      <header className="mt-8 border-b border-rule pb-8">
        <p className="label">
          <span className="text-accent">●</span> Written by an LLM from the week&rsquo;s ingested data
        </p>
        <h1 className="font-display text-5xl leading-[1.05] md:text-6xl mt-4">
          {formatDate(digest.run_date)}
        </h1>
      </header>

      <div className="digest-prose mt-10 text-[1.05rem] text-ink/90">
        <Markdown>{digest.content}</Markdown>
      </div>
    </>
  );
}
