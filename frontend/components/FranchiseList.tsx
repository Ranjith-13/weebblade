"use client";

import Image from "next/image";
import Link from "next/link";
import { useState } from "react";
import {
  formatLabel,
  relationLabel,
  SCORE_MAX,
  scoreOutOfTen,
  titleHref,
  type FranchiseEntry,
} from "@/lib/types";

/* Most franchises are a handful of entries. A few are enormous - Gundam runs to
   130 and Detective Conan to 129 - and a list that long buries the entries next
   to this one, which are the ones anyone came for. So a long franchise opens on
   the WINDOW entries around this title, with the rest one click away. */
const WINDOW = 12;

function around(entries: FranchiseEntry[], size: number): FranchiseEntry[] {
  if (entries.length <= size) return entries;
  const at = Math.max(0, entries.findIndex((e) => e.is_this));
  const start = Math.min(Math.max(0, at - Math.floor(size / 2) + 1), entries.length - size);
  return entries.slice(start, start + size);
}

export function FranchiseList({ entries }: { entries: FranchiseEntry[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? entries : around(entries, WINDOW);

  return (
    <>
      {/* A listing, like the schedule: the year is the column the eye runs down.
          Two columns on a wide screen, filled top to bottom so the order still
          reads as a timeline. */}
      <ol className="mt-4 gap-x-10 lg:columns-2">
        {shown.map((entry) => (
          <Row key={entry.mal_id} entry={entry} />
        ))}
      </ol>
      {entries.length > WINDOW && (
        <button
          type="button"
          aria-expanded={all}
          onClick={() => setAll((v) => !v)}
          className="meta mt-3 inline-block border-b-2 border-rule py-1.5 transition-colors hover:border-flag hover:text-flag"
        >
          {all ? `Show the ${WINDOW} nearest this title` : `Show all ${entries.length}`}
        </button>
      )}
    </>
  );
}

function Row({ entry: e }: { entry: FranchiseEntry }) {
  const year = e.start_date?.slice(0, 4) ?? null;
  // The certainty treatment, meaning what it means everywhere: in colour when
  // the catalogue has a score for it. An entry the catalogue does not hold has
  // none here, and is drawn that way.
  const known = e.score_100 !== null;
  const label = e.is_this ? "This title" : relationLabel(e.relation);

  const content = (
    <>
      <span
        className={[
          "relative block h-[3.2rem] w-[2.4rem] shrink-0 overflow-hidden border border-ink",
          known ? "plate-known" : "plate-unknown plate-fine",
          e.poster_url ? "" : "plate-empty bg-plate",
        ].join(" ")}
      >
        {e.poster_url && <Image src={e.poster_url} alt="" fill sizes="40px" className="object-cover" />}
      </span>
      <span className="min-w-0 flex-1">
        <span
          className={[
            "block truncate text-[0.9rem] leading-tight",
            e.is_this
              ? "font-semibold text-flag"
              : "font-medium transition-colors duration-150 group-hover:text-flag group-focus-visible:text-flag",
          ].join(" ")}
        >
          {e.title ?? "Untitled"}
        </span>
        <span className="meta mt-0.5 flex items-baseline gap-x-3">
          <span>{formatLabel(e.format)}</span>
          {known && (
            <span className="tnum">
              {scoreOutOfTen(e.score_100)} / {SCORE_MAX}
            </span>
          )}
          {!e.wb_id && <span>On MyAnimeList</span>}
        </span>
      </span>
    </>
  );

  const box = "group flex min-w-0 flex-1 items-center gap-3 focus:outline-none";
  return (
    <li
      aria-current={e.is_this ? "page" : undefined}
      className="flex break-inside-avoid items-center gap-4 border-t border-rule py-2.5"
    >
      <span className="tnum w-[2.6rem] shrink-0 text-[0.95rem] font-semibold">{year ?? "TBA"}</span>
      {e.is_this ? (
        <span className="flex min-w-0 flex-1 items-center gap-3">{content}</span>
      ) : e.wb_id ? (
        <Link href={titleHref({ wb_id: e.wb_id, source: "mal", source_id: String(e.mal_id) })} className={box}>
          {content}
        </Link>
      ) : (
        <a href={`https://myanimelist.net/anime/${e.mal_id}`} target="_blank" rel="noreferrer" className={box}>
          {content}
        </a>
      )}
      {label && <span className="meta shrink-0 text-right">{label}</span>}
    </li>
  );
}
