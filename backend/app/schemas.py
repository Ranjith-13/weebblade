from __future__ import annotations

from pydantic import BaseModel


class Anime(BaseModel):
    source: str
    source_id: str
    mal_id: int | None = None
    title_romaji: str | None = None
    title_english: str | None = None
    title_native: str | None = None
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
    popularity: float | None = None
    favourites: float | None = None
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
