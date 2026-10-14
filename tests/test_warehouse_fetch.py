"""The API fetching the warehouse it serves.

Everything here is about one question: when something goes wrong, does the
service keep serving what it already had? A free container has no persistent
disk, so it downloads the catalogue on every wake-up, which turns every GitHub
hiccup into a user-visible event unless the failure path is the careful one.
"""

import urllib.error

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


# RETRYING, AND THE ONE CASE IT IS FOR.
#
# On 14 October 2026 a wake-up's fetch failed and the container served 503 to
# everything until it slept again, taking a CI build with it. Nothing retried.
# The tests below pin both halves of the fix: it tries again when it has nothing
# to serve, and it does not when it has.


@pytest.fixture
def slept(monkeypatch):
    """Records the backoff instead of taking it, so a retry test stays instant."""
    waits: list[float] = []
    monkeypatch.setattr(warehouse.time, "sleep", waits.append)
    return waits


def _publishes(dest):
    _a_working_warehouse(dest)
    return dest.stat().st_size


def test_a_transient_failure_with_nothing_to_serve_is_tried_again(tmp_path, monkeypatch, slept):
    """The failure this was written for. An empty disk plus a shrug is a process
    that answers 503 for as long as it lives: the six-hourly refresh is the only
    other chance it gets, and on a container that sleeps after fifteen idle
    minutes that refresh will rarely fire at all."""
    monkeypatch.setenv("WAREHOUSE_REPO", "owner/repo")
    calls = []

    def flaky(repo, timeout):
        calls.append(repo)
        if len(calls) == 1:
            raise OSError("connection reset")
        return [_release("state-2026-10-11", ["warehouse.duckdb"])]

    monkeypatch.setattr(warehouse, "_fetch_releases", flaky)
    monkeypatch.setattr(warehouse, "_download",
                        lambda repo, asset_id, dest, timeout: _publishes(dest))

    assert warehouse.ensure_warehouse(tmp_path) == "state-2026-10-11"
    assert len(calls) == 2
    assert slept == [warehouse.BACKOFF[0]]


def test_a_transient_failure_is_not_retried_when_there_is_a_warehouse_to_serve(
    tmp_path, monkeypatch, slept
):
    """The other half, and the reason this is not just "retry everything". A
    stale catalogue is a fine answer, so a reader's first request should not
    wait behind attempts at a fresher one."""
    monkeypatch.setenv("WAREHOUSE_REPO", "owner/repo")
    _a_working_warehouse(tmp_path / "warehouse.duckdb")
    (tmp_path / "warehouse.tag").write_text("state-2026-10-04")
    calls = []

    def down(repo, timeout):
        calls.append(repo)
        raise OSError("name resolution failed")

    monkeypatch.setattr(warehouse, "_fetch_releases", down)

    assert warehouse.ensure_warehouse(tmp_path) == "state-2026-10-04"
    assert len(calls) == 1
    assert slept == []


def test_a_bad_token_is_not_retried(tmp_path, monkeypatch, slept):
    """A 401 answers the same way in five seconds as it does now, and three
    attempts at a certain answer only delay the service starting. The fix is a
    new token, which the log line says."""
    monkeypatch.setenv("WAREHOUSE_REPO", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "expired")
    calls = []

    def unauthorised(repo, timeout):
        calls.append(repo)
        raise urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(warehouse, "_fetch_releases", unauthorised)

    assert warehouse.ensure_warehouse(tmp_path) is None
    assert len(calls) == 1
    assert slept == []


def test_github_being_down_is_retried_and_then_given_up_on(tmp_path, monkeypatch, slept):
    """Still never raises. After the last attempt the process starts anyway and
    answers 503, which is the state /health reports and the refresher can still
    recover from - the point of the retry is to make that rare, not impossible."""
    monkeypatch.setenv("WAREHOUSE_REPO", "owner/repo")
    calls = []

    def unavailable(repo, timeout):
        calls.append(repo)
        raise urllib.error.HTTPError("url", 503, "Service Unavailable", {}, None)

    monkeypatch.setattr(warehouse, "_fetch_releases", unavailable)

    assert warehouse.ensure_warehouse(tmp_path) is None
    assert len(calls) == warehouse.ATTEMPTS
    assert slept == list(warehouse.BACKOFF)


def test_a_download_that_will_not_open_is_tried_again_with_nothing_to_serve(
    tmp_path, monkeypatch, slept
):
    """A file that will not open is usually a read that ended early rather than
    a published asset that is actually broken. It costs another 37 MB, which is
    why only the empty-disk case pays it."""
    monkeypatch.setenv("WAREHOUSE_REPO", "owner/repo")
    monkeypatch.setattr(warehouse, "_fetch_releases",
                        lambda *a, **k: [_release("state-2026-10-11", ["warehouse.duckdb"])])
    downloads = []

    def truncated_once(repo, asset_id, dest, timeout):
        downloads.append(asset_id)
        if len(downloads) == 1:
            dest.write_bytes(b"DUCK" + b"\x00" * 200)
            return 204
        return _publishes(dest)

    monkeypatch.setattr(warehouse, "_download", truncated_once)

    assert warehouse.ensure_warehouse(tmp_path) == "state-2026-10-11"
    assert len(downloads) == 2
    assert not (tmp_path / "warehouse.duckdb.part").exists()
