/**
 * logs.spec.ts — γ-5 Logs SSE tail (PLAN §10.3 path 5).
 *
 * Covers: from /logs, select unit `hal0-slot@primary`, level `info`,
 * range `5m`. Drive SSE to emit 10 lines via the in-page harness,
 * assert each appears in the viewport. Click Freeze → drive 5 more
 * lines → assert viewport unchanged. Unfreeze → emit fresh lines →
 * they appear (the SSE handler reopens the stream on unfreeze; old
 * frozen-window events were dropped by design, not buffered).
 *
 * Backend SSE format per Team E (Logs.vue:138): each frame's `data`
 * is JSON-encoded so the client can JSON.parse it. We honour that.
 */
import { test, expect, json } from '../fixtures/apiMock'
import { installSseHarness, emitSse, waitForSse } from '../fixtures/sseHarness'

test.beforeEach(async ({ page }) => {
  await installSseHarness(page)
})

test('tails SSE, freezes, unfreezes', async ({ page, mockState, cleanState }) => {
  // GET /api/logs — historical seed. The unit selector defaults to
  // hal0-api; the spec switches it to hal0-slot@primary, which then
  // triggers a fresh fetch. Return empty so we start from a known
  // baseline.
  await page.route('**/api/logs*', (route) => {
    const req = route.request()
    if (req.url().includes('/api/logs/stream')) {
      // The SSE harness intercepts EventSource construction; reply
      // here keeps the network layer happy.
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
    }
    return json(route, { unit: '', lines: [], count: 0 })
  })

  // Pre-seed a primary slot so the unit selector exposes it.
  mockState.status.slots.push({ name: 'primary', status: 'ready', port: 8081 })

  await page.goto('/logs')

  // ── Set filters ─────────────────────────────────────────────
  await page.locator('#log-unit-filter').selectOption('hal0-slot@primary')
  await page.locator('#log-level-filter').selectOption('info')
  await page.locator('#log-range-filter').selectOption('5m')

  // The Logs.vue watcher debounces filter changes by 400ms, then
  // reloads + reopens the stream. Wait for the new EventSource to
  // come up against the chosen unit.
  await waitForSse(page, '/api/logs/stream', 4000)
  // Settle: the filter watcher may open one stream, the debounce
  // may reopen another. Allow a microtask flush.
  await page.waitForTimeout(200)

  // ── Emit 10 SSE lines (each wrapped in JSON per backend contract) ──
  const streamUrl = '/api/logs/stream'
  for (let i = 0; i < 10; i++) {
    await emitSse(page, streamUrl, JSON.stringify(`line-${i}`))
  }
  for (let i = 0; i < 10; i++) {
    await expect(page.locator('.log-line', { hasText: `line-${i}` })).toBeVisible()
  }

  // ── Freeze ─────────────────────────────────────────────────
  await page.getByRole('button', { name: /Freeze/ }).click()
  // The button label switches to "Resume" when frozen.
  await expect(page.getByRole('button', { name: /Resume/ })).toBeVisible()

  // Freeze calls closeStream() so the original SSE entry is closed.
  // Drive 5 more events — they emit into a closed shim, no-op.
  for (let i = 10; i < 15; i++) {
    await emitSse(page, streamUrl, JSON.stringify(`line-${i}`))
  }
  // Wait a beat; the viewport must NOT contain the new lines.
  await page.waitForTimeout(200)
  for (let i = 10; i < 15; i++) {
    await expect(page.locator('.log-line', { hasText: `line-${i}` })).toHaveCount(0)
  }

  // ── Unfreeze ───────────────────────────────────────────────
  await page.getByRole('button', { name: /Resume/ }).click()
  // A fresh stream is opened. Wait for the new EventSource.
  await waitForSse(page, '/api/logs/stream', 4000)
  await page.waitForTimeout(100)

  // Emit a marker line — it should appear, proving the new stream is
  // live. Old frozen-window events are intentionally not replayed.
  await emitSse(page, streamUrl, JSON.stringify('post-resume-marker'))
  await expect(page.locator('.log-line', { hasText: 'post-resume-marker' })).toBeVisible()
})
