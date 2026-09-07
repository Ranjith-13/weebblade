from fastapi.testclient import TestClient

from backend.app.main import app


def test_search_returns_503_when_index_not_built(tmp_path, monkeypatch):
    import backend.app.routers.search as search_module

    monkeypatch.setattr(search_module, "CHROMA_DIR", tmp_path / "chroma")

    with TestClient(app) as client:
        response = client.get("/search", params={"q": "magic and war"})

    assert response.status_code == 503


def test_search_requires_nonempty_query():
    with TestClient(app) as client:
        response = client.get("/search", params={"q": ""})

    assert response.status_code == 422


def test_search_is_rate_limited(tmp_path, monkeypatch):
    # /search has a stricter 20/minute limit than the app default (60/minute) since
    # it runs the embedding model on every call. The 503 "index not built" path is
    # still subject to the limit - rate limiting happens before the route body runs.
    # Checks the behavior (early requests pass, the limiter does eventually kick
    # in) rather than an exact request-count boundary, since that's an internal
    # slowapi counting detail, not a contract worth pinning a test to.
    import backend.app.routers.search as search_module

    monkeypatch.setattr(search_module, "CHROMA_DIR", tmp_path / "chroma")

    with TestClient(app) as client:
        statuses = [client.get("/search", params={"q": "test"}).status_code for _ in range(25)]

    assert statuses[0] == 503
    assert 429 in statuses
