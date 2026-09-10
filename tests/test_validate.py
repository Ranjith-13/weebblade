"""Ingest-time schema checks.

Each test here corresponds to a mistake this project actually made. The point of
the module is that the next source added makes them again, and something notices
before the data is written rather than days later on the live site.
"""

import pytest

from ingestion.validate import SchemaViolation, validate_rows


def _row(**overrides):
    row = {
        "source": "mal",
        "source_id": "1",
        "format": "TV",
        "status": "current",
        "season": "SUMMER",
        "average_score": 78.0,
        "duration": 24,
        "genres": ["Action"],
        "studios": ["Studio"],
        "streaming_services": None,
        "streaming_urls": None,
    }
    row.update(overrides)
    return row


def _rows(n, **overrides):
    return [_row(source_id=str(i), **overrides) for i in range(n)]


def test_ordinary_rows_pass():
    validate_rows(_rows(30), "mal")


def test_a_zero_to_ten_scale_in_a_zero_to_hundred_column_is_caught():
    """The bug that shipped and stayed for days. 124 of 227 scored titles sat on
    MAL's 0-10 scale in a column called score_100, so good shows rendered as
    "8.58 out of 100" and sank to the bottom of a score-sorted catalogue.

    A range check could never have caught it - 8.58 is a valid score out of 100.
    The ceiling is the tell.
    """
    rows = [_row(source_id=str(i), average_score=5.0 + i / 20) for i in range(30)]

    with pytest.raises(SchemaViolation, match="0-10 scale"):
        validate_rows(rows, "mal")


def test_a_genuinely_low_scoring_season_is_not_mistaken_for_a_scale_error():
    """Real scores do reach down there. What makes the scale error detectable is
    that NOTHING exceeds 10, so a single ordinary score clears the suspicion."""
    rows = [_row(source_id=str(i), average_score=6.0) for i in range(30)]
    rows[0]["average_score"] = 74.0

    validate_rows(rows, "mal")


def test_too_few_scores_to_judge_the_scale_are_left_alone():
    """Three scored titles could sit under 10 by chance; twenty could not. Below
    the sample floor this stays quiet rather than failing an ingest on noise."""
    validate_rows([_row(source_id=str(i), average_score=8.0) for i in range(5)], "mal")


def test_a_score_outside_the_scale_entirely_is_caught():
    with pytest.raises(SchemaViolation, match="outside 0-100"):
        validate_rows(_rows(30, average_score=870.0), "mal")


def test_a_vocabulary_that_differs_only_in_case_is_caught():
    """MAL says "tv" where Kitsu says "TV". Unreconciled, the frontend showed two
    formats for one thing and the airing-now count missed every MAL row.

    Case is the tell: no source publishes both spellings, so this is always a
    mapping bug rather than something new upstream.
    """
    with pytest.raises(SchemaViolation, match="differs only in case"):
        validate_rows(_rows(30, format="tv"), "mal")

    with pytest.raises(SchemaViolation, match="differs only in case"):
        validate_rows(_rows(30, status="Current"), "mal")


def test_one_new_upstream_value_warns_rather_than_failing():
    """Kitsu passes its own subtype and status straight through, so it can publish
    something we have never seen. Killing a whole season's ingest over one such
    row would be a worse outcome than the row."""
    rows = _rows(30, source="kitsu")
    rows[0]["status"] = "something_new_upstream"

    validate_rows(rows, "kitsu")


def test_a_new_value_across_most_rows_does_fail():
    """One is upstream news. Most of them is our mapping having broken."""
    with pytest.raises(SchemaViolation, match="mapping looks broken"):
        validate_rows(_rows(30, format="totally_unknown"), "mal")


def test_seconds_in_a_minutes_column_are_caught():
    """MAL reports average_episode_duration in SECONDS. Unconverted, a 24-minute
    episode claimed to run 24 hours."""
    with pytest.raises(SchemaViolation, match="looks like seconds"):
        validate_rows(_rows(30, duration=1440), "mal")


def test_a_single_feature_length_entry_is_not_a_unit_error():
    """Films genuinely run long. The median is what distinguishes one long entry
    from a whole column an order of magnitude out."""
    rows = _rows(30)
    rows[0]["duration"] = 480

    validate_rows(rows, "mal")


def test_an_empty_list_warns_but_does_not_fail():
    """The first version of this failed on [] and would have broken every ingest
    run in the project - MAL emits studios=[] for 82 of 219 Spring rows. [] beating
    real data was fixed in the merge, where it mattered, so a source emitting it
    costs nothing now."""
    validate_rows(_rows(30, studios=[], genres=[]), "mal")


def test_a_list_column_holding_something_that_is_not_a_list_is_caught():
    with pytest.raises(SchemaViolation, match="not a list"):
        validate_rows(_rows(30, genres="Action"), "mal")


def test_rows_without_an_addressable_identity_are_caught():
    """source and source_id are the merge's join key and the view's dedupe key.
    A row missing either cannot be reached by anything downstream."""
    with pytest.raises(SchemaViolation, match="missing source or source_id"):
        validate_rows(_rows(5) + [_row(source_id=None)], "mal")


def test_rows_labelled_with_the_wrong_source_are_caught():
    """A copy-paste between two transforms writes one source's rows into another's
    directory, where nothing would ever look for them again."""
    with pytest.raises(SchemaViolation, match="unexpected source"):
        validate_rows(_rows(5), "kitsu")


def test_an_empty_fetch_is_not_an_error():
    """Every source has returned nothing at some point in this project's life;
    AniList and Jikan return nothing every run. That is handled downstream by
    consolidate skipping the source, not by failing here."""
    validate_rows([], "jikan")
