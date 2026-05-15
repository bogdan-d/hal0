/**
 * firstrun.spec.ts — γ-1 First-run wizard (PLAN §10.3 path 1).
 *
 * Covers: redirect from / to /firstrun when
 * /api/install/state.first_run is true, walk the three-step picker +
 * license + download flow, watch SSE progress, click "Open chat".
 *
 * The spec mocks the curated catalogue to surface a deterministic
 * "smallest card" (Phi-3 Mini, 2.4 GB) which the brief says to pick.
 * SSE events are pumped through the in-page shim so we can assert UI
 * updates in lockstep with each event.
 */
import { test, expect, json } from '../fixtures/apiMock'
import { installSseHarness, emitSse, waitForSse } from '../fixtures/sseHarness'

test.beforeEach(async ({ page, mockState }) => {
  mockState.installState.first_run = true
  await installSseHarness(page)
  // Stub window.open so the "Open chat" assertion captures the URL
  // without actually navigating away.
  await page.addInitScript(() => {
    ;(window).__openCalls = []
    const orig = window.open
    Object.defineProperty(window, 'open', {
      configurable: true,
      writable: true,
      value: function (url, target) {
        ;(window).__openCalls.push({ url: String(url), target: String(target == null ? '' : target) })
        return null
      },
    })
  })
})

test('redirects to /firstrun, walks the wizard, opens chat', async ({ page, mockState, cleanState }) => {
  // Pull-stream route reply so the network layer doesn't 200-with-{}; the
  // real events come from the SSE harness.
  await page.route('**/api/models/*/pull/stream', (route) =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' }),
  )

  await page.goto('/')

  // ── Step 1: should land on /firstrun via the guard ──────────────
  await expect(page).toHaveURL(/\/firstrun$/)
  await expect(page.getByText('Welcome to hal0')).toBeVisible()

  // Pick the smallest card — Phi-3 Mini, 2.4 GB per the curated mock.
  const phiCard = page.locator('.model-option', { hasText: 'Phi-3 Mini' })
  await expect(phiCard).toBeVisible()
  await phiCard.click()
  await expect(phiCard).toHaveClass(/selected/)

  await page.getByRole('button', { name: /Next: Review license/ }).click()

  // ── Step 2: license + checkbox enables Download ────────────────
  const acceptCheckbox = page.locator('.accept-label input[type="checkbox"]')
  const downloadBtn = page.getByRole('button', { name: /Accept .* download/i })
  await expect(downloadBtn).toBeDisabled()
  await acceptCheckbox.check()
  await expect(downloadBtn).toBeEnabled()
  await downloadBtn.click()

  // ── Step 3: SSE progress events ────────────────────────────────
  await waitForSse(page, '/api/models/phi3-mini/pull/stream')

  const streamUrl = '/api/models/phi3-mini/pull/stream'
  const total = 2_400_000_000
  for (let i = 1; i <= 4; i++) {
    await emitSse(page, streamUrl, {
      state: 'pulling',
      bytes_downloaded: Math.round((total * i) / 5),
      bytes_total: total,
    })
    await page.waitForTimeout(20)
  }
  // Progress bar partway filled (4/5 = 80%).
  await expect(page.locator('.progress-pct')).toHaveText('80%')

  // Final event flips state to completed → step 4.
  await emitSse(page, streamUrl, {
    state: 'completed',
    bytes_downloaded: total,
    bytes_total: total,
  })

  await expect(page.getByText("You're all set!")).toBeVisible({ timeout: 5_000 })

  // ── Step 4: Open chat → window.open + POST /api/install/complete ──
  const completeReq = page.waitForRequest(
    (req) => req.url().endsWith('/api/install/complete') && req.method() === 'POST',
  )
  await page.getByRole('button', { name: /Open chat/i }).click()
  await completeReq

  await expect.poll(async () => {
    return await page.evaluate(() => ((window).__openCalls || []).length)
  }).toBe(1)
  const openCalls = await page.evaluate(() => (window).__openCalls)
  expect(openCalls[0].url).toBe(mockState.configUrls.openwebui)
  expect(openCalls[0].target).toBe('_blank')
  expect(mockState.installCompleteCount).toBe(1)
})
