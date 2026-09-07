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
