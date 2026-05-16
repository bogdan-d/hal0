<script setup>
defineProps({
  /** Add extra padding inside */
  padded: { type: Boolean, default: true },
  /** Visually highlight (e.g. active state) — amber inset rail like hal0-web's "Why hal0" featured card */
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
  border-color: color-mix(in srgb, var(--hal0-accent) 40%, var(--color-border));
  box-shadow: inset 3px 0 0 var(--hal0-accent);
}
</style>
