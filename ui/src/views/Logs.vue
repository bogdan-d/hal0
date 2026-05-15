<script setup>
/**
 * Logs.vue
 *
 * SSE-based realtime log tail. Filters: level (all/error/warn/info/debug),
 * slot (all + each named slot), free-text search.
 * Design: monospace terminal-style box, no fancy formatting. Lines auto-scroll
 * to bottom unless the user has scrolled up (user scroll = pause auto-scroll).
 */
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useSystemStore } from '../stores/system.js'
import { api } from '../composables/useApi.js'
import PageHeader from '../components/PageHeader.vue'
import Card from '../components/Card.vue'

const system = useSystemStore()

const lines     = ref([])
const filter    = ref({ level: 'all', slot: 'all', text: '' })
const connected = ref(false)
const loading   = ref(false)
const logboxEl  = ref(null)
const autoScroll = ref(true)

let es = null

const levelColors = {
  ERROR: 'line-error',
  WARN:  'line-warn',
  DEBUG: 'line-debug',
}

function lineClass(line) {
  if (line.includes(' ERROR ') || line.includes('[ERROR]')) return 'line-error'
  if (line.includes(' WARN ')  || line.includes('[WARN]'))  return 'line-warn'
  if (line.includes(' DEBUG ') || line.includes('[DEBUG]')) return 'line-debug'
  return ''
}

const filteredLines = computed(() => {
  let result = lines.value
  if (filter.value.level !== 'all') {
    const lvl = filter.value.level.toUpperCase()
    result = result.filter((l) => l.includes(` ${lvl} `) || l.includes(`[${lvl}]`))
  }
  if (filter.value.slot !== 'all') {
    const slotTag = filter.value.slot
    result = result.filter((l) => l.includes(slotTag))
  }
  if (filter.value.text.trim()) {
    const q = filter.value.text.toLowerCase()
    result = result.filter((l) => l.toLowerCase().includes(q))
  }
  return result
})

function buildStreamUrl() {
  const params = new URLSearchParams()
  if (filter.value.slot !== 'all') params.set('slot', filter.value.slot)
  return `/api/logs/stream?${params}`
}

async function connect() {
  disconnect()
  loading.value = true
  // Load last 500 historical lines
  try {
    const data = await api(`/api/logs?lines=500${filter.value.slot !== 'all' ? `&slot=${filter.value.slot}` : ''}`)
    lines.value = (data?.logs ?? '').split('\n').filter(Boolean)
  } catch {
    lines.value = []
  } finally {
    loading.value = false
  }

  // SSE tail
  try {
    es = new EventSource(buildStreamUrl())
    es.onopen = () => { connected.value = true }
    es.onmessage = (ev) => {
      lines.value.push(ev.data)
      if (lines.value.length > 5000) lines.value = lines.value.slice(-5000)
      if (autoScroll.value) scrollToBottom()
    }
    es.onerror = () => { connected.value = false }
  } catch {}
}

function disconnect() {
  if (es) { es.close(); es = null }
  connected.value = false
}

async function scrollToBottom() {
  await nextTick()
  if (logboxEl.value) {
    logboxEl.value.scrollTop = logboxEl.value.scrollHeight
  }
}

function onScroll() {
  if (!logboxEl.value) return
  const { scrollTop, scrollHeight, clientHeight } = logboxEl.value
  autoScroll.value = scrollHeight - scrollTop - clientHeight < 40
}

function clear() {
  lines.value = []
}

// Re-connect when slot filter changes
watch(() => filter.value.slot, () => connect())

onMounted(connect)
onUnmounted(disconnect)
</script>

<template>
  <div class="logs-page">
    <PageHeader title="Logs" subtitle="API and slot log stream">
      <template #actions>
        <div class="status-dot-wrap" :title="connected ? 'SSE connected' : 'Disconnected'" aria-label="SSE connection status">
          <span class="dot" :class="connected ? 'dot-live' : 'dot-off'" aria-hidden="true" />
          <span class="dot-label">{{ connected ? 'live' : 'offline' }}</span>
        </div>
        <button class="btn-secondary" type="button" @click="clear">Clear</button>
        <button class="btn-secondary" type="button" @click="connect">
          <svg width="13" height="13" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2" :class="{ spin: loading }" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
          </svg>
          Reconnect
        </button>
      </template>
    </PageHeader>

    <!-- Filters -->
    <div class="filters-bar">
      <label class="sr-only" for="log-level-filter">Log level</label>
      <select id="log-level-filter" v-model="filter.level" class="filter-select">
        <option value="all">All levels</option>
        <option value="error">ERROR</option>
        <option value="warn">WARN</option>
        <option value="info">INFO</option>
        <option value="debug">DEBUG</option>
      </select>

      <label class="sr-only" for="log-slot-filter">Slot</label>
      <select id="log-slot-filter" v-model="filter.slot" class="filter-select">
        <option value="all">All slots</option>
        <option value="api">API</option>
        <option v-for="s in system.slots" :key="s.name" :value="s.name">{{ s.name }}</option>
      </select>

      <label class="sr-only" for="log-text-filter">Search</label>
      <div class="search-wrap">
        <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2" class="search-icon" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-4.35-4.35M10.5 18a7.5 7.5 0 100-15 7.5 7.5 0 000 15z"/>
        </svg>
        <input
          id="log-text-filter"
          v-model="filter.text"
          class="filter-search"
          placeholder="Filter text…"
          aria-label="Filter log lines"
        />
      </div>

      <span class="line-count">{{ filteredLines.length }} lines</span>
    </div>

    <!-- Log box -->
    <div class="page-body">
      <Card :padded="false" class="logbox-card">
        <div
          ref="logboxEl"
          class="logbox"
          @scroll="onScroll"
          role="log"
          aria-live="polite"
          aria-label="Log output"
        >
          <div v-if="loading" class="logbox-loading">Loading…</div>
          <div v-else-if="filteredLines.length === 0" class="logbox-empty">No log lines match the current filter.</div>
          <div
            v-for="(line, i) in filteredLines"
            :key="i"
            class="log-line"
            :class="lineClass(line)"
          >{{ line }}</div>
        </div>

        <!-- Auto-scroll indicator -->
        <div v-if="!autoScroll" class="scroll-paused">
          <button type="button" class="scroll-resume-btn" @click="autoScroll = true; scrollToBottom()">
            ↓ Auto-scroll paused — click to resume
          </button>
        </div>
      </Card>
    </div>
  </div>
</template>

<style scoped>
.logs-page { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.page-body { padding: 0 24px 20px; flex: 1; min-height: 0; display: flex; flex-direction: column; }

.filters-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 24px;
  border-bottom: 1px solid var(--color-border);
  flex-wrap: wrap;
}
.filter-select {
  padding: 5px 8px;
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
  background: var(--color-surface-2);
  color: var(--color-fg-muted);
  font-size: 12px;
  font-family: var(--font-mono);
  cursor: pointer;
}
.filter-select:focus { outline: none; border-color: var(--color-border-hi); }

.search-wrap { position: relative; }
.search-icon { position: absolute; left: 8px; top: 50%; transform: translateY(-50%); color: var(--color-fg-faint); pointer-events: none; }
.filter-search {
  padding: 5px 8px 5px 26px;
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
  background: var(--color-surface-2);
  color: var(--color-fg);
  font-size: 12px;
  font-family: var(--font-mono);
  outline: none;
  width: 180px;
  transition: border-color 0.1s;
}
.filter-search:focus { border-color: var(--color-border-hi); }
.filter-search::placeholder { color: var(--color-fg-faint); }

.line-count { font-family: var(--font-mono); font-size: 11px; color: var(--color-fg-faint); margin-left: auto; }

/* Status dot */
.status-dot-wrap { display: flex; align-items: center; gap: 6px; }
.dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.dot-live { background: var(--color-success); box-shadow: 0 0 6px -1px var(--color-success); }
.dot-off  { background: var(--color-fg-faint); }
.dot-label { font-family: var(--font-mono); font-size: 11px; color: var(--color-fg-faint); }

/* Log box */
.logbox-card { flex: 1; display: flex; flex-direction: column; position: relative; min-height: 0; }
.logbox {
  flex: 1;
  overflow-y: auto;
  background: oklch(9% 0.01 250);
  padding: 12px 16px;
  min-height: 400px;
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.55;
}
.logbox-loading, .logbox-empty { color: var(--color-fg-faint); padding: 8px 0; }
.log-line { color: var(--color-fg-muted); white-space: pre-wrap; word-break: break-all; }
.log-line.line-error { color: var(--color-danger); }
.log-line.line-warn  { color: var(--color-warning); }
.log-line.line-debug { color: var(--color-fg-faint); }

.scroll-paused {
  position: absolute;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
}
.scroll-resume-btn {
  padding: 6px 14px;
  border-radius: var(--radius-lg);
  background: var(--color-surface-2);
  border: 1px solid var(--color-border-hi);
  color: var(--color-fg-muted);
  font-size: 11.5px;
  font-family: var(--font-mono);
  cursor: pointer;
  backdrop-filter: blur(4px);
}
.scroll-resume-btn:hover { color: var(--color-fg); }

.btn-secondary { display: flex; align-items: center; gap: 6px; padding: 5px 11px; border-radius: var(--radius); border: 1px solid var(--color-border); background: transparent; color: var(--color-fg-muted); font-size: 12px; cursor: pointer; }
.btn-secondary:hover { background: var(--color-surface-2); color: var(--color-fg); }
.spin { animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
</style>
