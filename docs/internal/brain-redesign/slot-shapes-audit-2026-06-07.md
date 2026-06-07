# SLOT shape audit — descriptor-field proliferation & consolidation

Date: 2026-06-07
Author: audit agent (read-only)
Code read at: `/tmp/hal0-partA` (branch `fix/flm-host-probe`)
Runtime inspected: CT 105 (`ssh hal0`), `/etc/hal0/slots/*.toml`, live `GET /api/slots`,
`/var/lib/hal0/lemonade/config.json`.

> **Headline verdict.** The slot shape is genuinely redundant, and the operator's
> *instinct* (too many overlapping fields) is right — but the operator's stated
> *hypothesis* ("drop `device`, keep `backend`") points the **wrong way**. The
> codebase is mid-migration in the **opposite** direction: `device` is the v0.2
> canonical field, `backend` is **DEPRECATED, removed in v0.3** (ADR-0006 §7).
> Keep `device`, drop the stored `backend`. See Q2.

---

## 0. Raw evidence

### 0.1 Deployed slot TOMLs — `ssh hal0 cat /etc/hal0/slots/*.toml`

Field usage per slot (✓ = key present on disk). `D=device, B=backend, P=provider,
R=role, E=enabled`:

| slot           | type          | D (device) | B (backend) | P (provider) | R (role) | enabled | port | model.default                  | idle | other                                   |
|----------------|---------------|------------|-------------|--------------|----------|---------|------|--------------------------------|------|-----------------------------------------|
| npu            | llm           | npu        | flm         | lemonade     | npu      | ✓(enabled=true) | 8088 | qwen3-it-4b-FLM                | 1800 | ctx 65536                               |
| primary        | llm           | gpu-rocm   | rocm        | lemonade     | —        | ✓ true  | 8001 | chadrock-35b-ace-saber         | 900  | enable_thinking=false, llamacpp_args    |
| agent-hermes   | llm           | gpu-rocm   | — (none)    | — (none)     | —        | (default=false) | 8001 | qwopus3.6-27b-v2               | 900  | group="chat", llamacpp_args             |
| gpu-rocmfp4    | llm           | gpu-rocm   | rocm        | llama-server | —        | (default=false) | 8010 | qwopus3.6-27b-v2               | 900  | enable_thinking=true, [server].extra_args |
| gpu-rocmfp4-moe| llm           | gpu-rocm   | rocm        | llama-server | —        | —        | 8011 | chadrock3.6-35b-uncensored     | —    | enable_thinking=true, [server].extra_args |
| embed          | embedding     | npu        | flm         | — (none)     | —        | false   | 8082 | embed-gemma:300m               | 900  | llamacpp_args                           |
| rerank         | reranking     | gpu-vulkan | vulkan      | — (none)     | —        | true    | 8083 | jina-reranker-v1-tiny-en-GGUF  | —    | —                                       |
| stt            | transcription | npu        | flm         | — (none)     | —        | false   | 8085 | whisper-v3:turbo               | —    | —                                       |
| tts            | tts           | cpu        | cpu         | — (none)     | —        | false   | 8084 | kokoro-v1                      | —    | —                                       |
| utility        | llm           | gpu-vulkan | vulkan      | llama-server | —        | (default true) | 8081 | qwen3-zero-coder-v2-0.8b-f16   | —    | ctx 65536                               |

Observations from disk:
- Every slot redundantly carries **both** `device` AND `backend`, and they are
  always the device↔backend mirror image (`gpu-rocm`/`rocm`, `npu`/`flm`,
  `gpu-vulkan`/`vulkan`, `cpu`/`cpu`). Never independent. (`agent-hermes` omits
  `backend` entirely and works fine — proving `backend` is droppable.)
- `port` can be authored at **both** top level and under `[server]` — the loader
  reads both (slots.py:509-514). In deployment only **npu** actually double-authors it
  (8088 at `[slot]` AND `[server]`); `primary`'s `[server]` carries only `extra_args`
  and `agent-hermes` has no `[server]` table — but the schema permitting two homes is the
  redundancy.
- `provider` is set on only 5 of 10 slots and is **ignored by SlotManager**
  (schema.py:232-239: "SlotManager ignores them").
- `role` is set on exactly **one** slot (npu); everywhere else it is derived from
  the slot name (schema.py:245-252).

### 0.2 Live `/api/slots` payload (CT 105)

Per-slot top-level keys actually emitted:
`name, state, port, model_id, backend, metadata{updated_at,message,adopted,backend,provider},
last_used_at, kind, status, provider, models, type, model_default, enabled,
enable_thinking, n_gpu_layers, rope_freq_base, idle_timeout_s, workers, llamacpp_args,
lemonade_state, mem_mb, metrics{...}`. NPU slot additionally carries
`backend_url, declared_backend`. (When a `loaded` slot's actual backend can be
introspected: `actual_backend, backend_mismatch`.)

Live FLM args: `/var/lib/hal0/lemonade/config.json` → `"flm": {"args": "--asr 0 --embed 0"}`
— i.e. **the trio is currently chat-only** (stt + embed runtime-off). And `stt`/`embed`
slot TOMLs both have `enabled=false` (hal0-side off as well).

The payload also appends a **synthetic** `hal0` composite slot
(`kind:"slot", _synthetic:true, advertised_models:5`) — not a real slot, the
aggregate upstream (see Q6/§7).

---

## 1. Q1 — Field table: value · who SETS · who READS · redundancy

`SlotConfig` source of truth is `src/hal0/config/schema.py:195-428`. The payload is
assembled in `src/hal0/api/routes/slots.py` (`_slot_to_dict` :72; enrichment
`_lemonade_state_enrichment` :123).

| field | allowed values | SET (source of truth) | READ (consumers) | redundant-with / derivable-from |
|-------|----------------|------------------------|-------------------|----------------------------------|
| `name` | `^[a-z0-9][a-z0-9_-]{0,31}$` | TOML `[slot] name` (schema.py:207, validator :390) | everything; key in `out{}` (slots.py:307); role-derivation; UI cards | **canonical** — not redundant |
| `type` | `llm`/`embedding`/`reranking`/`transcription`/`tts`/`image` | TOML `[slot] type` (NB: **not a typed SlotConfig field** — rides `extra="allow"`); UI create modal (slot-modals.jsx:257) | trio gating (`v1._is_npu_trio_request`); enrichment npu-llm detection (slots.py:180); UI trio split (slots.jsx:621-623); model-compat filter (slot-modals.jsx:165) | **canonical** — the real modality discriminator |
| `device` | `gpu-rocm`/`gpu-vulkan`/`cpu`/`npu` (schema.py:51) | TOML `[slot] device` (schema.py:223); UI device select (slot-modals.jsx:274) | `device_to_backend()` (lemonade.py:89) → recipe+llamacpp_backend on `/v1/load`; `_cfg_effective_backend` (manager.py:2178); enrichment npu detect (slots.py:179); UI `NpuFlmStack` keys off `device==="npu"` (slots.jsx:607) | **CANONICAL hardware field** (v0.2) |
| `backend` | `vulkan`/`rocm`/`flm`/`moonshine`/`kokoro`/`cpu` (schema.py:45) | TOML `[slot] backend` (schema.py:214) — **DEPRECATED** | validator only; `_promote_backend_to_device` reads it ONLY when `device` absent (schema.py:324-363); else dead on disk | **100% redundant with `device`**; removed v0.3 |
| `provider` | `lemonade`/`llama-server`/`flm`/`moonshine`/`kokoro` (schema.py:89) | TOML `[slot] provider` (schema.py:232) — **DEPRECATED** | round-trip + UI label only; **SlotManager ignores it** (schema.py:237); payload lifts `metadata.provider` (slots.py:94) | redundant; lifecycle uses Lemonade unconditionally (ADR-0008) |
| `role` | freeform str / None | TOML `[slot] role` (schema.py:245); set on `npu` only | normalization-chain binding hint; "when unset, derived from name" | **derivable from `name`** in 9/10 cases |
| `enabled` | bool (default true) | TOML `[slot] enabled` (schema.py:241) | startup gating; `lemonade_state="disabled"` (slots.py:263); trio membership (slots.py:304); UI fade | **canonical** (operator on/off) |
| `group` | freeform str (e.g. `chat`) | TOML `[slot] group` (`extra="allow"`; set on agent-hermes) | capability bucketing; UI grouping | overlaps `type`+capability catalog; weak |
| `model.default` | registry id OR un-registered FLM tag | TOML `[model] default` (schema.py:147) | `LemonadeProvider.load` → `/v1/load` model_name (lemonade.py:608); payload `model_default` (slots.py:213); composite upstream (api/__init__.py:179) | **canonical config** (the assigned model) |
| `model_id` | str/None | **runtime** `SlotStateSnapshot.model_id` (state.py:231) — last dispatched/loaded id | payload top-level `model_id` (slots.py via `_serialize_slot`); UI `slot.model_id` | **observed**, distinct from `model.default` (config). Both exist on purpose. Live proof of divergence: `embed` slot `model_id="builtin.nomic-embed-text-v1.5-q8"` vs `model_default="embed-gemma:300m"`; `stt` slot `model_id="whisper-tiny"` vs `model_default="whisper-v3:turbo"` |
| `recipe` | `flm` / None (derived) | **NOT a stored slot field** | `device_to_backend(device)` (lemonade.py:89) returns `(recipe, backend)`; `npu→("flm",None)`, others→`(None,backend)`; sent on lemond `/v1/load` | **derived from `device`** |
| `model_default` | = `model.default` | payload-only mirror (slots.py:213) | UI persona dropdown, pickers | duplicate of `model.default` for wire convenience |
| `lemonade_state` | `disabled`/`idle`/`loaded` | enrichment computed (slots.py:262-298) from lemond `/v1/health.loaded[]` + `enabled` | UI chip (slots.jsx:64); NOT persisted | **derived** (enabled + health) |
| `state` | SlotState enum (`offline`/`ready`/`serving`/`idle`/`error`/…) | runtime `SlotStateSnapshot.state` (state.py); SlotManager state machine | payload `state`/`status`; UI dot | **derived/runtime** (≠ lemonade_state; one is hal0 SM, other is lemond) |
| `port` | 8081-8099 (schema.py:208) | TOML `[slot] port` and/or `[server] port` | child bind; backend_url; payload | authored in TWO places (redundant) |
| `idle_timeout_s` | ≥0 (default 300) | TOML `[slot] idle_timeout_s` (schema.py:277) | SlotManager eviction; payload | canonical knob |
| `backend` (payload top-level) | `rocm`/`vulkan`/`cpu`/`flm` | `_cfg_effective_backend(cfg)` = `device_to_backend(device)` (manager.py:2178, mirrored into `metadata.backend`); lifted by slots.py:92 | UI chip | **derived from `device`** — NOT the legacy TOML `backend`. Doc at manager.py:2186: legacy `backend` field "drifts the moment a user flips backend (which only rewrites `device`)" |
| `declared_backend` | `rocm`/`vulkan`/`cpu`/`flm` | `device_to_backend(device)` (slots.py:284) | UI drift chip | **fully redundant with `device`** (see §3) |
| `actual_backend` | `rocm`/`vulkan`/`cpu` | `resolve_actual_backend` via `/proc` binary path (lemonade.py:147-175,278) | UI drift chip; `backend_mismatch` | **NOT redundant** — observed runtime fact |
| `enable_thinking` | true/false/None | TOML `[slot] enable_thinking` (schema.py:253) | normalize/thinking.py; payload | canonical per-slot default |
| `n_gpu_layers`,`rope_freq_base`,`workers`,`llamacpp_args`,`context_size` | — | `[model]`/`[server]`/`[slot]` | launcher arg-build; UI edit drawer seeding | canonical tuning knobs |
| `flm_args` (`--asr`/`--embed`) | `"--asr <0|1> --embed <0|1>"` | **NOT a slot field** — lives in lemond config `flm.args` (client.py:95-114) | trio modality gating (orchestrator.py:88); UI toggles (slots.jsx:449) | trio-global, not per-slot (see Q3) |

---

## 2. Q2 — device · backend · type · role · provider — relationships; can `device` be dropped for `backend`?

**They are NOT five independent axes. There are two real axes plus three
redundant/legacy fields.**

- **`type`** — the modality discriminator (chat/embed/voice/img). Orthogonal to
  hardware. **Independent, keep.**
- **`device`** — hardware intent (`gpu-rocm|gpu-vulkan|cpu|npu`). **Independent, keep.**
  This is v0.2 canonical (schema.py:47-52, ADR-0006 §7).
- **`backend`** — DEPRECATED legacy enum. `device_to_backend()` (lemonade.py:89)
  is a clean **bijection** over the 4 live hardware classes:
  `gpu-rocm↔rocm, gpu-vulkan↔vulkan, cpu↔cpu, npu↔flm`. So `backend` carries
  **zero** information not in `device`. Removed v0.3.
- **`provider`** — DEPRECATED. Lemonade is the sole lifecycle driver
  (ADR-0008 §2); SlotManager **ignores** the field (schema.py:237). Derivable/constant.
- **`role`** — optional hint; "derived from name when unset" (schema.py:249).
  Set on 1/10 slots. Derivable from `name`.

### Can `device` be dropped in favour of `backend`? — **NO. The operator has the arrow reversed.**

The migration is explicitly **the other direction** (`backend` → `device`):
- `_VALID_BACKENDS` comment: "DEPRECATED v0.2: `SlotConfig.backend` is being retired
  in favour of … `SlotConfig.device`" (schema.py:40-44).
- `backend` field doc: "DEPRECATED (v0.2; removed v0.3) … Use `device` instead"
  (schema.py:217).
- `device` field doc: "Replaces the legacy `backend` field which mixed providers and
  backends" (schema.py:227).

And `backend` is the **strictly worse** primitive:
1. It is **many-to-one / overloaded**: `BACKEND_TO_DEVICE` (schema.py:67-81) collapses
   `moonshine`/`kokoro`/`cpu` → all `cpu`. It mixed *hardware* with *provider identity* —
   the exact confusion v0.2 split apart.
2. `npu`'s backend token is **`flm`** — a *recipe/provider*, not hardware. `device=npu`
   is clean hardware; `backend=flm` smuggles a runtime in.
3. The legacy TOML `backend` field **drifts and is never resynced**: flipping the
   backend in the UI rewrites only `device` (manager.py:2186 comment), so on-disk
   `backend` goes stale immediately. Even the runtime payload's `backend` is computed
   from `device` (`_cfg_effective_backend`), not read from the stale TOML field.

**Verdict: keep `device`, delete the stored `backend` (and `provider`). The operator's
redundancy instinct is correct but the field to drop is `backend`, not `device`.**

---

## 3. Declared vs Actual backend (added scope) — is the duplication necessary?

Two values, two different epistemics:

| value | source | code | meaning |
|-------|--------|------|---------|
| `declared_backend` | `device_to_backend(cfg.device)` | slots.py:284-287; status() lemonade.py:719-724 | the slot's **intent**, a pure function of `device` |
| `actual_backend` | resolve via `loaded[].backend_url` → port → PID → `/proc/<pid>/exe` path → classify (`/vulkan/`→vulkan, `/rocm-stable/` or `/rocmfp4-llama/`→rocm, else cpu) | lemonade.py:147-175, 278; `resolve_actual_backend` | the **observed** build dir of the live llama-server child |
| `backend_mismatch` | `actual != declared` (only when both known) | slots.py:288-292 | drift flag for UI chip (slots.jsx:324-330) |

**Why they can disagree:** when a model is loaded **outside** the normal slot path
(e.g. name-based lazy-load with no explicit `llamacpp_backend` in the `/v1/load` body),
lemond's **global `config.json` default backend wins** instead of the slot's device-derived
backend (lemonade.py:127-133). The slot says `gpu-rocm` but the child actually ran on
`vulkan` (the lemond global default in `/var/lib/hal0/lemonade/config.json` →
`llamacpp.backend = "vulkan"`).

**Is the duplication necessary?**
- `declared_backend` is **fully redundant with `device`** — the UI even notes it never
  recomputes (slots.jsx:73-78). It is in the payload purely so the UI compares
  like-for-like tokens without re-running the map. **Droppable** (UI can derive from
  `device`).
- `actual_backend` is **necessary** — it is a genuinely independent runtime observation
  that no config field encodes. Keep it.
- **Minimal non-redundant runtime set = `{device (intent), actual_backend (observed)}`.**
  Compute `declared`/`mismatch` on the client from `device`.

---

## 4. Q3 — the NPU "trio": one `flm serve` backs three slots

### Mechanism
One `flm serve <chat-tag> --asr <0|1> --embed <0|1>` child process answers three
OpenAI endpoints simultaneously (`flm.py:7-9`): `/v1/chat/completions`,
`/v1/audio/transcriptions`, `/v1/embeddings`. **Lemonade only registers the chat
model**; it has no knowledge of the ASR/embed roles (flm_trio.py:6-9).

hal0 surfaces three *slots* anyway — and here is the mess: the code constant
`_FLM_TRIO_SLOTS = {"agent","stt-npu","embed-npu"}` (slots.py:106-112), but the
**deployed slots are named `npu`/`stt`/`embed`**. So the hardcoded `coresident_group`
marker (slots.py:304 `if name in _FLM_TRIO_SLOTS`) **can never fire** for the real slots
— a **dead marker**. The UI sidesteps this entirely by keying the trio off
`device==="npu"` (slots.jsx:607, `NpuFlmStack`), splitting by `type`
(`llm`→chat anchor, `transcription`→stt, `embedding`→embed; slots.jsx:621-623).

### How `flm_args` gates live modalities
`flm_args` is **NOT a slot field** — it lives in lemond's config at `flm.args`
(client.py:85-92; top-level `flm_args` is rejected 400). The orchestrator toggles a
single `--asr`/`--embed` flag per child (orchestrator.py:88-138, `_recompose_flm_args`)
and writes `{"flm":{"args": ...}}` (client.py:108). It applies only on the **next FLM
load** — the anchor must be reloaded (UI "reload" affordance).

- **Chat** → routes through Lemonade normally (lemond proxies to the FLM child).
- **STT / embed** → hal0 **bypasses** lemond and POSTs straight to the FLM child's
  `{backend_url}/v1/audio/transcriptions` / `/v1/embeddings` (flm_trio.py:215-285).
  `backend_url` discovered from `/v1/health.loaded[]` where `recipe=="flm" && type=="llm"`
  (flm_trio.py:184-209). If no FLM chat is loaded → `FLMTrioNotAvailable` 503 ("load an
  NPU chat slot first").

### Why the stt/embed model pickers are read-only
The FLM build serves the asr/embed models **fixed by the `--asr`/`--embed` flags**; the
request `model` field is **ignored by FLM** (verified 2026-06-06, slots.jsx:555-559,574-585).
A picker would be cosmetic — so `NpuModalityCard` renders the served model as a read-only
label (`readOnlyModel`), showing `slot.modelDefault` (the configured FLM tag) because the
shadow modality "is never loaded as its own process, so its live `model_id` stays stale on
the pre-trio GGUF" (slots.jsx:579-583). Only the **chat anchor** is a real picker.

### Minimal correct recipe: "chat anchor = gemma4-it-e4b-FLM, stt+embed OFF"

There are **two independent OFF layers** — set both:

1. **Set the chat anchor model.** The FLM tag is NOT in the registry, so you
   **cannot** use `/load` or `/swap` (they 404 on the registry gate — see Q4). Use the
   **config-edit path** which has no registry gate:
   `PUT /api/slots/npu/config` (or `PATCH /api/slots/npu/defaults`) writing
   `[model].default = "gemma4-it-e4b-FLM"` (slots.py:1136 / :1172 — no `registry.has`).
2. **Runtime modality off** — set lemond `flm.args = "--asr 0 --embed 0"`
   (POST lemonade config; client.py:108 payload `{"flm":{"args":"--asr 0 --embed 0"}}`).
   *The live config already shows exactly this.*
3. **hal0-side off** — set `enabled=false` on the `stt` and `embed` slot TOMLs (already
   true in deployment). This removes them from startup + marks `lemonade_state="disabled"`.
4. **Reload the anchor** (`npu` slot unload+load) so the new model + `--asr 0 --embed 0`
   take effect.

Layer (2) stops the FLM child from serving those modalities at runtime; layer (3) is the
hal0 catalog/UI off-switch. Both should agree to avoid a slot that looks enabled but has no
backend.

---

## 5. Q4 — registry-bypass: config-default path vs slot-apply path

**The npu slot serves `qwen3-it-4b-FLM` even though it is NOT in hal0's registry.** Why:

- `LemonadeProvider.load()` (lemonade.py:582-637) reads `model.default` straight from the
  slot cfg (`_slot_model`, lemonade.py:608) and passes it to lemond `/v1/load` as
  `model_name`. **It never consults hal0's `model_registry`.** lemond resolves the model
  via its own `server_models.json` / FLM cache. (Comment lemonade.py:602-605: registry
  metadata "currently unused under Lemonade — the daemon resolves models via its own
  server_models.json".)
- So **anything written to `[model].default`** loads, registry or not — that is the FLM
  tag's whole route to existence.

**The slot-apply API path REQUIRES registry membership** at exactly two call sites:
- `POST /{name}/load` — `if registry is not None and not registry.has(model_id): raise
  ModelNotFound` — **but only when `model_id` is supplied in the body** (slots.py:1411-1419).
  An **empty body falls through** to `sm.load(name, model_id=None)` → uses the TOML default
  → **no registry check**.
- `POST /{name}/swap` — registry-gated **unconditionally** (swap requires a non-empty
  `model_id`; slots.py:1455-1468).

**Where the two paths diverge:**

| path | registry gate? | reaches FLM tag? |
|------|----------------|------------------|
| `PUT /{name}/config` `[model].default=…` (slots.py:1136) | **NO** | ✅ writes any tag to disk |
| `PATCH /{name}/defaults` (slots.py:1172) | **NO** | ✅ |
| `POST /{name}/load` with **empty body** (slots.py:1420) | **NO** (model_id None → TOML default) | ✅ |
| `POST /{name}/load` with `{model_id}` (slots.py:1413) | **YES** | ❌ 404 for FLM tag |
| `POST /{name}/swap` (slots.py:1462) | **YES** | ❌ 404 for FLM tag |
| `LemonadeProvider.load` → lemond `/v1/load` (lemonade.py:631) | **NO** (lemond's own catalog) | ✅ |

The divergence point: the registry check is an **API-route guard on operator-supplied
model_ids**, NOT a property of the load mechanism. The actual load (provider→lemond) is
registry-blind. So the bypass = "write the tag to `[model].default` (or load with empty
body), never pass it as an explicit `model_id`." This is why the UI shows the FLM picker as
read-only and drives the anchor via config-edit, not swap.

---

## 6. Q6 — composite `hal0` upstream

`_fetch_hal0_composite_models` (api/__init__.py:135-179) aggregates **each slot's
`[model].default`** (checks `model.default`/`model_default`/`model_id` shapes, :173-179)
into ONE synthetic `hal0` upstream (api/__init__.py:504-547, "register exactly ONE composite
`hal0` upstream"). The live payload's trailing `{"name":"hal0","_synthetic":true,
"advertised_models":5}` is this aggregate — it advertises slot-default models so the
dispatcher/OpenAI surface can name them without per-slot upstreams. It is **not a real
slot** and should be excluded from any "slot shape" count.

---

## 7. Q5 — recommended MINIMAL slot shape + assignment validation

### 7.1 Minimal non-redundant slot shape (config, on disk)

```toml
[slot]
name = "primary"          # canonical id (role derives from this)
type = "llm"              # modality: llm|embedding|reranking|transcription|tts|image
device = "gpu-rocm"       # hardware intent: gpu-rocm|gpu-vulkan|cpu|npu
enabled = true
port = 8001               # single location (drop the [server] duplicate)
idle_timeout_s = 900

[model]
default = "chadrock-35b-ace-saber"
context_size = 65536

[server]                  # optional tuning only
extra_args = "..."
```

**Drop entirely** (all redundant or derivable):
- `backend` — bijective with `device` (Q2). Already deprecated; finish the removal.
- `provider` — ignored by SlotManager; Lemonade is the sole driver (ADR-0008).
- `role` — derive from `name`; keep an override only if a slot truly needs a name≠role.
- duplicate `port` under `[server]` — keep one.
- payload `declared_backend` / `model_default` (mirror of `model.default`) — derive on
  the client.

**Keep as derived/runtime (payload only, never persisted):** `state`, `lemonade_state`,
`model_id` (observed), `actual_backend`/`backend_mismatch`, `backend_url`, `mem_mb`,
`metrics`. The only runtime-backend fields worth shipping are **`device` (intent)** +
**`actual_backend` (observed)**.

**Trio note:** `flm_args` stays a **lemond-global** setting (`flm.args`), not a slot field.
Either fix `_FLM_TRIO_SLOTS` to the real names (`npu`/`stt`/`embed`) or delete the dead
constant and rely solely on `device=="npu"` + `type` (as the UI already does).

### 7.2 How slot↔model assignment validation SHOULD work

Today the only real check is client-side (slot-modals.jsx:164-172) + the registry gate on
explicit `model_id`. A model is assignable to a slot **iff ALL**:

1. **Modality match:** `model.type == slot.type` (chat→llm, embed→embedding, asr→transcription,
   rerank→reranking, tts→tts, image→image). This is the primary, non-negotiable gate
   (already enforced client-side at slot-modals.jsx:165).
2. **Device/backend capability match:**
   - `device==npu` ⇒ model must be an FLM model (`model.device=="npu"` / backend `flm`).
   - `device∈{gpu-rocm,gpu-vulkan,cpu}` ⇒ `model.backends` contains the device's llamacpp
     backend token (`device.replace("gpu-","")`), per slot-modals.jsx:169-171.
   - `rocmfp4`-tagged models ⇒ only `device==gpu-rocm` (slot-modals.jsx:168).
3. **Existence:** registry id **OR** a provider-resolvable tag (FLM tags resolve via lemond,
   not hal0's registry). The current hard `registry.has()` gate is **too strict** — it blocks
   exactly the legitimate FLM-tag case and is the reason for the config-edit bypass. Replace
   "must be in registry" with "must be registry-resolvable **or** provider(lemond)-resolvable
   for this device's recipe."

Validation should be enforced **server-side** at the config-write/load boundary (not only in
the React modal), using `(type, device)` from the slot and `(type/capability, backends/device,
tags)` from the model — so the API can't be made to write an incompatible assignment that then
fails opaquely at load.

---

## 8. The "it's a mess" summary — blunt list of redundant/conflicting fields

1. **`backend` (TOML) — pure duplicate of `device`**, deprecated, drifts when unsynced;
   even runtime reads derive `backend` from `device` and ignore the field. **Delete.**
2. **`provider` (TOML) — ignored by the lifecycle layer**, Lemonade is hardwired. **Delete.**
3. **`declared_backend` (payload) — pure function of `device`.** Derive client-side. **Drop from wire.**
4. **`model_default` (payload) — exact mirror of `model.default`.** Wire convenience only.
5. **`port` may be authored twice** (top-level + `[server]`; loader reads both). In
   deployment only `npu` actually does it (8088 in both). Pick one home.
6. **`role` set on 1/10 slots**, otherwise name-derived. Override-only.
7. **`_FLM_TRIO_SLOTS` constant names `agent`/`stt-npu`/`embed-npu` but real slots are
   `npu`/`stt`/`embed`** → the `coresident_group` marker is **dead code**; the UI works only
   because it ignores the constant and keys off `device==="npu"`. Naming drift.
8. **`lemonade_state` vs `state`** — two different status notions (lemond runtime vs hal0
   state machine) both surface; legitimately distinct but confusing without the doc.
9. **`registry.has()` gate is conditional/inconsistent**: enforced on `/swap` and on `/load`
   *with* a body, but bypassed by empty-body `/load`, `PUT /config`, and the provider load —
   so "is this model allowed here?" has no single answer.

**Net:** the two real, independent descriptors are **`type`** (modality) and **`device`**
(hardware) plus **`model.default`** (assignment). Everything else is either a derived runtime
observation (`state`, `actual_backend`, `model_id`, `lemonade_state`) or dead/redundant
(`backend`, `provider`, `declared_backend`, `model_default`, duplicate `port`, mostly-unused
`role`). Consolidate to `{name, type, device, enabled, port, idle_timeout_s, [model].default,
[server].extra_args}` + runtime `{state, model_id, actual_backend}`.
