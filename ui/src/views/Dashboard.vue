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
const ACTIVE_STATES = new Set(['running', 'ready', 'serving'])
const slotSummary = computed(() => {
  const running = system.slots.filter((s) => ACTIVE_STATES.has(s.status)).length
  const total = system.slots.length
  return { running, total }
})

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

const diskUsedGb = computed(() => hw.value.disk_used_gb?.toFixed(0) ?? null)
const diskTotalGb = computed(() => hw.value.disk_total_gb?.toFixed(0) ?? null)
const diskPct = computed(() => {
  const u = hw.value.disk_used_gb || 0
  const t = hw.value.disk_total_gb || 0
  return t > 0 ? Math.min(100, (u / t) * 100) : 0
})

const ramUsedGb = computed(() => ((hw.value.ram_used_mb || 0) / 1024))
const ramTotalGb = computed(() => ((hw.value.ram_total_mb || 0) / 1024))
const ramPct = computed(() => {
  const t = ramTotalGb.value
  return t > 0 ? Math.min(100, (ramUsedGb.value / t) * 100) : 0
})

// ── Unified memory bar (Strix Halo: GTT + RAM + NPU + VRAM partitions) ──
// Total pool is the larger of (ram_total + gtt_total) and ram_total, since
// haloai exposes the partition explicitly. On non-UMA hardware we fall back
// to a simple RAM-only bar.
const unifiedTotalGb = computed(() => {
  const ramG = (hw.value.ram_total_mb || 0) / 1024
  const gttG = (hw.value.gtt_total_mb || 0) / 1024
  // Strix Halo reports the partition split; the host pool is the sum
  // (haloai's host.host_mem_total_mb is the authoritative figure when present).
  if (hw.value.host?.host_mem_total_mb) {
    return hw.value.host.host_mem_total_mb / 1024
  }
  return ramG + gttG
})
const unifiedSegments = computed(() => {
  const totalG = unifiedTotalGb.value || 0
  if (totalG === 0) return []
  const gtt = (hw.value.gtt_used_mb || 0) / 1024
  const sys = (hw.value.ram_used_mb || 0) / 1024
  const npuMb = hw.value.npu_status?.model_mb || 0
  const npu = npuMb / 1024
  const vram = (hw.value.vram_used_mb || 0) / 1024
  const used = gtt + sys + npu + vram
  const free = Math.max(0, totalG - used)
  const seg = (label, gb, cls) => ({
    label,
    gb,
    pct: Math.max(0, (gb / totalG) * 100),
    cls,
  })
  return [
    seg('GTT · inference', gtt, 'seg-gtt'),
    seg('System RAM', sys, 'seg-sys'),
    seg('NPU / FLM', npu, 'seg-npu'),
    seg('VRAM', vram, 'seg-vram'),
    seg('Free', free, 'seg-free'),
  ]
})

const npuOk = computed(() => !!hw.value.npu_status?.ok)
const npuLabel = computed(() => hw.value.npu_status?.npu_device || (npuOk.value ? 'Ready' : 'Offline'))

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
    offline: 'state-offline',
    unloading: 'state-offline',
  })[status] ?? 'state-offline'

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
    <PageHeader title="Dashboard" subtitle="Control Room">
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

        <Card class="stat-card">
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

        <Card class="stat-card">
          <div class="stat-label">Model storage</div>
          <div class="stat-value">
            <template v-if="diskUsedGb && diskTotalGb">
              {{ diskUsedGb }}<span class="stat-denom">/{{ diskTotalGb }} GB</span>
            </template>
            <template v-else>
              <span class="text-muted">—</span>
            </template>
          </div>
          <div class="stat-sub">
            <button class="stat-link" type="button" @click="router.push('/models')">Browse models →</button>
          </div>
        </Card>
      </div>

      <!-- ── Unified memory bar (Strix Halo) ─────────────────────── -->
      <Card v-if="unifiedSegments.length" class="um-card">
        <div class="um-head">
          <div class="um-title">Unified memory · {{ unifiedTotalGb.toFixed(0) }} GB pool</div>
          <div class="um-sub">
            {{ ((hw.gtt_used_mb || 0) / 1024 + (hw.ram_used_mb || 0) / 1024).toFixed(1) }} GB used
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

      <!-- ── Mini tiles row ───────────────────────────────────────── -->
      <div class="mini-grid">
        <Card class="mini-card">
          <div class="mini-head"><span>RAM</span><span class="dim">system</span></div>
          <div class="mini-value">{{ ramUsedGb.toFixed(1) }}<small>/{{ ramTotalGb.toFixed(0) }}G</small></div>
          <div class="mini-bar success"><span :style="{ width: ramPct + '%' }"></span></div>
        </Card>

        <Card class="mini-card">
          <div class="mini-head"><span>Disk</span><span class="dim">/mnt/ai-models</span></div>
          <div class="mini-value">{{ (hw.disk_used_gb ?? 0).toFixed(0) }}<small>/{{ (hw.disk_total_gb ?? 0).toFixed(0) }}G</small></div>
          <div class="mini-bar warning"><span :style="{ width: diskPct + '%' }"></span></div>
        </Card>

        <Card class="mini-card">
          <div class="mini-head"><span>Throughput</span><span class="dim">tok/s now</span></div>
          <div class="mini-value">{{ totalTps.toFixed(0) }}<small>tok/s</small></div>
          <svg class="mini-spark" viewBox="0 0 320 44" preserveAspectRatio="none" aria-hidden="true">
            <path :d="tputAreaPath" fill="currentColor" opacity="0.12" />
            <path :d="tputSparkPath" fill="none" stroke="currentColor" stroke-width="1.4" />
          </svg>
        </Card>

        <Card class="mini-card">
          <div class="mini-head"><span>NPU</span><span class="dim">{{ npuOk ? 'XDNA' : '—' }}</span></div>
          <div class="mini-value">
            <span :class="npuOk ? 'text-success' : 'text-muted'">{{ npuOk ? 'Ready' : 'Offline' }}</span>
          </div>
          <div class="dim mini-label">{{ npuLabel }}</div>
        </Card>
      </div>

      <!-- ── Active slots ─────────────────────────────────────────── -->
      <section aria-labelledby="slots-heading">
        <h2 id="slots-heading" class="section-title">Active slots</h2>
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
              <div class="slot-info">
                <span class="state-dot" :class="stateClass(slot.status)" aria-hidden="true" />
                <div class="slot-name-wrap">
                  <span class="slot-name">{{ slot.name }}</span>
                  <span v-if="slot.model" class="slot-model">{{ slot.model }}</span>
                </div>
              </div>
              <div class="slot-meta">
                <span class="mono-chip" v-if="slot.port">:{{ slot.port }}</span>
                <span class="state-label" :class="stateClass(slot.status)">{{ slot.status ?? 'offline' }}</span>
                <button class="slot-action-btn" type="button" @click="router.push('/slots')">Manage →</button>
              </div>
            </Card>
          </div>
        </template>
      </section>

      <!-- ── Chat panel ───────────────────────────────────────────── -->
      <section aria-labelledby="chat-heading">
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
.dashboard-page { display: flex; flex-direction: column; min-height: 100%; }
.page-body { padding: 20px 24px; display: flex; flex-direction: column; gap: 20px; }

/* ── Stat rail ──────────────────────────────────────────────────── */
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
@media (max-width: 900px) { .stat-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 480px) { .stat-grid { grid-template-columns: 1fr; } }

.stat-card { padding: 16px; }
.stat-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--color-fg-faint); font-family: var(--font-mono); margin-bottom: 6px; }
.stat-value { font-size: 28px; font-weight: 600; color: var(--color-fg); line-height: 1; margin-bottom: 6px; }
.stat-denom { font-size: 15px; color: var(--color-fg-muted); font-weight: 400; }
.stat-sub { font-size: 11.5px; color: var(--color-fg-faint); font-family: var(--font-mono); }
.stat-link { background: transparent; border: none; color: var(--color-accent); font-family: var(--font-mono); font-size: 11px; cursor: pointer; padding: 0; }
.stat-link:hover { text-decoration: underline; }

/* ── Unified memory bar ─────────────────────────────────────────── */
.um-card { padding: 16px 18px; }
.um-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; }
.um-title { font-size: 13px; font-weight: 600; color: var(--color-fg); }
.um-sub { font-size: 11.5px; color: var(--color-fg-muted); font-family: var(--font-mono); }
.um-bar { display: flex; height: 24px; border-radius: 4px; overflow: hidden; background: var(--color-surface-2); border: 1px solid var(--color-border); }
.useg { height: 100%; transition: width 0.4s ease; }
.seg-gtt   { background: var(--color-accent); }
.seg-sys   { background: var(--color-success); opacity: 0.85; }
.seg-npu   { background: var(--color-warning); opacity: 0.9; }
.seg-vram  { background: color-mix(in oklch, var(--color-accent) 50%, var(--color-warning)); }
.seg-free  { background: var(--color-surface-2); }
.um-legend { display: flex; flex-wrap: wrap; gap: 14px 18px; margin-top: 10px; font-size: 11.5px; color: var(--color-fg-muted); font-family: var(--font-mono); }
.lg { display: inline-flex; align-items: center; gap: 6px; }
.sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px; }
.lbl { color: var(--color-fg-muted); }
.lg .dim { color: var(--color-fg-faint); }
.lg small { color: var(--color-fg-faint); margin-left: 1px; }

/* ── Mini tiles ─────────────────────────────────────────────────── */
.mini-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
@media (max-width: 900px) { .mini-grid { grid-template-columns: repeat(2, 1fr); } }
.mini-card { padding: 12px 16px; min-height: 92px; }
.mini-head { display: flex; justify-content: space-between; font-size: 11px; color: var(--color-fg-faint); font-family: var(--font-mono); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px; }
.mini-value { font-size: 22px; font-weight: 600; color: var(--color-fg); line-height: 1; margin-bottom: 6px; }
.mini-value small { font-size: 12px; color: var(--color-fg-muted); font-weight: 400; margin-left: 4px; }
.mini-bar { height: 6px; border-radius: 3px; background: var(--color-surface-2); overflow: hidden; }
.mini-bar span { display: block; height: 100%; background: var(--color-accent); transition: width 0.3s ease; }
.mini-bar.success span { background: var(--color-success); }
.mini-bar.warning span { background: var(--color-warning); }
.mini-spark { width: 100%; height: 32px; color: var(--color-accent); }
.mini-label { font-size: 10.5px; font-family: var(--font-mono); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 4px; }

/* ── Sections ───────────────────────────────────────────────────── */
.section-title { font-size: 13px; font-weight: 600; color: var(--color-fg-muted); letter-spacing: 0.03em; margin: 0 0 10px; display: flex; align-items: center; gap: 12px; }
.section-link { margin-left: auto; }

/* ── Slot summary list ──────────────────────────────────────────── */
.slot-list { display: flex; flex-direction: column; gap: 6px; }
.slot-row { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; gap: 12px; }
.slot-info { display: flex; align-items: center; gap: 10px; min-width: 0; }
.state-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.state-running { background: var(--color-success); box-shadow: 0 0 6px -1px var(--color-success); }
.state-idle    { background: var(--color-warning); }
.state-error   { background: var(--color-danger); }
.state-offline { background: var(--color-fg-faint); }
.slot-name-wrap { display: flex; flex-direction: column; min-width: 0; }
.slot-name { font-size: 13px; font-weight: 600; color: var(--color-fg); }
.slot-model { font-size: 11px; color: var(--color-fg-faint); font-family: var(--font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.slot-meta { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.mono-chip { font-family: var(--font-mono); font-size: 11px; padding: 2px 7px; border-radius: 4px; background: var(--color-surface-2); border: 1px solid var(--color-border); color: var(--color-fg-faint); }
.state-label { font-family: var(--font-mono); font-size: 11px; padding: 2px 8px; border-radius: 4px; }
.state-label.state-running { background: color-mix(in oklch, var(--color-success) 15%, transparent); color: var(--color-success); }
.state-label.state-idle    { background: color-mix(in oklch, var(--color-warning) 15%, transparent); color: var(--color-warning); }
.state-label.state-error   { background: color-mix(in oklch, var(--color-danger) 15%, transparent); color: var(--color-danger); }
.state-label.state-offline { background: var(--color-surface-2); color: var(--color-fg-faint); }
.slot-action-btn { padding: 4px 10px; border-radius: var(--radius); border: 1px solid var(--color-border); background: transparent; color: var(--color-fg-muted); font-size: 11.5px; cursor: pointer; }
.slot-action-btn:hover { background: var(--color-surface-2); color: var(--color-fg); }

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
.logs-list { padding: 8px 0; max-height: 200px; overflow-y: auto; }
.log-line { padding: 3px 16px; font-family: var(--font-mono); font-size: 11.5px; color: var(--color-fg-muted); white-space: pre-wrap; word-break: break-all; border-bottom: 1px solid var(--color-border); }
.log-line:last-child { border-bottom: none; }

/* ── Utility ────────────────────────────────────────────────────── */
.dim { color: var(--color-fg-faint); }
.text-success { color: var(--color-success); }
.text-danger  { color: var(--color-danger); }
.text-muted   { color: var(--color-fg-faint); }
.mono-text    { font-family: var(--font-mono); font-size: 12px; }

.btn-primary { padding: 8px 18px; border-radius: var(--radius); background: var(--color-accent); color: var(--color-bg); font-size: 13px; font-weight: 600; border: none; cursor: pointer; flex-shrink: 0; }
.btn-primary:hover:not(:disabled) { opacity: 0.88; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-secondary { display: flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: var(--radius); border: 1px solid var(--color-border); background: transparent; color: var(--color-fg-muted); font-size: 12.5px; cursor: pointer; }
.btn-secondary:hover { background: var(--color-surface-2); color: var(--color-fg); }
</style>
