"use client";

import Image from "next/image";
import Link from "next/link";
import { useRef, useState } from "react";
import { Input } from "@/components/ui/input";
import { API_BASE, formatLabel, SCORE_MAX, scoreOutOfTen, type SearchResponse, type SearchResult } from "@/lib/types";

/** Trimmed season row handed down from the server so results can be rendered as
 *  real plates. Field names are short because this ships in the HTML payload
 *  for all 142 titles. */
export type PlateLite = {
  t: string;
  p: string | null;
  s: number | null;
  f: string | null;
  c: boolean;
};

const EXAMPLES = [
  "quiet show about cooking",
  "revenge story with swords",
  "found family in space",
  "romance that isn't a comedy",
] as const;

type State =
  | { status: "idle" }
  | { status: "loading"; query: string }
  | { status: "done"; query: string; results: SearchResult[] }
  | { status: "error"; message: string; retry?: string };

/* Deliberately client-side, unlike every other data read in this app. Two
 * reasons: /search is rate-limited at 20/min per client IP, and fetching it
 * server-side would pool every visitor into one shared budget — client-side,
 * each visitor spends their own. Queries are unique per user, so server caching
 * would buy nothing, and results have no SEO value worth prerendering. */
export function SearchClient({
  lookup,
  total,
}: {
  lookup: Record<string, PlateLite>;
  total: number;
}) {
  const [state, setState] = useState<State>({ status: "idle" });
  const inputRef = useRef<HTMLInputElement>(null);
  // Guards against an earlier slow request resolving after a later one and
  // overwriting fresher results.
  const requestId = useRef(0);

  async function run(query: string) {
    const trimmed = query.trim();
    if (!trimmed) return;

    const id = ++requestId.current;
    setState({ status: "loading", query: trimmed });

    try {
      const url = new URL("/search", API_BASE);
      url.searchParams.set("q", trimmed);
      url.searchParams.set("n", "20");

      const res = await fetch(url, { headers: { Accept: "application/json" } });
      if (id !== requestId.current) return;

      if (res.status === 429) {
        setState({
          status: "error",
          message:
            "Rate limited. The search endpoint allows 20 queries a minute per visitor, and you have used them up.",
          retry: trimmed,
        });
        return;
      }
      if (res.status === 503) {
        setState({
          status: "error",
          message:
            "The search index has not been built yet. It is written by the weekly pipeline, after ingestion.",
        });
        return;
      }
      if (!res.ok) {
        setState({ status: "error", message: `Search failed (${res.status}).`, retry: trimmed });
        return;
      }

      const data: SearchResponse = await res.json();
      setState({ status: "done", query: trimmed, results: data.results });
    } catch {
      if (id !== requestId.current) return;
      setState({
        status: "error",
        message: "Could not reach the API. It may be restarting after a deploy.",
        retry: trimmed,
      });
    }
  }

  /* Distances come back in a narrow band (roughly 1.0–1.5 in practice), so the
     raw float tells a reader almost nothing on its own. Normalising within the
     result set turns it into a visible ranking, while the actual number stays
     on the row — this is embedding search, and hiding the metric entirely would
     misrepresent it as something more certain than it is. */
  const closeness = (results: SearchResult[], d: number) => {
    const lo = Math.min(...results.map((r) => r.distance));
    const hi = Math.max(...results.map((r) => r.distance));
    if (hi === lo) return 1;
    return 1 - (d - lo) / (hi - lo);
  };

  return (
    <div className="mt-9">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          run(inputRef.current?.value ?? "");
        }}
        className="flex items-baseline gap-4 border-b-2 border-ink pb-2.5"
      >
        <label htmlFor="q" className="meta shrink-0">
          Describe it
        </label>
        <Input
          id="q"
          ref={inputRef}
          type="search"
          autoComplete="off"
          enterKeyHint="search"
          placeholder="a quiet show about cooking…"
          className="font-display text-[1.35rem]"
        />
        <button
          type="submit"
          className="meta shrink-0 border-b-2 border-flag py-1.5 transition-colors hover:text-flag"
        >
          Search
        </button>
      </form>

      <div className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-2">
        <span className="meta">Try</span>
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => {
              if (inputRef.current) inputRef.current.value = example;
              run(example);
            }}
            className="inline-block border-b border-transparent py-1.5 text-[0.82rem] text-ink-soft transition-colors hover:border-rule hover:text-ink"
          >
            {example}
          </button>
        ))}
      </div>

      <div className="mt-9" aria-live="polite" aria-atomic="false">
        {state.status === "idle" && (
          <p className="max-w-[52ch] text-[0.85rem] leading-relaxed text-ink-soft">
            Nothing searched yet. All {total} titles in the catalogue are indexed.
          </p>
        )}

        {state.status === "loading" && (
          <p className="meta">Embedding &ldquo;{state.query}&rdquo;&hellip;</p>
        )}

        {state.status === "error" && (
          <div className="max-w-[52ch] border-l-2 border-flag pl-4">
            <p className="leading-relaxed">{state.message}</p>
            {state.retry && (
              <button
                type="button"
                onClick={() => run(state.retry!)}
                className="meta mt-3 inline-block border-b-2 border-flag py-1.5 transition-colors hover:text-flag"
              >
                Try again
              </button>
            )}
          </div>
        )}

        {state.status === "done" && state.results.length === 0 && (
          <p className="max-w-[52ch] leading-relaxed text-ink-soft">
            Nothing came back for &ldquo;{state.query}&rdquo;. The index covers {total}
            titles, so it is a small pool to match against.
          </p>
        )}

        {state.status === "done" && state.results.length > 0 && (
          <>
            <p className="meta">
              <span className="tnum">{state.results.length}</span> matches, closest first
            </p>
            <ol className="mt-5 grid grid-cols-2 gap-x-4 gap-y-7 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6">
              {state.results.map((result) => {
                const meta = lookup[`${result.source}:${result.source_id}`];
                const known = meta?.s !== null && meta?.s !== undefined;
                const bar = closeness(state.results, result.distance);
                return (
                  <li key={`${result.source}:${result.source_id}`}>
                    <Link
                      href={`/anime/${result.source}/${result.source_id}`}
                      className="group block focus:outline-none"
                    >
                      <div
                        className={[
                          "relative aspect-[3/4] overflow-hidden border border-ink",
                          known ? "plate-known" : "plate-unknown",
                          meta?.p ? "" : "plate-empty bg-plate",
                        ].join(" ")}
                      >
                        {meta?.p ? (
                          <Image
                            src={meta.p}
                            alt=""
                            fill
                            sizes="(max-width: 640px) 46vw, (max-width: 1024px) 30vw, 15vw"
                            className="object-cover"
                          />
                        ) : (
                          <span className="absolute inset-0 flex items-end p-2.5 font-display text-[0.95rem] font-bold leading-[1.1] text-ink-soft">
                            {meta?.t ?? result.title}
                          </span>
                        )}
                        <span
                          className={[
                            "tnum absolute left-0 top-0 z-10 px-1.5 py-1 leading-none",
                            known
                              ? "bg-flag font-display text-[0.95rem] font-bold text-paper"
                              : "border-b border-r border-ink bg-paper text-[0.8rem] text-ink-soft",
                          ].join(" ")}
                        >
                          {known ? scoreOutOfTen(meta!.s) : "—"}
                          <span className="sr-only">
                            {known ? ` out of ${SCORE_MAX}` : "no score available for this title"}
                          </span>
                        </span>
                      </div>

                      <h3 className="mt-2 line-clamp-2 text-[0.78rem] font-medium leading-[1.3] transition-colors group-hover:text-flag">
                        {meta?.t ?? result.title}
                      </h3>

                      {/* Similarity, shown as a rail plus the real figure. */}
                      <div className="mt-1.5 h-[3px] bg-rule" aria-hidden>
                        <div
                          className="h-full bg-data"
                          style={{ width: `${Math.max(6, bar * 100)}%` }}
                        />
                      </div>
                      <p className="meta mt-1 flex justify-between gap-2">
                        <span>{meta ? formatLabel(meta.f) : "—"}</span>
                        <span className="tnum">{result.distance.toFixed(2)}</span>
                      </p>
                    </Link>
                  </li>
                );
              })}
            </ol>
            <p className="meta mt-6">
              The rail shows similarity relative to this result set. The figure is the raw
              embedding distance, where lower is closer.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
