from fastapi.testclient import TestClient

from backend.app.main import app


def test_latest_digest_returns_503_when_none_exist(tmp_path, monkeypatch):
    import backend.app.routers.digest as digest_module

    monkeypatch.setattr(digest_module, "DIGESTS_DIR", tmp_path / "digests")

    with TestClient(app) as client:
        response = client.get("/digest/latest")

    assert response.status_code == 503


def test_list_and_fetch_digests(tmp_path, monkeypatch):
    import backend.app.routers.digest as digest_module

    digests_dir = tmp_path / "digests"
    digests_dir.mkdir()
    (digests_dir / "2026-08-31.md").write_text("Older digest", encoding="utf-8")
    (digests_dir / "2026-09-07.md").write_text("Newest digest", encoding="utf-8")
    monkeypatch.setattr(digest_module, "DIGESTS_DIR", digests_dir)

    with TestClient(app) as client:
        list_response = client.get("/digest")
        latest_response = client.get("/digest/latest")
        specific_response = client.get("/digest/2026-08-31")
        missing_response = client.get("/digest/2026-01-01")

    assert list_response.json() == ["2026-09-07", "2026-08-31"]
    assert latest_response.json() == {"run_date": "2026-09-07", "content": "Newest digest"}
    assert specific_response.json() == {"run_date": "2026-08-31", "content": "Older digest"}
    assert missing_response.status_code == 404
