/**
 * hardware.spec.ts — γ-6 Hardware probe re-run (PLAN §10.3 path 6).
 *
 * Covers: from /hardware, assert UMA breakdown bar renders with
 * `unified_memory_mb` total and segmented chunks for GTT/RAM/VRAM.
 * Click "Re-probe", mock `POST /api/install/probe` to mutate
 * unified_memory_mb. Bar updates; stat tiles reflect new numbers.
 */
import { test, expect, json } from '../fixtures/apiMock'

test('renders UMA breakdown, re-probes, sees updated numbers', async ({
  page,
  mockState,
  cleanState,
}) => {
  // Default mockState is UMA 128 GB. After re-probe, mutate to 64 GB.
  await page.route('**/api/install/probe', (route) => {
    mockState.installProbeCount += 1
    mockState.hardware.unified_memory_mb = 64 * 1024
    mockState.hardware.ram_total_mb = 64 * 1024
    mockState.statsHardware.unified_memory_mb = 64 * 1024
    mockState.statsHardware.ram_total_mb = 64 * 1024
    return json(route, { ok: true, hardware: mockState.hardware })
  })

  await page.goto('/hardware')

  // ── UMA breakdown visible with default 128 GB ──────────────
  // Section heading "Memory breakdown" is the UMA-only block.
  const memSection = page.locator('section[aria-labelledby="mem-heading"]')
  await expect(memSection).toBeVisible()
  await expect(memSection.locator('.bar-total')).toHaveText('128 GB pool')

  // Each non-zero segment renders a <div class="bar-seg seg-*">.
  // The probe's defaults yield GTT + System RAM + Free — three
  // segments. The legend echoes them.
  await expect(memSection.locator('.bar-seg.seg-gtt')).toHaveCount(1)
  await expect(memSection.locator('.bar-seg.seg-sys')).toHaveCount(1)
  await expect(memSection.locator('.bar-seg.seg-free')).toHaveCount(1)

  // Tile shows 128 GB total.
  const unifiedTile = page.locator('.tile', { hasText: /Unified memory/ })
  await expect(unifiedTile.locator('.tile-value')).toContainText('128')

  // ── Re-probe → simulated hot-plug halves memory ───────────
  const probeResp = page.waitForResponse(
    (r) => r.url().endsWith('/api/install/probe') && r.request().method() === 'POST',
  )
  await page.getByRole('button', { name: /Re-probe/ }).click()
  await probeResp

  // The page calls loadHardware() after probe + status. Wait for
  // the bar to reflect the new total.
  await expect(memSection.locator('.bar-total')).toHaveText('64 GB pool', { timeout: 5_000 })
  await expect(unifiedTile.locator('.tile-value')).toContainText('64')
  expect(mockState.installProbeCount).toBe(1)
})
