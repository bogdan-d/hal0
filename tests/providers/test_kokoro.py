"""Unit tests for KokoroProvider.

Kokoro is hal0-native (no haloai reference); these tests are the
contract for the OpenAI-compat TTS endpoint shape.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from hal0.providers.kokoro import (
    _HAL0_KOKORO_IMAGE,
    KokoroInferError,
    KokoroProvider,
)


@pytest.fixture
def provider() -> KokoroProvider:
    return KokoroProvider()


@pytest.fixture
def slot_cfg() -> dict[str, Any]:
    return {"port": 8090, "default_voice": "af_bella", "_paths": {}}


@pytest.fixture
def model_info() -> dict[str, Any]:
    return {"path": "/var/lib/hal0/models/kokoro-82m"}


# ─── build_env / start_cmd ────────────────────────────────────────────────────


def test_build_env_hal0_namespace(
    provider: KokoroProvider,
    slot_cfg: dict[str, Any],
    model_info: dict[str, Any],
) -> None:
    env = provider.build_env(slot_cfg, model_info)
    assert env["HAL0_PORT"] == "8090"
    assert env["HAL0_KOKORO_DEFAULT_VOICE"] == "af_bella"
    assert env["HAL0_KOKORO_MODEL_PATH"] == model_info["path"]
    assert env["HAL0_KOKORO_BACKEND"] == "cpu"


def test_build_env_backend_override(provider: KokoroProvider, model_info: dict[str, Any]) -> None:
    slot_cfg = {"port": 8090, "backend": "vulkan", "_paths": {}}
    env = provider.build_env(slot_cfg, model_info)
    assert env["HAL0_KOKORO_BACKEND"] == "vulkan"


def test_start_cmd_emits_required_flags(
    provider: KokoroProvider,
    slot_cfg: dict[str, Any],
    model_info: dict[str, Any],
) -> None:
    env = provider.build_env(slot_cfg, model_info)
    cmd = provider.start_cmd(env)
    assert "--model_path" in cmd
    assert "--default_voice" in cmd
    assert "--port" in cmd
    assert "--host" in cmd


# ─── image_ref / container_spec ───────────────────────────────────────────────


def test_image_ref_is_hal0ai_kokoro(provider: KokoroProvider) -> None:
    assert provider.image_ref({}) == _HAL0_KOKORO_IMAGE
    assert _HAL0_KOKORO_IMAGE.startswith("ghcr.io/hal0ai/hal0-toolbox-kokoro")


def test_container_spec_cpu_no_devices(
    provider: KokoroProvider,
    slot_cfg: dict[str, Any],
    model_info: dict[str, Any],
) -> None:
    spec = provider.container_spec(slot_cfg, model_info)
    assert spec.port == 8090
    # CPU runtime: no device passthrough required.
    assert spec.devices == []
    assert spec.group_add == []


def test_container_spec_vulkan_passes_dri(
    provider: KokoroProvider, model_info: dict[str, Any]
) -> None:
    slot_cfg = {"port": 8090, "backend": "vulkan", "_paths": {}}
    spec = provider.container_spec(slot_cfg, model_info)
    assert "/dev/dri" in spec.devices
    # group_add is numeric GIDs (resolved from host) so toolbox image's
    # stock /etc/group doesn't matter — should always be at least one
    # integer-as-string when vulkan backend is selected.
    assert spec.group_add
    assert all(g.isdigit() for g in spec.group_add)


# ─── health ───────────────────────────────────────────────────────────────────


def _mock_response(
    *, status_code: int = 200, json_payload: Any = None, text: str = "", content: bytes = b""
) -> MagicMock:
    """httpx.Response stub with SYNC raise_for_status."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = lambda: json_payload
    resp.text = text
    resp.content = content
    resp.headers = {"content-type": "audio/mpeg"}
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
async def test_health_ok_requires_health_and_models(provider: KokoroProvider) -> None:
    """Health probe needs /health=ok AND /v1/models populated."""
    health_payload = {"status": "ok"}
    models_payload = {"data": [{"id": "kokoro"}]}

    async def _fake_get(url: str) -> httpx.Response:
        if url.endswith("/health"):
            return _mock_response(status_code=200, json_payload=health_payload)
        if url.endswith("/v1/models"):
            return _mock_response(status_code=200, json_payload=models_payload)
        raise AssertionError(f"unexpected GET {url}")

    with patch("hal0.providers.kokoro.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.get = _fake_get
        result = await provider.health(8090)

    assert result["ok"] is True
    assert result["model"] == "kokoro"


@pytest.mark.asyncio
async def test_health_empty_models_endpoint(provider: KokoroProvider) -> None:
    health_payload = {"status": "ok"}

    async def _fake_get(url: str) -> httpx.Response:
        if url.endswith("/health"):
            return _mock_response(status_code=200, json_payload=health_payload)
        return _mock_response(status_code=200, json_payload={"data": []})

    with patch("hal0.providers.kokoro.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.get = _fake_get
        result = await provider.health(8090)

    assert result["ok"] is False
    assert result["status"] == "models_endpoint_empty"


@pytest.mark.asyncio
async def test_health_health_endpoint_5xx(provider: KokoroProvider) -> None:
    async def _fake_get(url: str) -> httpx.Response:
        return _mock_response(status_code=502, text="bad gateway")

    with patch("hal0.providers.kokoro.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.get = _fake_get
        result = await provider.health(8090)

    assert result["ok"] is False
    assert "502" in result["status"]


@pytest.mark.asyncio
async def test_health_handles_no_json_health_body(provider: KokoroProvider) -> None:
    """Some Kokoro builds return 200 without JSON body — accept it."""
    models_payload = {"data": [{"id": "kokoro"}]}

    def _no_json() -> dict[str, Any]:
        raise ValueError("not json")

    async def _fake_get(url: str) -> httpx.Response:
        if url.endswith("/health"):
            r = MagicMock(spec=httpx.Response)
            r.status_code = 200
            r.json = _no_json
            r.text = "ok"
            r.raise_for_status = MagicMock(return_value=None)
            return r
        return _mock_response(status_code=200, json_payload=models_payload)

    with patch("hal0.providers.kokoro.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.get = _fake_get
        result = await provider.health(8090)

    assert result["ok"] is True


# ─── infer ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_infer_returns_audio_bytes_envelope(provider: KokoroProvider) -> None:
    audio_bytes = b"\xff\xfb\x90\x00fakeMP3"

    async def _fake_post(url: str, json: dict[str, Any]) -> httpx.Response:
        resp = _mock_response(status_code=200, content=audio_bytes)
        resp.headers = {"content-type": "audio/mpeg"}
        return resp

    with patch("hal0.providers.kokoro.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.post = _fake_post
        out = await provider.infer(
            8090,
            {
                "model": "kokoro",
                "input": "hello",
                "voice": "af_bella",
                "response_format": "mp3",
            },
        )

    assert out["audio"] == audio_bytes
    assert out["content_type"] == "audio/mpeg"
    assert out["voice"] == "af_bella"
    assert out["format"] == "mp3"


@pytest.mark.asyncio
async def test_infer_raises_typed_error_on_5xx(provider: KokoroProvider) -> None:
    async def _fake_post(url: str, json: dict[str, Any]) -> httpx.Response:
        return _mock_response(status_code=500, text="oom")

    with patch("hal0.providers.kokoro.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.post = _fake_post
        with pytest.raises(KokoroInferError) as exc:
            await provider.infer(8090, {"input": "x"})
    assert exc.value.code == "dispatch.upstream_failed"
