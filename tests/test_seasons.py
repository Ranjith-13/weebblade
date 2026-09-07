from ingestion.seasons import season_for_month


def test_season_for_month():
    assert season_for_month(1) == "WINTER"
    assert season_for_month(3) == "WINTER"
    assert season_for_month(4) == "SPRING"
    assert season_for_month(8) == "SUMMER"
    assert season_for_month(12) == "FALL"
