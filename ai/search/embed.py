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


def text_for_embedding(row: dict[str, Any]) -> str:
    """Build the text representation of a title that gets embedded.

    Names, then what kind of thing it is, then genres, then synopsis. The
    synopsis carries most of the semantic signal where it exists - and for the
    531 titles with none (8% of the catalogue, 2026-09-21) the rest is all there
    is, which is why the shape of the thing is worth saying: a 2019 film by
    ufotable adapted from a manga is a description, and a bare title is not.
    """
    parts = [", ".join(_names(row)) or "Untitled"]

    shape = [_FORMAT_WORDS.get(row.get("format") or "", row.get("format") or "")]
    season, year = row.get("season"), row.get("season_year")
    if season and year:
        shape.append(f"{season.capitalize()} {year}")
    elif year:
        shape.append(str(year))
    studios = row.get("studios") or []
    if studios:
        shape.append("by " + ", ".join(studios))
    shape = [part for part in shape if part]
    if shape:
        parts.append(", ".join(shape))

    material = row.get("source_material")
    if material:
        parts.append(
            "An original story" if material == "original"
            else f"Adapted from {material.replace('_', ' ')}"
        )

    genres = row.get("genres") or []
    if genres:
        parts.append("Genres: " + ", ".join(genres))

    synopsis = row.get("synopsis")
    if synopsis:
        parts.append(synopsis)

    return ". ".join(parts)


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = get_embedder()
    return model.encode(texts, show_progress_bar=False).tolist()
