"""Which source rows are one title. Pure Python, so these run anywhere; the
Spark merge built on them is tested in test_consolidate_merge.py.

The fixtures are live rows, trimmed to the columns the rules read."""

import random

from processing.matching import group, keys as title_keys


def _row(source, source_id, mal_id=None, romaji=None, english=None, fmt="TV", year=2026, date=None):
    y, m, d = date or (None, None, None)
    return {"source": source, "source_id": source_id, "mal_id": mal_id, "title_romaji": romaji,
            "title_english": english, "format": fmt, "season_year": year,
            "start_year": y, "start_month": m, "start_day": d}


def _titles(rows):
    groups, _ = group(rows)
    members = {}
    for node, root in groups.items():
        members.setdefault(root, set()).add(node)
    return sorted(sorted(m) for m in members.values())


ALDNOAH = "Aldnoah.Zero: Ame no Danshou - The Penultimate Truth"


def test_a_new_source_cannot_split_a_title_the_others_agreed_on():
    """AniList's first backfill split this title in two. Kitsu and MAL matched
    on the romaji and premiere date; AniList's English title then filled MAL's
    empty one, the merged title changed, and the Kitsu row matched nothing."""
    before = [
        _row("kitsu", "49209", romaji=ALDNOAH, fmt="OVA", year=2025, date=(2025, 3, 26)),
        _row("mal", "59843", 59843, romaji=ALDNOAH, fmt="special", year=2025, date=(2025, 3, 26)),
    ]
    anilist = _row("anilist", "181440", 59843, romaji=ALDNOAH, english="ALDNOAH.ZERO: The Penultimate Truth",
                   fmt="OVA", year=2025, date=(2025, 3, 26))

    assert _titles(before) == [["kitsu:49209", "mal:59843"]]
    assert _titles(before + [anilist]) == [["anilist:181440", "kitsu:49209", "mal:59843"]]


def test_a_row_with_one_sources_id_and_anothers_title_joins_them():
    """Kitsu has no MAL mapping for this and titles it differently from MAL, so
    it was in the catalogue twice. AniList carries MAL's id and Kitsu's title."""
    rows = [
        _row("kitsu", "45031", english="Heroines Run the Show", year=2022, date=(2022, 4, 7)),
        _row("mal", "49692", 49692, english="Heroines Run the Show: The Unpopular Girl and the Secret Task",
             year=2022, date=(2022, 4, 7)),
    ]
    assert len(_titles(rows)) == 2

    rows.append(_row("anilist", "138459", 49692, english="Heroines Run the Show", year=2022, date=(2022, 4, 7)))

    assert _titles(rows) == [["anilist:138459", "kitsu:45031", "mal:49692"]]


def test_a_name_shared_by_two_works_of_one_source_joins_neither():
    """MAL's two parts of The Tale of The Spirit Stone share an English title,
    a format and a year. Each has a Kitsu twin; the name must not fuse the
    parts."""
    rows = [
        _row("kitsu", "45779", romaji="Jing Cui Xian Zun", fmt="ONA", year=2022, date=(2022, 1, 18)),
        _row("mal", "50849", 50849, romaji="Jing Cui Xian Zun", english="The Tale of The Spirit Stone",
             fmt="ONA", year=2022, date=(2022, 1, 18)),
        _row("kitsu", "47158", 53498, english="The Tale of The Spirit Stone Part 2", fmt="ONA", year=2022,
             date=(2022, 11, 2)),
        _row("mal", "53498", 53498, english="The Tale of The Spirit Stone", fmt="ONA", year=2022,
             date=(2022, 11, 2)),
    ]
    groups, report = group(rows)

    assert _titles(rows) == [["kitsu:45779", "mal:50849"], ["kitsu:47158", "mal:53498"]]
    assert report.ambiguous == ["display:the tale of the spirit stone|short|2022"]


def test_two_music_videos_with_one_name_stay_two():
    """Two 2024 music videos called "Moonlight", months apart. The old passes
    merged them, and a Kitsu row, into one title."""
    rows = [
        _row("kitsu", "49268", romaji="Moonlight", fmt="music", year=2024, date=(2024, 9, 30)),
        _row("mal", "59994", 59994, romaji="Moonlight", fmt="music", year=2024, date=(2024, 9, 30)),
        _row("mal", "60524", 60524, romaji="Moonlight", fmt="music", year=2024, date=(2024, 12, 9)),
    ]

    # The Kitsu row still finds its own one, by premiere date.
    assert _titles(rows) == [["kitsu:49268", "mal:59994"], ["mal:60524"]]


def test_a_wrong_mal_id_from_another_source_does_not_block_a_match():
    """Kitsu maps this title to 140005, which is AniList's id for it, not MAL's.
    Every source agrees on the title; a guard on differing MAL ids across
    sources would have split it."""
    title = "Detective Conan: The Culprit Hanzawa"
    rows = [
        _row("kitsu", "45282", 140005, english=title, year=2022),
        _row("anilist", "140005", 50010, english=title, year=2022),
        _row("mal", "50010", 50010, english=title, year=2022),
    ]

    assert _titles(rows) == [["anilist:140005", "kitsu:45282", "mal:50010"]]


def test_a_work_one_source_lists_twice_is_still_one_title():
    """Kitsu lists Millenniums of Warring States twice, one copy mapped to MAL
    and one not. That is one work, not two a source keeps apart."""
    title = "Millenniums Of Warring States"
    rows = [
        _row("kitsu", "46793", 51517, english=title, fmt="ONA", year=2022, date=(2022, 7, 23)),
        _row("kitsu", "46993", english=title, fmt="ONA", year=2022, date=(2022, 7, 23)),
        _row("mal", "51517", 51517, english=title, fmt="ONA", year=2022, date=(2022, 7, 23)),
    ]

    assert len(_titles(rows)) == 1


def test_the_narrow_rules_stay_narrow():
    same = dict(english="Same Name")
    assert len(_titles([_row("kitsu", "1", fmt="TV", **same), _row("mal", "2", 2, fmt="movie", **same)])) == 2
    assert len(_titles([_row("kitsu", "1", year=2026, **same), _row("mal", "2", 2, year=2011, **same)])) == 2
    assert len(_titles([_row("kitsu", "1", fmt=None, **same), _row("mal", "2", 2, fmt=None, **same)])) == 2
    # Different formats, so only the premiere date could join these, and it is partial.
    assert len(_titles([_row("kitsu", "1", fmt="TV", date=(2026, None, None), **same),
                        _row("mal", "2", 2, fmt="movie", date=(2026, None, None), **same)])) == 2
    # A blank title is no title, however it is padded.
    assert len(_titles([_row("kitsu", "1", romaji=" "), _row("mal", "2", 2, romaji="  ")])) == 2


def test_titles_match_regardless_of_case_and_surrounding_space():
    assert len(_titles([_row("kitsu", "1", romaji="BLEACH "), _row("mal", "2", 2, romaji="Bleach")])) == 1


def test_a_mal_id_never_matches_a_source_id_that_happens_to_be_equal():
    assert len(_titles([_row("mal", "5", 5, romaji="A"), _row("kitsu", "5", romaji="B")])) == 2


def test_the_titles_do_not_depend_on_the_order_rows_arrive_in():
    rows = [
        _row("kitsu", "49268", romaji="Moonlight", fmt="music", year=2024, date=(2024, 9, 30)),
        _row("mal", "59994", 59994, romaji="Moonlight", fmt="music", year=2024, date=(2024, 9, 30)),
        _row("mal", "60524", 60524, romaji="Moonlight", fmt="music", year=2024, date=(2024, 12, 9)),
        _row("kitsu", "45031", english="Heroines Run the Show", year=2022, date=(2022, 4, 7)),
        _row("mal", "49692", 49692, english="Heroines", year=2022, date=(2022, 4, 7)),
        _row("anilist", "138459", 49692, english="Heroines Run the Show", year=2022, date=(2022, 4, 7)),
    ]
    expected = group(rows)[0]

    for seed in range(5):
        shuffled = rows[:]
        random.Random(seed).shuffle(shuffled)
        assert group(shuffled)[0] == expected


def test_the_short_forms_the_sources_file_interchangeably_count_as_one_format():
    """Plus-Sized Elf Specials: an ONA to AniList, a special to Kitsu, a day apart."""
    title = "Plus-Sized Elf Specials"
    rows = [_row("anilist", "179126", 59820, english=title, fmt="ONA", year=2024, date=(2024, 10, 6)),
            _row("kitsu", "49034", english=title, fmt="special", year=2024, date=(2024, 10, 5))]

    assert _titles(rows) == [["anilist:179126", "kitsu:49034"]]


def test_a_series_its_film_and_its_song_still_do_not():
    same = dict(english="Same Name", year=2026)
    for a, b in (("TV", "ONA"), ("movie", "OVA"), ("music", "special")):
        assert len(_titles([_row("kitsu", "1", fmt=a, **same), _row("mal", "2", 2, fmt=b, **same)])) == 2, (a, b)


def test_a_premiere_matches_on_the_romaji_as_well_as_the_display_title():
    """The War of the Rohirrim: one romaji and one premiere date in both sources,
    but Kitsu files it under 2025 with no English title, and AniList under 2024
    in English. The year keeps the title rules apart; the date does not."""
    romaji, date = "The Lord of the Rings: Rohan no Tatakai", (2024, 12, 13)
    rows = [_row("kitsu", "44686", romaji=romaji, fmt="movie", year=2025, date=date),
            _row("anilist", "185613", romaji=romaji, english="The Lord of the Rings: The War of the Rohirrim",
                 fmt="movie", year=2024, date=date)]

    assert len(_titles(rows)) == 1


def test_two_films_released_the_same_day_under_different_titles_stay_two():
    """The two Inazuma Eleven films both premiered on 27 December 2024."""
    rows = [_row("mal", "59709", 59709, romaji="Inazuma Eleven: Soushuuhen - Densetsu no Kickoff", fmt="movie",
                 year=2024, date=(2024, 12, 27)),
            _row("mal", "59710", 59710, romaji="Inazuma Eleven: Aratanaru Eiyuutachi no Joshou", fmt="movie",
                 year=2024, date=(2024, 12, 27))]

    assert len(_titles(rows)) == 2


def test_a_title_that_only_looks_latin_still_matches():
    """Kitsu and AniList spell Dandivine's romaji with a Cyrillic o (U+043E) and
    MAL with a Latin one. The strings are indistinguishable on screen and no
    title rule could match them, so the Kitsu row sat outside the title it
    belongs to. Six live rows carry one."""
    cyrillic = {"source": "anilist", "source_id": "213068",
                "title_romaji": "Juu\u043eu Mujin Dandivine", "format": "TV", "season_year": 2026}
    latin = {"source": "mal", "source_id": "64344",
             "title_romaji": "Juuou Mujin Dandivine", "format": "TV", "season_year": 2026}

    groups, _ = group([cyrillic, latin])

    assert groups["anilist:213068"] == groups["mal:64344"]


def test_folding_does_not_reach_past_the_letters_measured():
    """Folded by hand rather than with NFKC: a full compatibility fold also
    rewrites ligatures, widths and roman numerals, which was never measured."""
    built = dict(title_keys({"title_romaji": "Gundam \uff29\uff29", "format": "TV",
                             "season_year": 2026}))

    # NFKC would have made those "ii" and matched a title that is not this one.
    assert built["romaji"] == "gundam \uff49\uff49|tv|2026"
    assert "gundam ii" not in built["romaji"]

