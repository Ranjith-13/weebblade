import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-[1340px] px-5 py-20 sm:px-7">
      <p className="stamp">404</p>
      <h1 className="mt-3 font-display text-[clamp(2.2rem,7vw,4rem)] font-black leading-none">
        Not in this season
      </h1>
      <p className="mt-5 max-w-[52ch] leading-[1.7] text-ink-soft">
        WeebBlade only holds the season the pipeline most recently ingested, so an older title
        or a retired digest date will not be here. Nothing is archived beyond what you can
        reach from the two links below.
      </p>
      <div className="mt-8 flex flex-wrap gap-x-7 gap-y-3">
        <Link href="/" className="meta inline-block border-b-2 border-flag py-1.5 transition-colors hover:text-flag">
          The front page
        </Link>
        <Link href="/browse" className="meta inline-block border-b-2 border-rule py-1.5 transition-colors hover:border-flag hover:text-flag">
          Browse the season
        </Link>
      </div>
    </div>
  );
}
