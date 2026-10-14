"""Where the served warehouse comes from, on a box that has no lake.

Until October 2026 the API read a file on a volume the pipeline also wrote to:
one machine, one directory, both inside the same Docker Compose stack. That
machine is gone, and the thing replacing it - a free container rebuilt from its
image on every wake, with no persistent disk at all - cannot work that way. So
the API fetches what it serves.

What it fetches is processing/publish.materialise's output, published by the
weekly run as a release asset (pipeline/state.publish_warehouse): one 37 MB
DuckDB file holding the catalogue and the 6,349 embedding vectors as tables
rather than views, so it depends on nothing outside itself. That artifact was
built for exactly this and had no reader until now.

WHY THE GITHUB API AND NOT A PLAIN URL

A release has one asset per run date, and only the weekly run publishes a
warehouse - so on most days the newest release does not have one, and
/releases/latest/download/warehouse.duckdb would 404 for six days out of seven.
Asking which releases exist and taking the newest that actually carries the
asset is the only correct version of this.

ABOUT THE TOKEN

Optional, and which way it should go depends on whether the repository is
public. A private one cannot be read without it. A public one can, but
unauthenticated GitHub API calls are limited to 60 an hour PER IP, and a free
container's outbound address is shared with other tenants - so a token
(fine-grained, Contents: read, this repository only) is the difference between
"60 an hour, shared with strangers" and 5,000 of our own. Set GITHUB_TOKEN
either way.

WHAT IT REFUSES TO DO

Replace a working warehouse with a broken one. A half-finished download that
becomes the served file is worse than a stale one, because it looks like
success and answers every query with an error. So the file lands beside the
real one, is opened and queried, and only then replaces it - the same
reasoning, in the other direction, as publish_state refusing to upload an empty
archive.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# Mirrors pipeline/state.py. Not imported from it: that module shells out to the
# gh CLI, which is not installed where this runs, and importing it would drag a
# pipeline dependency into the serving process for two string constants.
TAG_PREFIX = "state-"
ASSET_NAME = "warehouse.duckdb"

# How many releases back to look. Eight are kept (state.KEEP_RELEASES), and the
# newest weekly is at most seven dailies back, so this covers every case with
# room to spare.
LOOK_BACK = 30

# What a usable warehouse has to answer. Cheap, and it is the only check that
# distinguishes "a DuckDB file" from "the file this API serves": a truncated
# download usually fails to open at all, but one that opens and holds nothing
# would otherwise be published as good.
_PROBE = "SELECT count(*) FROM anime_media_latest"

# Reported by /health, so the live service can be asked which day's catalogue it
# is actually serving - a question that has no answer anywhere else once the
# file is fetched rather than mounted.
state: dict[str, object] = {"tag": None, "origin": None}

# HOW HARD TO TRY, AND WHEN TRYING AGAIN IS WORTH ANYTHING AT ALL.
#
# On 14 October 2026 one wake-up's fetch failed and the container then served
# 503 to every request until it slept again - taking a CI build with it, and a
# production deploy had the timing differed. Nothing retried, because the
# never-raises rule below reads the same whether or not there is a catalogue on
# disk to fall back to.
#
# Those two cases are not the same, and the difference is the whole of this:
#
#   - Something on disk. A failure costs freshness. A reader sees last week's
#     catalogue and the next refresh tries again. Retrying here would hold up
#     startup to avoid an outcome that is already acceptable.
#   - Nothing on disk. A failure costs everything, and it does not heal: the API
#     answers 503 until the next refresh, and on a container that sleeps after
#     fifteen idle minutes that refresh will rarely fire at all (REFRESH_HOURS).
#
# So the retry is spent only where there is nothing to fall back to. Three
# attempts a few seconds apart covers what actually goes wrong - a dropped
# connection, a 5xx, a read that ends early - and is short enough that it can
# never be the reason a wake-up times out. It blocks startup, which is already
# true of the download it is retrying, and nothing is being served yet.
ATTEMPTS = 3
BACKOFF = (2.0, 5.0)


def _db_path(data_dir: Path) -> Path:
    return data_dir / ASSET_NAME


def _tag_path(data_dir: Path) -> Path:
    return data_dir / "warehouse.tag"


class _DropAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """Keeps the token from following the download off GitHub's own host.

    An asset download answers 302 to objects.githubusercontent.com, which
    carries its own credentials in the query string and rejects a request that
    also has an Authorization header ("Only one auth mechanism allowed").
    urllib copies every header onto the redirected request, so without this the
    download fails - and only for private repositories, i.e. only where it was
    tested least.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urlsplit(newurl).netloc != urlsplit(req.full_url).netloc:
            new.remove_header("Authorization")
        return new


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_DropAuthOnRedirect)


def _headers(accept: str) -> dict[str, str]:
    headers = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "weebblade-api"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def newest_warehouse(releases: list[dict]) -> tuple[str, int] | None:
    """The newest state release that actually carries a warehouse asset.

    Pure, so the choosing is testable without the network. Ordered by the tag's
    date rather than by the order GitHub returned them: the tags are
    state-YYYY-MM-DD, which sorts correctly as text, and a release created
    out of order (a backfill, a rerun) should not win on position alone.
    """
    with_asset = [
        (r["tag_name"], asset["id"])
        for r in releases
        if isinstance(r.get("tag_name"), str) and r["tag_name"].startswith(TAG_PREFIX)
        for asset in r.get("assets") or []
        if asset.get("name") == ASSET_NAME
    ]
    if not with_asset:
        return None
    return max(with_asset, key=lambda pair: pair[0])


def _fetch_releases(repo: str, timeout: float) -> list[dict]:
    url = f"{GITHUB_API}/repos/{repo}/releases?per_page={LOOK_BACK}"
    request = urllib.request.Request(url, headers=_headers("application/vnd.github+json"))
    with _opener().open(request, timeout=timeout) as response:
        return json.loads(response.read())


def _download(repo: str, asset_id: int, dest: Path, timeout: float) -> int:
    url = f"{GITHUB_API}/repos/{repo}/releases/assets/{asset_id}"
    request = urllib.request.Request(url, headers=_headers("application/octet-stream"))
    written = 0
    with _opener().open(request, timeout=timeout) as response, dest.open("wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
            written += len(chunk)
    return written


def _is_usable(path: Path) -> bool:
    import duckdb

    try:
        con = duckdb.connect(str(path), read_only=True)
    except Exception:
        logger.warning("Downloaded warehouse will not open", exc_info=True)
        return False
    try:
        (count,) = con.execute(_PROBE).fetchone()
        if not count:
            logger.warning("Downloaded warehouse opens but holds no titles")
            return False
        return True
    except Exception:
        logger.warning("Downloaded warehouse is missing the catalogue", exc_info=True)
        return False
    finally:
        con.close()


def current_tag(data_dir: Path) -> str | None:
    """Which published warehouse is on disk, if one was fetched."""
    tag_file, db = _tag_path(data_dir), _db_path(data_dir)
    if db.exists() and tag_file.exists():
        return tag_file.read_text().strip() or None
    return None


def ensure_warehouse(data_dir: Path, timeout: float = 60.0) -> str | None:
    """Make sure the newest published warehouse is on disk, and say which it is.

    Does nothing at all unless WAREHOUSE_REPO is set, which is what keeps a
    local run working untouched: there the warehouse is already on disk, built
    by the pipeline that just ran, and downloading over it would at best waste a
    minute and at worst replace it. Fetching is opt-in, and the service that
    needs it asks.

    Never raises. Every failure here - GitHub down, rate limited, no weekly run
    yet, a corrupt asset - leaves whatever was already on disk in place and
    lets the API answer from it. A serving process that refuses to start because
    a release could not be listed is strictly worse than one that serves last
    week's catalogue.

    What it does NOT do any more is shrug at a failure that leaves it with
    nothing. With an empty disk the same shrug means answering 503 to every
    request for as long as the process lives, so that case gets ATTEMPTS tries
    before it gives up. See the note above those constants: the two failures
    look identical in the code and are nothing alike in effect.
    """
    repo = os.environ.get("WAREHOUSE_REPO")
    db = _db_path(data_dir)

    # Reported before anything can fail, so /health describes what is actually
    # being served even on a run where the check could not be made. A tag file
    # beside the warehouse means some process fetched it, even if this one was
    # not asked to - where the file came from is the question being asked, not
    # what this process did about it.
    have = current_tag(data_dir)
    state.update(tag=have,
                 origin="fetched" if have else "mounted" if db.exists() else None)
    if not repo:
        return have

    for attempt in range(ATTEMPTS):
        tag, worth_retrying = _fetch_once(repo, data_dir, have, timeout)
        if tag is not None:
            return tag
        # Anything already on disk is an answer, so the service starts with it
        # rather than spending a reader's first request on a second attempt.
        if have is not None or not worth_retrying or attempt == ATTEMPTS - 1:
            return have
        pause = BACKOFF[attempt]
        logger.warning(
            "No warehouse to serve and the fetch failed; retrying in %.0fs (%d of %d)",
            pause, attempt + 2, ATTEMPTS,
        )
        time.sleep(pause)

    return have


def _fetch_once(
    repo: str, data_dir: Path, have: str | None, timeout: float
) -> tuple[str | None, bool]:
    """One attempt, as (the tag now on disk, whether another attempt could help).

    A tag means there is something to serve: either a fresh download or the one
    already there being the newest published. None means this attempt produced
    nothing, and the flag says whether that is worth sleeping on.

    WHAT COUNTS AS WORTH RETRYING is the narrow question of whether the same
    request could answer differently in five seconds. A dropped connection, a
    5xx, a 429, a download that ends early: yes. A 401, a 403 with no token, a
    repository with no warehouse published yet: no, and burning three attempts
    on a certain answer only delays the service starting.
    """
    try:
        newest = newest_warehouse(_fetch_releases(repo, timeout))
    except urllib.error.HTTPError as exc:
        # Name the two that have a specific fix, because a year from now the
        # symptom is identical in both cases - a warehouse that stops updating
        # and then, after a restart, 503s - and the fixes are opposites.
        #
        # 401 is the token: expired, revoked, or wrong. Fine-grained tokens last
        # a year at most, so this one is not hypothetical, it is scheduled. It
        # is not predicted here on purpose: GitHub does send a
        # GitHub-Authentication-Token-Expiration header, but it is documented as
        # unreliable for fine-grained tokens - returning server time, or a
        # minute from now - and a warning that fires falsely is worse than none.
        # So this says it plainly once it has actually happened.
        #
        # 403/429 with no token at all is the shared-IP rate limit, where the
        # fix is a token rather than a retry.
        if exc.code == 401:
            hint = " - GITHUB_TOKEN is expired, revoked or wrong"
        elif exc.code in (403, 429) and not os.environ.get("GITHUB_TOKEN"):
            hint = " - rate limited with no GITHUB_TOKEN set (60/hour per IP, shared)"
        else:
            hint = ""
        logger.warning("Could not list releases of %s: HTTP %s%s", repo, exc.code, hint)
        # A token problem and a shared-IP limit both answer the same way next
        # second; a 5xx or a secondary limit may not.
        return None, exc.code >= 500 or (exc.code == 429 and bool(os.environ.get("GITHUB_TOKEN")))
    except Exception:
        # Unreachable, timed out, a truncated JSON body. All transient.
        logger.warning("Could not list releases of %s", repo, exc_info=True)
        return None, True

    if newest is None:
        logger.warning("No release of %s carries a %s yet - nothing to serve",
                       repo, ASSET_NAME)
        return None, False

    tag, asset_id = newest
    if tag == have:
        logger.info("Already serving the newest published warehouse (%s)", tag)
        return tag, False

    data_dir.mkdir(parents=True, exist_ok=True)
    db = _db_path(data_dir)
    staged = db.with_name(db.name + ".part")
    try:
        size = _download(repo, asset_id, staged, timeout)
    except Exception:
        logger.warning("Could not download %s from %s", ASSET_NAME, tag, exc_info=True)
        staged.unlink(missing_ok=True)
        return None, True

    if not _is_usable(staged):
        staged.unlink(missing_ok=True)
        logger.warning("Keeping the existing warehouse (%s) rather than a bad download",
                       have or "none")
        # Worth another go: a file that will not open is usually a read that
        # ended early rather than a published asset that is actually broken. It
        # costs another 37 MB, which is why only the empty-disk case pays it.
        return None, True

    # os.replace, not a copy: atomic on the same filesystem, so no request can
    # ever see a partly written file. Connections already open keep reading the
    # old inode until they close, which is correct - a request mid-flight
    # finishes against the catalogue it started on.
    staged.replace(db)
    _tag_path(data_dir).write_text(tag)
    state.update(tag=tag, origin="fetched")
    logger.info("Serving warehouse from %s (%.1f MB)", tag, size / 1e6)
    return tag, False
