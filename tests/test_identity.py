"""Stable identities for titles.

The one promise here is that an identity does not move. Every test below is some
way it could, and a check that it doesn't.
"""

from processing.identity import Registry, assign, load, save


def _run(groups, registry=None, today="2026-09-10"):
    ids, reg, report = assign(groups, registry or Registry(), today)
    return ids, reg, report


def test_a_first_run_mints_one_identity_per_title():
    ids, reg, report = _run([["kitsu:1", "mal:10"], ["kitsu:2"], ["mal:30"]])

    assert len(set(ids)) == 3
    assert all(i.startswith("wb_") for i in ids)
    assert report.minted == 3 and report.reused == 0
    assert reg.identity_of("mal:10") == ids[0]


def test_the_same_titles_next_week_keep_the_same_identities():
    groups = [["kitsu:1", "mal:10"], ["kitsu:2"]]
    first, reg, _ = _run(groups)

    second, _, report = _run(groups, reg, today="2026-09-17")

    assert second == first
    assert report.reused == 2 and report.minted == 0


def test_the_identity_survives_the_merge_choosing_a_different_winner():
    """The reason this exists. AniList returning and outranking Kitsu, or a new
    pass collapsing rows differently, changes which source row survives - and
    with it the title's old (source, source_id) address. The identity must not
    care which member happened to win."""
    first, reg, _ = _run([["kitsu:1", "mal:10"]])

    # Same show, reported by a source that did not exist last week and now wins.
    second, _, _ = _run([["anilist:900", "kitsu:1", "mal:10"]], reg)

    assert second == first


def test_a_title_known_by_only_one_of_its_keys_is_still_found():
    """A source can drop a title from its listing while another keeps it."""
    first, reg, _ = _run([["kitsu:1", "mal:10"]])

    second, _, _ = _run([["mal:10"]], reg)

    assert second == first


def test_a_new_title_is_minted_while_the_rest_are_reused():
    first, reg, _ = _run([["kitsu:1"], ["kitsu:2"]])

    second, _, report = _run([["kitsu:1"], ["kitsu:2"], ["mal:99"]], reg)

    assert second[:2] == first
    assert second[2] not in first
    assert report.minted == 1 and report.reused == 2


def test_two_identities_recognised_as_one_show_merge_into_the_older():
    """A merge rule improves and collapses what used to be two titles - exactly
    what the premiere-date pass did to eight live pairs. The older identity is
    the one more likely to have been linked to, so it survives, and the younger
    becomes an alias so its address still resolves."""
    a, reg, _ = _run([["kitsu:1"]], today="2026-06-15")
    b, reg, _ = _run([["kitsu:1"], ["mal:10"]], reg, today="2026-09-09")
    older, younger = a[0], b[1]

    merged, reg, report = _run([["kitsu:1", "mal:10"]], reg, today="2026-09-10")

    assert merged == [older]
    assert report.merged == 1
    assert reg.resolve(younger) == older
    assert reg.identity_of("mal:10") == older
    assert reg.alias_date[younger] == "2026-09-10"


def test_a_split_never_leaves_two_titles_sharing_one_identity():
    """A rule gets stricter and one title becomes two. Both groups would claim
    the old identity; if both got it, anything deduplicating by identity would
    silently delete one of the two shows."""
    first, reg, _ = _run([["kitsu:1", "kitsu:2", "mal:10"]])

    ids, _, report = _run([["kitsu:1", "mal:10"], ["kitsu:2"]], reg)

    assert len(set(ids)) == 2
    assert report.split == 1
    # the group holding most of the old identity's keys keeps it
    assert ids[0] == first[0]


def test_a_title_that_disappears_gets_its_identity_back_when_it_returns():
    first, reg, _ = _run([["kitsu:1"], ["kitsu:2"]])
    _, reg, _ = _run([["kitsu:1"]], reg)  # kitsu:2 drops out for a week

    back, _, _ = _run([["kitsu:1"], ["kitsu:2"]], reg)

    assert back == first


def test_minting_is_deterministic_so_a_rerun_reissues_the_same_ids():
    """A retried run must not hand out a second, different set of identities."""
    groups = [["kitsu:1", "mal:10"], ["kitsu:2"]]

    assert _run(groups)[0] == _run(groups)[0]


def test_every_group_in_a_run_gets_a_distinct_identity():
    """The invariant everything downstream relies on, checked across a mix of
    reuse, merge, split and mint in one run."""
    _, reg, _ = _run([["a:1", "a:2", "a:3"], ["b:1"], ["c:1"]])

    ids, _, _ = _run([["a:1", "a:2"], ["a:3"], ["b:1", "c:1"], ["d:1"]], reg)

    assert len(ids) == len(set(ids))


def test_assign_does_not_modify_the_registry_it_was_given():
    _, reg, _ = _run([["kitsu:1"]])
    snapshot = (dict(reg.keys), dict(reg.minted), dict(reg.aliases))

    _run([["kitsu:1", "mal:10"], ["kitsu:2"]], reg)

    assert (reg.keys, reg.minted, reg.aliases) == snapshot


def test_aliases_are_followed_to_the_end_of_a_chain():
    reg = Registry(aliases={"wb_a": "wb_b", "wb_b": "wb_c"})

    assert reg.resolve("wb_a") == "wb_c"


def test_an_alias_cycle_cannot_hang_the_pipeline():
    """A correct registry never has one. A hand-edited one might, and an infinite
    loop in a weekly job is a far worse failure than an unresolved alias."""
    reg = Registry(aliases={"wb_a": "wb_b", "wb_b": "wb_a"})

    assert reg.resolve("wb_a") in {"wb_a", "wb_b"}


def test_the_registry_round_trips_through_disk(tmp_path):
    a, reg, _ = _run([["kitsu:1"]], today="2026-06-15")
    b, reg, _ = _run([["kitsu:1"], ["mal:10"]], reg, today="2026-09-09")
    _, reg, _ = _run([["kitsu:1", "mal:10"]], reg, today="2026-09-10")

    save(tmp_path, reg)
    loaded = load(tmp_path)

    assert loaded.keys == reg.keys
    assert loaded.minted == reg.minted
    assert loaded.aliases == reg.aliases
    assert loaded.alias_date == reg.alias_date
    assert loaded.resolve(b[1]) == a[0]


def test_saving_leaves_no_partial_file_behind(tmp_path):
    """Written beside the target and moved into place. A torn registry would cost
    every identity ever issued, so the temporary must never be what survives."""
    _, reg, _ = _run([["kitsu:1"]])

    path = save(tmp_path, reg)

    assert path.exists()
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_a_missing_registry_is_an_empty_one_not_an_error(tmp_path):
    """The first ever run has nothing to load."""
    reg = load(tmp_path)

    assert reg.keys == {} and reg.minted == {}


def test_a_partly_absorbed_identity_leaves_no_key_pointing_at_a_dead_address():
    """An identity with two keys; this week only one of them turns up, and it
    arrives inside another title's group. The absent key must still resolve to a
    live identity in ONE lookup - the warehouse view and the API read the saved
    registry with a single join, not a walk."""
    _, reg, _ = _run([["kitsu:1"]], today="2026-06-15")          # X, the older
    _, reg, _ = _run([["kitsu:1"], ["mal:10", "jikan:5"]], reg)  # Y = {mal:10, jikan:5}

    ids, reg, _ = _run([["kitsu:1", "mal:10"]], reg)             # mal:10 joins X; jikan:5 absent

    live = set(ids)
    assert all(w in live for w in reg.keys.values())
    assert reg.keys["jikan:5"] == ids[0]


def test_alias_chains_are_flattened_so_one_hop_always_reaches_the_end():
    _, reg, _ = _run([["a:1"]], today="2026-01-01")
    _, reg, _ = _run([["a:1"], ["b:1"]], reg, today="2026-02-01")
    _, reg, _ = _run([["a:1"], ["b:1"], ["c:1"]], reg, today="2026-03-01")
    _, reg, _ = _run([["b:1", "c:1"], ["a:1"]], reg, today="2026-04-01")   # c merges into b

    ids, reg, _ = _run([["a:1", "b:1", "c:1"]], reg, today="2026-05-01")  # b merges into a

    assert set(reg.aliases.values()) <= set(ids)
