from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

MAL_API_URL = "https://api.myanimelist.net/v2"

# MAL publishes no explicit public rate limit, so this is deliberately
# conservative - roughly 2 req/s, comparable to what the other sources use.
MIN_SECONDS_BETWEEN_REQUESTS = 0.5
MAX_RETRIES = 5


class MissingClientId(RuntimeError):
    """Raised when MAL_CLIENT_ID is not configured.

    A distinct type so the DAG task can report "not configured" rather than
    "MAL is down", which are very different things to see in a task log.
    """


class MalClient:
    """Minimal REST client for the OFFICIAL MyAnimeList API v2.

    Not to be confused with the community Jikan mirror, which this project
    used to fetch as a fourth source and no longer does: its public API was
    discontinued on 1 October 2026. Jikan had been returning 504
    ("MyAnimeList may be down") for the
    whole life of this project, but myanimelist.net itself answers 200 and
    api.myanimelist.net answers a well-formed "Invalid client id" - checked, not
    assumed. MAL was never the thing that was broken; Jikan was.

    Auth is a single header, not OAuth: OAuth is only needed for endpoints that
    read or write a specific user's list, and everything here is public catalogue
    data.
    """

    def __init__(self, client_id: str | None = None, session: requests.Session | None = None):
        self._client_id = client_id or os.environ.get("MAL_CLIENT_ID", "")
        if not self._client_id:
            raise MissingClientId(
                "MAL_CLIENT_ID is not set. Create one (free) at "
                "https://myanimelist.net/apiconfig and add it to the server .env."
            )
        self._session = session or requests.Session()
        self._last_request_at = 0.0

    def get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        for attempt in range(1, MAX_RETRIES + 1):
            self._throttle()
            response = self._session.get(
                url,
                params=params,
                headers={"X-MAL-CLIENT-ID": self._client_id},
                timeout=30,
            )
            self._last_request_at = time.monotonic()

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 5))
                logger.warning("MAL rate limit hit, sleeping %.0fs", retry_after)
                time.sleep(retry_after)
                continue

            if response.status_code >= 500:
                backoff = 2**attempt
                logger.warning(
                    "MAL server error %s, retrying in %ss (attempt %s/%s)",
                    response.status_code,
                    backoff,
                    attempt,
                    MAX_RETRIES,
                )
                time.sleep(backoff)
                continue

            # A bad client id comes back as 400/403 with a JSON body rather than a
            # 401, so surface the message instead of a bare status code - the
            # difference between "your key is wrong" and "MAL is down" matters.
            if response.status_code in (400, 401, 403):
                raise RuntimeError(
                    f"MAL rejected the request ({response.status_code}): {response.text[:200]}"
                )

            response.raise_for_status()
            return response.json()

        raise RuntimeError(f"MAL request to {url} failed after {MAX_RETRIES} attempts")

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < MIN_SECONDS_BETWEEN_REQUESTS:
            time.sleep(MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
