"""HindsightProvider — the platform memory engine (brain-redesign P1).

Maps hal0's engine-neutral MemoryProvider contract onto the shared
``hindsight-api`` over REST. Key design points (spec §3, §4b, P1):

* **Bank mapping** lives HERE (not namespace.py, which is unchanged): hal0
  namespace ``private:<agent>`` → Hindsight bank ``private__<agent>`` (``:``:
  ``__``); ``project:<id>`` → ``project__<id>``; ``shared``/``agents`` pass
  through.
* ``MemoryItem.id`` is the Hindsight **document_id** — idempotent on retain,
  recall-visible, delete-addressable. NOT a per-fact id (those are async +
  many-per-add).
* ``add`` routes to Hindsight **retain** so background consolidation fires.
* **Multi-bank recall fan-out** (Task P1-3): Hindsight recall is per-bank,
  client-orchestrated; we fan out to the caller's allowed banks and merge
  under one reranked token budget (recall returns NO numeric score, so the
  union is re-ranked via the :8086 reranker; §4b precedence is the tiebreak).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from hal0.memory.provider import MemoryProvider

_SHARED = "shared"
_PRIVATE = "private:"


def namespace_to_bank(namespace: str) -> str:
    """Map a hal0 namespace to a Hindsight bank id (spec §3 table)."""
    return namespace.replace(":", "__")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class HindsightProvider(MemoryProvider):
    def __init__(
        self,
        *,
        client: Any,
        client_id: str = "anonymous",
        reranker: Any = None,
    ) -> None:
        self._client = client
        self._client_id = client_id
        self._reranker = reranker
        self._graph_enabled = False
        self._graph_route = "upstream"
        self._rerank_enabled = reranker is not None

    # ── ACL: the caller's allowed namespaces → banks ───────────────────

    def _allowed_namespaces(self, requested: str | list[str], client_id: str | None) -> list[str]:
        cid = client_id or self._client_id
        own = f"{_PRIVATE}{cid}"
        reqs = [requested] if isinstance(requested, str) else list(requested or [_SHARED])
        out: list[str] = []
        for ds in reqs:
            if ds == _SHARED:
                out += [d for d in (_SHARED, own) if d not in out]
            elif ds == own and own not in out:
                out.append(own)
            elif ds.startswith(_PRIVATE):
                continue  # foreign private — dropped (fail-open-empty)
            elif ds not in out:
                out.append(ds)
        return out

    def _write_namespace(self, requested: str, client_id: str | None) -> str:
        # The REST/MCP front door already resolved the write namespace via
        # namespace.resolve_write_dataset; trust it verbatim here.
        return requested or _SHARED

    # ── Core five ──────────────────────────────────────────────────────

    async def add(
        self,
        text: str,
        dataset: str = _SHARED,
        tags: list[str] | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
        client_id: str | None = None,
    ) -> dict[str, str]:
        ns = self._write_namespace(dataset, client_id)
        bank = namespace_to_bank(ns)
        document_id = str(uuid.uuid4())  # the join key
        meta = dict(metadata or {})
        if source:
            meta["source"] = source
        await self._client.retain(
            bank_id=bank,
            content=text,
            document_id=document_id,
            context=meta.get("source"),
            metadata={k: str(v) for k, v in meta.items()},
            tags=list(tags or []),
            timestamp=None,
        )
        return {"id": document_id, "timestamp": _now()}

    async def search(
        self,
        query: str,
        limit: int = 10,
        dataset: str | list[str] = _SHARED,
        tags: list[str] | None = None,
        before: str | None = None,
        after: str | None = None,
        mode: str = "vector",
        client_id: str | None = None,
    ) -> list[dict[str, Any]]:
        # search delegates to recall (back-compat surface); the fan-out lives
        # in recall (Task P1-3). limit is honored after the merge.
        out = await self.recall(
            query=query,
            max_tokens=max(256, limit * 256),
            dataset=dataset,
            tags=tags,
            client_id=client_id,
        )
        return out[:limit]

    async def list_items(
        self,
        dataset: str = _SHARED,
        cursor: str | None = None,
        limit: int = 50,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        # Hindsight has no flat list; list = recall with an empty-ish broad
        # query is unreliable, so we surface the documents endpoint per bank.
        # P1 lists via recall on a wildcard-ish query; refined in P2 if needed.
        out = await self.recall(
            query="*", max_tokens=limit * 256, dataset=dataset, client_id=client_id
        )
        return {"items": out[:limit], "next_cursor": None}

    async def delete(self, ids: list[str], *, client_id: str | None = None) -> dict[str, int]:
        deleted = 0
        # We don't know which bank each document_id lives in without a lookup;
        # try the caller's allowed banks. delete_document is idempotent.
        banks = [namespace_to_bank(ns) for ns in self._allowed_namespaces(_SHARED, client_id)]
        for document_id in ids:
            for bank in banks:
                res = await self._client.delete_document(bank_id=bank, document_id=document_id)
                if int(res.get("memory_units_deleted", 0)) > 0:
                    deleted += 1
                    break
        return {"deleted": deleted}

    # ── recall (fan-out added in Task P1-3) ────────────────────────────

    async def recall(
        self,
        query: str,
        *,
        types: list[str] | None = None,
        max_tokens: int = 4096,
        dataset: str | list[str] = _SHARED,
        tags: list[str] | None = None,
        client_id: str | None = None,
    ) -> list[dict[str, Any]]:
        # Single-bank placeholder; Task P1-3 replaces this with the fan-out.
        banks = [namespace_to_bank(ns) for ns in self._allowed_namespaces(dataset, client_id)]
        merged: list[dict[str, Any]] = []
        for bank in banks:
            resp = await self._client.recall(
                bank_id=bank, query=query, types=types, max_tokens=max_tokens, tags=tags
            )
            for fact in resp.get("results", []):
                merged.append(self._fact_to_item(fact, bank))
        return merged

    # ── Runtime toggles ────────────────────────────────────────────────

    def graph_status(self) -> dict[str, Any]:
        return {
            "enabled": self._graph_enabled,
            "route": self._graph_route,
            "in_flight": 0,
            "builds_ok": 0,
            "errors": 0,
            "last_built_at": None,
            "last_error": None,
        }

    def set_graph_enabled(self, enabled: bool, route: str | None = None) -> None:
        self._graph_enabled = bool(enabled)
        if route is not None:
            self._graph_route = route

    def set_rerank_enabled(self, enabled: bool) -> None:
        self._rerank_enabled = bool(enabled)

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _fact_to_item(fact: dict[str, Any], bank: str) -> dict[str, Any]:
        """Map a Hindsight RecallResult to the MemoryItem wire shape.

        ``score`` is always None — Hindsight recall returns no numeric score;
        ordering carries the relevance signal.
        """
        return {
            "id": fact.get("document_id") or fact.get("id"),
            "text": fact.get("text", ""),
            "timestamp": fact.get("mentioned_at") or _now(),
            "dataset": bank.replace("__", ":"),
            "tags": list(fact.get("tags") or []),
            "source": (fact.get("metadata") or {}).get("source"),
            "metadata": dict(fact.get("metadata") or {}),
            "score": None,
            "type": fact.get("type"),
        }
