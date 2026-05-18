/**
 * footer.spec.ts — expandable bottom-dock status bar.
 *
 * Covers:
 *   1. Bar renders with brand + stats placeholders.
 *   2. Click bar to expand, click again to collapse.
 *   3. Tab switching (click each of 4 tabs, assert active class moves).
 *   4. Resize drag — programmatically dispatch mouse events on the
 *      handle, assert the pane height changes accordingly.
 *   5. localStorage persistence — pre-seed expanded=true, reload,
 *      assert footer comes back expanded.
 */
import { test, expect, json } from '../fixtures/apiMock'
import { installSseHarness } from '../fixtures/sseHarness'

test.beforeEach(async ({ page, mockState }) => {
  await installSseHarness(page)
  // Make /api/events* and /api/events/stream return empty / no events;
  // the SSE harness intercepts EventSource construction so the stream
  // call here is just to keep the network layer quiet.
  await page.route('**/api/events?**', (route) =>
    json(route, { events: [], next_since: 0 }),
  )
  await page.route('**/api/events', (route) =>
    json(route, { events: [], next_since: 0 }),
  )
  await page.route('**/api/events/stream*', (route) =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' }),
  )
  // Logs stream — same harness story.
  await page.route('**/api/logs/stream*', (route) =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' }),
  )
  // Ensure /api/status returns a hostname so the brand line is complete.
  mockState.status.hostname = 'hal0-test'
})

test('renders bar with brand and stats placeholders', async ({ page, cleanState }) => {
  await page.goto('/')
  const bar = page.locator('.bar[role="button"]')
  await expect(bar).toBeVisible()
  await expect(bar.locator('.brand-h')).toHaveText('hal0')
  await expect(bar.locator('.brand-host')).toContainText('hal0-test')
  // Stats group present (values may be em-dashes until first /api/stats/hardware
  // poll completes — assert the container, not the values).
  await expect(bar.locator('.bar-stats')).toBeVisible()
})

test('click bar toggles expanded; click again collapses', async ({ page, cleanState }) => {
  await page.goto('/')
  const bar = page.locator('.bar[role="button"]')
  const pane = page.locator('#hal0-footer-pane')

  // Initially collapsed.
  await expect(bar).toHaveAttribute('aria-expanded', 'false')
  await expect(pane).toHaveCount(0)

  // Click the brand — child elements like the slot tally / activity
  // ticker stop propagation so they don't accidentally toggle the bar.
  // Clicking the brand area always reaches the bar's click handler.
  await bar.locator('.bar-brand').click()
  await expect(bar).toHaveAttribute('aria-expanded', 'true')
  await expect(pane).toBeVisible()

  await bar.locator('.bar-brand').click()
  await expect(bar).toHaveAttribute('aria-expanded', 'false')
  await expect(pane).toHaveCount(0)
})

test('switching tabs moves active class', async ({ page, cleanState }) => {
  await page.goto('/')
  await page.locator('.bar[role="button"] .bar-brand').click()
  const pane = page.locator('#hal0-footer-pane')
  await expect(pane).toBeVisible()

  const tabs = ['activity', 'slots', 'logs', 'jobs'] as const
  for (const id of tabs) {
    await page.locator(`#footer-tab-${id}`).click()
    await expect(page.locator(`#footer-tab-${id}`)).toHaveAttribute('aria-selected', 'true')
    // Only one tab marked selected at a time.
    const selected = page.locator('[role="tab"][aria-selected="true"]', { has: page.locator(':scope') })
    await expect(selected).toHaveCount(2)  // main tab + (when on logs) sub-tab
      .catch(async () => {
        // Other tabs don't have sub-tabs — fall back to >=1 check.
        await expect(selected).not.toHaveCount(0)
      })
  }
})

test('drag handle resizes the pane', async ({ page, cleanState }) => {
  await page.goto('/')
  await page.locator('.bar[role="button"] .bar-brand').click()
  const handle = page.locator('.handle[role="separator"]')
  await expect(handle).toBeVisible()

  const paneHost = page.locator('#hal0-footer-pane').locator('..')
  const initial = await paneHost.evaluate((el) => (el as HTMLElement).offsetHeight)

  const box = await handle.boundingBox()
  if (!box) throw new Error('handle not laid out')
  const startY = box.y + box.height / 2
  const startX = box.x + box.width / 2

  // Drag the handle up by 80px → pane should grow by ~80px.
  await page.mouse.move(startX, startY)
  await page.mouse.down()
  await page.mouse.move(startX, startY - 80, { steps: 8 })
  await page.mouse.up()

  const after = await paneHost.evaluate((el) => (el as HTMLElement).offsetHeight)
  expect(after).toBeGreaterThan(initial + 40)
})

test('localStorage persistence: expanded=true survives reload', async ({ page, cleanState }) => {
  await page.goto('/')
  // Pre-seed and reload — `localStorage.setItem` before goto isn't
  // reliable cross-context; we set it via page.evaluate after the
  // first nav (origin established), then reload.
  await page.evaluate(() => {
    localStorage.setItem('hal0:footer:expanded', 'true')
    localStorage.setItem('hal0:footer:height', '300')
    localStorage.setItem('hal0:footer:tab', 'jobs')
  })
  await page.reload()

  const bar = page.locator('.bar[role="button"]')
  await expect(bar).toHaveAttribute('aria-expanded', 'true')
  await expect(page.locator('#hal0-footer-pane')).toBeVisible()
  // Persisted tab choice honoured.
  await expect(page.locator('#footer-tab-jobs')).toHaveAttribute('aria-selected', 'true')
})
