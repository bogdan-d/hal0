# Shape Consolidation Proposal — models & slots (2026-06-07)

Synthesis of two audits (read those for the file:line evidence):
- `model-shapes-audit-2026-06-07.md`
- `slot-shapes-audit-2026-06-07.md`

**Problem (operator's words: "it's a mess"):** a *model* and a *slot* each get re-projected into a
different vocabulary at every subsystem boundary. A model appears in **6+ distinct row shapes**;
`/api/models` alone emits **three** shapes in one array, then the UI throws the server's `type` away
and re-derives it. ~14 model descriptor fields and ~10 slot fields exist where a handful of primitives
+ read-time derivations would do.

---

## 1. The core asymmetry (operator's framing — correct)

| | carries | meaning | cardinality |
|---|---|---|---|
| **Model** | **`backends`** (plural) | *capability* — what it **can** run on | some 1 (`["rocm"]`), some many (`["rocm","vulkan","cpu"]`) |
| **Slot** | **`device`** (singular) | *target* — what it **will** run on now | exactly 1; swappable, not an identity |

**Assignment rule (the thing the whole mess is really about):**
```
assignable(model, slot)  ⇔  model.type == slot.type
                         AND  device_to_backend(slot.device) ∈ model.backends
                         AND  resolvable(model.id)        # registry OR provider-known
```

### ROCmMTP / rocm-vs-vulkan — handled, no new field
`device` stays **fine-grained**: `gpu-rocm`, `gpu-vulkan`, `npu`, `cpu` are *distinct* devices (never a
single "gpu"). A ROCmMTP model is `backends=["rocm"]` → matches a `gpu-rocm` slot, rejected by a
`gpu-vulkan` slot. A multi-backend GGUF is `backends=["rocm","vulkan","cpu"]` → matches any of the three.
The distinction lives **on the model's `backends`**, matched against the slot's fine-grained `device`.
Nothing is lost; slots do **not** need a plural backends field.

---

## 2. device vs backend — reconciled (both audits agree on the facts)

`device ↔ backend` is a **bijection modulo the `gpu-` prefix and the `npu`/`flm` synonym**
(`backendToDevice`, slot-modals.jsx:25): `rocm↔gpu-rocm`, `vulkan↔gpu-vulkan`, `npu|flm↔npu`, `cpu↔cpu`.
So one of the pair is pure redundancy. **Which to keep differs by entity, and the codebase already chose:**

- **Slots keep `device`** — ADR-0006 §7 is already migrating `backend`→`device`; `backend` is deprecated
  (removed v0.3, schema.py:40). `backend` is the *worse* slot primitive: it's many-to-one and smuggles the
  `flm` **provider** into a hardware field. → **drop slot `backend` + `provider` + `declared_backend`**
  (all = `device_to_backend(device)`).
- **Models keep `backends`** (plural) — the capability surface above. → **drop model singular `backend`,
  drop model `device`** (derive `device = backend_to_device(backends[0])` on read).

> The operator's original "drop device, keep backend" had the *arrow* reversed but the *instinct* right:
> kill one of the pair. Keep `device` on slots, `backends` on models.

### "Declared vs actual backend" in slot-edit
- `declared_backend` = `device_to_backend(device)` → **redundant, drop from the wire** (UI never recomputes).
- `actual_backend` = resolved from the live child's `/proc/<pid>/exe` build-dir (lemonade.py:147) →
  **NOT redundant.** Diverges when a model loads outside the slot path and lemond's global default wins.
  Keep it as **runtime-observed** state. Minimal runtime backend set = `{device (intent), actual_backend (observed)}`.

---

## 3. Vocabulary collisions a consolidation MUST preserve (don't naively merge)

1. **`type` has two value-spaces on one key:** W7 (`chat/embed/stt/img`) vs dispatcher
   (`llm/embedding/transcription`). The UI lib normalizer **already discards the server `type` and
   re-derives the dispatcher form from `capabilities`** (normalizeApiModel.ts:88). → Server should emit
   **dispatcher** `type` (hard-coded in SlotCard/create-slot/capability slots); W7 is just a counting
   bucket, derive on demand. `type` becomes a derivation of `capabilities`, not a stored field.
2. **FLM id fork:** colon `gemma4-it:e4b` (pull/probe/native FLM) vs `-FLM` `gemma4-it-e4b-FLM`
   (lemond-served / slot-default). Built **one-way** (models.py:215); **lemond owns the reverse map**, hal0
   has none. Keep both forms; the native `FLMProvider` path is **dormant** and expects the colon tag — do
   not "unify" on the assumption it handles `-FLM`.
3. **`capability` (sing) vs `capabilities` (plur)**, **`backend`/`backends`/`runtime`/`recipe`/`provider`**
   (five names for "what runs it"). Fold singular→plural; keep `recipe` (`backends→llamacpp`) and
   `provider` (`backend→provider`) as **derivation tables at their boundaries**, not stored fields.
   `runtime` is **dead** (written only to `metadata.runtime`; UI reads top-level `m.runtime` which is never
   set — slots.jsx:474). Drop it.

---

## 4. The registry-gate bug (root cause of the "not in the registry" apply error)

Both audits independently flag it. The slot-apply check (`slots.py:1413/1462`, `registry.has(model_id)`)
is **too strict and route-level**: enforced on `/swap` and `/load`-with-body, but *bypassed* by
empty-body `/load`, `PUT /config`, `PATCH /defaults` — which is exactly how gemma4 is live now (via
`npu.toml [model].default`, lemond-mediated, registry-blind; manager.py:1985 logs `model_not_in_registry`
and proceeds). FLM models structurally are **never** in hal0's registry — lemond owns them.

**Fix (the clean version of the patch I held):** replace `registry.has(id)` with
`resolvable(id) = registry.has(id) OR is_installed_flm(id) OR lemond_serves(id)`. Validation should gate on
**provider-resolvability**, not registry membership. This makes the dashboard "apply" button work for FLM
models without registering them or reconciling shapes.

---

## 5. Recommended minimal shapes

**Model — 8 stored fields, everything else derived on read:**
```
Model { id, name, path, size_bytes, capabilities[], backends[], hf_repo, hf_filename }
```
Derived: `type` (←capabilities, vocab-selectable), `device` (←backends[0]), `provider`/`recipe` (←backend,
at their boundaries), `ns` (←path, #220), `installed` (←path exists / FLM probe). Drop: singular
`capability`/`backend`, `runtime`, `owned_by`/`upstream` (→ `origin` enum if needed), the
`installed`/`downloaded` duplication (pick `installed`).

**Slot — config + runtime split:**
```
SlotConfig  { name, type, device, enabled, port, idle_timeout_s, [model].default, [server].extra_args }
SlotRuntime { state, model_id, actual_backend }   # observed, not stored
```
Drop: `backend`, `provider`, `declared_backend`, duplicate `port`, `model_default` mirror, mostly-unused
`role`. Trio modality on/off stays **lemond-global `flm.args`** (`--asr/--embed`), not a slot field.

**Dead code to delete:** `_FLM_TRIO_SLOTS={"agent","stt-npu","embed-npu"}` (slots.py:106 — wrong names vs
real `npu`/`stt`/`embed`; UI works only via `device==="npu"`); the top-level `runtime` read (slots.jsx:474);
the dual singular/plural reads in `catalog.py` once curated/FLM rows move to plurals.

---

## 6. Suggested phasing (smallest blast radius first)

- **P0 — registry-gate fix** (§4). Unblocks the dashboard apply button for FLM. ~1 route change + the
  `resolvable()` helper + a test. Independent of everything else. *(This is the held `slots.py:1413` fix,
  done right.)*
- **P1 — collapse `/api/models` to one row shape**, emitting dispatcher `type` + `installed` via shared
  derivation; delete the per-branch field-stamping (incl. the FLM block I added — it becomes a normal row).
- **P2 — drop the redundant projections**: slot `backend`/`provider`/`declared_backend` (derive from
  `device`); model singular `backend`/`capability`, `runtime`. Update the ~3 UI read sites + delete dead code.
- **P3 — vocab unification**: one `derive_type(caps, vocab)`; fold curated singular fields to plurals;
  document the colon/`-FLM` split + lemond-owns-reverse-map as the one intentional fork.

Each phase is independently shippable and testable; none requires the model/slot store schema to change at
once. P0 is the only one with user-visible payoff today.
