"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { API_BASE, type SearchResponse, type SearchResult } from "@/lib/types";

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
  | { status: "error"; message: string };

/* Deliberately client-side, unlike every other data read in this app. Two
 * reasons: the upstream /search endpoint is rate-limited at 20/min per client
 * IP, and fetching it server-side would pool every visitor into one shared
 * budget - whereas client-side each visitor spends their own. Search queries
 * are also unique per user, so server caching would buy nothing, and results
 * have no SEO value worth prerendering. */
export function SearchClient() {
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
          message: "Rate limited — the search endpoint allows 20 queries a minute. Try again shortly.",
        });
        return;
      }
      if (res.status === 503) {
        setState({ status: "error", message: "The search index isn't built yet." });
        return;
      }
      if (!res.ok) {
        setState({ status: "error", message: `Search failed (${res.status}).` });
        return;
      }

      const data: SearchResponse = await res.json();
      setState({ status: "done", query: trimmed, results: data.results });
    } catch {
      if (id !== requestId.current) return;
      setState({ status: "error", message: "Couldn't reach the API." });
    }
  }

  return (
    <div className="mt-12">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          run(inputRef.current?.value ?? "");
        }}
        className="flex items-baseline gap-4 border-b border-rule pb-3 focus-within:border-muted transition-colors"
      >
        <label htmlFor="q" className="label shrink-0">
          Query
        </label>
        <input
          id="q"
          ref={inputRef}
          type="search"
          autoComplete="off"
          placeholder="describe a show…"
          className="flex-1 bg-transparent text-xl outline-none placeholder:text-muted/50 font-display"
        />
        <button type="submit" className="label hover:!text-ink transition-colors shrink-0">
          Search →
        </button>
      </form>

      <div className="mt-4 flex flex-wrap items-baseline gap-x-4 gap-y-2">
        <span className="label">Try</span>
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => {
              if (inputRef.current) inputRef.current.value = example;
              run(example);
            }}
            className="text-sm text-muted hover:text-ink transition-colors border-b border-transparent hover:border-rule"
          >
            {example}
          </button>
        ))}
      </div>

      <div className="mt-12">
        {state.status === "loading" && <p className="label">Embedding “{state.query}”…</p>}

        {state.status === "error" && <p className="text-muted">{state.message}</p>}

        {state.status === "done" && state.results.length === 0 && (
          <p className="text-muted">Nothing came back for “{state.query}”.</p>
        )}

        {state.status === "done" && state.results.length > 0 && (
          <>
            <p className="label">
              <span className="tnum">{state.results.length}</span> matches, closest first
            </p>
            <ol className="mt-6 border-t border-rule">
              {state.results.map((result, i) => (
                <li key={`${result.source}:${result.source_id}`}>
                  <Link
                    href={`/anime/${result.source}/${result.source_id}`}
                    className="group flex items-baseline gap-5 border-b border-rule py-4 hover:bg-raised transition-colors"
                  >
                    <span className="tnum label w-7 shrink-0">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span className="flex-1 group-hover:text-accent transition-colors">
                      {result.title}
                    </span>
                    {/* Distance is the whole point of showing this as semantic
                        search rather than a keyword list - lower is closer. */}
                    <span className="tnum text-sm text-muted shrink-0">
                      {result.distance.toFixed(3)}
                    </span>
                  </Link>
                </li>
              ))}
            </ol>
            <p className="label mt-4">Lower distance = closer semantic match</p>
          </>
        )}
      </div>
    </div>
  );
}
