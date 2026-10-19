"""State between runs: pipeline/state.py.

A GitHub runner starts empty, so what travels - and what does not - is the whole
correctness of the thing. A missing registry means every title changes address.
A travelling warehouse means views that resolve to nothing on the next machine.
"""

import json
import tarfile
from pathlib import Path

from datetime import date

import pytest

from pipeline import state


@pytest.fixture
def gh(tmp_path, monkeypatch):
    """A release store on disk, standing in for the gh CLI.

    Not a mock of what the code does - a small real implementation of what
    GitHub does, so the tarball is really written, really uploaded under a tag,
    and really extracted somewhere else.
    """
    store = tmp_path / "releases"
    store.mkdir()
    calls: list[tuple[str, ...]] = []

    def fake_gh(*args, check=True):
        calls.append(args)
        if args[0] == "api":
            # What the REST API answers, assets included - which is the whole
            # reason the code asks it rather than `gh release list`.
            tags = sorted(p.name for p in store.iterdir())
            return json.dumps([
                {"tag_name": t, "created_at": f"2026-10-{i:02d}T00:00:00Z",
                 "assets": [{"name": f.name} for f in sorted((store / t).iterdir())]}
                for i, t in enumerate(tags, 1)
            ])
        verb = args[1]
        if verb == "list":
            tags = sorted(p.name for p in store.iterdir())
            return json.dumps([{"tagName": t, "createdAt": f"2026-10-{i:02d}"}
                               for i, t in enumerate(tags, 1)])
        if verb == "view":
            return "{}" if (store / args[2]).exists() else ""
        if verb == "create":
            (store / args[2]).mkdir(exist_ok=True)
            return ""
        if verb == "upload":
            asset = Path(args[3])
            (store / args[2] / asset.name).write_bytes(asset.read_bytes())
            return ""
        if verb == "download":
            target = Path(args[args.index("--dir") + 1])
            pattern = args[args.index("--pattern") + 1] if "--pattern" in args else None
            target.mkdir(parents=True, exist_ok=True)
            wanted = [f for f in (store / args[2]).iterdir()
                      if pattern is None or f.name == pattern]
            if not wanted:
                # gh exits non-zero when the pattern matches no asset, and _gh
                # turns that into a RuntimeError. Modelled, because a release
                # that lacks the asset being asked for is exactly the case this
                # suite needs to cover.
                raise RuntimeError(f"gh release download: no asset matching {pattern}")
            for f in wanted:
                (target / f.name).write_bytes(f.read_bytes())
            return ""
        if verb == "delete":
            for f in (store / args[2]).iterdir():
                f.unlink()
            (store / args[2]).rmdir()
            return ""
        raise AssertionError(f"unexpected gh call: {args}")

    monkeypatch.setattr(state, "_gh", fake_gh)
    return store, calls


def _lake(root: Path) -> Path:
    """A data directory with everything a run reads and writes."""
    for name, body in (
        ("processed/anime_media_consolidated/_catalogue/2026-10-11/p.parquet", b"catalogue"),
        ("processed/anilist_media/2026-FALL/2026-10-11.parquet", b"snapshot"),
        ("identity/registry.parquet", b"the registry"),
        ("raw/anilist/2026-FALL/2026-10-11.json", b"[]"),
        ("digests/2026-10-11.md", b"# digest"),
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    (root / "warehouse.duckdb").write_bytes(b"not portable")
    return root


def test_what_a_run_needs_next_time_survives_the_round_trip(gh, tmp_path):
    here, there = _lake(tmp_path / "here"), tmp_path / "there"

    state.publish_state(here, "2026-10-11")
    restored = state.fetch_state(there)

    assert restored == "state-2026-10-11"
    assert (there / "identity/registry.parquet").read_bytes() == b"the registry"
    assert (there / "processed/anilist_media/2026-FALL/2026-10-11.parquet").exists()
    assert (there / "raw/anilist/2026-FALL/2026-10-11.json").exists()


def test_the_warehouse_does_not_travel(gh, tmp_path):
    """Its views carry the absolute path of the machine that built them, so a
    warehouse that moved would answer every query with no rows - the worst way
    to fail. Every run builds its own; see pipeline.run._ensure_warehouse."""
    here, there = _lake(tmp_path / "here"), tmp_path / "there"

    state.publish_state(here, "2026-10-11")
    state.fetch_state(there)

    assert not (there / "warehouse.duckdb").exists()


def test_the_digests_do_travel(gh, tmp_path):
    """They were on the "not kept" list as something a run rebuilds. They are
    not: a digest is what a model wrote about one particular week, and asking
    again next week writes different prose about different data. Published
    without them, the site's archive page would have listed exactly one entry
    for ever - whichever week the reader happened to arrive in."""
    here, there = _lake(tmp_path / "here"), tmp_path / "there"

    state.publish_state(here, "2026-10-11")
    state.fetch_state(there)

    assert (there / "digests" / "2026-10-11.md").read_bytes() == b"# digest"


def test_a_release_holding_only_a_warehouse_is_not_mistaken_for_state(gh, tmp_path):
    """The newest release and the newest release that HAS state are different
    things, and treating them as one broke the next run within minutes of it
    first happening.

    publish_warehouse tags by today's date, so republishing an artifact built
    from yesterday's state made a release carrying a warehouse and nothing
    else. fetch_state took the newest tag, asked it for a state.tar.gz that was
    never there, and would have failed the following run at its first step - a
    whole pipeline stopped by an extra file in the wrong place. A run that dies
    between publishing its warehouse and its state leaves the same shape.
    """
    here, there = _lake(tmp_path / "here"), tmp_path / "there"
    state.publish_state(here, "2026-10-12")

    # A later release with only the serving artifact on it.
    store, _ = gh
    (store / "state-2026-10-13").mkdir()
    (store / "state-2026-10-13" / state.WAREHOUSE_ASSET).write_bytes(b"portable")

    assert state.fetch_state(there) == "state-2026-10-12"
    assert (there / "identity" / "registry.parquet").read_bytes() == b"the registry"


def test_the_tarball_is_not_left_behind_in_the_lake(gh, tmp_path):
    """It is written into the data directory and would otherwise end up inside
    the next run's tarball, doubling every time."""
    here, there = _lake(tmp_path / "here"), tmp_path / "there"

    state.publish_state(here, "2026-10-11")
    state.fetch_state(there)

    assert not (here / state.STATE_ASSET).exists()
    assert not (there / state.STATE_ASSET).exists()


def test_the_newest_state_is_the_one_restored(gh, tmp_path):
    here, there = _lake(tmp_path / "here"), tmp_path / "there"
    state.publish_state(here, "2026-10-09")
    (here / "identity/registry.parquet").write_bytes(b"newer registry")
    state.publish_state(here, "2026-10-11")

    state.fetch_state(there)

    assert (there / "identity/registry.parquet").read_bytes() == b"newer registry"


def test_a_second_run_on_one_day_replaces_that_days_assets(gh, tmp_path):
    """A Sunday has both a daily and a weekly run, and they land on one date."""
    store, _ = gh
    here = _lake(tmp_path / "here")

    state.publish_state(here, "2026-10-11")
    (here / "identity/registry.parquet").write_bytes(b"after the weekly")
    state.publish_state(here, "2026-10-11")

    there = tmp_path / "there"
    state.fetch_state(there)

    assert [p.name for p in store.iterdir()] == ["state-2026-10-11"]
    assert (there / "identity/registry.parquet").read_bytes() == b"after the weekly"


def test_an_empty_lake_is_never_published_over_good_state(gh, tmp_path):
    """The most important refusal here. Publishing runs with if: always(), so a
    run that dies before restoring anything would upload an empty archive and
    the next run would restore it - losing the registry and every snapshot. The
    first run on Actions did exactly that: pip filled the disk, every later step
    was skipped, and this was still asked to publish a directory that was not
    there."""
    store, _ = gh
    state.publish_state(_lake(tmp_path / "here"), "2026-10-11")

    assert state.publish_state(tmp_path / "never-existed", "2026-10-12") is None
    assert [p.name for p in store.iterdir()] == ["state-2026-10-11"]

    there = tmp_path / "there"
    state.fetch_state(there)
    assert (there / "identity/registry.parquet").read_bytes() == b"the registry"


def test_the_published_warehouse_is_the_portable_one(gh, tmp_path, monkeypatch):
    """What goes up is a materialised copy, not the run's own warehouse - whose
    views carry this machine's absolute paths and would answer a reader with no
    rows at all."""
    store, _ = gh
    here = _lake(tmp_path / "here")
    monkeypatch.setattr(
        "processing.publish.materialise",
        lambda src, out: (out.write_bytes(b"portable"), out)[1] if src.exists() else None,
    )

    assert state.publish_warehouse(here, "2026-10-11") == "state-2026-10-11"

    published = store / "state-2026-10-11" / state.WAREHOUSE_ASSET
    assert published.read_bytes() == b"portable"
    assert published.read_bytes() != (here / "warehouse.duckdb").read_bytes()


def test_no_warehouse_is_not_an_error(gh, tmp_path):
    assert state.publish_warehouse(tmp_path / "empty", "2026-10-11") is None


def test_the_first_run_ever_starts_from_nothing_rather_than_failing(gh, tmp_path):
    assert state.fetch_state(tmp_path / "empty") is None


def test_old_states_are_pruned_but_the_rollback_window_is_kept(gh, tmp_path):
    """Kept because publishing happens even when the check fails: restoring an
    older release is the undo, so there has to be one."""
    store, _ = gh
    here = _lake(tmp_path / "here")
    for day in range(1, 13):
        state.publish_state(here, f"2026-10-{day:02d}")

    pruned = state.prune(keep=8)

    assert len(pruned) == 4
    assert sorted(p.name for p in store.iterdir())[0] == "state-2026-10-05"


def test_releases_that_are_not_state_are_left_alone(gh, tmp_path):
    """The repo may hold ordinary releases one day; these functions must not
    list, restore or delete them."""
    store, _ = gh
    (store / "v1.0.0").mkdir()
    here = _lake(tmp_path / "here")
    state.publish_state(here, "2026-10-11")

    assert state.fetch_state(tmp_path / "there") == "state-2026-10-11"
    state.prune(keep=0)
    assert (store / "v1.0.0").exists()


def test_the_archive_holds_plain_relative_paths(gh, tmp_path):
    """Extraction uses filter="data", which refuses absolute paths and links
    pointing outside the destination. Worth knowing the writer agrees."""
    here = _lake(tmp_path / "here")
    state.publish_state(here, "2026-10-11")

    store, _ = gh
    with tarfile.open(store / "state-2026-10-11" / state.STATE_ASSET) as tar:
        names = tar.getnames()

    assert all(not n.startswith("/") and ".." not in n for n in names)
    assert {n.split("/")[0] for n in names} == {"processed", "identity", "raw", "digests"}


# RAW RETENTION
#
# raw/ is two thirds of the state archive and the dated half of it compounds:
# mal_relations writes a directory of batches per run, the AniList schedule and
# status a file each per morning, and the weekly refetch of the current season
# leaves another dated file beside the one the backfill put there. Measured on
# 2026-10-19 that was ~0.7 MB a day against a 73 MB archive the GitLab mirror
# keeps twenty copies of.
#
# The danger is not deleting too little. raw/kitsu holds one dated file per
# season back to 2017-FALL, put there by a single 40-season crawl and never
# refetched, so "older than ninety days" applied without care would delete the
# only copy of the most expensive thing in the lake.


def _fetch(data_dir, relative: str, body: bytes = b"{}") -> Path:
    path = data_dir / "raw" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def test_the_only_copy_of_a_season_is_never_pruned(tmp_path):
    """The whole safety of the rule. These were fetched once, years ago by their
    own dates and months ago by the fetch's, and nothing will fetch them again."""
    old = [_fetch(tmp_path, f"kitsu/{season}/2026-01-01.json")
           for season in ("2017-FALL", "2018-SPRING", "2019-SUMMER")]

    removed = state.prune_raw(tmp_path, today=date(2026, 10, 19))

    assert removed == []
    assert all(p.exists() for p in old)


def test_an_older_refetch_of_the_same_season_goes(tmp_path):
    """What the rule is actually for: the current season is fetched again every
    week, and last quarter's copies of it say nothing the newest does not."""
    stale = _fetch(tmp_path, "kitsu/2026-FALL/2026-01-01.json")
    recent = _fetch(tmp_path, "kitsu/2026-FALL/2026-10-11.json")
    newest = _fetch(tmp_path, "kitsu/2026-FALL/2026-10-18.json")

    removed = state.prune_raw(tmp_path, today=date(2026, 10, 19))

    assert removed == [stale]
    assert recent.exists() and newest.exists()


def test_a_daily_fetch_older_than_the_window_goes(tmp_path):
    kept = [_fetch(tmp_path, f"anilist_airing/2026-10-{d:02d}.json") for d in (1, 18)]
    stale = _fetch(tmp_path, "anilist_airing/2026-05-01.json")

    removed = state.prune_raw(tmp_path, today=date(2026, 10, 19))

    assert removed == [stale]
    assert all(p.exists() for p in kept)


def test_a_dated_directory_of_batches_is_pruned_whole(tmp_path):
    """mal_relations writes raw/mal_relations/<date>/from-*.json, so the fetch
    is the directory. The batch files inside carry no date of their own and must
    not be mistaken for one."""
    stale = _fetch(tmp_path, "mal_relations/2026-01-05/from-1006.json").parent
    _fetch(tmp_path, "mal_relations/2026-01-05/from-2000.json")
    newest = _fetch(tmp_path, "mal_relations/2026-10-18/from-1006.json").parent

    removed = state.prune_raw(tmp_path, today=date(2026, 10, 19))

    assert removed == [stale]
    assert not stale.exists()
    assert newest.exists()


def test_nothing_is_pruned_inside_the_window(tmp_path):
    kept = [_fetch(tmp_path, f"anilist_status/2026-{m:02d}-01.json") for m in (8, 9, 10)]

    assert state.prune_raw(tmp_path, today=date(2026, 10, 19)) == []
    assert all(p.exists() for p in kept)


def test_an_empty_or_absent_lake_is_not_an_error(tmp_path):
    assert state.prune_raw(tmp_path, today=date(2026, 10, 19)) == []
    (tmp_path / "raw").mkdir()
    assert state.prune_raw(tmp_path, today=date(2026, 10, 19)) == []
