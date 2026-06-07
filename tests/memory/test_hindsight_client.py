"""HindsightRestClient REST-path tests against a MockTransport (P1)."""

from __future__ import annotations

import httpx
import pytest

from hal0.memory.hindsight_client import HindsightRestClient


@pytest.mark.asyncio
async def test_retain_recall_delete_hit_v1_bank_paths():
    seen: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/recall"):
            return httpx.Response(200, json={"results": []})
        if request.url.path.endswith("/memories"):
            return httpx.Response(
                200, json={"success": True, "bank_id": "shared", "items_count": 1}
            )
        return httpx.Response(200, json={"memory_units_deleted": 1})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9177") as http:
        client = HindsightRestClient(http_client=http, api_key="lemonade-local-noauth")
        await client.retain(bank_id="shared", content="x", document_id="d1")
        await client.recall(bank_id="shared", query="x")
        await client.delete_document(bank_id="shared", document_id="d1")

    assert ("POST", "/v1/default/banks/shared/memories") in seen
    assert ("POST", "/v1/default/banks/shared/memories/recall") in seen
    # Delete is the documented delete_document path.
    assert any(m == "DELETE" and "/documents/d1" in p for m, p in seen)
