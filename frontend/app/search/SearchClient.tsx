"use client";

import Image from "next/image";
import Link from "next/link";
import { useRef, useState } from "react";
import { Input } from "@/components/ui/input";
import {
  API_BASE,
  formatLabel,
  NULL_MARKER,
  SCORE_MAX,
  scoreOutOfTen,
  titleHref,
  type SearchResponse,
  type SearchResult,
} from "@/lib/types";

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
 * server-side would pool every visitor into one shared budget - client-side,
 * each visitor spends their own. Queries are unique per user, so server caching
 * would buy nothing, and results have no SEO value worth prerendering. */
export function SearchClient({ total }: { total: number }) {
  const [state, setState] = useState<State>({ status: "idle" });
  const [isWaking, setIsWaking] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  // Guards against an earlier slow request resolving after a later one and
  // overwriting fresher results.
  const requestId = useRef(0);

  async function run(query: string) {
    const trimmed = query.trim();
    if (!trimmed) return;

    const id = ++requestId.current;
    setIsWaking(false);
    setState({ status: "loading", query: trimmed });

    /* MEASURED AGAINST THE LIVE SERVICE, 13 October 2026, after 17 idle
     * minutes: a cold /health took 32.4s, the first search after it 2.5s, a
     * warm search 1.8s. So this has to straddle 2.5s against 32s.
     *
     * 5s, not the 3.5s it first shipped with. 3.5s sat barely a second above a
     * normal warm search on a 0.1-CPU instance, so an ordinary slow query would
     * have told the reader the service was asleep while it was wide awake, and
     * a notice that cries wolf is worse than no notice. The 150ms it was set
     * from was measured on a laptop and does not survive the plan this runs on. */
    const wakeTimer = setTimeout(() => {
      if (id === requestId.current) {
        setIsWaking(true);
      }
    }, 5000);

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
    } finally {
      clearTimeout(wakeTimer);
    }
  }

  /* Distances come back in a narrow band (roughly 1.0–1.5 in practice), so the
     raw float tells a reader almost nothing on its own. Normalising within the
     result set turns it into a visible ranking, while the actual number stays
     on the row - this is embedding search, and hiding the metric entirely would
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
          /* ENTER MEANS TWO DIFFERENT THINGS, and this is a catalogue of
             Japanese titles, so the second one is not an edge case here.
             Typing with an IME, Enter confirms the candidate the IME is
             offering - it does not submit the form. Without this guard,
             composing "ゆるキャン" fired a search on the half-formed kana the
             moment the reader pressed Enter to pick the kanji, spending one of
             their 20 queries a minute on a string they never meant to send and
             replacing the box's contents mid-thought.

             isComposing is the browser telling us the IME still owns this
             keystroke. Preventing the default stops only the submit; the IME
             has already consumed the key for its own purposes. */
          onKeyDown={(e) => {
            if (e.key === "Enter" && e.nativeEvent.isComposing) e.preventDefault();
          }}
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
            Nothing searched yet. All {total.toLocaleString()} titles in the catalogue are indexed.
          </p>
        )}

        {state.status === "loading" && (
          <div>
            <p className="meta">Embedding &ldquo;{state.query}&rdquo;&hellip;</p>
            {/* A cold container takes ~32s to answer, and until now that was a
                line of static text: nothing on the screen said the page was
                still working rather than finished and empty. An indeterminate
                rule, never a percentage - nothing here knows how far along the
                request is, and a bar that invents one is lying to fill a gap.
                It is the same hairline the rest of the page separates with. */}
            <div className="mt-2.5 h-[2px] w-full max-w-[18rem] overflow-hidden bg-rule" aria-hidden>
              <div data-sweep className="h-full w-1/3 bg-flag" />
            </div>
            {/* Said the way everything else on this site says it: what is
              * happening and why, in the reader's terms. Not "the container is
              * booting on Render" - a reader has no container and did not choose
              * the host. "About half a minute" is measured, not borrowed: 32.4s to
              * the first response after 17 idle minutes. Render's published figure
              * is "about a minute", which would have been the safe thing to print
              * and the wrong thing to say. */}
            {isWaking && (
              <p className="mt-2.5 max-w-[50ch] text-[0.82rem] leading-relaxed text-ink-soft">
                Waking the search service. It sleeps when nobody has searched for a quarter of
                an hour, and takes about half a minute to come back.
              </p>
            )}
          </div>
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
            Nothing came back for &ldquo;{state.query}&rdquo;. The index covers {total.toLocaleString()}
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
                const score = result.score_100 ?? null;
                const known = score !== null;
                const bar = closeness(state.results, result.distance);
                return (
                  <li key={`${result.source}:${result.source_id}`}>
                    <Link
                      href={titleHref(result)}
                      className="group block focus:outline-none"
                    >
                      <div
                        className={[
                          "relative aspect-[3/4] overflow-hidden border border-ink",
                          known ? "plate-known" : "plate-unknown",
                          "bg-plate",
                          result.poster_url ? "" : "plate-empty",
                        ].join(" ")}
                      >
                        {/* Under the artwork, not instead of it - see Plate. */}
                        <span className="absolute inset-0 flex items-end p-2.5 font-display text-[0.95rem] font-bold leading-[1.1] text-ink-soft">
                          {result.title}
                        </span>
                        {result.poster_url && (
                          <Image
                            src={result.poster_url}
                            alt=""
                            fill
                            sizes="(max-width: 640px) 46vw, (max-width: 1024px) 30vw, 15vw"
                            className="object-cover"
                          />
                        )}
                        <span
                          className={[
                            "tnum absolute left-0 top-0 z-10 px-1.5 py-1 leading-none",
                            known
                              ? "bg-flag font-display text-[0.95rem] font-bold text-paper"
                              : "border-b border-r border-ink bg-paper text-[0.8rem] text-ink-soft",
                          ].join(" ")}
                        >
                          {known ? scoreOutOfTen(score) : NULL_MARKER}
                          <span className="sr-only">
                            {known ? ` out of ${SCORE_MAX}` : "no score available for this title"}
                          </span>
                        </span>
                      </div>

                      <h3 className="mt-2 line-clamp-2 text-[0.78rem] font-medium leading-[1.3] transition-colors group-hover:text-flag">
                        {result.title}
                      </h3>

                      {/* Similarity, shown as a rail plus the real figure. */}
                      <div className="mt-1.5 h-[3px] bg-rule" aria-hidden>
                        <div
                          className="h-full bg-data"
                          style={{ width: `${Math.max(6, bar * 100)}%` }}
                        />
                      </div>
                      <p className="meta mt-1 flex justify-between gap-2">
                        <span>{result.format ? formatLabel(result.format) : NULL_MARKER}</span>
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
