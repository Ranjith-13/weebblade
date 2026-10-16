"""The third copy, somewhere that is not GitHub.

Everything this project has ever collected lives in two places: GitHub releases
(pipeline/state.py) and whichever machine last ran the pipeline. Two copies in
two places is one short of the usual rule, and the gap is narrow but real - not
"the laptop dies", which releases already cover, but "the account goes AND the
laptop goes", which nothing does.

So each week's state.tar.gz is also pushed to a GitLab project's generic package
registry. Chosen after checking the alternatives rather than by reputation:
Codeberg caps private repositories at 100 MiB and asks people not to use git as
cloud storage, Zenodo mints a permanent DOI per deposit and is a research
archive rather than a backup target, and Hugging Face was breached in July 2026
through its dataset-processing pipeline, which is precisely the surface a
dataset backup would sit on. GitLab is free, takes no payment method, and is a
different company from GitHub, which is the only property that matters here.

WHAT THIS IS NOT PROTECTING

Confidentiality. The warehouse is derived from public anime APIs - every score
and airdate in it is on three websites already - so a reader of this mirror
learns nothing. The one real secret, MAL's client secret, lives in .env and
never enters the lake. GitLab's 2026 run of maximum-severity CVEs therefore
does not disqualify it for this job the way it would for a primary store: the
failures that matter here are the copy being GONE or being SILENTLY WRONG.

Gone is survivable, because this is the third copy and the other two answer.
Silently wrong is the one that hurts, because it is discovered on the day it is
needed - so every upload is read back and checksummed, and the digest is written
to MIRROR.md in the repository. A mirror nobody verifies is a belief, not a
backup.

NOTHING HERE MAY FAIL A RUN. The pipeline's job is the catalogue; this is
insurance on the side of it. mirror() catches everything and returns a result
object, the same discipline the RUNS.md push learned the hard way - a run that
did every piece of real work once went red on a one-line changelog.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .state import STATE_ASSET, TAG_PREFIX

logger = logging.getLogger(__name__)

# gitlab.com/weebblade/weebblade-state. Not a secret - a project id is in every
# URL the project has - so it is written here where it can be read and changed
# rather than hidden in an environment variable nobody can see.
PROJECT_ID = 87704833
API = "https://gitlab.com/api/v4"
PACKAGE = "state"

# The ledger. One line per mirrored run, committed to the repository, so the
# digest of what GitLab holds lives somewhere GitLab does not.
LEDGER = Path("MIRROR.md")

# Keep the last eight weeks outright, then one a month for a year. The namespace
# quota on GitLab's free tier is 5 GiB and a state tarball is ~39 MB, so an
# unpruned mirror would fill it in about two and a half years - quietly, since
# the failure would be a rejected upload on a step that is not allowed to fail
# the run. Twenty snapshots is ~800 MB and never grows.
KEEP_RECENT = 8
KEEP_MONTHLY = 12

TIMEOUT = 120


@dataclass
class Result:
    """What happened, in a form the workflow can print and a test can assert."""

    ok: bool
    detail: str
    version: str | None = None
    digest: str | None = None

    def __str__(self) -> str:
        return self.detail


def _token() -> str | None:
    return (os.environ.get("GITLAB_TOKEN") or "").strip() or None


def _request(
    method: str, path: str, token: str, data: bytes | None = None
) -> tuple[int, bytes]:
    """One call to GitLab. Returns the status rather than raising on 4xx, because
    several of them are ordinary answers here - a 404 listing packages is an
    empty registry, not a fault."""
    request = urllib.request.Request(f"{API}/{path}", data=data, method=method)
    request.add_header("PRIVATE-TOKEN", token)
    request.add_header("User-Agent", "weebblade-mirror")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def digest_of(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            sha.update(block)
    return sha.hexdigest()


def upload(archive: Path, version: str, token: str) -> None:
    """PUT the file into the generic package registry under `version`.

    Generic packages rather than the git repository: a 39 MB binary a week in
    git history is unrecoverable once it is in there, and LFS on the free tier
    shares the same 5 GiB. A package version can simply be deleted.
    """
    name = urllib.parse.quote(STATE_ASSET, safe="")
    status, body = _request(
        "PUT",
        f"projects/{PROJECT_ID}/packages/generic/{PACKAGE}/{version}/{name}",
        token,
        archive.read_bytes(),
    )
    if status not in (200, 201):
        raise RuntimeError(f"upload returned {status}: {body[:300]!r}")


def download(version: str, into: Path, token: str) -> Path:
    """Read a mirrored copy back. This is what makes it a backup rather than a
    belief: every week's upload is fetched again and checksummed before the run
    calls it done."""
    name = urllib.parse.quote(STATE_ASSET, safe="")
    status, body = _request(
        "GET", f"projects/{PROJECT_ID}/packages/generic/{PACKAGE}/{version}/{name}", token
    )
    if status != 200:
        raise RuntimeError(f"download returned {status}")
    into.write_bytes(body)
    return into


def versions(token: str) -> list[str]:
    """Every mirrored version, newest date first."""
    status, body = _request(
        "GET", f"projects/{PROJECT_ID}/packages?per_page=100&package_type=generic", token
    )
    if status != 200:
        return []
    found = [
        str(p.get("version"))
        for p in json.loads(body or b"[]")
        if p.get("name") == PACKAGE and p.get("version")
    ]
    return sorted(found, reverse=True)


def _package_ids(token: str) -> dict[str, int]:
    status, body = _request(
        "GET", f"projects/{PROJECT_ID}/packages?per_page=100&package_type=generic", token
    )
    if status != 200:
        return {}
    return {
        str(p["version"]): int(p["id"])
        for p in json.loads(body or b"[]")
        if p.get("name") == PACKAGE and p.get("version") and p.get("id")
    }


def keepers(all_versions: list[str], recent: int = KEEP_RECENT,
            monthly: int = KEEP_MONTHLY) -> set[str]:
    """Which versions survive a prune: the newest `recent`, then the newest of
    each month going back `monthly` months.

    Thinning rather than a flat window, because the two failures a backup is for
    have different ages. "Last week's run corrupted something" needs the last
    few weeks; "this was wrong months ago and nobody noticed" needs a sparse
    tail. A flat eight-week window answers only the first.
    """
    keep = set(all_versions[:recent])
    by_month: dict[str, str] = {}
    for version in all_versions:
        by_month.setdefault(version[:7], version)  # "2026-10", newest first
    keep |= set(list(by_month.values())[:monthly])
    return keep


def prune(token: str) -> list[str]:
    ids = _package_ids(token)
    keep = keepers(sorted(ids, reverse=True))
    gone = []
    for version, package_id in ids.items():
        if version in keep:
            continue
        status, _ = _request("DELETE", f"projects/{PROJECT_ID}/packages/{package_id}", token)
        if status in (200, 202, 204):
            gone.append(version)
    return gone


def record(version: str, digest: str, size: int, ledger: Path = LEDGER) -> None:
    """Write the digest where GitLab cannot reach it.

    The whole point of the ledger: if the mirror is ever corrupted or replaced,
    the evidence is in a different company's git history, and comparing is a
    `sha256sum` rather than an act of faith. Newest first, like RUNS.md.
    """
    line = f"- {version} `{digest}` {size / 1e6:.1f} MB\n"
    head = (
        "# Mirror ledger\n\n"
        "SHA-256 of each `state.tar.gz` mirrored to GitLab, newest first. Written\n"
        "here so the digest lives somewhere the mirror does not: see pipeline/mirror.py.\n"
        "To check a copy by hand: download it and run `sha256sum state.tar.gz`.\n\n"
    )
    existing = ledger.read_text(encoding="utf-8") if ledger.exists() else head
    if not existing.startswith("# Mirror ledger"):
        existing = head + existing
    body = existing[len(head):] if existing.startswith(head) else ""
    ledger.write_text(head + line + body, encoding="utf-8")


def fetch_published(run_date: str, into: Path) -> Path:
    """Get the state asset back out of its GitHub release.

    Downloaded rather than taken from the lake, and deliberately: publish_state
    deletes its tarball once uploaded, and rebuilding one here would mirror a
    file that nothing else ever had. Reading GitHub's own copy means the mirror
    is byte-for-byte what the primary holds - and proves that the primary is
    downloadable, which is itself worth knowing once a week.
    """
    _gh("release", "download", f"{TAG_PREFIX}{run_date}", "--pattern", STATE_ASSET,
        "--dir", str(into), "--clobber")
    return into / STATE_ASSET


def newest_published() -> str | None:
    """The run date of the newest GitHub release that actually carries state.

    Asset-aware for the reason state._releases is: "the newest release" and "the
    newest release that has what I need" are different questions, and a release
    can hold a warehouse and no state.
    """
    from .state import _releases

    tags = _releases(carrying=STATE_ASSET)
    return tags[0][len(TAG_PREFIX):] if tags else None


def mirror(run_date: str, ledger: Path = LEDGER) -> Result:
    """Copy this run's state to GitLab, read it back, and record the digest.

    Never raises. The caller is a pipeline step that must not fail the run.
    """
    token = _token()
    if token is None:
        return Result(False, "No GITLAB_TOKEN set - skipping the mirror")

    try:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            archive = fetch_published(run_date, work)
            sent = digest_of(archive)
            size = archive.stat().st_size

            upload(archive, run_date, token)

            # Read it back. An upload that returned 201 and stored something
            # else is exactly the failure this whole file exists to catch.
            back = download(run_date, work / "verify.tar.gz", token)
            got = digest_of(back)
            if got != sent:
                return Result(
                    False,
                    f"Mirror of {run_date} read back with digest {got[:12]}, "
                    f"expected {sent[:12]} - the copy is NOT good",
                )

        record(run_date, sent, size, ledger)
        removed = prune(token)
        detail = f"Mirrored {run_date} to GitLab, verified {sent[:12]} ({size / 1e6:.1f} MB)"
        if removed:
            detail += f"; pruned {len(removed)} old version(s)"
        return Result(True, detail, version=run_date, digest=sent)
    except Exception as exc:  # noqa: BLE001 - a backup must not fail the run
        logger.warning("Mirror failed", exc_info=True)
        return Result(False, f"Mirror of {run_date} failed: {exc}")


def verify_newest() -> Result:
    """Download whatever GitLab currently holds and check it against MIRROR.md.

    The thing nobody does until the day it matters. Run it whenever you want to
    know the backup is real: `python -m pipeline.mirror --verify`.
    """
    token = _token()
    if token is None:
        return Result(False, "No GITLAB_TOKEN set")
    try:
        found = versions(token)
        if not found:
            return Result(False, "GitLab holds no mirrored state at all")
        newest = found[0]
        recorded = None
        if LEDGER.exists():
            for line in LEDGER.read_text(encoding="utf-8").splitlines():
                if line.startswith(f"- {newest} "):
                    recorded = line.split("`")[1]
                    break
        with tempfile.TemporaryDirectory() as tmp:
            got = digest_of(download(newest, Path(tmp) / STATE_ASSET, token))
        if recorded is None:
            return Result(True, f"{newest} is on GitLab ({got[:12]}), not yet in {LEDGER}",
                          version=newest, digest=got)
        if got != recorded:
            return Result(False, f"{newest} on GitLab is {got[:12]}, "
                                 f"{LEDGER} says {recorded[:12]} - they DISAGREE")
        return Result(True, f"{newest} verified against {LEDGER} ({got[:12]})",
                      version=newest, digest=got)
    except Exception as exc:  # noqa: BLE001
        return Result(False, f"Verify failed: {exc}")


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true",
                        help="check what GitLab holds against MIRROR.md")
    parser.add_argument(
        "--run-date", default=None,
        help="which release to mirror; defaults to the newest carrying state",
    )
    args = parser.parse_args()

    if args.verify:
        print(verify_newest())
    else:
        # Not today's date by default: a manual run, or a weekly run that failed
        # before publishing, would ask for a release that does not exist and
        # report a gh failure instead of mirroring the state that IS there.
        when = args.run_date or newest_published()
        print(mirror(when) if when else Result(False, "No published state to mirror"))
