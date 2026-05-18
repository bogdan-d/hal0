<script setup>
/**
 * ImgCard
 *
 * Capability slot card for the `img` slot. Single section (image
 * generation); ComfyUI loads VAE / text-encoder / LoRAs internally so
 * they're not exposed as children at v1. Wires to the same
 * /api/capabilities/img/img endpoint as the other capability cards via
 * useCapabilities().setSelection().
 *
 * Metrics show `imgs/h` (req/s × 3600) when available — operator-visible
 * throughput is rare-event-y for image gen, so a per-hour rollup reads
 * more usefully than the underlying per-sec rate.
 */
import { computed, ref } from 'vue'
import { useCapabilities } from '../../composables/useCapabilities.js'
import { useSlotMetrics } from '../../composables/useStats.js'
import { useToastsStore } from '../../stores/toasts.js'
import CapabilityToggle from './CapabilityToggle.vue'

const props = defineProps({
  // { img: { backend, provider, model, enabled, slot, status } }
  selection: { type: Object, required: true },
})

const cap = useCapabilities()
const toasts = useToastsStore()
const { metrics } = useSlotMetrics()

const SLOT_NAME = 'img'
const togglePending = ref(false)

function fmtMem(mb) {
  if (mb == null) return '—'
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`
}

function optionsFor() {
  const models = cap.modelsForCapability('img', 'img')
  const opts = []
  for (const b of cap.backends.value) {
    for (const m of models) {
      if (m.backend !== b.id) continue
      opts.push({
        key: `${b.id}::${m.provider || ''}::${m.id}`,
        label: `${b.short} / ${m.id}`,
        backend: b.id,
        provider: m.provider,
        model: m.id,
        size_gb: m.size_gb,
      })
    }
  }
  return opts
}

async function onChange(ev) {
  const v = ev.target.value
  if (!v) return
  const [backend, provider, model] = v.split('::')
  try {
    await cap.setSelection('img', 'img', {
      backend,
      provider: provider || null,
      model,
    })
    toasts.success(`img.img → ${model}`)
  } catch (err) {
    toasts.error(`failed to set img: ${err?.message ?? err}`)
  }
}

async function onToggle(enabled) {
  togglePending.value = true
  try {
    await cap.setSelection('img', 'img', { enabled })
  } catch (err) {
    toasts.error(`toggle failed: ${err?.message ?? err}`)
  } finally {
    togglePending.value = false
  }
}

const currentValue = computed(() => {
  const s = props.selection?.img
  if (!s) return ''
  return `${s.backend}::${s.provider || ''}::${s.model}`
})
const selected = computed(() => {
  const s = props.selection?.img
  if (!s) return null
  return cap.modelsForCapability('img', 'img')
    .find((m) => m.backend === s.backend && m.id === s.model) ?? null
})
const selectedBackend = computed(() => {
  const s = props.selection?.img
  return s ? cap.backendById(s.backend) : null
})
const isActive = computed(() => {
  const s = props.selection?.img
  return s?.enabled && s?.status !== 'offline'
})

// Live metrics — image gen reads per-hour from the per-sec rate.
const imgMetrics = computed(() => metrics.value?.[SLOT_NAME] ?? null)
function reqRate(m) {
  if (!m) return null
  if (m.requests_per_sec != null) return m.requests_per_sec
  if (m.tokens_per_sec   != null) return m.tokens_per_sec
  return null
}
function latency(m) {
  if (!m) return null
  return m.latency_ms_p50 ?? m.p50_latency_ms ?? m.latency_p50 ?? null
}
function mem(m) {
  if (!m) return null
  return m.mem_rss_mb ?? m.vram_mb ?? m.gtt_mb ?? null
}
const imgsPerHour = computed(() => {
  const r = reqRate(imgMetrics.value)
  return r != null ? Math.round(r * 3600) : null
})
const secPerImg = computed(() => {
  const l = latency(imgMetrics.value)
  return l != null ? (l / 1000).toFixed(1) : null
})

const headerPill = computed(() => {
  const s = props.selection?.img?.status
  if (s === 'serving') return { cls: 'cap-pill-ok',  text: 'ready' }
  if (s === 'error')   return { cls: 'cap-pill-err', text: 'error' }
  return { cls: 'cap-pill-idle', text: s || 'offline' }
})
</script>

<template>
  <div class="cap-card">
    <header class="cap-head">
      <div class="cap-head-l">
        <span class="cap-dot cap-dot-ok" />
        <h3 class="cap-title">img</h3>
        <span class="cap-type">capability slot</span>
      </div>
      <span class="cap-pill" :class="headerPill.cls">{{ headerPill.text }}</span>
    </header>

    <section class="cap-section">
      <div class="cap-section-head">
        <span class="cap-section-head-l">
          <span class="cap-status" :data-state="selection?.img?.status || 'offline'">
            <span class="cap-status-dot" />
            {{ selection?.img?.status || 'offline' }}
          </span>
          <span class="cap-section-label">Image</span>
          <span class="cap-section-sub">/v1/images/generations</span>
        </span>
        <CapabilityToggle
          :model-value="!!selection?.img?.enabled"
          :loading="togglePending"
          label="enable img"
          @update:model-value="onToggle"
        />
      </div>
      <select
        class="cap-select"
        :value="currentValue"
        :disabled="togglePending"
        @change="onChange"
      >
        <option value="" disabled>pick model…</option>
        <option v-for="o in optionsFor()" :key="o.key" :value="o.key">
          {{ o.label }}{{ o.size_gb ? ` — ${o.size_gb} GB` : '' }}
        </option>
      </select>
      <div class="cap-meta">
        <span class="cap-chip" :data-backend="selectedBackend?.id">{{ selectedBackend?.label || '—' }}</span>
        <span class="cap-meta-item" v-if="selected?.size_gb">{{ selected.size_gb }} GB</span>
        <span class="cap-meta-item">comfyui handles VAE + text encoder</span>
      </div>
      <div v-if="isActive" class="cap-metrics">
        <div class="cap-metric cap-metric-headline" :class="{ 'cap-metric-na': imgsPerHour == null }">
          <span class="cap-metric-v">{{ imgsPerHour ?? '—' }}</span>
          <span class="cap-metric-u">imgs/h</span>
        </div>
        <div class="cap-metric" :class="{ 'cap-metric-na': secPerImg == null }">
          <span class="cap-metric-v">{{ secPerImg ?? '—' }}</span>
          <span class="cap-metric-u">s/img</span>
        </div>
        <div class="cap-metric cap-metric-mem">
          <span class="cap-metric-v">{{ fmtMem(mem(imgMetrics)) }}</span>
          <span class="cap-metric-u">resident</span>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* Structural styles only — shared chip/metric/section CSS is in
 * CapabilitiesSection.vue (non-scoped). */
.cap-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 16px 18px;
  display: flex; flex-direction: column; gap: 16px;
}

.cap-head { display: flex; align-items: center; justify-content: space-between; }
.cap-head-l { display: flex; align-items: center; gap: 10px; }
.cap-dot { width: 8px; height: 8px; border-radius: 50%; }
.cap-dot-ok { background: var(--color-success); box-shadow: 0 0 6px -1px var(--color-success); }
.cap-title { font-size: 14px; font-weight: 600; color: var(--color-fg); margin: 0; }
.cap-type { font-family: var(--font-mono); font-size: 10.5px; color: var(--color-fg-faint); }
.cap-pill {
  font-family: var(--font-mono); font-size: 10.5px;
  padding: 2px 8px; border-radius: 999px;
  border: 1px solid var(--color-border);
  background: var(--color-surface-2);
  color: var(--color-fg-muted);
}
.cap-pill-ok {
  border-color: color-mix(in oklch, var(--color-success) 30%, transparent);
  background: color-mix(in oklch, var(--color-success) 12%, transparent);
  color: var(--color-success);
}
.cap-pill-idle {
  border-color: color-mix(in oklch, var(--color-warning) 30%, transparent);
  background: color-mix(in oklch, var(--color-warning) 12%, transparent);
  color: var(--color-warning);
}
.cap-pill-err {
  border-color: color-mix(in oklch, var(--color-danger) 30%, transparent);
  background: color-mix(in oklch, var(--color-danger) 12%, transparent);
  color: var(--color-danger);
}
</style>
