import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-[1400px] px-6 py-24">
      <p className="label">404</p>
      <h1 className="font-display text-5xl leading-none md:text-6xl mt-4">
        Nothing here.
      </h1>
      <p className="mt-5 max-w-[52ch] leading-relaxed text-muted">
        That title or digest isn&rsquo;t in the warehouse. It may have been dropped from a source
        between weekly runs.
      </p>
      <div className="mt-10 flex gap-8">
        <Link href="/" className="label border-b border-accent pb-1 !text-ink">
          Home
        </Link>
        <Link href="/browse" className="label hover:!text-ink transition-colors">
          Browse
        </Link>
      </div>
    </div>
  );
}
