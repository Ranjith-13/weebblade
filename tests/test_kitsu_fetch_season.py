from ingestion.kitsu.fetch_season import _attach_metadata


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
