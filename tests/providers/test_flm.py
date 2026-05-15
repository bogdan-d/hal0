"""Unit tests for FLMProvider.

Critical: TIER1 — the haloai FLM health probe accepted an empty
/v1/models and an unstuck-but-non-functional NPU as "ready". hal0
requires a real inference round-trip. These tests are the contract.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from hal0.providers.flm import (
    _HAL0_FLM_IMAGE,
    FLMInferError,
    FLMProvider,
)


@pytest.fixture
def provider() -> FLMProvider:
    return FLMProvider()


@pytest.fixture
def slot_cfg() -> dict[str, Any]:
    return {"port": 8086, "ctx_size": 65536, "_paths": {}}


@pytest.fixture
def model_info() -> dict[str, Any]:
    return {"flm_tag": "qwen3.5:0.8b", "path": "/var/lib/hal0/models/flm-qwen3.5"}


# ─── build_env ────────────────────────────────────────────────────────────────


def test_build_env_renames_to_hal0_namespace(
    provider: FLMProvider, slot_cfg: dict[str, Any], model_info: dict[str, Any]
) -> None:
    env = provider.build_env(slot_cfg, model_info)
    assert all(k.startswith("HAL0_") for k in env)
    assert env["HAL0_FLM_TAG"] == "qwen3.5:0.8b"
    assert env["HAL0_PORT"] == "8086"
    assert env["HAL0_FLM_CTX"] == "65536"


def test_build_env_multiplex_flags(provider: FLMProvider, model_info: dict[str, Any]) -> None:
    """FLM multiplexes ASR + embed on the same NPU via defaults flags."""
    slot_cfg = {
        "port": 8086,
        "defaults": {"load_asr": True, "load_embed": True},
        "_paths": {},
    }
    env = provider.build_env(slot_cfg, model_info)
    assert env["HAL0_FLM_LOAD_ASR"] == "1"
    assert env["HAL0_FLM_LOAD_EMBED"] == "1"


def test_build_env_defaults_to_no_multiplex(
    provider: FLMProvider, slot_cfg: dict[str, Any], model_info: dict[str, Any]
) -> None:
    env = provider.build_env(slot_cfg, model_info)
    assert env["HAL0_FLM_LOAD_ASR"] == "0"
    assert env["HAL0_FLM_LOAD_EMBED"] == "0"


# ─── start_cmd ────────────────────────────────────────────────────────────────


def test_start_cmd_uses_flm_serve(
    provider: FLMProvider, slot_cfg: dict[str, Any], model_info: dict[str, Any]
) -> None:
    env = provider.build_env(slot_cfg, model_info)
    cmd = provider.start_cmd(env)
    assert "serve" in cmd
    assert env["HAL0_FLM_TAG"] in cmd
    assert "--port" in cmd
    assert "--ctx-len" in cmd


# ─── image_ref / container_spec ───────────────────────────────────────────────


def test_image_ref_is_hal0_dev_flm(provider: FLMProvider) -> None:
    assert provider.image_ref({}) == _HAL0_FLM_IMAGE
    assert _HAL0_FLM_IMAGE.startswith("ghcr.io/hal0-dev/hal0-toolbox-flm")


def test_container_spec_passes_through_accel_device(
    provider: FLMProvider, slot_cfg: dict[str, Any], model_info: dict[str, Any]
) -> None:
    spec = provider.container_spec(slot_cfg, model_info)
    # /dev/accel is the XDNA2 NPU device node.
    assert "/dev/accel" in spec.devices
    assert spec.port == 8086


# ─── health (TIER1 inference round-trip) ──────────────────────────────────────


def _mock_response(
    *, status_code: int = 200, json_payload: Any = None, text: str = ""
) -> MagicMock:
    """httpx.Response stub with SYNC raise_for_status (matches the real API)."""
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
async def test_health_requires_inference_round_trip(provider: FLMProvider) -> None:
    """TIER1: health MUST exercise /v1/chat/completions, not just /v1/models.

    This is the explicit contract from PLAN.md §5 Tier 1 (haloai bug
    at lib/slots.py:899-920).
    """
    models_payload = {"data": [{"id": "qwen3.5:0.8b"}]}
    chat_payload = {"choices": [{"message": {"content": "x"}}]}

    sentinel_was_called = {"value": False}

    async def _fake_get(url: str) -> httpx.Response:
        assert url.endswith("/v1/models")
        return _mock_response(status_code=200, json_payload=models_payload)

    async def _fake_post(url: str, json: dict[str, Any]) -> httpx.Response:
        # TIER1: sentinel POST is required, with max_tokens=1.
        assert url.endswith("/v1/chat/completions")
        assert json["max_tokens"] == 1
        assert json["model"] == "qwen3.5:0.8b"
        sentinel_was_called["value"] = True
        return _mock_response(status_code=200, json_payload=chat_payload)

    with patch("hal0.providers.flm.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.get = _fake_get
        client.post = _fake_post
        result = await provider.health(8086)

    assert sentinel_was_called["value"], (
        "TIER1: FLM health probe MUST issue a /v1/chat/completions sentinel "
        "(haloai bug was reporting ready without it)."
    )
    assert result["ok"] is True
    assert result["status"] == "ready"
    assert result["model"] == "qwen3.5:0.8b"


@pytest.mark.asyncio
async def test_health_rejects_empty_models(provider: FLMProvider) -> None:
    """TIER1: empty /v1/models → not ready (the original haloai bug)."""

    async def _fake_get(url: str) -> httpx.Response:
        return _mock_response(status_code=200, json_payload={"data": []})

    async def _fake_post(url: str, json: dict[str, Any]) -> httpx.Response:
        raise AssertionError("must not POST when /v1/models is empty")

    with patch("hal0.providers.flm.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.get = _fake_get
        client.post = _fake_post
        result = await provider.health(8086)

    assert result["ok"] is False
    assert result["status"] == "models_endpoint_empty"


@pytest.mark.asyncio
async def test_health_rejects_models_ok_but_inference_failing(
    provider: FLMProvider,
) -> None:
    """TIER1: populated /v1/models but failing inference → not ready.

    This is the precise failure mode the haloai code missed.
    """
    models_payload = {"data": [{"id": "qwen3.5:0.8b"}]}

    async def _fake_get(url: str) -> httpx.Response:
        return _mock_response(status_code=200, json_payload=models_payload)

    async def _fake_post(url: str, json: dict[str, Any]) -> httpx.Response:
        # Inference fails — NPU loaded the model metadata but the runtime is stuck.
        return _mock_response(status_code=500, text="kernel not ready")

    with patch("hal0.providers.flm.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.get = _fake_get
        client.post = _fake_post
        result = await provider.health(8086)

    assert result["ok"] is False, (
        "TIER1: failed sentinel must drop ok=False even though /v1/models was good."
    )
    assert "sentinel_completion_http_500" in result["status"]


@pytest.mark.asyncio
async def test_health_rejects_response_with_no_choices(provider: FLMProvider) -> None:
    """TIER1: 200 but malformed (no choices) → not ready."""
    models_payload = {"data": [{"id": "qwen3.5:0.8b"}]}

    async def _fake_get(url: str) -> httpx.Response:
        return _mock_response(status_code=200, json_payload=models_payload)

    async def _fake_post(url: str, json: dict[str, Any]) -> httpx.Response:
        return _mock_response(status_code=200, json_payload={"id": "x"})  # no choices

    with patch("hal0.providers.flm.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.get = _fake_get
        client.post = _fake_post
        result = await provider.health(8086)

    assert result["ok"] is False
    assert result["status"] == "sentinel_completion_no_choices"


@pytest.mark.asyncio
async def test_health_transport_failure_surfaces_typed_status(
    provider: FLMProvider,
) -> None:
    async def _fake_get(url: str) -> httpx.Response:
        raise httpx.ConnectError("ECONNREFUSED")

    with patch("hal0.providers.flm.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.get = _fake_get
        result = await provider.health(8086)

    assert result["ok"] is False
    assert result["status"] == "http_error"


# ─── infer ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_infer_passthrough(provider: FLMProvider) -> None:
    expected = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}

    async def _fake_post(url: str, json: dict[str, Any]) -> httpx.Response:
        return _mock_response(status_code=200, json_payload=expected)

    with patch("hal0.providers.flm.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.post = _fake_post
        out = await provider.infer(8086, {"model": "x", "messages": []})

    assert out == expected


@pytest.mark.asyncio
async def test_infer_raises_typed_error_on_upstream_failure(
    provider: FLMProvider,
) -> None:
    async def _fake_post(url: str, json: dict[str, Any]) -> httpx.Response:
        return _mock_response(status_code=502)

    with patch("hal0.providers.flm.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.post = _fake_post
        with pytest.raises(FLMInferError) as exc:
            await provider.infer(8086, {})
    assert exc.value.code == "dispatch.upstream_failed"
