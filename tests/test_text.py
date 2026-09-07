from ingestion.text import clean_synopsis


def test_clean_synopsis_strips_tags_and_collapses_whitespace():
    assert clean_synopsis("A boy named Tanjiro<br>fights demons.  \n\nHe is strong.") == (
        "A boy named Tanjiro fights demons. He is strong."
    )


def test_clean_synopsis_handles_none_and_empty():
    assert clean_synopsis(None) is None
    assert clean_synopsis("") is None
    assert clean_synopsis("   ") is None
