<script setup>
defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})
</script>

<template>
  <div class="page-header">
    <div class="page-header-text">
      <h1 class="page-title">{{ title }}</h1>
      <p v-if="subtitle" class="page-subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="page-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 24px 24px 0;
  flex-wrap: wrap;
}

.page-header-text { min-width: 0; }

.page-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--color-fg);
  margin: 0;
  letter-spacing: -0.02em;
  line-height: 1.3;
}

.page-subtitle {
  font-size: 13px;
  color: var(--color-fg-muted);
  margin: 3px 0 0;
}

.page-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  padding-top: 2px;
}
</style>
