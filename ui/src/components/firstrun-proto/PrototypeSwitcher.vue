<script setup>
/**
 * PrototypeSwitcher — floating bottom-center bar for flipping ?variant=A|B|C.
 * Throwaway. Hidden in production builds via import.meta.env.PROD guard.
 */
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const props = defineProps({
  variants: { type: Array, required: true },     // [{ key, name }, …]
  current:  { type: String, required: true },
})

const route = useRoute()
const router = useRouter()
const isProd = import.meta.env.PROD

const idx = computed(() => Math.max(0, props.variants.findIndex((v) => v.key === props.current)))
const currentMeta = computed(() => props.variants[idx.value])

function go(delta) {
  const n = props.variants.length
  const next = props.variants[(idx.value + delta + n) % n]
  router.replace({ path: route.path, query: { ...route.query, variant: next.key } })
}

function onKey(ev) {
  const t = ev.target
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
  if (ev.key === 'ArrowLeft')  { ev.preventDefault(); go(-1) }
  if (ev.key === 'ArrowRight') { ev.preventDefault(); go(1) }
}
onMounted(()  => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div v-if="!isProd" class="proto-switcher" role="toolbar" aria-label="Prototype variant switcher">
    <button class="ps-arrow" type="button" aria-label="Previous variant" @click="go(-1)">←</button>
    <span class="ps-label">
      <span class="ps-key">{{ currentMeta?.key }}</span>
      <span class="ps-name">{{ currentMeta?.name }}</span>
    </span>
    <button class="ps-arrow" type="button" aria-label="Next variant" @click="go(1)">→</button>
    <span class="ps-hint">←/→</span>
  </div>
</template>

<style scoped>
.proto-switcher {
  position: fixed;
  left: 50%;
  bottom: 18px;
  transform: translateX(-50%);
  z-index: 9999;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(20, 20, 24, 0.92);
  border: 1px solid var(--hal0-accent, #6cf);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5), 0 0 24px color-mix(in srgb, var(--hal0-accent, #6cf) 30%, transparent);
  font-family: var(--font-mono, monospace);
  color: #fff;
  backdrop-filter: blur(8px);
}
.ps-arrow {
  background: transparent;
  color: var(--hal0-accent, #6cf);
  border: 1px solid color-mix(in srgb, var(--hal0-accent, #6cf) 40%, transparent);
  border-radius: 6px;
  width: 28px;
  height: 28px;
  cursor: pointer;
  font-size: 14px;
  display: grid;
  place-items: center;
}
.ps-arrow:hover { background: color-mix(in srgb, var(--hal0-accent, #6cf) 18%, transparent); }
.ps-label { display: flex; align-items: center; gap: 8px; padding: 0 6px; }
.ps-key { font-weight: 700; color: var(--hal0-accent, #6cf); font-size: 12px; }
.ps-name { font-size: 12px; color: #ddd; }
.ps-hint { font-size: 10px; color: #888; padding-left: 4px; border-left: 1px solid #333; margin-left: 2px; }
</style>
