import pytest
from fastapi.testclient import TestClient

from backend.app.main import DEFAULT_ORIGINS, app


def test_a_named_origin_is_allowed():
    """The frontend fetches /search from the browser, so an origin missing from
    the allowlist is a search box that silently fails rather than a hardening
    detail. This asserts the production origin is in it."""
    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": DEFAULT_ORIGINS[0]})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == DEFAULT_ORIGINS[0]


def test_vercel_preview_origins_are_allowed():
    """Vercel builds a preview per branch at a URL nobody can list in advance.
    Search is fetched from the browser, so without this a preview's search box
    fails while production's works - the worst way for it to fail, since
    previews are where changes get looked at."""
    preview_origin = "https://weebblade-git-feature-branch-ranjith-13.vercel.app"
    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": preview_origin})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == preview_origin


@pytest.mark.parametrize("origin", [
    "https://weebblade-malware.vercel.app",
    "https://weebblade-.vercel.app",
    "https://weebblade-anything-at-all.vercel.app",
])
def test_a_vercel_project_anyone_could_register_is_not_allowed(origin):
    """The first version of the preview rule was ^https://weebblade(-.*)?\\.vercel\\.app$,
    which admitted every one of these - verified against the live service, which
    returned access-control-allow-origin for weebblade-malware.vercel.app.

    vercel.app is a shared suffix and project names are free-form, so no pattern
    written here is squat-proof and this test does not pretend otherwise. It
    pins the rule to the -git- preview shape, which is the difference between a
    surface anyone can reach for and one they have to aim at."""
    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": origin})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_an_unnamed_origin_gets_no_cors_header():
    """It was "*" while there was no frontend origin to name. The request still
    succeeds - this is a public read-only API and curl was never subject to CORS
    - but another site's page cannot use this container as its backend."""
    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": "https://example.com"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_health_says_what_it_is_serving_and_how():
    """Two questions that have no other answer once the API fetches its own
    warehouse onto a box with no disk and 512 MB.

    Which release: "is the live site stale?" would otherwise mean counting
    titles by hand. Which embedding backend: a fallback from ONNX to torch
    answers searches perfectly well at twice the memory, right up until the box
    kills it for that, and the log line saying so was being dropped entirely
    before logging was configured."""
    with TestClient(app) as client:
        body = client.get("/health").json()

    assert body["status"] == "ok"
    assert "warehouse" in body and "warehouse_origin" in body
    assert body["search_backend"] in ("onnx", "torch", None)


def test_root_lists_endpoints():
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "/search" in response.json()["endpoints"]
