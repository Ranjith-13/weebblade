"""Stable WeebBlade identities for titles.

Until now a title was addressed by whichever source "won" the merge -
`kitsu:49444`, `mal:63830`. That identity moves. The merge decides the survivor
by source priority, so a title changes address whenever that decision changes:
a new merge pass collapses two rows, AniList comes back online and outranks
Kitsu, a mapping appears where there was none. Each of those has already
happened in this project, and each time the losing address simply vanished.

It also breaks `anime_media_latest`, not just future features. That view keeps
the newest row per (source, source_id), so a title whose surviving source
changes between two runs is two different keys and survives TWICE - a duplicate
created by nothing more than the merge picking a different winner this week.

Anything that stores a reference to a title - a franchise edge, a watchlist, a
link somebody shared - needs an address that does not depend on which catalogue
happened to win. That is this.


WHY A REGISTRY AND NOT A HASH

There is no stateless stable ID once the set of rows that make up a title can
change. Hashing `mal_id` changes the day a Kitsu row without one gains a mapping;
hashing the group's smallest key changes when a new source joins with a smaller
one. Every deterministic function of "the rows in this group" moves when the
group moves, and the whole point is that the group WILL move.

So identities are minted once and remembered. The registry maps every source key
that has ever been seen to the identity it belongs to, and each run looks the
new groups up in it before minting anything.


THE REGISTRY IS STATE, NOT DERIVED DATA

Everything else under data/ can be rebuilt: raw snapshots are re-fetchable,
consolidated output is re-derivable from them, the warehouse is views, the index
and digests are regenerated weekly. This file cannot. Lose it and every identity
is re-minted, and every stored reference to a title is dead at once. It lives in
data/identity/ rather than data/processed/ to mark that difference, it is
written atomically, and it is inside the nightly backup and the off-instance
copy along with the rest of data/.


THE FOUR THINGS A RUN CAN DO TO AN IDENTITY

  reuse   - a group's keys are already known. The common case, and the only one
            most weeks.
  mint    - nothing in the group has been seen before. A new title.
  merge   - one group now contains keys from two identities, because a merge
            rule recognised them as one show. The OLDER identity survives, being
            the one most likely to have been referenced, and the younger becomes
            an alias pointing at it, so its address keeps resolving.
  split   - two groups both claim one identity, because a rule got stricter and
            one title became two. The group holding more of that identity's
            known keys keeps it; the other gets a new one. Without this both
            would carry the same ID, and a view deduplicating by ID would quietly
            delete one of the two titles.

Pure Python over lists of strings, deliberately: the catalogue is a few hundred
titles, the logic is branchy, and this way it is testable on any machine rather
than only on one with a JVM.
"""

from __future__ import annotations

import copy
import hashlib
import logging
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

REGISTRY_RELPATH = Path("identity") / "registry.parquet"

# One file, one atomic replace. Three kinds of row share it so the registry can
# never be left half-updated between two files:
#   key   - key is a source key ("kitsu:49444"), wb_id the identity it belongs to
#   id    - key and wb_id are both the identity; date is when it was minted
#   alias - key is a retired identity, wb_id is where it now resolves to
_SCHEMA = pa.schema(
    [
        ("kind", pa.string()),
        ("key", pa.string()),
        ("wb_id", pa.string()),
        ("date", pa.string()),
    ]
)

_ID_PREFIX = "wb_"
_ID_HEX = 10  # 40 bits: collision-free in practice at thousands of titles, and checked anyway


@dataclass
class Registry:
    keys: dict[str, str] = field(default_factory=dict)
    key_seen: dict[str, str] = field(default_factory=dict)
    minted: dict[str, str] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    alias_date: dict[str, str] = field(default_factory=dict)

    def resolve(self, wb_id: str) -> str:
        """Follow aliases to the identity that currently answers for this one.

        Guarded against cycles, which a correct registry never contains but a
        hand-edited one might; an infinite loop in the pipeline is a much worse
        failure than returning the id unchanged.
        """
        seen = set()
        while wb_id in self.aliases and wb_id not in seen:
            seen.add(wb_id)
            wb_id = self.aliases[wb_id]
        return wb_id

    def identity_of(self, source_key: str) -> str | None:
        wb_id = self.keys.get(source_key)
        return self.resolve(wb_id) if wb_id else None


@dataclass
class Report:
    reused: int = 0
    minted: int = 0
    merged: int = 0
    split: int = 0

    def __str__(self) -> str:
        return (
            f"reused {self.reused}, minted {self.minted}, "
            f"merged {self.merged}, split {self.split}"
        )


def source_key(source: str, source_id: str) -> str:
    return f"{source}:{source_id}"


def assign(
    groups: list[list[str]], registry: Registry, today: str
) -> tuple[list[str], Registry, Report]:
    """Give every group of source keys a stable identity.

    `groups[i]` is the source keys of the rows the merge collapsed into output
    row i. Returns one identity per group in the same order, the updated
    registry, and what happened. The input registry is not modified.
    """
    old = registry
    new = copy.deepcopy(registry)
    report = Report()

    # What each group already answers to, resolved through any aliases.
    known = [sorted({old.identity_of(k) for k in keys} - {None}) for keys in groups]

    # Each group's candidate is the OLDEST identity among its keys: when two
    # identities turn out to be one show, the one that has existed longer is the
    # one more likely to have been linked to.
    def age(wb_id: str) -> tuple[str, str]:
        return (old.minted.get(wb_id, "9999-99-99"), wb_id)

    claims: dict[str, list[int]] = defaultdict(list)
    for i, candidates in enumerate(known):
        if candidates:
            claims[min(candidates, key=age)].append(i)

    ids: list[str | None] = [None] * len(groups)
    for wb_id, claimants in claims.items():
        if len(claimants) == 1:
            ids[claimants[0]] = wb_id
            continue

        # A split. Keep the identity with the group that holds most of the keys
        # it was known by, so the bulk of any references stays pointed at the
        # same show; ties break on the group's smallest key for determinism.
        def hold(i: int) -> tuple[int, str]:
            owned = sum(1 for k in groups[i] if old.identity_of(k) == wb_id)
            return (-owned, min(groups[i]))

        keeper = min(claimants, key=hold)
        ids[keeper] = wb_id
        report.split += len(claimants) - 1

    taken = set(old.minted) | set(old.aliases)
    for i, keys in enumerate(groups):
        if ids[i] is None:
            ids[i] = _mint(keys, taken)
            taken.add(ids[i])
            new.minted[ids[i]] = today
            report.minted += 1
        else:
            report.reused += 1

    final = set(ids)

    # Identities that no group answers to any more have been absorbed. Point each
    # at wherever most of its keys went, so its address still resolves.
    retired = {c for candidates in known for c in candidates} - final
    for wb_id in sorted(retired):
        destinations = Counter(
            ids[i] for i, keys in enumerate(groups) for k in keys if old.identity_of(k) == wb_id
        )
        target, _ = destinations.most_common(1)[0]
        new.aliases[wb_id] = target
        new.alias_date[wb_id] = today
        report.merged += 1

    for i, keys in enumerate(groups):
        for k in keys:
            new.keys[k] = ids[i]
            new.key_seen.setdefault(k, today)

    # Normalise so every key points at a LIVE identity and every alias points at
    # its final destination rather than the next hop. Without this, an identity
    # that was only partly absorbed - one of its keys pulled into a merge, another
    # absent this week - leaves that absent key pointing at a retired ID, and
    # anything resolving it in a single join lands on a dead address. Readers of
    # the saved registry (the warehouse views, the API) can then resolve in one
    # hop instead of walking chains.
    new.aliases = {a: new.resolve(a) for a in new.aliases}
    new.keys = {k: new.resolve(w) for k, w in new.keys.items()}

    return ids, new, report  # type: ignore[return-value]


def _mint(keys: list[str], taken: set[str]) -> str:
    """A new identity, derived from the keys that first defined it.

    Derived rather than random so a rerun of the same week mints the same IDs
    instead of a fresh set; the registry is still what makes them permanent.
    Salted and retried on collision, so two different key sets can never be
    handed the same identity, however unlikely.
    """
    base = "|".join(sorted(keys))
    salt = 0
    while True:
        digest = hashlib.sha1(f"{base}#{salt}".encode()).hexdigest()[:_ID_HEX]
        wb_id = f"{_ID_PREFIX}{digest}"
        if wb_id not in taken:
            return wb_id
        salt += 1


def load(data_dir: Path) -> Registry:
    """The registry, or an empty one on the first ever run."""
    path = data_dir / REGISTRY_RELPATH
    if not path.exists():
        logger.warning("No identity registry at %s - every title will be minted fresh", path)
        return Registry()

    registry = Registry()
    for row in pq.read_table(path).to_pylist():
        kind, key, wb_id, date = row["kind"], row["key"], row["wb_id"], row["date"]
        if kind == "key":
            registry.keys[key] = wb_id
            registry.key_seen[key] = date
        elif kind == "id":
            registry.minted[wb_id] = date
        elif kind == "alias":
            registry.aliases[key] = wb_id
            registry.alias_date[key] = date
    return registry


def save(data_dir: Path, registry: Registry) -> Path:
    """Write the registry atomically.

    Written beside the target and moved into place, so a crash mid-write leaves
    the previous registry intact rather than a truncated one. For every other
    file in data/ a torn write costs a rerun. For this one it costs every
    identity the project has ever issued.
    """
    path = data_dir / REGISTRY_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = (
        [{"kind": "id", "key": w, "wb_id": w, "date": d} for w, d in sorted(registry.minted.items())]
        + [
            {"kind": "key", "key": k, "wb_id": w, "date": registry.key_seen.get(k)}
            for k, w in sorted(registry.keys.items())
        ]
        + [
            {"kind": "alias", "key": a, "wb_id": w, "date": registry.alias_date.get(a)}
            for a, w in sorted(registry.aliases.items())
        ]
    )

    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(pa.Table.from_pylist(rows, schema=_SCHEMA), tmp)
    os.replace(tmp, path)
    return path
