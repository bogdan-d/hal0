# Hindsight Engine Swap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Swap hal0's memory engine from Cognee to Hindsight behind a thin `MemoryProvider` ABC + mandatory ACL shim, re-enable the gated brain (`HAL0_MEMORY_ENABLED=1`), and converge Hermes onto the one shared brain — implementing spec phases P0, P1, P2, P5-H.

**Architecture:** Promote the implicit five-method `CogneeWrapper` contract into an explicit `MemoryProvider` ABC, route the single construction site through a `provider_from_config()` factory, add a `HindsightProvider` that fans recall out across the caller's allowed banks (Hindsight has no server-side cross-bank query) and merges under one reranked token budget, then cut the default over to Hindsight with Cognee retained behind a one-release fallback flag. The hal0-api front door (`/api/memory/*` + `/mcp/memory`) stays the only ACL'd choke point; `namespace.py` is the unchanged resolver and the `:`→`__` namespace→bank mapping lives inside `HindsightProvider`.

**Tech Stack:** Python 3.14, FastAPI, `pytest` (with a `slow` marker split — heavy backends are opt-in), `httpx` async client, Hindsight (`hindsight-all`, REST `/v1/default/banks/{bank}/...` + native MCP `/mcp/{bank}/`), lemond OpenAI-compatible gateway (`127.0.0.1:13305`), embedded pg0, systemd on CT 105.

---

## File Structure

Files created or modified across all four phases, each with its single responsibility.

### P0 — Seam & safety net
| Path | Create/Modify | Responsibility |
|---|---|---|
| `src/hal0/memory/provider.py` | Create | The `MemoryProvider` ABC + value types (`Mode` enum). Defines the contract every engine implements. |
| `src/hal0/memory/cognee_wrapper.py` | Modify | Declare `class CogneeWrapper(MemoryProvider)` — conformance only, no logic change. |
| `src/hal0/memory/pgvector_provider.py` | Create | `PgVectorProvider` — third conformance impl + P2 boot fallback. Minimal in-memory-backed stub honoring the ACL contract. |
| `src/hal0/memory/__init__.py` | Modify | Re-export `MemoryProvider` + value types; add `provider_from_config(cfg)` factory (Cognee-only branch in P0). |
| `tests/memory/test_provider_contract.py` | Create | Parametrized conformance suite. Default-gate param is an in-memory `FakeMemoryProvider`; Cognee/PgVector params are `@pytest.mark.slow`. |
| `tests/memory/fakes.py` | Create | `FakeMemoryProvider` — pure-Python ACL-honoring impl used by the default-gate conformance run + as a test double elsewhere. |
| `src/hal0/agents/hermes/plugins/memory_cognee/_client.py` | Modify | Fix the latent 404s: `list_items` → `GET /api/memory/list`, `delete` → `POST /api/memory/delete` with `{ids}`. |
| `tests/agents/hermes_plugins/test_memory_client_routes.py` | Create | Route-path test asserting `_client.py` paths match the real router. |

### P1 — Deploy Hindsight + parity smoke
| Path | Create/Modify | Responsibility |
|---|---|---|
| `src/hal0/memory/hindsight_provider.py` | Create | `HindsightProvider(MemoryProvider)` — core five mapped onto Hindsight retain/recall/delete, the `:`→`__` bank mapping, and the multi-bank recall fan-out + reranked merge. |
| `src/hal0/memory/__init__.py` | Modify | `provider_from_config` gains the `engine` branch (`cognee`/`hindsight`/`mem0`/`pgvector`) + degrade ladder (default still `cognee` in P1). |
| `src/hal0/config/schema.py` | Modify | Add `engine: str = "cognee"` field to `MemoryConfig` (schema.py:1279). |
| `tests/memory/test_hindsight_provider.py` | Create | Bank-mapping + fan-out merge unit tests against a fake Hindsight client. |
| `tests/memory/test_provider_contract.py` | Modify | Add the `HindsightProvider` param (`@pytest.mark.slow`, against a fake client) to the conformance run. |
| `installer/systemd/hindsight-api.service` | Create | systemd unit for the one shared `hindsight-api` (ops-checklist task; exact env/paths below). |
| `docs/internal/brain-redesign/ops/hindsight-deploy.md` | Create | Operator runbook for the P1 deploy + the on-box pre-flight checklist results. |

### P2 — Cutover + re-enable the gate
| Path | Create/Modify | Responsibility |
|---|---|---|
| `src/hal0/memory/__init__.py` | Modify | Flip `provider_from_config` default → `hindsight`. |
| `src/hal0/api/__init__.py` | Modify | Rename `app.state.memory_wrapper` → `app.state.memory_provider`; route construction through `provider_from_config`. |
| `src/hal0/api/routes/memory.py` | Modify | Read `memory_provider`; add `POST /api/memory/recall` route. |
| `src/hal0/api/routes/health.py` | Modify | `memory_enabled` reads `memory_provider` (health.py:98). |
| `src/hal0/api/agents/memory_stats.py` | Modify | Reader reads `memory_provider` (memory_stats.py:141). |
| `src/hal0/api/mcp_mount.py` | Modify | `memory_wrapper=` param → `memory_provider=`; pass through. |
| `src/hal0/mcp/memory.py` | Modify | Register a `recall` MCP tool wired to `provider.recall`. |
| `src/hal0/cli/...` (migrate) | Create | `hal0 memory migrate --dry-run` command (Cognee/sidecar → Hindsight). |
| `installer/install.sh` | Modify | Uncomment the `HAL0_MEMORY_ENABLED=1` template line (install.sh:527). |
| `tests/memory/test_recall_route.py` | Create | `/api/memory/recall` route + `add`→`retain` routing tests. |
| `tests/api/test_memory_provider_rename.py` | Create | `app.state.memory_provider` present; all readers resolve it. |

### P5-H — Hermes convergence
| Path | Create/Modify | Responsibility |
|---|---|---|
| `src/hal0/agents/hermes/plugins/memory_hindsight/` | Create (rename of `memory_cognee/`) | The renamed `hal0-memory` plugin (`hal0-cognee`→`hal0-memory`); `prefetch`→`recall`, `sync_turn`→`retain`. |
| `installer/agents/hermes/plugins/hal0-memory/__init__.py` | Modify/retire | Retire the old stub; vendored plugin is the renamed `memory_hindsight`. |
| `src/hal0/agents/hermes/driver.py` | Modify | Update the plugin-tree reference (driver.py:55) from `memory_cognee` to `memory_hindsight`. |
| `$HERMES_HOME/SOUL.md` (deployed) + `src/hal0/agents/hermes/templates/SOUL.md` if present | Modify | Add the §4b ground-truth precedence stanza. |
| `tests/agents/hermes_plugins/test_memory_hindsight_provider.py` | Create (rename) | Renamed provider tests; assert no `dataset` field, `recall`/`retain` wiring. |

---

## Conventions used throughout this plan

- **Run tests from the repo root** `/home/halo/dev/hal0` unless noted.
- **Default gate** = tests that run on every PR (no `slow` marker). Heavy backends (Cognee/LanceDB/70 MB embed model, a live Hindsight) are `@pytest.mark.slow` and excluded from the default gate — matching the existing `tests/memory/conftest.py` split.
- **"byte-compatible"** in the spec means **signatures + return-shapes**, NOT verbatim text round-trip. Hindsight `retain` extracts *facts* and never stores raw text, and its sync retain response carries **no per-fact id** (`success/bank_id/items_count` only). Conformance assertions therefore check the *contract* (return shapes, ACL/namespace isolation, `private:` rejection, fail-open-empty, tag-AND, date-range, `graph_status()` shape) — never `add("foo")`→`search` returns `"foo"`. The verbatim/on-topic check is the separate, non-gated **recall sanity** check (P1 Task P1-7).
- **`MemoryItem.id` is the Hindsight `document_id`**, never a fact id. `retain` is idempotent by `document_id`, `recall` results carry `document_id`, and delete is `delete_document(document_id=...)`. Fact ids are async + many-per-add, so they cannot be the join key.
- **Hindsight recall returns NO numeric score** ("Results do not include a numeric score" — recall.md). The multi-bank merge therefore **re-ranks the union via the `:8086` reranker** (query+documents→score), with the §4b precedence ladder as the ordering/tiebreak. The alternative "concatenate-by-score" the spec floated is impossible and is not used.

---

# P0 — Seam & safety net

*No gate, ships clean. Cognee stays the only live engine. Zero behaviour change.*

## Task P0-1: Define the `MemoryProvider` ABC + value types

**Files:**
- Create: `src/hal0/memory/provider.py`
- Test: `tests/memory/test_provider_contract.py` (created next task; this task is the impl the suite imports)

- [ ] **Step 1: Write the failing import test**

Create `tests/memory/test_provider_abc.py`:

```python
"""ABC shape tests — the explicit MemoryProvider contract (P0)."""

from __future__ import annotations

import inspect

from hal0.memory.provider import (
    AddResult,
    DeleteResult,
    GraphStatus,
    ListPage,
    MemoryItem,
    MemoryProvider,
    Mode,
)


def test_abc_declares_core_five_plus_status():
    # The methods every engine MUST implement (the call sites in
    # routes/memory.py + mcp/memory.py depend on these exact names).
    required = {
        "add",
        "search",
        "list_items",
        "delete",
        "graph_status",
        "set_graph_enabled",
        "set_rerank_enabled",
    }
    assert required <= set(MemoryProvider.__abstractmethods__)


def test_abc_optional_methods_have_safe_defaults():
    # Optional capability methods are concrete (NOT abstract) so an engine
    # that lacks consolidation still satisfies the ABC.
    optional = {"recall", "reflect", "consolidate", "register_compiled"}
    assert not (optional & set(MemoryProvider.__abstractmethods__))
    for name in optional:
        assert callable(getattr(MemoryProvider, name))


def test_add_signature_matches_cognee_call_sites():
    sig = inspect.signature(MemoryProvider.add)
    params = list(sig.parameters)
    # Mirrors CogneeWrapper.add + the REST/MCP callers.
    assert params == ["self", "text", "dataset", "tags", "source", "metadata", "client_id"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/memory/test_provider_abc.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hal0.memory.provider'`

- [ ] **Step 3: Write the ABC + value types**

Create `src/hal0/memory/provider.py`:

```python
"""The explicit MemoryProvider contract (brain-redesign P0).

Promotes the implicit five-method ``CogneeWrapper`` surface into an ABC so
hal0 can swap engines (Cognee → Hindsight, fallback Mem0/PgVector) without
touching a single call site. The ABC is the anti-lock-in seam (spec §1).

The *core five* (``add/search/list_items/delete`` + the three runtime
toggles ``graph_status/set_graph_enabled/set_rerank_enabled``) are abstract:
every engine must implement them, byte-compatible in **signature + return
shape** with ``CogneeWrapper`` so the REST shims + MCP dispatcher need no
changes. The *optional* methods (``recall/reflect/consolidate/
register_compiled``) ship concrete safe defaults so an engine without
consolidation still satisfies the contract.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class Mode(str, enum.Enum):
    """Search mode — mirrors CogneeWrapper's accepted ``mode`` values."""

    VECTOR = "vector"
    GRAPH = "graph"
    HYBRID = "hybrid"


@dataclass
class MemoryItem:
    """One stored memory. ``id`` is the engine's join key.

    For Hindsight this is the ``document_id`` (idempotent, recall-visible,
    delete-addressable) — NOT a per-fact id. For Cognee it is the sidecar
    uuid. The wire shape matches ``CogneeWrapper.MemoryRecord``.
    """

    id: str
    text: str
    timestamp: str  # ISO-8601 UTC
    dataset: str
    tags: list[str] = field(default_factory=list)
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "timestamp": self.timestamp,
            "dataset": self.dataset,
            "tags": list(self.tags),
            "source": self.source,
            "metadata": dict(self.metadata),
            "score": self.score,
        }


@dataclass
class AddResult:
    """Return shape of ``add`` — matches ``CogneeWrapper.add``."""

    id: str
    timestamp: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "timestamp": self.timestamp}


@dataclass
class ListPage:
    """Return shape of ``list_items`` — matches ``CogneeWrapper.list_items``."""

    items: list[dict[str, Any]]
    next_cursor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"items": list(self.items), "next_cursor": self.next_cursor}


@dataclass
class DeleteResult:
    """Return shape of ``delete`` — matches ``CogneeWrapper.delete``."""

    deleted: int

    def to_dict(self) -> dict[str, int]:
        return {"deleted": self.deleted}


@dataclass
class GraphStatus:
    """Return shape of ``graph_status`` — matches the CogneeWrapper payload."""

    enabled: bool
    route: str
    in_flight: int = 0
    builds_ok: int = 0
    errors: int = 0
    last_built_at: str | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "route": self.route,
            "in_flight": self.in_flight,
            "builds_ok": self.builds_ok,
            "errors": self.errors,
            "last_built_at": self.last_built_at,
            "last_error": self.last_error,
        }


class MemoryProvider(ABC):
    """Engine-neutral memory contract. See module docstring."""

    # ── Core five (abstract) ───────────────────────────────────────────

    @abstractmethod
    async def add(
        self,
        text: str,
        dataset: str = "shared",
        tags: list[str] | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
        client_id: str | None = None,
    ) -> dict[str, str]:
        """Add a memory item. Returns ``{id, timestamp}``."""

    @abstractmethod
    async def search(
        self,
        query: str,
        limit: int = 10,
        dataset: str | list[str] = "shared",
        tags: list[str] | None = None,
        before: str | None = None,
        after: str | None = None,
        mode: str = "vector",
        client_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Vector + filter search. Returns a list of MemoryItem dicts."""

    @abstractmethod
    async def list_items(
        self,
        dataset: str = "shared",
        cursor: str | None = None,
        limit: int = 50,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        """Paginated list. Returns ``{items, next_cursor}``."""

    @abstractmethod
    async def delete(self, ids: list[str], *, client_id: str | None = None) -> dict[str, int]:
        """Delete by id. Returns ``{deleted: int}``."""

    @abstractmethod
    def graph_status(self) -> dict[str, Any]:
        """Return the graph-extraction status payload (GraphStatus shape)."""

    @abstractmethod
    def set_graph_enabled(self, enabled: bool, route: str | None = None) -> None:
        """Flip the graph-extraction gate at runtime."""

    @abstractmethod
    def set_rerank_enabled(self, enabled: bool) -> None:
        """Flip the rerank gate at runtime."""

    # ── Optional capability methods (concrete safe defaults) ───────────

    async def recall(
        self,
        query: str,
        *,
        types: list[str] | None = None,
        max_tokens: int = 4096,
        dataset: str | list[str] = "shared",
        tags: list[str] | None = None,
        client_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Token-budgeted recall. Default delegates to ``search`` so an
        engine without a richer recall surface still answers the route."""
        return await self.search(
            query=query,
            limit=max(1, max_tokens // 256),
            dataset=dataset,
            tags=tags,
            client_id=client_id,
        )

    async def reflect(self, *, dataset: str = "shared", client_id: str | None = None) -> dict[str, Any]:
        """Trigger consolidation/reflection. No-op default."""
        return {"status": "unsupported"}

    async def consolidate(self, *, dataset: str = "shared") -> dict[str, Any]:
        """Trigger background consolidation. No-op default."""
        return {"status": "unsupported"}

    def register_compiled(self, *args: Any, **kwargs: Any) -> None:
        """Register a compiled artifact (directive/mental model). No-op default."""
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/memory/test_provider_abc.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/hal0/memory/provider.py tests/memory/test_provider_abc.py
git commit -m "feat(memory): add explicit MemoryProvider ABC + value types (P0)"
```

## Task P0-2: Declare `CogneeWrapper(MemoryProvider)` conformance

**Files:**
- Modify: `src/hal0/memory/cognee_wrapper.py:176` (`class CogneeWrapper:` → subclass)
- Test: `tests/memory/test_provider_abc.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/memory/test_provider_abc.py`:

```python
def test_cognee_wrapper_is_a_memory_provider():
    from hal0.memory.cognee_wrapper import CogneeWrapper
    from hal0.memory.provider import MemoryProvider

    assert issubclass(CogneeWrapper, MemoryProvider)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/memory/test_provider_abc.py::test_cognee_wrapper_is_a_memory_provider -v`
Expected: FAIL with `AssertionError` (CogneeWrapper is not yet a subclass)

- [ ] **Step 3: Make the subclass declaration**

In `src/hal0/memory/cognee_wrapper.py`, add the import near the top (after line 48, the `import structlog` line):

```python
from hal0.memory.provider import MemoryProvider
```

Change line 176 from:

```python
class CogneeWrapper:
```

to:

```python
class CogneeWrapper(MemoryProvider):
```

> NOTE (verify): `CogneeWrapper` already implements every abstract method (`add/search/list_items/delete/graph_status/set_graph_enabled/set_rerank_enabled`) with matching signatures — confirmed against the source. No method-body change is needed; this is a pure declaration.

- [ ] **Step 4: Run the test + the full existing memory suite to verify no regression**

Run: `python -m pytest tests/memory/test_provider_abc.py tests/memory/test_namespace_wrapper.py -v`
Expected: PASS (no abstract-method-instantiation error, namespace tests still green)

- [ ] **Step 5: Commit**

```bash
git add src/hal0/memory/cognee_wrapper.py tests/memory/test_provider_abc.py
git commit -m "feat(memory): declare CogneeWrapper conformance to MemoryProvider (P0)"
```

## Task P0-3: `FakeMemoryProvider` + the parametrized conformance suite

**Files:**
- Create: `tests/memory/fakes.py`
- Create: `tests/memory/test_provider_contract.py`

- [ ] **Step 1: Write the conformance suite (the failing test)**

Create `tests/memory/test_provider_contract.py`:

```python
"""Parametrized MemoryProvider conformance suite (brain-redesign P0).

Asserts the contract every engine must honor: namespace isolation,
``private:`` write rejection at the wrapper boundary, tag-AND, date-range,
delete semantics, fail-open-empty foreign-private reads, and the
``graph_status()`` payload shape.

The DEFAULT-gate parameter is the in-memory ``FakeMemoryProvider`` so this
suite runs on every PR without dragging a heavy backend in. Real backends
(Cognee, PgVector, Hindsight) attach as ``@pytest.mark.slow`` params, matching
the existing tests/memory/conftest.py split.
"""

from __future__ import annotations

import pytest

from tests.memory.fakes import FakeMemoryProvider


@pytest.fixture
def provider(request) -> object:
    # request.param is a 0-arg factory returning a fresh provider.
    return request.param()


def _fake_factory():
    return FakeMemoryProvider(client_id="alice")


# Default gate: the fake only. Slow backends are added by later tasks via
# pytest_generate_tests / additional params marked slow.
@pytest.fixture(params=[_fake_factory], ids=["fake"])
def conformant(request):
    return request.param()


@pytest.mark.asyncio
async def test_add_returns_id_and_timestamp(conformant):
    result = await conformant.add("a note", dataset="shared")
    assert set(result) == {"id", "timestamp"}
    assert isinstance(result["id"], str) and result["id"]


@pytest.mark.asyncio
async def test_namespace_isolation_foreign_private_reads_empty(conformant):
    # A write into alice's private bucket is invisible to a bob-scoped read.
    await conformant.add("alice secret", dataset="private:alice", client_id="alice")
    out = await conformant.search("secret", dataset="private:bob", client_id="bob")
    assert out == []


@pytest.mark.asyncio
async def test_tag_and_match(conformant):
    await conformant.add("tagged", dataset="shared", tags=["x", "y"])
    await conformant.add("partial", dataset="shared", tags=["x"])
    out = await conformant.search("tagged partial", dataset="shared", tags=["x", "y"])
    texts = {r["text"] for r in out}
    assert "tagged" in texts and "partial" not in texts


@pytest.mark.asyncio
async def test_date_range_before_after(conformant):
    await conformant.add("old", dataset="shared")
    out = await conformant.search("old", dataset="shared", after="2099-01-01T00:00:00+00:00")
    assert out == []  # nothing after the year 2099


@pytest.mark.asyncio
async def test_delete_semantics(conformant):
    res = await conformant.add("deleteme", dataset="shared")
    deleted = await conformant.delete([res["id"]])
    assert deleted == {"deleted": 1}
    out = await conformant.search("deleteme", dataset="shared")
    assert out == []


@pytest.mark.asyncio
async def test_graph_status_shape(conformant):
    status = conformant.graph_status()
    assert set(status) >= {
        "enabled",
        "route",
        "in_flight",
        "builds_ok",
        "errors",
        "last_built_at",
        "last_error",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/memory/test_provider_contract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.memory.fakes'`

- [ ] **Step 3: Write `FakeMemoryProvider`**

Create `tests/memory/fakes.py`:

```python
"""In-memory MemoryProvider for the default-gate conformance suite.

Honors the ACL contract (shared + own-private reads; foreign-private reads
fail-open-empty) with zero external deps so the suite runs on every PR.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from hal0.memory.provider import MemoryProvider

_SHARED = "shared"
_PRIVATE = "private:"


def _now() -> str:
    return datetime.now(UTC).isoformat()


class FakeMemoryProvider(MemoryProvider):
    def __init__(self, *, client_id: str = "anonymous") -> None:
        self._client_id = client_id
        self._rows: list[dict[str, Any]] = []
        self._graph_enabled = False
        self._graph_route = "upstream"
        self._rerank_enabled = False

    def _allowed(self, requested: str | list[str], client_id: str | None) -> list[str]:
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

    async def add(self, text, dataset=_SHARED, tags=None, source=None, metadata=None, client_id=None):
        item_id = str(uuid.uuid4())
        self._rows.append(
            {
                "id": item_id,
                "text": text,
                "timestamp": _now(),
                "dataset": dataset,
                "tags": list(tags or []),
                "source": source or (client_id or self._client_id),
                "metadata": dict(metadata or {}),
                "score": None,
            }
        )
        return {"id": item_id, "timestamp": self._rows[-1]["timestamp"]}

    async def search(self, query, limit=10, dataset=_SHARED, tags=None, before=None, after=None, mode="vector", client_id=None):
        allowed = self._allowed(dataset, client_id)
        tags = tags or []
        out = []
        for row in self._rows:
            if row["dataset"] not in allowed:
                continue
            if tags and not all(t in row["tags"] for t in tags):
                continue
            if before and row["timestamp"] >= before:
                continue
            if after and row["timestamp"] <= after:
                continue
            out.append(dict(row))
            if len(out) >= limit:
                break
        return out

    async def list_items(self, dataset=_SHARED, cursor=None, limit=50, client_id=None):
        allowed = self._allowed(dataset, client_id)
        items = [dict(r) for r in self._rows if r["dataset"] in allowed][:limit]
        return {"items": items, "next_cursor": None}

    async def delete(self, ids, *, client_id=None):
        before = len(self._rows)
        self._rows = [r for r in self._rows if r["id"] not in set(ids)]
        return {"deleted": before - len(self._rows)}

    def graph_status(self):
        return {
            "enabled": self._graph_enabled,
            "route": self._graph_route,
            "in_flight": 0,
            "builds_ok": 0,
            "errors": 0,
            "last_built_at": None,
            "last_error": None,
        }

    def set_graph_enabled(self, enabled, route=None):
        self._graph_enabled = bool(enabled)
        if route is not None:
            self._graph_route = route

    def set_rerank_enabled(self, enabled):
        self._rerank_enabled = bool(enabled)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/memory/test_provider_contract.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/memory/fakes.py tests/memory/test_provider_contract.py
git commit -m "test(memory): parametrized MemoryProvider conformance suite + FakeMemoryProvider (P0)"
```

## Task P0-4: `PgVectorProvider` stub (third conformance impl + P2 fallback)

**Files:**
- Create: `src/hal0/memory/pgvector_provider.py`
- Modify: `tests/memory/test_provider_contract.py` (add the slow param)

- [ ] **Step 1: Write the failing test**

Append to `tests/memory/test_provider_contract.py`:

```python
def _pgvector_factory():
    from hal0.memory.pgvector_provider import PgVectorProvider

    return PgVectorProvider(client_id="alice")


@pytest.mark.slow
@pytest.mark.asyncio
async def test_pgvector_conforms():
    p = _pgvector_factory()
    res = await p.add("pg note", dataset="shared")
    assert set(res) == {"id", "timestamp"}
    out = await p.search("pg", dataset="private:bob", client_id="bob")
    assert out == []
    assert set(p.graph_status()) >= {"enabled", "route"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/memory/test_provider_contract.py::test_pgvector_conforms -m slow -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hal0.memory.pgvector_provider'`

- [ ] **Step 3: Write the stub**

Create `src/hal0/memory/pgvector_provider.py`. It is a minimal, dependency-light provider (an in-process dict store with the same ACL behavior) used as the **P2 boot fallback** when Hindsight is unavailable — it answers `available:false`-style empties rather than crashing. The body mirrors `FakeMemoryProvider`'s ACL logic but lives in `src/` (not `tests/`):

```python
"""PgVectorProvider — the documented boot fallback (spec P1 degrade ladder).

Minimal MemoryProvider impl with the same shared+own-private ACL behaviour
as the engines. Stands in when Hindsight is unavailable at boot so the
tools return empties + the dashboard shows "no engine" instead of crashing.
A real pgvector backing is deferred; the contract + degrade path are what P0
needs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from hal0.memory.provider import MemoryProvider

_SHARED = "shared"
_PRIVATE = "private:"


def _now() -> str:
    return datetime.now(UTC).isoformat()


class PgVectorProvider(MemoryProvider):
    def __init__(self, *, client_id: str = "anonymous") -> None:
        self._client_id = client_id
        self._rows: list[dict[str, Any]] = []
        self._graph_enabled = False
        self._graph_route = "upstream"
        self._rerank_enabled = False

    def _allowed(self, requested: str | list[str], client_id: str | None) -> list[str]:
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
                continue
            elif ds not in out:
                out.append(ds)
        return out

    async def add(self, text, dataset=_SHARED, tags=None, source=None, metadata=None, client_id=None):
        item_id = str(uuid.uuid4())
        ts = _now()
        self._rows.append(
            {
                "id": item_id,
                "text": text,
                "timestamp": ts,
                "dataset": dataset,
                "tags": list(tags or []),
                "source": source or (client_id or self._client_id),
                "metadata": dict(metadata or {}),
                "score": None,
            }
        )
        return {"id": item_id, "timestamp": ts}

    async def search(self, query, limit=10, dataset=_SHARED, tags=None, before=None, after=None, mode="vector", client_id=None):
        allowed = self._allowed(dataset, client_id)
        tags = tags or []
        out = []
        for row in self._rows:
            if row["dataset"] not in allowed:
                continue
            if tags and not all(t in row["tags"] for t in tags):
                continue
            if before and row["timestamp"] >= before:
                continue
            if after and row["timestamp"] <= after:
                continue
            out.append(dict(row))
            if len(out) >= limit:
                break
        return out

    async def list_items(self, dataset=_SHARED, cursor=None, limit=50, client_id=None):
        allowed = self._allowed(dataset, client_id)
        return {"items": [dict(r) for r in self._rows if r["dataset"] in allowed][:limit], "next_cursor": None}

    async def delete(self, ids, *, client_id=None):
        before = len(self._rows)
        self._rows = [r for r in self._rows if r["id"] not in set(ids)]
        return {"deleted": before - len(self._rows)}

    def graph_status(self):
        return {
            "enabled": self._graph_enabled,
            "route": self._graph_route,
            "in_flight": 0,
            "builds_ok": 0,
            "errors": 0,
            "last_built_at": None,
            "last_error": None,
        }

    def set_graph_enabled(self, enabled, route=None):
        self._graph_enabled = bool(enabled)
        if route is not None:
            self._graph_route = route

    def set_rerank_enabled(self, enabled):
        self._rerank_enabled = bool(enabled)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/memory/test_provider_contract.py::test_pgvector_conforms -m slow -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/hal0/memory/pgvector_provider.py tests/memory/test_provider_contract.py
git commit -m "feat(memory): PgVectorProvider stub — third conformance impl + boot fallback (P0)"
```

## Task P0-5: `provider_from_config()` factory (Cognee-only branch)

**Files:**
- Modify: `src/hal0/memory/__init__.py`
- Test: `tests/memory/test_provider_factory.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/memory/test_provider_factory.py`:

```python
"""provider_from_config factory tests (P0: Cognee-only branch)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from hal0.memory import provider_from_config
from hal0.memory.cognee_wrapper import CogneeWrapper


def _cfg(engine="cognee"):
    return SimpleNamespace(
        memory=SimpleNamespace(
            engine=engine,
            embedding=SimpleNamespace(model="BAAI/bge-small-en-v1.5", rerank_enabled=False,
                                      rerank_url="http://127.0.0.1:8086", rerank_over_fetch_factor=5,
                                      rerank_max_candidates=500, rerank_connect_timeout_s=1.0,
                                      rerank_read_timeout_s=8.0),
            graph=SimpleNamespace(enabled=False, route="upstream"),
        )
    )


def test_factory_returns_cognee_for_default_engine():
    # Patch the constructor so we don't stand up real Cognee.
    with patch("hal0.memory.CogneeWrapper", autospec=True) as mock_cls:
        provider_from_config(_cfg("cognee"))
        assert mock_cls.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/memory/test_provider_factory.py -v`
Expected: FAIL with `ImportError: cannot import name 'provider_from_config'`

- [ ] **Step 3: Write the factory**

Replace `src/hal0/memory/__init__.py` with:

```python
"""hal0 memory subsystem (ADR-0005 + brain-redesign P0–P2).

Public contract for ``/mcp/memory`` + ``/api/memory/*``. Exposes the
engine-neutral :class:`MemoryProvider` ABC and the ``provider_from_config``
factory that the one construction site in ``api/__init__.py`` calls.
"""

from __future__ import annotations

from typing import Any

import structlog

from hal0.memory.cognee_wrapper import CogneeWrapper, MemoryRecord
from hal0.memory.provider import (
    AddResult,
    DeleteResult,
    GraphStatus,
    ListPage,
    MemoryItem,
    MemoryProvider,
    Mode,
)

log = structlog.get_logger(__name__)

__all__ = [
    "AddResult",
    "CogneeWrapper",
    "DeleteResult",
    "GraphStatus",
    "ListPage",
    "MemoryItem",
    "MemoryProvider",
    "MemoryRecord",
    "Mode",
    "provider_from_config",
]


def provider_from_config(cfg: Any) -> MemoryProvider:
    """Construct the active MemoryProvider from the loaded hal0 config.

    P0: only the ``cognee`` branch is wired (default). P1 adds ``hindsight``
    + the degrade ladder; P2 flips the default. ``cfg`` is the object returned
    by ``hal0.config.loader.load_hal0_config``.
    """
    engine = str(getattr(cfg.memory, "engine", "cognee") or "cognee").lower()
    embed = cfg.memory.embedding
    graph = cfg.memory.graph

    if engine == "cognee":
        return CogneeWrapper(
            embedding_model=str(embed.model),
            graph_enabled=bool(graph.enabled),
            graph_route=str(graph.route),
            rerank_enabled=bool(embed.rerank_enabled),
            rerank_url=str(embed.rerank_url),
            rerank_over_fetch_factor=int(embed.rerank_over_fetch_factor),
            rerank_max_candidates=int(embed.rerank_max_candidates),
            rerank_connect_timeout_s=float(embed.rerank_connect_timeout_s),
            rerank_read_timeout_s=float(embed.rerank_read_timeout_s),
        )

    # P1 wires hindsight/mem0/pgvector here.
    log.warning("hal0.memory.unknown_engine", engine=engine, fallback="cognee")
    return CogneeWrapper(embedding_model=str(embed.model))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/memory/test_provider_factory.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/hal0/memory/__init__.py tests/memory/test_provider_factory.py
git commit -m "feat(memory): provider_from_config factory (Cognee branch, P0)"
```

## Task P0-6: Fix the Hermes `_client.py` 404s + route-path test

**Files:**
- Modify: `src/hal0/agents/hermes/plugins/memory_cognee/_client.py:133-143`
- Create: `tests/agents/hermes_plugins/test_memory_client_routes.py`

The audit (spec P0 work-items) found two latent 404s: `list_items` calls `GET /api/memory` (real route is `GET /api/memory/list`) and `delete` calls `DELETE /api/memory/{id}` (real route is `POST /api/memory/delete` with `{ids}`).

- [ ] **Step 1: Write the failing route-path test**

Create `tests/agents/hermes_plugins/test_memory_client_routes.py`:

```python
"""Lock the hal0-memory REST client paths against the real router (P0).

The router only defines GET /api/memory/list and POST /api/memory/delete.
The client previously called GET /api/memory and DELETE /api/memory/{id},
which 404. This test asserts the client now hits routes the router serves.
"""

from __future__ import annotations

import httpx
import pytest

from hal0.agents.hermes.plugins.memory_cognee._client import Hal0MemoryClient
from hal0.api.routes.memory import router


def _router_paths() -> set[tuple[str, str]]:
    out = set()
    for route in router.routes:
        for method in getattr(route, "methods", set()):
            out.add((method, route.path))
    return out


@pytest.mark.asyncio
async def test_list_and_delete_hit_real_routes():
    seen: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json={"items": [], "next_cursor": None})
        return httpx.Response(200, json={"deleted": 1})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://x") as http:
        client = Hal0MemoryClient(http_client=http)
        await client.list_items(limit=10)
        await client.delete("some-id")

    # The router serves these; the client must target them.
    paths = _router_paths()
    assert ("GET", "/api/memory/list") in paths
    assert ("POST", "/api/memory/delete") in paths
    assert ("GET", "/api/memory/list") in seen
    assert ("POST", "/api/memory/delete") in seen
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/agents/hermes_plugins/test_memory_client_routes.py -v`
Expected: FAIL — `seen` contains `("GET", "/api/memory")` and `("DELETE", "/api/memory/some-id")`, not the router paths.

- [ ] **Step 3: Fix the client methods**

In `src/hal0/agents/hermes/plugins/memory_cognee/_client.py`, replace `list_items` (lines 133-139) and `delete` (lines 141-143):

```python
    async def list_items(self, *, limit: int = 50) -> dict[str, Any]:
        """GET /api/memory/list — page through stored items.

        ``limit`` is forwarded as a query parameter; the server resolves the
        dataset from ``X-hal0-Agent``. (Was GET /api/memory — a 404 — fixed
        in P0.)
        """
        return await self._request("GET", "/api/memory/list", params={"limit": int(limit)})

    async def delete(self, item_id: str) -> dict[str, Any]:
        """POST /api/memory/delete — remove memory items by id.

        The router exposes a body-based bulk delete (``{ids: [...]}``), not a
        path-param DELETE. (Was DELETE /api/memory/{id} — a 404 — fixed in P0.)
        """
        return await self._request("POST", "/api/memory/delete", json={"ids": [item_id]})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/agents/hermes_plugins/test_memory_client_routes.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/hal0/agents/hermes/plugins/memory_cognee/_client.py tests/agents/hermes_plugins/test_memory_client_routes.py
git commit -m "fix(hermes): hal0-memory client list/delete hit real routes (was 404) (P0)"
```

## Task P0-7: Wire the conformance suite + format check into the default CI gate

**Files:**
- Modify: the CI workflow that runs `pytest` (find via `ls .github/workflows/`)

- [ ] **Step 1: Locate the test step**

Run: `grep -rn "pytest\|ruff format" .github/workflows/`
Expected: a workflow step invoking `python -m pytest ...` and (per auto-memory `feedback_hal0_ci_ruff_format_check`) a separate `ruff format --check` step.

- [ ] **Step 2: Confirm the default gate already collects the new suite**

Run: `python -m pytest tests/memory/test_provider_contract.py tests/memory/test_provider_abc.py tests/memory/test_provider_factory.py -v`
Expected: PASS (default-gate params only; no `slow` backend pulled in)

- [ ] **Step 3: Run the format check the CI gate runs**

Run: `ruff format --check src/hal0/memory/provider.py src/hal0/memory/pgvector_provider.py src/hal0/memory/__init__.py tests/memory/fakes.py tests/memory/test_provider_contract.py`
Expected: PASS ("N files already formatted"). If it fails, run `ruff format <files>` and re-commit.

> NOTE (verify): hal0's pytest default selection already discovers `tests/memory/`; no workflow edit is needed unless the suite isn't collected. Confirm with `grep -n "tests" pyproject.toml` (the `[tool.pytest.ini_options]` `testpaths`) — if `testpaths` is set and excludes the new files, add them. Otherwise this task is a no-op verification.

- [ ] **Step 4: Commit (only if a workflow/pyproject edit was needed)**

```bash
git add .github/workflows/ pyproject.toml
git commit -m "ci(memory): ensure MemoryProvider conformance suite runs in default gate (P0)"
```

**P0 Exit:** Contract suite green for the fake (default gate) + Cognee/PgVector (`slow`); app boots unchanged; `_client.py` route test green; `add→search→list→delete` byte-identical to pre-change over both transports. **Rollback:** revert the one `class CogneeWrapper(MemoryProvider)` line (the factory + ABC are additive).

---

# P1 — Deploy Hindsight for real + parity smoke

*Real deploy (not a dark shadow). Default still Cognee. Leaves `main` shippable.*

## Task P1-1: `MemoryConfig.engine` field

**Files:**
- Modify: `src/hal0/config/schema.py:1279` (`MemoryConfig`)
- Test: `tests/config/test_memory_engine_field.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/config/test_memory_engine_field.py`:

```python
"""[memory] engine selector field (brain-redesign P1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hal0.config.schema import MemoryConfig


def test_engine_defaults_to_cognee():
    assert MemoryConfig().engine == "cognee"


def test_engine_accepts_known_engines():
    for e in ("cognee", "hindsight", "mem0", "pgvector"):
        assert MemoryConfig(engine=e).engine == e


def test_engine_rejects_unknown():
    with pytest.raises(ValidationError):
        MemoryConfig(engine="weaviate")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/config/test_memory_engine_field.py -v`
Expected: FAIL — `MemoryConfig().engine` raises `AttributeError` / the field doesn't exist.

- [ ] **Step 3: Add the field**

In `src/hal0/config/schema.py`, in `class MemoryConfig` (after the `embedding` field at line 1292), add:

```python
    engine: str = Field(
        default="cognee",
        description=(
            "Active memory engine. One of 'cognee' | 'hindsight' | 'mem0' | "
            "'pgvector'. Default 'cognee' until P2 cutover. The fallback flag: "
            "set back to 'cognee' to revert to the untouched Cognee store for "
            "one release after the Hindsight cutover."
        ),
    )

    @field_validator("engine")
    @classmethod
    def _engine_is_known(cls, v: str) -> str:
        known = {"cognee", "hindsight", "mem0", "pgvector"}
        s = str(v or "cognee").strip().lower()
        if s not in known:
            raise ValueError(f"memory.engine {v!r} must be one of {sorted(known)}")
        return s
```

> NOTE (verify): `field_validator` is already imported in schema.py (used by `ModelsConfig.roots_are_absolute` at schema.py:1340). Confirm the import line near the top of the file; if absent, add `from pydantic import field_validator`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/config/test_memory_engine_field.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/hal0/config/schema.py tests/config/test_memory_engine_field.py
git commit -m "feat(config): add memory.engine selector field (P1)"
```

## Task P1-2: `HindsightProvider` — bank mapping + core five (single-bank path)

**Files:**
- Create: `src/hal0/memory/hindsight_provider.py`
- Test: `tests/memory/test_hindsight_provider.py` (create)

The provider talks to the shared `hindsight-api` over REST. Tests inject a fake async client so they stay in the default gate; the real client is exercised by the `slow` conformance param (Task P1-4) and the on-box recall sanity check (Task P1-7).

- [ ] **Step 1: Write the failing bank-mapping test**

Create `tests/memory/test_hindsight_provider.py`:

```python
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

    async def retain(self, *, bank_id, content, document_id, context=None, metadata=None, tags=None, timestamp=None):
        self.retained.append({"bank_id": bank_id, "document_id": document_id, "content": content, "tags": list(tags or [])})
        self._facts_by_bank.setdefault(bank_id, []).append(
            {"document_id": document_id, "text": content, "tags": list(tags or []), "mentioned_at": "2026-06-06T00:00:00+00:00"}
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/memory/test_hindsight_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hal0.memory.hindsight_provider'`

- [ ] **Step 3: Write the provider (single-bank path; fan-out added next task)**

Create `src/hal0/memory/hindsight_provider.py`:

```python
"""HindsightProvider — the platform memory engine (brain-redesign P1).

Maps hal0's engine-neutral MemoryProvider contract onto the shared
``hindsight-api`` over REST. Key design points (spec §3, §4b, P1):

* **Bank mapping** lives HERE (not namespace.py, which is unchanged): hal0
  namespace ``private:<agent>`` → Hindsight bank ``private__<agent>`` (``:``→
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

    async def add(self, text, dataset=_SHARED, tags=None, source=None, metadata=None, client_id=None):
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

    async def search(self, query, limit=10, dataset=_SHARED, tags=None, before=None, after=None, mode="vector", client_id=None):
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

    async def list_items(self, dataset=_SHARED, cursor=None, limit=50, client_id=None):
        # Hindsight has no flat list; list = recall with an empty-ish broad
        # query is unreliable, so we surface the documents endpoint per bank.
        # P1 lists via recall on a wildcard-ish query; refined in P2 if needed.
        out = await self.recall(query="*", max_tokens=limit * 256, dataset=dataset, client_id=client_id)
        return {"items": out[:limit], "next_cursor": None}

    async def delete(self, ids, *, client_id=None):
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

    async def recall(self, query, *, types=None, max_tokens=4096, dataset=_SHARED, tags=None, client_id=None):
        # Single-bank placeholder; Task P1-3 replaces this with the fan-out.
        banks = [namespace_to_bank(ns) for ns in self._allowed_namespaces(dataset, client_id)]
        merged: list[dict[str, Any]] = []
        for bank in banks:
            resp = await self._client.recall(bank_id=bank, query=query, types=types, max_tokens=max_tokens, tags=tags)
            for fact in resp.get("results", []):
                merged.append(self._fact_to_item(fact, bank))
        return merged

    # ── Runtime toggles ────────────────────────────────────────────────

    def graph_status(self):
        return {
            "enabled": self._graph_enabled,
            "route": self._graph_route,
            "in_flight": 0,
            "builds_ok": 0,
            "errors": 0,
            "last_built_at": None,
            "last_error": None,
        }

    def set_graph_enabled(self, enabled, route=None):
        self._graph_enabled = bool(enabled)
        if route is not None:
            self._graph_route = route

    def set_rerank_enabled(self, enabled):
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/memory/test_hindsight_provider.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/hal0/memory/hindsight_provider.py tests/memory/test_hindsight_provider.py
git commit -m "feat(memory): HindsightProvider — bank mapping + retain/recall/delete core (P1)"
```

## Task P1-3: Multi-bank recall fan-out + reranked merge

**Files:**
- Modify: `src/hal0/memory/hindsight_provider.py` (`recall`)
- Test: `tests/memory/test_hindsight_provider.py` (extend)

Hindsight has no server-side cross-bank query; a hal0 recall must hit the caller's own `private:*` + `shared` (+ any `project:*`) **in parallel** and merge under one token budget. Because recall returns no numeric score, the merge **re-ranks the union via the `:8086` reranker** (query+documents→score), with the §4b precedence ladder (curated/`shared` observations above raw private facts) as the ordering tiebreak.

- [ ] **Step 1: Write the failing fan-out test**

Append to `tests/memory/test_hindsight_provider.py`:

```python
class FakeReranker:
    """Reverses input order so we can prove the merge re-ranked the union."""

    async def rerank(self, query: str, documents: list[str]) -> list[dict]:
        n = len(documents)
        return [{"index": i, "relevance_score": float(n - i)} for i in range(n)]


@pytest.mark.asyncio
async def test_recall_fans_out_across_allowed_banks_and_merges():
    fake = FakeHindsightClient()
    await fake.retain(bank_id="shared", content="shared fact", document_id="d-shared", tags=[])
    await fake.retain(bank_id="private__hermes", content="private fact", document_id="d-priv", tags=[])
    await fake.retain(bank_id="private__other", content="other private", document_id="d-other", tags=[])

    p = HindsightProvider(client=fake, client_id="hermes", reranker=FakeReranker())
    out = await p.recall("fact", dataset="shared", client_id="hermes")

    banks_queried = {c["bank_id"] for c in fake.recalled}
    # Fans out to own-private + shared; NEVER another agent's private.
    assert banks_queried == {"shared", "private__hermes"}
    texts = {r["text"] for r in out}
    assert texts == {"shared fact", "private fact"}
    assert "other private" not in texts


@pytest.mark.asyncio
async def test_recall_merge_precedence_shared_observation_before_private_fact():
    fake = FakeHindsightClient()
    # shared observation (curated) must outrank a raw private fact (§4b).
    fake._facts_by_bank["shared"] = [{"document_id": "o1", "text": "obs", "type": "observation", "tags": []}]
    fake._facts_by_bank["private__hermes"] = [{"document_id": "f1", "text": "raw", "type": "experience", "tags": []}]

    p = HindsightProvider(client=fake, client_id="hermes", reranker=FakeReranker())
    out = await p.recall("anything", dataset="shared", client_id="hermes")
    assert out[0]["text"] == "obs"  # observation ranks first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/memory/test_hindsight_provider.py -k "fans_out or precedence" -v`
Expected: FAIL — the placeholder `recall` queries banks serially with no rerank/precedence ordering (precedence test fails; fan-out test may pass on bank set but precedence is unordered).

- [ ] **Step 3: Implement the fan-out + reranked merge**

In `src/hal0/memory/hindsight_provider.py`, replace the `recall` method with:

```python
    async def recall(self, query, *, types=None, max_tokens=4096, dataset=_SHARED, tags=None, client_id=None):
        """Fan out per-bank recall to the caller's allowed banks, merge under
        one token budget. Hindsight has no server-side cross-bank query and
        returns no numeric score, so we re-rank the union via the :8086
        reranker, with the §4b precedence ladder as the tiebreak.
        """
        import asyncio

        banks = [namespace_to_bank(ns) for ns in self._allowed_namespaces(dataset, client_id)]
        if not banks:
            return []

        async def _one(bank: str) -> list[dict[str, Any]]:
            resp = await self._client.recall(
                bank_id=bank, query=query, types=types, max_tokens=max_tokens, tags=tags
            )
            return [self._fact_to_item(f, bank) for f in resp.get("results", [])]

        per_bank = await asyncio.gather(*[_one(b) for b in banks])
        union: list[dict[str, Any]] = [item for bank_items in per_bank for item in bank_items]
        if not union:
            return []

        union = await self._rerank_union(query, union)
        union.sort(key=self._precedence_key)  # stable: precedence wins ties
        return self._apply_token_budget(union, max_tokens)

    @staticmethod
    def _precedence_key(item: dict[str, Any]) -> tuple[int, float]:
        """§4b ladder: shared/curated observations rank above raw private
        facts. Lower tuple sorts first. Second element is negative rerank
        score so higher score sorts earlier within the same tier.
        """
        is_observation = item.get("type") == "observation"
        is_shared = item.get("dataset") == _SHARED
        tier = 0 if (is_observation or is_shared) else 1
        return (tier, -float(item.get("score") or 0.0))

    async def _rerank_union(self, query: str, union: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._reranker is None or len(union) < 2:
            return union
        try:
            ranked = await self._reranker.rerank(query, [u["text"] for u in union])
        except Exception:
            return union  # reranker down → keep fused order (fail-soft)
        for entry in ranked:
            idx = entry.get("index")
            if isinstance(idx, int) and 0 <= idx < len(union):
                union[idx]["score"] = float(entry.get("relevance_score", 0.0))
        return union

    @staticmethod
    def _apply_token_budget(items: list[dict[str, Any]], max_tokens: int) -> list[dict[str, Any]]:
        """Greedy fill by ~4 chars/token on the text field (Hindsight counts
        only fact text toward the budget)."""
        out: list[dict[str, Any]] = []
        spent = 0
        for item in items:
            cost = max(1, len(item.get("text", "")) // 4)
            if spent + cost > max_tokens and out:
                break
            out.append(item)
            spent += cost
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/memory/test_hindsight_provider.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/hal0/memory/hindsight_provider.py tests/memory/test_hindsight_provider.py
git commit -m "feat(memory): HindsightProvider multi-bank recall fan-out + reranked merge (P1)"
```

## Task P1-4: Add `HindsightProvider` to the conformance suite + factory branch

**Files:**
- Modify: `tests/memory/test_provider_contract.py`
- Modify: `src/hal0/memory/__init__.py` (`provider_from_config` engine branch + degrade ladder)
- Test: `tests/memory/test_provider_factory.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/memory/test_provider_contract.py`:

```python
def _hindsight_factory():
    from hal0.memory.hindsight_provider import HindsightProvider
    from tests.memory.test_hindsight_provider import FakeHindsightClient

    return HindsightProvider(client=FakeHindsightClient(), client_id="alice")


@pytest.mark.slow
@pytest.mark.asyncio
async def test_hindsight_conforms_to_contract():
    p = _hindsight_factory()
    res = await p.add("hs note", dataset="shared")
    assert set(res) == {"id", "timestamp"}
    # Foreign-private read → empty.
    out = await p.search("note", dataset="private:bob", client_id="bob")
    assert out == []
    assert set(p.graph_status()) >= {"enabled", "route"}
    d = await p.delete([res["id"]])
    assert "deleted" in d
```

Append to `tests/memory/test_provider_factory.py`:

```python
def test_factory_returns_hindsight_when_engine_hindsight():
    with patch("hal0.memory.HindsightProvider", autospec=True) as mock_cls, \
         patch("hal0.memory._build_hindsight_client", return_value=object()):
        provider_from_config(_cfg("hindsight"))
        assert mock_cls.called


def test_factory_degrades_to_pgvector_when_hindsight_unavailable():
    from hal0.memory.pgvector_provider import PgVectorProvider

    with patch("hal0.memory._build_hindsight_client", side_effect=RuntimeError("no daemon")):
        provider = provider_from_config(_cfg("hindsight"))
        assert isinstance(provider, PgVectorProvider)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/memory/test_provider_factory.py -k "hindsight or degrades" -v`
Expected: FAIL — `provider_from_config` has no hindsight branch and `_build_hindsight_client` doesn't exist.

- [ ] **Step 3: Add the engine branch + degrade ladder**

In `src/hal0/memory/__init__.py`, add the hindsight import + a client builder, then extend the factory. Insert after the existing imports:

```python
from hal0.memory.hindsight_provider import HindsightProvider
from hal0.memory.pgvector_provider import PgVectorProvider
```

Add a client builder (kept separate so tests can patch it):

```python
def _build_hindsight_client(cfg: Any) -> Any:
    """Construct the Hindsight REST client from config + env.

    Raises if the daemon is unreachable so the factory can degrade. The
    actual httpx-backed client lives in hindsight_provider; this indirection
    exists purely so the boot-degrade path is unit-testable.
    """
    from hal0.memory.hindsight_client import HindsightRestClient

    return HindsightRestClient.from_env()
```

Replace the body of `provider_from_config` after the `cognee` branch:

```python
    if engine == "hindsight":
        try:
            client = _build_hindsight_client(cfg)
        except Exception as exc:  # daemon down at boot → degrade ladder
            log.warning("hal0.memory.hindsight_unavailable", error=str(exc), fallback="pgvector")
            return PgVectorProvider()
        return HindsightProvider(client=client)

    if engine == "pgvector":
        return PgVectorProvider()

    if engine == "mem0":  # documented fallback (spec §2) — not yet implemented
        log.warning("hal0.memory.mem0_not_implemented", fallback="cognee")
        return CogneeWrapper(embedding_model=str(embed.model))

    # cognee branch above is the default; unknown engines log + fall back.
    log.warning("hal0.memory.unknown_engine", engine=engine, fallback="cognee")
    return CogneeWrapper(embedding_model=str(embed.model))
```

Add `HindsightProvider`, `PgVectorProvider`, `_build_hindsight_client` to `__all__`.

> NOTE (verify): `src/hal0/memory/hindsight_client.py` (`HindsightRestClient.from_env()`) is built in the ops task P1-6 alongside the deploy (it needs the real port + env). For P1 unit tests, `_build_hindsight_client` is always patched, so the import is lazy (inside the function) and never executed in the default gate.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/memory/test_provider_factory.py tests/memory/test_provider_contract.py::test_hindsight_conforms_to_contract -m "slow or not slow" -v`
Expected: PASS (factory tests + the slow hindsight conformance test green)

- [ ] **Step 5: Commit**

```bash
git add src/hal0/memory/__init__.py tests/memory/test_provider_factory.py tests/memory/test_provider_contract.py
git commit -m "feat(memory): provider_from_config hindsight branch + pgvector degrade ladder (P1)"
```

## Task P1-5: `HindsightRestClient` — the real REST adapter

**Files:**
- Create: `src/hal0/memory/hindsight_client.py`
- Test: `tests/memory/test_hindsight_client.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/memory/test_hindsight_client.py`:

```python
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
        if request.url.path.endswith("/retain"):
            return httpx.Response(200, json={"success": True, "bank_id": "shared", "items_count": 1})
        return httpx.Response(200, json={"memory_units_deleted": 1})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9177") as http:
        client = HindsightRestClient(http_client=http, api_key="lemonade-local-noauth")
        await client.retain(bank_id="shared", content="x", document_id="d1")
        await client.recall(bank_id="shared", query="x")
        await client.delete_document(bank_id="shared", document_id="d1")

    assert ("POST", "/v1/default/banks/shared/retain") in seen
    assert ("POST", "/v1/default/banks/shared/recall") in seen
    # Delete is the documented delete_document path.
    assert any(m == "DELETE" and "/documents/d1" in p for m, p in seen)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/memory/test_hindsight_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hal0.memory.hindsight_client'`

- [ ] **Step 3: Write the client**

Create `src/hal0/memory/hindsight_client.py`:

```python
"""Async REST client for the shared hindsight-api (brain-redesign P1).

Talks to ``/v1/default/banks/{bank}/...`` (the bank-scoped REST surface the
spike confirmed). Auth is the single server-wide key when enabled; on the LAN
the daemon runs no-auth but Hindsight still requires a NON-EMPTY key, so we
default to the spike's ``lemonade-local-noauth`` placeholder.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:9177"  # dynamic port — pinned by the unit (P1-6)
DEFAULT_API_KEY = "lemonade-local-noauth"


class HindsightRestClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str = DEFAULT_API_KEY,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._api_key = api_key
        self._owns = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=self._base_url, timeout=httpx.Timeout(120.0, connect=3.0)
        )

    @classmethod
    def from_env(cls) -> "HindsightRestClient":
        base = os.environ.get("HAL0_HINDSIGHT_URL", DEFAULT_BASE_URL)
        key = os.environ.get("HINDSIGHT_API_TENANT_API_KEY", DEFAULT_API_KEY) or DEFAULT_API_KEY
        return cls(base_url=base, api_key=key)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    async def retain(self, *, bank_id, content, document_id, context=None, metadata=None, tags=None, timestamp=None):
        body: dict[str, Any] = {"content": content, "document_id": document_id}
        if context is not None:
            body["context"] = context
        if metadata:
            body["metadata"] = metadata
        if tags:
            body["tags"] = list(tags)
        if timestamp is not None:
            body["timestamp"] = timestamp
        resp = await self._http.post(f"/v1/default/banks/{bank_id}/retain", headers=self._headers(), json=body)
        resp.raise_for_status()
        return resp.json()

    async def recall(self, *, bank_id, query, types=None, max_tokens=4096, tags=None):
        body: dict[str, Any] = {"query": query, "max_tokens": max_tokens}
        if types:
            body["types"] = list(types)
        if tags:
            body["tags"] = list(tags)
        resp = await self._http.post(f"/v1/default/banks/{bank_id}/recall", headers=self._headers(), json=body)
        resp.raise_for_status()
        return resp.json()

    async def delete_document(self, *, bank_id, document_id):
        resp = await self._http.request(
            "DELETE", f"/v1/default/banks/{bank_id}/documents/{document_id}", headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    async def aclose(self) -> None:
        if self._owns:
            await self._http.aclose()
```

> NOTE (verify): the exact delete path (`/v1/default/banks/{bank}/documents/{document_id}`) is the documented `delete_document` operation (hindsight-docs `developer/api/documents.md`). Confirm the on-box daemon serves it under `/v1/default/...` (the spike confirmed the `/v1/default/banks/{bank}/...` prefix); adjust if the deployed version differs.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/memory/test_hindsight_client.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/hal0/memory/hindsight_client.py tests/memory/test_hindsight_client.py
git commit -m "feat(memory): HindsightRestClient REST adapter for /v1/default/banks (P1)"
```

## Task P1-6: Deploy the shared `hindsight-api` systemd unit  *(OPS CHECKLIST — not unit-testable)*

This task is an **operator runbook** (no red-green TDD loop; it stands up infra on CT 105). Be exact about config/paths/env. Folds in the spike's hard-won config (auto-memory `hal0_hindsight_hermes_spike`).

**Files:**
- Create: `installer/systemd/hindsight-api.service`
- Create: `docs/internal/brain-redesign/ops/hindsight-deploy.md`

- [ ] **Step 1: Pin the version + run the on-box pre-flight (spec §7, read-only)**

On CT 105 (`ssh hal0`), record into `docs/internal/brain-redesign/ops/hindsight-deploy.md`:
- Platform Cognee/sidecar row counts: `ls -la /var/lib/hal0/memory/cognee` + `sqlite3 /var/lib/hal0/memory/cognee/hal0_memory_index.sqlite "SELECT COUNT(*) FROM hal0_memory_items;"` (expect empty/stale → P2 migration is a no-op).
- Embed-slot model + dim vs `bge-small-en-v1.5` (384-d) — schedule a re-embed if different ([Q4]).
- Pin Hindsight version (probe-confirmed 2026-06-06): the spike venv ran `hindsight-all` /
  `hindsight-api-slim` / `hindsight-embed` **0.7.2**, `hindsight-client` **0.6.1**, embedded
  **Postgres 18.1.0**, alembic schema head **`c1d2e3f4a5b6`**. **Pin the shared platform deploy
  to `hindsight-api` 0.7.x with the same alembic head** so the schema is known-good; record the
  [Q5'] extraction/schema behaviour. (Storage on this build = single `public` schema + a
  `bank_id` discriminator column; a tenant-schema model also exists but is only relevant if the
  shared instance is run multi-tenant — we are not.)

- [ ] **Step 2: Create the data root + writable HF cache**

```bash
sudo install -d -o hal0 -g hal0 /var/lib/hal0/memory/hindsight
sudo install -d -o hal0 -g hal0 /var/lib/hal0/memory/hindsight/hf-cache
```

(Spike gotcha #2: the default HF cache symlinks to read-only `/mnt/ai-models` and dies downloading `bge-small-en-v1.5` — point `HF_HOME` at this hal0-writable dir.)

- [ ] **Step 3: Write the systemd unit**

Create `installer/systemd/hindsight-api.service`:

```ini
[Unit]
Description=hal0 shared Hindsight memory engine (platform brain)
After=network-online.target hal0-lemonade.service
Wants=network-online.target

[Service]
Type=simple
User=hal0
Group=hal0
# Spike gotcha #2 — writable HF cache (default symlinks to read-only /mnt/ai-models).
Environment=HF_HOME=/var/lib/hal0/memory/hindsight/hf-cache
# Embedded pg0 under the data root (NOT a separate PG daemon).
Environment=HINDSIGHT_API_DATA_DIR=/var/lib/hal0/memory/hindsight
# Spike gotcha #1 — a NON-EMPTY key is required even for no-auth lemond.
Environment=HINDSIGHT_API_LLM_API_KEY=lemonade-local-noauth
# Extraction LLM → lemond (instruct model; reasoning/rambling models time out — spike).
Environment=HINDSIGHT_API_LLM_PROVIDER=openai
Environment=HINDSIGHT_API_LLM_BASE_URL=http://127.0.0.1:13305
Environment=HINDSIGHT_API_LLM_MODEL=qwen3-it-4b-FLM
# Pin the bind so the provider/client don't chase the dynamic port (gotcha #3).
Environment=HINDSIGHT_API_PORT=9177
ExecStart=/var/lib/hal0/memory/hindsight/.venv/bin/hindsight-api serve
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: Install + enable + health-check**

```bash
sudo cp installer/systemd/hindsight-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hindsight-api.service
# Health (spike gotcha #3 — health is /health; capture the actual bound port if not 9177):
curl -fsS http://127.0.0.1:9177/health && echo OK
# Verify pg0 persists across restart:
sudo systemctl restart hindsight-api.service && sleep 5 && curl -fsS http://127.0.0.1:9177/health
```

- [ ] **Step 5: Resolve [Q5'] the FLM schema gap the standard way (NOT the wrap-patch)**

Per spec §6 [Q5'] + the standing "third-party official fix first" rule, resolve extraction-schema tolerance via, in order: (a) grammar-/schema-constrained extraction via lemond if available, (b) a larger instruct extraction model that honors `{"facts":[...]}`, or (c) if a tolerance shim is unavoidable, **file it upstream and pin the version** — do NOT carry an unversioned in-tree patch. Record the chosen path + upstream issue link in `hindsight-deploy.md`.

- [ ] **Step 6: Commit the unit + runbook**

```bash
git add installer/systemd/hindsight-api.service docs/internal/brain-redesign/ops/hindsight-deploy.md
git commit -m "ops(memory): shared hindsight-api systemd unit + deploy runbook (P1)"
```

## Task P1-7: Recall sanity check on a seeded fixture corpus  *(OPS/SMOKE — recorded, not gated)*

Per spec D2, this is a **sanity** check (no graded δ-eval, no Cognee baseline — the platform store is empty). It is recorded, not gated on a delta.

**Files:**
- Create: `tests/memory/fixtures/recall_corpus.jsonl` (seed corpus)
- Create: `scripts/memory/recall_sanity.py` (one-shot probe)

- [ ] **Step 1: Seed a small fixture corpus**

Create `tests/memory/fixtures/recall_corpus.jsonl` (~10 facts spanning 2 banks):

```jsonl
{"bank": "shared", "text": "hal0 runs its inference on a Strix Halo iGPU via Lemonade."}
{"bank": "shared", "text": "The hal0 memory engine was swapped from Cognee to Hindsight in v0.5."}
{"bank": "private__hermes", "text": "Hermes prefers concise, citation-backed answers."}
```

(Extend to ~10 lines covering the fixed query set below.)

- [ ] **Step 2: Write the probe script**

Create `scripts/memory/recall_sanity.py` that retains the corpus into the live `hindsight-api`, runs a fixed query set (e.g. "what hardware does hal0 use", "which memory engine does hal0 use"), and prints recalled facts + per-query latency. No assertions — output is recorded in `hindsight-deploy.md`.

- [ ] **Step 3: Run the probe on CT 105 + record results**

```bash
ssh hal0 'cd /opt/hal0 && python scripts/memory/recall_sanity.py'
```

Paste the on-topic results + latencies into `docs/internal/brain-redesign/ops/hindsight-deploy.md` under "Recall sanity (P1 exit part 2)".

- [ ] **Step 4: Commit**

```bash
git add tests/memory/fixtures/recall_corpus.jsonl scripts/memory/recall_sanity.py docs/internal/brain-redesign/ops/hindsight-deploy.md
git commit -m "test(memory): recall sanity fixture corpus + probe (P1 exit, recorded not gated)"
```

**P1 Exit:** (1) `HindsightProvider` + `PgVectorProvider` pass `test_provider_contract.py` unmodified; `hindsight-api` boots as a unit; pg0 persists across restart; embed/rerank/extraction health-checked. (2) Recall sanity recorded. **Rollback:** stop/mask the unit; default still Cognee; Hindsight data root is isolated.

---

# P2 — Cutover + re-enable the gate

*Flip the default to Hindsight, map namespaces→banks behind the ACL shim, add the `recall` route, turn memory ON, keep Cognee behind a one-release fallback.*

## Task P2-1: Rename `app.state.memory_wrapper` → `app.state.memory_provider`

**Files:**
- Modify: `src/hal0/api/__init__.py:1434-1526`
- Modify: `src/hal0/api/routes/memory.py:172`
- Modify: `src/hal0/api/routes/health.py:98`
- Modify: `src/hal0/api/agents/memory_stats.py:141`
- Modify: `src/hal0/api/mcp_mount.py:172-241`
- Test: `tests/api/test_memory_provider_rename.py` (create)

The full reader list (grepped repo-wide): `api/__init__.py`, `api/mcp_mount.py`, `api/agents/memory_stats.py:141`, `api/routes/health.py:98`, `api/routes/memory.py:172`.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_memory_provider_rename.py`:

```python
"""Cutover: app.state exposes memory_provider (P2)."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient


def test_app_state_has_memory_provider(monkeypatch):
    monkeypatch.setenv("HAL0_MEMORY_ENABLED", "1")
    from hal0.api import create_app

    app = create_app()
    # New canonical name present; old name gone.
    assert hasattr(app.state, "memory_provider")
    assert not hasattr(app.state, "memory_wrapper")


def test_health_memory_enabled_reads_provider(monkeypatch):
    monkeypatch.setenv("HAL0_MEMORY_ENABLED", "1")
    from hal0.api import create_app

    with TestClient(create_app()) as client:
        body = client.get("/api/status").json()
        assert "memory_enabled" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/test_memory_provider_rename.py -v`
Expected: FAIL — `app.state.memory_wrapper` still exists / `memory_provider` absent.

- [ ] **Step 3: Rename across all readers**

In `src/hal0/api/__init__.py`, change the construction block (lines 1434-1494) to build via the factory and store under the new name. Replace the `else:` branch body (lines 1448-1494) with:

```python
    else:
        try:
            from hal0.config.loader import load_hal0_config
            from hal0.memory import provider_from_config

            memory_provider = provider_from_config(load_hal0_config())
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("hal0.memory.init_failed", error=str(exc))
```

Rename the local `memory_wrapper` → `memory_provider` (lines 1434, 1494, 1504-1524) and the assignment to `app.state.memory_provider = memory_provider`. Update the `mount_mcp_servers(..., memory_wrapper=memory_provider, ...)` call to `memory_provider=memory_provider`.

In the other readers, change `getattr(request.app.state, "memory_wrapper", None)` → `"memory_provider"`:
- `src/hal0/api/routes/memory.py:172` (`_wrapper` → rename to `_provider`, keep callers).
- `src/hal0/api/routes/health.py:98`.
- `src/hal0/api/agents/memory_stats.py:141`.

In `src/hal0/api/mcp_mount.py`, rename the `memory_wrapper` parameter (lines 172, 221, 225, 241) → `memory_provider`.

> NOTE (verify): `mcp_mount.py:225` passes `wrapper=memory_wrapper` into `build_server(wrapper=...)` — `build_server`'s param stays `wrapper` (it's engine-neutral `Any`); only the local variable/param name changes. Leave `hal0.mcp.memory.build_server`'s signature untouched.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/test_memory_provider_rename.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/hal0/api/__init__.py src/hal0/api/routes/memory.py src/hal0/api/routes/health.py src/hal0/api/agents/memory_stats.py src/hal0/api/mcp_mount.py tests/api/test_memory_provider_rename.py
git commit -m "refactor(api): rename memory_wrapper → memory_provider; build via factory (P2)"
```

## Task P2-2: `POST /api/memory/recall` route + `add`→`retain` confirmation

**Files:**
- Modify: `src/hal0/api/routes/memory.py` (add `recall` route)
- Test: `tests/memory/test_recall_route.py` (create)

`/api/memory/*` is the Cognee-era CRUD contract. Hindsight's value is `recall` (token-budgeted, observation hierarchy). Without a `recall` route the milestone silently ships "a better vector store". So: add `POST /api/memory/recall` the plugins call, and confirm `HindsightProvider.add` routes to `retain` (background consolidation) — which Task P1-2 already does.

- [ ] **Step 1: Write the failing route test**

Create `tests/memory/test_recall_route.py`:

```python
"""POST /api/memory/recall route (P2)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hal0.api.routes.memory import router
from tests.memory.fakes import FakeMemoryProvider


class RecordingProvider(FakeMemoryProvider):
    def __init__(self):
        super().__init__(client_id="anonymous")
        self.recall_calls = []

    async def recall(self, query, *, types=None, max_tokens=4096, dataset="shared", tags=None, client_id=None):
        self.recall_calls.append({"query": query, "max_tokens": max_tokens})
        return [{"id": "d1", "text": "recalled", "timestamp": "2026-06-06T00:00:00+00:00",
                 "dataset": "shared", "tags": [], "source": None, "metadata": {}, "score": None}]


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/memory")
    app.state.memory_provider = RecordingProvider()
    return TestClient(app)


def test_recall_route_returns_items(client):
    resp = client.post("/api/memory/recall", json={"query": "what do I know", "max_tokens": 2048})
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"][0]["text"] == "recalled"
    assert client.app.state.memory_provider.recall_calls[0]["max_tokens"] == 2048


def test_recall_requires_query(client):
    resp = client.post("/api/memory/recall", json={})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/memory/test_recall_route.py -v`
Expected: FAIL with 404 (no `/recall` route).

- [ ] **Step 3: Add the route**

In `src/hal0/api/routes/memory.py`, after `memory_search` (line 407), add:

```python
@router.post("/recall")
async def memory_recall(request: Request) -> dict[str, Any]:
    """Token-budgeted recall (Hindsight's preferred path).

    Body: ``{query, max_tokens?, types?, dataset?, tags?}``. Identity +
    namespace resolution behave like ``/search`` (X-hal0-Agent +
    X-hal0-Private). Returns ``{items: [MemoryItem, ...]}`` ordered by
    relevance (no numeric score — Hindsight recall returns none).

    Falls back to ``search`` semantics on engines without a richer recall
    (the ABC default), so this route is safe regardless of active engine.
    """
    body = await _read_json_body(request)
    query = body.get("query")
    if not isinstance(query, str) or not query:
        raise Hal0Error(
            "memory_recall requires 'query' (non-empty string)",
            details={"path": "/api/memory/recall"},
        )
    agent_id = _agent_id(request)
    private = _is_private(request)
    try:
        dataset = resolve_read_datasets(
            body.get("dataset"),
            private=private,
            client_id=agent_id if agent_id != "anonymous" else None,
        )
    except MemoryNamespaceError as exc:
        raise MemoryNamespaceInvalid(str(exc)) from exc

    provider = _provider(request)
    items = await provider.recall(
        query=query,
        types=body.get("types"),
        max_tokens=int(body.get("max_tokens", 4096)),
        dataset=dataset,
        tags=body.get("tags") or [],
        client_id=agent_id if agent_id != "anonymous" else None,
    )
    return {"items": items}
```

> NOTE (verify): Task P2-1 renames `_wrapper(request)` → `_provider(request)`. If executing P2-2 before that rename lands, use `_wrapper`. The route uses `_provider` assuming P2-1 is merged first (P2 tasks are ordered).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/memory/test_recall_route.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/hal0/api/routes/memory.py tests/memory/test_recall_route.py
git commit -m "feat(api): POST /api/memory/recall route (Hindsight preferred path) (P2)"
```

## Task P2-3: MCP `recall` tool

**Files:**
- Modify: `src/hal0/mcp/memory.py` (add `_memory_recall` handler + register)
- Test: `tests/mcp/test_memory_recall_tool.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/mcp/test_memory_recall_tool.py`:

```python
"""MCP memory_recall tool (P2)."""

from __future__ import annotations

import pytest

from hal0.mcp.memory import make_dispatcher
from tests.memory.fakes import FakeMemoryProvider


class RecallProvider(FakeMemoryProvider):
    async def recall(self, query, *, types=None, max_tokens=4096, dataset="shared", tags=None, client_id=None):
        return [{"id": "d1", "text": "from-recall", "timestamp": "t", "dataset": "shared",
                 "tags": [], "source": None, "metadata": {}, "score": None}]


@pytest.mark.asyncio
async def test_memory_recall_tool_dispatches():
    dispatch = make_dispatcher(RecallProvider(client_id="alice"))
    out = await dispatch("memory_recall", {"query": "hi", "max_tokens": 512})
    assert out["status"] == "ok"
    assert out["results"][0]["text"] == "from-recall"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/mcp/test_memory_recall_tool.py -v`
Expected: FAIL — `memory_recall` not in `_MEMORY_HANDLERS` → `mcp.unknown_memory_tool`.

- [ ] **Step 3: Add the handler + register it**

In `src/hal0/mcp/memory.py`, add a handler after `_memory_search` (line 271):

```python
async def _memory_recall(
    wrapper: Any,
    args: dict[str, Any],
    *,
    client_id: str | None,
    private: bool,
) -> dict[str, Any]:
    """memory_recall(query, max_tokens=4096, types?, dataset?, tags?) → {results}.

    The Hindsight-preferred retrieval path: token-budgeted, observation
    hierarchy, no numeric score. Provider.recall falls back to search on
    engines without a richer recall (ABC default), so this tool is safe
    regardless of active engine.
    """
    query = _require(args, "query", str)
    if not query.strip():
        raise MemorySchemaError("query must be non-empty")
    max_tokens = args.get("max_tokens", 4096)
    if not isinstance(max_tokens, int) or max_tokens < 1 or max_tokens > 32768:
        raise MemorySchemaError("max_tokens must be 1..32768")
    requested = args.get("dataset")
    if isinstance(requested, list):
        dataset: Any = [str(d) for d in requested]
    elif requested is None or (isinstance(requested, str) and not requested):
        dataset = ["shared", f"private:{client_id}"] if private and client_id else _DEFAULT_DATASET
    elif isinstance(requested, str):
        dataset = _resolve_dataset(requested, private=private, client_id=client_id)
    else:
        raise MemorySchemaError("dataset must be str | list[str] | null")
    tags = _normalise_tags(args.get("tags"))
    types = args.get("types")
    results = await wrapper.recall(
        query=query, types=types, max_tokens=max_tokens, dataset=dataset, tags=tags, client_id=client_id
    )
    return {"results": list(results)}
```

Add to `_MEMORY_HANDLERS` (line 331):

```python
    "memory_recall": _memory_recall,
```

Add an annotation in `_ANNOTATIONS` (line 400) and register it in `build_server` (after the `memory_search` registration, line 455):

```python
    _register("memory_recall", "Recall token-budgeted, consolidated memory (preferred over search).")
```

with annotation:

```python
    "memory_recall": ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/mcp/test_memory_recall_tool.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/hal0/mcp/memory.py tests/mcp/test_memory_recall_tool.py
git commit -m "feat(mcp): memory_recall tool (Hindsight preferred path) (P2)"
```

## Task P2-4: `hal0 memory migrate --dry-run`

**Files:**
- Create/Modify: the `hal0 memory` CLI group (find via `grep -rn "memory" src/hal0/cli/`)
- Test: `tests/cli/test_memory_migrate.py` (create)

Per spec [Q10]: the platform Cognee store has been dark since v0.4, so migration is **likely a no-op**. The command first measures, then dry-runs the row mapping.

- [ ] **Step 1: Write the failing test**

Create `tests/cli/test_memory_migrate.py`:

```python
"""hal0 memory migrate --dry-run (P2). No-op on empty/stale Cognee store."""

from __future__ import annotations

from hal0.memory.migrate import migrate_cognee_to_hindsight_dryrun


def test_dry_run_reports_zero_on_empty_store(tmp_path):
    # No sidecar file → empty store → no-op.
    report = migrate_cognee_to_hindsight_dryrun(cognee_dir=tmp_path)
    assert report == {"rows_total": 0, "rows_mapped": 0, "rows_unmapped": 0, "noop": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cli/test_memory_migrate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hal0.memory.migrate'`

- [ ] **Step 3: Write the dry-run mapper**

Create `src/hal0/memory/migrate.py`:

```python
"""Cognee → Hindsight migration (brain-redesign P2, [Q10]).

The platform Cognee store has been dark since v0.4 (memory OFF), so this is
likely a no-op. The dry-run reads the sidecar SQLite (the canonical filter
source) and reports rows mapped/unmapped without touching Hindsight. Cognee
data stays read-only.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from hal0.memory.hindsight_provider import namespace_to_bank


def migrate_cognee_to_hindsight_dryrun(*, cognee_dir: str | Path) -> dict[str, Any]:
    sidecar = Path(cognee_dir) / "hal0_memory_index.sqlite"
    if not sidecar.exists():
        return {"rows_total": 0, "rows_mapped": 0, "rows_unmapped": 0, "noop": True}
    with sqlite3.connect(sidecar) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, dataset FROM hal0_memory_items").fetchall()
    total = len(rows)
    if total == 0:
        return {"rows_total": 0, "rows_mapped": 0, "rows_unmapped": 0, "noop": True}
    mapped = 0
    for row in rows:
        bank = namespace_to_bank(row["dataset"])
        if bank:
            mapped += 1
    return {
        "rows_total": total,
        "rows_mapped": mapped,
        "rows_unmapped": total - mapped,
        "noop": False,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cli/test_memory_migrate.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Wire the CLI subcommand**

Add `hal0 memory migrate --dry-run` to the `hal0 memory` CLI group, calling `migrate_cognee_to_hindsight_dryrun(cognee_dir="/var/lib/hal0/memory/cognee")` and printing the report. A live `--apply` (copy-into-Hindsight + verify count + spot recall parity) is gated behind a non-empty dry-run; since the store is expected empty, ship `--dry-run` first.

> NOTE (verify): locate the existing `hal0 memory` Click/Typer group (`grep -rn "memory" src/hal0/cli/`) and add the subcommand in the repo's established CLI style. If no `memory` group exists yet, the command lands under `hal0 memory`.

- [ ] **Step 6: Commit**

```bash
git add src/hal0/memory/migrate.py tests/cli/test_memory_migrate.py src/hal0/cli/
git commit -m "feat(cli): hal0 memory migrate --dry-run (Cognee→Hindsight, no-op on empty) (P2)"
```

## Task P2-5: Flip the default engine → `hindsight`

**Files:**
- Modify: `src/hal0/memory/__init__.py` (`provider_from_config` default)
- Test: `tests/memory/test_provider_factory.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/memory/test_provider_factory.py`:

```python
def test_factory_default_engine_is_hindsight_after_cutover():
    from types import SimpleNamespace
    # cfg with NO engine field → factory default must now be hindsight.
    cfg = SimpleNamespace(memory=SimpleNamespace(
        embedding=SimpleNamespace(model="m", rerank_enabled=False, rerank_url="u",
                                  rerank_over_fetch_factor=5, rerank_max_candidates=500,
                                  rerank_connect_timeout_s=1.0, rerank_read_timeout_s=8.0),
        graph=SimpleNamespace(enabled=False, route="upstream")))
    with patch("hal0.memory.HindsightProvider", autospec=True) as mock_cls, \
         patch("hal0.memory._build_hindsight_client", return_value=object()):
        provider_from_config(cfg)
        assert mock_cls.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/memory/test_provider_factory.py::test_factory_default_engine_is_hindsight_after_cutover -v`
Expected: FAIL — default resolves to `cognee`.

- [ ] **Step 3: Flip the default**

In `src/hal0/memory/__init__.py`, change the engine resolution line in `provider_from_config`:

```python
    engine = str(getattr(cfg.memory, "engine", "hindsight") or "hindsight").lower()
```

> NOTE (verify): `MemoryConfig.engine` (P1-1) defaults to `"cognee"` at the schema level. The fallback flag (spec) is `[memory] engine = "cognee"` → reverts. The factory's `getattr` default to `"hindsight"` only applies to a config object that lacks the field entirely (test doubles). On a real loaded config the schema default wins, so **also flip the schema default**: change `MemoryConfig.engine`'s `default="cognee"` → `default="hindsight"` in `src/hal0/config/schema.py`. Update `tests/config/test_memory_engine_field.py::test_engine_defaults_to_cognee` to assert `"hindsight"` and rename it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/memory/test_provider_factory.py tests/config/test_memory_engine_field.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/hal0/memory/__init__.py src/hal0/config/schema.py tests/memory/test_provider_factory.py tests/config/test_memory_engine_field.py
git commit -m "feat(memory): cutover default engine cognee → hindsight; cognee = fallback flag (P2)"
```

## Task P2-6: Flip `HAL0_MEMORY_ENABLED=1`  *(OPS + template)*

**Files:**
- Modify: `installer/install.sh:527` (uncomment the template line)
- Modify (on box): `/etc/hal0/api.env` + systemd reload (running instance)

The gate default is NOT in `installer/api.env` (that file does not exist in-repo) — it is the heredoc template at `installer/install.sh:520-531`, which writes `/etc/hal0/api.env` at install time with `# HAL0_MEMORY_ENABLED=1` commented. **Two places must change**: the template (new installs) AND the running box's already-generated `/etc/hal0/api.env` (the template alone won't flip a live box).

- [ ] **Step 1: Uncomment the install template line**

In `installer/install.sh` lines 523-527, change:

```bash
# Memory subsystem (Cognee engine + /mcp/memory + the Agent → Memory tab)
# is deferred in this release and ships disabled by default. Uncomment to
# reintroduce it — no other change needed; the dashboard Agent nav returns
# automatically once /api/status reports it live.
# HAL0_MEMORY_ENABLED=1
```

to:

```bash
# Memory subsystem (Hindsight engine + /mcp/memory + the Agent → Memory tab)
# is ENABLED by default as of v0.5 (brain re-enablement). Comment out to
# ship with memory dark.
HAL0_MEMORY_ENABLED=1
```

- [ ] **Step 2: Flip the running CT 105 box (Tier-2 verify-first)**

```bash
# Verify current state first:
grep -n HAL0_MEMORY_ENABLED /etc/hal0/api.env
# Set it live + reload:
sudo sed -i 's/^# *HAL0_MEMORY_ENABLED=1/HAL0_MEMORY_ENABLED=1/' /etc/hal0/api.env
grep -q '^HAL0_MEMORY_ENABLED=1' /etc/hal0/api.env || echo 'HAL0_MEMORY_ENABLED=1' | sudo tee -a /etc/hal0/api.env
sudo systemctl restart hal0-api.service
curl -fsS http://127.0.0.1:8080/api/status | python -c "import sys,json; print(json.load(sys.stdin).get('memory_enabled'))"
# Expect: True
```

- [ ] **Step 3: Commit the template change**

```bash
git add installer/install.sh
git commit -m "ops(memory): enable HAL0_MEMORY_ENABLED=1 by default (v0.5 brain re-enablement) (P2)"
```

**P2 Exit:** Migration within threshold (or no-op); default boot uses Hindsight; `add/search/list/delete` green over both transports; namespace isolation + `private:` rejection + foreign-private fail-open-empty pass against the live engine; gate is ON; fallback flag cleanly reverts to the untouched Cognee store. **Rollback:** set `[memory] engine = "cognee"` + restart → instant revert (Cognee never mutated).

---

# P5-H — Hermes convergence

*Make Hermes use the one shared brain as its single source of truth — storage AND cognitive — and retire the spike's `local_embedded` instance.*

## Task P5H-1: Rename the plugin `hal0-cognee` → `hal0-memory` (`memory_cognee` → `memory_hindsight`)

**Files:**
- Create: `src/hal0/agents/hermes/plugins/memory_hindsight/` (move of `memory_cognee/`)
- Modify: `src/hal0/agents/hermes/driver.py:55` (plugin-tree reference)
- Create (rename): `tests/agents/hermes_plugins/test_memory_hindsight_provider.py`

- [ ] **Step 1: Write the failing rename test**

Create `tests/agents/hermes_plugins/test_memory_hindsight_provider.py`:

```python
"""Renamed hal0-memory Hermes plugin (P5-H)."""

from __future__ import annotations

import pytest

from hal0.agents.hermes.plugins.memory_hindsight.provider import Hal0MemoryProvider


def test_provider_name_is_hal0_memory():
    assert Hal0MemoryProvider().name == "hal0-memory"


def test_no_dataset_field_ever_sent():
    # The #317 contract: the client never sends a dataset key.
    from hal0.agents.hermes.plugins.memory_hindsight._client import Hal0MemoryClient

    import inspect
    src = inspect.getsource(Hal0MemoryClient.add)
    assert '"dataset"' not in src and "'dataset'" not in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/agents/hermes_plugins/test_memory_hindsight_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hal0.agents.hermes.plugins.memory_hindsight'`

- [ ] **Step 3: Rename the package + class + plugin name**

```bash
git mv src/hal0/agents/hermes/plugins/memory_cognee src/hal0/agents/hermes/plugins/memory_hindsight
```

In `src/hal0/agents/hermes/plugins/memory_hindsight/provider.py`:
- Rename `class Hal0CogneeProvider` → `class Hal0MemoryProvider`.
- Change `def name(self) -> str: return "hal0-cognee"` → `return "hal0-memory"`.
- Replace remaining `hal0-cognee` strings (system_prompt_block text, log prefixes) with `hal0-memory`.

In `src/hal0/agents/hermes/plugins/memory_hindsight/__init__.py`:
- `from .provider import Hal0MemoryProvider`; `register` registers `Hal0MemoryProvider()`.

In `src/hal0/agents/hermes/plugins/memory_hindsight/plugin.yaml`:
- `name: hal0-memory`; update the description to reference Hindsight.

In `src/hal0/agents/hermes/plugins/memory_hindsight/README.md`:
- Retitle `# hal0-memory`; update the contract table `Plugin name` → `hal0-memory`; update the dir paths to `memory_hindsight/` and the deploy target `$HERMES_HOME/plugins/memory/hal0-memory/`.

In `src/hal0/agents/hermes/driver.py:55`, change the comment/reference `memory_cognee` → `memory_hindsight`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/agents/hermes_plugins/test_memory_hindsight_provider.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add -A src/hal0/agents/hermes/plugins/ src/hal0/agents/hermes/driver.py tests/agents/hermes_plugins/test_memory_hindsight_provider.py
git rm tests/agents/hermes_plugins/test_memory_cognee_provider.py 2>/dev/null || true
git commit -m "refactor(hermes): rename hal0-cognee plugin → hal0-memory (memory_hindsight) (P5-H)"
```

## Task P5H-2: Wire `prefetch`→`recall` and `sync_turn`/`on_memory_write`→`retain`

**Files:**
- Modify: `src/hal0/agents/hermes/plugins/memory_hindsight/_client.py` (add `recall`)
- Modify: `src/hal0/agents/hermes/plugins/memory_hindsight/provider.py` (`prefetch` → recall depth)
- Test: `tests/agents/hermes_plugins/test_memory_hindsight_provider.py` (extend)

Per spec P5-H: `prefetch(query)` → `recall(types=['observation','world'], max_tokens=…)` instead of flat `search(limit=5)`; `sync_turn`/`on_memory_write` → Hindsight `retain` (which `HindsightProvider.add` already routes to). **Depends on the P2 `recall` route** — the plugin must call `recall`, not `search`.

- [ ] **Step 1: Write the failing test**

Append to `tests/agents/hermes_plugins/test_memory_hindsight_provider.py`:

```python
@pytest.mark.asyncio
async def test_client_recall_hits_recall_route():
    import httpx

    seen: list[tuple[str, str, dict]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        import json
        seen.append((request.method, request.url.path, json.loads(request.content or b"{}")))
        return httpx.Response(200, json={"items": [{"text": "obs"}]})

    from hal0.agents.hermes.plugins.memory_hindsight._client import Hal0MemoryClient

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://x") as http:
        client = Hal0MemoryClient(http_client=http)
        await client.recall("what do I know", types=["observation", "world"], max_tokens=2048)

    assert seen[0][0] == "POST" and seen[0][1] == "/api/memory/recall"
    assert seen[0][2]["types"] == ["observation", "world"]
    # The #317 contract still holds — no dataset key.
    assert "dataset" not in seen[0][2]


def test_prefetch_uses_recall_not_search():
    import inspect
    from hal0.agents.hermes.plugins.memory_hindsight.provider import Hal0MemoryProvider

    src = inspect.getsource(Hal0MemoryProvider.prefetch)
    assert ".recall(" in src and ".search(" not in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/agents/hermes_plugins/test_memory_hindsight_provider.py -k "recall or prefetch" -v`
Expected: FAIL — `_client.py` has no `recall`; `prefetch` still calls `.search`.

- [ ] **Step 3: Add `recall` to the client + rewire `prefetch`**

In `src/hal0/agents/hermes/plugins/memory_hindsight/_client.py`, add a `recall` method beside `search`:

```python
    async def recall(
        self,
        query: str,
        *,
        types: list[str] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """POST /api/memory/recall — token-budgeted, consolidated recall.

        Hindsight's preferred path (observation hierarchy). Omits ``dataset``
        by design — the server resolves the namespace from ``X-hal0-Agent``
        (the #317 contract).
        """
        payload: dict[str, Any] = {"query": query, "max_tokens": int(max_tokens)}
        if types is not None:
            payload["types"] = list(types)
        return await self._request("POST", "/api/memory/recall", json=payload)
```

In `src/hal0/agents/hermes/plugins/memory_hindsight/provider.py`, change `prefetch` to call `recall`:

```python
    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if not query or self._client is None:
            return ""
        try:
            result = asyncio.run(
                self._client.recall(query, types=["observation", "world"], max_tokens=2048)
            )
        except Hal0MemoryClientError as exc:
            logger.debug("hal0-memory prefetch transport failure: %s", exc)
            return ""
        except RuntimeError as exc:
            logger.debug("hal0-memory prefetch asyncio drift: %s", exc)
            return ""

        items = result.get("items") if isinstance(result, dict) else None
        if not items:
            return ""
        lines = []
        for item in items:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if text:
                    lines.append(f"- {text}")
        if not lines:
            return ""
        return "## hal0-memory recall\n" + "\n".join(lines)
```

`sync_turn` + `on_memory_write` already call `self._client.add(...)`, which lands on `/api/memory/add` → `HindsightProvider.add` → `retain`. No change needed there beyond the rename done in P5H-1 (verify the `tags=["chat", "hermes"]` calls remain).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/agents/hermes_plugins/test_memory_hindsight_provider.py -k "recall or prefetch" -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/hal0/agents/hermes/plugins/memory_hindsight/_client.py src/hal0/agents/hermes/plugins/memory_hindsight/provider.py tests/agents/hermes_plugins/test_memory_hindsight_provider.py
git commit -m "feat(hermes): prefetch→recall, sync_turn→retain via hal0-memory plugin (P5-H)"
```

## Task P5H-3: Set Hermes `config.yaml` `memory.provider = hal0-memory` + retire `local_embedded`  *(OPS CHECKLIST)*

Ops task on CT 105 (no unit test). Exact files from auto-memory `hal0_hindsight_hermes_spike`.

**Files / artifacts (on box) — probe-confirmed paths:**
- `/var/lib/hal0/.hermes/config.yaml` (canonical `HERMES_HOME`; flip `provider:` — guard a)
- `/var/lib/hal0/venvs/hermes/` (the venv — `pip uninstall hindsight-all hindsight-api-slim hindsight-embed hindsight-client` — guard b)
- `/var/lib/hal0/.hermes/hindsight/config.json` (remove — whole dir)
- `/etc/systemd/system/hal0-agent@hermes.service.d/20-hindsight.conf` (+`.bak.2026-06-04`) (remove; **keep** `21-hermes-subpackages.conf`)
- `/usr/local/sbin/hal0-hindsight-wrap-patch.py` + `/usr/local/sbin/hal0-hindsight-killgrace-patch.py` (remove both ExecStartPre hooks)
- `/var/lib/hal0/.pg0/instances/hindsight-embed-hermes/data` (init-orphaned Postgres 18.1.0 — stop explicitly, then `rm -rf /var/lib/hal0/.pg0`, 61 MB)
- `/var/lib/hal0/.hermes/hf-cache` (embedding-model cache, 216 MB — reclaim)
- Revert backups (for rollback): `config.yaml.bak-pre-hindsight-*`, `.env.bak-pre-hindsight-*`

- [ ] **Step 1: Point Hermes at the renamed plugin**

Set `memory.provider: hal0-memory` in `/var/lib/hal0/.hermes/config.yaml` (via `hermes_cli.config` save_config, run AS hal0 — never as root, spike gotcha #5). Hermes memory now flows `hal0-memory plugin → /api/memory/* (ACL + namespace) → HindsightProvider → shared hindsight-api`, landing in `private:hermes` + `shared`.

> **Probe-confirmed (2026-06-06).** The spike is *dormant, not retired*: `provider: hindsight`
> is still set (`config.yaml:315`) AND the embedded **Postgres 18.1.0** is still running
> (pid orphaned to init, `127.0.0.1:5432`). There are **TWO independent respawn guards** —
> `hindsight_embed/daemon_embed_manager.py` lazily re-spawns pg + `hindsight-api` on the
> next retain/recall if *either* (a) `memory.provider` still names `hindsight`, OR (b)
> `hindsight-embed` is still installed. Both must go, provider flipped FIRST (Step 1). The
> orphaned pg is reparented to **init** — restarting the Hermes unit will NOT kill it; it
> must be stopped explicitly (Step 4). Correct venv = `/var/lib/hal0/venvs/hermes/`.

- [ ] **Step 2: Retire `local_embedded` — uninstall ALL hindsight packages (respawn guard b)**

```bash
# Guard (b): uninstall the full set — `hindsight-all` is a meta-pkg and does NOT cascade to
# `hindsight-embed`, which is the actual respawn launcher. All four must go.
sudo -u hal0 /var/lib/hal0/venvs/hermes/bin/pip uninstall -y \
  hindsight-all hindsight-api-slim hindsight-embed hindsight-client
# Confirm the binaries are gone:
ls /var/lib/hal0/venvs/hermes/bin/ | grep -i hindsight   # expect: no output
```

- [ ] **Step 3: Remove the spike's config + systemd drop-in + BOTH patch scripts**

```bash
sudo rm -f /var/lib/hal0/.hermes/hindsight/config.json   # whole hindsight/ dir is just this
sudo rm -f /etc/systemd/system/hal0-agent@hermes.service.d/20-hindsight.conf \
           /etc/systemd/system/hal0-agent@hermes.service.d/20-hindsight.conf.bak.2026-06-04
# KEEP 21-hermes-subpackages.conf — that is the unrelated hermes_cli packaging fix (#34701).
sudo rm -f /usr/local/sbin/hal0-hindsight-wrap-patch.py \
           /usr/local/sbin/hal0-hindsight-killgrace-patch.py   # BOTH ExecStartPre patch hooks
sudo systemctl daemon-reload
```

- [ ] **Step 4: Stop the init-orphaned embedded pg + reclaim disk**

```bash
# The embedded pg (pid was 9858 at probe time; re-find it) is reparented to init and is NOT
# tied to the hermes unit — it survives a unit restart. Stop it explicitly, then delete.
PGDATA=/var/lib/hal0/.pg0/instances/hindsight-embed-hermes/data
sudo -u hal0 /var/lib/hal0/.pg0/installation/18.1.0/bin/pg_ctl stop -D "$PGDATA" -m fast || \
  sudo pkill -f 'postgres -D .*hindsight-embed-hermes'
sudo rm -rf /var/lib/hal0/.pg0                      # 61 MB — bundled pg binaries + the embed instance
sudo rm -rf /var/lib/hal0/.hermes/hf-cache          # 216 MB — embedding-model cache pulled by the embedded API
```

- [ ] **Step 5: [Q8] Confirm NO daemon re-spawns (both guards verified)**

After both guards are removed, restart the Hermes unit, run a memory turn, and confirm nothing re-spawns:

```bash
sudo systemctl restart hal0-agent@hermes.service
sudo -u hal0 hermes chat <<<'remember: smoke test of the shared brain
exit'                                               # exercises retain/recall via the new provider
# Expect: NO hindsight-api spawned from the hermes venv, NO embedded pg back on :5432.
ps aux | grep -i 'hindsight\|hindsight-embed' | grep -v grep   # expect: empty
ss -ltnp | grep ':5432'                                        # expect: empty (embedded pg gone)
# The ONLY hindsight that should be listening is the shared platform unit from P1-6.
```

- [ ] **Step 6: Record the outcome** in `docs/internal/brain-redesign/ops/hindsight-deploy.md` under "P5-H local_embedded retirement" (note both guards removed, pg stopped, disk reclaimed).

## Task P5H-4: Lock the canonical Hermes config against the root-clobber regression  *(OPS CHECKLIST)*

Per spec P5-H + auto-memory `hermes_home_migration_splitbrain` (spike gotcha #5): running hermes as root rewrites `config.yaml` to `root:root 0600` and silently falls back to the default provider.

- [ ] **Step 1: Verify the self-guarding wrapper is in place**

```bash
head -20 /usr/local/bin/hermes   # must re-exec as hal0 from a hal0-traversable cwd + export HF_HOME
ls -la /usr/local/bin/hermes.bak-pre-selfguard 2>/dev/null  # backup from the durable fix
```

- [ ] **Step 2: Verify + repair ownership**

```bash
stat -c '%U:%G %a' /var/lib/hal0/.hermes/config.yaml   # expect hal0:hal0 (NOT root:root 0600)
sudo chown hal0:hal0 /var/lib/hal0/.hermes/config.yaml
```

- [ ] **Step 3: Smoke — a root TUI session must NOT clobber the config**

```bash
# Launch hermes as root (the self-guard should re-exec as hal0); on exit, re-check:
sudo hermes chat <<<'exit' || true
stat -c '%U:%G %a' /var/lib/hal0/.hermes/config.yaml   # still hal0:hal0
grep -n 'provider' /var/lib/hal0/.hermes/config.yaml   # still hal0-memory
```

- [ ] **Step 4: Record the verification** in `hindsight-deploy.md`.

## Task P5H-5: Add the §4b ground-truth precedence stanza to SOUL.md (cognitive source of truth)

**Files:**
- Modify (deployed): `/var/lib/hal0/.hermes/SOUL.md` (canonical, under `HERMES_HOME`)
- Modify (in-repo template, if present): `src/hal0/agents/hermes/templates/SOUL.md`

SOUL.md is written under `HERMES_HOME` (driver.py:315) — it is a deployed identity doc, not a checked-in source file in the main tree. Add the precedence ladder so Hermes *trusts* recalled memory instead of re-deriving (spec §4b).

- [ ] **Step 1: Locate the canonical SOUL.md + any in-repo template**

```bash
ls -la /var/lib/hal0/.hermes/SOUL.md
grep -rln "SOUL.md\|ground-truth\|precedence" src/hal0/agents/hermes/ installer/
```

> NOTE (verify): if hal0 ships a SOUL.md *template* in-repo (so the stanza is provisioned on fresh installs), edit that template too. If SOUL.md is only ever authored on-box, this task edits the deployed file and the change is recorded in the runbook. The spike found SOUL.md at `/var/lib/hal0/.hermes/SOUL.md`.

- [ ] **Step 2: Append the precedence stanza**

Add to SOUL.md:

```markdown
## Ground-truth precedence (shared brain)

When sources conflict, rank them in this order — higher always wins:

1. **Safety / identity rules** (this SOUL, the rulebook, CLAUDE.md-class) — never overridden by a recalled memory.
2. **Live system / tool state** (terminal output, tool results) — what is true *now*.
3. **Recalled memory (shared brain)** — authoritative for project knowledge/decisions, **above your model priors**. Trust the recalled block; do not re-derive what it already states.
4. **Official documentation** — wins for version-specifics.
5. **Training priors** — reference only; always verify.

A recalled memory never overrides rules (1) or live state (2), but it **does** override your prior assumptions (5). If recall gives you a project fact, act on it instead of re-discovering it.
```

- [ ] **Step 3: Encode the within-memory ranking as Hindsight directives**

On the shared `hindsight-api`, set priority-ordered **directives** on the `private__hermes` + `shared` banks so curated observations/mental-models rank first (the within-memory half of §4b). Use the Hindsight directives API (hindsight-docs `developer/api/memory-banks.md`):

```bash
# Example (adjust to the deployed CLI/REST surface):
curl -fsS -X POST http://127.0.0.1:9177/v1/default/banks/shared/directives \
  -H 'Authorization: Bearer lemonade-local-noauth' -H 'Content-Type: application/json' \
  -d '{"text": "Prefer consolidated observations and shared decisions over raw episodic facts when answering.", "priority": 1}'
```

> NOTE (verify): confirm the exact directives endpoint/shape against the deployed Hindsight version (`memory-banks.md`); adjust the curl if the path differs.

- [ ] **Step 4: Record the stanza + directives** in `hindsight-deploy.md`. Commit any in-repo template change:

```bash
git add src/hal0/agents/hermes/templates/SOUL.md 2>/dev/null || true
git commit -m "feat(hermes): ground-truth precedence stanza in SOUL.md (Layer-7, cognitive SoT) (P5-H)" || true
```

## Task P5H-6: Lock the Hermes memory config (single active provider invariant)

**Files:**
- Modify (on box): `/var/lib/hal0/.hermes/config.yaml`

Per spec: **NO** background second store — Hermes' generic built-in memory stays OFF. Exactly one active provider.

- [ ] **Step 1: Confirm the single-provider invariant**

```bash
grep -nA3 'memory:' /var/lib/hal0/.hermes/config.yaml
# Expect: provider: hal0-memory ; NO second provider; built-in memory not also active.
```

- [ ] **Step 2: Verify the plugin kind is `exclusive`**

`plugin.yaml` ships `kind: exclusive` (MemoryManager single-external-provider invariant — confirmed in P5H-1). Confirm the deployed plugin retains it.

- [ ] **Step 3: Live-turn smoke** — a Hermes turn shows `prefetch` returning a recalled block that Hermes acts on (no redundant re-discovery):

```bash
sudo -u hal0 hermes chat   # run a turn that should hit a stored fact; confirm the recalled block appears + is used
```

- [ ] **Step 4: Record** the live-turn outcome in `hindsight-deploy.md`.

## Task P5H-MIG: Start fresh — abandon the spike `hermes` bank (NO migration)  *(OPS — decision recorded)*

**Decision (2026-06-06, owner + on-box probe).** Do **not** migrate the spike's embedded
`hermes` bank. The probe found it holds **5 spike-test memory_units / 4 docs / 17 entities**
against **40 failed retains vs 10 completed** (the extraction pipeline failed ~3× more than
it succeeded) — zero production value, 10 MB. Migrating 5 test rows is not worth the
pg-level schema/version-compat risk. Hermes **starts fresh**: its `private:hermes` + `shared`
banks **auto-create on first write** against the shared `hindsight-api`. The embedded pg is
deleted in **Task P5H-3 Step 4**, not dumped. (A native `hindsight-admin backup --schema
public` → `restore` vehicle *exists* as a fallback if continuity is ever wanted, but it is
schema-scoped + destructive-on-restore and not worth invoking here.)

- [ ] **Step 1: Confirm the shared instance has a clean slate for Hermes**

```bash
# Against the shared platform hindsight-api (P1-6). Banks auto-create, so "absent" is fine —
# the point is to confirm no STALE private:hermes data is lurking from a prior experiment.
curl -fsS http://127.0.0.1:<shared_api_port>/v1/default/banks 2>/dev/null | jq '.[].bank_id' \
  || echo "no banks yet — expected on a fresh shared instance"
# Expect: neither private__hermes nor shared exist yet, OR exist and are empty.
```

- [ ] **Step 2: Verify fresh accumulation works** — the P5H-3 Step 5 smoke turn (a `remember:`
  + recall) is the proof: after it runs, `private__hermes` exists in the shared instance and
  recall returns the just-stored fact. No separate action needed here; this task only records
  that migration was deliberately skipped.

- [ ] **Step 3: Record the abandon decision** in `docs/internal/brain-redesign/ops/hindsight-deploy.md`
  ("P5-H: spike `hermes` bank abandoned, not migrated — 5 test rows, 40 failed retains; started
  fresh; embedded pg deleted in P5H-3").

**P5-H Exit:** Hermes runs with a single `hal0-memory` provider; the `local_embedded` install is gone (both respawn guards removed, embedded pg stopped + deleted, no wrap-patch); Hermes' `private:hermes`/`shared` banks exist in the shared instance and accept new writes (**started fresh** — no spike data carried over); a live turn shows `prefetch` returning a recalled block Hermes acts on; `config.yaml` survives a root TUI session without clobber. **Rollback:** per-surface — the provider can revert (backups `config.yaml.bak-pre-hindsight-*` exist); the SOUL.md stanza is additive. (Note: retirement deletes the embedded pg, so reverting to `local_embedded` would mean a clean re-spike, not a restore — acceptable given the data was disposable.)

---

## Self-Review

Run after writing — see the bottom of this file for the recorded pass.
