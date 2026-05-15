<script setup>
/**
 * RestartBanner — sticky top-of-main banner when an update is available
 * or when a settings change requires an API restart.
 *
 * Phase 0: always hidden. The reactive state is wired to the system store
 * so Phase 1 (update check endpoint) just flips the flag.
 */
import { computed } from 'vue'
import { useSystemStore } from '../stores/system.js'

const system = useSystemStore()

// Phase 0: no update check endpoint yet — banner stays hidden.
// Phase 1: system.status?.update_available drives this.
const visible = computed(() => !!system.status?.update_available)
const version = computed(() => system.status?.update_version ?? null)

async function applyUpdate() {
  // Phase 1: POST /api/updates/apply
}
</script>

<template>
  <Transition name="slide-up">
    <div v-if="visible" class="restart-banner" role="alert" aria-live="assertive">
      <svg width="15" height="15" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
      </svg>
      <span>
        Update available
        <strong v-if="version"> v{{ version }}</strong>
        — slots will keep running.
      </span>
      <button type="button" class="banner-btn" @click="applyUpdate">Apply now</button>
    </div>
  </Transition>
</template>

<style scoped>
.restart-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 24px;
  background: color-mix(in oklch, var(--color-info) 16%, var(--color-surface));
  border-bottom: 1px solid color-mix(in oklch, var(--color-info) 30%, transparent);
  color: color-mix(in oklch, var(--color-info) 90%, var(--color-fg));
  font-size: 13px;
}

.banner-btn {
  margin-left: auto;
  padding: 4px 12px;
  border-radius: var(--radius);
  background: var(--color-info);
  color: var(--color-bg);
  font-size: 12px;
  font-weight: 600;
  border: none;
  cursor: pointer;
  flex-shrink: 0;
}
.banner-btn:hover { opacity: 0.9; }

.slide-up-enter-active { transition: all 0.2s ease; }
.slide-up-leave-active { transition: all 0.15s ease; }
.slide-up-enter-from   { opacity: 0; transform: translateY(-100%); }
.slide-up-leave-to     { opacity: 0; transform: translateY(-100%); }
</style>
