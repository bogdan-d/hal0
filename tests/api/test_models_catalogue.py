"""Route test for /api/models/catalogue.

Asserts the shape the UI's Models view depends on: split into
pullable (CuratedModel) + upstream (HaloaiModel), with counts that
add up.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_catalogue_returns_split_shape(client: TestClient) -> None:
    resp = client.get("/api/models/catalogue")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert set(body.keys()) >= {"pullable", "upstream", "counts"}
    assert isinstance(body["pullable"], list)
    assert isinstance(body["upstream"], list)

    counts = body["counts"]
    assert set(counts.keys()) >= {"pullable", "upstream", "total"}
    assert counts["pullable"] == len(body["pullable"])
    assert counts["upstream"] == len(body["upstream"])
    assert counts["total"] == counts["pullable"] + counts["upstream"]
    assert counts["total"] > 0


def test_catalogue_pullable_has_hf_coordinates(client: TestClient) -> None:
    body = client.get("/api/models/catalogue").json()
    assert body["pullable"], "expected at least one pullable curated entry"
    sample = body["pullable"][0]
    # CuratedModel guarantees these fields are present and non-empty.
    assert sample["hf_repo"]
    assert sample["hf_file"]
    assert sample["id"]
    assert sample["display_name"]


def test_catalogue_upstream_has_owned_by(client: TestClient) -> None:
    body = client.get("/api/models/catalogue").json()
    assert body["upstream"], "expected at least one upstream-routed entry"
    sample = body["upstream"][0]
    assert sample["owned_by"]
    assert sample["id"]
    assert "backend" in sample
    assert "capability" in sample
