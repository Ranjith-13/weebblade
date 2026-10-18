from ai.digest.prompt import build_prompt


def test_build_prompt_includes_all_sections():
    stats = {
        "top_rated": [
            {
                "title_english": "Demon Slayer",
                "title_romaji": None,
                "score_100": 84.0,
                "genres": ["Action", "Fantasy"],
                "source": "anilist",
            }
        ],
        "genre_counts": [{"genre": "Action", "title_count": 12}],
        "format_counts": [{"format": "TV", "title_count": 20}],
        "season_summary": [
            {"season": "SUMMER", "season_year": 2026, "title_count": 140, "avg_score": 68.5}
        ],
    }

    prompt = build_prompt(stats)

    assert "Demon Slayer" in prompt
    assert "8.4 out of 10" in prompt, "the scale a reader sees, not the one it is stored at"
    assert "Action, Fantasy" in prompt
    assert "Action: 12 titles" in prompt
    assert "TV: 20 titles" in prompt
    assert "SUMMER 2026: 140 titles, average score 6.8 out of 10" in prompt


def test_build_prompt_handles_missing_titles_and_genres():
    stats = {
        "top_rated": [
            {"title_english": None, "title_romaji": None, "score_100": 50.0, "genres": [], "source": "kitsu"}
        ],
        "genre_counts": [],
        "format_counts": [{"format": None, "title_count": 3}],
        "season_summary": [],
    }

    prompt = build_prompt(stats)

    assert "Untitled" in prompt
    assert "unlisted genres" in prompt
    assert "unknown: 3 titles" in prompt


def test_the_prompt_names_the_season_it_is_about():
    """The season summary lists every season on record, so a prompt that only
    said "this season" left the model to work out which rows were the subject and
    which were context. It guessed wrong: a Summer digest quoting Spring's count."""
    stats = {
        "current_season": [{"season": "SUMMER", "season_year": 2026}],
        "top_rated": [
            {
                "title_english": "Demon Slayer",
                "title_romaji": None,
                "score_100": 84.0,
                "genres": ["Action"],
                "source": "kitsu",
            }
        ],
        "genre_counts": [{"genre": "Action", "title_count": 12}],
        "format_counts": [{"format": "TV", "title_count": 20}],
        "season_summary": [
            {"season": "SUMMER", "season_year": 2026, "title_count": 228, "avg_score": 68.5},
            {"season": "SPRING", "season_year": 2026, "title_count": 248, "avg_score": 70.1},
        ],
    }

    prompt = build_prompt(stats)

    assert "## Top rated titles in SUMMER 2026" in prompt
    assert "## Most common genres in SUMMER 2026" in prompt
    assert "## Format breakdown for SUMMER 2026" in prompt
    assert "for comparison" in prompt  # the summary is labelled as context
    assert "do not present" in prompt  # and the model is told so outright


def test_the_prompt_still_builds_when_the_season_is_unknown():
    """collect_stats returns all-empty stats whenever the warehouse or its view is
    missing, which is a legitimate state. The prompt degrades to the old wording
    rather than printing "None None"."""
    stats = {
        "current_season": [],
        "top_rated": [
            {
                "title_english": "A",
                "title_romaji": None,
                "score_100": 50.0,
                "genres": [],
                "source": "kitsu",
            }
        ],
        "genre_counts": [],
        "format_counts": [],
        "season_summary": [],
    }

    prompt = build_prompt(stats)

    assert "## Top rated titles this season" in prompt
    assert "None" not in prompt


_STATS = {"top_rated": [], "genre_counts": [], "format_counts": [], "season_summary": []}


def _change(field, title, old=None, new=None, **kw):
    return {"field": field, "title": title, "old": old, "new": new, "label": None, "format": "TV", **kw}


def test_this_weeks_changes_are_lines_the_model_can_name_and_is_told_what_they_are():
    prompt = build_prompt(_STATS, [
        _change("status", "Frieren", "current", "finished"),
        _change("listed", "Poke Oki Season 2", format="ONA"),
        _change("score", "Dandadan", "7.2", "7.9"),
        _change("streaming", "Frieren", None, "https://netflix.com/x", label="Netflix"),
        _change("season", "Delayed Show", "SUMMER 2026", "FALL 2026"),
    ])

    assert "## What changed since last week (any season)" in prompt
    assert "- Frieren: now finished (was airing)" in prompt
    assert "- Poke Oki Season 2 (ONA): newly listed" in prompt
    assert "- Dandadan: score 7.2 to 7.9 out of 10" in prompt
    assert "- Frieren: now streaming on Netflix" in prompt
    assert "- Delayed Show: season SUMMER 2026 to FALL 2026" in prompt
    assert "Do not present these as this season's statistics" in prompt


def test_a_week_with_no_changes_has_no_section_and_no_instruction_about_one():
    prompt = build_prompt(_STATS, [])

    assert "What changed" not in prompt and "since last week" not in prompt


def test_a_busy_week_names_the_biggest_score_moves_and_counts_the_rest():
    moves = [_change("score", f"Show {i}", "7.0", f"{7 + i / 10:.1f}") for i in range(3, 18)]

    prompt = build_prompt(_STATS, moves)

    assert prompt.index("Show 17:") < prompt.index("Show 16:")
    assert "Show 3:" not in prompt and "Show 5:" not in prompt
    assert "- and 3 more score changes" in prompt


def test_a_tenth_either_way_is_counted_not_named():
    """Every one of the week's 51 score changes to 2026-09-13 was a tenth, some
    crossing a rounding line and back."""
    prompt = build_prompt(_STATS, [
        _change("score", "Ogre's Bride", "6.9", "6.8"), _change("score", "Ogre's Bride", "6.8", "6.9"),
        _change("score", "Big Mover", "6.8", "7.4"), _change("score", "Newly Scored", None, "7.1"),
    ])

    assert "Ogre's Bride" not in prompt
    assert "- 2 score moves under 0.3 out of 10, not listed" in prompt
    assert "- Big Mover: score 6.8 to 7.4 out of 10" in prompt
    assert "- Newly Scored: score none to 7.1 out of 10" in prompt


# --- the scale the digest quotes ----------------------------------------
#
# Scores are stored out of 100 and shown out of 10 everywhere a reader can see
# one. The prompt handed the model "83.63/100" and the model used what it was
# given, so the digest printed "an 83.63 rating" on a page whose every other
# element said 8.4 - and after the home page was reordered on 2026-10-18 the
# two sat a paragraph apart.


def _stats(score_100, avg=None):
    return {
        "top_rated": [{"title_english": "A Show", "title_romaji": None, "score_100": score_100,
                       "genres": ["Action"], "source": "kitsu"}],
        "genre_counts": [{"genre": "Action", "title_count": 1}],
        "format_counts": [{"format": "TV", "title_count": 1}],
        "season_summary": [{"season": "FALL", "season_year": 2026, "title_count": 1,
                            "avg_score": avg if avg is not None else score_100}],
        "total_titles": 1,
    }


def test_the_prompt_never_shows_the_storage_scale():
    prompt = build_prompt(_stats(83.63))

    assert "83.63" not in prompt, "two decimals of precision the product never prints"
    assert "/100" not in prompt
    assert "8.4 out of 10" in prompt


def test_the_season_table_uses_the_same_scale_as_the_titles():
    """Both were /100 while score CHANGES a few lines above were already out of
    ten, so one prompt could carry both scales and one paragraph could quote
    both."""
    prompt = build_prompt(_stats(84.0, avg=72.5))

    assert "average score 7.3 out of 10" in prompt
    assert "72.5" not in prompt


def test_the_model_is_told_the_scale_as_well_as_given_it():
    """Belt and braces: a model handed 8.4 can still write 84% or 8.36 if it
    decides to be helpful, and the digest sits directly beneath the site's own
    numbers."""
    from ai.digest.prompt import SYSTEM_INSTRUCTION

    assert "out of 10 to one decimal" in SYSTEM_INSTRUCTION
    assert "percentage" in SYSTEM_INSTRUCTION


def test_the_rounding_matches_the_site_rather_than_python():
    """scoreOutOfTen is (score100 / 10).toFixed(1). Python's round() rounds
    halves to even, so 72.5 gives 7.2 where the site shows 7.3 - fixing the
    scale and leaving the rounding would have put the digest 0.1 from the page
    on every exact tie. Values checked against node."""
    from ai.digest.prompt import _out_of_ten

    assert _out_of_ten(72.5) == "7.3", "round() would say 7.2"
    # And NOT decimal-string rounding: 83.5 / 10 is 8.34999999999999964, which
    # is what toFixed sees, so both answer 8.3 where Decimal("8.35") says 8.4.
    assert _out_of_ten(83.5) == "8.3"
    assert [_out_of_ten(v) for v in (86.5, 83.63, 84.0, 68.5, 79.95)] == [
        "8.7", "8.4", "8.4", "6.8", "8.0"
    ]
    assert _out_of_ten(None) is None
