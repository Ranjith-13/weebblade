from ingestion.kitsu.fetch_season import _attach_metadata, fetch_season


class _StubKitsuClient:
    """Replays canned pages, standing in for a live KitsuClient in tests."""

    def __init__(self, pages: list[dict]):
        self._pages = pages
        self.calls = 0

    def get(self, url, params=None):
        payload = self._pages[self.calls]
        self.calls += 1
        return payload


def test_attach_metadata_resolves_categories_and_season():
    payload = {
        "data": [
            {
                "id": "44778",
                "type": "anime",
                "attributes": {"canonicalTitle": "Youjo Senki II"},
                "relationships": {
                    "categories": {
                        "data": [{"type": "categories", "id": "25"}, {"type": "categories", "id": "61"}]
                    }
                },
            }
        ],
        "included": [
            {"id": "25", "type": "categories", "attributes": {"title": "Magic"}},
            {"id": "61", "type": "categories", "attributes": {"title": "War"}},
        ],
    }

    [item] = _attach_metadata(payload, "SUMMER", 2026)

    assert item["_genre_names"] == ["Magic", "War"]
    assert item["_season"] == "SUMMER"
    assert item["_season_year"] == 2026


def test_attach_metadata_handles_missing_relationships_and_included():
    payload = {"data": [{"id": "1", "type": "anime", "attributes": {}}]}

    [item] = _attach_metadata(payload, "winter", 2026)

    assert item["_genre_names"] == []
    assert item["_season"] == "WINTER"


def test_fetch_season_deduplicates_across_pages():
    # Reproduces a real bug found live: Kitsu's page[offset]=N request returned
    # byte-identical data to offset=0 for the same query, silently doubling rows.
    page_1 = {
        "data": [{"id": "1", "type": "anime", "attributes": {}}],
        "meta": {"count": 2},
        "links": {"next": "https://kitsu.io/api/edge/anime?page[offset]=1"},
    }
    duplicate_page = {
        "data": [{"id": "1", "type": "anime", "attributes": {}}],
        "links": {"next": "https://kitsu.io/api/edge/anime?page[offset]=2"},
    }
    page_3 = {
        "data": [{"id": "2", "type": "anime", "attributes": {}}],
        "meta": {"count": 2},
        "links": {},
    }
    client = _StubKitsuClient([page_1, duplicate_page, page_3])

    results = fetch_season("SUMMER", 2026, client=client)

    assert [r["id"] for r in results] == ["1", "2"]


# --- the block one walk cannot reach -------------------------------------------------

import logging  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402


class _Kitsu:
    """Kitsu's season listing as measured: pages of 20 in the requested order, a
    season-size count in meta, and - when `broken` - the page at offset 20 served
    as a copy of the page at offset 0, so every walk skips a block of titles.
    `phantom` titles are counted in meta but never served in any order."""

    def __init__(self, n: int, broken: bool = True, phantom: int = 0):
        self.ids = [str(1000 + i) for i in range(n)]
        self.broken, self.phantom, self.calls = broken, phantom, []

    def get(self, url, params=None):
        q = dict(params) if params else {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        sort, offset = q.get("sort", "id"), int(q.get("page[offset]", 0))
        self.calls.append(sort)
        order = self.ids if sort == "id" else self.ids[::-1]
        served = 0 if (self.broken and offset == 20) else offset
        nxt = offset + 20
        return {
            "data": [{"id": i, "type": "anime", "attributes": {}} for i in order[served:served + 20]],
            "meta": {"count": len(order) + self.phantom},
            "links": {"next": f"https://kitsu.io/api/edge/anime?sort={sort}&page%5Boffset%5D={nxt}"}
            if nxt < len(order) else {},
        }


def test_a_second_walk_in_reverse_recovers_the_block_kitsu_hides():
    """Fall 2023 reports 235 titles and one walk returns 220. The block the first
    walk skips is at the far end of the reverse walk."""
    kitsu = _Kitsu(235)

    results = fetch_season("FALL", 2023, client=kitsu)

    assert len({r["id"] for r in results}) == len(results) == 235
    assert "-id" in kitsu.calls


def test_a_walk_that_reaches_the_count_is_not_repeated():
    kitsu = _Kitsu(235, broken=False)

    results = fetch_season("FALL", 2023, client=kitsu)

    assert len(results) == 235
    assert set(kitsu.calls) == {"id"}  # half the requests, when Kitsu behaves


def test_a_season_kitsu_cannot_serve_in_full_is_kept_and_reported(caplog):
    kitsu = _Kitsu(100, phantom=3)

    with caplog.at_level(logging.WARNING):
        results = fetch_season("FALL", 2023, client=kitsu)

    assert len(results) == 100
    assert "reports 103 titles" in caplog.text
