"""OpenAI-compatible endpoints (mounted under /v1)."""

from __future__ import annotations

from fastapi import APIRouter

from hal0.api.middleware.error_codes import Hal0Error

router = APIRouter()


class NotImplementedYet(Hal0Error):
    code = "system.not_implemented"
    status = 501


@router.get("/models")
async def list_models() -> dict[str, object]:
    raise NotImplementedYet("/v1/models: Phase 1")


@router.get("/models/{model_id}")
async def get_model(model_id: str) -> dict[str, object]:
    raise NotImplementedYet(f"/v1/models/{model_id}: Phase 1")


@router.post("/chat/completions")
async def chat_completions() -> dict[str, object]:
    raise NotImplementedYet("/v1/chat/completions: Phase 1")


@router.post("/completions")
async def completions() -> dict[str, object]:
    raise NotImplementedYet("/v1/completions: Phase 1")


@router.post("/embeddings")
async def embeddings() -> dict[str, object]:
    raise NotImplementedYet("/v1/embeddings: Phase 1")


@router.post("/rerankings")
async def rerankings() -> dict[str, object]:
    raise NotImplementedYet("/v1/rerankings: Phase 1")


@router.post("/audio/transcriptions")
async def audio_transcriptions() -> dict[str, object]:
    raise NotImplementedYet("/v1/audio/transcriptions: Phase 1")


@router.post("/audio/speech")
async def audio_speech() -> dict[str, object]:
    raise NotImplementedYet("/v1/audio/speech: Phase 1")
