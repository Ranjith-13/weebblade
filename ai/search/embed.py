from __future__ import annotations

from typing import Any

MODEL_NAME = "all-MiniLM-L6-v2"

_model = None


def get_embedder():
    """Lazily load the sentence-transformers model - importing it (and its torch
    dependency) at module load time would slow down every import of this package,
    including ones that never actually embed anything.
    """
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(MODEL_NAME)
    return _model


# The shared format vocabulary, said the way a person would type it. "TV" alone
# embeds badly - it is two characters and a hundred other meanings.
_FORMAT_WORDS = {
    "TV": "TV series",
    "movie": "film",
    "OVA": "OVA",
    "ONA": "ONA",
    "special": "special",
    "music": "music video",
}


def _names(row: dict[str, Any]) -> list[str]:
    """Every name the title is known by, the display one first.

    Both, not one. Embedding only the display title meant a title listed in
    English could not be found by the name it airs under: searching the romaji
    of 40 such titles put the right one first 10 times (2026-09-21). The English
    name is what the site shows, so it leads.
    """
    english, romaji = row.get("title_english"), row.get("title_romaji")
    names = [n for n in (english, romaji) if n]
    if len(names) == 2 and names[0].strip().lower() == names[1].strip().lower():
        return names[:1]
    return names


def _shape(row: dict[str, Any]) -> list[str]:
    """What kind of thing the title is: format, when it ran, who made it, what
    it was adapted from."""
    said = [_FORMAT_WORDS.get(row.get("format") or "", row.get("format") or "")]
    season, year = row.get("season"), row.get("season_year")
    if season and year:
        said.append(f"{season.capitalize()} {year}")
    elif year:
        said.append(str(year))
    studios = row.get("studios") or []
    if studios:
        said.append("by " + ", ".join(studios))

    parts = [", ".join(part for part in said if part)] if any(said) else []
    material = row.get("source_material")
    if material:
        parts.append(
            "An original story" if material == "original"
            else f"Adapted from {material.replace('_', ' ')}"
        )
    return parts


def text_for_embedding(row: dict[str, Any]) -> str:
    """Build the text representation of a title that gets embedded.

    Every name, then genres, then the synopsis, which carries most of the
    semantic signal where it exists. Where it does not - 531 titles, 8% of the
    catalogue on 2026-09-21 - what the thing IS takes its place: a 2019 film by
    ufotable adapted from a manga is a description, and a bare title is not.

    Only where it does not, because the model mean-pools: every word added
    dilutes the rest. Four documents were built over the live catalogue and
    measured on twelve vague queries (how many of the top ten carry a genre the
    query asked for) and on 40 titles the site shows in English (how often
    typing the other name finds them):

        display title only     102/120 on-genre, 29 thin results, romaji 10/40
        + names + shape always  97/120,          24,              romaji 19/40
        + names only           100/120,          25,              romaji 23/40
        + names, shape if thin 102/120,          15,              romaji 22/40

    The last is this one: the whole gain in finding a title by its other name,
    no loss on vague queries, and thin titles crowding the results half as often
    as before, because a document that says what a thing is stops being a
    near-generic vector that every query matches a little.
    """
    parts = [", ".join(_names(row)) or "Untitled"]
    synopsis = row.get("synopsis")
    if not synopsis:
        parts += _shape(row)

    genres = row.get("genres") or []
    if genres:
        parts.append("Genres: " + ", ".join(genres))
    if synopsis:
        parts.append(synopsis)

    return ". ".join(parts)


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = get_embedder()
    return model.encode(texts, show_progress_bar=False).tolist()
