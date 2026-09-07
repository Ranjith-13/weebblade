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
