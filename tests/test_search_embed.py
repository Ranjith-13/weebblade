from ai.search.embed import text_for_embedding


def test_text_for_embedding_combines_title_genres_synopsis():
    row = {
        "title_english": "Demon Slayer",
        "title_romaji": "Kimetsu no Yaiba",
        "genres": ["Action", "Fantasy"],
        "synopsis": "A boy fights demons to save his sister.",
    }

    text = text_for_embedding(row)

    assert text == (
        "Demon Slayer. Genres: Action, Fantasy. A boy fights demons to save his sister."
    )


def test_text_for_embedding_falls_back_to_romaji_title():
    row = {"title_english": None, "title_romaji": "Kimetsu no Yaiba", "genres": [], "synopsis": None}

    text = text_for_embedding(row)

    assert text == "Kimetsu no Yaiba"


def test_text_for_embedding_handles_all_missing():
    assert text_for_embedding({}) == "Untitled"
