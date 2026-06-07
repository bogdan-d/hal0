# Shared `hindsight-api` deploy runbook (P1-6)

Platform-owned Hindsight memory engine on CT 105 (10.0.1.142). One shared instance;
banks isolate; Hermes re-points onto it in P5-H. Brain gate stays **OFF** until P2-6.

## Pre-flight (read-only, 2026-06-06)

| Check | Result |
|---|---|
| lemond | up, v10.6.0, `status:ok` on `:13305` |
| extraction model `qwen3-it-4b-FLM` | present in lemond ✅ |
| §4b reranker `bge-reranker-v2-m3-q4_k_m` | present in lemond ✅ (for P2-5) |
| disk `/var/lib` | 347 G free ✅ |
| python | 3.12.3 |
| cognee sidecar `/var/lib/hal0/memory/cognee/hal0_memory_index.sqlite` | **54 rows** (table `hal0_memory_items`) |
| prior spike Hindsight install | GONE (hermes bank abandoned) — clean slate |

⚠ **Cognee store is NOT empty (54 rows).** Spec [Q10] assumed empty → no-op. P2 migration
(`hal0 memory migrate --dry-run`) will report 54 rows; the migrate-vs-start-fresh decision is
a P2 call, not part of this deploy.

## Plan corrections (plan unit was wrong on 3 points — verified vs hindsight-docs 0.7.2)

1. **`HINDSIGHT_API_DATA_DIR` does not exist.** pg0 embedded Postgres lives at `$HOME/.pg0`.
   → control it with `Environment=HOME=/var/lib/hal0/memory/hindsight` (external PG would use
   `HINDSIGHT_API_DATABASE_URL`; we use pg0).
2. **No `serve` subcommand.** The CLI is `hindsight-api --host <h> --port <p>` (plan said
   `hindsight-api serve`).
3. **`/v1` suffix required** on the LLM base_url: `http://127.0.0.1:13305/v1` (plan omitted it).
   Provider value is `openai` for any OpenAI-compatible endpoint (confirmed; the spike's
   `openai_compatible` was the bundled-plugin config.json schema, a different surface).

## Package + topology choice

- `pip install hindsight-api==0.7.2` (**full** — bundles local BGE embedder 384-d + MiniLM
  cross-encoder; only needs the external LLM). Spec-aligned ([Q4] bge-small 384-d) and
  matches the spike's proven 0.7.2.
- Embeddings + reranker LOCAL (no external embed config). Extraction LLM → lemond.
- pg0 embedded (single instance, single `public` schema + `bank_id` discriminator).
- venv: `/var/lib/hal0/memory/hindsight/.venv`; data root `/var/lib/hal0/memory/hindsight`
  (owner hal0:hal0).

## Deploy steps

1. `install -d -o hal0 -g hal0 /var/lib/hal0/memory/hindsight{,/hf-cache}` ✅
2. `python3 -m venv .../.venv` + `pip install hindsight-api==0.7.2` (run as hal0, HOME+HF_HOME
   set, detached + logged to `pip-install.log`) — IN PROGRESS / see below.
3. Install unit: `cp installer/systemd/hindsight-api.service /etc/systemd/system/` (file
   authored on hal0-dev feat branch + copied to CT105 — the feat branch is NOT checked out on
   the runtime).
4. `systemctl daemon-reload && systemctl enable --now hindsight-api.service`
5. Health: `curl -fsS http://127.0.0.1:9177/health`
6. pg0 persistence: `systemctl restart hindsight-api && sleep 5 && curl .../health`

## Results (2026-06-06, deployed)

- Installed: `hindsight-api==0.7.2` + `hindsight-api-slim==0.7.2` + `pg0-embedded==0.14.2`
  + torch 2.12.0 + sentence-transformers 5.5.1 + onnxruntime 1.26.0 + pgvector 0.4.2.
- `/health`: `{"status":"healthy","database":"connected"}` — first boot ~85s (HF model
  download for BGE+MiniLM into HF_HOME + pg0 init + migrations); ~60s on warm restart.
- Migrations: completed for schema `public`, vector extension `pgvector` (exact alembic
  head hash not captured — functional success confirmed in journal; pg0 query deferred).
- **pg0 persists across restart** ✅ — data root `/var/lib/hal0/memory/hindsight/.pg0/`
  (`installation/` + `instances/`) survives `systemctl restart`; health returns
  `database:connected` post-restart.
- Bound: `Uvicorn running on http://127.0.0.1:9177` (pinned, not LAN-exposed).
- lemond `After=` target confirmed real: `hal0-lemonade.service`.
- **Benign log noise:** onnxruntime `pthread_setaffinity_np failed ... Invalid argument`
  — CPU-affinity is restricted inside the LXC; onnxruntime falls back fine, service is
  healthy. Cosmetic; silence later by pinning intra-op thread count if desired.
- No CUDA errors (FORCE_CPU + no NVIDIA device → clean CPU path), no tracebacks.

## [Q5'] FLM extraction schema gap — RESOLVED (official, no patch)

Surfaced at the P1-7 retain smoke: `qwen3-it-4b-FLM` (NPU) ignores `response_format` and
returns a bare JSON **list**; Hindsight's `fact_extraction` rejects it
(`LLM returned non-dict JSON ... list`, 3× retry → `RuntimeError: Fact extraction failed`),
~63s/attempt. There is NO official toggle in 0.7.2 (the spike patched `fact_extraction.py` —
we do NOT carry that unversioned patch).

Models evaluated live:
- `gemma-4-26b-a4b-it-q4kxl` (iGPU GGUF) → returns `{"facts":[...]}` dict ✅ but contends with the 35B primary on the iGPU.
- `qwen3.5-4b-q4kxl` (iGPU, reasoning) → empty content ✗ (reasoning models fail extraction).
- `qwen3-it-4b-FLM` (NPU) → bare list ✗.

### FINAL CHOICE (2026-06-07): NPU extraction via `gemma3-4b-FLM`

Moved extraction to the **NPU** to free the iGPU for the user-facing primary (kills the
P2-6 eviction risk). Path-finding:
- `gemma4-it:e2b` AND `gemma4-it:e4b` (NPU) → **BLOCKED**: `DRM_IOCTL_AMDXDNA_CREATE_HWCTX
  err=-22` ("Alloc hw resource failed"). Both sizes fail identically → Gemma-3n NPU2 arch is
  unsupported by the installed NPU stack (amdxdna `0.7`, NPU FW `1.1.2.65`, FLM `0.9.43`).
  Needs a host NPU driver/firmware update to enable. ~16GB downloaded + parked at
  `/var/lib/hal0/.config/flm/models/Gemma4-E{2,4}B-IT-NPU2/` for if/when that happens.
- `gemma3-4b-FLM` (NPU) → **WORKS** ✅. gemma3 arch loads on this NPU. Emits a ```json-fenced
  `{"facts":[...]}`; Hindsight's `fact_extraction` strips the fence + parses. Live retain+recall
  green (2 on-topic facts, with temporal/entity enrichment).

→ unit sets `HINDSIGHT_API_LLM_MODEL=gemma3-4b-FLM`, `LLM_TIMEOUT=300`.
**Trade-off:** NPU extraction ~160s vs iGPU gemma-26b ~74s — but retain is async/background
(client sends `async:true`), so latency doesn't block, and the iGPU stays free.
**To switch back to iGPU** (faster extraction, accepts contention): set model to
`gemma-4-26b-a4b-it-q4kxl`. **To get gemma4 on NPU:** update the host amdxdna driver/FW.

## Recall sanity (P1-7, recorded not gated)

Live end-to-end on bank `smoketest` (deleted after):
- RETAIN `POST /v1/default/banks/{bank}/memories` `{items:[{content,document_id}]}` →
  `{success:true, items_count:1, usage:{...}}`, ~74s incl. gemma load.
- RECALL `POST /v1/default/banks/{bank}/memories/recall` `{query,max_tokens}` → 0.7s,
  `results` = 2 facts, both on-topic:
  - "The hal0 memory engine was swapped from Cognee to Hindsight in version 0.5."
  - "hal0 performs inference on a Strix Halo iGPU via Lemonade."

## ⚠ Real 0.7.2 API paths (differ from plan + the P1-5 client — MUST fix before P2-5)

Discovered via the live `/openapi.json`:
| op | P1-5 client (WRONG) | real 0.7.2 |
|---|---|---|
| retain | `POST .../{bank}/retain` `{content,...}` | `POST .../{bank}/memories` `{items:[MemoryItem]}` |
| recall | `POST .../{bank}/recall` | `POST .../{bank}/memories/recall` |
| delete | `DELETE .../{bank}/documents/{id}` | ✅ same |

MemoryItem: `{content* , document_id?, tags?, metadata?{str:str}, context?, timestamp?, ...}`.
RetainRequest: `{items:[MemoryItem], async?, document_tags?}`. RecallRequest: `{query*, max_tokens?,
types?, tags?, budget?, ...}`. Recall response: `{results:[...], trace, entities, chunks,
source_facts}`. Retain response: `{success, bank_id, items_count, usage}`.
→ `hindsight_client.py` (53ec956) corrected in follow-up commit.

## ⚠ Carry-forward — MUST handle when executing P2-5 (default flip) / P2-6 (gate on)

The plan's P2-5 task ("flip default engine → hindsight") does NOT mention these. Do them
or the live brain ships broken:

1. **Wire the reranker into the factory — PRECONDITION for P2-5, not a followup.** P2-1 routes
   boot through `provider_from_config`, which builds `HindsightProvider(client=client)` with
   `reranker=None`. The moment the default flips to hindsight, the §4b rerank merge (the
   headline retrieval feature) is DEAD. At P2-5: construct a reranker (lemond's
   `bge-reranker-v2-m3-q4_k_m`, confirmed present) and pass it into `HindsightProvider`, AND make
   `set_rerank_enabled` gate on a field `_rerank_union` actually reads (currently it gates on
   `_reranker is None`, the toggle flag is inert). Verify rerank fires end-to-end before calling
   P2-5 done. (Note: Hindsight's own recall also reranks server-side via
   `HINDSIGHT_API_RERANKER_*`; decide whether the §4b merge reranks the cross-bank UNION on the
   hal0 side, or delegates — don't double-rerank blindly.)
2. **Async retain is UNVERIFIED.** The P1-7 smoke used `async:false` (sync). The shipped client
   (`hindsight_client.py`, 997c1ec) sends `async:true` so `add()` doesn't block ~60-90s on
   extraction. Correct design, but the queued-extraction path was never exercised live — confirm
   a fire-and-forget retain actually lands + becomes recallable before relying on it at P2-5.
3. **iGPU eviction risk — RESOLVED 2026-06-07.** Extraction moved to the NPU
   (`gemma3-4b-FLM`), so it no longer competes with the 35B primary on the iGPU. Remaining
   (minor): NPU extraction shares the NPU with the FLM asr/embed trio + any NPU primary use;
   confirm no NPU contention under load at gate-on. If reverting to iGPU `gemma-4-26b-a4b-it`,
   the original eviction risk returns.

## Rollback

`systemctl disable --now hindsight-api && systemctl mask hindsight-api`. Default engine is
still Cognee; the Hindsight data root is isolated under `/var/lib/hal0/memory/hindsight`.
