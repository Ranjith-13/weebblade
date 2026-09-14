from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

ANILIST_API_URL = "https://graphql.anilist.co"

# AniList documents 90 requests a minute but answers with X-RateLimit-Limit: 30
# (checked 2026-09-14). One a second would go over that, and each 429 costs a
# minute asleep; stay under it instead of relying on reacting to them.
MIN_SECONDS_BETWEEN_REQUESTS = 2.1
MAX_RETRIES = 5


class AniListClient:
    """Minimal GraphQL client for the AniList API with rate-limit handling."""

    def __init__(self, session: requests.Session | None = None):
        self._session = session or requests.Session()
        self._last_request_at = 0.0

    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        for attempt in range(1, MAX_RETRIES + 1):
            self._throttle()
            response = self._session.post(
                ANILIST_API_URL,
                json={"query": query, "variables": variables or {}},
                timeout=30,
            )
            self._last_request_at = time.monotonic()

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 60))
                logger.warning("AniList rate limit hit, sleeping %.0fs", retry_after)
                time.sleep(retry_after)
                continue

            if response.status_code >= 500:
                backoff = 2**attempt
                logger.warning(
                    "AniList server error %s, retrying in %ss (attempt %s/%s)",
                    response.status_code,
                    backoff,
                    attempt,
                    MAX_RETRIES,
                )
                time.sleep(backoff)
                continue

            response.raise_for_status()
            payload = response.json()
            if "errors" in payload:
                raise RuntimeError(f"AniList GraphQL errors: {payload['errors']}")
            return payload["data"]

        raise RuntimeError(f"AniList request failed after {MAX_RETRIES} attempts")

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < MIN_SECONDS_BETWEEN_REQUESTS:
            time.sleep(MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
