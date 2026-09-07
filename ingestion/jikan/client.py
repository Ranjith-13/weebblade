from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

JIKAN_API_URL = "https://api.jikan.moe/v4"

# Jikan's public instance is rate-limited to ~3 req/s and 60 req/min; stay well under it.
MIN_SECONDS_BETWEEN_REQUESTS = 1.0
MAX_RETRIES = 5


class JikanClient:
    """Minimal REST client for the Jikan (unofficial MyAnimeList) API."""

    def __init__(self, session: requests.Session | None = None):
        self._session = session or requests.Session()
        self._last_request_at = 0.0

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        for attempt in range(1, MAX_RETRIES + 1):
            self._throttle()
            response = self._session.get(f"{JIKAN_API_URL}{path}", params=params, timeout=30)
            self._last_request_at = time.monotonic()

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 5))
                logger.warning("Jikan rate limit hit, sleeping %.0fs", retry_after)
                time.sleep(retry_after)
                continue

            if response.status_code >= 500:
                backoff = 2**attempt
                logger.warning(
                    "Jikan server error %s, retrying in %ss (attempt %s/%s)",
                    response.status_code,
                    backoff,
                    attempt,
                    MAX_RETRIES,
                )
                time.sleep(backoff)
                continue

            response.raise_for_status()
            return response.json()

        raise RuntimeError(f"Jikan request to {path} failed after {MAX_RETRIES} attempts")

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < MIN_SECONDS_BETWEEN_REQUESTS:
            time.sleep(MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
