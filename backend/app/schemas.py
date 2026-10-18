from __future__ import annotations

from typing import Any

from pydantic import BaseModel, field_validator


class AiringEpisode(BaseModel):
    episode: int | None = None
    # ISO 8601 in UTC. A client converts it for display; the API does not guess
    # anyone's timezone.
    airing_at: str
    # The day AniList's schedule was fetched. It is refetched daily, and a
    # broadcast that slips after that is not reflected until the next fetch.
    fetched_on: str | None = None


class Change(BaseModel):
    """Something a title's sources now say differently from their last fetch.
    See processing/changes.py.

    `field` is one of status, episodes, score, premiere, season, broadcast,
    trailer, streaming, or listed: an entry a source created since its last
    fetch, with no old or new value. Values are as the source had them: a score
    out of 10 to one decimal, a premiere as precise as known ("2026", "2026-10",
    "2026-10-04"), a season as "FALL 2026", a streaming link as its URL with the
    service in `label`.
    """

    field: str
    old: str | None = None
    new: str | None = None
    label: str | None = None
    # The fetch the change was seen in, and the earlier one it was compared with.
    run_date: str
    since: str | None = None
    # Every source that reported this same change in that fetch, in the order the
    # merge ranks them.
    sources: list[str] = []


class ChangedTitle(Change):
    wb_id: str
    title: str | None = None
    format: str | None = None
    poster_url: str | None = None
    season: str | None = None
    season_year: int | None = None


class ChangeFeed(BaseModel):
    """Every change recorded in a run of days up to the newest fetch compared."""

    since: str | None = None
    until: str | None = None
    changes: list[ChangedTitle] = []


class RunFinding(BaseModel):
    # "fail", which failed the run, or "note".
    level: str
    message: str


class RunCheck(BaseModel):
    """What a pipeline run checked about its own output. See
    processing/run_checks.py; the numbers differ by DAG."""

    dag: str
    run_date: str
    passed: bool
    checked_at: str | None = None
    numbers: dict[str, Any] = {}
    findings: list[RunFinding] = []
    failed_tasks: list[str] = []


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
    # score covers 44% of a season and 88% of its TV (2026-09-14). favourites is
    # each source's own count on its own site, mostly 0.
    user_count: int | None = None
    favourites: float | None = None
    age_rating: str | None = None
    # Sparse enhancements. cover_url is on 32% of a season and trailer_id 56%
    # (69% and 93% of its TV; 2026-09-14), so
    # neither may be treated as a layout assumption by any client.
    cover_url: str | None = None
    trailer_id: str | None = None
    slug: str | None = None
    # MAL's weekly broadcast slot (day name + HH:MM, JST). Not a next-episode
    # date - MAL has none - so the next airing is derived by the client.
    broadcast_day: str | None = None
    broadcast_time: str | None = None
    # Parallel arrays: streaming_services[i] labels streaming_urls[i]. About half of
    # a season carries at least one link (51%; 93% of its TV, 2026-09-14).
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
    # The episodes that have already aired, newest first, from the archive of
    # every schedule fetched rather than from the current one - which holds the
    # coming weeks only, so an episode vanished the morning after it aired.
    # Capped at the recent few; see schedule.aired_episodes.
    aired_episodes: list[AiringEpisode] = []
    # What its sources have said differently from one fetch to the next, newest
    # first. Filled on a single title only; empty in lists.
    changes: list[Change] = []
    """Every reading of this title's score, oldest first; empty on list rows.

    ONLY WORTH RENDERING WHERE IT MOVED, and usually it has not. Measured
    2026-10-14 over 3,653 titles with two or more readings: 283 moved at all and
    only 121 moved enough to be visible at the one decimal the site prints. A
    flat line is not a history.

    The exception is where people actually look. Movement tracks how recently a
    show aired, because a score is an average over tens of thousands of votes
    and settles once the votes stop arriving - of TV titles with a series, 51%
    of the airing season and 71% of the season just ended had visibly moved,
    against 2% of a year ago and 0% of Fall 2025.
    """
    score_history: list[ScorePoint] = []
    # What each source says, where more than the winner has an opinion.
    source_scores: list[SourceScore] = []
    # `status` above is checked against AniList: where the sources call a title
    # airing and AniList's daily check says it has finished or not yet aired,
    # status says so. merged_status is what the sources said. The rest is
    # AniList's own answer, for titles the sources call airing and null
    # otherwise: finished, current, upcoming, or cancelled or hiatus, which the
    # shared vocabulary has no word for. A hiatus leaves status "current" but
    # means no weekly slot; see processing/duckdb_catalog._status_corrected.
    merged_status: str | None = None
    anilist_status: str | None = None
    # True where the sources call a title airing, AniList has never answered for
    # it, and it premiered over a year ago: nothing can confirm it is still
    # running. 67 of the 296 the sources call airing have no answer, 48 of them
    # premiered over a year ago. A client should not call these airing.
    airing_unconfirmed: bool = False
    # ISO, as much as AniList knows: "2026-09-10", "2026-09" or "2026".
    anilist_ended_on: str | None = None
    anilist_checked_on: str | None = None

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
    # True for a season the sources already list that has not started yet. The
    # pipeline fetches the next season months ahead (ingestion/seasons.
    # capture_both), so "the newest season on file" is not the season a reader
    # means by "this season".
    upcoming: bool = False


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
    # How often the sources actually agree about a score. Null on a warehouse
    # built before this was added, or one carrying a single source, which is a
    # state rather than a fault: a catalogue nothing can disagree in.
    contested: Contested | None = None


class Contested(BaseModel):
    """How much the sources differ about the scores they both hold.

    The catalogue's most distinctive fact and the one it never stated. A score
    on a page is the merge winner's, and of the titles two or more sources have
    rated, 79% print a different number depending on who is asked - measured
    at the one decimal the site shows, so this counts disagreements a reader
    could actually see rather than arithmetic noise.
    """

    # Titles at least two sources have scored; the denominator.
    rated_by_two: int
    # Of those, how many differ by 0.2 or more out of ten.
    differ: int


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


class ScorePoint(BaseModel):
    """One run's reading of a title's score."""

    run_date: str
    score_100: float


class SourceScore(BaseModel):
    """What one source says this title scores, and how many people it asked.

    The score a title page prints is the merge winner's: one number standing in
    for up to three. Measured over this catalogue, 4,138 titles carry a score
    from two or more sources and only 2.9% of them agree - 53% differ by 0.4 or
    more and 325 by over a full point, the widest being 4.2 against 6.7. The
    merged figure is a choice, and the ones it beat are data the warehouse holds
    and the API used to drop.

    `user_count` because the gap is usually a population rather than a verdict:
    120,000 voters and 3,000 voters disagreeing by half a point is a different
    statement from two crowds of equal size doing it, and a reader cannot tell
    which without the denominator.
    """

    source: str
    score_100: float
    user_count: int | None = None


class SeasonSettling(BaseModel):
    """One season's worth of re-asked readings. See routers/scores.py."""

    season: str
    season_year: int
    # Titles with at least one re-asked reading, not the size of the season.
    titles: int
    reasks: int
    # The number came back different at all, and different at the one decimal
    # the site prints. The gap between the two is the point of the endpoint.
    revised: int
    visible: int
    # Points out of 100, as the warehouse stores a score.
    median_change: float
    largest_change: float
    up: int
    down: int
    # Where the season's own quarter sits against the window: "airing" while
    # the pipeline was watching, "over" before it began, or "upcoming". Not a
    # boolean, because a season that has not started is not a season that has
    # settled, and the warehouse holds one of those at all times.
    phase: str


class SettlingBand(BaseModel):
    """Every season in one phase, summed."""

    phase: str
    seasons: int
    titles: int
    reasks: int
    revised: int
    visible: int
    median_change: float
    up: int
    down: int


class DailyScorePoint(BaseModel):
    """One morning's reading of a title's score and vote count."""

    fetched_on: str
    score_100: float
    user_count: int | None = None


class PrintedMove(BaseModel):
    """A pair of readings where the score the SITE shows changed.

    `votes_gained` is what keeps this honest. A score stored out of 100 and
    printed out of 10 crosses a rounding boundary on a single vote: measured on
    2026-10-17, Xian Ni went 6.8 to 6.9 on two new votes while Toaru Anbu no
    ITEM went 6.9 to 7.0 on 521. Those are not the same event and a page that
    prints them identically is reporting arithmetic as news - the mistake
    /scores exists to avoid. So the votes behind a move travel with it.
    """

    on: str
    was: float
    now: float
    votes_gained: int | None = None


class DailyScores(BaseModel):
    """A title's score as asked every morning, oldest first.

    THE DENSE HALF OF /scores. The weekly run records a score that moved twice
    in a week as one move; this is the same series at a day's resolution, and
    it costs no new fetch because the daily AniList status check already asks
    about exactly the airing titles.

    Only airing titles have readings at all - 199 of 11,992 on 2026-10-19 -
    because those are the ones the check asks about. An empty series on a
    finished title is a correct answer, not a gap.
    """

    wb_id: str
    points: list[DailyScorePoint] = []
    # Pairs of consecutive readings where the vote count moved. The unit, for
    # the reason set out at length above backend/app/routers/scores._REASKS: a
    # reading that returns an identical vote count cannot be told from a copy.
    reasks: int = 0
    # Of those, the ones that changed the score this site prints.
    moves: list[PrintedMove] = []
    votes_gained: int | None = None


class ArrivalPoint(BaseModel):
    """What the catalogue held about one season on one run date."""

    run_date: str
    listed: int
    scored: int


class ScoreArrival(BaseModel):
    """A season appearing in the catalogue, then acquiring its scores."""

    season: str
    season_year: int
    points: list[ArrivalPoint] = []


class SourceReasks(BaseModel):
    source: str
    reasks: int


class ScoreSettling(BaseModel):
    """What a score does over its life, read down the warehouse's time axis.

    Every figure is for TV titles, which is what the catalogue shows by default.
    """

    first_run: str | None = None
    last_run: str | None = None
    snapshots: int = 0
    # Seasons the catalogue holds, against the ones that were re-asked at all
    # inside the window. The difference is seasons this cannot speak for.
    seasons_held: int = 0
    reasks: int = 0
    sources: list[SourceReasks] = []
    seasons: list[SeasonSettling] = []
    bands: list[SettlingBand] = []
    arrival: ScoreArrival | None = None


class SimilarTitle(BaseModel):
    """One neighbour of a title, with enough on it to draw a plate.

    Decorated here rather than looked up by the client for the same reason a
    search result is: the vectors and the catalogue are one file, so the join
    cannot miss.
    """

    wb_id: str
    title: str | None = None
    poster_url: str | None = None
    score_100: float | None = None
    format: str | None = None
    season: str | None = None
    season_year: int | None = None
    # Cosine distance from the title being viewed: 0 is the same text, 2 its
    # opposite. In practice a good neighbour sits between 0.2 and 0.6.
    distance: float


class SimilarTitles(BaseModel):
    wb_id: str
    results: list[SimilarTitle] = []


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
