"""The index and the queries must keep being the same model.

Documents are embedded in the weekly run by sentence-transformers, on a machine
that has torch anyway. Queries are embedded by the API through ONNX, because
torch does not fit in 512 MB - 406 MB resident against 868, measured
2026-10-12. Two libraries, one set of weights.

That split is only sound while the two produce the same vector, and nothing
about it would announce itself if they stopped: search would just get quietly,
unexplainably worse, with every ranking computed between a query from one model
and documents from another. So it is asserted here, and this test is the reason
the arrangement is allowed to exist.
"""

import math

import pytest

from ai.search.embed import DIM

pytest.importorskip("fastembed", reason="the ONNX query backend is not installed")
pytest.importorskip("sentence_transformers", reason="the torch index backend is not installed")

# A title, a vague description and a one-word query - the three shapes a reader
# actually types, and short strings are where tokenisation differences between
# two implementations would show up first.
QUERIES = [
    "Sousou no Frieren",
    "dark psychological thriller with an unreliable narrator",
    "mecha",
    "cozy slice of life about cooking and small restaurants",
]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


@pytest.mark.parametrize("query", QUERIES)
def test_the_onnx_and_torch_backends_return_the_same_vector(query):
    from ai.search.embed import _onnx_backend, _torch_backend

    onnx, torch_based = _onnx_backend()(query), _torch_backend()(query)

    assert len(onnx) == len(torch_based) == DIM
    # Cosine, because that is what the search actually computes
    # (array_cosine_similarity in ai/search/query.py): two vectors this close
    # cannot rank the catalogue differently.
    similarity = _cosine(onnx, torch_based)
    biggest_difference = max(abs(x - y) for x, y in zip(onnx, torch_based))
    assert similarity > 0.999999, f"{query!r}: cosine {similarity:.7f}"
    # Observed 1e-7, which is float32 rounding rather than disagreement. The
    # threshold is two orders of magnitude looser so a different ONNX runtime
    # build cannot make this flaky, and still tight enough that an actual
    # change of model or pooling could not slip under it.
    assert biggest_difference < 1e-5, f"{query!r}: max element diff {biggest_difference:.2e}"
