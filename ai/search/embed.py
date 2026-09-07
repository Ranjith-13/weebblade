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


def text_for_embedding(row: dict[str, Any]) -> str:
    """Build the text representation of a title that gets embedded.

    Title + genres + synopsis, in that order - title and genres are short and always
    present, synopsis carries most of the actual semantic signal when it exists.
    """
    title = row.get("title_english") or row.get("title_romaji") or "Untitled"
    parts = [title]

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
