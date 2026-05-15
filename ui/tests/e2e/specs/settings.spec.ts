/**
 * settings.spec.ts — γ-4 Settings persistence + restart banner (PLAN §10.3 path 4).
 *
 * Covers: change `telemetry.channel` stable → nightly, save, assert
 * `PUT /api/settings` body matches, restart banner appears (channel
 * is restart-required per Team E's `RESTART_REQUIRED` set in
 * Settings.vue), click "Reload from disk", form re-populates.
 */
import { test, expect, json } from '../fixtures/apiMock'

test('changes telemetry.channel, saves, sees restart banner, reloads', async ({
  page,
  mockState,
  cleanState,
}) => {
  // Custom PUT handler that records the body for assertion. The
  // default fixture's PUT also mutates state.settings — we replace it
  // here so we can capture the body too.
  let putBody: any = null
  await page.route('**/api/settings', (route) => {
    const req = route.request()
    if (req.method() === 'PUT') {
      putBody = JSON.parse(req.postData() || '{}')
      for (const section of Object.keys(putBody)) {
        mockState.settings[section] = { ...mockState.settings[section], ...putBody[section] }
      }
      return json(route, mockState.settings)
    }
    return json(route, mockState.settings)
  })

  await page.goto('/settings')
  await expect(page.locator('#f-telemetry-channel')).toBeVisible()
  await expect(page.locator('#f-telemetry-channel')).toHaveValue('stable')

  // Change the channel — Settings.vue's "changed field" indicator
  // shows the unsaved-change counter in the header.
  await page.locator('#f-telemetry-channel').selectOption('nightly')
  await expect(page.getByText(/1 unsaved change/)).toBeVisible()

  // Save and observe the restart banner.
  const putResp = page.waitForResponse(
    (r) => r.url().endsWith('/api/settings') && r.request().method() === 'PUT',
  )
  await page.getByRole('button', { name: /Save changes/ }).click()
  await putResp

  // The PUT body is a partial deep-merge patch.
  expect(putBody).toEqual({ telemetry: { channel: 'nightly' } })

  // The page renders the restart banner with the changed key listed.
  const banner = page.locator('.restart-banner', { hasText: /Restart required/ })
  await expect(banner).toBeVisible()
  await expect(banner).toContainText('telemetry.channel')

  // ── Reload from disk ────────────────────────────────────────
  // Server-side: pretend the on-disk hal0.toml has channel=stable
  // (an out-of-band edit). The reload endpoint should re-populate
  // the form with that value.
  mockState.settings.telemetry.channel = 'stable'
  const reloadResp = page.waitForResponse(
    (r) => r.url().endsWith('/api/settings/reload') && r.request().method() === 'POST',
  )
  await page.getByRole('button', { name: /Reload from disk/ }).click()
  await reloadResp
  await expect(page.locator('#f-telemetry-channel')).toHaveValue('stable')
})
