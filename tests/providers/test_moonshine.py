"""Unit tests for MoonshineProvider.

Covers build_env / start_cmd / image_ref / container_spec / health
(mocked httpx). The unary infer() path is exercised too — streaming WS
is not the provider's concern (handled by the Dispatcher).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from hal0.providers.moonshine import (
    _HAL0_MOONSHINE_IMAGE,
    MoonshineInferError,
    MoonshineProvider,
)


@pytest.fixture
def provider() -> MoonshineProvider:
    return MoonshineProvider()


@pytest.fixture
def slot_cfg() -> dict[str, Any]:
    return {"port": 8089, "model_arch": "small_streaming", "_paths": {}}


@pytest.fixture
def model_info() -> dict[str, Any]:
    return {"path": "/var/lib/hal0/models/moonshine-small-streaming-en"}


# ─── build_env / start_cmd ────────────────────────────────────────────────────


def test_build_env_uses_hal0_namespace(
    provider: MoonshineProvider,
    slot_cfg: dict[str, Any],
    model_info: dict[str, Any],
) -> None:
    env = provider.build_env(slot_cfg, model_info)
    assert env["HAL0_PORT"] == "8089"
    assert env["HAL0_MOONSHINE_MODEL_ARCH"] == "small_streaming"
    assert env["HAL0_MOONSHINE_MODEL_PATH"] == model_info["path"]


def test_build_env_slot_arch_overrides_model_arch(
    provider: MoonshineProvider, model_info: dict[str, Any]
) -> None:
    slot_cfg = {"port": 8089, "model_arch": "tiny_streaming", "_paths": {}}
    model_info["model_arch"] = "small_streaming"
    env = provider.build_env(slot_cfg, model_info)
    assert env["HAL0_MOONSHINE_MODEL_ARCH"] == "tiny_streaming"


def test_build_env_falls_back_to_small_streaming(
    provider: MoonshineProvider, model_info: dict[str, Any]
) -> None:
    env = provider.build_env({"port": 8089, "_paths": {}}, model_info)
    assert env["HAL0_MOONSHINE_MODEL_ARCH"] == "small_streaming"


def test_start_cmd_emits_argparse_flags(
    provider: MoonshineProvider,
    slot_cfg: dict[str, Any],
    model_info: dict[str, Any],
) -> None:
    env = provider.build_env(slot_cfg, model_info)
    cmd = provider.start_cmd(env)
    # Mirror argparse in haloai lib/voice/moonshine_server.py:main().
    assert "--model_path" in cmd
    assert "--model_arch" in cmd
    assert "--port" in cmd
    assert "--host" in cmd
    assert env["HAL0_MOONSHINE_MODEL_PATH"] in cmd
    assert env["HAL0_MOONSHINE_MODEL_ARCH"] in cmd


# ─── image_ref / container_spec ───────────────────────────────────────────────


def test_image_ref_is_hal0ai_moonshine(provider: MoonshineProvider) -> None:
    assert provider.image_ref({}) == _HAL0_MOONSHINE_IMAGE
    assert _HAL0_MOONSHINE_IMAGE.startswith("ghcr.io/hal0ai/hal0-toolbox-moonshine")


def test_container_spec_command_args_only(
    provider: MoonshineProvider,
    slot_cfg: dict[str, Any],
    model_info: dict[str, Any],
) -> None:
    spec = provider.container_spec(slot_cfg, model_info)
    # The toolbox image ENTRYPOINT runs the FastAPI app; command[] is args only.
    assert spec.command[0].startswith("--")
    assert spec.port == 8089


def test_container_spec_mounts_models_base(
    provider: MoonshineProvider,
    slot_cfg: dict[str, Any],
    model_info: dict[str, Any],
) -> None:
    spec = provider.container_spec(slot_cfg, model_info)
    host_paths = [m[0] for m in spec.mounts]
    assert "/var/lib/hal0/models" in host_paths


# ─── health ───────────────────────────────────────────────────────────────────


def _mock_response(
    *, status_code: int = 200, json_payload: Any = None, text: str = ""
) -> MagicMock:
    """httpx.Response stub with SYNC raise_for_status."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = lambda: json_payload
    resp.text = text
    if status_code < 400:
        resp.raise_for_status = MagicMock(return_value=None)
    else:
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                f"http {status_code}", request=MagicMock(), response=resp
            )
        )
    return resp


@pytest.mark.asyncio
async def test_health_ok_when_model_loaded(provider: MoonshineProvider) -> None:
    payload = {
        "status": "ok",
        "model_loaded": True,
        "model_id": "moonshine-small-streaming-en",
        "model_arch": "SMALL_STREAMING",
    }

    async def _fake_get(url: str) -> httpx.Response:
        return _mock_response(status_code=200, json_payload=payload)

    with patch("hal0.providers.moonshine.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.get = _fake_get
        result = await provider.health(8089)

    assert result["ok"] is True
    assert result["model"] == "moonshine-small-streaming-en"
    assert result["model_arch"] == "SMALL_STREAMING"


@pytest.mark.asyncio
async def test_health_not_ok_when_model_not_loaded(provider: MoonshineProvider) -> None:
    payload = {"status": "ok", "model_loaded": False}

    async def _fake_get(url: str) -> httpx.Response:
        return _mock_response(status_code=200, json_payload=payload)

    with patch("hal0.providers.moonshine.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.get = _fake_get
        result = await provider.health(8089)

    assert result["ok"] is False
    assert result["status"] == "model_not_loaded"


@pytest.mark.asyncio
async def test_health_handles_5xx(provider: MoonshineProvider) -> None:
    async def _fake_get(url: str) -> httpx.Response:
        return _mock_response(status_code=503, text="overloaded")

    with patch("hal0.providers.moonshine.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.get = _fake_get
        result = await provider.health(8089)

    assert result["ok"] is False
    assert "503" in result["status"]


@pytest.mark.asyncio
async def test_health_transport_error(provider: MoonshineProvider) -> None:
    async def _fake_get(url: str) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with patch("hal0.providers.moonshine.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.get = _fake_get
        result = await provider.health(8089)

    assert result["ok"] is False
    assert result["status"] == "http_error"


# ─── infer ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_infer_posts_multipart_with_file(provider: MoonshineProvider) -> None:
    """infer() adapts dict body into multipart form upload."""
    expected = {"text": "hello world"}
    captured: dict[str, Any] = {}

    async def _fake_post(url: str, data: dict[str, Any], files: dict[str, Any]) -> httpx.Response:
        captured["url"] = url
        captured["data"] = data
        captured["files"] = files
        return _mock_response(status_code=200, json_payload=expected)

    with patch("hal0.providers.moonshine.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.post = _fake_post
        out = await provider.infer(
            8089,
            {
                "file": b"RIFF....",
                "model": "moonshine-small-streaming-en",
                "response_format": "json",
            },
        )

    assert out == expected
    assert captured["url"].endswith("/v1/audio/transcriptions")
    assert "file" in captured["files"]
    # Non-file fields end up in data form fields.
    assert "model" in captured["data"]


@pytest.mark.asyncio
async def test_infer_requires_file_field(provider: MoonshineProvider) -> None:
    with pytest.raises(MoonshineInferError):
        await provider.infer(8089, {"model": "x"})


@pytest.mark.asyncio
async def test_infer_raises_on_upstream_error(provider: MoonshineProvider) -> None:
    async def _fake_post(url: str, data: dict[str, Any], files: dict[str, Any]) -> httpx.Response:
        return _mock_response(status_code=500, text="boom")

    with patch("hal0.providers.moonshine.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.post = _fake_post
        with pytest.raises(MoonshineInferError):
            await provider.infer(8089, {"file": b"\x00"})
