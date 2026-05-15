/**
 * models.spec.ts — γ-3 Model management (PLAN §10.3 path 3).
 *
 * Covers: from /models, open the Pull modal (HF tab), submit a custom
 * Hugging Face repo, confirm the new model appears in the table,
 * assign it to the primary slot via the row's "Assign…" dropdown,
 * then delete it.
 *
 * Note: the UI's HF-pull flow at /models doesn't surface SSE progress
 * inline (only the FirstRun wizard does). The "watch progress" beat
 * in the brief reduces here to: the modal closes, a toast fires, the
 * row appears.
 */
import { test, expect, json } from '../fixtures/apiMock'

test('pulls a custom HF model, assigns it to primary, deletes it', async ({
  page,
  mockState,
  cleanState,
}) => {
  // Pre-seed the primary slot so the assign dropdown has something
  // to point at.
  mockState.status.slots.push({
    name: 'primary',
    backend: 'vulkan',
    model: null,
    port: 8081,
    status: 'offline',
  })

  // /api/models/pull — Models.vue's flow uses the haloai-style singular
  // endpoint for both curated and HF pulls. We side-effect: append a
  // new row to mockState.models keyed off the HF repo path.
  await page.route('**/api/models/pull', (route) => {
    const body = JSON.parse(route.request().postData() || '{}')
    const id = body.hf_url
      ? body.hf_url.split('/').pop().toLowerCase()
      : body.model_id || `m-${mockState.models.length + 1}`
    mockState.models.push({
      id,
      name: body.hf_url || id,
      size_gb: 3.0,
      architecture: 'llama',
      quant: body.quant ?? 'Q4_K_M',
    })
    return json(route, { ok: true, model_id: id })
  })

  // DELETE/PUT/GET /api/models/<id> — narrow the glob so it does
  // not intercept /api/models/pull (which is handled above).
  await page.route(/\/api\/models\/(?!pull$)[^/]+$/, (route) => {
    if (route.request().method() === 'DELETE') {
      const url = new URL(route.request().url())
      const id = decodeURIComponent(url.pathname.split('/').pop()!)
      mockState.models = mockState.models.filter((m) => m.id !== id)
      // The UI doesn't cascade-clear slot.model on delete; the
      // backend would. Mirror that here so the spec's slot-default-
      // cleared assertion is meaningful.
      for (const s of mockState.status.slots) {
        if (s.model === id) s.model = null
      }
      return route.fulfill({ status: 204 })
    }
    return json(route, mockState.models[0] || {})
  })

  // /api/slots/<name>/load — record the model that was loaded.
  let lastLoadBody: any = null
  await page.route(/\/api\/slots\/[^/]+\/load$/, (route) => {
    const post = route.request().postData()
    lastLoadBody = post ? JSON.parse(post) : null
    const slot = mockState.status.slots.find((s) => s.name === 'primary')
    if (slot && lastLoadBody?.model) slot.model = lastLoadBody.model
    return json(route, { ok: true })
  })

  await page.goto('/models')

  // ── Open pull modal, switch to HF tab, submit a repo ─────────
  await page.getByRole('button', { name: /^Pull model$/ }).click()
  await expect(page.locator('#pull-title')).toBeVisible()
  await page.getByRole('tab', { name: /HuggingFace/ }).click()
  await page.locator('#hf-url').fill('Qwen/Qwen3-4B-GGUF')
  await page.locator('#quant').selectOption('Q4_K_M')

  const pullReq = page.waitForRequest(
    (r) => r.url().endsWith('/api/models/pull') && r.method() === 'POST',
  )
  await page.locator('[aria-labelledby="pull-title"]')
    .getByRole('button', { name: /^Pull model$/ })
    .click()
  await pullReq

  // Modal closes after the pull and the row appears. The row text
  // includes the mock-side `name` (the HF repo path) plus the id.
  await expect(page.locator('#pull-title')).toBeHidden()
  const row = page.locator('tr', { hasText: 'Qwen3-4B-GGUF' })
  await expect(row).toBeVisible()

  // ── Assign to primary slot via the row's dropdown ────────────
  const assignResp = page.waitForResponse(
    (r) => r.url().endsWith('/api/slots/primary/load') && r.request().method() === 'POST',
  )
  await row.locator('select.assign-select').selectOption('primary')
  await assignResp

  expect(lastLoadBody?.model).toBe('qwen3-4b-gguf')
  expect(
    mockState.status.slots.find((s) => s.name === 'primary')?.model,
  ).toBe('qwen3-4b-gguf')

  // Refresh status from the page so the UI's "Used by" cell updates.
  await page.evaluate(async () => {
    const m = await import('/src/stores/system.js')
    await m.useSystemStore().fetchStatus()
  })
  await expect(row.locator('.slot-badge', { hasText: 'primary' })).toBeVisible()

  // ── Delete the model ─────────────────────────────────────────
  const deleteReq = page.waitForRequest(
    (r) => /\/api\/models\/qwen3-4b-gguf$/.test(r.url()) && r.method() === 'DELETE',
  )
  // The delete button's aria-label is `Delete <name>` where <name>
  // is the model's display name (the HF repo path here).
  await row.getByRole('button', { name: /Delete Qwen\/Qwen3-4B-GGUF/i }).click()
  // ConfirmDialog: when 1 slot uses the model, no type-to-confirm —
  // a single "Delete model" button does it.
  await page.getByRole('button', { name: /^Delete model$/ }).click()
  await deleteReq

  // The row is gone; the primary slot's model is cleared.
  await expect(page.locator('tr', { hasText: 'Qwen3-4B-GGUF' })).toHaveCount(0)
  expect(
    mockState.status.slots.find((s) => s.name === 'primary')?.model,
  ).toBeNull()
})
