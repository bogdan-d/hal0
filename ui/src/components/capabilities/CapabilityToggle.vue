<script setup>
/**
 * CapabilityToggle
 *
 * Pill-style on/off switch for capability rows. Compact (44×22) so it
 * sits in the section header next to the endpoint sub-label without
 * fighting the row for vertical space.
 *
 * Loading state replaces the knob with a spinner and disables click /
 * keyboard activation — the caller drives the optimistic update on its
 * own ref and flips `loading` true during the POST.
 *
 * Accessible: `role="switch"`, `aria-checked`, focusable, space/enter
 * toggles. Aria label falls back to the visible label so screen readers
 * announce which capability is being toggled.
 */
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  label: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

function toggle() {
  if (props.disabled || props.loading) return
  emit('update:modelValue', !props.modelValue)
}

function onKey(ev) {
  if (props.disabled || props.loading) return
  if (ev.key === ' ' || ev.key === 'Enter') {
    ev.preventDefault()
    emit('update:modelValue', !props.modelValue)
  }
}
</script>

<template>
  <button
    type="button"
    class="cap-toggle"
    :class="{ on: modelValue, off: !modelValue, disabled: disabled || loading, loading }"
    role="switch"
    :aria-checked="modelValue"
    :aria-label="label || (modelValue ? 'on' : 'off')"
    :aria-busy="loading"
    :disabled="disabled || loading"
    :tabindex="disabled ? -1 : 0"
    @click="toggle"
    @keydown="onKey"
  >
    <span class="cap-toggle-track">
      <span class="cap-toggle-knob">
        <svg
          v-if="loading"
          class="cap-toggle-spin"
          viewBox="0 0 16 16"
          aria-hidden="true"
        >
          <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-dasharray="9 28" />
        </svg>
      </span>
    </span>
  </button>
</template>

<style scoped>
.cap-toggle {
  width: 44px;
  height: 22px;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  flex-shrink: 0;
  border-radius: 999px;
  display: inline-block;
  position: relative;
}
.cap-toggle:focus-visible {
  outline: 2px solid var(--hal0-accent);
  outline-offset: 2px;
}
.cap-toggle.disabled { cursor: not-allowed; opacity: 0.55; }

.cap-toggle-track {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: 999px;
  background: var(--color-surface-3);
  border: 1px solid var(--color-border);
  position: relative;
  transition: background 0.18s ease, border-color 0.18s ease;
}
.cap-toggle.on .cap-toggle-track {
  background: color-mix(in oklch, var(--hal0-accent) 25%, var(--color-surface-3));
  border-color: color-mix(in oklch, var(--hal0-accent) 55%, var(--color-border));
}

.cap-toggle-knob {
  position: absolute;
  top: 1px;
  left: 1px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--color-fg-faint);
  display: grid;
  place-items: center;
  color: var(--color-bg);
  transition: transform 0.18s ease, background 0.18s ease;
}
.cap-toggle.on .cap-toggle-knob {
  transform: translateX(22px);
  background: var(--hal0-accent);
}

.cap-toggle-spin {
  width: 12px;
  height: 12px;
  animation: cap-toggle-spin 0.9s linear infinite;
}
@keyframes cap-toggle-spin {
  to { transform: rotate(360deg); }
}
@media (prefers-reduced-motion: reduce) {
  .cap-toggle-track, .cap-toggle-knob { transition: none; }
  .cap-toggle-spin { animation: none; }
}
</style>
