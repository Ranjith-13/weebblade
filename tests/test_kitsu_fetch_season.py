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
        "links": {"next": "https://kitsu.io/api/edge/anime?page[offset]=1"},
    }
    duplicate_page = {
        "data": [{"id": "1", "type": "anime", "attributes": {}}],
        "links": {"next": "https://kitsu.io/api/edge/anime?page[offset]=2"},
    }
    page_3 = {
        "data": [{"id": "2", "type": "anime", "attributes": {}}],
        "links": {},
    }
    client = _StubKitsuClient([page_1, duplicate_page, page_3])

    results = fetch_season("SUMMER", 2026, client=client)

    assert [r["id"] for r in results] == ["1", "2"]
