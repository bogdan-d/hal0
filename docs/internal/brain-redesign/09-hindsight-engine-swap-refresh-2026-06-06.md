# 09 — Hindsight Engine Swap + Hermes Convergence (Refresh)

**Status:** DECISION-RESOLVED SPEC. Refreshes docs 00–08 against current state and
locks the decisions needed to ship. Supersedes the *engine-swap* portions of doc 06/07
(Phases 0–2 + the Hermes slice of Phase 5); the wiki tier (06 §5, 07 Phases 3/4/6) is
explicitly out of scope here and the earlier docs stand unchanged for it.
**Date:** 2026-06-06.
**Milestone:** **v0.5 brain re-enablement** — ends with `HAL0_MEMORY_ENABLED=1`, running
Hindsight, Hermes and the platform sharing one brain.
**Reads against:** 06 (architecture), 07 (roadmap), 03 (as-built audit), 05 (landscape),
plus auto-memory `hal0_hindsight_hermes_spike`, `hal0_0.4_memory_gated_off`,
`hermes_home_migration_splitbrain_2026-06-04`.

---

## 0. Why this refresh exists

Docs 00–08 were written 2026-06-02 as *planning, pre-grilling*. Two things have
happened since that reshape the engine-swap plan, and a "don't reinvent the wheel"
review (2026-06-06) re-validated the engine choice against the current field. This
doc folds all three in and resolves the open forks for the engine swap so it can go
straight to an implementation plan.

### What changed since 2026-06-02

1. **Memory shipped OFF.** v0.4 (PR #492) gates the whole subsystem behind
   `HAL0_MEMORY_ENABLED` (default `0`). The platform brain is **dark today**, waiting
   for exactly this redesign. Consequence: there is **no live Cognee traffic to
   regress**, which is what lets us relax the eval gate (D2) and probably makes the
   Cognee→Hindsight data migration a near-no-op (verify on-box, §7).
2. **The Hermes Hindsight spike happened** (2026-06-04, auto-memory
   `hal0_hindsight_hermes_spike`). Hindsight already runs on CT 105 — but **inside
   Hermes' venv** (`mode: local_embedded`, bank `hermes`, extraction →
   `qwen3-it-4b-FLM` on the NPU via lemond:13305). This de-risks deployment (we have
   real operational config) **but** points at *two* Hindsight installs unless we
   converge (D1, P5-H).
3. **Build-vs-adopt review.** A fresh mid-2026 landscape scan (14 systems) + a
   deep-dive of the Hermes-specific `ClaudioDrews/memory-os` confirmed: we are **not**
   reinventing the wheel — Hindsight *is* the off-the-shelf wheel, and it wins on
   merits, not incumbency (§2).

---

## 1. Build / Adopt / Cut

The refresh **shrinks** the custom surface. The headline: don't build a memory engine,
adopt one; build only the thin, mandatory trust seam in front of it.

| | Decision | Why |
|---|---|---|
| **Adopt off-the-shelf** | **Hindsight** as the engine — native MCP (`/mcp`) + REST (`:8888`) + embedded Postgres + consolidation, all in one process, fully local. | Wins the 2026 landscape scan (§2). |
| **Build — thin, justified** | `MemoryProvider` ABC + `HindsightProvider` + the `X-hal0-Agent`→bank **ACL shim**, behind hal0's *existing* `/mcp/memory` + `/api/memory/*` front door. | The ACL shim is **mandatory** (Hindsight has no per-caller→bank enforcement, §3). The ABC doubles as **anti-lock-in insurance** (Mem0 is a real Apache-2.0 #2). |
| **Adopt the *idea*, not the code** | A **ground-truth precedence** stanza (Memory-OS Layer 7) in Hermes' identity docs, refined for a shared brain. | Makes the agent *trust* recalled memory; ~10 lines, not a subsystem (§4). |
| **Cut / defer** | The custom **wiki tier + gated promotion** (06 §5, 07 P3/P4/P6). | Out of scope for v0.5; Memory-OS confirms the auto-wiki is the fragile, unproven part. The dossier stands for a later milestone. |
| **Don't carry** | The FLM-schema **wrap-patch** hack from the spike. | Route to an upstream fix (grammar-constrained extraction or a larger extraction model) per the standing "third-party official fix first" rule (§6, [Q5']). |

---

## 2. Engine decision: Hindsight (confirmed on merits)

The mid-2026 scan scored every candidate against hal0's hard constraints: fully local
/ no-CUDA on Strix Halo; exposes **MCP and/or REST** so multiple consumers share one
brain; multi-agent namespacing; episodic→semantic **consolidation** (not naive
append-only RAG); and — decisive for this hardware — its **core function must not depend
on reliable structured-JSON from a <32B local model**.

**Hindsight is the only candidate that satisfies all of them at once:** one process
exposes both REST and a native MCP server, runs against a local OpenAI-compatible
gateway with CPU embed + CPU cross-encoder rerank, light footprint (FastAPI + embedded
Postgres), real consolidation (facts → observations → auto-updating mental models), and
**recall runs with zero LLM** — so a weak extraction model degrades *ingest quality* but
never *breaks retrieval*. MIT-licensed.

**Runners-up and why they lose here:**
- **Mem0** (Apache-2.0, ~58k★, OpenMemory MCP) — the one credible alternative; real
  ADD/UPDATE/DELETE consolidation. **Documented as the sanctioned fallback** behind the
  ABC. Pick it only if Hindsight's small-startup backing becomes a risk.
- **Graphiti / Cognee** — disqualified for *this hardware*: both self-admit ingest
  fails / emits bad schemas without structured-output models — hal0's exact failure mode.
- **Supermemory** — cloud-gated (self-host is enterprise-only).
- **Letta** — an MCP *host* with agent-centric memory, not a neutral memory *server*.
- **`ClaudioDrews/memory-os`** (the Hermes-specific 7-layer system) — **validates the
  design but is not adoptable**: no MCP/REST (Hermes-plugin-only), dense embeddings
  hardcoded to a cloud provider (OpenRouter), no multi-agent namespacing, 6 days old,
  no tests/benchmarks. Treat as a *reference architecture / parts bin* (we take its
  Layer-7 idea, §4).

> **Plan stays engine-neutral in structure** (the ABC), but **Hindsight is THE engine**.
> The seam is what makes "are we over-building?" answer itself: it's the not-reinventing-
> the-wheel insurance that lets us swap engines without touching a single consumer.

---

## 3. Architecture: one front door, one shared engine, a mandatory trust seam

```
   Hermes        external Claude Code      pi-coder        dashboard
     │ (hal0-memory plugin)   │ (MCP)         │ (MCP)         │ (REST)
     └───────────────┬────────┴───────────────┴───────────────┘
                     ▼
        hal0-api  ──  THE ONE FRONT DOOR
          /mcp/memory   +   /api/memory/*          (unchanged contract)
          │
          │  namespace.py:  server-trusted  X-hal0-Agent / Bearer  →  allowed banks
          │                 (ACL: read own private + shared, never another's private)
          ▼
        MemoryProvider (ABC)  ──►  HindsightProvider   [fallback: Mem0Provider, PgVectorProvider]
                                        │
                                        ▼
        ONE shared hindsight-api  (systemd unit on CT 105, embedded pg0)
          banks:  shared · private:<agent> · project:<id> · agents · hermes
```

### D1 — Topology: ONE shared platform-owned `hindsight-api`

A single `hindsight-api` systemd unit on CT 105 (embedded pg0 under
`/var/lib/hal0/memory/hindsight/`). The platform MCP **and** Hermes both point at it;
**banks** provide isolation. Rationale: re-pointing Hermes (the chosen scope) only buys
the "one brain" story against a shared instance; one store = one backup, one HF cache,
one upgrade/wrap surface. Cost: migrate the spike's in-venv `hermes` bank into the
shared store and retire `local_embedded` (P5-H).

### The ACL shim is mandatory — isolation ≠ authorization

Be precise here, because Hindsight *does* ship real isolation primitives and it's easy to
mistake them for access control. Hindsight has **two** isolation layers: **banks**
(`developer/api/memory-banks.md`: *"Banks are completely isolated from each other —
memories stored in one bank are not visible to another"*) and **tenants** (separate DB
schemas, e.g. `tenant_acme`). What it does **not** ship is an **authorization policy** —
a rule mapping *a given caller* to *the banks it may address*. The two are different:

- **Isolation** (banks/tenants do this): bank A's data can't leak into bank B. ✅
- **Authorization** (not shipped): *which* caller may open *which* bank.

Evidence (`developer/mcp-server.md` + `memory-banks.md`): the MCP server at `/mcp` is
**open by default**; enabling auth gives a **single server-wide API key**
(`HINDSIGHT_API_TENANT_API_KEY`), and the **bank is caller-chosen** via the
`/mcp/{bank_id}/` path or an `X-Bank-Id` header. `mcp_enabled_tools` is a per-bank tool
allowlist *for everyone on that bank*, not per-caller. Tenants are all-or-nothing
separate schemas, so they **can't** express hal0's "agents share `shared` but isolate
`private:*`" (mapping each agent to a tenant would sever the shared bank). Net: a holder
of the one key can set `X-Bank-Id: private__hermes` and read Hermes' private memory —
bank isolation only stops Hermes' bank from bleeding into *another* bank, not from being
*opened* by another caller.

hal0's rule — *"an agent reads its own private + `shared`, never another agent's
private"* — is a **cross-bank policy within one tenant** that neither primitive enforces.
`namespace.py` already implements it: it resolves a **server-trusted** `X-hal0-Agent`/
Bearer identity into the allowed banks (fail-open-empty on foreign private). **That
policy must be hal0-authored regardless of engine.** It can live in **either** place:
- **(recommended) the hal0-api front door** — reuses `namespace.py`, and also carries the
  `HAL0_MEMORY_ENABLED` gate, the stable `/api/memory/*` + `/mcp/memory` contract, and the
  new `recall` route. One trusted choke point.
- **a custom Hindsight `TenantExtension`** — Hindsight's pluggable auth point; a Python
  extension that reads the trusted identity and enforces the allow-list inside Hindsight's
  process. Viable, but it's net-new code to write/maintain in-engine and it wouldn't cover
  the gate/contract/recall-route, so the front door is the better home.

Either way, "just point consumers at Hindsight's native MCP with no hal0 layer" is unsafe
for multi-agent — the thin shim earns its keep.

> **Vendor confirmation.** Hindsight's *own* canonical multi-agent recipe
> (cookbook `support-agent-shared-knowledge`) ships **no access control** — it
> *"assumes a trusted caller,"* notes *"all users can theoretically read all banks if they
> knew the bank IDs,"* and relies on *"logical separation, not cryptographic
> enforcement."* It also does cross-bank reads as **client-side orchestration** (separate
> `recall(bank_id=...)` per bank, merged in the client). Both points are by design, not a
> gap — which is exactly why the trusted-identity→allowed-banks policy and the multi-bank
> fan-out are hal0's job (front door + `HindsightProvider`), not the engine's.

### Namespace → bank mapping (06 §4, unchanged resolver)

| hal0 namespace | Hindsight bank |
|---|---|
| `shared` | `shared` |
| `private:<agent>` | `private__<agent>` (`:`→`__`) |
| `project:<id>` | `project__<id>` (auto-create on first use) |
| `agents` | `agents` (identity cards, ADR-0011) |
| Hermes' own | `private__hermes` + `shared` (see P5-H) |

---

## 4. The two senses of "source of truth"

A shared brain has to win on **both**, and they're solved in different phases.

### 4a. Storage source of truth (the engine swap, P0–2)

Exactly one active memory provider holds the canonical memories. Enforced by:
single-provider config, a verified data migration into the shared engine, and a
one-release Cognee fallback flag. No background second store (see P5-H — we do **not**
keep Hermes' default memory running).

### 4b. Cognitive source of truth — ground-truth precedence (Memory-OS Layer 7)

The engine swap does **not** make an agent *use* what it recalls. Memory-OS's Layer 7
documents the failure: an agent ignores injected memory and re-derives via tool calls
because "injected memory had no explicit rank." The fix is a precedence ladder in the
agent's identity docs. **We adopt the idea, refined for a shared (poisoning-exposed)
brain** — hard rules sit *above* recalled memory, not below it:

1. **Safety / identity rules** (SOUL, rulebook, CLAUDE.md-class) — never overridden by a recalled memory
2. **Live system / tool state** (terminal, tool output)
3. **Recalled memory (shared brain)** — authoritative for project knowledge/decisions, **above model priors**
4. **Official documentation** — wins for version-specifics
5. **Training priors** — reference only; always verify

This **decomposes onto features we already have**: Hindsight **directives**
(priority-ordered bank instructions) + **mental models** (checked first) provide the
*within-memory* ranking; Hermes' **SOUL.md** provides the *rules-vs-memory* ranking. So
it is a ~10-line stanza (P5-H), not a new subsystem. Same idea later extends to external
consumers via the MCP tool descriptions / a context note (deferred).

---

## 5. Resolved decisions (index)

| # | Decision |
|---|---|
| Scope | Refresh the dossier into a decision-resolved roadmap. |
| Boundary | **Phases 0–2 + the Hermes-convergence slice of Phase 5.** Wiki/promotion deferred. |
| Engine | **Hindsight** (adopted). Mem0 = documented fallback behind the ABC. |
| **D1 Topology** | **One shared platform-owned `hindsight-api`** on CT 105; banks isolate; Hermes re-points onto it. |
| **D2 Eval gate** | **Relaxed** to conformance + a recall **sanity** check on a seeded fixture corpus (no graded δ-eval, and no Cognee "parity" baseline — the platform store is expected empty). Brain is OFF — nothing to regress; spike proved operability; we adopt for the consolidation upgrade path, not a benchmark margin. |
| **D3 Wiki** | **Cut** from this milestone. |
| Front door | Keep `/mcp/memory` + `/api/memory/*` with `MemoryProvider` ABC + `HindsightProvider` + ACL shim behind it. |
| Source of truth | **Storage** (single provider + migration, P0–2) **and cognitive** (Layer-7 precedence stanza, P5-H). |
| Wrap-patch | Don't carry — route to upstream fix ([Q5']). |

---

## 6. Phase plan (4 slices, each leaves `main` shippable)

### P0 — Seam & safety net  *(unchanged from 07 Phase 0; no gate, ships clean)*

**Goal.** Promote the implicit five-method `CogneeWrapper` contract into an explicit
`MemoryProvider` ABC + parametrized conformance suite, route the one construction site
(`api/__init__.py:1108`) through a `provider_from_config(cfg)` factory, and fix the
latent Hermes `_client.py` 404. **Zero behaviour change** — Cognee stays the only live
engine.

**Work items.**
- `src/hal0/memory/provider.py` — ABC + value types (06 §3): `MemoryItem`,
  `AddResult`, `ListPage`, `DeleteResult`, `GraphStatus`, `Mode`; core five
  `add/search/list_items/delete` + `graph_status/set_graph_enabled/set_rerank_enabled`;
  optional `recall/reflect/consolidate/register_compiled` with safe defaults. Core five
  **byte-compatible** with `CogneeWrapper` (audit §5) so no call site changes.
- `CogneeWrapper(MemoryProvider)` — declare conformance, no logic change.
- `provider_from_config()` in `src/hal0/memory/__init__.py` — returns
  `CogneeWrapper(...)` for now; engine branch added in P1.
- `PgVectorProvider` stub — third conformance implementation + P2 boot fallback.
- `tests/memory/test_provider_contract.py` — parametrized suite asserting namespace
  isolation, `private:` write rejection, tag-AND, date-range, delete semantics,
  fail-open-empty foreign-private read, and the `graph_status()` payload shape.
- Fix `src/hal0/agents/hermes/plugins/memory_cognee/_client.py` 404s (audit §4.2):
  `list_items` → `GET /api/memory/list`; `delete` → `POST /api/memory/delete` with
  `{ids}`. Add a route-path test against the real router.
- CI: wire the contract suite into the **default** gate; run `ruff format --check`.

**Exit.** Contract suite green for Cognee + PgVector + fakes; app boots; `add→search→
list→delete` byte-identical to pre-change over both transports; `_client.py` route test
green. **Rollback:** revert the one construction line. **Risk:** low, no open-Q.

### P1 — Deploy Hindsight for real (not shadow) + parity smoke

**Goal.** Stand up the **one shared** `hindsight-api`, implement `HindsightProvider`
against the ABC, wire embed/rerank/extraction to existing hal0 slots, and validate with
conformance + a recall **sanity** check on a seeded fixture corpus. (D2 relaxed the 07
δ-eval gate; this is a *real* deploy, not a dark shadow install, because there's no live
Cognee to shadow.)

**Work items.**
- **Deploy `hindsight-api`** as a systemd unit beside lemond. Data root
  `/var/lib/hal0/memory/hindsight/` with **embedded pg0** (not a separate PG daemon).
  Fold in the spike's hard-won config (auto-memory `hal0_hindsight_hermes_spike`):
  - **Writable `HF_HOME`** (default HF cache symlinks to read-only `/mnt/ai-models` and
    dies downloading `bge-small-en-v1.5`) — point at a hal0-writable dir.
  - **Non-empty `llm_api_key`** placeholder (empty key crash-loops the daemon even for
    no-auth lemond) — `"lemonade-local-noauth"`.
  - **Dynamic-port awareness** — the daemon may not bind the documented default; capture
    the actual port / pin it.
- **Wire to slots** (06 §4):
  - Embeddings → the **embed capability slot** (OpenAI-compatible/TEI). **Record the
    slot's actual model + dim now**; if ≠ Cognee's `bge-small-en-v1.5` (384-d), a
    re-embed on cutover is required ([Q4], assume CPU, validate).
  - Rerank → the **`:8086` rerank slot** (`bge-reranker-v2-m3`) via Hindsight's external
    reranker provider; fallback to its CPU MiniLM cross-encoder or pure RRF.
  - Extraction LLM → `HINDSIGHT_API_LLM_PROVIDER=openai` →
    `HINDSIGHT_API_LLM_BASE_URL=http://127.0.0.1:13305` (lemond). Use an **instruct**
    model (spike: `qwen3-it:4b` works ~45–90s; reasoning/rambling small models time out).
- **`src/hal0/memory/hindsight_provider.py`** — core five + `recall` (real TEMPR
  token-budgeting), `reflect`, `consolidate`, `register_compiled`. **Engine owns its
  filtering** — map hal0 `tags`→Hindsight tag filter, dataset→bank, date-range→engine
  (retire the SQLite sidecar as the filter source). `MemoryItem.id` is the join key.
- **Multi-bank recall fan-out (net-new — Hindsight has no server-side cross-bank query).**
  A hal0 recall expects results from the caller's **own `private:*` + `shared`** (+ any
  `project:*`) *together*, but Hindsight recall is **per-bank, client-orchestrated** — its
  own shared-knowledge recipe calls `recall(bank_id=...)` once per bank and **merges
  client-side** (cookbook: `support-agent-shared-knowledge`). So `HindsightProvider.recall`
  /`search` must: resolve the caller's allowed banks (the ACL seam already does this) →
  **fan out parallel `recall` calls** → **merge under one token budget**. Merge *ordering*
  follows the §4b precedence ladder (curated/`shared` mental-models + observations ranked
  above raw private facts), tying recall back to the ground-truth hierarchy. Decide the
  cross-bank merge strategy (concatenate-by-score vs re-rank the union via the `:8086`
  reranker) and pin it in the conformance suite.
- **`provider_from_config`** gains `engine = "cognee" | "hindsight" | "mem0" | "pgvector"`
  (default still **cognee** in P1) + a degrade ladder: Hindsight unavailable at boot →
  pgvector/no-op, tools return `available:false`, dashboard shows "no engine".
- **[Q5'] Upstream fix for the FLM schema gap, not the wrap-patch.** The spike's
  `local_embedded` extraction needed a one-line tolerance patch because FLM ignores
  `response_format` and returns a bare list, not `{"facts":[...]}`. For the platform
  instance, resolve this the standard way **before** relying on extraction:
  (a) grammar-/schema-constrained extraction via lemond if available, or
  (b) a larger instruct extraction model that honors the schema, or
  (c) if a tolerance shim is unavoidable, file it upstream and pin the version — do not
  carry an unversioned in-tree patch.

**Exit (two-part, no graded eval).**
1. **Conformance:** `HindsightProvider` + runnable `PgVectorProvider` pass
   `test_provider_contract.py` unmodified; `hindsight-api` boots as a unit; pg0 persists
   across restart; embed/rerank/extraction health-checked against the right slots.
2. **Recall sanity:** seed a small fixture corpus, then a fixed query set returns sane,
   on-topic results with acceptable latency (sanity, not benchmark; no Cognee baseline to
   compare against). Recorded, not gated on a delta.

**Rollback.** Nothing flipped — stop/mask the unit; default still Cognee; Hindsight data
root is isolated. **Risk:** [Q4] re-embed if embed model differs; [Q5'] extraction
quality tracks the local model (designed for recall-without-LLM so it degrades, not
breaks).

### P2 — Cutover + re-enable the gate

**Goal.** Flip the default to Hindsight, map namespaces→banks behind the ACL shim,
migrate any existing Cognee/sidecar data, **turn memory back on**
(`HAL0_MEMORY_ENABLED=1`), and keep Cognee behind a one-release fallback.

**Work items.**
- Implement + test the bank mapping (§3 table) in `HindsightProvider`; the
  `namespace.py` resolver is unchanged, now mapping to banks.
- **Migration ([Q10] — likely small).** The platform Cognee store has been dark (memory
  OFF since v0.4), so **first measure** (§7): if the store + sidecar are empty/stale,
  migration is a **no-op** and the risk evaporates. If non-empty: a `hal0 memory migrate
  --dry-run` reports rows mapped/unmapped, then a live copy-into-Hindsight + verify
  (count + spot recall parity). Cognee data stays read-only during migration.
- Flip `provider_from_config` default → `hindsight`; rename `app.state.memory_wrapper`
  → `app.state.memory_provider` across readers.
- **Expose `recall`/`retain` on the front door (net-new — do not skip).** `/api/memory/*`
  + `/mcp/memory` are the **Cognee-era CRUD contract** (`add/search/list/delete`).
  Hindsight's value is `recall` (TEMPR, token-budgeted, observation hierarchy) and
  `retain` (extraction → consolidation). If consumers keep calling `search`/`add`,
  `HindsightProvider.recall`/`retain` are never reached and the milestone silently ships
  "a better vector store" instead of the upgrade. So: **add a `recall` route**
  (`POST /api/memory/recall` + an MCP `recall` tool) the plugins call, and **confirm
  `HindsightProvider.add` routes to `retain`** (so background consolidation fires) rather
  than a dumb insert. `search` stays for back-compat; `recall` is the new preferred path.
- **Flip `HAL0_MEMORY_ENABLED=1`** (api.env + systemd) — backend re-inits, `/api/status`
  `memory_enabled` flips, dashboard nav returns. *(New deliverable — the gate didn't
  exist when the dossier was written; auto-memory `hal0_0.4_memory_gated_off`.)*
- Fallback flag `[memory] engine = "cognee"` reverts for one release; Cognee +
  `cognee_wrapper.py` stay in-tree (deletion deferred).
- Retire the sidecar as the filter source once verify passes.

**Exit.** Migration within agreed loss threshold (or no-op); default boot uses Hindsight;
`add/search/list/delete` green over both transports; namespace isolation + `private:`
rejection + foreign-private fail-open-empty pass against the live engine; the gate is
ON; the fallback flag cleanly reverts to the untouched Cognee store. **Rollback:** set
`engine = "cognee"` + restart → instant revert (Cognee never mutated).

### P5-H — Hermes convergence (the Hermes slice of 07 Phase 5)

**Goal.** Make Hermes use the **one shared** brain as its single source of truth — both
storage and cognitive — and **retire the spike's `local_embedded` instance**. Answers
the two convergence questions directly.

**Do we switch Hermes back to its default memory in the background? → NO.** Two systems
both capturing recreates the dual-source drift we're eliminating. Exactly one active
provider; Hermes' generic built-in memory stays off.

**How do we force the new one as source of truth? → both halves:**

*Storage:*
- Set Hermes `config.yaml` `memory.provider` to the **`hal0-memory`** plugin (the
  renamed `hal0-cognee`/`memory_cognee` plugin that already talks to hal0-api
  `/api/memory/*`). One active provider = one source. Hermes memory now flows
  `hal0-memory plugin → /api/memory/* (ACL + namespace) → HindsightProvider → shared
  hindsight-api`, landing in `private:hermes` + `shared` — *inside* the unified
  namespace, not a sibling bank. (Routing through hal0-api, not direct-to-Hindsight,
  preserves the single ACL'd front door.) **Depends on the P2 `recall` route** — the
  plugin must call `recall`, not `search`, or Hermes gets the storage swap without the
  recall/consolidation upgrade.
- **Retire `local_embedded` — TWO respawn guards, flip provider FIRST (probe-confirmed
  2026-06-06).** The spike is *dormant, not retired*: `provider: hindsight` is still set
  (`$HERMES_HOME/config.yaml:315`) and the embedded **Postgres 18.1.0** (pid orphaned to
  init, `127.0.0.1:5432`) is still up, so **any** retain/recall lazily respawns pg +
  `hindsight-api` via `hindsight_embed/daemon_embed_manager.py`. [Q8] is real and needs
  **both** guards removed: **(a) flip `memory.provider` off *first*** (revert backups exist:
  `config.yaml.bak-pre-hindsight-*`) **and (b) `pip uninstall hindsight-embed`** (+
  `hindsight-all/-api-slim/-client`). Then remove `$HERMES_HOME/hindsight/config.json`; the
  `20-hindsight.conf` drop-in (**keep `21-hermes-subpackages.conf`** — unrelated) +
  `daemon-reload`; the two `/usr/local/sbin/hal0-hindsight-*-patch.py` ExecStartPre scripts;
  **explicitly stop the orphaned pg** (reparented to init — restarting the hermes unit won't
  kill it) and delete `/var/lib/hal0/.pg0` (61 MB) + `.hermes/hf-cache` (216 MB). The exact
  ordered command checklist lives in the plan (task `P5H-RETIRE`).
- **Start fresh — no data migration (decided 2026-06-06).** Abandon the spike's embedded
  `hermes` bank rather than migrating it. Hermes begins accumulating into the shared
  instance's `private:hermes` + `shared` banks from zero (banks auto-create on first use).
  **Accepted trade-off:** lose ~2 days of low-value spike memories (rough wrap-patch / NPU
  extractions) in exchange for a clean cutover with **zero pg-level schema/version-compat
  risk**. The spike's embedded pg is left orphaned, then removed via the retirement
  checklist below. (This is why the [Q10]/`hermes`-bank-migration risk drops out of the
  plan: there is no migration vehicle to get wrong.)
- **Lock the canonical config** (`HERMES_HOME=/var/lib/hal0/.hermes/config.yaml`) against
  the root-clobber regression (spike gotcha #5 / `hermes_home_migration_splitbrain`):
  running hermes as root rewrites `config.yaml` `root:root 0600` and silently falls back
  to the default provider. Keep the self-guarding `/usr/local/bin/hermes` wrapper; verify
  ownership stays `hal0:hal0`.
- Wire recall depth: `Hal0…Provider.prefetch(query)` → `recall(types=['observation',
  'world'], max_tokens=…)` instead of flat `search(limit=5)`; `sync_turn`/`on_memory_write`
  → Hindsight `retain` (background consolidation now actually runs).

*Cognitive (Layer-7 precedence):*
- Add the **ground-truth precedence stanza** (§4b ladder) to Hermes' **SOUL.md**, and
  encode the within-memory ranking as Hindsight **directives** on the `hermes`/`shared`
  banks (and a top-priority mental model if useful). This is what makes Hermes *trust*
  the recalled block instead of re-deriving — the cognitive half of "source of truth."

**Exit.** Hermes runs with a single `hal0-memory` provider; the `local_embedded` install
is gone (no second daemon, no wrap-patch, embedded pg retired); Hermes' `private:hermes`/
`shared` banks exist in the shared instance and accept new writes (**started fresh** — no
spike data carried over); a live turn shows `prefetch` returning a recalled block that
Hermes acts on (no redundant re-discovery); `config.yaml` survives a root TUI session
without clobber.
**Rollback:** per-surface — provider can revert; the SOUL.md stanza is additive.

---

## 7. On-box pre-flight checklist (run before P2; read-only)

Grounds the migration/re-embed sections in real numbers instead of TBDs.

1. **Platform Cognee/sidecar row counts** — is `/var/lib/hal0/memory/cognee` + the
   `hal0_memory_index.sqlite` sidecar empty/stale? If yes → migration is a **no-op**
   (likely, given memory has been OFF since v0.4).
2. **Embed-slot model + dim** vs Hindsight's expectation — if ≠ `bge-small-en-v1.5`
   (384-d), schedule a re-embed ([Q4]).
3. **Hermes plugin remote mode / `:9077`** — confirm the upstream Hindsight plugin can be
   removed cleanly and that nothing re-spawns a daemon once `local_embedded` is gone ([Q8]).
4. **Spike `local_embedded` retirement surface** — ✅ *answered 2026-06-06* (probe).
   Exact ordered removal + the two-guard respawn ([Q8]) are in the P5-H retire bullet and
   plan task `P5H-RETIRE`. We start fresh — no data migration — so the embedded pg's
   contents don't matter, only that it's cleanly retired.
5. **Hindsight version pin** — ✅ *answered 2026-06-06* (probe). Spike venv:
   `hindsight-all/-api-slim/-embed 0.7.2`, `hindsight-client 0.6.1`, embedded **Postgres
   18.1.0**, alembic head **`c1d2e3f4a5b6`**. Pin the shared platform `hindsight-api` to
   **0.7.x** (same alembic head) for a known schema; record [Q5'] extraction behaviour.
   Storage on this build = single `public` schema + `bank_id` discriminator (a tenant-schema
   model also exists — relevant only if the shared instance is multi-tenant).

---

## 8. Deferred (still open; not blocking this milestone)

- **Wiki tier + gated promotion** (06 §5, 07 P3/P4/P6) — the dossier stands; revisit
  after v0.5 ships and real usage shows whether the engine's observations/mental-models
  already cover the "curated knowledge" need (the YAGNI counter-case, 05 §3).
  - **Lighter-weight candidate surfaced by the cookbook (`support-agent-shared-knowledge`):**
    that recipe builds a curated shared-knowledge layer **purely with banks** — a separate
    `support-learnings` bank that only accepts writes via an **explicit gated
    `promote_learning()`** call (no auto-escalation), distinct from the raw `shared`
    episodic bank. A hal0 analogue — a `shared-curated` (or `agents`-adjacent) bank fed
    only through a gated `promote` route on the front door, recalled at the top of the §4b
    hierarchy — could deliver "trusted, human-gated shared knowledge" **without** the
    markdown wiki, the QMD→engine swap, or the promotion-to-pages pipeline. Evaluate this
    against the full wiki tier before committing to Phase 3/4: it may collapse most of that
    scope into "one more bank + one gated route." (Trade-off: loses the wiki's human
    legibility/git-auditability — banks aren't a notebook a person reads/edits directly.)
- **External-consumer Layer-7** — extend the precedence idea to external Claude Code via
  MCP tool descriptions / a context note ([Q7] default-read posture).
- **Bank-templates as a hal0 primitive** (06 §8) — persona-bound bank provisioning.
- **Mem0 fallback** — implemented only if Hindsight's backing becomes a risk; the ABC
  keeps the option open at near-zero standing cost.

---

## 9. Sources

- Hindsight docs (local `hindsight-docs` skill): `developer/mcp-server.md` (MCP at `/mcp`,
  open-by-default, single server-wide key, caller-asserted bank — the ACL-shim basis),
  `developer/api/memory-banks.md` (bank/tenant isolation primitives; `mcp_enabled_tools`;
  directives), `developer/api/*`, `references/best-practices.md`.
- Hindsight cookbook: `recipes/support-agent-shared-knowledge`
  (https://hindsight.vectorize.io/cookbook/recipes/support-agent-shared-knowledge) — the
  vendor's canonical multi-agent pattern: per-agent private + shared + gated `learnings`
  banks, **client-side** multi-bank recall, gated `promote_learning`, and an explicit
  trusted-caller / no-access-control assumption. Basis for the §3 confirmation, the P1
  fan-out work item, and the §8 banks-only curated-layer alternative.
- Auto-memory: `hal0_hindsight_hermes_spike` (spike config + gotchas + wrap-patch),
  `hal0_0.4_memory_gated_off` (the gate), `hermes_home_migration_splitbrain_2026-06-04`
  (config clobber), `hal0_brain_redesign_planning_2026-06-02`.
- Dossier docs 03 (audit), 05 (landscape), 06 (architecture), 07 (roadmap), 08 (grilling).
- Build-vs-adopt review (2026-06-06): mid-2026 landscape scan (Hindsight/Mem0/Graphiti/
  Cognee/Letta/txtai/Supermemory/MemoryOS/A-MEM/MIRIX/Memobase/Memori) + `ClaudioDrews/
  memory-os` deep-dive (no MCP/REST, cloud embeddings, no namespacing — reference only)
  + its `layers/07-ground-truth.md` (the Layer-7 precedence idea adopted in §4b).
