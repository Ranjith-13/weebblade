"""The API fetching the warehouse it serves.

Everything here is about one question: when something goes wrong, does the
service keep serving what it already had? A free container has no persistent
disk, so it downloads the catalogue on every wake-up, which turns every GitHub
hiccup into a user-visible event unless the failure path is the careful one.
"""

import duckdb
import pytest

from backend.app import warehouse


def _release(tag: str, assets: list[str], asset_id: int = 1) -> dict:
    return {
        "tag_name": tag,
        "assets": [{"name": name, "id": asset_id + i} for i, name in enumerate(assets)],
    }


def _a_working_warehouse(path):
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE anime_media_latest AS SELECT 'kitsu:1' AS source_id")
    con.close()


def test_the_newest_release_carrying_a_warehouse_wins_not_the_newest_release():
    """Only the weekly run publishes a warehouse, so on six days out of seven the
    newest release does not have one. This is why the choice is made from the
    list rather than from /releases/latest."""
    chosen = warehouse.newest_warehouse([
        _release("state-2026-10-12", ["state.tar.gz"]),
        _release("state-2026-10-11", ["state.tar.gz", "warehouse.duckdb"], asset_id=10),
        _release("state-2026-10-04", ["state.tar.gz", "warehouse.duckdb"], asset_id=20),
    ])

    assert chosen == ("state-2026-10-11", 11)


def test_releases_are_ordered_by_their_date_not_by_the_order_github_returned():
    """A rerun or a backfill can create a release out of order. The tags are
    state-YYYY-MM-DD, which sorts correctly as text."""
    chosen = warehouse.newest_warehouse([
        _release("state-2026-09-27", ["warehouse.duckdb"], asset_id=1),
        _release("state-2026-10-11", ["warehouse.duckdb"], asset_id=2),
        _release("state-2026-10-04", ["warehouse.duckdb"], asset_id=3),
    ])

    assert chosen == ("state-2026-10-11", 2)


def test_releases_that_are_not_pipeline_state_are_ignored():
    """A hand-made release - a tagged version, anything - is not state, and an
    asset of the right name on one should not be served."""
    assert warehouse.newest_warehouse([
        _release("v1.0.0", ["warehouse.duckdb"]),
        _release("state-2026-10-11", ["state.tar.gz"]),
    ]) is None


def test_nothing_is_fetched_unless_a_repository_is_named(tmp_path, monkeypatch):
    """A local run already has the warehouse the pipeline just built. Downloading
    over it would at best waste a minute and at worst replace it, so fetching is
    opt-in and only the deployed service asks for it."""
    monkeypatch.delenv("WAREHOUSE_REPO", raising=False)
    monkeypatch.setattr(warehouse, "_fetch_releases",
                        lambda *a, **k: pytest.fail("asked GitHub with no repo configured"))
    _a_working_warehouse(tmp_path / "warehouse.duckdb")

    assert warehouse.ensure_warehouse(tmp_path) is None
    assert warehouse.state["origin"] == "mounted"


def test_a_corrupt_download_does_not_replace_a_working_warehouse(tmp_path, monkeypatch):
    """The failure this whole module is shaped around. A truncated download that
    becomes the served file is worse than a stale one, because it looks like
    success and answers every request with an error."""
    monkeypatch.setenv("WAREHOUSE_REPO", "owner/repo")
    db = tmp_path / "warehouse.duckdb"
    _a_working_warehouse(db)
    (tmp_path / "warehouse.tag").write_text("state-2026-10-04")
    good = db.read_bytes()

    monkeypatch.setattr(warehouse, "_fetch_releases",
                        lambda *a, **k: [_release("state-2026-10-11", ["warehouse.duckdb"])])

    def half_a_file(repo, asset_id, dest, timeout):
        dest.write_bytes(b"DUCK" + b"\x00" * 200)
        return 204

    monkeypatch.setattr(warehouse, "_download", half_a_file)

    assert warehouse.ensure_warehouse(tmp_path) == "state-2026-10-04"
    assert db.read_bytes() == good
    assert not (tmp_path / "warehouse.duckdb.part").exists()  # staged copy cleaned up


def test_github_being_unreachable_leaves_the_existing_warehouse_in_place(tmp_path, monkeypatch):
    """A service that refuses to serve last week's catalogue because a release
    could not be listed is strictly worse than one that serves it."""
    monkeypatch.setenv("WAREHOUSE_REPO", "owner/repo")
    _a_working_warehouse(tmp_path / "warehouse.duckdb")
    (tmp_path / "warehouse.tag").write_text("state-2026-10-04")

    def down(*args, **kwargs):
        raise OSError("name resolution failed")

    monkeypatch.setattr(warehouse, "_fetch_releases", down)

    assert warehouse.ensure_warehouse(tmp_path) == "state-2026-10-04"


def test_a_published_warehouse_already_on_disk_is_not_downloaded_again(tmp_path, monkeypatch):
    """Every six hours a warm container re-checks. Re-downloading 37 MB to
    arrive at the same file would spend the free plan's bandwidth on nothing."""
    monkeypatch.setenv("WAREHOUSE_REPO", "owner/repo")
    _a_working_warehouse(tmp_path / "warehouse.duckdb")
    (tmp_path / "warehouse.tag").write_text("state-2026-10-11")

    monkeypatch.setattr(warehouse, "_fetch_releases",
                        lambda *a, **k: [_release("state-2026-10-11", ["warehouse.duckdb"])])
    monkeypatch.setattr(warehouse, "_download",
                        lambda *a, **k: pytest.fail("downloaded a warehouse it already had"))

    assert warehouse.ensure_warehouse(tmp_path) == "state-2026-10-11"


def test_a_good_download_becomes_the_served_warehouse(tmp_path, monkeypatch):
    monkeypatch.setenv("WAREHOUSE_REPO", "owner/repo")
    monkeypatch.setattr(warehouse, "_fetch_releases",
                        lambda *a, **k: [_release("state-2026-10-11", ["warehouse.duckdb"])])

    def publish(repo, asset_id, dest, timeout):
        _a_working_warehouse(dest)
        return dest.stat().st_size

    monkeypatch.setattr(warehouse, "_download", publish)

    assert warehouse.ensure_warehouse(tmp_path) == "state-2026-10-11"
    assert (tmp_path / "warehouse.tag").read_text() == "state-2026-10-11"
    assert warehouse.state["origin"] == "fetched"
