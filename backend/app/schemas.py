from __future__ import annotations

from pydantic import BaseModel


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
    # Parallel arrays: streaming_services[i] labels streaming_urls[i]. ~59% of the
    # season carries at least one link.
    streaming_services: list[str] = []
    streaming_urls: list[str] = []
    start_year: int | None = None
    start_month: int | None = None
    start_day: int | None = None
    run_date: str | None = None


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
