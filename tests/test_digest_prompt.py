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
    assert "84.0/100" in prompt
    assert "Action, Fantasy" in prompt
    assert "Action: 12 titles" in prompt
    assert "TV: 20 titles" in prompt
    assert "SUMMER 2026: 140 titles, average score 68.5" in prompt


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
