"""MAL's season endpoint answers a different question than Kitsu's.

Kitsu returns what STARTS in a season. MAL returns what is AIRING in it, which
includes shows that have been running for decades, each still tagged with its
debut season. Every stored row in this project means start season, so the extras
have to go - and they are not harmless, because the frontend derives its season
switcher from whatever seasons the data contains.
"""

from ingestion.mal.fetch_season import fetch_season


class _StubMalClient:
    """Replays canned pages, standing in for a live MalClient in tests."""

    def __init__(self, pages: list[dict]):
        self._pages = pages
        self.calls = 0

    def get(self, url, params=None):
        payload = self._pages[self.calls]
        self.calls += 1
        return payload


def _node(node_id: int, title: str, season: str | None, year: int | None) -> dict:
    start = {}
    if season is not None:
        start["season"] = season
    if year is not None:
        start["year"] = year
    return {"node": {"id": node_id, "title": title, "start_season": start}}


def _page(*nodes: dict) -> dict:
    return {"data": list(nodes), "paging": {}}


def test_a_long_running_show_airing_this_season_but_starting_decades_ago_is_dropped():
    """The live failure. A single Summer 2026 fetch deposited One Piece under
    Fall 1999, Sazae-san under Fall 1969 and 34 others like them - rows no season
    view could ever show, each contributing a phantom entry to the switcher."""
    client = _StubMalClient(
        [
            _page(
                _node(1, "A Summer 2026 premiere", "summer", 2026),
                _node(21, "One Piece", "fall", 1999),
                _node(2406, "Mrs. Sazae", "fall", 1969),
            )
        ]
    )

    titles = fetch_season("SUMMER", 2026, client=client)

    assert [t["title"] for t in titles] == ["A Summer 2026 premiere"]


def test_the_same_season_in_a_different_year_is_not_a_match():
    """Season alone is not the key. Summer 2025 is a different season entirely,
    and matching on the name would keep a year's worth of the wrong titles."""
    client = _StubMalClient(
        [_page(_node(1, "This year", "summer", 2026), _node(2, "Last year", "summer", 2025))]
    )

    titles = fetch_season("SUMMER", 2026, client=client)

    assert [t["title"] for t in titles] == ["This year"]


def test_season_comparison_ignores_case():
    """MAL reports lowercase ("summer"); the pipeline passes uppercase. A
    case-sensitive comparison would drop the entire season."""
    client = _StubMalClient([_page(_node(1, "Kept", "summer", 2026))])

    assert len(fetch_season("SUMMER", 2026, client=client)) == 1


def test_an_entry_with_no_start_season_is_kept():
    """Missing information is not evidence of a mismatch. Dropping a title on an
    absent field would lose real rows for the sake of tidiness."""
    client = _StubMalClient(
        [
            _page(
                _node(1, "No start season at all", None, None),
                _node(2, "Year but no season", None, 2026),
            )
        ]
    )

    assert len(fetch_season("SUMMER", 2026, client=client)) == 2


def test_duplicate_ids_across_pages_are_still_collapsed():
    """The filter must not disturb the existing dedupe: trusting page boundaries
    has silently doubled rows in this project before."""
    client = _StubMalClient(
        [
            {
                "data": [_node(1, "Same show", "summer", 2026)],
                "paging": {"next": "https://api.myanimelist.net/v2/anime/season/2026/summer?p=2"},
            },
            _page(_node(1, "Same show", "summer", 2026)),
        ]
    )

    assert len(fetch_season("SUMMER", 2026, client=client)) == 1
    assert client.calls == 2  # it really did follow the second page
