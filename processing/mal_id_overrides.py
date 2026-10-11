"""MAL ids asserted by hand, when no rule can reach the answer.

Every other path to a MAL id is evidence: a source supplied it, or AniList named
it and a premiere confirmed it. This file is the exception - a person who knows
two rows are the same show, saying so. It lives in the repository rather than in
the data, so each entry is reviewed in a diff, carries its reason, and can be
taken back.

WHEN TO ADD ONE

Only when the rules cannot get there and the answer is not in doubt. The test is
whether the reason below would convince someone else looking at the two rows.

NOT as a substitute for fixing a rule. If a handful of entries start sharing a
cause, that cause is a rule worth changing, and the entries should disappear
with it - that is how the premiere window went from zero to three days, and how
Latin-looking Cyrillic letters came to be folded. An override that papers over a
pattern hides the thing worth fixing.

HOW IT BEHAVES

An entry wins over anything the evidence decided: it sets the row's MAL id
outright. A value of None means the opposite assertion - this row has no correct
MAL id, so carry none - which is how a mapping that is wrong but that nothing
can contradict gets taken out of the merge.
"""

from __future__ import annotations

# source key -> (MAL id or None, why)
OVERRIDES: dict[str, tuple[int | None, str]] = {
    "kitsu:50991": (
        64344,
        # Dandivine. The catalogue held it once until 2026-10-11, when AniList
        # renamed its romaji from Jyuou to Juuou; the Kitsu row was joined to the
        # group only through that string, so the title split in two and the
        # pipeline's own check caught it.
        #
        # Nothing can repair it automatically. Kitsu still says Jyuou and MAL says
        # Juuou, which differ for real rather than invisibly, so no title rule
        # matches. The bridge cannot help either: it searches AniList by the
        # Kitsu title and needs a strict match back, and "Jyuou" does not match
        # "Juuou". Both Kitsu and AniList also spell it with a Cyrillic o
        # (U+043E), though folding that is no longer what stands in the way.
        #
        # That they are one show is not in doubt: same premiere (8 October 2026),
        # same season, same format, and MAL 64344 is the entry AniList itself
        # points at from the row that used to hold this group together.
        "Kitsu romaji (Jyuou) and MAL romaji (Juuou) differ for real; same "
        "premiere 2026-10-08, same format, AniList's own entry names this id",
    ),
}
