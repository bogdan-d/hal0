"""Unit tests for LlamaServerProvider.

Covers build_env, start_cmd, container_spec, image_ref, and health
(mocked httpx). Health tests explicitly exercise the Tier 1 fix:
non-empty /v1/models PLUS sentinel /v1/chat/completions both required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from hal0.providers.llama_server import (
    _HAL0_TOOLBOX_IMAGES,
    LlamaServerProvider,
    ProviderInferError,
)

# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def provider() -> LlamaServerProvider:
    return LlamaServerProvider()


@pytest.fixture
def slot_cfg() -> dict[str, Any]:
    return {
        "port": 8081,
        "backend": "vulkan",
        "ctx_size": 8192,
        "threads": 8,
        "parallel": 4,
        "_paths": {
            "models_base": "/var/lib/hal0/models",
            "llama_vulkan": "/opt/llama-vulkan/llama-server",
            "llama_vulkan_lib": "/opt/llama-vulkan/lib",
        },
    }


@pytest.fixture
def model_info() -> dict[str, Any]:
    return {
        "path": "/var/lib/hal0/models/qwen3-4b.gguf",
        "max_context": 8192,
        "gpu_layers": 33,
    }


# ─── build_env ────────────────────────────────────────────────────────────────


def test_build_env_returns_hal0_namespaced_vars(
    provider: LlamaServerProvider, slot_cfg: dict[str, Any], model_info: dict[str, Any]
) -> None:
    env = provider.build_env(slot_cfg, model_info)
    # Tier 1 / rebrand: vars are HAL0_*, not HALOAI_*.
    assert all(k.startswith("HAL0_") for k in env), env.keys()
    for key in ("HAL0_MODEL", "HAL0_PORT", "HAL0_CTX", "HAL0_BACKEND", "HAL0_BINARY"):
        assert key in env


def test_build_env_uses_slot_backend_over_model_preferred(
    provider: LlamaServerProvider, model_info: dict[str, Any]
) -> None:
    slot_cfg = {"port": 8081, "backend": "rocm", "_paths": {}}
    model_info["preferred_backend"] = "vulkan"
    env = provider.build_env(slot_cfg, model_info)
    assert env["HAL0_BACKEND"] == "rocm"
    # ROCm gets the rocm binary path by default.
    assert "rocm" in env["HAL0_BINARY"]


def test_build_env_clamps_ctx_to_model_max(
    provider: LlamaServerProvider, slot_cfg: dict[str, Any], model_info: dict[str, Any]
) -> None:
    slot_cfg["ctx_size"] = 999999
    model_info["max_context"] = 4096
    env = provider.build_env(slot_cfg, model_info)
    assert env["HAL0_CTX"] == "4096"


def test_build_env_handles_legacy_nested_keys(
    provider: LlamaServerProvider, model_info: dict[str, Any]
) -> None:
    """Legacy slot TOML with nested [slot]/[defaults] still loads."""
    slot_cfg = {
        "slot": {"port": 9090, "backend": "vulkan"},
        "defaults": {"context_size": 2048, "threads": 6},
        "_paths": {},
    }
    env = provider.build_env(slot_cfg, model_info)
    assert env["HAL0_PORT"] == "9090"
    assert env["HAL0_BACKEND"] == "vulkan"
    assert env["HAL0_THREADS"] == "6"


def test_build_env_emits_mmproj_for_vision_models(
    provider: LlamaServerProvider, slot_cfg: dict[str, Any], model_info: dict[str, Any]
) -> None:
    model_info["mmproj"] = "/var/lib/hal0/models/qwen3-vl-mmproj.gguf"
    env = provider.build_env(slot_cfg, model_info)
    assert "--mmproj" in env["HAL0_EXTRA_ARGS"]
    assert model_info["mmproj"] in env["HAL0_EXTRA_ARGS"]


def test_build_env_emits_embedding_flag_when_model_is_embedding(
    provider: LlamaServerProvider, slot_cfg: dict[str, Any], model_info: dict[str, Any]
) -> None:
    model_info["embedding"] = True
    env = provider.build_env(slot_cfg, model_info)
    assert "--embedding" in env["HAL0_EXTRA_ARGS"]


# ─── start_cmd ────────────────────────────────────────────────────────────────


def test_start_cmd_includes_required_flags(
    provider: LlamaServerProvider, slot_cfg: dict[str, Any], model_info: dict[str, Any]
) -> None:
    env = provider.build_env(slot_cfg, model_info)
    cmd = provider.start_cmd(env)
    # First element is the binary, then flag/value pairs.
    assert cmd[0] == env["HAL0_BINARY"]
    assert "--model" in cmd
    assert "--port" in cmd
    assert "--ctx-size" in cmd
    assert "--threads" in cmd
    assert "-ngl" in cmd
    assert "--host" in cmd
    assert "0.0.0.0" in cmd


def test_start_cmd_appends_extra_args_when_present(
    provider: LlamaServerProvider, slot_cfg: dict[str, Any], model_info: dict[str, Any]
) -> None:
    model_info["mmproj"] = "/x/mmproj.gguf"
    env = provider.build_env(slot_cfg, model_info)
    cmd = provider.start_cmd(env)
    assert "--mmproj" in cmd
    assert "/x/mmproj.gguf" in cmd


# ─── image_ref ────────────────────────────────────────────────────────────────


def test_image_ref_default_vulkan(provider: LlamaServerProvider) -> None:
    assert provider.image_ref({}) == _HAL0_TOOLBOX_IMAGES["vulkan"]


def test_image_ref_rocm(provider: LlamaServerProvider) -> None:
    assert provider.image_ref({"backend": "rocm"}) == _HAL0_TOOLBOX_IMAGES["rocm"]


def test_image_ref_cpu_falls_through_to_vulkan(provider: LlamaServerProvider) -> None:
    assert provider.image_ref({"backend": "cpu"}) == _HAL0_TOOLBOX_IMAGES["vulkan"]


def test_image_ref_rejects_unknown_backend(provider: LlamaServerProvider) -> None:
    with pytest.raises(ValueError, match="Unknown llama-server backend"):
        provider.image_ref({"backend": "tpu"})


def test_image_ref_uses_hal0_dev_namespace(provider: LlamaServerProvider) -> None:
    """PLAN.md §12: toolbox images live under ghcr.io/hal0-dev/."""
    for backend in ("vulkan", "rocm"):
        ref = provider.image_ref({"backend": backend})
        assert ref.startswith("ghcr.io/hal0-dev/hal0-toolbox-"), ref


# ─── container_spec ───────────────────────────────────────────────────────────


def test_container_spec_returns_frozen_dataclass(
    provider: LlamaServerProvider, slot_cfg: dict[str, Any], model_info: dict[str, Any]
) -> None:
    spec = provider.container_spec(slot_cfg, model_info)
    assert spec.image == _HAL0_TOOLBOX_IMAGES["vulkan"]
    assert spec.port == 8081
    assert spec.network_mode == "host"
    # /dev/kfd + /dev/dri for both Vulkan and ROCm (cheap, no-op on Vulkan).
    assert "/dev/kfd" in spec.devices
    assert "/dev/dri" in spec.devices
    # The toolbox image ENTRYPOINT=llama-server, so command[0] is a flag.
    assert spec.command[0].startswith("--")


def test_container_spec_mounts_models_base(
    provider: LlamaServerProvider, slot_cfg: dict[str, Any], model_info: dict[str, Any]
) -> None:
    spec = provider.container_spec(slot_cfg, model_info)
    host_paths = [m[0] for m in spec.mounts]
    assert "/var/lib/hal0/models" in host_paths


# ─── health ───────────────────────────────────────────────────────────────────


def _mock_async_response(
    *, status_code: int = 200, json_payload: Any = None, text: str = ""
) -> MagicMock:
    """Construct a MagicMock that mimics httpx.Response.

    NOTE: httpx.Response.raise_for_status() is SYNC, not async — using
    AsyncMock(spec=httpx.Response) wraps it as a coroutine which never
    raises. MagicMock with sync side_effect is the right shape.
    """
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
async def test_health_ok_requires_both_models_and_sentinel(
    provider: LlamaServerProvider,
) -> None:
    """TIER1: /v1/models non-empty AND /v1/chat/completions both required."""
    models_payload = {"data": [{"id": "qwen3-4b"}]}
    chat_payload = {"choices": [{"message": {"content": "x"}}]}

    async def _fake_get(url: str) -> httpx.Response:
        assert url.endswith("/v1/models")
        return _mock_async_response(status_code=200, json_payload=models_payload)

    async def _fake_post(url: str, json: dict[str, Any]) -> httpx.Response:
        assert url.endswith("/v1/chat/completions")
        # TIER1: assert the sentinel body shape.
        assert json["max_tokens"] == 1
        assert json["model"] == "qwen3-4b"
        return _mock_async_response(status_code=200, json_payload=chat_payload)

    with patch("hal0.providers.llama_server.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.get = _fake_get
        client.post = _fake_post
        result = await provider.health(8081)

    assert result["ok"] is True
    assert result["status"] == "ready"
    assert result["model"] == "qwen3-4b"


@pytest.mark.asyncio
async def test_health_empty_models_endpoint_is_not_ready(
    provider: LlamaServerProvider,
) -> None:
    """TIER1: empty /v1/models must report not-ready (was the haloai bug)."""

    async def _fake_get(url: str) -> httpx.Response:
        return _mock_async_response(status_code=200, json_payload={"data": []})

    async def _fake_post(url: str, json: dict[str, Any]) -> httpx.Response:
        raise AssertionError("must not call /v1/chat/completions when models empty")

    with patch("hal0.providers.llama_server.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.get = _fake_get
        client.post = _fake_post
        result = await provider.health(8081)

    assert result["ok"] is False
    assert result["status"] == "models_endpoint_empty"


@pytest.mark.asyncio
async def test_health_failed_sentinel_completion_is_not_ready(
    provider: LlamaServerProvider,
) -> None:
    """TIER1: sentinel completion failing → not-ready."""
    models_payload = {"data": [{"id": "qwen3-4b"}]}

    async def _fake_get(url: str) -> httpx.Response:
        return _mock_async_response(status_code=200, json_payload=models_payload)

    async def _fake_post(url: str, json: dict[str, Any]) -> httpx.Response:
        return _mock_async_response(status_code=500, text="model not loaded")

    with patch("hal0.providers.llama_server.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.get = _fake_get
        client.post = _fake_post
        result = await provider.health(8081)

    assert result["ok"] is False
    assert "sentinel_completion_http_500" in result["status"]


@pytest.mark.asyncio
async def test_health_transport_error_surfaces_typed_status(
    provider: LlamaServerProvider,
) -> None:
    async def _fake_get(url: str) -> httpx.Response:
        raise httpx.ConnectError("ECONNREFUSED")

    with patch("hal0.providers.llama_server.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.get = _fake_get
        result = await provider.health(8081)

    assert result["ok"] is False
    assert result["status"] == "http_error"
    assert "ECONNREFUSED" in result["detail"]


# ─── infer ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_infer_returns_upstream_json(provider: LlamaServerProvider) -> None:
    expected = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}

    async def _fake_post(url: str, json: dict[str, Any]) -> httpx.Response:
        return _mock_async_response(status_code=200, json_payload=expected)

    with patch("hal0.providers.llama_server.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.post = _fake_post
        out = await provider.infer(8081, {"model": "x", "messages": []})

    assert out == expected


@pytest.mark.asyncio
async def test_infer_raises_typed_error_on_5xx(provider: LlamaServerProvider) -> None:
    async def _fake_post(url: str, json: dict[str, Any]) -> httpx.Response:
        return _mock_async_response(status_code=503)

    with patch("hal0.providers.llama_server.httpx.AsyncClient") as MockClient:
        client = MockClient.return_value.__aenter__.return_value
        client.post = _fake_post
        with pytest.raises(ProviderInferError) as exc:
            await provider.infer(8081, {})
    assert exc.value.code == "dispatch.upstream_failed"


# ─── parse_metrics ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parse_metrics_whitelists_counters(
    provider: LlamaServerProvider,
) -> None:
    raw = (
        "# HELP llamacpp:n_decode_total decoded tokens\n"
        "# TYPE llamacpp:n_decode_total counter\n"
        "llamacpp:n_decode_total 1234\n"
        "llamacpp:kv_cache_usage_ratio 0.42\n"
        "llamacpp:unknown_metric 7\n"
    )
    out = await provider.parse_metrics(raw)
    assert out["decode_total"] == 1234
    assert out["kv_cache_usage"] == pytest.approx(0.42)
    assert "unknown_metric" not in out
