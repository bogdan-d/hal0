<script setup>
/**
 * Hardware.vue
 *
 * Design intent: show what compute you have and how slots are using it.
 * Single-page layout: detected hardware at the top, current slot
 * allocation below, re-probe button prominent. Hardware fit warnings
 * reflect what /api/hardware returns; if the slot config form is
 * opened from here, it pre-fills the hardware context.
 */
import { ref, computed, onMounted } from 'vue'
import { useSystemStore } from '../stores/system.js'
import { useToastsStore } from '../stores/toasts.js'
import { api } from '../composables/useApi.js'
import PageHeader from '../components/PageHeader.vue'
import Card from '../components/Card.vue'
import LoadingSkeleton from '../components/LoadingSkeleton.vue'

const system = useSystemStore()
const toasts = useToastsStore()

const hardware = ref(null)
const loading  = ref(true)
const probing  = ref(false)
const error    = ref(null)

async function loadHardware() {
  loading.value = true
  error.value = null
  try {
    const data = await api('/api/hardware')
    hardware.value = data
  } catch (e) {
    error.value = e.message
    hardware.value = null
  } finally {
    loading.value = false
  }
}

async function reProbe() {
  probing.value = true
  try {
    await api('/api/hardware/probe', { method: 'POST' })
    toasts.success('Hardware probe re-run — refreshing data…')
    await loadHardware()
    await system.fetchStatus()
  } catch (e) {
    toasts.error(e.message)
  } finally {
    probing.value = false
  }
}

const hw = computed(() => hardware.value ?? {})

// Memory utilization for slot allocation bar
const gttTotalMb = computed(() => hw.value.gtt_total_mb ?? 0)
const gttUsedMb  = computed(() => hw.value.gtt_used_mb ?? 0)
const gttPct     = computed(() => gttTotalMb.value > 0 ? (gttUsedMb.value / gttTotalMb.value * 100) : 0)

const ramTotalGb = computed(() => hw.value.ram_total_gb ?? 0)
const ramUsedGb  = computed(() => hw.value.ram_used_gb ?? 0)
const ramPct     = computed(() => ramTotalGb.value > 0 ? (ramUsedGb.value / ramTotalGb.value * 100) : 0)

const diskTotalGb = computed(() => hw.value.disk_total_gb ?? 0)
const diskUsedGb  = computed(() => hw.value.disk_used_gb ?? 0)
const diskPct     = computed(() => diskTotalGb.value > 0 ? (diskUsedGb.value / diskTotalGb.value * 100) : 0)

function pctColor(pct) {
  if (pct > 85) return 'var(--color-danger)'
  if (pct > 60) return 'var(--color-warning)'
  return 'var(--color-success)'
}

const runningSlots = computed(() => system.slots.filter((s) => s.status === 'running'))

onMounted(loadHardware)
</script>

<template>
  <div class="hardware-page">
    <PageHeader title="Hardware" subtitle="Compute resources and slot allocation">
      <template #actions>
        <button class="btn-secondary" type="button" @click="reProbe" :disabled="probing">
          <svg width="13" height="13" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2" aria-hidden="true" :class="{ 'spin': probing }">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
          </svg>
          {{ probing ? 'Probing…' : 'Re-probe' }}
        </button>
      </template>
    </PageHeader>

    <div class="page-body">
      <div v-if="error" class="error-banner" role="alert">{{ error }}</div>

      <!-- ── GPU / NPU ────────────────────────────────────────── -->
      <section aria-labelledby="gpu-heading">
        <h2 id="gpu-heading" class="section-title">GPU / Accelerator</h2>
        <Card v-if="loading"><LoadingSkeleton :lines="3" /></Card>
        <Card v-else>
          <div class="hw-grid">
            <div class="hw-row" v-if="hw.gpu_name">
              <span class="hw-key">GPU</span>
              <span class="hw-val">{{ hw.gpu_name }}</span>
            </div>
            <div class="hw-row" v-if="hw.gpu_driver_version">
              <span class="hw-key">Driver</span>
              <span class="hw-val mono">{{ hw.gpu_driver_version }}</span>
            </div>
            <div class="hw-row" v-if="hw.gpu_usage_pct != null">
              <span class="hw-key">GPU util</span>
              <span class="hw-val mono">{{ hw.gpu_usage_pct?.toFixed(0) }}%</span>
            </div>
            <div class="hw-row" v-if="gttTotalMb > 0">
              <span class="hw-key">GTT memory</span>
              <div class="hw-bar-wrap">
                <div class="hw-bar">
                  <div class="hw-bar-fill" :style="{ width: gttPct + '%', background: pctColor(gttPct) }" />
                </div>
                <span class="hw-val mono">{{ (gttUsedMb/1024).toFixed(1) }} / {{ (gttTotalMb/1024).toFixed(0) }} GB</span>
              </div>
            </div>
            <div class="hw-row" v-if="hw.vram_total_mb">
              <span class="hw-key">VRAM</span>
              <span class="hw-val mono">{{ (hw.vram_total_mb/1024).toFixed(0) }} GB</span>
            </div>
            <div class="hw-row" v-if="hw.npu_ok != null">
              <span class="hw-key">NPU</span>
              <span class="hw-val" :class="hw.npu_ok ? 'text-success' : 'text-muted'">
                {{ hw.npu_ok ? 'Available' : 'Not detected' }}
                {{ hw.npu_fw_version ? `· fw ${hw.npu_fw_version}` : '' }}
              </span>
            </div>
            <div v-if="!hw.gpu_name && !loading" class="hw-empty">No GPU information available. Run <code class="inline-code">hal0 probe</code> or click Re-probe.</div>
          </div>
        </Card>
      </section>

      <!-- ── System memory ────────────────────────────────────── -->
      <section aria-labelledby="ram-heading">
        <h2 id="ram-heading" class="section-title">System Memory</h2>
        <Card v-if="loading"><LoadingSkeleton :lines="2" /></Card>
        <Card v-else>
          <div class="hw-grid">
            <div class="hw-row" v-if="ramTotalGb > 0">
              <span class="hw-key">RAM</span>
              <div class="hw-bar-wrap">
                <div class="hw-bar">
                  <div class="hw-bar-fill" :style="{ width: ramPct + '%', background: pctColor(ramPct) }" />
                </div>
                <span class="hw-val mono">{{ ramUsedGb.toFixed(1) }} / {{ ramTotalGb.toFixed(0) }} GB</span>
              </div>
            </div>
            <div class="hw-row" v-if="diskTotalGb > 0">
              <span class="hw-key">Disk</span>
              <div class="hw-bar-wrap">
                <div class="hw-bar">
                  <div class="hw-bar-fill" :style="{ width: diskPct + '%', background: pctColor(diskPct) }" />
                </div>
                <span class="hw-val mono">{{ diskUsedGb.toFixed(0) }} / {{ diskTotalGb.toFixed(0) }} GB</span>
              </div>
            </div>
            <div class="hw-row" v-if="hw.cpu_model">
              <span class="hw-key">CPU</span>
              <span class="hw-val">{{ hw.cpu_model }}</span>
            </div>
            <div class="hw-row" v-if="hw.cpu_pct != null">
              <span class="hw-key">CPU util</span>
              <span class="hw-val mono">{{ hw.cpu_pct?.toFixed(0) }}%</span>
            </div>
          </div>
        </Card>
      </section>

      <!-- ── Slot allocation ─────────────────────────────────── -->
      <section aria-labelledby="slots-heading">
        <h2 id="slots-heading" class="section-title">Slot allocation</h2>
        <Card :padded="false">
          <div v-if="runningSlots.length === 0" class="allocation-empty">
            No slots are currently loaded.
          </div>
          <table v-else class="alloc-table">
            <thead>
              <tr>
                <th>Slot</th>
                <th>Model</th>
                <th>Port</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="slot in system.slots" :key="slot.name">
                <td class="mono">{{ slot.name }}</td>
                <td class="mono small">{{ slot.model ?? '—' }}</td>
                <td class="mono small">{{ slot.port ? ':' + slot.port : '—' }}</td>
                <td>
                  <span class="status-chip" :class="slot.status === 'running' ? 'chip-ok' : 'chip-off'">
                    {{ slot.status ?? 'offline' }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </Card>
      </section>
    </div>
  </div>
</template>

<style scoped>
.hardware-page { display: flex; flex-direction: column; min-height: 100%; }
.page-body     { padding: 20px 24px; display: flex; flex-direction: column; gap: 20px; }

.error-banner { padding: 10px 16px; border-radius: var(--radius-lg); background: color-mix(in oklch, var(--color-danger) 10%, var(--color-surface)); border: 1px solid color-mix(in oklch, var(--color-danger) 30%, transparent); color: var(--color-danger); font-size: 13px; }

.section-title { font-size: 13px; font-weight: 600; color: var(--color-fg-muted); letter-spacing: 0.03em; margin: 0 0 8px; }

.hw-grid { display: flex; flex-direction: column; gap: 12px; }
.hw-row { display: flex; align-items: center; gap: 16px; }
.hw-key { font-family: var(--font-mono); font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--color-fg-faint); min-width: 100px; flex-shrink: 0; }
.hw-val { font-size: 13px; color: var(--color-fg-muted); }
.hw-val.mono { font-family: var(--font-mono); font-size: 12px; }
.hw-bar-wrap { display: flex; align-items: center; gap: 10px; flex: 1; }
.hw-bar { flex: 1; height: 5px; background: var(--color-surface-3); border-radius: 3px; overflow: hidden; }
.hw-bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s ease; }
.hw-empty { font-size: 13px; color: var(--color-fg-faint); }
.inline-code { font-family: var(--font-mono); font-size: 12px; padding: 1px 5px; border-radius: 3px; background: var(--color-surface-3); color: var(--color-fg-muted); }
.text-success { color: var(--color-success); }
.text-muted   { color: var(--color-fg-faint); }

.allocation-empty { padding: 24px; text-align: center; color: var(--color-fg-faint); font-size: 13px; }

.alloc-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.alloc-table th { padding: 9px 16px; text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--color-fg-faint); font-family: var(--font-mono); border-bottom: 1px solid var(--color-border); font-weight: 500; }
.alloc-table td { padding: 10px 16px; border-bottom: 1px solid var(--color-border); color: var(--color-fg-muted); }
.alloc-table tbody tr:last-child td { border-bottom: none; }
.alloc-table .mono { font-family: var(--font-mono); }
.alloc-table .small { font-size: 11.5px; }

.status-chip { font-family: var(--font-mono); font-size: 10.5px; padding: 2px 8px; border-radius: 4px; }
.chip-ok  { background: color-mix(in oklch, var(--color-success) 15%, transparent); color: var(--color-success); }
.chip-off { background: var(--color-surface-2); color: var(--color-fg-faint); }

.btn-secondary { display: flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: var(--radius); border: 1px solid var(--color-border); background: transparent; color: var(--color-fg-muted); font-size: 12.5px; cursor: pointer; }
.btn-secondary:hover:not(:disabled) { background: var(--color-surface-2); color: var(--color-fg); }
.btn-secondary:disabled { opacity: 0.5; cursor: not-allowed; }
.spin { animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
