from __future__ import annotations

import logging
from typing import Any, Callable

MODEL_NAME = "all-MiniLM-L6-v2"

# The same weights, named the way the ONNX runtime asks for them. fastembed
# fetches them from qdrant/all-MiniLM-L6-v2-onnx, which is a conversion of the
# sentence-transformers model above rather than a different model - which is the
# whole point, and is asserted in tests/test_embed_backends.py.
ONNX_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# The width of what the model returns. DuckDB stores the vectors as a fixed-size
# ARRAY - the only type array_cosine_similarity accepts - so the width has to be
# known when the table is made rather than inferred row by row.
DIM = 384

logger = logging.getLogger(__name__)

_model = None
_query_embedder: tuple[str, Callable[[str], list[float]]] | None = None


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


def _onnx_backend() -> Callable[[str], list[float]]:
    from fastembed import TextEmbedding

    model = TextEmbedding(model_name=ONNX_MODEL_NAME)

    def embed(text: str) -> list[float]:
        [vector] = model.embed([text])
        return [float(x) for x in vector]

    return embed


def _torch_backend() -> Callable[[str], list[float]]:
    model = get_embedder()
    return lambda text: [float(x) for x in model.encode(text)]


def get_query_embedder() -> tuple[str, Callable[[str], list[float]]]:
    """The thing that turns one search query into one vector, and its name.

    TWO BACKENDS FOR ONE MODEL, WHICH NEEDS SAYING

    Building the index embeds 6,349 documents in a batch, on a machine that has
    torch anyway because the weekly run installs it; sentence-transformers is
    the right tool there and embed_texts below keeps using it.

    Answering a search embeds one short string, in a process whose whole memory
    budget is 512 MB. torch does not fit that comfortably: loading the model and
    embedding a query peaked at 868 MB resident, against 406 MB through ONNX
    (measured 2026-10-12, same machine, same query). So the API asks ONNX.

    This is only safe because the two agree, and they do: measured over four
    queries, cosine similarity between the two vectors is 1.0000000 and the
    largest difference in any of the 384 elements is 3e-7 - float32 rounding,
    not disagreement. tests/test_embed_backends.py asserts it, and will fail
    rather than let the two drift apart silently.

    Prefers ONNX, falls back to torch, and says which out loud. A silent
    fallback is the dangerous version: it would turn "fastembed failed to
    install" into "the box runs out of memory on the first search", which is a
    much harder thing to read in a log.
    """
    global _query_embedder
    if _query_embedder is None:
        try:
            _query_embedder = ("onnx", _onnx_backend())
        except Exception:
            logger.warning(
                "No ONNX query embedder (fastembed) - falling back to "
                "sentence-transformers, which needs about twice the memory",
                exc_info=True,
            )
            _query_embedder = ("torch", _torch_backend())
        logger.info("Query embedding backend: %s", _query_embedder[0])
    return _query_embedder


def embed_query(text: str) -> list[float]:
    """One query's vector, by whichever backend this process can afford."""
    _, embed = get_query_embedder()
    return embed(text)


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
