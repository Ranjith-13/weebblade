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
  return { title: `Digest, ${formatDate(run_date)}` };
}

/* Shell prerenders; the params-dependent body streams. Cache Components makes
 * reading `params` outside a <Suspense> boundary a prerender error. */
export default function DigestPage(props: PageProps<"/digest/[run_date]">) {
  return (
    <article className="mx-auto max-w-[1340px] px-5 py-9 sm:px-7">
      <Link href="/digest" className="meta inline-block py-2 transition-colors hover:text-flag">
        Back to the archive
      </Link>
      <Suspense
        fallback={
          <div className="mt-8 space-y-4">
            <div className="h-14 w-1/2 bg-plate" />
            <div className="h-4 w-full max-w-[64ch] bg-plate" />
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
      <header className="mt-7 border-b-2 border-ink pb-7">
        <p className="meta">
          Written by an LLM from the week&rsquo;s ingested data
        </p>
        <h1 className="mt-3 font-display text-[clamp(2.2rem,6vw,3.6rem)] font-black leading-[1.02]">
          {formatDate(digest.run_date)}
        </h1>
      </header>

      <div className="digest-prose mt-8 text-[1.02rem]">
        <Markdown>{digest.content}</Markdown>
      </div>
    </>
  );
}
