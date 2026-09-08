import Link from "next/link";
import { Suspense } from "react";
import { PosterGrid } from "@/components/PosterTile";
import { getAnimeList } from "@/lib/api";
import type { AnimeQuery } from "@/lib/types";

export const metadata = { title: "Browse" };

const PAGE_SIZE = 24;

const SORTS = [
  { value: "score_desc", label: "Score" },
  { value: "popularity_desc", label: "Popularity" },
  { value: "title", label: "Title" },
] as const;

// Formats as the sources actually spell them - Kitsu returns lowercase subtypes
// ("TV", "ONA", "movie"), matched case-insensitively server-side (see
// backend/app/routers/anime.py), so these only need to be recognisable here.
const FORMATS = ["TV", "ONA", "movie", "special", "OVA", "music"] as const;

/** Hardcoded rather than derived: the API has no distinct-genres endpoint, and
 *  fetching every title just to populate a filter would spend the shared
 *  rate-limit budget on a dropdown. These are the highest-volume tags in the
 *  live data. */
const GENRES = [
  "Action",
  "Adventure",
  "Comedy",
  "Drama",
  "Fantasy",
  "Romance",
  "Sci-Fi",
  "Slice of Life",
  "Supernatural",
  "Isekai",
  "Mystery",
  "Music",
] as const;

type Current = Record<string, string | undefined>;

function buildHref(current: Current, patch: Current) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries({ ...current, ...patch })) {
    if (value) params.set(key, value);
  }
  const qs = params.toString();
  return qs ? `/browse?${qs}` : "/browse";
}

/* The page shell is static and prerenders; everything that depends on
 * searchParams lives inside <Suspense> below. Cache Components requires this -
 * reading searchParams outside a boundary makes the whole route unprerenderable
 * and blocks the initial paint on an upstream round-trip. */
export default function BrowsePage(props: PageProps<"/browse">) {
  return (
    <div className="mx-auto max-w-[1400px] px-6 py-12">
      <h1 className="font-display text-5xl leading-none">Browse</h1>
      <Suspense fallback={<BrowseSkeleton />}>
        <BrowseResults searchParams={props.searchParams} />
      </Suspense>
    </div>
  );
}

function BrowseSkeleton() {
  return (
    <>
      <div className="mt-10 h-[8.5rem] border-y border-rule" />
      <div className="mt-10 grid grid-cols-2 gap-x-4 gap-y-7 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
        {Array.from({ length: 12 }).map((_, i) => (
          <div key={i} className="aspect-[3/4] border border-rule bg-raised" />
        ))}
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

  const current: Current = {
    genre: read("genre"),
    format: read("format"),
    sort: read("sort") ?? "score_desc",
    page: read("page"),
  };

  const page = Math.max(1, Number(current.page ?? "1") || 1);
  const query: AnimeQuery = {
    genre: current.genre,
    format: current.format,
    sort: (current.sort as AnimeQuery["sort"]) ?? "score_desc",
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  };

  const data = await getAnimeList(query);
  const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  const hasFilters = Boolean(current.genre || current.format);

  return (
    <>
      <p className="label mt-3">
        <span className="tnum">{data.total.toLocaleString()}</span> titles
        {hasFilters ? " matching" : ""}
      </p>

      <div className="mt-8 space-y-5 border-y border-rule py-6">
        <FilterRow label="Genre">
          <FilterLink
            href={buildHref(current, { genre: undefined, page: undefined })}
            active={!current.genre}
          >
            All
          </FilterLink>
          {GENRES.map((genre) => (
            <FilterLink
              key={genre}
              href={buildHref(current, { genre, page: undefined })}
              active={current.genre === genre}
            >
              {genre}
            </FilterLink>
          ))}
        </FilterRow>

        <FilterRow label="Format">
          <FilterLink
            href={buildHref(current, { format: undefined, page: undefined })}
            active={!current.format}
          >
            All
          </FilterLink>
          {FORMATS.map((format) => (
            <FilterLink
              key={format}
              href={buildHref(current, { format, page: undefined })}
              active={current.format === format}
            >
              {format}
            </FilterLink>
          ))}
        </FilterRow>

        <FilterRow label="Sort">
          {SORTS.map((sort) => (
            <FilterLink
              key={sort.value}
              href={buildHref(current, { sort: sort.value, page: undefined })}
              active={current.sort === sort.value}
            >
              {sort.label}
            </FilterLink>
          ))}
        </FilterRow>
      </div>

      {data.items.length === 0 ? (
        <p className="mt-16 text-muted">
          Nothing matches that combination.{" "}
          <Link href="/browse" className="text-accent underline underline-offset-4">
            Clear filters
          </Link>
          .
        </p>
      ) : (
        <div className="mt-10">
          <PosterGrid items={data.items} />
        </div>
      )}

      {totalPages > 1 && (
        <nav className="mt-16 flex items-center justify-between border-t border-rule pt-6">
          {page > 1 ? (
            <Link
              href={buildHref(current, { page: String(page - 1) })}
              className="label hover:!text-ink"
            >
              ← Previous
            </Link>
          ) : (
            <span className="label opacity-30">← Previous</span>
          )}

          <span className="label tnum">
            Page {page} of {totalPages}
          </span>

          {page < totalPages ? (
            <Link
              href={buildHref(current, { page: String(page + 1) })}
              className="label hover:!text-ink"
            >
              Next →
            </Link>
          ) : (
            <span className="label opacity-30">Next →</span>
          )}
        </nav>
      )}
    </>
  );
}

function FilterRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-5 gap-y-2">
      <span className="label w-16 shrink-0">{label}</span>
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">{children}</div>
    </div>
  );
}

/* Filters are links, not client state: the page ships no JS for filtering, and
   every filtered view gets a real shareable, back-button-able URL. */
function FilterLink({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={
        active
          ? "text-sm text-ink border-b border-accent pb-0.5"
          : "text-sm text-muted hover:text-ink transition-colors border-b border-transparent pb-0.5"
      }
    >
      {children}
    </Link>
  );
}
