"""Which MAL id a row should carry, out of what AniList said."""

import pyarrow as pa
import pyarrow.parquet as pq

from ingestion.anilist.bridge_ids import SCHEMA as LEDGER_SCHEMA
from processing.bridge import OUT_NAME, build_bridge, doubtful_mappings

_SNAPSHOT = pa.schema(
    [
        ("source", pa.string()), ("source_id", pa.string()), ("mal_id", pa.int64()),
        ("title_romaji", pa.string()), ("title_english", pa.string()), ("format", pa.string()),
        ("season_year", pa.int64()), ("start_year", pa.int64()), ("start_month", pa.int64()),
        ("start_day", pa.int64()),
    ]
)


def _rows(data_dir, source, partition, rows, run_date="2026-09-21"):
    """A source's own rows. Each is a dict of whatever matters to the test:
    source_id, premiere (y, m, d), mal_id, title. A MAL row carries its own id
    unless the test says otherwise."""
    out = data_dir / "processed" / f"{source}_media" / partition / f"{run_date}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    built = []
    for row in rows:
        year, month, day = row.get("premiere", (None, None, None))
        built.append(
            {
                "source": source,
                "source_id": str(row["source_id"]),
                "mal_id": row.get("mal_id", int(row["source_id"]) if source == "mal" else None),
                "title_romaji": row.get("title", f"{source} {row['source_id']}"),
                "title_english": row.get("english"),
                "format": row.get("format", "ONA"),
                "season_year": year,
                "start_year": year, "start_month": month, "start_day": day,
            }
        )
    pq.write_table(pa.Table.from_pylist(built, schema=_SNAPSHOT), out)


def _ledger(data_dir, searched_on, rows):
    """What AniList said: (source_key, anilist_id, mal_id)."""
    out = data_dir / "processed" / "anilist_bridge" / f"{searched_on}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"source_key": key, "anilist_id": anilist_id, "mal_id": mal_id,
                 "matched_by": "premiere", "title": key, "searched_on": searched_on}
                for key, anilist_id, mal_id in rows
            ],
            schema=LEDGER_SCHEMA,
        ),
        out,
    )


def _decided(data_dir):
    path = data_dir / "processed" / OUT_NAME
    if not path.exists():
        return {}
    return {r["source_key"]: (r["mal_id"], r["action"]) for r in pq.read_table(path).to_pylist()}


# --- giving a MAL id to a row that has none -----------------------------------------

def test_a_row_whose_twin_premiered_the_same_day_is_given_its_mal_id(tmp_path):
    """Zhu Xian Final and Jade Dynasty Final Season, both on 21 August 2026: the
    same show under two names, and no rule in matching.py can see it."""
    _rows(tmp_path, "kitsu", "2026-SUMMER", [{"source_id": "50936", "premiere": (2026, 8, 21)}])
    _rows(tmp_path, "mal", "2026-SUMMER", [{"source_id": "62990", "premiere": (2026, 8, 21)}])
    _ledger(tmp_path, "2026-09-22", [("kitsu:50936", 206189, 62990)])

    build_bridge(tmp_path)

    assert _decided(tmp_path) == {"kitsu:50936": (62990, "fill")}


def test_a_stale_cross_reference_to_an_earlier_season_is_refused(tmp_path):
    """AniList files Throne of Seal 3 under Throne of Seal 2nd Season's MAL id.
    Adopting it would merge a 2025 series into a 2022 one and delete a title."""
    _rows(tmp_path, "kitsu", "2025-SPRING", [{"source_id": "50289", "premiere": (2025, 5, 1)}])
    _rows(tmp_path, "mal", "2022-FALL", [{"source_id": "52684", "premiere": (2022, 11, 10)}])
    _ledger(tmp_path, "2026-09-22", [("kitsu:50289", 185729, 52684)])

    build_bridge(tmp_path)

    assert _decided(tmp_path) == {}


def test_a_premiere_a_few_days_apart_is_accepted(tmp_path):
    """Santa Tell Me is a day apart across the two sources and is one work. The
    window was zero until it was measured: every real pair sits within three
    days and nothing new appears beyond, out to a month."""
    _rows(tmp_path, "kitsu", "2024-WINTER", [{"source_id": "1", "premiere": (2023, 12, 4)}])
    _rows(tmp_path, "mal", "2023-FALL", [{"source_id": "57586", "premiere": (2023, 12, 5)}])
    _ledger(tmp_path, "2026-09-22", [("kitsu:1", 900, 57586)])

    build_bridge(tmp_path)

    assert _decided(tmp_path) == {"kitsu:1": (57586, "fill")}


def test_a_premiere_outside_the_window_is_still_refused(tmp_path):
    """Four days is outside it, and nothing real was ever found out there."""
    _rows(tmp_path, "kitsu", "2024-WINTER", [{"source_id": "1", "premiere": (2023, 12, 1)}])
    _rows(tmp_path, "mal", "2023-FALL", [{"source_id": "57586", "premiere": (2023, 12, 5)}])
    _ledger(tmp_path, "2026-09-22", [("kitsu:1", 900, 57586)])

    build_bridge(tmp_path)

    assert _decided(tmp_path) == {}


def test_an_incomplete_premiere_proves_nothing(tmp_path):
    _rows(tmp_path, "kitsu", "2026-SUMMER", [{"source_id": "1", "premiere": (2026, None, None)}])
    _rows(tmp_path, "mal", "2026-SUMMER", [{"source_id": "2", "premiere": (2026, None, None)}])
    _ledger(tmp_path, "2026-09-22", [("kitsu:1", 900, 2)])

    build_bridge(tmp_path)

    assert _decided(tmp_path) == {}


def test_an_id_no_row_carries_is_not_adopted(tmp_path):
    """There is no merge to verify, and an unverifiable id on a row is one that
    may merge something later for no reason anyone can check."""
    _rows(tmp_path, "kitsu", "2026-SUMMER", [{"source_id": "1", "premiere": (2026, 8, 21)}])
    _rows(tmp_path, "mal", "2026-SUMMER", [{"source_id": "999", "premiere": (2026, 8, 21)}])
    _ledger(tmp_path, "2026-09-22", [("kitsu:1", 900, 62990)])

    build_bridge(tmp_path)

    assert _decided(tmp_path) == {}


def test_an_id_already_on_rows_that_disagree_is_refused(tmp_path):
    """An id can already name a group that is wrong. Adding a correct title to
    it would make the wrong group bigger, not the catalogue better."""
    _rows(tmp_path, "kitsu", "2023-WINTER", [{"source_id": "49158", "premiere": (2023, 1, 14)}])
    _rows(tmp_path, "kitsu", "2022-SPRING",
          [{"source_id": "47013", "premiere": (2022, 4, 23), "mal_id": 54285, "title": "Yao Shen Ji 6"}])
    _rows(tmp_path, "mal", "2023-WINTER",
          [{"source_id": "54285", "premiere": (2023, 1, 14), "title": "Yao Shen Ji 7th Season"}])
    _ledger(tmp_path, "2026-09-22", [("kitsu:49158", 900, 54285)])

    build_bridge(tmp_path)

    assert _decided(tmp_path) == {}


# --- correcting a MAL id that cannot be right ---------------------------------------

def _yao_shen_ji(tmp_path):
    """Kitsu maps its row for season 6 to season 7's MAL id, which is how the
    catalogue came to hold two seasons as one title."""
    _rows(tmp_path, "kitsu", "2022-SPRING",
          [{"source_id": "47013", "premiere": (2022, 4, 23), "mal_id": 54285, "title": "Yao Shen Ji 6"}])
    _rows(tmp_path, "mal", "2023-WINTER",
          [{"source_id": "54285", "premiere": (2023, 1, 14), "title": "Yao Shen Ji 7th Season"}])
    _rows(tmp_path, "mal", "2022-SPRING",
          [{"source_id": "59891", "premiere": (2022, 4, 23), "title": "Yao Shen Ji 6th Season"}])


def test_a_mapping_a_second_source_contradicts_is_corrected(tmp_path):
    """AniList names 59891 for this row, and MAL's own row for 59891 premiered
    on its exact day, while the mapped one is nine months away."""
    _yao_shen_ji(tmp_path)
    _ledger(tmp_path, "2026-09-22", [("kitsu:47013", 900, 59891)])

    build_bridge(tmp_path)

    assert _decided(tmp_path) == {"kitsu:47013": (59891, "replace")}


def test_correcting_one_row_frees_the_id_for_the_row_it_belongs_to(tmp_path):
    """The point of deciding corrections before fills. With season 6's row off
    season 7's id, that id names one row again, so Kitsu's own row for season 7
    can be given it in the same pass."""
    _yao_shen_ji(tmp_path)
    _rows(tmp_path, "kitsu", "2023-WINTER",
          [{"source_id": "49158", "premiere": (2023, 1, 14), "title": "Yao Shen Ji 7"}])
    _ledger(tmp_path, "2026-09-22", [("kitsu:47013", 900, 59891), ("kitsu:49158", 901, 54285)])

    build_bridge(tmp_path)

    assert _decided(tmp_path) == {
        "kitsu:47013": (59891, "replace"),
        "kitsu:49158": (54285, "fill"),
    }


def test_a_proposed_id_nothing_can_be_checked_against_is_left_alone(tmp_path):
    """Fei Ren Zai 2 Part 2: AniList names an id MAL has never been fetched for,
    so the mapping stays as Kitsu has it rather than being replaced by a guess."""
    _rows(tmp_path, "kitsu", "2023-WINTER",
          [{"source_id": "50508", "premiere": (2023, 1, 18), "mal_id": 52523, "title": "Fei Ren Zai 2 Part 2"}])
    _rows(tmp_path, "mal", "2022-SUMMER",
          [{"source_id": "52523", "premiere": (2022, 8, 10), "title": "Fei Ren Zai 2nd Season"}])
    _ledger(tmp_path, "2026-09-22", [("kitsu:50508", 900, 54061)])

    build_bridge(tmp_path)

    assert _decided(tmp_path) == {}


def test_a_mapping_the_second_source_agrees_with_is_left_alone(tmp_path):
    """Eight of the fifteen asked about. A gap alone is not a wrong mapping."""
    _yao_shen_ji(tmp_path)
    _ledger(tmp_path, "2026-09-22", [("kitsu:47013", 900, 54285)])

    build_bridge(tmp_path)

    assert _decided(tmp_path) == {}


def test_a_wrong_year_under_one_name_is_never_questioned(tmp_path):
    """26 pairs sit at exactly 365 days apart under the same name: one source
    has the year wrong and the mapping is right. Distrusting those on the gap
    would have broken correct merges."""
    _rows(tmp_path, "kitsu", "2023-WINTER",
          [{"source_id": "47756", "premiere": (2023, 1, 14), "mal_id": 54383, "title": "Case 143"}])
    _rows(tmp_path, "mal", "2022-WINTER",
          [{"source_id": "54383", "premiere": (2022, 1, 14), "title": "Case 143"}])

    assert doubtful_mappings(tmp_path) == []


def test_a_mapping_inside_a_season_is_not_questioned(tmp_path):
    """4,557 of 4,654 comparable mappings agree within a week. Inside thirteen
    weeks the sources are arguing about a date, not describing another work."""
    _rows(tmp_path, "kitsu", "2026-SUMMER",
          [{"source_id": "1", "premiere": (2026, 7, 1), "mal_id": 2, "title": "One Name"}])
    _rows(tmp_path, "mal", "2026-SUMMER",
          [{"source_id": "2", "premiere": (2026, 8, 21), "title": "Another Name"}])

    assert doubtful_mappings(tmp_path) == []


def test_a_row_months_away_under_another_name_is_worth_asking_about(tmp_path):
    _yao_shen_ji(tmp_path)

    assert [r["source_key"] for r in doubtful_mappings(tmp_path)] == ["kitsu:47013"]


def test_a_doubtful_mapping_is_put_in_front_of_anilist(tmp_path):
    """The rows bridge.py wants a second opinion on are exactly the rows
    bridge_ids asks about, alongside those with no MAL id at all."""
    from ingestion.anilist.bridge_ids import unsearched

    _yao_shen_ji(tmp_path)

    assert [r["source_key"] for r in unsearched(tmp_path, "2026-09-22")] == ["kitsu:47013"]


def test_a_row_already_asked_about_is_not_asked_again(tmp_path):
    from ingestion.anilist.bridge_ids import unsearched

    _yao_shen_ji(tmp_path)
    _ledger(tmp_path, "2026-09-22", [("kitsu:47013", 900, 59891)])

    assert unsearched(tmp_path, "2026-09-23") == []
    assert [r["source_key"] for r in unsearched(tmp_path, "2026-11-30")] == ["kitsu:47013"]


# --- asserted by hand ---------------------------------------------------------------

def test_an_override_wins_over_what_the_evidence_decided(tmp_path, monkeypatch):
    """The point of the file: a person who knows two rows are the same show,
    saying so, when no rule can get there."""
    _yao_shen_ji(tmp_path)
    _ledger(tmp_path, "2026-09-22", [("kitsu:47013", 900, 59891)])
    monkeypatch.setattr("processing.mal_id_overrides.OVERRIDES",
                        {"kitsu:47013": (54285, "a person looked")})

    build_bridge(tmp_path)

    assert _decided(tmp_path) == {"kitsu:47013": (54285, "override")}


def test_an_override_can_also_say_there_is_no_right_id(tmp_path, monkeypatch):
    """The opposite assertion: this mapping is wrong and nothing can contradict
    it, so carry none rather than a wrong one."""
    _yao_shen_ji(tmp_path)
    monkeypatch.setattr("processing.mal_id_overrides.OVERRIDES",
                        {"kitsu:47013": (None, "Kitsu maps this to the wrong season")})

    build_bridge(tmp_path)

    assert _decided(tmp_path) == {"kitsu:47013": (None, "override")}


def test_an_override_reaches_a_row_no_rule_could(tmp_path, monkeypatch):
    """Dandivine: Kitsu says Jyuou and MAL says Juuou, which differ for real, so
    no title rule matches and the search has nothing strict to match back."""
    _rows(tmp_path, "kitsu", "2026-FALL",
          [{"source_id": "50991", "premiere": (2026, 10, 8), "title": "Jyuou Mujin Dandivine"}])
    _rows(tmp_path, "mal", "2026-FALL",
          [{"source_id": "64344", "premiere": (2026, 10, 8), "title": "Juuou Mujin Dandivine"}])
    monkeypatch.setattr("processing.mal_id_overrides.OVERRIDES",
                        {"kitsu:50991": (64344, "same premiere, same show")})

    build_bridge(tmp_path)

    assert _decided(tmp_path) == {"kitsu:50991": (64344, "override")}


def test_an_override_for_a_row_that_is_gone_is_skipped_and_said_out_loud(tmp_path, monkeypatch, caplog):
    """How a stale entry surfaces: the row it was about no longer exists, so the
    assertion is now about nothing and the file should lose it."""
    _yao_shen_ji(tmp_path)
    _ledger(tmp_path, "2026-09-22", [("kitsu:47013", 900, 59891)])
    monkeypatch.setattr("processing.mal_id_overrides.OVERRIDES",
                        {"kitsu:99999": (1, "a row that left years ago")})

    with caplog.at_level("WARNING"):
        build_bridge(tmp_path)

    assert _decided(tmp_path) == {"kitsu:47013": (59891, "replace")}
    assert "names a row no source holds any more" in caplog.text


def test_the_shipped_overrides_are_shaped_like_source_keys():
    """They are typed by hand, and a typo would otherwise fail inside a weekly
    run rather than here."""
    from processing.mal_id_overrides import OVERRIDES

    for key, (mal_id, reason) in OVERRIDES.items():
        source, _, source_id = key.partition(":")
        assert source and source_id, key
        assert mal_id is None or isinstance(mal_id, int), key
        assert reason.strip(), key


# --- housekeeping -------------------------------------------------------------------

def test_a_search_that_found_nothing_says_nothing(tmp_path):
    _rows(tmp_path, "kitsu", "2026-SUMMER", [{"source_id": "1", "premiere": (2026, 8, 21)}])
    _rows(tmp_path, "mal", "2026-SUMMER", [{"source_id": "2", "premiere": (2026, 8, 21)}])
    _ledger(tmp_path, "2026-09-22", [("kitsu:1", None, None)])

    assert build_bridge(tmp_path) is None
    assert _decided(tmp_path) == {}


def test_the_newest_answer_about_a_row_is_the_one_used(tmp_path):
    """A monthly re-search can correct what an earlier one found."""
    _rows(tmp_path, "kitsu", "2026-SUMMER", [{"source_id": "1", "premiere": (2026, 8, 21)}])
    _rows(tmp_path, "mal", "2026-SUMMER",
          [{"source_id": "2", "premiere": (2026, 8, 21)}, {"source_id": "3", "premiere": (2026, 8, 21)}])
    _ledger(tmp_path, "2026-09-22", [("kitsu:1", 900, 2)])
    _ledger(tmp_path, "2026-11-30", [("kitsu:1", 901, 3)])

    build_bridge(tmp_path)

    assert _decided(tmp_path) == {"kitsu:1": (3, "fill")}


def test_a_mapping_whose_evidence_is_gone_does_not_go_on_merging(tmp_path):
    """The file is rebuilt every run, and removed when nothing survives, so a
    stale one cannot keep joining titles after the ledger stops saying so."""
    _rows(tmp_path, "kitsu", "2026-SUMMER", [{"source_id": "1", "premiere": (2026, 8, 21)}])
    _rows(tmp_path, "mal", "2026-SUMMER", [{"source_id": "2", "premiere": (2026, 8, 21)}])
    _ledger(tmp_path, "2026-09-22", [("kitsu:1", 900, 2)])
    build_bridge(tmp_path)

    (tmp_path / "processed" / "anilist_bridge" / "2026-09-22.parquet").unlink()
    build_bridge(tmp_path)

    assert _decided(tmp_path) == {}


def test_nothing_at_all_is_not_an_error(tmp_path):
    assert build_bridge(tmp_path) is None
    assert doubtful_mappings(tmp_path) == []
