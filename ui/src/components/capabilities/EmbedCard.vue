<script setup>
/**
 * EmbedCard
 *
 * Capability slot card for the `embed` slot. Two stacked sections — Embed
 * (text → vector) and Rerank (query+doc → score) — each with:
 *
 *   - A status pill (serving/idle/loading/error/offline) on the left of
 *     the header, driven by `selection.status` from /api/capabilities.
 *   - A CapabilityToggle on the right that POSTs `{enabled: …}` to
 *     /api/capabilities/embed/{child}.
 *   - A cross-backend dropdown listing every `<BACKEND>/<MODEL>` pair
 *     available for that capability (POSTs `{backend, provider, model}`
 *     on change).
 *   - A metrics strip wired to useSlotMetrics() — embed → `embed`,
 *     rerank → `embed-rerank` (mirrors the backend's slot naming).
 *
 * Selection comes from the singleton useCapabilities() store; the parent
 * just hands us the slice. We call setSelection() ourselves so the
 * optimistic patch + revert lives in one place.
 */
import { computed, ref } from 'vue'
import { useCapabilities } from '../../composables/useCapabilities.js'
import { useSlotMetrics } from '../../composables/useStats.js'
import { useToastsStore } from '../../stores/toasts.js'
import CapabilityToggle from './CapabilityToggle.vue'

const props = defineProps({
  // { embed: { backend, provider, model, enabled, slot, status }, rerank: {...} }
  selection: { type: Object, required: true },
})

const cap = useCapabilities()
const toasts = useToastsStore()
const { metrics } = useSlotMetrics()

// Map { capability → upstream slot name }. Mirrors the backend's slot
// naming convention so the metrics keyed in /api/slots/metrics line up
// with the cards. Keep in sync with the backend agent.
const SLOT_NAME = { embed: 'embed', rerank: 'embed-rerank' }
const ENDPOINTS  = { embed: '/v1/embeddings', rerank: '/v1/rerankings' }

// Per-child loading flag for the toggle spinner. Keyed by capability so
// flipping one pill doesn't lock the other.
const togglePending = ref({ embed: false, rerank: false })

function fmtMem(mb) {
  if (mb == null) return '—'
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`
}

function optionsFor(capability) {
  const models = cap.modelsForCapability('embed', capability)
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

function currentValue(capability) {
  const s = props.selection?.[capability]
  if (!s) return ''
  return `${s.backend}::${s.provider || ''}::${s.model}`
}

function selectedModel(capability) {
  const s = props.selection?.[capability]
  if (!s) return null
  return cap.modelsForCapability('embed', capability)
    .find((m) => m.backend === s.backend && m.id === s.model) ?? null
}

async function onChange(capability, ev) {
  const v = ev.target.value
  if (!v) return
  const [backend, provider, model] = v.split('::')
  try {
    await cap.setSelection('embed', capability, {
      backend,
      provider: provider || null,
      model,
    })
    toasts.success(`embed.${capability} → ${model}`)
  } catch (err) {
    toasts.error(`failed to set ${capability}: ${err?.message ?? err}`)
  }
}

async function onToggle(capability, enabled) {
  togglePending.value[capability] = true
  try {
    await cap.setSelection('embed', capability, { enabled })
  } catch (err) {
    toasts.error(`toggle failed: ${err?.message ?? err}`)
  } finally {
    togglePending.value[capability] = false
  }
}

function backendFor(capability) {
  const s = props.selection?.[capability]
  return s ? cap.backendById(s.backend) : null
}

// ── Live metrics ───────────────────────────────────────────────────────
// Read directly from useSlotMetrics() keyed by the upstream slot name.
// We synthesise a small per-capability row from real numbers: headline =
// requests-per-sec (rough proxy for "embedding throughput"), latency
// comes from the metrics blob if present, mem from `mem_rss_mb`.
// Cells that aren't available render `—` rather than fake data.
function metricsFor(capability) {
  const slotName = SLOT_NAME[capability]
  return slotName ? (metrics.value?.[slotName] ?? null) : null
}

function reqRate(m) {
  if (!m) return null
  // Prefer a precomputed rate; otherwise expose the running processing
  // count so the user sees something meaningful even before a window
  // averages out.
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

const embedActive = computed(() => {
  const s = props.selection?.embed
  return s?.enabled && s?.status !== 'offline'
})
const rerankActive = computed(() => {
  const s = props.selection?.rerank
  return s?.enabled && s?.status !== 'offline'
})

const headerPill = computed(() => {
  const states = ['embed', 'rerank']
    .map((c) => props.selection?.[c]?.status)
    .filter(Boolean)
  const serving = states.filter((s) => s === 'serving').length
  if (serving === 2) return { cls: 'cap-pill-ok',   text: '2 children · ready' }
  if (serving === 1) return { cls: 'cap-pill-ok',   text: '1/2 serving' }
  if (states.some((s) => s === 'error')) return { cls: 'cap-pill-err', text: 'error' }
  return { cls: 'cap-pill-idle', text: 'idle' }
})
</script>

<template>
  <div class="cap-card">
    <header class="cap-head">
      <div class="cap-head-l">
        <span class="cap-dot cap-dot-ok" />
        <h3 class="cap-title">embed</h3>
        <span class="cap-type">capability slot</span>
      </div>
      <span class="cap-pill" :class="headerPill.cls">{{ headerPill.text }}</span>
    </header>

    <!-- Embed section -->
    <section class="cap-section">
      <div class="cap-section-head">
        <span class="cap-section-head-l">
          <span class="cap-status" :data-state="selection?.embed?.status || 'offline'">
            <span class="cap-status-dot" />
            {{ selection?.embed?.status || 'offline' }}
          </span>
          <span class="cap-section-label">Embed</span>
          <span class="cap-section-sub">{{ ENDPOINTS.embed }}</span>
        </span>
        <CapabilityToggle
          :model-value="!!selection?.embed?.enabled"
          :loading="togglePending.embed"
          label="enable embed"
          @update:model-value="(v) => onToggle('embed', v)"
        />
      </div>
      <select
        class="cap-select"
        :value="currentValue('embed')"
        :disabled="togglePending.embed"
        @change="onChange('embed', $event)"
      >
        <option value="" disabled>pick model…</option>
        <option
          v-for="o in optionsFor('embed')"
          :key="o.key"
          :value="o.key"
        >{{ o.label }}{{ o.size_gb ? ` — ${o.size_gb} GB` : '' }}</option>
      </select>
      <div class="cap-meta">
        <span class="cap-chip" :data-backend="backendFor('embed')?.id">{{ backendFor('embed')?.label || '—' }}</span>
        <span class="cap-meta-item" v-if="selectedModel('embed')?.dims">{{ selectedModel('embed').dims }}-d</span>
        <span class="cap-meta-item" v-if="selectedModel('embed')?.size_gb">{{ selectedModel('embed').size_gb }} GB</span>
        <span class="cap-meta-item" v-if="backendFor('embed')?.multiplex">⚡ shared {{ backendFor('embed').label }} process</span>
      </div>
      <div v-if="embedActive" class="cap-metrics">
        <div class="cap-metric cap-metric-headline" :class="{ 'cap-metric-na': reqRate(metricsFor('embed')) == null }">
          <span class="cap-metric-v">{{ reqRate(metricsFor('embed')) != null ? Number(reqRate(metricsFor('embed'))).toFixed(1) : '—' }}</span>
          <span class="cap-metric-u">req/s</span>
        </div>
        <div class="cap-metric" :class="{ 'cap-metric-na': latency(metricsFor('embed')) == null }">
          <span class="cap-metric-v">{{ latency(metricsFor('embed')) ?? '—' }}</span>
          <span class="cap-metric-u">ms p50</span>
        </div>
        <div class="cap-metric cap-metric-mem">
          <span class="cap-metric-v">{{ fmtMem(mem(metricsFor('embed'))) }}</span>
          <span class="cap-metric-u">resident</span>
        </div>
      </div>
    </section>

    <!-- Rerank section -->
    <section class="cap-section">
      <div class="cap-section-head">
        <span class="cap-section-head-l">
          <span class="cap-status" :data-state="selection?.rerank?.status || 'offline'">
            <span class="cap-status-dot" />
            {{ selection?.rerank?.status || 'offline' }}
          </span>
          <span class="cap-section-label">Rerank</span>
          <span class="cap-section-sub">{{ ENDPOINTS.rerank }}</span>
        </span>
        <CapabilityToggle
          :model-value="!!selection?.rerank?.enabled"
          :loading="togglePending.rerank"
          label="enable rerank"
          @update:model-value="(v) => onToggle('rerank', v)"
        />
      </div>
      <select
        class="cap-select"
        :value="currentValue('rerank')"
        :disabled="togglePending.rerank"
        @change="onChange('rerank', $event)"
      >
        <option value="" disabled>pick model…</option>
        <option
          v-for="o in optionsFor('rerank')"
          :key="o.key"
          :value="o.key"
        >{{ o.label }}{{ o.size_gb ? ` — ${o.size_gb} GB` : '' }}</option>
      </select>
      <div class="cap-meta">
        <span class="cap-chip" :data-backend="backendFor('rerank')?.id">{{ backendFor('rerank')?.label || '—' }}</span>
        <span class="cap-meta-item" v-if="selectedModel('rerank')?.size_gb">{{ selectedModel('rerank').size_gb }} GB</span>
        <span class="cap-meta-item" v-if="backendFor('rerank')?.multiplex">⚡ shared {{ backendFor('rerank').label }} process</span>
      </div>
      <div v-if="rerankActive" class="cap-metrics">
        <div class="cap-metric cap-metric-headline" :class="{ 'cap-metric-na': reqRate(metricsFor('rerank')) == null }">
          <span class="cap-metric-v">{{ reqRate(metricsFor('rerank')) != null ? Number(reqRate(metricsFor('rerank'))).toFixed(1) : '—' }}</span>
          <span class="cap-metric-u">req/s</span>
        </div>
        <div class="cap-metric" :class="{ 'cap-metric-na': latency(metricsFor('rerank')) == null }">
          <span class="cap-metric-v">{{ latency(metricsFor('rerank')) ?? '—' }}</span>
          <span class="cap-metric-u">ms p50</span>
        </div>
        <div class="cap-metric cap-metric-mem">
          <span class="cap-metric-v">{{ fmtMem(mem(metricsFor('rerank'))) }}</span>
          <span class="cap-metric-u">resident</span>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* Structural styles only; shared chip/metric/section styles live in
 * CapabilitiesSection.vue as a non-scoped block so all four cards stay
 * visually aligned without duplicate-copy drift. */
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
