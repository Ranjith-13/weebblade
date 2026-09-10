import Link from "next/link";
import { Suspense } from "react";
import { PlateGrid, PlateGridSkeleton } from "@/components/Plate";
import { ScrollReveal } from "@/components/motion/ScrollReveal";
import { getCatalogue, getFacets, getSeason, getSeasons } from "@/lib/api";
import {
  DEFAULT_FORMAT,
  FORMAT_ALL,
  formatLabel,
  isKnown,
  resolveFormat,
  sortAnime,
  SORTS,
  sourceMaterialLabel,
  type SortKey,
} from "@/lib/types";

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

  // The season is chosen before anything else, because every facet and count
  // below is scoped to it. Absent means the newest season the warehouse holds,
  // so a backfill of an older season never changes what the bare URL shows.
  const seasonParam = read("season");
  const [season, facets, seasons, catalogue] = await Promise.all([
    getSeason(seasonParam),
    getFacets(seasonParam),
    getSeasons(),
    getCatalogue(),
  ]);

  const sortKey: SortKey = (["score", "popularity", "title"] as const).includes(
    read("sort") as SortKey,
  )
    ? (read("sort") as SortKey)
    : "score";

  const current: Current = {
    season: seasonParam,
    genre: read("genre"),
    format: read("format"),
    service: read("service"),
    material: read("material"),
    studio: read("studio"),
    rated: read("rated"),
    sort: sortKey,
    page: read("page"),
  };

  /* Filtering happens here rather than upstream because the whole season is
     already in memory and deduped — see lib/api.ts. It also lets "Rated only"
     exist at all: the API has a min_score parameter but no way to ask for
     "has any score", which is the distinction that matters when three quarters of
     the catalogue has none. */
  /* A studio lookup searches the WHOLE catalogue, not the season being viewed.
     Anime studios are long-tail: 135 distinct ones across a single season, and
     most make exactly one show in it, so a season-scoped studio filter answers
     "what else did they make" with "nothing" far too often. Measured over live
     data: clicking a studio yields more than one title 42% of the time within a
     season and 64% across the catalogue, and TMS Entertainment goes from 5
     titles to 11. Every other filter stays season-scoped, because every other
     filter is a facet with chips that have to match what is on screen. */
  let items = current.studio ? catalogue : season.items;
  if (current.genre) {
    const g = current.genre.toLowerCase();
    items = items.filter((a) => a.genres.some((x) => x.toLowerCase() === g));
  }
  /* Absent means the TV default, not "no filter" - FORMAT_ALL is the explicit
     way to see everything. A fifth of a season is music videos that are never
     scored, so an unfiltered grid mostly answers a question nobody asked. */
  const activeFormat = resolveFormat(current.format);
  if (activeFormat) {
    const f = activeFormat.toLowerCase();
    items = items.filter((a) => (a.format ?? "").toLowerCase() === f);
  }
  if (current.service) {
    const svc = current.service.toLowerCase();
    items = items.filter((a) =>
      (a.streaming_services ?? []).some((x) => x.toLowerCase() === svc),
    );
  }
  if (current.material) {
    const m = current.material.toLowerCase();
    items = items.filter((a) => (a.source_material ?? "").toLowerCase() === m);
  }
  /* No chip row for this one: reached from a title's Studio fact instead, which
     is where the question comes from and which works for all 135 of them. */
  if (current.studio) {
    const st = current.studio.toLowerCase();
    items = items.filter((a) => (a.studios ?? []).some((x) => x.toLowerCase() === st));
  }
  if (current.rated === "1") items = items.filter(isKnown);

  items = sortAnime(items, sortKey);

  const page = Math.max(1, Number(current.page ?? "1") || 1);
  const totalPages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  const clamped = Math.min(page, totalPages);
  const visible = items.slice((clamped - 1) * PAGE_SIZE, clamped * PAGE_SIZE);
  // The TV default is not a "filter" the user applied, so it does not light up
  // the clear-filters affordance. Choosing any other format does.
  // Season and the TV default are not filters the user applied, so neither
  // lights up the clear affordance.
  const hasFilters = Boolean(
    current.genre ||
      current.service ||
      current.rated ||
      current.material ||
      current.studio ||
      (current.format && current.format !== DEFAULT_FORMAT),
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
            <Link
              href={buildHref(
                {},
                { season: current.season, format: current.format },
              )}
              className="text-data underline underline-offset-4"
            >
              Clear filters
            </Link>
          </>
        )}
      </p>

      <div className="mt-7 space-y-4 border-y border-rule py-5">
        {seasons.length > 1 && (
          <FilterRow label="Season">
            {seasons.map((sn) => (
              <Chip
                key={sn.key}
                href={buildHref(current, {
                  season: sn.key,
                  // Genre and service facets differ per season, so a filter
                  // carried across would silently return nothing.
                  genre: undefined,
                  service: undefined,
                  material: undefined,
                  studio: undefined,
                  page: undefined,
                })}
                active={season.key === sn.key}
                count={sn.count}
              >
                {sn.label}
              </Chip>
            ))}
          </FilterRow>
        )}

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

        {/* Adapted from. MAL's contribution, and the facet a trend tracker
            actually wants: 61 originals against 35 manga adaptations says
            something about a season that a genre count does not. */}
        {facets.materials.length > 1 && (
          <FilterRow label="Adapted from">
            <Chip
              href={buildHref(current, { material: undefined, page: undefined })}
              active={!current.material}
            >
              All
            </Chip>
            {facets.materials.map((m) => (
              <Chip
                key={m.value}
                href={buildHref(current, { material: m.value, page: undefined })}
                active={current.material === m.value}
                count={m.count}
              >
                {sourceMaterialLabel(m.value)}
              </Chip>
            ))}
          </FilterRow>
        )}

        {/* Studio appears only once one is being filtered on, because it has no
            chip row to belong to. This is the way back out, and it says outright
            that these results ignore the season above them. */}
        {current.studio && (
          <FilterRow label="Studio">
            <Chip href={buildHref(current, { studio: current.studio })} active>
              {current.studio}
            </Chip>
            <span className="meta">across every season</span>
            <Chip
              href={buildHref(current, { studio: undefined, page: undefined })}
              active={false}
            >
              Clear studio
            </Chip>
          </FilterRow>
        )}

        <FilterRow label="Format">
          {facets.formats.map((f) => (
            <Chip
              key={f.value}
              href={buildHref(current, { format: f.value, page: undefined })}
              // TV is active both when chosen explicitly and when no format is in
              // the URL at all, because absent means TV.
              active={(activeFormat ?? "").toLowerCase() === f.value.toLowerCase()}
              count={f.count}
            >
              {formatLabel(f.value)}
            </Chip>
          ))}
          <span className="mx-1 h-4 w-px bg-rule" aria-hidden />
          <Chip
            href={buildHref(current, { format: FORMAT_ALL, page: undefined })}
            active={current.format === FORMAT_ALL}
            title="Include films, ONAs, specials and music videos"
          >
            All formats
          </Chip>
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
            This view shows {activeFormat ? formatLabel(activeFormat) : "every format"} from a
            season of {season.total} titles, so narrow combinations run out quickly.{" "}
            <Link
              href={buildHref({}, { season: current.season })}
              className="text-data underline underline-offset-4"
            >
              Clear the filters
            </Link>
            {activeFormat ? (
              <>
                {" or "}
                <Link
                  href={buildHref(current, { format: FORMAT_ALL, page: undefined })}
                  className="text-data underline underline-offset-4"
                >
                  include every format
                </Link>
              </>
            ) : null}
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
