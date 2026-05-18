# FirstRun prototype — IA variants

## The question

The hal0 FirstRun wizard was written when the only install-time decision was
"pick a primary chat model." With the new **Capability Slots** system (embed /
voice / img + NPU-as-backend), the wizard is badly underspecified — a fresh
install lands with every capability disabled and the operator has to wander
into `/slots` to make anything work.

**What information architecture should the new wizard use?** Three variants
disagree on this; pick one, fold its render into `views/FirstRun.vue`, delete
this directory.

## What's locked already (do not re-litigate)

These IA decisions were settled in the grilling session before prototyping:

| | Decision | Reason |
|---|---|---|
| Model dirs | Confirm-only default + free space, NO add-more UI at install | Multi-root is power-user; Settings owns it later |
| Voice TTS default | OFF | Wait for voice-agent UX before defaulting ON |
| Image gen default | OFF | 7–12 GB pull, niche on day one |
| Rerank placement | Advanced disclosure inside embed row | Keeps capabilities step at 3 clean rows |
| Re-entry | Pre-fill from `/etc/hal0/capabilities.toml`, idempotent | Matches existing password-skip precedent |

**Meta-rule**: capability toggle = **run state**, not config gate. Model
picker stays visible on every row regardless of toggle state.

## The variants

All three honor the locked IA. They disagree on **structure** only.

- **L — Legacy** (current 5-step wizard, kept as production fallback + visual baseline)
- **A — Linear wizard, more steps**
  8 discrete screens, one decision per screen. Step indicator across the top.
  Comfort food for first-timers; lots of clicks for power users.
- **B — Progressive single-page**
  Collapsible sections on one scroll, sticky bottom Install bar with live
  totals (download / disk free / model count). Power users see everything.
- **C — Two-pane, hardware-grounded**
  Left rail = live hardware + live disk projection + "what lands where" rollup
  that updates as the user picks. Right rail = question stack flowing
  top-to-bottom. Decisions feel grounded in physical reality.

## How to evaluate

```
http://hal0.local:5173/firstrun?variant=A
http://hal0.local:5173/firstrun?variant=B
http://hal0.local:5173/firstrun?variant=C
http://hal0.local:5173/firstrun?variant=L   # baseline
```

Floating bottom-center switcher cycles between variants; arrow keys work too.

Things to try in each:
- Flip embed on → check that the model picker stays visible whether on or off
- Toggle img on → see the disk projection update (variant C makes this obvious;
  variant B updates the sticky bar; variant A only shows on license step)
- Set a tiny `modelDir` like `/tmp` and add several caps → confirm
  the disk-fit gate blocks the Install button
- Click Install → fake multi-bar progress runs (no real download — variants
  stub `applyAll()` to keep the prototype throwaway)

## What's stubbed

- `applyAll()` simulates the pull with `setTimeout` — does not POST anywhere.
- Password is collected into form state but not POSTed.
- HF token is collected but not persisted.
- Model storage dir is editable but does not call any endpoint.

Only the **reads** are live:
- `GET /api/hardware` → smart defaults + left-rail probe (variant C)
- `GET /api/install/state` → first_run flag (decides smart-defaults vs hydrate)
- `GET /api/install/curated-models` → primary chat picker
- `GET /api/capabilities` → backends, catalogs, current selections (for re-entry pre-fill)
- `GET /api/auth/status` → auto-skip password step when already set

## The interesting feedback

Per the prototype skill, the actual design is usually **"I want the X from
A with the Y from C."** Expect:

- "I want C's left rail with A's step structure"
- "I want B's sticky bar but only show it on the licenses section"
- "I want C but without the two-pane on mobile" (C already collapses to one
  column at <880px; verify it feels right)

Note them on this file before folding the winner in.

## Capture (fill in when chosen)

Winner: _TBD_
Why: _TBD_
What to steal from the losers: _TBD_

## Cleanup checklist

When a winner is picked:

1. Fold winner's render into `views/FirstRun.vue` (replacing the shell + Variant import).
2. Wire its mutations to real endpoints (the prototype stubs `applyAll`).
3. Delete `components/firstrun-proto/` (this whole directory).
4. Delete `views/FirstRunLegacy.vue`.
5. Update `views/FirstRun.vue` head comment to drop the prototype phase note.
