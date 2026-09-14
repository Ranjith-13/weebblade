from __future__ import annotations

from pydantic import BaseModel, field_validator


class AiringEpisode(BaseModel):
    episode: int | None = None
    # ISO 8601 in UTC. A client converts it for display; the API does not guess
    # anyone's timezone.
    airing_at: str
    # The day AniList's schedule was fetched. It is refetched daily, and a
    # broadcast that slips after that is not reflected until the next fetch.
    fetched_on: str | None = None


class AniListStatus(BaseModel):
    """AniList's own account of whether a title is airing, from its daily check.

    Asked only about titles the catalogue calls airing, because it exists to
    catch the ones that have stopped: the catalogue's status is the merge
    winner's as of the snapshot the title was filed in, and on 2026-09-14 it
    called 51 titles airing that AniList had as finished.
    """

    # finished, current, upcoming - or cancelled or hiatus, which the catalogue
    # has no word for and which also mean "not airing".
    status: str | None = None
    # ISO, as much as AniList knows: "2026-09-10", "2026-09" or "2026".
    ended_on: str | None = None
    checked_on: str


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
    # The title's stable WeebBlade identity - see processing/identity.py. Unlike
    # (source, source_id), which is whichever source won this week's merge, this
    # does not move. Anything storing a reference to a title should store this.
    # Null only for a warehouse that has not yet run with identities.
    wb_id: str | None = None
    # Every source row that became this title, as "source:source_id". Its
    # provenance, and the reason an old address for it still resolves.
    source_keys: list[str] = []
    # The next few episodes from AniList's airing schedule, soonest first. Filled
    # on a single title only (GET /anime/{wb_id}); empty in lists. Several, not
    # one, so a client holding a cached copy can skip the ones that have aired.
    upcoming_episodes: list[AiringEpisode] = []
    # AniList's own status, for a title the catalogue calls airing; null
    # otherwise, and in lists. See AniListStatus.
    anilist_status: AniListStatus | None = None

    @field_validator(
        "genres", "studios", "streaming_services", "streaming_urls", "source_keys", mode="before"
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


class FranchiseEntry(BaseModel):
    mal_id: int
    # Null for an entry older than the catalogue - a 2019 prequel a current sequel
    # points at. It is still listed, from what MAL says about it, because it is
    # exactly what someone looking at the sequel wants to know exists.
    wb_id: str | None = None
    title: str | None = None
    format: str | None = None
    # ISO date, possibly partial ("2019", "2019-04"); MAL does not always know the day.
    start_date: str | None = None
    season: str | None = None
    season_year: int | None = None
    poster_url: str | None = None
    score_100: float | None = None
    # How this entry relates to the title asked about - "prequel", "side_story" -
    # when the two are linked directly. Null for the rest of the franchise.
    relation: str | None = None
    is_this: bool = False


class Franchise(BaseModel):
    franchise_id: str | None = None
    entries: list[FranchiseEntry] = []


class SeasonCount(BaseModel):
    season: str
    season_year: int
    count: int


class CatalogueSummary(BaseModel):
    """What the warehouse holds, in one small response.

    Exists so a client never has to page the whole catalogue to learn its shape.
    The frontend used to do exactly that - every title, 100 at a time - to derive
    the season list and the sources, and at 2,755 titles that was 28 requests and
    6.6s before a page could render.
    """

    total: int
    # Every source that contributed a row, not only those that won a merge: a
    # source whose rows all lost to a higher-priority one still reached the
    # warehouse, and its fields are in there.
    sources: list[str]
    # Newest first: by year, then the broadcast quarter, not the alphabet.
    seasons: list[SeasonCount]


class ScheduledEpisode(BaseModel):
    # Null for a show the catalogue does not hold - a long-runner older than it,
    # like One Piece. It is still on the schedule, described as AniList has it.
    wb_id: str | None = None
    anilist_id: int
    mal_id: int | None = None
    title: str | None = None
    format: str | None = None
    poster_url: str | None = None
    score_100: float | None = None
    episode: int | None = None
    # How many episodes the show has, where known.
    episodes: int | None = None
    airing_at: str


class Schedule(BaseModel):
    """Every episode airing in a run of days, soonest first.

    The days are Japan's: `start` is midnight in Tokyo today, because that is
    the calendar the broadcasts keep, and `end` is `days` later.
    """

    start: str
    end: str
    fetched_on: str | None = None
    episodes: list[ScheduledEpisode] = []


class SearchResult(BaseModel):
    title: str
    source: str
    source_id: str
    distance: float
    # Decoration from the warehouse, so a client can draw a result as the title it
    # is without holding a copy of the catalogue to look it up in. All optional:
    # the matches come from the vector index, and a title the warehouse cannot
    # place still comes back, just undecorated.
    wb_id: str | None = None
    poster_url: str | None = None
    score_100: float | None = None
    format: str | None = None
    status: str | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
