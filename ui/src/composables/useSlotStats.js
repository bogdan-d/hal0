import { computed } from 'vue'
import { useSystemStore } from '../stores/system.js'

// Shared running/total/active counts for navbar, sidebar, and dashboard.
export const ACTIVE_STATES = new Set(['running', 'ready', 'serving'])

// Providers that serve a single baked-in model without an explicit load —
// a missing model_id on these is not a misconfiguration.
export const SELF_MANAGED_PROVIDERS = new Set(['moonshine', 'kokoro', 'vibevoice'])

// True iff the slot is genuinely able to serve: an active state plus
// either an assigned model or a provider that doesn't need one. Slots
// that landed in ready/serving without a model (a state-machine
// edge — e.g. the slot was force-marked ready after a crash) are
// reported as not-running so the navbar/sidebar and dashboard agree
// with the per-slot row that says "no model".
export function isSlotServing(slot) {
  if (!slot || !ACTIVE_STATES.has(slot.status)) return false
  const model = slot.model_name || slot.model || slot.model_id
  if (model) return true
  return SELF_MANAGED_PROVIDERS.has((slot.provider || '').toLowerCase())
}

export function useSlotStats() {
  const system = useSystemStore()
  const active = computed(() => system.slots.filter(isSlotServing))
  const running = computed(() => active.value.length)
  const total = computed(() => system.slots.length)
  return { running, total, active }
}
