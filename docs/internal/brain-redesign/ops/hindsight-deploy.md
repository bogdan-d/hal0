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

## [Q5'] FLM extraction schema gap

FLM ignores `response_format` (no grammar enforcement) → small models can free-form the
fact-extraction output. Resolve the **official** way if it surfaces at P1-7, in order:
(a) grammar/schema-constrained extraction via lemond if available,
(b) a larger instruct model honoring `{"facts":[...]}`,
(c) if a shim is unavoidable, file upstream + pin the version — do NOT carry the spike's
unversioned in-tree wrap-patch.
Status: _deferred until P1-7 retain→extract exercises it._

## Rollback

`systemctl disable --now hindsight-api && systemctl mask hindsight-api`. Default engine is
still Cognee; the Hindsight data root is isolated under `/var/lib/hal0/memory/hindsight`.
