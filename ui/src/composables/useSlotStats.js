import { computed } from 'vue'
import { useSystemStore } from '../stores/system.js'

// Shared running/total/active counts for navbar, sidebar, and dashboard.
export const ACTIVE_STATES = new Set(['running', 'ready', 'serving'])

export function useSlotStats() {
  const system = useSystemStore()
  const active = computed(() => system.slots.filter((s) => ACTIVE_STATES.has(s.status)))
  const running = computed(() => active.value.length)
  const total = computed(() => system.slots.length)
  return { running, total, active }
}
