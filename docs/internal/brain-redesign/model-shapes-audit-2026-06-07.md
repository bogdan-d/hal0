# MODEL shape audit — descriptor-field proliferation across hal0 subsystems

**Date:** 2026-06-07
**Scope:** READ-ONLY. Maps every descriptor field a "model" carries, where it is SET and READ, to enable consolidation.
**Code read at:** `/tmp/hal0-partA` (branch `fix/flm-host-probe`). Runtime inspected on CT 105 (`ssh hal0`).

---

## 0. The shapes, named

A "model" is **not one object**. There are at least **six** distinct row shapes, each with a different field set:

| Shape | Where defined | Field naming convention |
|-------|---------------|--------------------------|
| **Registry `Model`** | `src/hal0/registry/model.py:50` | plural: `capabilities`, `backends`; no `device`/`type`/`provider` |
| **`/api/models` registry-derived row** | `routes/models.py:161-169` (`_model_to_dict`) | `Model` dump + `installed`/`object`/`created`/`owned_by`/`ns`/`type` |
| **`/api/models` upstream-synthesized row** | `routes/models.py:183-201` | `id`/`name`/`owned_by`/`upstream`/`installed`/`ns`/`type` — **no** capabilities/backends |
| **`/api/models` FLM-synthesized row** | `routes/models.py:229-244` | `backend`(sing)/`upstream`/`capability`(sing)/`capabilities`(plur)/`device`/`type` |
| **`CuratedModel`** | `registry/curated.py:75` | singular: `capability`, `backend`, `hf_file`; plus `recipe`(via `model_class`), `comfyui_subdir`, `bundle_only` |
| **Capabilities catalog picker row** | `capabilities/catalog.py:378,555` | model-first with `backends[]` list of `{id,provider,downloaded,pullable}` |
| **Lemonade `server_models.json` entry** | `lemonade/server_models_gen.py:382` | `checkpoint`/`recipe`/`labels`/`size`/`max_context_window` |

The `/api/models` endpoint emits **three of these shapes in the same array** (registry, upstream, FLM), and the UI's `normalizeApiModel` then re-derives `type`/`device` client-side because the shapes disagree.

---

## 1. Field table — value space → SET → READ → redundancy

| Field | Allowed values | SET (source of truth) | READ (consumers) | Redundant-with / derivable-from |
|-------|----------------|------------------------|-------------------|----------------------------------|
| **`id`** | freeform slug; FLM synthetic `<tag>-FLM`; FLM colon `family:size` | registry TOML key; `models.py:215` synth; lemond `/v1/models` | everything | irreducible (primary key) — but **value space is forked** (see Q3) |
| **`name`** | display string | `Model.name` (model.py:66); defaults to `id` | UI `longName` fallback | cosmetic; defaults to `id` |
| **`type`** | `chat/embed/rerank/stt/tts/img` **(W7)** OR `llm/embedding/transcription/reranking/tts/image` **(dispatcher)** | `_classify_type` (W7 vocab, models.py:167,199); `_FLM_DISPATCH_TYPE` (dispatcher vocab, models.py:240) | UI `SlotCard` (slots.jsx:229,251), `modelSlotType` (slots.jsx:484), W7 widget | **fully derivable** from `capabilities` — and is, twice, with two vocabularies (see Q3) |
| **`device`** | `gpu-rocm/gpu-vulkan/cpu/npu` | FLM row only (`device:"npu"`, models.py:243); slot TOML `device`; UI `derivedDevice` (slot-modals.jsx:74) | `SlotCard` chip (slots.jsx:319), `NpuFlmStack` filter (`s.device==="npu"`, slots.jsx:607), `backendToDevice` | **derivable from `backend`** (see Q2). Registry `Model` has NO `device`. |
| **`backend`** (singular) | `flm/llamacpp/llama-server/vulkan/rocm/cpu/kokoro/moonshine/whispercpp/comfyui/vibevoice` | `CuratedModel.backend` (curated.py:127); FLM row (`backend:"flm"`, models.py:238); slot TOML `backend` | `isFlmModel` (slots.jsx:473), `_provider_for_backend`, `_backend_variants` | overlaps `backends[]`; the catalog reads BOTH singular `.backend` and plural `.backends` defensively |
| **`backends`** (plural) | list of `vulkan/rocm/cuda/cpu/npu/moonshine/...` | `Model.backends` (model.py:112); `detect()` suggestions | `_backend_variants` (catalog.py:259), `server_models_gen._resolve_recipe`, UI `derivedDevice` | same concept as `backend`, list form. Curated uses singular, Registry uses plural |
| **`runtime`** | `flm` (only value seen) | **`metadata.runtime` ONLY** (pull.py:706,719,724) — never a top-level field | UI `m?.runtime==="flm"` (slots.jsx:474) — **reads top-level → DEAD clause** | redundant with `backend=="flm"`. **Drop candidate** (see note) |
| **`capability`** (singular) | `chat/embed/asr/tts/image/rerank` | `CuratedModel.capability` (curated.py:120); FLM row `capability` (models.py:241) | `_model_capabilities` (catalog.py:236), `modelSlotType` fallback (slots.jsx:486) | same concept as `capabilities`, scalar form |
| **`capabilities`** (plural) | list of `chat/embed/rerank/vision/asr/stt/tts/image` | `Model.capabilities` (model.py:89); `detect()`; FLM `_classify_flm_model` (flm.py:413) | `_classify_type`, `_model_capabilities`, `normalizeApiModel`, `server_models_gen` | canonical; `capability` is a curated/FLM-row alias |
| **`provider`** | `flm/llama-server/kokoro/moonshine/whispercpp/comfyui/lemonade` | `available_backends()` (catalog.py:147), `_provider_for_backend` (catalog.py:333); slot TOML `provider` | catalog picker row, slot config form | **derivable from `backend`** via `_BACKEND_TO_PROVIDER` (catalog.py:47) |
| **`recipe`** | `llamacpp/whispercpp/kokoro/sd-cpp/flm/ryzenai-llm` | `server_models_gen._resolve_recipe` (gen.py:258) from `backends` | Lemonade loader only | **derivable from `backend`/`backends`** via `_BACKEND_TO_RECIPE` (gen.py:140). Lemonade-internal alias of `backend` |
| **`owned_by`** | `local/<upstream-name>/flm` | `models.py:166,189,235` | OpenAI-compat clients (cosmetic) | redundant with `upstream`/`ns` (`local`⇔`installed`) |
| **`upstream`** | upstream name; `npu` for FLM | `models.py:190,237` | `isFlmModel` (`upstream==="npu"`, slots.jsx:476) | for FLM, redundant with `backend=="flm"` |
| **`ns`** | `blessed/pulled` | `_derive_ns` (model.py:165, path-shape rule, issue #220); hardcoded `pulled` for upstream/FLM rows | UI `OnDiskPanel` ns chip (model-modals.jsx:451) | derivable from `path` prefix; pure display bucket |
| **`installed`** / **`downloaded`** | bool | `installed` set in `/api/models` (models.py:163,191,238); `downloaded` in catalog rows (`_is_downloaded`, catalog.py:445) | UI `model.installed` guard (model-modals.jsx:436), swap popover "will pull" | **two names for one concept** (path-exists check); catalog says `downloaded`, models-API says `installed`. FLM uses `installed` from probe (flm.py:567) |

**Verdict:** Of ~14 descriptor fields, **only `id`, `name`, `capabilities`, `backends`, `path`, `size_bytes`, and pull coords (`hf_repo`/`hf_filename`) are load-bearing primitives.** `type`, `device`, `provider`, `recipe`, `runtime`, `owned_by`, `upstream`, `ns`, and the `installed`/`downloaded` duplication are all **derivable or duplicated** — they exist because each subsystem re-projects the model into its own vocabulary at its own boundary rather than deriving on read.

---

## 2. Is `device` fully derivable from `backend`?

**Yes — `device` is a lossy *rename* of `backend`, not independent information.**

### The mapping (`backendToDevice`, slot-modals.jsx:25-32)
```
rocm   → gpu-rocm
vulkan → gpu-vulkan
npu|flm → npu
cpu    → cpu
```
This is the **only** place `device` is computed from a backend id, and it is a clean total function from the backend token to a device token. The inverse is the `EditSlotDrawer`'s `device.replace("gpu-","")` (slot-modals.jsx:419,579,627) which recovers the bare backend token from the device — i.e. the two are **trivially inter-convertible** modulo the `gpu-` prefix.

### Is the map ever many-to-one or one-to-many?
- **Many backends → one device:** `rocm`, `vulkan`, `cpu` are *both* backends *and* devices (with the `gpu-` cosmetic prefix). `npu` and `flm` **both** map to device `npu` (slot-modals.jsx:29) — so `device=npu` is ambiguous about whether the backend token was `npu` or `flm`. In practice they're synonyms (FLM is the only npu runtime), so no information is lost.
- **One backend → many devices:** none. Each backend token maps to exactly one device.
- **The catalog's `backends[]` element** (catalog.py:610) carries `{id, provider, downloaded, pullable}` — it already keys by `backend` id (`gpu-vulkan`/`gpu-rocm`/`cpu`/`npu`) and never emits a separate `device`. So the *capability* surface already treats backend==device.

### What concretely breaks if `device` is dropped and everything filters by `backend`?
Three call sites would need to change from `device` to a `backend`-derived value:
1. **`NpuFlmStack` slot grouping** (slots.jsx:607,621,1117): `slots.filter(s => s.device === "npu")`. Would become `backend === "flm"` (or `backend === "npu"`). **No semantic change** — npu.toml already carries both `device="npu"` and `backend="flm"`.
2. **`SlotCard`/`SlotListRow` device chip** (slots.jsx:319,407; slot-modals.jsx:1013): `"chip dev-" + (device||"cpu").replace("gpu-","")`. Cosmetic; would derive the chip label from `backend`.
3. **`CreateSlotModal`/`EditSlotDrawer` device dropdown** (slot-modals.jsx:21,274,613): operator picks a "device". This is the one **real** UX coupling — but it already round-trips through `backendToDevice`/`.replace("gpu-","")`, so it can pick a `backend` directly and drop the rename.

**Conclusion:** `device` carries **zero information not in `backend`**. Dropping it requires only renaming three UI read sites; the slot TOML can stop storing `device` once the UI keys on `backend`. The only subtlety: the `gpu-` prefix and the `npu`/`flm` synonym must be preserved as a display convention.

---

## 3. Vocabulary collisions (what a consolidation MUST preserve)

### 3a. `type`: W7 vocab vs dispatcher vocab — TWO incompatible value spaces on one field name
- **W7 vocab** `chat/embed/rerank/stt/tts/img` — produced by `_CAPABILITY_TO_TYPE` (models.py:81) + `_classify_type` (models.py:113). Consumed by the Models view / W7 endpoints widget counter.
- **Dispatcher vocab** `llm/embedding/transcription/reranking/tts/image` — produced by `_FLM_DISPATCH_TYPE` (models.py:102) for FLM rows, and by `normalizeApiModel`'s `derivedType` (slot-modals.jsx:64) + `modelSlotType` (slots.jsx:484). Consumed by `SlotCard` metrics switch (slots.jsx:251-274: `type==="llm"|"embedding"|"reranking"|"transcription"|"tts"|"image"`), the slot create/edit type dropdown (slot-modals.jsx:257-264), and slot grouping.

**The same JSON key `type` holds different vocabularies depending on which row produced it.** Registry rows get W7 `chat` (models.py:167); FLM rows get dispatcher `llm` (models.py:240). The **shared lib normalizer** `@/lib/normalizeApiModel` (`ui/src/lib/normalizeApiModel.ts`), applied to *every* row `useModels()` returns (useModels.ts:17,43), **unconditionally discards the server-set `type` and re-derives the dispatcher form from `capabilities`**: `normalizeApiModel` spreads `...m` then overwrites `type: deriveType(caps)` (normalizeApiModel.ts:88), where `deriveType` reads only `capabilities` and never consults `m.type`. So a registry row arrives with W7 `type="chat"` and is **re-derived to dispatcher `type="llm"` client-side, throwing the server value away** — the slots.jsx:478 comment states this verbatim ("derives `type` from the plural `capabilities` array and **discards any backend-set type**"). This *strengthens* the "type fully derivable from capabilities" verdict: the client literally ignores the server's `type`.

There is also a *second, local* `normalizeApiModel` in slot-modals.jsx:53 that DOES trust `m.type` — but it runs on the already-lib-normalized rows (a double pass), so by the time it sees a row the dispatcher `type` is already set; its `derivedType` branch (slot-modals.jsx:64) only fires for rows that bypassed the lib normalizer. **A consolidation must keep the dispatcher vocab** (`llm/embedding/...`) because the SlotCard metrics rows, the create-slot dropdown, and capability slots all hard-code it. The W7 `chat/embed/...` vocab is only a counting bucket and can be derived on demand. FLM rows are the one wrinkle: their `capabilities` is empty (singular `capability` only), so `deriveType([])`→`""` and `modelSlotType` (slots.jsx:484) rescues the type from the singular field.

### 3b. `capability` vs `capabilities` — singular scalar vs plural list
- `CuratedModel.capability` (curated.py:120, scalar) and FLM row `capability` (models.py:241, scalar).
- `Model.capabilities` (model.py:89, list) everywhere else.
- `_model_capabilities` (catalog.py:220) reads BOTH and unions them; `modelSlotType` (slots.jsx:484) falls back from plural-derived `type` to singular `capability` because **FLM seed rows carry singular `capability` and an empty `capabilities`** would leave `type=""`. **Must preserve:** the catalog's union-both behaviour, or migrate curated/FLM rows to the plural list.

### 3c. `backend` vs `backends` vs `runtime` vs `recipe` — four names for "what runs it"
- `backend` (singular): curated + FLM row + slot TOML.
- `backends` (plural): registry Model + detect.
- `runtime`: only `metadata.runtime="flm"` (pull.py) — a third synonym, **dead in the UI** (reads top-level which is never set).
- `recipe`: Lemonade's name for the same thing (`_BACKEND_TO_RECIPE`, gen.py:140 — `vulkan/rocm/cuda/cpu`→`llamacpp`).
- `provider`: a fifth, derived view (`_BACKEND_TO_PROVIDER`, catalog.py:47).

**Must preserve:** the `backends→recipe` collapse (vulkan/rocm/cuda/cpu all → `llamacpp`) for Lemonade, and the `backend→provider` map for the slot form. These are pure functions of `backend` and can stay as derivation tables; the **stored** field should be one (`backends`).

### 3d. FLM id: colon tag `gemma4-it:e4b` vs `-FLM` id `gemma4-it-e4b-FLM`
- **Colon form** `family:size` (e.g. `qwen3-it:4b`, `gemma4-it:e4b`): what `flm pull`/`flm serve` consume; what `flm list -j` reports as `model`; what `is_flm_tag` (flm.py:590) matches (`":" in id`); what `flm_served_models()[].tag` carries.
- **`-FLM` form** `<tag-with-colon→dash>-FLM` (e.g. `qwen3-it-4b-FLM`): built **one-way** at `models.py:215` (`fm["tag"].replace(":","-") + "-FLM"`); is **lemond's** `/v1/models` id (verified: 11 `-FLM` ids served, incl. `qwen3-it-4b-FLM`); is what **npu.toml `[model].default`** stores (`= "qwen3-it-4b-FLM"`).

**There is NO reverse map `-FLM → colon` anywhere in hal0 source** (grep confirmed: `manager.py:1974` sets `flm_tag = model_id` *verbatim*). The two forms live in disjoint worlds: the colon form is the FLM-native/pull/catalog world; the `-FLM` form is the lemond-served/slot-default world. **Must preserve:** the `:`→`-`…`-FLM` transform (lossy: `qwen3-it:4b` and `qwen3-it-4b` would both → `qwen3-it-4b-FLM`) **and** the fact that lemond — not hal0 — owns the reverse resolution. A consolidation that "unifies" the id MUST keep the colon tag for the FLM probe/pull path and the `-FLM` id for the lemond serve/slot-default path, or move the reverse-map into hal0.

---

## 4. Why zero FLM models in the registry yet FLM models serve — the registry-bypass path

**Registry FLM count: 0.** `grep flm /var/lib/hal0/registry/registry.toml` → no `runtime=flm`, no `backends=["npu"]` entry. The 67 registry entries are all GGUF/local. Yet lemond's `/v1/models` serves 11 `-FLM` models including `qwen3-it-4b-FLM`, and npu.toml binds to it.

The bypass is **lemond's own built-in FLM recipe**, entirely independent of hal0's registry:

1. **npu.toml** (`/etc/hal0/slots/npu.toml`) declares `provider = "lemonade"`, `backend = "flm"`, `device = "npu"`, `[model].default = "qwen3-it-4b-FLM"`. The slot is **lemond-mediated**, not native-FLM.
2. The slot manager's `_resolve_model_info` (manager.py:1958) looks up `qwen3-it-4b-FLM` in the registry, gets `ModelNotFound`, logs `slot.model_not_in_registry`, and **proceeds anyway** (manager.py:1985: "not fatal — the toolbox will surface its own load error"). `flm_tag`/`_model_key` are stamped verbatim.
3. hal0 calls lemond's `/v1/load` with model id `qwen3-it-4b-FLM`.
4. **lemond resolves it.** lemond exposes 11 `<tag>-FLM` ids at `/v1/models` (verified live, incl. `qwen3-it-4b-FLM`) and maps `qwen3-it-4b-FLM` → the colon tag → `flm serve`, governed by lemond's `flm` recipe + `[flm].args` (`config.json`: `"flm": {"args": "--asr 0 --embed 0"}`). **Inference (exact discovery path not traced):** since these ids appear in neither hal0's registry nor hal0's generated `server_models.json`, they must originate in lemond's *own* bundled FLM catalog (FLM's `share/flm/model_list.json`, the same file `flm list -j` reads) rather than from anything hal0 emits. The keystone conclusion — hal0 does not register or generate these ids — is proven regardless of lemond's internal enumeration mechanism.
5. hal0's `server_models_gen.py` **emits no `-FLM` ids** (it reads registry.toml, which has zero FLM rows → the `flm` recipe branch at gen.py:268 never fires). Confirmed: deployed `/opt/lemonade/resources/server_models.json` contains **zero** `-FLM` ids and zero `recipe=flm` entries. So the `-FLM` ids come from **lemond's bundled FLM catalog, not hal0's generator.**

**Net:** FLM serving is a **lemond-internal capability** that hal0 *references by id* but does not *register*. hal0's registry is the source of truth for GGUF/local models only; FLM models are owned by lemond's `model_list.json`. The `/api/models` FLM-synthesized block (models.py:209-249) re-discovers them via the host `flm list -j` probe purely so the NPU slot picker has selectable rows — it does **not** write them to the registry. `_register_flm_pulled` (pull.py:688) *would* register an FLM tag (colon form, `backends=["npu"]`, `metadata.runtime="flm"`) but only fires after an explicit `flm pull` through hal0 — which hasn't happened on this host, hence zero rows.

### Dormant vs live (advisor flag — keep these separate in any consolidation)
- **LIVE path:** npu.toml `provider="lemonade"` → lemond `/v1/load` → lemond FLM recipe → `flm serve`. Uses `-FLM` ids.
- **DORMANT path:** `FLMProvider` class (flm.py:128 — `container_spec`/`build_env`/native host probe) is a *separate* native-FLM launcher the deployed runtime does **not** use. It expects the **colon** tag (`build_env` flm.py:154 defaults `qwen3:0.6b`). Feeding it `qwen3-it-4b-FLM` verbatim (as manager.py:1974 does) would break (`flm serve qwen3-it-4b-FLM` is not a valid tag). **The `-FLM` convention is lemond-only.** A consolidation must not delete the colon/`-FLM` distinction on the assumption "FLMProvider handles it" — FLMProvider is not in the live path.

---

## 5. Recommended minimal consolidated model shape + migration sketch

### Minimal shape (8 stored fields; everything else derived on read)
```
Model {
  id:           str          # primary key. For FLM: store the COLON tag (qwen3-it:4b);
                             #   derive the -FLM lemond id on serialization.
  name:         str          # display; defaults to id
  path:         str          # "" for lemond-owned/FLM models (no local bytes)
  size_bytes:   int
  capabilities: list[str]    # SINGLE source of truth. Vocab: chat/embed/rerank/vision/stt/tts/image
  backends:     list[str]    # SINGLE source of truth. Tokens: rocm/vulkan/cpu/cuda/npu/flm/kokoro/...
  hf_repo:      str          # pull coords (empty for FLM/local-only)
  hf_filename:  str
}
```
**Dropped as stored fields (all become pure read-time derivations):**
- `type` → `derive_type(capabilities, vocab)` — one function, two vocabularies selectable by caller (W7 vs dispatcher).
- `device` → `backend_to_device(backends[0])`.
- `provider` → `backend_to_provider(backend)`.
- `recipe` → `backend_to_recipe(backends)` (Lemonade boundary only).
- `runtime` → gone (was `metadata.runtime`, dead in UI; `backend=="flm"` replaces it).
- `owned_by` / `upstream` → derive from `path==""` + an `origin` enum if needed; `owned_by="local"`⇔installed.
- `ns` → `derive_ns(path)` (already a function, model.py:165).
- `capability` (singular) → fold into `capabilities`.
- `backend` (singular) → fold into `backends`.
- `installed`/`downloaded` → ONE name (`installed = path != "" and exists(path)`); FLM uses probe `installed`.

### Per-consumer migration

| Consumer | Today | After |
|----------|-------|-------|
| `routes/models.py` `list_models` | emits 3 shapes; hardcodes `type`/`device`/`owned_by`/`ns` per branch | emit one shape; attach `type`(dispatcher vocab) + `installed` via shared derivation; drop per-branch field-stamping |
| `_classify_type` / `_FLM_DISPATCH_TYPE` | two type maps, two vocabularies | one `derive_type(caps, vocab="dispatcher")`; W7 counter calls `vocab="w7"` |
| `CuratedModel` | singular `capability`/`backend`/`hf_file` | migrate to `capabilities`/`backends`/`hf_filename` (or keep an adapter — `_curated_to_registry_entry` gen.py:414 already bridges) |
| `capabilities/catalog.py` | reads `.backend` AND `.backends`, `.capability` AND `.capabilities` | read only the plural forms; delete the dual-read defensive code (`_backend_variants`, `_model_capabilities`) |
| `server_models_gen.py` | `_resolve_recipe(backends)` | unchanged (recipe stays a derivation at the Lemonade boundary) |
| `slots.jsx` | `isFlmModel` checks `backends`/`backend`/`runtime`/`upstream`; `modelSlotType` falls back to singular `capability`; `s.device==="npu"` | `isFlmModel`= `backends.includes("flm")`; `modelSlotType`= derive from `capabilities`; group by `backends.includes("flm")` — drop the `runtime`/`upstream`/singular-`capability` fallbacks |
| `@/lib/normalizeApiModel` | `deriveType(caps)` discards server `type`, re-derives dispatcher form (normalizeApiModel.ts:88) | once the server emits dispatcher `type` directly, the discard becomes redundant — `deriveType` can be deleted (or kept as a fallback for `capabilities`-only rows); the FLM empty-`capabilities` case must still be handled (singular `capability`) |
| `slot-modals.jsx` (local `normalizeApiModel`, line 53) | second-pass normalizer that trusts `m.type`; `backendToDevice` | keep `backendToDevice` as device-display helper; this local normalizer becomes a no-op once the lib normalizer + server agree on dispatcher `type` — collapse the two passes into one |
| `useModels.ts` `Model` iface | declares `type`/`device`/`runtime`/`ns`/`installed` | drop `runtime` (dead clause); `device` optional (display-only, derived from `backends`); keep `type`(dispatcher)/`installed`/`ns` as derived-but-present |
| npu.toml `[model].default` | `qwen3-it-4b-FLM` (lemond id) | **keep** (lemond owns reverse resolution) OR store colon tag + add a hal0 `-FLM`↔colon map if the native FLMProvider path is ever activated |

### Load-bearing invariants the migration MUST NOT break
1. **Dispatcher `type` vocab** (`llm/embedding/transcription/reranking/tts/image`) — hard-coded in SlotCard metrics, create-slot dropdown, capability slots.
2. **`backends→recipe` collapse** (vulkan/rocm/cuda/cpu → llamacpp) at the Lemonade boundary.
3. **FLM colon-tag for pull/probe** + **`-FLM` id for lemond serve/slot-default**, with lemond owning the reverse map (native FLMProvider is dormant and expects colon).
4. **`path`-shape `ns` rule** (issue #220) — keep `derive_ns` as the single derivation.
5. **`installed`/`downloaded` semantics** = "weights exist on disk" (FLM = probe `installed`); pick one name.
