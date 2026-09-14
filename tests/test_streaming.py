"""What to call the service behind a streaming link."""

from ingestion.streaming import service_name


def test_one_service_is_one_name_whatever_host_or_region_it_is_reached_by():
    """Named by host alone, Max was two chips and Prime Video two."""
    assert service_name("https://play.max.com/show/abc") == service_name("https://www.max.com/shows/abc") == "Max"
    assert service_name("https://www.amazon.co.jp/dp/B0D") == service_name("https://www.amazon.com/gp/video/x") == "Prime Video"


def test_hulu_japan_is_not_hulu():
    """A different company with a different catalogue."""
    assert service_name("https://www.hulu.jp/watch/1") == "Hulu Japan"
    assert service_name("https://www.hulu.com/series/x") == "Hulu"


def test_a_host_nobody_has_named_is_still_shown_by_its_host():
    assert service_name("https://www.anime-onegai.com/anime/123") == "anime-onegai.com"
