"""The third copy of the state, and whether it can be trusted.

The failure this guards against is not a dramatic one. It is an upload that
returns 201, a ledger line that looks right, and a file on GitLab that is not
what the digest says - discovered on the day somebody needs it, which is the one
day it cannot be fixed.
"""

from datetime import date, timedelta
from pathlib import Path

import pytest

from pipeline import mirror as m


@pytest.fixture
def archive(tmp_path):
    path = tmp_path / "state.tar.gz"
    path.write_bytes(b"a lake, tarred" * 1000)
    return path


class _GitLab:
    """A registry that stores what it is given, unless told to misbehave."""

    def __init__(self, corrupt=False, fail_upload=False):
        self.store: dict[str, bytes] = {}
        self.packages: list[dict] = []
        self.deleted: list[int] = []
        self.corrupt, self.fail_upload = corrupt, fail_upload
        self._next_id = 1

    def __call__(self, method, path, token, data=None):
        if method == "PUT" and "/packages/generic/" in path:
            if self.fail_upload:
                return 403, b'{"message":"forbidden"}'
            version = path.split("/generic/")[1].split("/")[1]
            self.store[version] = b"not what you sent" if self.corrupt else data
            self.packages.append({"id": self._next_id, "name": m.PACKAGE, "version": version})
            self._next_id += 1
            return 201, b""
        if method == "GET" and "/packages/generic/" in path:
            version = path.split("/generic/")[1].split("/")[1]
            return (200, self.store[version]) if version in self.store else (404, b"")
        if method == "GET" and "/packages?" in path:
            import json
            return 200, json.dumps(self.packages).encode()
        if method == "GET" and path.endswith("/package_files"):
            import json
            package_id = int(path.split("/packages/")[1].split("/")[0])
            version = next(
                (p["version"] for p in self.packages if p["id"] == package_id), None
            )
            size = len(self.store.get(version, b""))
            return 200, json.dumps([{"size": size}]).encode()
        if method == "DELETE":
            package_id = int(path.rsplit("/", 1)[1])
            self.deleted.append(package_id)
            self.packages = [p for p in self.packages if p["id"] != package_id]
            return 204, b""
        raise AssertionError(f"unexpected {method} {path}")


@pytest.fixture
def gitlab(monkeypatch, archive):
    """A stubbed registry, with the GitHub side returning a fixed tarball."""
    def _build(**kwargs):
        api = _GitLab(**kwargs)
        monkeypatch.setattr(m, "_request", api)
        monkeypatch.setattr(m, "fetch_published", lambda run_date, into: archive)
        monkeypatch.setenv("GITLAB_TOKEN", "a-token")
        return api
    return _build


def test_a_mirrored_copy_is_read_back_and_checksummed(gitlab, archive, tmp_path):
    """An upload is not a backup until something has read it again."""
    api = gitlab()
    ledger = tmp_path / "MIRROR.md"

    result = m.mirror("2026-10-18", ledger)

    assert result.ok, result.detail
    assert result.digest == m.digest_of(archive)
    assert api.store["2026-10-18"] == archive.read_bytes()
    assert "verified" in result.detail


def test_a_copy_that_reads_back_wrong_is_reported_as_not_good(gitlab, tmp_path):
    """THE TEST THIS FILE EXISTS FOR. The registry accepts the upload and then
    holds something else; the run must say so rather than record a digest for a
    file that does not match it."""
    gitlab(corrupt=True)
    ledger = tmp_path / "MIRROR.md"

    result = m.mirror("2026-10-18", ledger)

    assert not result.ok
    assert "NOT good" in result.detail
    # And nothing is written to the ledger, which would otherwise assert that a
    # bad copy is a good one.
    assert not ledger.exists()


def test_a_failed_upload_never_raises(gitlab, tmp_path):
    """The caller is a pipeline step. A backup must not fail a run."""
    gitlab(fail_upload=True)

    result = m.mirror("2026-10-18", tmp_path / "MIRROR.md")

    assert not result.ok
    assert "403" in result.detail


def test_without_a_token_it_says_so_and_stops(monkeypatch, tmp_path):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)

    result = m.mirror("2026-10-18", tmp_path / "MIRROR.md")

    assert not result.ok
    assert "GITLAB_TOKEN" in result.detail


def test_the_ledger_is_newest_first_and_keeps_what_came_before(tmp_path):
    ledger = tmp_path / "MIRROR.md"

    m.record("2026-10-11", "a" * 64, 39_000_000, ledger)
    m.record("2026-10-18", "b" * 64, 39_500_000, ledger)

    lines = [l for l in ledger.read_text().splitlines() if l.startswith("- ")]
    assert lines[0].startswith("- 2026-10-18") and "b" * 64 in lines[0]
    assert lines[1].startswith("- 2026-10-11")
    assert ledger.read_text().startswith("# Mirror ledger")


def test_retention_keeps_recent_weeks_and_thins_the_tail():
    """Two different failures need two different ages of copy: "last week broke
    something" wants the last few weeks, "this was wrong months ago" wants a
    sparse tail. A flat window answers only the first."""
    weekly = [(date(2026, 10, 18) - timedelta(weeks=n)).isoformat() for n in range(60)]

    keep = m.keepers(sorted(weekly, reverse=True))

    # The eight most recent, outright.
    assert set(sorted(weekly, reverse=True)[:8]) <= keep
    # One per month thereafter, and not all sixty.
    assert len(keep) < 25
    assert len({v[:7] for v in keep}) >= 12


def test_pruning_deletes_only_what_retention_drops(gitlab, archive, tmp_path):
    api = gitlab()
    ledger = tmp_path / "MIRROR.md"
    uploaded = [(date(2026, 10, 18) - timedelta(weeks=n)).isoformat() for n in range(14)]
    for version in uploaded:
        m.mirror(version, ledger)

    surviving = {p["version"] for p in api.packages}

    # Against keepers of EVERYTHING UPLOADED, not of what happens to be left.
    # Comparing the survivors to keepers(survivors) is true for any subset and
    # proves nothing - keepers() only ever returns a subset of what it is given.
    assert surviving == m.keepers(sorted(uploaded, reverse=True))
    assert api.deleted, "a 14-week upload with KEEP_RECENT=8 must drop something"
    assert uploaded[0] in surviving, "the newest copy is never pruned"
    assert uploaded[-1] not in surviving or len(uploaded) <= m.KEEP_RECENT


def test_verify_reports_a_disagreement_between_gitlab_and_the_ledger(gitlab, monkeypatch, tmp_path):
    """The check somebody runs on the day they are worried."""
    api = gitlab()
    ledger = tmp_path / "MIRROR.md"
    m.mirror("2026-10-18", ledger)
    monkeypatch.setattr(m, "LEDGER", ledger)

    assert m.verify_newest().ok

    # Something replaces the stored bytes without touching the ledger.
    api.store["2026-10-18"] = b"tampered"
    result = m.verify_newest()

    assert not result.ok
    assert "DISAGREE" in result.detail


# WHAT GITLAB IS HOLDING, said on every run.
#
# The comment above KEEP_RECENT used to put a state tarball at ~39 MB and twenty
# of them at "~800 MB and never grows". Within a fortnight a tarball was 73 MB -
# the 40-season backfill added 12 and persisting the search vectors 21 - so
# twenty is ~1.4 GiB, and it tracks the catalogue rather than standing still.
#
# The quota is years away at that rate, which is exactly why it needs saying out
# loud: the failure is a rejected upload on a step that is not allowed to fail
# the run, so nothing would report it. These check the run says what is held,
# and shouts before it matters rather than after.


def test_a_run_reports_what_gitlab_is_holding(gitlab, tmp_path):
    gitlab()
    ledger = tmp_path / "MIRROR.md"

    result = m.mirror("2026-10-19", ledger=ledger)

    assert result.ok
    assert "GitLab holds 1 version(s)" in result.detail
    assert "GiB" in result.detail


def test_the_note_shouts_only_once_the_namespace_is_filling(monkeypatch):
    """Below the threshold it is a fact on a line nobody needs to read; above it
    the line has to be the thing that gets noticed."""
    monkeypatch.setattr(m, "QUOTA_BYTES", 1000)

    assert "RUNNING OUT" not in m.quota_note(600, 8)
    assert "RUNNING OUT" in m.quota_note(700, 20)
    assert "60%" in m.quota_note(600, 8)


def test_occupied_sums_every_version_gitlab_still_has(gitlab, tmp_path):
    """Asked of GitLab, not summed from the ledger: MIRROR.md records every run
    ever mirrored, including the ones since pruned."""
    api = gitlab()
    for day in ("2026-10-05", "2026-10-12", "2026-10-19"):
        m.mirror(day, ledger=tmp_path / "MIRROR.md")

    held, kept = m.occupied("a-token")

    assert kept == 3
    assert held == sum(len(v) for v in api.store.values())


def test_accounting_that_fails_does_not_fail_the_backup(gitlab, monkeypatch, tmp_path):
    """A report is not worth a mirror. If GitLab will not say what it holds, the
    copy that was just verified still stands and the run says so.

    Patched at occupied rather than at the request underneath it: prune() asks
    the same endpoint first, so breaking that one tests prune's error handling
    and never reaches this. The first version of this test did exactly that,
    and asserted a disjunction that was true either way - it passed against the
    bug it was written to catch.
    """
    gitlab()
    monkeypatch.setattr(m, "occupied", lambda token: (_ for _ in ()).throw(RuntimeError("no")))

    result = m.mirror("2026-10-19", ledger=tmp_path / "MIRROR.md")

    assert result.ok, "a verified copy must not be reported lost over its own accounting"
    assert "could not read the namespace total" in result.detail
    assert "verified" in result.detail
