<script setup>
/**
 * ActivityTicker.vue — last-meaningful-event display in the collapsed
 * footer bar. Click → expand pane onto Activity tab scrolled to that
 * event. Truncates to a single line.
 */
import { computed } from 'vue'

const props = defineProps({
  event: { type: Object, default: null },
})

defineEmits(['click'])

const severityClass = computed(() => {
  const s = props.event?.severity
  if (s === 'error') return 'sev-error'
  if (s === 'warn' || s === 'warning') return 'sev-warn'
  return 'sev-info'
})

const text = computed(() => {
  if (!props.event) return 'No recent events'
  return props.event.message || props.event.type || ''
})
</script>

<template>
  <button
    type="button"
    class="ticker"
    :class="severityClass"
    :title="text"
    :aria-label="`Activity: ${text}`"
    @click.stop="$emit('click', event)"
  >
    <span class="ticker-dot" aria-hidden="true"></span>
    <span class="ticker-text">{{ text }}</span>
  </button>
</template>

<style scoped>
.ticker {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1 1 auto;
  background: transparent;
  border: 0;
  padding: 0 6px;
  height: 100%;
  color: var(--color-fg-faint);
  font-family: var(--font-mono);
  font-size: 11px;
  cursor: pointer;
  overflow: hidden;
}
.ticker:hover { color: var(--color-fg); }
.ticker-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
  flex: 1 1 auto;
  text-align: left;
}
.ticker-dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--color-fg-faint);
  flex-shrink: 0;
}
.sev-info .ticker-dot  { background: var(--color-info); }
.sev-warn .ticker-dot  { background: var(--color-warning); }
.sev-error .ticker-dot { background: var(--color-danger); }
.sev-warn  { color: color-mix(in oklch, var(--color-warning) 80%, var(--color-fg-faint)); }
.sev-error { color: color-mix(in oklch, var(--color-danger) 80%, var(--color-fg-faint)); }
</style>
