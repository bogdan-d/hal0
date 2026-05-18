<script setup>
/**
 * Dashboard.vue — Control Room (hal0).
 *
 * Layout (top to bottom):
 *   - Stat rail (API · slots · memory · model storage)
 *   - Unified memory bar (Strix Halo stacked breakdown)
 *   - Mini tiles (RAM · disk · throughput · NPU)
 *   - Active slots
 *   - Chat panel (test inference against any model)
 *   - Recent logs
 *
 * Stats arrive from /api/stats/hardware (proxied from configured upstreams)
 * via useStats; per-slot metrics from /api/slots/metrics via useSlotMetrics.
 */
import { computed, ref, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useSystemStore } from '../stores/system.js'
import { useStats, useSlotMetrics } from '../composables/useStats.js'
import { useSlotStats, isSlotServing } from '../composables/useSlotStats.js'
import { api } from '../composables/useApi.js'
import PageHeader from '../components/PageHeader.vue'
import Card from '../components/Card.vue'
import LoadingSkeleton from '../components/LoadingSkeleton.vue'
import EmptyState from '../components/EmptyState.vue'

const router = useRouter()
const system = useSystemStore()
const { stats } = useStats(2500)
const { metrics, aggHistory } = useSlotMetrics(2500)

const hw = computed(() => stats.value || {})

// ── Slot summary ─────────────────────────────────────────────────────
const { running: slotsRunning, total: slotsTotal } = useSlotStats()
const slotSummary = computed(() => ({ running: slotsRunning.value, total: slotsTotal.value }))

// ── Memory tiles — prefer GTT (unified) when present, else VRAM ──────
const memUsedGb = computed(() => {
  if (hw.value.gtt_used_mb) return (hw.value.gtt_used_mb / 1024).toFixed(1)
  if (hw.value.vram_used_mb) return (hw.value.vram_used_mb / 1024).toFixed(1)
  return null
})
const memTotalGb = computed(() => {
  if (hw.value.gtt_total_mb) return (hw.value.gtt_total_mb / 1024).toFixed(0)
  if (hw.value.vram_total_mb) return (hw.value.vram_total_mb / 1024).toFixed(0)
  return null
})
const memLabel = computed(() => (hw.value.gtt_total_mb ? 'GTT' : 'VRAM'))

// ── Unified memory bar (Strix Halo: one physical pool, multiple consumers) ──
// On AMD UMA, GTT *is* system RAM — they share the same DIMMs. Summing
// ram_total + gtt_total would double-count, which is what produced the
// "169 GB pool on a 128 GB machine" bug. The probe exposes the true
// unified_memory_mb (via dmidecode when /proc/meminfo reports an LXC
// cgroup quota); we trust that. host.host_mem_total_mb is the haloai
// upstream's equivalent.
const unifiedTotalGb = computed(() => {
  const probed = hw.value.unified_memory_mb || hw.value.host?.host_mem_total_mb
  if (probed) return probed / 1024
  // Non-UMA / unknown: RAM + dedicated VRAM is a fair total (no overlap).
  const ramG = (hw.value.ram_total_mb || 0) / 1024
  const vramG = (hw.value.vram_total_mb || 0) / 1024
  return ramG + vramG
})

const unifiedSegments = computed(() => {
  const totalG = unifiedTotalGb.value || 0
  if (totalG === 0) return []
  // Used breakdown:
  //   gtt   = GPU's GTT allocations (live model weights / KV cache on UMA)
  //   npu   = NPU model resident bytes (also drawn from the unified pool)
  //   vram  = dedicated VRAM in use (discrete GPUs only — 0 on UMA)
  //   sys   = system RAM used by everything else (MemTotal - MemAvailable
  //           minus what's already attributed to the GPU through GTT)
  const gtt = (hw.value.gtt_used_mb || 0) / 1024
  const vram = (hw.value.vram_used_mb || 0) / 1024
  const npuMb = hw.value.npu_status?.model_mb || 0
  const npu = npuMb / 1024
  // ram_used_gb is from /api/stats/hardware (haloai shape) — it's the OS-
  // visible used total, which already includes pinned GTT bytes on UMA.
  // Subtract gtt so we don't double-count GTT into both buckets.
  const ramUsedG = hw.value.ram_used_gb ?? ((hw.value.ram_total_mb || 0) - (hw.value.ram_available_mb || 0)) / 1024
  const sys = Math.max(0, ramUsedG - gtt)
  const used = gtt + sys + npu + vram
  const free = Math.max(0, totalG - used)
  const seg = (label, gb, cls) => ({
    label,
    gb,
    pct: Math.max(0, (gb / totalG) * 100),
    cls,
  })
  const out = [
    seg('GTT · inference', gtt, 'seg-gtt'),
    seg('System RAM', sys, 'seg-sys'),
    seg('NPU / FLM', npu, 'seg-npu'),
  ]
  // Hide the VRAM segment on UMA — it's always 0 and just clutters the legend.
  if (vram > 0.01) out.push(seg('VRAM', vram, 'seg-vram'))
  out.push(seg('Free', free, 'seg-free'))
  return out
})

// Prefer upstream-reported NPU readiness (haloai proxies it through
// /api/stats/hardware as npu_status.ok). Falls back to the local probe's
// npu_present so the single-LXC deployment — which has no upstreams to
// proxy from — still lights up when amdxdna + /dev/accel are present.
const npuOk = computed(() => hw.value.npu_status?.ok ?? !!hw.value.npu_present)

// ── Throughput ────────────────────────────────────────────────────────
const totalTps = computed(() =>
  Object.values(metrics.value).reduce((a, m) => a + (m?.tokens_per_sec ?? m?.tps ?? 0), 0),
)
const tputSparkPath = computed(() => {
  const series = aggHistory.value.tps
  if (!series.length) return ''
  const max = Math.max(1, ...series)
  const n = series.length
  const pts = series.map((v, i) => {
    const x = (i / Math.max(1, n - 1)) * 320
    const y = 44 - (v / max) * 40 - 2
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
  })
  return pts.join(' ')
})
const tputAreaPath = computed(() => {
  const line = tputSparkPath.value
  if (!line) return ''
  return `${line} L320,44 L0,44 Z`
})

// ── API health ───────────────────────────────────────────────────────
const apiOk = computed(() => !system.error && system.status !== null)
const recentLogs = computed(() => system.status?.recent_logs ?? [])

const stateClass = (status) =>
  ({
    running: 'state-running',
    ready: 'state-running',
    serving: 'state-running',
    idle: 'state-idle',
    warming: 'state-idle',
    starting: 'state-idle',
    pulling: 'state-idle',
    error: 'state-error',
    'no model': 'state-warn',
    offline: 'state-offline',
    unloading: 'state-offline',
  })[status] ?? 'state-offline'

// ── Slot-row helpers ─────────────────────────────────────────────────
// Mirrored from SlotCard.vue (not imported — the dashboard row is the
// compact denser cousin). Keep these in sync if SlotCard.vue's
// equivalents change. `slotRunning` uses the shared isSlotServing
// predicate so a slot stuck in ready/serving without a model is
// reported as not-running — matching the navbar/sidebar count.
const slotRunning = (slot) => isSlotServing(slot)

// State label shown in the row. When the state machine reports an
// active state (ready/serving) but the slot has no model loaded and
// isn't a self-managed provider, the surface state is a lie — render
// "no model" so the row stops contradicting itself.
function slotDisplayState(slot) {
  const raw = slot?.status ?? 'offline'
  if (['ready', 'serving', 'running'].includes(raw) && !isSlotServing(slot)) {
    return 'no model'
  }
  return raw
}

// Hardware-target mapping: backend/provider → human chip. Same buckets
// as SlotCard's hardwareTarget computed.
function hardwareTarget(slot) {
  const backend = (slot?.backend || '').toLowerCase()
  const provider = (slot?.provider || '').toLowerCase()
  if (backend === 'flm' || provider === 'flm') return { id: 'npu', label: 'NPU' }
  if (backend === 'cuda' || backend === 'rocm') return { id: 'gpu', label: 'GPU' }
  if (backend === 'vulkan' || backend === 'metal') return { id: 'igpu', label: 'iGPU' }
  if (backend === 'cpu') return { id: 'cpu', label: 'CPU' }
  if (provider === 'kokoro' || provider === 'moonshine') return { id: 'igpu', label: 'iGPU' }
  return { id: 'unknown', label: backend || provider || 'slot' }
}

// Model label with the same fallback chain SlotCard uses, truncated
// shorter to fit the dense single-line row.
function modelLabel(slot) {
  const raw = slot?.model_name || slot?.model || slot?.model_id || ''
  const s = typeof raw === 'string' ? raw : (raw?.default ?? '')
  if (!s) return 'no model'
  return s.length > 28 ? s.slice(0, 26) + '…' : s
}

// Per-slot metric formatters. Backend doesn't yet expose ttft directly;
// show em-dash so the chip layout stays stable when the field lands.
function slotTps(name) {
  const v = metrics.value[name]?.tokens_per_sec ?? metrics.value[name]?.tps
  return v ? `${v.toFixed(1)} tok/s` : '— tok/s'
}
function slotTtft(name) {
  const m = metrics.value[name] || {}
  const v = m.ttft_ms ?? m.first_token_ms ?? m.time_to_first_token_ms
  return v ? `${Math.round(v)}ms` : '— ms'
}
function slotMem(name) {
  const m = metrics.value[name] || {}
  const mb = m.mem_rss_mb ?? m.rss_mb ?? m.gtt_mb ?? m.vram_mb
  if (!mb || mb <= 0) return '— GB'
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)}GB` : `${mb.toFixed(0)}MB`
}

// ── Chat panel ───────────────────────────────────────────────────────
const chatModels = ref([])
const chatModel = ref('')
const chatPrompt = ref('')
const chatOutput = ref('')
const chatBusy = ref(false)
const chatError = ref(null)
const chatOutputEl = ref(null)

async function loadChatModels() {
  try {
    const r = await api('/v1/models')
    chatModels.value = (r?.data || []).map((m) => m.id)
    if (!chatModel.value && chatModels.value.length) {
      // Prefer a small fast model for the first interaction.
      const preferred = chatModels.value.find((m) =>
        ['gemma3:1b', 'qwen3:0.6b', 'llama3.2:1b', 'lfm2:1.2b'].includes(m),
      )
      chatModel.value = preferred || chatModels.value[0]
    }
  } catch (e) {
    chatError.value = e?.message ?? String(e)
  }
}

async function runChat() {
  if (!chatPrompt.value.trim() || !chatModel.value) return
  chatBusy.value = true
  chatError.value = null
  chatOutput.value = ''
  try {
    const resp = await fetch('/v1/chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        model: chatModel.value,
        messages: [{ role: 'user', content: chatPrompt.value }],
        stream: true,
        max_tokens: 512,
      }),
    })
    if (!resp.ok) {
      const txt = await resp.text()
      try {
        const j = JSON.parse(txt)
        throw new Error(j?.error?.message || `HTTP ${resp.status}`)
      } catch {
        throw new Error(`HTTP ${resp.status}: ${txt.slice(0, 200)}`)
      }
    }
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let idx
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const event = buffer.slice(0, idx).trim()
        buffer = buffer.slice(idx + 2)
        if (!event.startsWith('data:')) continue
        const data = event.slice(5).trim()
        if (data === '[DONE]') continue
        try {
          const j = JSON.parse(data)
          const delta = j?.choices?.[0]?.delta?.content
          if (delta) {
            chatOutput.value += delta
            await nextTick()
            if (chatOutputEl.value) {
              chatOutputEl.value.scrollTop = chatOutputEl.value.scrollHeight
            }
          }
        } catch {
          /* ignore partial JSON */
        }
      }
    }
  } catch (e) {
    chatError.value = e?.message ?? String(e)
  } finally {
    chatBusy.value = false
  }
}

loadChatModels()
</script>

<template>
  <div class="dashboard-page">
    <div class="dashboard-hero" aria-hidden="true"></div>
    <PageHeader eyebrow="Control Room" title="Dashboard" subtitle="Live status of your hal0 box.">
      <template #actions>
        <button class="btn-secondary" type="button" @click="system.fetchStatus()">
          <svg width="13" height="13" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Refresh
        </button>
      </template>
    </PageHeader>

    <div class="page-body">
      <!-- ── Stat rail ───────────────────────────────────────────── -->
      <div class="stat-grid">
        <Card class="stat-card">
          <div class="stat-label">API status</div>
          <div class="stat-value" :class="apiOk ? 'text-success' : 'text-danger'">
            {{ apiOk ? 'Online' : 'Unreachable' }}
          </div>
          <div class="stat-sub">
            {{ system.loading ? 'Checking…' : (system.status?.version ? `v${system.status.version}` : 'unknown') }}
          </div>
        </Card>

        <Card class="stat-card" :highlight="slotSummary.running > 0">
          <div class="stat-label">Slots running</div>
          <div class="stat-value">
            <template v-if="system.loading && system.slots.length === 0">
              <LoadingSkeleton :lines="1" height="28px" />
            </template>
            <template v-else>
              {{ slotSummary.running }}<span class="stat-denom">/{{ slotSummary.total }}</span>
            </template>
          </div>
          <div class="stat-sub">
            <button class="stat-link" type="button" @click="router.push('/slots')">Manage slots →</button>
          </div>
        </Card>

        <Card class="stat-card">
          <div class="stat-label">{{ memLabel }} memory</div>
          <div class="stat-value">
            <template v-if="memUsedGb && memTotalGb">
              {{ memUsedGb }}<span class="stat-denom">/{{ memTotalGb }} GB</span>
            </template>
            <template v-else>
              <span class="text-muted">—</span>
            </template>
          </div>
          <div class="stat-sub">
            <button class="stat-link" type="button" @click="router.push('/hardware')">Hardware details →</button>
          </div>
        </Card>

        <Card class="stat-card stat-tput">
          <div class="stat-label">Throughput</div>
          <div class="stat-value">
            {{ totalTps.toFixed(0) }}<span class="stat-denom">tok/s</span>
          </div>
          <svg class="stat-spark" viewBox="0 0 320 36" preserveAspectRatio="none" aria-hidden="true">
            <path :d="tputAreaPath" fill="currentColor" opacity="0.12" />
            <path :d="tputSparkPath" fill="none" stroke="currentColor" stroke-width="1.4" />
          </svg>
        </Card>
      </div>

      <!-- ── Unified memory bar (Strix Halo) ─────────────────────── -->
      <Card v-if="unifiedSegments.length" class="um-card">
        <div class="um-head">
          <div class="um-title">Unified memory · {{ unifiedTotalGb.toFixed(0) }} GB pool</div>
          <div class="um-sub">
            {{ unifiedSegments.filter(s => s.cls !== 'seg-free').reduce((a, s) => a + s.gb, 0).toFixed(1) }} GB used
            <span class="dim"> · NPU {{ npuOk ? 'ready' : 'offline' }}</span>
          </div>
        </div>
        <div class="um-bar" role="img" aria-label="Unified memory breakdown">
          <div
            v-for="seg in unifiedSegments"
            :key="seg.label"
            class="useg"
            :class="seg.cls"
            :style="{ width: seg.pct + '%' }"
            :title="`${seg.label}: ${seg.gb.toFixed(1)} GB`"
          ></div>
        </div>
        <div class="um-legend">
          <span v-for="seg in unifiedSegments" :key="seg.label" class="lg">
            <span class="sw" :class="seg.cls"></span>
            <span class="lbl">{{ seg.label }}</span>
            <span class="dim">{{ seg.gb.toFixed(1) }}<small>GB</small></span>
          </span>
        </div>
      </Card>

      <!-- ── Active slots ─────────────────────────────────────────── -->
      <section aria-labelledby="slots-heading">
        <p class="section-eyebrow"><span class="section-eyebrow-dot" aria-hidden="true"></span> Slots</p>
        <h2 id="slots-heading" class="section-title">Slots</h2>
        <template v-if="system.loading && system.slots.length === 0">
          <div class="slot-list">
            <Card v-for="i in 3" :key="i"><LoadingSkeleton :lines="3" /></Card>
          </div>
        </template>
        <template v-else-if="system.slots.length === 0">
          <Card :padded="false">
            <EmptyState
              title="No slots configured"
              description="Create a slot to start serving inference requests."
              cta-label="Go to Slots"
              @cta="router.push('/slots')"
            />
          </Card>
        </template>
        <template v-else>
          <div class="slot-list">
            <Card v-for="slot in system.slots" :key="slot.name" class="slot-row" :padded="false">
              <div class="slot-row-main">
                <span class="state-dot" :class="stateClass(slotDisplayState(slot))" aria-hidden="true" />
                <span class="state-label" :class="stateClass(slotDisplayState(slot))">{{ slotDisplayState(slot) }}</span>
                <span class="slot-name">{{ slot.name }}</span>
                <span
                  class="slot-model mono"
                  :class="{ 'needs-model': !(slot.model_name || slot.model || slot.model_id) }"
                  :title="(slot.model_name || slot.model || slot.model_id) || 'No default model — set one in /etc/hal0/slots/' + slot.name + '.toml or via the Slots page'"
                >{{ modelLabel(slot) }}</span>
                <span class="hw-chip" :class="`hw-${hardwareTarget(slot).id}`">{{ hardwareTarget(slot).label }}</span>
                <span v-if="slot.port" class="mono-chip">:{{ slot.port }}</span>
                <button class="slot-action-btn" type="button" @click="router.push('/slots')">Manage →</button>
              </div>
              <div class="slot-row-stats" :class="{ dim: !slotRunning(slot) }">
                <span class="stat-chip" :title="`Tokens per second from /api/slots/metrics`">{{ slotTps(slot.name) }}</span>
                <span class="stat-chip-sep">·</span>
                <span class="stat-chip" :title="`Time to first token (not yet emitted by backend — placeholder)`">{{ slotTtft(slot.name) }}</span>
                <span class="stat-chip-sep">·</span>
                <span class="stat-chip" :title="`Resident memory (RSS or GTT)`">{{ slotMem(slot.name) }}</span>
              </div>
            </Card>
          </div>
        </template>
      </section>

      <!-- ── Chat panel ───────────────────────────────────────────── -->
      <section aria-labelledby="chat-heading">
        <p class="section-eyebrow"><span class="section-eyebrow-dot" aria-hidden="true"></span> /v1/chat</p>
        <h2 id="chat-heading" class="section-title">Test chat</h2>
        <Card class="chat-card">
          <div class="chat-row">
            <select v-model="chatModel" class="chat-model">
              <option v-if="!chatModels.length" value="">No models</option>
              <option v-for="m in chatModels" :key="m" :value="m">{{ m }}</option>
            </select>
            <input
              v-model="chatPrompt"
              class="chat-input"
              placeholder="Ask the model anything…"
              @keydown.enter="runChat"
              :disabled="chatBusy"
            />
            <button
              class="btn-primary chat-send"
              type="button"
              :disabled="chatBusy || !chatPrompt.trim() || !chatModel"
              @click="runChat"
            >
              {{ chatBusy ? 'Streaming…' : 'Send' }}
            </button>
          </div>
          <div ref="chatOutputEl" class="chat-output" :class="{ empty: !chatOutput && !chatError }">
            <span v-if="chatError" class="text-danger">{{ chatError }}</span>
            <span v-else-if="chatOutput">{{ chatOutput }}</span>
            <span v-else class="text-muted mono-text">Response appears here · streaming SSE from /v1/chat/completions</span>
          </div>
        </Card>
      </section>

      <!-- ── Recent logs ──────────────────────────────────────────── -->
      <section aria-labelledby="logs-heading">
        <p class="section-eyebrow"><span class="section-eyebrow-dot" aria-hidden="true"></span> Journal</p>
        <h2 id="logs-heading" class="section-title">
          Recent log events
          <button class="stat-link section-link" type="button" @click="router.push('/logs')">View all →</button>
        </h2>
        <Card :padded="false">
          <div v-if="recentLogs.length === 0" class="logs-empty">
            <span class="text-muted mono-text">No recent log events.</span>
          </div>
          <div v-else class="logs-list">
            <div v-for="(line, i) in recentLogs.slice(-10)" :key="i" class="log-line">{{ line }}</div>
          </div>
        </Card>
      </section>
    </div>
  </div>
</template>

<style scoped>
.dashboard-page { position: relative; display: flex; flex-direction: column; min-height: 100%; }
.page-body { padding: 20px 24px; display: flex; flex-direction: column; gap: 20px; position: relative; z-index: 1; }

/* Hero glow — radial amber wash behind the page title, mirroring
   the HeroSection on hal0-web. Pointer-events none so it never
   blocks the refresh button. */
.dashboard-hero {
  position: absolute;
  inset: 0 0 auto 0;
  height: 220px;
  pointer-events: none;
  background: radial-gradient(ellipse at top, var(--hal0-accent-glow), transparent 70%);
  z-index: 0;
}

/* ── Stat rail ──────────────────────────────────────────────────── */
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
@media (max-width: 900px) { .stat-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 480px) { .stat-grid { grid-template-columns: 1fr; } }

.stat-card { padding: 16px; }
.stat-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--hal0-accent); font-family: var(--font-mono); margin-bottom: 8px; font-weight: 500; }
.stat-value { font-family: var(--font-mono); font-size: 26px; font-weight: 600; color: var(--color-fg); line-height: 1.1; margin-bottom: 6px; letter-spacing: -0.02em; font-feature-settings: 'zero' 1, 'ss02' 1, 'tnum' 1; }
.stat-denom { font-size: 14px; color: var(--color-fg-muted); font-weight: 400; margin-left: 2px; }
.stat-sub { font-size: 11.5px; color: var(--color-fg-faint); font-family: var(--font-mono); }
.stat-link { background: transparent; border: none; color: var(--hal0-accent); font-family: var(--font-mono); font-size: 11px; cursor: pointer; padding: 0; }
.stat-link:hover { text-decoration: underline; }
.stat-tput { display: flex; flex-direction: column; }
.stat-tput .stat-value { margin-bottom: 4px; }
.stat-tput .stat-denom { margin-left: 4px; font-size: 13px; }
.stat-spark { width: 100%; height: 30px; color: var(--hal0-accent); margin-top: auto; }

/* ── Unified memory bar ─────────────────────────────────────────── */
.um-card { padding: 16px 18px; }
.um-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; }
.um-title { font-family: var(--font-mono); font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; font-weight: 500; color: var(--hal0-accent); }
.um-sub { font-size: 11.5px; color: var(--color-fg-muted); font-family: var(--font-mono); font-feature-settings: 'zero' 1, 'ss02' 1, 'tnum' 1; }
.um-bar { display: flex; height: 24px; border-radius: 4px; overflow: hidden; background: var(--color-surface-2); border: 1px solid var(--color-border); }
.useg { height: 100%; transition: width 0.4s ease; }
.seg-gtt   { background: var(--hal0-accent); }
.seg-sys   { background: var(--color-success); opacity: 0.85; }
.seg-npu   { background: var(--color-warning); opacity: 0.9; }
.seg-vram  { background: color-mix(in oklch, var(--hal0-accent) 50%, var(--color-warning)); }
.seg-free  { background: var(--color-surface-2); }
.um-legend { display: flex; flex-wrap: wrap; gap: 14px 18px; margin-top: 10px; font-size: 11.5px; color: var(--color-fg-muted); font-family: var(--font-mono); font-feature-settings: 'zero' 1, 'ss02' 1, 'tnum' 1; }
.lg { display: inline-flex; align-items: center; gap: 6px; }
.sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px; }
.lbl { color: var(--color-fg-muted); }
.lg .dim { color: var(--color-fg-faint); }
.lg small { color: var(--color-fg-faint); margin-left: 1px; }

/* ── Sections ───────────────────────────────────────────────────── */
.section-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin: 0 0 6px;
  font-family: var(--font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--hal0-accent);
  font-weight: 500;
}
.section-eyebrow-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--hal0-accent);
  box-shadow: 0 0 6px var(--hal0-accent);
}
.section-title { font-size: 16px; font-weight: 600; color: var(--color-fg); letter-spacing: -0.01em; margin: 0 0 12px; display: flex; align-items: center; gap: 12px; }
.section-link { margin-left: auto; font-size: 11px; }

/* ── Slot summary list ──────────────────────────────────────────── */
/* Dense two-line row: top has identity + chips + Manage; bottom has
   the per-slot metric strip (tok/s · ttft · mem). Mirrors SlotCard's
   identity surface without committing to the full card grid. */
.slot-list { display: flex; flex-direction: column; gap: 6px; }
.slot-row { display: flex; flex-direction: column; padding: 10px 14px 8px; gap: 4px; }
.slot-row-main { display: flex; align-items: center; gap: 10px; min-width: 0; }
.state-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.state-running { background: var(--hal0-accent); box-shadow: 0 0 8px var(--hal0-accent); }
.state-idle    { background: var(--color-warning); }
.state-error   { background: var(--color-danger); }
.state-warn    { background: var(--color-warning); }
.state-offline { background: var(--color-fg-faint); }
.slot-name { font-family: var(--font-mono); font-size: 13px; font-weight: 600; color: var(--color-fg); flex-shrink: 0; }
.slot-model { font-size: 11.5px; color: var(--color-fg-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; flex: 1; }
.slot-model.needs-model { color: var(--color-warning); font-style: italic; }
.mono-chip { font-family: var(--font-mono); font-size: 11px; padding: 2px 7px; border-radius: 4px; background: var(--color-surface-2); border: 1px solid var(--color-border); color: var(--color-fg-faint); font-feature-settings: 'zero' 1, 'ss02' 1, 'tnum' 1; flex-shrink: 0; }
.state-label { font-family: var(--font-mono); font-size: 10.5px; padding: 2px 8px; border-radius: 4px; text-transform: uppercase; letter-spacing: 0.06em; flex-shrink: 0; }
.state-label.state-running { background: color-mix(in srgb, var(--hal0-accent) 14%, transparent); color: var(--hal0-accent); }
.state-label.state-idle    { background: color-mix(in oklch, var(--color-warning) 15%, transparent); color: var(--color-warning); }
.state-label.state-error   { background: color-mix(in oklch, var(--color-danger) 15%, transparent); color: var(--color-danger); }
.state-label.state-warn    { background: color-mix(in oklch, var(--color-warning) 15%, transparent); color: var(--color-warning); }
.state-label.state-offline { background: var(--color-surface-2); color: var(--color-fg-faint); }
.slot-action-btn { padding: 4px 10px; border-radius: var(--radius); border: 1px solid var(--color-border); background: transparent; color: var(--color-fg-muted); font-size: 11.5px; cursor: pointer; flex-shrink: 0; margin-left: auto; }
.slot-action-btn:hover { background: var(--color-surface-2); color: var(--color-fg); }

/* Hardware chip — same colour buckets SlotCard uses, slimmer for the
   inline row. NPU amber, GPU red, iGPU green, CPU muted. */
.hw-chip { font-family: var(--font-mono); font-size: 10px; padding: 2px 6px; border-radius: 4px; letter-spacing: 0.04em; border: 1px solid var(--color-border); background: var(--color-surface-2); color: var(--color-fg-muted); flex-shrink: 0; }
.hw-chip.hw-npu  { color: var(--color-warning); border-color: color-mix(in oklch, var(--color-warning), transparent 60%); background: color-mix(in oklch, var(--color-warning), transparent 88%); }
.hw-chip.hw-gpu  { color: var(--color-danger);  border-color: color-mix(in oklch, var(--color-danger),  transparent 60%); background: color-mix(in oklch, var(--color-danger),  transparent 88%); }
.hw-chip.hw-igpu { color: var(--color-success); border-color: color-mix(in oklch, var(--color-success), transparent 60%); background: color-mix(in oklch, var(--color-success), transparent 88%); }
.hw-chip.hw-cpu  { color: var(--color-fg-muted); border-color: var(--color-border-hi); }
.hw-chip.hw-unknown { opacity: 0.6; text-transform: lowercase; }

/* Metric strip — aligned under the model name so the eye scans
   identity → live numbers without crossing to a separate region. */
.slot-row-stats { display: flex; align-items: center; gap: 8px; padding-left: 18px; font-family: var(--font-mono); font-size: 11.5px; color: var(--color-fg-muted); font-feature-settings: 'zero' 1, 'ss02' 1, 'tnum' 1; }
.slot-row-stats.dim { color: var(--color-fg-faint); opacity: 0.7; }
.stat-chip { white-space: nowrap; }
.stat-chip-sep { color: var(--color-fg-faint); opacity: 0.6; }

/* ── Chat panel ─────────────────────────────────────────────────── */
.chat-card { padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.chat-row { display: flex; gap: 8px; align-items: stretch; }
.chat-model { padding: 6px 10px; font-size: 12px; font-family: var(--font-mono); background: var(--color-surface-2); border: 1px solid var(--color-border); border-radius: var(--radius); color: var(--color-fg); min-width: 160px; }
.chat-input { flex: 1; padding: 6px 12px; font-size: 13px; background: var(--color-surface-2); border: 1px solid var(--color-border); border-radius: var(--radius); color: var(--color-fg); }
.chat-input:focus, .chat-model:focus { outline: 2px solid var(--color-accent); outline-offset: 1px; }
.chat-send { padding: 6px 16px; flex-shrink: 0; }
.chat-output { min-height: 80px; max-height: 260px; overflow-y: auto; padding: 10px 12px; background: var(--color-surface-2); border: 1px solid var(--color-border); border-radius: var(--radius); font-size: 13px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
.chat-output.empty { display: flex; align-items: center; min-height: 60px; }

/* ── Logs ───────────────────────────────────────────────────────── */
.logs-empty { padding: 20px 16px; display: flex; align-items: center; }
.logs-list { padding: 8px 0; max-height: 200px; overflow-y: auto; background: var(--hal0-bg-sunken); }
.log-line { padding: 3px 16px; font-family: var(--font-mono); font-size: 11.5px; color: var(--hal0-fg-dim); white-space: pre-wrap; word-break: break-all; border-bottom: 1px solid var(--color-border); }
.log-line:last-child { border-bottom: none; }

/* ── Utility ────────────────────────────────────────────────────── */
.dim { color: var(--color-fg-faint); }
.text-success { color: var(--color-success); }
.text-danger  { color: var(--color-danger); }
.text-muted   { color: var(--color-fg-faint); }
.mono-text    { font-family: var(--font-mono); font-size: 12px; }

.btn-primary { padding: 8px 18px; border-radius: var(--radius); background: var(--hal0-accent); color: #000; font-family: var(--font-mono); font-size: 12px; font-weight: 500; border: none; cursor: pointer; flex-shrink: 0; transition: background 0.15s; }
.btn-primary:hover:not(:disabled) { background: var(--hal0-accent-hover); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-secondary { display: flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: var(--radius); border: 1px solid var(--color-border); background: transparent; color: var(--color-fg-muted); font-family: var(--font-mono); font-size: 12px; cursor: pointer; transition: border-color 0.15s, color 0.15s; }
.btn-secondary:hover { border-color: var(--color-border-hi); color: var(--color-fg); }
</style>
