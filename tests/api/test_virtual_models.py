"""GET /v1/models advertises hal0/* virtual names with context_length.

Verifies that the list_models handler appends rows for each canonical
virtual name (hal0/agent, hal0/npu, hal0/utility) when a slot is
loaded, and that each row carries a context_length field (required by
Hermes' custom provider for correct context-window sizing).

ADR-0023: the canonical advertised virtuals are ``hal0/agent`` (the default
anchor), ``hal0/utility``, and ``hal0/npu``. ``hal0/chat`` is retired — it is
neither advertised in /v1/models nor a canonical virtual name. (The older
``hal0/primary`` alias was removed in #654.)
"""

from __future__ import annotations

from hal0.normalize import resolver as R


def _views():
    return [
        R.SlotView(
            name="agent", role=None, device="gpu-vulkan", model_id="big", context_length=65536
        )
    ]


def test_virtual_names_present_with_context_length(client, monkeypatch):
    async def fake_views(request):
        return _views()

    monkeypatch.setattr("hal0.api.routes.v1._normalize_slot_views", fake_views)
    monkeypatch.setattr("hal0.api.routes.v1._normalize_loaded_models", lambda request: {"big"})

    data = client.get("/v1/models").json()["data"]
    by_id = {row["id"]: row for row in data}
    assert "hal0/agent" in by_id
    row = by_id["hal0/agent"]
    assert row["context_length"] == 65536  # FIRST key in Hermes' context precedence
    assert row["_hal0"]["virtual"] is True
    assert row["_hal0"]["resolves_to"] == "big"
    assert row["_hal0"]["device"] == "gpu-vulkan"


def test_virtual_rows_do_not_duplicate(client, monkeypatch):
    async def fake_views(request):
        return _views()

    monkeypatch.setattr("hal0.api.routes.v1._normalize_slot_views", fake_views)
    monkeypatch.setattr("hal0.api.routes.v1._normalize_loaded_models", lambda request: {"big"})

    ids = [r["id"] for r in client.get("/v1/models").json()["data"]]
    assert ids.count("hal0/agent") == 1


def test_legacy_primary_virtual_name_is_hidden(client, monkeypatch):
    """#654: hal0/primary was removed — it must NOT be advertised in /v1/models."""

    async def fake_views(request):
        return _views()

    monkeypatch.setattr("hal0.api.routes.v1._normalize_slot_views", fake_views)
    monkeypatch.setattr("hal0.api.routes.v1._normalize_loaded_models", lambda request: {"big"})

    ids = [r["id"] for r in client.get("/v1/models").json()["data"]]
    assert "hal0/primary" not in ids


def test_all_canonical_virtual_names_advertised_with_fallback(client, monkeypatch):
    async def fake_views(request):
        return _views()

    monkeypatch.setattr("hal0.api.routes.v1._normalize_slot_views", fake_views)
    monkeypatch.setattr("hal0.api.routes.v1._normalize_loaded_models", lambda request: {"big"})

    payload = client.get("/v1/models").json()
    assert payload["object"] == "list"
    by_id = {r["id"]: r for r in payload["data"]}
    # all three canonical names appear; npu/utility fall back to the agent
    # slot's model on a single-llm-slot box (ADR-0023).
    assert {"hal0/agent", "hal0/npu", "hal0/utility"}.issubset(by_id)
    # hal0/chat is retired — never advertised.
    assert "hal0/chat" not in by_id
    assert by_id["hal0/npu"]["_hal0"]["resolves_to"] == "big"
    assert by_id["hal0/utility"]["_hal0"]["resolves_to"] == "big"
    # every virtual row carries a context_length (mandatory for Hermes)
    for vid in ("hal0/agent", "hal0/npu", "hal0/utility"):
        assert by_id[vid]["context_length"] == 65536
