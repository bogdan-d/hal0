/**
 * slot-lifecycle.spec.ts — γ-2 Slot lifecycle (PLAN §10.3 path 2).
 *
 * Covers: from /slots, "Create slot" → fill modal → submit → walk
 * mock `/api/status.slots[].status` through
 *   offline → pulling → starting → warming → ready
 * then exercise restart → unload → delete.
 *
 * Per the actual implementation, slot state surfaces via the
 * /api/status poll (5s in App.vue, plus explicit calls after every
 * action) — there is no per-slot SSE channel for state in this UI.
 * We drive transitions by mutating `mockState.status.slots[].status`
 * and then triggering the store refresh either through an action
 * (which calls system.fetchStatus()) or by manually invoking the
 * store from the page context.
 */
import { test, expect, json } from '../fixtures/apiMock'

test('creates a slot, walks state transitions, restarts, unloads, deletes', async ({
  page,
  mockState,
  cleanState,
}) => {
  // Pre-seed a model so the create form's dropdown isn't empty.
  mockState.models.push({
    id: 'phi3-mini',
    name: 'Phi-3 Mini',
    size_gb: 2.4,
  })

  // Slot-mutating endpoints. POST /api/slots creates; per-name actions
  // mutate state.status.slots so the next /api/status fetch reflects
  // the new state.
  await page.route('**/api/slots', (route) => {
    const req = route.request()
    if (req.method() === 'POST') {
      const body = JSON.parse(req.postData() || '{}')
      const snap = {
        name: body.name,
        type: body.type ?? 'llama-server',
        backend: body.backend ?? 'vulkan',
        model: body.model ?? null,
        port: 8081,
        status: 'offline',
        context_size: body.ctx_size ?? 4096,
      }
      mockState.status.slots.push(snap)
      return json(route, snap, 201)
    }
    return json(route, mockState.status.slots)
  })

  // load/restart/unload/swap actions: idempotent OK; the spec
  // mutates `status.slots[i].status` directly to drive transitions.
  await page.route('**/api/slots/*/load', (route) => json(route, { ok: true }))
  await page.route('**/api/slots/*/restart', (route) => json(route, { ok: true }))
  await page.route('**/api/slots/*/unload', (route) => json(route, { ok: true }))
  await page.route('**/api/slots/*/swap', (route) => json(route, { ok: true }))

  // DELETE /api/slots/<name>
  await page.route('**/api/slots/test-vulkan', (route) => {
    if (route.request().method() === 'DELETE') {
      mockState.status.slots = mockState.status.slots.filter((s) => s.name !== 'test-vulkan')
      return route.fulfill({ status: 204 })
    }
    return json(route, mockState.status.slots.find((s) => s.name === 'test-vulkan') || {})
  })

  await page.goto('/slots')

  // ── Open the create modal ─────────────────────────────────────
  await page.getByRole('button', { name: /New slot/i }).click()
  await expect(page.locator('#create-slot-title')).toBeVisible()

  // Fill the form (name, provider, backend, model)
  await page.locator('#slot-name').fill('test-vulkan')
  await page.locator('#slot-type').selectOption('llama-server')
  await page.locator('#slot-backend').selectOption('vulkan')
  await page.locator('#slot-model').selectOption('phi3-mini')

  // Scope to the modal: there's another "Create slot" button in the
  // EmptyState CTA on the page itself.
  await page.locator('[aria-labelledby="create-slot-title"]')
    .getByRole('button', { name: /^Create slot$/ })
    .click()
  await expect(page.locator('#create-slot-title')).toBeHidden()

  // ── Walk state transitions ────────────────────────────────────
  // The slot card is now present in the grid. The card itself
  // doesn't render the state name as text — we observe the
  // `sc-state-X` class on the card element, plus the running
  // affordances (start vs restart/unload buttons) which switch
  // when `running` is true (running/ready/serving/idle).
  const slotCard = page.locator('.slot-card', { hasText: 'test-vulkan' })
  await expect(slotCard).toBeVisible()

  const states = ['pulling', 'starting', 'warming', 'ready']
  for (const next of states) {
    mockState.status.slots[0].status = next
    // Force a status refresh from inside the page (the App polls
    // every 5s; for test speed we call the store directly).
    await page.evaluate(async () => {
      const m = await import('/src/stores/system.js')
      await m.useSystemStore().fetchStatus()
    })
    if (next === 'ready') {
      // Running state: restart + unload (stop) buttons appear.
      await expect(slotCard.locator('button[title="Restart"]')).toBeVisible()
      await expect(slotCard.locator('button[title="Stop"]')).toBeVisible()
    } else {
      // Non-running: start (play) button is visible.
      await expect(slotCard.locator('button[title="Start"]')).toBeVisible()
    }
  }

  // ── Restart ───────────────────────────────────────────────────
  mockState.status.slots[0].status = 'restarting'
  const restartReq = page.waitForRequest((r) => r.url().includes('/api/slots/test-vulkan/restart'))
  await slotCard.locator('button[title="Restart"]').click()
  await restartReq
  mockState.status.slots[0].status = 'ready'
  await page.evaluate(async () => {
    const m = await import('/src/stores/system.js')
    await m.useSystemStore().fetchStatus()
  })
  await expect(slotCard.locator('button[title="Stop"]')).toBeVisible()

  // ── Unload ────────────────────────────────────────────────────
  const unloadReq = page.waitForRequest((r) => r.url().includes('/api/slots/test-vulkan/unload'))
  await slotCard.locator('button[title="Stop"]').click()
  await unloadReq
  mockState.status.slots[0].status = 'offline'
  await page.evaluate(async () => {
    const m = await import('/src/stores/system.js')
    await m.useSystemStore().fetchStatus()
  })
  await expect(slotCard.locator('button[title="Start"]')).toBeVisible()

  // ── Delete ────────────────────────────────────────────────────
  // The delete button is hidden for built-in slots; test-vulkan is
  // custom so the trash icon is present.
  const deleteReq = page.waitForRequest(
    (r) => r.url().endsWith('/api/slots/test-vulkan') && r.method() === 'DELETE',
  )
  await slotCard.getByRole('button', { name: /Delete slot test-vulkan/i }).click()
  // ConfirmDialog: click the confirm button.
  await page.getByRole('button', { name: /^Delete slot$/ }).click()
  await deleteReq
  await page.evaluate(async () => {
    const m = await import('/src/stores/system.js')
    await m.useSystemStore().fetchStatus()
  })
  await expect(page.locator('.slot-card', { hasText: 'test-vulkan' })).toHaveCount(0)
})
