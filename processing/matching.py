"""Which source rows describe the same title.

The sources list the same show under different ids, and a union of their rows
puts every popular title in the catalogue twice. This decides which rows are
one title; consolidate.py then merges each group column by column.


THE FOUR RULES

1. The MAL id, which Kitsu supplies through its mappings relationship and
   AniList as idMal. The reliable key, and it catches the large majority.
2. Romaji + format + year, for rows the id cannot match. 14 Kitsu rows in the
   live Summer 2026 data carried no MAL mapping, so their MAL twins survived the
   id as visible duplicates. Most of those have byte-identical romaji.
3. Display title (English, falling back to romaji) + format + year, because
   romaji is a transliteration and the sources transliterate differently:
   "Otome Kaiju Caramelise" against "Otome Kaijuu Caraméliser", "Koukaku
   Kidoutai: THE GHOST IN THE SHELL" against "Koukaku Kidoutai (TV)". All five
   such live pairs agree on the English title. The fallback matters: two of
   them have no English title on the Kitsu side, and match Kitsu's romaji
   against MAL's English.
4. Display title or romaji + exact premiere date, with no format or year, for
   pairs the sources file differently - `special` against `ONA` for the Re:Zero
   break-time shorts, eight live pairs. A same-day premiere under an identical
   title is stronger evidence than format would be. All three date parts are
   required; a partial date would match far too much. Three live pairs whose
   sources disagree on the date as well, by one to four days, are left apart:
   a window wide enough to bridge them is wide enough to join a series to its
   compilation film. The romaji counts as well as the display title: The Lord
   of the Rings: The War of the Rohirrim premiered on 13 December 2024 under
   one romaji in both sources, but Kitsu files it under 2025 and titles it only
   in romaji, and AniList in English. Measured over every live row, the romaji
   joined nine such pairs, the two Inazuma Eleven films of 27 December 2024
   each to its own twin and not to each other.

Rules 2-4 are deliberately narrow: an exact (case- and whitespace-insensitive)
title AND the same format AND the same year, or the same title AND the same
day. A false merge silently deletes a title, which is worse than the duplicate
it prevents, so fuzzy distance, substrings and title-without-format are all
left alone. The year does the work season scoping used to: this runs over the
whole catalogue, because sources disagree about which season a title starts
in, and the year keeps apart the generic names music videos and specials
reuse from one year to the next.

One widening of "the same format": ONA, OVA and special count as one. The
sources file a short release under whichever of the three they like, and it
was the last thing keeping pairs apart - Plus-Sized Elf Specials (ONA against
special), Fuyu no Okurimono (ONA against special, under its English title on
Kitsu), the fourth Opantsu OVA (ONA against OVA). Measured over every live row
it joined exactly those three and refused one more key, which named two MAL
entries. TV, film and music stay apart: that is what keeps a series from its
compilation film, and a song from the show it is the theme of.


EVERY ROW'S OWN TITLES, JOINED TRANSITIVELY

These rules used to run as four passes over the merged rows, each pass keying on
the title that had won the merge so far. Adding a source could then undo a
match. On AniList's first backfill (2026-09-14) its English title filled MAL's
empty one on the Aldnoah.Zero special, the merged row's display title changed,
and the Kitsu row that had matched MAL's romaji matched nothing: one title
became two, and the same happened to Virgin Punk.

Now every rule is applied to every source row's own titles, and rows joined by
any rule are one title, transitively. A new row can only add matches, unless it
is a second work under a name already matched, which the guard below then
refuses to guess between. It also
means a row can bridge two that share nothing: an AniList row carrying MAL's id
and Kitsu's title joins a Kitsu row with no MAL mapping to its MAL twin. The
catalogue held 47 titles twice for exactly that reason before AniList joined.


ONE GUARD: TWO WORKS A SOURCE KEEPS APART

Matching every row's titles offers more chances for two different works to
share a name. So a title rule never joins two rows of one source that carry
different MAL ids - that source has already said they are two works. Without
it, MAL's own two parts of "The Tale of The Spirit Stone", which share an
English title, format and year, would be one title. The old passes had in fact
already merged two 2024 music videos called "Moonlight", and Kitsu's two Dragon
Raja entries, each mapped to its own MAL id; the guard separates them.

Different MAL ids across sources are not enough on their own. Kitsu maps some
titles to AniList's id instead of MAL's (Detective Conan: The Culprit Hanzawa,
the 2026 Chiikawa film), and a guard on that would split titles every source
agrees on. A source listing one work twice, one copy mapped and one not -
Kitsu's Millenniums of Warring States - is still merged.

The rules run in the order the passes always ran, MAL id first, and keys in
sorted order, so a run is deterministic. Order only matters where the guard
refuses a key.

Pure Python over a few thousand small rows, like identity.py: the logic is
branchy, and this way it is testable on any machine rather than only on one
with a JVM.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# The columns each rule reads. consolidate.py collects exactly these.
FIELDS = (
    "source", "source_id", "mal_id", "title_romaji", "title_english", "format",
    "season_year", "start_year", "start_month", "start_day",
)

_RULES = ("mal_id", "romaji", "display", "premiere")


def node(source: str, source_id: Any) -> str:
    """A row's own address, the same "source:source_id" identity uses."""
    return f"{source}:{source_id}"


def _clean(title: str | None) -> str | None:
    title = (title or "").strip().lower()
    return title or None


# The short forms the sources file interchangeably; see "One widening" above.
_SHORT_FORMS = {"ona", "ova", "special"}


def keys(row: dict[str, Any]) -> list[tuple[str, str]]:
    """Every (rule, key) this row can be matched on."""
    out = []
    if row.get("mal_id") is not None:
        out.append(("mal_id", str(row["mal_id"])))

    fmt = _clean(row.get("format"))
    if fmt in _SHORT_FORMS:
        fmt = "short"
    year = row.get("season_year")
    romaji = _clean(row.get("title_romaji"))
    display = _clean(row.get("title_english")) or romaji
    if fmt and year is not None:
        if romaji:
            out.append(("romaji", f"{romaji}|{fmt}|{year}"))
        if display:
            out.append(("display", f"{display}|{fmt}|{year}"))

    date = (row.get("start_year"), row.get("start_month"), row.get("start_day"))
    if None not in date:
        for title in {display, romaji} - {None}:
            out.append(("premiere", f"{title}|{date[0]}-{date[1]}-{date[2]}"))
    return out


@dataclass
class Report:
    rows: int = 0
    titles: int = 0
    # How many joins each rule made, and the title keys refused by the guard.
    joins: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_RULES, 0))
    ambiguous: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        made = ", ".join(f"{n} by {rule}" for rule, n in self.joins.items())
        return (f"{self.rows} rows into {self.titles} titles ({made}); "
                f"{len(self.ambiguous)} title key(s) refused as naming two works")


def group(rows: list[dict[str, Any]]) -> tuple[dict[str, str], Report]:
    """Map every row's node to its title's group id: the smallest node in it.

    A source key can appear in more than one row - the same title in two season
    partitions - and is one node whatever it holds.
    """
    parent: dict[str, str] = {}
    # Per group: for each source, the MAL ids its rows carry. The guard's state.
    named: dict[str, dict[str, set]] = {}
    by_key: dict[str, dict[str, set[str]]] = {rule: defaultdict(set) for rule in _RULES}

    for row in rows:
        me = node(row["source"], row["source_id"])
        parent.setdefault(me, me)
        mine = named.setdefault(me, defaultdict(set))
        if row.get("mal_id") is not None:
            mine[row["source"]].add(row["mal_id"])
        for rule, key in keys(row):
            by_key[rule][key].add(me)

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        keep, gone = sorted((find(a), find(b)))
        parent[gone] = keep
        for source, ids in named.pop(gone).items():
            named[keep][source] |= ids

    report = Report(rows=len(rows))
    for rule in _RULES:
        for key in sorted(by_key[rule]):
            roots = sorted({find(n) for n in by_key[rule][key]})
            if len(roots) < 2:
                continue
            if rule != "mal_id":
                seen: dict[str, set] = defaultdict(set)
                for r in roots:
                    for source, ids in named[r].items():
                        seen[source] |= ids
                if any(len(ids) > 1 for ids in seen.values()):
                    report.ambiguous.append(f"{rule}:{key}")
                    continue
            for r in roots[1:]:
                union(roots[0], r)
            report.joins[rule] += len(roots) - 1

    groups = {n: find(n) for n in parent}
    report.titles = len(set(groups.values()))
    return groups, report
