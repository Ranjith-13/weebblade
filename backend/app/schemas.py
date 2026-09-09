from __future__ import annotations

from pydantic import BaseModel, field_validator


class Anime(BaseModel):
    source: str
    source_id: str
    mal_id: int | None = None
    title_romaji: str | None = None
    title_english: str | None = None
    title_native: str | None = None
    poster_url: str | None = None
    synopsis: str | None = None
    format: str | None = None
    status: str | None = None
    season: str | None = None
    season_year: int | None = None
    episodes: int | None = None
    duration_minutes: int | None = None
    genres: list[str] = []
    studios: list[str] = []
    source_material: str | None = None
    score_100: float | None = None
    # popularity and rating_rank are RANKS from the source (lower is better), not
    # counts. Named accordingly so no consumer repeats the sort-descending mistake.
    popularity: float | None = None
    rating_rank: int | None = None
    # The densest interest signal available: present for 100% of the season, where
    # score is present for 29% and favourites tops out around 25.
    user_count: int | None = None
    favourites: float | None = None
    age_rating: str | None = None
    # Sparse enhancements. cover_url is on ~17% of titles and trailer_id ~57%, so
    # neither may be treated as a layout assumption by any client.
    cover_url: str | None = None
    trailer_id: str | None = None
    slug: str | None = None
    # MAL's weekly broadcast slot (day name + HH:MM, JST). Not a next-episode
    # date - MAL has none - so the next airing is derived by the client.
    broadcast_day: str | None = None
    broadcast_time: str | None = None
    # Parallel arrays: streaming_services[i] labels streaming_urls[i]. ~59% of the
    # season carries at least one link.
    streaming_services: list[str] = []
    streaming_urls: list[str] = []
    start_year: int | None = None
    start_month: int | None = None
    start_day: int | None = None
    run_date: str | None = None

    @field_validator(
        "genres", "studios", "streaming_services", "streaming_urls", mode="before"
    )
    @classmethod
    def _null_list_is_empty(cls, value: object) -> object:
        """A list column reads back as NULL, not [], for any row written before that
        column existed.

        `anime_media_latest` keeps the newest row per title, so a title that stopped
        appearing upstream is still served from an older snapshot. standardize_schema
        fills the columns it lacks with typed NULLs by design - that is what makes
        backfills work - and those NULLs arrive here as None, which a bare list[str]
        rejects with a 500 for the whole page.

        Found in production the moment streaming_services shipped: /anime?limit=100
        failed on item 58 while limit=50 was fine, because the carried-over rows sit
        past the first page.
        """
        return [] if value is None else value


class AnimeListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[Anime]


class DigestResponse(BaseModel):
    run_date: str
    content: str


class SearchResult(BaseModel):
    title: str
    source: str
    source_id: str
    distance: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
