<script setup>
/**
 * ProgressChip.vue — small inline pill rendered in the collapsed footer
 * bar while a long-running job (pull, slot load, slot warm) is in flight.
 *
 * On terminal state:
 *   - failed → red ✗ pill, parent auto-dismisses after 10s.
 *   - completed/cancelled → fades + auto-dismisses by parent.
 */
import { computed } from 'vue'

const props = defineProps({
  /** Display label — e.g. "↓ deepseek-v3" or "load primary" */
  label: { type: String, required: true },
  /** 0-100; null when indeterminate (e.g. warming) */
  pct: { type: Number, default: null },
  /** 'queued'|'running'|'completed'|'failed'|'cancelled' */
  state: { type: String, default: 'running' },
  /** Optional click handler — usually open Jobs tab */
})

defineEmits(['click'])

const stateClass = computed(() => `chip-${props.state || 'running'}`)
const showProgress = computed(() => props.pct != null && props.state !== 'failed')
const showIndeterminate = computed(() => props.pct == null && (props.state === 'queued' || props.state === 'running'))

const ariaLabel = computed(() => {
  const pct = props.pct != null ? ` ${Math.round(props.pct)} percent` : ''
  return `${props.label}${pct} ${props.state}`
})
</script>

<template>
  <button
    type="button"
    class="chip"
    :class="stateClass"
    :aria-label="ariaLabel"
    @click="$emit('click')"
  >
    <span class="chip-label">{{ label }}</span>
    <span v-if="state === 'failed'" class="chip-x" aria-hidden="true">✗</span>
    <span v-else-if="state === 'completed'" class="chip-check" aria-hidden="true">✓</span>
    <span v-else-if="showProgress" class="chip-pct mono">{{ Math.round(pct) }}%</span>
    <span v-else-if="showIndeterminate" class="chip-spin" aria-hidden="true"></span>
    <span class="chip-track" v-if="showProgress" aria-hidden="true">
      <span class="chip-fill" :style="{ width: pct + '%' }"></span>
    </span>
  </button>
</template>

<style scoped>
.chip {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px 2px 8px;
  border-radius: 999px;
  background: var(--color-surface-2);
  border: 1px solid var(--color-border);
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--color-fg-muted);
  height: 18px;
  line-height: 1;
  cursor: pointer;
  white-space: nowrap;
  max-width: 200px;
  overflow: hidden;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.chip:hover { background: var(--color-surface-3); color: var(--color-fg); border-color: var(--color-border-hi); }
.chip-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 130px; }
.chip-pct { font-feature-settings: 'zero' 1, 'tnum' 1; color: var(--hal0-accent); }

.chip-track {
  position: absolute;
  left: 0; right: 0; bottom: 0;
  height: 2px;
  background: transparent;
}
.chip-fill {
  display: block;
  height: 100%;
  background: var(--hal0-accent);
  transition: width 0.25s ease;
}

.chip-spin {
  width: 8px; height: 8px;
  border-radius: 50%;
  border: 1.5px solid color-mix(in srgb, var(--hal0-accent) 30%, transparent);
  border-top-color: var(--hal0-accent);
  animation: chip-spin 0.8s linear infinite;
}
@keyframes chip-spin { to { transform: rotate(360deg); } }

.chip.chip-failed {
  color: var(--color-danger);
  border-color: color-mix(in oklch, var(--color-danger) 60%, transparent);
  background: color-mix(in oklch, var(--color-danger) 12%, transparent);
}
.chip.chip-completed {
  color: var(--color-success);
  border-color: color-mix(in oklch, var(--color-success) 50%, transparent);
}
.chip.chip-cancelled { opacity: 0.6; }

@media (prefers-reduced-motion: reduce) {
  .chip-spin { animation: none; }
  .chip-fill { transition: none; }
}
</style>
