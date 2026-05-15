# Contributing to hal0

**Pre-alpha.** External contributions aren't being accepted yet. This
file is a placeholder for the v0.2+ contribution flow.

When it opens up:

- One PR per feature; small, reviewable diffs
- Run `make lint test` before pushing
- Update `PLAN.md` if your change moves the v1 scope
- Slot/dispatcher/provider changes require both unit and integration
  tests (Tier-1 reliability is non-negotiable)
- UI changes need Playwright coverage for any new critical path

For now, please open issues for discussion only.

## E2E tests

The `ui/tests/e2e/` Playwright suite covers the seven critical paths
from PLAN §10.3 (FirstRun wizard, slot lifecycle, model management,
settings + restart banner, logs SSE tail, hardware probe, update
banner). All seven run on every PR via `.github/workflows/playwright.yml`
in <8 minutes against mocked backends.

```bash
cd ui
npm install                  # one-time, picks up @playwright/test
npm run test:e2e:install     # downloads Chromium (~150 MB, one-time)

npm run test:e2e             # full suite, headless
npm run test:e2e:ui          # Playwright UI mode (local dev)
npx playwright test firstrun # one spec only
```

### Mock vs live backend

Default mode mocks every `/api/*` endpoint via `page.route` — no
backend required. To exercise the real API against the `hal0-test`
LXC (or any live install):

```bash
HAL0_E2E_LIVE=1 npm run test:e2e
```

The `hal0-test` LXC at `10.0.1.230` is the standing target for
release-gate runs. The Vite dev server's `vite.config.js` proxy
already forwards `/api/*` + `/v1/*` to that host, so live mode just
needs the env var. Live-mode adjusts test timeouts (180s per spec,
30min wall-clock) to fit real model pulls and slot warm-up.

### Adding a spec

1. Drop a new file in `ui/tests/e2e/specs/`. Import `test`, `expect`,
   `json` from `../fixtures/apiMock` and the SSE helpers from
   `../fixtures/sseHarness` if you need an event stream.
2. Override the routes you care about by calling `page.route(...)`
   inside the test body — these take precedence over the fixture's
   defaults (Playwright matches routes in reverse-registration order).
3. Keep each spec <90s. If you need a `data-testid`, document the
   addition in the PR description so the lid on UI churn stays low.

