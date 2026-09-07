from fastapi.testclient import TestClient

from backend.app.main import app


def test_cors_headers_present_on_get():
    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": "https://example.com"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_root_lists_endpoints():
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "/search" in response.json()["endpoints"]
