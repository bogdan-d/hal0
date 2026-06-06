"""HindsightProvider unit tests — bank mapping + fan-out (P1)."""

from __future__ import annotations

import pytest
from hal0.memory.hindsight_provider import HindsightProvider, namespace_to_bank


class FakeHindsightClient:
    """Records calls; returns canned recall/retain/delete results."""

    def __init__(self) -> None:
        self.retained: list[dict] = []
        self.recalled: list[dict] = []
        self.deleted: list[str] = []
        self._facts_by_bank: dict[str, list[dict]] = {}

    async def retain(
        self,
        *,
        bank_id,
        content,
        document_id,
        context=None,
        metadata=None,
        tags=None,
        timestamp=None,
    ):
        self.retained.append(
            {
                "bank_id": bank_id,
                "document_id": document_id,
                "content": content,
                "tags": list(tags or []),
            }
        )
        self._facts_by_bank.setdefault(bank_id, []).append(
            {
                "document_id": document_id,
                "text": content,
                "tags": list(tags or []),
                "mentioned_at": "2026-06-06T00:00:00+00:00",
            }
        )
        return {"success": True, "bank_id": bank_id, "items_count": 1}

    async def recall(self, *, bank_id, query, types=None, max_tokens=4096, tags=None):
        self.recalled.append({"bank_id": bank_id, "query": query})
        return {"results": list(self._facts_by_bank.get(bank_id, []))}

    async def delete_document(self, *, bank_id, document_id):
        self.deleted.append(document_id)
        facts = self._facts_by_bank.get(bank_id, [])
        before = len(facts)
        self._facts_by_bank[bank_id] = [f for f in facts if f["document_id"] != document_id]
        return {"memory_units_deleted": before - len(self._facts_by_bank[bank_id])}


def test_namespace_to_bank_mapping():
    assert namespace_to_bank("shared") == "shared"
    assert namespace_to_bank("private:hermes") == "private__hermes"
    assert namespace_to_bank("project:42") == "project__42"
    assert namespace_to_bank("agents") == "agents"


@pytest.mark.asyncio
async def test_add_routes_to_retain_under_mapped_bank():
    fake = FakeHindsightClient()
    p = HindsightProvider(client=fake, client_id="hermes")
    res = await p.add("Alice works at Google", dataset="private:hermes", client_id="hermes")
    assert set(res) == {"id", "timestamp"}
    assert fake.retained[0]["bank_id"] == "private__hermes"
    # The returned id IS the document_id (the join key), not a fact id.
    assert fake.retained[0]["document_id"] == res["id"]
