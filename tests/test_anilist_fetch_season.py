"""What the season listing asks AniList for."""

from ingestion.anilist.fetch_season import fetch_season


class _AniList:
    def __init__(self):
        self.queries = []

    def query(self, query, variables=None):
        self.queries.append(query)
        return {"Page": {"pageInfo": {"hasNextPage": False}, "media": [{"id": 1}]}}


def test_the_listing_leaves_adult_titles_out_as_the_other_sources_do():
    """Kitsu and MAL leave adult titles out of their season listings; AniList
    includes them unless asked not to. The first live response, without the
    filter, was 13 hentai titles in 116, where the whole catalogue held one."""
    client = _AniList()

    fetch_season("SUMMER", 2026, client=client)

    assert "isAdult: false" in client.queries[0]


def test_the_listing_asks_for_the_full_list_of_source_types():
    """The default list files web novels, novels and picture books as OTHER."""
    client = _AniList()

    fetch_season("SUMMER", 2026, client=client)

    assert "source(version: 3)" in client.queries[0]


def test_the_listing_asks_for_banners_trailers_and_streaming_links():
    client = _AniList()

    fetch_season("SUMMER", 2026, client=client)

    for field in ("bannerImage", "trailer {", "externalLinks {"):
        assert field in client.queries[0]
