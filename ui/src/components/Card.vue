<script setup>
defineProps({
  /** Add extra padding inside */
  padded: { type: Boolean, default: true },
  /** Visually highlight (e.g. active state) */
  highlight: { type: Boolean, default: false },
})
</script>

<template>
  <div
    class="card"
    :class="{
      'card-padded': padded,
      'card-highlight': highlight,
    }"
  >
    <slot />
  </div>
</template>

<style scoped>
.card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.card-padded {
  padding: 16px;
}

.card-highlight {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 1px var(--color-accent-bg);
}
</style>
