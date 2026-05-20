<script setup>
/**
 * VoiceCard
 *
 * Capability slot card for the `voice` slot. Two stacked sections (STT /
 * TTS) — each with a status pill + on/off toggle + cross-backend
 * dropdown + live metrics strip. See EmbedCard for the long-form
 * comments — this card is the same shape, just with different
 * capabilities + endpoint sub-labels.
 */
import { computed, ref } from 'vue'
import { useCapabilities } from '../../composables/useCapabilities.js'
import { useSlotMetrics } from '../../composables/useStats.js'
import { useToastsStore } from '../../stores/toasts.js'
import { usePullJob, fmtBytes } from '../../composables/usePullJob.js'
import CapabilityToggle from './CapabilityToggle.vue'

const props = defineProps({
  selection: { type: Object, required: true },
})

const cap = useCapabilities()
const toasts = useToastsStore()
const { metrics } = useSlotMetrics()

const CAPS = ['stt', 'tts']
const SLOT_NAME = { stt: 'stt', tts: 'tts' }
const ENDPOINTS = {
  stt: '/v1/audio/transcriptions',
  tts: '/v1/audio/speech',
}

const togglePending = ref({ stt: false, tts: false })

function fmtMem(mb) {
  if (mb == null) return '—'
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`
}

function optionsFor(capability) {
  const models = cap.modelsForCapability('voice', capability)
  const opts = []
  for (const b of cap.backends.value) {
    for (const m of models) {
      if (m.backend !== b.id) continue
      // ◉ downloaded · ⬇ pullable · ✕ no source — see EmbedCard.vue.
      const ready = m.downloaded !== false
      const pullable = m.pullable !== false
      const icon = ready ? '◉' : pullable ? '⬇' : '✕'
      opts.push({
        key: `${b.id}::${m.provider || ''}::${m.id}`,
        label: `${icon} ${b.short} / ${m.id}`,
        backend: b.id,
        provider: m.provider,
        model: m.id,
        size_gb: m.size_gb,
        downloaded: ready,
        pullable,
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
  return cap.modelsForCapability('voice', capability)
    .find((m) => m.backend === s.backend && m.id === s.model) ?? null
}

function backendFor(capability) {
  const s = props.selection?.[capability]
  return s ? cap.backendById(s.backend) : null
}

// One pull job per voice child (stt, tts) so they can race in parallel
// with independent progress strips.
const pull = {
  stt: usePullJob(),
  tts: usePullJob(),
}

async function onChange(capability, ev) {
  const v = ev.target.value
  if (!v) return
  const [backend, provider, model] = v.split('::')
  const opt = optionsFor(capability).find((o) => o.key === v)
  if (opt && opt.downloaded === false) {
    if (opt.pullable === false) {
      toasts.error(
        `"${model}" has no download source (upstream-routed model). ` +
        `Add an hf_repo + hf_filename on the registry entry to enable pull.`,
      )
      ev.target.value = currentValue(capability)
      return
    }
    try {
      await pull[capability].pullAndWait(model)
      await cap.refresh()
    } catch (err) {
      toasts.error(`download "${model}" failed: ${err?.message ?? err}`)
      ev.target.value = currentValue(capability)
      return
    }
  }
  try {
    await cap.setSelection('voice', capability, {
      backend,
      provider: provider || null,
      model,
    })
    toasts.success(`voice.${capability} → ${model}`)
  } catch (err) {
    toasts.error(`failed to set ${capability}: ${err?.message ?? err}`)
  }
}

async function onToggle(capability, enabled) {
  togglePending.value[capability] = true
  try {
    await cap.setSelection('voice', capability, { enabled })
  } catch (err) {
    toasts.error(`toggle failed: ${err?.message ?? err}`)
  } finally {
    togglePending.value[capability] = false
  }
}

function metricsFor(capability) {
  const slotName = SLOT_NAME[capability]
  return slotName ? (metrics.value?.[slotName] ?? null) : null
}

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

function isActive(c) {
  const s = props.selection?.[c]
  return s?.enabled && s?.status !== 'offline'
}

const headerPill = computed(() => {
  const states = CAPS.map((c) => props.selection?.[c]?.status).filter(Boolean)
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
        <h3 class="cap-title">voice</h3>
        <span class="cap-type">capability slot</span>
      </div>
      <span class="cap-pill" :class="headerPill.cls">{{ headerPill.text }}</span>
    </header>

    <section v-for="c in CAPS" :key="c" class="cap-section">
      <div class="cap-section-head">
        <span class="cap-section-head-l">
          <span class="cap-status" :data-state="selection?.[c]?.status || 'offline'">
            <span class="cap-status-dot" />
            {{ selection?.[c]?.status || 'offline' }}
          </span>
          <span class="cap-section-label">{{ c.toUpperCase() }}</span>
          <span class="cap-section-sub">{{ ENDPOINTS[c] }}</span>
        </span>
        <CapabilityToggle
          :model-value="!!selection?.[c]?.enabled"
          :loading="togglePending[c]"
          :label="`enable ${c}`"
          @update:model-value="(v) => onToggle(c, v)"
        />
      </div>
      <select
        class="cap-select"
        :value="currentValue(c)"
        :disabled="togglePending[c] || pull[c].inFlight.value"
        @change="onChange(c, $event)"
      >
        <option value="" disabled>pick model…</option>
        <option v-for="o in optionsFor(c)" :key="o.key" :value="o.key">
          {{ o.label }}{{ o.size_gb ? ` — ${o.size_gb} GB` : '' }}
        </option>
      </select>
      <div v-if="pull[c].inFlight.value" class="cap-pull">
        <div class="cap-pull-bar"><div class="cap-pull-fill" :style="{ width: (pull[c].pct.value ?? 0) + '%' }" /></div>
        <span class="cap-pull-label mono">
          ↓ {{ pull[c].modelId.value }} · {{ pull[c].pct.value ?? 0 }}% · {{ fmtBytes(pull[c].downloaded.value) }} / {{ fmtBytes(pull[c].total.value) }}
        </span>
        <button class="cap-pull-cancel" type="button" @click="pull[c].cancel()">cancel</button>
      </div>
      <div class="cap-meta">
        <span class="cap-chip" :data-backend="backendFor(c)?.id">{{ backendFor(c)?.label || '—' }}</span>
        <span class="cap-meta-item" v-if="selectedModel(c)?.size_gb">{{ selectedModel(c).size_gb }} GB</span>
        <span class="cap-meta-item" v-if="backendFor(c)?.multiplex">⚡ shared {{ backendFor(c).label }} process</span>
      </div>
      <div v-if="isActive(c)" class="cap-metrics">
        <div class="cap-metric cap-metric-headline" :class="{ 'cap-metric-na': reqRate(metricsFor(c)) == null }">
          <span class="cap-metric-v">{{ reqRate(metricsFor(c)) != null ? Number(reqRate(metricsFor(c))).toFixed(1) : '—' }}</span>
          <span class="cap-metric-u">req/s</span>
        </div>
        <div class="cap-metric" :class="{ 'cap-metric-na': latency(metricsFor(c)) == null }">
          <span class="cap-metric-v">{{ latency(metricsFor(c)) ?? '—' }}</span>
          <span class="cap-metric-u">ms p50</span>
        </div>
        <div class="cap-metric cap-metric-mem">
          <span class="cap-metric-v">{{ fmtMem(mem(metricsFor(c))) }}</span>
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
