"""Wiring tests for ``POST /v1/images/generations`` + the image cache.

The provider's ``infer()`` is mocked so we don't need a live ComfyUI;
this exercises:

  * dispatcher routing (image-gen path lands on the ``img`` slot legacy
    fallback when no registry binding exists).
  * curated-model gating (random model id 404s).
  * URL response_format → cached PNG + ``/api/images/cache/...`` URL.
  * b64_json response_format → inline base64 PNG.
  * GET /api/images/cache/{name}.png serves the cached bytes.
  * Cache-miss + path-traversal attempt 404 cleanly.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from hal0.upstreams.registry import Upstream


def _seed_img_upstream(client: TestClient, port: int = 8186) -> None:
    """Register a fake `img` slot upstream so the dispatcher resolves to it."""
    upstreams = client.app.state.upstreams
    upstreams.upsert(
        Upstream(
            name="img",
            kind="slot",
            url=f"http://127.0.0.1:{port}/v1",
            slot_name="img",
            auth_style="none",
        )
    )


def test_v1_images_no_upstream_returns_envelope(client: TestClient) -> None:
    """No img slot configured → dispatch errors out with a 404 envelope."""
    r = client.post(
        "/v1/images/generations",
        json={"model": "sdxl-turbo", "prompt": "a cat"},
    )
    # NoRouteFound or LegacyResolutionFailed both surface as dispatch.* envelopes.
    assert r.status_code in (404, 502, 503)
    body = r.json()
    assert "error" in body
    assert body["error"]["code"].startswith(("dispatch.", "image."))


def test_v1_images_empty_prompt_422(client: TestClient) -> None:
    _seed_img_upstream(client)
    r = client.post(
        "/v1/images/generations",
        json={"model": "sdxl-turbo", "prompt": ""},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "image.prompt_required"


def test_v1_images_unknown_model_404(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_img_upstream(client)
    r = client.post(
        "/v1/images/generations",
        json={"model": "not-a-real-image-model", "prompt": "anything"},
    )
    # Could route to a model_not_curated 404 or the dispatcher's no_route 404.
    assert r.status_code == 404
    body = r.json()
    # Both shapes pass the test — what matters is a typed envelope.
    assert body["error"]["code"] in ("image.model_not_curated", "dispatch.no_route")


def test_v1_images_url_response_format_writes_cache(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_hal0_home: str,
) -> None:
    _seed_img_upstream(client)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"y" * 256
    mock_infer = AsyncMock(
        return_value={
            "images": [
                {
                    "png": fake_png,
                    "filename": "hal0-test_00001_.png",
                    "subfolder": "",
                    "type": "output",
                }
            ],
            "meta": {"template": "sdxl_turbo_simple", "seed": 1, "width": 1024, "height": 1024},
            "prompt_id": "abc123",
        }
    )

    # Patch the provider singleton's infer method.
    from hal0.providers import get_provider

    provider = get_provider("comfyui")
    monkeypatch.setattr(provider, "infer", mock_infer)

    r = client.post(
        "/v1/images/generations",
        json={
            "model": "sdxl-turbo",
            "prompt": "a cyberpunk cat",
            "size": "1024x1024",
            "n": 1,
            "response_format": "url",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]
    assert "url" in body["data"][0]
    url = body["data"][0]["url"]
    assert url.startswith("/api/images/cache/")
    # The cached PNG should be retrievable via the image-cache route.
    cache_get = client.get(url)
    assert cache_get.status_code == 200
    assert cache_get.headers["content-type"] == "image/png"
    assert cache_get.content == fake_png


def test_v1_images_b64_json_returns_inline_base64(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_hal0_home: str,
) -> None:
    _seed_img_upstream(client)

    import base64

    fake_png = b"\x89PNG\r\n\x1a\n" + b"z" * 128
    expected_b64 = base64.b64encode(fake_png).decode("ascii")

    mock_infer = AsyncMock(
        return_value={
            "images": [
                {
                    "png": fake_png,
                    "filename": "hal0-test.png",
                    "subfolder": "",
                    "type": "output",
                }
            ],
            "meta": {},
            "prompt_id": "xyz",
        }
    )
    from hal0.providers import get_provider

    monkeypatch.setattr(get_provider("comfyui"), "infer", mock_infer)

    r = client.post(
        "/v1/images/generations",
        json={
            "model": "sdxl-turbo",
            "prompt": "a unicorn",
            "response_format": "b64_json",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["data"][0]["b64_json"] == expected_b64


def test_v1_images_provider_error_surfaces(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_img_upstream(client)

    from hal0.providers import get_provider
    from hal0.providers.comfyui import ComfyUIInferError

    async def _raises(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ComfyUIInferError(
            "workflow execution failed",
            details={"prompt_id": "abc", "messages": []},
        )

    monkeypatch.setattr(get_provider("comfyui"), "infer", _raises)

    r = client.post(
        "/v1/images/generations",
        json={"model": "sdxl-turbo", "prompt": "x"},
    )
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "dispatch.upstream_failed"


# ─── image cache route ────────────────────────────────────────────────────────


def test_images_cache_miss_returns_404(client: TestClient, tmp_hal0_home: str) -> None:
    r = client.get("/api/images/cache/deadbeef0000.png")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "image.cache_miss"


def test_images_cache_blocks_path_traversal(client: TestClient, tmp_hal0_home: str) -> None:
    """`..` shouldn't slip past the safe-name regex even via URL encoding."""
    # FastAPI URL-decodes path params; we pass a name that, after decoding,
    # still has characters outside the uuid-hex regex so read_png() returns
    # None and the route surfaces a clean 404.
    r = client.get("/api/images/cache/..%2F..%2Fetc%2Fpasswd")
    # Some routers will 404 at the route layer; either way we never want
    # a 200 + traversed file contents.
    assert r.status_code in (400, 404)
