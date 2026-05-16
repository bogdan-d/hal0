<script setup>
defineProps({
  icon: { type: String, default: 'M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4' },
  title: { type: String, required: true },
  description: { type: String, default: '' },
  ctaLabel: { type: String, default: '' },
})
const emit = defineEmits(['cta'])
</script>

<template>
  <div class="empty-state" role="status">
    <div class="empty-icon" aria-hidden="true">
      <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.4">
        <path stroke-linecap="round" stroke-linejoin="round" :d="icon" />
      </svg>
    </div>
    <p class="empty-title">{{ title }}</p>
    <p v-if="description" class="empty-desc">{{ description }}</p>
    <button v-if="ctaLabel" class="empty-cta" type="button" @click="$emit('cta')">
      {{ ctaLabel }}
    </button>
    <slot />
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 48px 24px;
  text-align: center;
}

.empty-icon {
  width: 44px;
  height: 44px;
  color: var(--color-fg-faint);
  margin-bottom: 4px;
}
.empty-icon svg {
  width: 100%;
  height: 100%;
}

.empty-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-fg-muted);
  margin: 0;
}

.empty-desc {
  font-size: 13px;
  color: var(--color-fg-faint);
  margin: 0;
  max-width: 340px;
  line-height: 1.6;
}

.empty-cta {
  margin-top: 4px;
  padding: 7px 16px;
  border-radius: var(--radius);
  background: var(--hal0-accent);
  color: #000;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 500;
  border: none;
  cursor: pointer;
  transition: background 0.15s;
}
.empty-cta:hover { background: var(--hal0-accent-hover); }
</style>
