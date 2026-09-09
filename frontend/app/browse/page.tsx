import Link from "next/link";
import { Suspense } from "react";
import { PlateGrid, PlateGridSkeleton } from "@/components/Plate";
import { ScrollReveal } from "@/components/motion/ScrollReveal";
import { getFacets, getSeason } from "@/lib/api";
import { formatLabel, isKnown, sortAnime, SORTS, type SortKey } from "@/lib/types";

export const metadata = { title: "The season" };

const PAGE_SIZE = 30;

type Current = Record<string, string | undefined>;

function buildHref(current: Current, patch: Current) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries({ ...current, ...patch })) {
    if (value) params.set(key, value);
  }
  const qs = params.toString();
  return qs ? `/browse?${qs}` : "/browse";
}

/* The shell is static and prerenders; everything reading searchParams sits
 * inside <Suspense>. Cache Components requires this — reading searchParams
 * outside a boundary makes the route unprerenderable and blocks first paint. */
export default function BrowsePage(props: PageProps<"/browse">) {
  return (
    <div className="mx-auto max-w-[1340px] px-5 py-9 sm:px-7">
      <h1 className="font-display text-[clamp(2.2rem,6vw,3.4rem)] font-black leading-none">
        The season
      </h1>
      <Suspense fallback={<BrowseSkeleton />}>
        <BrowseResults searchParams={props.searchParams} />
      </Suspense>
    </div>
  );
}

function BrowseSkeleton() {
  return (
    <>
      <div className="mt-8 h-32 border-y border-rule" />
      <div className="mt-9">
        <PlateGridSkeleton count={18} />
      </div>
    </>
  );
}

async function BrowseResults({
  searchParams,
}: {
  searchParams: PageProps<"/browse">["searchParams"];
}) {
  const sp = await searchParams;
  const read = (key: string) => {
    const raw = sp[key];
    const value = Array.isArray(raw) ? raw[0] : raw;
    return value || undefined;
  };

  const [season, facets] = await Promise.all([getSeason(), getFacets()]);

  const sortKey: SortKey = (["score", "popularity", "title"] as const).includes(
    read("sort") as SortKey,
  )
    ? (read("sort") as SortKey)
    : "score";

  const current: Current = {
    genre: read("genre"),
    format: read("format"),
    service: read("service"),
    rated: read("rated"),
    sort: sortKey,
    page: read("page"),
  };

  /* Filtering happens here rather than upstream because the whole season is
     already in memory and deduped — see lib/api.ts. It also lets "Rated only"
     exist at all: the API has a min_score parameter but no way to ask for
     "has any score", which is the distinction that matters when three quarters of
     the catalogue has none. */
  let items = season.items;
  if (current.genre) {
    const g = current.genre.toLowerCase();
    items = items.filter((a) => a.genres.some((x) => x.toLowerCase() === g));
  }
  if (current.format) {
    const f = current.format.toLowerCase();
    items = items.filter((a) => (a.format ?? "").toLowerCase() === f);
  }
  if (current.service) {
    const svc = current.service.toLowerCase();
    items = items.filter((a) =>
      (a.streaming_services ?? []).some((x) => x.toLowerCase() === svc),
    );
  }
  if (current.rated === "1") items = items.filter(isKnown);

  items = sortAnime(items, sortKey);

  const page = Math.max(1, Number(current.page ?? "1") || 1);
  const totalPages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  const clamped = Math.min(page, totalPages);
  const visible = items.slice((clamped - 1) * PAGE_SIZE, clamped * PAGE_SIZE);
  const hasFilters = Boolean(
    current.genre || current.format || current.service || current.rated,
  );
  const scoredHere = items.filter(isKnown).length;

  return (
    <>
      <p className="mt-3 text-[0.85rem] text-ink-soft">
        <span className="tnum font-semibold text-ink">{items.length.toLocaleString()}</span>{" "}
        {hasFilters ? "matching" : "titles"},{" "}
        <span className="tnum">{scoredHere.toLocaleString()}</span> of them rated
        {hasFilters && (
          <>
            {". "}
            <Link href="/browse" className="text-data underline underline-offset-4">
              Clear filters
            </Link>
          </>
        )}
      </p>

      <div className="mt-7 space-y-4 border-y border-rule py-5">
        <FilterRow label="Genre">
          <Chip href={buildHref(current, { genre: undefined, page: undefined })} active={!current.genre}>
            All
          </Chip>
          {/* Derived from the live data with real counts. The previous build
              hardcoded this list and it had drifted: "Sci-Fi" matched nothing,
              because the tag is actually "Science Fiction". */}
          {facets.genres.map((g) => (
            <Chip
              key={g.value}
              href={buildHref(current, { genre: g.value, page: undefined })}
              active={current.genre === g.value}
              count={g.count}
            >
              {g.value}
            </Chip>
          ))}
        </FilterRow>

        <FilterRow label="Format">
          <Chip href={buildHref(current, { format: undefined, page: undefined })} active={!current.format}>
            All
          </Chip>
          {facets.formats.map((f) => (
            <Chip
              key={f.value}
              href={buildHref(current, { format: f.value, page: undefined })}
              active={current.format === f.value}
              count={f.count}
            >
              {formatLabel(f.value)}
            </Chip>
          ))}
        </FilterRow>

        {facets.services.length > 0 && (
          <FilterRow label="Watch on">
            <Chip
              href={buildHref(current, { service: undefined, page: undefined })}
              active={!current.service}
            >
              Anywhere
            </Chip>
            {facets.services.map((sv) => (
              <Chip
                key={sv.value}
                href={buildHref(current, { service: sv.value, page: undefined })}
                active={current.service === sv.value}
                count={sv.count}
              >
                {sv.value}
              </Chip>
            ))}
          </FilterRow>
        )}

        <FilterRow label="Sort">
          {SORTS.map((s) => (
            <Chip
              key={s.key}
              href={buildHref(current, { sort: s.key, page: undefined })}
              active={sortKey === s.key}
              title={s.hint}
            >
              {s.label}
            </Chip>
          ))}
          <span className="mx-1 h-4 w-px bg-rule" aria-hidden />
          <Chip
            href={buildHref(current, {
              rated: current.rated === "1" ? undefined : "1",
              page: undefined,
            })}
            active={current.rated === "1"}
            title="Hide titles with no score upstream"
          >
            Rated only
          </Chip>
        </FilterRow>
      </div>

      {visible.length === 0 ? (
        <div className="mt-14 max-w-prose">
          <p className="font-display text-2xl font-bold">Nothing matches that.</p>
          <p className="mt-2 text-ink-soft">
            The season is only {season.total} titles from a single source, so narrow
            combinations run out quickly.{" "}
            <Link href="/browse" className="text-data underline underline-offset-4">
              Clear the filters
            </Link>
            .
          </p>
        </div>
      ) : (
        <ScrollReveal className="mt-9" selector=":scope > div > a" stagger={0.035}>
          <PlateGrid items={visible} />
        </ScrollReveal>
      )}

      {totalPages > 1 && (
        <nav
          aria-label="Pagination"
          className="mt-14 flex items-center justify-between border-t border-rule pt-5"
        >
          {clamped > 1 ? (
            <Link
              href={buildHref(current, { page: String(clamped - 1) })}
              className="meta inline-block py-2 transition-colors hover:text-flag"
            >
              Previous
            </Link>
          ) : (
            <span className="meta inline-block py-2 opacity-35">Previous</span>
          )}
          <span className="meta tnum">
            Page {clamped} of {totalPages}
          </span>
          {clamped < totalPages ? (
            <Link
              href={buildHref(current, { page: String(clamped + 1) })}
              className="meta inline-block py-2 transition-colors hover:text-flag"
            >
              Next
            </Link>
          ) : (
            <span className="meta inline-block py-2 opacity-35">Next</span>
          )}
        </nav>
      )}
    </>
  );
}

function FilterRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
      <span className="stamp w-14 shrink-0">{label}</span>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-2">{children}</div>
    </div>
  );
}

/* Filters stay links, not client state: the page ships no JS for filtering and
   every view has a real shareable, back-button-able URL. */
function Chip({
  href,
  active,
  count,
  title,
  children,
}: {
  href: string;
  active: boolean;
  count?: number;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      title={title}
      aria-current={active ? "true" : undefined}
      className={[
        "inline-block border-b-2 py-1.5 text-[0.82rem] transition-colors duration-150",
        active
          ? "border-flag font-semibold text-ink"
          : "border-transparent text-ink-soft hover:border-rule hover:text-ink",
      ].join(" ")}
    >
      {children}
      {count !== undefined && <span className="tnum ml-1 text-[0.7rem] opacity-60">{count}</span>}
    </Link>
  );
}
