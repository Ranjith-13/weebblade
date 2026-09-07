from __future__ import annotations

from pathlib import Path
from typing import Any

from .build_index import COLLECTION_NAME
from .embed import embed_texts


def find_similar(chroma_dir: Path, query_text: str, n_results: int = 10) -> list[dict[str, Any]]:
    """Embed a free-text query (a title, a vibe, a description) and return the most
    semantically similar indexed titles, nearest first.
    """
    from .client import get_chroma_client

    client = get_chroma_client(chroma_dir)
    collection = client.get_collection(COLLECTION_NAME)

    [query_embedding] = embed_texts([query_text])
    result = collection.query(query_embeddings=[query_embedding], n_results=n_results)

    matches = []
    for metadata, distance in zip(result["metadatas"][0], result["distances"][0]):
        matches.append({**metadata, "distance": distance})
    return matches


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query", help="A title or free-text description to search for")
    parser.add_argument("--chroma-dir", type=Path, default=Path("data/chroma"))
    parser.add_argument("-n", "--n-results", type=int, default=10)
    args = parser.parse_args()

    for rank, match in enumerate(find_similar(args.chroma_dir, args.query, args.n_results), 1):
        print(f"{rank}. {match['title']} (distance={match['distance']:.4f}, source={match['source']})")
