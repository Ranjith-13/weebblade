from ai.search.embed import text_for_embedding


def test_text_for_embedding_combines_names_shape_genres_and_synopsis():
    row = {
        "title_english": "Demon Slayer",
        "title_romaji": "Kimetsu no Yaiba",
        "format": "TV",
        "season": "SPRING",
        "season_year": 2019,
        "studios": ["ufotable"],
        "source_material": "manga",
        "genres": ["Action", "Fantasy"],
        "synopsis": "A boy fights demons to save his sister.",
    }

    text = text_for_embedding(row)

    assert text == (
        "Demon Slayer, Kimetsu no Yaiba. TV series, Spring 2019, by ufotable. "
        "Adapted from manga. Genres: Action, Fantasy. A boy fights demons to save his sister."
    )


def test_both_names_are_embedded_so_either_one_finds_the_title():
    """A title listed in English could not be found under the name it airs
    under: searching the romaji of 40 such titles put the right one first 10
    times before this."""
    row = {"title_english": "Demon Slayer", "title_romaji": "Kimetsu no Yaiba"}

    assert text_for_embedding(row).startswith("Demon Slayer, Kimetsu no Yaiba")


def test_one_name_said_twice_is_said_once():
    row = {"title_english": "Blue Box", "title_romaji": "blue box"}

    assert text_for_embedding(row) == "Blue Box"


def test_text_for_embedding_falls_back_to_romaji_title():
    row = {"title_english": None, "title_romaji": "Kimetsu no Yaiba", "genres": [], "synopsis": None}

    assert text_for_embedding(row) == "Kimetsu no Yaiba"


def test_a_title_with_no_synopsis_is_still_described():
    """531 titles have none. What is left is the shape of the thing, which is
    the difference between a description and a bare name."""
    row = {
        "title_english": "Some Short",
        "format": "ONA",
        "season_year": 2022,
        "studios": ["Studio Gokumi"],
        "genres": ["Comedy"],
    }

    assert text_for_embedding(row) == (
        "Some Short. ONA, 2022, by Studio Gokumi. Genres: Comedy"
    )


def test_an_original_work_says_so_rather_than_being_adapted_from_one():
    row = {"title_romaji": "Original Thing", "source_material": "original"}

    assert text_for_embedding(row) == "Original Thing. An original story"


def test_an_underscored_source_reads_as_words():
    row = {"title_romaji": "A", "source_material": "light_novel"}

    assert text_for_embedding(row) == "A. Adapted from light novel"


def test_text_for_embedding_handles_all_missing():
    assert text_for_embedding({}) == "Untitled"
